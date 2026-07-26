# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""BGPCPP-on-EBB playbook factories (one factory = one playbook = one test case).

Naming: ``create_bgp_ebb_<usecase>_playbook``. Playbook ``name=`` field
values are GRANDFATHERED from the legacy ``playbooks/playbook_definitions.py``
home (Wave 4 will rename them to the canonical framework form).

See README.md.
"""

import typing as t

from taac.constants import (
    BgpPlusPlusProfile,
    DEFAULT_OPENR_START_IPV4S,
    DEFAULT_OPENR_START_IPV6S,
    Gigabyte,
    OpenRRouteAction,
)
from taac.stages.stage_definitions import (
    create_attribute_churn_stage,
    create_bgp_igp_instability_unresolvable_pnhs_stage,
    create_bgp_restart_test_stage,
    create_bgp_session_oscillation_stage,
    create_cold_start_test_stage,
    create_fauu_drain_undrain_stage,
    create_longevity_churn_stage,
    create_multipath_group_oscillation_stage,
    create_plane_aware_bgp_session_oscillation_stage,
    create_plane_drain_undrain_stage,
    create_revert_route_storm_stage,
    create_route_oscillations_stage,
    create_route_registry_runtime_update_stage,
    create_route_storm_stage,
    create_steps_stage,
)
from taac.steps.step_definitions import (
    create_advertise_withdraw_prefixes_step,
    create_bgp_instability_setup_steps,
    create_bgp_restart_setup_steps,
    create_longevity_step,
    create_openr_route_action_step,
    create_route_registry_prefix_list_setup_steps,
    create_set_route_filter_step,
    create_snapshot_bgp_withdraw_sent_counter_step,
    create_verify_bgp_withdraw_send_quiet_step,
)
from taac.task_definitions import (
    create_nexthop_group_poll_periodic_task,
)
from taac.testconfigs.routing.util.bgp_ebb_check_profiles import (
    CheckProfile,
    get_profile_checks,
    ProfileContext,
)
from taac.testconfigs.routing.util.bgp_ebb_periodic_tasks import (
    create_standard_periodic_tasks,
)
from taac.utils.hardware_capacity_utils import (
    get_postcheck_thresholds,
    get_precheck_thresholds,
    HardwareCapacityThresholds,
)
from taac.test_as_a_config.types import Playbook


__all__ = [
    "create_bgp_ebb_cold_start_playbook",
    "create_bgp_ebb_daemon_restart_playbook",
    "create_bgp_ebb_ebgp_route_oscillations_playbook",
    "create_bgp_ebb_ebgp_session_oscillations_playbook",
    "create_bgp_ebb_fauu_drain_undrain_playbook",
    "create_bgp_ebb_ibgp_route_oscillations_playbook",
    "create_bgp_ebb_ibgp_tornado_plane_oscillations_playbook",
    "create_bgp_ebb_igp_instability_unresolvable_pnhs_playbook",
    "create_bgp_ebb_igp_pnh_metric_oscillation_playbook",
    "create_bgp_ebb_instability_attribute_churn_playbook",
    "create_bgp_ebb_longevity_playbook",
    "create_bgp_ebb_multipath_group_oscillation_playbook",
    "create_bgp_ebb_nexthop_group_count_threshold_playbook",
    "create_bgp_ebb_plane_drain_undrain_playbook",
    "create_bgp_ebb_route_registry_runtime_update_playbook",
    "create_bgp_ebb_route_storm_playbook",
]


def create_bgp_ebb_daemon_restart_playbook(
    device_name: str,
    peergroup_ibgp_v6: str,
    peergroup_ibgp_v4: str,
    profile: BgpPlusPlusProfile = BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
    cpu_baseline: float = 8.0,
    memory_threshold: int = Gigabyte.GIG_5.value,
    cpu_util_terminate_on_error: bool = False,
    memory_terminate_on_error: bool = False,
    enable_thread_cpu_monitoring: bool = False,
    thread_name_filter: t.Optional[t.List[str]] = None,
    enable_offcpu_profiling: bool = False,
    enable_perf_profiling: bool = False,
    enable_bgp_events: bool = False,
    enable_socket_monitoring: bool = False,
    precheck_thresholds: t.Optional[HardwareCapacityThresholds] = None,
    postcheck_thresholds: t.Optional[HardwareCapacityThresholds] = None,
    expected_peer_identity: t.Optional[t.Dict[str, str]] = None,
    parent_prefixes_to_ignore: t.Optional[t.List[str]] = None,
    exclude_bgp_mon: bool = True,
) -> Playbook:
    """
    Create a BGP daemon restart test playbook.

    This playbook tests the BGP daemon restart behavior by:
    1. Setting up BGP restart prerequisites
    2. Running standard prechecks (session state, hardware capacity, etc.)
    3. Executing the BGP restart test stage
    4. Running standard postchecks (convergence, service restart verification)

    Args:
        device_name: Name of the device under test
        peergroup_ibgp_v6: IPv6 iBGP peer group name for session checks
        peergroup_ibgp_v4: IPv4 iBGP peer group name for session checks
        profile: BGP++ profile (with or without Open/R)
        cpu_baseline: CPU baseline threshold for prechecks (default: 6.0)
        memory_threshold: Memory threshold in bytes (default: 5GB)
        cpu_util_terminate_on_error: Terminate test on CPU threshold breach
        memory_terminate_on_error: Terminate test on memory threshold breach
        enable_thread_cpu_monitoring: Enable per-thread CPU monitoring
        thread_name_filter: List of thread name prefixes to monitor
        enable_offcpu_profiling: Enable off-CPU profiling
        enable_perf_profiling: Enable perf profiling for flame graphs
        enable_bgp_events: Enable BGP event annotation on timeline
        enable_socket_monitoring: Enable socket statistics monitoring
        precheck_thresholds: Custom precheck thresholds (uses defaults if None)
        postcheck_thresholds: Custom postcheck thresholds (uses defaults if None)

    Returns:
        Playbook configured for BGP daemon restart testing
    """
    if thread_name_filter is None:
        thread_name_filter = ["fi"]  # Fiber threads by default

    if precheck_thresholds is None:
        precheck_thresholds = get_precheck_thresholds()

    if postcheck_thresholds is None:
        postcheck_thresholds = get_postcheck_thresholds()

    restart_checks = get_profile_checks(
        CheckProfile.DAEMON_RESTART,
        ProfileContext(
            peergroup_ibgp_v6=peergroup_ibgp_v6,
            peergroup_ibgp_v4=peergroup_ibgp_v4,
            precheck_thresholds=precheck_thresholds,
            postcheck_thresholds=postcheck_thresholds,
            cpu_baseline=cpu_baseline,
            check_ibgp_pnh=(profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R),
            expected_peer_identity=expected_peer_identity,
            parent_prefixes_to_ignore=parent_prefixes_to_ignore,
            exclude_bgp_mon=exclude_bgp_mon,
        ),
    )
    return Playbook(
        name="bgp_daemon_restart_test_playbook",
        setup_steps=create_bgp_restart_setup_steps(device_name=device_name),
        prechecks=restart_checks.prechecks,
        postchecks=restart_checks.postchecks,
        snapshot_checks=restart_checks.snapshot_checks,
        periodic_tasks=create_standard_periodic_tasks(
            device_name=device_name,
            memory_threshold=memory_threshold,
            cpu_util_terminate_on_error=cpu_util_terminate_on_error,
            memory_terminate_on_error=memory_terminate_on_error,
        ),
        stages=[
            create_bgp_restart_test_stage(
                device_name=device_name,
                enable_thread_cpu_monitoring=enable_thread_cpu_monitoring,
                thread_name_filter=thread_name_filter,
                enable_offcpu_profiling=enable_offcpu_profiling,
                enable_perf_profiling=enable_perf_profiling,
                enable_bgp_events=enable_bgp_events,
            ),
        ],
    )


def create_bgp_ebb_cold_start_playbook(
    device_name: str,
    peergroup_ibgp_v6: str,
    peergroup_ibgp_v4: str,
    profile: BgpPlusPlusProfile = BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
    cpu_baseline: float = 8.0,
    memory_threshold: int = Gigabyte.GIG_5.value,
    cpu_util_terminate_on_error: bool = False,
    memory_terminate_on_error: bool = False,
    enable_thread_cpu_monitoring: bool = True,
    thread_name_filter: t.Optional[t.List[str]] = None,
    thread_cpu_monitoring_interval_seconds: int = 2,
    enable_offcpu_profiling: bool = False,
    enable_perf_profiling: bool = False,
    enable_bgp_events: bool = False,
    enable_socket_monitoring: bool = False,
    fail_on_eor_expired: bool = False,
    precheck_thresholds: t.Optional[HardwareCapacityThresholds] = None,
    postcheck_thresholds: t.Optional[HardwareCapacityThresholds] = None,
    expected_peer_identity: t.Optional[t.Dict[str, str]] = None,
    exclude_bgp_mon: bool = True,
) -> Playbook:
    """
    Create a BGP cold start test playbook.

    This playbook tests the BGP cold start behavior by:
    1. Setting up BGP restart prerequisites
    2. Running standard prechecks
    3. Executing the cold start test stage with CPU/perf profiling
    4. Running standard postchecks (with EOR expiry tolerance)

    Cold start differs from daemon restart in that:
    - It simulates a full BGP process restart from scratch
    - Thread CPU monitoring is enabled by default
    - Perf profiling is enabled by default for performance analysis
    - EOR (End of RIB) expiry is tolerated by default

    Args:
        device_name: Name of the device under test
        peergroup_ibgp_v6: IPv6 iBGP peer group name for session checks
        peergroup_ibgp_v4: IPv4 iBGP peer group name for session checks
        profile: BGP++ profile (with or without Open/R)
        memory_threshold: Memory threshold in bytes (default: 5GB)
        cpu_util_terminate_on_error: Terminate test on CPU threshold breach
        memory_terminate_on_error: Terminate test on memory threshold breach
        enable_thread_cpu_monitoring: Enable per-thread CPU monitoring (default: True)
        thread_name_filter: List of thread name prefixes to monitor
        thread_cpu_monitoring_interval_seconds: Monitoring interval (default: 2s)
        enable_offcpu_profiling: Enable off-CPU profiling
        enable_perf_profiling: Enable perf profiling for flame graphs (default: True)
        enable_bgp_events: Enable BGP event annotation on timeline
        enable_socket_monitoring: Enable socket statistics monitoring
        fail_on_eor_expired: Whether to fail if EOR expires (default: False)
        precheck_thresholds: Custom precheck thresholds (uses defaults if None)
        postcheck_thresholds: Custom postcheck thresholds (uses defaults if None)

    Returns:
        Playbook configured for BGP cold start testing
    """
    if thread_name_filter is None:
        thread_name_filter = [
            "fi",  # Fiber threads
            "pe",  # PeerManager threads
            "ri",  # RIB threads
        ]

    if precheck_thresholds is None:
        precheck_thresholds = get_precheck_thresholds()

    if postcheck_thresholds is None:
        postcheck_thresholds = get_postcheck_thresholds()

    cold_start_checks = get_profile_checks(
        CheckProfile.COLD_START,
        ProfileContext(
            peergroup_ibgp_v6=peergroup_ibgp_v6,
            peergroup_ibgp_v4=peergroup_ibgp_v4,
            precheck_thresholds=precheck_thresholds,
            postcheck_thresholds=postcheck_thresholds,
            cpu_baseline=cpu_baseline,
            check_ibgp_pnh=(profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R),
            expected_peer_identity=expected_peer_identity,
            exclude_bgp_mon=exclude_bgp_mon,
            fail_on_eor_expired=fail_on_eor_expired,
        ),
    )
    return Playbook(
        name="bgp_cold_start_test_playbook",
        setup_steps=create_bgp_restart_setup_steps(device_name=device_name),
        prechecks=cold_start_checks.prechecks,
        postchecks=cold_start_checks.postchecks,
        snapshot_checks=cold_start_checks.snapshot_checks,
        periodic_tasks=create_standard_periodic_tasks(
            device_name=device_name,
            memory_threshold=memory_threshold,
            cpu_util_terminate_on_error=cpu_util_terminate_on_error,
            memory_terminate_on_error=memory_terminate_on_error,
        ),
        stages=[
            create_cold_start_test_stage(
                device_name=device_name,
                enable_thread_cpu_monitoring=enable_thread_cpu_monitoring,
                thread_name_filter=thread_name_filter,
                enable_offcpu_profiling=enable_offcpu_profiling,
                thread_cpu_monitoring_interval_seconds=thread_cpu_monitoring_interval_seconds,
                enable_perf_profiling=enable_perf_profiling,
                enable_bgp_events=enable_bgp_events,
                enable_socket_monitoring=enable_socket_monitoring,
            ),
        ],
    )


def create_bgp_ebb_instability_attribute_churn_playbook(
    device_name: str,
    peergroup_ibgp_v6: str,
    peergroup_ibgp_v4: str,
    total_session_count: int,
    profile,  # BgpPlusPlusProfile
    exclude_bgp_mon: bool = True,
) -> Playbook:
    """Build the BAG010_ASH6 BGP instability + attribute churn Playbook.

    Drives the BGP++ peer set through a sustained attribute-churn stage
    (local_pref / med / origin / as_path iterations on the IBGP plane 1
    drain pool) to stress bgpcpp routing-attribute storage and update
    generation. Used by the BAG010_ASH6 BGP++ instability TestConfigs to
    verify the device does not crash, leak memory, or drop sessions under
    continuous attribute mutation.

    Args:
        device_name: DUT hostname (used for setup steps and periodic tasks).
        peergroup_ibgp_v6: IBGP IPv6 peer-group name on the DUT (passed to
            standard prechecks to assert expected established sessions).
        peergroup_ibgp_v4: IBGP IPv4 peer-group name on the DUT.
        total_session_count: Total expected established BGP sessions used
            by precheck/postcheck health checks.
        profile: `BgpPlusPlusProfile` enum value; enables the IBGP-PNH
            precheck when the OpenR variant is selected.

    Returns:
        A `Playbook` named `bgp_instability_attribute_churn` with standard
        BGP++ prechecks/postchecks, core-dumps snapshot check, standard
        periodic tasks (CPU/memory @ 9 GiB, non-terminating), and one
        attribute-churn stage over prefix indices 0..500.
    """
    instability_checks = get_profile_checks(
        CheckProfile.CHURN_STORM,
        ProfileContext(
            peergroup_ibgp_v6=peergroup_ibgp_v6,
            peergroup_ibgp_v4=peergroup_ibgp_v4,
            expected_established_sessions=total_session_count,
            check_ibgp_pnh=(profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R),
            exclude_bgp_mon=exclude_bgp_mon,
        ),
    )
    return Playbook(
        name="bgp_instability_attribute_churn",
        setup_steps=create_bgp_instability_setup_steps(
            device_name=device_name,
        ),
        prechecks=instability_checks.prechecks,
        postchecks=instability_checks.postchecks,
        snapshot_checks=instability_checks.snapshot_checks,
        periodic_tasks=create_standard_periodic_tasks(
            device_name=device_name,
            memory_threshold=Gigabyte.GIG_9.value,
            cpu_util_terminate_on_error=False,
            memory_terminate_on_error=False,
        ),
        stages=[
            create_attribute_churn_stage(
                prefix_pool_regex=".*",
                prefix_pool_regex_as_path="PREFIX_POOL_IBGP_IPV6_PLANE_1_REMOTE_EB_DRAIN",
                prefix_start_index=0,
                prefix_end_index=500,
                churn_time=60,
                local_pref_iters=5,
                med_iters=5,
                origin_iters=5,
                as_path_iters=5,
                med_value=-1,
                as_path_length_max=10,
            )
        ],
    )


def create_bgp_ebb_route_storm_playbook(
    device_name: str,
    peergroup_ibgp_v6: str,
    peergroup_ibgp_v4: str,
    total_session_count: int,
    ixia_interface_mimic_ibgp: str,
    profile,  # BgpPlusPlusProfile
    exclude_bgp_mon: bool = True,
) -> Playbook:
    """Build the BAG010_ASH6 BGP instability + route storm Playbook.

    Drives the BGP++ peer set through a route-storm advertise/withdraw
    cycle on the IBGP plane 1 traffic generator interface, then reverts
    and waits for convergence. Used by the BAG010_ASH6 BGP++ instability
    TestConfigs to verify bgpcpp survives sustained route churn (and that
    the constant-attribute-storage path holds AS path / pool size
    invariants set in `rib_fib_json_params`).

    Args:
        device_name: DUT hostname (used for setup steps and periodic tasks).
        peergroup_ibgp_v6: IBGP IPv6 peer-group name (precheck assertion).
        peergroup_ibgp_v4: IBGP IPv4 peer-group name (precheck assertion).
        total_session_count: Total expected established BGP sessions.
        ixia_interface_mimic_ibgp: IXIA logical interface name that mimics
            the IBGP peers; route-storm and revert stages target this.
        profile: `BgpPlusPlusProfile` enum value; enables IBGP-PNH precheck
            when the OpenR variant is selected.

    Returns:
        A `Playbook` named `bgp_instability_route_storm` with standard
        BGP++ prechecks/postchecks (postcheck enforces 255 AS path length
        and pool size 10), core-dumps snapshot check, standard periodic
        tasks (memory @ 10 GiB), a route-storm stage (3600s advertise/
        withdraw on the IBGP plane 1 pool), a revert stage, and a 120s
        convergence-wait stage.
    """
    instability_checks = get_profile_checks(
        CheckProfile.CHURN_STORM,
        ProfileContext(
            peergroup_ibgp_v6=peergroup_ibgp_v6,
            peergroup_ibgp_v4=peergroup_ibgp_v4,
            expected_established_sessions=total_session_count,
            check_ibgp_pnh=(profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R),
            exclude_bgp_mon=exclude_bgp_mon,
            rib_fib_json_params={
                "debug_route_attributes": True,
                "expected_as_path_length": 255,
                "expected_pool_size": 10,
            },
        ),
    )
    return Playbook(
        name="bgp_instability_route_storm",
        setup_steps=create_bgp_instability_setup_steps(
            device_name=device_name,
        ),
        prechecks=instability_checks.prechecks,
        postchecks=instability_checks.postchecks,
        snapshot_checks=instability_checks.snapshot_checks,
        periodic_tasks=create_standard_periodic_tasks(
            device_name=device_name,
            memory_threshold=Gigabyte.GIG_10.value,
            cpu_util_terminate_on_error=False,
            memory_terminate_on_error=False,
        ),
        stages=[
            create_route_storm_stage(
                device_name=device_name,
                interface=ixia_interface_mimic_ibgp,
                prefix_pool_regex=".*IBGP.*PLANE_1.*",
                prefix_start_index=0,
                prefix_end_index=500,
                device_group_regex=".*IBGP.*PLANE_1.*",
                test_duration_seconds=3600,
                advertise_time=30,
                withdraw_time=30,
            ),
            create_revert_route_storm_stage(
                device_name=device_name,
                interface=ixia_interface_mimic_ibgp,
                device_group_regex=".*IBGP.*PLANE_1.*",
            ),
            create_steps_stage(
                steps=[
                    create_longevity_step(
                        duration=120,
                        description="Wait for BGP convergence after revert",
                    ),
                ]
            ),
        ],
    )


def create_bgp_ebb_igp_pnh_metric_oscillation_playbook(
    device_name: str,
    peergroup_ibgp_v6: str,
    peergroup_ibgp_v4: str,
    local_link: t.Dict[str, t.Any],
    other_link: t.Dict[str, t.Any],
    expected_established_sessions: int = 0,
    profile: BgpPlusPlusProfile = BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
    cpu_baseline: float = 8.0,
    memory_threshold: int = Gigabyte.GIG_5.value,
    cpu_util_terminate_on_error: bool = False,
    memory_terminate_on_error: bool = False,
    start_ipv4s: t.Optional[t.List[str]] = None,
    start_ipv6s: t.Optional[t.List[str]] = None,
    count: int = 63,
    step_size: int = 2,
    duration: int = 2400,
    frequency: int = 30,
    precheck_thresholds: t.Optional[HardwareCapacityThresholds] = None,
    postcheck_thresholds: t.Optional[HardwareCapacityThresholds] = None,
    expected_peer_identity: t.Optional[t.Dict[str, str]] = None,
    exclude_bgp_mon: bool = True,
) -> Playbook:
    """
    Create a BGP IGP instability PNH metric oscillation test playbook.

    This playbook tests BGP behavior during IGP metric oscillations by:
    1. Setting up BGP instability prerequisites
    2. Running standard prechecks
    3. Performing Open/R metric oscillations while tracking BGP withdrawals
    4. Verifying no withdrawals, then running session-stability postchecks

    Args:
        device_name: Name of the device under test
        peergroup_ibgp_v6: IPv6 iBGP peer group name for session checks
        peergroup_ibgp_v4: IPv4 iBGP peer group name for session checks
        profile: BGP++ profile (with or without Open/R)
        memory_threshold: Memory threshold in bytes (default: 5GB)
        cpu_util_terminate_on_error: Terminate test on CPU threshold breach
        memory_terminate_on_error: Terminate test on memory threshold breach
        start_ipv4s: List of starting IPv4 addresses for Open/R routes
        start_ipv6s: List of starting IPv6 addresses for Open/R routes
        local_link: Local link dict for Open/R route configuration (device-specific)
        other_link: Other link dict for Open/R route configuration (device-specific)
        expected_established_sessions: Expected number of established BGP sessions
        count: Number of routes for metric oscillation (default: 63)
        step_size: Step size for route generation (default: 2)
        duration: Duration of metric oscillation in seconds (default: 2400)
        frequency: Frequency of oscillation in seconds (default: 30)
        precheck_thresholds: Custom precheck thresholds (uses defaults if None)
        postcheck_thresholds: Custom postcheck thresholds (uses defaults if None)

    Returns:
        Playbook configured for BGP IGP instability PNH metric oscillation testing
    """
    if start_ipv4s is None:
        start_ipv4s = DEFAULT_OPENR_START_IPV4S

    if start_ipv6s is None:
        start_ipv6s = DEFAULT_OPENR_START_IPV6S

    if precheck_thresholds is None:
        precheck_thresholds = get_precheck_thresholds()

    if postcheck_thresholds is None:
        postcheck_thresholds = get_postcheck_thresholds()

    igp_checks = get_profile_checks(
        CheckProfile.IGP_INSTABILITY,
        ProfileContext(
            peergroup_ibgp_v6=peergroup_ibgp_v6,
            peergroup_ibgp_v4=peergroup_ibgp_v4,
            precheck_thresholds=precheck_thresholds,
            postcheck_thresholds=postcheck_thresholds,
            expected_established_sessions=expected_established_sessions,
            cpu_baseline=cpu_baseline,
            check_ibgp_pnh=(profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R),
            expected_peer_identity=expected_peer_identity,
            exclude_bgp_mon=exclude_bgp_mon,
        ),
    )
    return Playbook(
        name="bgp_igp_instability_pnh_metric_oscillation_playbook",
        setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
        prechecks=igp_checks.prechecks,
        postchecks=igp_checks.postchecks,
        snapshot_checks=igp_checks.snapshot_checks,
        periodic_tasks=create_standard_periodic_tasks(
            device_name=device_name,
            memory_threshold=memory_threshold,
            cpu_util_terminate_on_error=cpu_util_terminate_on_error,
            memory_terminate_on_error=memory_terminate_on_error,
        ),
        stages=[
            create_steps_stage(
                steps=[
                    create_snapshot_bgp_withdraw_sent_counter_step(
                        hostname=device_name,
                        snapshot_key="igp_pnh_metric_oscillation",
                    ),
                    create_openr_route_action_step(
                        device_name=device_name,
                        start_ipv4s=start_ipv4s,
                        start_ipv6s=start_ipv6s,
                        local_link=local_link,
                        other_link=other_link,
                        action=OpenRRouteAction.METRIC_OSCILLATION.value,
                        count=count,
                        step=step_size,
                        duration=duration,
                        frequency=frequency,
                        description="Perform metric oscillation using Open/R configuration",
                    ),
                    create_verify_bgp_withdraw_send_quiet_step(
                        hostname=device_name,
                        snapshot_key="igp_pnh_metric_oscillation",
                    ),
                ],
            )
        ],
        cleanup_steps=[
            create_openr_route_action_step(
                device_name=device_name,
                start_ipv4s=start_ipv4s,
                start_ipv6s=start_ipv6s,
                local_link=local_link,
                other_link=other_link,
                action=OpenRRouteAction.INJECT.value,
                count=count,
                step=step_size,
                description="Re-inject Open/R routes to restore original metrics",
            ),
        ],
    )


def create_bgp_ebb_route_registry_runtime_update_playbook(
    device_name: str,
    peergroup_ibgp_v6: str,
    peergroup_ibgp_v4: str,
    expected_established_sessions: int = 0,
    profile: BgpPlusPlusProfile = BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
    cpu_baseline: float = 6.0,
    memory_threshold: int = Gigabyte.GIG_5.value,
    cpu_util_terminate_on_error: bool = False,
    memory_terminate_on_error: bool = False,
    ebgp_peer_description: str = "EBGP",
    prefix_pool_regex: str = ".*EBGP.*",
    soak_time_seconds: int = 120,
    expected_route_count: int = 650,
    precheck_thresholds: t.Optional[HardwareCapacityThresholds] = None,
    postcheck_thresholds: t.Optional[HardwareCapacityThresholds] = None,
    exclude_bgp_mon: bool = True,
) -> Playbook:
    """
    Create a BGP route registry prefix-list runtime update test playbook.

    This playbook tests BGP's handling of prefix-list runtime updates by:
    1. Setting up route registry prefix-list prerequisites
    2. Running standard prechecks + route count verification
    3. Dynamically adding/removing prefixes from prefix-lists via setRouteFilterPolicy
    4. Verifying route counts change accordingly without BGP restart

    Args:
        device_name: Name of the device under test
        peergroup_ibgp_v6: IPv6 iBGP peer group name for session checks
        peergroup_ibgp_v4: IPv4 iBGP peer group name for session checks
        expected_established_sessions: Expected number of established BGP sessions
        profile: BGP++ profile (with or without Open/R)
        cpu_baseline: CPU baseline threshold for prechecks (default: 6.0)
        memory_threshold: Memory threshold in bytes (default: 5GB)
        cpu_util_terminate_on_error: Terminate test on CPU threshold breach
        memory_terminate_on_error: Terminate test on memory threshold breach
        ebgp_peer_description: Description substring to match EBGP peers (default: "EBGP")
        prefix_pool_regex: Regex to match prefix pool names (default: ".*EBGP.*")
        soak_time_seconds: Soak duration for BGP stability (default: 120s)
        expected_route_count: Expected baseline eBGP route count (default: 650)
        precheck_thresholds: Custom precheck thresholds (uses defaults if None)
        postcheck_thresholds: Custom postcheck thresholds (uses defaults if None)

    Returns:
        Playbook configured for BGP route registry prefix-list runtime update testing
    """
    if precheck_thresholds is None:
        precheck_thresholds = get_precheck_thresholds()

    if postcheck_thresholds is None:
        postcheck_thresholds = get_postcheck_thresholds()

    runtime_update_checks = get_profile_checks(
        CheckProfile.RUNTIME_UPDATE,
        ProfileContext(
            peergroup_ibgp_v6=peergroup_ibgp_v6,
            peergroup_ibgp_v4=peergroup_ibgp_v4,
            precheck_thresholds=precheck_thresholds,
            postcheck_thresholds=postcheck_thresholds,
            cpu_baseline=cpu_baseline,
            expected_established_sessions=expected_established_sessions,
            check_ibgp_pnh=(profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R),
            exclude_bgp_mon=exclude_bgp_mon,
            route_count_expected=expected_route_count,
        ),
    )
    return Playbook(
        name="bgp_route_registry_prefix_list_runtime_update_playbook",
        setup_steps=create_route_registry_prefix_list_setup_steps(
            device_name=device_name
        ),
        prechecks=runtime_update_checks.prechecks,
        postchecks=runtime_update_checks.postchecks,
        snapshot_checks=runtime_update_checks.snapshot_checks,
        periodic_tasks=create_standard_periodic_tasks(
            device_name=device_name,
            memory_threshold=memory_threshold,
            cpu_util_terminate_on_error=cpu_util_terminate_on_error,
            memory_terminate_on_error=memory_terminate_on_error,
        ),
        stages=[
            create_route_registry_runtime_update_stage(
                device_name=device_name,
                ebgp_peer_description=ebgp_peer_description,
                prefix_pool_regex=prefix_pool_regex,
                soak_time_seconds=soak_time_seconds,
            )
        ],
        cleanup_steps=[
            create_advertise_withdraw_prefixes_step(
                device_name=device_name,
                advertise=True,
                prefix_pool_regex=prefix_pool_regex,
                prefix_start_index=0,
                prefix_end_index=100,
                description="Cleanup: Re-advertise 100 test prefixes (0-100) so next playbook has full prefix pool",
            ),
            create_set_route_filter_step(
                device_name=device_name,
                config_path="taac/test_bgp_policies/ebb_route_registry_prefix_list_750.json",
                description="Cleanup: Restore permissive route filter policy (750.json) so next playbook receives all prefixes",
            ),
        ],
    )


def create_bgp_ebb_multipath_group_oscillation_playbook(
    device_name: str,
    peergroup_ibgp_v6: str,
    peergroup_ibgp_v4: str,
    expected_established_sessions: int = 0,
    profile: BgpPlusPlusProfile = BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
    cpu_baseline: float = 8.0,
    memory_threshold: int = Gigabyte.GIG_5.value,
    cpu_util_terminate_on_error: bool = False,
    memory_terminate_on_error: bool = False,
    ipv4_peer_regex: str = ".*IPV4_EBGP$",
    ipv6_peer_regex: str = ".*IPV6_EBGP$",
    ipv4_session_count: int = 140,
    ipv6_session_count: int = 140,
    test_duration_seconds: int = 1800,
    oscillation_interval_seconds: int = 280,
    min_peers_to_stop: int = 1,
    max_peers_to_stop: int = 11,
    expected_min_baseline_width: t.Optional[int] = None,
    expected_max_baseline_width: t.Optional[int] = None,
    min_multipath_width: t.Optional[int] = None,
    precheck_thresholds: t.Optional[HardwareCapacityThresholds] = None,
    postcheck_thresholds: t.Optional[HardwareCapacityThresholds] = None,
    exclude_bgp_mon: bool = True,
) -> Playbook:
    """
    Create a BGP multipath group oscillation test playbook.

    Test Case 5.2.4: BGP Instability - Multipath Group Oscillations

    This playbook tests BGP stability during multipath group oscillations by:
    1. Setting up BGP instability prerequisites
    2. Running standard prechecks
    3. Measuring the live multipath group width as the baseline
    4. Fluctuating BGP multipath groups by stopping/starting eBGP sessions
    5. Verifying multipath groups reduce/restore relative to the measured baseline
    6. Running standard postchecks (no convergence check)

    Args:
        device_name: Name of the device under test
        peergroup_ibgp_v6: IPv6 iBGP peer group name for session checks
        peergroup_ibgp_v4: IPv4 iBGP peer group name for session checks
        expected_established_sessions: Expected number of established BGP sessions
        profile: BGP++ profile (with or without Open/R)
        cpu_baseline: CPU baseline threshold for prechecks (default: 8.0)
        memory_threshold: Memory threshold in bytes (default: 5GB)
        cpu_util_terminate_on_error: Terminate test on CPU threshold breach
        memory_terminate_on_error: Terminate test on memory threshold breach
        ipv4_peer_regex: Regex to match IPv4 eBGP peers (default: ".*IPV4_EBGP$")
        ipv6_peer_regex: Regex to match IPv6 eBGP peers (default: ".*IPV6_EBGP$")
        ipv4_session_count: Number of IPv4 eBGP sessions on the IXIA side
            (default: 140). Used only for peer-stop indexing — NOT assumed to
            equal the DUT-side multipath group width, which is measured live.
        ipv6_session_count: Number of IPv6 eBGP sessions on the IXIA side.
        test_duration_seconds: Total oscillation test duration (default: 1800s)
        oscillation_interval_seconds: Interval between oscillations (default: 280s)
        min_peers_to_stop: Minimum peers to stop per cycle (default: 1)
        max_peers_to_stop: Maximum peers to stop per cycle (default: 11)
        expected_min_baseline_width: Optional sanity lower bound on the measured
            multipath width. Discovery fails if the measurement is below.
        expected_max_baseline_width: Optional sanity upper bound.
        min_multipath_width: Floor for distribution scan (default None, delegates downstream).
        precheck_thresholds: Custom precheck thresholds (uses defaults if None)
        postcheck_thresholds: Custom postcheck thresholds (uses defaults if None)

    Returns:
        Playbook configured for BGP multipath group oscillation testing
    """
    if precheck_thresholds is None:
        precheck_thresholds = get_precheck_thresholds()

    if postcheck_thresholds is None:
        postcheck_thresholds = get_postcheck_thresholds()

    osc_checks = get_profile_checks(
        CheckProfile.OSCILLATION,
        ProfileContext(
            peergroup_ibgp_v6=peergroup_ibgp_v6,
            peergroup_ibgp_v4=peergroup_ibgp_v4,
            precheck_thresholds=precheck_thresholds,
            postcheck_thresholds=postcheck_thresholds,
            expected_established_sessions=expected_established_sessions,
            cpu_baseline=cpu_baseline,
            check_ibgp_pnh=(profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R),
            exclude_bgp_mon=exclude_bgp_mon,
            snapshot_skip_flap=True,
            snapshot_skip_uptime=True,
        ),
    )
    return Playbook(
        name="bgp_multipath_group_oscillation_playbook",
        setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
        prechecks=osc_checks.prechecks,
        postchecks=osc_checks.postchecks,
        snapshot_checks=osc_checks.snapshot_checks,
        periodic_tasks=create_standard_periodic_tasks(
            device_name=device_name,
            memory_threshold=memory_threshold,
            cpu_util_terminate_on_error=cpu_util_terminate_on_error,
            memory_terminate_on_error=memory_terminate_on_error,
        ),
        stages=[
            create_multipath_group_oscillation_stage(
                ipv4_peer_regex=ipv4_peer_regex,
                ipv6_peer_regex=ipv6_peer_regex,
                ipv4_session_count=ipv4_session_count,
                ipv6_session_count=ipv6_session_count,
                test_duration_seconds=test_duration_seconds,
                oscillation_interval_seconds=oscillation_interval_seconds,
                min_peers_to_stop=min_peers_to_stop,
                max_peers_to_stop=max_peers_to_stop,
                expected_min_baseline_width=expected_min_baseline_width,
                expected_max_baseline_width=expected_max_baseline_width,
                min_multipath_width=min_multipath_width,
            ),
        ],
    )


def create_bgp_ebb_fauu_drain_undrain_playbook(
    device_name: str,
    peergroup_ibgp_v6: str,
    peergroup_ibgp_v4: str,
    expected_established_sessions: int = 0,
    profile: BgpPlusPlusProfile = BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
    memory_threshold: int = Gigabyte.GIG_5.value,
    cpu_util_terminate_on_error: bool = False,
    memory_terminate_on_error: bool = False,
    prefix_pool_regex: str = ".*EBGP.*",
    prefix_end_index: int = 96,
    tcp_dump_capture_interface_ebgp: str = "",
    tcp_dump_capture_interface_bgpmon: str = "",
    tcp_dump_capture_interface_ibgp: str = "",
    soak_time_seconds: int = 300,
    exclude_bgp_mon: bool = True,
) -> Playbook:
    """
    Create a BGP FAUU drain/undrain test playbook.

    This playbook tests BGP convergence during FAUU (FA Drain/Undrain)
    drain/undrain operations with IXIA-side attribute changes (local_pref + origin).
    Convergence limit is 5 minutes (hardcoded in stage definition).

    Args:
        device_name: Name of the device under test
        peergroup_ibgp_v6: IPv6 iBGP peer group name for session checks
        peergroup_ibgp_v4: IPv4 iBGP peer group name for session checks
        expected_established_sessions: Expected number of established BGP sessions
        profile: BGP++ profile (with or without Open/R)
        memory_threshold: Memory threshold in bytes (default: 5GB)
        cpu_util_terminate_on_error: Terminate test on CPU threshold breach
        memory_terminate_on_error: Terminate test on memory threshold breach
        prefix_pool_regex: Regex to match eBGP prefix pools (default: ".*EBGP.*")
        prefix_end_index: Ending prefix index (default: 96)
        tcp_dump_capture_interface_ebgp: eBGP interface for PCAP capture
        tcp_dump_capture_interface_bgpmon: BGP MON interface for PCAP capture
        tcp_dump_capture_interface_ibgp: iBGP interface for PCAP capture
        soak_time_seconds: Soak time in seconds (default: 300)

    Returns:
        Playbook configured for BGP FAUU drain/undrain testing
    """
    drain_checks = get_profile_checks(
        CheckProfile.DRAIN_UNDRAIN,
        ProfileContext(
            peergroup_ibgp_v6=peergroup_ibgp_v6,
            peergroup_ibgp_v4=peergroup_ibgp_v4,
            expected_established_sessions=expected_established_sessions,
            exclude_bgp_mon=exclude_bgp_mon,
            check_ibgp_pnh=(profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R),
        ),
    )
    return Playbook(
        name="bgp_fauu_drain_undrain_playbook",
        setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
        prechecks=drain_checks.prechecks,
        postchecks=drain_checks.postchecks,
        snapshot_checks=drain_checks.snapshot_checks,
        periodic_tasks=create_standard_periodic_tasks(
            device_name=device_name,
            memory_threshold=memory_threshold,
            cpu_util_terminate_on_error=cpu_util_terminate_on_error,
            memory_terminate_on_error=memory_terminate_on_error,
        ),
        stages=[
            create_fauu_drain_undrain_stage(
                device_name=device_name,
                prefix_pool_regex=prefix_pool_regex,
                prefix_end_index=prefix_end_index,
                tcp_dump_capture_interface_ebgp=tcp_dump_capture_interface_ebgp,
                tcp_dump_capture_interface_bgpmon=tcp_dump_capture_interface_bgpmon,
                tcp_dump_capture_interface_ibgp=tcp_dump_capture_interface_ibgp,
                soak_time_seconds=soak_time_seconds,
            )
        ],
    )


def create_bgp_ebb_plane_drain_undrain_playbook(
    device_name: str,
    peergroup_ibgp_v6: str,
    peergroup_ibgp_v4: str,
    expected_established_sessions: int = 0,
    profile: BgpPlusPlusProfile = BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
    memory_threshold: int = Gigabyte.GIG_5.value,
    cpu_util_terminate_on_error: bool = False,
    memory_terminate_on_error: bool = False,
    prefix_pool_regex: str = ".*IBGP.*PLANE_.*",
    tcp_dump_capture_interface_ebgp: str = "",
    tcp_dump_capture_interface_bgpmon: str = "",
    tcp_dump_capture_interface_ibgp: str = "",
    soak_time_seconds: int = 1200,
    exclude_bgp_mon: bool = True,
) -> Playbook:
    """
    Create a BGP plane drain/undrain test playbook.

    This playbook tests BGP convergence during plane drain/undrain operations
    with concurrent IXIA attribute changes and DUT policy changes.
    Convergence limit is 10 minutes (hardcoded in stage definition).

    Args:
        device_name: Name of the device under test
        peergroup_ibgp_v6: IPv6 iBGP peer group name for session checks
        peergroup_ibgp_v4: IPv4 iBGP peer group name for session checks
        expected_established_sessions: Expected number of established BGP sessions
        profile: BGP++ profile (with or without Open/R)
        memory_threshold: Memory threshold in bytes (default: 5GB)
        cpu_util_terminate_on_error: Terminate test on CPU threshold breach
        memory_terminate_on_error: Terminate test on memory threshold breach
        prefix_pool_regex: Regex to match iBGP prefix pools (default: ".*IBGP.*PLANE_.*")
        tcp_dump_capture_interface_ebgp: eBGP interface for PCAP capture
        tcp_dump_capture_interface_bgpmon: BGP MON interface for PCAP capture
        tcp_dump_capture_interface_ibgp: iBGP interface for PCAP capture
        soak_time_seconds: Soak time in seconds (default: 1200)

    Returns:
        Playbook configured for BGP plane drain/undrain testing
    """
    drain_checks = get_profile_checks(
        CheckProfile.DRAIN_UNDRAIN,
        ProfileContext(
            peergroup_ibgp_v6=peergroup_ibgp_v6,
            peergroup_ibgp_v4=peergroup_ibgp_v4,
            expected_established_sessions=expected_established_sessions,
            exclude_bgp_mon=exclude_bgp_mon,
            check_ibgp_pnh=(profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R),
        ),
    )
    return Playbook(
        name="bgp_plane_drain_undrain_playbook",
        setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
        prechecks=drain_checks.prechecks,
        postchecks=drain_checks.postchecks,
        snapshot_checks=drain_checks.snapshot_checks,
        periodic_tasks=create_standard_periodic_tasks(
            device_name=device_name,
            memory_threshold=memory_threshold,
            cpu_util_terminate_on_error=cpu_util_terminate_on_error,
            memory_terminate_on_error=memory_terminate_on_error,
        ),
        stages=[
            *create_plane_drain_undrain_stage(
                device_name=device_name,
                prefix_pool_regex=prefix_pool_regex,
                tcp_dump_capture_interface_bgpmon=tcp_dump_capture_interface_bgpmon,
                tcp_dump_capture_interface_ebgp=tcp_dump_capture_interface_ebgp,
                tcp_dump_capture_interface_ibgp=tcp_dump_capture_interface_ibgp,
                soak_time_seconds=soak_time_seconds,
            )
        ],
    )


def create_bgp_ebb_longevity_playbook(
    device_name: str,
    duration: int = 86400,
    community_churn_frequency: int = 60,
    postcheck_thresholds: t.Optional[HardwareCapacityThresholds] = None,
    exclude_bgp_mon: bool = True,
) -> Playbook:
    """
    Create a BGP longevity soak playbook.

    Runs a long-duration soak with IN-STAGE community churn (add/remove every
    ``community_churn_frequency`` seconds, each cycle returning the RIB to
    baseline) followed by a quiesce window, after which the SOAK_NO_PRECHECK
    post-checks run on the quiesced device. Churn is in-stage (not background
    ``periodic_tasks``) so it ends before the post-checks rather than racing
    them.

    Args:
        device_name: Target device hostname
        duration: Soak duration in seconds (default: 86400 = 24 hours)
        community_churn_frequency: Seconds between community add/remove cycles
        postcheck_thresholds: Hardware capacity thresholds for postchecks
        exclude_bgp_mon: Exclude BGP MON peers from session / snapshot checks

    Returns:
        Playbook configured for BGP longevity soak testing
    """
    # SOAK_NO_PRECHECK has no prechecks (the prechecks field is left unset).
    soak_checks = get_profile_checks(
        CheckProfile.SOAK_NO_PRECHECK,
        ProfileContext(
            postcheck_thresholds=postcheck_thresholds,
            check_bgp_convergence=False,
            exclude_bgp_mon=exclude_bgp_mon,
        ),
    )
    return Playbook(
        name="bgp_longevity_playbook",
        setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
        postchecks=soak_checks.postchecks,
        snapshot_checks=soak_checks.snapshot_checks,
        stages=[
            create_longevity_churn_stage(
                test_duration_seconds=duration,
                churn_interval_seconds=community_churn_frequency,
            )
        ],
    )


def create_bgp_ebb_ebgp_route_oscillations_playbook(
    device_name: str,
    peergroup_ibgp_v6: str,
    peergroup_ibgp_v4: str,
    expected_established_sessions: int = 0,
    profile: BgpPlusPlusProfile = BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
    cpu_baseline: float = 8.0,
    memory_threshold: int = Gigabyte.GIG_5.value,
    cpu_util_terminate_on_error: bool = False,
    memory_terminate_on_error: bool = False,
    prefix_pool_regex: str = ".*EBGP.*",
    prefix_start_index: int = 0,
    prefix_end_index: int = 500,
    precheck_thresholds: t.Optional[HardwareCapacityThresholds] = None,
    postcheck_thresholds: t.Optional[HardwareCapacityThresholds] = None,
    expected_peer_identity: t.Optional[t.Dict[str, str]] = None,
    exclude_bgp_mon: bool = True,
) -> Playbook:
    """
    Create a BGP eBGP route oscillations test playbook.

    This playbook tests BGP stability during eBGP route advertisement/withdrawal
    oscillations by repeatedly advertising and withdrawing prefixes from eBGP peers.
    """
    if precheck_thresholds is None:
        precheck_thresholds = get_precheck_thresholds()

    if postcheck_thresholds is None:
        postcheck_thresholds = get_postcheck_thresholds()

    osc_checks = get_profile_checks(
        CheckProfile.OSCILLATION,
        ProfileContext(
            peergroup_ibgp_v6=peergroup_ibgp_v6,
            peergroup_ibgp_v4=peergroup_ibgp_v4,
            precheck_thresholds=precheck_thresholds,
            postcheck_thresholds=postcheck_thresholds,
            expected_established_sessions=expected_established_sessions,
            cpu_baseline=cpu_baseline,
            check_ibgp_pnh=(profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R),
            expected_peer_identity=expected_peer_identity,
            exclude_bgp_mon=exclude_bgp_mon,
            snapshot_skip_uptime=True,
        ),
    )
    return Playbook(
        name="bgp_ebgp_route_oscillations",
        setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
        prechecks=osc_checks.prechecks,
        postchecks=osc_checks.postchecks,
        snapshot_checks=osc_checks.snapshot_checks,
        periodic_tasks=create_standard_periodic_tasks(
            device_name=device_name,
            memory_threshold=memory_threshold,
            cpu_util_terminate_on_error=cpu_util_terminate_on_error,
            memory_terminate_on_error=memory_terminate_on_error,
        ),
        stages=[
            create_route_oscillations_stage(
                device_name=device_name,
                prefix_pool_regex=prefix_pool_regex,
                prefix_start_index=prefix_start_index,
                prefix_end_index=prefix_end_index,
            )
        ],
    )


def create_bgp_ebb_ibgp_route_oscillations_playbook(
    device_name: str,
    peergroup_ibgp_v6: str,
    peergroup_ibgp_v4: str,
    expected_established_sessions: int = 0,
    profile: BgpPlusPlusProfile = BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
    cpu_baseline: float = 8.0,
    memory_threshold: int = Gigabyte.GIG_5.value,
    cpu_util_terminate_on_error: bool = False,
    memory_terminate_on_error: bool = False,
    prefix_pool_regex: str = ".*IBGP.*",
    prefix_start_index: int = 0,
    prefix_end_index: int = 100,
    precheck_thresholds: t.Optional[HardwareCapacityThresholds] = None,
    postcheck_thresholds: t.Optional[HardwareCapacityThresholds] = None,
    expected_peer_identity: t.Optional[t.Dict[str, str]] = None,
    exclude_bgp_mon: bool = True,
) -> Playbook:
    """
    Create a BGP iBGP route oscillations test playbook.

    This playbook tests BGP stability during iBGP route advertisement/withdrawal
    oscillations by repeatedly advertising and withdrawing prefixes from iBGP peers.
    """
    if precheck_thresholds is None:
        precheck_thresholds = get_precheck_thresholds()

    if postcheck_thresholds is None:
        postcheck_thresholds = get_postcheck_thresholds()

    osc_checks = get_profile_checks(
        CheckProfile.OSCILLATION,
        ProfileContext(
            peergroup_ibgp_v6=peergroup_ibgp_v6,
            peergroup_ibgp_v4=peergroup_ibgp_v4,
            precheck_thresholds=precheck_thresholds,
            postcheck_thresholds=postcheck_thresholds,
            expected_established_sessions=expected_established_sessions,
            cpu_baseline=cpu_baseline,
            check_ibgp_pnh=(profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R),
            expected_peer_identity=expected_peer_identity,
            exclude_bgp_mon=exclude_bgp_mon,
        ),
    )
    return Playbook(
        name="bgp_ibgp_route_oscillations",
        setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
        prechecks=osc_checks.prechecks,
        postchecks=osc_checks.postchecks,
        snapshot_checks=osc_checks.snapshot_checks,
        periodic_tasks=create_standard_periodic_tasks(
            device_name=device_name,
            memory_threshold=memory_threshold,
            cpu_util_terminate_on_error=cpu_util_terminate_on_error,
            memory_terminate_on_error=memory_terminate_on_error,
        ),
        stages=[
            create_route_oscillations_stage(
                device_name=device_name,
                prefix_pool_regex=prefix_pool_regex,
                prefix_start_index=prefix_start_index,
                prefix_end_index=prefix_end_index,
            )
        ],
    )


def create_bgp_ebb_igp_instability_unresolvable_pnhs_playbook(
    device_name: str,
    peergroup_ibgp_v6: str,
    peergroup_ibgp_v4: str,
    local_link: t.Dict[str, t.Any],
    other_link: t.Dict[str, t.Any],
    expected_established_sessions: int = 0,
    profile: BgpPlusPlusProfile = BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
    cpu_baseline: float = 8.0,
    memory_threshold: int = Gigabyte.GIG_5.value,
    cpu_util_terminate_on_error: bool = False,
    memory_terminate_on_error: bool = False,
    start_ipv4s: t.Optional[t.List[str]] = None,
    start_ipv6s: t.Optional[t.List[str]] = None,
    count: int = 63,
    step_size: int = 2,
    precheck_thresholds: t.Optional[HardwareCapacityThresholds] = None,
    postcheck_thresholds: t.Optional[HardwareCapacityThresholds] = None,
    expected_peer_identity: t.Optional[t.Dict[str, str]] = None,
    exclude_bgp_mon: bool = True,
    tcp_dump_capture_interface: t.Optional[str] = None,
) -> Playbook:
    """
    Create a BGP IGP instability unresolvable PNHs test playbook.

    This playbook tests BGP behavior when protocol next-hops become unresolvable by:
    1. Setting up BGP instability prerequisites
    2. Running standard prechecks
    3. Executing the unresolvable PNHs stage (deleting Open/R routes)
    4. Validating BGP++ UPDATE sends, no withdrawals, and sustained stability
    5. Cleanup: re-injecting deleted routes to restore original state

    ``tcp_dump_capture_interface`` is retained as an ignored compatibility
    parameter while callers migrate to the counter-based validation.
    """
    if start_ipv4s is None:
        start_ipv4s = [DEFAULT_OPENR_START_IPV4S[0]]

    if start_ipv6s is None:
        start_ipv6s = [DEFAULT_OPENR_START_IPV6S[0]]

    cleanup_start_ipv4s = list(
        dict.fromkeys([*DEFAULT_OPENR_START_IPV4S, *start_ipv4s])
    )
    cleanup_start_ipv6s = list(
        dict.fromkeys([*DEFAULT_OPENR_START_IPV6S, *start_ipv6s])
    )

    if precheck_thresholds is None:
        precheck_thresholds = get_precheck_thresholds()

    if postcheck_thresholds is None:
        postcheck_thresholds = get_postcheck_thresholds()

    igp_checks = get_profile_checks(
        CheckProfile.IGP_INSTABILITY,
        ProfileContext(
            peergroup_ibgp_v6=peergroup_ibgp_v6,
            peergroup_ibgp_v4=peergroup_ibgp_v4,
            precheck_thresholds=precheck_thresholds,
            postcheck_thresholds=postcheck_thresholds,
            expected_established_sessions=expected_established_sessions,
            cpu_baseline=cpu_baseline,
            check_ibgp_pnh=(profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R),
            expected_peer_identity=expected_peer_identity,
            exclude_bgp_mon=exclude_bgp_mon,
        ),
    )
    return Playbook(
        name="bgp_igp_instability_unresolvable_pnhs_playbook",
        setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
        prechecks=igp_checks.prechecks,
        postchecks=igp_checks.postchecks,
        snapshot_checks=igp_checks.snapshot_checks,
        periodic_tasks=create_standard_periodic_tasks(
            device_name=device_name,
            memory_threshold=memory_threshold,
            cpu_util_terminate_on_error=cpu_util_terminate_on_error,
            memory_terminate_on_error=memory_terminate_on_error,
        ),
        stages=[
            create_bgp_igp_instability_unresolvable_pnhs_stage(
                device_name=device_name,
                start_ipv4s=start_ipv4s,
                start_ipv6s=start_ipv6s,
            )
        ],
        cleanup_steps=[
            create_openr_route_action_step(
                device_name=device_name,
                start_ipv4s=cleanup_start_ipv4s,
                start_ipv6s=cleanup_start_ipv6s,
                local_link=local_link,
                other_link=other_link,
                action=OpenRRouteAction.INJECT.value,
                count=count,
                step=step_size,
                description="Re-inject Open/R routes to restore deleted routes",
            ),
        ],
    )


def create_bgp_ebb_ebgp_session_oscillations_playbook(
    device_name: str,
    peergroup_ibgp_v6: str,
    peergroup_ibgp_v4: str,
    ipv4_session_count: int,
    ipv6_session_count: int,
    expected_established_sessions: int = 0,
    profile: BgpPlusPlusProfile = BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
    cpu_baseline: float = 8.0,
    memory_threshold: int = Gigabyte.GIG_5.value,
    cpu_util_terminate_on_error: bool = False,
    memory_terminate_on_error: bool = False,
    ipv4_peer_regex: str = ".*IPV4_EBGP$",
    ipv6_peer_regex: str = ".*IPV6_EBGP$",
    test_duration_seconds: int = 1800,
    uptime_seconds: int = 30,
    downtime_seconds: int = 30,
    sessions_per_cycle: int = 70,
    precheck_thresholds: t.Optional[HardwareCapacityThresholds] = None,
    postcheck_thresholds: t.Optional[HardwareCapacityThresholds] = None,
    expected_peer_identity: t.Optional[t.Dict[str, str]] = None,
    parent_prefixes_to_ignore: t.Optional[t.List[str]] = None,
    exclude_bgp_mon: bool = True,
) -> Playbook:
    """
    Create a BGP eBGP session oscillations test playbook.

    Randomly disrupts subsets of eBGP sessions in cycles.
    """
    if precheck_thresholds is None:
        precheck_thresholds = get_precheck_thresholds()

    if postcheck_thresholds is None:
        postcheck_thresholds = get_postcheck_thresholds()

    osc_checks = get_profile_checks(
        CheckProfile.OSCILLATION,
        ProfileContext(
            peergroup_ibgp_v6=peergroup_ibgp_v6,
            peergroup_ibgp_v4=peergroup_ibgp_v4,
            precheck_thresholds=precheck_thresholds,
            postcheck_thresholds=postcheck_thresholds,
            expected_established_sessions=expected_established_sessions,
            cpu_baseline=cpu_baseline,
            check_ibgp_pnh=(profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R),
            expected_peer_identity=expected_peer_identity,
            parent_prefixes_to_ignore=parent_prefixes_to_ignore,
            exclude_bgp_mon=exclude_bgp_mon,
            snapshot_skip_flap=True,
            snapshot_skip_uptime=True,
        ),
    )
    return Playbook(
        name="bgp_ebgp_session_oscillations_test_playbook",
        setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
        prechecks=osc_checks.prechecks,
        postchecks=osc_checks.postchecks,
        snapshot_checks=osc_checks.snapshot_checks,
        periodic_tasks=create_standard_periodic_tasks(
            device_name=device_name,
            memory_threshold=memory_threshold,
            cpu_util_terminate_on_error=cpu_util_terminate_on_error,
            memory_terminate_on_error=memory_terminate_on_error,
        ),
        stages=[
            create_bgp_session_oscillation_stage(
                ipv4_peer_regex=ipv4_peer_regex,
                ipv6_peer_regex=ipv6_peer_regex,
                test_duration_seconds=test_duration_seconds,
                uptime_seconds=uptime_seconds,
                downtime_seconds=downtime_seconds,
                sessions_per_cycle=sessions_per_cycle,
                ipv4_session_count=ipv4_session_count,
                ipv6_session_count=ipv6_session_count,
            ),
        ],
    )


def create_bgp_ebb_ibgp_tornado_plane_oscillations_playbook(
    device_name: str,
    peergroup_ibgp_v6: str,
    peergroup_ibgp_v4: str,
    ipv4_sessions_per_plane: int,
    ipv6_sessions_per_plane: int,
    expected_established_sessions: int = 0,
    profile: BgpPlusPlusProfile = BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
    cpu_baseline: float = 8.0,
    memory_threshold: int = Gigabyte.GIG_5.value,
    cpu_util_terminate_on_error: bool = False,
    memory_terminate_on_error: bool = False,
    ipv4_peer_regex: str = ".*IPV4_IBGP.*",
    ipv6_peer_regex: str = ".*IPV6_IBGP.*",
    test_duration_seconds: int = 1800,
    uptime_seconds: int = 30,
    downtime_seconds: int = 30,
    sessions_per_plane: int = 16,
    tornado_planes: t.Optional[t.List[int]] = None,
    session_type: str = "both",
    precheck_thresholds: t.Optional[HardwareCapacityThresholds] = None,
    postcheck_thresholds: t.Optional[HardwareCapacityThresholds] = None,
    expected_peer_identity: t.Optional[t.Dict[str, str]] = None,
    parent_prefixes_to_ignore: t.Optional[t.List[str]] = None,
    exclude_bgp_mon: bool = True,
) -> Playbook:
    """
    Create a BGP iBGP tornado plane oscillations test playbook.

    Disrupts iBGP sessions across tornado planes in cycles.
    """
    if tornado_planes is None:
        tornado_planes = [1, 2, 3, 4]

    if precheck_thresholds is None:
        precheck_thresholds = get_precheck_thresholds()

    if postcheck_thresholds is None:
        postcheck_thresholds = get_postcheck_thresholds()

    osc_checks = get_profile_checks(
        CheckProfile.OSCILLATION,
        ProfileContext(
            peergroup_ibgp_v6=peergroup_ibgp_v6,
            peergroup_ibgp_v4=peergroup_ibgp_v4,
            precheck_thresholds=precheck_thresholds,
            postcheck_thresholds=postcheck_thresholds,
            expected_established_sessions=expected_established_sessions,
            cpu_baseline=cpu_baseline,
            check_ibgp_pnh=(profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R),
            expected_peer_identity=expected_peer_identity,
            parent_prefixes_to_ignore=parent_prefixes_to_ignore,
            exclude_bgp_mon=exclude_bgp_mon,
            snapshot_skip_flap=True,
            snapshot_skip_uptime=True,
        ),
    )
    return Playbook(
        name="bgp_ibgp_tornado_plane_oscillations_test_playbook",
        setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
        prechecks=osc_checks.prechecks,
        postchecks=osc_checks.postchecks,
        snapshot_checks=osc_checks.snapshot_checks,
        periodic_tasks=create_standard_periodic_tasks(
            device_name=device_name,
            memory_threshold=memory_threshold,
            cpu_util_terminate_on_error=cpu_util_terminate_on_error,
            memory_terminate_on_error=memory_terminate_on_error,
        ),
        stages=[
            create_plane_aware_bgp_session_oscillation_stage(
                ipv4_peer_regex=ipv4_peer_regex,
                ipv6_peer_regex=ipv6_peer_regex,
                test_duration_seconds=test_duration_seconds,
                uptime_seconds=uptime_seconds,
                downtime_seconds=downtime_seconds,
                sessions_per_plane=sessions_per_plane,
                ipv4_sessions_per_plane=ipv4_sessions_per_plane,
                ipv6_sessions_per_plane=ipv6_sessions_per_plane,
                tornado_planes=tornado_planes,
                session_type=session_type,
            ),
        ],
    )


def create_bgp_ebb_nexthop_group_count_threshold_playbook(
    device_name: str,
    nexthop_group_threshold: int = 100,
    prefix_pool_regex: str = ".*EBGP.*",
    prefix_start_index: int = 0,
    prefix_end_index: int = 5000,
    test_duration_seconds: int = 1200,
    soak_duration: int = 300,
    convergence_threshold: int = 600,
    exclude_bgp_mon: bool = True,
) -> Playbook:
    """
    Create a nexthop group count threshold test playbook.

    Monitors nexthop group counts during eBGP route oscillations and fails
    if the count meets or exceeds the configured threshold.
    """
    # SOAK_NO_PRECHECK has no prechecks (the prechecks field is left unset).
    soak_checks = get_profile_checks(
        CheckProfile.SOAK_NO_PRECHECK,
        ProfileContext(
            check_bgp_convergence=True,
            convergence_threshold=convergence_threshold,
            exclude_bgp_mon=exclude_bgp_mon,
        ),
    )
    return Playbook(
        name="nexthop_group_count_threshold_playbook",
        setup_steps=create_bgp_instability_setup_steps(
            device_name=device_name,
        ),
        snapshot_checks=soak_checks.snapshot_checks,
        periodic_tasks=create_standard_periodic_tasks(
            device_name=device_name,
        )
        + [
            create_nexthop_group_poll_periodic_task(
                device_name=device_name,
                threshold=nexthop_group_threshold,
            ),
        ],
        postchecks=soak_checks.postchecks,
        stages=[
            create_route_oscillations_stage(
                device_name=device_name,
                prefix_pool_regex=prefix_pool_regex,
                prefix_start_index=prefix_start_index,
                prefix_end_index=prefix_end_index,
                test_duration_seconds=test_duration_seconds,
                spread=True,
            ),
            create_steps_stage(
                steps=[
                    create_longevity_step(
                        duration=soak_duration,
                        description=f"Soak after final prefix changes for {soak_duration} seconds",
                    ),
                ],
            ),
        ],
    )
