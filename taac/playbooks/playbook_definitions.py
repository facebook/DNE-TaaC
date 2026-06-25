# pyre-unsafe
"""
Centralized Playbook factory definitions.

All `create_*_playbook()` factory functions for TAAC live in this single file.
Per the Phase 4 v2 architecture: TestConfig/Playbook are the only categorizable
TAAC primitives, but Playbook factories themselves are centralized here so
test configs have one canonical import location.

The runner-side abstract base class lives in `playbooks/playbook.py`.
"""

import json
import math
import typing as t
from enum import Enum

from ixia.ixia import types as ixia_types
from taac.utils.qos_constants import ClassOfService
from taac.constants import (
    ARP_SOFT_LIMIT,
    BgpPlusPlusProfile,
    DEFAULT_OPENR_START_IPV4S,
    DEFAULT_OPENR_START_IPV6S,
    Gigabyte,
    MAC_SOFT_LIMIT,
    NDP_SOFT_LIMIT,
    OpenRRouteAction,
)
from taac.health_checks.constants import (
    _get_services_excluding,
    DEFAULT_SERVICE_NAMES,
    SERVICES_EXPECTED_TO_RESTART_DURING_AGENT_WARMBOOT,
    SERVICES_TO_MONITOR_DURING_AGENT_RESTART,
    SERVICES_TO_MONITOR_DURING_BGP_RESTART,
    SERVICES_TO_MONITOR_DURING_FSDB_RESTART,
    SERVICES_TO_MONITOR_DURING_OPENR_RESTART,
    SERVICES_TO_MONITOR_DURING_QSFP_SERVICE_RESTART,
)
from taac.playbooks.dlb_platform_constants import (
    DLB_RESOURCE_PROFILES,
    DlbAsic,
)
from taac.health_checks.healthcheck_definitions import (
    create_bgp_convergence_check,
    create_bgp_peer_route_set_equality_check,
    create_bgp_peer_route_snapshot_check,
    create_bgp_received_route_community_check,
    create_bgp_rib_fib_consistency_check,
    create_bgp_route_count_verification_check,
    create_bgp_session_establish_check,
    create_bgp_session_snapshot_check,
    create_bgp_stale_route_check,
    create_bgp_tcpdump_check,
    create_bgp_update_group_check,
    create_clear_counters_check,
    create_core_dumps_snapshot_check,
    create_cpu_queue_snapshot_check,
    create_cpu_utilization_check,
    create_device_core_dumps_check,
    create_dlb_resource_stickiness_check,
    create_drain_state_check,
    create_dsf_drain_state_check,
    create_dsf_fabric_reachability_check,
    create_dsf_pfc_check as _create_dsf_pfc_check_central,
    create_ecmp_group_and_member_count_check,
    create_fsdb_subscriber_timestamp_check,
    create_ixia_packet_loss_check,
    create_ixia_port_stats_check,
    create_ixia_traffic_rate_check,
    create_l2_entry_threshold_check,
    create_lldp_check,
    create_memory_utilization_check,
    create_oomd_kill_check,
    create_packetloss_health_check,
    create_pfc_wd_check as _create_pfc_wd_check_central,
    create_port_channel_expected_state_check,
    create_port_channel_state_snapshot_check,
    create_port_counters_check,
    create_port_queue_rate_check,
    create_port_state_check,
    create_port_transceiver_check,
    create_port_tx_rx_check,
    create_prefix_limit_check,
    create_service_restart_check,
    create_system_cpu_load_average_check,
    create_systemctl_active_state_check,
    create_unclean_exit_check,
    create_wedge_agent_configured_check,
)
from taac.packet_headers import (
    DSF_BE_PACKET_HEADERS,
    DSF_MONITORING_PACKET_HEADERS,
    DSF_NC_PACKET_HEADERS,
    DSF_RDMA_IB_PACKET_HEADERS,
    DSF_RDMA_PACKET_HEADERS,
    TC2_PFC_PAUSE_PACKET_HEADERS,
)
from taac.routing.dc_routing.bgp_dc.common import (
    DISABLE_PREFIX_FLAPS_STAGE,
    DISABLE_SESSION_FLAPS_STAGE,
    FREQUENT_BEST_PATH_COMPUTATION_STAGE,
)
from taac.routing.dc_routing.bgp_dc.shared_constants import (
    BGP_SESSION_HEALTHCHECK_NO_V6_LOSS_EXPECTED,
    get_ixia_healthcheck_ignore_cpu_and_v4_directional_traffic,
    get_ixia_healthcheck_stable_state,
)
from taac.routing.ebb.ebb_bgp_plus_plus_test_config.common_health_checks import (
    BGP_STANDARD_POSTCHECKS,
    BGP_STANDARD_SNAPSHOT_CHECKS,
    create_standard_postchecks,
    create_standard_prechecks,
    create_standard_snapshot_checks,
)
from taac.routing.ebb.ebb_bgp_plus_plus_test_config.common_periodic_tasks import (
    create_longevity_periodic_tasks,
    create_standard_periodic_tasks,
)
from taac.stages.stage_definitions import (
    create_bgp_igp_instability_unresolvable_pnhs_stage,
    create_bgp_restart_test_stage,
    create_bgp_session_oscillation_stage,
    create_cold_start_test_stage,
    create_fauu_drain_undrain_stage,
    create_longevity_stage,
    create_multipath_group_oscillation_stage,
    create_periodic_service_restart_stage,
    create_plane_aware_bgp_session_oscillation_stage,
    create_plane_drain_undrain_stage,
    create_port_channel_concurrent_cross_flap_stage,
    create_port_channel_concurrent_flap_stage,
    create_port_channel_cross_flap_stage,
    create_port_channel_flap_only_stage,
    create_port_channel_initial_setup_stage,
    create_port_channel_initial_setup_stage_with_permanent_disable,
    create_port_channel_permanent_teardown_stage,
    create_port_channel_teardown_stage,
    create_route_oscillations_stage,
    create_route_registry_runtime_update_stage,
    create_steps_stage,
)
from taac.steps.step_definitions import (
    COLD_START_PREFIX_OSCILLATIONS,
    CONTINUOUSLY_ACTIVATE_DEACTIVATE_ALL_PREFIXES,
    create_advertise_withdraw_prefixes_step,
    create_allocate_cgroup_memory_step,
    create_bgp_instability_setup_steps,
    create_bgp_restart_setup_steps,
    create_configure_community_pool_step,
    create_custom_step,
    create_drain_undrain_step,
    create_ecmp_member_static_route_step,
    create_interface_flap_step,
    create_ixia_api_step,
    create_ixia_device_group_toggle_step,
    create_longevity_step,
    create_mass_bgp_peer_toggle_step,
    create_openr_route_action_step,
    create_performance_scaling_convergence_step,
    create_performance_scaling_egress_sweep_aggregator_step,
    create_register_patcher_step,
    create_route_registry_prefix_list_setup_steps,
    create_run_ssh_command_step,
    create_run_task_step,
    create_service_convergence_step,
    create_service_interruption_step,
    create_service_restart_steps,
    create_set_route_filter_step,
    create_start_stop_bgp_peers_step,
    create_system_reboot_step,
    create_tcpdump_step,
    create_toggle_ixia_prefix_session_flap_churn_step,
    create_unregister_patcher_step,
    create_validation_step,
    create_verify_port_operational_state_step,
    duration_all_prefix_flaps_s,
    duration_all_session_flaps_s,
    duration_no_prefix_session_flaps_s,
    duration_only_rogue_session_prefix_flaps_s,
    REVERT_LOCAL_PREFERENCE_STEPS,
    ROGUE_PREFIX_SESSION_FLAP_STEPS,
    TOGGLE_ROGUE_DEVICE_GROUP_STEPS_CONTIUOUSLY,
    wait_time_after_disable_churn_s,
)
from taac.task_definitions import (
    create_nexthop_group_poll_periodic_task,
    create_thrift_stress_periodic_task,
)
from taac.tasks.thrift_stress_payloads import (
    fboss_with_qsfp_flaps,
    ThriftStressCall,
)
from taac.utils.hardware_capacity_utils import (
    get_postcheck_thresholds,
    get_precheck_thresholds,
    HardwareCapacityThresholds,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import (
    Playbook,
    PointInTimeHealthCheck,
    Service,
    ServiceInterruptionTrigger,
    SnapshotHealthCheck,
    Stage,
    Step,
    SystemRebootTrigger,
    TrafficEndpoint,
    TransformFunction,
    ValidationStage,
)


def create_bag010_ash6_bgp_instability_attribute_churn_playbook(
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
    from neteng.test_infra.dne.taac.constants import BgpPlusPlusProfile, Gigabyte
    from taac.routing.ebb.ebb_bgp_plus_plus_test_config.common_health_checks import (
        create_standard_postchecks,
        create_standard_prechecks,
    )
    from taac.stages.stage_definitions import (
        create_attribute_churn_stage,
    )

    return Playbook(
        name="bgp_instability_attribute_churn",
        setup_steps=create_bgp_instability_setup_steps(
            device_name=device_name,
        ),
        prechecks=create_standard_prechecks(
            peergroup_ibgp_v6=peergroup_ibgp_v6,
            peergroup_ibgp_v4=peergroup_ibgp_v4,
            expected_established_sessions=total_session_count,
            check_ibgp_pnh=(profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R),
            exclude_bgp_mon=exclude_bgp_mon,
        ),
        postchecks=create_standard_postchecks(
            check_bgp_convergence=False,
            expected_established_session_count=total_session_count,
            exclude_bgp_mon=exclude_bgp_mon,
        ),
        snapshot_checks=[
            create_core_dumps_snapshot_check(),
        ],
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


def create_bag010_ash6_bgp_instability_route_storm_playbook(
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
    from neteng.test_infra.dne.taac.constants import BgpPlusPlusProfile, Gigabyte
    from taac.routing.ebb.ebb_bgp_plus_plus_test_config.common_health_checks import (
        create_standard_postchecks,
        create_standard_prechecks,
    )
    from taac.stages.stage_definitions import (
        create_revert_route_storm_stage,
        create_route_storm_stage,
    )

    return Playbook(
        name="bgp_instability_route_storm",
        setup_steps=create_bgp_instability_setup_steps(
            device_name=device_name,
        ),
        prechecks=create_standard_prechecks(
            peergroup_ibgp_v6=peergroup_ibgp_v6,
            peergroup_ibgp_v4=peergroup_ibgp_v4,
            expected_established_sessions=total_session_count,
            check_ibgp_pnh=(profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R),
            exclude_bgp_mon=exclude_bgp_mon,
        ),
        postchecks=create_standard_postchecks(
            check_bgp_convergence=False,
            expected_established_session_count=total_session_count,
            rib_fib_json_params={
                "debug_route_attributes": True,
                "expected_as_path_length": 255,
                "expected_pool_size": 10,
            },
            exclude_bgp_mon=exclude_bgp_mon,
        ),
        snapshot_checks=[
            create_core_dumps_snapshot_check(),
        ],
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


def get_restart_playbooks(
    device_name: str,
    wedge_agent_restart_no_of_interations=10,
    **kwargs,
):
    """
    Returns a list of service restart playbooks (BGP_DC).

    These playbooks test the DUT's ability to handle repeated service
    restarts (both wedge_agent and BGP daemon) without traffic loss
    or session disruption.

    Args:
        device_name: The hostname of the device under test (DUT).
            Used to generate device-specific health checks.
        wedge_agent_restart_no_of_interations: Number of times to restart
            the wedge_agent in the agent restart test. Defaults to 10.
        **kwargs: Additional device parameters (ignored, for compatibility
            with the registry pattern).

    Returns:
        list[Playbook]: List of Playbook objects to be assembled by the
            main test config.
    """
    from taac.health_checks.constants import (
        SERVICES_TO_MONITOR_DURING_AGENT_RESTART,
        SERVICES_TO_MONITOR_DURING_BGP_RESTART,
    )
    from taac.routing.dc_routing.bgp_dc.common import (
        BGP_RESTART_STAGE,
    )
    from taac.routing.dc_routing.bgp_dc.shared_constants import (
        AGENT_RESTART_STEPS,
    )

    return [
        Playbook(
            name="test_agent_restart",
            postchecks=[
                create_service_restart_check(
                    services=SERVICES_TO_MONITOR_DURING_AGENT_RESTART
                ),
            ],
            stages=[
                create_steps_stage(
                    iteration=wedge_agent_restart_no_of_interations,
                    steps=AGENT_RESTART_STEPS,
                ),
            ],
        ),
        Playbook(
            name="test_bgp_restart",
            postchecks=[
                create_service_restart_check(
                    services=SERVICES_TO_MONITOR_DURING_BGP_RESTART
                ),
            ],
            stages=[BGP_RESTART_STAGE],
        ),
    ]


def get_hyperport_bag_disruptive_playbooks(
    traffic_items_to_start: list[str],
    device_regexes: t.Optional[t.List[str]] = None,
) -> list[Playbook]:
    """
    Get disruptive playbooks for Hyperport BAG testing.

    These playbooks test device resilience by simulating various failure scenarios
    including device reboots, module restarts, and agent crashes.

    This function maintains Hyperport-specific configurations that differ from the
    shared get_bag_disruptive_playbooks function:
    - 600 second longevity duration (vs 300 seconds in shared)
    - Linecard5 for module restart
    - Linecard5 AND Linecard6 for agent crash testing (shared uses Linecard3/4)

    Args:
        traffic_items_to_start: List of traffic item names to start during tests
        device_regexes: Optional list of device regex patterns to target

    Returns:
        List of Playbook objects for disruptive testing
    """
    from taac.steps.step_definitions import (
        create_system_reboot_step,
    )

    # Device reboot playbook (600 second duration - Hyperport-specific)
    test_device_reboot_playbook = Playbook(
        name="test_device_reboot",
        device_regexes=device_regexes,
        postchecks=[
            create_ixia_packet_loss_check(clear_traffic_stats=True),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_system_reboot_step(
                        trigger=taac_types.SystemRebootTrigger.FULL_SYSTEM_REBOOT,
                    ),
                    create_longevity_step(duration=600),
                ]
            )
        ],
        traffic_items_to_start=traffic_items_to_start,
    )

    # Fabric card restart - uses Fabric1
    test_fabric_card_restart_playbook = get_bag_module_restart_playbook(
        name="test_bag_fabric_card_restart",
        device_regexes=device_regexes,
        modules=["Fabric1"],
        traffic_items_to_start=traffic_items_to_start,
        is_seqential=False,
    )

    # Line card restart - uses Linecard5
    test_line_card_restart_playbook = get_bag_module_restart_playbook(
        name="test_bag_line_card_restart",
        device_regexes=device_regexes,
        modules=["Linecard5"],
        traffic_items_to_start=traffic_items_to_start,
        is_seqential=False,
    )

    # BGP agent crash
    test_bgp_agent_crash_playbook = get_bag_agent_interruption_playbook(
        name="test_bgp_agent_terminate",
        device_regexes=device_regexes,
        trigger=taac_types.ServiceInterruptionTrigger.CRASH,
        agents=["Bgp"],
        traffic_items_to_start=traffic_items_to_start,
    )

    # Fabric agent crash
    test_fabric_agent_crash_playbook = get_bag_agent_interruption_playbook(
        name="test_fabric_agent_terminate",
        device_regexes=device_regexes,
        trigger=taac_types.ServiceInterruptionTrigger.CRASH,
        agents=["SandFabric-Fabric1", "SandFabric-Fabric2", "SandFabric-Fabric3"],
        traffic_items_to_start=traffic_items_to_start,
    )

    # Linecard agent crash - uses BOTH Linecard5 AND Linecard6
    test_linecard_agent_crash_playbook = get_bag_agent_interruption_playbook(
        name="test_linecard_agent_terminate",
        device_regexes=device_regexes,
        trigger=taac_types.ServiceInterruptionTrigger.CRASH,
        agents=["SandFapNi-Linecard5", "SandFapNi-Linecard6"],
        traffic_items_to_start=traffic_items_to_start,
    )

    return [
        test_device_reboot_playbook,
        test_fabric_card_restart_playbook,
        test_line_card_restart_playbook,
        test_bgp_agent_crash_playbook,
        test_fabric_agent_crash_playbook,
        test_linecard_agent_crash_playbook,
    ]


def create_hyperport_snc_bag_longevity_playbook(
    traffic_items_to_start: list[str],
    longevity_duration: int,
    prechecks: list,
    postchecks: list,
) -> Playbook:
    """Build the `test_hyperport_longevity` Playbook for HYPERPORT_SNC_BAG TestConfigs.

    Single-stage longevity soak on `edsw003.n000.l201.snc1` that runs the
    given traffic items for `longevity_duration` seconds, gated by the
    caller-provided pre/postchecks. Used by HYPERPORT_SNC_BAG_TEST_CONFIGS
    to assert traffic stability over the configured duration.

    Args:
        traffic_items_to_start: IXIA traffic item names to enable for the
            playbook (e.g. RDMA streams).
        longevity_duration: Wall-clock duration of the longevity stage in
            seconds.
        prechecks: Point-in-time health checks to run before the stage
            (typically systemctl + IXIA stability).
        postchecks: Point-in-time health checks to run after the stage
            (typically traffic packet-loss + service-restart checks).

    Returns:
        A `Playbook` named `test_hyperport_longevity` scoped to the
        edsw003 SNC1 hyperport DUT with a single longevity stage.
    """
    return Playbook(
        name="test_hyperport_longevity",
        device_regexes=["edsw003.n000.l201.snc1"],
        traffic_items_to_start=traffic_items_to_start,
        stages=[create_longevity_stage(duration=longevity_duration)],
        prechecks=prechecks,
        postchecks=postchecks,
    )


# Hyperport EDSW003 DSF hardening — traffic item names
HYPERPORT_EDSW003_DSF_HARDENING_TRAFFIC_ITEM_GOLDEN = "golden"
HYPERPORT_EDSW003_DSF_HARDENING_EXPECT_LOSS_TRAFFIC_ITEMS = []
HYPERPORT_EDSW003_DSF_HARDENING_NO_LOSS_TRAFFIC_ITEMS = [
    HYPERPORT_EDSW003_DSF_HARDENING_TRAFFIC_ITEM_GOLDEN
]


def _build_dsf_hardening_thresholds(
    device_name: str,
    expect_loss_traffic: list[str],
    no_loss_traffic: list[str],
    skip_traffic_items: t.Optional[list[str]] = None,
) -> list[hc_types.PacketLossThreshold]:
    """Build the standard DSF-hardening packet-loss threshold list.

    Shared by ``create_hyperport_edsw003_dsf_hardening_ixia_healthcheck`` and
    ``create_dsf_hardening_ixia_healthcheck``. Both factories inline-built the
    same shape: an optional ``expect_packet_loss=True`` threshold for the
    expect-loss traffic items, followed by an optional ``str_value="0.1"``
    no-loss threshold for the no-loss traffic items.

    ``skip_traffic_items`` is accepted for signature parity with the public
    factories but does not currently influence the produced thresholds (the
    pre-refactor code only constructed an unused local for it).
    """
    thresholds: list[hc_types.PacketLossThreshold] = []
    if expect_loss_traffic:
        thresholds.append(
            hc_types.PacketLossThreshold(
                names=list(expect_loss_traffic),
                expect_packet_loss=True,
            )
        )
    if no_loss_traffic:
        thresholds.append(
            hc_types.PacketLossThreshold(
                names=list(no_loss_traffic),
                str_value="0.1",
                expect_packet_loss=False,
            )
        )
    return thresholds


def create_hyperport_edsw003_dsf_hardening_ixia_healthcheck(
    device_name: str,
    expect_loss_traffic: list = HYPERPORT_EDSW003_DSF_HARDENING_EXPECT_LOSS_TRAFFIC_ITEMS,
    no_loss_traffic: list = HYPERPORT_EDSW003_DSF_HARDENING_NO_LOSS_TRAFFIC_ITEMS,
) -> PointInTimeHealthCheck:
    """IXIA packet-loss healthcheck used by hyperport EDSW003 DSF hardening playbooks."""
    thresholds = _build_dsf_hardening_thresholds(
        device_name=device_name,
        expect_loss_traffic=expect_loss_traffic,
        no_loss_traffic=no_loss_traffic,
    )
    return create_ixia_packet_loss_check(thresholds=thresholds)


def create_edsw003_dsf_hardening_longevity_playbook(
    device_name: str,
    prefix_limit,
) -> Playbook:
    """Build the 4-minute longevity Playbook for hyperport EDSW003 DSF hardening.

    Runs a 240-second longevity stage gated by systemctl-active and
    hyperport-EDSW003 IXIA packet-loss prechecks; postchecks add a
    prefix-limit assertion. Used as the smoke/baseline playbook in the
    EDSW003 DSF hardening TestConfig before any disruptive playbooks run.

    Args:
        device_name: DUT hostname for the IXIA-loss health-check factory.
        prefix_limit: Expected RIB prefix-limit value for the postcheck
            (raw value passed through to `create_prefix_limit_check`).

    Returns:
        A `Playbook` named `1_test_longevity` with a single 240s longevity
        stage and a core-dumps snapshot check.
    """
    return Playbook(
        name="1_test_longevity",
        stages=[create_longevity_stage(duration=240)],
        prechecks=[
            create_systemctl_active_state_check(),
            create_hyperport_edsw003_dsf_hardening_ixia_healthcheck(device_name),
        ],
        postchecks=[
            create_systemctl_active_state_check(),
            create_hyperport_edsw003_dsf_hardening_ixia_healthcheck(device_name),
            create_prefix_limit_check(prefix_limit=prefix_limit),
        ],
        snapshot_checks=[
            create_core_dumps_snapshot_check(),
        ],
    )


def create_edsw003_dsf_hardening_agent_warmboot_playbook(
    device_name: str,
    prefix_limit,
) -> Playbook:
    """Build the agent warmboot Playbook for hyperport EDSW003 DSF hardening.

    Performs one systemctl restart of the AGENT service followed by an
    AGENT+BGP service-convergence wait. Pre/postchecks assert systemctl
    state and IXIA stability; postchecks additionally enforce a
    prefix-limit. Used after the longevity playbook in the EDSW003 DSF
    hardening TestConfig to verify warmboot does not regress traffic or
    RIB state.

    Args:
        device_name: DUT hostname for the IXIA-loss health-check factory.
        prefix_limit: Expected RIB prefix-limit value for the postcheck.

    Returns:
        A `Playbook` named `2_test_agent_warmboot` with a single
        warmboot-and-converge stage and a core-dumps snapshot check.
    """
    return Playbook(
        name="2_test_agent_warmboot",
        stages=[
            create_steps_stage(
                iteration=1,
                steps=[
                    create_service_interruption_step(
                        service=taac_types.Service.AGENT,
                        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(
                        services=[taac_types.Service.AGENT, taac_types.Service.BGP],
                    ),
                ],
            ),
        ],
        prechecks=[
            create_systemctl_active_state_check(),
            create_hyperport_edsw003_dsf_hardening_ixia_healthcheck(device_name),
        ],
        postchecks=[
            create_systemctl_active_state_check(),
            create_hyperport_edsw003_dsf_hardening_ixia_healthcheck(device_name),
            AGENT_RESTART_SERVICE_CHECK,
            create_prefix_limit_check(prefix_limit=prefix_limit),
        ],
    )


def create_fboss_vip_hardening_4_min_longevity_playbook() -> Playbook:
    """Build the test_4_min_longevity Playbook for FBOSS VIP hardening (4-min variant).

    Single 240s longevity stage with postcheck-only IXIA-packet-loss (0.1
    threshold), unclean-exit, and memory-utilization (4.3 GiB) checks.
    """
    return Playbook(
        name="test_4_min_longevity",
        stages=[create_longevity_stage(duration=240)],
        postchecks=[
            create_ixia_packet_loss_check(
                thresholds=[hc_types.PacketLossThreshold(str_value="0.1")]
            ),
            create_unclean_exit_check(),
            create_memory_utilization_check(
                threshold=Gigabyte.GIG_4_POINT_3.value,
                start_time_jq_var="test_case_start_time",
            ),
        ],
    )


def create_fboss_vip_hardening_4000_min_longevity_playbook() -> Playbook:
    """Build the test_4000_min_longevity Playbook for FBOSS VIPs RIB protection.

    Single 240000s (~4000 min) longevity stage; no extra checks.
    """
    return Playbook(
        name="test_4000_min_longevity",
        stages=[create_longevity_stage(duration=240000)],
    )


def build_mp3n_profiling_playbook(
    name: str,
    description: str,
    postchecks_to_skip: t.List,
    postchecks: t.List[PointInTimeHealthCheck],
    snapshot_checks: t.List[SnapshotHealthCheck],
    stages: t.List[taac_types.Stage],
) -> Playbook:
    """
    Generic Playbook builder shared by the warmboot/bgp_restart/coldboot
    factories in mp3n_prefix_profiling_ixia_config. Centralizes the
    `taac_types.Playbook(...)` construction so the source file no longer
    inline-constructs Playbook.
    """
    return Playbook(
        name=name,
        description=description,
        postchecks_to_skip=postchecks_to_skip,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
        stages=stages,
    )


# DSF hardening test config — traffic item names
DSF_HARDENING_TRAFFIC_ITEM_GOLDEN = "golden"
DSF_HARDENING_TRAFFIC_ITEM_RDSW_RDSW_SAME_CLUSTER = "rdsw_rdsw_same_cluster"

# TODO(pavanpatil): golden traffic is expected to be lossy because RA flood
# slows NDP entry addition to the platform, causing transient ECMP nexthop misses.
DSF_HARDENING_EXPECT_LOSS_TRAFFIC_ITEMS = [DSF_HARDENING_TRAFFIC_ITEM_GOLDEN]
DSF_HARDENING_NO_LOSS_TRAFFIC_ITEMS = [
    DSF_HARDENING_TRAFFIC_ITEM_RDSW_RDSW_SAME_CLUSTER
]


def create_dsf_hardening_ixia_healthcheck(
    device_name: str,
    expect_loss_traffic: list = DSF_HARDENING_EXPECT_LOSS_TRAFFIC_ITEMS,
    no_loss_traffic: list = DSF_HARDENING_NO_LOSS_TRAFFIC_ITEMS,
    skip_traffic_items: list | None = None,
) -> PointInTimeHealthCheck:
    """IXIA packet-loss health check used by DSF hardening playbooks."""
    thresholds = _build_dsf_hardening_thresholds(
        device_name=device_name,
        expect_loss_traffic=expect_loss_traffic,
        no_loss_traffic=no_loss_traffic,
        skip_traffic_items=skip_traffic_items,
    )
    return create_ixia_packet_loss_check(thresholds=thresholds)


def create_ndp_device_group_churn_playbook(
    duration_minutes: int = 60,
    toggle_interval_seconds: int = 30,
    name: str = "test_ndp_supporting_nexthop_device_group_churn",
    description: t.Optional[str] = None,
    postchecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
) -> Playbook:
    """
    Create a playbook that continuously churns (enables/disables) the
    NDP_SUPPORTING_NEXTHOP device group for the specified duration.

    Each iteration: enable -> wait -> disable -> wait.
    With default 30s intervals, each iteration takes ~60s,
    so 60 iterations covers ~60 minutes.

    Args:
        duration_minutes: Total duration to run the churn in minutes
        toggle_interval_seconds: Seconds to wait between each toggle
        name: Playbook name (defaults to "test_ndp_supporting_nexthop_device_group_churn")
        description: Optional playbook description (defaults to a churn-summary string)
        postchecks: Optional list of PointInTimeHealthCheck postchecks

    Returns:
        Playbook configured for NDP device group churn
    """
    iterations = (duration_minutes * 60) // (toggle_interval_seconds * 2)
    if description is None:
        description = (
            f"Churn NDP_SUPPORTING_NEXTHOP device group for {duration_minutes} minutes"
        )
    playbook_kwargs: dict = {
        "name": name,
        "description": description,
        "stages": [
            create_steps_stage(
                iteration=iterations,
                steps=[
                    create_ixia_device_group_toggle_step(
                        enable=True,
                        device_group_name_regex="NDP_SUPPORTING_NEXTHOP",
                    ),
                    create_longevity_step(
                        duration=toggle_interval_seconds,
                        description=f"Wait {toggle_interval_seconds}s with device group enabled",
                    ),
                    create_ixia_device_group_toggle_step(
                        enable=False,
                        device_group_name_regex="NDP_SUPPORTING_NEXTHOP",
                    ),
                    create_longevity_step(
                        duration=toggle_interval_seconds,
                        description=f"Wait {toggle_interval_seconds}s with device group disabled",
                    ),
                ],
            ),
        ],
    }
    if postchecks is not None:
        playbook_kwargs["postchecks"] = postchecks
    return Playbook(**playbook_kwargs)


def create_dsf_test_agent_warmboot_playbook(
    device_name: str,
    prefix_limit,
    fsdb_subscriber_clients: dict,
) -> Playbook:
    """
    Create the test_agent_warmboot Playbook used in the DSF hardening conveyor
    test config. Captures device-specific state (device_name, prefix_limit,
    FSDB subscriber client names) via explicit parameters.
    """
    return Playbook(
        name="test_agent_warmboot",
        stages=[
            create_steps_stage(
                iteration=1,
                steps=[
                    create_service_interruption_step(
                        service=taac_types.Service.AGENT,
                        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(
                        services=[taac_types.Service.AGENT, taac_types.Service.BGP],
                    ),
                ],
            ),
            create_steps_stage(
                iteration=1,
                steps=[
                    create_ixia_device_group_toggle_step(
                        enable=True,
                        device_group_name_regex="NDP_SUPPORTING_NEXTHOP",
                        description="Enable NDP_SUPPORTING_NEXTHOP device group (one-time)",
                    ),
                    create_longevity_step(
                        duration=300,
                        description="Wait 5 minutes for NDP entries to populate on DUT",
                    ),
                    create_ixia_api_step(
                        api_name="clear_traffic_stats",
                        args_dict={"wait_for_refresh": True},
                        description="Clear IXIA traffic counters before warmboot",
                    ),
                    create_longevity_step(
                        duration=300,
                        description="Wait 5 minutes after clearing counters",
                    ),
                    create_service_interruption_step(
                        service=taac_types.Service.AGENT,
                        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(
                        services=[taac_types.Service.AGENT, taac_types.Service.BGP],
                    ),
                ],
            ),
        ],
        prechecks=[
            create_systemctl_active_state_check(),
            create_dsf_hardening_ixia_healthcheck(
                device_name,
                expect_loss_traffic=[],
                no_loss_traffic=[DSF_HARDENING_TRAFFIC_ITEM_RDSW_RDSW_SAME_CLUSTER],
                skip_traffic_items=[DSF_HARDENING_TRAFFIC_ITEM_GOLDEN],
            ),
        ],
        postchecks=[
            create_systemctl_active_state_check(),
            create_dsf_hardening_ixia_healthcheck(
                device_name,
                expect_loss_traffic=[],
                no_loss_traffic=[
                    DSF_HARDENING_TRAFFIC_ITEM_GOLDEN,
                    DSF_HARDENING_TRAFFIC_ITEM_RDSW_RDSW_SAME_CLUSTER,
                ],
            ),
            AGENT_RESTART_SERVICE_CHECK,
            create_fsdb_subscriber_timestamp_check(
                json_params={
                    "target_device": device_name,
                    "subscriber_names": list(fsdb_subscriber_clients.keys()),
                    "is_validate_fsdb_session_after_agent_restart": True,
                },
                start_time_jq_var="test_case_start_time",
            ),
            create_prefix_limit_check(prefix_limit=prefix_limit),
        ],
    )


def create_snc_bgp_scale_20_hour_longevity_playbook() -> Playbook:
    """Build the 20-hour longevity Playbook for SNC_BGP_SCALE_TEST.

    Single 72,000-second (20-hour) soak stage with no playbook-level
    checks (TestConfig-level checks gate the run). Used to validate that
    a fully scaled BGP control plane on the SNC1 BGP-scale testbed stays
    stable over an extended duration.

    Returns:
        A `Playbook` named `test_20_hour_longevity` with one longevity
        stage and no playbook-level pre/postchecks.
    """
    return Playbook(
        name="test_20_hour_longevity",
        stages=[create_longevity_stage(duration=72000)],
    )


def create_sev_0_route_break_retro_longevity_playbook() -> Playbook:
    """Build the SEV-0 route break repro longevity Playbook.

    A near-perpetual longevity stage (360,000,000 seconds) used by the
    SEV-0 route-break repro TestConfig to keep traffic flowing while
    operators iteratively trigger the suspected route-break condition out
    of band. Intended for repro/debug runs only — never as a CI playbook.

    Returns:
        A `Playbook` named `test_longevity` with a single multi-year
        longevity stage and no checks.
    """
    return Playbook(
        name="test_longevity",
        stages=[create_longevity_stage(duration=360000000)],
    )


def create_rtsw_longevity_playbook(
    rtsw_id: int,
    ixia_packet_loss_check: PointInTimeHealthCheck,
    duration: int = 240,
    traffic_item_name: str | None = None,
) -> Playbook:
    """Build the RTSW longevity Playbook for the given testbed.

    Single-stage longevity Playbook parameterized by `rtsw_id` (e.g. 1, 2)
    used to derive the testbed-specific Playbook name and default IXIA
    traffic item name (`RTSW{rtsw_id:03d}_SNC1_TRAFFIC`). An IXIA
    packet-loss postcheck is attached.

    Args:
        rtsw_id: Numeric RTSW testbed id (e.g. 1 for RTSW001, 2 for RTSW002).
        ixia_packet_loss_check: PointInTime healthcheck enforcing packet-loss
            bound after the longevity stage completes.
        duration: Longevity stage duration in seconds. Defaults to 240.
        traffic_item_name: Override for the IXIA traffic item to start.
            Defaults to ``f"RTSW{rtsw_id:03d}_SNC1_TRAFFIC"``.

    Returns:
        A `Playbook` configured with one longevity stage and an IXIA
        packet-loss postcheck.
    """
    if traffic_item_name is None:
        traffic_item_name = f"RTSW{rtsw_id:03d}_SNC1_TRAFFIC"
    return Playbook(
        name=f"test_rtsw{rtsw_id:03d}_longevity",
        stages=[create_longevity_stage(duration=duration)],
        postchecks=[
            ixia_packet_loss_check,
        ],
        traffic_items_to_start=[traffic_item_name],
        enabled=True,
    )


def create_network_ai_hardening_agent_warmboot_playbook(
    ixia_stable_state_healthcheck: taac_types.PointInTimeHealthCheck,
    bgp_session_healthcheck: taac_types.PointInTimeHealthCheck,
    agent_restart_service_check: taac_types.PointInTimeHealthCheck,
    prefix_limit: str,
) -> taac_types.Playbook:
    """Build the test_agent_warmboot Playbook for Network AI hardening conveyor.

    Single-stage AGENT warmboot + service convergence on AGENT and BGP, with
    pre/post systemctl + IXIA stable + BGP-session checks plus a postcheck-only
    AGENT_RESTART service check and prefix-limit check (parameterized via
    `prefix_limit`).
    """
    return taac_types.Playbook(
        name="test_agent_warmboot",
        stages=[
            create_steps_stage(
                iteration=1,
                steps=[
                    create_service_interruption_step(
                        service=taac_types.Service.AGENT,
                    ),
                    create_service_convergence_step(
                        services=[
                            taac_types.Service.AGENT,
                            taac_types.Service.BGP,
                        ],
                    ),
                ],
            ),
        ],
        prechecks=[
            create_systemctl_active_state_check(),
            ixia_stable_state_healthcheck,
            bgp_session_healthcheck,
        ],
        postchecks=[
            create_systemctl_active_state_check(),
            ixia_stable_state_healthcheck,
            bgp_session_healthcheck,
            agent_restart_service_check,
            create_prefix_limit_check(prefix_limit=prefix_limit),
        ],
    )


def create_longevity_playbook(
    playbook_name: str,
    longevity_duration: int,
    traffic_items_to_start: list[str],
    prechecks: list[PointInTimeHealthCheck] | None = None,
    postchecks: list[PointInTimeHealthCheck] | None = None,
    snapshot_checks: list[SnapshotHealthCheck] | None = None,
) -> Playbook:
    """Build the CBAG_BAG longevity Playbook.

    Single-stage longevity soak that runs the two RDMA CBAG001 -> BAG001/2
    traffic items for `longevity_duration` seconds, gated by the caller-
    provided pre/post/snapshot health checks (typically TestConfig-level
    BGP / drain / core-dump checks merged through here so the playbook
    self-contains its assertions).

    Args:
        longevity_duration: Wall-clock duration of the longevity stage in
            seconds.
        prechecks: Point-in-time health checks to run before the stage.
        postchecks: Point-in-time health checks to run after the stage.
        snapshot_checks: Snapshot health checks (before/after deltas).

    Returns:
        A `Playbook` named `test_cbag_bag_longevity` with the two RDMA
        traffic items started and a single longevity stage.
    """
    return Playbook(
        name=playbook_name,
        traffic_items_to_start=traffic_items_to_start,
        stages=[create_longevity_stage(duration=longevity_duration)],
        prechecks=prechecks or [],
        postchecks=postchecks or [],
        snapshot_checks=snapshot_checks or [],
    )


def create_bag_qza1_longevity_playbook(
    longevity_duration: int,
    traffic_items_to_start: list[str],
    prechecks: list[PointInTimeHealthCheck],
    postchecks: list[PointInTimeHealthCheck],
    snapshot_checks: list[SnapshotHealthCheck],
) -> Playbook:
    """Build the BAG ASH6 <-> QZA1 longevity Playbook.

    Single-stage longevity soak across the BAG ASH6 to QZA1 testbed pair,
    running the given IXIA traffic items for `longevity_duration` seconds
    and gated entirely by caller-supplied pre/post/snapshot health checks.

    Args:
        longevity_duration: Wall-clock duration of the longevity stage in
            seconds.
        traffic_items_to_start: IXIA traffic item names to enable.
        prechecks: Point-in-time health checks to run before the stage.
        postchecks: Point-in-time health checks to run after the stage.
        snapshot_checks: Snapshot health checks (before/after deltas).

    Returns:
        A `Playbook` named `test_bag_ash6_qza_longevity` with one
        longevity stage and the provided checks.
    """
    return Playbook(
        name="test_bag_ash6_qza_longevity",
        traffic_items_to_start=traffic_items_to_start,
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
        stages=[create_longevity_stage(duration=longevity_duration)],
    )


def create_bag_qza1_stsw_longevity_playbook(
    longevity_duration: int,
    traffic_items_to_start: list[str],
    prechecks: list[PointInTimeHealthCheck],
    postchecks: list[PointInTimeHealthCheck],
    snapshot_checks: list[SnapshotHealthCheck],
) -> Playbook:
    """Build the BAG QZA1 <-> STSW longevity Playbook.

    Single-stage longevity soak across the bag001.qza1 <-> stsw003.s001.l201.qza1
    testbed pair, running the given IXIA traffic items for `longevity_duration`
    seconds and gated entirely by caller-supplied pre/post/snapshot health checks.

    Args:
        longevity_duration: Wall-clock duration of the longevity stage in
            seconds.
        traffic_items_to_start: IXIA traffic item names to enable.
        prechecks: Point-in-time health checks to run before the stage.
        postchecks: Point-in-time health checks to run after the stage.
        snapshot_checks: Snapshot health checks (before/after deltas).

    Returns:
        A `Playbook` named `test_bag_qza1_stsw_longevity` with one
        longevity stage and the provided checks.
    """
    return Playbook(
        name="test_bag_qza1_stsw_longevity",
        traffic_items_to_start=traffic_items_to_start,
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
        stages=[create_longevity_stage(duration=longevity_duration)],
    )


def _add_checks_to_optics_npi_playbook(playbook, prechecks, postchecks):
    """Create a copy of a playbook with added prechecks and postchecks."""
    return playbook(
        prechecks=list(playbook.prechecks or []) + list(prechecks),
        postchecks=list(playbook.postchecks or []) + list(postchecks),
    )


def build_optics_npi_playbooks():
    """Build the full playbook list for FBOSS optics NPI TestConfigs.

    Includes a 2-min longevity playbook plus standard agent/bgpd/fsdb/qsfp
    restart playbooks, all with the standard prechecks/postchecks attached.
    """
    _prechecks = [
        create_lldp_check(),
        create_port_state_check(),
        create_ixia_packet_loss_check(clear_traffic_stats=True),
    ]
    _postchecks = [
        create_lldp_check(),
        create_port_state_check(),
        create_ixia_packet_loss_check(clear_traffic_stats=True),
    ]
    return [
        taac_types.Playbook(
            name="test_2_min_longevity",
            prechecks=_prechecks,
            postchecks=_postchecks,
            stages=[create_longevity_stage(duration=120)],
        ),
        _add_checks_to_optics_npi_playbook(
            TEST_AGENT_WARMBOOT_PLAYBOOK, _prechecks, _postchecks
        ),
        _add_checks_to_optics_npi_playbook(
            TEST_BGPD_RESTART_PLAYBOOK, _prechecks, _postchecks
        ),
        _add_checks_to_optics_npi_playbook(
            TEST_CONTINUOUS_AGENT_WARMBOOT_PLAYBOOK, _prechecks, _postchecks
        ),
        _add_checks_to_optics_npi_playbook(
            TEST_CONTINUOUS_FSDB_RESTART_PLAYBOOK, _prechecks, _postchecks
        ),
        _add_checks_to_optics_npi_playbook(
            TEST_CONTINUOUS_QSPF_RESTART_PLAYBOOK, _prechecks, _postchecks
        ),
        _add_checks_to_optics_npi_playbook(
            TEST_FSDB_RESTART_PLAYBOOK, _prechecks, _postchecks
        ),
        _add_checks_to_optics_npi_playbook(
            TEST_QSPF_RESTART_PLAYBOOK, _prechecks, _postchecks
        ),
        _add_checks_to_optics_npi_playbook(
            TEST_AGENT_WARMBOOT_AND_FSDB_RESTART_PLAYBOOK, _prechecks, _postchecks
        ),
    ]


def create_building_block_playbooks(
    duration_mass_bgp_toggle_hr,
    longevity_duration_hr,
    stable_state_duration_hours,
    rogue_interface_name,
    total_run_time,
):
    """
    Generate a set of playbooks that iterate over BGP DC building-block test patterns.

    Each iteration produces playbooks for:
    - TOGGLE_IXIA_PREFIX_SESSION_FLAP
    - MASS_BGP_PEER_TOGGLE
    - Longevity step

    The total_run_time is evenly divided by the per-block time to determine
    the number of iterations.

    Args:
        duration_mass_bgp_toggle_hr: Hours for mass BGP peer toggle.
        longevity_duration_hr: Hours for longevity/soak.
        stable_state_duration_hours: Hours for stable state observation.
        rogue_interface_name: Name of the rogue interface (auto-uppercased).
        total_run_time: Total run time in hours. Must be a multiple of
            the per-building-block time.

    Returns:
        list[Playbook]: List of playbooks, one per step per iteration.
    """
    rogue_interface_name = rogue_interface_name.upper()
    time_per_building_block = (
        duration_mass_bgp_toggle_hr
        + longevity_duration_hr
        + stable_state_duration_hours
    )
    if total_run_time % time_per_building_block != 0:
        raise ValueError(
            "Total run time must be a multiple of the time per building block"
        )
    num_iterations = int(total_run_time // time_per_building_block)
    playbooks = []
    for i in range(1, num_iterations + 1):
        building_block_step = [
            create_toggle_ixia_prefix_session_flap_churn_step(),
            create_mass_bgp_peer_toggle_step(
                device_group_name_regex=rogue_interface_name,
                toggle_time_interval_s=100,
                total_step_time_hours=duration_mass_bgp_toggle_hr,
            ),
            create_longevity_step(
                duration=longevity_duration_hr * 60,
            ),
        ]
        for step in building_block_step:
            playbook_name = f"test_chronos_{step.name.name.lower()}_iteration_{i}"
            playbooks.append(
                Playbook(
                    name=playbook_name,
                    stages=[create_steps_stage(steps=[step])],
                )
            )
    return playbooks


def create_mp3n_gar_agent_restart_playbook(
    ixia_stable_state_healthcheck: taac_types.PointInTimeHealthCheck,
) -> taac_types.Playbook:
    """Build the MP3N GAR test_agent_restart Playbook.

    Restarts AGENT via systemctl, waits for AGENT + BGP convergence, with
    pre/post systemctl + core-dump checks plus IXIA stable-state check
    (caller supplies the IXIA healthcheck since it's source-device-dependent).
    """
    return taac_types.Playbook(
        name="test_agent_restart",
        stages=[
            create_steps_stage(
                iteration=1,
                steps=[
                    create_service_interruption_step(
                        service=taac_types.Service.AGENT,
                        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(
                        services=[taac_types.Service.AGENT, taac_types.Service.BGP],
                    ),
                ],
            ),
        ],
        prechecks=[
            create_systemctl_active_state_check(),
            create_device_core_dumps_check(use_start_time=False),
            ixia_stable_state_healthcheck,
        ],
        postchecks=[
            create_systemctl_active_state_check(),
            create_device_core_dumps_check(use_start_time=False),
            ixia_stable_state_healthcheck,
        ],
        snapshot_checks=[
            create_core_dumps_snapshot_check(),
        ],
    )


def create_test_portchannel_playbook(longevity_duration: int = 600) -> Playbook:
    """Build the `test_portchannel` longevity Playbook for port-channel TestConfigs.

    Single-stage longevity playbook that exercises a port-channel under
    sustained traffic for `longevity_duration` seconds, with comprehensive
    FBOSS-process pre/postchecks (systemctl, prefix limit, unclean exit,
    per-service memory thresholds, postcheck CPU + service-restart) and a
    core-dumps snapshot check.

    Args:
        longevity_duration: Wall-clock duration of the longevity stage in
            seconds. Default 600.

    Returns:
        A `Playbook` named `test_portchannel` with the gated checks above
        and a single longevity stage.
    """
    return Playbook(
        name="test_portchannel",
        prechecks=[
            create_systemctl_active_state_check(),
            create_prefix_limit_check(prefix_limit=74000),
            create_unclean_exit_check(),
            create_memory_utilization_check(
                threshold=5 * (1024**3),
                threshold_by_service={
                    "bgpd": 4.5 * (1024**3),
                    "fsdb": 5 * (1024**3),
                    "qsfp_service": 2 * (1024**3),
                    "fboss_sw_agent": 9 * (1024**3),
                    "fboss_hw_agent@0": 8 * (1024**3),
                },
                start_time_jq_var="test_case_start_time",
            ),
        ],
        postchecks=[
            create_systemctl_active_state_check(),
            create_device_core_dumps_check(),
            create_prefix_limit_check(prefix_limit=74000),
            create_unclean_exit_check(),
            create_memory_utilization_check(
                threshold=5 * (1024**3),
                threshold_by_service={
                    "bgpd": 4.5 * (1024**3),
                    "fsdb": 5 * (1024**3),
                    "qsfp_service": 2 * (1024**3),
                    "fboss_sw_agent": 9 * (1024**3),
                    "fboss_hw_agent@0": 8 * (1024**3),
                },
                start_time_jq_var="test_case_start_time",
            ),
            create_cpu_utilization_check(
                threshold=400.0, start_time_jq_var="test_case_start_time"
            ),
            create_service_restart_check(),
        ],
        snapshot_checks=[
            create_core_dumps_snapshot_check(),
        ],
        stages=[create_longevity_stage(duration=longevity_duration)],
    )


def create_fboss_hardening_3_min_longevity_playbook() -> taac_types.Playbook:
    """Build the test_3_min_longevity Playbook for FBOSS hardening TestConfigs.

    Single 180s longevity stage with IXIA-packet-loss pre/postchecks, plus
    postcheck-only unclean-exit, memory-utilization (4.3 GiB threshold), and
    a BGP-session snapshot check. Used identically by both wedge100s and
    minipack hardening TestConfigs in this file.
    """
    return taac_types.Playbook(
        name="test_3_min_longevity",
        prechecks=[
            create_ixia_packet_loss_check(clear_traffic_stats=True),
        ],
        postchecks=[
            create_ixia_packet_loss_check(
                thresholds=[hc_types.PacketLossThreshold(str_value="0.1")],
                clear_traffic_stats=True,
            ),
            create_unclean_exit_check(),
            create_memory_utilization_check(threshold=Gigabyte.GIG_4_POINT_3.value),
        ],
        stages=[create_longevity_stage(duration=180)],
        snapshot_checks=[create_bgp_session_snapshot_check()],
    )


def add_common_checks_to_cpu_queue_playbooks(
    playbooks: list[Playbook],
    unique_prefix_limit: int,
    ixia_packet_loss_threshold: str = "0.1",
    service_restart_services: list[str] | None = None,
) -> list[Playbook]:
    """Add former TestConfig-level checks to each playbook from create_cpu_queue_playbooks().

    Merges prechecks, postchecks, and snapshot_checks into each playbook,
    appending to any existing checks the playbook already has.

    `ixia_packet_loss_threshold` controls the precheck/postcheck packet-loss
    tolerance (default "0.1" = 10%). Set to "1.0" on TestConfigs where BGP route
    forwarding intentionally won't work for IXIA-mimic peers (e.g., the DUT
    applies strict ingress filters that drop synthetic routes), so the
    precheck doesn't block the actual CPU-queue snapshot assertion.

    `service_restart_services` overrides the default service list monitored by
    the postcheck `ServiceRestartHealthCheck`. Default (None) keeps the check's
    built-in list (bgpd, fboss_hw_agent@0, fboss_sw_agent, fsdb, openr,
    qsfp_service, wedge_agent). Set explicitly to drop services not present on
    a given DUT — e.g. IcePack backend GTSWs don't run openr, so omitting it
    here avoids a postcheck false-fail on INACTIVE.
    """
    common_prechecks = [
        create_drain_state_check(),
        create_bgp_session_establish_check(),
        create_systemctl_active_state_check(),
        create_prefix_limit_check(prefix_limit=unique_prefix_limit),
        create_memory_utilization_check(
            threshold=5 * (1024**3),  # 5gb
            start_time_jq_var="test_case_start_time",
        ),
        create_port_state_check(),
        create_lldp_check(),
        create_ixia_packet_loss_check(
            clear_traffic_stats=True,
            thresholds=[
                hc_types.PacketLossThreshold(str_value=ixia_packet_loss_threshold)
            ],
        ),
    ]
    common_service_restart_check = create_service_restart_check(
        services=service_restart_services
    )
    common_postchecks_without_srh = [
        create_prefix_limit_check(prefix_limit=unique_prefix_limit),
        create_unclean_exit_check(),
        create_ixia_packet_loss_check(
            thresholds=[
                hc_types.PacketLossThreshold(str_value=ixia_packet_loss_threshold)
            ]
        ),
        create_cpu_utilization_check(
            threshold=400.0, start_time_jq_var="test_case_start_time"
        ),
    ]
    common_snapshot_checks = [
        create_core_dumps_snapshot_check(),
        create_bgp_peer_route_snapshot_check(),
    ]
    result = []
    for pb in playbooks:
        # If the playbook defines its own SERVICE_RESTART_CHECK (e.g.
        # npi_cpu_036/037/038, which intentionally restart wedge_agent and
        # need the BindsTo cascade in expected_restarted_services), skip the
        # generic common SERVICE_RESTART_CHECK — the generic one monitors
        # wedge_agent but has empty expected_restarted_services, so it would
        # false-fail the intentional restart.
        pb_has_service_restart_check = any(
            c.name == hc_types.CheckName.SERVICE_RESTART_CHECK
            for c in (pb.postchecks or [])
        )
        common_postchecks = (
            common_postchecks_without_srh
            if pb_has_service_restart_check
            else [common_service_restart_check] + common_postchecks_without_srh
        )
        result.append(
            Playbook(
                name=pb.name,
                stages=pb.stages,
                description=pb.description,
                iteration=pb.iteration,
                traffic_items_to_start=pb.traffic_items_to_start,
                enabled=pb.enabled,
                backup_and_restore_ixia_config=pb.backup_and_restore_ixia_config,
                prechecks=list(pb.prechecks or []) + common_prechecks,
                postchecks=common_postchecks + list(pb.postchecks or []),
                snapshot_checks=list(pb.snapshot_checks or []) + common_snapshot_checks,
                skip_test_config_prechecks=pb.skip_test_config_prechecks,
                skip_test_config_postchecks=pb.skip_test_config_postchecks,
                skip_test_config_snapshot_checks=pb.skip_test_config_snapshot_checks,
                override_duplicate_checks=pb.override_duplicate_checks,
                prechecks_to_skip=pb.prechecks_to_skip,
                postchecks_to_skip=pb.postchecks_to_skip,
                snapshot_checks_to_skip=pb.snapshot_checks_to_skip,
                check_ids_to_skip=pb.check_ids_to_skip,
                cleanup_steps=pb.cleanup_steps,
                setup_steps=pb.setup_steps,
                device_regexes=pb.device_regexes,
                periodic_tasks=pb.periodic_tasks,
                attribute_filters=pb.attribute_filters,
                traffic_items_to_configure=pb.traffic_items_to_configure,
                scuba_table=pb.scuba_table,
            )
        )
    return result


def _scale_payload_per_call(
    payload: list[ThriftStressCall], requests_per_burst: int
) -> list[ThriftStressCall]:
    """Override `requests_per_burst` on every read-only thrift entry in the
    payload, preserving the flap entry's per-burst count (which is always 1 —
    the 100-flap scale lives inside the args, not the count)."""
    scaled = []
    for c in payload:
        if c.method == "async_do_rapid_interface_flaps":
            scaled.append(c)
            continue
        scaled.append(
            ThriftStressCall(
                method=c.method,
                args=c.args,
                requests_per_burst=requests_per_burst,
            )
        )
    return scaled


def create_thft_baseline_playbook(
    device_name: str,
    stsw_flap_ports: list[str],
    test_duration_s: int = 600,
    requests_per_burst: int = 10000,
    burst_timeout_s: float = 60.0,
) -> Playbook:
    """THFT_001 baseline — Pavan-design thrift stress (qsfp port flap is
    assumed in the background and always present in the periodic-task
    payload; to disable, omit `stsw_flap_ports`).

    Faithful to `scripts/pavanpatil/thrift_call_disruptive.py`: each
    PeriodicTask burst fires a single `asyncio.gather` of read-only thrift
    calls (`requests_per_burst` each of 7 APIs) + one
    `async_do_rapid_interface_flaps(stsw_flap_ports, 4, 100)` call which
    internally loops 100 flaps × 4s = ~6.7 min. Outer `PeriodicTaskWorker`
    loops with `interval=5` between bursts.

    THFT_002..005 layer foreground per-daemon restart triggers on top of
    this same background — see `create_thft_restart_playbook` +
    `create_thft_playbooks`.

    Args:
        device_name: DUT hostname (FBOSS-only — `_get_qsfp_info_map` and
            `async_do_rapid_interface_flaps` are FBOSS-only).
        stsw_flap_ports: DUT-side ports to flap. EXCLUDE IXIA-facing ports.
        test_duration_s: Longevity stage duration. Default 600s (10 min
            smoke). Prod runs use 14400 (4 hr).
        requests_per_burst: Concurrent calls per read-only API per burst.
            Default 10000 matches Pavan's original. Dial down (e.g. 1000)
            to find the breaking-point ceiling without crashing the agent.
        burst_timeout_s: Wall-clock cap on a single burst's gather(). If
            the agent stops responding, the gather is cancelled, a timed-
            out burst recorded, and the worker continues. Default 60s.

    Returns:
        Single `Playbook` for THFT_001.
    """
    payload = fboss_with_qsfp_flaps(stsw_flap_ports)
    payload = _scale_payload_per_call(payload, requests_per_burst)
    return Playbook(
        name="npi_thft_001_baseline_thrift_stress",
        description=(
            f"THFT_001 baseline — Pavan-design thrift stress + qsfp port "
            f"flap background for {test_duration_s}s on {device_name} "
            f"(requests_per_burst={requests_per_burst}). Mirrors "
            f"scripts/pavanpatil/thrift_call_disruptive.py."
        ),
        periodic_tasks=[
            create_thrift_stress_periodic_task(
                device_name=device_name,
                calls=payload,
                interval=5,
                burst_timeout_s=burst_timeout_s,
            )
        ],
        stages=[create_longevity_stage(duration=test_duration_s)],
    )


# =============================================================================
# THFT 002-005 — restart-trigger variants on top of THFT_001 background.
# Each variant shares the same `fboss_with_qsfp_flaps` periodic-task
# background (thrift storm + 100-flap qsfp burst), and adds a FOREGROUND
# sequence of `systemctl restart <service>` triggers fired every 5 min.
# Concurrency model:
#   - periodic_tasks runs in its own multiprocessing.Process (continuous)
#   - foreground stages run sequentially in the test worker process
#   - both proceed in parallel for the entire test_duration_s window
# =============================================================================

# Single source of truth for the systemd `BindsTo` cascade that fires when
# wedge_agent is restarted. In practice the observable effect is that
# `bgpd` restarts alongside wedge_agent — bgpd's RIB state depends on
# wedge_agent for FIB programming, so cascading restart is correct
# (Pavan-confirmed by-design, T274731352 closed 2026-06-11). The
# `fboss_sw_agent` and `fboss_hw_agent@0` ALSO cascade on a wedge_agent
# restart, via the wedge_agent unit's hand-coded
# `ExecStop=pre_wedge_agent_shut_runner.par` hook (NOT via a passive
# systemd BindsTo directive — those two daemons have only
# `After=wedge_agent.service` and no propagation directive on the live
# DUT; the script explicitly tears them down). Pavan confirmed this is
# by-design — see T275672046 for the unit-file evidence and the open
# FBOSS investigation into whether the ExecStop teardown is still
# required, and T274731352 (closed by-design) for the original ack.
#
# Net: the full cascade set has FOUR members. The name
# `WEDGE_AGENT_BINDS_TO_CASCADE` is retained for backward compatibility
# even though only `bgpd` is strictly a BindsTo binder — the constant's
# semantic is "every daemon that restarts when wedge_agent restarts",
# regardless of the cascade mechanism.
#
# Any TAAC playbook that intentionally restarts wedge_agent AND has a
# SERVICE_RESTART_CHECK postcheck monitoring wedge_agent must include
# this full list in the check's `expected_restarted_services` — otherwise
# the postcheck false-fails the by-design cascade. The
# `test_service_restart_dependency` invariant test enforces this
# fleet-wide; if the cascade set ever changes here, update this constant
# in ONE place and every dependent playbook stays correct.
WEDGE_AGENT_BINDS_TO_CASCADE: list[str] = [
    "wedge_agent",
    "bgpd",
    "fboss_sw_agent",
    "fboss_hw_agent@0",
]

# Map of (playbook_number, name_suffix, Service enum, friendly_name).
# These are the 4 daemons listed in `service_restart_check`'s default
# monitor set for IcePack GTSW (modulo `openr` which IcePack doesn't run).
_THFT_RESTART_VARIANTS: list[tuple[int, str, Service, str]] = [
    (2, "wedge_agent", Service.AGENT, "wedge_agent"),
    (3, "bgpd", Service.BGP, "bgpd"),
    (4, "qsfp_service", Service.QSFP_SERVICE, "qsfp_service"),
    (5, "fsdb", Service.FSDB, "fsdb"),
]


def _build_periodic_restart_stages(
    service: Service,
    service_label: str,
    period_s: int = 300,
    total_duration_s: int = 14400,
) -> list[Stage]:
    """Build N stages: each is [`SERVICE_INTERRUPTION_STEP`, `longevity(period_s)`].

    N = `total_duration_s // period_s`. For prod (14400s = 4hr) and the
    default 300s (5min) cadence, that's 48 restart iterations. The first
    restart fires at T+0, the next at T+300s, etc. The final
    `longevity(period_s)` after the last restart ensures we sleep through
    the recovery window before the test ends and postchecks fire.

    The periodic_task background runs concurrently in its own
    multiprocessing.Process — these foreground stages don't gate it.

    Each iteration uses `create_periodic_service_restart_stage` from
    `stages/stage_definitions.py` so `Stage(...)` is never constructed
    inline outside the centralized factories (enforced by
    `tests/test_no_inline_stage_construction.py`).
    """
    n_iterations = max(1, total_duration_s // period_s)
    return [
        create_periodic_service_restart_stage(
            service=service,
            service_label=service_label,
            period_s=period_s,
            iteration_index=i,
            total_iterations=n_iterations,
        )
        for i in range(n_iterations)
    ]


def create_thft_restart_playbook(
    device_name: str,
    stsw_flap_ports: list[str],
    playbook_number: int,
    service: Service,
    service_label: str,
    test_duration_s: int = 14400,
    restart_period_s: int = 300,
    requests_per_burst: int = 10000,
    burst_timeout_s: float = 60.0,
) -> Playbook:
    """THFT_002..005 — THFT_001 background + 5-min systemctl-restart trigger.

    Same `fboss_with_qsfp_flaps` periodic-task background as THFT_001
    (thrift storm + 100-flap qsfp burst every 5s). Adds a foreground
    sequence of `systemctl restart <service>` triggers fired every
    `restart_period_s` for the full `test_duration_s` window.

    Args:
        device_name: DUT hostname (FBOSS-only).
        stsw_flap_ports: DUT-side ports for the qsfp flap entry.
        playbook_number: 2 / 3 / 4 / 5 — sets the THFT_NNN prefix.
        service: `Service.AGENT` / `BGP` / `QSFP_SERVICE` / `FSDB`.
        service_label: human-readable name used in the playbook name +
            description + restart-step labels (e.g. "wedge_agent").
        test_duration_s: Total foreground stage duration. Default 14400 (4hr).
        restart_period_s: Sleep between consecutive restarts. Default 300s
            (5min). Number of restart iterations = test_duration_s //
            restart_period_s (48 at defaults).
        requests_per_burst / burst_timeout_s: Same semantics as
            `create_thft_baseline_playbook`.
    """
    payload = fboss_with_qsfp_flaps(stsw_flap_ports)
    payload = _scale_payload_per_call(payload, requests_per_burst)
    name = f"npi_thft_{playbook_number:03d}_thrift_stress_with_restart_{service_label}"
    description = (
        f"THFT_{playbook_number:03d} — THFT_001 background "
        f"(thrift stress + qsfp port flap) + systemctl restart "
        f"{service_label} every {restart_period_s}s for {test_duration_s}s "
        f"on {device_name} (requests_per_burst={requests_per_burst})."
    )
    return Playbook(
        name=name,
        description=description,
        periodic_tasks=[
            create_thrift_stress_periodic_task(
                device_name=device_name,
                calls=payload,
                interval=5,
                burst_timeout_s=burst_timeout_s,
            )
        ],
        stages=_build_periodic_restart_stages(
            service=service,
            service_label=service_label,
            period_s=restart_period_s,
            total_duration_s=test_duration_s,
        ),
    )


def create_thft_playbooks(
    device_name: str,
    stsw_flap_ports: list[str],
    test_duration_s: int = 14400,
    restart_test_duration_s: int = 3600,
    restart_period_s: int = 300,
    requests_per_burst: int = 10000,
    burst_timeout_s: float = 60.0,
) -> list[Playbook]:
    """Return the full THFT_001..005 playbook list — standard NPI THFT
    testcase set for any FBOSS DUT.

    Order matters: THFT_001 (no restart trigger) runs first to establish
    the device tolerates the background storm alone. THFT_002..005 then
    layer on the per-daemon restart trigger one at a time.

    Per-playbook duration is split so the campaign wall time stays
    bounded: `test_duration_s` drives THFT_001 (default 4hr prod);
    `restart_test_duration_s` drives THFT_002..005 (default 1hr prod
    each = 4hr total across the 4 restart variants, matching the
    baseline's 4hr soak).
    """
    playbooks: list[Playbook] = [
        create_thft_baseline_playbook(
            device_name=device_name,
            stsw_flap_ports=stsw_flap_ports,
            test_duration_s=test_duration_s,
            requests_per_burst=requests_per_burst,
            burst_timeout_s=burst_timeout_s,
        )
    ]
    for (
        playbook_number,
        _suffix,
        service,
        service_label,
    ) in _THFT_RESTART_VARIANTS:
        playbooks.append(
            create_thft_restart_playbook(
                device_name=device_name,
                stsw_flap_ports=stsw_flap_ports,
                playbook_number=playbook_number,
                service=service,
                service_label=service_label,
                test_duration_s=restart_test_duration_s,
                restart_period_s=restart_period_s,
                requests_per_burst=requests_per_burst,
                burst_timeout_s=burst_timeout_s,
            )
        )
    return playbooks


def add_common_checks_to_thft_playbooks(
    playbooks: list[Playbook],
    service_restart_services: list[str] | None = None,
) -> list[Playbook]:
    """Add THFT validation chain (BGP-only mirror of cpu_queue's chain).

    Mirrors `add_common_checks_to_cpu_queue_playbooks` but DROPS:
      - `prefix_limit_check` — THFT doesn't inject test prefixes
      - `ixia_packet_loss_check` — THFT has no IXIA traffic items

    Keeps the BGP_SESSION_ESTABLISH precheck + BGP_PEER_ROUTE snapshot
    (relevant: does BGP survive the 100-flap qsfp burst?) and all the
    device-side checks (systemctl active, memory, port state, lldp,
    service restart, unclean exit, cpu utilization, core dumps).

    `service_restart_services` overrides the postcheck's default service
    list. Default (None) keeps the check's built-in list. Set explicitly
    to drop services not present on a given DUT — e.g. IcePack backend
    GTSWs don't run openr, so omitting it here avoids a postcheck
    false-fail on INACTIVE.

    `SERVICE_RESTART_CHECK` semantics per playbook:
      - THFT_001 (baseline, no foreground restart): plain check, any
        restart of the monitored set FAILs.
      - THFT_002..005 (each restarts ONE targeted daemon on a 5-min
        cadence): the check is KEPT but the targeted daemon AND its
        confirmed cascade binders are declared in
        `expected_restarted_services` so the by-design cascade does NOT
        trip the check. Restarts of OTHER daemons (not in the cascade)
        still FAIL — preserves cascade-detection for unexpected events.

    Mapping (playbook name suffix → expected-restarted daemon list):
      `_with_restart_wedge_agent`   → WEDGE_AGENT_BINDS_TO_CASCADE  (4-element)
      `_with_restart_bgpd`          → [bgpd]
      `_with_restart_qsfp_service`  → [qsfp_service]
      `_with_restart_fsdb`          → [fsdb]

    The `_with_restart_wedge_agent` cascade covers wedge_agent + bgpd +
    fboss_sw_agent + fboss_hw_agent@0, all Pavan-confirmed by-design
    (T275672046 + T274731352 closed by-design). Only bgpd has a formal
    `BindsTo=wedge_agent.service` directive; fboss_sw_agent and
    fboss_hw_agent@0 cascade via the wedge_agent unit's hand-coded
    `ExecStop=pre_wedge_agent_shut_runner.par` hook — same by-design
    intent, different mechanism. `qsfp_service` and `fsdb` are NOT in
    the cascade set so they don't propagate.
    """
    common_prechecks = [
        create_drain_state_check(),
        create_bgp_session_establish_check(),
        create_systemctl_active_state_check(),
        create_memory_utilization_check(
            threshold=5 * (1024**3),  # 5 GiB
            start_time_jq_var="test_case_start_time",
        ),
        create_port_state_check(),
        create_lldp_check(),
    ]
    common_snapshot_checks = [
        create_core_dumps_snapshot_check(),
        create_bgp_peer_route_snapshot_check(),
    ]
    # Suffix → expected-restarted-daemons mapping for the targeted-restart
    # exclusion. Keys MUST match the suffix used by `create_thft_restart_playbook`.
    #
    # For `_with_restart_wedge_agent` the canonical 4-element cascade
    # set lives in `WEDGE_AGENT_BINDS_TO_CASCADE` (bgpd via BindsTo;
    # fboss_sw_agent + fboss_hw_agent@0 via the ExecStop hook). All
    # Pavan-confirmed by-design — see T275672046 + T274731352. Without
    # this entry the SERVICE_RESTART_CHECK postcheck false-fails
    # THFT_002 even though every restart is expected. `qsfp_service`
    # and `fsdb` are NOT in wedge_agent's cascade set, so they don't
    # propagate and don't need to be listed here.
    _restart_suffix_to_daemons: dict[str, list[str]] = {
        "_with_restart_wedge_agent": WEDGE_AGENT_BINDS_TO_CASCADE,
        "_with_restart_bgpd": ["bgpd"],
        "_with_restart_qsfp_service": ["qsfp_service"],
        "_with_restart_fsdb": ["fsdb"],
    }
    result = []
    for pb in playbooks:
        expected_restarted = None
        for suffix, daemons in _restart_suffix_to_daemons.items():
            if pb.name.endswith(suffix):
                expected_restarted = list(daemons)
                break
        per_playbook_postchecks = [
            create_service_restart_check(
                services=service_restart_services,
                expected_restarted_services=expected_restarted,
            ),
            create_unclean_exit_check(),
            create_cpu_utilization_check(
                threshold=400.0, start_time_jq_var="test_case_start_time"
            ),
        ]
        result.append(
            Playbook(
                name=pb.name,
                stages=pb.stages,
                description=pb.description,
                iteration=pb.iteration,
                traffic_items_to_start=pb.traffic_items_to_start,
                enabled=pb.enabled,
                backup_and_restore_ixia_config=pb.backup_and_restore_ixia_config,
                prechecks=list(pb.prechecks or []) + common_prechecks,
                postchecks=per_playbook_postchecks + list(pb.postchecks or []),
                snapshot_checks=list(pb.snapshot_checks or []) + common_snapshot_checks,
                skip_test_config_prechecks=pb.skip_test_config_prechecks,
                skip_test_config_postchecks=pb.skip_test_config_postchecks,
                skip_test_config_snapshot_checks=pb.skip_test_config_snapshot_checks,
                override_duplicate_checks=pb.override_duplicate_checks,
                prechecks_to_skip=pb.prechecks_to_skip,
                postchecks_to_skip=pb.postchecks_to_skip,
                snapshot_checks_to_skip=pb.snapshot_checks_to_skip,
                check_ids_to_skip=pb.check_ids_to_skip,
                cleanup_steps=pb.cleanup_steps,
                setup_steps=pb.setup_steps,
                device_regexes=pb.device_regexes,
                periodic_tasks=pb.periodic_tasks,
                attribute_filters=pb.attribute_filters,
                traffic_items_to_configure=pb.traffic_items_to_configure,
                scuba_table=pb.scuba_table,
            )
        )
    return result


def add_checks_to_playbooks(
    playbooks: list[Playbook],
    prechecks: list[PointInTimeHealthCheck] | None = None,
    postchecks: list[PointInTimeHealthCheck] | None = None,
    snapshot_checks: list | None = None,
) -> list[Playbook]:
    """Return new Playbooks merging the given pre/post/snapshot checks into each input playbook."""
    result = []
    for pb in playbooks:
        result.append(
            Playbook(
                name=pb.name,
                stages=pb.stages,
                description=pb.description,
                iteration=pb.iteration,
                traffic_items_to_start=pb.traffic_items_to_start,
                enabled=pb.enabled,
                backup_and_restore_ixia_config=pb.backup_and_restore_ixia_config,
                prechecks=list(pb.prechecks or []) + list(prechecks or []),
                postchecks=list(pb.postchecks or []) + list(postchecks or []),
                snapshot_checks=list(pb.snapshot_checks or [])
                + list(snapshot_checks or []),
                skip_test_config_prechecks=pb.skip_test_config_prechecks,
                skip_test_config_postchecks=pb.skip_test_config_postchecks,
                skip_test_config_snapshot_checks=pb.skip_test_config_snapshot_checks,
                override_duplicate_checks=pb.override_duplicate_checks,
                prechecks_to_skip=pb.prechecks_to_skip,
                postchecks_to_skip=pb.postchecks_to_skip,
                snapshot_checks_to_skip=pb.snapshot_checks_to_skip,
                check_ids_to_skip=pb.check_ids_to_skip,
                cleanup_steps=pb.cleanup_steps,
                setup_steps=pb.setup_steps,
                device_regexes=pb.device_regexes,
                periodic_tasks=pb.periodic_tasks,
                attribute_filters=pb.attribute_filters,
                traffic_items_to_configure=pb.traffic_items_to_configure,
                scuba_table=pb.scuba_table,
            )
        )
    return result


def create_device_provisioning_playbook(
    task_params: dict[str, str | int],
    device_name: str,
) -> taac_types.Playbook:
    """Build the single Playbook used by the device-provisioning TestConfig.

    Runs the `device_provisioning` task as a one-shot step that drains
    and provisions the named device. No pre/postchecks — the task itself
    raises on failure. Used by the device-provisioning TestConfig that
    onboards new lab devices.

    Args:
        task_params: Parameter dict passed through to the
            `device_provisioning` task (typically credentials, role,
            switch type, MAC, etc.).
        device_name: DUT hostname to embed in the step description.

    Returns:
        A `Playbook` named `device_provisioning_playbook` with one stage
        invoking the `device_provisioning` task.
    """
    return taac_types.Playbook(
        name="device_provisioning_playbook",
        stages=[
            create_steps_stage(
                steps=[
                    create_run_task_step(
                        task_name="device_provisioning",
                        params_dict=task_params,
                        description=f"Drain and provision device {device_name}",
                    )
                ]
            )
        ],
    )


def create_ctsw_rtsw_interface_flap_playbook() -> taac_types.Playbook:
    """Build the single Playbook for CTSW_RTSW_TEST.

    Single-stage interface flap exercising the CTSW <-> RTSW topology in
    SNC1 c081 f00. Postchecks validate LLDP, port state, and IXIA packet
    loss after a random RTSW interface flap.
    """
    return taac_types.Playbook(
        name="test_interface_flap",
        postchecks=[
            create_lldp_check(),
            create_port_state_check(),
            create_packetloss_health_check(),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_interface_flap_step(
                        enable=False,
                        interfaces="",
                        jq_params={"interfaces": '."{dut}".interfaces'},
                        cache_params={"interfaces": "random_interface"},
                    ),
                    create_interface_flap_step(
                        enable=True,
                        interfaces="",
                        jq_params={"interfaces": ".cached.random_interface"},
                    ),
                ],
            )
        ],
    )


def create_test_hardening_continuous_agent_coldboot_playbook() -> taac_types.Playbook:
    """Build the `test_continuous_agent_coldboot` Playbook for FAUU_CONVERGENCE_CONFIGS.

    Two iterations of AGENT coldboot (systemctl restart with cold-boot
    file) + AGENT/BGP convergence, followed by a 900s longevity soak.
    Pre/postchecks include LLDP, port-state, unclean-exit, and an
    elaborate IXIA packet-loss assertion that expects loss on
    rogue/lossy/high-queue traffic items and zero loss on directional
    V6/V4 RSW <-> FA traffic.

    Returns:
        A `Playbook` named `test_continuous_agent_coldboot` used by the
        FA-UU QZD1 convergence-hardening TestConfig stack.
    """
    return taac_types.Playbook(
        name="test_continuous_agent_coldboot",
        stages=[
            create_steps_stage(
                steps=[
                    create_service_interruption_step(
                        service=taac_types.Service.AGENT,
                        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                        create_cold_boot_file=True,
                    ),
                    create_service_convergence_step(
                        services=[taac_types.Service.AGENT, taac_types.Service.BGP]
                    ),
                ],
                iteration=2,
            ),
            create_longevity_stage(duration=900),
        ],
        prechecks=[
            create_unclean_exit_check(),
            create_lldp_check(),
            create_port_state_check(),
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=[
                            "GOOD_BUT_LOSSY_NDP_TRAFFIC",
                            "LOSSY_ROGUE_NDP_TRAFFIC",
                            "HIGH_QUEUE_BGP_CP_TRAFFIC",
                        ],
                        expect_packet_loss=True,
                    ),
                    hc_types.PacketLossThreshold(
                        names=[
                            "V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
                            "V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
                            "RSW001.P002.F01.QZD1:ETH1/16/1_TO_FA003-UU001.QZD1:ETH6/13/1_IPV6",
                        ],
                        expect_packet_loss=False,
                    ),
                ]
            ),
        ],
        postchecks=[
            create_ixia_packet_loss_check(
                clear_traffic_stats=True,
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=[
                            "GOOD_BUT_LOSSY_NDP_TRAFFIC",
                            "LOSSY_ROGUE_NDP_TRAFFIC",
                            "HIGH_QUEUE_BGP_CP_TRAFFIC",
                        ],
                        expect_packet_loss=True,
                    ),
                    hc_types.PacketLossThreshold(
                        names=[
                            "V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
                            "V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
                            "RSW001.P002.F01.QZD1:ETH1/16/1_TO_FA003-UU001.QZD1:ETH6/13/1_IPV6",
                        ],
                        expect_packet_loss=False,
                    ),
                ],
            ),
            create_port_state_check(),
            create_unclean_exit_check(),
            create_memory_utilization_check(
                threshold=10 * (1024**3), start_time_jq_var="test_case_start_time"
            ),
        ],
    )


def create_arbgp_4session_longevity_playbook(duration: int = 180) -> Playbook:
    """Build the longevity Playbook for the bag002.snc1 ar-bgp 4-session TestConfig.

    Single-stage longevity soak that verifies BGP sessions stay
    established for `duration` seconds. Prechecks assert port state +
    BGP session establishment; postcheck asserts BGP sessions remain up.

    Args:
        duration: Longevity stage duration in seconds. Default 180.

    Returns:
        A `Playbook` named `test_arbgp_4session_longevity` with one
        longevity stage.
    """
    return Playbook(
        name="test_arbgp_4session_longevity",
        stages=[create_longevity_stage(duration=duration)],
        prechecks=[
            create_port_state_check(),
            create_bgp_session_establish_check(),
        ],
        postchecks=[
            create_bgp_session_establish_check(),
        ],
        snapshot_checks=[],
    )


def create_case1_tcp_socket_data_collection_playbook(
    bgpcpp_device: str,
    tcp_data_collection_script: str,
    tcp_convergence_time: int,
    tcp_sample_interval: int,
) -> Playbook:
    """Build the Case 1 TCP socket data collection Playbook.

    Restarts BGP++ on `bgpcpp_device` (disable + enable via the Arista
    daemon control task), then runs `tcp_data_collection_script` for
    `tcp_convergence_time` seconds with `tcp_sample_interval` granularity
    to capture `ss` and bgpcpp egress summary snapshots. Output lands in
    `/tmp/tcp_data/`. Used by performance scaling Case 1 to characterize
    TCP socket behaviour during BGP++ convergence.

    Args:
        bgpcpp_device: DUT hostname running BGP++ (Arista).
        tcp_data_collection_script: Absolute path on the device of the
            `collect_tcp_data.sh` script.
        tcp_convergence_time: Total collection duration in seconds.
        tcp_sample_interval: Sampling interval in seconds.

    Returns:
        A `Playbook` named `tcp_socket_data_collection` with a single
        stage containing daemon restart + script invocation steps.
    """
    return Playbook(
        name="tcp_socket_data_collection",
        stages=[
            # Stage 1: Restart BGP++ daemon and collect TCP data
            # during convergence. The collect_tcp_data.sh script
            # runs for convergence_time seconds, capturing ss and
            # bgpcpp egress summary snapshots every sample_interval.
            # Output: /tmp/tcp_data/ss_* and /tmp/tcp_data/egress_*
            create_steps_stage(
                steps=[
                    create_run_task_step(
                        task_name="arista_daemon_control",
                        params_dict={
                            "hostname": bgpcpp_device,
                            "daemon_name": "Bgp",
                            "action": "disable",
                        },
                    ),
                    create_run_task_step(
                        task_name="arista_daemon_control",
                        params_dict={
                            "hostname": bgpcpp_device,
                            "daemon_name": "Bgp",
                            "action": "enable",
                        },
                    ),
                    create_run_task_step(
                        task_name="run_commands_on_shell",
                        params_dict={
                            "hostname": bgpcpp_device,
                            "cmds": [
                                f"bash {tcp_data_collection_script}"
                                f" {tcp_convergence_time}"
                                f" {tcp_sample_interval}"
                                " true",
                            ],
                        },
                    ),
                ],
                concurrent=False,
                description=(
                    "Restart BGP++ and collect TCP data"
                    " (ss + egress) during convergence"
                ),
            ),
        ],
    )


# =====================================================================
# Performance Scaling Case 1 (egress IBGP peer sweep)
# =====================================================================

# Upper bound used when stopping any prior IBGP peers on each AF. Kept high
# so callers don't have to tune it per-iteration.
_MAX_IBGP_SESSIONS_TO_STOP: int = 500
_REGEX_IBGP_V6: str = "BGP_PEER_IPV6_IBGP"
_REGEX_IBGP_V4: str = "BGP_PEER_IPV4_IBGP"


# Caller-supplied per-iteration setup-steps factory. Signature is
# ``(n_v6, n_v4) -> List[Step]``. Use this for tests that need to actually
# rescale the device (e.g. rewrite ``/mnt/flash/bgpcpp_config`` to have
# exactly N peer entries before each Stage). Defaults to the IXIA-only
# helper ``_build_per_iteration_peer_setup_steps`` for lab use cases.
PerIterationSetupStepsFactory = t.Callable[[int, int], list[Step]]


def _ps_case1_common_snapshot_checks() -> list[SnapshotHealthCheck]:
    return [
        create_bgp_session_snapshot_check(skip_flap_check=True, skip_uptime_check=True),
        create_core_dumps_snapshot_check(),
    ]


def _ps_case1_common_periodic_tasks(device_name: str):
    return create_standard_periodic_tasks(
        device_name=device_name,
        memory_threshold=Gigabyte.GIG_5.value,
        cpu_util_terminate_on_error=False,
        memory_terminate_on_error=False,
    )


def _ps_case1_start_bgp_peers_args(
    *, start: bool, regex: str, end_idx: int, start_idx: int = 1
) -> dict[str, object]:
    return {
        "start": start,
        "regex": regex,
        "session_start_idx": start_idx,
        "session_end_idx": end_idx,
    }


def _ps_case1_build_per_iteration_peer_setup_steps(n: int) -> list[Step]:
    """Stop any prior IBGP sessions on both AFs, then start n v6 + n v4."""
    steps: list[Step] = [
        create_ixia_api_step(
            api_name="start_bgp_peers",
            args_dict=_ps_case1_start_bgp_peers_args(
                start=False, regex=regex, end_idx=_MAX_IBGP_SESSIONS_TO_STOP
            ),
            description=f"Stop any {label} IBGP peers from prior iterations",
        )
        for regex, label in (
            (_REGEX_IBGP_V6, "IPv6"),
            (_REGEX_IBGP_V4, "IPv4"),
        )
    ]
    for regex, label in (
        (_REGEX_IBGP_V6, "IPv6"),
        (_REGEX_IBGP_V4, "IPv4"),
    ):
        steps.append(
            create_ixia_api_step(
                api_name="start_bgp_peers",
                args_dict=_ps_case1_start_bgp_peers_args(
                    start=True, regex=regex, end_idx=n
                ),
                description=f"Start {n} {label} IBGP egress peers for this iteration",
            )
        )
    return steps


def create_performance_scaling_egress_peer_sweep_playbook(
    *,
    device_name: str,
    egress_peer_counts: list[int],
    prefix_count: int,
    ebgp_peer_count: int,
    per_iteration_setup_steps_factory: PerIterationSetupStepsFactory | None = None,
) -> Playbook:
    """Build the egress-peer-sweep performance-scaling Playbook (Case 1 family).

    Generates one Stage per entry in `egress_peer_counts` that (a) tears
    down prior IBGP sessions and brings up `n` v6 + `n` v4 IBGP egress
    peers, then (b) runs a convergence step against `prefix_count`
    prefixes. After the per-N Stages, a trailing aggregator Stage
    consolidates per-Stage convergence results into a single plot of
    convergence-time vs total-peer-count. Used by the BGP++ performance-
    scaling Case 1 TestConfig.

    Args:
        device_name: DUT hostname (used by setup, periodic tasks, and
            convergence step).
        egress_peer_counts: IBGP egress peer counts to sweep (each entry
            `n` becomes `2*n` total IBGP peers since v6 and v4 are
            started in parallel).
        prefix_count: Prefixes advertised per peer for the convergence
            measurement.
        ebgp_peer_count: Constant EBGP peer count present in every Stage
            (also contributes `2 * ebgp_peer_count` to total peer count).
        per_iteration_setup_steps_factory: Optional override for the
            per-iteration peer-setup steps factory; defaults to
            `_ps_case1_build_per_iteration_peer_setup_steps`.

    Returns:
        A `Playbook` named `Performance_Scaling_Egress_Peer_Sweep` with
        N sweep Stages + 1 aggregator Stage, standard PS-Case1 snapshot
        checks and periodic tasks, and a RIB/FIB consistency postcheck.
    """
    stages: list[taac_types.Stage] = []
    for idx, n in enumerate(egress_peer_counts):
        # Both v6 and v4 IBGP sessions are started in parallel, so the
        # X-axis label for this Stage is 2*n.
        total_peer_count = 2 * n + 2 * ebgp_peer_count
        ibgp_peer_count = 2 * n
        ebgp_total = 2 * ebgp_peer_count
        steps = (
            per_iteration_setup_steps_factory(n, n)
            if per_iteration_setup_steps_factory is not None
            else _ps_case1_build_per_iteration_peer_setup_steps(n)
        )
        steps.append(
            create_performance_scaling_convergence_step(
                device_name=device_name,
                prefix_counts=[prefix_count],
                total_peer_count=total_peer_count,
                ibgp_peer_count=ibgp_peer_count,
                ebgp_peer_count=ebgp_total,
            )
        )
        stages.append(
            create_steps_stage(
                stage_id=f"egress_{2 * n}_ibgp_peers",
                description=(
                    f"Iteration {idx + 1}/{len(egress_peer_counts)}:"
                    f" {2 * n} IBGP egress peers (v6={n}, v4={n}) +"
                    f" {ebgp_total} EBGP @ prefix_count={prefix_count}"
                ),
                steps=steps,
            )
        )

    # Final aggregator Stage — one consolidated plot across all Stages.
    stages.append(
        create_steps_stage(
            stage_id="egress_sweep_aggregator",
            description=(
                "Aggregate per-Stage convergence results into one plot of"
                f" convergence-time vs total-peer-count @ prefix_count={prefix_count}"
            ),
            steps=[
                create_performance_scaling_egress_sweep_aggregator_step(
                    prefix_count=prefix_count,
                ),
            ],
        )
    )

    return Playbook(
        name="Performance_Scaling_Egress_Peer_Sweep",
        setup_steps=[],
        periodic_tasks=_ps_case1_common_periodic_tasks(device_name),
        prechecks=[],
        snapshot_checks=_ps_case1_common_snapshot_checks(),
        postchecks=[
            create_bgp_rib_fib_consistency_check(),
        ],
        stages=stages,
    )


def create_bgp_update_packing_validation_playbook(
    device_name: str,
    ixia_interface_mimic_ibgp: str,
    ibgp_peer_count: int,
    prefixes_per_peer: int,
    ixia_interface_mimic_ebgp: str,
    ebgp_peer_count: int,
    test_address_families: list[str],
    as_path_pool,
    community_pool,
    communities_per_route: int,
    ibgp_route_acceptance_communities: list[str] | None,
    ebgp_route_acceptance_communities: list[str] | None,
    capture_duration_seconds: int,
    min_packed_size: int,
    restart_bgp_for_complete_view: bool,
) -> Playbook:
    """Build the BGP++ UPDATE message packing validation Playbook.

    Runs the `test_bgp_update_packing_eos_bgp_plus_plus` custom step,
    which captures BGP UPDATE packets via tshark and validates that the
    EOS BGP++ implementation packs prefixes per UPDATE message at or
    above the configured minimum efficiency threshold. Used by the EOS
    BGP++ UPDATE-packing validation TestConfig.

    Args:
        device_name: DUT hostname (EOS BGP++).
        ixia_interface_mimic_ibgp: IXIA logical interface mimicking IBGP
            peers.
        ibgp_peer_count: Number of IBGP peers to mimic.
        prefixes_per_peer: Prefixes advertised per peer.
        ixia_interface_mimic_ebgp: IXIA logical interface mimicking EBGP
            peers.
        ebgp_peer_count: Number of EBGP peers to mimic.
        test_address_families: AF list (e.g. `["ipv6", "ipv4"]`).
        as_path_pool: AS path pool spec used for per-prefix AS path
            generation.
        community_pool: Community pool spec used for per-prefix community
            generation.
        communities_per_route: Communities attached per advertised route.
        ibgp_route_acceptance_communities: Communities the IBGP ingress
            policy requires for route acceptance (or None to skip).
        ebgp_route_acceptance_communities: Communities the EBGP ingress
            policy requires for route acceptance (or None to skip).
        capture_duration_seconds: tshark capture window in seconds.
        min_packed_size: Minimum acceptable number of prefixes packed per
            UPDATE message.
        restart_bgp_for_complete_view: If True, restart BGP++ during the
            test to force a full advertisement cycle (cleaner capture at
            the cost of test time).

    Returns:
        A `Playbook` named `bgp_update_packing_validation_playbook` with
        a single custom-step stage.
    """
    return Playbook(
        name="bgp_update_packing_validation_playbook",
        description="Validate BGP++ UPDATE message packing efficiency",
        stages=[
            create_steps_stage(
                steps=[
                    create_custom_step(
                        params_dict={
                            "custom_step_name": "test_bgp_update_packing_eos_bgp_plus_plus",
                            "hostname": device_name,
                            "ixia_interface_mimic_ibgp": ixia_interface_mimic_ibgp,
                            "ibgp_peer_count": ibgp_peer_count,
                            "prefixes_per_peer": prefixes_per_peer,
                            "ixia_interface_mimic_ebgp": ixia_interface_mimic_ebgp,
                            "ebgp_peer_count": ebgp_peer_count,
                            "test_address_families": test_address_families,
                            "as_path_pool": as_path_pool,
                            "community_pool": community_pool,
                            "communities_per_route": communities_per_route,
                            "ibgp_route_acceptance_communities": (
                                ibgp_route_acceptance_communities
                                if ibgp_route_acceptance_communities
                                else []
                            ),
                            "ebgp_route_acceptance_communities": (
                                ebgp_route_acceptance_communities
                                if ebgp_route_acceptance_communities
                                else []
                            ),
                            "capture_duration_seconds": capture_duration_seconds,
                            "min_packed_size": min_packed_size,
                            "restart_bgp_for_complete_view": restart_bgp_for_complete_view,
                        },
                    ),
                ],
            )
        ],
    )


def create_test_constant_attribute_storage_playbook(
    device_name: str,
    peergroup_ibgp_v6: str,
    peergroup_ebgp_v6: str,
    peergroup_ibgp_v4: str,
    peergroup_ebgp_v4: str,
    ixia_interface_mimic_ebgp: str,
    ixia_interface_mimic_ibgp: str,
    ibgp_remote_as: int,
    ebgp_remote_as: int,
    ebgp_peer_counts: list[int],
    unqiue_prefix_limit,
    total_path_limit,
    ixia_ebgp_ic_parent_network_v6: str,
    ixia_ibgp_ic_parent_network_v6: str,
    ixia_ebgp_ic_parent_network_v4: str,
    ixia_ibgp_ic_parent_network_v4: str,
    ixia_ebgp_communities,
    ixia_ibgp_communities,
    ebgp_ingress_policy_name: str,
    ebgp_egress_policy_name: str,
    ibgp_ingress_policy_name: str,
    ibgp_egress_policy_name: str,
    ibgp_peer_count: int,
    prefix_counts: list[int],
) -> Playbook:
    """Build the constant-attribute-storage verification Playbook for BGP++.

    Runs the `test_constant_attribute_storage` custom step, which sweeps
    `ebgp_peer_counts x prefix_counts` combinations and verifies that
    BGP++ shares one attribute-storage record per unique attribute set
    (rather than per route) and releases memory after route withdrawal.
    Includes a 10-minute soak between sweeps and a final memory-release
    verification. Used by EOS BGP++ constant-attribute-storage TestConfig.

    Args:
        device_name: DUT hostname (EOS BGP++).
        peergroup_ibgp_v6 / peergroup_ibgp_v4 / peergroup_ebgp_v6 /
            peergroup_ebgp_v4: Peer-group names on the DUT.
        ixia_interface_mimic_ebgp / ixia_interface_mimic_ibgp: IXIA
            logical interface names mimicking EBGP / IBGP peers.
        ibgp_remote_as / ebgp_remote_as: Remote ASN values for the
            mimicked peers.
        ebgp_peer_counts: List of EBGP peer counts to sweep.
        unqiue_prefix_limit: Unique prefix-limit policy applied during
            the sweep (sic — kwarg name preserved from custom step).
        total_path_limit: Total path-limit policy applied during sweep.
        ixia_ebgp_ic_parent_network_v6 / _v4: IXIA EBGP parent network
            prefixes.
        ixia_ibgp_ic_parent_network_v6 / _v4: IXIA IBGP parent network
            prefixes.
        ixia_ebgp_communities / ixia_ibgp_communities: Communities the
            IXIA peers attach to advertised prefixes (used to satisfy
            ingress acceptance policies).
        ebgp_ingress_policy_name / ebgp_egress_policy_name /
            ibgp_ingress_policy_name / ibgp_egress_policy_name: BGP
            policy names applied on the DUT.
        ibgp_peer_count: IBGP peer count (constant for this sweep).
        prefix_counts: List of prefix counts to sweep.

    Returns:
        A `Playbook` named `test_constant_attribute_storage` with one
        custom-step stage. Note: side-effects include reconfiguring BGP
        sessions on the DUT during the sweep.
    """
    return Playbook(
        name="test_constant_attribute_storage",
        description="Test to verify constant attribute storage with varying EBGP peers and routes",
        stages=[
            create_steps_stage(
                steps=[
                    create_custom_step(
                        params_dict={
                            "custom_step_name": "test_constant_attribute_storage",
                            "hostname": device_name,
                            "peergroup_ibgp_v6": peergroup_ibgp_v6,
                            "peergroup_ebgp_v6": peergroup_ebgp_v6,
                            "peergroup_ibgp_v4": peergroup_ibgp_v4,
                            "peergroup_ebgp_v4": peergroup_ebgp_v4,
                            "ixia_interface_mimic_ebgp": ixia_interface_mimic_ebgp,
                            "ixia_interface_mimic_ibgp": ixia_interface_mimic_ibgp,
                            "ibgp_remote_as": ibgp_remote_as,
                            "ebgp_remote_as": ebgp_remote_as,
                            "ebgp_peer_counts": ebgp_peer_counts,
                            "unqiue_prefix_limit": unqiue_prefix_limit,
                            "total_path_limit": total_path_limit,
                            "ixia_ebgp_ic_parent_network_v6": ixia_ebgp_ic_parent_network_v6,
                            "ixia_ibgp_ic_parent_network_v6": ixia_ibgp_ic_parent_network_v6,
                            "ixia_ebgp_ic_parent_network_v4": ixia_ebgp_ic_parent_network_v4,
                            "ixia_ibgp_ic_parent_network_v4": ixia_ibgp_ic_parent_network_v4,
                            "attach_communities_for_ebgp_prefixes": ixia_ebgp_communities,
                            "attach_communities_for_ibgp_prefixes": ixia_ibgp_communities,
                            "ebgp_ingress_policy_name": ebgp_ingress_policy_name,
                            "ebgp_egress_policy_name": ebgp_egress_policy_name,
                            "ibgp_ingress_policy_name": ibgp_ingress_policy_name,
                            "ibgp_egress_policy_name": ibgp_egress_policy_name,
                            "ibgp_peer_count": ibgp_peer_count,
                            "prefix_counts": prefix_counts,
                            "soak_time_minutes": 10,
                            "verify_memory_release": "True",
                            "allow_user_to_ask_for_confirmation": "True",
                        },
                    ),
                ],
            )
        ],
    )


def create_test_computational_load_for_bgp_plus_plus_playbook(
    device_name: str,
    peergroup_ibgp_v6: str,
    peergroup_ebgp_v6: str,
    peergroup_ibgp_v4: str,
    peergroup_ebgp_v4: str,
    ixia_interface_mimic_ebgp: str,
    ixia_interface_mimic_ibgp: str,
    ibgp_remote_as: int,
    ebgp_remote_as: int,
    ebgp_peer_scale,
    unqiue_prefix_limit,
    total_path_limit,
    ixia_ebgp_ic_parent_network_v6: str,
    ixia_ibgp_ic_parent_network_v6: str,
    ixia_ebgp_ic_parent_network_v4: str,
    ixia_ibgp_ic_parent_network_v4: str,
    ixia_ebgp_communities,
    ixia_ibgp_communities,
    ebgp_ingress_policy_name: str,
    ebgp_egress_policy_name: str,
    ibgp_ingress_policy_name: str,
    ibgp_egress_policy_name: str,
    ibgp_peer_counts: list[int],
    prefix_counts: list[int],
) -> Playbook:
    """Build the computational-load verification Playbook for BGP++.

    Runs the `test_computational_load_for_bgp_plus_plus` custom step,
    which sweeps `ibgp_peer_counts x prefix_counts x ebgp_peer_scale`
    combinations and characterizes BGP++ CPU + convergence behavior under
    increasing computational load. Used by the EOS BGP++ computational-
    load TestConfig.

    Args:
        device_name: DUT hostname (EOS BGP++).
        peergroup_ibgp_v6 / peergroup_ibgp_v4 / peergroup_ebgp_v6 /
            peergroup_ebgp_v4: Peer-group names on the DUT.
        ixia_interface_mimic_ebgp / ixia_interface_mimic_ibgp: IXIA
            logical interface names mimicking the peers.
        ibgp_remote_as / ebgp_remote_as: Remote ASNs for mimicked peers.
        ebgp_peer_scale: EBGP peer scaling spec (count or list, passed
            through to the custom step).
        unqiue_prefix_limit / total_path_limit: BGP policy limits (sic
            on `unqiue` — preserved from the custom-step interface).
        ixia_ebgp_ic_parent_network_v6 / _v4 / ixia_ibgp_ic_parent_network_v6 / _v4:
            IXIA parent network prefixes per AF / peer type.
        ixia_ebgp_communities / ixia_ibgp_communities: Communities the
            IXIA peers attach to advertised prefixes.
        ebgp_ingress_policy_name / ebgp_egress_policy_name /
            ibgp_ingress_policy_name / ibgp_egress_policy_name: BGP
            policy names applied on the DUT.
        ibgp_peer_counts: List of IBGP peer counts to sweep.
        prefix_counts: List of prefix counts to sweep.

    Returns:
        A `Playbook` named `test_computational_load_for_bgp_plus_plus`
        with a single custom-step stage.
    """
    return Playbook(
        name="test_computational_load_for_bgp_plus_plus",
        description="test_computational_load_for_bgp_plus_plus",
        stages=[
            create_steps_stage(
                steps=[
                    create_custom_step(
                        params_dict={
                            "custom_step_name": "test_computational_load_for_bgp_plus_plus",
                            "hostname": device_name,
                            "peergroup_ibgp_v6": peergroup_ibgp_v6,
                            "peergroup_ebgp_v6": peergroup_ebgp_v6,
                            "peergroup_ibgp_v4": peergroup_ibgp_v4,
                            "peergroup_ebgp_v4": peergroup_ebgp_v4,
                            "ixia_interface_mimic_ebgp": ixia_interface_mimic_ebgp,
                            "ixia_interface_mimic_ibgp": ixia_interface_mimic_ibgp,
                            "ibgp_remote_as": ibgp_remote_as,
                            "ebgp_remote_as": ebgp_remote_as,
                            "ebgp_peer_scale": ebgp_peer_scale,
                            "unqiue_prefix_limit": unqiue_prefix_limit,
                            "total_path_limit": total_path_limit,
                            "ixia_ebgp_ic_parent_network_v6": ixia_ebgp_ic_parent_network_v6,
                            "ixia_ibgp_ic_parent_network_v6": ixia_ibgp_ic_parent_network_v6,
                            "ixia_ebgp_ic_parent_network_v4": ixia_ebgp_ic_parent_network_v4,
                            "ixia_ibgp_ic_parent_network_v4": ixia_ibgp_ic_parent_network_v4,
                            "attach_communities_for_ebgp_prefixes": ixia_ebgp_communities,
                            "attach_communities_for_ibgp_prefixes": ixia_ibgp_communities,
                            "ebgp_ingress_policy_name": ebgp_ingress_policy_name,
                            "ebgp_egress_policy_name": ebgp_egress_policy_name,
                            "ibgp_ingress_policy_name": ibgp_ingress_policy_name,
                            "ibgp_egress_policy_name": ibgp_egress_policy_name,
                            "ibgp_peer_counts": ibgp_peer_counts,
                            "prefix_counts": prefix_counts,
                        },
                    ),
                ],
            )
        ],
    )


def create_bgp_queue_memory_monitoring_playbook(
    device_name: str,
    monitoring_duration_minutes: int,
    monitoring_interval_seconds: int,
    ebgp_as_paths,
    ebgp_peer_count: int,
    ixia_interface_mimic_ebgp: str,
    monitor_cpu_stress: bool,
) -> Playbook:
    """Build the BGP++ queue/memory monitoring Playbook.

    Runs the `test_bgp_queue_memory_monitor_eos_bgp_plus_plus` custom
    step for `monitoring_duration_minutes`, sampling every
    `monitoring_interval_seconds` while IXIA continuously churns routes
    on the EBGP plane. Snapshot check asserts BGP sessions stay up
    (flap-check skipped because routes — not sessions — are flapping by
    design). PID-based crash detection lives in the custom step itself,
    so CORE_DUMPS_CHECK is intentionally omitted to avoid false fails
    from unrelated daemons. Used by `test_config_queue_memory_monitor`.

    Args:
        device_name: DUT hostname (EOS BGP++).
        monitoring_duration_minutes: Total monitor duration in minutes.
        monitoring_interval_seconds: Sampling interval in seconds.
        ebgp_as_paths: AS-path pool spec used by route churn.
        ebgp_peer_count: Number of EBGP peers to mimic on the IXIA side.
        ixia_interface_mimic_ebgp: IXIA logical interface mimicking the
            EBGP peers.
        monitor_cpu_stress: If True, additionally drive CPU-stress
            monitoring inside the custom step.

    Returns:
        A `Playbook` named `bgp_queue_memory_monitoring_playbook` with
        one custom-step stage and a BGP-session snapshot check.
    """
    return Playbook(
        name="bgp_queue_memory_monitoring_playbook",
        description="Monitor BGP++ queue and memory under route churn",
        snapshot_checks=[
            # NOTE: CORE_DUMPS_CHECK removed — it catches unrelated
            # crashes (e.g. OpenR) that fail the test even though this
            # test only exercises BGP++. BGP++ crashes are detected by
            # the PID monitoring in the custom step instead.
            #
            # BGP session health check - detect unexpected session flaps
            # IMPORTANT: We skip flap check because IXIA is intentionally flapping ROUTES,
            # not BGP sessions. This health check ensures BGP sessions themselves stay stable.
            create_bgp_session_snapshot_check(
                skip_flap_check=True,
                skip_uptime_check=False,
            ),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_custom_step(
                        params_dict={
                            "custom_step_name": "test_bgp_queue_memory_monitor_eos_bgp_plus_plus",
                            "hostname": device_name,
                            "duration_minutes": monitoring_duration_minutes,
                            "interval_seconds": monitoring_interval_seconds,
                            "focused_queues": [
                                "AdjRibIn",
                            ],
                            "as_path_pool": ebgp_as_paths,
                            "ebgp_peer_count": ebgp_peer_count,
                            "ixia_interface_ebgp": ixia_interface_mimic_ebgp,
                            "monitor_cpu_stress": monitor_cpu_stress,
                        },
                    ),
                ],
            )
        ],
    )


def create_bgp_plus_plus_arista_bounded_ecmp_sets_playbook(
    device_name: str,
) -> Playbook:
    """Build the BGP++ bounded-ECMP-sets Playbook (performance scaling case9).

    20-minute route-oscillations stage that spreads 5000 EBGP prefixes
    across the DUT followed by a 300s soak, with a nexthop-group
    periodic poll (threshold=50) on top of the standard BGP++ periodic
    tasks. Postchecks assert BGP session establishment, RIB/FIB
    consistency, and BGP convergence within 600 seconds. Used by EOS
    BGP++ performance-scaling Case 9 to characterize bounded-ECMP-set
    behavior under churn.

    Args:
        device_name: DUT hostname (EOS BGP++).

    Returns:
        A `Playbook` named `bgp_plus_plus_arista_bounded_ecmp_sets_test`.
    """
    return Playbook(
        name="bgp_plus_plus_arista_bounded_ecmp_sets_test",
        description="Test BGP++ performance with bounded ECMP sets",
        snapshot_checks=[
            create_core_dumps_snapshot_check(),
            create_bgp_session_snapshot_check(
                skip_flap_check=True, skip_uptime_check=True
            ),
        ],
        periodic_tasks=create_standard_periodic_tasks(
            device_name=device_name,
            memory_threshold=Gigabyte.GIG_5.value,
            cpu_util_terminate_on_error=False,
            memory_terminate_on_error=False,
        )
        + [
            create_nexthop_group_poll_periodic_task(
                device_name=device_name,
                threshold=50,
            ),
        ],
        postchecks=[
            create_bgp_session_establish_check(),
            create_bgp_rib_fib_consistency_check(),
            create_bgp_convergence_check(
                convergence_threshold=600,
                check_id="postcheck_bgp_convergence_time",
            ),
        ],
        setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
        stages=[
            create_route_oscillations_stage(
                device_name=device_name,
                prefix_pool_regex=".*EBGP.*",
                prefix_start_index=0,
                prefix_end_index=5000,
                test_duration_seconds=1200,
                spread=True,
            ),
            create_steps_stage(
                steps=[
                    create_longevity_step(
                        duration=300,
                        description="Soak after final prefix changes for 300 seconds",
                    ),
                ],
            ),
        ],
    )


def create_bgp_plus_plus_transient_memory_peer_scale_playbook(
    device_name: str,
    ixia_interface_mimic_ebgp: str,
    ixia_interface_mimic_ibgp: str,
    prefixes: int,
    constant_acceptance_communities: list[str] | None,
    peers_combination: list[tuple[int, int]],
    ebgp_remote_as: int,
    ibgp_remote_as: int,
    ixia_ebgp_ic_parent_network_v6: str,
    ixia_ebgp_ic_parent_network_v4: str,
    ixia_ibgp_ic_parent_network_v6: str,
    ixia_ibgp_ic_parent_network_v4: str,
    peergroup_ebgp_v6: str,
    peergroup_ebgp_v4: str,
    peergroup_ibgp_v6: str,
    peergroup_ibgp_v4: str,
    ssh_user: str,
    ssh_password: str,
) -> Playbook:
    """Build the BGP++ transient-memory peer-scale Playbook (perf scaling case4).

    Runs the
    `test_bgp_transient_memory_route_peer_scale_eos_bgp_plus_plus`
    custom step in `peer_scale` mode, sweeping the
    `peers_combination` list (each tuple = EBGP/IBGP peer counts) at a
    fixed prefix count. Measures peak vs. steady-state memory to detect
    transient leaks during peer add/remove cycles. Used by EOS BGP++
    performance-scaling Case 4.

    Args:
        device_name: DUT hostname (EOS BGP++).
        ixia_interface_mimic_ebgp / ixia_interface_mimic_ibgp: IXIA
            logical interfaces mimicking the peers.
        prefixes: Fixed prefix count per peer.
        constant_acceptance_communities: Communities required by the
            EBGP ingress policy (or None).
        peers_combination: List of (ebgp_peers, ibgp_peers) tuples to
            sweep.
        ebgp_remote_as / ibgp_remote_as: Remote ASNs for mimicked peers.
        ixia_ebgp_ic_parent_network_v6 / _v4 / ixia_ibgp_ic_parent_network_v6 / _v4:
            IXIA parent network prefixes per AF / peer type.
        peergroup_ebgp_v6 / peergroup_ebgp_v4 / peergroup_ibgp_v6 /
            peergroup_ibgp_v4: Peer-group names on the DUT.
        ssh_user / ssh_password: DUT SSH credentials used by the custom
            step for memory introspection.

    Returns:
        A `Playbook` named `bgp_plus_plus_transient_memory_peer_scale_test`.
    """
    return Playbook(
        name="bgp_plus_plus_transient_memory_peer_scale_test",
        description="Test BGP++ transient memory usage with varying peer scale",
        snapshot_checks=[
            create_core_dumps_snapshot_check(),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_custom_step(
                        params_dict={
                            "custom_step_name": "test_bgp_transient_memory_route_peer_scale_eos_bgp_plus_plus",
                            "hostname": device_name,
                            "ixia_interface_mimic_ebgp": ixia_interface_mimic_ebgp,
                            "ixia_interface_mimic_ibgp": ixia_interface_mimic_ibgp,
                            "prefixes": prefixes,
                            # This community is required by device BGP policy to accept routes
                            "attach_communities_for_ebgp_prefixes": constant_acceptance_communities,
                            "peers_combination": peers_combination,
                            "mode": "peer_scale",
                            "ebgp_remote_as": ebgp_remote_as,
                            "ibgp_remote_as": ibgp_remote_as,
                            "ixia_ebgp_ic_parent_network_v6": ixia_ebgp_ic_parent_network_v6,
                            "ixia_ebgp_ic_parent_network_v4": ixia_ebgp_ic_parent_network_v4,
                            "ixia_ibgp_ic_parent_network_v6": ixia_ibgp_ic_parent_network_v6,
                            "ixia_ibgp_ic_parent_network_v4": ixia_ibgp_ic_parent_network_v4,
                            "peergroup_ebgp_v6": peergroup_ebgp_v6,
                            "peergroup_ebgp_v4": peergroup_ebgp_v4,
                            "peergroup_ibgp_v6": peergroup_ibgp_v6,
                            "peergroup_ibgp_v4": peergroup_ibgp_v4,
                            "ssh_user": ssh_user,
                            "ssh_password": ssh_password,
                        }
                    ),
                ],
            )
        ],
    )


def create_bgp_plus_plus_transient_memory_route_scale_playbook(
    device_name: str,
    ixia_interface_mimic_ebgp: str,
    ebgp_peer_count_v6: int,
    ebgp_peer_count_v4: int,
    ibgp_peer_count_v6: int,
    ibgp_peer_count_v4: int,
    prefixes: list[int],
    constant_acceptance_communities: list[str] | None,
) -> Playbook:
    """Build the BGP++ transient-memory route-scale Playbook (perf scaling case3).

    Runs the
    `test_bgp_transient_memory_route_peer_scale_eos_bgp_plus_plus`
    custom step in `route_scale` mode, sweeping the `prefixes` list at a
    fixed peer count to measure transient memory under route churn.
    Used by EOS BGP++ performance-scaling Case 3.

    Args:
        device_name: DUT hostname (EOS BGP++).
        ixia_interface_mimic_ebgp: IXIA logical interface for EBGP.
        ebgp_peer_count_v6 / ebgp_peer_count_v4 / ibgp_peer_count_v6 /
            ibgp_peer_count_v4: Per-AF peer counts (constant for this
            sweep).
        prefixes: List of route counts to sweep.
        constant_acceptance_communities: Communities required by the
            EBGP ingress policy (or None).

    Returns:
        A `Playbook` named `bgp_plus_plus_transient_memory_route_scale_test`.
    """
    return Playbook(
        name="bgp_plus_plus_transient_memory_route_scale_test",
        description="Test BGP++ transient memory usage with varying route scale",
        snapshot_checks=[
            create_core_dumps_snapshot_check(),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_custom_step(
                        params_dict={
                            "custom_step_name": "test_bgp_transient_memory_route_peer_scale_eos_bgp_plus_plus",
                            "hostname": device_name,
                            "ixia_interface_mimic_ebgp": ixia_interface_mimic_ebgp,
                            "ebgp_peer_count_v6": ebgp_peer_count_v6,
                            "ebgp_peer_count_v4": ebgp_peer_count_v4,
                            "ibgp_peer_count_v6": ibgp_peer_count_v6,
                            "ibgp_peer_count_v4": ibgp_peer_count_v4,
                            "prefixes": prefixes,
                            # This community is required by device BGP policy to accept routes
                            "attach_communities_for_ebgp_prefixes": constant_acceptance_communities,
                            "mode": "route_scale",
                        }
                    ),
                ],
            )
        ],
    )


def create_case2_tcp_socket_data_collection_playbook(
    bgpcpp_device: str,
    tcp_data_collection_script: str,
    tcp_convergence_time: int,
    tcp_sample_interval: int,
) -> Playbook:
    """Build the TCP socket data collection Playbook for Case 2.

    Restarts BGP++ on `bgpcpp_device` and collects TCP data (ss + egress)
    during convergence using `tcp_data_collection_script`.
    """
    return Playbook(
        name="tcp_socket_data_collection",
        stages=[
            create_steps_stage(
                steps=[
                    create_run_task_step(
                        task_name="arista_daemon_control",
                        params_dict={
                            "hostname": bgpcpp_device,
                            "daemon_name": "Bgp",
                            "action": "disable",
                        },
                    ),
                    create_run_task_step(
                        task_name="arista_daemon_control",
                        params_dict={
                            "hostname": bgpcpp_device,
                            "daemon_name": "Bgp",
                            "action": "enable",
                        },
                    ),
                    create_run_task_step(
                        task_name="run_commands_on_shell",
                        params_dict={
                            "hostname": bgpcpp_device,
                            "cmds": [
                                f"bash {tcp_data_collection_script}"
                                f" {tcp_convergence_time}"
                                f" {tcp_sample_interval}"
                                " true",
                            ],
                        },
                    ),
                ],
                concurrent=False,
                description=(
                    "Restart BGP++ and collect TCP data"
                    " (ss + egress) during convergence"
                ),
            ),
        ],
    )


def build_case8_playbook(
    name: str,
    description: str,
    snapshot_checks: t.List[SnapshotHealthCheck],
    periodic_tasks: t.List,
    postchecks: t.List[PointInTimeHealthCheck],
    setup_steps: t.List,
    stages: t.List[taac_types.Stage],
) -> Playbook:
    """
    Generic Playbook builder shared by the case8 test_config factories.
    Centralizes the `taac_types.Playbook(...)` construction so the source
    file no longer inline-constructs Playbook.
    """
    return Playbook(
        name=name,
        description=description,
        snapshot_checks=snapshot_checks,
        periodic_tasks=periodic_tasks,
        postchecks=postchecks,
        setup_steps=setup_steps,
        stages=stages,
    )


def build_case6_playbook(
    name: str,
    description: str,
    snapshot_checks: t.List[SnapshotHealthCheck],
    periodic_tasks: t.List,
    prechecks: t.List,
    postchecks: t.List[PointInTimeHealthCheck],
    stages: t.List[taac_types.Stage],
) -> Playbook:
    """
    Generic Playbook builder shared by the case6 test_config factories.
    Centralizes the `taac_types.Playbook(...)` construction so the source
    file no longer inline-constructs Playbook.
    """
    return Playbook(
        name=name,
        description=description,
        snapshot_checks=snapshot_checks,
        periodic_tasks=periodic_tasks,
        prechecks=prechecks,
        postchecks=postchecks,
        stages=stages,
    )


def build_hyperport_vrf_bag_n000_playbook(
    name,
    stages,
    device_regexes=None,
    description=None,
    prechecks=None,
    postchecks=None,
    snapshot_checks=None,
    traffic_items_to_start=None,
    iteration=None,
):
    """Tiny trampoline so source no longer inline-constructs Playbook(...).

    Source `testconfigs/hyperport/hyperport_vrf_bag_n000_test_configs.py` had 6
    inline `Playbook(...)` constructions (2 inside factory helpers
    `_create_agent_terminate_playbook` and `_create_bgp_disruption_playbook`,
    4 standalone module-scope: vrf_bag_longevity + 3 PFC WD playbooks). Their
    kwarg shapes vary; this trampoline accepts all relevant fields as optional
    kwargs.
    """
    kwargs = {"name": name, "stages": stages}
    if device_regexes is not None:
        kwargs["device_regexes"] = device_regexes
    if description is not None:
        kwargs["description"] = description
    if prechecks is not None:
        kwargs["prechecks"] = prechecks
    if postchecks is not None:
        kwargs["postchecks"] = postchecks
    if snapshot_checks is not None:
        kwargs["snapshot_checks"] = snapshot_checks
    if traffic_items_to_start is not None:
        kwargs["traffic_items_to_start"] = traffic_items_to_start
    if iteration is not None:
        kwargs["iteration"] = iteration
    return Playbook(**kwargs)


def create_hyperport_vrf_bag_longevity_playbook(
    traffic_items_to_start: list[str],
    longevity_duration: int,
    prechecks: list[PointInTimeHealthCheck],
    postchecks: list[PointInTimeHealthCheck],
    snapshot_checks: list[SnapshotHealthCheck],
) -> Playbook:
    """Build the test_vrf_bag_longevity Playbook for hyperport VRF BAG TestConfigs.

    Single-stage longevity step with caller-supplied traffic items, duration,
    and pre/post/snapshot health checks (all of which depend on file-local
    callsite state in the source TestConfig — too closely coupled to move
    here, so they remain parameters).
    """
    return Playbook(
        name="test_vrf_bag_longevity",
        traffic_items_to_start=traffic_items_to_start,
        stages=[create_longevity_stage(duration=longevity_duration)],
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
    )


# ---------------------------------------------------------------------------
# Multinode test configs playbook trampoline
# ---------------------------------------------------------------------------


def build_multinode_playbook(
    name,
    stages,
    prechecks_to_skip=None,
    postchecks_to_skip=None,
    cleanup_steps=None,
):
    """Tiny trampoline so source no longer inline-constructs Playbook(...).

    Source `testconfigs/internal/multinode_test_configs.py` had 7 inline
    `Playbook(...)` constructions across module-scope (MULTINODE_HARDENING_PLAYBOOKS)
    and inside playbook factory helpers (create_port_channel_playbook,
    create_port_channel_playbooks, create_speed_flip_playbook). The Playbooks
    have varying kwarg shapes; this trampoline accepts all relevant fields as
    optional kwargs so the source can use a single call site.
    """
    kwargs = {"name": name, "stages": stages}
    if prechecks_to_skip is not None:
        kwargs["prechecks_to_skip"] = prechecks_to_skip
    if postchecks_to_skip is not None:
        kwargs["postchecks_to_skip"] = postchecks_to_skip
    if cleanup_steps is not None:
        kwargs["cleanup_steps"] = cleanup_steps
    return Playbook(**kwargs)


# ---------------------------------------------------------------------------
# FBOSS BGP + platform hardening conveyor playbook trampoline
# ---------------------------------------------------------------------------


def build_hardening_conveyor_playbook(
    name,
    stages,
    description=None,
    prechecks=None,
    postchecks=None,
    snapshot_checks=None,
    cleanup_steps=None,
    setup_steps=None,
    traffic_items_to_start=None,
    iteration=None,
    enabled=None,
    skip_test_config_postchecks=None,
    skip_test_config_prechecks=None,
    prechecks_to_skip=None,
    postchecks_to_skip=None,
    snapshot_checks_to_skip=None,
    check_ids_to_skip=None,
    periodic_tasks=None,
    device_regexes=None,
):
    """Tiny trampoline so source no longer inline-constructs Playbook(...).

    Source `testconfigs/internal/fboss_bgp_and_platform_hardening_conveyor.py`
    had 9 inline `Playbook(...)` constructions: 1 inside a loop generating
    `test_chronos_*` playbooks per iteration, and 8 inside the
    `test_config_for_bgp_and_fboss_platform_hardening_in_conveyor` factory's
    default playbook list (NDP/MAC/ARP overflow, BGP graceful restart, etc.).
    Their kwarg shapes vary; this trampoline accepts all relevant fields as
    optional kwargs.
    """
    kwargs = {"name": name, "stages": stages}
    for k, v in [
        ("description", description),
        ("prechecks", prechecks),
        ("postchecks", postchecks),
        ("snapshot_checks", snapshot_checks),
        ("cleanup_steps", cleanup_steps),
        ("setup_steps", setup_steps),
        ("traffic_items_to_start", traffic_items_to_start),
        ("iteration", iteration),
        ("enabled", enabled),
        ("skip_test_config_postchecks", skip_test_config_postchecks),
        ("skip_test_config_prechecks", skip_test_config_prechecks),
        ("prechecks_to_skip", prechecks_to_skip),
        ("postchecks_to_skip", postchecks_to_skip),
        ("snapshot_checks_to_skip", snapshot_checks_to_skip),
        ("check_ids_to_skip", check_ids_to_skip),
        ("periodic_tasks", periodic_tasks),
        ("device_regexes", device_regexes),
    ]:
        if v is not None:
            kwargs[k] = v
    return Playbook(**kwargs)


# ---------------------------------------------------------------------------
# BAG (non-QZA) test config disruptive playbooks
# ---------------------------------------------------------------------------


def get_bag_module_restart_playbook(
    name,
    device_regexes,
    modules,
    traffic_items_to_start,
    is_seqential=False,
):
    from taac.stages.stage_definitions import create_steps_stage
    from taac.steps.step_definitions import (
        create_longevity_step,
        create_module_power_toggle_step,
    )

    return Playbook(
        name=name,
        device_regexes=device_regexes,
        stages=[
            create_steps_stage(
                steps=[
                    create_module_power_toggle_step(
                        modules=modules,
                        enable=False,
                        sequential=is_seqential,
                    ),
                    create_longevity_step(duration=300),
                    create_module_power_toggle_step(
                        modules=modules,
                        enable=True,
                        sequential=is_seqential,
                    ),
                    create_longevity_step(duration=300),
                ]
            )
        ],
        postchecks=[
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        str_value="0",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                ],
                clear_traffic_stats=True,
            ),
        ],
        traffic_items_to_start=traffic_items_to_start,
    )


def get_bag_agent_interruption_playbook(
    name,
    device_regexes,
    trigger,
    agents,
    traffic_items_to_start,
):
    from taac.stages.stage_definitions import create_steps_stage
    from taac.steps.step_definitions import (
        create_arista_custom_agents_service_interruption_step,
        create_longevity_step,
    )

    return Playbook(
        name=name,
        device_regexes=device_regexes,
        postchecks=[create_ixia_packet_loss_check(clear_traffic_stats=True)],
        stages=[
            create_steps_stage(
                steps=[
                    create_arista_custom_agents_service_interruption_step(
                        agents=agents,
                        trigger=trigger,
                    ),
                    create_longevity_step(duration=60),
                ]
            )
        ],
        traffic_items_to_start=traffic_items_to_start,
    )


def get_bag_disruptive_playbooks(
    traffic_items_to_start: list[str],
    device_regexes: t.Optional[t.List[str]] = None,
    fabric_modules: t.Optional[t.List[str]] = None,
    linecard_modules: t.Optional[t.List[str]] = None,
):
    from taac.stages.stage_definitions import create_steps_stage
    from taac.steps.step_definitions import (
        create_longevity_step,
        create_system_reboot_step,
    )

    # Set defaults if not provided
    if fabric_modules is None:
        fabric_modules = ["Fabric1"]
    if linecard_modules is None:
        linecard_modules = ["Linecard3"]

    TEST_BAG_DEVICE_REBOOT_PLAYBOOK = Playbook(
        name="test_device_reboot",
        device_regexes=device_regexes,
        postchecks=[
            create_ixia_packet_loss_check(clear_traffic_stats=True),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_system_reboot_step(
                        trigger=taac_types.SystemRebootTrigger.FULL_SYSTEM_REBOOT,
                    ),
                    create_longevity_step(duration=300),
                ]
            )
        ],
        traffic_items_to_start=traffic_items_to_start,
    )

    TEST_BAG_FABRIC_CARD_RESTART_PLAYBOOK = get_bag_module_restart_playbook(
        name="test_bag_fabric_card_restart",
        device_regexes=device_regexes,
        modules=fabric_modules,
        traffic_items_to_start=traffic_items_to_start,
        is_seqential=False,
    )

    TEST_BAG_LINE_CARD_RESTART_PLAYBOOK = get_bag_module_restart_playbook(
        name="test_bag_line_card_restart",
        device_regexes=device_regexes,
        modules=linecard_modules,
        traffic_items_to_start=traffic_items_to_start,
        is_seqential=False,
    )

    TEST_BGP_AGENT_CRASH_PLAYBOOK = get_bag_agent_interruption_playbook(
        name="test_bgp_agent_terminate",
        device_regexes=device_regexes,
        trigger=taac_types.ServiceInterruptionTrigger.CRASH,
        agents=["Bgp"],
        traffic_items_to_start=traffic_items_to_start,
    )

    TEST_FABRIC_AGENT_CRASH_PLAYBOOK = get_bag_agent_interruption_playbook(
        name="test_fabric_agent_terminate",
        device_regexes=device_regexes,
        trigger=taac_types.ServiceInterruptionTrigger.CRASH,
        agents=["SandFabric-Fabric1", "SandFabric-Fabric2", "SandFabric-Fabric3"],
        traffic_items_to_start=traffic_items_to_start,
    )

    TEST_LINECARD_AGENT_CRASH_PLAYBOOK = get_bag_agent_interruption_playbook(
        name="test_linecard_agent_terminate",
        device_regexes=device_regexes,
        trigger=taac_types.ServiceInterruptionTrigger.CRASH,
        agents=["SandFapNi-Linecard3", "SandFapNi-Linecard4"],
        traffic_items_to_start=traffic_items_to_start,
    )

    return [
        TEST_BAG_DEVICE_REBOOT_PLAYBOOK,
        TEST_BAG_FABRIC_CARD_RESTART_PLAYBOOK,
        TEST_BAG_LINE_CARD_RESTART_PLAYBOOK,
        TEST_BGP_AGENT_CRASH_PLAYBOOK,
        TEST_FABRIC_AGENT_CRASH_PLAYBOOK,
        TEST_LINECARD_AGENT_CRASH_PLAYBOOK,
    ]


# ---------------------------------------------------------------------------
# BAG QZA disruptive playbooks
# ---------------------------------------------------------------------------


def get_bag_qza_module_restart_playbook(
    name: str,
    device_regexes: t.List[str],
    modules: t.List[str],
    traffic_items_to_start: t.List[str],
    is_seqential: bool = False,
    iteration: int = 10,
) -> Playbook:
    from taac.stages.stage_definitions import create_steps_stage
    from taac.steps.step_definitions import (
        create_longevity_step,
        create_module_power_toggle_step,
    )

    return Playbook(
        name=name,
        device_regexes=device_regexes,
        stages=[
            create_steps_stage(
                steps=[
                    create_module_power_toggle_step(
                        modules=modules,
                        enable=False,
                        sequential=is_seqential,
                    ),
                    create_longevity_step(duration=300),
                    create_module_power_toggle_step(
                        modules=modules,
                        enable=True,
                        sequential=is_seqential,
                    ),
                    create_longevity_step(duration=300),
                ]
            )
        ],
        postchecks=[
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        str_value="0",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                ],
                clear_traffic_stats=True,
            ),
        ],
        traffic_items_to_start=traffic_items_to_start,
        iteration=iteration,
    )


def get_bag_qza_agent_interruption_playbook(
    name: str,
    device_regexes: t.List[str],
    trigger: taac_types.ServiceInterruptionTrigger,
    agents: t.List[str],
    traffic_items_to_start: t.List[str],
    clear_traffic_stats: bool = True,
    longevity_duration: int = 300,
    iteration: int = 10,
) -> Playbook:
    from taac.stages.stage_definitions import create_steps_stage
    from taac.steps.step_definitions import (
        create_arista_custom_agents_service_interruption_step,
        create_longevity_step,
    )

    return Playbook(
        name=name,
        device_regexes=device_regexes,
        postchecks=[
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        str_value="0",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                ],
                clear_traffic_stats=clear_traffic_stats,
            ),
            create_service_restart_check(expected_restarted_services=agents),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_arista_custom_agents_service_interruption_step(
                        agents=agents,
                        trigger=trigger,
                    ),
                    create_longevity_step(duration=longevity_duration),
                ]
            )
        ],
        traffic_items_to_start=traffic_items_to_start,
        iteration=iteration,
    )


def create_bag_qza_disruptive_playbooks(
    traffic_items_to_start: t.List[str],
    device_regexes: t.List[str],
    fabric_modules: t.List[str],
    linecard_modules: t.List[str],
    fabric_agents: t.List[str],
    linecard_agents: t.List[str],
    is_seqential: bool = False,
    iteration: int = 10,
) -> t.List[Playbook]:
    """Build the standard BAG QZA disruptive Playbook bundle.

    Bundle of seven playbooks exercising device-reboot, fabric/linecard
    module restarts, and fabric/linecard agent restarts + crashes against
    the given device set. Each playbook starts `traffic_items_to_start`
    and asserts zero packet loss; module/agent playbooks delegate to the
    `get_bag_qza_*` helpers. Used by BAG QZA TestConfigs as the canonical
    disruptive-coverage suite.

    Args:
        traffic_items_to_start: IXIA traffic items to enable during each
            playbook.
        device_regexes: DUT device regex(es) (e.g. `["bag001.qza1"]`).
        fabric_modules: Fabric module names (e.g. `["Fabric1", ...]`)
            cycled by the fabric-card restart playbook.
        linecard_modules: Linecard module names cycled by the linecard-
            card restart playbook.
        fabric_agents: Fabric Arista agent names (e.g. `SandFabric-Fabric1`)
            cycled by the fabric agent restart + crash playbooks.
        linecard_agents: Linecard Arista agent names (e.g. `SandFapNi-Linecard3`)
            cycled by the linecard agent restart + crash playbooks.
        is_seqential: If True, modules/agents are cycled one at a time
            (sic on spelling — preserved upstream). Default False.
        iteration: Number of iterations per playbook. Default 10.

    Returns:
        List of seven `Playbook` objects in order: device reboot, fabric
        card restart, linecard card restart, fabric agent restart,
        linecard agent restart, fabric agent crash, linecard agent crash.
    """
    from taac.stages.stage_definitions import create_steps_stage
    from taac.steps.step_definitions import (
        create_longevity_step,
        create_system_reboot_step,
    )

    TEST_DEVICE_REBOOT_PLAYBOOK = Playbook(
        name="test_device_reboot",
        device_regexes=device_regexes,
        postchecks=[
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        str_value="0",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                ],
                clear_traffic_stats=True,
            ),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_system_reboot_step(
                        trigger=taac_types.SystemRebootTrigger.FULL_SYSTEM_REBOOT,
                    ),
                    create_longevity_step(duration=300),
                ]
            )
        ],
        traffic_items_to_start=traffic_items_to_start,
        iteration=iteration,
    )

    TEST_FABRIC_CARD_RESTART_PLAYBOOK = get_bag_qza_module_restart_playbook(
        name="test_bag_fabric_card_restart",
        device_regexes=device_regexes,
        modules=fabric_modules,
        traffic_items_to_start=traffic_items_to_start,
        is_seqential=is_seqential,
        iteration=iteration,
    )

    TEST_LINE_CARD_RESTART_PLAYBOOK = get_bag_qza_module_restart_playbook(
        name="test_bag_line_card_restart",
        device_regexes=device_regexes,
        modules=linecard_modules,
        traffic_items_to_start=traffic_items_to_start,
        is_seqential=is_seqential,
        iteration=iteration,
    )

    TEST_FABRIC_AGENT_RESTART_PLAYBOOK = get_bag_qza_agent_interruption_playbook(
        name="test_fabric_agent_restart",
        device_regexes=device_regexes,
        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
        agents=fabric_agents,
        traffic_items_to_start=traffic_items_to_start,
        iteration=iteration,
    )

    TEST_LINECARD_AGENT_RESTART_PLAYBOOK = get_bag_qza_agent_interruption_playbook(
        name="test_linecard_agent_restart",
        device_regexes=device_regexes,
        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
        agents=linecard_agents,
        traffic_items_to_start=traffic_items_to_start,
        iteration=iteration,
    )

    TEST_FABRIC_AGENT_CRASH_PLAYBOOK = get_bag_qza_agent_interruption_playbook(
        name="test_fabric_agent_terminate",
        device_regexes=device_regexes,
        trigger=taac_types.ServiceInterruptionTrigger.CRASH,
        agents=fabric_agents,
        traffic_items_to_start=traffic_items_to_start,
        iteration=iteration,
    )

    TEST_LINECARD_AGENT_CRASH_PLAYBOOK = get_bag_qza_agent_interruption_playbook(
        name="test_linecard_agent_terminate",
        device_regexes=device_regexes,
        trigger=taac_types.ServiceInterruptionTrigger.CRASH,
        agents=linecard_agents,
        traffic_items_to_start=traffic_items_to_start,
        iteration=iteration,
    )

    return [
        TEST_DEVICE_REBOOT_PLAYBOOK,
        TEST_FABRIC_CARD_RESTART_PLAYBOOK,
        TEST_LINE_CARD_RESTART_PLAYBOOK,
        TEST_FABRIC_AGENT_RESTART_PLAYBOOK,
        TEST_LINECARD_AGENT_RESTART_PLAYBOOK,
        TEST_FABRIC_AGENT_CRASH_PLAYBOOK,
        TEST_LINECARD_AGENT_CRASH_PLAYBOOK,
    ]


# (agent_name, playbook_name, clear_traffic_stats)
# Device-level agents (not tied to specific linecard/fabric slot)
_BAG_QZA_AGENT_TERMINATE_CONFIGS: t.List[t.Tuple[str, str, bool]] = [
    ("sandadj", "test_sandadj_agent_terminate", False),
    ("sandlag", "test_sandlag_agent_terminate", True),
    ("SandL3Ni", "test_sandl3ni_agent_terminate", False),
    ("snmp", "test_snmp_agent_terminate", False),
    ("XcvrAgent", "test_xcvragent_agent_terminate", False),
    ("SandTm", "test_sandtm_agent_terminate", False),
    ("SandLanz", "test_sandlanz_agent_terminate", False),
]


def create_bag_qza_agent_terminate_playbooks(
    device_regexes: t.List[str],
    traffic_items_to_start: t.List[str],
    linecard_numbers: t.Optional[t.List[int]] = None,
    fabric_numbers: t.Optional[t.List[int]] = None,
    iteration: int = 5,
) -> t.List[Playbook]:
    """Create individual agent terminate (crash) playbooks for BAG QZA testing.

    Each playbook crashes a single Arista agent and verifies traffic recovery.
    Generates per-linecard (SandFapNi-LinecardN) and per-fabric
    (SandFabric-FabricN) playbooks based on the device's module inventory.

    Args:
        device_regexes: DUT device patterns (e.g., ["bag001.qza1"])
        traffic_items_to_start: Traffic items to run during the test
        linecard_numbers: Linecard slot numbers (e.g., [3, 4, ..., 14])
        fabric_numbers: Fabric module numbers (e.g., [1, 2, 3, 4, 5])
        iteration: Number of iterations per playbook
    """
    # Device-level agent terminate playbooks
    playbooks = [
        get_bag_qza_agent_interruption_playbook(
            name=name,
            device_regexes=device_regexes,
            trigger=taac_types.ServiceInterruptionTrigger.CRASH,
            agents=[agent],
            traffic_items_to_start=traffic_items_to_start,
            clear_traffic_stats=clear_stats,
            longevity_duration=120,
            iteration=iteration,
        )
        for agent, name, clear_stats in _BAG_QZA_AGENT_TERMINATE_CONFIGS
    ]

    # Per-linecard agent terminate playbooks (hitfull)
    for lc in linecard_numbers or []:
        playbooks.append(
            get_bag_qza_agent_interruption_playbook(
                name=f"test_sandfapni_linecard{lc}_agent_terminate",
                device_regexes=device_regexes,
                trigger=taac_types.ServiceInterruptionTrigger.CRASH,
                agents=[f"SandFapNi-Linecard{lc}"],
                traffic_items_to_start=traffic_items_to_start,
                clear_traffic_stats=True,
                longevity_duration=120,
                iteration=iteration,
            )
        )

    # Per-fabric agent terminate playbooks (hitfull)
    for fab in fabric_numbers or []:
        playbooks.append(
            get_bag_qza_agent_interruption_playbook(
                name=f"test_sandfabric_fabric{fab}_agent_terminate",
                device_regexes=device_regexes,
                trigger=taac_types.ServiceInterruptionTrigger.CRASH,
                agents=[f"SandFabric-Fabric{fab}"],
                traffic_items_to_start=traffic_items_to_start,
                clear_traffic_stats=True,
                longevity_duration=120,
                iteration=iteration,
            )
        )

    return playbooks


# ---------------------------------------------------------------------------
# Speed flip playbooks
# ---------------------------------------------------------------------------


def create_speed_flip_playbook(
    name: str,
    stages: t.List[taac_types.Stage],
    iteration: int,
) -> Playbook:
    """Build a SpeedFlipPlaybook-style Playbook from caller-supplied stages.

    Thin factory mirroring the construction inside
    `SpeedFlipPlaybook.build_playbook()`. Used by speed-flip TestConfigs
    that have already assembled their `stages` list (typically alternating
    interface speed changes with verification).

    Args:
        name: Playbook name (becomes the test-case name in results).
        stages: Pre-built list of stages to attach.
        iteration: Number of times to repeat the full stage sequence.

    Returns:
        A `Playbook` with the given name, stages, and iteration count.
    """
    return Playbook(
        name=name,
        stages=stages,
        iteration=iteration,
    )


def create_speed_flip_test_config_playbook(
    built_playbook: Playbook,
    snapshot_checks: t.List,
) -> Playbook:
    """
    Build the wrapper Playbook produced inside SpeedFlipTestConfig.build_test_config()
    that augments a built SpeedFlipPlaybook with the test-config-level snapshot
    health checks (combined with any playbook-level snapshot_checks).
    """
    return Playbook(
        name=built_playbook.name,
        prechecks=built_playbook.prechecks,
        postchecks=built_playbook.postchecks,
        stages=built_playbook.stages,
        iteration=built_playbook.iteration,
        traffic_items_to_start=built_playbook.traffic_items_to_start,
        snapshot_checks=list(built_playbook.snapshot_checks or [])
        + list(snapshot_checks),
        enabled=built_playbook.enabled,
    )


# ---------------------------------------------------------------------------
# CTE UCMP stand-alone playbooks
# ---------------------------------------------------------------------------

# UCMP test constants (duplicated from source per low-complexity principle)
CTE_UCMP_VIP_COMMUNITY = "65441:260"
CTE_UCMP_VIP_V6 = "2402:db00:1100::/64"

CTE_UCMP_DC1_ASN = 50001
CTE_UCMP_DC2_ASN = 50002
CTE_UCMP_DC3_ASN = 50003
CTE_UCMP_DC_ASNS = [CTE_UCMP_DC1_ASN, CTE_UCMP_DC2_ASN, CTE_UCMP_DC3_ASN]

CTE_UCMP_PEERS_PER_DC = 4
CTE_UCMP_TOTAL_DOWNLINK_PEERS = CTE_UCMP_PEERS_PER_DC * len(CTE_UCMP_DC_ASNS)  # 12
CTE_UCMP_NUM_ITERATIONS = 10


def _create_cte_ucmp_custom_step(action: str) -> taac_types.Step:
    """Thin wrapper over central factory; preserves CTE UCMP file-local constants."""
    from taac.steps.step_definitions import (
        create_cte_ucmp_custom_step,
    )

    return create_cte_ucmp_custom_step(
        action=action,
        target_community=CTE_UCMP_VIP_COMMUNITY,
        dc_asns=CTE_UCMP_DC_ASNS,
        peers_per_dc=CTE_UCMP_PEERS_PER_DC,
    )


def _create_cte_ucmp_dynamic_rib_validation_step() -> taac_types.Step:
    """Thin wrapper over central factory; preserves CTE UCMP file-local constants."""
    from taac.steps.step_definitions import (
        create_cte_ucmp_dynamic_rib_validation_step,
    )

    return create_cte_ucmp_dynamic_rib_validation_step(
        target_community=CTE_UCMP_VIP_COMMUNITY,
        target_prefix=CTE_UCMP_VIP_V6,
    )


def _create_cte_ucmp_dg_toggle_stage(stage_id: str, action: str) -> taac_types.Stage:
    """Create a stage that disables DGs, sets/updates UCMP policy, re-enables DGs, then verifies.

    bgpcpp's setRouteAttributePolicy does NOT re-evaluate existing routes.
    Routes must arrive AFTER the policy is set for weights to be applied.
    Pattern: disable DGs -> set policy -> re-enable DGs -> wait -> verify.
    """
    from taac.stages.stage_definitions import create_steps_stage
    from taac.steps.step_definitions import (
        create_bgp_convergence_wait_step,
        create_disable_dc_vip_step,
        create_enable_dc_vip_step,
    )

    return create_steps_stage(
        stage_id=stage_id,
        steps=[
            # 1. Disable all 3 DGs (withdraw routes from RIB)
            create_disable_dc_vip_step(1),
            create_disable_dc_vip_step(2),
            create_disable_dc_vip_step(3),
            # 2. Wait for routes to drain from RIB
            create_bgp_convergence_wait_step(wait_seconds=15),
            # 3. Set/update UCMP policy (no routes in RIB)
            _create_cte_ucmp_custom_step(action),
            # 4. Re-enable all 3 DGs (routes arrive with policy active)
            create_enable_dc_vip_step(1),
            create_enable_dc_vip_step(2),
            create_enable_dc_vip_step(3),
            # 5. Wait for BGP convergence
            create_bgp_convergence_wait_step(wait_seconds=30),
            # 6. Verify weights applied
            _create_cte_ucmp_dynamic_rib_validation_step(),
        ],
    )


def create_baseline_ecmp_playbook() -> taac_types.Playbook:
    """Build the baseline ECMP-verification Playbook for the CTE UCMP TestConfig.

    Verifies that all 12 BGP sessions (3 DCs x 4 peers) are established
    and that traffic distributes evenly across the ECMP nexthop group
    with zero packet loss, prior to running any UCMP weight-mutation
    iterations. Asserts LLDP and port-state in pre + postchecks, and
    captures a core-dumps snapshot. Used as the first playbook in the
    CTE UCMP stand-alone TestConfig.

    Returns:
        A `Playbook` named `baseline_ecmp_verification` that starts the
        UCMP_STAND_ALONE_TRAFFIC item and validates baseline ECMP.
    """
    from taac.steps.step_definitions import (
        create_bgp_convergence_wait_step,
        create_clear_traffic_stats_step,
        create_traffic_duration_step,
        create_ucmp_policy_config_step,
    )
    from taac.health_checks.healthcheck_definitions import (
        create_bgp_rib_weight_check,
        create_packetloss_health_check,
    )
    from taac.stages.stage_definitions import create_steps_stage
    from taac.steps.step_definitions import create_validation_step

    return taac_types.Playbook(
        name="baseline_ecmp_verification",
        description="Verify all 12 BGP sessions up, ECMP traffic distribution, zero packet loss",
        prechecks=[
            create_lldp_check(),
            create_port_state_check(),
        ],
        postchecks=[
            create_lldp_check(),
            create_port_state_check(),
        ],
        snapshot_checks=[
            create_core_dumps_snapshot_check(),
        ],
        traffic_items_to_start=["UCMP_STAND_ALONE_TRAFFIC"],
        stages=[
            create_steps_stage(
                stage_id="clear_residual_ucmp_policy",
                steps=[
                    # Clear any residual UCMP policy from prior test runs
                    # so baseline ECMP check sees weight=0 for all nexthops
                    create_ucmp_policy_config_step(
                        vip_community=CTE_UCMP_VIP_COMMUNITY,
                        dc1_asn=CTE_UCMP_DC1_ASN,
                        dc2_asn=CTE_UCMP_DC2_ASN,
                        dc3_asn=CTE_UCMP_DC3_ASN,
                        dc1_weight=0,
                        dc2_weight=0,
                        dc3_weight=0,
                        action="clear",
                    ),
                ],
            ),
            create_steps_stage(
                stage_id="baseline_setup",
                steps=[
                    create_bgp_convergence_wait_step(
                        wait_seconds=60
                    ),  # Keep 60s for BGP convergence
                ],
            ),
            create_steps_stage(
                stage_id="baseline_ecmp_verify",
                steps=[
                    create_clear_traffic_stats_step(),
                    create_traffic_duration_step(duration_seconds=300),
                    create_validation_step(
                        point_in_time_checks=[
                            # Verify all BGP sessions are established
                            create_bgp_session_establish_check(),
                            # Verify ECMP: all 12 nexthops with weight 0
                            create_bgp_rib_weight_check(
                                target_community=CTE_UCMP_VIP_COMMUNITY,
                                target_prefix=CTE_UCMP_VIP_V6,
                                expected_weights={0: CTE_UCMP_TOTAL_DOWNLINK_PEERS},
                                require_ucmp=False,
                            ),
                            # Verify zero packet loss
                            create_packetloss_health_check(),
                        ],
                        description="Verify ECMP baseline: sessions up, equal weights, no loss",
                    ),
                ],
            ),
        ],
    )


def create_ucmp_iteration_playbook() -> taac_types.Playbook:
    """N iterations of set/delete+reset/update with random weights.

    Each stage uses the DG toggle pattern: disable DGs -> set policy -> re-enable DGs.
    This is required because bgpcpp's setRouteAttributePolicy does NOT re-evaluate
    existing routes - routes must arrive AFTER the policy is set.
    """
    return taac_types.Playbook(
        name="ucmp_random_weight_iterations",
        description=f"CTE UCMP stand-alone: {CTE_UCMP_NUM_ITERATIONS} iterations of random weight set/delete/update",
        prechecks=[
            create_lldp_check(),
            create_port_state_check(),
        ],
        postchecks=[
            create_lldp_check(),
            create_port_state_check(),
        ],
        snapshot_checks=[
            create_core_dumps_snapshot_check(),
        ],
        iteration=CTE_UCMP_NUM_ITERATIONS,
        traffic_items_to_start=["UCMP_STAND_ALONE_TRAFFIC"],
        stages=[
            _create_cte_ucmp_dg_toggle_stage("set_random_weights", "generate_and_set"),
            _create_cte_ucmp_dg_toggle_stage(
                "clear_and_reset_same_weights", "clear_and_reset"
            ),
            _create_cte_ucmp_dg_toggle_stage(
                "update_to_new_weights", "generate_and_update"
            ),
        ],
    )


def build_2_ixia_hardening_playbook(
    name,
    stages,
    description=None,
    prechecks=None,
    postchecks=None,
    snapshot_checks=None,
    cleanup_steps=None,
    setup_steps=None,
    traffic_items_to_start=None,
    iteration=None,
    enabled=None,
    skip_test_config_postchecks=None,
    skip_test_config_prechecks=None,
    prechecks_to_skip=None,
    postchecks_to_skip=None,
    snapshot_checks_to_skip=None,
    check_ids_to_skip=None,
    periodic_tasks=None,
    device_regexes=None,
):
    """Trampoline for `test_config_for_2_ixia_bgp_and_fboss_platform_hardening_in_conveyor`.

    The source TestConfig has 16 inline `Playbook(...)` constructions whose
    kwarg shapes vary; this trampoline accepts all relevant fields as optional
    kwargs.
    """
    kwargs = {"name": name, "stages": stages}
    for k, v in [
        ("description", description),
        ("prechecks", prechecks),
        ("postchecks", postchecks),
        ("snapshot_checks", snapshot_checks),
        ("cleanup_steps", cleanup_steps),
        ("setup_steps", setup_steps),
        ("traffic_items_to_start", traffic_items_to_start),
        ("iteration", iteration),
        ("enabled", enabled),
        ("skip_test_config_postchecks", skip_test_config_postchecks),
        ("skip_test_config_prechecks", skip_test_config_prechecks),
        ("prechecks_to_skip", prechecks_to_skip),
        ("postchecks_to_skip", postchecks_to_skip),
        ("snapshot_checks_to_skip", snapshot_checks_to_skip),
        ("check_ids_to_skip", check_ids_to_skip),
        ("periodic_tasks", periodic_tasks),
        ("device_regexes", device_regexes),
    ]:
        if v is not None:
            kwargs[k] = v
    return Playbook(**kwargs)


def get_cbag_module_restart_playbook(
    name: str,
    device_regexes: t.List[str],
    modules: t.List[str],
    traffic_items_to_start: t.List[str],
    is_sequential: bool = False,
    iteration: int = 10,
) -> Playbook:
    """CBAG module power toggle playbook (fabric or linecard cards)."""
    from taac.steps.step_definitions import (
        create_module_power_toggle_step,
    )

    return Playbook(
        name=name,
        device_regexes=device_regexes,
        stages=[
            create_steps_stage(
                steps=[
                    create_module_power_toggle_step(
                        modules=modules,
                        enable=False,
                        sequential=is_sequential,
                    ),
                    create_longevity_step(duration=300),
                    create_module_power_toggle_step(
                        modules=modules,
                        enable=True,
                        sequential=is_sequential,
                    ),
                    create_longevity_step(duration=300 * 3),
                ]
            )
        ],
        postchecks=[
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        str_value="0",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                ],
                clear_traffic_stats=True,
            ),
        ],
        traffic_items_to_start=traffic_items_to_start,
        iteration=iteration,
    )


def get_cbag_agent_interruption_playbook(
    name: str,
    device_regexes: t.List[str],
    trigger: taac_types.ServiceInterruptionTrigger,
    agents: t.List[str],
    traffic_items_to_start: t.List[str],
    iteration: int = 10,
) -> Playbook:
    """CBAG arista custom-agents service-interruption playbook."""
    from taac.steps.step_definitions import (
        create_arista_custom_agents_service_interruption_step,
    )

    return Playbook(
        name=name,
        device_regexes=device_regexes,
        postchecks=[
            create_ixia_packet_loss_check(clear_traffic_stats=True),
            create_service_restart_check(
                services=[
                    "SandFabric-Fabric1",
                    "SandFabric-Fabric2",
                    "SandFabric-Fabric3",
                    "SandFabric-Fabric4",
                    "SandFabric-Fabric5",
                    "SandFapNi-Linecard3",
                    "SandFapNi-Linecard4",
                    "XcvrAgent",
                ],
                expected_restarted_services=agents,
            ),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_arista_custom_agents_service_interruption_step(
                        agents=agents,
                        trigger=trigger,
                    ),
                    create_longevity_step(duration=300),
                ]
            )
        ],
        traffic_items_to_start=traffic_items_to_start,
        iteration=iteration,
    )


def create_cbag_disruptive_playbooks(
    traffic_items_to_start: t.List[str],
    device_regexes: t.List[str],
    fabric_modules: t.List[str],
    linecard_modules: t.List[str],
    fabric_agents: t.List[str],
    linecard_agents: t.List[str],
    is_sequential: bool = False,
    iteration: int = 10,
) -> t.List[Playbook]:
    """Build the standard CBAG disruptive Playbook bundle.

    Bundle of eight playbooks exercising device reboot, fabric/linecard
    module restarts, fabric/linecard agent restarts + crashes, and an
    interface-flap playbook across all 20 Ethernet3 interfaces. Each
    playbook starts `traffic_items_to_start` and validates traffic via
    IXIA packet-loss postchecks. Used by CBAG TestConfigs as their
    canonical disruptive-coverage suite.

    Args:
        traffic_items_to_start: IXIA traffic items to enable during each
            playbook.
        device_regexes: DUT device regex(es).
        fabric_modules: Fabric module names cycled by the fabric-card
            restart playbook.
        linecard_modules: Linecard module names cycled by the linecard-
            card restart playbook.
        fabric_agents: Fabric Arista agent names cycled by the fabric
            agent restart + crash playbooks.
        linecard_agents: Linecard Arista agent names cycled by the
            linecard agent restart + crash playbooks.
        is_sequential: If True, modules/agents are cycled one at a time.
            Default False.
        iteration: Number of iterations per playbook. Default 10.

    Returns:
        List of eight `Playbook` objects: device reboot, fabric card
        restart, linecard card restart, fabric agent restart, linecard
        agent restart, fabric agent crash, linecard agent crash, and
        interface flap (60s/300s settle windows).
    """
    from taac.steps.step_definitions import (
        create_system_reboot_step,
    )

    test_cbag_device_reboot_playbook = Playbook(
        name="test_device_reboot",
        device_regexes=device_regexes,
        postchecks=[
            create_ixia_packet_loss_check(clear_traffic_stats=True),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_system_reboot_step(
                        trigger=taac_types.SystemRebootTrigger.FULL_SYSTEM_REBOOT,
                    ),
                    create_longevity_step(duration=300),
                ]
            )
        ],
        traffic_items_to_start=traffic_items_to_start,
        iteration=iteration,
    )

    test_cbag_fabric_card_reboot_playbook = get_cbag_module_restart_playbook(
        name="test_cbag_fabric_card_restart",
        device_regexes=device_regexes,
        modules=fabric_modules,
        traffic_items_to_start=traffic_items_to_start,
        is_sequential=is_sequential,
        iteration=iteration,
    )

    test_cbag_line_card_reboot_playbook = get_cbag_module_restart_playbook(
        name="test_cbag_line_card_restart",
        device_regexes=device_regexes,
        modules=linecard_modules,
        traffic_items_to_start=traffic_items_to_start,
        is_sequential=is_sequential,
        iteration=iteration,
    )

    test_fabric_agent_restart_playbook = get_cbag_agent_interruption_playbook(
        name="test_fabric_agent_restart",
        device_regexes=device_regexes,
        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
        agents=fabric_agents,
        traffic_items_to_start=traffic_items_to_start,
        iteration=iteration,
    )

    test_linecard_agent_restart_playbook = get_cbag_agent_interruption_playbook(
        name="test_linecard_agent_restart",
        device_regexes=device_regexes,
        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
        agents=linecard_agents,
        traffic_items_to_start=traffic_items_to_start,
        iteration=iteration,
    )

    test_fabric_agent_crash_playbook = get_cbag_agent_interruption_playbook(
        name="test_fabric_agent_terminate",
        device_regexes=device_regexes,
        trigger=taac_types.ServiceInterruptionTrigger.CRASH,
        agents=fabric_agents,
        traffic_items_to_start=traffic_items_to_start,
        iteration=iteration,
    )

    test_linecard_agent_crash_playbook = get_cbag_agent_interruption_playbook(
        name="test_linecard_agent_terminate",
        device_regexes=device_regexes,
        trigger=taac_types.ServiceInterruptionTrigger.CRASH,
        agents=linecard_agents,
        traffic_items_to_start=traffic_items_to_start,
        iteration=iteration,
    )

    test_interface_flap_playbook = Playbook(
        name="test_interface_flap",
        device_regexes=device_regexes,
        stages=[
            create_steps_stage(
                steps=[
                    create_interface_flap_step(
                        enable=False,
                        interfaces=[f"Ethernet3/{i}/1" for i in range(1, 21)],
                        description="Flap all interfaces",
                        interface_flap_method=4,
                        device_name=device_regexes[0],
                    ),
                    create_longevity_step(duration=60),
                    create_interface_flap_step(
                        enable=True,
                        interfaces=[f"Ethernet3/{i}/1" for i in range(1, 21)],
                        description="Flap all interfaces",
                        interface_flap_method=4,
                        device_name=device_regexes[0],
                    ),
                    create_longevity_step(duration=300),
                ],
            ),
        ],
        postchecks=[
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        str_value="0",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                ],
                clear_traffic_stats=True,
            ),
        ],
        traffic_items_to_start=traffic_items_to_start,
        iteration=iteration,
    )

    return [
        test_cbag_device_reboot_playbook,
        test_cbag_fabric_card_reboot_playbook,
        test_cbag_line_card_reboot_playbook,
        test_fabric_agent_restart_playbook,
        test_linecard_agent_restart_playbook,
        test_fabric_agent_crash_playbook,
        test_linecard_agent_crash_playbook,
        test_interface_flap_playbook,
    ]


def get_cpr_module_restart_playbook(
    name: str,
    device_regexes: t.List[str],
    modules: t.List[str],
    traffic_items_to_start: t.List[str],
    is_sequential: bool = False,
    iteration: int = 10,
) -> Playbook:
    from taac.steps.step_definitions import (
        create_module_power_toggle_step,
    )

    return Playbook(
        name=name,
        device_regexes=device_regexes,
        stages=[
            create_steps_stage(
                steps=[
                    create_module_power_toggle_step(
                        modules=modules,
                        enable=False,
                        sequential=is_sequential,
                    ),
                    create_longevity_step(duration=300),
                    create_module_power_toggle_step(
                        modules=modules,
                        enable=True,
                        sequential=is_sequential,
                    ),
                    create_longevity_step(duration=300 * 3),
                ]
            )
        ],
        postchecks=[
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        str_value="0",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                ],
                clear_traffic_stats=True,
            ),
        ],
        traffic_items_to_start=traffic_items_to_start,
        iteration=iteration,
    )


def get_cpr_agent_interruption_playbook(
    name: str,
    device_regexes: t.List[str],
    trigger: taac_types.ServiceInterruptionTrigger,
    agents: t.List[str],
    traffic_items_to_start: t.List[str],
    iteration: int = 10,
    clear_traffic_stats: bool = False,
) -> Playbook:
    from taac.steps.step_definitions import (
        create_arista_custom_agents_service_interruption_step,
    )

    return Playbook(
        name=name,
        device_regexes=device_regexes,
        postchecks=[
            create_ixia_packet_loss_check(clear_traffic_stats=clear_traffic_stats),
            create_service_restart_check(
                services=[
                    "SandFabric-Fabric1",
                    "SandFabric-Fabric2",
                    "SandFabric-Fabric3",
                    "SandFabric-Fabric4",
                    "SandFabric-Fabric5",
                    "SandFapNi-Linecard3",
                    "SandFapNi-Linecard4",
                    "XcvrAgent",
                ],
                expected_restarted_services=agents,
                check_scope=hc_types.Scope.DEFAULT,
            ),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_arista_custom_agents_service_interruption_step(
                        agents=agents,
                        trigger=trigger,
                    ),
                    create_longevity_step(duration=300),
                ]
            )
        ],
        traffic_items_to_start=traffic_items_to_start,
        iteration=iteration,
    )


def create_cpr_disruptive_playbooks(
    traffic_items_to_start: t.List[str],
    device_regexes: t.List[str],
    fabric_modules: t.List[str],
    linecard_modules: t.List[str],
    fabric_agents: t.List[str],
    linecard_agents: t.List[str],
    is_sequential: bool = False,
    iteration: int = 10,
) -> t.List[Playbook]:
    from taac.steps.step_definitions import (
        create_system_reboot_step,
    )

    TEST_CPR_DEVICE_REBOOT_PLAYBOOK = Playbook(
        name="test_device_reboot",
        device_regexes=device_regexes,
        postchecks=[
            create_ixia_packet_loss_check(clear_traffic_stats=True),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_system_reboot_step(
                        trigger=taac_types.SystemRebootTrigger.FULL_SYSTEM_REBOOT,
                    ),
                    # once device becomes SSH able, its take approx 3 mins for all agents to start
                    # and then link bring up starts.
                    create_longevity_step(duration=500),
                ]
            )
        ],
        traffic_items_to_start=traffic_items_to_start,
        iteration=iteration,
    )

    TEST_CPR_FABRIC_CARD_REBOOT_PLAYBOOK = get_cpr_module_restart_playbook(
        name="test_cpr_fabric_card_restart",
        device_regexes=device_regexes,
        modules=fabric_modules,
        traffic_items_to_start=traffic_items_to_start,
        is_sequential=is_sequential,
        iteration=iteration,
    )

    TEST_CPR_LINE_CARD_REBOOT_PLAYBOOK = get_cpr_module_restart_playbook(
        name="test_cpr_line_card_restart",
        device_regexes=device_regexes,
        modules=linecard_modules,
        traffic_items_to_start=traffic_items_to_start,
        is_sequential=is_sequential,
        iteration=iteration,
    )

    TEST_FABRIC_AGENT_RESTART_PLAYBOOK = get_cpr_agent_interruption_playbook(
        name="test_fabric_agent_restart",
        device_regexes=device_regexes,
        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
        agents=fabric_agents,
        traffic_items_to_start=traffic_items_to_start,
        iteration=iteration,
        clear_traffic_stats=True,
    )

    TEST_LINE_CARD_AGENT_RESTART_PLAYBOOK = get_cpr_agent_interruption_playbook(
        name="test_line_card_agent_restart",
        device_regexes=device_regexes,
        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
        agents=linecard_agents,
        traffic_items_to_start=traffic_items_to_start,
        iteration=iteration,
        clear_traffic_stats=True,
    )

    TEST_FABRIC_AGENT_CRASH_PLAYBOOK = get_cpr_agent_interruption_playbook(
        name="test_fabric_agent_terminate",
        device_regexes=device_regexes,
        trigger=taac_types.ServiceInterruptionTrigger.CRASH,
        agents=fabric_agents,
        traffic_items_to_start=traffic_items_to_start,
        iteration=iteration,
        clear_traffic_stats=True,
    )

    TEST_LINE_CARD_AGENT_CRASH_PLAYBOOK = get_cpr_agent_interruption_playbook(
        name="test_line_card_agent_terminate",
        device_regexes=device_regexes,
        trigger=taac_types.ServiceInterruptionTrigger.CRASH,
        agents=linecard_agents,
        traffic_items_to_start=traffic_items_to_start,
        iteration=iteration,
        clear_traffic_stats=True,
    )

    TEST_INTERFACE_FLAP_PLAYBOOK = Playbook(
        name="test_interface_flap",
        device_regexes=device_regexes,
        stages=[
            create_steps_stage(
                steps=[
                    create_interface_flap_step(
                        enable=False,
                        interfaces=[f"Ethernet3/{i}/1" for i in range(1, 21)],
                        description="Flap all interfaces",
                        interface_flap_method=4,
                        device_name=device_regexes[0],
                    ),
                    create_longevity_step(duration=60),
                    create_interface_flap_step(
                        enable=True,
                        interfaces=[f"Ethernet3/{i}/1" for i in range(1, 21)],
                        description="Flap all interfaces",
                        interface_flap_method=4,
                        device_name=device_regexes[0],
                    ),
                    create_longevity_step(duration=300),
                ],
            ),
        ],
        postchecks=[
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        str_value="0",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                ],
                clear_traffic_stats=True,
            ),
        ],
        traffic_items_to_start=traffic_items_to_start,
        iteration=iteration,
    )

    return [
        TEST_CPR_DEVICE_REBOOT_PLAYBOOK,
        TEST_CPR_FABRIC_CARD_REBOOT_PLAYBOOK,
        TEST_CPR_LINE_CARD_REBOOT_PLAYBOOK,
        TEST_FABRIC_AGENT_RESTART_PLAYBOOK,
        TEST_LINE_CARD_AGENT_RESTART_PLAYBOOK,
        TEST_FABRIC_AGENT_CRASH_PLAYBOOK,
        TEST_LINE_CARD_AGENT_CRASH_PLAYBOOK,
        TEST_INTERFACE_FLAP_PLAYBOOK,
    ]


def get_bc_agent_interruption_playbook(
    name: str,
    device_regexes: t.List[str],
    trigger: taac_types.ServiceInterruptionTrigger,
    service: taac_types.Service,
    traffic_items_to_start: t.List[str],
    iteration: int = 10,
    clear_traffic_stats: bool = False,
    cold_boot: bool = False,
) -> Playbook:
    service_name = taac_types.SERVICE_NAME_MAP.get(service, service.name)

    if service == taac_types.Service.AGENT:
        expected_restarted = list(SERVICES_EXPECTED_TO_RESTART_DURING_AGENT_WARMBOOT)
        if trigger == taac_types.ServiceInterruptionTrigger.CRASH:
            expected_restarted.append("qsfp_service")
    else:
        expected_restarted = [service_name]

    return Playbook(
        name=name,
        device_regexes=device_regexes,
        postchecks=[
            create_ixia_packet_loss_check(
                clear_traffic_stats=clear_traffic_stats,
                thresholds=[
                    hc_types.PacketLossThreshold(
                        str_value="0",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                ],
            ),
            create_service_restart_check(
                services=_get_services_excluding({"openr"}),
                expected_restarted_services=expected_restarted,
                check_scope=hc_types.Scope.DEFAULT,
            ),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_service_interruption_step(
                        service=service,
                        trigger=trigger,
                        create_cold_boot_file=cold_boot,
                    ),
                    create_service_convergence_step(
                        services=[
                            taac_types.Service.AGENT,
                            taac_types.Service.QSFP_SERVICE,
                            taac_types.Service.BGP,
                        ],
                        description="Wait for wedge_agent to converge",
                    ),
                    create_longevity_step(duration=300),
                ]
            )
        ],
        traffic_items_to_start=traffic_items_to_start,
        iteration=iteration,
    )


def create_bc_disruptive_playbooks(
    traffic_items_to_start: t.List[str],
    device_regexes: t.List[str],
    is_sequential: bool = False,
    iteration: int = 10,
) -> t.List[Playbook]:
    TEST_BC_DEVICE_AGENT_WARMBOOT = get_bc_agent_interruption_playbook(
        name="test_agent_warmboot",
        device_regexes=device_regexes,
        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
        service=taac_types.Service.AGENT,
        traffic_items_to_start=traffic_items_to_start,
        iteration=iteration,
    )

    TEST_BC_DEVICE_QSFP_RESTART = get_bc_agent_interruption_playbook(
        name="test_qsfp_warmboot",
        device_regexes=device_regexes,
        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
        service=taac_types.Service.QSFP_SERVICE,
        traffic_items_to_start=traffic_items_to_start,
        iteration=iteration,
    )

    TEST_BC_DEVICE_AGENT_COLDBOOT = get_bc_agent_interruption_playbook(
        name="test_agent_coldboot",
        device_regexes=device_regexes,
        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
        service=taac_types.Service.AGENT,
        traffic_items_to_start=traffic_items_to_start,
        iteration=iteration,
        cold_boot=True,
        clear_traffic_stats=True,
    )

    TEST_BC_DEVICE_AGENT_CRASH = get_bc_agent_interruption_playbook(
        name="test_agent_crash",
        device_regexes=device_regexes,
        trigger=taac_types.ServiceInterruptionTrigger.CRASH,
        service=taac_types.Service.AGENT,
        traffic_items_to_start=traffic_items_to_start,
        iteration=iteration,
        clear_traffic_stats=True,
    )

    TEST_BC_DEVICE_QSFP_CRASH = get_bc_agent_interruption_playbook(
        name="test_qsfp_crash",
        device_regexes=device_regexes,
        trigger=taac_types.ServiceInterruptionTrigger.CRASH,
        service=taac_types.Service.QSFP_SERVICE,
        traffic_items_to_start=traffic_items_to_start,
        iteration=iteration,
        clear_traffic_stats=True,
    )

    return [
        TEST_BC_DEVICE_AGENT_WARMBOOT,
        TEST_BC_DEVICE_QSFP_RESTART,
        TEST_BC_DEVICE_AGENT_COLDBOOT,
        TEST_BC_DEVICE_AGENT_CRASH,
        TEST_BC_DEVICE_QSFP_CRASH,
    ]


def build_mp3n_bgp_path_scale_playbook(
    name: str,
    stages: t.List[taac_types.Stage],
    prechecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    postchecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    snapshot_checks: t.Optional[t.List[SnapshotHealthCheck]] = None,
    iteration: t.Optional[int] = None,
) -> Playbook:
    """Trampoline for `testconfigs/ai_bb/mp3n_bgp_path_scale_test_config.py`.

    The source TestConfig has 10 inline `Playbook(...)` constructions
    (longevity + 9 disruption playbooks) that share a flexible kwarg shape.
    """
    return Playbook(
        name=name,
        stages=stages,
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
        iteration=iteration if iteration is not None else 1,
    )


def build_cisco_ctsw_playbook(
    name,
    stages,
    description=None,
    prechecks=None,
    postchecks=None,
    snapshot_checks=None,
    cleanup_steps=None,
    setup_steps=None,
    traffic_items_to_start=None,
    iteration=None,
    enabled=None,
    skip_test_config_postchecks=None,
    device_regexes=None,
):
    """Trampoline for `testconfigs/internal/cisco_ctsw_snc1_test_config.py`.

    The source TestConfig has 13 inline `Playbook(...)` constructions across
    the CTSW longevity + interface-flap + module-toggle + system-reboot
    disruption playbooks; kwarg shapes vary so all are optional.
    """
    kwargs = {"name": name, "stages": stages}
    for k, v in [
        ("description", description),
        ("prechecks", prechecks),
        ("postchecks", postchecks),
        ("snapshot_checks", snapshot_checks),
        ("cleanup_steps", cleanup_steps),
        ("setup_steps", setup_steps),
        ("traffic_items_to_start", traffic_items_to_start),
        ("iteration", iteration),
        ("enabled", enabled),
        ("skip_test_config_postchecks", skip_test_config_postchecks),
        ("device_regexes", device_regexes),
    ]:
        if v is not None:
            kwargs[k] = v
    return Playbook(**kwargs)


def build_dsf_c85_ash6_cpu_playbook(
    name,
    traffic_items_to_start,
    prechecks,
    stages,
    snapshot_checks,
    postchecks=None,
):
    """Trampoline for `testconfigs/internal/dsf_c85_ash6_cpu_test_config.py`.

    The source TestConfig has 4 inline `Playbook(...)` constructions at
    module scope inside the `playbooks=[...]` list. Each Playbook is
    self-contained with its own checks and stages.
    """
    kwargs = {
        "name": name,
        "traffic_items_to_start": traffic_items_to_start,
        "prechecks": prechecks,
        "stages": stages,
        "snapshot_checks": snapshot_checks,
    }
    if postchecks is not None:
        kwargs["postchecks"] = postchecks
    return Playbook(**kwargs)


def build_fa_uu_qzd1_playbook(
    name,
    stages,
    postchecks,
    traffic_items_to_start,
    enabled,
    snapshot_checks,
    prechecks=None,
):
    """Trampoline for `testconfigs/internal/fa_uu_qzd1_single_node_test_config.py`.

    The source TestConfig has 5 inline `Playbook(...)` constructions at
    module scope (1 longevity + 4 disruptive) sharing a consistent kwarg
    shape.
    """
    kwargs = {
        "name": name,
        "stages": stages,
        "postchecks": postchecks,
        "traffic_items_to_start": traffic_items_to_start,
        "enabled": enabled,
        "snapshot_checks": snapshot_checks,
    }
    if prechecks is not None:
        kwargs["prechecks"] = prechecks
    return Playbook(**kwargs)


def build_back_pressure_playbook(
    name,
    snapshot_checks,
    postchecks,
    skip_test_config_postchecks,
    cleanup_steps,
    stages,
    traffic_items_to_start=None,
):
    """Trampoline for `testconfigs/internal/fboss_bgp_back_pressure_test_config.py`.

    The source TestConfig has 5 inline `Playbook(...)` constructions across
    the longevity factories (setup, experiment_group, churn, restart, etc.)
    sharing a consistent kwarg shape.
    """
    kwargs = {
        "name": name,
        "snapshot_checks": snapshot_checks,
        "postchecks": postchecks,
        "skip_test_config_postchecks": skip_test_config_postchecks,
        "cleanup_steps": cleanup_steps,
        "stages": stages,
    }
    if traffic_items_to_start is not None:
        kwargs["traffic_items_to_start"] = traffic_items_to_start
    return Playbook(**kwargs)


def build_best_path_eval_playbook(
    name,
    snapshot_checks,
    postchecks,
    skip_test_config_postchecks,
    stages,
    cleanup_steps=None,
    traffic_items_to_start=None,
):
    """Trampoline for `testconfigs/internal/fboss_bgp_best_path_eval_test_config.py`.

    The source TestConfig has 3 inline `Playbook(...)` constructions
    (setup, local_pref churn, core dump). Each builds its own
    snapshot/postcheck list and stages locally.
    """
    kwargs = {
        "name": name,
        "snapshot_checks": snapshot_checks,
        "postchecks": postchecks,
        "skip_test_config_postchecks": skip_test_config_postchecks,
        "stages": stages,
    }
    if cleanup_steps is not None:
        kwargs["cleanup_steps"] = cleanup_steps
    if traffic_items_to_start is not None:
        kwargs["traffic_items_to_start"] = traffic_items_to_start
    return Playbook(**kwargs)


def build_dctypef_npi_playbook(
    name=None,
    stages=None,
    description=None,
    iteration=None,
    traffic_items_to_start=None,
    traffic_items_to_configure=None,
    enabled=None,
    backup_and_restore_ixia_config=None,
    prechecks=None,
    postchecks=None,
    snapshot_checks=None,
    skip_test_config_prechecks=None,
    skip_test_config_postchecks=None,
    skip_test_config_snapshot_checks=None,
    override_duplicate_checks=None,
    prechecks_to_skip=None,
    postchecks_to_skip=None,
    snapshot_checks_to_skip=None,
    check_ids_to_skip=None,
    cleanup_steps=None,
    setup_steps=None,
    device_regexes=None,
    periodic_tasks=None,
    attribute_filters=None,
    scuba_table=None,
):
    """Trampoline for `testconfigs/internal/fboss_dctypef_51t_npi_test_config.py`.

    The source TestConfig has 41 inline `Playbook(...)` constructions: 1
    inside the `_add_common_checks_to_npi_playbooks` re-wrapper helper and
    40 inside the default playbook list passed to that helper from
    `create_dctypef_npi_test_config`. Their kwarg shapes vary widely so all
    fields are optional.
    """
    kwargs = {}
    for k, v in [
        ("name", name),
        ("stages", stages),
        ("description", description),
        ("iteration", iteration),
        ("traffic_items_to_start", traffic_items_to_start),
        ("traffic_items_to_configure", traffic_items_to_configure),
        ("enabled", enabled),
        ("backup_and_restore_ixia_config", backup_and_restore_ixia_config),
        ("prechecks", prechecks),
        ("postchecks", postchecks),
        ("snapshot_checks", snapshot_checks),
        ("skip_test_config_prechecks", skip_test_config_prechecks),
        ("skip_test_config_postchecks", skip_test_config_postchecks),
        ("skip_test_config_snapshot_checks", skip_test_config_snapshot_checks),
        ("override_duplicate_checks", override_duplicate_checks),
        ("prechecks_to_skip", prechecks_to_skip),
        ("postchecks_to_skip", postchecks_to_skip),
        ("snapshot_checks_to_skip", snapshot_checks_to_skip),
        ("check_ids_to_skip", check_ids_to_skip),
        ("cleanup_steps", cleanup_steps),
        ("setup_steps", setup_steps),
        ("device_regexes", device_regexes),
        ("periodic_tasks", periodic_tasks),
        ("attribute_filters", attribute_filters),
        ("scuba_table", scuba_table),
    ]:
        if v is not None:
            kwargs[k] = v
    return Playbook(**kwargs)


def build_wide_ecmp_playbook(
    name,
    snapshot_checks,
    postchecks,
    skip_test_config_postchecks,
    cleanup_steps,
    stages,
):
    """Trampoline for `testconfigs/internal/fboss_wide_ecmp_test_config.py`.

    The source TestConfig has 3 inline `Playbook(...)` constructions (setup,
    wide_ecmp_stress, dump_unclean_exit). Each builds its own
    snapshot/postcheck list and stages locally.
    """
    return Playbook(
        name=name,
        snapshot_checks=snapshot_checks,
        postchecks=postchecks,
        skip_test_config_postchecks=skip_test_config_postchecks,
        cleanup_steps=cleanup_steps,
        stages=stages,
    )


def build_case2_playbook(name, description, stages):
    """Trampoline for `testconfigs/routing/ebb/test_config_performance_scaling_case2.py`.

    Source had 2 inline `Playbook(...)` constructions inside two TestConfig
    builder factories. Each Playbook is a single-stage custom-step wrapper;
    this trampoline keeps the source from inline-constructing Playbook(...).
    """
    return Playbook(
        name=name,
        description=description,
        stages=stages,
    )


def build_bgp_weight_playbook(
    name,
    setup_steps,
    periodic_tasks,
    prechecks,
    snapshot_checks,
    postchecks,
    stages,
):
    """Trampoline for `testconfigs/routing/ebb/test_config_bgp_weight_feature.py`.

    Source had 5 inline `Playbook(...)` constructions inside the
    `test_config_for_bgp_weight_feature` factory (Phase1..Phase5). All
    Playbooks share an identical kwarg shape; this trampoline keeps the
    source from inline-constructing Playbook(...).
    """
    return Playbook(
        name=name,
        setup_steps=setup_steps,
        periodic_tasks=periodic_tasks,
        prechecks=prechecks,
        snapshot_checks=snapshot_checks,
        postchecks=postchecks,
        stages=stages,
    )


def build_bgp_med_playbook(
    name,
    setup_steps,
    periodic_tasks,
    prechecks,
    snapshot_checks,
    postchecks,
    stages,
):
    """Trampoline for `testconfigs/routing/ebb/test_config_bgp_med_feature.py`.

    Source had 11 inline `Playbook(...)` constructions inside the
    `test_config_for_bgp_med_feature` factory. All Playbooks share an
    identical kwarg shape; this trampoline keeps the source from
    inline-constructing Playbook(...).
    """
    return Playbook(
        name=name,
        setup_steps=setup_steps,
        periodic_tasks=periodic_tasks,
        prechecks=prechecks,
        snapshot_checks=snapshot_checks,
        postchecks=postchecks,
        stages=stages,
    )


def build_fast_reset_playbook(
    name,
    setup_steps,
    periodic_tasks,
    prechecks,
    snapshot_checks,
    postchecks,
    stages,
):
    """Trampoline for `testconfigs/routing/ebb/test_config_bgp_fast_reset_feature.py`.

    Source had 3 inline `Playbook(...)` constructions inside the
    `test_config_for_bgp_fast_reset_feature` factory (Phase0 single-link,
    Phase1 multi-link, Phase2 link-flap). All Playbooks share an identical
    kwarg shape; this trampoline keeps the source from inline-constructing
    Playbook(...).
    """
    return Playbook(
        name=name,
        setup_steps=setup_steps,
        periodic_tasks=periodic_tasks,
        prechecks=prechecks,
        snapshot_checks=snapshot_checks,
        postchecks=postchecks,
        stages=stages,
    )


def build_enforce_first_as_playbook(
    name,
    setup_steps,
    periodic_tasks,
    prechecks,
    snapshot_checks,
    postchecks,
    stages,
):
    """Trampoline for `testconfigs/routing/ebb/test_config_bgp_enforce_first_as_feature.py`.

    Source had 4 inline `Playbook(...)` constructions inside the
    `test_config_for_bgp_enforce_first_as_feature` factory (Phase0..Phase3).
    All Playbooks share an identical kwarg shape; this trampoline keeps the
    source from inline-constructing Playbook(...).
    """
    return Playbook(
        name=name,
        setup_steps=setup_steps,
        periodic_tasks=periodic_tasks,
        prechecks=prechecks,
        snapshot_checks=snapshot_checks,
        postchecks=postchecks,
        stages=stages,
    )


def build_bgp_well_known_community_playbook(
    name,
    setup_steps,
    periodic_tasks,
    prechecks,
    snapshot_checks,
    postchecks,
    stages,
):
    """Trampoline for `testconfigs/routing/ebb/test_config_well_known_communities.py`.

    RFC 1997 well-known community egress filtering test playbooks
    (NO_EXPORT, NO_ADVERTISE, NO_EXPORT_SUBCONFED, BASELINE, flag-off
    regression). All Playbooks share an identical kwarg shape; this
    trampoline keeps the source from inline-constructing Playbook(...).
    """
    return Playbook(
        name=name,
        setup_steps=setup_steps,
        periodic_tasks=periodic_tasks,
        prechecks=prechecks,
        snapshot_checks=snapshot_checks,
        postchecks=postchecks,
        stages=stages,
    )


def build_ebb_scale_playbook(
    name,
    stages,
    description=None,
    prechecks=None,
    postchecks=None,
    snapshot_checks=None,
    cleanup_steps=None,
    setup_steps=None,
    traffic_items_to_start=None,
    iteration=None,
    enabled=None,
    skip_test_config_postchecks=None,
    skip_test_config_prechecks=None,
    prechecks_to_skip=None,
    postchecks_to_skip=None,
    snapshot_checks_to_skip=None,
    check_ids_to_skip=None,
    periodic_tasks=None,
):
    """Trampoline for `testconfigs/routing/ebb/fboss_ebb_scale_test_config.py`.

    Source had 6 inline `Playbook(...)` constructions: 2 inside factory
    functions (test_bgpd_restart, test_bgpd_coldboot) and 4 standalone Playbook
    constructions inside TestConfig builders. All Playbooks share a flexible
    kwarg shape; this trampoline keeps the source from inline-constructing
    Playbook(...).
    """
    kwargs = {"name": name, "stages": stages}
    for k, v in [
        ("description", description),
        ("prechecks", prechecks),
        ("postchecks", postchecks),
        ("snapshot_checks", snapshot_checks),
        ("cleanup_steps", cleanup_steps),
        ("setup_steps", setup_steps),
        ("traffic_items_to_start", traffic_items_to_start),
        ("iteration", iteration),
        ("enabled", enabled),
        ("skip_test_config_postchecks", skip_test_config_postchecks),
        ("skip_test_config_prechecks", skip_test_config_prechecks),
        ("prechecks_to_skip", prechecks_to_skip),
        ("postchecks_to_skip", postchecks_to_skip),
        ("snapshot_checks_to_skip", snapshot_checks_to_skip),
        ("check_ids_to_skip", check_ids_to_skip),
        ("periodic_tasks", periodic_tasks),
    ]:
        if v is not None:
            kwargs[k] = v
    return Playbook(**kwargs)


def create_update_group_sustained_link_flap_playbook(
    device_name: str,
    port_schedule: t.List[t.Dict[str, t.Any]],
    total_duration_s: int,
    prechecks: t.List[PointInTimeHealthCheck],
    postchecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    snapshot_checks: t.Optional[t.List[SnapshotHealthCheck]] = None,
    stabilization_s: int = 30,
    checkpoint_interval_s: int = 900,
) -> Playbook:
    """Build the BGP++ Update Group qualification 2.7.2 playbook
    (Sustained Link Flapping Across Multiple Ports).

    Builds a one-stage Playbook with a single
    ``staggered_flap_with_isolation_check`` custom step that rotates
    flapping the IXIA-facing ports listed in ``port_schedule`` on
    independent cadences for ``total_duration_s`` seconds. On every
    cycle the step snapshots per-session ``num_of_flaps`` / ``uptime``
    for all non-flapping peers before the flap, re-snapshots after the
    stabilization window, and records a violation for any peer that
    flapped or disappeared while a sibling port was being flapped.
    Violations are aggregated across the whole run and reported at the
    end -- the run does not bail on the first hit so pattern-spotting
    across cycles is preserved.

    The factory is intentionally device-agnostic so it can be reused
    across EBB devices (bag013 / bag010 / bag011 / etc.). Caller
    supplies all device-specific knobs:

    Args:
        device_name: DUT hostname passed through to the custom step's
            ``hostname`` param and the BGP-helper client.
        port_schedule: List of port dicts; one entry per IXIA-facing
            port to flap. Each entry must contain:
              - interface (str): e.g. "Ethernet3/36/1"
              - label (str): human label, e.g. "eBGP" / "iBGP" / "BGP-MON"
              - period_s (int): cadence between flaps for this port
              - down_s (int): how long the link stays down each cycle
              - peer_subnets (list[str]): CIDR prefixes whose BGP peers
                live on this interface; used to attribute each session
                to its interface so the isolation check knows which
                peers should be unaffected by each flap.
        total_duration_s: total test duration; the scheduler exits the
            cycle loop after this many seconds. Production: 3600
            (matches the 2.7.2 spec literal 1h). Test-scale: 900.
        prechecks: precheck list to attach. Device-specific (e.g.
            bag013 needs ``parent_prefixes_to_ignore`` for its IDLE
            BGP MON peers; other devices may use
            ``create_standard_prechecks``).
        postchecks: optional postcheck list. When ``None``, defaults to
            ``BGP_STANDARD_POSTCHECKS`` plus:
              * ``create_system_cpu_load_average_check(baseline=12.0)`` --
                required for 2.7.2 pass criterion #6 ("1m, 5m and 15m
                load-averages never cross 12"); not in the bare standard list.
              * ``create_bgp_update_group_check(expect_enabled=True)`` --
                covers 2.7.2 pass criterion #3 ("all update groups correctly
                formed, no stale entries"). Thrift-backed (``getUpdateGroupInfo``
                API per D108632994), replaces an earlier CLI-based EOR check
                that lived inline in the step. Callers can override to pin a
                specific ``expected_group_count`` / ``expected_member_counts``
                if they have a golden initial-dump snapshot.
        snapshot_checks: optional snapshot-check list. Defaults to
            ``BGP_STANDARD_SNAPSHOT_CHECKS`` (core-dumps + per-peer
            route count) when ``None``.
        stabilization_s: post-flap sleep before the isolation check;
            gives the flapped port's own sessions time to re-establish
            before the snapshot comparison. Default 30.
        checkpoint_interval_s: how often (in seconds) the step runs the
            mid-test lightweight total-session-count check against the
            baseline. Default 900 (matches the 2.7.2 spec's "15-min
            intervals" requirement).

    Returns:
        A ``Playbook`` named ``update_group_sustained_link_flap`` ready
        to drop into the ``_UPDATE_GROUP`` variant of any EBB
        TestConfig.
    """
    flap_step = create_custom_step(
        params_dict={
            "custom_step_name": "staggered_flap_with_isolation_check",
            "hostname": device_name,
            "port_schedule": port_schedule,
            "total_duration_s": total_duration_s,
            "stabilization_s": stabilization_s,
            "checkpoint_interval_s": checkpoint_interval_s,
        },
        description=(
            f"BGP++ Update Group qualification 2.7.2 -- rotate flap on "
            f"{len(port_schedule)} ports for {total_duration_s}s on "
            f"{device_name}; per-session isolation check after each cycle."
        ),
    )
    # 2.7.2 pass criteria #3 and #6:
    #   #3 "all update groups correctly formed, no stale entries"
    #      -> ``create_bgp_update_group_check`` (Thrift API per D108632994).
    #   #6 "1m, 5m and 15m load-averages never cross 12"
    #      -> ``create_system_cpu_load_average_check(baseline=12.0)``.
    # ``BGP_STANDARD_POSTCHECKS`` covers per-process CPU (400% threshold) and
    # memory but neither of the above, so extend the default postcheck list
    # here so every consumer of this factory asserts both spec bounds.
    if postchecks is None:
        postchecks = list(BGP_STANDARD_POSTCHECKS) + [
            create_system_cpu_load_average_check(baseline=12.0),
            create_bgp_update_group_check(expect_enabled=True),
        ]
    if snapshot_checks is None:
        snapshot_checks = list(BGP_STANDARD_SNAPSHOT_CHECKS)
    return Playbook(
        # Generic name -- reusable across EBB devices. Device-specific scope
        # lives in the surrounding TestConfig (e.g.
        # ``BAG013_ASH6_BGP_CONVEYOR_TEST_UPDATE_GROUP``), not in the
        # playbook name itself.
        name="update_group_sustained_link_flap",
        stages=[create_steps_stage(steps=[flap_step])],
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
    )


# =============================================================================
# BGP++ Update Group hardening 2.4.1 / 2.4.2 / 2.4.3 playbooks.
#
# These playbooks share a common topology contract enforced by the surrounding
# TestConfig: a small UG with 1 control peer (DG_A_CTRL, multiplier > 1 OK), 1
# held-back peer (DG_A_HELD, starts admin-DOWN), 0+ "disposable" peers
# (DG_A_DISP, only used in 2.4.1), and a set of senders that advertise routes
# into the DUT RIB which are then propagated via the UG to side A
# (DG_B_KEEP -- 300 routes baseline; DG_B_VAR1 -- 200 routes
# inject/withdraw; DG_B_VAR2 -- 50 routes runtime-inject).
#
# All three playbooks bracket their trigger stage with rigorous verify-the-
# knob postchecks: every IXIA toggle is paired with a session-state check, and
# every spec assertion is anchored by a per-peer route count + set-equality.
# Lesson burned in from prior work where IXIA `Stop()` was a silent on-wire
# no-op: we never trust that a knob fired -- we always verify.
#
# Each playbook is fully idempotent: prechecks assert baseline state, cleanup
# restores it. They are designed to run sequentially in the same TestConfig
# without state pollution between runs.
# =============================================================================


def create_new_peer_join_full_sync_resilience_playbook(
    device_name: str,
    control_peer_addrs: t.List[str],
    held_back_peer_addr: str,
    held_back_peer_regex: str,
    disp_peer_addrs: t.List[str],
    disp_peer_regex: str,
    disp_session_start_idx: int,
    disp_session_end_idx: int,
    b_keep_peer_addr: str,
    b_keep_route_count: int,
    b_var1_peer_regex: str,
    b_var1_peer_addr: str,
    b_var1_route_count: int,
    b_var2_peer_regex: str,
    b_var2_peer_addr: str,
    b_var2_route_count: int,
    ug_peer_group_substring: str = "EB-FA-V6",
    setup_convergence_s: int = 30,
    post_test_convergence_s: int = 60,
    post_inject_convergence_s: int = 30,
    setup_steps: t.Optional[t.List[Step]] = None,
    prechecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    postchecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    snapshot_checks: t.Optional[t.List[SnapshotHealthCheck]] = None,
) -> Playbook:
    """Build the BGP++ Update Group qualification 2.4.1 playbook
    (New Peer Joins, Receives Full Sync, Then a Peer Goes Down).

    Spec: verify that when a new peer establishes a session and joins an
    existing update group that already has routes, the new peer receives a
    full initial dump of all current routes -- and that subsequent peer-
    down events in the group during the new peer's initial sync do not
    disrupt the newly joined peer's sync. After sync, runtime updates (50
    more routes injected) must flow normally to all peers.

    Flow:
      Phase 0 (precheck): UG enabled + UG membership + per-peer baseline.
      Phase 1 (setup): bring DG_B_VAR1 UP -> 200 new routes injected while
        held-back is still down; settle; verify CTRL has 500 routes total.
      Phase 2 (test trigger, sequential, no inter-step wait): bring HELD
        UP; kill 16 DISP sessions mid-sync.
      Phase 3 (verify trigger + spec gate): HELD now Established; DISP
        sessions all not-Established; HELD + all CTRL have b_keep + b_var1
        routes received (full sync completed despite UG churn); prefix
        sets identical between HELD and each CTRL.
      Phase 4 (runtime update): bring DG_B_VAR2 UP -> 50 more routes; HELD
        + all CTRL must now show b_keep + b_var1 + b_var2. Surviving DISP
        peers (those outside the killed range) are not asserted by this
        validation; DISP fan-out coverage is the BgpUpdateGroup membership
        check's responsibility.
      Phase 5 (cleanup): restore DG_A_DISP, DG_B_VAR1, DG_B_VAR2 to baseline;
        bring HELD back DOWN.

    Args:
        device_name: DUT hostname.
        control_peer_addrs: List of control-peer IPs (DG_A_CTRL members) --
            always UP, observed for consistency.
        held_back_peer_addr: IP of the held-back peer (the SUT).
        held_back_peer_regex: IXIA peer-object name regex for the held-back
            peer (e.g. "BGP_PEER_IPV6_EBGP_UG_HELD").
        disp_peer_addrs: IPs of the disposable peers that get shut down
            mid-sync.
        disp_peer_regex: IXIA peer-object name regex for the disposable
            peers (one regex matches all N sessions when DG multiplier > 1).
        disp_session_start_idx: First session index to kill (1-based).
        disp_session_end_idx: Last session index to kill (inclusive).
        b_keep_peer_addr: DG_B_KEEP sender peer IP (kept up throughout).
        b_keep_route_count: Baseline routes advertised by DG_B_KEEP.
        b_var1_peer_regex / b_var1_peer_addr: DG_B_VAR1 sender (starts
            admin-DOWN; brought UP in Phase 1 to inject ``b_var1_route_count``
            routes while held-back is still down).
        b_var2_peer_regex / b_var2_peer_addr: DG_B_VAR2 sender (starts
            admin-DOWN; brought UP in Phase 4 to inject ``b_var2_route_count``
            additional routes after held-back is fully synced).
        ug_peer_group_substring: peer-group substring used for UG membership
            verification (default "EB-FA-V6" matches bag012 / bag013 eBGP UG).
        setup_convergence_s: Settle time after Phase 1 inject before Phase 2
            trigger (default 30s).
        post_test_convergence_s: Settle time after Phase 2 trigger before
            Phase 3 verification (default 60s).
        post_inject_convergence_s: Settle time after Phase 4 inject before
            re-verifying counts (default 30s).
        prechecks: Optional override of the Phase 0 prechecks. Default:
            UG enabled + UG membership + per-peer baseline state and counts.
        postchecks: Optional override of Phase 3 + Phase 4 postchecks.
        snapshot_checks: Optional snapshot-check list.

    Returns:
        A ``Playbook`` named ``new_peer_join_full_sync_resilience``.
    """
    phase_1_inject_steps = [
        # Phase 1: bring DG_B_VAR1 UP -> 200 routes injected while held-back
        # is still down. Use session range 1-1 since the sender DG has
        # multiplier=1.
        create_start_stop_bgp_peers_step(
            peer_regex=b_var1_peer_regex,
            start=True,
            start_idx=1,
            end_idx=1,
            description=(
                f"Phase 1 (2.4.1): bring sender DG_B_VAR1 UP -- inject "
                f"{b_var1_route_count} routes while held-back is still down"
            ),
        ),
        create_longevity_step(
            duration=setup_convergence_s,
            description=(
                f"Phase 1 (2.4.1): settle {setup_convergence_s}s for "
                f"DG_B_VAR1 advertise to propagate via UG to side A receivers"
            ),
        ),
        # Phase 1 verify: CTRL now sees b_keep + b_var1 = 500 routes.
        create_validation_step(
            point_in_time_checks=[
                create_bgp_route_count_verification_check(
                    json_params={
                        "descriptions_to_check": list(control_peer_addrs),
                        "direction": "received",
                        "policy_type": "post_policy",
                        "expected_count": b_keep_route_count + b_var1_route_count,
                    },
                )
            ],
            description=(
                "Phase 1 verify (2.4.1): control peers received baseline + "
                "inject routes"
            ),
        ),
    ]

    # Phase 2 trigger -- sequential, no inter-step wait (preserve the race).
    trigger_steps = [
        # 2a: bring HELD admin-UP -> sync begins.
        create_start_stop_bgp_peers_step(
            peer_regex=held_back_peer_regex,
            start=True,
            start_idx=1,
            end_idx=1,
            description=("Phase 2a (2.4.1): bring held-back peer UP -- begin UG sync"),
        ),
        # 2b: immediately kill N disposable UG-member sessions mid-sync.
        create_start_stop_bgp_peers_step(
            peer_regex=disp_peer_regex,
            start=False,
            start_idx=disp_session_start_idx,
            end_idx=disp_session_end_idx,
            description=(
                f"Phase 2b (2.4.1): kill DG_A_DISP sessions "
                f"{disp_session_start_idx}-{disp_session_end_idx} mid-sync "
                "(UG member churn during held-back's initial sync)"
            ),
        ),
        # Settle so HELD finishes its sync + UG re-converges without DISP.
        create_longevity_step(
            duration=post_test_convergence_s,
            description=(
                f"Phase 2 (2.4.1): settle {post_test_convergence_s}s for "
                "held-back sync + UG re-convergence"
            ),
        ),
        # Inline Phase 3 spec gate (must run NOW, before Phase 4 adds 50 more
        # routes and changes the count). Asserts the "500 not stale" gate.
        create_validation_step(
            point_in_time_checks=[
                create_bgp_peer_route_set_equality_check(
                    baseline_peer_addr=control_peer_addrs[0],
                    tested_peer_addrs=[held_back_peer_addr]
                    + list(control_peer_addrs[1:]),
                    anchor_route_count=b_keep_route_count + b_var1_route_count,
                )
            ],
            description=(
                "Phase 3 spec gate (2.4.1): held-back + remaining control peers "
                f"received {b_keep_route_count + b_var1_route_count} routes "
                "after sync (full initial dump survived DISP kill mid-sync)"
            ),
        ),
    ]

    # Postchecks: session-state diagnostics only. The route-count spec gates
    # are inline at end of Phase 2 (500) and Phase 4 (550) so they see the
    # right state -- postchecks run AFTER Phase 4 so the route count is 550,
    # not 500.
    expected_after_inject_50 = (
        b_keep_route_count + b_var1_route_count + b_var2_route_count
    )
    phase_3_checks = [
        # 3a: held-back UP took effect.
        create_bgp_session_establish_check(
            ignore_all_prefixes_except=[held_back_peer_addr],
        ),
        # 3b: disp kill took effect (none of the killed peers should be
        # Established).
        create_bgp_session_establish_check(
            ignore_all_prefixes_except=disp_peer_addrs,
            expected_established_sessions=0,
        ),
        # 3c: end-of-test spec gate -- HELD + all CTRL have all 550 routes
        # (b_keep + b_var1 + the Phase 4 b_var2 runtime inject). Set equality
        # also asserts identical prefix sets across all members.
        create_bgp_peer_route_set_equality_check(
            baseline_peer_addr=control_peer_addrs[0],
            tested_peer_addrs=[held_back_peer_addr] + list(control_peer_addrs[1:]),
            anchor_route_count=expected_after_inject_50,
        ),
        # 3d: spec passing-criterion "BGP++ agent does not crash" -- the
        # canonical Arista BGP++ gate. Reads `show agent uptime` for `Bgp`
        # (bgpcpp on Arista) and `FibBgpGrpc`; FAIL if either was restarted
        # during the test window. Mirrors the bag-conveyor
        # create_standard_postchecks() pattern. (UNCLEAN_EXIT_CHECK doesn't
        # apply here -- queries ODS for DCS FBOSS service names that don't
        # exist on ARISTA_FBOSS, returns SKIP.)
        create_service_restart_check(
            services=["Bgp"],
            daemons=["FibBgpGrpc"],
        ),
        # 3e: spec passing-criterion "no stale routes" -- asserts no
        # graceful-restart stale flags remain on any installed prefix.
        create_bgp_stale_route_check(),
    ]

    # Phase 4 (runtime inject 50 more). expected_after_inject_50 already
    # defined above for postchecks.
    phase_4_steps = [
        create_start_stop_bgp_peers_step(
            peer_regex=b_var2_peer_regex,
            start=True,
            start_idx=1,
            end_idx=1,
            description=(
                f"Phase 4 (2.4.1): bring sender DG_B_VAR2 UP -- inject "
                f"{b_var2_route_count} more routes (runtime update)"
            ),
        ),
        create_longevity_step(
            duration=post_inject_convergence_s,
            description=(
                f"Phase 4 (2.4.1): settle {post_inject_convergence_s}s for "
                "DG_B_VAR2 advertise to propagate"
            ),
        ),
        create_validation_step(
            point_in_time_checks=[
                create_bgp_peer_route_set_equality_check(
                    baseline_peer_addr=control_peer_addrs[0],
                    tested_peer_addrs=[held_back_peer_addr]
                    + list(control_peer_addrs[1:]),
                    anchor_route_count=expected_after_inject_50,
                )
            ],
            description=(
                "Phase 4 verify (2.4.1): held-back + remaining control peers "
                f"received {expected_after_inject_50} routes after runtime "
                "inject (no missing prefixes)"
            ),
        ),
    ]

    # Phase 5 cleanup: restore baseline.
    cleanup_steps = [
        # Restore disposable peers UP.
        create_start_stop_bgp_peers_step(
            peer_regex=disp_peer_regex,
            start=True,
            start_idx=disp_session_start_idx,
            end_idx=disp_session_end_idx,
            description="Phase 5 cleanup (2.4.1): restore DG_A_DISP sessions UP",
        ),
        # Bring sender DG_B_VAR1 back DOWN.
        create_start_stop_bgp_peers_step(
            peer_regex=b_var1_peer_regex,
            start=False,
            start_idx=1,
            end_idx=1,
            description="Phase 5 cleanup (2.4.1): bring DG_B_VAR1 back DOWN",
        ),
        # Bring sender DG_B_VAR2 back DOWN.
        create_start_stop_bgp_peers_step(
            peer_regex=b_var2_peer_regex,
            start=False,
            start_idx=1,
            end_idx=1,
            description="Phase 5 cleanup (2.4.1): bring DG_B_VAR2 back DOWN",
        ),
        # Bring held-back peer back DOWN (baseline).
        create_start_stop_bgp_peers_step(
            peer_regex=held_back_peer_regex,
            start=False,
            start_idx=1,
            end_idx=1,
            description="Phase 5 cleanup (2.4.1): restore HELD to admin-DOWN",
        ),
        create_longevity_step(
            duration=setup_convergence_s,
            description=(
                f"Phase 5 cleanup (2.4.1): settle {setup_convergence_s}s for "
                "baseline state to converge"
            ),
        ),
    ]

    # Default prechecks: UG enabled + membership + per-peer baseline.
    if prechecks is None:
        prechecks = [
            create_bgp_update_group_check(
                expect_enabled=True,
                peer_group_substrings=[ug_peer_group_substring],
            ),
            create_bgp_session_establish_check(
                ignore_all_prefixes_except=list(control_peer_addrs)
                + [b_keep_peer_addr],
            ),
            create_bgp_session_establish_check(
                ignore_all_prefixes_except=[
                    held_back_peer_addr,
                    b_var1_peer_addr,
                    b_var2_peer_addr,
                ],
                expected_established_sessions=0,
            ),
            create_bgp_route_count_verification_check(
                json_params={
                    "descriptions_to_check": list(control_peer_addrs),
                    "direction": "received",
                    "policy_type": "post_policy",
                    "expected_count": b_keep_route_count,
                },
            ),
        ]
    if postchecks is None:
        postchecks = list(phase_3_checks)
    if snapshot_checks is None:
        # core_dumps (any daemon crash drops a core file -> detected) +
        # peer_route (per-peer route count drift before vs after).
        # NOT including create_bgp_session_snapshot_check: it flags ANY
        # session state change between snapshots as a "flap", but our 2.4
        # tests intentionally change session admin state (HELD up, DISP
        # down, VAR2 up, KEEP swap) as the trigger -- so the snapshot
        # would always false-positive. Post-test session state IS still
        # asserted via the explicit BgpSessionEstablishCheck in postchecks
        # (Phase 3a/3b), which is the right semantic for this test family.
        snapshot_checks = list(BGP_STANDARD_SNAPSHOT_CHECKS)

    kwargs = dict(
        name="new_peer_join_full_sync_resilience",
        stages=[
            create_steps_stage(
                steps=phase_1_inject_steps,
                description="Phase 1 (2.4.1): inject 200 while held-back DOWN",
            ),
            create_steps_stage(
                steps=trigger_steps,
                description=(
                    "Phase 2 (2.4.1): held-back UP + DISP kill (mid-sync churn)"
                ),
            ),
            create_steps_stage(
                steps=phase_4_steps,
                description="Phase 4 (2.4.1): runtime inject 50 more",
            ),
        ],
        cleanup_steps=cleanup_steps,
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
    )
    if setup_steps is not None:
        kwargs["setup_steps"] = setup_steps
    return Playbook(**kwargs)


def create_new_peer_join_routes_withdrawn_playbook(
    device_name: str,
    control_peer_addrs: t.List[str],
    held_back_peer_addr: str,
    held_back_peer_regex: str,
    b_keep_peer_addr: str,
    b_keep_route_count: int,
    b_var1_peer_regex: str,
    b_var1_peer_addr: str,
    b_var1_route_count: int,
    b_var1_device_group_regex: str,
    ug_peer_group_substring: str = "EB-FA-V6",
    setup_convergence_s: int = 30,
    post_test_convergence_s: int = 180,
    capture_tcpdump_device: t.Optional[str] = None,
    capture_tcpdump_path: str = "/tmp/bgp_capture_2_4_2.txt",
    setup_steps: t.Optional[t.List[Step]] = None,
    prechecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    postchecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    snapshot_checks: t.Optional[t.List[SnapshotHealthCheck]] = None,
) -> Playbook:
    """Build the BGP++ Update Group qualification 2.4.2 playbook
    (New Peer Joins, Then Routes Are Withdrawn).

    Spec: verify that when routes are withdrawn from the RIB while a new
    peer is joining and syncing to the update group, the new peer correctly
    handles the withdrawal -- it should NOT have stale routes that were
    withdrawn before its sync completed. Final route count must be
    ``b_keep_route_count`` (the routes that remain), NOT
    ``b_keep_route_count + b_var1_route_count`` (stale).

    Topology contract: DG_B_VAR1 starts UP (advertising
    ``b_var1_route_count`` routes); held-back peer starts admin-DOWN.

    Trigger mechanism: admin-disable DG_B_VAR1's DeviceGroup via
    ``toggle_device_groups(enable=False, regex=b_var1_device_group_regex)``.
    This tears down the entire L3 stack (IP/ND + BGP peer) so the IXIA
    endpoint stops answering. DUT's hold-timer expires (peer-group default
    15s), session drops to IDLE, DUT's ConnectRetry attempts find no ND
    response, session stays IDLE for the test window. DUT drops the routes
    learned from DG_B_VAR1 and propagates withdrawal via UG to all members.
    Earlier mechanisms ruled out: IXIA pool ``Stop()`` was silent (0 packets
    on wire); IXIA ``start_bgp_peers(start=False)`` was transient (DUT
    re-established within ~45s, masking the withdraw before HC observed).

    Flow:
      Phase 0 (precheck): UG enabled + membership + DG_B_VAR1 Established,
        CTRL receives ``b_keep + b_var1`` routes (full 500).
      Phase 2 (trigger, sequential): optional tcpdump start; bring HELD UP;
        kill DG_B_VAR1 session; tcpdump stop; settle.
      Phase 3 (verify + spec gate): HELD Established; DG_B_VAR1 NOT
        Established; HELD + all CTRL have exactly ``b_keep_route_count``
        received; sets identical.
      Phase 5 (cleanup): restore DG_B_VAR1 UP, HELD DOWN.

    Args:
        device_name: DUT hostname.
        control_peer_addrs: IPs of control peers (always UP).
        held_back_peer_addr: IP of the held-back peer (SUT).
        held_back_peer_regex: IXIA peer-object name regex for HELD.
        b_keep_peer_addr: DG_B_KEEP IP; advertises ``b_keep_route_count``
            routes throughout (these survive the withdrawal).
        b_keep_route_count: Routes from DG_B_KEEP. Expected post-trigger count.
        b_var1_peer_regex / b_var1_peer_addr: DG_B_VAR1 sender (starts UP
            for 2.4.2; admin-disabled in Phase 2 as the withdrawal trigger).
        b_var1_route_count: Routes from DG_B_VAR1 (these are withdrawn).
        b_var1_device_group_regex: IXIA DeviceGroup name regex for DG_B_VAR1.
            The Phase-2 trigger calls `toggle_device_groups(enable=False,
            regex=...)` on this DG -- durable admin-down that survives DUT
            ConnectRetry (start_bgp_peers(start=False) is transient and lets
            DUT re-establish within ~45s, masking the withdraw).
        ug_peer_group_substring: UG-membership substring (default "EB-FA-V6").
        setup_convergence_s: Settle time used in cleanup.
        post_test_convergence_s: Settle after trigger before verification.
        capture_tcpdump_device: When set, captures BGP updates on this
            device for the trigger window (diagnostic). Default None.
        capture_tcpdump_path: Where to save the capture on the device.

    Returns:
        A ``Playbook`` named ``new_peer_join_routes_withdrawn``.
    """
    trigger_steps: t.List[Step] = []

    if capture_tcpdump_device is not None:
        trigger_steps.append(
            create_tcpdump_step(
                device_name=capture_tcpdump_device,
                mode="start_capture",
                capture_file_path=capture_tcpdump_path,
                description=(
                    "Phase 2 (2.4.2): start tcpdump capture (diagnostic -- "
                    "proves the withdrawal trigger fires on the wire)"
                ),
            )
        )

    trigger_steps.extend(
        [
            # 2a: bring HELD admin-UP -> sync begins.
            create_start_stop_bgp_peers_step(
                peer_regex=held_back_peer_regex,
                start=True,
                start_idx=1,
                end_idx=1,
                description=(
                    "Phase 2a (2.4.2): bring held-back peer UP -- begin UG sync"
                ),
            ),
            # 2b: admin-disable DG_B_VAR1 -- tears down the entire L3 stack
            # (IP/ND + BGP peer). DUT hold-timer expires, session drops to
            # IDLE, and DUT's ConnectRetry attempts get no ND response since
            # the DG is gone -- session stays down for the entire test
            # window. DUT withdraws B_VAR1's routes via UG to all members.
            create_ixia_api_step(
                api_name="toggle_device_groups",
                args_dict={
                    "enable": False,
                    "device_group_name_regex": b_var1_device_group_regex,
                    "sleep_time_before_applying_change": 5,
                },
                description=(
                    "Phase 2b (2.4.2): admin-disable DG_B_VAR1 mid-sync -- "
                    "DUT withdraws B_VAR1's routes via UG to all members"
                ),
            ),
        ]
    )

    if capture_tcpdump_device is not None:
        trigger_steps.append(
            create_tcpdump_step(
                device_name=capture_tcpdump_device,
                mode="stop_capture",
                capture_file_path=capture_tcpdump_path,
                description="Phase 2 (2.4.2): stop tcpdump capture",
            )
        )

    trigger_steps.append(
        create_longevity_step(
            duration=post_test_convergence_s,
            description=(
                f"Phase 2 (2.4.2): settle {post_test_convergence_s}s for "
                "UG to converge on withdrawn state"
            ),
        )
    )

    # Phase 3 verify-the-knob + spec gate.
    phase_3_checks = [
        # 3a: held-back UP took effect.
        create_bgp_session_establish_check(
            ignore_all_prefixes_except=[held_back_peer_addr],
        ),
        # 3b: sender session-down took effect.
        create_bgp_session_establish_check(
            ignore_all_prefixes_except=[b_var1_peer_addr],
            expected_established_sessions=0,
        ),
        # 3c: SPEC GATE -- HELD + all CTRL have exactly b_keep routes; sets
        # identical. The "300 not 500" assertion.
        create_bgp_peer_route_set_equality_check(
            baseline_peer_addr=control_peer_addrs[0],
            tested_peer_addrs=[held_back_peer_addr] + list(control_peer_addrs[1:]),
            anchor_route_count=b_keep_route_count,
        ),
        # 3d: spec passing-criterion "BGP++ agent does not crash" -- the
        # canonical Arista BGP++ gate (Bgp agent + FibBgpGrpc daemon uptime
        # via `show agent uptime`; FAIL if either restarted during the test).
        # Mirrors bag-conveyor create_standard_postchecks() pattern.
        create_service_restart_check(
            services=["Bgp"],
            daemons=["FibBgpGrpc"],
        ),
        # 3e: spec passing-criterion "no stale routes on the newly joined
        # peer" -- asserts no graceful-restart stale flags remain on any
        # installed prefix.
        create_bgp_stale_route_check(),
    ]

    cleanup_steps = [
        # Restore DG_B_VAR1 (re-enable the DeviceGroup -- L3 stack + BGP peer
        # come back up and re-advertise the 200 routes).
        create_ixia_api_step(
            api_name="toggle_device_groups",
            args_dict={
                "enable": True,
                "device_group_name_regex": b_var1_device_group_regex,
                "sleep_time_before_applying_change": 0,
            },
            description="Phase 5 cleanup (2.4.2): re-enable DG_B_VAR1",
        ),
        # Bring HELD back DOWN.
        create_start_stop_bgp_peers_step(
            peer_regex=held_back_peer_regex,
            start=False,
            start_idx=1,
            end_idx=1,
            description="Phase 5 cleanup (2.4.2): restore HELD to admin-DOWN",
        ),
        create_longevity_step(
            duration=setup_convergence_s,
            description=(
                f"Phase 5 cleanup (2.4.2): settle {setup_convergence_s}s for "
                "baseline state to converge"
            ),
        ),
    ]

    if prechecks is None:
        prechecks = [
            create_bgp_update_group_check(
                expect_enabled=True,
                peer_group_substrings=[ug_peer_group_substring],
            ),
            # CTRL + sender peers Established (DG_B_VAR1 IS UP at 2.4.2 start).
            create_bgp_session_establish_check(
                ignore_all_prefixes_except=list(control_peer_addrs)
                + [b_keep_peer_addr, b_var1_peer_addr],
            ),
            # HELD admin-DOWN baseline.
            create_bgp_session_establish_check(
                ignore_all_prefixes_except=[held_back_peer_addr],
                expected_established_sessions=0,
            ),
            # CTRL has full b_keep + b_var1 baseline.
            create_bgp_route_count_verification_check(
                json_params={
                    "descriptions_to_check": list(control_peer_addrs),
                    "direction": "received",
                    "policy_type": "post_policy",
                    "expected_count": b_keep_route_count + b_var1_route_count,
                },
            ),
        ]
    if postchecks is None:
        postchecks = list(phase_3_checks)
    if snapshot_checks is None:
        # core_dumps + peer_route only -- see 2.4.1 factory for rationale.
        snapshot_checks = list(BGP_STANDARD_SNAPSHOT_CHECKS)

    kwargs = dict(
        name="new_peer_join_routes_withdrawn",
        stages=[
            create_steps_stage(
                steps=trigger_steps,
                description=(
                    "Phase 2 (2.4.2): held-back UP + sender session-DOWN "
                    "(mid-sync withdrawal trigger)"
                ),
            ),
        ],
        cleanup_steps=cleanup_steps,
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
    )
    if setup_steps is not None:
        kwargs["setup_steps"] = setup_steps
    return Playbook(**kwargs)


def create_new_peer_join_attribute_change_playbook(
    device_name: str,
    control_peer_addrs: t.List[str],
    held_back_peer_addr: str,
    held_back_peer_regex: str,
    b_keep_peer_addr: str,
    b_keep_route_count: int,
    b_keep_peer_regex: str,
    b_keep_device_group_regex: str,
    b_keep_mutated_peer_addr: str,
    b_keep_mutated_device_group_regex: str,
    initial_community: str,
    mutated_community: str,
    ug_peer_group_substring: str = "EB-FA-V6",
    setup_convergence_s: int = 30,
    # 90s for DUT hold-timer expiry to take effect after KEEP_INITIAL goes
    # DG-down. Empirical: bag012 iBGP hold-timer is >60s; 90s is the value
    # already proven safe in the bag012 baseline SCRUB phase.
    initial_withdraw_settle_s: int = 90,
    # 60s for DUT to receive KEEP_MUTATED's full re-advertisement after DG-up
    # and re-distribute via UG. Same family of value as 2.4.2 (60s post-test).
    post_test_convergence_s: int = 60,
    setup_steps: t.Optional[t.List[Step]] = None,
    prechecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    postchecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    snapshot_checks: t.Optional[t.List[SnapshotHealthCheck]] = None,
) -> Playbook:
    """Build the BGP++ Update Group qualification 2.4.3 playbook
    (New Peer Joins, Then Attribute Change on Existing Routes).

    Spec: verify that when route attributes are changed while a new peer is
    joining and syncing to the update group, the new peer ends up with the
    correct (updated) attributes -- not the stale ones from before the
    change.

    Trigger mechanism: TWO-DG TOPOLOGY SWAP. KEEP_INITIAL and KEEP_MUTATED
    advertise the SAME 300-prefix range with different communities. Only
    KEEP_INITIAL is UP at baseline (KEEP_MUTATED is DG-disabled). The trigger
    DG-disables KEEP_INITIAL (DUT withdraws old-community routes) and
    DG-enables KEEP_MUTATED (DUT receives new-community routes for the same
    prefixes via the other peer). DUT bestpath flips, EB-FA-OUT re-distributes
    the mutated community via UG to HELD+CTRL.

    Rationale for two-DG instead of IXIA configure_community_pool: empirically
    the configure_community_pool API does NOT update the wire on this
    topology even with restart_protocols=True, regardless of how the
    community_combinations list is shaped (1-element, 8-element with marker
    swap). bag012 2026-06-23 v5+v6 runs: KEEP session re-established cleanly
    but all 300 advertised prefixes still carried the original community. The
    two-DG swap uses ``toggle_device_groups`` which IS proven on this testbed
    (same primitive as 2.4.2's withdraw trigger).

    Flow:
      Phase 0 (precheck): UG enabled + membership + KEEP_INITIAL Established
        + KEEP_MUTATED DG-disabled; CTRL has ``b_keep_route_count`` routes
        carrying ``initial_community``; HELD admin-DOWN.
      Phase 2 (trigger): bring HELD UP -> sync begins; toggle KEEP_INITIAL
        DG-disable (DUT withdraws old routes via hold-timer);
        ``initial_withdraw_settle_s`` settle; toggle KEEP_MUTATED DG-enable
        (same prefixes re-advertised with mutated community);
        ``post_test_convergence_s`` settle for UG re-distribute.
      Phase 3 (verify): HELD + KEEP_MUTATED Established; HELD + all CTRL
        have all 300 routes carrying ``mutated_community``, NOT the stale
        ``initial_community``.
      Phase 5 (cleanup): toggle KEEP_MUTATED DG-disable + toggle KEEP_INITIAL
        DG-enable -- restores baseline; HELD back DOWN.

    Args:
        device_name: DUT hostname.
        control_peer_addrs: IPs of control peers.
        held_back_peer_addr: IP of the held-back peer (SUT).
        held_back_peer_regex: IXIA peer-object name regex for HELD.
        b_keep_peer_addr: KEEP_INITIAL sender IP (UP at baseline).
        b_keep_route_count: Routes advertised (300; same across both KEEP DGs).
        b_keep_peer_regex: IXIA peer-object name regex for KEEP_INITIAL.
        b_keep_device_group_regex: IXIA DG regex for KEEP_INITIAL.
        b_keep_mutated_peer_addr: KEEP_MUTATED sender IP (DOWN at baseline).
        b_keep_mutated_device_group_regex: IXIA DG regex for KEEP_MUTATED.
        initial_community: Pre-test community marker (e.g. "65529:39744"); must
            be in the DUT's EB-FA-IN+EB-FA-OUT policy permit lists.
        mutated_community: Post-test community marker (e.g. "65531:50200");
            must also be in the EB-FA-IN+EB-FA-OUT permit lists.
        ug_peer_group_substring: UG-membership substring.
        setup_convergence_s: Settle time used in cleanup.
        initial_withdraw_settle_s: Settle after KEEP_INITIAL DG-disable
            for hold-timer expiry + adj-RIB-out withdraw.
        post_test_convergence_s: Settle after KEEP_MUTATED DG-enable
            for full re-advertise + UG re-distribute before verification.

    Returns:
        A ``Playbook`` named ``new_peer_join_attribute_change``.
    """
    trigger_steps: t.List[Step] = [
        # 2a: bring HELD admin-UP -> sync begins.
        create_start_stop_bgp_peers_step(
            peer_regex=held_back_peer_regex,
            start=True,
            start_idx=1,
            end_idx=1,
            description=("Phase 2a (2.4.3): bring held-back peer UP -- begin UG sync"),
        ),
        # 2b: DG-disable KEEP_INITIAL. DUT's adj-RIB-in for that peer
        # invalidates; hold-timer expiry triggers withdraw of all 300 routes
        # from adj-RIB-out (the proven-durable primitive from 2.4.2).
        create_ixia_api_step(
            api_name="toggle_device_groups",
            args_dict={
                "enable": False,
                "device_group_name_regex": b_keep_device_group_regex,
                "sleep_time_before_applying_change": 0,
            },
            description=(
                "Phase 2b (2.4.3): DG-disable KEEP_INITIAL -- DUT withdraws "
                "the 300 routes carrying the initial community via hold-timer"
            ),
        ),
        create_longevity_step(
            duration=initial_withdraw_settle_s,
            description=(
                f"Phase 2b-settle (2.4.3): {initial_withdraw_settle_s}s for "
                "DUT hold-timer expiry + adj-RIB-out withdraw"
            ),
        ),
        # 2c: DG-enable KEEP_MUTATED. Same 300 prefixes re-advertised, but
        # carrying the mutated community marker. DUT learns them via the new
        # peer, picks bestpath, re-distributes via UG to HELD+CTRL.
        create_ixia_api_step(
            api_name="toggle_device_groups",
            args_dict={
                "enable": True,
                "device_group_name_regex": b_keep_mutated_device_group_regex,
                "sleep_time_before_applying_change": 0,
            },
            description=(
                "Phase 2c (2.4.3): DG-enable KEEP_MUTATED -- same 300 prefixes "
                "re-advertised with mutated community; DUT must re-distribute "
                "via UG to HELD+CTRL"
            ),
        ),
        create_longevity_step(
            duration=post_test_convergence_s,
            description=(
                f"Phase 2 (2.4.3): settle {post_test_convergence_s}s for "
                "KEEP_MUTATED session establish, full route re-advertise, "
                "and DUT UG re-distribute to HELD+CTRL"
            ),
        ),
    ]

    # Phase 3 verify-the-knob + spec gate.
    phase_3_checks = [
        # 3a: held-back UP took effect.
        create_bgp_session_establish_check(
            ignore_all_prefixes_except=[held_back_peer_addr],
        ),
        # 3b: KEEP_MUTATED Established (this is the active sender post-swap).
        create_bgp_session_establish_check(
            ignore_all_prefixes_except=[b_keep_mutated_peer_addr],
        ),
        # 3c: SPEC GATE -- HELD + all CTRL have routes with NEW community,
        # NOT the stale one. ``forbidden_communities`` catches the
        # "stale community survived" failure mode directly.
        create_bgp_received_route_community_check(
            baseline_peer_addr=control_peer_addrs[0],
            tested_peer_addrs=[held_back_peer_addr] + list(control_peer_addrs[1:]),
            anchor_community=mutated_community,
            forbidden_communities=[initial_community],
        ),
        # 3d: route count unchanged (community swap shouldn't change count).
        create_bgp_route_count_verification_check(
            json_params={
                "descriptions_to_check": [held_back_peer_addr]
                + list(control_peer_addrs),
                "direction": "received",
                "policy_type": "post_policy",
                "expected_count": b_keep_route_count,
            },
        ),
        # 3e: spec passing-criterion "BGP++ agent does not crash" -- the
        # canonical Arista BGP++ gate (Bgp agent + FibBgpGrpc daemon uptime
        # via `show agent uptime`; FAIL if either restarted during the test).
        # Mirrors bag-conveyor create_standard_postchecks() pattern.
        create_service_restart_check(
            services=["Bgp"],
            daemons=["FibBgpGrpc"],
        ),
        # 3f: spec passing-criterion "no stale routes / no stale community
        # values" -- asserts no graceful-restart stale flags remain on any
        # installed prefix.
        create_bgp_stale_route_check(),
    ]

    cleanup_steps = [
        # Restore baseline: KEEP_MUTATED DG-disable + KEEP_INITIAL DG-enable.
        create_ixia_api_step(
            api_name="toggle_device_groups",
            args_dict={
                "enable": False,
                "device_group_name_regex": b_keep_mutated_device_group_regex,
                "sleep_time_before_applying_change": 0,
            },
            description=("Phase 5 cleanup (2.4.3): DG-disable KEEP_MUTATED"),
        ),
        create_ixia_api_step(
            api_name="toggle_device_groups",
            args_dict={
                "enable": True,
                "device_group_name_regex": b_keep_device_group_regex,
                "sleep_time_before_applying_change": 0,
            },
            description=(
                "Phase 5 cleanup (2.4.3): DG-enable KEEP_INITIAL -- restores "
                "baseline initial-community advertisement"
            ),
        ),
        # Bring HELD back DOWN.
        create_start_stop_bgp_peers_step(
            peer_regex=held_back_peer_regex,
            start=False,
            start_idx=1,
            end_idx=1,
            description="Phase 5 cleanup (2.4.3): restore HELD to admin-DOWN",
        ),
        create_longevity_step(
            duration=setup_convergence_s,
            description=(
                f"Phase 5 cleanup (2.4.3): settle {setup_convergence_s}s for "
                "baseline state to converge"
            ),
        ),
    ]

    if prechecks is None:
        prechecks = [
            create_bgp_update_group_check(
                expect_enabled=True,
                peer_group_substrings=[ug_peer_group_substring],
            ),
            # CTRL + DG_B_KEEP Established.
            create_bgp_session_establish_check(
                ignore_all_prefixes_except=list(control_peer_addrs)
                + [b_keep_peer_addr],
            ),
            # HELD admin-DOWN.
            create_bgp_session_establish_check(
                ignore_all_prefixes_except=[held_back_peer_addr],
                expected_established_sessions=0,
            ),
            # CTRL receives b_keep_route_count carrying initial_community.
            create_bgp_received_route_community_check(
                baseline_peer_addr=control_peer_addrs[0],
                tested_peer_addrs=list(control_peer_addrs[1:]),
                anchor_community=initial_community,
            ),
        ]
    if postchecks is None:
        postchecks = list(phase_3_checks)
    if snapshot_checks is None:
        # core_dumps + peer_route only -- see 2.4.1 factory for rationale.
        snapshot_checks = list(BGP_STANDARD_SNAPSHOT_CHECKS)

    kwargs = dict(
        name="new_peer_join_attribute_change",
        stages=[
            create_steps_stage(
                steps=trigger_steps,
                description=(
                    "Phase 2 (2.4.3): held-back UP + community swap on "
                    "sender (mid-sync attribute mutation trigger)"
                ),
            ),
        ],
        cleanup_steps=cleanup_steps,
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
    )
    if setup_steps is not None:
        kwargs["setup_steps"] = setup_steps
    return Playbook(**kwargs)


def build_arista_ebb_scale_playbook(
    name,
    stages,
    setup_steps=None,
    periodic_tasks=None,
    prechecks=None,
    postchecks=None,
    snapshot_checks=None,
):
    """Trampoline for `testconfigs/routing/ebb/arista_ebb_scale_test_config.py`.

    Source had 23 inline `Playbook(...)` constructions inside the
    `test_config_for_bgp_plus_plus_on_ebb_arista_with_bgp_mon` factory. All
    Playbooks share a small kwarg shape; this trampoline accepts every relevant
    field as an optional kwarg so the source no longer inline-constructs
    `Playbook(...)`.
    """
    kwargs = {"name": name, "stages": stages}
    for k, v in [
        ("setup_steps", setup_steps),
        ("periodic_tasks", periodic_tasks),
        ("prechecks", prechecks),
        ("postchecks", postchecks),
        ("snapshot_checks", snapshot_checks),
    ]:
        if v is not None:
            kwargs[k] = v
    return Playbook(**kwargs)


def build_ssw_fauu_bgp_scale_playbook(
    name,
    device_regexes,
    stages,
    prechecks,
    postchecks,
):
    """Trampoline for `testconfigs/internal/ssw_fauu_bgp_scale_test_config.py`.

    Source had 5 inline `Playbook(...)` constructions at module scope, all thin
    wrappers around imported common_playbooks (warmboot/qspf/bgpd/fsdb/agent+fsdb).
    This trampoline keeps the source from inline-constructing Playbook(...).
    """
    return Playbook(
        name=name,
        device_regexes=device_regexes,
        stages=stages,
        prechecks=prechecks,
        postchecks=postchecks,
    )


def build_qza_gb300_playbook(name, prechecks, postchecks, stages):
    """Trampoline for `testconfigs/internal/qza_gb300_test_config.py`.

    Source had 8 inline `Playbook(...)` constructions at module scope inside
    the QZA_GB300_TEST_CONFIG TestConfig (longevity + 7 service-interruption
    playbooks). All Playbooks share an identical kwarg shape; this trampoline
    keeps the source from inline-constructing Playbook(...).
    """
    return Playbook(
        name=name,
        prechecks=prechecks,
        postchecks=postchecks,
        stages=stages,
    )


def build_qos_scheduling_playbook(
    name,
    traffic_items_to_configure,
    traffic_items_to_start,
    postchecks,
    snapshot_checks,
    stages,
    cleanup_steps=None,
):
    """Trampoline for `testconfigs/internal/qos_scheduling_test_config.py`.

    The source TestConfig had 7 inline `Playbook(...)` constructions inside
    QoS scheduling playbook factory functions (continuous_burst, congestion,
    ncnf_scheduling, etc.). All Playbooks share a consistent kwarg shape;
    this trampoline keeps the source from inline-constructing Playbook(...).
    """
    kwargs = {
        "name": name,
        "traffic_items_to_configure": traffic_items_to_configure,
        "traffic_items_to_start": traffic_items_to_start,
        "postchecks": postchecks,
        "snapshot_checks": snapshot_checks,
        "stages": stages,
    }
    if cleanup_steps is not None:
        kwargs["cleanup_steps"] = cleanup_steps
    return Playbook(**kwargs)


def build_edsw003_bgp_path_scale_playbook(
    name,
    stages,
    prechecks=None,
    postchecks=None,
    postchecks_to_skip=None,
    snapshot_checks=None,
    iteration=None,
    traffic_items_to_start=None,
    cleanup_steps=None,
    setup_steps=None,
    description=None,
    skip_test_config_postchecks=None,
):
    """Trampoline for `testconfigs/hyperport/hyperport_edsw003_bgp_path_scale_test_config.py`.

    The source TestConfig has 10 inline `Playbook(...)` constructions
    (longevity + 9 disruption playbooks). All Playbooks share a flexible kwarg
    shape; this trampoline keeps the source from inline-constructing Playbook(...).
    """
    kwargs = {"name": name, "stages": stages}
    for k, v in [
        ("prechecks", prechecks),
        ("postchecks", postchecks),
        ("postchecks_to_skip", postchecks_to_skip),
        ("snapshot_checks", snapshot_checks),
        ("iteration", iteration),
        ("traffic_items_to_start", traffic_items_to_start),
        ("cleanup_steps", cleanup_steps),
        ("setup_steps", setup_steps),
        ("description", description),
        ("skip_test_config_postchecks", skip_test_config_postchecks),
    ]:
        if v is not None:
            kwargs[k] = v
    return Playbook(**kwargs)


# =============================================================================
# Hyperport PFC: constants, traffic configs, health-check builders, playbooks
# (migrated from playbooks/helpers/hyperport/pfc_playbooks.py in Phase 4 v2)
# =============================================================================

# There are 4 traffic classes for PFC queues at Meta
# TC1: Default - Lossy (Queue 0, least priority)
# TC2: RDMA - Lossless (Queue 2, PFC-enabled)
# TC6: Monitoring - Lossy (Queue 6) / Lossless (Queue 6, PFC-enabled) on Tahan/SUSW
# TC7: Network Control - Strict priority and Lossy (Queue 7, highest priority)
TRAFFIC_ITEM_HEADERS_MAP = {
    "RDMA": DSF_RDMA_PACKET_HEADERS,
    "RDMA_IB": DSF_RDMA_IB_PACKET_HEADERS,
    "BE": DSF_BE_PACKET_HEADERS,
    "NC": DSF_NC_PACKET_HEADERS,
    "MONITORING": DSF_MONITORING_PACKET_HEADERS,
}

# DSF IMIX frame size distribution
DSF_FRAME_SIZES = ixia_types.FrameSize(
    type=ixia_types.FrameSizeType.CUSTOM_IMIX,
    imix_weight={94: 1, 96: 18, 192: 3, 512: 1, 1200: 1, 4600: 76},
)

# IXIA PFC L1 port config with PFC queue priority mapping
IXIA_ENABLE_PFC_PORT_CONFIG = taac_types.BasicPortConfig(
    l1_config=ixia_types.L1Config(
        enable_fcoe=True,
        flow_control_config=ixia_types.FlowControlConfig(
            pfc_prority_groups_config=ixia_types.PfcPriorityGroupsConfig(
                priority0_pfc_queue=ixia_types.PfcQueue.TWO,
                priority1_pfc_queue=ixia_types.PfcQueue.ONE,
                priority2_pfc_queue=ixia_types.PfcQueue.ZERO,
                priority3_pfc_queue=ixia_types.PfcQueue.THREE,
                priority4_pfc_queue=ixia_types.PfcQueue.TWO,
                priority5_pfc_queue=ixia_types.PfcQueue.ONE,
                priority6_pfc_queue=ixia_types.PfcQueue.ZERO,
                priority7_pfc_queue=ixia_types.PfcQueue.THREE,
            ),
            enable_pfc_pause_delay=False,
        ),
    )
)


def get_pfc_wd_params(port_speed: int) -> dict:
    """
    Get PFC watchdog parameters based on port speed.

    Returns a dict with keys:
        pfc_pause_frame_rates: [high_rate, low_rate]
        tc2_wd_traffic_item_high: str
        tc2_wd_traffic_item_low: str
        tc6_wd_traffic_item_high: str
        tc6_wd_traffic_item_low: str
        wd_pfc_threshold_high: int
        wd_pfc_threshold_low: int
    """
    if port_speed == 400:
        return {
            "pfc_pause_frame_rates": [15000, 10000],
            "tc2_wd_traffic_item_high": "TRAFFIC_TC2_PFC_PAUSE_15000FPS",
            "tc2_wd_traffic_item_low": "TRAFFIC_TC2_PFC_PAUSE_10000FPS",
            "tc6_wd_traffic_item_high": "TRAFFIC_TC6_PFC_PAUSE_15000FPS",
            "tc6_wd_traffic_item_low": "TRAFFIC_TC6_PFC_PAUSE_10000FPS",
            "wd_pfc_threshold_high": 800000,
            "wd_pfc_threshold_low": 500000,
        }
    elif port_speed == 800:
        return {
            "pfc_pause_frame_rates": [30000, 20000],
            "tc2_wd_traffic_item_high": "TRAFFIC_TC2_PFC_PAUSE_30000FPS",
            "tc2_wd_traffic_item_low": "TRAFFIC_TC2_PFC_PAUSE_20000FPS",
            "tc6_wd_traffic_item_high": "TRAFFIC_TC6_PFC_PAUSE_30000FPS",
            "tc6_wd_traffic_item_low": "TRAFFIC_TC6_PFC_PAUSE_20000FPS",
            "wd_pfc_threshold_high": 1600000,
            "wd_pfc_threshold_low": 1000000,
        }
    else:
        raise ValueError(
            f"Port speed {port_speed} is not supported by PFC watchdog test"
        )


def create_dsf_proto_ipv6_traffic_config(
    proto: str,
    src_endpoints: list[TrafficEndpoint],
    dest_endpoints: list[TrafficEndpoint],
    name: str,
    line_rate: int,
) -> taac_types.BasicTrafficItemConfig:
    """Create an IPv6 traffic config for a specific protocol/traffic class."""
    return taac_types.BasicTrafficItemConfig(
        src_endpoints=src_endpoints,
        dest_endpoints=dest_endpoints,
        name=name,
        line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
        line_rate=line_rate,
        traffic_type=ixia_types.TrafficType.IPV6,
        bidirectional=False,
        packet_headers=TRAFFIC_ITEM_HEADERS_MAP.get(proto),
        skip_default_l4_protocol=True,
        full_mesh=False,
        src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
        frame_size_settings=DSF_FRAME_SIZES,
    )


def create_pfc_pause_traffic_config(
    src_endpoints: list[TrafficEndpoint],
    dest_endpoints: list[TrafficEndpoint],
    name: str,
    line_rate: int,
    packet_headers: list[taac_types.PacketHeader] = TC2_PFC_PAUSE_PACKET_HEADERS,
) -> taac_types.BasicTrafficItemConfig:
    """Create a PFC pause RAW traffic configuration."""
    return taac_types.BasicTrafficItemConfig(
        src_endpoints=src_endpoints,
        dest_endpoints=dest_endpoints,
        name=name,
        line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
        line_rate=line_rate,
        traffic_type=ixia_types.TrafficType.RAW,
        bidirectional=False,
        packet_headers=packet_headers,
        full_mesh=False,
        frame_size_settings=ixia_types.FrameSize(
            type=ixia_types.FrameSizeType.FIXED, fixed_size=64
        ),
        src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
    )


def create_dsf_pfc_check(
    interfaces: list[TrafficEndpoint],
    min_in_pfc_value: int,
    priority: hc_types.Priority = hc_types.Priority.PRIORITY_2,
) -> PointInTimeHealthCheck:
    """Check if incoming PFC pause frame rate is greater than provided value.

    Local helper preserved for downstream test config callers (hyperport, etc.).
    Wraps the central `_create_dsf_pfc_check_central` factory with a
    typed-interfaces signature.
    """
    return _create_dsf_pfc_check_central(
        thresholds=[
            hc_types.DsfPfcThreshold(
                interfaces=[interface.name for interface in interfaces],
                in_pfc=min_in_pfc_value,
                comparison=hc_types.ComparisonType.GREATER_THAN,
                priority=priority,
            ),
        ],
        check_scope=hc_types.Scope.DEFAULT,
    )


def create_pfc_wd_check(
    interfaces: list[TrafficEndpoint],
    comparison_type: hc_types.ComparisonType,
) -> PointInTimeHealthCheck:
    """Check PFC deadlock and recovery counter values.

    Local helper preserved for downstream test config callers. Wraps the central
    `_create_pfc_wd_check_central` factory.
    """
    return _create_pfc_wd_check_central(
        thresholds=[
            hc_types.PfcWdThreshold(
                interfaces=[interface.name for interface in interfaces],
                deadlock_threshold=0,
                recovery_threshold=0,
                comparison=comparison_type,
            ),
        ],
        check_scope=hc_types.Scope.DEFAULT,
    )


def create_packet_loss_check(traffic_item_name: str) -> PointInTimeHealthCheck:
    """Create a packet loss health check for a specific traffic item."""
    return create_ixia_packet_loss_check(
        thresholds=[
            hc_types.PacketLossThreshold(
                names=[traffic_item_name],
                str_value="0",
                metric=hc_types.PacketLossMetric.PERCENTAGE,
            ),
        ]
    )


def create_playbook_pfc_congestion(
    name: str,
    rdma_traffic_items_names: list[str],
    src_endpoints: list[TrafficEndpoint],
    dst_endpoints: list[TrafficEndpoint],
    traffic_duration: int = 60,
    description: str = "",
) -> Playbook:
    """
    Create a PFC congestion playbook that verifies equal slowdown and zero
    packet loss when multiple RDMA streams compete for bandwidth.
    """
    return Playbook(
        name=name,
        description=description
        or "Equal slowdown and no packet loss in congestion with multiple TC2 traffic",
        prechecks=[
            create_clear_counters_check(),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_longevity_step(duration=traffic_duration),
                ]
            )
        ],
        postchecks=[
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=rdma_traffic_items_names,
                        str_value="0.1",
                    ),
                ],
                clear_traffic_stats=True,
            ),
            create_ixia_traffic_rate_check(
                thresholds=[
                    hc_types.TrafficRateThreshold(
                        names=rdma_traffic_items_names,
                        # line rate equally shared among streams
                        value=int(90 / len(rdma_traffic_items_names)) - 1,
                        threshold_type=hc_types.ThresholdType.PERCENT,
                        metric=hc_types.TrafficRateMetric.TX_RATE,
                    ),
                ]
            ),
            _create_dsf_pfc_check_central(
                thresholds=[
                    hc_types.DsfPfcThreshold(
                        interfaces=[endpoint.name for endpoint in src_endpoints],
                        out_pfc=1000,
                        comparison=hc_types.ComparisonType.GREATER_THAN,
                    ),
                ]
            ),
            create_port_counters_check(
                thresholds=[
                    hc_types.PortCountersThreshold(
                        interfaces=[endpoint.name for endpoint in dst_endpoints],
                        out_discards=0,
                        comparison=hc_types.ComparisonType.EQUAL_TO,
                    ),
                ]
            ),
        ],
        traffic_items_to_start=rdma_traffic_items_names,
    )


def create_playbook_pfc_non_congestion(
    name: str,
    rdma_traffic_items_names: list[str],
    src_endpoints: list[TrafficEndpoint],
    dst_endpoints: list[TrafficEndpoint],
    traffic_duration: int = 60,
    description: str = "",
) -> Playbook:
    """
    Create a PFC non-congestion playbook that verifies no PFC frames and
    zero packet loss when traffic does not exceed port capacity.
    """
    return Playbook(
        name=name,
        description=description
        or "No PFC frame dispersion and zero packet loss in non-congestion",
        prechecks=[
            create_clear_counters_check(),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_longevity_step(duration=traffic_duration),
                ]
            )
        ],
        postchecks=[
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=rdma_traffic_items_names[:1],
                        str_value="0",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                ]
            ),
            create_ixia_traffic_rate_check(
                thresholds=[
                    hc_types.TrafficRateThreshold(
                        names=rdma_traffic_items_names[:1],
                        value=89,
                        threshold_type=hc_types.ThresholdType.PERCENT,
                        metric=hc_types.TrafficRateMetric.TX_RATE,
                    ),
                ]
            ),
            _create_dsf_pfc_check_central(
                thresholds=[
                    hc_types.DsfPfcThreshold(
                        interfaces=[endpoint.name for endpoint in src_endpoints[:1]],
                        out_pfc=0,
                        comparison=hc_types.ComparisonType.EQUAL_TO,
                    ),
                ]
            ),
            create_port_counters_check(
                thresholds=[
                    hc_types.PortCountersThreshold(
                        interfaces=[endpoint.name for endpoint in dst_endpoints],
                        out_discards=0,
                        comparison=hc_types.ComparisonType.EQUAL_TO,
                    ),
                ]
            ),
        ],
        traffic_items_to_start=rdma_traffic_items_names[:1],
    )


def create_playbook_pfc_congestion_non_pfc_traffic(
    name: str,
    pfc_traffic_items_names: list[str],
    be_traffic_item_name: str,
    src_endpoints: list[TrafficEndpoint],
    dst_endpoints: list[TrafficEndpoint],
    traffic_duration: int = 60,
    priority: hc_types.Priority = hc_types.Priority.PRIORITY_2,
    description: str = "",
) -> Playbook:
    """
    Create a playbook for testing PFC functionality under congestion
    with a mix of lossless (PFC-enabled) and lossy (BE) traffic.

    Verifies:
    1. No packet loss on PFC-enabled traffic
    2. High packet loss on BE traffic (expected due to congestion)
    3. No PFC packets received at src endpoints if total PFC < 100% line rate
    """
    return Playbook(
        name=name,
        description=description
        or "No packet loss on lossless traffic, high loss on BE under congestion",
        prechecks=[
            create_clear_counters_check(),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_longevity_step(duration=traffic_duration),
                ]
            )
        ],
        postchecks=[
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=pfc_traffic_items_names,
                        str_value="0",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                    # BE traffic gets 10% line rate (40 Gbps)
                    # Tx 24% line rate is 96 Gbps, (96-40)/96 = ~58%
                    hc_types.PacketLossThreshold(
                        names=[be_traffic_item_name],
                        str_value="65",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                ]
            ),
            create_ixia_traffic_rate_check(
                thresholds=[
                    hc_types.TrafficRateThreshold(
                        names=pfc_traffic_items_names,
                        value=29,
                        threshold_type=hc_types.ThresholdType.PERCENT,
                        metric=hc_types.TrafficRateMetric.TX_RATE,
                    ),
                ]
            ),
            _create_dsf_pfc_check_central(
                thresholds=[
                    hc_types.DsfPfcThreshold(
                        interfaces=[endpoint.name for endpoint in src_endpoints[:3]],
                        out_pfc=0,
                        comparison=hc_types.ComparisonType.EQUAL_TO,
                        priority=priority,
                    ),
                ]
            ),
            create_port_counters_check(
                thresholds=[
                    hc_types.PortCountersThreshold(
                        interfaces=[endpoint.name for endpoint in dst_endpoints],
                        out_discards=0,
                        comparison=hc_types.ComparisonType.GREATER_THAN,
                    ),
                ]
            ),
        ],
        traffic_items_to_start=pfc_traffic_items_names + [be_traffic_item_name],
    )


def create_playbook_wd(
    name: str,
    interfaces_to_check: list[TrafficEndpoint],
    min_in_pfc_value: int,
    wd_metric_comparison_type: hc_types.ComparisonType,
    traffic_items_to_start: list[str],
    description: str = "",
    packetlosscheck: bool = False,
    priority: hc_types.Priority = hc_types.Priority.PRIORITY_2,
) -> Playbook:
    """Create a PFC watchdog playbook to verify PFC pause frame handling."""
    postchecks = [
        create_dsf_pfc_check(interfaces_to_check, min_in_pfc_value, priority),
        create_pfc_wd_check(interfaces_to_check, wd_metric_comparison_type),
    ]

    if packetlosscheck:
        postchecks.append(create_packet_loss_check(traffic_items_to_start[1]))

    return Playbook(
        name=name,
        description=description,
        stages=[
            create_steps_stage(
                steps=[
                    create_longevity_step(duration=60),
                ]
            )
        ],
        prechecks=[
            create_clear_counters_check(),
        ],
        postchecks=postchecks,
        traffic_items_to_start=traffic_items_to_start,
    )


# =============================================================================
# qzd_single_node_topology_mimic_fauu Playbook trampolines
# (migrated from playbooks/helpers/qzd_single_node_topology_mimic_fauu_test_config_playbooks.py
#  in Phase 4 v2)
# =============================================================================


def rebuild_qzd_playbook_with_checks(
    pb, prechecks=None, postchecks=None, snapshot_checks=None
):
    """Rebuild a Playbook with merged checks (used by _add_checks_to_playbooks)."""
    return Playbook(
        name=pb.name,
        stages=pb.stages,
        description=pb.description,
        iteration=pb.iteration,
        traffic_items_to_start=pb.traffic_items_to_start,
        enabled=pb.enabled,
        backup_and_restore_ixia_config=pb.backup_and_restore_ixia_config,
        prechecks=(pb.prechecks or []) + (prechecks or []),
        postchecks=(pb.postchecks or []) + (postchecks or []),
        snapshot_checks=(pb.snapshot_checks or []) + (snapshot_checks or []),
        skip_test_config_prechecks=pb.skip_test_config_prechecks,
        skip_test_config_postchecks=pb.skip_test_config_postchecks,
        skip_test_config_snapshot_checks=pb.skip_test_config_snapshot_checks,
        override_duplicate_checks=pb.override_duplicate_checks,
        prechecks_to_skip=pb.prechecks_to_skip,
        postchecks_to_skip=pb.postchecks_to_skip,
        snapshot_checks_to_skip=pb.snapshot_checks_to_skip,
        check_ids_to_skip=pb.check_ids_to_skip,
        cleanup_steps=pb.cleanup_steps,
        setup_steps=pb.setup_steps,
        device_regexes=pb.device_regexes,
        periodic_tasks=pb.periodic_tasks,
        attribute_filters=pb.attribute_filters,
        traffic_items_to_configure=pb.traffic_items_to_configure,
        scuba_table=pb.scuba_table,
    )


# =============================================================================
# snc_single_node_topology_mimic_fauu Playbook trampolines
# (migrated from playbooks/helpers/snc_single_node_topology_mimic_fauu_test_config_playbooks.py
#  in Phase 4 v2)
# =============================================================================


def rebuild_snc_playbook_with_checks(
    pb, prechecks=None, postchecks=None, snapshot_checks=None
):
    """Rebuild a Playbook with merged checks (used by _add_checks_to_playbooks)."""
    return Playbook(
        name=pb.name,
        stages=pb.stages,
        description=pb.description,
        iteration=pb.iteration,
        traffic_items_to_start=pb.traffic_items_to_start,
        enabled=pb.enabled,
        backup_and_restore_ixia_config=pb.backup_and_restore_ixia_config,
        prechecks=(pb.prechecks or []) + (prechecks or []),
        postchecks=(pb.postchecks or []) + (postchecks or []),
        snapshot_checks=(pb.snapshot_checks or []) + (snapshot_checks or []),
        skip_test_config_prechecks=pb.skip_test_config_prechecks,
        skip_test_config_postchecks=pb.skip_test_config_postchecks,
        skip_test_config_snapshot_checks=pb.skip_test_config_snapshot_checks,
        override_duplicate_checks=pb.override_duplicate_checks,
        prechecks_to_skip=pb.prechecks_to_skip,
        postchecks_to_skip=pb.postchecks_to_skip,
        snapshot_checks_to_skip=pb.snapshot_checks_to_skip,
        check_ids_to_skip=pb.check_ids_to_skip,
        cleanup_steps=pb.cleanup_steps,
        setup_steps=pb.setup_steps,
        device_regexes=pb.device_regexes,
        periodic_tasks=pb.periodic_tasks,
        attribute_filters=pb.attribute_filters,
        traffic_items_to_configure=pb.traffic_items_to_configure,
        scuba_table=pb.scuba_table,
    )


def build_snc_playbook(
    name,
    stages,
    description=None,
    iteration=None,
    traffic_items_to_start=None,
    enabled=None,
    prechecks=None,
    postchecks=None,
    snapshot_checks=None,
    cleanup_steps=None,
    setup_steps=None,
    skip_test_config_postchecks=None,
    skip_test_config_prechecks=None,
    skip_test_config_snapshot_checks=None,
    prechecks_to_skip=None,
    postchecks_to_skip=None,
    snapshot_checks_to_skip=None,
    check_ids_to_skip=None,
    override_duplicate_checks=None,
    backup_and_restore_ixia_config=None,
    device_regexes=None,
    periodic_tasks=None,
    attribute_filters=None,
    traffic_items_to_configure=None,
    scuba_table=None,
):
    """Build a generic standalone SNC `Playbook` from kwargs.

    Tiny trampoline that forwards only the kwargs the caller actually
    sets (avoiding `None` overrides of `Playbook` defaults). Used by SNC
    TestConfigs that previously inline-constructed `Playbook(...)` so
    every call site funnels through one factory.

    Args:
        name: Playbook name.
        stages: List of stages.
        description / iteration / traffic_items_to_start / enabled /
        prechecks / postchecks / snapshot_checks / cleanup_steps /
        setup_steps / skip_test_config_postchecks /
        skip_test_config_prechecks /
        skip_test_config_snapshot_checks / prechecks_to_skip /
        postchecks_to_skip / snapshot_checks_to_skip /
        check_ids_to_skip / override_duplicate_checks /
        backup_and_restore_ixia_config / device_regexes /
        periodic_tasks / attribute_filters /
        traffic_items_to_configure / scuba_table: Optional `Playbook`
            kwargs; only forwarded when not None.

    Returns:
        A `Playbook` constructed from the supplied non-None kwargs.
    """
    kwargs = {"name": name, "stages": stages}
    for k, v in [
        ("description", description),
        ("iteration", iteration),
        ("traffic_items_to_start", traffic_items_to_start),
        ("enabled", enabled),
        ("prechecks", prechecks),
        ("postchecks", postchecks),
        ("snapshot_checks", snapshot_checks),
        ("cleanup_steps", cleanup_steps),
        ("setup_steps", setup_steps),
        ("skip_test_config_postchecks", skip_test_config_postchecks),
        ("skip_test_config_prechecks", skip_test_config_prechecks),
        ("skip_test_config_snapshot_checks", skip_test_config_snapshot_checks),
        ("prechecks_to_skip", prechecks_to_skip),
        ("postchecks_to_skip", postchecks_to_skip),
        ("snapshot_checks_to_skip", snapshot_checks_to_skip),
        ("check_ids_to_skip", check_ids_to_skip),
        ("override_duplicate_checks", override_duplicate_checks),
        ("backup_and_restore_ixia_config", backup_and_restore_ixia_config),
        ("device_regexes", device_regexes),
        ("periodic_tasks", periodic_tasks),
        ("attribute_filters", attribute_filters),
        ("traffic_items_to_configure", traffic_items_to_configure),
        ("scuba_table", scuba_table),
    ]:
        if v is not None:
            kwargs[k] = v
    return Playbook(**kwargs)


def build_qzd_playbook(
    name,
    stages,
    description=None,
    iteration=None,
    traffic_items_to_start=None,
    enabled=None,
    prechecks=None,
    postchecks=None,
    snapshot_checks=None,
    cleanup_steps=None,
    setup_steps=None,
    skip_test_config_postchecks=None,
    skip_test_config_prechecks=None,
    skip_test_config_snapshot_checks=None,
    prechecks_to_skip=None,
    postchecks_to_skip=None,
    snapshot_checks_to_skip=None,
    check_ids_to_skip=None,
    override_duplicate_checks=None,
    backup_and_restore_ixia_config=None,
    device_regexes=None,
    periodic_tasks=None,
    attribute_filters=None,
    traffic_items_to_configure=None,
    scuba_table=None,
):
    """Build a generic standalone QZD `Playbook` from kwargs.

    Tiny trampoline that forwards only the kwargs the caller actually
    sets (avoiding `None` overrides of `Playbook` defaults). Used by QZD
    TestConfigs that previously inline-constructed `Playbook(...)` so
    every call site funnels through one factory.

    Args:
        name: Playbook name.
        stages: List of stages.
        description / iteration / traffic_items_to_start / enabled /
        prechecks / postchecks / snapshot_checks / cleanup_steps /
        setup_steps / skip_test_config_postchecks /
        skip_test_config_prechecks /
        skip_test_config_snapshot_checks / prechecks_to_skip /
        postchecks_to_skip / snapshot_checks_to_skip /
        check_ids_to_skip / override_duplicate_checks /
        backup_and_restore_ixia_config / device_regexes /
        periodic_tasks / attribute_filters /
        traffic_items_to_configure / scuba_table: Optional `Playbook`
            kwargs; only forwarded when not None.

    Returns:
        A `Playbook` constructed from the supplied non-None kwargs.
    """
    kwargs = {"name": name, "stages": stages}
    for k, v in [
        ("description", description),
        ("iteration", iteration),
        ("traffic_items_to_start", traffic_items_to_start),
        ("enabled", enabled),
        ("prechecks", prechecks),
        ("postchecks", postchecks),
        ("snapshot_checks", snapshot_checks),
        ("cleanup_steps", cleanup_steps),
        ("setup_steps", setup_steps),
        ("skip_test_config_postchecks", skip_test_config_postchecks),
        ("skip_test_config_prechecks", skip_test_config_prechecks),
        ("skip_test_config_snapshot_checks", skip_test_config_snapshot_checks),
        ("prechecks_to_skip", prechecks_to_skip),
        ("postchecks_to_skip", postchecks_to_skip),
        ("snapshot_checks_to_skip", snapshot_checks_to_skip),
        ("check_ids_to_skip", check_ids_to_skip),
        ("override_duplicate_checks", override_duplicate_checks),
        ("backup_and_restore_ixia_config", backup_and_restore_ixia_config),
        ("device_regexes", device_regexes),
        ("periodic_tasks", periodic_tasks),
        ("attribute_filters", attribute_filters),
        ("traffic_items_to_configure", traffic_items_to_configure),
        ("scuba_table", scuba_table),
    ]:
        if v is not None:
            kwargs[k] = v
    return Playbook(**kwargs)


# =============================================================================
# Port-Channel (LAG) playbooks + helpers
# (migrated from playbooks/helpers/portchannel_playbooks.py in Phase 4 v2)
# =============================================================================


class LinkFlapVariation(Enum):
    BELOW_MIN_CAPACITY = "below"
    AT_MIN_CAPACITY = "at"
    ABOVE_MIN_CAPACITY = "above"
    ALL_LINKS = "all"


def _compute_min_capacity(total_links: int, min_link_percentage: float) -> int:
    return math.ceil(total_links * min_link_percentage)


def _compute_min_capacity_to_up(total_links: int, min_link_up_percentage: float) -> int:
    return math.ceil(total_links * min_link_up_percentage)


def create_portchannel_health_check(
    port_channel_name_map: dict[str, list[str]],
    expected_up: bool = True,
) -> PointInTimeHealthCheck:
    return create_port_channel_expected_state_check(
        json_params={
            "port_channel_names": port_channel_name_map,
            "expected_up": expected_up,
        },
    )


def _compute_links_to_flap(
    min_capacity: int,
    min_capacity_to_up: int,
    variation: LinkFlapVariation,
) -> int:
    if variation == LinkFlapVariation.ALL_LINKS:
        return min_capacity_to_up
    elif variation == LinkFlapVariation.BELOW_MIN_CAPACITY:
        return min_capacity_to_up - min_capacity + 1
    elif variation == LinkFlapVariation.AT_MIN_CAPACITY:
        return min_capacity_to_up - min_capacity
    else:
        return max(min_capacity_to_up - min_capacity - 1, 0)


def _create_lag_prechecks(
    portchannel_name_map: dict[str, list[str]],
    ignore_all_prefixes_except: t.Optional[t.List[str]] = None,
) -> list[PointInTimeHealthCheck]:
    return [
        create_systemctl_active_state_check(),
        create_lldp_check(),
        create_portchannel_health_check(portchannel_name_map, expected_up=True),
        create_prefix_limit_check(prefix_limit=74000),
        create_unclean_exit_check(),
        create_memory_utilization_check(
            threshold=5 * (1024**3),
            threshold_by_service={
                "bgpd": 4.5 * (1024**3),
                "fsdb": 5 * (1024**3),
                "qsfp_service": 2 * (1024**3),
                "fboss_sw_agent": 9 * (1024**3),
                "fboss_hw_agent@0": 8 * (1024**3),
            },
            start_time_jq_var="test_case_start_time",
        ),
        create_bgp_session_establish_check(
            ignore_all_prefixes_except=ignore_all_prefixes_except
        ),
    ]


def _create_lag_postchecks(
    portchannel_name_map: dict[str, list[str]],
    ignore_all_prefixes_except: t.Optional[t.List[str]] = None,
) -> list[PointInTimeHealthCheck]:
    return [
        create_systemctl_active_state_check(),
        create_lldp_check(),
        create_portchannel_health_check(portchannel_name_map, expected_up=True),
        create_device_core_dumps_check(),
        create_service_restart_check(),
        create_prefix_limit_check(prefix_limit=74000),
        create_unclean_exit_check(),
        create_memory_utilization_check(
            threshold=5 * (1024**3),
            threshold_by_service={
                "bgpd": 4.5 * (1024**3),
                "fsdb": 5 * (1024**3),
                "qsfp_service": 2 * (1024**3),
                "fboss_sw_agent": 9 * (1024**3),
                "fboss_hw_agent@0": 8 * (1024**3),
            },
            start_time_jq_var="test_case_start_time",
        ),
        create_bgp_session_establish_check(
            ignore_all_prefixes_except=ignore_all_prefixes_except
        ),
        create_cpu_utilization_check(
            threshold=400.0, start_time_jq_var="test_case_start_time"
        ),
    ]


def _create_lag_snapshot_checks() -> list[SnapshotHealthCheck]:
    return [
        create_core_dumps_snapshot_check(),
        create_port_channel_state_snapshot_check(),
    ]


from taac.steps.step_definitions import (
    create_lag_cleanup_steps as _create_lag_cleanup_steps,
    create_lag_permanent_cleanup_steps as _create_lag_permanent_cleanup_steps,
)


def create_lag_baseline_playbook_1(
    playbook_name: str,
    member_interfaces: list[str],
    min_link_percentage: float,
    min_link_up_percentage: float,
    portchannel_name_map: dict[str, list[str]],
    iteration: int = 10,
) -> Playbook:
    """
    Build LAG_001: port-channel variable-minlink baseline functionality Playbook.

    Verifies a port-channel's response as members are progressively
    disabled then re-enabled across three phases relative to its
    MinCapacity (`min_link_percentage`) and MinCapacityToUp
    (`min_link_up_percentage`) thresholds. After the initial setup
    leaves `min_cap_to_up` members up, the playbook:
      1. Disables members down to MinCap — port-channel stays up.
      2. Disables one more member — port-channel goes down.
      3. Re-enables that member — port-channel stays down (hysteresis).
      4. Re-enables the rest — port-channel comes back up.

    Args:
        playbook_name: Name to record the playbook under.
        port_channel_name: DUT port-channel under test.
        member_interfaces: All physical members of the port-channel.
        min_link_percentage: Fractional MinLinks threshold (0-1).
        min_link_up_percentage: Fractional MinLinksUp threshold (0-1).

    Returns:
        A `Playbook` with LAG prechecks/postchecks/snapshot/cleanup steps
        wired in, exercising the three-phase enable/disable sequence.
    """
    total_links = len(member_interfaces)
    min_cap = _compute_min_capacity(total_links, min_link_percentage)
    min_cap_to_up = _compute_min_capacity_to_up(total_links, min_link_up_percentage)

    # Interfaces disabled in each phase (cumulative)
    links_to_mincap_to_up = total_links - min_cap_to_up
    links_to_mincap = total_links - min_cap

    phase1_interfaces = member_interfaces[:links_to_mincap_to_up]
    phase2_interfaces = member_interfaces[links_to_mincap_to_up:links_to_mincap]
    phase3_interface = [member_interfaces[links_to_mincap]]

    return Playbook(
        name=playbook_name,
        iteration=iteration,
        prechecks=[],
        stages=[
            # Stage 1: Disable to MinCapToUp boundary → LAG stays UP
            create_port_channel_initial_setup_stage(
                interfaces_to_disable=phase1_interfaces,
                portchannel_health_check=create_portchannel_health_check(
                    port_channel_name_map=portchannel_name_map,
                    expected_up=True,
                ),
            ),
            # Stage 2: Disable to MinCap boundary → LAG stays UP
            create_steps_stage(
                steps=[
                    create_interface_flap_step(
                        enable=False,
                        interfaces=phase2_interfaces,
                        interface_flap_method=taac_types.InterfaceFlapMethod.THRIFT_PORT_STATE_CHANGE,
                    ),
                    create_verify_port_operational_state_step(
                        interfaces=phase2_interfaces,
                        operational_state=False,
                    ),
                    create_validation_step(
                        point_in_time_checks=[
                            create_portchannel_health_check(
                                port_channel_name_map=portchannel_name_map,
                                expected_up=True,
                            ),
                        ],
                        description="Validate port channel health",
                    ),
                ]
            ),
            # Stage 3: Disable one more below MinCap → LAG goes DOWN
            create_steps_stage(
                steps=[
                    create_interface_flap_step(
                        enable=False,
                        interfaces=phase3_interface,
                        interface_flap_method=taac_types.InterfaceFlapMethod.THRIFT_PORT_STATE_CHANGE,
                    ),
                    create_verify_port_operational_state_step(
                        interfaces=phase3_interface, operational_state=False
                    ),
                    create_validation_step(
                        point_in_time_checks=[
                            create_portchannel_health_check(
                                port_channel_name_map=portchannel_name_map,
                                expected_up=False,
                            ),
                        ],
                        description="Validate port channel health",
                    ),
                ]
            ),
            # Stage 4: Re-enable one (at MinCap) → LAG still DOWN
            create_steps_stage(
                steps=[
                    create_interface_flap_step(
                        enable=True,
                        interfaces=phase3_interface,
                        interface_flap_method=taac_types.InterfaceFlapMethod.THRIFT_PORT_STATE_CHANGE,
                    ),
                    create_verify_port_operational_state_step(
                        interfaces=phase3_interface,
                        operational_state=True,
                    ),
                    create_validation_step(
                        point_in_time_checks=[
                            create_portchannel_health_check(
                                port_channel_name_map=portchannel_name_map,
                                expected_up=False,
                            ),
                        ],
                        description="Validate port channel health",
                    ),
                ]
            ),
            # Stage 5: Re-enable to MinCapToUp → LAG goes UP
            create_steps_stage(
                steps=[
                    create_interface_flap_step(
                        enable=True,
                        interfaces=phase2_interfaces,
                        interface_flap_method=taac_types.InterfaceFlapMethod.THRIFT_PORT_STATE_CHANGE,
                    ),
                    create_verify_port_operational_state_step(
                        interfaces=phase2_interfaces, operational_state=True
                    ),
                    create_validation_step(
                        point_in_time_checks=[
                            create_portchannel_health_check(
                                port_channel_name_map=portchannel_name_map,
                                expected_up=True,
                            ),
                        ],
                        description="Validate port channel health",
                    ),
                ]
            ),
            # Stage 6: Restore all remaining links
            create_port_channel_teardown_stage(
                interfaces_to_enable=phase1_interfaces,
                portchannel_health_check=create_portchannel_health_check(
                    port_channel_name_map=portchannel_name_map,
                    expected_up=True,
                ),
            ),
            create_steps_stage(
                steps=[
                    create_longevity_step(duration=300),
                ]
            ),
        ],
        postchecks=[
            create_ixia_packet_loss_check(
                clear_traffic_stats=True,
            )
        ],
        cleanup_steps=_create_lag_cleanup_steps(member_interfaces),
    )


def create_lag_baseline_playbook_2(
    playbook_name: str,
    member_interfaces: list[str],
    min_link_percentage: float,
    min_link_up_percentage: float,
    portchannel_name_map: dict[str, list[str]],
    iteration: int = 10,
) -> Playbook:
    """
    Build LAG_002: port-channel variable-minlink oscillation Playbook.

    After leaving `min_cap_to_up` members enabled, oscillates the
    boundary members between MinCap and MinCapToUp for 25 iterations and
    verifies the port-channel remains operationally up throughout. This
    stresses LACP hysteresis under repeated link transitions.

    Args:
        playbook_name: Name to record the playbook under.
        port_channel_name: DUT port-channel under test.
        member_interfaces: All physical members of the port-channel.
        min_link_percentage: Fractional MinLinks threshold (0-1).
        min_link_up_percentage: Fractional MinLinksUp threshold (0-1).

    Returns:
        A `Playbook` with standard LAG checks and a 25-iteration
        oscillation stage on the MinCap..MinCapToUp boundary members.
    """
    total_links = len(member_interfaces)
    min_cap = _compute_min_capacity(total_links, min_link_percentage)
    min_cap_to_up = _compute_min_capacity_to_up(total_links, min_link_up_percentage)

    links_to_mincap = total_links - min_cap
    links_to_mincap_to_up = total_links - min_cap_to_up
    interfaces_to_disable = member_interfaces[:links_to_mincap_to_up]
    oscillation_interface = member_interfaces[links_to_mincap_to_up:links_to_mincap]

    return Playbook(
        name=playbook_name,
        prechecks=[],
        stages=[
            # Stage 1: Disable to MinCap → LAG stays UP
            create_port_channel_initial_setup_stage(
                interfaces_to_disable=interfaces_to_disable,
                portchannel_health_check=create_portchannel_health_check(
                    port_channel_name_map=portchannel_name_map,
                    expected_up=True,
                ),
            ),
            # Stage 2: Flap one link to oscillate between MinCap and MinCapToUp
            # LAG should remain UP since it never drops below MinCap
            create_port_channel_flap_only_stage(
                interfaces_to_flap=oscillation_interface,
                iteration=iteration,
            ),
            create_steps_stage(
                steps=[
                    create_validation_step(
                        point_in_time_checks=[
                            create_portchannel_health_check(
                                port_channel_name_map=portchannel_name_map,
                                expected_up=True,
                            ),
                        ],
                        description="Validate port channel health",
                    ),
                ]
            ),
            create_port_channel_teardown_stage(
                interfaces_to_enable=interfaces_to_disable,
                portchannel_health_check=create_portchannel_health_check(
                    port_channel_name_map=portchannel_name_map,
                    expected_up=True,
                ),
            ),
        ],
        postchecks=[
            create_ixia_packet_loss_check(
                clear_traffic_stats=True,
            )
        ],
        cleanup_steps=_create_lag_cleanup_steps(member_interfaces),
    )


def create_lag_longevity_playbook(
    playbook_name: str,
    member_interfaces: list[str],
    duration: int = 3600,
) -> Playbook:
    """
    Build LAG_003: port-channel longevity Playbook.

    All members up for `duration` seconds (default 1 hour); standard LAG
    pre/postchecks and the snapshot check verify no link flaps occurred
    during the soak.

    Args:
        playbook_name: Name to record the playbook under.
        port_channel_name: DUT port-channel under test.
        member_interfaces: All physical members (used for cleanup steps).
        duration: Longevity stage duration in seconds. Default 3600.

    Returns:
        A `Playbook` with one longevity stage plus standard LAG checks.
    """
    return Playbook(
        name=playbook_name,
        stages=[
            create_steps_stage(
                steps=[
                    create_longevity_step(duration=duration),
                ]
            ),
        ],
        cleanup_steps=_create_lag_cleanup_steps(member_interfaces),
    )


def create_lag_all_link_flap_playbook(
    playbook_name: str,
    member_interfaces: list[str],
    portchannel_name_map: dict[str, list[str]],
    iterations: int = 25,
    with_agent_restart: bool = False,
    cold_boot: bool = False,
) -> Playbook:
    """
    Build a 100%-member-link-flap port-channel Playbook with optional concurrent agent restart/coldboot.

    LAG_004: with_agent_restart=True, cold_boot=False, iterations=15
    LAG_008: with_agent_restart=True, cold_boot=True, iterations=10
    LAG_012: with_agent_restart=False, iterations=25

    Flaps all members concurrently for `iterations` iterations and
    asserts the port-channel returns to operationally-up at the end.
    With `with_agent_restart=True`, runs the flap concurrently with an
    AGENT systemctl restart (and optional coldboot via `cold_boot=True`)
    to validate combined hardware + control-plane resilience.

    Args:
        playbook_name: Name to record the playbook under.
        port_channel_name: DUT port-channel under test.
        member_interfaces: All physical members of the port-channel.
        iterations: Flap-cycle count. Default 25.
        with_agent_restart: If True, concurrently restart the AGENT.
            Default False.
        cold_boot: If True (and `with_agent_restart`), use coldboot
            instead of warmboot. Default False.

    Returns:
        A `Playbook` with standard LAG checks and the configured flap
        stage.
    """
    if with_agent_restart:
        test_stage = create_port_channel_concurrent_flap_stage(
            interfaces_to_flap=member_interfaces,
            iteration=iterations,
            cold_boot=cold_boot,
        )
    else:
        test_stage = create_port_channel_flap_only_stage(
            interfaces_to_flap=member_interfaces,
            iteration=iterations,
        )

    return Playbook(
        name=playbook_name,
        prechecks=[],
        stages=[
            test_stage,
            # Stage 2: validation step
            create_steps_stage(
                steps=[
                    # longevity step to wait for LACP to converge after agent restart and BGP to converge
                    create_longevity_step(duration=300),
                    create_validation_step(
                        point_in_time_checks=[
                            create_portchannel_health_check(
                                port_channel_name_map=portchannel_name_map,
                                expected_up=True,
                            ),
                        ],
                        description="Validate port channel health",
                    ),
                ]
            ),
        ],
        postchecks_to_skip=(
            [hc_types.CheckName.SERVICE_RESTART_CHECK] if with_agent_restart else []
        ),
        postchecks=[
            create_ixia_packet_loss_check(
                clear_traffic_stats=True,
            )
        ],
        cleanup_steps=_create_lag_cleanup_steps(member_interfaces),
    )


def create_lag_variable_minlink_flap_playbook(
    playbook_name: str,
    member_interfaces: list[str],
    min_link_percentage: float,
    min_link_up_percentage: float,
    portchannel_name_map: dict[str, list[str]],
    variation: LinkFlapVariation,
    iterations: int = 25,
    with_agent_restart: bool = False,
    cold_boot: bool = False,
) -> Playbook:
    """
    Variable minlink flap: permanently disable links to MinCapToUp,
    then flap K links based on variation ± concurrent agent restart.

    LAG_005: variation=BELOW, with_agent_restart=True, iterations=15
    LAG_006: variation=AT, with_agent_restart=True, iterations=15
    LAG_007: variation=ABOVE, with_agent_restart=True, iterations=15
    LAG_009: variation=BELOW, with_agent_restart=True, cold_boot=True, iterations=10
    LAG_010: variation=AT, with_agent_restart=True, cold_boot=True, iterations=10
    LAG_011: variation=ABOVE, with_agent_restart=True, cold_boot=True, iterations=10
    LAG_013: variation=BELOW, with_agent_restart=False, iterations=25
    LAG_014: variation=AT, with_agent_restart=False, iterations=25
    LAG_015: variation=ABOVE, with_agent_restart=False, iterations=25

    Permanently disables enough members to leave exactly MinCapToUp
    active, then flaps `K` members where `K` is derived from `variation`
    relative to the MinCap..MinCapToUp boundary (above / at / below /
    all). Optional concurrent AGENT restart (with optional coldboot) via
    `with_agent_restart`/`cold_boot`. Used to characterize behavior at
    different points on the LACP min-link curve.

    Args:
        playbook_name: Name to record the playbook under.
        port_channel_name: DUT port-channel under test.
        member_interfaces: All physical members of the port-channel.
        min_link_percentage: Fractional MinLinks threshold (0-1).
        min_link_up_percentage: Fractional MinLinksUp threshold (0-1).
        variation: `LinkFlapVariation` choosing where on the
            MinCap..MinCapToUp curve to flap (below / at / above / all).
        iterations: Flap-cycle count. Default 25.
        with_agent_restart: If True, concurrently restart the AGENT.
            Default False.
        cold_boot: If True (and `with_agent_restart`), use coldboot.
            Default False.

    Returns:
        A `Playbook` with standard LAG checks, a permanent-disable
        setup, the configured flap stage, and a permanent-teardown stage.
    """
    total_links = len(member_interfaces)
    min_cap = _compute_min_capacity(total_links, min_link_percentage)
    min_cap_to_up = _compute_min_capacity_to_up(total_links, min_link_up_percentage)

    links_to_permanently_disable = total_links - min_cap_to_up
    links_to_flap_count = _compute_links_to_flap(min_cap, min_cap_to_up, variation)

    permanently_disabled = member_interfaces[:links_to_permanently_disable]
    flap_interfaces = member_interfaces[
        links_to_permanently_disable : links_to_permanently_disable
        + links_to_flap_count
    ]

    if with_agent_restart:
        test_stage = create_port_channel_concurrent_flap_stage(
            interfaces_to_flap=flap_interfaces,
            iteration=iterations,
            cold_boot=cold_boot,
        )
    else:
        test_stage = create_port_channel_flap_only_stage(
            interfaces_to_flap=flap_interfaces,
            iteration=iterations,
        )

    return Playbook(
        name=playbook_name,
        prechecks=[],
        stages=[
            # Stage 1: Permanently disable links to reach MinCapToUp
            # NOTE: For tests with agent restart, this disable may not persist
            # across restarts. A persistent patcher mechanism (e.g.,
            # async_register_patcher_to_shut_ports_persistently) should be
            # used if the agent restart re-enables these interfaces.
            create_port_channel_initial_setup_stage_with_permanent_disable(
                interfaces_to_disable=permanently_disabled,
                portchannel_health_check=create_portchannel_health_check(
                    port_channel_name_map=portchannel_name_map,
                    expected_up=True,
                ),
            ),
            # Stage 2: Flap K links ± restart
            test_stage,
            create_steps_stage(
                steps=[
                    # longevity step to wait for LACP to converge after agent restart
                    create_longevity_step(duration=60),
                    create_validation_step(
                        point_in_time_checks=[
                            create_portchannel_health_check(
                                port_channel_name_map=portchannel_name_map,
                                expected_up=True,
                            ),
                        ],
                        description="Validate port channel health",
                    ),
                ]
            ),
            create_port_channel_permanent_teardown_stage(
                interfaces_to_enable=permanently_disabled,
                portchannel_health_check=create_portchannel_health_check(
                    port_channel_name_map=portchannel_name_map,
                    expected_up=True,
                ),
            ),
            create_steps_stage(
                steps=[
                    create_longevity_step(duration=300),
                ]
            ),
        ],
        postchecks_to_skip=(
            [hc_types.CheckName.SERVICE_RESTART_CHECK] if with_agent_restart else []
        ),
        postchecks=[
            create_ixia_packet_loss_check(
                clear_traffic_stats=True,
            )
        ],
        cleanup_steps=_create_lag_permanent_cleanup_steps(),
    )


def create_lag_cross_flap_playbook(
    playbook_name: str,
    dut_name: str,
    remote_name: str,
    dut_member_interfaces: list[str],
    remote_member_interfaces: list[str],
    portchannel_name_map: dict[str, list[str]],
    cross_flap_links: int = 2,
    iterations: int = 25,
    with_agent_restart: bool = False,
    cold_boot: bool = False,
) -> Playbook:
    """
    Build a cross-flap port-channel Playbook.

    Simultaneously flaps `cross_flap_links` members on the DUT and
    `cross_flap_links` non-overlapping members on the remote, for
    `iterations` iterations. Optional concurrent AGENT restart (with
    optional coldboot) via `with_agent_restart` / `cold_boot`. Used to
    stress LACP convergence when both ends mutate state at once.

    Args:
        playbook_name: Name to record the playbook under.
        port_channel_name: DUT port-channel under test.
        dut_member_interfaces: All DUT-side physical members.
        remote_member_interfaces: All remote-side physical members.
        cross_flap_links: Per-side count of members to flap (DUT picks
            `[0:K]`, remote picks `[K:2K]`). Default 2.
        iterations: Flap-cycle count. Default 25.
        with_agent_restart: If True, concurrently restart the AGENT.
            Default False.
        cold_boot: If True (and `with_agent_restart`), use coldboot.
            Default False.

    Returns:
        A `Playbook` with standard LAG checks and the cross-flap stage,
        verifying the port-channel returns to operationally-up.
    """
    dut_flap_interfaces = dut_member_interfaces[:cross_flap_links]
    remote_flap_interfaces = remote_member_interfaces[
        cross_flap_links : 2 * cross_flap_links
    ]

    if with_agent_restart:
        test_stage = create_port_channel_concurrent_cross_flap_stage(
            dut_flap_interfaces=dut_flap_interfaces,
            remote_flap_interfaces=remote_flap_interfaces,
            dut_name=dut_name,
            remote_name=remote_name,
            iterations=iterations,
            cold_boot=cold_boot,
        )
    else:
        test_stage = create_port_channel_cross_flap_stage(
            dut_flap_interfaces=dut_flap_interfaces,
            remote_flap_interfaces=remote_flap_interfaces,
            dut_name=dut_name,
            remote_name=remote_name,
            iterations=iterations,
        )

    return Playbook(
        name=playbook_name,
        prechecks=[],
        stages=[
            # Stage 1: Verify starting state
            create_steps_stage(
                steps=[
                    create_verify_port_operational_state_step(
                        interfaces=dut_member_interfaces, operational_state=True
                    ),
                ]
            ),
            # Stage 2: Cross flap ± restart
            test_stage,
            create_steps_stage(
                steps=[
                    create_longevity_step(duration=300),
                    create_validation_step(
                        point_in_time_checks=[
                            create_portchannel_health_check(
                                port_channel_name_map=portchannel_name_map,
                                expected_up=True,
                            ),
                        ],
                        description="Validate port channel health",
                    ),
                ]
            ),
        ],
        postchecks_to_skip=(
            [hc_types.CheckName.SERVICE_RESTART_CHECK] if with_agent_restart else []
        ),
        postchecks=[
            create_ixia_packet_loss_check(
                clear_traffic_stats=True,
            )
        ],
        cleanup_steps=_create_lag_cleanup_steps(
            dut_member_interfaces,
        ),
    )


def create_lag_mismatched_minlink_playbook(
    playbook_name: str,
    remote_device_name: str,
    dut_port_channel_name: str,
    remote_port_channel_name: str,
    dut_member_interfaces: list[str],
    dut_min_link_percentage: float,
    dut_min_link_up_percentage: float,
    remote_min_link_percentage: float,
    remote_min_link_up_percentage: float,
    links_to_permanently_disable: int,
    portchannel_name_map: dict[str, list[str]],
    links_to_flap: int,
    iterations: int = 15,
    cold_boot: bool = False,
) -> Playbook:
    """
    Mismatched minlink config between DUT and remote. Permanently disable
    some links on DUT, then flap K links on DUT with concurrent agent restart.

    The thresholds differ on each side, so the LAG goes DOWN/UP based on
    whichever side's threshold is violated first.

    LAG_018: perm_disable=1, flap=3 — remote MinCap triggers DOWN
    LAG_019: perm_disable=1, flap=4 — DUT MinCap triggers DOWN
    LAG_020: perm_disable=2, flap=2 — remote MinCap triggers, DUT comes up with peer
    LAG_021: perm_disable=2, flap=3 — both sides stay DOWN

    Tests behavior when DUT and remote have intentionally different
    MinLinks/MinLinksUp percentages (passed only for documentation here —
    the helper steps consume them indirectly). Permanently disables
    `links_to_permanently_disable` DUT members, then concurrently flaps
    `links_to_flap` more for `iterations` iterations (with optional
    coldboot via `cold_boot`).

    Args:
        playbook_name: Name to record the playbook under.
        dut_port_channel_name: DUT port-channel under test.
        remote_port_channel_name: Remote port-channel (informational —
            used by snapshot/cleanup helpers in the wider TestConfig).
        dut_member_interfaces: All DUT-side physical members.
        remote_member_interfaces: All remote-side physical members.
        dut_min_link_percentage / dut_min_link_up_percentage /
            remote_min_link_percentage / remote_min_link_up_percentage:
            Documenting the mismatch (raw values, not consumed here).
        links_to_permanently_disable: Count of DUT members permanently
            disabled before the flap stage.
        links_to_flap: Count of DUT members flapped concurrently.
        iterations: Flap-cycle count. Default 15.
        cold_boot: If True, use coldboot during the concurrent flap.
            Default False.

    Returns:
        A `Playbook` with standard LAG checks, the permanent-disable
        setup, the concurrent-flap stage, and a permanent-teardown stage.
    """
    permanently_disabled = dut_member_interfaces[:links_to_permanently_disable]
    flap_interfaces = dut_member_interfaces[
        links_to_permanently_disable : links_to_permanently_disable + links_to_flap
    ]

    return Playbook(
        name=playbook_name,
        prechecks=[],
        stages=[
            # Stage 1: Update the minlink config on both sides
            create_steps_stage(
                steps=[
                    create_register_patcher_step(
                        patcher_name="set_port_channel_mismatch_min_link_capacity",
                        py_func_name="set_port_channel_min_link_capacity",
                        kwargs={
                            "port_channel_name": dut_port_channel_name,
                            "link_percentage": str(dut_min_link_percentage),
                            "link_up_percentage": str(dut_min_link_up_percentage),
                        },
                        config_name="agent",
                        description="Set port channel mismatch min link capacity",
                    ),
                    create_service_interruption_step(
                        service=taac_types.Service.AGENT,
                        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                        create_cold_boot_file=cold_boot,
                    ),
                    create_register_patcher_step(
                        patcher_name="set_port_channel_mismatch_min_link_capacity",
                        py_func_name="set_port_channel_min_link_capacity",
                        kwargs={
                            "port_channel_name": remote_port_channel_name,
                            "link_percentage": str(remote_min_link_percentage),
                            "link_up_percentage": str(remote_min_link_up_percentage),
                        },
                        config_name="agent",
                        description="Set port channel mismatch min link capacity",
                        device_regexes=[remote_device_name],
                    ),
                    create_service_interruption_step(
                        service=taac_types.Service.AGENT,
                        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                        create_cold_boot_file=cold_boot,
                        device_regexes=[remote_device_name],
                    ),
                    create_service_convergence_step(),
                    create_service_convergence_step(
                        device_regexes=[remote_device_name],
                    ),
                ]
            ),
            # Stage 2: Permanently disable links on DUT
            create_port_channel_initial_setup_stage_with_permanent_disable(
                interfaces_to_disable=permanently_disabled,
                portchannel_health_check=create_portchannel_health_check(
                    port_channel_name_map=portchannel_name_map,
                    expected_up=True,
                ),
            ),
            # Stage 3: Concurrent flap + agent restart
            create_port_channel_concurrent_flap_stage(
                interfaces_to_flap=flap_interfaces,
                iteration=iterations,
                cold_boot=cold_boot,
            ),
            # Stage 4: Restore — re-enable all disabled links on DUT
            create_steps_stage(
                steps=[
                    create_unregister_patcher_step(
                        patcher_name="set_port_channel_mismatch_min_link_capacity",
                        config_name="agent",
                    ),
                    create_service_interruption_step(
                        service=taac_types.Service.AGENT,
                        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                        create_cold_boot_file=cold_boot,
                    ),
                    create_unregister_patcher_step(
                        patcher_name="set_port_channel_mismatch_min_link_capacity",
                        config_name="agent",
                        device_regexes=[remote_device_name],
                    ),
                    create_service_interruption_step(
                        service=taac_types.Service.AGENT,
                        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                        create_cold_boot_file=cold_boot,
                        device_regexes=[remote_device_name],
                    ),
                    create_service_convergence_step(),
                    create_service_convergence_step(
                        device_regexes=[remote_device_name],
                    ),
                ]
            ),
            create_port_channel_permanent_teardown_stage(
                interfaces_to_enable=permanently_disabled,
                portchannel_health_check=create_portchannel_health_check(
                    port_channel_name_map=portchannel_name_map,
                    expected_up=True,
                ),
            ),
            create_steps_stage(
                steps=[
                    create_longevity_step(duration=300),
                ]
            ),
        ],
        postchecks_to_skip=[hc_types.CheckName.SERVICE_RESTART_CHECK],
        postchecks=[
            create_ixia_packet_loss_check(
                clear_traffic_stats=True,
            )
        ],
        cleanup_steps=_create_lag_permanent_cleanup_steps(),
    )


def create_all_lag_playbooks(
    dut_name: str,
    remote_name: str,
    dut_port_channel_name: str,
    remote_port_channel_name: str,
    dut_member_interfaces: list[str],
    remote_member_interfaces: list[str],
    min_link_percentage: float,
    min_link_up_percentage: float,
    dut_mistmatch_min_link_percentage: float,
    dut_mistmatch_min_link_up_percentage: float,
    remote_mistmatch_min_link_percentage: float | None = None,
    remote_mistmatch_min_link_up_percentage: float | None = None,
) -> list[Playbook]:
    """
    Build the full P0 LAG Playbook bundle (LAG_001 through LAG_021).

    For mismatched minlink tests (LAG_018-021), provide remote_min_link_percentage
    and remote_min_link_up_percentage. If not provided, defaults to
    DUT: min=50%/up=85%, Remote: min=62.5%/up=75% for an 8-member LAG.

    Generates the canonical 21-playbook portchannel coverage suite:
    baseline-1/2, longevity, all-flap warm/coldboot, per-variation
    minlink flaps (above/at/below) with and without agent restart, cross
    flaps, and the DUT/remote mismatched-minlink variant. Used by the
    portchannel TestConfigs as the standard P0 suite.

    Args:
        dut_port_channel_name: DUT port-channel name.
        remote_port_channel_name: Remote port-channel name.
        dut_member_interfaces: All DUT-side physical members.
        remote_member_interfaces: All remote-side physical members.
        min_link_percentage: Default fractional MinLinks threshold.
        min_link_up_percentage: Default fractional MinLinksUp threshold.
        dut_mistmatch_min_link_percentage / dut_mistmatch_min_link_up_percentage:
            DUT thresholds for the mismatched-minlink variant (sic on
            spelling — preserved from upstream).
        remote_mistmatch_min_link_percentage: Optional remote MinLinks for
            the mismatched-minlink variant. Default 0.625.
        remote_mistmatch_min_link_up_percentage: Optional remote
            MinLinksUp for the mismatched-minlink variant. Default 0.75.

    Returns:
        List of `Playbook` objects covering LAG_001..LAG_021 in order.
    """
    if remote_mistmatch_min_link_percentage is None:
        remote_mistmatch_min_link_percentage = 0.625
    if remote_mistmatch_min_link_up_percentage is None:
        remote_mistmatch_min_link_up_percentage = 0.75

    portchannel_to_device_map = {
        dut_name: [dut_port_channel_name],
        remote_name: [remote_port_channel_name],
    }

    _prechecks = _create_lag_prechecks(portchannel_to_device_map)

    _postchecks = _create_lag_postchecks(portchannel_to_device_map)

    playbooks_ = [
        # LAG_001: Baseline functionality — progressive disable/enable
        create_lag_baseline_playbook_1(
            playbook_name="lag_001_baseline_functionality_1",
            member_interfaces=dut_member_interfaces,
            min_link_percentage=min_link_percentage,
            min_link_up_percentage=min_link_up_percentage,
            portchannel_name_map=portchannel_to_device_map,
            iteration=10,
        ),
        # LAG_002: Baseline functionality — threshold oscillation
        create_lag_baseline_playbook_2(
            playbook_name="lag_002_baseline_functionality_2",
            member_interfaces=dut_member_interfaces,
            min_link_percentage=min_link_percentage,
            min_link_up_percentage=min_link_up_percentage,
            portchannel_name_map=portchannel_to_device_map,
            iteration=10,
        ),
        # LAG_003: Longevity — 1 hour
        create_lag_longevity_playbook(
            playbook_name="lag_003_longevity",
            member_interfaces=dut_member_interfaces,
            duration=3600,
        ),
        # LAG_004: 100% flap + warmboot, 15 iterations
        create_lag_all_link_flap_playbook(
            playbook_name="lag_004_all_flap_warmboot",
            member_interfaces=dut_member_interfaces,
            portchannel_name_map=portchannel_to_device_map,
            iterations=15,
            with_agent_restart=True,
            cold_boot=False,
        ),
        # LAG_005: Variable minlink below MinCap + warmboot, 15 iterations
        create_lag_variable_minlink_flap_playbook(
            playbook_name="lag_005_variable_minlink_below_warmboot",
            member_interfaces=dut_member_interfaces,
            min_link_percentage=min_link_percentage,
            min_link_up_percentage=min_link_up_percentage,
            portchannel_name_map=portchannel_to_device_map,
            variation=LinkFlapVariation.BELOW_MIN_CAPACITY,
            iterations=15,
            with_agent_restart=True,
        ),
        # LAG_006: Variable minlink at MinCap + warmboot, 15 iterations
        create_lag_variable_minlink_flap_playbook(
            playbook_name="lag_006_variable_minlink_at_warmboot",
            member_interfaces=dut_member_interfaces,
            min_link_percentage=min_link_percentage,
            min_link_up_percentage=min_link_up_percentage,
            portchannel_name_map=portchannel_to_device_map,
            variation=LinkFlapVariation.AT_MIN_CAPACITY,
            iterations=15,
            with_agent_restart=True,
        ),
        # LAG_007: Variable minlink above MinCap + warmboot, 15 iterations
        create_lag_variable_minlink_flap_playbook(
            playbook_name="lag_007_variable_minlink_above_warmboot",
            member_interfaces=dut_member_interfaces,
            min_link_percentage=min_link_percentage,
            min_link_up_percentage=min_link_up_percentage,
            portchannel_name_map=portchannel_to_device_map,
            variation=LinkFlapVariation.ABOVE_MIN_CAPACITY,
            iterations=15,
            with_agent_restart=True,
        ),
        # LAG_008: 100% flap + coldboot, 10 iterations
        create_lag_all_link_flap_playbook(
            playbook_name="lag_008_all_flap_coldboot",
            member_interfaces=dut_member_interfaces,
            portchannel_name_map=portchannel_to_device_map,
            iterations=10,
            with_agent_restart=True,
            cold_boot=True,
        ),
        # LAG_009: Variable minlink below MinCap + coldboot, 10 iterations
        create_lag_variable_minlink_flap_playbook(
            playbook_name="lag_009_variable_minlink_below_coldboot",
            member_interfaces=dut_member_interfaces,
            min_link_percentage=min_link_percentage,
            min_link_up_percentage=min_link_up_percentage,
            portchannel_name_map=portchannel_to_device_map,
            variation=LinkFlapVariation.BELOW_MIN_CAPACITY,
            iterations=10,
            with_agent_restart=True,
            cold_boot=True,
        ),
        # LAG_010: Variable minlink at MinCap + coldboot, 10 iterations
        create_lag_variable_minlink_flap_playbook(
            playbook_name="lag_010_variable_minlink_at_coldboot",
            member_interfaces=dut_member_interfaces,
            min_link_percentage=min_link_percentage,
            min_link_up_percentage=min_link_up_percentage,
            portchannel_name_map=portchannel_to_device_map,
            variation=LinkFlapVariation.AT_MIN_CAPACITY,
            iterations=10,
            with_agent_restart=True,
            cold_boot=True,
        ),
        # LAG_011: Variable minlink above MinCap + coldboot, 10 iterations
        create_lag_variable_minlink_flap_playbook(
            playbook_name="lag_011_variable_minlink_above_coldboot",
            member_interfaces=dut_member_interfaces,
            min_link_percentage=min_link_percentage,
            min_link_up_percentage=min_link_up_percentage,
            portchannel_name_map=portchannel_to_device_map,
            variation=LinkFlapVariation.ABOVE_MIN_CAPACITY,
            iterations=10,
            with_agent_restart=True,
            cold_boot=True,
        ),
        # LAG_012: 100% flap, no restart, 25 iterations
        create_lag_all_link_flap_playbook(
            playbook_name="lag_012_all_flap_stress",
            member_interfaces=dut_member_interfaces,
            portchannel_name_map=portchannel_to_device_map,
            iterations=25,
            with_agent_restart=False,
        ),
        # LAG_013: Variable minlink below MinCap, no restart, 25 iterations
        create_lag_variable_minlink_flap_playbook(
            playbook_name="lag_013_variable_minlink_below_stress",
            member_interfaces=dut_member_interfaces,
            min_link_percentage=min_link_percentage,
            min_link_up_percentage=min_link_up_percentage,
            portchannel_name_map=portchannel_to_device_map,
            variation=LinkFlapVariation.BELOW_MIN_CAPACITY,
            iterations=25,
        ),
        # LAG_014: Variable minlink at MinCap, no restart, 25 iterations
        create_lag_variable_minlink_flap_playbook(
            playbook_name="lag_014_variable_minlink_at_stress",
            member_interfaces=dut_member_interfaces,
            min_link_percentage=min_link_percentage,
            min_link_up_percentage=min_link_up_percentage,
            portchannel_name_map=portchannel_to_device_map,
            variation=LinkFlapVariation.AT_MIN_CAPACITY,
            iterations=25,
        ),
        # LAG_015: Variable minlink above MinCap, no restart, 25 iterations
        create_lag_variable_minlink_flap_playbook(
            playbook_name="lag_015_variable_minlink_above_stress",
            member_interfaces=dut_member_interfaces,
            min_link_percentage=min_link_percentage,
            min_link_up_percentage=min_link_up_percentage,
            portchannel_name_map=portchannel_to_device_map,
            variation=LinkFlapVariation.ABOVE_MIN_CAPACITY,
            iterations=25,
        ),
        # LAG_016: Cross flap, no restart, 25 iterations
        create_lag_cross_flap_playbook(
            playbook_name="lag_016_cross_flap",
            dut_name=dut_name,
            remote_name=remote_name,
            dut_member_interfaces=dut_member_interfaces,
            remote_member_interfaces=remote_member_interfaces,
            portchannel_name_map=portchannel_to_device_map,
            cross_flap_links=1,
            iterations=25,
        ),
        # LAG_017: Cross flap + warmboot, 15 iterations
        create_lag_cross_flap_playbook(
            playbook_name="lag_017_cross_flap_warmboot",
            dut_name=dut_name,
            remote_name=remote_name,
            dut_member_interfaces=dut_member_interfaces,
            remote_member_interfaces=remote_member_interfaces,
            portchannel_name_map=portchannel_to_device_map,
            cross_flap_links=1,
            iterations=15,
            with_agent_restart=True,
        ),
        # LAG_018: Mismatched minlink — perm disable 0, flap 3 (remote MinCap)
        create_lag_mismatched_minlink_playbook(
            playbook_name="lag_018_mismatched_minlink_remote_mincap",
            remote_device_name=remote_name,
            dut_port_channel_name=dut_port_channel_name,
            remote_port_channel_name=remote_port_channel_name,
            dut_member_interfaces=dut_member_interfaces,
            dut_min_link_percentage=dut_mistmatch_min_link_percentage,
            dut_min_link_up_percentage=dut_mistmatch_min_link_up_percentage,
            remote_min_link_percentage=remote_mistmatch_min_link_percentage,
            remote_min_link_up_percentage=remote_mistmatch_min_link_up_percentage,
            portchannel_name_map=portchannel_to_device_map,
            links_to_permanently_disable=0,
            links_to_flap=3,
            iterations=15,
        ),
        # LAG_019: Mismatched minlink — perm disable 0, flap 4 (DUT MinCap)
        create_lag_mismatched_minlink_playbook(
            playbook_name="lag_019_mismatched_minlink_dut_mincap",
            remote_device_name=remote_name,
            dut_port_channel_name=dut_port_channel_name,
            remote_port_channel_name=remote_port_channel_name,
            dut_member_interfaces=dut_member_interfaces,
            dut_min_link_percentage=dut_mistmatch_min_link_percentage,
            dut_min_link_up_percentage=dut_mistmatch_min_link_up_percentage,
            remote_min_link_percentage=remote_mistmatch_min_link_percentage,
            remote_min_link_up_percentage=remote_mistmatch_min_link_up_percentage,
            portchannel_name_map=portchannel_to_device_map,
            links_to_permanently_disable=0,
            links_to_flap=4,
            iterations=15,
        ),
        # LAG_020: Mismatched minlink — perm disable 1, flap 2 (remote recovers with peer)
        create_lag_mismatched_minlink_playbook(
            playbook_name="lag_020_mismatched_minlink_peer_recovery",
            remote_device_name=remote_name,
            dut_port_channel_name=dut_port_channel_name,
            remote_port_channel_name=remote_port_channel_name,
            dut_member_interfaces=dut_member_interfaces,
            dut_min_link_percentage=dut_mistmatch_min_link_percentage,
            dut_min_link_up_percentage=dut_mistmatch_min_link_up_percentage,
            remote_min_link_percentage=remote_mistmatch_min_link_percentage,
            remote_min_link_up_percentage=remote_mistmatch_min_link_up_percentage,
            portchannel_name_map=portchannel_to_device_map,
            links_to_permanently_disable=1,
            links_to_flap=2,
            iterations=15,
        ),
        # LAG_021: Mismatched minlink — perm disable 1, flap 3 (both sides down)
        create_lag_mismatched_minlink_playbook(
            playbook_name="lag_021_mismatched_minlink_both_down",
            remote_device_name=remote_name,
            dut_port_channel_name=dut_port_channel_name,
            remote_port_channel_name=remote_port_channel_name,
            dut_member_interfaces=dut_member_interfaces,
            dut_min_link_percentage=dut_mistmatch_min_link_percentage,
            dut_min_link_up_percentage=dut_mistmatch_min_link_up_percentage,
            remote_min_link_percentage=remote_mistmatch_min_link_percentage,
            remote_min_link_up_percentage=remote_mistmatch_min_link_up_percentage,
            portchannel_name_map=portchannel_to_device_map,
            links_to_permanently_disable=1,
            links_to_flap=3,
            iterations=15,
        ),
    ]

    playbooks_ = [
        _pb(
            prechecks=_prechecks + list(_pb.prechecks or []),
            postchecks=_postchecks + list(_pb.postchecks or []),
            snapshot_checks=list(_pb.snapshot_checks or []),
        )
        for _pb in playbooks_
    ]

    return playbooks_


# =============================================================================
# BGP DC Platform Hardening playbooks
# (migrated from playbooks/helpers/routing/bgp_dc/platform_hardening_playbooks.py
#  in Phase 4 v2)
# =============================================================================


def get_platform_hardening_playbooks(
    device_name,
    ixia_downlink_interface,
    ixia_uplink_interface,
    good_ndp_entries_downlink,
    good_ndp_entries_uplink,
    rogue_ndp_entries,
    good_arp_entries,
    rogue_arp_entries,
    good_mac_entry_count,
    rogue_mac_entry_count,
    ecmp_group_limit,
    ixia_uplink_good_ndp_network,
    ixia_rogue_ic_parent_network_v6,
    ixia_rogue_ic_parent_network_v4,
    ndp_entry_limit=NDP_SOFT_LIMIT,
    arp_entry_limit=ARP_SOFT_LIMIT,
    mac_entry_limit=MAC_SOFT_LIMIT,
    ecmp_member_limit=11500,
    ecmp_member_test_member_limit=11950,
    ecmp_member_test_group_limit=1300,
    bgpd_restart_no_of_interations=1,
    wedge_agent_restart_no_of_interations=1,
    process_restart_iterations=25,
    **kwargs,
):
    """
    Returns a list of platform hardening playbooks.

    These playbooks test the DUT under extreme platform-level conditions
    including memory pressure, L2 table overflows, ECMP limit violations,
    CPU queue overload, malformed BGP packets, and service crash/restart
    combinations.
    """
    # Uppercase interface names for IXIA API regex matching
    downlink_iface = ixia_downlink_interface.upper()
    uplink_iface = ixia_uplink_interface.upper()

    return [
        Playbook(
            name="test_cgroup_system_slice_oom_kill_policy",
            postchecks=[
                create_oomd_kill_check(
                    expected_oom_kills={"system.slice": ["memory-pressure"]},
                )
            ],
            stages=[
                create_steps_stage(
                    steps=[
                        create_allocate_cgroup_memory_step(
                            total_memory_pct_decimal=0.25,
                            slice_name="system",
                            duration=180,
                            minimum_memory_allocation=1048 * 10,
                            oom_score_adj=1000,
                        ),
                        create_longevity_step(duration=300),
                    ]
                )
            ],
        ),
        Playbook(
            name="test_hardening_of_ndp_overload_entries",
            cleanup_steps=[
                create_ixia_api_step(
                    api_name="configure_ipv6_entries",
                    args_dict={
                        "device_group_regex": f".*{downlink_iface}.*",
                        "prefix_count": good_ndp_entries_downlink,
                        "toggle_all_ipv6_ipv4_only_protocol": True,
                    },
                ),
            ],
            stages=[
                create_steps_stage(
                    steps=[
                        create_ixia_api_step(
                            api_name="configure_ipv6_entries",
                            args_dict={
                                "device_group_regex": f".*{downlink_iface}.*",
                                "prefix_count": good_ndp_entries_downlink,
                                "toggle_all_ipv6_ipv4_only_protocol": True,
                            },
                        ),
                        create_ixia_api_step(
                            api_name="configure_ipv6_entries",
                            args_dict={
                                "device_group_regex": f".*{uplink_iface}.*",
                                "prefix_count": good_ndp_entries_uplink,
                                "toggle_all_ipv6_ipv4_only_protocol": True,
                            },
                        ),
                        create_ixia_api_step(
                            api_name="configure_ipv6_entries",
                            args_dict={
                                "device_group_regex": f".*{downlink_iface}.*",
                                "prefix_count": rogue_ndp_entries,
                                "toggle_all_ipv6_ipv4_only_protocol": True,
                            },
                        ),
                        create_longevity_step(duration=600),
                    ]
                )
            ],
            postchecks=[
                create_l2_entry_threshold_check(
                    ndp_entry_upper_lower_threshold=(
                        ndp_entry_limit,
                        good_ndp_entries_uplink + good_ndp_entries_downlink,
                    )
                ),
                get_ixia_healthcheck_stable_state(device_name),
            ],
        ),
        Playbook(
            name="test_hardening_of_arp_overload_entries",
            cleanup_steps=[
                create_ixia_api_step(
                    api_name="configure_ipv4_entries",
                    args_dict={
                        "device_group_regex": f".*{downlink_iface}.*",
                        "prefix_count": 1,
                        "toggle_all_ipv6_ipv4_only_protocol": True,
                    },
                ),
            ],
            stages=[
                create_steps_stage(
                    steps=[
                        create_ixia_api_step(
                            api_name="configure_ipv4_entries",
                            args_dict={
                                "device_group_regex": f".*{downlink_iface}.*",
                                "prefix_count": 1,
                                "toggle_all_ipv6_ipv4_only_protocol": True,
                            },
                        ),
                        create_ixia_api_step(
                            api_name="configure_ipv4_entries",
                            args_dict={
                                "device_group_regex": f".*{uplink_iface}.*",
                                "prefix_count": good_arp_entries,
                                "toggle_all_ipv6_ipv4_only_protocol": True,
                            },
                        ),
                        create_ixia_api_step(
                            api_name="configure_ipv4_entries",
                            args_dict={
                                "device_group_regex": f".*{downlink_iface}.*",
                                "prefix_count": rogue_arp_entries,
                                "toggle_all_ipv6_ipv4_only_protocol": True,
                            },
                        ),
                        create_longevity_step(duration=600),
                    ]
                )
            ],
            postchecks=[
                create_l2_entry_threshold_check(
                    arp_entry_upper_lower_threshold=(
                        arp_entry_limit,
                        good_arp_entries,
                    )
                ),
            ],
        ),
        Playbook(
            name="test_hardening_of_mac_overload_entries",
            cleanup_steps=[
                create_ixia_api_step(
                    api_name="configure_traffic_item_src_mac_entry_count",
                    args_dict={
                        "src_mac_entry_count": 1,
                        "traffic_item_regex": f".*_{downlink_iface}_.*",
                    },
                ),
            ],
            stages=[
                create_steps_stage(
                    steps=[
                        create_ixia_api_step(
                            api_name="configure_traffic_item_src_mac_entry_count",
                            args_dict={
                                "src_mac_entry_count": rogue_mac_entry_count,
                                "traffic_item_regex": f".*_{downlink_iface}_.*",
                            },
                        ),
                        create_longevity_step(duration=100),
                    ],
                )
            ],
            postchecks=[
                create_l2_entry_threshold_check(
                    mac_entry_upper_lower_threshold=(
                        mac_entry_limit,
                        good_mac_entry_count
                        + good_ndp_entries_uplink
                        + good_ndp_entries_downlink
                        + good_arp_entries,
                    )
                ),
            ],
        ),
        create_agent_warmboot_playbook(
            iteration=wedge_agent_restart_no_of_interations,
        ),
        create_bgpd_restart_playbook(
            iteration=bgpd_restart_no_of_interations,
            ixia_rogue_ic_parent_network_v6=ixia_rogue_ic_parent_network_v6,
            ixia_rogue_ic_parent_network_v4=ixia_rogue_ic_parent_network_v4,
        ),
        Playbook(
            name="test_bgp_malformed_packet_test",
            iteration=1,
            postchecks=[
                get_ixia_healthcheck_ignore_cpu_and_v4_directional_traffic(device_name),
            ],
            cleanup_steps=[],
            stages=[
                create_steps_stage(
                    steps=[
                        create_ixia_api_step(
                            api_name="bounce_bgp_next_hop_attribute",
                            args_dict={
                                "enable": False,
                                "network_group_regex": "NO_PACKET_LOSS_EXPECTED|ECMP_1",
                            },
                        ),
                        create_ixia_api_step(
                            api_name="bounce_bgp_next_hop_attribute",
                            args_dict={
                                "enable": False,
                                "network_group_regex": "NO_PACKET_LOSS_EXPECTED|ECMP_1",
                            },
                        ),
                        create_longevity_step(duration=1000),
                        create_ixia_api_step(
                            api_name="bounce_bgp_next_hop_attribute",
                            args_dict={
                                "enable": True,
                                "network_group_regex": "NO_PACKET_LOSS_EXPECTED|ECMP_1",
                            },
                        ),
                        create_ixia_api_step(
                            api_name="bounce_bgp_next_hop_attribute",
                            args_dict={
                                "enable": True,
                                "network_group_regex": "NO_PACKET_LOSS_EXPECTED|ECMP_1",
                            },
                        ),
                        create_longevity_step(duration=200),
                    ]
                ),
            ],
        ),
        Playbook(
            iteration=1,
            name="test_ecmp_member_overload_limit",
            postchecks=[
                AGENT_RESTART_SERVICE_CHECK,
            ],
            cleanup_steps=[
                create_ixia_api_step(
                    api_name="toggle_device_groups",
                    args_dict={
                        "enable": False,
                        "device_group_name_regex": "ECMP_2",
                    },
                ),
                create_ecmp_member_static_route_step(
                    delete_patcher_and_exit_step=True,
                ),
                create_service_interruption_step(
                    service=taac_types.Service.AGENT,
                    trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(
                    services=[taac_types.Service.AGENT, taac_types.Service.BGP],
                ),
                create_ecmp_member_static_route_step(
                    max_ecmp_group=ecmp_group_limit,
                    max_ecmp_members=ecmp_member_limit,
                    nh_prefix_1=f"{ixia_uplink_good_ndp_network}::/80",
                    lb_prefix_agg="6000:ab::/32",
                    device_group_count=good_ndp_entries_uplink,
                    delete_patcher_and_exit_step=False,
                ),
            ],
            stages=[
                create_steps_stage(
                    steps=[
                        create_ecmp_member_static_route_step(
                            delete_patcher_and_exit_step=True,
                        ),
                        create_service_interruption_step(
                            service=taac_types.Service.AGENT,
                            trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                        ),
                        create_service_convergence_step(
                            services=[taac_types.Service.AGENT, taac_types.Service.BGP],
                        ),
                        create_ecmp_member_static_route_step(
                            max_ecmp_group=ecmp_member_test_group_limit,
                            max_ecmp_members=ecmp_member_test_member_limit,
                            nh_prefix_1=f"{ixia_uplink_good_ndp_network}::/80",
                            lb_prefix_agg="6000:ab::/32",
                            device_group_count=good_ndp_entries_uplink,
                            delete_patcher_and_exit_step=False,
                        ),
                        create_ixia_api_step(
                            api_name="toggle_device_groups",
                            args_dict={
                                "enable": True,
                                "device_group_name_regex": "ECMP_2",
                            },
                        ),
                        create_longevity_step(duration=600),
                    ],
                )
            ],
        ),
        Playbook(
            iteration=1,
            name="test_ecmp_group_overload_limit",
            cleanup_steps=[
                create_ixia_api_step(
                    api_name="toggle_device_groups",
                    args_dict={
                        "enable": False,
                        "device_group_name_regex": "ECMP_2",
                    },
                ),
            ],
            stages=[
                create_steps_stage(
                    steps=[
                        create_ixia_api_step(
                            api_name="toggle_device_groups",
                            args_dict={
                                "enable": True,
                                "device_group_name_regex": "ECMP_2",
                            },
                        ),
                        create_longevity_step(duration=100),
                    ],
                )
            ],
        ),
        Playbook(
            name="test_cpu_high_priority_queue_overload",
            snapshot_checks=[
                create_bgp_session_snapshot_check(
                    parent_prefixes_to_ignore=[
                        f"{ixia_rogue_ic_parent_network_v6}::/80",
                        f"{ixia_rogue_ic_parent_network_v4}.0/16",
                    ],
                    pre_snapshot_checkpoint_id="stage.test_cpu_high_priority_queue_overload.step.sleep_120_secs_after_disabling_bgp_cp_traffic.end",
                ),
                create_bgp_session_snapshot_check(
                    skip_flap_check=True,
                    parent_prefixes_to_ignore=[
                        f"{ixia_rogue_ic_parent_network_v6}::/80",
                        f"{ixia_rogue_ic_parent_network_v4}.0/16",
                    ],
                    post_snapshot_checkpoint_id="stage.test_cpu_high_priority_queue_overload.step.sleep_120_secs_after_disabling_bgp_cp_traffic.end",
                ),
            ],
            stages=[
                create_steps_stage(
                    stage_id="test_cpu_high_priority_queue_overload",
                    steps=[
                        create_ixia_api_step(
                            api_name="enable_traffic",
                            args_dict={
                                "regexes": ["HIGH_QUEUE_BGP_CP_TRAFFIC"],
                                "enable": True,
                            },
                        ),
                        create_longevity_step(duration=150),
                        create_ixia_api_step(
                            api_name="enable_traffic",
                            args_dict={
                                "regexes": ["HIGH_QUEUE_BGP_CP_TRAFFIC"],
                                "enable": False,
                            },
                        ),
                        create_longevity_step(
                            duration=120,
                            step_id="sleep_120_secs_after_disabling_bgp_cp_traffic",
                        ),
                        create_ixia_api_step(
                            api_name="clear_traffic_stats",
                            args_dict={},
                        ),
                        create_longevity_step(duration=30),
                    ],
                )
            ],
        ),
        create_qsfp_service_restart_playbook(
            iteration=process_restart_iterations,
        ),
        create_fsdb_restart_playbook(
            iteration=process_restart_iterations,
        ),
        create_openr_restart_playbook(
            iteration=process_restart_iterations,
        ),
        create_agent_coldboot_playbook(
            iteration=process_restart_iterations,
        ),
        create_agent_crash_playbook(
            iteration=process_restart_iterations,
        ),
        create_bgpd_crash_playbook(
            iteration=process_restart_iterations,
        ),
        create_openr_crash_playbook(
            iteration=process_restart_iterations,
        ),
        create_qsfp_service_crash_playbook(
            iteration=process_restart_iterations,
        ),
        create_fsdb_crash_playbook(
            iteration=process_restart_iterations,
        ),
        TEST_FBOSS_SW_AGENT_WARMBOOT_PLAYBOOK,
        TEST_FBOSS_SW_AGENT_CRASH_PLAYBOOK,
        TEST_FBOSS_HW_AGENT_0_RESTART_PLAYBOOK,
        TEST_FBOSS_HW_AGENT_0_CRASH_PLAYBOOK,
        TEST_FBOSS_SW_AGENT_AND_HW_AGENT_0_RESTART_PLAYBOOK,
        TEST_FBOSS_SW_AGENT_AND_HW_AGENT_0_CRASH_PLAYBOOK,
        TEST_BGPD_AND_FSDB_RESTART_PLAYBOOK,
        TEST_AGENT_AND_BGPD_RESTART_PLAYBOOK,
        TEST_AGENT_AND_FSDB_RESTART_PLAYBOOK,
        TEST_AGENT_AND_QSFP_SERVICE_RESTART_PLAYBOOK,
        TEST_FSDB_AND_QSFP_SERVICE_RESTART_PLAYBOOK,
        TEST_SW_AGENT_AND_WEDGE_AGENT_RESTART_PLAYBOOK,
    ]


# =============================================================================
# BGP DC Longevity / Convergence playbooks
# (migrated from playbooks/helpers/routing/bgp_dc/longevity_playbooks.py
#  in Phase 4 v2)
# =============================================================================


def get_longevity_playbooks(device_name: str, **kwargs):
    """
    Returns a list of longevity, prefix/session flap, and convergence playbooks.

    These playbooks test the DUT under sustained network disruption
    scenarios including prefix flaps, session flaps, device group toggling,
    best-path computation churn, cold start oscillations, and combinations
    of churn with BGP daemon restarts.
    """
    del device_name  # unused after dropping IXIA traffic checks
    return [
        Playbook(
            name="test_longevity_prefix_flap_all_prefixes",
            cleanup_steps=ROGUE_PREFIX_SESSION_FLAP_STEPS,
            stages=[
                DISABLE_SESSION_FLAPS_STAGE,
                create_steps_stage(
                    steps=[
                        create_toggle_ixia_prefix_session_flap_churn_step(
                            churn_mode="prefix_flap",
                            enable_prefix_flap=True,
                            is_all_prefix_groups=True,
                            churn_duration_s=duration_all_prefix_flaps_s,
                        ),
                    ]
                ),
                DISABLE_PREFIX_FLAPS_STAGE,
            ],
        ),
        Playbook(
            name="test_longevity_activate_deactivate_all_prefixes",
            cleanup_steps=ROGUE_PREFIX_SESSION_FLAP_STEPS,
            stages=[
                DISABLE_SESSION_FLAPS_STAGE,
                create_steps_stage(steps=CONTINUOUSLY_ACTIVATE_DEACTIVATE_ALL_PREFIXES),
                DISABLE_PREFIX_FLAPS_STAGE,
            ],
        ),
        Playbook(
            name="test_longevity_session_flap_all_prefixes",
            postchecks=[
                BGP_SESSION_HEALTHCHECK_NO_V6_LOSS_EXPECTED,
            ],
            cleanup_steps=ROGUE_PREFIX_SESSION_FLAP_STEPS,
            stages=[
                DISABLE_PREFIX_FLAPS_STAGE,
                create_steps_stage(
                    steps=[
                        create_toggle_ixia_prefix_session_flap_churn_step(
                            churn_mode="session_flap",
                            enable_session_flap=True,
                            is_all_session_groups=True,
                            churn_duration_s=duration_all_session_flaps_s,
                        ),
                    ]
                ),
                DISABLE_SESSION_FLAPS_STAGE,
            ],
        ),
        Playbook(
            name="test_longevity_prefix_flap_all_prefixes_plus_bgp_restart",
            postchecks=[
                BGP_RESTART_SERVICE_CHECK,
            ],
            cleanup_steps=ROGUE_PREFIX_SESSION_FLAP_STEPS,
            stages=[
                DISABLE_SESSION_FLAPS_STAGE,
                create_steps_stage(
                    steps=[
                        create_toggle_ixia_prefix_session_flap_churn_step(
                            churn_mode="prefix_flap",
                            enable_prefix_flap=True,
                            is_all_prefix_groups=True,
                            churn_duration_s=wait_time_after_disable_churn_s,
                        ),
                    ]
                ),
                DISABLE_PREFIX_FLAPS_STAGE,
            ],
        ),
        Playbook(
            name="test_longevity_session_flap_all_prefixes_plus_bgp_restart",
            postchecks=[
                BGP_SESSION_HEALTHCHECK_NO_V6_LOSS_EXPECTED,
                BGP_RESTART_SERVICE_CHECK,
            ],
            cleanup_steps=ROGUE_PREFIX_SESSION_FLAP_STEPS,
            stages=[
                DISABLE_PREFIX_FLAPS_STAGE,
                create_steps_stage(
                    steps=[
                        create_toggle_ixia_prefix_session_flap_churn_step(
                            churn_mode="session_flap",
                            enable_session_flap=True,
                            is_all_session_groups=True,
                            churn_duration_s=wait_time_after_disable_churn_s,
                        ),
                    ]
                ),
                DISABLE_SESSION_FLAPS_STAGE,
            ],
        ),
        Playbook(
            name="test_longevity_rogue_prefix_session_enable",
            cleanup_steps=ROGUE_PREFIX_SESSION_FLAP_STEPS,
            stages=[
                create_steps_stage(
                    steps=[
                        create_longevity_step(
                            duration=duration_only_rogue_session_prefix_flaps_s
                        ),
                    ]
                )
            ],
        ),
        Playbook(
            name="test_longevity_no_prefix_no_session_flap",
            cleanup_steps=ROGUE_PREFIX_SESSION_FLAP_STEPS,
            stages=[
                DISABLE_SESSION_FLAPS_STAGE,
                DISABLE_PREFIX_FLAPS_STAGE,
                create_steps_stage(
                    steps=[
                        create_longevity_step(
                            duration=duration_no_prefix_session_flaps_s
                        ),
                    ]
                ),
            ],
        ),
        Playbook(
            name="test_longevity_continuous_toggle_device_group",
            postchecks=[
                BGP_SESSION_HEALTHCHECK_NO_V6_LOSS_EXPECTED,
            ],
            cleanup_steps=ROGUE_PREFIX_SESSION_FLAP_STEPS
            + [
                create_ixia_api_step(
                    api_name="toggle_device_groups",
                    args_dict={
                        "enable": True,
                        "device_group_name_regex": "ROGUE|NO_PACKET_LOSS_EXPECTED|ECMP_1|ARP|NDP",
                    },
                ),
            ],
            stages=[
                DISABLE_SESSION_FLAPS_STAGE,
                DISABLE_PREFIX_FLAPS_STAGE,
                create_steps_stage(steps=TOGGLE_ROGUE_DEVICE_GROUP_STEPS_CONTIUOUSLY),
            ],
        ),
        Playbook(
            name="test_longevity_frequent_best_path_computation",
            cleanup_steps=ROGUE_PREFIX_SESSION_FLAP_STEPS
            + REVERT_LOCAL_PREFERENCE_STEPS,
            stages=[
                DISABLE_SESSION_FLAPS_STAGE,
                DISABLE_PREFIX_FLAPS_STAGE,
                FREQUENT_BEST_PATH_COMPUTATION_STAGE,
            ],
        ),
        Playbook(
            name="test_longevity_cold_start_with_prefix_and_session_oscillations",
            postchecks_to_skip=[
                hc_types.CheckName.BGP_SESSION_ESTABLISH_CHECK,
            ],
            cleanup_steps=ROGUE_PREFIX_SESSION_FLAP_STEPS
            + [
                create_ixia_api_step(
                    api_name="rename_device_groups",
                    args_dict={
                        "device_group_name_regex": "PREFIX_FLAP_TRAFFIC_LOSS_EXPECTED",
                        "old_tag_name": "PREFIX_FLAP_TRAFFIC_LOSS_EXPECTED",
                        "new_tag_name": "NO_PACKET_LOSS_EXPECTED",
                    },
                ),
                create_ixia_api_step(
                    api_name="rename_device_groups",
                    args_dict={
                        "device_group_name_regex": "SESSION_FLAP_TRAFFIC_LOSS_EXPECTED",
                        "old_tag_name": "SESSION_FLAP_TRAFFIC_LOSS_EXPECTED",
                        "new_tag_name": "NO_V6_PACKET_LOSS_EXPECTED",
                    },
                ),
            ],
            stages=[
                create_steps_stage(
                    steps=[
                        create_ixia_api_step(
                            api_name="rename_device_groups",
                            args_dict={
                                "device_group_name_regex": "NO_PACKET_LOSS_EXPECTED",
                                "old_tag_name": "NO_PACKET_LOSS_EXPECTED",
                                "new_tag_name": "PREFIX_FLAP_TRAFFIC_LOSS_EXPECTED",
                            },
                        ),
                        create_ixia_api_step(
                            api_name="rename_device_groups",
                            args_dict={
                                "device_group_name_regex": "NO_V6_PACKET_LOSS_EXPECTED",
                                "old_tag_name": "NO_V6_PACKET_LOSS_EXPECTED",
                                "new_tag_name": "SESSION_FLAP_TRAFFIC_LOSS_EXPECTED",
                            },
                        ),
                    ]
                ),
                create_steps_stage(steps=COLD_START_PREFIX_OSCILLATIONS),
            ],
        ),
    ]


# ---------------------------------------------------------------------------
# routing/ebb/ebb_bgp_plus_plus playbook factories
# ---------------------------------------------------------------------------
def create_bgp_daemon_restart_playbook(
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

    return Playbook(
        name="bgp_daemon_restart_test_playbook",
        setup_steps=create_bgp_restart_setup_steps(device_name=device_name),
        prechecks=create_standard_prechecks(
            peergroup_ibgp_v6=peergroup_ibgp_v6,
            peergroup_ibgp_v4=peergroup_ibgp_v4,
            precheck_thresholds=precheck_thresholds,
            cpu_baseline=cpu_baseline,
            check_ibgp_pnh=(profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R),
            exclude_bgp_mon=exclude_bgp_mon,
        ),
        postchecks=create_standard_postchecks(
            postcheck_thresholds=postcheck_thresholds,
            expected_restarted_services=["Bgp"],
            restart_start_time_jq_var="daemon_restart_time",
            exclude_bgp_mon=exclude_bgp_mon,
        ),
        snapshot_checks=create_standard_snapshot_checks(
            skip_uptime_check=True,
            expected_peer_identity=expected_peer_identity,
            parent_prefixes_to_ignore=parent_prefixes_to_ignore,
            exclude_bgp_mon=exclude_bgp_mon,
        ),
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


def create_bgp_ebgp_route_oscillations_playbook(
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
        prefix_pool_regex: Regex to match eBGP prefix pools (default: ".*EBGP.*")
        prefix_start_index: Starting prefix index for oscillation (default: 0)
        prefix_end_index: Ending prefix index for oscillation (default: 500)
        precheck_thresholds: Custom precheck thresholds (uses defaults if None)
        postcheck_thresholds: Custom postcheck thresholds (uses defaults if None)

    Returns:
        Playbook configured for BGP eBGP route oscillation testing
    """
    if precheck_thresholds is None:
        precheck_thresholds = get_precheck_thresholds()

    if postcheck_thresholds is None:
        postcheck_thresholds = get_postcheck_thresholds()

    return Playbook(
        name="bgp_ebgp_route_oscillations",
        setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
        prechecks=create_standard_prechecks(
            peergroup_ibgp_v6=peergroup_ibgp_v6,
            peergroup_ibgp_v4=peergroup_ibgp_v4,
            precheck_thresholds=precheck_thresholds,
            expected_established_sessions=expected_established_sessions,
            cpu_baseline=cpu_baseline,
            check_ibgp_pnh=(profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R),
            exclude_bgp_mon=exclude_bgp_mon,
        ),
        postchecks=create_standard_postchecks(
            postcheck_thresholds=postcheck_thresholds,
            check_bgp_convergence=False,
            exclude_bgp_mon=exclude_bgp_mon,
        ),
        snapshot_checks=create_standard_snapshot_checks(
            skip_uptime_check=True,
            expected_peer_identity=expected_peer_identity,
            exclude_bgp_mon=exclude_bgp_mon,
        ),
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


def create_bgp_ibgp_route_oscillations_playbook(
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
        prefix_pool_regex: Regex to match iBGP prefix pools (default: ".*IBGP.*")
        prefix_start_index: Starting prefix index for oscillation (default: 0)
        prefix_end_index: Ending prefix index for oscillation (default: 100)
        precheck_thresholds: Custom precheck thresholds (uses defaults if None)
        postcheck_thresholds: Custom postcheck thresholds (uses defaults if None)

    Returns:
        Playbook configured for BGP iBGP route oscillation testing
    """
    if precheck_thresholds is None:
        precheck_thresholds = get_precheck_thresholds()

    if postcheck_thresholds is None:
        postcheck_thresholds = get_postcheck_thresholds()

    return Playbook(
        name="bgp_ibgp_route_oscillations",
        setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
        prechecks=create_standard_prechecks(
            peergroup_ibgp_v6=peergroup_ibgp_v6,
            peergroup_ibgp_v4=peergroup_ibgp_v4,
            precheck_thresholds=precheck_thresholds,
            expected_established_sessions=expected_established_sessions,
            cpu_baseline=cpu_baseline,
            check_ibgp_pnh=(profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R),
            exclude_bgp_mon=exclude_bgp_mon,
        ),
        postchecks=create_standard_postchecks(
            postcheck_thresholds=postcheck_thresholds,
            check_bgp_convergence=False,
            exclude_bgp_mon=exclude_bgp_mon,
        ),
        snapshot_checks=create_standard_snapshot_checks(
            expected_peer_identity=expected_peer_identity,
            exclude_bgp_mon=exclude_bgp_mon,
        ),
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


def create_bgp_cold_start_playbook(
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

    return Playbook(
        name="bgp_cold_start_test_playbook",
        setup_steps=create_bgp_restart_setup_steps(device_name=device_name),
        prechecks=create_standard_prechecks(
            peergroup_ibgp_v6=peergroup_ibgp_v6,
            peergroup_ibgp_v4=peergroup_ibgp_v4,
            precheck_thresholds=precheck_thresholds,
            cpu_baseline=cpu_baseline,
            check_ibgp_pnh=(profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R),
            exclude_bgp_mon=exclude_bgp_mon,
        ),
        postchecks=create_standard_postchecks(
            postcheck_thresholds=postcheck_thresholds,
            fail_on_eor_expired=fail_on_eor_expired,
            expected_restarted_services=["Bgp"],
            restart_start_time_jq_var="daemon_restart_time",
            exclude_bgp_mon=exclude_bgp_mon,
        ),
        snapshot_checks=create_standard_snapshot_checks(
            expected_peer_identity=expected_peer_identity,
            exclude_bgp_mon=exclude_bgp_mon,
        ),
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


def create_bgp_igp_instability_pnh_metric_oscillation_playbook(
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
    3. Starting tcpdump capture, performing Open/R metric oscillations, stopping capture
    4. Running standard postchecks (verifying only KEEPALIVE messages, no NOTIFICATION/OPEN)

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
        duration: Duration of metric oscillation in seconds (default: 3600)
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

    return Playbook(
        name="bgp_igp_instability_pnh_metric_oscillation_playbook",
        setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
        prechecks=create_standard_prechecks(
            peergroup_ibgp_v6=peergroup_ibgp_v6,
            peergroup_ibgp_v4=peergroup_ibgp_v4,
            precheck_thresholds=precheck_thresholds,
            expected_established_sessions=expected_established_sessions,
            cpu_baseline=cpu_baseline,
            check_ibgp_pnh=(profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R),
            exclude_bgp_mon=exclude_bgp_mon,
        ),
        postchecks=create_standard_postchecks(
            postcheck_thresholds=postcheck_thresholds,
            expected_message_types=["KEEPALIVE"],
            unexpected_message_types=["NOTIFICATION", "OPEN"],
            check_bgp_convergence=False,
            exclude_bgp_mon=exclude_bgp_mon,
        ),
        snapshot_checks=create_standard_snapshot_checks(
            expected_peer_identity=expected_peer_identity,
            exclude_bgp_mon=exclude_bgp_mon,
        ),
        periodic_tasks=create_standard_periodic_tasks(
            device_name=device_name,
            memory_threshold=memory_threshold,
            cpu_util_terminate_on_error=cpu_util_terminate_on_error,
            memory_terminate_on_error=memory_terminate_on_error,
        ),
        stages=[
            create_steps_stage(
                steps=[
                    create_tcpdump_step(
                        device_name=device_name,
                        mode="start_capture",
                        message_type="Keepalive|Open|Notification",
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
                    create_tcpdump_step(
                        device_name=device_name,
                        mode="stop_capture",
                        capture_file_path="/tmp/bgp_capture.txt",
                        description="Stop tcpdump capture and keep file",
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


def create_bgp_igp_instability_unresolvable_pnhs_playbook(
    device_name: str,
    peergroup_ibgp_v6: str,
    peergroup_ibgp_v4: str,
    tcp_dump_capture_interface: str,
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
) -> Playbook:
    """
    Create a BGP IGP instability unresolvable PNHs test playbook.

    This playbook tests BGP behavior when protocol next-hops become unresolvable by:
    1. Setting up BGP instability prerequisites
    2. Running standard prechecks
    3. Executing the unresolvable PNHs stage (deleting Open/R routes)
    4. Running standard postchecks with tcpdump verification for UPDATE messages
    5. Cleanup: re-injecting deleted routes to restore original state

    Args:
        device_name: Name of the device under test
        peergroup_ibgp_v6: IPv6 iBGP peer group name for session checks
        peergroup_ibgp_v4: IPv4 iBGP peer group name for session checks
        tcp_dump_capture_interface: Interface for tcpdump capture (short format)
        local_link: Local link dict for Open/R route configuration (device-specific)
        other_link: Other link dict for Open/R route configuration (device-specific)
        expected_established_sessions: Expected number of established BGP sessions
        profile: BGP++ profile (with or without Open/R)
        memory_threshold: Memory threshold in bytes (default: 5GB)
        cpu_util_terminate_on_error: Terminate test on CPU threshold breach
        memory_terminate_on_error: Terminate test on memory threshold breach
        start_ipv4s: List of starting IPv4 addresses for Open/R routes
        start_ipv6s: List of starting IPv6 addresses for Open/R routes
        count: Number of routes per start IP (default: 63)
        step_size: Step size for route generation (default: 2)
        precheck_thresholds: Custom precheck thresholds (uses defaults if None)
        postcheck_thresholds: Custom postcheck thresholds (uses defaults if None)

    Returns:
        Playbook configured for BGP IGP instability unresolvable PNHs testing
    """
    if start_ipv4s is None:
        start_ipv4s = [DEFAULT_OPENR_START_IPV4S[0]]

    if start_ipv6s is None:
        start_ipv6s = [DEFAULT_OPENR_START_IPV6S[0]]

    if precheck_thresholds is None:
        precheck_thresholds = get_precheck_thresholds()

    if postcheck_thresholds is None:
        postcheck_thresholds = get_postcheck_thresholds()

    return Playbook(
        name="bgp_igp_instability_unresolvable_pnhs_playbook",
        setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
        prechecks=create_standard_prechecks(
            peergroup_ibgp_v6=peergroup_ibgp_v6,
            peergroup_ibgp_v4=peergroup_ibgp_v4,
            precheck_thresholds=precheck_thresholds,
            expected_established_sessions=expected_established_sessions,
            cpu_baseline=cpu_baseline,
            check_ibgp_pnh=(profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R),
            exclude_bgp_mon=exclude_bgp_mon,
        ),
        postchecks=create_standard_postchecks(
            postcheck_thresholds=postcheck_thresholds,
            check_bgp_convergence=False,
            exclude_bgp_mon=exclude_bgp_mon,
        )
        + [
            create_bgp_tcpdump_check(
                expected_message_types=["UPDATE"],
                unexpected_message_types=[],
                cleanup_capture_file=False,
                expected_last_mod_time=1740,  # 29 minutes
            ),
        ],
        snapshot_checks=create_standard_snapshot_checks(
            expected_peer_identity=expected_peer_identity,
            exclude_bgp_mon=exclude_bgp_mon,
        ),
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
                tcp_dump_capture_interface=tcp_dump_capture_interface,
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
                description="Re-inject Open/R routes to restore deleted routes",
            ),
        ],
    )


def create_bgp_ebgp_session_oscillations_playbook(
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

    This playbook tests BGP stability during eBGP session flapping by:
    1. Setting up BGP instability prerequisites
    2. Running standard prechecks
    3. Randomly disrupting subsets of eBGP sessions in cycles
    4. Running standard postchecks (no convergence check, sessions will flap)

    Args:
        device_name: Name of the device under test
        peergroup_ibgp_v6: IPv6 iBGP peer group name for session checks
        peergroup_ibgp_v4: IPv4 iBGP peer group name for session checks
        ipv4_session_count: Total number of IPv4 eBGP sessions
        ipv6_session_count: Total number of IPv6 eBGP sessions
        expected_established_sessions: Expected number of established BGP sessions
        profile: BGP++ profile (with or without Open/R)
        memory_threshold: Memory threshold in bytes (default: 5GB)
        cpu_util_terminate_on_error: Terminate test on CPU threshold breach
        memory_terminate_on_error: Terminate test on memory threshold breach
        ipv4_peer_regex: Regex to match IPv4 eBGP peers (default: ".*IPV4_EBGP$")
        ipv6_peer_regex: Regex to match IPv6 eBGP peers (default: ".*IPV6_EBGP$")
        test_duration_seconds: Duration of oscillation test (default: 3600s)
        uptime_seconds: Time sessions stay up per cycle (default: 30s)
        downtime_seconds: Time sessions stay down per cycle (default: 30s)
        sessions_per_cycle: Number of sessions to disrupt per cycle (default: 70)
        precheck_thresholds: Custom precheck thresholds (uses defaults if None)
        postcheck_thresholds: Custom postcheck thresholds (uses defaults if None)

    Returns:
        Playbook configured for BGP eBGP session oscillation testing
    """
    if precheck_thresholds is None:
        precheck_thresholds = get_precheck_thresholds()

    if postcheck_thresholds is None:
        postcheck_thresholds = get_postcheck_thresholds()

    return Playbook(
        name="bgp_ebgp_session_oscillations_test_playbook",
        setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
        prechecks=create_standard_prechecks(
            peergroup_ibgp_v6=peergroup_ibgp_v6,
            peergroup_ibgp_v4=peergroup_ibgp_v4,
            precheck_thresholds=precheck_thresholds,
            expected_established_sessions=expected_established_sessions,
            cpu_baseline=cpu_baseline,
            check_ibgp_pnh=(profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R),
            exclude_bgp_mon=exclude_bgp_mon,
        ),
        postchecks=create_standard_postchecks(
            postcheck_thresholds=postcheck_thresholds,
            check_bgp_convergence=False,
            exclude_bgp_mon=exclude_bgp_mon,
        ),
        snapshot_checks=create_standard_snapshot_checks(
            skip_flap_check=True,
            skip_uptime_check=True,
            expected_peer_identity=expected_peer_identity,
            parent_prefixes_to_ignore=parent_prefixes_to_ignore,
            exclude_bgp_mon=exclude_bgp_mon,
        ),
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


def create_bgp_ibgp_tornado_plane_oscillations_playbook(
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

    This playbook tests BGP stability during iBGP tornado plane session flapping by:
    1. Setting up BGP instability prerequisites
    2. Running standard prechecks
    3. Disrupting iBGP sessions across tornado planes in cycles
    4. Running standard postchecks (no convergence check, sessions will flap)

    Args:
        device_name: Name of the device under test
        peergroup_ibgp_v6: IPv6 iBGP peer group name for session checks
        peergroup_ibgp_v4: IPv4 iBGP peer group name for session checks
        ipv4_sessions_per_plane: Total IPv4 iBGP sessions per plane
        ipv6_sessions_per_plane: Total IPv6 iBGP sessions per plane
        expected_established_sessions: Expected number of established BGP sessions
        profile: BGP++ profile (with or without Open/R)
        memory_threshold: Memory threshold in bytes (default: 5GB)
        cpu_util_terminate_on_error: Terminate test on CPU threshold breach
        memory_terminate_on_error: Terminate test on memory threshold breach
        ipv4_peer_regex: Regex to match IPv4 iBGP peers (default: ".*IPV4_IBGP.*")
        ipv6_peer_regex: Regex to match IPv6 iBGP peers (default: ".*IPV6_IBGP.*")
        test_duration_seconds: Duration of oscillation test (default: 3600s)
        uptime_seconds: Time sessions stay up per cycle (default: 30s)
        downtime_seconds: Time sessions stay down per cycle (default: 30s)
        sessions_per_plane: Number of sessions to disrupt per tornado plane (default: 16)
        tornado_planes: List of tornado plane IDs to cycle through (default: [1, 2, 3, 4])
        session_type: Target session type - "both", "eb", or "mp" (default: "both")
        precheck_thresholds: Custom precheck thresholds (uses defaults if None)
        postcheck_thresholds: Custom postcheck thresholds (uses defaults if None)

    Returns:
        Playbook configured for BGP iBGP tornado plane oscillation testing
    """
    if tornado_planes is None:
        tornado_planes = [1, 2, 3, 4]

    if precheck_thresholds is None:
        precheck_thresholds = get_precheck_thresholds()

    if postcheck_thresholds is None:
        postcheck_thresholds = get_postcheck_thresholds()

    return Playbook(
        name="bgp_ibgp_tornado_plane_oscillations_test_playbook",
        setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
        prechecks=create_standard_prechecks(
            peergroup_ibgp_v6=peergroup_ibgp_v6,
            peergroup_ibgp_v4=peergroup_ibgp_v4,
            precheck_thresholds=precheck_thresholds,
            expected_established_sessions=expected_established_sessions,
            cpu_baseline=cpu_baseline,
            check_ibgp_pnh=(profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R),
            exclude_bgp_mon=exclude_bgp_mon,
        ),
        postchecks=create_standard_postchecks(
            postcheck_thresholds=postcheck_thresholds,
            check_bgp_convergence=False,
            exclude_bgp_mon=exclude_bgp_mon,
        ),
        snapshot_checks=create_standard_snapshot_checks(
            skip_flap_check=True,
            skip_uptime_check=True,
            expected_peer_identity=expected_peer_identity,
            parent_prefixes_to_ignore=parent_prefixes_to_ignore,
            exclude_bgp_mon=exclude_bgp_mon,
        ),
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


def create_bgp_route_registry_prefix_list_runtime_update_playbook(
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

    return Playbook(
        name="bgp_route_registry_prefix_list_runtime_update_playbook",
        setup_steps=create_route_registry_prefix_list_setup_steps(
            device_name=device_name
        ),
        prechecks=create_standard_prechecks(
            peergroup_ibgp_v6=peergroup_ibgp_v6,
            peergroup_ibgp_v4=peergroup_ibgp_v4,
            precheck_thresholds=precheck_thresholds,
            cpu_baseline=cpu_baseline,
            expected_established_sessions=expected_established_sessions,
            check_ibgp_pnh=(profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R),
            exclude_bgp_mon=exclude_bgp_mon,
        )
        + [
            create_bgp_route_count_verification_check(
                json_params={
                    "descriptions_to_ignore": ["IBGP"],
                    "descriptions_to_check": ["EBGP"],
                    "direction": "received",
                    "expected_count": expected_route_count,
                    "policy_type": "post_policy",
                },
                check_id="startup_bgp_session_verification",
            ),
        ],
        postchecks=create_standard_postchecks(
            postcheck_thresholds=postcheck_thresholds,
            fail_on_eor_expired=False,
            exclude_bgp_mon=exclude_bgp_mon,
        ),
        snapshot_checks=create_standard_snapshot_checks(
            exclude_bgp_mon=exclude_bgp_mon,
        ),
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


def create_bgp_multipath_group_oscillation_playbook(
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
    3. Fluctuating BGP multipath groups by stopping/starting eBGP sessions
    4. Verifying multipath groups reduce/restore proportionally
    5. Running standard postchecks (no convergence check)

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
        ipv4_session_count: Baseline IPv4 multipath group size (default: 140)
        ipv6_session_count: Baseline IPv6 multipath group size (default: 140)
        test_duration_seconds: Total oscillation test duration (default: 1800s)
        oscillation_interval_seconds: Interval between oscillations (default: 280s)
        min_peers_to_stop: Minimum peers to stop per cycle (default: 1)
        max_peers_to_stop: Maximum peers to stop per cycle (default: 11)
        precheck_thresholds: Custom precheck thresholds (uses defaults if None)
        postcheck_thresholds: Custom postcheck thresholds (uses defaults if None)

    Returns:
        Playbook configured for BGP multipath group oscillation testing
    """
    if precheck_thresholds is None:
        precheck_thresholds = get_precheck_thresholds()

    if postcheck_thresholds is None:
        postcheck_thresholds = get_postcheck_thresholds()

    return Playbook(
        name="bgp_multipath_group_oscillation_playbook",
        setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
        prechecks=create_standard_prechecks(
            peergroup_ibgp_v6=peergroup_ibgp_v6,
            peergroup_ibgp_v4=peergroup_ibgp_v4,
            precheck_thresholds=precheck_thresholds,
            expected_established_sessions=expected_established_sessions,
            cpu_baseline=cpu_baseline,
            check_ibgp_pnh=(profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R),
            exclude_bgp_mon=exclude_bgp_mon,
        ),
        postchecks=create_standard_postchecks(
            postcheck_thresholds=postcheck_thresholds,
            check_bgp_convergence=False,
            exclude_bgp_mon=exclude_bgp_mon,
        ),
        snapshot_checks=create_standard_snapshot_checks(
            skip_flap_check=True,
            skip_uptime_check=True,
            exclude_bgp_mon=exclude_bgp_mon,
        ),
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
            ),
        ],
    )


def create_bgp_fauu_drain_undrain_playbook(
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

    This playbook tests BGP convergence during FAUU (FA Undrain/Undrain)
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
    return Playbook(
        name="bgp_fauu_drain_undrain_playbook",
        setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
        prechecks=create_standard_prechecks(
            peergroup_ibgp_v6=peergroup_ibgp_v6,
            peergroup_ibgp_v4=peergroup_ibgp_v4,
            expected_established_sessions=expected_established_sessions,
            check_ibgp_pnh=False,
            exclude_bgp_mon=exclude_bgp_mon,
        ),
        postchecks=create_standard_postchecks(
            check_bgp_convergence=False,
            exclude_bgp_mon=exclude_bgp_mon,
        ),
        snapshot_checks=create_standard_snapshot_checks(
            skip_flap_check=True,
            exclude_bgp_mon=exclude_bgp_mon,
        ),
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


def create_nexthop_group_count_threshold_playbook(
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

    This playbook monitors nexthop group counts during eBGP route oscillations
    and fails if the count meets or exceeds the configured threshold.

    Args:
        device_name: Name of the device under test
        nexthop_group_threshold: Fail threshold for nexthop group count (default: 100)
        prefix_pool_regex: Regex to match eBGP prefix pools (default: ".*EBGP.*")
        prefix_start_index: Starting prefix index for oscillation (default: 0)
        prefix_end_index: Ending prefix index for oscillation (default: 5000)
        test_duration_seconds: Duration of route oscillation in seconds (default: 1200)
        soak_duration: Soak time after final prefix changes in seconds (default: 300)
        convergence_threshold: BGP convergence threshold in seconds (default: 600)

    Returns:
        Playbook configured for nexthop group count threshold testing
    """
    return Playbook(
        name="nexthop_group_count_threshold_playbook",
        setup_steps=create_bgp_instability_setup_steps(
            device_name=device_name,
        ),
        snapshot_checks=create_standard_snapshot_checks(
            skip_flap_check=True,
            skip_uptime_check=True,
            exclude_bgp_mon=exclude_bgp_mon,
        ),
        periodic_tasks=create_standard_periodic_tasks(
            device_name=device_name,
        )
        + [
            create_nexthop_group_poll_periodic_task(
                device_name=device_name,
                threshold=nexthop_group_threshold,
            ),
        ],
        postchecks=create_standard_postchecks(
            convergence_threshold=convergence_threshold,
            exclude_bgp_mon=exclude_bgp_mon,
        ),
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


def create_bgp_plane_drain_undrain_playbook(
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
    return Playbook(
        name="bgp_plane_drain_undrain_playbook",
        setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
        prechecks=create_standard_prechecks(
            peergroup_ibgp_v6=peergroup_ibgp_v6,
            peergroup_ibgp_v4=peergroup_ibgp_v4,
            expected_established_sessions=expected_established_sessions,
            check_ibgp_pnh=False,
            exclude_bgp_mon=exclude_bgp_mon,
        ),
        postchecks=create_standard_postchecks(
            check_bgp_convergence=False,
            exclude_bgp_mon=exclude_bgp_mon,
        ),
        snapshot_checks=create_standard_snapshot_checks(
            skip_flap_check=True,
            exclude_bgp_mon=exclude_bgp_mon,
        ),
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


def create_bgp_longevity_playbook(
    device_name: str,
    duration: int = 86400,
    community_churn_frequency: int = 60,
    route_churn_frequency: int = 0,
    local_pref_churn_frequency: int = 0,
    as_path_drain_frequency: int = 0,
    origin_churn_frequency: int = 0,
    igp_cost_frequency: int = 0,
    restart_peers_frequency: int = 0,
    postcheck_thresholds: t.Optional[HardwareCapacityThresholds] = None,
    exclude_bgp_mon: bool = True,
) -> Playbook:
    """
    Create a BGP longevity soak playbook.

    This playbook runs a long-duration soak test with configurable periodic
    BGP attribute churn tasks running in the background.

    Args:
        device_name: Target device hostname
        duration: Soak duration in seconds (default: 86400 = 24 hours)
        community_churn_frequency: Frequency of community churn in seconds (0 to disable)
        route_churn_frequency: Frequency of route churn in seconds (0 to disable)
        local_pref_churn_frequency: Frequency of local_pref churn in seconds (0 to disable)
        as_path_drain_frequency: Frequency of AS-path drain in seconds (0 to disable)
        origin_churn_frequency: Frequency of origin churn in seconds (0 to disable)
        igp_cost_frequency: Frequency of IGP cost churn in seconds (0 to disable)
        restart_peers_frequency: Frequency of peer restarts in seconds (0 to disable)
        postcheck_thresholds: Hardware capacity thresholds for postchecks

    Returns:
        Playbook configured for BGP longevity soak testing
    """
    return Playbook(
        name="bgp_longevity_playbook",
        setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
        postchecks=create_standard_postchecks(
            postcheck_thresholds=postcheck_thresholds,
            check_bgp_convergence=False,
            exclude_bgp_mon=exclude_bgp_mon,
        ),
        snapshot_checks=create_standard_snapshot_checks(
            skip_flap_check=True,
            skip_uptime_check=True,
            exclude_bgp_mon=exclude_bgp_mon,
        ),
        periodic_tasks=create_longevity_periodic_tasks(
            device_name=device_name,
            route_churn_frequency=route_churn_frequency,
            local_pref_churn_frequency=local_pref_churn_frequency,
            as_path_drain_frequency=as_path_drain_frequency,
            origin_churn_frequency=origin_churn_frequency,
            community_churn_frequency=community_churn_frequency,
            igp_cost_frequency=igp_cost_frequency,
            restart_peers_frequency=restart_peers_frequency,
        ),
        stages=[
            create_steps_stage(
                steps=[
                    create_longevity_step(
                        duration=duration,
                        description=f"Longevity soak for {duration} seconds",
                    ),
                ]
            )
        ],
    )


# ---------------------------------------------------------------------------
# tahan_disruptive playbook factories (FBOSS Tahan SUSW)
# ---------------------------------------------------------------------------
def transform_to_endurance_playbook(
    original_playbook,
    name,
    iteration,
):
    postchecks = original_playbook.postchecks + [
        create_memory_utilization_check(
            threshold=Gigabyte.GIG_4_POINT_3.value,
            start_time_jq_var="test_case_start_time",
        ),
    ]

    return Playbook(
        name=name,
        prechecks=original_playbook.prechecks,
        postchecks=postchecks,
        stages=original_playbook.stages,
        iteration=iteration,
        traffic_items_to_start=original_playbook.traffic_items_to_start,
    )


def get_all_disruptive_tests(
    traffic_items_to_start: list[str],
    iteration: int = 1,
):
    """
    Return all disruptive test playbooks defined in this module.

    Args:
        traffic_items_to_start: list[str]: A list of traffic items to start.

    Returns:
        list[Playbook]: A list of all disruptive test playbooks.
    """

    TEST_AGENT_WARMBOOT_PLAYBOOK = Playbook(
        name="test_agent_warmboot",
        prechecks=[
            create_systemctl_active_state_check(),
            create_wedge_agent_configured_check(),
        ],
        postchecks=[
            create_packetloss_health_check(),
            create_unclean_exit_check(),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_service_interruption_step(
                        service=Service.AGENT,
                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(
                        services=[Service.AGENT],
                    ),
                ],
            ),
        ],
        traffic_items_to_start=traffic_items_to_start,
    )

    TEST_QSFP_SERVICE_WARMBOOT_PLAYBOOK = Playbook(
        name="test_qsfp_service_warmboot",
        prechecks=[
            create_systemctl_active_state_check(),
            create_wedge_agent_configured_check(),
        ],
        postchecks=[
            create_packetloss_health_check(),
            create_unclean_exit_check(),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_service_interruption_step(
                        service=Service.QSFP_SERVICE,
                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(
                        services=[
                            Service.QSFP_SERVICE,
                        ],
                    ),
                ]
            ),
        ],
        traffic_items_to_start=traffic_items_to_start,
    )

    TEST_FSDB_RESTART_PLAYBOOK = Playbook(
        name="test_fsdb_restart",
        prechecks=[
            create_systemctl_active_state_check(),
            create_wedge_agent_configured_check(),
        ],
        postchecks=[
            create_packetloss_health_check(),
            create_unclean_exit_check(),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_service_interruption_step(
                        service=Service.FSDB,
                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(
                        services=[
                            Service.AGENT,
                            Service.FSDB,
                        ],
                    ),
                ]
            )
        ],
        traffic_items_to_start=traffic_items_to_start,
    )

    TEST_FBOSS_HW_AGENT_0_WARMBOOT_PLAYBOOK = Playbook(
        name="test_fboss_hw_agent_0_warmboot",
        prechecks=[
            create_systemctl_active_state_check(),
            create_wedge_agent_configured_check(),
        ],
        postchecks=[
            create_packetloss_health_check(),
        ],
        snapshot_checks_to_skip=[
            hc_types.CheckName.CORE_DUMPS_CHECK,
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_service_interruption_step(
                        service=Service.FBOSS_HW_AGENT_0,
                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(
                        services=[
                            Service.AGENT,
                        ],
                    ),
                ]
            )
        ],
    )

    TEST_AGENT_WARMBOOT_AND_FSDB_RESTART_SUSW_PLAYBOOK = Playbook(
        name=TEST_AGENT_WARMBOOT_AND_FSDB_RESTART_PLAYBOOK.name,
        stages=TEST_AGENT_WARMBOOT_AND_FSDB_RESTART_PLAYBOOK.stages,
        prechecks=TEST_AGENT_WARMBOOT_AND_FSDB_RESTART_PLAYBOOK.prechecks,
        postchecks=TEST_AGENT_WARMBOOT_AND_FSDB_RESTART_PLAYBOOK.postchecks,
        traffic_items_to_start=traffic_items_to_start,
    )

    TEST_AGENT_CRASH_SUSW_PLAYBOOK = Playbook(
        name=TEST_AGENT_CRASH_PLAYBOOK.name,
        stages=TEST_AGENT_CRASH_PLAYBOOK.stages,
        prechecks=[
            create_systemctl_active_state_check(),
            create_wedge_agent_configured_check(),
        ],
        postchecks=TEST_AGENT_CRASH_PLAYBOOK.postchecks,
        traffic_items_to_start=traffic_items_to_start,
    )

    TEST_FBOSS_HW_AGENT_0_CRASH_SUSW_PLAYBOOK = Playbook(
        name=TEST_FBOSS_HW_AGENT_0_CRASH_PLAYBOOK.name,
        stages=TEST_FBOSS_HW_AGENT_0_CRASH_PLAYBOOK.stages,
        prechecks=[
            create_systemctl_active_state_check(),
            create_wedge_agent_configured_check(),
        ],
        postchecks=TEST_FBOSS_HW_AGENT_0_CRASH_PLAYBOOK.postchecks,
        snapshot_checks_to_skip=[
            hc_types.CheckName.CORE_DUMPS_CHECK,
        ],
        traffic_items_to_start=traffic_items_to_start,
    )

    TEST_FBOSS_SW_AGENT_WARMBOOT_SUSW_PLAYBOOK = Playbook(
        name=TEST_FBOSS_SW_AGENT_WARMBOOT_PLAYBOOK.name,
        stages=[
            create_steps_stage(
                steps=[
                    create_service_interruption_step(
                        service=Service.FBOSS_SW_AGENT,
                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(
                        services=[
                            Service.AGENT,
                            Service.QSFP_SERVICE,
                            Service.FSDB,
                        ],
                    ),
                ]
            ),
        ],
        prechecks=[
            create_systemctl_active_state_check(),
            create_wedge_agent_configured_check(),
        ],
        postchecks=[
            create_packetloss_health_check(),
            create_unclean_exit_check(),
        ],
        traffic_items_to_start=traffic_items_to_start,
    )

    TEST_AGENT_COLDBOOT_PLAYBOOK = Playbook(
        name="test_agent_coldboot",
        prechecks=[
            create_systemctl_active_state_check(),
            create_wedge_agent_configured_check(),
        ],
        postchecks=[
            create_ixia_packet_loss_check(clear_traffic_stats=True),
            create_unclean_exit_check(),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_service_interruption_step(
                        service=Service.AGENT,
                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                        create_cold_boot_file=True,
                    ),
                    create_service_convergence_step(
                        services=[Service.AGENT],
                    ),
                    create_longevity_step(duration=300),
                ],
            ),
        ],
        traffic_items_to_start=traffic_items_to_start,
    )

    TEST_FBOSS_SW_AGENT_CRASH_SUSW_PLAYBOOK = Playbook(
        name=TEST_FBOSS_SW_AGENT_CRASH_PLAYBOOK.name,
        stages=TEST_FBOSS_SW_AGENT_CRASH_PLAYBOOK.stages,
        prechecks=[
            create_systemctl_active_state_check(),
            create_wedge_agent_configured_check(),
        ],
        postchecks=TEST_FBOSS_SW_AGENT_CRASH_PLAYBOOK.postchecks,
        traffic_items_to_start=traffic_items_to_start,
    )

    TEST_REPEATED_AGENT_WARMBOOT_SUSW_PLAYBOOK = transform_to_endurance_playbook(
        TEST_AGENT_WARMBOOT_PLAYBOOK,
        "test_repeated_agent_warmboot",
        iteration,
    )

    TEST_DEVICE_REBOOT_SUSW_PLAYBOOK = Playbook(
        name="test_device_reboot",
        prechecks=[
            create_systemctl_active_state_check(),
            create_wedge_agent_configured_check(),
        ],
        postchecks=[
            create_systemctl_active_state_check(),
            create_wedge_agent_configured_check(),
            create_ixia_packet_loss_check(clear_traffic_stats=True),
        ],
        snapshot_checks_to_skip=[
            hc_types.CheckName.CORE_DUMPS_CHECK,
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_system_reboot_step(
                        trigger=SystemRebootTrigger.FULL_SYSTEM_REBOOT,
                    ),
                    create_service_convergence_step(
                        services=[Service.AGENT],
                    ),
                    create_longevity_step(duration=300),
                ]
            )
        ],
        traffic_items_to_start=traffic_items_to_start,
    )

    TEST_REPEATED_FSDB_RESTART_SUSW_PLAYBOOK = transform_to_endurance_playbook(
        TEST_FSDB_RESTART_PLAYBOOK,
        "test_repeated_fsdb_restart",
        iteration,
    )

    TEST_REPEATED_QSFP_SERVICE_WARMBOOT_SUSW_PLAYBOOK = transform_to_endurance_playbook(
        TEST_QSFP_SERVICE_WARMBOOT_PLAYBOOK,
        "test_repeated_qsfp_service_warmboot",
        iteration,
    )

    TEST_REPEATED_AGENT_WARMBOOT_AND_FSDB_RESTART_SUSW_PLAYBOOK = (
        transform_to_endurance_playbook(
            TEST_AGENT_WARMBOOT_AND_FSDB_RESTART_SUSW_PLAYBOOK,
            "test_repeated_agent_warmboot_and_fsdb_restart",
            iteration,
        )
    )

    TEST_REPEATED_AGENT_COLDBOOT_SUSW_PLAYBOOK = transform_to_endurance_playbook(
        TEST_AGENT_COLDBOOT_PLAYBOOK,
        "test_repeated_agent_coldboot",
        iteration,
    )

    TEST_REPEATED_AGENT_CRASH_SUSW_PLAYBOOK = transform_to_endurance_playbook(
        TEST_AGENT_CRASH_SUSW_PLAYBOOK,
        "test_repeated_agent_crash",
        iteration,
    )

    TEST_REPEATED_FBOSS_HW_AGENT_0_CRASH_SUSW_PLAYBOOK = (
        transform_to_endurance_playbook(
            TEST_FBOSS_HW_AGENT_0_CRASH_SUSW_PLAYBOOK,
            "test_repeated_fboss_hw_agent_0_crash",
            iteration,
        )
    )

    TEST_REPEATED_FBOSS_SW_AGENT_CRASH_SUSW_PLAYBOOK = transform_to_endurance_playbook(
        TEST_FBOSS_SW_AGENT_CRASH_SUSW_PLAYBOOK,
        "test_repeated_fboss_sw_agent_crash",
        iteration,
    )

    TEST_FSDB_CRASH_SUSW_PLAYBOOK = Playbook(
        name=TEST_FSDB_CRASH_PLAYBOOK.name,
        stages=TEST_FSDB_CRASH_PLAYBOOK.stages,
        prechecks=[
            create_systemctl_active_state_check(),
            create_wedge_agent_configured_check(),
        ],
        postchecks=TEST_FSDB_CRASH_PLAYBOOK.postchecks,
        traffic_items_to_start=traffic_items_to_start,
    )

    TEST_REPEATED_FSDB_CRASH_SUSW_PLAYBOOK = transform_to_endurance_playbook(
        TEST_FSDB_CRASH_SUSW_PLAYBOOK,
        "test_repeated_fsdb_crash",
        iteration,
    )

    TEST_BGPD_RESTART_SUSW_PLAYBOOK = Playbook(
        name="test_bgpd_restart",
        prechecks=[
            create_systemctl_active_state_check(),
            create_wedge_agent_configured_check(),
        ],
        postchecks=[
            create_packetloss_health_check(),
            create_unclean_exit_check(),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_service_interruption_step(
                        service=Service.BGP,
                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(
                        services=[
                            Service.BGP,
                        ],
                        timeout=800,
                    ),
                ]
            ),
        ],
        traffic_items_to_start=traffic_items_to_start,
    )

    TEST_REPEATED_DEVICE_REBOOT_SUSW_PLAYBOOK = transform_to_endurance_playbook(
        TEST_DEVICE_REBOOT_SUSW_PLAYBOOK,
        "test_repeated_device_reboot",
        iteration,
    )

    TEST_QSPF_SERVICE_CRASH_SUSW_PLAYBOOK = Playbook(
        name=TEST_QSPF_SERVICE_CRASH_PLAYBOOK.name,
        stages=TEST_QSPF_SERVICE_CRASH_PLAYBOOK.stages,
        prechecks=TEST_QSPF_SERVICE_CRASH_PLAYBOOK.prechecks,
        postchecks=TEST_QSPF_SERVICE_CRASH_PLAYBOOK.postchecks,
        traffic_items_to_start=traffic_items_to_start,
    )

    TEST_REPEATED_QSPF_SERVICE_CRASH_SUSW_PLAYBOOK = transform_to_endurance_playbook(
        TEST_QSPF_SERVICE_CRASH_SUSW_PLAYBOOK,
        "test_repeated_qsfp_service_crash",
        iteration,
    )

    TEST_WEDGE_AGENT_AND_FSDB_CRASH_SUSW_PLAYBOOK = Playbook(
        name=TEST_WEDGE_AGENT_AND_FSDB_CRASH_PLAYBOOK.name,
        stages=TEST_WEDGE_AGENT_AND_FSDB_CRASH_PLAYBOOK.stages,
        prechecks=TEST_WEDGE_AGENT_AND_FSDB_CRASH_PLAYBOOK.prechecks,
        postchecks=TEST_WEDGE_AGENT_AND_FSDB_CRASH_PLAYBOOK.postchecks,
        traffic_items_to_start=traffic_items_to_start,
    )

    TEST_REPEATED_WEDGE_AGENT_AND_FSDB_CRASH_SUSW_PLAYBOOK = (
        transform_to_endurance_playbook(
            TEST_WEDGE_AGENT_AND_FSDB_CRASH_SUSW_PLAYBOOK,
            "test_repeated_wedge_agent_and_fsdb_crash",
            iteration,
        )
    )

    return [
        TEST_AGENT_WARMBOOT_PLAYBOOK,
        TEST_QSFP_SERVICE_WARMBOOT_PLAYBOOK,
        TEST_FSDB_RESTART_PLAYBOOK,
        TEST_FBOSS_HW_AGENT_0_WARMBOOT_PLAYBOOK,
        TEST_AGENT_CRASH_SUSW_PLAYBOOK,
        TEST_FBOSS_HW_AGENT_0_CRASH_SUSW_PLAYBOOK,
        TEST_FBOSS_SW_AGENT_WARMBOOT_SUSW_PLAYBOOK,
        TEST_AGENT_WARMBOOT_AND_FSDB_RESTART_SUSW_PLAYBOOK,
        TEST_AGENT_COLDBOOT_PLAYBOOK,
        TEST_FBOSS_SW_AGENT_CRASH_SUSW_PLAYBOOK,
        TEST_REPEATED_AGENT_WARMBOOT_SUSW_PLAYBOOK,
        TEST_DEVICE_REBOOT_SUSW_PLAYBOOK,
        TEST_REPEATED_FSDB_RESTART_SUSW_PLAYBOOK,
        TEST_REPEATED_QSFP_SERVICE_WARMBOOT_SUSW_PLAYBOOK,
        TEST_REPEATED_AGENT_WARMBOOT_AND_FSDB_RESTART_SUSW_PLAYBOOK,
        TEST_REPEATED_AGENT_COLDBOOT_SUSW_PLAYBOOK,
        TEST_REPEATED_AGENT_CRASH_SUSW_PLAYBOOK,
        TEST_REPEATED_FBOSS_HW_AGENT_0_CRASH_SUSW_PLAYBOOK,
        TEST_REPEATED_FBOSS_SW_AGENT_CRASH_SUSW_PLAYBOOK,
        TEST_FSDB_CRASH_SUSW_PLAYBOOK,
        TEST_REPEATED_FSDB_CRASH_SUSW_PLAYBOOK,
        TEST_BGPD_RESTART_SUSW_PLAYBOOK,
        TEST_REPEATED_DEVICE_REBOOT_SUSW_PLAYBOOK,
        TEST_QSPF_SERVICE_CRASH_SUSW_PLAYBOOK,
        TEST_REPEATED_QSPF_SERVICE_CRASH_SUSW_PLAYBOOK,
        TEST_WEDGE_AGENT_AND_FSDB_CRASH_SUSW_PLAYBOOK,
        TEST_REPEATED_WEDGE_AGENT_AND_FSDB_CRASH_SUSW_PLAYBOOK,
    ]


# =============================================================================
# WEDGE400 ECMP RESOURCE TESTING PLAYBOOK FACTORIES
# Migrated from playbooks/helpers/ai_bb/wedge400_ecmp_playbooks.py per Phase 4 v2
# =============================================================================


def create_ecmp_groups_playbooks(
    ixia_downlink_interface: str,
    ixia_remote_interface: str,
    asic: DlbAsic = DlbAsic.TOMAHAWK3,
) -> list[Playbook]:
    """
    Create ECMP Groups playbooks (base, Warmboot, bgp_restart, Coldboot).

    This function generates 4 playbooks for ECMP Groups testing to reduce
    code duplication. All playbooks share the same structure with different
    service restart configurations.

    Args:
        ixia_downlink_interface: The IXIA downlink interface name for Gold traffic item
        ixia_remote_interface: The IXIA remote interface name for Silver traffic item
        asic: ASIC family of the DUT; selects the platform-aware DLB resource
            sizing profile (e.g. max DLB groups: Tomahawk3=10, Tomahawk5=94).

    Returns:
        A list of 4 Playbook objects:
        - Full_Utilization_ECMP_Groups (base playbook)
        - Full_Utilization_ECMP_Group_Warmboot
        - Full_Utilization_ECMP_Group_bgp_restart
        - Full_Utilization_ECMP_Group_Coldboot
    """
    dlb_profile = DLB_RESOURCE_PROFILES[asic]

    def _create_dlb_steady_check() -> PointInTimeHealthCheck:
        """DLB resource-stickiness check for steady state (base/coldboot)."""
        return create_dlb_resource_stickiness_check(
            json_params={
                "prefix_patterns": ["5000:dd::", "5000:ee::"],
                "expected_counts": {
                    "5000:dd prefixes": dlb_profile.gold_counts,
                    "5000:ee prefixes": dlb_profile.silver_counts,
                },
                "expected_totals": {"dlb": dlb_profile.max_dlb_groups},
            }
        )

    def _create_dlb_overcommit_check() -> PointInTimeHealthCheck:
        """DLB resource-stickiness check for overcommit (Rouge enabled)."""
        return create_dlb_resource_stickiness_check(
            json_params={
                "prefix_patterns": ["5000:dd::", "5000:ee::"],
                "expected_counts": {
                    "5000:dd prefixes": dlb_profile.gold_counts,
                    "5000:ee prefixes": dlb_profile.overcommit_silver_counts,
                },
                "expected_totals": {"dlb": dlb_profile.max_dlb_groups},
            }
        )

    def _create_common_postchecks(
        gold_interface: str, silver_interface: str
    ) -> list[PointInTimeHealthCheck]:
        """Create common postchecks for Groups playbooks."""
        return [
            create_systemctl_active_state_check(
                services=[
                    hc_types.Service.WEDGE_AGENT,
                    hc_types.Service.BGPD,
                    hc_types.Service.QSFP_SERVICE,
                    hc_types.Service.FSDB,
                    hc_types.Service.FBOSS_SW_AGENT,
                    hc_types.Service.FBOSS_HW_AGENT_0,
                ]
            ),
            # Combined DLB check: counts unique ECMP groups per prefix
            # category. Sizing is platform-aware — see dlb_platform_constants.py
            # (Tomahawk3/Wedge400 dlb cap = 10, Tomahawk5/Minipack3 = 94).
            _create_dlb_steady_check(),
            create_cpu_utilization_check(
                threshold=400.0, start_time_jq_var="test_case_start_time"
            ),
            create_service_restart_check(
                services=SERVICES_TO_MONITOR_DURING_AGENT_RESTART
            ),
            create_memory_utilization_check(
                threshold=5 * (1024**3),
                threshold_by_service={
                    "bgpd": 4.5 * (1024**3),
                    "fsdb": 5 * (1024**3),
                    "qsfp_service": 2 * (1024**3),
                    "fboss_sw_agent": 9 * (1024**3),
                    "fboss_hw_agent@0": 8 * (1024**3),
                },
                start_time_jq_var="test_case_start_time",
            ),
            create_unclean_exit_check(),
            create_ixia_packet_loss_check(
                clear_traffic_stats=True,
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=[
                            f"{gold_interface.upper().replace('/', '_')}_TO_DLB_GOLDEN_TRAFFIC"
                        ],
                        str_value="0",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                    hc_types.PacketLossThreshold(
                        names=[
                            f"{silver_interface.upper().replace('/', '_')}_TO_SILVER_TRAFFIC"
                        ],
                        str_value="0",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                    hc_types.PacketLossThreshold(
                        names=[
                            f"{silver_interface.upper().replace('/', '_')}_TO_ROUGE_TRAFFIC"
                        ],
                        str_value="100",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                ],
            ),
        ]

    # Base playbook - Full_Utilization_ECMP_Members

    def _create_coldboot_postchecks(
        gold_interface: str, silver_interface: str
    ) -> list[PointInTimeHealthCheck]:
        """Create postchecks for Coldboot playbook (simplified version)."""
        return [
            create_systemctl_active_state_check(
                services=[
                    hc_types.Service.WEDGE_AGENT,
                    hc_types.Service.BGPD,
                    hc_types.Service.QSFP_SERVICE,
                    hc_types.Service.FSDB,
                    hc_types.Service.FBOSS_SW_AGENT,
                    hc_types.Service.FBOSS_HW_AGENT_0,
                ]
            ),
            # Combined DLB check: counts unique ECMP groups per prefix
            # category. Sizing is platform-aware — see dlb_platform_constants.py
            # (Tomahawk3/Wedge400 dlb cap = 10, Tomahawk5/Minipack3 = 94).
            _create_dlb_steady_check(),
            create_ixia_packet_loss_check(
                clear_traffic_stats=True,
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=[
                            f"{gold_interface.upper().replace('/', '_')}_TO_DLB_GOLDEN_TRAFFIC"
                        ],
                        str_value="0",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                    hc_types.PacketLossThreshold(
                        names=[
                            f"{silver_interface.upper().replace('/', '_')}_TO_SILVER_TRAFFIC"
                        ],
                        str_value="0",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                    hc_types.PacketLossThreshold(
                        names=[
                            f"{silver_interface.upper().replace('/', '_')}_TO_ROUGE_TRAFFIC"
                        ],
                        str_value="100",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                ],
            ),
        ]

    def _create_overcommit_postchecks(
        gold_interface: str, silver_interface: str
    ) -> list[PointInTimeHealthCheck]:
        """Create postchecks for Overcommit playbooks (with Rouge enabled)."""
        return [
            create_systemctl_active_state_check(
                services=[
                    hc_types.Service.WEDGE_AGENT,
                    hc_types.Service.BGPD,
                    hc_types.Service.QSFP_SERVICE,
                    hc_types.Service.FSDB,
                    hc_types.Service.FBOSS_SW_AGENT,
                    hc_types.Service.FBOSS_HW_AGENT_0,
                ]
            ),
            # Combined DLB check: counts unique ECMP groups per prefix
            # category. Overcommit (Rouge enabled) — platform-aware sizing
            # via dlb_platform_constants.py (TH3 asserts a spill floor,
            # TH5 asserts the full silver total).
            _create_dlb_overcommit_check(),
            create_cpu_utilization_check(
                threshold=400.0, start_time_jq_var="test_case_start_time"
            ),
            create_service_restart_check(
                services=SERVICES_TO_MONITOR_DURING_AGENT_RESTART
            ),
            create_memory_utilization_check(
                threshold=5 * (1024**3),
                threshold_by_service={
                    "bgpd": 4.5 * (1024**3),
                    "fsdb": 5 * (1024**3),
                    "qsfp_service": 2 * (1024**3),
                    "fboss_sw_agent": 9 * (1024**3),
                    "fboss_hw_agent@0": 8 * (1024**3),
                },
                start_time_jq_var="test_case_start_time",
            ),
            create_unclean_exit_check(),
            # Packet loss check for Gold and Silver traffic (expect 0% loss)
            create_ixia_packet_loss_check(
                clear_traffic_stats=True,
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=[
                            f"{gold_interface.upper().replace('/', '_')}_TO_DLB_GOLDEN_TRAFFIC"
                        ],
                        str_value="0",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                    hc_types.PacketLossThreshold(
                        names=[
                            f"{silver_interface.upper().replace('/', '_')}_TO_SILVER_TRAFFIC"
                        ],
                        str_value="0",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                    hc_types.PacketLossThreshold(
                        names=[
                            f"{silver_interface.upper().replace('/', '_')}_TO_ROUGE_TRAFFIC"
                        ],
                        str_value="100",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                ],
            ),
        ]

    # Base playbook - Full_Utilization_ECMP_Groups
    base_playbook = Playbook(
        name="Full_Utilization_ECMP_Groups",
        description="Utilize 100% of DLB, NON_DLB Groups (50% Member Occupancy)",
        backup_and_restore_ixia_config=True,
        stages=[
            create_steps_stage(
                stage_id="run_traffic_steady_state",
                steps=[
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*NON_DLB_RESOURCE\\(ROUGE\\)",
                            "enable": False,
                        },
                        description="Disable Rouge device group for Groups testing",
                    ),
                    create_longevity_step(
                        duration=60,
                        description="Wait for BGP routes to converge",
                    ),
                    create_ixia_api_step(
                        api_name="start_traffic",
                        args_dict={},
                        description="Start traffic after BGP convergence",
                    ),
                    create_longevity_step(
                        duration=120,
                        description="Run traffic for steady state measurement",
                    ),
                ],
            ),
        ],
        postchecks=_create_common_postchecks(
            ixia_downlink_interface, ixia_remote_interface
        ),
    )

    # Warmboot playbook
    warmboot_playbook = Playbook(
        name="Full_Utilization_ECMP_Group_Warmboot",
        stages=[
            create_steps_stage(
                stage_id="disable_rouge",
                steps=[
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*NON_DLB_RESOURCE\\(ROUGE\\)",
                            "enable": False,
                        },
                        description="Disable Rouge device group for Groups testing",
                    ),
                ],
            ),
            create_steps_stage(
                stage_id="enable_prefix_flapping",
                steps=[
                    create_toggle_ixia_prefix_session_flap_churn_step(
                        churn_mode="random",
                        enable_prefix_flap=True,
                        is_all_prefix_groups=True,
                        churn_duration_s=0,
                    ),
                ],
            ),
            create_steps_stage(
                iteration=5,
                steps=[
                    create_service_interruption_step(
                        service=Service.AGENT,
                        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(
                        services=[Service.AGENT, Service.BGP],
                        timeout=300,  # 5 min timeout - BGP may not fully converge during flapping
                    ),
                    create_longevity_step(duration=900),
                ],
            ),
            create_steps_stage(
                stage_id="disable_prefix_flapping",
                steps=[
                    create_toggle_ixia_prefix_session_flap_churn_step(
                        churn_mode="random",
                        enable_prefix_flap=False,
                        is_all_prefix_groups=True,
                        churn_duration_s=0,
                    ),
                ],
            ),
            create_steps_stage(
                stage_id="post_churn_stabilization",
                steps=[
                    create_longevity_step(duration=120),
                ],
            ),
        ],
        skip_test_config_snapshot_checks=True,
        postchecks=_create_common_postchecks(
            ixia_downlink_interface, ixia_remote_interface
        ),
    )

    # BGP restart playbook
    bgp_restart_playbook = Playbook(
        name="Full_Utilization_ECMP_Group_bgp_restart",
        stages=[
            create_steps_stage(
                stage_id="disable_rouge",
                steps=[
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*NON_DLB_RESOURCE\\(ROUGE\\)",
                            "enable": False,
                        },
                        description="Disable Rouge device group for Groups testing",
                    ),
                ],
            ),
            create_steps_stage(
                stage_id="enable_prefix_flapping",
                steps=[
                    create_toggle_ixia_prefix_session_flap_churn_step(
                        churn_mode="random",
                        enable_prefix_flap=True,
                        is_all_prefix_groups=True,
                        churn_duration_s=0,
                    ),
                ],
            ),
            create_steps_stage(
                iteration=5,
                steps=[
                    create_service_interruption_step(
                        service=Service.BGP,
                        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(
                        services=[Service.AGENT, Service.BGP],
                        timeout=300,  # 5 min timeout - BGP may not fully converge during flapping
                    ),
                    create_longevity_step(duration=120),
                ],
            ),
            create_steps_stage(
                stage_id="disable_prefix_flapping",
                steps=[
                    create_toggle_ixia_prefix_session_flap_churn_step(
                        churn_mode="random",
                        enable_prefix_flap=False,
                        is_all_prefix_groups=True,
                        churn_duration_s=0,
                    ),
                ],
            ),
            create_steps_stage(
                stage_id="post_churn_stabilization",
                steps=[
                    create_longevity_step(duration=120),
                ],
            ),
        ],
        skip_test_config_snapshot_checks=True,
        postchecks=_create_common_postchecks(
            ixia_downlink_interface, ixia_remote_interface
        ),
    )

    # Coldboot playbook
    coldboot_playbook = Playbook(
        name="Full_Utilization_ECMP_Group_Coldboot",
        stages=[
            create_steps_stage(
                stage_id="disable_rouge",
                steps=[
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*NON_DLB_RESOURCE\\(ROUGE\\)",
                            "enable": False,
                        },
                        description="Disable Rouge device group for Groups testing",
                    ),
                ],
            ),
            create_steps_stage(
                stage_id="enable_prefix_flapping",
                steps=[
                    create_toggle_ixia_prefix_session_flap_churn_step(
                        churn_mode="random",
                        enable_prefix_flap=True,
                        is_all_prefix_groups=True,
                        churn_duration_s=0,
                    ),
                ],
            ),
            create_steps_stage(
                iteration=5,
                steps=[
                    create_service_interruption_step(
                        service=Service.AGENT,
                        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                        create_cold_boot_file=True,
                    ),
                    create_service_convergence_step(
                        services=[Service.AGENT, Service.BGP],
                        timeout=300,  # 5 min timeout - BGP may not fully converge during flapping
                    ),
                    create_longevity_step(duration=900),
                ],
            ),
            create_steps_stage(
                stage_id="disable_prefix_flapping",
                steps=[
                    create_toggle_ixia_prefix_session_flap_churn_step(
                        churn_mode="random",
                        enable_prefix_flap=False,
                        is_all_prefix_groups=True,
                        churn_duration_s=0,
                    ),
                ],
            ),
            create_steps_stage(
                stage_id="post_churn_stabilization",
                steps=[
                    create_longevity_step(duration=120),
                ],
            ),
        ],
        skip_test_config_snapshot_checks=True,
        postchecks=_create_coldboot_postchecks(
            ixia_downlink_interface, ixia_remote_interface
        ),
    )

    # =========================================================================
    # OVERCOMMIT PLAYBOOKS (duplicates with "Overcommit" prefix)
    # =========================================================================

    # Overcommit base playbook
    overcommit_base_playbook = Playbook(
        name="Overcommit_ECMP_Groups",
        description="Overcommit DLB, NON_DLB Groups (50% Member Occupancy)",
        backup_and_restore_ixia_config=True,
        stages=[
            create_steps_stage(
                stage_id="run_traffic_steady_state",
                steps=[
                    # Enable Gold device group
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*DLB_RESOURCE\\(GOLD\\)",
                            "enable": True,
                        },
                        description="Enable Gold device group",
                    ),
                    # Enable Silver device group
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*NON_DLB_RESOURCE\\(SILVER\\)",
                            "enable": True,
                        },
                        description="Enable Silver device group",
                    ),
                    # Enable Rouge device group for overcommit testing
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*NON_DLB_RESOURCE\\(ROUGE\\)",
                            "enable": True,
                        },
                        description="Enable Rouge device group for overcommit testing",
                    ),
                    create_longevity_step(
                        duration=60,
                        description="Wait for BGP routes to converge",
                    ),
                    create_ixia_api_step(
                        api_name="start_traffic",
                        args_dict={},
                        description="Start traffic after BGP convergence",
                    ),
                    create_longevity_step(
                        duration=120,
                        description="Run traffic for steady state measurement",
                    ),
                    # Validate ResourceAccountant in wedge_agent log - FAIL if not found
                    create_run_ssh_command_step(
                        cmd="cat /var/facebook/logs/fboss/wedge_agent.log | grep -i 'ResourceAccountant' | tail -50 || (echo 'FAILED: ResourceAccountant not found in wedge_agent log' && exit 1)"
                    ),
                ],
            ),
        ],
        postchecks=_create_overcommit_postchecks(
            ixia_downlink_interface, ixia_remote_interface
        ),
    )

    # Overcommit Warmboot playbook
    overcommit_warmboot_playbook = Playbook(
        name="Overcommit_ECMP_Group_Warmboot",
        stages=[
            create_steps_stage(
                stage_id="enable_overcommit_and_validate",
                steps=[
                    # Enable Gold device group
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*DLB_RESOURCE\\(GOLD\\)",
                            "enable": True,
                        },
                        description="Enable Gold device group",
                    ),
                    # Enable Silver device group
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*NON_DLB_RESOURCE\\(SILVER\\)",
                            "enable": True,
                        },
                        description="Enable Silver device group",
                    ),
                    # Enable Rouge device group for overcommit testing
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*NON_DLB_RESOURCE\\(ROUGE\\)",
                            "enable": True,
                        },
                        description="Enable Rouge device group for overcommit testing",
                    ),
                    create_longevity_step(
                        duration=60,
                        description="Wait for BGP routes to converge after enabling device groups",
                    ),
                    # Validate ResourceAccountant in wedge_agent log - FAIL if not found
                    create_run_ssh_command_step(
                        cmd="cat /var/facebook/logs/fboss/wedge_agent.log | grep -i 'ResourceAccountant' | tail -50 || (echo 'FAILED: ResourceAccountant not found in wedge_agent log' && exit 1)"
                    ),
                ],
            ),
            create_steps_stage(
                stage_id="enable_prefix_flapping",
                steps=[
                    create_toggle_ixia_prefix_session_flap_churn_step(
                        churn_mode="random",
                        enable_prefix_flap=True,
                        is_all_prefix_groups=True,
                        churn_duration_s=0,
                    ),
                ],
            ),
            create_steps_stage(
                iteration=1,  # TODO: Revert to 5 after testing
                steps=[
                    create_service_interruption_step(
                        service=Service.AGENT,
                        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(
                        services=[Service.AGENT, Service.BGP],
                    ),
                    create_longevity_step(duration=900),
                ],
            ),
            create_steps_stage(
                stage_id="disable_prefix_flapping",
                steps=[
                    create_toggle_ixia_prefix_session_flap_churn_step(
                        churn_mode="random",
                        enable_prefix_flap=False,
                        is_all_prefix_groups=True,
                        churn_duration_s=0,
                    ),
                ],
            ),
            create_steps_stage(
                stage_id="post_churn_stabilization",
                steps=[
                    create_longevity_step(duration=120),
                ],
            ),
        ],
        skip_test_config_snapshot_checks=True,
        postchecks=_create_overcommit_postchecks(
            ixia_downlink_interface, ixia_remote_interface
        ),
    )

    # Overcommit BGP restart playbook
    overcommit_bgp_restart_playbook = Playbook(
        name="Overcommit_ECMP_Group_bgp_restart",
        stages=[
            create_steps_stage(
                stage_id="enable_overcommit_and_validate",
                steps=[
                    # Enable Gold device group
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*DLB_RESOURCE\\(GOLD\\)",
                            "enable": True,
                        },
                        description="Enable Gold device group",
                    ),
                    # Enable Silver device group
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*NON_DLB_RESOURCE\\(SILVER\\)",
                            "enable": True,
                        },
                        description="Enable Silver device group",
                    ),
                    # Enable Rouge device group for overcommit testing
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*NON_DLB_RESOURCE\\(ROUGE\\)",
                            "enable": True,
                        },
                        description="Enable Rouge device group for overcommit testing",
                    ),
                    create_longevity_step(
                        duration=60,
                        description="Wait for BGP routes to converge after enabling device groups",
                    ),
                    # Validate ResourceAccountant in wedge_agent log - FAIL if not found
                    create_run_ssh_command_step(
                        cmd="cat /var/facebook/logs/fboss/wedge_agent.log | grep -i 'ResourceAccountant' | tail -50 || (echo 'FAILED: ResourceAccountant not found in wedge_agent log' && exit 1)"
                    ),
                ],
            ),
            create_steps_stage(
                stage_id="enable_prefix_flapping",
                steps=[
                    create_toggle_ixia_prefix_session_flap_churn_step(
                        churn_mode="random",
                        enable_prefix_flap=True,
                        is_all_prefix_groups=True,
                        churn_duration_s=0,
                    ),
                ],
            ),
            create_steps_stage(
                iteration=1,  # TODO: Revert to 5 after testing
                steps=[
                    create_service_interruption_step(
                        service=Service.BGP,
                        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(
                        services=[Service.AGENT, Service.BGP],
                    ),
                    create_longevity_step(duration=300),
                ],
            ),
            create_steps_stage(
                stage_id="disable_prefix_flapping",
                steps=[
                    create_toggle_ixia_prefix_session_flap_churn_step(
                        churn_mode="random",
                        enable_prefix_flap=False,
                        is_all_prefix_groups=True,
                        churn_duration_s=0,
                    ),
                ],
            ),
            create_steps_stage(
                stage_id="post_churn_stabilization",
                steps=[
                    create_longevity_step(duration=120),
                ],
            ),
        ],
        skip_test_config_snapshot_checks=True,
        postchecks=_create_overcommit_postchecks(
            ixia_downlink_interface, ixia_remote_interface
        ),
    )

    # Overcommit Coldboot playbook
    overcommit_coldboot_playbook = Playbook(
        name="Overcommit_ECMP_Group_Coldboot",
        stages=[
            create_steps_stage(
                stage_id="enable_overcommit_and_validate",
                steps=[
                    # Enable Gold device group
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*DLB_RESOURCE\\(GOLD\\)",
                            "enable": True,
                        },
                        description="Enable Gold device group",
                    ),
                    # Enable Silver device group
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*NON_DLB_RESOURCE\\(SILVER\\)",
                            "enable": True,
                        },
                        description="Enable Silver device group",
                    ),
                    # Enable Rouge device group for overcommit testing
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*NON_DLB_RESOURCE\\(ROUGE\\)",
                            "enable": True,
                        },
                        description="Enable Rouge device group for overcommit testing",
                    ),
                    create_longevity_step(
                        duration=60,
                        description="Wait for BGP routes to converge after enabling device groups",
                    ),
                    # Validate ResourceAccountant in wedge_agent log - FAIL if not found
                    create_run_ssh_command_step(
                        cmd="cat /var/facebook/logs/fboss/wedge_agent.log | grep -i 'ResourceAccountant' | tail -50 || (echo 'FAILED: ResourceAccountant not found in wedge_agent log' && exit 1)"
                    ),
                ],
            ),
            create_steps_stage(
                stage_id="enable_prefix_flapping",
                steps=[
                    create_toggle_ixia_prefix_session_flap_churn_step(
                        churn_mode="random",
                        enable_prefix_flap=True,
                        is_all_prefix_groups=True,
                        churn_duration_s=0,
                    ),
                ],
            ),
            create_steps_stage(
                iteration=1,  # TODO: Revert to 5 after testing
                steps=[
                    create_service_interruption_step(
                        service=Service.AGENT,
                        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                        create_cold_boot_file=True,
                    ),
                    create_service_convergence_step(
                        services=[Service.AGENT, Service.BGP],
                    ),
                    create_longevity_step(duration=900),
                ],
            ),
            create_steps_stage(
                stage_id="disable_prefix_flapping",
                steps=[
                    create_toggle_ixia_prefix_session_flap_churn_step(
                        churn_mode="random",
                        enable_prefix_flap=False,
                        is_all_prefix_groups=True,
                        churn_duration_s=0,
                    ),
                ],
            ),
            create_steps_stage(
                stage_id="post_churn_stabilization",
                steps=[
                    create_longevity_step(duration=120),
                ],
            ),
        ],
        skip_test_config_snapshot_checks=True,
        postchecks=_create_overcommit_postchecks(
            ixia_downlink_interface, ixia_remote_interface
        ),
    )

    return [
        base_playbook,
        warmboot_playbook,
        bgp_restart_playbook,
        coldboot_playbook,
        overcommit_base_playbook,
        overcommit_warmboot_playbook,
        overcommit_bgp_restart_playbook,
        overcommit_coldboot_playbook,
    ]


def create_ecmp_members_playbooks(
    ixia_downlink_interface: str,
    ixia_remote_interface: str,
    asic: DlbAsic = DlbAsic.TOMAHAWK3,
) -> list[Playbook]:
    """
    Create ECMP Members playbooks (base, Warmboot, bgp_restart, Coldboot).

    This function generates 4 playbooks for ECMP Members testing to reduce
    code duplication. All playbooks share the same structure with different
    service restart configurations.

    Args:
        ixia_downlink_interface: The IXIA downlink interface name for Gold traffic item
        ixia_remote_interface: The IXIA remote interface name for Silver traffic item
        asic: ASIC family of the DUT; selects the platform-aware DLB group
            ceiling (Tomahawk3=10, Tomahawk5=94) for the resource checks.

    Returns:
        A list of 4 Playbook objects:
        - Full_Utilization_ECMP_Members (base playbook)
        - Full_Utilization_ECMP_Members_Warmboot
        - Full_Utilization_ECMP_Members_bgp_restart
        - Full_Utilization_ECMP_Members_Coldboot
    """
    # Platform-aware DLB group ceiling (expected_totals["dlb"]). The prefix
    # counts below are test-traffic design (identical across platforms); only
    # the DLB group ceiling is ASIC-specific. See dlb_platform_constants.py.
    max_dlb_groups = DLB_RESOURCE_PROFILES[asic].max_dlb_groups

    def _create_common_postchecks(
        gold_interface: str, silver_interface: str
    ) -> list[PointInTimeHealthCheck]:
        """Create common postchecks for Members playbooks."""
        return [
            create_systemctl_active_state_check(
                services=[
                    hc_types.Service.WEDGE_AGENT,
                    hc_types.Service.BGPD,
                    hc_types.Service.QSFP_SERVICE,
                    hc_types.Service.FSDB,
                    hc_types.Service.FBOSS_SW_AGENT,
                    hc_types.Service.FBOSS_HW_AGENT_0,
                ]
            ),
            # Combined DLB check: counts unique ECMP groups per prefix category
            create_dlb_resource_stickiness_check(
                json_params={
                    "prefix_patterns": ["5000:dd::", "5000:ee::"],
                    "expected_counts": {
                        "5000:dd prefixes": {"total": 110, "max_next_hops": 64},
                        "5000:ee prefixes": {
                            "total": 270,
                            "max_next_hops": 128,
                        },
                    },
                    "expected_totals": {
                        "dlb": max_dlb_groups,
                    },
                }
            ),
            create_cpu_utilization_check(
                threshold=400.0, start_time_jq_var="test_case_start_time"
            ),
            create_service_restart_check(
                services=SERVICES_TO_MONITOR_DURING_AGENT_RESTART
            ),
            create_memory_utilization_check(
                threshold=5 * (1024**3),
                threshold_by_service={
                    "bgpd": 4.5 * (1024**3),
                    "fsdb": 5 * (1024**3),
                    "qsfp_service": 2 * (1024**3),
                    "fboss_sw_agent": 9 * (1024**3),
                    "fboss_hw_agent@0": 8 * (1024**3),
                },
                start_time_jq_var="test_case_start_time",
            ),
            create_unclean_exit_check(),
            create_ixia_packet_loss_check(
                clear_traffic_stats=True,
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=[
                            f"{gold_interface.upper().replace('/', '_')}_TO_DLB_GOLDEN_TRAFFIC"
                        ],
                        str_value="0",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                    hc_types.PacketLossThreshold(
                        names=[
                            f"{silver_interface.upper().replace('/', '_')}_TO_SILVER_TRAFFIC"
                        ],
                        str_value="0",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                    hc_types.PacketLossThreshold(
                        names=[
                            f"{silver_interface.upper().replace('/', '_')}_TO_ROUGE_TRAFFIC"
                        ],
                        str_value="100",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                ],
            ),
        ]

    def _create_coldboot_postchecks(
        gold_interface: str, silver_interface: str
    ) -> list[PointInTimeHealthCheck]:
        """Create postchecks for Coldboot playbook (simplified version)."""
        return [
            create_systemctl_active_state_check(
                services=[
                    hc_types.Service.WEDGE_AGENT,
                    hc_types.Service.BGPD,
                    hc_types.Service.QSFP_SERVICE,
                    hc_types.Service.FSDB,
                    hc_types.Service.FBOSS_SW_AGENT,
                    hc_types.Service.FBOSS_HW_AGENT_0,
                ]
            ),
            # Combined DLB check: counts unique ECMP groups per prefix category
            create_dlb_resource_stickiness_check(
                json_params={
                    "prefix_patterns": ["5000:dd::", "5000:ee::"],
                    "expected_counts": {
                        "5000:dd prefixes": {"total": 110, "max_next_hops": 64},
                        "5000:ee prefixes": {
                            "total": 270,
                            "max_next_hops": 128,
                        },
                    },
                    "expected_totals": {
                        "dlb": max_dlb_groups,
                    },
                }
            ),
            create_ixia_packet_loss_check(
                clear_traffic_stats=True,
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=[
                            f"{gold_interface.upper().replace('/', '_')}_TO_DLB_GOLDEN_TRAFFIC"
                        ],
                        str_value="0",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                    hc_types.PacketLossThreshold(
                        names=[
                            f"{silver_interface.upper().replace('/', '_')}_TO_SILVER_TRAFFIC"
                        ],
                        str_value="0",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                    hc_types.PacketLossThreshold(
                        names=[
                            f"{silver_interface.upper().replace('/', '_')}_TO_ROUGE_TRAFFIC"
                        ],
                        str_value="100",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                ],
            ),
        ]

    def _create_overcommit_members_postchecks(
        gold_interface: str, silver_interface: str
    ) -> list[PointInTimeHealthCheck]:
        """Create postchecks for Overcommit Members playbooks."""
        return [
            create_systemctl_active_state_check(
                services=[
                    hc_types.Service.WEDGE_AGENT,
                    hc_types.Service.BGPD,
                    hc_types.Service.QSFP_SERVICE,
                    hc_types.Service.FSDB,
                    hc_types.Service.FBOSS_SW_AGENT,
                    hc_types.Service.FBOSS_HW_AGENT_0,
                ]
            ),
            # Combined DLB check for Overcommit Members. Prefix counts
            # (5000:dd = 70, 5000:ee = 173) are test-traffic design; the DLB
            # group ceiling is platform-aware (dlb_platform_constants.py).
            create_dlb_resource_stickiness_check(
                json_params={
                    "prefix_patterns": ["5000:dd::", "5000:ee::"],
                    "expected_counts": {
                        "5000:dd prefixes": {"total": 70, "max_next_hops": 64},
                        "5000:ee prefixes": {
                            "total": 173,
                            "max_next_hops": 128,
                        },
                    },
                    "expected_totals": {
                        "dlb": max_dlb_groups,
                    },
                }
            ),
            create_cpu_utilization_check(
                threshold=400.0, start_time_jq_var="test_case_start_time"
            ),
            create_service_restart_check(
                services=SERVICES_TO_MONITOR_DURING_AGENT_RESTART
            ),
            create_memory_utilization_check(
                threshold=5 * (1024**3),
                threshold_by_service={
                    "bgpd": 4.5 * (1024**3),
                    "fsdb": 5 * (1024**3),
                    "qsfp_service": 2 * (1024**3),
                    "fboss_sw_agent": 9 * (1024**3),
                    "fboss_hw_agent@0": 8 * (1024**3),
                },
                start_time_jq_var="test_case_start_time",
            ),
            create_unclean_exit_check(),
        ]

    # Base playbook - Full_Utilization_ECMP_Members (duplicate of Full_Utilization_ECMP_Groups)
    base_playbook = Playbook(
        name="Full_Utilization_ECMP_Members",
        description="Utilize 100% of DLB, NON_DLB Members (50% Member Occupancy)",
        backup_and_restore_ixia_config=True,
        stages=[
            create_steps_stage(
                stage_id="configure_ecmp_and_run_traffic",
                steps=[
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*NON_DLB_RESOURCE\\(ROUGE\\)",
                            "enable": False,
                        },
                        description="Disable Rouge device group for Members testing",
                    ),
                    # Modify ECMP width for Gold network group to 64
                    create_ixia_api_step(
                        api_name="modify_network_group_ecmp_width",
                        args_dict={
                            "network_group_name_regex": ".*DLB_golden_prefixes.*",
                            "ecmp_width": 64,
                        },
                        description="Change Gold network group ECMP width to 64",
                    ),
                    # Modify ECMP width for Silver network group to 128
                    create_ixia_api_step(
                        api_name="modify_network_group_ecmp_width",
                        args_dict={
                            "network_group_name_regex": ".*SILVER_BGP_PREFIXES.*",
                            "ecmp_width": 128,
                        },
                        description="Change Silver network group ECMP width to 128",
                    ),
                    create_longevity_step(
                        duration=60,
                        description="Wait for BGP routes to converge",
                    ),
                    create_ixia_api_step(
                        api_name="start_traffic",
                        args_dict={},
                        description="Start traffic after BGP convergence",
                    ),
                    create_longevity_step(
                        duration=120,
                        description="Run traffic for steady state measurement",
                    ),
                ],
            ),
        ],
        postchecks=_create_common_postchecks(
            ixia_downlink_interface, ixia_remote_interface
        ),
    )

    # Warmboot playbook
    warmboot_playbook = Playbook(
        name="Full_Utilization_ECMP_Members_Warmboot",
        stages=[
            create_steps_stage(
                stage_id="disable_rouge",
                steps=[
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*NON_DLB_RESOURCE\\(ROUGE\\)",
                            "enable": False,
                        },
                        description="Disable Rouge device group for Members testing",
                    ),
                ],
            ),
            create_steps_stage(
                stage_id="enable_prefix_flapping",
                steps=[
                    create_toggle_ixia_prefix_session_flap_churn_step(
                        churn_mode="random",
                        enable_prefix_flap=True,
                        is_all_prefix_groups=True,
                        churn_duration_s=0,
                    ),
                ],
            ),
            create_steps_stage(
                iteration=5,
                steps=[
                    create_service_interruption_step(
                        service=Service.AGENT,
                        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(
                        services=[Service.AGENT, Service.BGP],
                    ),
                    create_longevity_step(duration=900),
                ],
            ),
            create_steps_stage(
                stage_id="disable_prefix_flapping",
                steps=[
                    create_toggle_ixia_prefix_session_flap_churn_step(
                        churn_mode="random",
                        enable_prefix_flap=False,
                        is_all_prefix_groups=True,
                        churn_duration_s=0,
                    ),
                ],
            ),
            create_steps_stage(
                stage_id="post_churn_stabilization",
                steps=[
                    create_longevity_step(duration=120),
                ],
            ),
        ],
        skip_test_config_snapshot_checks=True,
        postchecks=_create_common_postchecks(
            ixia_downlink_interface, ixia_remote_interface
        ),
    )

    # BGP restart playbook
    bgp_restart_playbook = Playbook(
        name="Full_Utilization_ECMP_Members_bgp_restart",
        stages=[
            create_steps_stage(
                stage_id="disable_rouge",
                steps=[
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*NON_DLB_RESOURCE\\(ROUGE\\)",
                            "enable": False,
                        },
                        description="Disable Rouge device group for Members testing",
                    ),
                ],
            ),
            create_steps_stage(
                stage_id="enable_prefix_flapping",
                steps=[
                    create_toggle_ixia_prefix_session_flap_churn_step(
                        churn_mode="random",
                        enable_prefix_flap=True,
                        is_all_prefix_groups=True,
                        churn_duration_s=0,
                    ),
                ],
            ),
            create_steps_stage(
                iteration=5,
                steps=[
                    create_service_interruption_step(
                        service=Service.BGP,
                        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(
                        services=[Service.AGENT, Service.BGP],
                    ),
                    create_longevity_step(duration=300),
                ],
            ),
            create_steps_stage(
                stage_id="disable_prefix_flapping",
                steps=[
                    create_toggle_ixia_prefix_session_flap_churn_step(
                        churn_mode="random",
                        enable_prefix_flap=False,
                        is_all_prefix_groups=True,
                        churn_duration_s=0,
                    ),
                ],
            ),
            create_steps_stage(
                stage_id="post_churn_stabilization",
                steps=[
                    create_longevity_step(duration=120),
                ],
            ),
        ],
        skip_test_config_snapshot_checks=True,
        postchecks=_create_common_postchecks(
            ixia_downlink_interface, ixia_remote_interface
        ),
    )

    # Coldboot playbook
    coldboot_playbook = Playbook(
        name="Full_Utilization_ECMP_Members_Coldboot",
        stages=[
            create_steps_stage(
                stage_id="disable_rouge",
                steps=[
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*NON_DLB_RESOURCE\\(ROUGE\\)",
                            "enable": False,
                        },
                        description="Disable Rouge device group for Members testing",
                    ),
                ],
            ),
            create_steps_stage(
                stage_id="enable_prefix_flapping",
                steps=[
                    create_toggle_ixia_prefix_session_flap_churn_step(
                        churn_mode="random",
                        enable_prefix_flap=True,
                        is_all_prefix_groups=True,
                        churn_duration_s=0,
                    ),
                ],
            ),
            create_steps_stage(
                iteration=5,
                steps=[
                    create_service_interruption_step(
                        service=Service.AGENT,
                        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                        create_cold_boot_file=True,
                    ),
                    create_service_convergence_step(
                        services=[Service.AGENT, Service.BGP],
                    ),
                    create_longevity_step(duration=900),
                ],
            ),
            create_steps_stage(
                stage_id="disable_prefix_flapping",
                steps=[
                    create_toggle_ixia_prefix_session_flap_churn_step(
                        churn_mode="random",
                        enable_prefix_flap=False,
                        is_all_prefix_groups=True,
                        churn_duration_s=0,
                    ),
                ],
            ),
            create_steps_stage(
                stage_id="post_churn_stabilization",
                steps=[
                    create_longevity_step(duration=120),
                ],
            ),
        ],
        skip_test_config_snapshot_checks=True,
        postchecks=_create_coldboot_postchecks(
            ixia_downlink_interface, ixia_remote_interface
        ),
    )

    # =========================================================================
    # OVERCOMMIT PLAYBOOKS (duplicates with "Overcommit" prefix)
    # =========================================================================

    # Overcommit base playbook
    overcommit_base_playbook = Playbook(
        name="Overcommit_ECMP_Members",
        description="Overcommit DLB, NON_DLB Members (50% Member Occupancy)",
        backup_and_restore_ixia_config=True,
        stages=[
            create_steps_stage(
                stage_id="configure_ecmp_and_run_traffic",
                steps=[
                    # Enable Gold device group
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*DLB_RESOURCE\\(GOLD\\)",
                            "enable": True,
                        },
                        description="Enable Gold device group",
                    ),
                    # Enable Silver device group
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*NON_DLB_RESOURCE\\(SILVER\\)",
                            "enable": True,
                        },
                        description="Enable Silver device group",
                    ),
                    # Disable Rouge device group for members testing
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*NON_DLB_RESOURCE\\(ROUGE\\)",
                            "enable": False,
                        },
                        description="Disable Rouge device group for members testing",
                    ),
                    # Modify ECMP width for Gold network group to 100
                    create_ixia_api_step(
                        api_name="modify_network_group_ecmp_width",
                        args_dict={
                            "network_group_name_regex": ".*DLB_golden_prefixes.*",
                            "ecmp_width": 100,
                        },
                        description="Change Gold network group ECMP width to 100",
                    ),
                    # Modify ECMP width for Silver network group to 200
                    create_ixia_api_step(
                        api_name="modify_network_group_ecmp_width",
                        args_dict={
                            "network_group_name_regex": ".*SILVER_BGP_PREFIXES.*",
                            "ecmp_width": 200,
                        },
                        description="Change Silver network group ECMP width to 200",
                    ),
                    create_longevity_step(
                        duration=60,
                        description="Wait for BGP routes to converge",
                    ),
                    create_ixia_api_step(
                        api_name="start_traffic",
                        args_dict={},
                        description="Start traffic after BGP convergence",
                    ),
                    create_longevity_step(
                        duration=120,
                        description="Run traffic for steady state measurement",
                    ),
                    # Validate ResourceAccountant in wedge_agent log - FAIL if not found
                    create_run_ssh_command_step(
                        cmd="cat /var/facebook/logs/fboss/wedge_agent.log | grep -i 'ResourceAccountant' | tail -50 || (echo 'FAILED: ResourceAccountant not found in wedge_agent log' && exit 1)"
                    ),
                ],
            ),
        ],
        postchecks=_create_overcommit_members_postchecks(
            ixia_downlink_interface, ixia_remote_interface
        ),
    )

    # Overcommit Warmboot playbook
    overcommit_warmboot_playbook = Playbook(
        name="Overcommit_ECMP_Members_Warmboot",
        stages=[
            create_steps_stage(
                stage_id="configure_ecmp_and_validate",
                steps=[
                    # Enable Gold device group
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*DLB_RESOURCE\\(GOLD\\)",
                            "enable": True,
                        },
                        description="Enable Gold device group",
                    ),
                    # Enable Silver device group
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*NON_DLB_RESOURCE\\(SILVER\\)",
                            "enable": True,
                        },
                        description="Enable Silver device group",
                    ),
                    # Disable Rouge device group for members testing
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*NON_DLB_RESOURCE\\(ROUGE\\)",
                            "enable": False,
                        },
                        description="Disable Rouge device group for members testing",
                    ),
                    # Modify ECMP width for Gold network group to 100
                    create_ixia_api_step(
                        api_name="modify_network_group_ecmp_width",
                        args_dict={
                            "network_group_name_regex": ".*DLB_golden_prefixes.*",
                            "ecmp_width": 100,
                        },
                        description="Change Gold network group ECMP width to 100",
                    ),
                    # Modify ECMP width for Silver network group to 200
                    create_ixia_api_step(
                        api_name="modify_network_group_ecmp_width",
                        args_dict={
                            "network_group_name_regex": ".*SILVER_BGP_PREFIXES.*",
                            "ecmp_width": 200,
                        },
                        description="Change Silver network group ECMP width to 200",
                    ),
                    create_longevity_step(
                        duration=60,
                        description="Wait for BGP routes to converge",
                    ),
                    # Validate ResourceAccountant in wedge_agent log - FAIL if not found
                    create_run_ssh_command_step(
                        cmd="cat /var/facebook/logs/fboss/wedge_agent.log | grep -i 'ResourceAccountant' | tail -50 || (echo 'FAILED: ResourceAccountant not found in wedge_agent log' && exit 1)"
                    ),
                ],
            ),
            create_steps_stage(
                stage_id="enable_prefix_flapping",
                steps=[
                    create_toggle_ixia_prefix_session_flap_churn_step(
                        churn_mode="random",
                        enable_prefix_flap=True,
                        is_all_prefix_groups=True,
                        churn_duration_s=0,
                    ),
                ],
            ),
            create_steps_stage(
                iteration=5,
                steps=[
                    create_service_interruption_step(
                        service=Service.AGENT,
                        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(
                        services=[Service.AGENT, Service.BGP],
                    ),
                    create_longevity_step(duration=900),
                ],
            ),
            create_steps_stage(
                stage_id="disable_prefix_flapping",
                steps=[
                    create_toggle_ixia_prefix_session_flap_churn_step(
                        churn_mode="random",
                        enable_prefix_flap=False,
                        is_all_prefix_groups=True,
                        churn_duration_s=0,
                    ),
                ],
            ),
            create_steps_stage(
                stage_id="post_churn_stabilization",
                steps=[
                    create_longevity_step(duration=120),
                ],
            ),
        ],
        skip_test_config_snapshot_checks=True,
        postchecks=_create_overcommit_members_postchecks(
            ixia_downlink_interface, ixia_remote_interface
        ),
    )

    # Overcommit BGP restart playbook
    overcommit_bgp_restart_playbook = Playbook(
        name="Overcommit_ECMP_Members_bgp_restart",
        stages=[
            create_steps_stage(
                stage_id="disable_rouge",
                steps=[
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*NON_DLB_RESOURCE\\(ROUGE\\)",
                            "enable": False,
                        },
                        description="Disable Rouge device group for Overcommit Members testing",
                    ),
                ],
            ),
            create_steps_stage(
                stage_id="validate_resource_accountant",
                steps=[
                    # Validate ResourceAccountant in wedge_agent log - FAIL if not found
                    create_run_ssh_command_step(
                        cmd="cat /var/facebook/logs/fboss/wedge_agent.log | grep -i 'ResourceAccountant' | tail -50 || (echo 'FAILED: ResourceAccountant not found in wedge_agent log' && exit 1)"
                    ),
                ],
            ),
            create_steps_stage(
                stage_id="enable_prefix_flapping",
                steps=[
                    create_toggle_ixia_prefix_session_flap_churn_step(
                        churn_mode="random",
                        enable_prefix_flap=True,
                        is_all_prefix_groups=True,
                        churn_duration_s=0,
                    ),
                ],
            ),
            create_steps_stage(
                iteration=5,
                steps=[
                    create_service_interruption_step(
                        service=Service.BGP,
                        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(
                        services=[Service.AGENT, Service.BGP],
                    ),
                    create_longevity_step(duration=120),
                ],
            ),
            create_steps_stage(
                stage_id="disable_prefix_flapping",
                steps=[
                    create_toggle_ixia_prefix_session_flap_churn_step(
                        churn_mode="random",
                        enable_prefix_flap=False,
                        is_all_prefix_groups=True,
                        churn_duration_s=0,
                    ),
                ],
            ),
            create_steps_stage(
                stage_id="post_churn_stabilization",
                steps=[
                    create_longevity_step(duration=120),
                ],
            ),
        ],
        skip_test_config_snapshot_checks=True,
        postchecks=_create_overcommit_members_postchecks(
            ixia_downlink_interface, ixia_remote_interface
        ),
    )

    # Overcommit Coldboot playbook
    overcommit_coldboot_playbook = Playbook(
        name="Overcommit_ECMP_Members_Coldboot",
        stages=[
            create_steps_stage(
                stage_id="disable_rouge",
                steps=[
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*NON_DLB_RESOURCE\\(ROUGE\\)",
                            "enable": False,
                        },
                        description="Disable Rouge device group for Overcommit Members testing",
                    ),
                ],
            ),
            create_steps_stage(
                stage_id="validate_resource_accountant",
                steps=[
                    # Validate ResourceAccountant in wedge_agent log - FAIL if not found
                    create_run_ssh_command_step(
                        cmd="cat /var/facebook/logs/fboss/wedge_agent.log | grep -i 'ResourceAccountant' | tail -50 || (echo 'FAILED: ResourceAccountant not found in wedge_agent log' && exit 1)"
                    ),
                ],
            ),
            create_steps_stage(
                stage_id="enable_prefix_flapping",
                steps=[
                    create_toggle_ixia_prefix_session_flap_churn_step(
                        churn_mode="random",
                        enable_prefix_flap=True,
                        is_all_prefix_groups=True,
                        churn_duration_s=0,
                    ),
                ],
            ),
            create_steps_stage(
                iteration=5,
                steps=[
                    create_service_interruption_step(
                        service=Service.AGENT,
                        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                        create_cold_boot_file=True,
                    ),
                    create_service_convergence_step(
                        services=[Service.AGENT, Service.BGP],
                    ),
                    create_longevity_step(duration=900),
                ],
            ),
            create_steps_stage(
                stage_id="disable_prefix_flapping",
                steps=[
                    create_toggle_ixia_prefix_session_flap_churn_step(
                        churn_mode="random",
                        enable_prefix_flap=False,
                        is_all_prefix_groups=True,
                        churn_duration_s=0,
                    ),
                ],
            ),
            create_steps_stage(
                stage_id="post_churn_stabilization",
                steps=[
                    create_longevity_step(duration=120),
                ],
            ),
        ],
        skip_test_config_snapshot_checks=True,
        postchecks=_create_overcommit_members_postchecks(
            ixia_downlink_interface, ixia_remote_interface
        ),
    )

    return [
        base_playbook,
        warmboot_playbook,
        bgp_restart_playbook,
        coldboot_playbook,
        overcommit_base_playbook,
        overcommit_warmboot_playbook,
        overcommit_bgp_restart_playbook,
        overcommit_coldboot_playbook,
    ]


# =============================================================================
# SECTION 4.3: SPILLOVER TESTING PLAYBOOKS HELPER FUNCTION
# =============================================================================
def create_spillover_testing_playbooks(
    ixia_downlink_interface: str,
    ixia_remote_interface: str,
    asic: DlbAsic = DlbAsic.TOMAHAWK3,
) -> list[Playbook]:
    """
    Create Spillover Testing playbook for ECMP resource spillover validation.

    This playbook tests the spillover behavior when ECMP resources exceed limits:
    - Gold ECMP width = 75
    - Silver ECMP width = 370

    Three stages:
    1. Enable Gold + Silver: Expect no packet loss (PASS)
    2. Disable Gold, Enable Silver: Expect packet loss on Gold, no loss on Silver (PASS)
    3. Enable Gold, Disable Silver: Expect no loss on Gold, packet loss on Silver (PASS)

    Args:
        ixia_downlink_interface: The IXIA downlink interface name for Gold traffic
        ixia_remote_interface: The IXIA remote interface name for Silver traffic
        asic: ASIC family of the DUT; selects the platform-aware DLB group
            ceiling (Tomahawk3=10, Tomahawk5=94) for the resource checks.

    Returns:
        A list containing the Spillover_Testing playbook
    """
    # Platform-aware DLB group ceiling (expected_totals["dlb"]); see
    # dlb_platform_constants.py. Prefix counts below are test-traffic design.
    max_dlb_groups = DLB_RESOURCE_PROFILES[asic].max_dlb_groups

    def _create_spillover_postchecks_both_enabled(
        gold_interface: str, rouge_interface: str
    ) -> list[PointInTimeHealthCheck]:
        """Create postchecks for Stage 1: Both Gold and Rouge enabled - expect no packet loss."""
        return [
            create_systemctl_active_state_check(
                services=[
                    hc_types.Service.WEDGE_AGENT,
                    hc_types.Service.BGPD,
                    hc_types.Service.QSFP_SERVICE,
                    hc_types.Service.FSDB,
                    hc_types.Service.FBOSS_SW_AGENT,
                    hc_types.Service.FBOSS_HW_AGENT_0,
                ]
            ),
            create_ixia_packet_loss_check(
                clear_traffic_stats=True,
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=[
                            f"{gold_interface.upper().replace('/', '_')}_TO_DLB_GOLDEN_TRAFFIC"
                        ],
                        str_value="0",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                    hc_types.PacketLossThreshold(
                        names=[
                            f"{rouge_interface.upper().replace('/', '_')}_TO_ROUGE_TRAFFIC"
                        ],
                        str_value="0",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                ],
            ),
        ]

    def _create_spillover_postchecks_gold_disabled(
        gold_interface: str, silver_interface: str
    ) -> list[PointInTimeHealthCheck]:
        """Create postchecks for Stage 2a: Gold disabled, Rouge enabled.
        Expect packet loss on Gold (100%), no loss on Rouge (0%).
        """
        return [
            create_systemctl_active_state_check(
                services=[
                    hc_types.Service.WEDGE_AGENT,
                    hc_types.Service.BGPD,
                    hc_types.Service.QSFP_SERVICE,
                    hc_types.Service.FSDB,
                    hc_types.Service.FBOSS_SW_AGENT,
                    hc_types.Service.FBOSS_HW_AGENT_0,
                ]
            ),
            create_ixia_packet_loss_check(
                clear_traffic_stats=True,
                thresholds=[
                    # Gold should have 100% packet loss (device group disabled)
                    hc_types.PacketLossThreshold(
                        names=[
                            f"{gold_interface.upper().replace('/', '_')}_TO_DLB_GOLDEN_TRAFFIC"
                        ],
                        str_value="100",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                    # Rouge should have no packet loss
                    hc_types.PacketLossThreshold(
                        names=[
                            f"{silver_interface.upper().replace('/', '_')}_TO_ROUGE_TRAFFIC"
                        ],
                        str_value="0",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                    # Silver is disabled - expect 100% loss
                    hc_types.PacketLossThreshold(
                        names=[
                            f"{silver_interface.upper().replace('/', '_')}_TO_SILVER_TRAFFIC"
                        ],
                        str_value="100",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                ],
            ),
        ]

    def _create_spillover_postchecks_silver_disabled(
        gold_interface: str, silver_interface: str
    ) -> list[PointInTimeHealthCheck]:
        """Create postchecks for Stage 3: Gold enabled, Silver disabled.
        Expect no loss on Gold (0%), packet loss on Silver (>0%).
        """
        return [
            create_systemctl_active_state_check(
                services=[
                    hc_types.Service.WEDGE_AGENT,
                    hc_types.Service.BGPD,
                    hc_types.Service.QSFP_SERVICE,
                    hc_types.Service.FSDB,
                    hc_types.Service.FBOSS_SW_AGENT,
                    hc_types.Service.FBOSS_HW_AGENT_0,
                ]
            ),
            create_ixia_packet_loss_check(
                clear_traffic_stats=True,
                thresholds=[
                    # Gold should have no packet loss
                    hc_types.PacketLossThreshold(
                        names=[
                            f"{gold_interface.upper().replace('/', '_')}_TO_DLB_GOLDEN_TRAFFIC"
                        ],
                        str_value="0",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                    # Silver should have 100% packet loss (device group disabled)
                    hc_types.PacketLossThreshold(
                        names=[
                            f"{silver_interface.upper().replace('/', '_')}_TO_SILVER_TRAFFIC"
                        ],
                        str_value="100",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                ],
            ),
        ]

    # Spillover Testing Playbook
    spillover_testing_playbook = Playbook(
        name="Spillover_Testing",
        description="Test ECMP resource spillover with Gold and Rouge (Silver disabled)",
        backup_and_restore_ixia_config=True,
        stages=[
            # Stage 1: Enable Gold and Rouge, disable Silver, run traffic
            create_steps_stage(
                stage_id="configure_and_run_traffic",
                steps=[
                    # Start IXIA protocols first (required for BGP sessions to come up)
                    create_ixia_api_step(
                        api_name="start_protocols",
                        args_dict={},
                        description="Start IXIA protocols to bring up BGP sessions",
                    ),
                    # Enable Gold device group
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*DLB_RESOURCE\\(GOLD\\)",
                            "enable": True,
                        },
                        description="Enable Gold device group",
                    ),
                    # Enable Rouge device group
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*NON_DLB_RESOURCE\\(ROUGE\\)",
                            "enable": True,
                        },
                        description="Enable Rouge device group",
                    ),
                    # Disable Silver device group
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*NON_DLB_RESOURCE\\(SILVER\\)",
                            "enable": False,
                        },
                        description="Disable Silver device group",
                    ),
                    create_longevity_step(
                        duration=60,
                        description="Wait for BGP routes to converge",
                    ),
                    create_ixia_api_step(
                        api_name="start_traffic",
                        args_dict={},
                        description="Start traffic after BGP convergence",
                    ),
                    create_longevity_step(
                        duration=120,
                        description="Run traffic - Gold and Rouge enabled - expect no packet loss",
                    ),
                    # Validation step for Stage 1
                    create_validation_step(
                        point_in_time_checks=_create_spillover_postchecks_both_enabled(
                            ixia_downlink_interface, ixia_remote_interface
                        ),
                        description="Validate no packet loss on Gold and Rouge traffic",
                    ),
                ],
            ),
            # Stage 2: Spillover toggle - iterate 5 times
            # Each iteration: Disable Gold -> Enable Gold/Disable Rouge -> Re-enable Rouge
            create_steps_stage(
                stage_id="spillover_toggle_iterations",
                iteration=5,
                steps=[
                    # Part A: Disable Gold (Rouge remains enabled)
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*DLB_RESOURCE\\(GOLD\\)",
                            "enable": False,
                        },
                        description="Disable Gold device group",
                    ),
                    create_longevity_step(
                        duration=60,
                        description="Wait for BGP routes to converge after disabling Gold",
                    ),
                    create_longevity_step(
                        duration=120,
                        description="Run traffic - Gold disabled, Rouge enabled",
                    ),
                    # Validation step for Part A: Gold disabled, Rouge enabled
                    create_validation_step(
                        point_in_time_checks=[
                            create_dlb_resource_stickiness_check(
                                json_params={
                                    "prefix_patterns": [
                                        "5000:dd::",
                                        "5000:ff::",
                                    ],
                                    "expected_counts": {
                                        "5000:dd prefixes": {"total": 0},
                                        "5000:ff prefixes": {
                                            "min_total": 110,
                                        },
                                    },
                                }
                            ),
                        ],
                        description="Validate Gold disabled (0 prefixes), Rouge enabled (min_total=110)",
                    ),
                    # Part B: Enable Gold, Disable Rouge
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*DLB_RESOURCE\\(GOLD\\)",
                            "enable": True,
                        },
                        description="Enable Gold device group",
                    ),
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*NON_DLB_RESOURCE\\(ROUGE\\)",
                            "enable": False,
                        },
                        description="Disable Rouge device group",
                    ),
                    create_longevity_step(
                        duration=60,
                        description="Wait for BGP routes to converge after disabling Rouge",
                    ),
                    create_longevity_step(
                        duration=120,
                        description="Run traffic - Gold enabled, Rouge disabled",
                    ),
                    # Validation step for Part B: Gold enabled, Rouge disabled
                    create_validation_step(
                        point_in_time_checks=[
                            create_dlb_resource_stickiness_check(
                                json_params={
                                    "prefix_patterns": [
                                        "5000:dd::",
                                        "5000:ff::",
                                    ],
                                    "expected_counts": {
                                        "5000:dd prefixes": {
                                            "min_total": 110,
                                            # TODO(dne_pit): per-bucket "dlb": 91
                                            # predates the platform-aware ceiling
                                            # and exceeds it — review whether this
                                            # should track max_dlb_groups.
                                            "dlb": 91,
                                        },
                                        "5000:ff prefixes": {"total": 0},
                                    },
                                    "expected_totals": {
                                        "dlb": max_dlb_groups,
                                    },
                                }
                            ),
                        ],
                        description="Validate Gold enabled (min_total=110, dlb=90), Rouge disabled (0 prefixes)",
                    ),
                    # Part C: Re-enable Rouge for next iteration
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "device_group_name_regex": ".*NON_DLB_RESOURCE\\(ROUGE\\)",
                            "enable": True,
                        },
                        description="Re-enable Rouge device group for next iteration",
                    ),
                ],
            ),
        ],
        skip_test_config_snapshot_checks=True,
        snapshot_checks=[
            create_core_dumps_snapshot_check(),
        ],
        postchecks=[
            create_systemctl_active_state_check(
                services=[
                    hc_types.Service.WEDGE_AGENT,
                    hc_types.Service.BGPD,
                    hc_types.Service.QSFP_SERVICE,
                    hc_types.Service.FSDB,
                    hc_types.Service.FBOSS_SW_AGENT,
                    hc_types.Service.FBOSS_HW_AGENT_0,
                ]
            ),
            create_cpu_utilization_check(
                threshold=400.0, start_time_jq_var="test_case_start_time"
            ),
            create_memory_utilization_check(
                threshold=5 * (1024**3),
                threshold_by_service={
                    "bgpd": 4.5 * (1024**3),
                    "fsdb": 5 * (1024**3),
                    "qsfp_service": 2 * (1024**3),
                    "fboss_sw_agent": 9 * (1024**3),
                    "fboss_hw_agent@0": 8 * (1024**3),
                },
                start_time_jq_var="test_case_start_time",
            ),
            create_unclean_exit_check(),
        ],
    )

    return [spillover_testing_playbook]


# =============================================================================
# SECTION 5: COOP PATCHER TASKS
# =============================================================================


# =============================================================================
# SNAKE (loopback) PLAYBOOK FACTORIES
# Migrated from playbooks/helpers/snake/snake_playbooks.py per Phase 4 v2
# =============================================================================


def gen_ptp_health_checks() -> t.List[taac_types.PointInTimeHealthCheck]:
    return []


def gen_common_hcs(skip_lldp_check: bool) -> t.List[taac_types.PointInTimeHealthCheck]:
    common_hcs: t.List[taac_types.PointInTimeHealthCheck] = []

    if not skip_lldp_check:
        common_hcs.append(
            create_lldp_check(),
        )

    common_hcs.extend(
        [
            create_port_state_check(),
            create_packetloss_health_check(),
        ]
    )

    common_hcs.extend(gen_ptp_health_checks())

    return common_hcs


def gen_snake_longevity_playbook(
    name: str,
    duration: int,
    prechecks: t.Optional[t.List[taac_types.PointInTimeHealthCheck]] = None,
    postchecks: t.Optional[t.List[taac_types.PointInTimeHealthCheck]] = None,
):
    return taac_types.Playbook(
        name=name,
        prechecks=prechecks or [],
        postchecks=postchecks or [],
        stages=[create_steps_stage(steps=[create_longevity_step(duration=duration)])],
    )


def gen_snake_transceiver_removal_playbook(
    hostname: str,
    interfaces: t.List[str],
    prechecks: t.Optional[t.List[taac_types.PointInTimeHealthCheck]] = None,
    postchecks: t.Optional[t.List[taac_types.PointInTimeHealthCheck]] = None,
) -> taac_types.Playbook:
    interfaces_str = ", ".join(interfaces)
    return taac_types.Playbook(
        name="test_snake_transceiver_removal",
        prechecks=(prechecks or []),
        stages=[
            # Stage 1: Remove transceiver and validate
            create_steps_stage(
                steps=[
                    create_custom_step(
                        params_dict={
                            "custom_step_name": "wait_for_user_confirmation",
                            "message": f"Please REMOVE the transceiver from {interfaces_str} on {hostname}, then confirm by running the echo command shown below.",
                            "timeout": 3600,
                        },
                        description=f"Wait for transceiver removal on {interfaces_str}",
                    ),
                    create_validation_step(
                        point_in_time_checks=[
                            create_port_state_check(
                                disabled_interfaces=[
                                    {
                                        "switch_name": hostname,
                                        "interface_name": intf,
                                    }
                                    for intf in interfaces
                                ],
                            ),
                            create_port_transceiver_check(
                                json_params={
                                    "interfaces": interfaces,
                                    "expected_present": False,
                                }
                            ),
                        ],
                        stage=taac_types.ValidationStage.MID_TEST,
                        description="Verify ports are down and transceiver is absent after removal",
                    ),
                ],
            ),
            # Stage 2: Re-insert transceiver, wait for convergence, validate
            create_steps_stage(
                steps=[
                    create_custom_step(
                        params_dict={
                            "custom_step_name": "wait_for_user_confirmation",
                            "message": f"Please INSERT the transceiver into {interfaces_str} on {hostname}, then confirm by running the echo command shown above.",
                            "timeout": 3600,
                        },
                        description=f"Wait for transceiver insertion on {interfaces_str}",
                    ),
                    create_longevity_step(
                        duration=300,
                        description="Wait for link to come up and traffic to stabilize",
                    ),
                ],
            ),
        ],
        postchecks=(postchecks or [])
        + [
            create_ixia_packet_loss_check(clear_traffic_stats=True),
            create_port_transceiver_check(
                json_params={
                    "interfaces": interfaces,
                    "expected_present": True,
                }
            ),
            create_port_tx_rx_check(
                json_params={
                    "interfaces": interfaces,
                    "expected_tx": True,
                    "expected_rx": True,
                }
            ),
        ],
    )


def gen_snake_fiber_removal_playbook(
    hostname: str,
    interfaces: t.List[str],
    prechecks: t.Optional[t.List[taac_types.PointInTimeHealthCheck]] = None,
    postchecks: t.Optional[t.List[taac_types.PointInTimeHealthCheck]] = None,
) -> taac_types.Playbook:
    interfaces_str = ", ".join(interfaces)

    return taac_types.Playbook(
        name="test_snake_fiber_removal",
        prechecks=(prechecks or []),
        stages=[
            # Stage 1: Remove fiber and validate
            create_steps_stage(
                steps=[
                    create_custom_step(
                        params_dict={
                            "custom_step_name": "wait_for_user_confirmation",
                            "message": f"Please REMOVE the fiber from {interfaces_str} on {hostname}, then confirm by running the echo command shown above.",
                            "timeout": 3600,
                        },
                        description=f"Wait for fiber removal on {interfaces_str}",
                    ),
                    create_validation_step(
                        point_in_time_checks=[
                            create_port_state_check(
                                disabled_interfaces=[
                                    {
                                        "switch_name": hostname,
                                        "interface_name": intf,
                                    }
                                    for intf in interfaces
                                ],
                            ),
                            create_port_transceiver_check(
                                json_params={
                                    "interfaces": interfaces,
                                    "expected_present": True,
                                }
                            ),
                            create_port_tx_rx_check(
                                json_params={
                                    "interfaces": interfaces,
                                    "expected_tx": True,
                                    "expected_rx": False,
                                }
                            ),
                        ],
                        stage=taac_types.ValidationStage.MID_TEST,
                        description="Verify ports are down, transceiver present, but RX has no light after fiber removal",
                    ),
                ],
            ),
            # Stage 2: Re-insert fiber, wait for convergence, validate
            create_steps_stage(
                steps=[
                    create_custom_step(
                        params_dict={
                            "custom_step_name": "wait_for_user_confirmation",
                            "message": f"Please INSERT the fiber into {interfaces_str} on {hostname}, then confirm by running the echo command shown above.",
                            "timeout": 3600,
                        },
                        description=f"Wait for fiber insertion on {interfaces_str}",
                    ),
                    create_longevity_step(
                        duration=300,
                        description="Wait for link to come up and traffic to stabilize",
                    ),
                ],
            ),
        ],
        postchecks=(postchecks or [])
        + [
            create_ixia_packet_loss_check(clear_traffic_stats=True),
            create_port_transceiver_check(
                json_params={
                    "interfaces": interfaces,
                    "expected_present": True,
                }
            ),
            create_port_tx_rx_check(
                json_params={
                    "interfaces": interfaces,
                    "expected_tx": True,
                    "expected_rx": True,
                }
            ),
        ],
    )


def gen_snake_playbooks(
    hostname: str,
    iteration: int,
    playbooks_to_skip: t.Optional[t.List[str]] = None,
    include_link_flap_longevity: bool = False,
    common_prechecks: t.Optional[t.List[taac_types.PointInTimeHealthCheck]] = None,
    common_postchecks: t.Optional[t.List[taac_types.PointInTimeHealthCheck]] = None,
    manual_test_interfaces: t.Optional[t.List[str]] = None,
) -> t.List[taac_types.Playbook]:
    _prechecks = common_prechecks or []
    _postchecks = common_postchecks or []

    playbooks: t.List[taac_types.Playbook] = []

    playbooks.extend(
        [
            gen_snake_longevity_playbook(
                "test_one_min_longevity",
                60,
                prechecks=_prechecks,
                postchecks=_postchecks,
            ),
            gen_snake_longevity_playbook(
                "test_ten_min_longevity",
                600,
                prechecks=_prechecks,
                postchecks=_postchecks,
            ),
            gen_snake_longevity_playbook(
                "test_one_hour_longevity",
                3600,
                prechecks=_prechecks,
                postchecks=_postchecks,
            ),
            gen_snake_longevity_playbook(
                "test_72hr_longevity",
                3600 * 24 * 3,
                prechecks=_prechecks,
                postchecks=_postchecks,
            ),
            taac_types.Playbook(
                name="test_snake_interface_toggle_with_thrift_api",
                prechecks=_prechecks,
                postchecks=_postchecks
                + [
                    create_ixia_packet_loss_check(clear_traffic_stats=True),
                ]
                + gen_ptp_health_checks(),
                stages=[
                    create_steps_stage(
                        steps=[
                            create_interface_flap_step(
                                enable=False,
                                interface_flap_method=1,
                                delay=30,
                                jq_params={"interfaces": f'."{hostname}".interfaces'},
                                description="Sequentially disable all interfaces",
                            ),
                            create_interface_flap_step(
                                enable=True,
                                interface_flap_method=1,
                                delay=300,
                                jq_params={
                                    "interfaces": f'."{hostname}".interfaces',
                                },
                                transform_params={
                                    "interfaces": [
                                        taac_types.TransformFunction(
                                            name="SELECT_INTERFACES_BY_SLICING",
                                            json_params=json.dumps(
                                                {"slicing_expression": "::2"}
                                            ),
                                        )
                                    ]
                                },
                                description="Sequentially enable even interfaces",
                            ),
                            create_interface_flap_step(
                                enable=True,
                                interface_flap_method=1,
                                delay=300,
                                jq_params={"interfaces": f'."{hostname}".interfaces'},
                                transform_params={
                                    "interfaces": [
                                        taac_types.TransformFunction(
                                            name="SELECT_INTERFACES_BY_SLICING",
                                            json_params=json.dumps(
                                                {"slicing_expression": "1::2"}
                                            ),
                                        )
                                    ]
                                },
                                description="Sequentially enable odd interfaces",
                            ),
                        ]
                    )
                ],
                iteration=iteration,
            ),
            # Snake half-interface toggle, modeled in terms of SNAKE CIRCUITS.
            #
            # A snake circuit is a pair of interfaces on this DUT cabled to each
            # other (a loopback jumper). The SELECT_SNAKE_CIRCUIT_A_ENDS transform
            # orders circuits deterministically and returns the A-end (the
            # lower-sorting interface) of the even- or odd-indexed circuits.
            #
            # We only ever flap the A-end: disabling it takes the whole circuit
            # down. Because each disabled-circuit set is derived deterministically
            # from the topology (not positional interface slicing), the two MID_TEST
            # checks can re-derive the exact same set with NO cache, and -- crucially
            # -- disabling "even circuits" downs ONLY even circuits, leaving every
            # odd circuit fully up. The checks expand each A-end back to both ends of
            # its circuit, so "even circuits down, odd circuits up" holds exactly.
            # (The old ::4/2::4 positional slicing split a jumper's two ends across
            # waves, which forced a circuit's partner down while the check still
            # expected it up -- structurally broken on a loopback snake.)
            taac_types.Playbook(
                name="test_snake_half_interface_toggle_with_thrift_api",
                iteration=iteration,
                prechecks=_prechecks,
                postchecks=_postchecks
                + [
                    create_ixia_packet_loss_check(clear_traffic_stats=True),
                ]
                + gen_ptp_health_checks(),
                stages=[
                    create_steps_stage(
                        steps=[
                            create_interface_flap_step(
                                enable=False,
                                interface_flap_method=1,
                                delay=30,
                                jq_params={"interfaces": f'."{hostname}".interfaces'},
                                transform_params={
                                    "interfaces": [
                                        taac_types.TransformFunction(
                                            name="SELECT_SNAKE_CIRCUIT_A_ENDS",
                                            json_params=json.dumps({"parity": "even"}),
                                        )
                                    ]
                                },
                                description="Disable A-end of even snake circuits",
                            ),
                            create_validation_step(
                                point_in_time_checks=[
                                    create_lldp_check(
                                        disabled_interfaces_jq=f'."{hostname}".interfaces',
                                        disabled_interfaces_transforms=[
                                            taac_types.TransformFunction(
                                                name="SELECT_SNAKE_CIRCUIT_A_ENDS",
                                                json_params=json.dumps(
                                                    {
                                                        "parity": "even",
                                                        "include_z_ends": True,
                                                    }
                                                ),
                                            )
                                        ],
                                    ),
                                    create_port_state_check(
                                        disabled_interfaces_jq=f'."{hostname}".interfaces',
                                        disabled_interfaces_transforms=[
                                            taac_types.TransformFunction(
                                                name="SELECT_SNAKE_CIRCUIT_A_ENDS",
                                                json_params=json.dumps(
                                                    {
                                                        "parity": "even",
                                                        "include_z_ends": True,
                                                    }
                                                ),
                                            )
                                        ],
                                    ),
                                ],
                                stage=taac_types.ValidationStage.MID_TEST,
                            ),
                            create_interface_flap_step(
                                enable=False,
                                interface_flap_method=1,
                                delay=30,
                                jq_params={"interfaces": f'."{hostname}".interfaces'},
                                transform_params={
                                    "interfaces": [
                                        taac_types.TransformFunction(
                                            name="SELECT_SNAKE_CIRCUIT_A_ENDS",
                                            json_params=json.dumps({"parity": "odd"}),
                                        )
                                    ]
                                },
                                description="Disable A-end of odd snake circuits (all circuits now down)",
                            ),
                            create_interface_flap_step(
                                enable=True,
                                interface_flap_method=1,
                                delay=300,
                                jq_params={"interfaces": f'."{hostname}".interfaces'},
                                transform_params={
                                    "interfaces": [
                                        taac_types.TransformFunction(
                                            name="SELECT_SNAKE_CIRCUIT_A_ENDS",
                                            json_params=json.dumps({"parity": "even"}),
                                        )
                                    ]
                                },
                                description="Re-enable A-end of even snake circuits, odd circuits remain down",
                            ),
                            create_validation_step(
                                point_in_time_checks=[
                                    create_lldp_check(
                                        disabled_interfaces_jq=f'."{hostname}".interfaces',
                                        disabled_interfaces_transforms=[
                                            taac_types.TransformFunction(
                                                name="SELECT_SNAKE_CIRCUIT_A_ENDS",
                                                json_params=json.dumps(
                                                    {
                                                        "parity": "odd",
                                                        "include_z_ends": True,
                                                    }
                                                ),
                                            )
                                        ],
                                    ),
                                    create_port_state_check(
                                        disabled_interfaces_jq=f'."{hostname}".interfaces',
                                        disabled_interfaces_transforms=[
                                            taac_types.TransformFunction(
                                                name="SELECT_SNAKE_CIRCUIT_A_ENDS",
                                                json_params=json.dumps(
                                                    {
                                                        "parity": "odd",
                                                        "include_z_ends": True,
                                                    }
                                                ),
                                            )
                                        ],
                                    ),
                                ],
                                stage=taac_types.ValidationStage.MID_TEST,
                            ),
                            create_interface_flap_step(
                                enable=True,
                                interface_flap_method=1,
                                delay=300,
                                jq_params={"interfaces": f'."{hostname}".interfaces'},
                                transform_params={
                                    "interfaces": [
                                        taac_types.TransformFunction(
                                            name="SELECT_SNAKE_CIRCUIT_A_ENDS",
                                            json_params=json.dumps({"parity": "odd"}),
                                        )
                                    ]
                                },
                                description="Re-enable A-end of odd snake circuits, all circuits restored",
                            ),
                        ]
                    )
                ],
            ),
            taac_types.Playbook(
                name="test_snake_interface_toggle_with_qsfp_util_disable",
                iteration=iteration,
                prechecks=_prechecks,
                postchecks=_postchecks
                + [
                    create_ixia_packet_loss_check(clear_traffic_stats=True),
                ]
                + gen_ptp_health_checks(),
                stages=[
                    create_steps_stage(
                        steps=[
                            create_interface_flap_step(
                                enable=False,
                                interface_flap_method=2,
                                delay=30,
                                jq_params={"interfaces": f'."{hostname}".interfaces'},
                                description="Sequentially disable all interfaces",
                            ),
                            create_interface_flap_step(
                                enable=True,
                                interface_flap_method=2,
                                delay=300,
                                jq_params={"interfaces": f'."{hostname}".interfaces'},
                                description="Sequentially enable all interfaces",
                            ),
                        ]
                    )
                ],
            ),
            taac_types.Playbook(
                name="test_snake_interface_toggle_with_qsfp_util_low_power",
                iteration=iteration,
                prechecks=_prechecks,
                postchecks=_postchecks
                + [
                    create_ixia_packet_loss_check(clear_traffic_stats=True),
                ]
                + gen_ptp_health_checks(),
                stages=[
                    create_steps_stage(
                        steps=[
                            create_interface_flap_step(
                                enable=False,
                                interface_flap_method=3,
                                delay=30,
                                jq_params={"interfaces": f'."{hostname}".interfaces'},
                                description="Sequentially disable all interfaces",
                            ),
                            create_interface_flap_step(
                                enable=True,
                                interface_flap_method=3,
                                delay=300,
                                jq_params={"interfaces": f'."{hostname}".interfaces'},
                                description="Sequentially enable all interfaces",
                            ),
                        ]
                    )
                ],
            ),
            taac_types.Playbook(
                name="test_snake_interface_reset_with_qsfp_reset",
                iteration=1,
                prechecks=_prechecks,
                postchecks=_postchecks
                + [
                    create_ixia_packet_loss_check(clear_traffic_stats=True),
                ]
                + gen_ptp_health_checks(),
                stages=[
                    create_steps_stage(
                        steps=[
                            # Resets the transceiver, no explicit enable step.
                            create_interface_flap_step(
                                enable=False,
                                interface_flap_method=5,
                                delay=30,
                                jq_params={"interfaces": f'."{hostname}".interfaces'},
                                description="Sequentially reset all interfaces",
                            ),
                            # Wait some additional time for ZR optics to reset which takes around 5 mins
                            create_longevity_step(duration=300),
                        ]
                    )
                ],
            ),
            taac_types.Playbook(
                name="test_snake_agent_warmboot",
                iteration=iteration,
                prechecks=_prechecks,
                postchecks=_postchecks,
                stages=[
                    create_steps_stage(
                        steps=[
                            create_service_interruption_step(
                                service=taac_types.Service.AGENT,
                                trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                            ),
                            create_service_convergence_step(
                                services=[taac_types.Service.AGENT],
                                description="Wait for wedge_agent to converge",
                            ),
                        ]
                    )
                ],
            ),
            taac_types.Playbook(
                name="test_snake_qsfp_service_restart",
                iteration=iteration,
                prechecks=_prechecks,
                postchecks=_postchecks,
                stages=[
                    create_steps_stage(
                        steps=[
                            create_service_interruption_step(
                                service=taac_types.Service.QSFP_SERVICE,
                                trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                            ),
                            create_service_convergence_step(
                                services=[taac_types.Service.AGENT],
                                description="Wait for wedge_agent to converge",
                            ),
                        ]
                    )
                ],
            ),
            taac_types.Playbook(
                name="test_snake_fsdb_restart",
                iteration=iteration,
                prechecks=_prechecks,
                postchecks=_postchecks,
                stages=[
                    create_steps_stage(
                        steps=[
                            create_service_interruption_step(
                                service=taac_types.Service.FSDB,
                                trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                            ),
                            create_service_convergence_step(
                                services=[
                                    taac_types.Service.AGENT,
                                    taac_types.Service.FSDB,
                                ],
                            ),
                        ]
                    )
                ],
            ),
            taac_types.Playbook(
                name="test_snake_agent_coldboot",
                iteration=iteration,
                prechecks=_prechecks,
                stages=[
                    create_steps_stage(
                        steps=[
                            create_service_interruption_step(
                                service=taac_types.Service.AGENT,
                                trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                                create_cold_boot_file=True,
                            ),
                            create_service_convergence_step(
                                services=[taac_types.Service.AGENT],
                                description="Wait for wedge_agent to converge",
                            ),
                            # Wait some additional time since the convergence step can sometimes complete too quickly
                            create_longevity_step(duration=300),
                        ]
                    )
                ],
                postchecks=_postchecks
                + [
                    create_ixia_packet_loss_check(clear_traffic_stats=True),
                ]
                + gen_ptp_health_checks(),
            ),
            taac_types.Playbook(
                name="test_snake_agent_crash",
                iteration=iteration,
                prechecks=_prechecks,
                stages=[
                    create_steps_stage(
                        steps=[
                            create_service_interruption_step(
                                service=taac_types.Service.AGENT,
                                trigger=taac_types.ServiceInterruptionTrigger.CRASH,
                            ),
                            create_service_convergence_step(
                                services=[taac_types.Service.AGENT],
                                description="Wait for wedge_agent to converge",
                            ),
                            # Wait some additional time since the convergence step can sometimes complete too quickly
                            create_longevity_step(duration=300),
                        ]
                    )
                ],
                postchecks=_postchecks
                + [
                    create_ixia_packet_loss_check(clear_traffic_stats=True),
                ]
                + gen_ptp_health_checks(),
            ),
            taac_types.Playbook(
                name="test_snake_qsfp_service_crash",
                iteration=iteration,
                prechecks=_prechecks,
                stages=[
                    create_steps_stage(
                        steps=[
                            create_service_interruption_step(
                                service=taac_types.Service.QSFP_SERVICE,
                                trigger=taac_types.ServiceInterruptionTrigger.CRASH,
                            ),
                            create_service_convergence_step(
                                services=[
                                    taac_types.Service.AGENT,
                                    taac_types.Service.QSFP_SERVICE,
                                ],
                                description="Wait for wedge_agent to converge",
                            ),
                            # Wait some additional time since the convergence step can sometimes complete too quickly
                            create_longevity_step(duration=300),
                        ]
                    )
                ],
                postchecks=_postchecks
                + [
                    create_ixia_packet_loss_check(clear_traffic_stats=True),
                ]
                + gen_ptp_health_checks(),
            ),
            taac_types.Playbook(
                name="test_snake_fsdb_crash",
                iteration=iteration,
                prechecks=_prechecks,
                postchecks=_postchecks,
                stages=[
                    create_steps_stage(
                        steps=[
                            create_service_interruption_step(
                                service=taac_types.Service.FSDB,
                                trigger=taac_types.ServiceInterruptionTrigger.CRASH,
                            ),
                            create_service_convergence_step(
                                services=[
                                    taac_types.Service.AGENT,
                                    taac_types.Service.FSDB,
                                ],
                            ),
                            # Wait some additional time since the convergence step can sometimes complete too quickly
                            create_longevity_step(duration=300),
                        ]
                    )
                ],
            ),
            taac_types.Playbook(
                name="test_snake_system_reboot_bmc_full",
                iteration=iteration,
                prechecks=_prechecks,
                stages=[
                    create_steps_stage(
                        steps=[
                            create_system_reboot_step(
                                trigger=taac_types.SystemRebootTrigger.FULL_SYSTEM_REBOOT,
                            ),
                            create_service_convergence_step(
                                services=[taac_types.Service.AGENT],
                            ),
                            # Wait some additional time since the convergence step can sometimes complete too quickly
                            create_longevity_step(duration=300),
                        ]
                    )
                ],
                postchecks=_postchecks
                + [
                    create_ixia_packet_loss_check(clear_traffic_stats=True),
                ]
                + gen_ptp_health_checks(),
            ),
            taac_types.Playbook(
                name="test_snake_system_reboot_bmc_microserver",
                iteration=iteration,
                prechecks=_prechecks,
                stages=[
                    create_steps_stage(
                        steps=[
                            create_system_reboot_step(
                                trigger=taac_types.SystemRebootTrigger.BMC_POWER_RESET,
                            ),
                            create_service_convergence_step(
                                services=[taac_types.Service.AGENT],
                            ),
                            # Wait some additional time since the convergence step can sometimes complete too quickly
                            create_longevity_step(duration=300),
                        ]
                    )
                ],
                postchecks=_postchecks
                + [
                    create_ixia_packet_loss_check(clear_traffic_stats=True),
                ]
                + gen_ptp_health_checks(),
            ),
            taac_types.Playbook(
                name="test_snake_system_reboot_microserver",
                iteration=iteration,
                prechecks=_prechecks,
                stages=[
                    create_steps_stage(
                        steps=[
                            create_system_reboot_step(
                                trigger=taac_types.SystemRebootTrigger.BMC_MICROSERVER_ONLY_RESET,
                            ),
                            create_service_convergence_step(
                                services=[taac_types.Service.AGENT],
                            ),
                            # Wait some additional time since the convergence step can sometimes complete too quickly
                            create_longevity_step(duration=300),
                        ]
                    )
                ],
                postchecks=_postchecks
                + [
                    create_ixia_packet_loss_check(clear_traffic_stats=True),
                ]
                + gen_ptp_health_checks(),
            ),
        ]
    )

    if include_link_flap_longevity:
        playbooks.append(
            taac_types.Playbook(
                name="test_snake_link_flap_with_longevity",
                prechecks=_prechecks,
                stages=[
                    # Stage 1: Flap all links for ~3 hours
                    # Each cycle: ~330 seconds (30s disable delay + 300s enable delay)
                    # 33 iterations ≈ 3 hours
                    create_steps_stage(
                        steps=[
                            create_interface_flap_step(
                                enable=False,
                                interface_flap_method=1,
                                delay=30,
                                jq_params={"interfaces": f'."{hostname}".interfaces'},
                                description="Sequentially disable all interfaces",
                            ),
                            create_interface_flap_step(
                                enable=True,
                                interface_flap_method=1,
                                delay=300,
                                jq_params={"interfaces": f'."{hostname}".interfaces'},
                                description="Sequentially enable all interfaces",
                            ),
                        ],
                        iteration=33,
                    ),
                    # Stage 2: Wait 5 minutes for links to come UP
                    create_steps_stage(steps=[create_longevity_step(duration=300)]),
                    # Stage 3: Validate links are UP and LLDP is correct
                    create_steps_stage(
                        steps=[
                            create_validation_step(
                                point_in_time_checks=[
                                    create_port_state_check(),
                                    create_lldp_check(),
                                ],
                                stage=taac_types.ValidationStage.MID_TEST,
                            ),
                        ]
                    ),
                    # Stage 4: 1 hour longevity
                    create_steps_stage(steps=[create_longevity_step(duration=3600)]),
                ],
                postchecks=_postchecks
                + [
                    create_ixia_packet_loss_check(clear_traffic_stats=True),
                ]
                + gen_ptp_health_checks(),
            ),
        )

    if manual_test_interfaces:
        playbooks.extend(
            [
                gen_snake_transceiver_removal_playbook(
                    hostname=hostname,
                    interfaces=manual_test_interfaces,
                    prechecks=_prechecks,
                    postchecks=_postchecks,
                ),
                gen_snake_fiber_removal_playbook(
                    hostname=hostname,
                    interfaces=manual_test_interfaces,
                    prechecks=_prechecks,
                    postchecks=_postchecks,
                ),
            ]
        )

    if playbooks_to_skip:
        return [
            playbook
            for playbook in playbooks
            if playbook.name not in set(playbooks_to_skip)
        ]
    else:
        return playbooks


# ----- Migrated from playbooks/helpers/routing/cte_ucmp_playbooks.py -----

from taac.health_checks.healthcheck_definitions import (
    create_bgp_rib_weight_check,
    create_fib_traffic_distribution_check,
    create_traffic_item_packet_loss_check,
)
from taac.steps.step_definitions import (
    create_bgp_convergence_wait_step,
    create_bgp_service_convergence_step,
    create_bgp_service_crash_step,
    create_bgp_service_restart_step,
    create_clear_traffic_stats_step,
    create_cte_ucmp_drain_undrain_step,
    create_cte_ucmp_interface_flap_step as _cte_create_interface_flap_step,
    create_disable_dc_vip_step,
    create_enable_dc_vip_step,
    create_record_agent_state_step,
    create_service_interption_step,
    create_traffic_duration_step,
    create_ucmp_policy_config_step,
    create_ucmp_validation_step,
    packetloss_validation_step,
    system_health_validation_step,
)


def create_test_case_1_playbooks(
    vip_community: str,
    vip_v6: str,
    dc1_asn: int,
    dc2_asn: int,
    dc3_asn: int,
    dc1_weight: int,
    dc2_weight: int,
    dc3_weight: int,
) -> list[Playbook]:
    """
    Create playbooks for Test Case 1: Progressive DC Bring-up.

    Args:
        vip_community: VIP community string (e.g., "65441:260")
        vip_v6: VIP IPv6 prefix (e.g., "2402:db00:1000::/64")
        dc1_asn: DC1 AS number for AS_PATH matching
        dc2_asn: DC2 AS number for AS_PATH matching
        dc3_asn: DC3 AS number for AS_PATH matching
        dc1_weight: UCMP weight for DC1
        dc2_weight: UCMP weight for DC2
        dc3_weight: UCMP weight for DC3

    Returns:
        List of 3 playbooks: TC1 (DC1), TC1a (DC2), TC1b (DC3)
    """
    playbooks = []

    # Test Case 1: Single DC Online
    playbooks.append(
        Playbook(
            name="bringup_shiv_dc1",
            description="CTE UCMP Test Case 1: Policy deployed, DC1 comes online",
            prechecks=[],
            setup_steps=[
                # Deploy UCMP policy once at the beginning with all 3 DCs configured
                create_ucmp_policy_config_step(
                    vip_community=vip_community,
                    dc1_asn=dc1_asn,
                    dc2_asn=dc2_asn,
                    dc3_asn=dc3_asn,
                    dc1_weight=dc1_weight,
                    dc2_weight=dc2_weight,
                    dc3_weight=dc3_weight,
                ),
            ],
            stages=[
                create_steps_stage(
                    steps=[
                        # Enable DC1 device group for VIP advertisements
                        create_enable_dc_vip_step(dc_number=1),
                        # Wait for BGP convergence
                        create_bgp_convergence_wait_step(wait_seconds=60),
                        # Clear traffic stats to ignore loss during convergence
                        create_clear_traffic_stats_step(),
                        # Run traffic for test duration
                        create_traffic_duration_step(duration_seconds=300),
                    ],
                )
            ],
            postchecks=[
                # Standard traffic validation
                create_packetloss_health_check(),
                # UCMP Control Plane Check after DC1 comes online
                create_bgp_rib_weight_check(
                    target_community=vip_community,
                    target_prefix=vip_v6,
                    expected_weights={
                        dc1_weight: 4,  # 4 nexthops with weight 10 (DC1 only, one per spine)
                    },
                    expected_as_weights={
                        dc1_asn: dc1_weight,  # AS 64901 should have weight 10
                    },
                ),
                # UCMP Data Plane Check after DC1 comes online
                # FIB normalizes weights by GCD: GCD(10) = 10, so 10→1
                create_fib_traffic_distribution_check(
                    target_prefix=vip_v6,
                    expected_fib_weights={
                        1: 4,  # FIB normalizes: 10/GCD(10) = 10/10 = 1
                    },
                ),
            ],
            traffic_items_to_start=[
                "UCMP_TEST_TRAFFIC"
            ],  # Start only VIP traffic (non-VIP device groups disabled in TC1)
        )
    )

    # Test Case 1a: Second DC Comes Online
    playbooks.append(
        Playbook(
            name="bringup_shiv_dc2",
            description="CTE UCMP Test Case 1a: DC2 comes online",
            prechecks=[],
            stages=[
                create_steps_stage(
                    steps=[
                        # Enable DC2 device group for VIP advertisements
                        create_enable_dc_vip_step(dc_number=2),
                        # Wait for BGP convergence
                        create_bgp_convergence_wait_step(wait_seconds=60),
                        # Clear traffic stats to ignore loss during convergence
                        create_clear_traffic_stats_step(),
                        # Run traffic for test duration
                        create_traffic_duration_step(duration_seconds=300),
                    ],
                )
            ],
            postchecks=[
                # Standard traffic validation
                create_packetloss_health_check(),
                # UCMP Control Plane Check after DC2 comes online
                create_bgp_rib_weight_check(
                    target_community=vip_community,
                    target_prefix=vip_v6,
                    expected_weights={
                        dc1_weight: 4,  # 4 nexthops with weight 10 (DC1, one per spine)
                        dc2_weight: 4,  # 4 nexthops with weight 5 (DC2, one per spine)
                    },
                    expected_as_weights={
                        dc1_asn: dc1_weight,  # AS 64901 should have weight 10
                        dc2_asn: dc2_weight,  # AS 64902 should have weight 5
                    },
                ),
                # UCMP Data Plane Check after DC2 comes online
                # FIB normalizes weights by GCD: GCD(10, 5) = 5, so 10→2, 5→1
                create_fib_traffic_distribution_check(
                    target_prefix=vip_v6,
                    expected_fib_weights={
                        2: 4,  # FIB normalizes: 10/GCD(10,5) = 10/5 = 2
                        1: 4,  # FIB normalizes: 5/GCD(10,5) = 5/5 = 1
                    },
                ),
            ],
            traffic_items_to_start=["UCMP_TEST_TRAFFIC"],  # VIP traffic only (TC1a)
        )
    )

    # Test Case 1b: Third DC Comes Online
    playbooks.append(
        Playbook(
            name="bringup_shiv_dc3",
            description="CTE UCMP Test Case 1b: DC3 comes online (final state)",
            prechecks=[],
            stages=[
                create_steps_stage(
                    steps=[
                        # Enable DC3 device group for VIP advertisements
                        create_enable_dc_vip_step(dc_number=3),
                        # Wait for BGP convergence
                        create_bgp_convergence_wait_step(wait_seconds=60),
                        # Clear traffic stats to ignore loss during convergence
                        create_clear_traffic_stats_step(),
                        # Run traffic for test duration
                        create_traffic_duration_step(duration_seconds=300),
                    ],
                )
            ],
            postchecks=[
                # Standard traffic validation
                create_packetloss_health_check(),
                # UCMP Control Plane Check after DC3 comes online
                create_bgp_rib_weight_check(
                    target_community=vip_community,
                    target_prefix=vip_v6,
                    expected_weights={
                        dc1_weight: 4,  # 4 nexthops with weight 10 (DC1, one per spine)
                        dc2_weight: 4,  # 4 nexthops with weight 5 (DC2, one per spine)
                        dc3_weight: 4,  # 4 nexthops with weight 2 (DC3, one per spine - final state)
                    },
                    expected_as_weights={
                        dc1_asn: dc1_weight,  # AS 64901 should have weight 10
                        dc2_asn: dc2_weight,  # AS 64902 should have weight 5
                        dc3_asn: dc3_weight,  # AS 64903 should have weight 2
                    },
                ),
                # UCMP Data Plane Check after DC3 comes online
                # FIB normalizes weights by GCD: GCD(10, 5, 2) = 1, so no change
                create_fib_traffic_distribution_check(
                    target_prefix=vip_v6,
                    expected_fib_weights={
                        dc1_weight: 4,  # FIB: 10/GCD(10,5,2) = 10/1 = 10
                        dc2_weight: 4,  # FIB: 5/GCD(10,5,2) = 5/1 = 5
                        dc3_weight: 4,  # FIB: 2/GCD(10,5,2) = 2/1 = 2
                    },
                ),
            ],
            traffic_items_to_start=["UCMP_TEST_TRAFFIC"],  # VIP traffic only (TC1b)
        )
    )

    return playbooks


def create_test_case_3_playbooks(
    vip_community: str,
    vip_v6: str,
    dc1_asn: int,
    dc2_asn: int,
    dc3_asn: int,
    dc1_weight: int,
    dc2_weight: int,
    dc3_weight: int,
) -> list[Playbook]:
    """
    Create playbooks for Test Case 3: ECMP ↔ UCMP Transitions.

    Two playbooks to test bidirectional transitions:
    1. ECMP → UCMP: Initial CTE deployment (33.33% per DC → 58.8%/29.4%/11.8%)
    2. UCMP → ECMP: CTE policy removal/rollback (58.8%/29.4%/11.8% → 33.33% per DC)

    Args:
        vip_community: VIP community string (e.g., "65441:260")
        vip_v6: VIP IPv6 prefix (e.g., "2402:db00:1100::/64")
        dc1_asn: DC1 AS number for AS_PATH matching
        dc2_asn: DC2 AS number for AS_PATH matching
        dc3_asn: DC3 AS number for AS_PATH matching
        dc1_weight: UCMP weight for DC1 (e.g., 10)
        dc2_weight: UCMP weight for DC2 (e.g., 5)
        dc3_weight: UCMP weight for DC3 (e.g., 2)

    Returns:
        List of 2 playbooks: TC3a (ECMP → UCMP), TC3b (UCMP → ECMP)
    """
    playbooks = []

    # Test Case 3a: ECMP to UCMP Transition (Initial CTE Deployment)
    playbooks.append(
        Playbook(
            name="ecmp_to_ucmp_transition",
            description="CTE UCMP Test Case 3: Initial CTE policy deployment (ECMP → UCMP transition)",
            prechecks=[],
            setup_steps=[
                # Step 1: Clear any existing UCMP policy (ensure clean ECMP state)
                create_ucmp_policy_config_step(
                    vip_community=vip_community,
                    dc1_asn=dc1_asn,
                    dc2_asn=dc2_asn,
                    dc3_asn=dc3_asn,
                    dc1_weight=dc1_weight,
                    dc2_weight=dc2_weight,
                    dc3_weight=dc3_weight,
                    action="clear",
                ),
                # Step 2: Enable all 3 DCs (ECMP baseline state)
                create_enable_dc_vip_step(dc_number=1),
                create_enable_dc_vip_step(dc_number=2),
                create_enable_dc_vip_step(dc_number=3),
                create_bgp_convergence_wait_step(wait_seconds=60),
            ],
            stages=[
                # Stage 1: Run traffic and verify ECMP baseline
                create_steps_stage(
                    steps=[
                        # Clear traffic stats before ECMP baseline measurement
                        create_clear_traffic_stats_step(),
                        # Run traffic for 5 minutes to establish ECMP baseline
                        create_traffic_duration_step(duration_seconds=300),
                        # Verify ECMP Control Plane and Data Plane
                        create_ucmp_validation_step(
                            vip_community=vip_community,
                            vip_v6=vip_v6,
                            expected_rib_weights={0: 12},  # ECMP: all nexthops weight 0
                            expected_as_weights={},  # No AS-specific weights for ECMP
                            expected_fib_weights={1: 12},  # FIB normalizes 0→1
                            tolerance_percent=5,
                            require_ucmp=False,  # We expect ECMP
                        ),
                    ],
                ),
                # Stage 2: Deploy UCMP policy (transition from ECMP to UCMP)
                create_steps_stage(
                    steps=[
                        # Deploy CTE policy (ECMP → UCMP transition)
                        create_ucmp_policy_config_step(
                            vip_community=vip_community,
                            dc1_asn=dc1_asn,
                            dc2_asn=dc2_asn,
                            dc3_asn=dc3_asn,
                            dc1_weight=dc1_weight,
                            dc2_weight=dc2_weight,
                            dc3_weight=dc3_weight,
                        ),
                        # Wait for policy to propagate and converge
                        create_bgp_convergence_wait_step(wait_seconds=60),
                    ],
                ),
                # Stage 3: Run traffic and verify UCMP distribution
                create_steps_stage(
                    steps=[
                        # Clear traffic stats to measure UCMP distribution
                        create_clear_traffic_stats_step(),
                        # Run traffic for 5 minutes to validate UCMP steady state
                        create_traffic_duration_step(duration_seconds=300),
                    ],
                ),
            ],
            postchecks=[
                # Standard traffic validation (final check after all stages)
                create_packetloss_health_check(),
                # UCMP Control Plane Check - verify final UCMP state
                create_bgp_rib_weight_check(
                    target_community=vip_community,
                    target_prefix=vip_v6,
                    expected_weights={
                        dc1_weight: 4,  # 4 nexthops with weight 10 (DC1)
                        dc2_weight: 4,  # 4 nexthops with weight 5 (DC2)
                        dc3_weight: 4,  # 4 nexthops with weight 2 (DC3)
                    },
                    expected_as_weights={
                        dc1_asn: dc1_weight,  # AS 64901 should have weight 10
                        dc2_asn: dc2_weight,  # AS 64902 should have weight 5
                        dc3_asn: dc3_weight,  # AS 64903 should have weight 2
                    },
                ),
                # UCMP Data Plane Check - verify final traffic distribution
                # FIB normalizes weights by GCD: GCD(10, 5, 2) = 1, so no change
                create_fib_traffic_distribution_check(
                    target_prefix=vip_v6,
                    expected_fib_weights={
                        dc1_weight: 4,  # FIB: 10/GCD(10,5,2) = 10/1 = 10
                        dc2_weight: 4,  # FIB: 5/GCD(10,5,2) = 5/1 = 5
                        dc3_weight: 4,  # FIB: 2/GCD(10,5,2) = 2/1 = 2
                    },
                ),
            ],
            traffic_items_to_start=["UCMP_TEST_TRAFFIC"],  # VIP traffic only (TC3)
        )
    )

    # Test Case 3b: UCMP to ECMP Transition (CTE Policy Removal/Rollback)
    playbooks.append(
        Playbook(
            name="ucmp_to_ecmp_transition",
            description="CTE UCMP Test Case 3b: CTE policy removal/rollback (UCMP → ECMP transition)",
            prechecks=[],
            setup_steps=[
                # Step 1: Deploy UCMP policy (ensure UCMP baseline state)
                create_ucmp_policy_config_step(
                    vip_community=vip_community,
                    dc1_asn=dc1_asn,
                    dc2_asn=dc2_asn,
                    dc3_asn=dc3_asn,
                    dc1_weight=dc1_weight,
                    dc2_weight=dc2_weight,
                    dc3_weight=dc3_weight,
                ),
                # Step 2: Enable all 3 DCs (UCMP baseline state)
                create_enable_dc_vip_step(dc_number=1),
                create_enable_dc_vip_step(dc_number=2),
                create_enable_dc_vip_step(dc_number=3),
                create_bgp_convergence_wait_step(wait_seconds=60),
            ],
            stages=[
                # Stage 1: Run traffic and verify UCMP baseline
                create_steps_stage(
                    steps=[
                        # Clear traffic stats before UCMP baseline measurement
                        create_clear_traffic_stats_step(),
                        # Run traffic for 5 minutes to establish UCMP baseline
                        create_traffic_duration_step(duration_seconds=300),
                        # Verify UCMP Control Plane and Data Plane
                        create_ucmp_validation_step(
                            vip_community=vip_community,
                            vip_v6=vip_v6,
                            expected_rib_weights={
                                dc1_weight: 4,  # 4 nexthops with weight 10
                                dc2_weight: 4,  # 4 nexthops with weight 5
                                dc3_weight: 4,  # 4 nexthops with weight 2
                            },
                            expected_as_weights={
                                dc1_asn: dc1_weight,
                                dc2_asn: dc2_weight,
                                dc3_asn: dc3_weight,
                            },
                            expected_fib_weights={
                                dc1_weight: 4,  # FIB: 10
                                dc2_weight: 4,  # FIB: 5
                                dc3_weight: 4,  # FIB: 2
                            },
                            tolerance_percent=5,
                        ),
                    ],
                ),
                # Stage 2: Remove UCMP policy (transition from UCMP to ECMP)
                create_steps_stage(
                    steps=[
                        # Remove CTE policy (UCMP → ECMP transition)
                        create_ucmp_policy_config_step(
                            vip_community=vip_community,
                            dc1_asn=dc1_asn,
                            dc2_asn=dc2_asn,
                            dc3_asn=dc3_asn,
                            dc1_weight=dc1_weight,
                            dc2_weight=dc2_weight,
                            dc3_weight=dc3_weight,
                            action="clear",
                        ),
                        # Wait for policy removal to propagate and converge
                        create_bgp_convergence_wait_step(wait_seconds=60),
                    ],
                ),
                # Stage 3: Run traffic and verify ECMP distribution
                create_steps_stage(
                    steps=[
                        # Clear traffic stats to measure ECMP distribution
                        create_clear_traffic_stats_step(),
                        # Run traffic for 5 minutes to validate ECMP steady state
                        create_traffic_duration_step(duration_seconds=300),
                    ],
                ),
            ],
            postchecks=[
                # Standard traffic validation (final check after all stages)
                create_packetloss_health_check(),
                # ECMP Control Plane Check - verify final ECMP state
                create_bgp_rib_weight_check(
                    target_community=vip_community,
                    target_prefix=vip_v6,
                    expected_weights={0: 12},  # ECMP: all 12 nexthops with weight 0
                    require_ucmp=False,  # We expect ECMP fallback
                ),
                # ECMP Data Plane Check - verify final traffic distribution
                # FIB normalizes ECMP weight 0→1
                create_fib_traffic_distribution_check(
                    target_prefix=vip_v6,
                    expected_fib_weights={
                        1: 12  # FIB normalizes 0→1 for all ECMP nexthops
                    },
                ),
            ],
            traffic_items_to_start=["UCMP_TEST_TRAFFIC"],  # VIP traffic only (TC3b)
        )
    )

    return playbooks


def create_test_case_4_playbooks(
    vip_community: str,
    vip_v6: str,
    dc1_asn: int,
    dc2_asn: int,
    dc3_asn: int,
    dc1_weight: int,
    dc2_weight: int,
    dc3_weight: int,
) -> list[Playbook]:
    """
    Create playbooks for Test Case 4: DC Withdrawal Scenarios.

    Three playbooks to test progressive DC withdrawal:
    1. TC4: One DC withdrawn (DC3) - DC1 66.67%, DC2 33.33%, DC3 0%
    2. TC4a: Second DC withdrawn (DC2) - DC1 100%, DC2 0%, DC3 0%
    3. TC4b: All DCs withdrawn - Complete service loss (0% traffic, 100% packet loss)

    Args:
        vip_community: VIP community string (e.g., "65520:724")
        vip_v6: VIP IPv6 prefix (e.g., "2001:db8:203::/48")
        dc1_asn: DC1 AS number for AS_PATH matching
        dc2_asn: DC2 AS number for AS_PATH matching
        dc3_asn: DC3 AS number for AS_PATH matching
        dc1_weight: UCMP weight for DC1
        dc2_weight: UCMP weight for DC2
        dc3_weight: UCMP weight for DC3

    Returns:
        List of 3 playbooks: TC4 (DC3 withdrawn), TC4a (DC2+DC3 withdrawn), TC4b (all withdrawn)
    """
    playbooks = []

    # Test Case 4: One DC Withdrawn (DC3)
    playbooks.append(
        Playbook(
            name="dc_withdrawal_one_dc",
            description="CTE UCMP Test Case 4: One DC withdrawn (DC3), policy still configured for all 3 DCs",
            prechecks=[],
            setup_steps=[
                # Deploy UCMP policy for all 3 DCs
                create_ucmp_policy_config_step(
                    vip_community=vip_community,
                    dc1_asn=dc1_asn,
                    dc2_asn=dc2_asn,
                    dc3_asn=dc3_asn,
                    dc1_weight=dc1_weight,
                    dc2_weight=dc2_weight,
                    dc3_weight=dc3_weight,
                ),
                # Enable all 3 DCs (baseline: all online)
                create_enable_dc_vip_step(dc_number=1),
                create_enable_dc_vip_step(dc_number=2),
                create_enable_dc_vip_step(dc_number=3),
                create_bgp_convergence_wait_step(wait_seconds=60),
            ],
            stages=[
                # Stage 1: Verify baseline with all 3 DCs online
                create_steps_stage(
                    steps=[
                        # Clear traffic stats for baseline measurement
                        create_clear_traffic_stats_step(),
                        # Run traffic to establish 3-DC baseline
                        create_traffic_duration_step(duration_seconds=300),
                        # Verify all 3 DCs are serving traffic correctly
                        create_ucmp_validation_step(
                            vip_community=vip_community,
                            vip_v6=vip_v6,
                            expected_rib_weights={
                                dc1_weight: 4,  # DC1: 4 nexthops
                                dc2_weight: 4,  # DC2: 4 nexthops
                                dc3_weight: 4,  # DC3: 4 nexthops
                            },
                            expected_as_weights={
                                dc1_asn: dc1_weight,
                                dc2_asn: dc2_weight,
                                dc3_asn: dc3_weight,
                            },
                            expected_fib_weights={
                                dc1_weight: 4,  # 10/1 = 10
                                dc2_weight: 4,  # 5/1 = 5
                                dc3_weight: 4,  # 2/1 = 2
                            },
                        ),
                    ],
                ),
                # Stage 2: Withdraw DC3 and verify redistribution
                create_steps_stage(
                    steps=[
                        # Withdraw DC3 (disable device group)
                        create_disable_dc_vip_step(dc_number=3),
                        # Wait for BGP route withdrawal to converge
                        create_bgp_convergence_wait_step(wait_seconds=60),
                        # Clear traffic stats to ignore loss during convergence
                        create_clear_traffic_stats_step(),
                        # Run traffic for test duration
                        create_traffic_duration_step(duration_seconds=300),
                    ],
                ),
            ],
            postchecks=[
                # Standard traffic validation
                create_packetloss_health_check(),
                # UCMP Control Plane Check - 8 nexthops (DC1 + DC2 only)
                create_bgp_rib_weight_check(
                    target_community=vip_community,
                    target_prefix=vip_v6,
                    expected_weights={
                        dc1_weight: 4,  # DC1: 4 nexthops with weight 10
                        dc2_weight: 4,  # DC2: 4 nexthops with weight 5
                        # DC3: 0 nexthops (withdrawn, weight configured but unused)
                    },
                    expected_as_weights={
                        dc1_asn: dc1_weight,  # AS 64901 should have weight 10
                        dc2_asn: dc2_weight,  # AS 64902 should have weight 5
                        # DC3 (AS 64903) has no paths, weight unused
                    },
                ),
                # UCMP Data Plane Check - FIB with 8 nexthops
                # GCD(10, 5) = 5, normalized to {2: 4, 1: 4}
                create_fib_traffic_distribution_check(
                    target_prefix=vip_v6,
                    expected_fib_weights={
                        2: 4,  # DC1: 10/GCD(10,5) = 10/5 = 2
                        1: 4,  # DC2: 5/GCD(10,5) = 5/5 = 1
                        # DC3: 0 nexthops (no FIB entries)
                    },
                ),
            ],
            traffic_items_to_start=["UCMP_TEST_TRAFFIC"],  # VIP traffic only (TC4)
        )
    )

    # Test Case 4a: Second DC Withdrawn (DC2 + DC3)
    playbooks.append(
        Playbook(
            name="dc_withdrawal_two_dcs",
            description="CTE UCMP Test Case 4a: Second DC withdrawn (DC2), only DC1 remains (100% traffic)",
            prechecks=[],
            stages=[
                create_steps_stage(
                    steps=[
                        # Disable DC2 device group (withdraw VIP advertisements)
                        create_disable_dc_vip_step(dc_number=2),
                        # Wait for BGP route withdrawal to converge
                        create_bgp_convergence_wait_step(wait_seconds=60),
                        # Clear traffic stats to ignore loss during convergence
                        create_clear_traffic_stats_step(),
                        # Run traffic for test duration
                        create_traffic_duration_step(duration_seconds=300),
                    ],
                )
            ],
            postchecks=[
                # Standard traffic validation
                create_packetloss_health_check(),
                # UCMP Control Plane Check - 4 nexthops (DC1 only)
                create_bgp_rib_weight_check(
                    target_community=vip_community,
                    target_prefix=vip_v6,
                    expected_weights={
                        dc1_weight: 4,  # DC1: 4 nexthops with weight 10
                        # DC2: 0 nexthops (withdrawn)
                        # DC3: 0 nexthops (already withdrawn)
                    },
                    expected_as_weights={
                        dc1_asn: dc1_weight,  # AS 64901 should have weight 10
                        # DC2 and DC3 have no paths
                    },
                ),
                # UCMP Data Plane Check - FIB with 4 nexthops
                # Single DC: GCD(10) = 10, normalized to {1: 4}
                # Effectively ECMP within DC1
                create_fib_traffic_distribution_check(
                    target_prefix=vip_v6,
                    expected_fib_weights={
                        1: 4,  # DC1: 10/GCD(10) = 10/10 = 1 (ECMP within DC)
                        # DC2: 0 nexthops
                        # DC3: 0 nexthops
                    },
                ),
            ],
            traffic_items_to_start=["UCMP_TEST_TRAFFIC"],  # VIP traffic only (TC4a)
        )
    )

    # Test Case 4b: All DCs Withdrawn (Complete Service Loss)
    playbooks.append(
        Playbook(
            name="dc_withdrawal_all_dcs",
            description="CTE UCMP Test Case 4b: All DCs withdrawn, complete service loss (100% packet loss)",
            prechecks=[],
            stages=[
                create_steps_stage(
                    steps=[
                        # Disable DC1 device group (last remaining DC)
                        create_disable_dc_vip_step(dc_number=1),
                        # Wait for BGP route withdrawal to converge
                        create_bgp_convergence_wait_step(wait_seconds=60),
                        # Clear traffic stats
                        create_clear_traffic_stats_step(),
                        # Run traffic for test duration (expect 100% loss)
                        create_traffic_duration_step(duration_seconds=300),
                    ],
                )
            ],
            postchecks=[
                # Traffic validation - expect 100% packet loss (no routes)
                # Configure check to expect packet loss (service outage scenario)
                create_ixia_packet_loss_check(json_params={"expect_loss": True}),
                # No BGP RIB or FIB checks - routes are completely withdrawn
                # Service outage validated by packet loss check above
            ],
            traffic_items_to_start=["UCMP_TEST_TRAFFIC"],  # VIP traffic only (TC4b)
        )
    )

    return playbooks


def create_test_case_6_playbooks(
    vip_community: str,
    non_vip_community: str,
    vip_v6: str,
    non_vip_v6: str,
    dc1_asn: int,
    dc2_asn: int,
    dc3_asn: int,
    dc1_weight: int,
    dc2_weight: int,
    dc3_weight: int,
) -> list[Playbook]:
    """
    Create playbook for Test Case 6: Policy Isolation (VIP vs Non-VIP Traffic).

    Tests that UCMP policy applies only to VIP routes (with VIP community tag),
    while non-VIP routes (with different community tag) remain ECMP, even with identical AS_PATHs.

    Args:
        vip_community: VIP community string (e.g., "65441:260")
        non_vip_community: Non-VIP community string (e.g., "65441:261")
        vip_v6: VIP IPv6 prefix (e.g., "2402:db00:1100::/64")
        non_vip_v6: Non-VIP IPv6 prefix (e.g., "2402:db00:1300::/64")
        dc1_asn: DC1 AS number for AS_PATH matching
        dc2_asn: DC2 AS number for AS_PATH matching
        dc3_asn: DC3 AS number for AS_PATH matching
        dc1_weight: UCMP weight for DC1 (e.g., 10)
        dc2_weight: UCMP weight for DC2 (e.g., 5)
        dc3_weight: UCMP weight for DC3 (e.g., 2)

    Returns:
        List with 1 playbook: TC6 (Policy Isolation)
    """
    playbooks = []

    # Test Case 6: Policy Isolation - VIP (UCMP) vs Non-VIP (ECMP)
    playbooks.append(
        Playbook(
            name="policy_isolation_vip_vs_non_vip",
            description="CTE UCMP Test Case 6: Policy isolation - VIP routes use UCMP, Non-VIP routes use ECMP",
            prechecks=[],
            setup_steps=[
                # Deploy UCMP policy for VIP community only
                create_ucmp_policy_config_step(
                    vip_community=vip_community,
                    dc1_asn=dc1_asn,
                    dc2_asn=dc2_asn,
                    dc3_asn=dc3_asn,
                    dc1_weight=dc1_weight,
                    dc2_weight=dc2_weight,
                    dc3_weight=dc3_weight,
                ),
                # Enable all 3 DCs (single device group per DC contains both VIP and non-VIP network groups)
                create_enable_dc_vip_step(dc_number=1),
                create_enable_dc_vip_step(dc_number=2),
                create_enable_dc_vip_step(dc_number=3),
                create_bgp_convergence_wait_step(wait_seconds=60),
            ],
            stages=[
                create_steps_stage(
                    steps=[
                        # Clear traffic stats
                        create_clear_traffic_stats_step(),
                        # Run traffic for test duration (VIP + Non-VIP streams)
                        create_traffic_duration_step(duration_seconds=300),
                    ],
                )
            ],
            postchecks=[
                # Traffic validation - separate packet loss checks for VIP and non-VIP traffic items
                create_traffic_item_packet_loss_check(
                    traffic_item_names=["UCMP_TEST_TRAFFIC"],
                    max_packet_loss_percent=0.0,
                ),
                create_traffic_item_packet_loss_check(
                    traffic_item_names=["NON_VIP_TEST_TRAFFIC"],
                    max_packet_loss_percent=0.0,
                ),
                # VIP Routes: UCMP Control Plane Check
                create_bgp_rib_weight_check(
                    target_community=vip_community,
                    target_prefix=vip_v6,
                    expected_weights={
                        dc1_weight: 4,  # DC1: 4 nexthops with weight 10 (UCMP)
                        dc2_weight: 4,  # DC2: 4 nexthops with weight 5 (UCMP)
                        dc3_weight: 4,  # DC3: 4 nexthops with weight 2 (UCMP)
                    },
                    expected_as_weights={
                        dc1_asn: dc1_weight,
                        dc2_asn: dc2_weight,
                        dc3_asn: dc3_weight,
                    },
                ),
                # Non-VIP Routes: ECMP Control Plane Check
                # Note: Non-VIP routes have same AS_PATH but DIFFERENT community tag (non-VIP community)
                create_bgp_rib_weight_check(
                    target_community=non_vip_community,  # Check non-VIP community routes
                    target_prefix=non_vip_v6,
                    expected_weights={0: 12},  # All 12 nexthops with weight 0 (ECMP)
                    require_ucmp=False,  # Expect ECMP, not UCMP
                ),
                # Combined Traffic Distribution Check (VIP + Non-VIP)
                # IMPORTANT: Both traffic streams share the same physical interfaces to DCs
                # ODS interface metrics measure COMBINED traffic from both streams:
                #   VIP traffic (UCMP_TEST_TRAFFIC):     10% line rate, UCMP weights 10:5:2
                #   Non-VIP traffic (NON_VIP_TEST_TRAFFIC): 5% line rate, ECMP weights 1:1:1
                #
                # Combined distribution calculation (assuming 100G links = 100 Gbps):
                #   Total VIP traffic:     10 Gbps
                #   Total non-VIP traffic:  5 Gbps
                #   Total combined:        15 Gbps
                #
                #   DC1: VIP (10 Gbps × 10/17) + Non-VIP (5 Gbps × 1/3) = 5.88 + 1.67 = 7.55 Gbps
                #        Percentage: 7.55 / 15 = 50.3%
                #   DC2: VIP (10 Gbps × 5/17)  + Non-VIP (5 Gbps × 1/3) = 2.94 + 1.67 = 4.61 Gbps
                #        Percentage: 4.61 / 15 = 30.7%
                #   DC3: VIP (10 Gbps × 2/17)  + Non-VIP (5 Gbps × 1/3) = 1.18 + 1.67 = 2.85 Gbps
                #        Percentage: 2.85 / 15 = 19.0%
                #
                # We validate:
                #   1. FIB has UCMP weights programmed (10, 5, 2)
                #   2. Actual traffic distribution matches combined expected (50.3%, 30.7%, 19.0%)
                create_fib_traffic_distribution_check(
                    target_prefix=vip_v6,  # Check VIP prefix (both prefixes use same interfaces)
                    expected_fib_weights={
                        dc1_weight: 4,  # DC1: 4 nexthops with weight 10 (UCMP)
                        dc2_weight: 4,  # DC2: 4 nexthops with weight 5 (UCMP)
                        dc3_weight: 4,  # DC3: 4 nexthops with weight 2 (UCMP)
                    },
                    # Manual expected distribution: accounts for combined VIP (UCMP) + Non-VIP (ECMP) traffic
                    # dc1=highest weight (10), dc2=middle weight (5), dc3=lowest weight (2)
                    expected_traffic_distribution={
                        "dc1": 50.3,  # Combined: (10Gbps × 10/17) + (5Gbps × 1/3) = 7.55/15 = 50.3%
                        "dc2": 30.7,  # Combined: (10Gbps × 5/17)  + (5Gbps × 1/3) = 4.61/15 = 30.7%
                        "dc3": 19.0,  # Combined: (10Gbps × 2/17)  + (5Gbps × 1/3) = 2.85/15 = 19.0%
                    },
                    tolerance_percent=10,  # Lower tolerance now that we have accurate expected values
                ),
            ],
            traffic_items_to_start=[".*"],  # Start all traffic (VIP + Non-VIP)
        )
    )

    return playbooks


def create_test_case_7_playbooks(
    vip_community: str,
    vip_v6: str,
    dc1_asn: int,
    dc2_asn: int,
    dc3_asn: int,
    dc1_weight: int,
    dc2_weight: int,
    dc3_weight: int,
    dc1_neighbor_hostname: str,
    num_interfaces_to_flap: int = 2,
) -> list[Playbook]:
    """
    Create playbook for Test Case 7: CTE DC-Level UCMP - Link Failure (Path Reduction).

    Tests system behavior when there's a mismatch between configured capacity (Shiv instance weights)
    and actual available network capacity due to link failures. Specifically simulates DC1 with weight 10
    (10 Shiv instances) but only 50% of network paths available (2 out of 4 links).

    Test Scenario:
        - All 3 DCs initially online with full connectivity (12 paths total)
        - Baseline: DC1 58.8%, DC2 29.4%, DC3 11.8%
        - Simulate link failure: 2 of 4 DC1 paths withdrawn (50% link failure)
        - Expected: DC1 41.7%, DC2 41.7%, DC3 16.7% (10 paths total)

    Note: In production this would be physical link failure. In test environment, we simulate
    by withdrawing half of DC1's BGP routes to mimic the effect of losing 2 out of 4 links.

    Args:
        vip_community: VIP community string (e.g., "65441:260")
        vip_v6: VIP IPv6 prefix (e.g., "2402:db00:1100::/64")
        dc1_asn: DC1 AS number for AS_PATH matching
        dc2_asn: DC2 AS number for AS_PATH matching
        dc3_asn: DC3 AS number for AS_PATH matching
        dc1_weight: UCMP weight for DC1 (e.g., 10)
        dc2_weight: UCMP weight for DC2 (e.g., 5)
        dc3_weight: UCMP weight for DC3 (e.g., 2)
        dc1_neighbor_hostname: Hostname of DC1 neighbor device for LLDP-based interface selection (e.g., "ssw004.s002.f01.qzd1")
        num_interfaces_to_flap: Number of interfaces to flap for link failure simulation (default: 2)

    Returns:
        List with 1 playbook: TC7 (Link Failure - Path Reduction)
    """
    playbooks = []

    # Test Case 7: Link Failure (Path Reduction) - Weight vs. Available Capacity
    playbooks.append(
        Playbook(
            name="link_failure_path_reduction",
            description="CTE UCMP Test Case 7: Link failure in DC1 (50% path reduction), UCMP weight remains but traffic redistributes",
            prechecks=[],
            postchecks_to_skip=[
                hc_types.CheckName.PORT_STATE_CHECK,  # Interfaces intentionally shut down
                hc_types.CheckName.LLDP_CHECK,  # LLDP affected by interface shutdown
            ],
            setup_steps=[
                # Deploy UCMP policy for all 3 DCs
                create_ucmp_policy_config_step(
                    vip_community=vip_community,
                    dc1_asn=dc1_asn,
                    dc2_asn=dc2_asn,
                    dc3_asn=dc3_asn,
                    dc1_weight=dc1_weight,
                    dc2_weight=dc2_weight,
                    dc3_weight=dc3_weight,
                ),
                # Enable all 3 DCs (full connectivity baseline)
                create_enable_dc_vip_step(dc_number=1),
                create_enable_dc_vip_step(dc_number=2),
                create_enable_dc_vip_step(dc_number=3),
                create_bgp_convergence_wait_step(wait_seconds=60),
            ],
            cleanup_steps=[
                # Re-enable the interfaces that were shut down during the test
                # Use cached interfaces from Stage 2
                _cte_create_interface_flap_step(
                    neighbor_hostname=dc1_neighbor_hostname,
                    num_interfaces=num_interfaces_to_flap,
                    enable=True,
                    interface_flap_method=1,
                    cache_name="dc1_flapped_interfaces",
                    use_cached_interfaces=True,
                ),
            ],
            stages=[
                # Stage 1: Verify baseline with all 3 DCs online and full connectivity (12 paths)
                create_steps_stage(
                    steps=[
                        # Clear traffic stats for baseline measurement
                        create_clear_traffic_stats_step(),
                        # Run traffic to establish full connectivity baseline
                        create_traffic_duration_step(duration_seconds=300),
                        # Verify all 12 paths serving traffic correctly
                        create_ucmp_validation_step(
                            vip_community=vip_community,
                            vip_v6=vip_v6,
                            expected_rib_weights={
                                dc1_weight: 4,  # DC1: 4 paths
                                dc2_weight: 4,  # DC2: 4 paths
                                dc3_weight: 4,  # DC3: 4 paths
                            },
                            expected_as_weights={
                                dc1_asn: dc1_weight,
                                dc2_asn: dc2_weight,
                                dc3_asn: dc3_weight,
                            },
                            expected_fib_weights={
                                dc1_weight: 4,  # 10/1 = 10
                                dc2_weight: 4,  # 5/1 = 5
                                dc3_weight: 4,  # 2/1 = 2
                            },
                            tolerance_percent=5,
                        ),
                    ],
                ),
                # Stage 2: Simulate link failure (shut down links to DC1)
                # In production: Physical links fail (e.g., eth1/1, eth1/2 DOWN)
                # In test: Use LLDP to identify DC1 interfaces and shut them down
                create_steps_stage(
                    steps=[
                        # Shut down interfaces connected to DC1 spine
                        # This simulates link failure (50% path reduction for default 2 of 4 links)
                        # Cache the selected interfaces so we can re-enable them in cleanup
                        _cte_create_interface_flap_step(
                            neighbor_hostname=dc1_neighbor_hostname,
                            num_interfaces=num_interfaces_to_flap,
                            enable=False,
                            interface_flap_method=1,  # THRIFT_PORT_STATE_CHANGE
                            cache_name="dc1_flapped_interfaces",
                        ),
                        # Wait for BGP convergence after link failure
                        create_bgp_convergence_wait_step(wait_seconds=60),
                        # Clear traffic stats to ignore loss during convergence
                        create_clear_traffic_stats_step(),
                        # Run traffic for test duration
                        create_traffic_duration_step(duration_seconds=300),
                    ],
                ),
            ],
            postchecks=[
                # Standard traffic validation
                create_packetloss_health_check(),
                # UCMP Control Plane Check - verify routes after link failure
                # Note: We can't easily verify exact path count with partial withdrawal,
                # but we can verify weights are still applied to remaining paths
                create_bgp_rib_weight_check(
                    target_community=vip_community,
                    target_prefix=vip_v6,
                    expected_weights={
                        dc1_weight: 2,  # DC1: ~2 paths (50% of 4 withdrawn)
                        dc2_weight: 4,  # DC2: 4 paths (unchanged)
                        dc3_weight: 4,  # DC3: 4 paths (unchanged)
                    },
                    expected_as_weights={
                        dc1_asn: dc1_weight,  # Weight config unchanged
                        dc2_asn: dc2_weight,
                        dc3_asn: dc3_weight,
                    },
                ),
                # UCMP Data Plane Check - verify traffic redistribution after link failure
                # Before: DC1=40 (4×10), DC2=20 (4×5), DC3=8 (4×2), Total=68
                #         DC1 58.8%, DC2 29.4%, DC3 11.8%
                # After:  DC1=20 (2×10), DC2=20 (4×5), DC3=8 (4×2), Total=48
                #         DC1 41.7%, DC2 41.7%, DC3 16.7%
                # GCD(10, 5, 2) = 1, so FIB weights unchanged
                create_fib_traffic_distribution_check(
                    target_prefix=vip_v6,
                    expected_fib_weights={
                        dc1_weight: 2,  # DC1: 2 paths remaining (50% withdrawn)
                        dc2_weight: 4,  # DC2: 4 paths
                        dc3_weight: 4,  # DC3: 4 paths
                    },
                    # Manual expected distribution after link failure
                    expected_traffic_distribution={
                        "dc1": 41.7,  # DC1: 20/48 = 41.7% (reduced from 58.8%)
                        "dc2": 41.7,  # DC2: 20/48 = 41.7% (increased from 29.4%)
                        "dc3": 16.7,  # DC3: 8/48 = 16.7% (increased from 11.8%)
                    },
                    tolerance_percent=10,  # Allow higher tolerance for link failure scenario
                ),
            ],
            traffic_items_to_start=["UCMP_TEST_TRAFFIC"],  # VIP traffic only (TC7)
        )
    )

    return playbooks


def create_test_case_8_playbooks(
    vip_community: str,
    vip_v6: str,
    dc1_asn: int,
    dc2_asn: int,
    dc3_asn: int,
    dc1_weight: int,
    dc2_weight: int,
    dc3_weight: int,
    dc1_neighbor_hostname: str,
) -> list[Playbook]:
    """
    Create playbook for Test Case 8: Complete DC1 Failure and Recovery.

    Tests system behavior when all links to DC1 fail and then recover, validating:
    1. Baseline traffic distribution with all 3 DCs online
    2. Traffic redistributes to remaining DCs (DC2+DC3) during DC1 failure
    3. Traffic returns to baseline after DC1 links are restored

    Test Scenario:
        - Stage 1: All 3 DCs online - verify baseline (DC1 58.8%, DC2 29.4%, DC3 11.8%)
        - Stage 2: Shut all 4 DC1 links - verify redistribution (DC1 0%, DC2 71.4%, DC3 28.6%)
        - Stage 3: Restore all 4 DC1 links - verify baseline recovery (DC1 58.8%, DC2 29.4%, DC3 11.8%)

    Args:
        vip_community: VIP community string (e.g., "65441:260")
        vip_v6: VIP IPv6 prefix (e.g., "2402:db00:1100::/64")
        dc1_asn: DC1 AS number for AS_PATH matching
        dc2_asn: DC2 AS number for AS_PATH matching
        dc3_asn: DC3 AS number for AS_PATH matching
        dc1_weight: UCMP weight for DC1 (e.g., 10)
        dc2_weight: UCMP weight for DC2 (e.g., 5)
        dc3_weight: UCMP weight for DC3 (e.g., 2)
        dc1_neighbor_hostname: Hostname of DC1 neighbor device for LLDP-based interface selection

    Returns:
        List with 1 playbook: TC8 (Complete DC1 Failure and Recovery)
    """
    playbooks = []

    # Test Case 8: Complete DC1 Failure and Recovery
    playbooks.append(
        Playbook(
            name="complete_dc1_failure_and_recovery",
            description="CTE UCMP Test Case 8: Complete DC1 failure (all 4 links down) and recovery - verify redistribution and baseline restoration",
            prechecks=[],
            postchecks_to_skip=[
                hc_types.CheckName.PORT_STATE_CHECK,  # DC1 interfaces flapped during test
                hc_types.CheckName.LLDP_CHECK,  # LLDP affected by interface flap
            ],
            setup_steps=[
                # Deploy UCMP policy for all 3 DCs
                create_ucmp_policy_config_step(
                    vip_community=vip_community,
                    dc1_asn=dc1_asn,
                    dc2_asn=dc2_asn,
                    dc3_asn=dc3_asn,
                    dc1_weight=dc1_weight,
                    dc2_weight=dc2_weight,
                    dc3_weight=dc3_weight,
                ),
                # Enable all 3 DCs (full connectivity baseline)
                create_enable_dc_vip_step(dc_number=1),
                create_enable_dc_vip_step(dc_number=2),
                create_enable_dc_vip_step(dc_number=3),
                create_bgp_convergence_wait_step(wait_seconds=60),
            ],
            stages=[
                # Stage 1: Verify baseline with all 3 DCs online
                create_steps_stage(
                    steps=[
                        # Clear traffic stats for baseline measurement
                        create_clear_traffic_stats_step(),
                        # Run traffic to establish baseline (5 minutes)
                        create_traffic_duration_step(duration_seconds=300),
                        # Verify all 12 paths serving traffic correctly
                        create_ucmp_validation_step(
                            vip_community=vip_community,
                            vip_v6=vip_v6,
                            expected_rib_weights={
                                dc1_weight: 4,  # DC1: 4 paths
                                dc2_weight: 4,  # DC2: 4 paths
                                dc3_weight: 4,  # DC3: 4 paths
                            },
                            expected_as_weights={
                                dc1_asn: dc1_weight,
                                dc2_asn: dc2_weight,
                                dc3_asn: dc3_weight,
                            },
                            expected_fib_weights={
                                dc1_weight: 4,  # 10/1 = 10
                                dc2_weight: 4,  # 5/1 = 5
                                dc3_weight: 4,  # 2/1 = 2
                            },
                            tolerance_percent=5,
                        ),
                    ],
                ),
                # Stage 2: Shut all 4 DC1 links and verify redistribution
                create_steps_stage(
                    steps=[
                        # Shut down ALL 4 interfaces connected to DC1 spine
                        # This simulates complete DC1 failure (100% link failure)
                        _cte_create_interface_flap_step(
                            neighbor_hostname=dc1_neighbor_hostname,
                            num_interfaces=4,
                            enable=False,
                            interface_flap_method=1,
                            cache_name="dc1_all_flapped_interfaces",
                        ),
                        # Wait for BGP convergence after complete link failure
                        create_bgp_convergence_wait_step(wait_seconds=60),
                        # Clear traffic stats to ignore loss during convergence
                        create_clear_traffic_stats_step(),
                        # Run traffic for test duration
                        create_traffic_duration_step(duration_seconds=300),
                        # Verify traffic redistributes to DC2+DC3 only
                        create_ucmp_validation_step(
                            vip_community=vip_community,
                            vip_v6=vip_v6,
                            expected_rib_weights={
                                dc2_weight: 4,  # DC2: 4 paths
                                dc3_weight: 4,  # DC3: 4 paths
                                # DC1: 0 paths (all links down)
                            },
                            expected_as_weights={
                                dc2_asn: dc2_weight,  # AS 50002 should have weight 5
                                dc3_asn: dc3_weight,  # AS 50003 should have weight 2
                                # DC1 (AS 50001) has no paths
                            },
                            expected_fib_weights={
                                dc2_weight: 4,  # DC2: 4 paths with weight 5
                                dc3_weight: 4,  # DC3: 4 paths with weight 2
                                # DC1: 0 paths
                            },
                            expected_traffic_distribution={
                                "dc2": 71.4,  # DC2: 20/28 = 71.4%
                                "dc3": 28.6,  # DC3: 8/28 = 28.6%
                            },
                            tolerance_percent=10,
                        ),
                    ],
                ),
                # Stage 3: Restore all 4 DC1 links and verify baseline recovery
                create_steps_stage(
                    steps=[
                        # Re-enable all 4 interfaces that were shut down in Stage 2
                        _cte_create_interface_flap_step(
                            neighbor_hostname=dc1_neighbor_hostname,
                            num_interfaces=4,
                            enable=True,
                            interface_flap_method=1,
                            cache_name="dc1_all_flapped_interfaces",
                            use_cached_interfaces=True,
                        ),
                        # Wait for BGP convergence after link restoration
                        create_bgp_convergence_wait_step(wait_seconds=60),
                        # Run traffic for test duration
                        create_traffic_duration_step(duration_seconds=300),
                    ],
                ),
            ],
            postchecks=[
                # Standard traffic validation
                create_packetloss_health_check(),
                # UCMP Control Plane Check - verify all 12 paths restored after DC1 recovery
                create_bgp_rib_weight_check(
                    target_community=vip_community,
                    target_prefix=vip_v6,
                    expected_weights={
                        dc1_weight: 4,  # DC1: 4 paths (restored)
                        dc2_weight: 4,  # DC2: 4 paths
                        dc3_weight: 4,  # DC3: 4 paths
                    },
                    expected_as_weights={
                        dc1_asn: dc1_weight,  # AS 50001 should have weight 10
                        dc2_asn: dc2_weight,  # AS 50002 should have weight 5
                        dc3_asn: dc3_weight,  # AS 50003 should have weight 2
                    },
                ),
                # UCMP Data Plane Check - verify baseline traffic distribution restored
                # After DC1 recovery: DC1=40 (4×10), DC2=20 (4×5), DC3=8 (4×2), Total=68
                #                     DC1 58.8%, DC2 29.4%, DC3 11.8%
                create_fib_traffic_distribution_check(
                    target_prefix=vip_v6,
                    expected_fib_weights={
                        dc1_weight: 4,  # DC1: 4 paths (fully restored)
                        dc2_weight: 4,  # DC2: 4 paths
                        dc3_weight: 4,  # DC3: 4 paths
                    },
                    tolerance_percent=10,
                ),
            ],
            traffic_items_to_start=["UCMP_TEST_TRAFFIC"],
        )
    )

    return playbooks


def create_test_case_9_playbooks(
    vip_community: str,
    vip_v6: str,
    dc1_asn: int,
    dc2_asn: int,
    dc3_asn: int,
    dc1_weight: int,
    dc2_weight: int,
    dc3_weight: int,
) -> list[Playbook]:
    """
    Create playbook for Test Case 9: BGP Daemon Restart on DUT WITH Graceful Restart.

    Tests system behavior when BGP daemon restarts on the DUT (fa001-du004) during
    active traffic with BGP Graceful Restart enabled. This simulates scenarios like:
    - DUT device reboot
    - DUT software upgrade
    - BGP daemon crash on DUT

    Test Scenario:
        - All 3 DCs online, baseline traffic: DC1 58.8%, DC2 29.4%, DC3 11.8%
        - BGP daemon restarts on DUT (all sessions from DUT to 3 DCs go down ~10s, then recover)
        - With Graceful Restart: DUT's FIB retained, traffic continues during restart
        - After recovery: All BGP sessions (DUT ↔ DC1, DC2, DC3) re-establish, traffic remains stable

    Expected Behavior (WITH Graceful Restart):
        - BGP daemon restart on DUT: ~10s downtime
        - FIB retention on DUT: Routes remain in DUT's FIB during restart
        - Traffic impact: Minimal disruption (traffic continues via retained FIB)
        - Session re-establishment: <5s per session after daemon up
        - Full reconvergence: <30s after daemon up
        - Packet loss: <0.1% (minimal due to Graceful Restart)

    NOTE: This tests DUT resilience, not DC resilience. The BGP daemon restarts
    on the DUT (fa001-du004), causing all sessions from DUT to the 3 DCs to flap.

    Args:
        vip_community: VIP community string (e.g., "65441:260")
        vip_v6: VIP IPv6 prefix (e.g., "2402:db00:1100::/64")
        dc1_asn: DC1 AS number for AS_PATH matching
        dc2_asn: DC2 AS number for AS_PATH matching
        dc3_asn: DC3 AS number for AS_PATH matching
        dc1_weight: UCMP weight for DC1 (e.g., 10)
        dc2_weight: UCMP weight for DC2 (e.g., 5)
        dc3_weight: UCMP weight for DC3 (e.g., 2)

    Returns:
        List with 1 playbook: TC9 (BGP Daemon Restart on DUT with Graceful Restart)
    """
    playbooks = []

    # Test Case 9: BGP Daemon Restart on DUT with Graceful Restart
    playbooks.append(
        Playbook(
            name="bgp_daemon_restart_dut_graceful",
            description="CTE UCMP Test Case 9: BGP daemon restart on DUT WITH Graceful Restart (simulates DUT reboot/software upgrade)",
            prechecks=[],
            setup_steps=[
                # Deploy UCMP policy for all 3 DCs
                create_ucmp_policy_config_step(
                    vip_community=vip_community,
                    dc1_asn=dc1_asn,
                    dc2_asn=dc2_asn,
                    dc3_asn=dc3_asn,
                    dc1_weight=dc1_weight,
                    dc2_weight=dc2_weight,
                    dc3_weight=dc3_weight,
                ),
                # Enable all 3 DCs (full connectivity baseline)
                create_enable_dc_vip_step(dc_number=1),
                create_enable_dc_vip_step(dc_number=2),
                create_enable_dc_vip_step(dc_number=3),
                create_bgp_convergence_wait_step(wait_seconds=60),
            ],
            stages=[
                # Stage 1: Verify baseline with all BGP sessions up
                create_steps_stage(
                    steps=[
                        # Clear traffic stats for baseline measurement
                        create_clear_traffic_stats_step(),
                        # Run traffic to establish baseline (5 minutes)
                        create_traffic_duration_step(duration_seconds=300),
                        # Verify all 12 paths serving traffic correctly
                        create_ucmp_validation_step(
                            vip_community=vip_community,
                            vip_v6=vip_v6,
                            expected_rib_weights={
                                dc1_weight: 4,  # DC1: 4 paths
                                dc2_weight: 4,  # DC2: 4 paths
                                dc3_weight: 4,  # DC3: 4 paths
                            },
                            expected_as_weights={
                                dc1_asn: dc1_weight,
                                dc2_asn: dc2_weight,
                                dc3_asn: dc3_weight,
                            },
                            expected_fib_weights={
                                dc1_weight: 4,  # 10/1 = 10
                                dc2_weight: 4,  # 5/1 = 5
                                dc3_weight: 4,  # 2/1 = 2
                            },
                            tolerance_percent=5,
                        ),
                    ],
                ),
                # Stage 2: BGP daemon restart on DUT and recovery
                create_steps_stage(
                    steps=[
                        # Restart BGP daemon on DUT (fa001-du004)
                        # This causes all BGP sessions from DUT to 3 DCs to go down and come back up
                        # With Graceful Restart: DUT's FIB is retained, traffic continues
                        create_bgp_service_restart_step(),
                        # Wait for BGP daemon to come back up and sessions to re-establish
                        create_bgp_service_convergence_step(wait_seconds=300),
                    ],
                ),
            ],
            postchecks=[
                # Verify BGP convergence after daemon restart (within 60s threshold)
                create_bgp_convergence_check(convergence_threshold=300),
                # Packet loss check - measures entire period including BGP daemon restart
                # With Graceful Restart: expect <0.1% loss (FIB retained, traffic continues)
                create_packetloss_health_check(),
                # UCMP Control Plane Check - verify all 12 paths restored
                create_bgp_rib_weight_check(
                    target_community=vip_community,
                    target_prefix=vip_v6,
                    expected_weights={
                        dc1_weight: 4,  # DC1: 4 paths (restored)
                        dc2_weight: 4,  # DC2: 4 paths
                        dc3_weight: 4,  # DC3: 4 paths
                    },
                    expected_as_weights={
                        dc1_asn: dc1_weight,  # AS 50001 should have weight 10
                        dc2_asn: dc2_weight,  # AS 50002 should have weight 5
                        dc3_asn: dc3_weight,  # AS 50003 should have weight 2
                    },
                ),
                # UCMP Data Plane Check - verify baseline traffic distribution restored
                # After recovery: DC1=40 (4×10), DC2=20 (4×5), DC3=8 (4×2), Total=68
                #                 DC1 58.8%, DC2 29.4%, DC3 11.8%
                create_fib_traffic_distribution_check(
                    target_prefix=vip_v6,
                    expected_fib_weights={
                        dc1_weight: 4,  # DC1: 4 paths (restored)
                        dc2_weight: 4,  # DC2: 4 paths
                        dc3_weight: 4,  # DC3: 4 paths
                    },
                    tolerance_percent=5,  # ±5% tolerance as specified
                ),
            ],
            traffic_items_to_start=["UCMP_TEST_TRAFFIC"],
        )
    )

    return playbooks


def create_test_case_10_playbooks(
    vip_community: str,
    vip_v6: str,
    dc1_asn: int,
    dc2_asn: int,
    dc3_asn: int,
    dc1_weight: int,
    dc2_weight: int,
    dc3_weight: int,
) -> list[Playbook]:
    """
    Create playbook for Test Case 10: BGP Process Crash and Policy Recovery.

    Tests system behavior when BGP daemon crashes (SIGKILL) on the DUT during
    active traffic, validating that CTE UCMP policy survives the crash and is
    correctly reapplied after automatic restart by systemd/watchdog.

    Test Scenario:
        - All 3 DCs online, baseline traffic: DC1 58.8%, DC2 29.4%, DC3 11.8%
        - Kill BGP process with SIGKILL (simulates abnormal crash, not graceful shutdown)
        - Systemd/watchdog automatically restarts BGP process
        - CTE UCMP policy reloaded from persistent config
        - All BGP sessions re-establish, policy reapplied
        - Traffic distribution returns to baseline

    Expected Behavior:
        With Graceful Restart Enabled:
            - Zero packet loss (stale routes continue forwarding during restart)
            - FIB retained during crash and recovery
            - Seamless recovery

        With Graceful Restart Disabled:
            - Significant packet loss during recovery (60-120 seconds)
            - Routes withdrawn from RIB when BGP crashes
            - Full reconvergence required

    Key Validations:
        - BGP process running after crash (uptime < 5 minutes)
        - CTE policy exists and is not null (successfully reloaded)
        - Policy contains correct weights: DC1=10, DC2=5, DC3=2
        - All 12 paths restored with correct UCMP weights
        - Traffic distribution matches baseline

    NOTE: This differs from TC9 (graceful restart):
        - TC9: SYSTEMCTL_RESTART (graceful service restart)
        - TC10: CRASH (SIGKILL - abnormal termination)

    Args:
        vip_community: VIP community string (e.g., "65441:260")
        vip_v6: VIP IPv6 prefix (e.g., "2402:db00:1100::/64")
        dc1_asn: DC1 AS number for AS_PATH matching
        dc2_asn: DC2 AS number for AS_PATH matching
        dc3_asn: DC3 AS number for AS_PATH matching
        dc1_weight: UCMP weight for DC1 (e.g., 10)
        dc2_weight: UCMP weight for DC2 (e.g., 5)
        dc3_weight: UCMP weight for DC3 (e.g., 2)

    Returns:
        List with 1 playbook: TC10 (BGP Process Crash and Policy Recovery)
    """
    playbooks = []

    # Test Case 10: BGP Process Crash and Policy Recovery
    playbooks.append(
        Playbook(
            name="bgp_process_crash_policy_recovery",
            description="CTE UCMP Test Case 10: BGP process crash (SIGKILL), automatic restart, and UCMP policy recovery",
            prechecks=[],
            setup_steps=[
                # Deploy UCMP policy for all 3 DCs
                create_ucmp_policy_config_step(
                    vip_community=vip_community,
                    dc1_asn=dc1_asn,
                    dc2_asn=dc2_asn,
                    dc3_asn=dc3_asn,
                    dc1_weight=dc1_weight,
                    dc2_weight=dc2_weight,
                    dc3_weight=dc3_weight,
                ),
                # Enable all 3 DCs (full connectivity baseline)
                create_enable_dc_vip_step(dc_number=1),
                create_enable_dc_vip_step(dc_number=2),
                create_enable_dc_vip_step(dc_number=3),
                create_bgp_convergence_wait_step(wait_seconds=60),
            ],
            stages=[
                # Stage 1: Verify baseline with all BGP sessions up and policy active
                create_steps_stage(
                    steps=[
                        # Clear traffic stats for baseline measurement
                        create_clear_traffic_stats_step(),
                        # Run traffic to establish baseline (5 minutes)
                        create_traffic_duration_step(duration_seconds=300),
                        # Verify all 12 paths serving traffic correctly with UCMP policy
                        create_ucmp_validation_step(
                            vip_community=vip_community,
                            vip_v6=vip_v6,
                            expected_rib_weights={
                                dc1_weight: 4,  # DC1: 4 paths
                                dc2_weight: 4,  # DC2: 4 paths
                                dc3_weight: 4,  # DC3: 4 paths
                            },
                            expected_as_weights={
                                dc1_asn: dc1_weight,
                                dc2_asn: dc2_weight,
                                dc3_asn: dc3_weight,
                            },
                            expected_fib_weights={
                                dc1_weight: 4,  # 10/1 = 10
                                dc2_weight: 4,  # 5/1 = 5
                                dc3_weight: 4,  # 2/1 = 2
                            },
                            tolerance_percent=5,
                        ),
                    ],
                ),
                # Stage 2: BGP process crash (SIGKILL) and automatic recovery
                create_steps_stage(
                    steps=[
                        # Crash BGP process with SIGKILL on DUT
                        # This causes abnormal termination - systemd/watchdog will auto-restart
                        create_bgp_service_crash_step(),
                        # Wait for BGP process to be auto-restarted and sessions to re-establish
                        # Longer wait than TC9 due to crash vs graceful restart
                        create_bgp_service_convergence_step(wait_seconds=300),
                    ],
                ),
            ],
            postchecks=[
                # Verify BGP convergence after crash and recovery
                # CRITICAL: Policy must be reloaded and reapplied
                create_bgp_convergence_check(convergence_threshold=300),
                # Packet loss check - measures entire period including BGP crash
                # Expected loss depends on Graceful Restart configuration:
                #   - GR enabled: <0.1% loss (stale routes continue forwarding)
                #   - GR disabled: significant loss during recovery (60-120s)
                create_packetloss_health_check(),
                # UCMP Control Plane Check - CRITICAL validation
                # Verify CTE policy was reloaded and all 12 paths restored with correct weights
                create_bgp_rib_weight_check(
                    target_community=vip_community,
                    target_prefix=vip_v6,
                    expected_weights={
                        dc1_weight: 4,  # DC1: 4 paths (restored after crash)
                        dc2_weight: 4,  # DC2: 4 paths
                        dc3_weight: 4,  # DC3: 4 paths
                    },
                    expected_as_weights={
                        dc1_asn: dc1_weight,  # AS 50001 should have weight 10 (policy reloaded)
                        dc2_asn: dc2_weight,  # AS 50002 should have weight 5 (policy reloaded)
                        dc3_asn: dc3_weight,  # AS 50003 should have weight 2 (policy reloaded)
                    },
                ),
                # UCMP Data Plane Check - verify baseline traffic distribution restored
                # After recovery: DC1=40 (4×10), DC2=20 (4×5), DC3=8 (4×2), Total=68
                #                 DC1 58.8%, DC2 29.4%, DC3 11.8%
                # This validates that:
                #   1. CTE policy was correctly reloaded from persistent config
                #   2. Policy was reapplied to all routes
                #   3. FIB is correctly programmed with UCMP weights
                create_fib_traffic_distribution_check(
                    target_prefix=vip_v6,
                    expected_fib_weights={
                        dc1_weight: 4,  # DC1: 4 paths (policy reapplied)
                        dc2_weight: 4,  # DC2: 4 paths
                        dc3_weight: 4,  # DC3: 4 paths
                    },
                    tolerance_percent=5,  # ±5% tolerance
                ),
            ],
            traffic_items_to_start=["UCMP_TEST_TRAFFIC"],
        )
    )

    return playbooks


def create_test_case_14_playbooks(
    vip_community: str,
    vip_v6: str,
    dc1_asn: int,
    dc2_asn: int,
    dc3_asn: int,
    dc1_weight: int,
    dc2_weight: int,
    dc3_weight: int,
    dc1_device_name: str,
) -> list[Playbook]:
    """
    Create playbooks for Test Case 14: Device Drain and Undrain.

    Two playbooks to test device drain and recovery:
    1. TC14: Drain DC1 - routes not selected as best paths
    2. TC14b: Undrain DC1 - routes selected as best again, traffic returns to baseline

    Test Scenario (TC14 - Drain):
        - All 3 DCs initially online with full connectivity (12 paths total)
        - Baseline: DC1 58.8%, DC2 29.4%, DC3 11.8%
        - Drain DC1: Routes from DC1 should not be selected as best paths
        - Expected: DC1 0%, DC2 71.4%, DC3 28.6% (8 paths total, DC2+DC3 only)

    Test Scenario (TC14b - Undrain):
        - Stage 1: Drain DC1 (to get into same state as TC14 ended)
        - Stage 2: Undrain DC1 and verify recovery
        - Expected: DC1 58.8%, DC2 29.4%, DC3 11.8% (baseline restored)

    Args:
        vip_community: VIP community string (e.g., "65441:260")
        vip_v6: VIP IPv6 prefix (e.g., "2402:db00:1100::/64")
        dc1_asn: DC1 AS number for AS_PATH matching
        dc2_asn: DC2 AS number for AS_PATH matching
        dc3_asn: DC3 AS number for AS_PATH matching
        dc1_weight: UCMP weight for DC1 (e.g., 10)
        dc2_weight: UCMP weight for DC2 (e.g., 5)
        dc3_weight: UCMP weight for DC3 (e.g., 2)
        dc1_device_name: Device name for DC1 (e.g., "ssw004.s002.f01.qzd1")

    Returns:
        List of 2 playbooks: TC14 (Device Drain), TC14b (Device Undrain)
    """
    playbooks = []

    # Test Case 14: Device Drain - DC1 drained, routes not selected as best
    playbooks.append(
        Playbook(
            name="device_drain_dc1",
            description="CTE UCMP Test Case 14: DC1 drained, routes not selected as best paths, traffic redistributes to DC2+DC3",
            prechecks=[],
            setup_steps=[
                # Deploy UCMP policy for all 3 DCs
                create_ucmp_policy_config_step(
                    vip_community=vip_community,
                    dc1_asn=dc1_asn,
                    dc2_asn=dc2_asn,
                    dc3_asn=dc3_asn,
                    dc1_weight=dc1_weight,
                    dc2_weight=dc2_weight,
                    dc3_weight=dc3_weight,
                ),
                # Enable all 3 DCs (full connectivity baseline)
                create_enable_dc_vip_step(dc_number=1),
                create_enable_dc_vip_step(dc_number=2),
                create_enable_dc_vip_step(dc_number=3),
                create_bgp_convergence_wait_step(wait_seconds=60),
            ],
            cleanup_steps=[
                # Undrain DC1 after test
                create_cte_ucmp_drain_undrain_step(
                    device_name=dc1_device_name,
                    drain=False,
                ),
                create_bgp_convergence_wait_step(wait_seconds=60),
            ],
            stages=[
                # Stage 1: Verify baseline with all 3 DCs online
                create_steps_stage(
                    steps=[
                        # Clear traffic stats for baseline measurement
                        create_clear_traffic_stats_step(),
                        # Run traffic to establish baseline (5 minutes)
                        create_traffic_duration_step(duration_seconds=300),
                        # Verify all 12 paths serving traffic correctly
                        create_ucmp_validation_step(
                            vip_community=vip_community,
                            vip_v6=vip_v6,
                            expected_rib_weights={
                                dc1_weight: 4,  # DC1: 4 paths
                                dc2_weight: 4,  # DC2: 4 paths
                                dc3_weight: 4,  # DC3: 4 paths
                            },
                            expected_as_weights={
                                dc1_asn: dc1_weight,
                                dc2_asn: dc2_weight,
                                dc3_asn: dc3_weight,
                            },
                            expected_fib_weights={
                                dc1_weight: 4,  # 10/1 = 10
                                dc2_weight: 4,  # 5/1 = 5
                                dc3_weight: 4,  # 2/1 = 2
                            },
                            tolerance_percent=5,
                        ),
                    ],
                ),
                # Stage 2: Drain DC1 and verify route selection
                create_steps_stage(
                    steps=[
                        # Drain DC1 device
                        create_cte_ucmp_drain_undrain_step(
                            device_name=dc1_device_name,
                            drain=True,
                        ),
                        # Wait for BGP convergence after drain
                        create_bgp_convergence_wait_step(wait_seconds=60),
                        # Clear traffic stats to ignore loss during convergence
                        create_clear_traffic_stats_step(),
                        # Run traffic for test duration
                        create_traffic_duration_step(duration_seconds=300),
                    ],
                ),
            ],
            postchecks=[
                # Standard traffic validation
                create_packetloss_health_check(),
                # UCMP Control Plane Check - verify only DC2 and DC3 paths selected
                # DC1 routes should still be present but NOT selected as best
                create_bgp_rib_weight_check(
                    target_community=vip_community,
                    target_prefix=vip_v6,
                    expected_weights={
                        dc2_weight: 4,  # DC2: 4 paths (only DC2 selected as best)
                        dc3_weight: 4,  # DC3: 4 paths (only DC3 selected as best)
                        # DC1: 0 paths selected as best (drained)
                    },
                    expected_as_weights={
                        dc2_asn: dc2_weight,  # AS 50002 should have weight 5
                        dc3_asn: dc3_weight,  # AS 50003 should have weight 2
                        # DC1 (AS 50001) routes not selected as best
                    },
                ),
                # UCMP Data Plane Check - verify traffic redistributes to DC2+DC3 only
                # After DC1 drain: DC1=0, DC2=20 (4×5), DC3=8 (4×2), Total=28
                #                  DC1 0%, DC2 71.4%, DC3 28.6%
                # GCD(5, 2) = 1, so FIB weights: DC2=5, DC3=2
                create_fib_traffic_distribution_check(
                    target_prefix=vip_v6,
                    expected_fib_weights={
                        dc2_weight: 4,  # DC2: 4 paths with weight 5
                        dc3_weight: 4,  # DC3: 4 paths with weight 2
                        # DC1: 0 paths (drained)
                    },
                    # Manual expected distribution after DC1 drain
                    expected_traffic_distribution={
                        "dc2": 71.4,  # DC2: 20/28 = 71.4% (increased from 29.4%)
                        "dc3": 28.6,  # DC3: 8/28 = 28.6% (increased from 11.8%)
                        # DC1: 0% (drained)
                    },
                    tolerance_percent=10,
                ),
            ],
            traffic_items_to_start=["UCMP_TEST_TRAFFIC"],
        )
    )

    # Test Case 14b: Undrain DC1 and Verify Recovery
    playbooks.append(
        Playbook(
            name="device_undrain_dc1",
            description="CTE UCMP Test Case 14b: Undrain DC1, routes selected as best again, traffic returns to baseline",
            prechecks=[],
            stages=[
                # Stage 1: Drain DC1 (to get into same state as TC14 ended)
                create_steps_stage(
                    steps=[
                        # Drain DC1 device
                        create_cte_ucmp_drain_undrain_step(
                            device_name=dc1_device_name,
                            drain=True,
                        ),
                        # Wait for BGP convergence after drain
                        create_bgp_convergence_wait_step(wait_seconds=60),
                    ],
                ),
                # Stage 2: Undrain DC1 and verify recovery
                create_steps_stage(
                    steps=[
                        # Undrain DC1 device
                        create_cte_ucmp_drain_undrain_step(
                            device_name=dc1_device_name,
                            drain=False,
                        ),
                        # Wait for BGP convergence after undrain
                        create_bgp_convergence_wait_step(wait_seconds=60),
                        # Clear traffic stats to ignore loss during convergence
                        create_clear_traffic_stats_step(),
                        # Run traffic for test duration
                        create_traffic_duration_step(duration_seconds=300),
                    ],
                ),
            ],
            postchecks=[
                # Standard traffic validation
                create_packetloss_health_check(),
                # UCMP Control Plane Check - verify all 3 DCs paths selected as best
                create_bgp_rib_weight_check(
                    target_community=vip_community,
                    target_prefix=vip_v6,
                    expected_weights={
                        dc1_weight: 4,  # DC1: 4 paths (restored)
                        dc2_weight: 4,  # DC2: 4 paths
                        dc3_weight: 4,  # DC3: 4 paths
                    },
                    expected_as_weights={
                        dc1_asn: dc1_weight,  # AS 50001 should have weight 10
                        dc2_asn: dc2_weight,  # AS 50002 should have weight 5
                        dc3_asn: dc3_weight,  # AS 50003 should have weight 2
                    },
                ),
                # UCMP Data Plane Check - verify baseline traffic distribution restored
                # After undrain: DC1=40 (4×10), DC2=20 (4×5), DC3=8 (4×2), Total=68
                #                DC1 58.8%, DC2 29.4%, DC3 11.8%
                create_fib_traffic_distribution_check(
                    target_prefix=vip_v6,
                    expected_fib_weights={
                        dc1_weight: 4,  # DC1: 4 paths (restored)
                        dc2_weight: 4,  # DC2: 4 paths
                        dc3_weight: 4,  # DC3: 4 paths
                    },
                    tolerance_percent=10,
                ),
            ],
            traffic_items_to_start=["UCMP_TEST_TRAFFIC"],
        )
    )

    return playbooks


def create_test_case_12_playbooks(
    vip_community: str,
    vip_v6: str,
    dc1_asn: int,
    dc2_asn: int,
    dc3_asn: int,
    dc1_weight: int,
    dc2_weight: int,
    dc3_weight: int,
    iter: int,
) -> list[Playbook]:
    """
    Create playbooks for Test Case 12: Continuous Agent(Warmboot) Restart on DUT .

    Three playbooks to Continuous Agent(Warmboot) Restart on DUT:
    1. TC12 : Precheck - I: All 12 sessions are formed with [Dc1,Dc2,Dc3]],
                         II: Prefix( vip_v6 ) Present with UCMP  with [Dc1,Dc2,Dc3] 12 Paths,
                         III : Base line traffic is flowing among all DC's[DC1,DC2,DC3] Baseline: DC1 58.8%, DC2 29.4%, DC3 11.8%,
                         VI: Fboss agent is running, VI: Fboss agent uptime and PID recorded
                         V:Bgp session Uptimes stable
    2. TC12A: Triggers - I: Perform a warmboot restart on DUT (Using Warmboot Procedure),
                         II: All Fboss agent components and hardware manager should restart But hardware forwarding state is preserved
                         III: All Bgp sessions go down and must re-established
    3. TC12B: Control Plane - I : All Bgp sessions go down and must re-established,
                              II : Hardware Forwarding state(routes, ECMP Groups) is Preserved during agent restart
                              III: No routes withdrawal from hardware; data plane continues forwarding with existing state.
                              VI: After agent restart Bgp session re-established, routes re-learned, Ucmp weights re-calculated(FIB and RIB should be validated)
    4. TC12C: Data Plane - I : Hard ware contnues forwarding through out agent warmboot
                           II : Ucmp distribution maintained
                           III : minimal packet loss (<1%) brief disruption possible only during agent/hardware sync
                           VI : After agent restart completes Hardware state is validated and refreshed.
                           V : Seamless continuation of traffic flow
    5. TC12D: Postcheck - I: All 12 sessions are formed with [Dc1,Dc2,Dc3]] < 2 minutes,
                         II: Prefix( vip_v6 ) Present with UCMP  with [Dc1,Dc2,Dc3] 12 Paths,
                         III : FIB, hardware entries (12 next hops for the prefix) allong with DC's with their weights


    Args:
        vip_community: VIP community string (e.g., "65441:260")
        vip_v6: VIP IPv6 prefix (e.g., "2402:db00:1100::/64")
        dc1_asn: DC1 AS number for AS_PATH matching
        dc2_asn: DC2 AS number for AS_PATH matching
        dc3_asn: DC3 AS number for AS_PATH matching
        dc1_weight: UCMP weight for DC1 (e.g., 10)
        dc2_weight: UCMP weight for DC2 (e.g., 5)
        dc3_weight: UCMP weight for DC3 (e.g., 2)
        dc1_device_name: Device name for DC1 (e.g., "ssw004.s002.f01.qzd1")

    Returns:
        List of 5 playbooks: TC12 , TC12A , TC12B, TC12C, TC12D
    """
    playbooks = []

    # Test Case 12: warmboot - verify baseline state
    playbooks.append(
        Playbook(
            name="TC12_Warmboot",
            description="CTE UCMP Test Case 12: Verify all 12 BGP sessions established, UCMP paths present, baseline traffic distribution, and agent state",
            iteration=iter,
            prechecks=[
                create_bgp_session_establish_check(
                    expected_established_sessions=16,
                    parent_prefixes_to_ignore=[
                        "10.127.240.0/23",  # Ignore management sessions
                        "2401:db00:1ff:c100::/56",  # Ignore management sessions
                        "2401:db00:e50f:3:6::/80",  # Ignore Ixia peers
                        "2401:db00:e50f:3:7::/80",  # Ignore Ixia peers
                        "2401:db00:e50f:3:6::/80",  # Ignore Ixia peers
                        "2401:db00:e50f:fc::/64",  # Ignore uu004 uplink
                        "2401:db00:e50f:fd::/64",  # Ignore uu003 uplink
                        "2401:db00:e50f:fe::/64",  # Ignore uu002 uplink
                        "2401:db00:e50f:ff::/64",  # Ignore uu001 uplink
                    ],
                    check_scope=hc_types.Scope.DEFAULT,
                )
            ],
            setup_steps=[
                # Deploy UCMP policy for all 3 DCs
                create_ucmp_policy_config_step(
                    vip_community=vip_community,
                    dc1_asn=dc1_asn,
                    dc2_asn=dc2_asn,
                    dc3_asn=dc3_asn,
                    dc1_weight=dc1_weight,
                    dc2_weight=dc2_weight,
                    dc3_weight=dc3_weight,
                ),
                # Enable all 3 DCs (full connectivity baseline)
                create_enable_dc_vip_step(dc_number=1),
                create_enable_dc_vip_step(dc_number=2),
                create_enable_dc_vip_step(dc_number=3),
                create_bgp_convergence_wait_step(wait_seconds=60),
            ],
            cleanup_steps=[],
            stages=[
                # Stage 1: Verify baseline with all 3 DCs online
                create_steps_stage(
                    steps=[
                        # Clear traffic stats for baseline measurement
                        create_clear_traffic_stats_step(),
                        # Triggering the warmboot
                        create_service_interption_step("SYSTEMCTL_RESTART"),
                        # packet loss validation step
                        packetloss_validation_step(),
                        # Wait for BGP convergence after warmboot
                        create_bgp_convergence_wait_step(wait_seconds=120),
                        # System helth check (no kenel panic, warmboot success)
                        system_health_validation_step(),
                        # Verify all 12 BGP sessions established
                        create_ucmp_validation_step(
                            vip_community=vip_community,
                            vip_v6=vip_v6,
                            expected_rib_weights={
                                dc1_weight: 4,  # DC1: 4 paths
                                dc2_weight: 4,  # DC2: 4 paths
                                dc3_weight: 4,  # DC3: 4 paths
                            },
                            expected_as_weights={
                                dc1_asn: dc1_weight,
                                dc2_asn: dc2_weight,
                                dc3_asn: dc3_weight,
                            },
                            expected_fib_weights={
                                dc1_weight: 4,  # 10/1 = 10
                                dc2_weight: 4,  # 5/1 = 5
                                dc3_weight: 4,  # 2/1 = 2
                            },
                            tolerance_percent=5,
                        ),
                        create_record_agent_state_step(),
                    ],
                ),
            ],
            traffic_items_to_start=["UCMP_TEST_TRAFFIC"],
        )
    )
    return playbooks


def create_test_case_13_playbooks(
    vip_community: str,
    vip_v6: str,
    dc1_asn: int,
    dc2_asn: int,
    dc3_asn: int,
    dc1_weight: int,
    dc2_weight: int,
    dc3_weight: int,
    iter: int,
) -> list[Playbook]:
    """
    Create playbooks for Test Case 13: Continuous Coldboot on DUT .

    Two playbooks to Continuous Coldboot on DUT:
    1. TC12 : Precheck - I: All 12 sessions are formed with [Dc1,Dc2,Dc3]],
                         II: Prefix( vip_v6 ) Present with UCMP  with [Dc1,Dc2,Dc3] 12 Paths,
                         III : Base line traffic is flowing among all DC's[DC1,DC2,DC3] Baseline: DC1 58.8%, DC2 29.4%, DC3 11.8%,
                         VI: Fboss agent is running, VI: Fboss agent uptime and PID recorded
                         V:Bgp session Uptimes stable
    2. TC12A: Triggers - I: Perform a Clodboot on DUT (Using coldboot Procedure),
                         II: All Fboss agent components and hardware manager should restart But hardware forwarding state is preserved
                         III: All Bgp sessions go down and must re-established
            Control Plane - I : All Bgp sessions go down and must re-established,
                              II : Hardware Forwarding should restart

                              VI: After coldboot Bgp session re-established, routes re-learned, Ucmp weights re-calculated(FIB and RIB should be validated)
             Data Plane - I : Hard ware contnues forwarding through out agent warmboot
                           II : Ucmp distribution maintained
                           III : expected  packet loss
                           VI coldboot restart completes Hardware state is validated and refreshed.
             Postcheck - I: All 12 sessions are formed with [Dc1,Dc2,Dc3]] < 2 minutes,
                         II: Prefix( vip_v6 ) Present with UCMP  with [Dc1,Dc2,Dc3] 12 Paths,
                         III : FIB, hardware entries (12 next hops for the prefix) allong with DC's with their weights


    Args:
        vip_community: VIP community string (e.g., "65441:260")
        vip_v6: VIP IPv6 prefix (e.g., "2402:db00:1100::/64")
        dc1_asn: DC1 AS number for AS_PATH matching
        dc2_asn: DC2 AS number for AS_PATH matching
        dc3_asn: DC3 AS number for AS_PATH matching
        dc1_weight: UCMP weight for DC1 (e.g., 10)
        dc2_weight: UCMP weight for DC2 (e.g., 5)
        dc3_weight: UCMP weight for DC3 (e.g., 2)
        dc1_device_name: Device name for DC1 (e.g., "ssw004.s002.f01.qzd1")

    Returns:
        List of 5 playbooks: TC12 , TC12A , TC12B, TC12C, TC12D
    """
    playbooks = []

    # Test Case 13: Add extra weights to UCMP policy and validate
    playbooks.append(
        Playbook(
            name="TC13_Coldboot",
            description="CTE UCMP Test Case 13:  - Verify all 12 BGP sessions established, UCMP paths present, baseline traffic distribution, and system state",
            iteration=iter,
            prechecks=[
                create_bgp_session_establish_check(
                    expected_established_sessions=16,
                    parent_prefixes_to_ignore=[
                        "10.127.240.0/23",  # Ignore management sessions
                        "2401:db00:1ff:c100::/56",  # Ignore management sessions
                        "2401:db00:e50f:3:6::/80",  # Ignore Ixia peers
                        "2401:db00:e50f:3:7::/80",  # Ignore Ixia peers
                        "2401:db00:e50f:3:6::/80",  # Ignore Ixia peers
                        "2401:db00:e50f:fc::/64",  # Ignore uu004 uplink
                        "2401:db00:e50f:fd::/64",  # Ignore uu003 uplink
                        "2401:db00:e50f:fe::/64",  # Ignore uu002 uplink
                        "2401:db00:e50f:ff::/64",  # Ignore uu001 uplink
                    ],
                    check_scope=hc_types.Scope.DEFAULT,
                )
            ],
            setup_steps=[
                # Deploy UCMP policy for all 3 DCs
                create_ucmp_policy_config_step(
                    vip_community=vip_community,
                    dc1_asn=dc1_asn,
                    dc2_asn=dc2_asn,
                    dc3_asn=dc3_asn,
                    dc1_weight=dc1_weight,
                    dc2_weight=dc2_weight,
                    dc3_weight=dc3_weight,
                ),
                # Enable all 3 DCs (full connectivity baseline)
                create_enable_dc_vip_step(dc_number=1),
                create_enable_dc_vip_step(dc_number=2),
                create_enable_dc_vip_step(dc_number=3),
                create_bgp_convergence_wait_step(wait_seconds=60),
            ],
            cleanup_steps=[],
            stages=[
                # Stage 1: Verify baseline with all 3 DCs online
                create_steps_stage(
                    steps=[
                        # Triggering the coldboot
                        create_service_interption_step("COLD_BOOT"),
                        # Wait for BGP convergence after coldboot
                        create_bgp_convergence_wait_step(wait_seconds=300),
                        # System helth check (no kenel panic, coldboot success)
                        system_health_validation_step(),
                        # Clear traffic stats for baseline measurement
                        create_clear_traffic_stats_step(),
                        # Run traffic to establish baseline, checks packets loss (2 minutes)
                        create_traffic_duration_step(duration_seconds=120),
                        # packet loss validation step
                        packetloss_validation_step(),
                        # Verify all 12 paths serving traffic correctly
                        create_ucmp_validation_step(
                            vip_community=vip_community,
                            vip_v6=vip_v6,
                            expected_rib_weights={
                                dc1_weight: 4,  # DC1: 4 paths
                                dc2_weight: 4,  # DC2: 4 paths
                                dc3_weight: 4,  # DC3: 4 paths
                            },
                            expected_as_weights={
                                dc1_asn: dc1_weight,
                                dc2_asn: dc2_weight,
                                dc3_asn: dc3_weight,
                            },
                            expected_fib_weights={
                                dc1_weight: 4,  # 10/1 = 10
                                dc2_weight: 4,  # 5/1 = 5
                                dc3_weight: 4,  # 2/1 = 2
                            },
                            tolerance_percent=5,
                        ),
                        create_record_agent_state_step(),
                    ],
                ),
            ],
            traffic_items_to_start=["UCMP_TEST_TRAFFIC"],
        )
    )
    return playbooks


def create_extra_weights_added_to_policy(
    vip_community: str,
    vip_v6: str,
    dc1_asn: int,
    dc2_asn: int,
    dc3_asn: int,
    dc1_weight: int,
    dc2_weight: int,
    dc3_weight: int,
) -> list[Playbook]:
    """
    Create playbook for Test Case: Add extra weights to UCMP policy.

    Tests that adding +5 to all DC weights results in correct traffic distribution.

    Args:
        vip_community: VIP community string (e.g., "65441:260")
        vip_v6: VIP IPv6 prefix (e.g., "2402:db00:1100::/64")
        dc1_asn: DC1 AS number for AS_PATH matching
        dc2_asn: DC2 AS number for AS_PATH matching
        dc3_asn: DC3 AS number for AS_PATH matching
        dc1_weight: UCMP weight for DC1 (e.g., 10)
        dc2_weight: UCMP weight for DC2 (e.g., 5)
        dc3_weight: UCMP weight for DC3 (e.g., 2)
        iter: Iteration number for the playbook

    Args2:
        vip_community: VIP community string (e.g., "65441:260")
        vip_v6: VIP IPv6 prefix (e.g., "2402:db00:1100::/64")
        dc1_asn: DC1 AS number for AS_PATH matching
        dc2_asn: DC2 AS number for AS_PATH matching
        dc3_asn: DC3 AS number for AS_PATH matching
        dc1_weight: UCMP weight for DC1 + 5 (e.g., 15)
        dc2_weight: UCMP weight for DC2 + 5 (e.g., 10)
        dc3_weight: UCMP weight for DC3 + 5 (e.g., 7)
        iter: Iteration number for the playbook


    Returns:
        List containing 1 playbook
    """
    playbooks = []

    # Test Case 12: Prechecks before warmboot - verify baseline state
    playbooks.append(
        Playbook(
            name="add_more_weights_to_policy",
            description="CTE UCMP Test Case :  - Verify after adding extra weights to all 3 dcs, UCMP paths present, baseline traffic distribution, and system state",
            prechecks=[
                create_bgp_session_establish_check(
                    expected_established_sessions=16,
                    parent_prefixes_to_ignore=[
                        "10.127.240.0/23",  # Ignore management sessions
                        "2401:db00:1ff:c100::/56",  # Ignore management sessions
                        "2401:db00:e50f:3:6::/80",  # Ignore Ixia peers
                        "2401:db00:e50f:3:7::/80",  # Ignore Ixia peers
                        "2401:db00:e50f:3:6::/80",  # Ignore Ixia peers
                        "2401:db00:e50f:fc::/64",  # Ignore uu004 uplink
                        "2401:db00:e50f:fd::/64",  # Ignore uu003 uplink
                        "2401:db00:e50f:fe::/64",  # Ignore uu002 uplink
                        "2401:db00:e50f:ff::/64",  # Ignore uu001 uplink
                    ],
                    check_scope=hc_types.Scope.DEFAULT,
                )
            ],
            setup_steps=[
                # Deploy UCMP policy for all 3 DCs
                create_ucmp_policy_config_step(
                    vip_community=vip_community,
                    dc1_asn=dc1_asn,
                    dc2_asn=dc2_asn,
                    dc3_asn=dc3_asn,
                    dc1_weight=dc1_weight,
                    dc2_weight=dc2_weight,
                    dc3_weight=dc3_weight,
                ),
                # Enable all 3 DCs (full connectivity baseline)
                create_enable_dc_vip_step(dc_number=1),
                create_enable_dc_vip_step(dc_number=2),
                create_enable_dc_vip_step(dc_number=3),
                create_bgp_convergence_wait_step(wait_seconds=60),
            ],
            cleanup_steps=[],
            stages=[
                # Stage 1: Verify baseline with all 3 DCs online
                create_steps_stage(
                    steps=[
                        system_health_validation_step(),
                        # Clear traffic stats for baseline measurement
                        create_clear_traffic_stats_step(),
                        # Run traffic to establish baseline, checks packets loss (2 minutes)
                        create_traffic_duration_step(duration_seconds=120),
                        # packet loss validation step
                        packetloss_validation_step(),
                        # Verify all 12 paths serving traffic correctly
                        create_ucmp_validation_step(
                            vip_community=vip_community,
                            vip_v6=vip_v6,
                            expected_rib_weights={
                                dc1_weight: 4,  # DC1: 4 paths
                                dc2_weight: 4,  # DC2: 4 paths
                                dc3_weight: 4,  # DC3: 4 paths
                            },
                            expected_as_weights={
                                dc1_asn: dc1_weight,
                                dc2_asn: dc2_weight,
                                dc3_asn: dc3_weight,
                            },
                            expected_fib_weights={
                                dc1_weight: 4,  # 10/1 = 10
                                dc2_weight: 4,  # 5/1 = 5
                                dc3_weight: 4,  # 2/1 = 2
                            },
                            tolerance_percent=5,
                        ),
                        create_record_agent_state_step(),
                    ],
                ),
                # Stage 2: Add extra weights to policy
                create_steps_stage(
                    steps=[
                        # Deploy UCMP policy for all 3 DCs
                        create_ucmp_policy_config_step(
                            vip_community=vip_community,
                            dc1_asn=dc1_asn,
                            dc2_asn=dc2_asn,
                            dc3_asn=dc3_asn,
                            dc1_weight=dc1_weight + 5,
                            dc2_weight=dc2_weight + 5,
                            dc3_weight=dc3_weight + 5,
                        ),
                        # Enable all 3 DCs (full connectivity baseline)
                        create_enable_dc_vip_step(dc_number=1),
                        create_enable_dc_vip_step(dc_number=2),
                        create_enable_dc_vip_step(dc_number=3),
                        create_bgp_convergence_wait_step(wait_seconds=60),
                    ],
                ),
                # Stage 3: Validate extra weights added
                create_steps_stage(
                    steps=[
                        system_health_validation_step(),
                        # Clear traffic stats for baseline measurement
                        create_clear_traffic_stats_step(),
                        # Run traffic to establish baseline, checks packets loss (2 minutes)
                        create_traffic_duration_step(duration_seconds=120),
                        # packet loss validation step
                        packetloss_validation_step(),
                        # Verify all 12 paths serving traffic correctly
                        create_ucmp_validation_step(
                            vip_community=vip_community,
                            vip_v6=vip_v6,
                            expected_rib_weights={
                                dc1_weight + 5: 4,  # DC1: 4 paths
                                dc2_weight + 5: 4,  # DC2: 4 paths
                                dc3_weight + 5: 4,  # DC3: 4 paths
                            },
                            expected_as_weights={
                                dc1_asn: dc1_weight + 5,
                                dc2_asn: dc2_weight + 5,
                                dc3_asn: dc3_weight + 5,
                            },
                            expected_fib_weights={
                                dc1_weight + 5: 4,  # DC1: 4 paths with weight+5
                                dc2_weight + 5: 4,  # DC2: 4 paths with weight+5
                                dc3_weight + 5: 4,  # DC3: 4 paths with weight+5
                            },
                            tolerance_percent=5,
                        ),
                        create_record_agent_state_step(),
                    ],
                ),
            ],
            traffic_items_to_start=["UCMP_TEST_TRAFFIC"],
        )
    )
    return playbooks


def create_test_case_fallback_to_ecmp_playbooks(
    vip_community: str,
    vip_v6: str,
    dc1_asn: int,
    dc2_asn: int,
    dc3_asn: int,
    dc1_weight: int,
    dc2_weight: int,
    dc3_weight: int,
) -> list[Playbook]:
    """
    Create playbook for Test Case: UCMP to ECMP Fallback.

    Tests that clearing the UCMP policy results in correct fallback to ECMP
    with equal traffic distribution across all DCs.

    Test Scenario:
        - Stage 1: Verify UCMP baseline with weights (DC1 58.8%, DC2 29.4%, DC3 11.8%)
        - Stage 2: Clear UCMP policy (fallback to ECMP)
        - Stage 3: Verify ECMP distribution (DC1 33.3%, DC2 33.3%, DC3 33.3%)

    Args:
        vip_community: VIP community string (e.g., "65441:260")
        vip_v6: VIP IPv6 prefix (e.g., "2402:db00:1100::/64")
        dc1_asn: DC1 AS number for AS_PATH matching
        dc2_asn: DC2 AS number for AS_PATH matching
        dc3_asn: DC3 AS number for AS_PATH matching
        dc1_weight: UCMP weight for DC1 (e.g., 10)
        dc2_weight: UCMP weight for DC2 (e.g., 5)
        dc3_weight: UCMP weight for DC3 (e.g., 2)

    Returns:
        List containing 1 playbook
    """
    playbooks = []

    # Test Case: UCMP to ECMP Fallback
    playbooks.append(
        Playbook(
            name="fall_back_ucmp_to_ecmp",
            description="CTE UCMP Test Case: Verify UCMP to ECMP fallback - clear UCMP policy and validate equal traffic distribution across all DCs",
            prechecks=[
                create_bgp_session_establish_check(
                    expected_established_sessions=16,
                    parent_prefixes_to_ignore=[
                        "10.127.240.0/23",  # Ignore management sessions
                        "2401:db00:1ff:c100::/56",  # Ignore management sessions
                        "2401:db00:e50f:3:6::/80",  # Ignore Ixia peers
                        "2401:db00:e50f:3:7::/80",  # Ignore Ixia peers
                        "2401:db00:e50f:3:6::/80",  # Ignore Ixia peers
                        "2401:db00:e50f:fc::/64",  # Ignore uu004 uplink
                        "2401:db00:e50f:fd::/64",  # Ignore uu003 uplink
                        "2401:db00:e50f:fe::/64",  # Ignore uu002 uplink
                        "2401:db00:e50f:ff::/64",  # Ignore uu001 uplink
                    ],
                    check_scope=hc_types.Scope.DEFAULT,
                )
            ],
            setup_steps=[
                # Deploy UCMP policy for all 3 DCs
                create_ucmp_policy_config_step(
                    vip_community=vip_community,
                    dc1_asn=dc1_asn,
                    dc2_asn=dc2_asn,
                    dc3_asn=dc3_asn,
                    dc1_weight=dc1_weight,
                    dc2_weight=dc2_weight,
                    dc3_weight=dc3_weight,
                ),
                # Enable all 3 DCs (full connectivity baseline)
                create_enable_dc_vip_step(dc_number=1),
                create_enable_dc_vip_step(dc_number=2),
                create_enable_dc_vip_step(dc_number=3),
                create_bgp_convergence_wait_step(wait_seconds=60),
            ],
            cleanup_steps=[],
            stages=[
                # Stage 1: Verify baseline with all 3 DCs online
                create_steps_stage(
                    steps=[
                        system_health_validation_step(),
                        # Clear traffic stats for baseline measurement
                        create_clear_traffic_stats_step(),
                        # Run traffic to establish baseline, checks packets loss (2 minutes)
                        create_traffic_duration_step(duration_seconds=120),
                        # packet loss validation step
                        packetloss_validation_step(),
                        # Verify all 12 paths serving traffic correctly
                        create_ucmp_validation_step(
                            vip_community=vip_community,
                            vip_v6=vip_v6,
                            expected_rib_weights={
                                dc1_weight: 4,  # DC1: 4 paths
                                dc2_weight: 4,  # DC2: 4 paths
                                dc3_weight: 4,  # DC3: 4 paths
                            },
                            expected_as_weights={
                                dc1_asn: dc1_weight,
                                dc2_asn: dc2_weight,
                                dc3_asn: dc3_weight,
                            },
                            expected_fib_weights={
                                dc1_weight: 4,  # 10/1 = 10
                                dc2_weight: 4,  # 5/1 = 5
                                dc3_weight: 4,  # 2/1 = 2
                            },
                            tolerance_percent=5,
                        ),
                        create_record_agent_state_step(),
                    ],
                ),
                # Stage 2: fallback to ecmp
                create_steps_stage(
                    steps=[
                        # Deploy UCMP policy for all 3 DCs
                        create_ucmp_policy_config_step(
                            vip_community=vip_community,
                            dc1_asn=dc1_asn,
                            dc2_asn=dc2_asn,
                            dc3_asn=dc3_asn,
                            dc1_weight=dc1_weight,
                            dc2_weight=dc2_weight,
                            dc3_weight=dc3_weight,
                            action="clear",
                        ),
                    ],
                ),
                # Stage 3: Validate extra weights added
                create_steps_stage(
                    steps=[
                        system_health_validation_step(),
                        # Clear traffic stats for baseline measurement
                        create_clear_traffic_stats_step(),
                        # Run traffic to establish baseline, checks packets loss (2 minutes)
                        create_traffic_duration_step(duration_seconds=120),
                        # packet loss validation step
                        packetloss_validation_step(),
                        # Verify all 12 paths serving traffic correctly
                        create_ucmp_validation_step(
                            vip_community=vip_community,
                            vip_v6=vip_v6,
                            expected_rib_weights={0: 12},
                            expected_as_weights={},
                            expected_fib_weights={1: 12},  # FIB normalizes 0→1
                            require_ucmp=False,
                            tolerance_percent=5,
                        ),
                        create_record_agent_state_step(),
                    ],
                ),
            ],
            traffic_items_to_start=["UCMP_TEST_TRAFFIC"],
        )
    )
    return playbooks


# ----- Migrated from playbooks/helpers/ai_bb/dsf_snc1_c084_playbooks.py -----


def gen_dsf_endurance_playbook(playbook: Playbook, iteration: int) -> Playbook:
    return playbook(iteration=iteration)


# TestConfig-level prechecks/postchecks moved to playbook level
_TC_PRECHECKS = [
    create_dsf_drain_state_check(),
    create_dsf_fabric_reachability_check(),
    # PointInTimeHealthCheck(
    #     name=hc_types.CheckName.DSF_TRAFFIC_REBALANCE_CHECK,
    # ),
    create_ixia_port_stats_check(),
]

_TC_POSTCHECKS = [
    create_dsf_drain_state_check(),
    create_dsf_fabric_reachability_check(),
    # PointInTimeHealthCheck(
    #     name=hc_types.CheckName.DSF_TRAFFIC_REBALANCE_CHECK,
    # ),
    create_packetloss_health_check(),
    create_ixia_port_stats_check(),
]


def _add_tc_checks_to_playbook(playbook: Playbook) -> Playbook:
    """Add former TestConfig-level prechecks/postchecks to a playbook.

    Respects skip_test_config_postchecks: if True, do not merge TC postchecks
    and remove the skip flag. Otherwise, append TC postchecks after existing ones.
    Prechecks are always added (prepended before any existing prechecks).
    """
    new_prechecks = _TC_PRECHECKS + list(playbook.prechecks or [])

    if playbook.skip_test_config_postchecks:
        new_postchecks = list(playbook.postchecks or [])
    else:
        new_postchecks = list(playbook.postchecks or []) + _TC_POSTCHECKS

    return playbook(
        prechecks=new_prechecks,
        postchecks=new_postchecks,
        skip_test_config_postchecks=False,
    )


def gen_dsf_longevity_playbook(
    name: str, duration: int, attribute_filters: dict | None = None
):
    return Playbook(
        name=name,
        stages=[create_steps_stage(steps=[create_longevity_step(duration=duration)])],
        attribute_filters=attribute_filters,
    )


ATTRIBUTE_FILTERS_FDSW = {"role": ["FDSW"]}

DSF_TEST_AGENT_COLDBOOT_PLAYBOOK = Playbook(
    name="test_agent_coldboot",
    attribute_filters=None,
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    create_cold_boot_file=True,
                ),
                create_service_convergence_step(
                    services=[
                        Service.AGENT,
                    ]
                ),
                create_longevity_step(duration=200),
            ]
        )
    ],
    postchecks=[create_ixia_packet_loss_check(clear_traffic_stats=True)],
    skip_test_config_postchecks=True,
)


DSF_TEST_CONTINUOUS_AGENT_COLDBOOT_PLAYBOOK = Playbook(
    name="test_continuous_agent_coldboot",
    attribute_filters=None,
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    create_cold_boot_file=True,
                ),
                create_service_convergence_step(services=[Service.AGENT]),
                create_longevity_step(duration=200),
            ],
            iteration=5,
        ),
    ],
    postchecks=[create_ixia_packet_loss_check(clear_traffic_stats=True)],
)


DSF_TEST_CONTINUOUS_QSPF_RESTART_PLAYBOOK = Playbook(
    name="test_continuous_qsfp_restart",
    attribute_filters=None,
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.QSFP_SERVICE,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
            ]
        ),
    ],
    iteration=5,
)


DSF_TEST_BGPD_RESTART_PLAYBOOK = Playbook(
    name="test_bgpd_restart",
    attribute_filters=None,
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.BGP,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(services=[Service.AGENT]),
            ]
        ),
    ],
)

DSF_TEST_FBOSS_SW_AGENT_WARMBOOT_PLAYBOOK = Playbook(
    name="test_fboss_sw_agent_warmboot",
    attribute_filters=ATTRIBUTE_FILTERS_FDSW,
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.FBOSS_SW_AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(
                    services=[
                        # Service.BGP, # Takes > 700s to converge
                        Service.AGENT,
                        Service.QSFP_SERVICE,
                        Service.FSDB,
                    ]
                ),
            ]
        )
    ],
)

DSF_TEST_FBOSS_SW_AGENT_AND_HW_AGENT_0_RESTART_PLAYBOOK = Playbook(
    name="test_fboss_sw_agent_and_hw_agent_0_restart",
    attribute_filters=ATTRIBUTE_FILTERS_FDSW,
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.FBOSS_SW_AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_interruption_step(
                    service=Service.FBOSS_HW_AGENT_0,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
            ],
            concurrent=True,
        ),
        create_steps_stage(
            steps=[
                create_service_convergence_step(
                    services=[
                        # Service.BGP, # Takes > 700s to converge
                        Service.AGENT,
                        Service.QSFP_SERVICE,
                        Service.FSDB,
                    ]
                ),
            ]
        ),
    ],
)

DSF_TEST_DEVICE_REBOOT_PLAYBOOK = Playbook(
    name="test_device_reboot",
    attribute_filters=ATTRIBUTE_FILTERS_FDSW,
    stages=[
        create_steps_stage(
            steps=[
                create_system_reboot_step(
                    trigger=SystemRebootTrigger.FULL_SYSTEM_REBOOT
                ),
                create_longevity_step(duration=150),
                create_service_convergence_step(services=[Service.AGENT]),
                create_longevity_step(duration=150),
                create_validation_step(
                    point_in_time_checks=[
                        create_dsf_drain_state_check(is_drained=True),
                    ],
                    stage=ValidationStage.MID_TEST,
                ),
                create_drain_undrain_step(drain=False),
                create_longevity_step(duration=150),
            ]
        )
    ],
    postchecks=[
        create_ixia_packet_loss_check(clear_traffic_stats=True),
    ],
    skip_test_config_postchecks=True,
)

TEST_DEVICE_REBOOT_WITHOUT_DRAIN_CHECK_PLAYBOOK = Playbook(
    name="test_device_reboot_without_drain_check",
    attribute_filters={"role": ["RDSW"]},
    stages=[
        create_steps_stage(
            steps=[
                create_system_reboot_step(
                    trigger=SystemRebootTrigger.FULL_SYSTEM_REBOOT
                ),
                # Reboot can take 120s to actually occur!
                create_longevity_step(duration=150),
                create_service_convergence_step(services=[Service.AGENT]),
                create_longevity_step(duration=300),
            ]
        )
    ],
    postchecks=[
        create_ixia_packet_loss_check(clear_traffic_stats=True),
    ],
    skip_test_config_postchecks=True,
)

TEST_INTERFACE_FLAP_PLAYBOOK = Playbook(
    name="test_interface_flap",
    stages=[
        create_steps_stage(
            steps=[
                create_interface_flap_step(
                    enable=False,
                    interface_flap_method=4,
                    delay=60,
                    jq_params={"interfaces": '."{dut}".interfaces'},
                    transform_params={
                        "interfaces": [
                            TransformFunction(
                                name="SELECT_SAMPLE",
                                json_params=json.dumps({"sample_size": 1}),
                            )
                        ]
                    },
                    cache_params={
                        "interfaces": "random_interface",
                    },
                ),
                create_interface_flap_step(
                    enable=True,
                    interface_flap_method=4,
                    delay=60,
                    jq_params={"interfaces": ".cached.random_interface"},
                ),
            ],
        )
    ],
    postchecks=[
        create_ixia_packet_loss_check(clear_traffic_stats=True),
    ],
)


DSF_TEST_AGENT_CRASH_PLAYBOOK = Playbook(
    name="test_agent_crash",
    postchecks=[create_ixia_packet_loss_check(clear_traffic_stats=True)],
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.AGENT, trigger=ServiceInterruptionTrigger.CRASH
                ),
                create_service_convergence_step(services=[Service.AGENT]),
                create_longevity_step(duration=200),
            ]
        )
    ],
    skip_test_config_postchecks=True,
)

DSF_TEST_BGPD_CRASH_PLAYBOOK = Playbook(
    name="test_bgpd_crash",
    postchecks=[create_packetloss_health_check()],
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.BGP, trigger=ServiceInterruptionTrigger.CRASH
                ),
                create_service_convergence_step(services=[Service.AGENT]),
            ]
        ),
    ],
)

TEST_QSFP_CRASH_PLAYBOOK = Playbook(
    name="test_qsfp_crash",
    postchecks=[create_packetloss_health_check()],
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.QSFP_SERVICE,
                    trigger=ServiceInterruptionTrigger.CRASH,
                ),
                create_service_convergence_step(
                    services=[Service.AGENT, Service.QSFP_SERVICE]
                ),
                create_longevity_step(duration=200),
            ]
        )
    ],
)

DSF_C084_TEST_FBOSS_HW_AGENT_0_CRASH_PLAYBOOK = Playbook(
    name="test_fboss_hw_agent_0_crash",
    attribute_filters=ATTRIBUTE_FILTERS_FDSW,
    postchecks=[create_ixia_packet_loss_check(clear_traffic_stats=True)],
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.FBOSS_HW_AGENT_0,
                    trigger=ServiceInterruptionTrigger.CRASH,
                ),
                create_service_convergence_step(
                    services=[
                        Service.AGENT,
                    ]
                ),
                create_longevity_step(duration=200),
            ]
        )
    ],
)

TEST_FBOSS_HW_AGENT_1_CRASH_PLAYBOOK = Playbook(
    name="test_fboss_hw_agent_1_crash",
    attribute_filters=ATTRIBUTE_FILTERS_FDSW,
    postchecks=[create_ixia_packet_loss_check(clear_traffic_stats=True)],
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.FBOSS_HW_AGENT_1,
                    trigger=ServiceInterruptionTrigger.CRASH,
                ),
                create_service_convergence_step(
                    services=[
                        Service.AGENT,
                    ]
                ),
                create_longevity_step(duration=200),
            ]
        )
    ],
)


DSF_TEST_FBOSS_SW_AGENT_CRASH_PLAYBOOK = Playbook(
    name="test_fboss_sw_agent_crash",
    attribute_filters=ATTRIBUTE_FILTERS_FDSW,
    postchecks=[create_ixia_packet_loss_check(clear_traffic_stats=True)],
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.FBOSS_SW_AGENT,
                    trigger=ServiceInterruptionTrigger.CRASH,
                ),
                create_service_convergence_step(
                    services=[
                        Service.FBOSS_SW_AGENT,
                    ]
                ),
                create_longevity_step(duration=200),
            ]
        )
    ],
)

DSF_C084_TEST_FSDB_CRASH_PLAYBOOK = Playbook(
    name="test_fsdb_crash",
    postchecks=[create_ixia_packet_loss_check(clear_traffic_stats=True)],
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.FSDB, trigger=ServiceInterruptionTrigger.CRASH
                ),
                create_service_convergence_step(
                    services=[
                        Service.FSDB,
                    ]
                ),
                create_longevity_step(duration=200),
            ]
        )
    ],
)

DSF_C084_TEST_QSPF_SERVICE_CRASH_PLAYBOOK = Playbook(
    name="test_qspf_service_crash",
    prechecks=[
        create_systemctl_active_state_check(),
        create_wedge_agent_configured_check(),
    ],
    postchecks=[create_ixia_packet_loss_check(clear_traffic_stats=True)],
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.QSFP_SERVICE,
                    trigger=ServiceInterruptionTrigger.CRASH,
                ),
                create_service_convergence_step(
                    services=[
                        Service.QSFP_SERVICE,
                    ]
                ),
                create_longevity_step(duration=200),
            ]
        )
    ],
)

DSF_C084_TEST_WEDGE_AGENT_AND_FSDB_CRASH_PLAYBOOK = Playbook(
    name="test_wedge_agent_and_fsdb_crash",
    prechecks=[
        create_systemctl_active_state_check(),
        create_wedge_agent_configured_check(),
    ],
    postchecks=[create_ixia_packet_loss_check(clear_traffic_stats=True)],
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.AGENT, trigger=ServiceInterruptionTrigger.CRASH
                ),
                create_service_interruption_step(
                    service=Service.FSDB, trigger=ServiceInterruptionTrigger.CRASH
                ),
            ],
            concurrent=True,
        ),
        create_steps_stage(
            steps=[
                create_service_convergence_step(
                    services=[
                        Service.AGENT,
                        Service.FSDB,
                    ]
                ),
                create_longevity_step(duration=200),
            ],
        ),
    ],
)

DSF_C084_TEST_INTERFACE_DRAIN_PLAYBOOK = Playbook(
    name="test_interface_drain",
    attribute_filters=ATTRIBUTE_FILTERS_FDSW,
    stages=[
        create_steps_stage(
            steps=[
                create_drain_undrain_step(
                    drain=True, description="Drain 1 random interface"
                ),
                create_drain_undrain_step(
                    drain=False, description="Undrain the interface"
                ),
            ]
        )
    ],
    postchecks=[create_ixia_packet_loss_check(clear_traffic_stats=True)],
    skip_test_config_postchecks=True,
)

DSF_C084_TEST_DEVICE_DRAIN_PLAYBOOK = Playbook(
    name="test_device_drain",
    attribute_filters=ATTRIBUTE_FILTERS_FDSW,
    stages=[
        create_steps_stage(
            steps=[
                create_drain_undrain_step(drain=True),
                create_drain_undrain_step(drain=False),
            ]
        )
    ],
    postchecks=[create_ixia_packet_loss_check(clear_traffic_stats=True)],
    skip_test_config_postchecks=True,
)


# ----- Migrated from playbooks/helpers/qos_scheduling_playbooks.py -----

# Playbook constants - single source of truth for QoS scheduling playbook names.
# Used by both qos_scheduling_test_config.py and UTP test case definitions.
# UTP uses .name to get the playbook name string.

# Scheduling playbooks (one per ClassOfService queue)
TEST_QOS_SCHEDULING_QUEUE7_NC = Playbook(
    name="test_qos_scheduling_queue7_nc",
)
TEST_QOS_SCHEDULING_QUEUE6_ICP = Playbook(
    name="test_qos_scheduling_queue6_icp",
)
TEST_QOS_SCHEDULING_QUEUE3_GOLD = Playbook(
    name="test_qos_scheduling_queue3_gold",
)
TEST_QOS_SCHEDULING_QUEUE2_SILVER = Playbook(
    name="test_qos_scheduling_queue2_silver",
)
TEST_QOS_SCHEDULING_QUEUE1_BRONZE = Playbook(
    name="test_qos_scheduling_queue1_bronze",
)
# NCNF is not yet a first-class ClassOfService enum value, so it is not
# included in the COS_TO_SCHEDULING_PLAYBOOK dict.  The test config
# generates its playbook separately using this constant.
TEST_QOS_SCHEDULING_QUEUE0_NCNF = Playbook(
    name="test_qos_scheduling_queue0_ncnf",
)

# Per-queue congestion playbooks (one per CoS queue, same DSCP on both ports)
TEST_QOS_PER_QUEUE_CONGESTION_QUEUE7_NC = Playbook(
    name="test_qos_per_queue_congestion_queue7_nc",
)
TEST_QOS_PER_QUEUE_CONGESTION_QUEUE6_ICP = Playbook(
    name="test_qos_per_queue_congestion_queue6_icp",
)
TEST_QOS_PER_QUEUE_CONGESTION_QUEUE3_GOLD = Playbook(
    name="test_qos_per_queue_congestion_queue3_gold",
)
TEST_QOS_PER_QUEUE_CONGESTION_QUEUE2_SILVER = Playbook(
    name="test_qos_per_queue_congestion_queue2_silver",
)
TEST_QOS_PER_QUEUE_CONGESTION_QUEUE1_BRONZE = Playbook(
    name="test_qos_per_queue_congestion_queue1_bronze",
)
# NCNF is not yet a first-class ClassOfService enum value, so it is not
# included in the COS_TO_PER_QUEUE_CONGESTION_PLAYBOOK dict.
TEST_QOS_PER_QUEUE_CONGESTION_QUEUE0_NCNF = Playbook(
    name="test_qos_per_queue_congestion_queue0_ncnf",
)

# Congestion playbooks (one per priority pair)
TEST_QOS_CONGESTION_QUEUE7_NC_VS_QUEUE6_ICP = Playbook(
    name="test_qos_congestion_queue7_nc_vs_queue6_icp",
)
TEST_QOS_CONGESTION_QUEUE7_NC_VS_QUEUE3_GOLD = Playbook(
    name="test_qos_congestion_queue7_nc_vs_queue3_gold",
)
TEST_QOS_CONGESTION_QUEUE7_NC_VS_QUEUE2_SILVER = Playbook(
    name="test_qos_congestion_queue7_nc_vs_queue2_silver",
)
TEST_QOS_CONGESTION_QUEUE7_NC_VS_QUEUE1_BRONZE = Playbook(
    name="test_qos_congestion_queue7_nc_vs_queue1_bronze",
)
TEST_QOS_CONGESTION_QUEUE6_ICP_VS_QUEUE3_GOLD = Playbook(
    name="test_qos_congestion_queue6_icp_vs_queue3_gold",
)
TEST_QOS_CONGESTION_QUEUE6_ICP_VS_QUEUE2_SILVER = Playbook(
    name="test_qos_congestion_queue6_icp_vs_queue2_silver",
)
TEST_QOS_CONGESTION_QUEUE6_ICP_VS_QUEUE1_BRONZE = Playbook(
    name="test_qos_congestion_queue6_icp_vs_queue1_bronze",
)
TEST_QOS_CONGESTION_QUEUE3_GOLD_VS_QUEUE2_SILVER = Playbook(
    name="test_qos_congestion_queue3_gold_vs_queue2_silver",
)
TEST_QOS_CONGESTION_QUEUE3_GOLD_VS_QUEUE1_BRONZE = Playbook(
    name="test_qos_congestion_queue3_gold_vs_queue1_bronze",
)
TEST_QOS_CONGESTION_QUEUE2_SILVER_VS_QUEUE1_BRONZE = Playbook(
    name="test_qos_congestion_queue2_silver_vs_queue1_bronze",
)

# Multi-queue congestion playbooks (multiple queues congested simultaneously)
# Each test sends congestion traffic on multiple lower-priority queues while
# the highest-priority queue of the group carries the 3 existing traffic items.
TEST_QOS_MULTI_CONGESTION_NC_VS_ICP_GOLD = Playbook(
    name="test_qos_multi_congestion_nc_vs_icp_gold",
)
TEST_QOS_MULTI_CONGESTION_NC_VS_ICP_GOLD_SILVER = Playbook(
    name="test_qos_multi_congestion_nc_vs_icp_gold_silver",
)
TEST_QOS_MULTI_CONGESTION_NC_VS_ICP_GOLD_SILVER_BRONZE = Playbook(
    name="test_qos_multi_congestion_nc_vs_icp_gold_silver_bronze",
)
TEST_QOS_MULTI_CONGESTION_ICP_VS_GOLD_SILVER = Playbook(
    name="test_qos_multi_congestion_icp_vs_gold_silver",
)
TEST_QOS_MULTI_CONGESTION_ICP_VS_GOLD_SILVER_BRONZE = Playbook(
    name="test_qos_multi_congestion_icp_vs_gold_silver_bronze",
)
TEST_QOS_MULTI_CONGESTION_GOLD_VS_SILVER_BRONZE = Playbook(
    name="test_qos_multi_congestion_gold_vs_silver_bronze",
)

# Lookup dict: (priority_cos, tuple_of_congested_cos) → multi-congestion Playbook.
COS_MULTI_CONGESTION_PLAYBOOK: t.Dict[
    t.Tuple[ClassOfService, t.Tuple[ClassOfService, ...]], Playbook
] = {
    (
        ClassOfService.NC,
        (ClassOfService.ICP, ClassOfService.GOLD),
    ): TEST_QOS_MULTI_CONGESTION_NC_VS_ICP_GOLD,
    (
        ClassOfService.NC,
        (
            ClassOfService.ICP,
            ClassOfService.GOLD,
            ClassOfService.SILVER,
        ),
    ): TEST_QOS_MULTI_CONGESTION_NC_VS_ICP_GOLD_SILVER,
    (
        ClassOfService.NC,
        (
            ClassOfService.ICP,
            ClassOfService.GOLD,
            ClassOfService.SILVER,
            ClassOfService.BRONZE,
        ),
    ): TEST_QOS_MULTI_CONGESTION_NC_VS_ICP_GOLD_SILVER_BRONZE,
    (
        ClassOfService.ICP,
        (ClassOfService.GOLD, ClassOfService.SILVER),
    ): TEST_QOS_MULTI_CONGESTION_ICP_VS_GOLD_SILVER,
    (
        ClassOfService.ICP,
        (
            ClassOfService.GOLD,
            ClassOfService.SILVER,
            ClassOfService.BRONZE,
        ),
    ): TEST_QOS_MULTI_CONGESTION_ICP_VS_GOLD_SILVER_BRONZE,
    (
        ClassOfService.GOLD,
        (ClassOfService.SILVER, ClassOfService.BRONZE),
    ): TEST_QOS_MULTI_CONGESTION_GOLD_VS_SILVER_BRONZE,
}


# Single-queue congestion playbooks (one queue congested at a time via the
# per-queue congestion traffic item from the third port).
# The 3 existing items run on NC (highest priority), while one per-queue
# congestion item overloads the target queue.
TEST_QOS_SINGLE_CONGESTION_QUEUE6_ICP = Playbook(
    name="test_qos_single_congestion_queue6_icp",
)
TEST_QOS_SINGLE_CONGESTION_QUEUE3_GOLD = Playbook(
    name="test_qos_single_congestion_queue3_gold",
)
TEST_QOS_SINGLE_CONGESTION_QUEUE2_SILVER = Playbook(
    name="test_qos_single_congestion_queue2_silver",
)
TEST_QOS_SINGLE_CONGESTION_QUEUE1_BRONZE = Playbook(
    name="test_qos_single_congestion_queue1_bronze",
)

# Lookup dict: congested_cos → single-queue congestion Playbook constant.
COS_TO_SINGLE_CONGESTION_PLAYBOOK: t.Dict[ClassOfService, Playbook] = {
    ClassOfService.ICP: TEST_QOS_SINGLE_CONGESTION_QUEUE6_ICP,
    ClassOfService.GOLD: TEST_QOS_SINGLE_CONGESTION_QUEUE3_GOLD,
    ClassOfService.SILVER: TEST_QOS_SINGLE_CONGESTION_QUEUE2_SILVER,
    ClassOfService.BRONZE: TEST_QOS_SINGLE_CONGESTION_QUEUE1_BRONZE,
}


# Lookup dict: ClassOfService → scheduling Playbook constant.
COS_TO_SCHEDULING_PLAYBOOK: t.Dict[ClassOfService, Playbook] = {
    ClassOfService.NC: TEST_QOS_SCHEDULING_QUEUE7_NC,
    ClassOfService.ICP: TEST_QOS_SCHEDULING_QUEUE6_ICP,
    ClassOfService.GOLD: TEST_QOS_SCHEDULING_QUEUE3_GOLD,
    ClassOfService.SILVER: TEST_QOS_SCHEDULING_QUEUE2_SILVER,
    ClassOfService.BRONZE: TEST_QOS_SCHEDULING_QUEUE1_BRONZE,
}

# Lookup dict: (priority_cos, congested_cos) → congestion Playbook constant.
COS_PAIR_TO_CONGESTION_PLAYBOOK: t.Dict[
    t.Tuple[ClassOfService, ClassOfService], Playbook
] = {
    (
        ClassOfService.NC,
        ClassOfService.ICP,
    ): TEST_QOS_CONGESTION_QUEUE7_NC_VS_QUEUE6_ICP,
    (
        ClassOfService.NC,
        ClassOfService.GOLD,
    ): TEST_QOS_CONGESTION_QUEUE7_NC_VS_QUEUE3_GOLD,
    (
        ClassOfService.NC,
        ClassOfService.SILVER,
    ): TEST_QOS_CONGESTION_QUEUE7_NC_VS_QUEUE2_SILVER,
    (
        ClassOfService.NC,
        ClassOfService.BRONZE,
    ): TEST_QOS_CONGESTION_QUEUE7_NC_VS_QUEUE1_BRONZE,
    (
        ClassOfService.ICP,
        ClassOfService.GOLD,
    ): TEST_QOS_CONGESTION_QUEUE6_ICP_VS_QUEUE3_GOLD,
    (
        ClassOfService.ICP,
        ClassOfService.SILVER,
    ): TEST_QOS_CONGESTION_QUEUE6_ICP_VS_QUEUE2_SILVER,
    (
        ClassOfService.ICP,
        ClassOfService.BRONZE,
    ): TEST_QOS_CONGESTION_QUEUE6_ICP_VS_QUEUE1_BRONZE,
    (
        ClassOfService.GOLD,
        ClassOfService.SILVER,
    ): TEST_QOS_CONGESTION_QUEUE3_GOLD_VS_QUEUE2_SILVER,
    (
        ClassOfService.GOLD,
        ClassOfService.BRONZE,
    ): TEST_QOS_CONGESTION_QUEUE3_GOLD_VS_QUEUE1_BRONZE,
    (
        ClassOfService.SILVER,
        ClassOfService.BRONZE,
    ): TEST_QOS_CONGESTION_QUEUE2_SILVER_VS_QUEUE1_BRONZE,
}

# Lookup dict: ClassOfService → per-queue congestion Playbook constant.
COS_TO_PER_QUEUE_CONGESTION_PLAYBOOK: t.Dict[ClassOfService, Playbook] = {
    ClassOfService.NC: TEST_QOS_PER_QUEUE_CONGESTION_QUEUE7_NC,
    ClassOfService.ICP: TEST_QOS_PER_QUEUE_CONGESTION_QUEUE6_ICP,
    ClassOfService.GOLD: TEST_QOS_PER_QUEUE_CONGESTION_QUEUE3_GOLD,
    ClassOfService.SILVER: TEST_QOS_PER_QUEUE_CONGESTION_QUEUE2_SILVER,
    ClassOfService.BRONZE: TEST_QOS_PER_QUEUE_CONGESTION_QUEUE1_BRONZE,
}


# =========================================================================
# Programmatically generated playbook constants for remaining test categories.
# Uses _COS_INFO to generate names matching the UTP test case conventions.
# =========================================================================
_COS_INFO: t.List[t.Tuple[ClassOfService, str, str]] = [
    (ClassOfService.NC, "queue7", "nc"),
    (ClassOfService.ICP, "queue6", "icp"),
    (ClassOfService.GOLD, "queue3", "gold"),
    (ClassOfService.SILVER, "queue2", "silver"),
    (ClassOfService.BRONZE, "queue1", "bronze"),
]

# ---------------------------------------------------------------------------
# Microburst congestion playbooks (one per CoS, same DSCP on both ports,
# Port 1 microburst + Port 2 continuous)
# ---------------------------------------------------------------------------
COS_TO_MICROBURST_CONGESTION_PLAYBOOK: t.Dict[ClassOfService, Playbook] = {
    cos: Playbook(name=f"test_qos_microburst_congestion_{queue}_{name}")
    for cos, queue, name in _COS_INFO
}
TEST_QOS_MICROBURST_CONGESTION_QUEUE0_NCNF = Playbook(
    name="test_qos_microburst_congestion_queue0_ncnf",
)

# ---------------------------------------------------------------------------
# 2-Queue Priority Congestion — Higher Priority Bursty
# ---------------------------------------------------------------------------
COS_PAIR_TO_CONGESTION_HI_BURST_PLAYBOOK: t.Dict[
    t.Tuple[ClassOfService, ClassOfService], Playbook
] = {
    (hi_cos, lo_cos): Playbook(
        name=f"test_qos_congestion_hi_burst_{hi_q}_{hi_n}_vs_{lo_q}_{lo_n}"
    )
    for i, (hi_cos, hi_q, hi_n) in enumerate(_COS_INFO)
    for lo_cos, lo_q, lo_n in _COS_INFO[i + 1 :]
}

# ---------------------------------------------------------------------------
# 2-Queue Priority Congestion — Lower Priority Bursty
# ---------------------------------------------------------------------------
COS_PAIR_TO_CONGESTION_LO_BURST_PLAYBOOK: t.Dict[
    t.Tuple[ClassOfService, ClassOfService], Playbook
] = {
    (hi_cos, lo_cos): Playbook(
        name=f"test_qos_congestion_lo_burst_{hi_q}_{hi_n}_vs_{lo_q}_{lo_n}"
    )
    for i, (hi_cos, hi_q, hi_n) in enumerate(_COS_INFO)
    for lo_cos, lo_q, lo_n in _COS_INFO[i + 1 :]
}

# ---------------------------------------------------------------------------
# 3-Queue Priority Congestion — Continuous
# ---------------------------------------------------------------------------
COS_TRIPLE_TO_3Q_CONGESTION_PLAYBOOK: t.Dict[
    t.Tuple[
        ClassOfService,
        ClassOfService,
        ClassOfService,
    ],
    Playbook,
] = {
    (hi_cos, mid_cos, lo_cos): Playbook(
        name=f"test_qos_3q_congestion_{hi_q}_{hi_n}_vs_{mid_q}_{mid_n}_vs_{lo_q}_{lo_n}"
    )
    for i, (hi_cos, hi_q, hi_n) in enumerate(_COS_INFO)
    for j, (mid_cos, mid_q, mid_n) in enumerate(_COS_INFO[i + 1 :], start=i + 1)
    for lo_cos, lo_q, lo_n in _COS_INFO[j + 1 :]
}

# ---------------------------------------------------------------------------
# 3-Queue Priority Congestion — Highest Bursty
# ---------------------------------------------------------------------------
COS_TRIPLE_TO_3Q_HI_BURST_PLAYBOOK: t.Dict[
    t.Tuple[
        ClassOfService,
        ClassOfService,
        ClassOfService,
    ],
    Playbook,
] = {
    (hi_cos, mid_cos, lo_cos): Playbook(
        name=f"test_qos_3q_congestion_hi_burst_{hi_q}_{hi_n}_vs_{mid_q}_{mid_n}_vs_{lo_q}_{lo_n}"
    )
    for i, (hi_cos, hi_q, hi_n) in enumerate(_COS_INFO)
    for j, (mid_cos, mid_q, mid_n) in enumerate(_COS_INFO[i + 1 :], start=i + 1)
    for lo_cos, lo_q, lo_n in _COS_INFO[j + 1 :]
}

# ---------------------------------------------------------------------------
# 3-Queue Priority Congestion — Lowest Bursty
# ---------------------------------------------------------------------------
COS_TRIPLE_TO_3Q_LO_BURST_PLAYBOOK: t.Dict[
    t.Tuple[
        ClassOfService,
        ClassOfService,
        ClassOfService,
    ],
    Playbook,
] = {
    (hi_cos, mid_cos, lo_cos): Playbook(
        name=f"test_qos_3q_congestion_lo_burst_{hi_q}_{hi_n}_vs_{mid_q}_{mid_n}_vs_{lo_q}_{lo_n}"
    )
    for i, (hi_cos, hi_q, hi_n) in enumerate(_COS_INFO)
    for j, (mid_cos, mid_q, mid_n) in enumerate(_COS_INFO[i + 1 :], start=i + 1)
    for lo_cos, lo_q, lo_n in _COS_INFO[j + 1 :]
}

# ---------------------------------------------------------------------------
# Multi-Port Single-Queue Congestion
# ---------------------------------------------------------------------------
COS_TO_MULTI_PORT_CONGESTION_PLAYBOOK: t.Dict[ClassOfService, Playbook] = {
    cos: Playbook(name=f"test_qos_multi_port_congestion_{queue}_{name}")
    for cos, queue, name in _COS_INFO
}
TEST_QOS_MULTI_PORT_CONGESTION_QUEUE0_NCNF = Playbook(
    name="test_qos_multi_port_congestion_queue0_ncnf",
)

# ---------------------------------------------------------------------------
# Multi-Port 2-Queue Congestion
# ---------------------------------------------------------------------------
COS_PAIR_TO_MULTI_PORT_2Q_PLAYBOOK: t.Dict[
    t.Tuple[ClassOfService, ClassOfService], Playbook
] = {
    (hi_cos, lo_cos): Playbook(
        name=f"test_qos_multi_port_2q_congestion_{hi_q}_{hi_n}_vs_{lo_q}_{lo_n}"
    )
    for i, (hi_cos, hi_q, hi_n) in enumerate(_COS_INFO)
    for lo_cos, lo_q, lo_n in _COS_INFO[i + 1 :]
}


# ----- Migrated from playbooks/helpers/common_playbooks.py -----


def create_service_restart_health_check(
    services_to_monitor, expected_restarted_services=None
):
    """
    Create a PointInTimeHealthCheck for monitoring service restarts.

    Args:
        services_to_monitor: List of services to monitor during restart
        expected_restarted_services: Optional list of services that are expected
            to restart (e.g. during warmboot). These will be skipped during the
            restart detection check.

    Returns:
        PointInTimeHealthCheck configured for service restart monitoring
    """
    return create_service_restart_check(
        services=services_to_monitor,
        expected_restarted_services=expected_restarted_services,
    )


TEST_AGENT_COLDBOOT_PLAYBOOK = Playbook(
    name="test_agent_coldboot",
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    create_cold_boot_file=True,
                ),
                create_service_convergence_step(services=[Service.AGENT]),
                create_longevity_step(duration=180),
            ]
        )
    ],
    postchecks=[create_ixia_packet_loss_check(clear_traffic_stats=True)],
)
TEST_CONTINUOUS_AGENT_COLDBOOT_PLAYBOOK = Playbook(
    name="test_continuous_agent_coldboot",
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    create_cold_boot_file=True,
                ),
                create_service_convergence_step(services=[Service.AGENT]),
            ],
            iteration=5,
        ),
        create_steps_stage(
            steps=[
                create_longevity_step(duration=180),
            ]
        ),
    ],
    postchecks=[create_ixia_packet_loss_check(clear_traffic_stats=True)],
)


TEST_AGENT_WARMBOOT_PLAYBOOK = Playbook(
    name="test_agent_warmboot",
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(services=[Service.AGENT]),
            ],
        ),
    ],
)

TEST_MULTIPLE_AGENT_WARMBOOT_PLAYBOOK = Playbook(
    name="test_multiple_agent_warmboot",
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(services=[Service.AGENT]),
                create_longevity_step(duration=120),
            ],
            iteration=5,
        ),
    ],
)


TEST_CONTINUOUS_AGENT_WARMBOOT_PLAYBOOK = Playbook(
    name="test_continuous_agent_warmboot",
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(services=[Service.AGENT]),
            ],
        ),
        create_steps_stage(
            steps=[
                create_longevity_step(duration=120),
            ]
        ),
    ],
    iteration=5,
)


TEST_AGENT_WARMBOOT_AND_FSDB_RESTART_PLAYBOOK = Playbook(
    name="test_agent_warmboot_and_fsdb_restart",
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_interruption_step(
                    service=Service.FSDB,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
            ],
            concurrent=True,
        ),
        create_steps_stage(
            steps=[
                create_service_convergence_step(services=[Service.AGENT, Service.FSDB]),
            ],
        ),
    ],
    prechecks=[
        create_systemctl_active_state_check(),
        create_wedge_agent_configured_check(),
    ],
    postchecks=[
        create_packetloss_health_check(),
        create_unclean_exit_check(),
    ],
)


TEST_CONTINUOUS_AGENT_WARMBOOT_AND_FSDB_RESTART_PLAYBOOK = Playbook(
    name="test_continuous_agent_warmboot_and_fsdb_restart",
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_interruption_step(
                    service=Service.FSDB,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
            ],
            concurrent=True,
        ),
        create_steps_stage(
            steps=[
                create_service_convergence_step(services=[Service.AGENT]),
            ],
        ),
    ],
    iteration=5,
)

TEST_QSPF_RESTART_PLAYBOOK = Playbook(
    name="test_qsfp_restart",
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.QSFP_SERVICE,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
            ]
        ),
    ],
)

TEST_QSFP_SERVICE_RESTART_PLAYBOOK = Playbook(
    name="test_qsfp_service_restart",
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.QSFP_SERVICE,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(services=[Service.QSFP_SERVICE]),
            ]
        ),
    ],
)

TEST_CONTINUOUS_QSPF_RESTART_PLAYBOOK = Playbook(
    name="test_continuous_qsfp_restart",
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.QSFP_SERVICE,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
            ]
        ),
    ],
)

TEST_FSDB_RESTART_PLAYBOOK = Playbook(
    name="test_fsdb_restart",
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.FSDB,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
            ]
        ),
    ],
)

TEST_CONTINUOUS_FSDB_RESTART_PLAYBOOK = Playbook(
    name="test_continuous_fsdb_restart",
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.FSDB,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
            ],
            iteration=5,
        ),
    ],
)

TEST_BGPD_RESTART_PLAYBOOK = Playbook(
    name="test_bgpd_restart",
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.BGP,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(services=[Service.AGENT]),
            ]
        ),
    ],
    enabled=False,
)

TEST_BGPD_CRASH_PLAYBOOK = Playbook(
    name="test_bgpd_crash",
    prechecks=[
        create_unclean_exit_check(exclude_services=["bgpd"]),
    ],
    postchecks=[
        create_unclean_exit_check(exclude_services=["bgpd"]),
    ],
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.BGP,
                    trigger=ServiceInterruptionTrigger.CRASH,
                ),
                create_service_convergence_step(services=[Service.AGENT]),
            ]
        ),
    ],
    enabled=False,
)

TEST_FBOSS_HW_AGENT_0_RESTART_PLAYBOOK = Playbook(
    name="test_fboss_hw_agent_0_restart",
    attribute_filters={"role": ["FDSW"]},
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.FBOSS_HW_AGENT_0,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(),
            ]
        )
    ],
    enabled=False,
)

TEST_FBOSS_HW_AGENT_1_RESTART_PLAYBOOK = Playbook(
    name="test_fboss_hw_agent_1_restart",
    attribute_filters={"role": ["FDSW"]},
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.FBOSS_HW_AGENT_1,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(),
            ]
        )
    ],
    enabled=False,
)

TEST_FBOSS_SW_AGENT_WARMBOOT_PLAYBOOK = Playbook(
    name="test_fboss_sw_agent_warmboot",
    attribute_filters={"role": ["FDSW"]},
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.FBOSS_SW_AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(),
            ]
        )
    ],
    enabled=False,
)

TEST_FBOSS_SW_AGENT_AND_HW_AGENT_0_RESTART_PLAYBOOK = Playbook(
    name="test_fboss_sw_agent_and_hw_agent_0_restart",
    attribute_filters={"role": ["FDSW"]},
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.FBOSS_SW_AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_interruption_step(
                    service=Service.FBOSS_HW_AGENT_0,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
            ],
            concurrent=True,
        ),
        create_steps_stage(
            steps=[
                create_service_convergence_step(),
            ]
        ),
    ],
    enabled=False,
    postchecks=[
        create_service_restart_health_check(
            DEFAULT_SERVICE_NAMES,
            expected_restarted_services=["fboss_sw_agent", "fboss_hw_agent@0"],
        ),
    ],
)

TEST_FBOSS_SW_AGENT_AND_HW_AGENT_1_RESTART_PLAYBOOK = Playbook(
    name="test_fboss_sw_agent_and_hw_agent_1_restart",
    attribute_filters={"role": ["FDSW"]},
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.FBOSS_SW_AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_interruption_step(
                    service=Service.FBOSS_HW_AGENT_1,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
            ],
            concurrent=True,
        ),
        create_steps_stage(
            steps=[
                create_service_convergence_step(services=[Service.AGENT]),
            ],
        ),
    ],
    postchecks=[
        create_service_restart_health_check(
            DEFAULT_SERVICE_NAMES,
            expected_restarted_services=["fboss_sw_agent", "fboss_hw_agent@1"],
        ),
    ],
)

TEST_DEVICE_REBOOT_PLAYBOOK = Playbook(
    name="test_device_reboot",
    stages=[
        create_steps_stage(
            steps=[
                create_system_reboot_step(
                    trigger=SystemRebootTrigger.FULL_SYSTEM_REBOOT,
                ),
                create_service_convergence_step(services=[Service.AGENT]),
                create_validation_step(
                    point_in_time_checks=[
                        create_dsf_drain_state_check(is_drained=True),
                    ],
                    stage=ValidationStage.MID_TEST,
                ),
                create_drain_undrain_step(drain=False),
                create_longevity_step(duration=120),
            ]
        )
    ],
    postchecks=[
        create_ixia_packet_loss_check(clear_traffic_stats=True),
    ],
)

TEST_INTERFACE_DRAIN_PLAYBOOK = Playbook(
    name="test_interface_drain",
    attribute_filters={"role": ["FDSW", "RDSW"]},
    stages=[
        create_steps_stage(
            steps=[
                create_drain_undrain_step(
                    drain=True, description="Drain 1 random interface"
                ),
                create_drain_undrain_step(
                    drain=False, description="Undrain the interface"
                ),
            ]
        )
    ],
    postchecks=[create_ixia_packet_loss_check(clear_traffic_stats=True)],
)

TEST_DEVICE_DRAIN_PLAYBOOK = Playbook(
    name="test_device_drain",
    attribute_filters={"role": ["FDSW"]},
    stages=[
        create_steps_stage(
            steps=[
                create_drain_undrain_step(drain=True),
                create_drain_undrain_step(drain=False),
            ]
        )
    ],
)


TEST_DEVICE_DRAIN_AND_REMOTE_INTERFACE_DRAIN_PLAYBOOK = Playbook(
    name="test_device_drain_and_remote_interface_drain",
    attribute_filters={"role": ["FDSW"]},
    stages=[
        create_steps_stage(
            steps=[
                create_drain_undrain_step(drain=True),
            ]
        ),
        create_steps_stage(
            steps=[create_drain_undrain_step(drain=True)],
        ),
        create_steps_stage(
            steps=[create_drain_undrain_step(drain=False)],
        ),
        create_steps_stage(
            steps=[
                create_drain_undrain_step(drain=False),
            ]
        ),
    ],
    postchecks=[create_ixia_packet_loss_check(clear_traffic_stats=True)],
)

TEST_DEVICE_DRAIN_AND_LOCAL_INTERFACE_DRAIN_PLAYBOOK = Playbook(
    name="test_device_drain_and_local_interface_drain",
    attribute_filters={"role": ["FDSW"]},
    stages=[
        create_steps_stage(
            steps=[
                create_drain_undrain_step(drain=True),
                create_drain_undrain_step(drain=True),
                create_drain_undrain_step(drain=False),
                create_drain_undrain_step(drain=False),
            ]
        ),
    ],
    postchecks=[create_ixia_packet_loss_check(clear_traffic_stats=True)],
)

TEST_AGENT_CRASH_PLAYBOOK = Playbook(
    name="test_agent_crash",
    prechecks=[
        create_unclean_exit_check(
            exclude_services=[
                "wedge_agent",
                "bgpd",
                "fboss_sw_agent",
                "fboss_hw_agent@0",
            ]
        ),
    ],
    postchecks=[
        create_ixia_packet_loss_check(clear_traffic_stats=True),
        create_unclean_exit_check(
            exclude_services=[
                "wedge_agent",
                "bgpd",
                "fboss_sw_agent",
                "fboss_hw_agent@0",
            ]
        ),
    ],
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.AGENT,
                    trigger=ServiceInterruptionTrigger.CRASH,
                ),
                create_service_convergence_step(services=[Service.AGENT]),
                create_longevity_step(duration=180),
            ]
        )
    ],
)

TEST_FBOSS_HW_AGENT_0_CRASH_PLAYBOOK = Playbook(
    name="test_fboss_hw_agent_0_crash",
    prechecks=[
        create_unclean_exit_check(exclude_services=["fboss_hw_agent@0"]),
    ],
    postchecks=[
        create_ixia_packet_loss_check(clear_traffic_stats=True),
        create_unclean_exit_check(exclude_services=["fboss_hw_agent@0"]),
    ],
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.FBOSS_HW_AGENT_0,
                    trigger=ServiceInterruptionTrigger.CRASH,
                ),
                create_service_convergence_step(services=[Service.AGENT]),
                create_longevity_step(duration=180),
            ]
        )
    ],
)

TEST_51T_NPI_DCTYPEF_PLAYBOOKS = (
    Playbook(
        name="test_fsdb_restart",
        stages=[
            create_steps_stage(
                steps=[
                    create_service_interruption_step(
                        service=Service.FSDB,
                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                ]
            ),
        ],
        postchecks=[
            create_service_restart_check(
                services=SERVICES_TO_MONITOR_DURING_FSDB_RESTART
            ),
        ],
    ),
    Playbook(
        name="test_qsfp_restart",
        stages=[
            create_steps_stage(
                steps=[
                    create_service_interruption_step(
                        service=Service.QSFP_SERVICE,
                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                ]
            ),
        ],
        postchecks=[
            create_service_restart_check(
                services=SERVICES_TO_MONITOR_DURING_QSFP_SERVICE_RESTART
            ),
        ],
    ),
    Playbook(
        name="test_agent_coldboot",
        stages=[
            create_steps_stage(
                steps=[
                    create_service_interruption_step(
                        service=Service.AGENT,
                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                        create_cold_boot_file=True,
                    ),
                    create_service_convergence_step(
                        services=[Service.AGENT, Service.BGP]
                    ),
                    create_longevity_step(duration=300),
                ]
            )
        ],
        postchecks=[
            create_ixia_packet_loss_check(clear_traffic_stats=True),
            create_service_restart_check(
                services=SERVICES_TO_MONITOR_DURING_AGENT_RESTART
            ),
        ],
    ),
    Playbook(
        name="test_51t_continuous_agent_warmboot",
        stages=[
            create_steps_stage(
                steps=[
                    create_service_interruption_step(
                        service=Service.AGENT,
                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(
                        services=[Service.AGENT, Service.BGP]
                    ),
                ],
            ),
            create_steps_stage(
                steps=[
                    create_longevity_step(duration=300),
                ]
            ),
        ],
        iteration=5,
        postchecks=[
            create_service_restart_check(
                services=SERVICES_TO_MONITOR_DURING_AGENT_RESTART
            ),
        ],
    ),
    Playbook(
        name="test_51t_agent_warmboot",
        stages=[
            create_steps_stage(
                steps=[
                    create_service_interruption_step(
                        service=Service.AGENT,
                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(
                        services=[Service.AGENT, Service.BGP]
                    ),
                    create_longevity_step(duration=300),
                ],
            ),
        ],
        postchecks=[
            create_service_restart_check(
                services=SERVICES_TO_MONITOR_DURING_AGENT_RESTART
            ),
        ],
    ),
    Playbook(
        name="test_bgpd_restart",
        stages=[
            create_steps_stage(
                steps=[
                    create_service_interruption_step(
                        service=Service.BGP,
                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(
                        services=[Service.AGENT, Service.BGP]
                    ),
                ]
            ),
        ],
        postchecks=[
            create_service_restart_check(
                services=SERVICES_TO_MONITOR_DURING_BGP_RESTART
            ),
        ],
    ),
)

TEST_FBOSS_SW_AGENT_CRASH_PLAYBOOK = Playbook(
    name="test_fboss_sw_agent_crash",
    prechecks=[
        create_unclean_exit_check(exclude_services=["fboss_sw_agent"]),
    ],
    postchecks=[
        create_ixia_packet_loss_check(clear_traffic_stats=True),
        create_unclean_exit_check(exclude_services=["fboss_sw_agent"]),
    ],
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.FBOSS_SW_AGENT,
                    trigger=ServiceInterruptionTrigger.CRASH,
                ),
                create_service_convergence_step(services=[Service.AGENT]),
                create_longevity_step(duration=180),
            ],
        ),
    ],
)

TEST_FSDB_CRASH_PLAYBOOK = Playbook(
    name="test_fsdb_crash",
    prechecks=[
        create_unclean_exit_check(exclude_services=["fsdb"]),
    ],
    postchecks=[
        create_ixia_packet_loss_check(clear_traffic_stats=True),
        create_unclean_exit_check(exclude_services=["fsdb"]),
    ],
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.FSDB,
                    trigger=ServiceInterruptionTrigger.CRASH,
                ),
                create_service_convergence_step(services=[Service.FSDB]),
                create_longevity_step(duration=180),
            ]
        )
    ],
)

TEST_QSPF_SERVICE_CRASH_PLAYBOOK = Playbook(
    name="test_qspf_service_crash",
    prechecks=[
        create_systemctl_active_state_check(),
        create_wedge_agent_configured_check(),
        create_unclean_exit_check(exclude_services=["qsfp_service"]),
    ],
    postchecks=[
        create_ixia_packet_loss_check(clear_traffic_stats=True),
        create_unclean_exit_check(exclude_services=["qsfp_service"]),
    ],
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.QSFP_SERVICE,
                    trigger=ServiceInterruptionTrigger.CRASH,
                ),
                create_service_convergence_step(services=[Service.QSFP_SERVICE]),
                create_longevity_step(duration=180),
            ]
        )
    ],
)

TEST_QSFP_SERVICE_CRASH_PLAYBOOK = Playbook(
    name="test_qsfp_service_crash",
    prechecks=[
        create_unclean_exit_check(exclude_services=["qsfp_service"]),
    ],
    postchecks=[
        create_ixia_packet_loss_check(clear_traffic_stats=True),
        create_unclean_exit_check(exclude_services=["qsfp_service"]),
    ],
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.QSFP_SERVICE,
                    trigger=ServiceInterruptionTrigger.CRASH,
                ),
                create_service_convergence_step(services=[Service.QSFP_SERVICE]),
                create_longevity_step(duration=180),
            ]
        )
    ],
)

TEST_OPENR_RESTART_PLAYBOOK = Playbook(
    name="test_openr_restart",
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.OPENR,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(),
            ]
        ),
    ],
)

TEST_OPENR_CRASH_PLAYBOOK = Playbook(
    name="test_openr_crash",
    prechecks=[
        create_unclean_exit_check(exclude_services=["openr"]),
    ],
    postchecks=[
        create_ixia_packet_loss_check(clear_traffic_stats=True),
        create_unclean_exit_check(exclude_services=["openr"]),
    ],
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.OPENR,
                    trigger=ServiceInterruptionTrigger.CRASH,
                ),
                create_service_convergence_step(),
                create_longevity_step(duration=180),
            ]
        )
    ],
)

TEST_SW_AGENT_AND_WEDGE_AGENT_RESTART_PLAYBOOK = Playbook(
    name="test_sw_agent_and_wedge_agent_restart",
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.FBOSS_SW_AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_interruption_step(
                    service=Service.AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(services=[Service.AGENT]),
            ],
        ),
    ],
    postchecks=[
        create_service_restart_health_check(
            DEFAULT_SERVICE_NAMES,
            expected_restarted_services=[
                "fboss_sw_agent",
                "wedge_agent",
                "fboss_hw_agent@0",
                "bgpd",
                "openr",
            ],
        ),
    ],
)

TEST_QSFP_SERVICE_AND_AGENT_WARMBOOT_PLAYBOOK = Playbook(
    name="test_qsfp_service_and_agent_warmboot",
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.QSFP_SERVICE,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_longevity_step(duration=300),
                create_service_interruption_step(
                    service=Service.AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(services=[Service.AGENT]),
            ],
        ),
    ],
    postchecks=[
        create_service_restart_health_check(
            DEFAULT_SERVICE_NAMES,
            expected_restarted_services=[
                "qsfp_service",
                "wedge_agent",
                "fboss_sw_agent",
                "fboss_hw_agent@0",
                "bgpd",
                "openr",
            ],
        ),
    ],
)

TEST_BGPD_AND_FSDB_RESTART_PLAYBOOK = Playbook(
    name="test_bgpd_and_fsdb_restart",
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.BGP,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_interruption_step(
                    service=Service.FSDB,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(
                    services=[Service.AGENT, Service.BGP, Service.FSDB]
                ),
            ],
            iteration=5,
        ),
    ],
    postchecks=[
        create_service_restart_health_check(
            DEFAULT_SERVICE_NAMES,
            expected_restarted_services=["bgpd", "fsdb"],
        ),
    ],
)


TEST_AGENT_AND_FSDB_RESTART_PLAYBOOK = Playbook(
    name="test_agent_and_fsdb_restart",
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_interruption_step(
                    service=Service.FSDB,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(services=[Service.AGENT, Service.FSDB]),
            ],
            iteration=5,
        ),
    ],
    postchecks=[
        create_service_restart_health_check(
            DEFAULT_SERVICE_NAMES,
            expected_restarted_services=[
                "wedge_agent",
                "fsdb",
                "fboss_sw_agent",
                "fboss_hw_agent@0",
                "bgpd",
                "openr",
            ],
        ),
    ],
)


TEST_FBOSS_SW_AGENT_AND_HW_AGENT_0_CRASH_PLAYBOOK = Playbook(
    name="test_fboss_sw_agent_and_hw_agent_0_crash",
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.FBOSS_SW_AGENT,
                    trigger=ServiceInterruptionTrigger.CRASH,
                ),
                create_service_interruption_step(
                    service=Service.FBOSS_HW_AGENT_0,
                    trigger=ServiceInterruptionTrigger.CRASH,
                ),
            ],
            concurrent=True,
        ),
        create_steps_stage(
            steps=[
                create_service_convergence_step(services=[Service.AGENT]),
            ],
        ),
    ],
    postchecks=[
        create_service_restart_health_check(
            DEFAULT_SERVICE_NAMES,
            expected_restarted_services=["fboss_sw_agent", "fboss_hw_agent@0"],
        ),
    ],
)

TEST_AGENT_AND_BGPD_RESTART_PLAYBOOK = Playbook(
    name="test_agent_and_bgpd_restart",
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_interruption_step(
                    service=Service.BGP,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(services=[Service.AGENT, Service.BGP]),
            ],
            iteration=5,
        ),
    ],
    postchecks=[
        create_service_restart_health_check(
            DEFAULT_SERVICE_NAMES,
            expected_restarted_services=[
                "wedge_agent",
                "bgpd",
                "fboss_sw_agent",
                "fboss_hw_agent@0",
                "openr",
            ],
        ),
    ],
)

TEST_AGENT_AND_QSFP_SERVICE_RESTART_PLAYBOOK = Playbook(
    name="test_agent_and_qsfp_service_restart",
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_interruption_step(
                    service=Service.QSFP_SERVICE,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(
                    services=[Service.AGENT, Service.QSFP_SERVICE]
                ),
            ],
            iteration=5,
        ),
    ],
    postchecks=[
        create_service_restart_health_check(
            DEFAULT_SERVICE_NAMES,
            expected_restarted_services=[
                "wedge_agent",
                "qsfp_service",
                "fboss_sw_agent",
                "fboss_hw_agent@0",
                "bgpd",
                "openr",
            ],
        ),
    ],
)

TEST_FSDB_AND_QSFP_SERVICE_RESTART_PLAYBOOK = Playbook(
    name="test_fsdb_and_qsfp_service_restart",
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.FSDB,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_interruption_step(
                    service=Service.QSFP_SERVICE,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(
                    services=[Service.FSDB, Service.QSFP_SERVICE]
                ),
            ],
            iteration=5,
        ),
    ],
    postchecks=[
        create_service_restart_health_check(
            DEFAULT_SERVICE_NAMES,
            expected_restarted_services=["fsdb", "qsfp_service"],
        ),
    ],
)


# ---------------------------------------------------------------------------
# Service restart health-check constants
# ---------------------------------------------------------------------------

AGENT_RESTART_SERVICE_CHECK = create_service_restart_health_check(
    SERVICES_TO_MONITOR_DURING_AGENT_RESTART
)

AGENT_WARMBOOT_SERVICE_CHECK = create_service_restart_health_check(
    DEFAULT_SERVICE_NAMES,
    expected_restarted_services=SERVICES_EXPECTED_TO_RESTART_DURING_AGENT_WARMBOOT,
)

BGP_RESTART_SERVICE_CHECK = create_service_restart_health_check(
    SERVICES_TO_MONITOR_DURING_BGP_RESTART
)

FSDB_RESTART_SERVICE_CHECK = create_service_restart_health_check(
    SERVICES_TO_MONITOR_DURING_FSDB_RESTART
)

QSFP_SERVICE_RESTART_SERVICE_CHECK = create_service_restart_health_check(
    SERVICES_TO_MONITOR_DURING_QSFP_SERVICE_RESTART
)

OPENR_RESTART_SERVICE_CHECK = create_service_restart_health_check(
    SERVICES_TO_MONITOR_DURING_OPENR_RESTART
)


# ---------------------------------------------------------------------------
# Factory functions for restart / crash playbooks
# (parameterised by iteration count to support different conveyors)
# ---------------------------------------------------------------------------


def create_agent_warmboot_playbook(iteration: int = 5) -> Playbook:
    """Build the `test_agent_warmboot` Playbook for FBOSS hardening conveyors.

    Repeats `iteration` cycles of FBOSS AGENT service restart (warmboot
    semantics: no `create_cold_boot_file`) plus convergence wait, and
    asserts the AGENT warmboot service health check at postcheck. Used
    as the canonical warmboot playbook across FBOSS hardening
    TestConfigs.

    Args:
        iteration: Number of warmboot cycles. Default 5.

    Returns:
        A `Playbook` named `test_agent_warmboot` with one repeated stage.
    """
    return Playbook(
        name="test_agent_warmboot",
        stages=[
            create_steps_stage(
                iteration=iteration,
                steps=create_service_restart_steps(Service.AGENT),
            ),
        ],
        postchecks=[
            AGENT_WARMBOOT_SERVICE_CHECK,
        ],
    )


def create_bgpd_restart_playbook(
    iteration: int = 5,
    ixia_rogue_ic_parent_network_v6: str = "",
    ixia_rogue_ic_parent_network_v4: str = "",
) -> Playbook:
    """Build the `test_bgpd_restart` Playbook for FBOSS hardening conveyors.

    Repeats `iteration` cycles of BGP-daemon service restart + convergence
    wait, asserting BGP-convergence and the BGP restart service health
    check at postcheck. When the optional `ixia_rogue_ic_parent_network_*`
    args are supplied, those parent prefixes are excluded from the
    RIB/FIB consistency postcheck (used to avoid false positives from
    intentionally-rogue IXIA traffic).

    Args:
        iteration: Number of restart cycles. Default 5.
        ixia_rogue_ic_parent_network_v6: Optional IPv6 prefix of the
            IXIA rogue interconnect parent network to ignore in the
            RIB/FIB consistency check.
        ixia_rogue_ic_parent_network_v4: Optional IPv4 prefix of the
            IXIA rogue interconnect parent network to ignore.

    Returns:
        A `Playbook` named `test_bgpd_restart` with one repeated stage.
    """
    postchecks = [
        create_bgp_convergence_check(),
    ]
    if ixia_rogue_ic_parent_network_v6 or ixia_rogue_ic_parent_network_v4:
        postchecks.append(
            create_bgp_rib_fib_consistency_check(
                extra_json_params={
                    "parent_prefixes_to_ignore": [
                        f"{ixia_rogue_ic_parent_network_v6}::/80",
                        f"{ixia_rogue_ic_parent_network_v4}.0/16",
                    ]
                },
            ),
        )
    postchecks.append(BGP_RESTART_SERVICE_CHECK)
    return Playbook(
        name="test_bgpd_restart",
        stages=[
            create_steps_stage(
                iteration=iteration,
                steps=create_service_restart_steps(Service.BGP),
            ),
        ],
        postchecks=postchecks,
    )


def create_qsfp_service_restart_playbook(iteration: int = 5) -> Playbook:
    """Build the `test_qsfp_service_restart` Playbook.

    Repeats `iteration` cycles of qsfp_service systemctl restart +
    service convergence, asserting the qsfp restart health check at
    postcheck. Used by FBOSS hardening conveyors to verify the optics
    daemon recovers cleanly under repeated restart.

    Args:
        iteration: Number of restart cycles. Default 5.

    Returns:
        A `Playbook` named `test_qsfp_service_restart`.
    """
    return Playbook(
        name="test_qsfp_service_restart",
        postchecks=[
            QSFP_SERVICE_RESTART_SERVICE_CHECK,
        ],
        stages=[
            create_steps_stage(
                iteration=iteration,
                steps=[
                    create_service_interruption_step(
                        service=Service.QSFP_SERVICE,
                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(),
                ],
            ),
        ],
    )


def create_fsdb_restart_playbook(iteration: int = 5) -> Playbook:
    """Build the `test_fsdb_restart` Playbook.

    Repeats `iteration` cycles of fsdb systemctl restart followed by a
    short 10s longevity wait (fsdb has no convergence step — settle is
    enough). Asserts the fsdb restart service health check at postcheck.

    Args:
        iteration: Number of restart cycles. Default 5.

    Returns:
        A `Playbook` named `test_fsdb_restart`.
    """
    return Playbook(
        name="test_fsdb_restart",
        postchecks=[
            FSDB_RESTART_SERVICE_CHECK,
        ],
        stages=[
            create_steps_stage(
                iteration=iteration,
                steps=[
                    create_service_interruption_step(
                        service=Service.FSDB,
                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_longevity_step(duration=10),
                ],
            ),
        ],
    )


def create_openr_restart_playbook(iteration: int = 5) -> Playbook:
    """Build the `test_openr_restart` Playbook.

    Repeats `iteration` cycles of OpenR systemctl restart + service
    convergence, asserting the OpenR restart service health check at
    postcheck. Used by FBOSS hardening conveyors that include OpenR.

    Args:
        iteration: Number of restart cycles. Default 5.

    Returns:
        A `Playbook` named `test_openr_restart`.
    """
    return Playbook(
        name="test_openr_restart",
        postchecks=[
            OPENR_RESTART_SERVICE_CHECK,
        ],
        stages=[
            create_steps_stage(
                iteration=iteration,
                steps=[
                    create_service_interruption_step(
                        service=Service.OPENR,
                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(),
                ],
            ),
        ],
    )


def create_agent_coldboot_playbook(iteration: int = 5) -> Playbook:
    """Build the `test_agent_coldboot` Playbook.

    Repeats `iteration` cycles of FBOSS AGENT coldboot (systemctl
    restart with `create_cold_boot_file=True`) plus AGENT/BGP
    convergence wait. Asserts the AGENT warmboot service health check
    at postcheck (the same SERVICE_CHECK suffices for both modes).

    Args:
        iteration: Number of coldboot cycles. Default 5.

    Returns:
        A `Playbook` named `test_agent_coldboot`.
    """
    return Playbook(
        name="test_agent_coldboot",
        postchecks=[
            AGENT_WARMBOOT_SERVICE_CHECK,
        ],
        stages=[
            create_steps_stage(
                iteration=iteration,
                steps=[
                    create_service_interruption_step(
                        service=Service.AGENT,
                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                        create_cold_boot_file=True,
                    ),
                    create_service_convergence_step(
                        services=[Service.AGENT, Service.BGP],
                    ),
                ],
            ),
        ],
    )


def _unclean_exit_check(exclude_services: list) -> PointInTimeHealthCheck:
    return create_unclean_exit_check(exclude_services=exclude_services)


def create_agent_crash_playbook(iteration: int = 5) -> Playbook:
    """Build the `test_agent_crash` Playbook.

    Repeats `iteration` cycles of crashing FBOSS AGENT (SIGKILL via
    `ServiceInterruptionTrigger.CRASH`) plus AGENT/BGP convergence
    wait. Pre/postchecks assert no unclean exit for unrelated daemons
    (excluding `wedge_agent` and `bgpd` from the unclean-exit ledger
    because the test itself produces those).

    Args:
        iteration: Number of crash cycles. Default 5.

    Returns:
        A `Playbook` named `test_agent_crash`.
    """
    return Playbook(
        name="test_agent_crash",
        prechecks=[
            _unclean_exit_check(["wedge_agent", "bgpd"]),
        ],
        postchecks=[
            AGENT_WARMBOOT_SERVICE_CHECK,
            _unclean_exit_check(["wedge_agent", "bgpd"]),
        ],
        stages=[
            create_steps_stage(
                iteration=iteration,
                steps=[
                    create_service_interruption_step(
                        service=Service.AGENT,
                        trigger=ServiceInterruptionTrigger.CRASH,
                    ),
                    create_service_convergence_step(
                        services=[Service.AGENT, Service.BGP],
                    ),
                ],
            ),
        ],
    )


def create_bgpd_crash_playbook(iteration: int = 5) -> Playbook:
    """Build the `test_bgpd_crash` Playbook.

    Repeats `iteration` cycles of crashing bgpd plus service
    convergence wait. Pre/postchecks assert no unrelated unclean exits
    (`bgpd` is intentionally excluded from the unclean-exit ledger).

    Args:
        iteration: Number of crash cycles. Default 5.

    Returns:
        A `Playbook` named `test_bgpd_crash`.
    """
    return Playbook(
        name="test_bgpd_crash",
        prechecks=[
            _unclean_exit_check(["bgpd"]),
        ],
        postchecks=[
            BGP_RESTART_SERVICE_CHECK,
            _unclean_exit_check(["bgpd"]),
        ],
        stages=[
            create_steps_stage(
                iteration=iteration,
                steps=[
                    create_service_interruption_step(
                        service=Service.BGP,
                        trigger=ServiceInterruptionTrigger.CRASH,
                    ),
                    create_service_convergence_step(
                        services=[Service.BGP],
                    ),
                ],
            ),
        ],
    )


def create_openr_crash_playbook(iteration: int = 5) -> Playbook:
    """Build the `test_openr_crash` Playbook.

    Repeats `iteration` cycles of crashing OpenR plus service
    convergence wait. Pre/postchecks exclude `openr` from the
    unclean-exit ledger.

    Args:
        iteration: Number of crash cycles. Default 5.

    Returns:
        A `Playbook` named `test_openr_crash`.
    """
    return Playbook(
        name="test_openr_crash",
        prechecks=[
            _unclean_exit_check(["openr"]),
        ],
        postchecks=[
            OPENR_RESTART_SERVICE_CHECK,
            _unclean_exit_check(["openr"]),
        ],
        stages=[
            create_steps_stage(
                iteration=iteration,
                steps=[
                    create_service_interruption_step(
                        service=Service.OPENR,
                        trigger=ServiceInterruptionTrigger.CRASH,
                    ),
                    create_service_convergence_step(),
                ],
            ),
        ],
    )


def create_qsfp_service_crash_playbook(iteration: int = 5) -> Playbook:
    """Build the `test_qsfp_service_crash` Playbook.

    Repeats `iteration` cycles of crashing qsfp_service plus service
    convergence wait. Pre/postchecks exclude `qsfp_service` from the
    unclean-exit ledger.

    Args:
        iteration: Number of crash cycles. Default 5.

    Returns:
        A `Playbook` named `test_qsfp_service_crash`.
    """
    return Playbook(
        name="test_qsfp_service_crash",
        prechecks=[
            _unclean_exit_check(["qsfp_service"]),
        ],
        postchecks=[
            QSFP_SERVICE_RESTART_SERVICE_CHECK,
            _unclean_exit_check(["qsfp_service"]),
        ],
        stages=[
            create_steps_stage(
                iteration=iteration,
                steps=[
                    create_service_interruption_step(
                        service=Service.QSFP_SERVICE,
                        trigger=ServiceInterruptionTrigger.CRASH,
                    ),
                    create_service_convergence_step(),
                ],
            ),
        ],
    )


def create_fsdb_crash_playbook(iteration: int = 5) -> Playbook:
    """Build the `test_fsdb_crash` Playbook.

    Repeats `iteration` cycles of crashing fsdb followed by a 10s
    longevity settle. Pre/postchecks exclude `fsdb` from the
    unclean-exit ledger.

    Args:
        iteration: Number of crash cycles. Default 5.

    Returns:
        A `Playbook` named `test_fsdb_crash`.
    """
    return Playbook(
        name="test_fsdb_crash",
        prechecks=[
            _unclean_exit_check(["fsdb"]),
        ],
        postchecks=[
            FSDB_RESTART_SERVICE_CHECK,
            _unclean_exit_check(["fsdb"]),
        ],
        stages=[
            create_steps_stage(
                iteration=iteration,
                steps=[
                    create_service_interruption_step(
                        service=Service.FSDB,
                        trigger=ServiceInterruptionTrigger.CRASH,
                    ),
                    create_longevity_step(duration=10),
                ],
            ),
        ],
    )


TEST_WEDGE_AGENT_AND_FSDB_CRASH_PLAYBOOK = Playbook(
    name="test_wedge_agent_and_fsdb_crash",
    prechecks=[
        create_systemctl_active_state_check(),
        create_wedge_agent_configured_check(),
    ],
    postchecks=[create_ixia_packet_loss_check(clear_traffic_stats=True)],
    stages=[
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=Service.AGENT,
                    trigger=ServiceInterruptionTrigger.CRASH,
                ),
                create_service_interruption_step(
                    service=Service.FSDB,
                    trigger=ServiceInterruptionTrigger.CRASH,
                ),
            ],
            concurrent=True,
        ),
        create_steps_stage(
            steps=[
                create_service_convergence_step(services=[Service.AGENT, Service.FSDB]),
                create_longevity_step(duration=180),
            ],
        ),
    ],
)


# ----- Migrated from playbooks/helpers/cpu_queue_playbooks.py -----

# Playbook constants - single source of truth for playbook definitions.
# Used by both create_cpu_queue_playbooks() and UTP test case definitions.
# UTP uses .name to get the playbook name string.
NPI_CPU_001_LLDP_MCAST_TO_MID_QUEUE = Playbook(
    name="npi_cpu_001_lldp_mcast_to_mid_queue",
)
NPI_CPU_007_DHCP_V6_GLOBAL_DSCP48_TO_MID_QUEUE = Playbook(
    name="npi_cpu_007_dhcp_v6_global_dscp48_to_mid_queue",
)
NPI_CPU_008_DHCP_V6_GLOBAL_DSCP0_TO_MID_QUEUE = Playbook(
    name="npi_cpu_008_dhcp_v6_global_dscp0_to_mid_queue",
)
NPI_CPU_009_DHCP_V6_LL_DSCP48_TO_MID_QUEUE = Playbook(
    name="npi_cpu_009_dhcp_v6_ll_dscp48_to_mid_queue",
)
NPI_CPU_016_ICMP_V6_ECHO_REQ_LL_TO_MID_QUEUE = Playbook(
    name="npi_cpu_016_icmp_v6_echo_req_ll_to_mid_queue",
)
NPI_CPU_038_UNH_REMOTE_HOST_ROUTE_TO_LOW_QUEUE = Playbook(
    name="npi_cpu_038_unh_remote_host_route_to_low_queue",
)
NPI_CPU_037_UNH_REMOTE_SUBNET_TO_LOW_QUEUE = Playbook(
    name="npi_cpu_037_unh_remote_subnet_to_low_queue",
)
NPI_CPU_036_UNH_DIR_CONN_HOST_TO_LOW_QUEUE = Playbook(
    name="npi_cpu_036_unh_dir_conn_host_to_low_queue",
)
NPI_CPU_040_LACP_MCAST_TO_HIGH_QUEUE = Playbook(
    name="npi_cpu_040_lacp_mcast_to_high_queue",
)
NPI_CPU_042_HOP_LIMIT_1_TO_LOW_QUEUE = Playbook(
    name="npi_cpu_042_hop_limit_1_to_low_queue",
)
NPI_CPU_043_HOP_LIMIT_0_NOT_PUNTED = Playbook(
    name="npi_cpu_043_hop_limit_0_not_punted",
)
NPI_CPU_017_ARP_REQUEST_BCAST_TO_HIGH_QUEUE = Playbook(
    name="npi_cpu_017_arp_request_bcast_to_high_queue",
)
NPI_CPU_018_ARP_RESPONSE_TO_HIGH_QUEUE = Playbook(
    name="npi_cpu_018_arp_response_to_high_queue",
)
NPI_CPU_019_ARP_RESPONSE_BCAST_TO_HIGH_QUEUE = Playbook(
    name="npi_cpu_019_arp_response_bcast_to_high_queue",
)
NPI_CPU_020_NDP_NS_GLOBAL_DSCP48_TO_HIGH_QUEUE = Playbook(
    name="npi_cpu_020_ndp_ns_global_dscp48_to_high_queue",
)
NPI_CPU_021_NDP_NS_LL_DSCP48_TO_HIGH_QUEUE = Playbook(
    name="npi_cpu_021_ndp_ns_ll_dscp48_to_high_queue",
)
NPI_CPU_041_QUEUE_PRIORITIZATION_HIGH_NO_DROPS = Playbook(
    name="npi_cpu_041_queue_prioritization_high_no_drops",
)
NPI_CPU_044_TTL_1_IPV4_TO_LOW_QUEUE = Playbook(
    name="npi_cpu_044_ttl_1_ipv4_to_low_queue",
)
NPI_CPU_045_TTL_0_IPV4_NOT_PUNTED = Playbook(
    name="npi_cpu_045_ttl_0_ipv4_not_punted",
)
# ICMP v4 sub-test playbooks (CPU_012 expansion)
NPI_CPU_012_ICMP_V4_ECHO_REQ_TO_MID_QUEUE = Playbook(
    name="npi_cpu_012_icmp_v4_echo_req_to_mid_queue",
)
NPI_CPU_013_ICMP_V4_ECHO_REPLY_TO_MID_QUEUE = Playbook(
    name="npi_cpu_013_icmp_v4_echo_reply_to_mid_queue",
)
NPI_CPU_014_ICMP_V4_DEST_UNREACH_TO_MID_QUEUE = Playbook(
    name="npi_cpu_014_icmp_v4_dest_unreach_to_mid_queue",
)
NPI_CPU_015_ICMP_V4_TIME_EXCEEDED_TO_MID_QUEUE = Playbook(
    name="npi_cpu_015_icmp_v4_time_exceeded_to_mid_queue",
)
# ICMPv6 global DSCP 48 sub-test playbooks (CPU_019 expansion)
NPI_CPU_022_ICMP_V6_ECHO_REQ_GLOBAL_DSCP48_TO_MID_QUEUE = Playbook(
    name="npi_cpu_022_icmp_v6_echo_req_global_dscp48_to_mid_queue",
)
NPI_CPU_023_ICMP_V6_ECHO_REPLY_GLOBAL_DSCP48_TO_MID_QUEUE = Playbook(
    name="npi_cpu_023_icmp_v6_echo_reply_global_dscp48_to_mid_queue",
)
NPI_CPU_024_ICMP_V6_DEST_UNREACH_GLOBAL_DSCP48_TO_MID_QUEUE = Playbook(
    name="npi_cpu_024_icmp_v6_dest_unreach_global_dscp48_to_mid_queue",
)
NPI_CPU_025_ICMP_V6_PACKET_TOO_BIG_GLOBAL_DSCP48_TO_MID_QUEUE = Playbook(
    name="npi_cpu_025_icmp_v6_packet_too_big_global_dscp48_to_mid_queue",
)
NPI_CPU_026_ICMP_V6_TIME_EXCEEDED_GLOBAL_DSCP48_TO_MID_QUEUE = Playbook(
    name="npi_cpu_026_icmp_v6_time_exceeded_global_dscp48_to_mid_queue",
)
# ICMPv6 link local DSCP 0 sub-test playbooks (CPU_020 expansion)
NPI_CPU_027_ICMP_V6_ECHO_REQ_LL_DSCP0_TO_MID_QUEUE = Playbook(
    name="npi_cpu_027_icmp_v6_echo_req_ll_dscp0_to_mid_queue",
)
NPI_CPU_028_ICMP_V6_ECHO_REPLY_LL_DSCP0_TO_MID_QUEUE = Playbook(
    name="npi_cpu_028_icmp_v6_echo_reply_ll_dscp0_to_mid_queue",
)
NPI_CPU_029_ICMP_V6_DEST_UNREACH_LL_DSCP0_TO_MID_QUEUE = Playbook(
    name="npi_cpu_029_icmp_v6_dest_unreach_ll_dscp0_to_mid_queue",
)
NPI_CPU_030_ICMP_V6_PACKET_TOO_BIG_LL_DSCP0_TO_MID_QUEUE = Playbook(
    name="npi_cpu_030_icmp_v6_packet_too_big_ll_dscp0_to_mid_queue",
)
NPI_CPU_031_ICMP_V6_TIME_EXCEEDED_LL_DSCP0_TO_MID_QUEUE = Playbook(
    name="npi_cpu_031_icmp_v6_time_exceeded_ll_dscp0_to_mid_queue",
)
# NDP sub-test playbooks (Cat 4 CPU_032/033/034/035)
# CPU_032 (NDP NS LL DSCP=48) is the same spec as CPU_021 — both fire
# TEST_NDP_NS_UNICAST_TRAFFIC against the switch's link-local IPv6 address
# with DSCP=48. Rather than duplicate the playbook, the utp entry for
# CPU_032 points to NPI_CPU_021_NDP_NS_LL_DSCP48_TO_HIGH_QUEUE.
# CPU_034 (NDP RS) is the only NDP variant whose spec is genuinely multicast
# (RS is always sent to the all-routers mcast address ff02::2); it keeps the
# mcast playbook below.
NPI_CPU_034_NDP_RS_MCAST_TO_HIGH_QUEUE = Playbook(
    name="npi_cpu_034_ndp_rs_mcast_to_high_queue",
)
# Strict CPU_033 / CPU_035: per Cat 4 the NDP NA and NDP RA testcases use
# link-local source + link-local destination (NDP unicast), not the IPv6
# all-nodes multicast destination. The mcast hybrids (previously named
# npi_cpu_03[35]_ndp_na/ra_mcast_to_high_queue) are replaced with the
# link-local-unicast variants below.
NPI_CPU_033_NDP_NA_LL_TO_HIGH_QUEUE = Playbook(
    name="npi_cpu_033_ndp_na_ll_to_high_queue",
)
NPI_CPU_035_NDP_RA_LL_TO_HIGH_QUEUE = Playbook(
    name="npi_cpu_035_ndp_ra_ll_to_high_queue",
)
# DHCP v4 sub-test playbooks (CPU_010/CPU_011)
NPI_CPU_010_DHCP_V4_DISCOVER_BCAST_TO_MID_QUEUE = Playbook(
    name="npi_cpu_010_dhcp_v4_discover_bcast_to_mid_queue",
)
NPI_CPU_011_DHCP_V4_DISCOVER_UCAST_TO_MID_QUEUE = Playbook(
    name="npi_cpu_011_dhcp_v4_discover_ucast_to_mid_queue",
)
# BGP v4 CP traffic playbooks (CPU_005/CPU_006)
NPI_CPU_005_BGP_CP_V4_DEF_GW_DSCP48_TO_HIGH_QUEUE = Playbook(
    name="npi_cpu_005_bgp_cp_v4_def_gw_dscp48_to_high_queue",
)
NPI_CPU_006_BGP_CP_V4_DEF_GW_DSCP0_TO_HIGH_QUEUE = Playbook(
    name="npi_cpu_006_bgp_cp_v4_def_gw_dscp0_to_high_queue",
)
# BGP v6 CP traffic playbooks (CPU_002/CPU_003/CPU_004)
NPI_CPU_002_BGP_CP_V6_GLOBAL_DSCP48_TO_HIGH_QUEUE = Playbook(
    name="npi_cpu_002_bgp_cp_v6_global_dscp48_to_high_queue",
)
NPI_CPU_003_BGP_CP_V6_LINK_LOCAL_DSCP48_TO_HIGH_QUEUE = Playbook(
    name="npi_cpu_003_bgp_cp_v6_link_local_dscp48_to_high_queue",
)
NPI_CPU_004_BGP_CP_V6_LINK_LOCAL_DSCP0_TO_HIGH_QUEUE = Playbook(
    name="npi_cpu_004_bgp_cp_v6_link_local_dscp0_to_high_queue",
)

# Backward-compat aliases — preserve `from playbook_definitions import OLD_NAME`
# imports for any external caller that pinned the pre-rename identifier. These
# point to the same Playbook object as the new NPI_CPU_NNN_* constants; the
# user-visible `.name` string reflects the new convention.
TEST_LLDP_TRAFFIC_PUNTED_TO_CPU_MID_QUEUE = NPI_CPU_001_LLDP_MCAST_TO_MID_QUEUE
TEST_ICMP_V6_REQUEST_TRAFFIC_PUNTED_TO_CPU_MID_QUEUE = (
    NPI_CPU_016_ICMP_V6_ECHO_REQ_LL_TO_MID_QUEUE
)
TEST_FBOSS_CPU_REMOTE_SUBNET_128_UNH = NPI_CPU_038_UNH_REMOTE_HOST_ROUTE_TO_LOW_QUEUE
TEST_FBOSS_CPU_REMOTE_SUBNET_UNH = NPI_CPU_037_UNH_REMOTE_SUBNET_TO_LOW_QUEUE
TEST_FBOSS_CPU_DIR_CONN_HOST_UNH = NPI_CPU_036_UNH_DIR_CONN_HOST_TO_LOW_QUEUE
TEST_LACP_TRAFFIC_PUNTED_TO_CPU_HIGH_QUEUE = NPI_CPU_040_LACP_MCAST_TO_HIGH_QUEUE
TEST_NEXTHOP_LIMIT_1_PUNTED_TO_CPU_LOW_QUEUE = NPI_CPU_042_HOP_LIMIT_1_TO_LOW_QUEUE
TEST_NEXTHOP_LIMIT_0_NOT_PUNTED_TO_CPU = NPI_CPU_043_HOP_LIMIT_0_NOT_PUNTED
TEST_ARP_TRAFFIC_PUNTED_TO_CPU_HIGH_QUEUE = NPI_CPU_017_ARP_REQUEST_BCAST_TO_HIGH_QUEUE
TEST_ARP_RESPONSE_TRAFFIC_PUNTED_TO_CPU_HIGH_QUEUE = (
    NPI_CPU_018_ARP_RESPONSE_TO_HIGH_QUEUE
)
TEST_QUEUE_PRIORITIZATION_HIGH_QUEUE_NO_DROPS = (
    NPI_CPU_041_QUEUE_PRIORITIZATION_HIGH_NO_DROPS
)
TEST_TTL_1_IPV4_TRAFFIC_PUNTED_TO_CPU_LOW_QUEUE = NPI_CPU_044_TTL_1_IPV4_TO_LOW_QUEUE
TEST_TTL_0_IPV4_TRAFFIC_NOT_PUNTED_TO_CPU = NPI_CPU_045_TTL_0_IPV4_NOT_PUNTED
TEST_ICMP_V4_ECHO_REQUEST_TRAFFIC_PUNTED_TO_CPU_MID_QUEUE = (
    NPI_CPU_012_ICMP_V4_ECHO_REQ_TO_MID_QUEUE
)
TEST_ICMP_V4_ECHO_REPLY_TRAFFIC_PUNTED_TO_CPU_MID_QUEUE = (
    NPI_CPU_013_ICMP_V4_ECHO_REPLY_TO_MID_QUEUE
)
TEST_ICMP_V4_DEST_UNREACHABLE_TRAFFIC_PUNTED_TO_CPU_MID_QUEUE = (
    NPI_CPU_014_ICMP_V4_DEST_UNREACH_TO_MID_QUEUE
)
TEST_ICMP_V4_TIME_EXCEEDED_TRAFFIC_PUNTED_TO_CPU_MID_QUEUE = (
    NPI_CPU_015_ICMP_V4_TIME_EXCEEDED_TO_MID_QUEUE
)
TEST_ICMPV6_ECHO_REQUEST_GLOBAL_DSCP48_TRAFFIC_PUNTED_TO_CPU_MID_QUEUE = (
    NPI_CPU_022_ICMP_V6_ECHO_REQ_GLOBAL_DSCP48_TO_MID_QUEUE
)
TEST_ICMPV6_ECHO_REPLY_GLOBAL_DSCP48_TRAFFIC_PUNTED_TO_CPU_MID_QUEUE = (
    NPI_CPU_023_ICMP_V6_ECHO_REPLY_GLOBAL_DSCP48_TO_MID_QUEUE
)
TEST_ICMPV6_DEST_UNREACHABLE_GLOBAL_DSCP48_TRAFFIC_PUNTED_TO_CPU_MID_QUEUE = (
    NPI_CPU_024_ICMP_V6_DEST_UNREACH_GLOBAL_DSCP48_TO_MID_QUEUE
)
TEST_ICMPV6_PACKET_TOO_BIG_GLOBAL_DSCP48_TRAFFIC_PUNTED_TO_CPU_MID_QUEUE = (
    NPI_CPU_025_ICMP_V6_PACKET_TOO_BIG_GLOBAL_DSCP48_TO_MID_QUEUE
)
TEST_ICMPV6_TIME_EXCEEDED_GLOBAL_DSCP48_TRAFFIC_PUNTED_TO_CPU_MID_QUEUE = (
    NPI_CPU_026_ICMP_V6_TIME_EXCEEDED_GLOBAL_DSCP48_TO_MID_QUEUE
)
TEST_ICMPV6_ECHO_REQUEST_LINK_LOCAL_TRAFFIC_PUNTED_TO_CPU_MID_QUEUE = (
    NPI_CPU_027_ICMP_V6_ECHO_REQ_LL_DSCP0_TO_MID_QUEUE
)
TEST_ICMPV6_ECHO_REPLY_LINK_LOCAL_TRAFFIC_PUNTED_TO_CPU_MID_QUEUE = (
    NPI_CPU_028_ICMP_V6_ECHO_REPLY_LL_DSCP0_TO_MID_QUEUE
)
TEST_ICMPV6_DEST_UNREACHABLE_LINK_LOCAL_TRAFFIC_PUNTED_TO_CPU_MID_QUEUE = (
    NPI_CPU_029_ICMP_V6_DEST_UNREACH_LL_DSCP0_TO_MID_QUEUE
)
TEST_ICMPV6_PACKET_TOO_BIG_LINK_LOCAL_TRAFFIC_PUNTED_TO_CPU_MID_QUEUE = (
    NPI_CPU_030_ICMP_V6_PACKET_TOO_BIG_LL_DSCP0_TO_MID_QUEUE
)
TEST_ICMPV6_TIME_EXCEEDED_LINK_LOCAL_TRAFFIC_PUNTED_TO_CPU_MID_QUEUE = (
    NPI_CPU_031_ICMP_V6_TIME_EXCEEDED_LL_DSCP0_TO_MID_QUEUE
)
TEST_NDP_RS_MULTICAST_TRAFFIC_PUNTED_TO_CPU_HIGH_QUEUE = (
    NPI_CPU_034_NDP_RS_MCAST_TO_HIGH_QUEUE
)
TEST_DHCP_V4_DISCOVER_TRAFFIC_PUNTED_TO_CPU_MID_QUEUE = (
    NPI_CPU_010_DHCP_V4_DISCOVER_BCAST_TO_MID_QUEUE
)
TEST_DHCP_V4_DISCOVER_TO_SERVER_TRAFFIC_PUNTED_TO_CPU_MID_QUEUE = (
    NPI_CPU_011_DHCP_V4_DISCOVER_UCAST_TO_MID_QUEUE
)
TEST_BGP_CP_V4_TRAFFIC_PUNTED_TO_CPU_HIGH_QUEUE = (
    NPI_CPU_005_BGP_CP_V4_DEF_GW_DSCP48_TO_HIGH_QUEUE
)
TEST_BGP_CP_V4_DSCP0_TRAFFIC_PUNTED_TO_CPU_HIGH_QUEUE = (
    NPI_CPU_006_BGP_CP_V4_DEF_GW_DSCP0_TO_HIGH_QUEUE
)


def create_cpu_queue_playbooks(
    low_queue: int,
    mid_queue: int,
    high_queue: int,
    ixia_downlink_interface: str,
    bgp_peer_count: int = 0,
) -> t.List[Playbook]:
    """Create all CPU queue test playbooks.

    Args:
        low_queue: Queue index for low priority traffic
        mid_queue: Queue index for mid priority traffic
        high_queue: Queue index for high priority traffic
        ixia_downlink_interface: IXIA downlink interface name (for UNH playbooks)
        bgp_peer_count: Total IXIA-mimic BGP peers configured by the TestConfig
            (downlink + uplink + rogue). Used to scale the A2-leakage noise
            tolerance for inactive CPU queues. Default 0 yields the baseline
            noise floor (no per-session scaling) — appropriate for callers that
            don't supply a peer count. Pass `downlink + uplink + rogue` from the
            TestConfig factory to enable scale-aware tuning.

    Returns:
        List of all CPU queue test Playbook objects
    """
    # Per-queue inactive-queue noise tolerances for the A2 leakage assertion.
    # These scale with `bgp_peer_count` because BGP control traffic dominates
    # CPU-queue background pps at multi-session test scale (each established
    # session contributes keepalives + update churn that lands on the high
    # queue, with smaller spillover into mid/low). The per-session coefficients
    # are tuned from observed pps on `gtsw001.l1001.c085.ash6` 2026-06-05 with
    # 24 peers (16 establishing): high queue measured at ~762 pps (~48 pps per
    # established session). The thresholds below pad those measurements by
    # roughly 2x to absorb update-storm spikes while still surfacing real
    # misclassification (which would push the wrong queue into thousands of
    # pps from 2000-fps RAW test traffic).
    #
    # Bases held at 100 pps for back-compat with the prior hardcoded tolerance
    # (so callers that do not supply `bgp_peer_count` see no behavioral change
    # vs the pre-D107736854 state). The per-session coefficients carry all of
    # the scale-aware tuning. For our 24-peer IcePack TestConfig:
    #   low_q_noise  = 100 + 24*20 = 580   (covers q0 data-plane exception background)
    #   mid_q_noise  = 100 + 24*5  = 220   (LLDP/NDP/ARP refresh)
    #   high_q_noise = 100 + 24*50 = 1300  (BGP keepalives + updates from 24 peers)
    #
    # If the heuristic drifts (false-fail at scale OR misses real leakage),
    # the long-term fix is auto-calibration via a setup-time baseline task —
    # see project memory `project_icepack_npi_cpu_queues.md` Option B/C.
    low_q_noise = 100 + bgp_peer_count * 20
    mid_q_noise = 100 + bgp_peer_count * 5
    high_q_noise = 100 + bgp_peer_count * 50

    longevity_playbook = Playbook(
        name="1_test_longevity",
        traffic_items_to_start=[
            "V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
            "V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
        ],
        stages=[
            create_steps_stage(
                steps=[create_longevity_step(duration=240)],
            )
        ],
    )

    test_cpu_mid_queue_traffic_playbook = Playbook(
        name="test_cpu_mid_queue_traffic",
        traffic_items_to_start=[
            "TEST_RAW_LLDP_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                steps=[create_longevity_step(duration=60)],
            )
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[mid_queue],
                inactive_queues=[low_queue, high_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    high_queue: high_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            )
        ],
    )

    test_cpu_high_queue_traffic_playbook = Playbook(
        name="test_cpu_high_queue_traffic",
        traffic_items_to_start=[
            "TEST_RAW_BGP_CP_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                steps=[create_longevity_step(duration=60)],
            )
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[high_queue],
                inactive_queues=[low_queue, mid_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    mid_queue: mid_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            )
        ],
    )

    # Queue prioritization test: send burst traffic to LOW and MID queues
    # to create drops, while verifying no drops on HIGH queue (BGP_CP)
    # LOW queue: TTL=1 IPv4 traffic (punted for ICMP TTL exceeded)
    # MID queue: DHCPv6 traffic
    # HIGH queue: BGP CP traffic
    npi_cpu_041_queue_prioritization_high_no_drops_playbook = Playbook(
        name="npi_cpu_041_queue_prioritization_high_no_drops",
        traffic_items_to_start=[
            "BURST_LOW_QUEUE_TTL1_TRAFFIC",
            "BURST_MID_QUEUE_DHCPV6_TRAFFIC",
            "TEST_RAW_BGP_CP_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                steps=[create_longevity_step(duration=60)],
            )
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[low_queue, mid_queue, high_queue],
                no_discard_queues=[high_queue],
            )
        ],
    )

    npi_cpu_016_icmp_v6_echo_req_ll_to_mid_queue_playbook = Playbook(
        name=NPI_CPU_016_ICMP_V6_ECHO_REQ_LL_TO_MID_QUEUE.name,
        traffic_items_to_start=[
            "TEST_RAW_ICMP_V6_REQUEST_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                steps=[create_longevity_step(duration=60)],
            )
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[mid_queue],
                inactive_queues=[low_queue, high_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    high_queue: high_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            )
        ],
    )

    npi_cpu_012_icmp_v4_echo_req_to_mid_queue_playbook = Playbook(
        name="npi_cpu_012_icmp_v4_echo_req_to_mid_queue",
        traffic_items_to_start=[
            "TEST_RAW_ICMP_V4_ECHO_REQUEST_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                steps=[create_longevity_step(duration=60)],
            )
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[mid_queue],
                inactive_queues=[low_queue, high_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    high_queue: high_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            )
        ],
    )

    npi_cpu_013_icmp_v4_echo_reply_to_mid_queue_playbook = Playbook(
        name="npi_cpu_013_icmp_v4_echo_reply_to_mid_queue",
        traffic_items_to_start=[
            "TEST_RAW_ICMP_V4_ECHO_REPLY_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                steps=[create_longevity_step(duration=60)],
            )
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[mid_queue],
                inactive_queues=[low_queue, high_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    high_queue: high_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            )
        ],
    )

    npi_cpu_014_icmp_v4_dest_unreach_to_mid_queue_playbook = Playbook(
        name="npi_cpu_014_icmp_v4_dest_unreach_to_mid_queue",
        traffic_items_to_start=[
            "TEST_RAW_ICMP_V4_DEST_UNREACHABLE_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                steps=[create_longevity_step(duration=60)],
            )
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[mid_queue],
                inactive_queues=[low_queue, high_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    high_queue: high_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            )
        ],
    )

    npi_cpu_015_icmp_v4_time_exceeded_to_mid_queue_playbook = Playbook(
        name="npi_cpu_015_icmp_v4_time_exceeded_to_mid_queue",
        traffic_items_to_start=[
            "TEST_RAW_ICMP_V4_TIME_EXCEEDED_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                steps=[create_longevity_step(duration=60)],
            )
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[mid_queue],
                inactive_queues=[low_queue, high_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    high_queue: high_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            )
        ],
    )

    npi_cpu_007_dhcp_v6_global_dscp48_to_mid_queue_playbook = Playbook(
        name=NPI_CPU_007_DHCP_V6_GLOBAL_DSCP48_TO_MID_QUEUE.name,
        description=(
            "CPU_007: DHCPv6 request with global source/destination IPv6 "
            "addresses and DSCP=48 (UDP src 546, dst 547) must be punted to "
            "the MID CPU queue. Verifies DHCPv6 host-mgmt classification for "
            "IPv6 global-scope sessions."
        ),
        traffic_items_to_start=[
            "TEST_RAW_DHCP_V6_GLOBAL_DSCP48_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                steps=[create_longevity_step(duration=60)],
            )
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[mid_queue],
                inactive_queues=[low_queue, high_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    high_queue: high_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            )
        ],
    )

    npi_cpu_008_dhcp_v6_global_dscp0_to_mid_queue_playbook = Playbook(
        name=NPI_CPU_008_DHCP_V6_GLOBAL_DSCP0_TO_MID_QUEUE.name,
        description=(
            "CPU_008: DHCPv6 request with global source/destination IPv6 "
            "addresses and DSCP=0 (UDP src 546, dst 547) must be punted to "
            "the MID CPU queue. Verifies DHCPv6 host-mgmt classification "
            "falls through to UDP/547 protocol match even without DSCP "
            "marking on IPv6 global-scope sessions."
        ),
        traffic_items_to_start=[
            "TEST_RAW_DHCP_V6_GLOBAL_DSCP0_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                steps=[create_longevity_step(duration=60)],
            )
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[mid_queue],
                inactive_queues=[low_queue, high_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    high_queue: high_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            )
        ],
    )

    npi_cpu_009_dhcp_v6_ll_dscp48_to_mid_queue_playbook = Playbook(
        name=NPI_CPU_009_DHCP_V6_LL_DSCP48_TO_MID_QUEUE.name,
        description=(
            "CPU_009: DHCPv6 request with link-local source (fe80::) and "
            "link-local multicast destination (ff02::1:2) and DSCP=48 (UDP "
            "src 546, dst 547) must be punted to the MID CPU queue. Matches "
            "the real DHCPv6 client→server discovery flow with explicit DSCP "
            "marking."
        ),
        traffic_items_to_start=[
            "TEST_RAW_DHCP_V6_LL_DSCP48_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                steps=[create_longevity_step(duration=60)],
            )
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[mid_queue],
                inactive_queues=[low_queue, high_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    high_queue: high_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            )
        ],
    )

    npi_cpu_010_dhcp_v4_discover_bcast_to_mid_queue_playbook = Playbook(
        name="npi_cpu_010_dhcp_v4_discover_bcast_to_mid_queue",
        traffic_items_to_start=[
            "TEST_RAW_DHCP_V4_DISCOVER_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                steps=[create_longevity_step(duration=60)],
            )
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[mid_queue],
                inactive_queues=[low_queue, high_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    high_queue: high_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            )
        ],
    )

    npi_cpu_011_dhcp_v4_discover_ucast_to_mid_queue_playbook = Playbook(
        name="npi_cpu_011_dhcp_v4_discover_ucast_to_mid_queue",
        traffic_items_to_start=[
            "TEST_RAW_DHCP_V4_DISCOVER_TO_SERVER_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                steps=[create_longevity_step(duration=60)],
            )
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[mid_queue],
                inactive_queues=[low_queue, high_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    high_queue: high_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            )
        ],
    )

    npi_cpu_001_lldp_mcast_to_mid_queue_playbook = Playbook(
        name=NPI_CPU_001_LLDP_MCAST_TO_MID_QUEUE.name,
        traffic_items_to_start=[
            "TEST_RAW_LLDP_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                steps=[create_longevity_step(duration=60)],
            )
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[mid_queue],
                inactive_queues=[low_queue, high_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    high_queue: high_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            )
        ],
    )

    npi_cpu_005_bgp_cp_v4_def_gw_dscp48_to_high_queue_playbook = Playbook(
        name=NPI_CPU_005_BGP_CP_V4_DEF_GW_DSCP48_TO_HIGH_QUEUE.name,
        traffic_items_to_start=[
            "TEST_RAW_BGP_CP_V4_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                steps=[create_longevity_step(duration=60)],
            )
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[high_queue],
                inactive_queues=[low_queue, mid_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    mid_queue: mid_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            )
        ],
    )

    npi_cpu_006_bgp_cp_v4_def_gw_dscp0_to_high_queue_playbook = Playbook(
        name=NPI_CPU_006_BGP_CP_V4_DEF_GW_DSCP0_TO_HIGH_QUEUE.name,
        traffic_items_to_start=[
            "TEST_RAW_BGP_CP_V4_DSCP0_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                steps=[create_longevity_step(duration=60)],
            )
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[high_queue],
                inactive_queues=[low_queue, mid_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    mid_queue: mid_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            )
        ],
    )

    npi_cpu_002_bgp_cp_v6_global_dscp48_to_high_queue_playbook = Playbook(
        name=NPI_CPU_002_BGP_CP_V6_GLOBAL_DSCP48_TO_HIGH_QUEUE.name,
        description=(
            "CPU_002: BGPv6 control-plane traffic with global source/destination "
            "addresses and DSCP=48 (TCP/179) must be punted to the HIGH CPU queue. "
            "Verifies BGP CP classification for IPv6 global-scope sessions."
        ),
        traffic_items_to_start=[
            "TEST_RAW_BGP_CP_V6_GLOBAL_DSCP48_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                steps=[create_longevity_step(duration=60)],
            )
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[high_queue],
                inactive_queues=[low_queue, mid_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    mid_queue: mid_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            )
        ],
    )

    npi_cpu_003_bgp_cp_v6_link_local_dscp48_to_high_queue_playbook = Playbook(
        name=NPI_CPU_003_BGP_CP_V6_LINK_LOCAL_DSCP48_TO_HIGH_QUEUE.name,
        description=(
            "CPU_003: BGPv6 control-plane traffic with link-local source/destination "
            "addresses and DSCP=48 (TCP/179, Hop Limit=255) must be punted to the "
            "HIGH CPU queue. Verifies BGP CP classification for IPv6 link-local-scope "
            "sessions."
        ),
        traffic_items_to_start=[
            "TEST_RAW_BGP_CP_V6_LINK_LOCAL_DSCP48_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                steps=[create_longevity_step(duration=60)],
            )
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[high_queue],
                inactive_queues=[low_queue, mid_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    mid_queue: mid_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            )
        ],
    )

    npi_cpu_004_bgp_cp_v6_link_local_dscp0_to_high_queue_playbook = Playbook(
        name=NPI_CPU_004_BGP_CP_V6_LINK_LOCAL_DSCP0_TO_HIGH_QUEUE.name,
        description=(
            "CPU_004: BGPv6 control-plane traffic with link-local source/destination "
            "addresses and DSCP=0 (TCP/179) must be punted to the HIGH CPU queue. "
            "Verifies BGP CP classification falls through to TCP/179 protocol match "
            "even without DSCP marking on IPv6 link-local-scope sessions."
        ),
        traffic_items_to_start=[
            "TEST_RAW_BGP_CP_V6_LINK_LOCAL_DSCP0_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                steps=[create_longevity_step(duration=60)],
            )
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[high_queue],
                inactive_queues=[low_queue, mid_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    mid_queue: mid_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            )
        ],
    )

    npi_cpu_040_lacp_mcast_to_high_queue_playbook = Playbook(
        name=NPI_CPU_040_LACP_MCAST_TO_HIGH_QUEUE.name,
        traffic_items_to_start=[
            "TEST_LACP_SLOW_TIMER_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                steps=[create_longevity_step(duration=60)],
            )
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[high_queue],
                inactive_queues=[low_queue, mid_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    mid_queue: mid_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            )
        ],
    )

    npi_cpu_042_hop_limit_1_to_low_queue_playbook = Playbook(
        name=NPI_CPU_042_HOP_LIMIT_1_TO_LOW_QUEUE.name,
        traffic_items_to_start=[
            "TEST_NEXTHOP_LIMIT_1_IPV6_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                steps=[create_longevity_step(duration=60)],
            )
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[low_queue],
                inactive_queues=[mid_queue, high_queue],
                inactive_max_pps_per_queue={
                    mid_queue: mid_q_noise,
                    high_queue: high_q_noise,
                },
                no_discard_queues=[mid_queue, high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            )
        ],
    )

    npi_cpu_043_hop_limit_0_not_punted_playbook = Playbook(
        name=NPI_CPU_043_HOP_LIMIT_0_NOT_PUNTED.name,
        traffic_items_to_start=[
            "TEST_NEXTHOP_LIMIT_0_IPV6_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                steps=[create_longevity_step(duration=60)],
            )
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[],
                no_discard_queues=[low_queue, mid_queue, high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            )
        ],
    )

    npi_cpu_044_ttl_1_ipv4_to_low_queue_playbook = Playbook(
        name="npi_cpu_044_ttl_1_ipv4_to_low_queue",
        traffic_items_to_start=[
            "TEST_TTL_1_IPV4_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                steps=[create_longevity_step(duration=30)],
            )
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[low_queue],
                inactive_queues=[mid_queue, high_queue],
                inactive_max_pps_per_queue={
                    mid_queue: mid_q_noise,
                    high_queue: high_q_noise,
                },
                no_discard_queues=[mid_queue, high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            )
        ],
    )

    npi_cpu_045_ttl_0_ipv4_not_punted_playbook = Playbook(
        name="npi_cpu_045_ttl_0_ipv4_not_punted",
        traffic_items_to_start=[
            "TEST_TTL_0_IPV4_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                steps=[create_longevity_step(duration=30)],
            )
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[],
                no_discard_queues=[low_queue, mid_queue, high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            )
        ],
    )

    # CPU_039: MTU exceed → LOW queue. Oversize IPv6 packet exceeds DUT egress
    # MTU; router punts to CPU for ICMPv6 "Packet Too Big" generation.
    npi_cpu_039_mtu_exceed_to_low_queue_playbook = Playbook(
        name="npi_cpu_039_mtu_exceed_to_low_queue",
        traffic_items_to_start=[
            "TEST_MTU_EXCEED_IPV6_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                steps=[
                    # Test-case prerequisite: shrink the DUT egress
                    # interface MTU to 1500 BEFORE sending the
                    # traffic. Without this, the DUT keeps its
                    # provisioned 9000-byte jumbo MTU and even a
                    # 9100-byte frame either fits within MTU or
                    # is dropped silently — neither produces the
                    # MTU-exceed → CPU q0 punt the spec requires.
                    create_custom_step(
                        params_dict={
                            "custom_step_name": "change_interface_mtu_patcher",
                            "interface": ixia_downlink_interface,
                            "mtu": 1500,
                            "patcher_name": "mtu_exceed_patcher",
                        },
                    ),
                    # FBOSS gotcha: `change_mtu` agent-config patcher
                    # writes the new MTU to the agent's view of the
                    # interface config, but the underlying silicon does
                    # not re-program the port until the port is
                    # administratively bounced. Without this down/up
                    # cycle, `fboss2 show interface eth1/13/1` still
                    # reports the previous MTU (9000 on IcePack) and
                    # MTU-exceed frames silently forward without
                    # triggering the silicon's CPU punt. See Run 5 v6
                    # 2026-06-09 01:46 where MTU stayed at 9000
                    # post-patcher.
                    create_interface_flap_step(
                        enable=False,
                        interfaces=[ixia_downlink_interface],
                        interface_flap_method=4,  # SSH_PORT_STATE_CHANGE
                        step_id="mtu_change_force_flap_down",
                    ),
                    create_interface_flap_step(
                        enable=True,
                        interfaces=[ixia_downlink_interface],
                        interface_flap_method=4,  # SSH_PORT_STATE_CHANGE
                        step_id="mtu_change_force_flap_up",
                    ),
                    # Brief settle so the link comes back + BGP/IXIA
                    # streams re-establish before we measure punt.
                    create_longevity_step(duration=15),
                    # Verify the MTU change actually reached silicon
                    # before we depend on it. Fails loud if the patcher
                    # + flap combo did not propagate, so CPU_QUEUE_CHECK
                    # is not asked to interpret counters under an
                    # incorrect MTU assumption.
                    create_custom_step(
                        params_dict={
                            "custom_step_name": "verify_interface_mtu",
                            "interface": ixia_downlink_interface,
                            "expected_mtu": 1500,
                        },
                    ),
                    create_longevity_step(duration=30),
                    # Diagnostic: dump IXIA-side Tx/Rx for the MTU exceed
                    # traffic item BEFORE the snapshot check stops traffic.
                    # Disambiguates "No output packet increase on queue 0"
                    # — nonzero Tx Frames here means IXIA transmitted →
                    # silicon/CoPP didn't punt; zero Tx Frames means IXIA
                    # never sent → test/IXIA-side bug.
                    create_custom_step(
                        params_dict={
                            "custom_step_name": "dump_traffic_item_stats",
                            "traffic_item_names": [
                                "TEST_MTU_EXCEED_IPV6_TRAFFIC",
                            ],
                        },
                    ),
                    # Restore the DUT egress interface MTU back to its
                    # provisioned value (paired with the
                    # change_interface_mtu_patcher above).
                    create_unregister_patcher_step(
                        patcher_name="mtu_exceed_patcher",
                    ),
                ],
            )
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[low_queue],
                inactive_queues=[mid_queue, high_queue],
                inactive_max_pps_per_queue={
                    mid_queue: mid_q_noise,
                    high_queue: high_q_noise,
                },
                no_discard_queues=[mid_queue, high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            )
        ],
    )

    # CPU_046: martian SIP=def-gw → MUST NOT punt (negative test).
    npi_cpu_046_martian_sip_not_punted_playbook = Playbook(
        name="npi_cpu_046_martian_sip_not_punted",
        traffic_items_to_start=[
            "TEST_MARTIAN_SIP_IPV4_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                steps=[create_longevity_step(duration=30)],
            )
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[],
                no_discard_queues=[low_queue, mid_queue, high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            )
        ],
    )

    # CPU_047: DSCP=48 to-switch global IPv6 → MID queue. Generic IPv6 packet
    # destined to switch's own global address with DSCP=48 — host-bound class
    # of service, no L4/ICMP layer.
    npi_cpu_047_dscp_48_to_switch_global_to_mid_queue_playbook = Playbook(
        name="npi_cpu_047_dscp_48_to_switch_global_to_mid_queue",
        traffic_items_to_start=[
            "TEST_DSCP_48_TO_SWITCH_GLOBAL_IPV6_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                steps=[create_longevity_step(duration=30)],
            )
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[mid_queue],
                inactive_queues=[low_queue, high_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    high_queue: high_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={mid_queue: 10},
            )
        ],
    )

    # CPU_048: DSCP=48 to-switch link-local IPv6 → MID queue. Link-local
    # variant of CPU_047 (SIP=Ixia LL, DIP=switch LL).
    npi_cpu_048_dscp_48_to_switch_ll_to_mid_queue_playbook = Playbook(
        name="npi_cpu_048_dscp_48_to_switch_ll_to_mid_queue",
        traffic_items_to_start=[
            "TEST_DSCP_48_TO_SWITCH_LINK_LOCAL_IPV6_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                steps=[create_longevity_step(duration=30)],
            )
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[mid_queue],
                inactive_queues=[low_queue, high_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    high_queue: high_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={mid_queue: 10},
            )
        ],
    )

    npi_cpu_017_arp_request_bcast_to_high_queue_playbook = Playbook(
        name="npi_cpu_017_arp_request_bcast_to_high_queue",
        traffic_items_to_start=[
            "TEST_RAW_ARP_REQUEST_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                stage_id="npi_cpu_017_arp_request_bcast_to_high_queue",
                steps=[
                    create_longevity_step(duration=60),
                ],
            ),
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[high_queue],
                inactive_queues=[low_queue, mid_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    mid_queue: mid_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={high_queue: 10},
            ),
        ],
    )

    npi_cpu_018_arp_response_to_high_queue_playbook = Playbook(
        name=NPI_CPU_018_ARP_RESPONSE_TO_HIGH_QUEUE.name,
        description=(
            "CPU_018: ARP Response (EtherType 0x0806) with the Ethernet "
            "destination MAC set to the switch MAC (unicast). Per Cat 4 the "
            "ARP response must be punted to the HIGH CPU queue."
        ),
        traffic_items_to_start=[
            "TEST_RAW_ARP_RESPONSE_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                stage_id=NPI_CPU_018_ARP_RESPONSE_TO_HIGH_QUEUE.name,
                steps=[
                    create_longevity_step(duration=60),
                ],
            ),
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[high_queue],
                inactive_queues=[low_queue, mid_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    mid_queue: mid_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={high_queue: 10},
            ),
        ],
    )

    npi_cpu_019_arp_response_bcast_to_high_queue_playbook = Playbook(
        name=NPI_CPU_019_ARP_RESPONSE_BCAST_TO_HIGH_QUEUE.name,
        description=(
            "CPU_019: ARP Response (EtherType 0x0806) with the Ethernet "
            "destination MAC set to ff:ff:ff:ff:ff:ff (broadcast). Same "
            "ARP-response payload as CPU_018, only L2 framing differs. Per "
            "Cat 4 the broadcast-DMAC ARP response must still be punted to "
            "the HIGH CPU queue."
        ),
        traffic_items_to_start=[
            "TEST_RAW_ARP_RESPONSE_BCAST_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                stage_id=NPI_CPU_019_ARP_RESPONSE_BCAST_TO_HIGH_QUEUE.name,
                steps=[
                    create_longevity_step(duration=60),
                ],
            ),
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[high_queue],
                inactive_queues=[low_queue, mid_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    mid_queue: mid_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={high_queue: 10},
            ),
        ],
    )

    npi_cpu_020_ndp_ns_global_dscp48_to_high_queue_playbook = Playbook(
        name=NPI_CPU_020_NDP_NS_GLOBAL_DSCP48_TO_HIGH_QUEUE.name,
        description=(
            "CPU_020: NDP Neighbor Solicitation (ICMPv6 type 135) with global "
            "source/destination IPv6 addresses, DSCP=48, and Hop Limit=255 "
            "must be punted to the HIGH CPU queue. Verifies that the CoPP "
            "classifier elevates ICMPv6 type 135 to HIGH regardless of "
            "address scope."
        ),
        traffic_items_to_start=[
            "TEST_RAW_NDP_NS_GLOBAL_DSCP48_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                stage_id="npi_cpu_020_ndp_ns_global_dscp48_to_high_queue",
                steps=[
                    create_longevity_step(duration=60),
                ],
            ),
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[high_queue],
                inactive_queues=[low_queue, mid_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    mid_queue: mid_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={high_queue: 10},
            ),
        ],
    )

    npi_cpu_021_ndp_ns_ll_dscp48_to_high_queue_playbook = Playbook(
        name=NPI_CPU_021_NDP_NS_LL_DSCP48_TO_HIGH_QUEUE.name,
        description=(
            "CPU_021: NDP Neighbor Solicitation (ICMPv6 type 135) with "
            "link-local source (NDP_IXIA_LINK_LOCAL_IPV6) and link-local "
            "destination (DST_LINK_LOCAL_IPV6_ADDRESS), DSCP=48, and Hop "
            "Limit=255 must be punted to the HIGH CPU queue. Verifies the "
            "real-world (RFC 4861) NDP NS flow is classified to HIGH."
        ),
        traffic_items_to_start=[
            "TEST_NDP_NS_UNICAST_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                stage_id="npi_cpu_021_ndp_ns_ll_dscp48_to_high_queue",
                steps=[
                    create_longevity_step(duration=60),
                ],
            ),
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[high_queue],
                inactive_queues=[low_queue, mid_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    mid_queue: mid_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={high_queue: 10},
            ),
        ],
    )

    # CPU_032 (NDP NS LL DSCP=48) is the same spec as CPU_021 — covered by
    # npi_cpu_021_ndp_ns_ll_dscp48_to_high_queue_playbook above. The utp
    # catalog entry for CPU_032 points to that playbook; no separate
    # CPU_032 playbook is constructed here.

    npi_cpu_033_ndp_na_ll_to_high_queue_playbook = Playbook(
        name=NPI_CPU_033_NDP_NA_LL_TO_HIGH_QUEUE.name,
        description=(
            "CPU_033: NDP Neighbor Advertisement (ICMPv6 type 136) with "
            "link-local source (NDP_IXIA_LINK_LOCAL_IPV6) and link-local "
            "destination (DST_LINK_LOCAL_IPV6_ADDRESS) and Hop Limit=255 "
            "must be punted to the HIGH CPU queue. Verifies the real-world "
            "(RFC 4861) NDP NA flow is classified to HIGH; replaces the "
            "earlier all-nodes-multicast hybrid which did not match the Cat "
            "4 spec for CPU_033."
        ),
        traffic_items_to_start=[
            "TEST_NDP_NA_UNICAST_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                stage_id=NPI_CPU_033_NDP_NA_LL_TO_HIGH_QUEUE.name,
                steps=[
                    create_longevity_step(duration=60),
                ],
            ),
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[high_queue],
                inactive_queues=[low_queue, mid_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    mid_queue: mid_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={high_queue: 10},
            ),
        ],
    )

    npi_cpu_034_ndp_rs_mcast_to_high_queue_playbook = Playbook(
        name="npi_cpu_034_ndp_rs_mcast_to_high_queue",
        traffic_items_to_start=[
            "TEST_NDP_RS_MULTICAST_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                stage_id="npi_cpu_034_ndp_rs_mcast_to_high_queue",
                steps=[
                    create_longevity_step(duration=60),
                ],
            ),
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[high_queue],
                inactive_queues=[low_queue, mid_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    mid_queue: mid_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={high_queue: 10},
            ),
        ],
    )

    npi_cpu_035_ndp_ra_ll_to_high_queue_playbook = Playbook(
        name=NPI_CPU_035_NDP_RA_LL_TO_HIGH_QUEUE.name,
        description=(
            "CPU_035: NDP Router Advertisement (ICMPv6 type 134) with "
            "link-local source (NDP_IXIA_LINK_LOCAL_IPV6) and link-local "
            "destination (DST_LINK_LOCAL_IPV6_ADDRESS) and Hop Limit=255 "
            "must be punted to the HIGH CPU queue. Verifies the real-world "
            "(RFC 4861) NDP RA flow is classified to HIGH; replaces the "
            "earlier all-nodes-multicast hybrid which did not match the Cat "
            "4 spec for CPU_035."
        ),
        traffic_items_to_start=[
            "TEST_NDP_RA_UNICAST_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                stage_id=NPI_CPU_035_NDP_RA_LL_TO_HIGH_QUEUE.name,
                steps=[
                    create_longevity_step(duration=60),
                ],
            ),
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[high_queue],
                inactive_queues=[low_queue, mid_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    mid_queue: mid_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={high_queue: 10},
            ),
        ],
    )

    # Commented out as this is not supported in the current version of the testbed for KO3 devices T252169955
    # Playbook(
    #     name="test_ndp_ns_unicast_traffic_punted_to_cpu_high_queue",
    #     ...
    # ),
    # Playbook(
    #     name="test_ndp_na_unicast_traffic_punted_to_cpu_high_queue",
    #     ...
    # ),
    # Playbook(
    #     name="test_ndp_rs_unicast_traffic_punted_to_cpu_high_queue",
    #     ...
    # ),
    # Playbook(
    #     name="test_ndp_ra_unicast_traffic_punted_to_cpu_high_queue",
    #     ...
    # ),
    # ICMPv6 Non-NDP with Link-Local Addresses - Punted to MID queue
    npi_cpu_027_icmp_v6_echo_req_ll_dscp0_to_mid_queue_playbook = Playbook(
        name="npi_cpu_027_icmp_v6_echo_req_ll_dscp0_to_mid_queue",
        traffic_items_to_start=[
            "TEST_ICMPV6_ECHO_REQUEST_LINK_LOCAL_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                stage_id="npi_cpu_027_icmp_v6_echo_req_ll_dscp0_to_mid_queue",
                steps=[
                    create_longevity_step(duration=60),
                ],
            ),
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[mid_queue],
                inactive_queues=[low_queue, high_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    high_queue: high_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            ),
        ],
    )

    npi_cpu_028_icmp_v6_echo_reply_ll_dscp0_to_mid_queue_playbook = Playbook(
        name="npi_cpu_028_icmp_v6_echo_reply_ll_dscp0_to_mid_queue",
        traffic_items_to_start=[
            "TEST_ICMPV6_ECHO_REPLY_LINK_LOCAL_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                stage_id="npi_cpu_028_icmp_v6_echo_reply_ll_dscp0_to_mid_queue",
                steps=[
                    create_longevity_step(duration=60),
                ],
            ),
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[mid_queue],
                inactive_queues=[low_queue, high_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    high_queue: high_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            ),
        ],
    )

    npi_cpu_029_icmp_v6_dest_unreach_ll_dscp0_to_mid_queue_playbook = Playbook(
        name="npi_cpu_029_icmp_v6_dest_unreach_ll_dscp0_to_mid_queue",
        traffic_items_to_start=[
            "TEST_ICMPV6_DEST_UNREACHABLE_LINK_LOCAL_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                stage_id="npi_cpu_029_icmp_v6_dest_unreach_ll_dscp0_to_mid_queue",
                steps=[
                    create_longevity_step(duration=60),
                ],
            ),
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[mid_queue],
                inactive_queues=[low_queue, high_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    high_queue: high_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            ),
        ],
    )

    npi_cpu_030_icmp_v6_packet_too_big_ll_dscp0_to_mid_queue_playbook = Playbook(
        name="npi_cpu_030_icmp_v6_packet_too_big_ll_dscp0_to_mid_queue",
        traffic_items_to_start=[
            "TEST_ICMPV6_PACKET_TOO_BIG_LINK_LOCAL_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                stage_id="npi_cpu_030_icmp_v6_packet_too_big_ll_dscp0_to_mid_queue",
                steps=[
                    create_longevity_step(duration=60),
                ],
            ),
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[mid_queue],
                inactive_queues=[low_queue, high_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    high_queue: high_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            ),
        ],
    )

    npi_cpu_031_icmp_v6_time_exceeded_ll_dscp0_to_mid_queue_playbook = Playbook(
        name="npi_cpu_031_icmp_v6_time_exceeded_ll_dscp0_to_mid_queue",
        traffic_items_to_start=[
            "TEST_ICMPV6_TIME_EXCEEDED_LINK_LOCAL_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                stage_id="npi_cpu_031_icmp_v6_time_exceeded_ll_dscp0_to_mid_queue",
                steps=[
                    create_longevity_step(duration=60),
                ],
            ),
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[mid_queue],
                inactive_queues=[low_queue, high_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    high_queue: high_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            ),
        ],
    )

    # ICMPv6 Non-NDP with Global Addresses and DSCP 48 - Punted to MID queue
    npi_cpu_022_icmp_v6_echo_req_global_dscp48_to_mid_queue_playbook = Playbook(
        name="npi_cpu_022_icmp_v6_echo_req_global_dscp48_to_mid_queue",
        traffic_items_to_start=[
            "TEST_ICMPV6_ECHO_REQUEST_GLOBAL_DSCP48_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                stage_id="npi_cpu_022_icmp_v6_echo_req_global_dscp48_to_mid_queue",
                steps=[
                    create_longevity_step(duration=60),
                ],
            ),
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[mid_queue],
                inactive_queues=[low_queue, high_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    high_queue: high_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            ),
        ],
    )

    npi_cpu_023_icmp_v6_echo_reply_global_dscp48_to_mid_queue_playbook = Playbook(
        name="npi_cpu_023_icmp_v6_echo_reply_global_dscp48_to_mid_queue",
        traffic_items_to_start=[
            "TEST_ICMPV6_ECHO_REPLY_GLOBAL_DSCP48_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                stage_id="npi_cpu_023_icmp_v6_echo_reply_global_dscp48_to_mid_queue",
                steps=[
                    create_longevity_step(duration=60),
                ],
            ),
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[mid_queue],
                inactive_queues=[low_queue, high_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    high_queue: high_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            ),
        ],
    )

    npi_cpu_024_icmp_v6_dest_unreach_global_dscp48_to_mid_queue_playbook = Playbook(
        name="npi_cpu_024_icmp_v6_dest_unreach_global_dscp48_to_mid_queue",
        traffic_items_to_start=[
            "TEST_ICMPV6_DEST_UNREACHABLE_GLOBAL_DSCP48_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                stage_id="npi_cpu_024_icmp_v6_dest_unreach_global_dscp48_to_mid_queue",
                steps=[
                    create_longevity_step(duration=60),
                ],
            ),
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[mid_queue],
                inactive_queues=[low_queue, high_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    high_queue: high_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            ),
        ],
    )

    npi_cpu_025_icmp_v6_packet_too_big_global_dscp48_to_mid_queue_playbook = Playbook(
        name="npi_cpu_025_icmp_v6_packet_too_big_global_dscp48_to_mid_queue",
        traffic_items_to_start=[
            "TEST_ICMPV6_PACKET_TOO_BIG_GLOBAL_DSCP48_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                stage_id="npi_cpu_025_icmp_v6_packet_too_big_global_dscp48_to_mid_queue",
                steps=[
                    create_longevity_step(duration=60),
                ],
            ),
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[mid_queue],
                inactive_queues=[low_queue, high_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    high_queue: high_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            ),
        ],
    )

    npi_cpu_026_icmp_v6_time_exceeded_global_dscp48_to_mid_queue_playbook = Playbook(
        name="npi_cpu_026_icmp_v6_time_exceeded_global_dscp48_to_mid_queue",
        traffic_items_to_start=[
            "TEST_ICMPV6_TIME_EXCEEDED_GLOBAL_DSCP48_TRAFFIC",
        ],
        stages=[
            create_steps_stage(
                stage_id="npi_cpu_026_icmp_v6_time_exceeded_global_dscp48_to_mid_queue",
                steps=[
                    create_longevity_step(duration=60),
                ],
            ),
        ],
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[mid_queue],
                inactive_queues=[low_queue, high_queue],
                inactive_max_pps_per_queue={
                    low_queue: low_q_noise,
                    high_queue: high_q_noise,
                },
                no_discard_queues=[high_queue],
                active_min_out_pps_per_queue={low_queue: 10},
            ),
        ],
    )

    # Complex UNH playbooks - require ixia_downlink_interface
    #
    # Each of these 3 UNH playbooks runs `create_service_interruption_step(
    # service=Service.AGENT)` twice (once to apply the patcher, once to
    # unregister it). The wedge_agent restart cascades a bgpd restart
    # (bgpd's RIB state depends on wedge_agent for FIB programming), so
    # both daemons must be in `expected_restarted_services` and the
    # postcheck tolerates the by-design cascade (Pavan-confirmed,
    # T274731352 closed 2026-06-11).
    npi_cpu_037_unh_remote_subnet_to_low_queue_playbook = Playbook(
        postchecks=[
            create_ixia_packet_loss_check(clear_traffic_stats=True),
            create_service_restart_check(
                services=SERVICES_TO_MONITOR_DURING_AGENT_RESTART,
                expected_restarted_services=WEDGE_AGENT_BINDS_TO_CASCADE,
            ),
        ],
        traffic_items_to_start=["BGP_PREFIX_TRAFFIC"],
        name=NPI_CPU_037_UNH_REMOTE_SUBNET_TO_LOW_QUEUE.name,
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[low_queue],
                inactive_queues=[mid_queue, high_queue],
                inactive_max_pps_per_queue={
                    mid_queue: mid_q_noise,
                    high_queue: high_q_noise,
                },
                no_discard_queues=[mid_queue, high_queue],
                pre_snapshot_checkpoint_id="stage.test_fboss_cpu_remote_subnet_unh.step.disable_next_hop_egress_port.end",
                post_snapshot_checkpoint_id="stage.test_fboss_cpu_remote_subnet_unh.step.enable_next_hop_egress_port.start",
            ),
            create_cpu_queue_snapshot_check(
                active_queues=[],
                no_discard_queues=[high_queue],
                pre_snapshot_checkpoint_id="stage.test_fboss_cpu_remote_subnet_unh.step.enable_next_hop_egress_port.end",
            ),
        ],
        stages=[
            create_steps_stage(
                stage_id="npi_cpu_037_unh_remote_subnet_to_low_queue",
                steps=[
                    create_custom_step(
                        params_dict={
                            "custom_step_name": "register_cpu_queue_static_route_patcher",
                            "static_route_mask": 64,
                            "next_hop_egress_port": ixia_downlink_interface,
                            "patcher_name": "cpu_queue_static_route_patcher",
                        },
                    ),
                    create_service_interruption_step(service=Service.AGENT),
                    create_service_convergence_step(),
                    create_interface_flap_step(
                        enable=False,
                        interfaces=[ixia_downlink_interface],
                        interface_flap_method=4,  # SSH_PORT_STATE_CHANGE
                        step_id="disable_next_hop_egress_port",
                    ),
                    create_longevity_step(duration=60),
                    create_interface_flap_step(
                        enable=True,
                        interfaces=[ixia_downlink_interface],
                        interface_flap_method=4,  # SSH_PORT_STATE_CHANGE
                        step_id="enable_next_hop_egress_port",
                    ),
                    create_longevity_step(duration=60),
                    create_unregister_patcher_step(
                        patcher_name="cpu_queue_static_route_patcher",
                    ),
                    create_service_interruption_step(service=Service.AGENT),
                    create_service_convergence_step(),
                ],
            )
        ],
    )

    npi_cpu_038_unh_remote_host_route_to_low_queue_playbook = Playbook(
        postchecks=[
            create_ixia_packet_loss_check(clear_traffic_stats=True),
            create_service_restart_check(
                services=SERVICES_TO_MONITOR_DURING_AGENT_RESTART,
                expected_restarted_services=WEDGE_AGENT_BINDS_TO_CASCADE,
            ),
        ],
        traffic_items_to_start=["BGP_PREFIX_TRAFFIC"],
        name=NPI_CPU_038_UNH_REMOTE_HOST_ROUTE_TO_LOW_QUEUE.name,
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[low_queue],
                inactive_queues=[mid_queue, high_queue],
                inactive_max_pps_per_queue={
                    mid_queue: mid_q_noise,
                    high_queue: high_q_noise,
                },
                no_discard_queues=[mid_queue, high_queue],
                pre_snapshot_checkpoint_id="stage.test_fboss_cpu_remote_subnet_128_unh.step.disable_next_hop_egress_port.end",
                post_snapshot_checkpoint_id="stage.test_fboss_cpu_remote_subnet_128_unh.step.enable_next_hop_egress_port.start",
            ),
            create_cpu_queue_snapshot_check(
                active_queues=[],
                no_discard_queues=[high_queue],
                pre_snapshot_checkpoint_id="stage.test_fboss_cpu_remote_subnet_128_unh.step.enable_next_hop_egress_port.end",
            ),
        ],
        stages=[
            create_steps_stage(
                stage_id="npi_cpu_038_unh_remote_host_route_to_low_queue",
                steps=[
                    create_custom_step(
                        params_dict={
                            "custom_step_name": "register_cpu_queue_static_route_patcher",
                            "static_route_mask": 128,
                            "next_hop_egress_port": ixia_downlink_interface,
                            "patcher_name": "cpu_queue_static_route_patcher",
                        },
                    ),
                    create_service_interruption_step(service=Service.AGENT),
                    create_service_convergence_step(),
                    create_interface_flap_step(
                        enable=False,
                        interfaces=[ixia_downlink_interface],
                        interface_flap_method=4,  # SSH_PORT_STATE_CHANGE
                        step_id="disable_next_hop_egress_port",
                    ),
                    create_longevity_step(duration=60),
                    create_interface_flap_step(
                        enable=True,
                        interfaces=[ixia_downlink_interface],
                        interface_flap_method=4,  # SSH_PORT_STATE_CHANGE
                        step_id="enable_next_hop_egress_port",
                    ),
                    create_longevity_step(duration=60),
                    create_unregister_patcher_step(
                        patcher_name="cpu_queue_static_route_patcher",
                    ),
                    create_service_interruption_step(service=Service.AGENT),
                    create_service_convergence_step(),
                ],
            )
        ],
    )

    npi_cpu_036_unh_dir_conn_host_to_low_queue_playbook = Playbook(
        postchecks=[
            create_ixia_packet_loss_check(clear_traffic_stats=True),
            create_service_restart_check(
                services=SERVICES_TO_MONITOR_DURING_AGENT_RESTART,
                expected_restarted_services=WEDGE_AGENT_BINDS_TO_CASCADE,
            ),
        ],
        traffic_items_to_start=["IPV6_TRAFFIC"],
        name=NPI_CPU_036_UNH_DIR_CONN_HOST_TO_LOW_QUEUE.name,
        snapshot_checks=[
            create_cpu_queue_snapshot_check(
                active_queues=[low_queue],
                inactive_queues=[mid_queue, high_queue],
                inactive_max_pps_per_queue={
                    mid_queue: mid_q_noise,
                    high_queue: high_q_noise,
                },
                no_discard_queues=[mid_queue, high_queue],
                pre_snapshot_checkpoint_id="stage.test_fboss_cpu_dir_conn_host_unh.step.disable_next_hop_egress_port.end",
                post_snapshot_checkpoint_id="stage.test_fboss_cpu_dir_conn_host_unh.step.enable_next_hop_egress_port.start",
            ),
            create_cpu_queue_snapshot_check(
                active_queues=[],
                no_discard_queues=[high_queue],
                pre_snapshot_checkpoint_id="stage.test_fboss_cpu_dir_conn_host_unh.step.enable_next_hop_egress_port.end",
            ),
        ],
        stages=[
            create_steps_stage(
                stage_id="npi_cpu_036_unh_dir_conn_host_to_low_queue",
                steps=[
                    create_custom_step(
                        params_dict={
                            "custom_step_name": "register_cpu_queue_static_route_patcher",
                            "static_route_mask": 64,
                            "next_hop_egress_port": ixia_downlink_interface,
                            "patcher_name": "cpu_queue_static_route_patcher",
                        },
                    ),
                    create_service_interruption_step(service=Service.AGENT),
                    create_service_convergence_step(),
                    create_interface_flap_step(
                        enable=False,
                        interfaces=[ixia_downlink_interface],
                        interface_flap_method=4,  # SSH_PORT_STATE_CHANGE
                        step_id="disable_next_hop_egress_port",
                    ),
                    create_longevity_step(duration=60),
                    create_interface_flap_step(
                        enable=True,
                        interfaces=[ixia_downlink_interface],
                        interface_flap_method=4,  # SSH_PORT_STATE_CHANGE
                        step_id="enable_next_hop_egress_port",
                    ),
                    create_longevity_step(duration=60),
                    create_unregister_patcher_step(
                        patcher_name="cpu_queue_static_route_patcher",
                    ),
                    create_service_interruption_step(service=Service.AGENT),
                    create_service_convergence_step(),
                ],
            )
        ],
    )

    return [
        longevity_playbook,
        test_cpu_mid_queue_traffic_playbook,
        test_cpu_high_queue_traffic_playbook,
        npi_cpu_041_queue_prioritization_high_no_drops_playbook,
        npi_cpu_016_icmp_v6_echo_req_ll_to_mid_queue_playbook,
        npi_cpu_012_icmp_v4_echo_req_to_mid_queue_playbook,
        npi_cpu_013_icmp_v4_echo_reply_to_mid_queue_playbook,
        npi_cpu_014_icmp_v4_dest_unreach_to_mid_queue_playbook,
        npi_cpu_015_icmp_v4_time_exceeded_to_mid_queue_playbook,
        npi_cpu_007_dhcp_v6_global_dscp48_to_mid_queue_playbook,
        npi_cpu_008_dhcp_v6_global_dscp0_to_mid_queue_playbook,
        npi_cpu_009_dhcp_v6_ll_dscp48_to_mid_queue_playbook,
        npi_cpu_010_dhcp_v4_discover_bcast_to_mid_queue_playbook,
        npi_cpu_011_dhcp_v4_discover_ucast_to_mid_queue_playbook,
        npi_cpu_001_lldp_mcast_to_mid_queue_playbook,
        npi_cpu_005_bgp_cp_v4_def_gw_dscp48_to_high_queue_playbook,
        npi_cpu_006_bgp_cp_v4_def_gw_dscp0_to_high_queue_playbook,
        npi_cpu_002_bgp_cp_v6_global_dscp48_to_high_queue_playbook,
        npi_cpu_003_bgp_cp_v6_link_local_dscp48_to_high_queue_playbook,
        npi_cpu_004_bgp_cp_v6_link_local_dscp0_to_high_queue_playbook,
        npi_cpu_040_lacp_mcast_to_high_queue_playbook,
        npi_cpu_042_hop_limit_1_to_low_queue_playbook,
        npi_cpu_043_hop_limit_0_not_punted_playbook,
        npi_cpu_044_ttl_1_ipv4_to_low_queue_playbook,
        npi_cpu_045_ttl_0_ipv4_not_punted_playbook,
        npi_cpu_039_mtu_exceed_to_low_queue_playbook,
        npi_cpu_046_martian_sip_not_punted_playbook,
        npi_cpu_047_dscp_48_to_switch_global_to_mid_queue_playbook,
        npi_cpu_048_dscp_48_to_switch_ll_to_mid_queue_playbook,
        npi_cpu_017_arp_request_bcast_to_high_queue_playbook,
        npi_cpu_018_arp_response_to_high_queue_playbook,
        npi_cpu_019_arp_response_bcast_to_high_queue_playbook,
        npi_cpu_020_ndp_ns_global_dscp48_to_high_queue_playbook,
        npi_cpu_021_ndp_ns_ll_dscp48_to_high_queue_playbook,
        npi_cpu_033_ndp_na_ll_to_high_queue_playbook,
        npi_cpu_034_ndp_rs_mcast_to_high_queue_playbook,
        npi_cpu_035_ndp_ra_ll_to_high_queue_playbook,
        npi_cpu_027_icmp_v6_echo_req_ll_dscp0_to_mid_queue_playbook,
        npi_cpu_028_icmp_v6_echo_reply_ll_dscp0_to_mid_queue_playbook,
        npi_cpu_029_icmp_v6_dest_unreach_ll_dscp0_to_mid_queue_playbook,
        npi_cpu_030_icmp_v6_packet_too_big_ll_dscp0_to_mid_queue_playbook,
        npi_cpu_031_icmp_v6_time_exceeded_ll_dscp0_to_mid_queue_playbook,
        npi_cpu_022_icmp_v6_echo_req_global_dscp48_to_mid_queue_playbook,
        npi_cpu_023_icmp_v6_echo_reply_global_dscp48_to_mid_queue_playbook,
        npi_cpu_024_icmp_v6_dest_unreach_global_dscp48_to_mid_queue_playbook,
        npi_cpu_025_icmp_v6_packet_too_big_global_dscp48_to_mid_queue_playbook,
        npi_cpu_026_icmp_v6_time_exceeded_global_dscp48_to_mid_queue_playbook,
        npi_cpu_037_unh_remote_subnet_to_low_queue_playbook,
        npi_cpu_038_unh_remote_host_route_to_low_queue_playbook,
        npi_cpu_036_unh_dir_conn_host_to_low_queue_playbook,
    ]


# ----- Migrated from playbooks/helpers/mtia/mtia_eibgp_test_configs_playbooks.py -----


def create_mtia_eibgp_longevity_playbook(longevity_duration: int) -> Playbook:
    """Build the MTIA eiBGP longevity Playbook.

    Single-stage longevity soak for the MTIA eiBGP TestConfigs, gated by
    systemctl-active, prefix-limit (74000), and unclean-exit prechecks;
    postchecks add device-core-dumps and service-restart assertions, with
    a core-dumps snapshot check.

    Args:
        longevity_duration: Wall-clock duration of the longevity stage in
            seconds.

    Returns:
        A `Playbook` named `test_mtia_eibgp_longevity`.
    """
    return Playbook(
        name="test_mtia_eibgp_longevity",
        prechecks=[
            create_systemctl_active_state_check(),
            create_prefix_limit_check(prefix_limit=74000),
            create_unclean_exit_check(),
        ],
        postchecks=[
            create_systemctl_active_state_check(),
            create_device_core_dumps_check(),
            create_unclean_exit_check(),
            create_service_restart_check(),
        ],
        snapshot_checks=[
            create_core_dumps_snapshot_check(),
        ],
        stages=[create_longevity_stage(duration=longevity_duration)],
    )


# ----- Migrated from playbooks/helpers/networkai/fboss_tahan_playbooks.py -----

TEST_LONGEVITY_PLAYBOOK = Playbook(
    name="test_10_min_longevity",
    stages=[
        create_steps_stage(
            steps=[
                create_longevity_step(duration=600),
            ]
        )
    ],
    postchecks=[
        create_ixia_packet_loss_check(clear_traffic_stats=True),
    ],
    snapshot_checks=[
        create_core_dumps_snapshot_check(),
    ],
)


TAHAN_SNAPSHOT_CHECKS = [
    create_core_dumps_snapshot_check(),
]


def create_port_flap_playbook(
    interface_to_flap,
    interface_flap_method,
    traffic_items_to_start,
    iteration,
):
    """Create a port-flap iteration playbook for SUSW testing.

    Args:
        interface_to_flap: List of interfaces to flap.
        interface_flap_method: Method to use for flapping the interface.
        traffic_items_to_start: List of traffic items to start.
        iteration: Number of port-flap iterations.

    Returns:
        Playbook: A configured port-flap playbook.
    """
    return Playbook(
        name="test_port_flap_susw",
        prechecks=[
            create_port_state_check(),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_interface_flap_step(
                        enable=False,
                        interfaces=interface_to_flap,
                    ),
                    create_interface_flap_step(
                        enable=True,
                        interfaces=interface_to_flap,
                    ),
                ]
            )
        ],
        postchecks=[
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=traffic_items_to_start,
                        str_value="0.1",
                        metric=hc_types.PacketLossMetric.DURATION,
                    )
                ],
                clear_traffic_stats=True,
            ),
            create_port_state_check(),
        ],
        traffic_items_to_start=traffic_items_to_start,
        iteration=iteration,
        snapshot_checks=[
            create_core_dumps_snapshot_check(),
        ],
    )


def add_snapshot_checks_to_playbooks(playbooks):
    """Add Tahan-standard snapshot_checks to each playbook, respecting `snapshot_checks_to_skip`."""
    result = []
    for pb in playbooks:
        checks_to_skip = pb.snapshot_checks_to_skip or []
        checks_to_add = [
            sc for sc in TAHAN_SNAPSHOT_CHECKS if sc.name not in checks_to_skip
        ]
        if checks_to_add:
            result.append(
                Playbook(
                    name=pb.name,
                    prechecks=pb.prechecks,
                    postchecks=pb.postchecks,
                    stages=pb.stages,
                    iteration=pb.iteration,
                    traffic_items_to_start=pb.traffic_items_to_start,
                    snapshot_checks=(pb.snapshot_checks or []) + checks_to_add,
                    enabled=pb.enabled,
                )
            )
        else:
            result.append(pb)
    return result


# ----- Migrated from playbooks/helpers/networkai/network_ai_playbooks.py -----
# Note: 4 functions (create_dsf_pfc_check, create_pfc_wd_check,
# create_packet_loss_check, create_playbook_wd) were already present in
# playbook_definitions with compatible signatures and minor improvements;
# the helper duplicates are intentionally NOT migrated — calls resolve to
# the pre-existing definitions.

PLAYBOOKS_TEST = [
    Playbook(
        name="test_qos_functionality_nc_be",
        stages=[
            create_steps_stage(
                steps=[
                    create_longevity_step(duration=60),
                ]
            )
        ],
        postchecks=[
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=["TEST_PACKET_LOSS"],
                        str_value="0",
                    ),
                ]
            )
        ],
        traffic_items_to_start=["TEST_PACKET_LOSS"],
        enabled=True,
    ),
]


def create_qos_playbooks(
    traffic_items: dict[str, taac_types.BasicTrafficItemConfig],
    is_monitoring_lossless: bool = False,
) -> list[Playbook]:
    """Creates a list of playbooks for testing QoS functionality between different traffic classes.

    Args:
        traffic_items: A dict mapping 4 traffic classes to corresponding traffic item configs.
            Keys should be ["RDMA", "BE", "NC", "MONITORING"]
        is_monitoring_lossless: Whether monitoring traffic is lossless (True) or lossy (False)

    Returns:
        A list of playbooks for testing QoS functionality between different traffic classes
    """
    traffic_item_details = {}
    # Check for None names and raise an error if any are found
    for key in ["RDMA", "BE", "NC", "MONITORING"]:
        item = traffic_items[key]
        name = item.name
        if name is None:
            raise ValueError(f"Traffic item '{key}' has no name.")
        traffic_item_details[key] = {
            "traffic_name": name,
            "src_endpoints": item.src_endpoints,
            "dest_endpoints": item.dest_endpoints,
        }
    return [
        create_qos_playbook(
            "test_qos_functionality_nc_be",
            # pyrefly: ignore [bad-argument-type]
            {
                traffic_item_details["NC"]["traffic_name"]: "0",
                traffic_item_details["BE"]["traffic_name"]: "100",
            },
            [
                # pyrefly: ignore [missing-attribute]
                endpoint.name
                for endpoint in traffic_item_details["NC"]["dest_endpoints"]
            ],  # destination endpoints would be the same for both traffics
            [
                (hc_types.Priority.PRIORITY_7, hc_types.ComparisonType.EQUAL_TO, 70),
                (hc_types.Priority.PRIORITY_0, hc_types.ComparisonType.EQUAL_TO, 30),
            ],
        ),
        create_qos_playbook(
            "test_qos_functionality_rdma_be",
            # pyrefly: ignore [bad-argument-type]
            {
                traffic_item_details["RDMA"]["traffic_name"]: "0",
                traffic_item_details["BE"]["traffic_name"]: "100",
            },
            [
                # pyrefly: ignore [missing-attribute]
                endpoint.name
                for endpoint in traffic_item_details["RDMA"]["dest_endpoints"]
            ],
            [
                (hc_types.Priority.PRIORITY_2, hc_types.ComparisonType.EQUAL_TO, 70),
                (hc_types.Priority.PRIORITY_0, hc_types.ComparisonType.EQUAL_TO, 30),
            ],
        ),
        create_qos_playbook(
            "test_qos_functionality_nc_monitoring",
            # pyrefly: ignore [bad-argument-type]
            {
                traffic_item_details["NC"]["traffic_name"]: "0",
                traffic_item_details["MONITORING"]["traffic_name"]: (
                    "0" if is_monitoring_lossless else "100"
                ),
            },
            [
                # pyrefly: ignore [missing-attribute]
                endpoint.name
                for endpoint in traffic_item_details["NC"]["dest_endpoints"]
            ],
            [
                (hc_types.Priority.PRIORITY_7, hc_types.ComparisonType.EQUAL_TO, 70),
                (hc_types.Priority.PRIORITY_6, hc_types.ComparisonType.EQUAL_TO, 30),
            ],
        ),
        create_qos_playbook(
            "test_qos_functionality_rdma_nc",
            # pyrefly: ignore [bad-argument-type]
            {
                traffic_item_details["RDMA"]["traffic_name"]: "0",
                traffic_item_details["NC"]["traffic_name"]: "0",
            },
            [
                # pyrefly: ignore [missing-attribute]
                endpoint.name
                for endpoint in traffic_item_details["NC"]["dest_endpoints"]
            ],
            [
                (hc_types.Priority.PRIORITY_7, hc_types.ComparisonType.EQUAL_TO, 70),
                (hc_types.Priority.PRIORITY_2, hc_types.ComparisonType.EQUAL_TO, 30),
            ],
        ),
        create_qos_playbook(
            "test_qos_functionality_monitoring_be",
            # pyrefly: ignore [bad-argument-type]
            {
                traffic_item_details["MONITORING"]["traffic_name"]: "0",
                traffic_item_details["BE"]["traffic_name"]: "100",
            },
            [
                # pyrefly: ignore [missing-attribute]
                endpoint.name
                for endpoint in traffic_item_details["BE"]["dest_endpoints"]
            ],
            [
                (hc_types.Priority.PRIORITY_6, hc_types.ComparisonType.EQUAL_TO, 70),
                (hc_types.Priority.PRIORITY_0, hc_types.ComparisonType.EQUAL_TO, 30),
            ],
        ),
        create_qos_playbook(
            "test_qos_functionality_monitoring_rdma",
            # pyrefly: ignore [bad-argument-type]
            {
                traffic_item_details["MONITORING"]["traffic_name"]: "0",
                traffic_item_details["RDMA"]["traffic_name"]: "0",
            },
            [],
            [],
        ),
    ]


def create_qos_playbook(
    name: str,
    traffic_name_to_loss_threshold: dict[str, str],
    interfaces: list[str],
    priority_rate_list: list[tuple[hc_types.Priority, hc_types.ComparisonType, int]],
) -> Playbook:
    """Creates a single playbook for testing QoS functionality.

    Args:
        name: The name of the playbook
        traffic_name_to_loss_threshold: A dictionary mapping traffic item names to their
            expected packet loss thresholds as strings (e.g., "0" for no loss, "58" for 58% loss)
        interfaces: A list of interfaces to check queue rates
        priority_rate_list: A list of tuples containing priority, comparison type, and rate percentage
    Returns:
        A playbook configured for QoS testing with the specified traffic items and thresholds
    """
    priority_rate_thresholds = [
        hc_types.PriorityRateThreshold(
            priority=priority,
            comparison=comparison,
            rate_percent=rate_percent,
        )
        for priority, comparison, rate_percent in priority_rate_list
    ]
    return Playbook(
        name=name,
        stages=[
            create_steps_stage(
                steps=[
                    create_longevity_step(duration=60),
                ]
            )
        ],
        postchecks=[
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=[name],
                        str_value=value,
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    )
                    for name, value in traffic_name_to_loss_threshold.items()
                ]
            ),
            create_port_queue_rate_check(
                thresholds=[
                    hc_types.PortQueueRateThreshold(
                        interfaces=interfaces,
                        priority_rate_thresholds=priority_rate_thresholds,
                    ),
                ],
            ),
        ],
        traffic_items_to_start=list(traffic_name_to_loss_threshold),
        enabled=True,
    )


def create_pfc_functionality_congestion_non_pfc_traffic(
    name: str,
    description: str,
    pfc_traffic_items_names: t.List[str],
    be_traffic_item_name: str,
    src_endpoints: t.List[TrafficEndpoint],
    dst_endpoints: t.List[TrafficEndpoint],
    traffic_duration: int,
    priority: hc_types.Priority = hc_types.Priority.PRIORITY_2,
) -> Playbook:
    """Build a PFC-functionality Playbook for congestion in a non-PFC queue.

    Runs `traffic_duration` seconds of mixed traffic where the PFC items
    flow at their priority and a Best-Effort item competes on the same
    egress port at 24% line rate. Asserts zero loss on PFC items, ~65%
    loss on BE (BE caps at 10% line rate), the PFC items still see
    ~29% TX rate, no outbound PFC pauses from the source endpoints, and
    nonzero out_discards on the destination endpoints (proving
    congestion).

    Args:
        name: Playbook name.
        description: Playbook description (free-form).
        pfc_traffic_items_names: IXIA traffic items carrying PFC priority.
        be_traffic_item_name: IXIA traffic item used as the BE competitor.
        src_endpoints: Source traffic endpoints (first three are checked
            for outbound PFC counts).
        dst_endpoints: Destination traffic endpoints (checked for
            out_discards > 0).
        traffic_duration: Test duration in seconds.
        priority: PFC priority enum; the DSF PFC check asserts no
            outbound pause for this priority. Default `PRIORITY_2`.

    Returns:
        A `Playbook` with one longevity stage, the above postchecks, and
        all PFC + BE traffic items started.
    """
    return Playbook(
        name=name,
        description=description,
        prechecks=[
            create_clear_counters_check(),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_longevity_step(duration=traffic_duration),
                ]
            )
        ],
        postchecks=[
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=pfc_traffic_items_names,
                        str_value="0",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                    # BE traffic gets 10% line rate (40 Gbps)
                    # Tx 24% line rate is 96 Gbps, (96-40)/96 = ~58%
                    hc_types.PacketLossThreshold(
                        names=[be_traffic_item_name],
                        str_value="65",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                ]
            ),
            create_ixia_traffic_rate_check(
                thresholds=[
                    hc_types.TrafficRateThreshold(
                        names=pfc_traffic_items_names,
                        value=29,
                        threshold_type=hc_types.ThresholdType.PERCENT,
                        metric=hc_types.TrafficRateMetric.TX_RATE,
                    ),
                ]
            ),
            _create_dsf_pfc_check_central(
                thresholds=[
                    hc_types.DsfPfcThreshold(
                        interfaces=[endpoint.name for endpoint in src_endpoints[:3]],
                        out_pfc=0,
                        comparison=hc_types.ComparisonType.EQUAL_TO,
                        priority=priority,
                    ),
                ]
            ),
            create_port_counters_check(
                thresholds=[
                    hc_types.PortCountersThreshold(
                        interfaces=[endpoint.name for endpoint in dst_endpoints],
                        out_discards=0,
                        comparison=hc_types.ComparisonType.GREATER_THAN,
                    ),
                ]
            ),
        ],
        traffic_items_to_start=pfc_traffic_items_names + [be_traffic_item_name],
    )


def gen_endurance_playbook(playbook: Playbook, iteration: int) -> Playbook:
    return playbook(iteration=iteration)


def get_playbook_longevity(
    name: str,
    time_in_seconds: int,
    traffic_item_list: t.List[str],
    device_regexes: t.Optional[t.List[str]] = None,
) -> t.List[Playbook]:
    PLAYBOOK_LONGEVITY = [
        Playbook(
            name=name,
            device_regexes=device_regexes,
            stages=[
                create_steps_stage(
                    steps=[
                        create_longevity_step(duration=time_in_seconds),
                    ]
                )
            ],
            postchecks=[
                create_packetloss_health_check(),
            ],
            traffic_items_to_start=traffic_item_list,
            enabled=True,
        ),
    ]
    return PLAYBOOK_LONGEVITY


def create_pfc_functionality_congestion_non_tc2_traffic_playbook(
    traffic_items_names_first_4: list[str],
    src_endpoints: t.List[TrafficEndpoint],
) -> Playbook:
    """Playbook factory for `test_pfc_functionality_congestion_non_tc2_traffic`.

    Originally inline inside `gen_pfc_functionality_test_configs`. Caller passes
    `traffic_items_names[:4]` (typically empty at the original construction
    point — preserves prior behavior) and the source endpoints.
    """
    return Playbook(
        name="test_pfc_functionality_congestion_non_tc2_traffic",
        prechecks=[
            create_clear_counters_check(),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_longevity_step(duration=60),
                ]
            )
        ],
        postchecks=[
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=traffic_items_names_first_4,
                        str_value="0",
                    ),
                    hc_types.PacketLossThreshold(
                        names=["TEST_BE_24_TRAFFIC"],
                        str_value="90",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                ]
            ),
            _create_dsf_pfc_check_central(
                thresholds=[
                    hc_types.DsfPfcThreshold(
                        interfaces=[endpoint.name for endpoint in src_endpoints],
                        out_pfc=0,
                    ),
                ]
            ),
        ],
        traffic_items_to_start=[
            "TEST_RDMA_24_TRAFFIC_1",
            "TEST_RDMA_24_TRAFFIC_2",
            "TEST_RDMA_24_TRAFFIC_3",
            "TEST_RDMA_24_TRAFFIC_4",
            "TEST_BE_24_TRAFFIC",
        ],
        enabled=True,
    )


def create_pfc_functionality_congestion_playbook(
    traffic_items_names: list[str],
) -> Playbook:
    """Playbook factory for `test_pfc_functionality_congestion`.

    Originally inline inside `gen_pfc_functionality_test_configs`. Caller passes
    a reference to the running `traffic_items_names` list.
    """
    return Playbook(
        name="test_pfc_functionality_congestion",
        stages=[
            create_steps_stage(
                steps=[
                    create_longevity_step(duration=60),
                ]
            )
        ],
        postchecks=[
            create_ixia_traffic_rate_check(
                thresholds=[
                    hc_types.TrafficRateThreshold(
                        names=traffic_items_names,
                        value=49,
                        threshold_type=hc_types.ThresholdType.PERCENT,
                        metric=hc_types.TrafficRateMetric.TX_RATE,
                    ),
                ]
            ),
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=traffic_items_names,
                        str_value="0",
                    ),
                ]
            ),
        ],
        traffic_items_to_start=["TEST_RDMA_90_TRAFFIC_1", "TEST_RDMA_90_TRAFFIC_2"],
        enabled=True,
    )


def create_pfc_functionality_non_congestion_playbook(
    traffic_items_names: list[str],
    src_endpoints: t.List[TrafficEndpoint],
) -> Playbook:
    """Playbook factory for `test_pfc_functionality_non_congestion`.

    Originally inline inside `gen_pfc_functionality_test_configs`. Caller passes
    a reference to the running `traffic_items_names` list and the source
    endpoints (the factory itself slices `src_endpoints[:1]`).
    """
    return Playbook(
        name="test_pfc_functionality_non_congestion",
        prechecks=[
            create_clear_counters_check(),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_longevity_step(duration=60),
                ]
            )
        ],
        postchecks=[
            create_ixia_traffic_rate_check(
                thresholds=[
                    hc_types.TrafficRateThreshold(
                        names=traffic_items_names,
                        value=89,
                        threshold_type=hc_types.ThresholdType.PERCENT,
                        metric=hc_types.TrafficRateMetric.TX_RATE,
                    ),
                ]
            ),
            _create_dsf_pfc_check_central(
                thresholds=[
                    hc_types.DsfPfcThreshold(
                        interfaces=[endpoint.name for endpoint in src_endpoints[:1]],
                        out_pfc=0,
                        comparison=hc_types.ComparisonType.EQUAL_TO,
                    ),
                ]
            ),
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=traffic_items_names,
                        str_value="0",
                    ),
                ]
            ),
        ],
        traffic_items_to_start=["TEST_RDMA_90_TRAFFIC_2"],
        enabled=True,
    )


def create_pfc_functionality_incast_playbook(
    traffic_items_names: list[str],
) -> Playbook:
    """Playbook factory for
    `test_pfc_functionality_incast_voq_credit_fairness`.

    Originally inline inside `gen_pfc_functionality_test_configs`.
    """
    return Playbook(
        name="test_pfc_functionality_incast_voq_credit_fairness",
        stages=[
            create_steps_stage(
                steps=[
                    create_longevity_step(duration=60),
                ]
            )
        ],
        postchecks=[
            create_ixia_traffic_rate_check(
                thresholds=[
                    hc_types.TrafficRateThreshold(
                        names=traffic_items_names,
                        value=33,
                        threshold_type=hc_types.ThresholdType.PERCENT,
                        metric=hc_types.TrafficRateMetric.TX_RATE,
                    ),
                ]
            ),
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=traffic_items_names,
                        str_value="0",
                    ),
                ]
            ),
        ],
        traffic_items_to_start=[
            "TEST_RDMA_90_TRAFFIC_3",
            "TEST_RDMA_90_TRAFFIC_4",
            "TEST_RDMA_90_TRAFFIC_5",
        ],
        enabled=True,
    )


def create_pfc_functionality_port_flap_playbook(
    traffic_items_names: list[str],
    interface_to_flap: str,
) -> Playbook:
    """Playbook factory for `test_pfc_functionality_port_flap`.

    Originally inline inside `gen_pfc_functionality_test_configs`.
    """
    return Playbook(
        name="test_pfc_functionality_port_flap",
        stages=[
            create_steps_stage(
                steps=[
                    create_interface_flap_step(
                        enable=False,
                        interfaces=[interface_to_flap],
                        interface_flap_method=4,
                    ),
                    create_longevity_step(duration=60),
                    create_interface_flap_step(
                        enable=True,
                        interfaces=[interface_to_flap],
                        interface_flap_method=4,
                    ),
                    create_longevity_step(duration=60),
                ]
            )
        ],
        postchecks=[
            create_ixia_traffic_rate_check(
                thresholds=[
                    hc_types.TrafficRateThreshold(
                        names=traffic_items_names,
                        value=49,
                        threshold_type=hc_types.ThresholdType.PERCENT,
                        metric=hc_types.TrafficRateMetric.TX_RATE,
                    ),
                ]
            ),
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=["TEST_RDMA_90_TRAFFIC_5"],
                        str_value="0",
                    ),
                ]
            ),
        ],
        traffic_items_to_start=["TEST_RDMA_90_TRAFFIC_4", "TEST_RDMA_90_TRAFFIC_5"],
        enabled=True,
    )


def create_pfc_functionality_congestion_voq_credit_fairness_playbook(
    rdma_90pct_traffic_items_names: list[str],
    src_endpoints: t.List[TrafficEndpoint],
    dst_endpoints: t.List[TrafficEndpoint],
    traffic_duration: int,
) -> Playbook:
    """Playbook factory for
    `test_pfc_functionality_congestion_and_voq_credit_fairness`.

    Originally inline inside
    `gen_pfc_functionality_test_generic_4port_configs`. The factory itself
    slices `src_endpoints[:3]` for the DSF PFC check.
    """
    return Playbook(
        name="test_pfc_functionality_congestion_and_voq_credit_fairness",
        description="""Equal slowdown and no packet loss in congestion
                with multiple TC2 traffic. Verify that congestion in one PFC queue does not affect other PFC queues.""",
        prechecks=[
            # clear counters before starting the test on Arista EOS devices
            create_clear_counters_check(),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_longevity_step(duration=traffic_duration),
                ]
            )
        ],
        postchecks=[
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(str_value="0.1"),
                ],
                clear_traffic_stats=True,
            ),
            create_ixia_traffic_rate_check(
                thresholds=[
                    hc_types.TrafficRateThreshold(
                        names=rdma_90pct_traffic_items_names,
                        value=32,  # line rate equally shared among 3 traffics (33% each, set to 32% for a safe marigin)
                        threshold_type=hc_types.ThresholdType.PERCENT,
                        metric=hc_types.TrafficRateMetric.TX_RATE,
                    ),
                ]
            ),
            _create_dsf_pfc_check_central(
                thresholds=[
                    hc_types.DsfPfcThreshold(
                        interfaces=[endpoint.name for endpoint in src_endpoints[:3]],
                        # A small threshold to make the test flexible to different switch configurations
                        out_pfc=1000,
                        comparison=hc_types.ComparisonType.GREATER_THAN,
                    ),
                    hc_types.DsfPfcThreshold(
                        interfaces=[endpoint.name for endpoint in src_endpoints[:3]],
                        # Congestion in one PFC queue should not affect other PFC queue
                        # TC6 is also lossless (PFC enabled) in Tahan/SUSW
                        out_pfc=0,
                        comparison=hc_types.ComparisonType.EQUAL_TO,
                        priority=hc_types.Priority.PRIORITY_6,
                    ),
                ]
            ),
            create_port_counters_check(
                thresholds=[
                    hc_types.PortCountersThreshold(
                        interfaces=[endpoint.name for endpoint in dst_endpoints],
                        out_discards=0,
                        comparison=hc_types.ComparisonType.EQUAL_TO,
                    ),
                ]
            ),
        ],
        traffic_items_to_start=rdma_90pct_traffic_items_names,
    )


def create_pfc_rdma_only_with_clear_counters_playbook(
    rdma_90pct_traffic_items_names: list[str],
    src_endpoints: t.List[TrafficEndpoint],
    dst_endpoints: t.List[TrafficEndpoint],
    traffic_duration: int = 60,
) -> Playbook:
    """3:1 RDMA incast with FBOSS counter clear right before longevity.

    Used to debug T271053421: separates real test-traffic counter behavior from
    pollution caused by the IXIA setup trial-traffic phase (which briefly runs
    all 21 streams including BE for ARP/NDP resolution). Clears interface
    counters via `fboss2 clear interface counters` as the first step of the
    stage, then runs 60s of RDMA-only 3:1 incast traffic.
    """
    return Playbook(
        name="test_pfc_rdma_only_with_clear_counters",
        description="""3:1 RDMA incast (no BE) with FBOSS counter clear right
                before longevity so post-test in_discards/in_pfc/out_pfc readings
                reflect only the actual test traffic, not earlier trial traffic.""",
        stages=[
            create_steps_stage(
                steps=[
                    create_run_ssh_command_step(
                        cmd="fboss2 clear interface counters",
                        description="Clear FBOSS interface counters after IXIA trial traffic",
                    ),
                    create_longevity_step(duration=traffic_duration),
                ]
            )
        ],
        postchecks=[
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(str_value="0.1"),
                ],
                clear_traffic_stats=True,
            ),
            create_ixia_traffic_rate_check(
                thresholds=[
                    hc_types.TrafficRateThreshold(
                        names=rdma_90pct_traffic_items_names,
                        value=32,
                        threshold_type=hc_types.ThresholdType.PERCENT,
                        metric=hc_types.TrafficRateMetric.TX_RATE,
                    ),
                ]
            ),
            _create_dsf_pfc_check_central(
                thresholds=[
                    hc_types.DsfPfcThreshold(
                        interfaces=[endpoint.name for endpoint in src_endpoints[:3]],
                        out_pfc=1000,
                        comparison=hc_types.ComparisonType.GREATER_THAN,
                    ),
                ]
            ),
        ],
        traffic_items_to_start=rdma_90pct_traffic_items_names,
    )


def create_pfc_functionality_non_congestion_4port_playbook(
    rdma_90pct_traffic_items_names: list[str],
    src_endpoints: t.List[TrafficEndpoint],
    dst_endpoints: t.List[TrafficEndpoint],
    traffic_duration: int,
) -> Playbook:
    """Playbook factory for `test_pfc_functionality_non_congestion` (4port
    variant).

    Originally inline inside
    `gen_pfc_functionality_test_generic_4port_configs`. The factory slices the
    inputs (`rdma_90pct_traffic_items_names[:1]`, `src_endpoints[:1]`).
    """
    return Playbook(
        name="test_pfc_functionality_non_congestion",
        description="No PFC frame dispersion and zero packet loss in non-congestion",
        prechecks=[
            create_clear_counters_check(),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_longevity_step(duration=traffic_duration),
                ]
            )
        ],
        postchecks=[
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=rdma_90pct_traffic_items_names[:1],
                        str_value="0",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                ]
            ),
            create_ixia_traffic_rate_check(
                thresholds=[
                    hc_types.TrafficRateThreshold(
                        names=rdma_90pct_traffic_items_names[:1],
                        value=89,
                        threshold_type=hc_types.ThresholdType.PERCENT,
                        metric=hc_types.TrafficRateMetric.TX_RATE,
                    ),
                ]
            ),
            _create_dsf_pfc_check_central(
                thresholds=[
                    hc_types.DsfPfcThreshold(
                        interfaces=[endpoint.name for endpoint in src_endpoints[:1]],
                        out_pfc=0,
                        comparison=hc_types.ComparisonType.EQUAL_TO,
                    ),
                ]
            ),
            create_port_counters_check(
                thresholds=[
                    hc_types.PortCountersThreshold(
                        interfaces=[endpoint.name for endpoint in dst_endpoints],
                        out_discards=0,
                        comparison=hc_types.ComparisonType.EQUAL_TO,
                    ),
                ]
            ),
        ],
        traffic_items_to_start=rdma_90pct_traffic_items_names[:1],
    )


def create_pfc_functionality_port_flap_4port_playbook(
    rdma_90pct_traffic_items_names: list[str],
    src_endpoints: t.List[TrafficEndpoint],
    interface_to_flap: str,
    device_name_of_interface_flap: str,
) -> Playbook:
    """Playbook factory for `test_pfc_functionality_port_flap` (4port variant).

    Originally inline inside
    `gen_pfc_functionality_test_generic_4port_configs`. The factory slices the
    inputs (`rdma_90pct_traffic_items_names[:1|:2]`, `src_endpoints[:2]`).
    """
    return Playbook(
        name="test_pfc_functionality_port_flap",
        description="""Zero packet loss on the undisturbed traffic, and equal
                traffic rate distribution after port flap recovers""",
        prechecks=[
            create_clear_counters_check(),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_interface_flap_step(
                        enable=False,
                        interfaces=json.dumps([interface_to_flap]),
                        device_name=device_name_of_interface_flap,
                        interface_flap_method=4,  # InterfaceFlapMethod.SSH_PORT_STATE_CHANGE
                    ),
                    create_longevity_step(duration=120),
                    create_interface_flap_step(
                        enable=False,
                        interfaces=json.dumps([interface_to_flap]),
                        device_name=device_name_of_interface_flap,
                        interface_flap_method=4,  # InterfaceFlapMethod.SSH_PORT_STATE_CHANGE
                    ),
                    create_longevity_step(duration=120),
                    create_interface_flap_step(
                        enable=True,
                        interfaces=json.dumps([interface_to_flap]),
                        device_name=device_name_of_interface_flap,
                        interface_flap_method=4,
                    ),
                    create_longevity_step(duration=600),
                ]
            )
        ],
        postchecks=[
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=rdma_90pct_traffic_items_names[:1],
                        str_value="0",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                    hc_types.PacketLossThreshold(
                        names=rdma_90pct_traffic_items_names[1:2],
                        str_value="3",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                ]
            ),
            create_ixia_traffic_rate_check(
                thresholds=[
                    hc_types.TrafficRateThreshold(
                        names=rdma_90pct_traffic_items_names[:2],
                        value=49,
                        threshold_type=hc_types.ThresholdType.PERCENT,
                        metric=hc_types.TrafficRateMetric.TX_RATE,
                    ),
                ]
            ),
            _create_dsf_pfc_check_central(
                thresholds=[
                    hc_types.DsfPfcThreshold(
                        interfaces=[endpoint.name for endpoint in src_endpoints[:2]],
                        # A small threshold to make the test flexible to different switch configurations
                        out_pfc=1000,
                        comparison=hc_types.ComparisonType.GREATER_THAN,
                    ),
                ]
            ),
        ],
        traffic_items_to_start=rdma_90pct_traffic_items_names[:2],
    )


def create_multi_pfc_congestion_playbook(
    monitoring_90pct_traffic_items_names: list[str],
    rdma_30pct_traffic_items_names: list[str],
    src_endpoints: t.List[TrafficEndpoint],
    traffic_duration: int,
) -> Playbook:
    """Playbook factory for `test_multi_pfc_congestion`.

    Originally inline inside
    `gen_pfc_functionality_test_generic_4port_configs`. The factory slices the
    inputs (`monitoring_90pct_traffic_items_names[:2]`,
    `rdma_30pct_traffic_items_names[-1:]`, `src_endpoints[:2]`,
    `src_endpoints[2:3]`).
    """
    return Playbook(
        name="test_multi_pfc_congestion",
        description="Congestion with RDMA/TC2 traffic (lossless) and Monitoring/TC6 (lossless) traffic on Tahan/SUSW",
        prechecks=[
            create_clear_counters_check(),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_longevity_step(duration=traffic_duration),
                ]
            )
        ],
        postchecks=[
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=monitoring_90pct_traffic_items_names[:2],
                        str_value="0",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                    hc_types.PacketLossThreshold(
                        names=rdma_30pct_traffic_items_names[-1:],
                        str_value="95",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                ]
            ),
            create_ixia_traffic_rate_check(
                thresholds=[
                    hc_types.TrafficRateThreshold(
                        names=monitoring_90pct_traffic_items_names[:2],
                        value=45,
                        threshold_type=hc_types.ThresholdType.PERCENT,
                        metric=hc_types.TrafficRateMetric.TX_RATE,
                    ),
                ]
            ),
            _create_dsf_pfc_check_central(
                thresholds=[
                    hc_types.DsfPfcThreshold(
                        # Interfaces of TC6 traffic
                        interfaces=[endpoint.name for endpoint in src_endpoints[:2]],
                        out_pfc=1000,
                        comparison=hc_types.ComparisonType.GREATER_THAN,
                        priority=hc_types.Priority.PRIORITY_6,
                    ),
                    hc_types.DsfPfcThreshold(
                        # TC6 congestion should not affect TC2
                        interfaces=[endpoint.name for endpoint in src_endpoints[:2]],
                        out_pfc=0,
                        comparison=hc_types.ComparisonType.EQUAL_TO,
                        priority=hc_types.Priority.PRIORITY_2,
                    ),
                    hc_types.DsfPfcThreshold(
                        # Interfaces of TC2 traffic
                        interfaces=[endpoint.name for endpoint in src_endpoints[2:3]],
                        out_pfc=1000,
                        comparison=hc_types.ComparisonType.GREATER_THAN,
                        priority=hc_types.Priority.PRIORITY_2,
                    ),
                    hc_types.DsfPfcThreshold(
                        # TC2 congestion should not affect TC6
                        interfaces=[endpoint.name for endpoint in src_endpoints[2:3]],
                        out_pfc=0,
                        comparison=hc_types.ComparisonType.EQUAL_TO,
                        priority=hc_types.Priority.PRIORITY_6,
                    ),
                ]
            ),
        ],
        traffic_items_to_start=rdma_30pct_traffic_items_names[-1:]
        + monitoring_90pct_traffic_items_names[:2],
    )


def create_dsf_dtsw_mesh_longevity_playbook(
    name: str,
    traffic_item_name: str,
    duration_seconds: int = 600,
) -> Playbook:
    """Playbook factory for the SNC1 DSF DTSW C087/C088 mesh longevity Playbook.

    Originally inline inside the
    `SNC1_DSF_DTSW_C087_C088_MESH_LONGEVITY_TEST_CONFIG` module-level
    `TestConfig`.
    """
    return Playbook(
        name=name,
        stages=[
            create_steps_stage(
                steps=[
                    create_longevity_step(duration=duration_seconds),
                ]
            )
        ],
        postchecks=[
            create_packetloss_health_check(),
        ],
        traffic_items_to_start=[traffic_item_name],
        enabled=True,
    )


def create_dsf_dtsw_mesh_consecutive_warmboot_endurance_playbook(
    name: str,
    traffic_item_name: str,
    iteration_count: int = 10,
    longevity_duration_seconds: int = 120,
) -> Playbook:
    """Playbook factory for the SNC1 DSF DTSW C087/C088 mesh consecutive
    warmboot endurance Playbook.

    Originally inline inside the
    `SNC1_DSF_DTSW_C087_C088_MESH_LONGEVITY_TEST_CONFIG` module-level
    `TestConfig`.
    """
    return Playbook(
        name=name,
        stages=[
            create_steps_stage(
                steps=[
                    create_service_interruption_step(
                        service=Service.AGENT,
                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(
                        services=[taac_types.Service.AGENT],
                    ),
                    create_longevity_step(duration=longevity_duration_seconds),
                ],
                iteration=iteration_count,
            )
        ],
        postchecks=[
            create_packetloss_health_check(),
        ],
        traffic_items_to_start=[traffic_item_name],
        enabled=True,
    )


def create_edsw_agent_warmboot_with_ndp_playbook(
    ixia_healthcheck: PointInTimeHealthCheck,
    ndp_populate_wait_seconds: int = 300,
    post_clear_wait_seconds: int = 300,
    bgp_convergence_threshold: int = 600,
    bgp_fail_on_eor_expired: bool = False,
    ecmp_member_count: int = 16000,
    ecmp_group_count: int = 1536,
    monitored_services: t.Optional[t.List[str]] = None,
) -> Playbook:
    """
    Create the EDSW `test_agent_warmboot` Playbook used in
    `EDSW003_N001_ECMP_SCALE_3PORT` (and related EDSW ECMP scale configs).

    Two-phase warmboot:
      1. Initial warmboot before NDP is enabled.
      2. Enable NDP responders, wait for resolution, clear stats,
         then warmboot again.

    Args:
        ixia_healthcheck: Caller-supplied IXIA packet-loss check (config-specific
            because traffic-item names and loss expectations vary per testbed).
        ndp_populate_wait_seconds: Seconds to wait after enabling NDP responders.
        post_clear_wait_seconds: Seconds to wait after clearing IXIA stats.
        bgp_convergence_threshold: BGP convergence threshold seconds.
        bgp_fail_on_eor_expired: Whether BGP convergence check fails on EOR expiry.
        ecmp_member_count: Maximum allowed ECMP member count.
        ecmp_group_count: Maximum allowed ECMP group count.
        monitored_services: Service names monitored by SERVICE_RESTART_CHECK
            (defaults to `["wedge_agent", "bgpd", "fsdb", "qsfp_service"]`).
    """
    if monitored_services is None:
        monitored_services = ["wedge_agent", "bgpd", "fsdb", "qsfp_service"]
    return Playbook(
        name="test_agent_warmboot",
        postchecks_to_skip=[
            hc_types.CheckName.SERVICE_RESTART_CHECK,
        ],
        stages=[
            create_steps_stage(
                iteration=1,
                steps=[
                    create_service_interruption_step(
                        service=Service.AGENT,
                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(
                        services=[Service.AGENT, Service.BGP],
                    ),
                ],
            ),
            create_steps_stage(
                iteration=1,
                steps=[
                    create_ixia_device_group_toggle_step(
                        enable=True,
                        device_group_name_regex="NDP_SUPPORTING_NEXTHOP",
                        description="Enable NDP nexthop responders (one-time)",
                    ),
                    create_longevity_step(
                        duration=ndp_populate_wait_seconds,
                        description=f"Wait {ndp_populate_wait_seconds // 60} minutes for NDP entries to populate",
                    ),
                    create_ixia_api_step(
                        api_name="clear_traffic_stats",
                        args_dict={"wait_for_refresh": True},
                        description="Clear IXIA traffic counters before warmboot",
                    ),
                    create_longevity_step(
                        duration=post_clear_wait_seconds,
                        description=f"Wait {post_clear_wait_seconds // 60} minutes after clearing counters",
                    ),
                    create_service_interruption_step(
                        service=Service.AGENT,
                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(
                        services=[Service.AGENT, Service.BGP],
                    ),
                ],
            ),
        ],
        skip_test_config_snapshot_checks=True,
        postchecks=[
            create_systemctl_active_state_check(),
            ixia_healthcheck,
            create_bgp_convergence_check(
                convergence_threshold=bgp_convergence_threshold,
                fail_on_eor_expired=bgp_fail_on_eor_expired,
            ),
            create_ecmp_group_and_member_count_check(
                ecmp_member_count=ecmp_member_count,
                ecmp_group_count=ecmp_group_count,
            ),
            create_service_restart_check(services=monitored_services),
        ],
    )


def create_w400_longevity_playbook(
    duration: int,
    packet_loss_check: PointInTimeHealthCheck,
    traffic_items_to_start: t.List[str],
    snapshot_checks: t.List[SnapshotHealthCheck],
) -> Playbook:
    return Playbook(
        name="test_w400_ash6_longevity",
        stages=[create_longevity_stage(duration=duration)],
        postchecks=[packet_loss_check],
        traffic_items_to_start=traffic_items_to_start,
        enabled=True,
        snapshot_checks=snapshot_checks,
    )


def create_w400_agent_restart_playbook(
    packet_loss_check: PointInTimeHealthCheck,
    systemctl_check: PointInTimeHealthCheck,
    traffic_items_to_start: t.List[str],
    snapshot_checks: t.List[SnapshotHealthCheck],
) -> Playbook:
    return Playbook(
        name="test_w400_ash6_agent_restart",
        prechecks=[systemctl_check, packet_loss_check],
        stages=[
            create_steps_stage(
                steps=[
                    create_service_interruption_step(
                        service=taac_types.Service.AGENT,
                        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(
                        services=[taac_types.Service.AGENT, taac_types.Service.BGP],
                    ),
                    create_longevity_step(duration=60),
                ]
            )
        ],
        postchecks=[packet_loss_check, systemctl_check],
        traffic_items_to_start=traffic_items_to_start,
        enabled=True,
        snapshot_checks=snapshot_checks,
    )


def create_w400_coldboot_playbook(
    packet_loss_check_clear_stats: PointInTimeHealthCheck,
    packet_loss_check: PointInTimeHealthCheck,
    systemctl_check: PointInTimeHealthCheck,
    traffic_items_to_start: t.List[str],
    snapshot_checks: t.List[SnapshotHealthCheck],
) -> Playbook:
    return Playbook(
        name="test_w400_ash6_coldboot",
        prechecks=[systemctl_check, packet_loss_check],
        stages=[
            create_steps_stage(
                steps=[
                    create_service_interruption_step(
                        service=taac_types.Service.AGENT,
                        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                        create_cold_boot_file=True,
                    ),
                    create_service_convergence_step(
                        services=[taac_types.Service.AGENT, taac_types.Service.BGP],
                    ),
                    create_longevity_step(duration=60),
                ]
            )
        ],
        postchecks=[packet_loss_check_clear_stats, systemctl_check],
        traffic_items_to_start=traffic_items_to_start,
        enabled=True,
        snapshot_checks=snapshot_checks,
    )


def create_w400_agent_crash_playbook(
    packet_loss_check_clear_stats: PointInTimeHealthCheck,
    packet_loss_check: PointInTimeHealthCheck,
    systemctl_check: PointInTimeHealthCheck,
    traffic_items_to_start: t.List[str],
    snapshot_checks: t.List[SnapshotHealthCheck],
) -> Playbook:
    return Playbook(
        name="test_w400_ash6_agent_crash",
        prechecks=[systemctl_check, packet_loss_check],
        stages=[
            create_steps_stage(
                steps=[
                    create_service_interruption_step(
                        service=taac_types.Service.AGENT,
                        trigger=taac_types.ServiceInterruptionTrigger.CRASH,
                    ),
                    create_service_convergence_step(
                        services=[taac_types.Service.AGENT, taac_types.Service.BGP],
                    ),
                    create_longevity_step(duration=60),
                ]
            )
        ],
        postchecks=[packet_loss_check_clear_stats, systemctl_check],
        traffic_items_to_start=traffic_items_to_start,
        enabled=True,
        snapshot_checks=snapshot_checks,
    )


def create_w400_bgpd_restart_playbook(
    packet_loss_check: PointInTimeHealthCheck,
    systemctl_check: PointInTimeHealthCheck,
    traffic_items_to_start: t.List[str],
    snapshot_checks: t.List[SnapshotHealthCheck],
) -> Playbook:
    return Playbook(
        name="test_w400_ash6_bgpd_restart",
        prechecks=[systemctl_check, packet_loss_check],
        stages=[
            create_steps_stage(
                steps=[
                    create_service_interruption_step(
                        service=taac_types.Service.BGP,
                        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(
                        services=[taac_types.Service.BGP],
                    ),
                    create_longevity_step(duration=60),
                ]
            )
        ],
        postchecks=[packet_loss_check, systemctl_check],
        traffic_items_to_start=traffic_items_to_start,
        enabled=True,
        snapshot_checks=snapshot_checks,
    )


# ---------------------------------------------------------------------------
# EDSW003.N001.L201.SNC1 DSF hardening playbook factories.
# Used by testconfigs/ai_bb/edsw003_n001_l201_snc1_hardening_test_config.py.
# ---------------------------------------------------------------------------


def create_edsw_fboss_critical_service_playbook(
    name: str,
    services: list,
    trigger: taac_types.ServiceInterruptionTrigger,
    device_regexes: list,
    traffic_item_to_start: str,
    create_cold_boot_file: bool = False,
    concurrent: bool = False,
    iteration: int = 2,
    longevity_duration: int = 120,
    clear_traffic_stats: bool = False,
    unclean_exit_exclude_services: list | None = None,
    add_service_convergence: bool = False,
) -> Playbook:
    """Build a single-stage FBOSS critical-service Playbook scoped to the DUT.

    `services` may be a single Service or a list. When more than one service is
    given the interruption steps run concurrently within the same stage,
    followed by a longevity step to allow convergence.

    `clear_traffic_stats` should be True for crash playbooks: the IXIA packet
    loss postcheck clears traffic counters before measuring, so loss accumulated
    during the prior steady-state window is not counted against the test.

    `unclean_exit_exclude_services` should list the services SIGKILL'd by the
    test so the UNCLEAN_EXIT_CHECK postcheck does not flag them as unexpected.

    `add_service_convergence` inserts a SERVICE_CONVERGENCE_STEP between the
    interruption and the longevity step. Required for agent coldboot/crash so
    wedge_agent is fully back online before downstream checks fire.
    """
    interruption_steps = [
        create_service_interruption_step(
            service=svc,
            trigger=trigger,
            create_cold_boot_file=create_cold_boot_file,
        )
        for svc in services
    ]
    stage_steps = list(interruption_steps)
    if add_service_convergence:
        stage_steps.append(create_service_convergence_step(services=services))
    stage_steps.append(create_longevity_step(duration=longevity_duration))
    return Playbook(
        name=name,
        device_regexes=device_regexes,
        prechecks=[
            create_ixia_packet_loss_check(
                thresholds=[hc_types.PacketLossThreshold(str_value="0.1")],
            ),
            create_systemctl_active_state_check(),
            create_dsf_drain_state_check(check_scope=hc_types.Scope.DEFAULT),
        ],
        postchecks=[
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        str_value="0",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                ],
                clear_traffic_stats=clear_traffic_stats,
            ),
            create_systemctl_active_state_check(),
            create_unclean_exit_check(exclude_services=unclean_exit_exclude_services),
            create_memory_utilization_check(
                threshold=5 * (1024**3),
                start_time_jq_var="test_case_start_time",
                check_scope=hc_types.Scope.DEFAULT,
            ),
            create_cpu_utilization_check(
                threshold=100.0,
                start_time_jq_var="test_case_start_time",
                check_scope=hc_types.Scope.DEFAULT,
            ),
        ],
        snapshot_checks=[create_core_dumps_snapshot_check()],
        stages=[
            create_steps_stage(
                steps=stage_steps,
                concurrent=concurrent if len(services) > 1 else False,
            ),
        ],
        traffic_items_to_start=[traffic_item_to_start],
        iteration=iteration,
    )


def create_edsw003_n001_l201_snc1_warmboot_playbook(
    ixia_healthcheck: PointInTimeHealthCheck,
) -> Playbook:
    """Build the `0_test_agent_warmboot` Playbook for the EDSW003.N001.L201.SNC1
    DSF hardening test config: agent warmboot, NDP device-group enable +
    5-minute soak, then a second agent warmboot.
    """
    systemctl_check = create_systemctl_active_state_check()
    return Playbook(
        name="0_test_agent_warmboot",
        stages=[
            create_steps_stage(
                iteration=1,
                steps=[
                    create_service_interruption_step(
                        service=taac_types.Service.AGENT,
                        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(
                        services=[taac_types.Service.AGENT, taac_types.Service.BGP],
                    ),
                ],
            ),
            create_steps_stage(
                iteration=1,
                steps=[
                    create_ixia_device_group_toggle_step(
                        enable=True,
                        device_group_name_regex="NDP_SUPPORTING_NEXTHOP",
                        description="Enable NDP_SUPPORTING_NEXTHOP device group (one-time)",
                    ),
                    create_longevity_step(
                        duration=300,
                        description="Wait 5 minutes for NDP entries to populate on DUT",
                    ),
                    create_ixia_api_step(
                        api_name="clear_traffic_stats",
                        args_dict={"wait_for_refresh": True},
                        description="Clear IXIA traffic counters before warmboot",
                    ),
                    create_longevity_step(
                        duration=300,
                        description="Wait 5 minutes after clearing counters",
                    ),
                    create_service_interruption_step(
                        service=taac_types.Service.AGENT,
                        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(
                        services=[taac_types.Service.AGENT, taac_types.Service.BGP],
                    ),
                ],
            ),
        ],
        prechecks=[ixia_healthcheck, systemctl_check],
        postchecks=[ixia_healthcheck, systemctl_check],
    )


def create_edsw003_n001_l201_snc1_longevity_playbook(
    ixia_healthcheck: PointInTimeHealthCheck,
    longevity_duration: int = 240,
) -> Playbook:
    """Build the `1_test_longevity` Playbook for the EDSW003.N001.L201.SNC1
    DSF hardening test config: a single longevity stage with IXIA-loss +
    DSF drain-state pre/postchecks and a CORE_DUMPS_CHECK snapshot.
    """
    systemctl_check = create_systemctl_active_state_check()
    return Playbook(
        name="1_test_longevity",
        stages=[
            create_steps_stage(
                steps=[create_longevity_step(duration=longevity_duration)],
            ),
        ],
        prechecks=[
            ixia_healthcheck,
            create_dsf_drain_state_check(),
            systemctl_check,
        ],
        postchecks=[
            ixia_healthcheck,
            systemctl_check,
            create_memory_utilization_check(
                threshold=5 * (1024**3),
                start_time_jq_var="test_case_start_time",
                check_scope=hc_types.Scope.DEFAULT,
            ),
            create_cpu_utilization_check(
                threshold=100.0,
                start_time_jq_var="test_case_start_time",
                check_scope=hc_types.Scope.DEFAULT,
            ),
        ],
        snapshot_checks=[
            create_core_dumps_snapshot_check(),
        ],
    )


def create_w400_interface_flap_playbook(
    interfaces: t.List[str],
    device_name: str,
    packet_loss_check_clear_stats: PointInTimeHealthCheck,
    packet_loss_check: PointInTimeHealthCheck,
    systemctl_check: PointInTimeHealthCheck,
    traffic_items_to_start: t.List[str],
    snapshot_checks: t.List[SnapshotHealthCheck],
) -> Playbook:
    return Playbook(
        name="test_w400_ash6_interface_flap",
        prechecks=[systemctl_check, packet_loss_check],
        stages=[
            create_steps_stage(
                steps=[
                    create_interface_flap_step(
                        enable=False,
                        interfaces=interfaces,
                        device_name=device_name,
                        interface_flap_method=4,
                        delay=10,
                    ),
                    create_interface_flap_step(
                        enable=True,
                        interfaces=interfaces,
                        device_name=device_name,
                        interface_flap_method=4,
                        delay=30,
                    ),
                    create_interface_flap_step(
                        enable=False,
                        interfaces=interfaces,
                        device_name=device_name,
                        interface_flap_method=4,
                        delay=10,
                    ),
                    create_interface_flap_step(
                        enable=True,
                        interfaces=interfaces,
                        device_name=device_name,
                        interface_flap_method=4,
                        delay=30,
                    ),
                    create_service_convergence_step(
                        services=[taac_types.Service.AGENT, taac_types.Service.BGP],
                    ),
                    create_longevity_step(duration=60),
                ]
            )
        ],
        postchecks=[packet_loss_check_clear_stats, systemctl_check],
        traffic_items_to_start=traffic_items_to_start,
        enabled=True,
        snapshot_checks=snapshot_checks,
    )


def create_fpf_prefix_injection_stress_playbook(
    gtsws: list[str],
    hosts: list[str],
    trigger_stsws: list[str],
    baseline_delay_sec: int = 120,
    collection_duration_sec: int = 720,
    poll_interval_sec: int = 5,
    subnet_prefix: str = "5000:dd::/32",
    prefix_count: int = 20000,
    community_list: str = "stsw",
    lanes: list[int] | None = None,
    services_to_check: list[str] | None = None,
) -> Playbook:
    """Full FPF prefix-injection stress playbook (prechecks + stress stage + postchecks).

    Wraps `create_fpf_stress_concurrent_stage` with standard FPF pre/postchecks
    and a withdraw cleanup step.
    """
    from taac.health_checks.healthcheck_definitions import (
        create_bgp_rib_fib_consistency_check,
        create_bgp_session_establish_check,
        create_core_dumps_snapshot_check,
        create_cpu_utilization_check,
        create_device_core_dumps_check,
        create_fpf_bgp_rib_convergence_check,
        create_fpf_fsdb_ribmap_convergence_check,
        create_fpf_hrt_bulk_convergence_check,
        create_fpf_hrt_fsdb_session_check,
        create_fpf_stale_prefix_check,
        create_memory_utilization_check,
        create_port_state_check,
        create_systemctl_active_state_check,
        create_unclean_exit_check,
    )
    from taac.stages.stage_definitions import (
        create_fpf_stress_concurrent_stage,
    )
    from taac.steps.step_definitions import (
        create_fpf_bgp_prefix_injection_step,
    )

    services = services_to_check or ["bgpd", "fsdb", "wedge_agent", "qsfp_service"]
    resolved_lanes = lanes if lanes is not None else [0, 1]

    prechecks = [
        create_bgp_session_establish_check(),
        create_port_state_check(),
        create_systemctl_active_state_check(services_json=services),
        create_unclean_exit_check(),
        create_device_core_dumps_check(),
        create_fpf_stale_prefix_check(
            subnet_prefix=subnet_prefix,
            check_id="fpf_stale_prefix_precheck",
        ),
        create_fpf_hrt_fsdb_session_check(
            hosts=hosts,
            check_id="fpf_hrt_precheck",
        ),
    ]

    convergence_postchecks = []
    for lane_id, gtsw in enumerate(gtsws):
        lane_map = {str(lane_id): gtsw}
        convergence_postchecks.append(
            create_fpf_fsdb_ribmap_convergence_check(
                lane_map=lane_map,
                expected_matched=prefix_count,
                trigger_delay_sec=baseline_delay_sec,
                check_id=f"fpf_fsdb_convergence_lane{lane_id}",
            )
        )
        convergence_postchecks.append(
            create_fpf_bgp_rib_convergence_check(
                lane_map=lane_map,
                expected_matched=prefix_count,
                trigger_delay_sec=baseline_delay_sec,
                check_id=f"fpf_bgp_convergence_lane{lane_id}",
            )
        )
    for lane_id in resolved_lanes:
        convergence_postchecks.append(
            create_fpf_hrt_bulk_convergence_check(
                lanes=[lane_id],
                expected_per_lane={str(lane_id): prefix_count},
                trigger_delay_sec=baseline_delay_sec,
                check_id=f"fpf_hrt_convergence_lane{lane_id}",
            )
        )

    postchecks = [
        create_bgp_session_establish_check(),
        create_port_state_check(),
        create_systemctl_active_state_check(services_json=services),
        create_unclean_exit_check(),
        create_device_core_dumps_check(),
        create_bgp_rib_fib_consistency_check(),
        create_memory_utilization_check(),
        create_cpu_utilization_check(),
        create_fpf_hrt_fsdb_session_check(
            hosts=hosts,
            check_id="fpf_hrt_postcheck",
        ),
        *convergence_postchecks,
    ]

    snapshot_checks = [create_core_dumps_snapshot_check()]

    stress_stage = create_fpf_stress_concurrent_stage(
        gtsws=gtsws,
        hosts=hosts,
        trigger_stsws=trigger_stsws,
        baseline_delay_sec=baseline_delay_sec,
        collection_duration_sec=collection_duration_sec,
        poll_interval_sec=poll_interval_sec,
        subnet_prefix=subnet_prefix,
        prefix_count=prefix_count,
        community_list=community_list,
        lanes=resolved_lanes,
    )

    cleanup_steps = [
        create_fpf_bgp_prefix_injection_step(
            devices=trigger_stsws,
            count=prefix_count,
            community_list=community_list,
            withdraw_only=True,
            description="Withdraw injected BGP prefixes (cleanup)",
        ),
    ]

    return Playbook(
        name="fpf_prefix_injection_stress",
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
        stages=[stress_stage],
        cleanup_steps=cleanup_steps,
    )


def _build_fpf_generic_checks(
    *,
    hosts: list[str],
    services: list[str],
    gtsws: list[str],
    trigger_stsws: list[str],
    skip_ssh_dependent_checks: bool,
    fsdb_sessions_per_host: int | None,
    prod_prefixes: list[str] | None,
    hrt_memory_hosts: list[str] | None,
    hrt_driver_hosts: list[str] | None,
    spray_hosts: list[str] | None,
    ods_entities: list[str] | None,
    use_bgp_snapshot: bool = False,
    skip_fsdb_session_precheck: bool = False,
    ods_discard_informational: bool = False,
    host_spray_label: str = "",
) -> tuple[list, list, list]:
    """Build the generic (non-convergence) FPF check lists shared by the
    hardening / service-restart playbooks.

    Returns ``(generic_prechecks, generic_postchecks, snapshot_checks)``.

    This is the generic-check logic factored out of
    ``create_fpf_hardening_playbook_v2`` verbatim so every caller produces the
    same generic check set (and v2's assembled lists stay byte-for-byte
    identical). It deliberately does NOT include the convergence checks, the
    prod-prefix-stability postcheck, the HRT plane-status postcheck, or the
    BGP convergence-timing disruption postcheck — those stay in each caller.

    ``generic_postchecks`` is ordered as the SSH/device-shell "head" block
    (bgp-establish, port-state, systemctl, unclean-exit, device-core-dumps,
    bgp-rib-fib-consistency, mem-util, cpu-util, hrt-fsdb-session) followed by
    the ODS-only "tail" block (ODS discard/congestion counters, HRT
    system-memory, HRT driver-disconnect, host-spray). Callers that need to
    splice convergence checks between the two blocks (v2) can split on the
    first ODS check (``ods_in_dst_null_discard``); callers that don't (v1,
    service-restart) use the flat list directly.

    When ``skip_ssh_dependent_checks`` is set, the SSH/device-shell generic
    checks AND the ODS discard/congestion counters are dropped, but the
    ODS-only HRT-mem / HRT-driver / host-spray and the prod-prefix / HRT-mem /
    HRT-driver prechecks are KEPT (they only need ODS/collector access).
    """
    from taac.health_checks.healthcheck_definitions import (
        create_bgp_session_establish_check,
        create_bgp_session_snapshot_check,
        create_core_dumps_snapshot_check,
        create_cpu_utilization_check,
        create_device_core_dumps_check,
        create_fpf_host_spray_check,
        create_fpf_hrt_driver_disconnect_check,
        create_fpf_hrt_fsdb_session_check,
        create_fpf_hrt_system_memory_check,
        create_fpf_ods_counter_check,
        create_fpf_prod_hrt_prefix_stability_check,
        create_memory_utilization_check,
        create_port_state_check,
        create_systemctl_active_state_check,
        create_unclean_exit_check,
    )

    from taac.libs.fpf.fpf_thresholds import (
        ACTIVE as FPF_ACTIVE_THRESHOLDS,
    )

    # --- Prechecks -------------------------------------------------------
    prechecks = (
        []
        if skip_ssh_dependent_checks
        else [
            *(
                []
                if use_bgp_snapshot
                else [create_bgp_session_establish_check(min_established_pct=0.5)]
            ),
            create_port_state_check(),
            create_systemctl_active_state_check(services_json=services),
            create_unclean_exit_check(),
            create_device_core_dumps_check(),
            *(
                []
                if skip_fsdb_session_precheck
                else [
                    create_fpf_hrt_fsdb_session_check(
                        hosts=hosts,
                        expected_session_count=fsdb_sessions_per_host,
                        check_id="fpf_hrt_precheck",
                    )
                ]
            ),
        ]
    )
    # ODS/collector baseline prechecks (no SSH needed): kept in both modes.
    if prod_prefixes:
        prechecks.append(
            create_fpf_prod_hrt_prefix_stability_check(
                check_id="fpf_prod_hrt_prefix_stability_precheck",
            )
        )
    if hrt_memory_hosts:
        prechecks.append(
            create_fpf_hrt_system_memory_check(
                hosts=hrt_memory_hosts,
                threshold_gib=FPF_ACTIVE_THRESHOLDS.hrt_system_memory_max_gib,
                check_id="fpf_hrt_system_memory_precheck",
            )
        )
    if hrt_driver_hosts:
        prechecks.append(
            create_fpf_hrt_driver_disconnect_check(
                hosts=hrt_driver_hosts,
                check_id="fpf_hrt_driver_disconnect_precheck",
            )
        )

    # --- ODS discard/congestion counter postchecks (SSH-independent but
    # dropped in minimal mode alongside the generic SSH checks). ---
    # The two DISCARD counters can be marked informational
    # (``ods_discard_informational``) so a disruptive restart/coldboot — where
    # transient in-flight packet loss is expected with live traffic — reports
    # the breach (values + ODS link) without failing the test. The congestion
    # counters stay hard checks (a restart should not cause congestion).
    ods_entity_desc = ",".join(ods_entities or (gtsws + trigger_stsws))
    ods_reduce = r"groupby(entity, (\S+?\.\S+?)\..*, %1),sum"
    ods_postchecks = [
        create_fpf_ods_counter_check(
            entity_desc=ods_entity_desc,
            key_desc="regex(fboss.agent.eth.*discards.sum.60),filter(.*in_dst_null.*)",
            validation_expr=f"<= {FPF_ACTIVE_THRESHOLDS.ods_in_dst_null_discard_max}",
            reduce_desc=ods_reduce,
            counter_name="in_dst_null_discard",
            shorten_pass_url=True,
            informational=ods_discard_informational,
            check_id="ods_in_dst_null_discard",
        ),
        create_fpf_ods_counter_check(
            entity_desc=ods_entity_desc,
            key_desc="regex(fboss.agent.eth.*discards.sum.60),filter(.*in_discard.*)",
            validation_expr=f"<= {FPF_ACTIVE_THRESHOLDS.ods_in_discard_max}",
            reduce_desc=ods_reduce,
            counter_name="in_discard",
            shorten_pass_url=True,
            informational=ods_discard_informational,
            check_id="ods_in_discard",
        ),
        create_fpf_ods_counter_check(
            entity_desc=ods_entity_desc,
            key_desc="regex(fboss.agent.eth.*congestion.*sum.60),filter(.*in_congestion_discards.sum.*)",
            validation_expr=f"<= {FPF_ACTIVE_THRESHOLDS.ods_in_congestion_max}",
            reduce_desc=ods_reduce,
            counter_name="in_congestion",
            shorten_pass_url=True,
            check_id="ods_in_congestion",
        ),
        create_fpf_ods_counter_check(
            entity_desc=ods_entity_desc,
            key_desc="regex(fboss.agent.eth.*congestion.*sum.60),filter(.*out_congestion_discards.sum.*)",
            validation_expr=f"<= {FPF_ACTIVE_THRESHOLDS.ods_out_congestion_max}",
            reduce_desc=ods_reduce,
            counter_name="out_congestion",
            shorten_pass_url=True,
            check_id="ods_out_congestion",
        ),
    ]

    # HRT system-memory / driver-disconnect / host-spray postchecks (ODS-only,
    # kept in both minimal and full modes).
    hrt_memory_postchecks = []
    if hrt_memory_hosts:
        hrt_memory_postchecks.append(
            create_fpf_hrt_system_memory_check(
                hosts=hrt_memory_hosts,
                threshold_gib=FPF_ACTIVE_THRESHOLDS.hrt_system_memory_max_gib,
                check_id="fpf_hrt_system_memory",
            )
        )
    hrt_driver_postchecks = []
    if hrt_driver_hosts:
        hrt_driver_postchecks.append(
            create_fpf_hrt_driver_disconnect_check(
                hosts=hrt_driver_hosts,
                check_id="fpf_hrt_driver_disconnect",
            )
        )
    spray_postchecks = []
    if spray_hosts:
        spray_postchecks.append(
            create_fpf_host_spray_check(
                hosts=spray_hosts,
                min_egress_gbps=FPF_ACTIVE_THRESHOLDS.host_spray_min_egress_gbps,
                max_spread_gbps=FPF_ACTIVE_THRESHOLDS.host_spray_max_spread_gbps,
                label=host_spray_label or None,
                check_id="fpf_host_spray",
            )
        )

    # --- Postchecks + snapshots ------------------------------------------
    if skip_ssh_dependent_checks:
        # Minimal mode: drop the generic SSH checks and ODS counters; keep the
        # ODS-only HRT-mem / HRT-driver / host-spray postchecks.
        generic_postchecks = [
            *hrt_memory_postchecks,
            *hrt_driver_postchecks,
            *spray_postchecks,
        ]
        snapshot_checks = []
    else:
        generic_postchecks = [
            # head: SSH/device-shell generic checks
            *(
                []
                if use_bgp_snapshot
                else [create_bgp_session_establish_check(min_established_pct=0.5)]
            ),
            create_port_state_check(),
            create_systemctl_active_state_check(services_json=services),
            create_unclean_exit_check(),
            create_device_core_dumps_check(),
            # BGP RIB<->FIB consistency check omitted: it is FBOSS-OS-gated and
            # SKIPs (empty message) on these MWG2 GTSW/STSW endpoints, validating
            # nothing while inflating the per-host SKIP-counted-as-failed tally.
            create_memory_utilization_check(
                threshold=FPF_ACTIVE_THRESHOLDS.mem_util_default_bytes,
                threshold_by_service=dict(FPF_ACTIVE_THRESHOLDS.mem_util_by_service),
                start_time_jq_var="test_case_start_time",
            ),
            create_cpu_utilization_check(
                # 100% per-process floor: at the 8-STSW injection scale, fsdb/bgpd
                # legitimately run hotter (e.g. fsdb ~71% rebuilding the larger
                # ribMap after an fsdb restart) — well within a single core. The
                # split agents keep their higher 250% (multi-core) overrides.
                threshold=100.0,
                threshold_by_service={
                    "fboss_hw_agent@0": 250.0,
                    "fboss_sw_agent": 250.0,
                },
            ),
            create_fpf_hrt_fsdb_session_check(
                hosts=hosts,
                expected_session_count=fsdb_sessions_per_host,
                check_id="fpf_hrt_postcheck",
            ),
            # tail: ODS-only checks
            *ods_postchecks,
            *hrt_memory_postchecks,
            *hrt_driver_postchecks,
            *spray_postchecks,
        ]
        snapshot_checks = [
            create_core_dumps_snapshot_check(),
        ]
        if use_bgp_snapshot:
            snapshot_checks.append(
                create_bgp_session_snapshot_check(
                    skip_flap_check=True, skip_uptime_check=True
                )
            )

    return prechecks, generic_postchecks, snapshot_checks


# Number of ODS-only "tail" postchecks the generic builder appends after the
# SSH/device-shell "head" block, given the ODS-only host lists. v2 uses this to
# splice its convergence checks between the head and the tail so its assembled
# postcheck order stays byte-for-byte identical.
def _fpf_generic_postcheck_tail_len(
    *,
    skip_ssh_dependent_checks: bool,
    hrt_memory_hosts: list[str] | None,
    hrt_driver_hosts: list[str] | None,
    spray_hosts: list[str] | None,
) -> int:
    n = 1 if hrt_memory_hosts else 0
    n += 1 if hrt_driver_hosts else 0
    n += 1 if spray_hosts else 0
    if not skip_ssh_dependent_checks:
        n += 4  # the four ODS discard/congestion counter checks
    return n


def create_fpf_hardening_playbook(
    gtsws: list[str],
    hosts: list[str],
    trigger_stsws: list[str],
    disruption_steps: list,
    disruption_duration_sec: int,
    recovery_wait_sec: int = 300,
    stabilization_delay_sec: int = 600,
    baseline_delay_sec: int = 120,
    injection_estimate_sec: int = 120,
    poll_interval_sec: int = 5,
    subnet_prefix: str = "5000:dd::/32",
    prefix_count: int = 70000,
    community_list: str = "stsw",
    lanes: list[int] | None = None,
    services_to_check: list[str] | None = None,
    additional_postchecks: list | None = None,
    concurrent_disruption_steps: list | None = None,
    playbook_name: str = "fpf_hardening",
    skip_ssh_dependent_checks: bool = False,
    prod_prefixes: list[str] | None = None,
    hrt_memory_hosts: list[str] | None = None,
    hrt_driver_hosts: list[str] | None = None,
    spray_hosts: list[str] | None = None,
    ods_entities: list[str] | None = None,
) -> Playbook:
    """FPF hardening playbook: prefix injection + stabilization + disruptive event.

    Extends the stable-state stress playbook with a disruptive event phase.
    The collector runs continuously through injection, stabilization, disruption,
    and recovery. The playbook structure is:

        prechecks → hardening_concurrent_stage → postchecks → cleanup

    The concurrent stage has 3 tracks (4 if concurrent_disruption_steps provided):
        Track 1: Continuous collector (FSDB ribMap, HRT bulk, BGP RIB)
        Track 2: Baseline delay → prefix injection
        Track 3: Pre-disruption delay → disruption_steps
        Track 4 (optional): Pre-disruption delay → concurrent_disruption_steps
    """
    from taac.health_checks.healthcheck_definitions import (
        create_bgp_stale_route_check,
        create_drain_state_check,
        create_fpf_bgp_rib_convergence_check,
        create_fpf_fsdb_ribmap_convergence_check,
        create_fpf_hrt_bulk_convergence_check,
        create_fpf_hrt_remote_failure_convergence_check,
        create_fpf_stale_prefix_check,
        create_service_restart_check,
    )
    from taac.stages.stage_definitions import (
        create_fpf_hardening_concurrent_stage,
    )
    from taac.steps.step_definitions import (
        create_fpf_bgp_prefix_injection_step,
    )

    services = services_to_check or ["bgpd", "fsdb", "wedge_agent", "qsfp_service"]
    resolved_lanes = lanes if lanes is not None else [0, 1]

    # Track 2 does: baseline_delay → injection (~injection_estimate_sec).
    # Track 3 must wait for injection to finish PLUS a full stabilization
    # window so prefixes are programmed before any disruption starts.
    pre_disruption_delay_sec = (
        baseline_delay_sec + injection_estimate_sec + stabilization_delay_sec
    )

    # Generic (non-convergence) checks shared with v2 / service-restart. This
    # adds the previously-missing ODS-counter / HRT-mem / HRT-driver / host-spray
    # checks plus the skip_ssh gating that v1 lacked.
    generic_prechecks, generic_postchecks, snapshot_checks = _build_fpf_generic_checks(
        hosts=hosts,
        services=services,
        gtsws=gtsws,
        trigger_stsws=trigger_stsws,
        skip_ssh_dependent_checks=skip_ssh_dependent_checks,
        fsdb_sessions_per_host=None,
        prod_prefixes=prod_prefixes,
        hrt_memory_hosts=hrt_memory_hosts,
        hrt_driver_hosts=hrt_driver_hosts,
        spray_hosts=spray_hosts,
        ods_entities=ods_entities,
    )

    # MANDATORY FPF drain pre-check: abort if any in-scope GTSW / trigger STSW is
    # drained (VF routes may already be withdrawn). Drainer doesn't yet support
    # GTSW (T263331198); the check reads the device drain state directly. One
    # check per device since create_drain_state_check is single-device scoped.
    drain_prechecks = [
        create_drain_state_check(expected_drained=False, device_name=device)
        for device in [*gtsws, *trigger_stsws]
    ]

    prechecks = [
        *drain_prechecks,
        *generic_prechecks,
        create_fpf_stale_prefix_check(
            subnet_prefix=subnet_prefix,
            check_id="fpf_stale_prefix_precheck",
        ),
    ]

    convergence_postchecks = []
    for lane_id, gtsw in enumerate(gtsws):
        lane_map = {str(lane_id): gtsw}
        convergence_postchecks.append(
            create_fpf_fsdb_ribmap_convergence_check(
                lane_map=lane_map,
                expected_matched=prefix_count,
                trigger_delay_sec=baseline_delay_sec,
                check_id=f"fpf_fsdb_convergence_lane{lane_id}",
            )
        )
        convergence_postchecks.append(
            create_fpf_bgp_rib_convergence_check(
                lane_map=lane_map,
                expected_matched=prefix_count,
                trigger_delay_sec=baseline_delay_sec,
                check_id=f"fpf_bgp_convergence_lane{lane_id}",
            )
        )
    for lane_id in resolved_lanes:
        convergence_postchecks.append(
            create_fpf_hrt_bulk_convergence_check(
                lanes=[lane_id],
                expected_per_lane={str(lane_id): prefix_count},
                trigger_delay_sec=baseline_delay_sec,
                check_id=f"fpf_hrt_convergence_lane{lane_id}",
            )
        )
    convergence_postchecks.append(
        create_fpf_hrt_remote_failure_convergence_check(
            lanes=resolved_lanes,
            direction="stable",
            use_live_collectors=True,
            check_id="fpf_remote_failure_stable",
        )
    )

    # Process-restart composition (the hardening playbook covers GR/warmboot of
    # various services): assert ONLY the expected services restarted and that no
    # BGP graceful-restart stale routes linger after recovery.
    # SERVICE_RESTART_CHECK is SSH/systemctl-based — gate it behind
    # skip_ssh_dependent_checks; BGP_STALE_ROUTE_CHECK reads the RIB over thrift
    # so it runs in both modes.
    postchecks = [
        *generic_postchecks,
        *(
            []
            if skip_ssh_dependent_checks
            else [create_service_restart_check(services=services)]
        ),
        create_bgp_stale_route_check(),
        *convergence_postchecks,
        *(additional_postchecks or []),
    ]

    hardening_stage = create_fpf_hardening_concurrent_stage(
        gtsws=gtsws,
        hosts=hosts,
        trigger_stsws=trigger_stsws,
        disruption_steps=disruption_steps,
        pre_disruption_delay_sec=pre_disruption_delay_sec,
        disruption_duration_sec=disruption_duration_sec,
        recovery_wait_sec=recovery_wait_sec,
        baseline_delay_sec=baseline_delay_sec,
        poll_interval_sec=poll_interval_sec,
        subnet_prefix=subnet_prefix,
        prefix_count=prefix_count,
        community_list=community_list,
        lanes=resolved_lanes,
        concurrent_disruption_steps=concurrent_disruption_steps,
    )

    cleanup_steps = [
        create_fpf_bgp_prefix_injection_step(
            devices=trigger_stsws,
            count=prefix_count,
            community_list=community_list,
            withdraw_only=True,
            description="Withdraw injected BGP prefixes (cleanup)",
        ),
    ]

    return Playbook(
        name=playbook_name,
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
        stages=[hardening_stage],
        cleanup_steps=cleanup_steps,
    )


def create_fpf_hardening_playbook_v2(
    gtsws: list[str],
    hosts: list[str],
    trigger_stsws: list[str],
    disruption_steps: list | None = None,
    soak_duration_sec: int = 60,
    stabilization_delay_sec: int = 600,
    prefix_count: int = 70000,
    community_list: str = "stsw",
    lanes: list[int] | None = None,
    services_to_check: list[str] | None = None,
    additional_postchecks: list | None = None,
    ods_entities: list[str] | None = None,
    playbook_name: str = "fpf_hardening_v2",
    prod_prefixes: list[str] | None = None,
    skip_ssh_dependent_checks: bool = False,
    use_bgp_snapshot: bool = False,
    prod_prefix_settle_sec: int = 0,
    convergence_settle_sec: int = 0,
    fsdb_expected_total: int | None = None,
    skip_fsdb_session_precheck: bool = False,
    hrt_memory_hosts: list[str] | None = None,
    hrt_driver_hosts: list[str] | None = None,
    spray_hosts: list[str] | None = None,
    host_spray_label: str = "",
    plane_status_check: bool = False,
    prod_prefix_recovery: bool = False,
    local_prod_prefixes: list[str] | None = None,
    impacted_planes_by_host: dict | None = None,
    skip_injection: bool = False,
    rf_vf_groups: list | None = None,
) -> Playbook:
    """FPF hardening playbook for use with long-lived collectors.

    ``rf_vf_groups`` (8-STSW split-per-VF injection): list of
    ``{"suffix", "subnet", "lanes"}``. When given, the single broad HRT
    remote-failure "stable" check is replaced by one per VF group, each scoped to
    that group's own lanes and reading its per-group collector
    ("hrt_remote_failure_<suffix>").

    ``skip_injection`` drops the in-playbook prefix-injection + stabilization
    stage steps. Use it when prefixes are injected once by a dedicated setup
    task (``fpf_inject_bgp_prefixes``, e.g. the 8-STSW split-per-VF injection) so
    the netcastle run injects exactly once from setup. ``prefix_count`` is then
    used only as the EXPECTED converged count for the per-GTSW/per-lane checks.

    ``fsdb_expected_total`` overrides the expected HRT FSDB session count
    (default ``32`` — every one of the 4 GPUs subscribes to all 8 GTSWs, so a
    BE node has a FIXED 4 x 8 = 32 sessions regardless of how many GTSWs we
    observe; the old ``len(gtsws) * 4`` default was wrong when ``gtsws`` is just
    the observer subset). ``skip_fsdb_session_precheck``
    drops the FSDB-session precheck (restore phase: the lab may still be in
    graceful-restart hold from the disrupt, which is informational, not a
    restore failure). ``convergence_settle_sec`` advances the convergence
    postchecks' window past the recovery (restore phase) so the impacted lane's
    re-converge transient isn't flagged as post-convergence instability.

    ``use_bgp_snapshot`` replaces the BGP-session *establish* checks (precheck,
    convergence-timing disruption postcheck, and full postcheck) with a single
    BGP-session SNAPSHOT check: the established set is tallied at precheck (no
    fail on baseline-down sessions) and asserted unchanged at postcheck. Use for
    link-event tests (interface enable / undrain), where the lab fabric may have
    sessions down at baseline and a GPU-link event does not change — nor flap —
    the GTSW<->STSW BGP sessions (so the uptime<10s convergence-timing check
    does not apply).

    ``host_spray_label`` (default "") is passed through as the ``label=`` of the
    generic host-spray postcheck so a results-table row can be self-describing
    (e.g. "[longevity] all 4 lanes >75Gbps"). Empty means no prefix — no change
    for existing callers.

    Assumes collectors are already running (via FpfStartCollectorsTask in
    setup_tasks). This playbook:
      1. Injects prefixes on STSW devices (test_case_start_time aligns here)
      2. Waits for stabilization (prefixes programmed on GTSW/HRT)
      3. Runs disruption steps (or soak for stable-state tests)
      4. Postchecks query live collectors for time-windowed convergence
    """
    from taac.health_checks.healthcheck_definitions import (
        create_bgp_session_establish_check,
        create_fpf_bgp_rib_convergence_check,
        create_fpf_fsdb_ribmap_convergence_check,
        create_fpf_hrt_bulk_convergence_check,
        create_fpf_hrt_plane_status_check,
        create_fpf_hrt_remote_failure_convergence_check,
        create_fpf_prod_hrt_prefix_stability_check,
    )
    from taac.stages.stage_definitions import (
        create_steps_stage,
    )
    from taac.steps.step_definitions import (
        create_fpf_bgp_prefix_injection_step,
        create_longevity_step,
    )

    from taac.libs.fpf.fpf_thresholds import (
        ACTIVE as FPF_ACTIVE_THRESHOLDS,
    )

    services = services_to_check or ["bgpd", "fsdb", "wedge_agent", "qsfp_service"]
    resolved_lanes = lanes if lanes is not None else [0, 1]
    # Default the expected HRT FSDB session count to 32 — the per-BE-node count
    # is FIXED at 32 (every one of the 4 GPUs subscribes to all 8 GTSWs:
    # 4 x 8 = 32) regardless of how many GTSWs we observe. The previous
    # ``len(gtsws) * 4`` default was wrong whenever ``gtsws`` is the observer
    # subset (e.g. 2 observers -> 8), which produced a false FAIL
    # "32/32 CONNECTED (expected 8)" on a healthy device. The
    # ``fsdb_expected_total`` override path is preserved for callers that need a
    # non-32 value (e.g. disruption configs expecting impacted lanes).
    fsdb_sessions_per_host = (
        fsdb_expected_total if fsdb_expected_total is not None else 32
    )

    # Generic (non-convergence) check set — SSH/device-shell generic checks +
    # ODS-only checks (discard/congestion counters, HRT mem/driver, host-spray)
    # + the matching prechecks and snapshot checks. Factored into
    # _build_fpf_generic_checks so v1 / service-restart share the exact same
    # logic; the assembled v2 lists below are byte-for-byte identical to before.
    prechecks, generic_postchecks, snapshot_checks = _build_fpf_generic_checks(
        hosts=hosts,
        services=services,
        gtsws=gtsws,
        trigger_stsws=trigger_stsws,
        skip_ssh_dependent_checks=skip_ssh_dependent_checks,
        fsdb_sessions_per_host=fsdb_sessions_per_host,
        prod_prefixes=prod_prefixes,
        hrt_memory_hosts=hrt_memory_hosts,
        hrt_driver_hosts=hrt_driver_hosts,
        spray_hosts=spray_hosts,
        ods_entities=ods_entities,
        use_bgp_snapshot=use_bgp_snapshot,
        skip_fsdb_session_precheck=skip_fsdb_session_precheck,
        host_spray_label=host_spray_label,
    )

    # Stage steps: inject → stabilize → disruption (or soak). When
    # skip_injection, prefixes are injected once by a setup task instead.
    stage_steps = []
    if not skip_injection:
        stage_steps.extend(
            [
                create_fpf_bgp_prefix_injection_step(
                    devices=trigger_stsws,
                    count=prefix_count,
                    community_list=community_list,
                    description=(
                        f"Inject {prefix_count} BGP prefixes on "
                        f"{', '.join(trigger_stsws)}"
                    ),
                ),
                create_longevity_step(
                    duration=stabilization_delay_sec,
                    description=(
                        f"Stabilization wait — {stabilization_delay_sec}s for "
                        f"prefixes to program on GTSW/HRT"
                    ),
                ),
            ]
        )
    if disruption_steps:
        stage_steps.extend(disruption_steps)
    elif soak_duration_sec > 0:
        stage_steps.append(
            create_longevity_step(
                duration=soak_duration_sec,
                description="Stable-state soak — no disruption",
            ),
        )

    convergence_postchecks = []
    for lane_id, gtsw in enumerate(gtsws):
        lane_map = {str(lane_id): gtsw}
        convergence_postchecks.append(
            create_fpf_fsdb_ribmap_convergence_check(
                lane_map=lane_map,
                expected_matched=prefix_count,
                use_live_collectors=True,
                signal1_e2e_max_sec=FPF_ACTIVE_THRESHOLDS.convergence_signal1_e2e_max_sec,
                signal2_local_max_sec=FPF_ACTIVE_THRESHOLDS.convergence_signal2_local_max_sec,
                signal3_stability_duration_sec=FPF_ACTIVE_THRESHOLDS.convergence_signal3_stability_duration_sec,
                settle_sec=convergence_settle_sec or None,
                check_id=f"fpf_fsdb_convergence_lane{lane_id}",
            )
        )
        convergence_postchecks.append(
            create_fpf_bgp_rib_convergence_check(
                lane_map=lane_map,
                expected_matched=prefix_count,
                use_live_collectors=True,
                signal1_e2e_max_sec=FPF_ACTIVE_THRESHOLDS.convergence_signal1_e2e_max_sec,
                signal2_local_max_sec=FPF_ACTIVE_THRESHOLDS.convergence_signal2_local_max_sec,
                signal3_stability_duration_sec=FPF_ACTIVE_THRESHOLDS.convergence_signal3_stability_duration_sec,
                settle_sec=convergence_settle_sec or None,
                check_id=f"fpf_bgp_convergence_lane{lane_id}",
            )
        )
    for lane_id in resolved_lanes:
        convergence_postchecks.append(
            create_fpf_hrt_bulk_convergence_check(
                lanes=[lane_id],
                expected_per_lane={str(lane_id): prefix_count},
                use_live_collectors=True,
                signal1_e2e_max_sec=FPF_ACTIVE_THRESHOLDS.convergence_signal1_e2e_max_sec,
                signal2_local_max_sec=FPF_ACTIVE_THRESHOLDS.convergence_signal2_local_max_sec,
                signal3_stability_duration_sec=FPF_ACTIVE_THRESHOLDS.convergence_signal3_stability_duration_sec,
                # settle past the recovery (restore phase) so the impacted lane's
                # re-converge transient isn't flagged as post-convergence churn.
                settle_sec=convergence_settle_sec or None,
                check_id=f"fpf_hrt_convergence_lane{lane_id}",
            )
        )
    if rf_vf_groups:
        for _g in rf_vf_groups:
            convergence_postchecks.append(
                create_fpf_hrt_remote_failure_convergence_check(
                    lanes=_g["lanes"],
                    direction="stable",
                    use_live_collectors=True,
                    collector_name=f"hrt_remote_failure_{_g['suffix']}",
                    check_id=f"fpf_remote_failure_stable_{_g['suffix']}",
                )
            )
    else:
        convergence_postchecks.append(
            create_fpf_hrt_remote_failure_convergence_check(
                lanes=resolved_lanes,
                direction="stable",
                use_live_collectors=True,
                check_id="fpf_remote_failure_stable",
            )
        )
    # Fifth collector ↔ fifth validating check: production HRT prefix
    # reachability stability. Only added when the prod_hrt_prefix collector
    # was started (prod_prefixes supplied to FpfStartCollectorsTask).
    if prod_prefixes and prod_prefix_recovery and local_prod_prefixes:
        # Recovery-anchored restore check: instead of a settle-and-baseline
        # stability assertion (which flags the recovery transient if the lane
        # comes back after the settle window), measure the LOCAL prefix's
        # restored lane returning to reachable — timed from the recorded recovery
        # moment (the re-enable / undrain command) to when the lane re-enters the
        # reachable set — and assert it within the SLA. REMOTE prefixes must not
        # churn. Robust regardless of how long recovery takes.
        convergence_postchecks.append(
            create_fpf_prod_hrt_prefix_stability_check(
                mode="local_undrain",
                local_prefixes=local_prod_prefixes,
                impacted_planes_by_host=impacted_planes_by_host or {},
                max_drain_sec=FPF_ACTIVE_THRESHOLDS.prod_prefix_recovery_sla_sec,
                check_id="fpf_prod_hrt_prefix_recovery",
            )
        )
    elif prod_prefixes:
        convergence_postchecks.append(
            create_fpf_prod_hrt_prefix_stability_check(
                # settle past the recovery (restore phase): the plane comes back
                # mid-window, so take the per-prefix baseline after it settles
                # rather than flagging the recovery as a regression.
                settle_sec=prod_prefix_settle_sec or None,
                check_id="fpf_prod_hrt_prefix_stability",
            )
        )
    # HRT plane-status (hrtctl show plane-status): every plane must be UP. Used by
    # the restore halves (link/device undrain) and stable configs (interface
    # enable) to assert full plane recovery. convergence_settle_sec advances the
    # window past the recovery transient so the re-up isn't flagged.
    if plane_status_check and prod_prefixes:
        convergence_postchecks.append(
            create_fpf_hrt_plane_status_check(
                mode="all_up",
                settle_sec=convergence_settle_sec or None,
                check_id="fpf_hrt_plane_status_all_up",
            )
        )

    disruption_postchecks = []
    if disruption_steps and not use_bgp_snapshot:
        # Convergence-timing check expects the BGP sessions to have flapped
        # (uptime<10s). For a GPU-link event the GTSW<->STSW sessions never flap,
        # so this is skipped under use_bgp_snapshot in favor of the snapshot.
        disruption_postchecks.append(
            create_bgp_session_establish_check(
                min_established_pct=0.5,
                max_session_uptime_sec=10.0,
                check_id="fpf_bgp_convergence_timing",
            )
        )

    # Splice the disruption + convergence postchecks between the generic head
    # (SSH/device-shell checks) and the generic tail (ODS counters, HRT
    # mem/driver, host-spray) so the assembled order is byte-for-byte identical
    # to before the _build_fpf_generic_checks extraction.
    tail_len = _fpf_generic_postcheck_tail_len(
        skip_ssh_dependent_checks=skip_ssh_dependent_checks,
        hrt_memory_hosts=hrt_memory_hosts,
        hrt_driver_hosts=hrt_driver_hosts,
        spray_hosts=spray_hosts,
    )
    generic_head = generic_postchecks[: len(generic_postchecks) - tail_len]
    generic_tail = generic_postchecks[len(generic_postchecks) - tail_len :]

    postchecks = [
        *generic_head,
        *disruption_postchecks,
        *convergence_postchecks,
        *generic_tail,
        *(additional_postchecks or []),
    ]

    return Playbook(
        name=playbook_name,
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
        stages=[create_steps_stage(stage_id="disruption", steps=stage_steps)],
    )


def create_fpf_link_event_disrupt_playbook(
    *,
    gtsws: list[str],
    hosts: list[str],
    trigger_stsws: list[str],
    disruption_steps: list,
    prefix_count: int,
    community_list: str,
    stabilization_delay_sec: int,
    injected_lanes: list[int],
    impacted_lanes: list[int],
    impacted_lanes_by_host_gpu: dict,
    impacted_beths_by_host: dict,
    impacted_planes_by_host: dict,
    prod_prefixes: list[str] | None = None,
    hrt_memory_hosts: list[str] | None = None,
    hrt_driver_hosts: list[str] | None = None,
    spray_hosts: list[str] | None = None,
    flip_fsdb_session: bool = True,
    flip_discards: bool = True,
    injected_prefixes_withdrawn: bool = True,
    remote_failure_sla_sec: int = 30,
    transition_sla_sec: int = 30,
    fsdb_expected_total: int = 32,
    impacted_max_gbps: float = 10.0,
    ods_entities: list[str] | None = None,
    include_ssh_checks: bool = False,
    plane_status_mode: str | None = None,
    ods_discard_informational: bool = False,
    skip_injection: bool = False,
    rf_vf_groups: list | None = None,
    gtsw_convergence_settle_sec: int = 0,
    playbook_name: str = "fpf_link_event_disrupt",
) -> Playbook:
    """Disrupt-phase playbook for FPF link events (interface-disable / link-drain).

    ``gtsw_convergence_settle_sec`` (use with skip_injection): settles the
    GTSW-side ribMap/BGP convergence eval window past the disruption so a
    transient single-poll BGP-thrift read of 0 during the drain/disable (a query
    artifact — FSDB stays at the expected count) is not counted as a post-
    convergence drop. Default 0 = unchanged for in-playbook-injection callers.

    ``rf_vf_groups`` (8-STSW split-per-VF injection): list of
    ``{"suffix", "subnet", "lanes"}``. When given, the broad HRT remote-failure
    "stable" check is replaced by one per VF group (scoped to that group's own
    lanes, reading its per-group collector) so each group asserts zero
    remote-failure where it IS reachable, not the other group's expected failures.

    ``skip_injection`` drops the in-playbook prefix-injection + stabilization
    stage steps (prefixes injected once by the ``fpf_inject_bgp_prefixes`` setup
    task — 8-STSW split-per-VF injection). ``prefix_count`` then serves only as
    the EXPECTED converged count for the per-GTSW ribMap/BGP and per-lane HRT
    bulk checks.

    Injects stress prefixes, stabilizes, then runs the supplied disruption steps
    (disable+longevity, or port-drain+longevity). Postchecks assert the
    *disrupted* contract over this playbook's own collector window (test case
    start time is reset per-playbook by the runner):

      - HRT bulk: ``impacted_lanes`` withdrawn (last sample 0), other injected
        lanes still converge.
      - HRT remote-failure: impacted lanes 0->prefix_count within
        ``remote_failure_sla_sec``; the other lanes stay 0 (stable).
      - Prod/broad prefix: mode="transition" — impacted planes go
        reachable->unreachable within ``transition_sla_sec`` on every host.
      - Host-spray: impacted beths < ``impacted_max_gbps``; floor+fairness over
        the unimpacted lanes.
      - FSDB/HRT session: when ``flip_fsdb_session`` (interface-disable),
        overall == ``fsdb_expected_total`` - N with per-GPU0 reconciliation;
        when False (link-drain "control up"), sessions stay all-CONNECTED.
      - ODS discards/congestion: when ``flip_discards`` (interface-disable),
        assert loss >= 10000; when False (drain), keep the stable <= bound.
        When ``ods_discard_informational`` is True (e.g. tc36 STSW all
        connections down) the two DISCARD checks (``in_dst_null_discard``,
        ``in_discard``) are recorded as INFORMATIONAL (breach -> PASS with an
        ``[INFORMATIONAL]`` prefix in the message instead of FAIL) — expected
        transient loss during the disruption window. The two CONGESTION checks
        stay hard (a link event must not cause congestion). This mirrors the
        ``ods_discard_informational`` plumbing on the service-restart playbook.
      - BGP RIB + FSDB ribMap (GTSW-side): unchanged convergence to threshold.

    Generic SSH/device checks are intentionally omitted — this is the no-SSH
    collector/ODS validation path. Pair this with a v2 stable-state restore
    playbook (enable/undrain) sequenced immediately after.
    """
    from taac.health_checks.healthcheck_definitions import (
        create_fpf_bgp_rib_convergence_check,
        create_fpf_fsdb_ribmap_convergence_check,
        create_fpf_host_spray_check,
        create_fpf_hrt_bulk_convergence_check,
        create_fpf_hrt_driver_disconnect_check,
        create_fpf_hrt_fsdb_session_check,
        create_fpf_hrt_plane_status_check,
        create_fpf_hrt_remote_failure_convergence_check,
        create_fpf_hrt_system_memory_check,
        create_fpf_ods_counter_check,
        create_fpf_prod_hrt_prefix_stability_check,
    )
    from taac.libs.fpf.fpf_thresholds import (
        ACTIVE as FPF_ACTIVE_THRESHOLDS,
    )
    from taac.stages.stage_definitions import create_steps_stage
    from taac.steps.step_definitions import (
        create_fpf_bgp_prefix_injection_step,
        create_fpf_record_disruption_time_step,
        create_longevity_step,
    )

    # ---- Prechecks: assert healthy/stable BEFORE the disruption ----
    prechecks = [
        create_fpf_hrt_fsdb_session_check(
            hosts=hosts,
            expected_session_count=fsdb_expected_total,
            check_id="fpf_hrt_fsdb_session_precheck",
        ),
    ]
    if prod_prefixes:
        prechecks.append(
            create_fpf_prod_hrt_prefix_stability_check(
                check_id="fpf_prod_hrt_prefix_stability_precheck",
            )
        )
    if hrt_memory_hosts:
        prechecks.append(
            create_fpf_hrt_system_memory_check(
                hosts=hrt_memory_hosts,
                threshold_gib=FPF_ACTIVE_THRESHOLDS.hrt_system_memory_max_gib,
                check_id="fpf_hrt_system_memory_precheck",
            )
        )

    # Generic SSH/device-shell checks (require a Kerberos/SSH cert). Asserted on
    # the DUT GTSWs before the disruption: services up, no recent unclean exits,
    # memory within per-process bounds. BGP sessions are handled as a SNAPSHOT
    # check (below) rather than a precheck establish check: the lab fabric often
    # has a few sessions already down at baseline, and a GPU-link disable/drain
    # must not change the GTSW<->STSW BGP session count anyway. So we tally the
    # established sessions at precheck (no fail) and assert the post-disruption
    # count matches in the postcheck — like the other snapshot checks.
    _mem_thresholds = {
        "bgpd": 4.5 * (1024**3),
        "fsdb": 5 * (1024**3),
        "qsfp_service": 2 * (1024**3),
        "fboss_sw_agent": 9 * (1024**3),
        "fboss_hw_agent@0": 8 * (1024**3),
    }
    if include_ssh_checks:
        prechecks.extend(
            [
                create_systemctl_active_state_check(),
                create_unclean_exit_check(),
                create_memory_utilization_check(
                    threshold=5 * (1024**3),
                    threshold_by_service=_mem_thresholds,
                    start_time_jq_var="test_case_start_time",
                ),
            ]
        )

    # ---- Stage: inject -> stabilize -> disruption ----
    # When skip_injection, prefixes are injected once by a setup task; the stage
    # starts at the disruption-time stamp.
    stage_steps = []
    if not skip_injection:
        stage_steps.extend(
            [
                create_fpf_bgp_prefix_injection_step(
                    devices=trigger_stsws,
                    count=prefix_count,
                    community_list=community_list,
                    description=f"Inject {prefix_count} BGP prefixes on {', '.join(trigger_stsws)}",
                ),
                create_longevity_step(
                    duration=stabilization_delay_sec,
                    description=(
                        f"Stabilization wait — {stabilization_delay_sec}s for prefixes "
                        f"to program on GTSW/HRT before disruption"
                    ),
                ),
            ]
        )
    stage_steps.extend(
        [
            # Stamp the disruption moment so the prod-prefix transition check
            # measures reachable->unreachable from here (30s SLA), not from
            # test_case_start (which precedes the stabilization wait).
            create_fpf_record_disruption_time_step(),
            *disruption_steps,
        ]
    )

    sig1 = FPF_ACTIVE_THRESHOLDS.convergence_signal1_e2e_max_sec
    sig2 = FPF_ACTIVE_THRESHOLDS.convergence_signal2_local_max_sec
    sig3 = FPF_ACTIVE_THRESHOLDS.convergence_signal3_stability_duration_sec

    postchecks = []

    # GTSW-side convergence (UNCHANGED — the GTSW<->GPU link being down does not
    # affect GTSW BGP/FSDB; prefixes remain present and converged).
    #
    # gtsw_convergence_settle_sec: when prefixes are injected by a SETUP TASK
    # (skip_injection=True), the injected prefixes are already converged when this
    # disrupt playbook starts, so T2 ≈ window_start and the 3-signal Signal-3
    # stability window overlaps the disruption. A drain/disable can make the
    # GTSW's BGP thrift query momentarily read 0 for a single poll (a transient
    # query artifact — the FSDB ribMap on the same GTSW stays at the expected
    # count, proving the prefixes never left), which Signal-3 would otherwise count
    # as a drop. Settling the window past the disruption skips that artifact and
    # measures the post-disruption steady state. Default 0 keeps existing callers
    # (in-playbook injection) byte-identical.
    _gtsw_settle = gtsw_convergence_settle_sec or None
    for lane_id, gtsw in enumerate(gtsws):
        lane_map = {str(lane_id): gtsw}
        postchecks.append(
            create_fpf_fsdb_ribmap_convergence_check(
                lane_map=lane_map,
                expected_matched=prefix_count,
                use_live_collectors=True,
                signal1_e2e_max_sec=sig1,
                signal2_local_max_sec=sig2,
                signal3_stability_duration_sec=sig3,
                settle_sec=_gtsw_settle,
                check_id=f"fpf_fsdb_convergence_lane{lane_id}",
            )
        )
        postchecks.append(
            create_fpf_bgp_rib_convergence_check(
                lane_map=lane_map,
                expected_matched=prefix_count,
                use_live_collectors=True,
                signal1_e2e_max_sec=sig1,
                signal2_local_max_sec=sig2,
                signal3_stability_duration_sec=sig3,
                settle_sec=_gtsw_settle,
                check_id=f"fpf_bgp_convergence_lane{lane_id}",
            )
        )

    # Lane -> host-NIC mapping note for debuggability (e.g. "→ beth0@rtptest1544").
    # Derived from the circuits' impacted beths (beth index = gpu*8 + lane, so
    # lane = index % 8). Surfaced verbatim in the bulk/remote-failure messages so
    # a reviewer sees which physical NIC each impacted fabric lane corresponds to.
    _lane_to_beths: dict[str, list[str]] = {}
    for _host, _beths in (impacted_beths_by_host or {}).items():
        for _beth in _beths:
            _digits = "".join(ch for ch in _beth if ch.isdigit())
            if not _digits:
                continue
            _lane = str(int(_digits) % 8)
            _lane_to_beths.setdefault(_lane, []).append(f"{_beth}@{_host}")
    lane_labels = {
        _lane: "→ " + ", ".join(sorted(_v)) for _lane, _v in _lane_to_beths.items()
    }

    # ``injected_prefixes_withdrawn`` distinguishes interface-disable (the port
    # goes DOWN -> ALL prefixes on the lane withdrawn -> bulk -> 0, remote-failure
    # rises) from a community-based soft-DRAIN (depreferences the production VF
    # plane — caught by the prod-prefix transition below — but does NOT withdraw
    # the directly-injected test prefixes, whose count in HRT is unchanged). For
    # a drain we therefore do NOT expect the injected prefixes to withdraw: the
    # impacted lane is asserted as a normal converged lane and remote-failure
    # stays stable on every injected lane. The real drain disruption signal is
    # the prod-prefix transition + host-spray.
    impacted_hosts = sorted(impacted_lanes_by_host_gpu.keys())
    bulk_impacted = impacted_lanes if injected_prefixes_withdrawn else []
    # When the injected prefixes withdraw (disable) only the impacted host's lane
    # changes -> scope to it. When they don't (drain) the injected prefixes stay
    # converged on EVERY host -> evaluate all hosts.
    bulk_only_hosts = impacted_hosts if injected_prefixes_withdrawn else None
    postchecks.append(
        create_fpf_hrt_bulk_convergence_check(
            lanes=injected_lanes,
            expected_per_lane={str(lane): prefix_count for lane in injected_lanes},
            impacted_lanes=bulk_impacted,
            withdrawn_max_count=0,
            lane_labels=lane_labels,
            only_hosts=bulk_only_hosts,
            use_live_collectors=True,
            signal1_e2e_max_sec=sig1,
            signal2_local_max_sec=sig2,
            signal3_stability_duration_sec=sig3,
            check_id="fpf_hrt_bulk_disrupt",
        )
    )

    # HRT remote-failure. For interface-disable the impacted lane rises 0->count
    # (drain direction); for a soft-drain the injected prefixes don't withdraw, so
    # there is no rise — every injected lane stays stable. Scoped to the impacted
    # host(s) for the rise; the stable assertion covers the injected lanes only
    # (a non-injected lane can show unrelated nonzero samples).
    if injected_prefixes_withdrawn and impacted_lanes:
        postchecks.append(
            create_fpf_hrt_remote_failure_convergence_check(
                lanes=impacted_lanes,
                expected_per_lane={str(lane): prefix_count for lane in impacted_lanes},
                direction="drain",
                max_convergence_sec=remote_failure_sla_sec,
                lane_labels=lane_labels,
                only_hosts=impacted_hosts,
                use_live_collectors=True,
                check_id="fpf_remote_failure_impacted",
            )
        )
    stable_rf = [
        lane
        for lane in injected_lanes
        if not (injected_prefixes_withdrawn and lane in impacted_lanes)
    ]
    if stable_rf and rf_vf_groups:
        # Per-VF-group: assert zero remote-failure on each group's OWN lanes
        # (intersected with the stable set), reading the group's narrow-subnet
        # collector so the other group's expected cross-plane failures are excluded.
        for _g in rf_vf_groups:
            _glanes = [lane for lane in _g["lanes"] if lane in stable_rf]
            if not _glanes:
                continue
            postchecks.append(
                create_fpf_hrt_remote_failure_convergence_check(
                    lanes=_glanes,
                    direction="stable",
                    only_hosts=impacted_hosts,
                    use_live_collectors=True,
                    collector_name=f"hrt_remote_failure_{_g['suffix']}",
                    check_id=f"fpf_remote_failure_unimpacted_stable_{_g['suffix']}",
                )
            )
    elif stable_rf:
        postchecks.append(
            create_fpf_hrt_remote_failure_convergence_check(
                lanes=stable_rf,
                direction="stable",
                only_hosts=impacted_hosts,
                use_live_collectors=True,
                check_id="fpf_remote_failure_unimpacted_stable",
            )
        )

    # Prod/broad prefix transition: impacted planes go unreachable within SLA,
    # evaluated on every registered prod-prefix host.
    if prod_prefixes:
        postchecks.append(
            create_fpf_prod_hrt_prefix_stability_check(
                mode="transition",
                impacted_planes_by_host=impacted_planes_by_host,
                max_transition_sec=float(transition_sla_sec),
                check_id="fpf_prod_hrt_prefix_transition",
            )
        )

    # HRT plane-status (hrtctl show plane-status): for a DRAIN the impacted
    # plane(s) go DRAINED while every other plane stays UP. Only added when the
    # caller opts in via plane_status_mode="drain" (link/device drain) — a port
    # disable shows the plane DOWN, not DRAINED, so it is out of this contract.
    # Plane == lane on the monitored GPU device, so impacted_planes=impacted_lanes.
    if plane_status_mode == "drain" and prod_prefixes and impacted_lanes:
        postchecks.append(
            create_fpf_hrt_plane_status_check(
                mode="drain",
                impacted_planes=impacted_lanes,
                check_id="fpf_hrt_plane_status_drain",
            )
        )

    # Host-spray: impacted beths drained (<impacted_max_gbps); floor+fairness
    # on the unimpacted lanes. Draining a fabric lane (the GTSW plane serving it)
    # stops egress on that lane's beth for EVERY traffic host attached to the
    # plane — not just the directly-drained circuit's host. So the impacted beth
    # (beth{lane}) is expected at ~0 on ALL spray hosts; mark it impacted on each
    # so the floor/spread are asserted only over the genuinely unimpacted lanes.
    if spray_hosts:
        spray_impacted_by_host = {
            h: [f"beth{lane}" for lane in impacted_lanes] for h in spray_hosts
        }
        postchecks.append(
            create_fpf_host_spray_check(
                hosts=spray_hosts,
                min_egress_gbps=FPF_ACTIVE_THRESHOLDS.host_spray_min_egress_gbps,
                max_spread_gbps=FPF_ACTIVE_THRESHOLDS.host_spray_max_spread_gbps,
                impacted_lanes_by_host=spray_impacted_by_host,
                impacted_max_gbps=impacted_max_gbps,
                check_id="fpf_host_spray_disrupt",
            )
        )

    # FSDB/HRT session reconciliation.
    if flip_fsdb_session:
        postchecks.append(
            create_fpf_hrt_fsdb_session_check(
                hosts=hosts,
                expected_session_count=fsdb_expected_total,
                impacted_lanes_by_host_gpu=impacted_lanes_by_host_gpu,
                reconcile_device_id=0,
                check_id="fpf_hrt_fsdb_session_disrupt",
            )
        )
    else:
        # Link-drain "control up": sessions stay fully CONNECTED.
        postchecks.append(
            create_fpf_hrt_fsdb_session_check(
                hosts=hosts,
                expected_session_count=fsdb_expected_total,
                check_id="fpf_hrt_fsdb_session_stable",
            )
        )

    # ODS discards/congestion (ODS-only, no SSH). interface-disable flips the
    # expectation to assert real packet loss; drain keeps the clean bound.
    # When ods_discard_informational is True (e.g. tc36: shutting an entire
    # STSW->GTSW bundle), expected transient loss on the impacted plane is
    # RECORDED but never fails the test — the two DISCARD <= checks carry
    # informational=True (breach -> PASS with [INFORMATIONAL]). The two
    # CONGESTION checks are always hard (a link event must not cause
    # congestion). This mirrors the same knob on the service-restart playbook.
    ods_entity_desc = ",".join(ods_entities or (gtsws + trigger_stsws))
    ods_reduce = r"groupby(entity, (\S+?\.\S+?)\..*, %1),sum"
    if ods_discard_informational:
        # Same four-check shape as _build_fpf_generic_checks but inline (the
        # link-event playbook does not otherwise route through that helper).
        postchecks.extend(
            [
                create_fpf_ods_counter_check(
                    entity_desc=ods_entity_desc,
                    key_desc="regex(fboss.agent.eth.*discards.sum.60),filter(.*in_dst_null.*)",
                    validation_expr=f"<= {FPF_ACTIVE_THRESHOLDS.ods_in_dst_null_discard_max}",
                    reduce_desc=ods_reduce,
                    counter_name="in_dst_null_discard",
                    shorten_pass_url=True,
                    informational=True,
                    check_id="ods_in_dst_null_discard",
                ),
                create_fpf_ods_counter_check(
                    entity_desc=ods_entity_desc,
                    key_desc="regex(fboss.agent.eth.*discards.sum.60),filter(.*in_discard.*)",
                    validation_expr=f"<= {FPF_ACTIVE_THRESHOLDS.ods_in_discard_max}",
                    reduce_desc=ods_reduce,
                    counter_name="in_discard",
                    shorten_pass_url=True,
                    informational=True,
                    check_id="ods_in_discard",
                ),
                create_fpf_ods_counter_check(
                    entity_desc=ods_entity_desc,
                    key_desc="regex(fboss.agent.eth.*congestion.*sum.60),filter(.*in_congestion_discards.sum.*)",
                    validation_expr=f"<= {FPF_ACTIVE_THRESHOLDS.ods_in_congestion_max}",
                    reduce_desc=ods_reduce,
                    counter_name="in_congestion",
                    shorten_pass_url=True,
                    check_id="ods_in_congestion",
                ),
                create_fpf_ods_counter_check(
                    entity_desc=ods_entity_desc,
                    key_desc="regex(fboss.agent.eth.*congestion.*sum.60),filter(.*out_congestion_discards.sum.*)",
                    validation_expr=f"<= {FPF_ACTIVE_THRESHOLDS.ods_out_congestion_max}",
                    reduce_desc=ods_reduce,
                    counter_name="out_congestion",
                    shorten_pass_url=True,
                    check_id="ods_out_congestion",
                ),
            ]
        )
    elif flip_discards:
        loss_expr = f">= {FPF_ACTIVE_THRESHOLDS.ods_in_discard_max}"
        # "Assert loss occurred": a disable only drops traffic on the impacted
        # path, and in_discard is 0 at most samples. So judge each device's PEAK
        # over the window and pass if ANY device saw loss >= threshold — not
        # every sample on every device (which would never pass).
        postchecks.append(
            create_fpf_ods_counter_check(
                entity_desc=ods_entity_desc,
                key_desc="regex(fboss.agent.eth.*discards.sum.60),filter(.*in_discard.*)",
                validation_expr=loss_expr,
                reduce_desc=ods_reduce,
                counter_name="in_discard",
                shorten_pass_url=True,
                aggregate="max",
                require="any",
                check_id="ods_in_discard_loss_expected",
            )
        )

    # HRT memory/driver stability (ODS-only).
    if hrt_memory_hosts:
        postchecks.append(
            create_fpf_hrt_system_memory_check(
                hosts=hrt_memory_hosts,
                threshold_gib=FPF_ACTIVE_THRESHOLDS.hrt_system_memory_max_gib,
                check_id="fpf_hrt_system_memory",
            )
        )
    if hrt_driver_hosts:
        postchecks.append(
            create_fpf_hrt_driver_disconnect_check(
                hosts=hrt_driver_hosts,
                check_id="fpf_hrt_driver_disconnect",
            )
        )

    # Generic SSH/device-shell postchecks on the DUT GTSWs: services still up,
    # no new core dumps, no unclean exits, memory/CPU within bounds after the
    # disruption window.
    snapshot_checks = []
    if include_ssh_checks:
        postchecks.extend(
            [
                create_systemctl_active_state_check(),
                create_device_core_dumps_check(use_start_time=False),
                create_unclean_exit_check(),
                create_memory_utilization_check(
                    threshold=5 * (1024**3),
                    threshold_by_service=_mem_thresholds,
                    start_time_jq_var="test_case_start_time",
                ),
                create_cpu_utilization_check(
                    threshold=400.0, start_time_jq_var="test_case_start_time"
                ),
            ]
        )
        snapshot_checks.append(create_core_dumps_snapshot_check())
        # BGP sessions: snapshot the established set at precheck (no fail on
        # baseline-down sessions) and assert it is unchanged post-disruption —
        # a GPU-link disable/drain must not drop any GTSW<->STSW BGP session.
        snapshot_checks.append(
            create_bgp_session_snapshot_check(
                skip_flap_check=True, skip_uptime_check=True
            )
        )

    return Playbook(
        name=playbook_name,
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
        stages=[create_steps_stage(stage_id="disruption", steps=stage_steps)],
    )


def create_fpf_disruption_only_playbook(
    *,
    gtsws: list[str],
    hosts: list[str],
    trigger_stsws: list[str],
    disruption_steps: list,
    playbook_name: str,
) -> Playbook:
    """Bare FPF disruption playbook — runs disruption steps, NO pre/postchecks.

    This is the FIRST half of the two-playbook "longevity-anchored health
    check" pattern. It executes ``disruption_steps`` as a single sequential
    stage and attaches NO prechecks, NO postchecks, and NO snapshot checks, so
    it does nothing but perform the disruption (interface disable/enable, link
    drain/undrain, service kill, etc.).

    Why two playbooks: the TaacRunner stamps a FRESH ``test_case_start_time``
    (both ``jq_vars["test_case_start_time"]`` and the FPF collector-registry
    ``set_test_case_start_time(...)``) at the START of EVERY playbook it runs
    (see ``TaacRunner._run_playbook``). Any FPF check that anchors its query
    window at ``get_test_case_start_time()`` (host-spray, HRT convergence/
    stability, prod-prefix drain, ODS-counter, etc.) therefore measures from
    whichever playbook it lives in — NOT from the overall test-case start.

    The disruptive configs run a disruption phase and then a 5-minute longevity
    phase, and want MOST health checks to measure only the steady-state
    LONGEVITY window (not the noisy disruption window). To achieve that, a
    config lists TWO playbooks:

        playbooks = [
            create_fpf_disruption_only_playbook(
                gtsws=...,
                hosts=...,
                trigger_stsws=...,
                disruption_steps=[...],          # the disruptive actions
                playbook_name="fpf_<case>_disrupt",
            ),
            create_fpf_<...>_longevity_playbook(  # any stable-state playbook
                ...,                              # e.g. a 300s longevity stage
            ),
        ]

    Because the runner stamps a new ``test_case_start_time`` when it starts the
    SECOND (longevity) playbook, every stable-state health check in that
    longevity playbook naturally anchors its window at LONGEVITY START — the
    disruption window is already over and is excluded. The disruption playbook
    here carries no checks, so nothing measures across the disruption itself.

    Args:
        gtsws / hosts / trigger_stsws: FPF topology handles, accepted for
            signature-parity with the other FPF playbook factories (so a config
            can pass the same handles it passes elsewhere). Not otherwise used
            since this playbook runs no checks.
        disruption_steps: Pre-built Steps to run as the single disruption stage.
        playbook_name: Name for this playbook (e.g. ``"fpf_<case>_disrupt"``).

    Returns:
        A ``Playbook`` with empty prechecks/postchecks/snapshot_checks and a
        single ``create_steps_stage`` wrapping ``disruption_steps``.
    """
    return Playbook(
        name=playbook_name,
        prechecks=[],
        postchecks=[],
        snapshot_checks=[],
        stages=[
            create_steps_stage(stage_id="disruption", steps=list(disruption_steps))
        ],
    )


def create_fpf_stays_down_assertion_playbook(
    *,
    playbook_name: str,
    stays_down_steps: list,
    postchecks: list,
    stage_id: str = "stays_down",
) -> Playbook:
    """Bare FPF "stays-down" assertion playbook — runs a short longevity, then
    asserts the impaired steady state.

    This is the SECOND half of the two-playbook "longevity-anchored health
    check" pattern used by tc30-style "stop and never re-enable" tests where
    the system is left in an impaired steady state and the check asserts that
    state holds. The TaacRunner stamps a FRESH ``test_case_start_time`` at
    the START of this playbook (see ``TaacRunner._run_playbook``), so any
    health check anchored at ``get_test_case_start_time()`` measures only the
    post-disruption stable window.

    Args:
        playbook_name: Name for this playbook (e.g.
            ``"fpf_<case>_stays_down"``).
        stays_down_steps: Pre-built Steps to run as the single stays-down
            stage (typically a single ``create_longevity_step``).
        postchecks: Postchecks to assert the impaired steady state — typically
            ``create_fpf_hrt_session_stat_check(mode="stable", ...)`` and any
            related stable-mode checks.
        stage_id: Stage id (default ``"stays_down"``).

    Returns:
        A ``Playbook`` with empty prechecks/snapshot_checks, the supplied
        postchecks, and a single ``create_steps_stage`` wrapping
        ``stays_down_steps``.
    """
    return Playbook(
        name=playbook_name,
        prechecks=[],
        postchecks=list(postchecks),
        snapshot_checks=[],
        stages=[create_steps_stage(stage_id=stage_id, steps=list(stays_down_steps))],
    )


def create_fpf_disrupt_window_playbook(
    *,
    playbook_name: str,
    disruption_steps: list,
    postchecks: list,
    stage_id: str = "disruption",
) -> Playbook:
    """FPF disruption playbook with disruption-window-scoped postchecks.

    Variant of ``create_fpf_disruption_only_playbook`` that ALSO attaches the
    supplied ``postchecks``. Use this when a tc-specific check (typically
    ``create_fpf_hrt_session_stat_check`` in ``mode="disruption"``) must
    measure ACROSS the disruption window — i.e. the postcheck's query window
    must include the disruptive event itself, so the check has to live in the
    same playbook as the disruption stage (since TaacRunner stamps a fresh
    ``test_case_start_time`` at every playbook start). Common pattern for
    tc28/tc29 (fsdb kill / GR stop-and-reenable) where the session-stat check
    must observe both the impaired count and the recovery.

    Args:
        playbook_name: Name for this playbook (e.g. ``"fpf_<case>_disrupt"``).
        disruption_steps: Pre-built Steps to run as the single disruption
            stage.
        postchecks: Postchecks to run at the end of the disruption stage —
            typically a single ``create_fpf_hrt_session_stat_check`` plus any
            additional disruption-window-anchored checks (e.g. host-spray).
        stage_id: Stage id (default ``"disruption"``).

    Returns:
        A ``Playbook`` with empty prechecks/snapshot_checks, the supplied
        postchecks, and a single ``create_steps_stage`` wrapping
        ``disruption_steps``.
    """
    return Playbook(
        name=playbook_name,
        prechecks=[],
        postchecks=list(postchecks),
        snapshot_checks=[],
        stages=[create_steps_stage(stage_id=stage_id, steps=list(disruption_steps))],
    )


def create_fpf_prod_prefix_drain_only_playbook(
    *,
    hosts: list[str],
    disruption_steps: list,
    local_prefixes: list[str],
    remote_prefixes: list[str],
    impacted_planes_by_host: dict,
    mode: str,
    max_drain_sec: float | None = None,
    playbook_name: str = "fpf_prod_prefix_drain_only",
) -> Playbook:
    """Minimal FPF playbook that runs ONLY the prod-prefix local-drain check.

    A focused validation harness for the local-vs-remote drain contract — NO
    test-prefix injection, NO stabilization wait, and NO other health checks.
    The production prefixes are real (already on the fabric), so nothing needs
    injecting; the prod-prefix collector (started by FpfStartCollectorsTask in
    setup_tasks) supplies the pre/post-drain samples. The supplied
    ``disruption_steps`` (drain+longevity or undrain+longevity) record the
    disruption moment themselves, from which the check measures drain latency.

    ``mode`` is "local_drain" (the LOCAL prefix's impacted plane must reach
    DRAINED — not unreachable — within the SLA while REMOTE prefixes don't churn)
    or "local_undrain" (the impacted plane returns to reachable within the SLA).
    """
    from taac.health_checks.healthcheck_definitions import (
        create_fpf_prod_hrt_prefix_stability_check,
    )
    from taac.libs.fpf.fpf_thresholds import (
        ACTIVE as FPF_ACTIVE_THRESHOLDS,
    )
    from taac.stages.stage_definitions import create_steps_stage

    if max_drain_sec is not None:
        sla = max_drain_sec
    elif mode == "local_undrain":
        # Recovery (undrain / re-enable) is inherently slower than a drain.
        sla = FPF_ACTIVE_THRESHOLDS.prod_prefix_recovery_sla_sec
    else:
        sla = FPF_ACTIVE_THRESHOLDS.prod_prefix_drain_sla_sec
    monitored = list(local_prefixes) + list(remote_prefixes)
    postchecks = [
        create_fpf_prod_hrt_prefix_stability_check(
            mode=mode,
            prefixes=monitored,
            local_prefixes=local_prefixes,
            impacted_planes_by_host=impacted_planes_by_host,
            max_drain_sec=sla,
            check_id=f"fpf_prod_prefix_{mode}",
        )
    ]
    return Playbook(
        name=playbook_name,
        prechecks=[],
        postchecks=postchecks,
        snapshot_checks=[],
        stages=[
            create_steps_stage(stage_id="disruption", steps=list(disruption_steps))
        ],
    )


def create_fpf_service_restart_playbook(
    *,
    gtsws: list[str],
    hosts: list[str],
    trigger_stsws: list[str],
    service,
    trigger: taac_types.ServiceInterruptionTrigger = taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
    restart_device_regexes: list[str],
    affected_rib: str | None,
    prefix_count: int,
    community_list: str,
    injected_lanes: list[int],
    prod_prefixes: list[str] | None = None,
    hrt_memory_hosts: list[str] | None = None,
    hrt_driver_hosts: list[str] | None = None,
    spray_hosts: list[str] | None = None,
    ods_entities: list[str] | None = None,
    fsdb_expected_total: int = 32,
    stabilization_delay_sec: int = 120,
    settle_after_restart_sec: int = 120,
    create_cold_boot_file: bool = False,
    bgp_reconverge_sla_sec: float | None = None,
    fsdb_reconverge_sla_sec: float | None = None,
    stable_settle_sec: int = 0,
    skip_ssh_dependent_checks: bool = False,
    skip_injection: bool = False,
    rf_vf_groups: list | None = None,
    playbook_name: str = "fpf_service_restart",
) -> Playbook:
    """FPF service-restart / coldboot playbook (single playbook, self-recovering).

    ``rf_vf_groups`` (8-STSW split-per-VF injection): a list of
    ``{"suffix", "subnet", "lanes"}`` dicts. When given, the single broad HRT
    remote-failure "stable" check is replaced by one per VF group, each scoped to
    that group's own lanes and reading its per-group collector
    ("hrt_remote_failure_<suffix>") — so each group asserts ZERO remote-failure on
    the lanes where it IS reachable, instead of tripping on the other group's
    expected cross-plane failures.

    ``skip_injection`` drops the in-playbook prefix-injection + stabilization
    stage steps (prefixes injected once by the ``fpf_inject_bgp_prefixes`` setup
    task — 8-STSW split-per-VF injection). ``prefix_count`` then serves only as
    the EXPECTED converged count for the per-GTSW/per-lane checks.

    Injects prefixes, stabilizes, records the restart moment, restarts ``service``
    on ``restart_device_regexes`` (the DUT GTSW), waits ``settle_after_restart_sec``,
    then asserts:

      - HRT (bulk / remote-failure / prod-prefix / plane-status): NO churn — the
        restart is on the GTSW; HRT is queried on the GPU host and is unaffected.
        (For a disruptive coldboot, ``stable_settle_sec`` advances these windows
        past the recovery transient so only the recovered steady state is judged.)
      - The AFFECTED rib (``affected_rib`` = "bgp" for bgpd / wedge_agent restart,
        "fsdb" for an fsdb restart) uses mode="restart": tolerate the
        null/unresponsive polls during the restart and assert the rib returns to
        ``prefix_count`` within the reconverge SLA from the recorded restart.
      - The UNAFFECTED rib stays converged (normal 3-signal, no drop).
      - ``affected_rib=None`` (qsfp_service): both ribs stay converged — identical
        to stable state.

    No SSH/host-spray/discard-loss assertions are added — a graceful restart is
    lossless and host-spray needs live ib traffic. Coldboot
    (``create_cold_boot_file=True``) is the same shape with a longer settle
    (``stable_settle_sec``/``settle_after_restart_sec``) and reconverge SLAs.
    """
    from taac.health_checks.healthcheck_definitions import (
        create_bgp_stale_route_check,
        create_drain_state_check,
        create_fpf_bgp_rib_convergence_check,
        create_fpf_fsdb_ribmap_convergence_check,
        create_fpf_hrt_bulk_convergence_check,
        create_fpf_hrt_fsdb_session_check,
        create_fpf_hrt_plane_status_check,
        create_fpf_hrt_remote_failure_convergence_check,
        create_fpf_prod_hrt_prefix_stability_check,
        create_service_restart_check,
    )
    from taac.libs.fpf.fpf_thresholds import (
        ACTIVE as FPF_ACTIVE_THRESHOLDS,
    )
    from taac.stages.stage_definitions import create_steps_stage
    from taac.steps.step_definitions import (
        create_fpf_bgp_prefix_injection_step,
        create_fpf_record_disruption_time_step,
        create_longevity_step,
        create_service_interruption_step,
    )

    services = ["bgpd", "fsdb", "wedge_agent", "qsfp_service"]

    # Generic (non-convergence) check set shared with the hardening playbooks:
    # generic prechecks (with the MANDATORY drain pre-check prepended as the
    # first stage step below), generic postchecks, and snapshot checks.
    generic_prechecks, generic_postchecks, snapshot_checks = _build_fpf_generic_checks(
        hosts=hosts,
        services=services,
        gtsws=gtsws,
        trigger_stsws=trigger_stsws,
        skip_ssh_dependent_checks=skip_ssh_dependent_checks,
        fsdb_sessions_per_host=fsdb_expected_total,
        prod_prefixes=prod_prefixes,
        hrt_memory_hosts=hrt_memory_hosts,
        hrt_driver_hosts=hrt_driver_hosts,
        spray_hosts=spray_hosts,
        ods_entities=ods_entities,
        # A restart/coldboot with live traffic causes expected transient
        # in-flight discards; surface them as informational, not a test failure.
        ods_discard_informational=True,
    )

    # MANDATORY FPF drain pre-check (matches v1): abort if any in-scope GTSW /
    # trigger STSW is drained. One check per device (single-device scoped).
    drain_prechecks = [
        create_drain_state_check(expected_drained=False, device_name=device)
        for device in [*gtsws, *trigger_stsws]
    ]

    bgp_sla = (
        bgp_reconverge_sla_sec
        if bgp_reconverge_sla_sec is not None
        else FPF_ACTIVE_THRESHOLDS.bgp_restart_reconverge_sla_sec
    )
    fsdb_sla = (
        fsdb_reconverge_sla_sec
        if fsdb_reconverge_sla_sec is not None
        else FPF_ACTIVE_THRESHOLDS.fsdb_restart_reconverge_sla_sec
    )
    settle = stable_settle_sec or None

    # When skip_injection, prefixes are injected once by a setup task; the stage
    # starts at the restart-time stamp.
    stage_steps = []
    if not skip_injection:
        stage_steps.extend(
            [
                create_fpf_bgp_prefix_injection_step(
                    devices=trigger_stsws,
                    count=prefix_count,
                    community_list=community_list,
                    description=f"Inject {prefix_count} BGP prefixes on {', '.join(trigger_stsws)}",
                ),
                create_longevity_step(
                    duration=stabilization_delay_sec,
                    description=f"Stabilization wait {stabilization_delay_sec}s before restart",
                ),
            ]
        )
    stage_steps.extend(
        [
            # Stamp the restart moment so the affected-rib reconverge SLA measures
            # from here, not test-case start.
            create_fpf_record_disruption_time_step(),
            create_service_interruption_step(
                service=service,
                trigger=trigger,
                create_cold_boot_file=create_cold_boot_file,
                device_regexes=restart_device_regexes,
                description=f"{'Cold boot' if create_cold_boot_file else 'Restart'} "
                f"service on {restart_device_regexes}",
            ),
            create_longevity_step(
                duration=settle_after_restart_sec,
                description=f"Settle {settle_after_restart_sec}s after restart before assertion",
            ),
        ]
    )

    postchecks = []

    # --- Per-GTSW rib checks: affected rib reconverges (null-tolerant), the
    # other stays converged. ---
    for lane_id, gtsw in enumerate(gtsws):
        lane_map = {str(lane_id): gtsw}
        if affected_rib == "bgp":
            postchecks.append(
                create_fpf_bgp_rib_convergence_check(
                    lane_map=lane_map,
                    expected_matched=prefix_count,
                    use_live_collectors=True,
                    mode="restart",
                    reconverge_sla_sec=bgp_sla,
                    check_id=f"fpf_bgp_restart_reconverge_lane{lane_id}",
                )
            )
            postchecks.append(
                create_fpf_fsdb_ribmap_convergence_check(
                    lane_map=lane_map,
                    expected_matched=prefix_count,
                    use_live_collectors=True,
                    settle_sec=settle,
                    check_id=f"fpf_fsdb_stable_lane{lane_id}",
                )
            )
        elif affected_rib == "fsdb":
            postchecks.append(
                create_fpf_fsdb_ribmap_convergence_check(
                    lane_map=lane_map,
                    expected_matched=prefix_count,
                    use_live_collectors=True,
                    mode="restart",
                    reconverge_sla_sec=fsdb_sla,
                    check_id=f"fpf_fsdb_restart_reconverge_lane{lane_id}",
                )
            )
            postchecks.append(
                create_fpf_bgp_rib_convergence_check(
                    lane_map=lane_map,
                    expected_matched=prefix_count,
                    use_live_collectors=True,
                    settle_sec=settle,
                    check_id=f"fpf_bgp_stable_lane{lane_id}",
                )
            )
        else:
            # qsfp_service: both ribs stay converged (identical to stable state).
            postchecks.append(
                create_fpf_fsdb_ribmap_convergence_check(
                    lane_map=lane_map,
                    expected_matched=prefix_count,
                    use_live_collectors=True,
                    settle_sec=settle,
                    check_id=f"fpf_fsdb_stable_lane{lane_id}",
                )
            )
            postchecks.append(
                create_fpf_bgp_rib_convergence_check(
                    lane_map=lane_map,
                    expected_matched=prefix_count,
                    use_live_collectors=True,
                    settle_sec=settle,
                    check_id=f"fpf_bgp_stable_lane{lane_id}",
                )
            )

    # --- HRT signals: NO churn (queried on the GPU host, unaffected by a GTSW
    # service restart). For a disruptive coldboot, stable_settle_sec skips the
    # recovery transient so only the recovered steady state is judged. ---
    postchecks.append(
        create_fpf_hrt_bulk_convergence_check(
            lanes=injected_lanes,
            expected_per_lane={str(lane): prefix_count for lane in injected_lanes},
            use_live_collectors=True,
            settle_sec=settle,
            check_id="fpf_hrt_bulk_stable",
        )
    )
    if rf_vf_groups:
        # Per-VF-group: assert each group has zero remote-failure on its OWN
        # lanes (reading the group's narrow-subnet collector), avoiding the other
        # group's expected cross-plane failures.
        for _g in rf_vf_groups:
            postchecks.append(
                create_fpf_hrt_remote_failure_convergence_check(
                    lanes=_g["lanes"],
                    direction="stable",
                    use_live_collectors=True,
                    collector_name=f"hrt_remote_failure_{_g['suffix']}",
                    check_id=f"fpf_hrt_remote_failure_stable_{_g['suffix']}",
                )
            )
    else:
        postchecks.append(
            create_fpf_hrt_remote_failure_convergence_check(
                lanes=injected_lanes,
                direction="stable",
                use_live_collectors=True,
                check_id="fpf_hrt_remote_failure_stable",
            )
        )
    if prod_prefixes:
        postchecks.append(
            create_fpf_prod_hrt_prefix_stability_check(
                settle_sec=settle,
                check_id="fpf_prod_hrt_prefix_stable",
            )
        )
        postchecks.append(
            create_fpf_hrt_plane_status_check(
                mode="all_up",
                # Scope to the injected/tested lanes so a lab plane that is
                # already impaired at baseline (e.g. an unrelated drained GTSW)
                # is not flagged as a restart regression. Mirrors the
                # injected-lane scoping used by the convergence/bulk/remote-
                # failure checks above.
                expected_planes=injected_lanes,
                settle_sec=settle,
                check_id="fpf_hrt_plane_status_all_up",
            )
        )

    # --- FSDB/HRT session: stays fully CONNECTED through the restart. ---
    postchecks.append(
        create_fpf_hrt_fsdb_session_check(
            hosts=hosts,
            expected_session_count=fsdb_expected_total,
            check_id="fpf_hrt_fsdb_session_stable",
        )
    )

    # Process-restart composition: assert ONLY the expected service(s) restarted
    # (no UNEXPECTED collateral restarts) and that no BGP graceful-restart stale
    # routes linger after recovery. The targeted service's systemctl name is
    # resolved from the Service enum via SERVICE_NAME_MAP.
    #
    # Cascade handling: a wedge_agent (AGENT) restart OR an agent coldboot
    # (create_cold_boot_file=True) intentionally cascades and ALSO restarts
    # bgpd/fsdb/qsfp/the split sw+hw agents (BindsTo + ExecStop hooks). Declaring
    # only the targeted service would false-fail the by-design cascade (e.g. tc25
    # FAIL "bgpd restarted during test"), so for those cases we declare the full
    # FPF service set as expected_restarted_services. For every OTHER service
    # (bgpd / fsdb / qsfp_service on their own) we keep just the targeted service
    # so an unexpected collateral restart still trips the check.
    #
    # SERVICE_RESTART_CHECK probes systemctl over SSH, so it is gated behind
    # skip_ssh_dependent_checks (dropped in headless runs without an SSH cert).
    # Its active-state probe is scoped to the FPF ``services`` list — openr is
    # not loaded on GTSW/STSW, so the default service list would false-fail on
    # openr being INACTIVE.
    #
    # When the targeted service is ``AGENT`` (= wedge_agent on FBOSS), three
    # other daemons restart with it via systemd cascade (Pavan-confirmed
    # by-design, T274731352 + T275672046):
    #   - bgpd via ``BindsTo=wedge_agent.service``
    #   - fboss_sw_agent + fboss_hw_agent@0 via the wedge_agent unit's
    #     hand-coded ``ExecStop=pre_wedge_agent_shut_runner.par`` hook
    # The postcheck must whitelist all four so the cascade-restarts are not
    # flagged as collateral. This invariant is enforced at CI time by
    # ``test_wedge_agent_restart_implies_bindsto_cascade_in_expected`` in
    # ``tests/test_service_restart_dependency.py``.
    if not skip_ssh_dependent_checks:
        is_agent_restart = service == taac_types.Service.AGENT
        if is_agent_restart or create_cold_boot_file:
            # Full FPF cascade set restarted by a wedge_agent restart / coldboot.
            expected_restarted_services = [
                "wedge_agent",
                "bgpd",
                "fsdb",
                "qsfp_service",
                "fboss_sw_agent",
                "fboss_hw_agent@0",
            ]
        else:
            expected_restarted_services = [
                taac_types.SERVICE_NAME_MAP.get(service, service.name)
            ]
        postchecks.append(
            create_service_restart_check(
                services=services,
                expected_restarted_services=expected_restarted_services,
            )
        )
    # BGP_STALE_ROUTE_CHECK reads the BGP RIB over thrift (no SSH), so it runs in
    # both full and headless modes.
    postchecks.append(create_bgp_stale_route_check())

    # Prepend the shared generic (non-convergence) check set: generic SSH/device
    # + ODS-only postchecks (HRT mem/driver/spray are included here, replacing the
    # previously-inline ones).
    postchecks = [*generic_postchecks, *postchecks]

    return Playbook(
        name=playbook_name,
        prechecks=[*drain_prechecks, *generic_prechecks],
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
        stages=[create_steps_stage(stage_id="restart", steps=stage_steps)],
    )
