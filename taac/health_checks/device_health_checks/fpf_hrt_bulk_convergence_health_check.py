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
    disruption_inconclusive_skip,
    evaluate_three_signals,
    everpaste_details_suffix,
    get_collector,
    get_test_case_start_time,
)
from taac.libs.fpf.fpf_stress_checks import _parse_ts
from taac.health_check.health_check import types as hc_types

JSONL_PATH = "/tmp/fpf_stress_hrt_bulk.jsonl"


class FpfHrtBulkConvergenceHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    """Postcheck: evaluate HRT bulk prefix convergence from collector data.

    Each monitored injected lane normally must converge to its threshold
    (3-signal evaluation). For link-event tests, lanes listed in
    ``impacted_lanes`` instead flip to a *withdrawn* contract: the last
    in-window sample for that lane (on every host/device the collector polls)
    must be at or below ``withdrawn_max_count`` (default 0) — i.e. once the
    GTSW<->GPU link is disabled or drained, the lane's FSDB session is gone and
    the prefixes that arrived over it must no longer be present. The
    unimpacted injected lanes still get the full convergence evaluation, so one
    disrupted lane never masks a regression on the healthy lanes.

    When ``use_live_collectors`` is True, queries the live HRT collector via the
    module-level registry using ``window_start``/``window_end``; otherwise reads
    ``/tmp/fpf_stress_hrt_bulk.jsonl``.
    """

    CHECK_NAME = hc_types.CheckName.FPF_HRT_BULK_CONVERGENCE_CHECK
    CHECK_SCOPE = hc_types.Scope.DEFAULT
    OPERATING_SYSTEMS = ["FBOSS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        lanes: t.List[int] = check_params.get("lanes", [0, 1])
        expected_per_lane: t.Dict[int, int] = {
            int(k): v for k, v in check_params.get("expected_per_lane", {}).items()
        }
        if not expected_per_lane:
            expected_per_lane = {lane: int(20000) for lane in lanes}
        impacted_lanes: t.List[int] = [
            int(x) for x in check_params.get("impacted_lanes", [])
        ]
        withdrawn_max: int = int(check_params.get("withdrawn_max_count", 0))
        use_live = check_params.get("use_live_collectors", False)
        if impacted_lanes:
            _skip = disruption_inconclusive_skip()
            if _skip:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.SKIP, message=_skip
                )

        if use_live:
            return await self._evaluate_from_live_collector(
                lanes,
                expected_per_lane,
                impacted_lanes,
                withdrawn_max,
                check_params,
            )

        return self._evaluate_from_jsonl(
            lanes, expected_per_lane, impacted_lanes, withdrawn_max, check_params
        )

    async def _evaluate_from_live_collector(
        self,
        lanes: t.List[int],
        expected_per_lane: t.Dict[int, int],
        impacted_lanes: t.List[int],
        withdrawn_max: int,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        collector = get_collector("hrt")
        if collector is None:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message="No live HRT collector in registry",
            )

        # Lane -> host-NIC mapping note (e.g. "→ beth0@rtptest1544") for messages.
        lane_labels: t.Dict[str, str] = check_params.get("lane_labels", {})

        def _lbl(lane: int) -> str:
            note = lane_labels.get(str(lane), "")
            return f" {note}" if note else ""

        # Restrict this check to only the host(s) whose lane was actually
        # impacted. The HRT collector polls every GPU host, but for a link-event
        # disable/drain only the impacted host's lane withdraws — the remote
        # host keeps the route, so evaluating it here would be a false FAIL.
        only_hosts: t.Optional[t.List[str]] = check_params.get("only_hosts") or None

        window_end = check_params.get("window_end", time.time())
        tc_start = get_test_case_start_time()
        lookback_sec = check_params.get("lookback_sec", 900)
        window_start = check_params.get(
            "window_start", tc_start if tc_start else window_end - lookback_sec
        )
        # settle_sec: skip the first N seconds of the window (restore/recovery
        # phase) so the impacted lane's re-converge transient (converge -> brief
        # withdraw -> re-converge as the link comes back) isn't measured as
        # post-convergence instability. The convergence then starts from the
        # settled, recovered state.
        settle_sec = float(check_params.get("settle_sec", 0))
        if settle_sec > 0:
            window_start = min(window_start + settle_sec, window_end)

        self.logger.info(
            f"  [HRT bulk live] Evaluating window: "
            f"{window_start:.0f} to {window_end:.0f} "
            f"({window_end - window_start:.0f}s span); "
            f"impacted (withdrawn) lanes={impacted_lanes or '[]'}"
        )

        signal1_max = check_params.get(
            "signal1_e2e_max_sec", DEFAULT_SIGNAL1_E2E_MAX_SEC
        )
        signal2_max = check_params.get(
            "signal2_local_max_sec", DEFAULT_SIGNAL2_LOCAL_MAX_SEC
        )
        signal3_duration = check_params.get(
            "signal3_stability_duration_sec", DEFAULT_SIGNAL3_STABILITY_DURATION_SEC
        )

        impacted_set = set(impacted_lanes)
        normal_lanes = [lane for lane in lanes if lane not in impacted_set]

        # ---- Unimpacted injected lanes: full 3-signal convergence -----------
        per_lane_results = collector.evaluate_per_lane_window(
            window_start=window_start,
            window_end=window_end,
            lanes=normal_lanes,
            expected_per_lane=expected_per_lane,
            only_hosts=only_hosts,
        )
        for i, r in enumerate(per_lane_results):
            per_lane_results[i] = evaluate_three_signals(
                result=r,
                collector=collector,
                window_start=window_start,
                window_end=window_end,
                expected=expected_per_lane.get(r.lane, 0),
                signal1_e2e_max_sec=signal1_max,
                signal2_local_max_sec=signal2_max,
                signal3_stability_duration_sec=signal3_duration,
                lane_id=r.lane,
            )
        for r in per_lane_results:
            overall = "PASS" if r.passed else "FAIL"
            self.logger.info(
                f"  [HRT bulk live] Lane {r.lane}: [{overall}] — 3-signal evaluation"
            )

        normal_failures = [
            f"Lane {r.lane}{_lbl(r.lane)}: {r.detail}"
            for r in per_lane_results
            if not r.passed
        ]

        # ---- Impacted lanes: withdrawn contract (last sample <= max) ---------
        withdrawn_failures: t.List[str] = []
        withdrawn_pass_detail: t.List[str] = []
        if impacted_lanes:
            rows = collector.get_rows_in_window(window_start, window_end)
            if only_hosts:
                allow = set(only_hosts)
                rows = [r for r in rows if getattr(r, "host", None) in allow]
            for lane, passed, detail in self._evaluate_withdrawn_rows(
                rows, impacted_lanes, withdrawn_max
            ):
                status = "PASS" if passed else "FAIL"
                self.logger.info(
                    f"  [HRT bulk live] Lane {lane} (impacted): [{status}] {detail}"
                )
                if passed:
                    withdrawn_pass_detail.append(f"Lane {lane}{_lbl(lane)}: {detail}")
                else:
                    withdrawn_failures.append(f"Lane {lane}{_lbl(lane)}: {detail}")

        detail_lines = [
            f"Lane {r.lane}: [{'PASS' if r.passed else 'FAIL'}] {r.detail}"
            for r in per_lane_results
        ] + [f"(impacted) {d}" for d in (withdrawn_pass_detail + withdrawn_failures)]
        details = await everpaste_details_suffix(
            "HRT bulk convergence — per-lane detail",
            detail_lines,
            collectors=[collector],
            window_start=window_start,
            window_end=window_end,
            result_status=(
                "FAIL" if (normal_failures or withdrawn_failures) else "PASS"
            ),
            result_reason="; ".join(normal_failures + withdrawn_failures)[:300],
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

        failures = normal_failures + withdrawn_failures
        if failures:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message="; ".join(failures) + details,
            )

        pass_bits = [
            f"Lane {r.lane}: E2E={r.signal1_e2e_sec}s, "
            f"GTSW-prop={r.signal2_local_sec}s, "
            f"stable={r.signal3_stability_duration_sec:.0f}s"
            for r in per_lane_results
        ] + withdrawn_pass_detail
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message="All lanes passed — "
            + (" | ".join(pass_bits) or "no lanes")
            + details,
        )

    def _evaluate_withdrawn_rows(
        self,
        rows: t.List[t.Any],
        impacted_lanes: t.List[int],
        withdrawn_max: int,
    ) -> t.List[t.Tuple[int, bool, str]]:
        """For each impacted lane, the latest in-window sample on every
        (host, device_id) the collector polled must be <= withdrawn_max.

        ``rows`` are HrtBulkRow dataclasses (each carries host, device_id,
        lane_counts, timestamp). Returns (lane, passed, detail) per lane.
        """
        results: t.List[t.Tuple[int, bool, str]] = []
        # latest row per (host, device_id)
        latest: t.Dict[t.Tuple[str, int], t.Tuple[float, t.Any]] = {}
        for row in rows:
            try:
                ts = _parse_ts(row.timestamp).timestamp()
            except (ValueError, AttributeError):
                continue
            key = (getattr(row, "host", ""), int(getattr(row, "device_id", 0)))
            if key not in latest or ts > latest[key][0]:
                latest[key] = (ts, row)

        if not latest:
            return [
                (lane, False, "no in-window samples to evaluate withdrawal")
                for lane in sorted(impacted_lanes)
            ]

        for lane in sorted(impacted_lanes):
            problems: t.List[str] = []
            worst = 0
            for (host, dev), (_ts, row) in sorted(latest.items()):
                counts = getattr(row, "lane_counts", [])
                if lane >= len(counts):
                    continue
                count = counts[lane]
                worst = max(worst, count)
                if count > withdrawn_max:
                    problems.append(f"{host.split('.')[0]}/dev{dev}={count}")
            passed = not problems
            if passed:
                detail = (
                    f"withdrawn — last sample <= {withdrawn_max} on all "
                    f"{len(latest)} group(s) (max seen {worst})"
                )
            else:
                detail = (
                    f"still present in last sample (> {withdrawn_max}): "
                    + ", ".join(problems)
                )
            results.append((lane, passed, detail))
        return results

    def _evaluate_from_jsonl(
        self,
        lanes: t.List[int],
        expected_per_lane: t.Dict[int, int],
        impacted_lanes: t.List[int],
        withdrawn_max: int,
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

        impacted_set = set(impacted_lanes)
        normal_lanes = [lane for lane in lanes if lane not in impacted_set]

        results = [
            self._evaluate_lane(
                lane_id, expected_per_lane.get(lane_id, 0), rows, trigger_ts
            )
            for lane_id in sorted(normal_lanes)
        ]

        failures = [f"Lane {r[0]}: {r[4]}" for r in results if not r[1]]
        for lane_id, passed, _actual, _conv, detail in results:
            status = "PASS" if passed else "FAIL"
            self.logger.info(f"  [HRT bulk] Lane {lane_id}: [{status}] {detail}")

        if impacted_lanes:
            jsonl_rows = [_JsonlRow(r) for r in rows]
            for lane, passed, detail in self._evaluate_withdrawn_rows(
                jsonl_rows, impacted_lanes, withdrawn_max
            ):
                status = "PASS" if passed else "FAIL"
                self.logger.info(
                    f"  [HRT bulk] Lane {lane} (impacted): [{status}] {detail}"
                )
                if not passed:
                    failures.append(f"Lane {lane}: {detail}")

        if failures:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message="; ".join(failures),
            )
        pass_summary = "; ".join(f"Lane {r[0]}: {r[3]}s" for r in results)
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=f"All lanes OK — {pass_summary}",
        )

    def _evaluate_lane(
        self,
        lane_id: int,
        expected: int,
        rows: t.List[t.Dict[str, t.Any]],
        trigger_ts: float,
    ) -> t.Tuple[int, bool, int, t.Optional[float], str]:
        if expected == 0:
            return (lane_id, True, 0, None, "no threshold set")

        convergence_sec = None
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
            if count >= expected and convergence_sec is None:
                convergence_sec = round(row_ts - trigger_ts, 1)

        passed = convergence_sec is not None
        detail = (
            f"reached {expected} in {convergence_sec}s"
            if passed
            else f"only reached {last_actual}/{expected}"
        )
        return (lane_id, passed, last_actual, convergence_sec, detail)


class _JsonlRow:
    """Adapter exposing a JSONL dict row as the attribute shape that
    ``_evaluate_withdrawn_rows`` expects (host, device_id, lane_counts, ts)."""

    def __init__(self, d: t.Dict[str, t.Any]) -> None:
        self.host = d.get("host", "")
        self.device_id = d.get("device_id", 0)
        self.lane_counts = d.get("lane_counts", [])
        self.timestamp = d.get("timestamp", "")
