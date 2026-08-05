# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Spec 2.7.5: Update Group formation from a verified zero state."""

import ipaddress
import typing as t

from taac.health_checks.healthcheck_definitions import (
    create_bgp_update_group_check,
    create_hardware_capacity_check,
    create_memory_utilization_check,
    create_service_restart_check,
    create_system_cpu_load_average_check,
)
from taac.stages.stage_definitions import (
    create_concurrent_steps_stage,
    create_steps_stage,
)
from taac.steps.step_definitions import (
    create_advertise_withdraw_prefixes_step,
    create_bgp_agent_log_artifact_step,
    create_bgp_lifecycle_convergence_step,
    create_bgp_update_group_state_step,
    create_custom_step,
    create_daemon_control_step,
    create_hardware_capacity_delta_step,
    create_ixia_device_group_toggle_step,
    create_longevity_step,
    create_prepare_compact_bgp_prefix_pool_step,
    create_record_jq_timestamp_step,
    create_snapshot_bgp_sent_route_counts_step,
    create_verify_bgp_sent_route_count_delta_step,
)
from taac.task_definitions import create_standard_periodic_tasks
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config.types import (
    Playbook,
    PointInTimeHealthCheck,
    SnapshotHealthCheck,
    Step,
)


_EXPECTED_SESSIONS = 1272
_EXPECTED_GROUPS = 4
_EXPECTED_DEVICE_GROUPS = 18
_EXPECTED_RECEIVERS_PER_AFI = 496
_EXPECTED_ROUTE_AFIS = frozenset({"ipv4", "ipv6"})
_EXPECTED_ALL_PEER_AFIS = {4: 636, 6: 636}
_ROUTE_DELTA = 100
_STRICT_MEMORY_LIMIT_BYTES = 9_999_999_999
_STRICT_MEMORY_GROWTH_BYTES = 199_999_999
_SOAK_SECONDS = 1800.0
_RESTART_TIME_VAR = "bgp_cold_start_restart_time"
_FORMATION_TIME_VAR = "bgp_cold_start_formation_t0"
_NON_GATING_ECMP_LEVEL_LIMIT = 2**63 - 1


def _validate_wire_inputs(
    capture_interfaces: t.Sequence[str],
    dut_source_addresses: t.Sequence[str],
    runtime_update_interfaces: t.Sequence[str],
) -> tuple[tuple[str, str], tuple[str, ...], tuple[str, ...]]:
    interfaces = tuple(capture_interfaces)
    if (
        len(interfaces) != 2
        or len(set(interfaces)) != 2
        or any(not interface.strip() for interface in interfaces)
    ):
        raise ValueError(
            "2.7.5 requires exactly two unique non-empty capture interfaces"
        )
    normalized_sources = []
    for raw_address in dut_source_addresses:
        try:
            normalized_sources.append(str(ipaddress.ip_address(raw_address)))
        except ValueError as error:
            raise ValueError(
                f"2.7.5 DUT wire source {raw_address!r} is not a valid IP address"
            ) from error
    if (
        len(normalized_sources) != _EXPECTED_SESSIONS
        or len(set(normalized_sources)) != _EXPECTED_SESSIONS
    ):
        raise ValueError("2.7.5 requires exactly 1272 unique DUT wire source addresses")
    runtime_interfaces = tuple(runtime_update_interfaces)
    if (
        not runtime_interfaces
        or len(set(runtime_interfaces)) != len(runtime_interfaces)
        or not set(runtime_interfaces) <= set(interfaces)
    ):
        raise ValueError(
            "2.7.5 runtime-update interfaces must be a unique non-empty subset "
            "of capture interfaces"
        )
    return (
        t.cast(tuple[str, str], interfaces),
        tuple(normalized_sources),
        runtime_interfaces,
    )


def _validate_route_inputs(
    pools: t.Mapping[str, str],
    receivers: t.Mapping[str, t.Sequence[str]],
    all_peer_addresses: t.Sequence[str],
) -> dict[str, tuple[str, ...]]:
    if set(pools) != _EXPECTED_ROUTE_AFIS or set(receivers) != _EXPECTED_ROUTE_AFIS:
        raise ValueError("route pools and receiver scopes must contain ipv4 and ipv6")
    if any(not value for value in pools.values()) or len(set(pools.values())) != len(
        _EXPECTED_ROUTE_AFIS
    ):
        raise ValueError(
            f"2.7.5 requires {len(_EXPECTED_ROUTE_AFIS)} distinct non-empty "
            "route-pool regexes"
        )
    _validate_all_peer_addresses(all_peer_addresses)
    return {
        afi: _validate_receiver_addresses(afi, receivers[afi])
        for afi in ("ipv4", "ipv6")
    }


def _validate_receiver_addresses(
    afi: str, receiver_scopes: t.Sequence[str]
) -> tuple[str, ...]:
    expected_version = 4 if afi == "ipv4" else 6
    networks = []
    for receiver_scope in receiver_scopes:
        try:
            networks.append(ipaddress.ip_network(receiver_scope, strict=False))
        except ValueError as error:
            raise ValueError(
                f"2.7.5 {afi} receivers contain invalid host prefix {receiver_scope!r}"
            ) from error
    if any(
        network.version != expected_version
        or network.prefixlen != network.max_prefixlen
        for network in networks
    ):
        raise ValueError(
            f"2.7.5 {afi} receivers must be individual host addresses or host prefixes"
        )
    addresses = tuple(str(network.network_address) for network in networks)
    if len(addresses) != _EXPECTED_RECEIVERS_PER_AFI or len(set(addresses)) != len(
        addresses
    ):
        raise ValueError(
            f"2.7.5 requires exactly {_EXPECTED_RECEIVERS_PER_AFI} unique {afi} "
            "iBGP receivers"
        )
    return addresses


def _validate_all_peer_addresses(addresses: t.Sequence[str]) -> None:
    if (
        len(addresses) != _EXPECTED_SESSIONS
        or len(set(addresses)) != _EXPECTED_SESSIONS
    ):
        raise ValueError("all_peer_addresses must contain exactly 1272 unique peers")
    counts = {4: 0, 6: 0}
    for raw_address in addresses:
        try:
            address = ipaddress.ip_address(raw_address)
        except ValueError as error:
            raise ValueError(
                f"all_peer_addresses contains invalid address {raw_address!r}"
            ) from error
        counts[address.version] += 1
    if counts != _EXPECTED_ALL_PEER_AFIS:
        raise ValueError(
            "all_peer_addresses must contain exactly 636 IPv4 and 636 IPv6 "
            f"peers; got {counts}"
        )


def _state_step(
    device_name: str,
    action: str,
    state_key: str,
    *,
    continuity: str = "none",
) -> Step:
    action_params: dict[str, t.Any] | None = None
    if action in {"capture", "compare"}:
        action_params = {
            "expected_group_count": _EXPECTED_GROUPS,
            "expected_session_count": _EXPECTED_SESSIONS,
            "operational_continuity": continuity,
            "require_uniform_sent_route_counts": True,
            "require_equal_sent_route_counts": False,
            "expected_group_states": ["IDLE"],
        }
    elif action == "verify_zero":
        action_params = {
            "expected_configured_session_count": _EXPECTED_SESSIONS,
            "timeout_seconds": 180.0,
            "poll_interval_seconds": 2.0,
        }
    elif action == "formation_monitor":
        action_params = {
            "expected_group_count": _EXPECTED_GROUPS,
            "expected_session_count": _EXPECTED_SESSIONS,
            "timeout_seconds": 600.0,
            "poll_interval_seconds": 2.0,
            "expected_group_states": ["IDLE"],
        }
    elif action == "wait_formation_monitor_armed":
        action_params = {
            "timeout_seconds": 60.0,
        }
    elif action == "monitor":
        action_params = {
            "case": "strict",
            "duration_seconds": _SOAK_SECONDS,
            "poll_interval_seconds": 30.0,
            "expected_group_count": _EXPECTED_GROUPS,
            "expected_session_count": _EXPECTED_SESSIONS,
            "expected_group_states": ["IDLE"],
        }
    elif action != "clear":
        raise ValueError(f"Unsupported 2.7.5 state action {action!r}")
    return create_bgp_update_group_state_step(
        device_name,
        action,
        state_key,
        action_params=action_params,
        description=f"2.7.5 {action} Update Group state",
    )


def _capacity_step(device_name: str, action: str, state_key: str) -> Step:
    return create_hardware_capacity_delta_step(
        device_name,
        action,
        state_key,
        max_current_delta=100,
        max_high_watermark_increase=100,
        description=f"2.7.5 {action} FEC/ECMP capacity delta baseline",
    )


def _wire_step(
    device_name: str,
    state_key: str,
    action: str,
    *,
    capture_interfaces: t.Sequence[str] = (),
    dut_source_addresses: t.Sequence[str] = (),
    runtime_update_interfaces: t.Sequence[str] = (),
) -> Step:
    params: dict[str, t.Any] = {
        "custom_step_name": "bgp_cold_start_wire_monitor",
        "hostname": device_name,
        "action": action,
        "state_key": state_key,
    }
    if action == "start":
        params.update(
            {
                "capture_interfaces": list(capture_interfaces),
                "dut_source_addresses": list(dut_source_addresses),
            }
        )
    elif action == "rebaseline":
        params["runtime_update_interfaces"] = list(runtime_update_interfaces)
    elif action == "verify":
        params["minimum_post_t1_duration_seconds"] = _SOAK_SECONDS
    return create_custom_step(
        params_dict=params,
        description=f"2.7.5 {action} segmented two-port BGP wire evidence",
    )


def _route_toggle_steps(
    device_name: str,
    pools: t.Mapping[str, str],
    *,
    advertise: bool,
    phase: str,
) -> list[Step]:
    return [
        create_advertise_withdraw_prefixes_step(
            device_name=device_name,
            advertise=advertise,
            prefix_pool_regex=pools[afi],
            prefix_start_index=0,
            prefix_end_index=100,
            expected_prefix_pool_count=1,
            expected_number_of_addresses=_ROUTE_DELTA,
            runtime_route_operation=True,
            description=f"2.7.5 {phase}: {'advertise' if advertise else 'withdraw'} {afi} pool",
        )
        for afi in ("ipv4", "ipv6")
    ]


def _route_prepare_steps(
    device_name: str,
    pools: t.Mapping[str, str],
    phase: str,
) -> list[Step]:
    return [
        create_prepare_compact_bgp_prefix_pool_step(
            device_name=device_name,
            prefix_pool_regex=pools[afi],
            target_number_of_addresses=_ROUTE_DELTA,
            allowed_current_number_of_addresses=(_ROUTE_DELTA,),
            safe_number_of_addresses=_ROUTE_DELTA,
            description=f"2.7.5 {phase}: verify inactive 100-route {afi} pool",
        )
        for afi in ("ipv4", "ipv6")
    ]


def _route_snapshot_steps(
    device_name: str,
    state_key: str,
    receivers: t.Mapping[str, t.Sequence[str]],
) -> list[Step]:
    return [
        create_snapshot_bgp_sent_route_counts_step(
            hostname=device_name,
            snapshot_key=f"{state_key}:{afi}",
            peer_addrs=list(receivers[afi]),
            description=f"2.7.5 snapshot all 496 {afi} iBGP receivers",
        )
        for afi in ("ipv4", "ipv6")
    ]


def _all_peer_snapshot_step(
    device_name: str,
    snapshot_key: str,
    all_peer_addresses: t.Sequence[str],
    description: str,
) -> Step:
    return create_snapshot_bgp_sent_route_counts_step(
        hostname=device_name,
        snapshot_key=snapshot_key,
        peer_addrs=list(all_peer_addresses),
        description=description,
    )


def _all_peer_parity_step(
    device_name: str,
    snapshot_key: str,
    all_peer_addresses: t.Sequence[str],
    description: str,
    *,
    converge_from_formation_t0: bool = False,
) -> Step:
    return create_verify_bgp_sent_route_count_delta_step(
        hostname=device_name,
        snapshot_key=snapshot_key,
        peer_addrs=list(all_peer_addresses),
        min_delta=0,
        max_delta=0,
        tolerance=0,
        convergence_hard_timeout_seconds=(
            600.0 if converge_from_formation_t0 else None
        ),
        convergence_poll_interval_seconds=(5.0 if converge_from_formation_t0 else None),
        convergence_stability_window_seconds=(
            30.0 if converge_from_formation_t0 else None
        ),
        convergence_trigger_time_jq_var=(
            _FORMATION_TIME_VAR if converge_from_formation_t0 else None
        ),
        description=description,
    )


def _route_verify_steps(
    device_name: str,
    state_key: str,
    receivers: t.Mapping[str, t.Sequence[str]],
    delta: int,
) -> list[Step]:
    return [
        create_verify_bgp_sent_route_count_delta_step(
            hostname=device_name,
            snapshot_key=f"{state_key}:{afi}",
            peer_addrs=list(receivers[afi]),
            min_delta=delta,
            max_delta=delta,
            tolerance=0,
            description=f"2.7.5 require exact {delta:+d} at all 496 {afi} iBGP peers",
        )
        for afi in ("ipv4", "ipv6")
    ]


def _bounded_checks(
    checks: t.Sequence[PointInTimeHealthCheck],
    peer_groups: t.Sequence[str],
    member_counts: t.Mapping[str, int],
    afis: t.Mapping[str, str],
    *,
    fec_threshold: int,
    enforce_absolute_high_watermarks: bool = False,
) -> list[PointInTimeHealthCheck]:
    return [
        *checks,
        create_bgp_update_group_check(
            peer_group_substrings=list(peer_groups),
            expected_member_counts=dict(member_counts),
            expected_afi_by_substring=dict(afis),
            expected_out_delay_seconds_by_substring=dict.fromkeys(peer_groups, 0),
            expected_group_count=_EXPECTED_GROUPS,
            expected_group_states=["IDLE"],
            expect_enabled=True,
        ),
        create_hardware_capacity_check(
            fec_threshold=fec_threshold,
            ecmp_threshold=999,
            fec_high_watermark_threshold=(
                fec_threshold if enforce_absolute_high_watermarks else None
            ),
            ecmp_high_watermark_threshold=(
                999 if enforce_absolute_high_watermarks else None
            ),
            max_ecmp_level1=_NON_GATING_ECMP_LEVEL_LIMIT,
            max_ecmp_level2=_NON_GATING_ECMP_LEVEL_LIMIT,
            max_ecmp_level3=_NON_GATING_ECMP_LEVEL_LIMIT,
            watermark_delta_threshold=100,
            check_watermarks=False,
        ),
        create_system_cpu_load_average_check(baseline=12.0),
        create_memory_utilization_check(vmhwm_threshold=_STRICT_MEMORY_LIMIT_BYTES),
    ]


def _cold_zero_stage(
    device_name: str,
    state_key: str,
) -> t.Any:
    return create_steps_stage(
        steps=[
            create_daemon_control_step(
                device_name,
                action="disable",
                description="2.7.5 disable Bgp and verify the process is stopped",
            ),
            create_daemon_control_step(device_name, action="enable"),
            create_record_jq_timestamp_step(
                _RESTART_TIME_VAR,
                description="2.7.5 record completion of intentional Bgp cold start",
            ),
            _state_step(device_name, "verify_zero", state_key),
        ]
    )


def _formation_stage(
    device_name: str,
    state_key: str,
    device_group_regex: str,
    capture_interfaces: t.Sequence[str],
    dut_source_addresses: t.Sequence[str],
) -> t.Any:
    return create_concurrent_steps_stage(
        [
            [_state_step(device_name, "formation_monitor", state_key)],
            [
                _state_step(
                    device_name,
                    "wait_formation_monitor_armed",
                    state_key,
                ),
                _wire_step(
                    device_name,
                    state_key,
                    "start",
                    capture_interfaces=capture_interfaces,
                    dut_source_addresses=dut_source_addresses,
                ),
                create_record_jq_timestamp_step(
                    _FORMATION_TIME_VAR,
                    description=(
                        "2.7.5 record T0 immediately before simultaneous IXIA "
                        "session enable"
                    ),
                ),
                create_ixia_device_group_toggle_step(
                    enable=True,
                    device_group_name_regex=device_group_regex,
                    expected_match_count=_EXPECTED_DEVICE_GROUPS,
                    description="2.7.5 enable and read back all 18 IXIA device groups",
                ),
                create_bgp_lifecycle_convergence_step(
                    device_name=device_name,
                    expected_established_sessions=_EXPECTED_SESSIONS,
                    parent_prefixes_to_ignore=[],
                    convergence_soft_threshold_seconds=600.0,
                    convergence_hard_timeout_seconds=600.0,
                    convergence_poll_interval_seconds=5.0,
                    convergence_trigger_time_jq_var=_FORMATION_TIME_VAR,
                ),
            ],
        ],
        description="2.7.5 observe dynamic UG formation while all peers enable",
    )


def _runtime_route_stage(
    device_name: str,
    state_key: str,
    pools: t.Mapping[str, str],
    receivers: t.Mapping[str, t.Sequence[str]],
    runtime_update_interfaces: t.Sequence[str],
) -> t.Any:
    return create_steps_stage(
        steps=[
            *_route_toggle_steps(device_name, pools, advertise=True, phase="runtime"),
            create_longevity_step(
                duration=30,
                description="2.7.5 bound runtime route convergence to 30 seconds",
            ),
            *_route_verify_steps(device_name, state_key, receivers, _ROUTE_DELTA),
            *_route_toggle_steps(device_name, pools, advertise=False, phase="restore"),
            create_longevity_step(duration=30, description="2.7.5 settle withdrawals"),
            *_route_verify_steps(device_name, state_key, receivers, 0),
            _wire_step(
                device_name,
                state_key,
                "rebaseline",
                runtime_update_interfaces=runtime_update_interfaces,
            ),
        ]
    )


def _baseline_stage(
    device_name: str,
    state_key: str,
    device_group_regex: str,
    pools: t.Mapping[str, str],
    receivers: t.Mapping[str, t.Sequence[str]],
    all_peer_addresses: t.Sequence[str],
) -> t.Any:
    return create_steps_stage(
        steps=[
            *_route_prepare_steps(device_name, pools, "baseline"),
            create_longevity_step(duration=30, description="2.7.5 settle baseline"),
            _capacity_step(device_name, "capture", state_key),
            _state_step(device_name, "capture", state_key),
            *_route_snapshot_steps(device_name, state_key, receivers),
            _all_peer_snapshot_step(
                device_name,
                f"{state_key}:all-1272-peers",
                all_peer_addresses,
                "2.7.5 snapshot route counts on all exact 1272 peers",
            ),
            create_ixia_device_group_toggle_step(
                enable=False,
                device_group_name_regex=device_group_regex,
                expected_match_count=_EXPECTED_DEVICE_GROUPS,
                description="2.7.5 disable and read back all 18 IXIA device groups",
            ),
        ]
    )


def _validation_stage(
    device_name: str,
    state_key: str,
    all_peer_addresses: t.Sequence[str],
) -> t.Any:
    return create_steps_stage(
        steps=[
            _state_step(device_name, "compare", state_key),
            _all_peer_parity_step(
                device_name,
                f"{state_key}:all-1272-peers",
                all_peer_addresses,
                "2.7.5 converge from formation T0, then require pre/post "
                "cold-start route-count parity on all peers",
                converge_from_formation_t0=True,
            ),
            _capacity_step(device_name, "compare", state_key),
            _wire_step(device_name, state_key, "checkpoint"),
            _all_peer_snapshot_step(
                device_name,
                f"{state_key}:stable-all-1272-peers",
                all_peer_addresses,
                "2.7.5 snapshot all-peer route counts after cold-start formation",
            ),
            create_longevity_step(
                duration=30,
                description="2.7.5 hold formed semantic state stable for 30 seconds",
            ),
            _state_step(device_name, "compare", state_key),
            _all_peer_parity_step(
                device_name,
                f"{state_key}:stable-all-1272-peers",
                all_peer_addresses,
                "2.7.5 require unchanged all-peer route counts after 30 seconds",
            ),
        ]
    )


def _soak_stage(device_name: str, state_key: str) -> t.Any:
    memory_monitor = create_custom_step(
        params_dict={
            "custom_step_name": "bgp_vmhwm_growth_monitor",
            "hostname": device_name,
            "duration_seconds": _SOAK_SECONDS,
            "growth_threshold_bytes": _STRICT_MEMORY_GROWTH_BYTES,
        },
        description=(
            "2.7.5 prove VmHWM remains monotonic and grows less than 200 MB "
            "during the 30-minute soak"
        ),
    )
    return create_concurrent_steps_stage(
        [
            [memory_monitor],
            [
                _state_step(device_name, "monitor", state_key),
                _state_step(device_name, "compare", state_key),
            ],
        ],
        description=(
            "2.7.5 continuously verify semantic groups and bound memory growth "
            "through the 30-minute soak"
        ),
    )


def _wire_verification_stage(device_name: str, state_key: str) -> t.Any:
    return create_steps_stage(steps=[_wire_step(device_name, state_key, "verify")])


def _postchecks(
    checks: t.Sequence[PointInTimeHealthCheck],
    peer_groups: t.Sequence[str],
    member_counts: t.Mapping[str, int],
    afis: t.Mapping[str, str],
) -> list[PointInTimeHealthCheck]:
    """Preserve non-restart checks and replace every inherited restart check.

    Generic restart windows cannot distinguish the intentional Bgp cold start,
    so this case installs one expected-restart guard and one post-restart guard.
    """
    case_aware_checks = [
        check for check in checks if not _is_service_restart_check(check)
    ]
    bounded = _bounded_checks(
        case_aware_checks,
        peer_groups,
        member_counts,
        afis,
        fec_threshold=19_999,
        enforce_absolute_high_watermarks=True,
    )
    post_cold_start_crash_guard = create_service_restart_check(
        services=["Bgp"],
        daemons=["FibBgpGrpc"],
        expected_restarted_services=["Bgp"],
        restart_start_time_jq_var=_RESTART_TIME_VAR,
    )
    no_unexpected_post_restart = create_service_restart_check(
        services=["Bgp"],
        daemons=["FibBgpGrpc"],
        start_time_jq_var=_RESTART_TIME_VAR,
    )
    bounded.extend([post_cold_start_crash_guard, no_unexpected_post_restart])
    return bounded


def _is_service_restart_check(check: PointInTimeHealthCheck) -> bool:
    return check.name == hc_types.CheckName.SERVICE_RESTART_CHECK


def _cleanup_steps(
    device_name: str,
    state_key: str,
    device_group_regex: str,
    pools: t.Mapping[str, str],
) -> list[Step]:
    return [
        _wire_step(device_name, state_key, "cleanup"),
        _state_step(device_name, "clear", state_key),
        _capacity_step(device_name, "clear", state_key),
        create_daemon_control_step(
            device_name,
            action="enable",
            description="2.7.5 cleanup: idempotently enable Bgp",
        ),
        create_ixia_device_group_toggle_step(
            enable=True,
            device_group_name_regex=device_group_regex,
            expected_match_count=_EXPECTED_DEVICE_GROUPS,
            description="2.7.5 cleanup: restore all 18 IXIA device groups",
        ),
        *_route_prepare_steps(device_name, pools, "cleanup"),
        create_bgp_lifecycle_convergence_step(
            device_name=device_name,
            expected_established_sessions=_EXPECTED_SESSIONS,
            parent_prefixes_to_ignore=[],
            convergence_soft_threshold_seconds=600.0,
            convergence_hard_timeout_seconds=600.0,
            convergence_poll_interval_seconds=5.0,
            description="2.7.5 cleanup: verify all 1272 BGP sessions recover",
        ),
    ]


def _periodic_tasks(device_name: str) -> list[t.Any]:
    return create_standard_periodic_tasks(
        device_name=device_name,
        cpu_load_threshold=12.0,
        memory_threshold=_STRICT_MEMORY_LIMIT_BYTES,
        interval=30,
        cpu_load_terminate_on_error=True,
        cpu_util_terminate_on_error=True,
        memory_terminate_on_error=True,
        enable_queue_backpressure_monitor=False,
    )


def create_bgp_ug_cold_start_playbook(
    *,
    device_name: str,
    state_key: str,
    device_group_regex: str,
    capture_interfaces: t.Sequence[str],
    dut_source_addresses: t.Sequence[str],
    runtime_update_interfaces: t.Sequence[str],
    route_pool_regex_by_afi: t.Mapping[str, str],
    ibgp_receiver_host_prefixes_by_afi: t.Mapping[str, t.Sequence[str]],
    all_peer_addresses: t.Sequence[str],
    peer_group_substrings: t.Sequence[str],
    expected_member_counts: t.Mapping[str, int],
    expected_afi_by_substring: t.Mapping[str, str],
    prechecks: t.Sequence[PointInTimeHealthCheck],
    postchecks: t.Sequence[PointInTimeHealthCheck],
    snapshot_checks: t.Sequence[SnapshotHealthCheck],
) -> Playbook:
    """Build 2.7.5 with a verified zero state and concurrent formation trace."""
    if not device_group_regex:
        raise ValueError("device_group_regex must be non-empty")
    receiver_addrs = _validate_route_inputs(
        route_pool_regex_by_afi,
        ibgp_receiver_host_prefixes_by_afi,
        all_peer_addresses,
    )
    wire_interfaces, wire_sources, wire_runtime_interfaces = _validate_wire_inputs(
        capture_interfaces,
        dut_source_addresses,
        runtime_update_interfaces,
    )
    return Playbook(
        name="bgp_ug_cold_start",
        setup_steps=[
            create_bgp_agent_log_artifact_step(
                device_name, "capture", state_key, case_id="2.7.5"
            )
        ],
        stages=[
            _baseline_stage(
                device_name,
                state_key,
                device_group_regex,
                route_pool_regex_by_afi,
                receiver_addrs,
                all_peer_addresses,
            ),
            _cold_zero_stage(device_name, state_key),
            _formation_stage(
                device_name,
                state_key,
                device_group_regex,
                wire_interfaces,
                wire_sources,
            ),
            _validation_stage(device_name, state_key, all_peer_addresses),
            _runtime_route_stage(
                device_name,
                state_key,
                route_pool_regex_by_afi,
                receiver_addrs,
                wire_runtime_interfaces,
            ),
            _soak_stage(device_name, state_key),
            _wire_verification_stage(device_name, state_key),
        ],
        cleanup_steps=[
            create_bgp_agent_log_artifact_step(
                device_name, "publish", state_key, case_id="2.7.5"
            ),
            *_cleanup_steps(
                device_name,
                state_key,
                device_group_regex,
                route_pool_regex_by_afi,
            ),
        ],
        prechecks=_bounded_checks(
            prechecks,
            peer_group_substrings,
            expected_member_counts,
            expected_afi_by_substring,
            fec_threshold=9_999,
        ),
        postchecks=_postchecks(
            postchecks,
            peer_group_substrings,
            expected_member_counts,
            expected_afi_by_substring,
        ),
        snapshot_checks=list(snapshot_checks),
        periodic_tasks=_periodic_tasks(device_name),
    )
