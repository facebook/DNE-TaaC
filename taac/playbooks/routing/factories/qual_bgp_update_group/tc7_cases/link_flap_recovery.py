# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Spec 2.7.1: verified physical-link flap and Update Group recovery."""

import ipaddress
import typing as t

from taac.health_checks.healthcheck_definitions import (
    create_bgp_update_group_check,
    create_memory_utilization_check,
    create_service_restart_check,
    create_system_cpu_load_average_check,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_bgp_agent_log_artifact_step,
    create_bgp_update_group_disruption_step,
    create_bgp_update_group_state_step,
    create_custom_step,
    create_longevity_step,
    create_prepare_compact_bgp_prefix_pool_step,
    create_snapshot_bgp_sent_route_counts_step,
    create_verify_bgp_sent_route_count_delta_step,
)
from taac.task_definitions import create_standard_periodic_tasks
from taac.test_as_a_config.types import (
    Playbook,
    PointInTimeHealthCheck,
    SnapshotHealthCheck,
    Step,
)


_MEMORY_UPPER_BOUND_BYTES = 9_999_999_999
_STRICT_GROWTH_LIMIT_BYTES = 199_999_999
_RUNTIME_POOL_CAPACITY = 100
_ACTIVE_ROUTE_COUNT = 50
_EXPECTED_RECOVERED_RECEIVER_COUNT = 140
_EXPECTED_TARGET_PEER_COUNT = 280
_BGP_HOLD_TIMER_SECONDS = 180


def _exact_update_group_check(
    peer_group_substrings: t.Sequence[str],
    expected_member_counts: t.Mapping[str, int],
    expected_afi_by_substring: t.Mapping[str, str],
    expected_group_count: int,
) -> PointInTimeHealthCheck:
    return create_bgp_update_group_check(
        peer_group_substrings=list(peer_group_substrings),
        expected_member_counts=dict(expected_member_counts),
        expected_group_count=expected_group_count,
        expected_afi_by_substring=dict(expected_afi_by_substring),
        expected_out_delay_seconds_by_substring=dict.fromkeys(peer_group_substrings, 0),
        expected_group_states=["IDLE"],
        expect_enabled=True,
    )


def _bounded_checks(
    checks: t.Sequence[PointInTimeHealthCheck],
    *,
    peer_group_substrings: t.Sequence[str],
    expected_member_counts: t.Mapping[str, int],
    expected_afi_by_substring: t.Mapping[str, str],
    expected_group_count: int,
) -> list[PointInTimeHealthCheck]:
    return [
        *checks,
        _exact_update_group_check(
            peer_group_substrings,
            expected_member_counts,
            expected_afi_by_substring,
            expected_group_count,
        ),
        create_system_cpu_load_average_check(baseline=12.0),
        create_memory_utilization_check(vmhwm_threshold=_MEMORY_UPPER_BOUND_BYTES),
    ]


def _state_step(
    device_name: str,
    action: str,
    state_key: str,
    expected_group_count: int,
    expected_session_count: int,
) -> Step:
    action_params = None
    if action != "clear":
        action_params = {
            "expected_group_count": expected_group_count,
            "expected_session_count": expected_session_count,
            "expected_group_states": ["IDLE"],
        }
    return create_bgp_update_group_state_step(
        device_name=device_name,
        action=action,
        state_key=state_key,
        action_params=action_params,
        description=f"2.7.1 {action} semantic Update Group state",
    )


def _disruption_step(
    device_name: str,
    interface: str,
    target_peer_subnets: t.Sequence[str],
    route_pool_regexes: t.Sequence[str],
    recovered_ebgp_peer_addrs: t.Sequence[str],
    expected_group_count: int,
    flap_count: int,
    down_seconds: int,
    up_seconds: int,
) -> Step:
    return create_bgp_update_group_disruption_step(
        device_name=device_name,
        action="link_flap_recovery",
        action_params={
            "interface": interface,
            "target_peer_subnets": list(target_peer_subnets),
            "expected_target_peer_count": _EXPECTED_TARGET_PEER_COUNT,
            "first_down_prefix_pool_regexes": list(route_pool_regexes),
            "bgp_hold_timer_seconds": _BGP_HOLD_TIMER_SECONDS,
            "recovered_receiver_parent_prefixes": [
                f"{address}/{ipaddress.ip_address(address).max_prefixlen}"
                for address in recovered_ebgp_peer_addrs
            ],
            "expected_recovered_receiver_count": (_EXPECTED_RECOVERED_RECEIVER_COUNT),
            "expected_route_delta": _ACTIVE_ROUTE_COUNT,
            "verify_down_route_delta": False,
            "prefix_start_index": 0,
            "prefix_end_index": _ACTIVE_ROUTE_COUNT,
            "expected_prefix_pool_count": 1,
            "flap_count": flap_count,
            "down_seconds": down_seconds,
            "up_seconds": up_seconds,
            "transition_timeout_seconds": 60,
            "restore_timeout_seconds": 600,
            "route_verification_timeout_seconds": 600,
            "expected_recovered_group_states": ["IDLE"],
            "expected_recovered_group_count": expected_group_count,
            "recovered_group_state_timeout_seconds": 600,
        },
        description=(
            "2.7.1 flap the verified eBGP physical link; advertise the dedicated "
            "iBGP-v6 runtime pool, require structural continuity at all 992 "
            "unaffected iBGP peers, then require exact +50 shadow-RIB resync to all 140 "
            "recovered eBGP-v6 peers after every up transition"
        ),
    )


def _vmhwm_monitor_step(device_name: str, action: str, state_key: str) -> Step:
    return create_custom_step(
        params_dict={
            "custom_step_name": "bgp_vmhwm_growth_monitor",
            "hostname": device_name,
            "action": action,
            "state_key": state_key,
            "growth_threshold_bytes": _STRICT_GROWTH_LIMIT_BYTES,
        },
        description=(
            f"2.7.1 {action} bgpcpp VmHWM for the complete ten-cycle workload"
        ),
    )


def _cleanup_steps(
    device_name: str,
    route_pool_regexes: t.Sequence[str],
    state_key: str,
) -> list[Step]:
    withdrawals = [
        create_prepare_compact_bgp_prefix_pool_step(
            device_name=device_name,
            prefix_pool_regex=pool_regex,
            target_number_of_addresses=_RUNTIME_POOL_CAPACITY,
            allowed_current_number_of_addresses=(
                _ACTIVE_ROUTE_COUNT,
                _RUNTIME_POOL_CAPACITY,
            ),
            safe_number_of_addresses=_RUNTIME_POOL_CAPACITY,
            description=(
                f"2.7.1 cleanup: withdraw and restore capacity for {pool_regex}"
            ),
        )
        for pool_regex in route_pool_regexes
    ]
    return [
        *withdrawals,
        _vmhwm_monitor_step(device_name, "clear", f"{state_key}:vmhwm"),
        create_bgp_update_group_state_step(
            device_name=device_name,
            action="clear",
            state_key=state_key,
            description="2.7.1 cleanup: clear semantic Update Group baseline",
        ),
    ]


def _validate_target_peer_scope(
    target_peer_subnets: t.Sequence[str],
) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    target_peers: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for raw_subnet in target_peer_subnets:
        try:
            network = ipaddress.ip_network(raw_subnet, strict=False)
        except ValueError as error:
            raise ValueError(
                f"2.7.1 target_peer_subnets contains invalid subnet {raw_subnet!r}"
            ) from error
        if network.prefixlen != network.max_prefixlen:
            raise ValueError(
                "2.7.1 target_peer_subnets must contain exact /32 or /128 "
                f"peer hosts; found {raw_subnet!r}"
            )
        target_peers.append(network.network_address)
    unique_target_peers = set(target_peers)
    if (
        len(target_peers) != _EXPECTED_TARGET_PEER_COUNT
        or len(unique_target_peers) != _EXPECTED_TARGET_PEER_COUNT
    ):
        raise ValueError(
            "2.7.1 target_peer_subnets must resolve to exactly 280 unique peers"
        )
    target_peer_afis = {4: 0, 6: 0}
    for peer in unique_target_peers:
        target_peer_afis[peer.version] += 1
    if target_peer_afis != {4: 140, 6: 140}:
        raise ValueError(
            "2.7.1 target_peer_subnets must contain exactly 140 IPv4 and 140 "
            f"IPv6 peer hosts; got {target_peer_afis}"
        )
    return unique_target_peers


def _validate_recovered_peer_scope(
    target_peers: t.Collection[ipaddress.IPv4Address | ipaddress.IPv6Address],
    recovered_ebgp_peer_addrs: t.Sequence[str],
) -> None:
    parsed_recovered_peers: list[
        tuple[str, ipaddress.IPv4Address | ipaddress.IPv6Address]
    ] = []
    for raw_address in recovered_ebgp_peer_addrs:
        try:
            parsed_address = ipaddress.ip_address(raw_address)
        except ValueError as error:
            raise ValueError(
                "2.7.1 recovered_ebgp_peer_addrs contains invalid exact "
                f"address {raw_address!r}"
            ) from error
        parsed_recovered_peers.append((raw_address, parsed_address))
    unique_recovered = {parsed_address for _, parsed_address in parsed_recovered_peers}
    if len(parsed_recovered_peers) != len(unique_recovered):
        raise ValueError("2.7.1 recovered_ebgp_peer_addrs contains duplicate addresses")
    if len(unique_recovered) != _EXPECTED_RECOVERED_RECEIVER_COUNT:
        raise ValueError(
            "2.7.1 recovered_ebgp_peer_addrs must contain exactly 140 unique peers"
        )
    non_ipv6_peers = [
        raw_address
        for raw_address, parsed_address in parsed_recovered_peers
        if parsed_address.version != 6
    ]
    if non_ipv6_peers:
        raise ValueError(
            "2.7.1 recovered_ebgp_peer_addrs must contain only IPv6 peers; "
            f"non-IPv6 peers: {non_ipv6_peers[:3]}"
        )
    outside_scope = [
        raw_address
        for raw_address, parsed_address in parsed_recovered_peers
        if parsed_address not in target_peers
    ]
    if outside_scope:
        raise ValueError(
            "2.7.1 recovered eBGP peers must belong to target_peer_subnets; "
            f"outside scope: {outside_scope[:3]}"
        )


def _validate_inputs(
    target_peer_subnets: t.Sequence[str],
    route_pool_regexes: t.Sequence[str],
    recovered_ebgp_peer_addrs: t.Sequence[str],
    down_seconds: int,
) -> None:
    required = {
        "target_peer_subnets": target_peer_subnets,
        "route_pool_regexes": route_pool_regexes,
        "recovered_ebgp_peer_addrs": recovered_ebgp_peer_addrs,
    }
    empty = sorted(name for name, values in required.items() if not values)
    if empty:
        raise ValueError(f"2.7.1 requires non-empty {empty}")
    if len(route_pool_regexes) != 1:
        raise ValueError("2.7.1 requires exactly one shared iBGP-v6 runtime pool")
    if down_seconds >= _BGP_HOLD_TIMER_SECONDS:
        raise ValueError(
            "2.7.1 down_seconds must be less than bgp_hold_timer_seconds "
            f"({_BGP_HOLD_TIMER_SECONDS})"
        )
    target_peers = _validate_target_peer_scope(target_peer_subnets)
    _validate_recovered_peer_scope(target_peers, recovered_ebgp_peer_addrs)


def _withdraw_runtime_steps(
    device_name: str,
    route_pool_regexes: t.Sequence[str],
    phase: str,
) -> list[Step]:
    return [
        create_prepare_compact_bgp_prefix_pool_step(
            device_name=device_name,
            prefix_pool_regex=pool_regex,
            target_number_of_addresses=_ACTIVE_ROUTE_COUNT,
            allowed_current_number_of_addresses=(
                _ACTIVE_ROUTE_COUNT,
                _RUNTIME_POOL_CAPACITY,
            ),
            safe_number_of_addresses=_RUNTIME_POOL_CAPACITY,
            description=(
                f"2.7.1 {phase}: withdraw and prepare 50-route pool {pool_regex}"
            ),
        )
        for pool_regex in route_pool_regexes
    ]


def _route_delta_step(
    device_name: str,
    snapshot_key: str,
    recovered_ebgp_peer_addrs: t.Sequence[str],
    delta: int,
    phase: str,
) -> Step:
    return create_verify_bgp_sent_route_count_delta_step(
        hostname=device_name,
        snapshot_key=snapshot_key,
        peer_addrs=list(recovered_ebgp_peer_addrs),
        min_delta=delta,
        max_delta=delta,
        tolerance=0,
        description=(
            f"2.7.1 {phase}: every one of 140 recovered eBGP peers has "
            f"an exact signed route delta of {delta}"
        ),
    )


def _build_stages(
    device_name: str,
    capture: Step,
    disruption: Step,
    compare: Step,
    state_key: str,
    route_pool_regexes: t.Sequence[str],
    recovered_ebgp_peer_addrs: t.Sequence[str],
    route_count_snapshot_key: str,
    settle_seconds: int,
) -> list[t.Any]:
    baseline_steps = [
        *_withdraw_runtime_steps(device_name, route_pool_regexes, "baseline"),
        create_longevity_step(
            duration=settle_seconds,
            description="2.7.1 baseline: settle after withdrawing runtime pools",
        ),
        capture,
        create_snapshot_bgp_sent_route_counts_step(
            hostname=device_name,
            snapshot_key=route_count_snapshot_key,
            peer_addrs=list(recovered_ebgp_peer_addrs),
            description="2.7.1 baseline: snapshot all 140 target eBGP peers",
        ),
        _vmhwm_monitor_step(device_name, "capture", f"{state_key}:vmhwm"),
    ]
    recovery_steps = [
        _route_delta_step(
            device_name,
            route_count_snapshot_key,
            recovered_ebgp_peer_addrs,
            _ACTIVE_ROUTE_COUNT,
            "recovery",
        ),
        compare,
        _vmhwm_monitor_step(device_name, "compare", f"{state_key}:vmhwm"),
        *_withdraw_runtime_steps(device_name, route_pool_regexes, "restore"),
        create_longevity_step(
            duration=settle_seconds,
            description="2.7.1 restore: settle after withdrawing runtime routes",
        ),
        _route_delta_step(
            device_name,
            route_count_snapshot_key,
            recovered_ebgp_peer_addrs,
            0,
            "post-withdraw",
        ),
    ]
    return [
        create_steps_stage(steps=baseline_steps),
        create_steps_stage(steps=[disruption]),
        create_steps_stage(steps=recovery_steps),
    ]


def create_bgp_ug_link_flap_recovery_playbook(
    *,
    device_name: str,
    interface: str,
    target_peer_subnets: t.Sequence[str],
    route_pool_regexes: t.Sequence[str],
    recovered_ebgp_peer_addrs: t.Sequence[str],
    state_key: str,
    peer_group_substrings: t.Sequence[str],
    expected_member_counts: t.Mapping[str, int],
    expected_afi_by_substring: t.Mapping[str, str],
    prechecks: t.Sequence[PointInTimeHealthCheck],
    postchecks: t.Sequence[PointInTimeHealthCheck],
    snapshot_checks: t.Sequence[SnapshotHealthCheck],
    expected_group_count: int = 4,
    expected_session_count: int = 1272,
    flap_count: int = 10,
    down_seconds: int = 30,
    up_seconds: int = 30,
    settle_seconds: int = 30,
    route_count_snapshot_key: str | None = None,
) -> Playbook:
    """Build spec 2.7.1 with trigger verification and semantic recovery gates."""
    _validate_inputs(
        target_peer_subnets,
        route_pool_regexes,
        recovered_ebgp_peer_addrs,
        down_seconds,
    )
    capture = _state_step(
        device_name,
        "capture",
        state_key,
        expected_group_count,
        expected_session_count,
    )
    compare = _state_step(
        device_name,
        "compare",
        state_key,
        expected_group_count,
        expected_session_count,
    )
    disruption = _disruption_step(
        device_name,
        interface,
        target_peer_subnets,
        route_pool_regexes,
        recovered_ebgp_peer_addrs,
        expected_group_count,
        flap_count,
        down_seconds,
        up_seconds,
    )
    bounded_prechecks = _bounded_checks(
        prechecks,
        peer_group_substrings=peer_group_substrings,
        expected_member_counts=expected_member_counts,
        expected_afi_by_substring=expected_afi_by_substring,
        expected_group_count=expected_group_count,
    )
    bounded_postchecks = _bounded_checks(
        postchecks,
        peer_group_substrings=peer_group_substrings,
        expected_member_counts=expected_member_counts,
        expected_afi_by_substring=expected_afi_by_substring,
        expected_group_count=expected_group_count,
    )
    bounded_postchecks.append(
        create_service_restart_check(services=["Bgp"], daemons=["FibBgpGrpc"])
    )
    return Playbook(
        name="bgp_ug_link_flap_recovery",
        setup_steps=[
            create_bgp_agent_log_artifact_step(
                device_name, "capture", state_key, case_id="2.7.1"
            )
        ],
        stages=_build_stages(
            device_name,
            capture,
            disruption,
            compare,
            state_key,
            route_pool_regexes,
            recovered_ebgp_peer_addrs,
            route_count_snapshot_key or f"{state_key}:ebgp-route-counts",
            settle_seconds,
        ),
        cleanup_steps=[
            create_bgp_agent_log_artifact_step(
                device_name, "publish", state_key, case_id="2.7.1"
            ),
            *_cleanup_steps(device_name, route_pool_regexes, state_key),
        ],
        prechecks=bounded_prechecks,
        postchecks=bounded_postchecks,
        snapshot_checks=list(snapshot_checks),
        periodic_tasks=create_standard_periodic_tasks(
            device_name=device_name,
            cpu_load_threshold=12.0,
            memory_threshold=_MEMORY_UPPER_BOUND_BYTES,
            interval=30,
            cpu_load_terminate_on_error=True,
            memory_terminate_on_error=True,
            enable_queue_backpressure_monitor=False,
        ),
    )
