# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""FPF HRT FSDB-session-count statistics health check.

Consumes the single live ``hrt_fsdb_session`` collector registered in the FPF
collector registry. That ONE collector holds ALL monitored GPU hosts (each row
carries its ``host``); this check iterates the hosts present in its rows and
evaluates each host independently; every host must satisfy the contract. Each
poll captures the total CONNECTED FSDB-session count plus a per-lane breakdown.
Two contracts via ``mode``:

  mode="disruption": two independent signals over the test window.
    Signal 1 — DURING the disruption the CONNECTED count drops to
      ``expected_connected_during`` (e.g. 28 when lane 0 of all 4 GPUs is
      impacted: 32 - 4) and the impacted lane(s) show churn (connected count
      drops below their total).
    Signal 2 — AFTER the disruption stops the count recovers to
      ``expected_connected`` (32) and holds there for >= ``recovery_min_sec``.
    FAILs if either signal is violated, SKIPs when there are no in-window
    samples, else PASSes. SKIPs (inconclusive) when the disruption was verified
    ineffective.

  mode="stable": the CONNECTED count stays at ``expected_connected`` across the
    whole window with no churn — used for stable-state configs.

The overall status is FAIL if any host violates its contract, SKIP if no host
produced in-window data, else PASS. Mirrors the everpaste-suffix + logging style
of the plane-status check.
"""

import time
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.libs.fpf.fpf_collector_registry import (
    disruption_inconclusive_skip,
    everpaste_details_suffix,
    get_collector,
    get_disruption_time,
    get_test_case_start_time,
)
from taac.health_check.health_check import types as hc_types

DEFAULT_EXPECTED_CONNECTED = 32
DEFAULT_EXPECTED_CONNECTED_DURING = 28
DEFAULT_RECOVERY_MIN_SEC = 60.0
DEFAULT_LOOKBACK_SEC = 900

# Registry name of the single FSDB-session collector (holds ALL hosts).
_COLLECTOR_NAME = "hrt_fsdb_session"


class _HostSessionResult:
    """Per-host FSDB-session evaluation outcome."""

    def __init__(self, host: str) -> None:
        self.host = host
        self.status = "SKIP"  # PASS / FAIL / SKIP
        self.reason = ""
        self.detail_lines: t.List[str] = []


class FpfHrtSessionStatHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    """Postcheck over the ``hrt_fsdb_session`` collector(s) — CONNECTED census.

    check_params:
        mode (str): "disruption" (default) | "stable".
        expected_connected (int): full CONNECTED census. Default 32.
        expected_connected_during (int): count expected during the disruption
            (e.g. 28). disruption mode only. Default 28.
        impacted_lanes (List[int]): lanes the disruption should churn (e.g. [0]).
        recovery_min_sec (float): seconds the recovered census must hold.
            disruption mode only. Default 60.
        window_start / window_end (float): explicit window overrides.
        lookback_sec (int): fallback window length if no test-case start time.
        window_from_disruption_time (bool) + window_duration_sec (float): When
            True and a disruption time was recorded (get_disruption_time() > 0),
            scope the window to [disruption_time, disruption_time +
            window_duration_sec] (default window_duration_sec = lookback_sec),
            overriding the lookback/tc_start window. Default False.
    """

    CHECK_NAME = hc_types.CheckName.FPF_HRT_SESSION_STAT_CHECK
    CHECK_SCOPE = hc_types.Scope.DEFAULT
    OPERATING_SYSTEMS = ["FBOSS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        collector = get_collector(check_params.get("collector_name", _COLLECTOR_NAME))
        if collector is None:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message="No live HRT FSDB-session collector in registry",
            )

        mode = check_params.get("mode", "disruption")
        expected_connected = int(
            check_params.get("expected_connected", DEFAULT_EXPECTED_CONNECTED)
        )
        expected_during = int(
            check_params.get(
                "expected_connected_during", DEFAULT_EXPECTED_CONNECTED_DURING
            )
        )
        impacted_lanes: t.List[int] = [
            int(p) for p in (check_params.get("impacted_lanes") or [])
        ]
        impacted_tuples_by_host_device: t.Dict[str, t.Dict[str, t.List[int]]] = (
            check_params.get("impacted_tuples_by_host_device", {}) or {}
        )
        recovery_min_sec = float(
            check_params.get("recovery_min_sec", DEFAULT_RECOVERY_MIN_SEC)
        )

        if mode == "disruption":
            _skip = disruption_inconclusive_skip()
            if _skip:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.SKIP, message=_skip
                )

        lookback_sec = float(check_params.get("lookback_sec", DEFAULT_LOOKBACK_SEC))
        # window_from_disruption_time: scope the ODS/collector window to
        # [disruption_time, disruption_time + window_duration_sec] (the recorded
        # disruptive-action epoch) instead of the lookback/tc_start window. Falls
        # back to the normal window resolution when False or when no disruption
        # time was recorded.
        window_from_disruption_time = bool(
            check_params.get("window_from_disruption_time", False)
        )
        window_duration_sec = float(
            check_params.get("window_duration_sec", lookback_sec)
        )
        # window_offset_sec: skip the first N seconds after the disruption so the
        # window excludes the stop-instant boundary sample. The FSDB session
        # census drops within a few seconds of the stop, so a small offset (~10s)
        # drops the single pre-drop poll captured at the exact stop epoch.
        window_offset_sec = float(check_params.get("window_offset_sec", 0))
        disruption_time = get_disruption_time()
        if window_from_disruption_time and disruption_time > 0:
            window_start = disruption_time + window_offset_sec
            window_end = disruption_time + window_duration_sec
        else:
            window_end = float(check_params.get("window_end", time.time()))
            tc_start = get_test_case_start_time()
            default_start = tc_start if tc_start else window_end - lookback_sec
            window_start = float(check_params.get("window_start", default_start))

        # The single collector holds all hosts (each row carries its host); the
        # hosts to evaluate are those present in the in-window rows.
        hosts = collector.hosts_in_window(window_start, window_end)
        if not hosts:
            hosts = list(getattr(collector, "hosts", []) or [])
        self.logger.info(
            f"  [HRT session-stat] mode={mode} hosts={hosts} "
            f"window: {window_start:.0f} to {window_end:.0f} "
            f"({window_end - window_start:.0f}s span)"
            + (
                f" [window from disruption_time {int(disruption_time)} "
                f"+{int(window_duration_sec)}s]"
                if window_from_disruption_time and disruption_time > 0
                else ""
            )
        )

        host_results: t.List[_HostSessionResult] = []
        for host in hosts:
            if mode == "stable":
                hr = self._eval_host_stable(
                    host,
                    collector,
                    window_start,
                    window_end,
                    expected_connected,
                    impacted_lanes,
                )
            else:
                hr = self._eval_host_disruption(
                    host,
                    collector,
                    window_start,
                    window_end,
                    expected_connected,
                    expected_during,
                    impacted_lanes,
                    impacted_tuples_by_host_device.get(host, {}),
                    recovery_min_sec,
                )
            host_results.append(hr)

        if not host_results or all(hr.status == "SKIP" for hr in host_results):
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=(
                    "No in-window HRT session samples on any host "
                    f"[{window_start:.0f}, {window_end:.0f}]"
                ),
            )

        agg_fail = any(hr.status == "FAIL" for hr in host_results)
        agg = "FAIL" if agg_fail else "PASS"
        report = _format_report(host_results, mode, agg)
        details = await everpaste_details_suffix(
            f"HRT session-stat ({mode}) — per-host CONNECTED census detail",
            report.splitlines(),
            collectors=[collector],
            window_start=window_start,
            window_end=window_end,
            result_status=agg,
            result_reason=(
                report.splitlines()[1] if len(report.splitlines()) > 1 else ""
            )[:300],
        )
        status = (
            hc_types.HealthCheckStatus.FAIL
            if agg_fail
            else hc_types.HealthCheckStatus.PASS
        )
        return hc_types.HealthCheckResult(status=status, message=report + details)

    def _eval_host_stable(
        self,
        host: str,
        collector: t.Any,
        window_start: float,
        window_end: float,
        expected_connected: int,
        impacted_lanes: t.Optional[t.List[int]] = None,
    ) -> _HostSessionResult:
        hr = _HostSessionResult(host)
        res = collector.evaluate_window(
            window_start=window_start,
            window_end=window_end,
            expected_connected=expected_connected,
            host=host,
        )
        # PASS iff every non-null sample held the full census (min == expected).
        ok = (
            res.samples > 0
            and res.min_connected == expected_connected
            and res.max_connected == expected_connected
        )
        span_sec = window_end - window_start
        impacted_str = (
            "lane(s) " + ",".join(f"L{lane}" for lane in (impacted_lanes or []))
            if impacted_lanes
            else "none"
        )
        window_color = (
            f"window {span_sec:.0f}s [{window_start:.0f}-{window_end:.0f}], "
            f"impacted {impacted_str}, "
            f"connected min={res.min_connected}/max={res.max_connected}/"
            f"last={res.last_connected} on {host_label(res)}"
        )
        if res.samples == 0:
            hr.status = "SKIP"
            hr.reason = f"No in-window HRT session samples — {res.detail}"
        elif ok:
            hr.status = "PASS"
            hr.reason = (
                f"CONNECTED held steady at {expected_connected} across "
                f"{res.samples} samples (no churn; {window_color}) — {res.detail}"
            )
        else:
            hr.status = "FAIL"
            hr.reason = (
                f"CONNECTED dipped to {res.min_connected} "
                f"(expected steady {expected_connected}; {window_color}) "
                f"— {res.detail}"
            )
        hr.detail_lines = [res.detail]
        self.logger.info(
            f"  [HRT session-stat][{host}] (stable) [{hr.status}] {hr.reason}"
        )
        return hr

    def _eval_host_disruption(
        self,
        host: str,
        collector: t.Any,
        window_start: float,
        window_end: float,
        expected_connected: int,
        expected_during: int,
        impacted_lanes: t.List[int],
        impacted_tuples_by_device: t.Dict[str, t.List[int]],
        recovery_min_sec: float,
    ) -> _HostSessionResult:
        hr = _HostSessionResult(host)
        res = collector.evaluate_window(
            window_start=window_start,
            window_end=window_end,
            expected_connected=expected_connected,
            impacted_lanes=impacted_lanes,
            impacted_tuples_by_device=impacted_tuples_by_device,
            host=host,
        )
        if res.samples == 0:
            hr.status = "SKIP"
            hr.reason = f"No in-window HRT session samples — {res.detail}"
            hr.detail_lines = [res.detail]
            self.logger.info(
                f"  [HRT session-stat][{host}] (disruption) [SKIP] {hr.reason}"
            )
            return hr

        # Signal 1: census dropped to expected_during during the disruption, and
        # every requested impacted lane churned (connected dropped below total).
        drop_ok = res.min_connected is not None and res.min_connected <= expected_during
        tuple_keys = [
            f"dev{int(device_id)}/L{int(local_plane)}"
            for device_id, local_planes in impacted_tuples_by_device.items()
            for local_plane in local_planes
        ]
        if tuple_keys:
            churn_ok = all(
                res.impacted_tuple_churn.get(key, False) for key in tuple_keys
            )
            churn_label = "impacted-tuple churn"
            churn_detail = _tuple_churn_str(res, tuple_keys)
        else:
            churn_ok = all(
                res.impacted_lane_churn.get(lane, False) for lane in impacted_lanes
            )
            churn_label = "impacted-lane churn"
            churn_detail = _churn_str(res, impacted_lanes)
        signal1_ok = drop_ok and churn_ok
        signal1_msg = (
            f"Signal1[drop]: min_connected={res.min_connected} "
            f"(<= {expected_during} expected during) "
            f"{'OK' if drop_ok else 'FAIL'}; {churn_label} "
            f"{'OK' if churn_ok else 'FAIL'} ({churn_detail})"
        )

        # Signal 2: census recovered to expected and held >= recovery_min_sec.
        recover_ok, _held_sec, recover_detail = collector.evaluate_recovery_hold(
            window_start=window_start,
            window_end=window_end,
            expected_connected=expected_connected,
            recovery_min_sec=recovery_min_sec,
            host=host,
        )
        signal2_msg = f"Signal2[recover]: {recover_detail}"

        timeout_count = collector.timeout_count_in_window(
            window_start, window_end, host=host
        )
        passed = signal1_ok and recover_ok and timeout_count == 0
        hr.status = "PASS" if passed else "FAIL"
        hr.reason = f"{signal1_msg} | {signal2_msg}"
        if timeout_count > 0:
            hr.reason = (
                f"{timeout_count} poll timeout(s) recorded null data | {hr.reason}"
            )
        hr.detail_lines = [signal1_msg, signal2_msg, res.detail]
        if passed:
            self.logger.info(
                f"  [HRT session-stat][{host}] (disruption) [PASS] {hr.reason}"
            )
        else:
            self.logger.error(
                f"  [HRT session-stat][{host}] (disruption) [FAIL] {hr.reason}"
            )
        return hr


def _format_report(
    host_results: t.List[_HostSessionResult], mode: str, agg: str
) -> str:
    """Human-readable multi-host report (this is the everpaste'd message)."""
    lines: t.List[str] = []
    lines.append(f"HRT session-stat ({mode}) — {len(host_results)} host(s)")
    for hr in host_results:
        lines.append(f"[{hr.host}] VERDICT {hr.status} | {hr.reason}")
    lines.append(f"AGGREGATE: {agg}")
    return "\n".join(lines)


def host_label(res: t.Any) -> str:
    return getattr(res, "host", "?")


def _churn_str(res: t.Any, impacted_lanes: t.List[int]) -> str:
    if not impacted_lanes:
        return "no impacted lanes"
    return ", ".join(
        f"L{lane}={'yes' if res.impacted_lane_churn.get(lane, False) else 'no'}"
        for lane in impacted_lanes
    )


def _tuple_churn_str(res: t.Any, tuple_keys: t.List[str]) -> str:
    if not tuple_keys:
        return "no impacted tuples"
    return ", ".join(
        f"{key}={'yes' if res.impacted_tuple_churn.get(key, False) else 'no'}"
        for key in sorted(tuple_keys)
    )
