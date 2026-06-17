# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""FPF HRT FSDB-session-count statistics health check.

Consumes the live ``hrt_fsdb_session`` collector (one GPU host) registered in
the FPF collector registry. Each poll captures the total CONNECTED FSDB-session
count plus a per-lane breakdown. Two contracts via ``mode``:

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

Mirrors the everpaste-suffix + logging style of the plane-status check.
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


class FpfHrtSessionStatHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    """Postcheck over the ``hrt_fsdb_session`` collector — CONNECTED census.

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
        collector = get_collector("hrt_fsdb_session")
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
        recovery_min_sec = float(
            check_params.get("recovery_min_sec", DEFAULT_RECOVERY_MIN_SEC)
        )

        if mode == "disruption":
            _skip = disruption_inconclusive_skip()
            if _skip:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.SKIP, message=_skip
                )

        window_end = float(check_params.get("window_end", time.time()))
        tc_start = get_test_case_start_time()
        lookback_sec = check_params.get("lookback_sec", DEFAULT_LOOKBACK_SEC)
        default_start = tc_start if tc_start else window_end - lookback_sec
        window_start = float(check_params.get("window_start", default_start))

        host = getattr(collector, "host", "?")
        self.logger.info(
            f"  [HRT session-stat] mode={mode} host={host} "
            f"window: {window_start:.0f} to {window_end:.0f} "
            f"({window_end - window_start:.0f}s span)"
        )

        if mode == "stable":
            return await self._run_stable(
                collector, window_start, window_end, expected_connected
            )
        return await self._run_disruption(
            collector,
            window_start,
            window_end,
            expected_connected,
            expected_during,
            impacted_lanes,
            recovery_min_sec,
        )

    async def _run_stable(
        self,
        collector: t.Any,
        window_start: float,
        window_end: float,
        expected_connected: int,
    ) -> hc_types.HealthCheckResult:
        res = collector.evaluate_window(
            window_start=window_start,
            window_end=window_end,
            expected_connected=expected_connected,
        )
        # PASS iff every non-null sample held the full census (min == expected).
        ok = (
            res.samples > 0
            and res.min_connected == expected_connected
            and res.max_connected == expected_connected
        )
        if res.samples == 0:
            status = hc_types.HealthCheckStatus.SKIP
            reason = f"No in-window HRT session samples — {res.detail}"
        elif ok:
            status = hc_types.HealthCheckStatus.PASS
            reason = (
                f"CONNECTED held at {expected_connected} across {res.samples} "
                f"samples (no churn) — {res.detail}"
            )
        else:
            status = hc_types.HealthCheckStatus.FAIL
            reason = (
                f"CONNECTED dipped to {res.min_connected} "
                f"(expected steady {expected_connected}) — {res.detail}"
            )

        self.logger.info(f"  [HRT session-stat] (stable) [{status}] {reason}")
        details = await everpaste_details_suffix(
            "HRT session-stat (stable) — CONNECTED census detail",
            [res.detail],
            collectors=[collector],
            window_start=window_start,
            window_end=window_end,
            result_status=str(status).split(".")[-1],
            result_reason=reason[:300],
        )
        return hc_types.HealthCheckResult(status=status, message=reason + details)

    async def _run_disruption(
        self,
        collector: t.Any,
        window_start: float,
        window_end: float,
        expected_connected: int,
        expected_during: int,
        impacted_lanes: t.List[int],
        recovery_min_sec: float,
    ) -> hc_types.HealthCheckResult:
        res = collector.evaluate_window(
            window_start=window_start,
            window_end=window_end,
            expected_connected=expected_connected,
            impacted_lanes=impacted_lanes,
        )
        if res.samples == 0:
            reason = f"No in-window HRT session samples — {res.detail}"
            self.logger.info(f"  [HRT session-stat] (disruption) [SKIP] {reason}")
            details = await everpaste_details_suffix(
                "HRT session-stat (disruption) — CONNECTED census detail",
                [res.detail],
                collectors=[collector],
                window_start=window_start,
                window_end=window_end,
                result_status="SKIP",
                result_reason=reason[:300],
            )
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP, message=reason + details
            )

        # Signal 1: census dropped to expected_during during the disruption, and
        # every requested impacted lane churned (connected dropped below total).
        drop_ok = res.min_connected is not None and res.min_connected <= expected_during
        churn_ok = all(
            res.impacted_lane_churn.get(lane, False) for lane in impacted_lanes
        )
        signal1_ok = drop_ok and churn_ok
        signal1_msg = (
            f"Signal1[drop]: min_connected={res.min_connected} "
            f"(<= {expected_during} expected during) "
            f"{'OK' if drop_ok else 'FAIL'}; impacted-lane churn "
            f"{'OK' if churn_ok else 'FAIL'} ({_churn_str(res, impacted_lanes)})"
        )

        # Signal 2: census recovered to expected and held >= recovery_min_sec.
        recover_ok, held_sec, recover_detail = collector.evaluate_recovery_hold(
            window_start=window_start,
            window_end=window_end,
            expected_connected=expected_connected,
            recovery_min_sec=recovery_min_sec,
        )
        signal2_msg = f"Signal2[recover]: {recover_detail}"

        passed = signal1_ok and recover_ok
        status = (
            hc_types.HealthCheckStatus.PASS
            if passed
            else hc_types.HealthCheckStatus.FAIL
        )
        summary = f"{host_label(res)} — {signal1_msg} | {signal2_msg}"
        if passed:
            self.logger.info(f"  [HRT session-stat] (disruption) [PASS] {summary}")
        else:
            self.logger.error(f"  [HRT session-stat] (disruption) [FAIL] {summary}")

        details = await everpaste_details_suffix(
            "HRT session-stat (disruption) — CONNECTED census detail",
            [signal1_msg, signal2_msg, res.detail],
            collectors=[collector],
            window_start=window_start,
            window_end=window_end,
            result_status=str(status).split(".")[-1],
            result_reason=summary[:300],
        )

        timeout_count = collector.timeout_count_in_window(window_start, window_end)
        if timeout_count > 0:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    f"Got null data — {timeout_count} poll timeout(s) in window "
                    f"[{window_start:.0f}, {window_end:.0f}] | {summary}{details}"
                ),
            )
        return hc_types.HealthCheckResult(status=status, message=summary + details)


def host_label(res: t.Any) -> str:
    return getattr(res, "host", "?")


def _churn_str(res: t.Any, impacted_lanes: t.List[int]) -> str:
    if not impacted_lanes:
        return "no impacted lanes"
    return ", ".join(
        f"L{lane}={'yes' if res.impacted_lane_churn.get(lane, False) else 'no'}"
        for lane in impacted_lanes
    )
