# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Spec 2.7.2: sustained verified flapping across the two EBB IXIA ports."""

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
    create_bgp_update_group_physical_restore_step,
    create_bgp_update_group_state_step,
    create_longevity_step,
    create_prepare_compact_bgp_prefix_pool_step,
)
from taac.task_definitions import create_standard_periodic_tasks
from taac.test_as_a_config.types import (
    Playbook,
    PointInTimeHealthCheck,
    SnapshotHealthCheck,
    Step,
)


_DURATION_SECONDS = 3600
_TRANSITION_TIMEOUT_SECONDS = 30
_RECOVERY_TIMEOUT_SECONDS = 70
_GLOBAL_RECOVERY_TIMEOUT_SECONDS = 600
_HEARTBEAT_TIMEOUT_SECONDS = 12
_HEARTBEAT_PREPARATION_TIMEOUT_SECONDS = 900
_ROUTE_CLEANUP_TIMEOUT_SECONDS = 900
_EVENT_TIMEOUT_SECONDS = 119
_CHECKPOINT_TRANSITION_TIMEOUT_SECONDS = 60
_CHECKPOINT_TIMEOUT_SECONDS = (
    _EVENT_TIMEOUT_SECONDS + _CHECKPOINT_TRANSITION_TIMEOUT_SECONDS + 5
)
_EXPECTED_GROUP_COUNT = 4
_EXPECTED_SESSION_COUNT = 1272
_STRICT_MEMORY_LIMIT_BYTES = 9_999_999_999
_REQUIRED_ROLES = frozenset({"ebgp", "ibgp"})
_ROUTE_HEARTBEAT_STATES = frozenset({frozenset()})
_STRUCTURAL_HEARTBEAT_STATES = frozenset(
    {
        frozenset({"ebgp"}),
        frozenset({"ibgp"}),
        frozenset({"ebgp", "ibgp"}),
    }
)
_REQUIRED_HEARTBEAT_STATES = _ROUTE_HEARTBEAT_STATES | _STRUCTURAL_HEARTBEAT_STATES


def _validate_port_tracks(
    port_tracks: t.Sequence[t.Mapping[str, t.Any]],
) -> list[dict[str, t.Any]]:
    normalized = [dict(track) for track in port_tracks]
    roles = [str(track.get("role", "")) for track in normalized]
    if len(normalized) != 2 or set(roles) != _REQUIRED_ROLES:
        raise ValueError("2.7.2 port_tracks must contain exactly one ebgp and ibgp")
    for track in normalized:
        if not track.get("interface") or not track.get("target_peer_subnets"):
            raise ValueError(
                "2.7.2 each port track requires interface and target_peer_subnets"
            )
    return normalized


def _validate_heartbeat_scenarios(
    heartbeat_scenarios: t.Sequence[t.Mapping[str, t.Any]],
) -> list[dict[str, t.Any]]:
    normalized = [dict(scenario) for scenario in heartbeat_scenarios]
    states = [frozenset(scenario.get("down_roles", ())) for scenario in normalized]
    if len(normalized) != 4 or frozenset(states) != _REQUIRED_HEARTBEAT_STATES:
        raise ValueError(
            "2.7.2 heartbeat_scenarios must cover full-up plus all three "
            "planned-down states"
        )
    for state, scenario in zip(states, normalized):
        mode = scenario.get("verification_mode")
        if state in _ROUTE_HEARTBEAT_STATES:
            if mode != "route":
                raise ValueError(
                    f"2.7.2 state {sorted(state)} requires route verification"
                )
            legs = [dict(leg) for leg in scenario.get("legs", ())]
            if len(legs) != 4:
                raise ValueError("2.7.2 full-up route state requires exactly four legs")
            for leg in legs:
                leg.setdefault("route_verification_timeout_seconds", 60)
                leg.setdefault("state_baseline_timeout_seconds", 30)
                _validate_heartbeat_scope(leg)
            scenario["legs"] = legs
        else:
            if mode != "structural":
                raise ValueError(f"2.7.2 down state {sorted(state)} must be structural")
            if scenario.get("legs") or scenario.get("source_prefix_pool_regexes"):
                raise ValueError(
                    "2.7.2 structural states cannot configure route heartbeat legs"
                )
            reason = scenario.get("structural_reason")
            if not isinstance(reason, str) or not reason:
                raise ValueError(
                    "2.7.2 structural states require an explicit non-empty reason"
                )
    return normalized


def _validate_heartbeat_scope(scenario: t.Mapping[str, t.Any]) -> None:
    if not scenario.get("source_prefix_pool_regexes"):
        raise ValueError("2.7.2 every heartbeat requires source prefix pools")
    if not scenario.get("receiver_parent_prefixes"):
        raise ValueError("2.7.2 every heartbeat requires receiver scope")
    for field in ("expected_receiver_count", "expected_route_delta"):
        value = scenario.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"2.7.2 heartbeat {field} must be a positive integer")
    allowed_unchanged = scenario.get("allowed_unchanged_receiver_count", 0)
    if (
        not isinstance(allowed_unchanged, int)
        or isinstance(allowed_unchanged, bool)
        or allowed_unchanged < 0
    ):
        raise ValueError(
            "2.7.2 heartbeat allowed_unchanged_receiver_count must be a "
            "non-negative integer"
        )
    route_timeout = scenario.get("route_verification_timeout_seconds", 60)
    baseline_timeout = scenario.get("state_baseline_timeout_seconds", 30)
    if (
        not isinstance(route_timeout, (int, float))
        or isinstance(route_timeout, bool)
        or route_timeout <= 0
        or not isinstance(baseline_timeout, (int, float))
        or isinstance(baseline_timeout, bool)
        or baseline_timeout <= 0
    ):
        raise ValueError("2.7.2 route and baseline timeouts must be positive numbers")


def _validate_update_group_contract(
    peer_group_substrings: t.Sequence[str],
    expected_member_counts: t.Mapping[str, int],
    expected_afi_by_substring: t.Mapping[str, str],
) -> None:
    selectors = set(peer_group_substrings)
    if len(peer_group_substrings) != 4 or len(selectors) != 4:
        raise ValueError("2.7.2 requires exactly four unique Update Group selectors")
    if set(expected_member_counts) != selectors:
        raise ValueError("2.7.2 member-count selectors must match peer groups")
    if sorted(expected_member_counts.values()) != [140, 140, 496, 496]:
        raise ValueError("2.7.2 requires exact 140/140/496/496 UG membership")
    if set(expected_afi_by_substring) != selectors:
        raise ValueError("2.7.2 AFI selectors must match peer groups")
    if sorted(expected_afi_by_substring.values()) != [
        "ipv4",
        "ipv4",
        "ipv6",
        "ipv6",
    ]:
        raise ValueError("2.7.2 requires two IPv4 and two IPv6 Update Groups")


def _state_step(device_name: str, action: str, state_key: str) -> Step:
    action_params = None
    if action != "clear":
        action_params = {
            "expected_group_count": _EXPECTED_GROUP_COUNT,
            "expected_session_count": _EXPECTED_SESSION_COUNT,
        }
    return create_bgp_update_group_state_step(
        device_name=device_name,
        action=action,
        state_key=state_key,
        action_params=action_params,
        description=f"2.7.2 {action} exact semantic Update Group state",
    )


def _update_group_check(
    peer_group_substrings: t.Sequence[str],
    expected_member_counts: t.Mapping[str, int],
    expected_afi_by_substring: t.Mapping[str, str],
) -> PointInTimeHealthCheck:
    return create_bgp_update_group_check(
        peer_group_substrings=list(peer_group_substrings),
        expected_member_counts=dict(expected_member_counts),
        expected_group_count=_EXPECTED_GROUP_COUNT,
        expected_group_states=["IDLE"],
        expected_afi_by_substring=dict(expected_afi_by_substring),
        expected_out_delay_seconds_by_substring=dict.fromkeys(peer_group_substrings, 0),
        expect_enabled=True,
    )


def _bounded_checks(
    checks: t.Sequence[PointInTimeHealthCheck],
    peer_group_substrings: t.Sequence[str],
    expected_member_counts: t.Mapping[str, int],
    expected_afi_by_substring: t.Mapping[str, str],
) -> list[PointInTimeHealthCheck]:
    return [
        *checks,
        _update_group_check(
            peer_group_substrings,
            expected_member_counts,
            expected_afi_by_substring,
        ),
        create_system_cpu_load_average_check(baseline=12.0),
        create_memory_utilization_check(vmhwm_threshold=_STRICT_MEMORY_LIMIT_BYTES),
    ]


def _bounded_postchecks(
    checks: t.Sequence[PointInTimeHealthCheck],
    peer_group_substrings: t.Sequence[str],
    expected_member_counts: t.Mapping[str, int],
    expected_afi_by_substring: t.Mapping[str, str],
) -> list[PointInTimeHealthCheck]:
    bounded = _bounded_checks(
        checks,
        peer_group_substrings,
        expected_member_counts,
        expected_afi_by_substring,
    )
    bounded.append(
        create_service_restart_check(services=["Bgp"], daemons=["FibBgpGrpc"])
    )
    return bounded


def _route_pool_regexes(
    heartbeat_scenarios: t.Sequence[t.Mapping[str, t.Any]],
) -> list[str]:
    return sorted(
        {
            str(regex)
            for scenario in heartbeat_scenarios
            for leg in scenario.get("legs", ())
            for regex in leg["source_prefix_pool_regexes"]
        }
    )


def _prepare_route_steps(
    device_name: str,
    route_pool_regexes: t.Sequence[str],
    phase: str,
    target_number_of_addresses: int,
) -> list[Step]:
    return [
        create_prepare_compact_bgp_prefix_pool_step(
            device_name=device_name,
            prefix_pool_regex=pool_regex,
            target_number_of_addresses=target_number_of_addresses,
            allowed_current_number_of_addresses=(1, 100),
            safe_number_of_addresses=100,
            description=(
                f"2.7.2 {phase}: withdraw and set heartbeat capacity "
                f"to {target_number_of_addresses} for {pool_regex}"
            ),
        )
        for pool_regex in route_pool_regexes
    ]


def _disruption_step(
    device_name: str,
    port_tracks: t.Sequence[t.Mapping[str, t.Any]],
    heartbeat_scenarios: t.Sequence[t.Mapping[str, t.Any]],
) -> Step:
    return create_bgp_update_group_disruption_step(
        device_name=device_name,
        action="sustained_link_flap",
        action_params={
            "duration_seconds": _DURATION_SECONDS,
            "port_tracks": list(port_tracks),
            "heartbeat_scenarios": list(heartbeat_scenarios),
            "down_seconds": 15,
            "event_timeout_seconds": _EVENT_TIMEOUT_SECONDS,
            "transition_timeout_seconds": _TRANSITION_TIMEOUT_SECONDS,
            "recovery_timeout_seconds": _RECOVERY_TIMEOUT_SECONDS,
            "global_recovery_timeout_seconds": _GLOBAL_RECOVERY_TIMEOUT_SECONDS,
            "expected_recovered_group_states": ["IDLE"],
            "expected_recovered_group_count": _EXPECTED_GROUP_COUNT,
            "recovered_group_state_timeout_seconds": (_GLOBAL_RECOVERY_TIMEOUT_SECONDS),
            "recovered_group_state_poll_interval_seconds": 1,
            "recovery_stable_sample_count": 2,
            "heartbeat_timeout_seconds": _HEARTBEAT_TIMEOUT_SECONDS,
            "heartbeat_preparation_timeout_seconds": (
                _HEARTBEAT_PREPARATION_TIMEOUT_SECONDS
            ),
            "route_cleanup_timeout_seconds": _ROUTE_CLEANUP_TIMEOUT_SECONDS,
            "cleanup_timeout_seconds": (
                _GLOBAL_RECOVERY_TIMEOUT_SECONDS + _TRANSITION_TIMEOUT_SECONDS
            ),
            "checkpoint_transition_timeout_seconds": (
                _CHECKPOINT_TRANSITION_TIMEOUT_SECONDS
            ),
            "checkpoint_timeout_seconds": _CHECKPOINT_TIMEOUT_SECONDS,
            "checkpoint_expected_group_count": _EXPECTED_GROUP_COUNT,
            "checkpoint_expected_session_count": _EXPECTED_SESSION_COUNT,
            "checkpoint_group_counts_by_role": {
                "ebgp": 2,
                "ibgp": 2,
            },
        },
        description=(
            "2.7.2 run the pinned one-hour EBB two-port schedule; verify all "
            "DUT-port transitions, exact unaffected-role isolation whenever "
            "one port remains up, four exact bidirectional full-recovery route "
            "legs, and quiescent semantic Update Group integrity every 900 "
            "seconds"
        ),
    )


def _cleanup_steps(
    device_name: str,
    port_tracks: t.Sequence[t.Mapping[str, t.Any]],
    route_pool_regexes: t.Sequence[str],
    state_key: str,
) -> list[Step]:
    return [
        create_bgp_update_group_physical_restore_step(
            device_name=device_name,
            port_tracks=port_tracks,
            transition_timeout_seconds=600,
            description="2.7.2 cleanup: restore and verify both physical links",
        ),
        *_prepare_route_steps(device_name, route_pool_regexes, "cleanup", 100),
        _state_step(device_name, "clear", state_key),
    ]


def _stages(
    device_name: str,
    port_tracks: t.Sequence[t.Mapping[str, t.Any]],
    heartbeat_scenarios: t.Sequence[t.Mapping[str, t.Any]],
    route_pool_regexes: t.Sequence[str],
    state_key: str,
    settle_seconds: int,
) -> list[t.Any]:
    return [
        create_steps_stage(
            steps=[
                *_prepare_route_steps(
                    device_name,
                    route_pool_regexes,
                    "baseline",
                    1,
                ),
                create_longevity_step(
                    duration=settle_seconds,
                    description="2.7.2 settle after withdrawing heartbeat pools",
                ),
                _state_step(device_name, "capture", state_key),
            ]
        ),
        create_steps_stage(
            steps=[_disruption_step(device_name, port_tracks, heartbeat_scenarios)]
        ),
        create_steps_stage(steps=[_state_step(device_name, "compare", state_key)]),
    ]


def _build_playbook(
    *,
    device_name: str,
    port_tracks: list[dict[str, t.Any]],
    heartbeat_scenarios: list[dict[str, t.Any]],
    state_key: str,
    peer_group_substrings: t.Sequence[str],
    expected_member_counts: t.Mapping[str, int],
    expected_afi_by_substring: t.Mapping[str, str],
    prechecks: t.Sequence[PointInTimeHealthCheck],
    postchecks: t.Sequence[PointInTimeHealthCheck],
    snapshot_checks: t.Sequence[SnapshotHealthCheck],
    settle_seconds: int,
) -> Playbook:
    route_pools = _route_pool_regexes(heartbeat_scenarios)
    return Playbook(
        name="update_group_sustained_link_flap",
        setup_steps=[
            create_bgp_agent_log_artifact_step(
                device_name, "capture", state_key, case_id="2.7.2"
            )
        ],
        stages=_stages(
            device_name,
            port_tracks,
            heartbeat_scenarios,
            route_pools,
            state_key,
            settle_seconds,
        ),
        cleanup_steps=[
            create_bgp_agent_log_artifact_step(
                device_name, "publish", state_key, case_id="2.7.2"
            ),
            *_cleanup_steps(device_name, port_tracks, route_pools, state_key),
        ],
        prechecks=_bounded_checks(
            prechecks,
            peer_group_substrings,
            expected_member_counts,
            expected_afi_by_substring,
        ),
        postchecks=_bounded_postchecks(
            postchecks,
            peer_group_substrings,
            expected_member_counts,
            expected_afi_by_substring,
        ),
        snapshot_checks=list(snapshot_checks),
        periodic_tasks=create_standard_periodic_tasks(
            device_name=device_name,
            cpu_load_threshold=12.0,
            memory_threshold=_STRICT_MEMORY_LIMIT_BYTES,
            interval=30,
            cpu_load_terminate_on_error=True,
            memory_terminate_on_error=True,
            enable_queue_backpressure_monitor=False,
        ),
    )


def create_bgp_ug_sustained_link_flap_playbook(
    *,
    device_name: str,
    port_tracks: t.Sequence[t.Mapping[str, t.Any]],
    heartbeat_scenarios: t.Sequence[t.Mapping[str, t.Any]],
    state_key: str,
    peer_group_substrings: t.Sequence[str],
    expected_member_counts: t.Mapping[str, int],
    expected_afi_by_substring: t.Mapping[str, str],
    prechecks: t.Sequence[PointInTimeHealthCheck],
    postchecks: t.Sequence[PointInTimeHealthCheck],
    snapshot_checks: t.Sequence[SnapshotHealthCheck],
    settle_seconds: int = 30,
) -> Playbook:
    """Build spec 2.7.2 with verified triggers and continuous validation."""
    if not state_key:
        raise ValueError("2.7.2 state_key must be non-empty")
    if settle_seconds <= 0:
        raise ValueError("2.7.2 settle_seconds must be positive")
    tracks = _validate_port_tracks(port_tracks)
    heartbeats = _validate_heartbeat_scenarios(heartbeat_scenarios)
    _validate_update_group_contract(
        peer_group_substrings,
        expected_member_counts,
        expected_afi_by_substring,
    )
    return _build_playbook(
        device_name=device_name,
        port_tracks=tracks,
        heartbeat_scenarios=heartbeats,
        state_key=state_key,
        peer_group_substrings=peer_group_substrings,
        expected_member_counts=expected_member_counts,
        expected_afi_by_substring=expected_afi_by_substring,
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
        settle_seconds=settle_seconds,
    )
