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
    get_baseline_impaired_tuples,
    set_baseline_impaired_lanes,
    set_baseline_impaired_tuples,
)
from taac.libs.fpf.fpf_hrt_polling import get_hrt_client
from taac.health_check.health_check import types as hc_types

EXPECTED_FSDB_SESSION_COUNT = 32
PLANES_PER_GPU = 8
PLANES_PER_PAIRED_DEVICE = 4
GPU_HOST_PREFIXES = ("rtptest", "twshared")


def _is_connected(session: t.Any) -> bool:
    return str(getattr(session, "state", None)) == "CONNECTED"


def _paired_device_tuple(gpu_id: int, global_lane: int) -> t.Tuple[int, int]:
    """Translate a GPU/global-lane pair to the new SDK device/local-plane key."""
    return (2 * gpu_id + global_lane // PLANES_PER_PAIRED_DEVICE, global_lane % 4)


def _normalize_tuple_map(
    raw: t.Mapping[str, t.Mapping[t.Union[str, int], t.Iterable[int]]],
) -> t.Dict[str, t.Set[t.Tuple[int, int]]]:
    return {
        host: {
            (int(device_id), int(local_plane))
            for device_id, local_planes in devices.items()
            for local_plane in local_planes
        }
        for host, devices in raw.items()
    }


class FpfHrtFsdbSessionHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    """Health check verifying HRT FSDB sessions are CONNECTED on GPU hosts.

    HRT runs on rtptest/twshared GPU hosts, not on GTSW/STSW switches. Pass the GPU
    hostnames via ``check_params["hosts"]``. The check connects to HRT
    (port 5909) and queries ``getFsdbSessions()`` (each session carries
    ``device_id`` and local ``plane_id``) on every host.

    Two independent signals are asserted per host:

      Signal 1 (overall): the total number of CONNECTED expected tuples equals
        ``expected_session_count`` minus the exact impacted tuples.

      Signal 2 (tuple reconciliation): every expected
        ``(host, device_id, local_plane)`` is checked independently. An impacted
        tuple must not be CONNECTED; every other tuple must be present and
        CONNECTED.

    New-SDK callers pass ``device_ids`` (normally 0..7),
    ``planes_per_device=4``, and optionally
    ``impacted_tuples_by_host_device``. Legacy RTP callers may omit those
    parameters and retain the historical four-device/eight-plane model.
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
            if not host.startswith(GPU_HOST_PREFIXES):
                self.logger.warning(
                    f"Host {host} is not a GPU host (expected one of "
                    f"{GPU_HOST_PREFIXES}), skipping HRT check"
                )
                continue
            gpu_hosts.append(host)

        if not gpu_hosts:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message="No valid GPU hosts after filtering",
            )

        expected_count = check_params.get(
            "expected_session_count", EXPECTED_FSDB_SESSION_COUNT
        )
        explicit_device_ids = check_params.get("device_ids")
        paired_device_model = explicit_device_ids is not None
        planes_per_device = int(
            check_params.get(
                "planes_per_device",
                PLANES_PER_PAIRED_DEVICE if paired_device_model else PLANES_PER_GPU,
            )
        )
        if explicit_device_ids is None:
            num_devices = max(1, expected_count // max(1, planes_per_device))
            device_ids = list(range(num_devices))
        else:
            device_ids = sorted({int(device_id) for device_id in explicit_device_ids})
        expected_tuples = {
            (device_id, plane)
            for device_id in device_ids
            for plane in range(planes_per_device)
        }
        if len(expected_tuples) != expected_count:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    "Invalid HRT FSDB-session topology: "
                    f"{len(device_ids)} device(s) x {planes_per_device} plane(s) "
                    f"= {len(expected_tuples)}, expected_session_count="
                    f"{expected_count}"
                ),
            )
        # host -> {gpu_id(str|int) -> [lanes]}; normalize gpu keys to int below.
        impacted_map = check_params.get("impacted_lanes_by_host_gpu", {}) or {}
        tuple_impact_map = _normalize_tuple_map(
            check_params.get("impacted_tuples_by_host_device", {}) or {}
        )
        if impacted_map or tuple_impact_map:
            _skip = disruption_inconclusive_skip()
            if _skip:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.SKIP, message=_skip
                )

        allow_baseline = get_allow_baseline_failures()
        baseline_tuples = get_baseline_impaired_tuples()
        legacy_baseline = get_baseline_impaired_lanes()

        all_results = []
        any_fail = False
        observed_down: t.Dict[str, t.Set[t.Tuple[int, int]]] = {}

        for host in gpu_hosts:
            host_impacted = set(tuple_impact_map.get(host, set()))
            if not host_impacted:
                for gpu, lanes in (impacted_map.get(host, {}) or {}).items():
                    for lane in lanes:
                        host_impacted.add(
                            _paired_device_tuple(int(gpu), int(lane))
                            if paired_device_model
                            else (int(gpu), int(lane))
                        )
            # Multi-device baselines are exact tuple keys. Legacy lane-only
            # baselines are retained only for the old four-device/eight-plane
            # model; never project a local plane impairment across all devices.
            host_baseline = (
                set(baseline_tuples.get(host, set()))
                if allow_baseline and (impacted_map or tuple_impact_map)
                else set()
            )
            if (
                allow_baseline
                and not paired_device_model
                and impacted_map
                and not host_baseline
            ):
                host_baseline = {
                    (device_id, lane)
                    for device_id in device_ids
                    for lane in legacy_baseline.get(host, set())
                }
            result, down_tuples = await self._check_host(
                host,
                expected_count,
                host_impacted,
                expected_tuples,
                host_baseline,
            )
            observed_down[host] = down_tuples
            all_results.append(result)
            if result.status == hc_types.HealthCheckStatus.FAIL:
                any_fail = True

        # In the baseline/stable context (no test-impacted lanes — i.e. the
        # precheck), record which lanes are already down so the disrupt
        # postcheck can exclude them as PRE-EXISTING.
        if not impacted_map and not tuple_impact_map:
            set_baseline_impaired_tuples(observed_down)
            if paired_device_model:
                # Conservatively disable the legacy lane-only projection: local
                # plane L0 on dev0 is not the same physical beth as L0 on dev1.
                set_baseline_impaired_lanes({})
            else:
                set_baseline_impaired_lanes(
                    {
                        host: {plane for _device, plane in tuples}
                        for host, tuples in observed_down.items()
                    }
                )

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
        impacted_tuples: t.Set[t.Tuple[int, int]],
        expected_tuples: t.Set[t.Tuple[int, int]],
        baseline_tuples: t.Optional[t.Set[t.Tuple[int, int]]] = None,
    ) -> t.Tuple[hc_types.HealthCheckResult, t.Set[t.Tuple[int, int]]]:
        """Return the result and exact observed-down device/local-plane tuples."""
        baseline_tuples = baseline_tuples or set()
        expected_down = (impacted_tuples | baseline_tuples) & expected_tuples
        expected_down_total = len(expected_down)
        expected_overall = expected_count - expected_down_total
        base_note = (
            f" excl. baseline tuples {sorted(baseline_tuples)}"
            if baseline_tuples
            else ""
        )
        self.logger.info(
            f"Running FPF HRT FSDB session check on {hostname}: expecting "
            f"{expected_overall} CONNECTED overall ({expected_count} - "
            f"{expected_down_total} expected-down{base_note}); reconciling "
            f"{len(expected_tuples)} exact device/local-plane tuples"
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
        tuple_states: t.Dict[t.Tuple[int, int], t.List[t.Any]] = {}
        malformed = 0
        for s in sessions:
            device_id = getattr(s, "device_id", None)
            plane_id = getattr(s, "plane_id", None)
            if not isinstance(device_id, int) or not isinstance(plane_id, int):
                malformed += 1
                continue
            tuple_states.setdefault((device_id, plane_id), []).append(s)

        observed_down = {
            key
            for key in expected_tuples
            if key not in tuple_states
            or not any(_is_connected(s) for s in tuple_states[key])
        }
        connected_count = sum(
            1
            for key in expected_tuples
            if any(_is_connected(s) for s in tuple_states.get(key, []))
        )
        down_sessions = [
            f"dev{device_id}/L{plane_id}="
            + (
                "/".join(
                    sorted({str(getattr(s, "state", None)) for s in tuple_states[key]})
                )
                if key in tuple_states
                else "MISSING"
            )
            for key in sorted(observed_down)
            for device_id, plane_id in [key]
        ]

        # ---- Signal 1: overall CONNECTED count == expected - expected-down ---
        signal1_ok = connected_count == expected_overall and malformed == 0
        signal1_msg = (
            f"Signal1[overall]: {connected_count}/{total_sessions} CONNECTED "
            f"(expected {expected_overall}{base_note})"
        )
        if malformed:
            signal1_msg += f" — {malformed} malformed session(s) missing tuple identity"
        if down_sessions:
            signal1_msg += " — DOWN: " + ", ".join(down_sessions[:16])
            if len(down_sessions) > 16:
                signal1_msg += f" (+{len(down_sessions) - 16} more)"
            self.logger.info(
                f"{hostname} non-CONNECTED FSDB sessions ({len(down_sessions)}): "
                + ", ".join(down_sessions)
            )

        problems: t.List[str] = []
        for device_id, plane_id in sorted(expected_tuples):
            key = (device_id, plane_id)
            entries = tuple_states.get(key, [])
            connected = any(_is_connected(s) for s in entries)
            if len(entries) > 1:
                problems.append(f"dev{device_id}/L{plane_id} duplicated")
            if key in expected_down:
                if connected:
                    problems.append(f"dev{device_id}/L{plane_id} expected DOWN")
            elif not connected:
                state = (
                    "/".join(sorted({str(getattr(s, "state", None)) for s in entries}))
                    if entries
                    else "MISSING"
                )
                problems.append(
                    f"dev{device_id}/L{plane_id} expected CONNECTED, saw {state}"
                )
        unexpected = sorted(set(tuple_states) - expected_tuples)
        if unexpected:
            problems.append(f"unexpected tuples {unexpected}")
        signal2_ok = not problems
        signal2_msg = (
            f"Signal2[tuple reconcile]: {len(expected_tuples) - len(observed_down)}/"
            f"{len(expected_tuples)} exact tuples CONNECTED; expected DOWN "
            f"{sorted(expected_down) or '[]'}"
        )
        if problems:
            signal2_msg += " — " + "; ".join(problems[:8])

        passed = signal1_ok and signal2_ok
        summary = f"{hostname}: {signal1_msg} | {signal2_msg}"
        if passed:
            self.logger.info(summary)
            return (
                hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.PASS, message=summary
                ),
                observed_down,
            )

        self.logger.error(summary)
        return (
            hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL, message=summary
            ),
            observed_down,
        )
