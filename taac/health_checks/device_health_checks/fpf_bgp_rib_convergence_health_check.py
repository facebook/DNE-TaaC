# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import json
import time
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.libs.fpf.fpf_collector_registry import (
    DEFAULT_SIGNAL1_E2E_MAX_SEC,
    DEFAULT_SIGNAL2_LOCAL_MAX_SEC,
    DEFAULT_SIGNAL3_STABILITY_DURATION_SEC,
    evaluate_three_signals,
    everpaste_details_suffix,
    get_collector,
    get_disruption_time,
    get_test_case_start_time,
    wait_for_restart_reconverge,
    wait_for_target_rib_rows,
)
from taac.libs.fpf.fpf_stress_checks import (
    _parse_ts,
    BLIP_MODE_SKIP_NULL_STRICT,
)
from taac.libs.fpf.fpf_thresholds import (
    ACTIVE as FPF_ACTIVE_THRESHOLDS,
)
from taac.health_check.health_check import types as hc_types

JSONL_PATH = "/tmp/fpf_stress_bgp_rib.jsonl"


def _target_timeout_attribution(
    collector: t.Any,
    target_devices: t.Iterable[str],
    window_start: float,
    window_end: float,
) -> t.Tuple[t.Dict[str, int], t.List[str]]:
    """Attribute completed BGP timeouts by request start, not row publication.

    A request that started before the current playbook but completed inside its
    window belongs to the previous boundary and is excluded. A request that
    started inside the window is charged to the current playbook. Collectors
    without request telemetry retain the legacy completion-timestamp fallback.
    """
    targets = set(target_devices)
    counts = dict.fromkeys(targets, 0)
    telemetry_hosts: t.Set[str] = set()
    boundary_notes: t.List[str] = []
    for row in getattr(collector, "rows", []):
        device = str(getattr(row, "gtsw", ""))
        notes = str(getattr(row, "notes", "") or "")
        if device not in targets or not notes.startswith("error: poll timeout"):
            continue
        request_start = float(getattr(row, "request_start_epoch", 0.0) or 0.0)
        request_end = float(getattr(row, "request_end_epoch", 0.0) or 0.0)
        if request_start <= 0:
            continue
        telemetry_hosts.add(device)
        if window_start <= request_start <= window_end:
            counts[device] += 1
            boundary_notes.append(
                f"charged {device} timeout to current window "
                f"({request_start:.3f}->{request_end:.3f})"
            )
        elif request_start < window_start <= request_end:
            boundary_notes.append(
                f"excluded {device} timeout started before window "
                f"({request_start:.3f}->{request_end:.3f})"
            )

    host_timeout_timestamps = getattr(collector, "host_timeout_timestamps", {})
    if not isinstance(host_timeout_timestamps, dict):
        host_timeout_timestamps = {}
    for device in targets - telemetry_hosts:
        counts[device] = len(
            [
                ts
                for ts in host_timeout_timestamps.get(device, [])
                if window_start <= ts <= window_end
            ]
        )
    return counts, boundary_notes


class FpfBgpRibConvergenceHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    """Postcheck: evaluate BGP RIB convergence from collector data.

    When ``use_live_collectors`` is True in check_params, queries the live
    BGP RIB collector via the module-level registry using
    ``window_start``/``window_end`` timestamps for time-windowed assessment.

    Otherwise falls back to reading ``/tmp/fpf_stress_bgp_rib.jsonl``.
    """

    CHECK_NAME = hc_types.CheckName.FPF_BGP_RIB_CONVERGENCE_CHECK
    CHECK_SCOPE = hc_types.Scope.DEFAULT
    OPERATING_SYSTEMS = ["FBOSS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        lane_map: t.Dict[int, str] = {
            int(k): v for k, v in check_params.get("lane_map", {}).items()
        }
        expected = check_params.get("expected_matched", 20000)
        use_live = check_params.get("use_live_collectors", False)

        if not lane_map:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message="No lane_map in check_params",
            )

        if use_live:
            return await self._evaluate_from_live_collector(
                lane_map, expected, check_params
            )

        return self._evaluate_from_jsonl(lane_map, expected, check_params)

    async def _evaluate_from_live_collector(
        self,
        lane_map: t.Dict[int, str],
        expected: int,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        collector = get_collector("bgp")
        if collector is None:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message="No live BGP collector in registry",
            )

        if check_params.get("mode") == "restart":
            return await self._evaluate_restart_reconverge(
                collector,
                lane_map,
                expected,
                check_params,
                default_sla_sec=FPF_ACTIVE_THRESHOLDS.bgp_restart_reconverge_sla_sec,
            )

        explicit_window_end = check_params.get("window_end")
        window_end = (
            float(explicit_window_end)
            if explicit_window_end is not None
            else time.time()
        )
        tc_start = get_test_case_start_time()
        lookback_sec = check_params.get("lookback_sec", 900)
        window_start = check_params.get(
            "window_start", tc_start if tc_start else window_end - lookback_sec
        )
        # settle_sec: skip the first N seconds (restore/recovery phase) so the
        # GTSW RIB re-converge transient on undrain/re-enable isn't measured as
        # post-convergence instability.
        settle_sec = float(check_params.get("settle_sec", 0))
        if settle_sec > 0:
            window_start = min(window_start + settle_sec, window_end)

        signal1_max = check_params.get(
            "signal1_e2e_max_sec", DEFAULT_SIGNAL1_E2E_MAX_SEC
        )
        signal2_max = check_params.get(
            "signal2_local_max_sec", DEFAULT_SIGNAL2_LOCAL_MAX_SEC
        )
        signal3_duration = check_params.get(
            "signal3_stability_duration_sec", DEFAULT_SIGNAL3_STABILITY_DURATION_SEC
        )
        stability_mode = check_params.get("stability_mode", "strict")

        if stability_mode == BLIP_MODE_SKIP_NULL_STRICT and explicit_window_end is None:
            window_end = await wait_for_target_rib_rows(
                collector=collector,
                target_devices=lane_map.values(),
                window_start=float(window_start),
                deadline=float(window_start) + float(signal1_max),
                poll_interval_sec=float(
                    check_params.get("target_row_poll_interval_sec", 1.0)
                ),
            )

        self.logger.info(
            f"  [BGP RIB live] Evaluating window: "
            f"{window_start:.0f} to {window_end:.0f} "
            f"({window_end - window_start:.0f}s span)"
        )

        per_lane_results = collector.evaluate_per_device_window(
            window_start=window_start,
            window_end=window_end,
            lane_map=lane_map,
            expected_matched=expected,
        )

        for i, r in enumerate(per_lane_results):
            per_lane_results[i] = evaluate_three_signals(
                result=r,
                collector=collector,
                window_start=window_start,
                window_end=window_end,
                expected=expected,
                signal1_e2e_max_sec=signal1_max,
                signal2_local_max_sec=signal2_max,
                signal3_stability_duration_sec=signal3_duration,
                stability_mode=stability_mode,
            )

        for r in per_lane_results:
            overall = "PASS" if r.passed else "FAIL"
            self.logger.info(
                f"  [BGP RIB live] Lane {r.lane} {r.device}: "
                f"[{overall}] — 3-signal evaluation"
            )
            self.logger.info(
                f"    Signal 1 — E2E convergence "
                f"(≤{r.signal1_e2e_threshold_sec:.0f}s from test case start): "
                f"[{'PASS' if r.signal1_e2e_ok else 'FAIL'}] {r.signal1_e2e_detail}"
            )
            self.logger.info(
                f"    Signal 2 — GTSW propagation "
                f"(≤{r.signal2_local_threshold_sec:.0f}s from first non-zero to threshold): "
                f"[{'PASS' if r.signal2_local_ok else 'FAIL'}] {r.signal2_local_detail}"
            )
            self.logger.info(
                f"    Signal 3 — Post-conv stability "
                f"({r.signal3_stability_duration_sec:.0f}s held at threshold, no drops): "
                f"[{'PASS' if r.signal3_stability_ok else 'FAIL'}] {r.signal3_stability_detail}"
            )

        failures = [r for r in per_lane_results if not r.passed]

        detail_lines = [
            f"Lane {r.lane} {r.device}: [{'PASS' if r.passed else 'FAIL'}] {r.detail}"
            for r in per_lane_results
        ]
        details = await everpaste_details_suffix(
            "BGP RIB convergence — per-lane 3-signal detail",
            detail_lines,
            collectors=[collector],
            window_start=window_start,
            window_end=window_end,
            result_status=("FAIL" if failures else "PASS"),
            result_reason="; ".join(
                f"Lane {r.lane} {r.device}: {r.detail}" for r in failures
            )[:300],
        )

        global_timeout_count = collector.timeout_count_in_window(
            window_start, window_end
        )
        target_timeouts, boundary_notes = _target_timeout_attribution(
            collector,
            lane_map.values(),
            window_start,
            window_end,
        )
        for note in boundary_notes:
            self.logger.info(f"  [BGP RIB live] timeout boundary: {note}")
        timeout_count = global_timeout_count + sum(target_timeouts.values())
        if timeout_count > 0 and stability_mode != BLIP_MODE_SKIP_NULL_STRICT:
            attribution = (
                f"; request attribution: {'; '.join(boundary_notes)}"
                if boundary_notes
                else ""
            )
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    f"Got null data — {timeout_count} target/global poll "
                    f"timeout(s) in window "
                    f"[{window_start:.0f}, {window_end:.0f}]"
                    f"{attribution}{details}"
                ),
            )
        if stability_mode == BLIP_MODE_SKIP_NULL_STRICT:
            observed_target_timeouts = {
                device: count for device, count in target_timeouts.items() if count
            }
            if observed_target_timeouts:
                self.logger.info(
                    "  [BGP RIB live] tolerated target-device null polls in "
                    f"skip_null_strict mode: {observed_target_timeouts}"
                )

        if failures:
            missing_targets: t.List[str] = []
            if stability_mode == BLIP_MODE_SKIP_NULL_STRICT:
                observed_targets = {
                    str(getattr(row, "gtsw", ""))
                    for row in collector.get_rows_in_window(window_start, window_end)
                    if getattr(row, "matched", None) is not None
                    and not str(getattr(row, "notes", "") or "").startswith("error:")
                }
                missing_targets = sorted(set(lane_map.values()) - observed_targets)
            fail_summary = "; ".join(
                f"Lane {r.lane} {r.device}: {r.detail}" for r in failures
            )
            if missing_targets:
                fail_summary = (
                    "INSUFFICIENT MEASUREMENT — no valid BGP RIB sample for "
                    f"target(s) {', '.join(missing_targets)}; {fail_summary}"
                )
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=fail_summary + details,
            )
        pass_summary = " | ".join(
            f"Lane {r.lane} ({r.device}): E2E={r.signal1_e2e_sec}s, "
            f"GTSW-prop={r.signal2_local_sec}s, "
            f"stable={r.signal3_stability_duration_sec:.0f}s"
            for r in per_lane_results
        )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=f"All lanes passed 3-signal evaluation — {pass_summary}{details}",
        )

    async def _evaluate_restart_reconverge(
        self,
        collector: t.Any,
        lane_map: t.Dict[int, str],
        expected: int,
        check_params: t.Dict[str, t.Any],
        default_sla_sec: float,
    ) -> hc_types.HealthCheckResult:
        """mode="restart": tolerate the null/unresponsive polls during a service
        restart and assert each device's RIB returns to ``expected`` within the
        reconverge SLA, measured from the recorded restart moment."""
        window_end = check_params.get("window_end")
        disruption_ts = check_params.get("disruption_ts")
        if disruption_ts is None:
            recorded = get_disruption_time()
            disruption_ts = recorded if recorded > 0 else get_test_case_start_time()
        reconverge_sla = float(check_params.get("reconverge_sla_sec", default_sla_sec))

        self.logger.info(
            f"  [BGP RIB restart] waiting through "
            f"{float(disruption_ts) + reconverge_sla:.0f}; "
            f"SLA {reconverge_sla:.0f}s from restart"
        )
        results, window_end = await wait_for_restart_reconverge(
            collector=collector,
            lane_map=lane_map,
            expected=expected,
            disruption_ts=float(disruption_ts),
            reconverge_sla_sec=reconverge_sla,
            window_end=float(window_end) if window_end is not None else None,
            poll_interval_sec=float(check_params.get("restart_poll_interval_sec", 1.0)),
        )
        for lane_id, device, passed, _sec, _null, detail in results:
            self.logger.info(
                f"  [BGP RIB restart] Lane {lane_id} {device}: "
                f"[{'PASS' if passed else 'FAIL'}] {detail}"
            )
        failures = [r for r in results if not r[2]]
        details = await everpaste_details_suffix(
            "BGP RIB restart reconverge — per-device detail",
            [
                f"Lane {r[0]} {r[1]}: [{'PASS' if r[2] else 'FAIL'}] {r[5]}"
                for r in results
            ],
            collectors=[collector],
            window_start=float(disruption_ts),
            window_end=float(window_end),
            result_status=("FAIL" if failures else "PASS"),
            result_reason="; ".join(f"Lane {r[0]} {r[1]}: {r[5]}" for r in failures)[
                :300
            ],
        )
        if not results:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=f"No restart reconverge data{details}",
            )
        if failures:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message="; ".join(f"Lane {r[0]} {r[1]}: {r[5]}" for r in failures)
                + details,
            )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message="All devices reconverged after restart — "
            + "; ".join(f"Lane {r[0]}: {r[5]}" for r in results)
            + details,
        )

    def _evaluate_from_jsonl(
        self,
        lane_map: t.Dict[int, str],
        expected: int,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        jsonl_path = check_params.get("jsonl_path", JSONL_PATH)
        trigger_delay_sec = check_params.get("trigger_delay_sec", 120)

        try:
            with open(jsonl_path) as f:
                rows = [json.loads(line) for line in f if line.strip()]
        except FileNotFoundError:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=f"JSONL file not found: {jsonl_path}",
            )

        if not rows:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message="JSONL file is empty",
            )

        first_ts = _parse_ts(rows[0]["timestamp"]).timestamp()
        trigger_ts = first_ts + trigger_delay_sec

        results = [
            self._evaluate_lane(lane_id, gtsw, rows, expected, trigger_ts)
            for lane_id, gtsw in sorted(lane_map.items())
        ]

        failures = [r for r in results if not r[2]]
        for lane_id, gtsw, passed, _actual, _conv, detail in results:
            status = "PASS" if passed else "FAIL"
            self.logger.info(f"  [BGP RIB] Lane {lane_id} {gtsw}: [{status}] {detail}")

        if failures:
            fail_summary = "; ".join(f"Lane {r[0]} {r[1]}: {r[5]}" for r in failures)
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=fail_summary,
            )
        pass_summary = "; ".join(f"Lane {r[0]}: {r[4]}s" for r in results)
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=f"All lanes converged — {pass_summary}",
        )

    def _evaluate_lane(
        self,
        lane_id: int,
        gtsw: str,
        rows: t.List[t.Dict[str, t.Any]],
        expected: int,
        trigger_ts: float,
    ) -> t.Tuple[int, str, bool, int, t.Optional[float], str]:
        device_rows = [r for r in rows if r.get("gtsw") == gtsw]
        if not device_rows:
            return (lane_id, gtsw, False, 0, None, "no data")

        all_errors = all(r.get("notes", "").startswith("error:") for r in device_rows)
        if all_errors:
            return (
                lane_id,
                gtsw,
                False,
                0,
                None,
                f"BGP unresponsive (all {len(device_rows)} polls failed)",
            )

        convergence_sec = None
        last_matched = 0
        for r in device_rows:
            try:
                row_ts = _parse_ts(r["timestamp"]).timestamp()
            except ValueError:
                continue
            matched = r.get("matched", 0)
            if not r.get("notes") and matched >= expected and convergence_sec is None:
                convergence_sec = round(row_ts - trigger_ts, 1)
            last_matched = matched

        passed = convergence_sec is not None
        detail = (
            f"reached {last_matched} in {convergence_sec}s"
            if passed
            else f"only reached {last_matched}/{expected}"
        )
        return (lane_id, gtsw, passed, last_matched, convergence_sec, detail)
