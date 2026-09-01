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

# Registry name of the single plane-status collector (holds ALL hosts).
_COLLECTOR_NAME = "hrt_plane_status"


class _HostPlaneResult:
    """Per-host plane-status evaluation outcome."""

    def __init__(self, host: str) -> None:
        self.host = host
        self.status = "SKIP"  # PASS / FAIL / SKIP
        self.results: t.List[t.Any] = []
        self.timeout_count = 0


class FpfHrtPlaneStatusHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    """Per-device HRT plane-status check — the ``hrtctl show plane-status`` signal.

    Consumes the single live ``hrt_plane_status`` collector registered in the FPF
    collector registry. That ONE collector holds ALL monitored GPU hosts (each
    row carries its ``host``); this check iterates the hosts present in its rows
    and evaluates each host independently; every host must satisfy the contract.
    Each poll captures every configured device/local-plane tuple. New-SDK MWG2
    uses devices 0..7 with local planes 0..3; legacy RTP may retain one device
    with planes 0..7. Two contracts
    via ``mode``:

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

    The overall status is FAIL if any host violates its contract (or has poll
    timeouts), SKIP if no host produced in-window data, else PASS.
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
        collector = get_collector(check_params.get("collector_name", _COLLECTOR_NAME))
        if collector is None:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message="No live HRT plane-status collector in registry",
            )

        mode = check_params.get("mode", "all_up")
        # Blip-handling contract for the all_up assertion: "strict" (default),
        # "last_sample" (MODE A — disruptive coldboot/kill/reboot: only the last
        # sample must be UP; a mid-window transient that recovers is tolerated),
        # or "skip_null_strict" (MODE B — graceful: every non-null sample UP,
        # nulls tolerated). Ignored by the "drain" mode.
        stability_mode = check_params.get("stability_mode", "strict")
        expected_planes: t.Optional[t.List[int]] = check_params.get("expected_planes")
        device_ids: t.Optional[t.List[int]] = check_params.get("device_ids")
        impacted_planes: t.List[int] = [
            int(p) for p in (check_params.get("impacted_planes") or [])
        ]
        impacted_tuples_by_host_device: t.Dict[str, t.Dict[str, t.List[int]]] = (
            check_params.get("impacted_tuples_by_host_device", {}) or {}
        )

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
                default_start = max(default_start, disruption_ts)
        window_start = check_params.get("window_start", default_start)
        # all_up settle: skip the first settle_sec (restore-phase recovery
        # transient) before asserting every plane is UP.
        settle_sec = float(check_params.get("settle_sec", 0))
        if settle_sec > 0 and mode != "drain":
            window_start = min(window_start + settle_sec, window_end)

        # The single collector holds all hosts (each row carries its host); the
        # hosts to evaluate are those present in the in-window rows.
        hosts = collector.hosts_in_window(window_start, window_end)
        if not hosts:
            hosts = list(getattr(collector, "hosts", []) or [])

        host_results: t.List[_HostPlaneResult] = []
        for host in hosts:
            hr = self._evaluate_host(
                host,
                collector,
                mode,
                stability_mode,
                expected_planes,
                impacted_planes,
                device_ids,
                impacted_tuples_by_host_device.get(host, {}),
                window_start,
                window_end,
            )
            host_results.append(hr)

        if not host_results or all(hr.status == "SKIP" for hr in host_results):
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=(
                    "No in-window HRT plane-status samples on any host "
                    f"[{window_start:.0f}, {window_end:.0f}]"
                ),
            )

        agg_fail = any(hr.status == "FAIL" for hr in host_results)
        agg = "FAIL" if agg_fail else "PASS"

        report = _format_report(host_results, mode, agg)
        details = await everpaste_details_suffix(
            f"HRT plane-status ({mode}) — per-host / per-plane detail",
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

    def _evaluate_host(
        self,
        host: str,
        collector: t.Any,
        mode: str,
        stability_mode: str,
        expected_planes: t.Optional[t.List[int]],
        impacted_planes: t.List[int],
        device_ids: t.Optional[t.List[int]],
        impacted_tuples_by_device: t.Dict[str, t.List[int]],
        window_start: float,
        window_end: float,
    ) -> _HostPlaneResult:
        hr = _HostPlaneResult(host)
        self.logger.info(
            f"  [HRT plane-status][{host}] mode={mode} "
            f"devices={device_ids or getattr(collector, 'device_ids', '?')} "
            f"window: {window_start:.0f} to {window_end:.0f} "
            f"({window_end - window_start:.0f}s span)"
        )

        if mode == "drain":
            results = collector.evaluate_drain_window(
                window_start=window_start,
                window_end=window_end,
                impacted_planes=impacted_planes,
                expected_planes=expected_planes,
                host=host,
                device_ids=device_ids,
                impacted_tuples_by_device=impacted_tuples_by_device,
            )
        else:
            results = collector.evaluate_all_up_window(
                window_start=window_start,
                window_end=window_end,
                expected_planes=expected_planes,
                last_sample_only=(stability_mode == "last_sample"),
                skip_null_strict=(stability_mode == "skip_null_strict"),
                host=host,
                device_ids=device_ids,
            )
        hr.results = results
        hr.timeout_count = collector.timeout_count_in_window(
            window_start, window_end, host=host
        )

        for r in results:
            status = "PASS" if r.passed else "FAIL"
            self.logger.info(
                f"  [HRT plane-status][{host}] dev{r.device_id}/L{r.plane}: "
                f"[{status}] "
                f"expect={r.expected_state} {r.detail}"
            )

        # No in-window samples for THIS host => every plane result has samples==0
        # (the collector holds all hosts; a host with no rows yields empty-sample
        # per-plane results). Treat that as SKIP, not FAIL.
        no_samples = bool(results) and all(r.samples == 0 for r in results)
        if hr.timeout_count > 0:
            hr.status = "FAIL"
        elif not results or no_samples:
            hr.status = "SKIP"
        elif any(not r.passed for r in results):
            hr.status = "FAIL"
        else:
            hr.status = "PASS"
        return hr


def _format_report(host_results: t.List[_HostPlaneResult], mode: str, agg: str) -> str:
    """Human-readable multi-host report (this is the everpaste'd message)."""
    lines: t.List[str] = []
    lines.append(f"HRT plane-status ({mode}) — {len(host_results)} host(s)")
    for hr in host_results:
        if hr.timeout_count > 0:
            lines.append(
                f"[{hr.host}] VERDICT {hr.status} | "
                f"{hr.timeout_count} poll timeout(s) recorded null data"
            )
        elif not hr.results:
            lines.append(f"[{hr.host}] VERDICT {hr.status} | no in-window samples")
        else:
            failures = [r for r in hr.results if not r.passed]
            lines.append(
                f"[{hr.host}] VERDICT {hr.status} | "
                f"{len(hr.results) - len(failures)}/{len(hr.results)} plane(s) OK"
            )
            for r in failures:
                lines.append(
                    f"    dev{r.device_id}/L{r.plane}: [FAIL] "
                    f"expect={r.expected_state} "
                    f"observed={r.observed_state} — {r.detail}"
                )
    lines.append(f"AGGREGATE: {agg}")
    return "\n".join(lines)
