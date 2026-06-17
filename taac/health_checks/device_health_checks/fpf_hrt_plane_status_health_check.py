# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

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


class FpfHrtPlaneStatusHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    """Per-device HRT plane-status check — the ``hrtctl show plane-status`` signal.

    Consumes the live ``hrt_plane_status`` collector (one GPU device) registered
    in the FPF collector registry. Each poll captures the State of every plane
    (beth0..beth7). Two contracts via ``mode``:

      mode="all_up" (default): every plane is UP across the whole window. Used
        for non-drained scenarios — baseline/precheck, interface enable, and
        link/device undrain. ``settle_sec`` advances the window start past a
        recovery transient (restore phase) so the re-up isn't flagged.

      mode="drain": the impacted plane(s) must be DRAINED by window end while
        every other plane stays UP. Used for link drain (TC17) and device drain
        (TC19) — from the GPU's plane-status view a device drain of the GTSW
        serving a plane is indistinguishable from a link drain of that plane.
        The window is anchored at the recorded disruption time so the impacted
        plane's pre-drain UP samples are excluded. SKIPs (inconclusive) when the
        disruption was verified ineffective.

    Status is FAIL if any plane violates its contract, SKIP if no in-window data,
    else PASS.
    """

    CHECK_NAME = hc_types.CheckName.FPF_HRT_PLANE_STATUS_CHECK
    CHECK_SCOPE = hc_types.Scope.DEFAULT
    OPERATING_SYSTEMS = ["FBOSS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        collector = get_collector("hrt_plane_status")
        if collector is None:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message="No live HRT plane-status collector in registry",
            )

        mode = check_params.get("mode", "all_up")
        expected_planes: t.Optional[t.List[int]] = check_params.get("expected_planes")
        impacted_planes: t.List[int] = [
            int(p) for p in (check_params.get("impacted_planes") or [])
        ]

        if mode == "drain":
            _skip = disruption_inconclusive_skip()
            if _skip:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.SKIP, message=_skip
                )

        window_end = check_params.get("window_end", time.time())
        tc_start = get_test_case_start_time()
        lookback_sec = check_params.get("lookback_sec", 900)
        default_start = tc_start if tc_start else window_end - lookback_sec
        # Drain: anchor at the disruption moment so the impacted plane's pre-drain
        # UP samples are excluded (a drain takes a few seconds to reflect).
        if mode == "drain":
            disruption_ts = get_disruption_time()
            if disruption_ts > 0:
                default_start = disruption_ts
        window_start = check_params.get("window_start", default_start)
        # all_up settle: skip the first settle_sec (restore-phase recovery
        # transient) before asserting every plane is UP.
        settle_sec = float(check_params.get("settle_sec", 0))
        if settle_sec > 0 and mode != "drain":
            window_start = min(window_start + settle_sec, window_end)

        self.logger.info(
            f"  [HRT plane-status] mode={mode} dev{getattr(collector, 'device_id', '?')} "
            f"window: {window_start:.0f} to {window_end:.0f} "
            f"({window_end - window_start:.0f}s span)"
        )

        if mode == "drain":
            results = collector.evaluate_drain_window(
                window_start=window_start,
                window_end=window_end,
                impacted_planes=impacted_planes,
                expected_planes=expected_planes,
            )
        else:
            results = collector.evaluate_all_up_window(
                window_start=window_start,
                window_end=window_end,
                expected_planes=expected_planes,
            )

        for r in results:
            status = "PASS" if r.passed else "FAIL"
            self.logger.info(
                f"  [HRT plane-status] Plane {r.plane}: [{status}] "
                f"expect={r.expected_state} {r.detail}"
            )

        failures = [r for r in results if not r.passed]
        details = await everpaste_details_suffix(
            f"HRT plane-status ({mode}) — per-plane detail",
            [
                f"Plane {r.plane}: [{'PASS' if r.passed else 'FAIL'}] "
                f"expect={r.expected_state} observed={r.observed_state} — {r.detail}"
                for r in results
            ],
            collectors=[collector],
            window_start=window_start,
            window_end=window_end,
            result_status=("FAIL" if failures else "PASS"),
            result_reason="; ".join(f"Plane {r.plane}: {r.detail}" for r in failures)[
                :300
            ],
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

        if not results:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=(
                    "No in-window HRT plane-status samples "
                    f"[{window_start:.0f}, {window_end:.0f}]{details}"
                ),
            )

        if failures:
            fail_summary = "; ".join(f"Plane {r.plane}: {r.detail}" for r in failures)
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=fail_summary + details,
            )
        pass_summary = "; ".join(f"Plane {r.plane}={r.observed_state}" for r in results)
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=f"All planes OK ({mode}) — {pass_summary}{details}",
        )
