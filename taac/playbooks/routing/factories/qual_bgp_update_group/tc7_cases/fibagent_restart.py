# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Spec 2.7.6: Update Group stability through verified FibAgent restart."""

import ipaddress
import json
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
    create_bgp_update_group_state_step,
    create_custom_step,
    create_hardware_capacity_delta_step,
    create_longevity_step,
    create_prepare_compact_bgp_prefix_pool_step,
    create_service_interruption_step,
    create_snapshot_bgp_sent_route_counts_step,
    create_verified_fibagent_restart_step,
    create_verify_bgp_sent_route_count_delta_step,
    create_verify_fibagent_active_step,
)
from taac.task_definitions import create_standard_periodic_tasks
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config.types import (
    Playbook,
    PointInTimeHealthCheck,
    Service,
    ServiceInterruptionTrigger,
    SnapshotHealthCheck,
    Step,
)


_EXPECTED_SESSIONS = 1272
_EXPECTED_GROUPS = 4
_EXPECTED_RECEIVERS_PER_AFI = 496
_ROUTE_DELTA = 100
_STRICT_MEMORY_LIMIT_BYTES = 9_999_999_999
_STRICT_MEMORY_GROWTH_BYTES = 199_999_999
_SOAK_SECONDS = 1800
_RESTART_TIMEOUT_SECONDS = 300.0
_CONTINUITY_MONITOR_SECONDS = 305.0
_MONITOR_ARM_TIMEOUT_SECONDS = 60.0
_NON_GATING_CAPACITY_LIMIT = 2**63 - 1


def _validate_route_inputs(
    pools: t.Mapping[str, str], receivers: t.Mapping[str, t.Sequence[str]]
) -> dict[str, tuple[str, ...]]:
    expected_afis = {"ipv4", "ipv6"}
    if set(pools) != expected_afis or set(receivers) != expected_afis:
        raise ValueError("route pools and receiver scopes must contain ipv4 and ipv6")
    if any(not value for value in pools.values()) or len(set(pools.values())) != 2:
        raise ValueError("2.7.6 requires two distinct non-empty 100-route pools")
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
                f"2.7.6 {afi} receivers contain invalid host prefix {receiver_scope!r}"
            ) from error
    if any(
        network.version != expected_version
        or network.prefixlen != network.max_prefixlen
        for network in networks
    ):
        raise ValueError(
            f"2.7.6 {afi} receivers must be individual host addresses or host prefixes"
        )
    addresses = tuple(str(network.network_address) for network in networks)
    if len(addresses) != _EXPECTED_RECEIVERS_PER_AFI or len(set(addresses)) != len(
        addresses
    ):
        raise ValueError(
            f"2.7.6 requires exactly {_EXPECTED_RECEIVERS_PER_AFI} unique {afi} "
            "iBGP receivers"
        )
    return addresses


def _state_step(device_name: str, action: str, state_key: str) -> Step:
    action_params: dict[str, t.Any] | None = None
    if action in {"capture", "compare"}:
        action_params = {
            "expected_group_count": _EXPECTED_GROUPS,
            "expected_session_count": _EXPECTED_SESSIONS,
            "expected_group_states": ["IDLE"],
            "operational_continuity": "group_id",
            "require_uniform_sent_route_counts": True,
            "require_equal_sent_route_counts": action == "compare",
        }
    elif action == "monitor":
        action_params = {
            "case": "fibagent_restart",
            "duration_seconds": _CONTINUITY_MONITOR_SECONDS,
            "poll_interval_seconds": 1.0,
            "expected_group_count": _EXPECTED_GROUPS,
            "expected_session_count": _EXPECTED_SESSIONS,
            "expected_group_states": ["IDLE"],
            "operational_continuity": "group_id",
            "require_uniform_sent_route_counts": True,
            "require_equal_sent_route_counts": True,
        }
    elif action == "wait_monitor_armed":
        action_params = {"timeout_seconds": _MONITOR_ARM_TIMEOUT_SECONDS}
    return create_bgp_update_group_state_step(
        device_name,
        action,
        state_key,
        action_params=action_params,
        description=f"2.7.6 {action} operational Update Group state",
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
            prefix_end_index=_ROUTE_DELTA,
            expected_prefix_pool_count=1,
            expected_number_of_addresses=_ROUTE_DELTA,
            runtime_route_operation=True,
            description=f"2.7.6 {phase}: {'advertise' if advertise else 'withdraw'} {afi} pool",
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
            description=f"2.7.6 {phase}: verify inactive 100-route {afi} pool",
        )
        for afi in ("ipv4", "ipv6")
    ]


def _route_snapshot_steps(
    device_name: str,
    state_key: str,
    receiver_addrs: t.Mapping[str, t.Sequence[str]],
) -> list[Step]:
    return [
        create_snapshot_bgp_sent_route_counts_step(
            hostname=device_name,
            snapshot_key=f"{state_key}:{afi}",
            peer_addrs=list(receiver_addrs[afi]),
            description=f"2.7.6 snapshot all 496 {afi} iBGP receivers",
        )
        for afi in ("ipv4", "ipv6")
    ]


def _route_verify_steps(
    device_name: str,
    state_key: str,
    receiver_addrs: t.Mapping[str, t.Sequence[str]],
    delta: int,
) -> list[Step]:
    return [
        create_verify_bgp_sent_route_count_delta_step(
            hostname=device_name,
            snapshot_key=f"{state_key}:{afi}",
            peer_addrs=list(receiver_addrs[afi]),
            min_delta=delta,
            max_delta=delta,
            tolerance=0,
            description=f"2.7.6 require exact {delta:+d} at all 496 {afi} iBGP peers",
        )
        for afi in ("ipv4", "ipv6")
    ]


def _bounded_checks(
    checks: t.Sequence[PointInTimeHealthCheck],
    peer_groups: t.Sequence[str],
    member_counts: t.Mapping[str, int],
    afis: t.Mapping[str, str],
    *,
    hardware_capacity_check: PointInTimeHealthCheck,
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
        hardware_capacity_check,
        create_system_cpu_load_average_check(baseline=12.0),
        create_memory_utilization_check(vmhwm_threshold=_STRICT_MEMORY_LIMIT_BYTES),
    ]


def _hardware_capacity_collection_check() -> PointInTimeHealthCheck:
    return create_hardware_capacity_check(
        fec_threshold=_NON_GATING_CAPACITY_LIMIT,
        ecmp_threshold=_NON_GATING_CAPACITY_LIMIT,
        max_ecmp_level1=_NON_GATING_CAPACITY_LIMIT,
        max_ecmp_level2=_NON_GATING_CAPACITY_LIMIT,
        max_ecmp_level3=_NON_GATING_CAPACITY_LIMIT,
        watermark_delta_threshold=_NON_GATING_CAPACITY_LIMIT,
        check_watermarks=False,
        check_id="baseline_hardware_capacity_collection",
    )


def _hardware_capacity_postcheck() -> PointInTimeHealthCheck:
    return create_hardware_capacity_check(
        fec_threshold=19_999,
        ecmp_threshold=999,
        max_ecmp_level1=_NON_GATING_CAPACITY_LIMIT,
        max_ecmp_level2=_NON_GATING_CAPACITY_LIMIT,
        max_ecmp_level3=_NON_GATING_CAPACITY_LIMIT,
        watermark_delta_threshold=_NON_GATING_CAPACITY_LIMIT,
        check_watermarks=False,
        check_id="post_fibagent_hardware_capacity",
    )


def _capacity_step(device_name: str, action: str, state_key: str) -> Step:
    return create_hardware_capacity_delta_step(
        device_name,
        action,
        state_key,
        max_current_delta=100,
        max_high_watermark_increase=100,
        description=f"2.7.6 {action} FEC/ECMP capacity delta baseline",
    )


def _restart_stage(device_name: str, state_key: str) -> t.Any:
    return create_concurrent_steps_stage(
        [
            [
                _state_step(device_name, "wait_monitor_armed", state_key),
                create_verified_fibagent_restart_step(
                    device_name,
                    restart_timeout_seconds=_RESTART_TIMEOUT_SECONDS,
                    poll_interval_seconds=1.0,
                    require_uptime_change=True,
                    description="2.7.6 restart FibAgent and verify status transition",
                ),
            ],
            [_state_step(device_name, "monitor", state_key)],
        ],
        description="2.7.6 prove BGP sessions and group IDs survive FibAgent restart",
    )


def _runtime_route_stage(
    device_name: str,
    state_key: str,
    pools: t.Mapping[str, str],
    receivers: t.Mapping[str, t.Sequence[str]],
) -> t.Any:
    return create_steps_stage(
        steps=[
            *_route_toggle_steps(device_name, pools, advertise=True, phase="runtime"),
            create_longevity_step(
                duration=30,
                description="2.7.6 bound runtime route convergence to 30 seconds",
            ),
            *_route_verify_steps(device_name, state_key, receivers, _ROUTE_DELTA),
            *_route_toggle_steps(device_name, pools, advertise=False, phase="restore"),
            create_longevity_step(duration=30, description="2.7.6 settle withdrawals"),
            *_route_verify_steps(device_name, state_key, receivers, 0),
            _capacity_step(device_name, "compare", state_key),
        ]
    )


def _baseline_stage(
    device_name: str,
    state_key: str,
    pools: t.Mapping[str, str],
    receivers: t.Mapping[str, t.Sequence[str]],
) -> t.Any:
    return create_steps_stage(
        steps=[
            *_route_prepare_steps(device_name, pools, "baseline"),
            create_longevity_step(duration=30, description="2.7.6 settle baseline"),
            _capacity_step(device_name, "capture", state_key),
            _state_step(device_name, "capture", state_key),
            *_route_snapshot_steps(device_name, state_key, receivers),
        ]
    )


def _validation_stage(
    device_name: str,
    state_key: str,
    receivers: t.Mapping[str, t.Sequence[str]],
) -> t.Any:
    return create_steps_stage(
        steps=[
            _state_step(device_name, "compare", state_key),
            *_route_verify_steps(device_name, state_key, receivers, 0),
            _capacity_step(device_name, "compare", state_key),
        ]
    )


def _memory_growth_monitor_step(device_name: str) -> Step:
    return create_custom_step(
        params_dict={
            "custom_step_name": "bgp_vmhwm_growth_monitor",
            "hostname": device_name,
            "duration_seconds": _SOAK_SECONDS,
            "growth_threshold_bytes": _STRICT_MEMORY_GROWTH_BYTES,
        },
        description=("2.7.6 prove 30-minute bgpcpp VmHWM growth remains below 200 MB"),
    )


def _soak_stage(device_name: str, state_key: str) -> t.Any:
    return create_concurrent_steps_stage(
        [
            [
                create_longevity_step(
                    duration=_SOAK_SECONDS,
                    description="2.7.6 30-minute stable soak",
                ),
                _state_step(device_name, "compare", state_key),
            ],
            [_memory_growth_monitor_step(device_name)],
        ],
        description="2.7.6 range-bound memory and stable Update Group soak",
    )


def _postchecks(
    checks: t.Sequence[PointInTimeHealthCheck],
    peer_groups: t.Sequence[str],
    member_counts: t.Mapping[str, int],
    afis: t.Mapping[str, str],
) -> list[PointInTimeHealthCheck]:
    conflicting_restart_checks = [
        check for check in checks if _is_fibagent_restart_check(check)
    ]
    if len(conflicting_restart_checks) > 1:
        raise ValueError(
            "2.7.6 accepts at most one inherited FibAgent service restart check"
        )
    case_aware_checks = [
        transformed
        for check in checks
        if (transformed := _without_fibagent(check)) is not None
    ]
    bounded = _bounded_checks(
        case_aware_checks,
        peer_groups,
        member_counts,
        afis,
        hardware_capacity_check=_hardware_capacity_postcheck(),
    )
    if not any(_guards_bgp_and_fibbgpgrpc(check) for check in case_aware_checks):
        bounded.append(
            create_service_restart_check(services=["Bgp"], daemons=["FibBgpGrpc"])
        )
    return bounded


def _is_service_restart_check(check: PointInTimeHealthCheck) -> bool:
    return check.name == hc_types.CheckName.SERVICE_RESTART_CHECK


def _service_restart_payload(
    check: PointInTimeHealthCheck,
) -> t.Mapping[str, t.Any] | None:
    if not _is_service_restart_check(check):
        return None
    check_params = getattr(check, "check_params", None)
    raw_params = getattr(check_params, "json_params", None)
    if not raw_params:
        return {}
    try:
        payload = json.loads(raw_params)
    except (json.JSONDecodeError, TypeError) as error:
        raise ValueError(
            "2.7.6 inherited SERVICE_RESTART_CHECK has malformed json_params"
        ) from error
    if not isinstance(payload, dict):
        raise ValueError(
            "2.7.6 inherited SERVICE_RESTART_CHECK json_params must decode to an object"
        )
    return payload


def _is_fibagent_restart_check(check: PointInTimeHealthCheck) -> bool:
    payload = _service_restart_payload(check)
    if payload is None:
        return False
    services = payload.get("services")
    return isinstance(services, list) and "FibAgent" in services


def _without_fibagent(
    check: PointInTimeHealthCheck,
) -> PointInTimeHealthCheck | None:
    payload = _service_restart_payload(check)
    if payload is None:
        return check
    services = payload.get("services")
    if not isinstance(services, list) or "FibAgent" not in services:
        return check
    check_params = check.check_params
    if check_params is None:
        raise ValueError("FibAgent restart check has no check_params")
    updated_payload = dict(payload)
    remaining_services = [service for service in services if service != "FibAgent"]
    if not remaining_services:
        return None
    updated_payload["services"] = remaining_services
    # fbthrift py3 structs are immutable; calling an instance is the supported
    # functional-update operation and preserves all fields not overridden here.
    return check(check_params=check_params(json_params=json.dumps(updated_payload)))


def _guards_bgp_and_fibbgpgrpc(check: PointInTimeHealthCheck) -> bool:
    payload = _service_restart_payload(check)
    if payload is None:
        return False
    services = payload.get("services")
    daemons = payload.get("daemons")
    return (
        isinstance(services, list)
        and "Bgp" in services
        and isinstance(daemons, list)
        and "FibBgpGrpc" in daemons
    )


def _cleanup_steps(
    device_name: str,
    state_key: str,
    pools: t.Mapping[str, str],
) -> list[Step]:
    return [
        _state_step(device_name, "clear", state_key),
        _capacity_step(device_name, "clear", state_key),
        create_service_interruption_step(
            service=Service.ARISTA_L3_FORWARDING_AGENT,
            trigger=ServiceInterruptionTrigger.SYSTEMCTL_START,
            description=(
                "2.7.6 cleanup: idempotently restore the EOS L3 forwarding agent"
            ),
        ),
        create_verify_fibagent_active_step(
            device_name,
            active_timeout_seconds=_RESTART_TIMEOUT_SECONDS,
            poll_interval_seconds=1.0,
            description="2.7.6 cleanup: verify the EOS L3 forwarding agent is active",
        ),
        create_longevity_step(
            duration=30,
            description="2.7.6 cleanup: allow FibAgent recovery to settle",
        ),
        *_route_prepare_steps(device_name, pools, "cleanup"),
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


def create_bgp_ug_fibagent_restart_playbook(
    *,
    device_name: str,
    state_key: str,
    route_pool_regex_by_afi: t.Mapping[str, str],
    ibgp_receiver_parent_prefixes_by_afi: t.Mapping[str, t.Sequence[str]],
    peer_group_substrings: t.Sequence[str],
    expected_member_counts: t.Mapping[str, int],
    expected_afi_by_substring: t.Mapping[str, str],
    prechecks: t.Sequence[PointInTimeHealthCheck],
    postchecks: t.Sequence[PointInTimeHealthCheck],
    snapshot_checks: t.Sequence[SnapshotHealthCheck],
) -> Playbook:
    """Build 2.7.6 with a verified restart and semantic BGP continuity."""
    receiver_addrs = _validate_route_inputs(
        route_pool_regex_by_afi, ibgp_receiver_parent_prefixes_by_afi
    )
    return Playbook(
        name="bgp_ug_fibagent_restart",
        setup_steps=[
            create_bgp_agent_log_artifact_step(
                device_name, "capture", state_key, case_id="2.7.6"
            )
        ],
        stages=[
            _baseline_stage(
                device_name,
                state_key,
                route_pool_regex_by_afi,
                receiver_addrs,
            ),
            _restart_stage(device_name, state_key),
            _validation_stage(
                device_name,
                state_key,
                receiver_addrs,
            ),
            _runtime_route_stage(
                device_name,
                state_key,
                route_pool_regex_by_afi,
                receiver_addrs,
            ),
            _soak_stage(device_name, state_key),
        ],
        cleanup_steps=[
            create_bgp_agent_log_artifact_step(
                device_name, "publish", state_key, case_id="2.7.6"
            ),
            *_cleanup_steps(
                device_name,
                state_key,
                route_pool_regex_by_afi,
            ),
        ],
        prechecks=_bounded_checks(
            prechecks,
            peer_group_substrings,
            expected_member_counts,
            expected_afi_by_substring,
            hardware_capacity_check=_hardware_capacity_collection_check(),
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
