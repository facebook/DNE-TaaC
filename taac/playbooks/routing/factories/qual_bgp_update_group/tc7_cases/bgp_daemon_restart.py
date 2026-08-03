# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Spec 2.7.4: BGP restart with Update Group reconstruction proof."""

import ipaddress
import re
import typing as t

from taac.health_checks.healthcheck_definitions import (
    create_bgp_update_group_check,
    create_hardware_capacity_check,
    create_memory_utilization_check,
    create_service_restart_check,
    create_system_cpu_load_average_check,
)
from taac.stages.stage_definitions import (
    create_bgp_restart_test_stage,
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
    create_longevity_step,
    create_prepare_compact_bgp_prefix_pool_step,
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


EXPECTED_SESSION_COUNT = 1272
_EXPECTED_GROUPS = 4
_EXPECTED_IBGP_MEMBERS_PER_AFI = 496
_ROUTE_DELTA = 100
_STRICT_MEMORY_LIMIT_BYTES = 9_999_999_999
_STRICT_MEMORY_GROWTH_LIMIT_BYTES = 199_999_999
_EXPECTED_ALL_PEER_AFIS = {4: 636, 6: 636}
_NON_GATING_ECMP_LEVEL_LIMIT = 2**63 - 1


def _validate_route_inputs(
    route_pool_regex_by_afi: t.Mapping[str, str],
    ibgp_receiver_host_prefixes_by_afi: t.Mapping[str, t.Sequence[str]],
    all_peer_addresses: t.Sequence[str],
) -> dict[str, tuple[str, ...]]:
    expected_afis = {"ipv4", "ipv6"}
    if set(route_pool_regex_by_afi) != expected_afis:
        raise ValueError("route_pool_regex_by_afi must contain ipv4 and ipv6")
    if set(ibgp_receiver_host_prefixes_by_afi) != expected_afis:
        raise ValueError(
            "ibgp_receiver_host_prefixes_by_afi must contain ipv4 and ipv6"
        )
    pools = list(route_pool_regex_by_afi.values())
    if any(not pool for pool in pools) or len(set(pools)) != 2:
        raise ValueError("2.7.4 requires two distinct non-empty 100-route pools")
    for pool in pools:
        try:
            re.compile(pool)
        except re.error as error:
            raise ValueError(
                f"route_pool_regex_by_afi contains invalid regex {pool!r}"
            ) from error
    _validate_all_peer_addresses(all_peer_addresses)
    return {
        afi: _validate_receiver_addresses(afi, ibgp_receiver_host_prefixes_by_afi[afi])
        for afi in ("ipv4", "ipv6")
    }


def _validate_receiver_addresses(
    afi: str, receiver_scopes: t.Sequence[str]
) -> tuple[str, ...]:
    expected_version = 4 if afi == "ipv4" else 6
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for receiver_scope in receiver_scopes:
        try:
            networks.append(ipaddress.ip_network(receiver_scope, strict=False))
        except ValueError as error:
            raise ValueError(
                f"2.7.4 {afi} receivers contain invalid host prefix {receiver_scope!r}"
            ) from error
    if any(
        network.version != expected_version
        or network.prefixlen != network.max_prefixlen
        for network in networks
    ):
        raise ValueError(
            f"2.7.4 {afi} receivers must be individual host addresses or host prefixes"
        )
    addresses = tuple(str(network.network_address) for network in networks)
    if len(addresses) != _EXPECTED_IBGP_MEMBERS_PER_AFI or len(set(addresses)) != len(
        addresses
    ):
        raise ValueError(
            f"2.7.4 requires exactly {_EXPECTED_IBGP_MEMBERS_PER_AFI} unique "
            f"{afi} iBGP receivers"
        )
    return addresses


def _validate_all_peer_addresses(addresses: t.Sequence[str]) -> None:
    if (
        len(addresses) != EXPECTED_SESSION_COUNT
        or len(set(addresses)) != EXPECTED_SESSION_COUNT
    ):
        raise ValueError(
            "all_peer_addresses must contain exactly "
            f"{EXPECTED_SESSION_COUNT} unique peers"
        )
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


def _state_step(device_name: str, action: str, state_key: str) -> Step:
    action_params = None
    if action != "clear":
        action_params = {
            "expected_group_count": _EXPECTED_GROUPS,
            "expected_session_count": EXPECTED_SESSION_COUNT,
            "expected_group_states": ["IDLE"],
            "require_uniform_sent_route_counts": True,
            "require_equal_sent_route_counts": action == "compare",
        }
    return create_bgp_update_group_state_step(
        device_name,
        action,
        state_key,
        action_params=action_params,
        description=f"2.7.4 {action} semantic Update Group state",
    )


def _capacity_step(device_name: str, action: str, state_key: str) -> Step:
    return create_hardware_capacity_delta_step(
        device_name,
        action,
        state_key,
        max_current_delta=100,
        max_high_watermark_increase=100,
        description=f"2.7.4 {action} FEC/ECMP capacity delta baseline",
    )


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
            description=f"2.7.4 snapshot all 496 {afi} iBGP receivers",
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
) -> Step:
    return create_verify_bgp_sent_route_count_delta_step(
        hostname=device_name,
        snapshot_key=snapshot_key,
        peer_addrs=list(all_peer_addresses),
        min_delta=0,
        max_delta=0,
        tolerance=0,
        description=description,
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
            description=f"2.7.4 {phase}: {'advertise' if advertise else 'withdraw'} {afi} pool",
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
            description=f"2.7.4 {phase}: verify inactive 100-route {afi} pool",
        )
        for afi in ("ipv4", "ipv6")
    ]


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
            description=f"2.7.4 require exact {delta:+d} at all 496 {afi} iBGP peers",
        )
        for afi in ("ipv4", "ipv6")
    ]


def _exact_group_check(
    peer_group_substrings: t.Sequence[str],
    expected_member_counts: t.Mapping[str, int],
    expected_afi_by_substring: t.Mapping[str, str],
) -> PointInTimeHealthCheck:
    return create_bgp_update_group_check(
        peer_group_substrings=list(peer_group_substrings),
        expected_member_counts=dict(expected_member_counts),
        expected_afi_by_substring=dict(expected_afi_by_substring),
        expected_out_delay_seconds_by_substring=dict.fromkeys(peer_group_substrings, 0),
        expected_group_count=_EXPECTED_GROUPS,
        expected_group_states=["IDLE"],
        expect_enabled=True,
    )


def _bounded_checks(
    checks: t.Sequence[PointInTimeHealthCheck],
    peer_group_substrings: t.Sequence[str],
    expected_member_counts: t.Mapping[str, int],
    expected_afi_by_substring: t.Mapping[str, str],
    *,
    fec_threshold: int,
    enforce_absolute_high_watermarks: bool = False,
) -> list[PointInTimeHealthCheck]:
    return [
        *checks,
        _exact_group_check(
            peer_group_substrings,
            expected_member_counts,
            expected_afi_by_substring,
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


def _runtime_route_stage(
    device_name: str,
    state_key: str,
    pools: t.Mapping[str, str],
    receivers: t.Mapping[str, t.Sequence[str]],
) -> t.Any:
    steps = [
        *_route_toggle_steps(device_name, pools, advertise=True, phase="runtime"),
        create_longevity_step(
            duration=30,
            description="2.7.4 bound runtime route convergence to 30 seconds",
        ),
        *_route_verify_steps(device_name, state_key, receivers, _ROUTE_DELTA),
        *_route_toggle_steps(device_name, pools, advertise=False, phase="restore"),
        create_longevity_step(duration=30, description="2.7.4 settle withdrawals"),
        *_route_verify_steps(device_name, state_key, receivers, 0),
    ]
    return create_steps_stage(steps=steps)


def _baseline_stage(
    device_name: str,
    state_key: str,
    pools: t.Mapping[str, str],
    receivers: t.Mapping[str, t.Sequence[str]],
    all_peer_addresses: t.Sequence[str],
) -> t.Any:
    return create_steps_stage(
        steps=[
            *_route_prepare_steps(device_name, pools, "baseline"),
            create_longevity_step(duration=30, description="2.7.4 settle baseline"),
            _capacity_step(device_name, "capture", state_key),
            _state_step(device_name, "capture", state_key),
            *_route_snapshot_steps(device_name, state_key, receivers),
            _all_peer_snapshot_step(
                device_name,
                f"{state_key}:all-1272-peers",
                all_peer_addresses,
                "2.7.4 snapshot route counts on all exact 1272 peers",
            ),
        ]
    )


def _soak_stage(device_name: str, state_key: str) -> t.Any:
    memory_monitor = create_custom_step(
        params_dict={
            "custom_step_name": "bgp_vmhwm_growth_monitor",
            "hostname": device_name,
            "duration_seconds": 1800,
            "growth_threshold_bytes": _STRICT_MEMORY_GROWTH_LIMIT_BYTES,
            "process_name": "bgpcpp",
        },
        description=(
            "2.7.4 prove 30-minute VmHWM growth stays below strict 200 MB bound"
        ),
    )
    return create_concurrent_steps_stage(
        [
            [
                create_longevity_step(
                    duration=1800,
                    description="2.7.4 30-minute stable soak",
                ),
                _state_step(device_name, "compare", state_key),
            ],
            [memory_monitor],
        ],
        description="2.7.4 soak with concurrent range-bound memory evidence",
    )


def _restart_stages(
    device_name: str,
    state_key: str,
    pools: t.Mapping[str, str],
    receivers: t.Mapping[str, t.Sequence[str]],
    all_peer_addresses: t.Sequence[str],
    parent_prefixes_to_ignore: t.Sequence[str],
) -> list[t.Any]:
    restart = create_bgp_restart_test_stage(
        device_name=device_name,
        reactivate_device_groups=False,
        adaptive_convergence=True,
        expected_established_sessions=EXPECTED_SESSION_COUNT,
        parent_prefixes_to_ignore=list(parent_prefixes_to_ignore),
        convergence_soft_threshold_seconds=600.0,
        convergence_hard_timeout_seconds=600.0,
        convergence_poll_interval_seconds=5.0,
    )
    validation = create_steps_stage(
        steps=[
            _state_step(device_name, "compare", state_key),
            _all_peer_parity_step(
                device_name,
                f"{state_key}:all-1272-peers",
                all_peer_addresses,
                "2.7.4 require pre/post restart route-count parity on all peers",
            ),
            _capacity_step(device_name, "compare", state_key),
            _all_peer_snapshot_step(
                device_name,
                f"{state_key}:stable-all-1272-peers",
                all_peer_addresses,
                "2.7.4 snapshot all-peer route counts after reconstruction",
            ),
            create_longevity_step(
                duration=30,
                description="2.7.4 hold reconstructed state stable for 30 seconds",
            ),
            _state_step(device_name, "compare", state_key),
            _all_peer_parity_step(
                device_name,
                f"{state_key}:stable-all-1272-peers",
                all_peer_addresses,
                "2.7.4 require unchanged all-peer route counts after 30 seconds",
            ),
        ]
    )
    soak = _soak_stage(device_name, state_key)
    return [
        restart,
        validation,
        _runtime_route_stage(device_name, state_key, pools, receivers),
        soak,
    ]


def _postchecks(
    checks: t.Sequence[PointInTimeHealthCheck],
    peer_groups: t.Sequence[str],
    member_counts: t.Mapping[str, int],
    afis: t.Mapping[str, str],
) -> list[PointInTimeHealthCheck]:
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
    bounded.append(
        create_service_restart_check(
            services=["Bgp", "FibAgent", "FibAgentBgp"],
            daemons=["FibBgpGrpc"],
            expected_restarted_services=["Bgp"],
            restart_start_time_jq_var="daemon_restart_time",
        )
    )
    return bounded


def _is_service_restart_check(check: PointInTimeHealthCheck) -> bool:
    return check.name == hc_types.CheckName.SERVICE_RESTART_CHECK


def _cleanup_steps(
    device_name: str,
    state_key: str,
    pools: t.Mapping[str, str],
    parent_prefixes_to_ignore: t.Sequence[str],
) -> list[Step]:
    return [
        _state_step(device_name, "clear", state_key),
        _capacity_step(device_name, "clear", state_key),
        *_route_prepare_steps(device_name, pools, "cleanup"),
        create_daemon_control_step(
            device_name=device_name,
            daemon_name="Bgp",
            action="enable",
            description="2.7.4 cleanup: idempotently enable Bgp",
        ),
        create_bgp_lifecycle_convergence_step(
            device_name=device_name,
            expected_established_sessions=EXPECTED_SESSION_COUNT,
            parent_prefixes_to_ignore=list(parent_prefixes_to_ignore),
            convergence_soft_threshold_seconds=600.0,
            convergence_hard_timeout_seconds=600.0,
            convergence_poll_interval_seconds=5.0,
            description="2.7.4 cleanup: restore all 1272 BGP sessions",
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


def create_bgp_ug_bgp_daemon_restart_playbook(
    *,
    device_name: str,
    state_key: str,
    route_pool_regex_by_afi: t.Mapping[str, str],
    ibgp_receiver_host_prefixes_by_afi: t.Mapping[str, t.Sequence[str]],
    all_peer_addresses: t.Sequence[str],
    peer_group_substrings: t.Sequence[str],
    expected_member_counts: t.Mapping[str, int],
    expected_afi_by_substring: t.Mapping[str, str],
    prechecks: t.Sequence[PointInTimeHealthCheck],
    postchecks: t.Sequence[PointInTimeHealthCheck],
    snapshot_checks: t.Sequence[SnapshotHealthCheck],
    parent_prefixes_to_ignore: t.Sequence[str] = (),
) -> Playbook:
    """Build 2.7.4 with a verified 600-second reconstruction boundary."""
    receiver_addrs = _validate_route_inputs(
        route_pool_regex_by_afi,
        ibgp_receiver_host_prefixes_by_afi,
        all_peer_addresses,
    )
    return Playbook(
        name="bgp_ug_bgp_daemon_restart",
        setup_steps=[
            create_bgp_agent_log_artifact_step(
                device_name, "capture", state_key, case_id="2.7.4"
            )
        ],
        stages=[
            _baseline_stage(
                device_name,
                state_key,
                route_pool_regex_by_afi,
                receiver_addrs,
                all_peer_addresses,
            ),
            *_restart_stages(
                device_name,
                state_key,
                route_pool_regex_by_afi,
                receiver_addrs,
                all_peer_addresses,
                parent_prefixes_to_ignore,
            ),
        ],
        cleanup_steps=[
            create_bgp_agent_log_artifact_step(
                device_name, "publish", state_key, case_id="2.7.4"
            ),
            *_cleanup_steps(
                device_name,
                state_key,
                route_pool_regex_by_afi,
                parent_prefixes_to_ignore,
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
