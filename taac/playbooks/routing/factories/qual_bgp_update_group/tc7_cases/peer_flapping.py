# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Spec 2.7.3: verified fixed-set BGP peer flapping and recovery."""

import ipaddress
import re
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
    create_longevity_step,
    create_prepare_compact_bgp_prefix_pool_step,
    create_snapshot_bgp_vmhwm_step,
    create_validation_step,
    create_verify_bgp_vmhwm_growth_step,
)
from taac.task_definitions import create_standard_periodic_tasks
from taac.test_as_a_config.types import (
    Playbook,
    PointInTimeHealthCheck,
    SnapshotHealthCheck,
    Stage,
    Step,
    ValidationStage,
)


_EXPECTED_SESSION_COUNT = 1272
_EXPECTED_GROUP_COUNT = 4
_EXPECTED_RECEIVER_COUNT = 992
_EXPECTED_ROUTE_DELTA = 20
_DURATION_SECONDS = 1800
_ROUTE_PERIOD_SECONDS = 60
_ROUTE_ACTIVE_SECONDS = 10
_ROUTE_CYCLES = 30
_ABSOLUTE_MEMORY_CEILING_BYTES = 9_999_999_999
_STRICT_GROWTH_LIMIT_BYTES = 199_999_999
_PEER_GROUPS = ("EB-FA-V4", "EB-FA-V6", "EB-EB-V4", "EB-EB-V6")
_MEMBER_COUNTS = {
    "EB-FA-V4": 140,
    "EB-FA-V6": 140,
    "EB-EB-V4": 496,
    "EB-EB-V6": 496,
}
_AFIS = {
    "EB-FA-V4": "ipv4",
    "EB-FA-V6": "ipv6",
    "EB-EB-V4": "ipv4",
    "EB-EB-V6": "ipv6",
}


def _validate_dual_afi_addresses(addresses: t.Sequence[str]) -> None:
    if len(addresses) != 2 or len(set(addresses)) != 2:
        raise ValueError(
            "2.7.3 requires exactly two unique reserved stable advertisers"
        )
    versions = set()
    for address in addresses:
        try:
            versions.add(ipaddress.ip_address(address).version)
        except ValueError as error:
            raise ValueError(
                f"2.7.3 reserved stable advertiser {address!r} is not a valid IP address"
            ) from error
    if versions != {4, 6}:
        raise ValueError(
            "2.7.3 reserved stable advertisers must contain one IPv4 and one IPv6 peer"
        )


def _validate_receiver_scope(receiver_parent_prefixes: t.Sequence[str]) -> None:
    if (
        len(receiver_parent_prefixes) != _EXPECTED_RECEIVER_COUNT
        or len(set(receiver_parent_prefixes)) != _EXPECTED_RECEIVER_COUNT
    ):
        raise ValueError(
            f"2.7.3 requires exactly {_EXPECTED_RECEIVER_COUNT} unique iBGP receivers"
        )
    networks = []
    for prefix in receiver_parent_prefixes:
        try:
            networks.append(ipaddress.ip_network(prefix, strict=False))
        except ValueError as error:
            raise ValueError(
                f"2.7.3 receiver prefix {prefix!r} is not a valid IP prefix"
            ) from error
    versions = [network.version for network in networks]
    valid_hosts = all(
        network.prefixlen == (32 if network.version == 4 else 128)
        for network in networks
    )
    expected_per_afi = _EXPECTED_RECEIVER_COUNT // 2
    if (
        versions.count(4) != expected_per_afi
        or versions.count(6) != expected_per_afi
        or not valid_hosts
    ):
        raise ValueError(
            f"2.7.3 requires {expected_per_afi} IPv4 /32 and "
            f"{expected_per_afi} IPv6 /128 iBGP receivers"
        )


def _validate_inputs(
    *,
    device_name: str,
    peer_regex: str,
    reserved_peer_addresses: t.Sequence[str],
    churn_prefix_pool_regexes: t.Sequence[str],
    receiver_parent_prefixes: t.Sequence[str],
    seed: int,
    settle_seconds: int,
) -> None:
    if not device_name.strip():
        raise ValueError("2.7.3 device_name must be non-empty")
    if not peer_regex:
        raise ValueError("2.7.3 peer_regex must be non-empty")
    try:
        re.compile(peer_regex)
    except re.error as error:
        raise ValueError(
            f"2.7.3 peer regex {peer_regex!r} is invalid: {error}"
        ) from error
    _validate_dual_afi_addresses(reserved_peer_addresses)
    if len(churn_prefix_pool_regexes) != 2 or len(set(churn_prefix_pool_regexes)) != 2:
        raise ValueError("2.7.3 requires exactly two unique dual-AFI churn pools")
    for pool_regex in churn_prefix_pool_regexes:
        if not isinstance(pool_regex, str) or not pool_regex.strip():
            raise ValueError(
                f"2.7.3 churn pool regex must be non-empty: {pool_regex!r}"
            )
        try:
            re.compile(pool_regex)
        except re.error as error:
            raise ValueError(
                f"2.7.3 churn pool regex {pool_regex!r} is invalid: {error}"
            ) from error
    _validate_receiver_scope(receiver_parent_prefixes)
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("2.7.3 seed must be an integer")
    if settle_seconds <= 0:
        raise ValueError("2.7.3 settle_seconds must be positive")


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
        description=f"2.7.3 {action} semantic Update Group state",
    )


def _prepare_pool_steps(
    device_name: str,
    churn_prefix_pool_regexes: t.Sequence[str],
    *,
    target_count: int,
    allowed_current_counts: t.Sequence[int],
    phase: str,
    operation: str,
) -> list[Step]:
    return [
        create_prepare_compact_bgp_prefix_pool_step(
            device_name=device_name,
            prefix_pool_regex=pool_regex,
            target_number_of_addresses=target_count,
            allowed_current_number_of_addresses=allowed_current_counts,
            safe_number_of_addresses=100,
            description=(
                f"2.7.3 {phase}: {operation} shared runtime pool "
                f"to {target_count} routes"
            ),
        )
        for pool_regex in churn_prefix_pool_regexes
    ]


def _disruption_step(
    *,
    device_name: str,
    peer_regex: str,
    seed: int,
    reserved_peer_addresses: t.Sequence[str],
    churn_prefix_pool_regexes: t.Sequence[str],
    receiver_parent_prefixes: t.Sequence[str],
    expected_receiver_count: int,
    expected_route_delta: int,
    duration_seconds: int,
) -> Step:
    return create_bgp_update_group_disruption_step(
        device_name=device_name,
        action="fixed_peer_flap",
        action_params={
            "peer_regex": peer_regex,
            "seed": seed,
            "reserved_peer_addresses": list(reserved_peer_addresses),
            "duration_seconds": duration_seconds,
            "churn_prefix_pool_regexes": list(churn_prefix_pool_regexes),
            "receiver_parent_prefixes": list(receiver_parent_prefixes),
            "expected_receiver_count": expected_receiver_count,
            "expected_session_count": _EXPECTED_SESSION_COUNT,
            "expected_route_delta": expected_route_delta,
            "route_period_seconds": _ROUTE_PERIOD_SECONDS,
            "route_active_seconds": _ROUTE_ACTIVE_SECONDS,
            "expected_route_cycles": _ROUTE_CYCLES,
            "restore_timeout_seconds": 600,
            "start_headroom_seconds": 5,
        },
        description=(
            "2.7.3 deterministically select 64 non-reserved eBGP sessions; "
            "verify exact 5s Stop/Start edges for 30 minutes while the two stable "
            "dual-AFI advertisers inject and withdraw 20 routes every 60s; "
            "require every post-withdraw route baseline, per-cycle Update Group "
            "announcement/withdrawal counters, and a final per-peer UPDATE "
            "socket-counter audit, then bounded full peer and Update Group recovery"
        ),
    )


def _exact_update_group_check(
    *,
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
    return _resource_checks(
        [
            *checks,
            _exact_update_group_check(
                peer_group_substrings=peer_group_substrings,
                expected_member_counts=expected_member_counts,
                expected_afi_by_substring=expected_afi_by_substring,
                expected_group_count=expected_group_count,
            ),
        ]
    )


def _resource_checks(
    checks: t.Sequence[PointInTimeHealthCheck],
) -> list[PointInTimeHealthCheck]:
    return [
        *checks,
        create_system_cpu_load_average_check(baseline=12.0),
        create_memory_utilization_check(vmhwm_threshold=_ABSOLUTE_MEMORY_CEILING_BYTES),
    ]


def _build_stages(
    *,
    device_name: str,
    update_group_check: PointInTimeHealthCheck,
    capture: Step,
    disruption: Step,
    compare: Step,
    churn_prefix_pool_regexes: t.Sequence[str],
    settle_seconds: int,
    memory_snapshot_key: str,
) -> list[Stage]:
    return [
        create_steps_stage(
            steps=[
                *_prepare_pool_steps(
                    device_name,
                    churn_prefix_pool_regexes,
                    target_count=20,
                    allowed_current_counts=(100,),
                    phase="baseline",
                    operation="compact",
                ),
                create_longevity_step(
                    duration=settle_seconds,
                    description="2.7.3 settle with both runtime pools withdrawn",
                ),
                create_validation_step(
                    point_in_time_checks=[update_group_check],
                    stage=ValidationStage.PRE_TEST,
                    description=(
                        "2.7.3 gate exact Update Group membership, AFI, IAR, and "
                        "steady state after startup convergence"
                    ),
                ),
                capture,
                create_snapshot_bgp_vmhwm_step(
                    hostname=device_name,
                    snapshot_key=memory_snapshot_key,
                    description=(
                        "2.7.3 record VmHWM immediately before peer and route churn"
                    ),
                ),
            ]
        ),
        create_steps_stage(steps=[disruption]),
        create_steps_stage(
            steps=[
                compare,
                create_verify_bgp_vmhwm_growth_step(
                    hostname=device_name,
                    snapshot_key=memory_snapshot_key,
                    growth_threshold_bytes=_STRICT_GROWTH_LIMIT_BYTES,
                    description=(
                        "2.7.3 require VmHWM growth below 200 MB after full recovery"
                    ),
                ),
            ]
        ),
    ]


def _cleanup_steps(
    device_name: str,
    churn_prefix_pool_regexes: t.Sequence[str],
    state_key: str,
) -> list[Step]:
    return [
        *_prepare_pool_steps(
            device_name,
            churn_prefix_pool_regexes,
            target_count=100,
            allowed_current_counts=(20, 100),
            phase="cleanup",
            operation="restore",
        ),
        create_bgp_update_group_state_step(
            device_name=device_name,
            action="clear",
            state_key=state_key,
            description="2.7.3 cleanup: clear semantic Update Group baseline",
        ),
    ]


def _create_core_steps(
    *,
    device_name: str,
    peer_regex: str,
    seed: int,
    reserved_peer_addresses: t.Sequence[str],
    churn_prefix_pool_regexes: t.Sequence[str],
    receiver_parent_prefixes: t.Sequence[str],
    state_key: str,
) -> tuple[Step, Step, Step]:
    capture = _state_step(
        device_name,
        "capture",
        state_key,
        _EXPECTED_GROUP_COUNT,
        _EXPECTED_SESSION_COUNT,
    )
    compare = _state_step(
        device_name,
        "compare",
        state_key,
        _EXPECTED_GROUP_COUNT,
        _EXPECTED_SESSION_COUNT,
    )
    disruption = _disruption_step(
        device_name=device_name,
        peer_regex=peer_regex,
        seed=seed,
        reserved_peer_addresses=reserved_peer_addresses,
        churn_prefix_pool_regexes=churn_prefix_pool_regexes,
        receiver_parent_prefixes=receiver_parent_prefixes,
        expected_receiver_count=_EXPECTED_RECEIVER_COUNT,
        expected_route_delta=_EXPECTED_ROUTE_DELTA,
        duration_seconds=_DURATION_SECONDS,
    )
    return capture, disruption, compare


def _assemble_playbook(
    *,
    device_name: str,
    core_steps: tuple[Step, Step, Step],
    churn_prefix_pool_regexes: t.Sequence[str],
    state_key: str,
    prechecks: t.Sequence[PointInTimeHealthCheck],
    postchecks: t.Sequence[PointInTimeHealthCheck],
    snapshot_checks: t.Sequence[SnapshotHealthCheck],
    settle_seconds: int,
) -> Playbook:
    capture, disruption, compare = core_steps
    check_args = {
        "peer_group_substrings": _PEER_GROUPS,
        "expected_member_counts": _MEMBER_COUNTS,
        "expected_afi_by_substring": _AFIS,
        "expected_group_count": _EXPECTED_GROUP_COUNT,
    }
    bounded_postchecks = _bounded_checks(postchecks, **check_args)
    update_group_check = _exact_update_group_check(**check_args)
    bounded_postchecks.append(
        create_service_restart_check(services=["Bgp"], daemons=["FibBgpGrpc"])
    )
    return Playbook(
        name="bgp_ug_bgp_peer_flapping",
        setup_steps=[
            create_bgp_agent_log_artifact_step(
                device_name, "capture", state_key, case_id="2.7.3"
            )
        ],
        stages=_build_stages(
            device_name=device_name,
            update_group_check=update_group_check,
            capture=capture,
            disruption=disruption,
            compare=compare,
            churn_prefix_pool_regexes=churn_prefix_pool_regexes,
            settle_seconds=settle_seconds,
            memory_snapshot_key=f"{state_key}:vmhwm",
        ),
        cleanup_steps=[
            create_bgp_agent_log_artifact_step(
                device_name, "publish", state_key, case_id="2.7.3"
            ),
            *_cleanup_steps(device_name, churn_prefix_pool_regexes, state_key),
        ],
        prechecks=_resource_checks(prechecks),
        postchecks=bounded_postchecks,
        snapshot_checks=list(snapshot_checks),
        periodic_tasks=create_standard_periodic_tasks(
            device_name=device_name,
            cpu_load_threshold=12.0,
            memory_threshold=_ABSOLUTE_MEMORY_CEILING_BYTES,
            interval=30,
            cpu_load_terminate_on_error=True,
            cpu_util_terminate_on_error=True,
            memory_terminate_on_error=True,
            enable_queue_backpressure_monitor=False,
        ),
    )


def create_bgp_ug_bgp_peer_flapping_playbook(
    *,
    device_name: str,
    peer_regex: str,
    reserved_peer_addresses: t.Sequence[str],
    churn_prefix_pool_regexes: t.Sequence[str],
    receiver_parent_prefixes: t.Sequence[str],
    state_key: str,
    prechecks: t.Sequence[PointInTimeHealthCheck],
    postchecks: t.Sequence[PointInTimeHealthCheck],
    snapshot_checks: t.Sequence[SnapshotHealthCheck],
    seed: int = 2713,
    settle_seconds: int = 30,
) -> Playbook:
    """Build spec 2.7.3 with verified trigger, delivery, and recovery gates."""
    _validate_inputs(
        device_name=device_name,
        peer_regex=peer_regex,
        reserved_peer_addresses=reserved_peer_addresses,
        churn_prefix_pool_regexes=churn_prefix_pool_regexes,
        receiver_parent_prefixes=receiver_parent_prefixes,
        seed=seed,
        settle_seconds=settle_seconds,
    )
    core_steps = _create_core_steps(
        device_name=device_name,
        peer_regex=peer_regex,
        seed=seed,
        reserved_peer_addresses=reserved_peer_addresses,
        churn_prefix_pool_regexes=churn_prefix_pool_regexes,
        receiver_parent_prefixes=receiver_parent_prefixes,
        state_key=state_key,
    )
    return _assemble_playbook(
        device_name=device_name,
        core_steps=core_steps,
        churn_prefix_pool_regexes=churn_prefix_pool_regexes,
        state_key=state_key,
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
        settle_seconds=settle_seconds,
    )
