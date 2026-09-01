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
    baseline_impaired_lane_union,
    disruption_inconclusive_skip,
    everpaste_details_suffix,
    get_allow_baseline_failures,
    get_collector,
    get_disruption_time,
    get_restart_completion_time,
    get_restart_time,
    get_test_case_start_time,
    validate_restart_tolerant_tuple,
)
from taac.libs.fpf.fpf_stress_checks import _parse_ts
from taac.health_check.health_check import types as hc_types

JSONL_PATH = "/tmp/fpf_stress_hrt_remote_failure.jsonl"


class FpfHrtRemoteFailureConvergenceHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    """Evaluate HRT remote-failure (negative-route) convergence from collector data.

    Supports two directions:
      - "drain": count transitions 0->N (negative routes appear after drain)
      - "recovery": count transitions N->0 (negative routes clear after undrain)

    When ``use_live_collectors`` is True, queries the live HRT remote-failure
    collector via the module-level registry using time-windowed assessment.
    Otherwise falls back to reading the JSONL file.
    """

    CHECK_NAME = hc_types.CheckName.FPF_HRT_REMOTE_FAILURE_CONVERGENCE_CHECK
    CHECK_SCOPE = hc_types.Scope.DEFAULT
    OPERATING_SYSTEMS = ["FBOSS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        lanes: t.List[int] = check_params.get("lanes", [0, 1, 2, 3])
        device_ids: t.List[int] = check_params.get("device_ids", [0])
        expected_per_lane: t.Dict[int, int] = {
            int(k): v for k, v in check_params.get("expected_per_lane", {}).items()
        }
        direction: str = check_params.get("direction", "drain")
        max_convergence_sec: int = check_params.get("max_convergence_sec", 120)
        use_live = check_params.get("use_live_collectors", False)
        if direction == "drain":
            _skip = disruption_inconclusive_skip()
            if _skip:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.SKIP, message=_skip
                )
        # Baseline exclusion is lane-only legacy state, so apply it only to the
        # compatible dev0 topology. Multi-device checks retain every tuple rather
        # than allowing one device's degraded lane to mask another device.
        if (
            direction
            in (
                "stable",
                "stable_last_sample",
                "stable_skip_null_strict",
                "stable_last_n",
            )
            and get_allow_baseline_failures()
            and device_ids == [0]
        ):
            baseline = baseline_impaired_lane_union()
            excluded = {
                lane for lane in baseline if expected_per_lane.get(lane, 0) == 0
            }
            kept = [lane for lane in lanes if lane not in excluded]
            if baseline:
                self.logger.info(
                    f"  [HRT remote_failure] excluding baseline-impaired lanes "
                    f"{sorted(excluded & set(lanes))} from stable assertion"
                )
            lanes = kept

        if use_live:
            return await self._evaluate_from_live_collector(
                lanes,
                device_ids,
                expected_per_lane,
                direction,
                max_convergence_sec,
                check_params,
            )

        return self._evaluate_from_jsonl(
            lanes, expected_per_lane, direction, max_convergence_sec, check_params
        )

    async def _evaluate_from_live_collector(
        self,
        lanes: t.List[int],
        device_ids: t.List[int],
        expected_per_lane: t.Dict[int, int],
        direction: str,
        max_convergence_sec: int,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        collector_name: str = check_params.get("collector_name", "hrt_remote_failure")
        collector = get_collector(collector_name)
        if collector is None:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=f"No live HRT remote-failure collector '{collector_name}' in registry",
            )

        # Lane -> host-NIC mapping note (e.g. "→ beth0@rtptest1544") for messages.
        lane_labels: t.Dict[str, str] = check_params.get("lane_labels", {})

        def _lbl(lane: int) -> str:
            note = lane_labels.get(str(lane), "")
            return f" {note}" if note else ""

        # Restrict to the host(s) whose lane was actually impacted — the remote
        # host keeps the route on the same lane, so evaluating it is a false FAIL.
        only_hosts: t.Optional[t.List[str]] = check_params.get("only_hosts") or None

        window_end = check_params.get("window_end", time.time())
        tc_start = get_test_case_start_time()
        lookback_sec = check_params.get("lookback_sec", 900)
        # For the "stable" assertion on the impacted lane, anchor the window at the
        # recorded disruption time (the drain/disable moment) rather than the
        # test-case start. The negative-route count legitimately blips during the
        # pre-disruption prefix INJECTION ramp (observed: L0=100 for one ~3s sample
        # minutes before the drain); starting at tc_start would count that
        # injection artifact as a drain-time regression. Falls back to tc_start
        # when no disruption time was recorded (disruption_time defaults to 0.0).
        default_start = tc_start if tc_start else window_end - lookback_sec
        if direction in (
            "stable",
            "stable_last_sample",
            "stable_skip_null_strict",
            "stable_last_n",
        ):
            disruption_ts = get_disruption_time()
            if disruption_ts > 0:
                default_start = max(default_start, disruption_ts)
        window_start = check_params.get("window_start", default_start)

        self.logger.info(
            f"  [HRT remote_failure live] direction={direction} "
            f"window: {window_start:.0f} to {window_end:.0f} "
            f"({window_end - window_start:.0f}s span)"
        )

        tuple_lanes: t.Dict[str, t.Dict[str, t.List[int]]] = check_params.get(
            "tuple_lanes_by_host_device", {}
        )
        excluded_tuple_lanes: t.Dict[str, t.Dict[str, t.List[int]]] = check_params.get(
            "excluded_tuple_lanes_by_host_device", {}
        )
        restart_tolerant_hosts = set(
            check_params.get("restart_tolerant_hosts", []) or []
        )
        if restart_tolerant_hosts:
            per_lane_results = []
            selected_hosts = only_hosts or collector.hosts
            for host in selected_hosts:
                host_direction = (
                    "stable_skip_null_strict"
                    if host in restart_tolerant_hosts
                    else direction
                )
                for device_id in device_ids:
                    per_lane_results.extend(
                        collector.evaluate_per_lane_window(
                            window_start=window_start,
                            window_end=window_end,
                            lanes=lanes,
                            device_ids=[device_id],
                            expected_per_lane=expected_per_lane,
                            direction=host_direction,
                            max_convergence_sec=max_convergence_sec,
                            only_hosts=[host],
                        )
                    )
        elif tuple_lanes:
            per_lane_results = []
            for host, devices in tuple_lanes.items():
                for device_id, selected_lanes in devices.items():
                    per_lane_results.extend(
                        collector.evaluate_per_lane_window(
                            window_start=window_start,
                            window_end=window_end,
                            lanes=selected_lanes,
                            device_ids=[int(device_id)],
                            expected_per_lane=expected_per_lane,
                            direction=direction,
                            max_convergence_sec=max_convergence_sec,
                            only_hosts=[host],
                        )
                    )
        elif excluded_tuple_lanes:
            per_lane_results = []
            selected_hosts = only_hosts or collector.hosts
            for host in selected_hosts:
                for device_id in device_ids:
                    excluded = set(
                        excluded_tuple_lanes.get(host, {}).get(str(device_id), [])
                    )
                    selected_lanes = [lane for lane in lanes if lane not in excluded]
                    per_lane_results.extend(
                        collector.evaluate_per_lane_window(
                            window_start=window_start,
                            window_end=window_end,
                            lanes=selected_lanes,
                            device_ids=[device_id],
                            expected_per_lane=expected_per_lane,
                            direction=direction,
                            max_convergence_sec=max_convergence_sec,
                            only_hosts=[host],
                        )
                    )
        else:
            per_lane_results = collector.evaluate_per_lane_window(
                window_start=window_start,
                window_end=window_end,
                lanes=lanes,
                device_ids=device_ids,
                expected_per_lane=expected_per_lane,
                direction=direction,
                max_convergence_sec=max_convergence_sec,
                only_hosts=only_hosts,
            )

        if restart_tolerant_hosts:
            restart_ts = get_restart_time()
            restart_completion_ts = get_restart_completion_time()
            rows = collector.get_rows_in_window(window_start, window_end)
            for result in per_lane_results:
                if result.host not in restart_tolerant_hosts:
                    continue
                if restart_ts <= 0:
                    recovered = False
                    recovery_detail = "no recorded HRT restart timestamp"
                else:
                    recovered, recovery_detail = validate_restart_tolerant_tuple(
                        rows=rows,
                        host=t.cast(str, result.host),
                        device_id=t.cast(int, result.device_id),
                        lane=result.lane,
                        expected=expected_per_lane.get(result.lane, 0),
                        restart_ts=restart_ts,
                        restart_completion_ts=(
                            restart_completion_ts if restart_completion_ts > 0 else None
                        ),
                    )
                result.detail += f" | restart recovery: {recovery_detail}"
                if not recovered:
                    result.passed = False

        failures = [r for r in per_lane_results if not r.passed]
        for r in per_lane_results:
            status = "PASS" if r.passed else "FAIL"
            self.logger.info(
                f"  [HRT remote_failure live] {r.device}: [{status}] {r.detail}"
            )

        details = await everpaste_details_suffix(
            f"HRT remote-failure ({direction}) — per-lane detail",
            [
                f"{r.device}{_lbl(r.lane)}: [{'PASS' if r.passed else 'FAIL'}] "
                f"{r.detail}"
                for r in per_lane_results
            ],
            collectors=[collector],
            window_start=window_start,
            window_end=window_end,
            result_status=("FAIL" if failures else "PASS"),
            result_reason="; ".join(
                f"{r.device}{_lbl(r.lane)}: {r.detail}" for r in failures
            )[:300],
        )

        timeout_count = collector.timeout_count_in_window(window_start, window_end)
        if timeout_count > 0:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    f"Got null data — {timeout_count} poll timeout(s) in window "
                    f"[{window_start:.0f}, {window_end:.0f}]{details}"
                ),
            )

        if failures:
            fail_summary = "; ".join(
                f"{r.device}{_lbl(r.lane)}: {r.detail}" for r in failures
            )
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=fail_summary + details,
            )
        pass_summary = "; ".join(f"{r.device}: {r.detail}" for r in per_lane_results)
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=f"All lanes OK ({direction}) — {pass_summary}{details}",
        )

    def _evaluate_from_jsonl(
        self,
        lanes: t.List[int],
        expected_per_lane: t.Dict[int, int],
        direction: str,
        max_convergence_sec: int,
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
            self._evaluate_lane_from_rows(
                lane_id,
                expected_per_lane.get(lane_id, 0),
                rows,
                trigger_ts,
                direction,
                max_convergence_sec,
            )
            for lane_id in sorted(lanes)
        ]

        failures = [r for r in results if not r[1]]
        for lane_id, passed, _actual, _conv, detail in results:
            status = "PASS" if passed else "FAIL"
            self.logger.info(
                f"  [HRT remote_failure] Lane {lane_id}: [{status}] {detail}"
            )

        if failures:
            fail_summary = "; ".join(f"Lane {r[0]}: {r[4]}" for r in failures)
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=fail_summary,
            )
        pass_summary = "; ".join(f"Lane {r[0]}: {r[4]}" for r in results)
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=f"All lanes OK ({direction}) — {pass_summary}",
        )

    def _evaluate_lane_from_rows(
        self,
        lane_id: int,
        expected: int,
        rows: t.List[t.Dict[str, t.Any]],
        trigger_ts: float,
        direction: str,
        max_convergence_sec: int,
    ) -> t.Tuple[int, bool, int, t.Optional[float], str]:
        if direction in (
            "stable",
            "stable_last_sample",
            "stable_skip_null_strict",
            "stable_last_n",
        ):
            return self._evaluate_stable_from_rows(lane_id, expected, rows, direction)
        if direction == "drain":
            return self._evaluate_drain_from_rows(
                lane_id, expected, rows, max_convergence_sec
            )
        return self._evaluate_recovery_from_rows(
            lane_id, expected, rows, max_convergence_sec
        )

    def _evaluate_stable_from_rows(
        self,
        lane_id: int,
        expected: int,
        rows: t.List[t.Dict[str, t.Any]],
        direction: str = "stable",
    ) -> t.Tuple[int, bool, int, t.Optional[float], str]:
        # The direction selects the per-sample blip contract around the expected
        # count. The default is zero, while a VF group whose own planes are not
        # exposed can intentionally assert its cross-plane remote-failure count.
        # A row that lacks this lane's count is a null/missing sample.
        from taac.libs.fpf.fpf_stress_checks import (
            BLIP_MODE_LAST_N,
            BLIP_MODE_LAST_SAMPLE,
            BLIP_MODE_SKIP_NULL_STRICT,
            BLIP_MODE_STRICT,
            evaluate_blip_series,
        )

        mode = {
            "stable": BLIP_MODE_STRICT,
            "stable_last_sample": BLIP_MODE_LAST_SAMPLE,
            "stable_skip_null_strict": BLIP_MODE_SKIP_NULL_STRICT,
            "stable_last_n": BLIP_MODE_LAST_N,
        }.get(direction, BLIP_MODE_STRICT)

        series: t.List[t.Optional[int]] = []
        max_seen = 0
        for r in rows:
            lane_counts = r.get("lane_counts", [])
            if lane_id >= len(lane_counts):
                # Strict mode skips missing-lane rows entirely (legacy behaviour);
                # the blip-aware modes record them as null/missing samples.
                if mode != BLIP_MODE_STRICT:
                    series.append(None)
                continue
            count = lane_counts[lane_id]
            if count > max_seen:
                max_seen = count
            series.append(count)

        passed, detail = evaluate_blip_series(series, expected, mode)
        return (
            lane_id,
            passed,
            max_seen,
            None,
            f"[{direction}] {detail} (expected={expected}, max={max_seen})",
        )

    def _evaluate_drain_from_rows(
        self,
        lane_id: int,
        expected: int,
        rows: t.List[t.Dict[str, t.Any]],
        max_convergence_sec: int,
    ) -> t.Tuple[int, bool, int, t.Optional[float], str]:
        if expected == 0:
            return (lane_id, True, 0, None, "no threshold set")

        t_last_zero = None
        t_converge = None
        last_actual = 0
        for r in rows:
            lane_counts = r.get("lane_counts", [])
            if lane_id >= len(lane_counts):
                continue
            try:
                row_ts = _parse_ts(r["timestamp"]).timestamp()
            except ValueError:
                continue
            count = lane_counts[lane_id]
            last_actual = count
            # Only update t_last_zero before convergence — otherwise a later
            # recovery (count back to 0) would push t_last_zero past
            # t_converge and yield a negative convergence_sec.
            if count == 0 and t_converge is None:
                t_last_zero = row_ts
            if count >= expected and t_converge is None and t_last_zero is not None:
                t_converge = row_ts

        if t_converge is not None and t_last_zero is not None:
            convergence_sec = round(t_converge - t_last_zero, 1)
            passed = convergence_sec <= max_convergence_sec
            detail = f"0->{expected} in {convergence_sec}s (SLA {max_convergence_sec}s)"
            return (lane_id, passed, last_actual, convergence_sec, detail)

        return (
            lane_id,
            False,
            last_actual,
            None,
            f"never reached {expected} (last={last_actual})",
        )

    def _evaluate_recovery_from_rows(
        self,
        lane_id: int,
        expected: int,
        rows: t.List[t.Dict[str, t.Any]],
        max_convergence_sec: int,
    ) -> t.Tuple[int, bool, int, t.Optional[float], str]:
        if expected == 0:
            return (lane_id, True, 0, None, "no threshold set")

        t_peak = None
        t_recovered = None
        last_actual = 0
        for r in rows:
            lane_counts = r.get("lane_counts", [])
            if lane_id >= len(lane_counts):
                continue
            try:
                row_ts = _parse_ts(r["timestamp"]).timestamp()
            except ValueError:
                continue
            count = lane_counts[lane_id]
            last_actual = count
            if count >= expected:
                t_peak = row_ts
                t_recovered = None
            if count == 0 and t_peak is not None and t_recovered is None:
                t_recovered = row_ts

        if t_recovered is not None and t_peak is not None:
            convergence_sec = round(t_recovered - t_peak, 1)
            passed = convergence_sec <= max_convergence_sec
            detail = f"{expected}->0 in {convergence_sec}s (SLA {max_convergence_sec}s)"
            return (lane_id, passed, last_actual, convergence_sec, detail)

        return (
            lane_id,
            False,
            last_actual,
            None,
            f"never recovered to 0 (last={last_actual})",
        )
