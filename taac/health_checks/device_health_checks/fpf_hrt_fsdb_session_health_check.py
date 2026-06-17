# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.libs.fpf.fpf_collector_registry import (
    disruption_inconclusive_skip,
    get_allow_baseline_failures,
    get_baseline_impaired_lanes,
    set_baseline_impaired_lanes,
)
from taac.libs.fpf.fpf_hrt_polling import get_hrt_client
from taac.health_check.health_check import types as hc_types

EXPECTED_FSDB_SESSION_COUNT = 32
PLANES_PER_GPU = 8


def _is_connected(session: t.Any) -> bool:
    return str(getattr(session, "state", None)) == "CONNECTED"


class FpfHrtFsdbSessionHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    """Health check verifying HRT FSDB sessions are CONNECTED on GPU hosts.

    HRT runs on rtptest GPU hosts, not on GTSW/STSW switches. Pass the GPU
    hostnames via ``check_params["hosts"]``. The check connects to HRT
    (port 5909) and queries ``getFsdbSessions()`` (each session carries
    ``device_id`` = GPU and ``plane_id`` = lane) on every host.

    Two independent signals are asserted per host:

      Signal 1 (overall): the total number of CONNECTED sessions equals
        ``expected_session_count`` (default 32 = 4 GPUs x 8 GTSWs) minus the
        number of impacted (gpu, lane) links for that host. This proves that
        disrupting one link does not collateral-damage any other session.

      Signal 2 (per-device reconciliation): on ``reconcile_device_id``
        (default GPU 0), every impacted lane must NOT be CONNECTED and every
        non-impacted lane must be CONNECTED.

    ``impacted_lanes_by_host_gpu`` maps host -> {gpu_id -> [lanes]}; when it is
    absent/empty the check degrades to the stable-state contract (all sessions
    CONNECTED), so the same check is reused unchanged for stable-state, enable,
    undrain, and link-drain (control-up) tests.
    """

    CHECK_NAME = hc_types.CheckName.FPF_HRT_FSDB_SESSION_CHECK
    CHECK_SCOPE = hc_types.Scope.DEFAULT
    OPERATING_SYSTEMS = ["FBOSS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        hosts = check_params.get("hosts", [])
        if not hosts:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message="No GPU hosts specified in check_params['hosts']",
            )

        gpu_hosts = []
        for host in hosts:
            if not host.startswith("rtptest"):
                self.logger.warning(
                    f"Host {host} is not a GPU host (expected 'rtptest' prefix), "
                    f"skipping HRT check — HRT only runs on rtptest hosts"
                )
                continue
            gpu_hosts.append(host)

        if not gpu_hosts:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message="No valid rtptest GPU hosts after filtering",
            )

        expected_count = check_params.get(
            "expected_session_count", EXPECTED_FSDB_SESSION_COUNT
        )
        planes_per_gpu = int(check_params.get("planes_per_gpu", PLANES_PER_GPU))
        reconcile_device_id = int(check_params.get("reconcile_device_id", 0))
        # host -> {gpu_id(str|int) -> [lanes]}; normalize gpu keys to int below.
        impacted_map = check_params.get("impacted_lanes_by_host_gpu", {}) or {}
        if impacted_map:
            _skip = disruption_inconclusive_skip()
            if _skip:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.SKIP, message=_skip
                )

        num_gpus = max(1, expected_count // max(1, planes_per_gpu))
        allow_baseline = get_allow_baseline_failures()
        baseline = get_baseline_impaired_lanes()

        all_results = []
        any_fail = False
        observed_down: t.Dict[str, t.Set[int]] = {}

        for host in gpu_hosts:
            host_impacted = {
                int(gpu): set(lanes)
                for gpu, lanes in (impacted_map.get(host, {}) or {}).items()
            }
            # Fold baseline-impaired lanes into "expected down" only in the
            # disrupt postcheck (impacted_map set) when the config opted in.
            baseline_lanes = (
                set(baseline.get(host, set()))
                if (allow_baseline and impacted_map)
                else set()
            )
            result, down_lanes = await self._check_host(
                host,
                expected_count,
                host_impacted,
                reconcile_device_id,
                planes_per_gpu,
                num_gpus,
                baseline_lanes,
            )
            observed_down[host] = down_lanes
            all_results.append(result)
            if result.status == hc_types.HealthCheckStatus.FAIL:
                any_fail = True

        # In the baseline/stable context (no test-impacted lanes — i.e. the
        # precheck), record which lanes are already down so the disrupt
        # postcheck can exclude them as PRE-EXISTING.
        if not impacted_map:
            set_baseline_impaired_lanes(observed_down)

        messages = [r.message for r in all_results]
        # pyrefly: ignore [no-matching-overload]
        combined = "; ".join(messages)

        if any_fail:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=combined,
            )

        has_skip = any(r.status == hc_types.HealthCheckStatus.SKIP for r in all_results)
        if has_skip:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=combined,
            )

        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=combined,
        )

    async def _check_host(
        self,
        hostname: str,
        expected_count: int,
        impacted_by_gpu: t.Dict[int, t.Set[int]],
        reconcile_device_id: int,
        planes_per_gpu: int,
        num_gpus: int = 4,
        baseline_lanes: t.Optional[t.Set[int]] = None,
    ) -> t.Tuple[hc_types.HealthCheckResult, t.Set[int]]:
        """Returns (result, observed_down_lanes). ``baseline_lanes`` (when the
        config opted in) are treated as additional expected-down lanes on every
        GPU, so a known-degraded lab lane is PRE-EXISTING, not a regression."""
        baseline_lanes = baseline_lanes or set()
        total_impacted = sum(len(lanes) for lanes in impacted_by_gpu.values())
        # Expected-down total = test-impacted (per gpu) folded with baseline
        # lanes (every gpu). Overall expectation subtracts both.
        expected_down_total = sum(
            len(impacted_by_gpu.get(gpu, set()) | baseline_lanes)
            for gpu in range(num_gpus)
        )
        expected_overall = expected_count - expected_down_total
        base_note = (
            f" excl. baseline lanes {sorted(baseline_lanes)}" if baseline_lanes else ""
        )
        self.logger.info(
            f"Running FPF HRT FSDB session check on {hostname}: expecting "
            f"{expected_overall} CONNECTED overall ({expected_count} - "
            f"{expected_down_total} expected-down{base_note}); "
            f"reconciling GPU {reconcile_device_id}"
        )

        try:
            client = await get_hrt_client(hostname)
        except Exception as e:
            self.logger.warning(f"Failed to connect to HRT on {hostname}: {e}")
            return (
                hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.SKIP,
                    message=f"Failed to connect to HRT on {hostname}: {e}",
                ),
                set(),
            )

        try:
            async with client:
                sessions = await client.getFsdbSessions()
        except Exception as e:
            self.logger.warning(
                f"Failed to get FSDB sessions from HRT on {hostname}: {e}"
            )
            return (
                hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.SKIP,
                    message=f"Failed to get FSDB sessions from HRT on {hostname}: {e}",
                ),
                set(),
            )

        total_sessions = len(sessions)
        connected_count = sum(1 for s in sessions if _is_connected(s))

        # Enumerate the non-CONNECTED sessions (GPU/lane/state) for triage, and
        # collect the down lane ids (union across GPUs) for baseline recording.
        down_sessions = []
        down_lanes: t.Set[int] = set()
        for s in sessions:
            if _is_connected(s):
                continue
            dev = getattr(s, "device_id", "?")
            lane = getattr(s, "plane_id", "?")
            down_sessions.append(f"GPU{dev}/lane{lane}={getattr(s, 'state', None)}")
            if isinstance(lane, int):
                down_lanes.add(lane)
        down_sessions.sort()

        # ---- Signal 1: overall CONNECTED count == expected - expected-down ---
        signal1_ok = connected_count == expected_overall
        signal1_msg = (
            f"Signal1[overall]: {connected_count}/{total_sessions} CONNECTED "
            f"(expected {expected_overall}{base_note})"
        )
        if down_sessions:
            signal1_msg += " — DOWN: " + ", ".join(down_sessions[:16])
            if len(down_sessions) > 16:
                signal1_msg += f" (+{len(down_sessions) - 16} more)"
            self.logger.info(
                f"{hostname} non-CONNECTED FSDB sessions ({len(down_sessions)}): "
                + ", ".join(down_sessions)
            )

        # ---- Signal 2: per-device reconciliation on reconcile_device_id -----
        # Skipped in the pure stable/precheck context (no test-impacted lanes);
        # Signal 1 governs there. Baseline lanes are folded into expected-down.
        dev_impacted = impacted_by_gpu.get(reconcile_device_id, set()) | baseline_lanes
        if total_impacted == 0:
            signal2_msg = (
                f"Signal2[GPU{reconcile_device_id} reconcile]: skipped "
                f"(no impacted lanes — Signal 1 governs)"
            )
            summary = f"{hostname}: {signal1_msg} | {signal2_msg}"
            if signal1_ok:
                self.logger.info(summary)
                return (
                    hc_types.HealthCheckResult(
                        status=hc_types.HealthCheckStatus.PASS, message=summary
                    ),
                    down_lanes,
                )
            self.logger.error(summary)
            return (
                hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL, message=summary
                ),
                down_lanes,
            )

        signal2_ok, signal2_msg = self._reconcile_device(
            sessions, reconcile_device_id, dev_impacted, planes_per_gpu
        )

        passed = signal1_ok and signal2_ok
        summary = f"{hostname}: {signal1_msg} | {signal2_msg}"
        if passed:
            self.logger.info(summary)
            return (
                hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.PASS, message=summary
                ),
                down_lanes,
            )

        self.logger.error(summary)
        return (
            hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL, message=summary
            ),
            down_lanes,
        )

    def _reconcile_device(
        self,
        sessions: t.Sequence[t.Any],
        reconcile_device_id: int,
        dev_impacted: t.Set[int],
        planes_per_gpu: int,
    ) -> t.Tuple[bool, str]:
        """Signal 2: on ``reconcile_device_id``, impacted lanes must be DOWN and
        every other lane must be present and CONNECTED. Returns (ok, message)."""
        dev_sessions = [
            s for s in sessions if getattr(s, "device_id", None) == reconcile_device_id
        ]
        problems: t.List[str] = []
        seen_lanes: t.Set[int] = set()
        for s in dev_sessions:
            lane = getattr(s, "plane_id", None)
            if lane is None:
                continue
            lane = int(lane)
            seen_lanes.add(lane)
            connected = _is_connected(s)
            if lane in dev_impacted and connected:
                problems.append(f"lane {lane} expected DOWN but CONNECTED")
            elif lane not in dev_impacted and not connected:
                problems.append(
                    f"lane {lane} expected CONNECTED but state={getattr(s, 'state', None)}"
                )
        # Non-impacted lanes entirely missing from the list are also a failure.
        for lane in range(planes_per_gpu):
            if lane not in dev_impacted and lane not in seen_lanes:
                problems.append(f"lane {lane} expected CONNECTED but session missing")

        dev_connected = sum(1 for s in dev_sessions if _is_connected(s))
        msg = (
            f"Signal2[GPU{reconcile_device_id} reconcile]: {dev_connected} CONNECTED, "
            f"impacted lanes {sorted(dev_impacted) or '[]'} expected DOWN"
        )
        if problems:
            msg += " — " + "; ".join(problems[:8])
        return (not problems, msg)
