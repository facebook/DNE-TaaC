# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Arista EBB scale TestConfig builder.

Builds a full-scale BGP++ TestConfig for an Arista EBB device with BGP MON
peers, exercising IBGP/EBGP route advertisement, route registry runtime
updates, BGP session/route oscillations, attribute churn, plane drain/undrain,
multipath group oscillations, FAUU drain/undrain, cold start, and BGP restart
stages. Used to longevity-test EBB BGP++ at production peer/route scale.
"""

import json

from taac.constants import (
    BgpPlusPlusProfile,
    DEFAULT_LOCAL_LINK,
    DEFAULT_OPENR_START_IPV4S,
    DEFAULT_OPENR_START_IPV6S,
    DEFAULT_OTHER_LINK,
    Gigabyte,
    OpenRRouteAction,
)
from taac.health_checks.healthcheck_definitions import (
    create_bgp_route_count_verification_check,
    create_bgp_tcpdump_check,
)
from taac.playbooks.playbook_definitions import (
    build_arista_ebb_scale_playbook,
)
from taac.routing.ebb.ebb_bgp_plus_plus_test_config.common_health_checks import (
    create_standard_postchecks,
    create_standard_prechecks,
    create_standard_snapshot_checks,
)
from taac.routing.ebb.ebb_bgp_plus_plus_test_config.common_periodic_tasks import (
    create_longevity_periodic_tasks,
    create_standard_periodic_tasks,
)
from taac.routing.ebb.ebb_bgp_plus_plus_test_config.ixia_config_for_ebb_scale import (
    create_ebb_scale_basic_port_configs,
)
from taac.stages.stage_definitions import (
    create_attribute_churn_stage,
    create_bgp_igp_instability_unresolvable_pnhs_stage,
    create_bgp_restart_test_stage,
    create_bgp_session_oscillation_stage,
    create_cold_start_test_stage,
    create_fauu_drain_undrain_stage,
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
    create_bgp_instability_setup_steps,
    create_bgp_restart_setup_steps,
    create_longevity_step,
    create_openr_route_action_step,
    create_route_registry_prefix_list_setup_steps,
    create_run_task_step,
    create_tcpdump_step,
)
from taac.task_definitions import create_openr_route_action_task
from taac.utils.arista_utils import interface_name_to_short_format
from taac.utils.hardware_capacity_utils import (
    get_postcheck_thresholds,
    get_precheck_thresholds,
)
from taac.test_as_a_config.types import Endpoint, TestConfig


def test_config_for_bgp_plus_plus_on_ebb_arista_with_bgp_mon(
    test_config_name,
    device_name,
    peergroup_ibgp_v6,
    peergroup_ebgp_v6,
    peergroup_ibgp_v4,
    peergroup_ebgp_v4,
    peergroup_bgp_mon,
    ixia_interface_mimic_ebgp,
    ixia_interface_mimic_ibgp,
    ixia_interface_mimic_bgp_mon,
    ibgp_remote_as,
    ebgp_remote_as,
    bgp_mon_remote_as,
    ebgp_peer_count_v4,
    ebgp_peer_count_v6,
    bgp_mon_peer_count,
    unqiue_prefix_limit,
    total_path_limit,
    ixia_ebgp_ic_parent_network_v6,
    ixia_ebgp_ic_parent_network_v4,
    ixia_ibgp_ic_parent_network_v6_dc_plane1,
    ixia_ibgp_ic_parent_network_v6_dc_plane2,
    ixia_ibgp_ic_parent_network_v6_dc_plane3,
    ixia_ibgp_ic_parent_network_v6_dc_plane4,
    ixia_ibgp_ic_parent_network_v6_mp_plane1,
    ixia_ibgp_ic_parent_network_v6_mp_plane2,
    ixia_ibgp_ic_parent_network_v6_mp_plane3,
    ixia_ibgp_ic_parent_network_v6_mp_plane4,
    ixia_ibgp_ic_parent_network_v4_dc_plane1,
    ixia_ibgp_ic_parent_network_v4_dc_plane2,
    ixia_ibgp_ic_parent_network_v4_dc_plane3,
    ixia_ibgp_ic_parent_network_v4_dc_plane4,
    ixia_ibgp_ic_parent_network_v4_mp_plane1,
    ixia_ibgp_ic_parent_network_v4_mp_plane2,
    ixia_ibgp_ic_parent_network_v4_mp_plane3,
    ixia_ibgp_ic_parent_network_v4_mp_plane4,
    ixia_bgp_mon_ic_parent_network,
    ixia_ebgp_communities,
    ixia_ibgp_communities,
    ebgp_ingress_policy_name,
    ebgp_egress_policy_name,
    ibgp_ingress_policy_name,
    ibgp_egress_policy_name,
    bgp_mon_ingress_policy_name,
    bgp_mon_egress_policy_name,
    ibgp_peer_scale_per_plane,
    local_as_4_byte,
    bgp_router_id,
    profile: BgpPlusPlusProfile = BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
    ibgp_peer_to_drain_per_plane: int = 2,
    ebgp_peer_to_drain: int = 4,
    bgpd_restart_no_of_interations: int = 1,
    log_collection_timeout: int = 600,
    oss_mock_device_data=None,
    host_os_type_map=None,
    host_driver_args=None,
    direct_ixia_connections=None,
    multiport_ibgp_sessions: bool = False,
    ixia_interface_mimic_ibgp_plane1: str | None = None,
    ixia_interface_mimic_ibgp_plane2: str | None = None,
    ixia_interface_mimic_ibgp_plane3: str | None = None,
    ixia_interface_mimic_ibgp_plane4: str | None = None,
):
    """Build a full-scale Arista EBB BGP++ TestConfig with BGP MON peer support.

    Wires up IBGP + EBGP + BGP MON peering across 4 planes (DC + MP), then
    composes a multi-stage longevity playbook: cold start, route registry
    runtime updates, BGP/IGP instability + unresolvable PNHs, BGP session
    oscillation (plain + plane-aware), route oscillations, route storm,
    attribute churn, multipath group oscillation, FAUU/plane drain-undrain,
    and BGP restart. Used for sustained EBB BGP++ stress testing on Arista
    hardware at production peer/route scale.

    Args:
        test_config_name: Final name of the produced TestConfig.
        device_name: DUT hostname (Arista EBB device).
        peergroup_*: Per-AFI/SAFI peer-group names for IBGP/EBGP/BGP MON.
        ixia_interface_mimic_*: IXIA port names used as peer endpoints.
        ibgp_remote_as / ebgp_remote_as / bgp_mon_remote_as: Remote ASNs.
        ebgp_peer_count_v4 / ebgp_peer_count_v6 / bgp_mon_peer_count: IXIA peer
            counts per AFI.
        unqiue_prefix_limit / total_path_limit: Route scale knobs (note the
            historical typo in `unqiue_*` parameter names).
        ixia_*_ic_parent_network_v6/v4_*: Parent networks for IXIA-side prefix
            generation, partitioned by plane (DC plane1..4, MP plane1..4).
        ixia_*_communities: Communities advertised by IXIA peers.
        *_ingress_policy_name / *_egress_policy_name: COOP BGP policy names.
        ibgp_peer_scale_per_plane: IBGP peer count per plane (scales 8 ways).
        local_as_4_byte: DUT local AS.
        bgp_router_id: DUT BGP router-id.
        profile: BgpPlusPlusProfile flavor (with/without Open/R).
        ibgp_peer_to_drain_per_plane / ebgp_peer_to_drain: Peer counts for
            drain-stage scenarios.
        bgpd_restart_no_of_interations: Iteration count for the BGP restart
            stage (historical typo preserved).
        log_collection_timeout: Per-stage log collection timeout (seconds).
        oss_mock_device_data / host_os_type_map / host_driver_args: Optional
            overrides for OSS mock harness wiring.
        direct_ixia_connections: Optional direct IXIA-port connection list.
        multiport_ibgp_sessions: When True, splits IBGP across plane-specific
            IXIA ports (requires `ixia_interface_mimic_ibgp_plane{1..4}`).

    Returns:
        TestConfig: The fully constructed Arista EBB scale TestConfig
        (consumed by callers via `testconfigs.routing.ebb`).
    """
    # Get pre-check and post-check hardware capacity thresholds
    precheck_thresholds = get_precheck_thresholds()
    postcheck_thresholds = get_postcheck_thresholds()
    total_session_count = (
        ebgp_peer_count_v6
        + ebgp_peer_count_v4
        + bgp_mon_peer_count
        + ibgp_peer_scale_per_plane * 4  # 4 planes for v4 remote EB
        + ibgp_peer_scale_per_plane * 4  # 4 planes for v6 remote EB
        + ibgp_peer_scale_per_plane * 4  # 4 planes for v4 remote Mid Point
        + ibgp_peer_scale_per_plane * 4  # 4 planes for v6 remote Mid Point
        - 3
    )
    # Build ixia_ports list based on multiport mode
    if multiport_ibgp_sessions:
        ixia_ports = [
            ixia_interface_mimic_ebgp,
            ixia_interface_mimic_ibgp_plane1,
            ixia_interface_mimic_ibgp_plane2,
            ixia_interface_mimic_ibgp_plane3,
            ixia_interface_mimic_ibgp_plane4,
        ] + ([ixia_interface_mimic_bgp_mon] if bgp_mon_peer_count > 0 else [])
    else:
        ixia_ports = [
            ixia_interface_mimic_ebgp,
            ixia_interface_mimic_ibgp,
        ] + ([ixia_interface_mimic_bgp_mon] if bgp_mon_peer_count > 0 else [])

    return TestConfig(
        name=test_config_name,
        skip_ixia_protocol_verification=True,
        # ixia_protocol_verification_timeout=900,
        log_collection_timeout=log_collection_timeout,
        basset_pool="dne.test",
        endpoints=[
            Endpoint(
                name=device_name,
                dut=True,
                # pyrefly: ignore [bad-argument-type]
                ixia_ports=ixia_ports,
                direct_ixia_connections=(
                    direct_ixia_connections if direct_ixia_connections else []
                ),
            ),
        ],
        host_driver_args=host_driver_args,
        oss_mock_device_data=oss_mock_device_data,
        host_os_type_map=host_os_type_map,
        startup_checks=[],
        setup_tasks=(
            [
                create_openr_route_action_task(
                    device_name=device_name,
                    start_ipv4s=DEFAULT_OPENR_START_IPV4S,
                    start_ipv6s=DEFAULT_OPENR_START_IPV6S,
                    local_link=DEFAULT_LOCAL_LINK,
                    other_link=DEFAULT_OTHER_LINK,
                    action=OpenRRouteAction.INJECT.value,
                    count=63,
                    step=2,
                    description="Inject Open/R routes during test setup",
                ),
            ]
            if profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R
            else []
        ),
        teardown_tasks=[],
        # Deprecated - define at playbook level
        # prechecks=[],
        # postchecks=[],
        # snapshot_checks=[],
        basic_port_configs=create_ebb_scale_basic_port_configs(
            device_name=device_name,
            ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
            ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
            ixia_interface_mimic_bgp_mon=ixia_interface_mimic_bgp_mon,
            ebgp_peer_count_v6=ebgp_peer_count_v6,
            ebgp_peer_count_v4=ebgp_peer_count_v4,
            ebgp_peer_to_drain=ebgp_peer_to_drain,
            ibgp_peer_scale_per_plane=ibgp_peer_scale_per_plane,
            ibgp_peer_to_drain_per_plane=ibgp_peer_to_drain_per_plane,
            bgp_mon_peer_count=bgp_mon_peer_count,
            ebgp_remote_as=ebgp_remote_as,
            ibgp_remote_as=ibgp_remote_as,
            bgp_mon_remote_as=bgp_mon_remote_as,
            ixia_ebgp_ic_parent_network_v6=ixia_ebgp_ic_parent_network_v6,
            ixia_ebgp_ic_parent_network_v4=ixia_ebgp_ic_parent_network_v4,
            ixia_ibgp_ic_parent_network_v6_dc_plane1=ixia_ibgp_ic_parent_network_v6_dc_plane1,
            ixia_ibgp_ic_parent_network_v6_dc_plane2=ixia_ibgp_ic_parent_network_v6_dc_plane2,
            ixia_ibgp_ic_parent_network_v6_dc_plane3=ixia_ibgp_ic_parent_network_v6_dc_plane3,
            ixia_ibgp_ic_parent_network_v6_dc_plane4=ixia_ibgp_ic_parent_network_v6_dc_plane4,
            ixia_ibgp_ic_parent_network_v6_mp_plane1=ixia_ibgp_ic_parent_network_v6_mp_plane1,
            ixia_ibgp_ic_parent_network_v6_mp_plane2=ixia_ibgp_ic_parent_network_v6_mp_plane2,
            ixia_ibgp_ic_parent_network_v6_mp_plane3=ixia_ibgp_ic_parent_network_v6_mp_plane3,
            ixia_ibgp_ic_parent_network_v6_mp_plane4=ixia_ibgp_ic_parent_network_v6_mp_plane4,
            ixia_ibgp_ic_parent_network_v4_dc_plane1=ixia_ibgp_ic_parent_network_v4_dc_plane1,
            ixia_ibgp_ic_parent_network_v4_dc_plane2=ixia_ibgp_ic_parent_network_v4_dc_plane2,
            ixia_ibgp_ic_parent_network_v4_dc_plane3=ixia_ibgp_ic_parent_network_v4_dc_plane3,
            ixia_ibgp_ic_parent_network_v4_dc_plane4=ixia_ibgp_ic_parent_network_v4_dc_plane4,
            ixia_ibgp_ic_parent_network_v4_mp_plane1=ixia_ibgp_ic_parent_network_v4_mp_plane1,
            ixia_ibgp_ic_parent_network_v4_mp_plane2=ixia_ibgp_ic_parent_network_v4_mp_plane2,
            ixia_ibgp_ic_parent_network_v4_mp_plane3=ixia_ibgp_ic_parent_network_v4_mp_plane3,
            ixia_ibgp_ic_parent_network_v4_mp_plane4=ixia_ibgp_ic_parent_network_v4_mp_plane4,
            ixia_bgp_mon_ic_parent_network=ixia_bgp_mon_ic_parent_network,
            profile=profile,
            multiport_ibgp_sessions=multiport_ibgp_sessions,
            ixia_interface_mimic_ibgp_plane1=ixia_interface_mimic_ibgp_plane1,
            ixia_interface_mimic_ibgp_plane2=ixia_interface_mimic_ibgp_plane2,
            ixia_interface_mimic_ibgp_plane3=ixia_interface_mimic_ibgp_plane3,
            ixia_interface_mimic_ibgp_plane4=ixia_interface_mimic_ibgp_plane4,
        ),
        playbooks=[
            build_arista_ebb_scale_playbook(
                periodic_tasks=[],
                prechecks=create_standard_prechecks(
                    peergroup_ibgp_v6=peergroup_ibgp_v6,
                    peergroup_ibgp_v4=peergroup_ibgp_v4,
                    precheck_thresholds=precheck_thresholds,
                    expected_established_sessions=total_session_count,
                    check_ibgp_pnh=(
                        profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R
                    ),
                ),
                name="test_1_min_longevity",
                # postchecks=[
                #     PointInTimeHealthCheck(
                #         name=hc_types.CheckName.BGP_TCPDUMP_CHECK,
                #         check_params=Params(
                #             json_params=json.dumps(
                #                 {
                #                     "expected_message_types": ["KEEPALIVE"],
                #                     "unexpected_message_types": ["UPDATE"],
                #                     "cleanup_capture_file": False,
                #                     "expected_last_mod_time": 60,
                #                 }
                #             )
                #         ),
                #     ),
                # ],
                stages=[
                    create_steps_stage(
                        steps=[
                            # create_tcpdump_step(
                            #     device_name=device_name,
                            #     mode="start_capture",
                            #     message_type="Update",
                            # ),
                            create_longevity_step(
                                duration=5,
                            ),
                            # create_tcpdump_step(
                            #     device_name=device_name,
                            #     mode="stop_capture",
                            #     capture_file_path="/tmp/bgp_capture.txt",
                            #     description="Stop tcpdump capture and keep file",
                            # ),
                        ],
                    )
                ],
            ),
            build_arista_ebb_scale_playbook(
                name="bgp_daemon_restart_test_playbook",
                setup_steps=create_bgp_restart_setup_steps(device_name=device_name),
                prechecks=create_standard_prechecks(
                    peergroup_ibgp_v6=peergroup_ibgp_v6,
                    peergroup_ibgp_v4=peergroup_ibgp_v4,
                    precheck_thresholds=precheck_thresholds,
                    cpu_baseline=6.0,
                    check_ibgp_pnh=(
                        profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R
                    ),
                ),
                postchecks=create_standard_postchecks(
                    postcheck_thresholds=postcheck_thresholds,
                    expected_restarted_services=["Bgp"],
                    restart_start_time_jq_var="daemon_restart_time",
                ),
                snapshot_checks=create_standard_snapshot_checks(),
                periodic_tasks=create_standard_periodic_tasks(
                    device_name=device_name,
                    memory_threshold=Gigabyte.GIG_5.value,
                    cpu_util_terminate_on_error=False,
                    memory_terminate_on_error=False,
                ),
                stages=[
                    # BGP restart with CPU monitoring and profiling
                    # Note: enable_perf_profiling=True works even if flamegraph tools
                    # are not installed on device. Profiling data and top functions
                    # reports are uploaded to Everpaste. Flame graphs can be generated
                    # locally from downloaded data using generate_flamegraph_local tool.
                    create_bgp_restart_test_stage(
                        device_name=device_name,
                        enable_thread_cpu_monitoring=False,
                        thread_name_filter=[
                            "fi",  # Fiber threads
                            # "pe",  # PeerManager threads
                            # "ri",  # RIB threads
                        ],
                        enable_offcpu_profiling=False,
                        enable_perf_profiling=False,  # Generates flame graphs + phased analysis
                        enable_bgp_events=True,  # Annotates BGP events on timeline
                        enable_socket_monitoring=False,  # Monitors socket stats
                    ),
                ],
            ),
            # BGP daemon restart with update groups and serialize group PDU enabled
            # This playbook enables both features before performing the restart test
            build_arista_ebb_scale_playbook(
                name="bgp_daemon_restart_with_update_groups_and_serialize_playbook",
                setup_steps=create_bgp_restart_setup_steps(device_name=device_name)
                + [
                    create_run_task_step(
                        task_name="set_bgp_setting_config",
                        params_dict={
                            "hostname": device_name,
                            "settings": {
                                "enable_update_group": True,
                                "enable_serialize_group_pdu": True,
                            },
                            "reload_bgp": False,  # Don't reload, we're restarting anyway
                        },
                        description="Enable update groups and serialize group PDU features",
                    ),
                ],
                prechecks=create_standard_prechecks(
                    peergroup_ibgp_v6=peergroup_ibgp_v6,
                    peergroup_ibgp_v4=peergroup_ibgp_v4,
                    precheck_thresholds=precheck_thresholds,
                    cpu_baseline=6.0,
                    check_ibgp_pnh=(
                        profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R
                    ),
                ),
                postchecks=create_standard_postchecks(
                    postcheck_thresholds=postcheck_thresholds,
                    expected_restarted_services=["Bgp"],
                    restart_start_time_jq_var="daemon_restart_time",
                ),
                snapshot_checks=create_standard_snapshot_checks(),
                periodic_tasks=create_standard_periodic_tasks(
                    device_name=device_name,
                    memory_threshold=Gigabyte.GIG_5.value,
                    cpu_util_terminate_on_error=False,
                    memory_terminate_on_error=False,
                ),
                stages=[
                    create_bgp_restart_test_stage(
                        device_name=device_name,
                        enable_thread_cpu_monitoring=False,
                        thread_name_filter=[
                            "fi",  # Fiber threads
                        ],
                        enable_offcpu_profiling=False,
                        enable_perf_profiling=False,
                        enable_bgp_events=True,
                        enable_socket_monitoring=False,
                    ),
                ],
            ),
            # BGP daemon restart with update groups enabled but serialize group PDU disabled
            # This playbook enables only update groups before performing the restart test
            build_arista_ebb_scale_playbook(
                name="bgp_daemon_restart_with_update_groups_only_playbook",
                setup_steps=create_bgp_restart_setup_steps(device_name=device_name)
                + [
                    create_run_task_step(
                        task_name="set_bgp_setting_config",
                        params_dict={
                            "hostname": device_name,
                            "settings": {
                                "enable_update_group": True,
                                "enable_serialize_group_pdu": False,
                            },
                            "reload_bgp": False,  # Don't reload, we're restarting anyway
                        },
                        description="Enable update groups only (serialize group PDU disabled)",
                    ),
                ],
                prechecks=create_standard_prechecks(
                    peergroup_ibgp_v6=peergroup_ibgp_v6,
                    peergroup_ibgp_v4=peergroup_ibgp_v4,
                    precheck_thresholds=precheck_thresholds,
                    cpu_baseline=6.0,
                    check_ibgp_pnh=(
                        profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R
                    ),
                ),
                postchecks=create_standard_postchecks(
                    postcheck_thresholds=postcheck_thresholds,
                    expected_restarted_services=["Bgp"],
                    restart_start_time_jq_var="daemon_restart_time",
                ),
                snapshot_checks=create_standard_snapshot_checks(),
                periodic_tasks=create_standard_periodic_tasks(
                    device_name=device_name,
                    memory_threshold=Gigabyte.GIG_5.value,
                    cpu_util_terminate_on_error=False,
                    memory_terminate_on_error=False,
                ),
                stages=[
                    create_bgp_restart_test_stage(
                        device_name=device_name,
                        enable_thread_cpu_monitoring=False,
                        thread_name_filter=[
                            "fi",  # Fiber threads
                        ],
                        enable_offcpu_profiling=False,
                        enable_perf_profiling=False,
                        enable_bgp_events=True,
                        enable_socket_monitoring=False,
                    ),
                ],
            ),
            build_arista_ebb_scale_playbook(
                name="bgp_cold_start_test_playbook",
                setup_steps=create_bgp_restart_setup_steps(device_name=device_name),
                prechecks=create_standard_prechecks(
                    peergroup_ibgp_v6=peergroup_ibgp_v6,
                    peergroup_ibgp_v4=peergroup_ibgp_v4,
                    precheck_thresholds=precheck_thresholds,
                    check_ibgp_pnh=(
                        profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R
                    ),
                ),
                postchecks=create_standard_postchecks(
                    postcheck_thresholds=postcheck_thresholds,
                    fail_on_eor_expired=False,
                    expected_restarted_services=["Bgp"],
                    restart_start_time_jq_var="daemon_restart_time",
                ),
                snapshot_checks=create_standard_snapshot_checks(),
                periodic_tasks=create_standard_periodic_tasks(
                    device_name=device_name,
                    memory_threshold=Gigabyte.GIG_5.value,
                    cpu_util_terminate_on_error=False,
                    memory_terminate_on_error=False,
                ),
                stages=[
                    create_cold_start_test_stage(
                        device_name=device_name,
                        enable_thread_cpu_monitoring=True,
                        thread_name_filter=[
                            "fi",  # Fiber threads
                            "pe",  # PeerManager threads
                            "ri",  # RIB threads
                        ],
                        enable_offcpu_profiling=False,
                        thread_cpu_monitoring_interval_seconds=2,
                        enable_perf_profiling=True,  # Generates flame graphs + phased analysis
                        enable_bgp_events=False,  # Annotates BGP events on timeline
                        enable_socket_monitoring=False,  # Monitors socket stats
                    ),
                ],
            ),
            build_arista_ebb_scale_playbook(
                name="bgp_igp_instability_pnh_metric_oscillation_playbook",
                setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
                prechecks=create_standard_prechecks(
                    peergroup_ibgp_v6=peergroup_ibgp_v6,
                    peergroup_ibgp_v4=peergroup_ibgp_v4,
                    precheck_thresholds=precheck_thresholds,
                    expected_established_sessions=total_session_count,
                    check_ibgp_pnh=(
                        profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R
                    ),
                ),
                postchecks=create_standard_postchecks(
                    postcheck_thresholds=postcheck_thresholds,
                    expected_message_types=["KEEPALIVE"],
                    unexpected_message_types=["NOTIFICATION", "OPEN"],
                    check_bgp_convergence=False,
                ),
                snapshot_checks=create_standard_snapshot_checks(),
                periodic_tasks=create_standard_periodic_tasks(
                    device_name=device_name,
                    memory_threshold=Gigabyte.GIG_5.value,
                    cpu_util_terminate_on_error=False,
                    memory_terminate_on_error=False,
                ),
                stages=[
                    create_steps_stage(
                        steps=[
                            create_tcpdump_step(
                                device_name=device_name,
                                mode="start_capture",
                                message_type="Keepalive|Open|Notification",
                            ),
                            # Perform metric oscillation using default Open/R route configuration
                            create_openr_route_action_step(
                                device_name=device_name,
                                start_ipv4s=DEFAULT_OPENR_START_IPV4S,
                                start_ipv6s=DEFAULT_OPENR_START_IPV6S,
                                local_link=DEFAULT_LOCAL_LINK,
                                other_link=DEFAULT_OTHER_LINK,
                                action=OpenRRouteAction.METRIC_OSCILLATION.value,
                                count=63,
                                step=2,
                                duration=3600,  # 2 minutes - change to 3600 for 1 hour
                                frequency=30,  # Every 30 seconds
                                description="Perform metric oscillation using default Open/R configuration",
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
            ),
            build_arista_ebb_scale_playbook(
                name="bgp_igp_instability_unresolvable_pnhs_playbook",
                setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
                prechecks=create_standard_prechecks(
                    peergroup_ibgp_v6=peergroup_ibgp_v6,
                    peergroup_ibgp_v4=peergroup_ibgp_v4,
                    precheck_thresholds=precheck_thresholds,
                    expected_established_sessions=total_session_count,
                    check_ibgp_pnh=(
                        profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R
                    ),
                ),
                postchecks=create_standard_postchecks(
                    postcheck_thresholds=postcheck_thresholds,
                    check_bgp_convergence=False,
                )
                + [
                    create_bgp_tcpdump_check(
                        expected_message_types=["UPDATE"],
                        unexpected_message_types=[],
                        cleanup_capture_file=False,
                        expected_last_mod_time=1740,  # 29 minutes
                    ),
                ],
                snapshot_checks=create_standard_snapshot_checks(),
                periodic_tasks=create_standard_periodic_tasks(
                    device_name=device_name,
                    memory_threshold=Gigabyte.GIG_5.value,
                    cpu_util_terminate_on_error=False,
                    memory_terminate_on_error=False,
                ),
                stages=[
                    create_bgp_igp_instability_unresolvable_pnhs_stage(
                        device_name=device_name,
                        start_ipv4s=[DEFAULT_OPENR_START_IPV4S[0]],
                        start_ipv6s=[DEFAULT_OPENR_START_IPV6S[0]],
                        tcp_dump_capture_interface=interface_name_to_short_format(
                            ixia_interface_mimic_bgp_mon
                        ),
                    )
                ],
            ),
            build_arista_ebb_scale_playbook(
                name="bgp_ebgp_session_oscillations_test_playbook",
                setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
                prechecks=create_standard_prechecks(
                    peergroup_ibgp_v6=peergroup_ibgp_v6,
                    peergroup_ibgp_v4=peergroup_ibgp_v4,
                    precheck_thresholds=precheck_thresholds,
                    expected_established_sessions=total_session_count,
                    check_ibgp_pnh=(
                        profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R
                    ),
                ),
                postchecks=create_standard_postchecks(
                    postcheck_thresholds=postcheck_thresholds,
                    check_bgp_convergence=False,
                ),
                snapshot_checks=create_standard_snapshot_checks(
                    skip_flap_check=True,
                    skip_uptime_check=True,
                ),
                periodic_tasks=create_standard_periodic_tasks(
                    device_name=device_name,
                    memory_threshold=Gigabyte.GIG_5.value,
                    cpu_util_terminate_on_error=False,
                    memory_terminate_on_error=False,
                ),
                stages=[
                    create_bgp_session_oscillation_stage(
                        ipv4_peer_regex=".*IPV4_EBGP$",  # IPv4 eBGP session regex (exclude DRAIN)
                        ipv6_peer_regex=".*IPV6_EBGP$",  # IPv6 eBGP session regex (exclude DRAIN)
                        test_duration_seconds=3600,  # 1 hour
                        uptime_seconds=30,
                        downtime_seconds=30,
                        sessions_per_cycle=70,  # Random subset of 70 eBGP sessions per cycle (split between v4/v6)
                        ipv4_session_count=ebgp_peer_count_v4,  # Total IPv4 eBGP sessions
                        ipv6_session_count=ebgp_peer_count_v6,  # Total IPv6 eBGP sessions
                    ),
                ],
            ),
            build_arista_ebb_scale_playbook(
                name="bgp_ebgp_continuous_oscillations_test_playbook",
                setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
                prechecks=create_standard_prechecks(
                    peergroup_ibgp_v6=peergroup_ibgp_v6,
                    peergroup_ibgp_v4=peergroup_ibgp_v4,
                    precheck_thresholds=precheck_thresholds,
                    expected_established_sessions=total_session_count,
                    check_ibgp_pnh=(
                        profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R
                    ),
                ),
                postchecks=create_standard_postchecks(
                    postcheck_thresholds=postcheck_thresholds,
                    check_bgp_convergence=False,
                ),
                snapshot_checks=create_standard_snapshot_checks(
                    skip_flap_check=True,
                    skip_uptime_check=True,
                ),
                periodic_tasks=create_standard_periodic_tasks(
                    device_name=device_name,
                    memory_threshold=Gigabyte.GIG_5.value,
                    cpu_util_terminate_on_error=False,
                    memory_terminate_on_error=False,
                ),
                stages=[
                    # Use cycle-based mode with very short duration to simulate continuous flapping
                    create_bgp_session_oscillation_stage(
                        ipv4_peer_regex=".*IPV4_EBGP$",  # IPv4 eBGP session regex (exclude DRAIN)
                        ipv6_peer_regex=".*IPV6_EBGP$",  # IPv6 eBGP session regex (exclude DRAIN)
                        test_duration_seconds=3600,  # 1 hour
                        uptime_seconds=30,
                        downtime_seconds=30,
                        sessions_per_cycle=ebgp_peer_count_v4
                        + ebgp_peer_count_v6,  # All eBGP sessions per cycle
                        ipv4_session_count=ebgp_peer_count_v4,  # Total IPv4 eBGP sessions
                        ipv6_session_count=ebgp_peer_count_v6,  # Total IPv6 eBGP sessions
                    ),
                ],
            ),
            build_arista_ebb_scale_playbook(
                name="bgp_ibgp_tornado_plane_oscillations_test_playbook",
                setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
                prechecks=create_standard_prechecks(
                    peergroup_ibgp_v6=peergroup_ibgp_v6,
                    peergroup_ibgp_v4=peergroup_ibgp_v4,
                    precheck_thresholds=precheck_thresholds,
                    expected_established_sessions=total_session_count,
                    check_ibgp_pnh=(
                        profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R
                    ),
                ),
                postchecks=create_standard_postchecks(
                    postcheck_thresholds=postcheck_thresholds,
                    check_bgp_convergence=False,
                ),
                snapshot_checks=create_standard_snapshot_checks(
                    skip_flap_check=True,
                    skip_uptime_check=True,
                ),
                periodic_tasks=create_standard_periodic_tasks(
                    device_name=device_name,
                    memory_threshold=Gigabyte.GIG_5.value,
                    cpu_util_terminate_on_error=False,
                    memory_terminate_on_error=False,
                ),
                stages=[
                    create_plane_aware_bgp_session_oscillation_stage(
                        ipv4_peer_regex=".*IPV4_IBGP.*",  # IPv4 iBGP session regex
                        ipv6_peer_regex=".*IPV6_IBGP.*",  # IPv6 iBGP session regex
                        test_duration_seconds=3600,  # 1 hour
                        uptime_seconds=30,
                        downtime_seconds=30,
                        sessions_per_plane=16,  # Number of sessions to disrupt per tornado plane
                        ipv4_sessions_per_plane=ibgp_peer_scale_per_plane,  # Total IPv4 sessions per plane
                        ipv6_sessions_per_plane=ibgp_peer_scale_per_plane,  # Total IPv6 sessions per plane
                        tornado_planes=[1, 2, 3, 4],  # Tornado planes to cycle through
                        session_type="both",  # Target both EB and MP sessions
                    ),
                ],
            ),
            build_arista_ebb_scale_playbook(
                name="bgp_ibgp_tornado_plane_continuous_flapping_test_playbook",
                setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
                prechecks=create_standard_prechecks(
                    peergroup_ibgp_v6=peergroup_ibgp_v6,
                    peergroup_ibgp_v4=peergroup_ibgp_v4,
                    precheck_thresholds=precheck_thresholds,
                    expected_established_sessions=total_session_count,
                    check_ibgp_pnh=(
                        profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R
                    ),
                ),
                postchecks=create_standard_postchecks(
                    postcheck_thresholds=postcheck_thresholds,
                ),
                snapshot_checks=create_standard_snapshot_checks(
                    skip_flap_check=True,
                    skip_uptime_check=True,
                ),
                periodic_tasks=create_standard_periodic_tasks(
                    device_name=device_name,
                    memory_threshold=Gigabyte.GIG_5.value,
                    cpu_util_terminate_on_error=False,
                    memory_terminate_on_error=False,
                ),
                stages=[
                    # Use cycle-based mode with very short cycles to simulate continuous flapping
                    create_plane_aware_bgp_session_oscillation_stage(
                        ipv4_peer_regex=".*IPV4_IBGP.*",  # IPv4 iBGP session regex
                        ipv6_peer_regex=".*IPV6_IBGP.*",  # IPv6 iBGP session regex
                        test_duration_seconds=3600,  # 1 hour
                        uptime_seconds=30,
                        downtime_seconds=30,
                        sessions_per_plane=ibgp_peer_scale_per_plane,  # Disrupt all sessions per plane
                        ipv4_sessions_per_plane=ibgp_peer_scale_per_plane,  # Total IPv4 sessions per plane
                        ipv6_sessions_per_plane=ibgp_peer_scale_per_plane,  # Total IPv6 sessions per plane
                        tornado_planes=[1, 2, 3, 4],  # Tornado planes for cycling
                        session_type="both",  # Target both EB and MP sessions
                    ),
                ],
            ),
            build_arista_ebb_scale_playbook(
                name="bgp_ibgp_tornado_eb_only_oscillations_test_playbook",
                setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
                prechecks=create_standard_prechecks(
                    peergroup_ibgp_v6=peergroup_ibgp_v6,
                    peergroup_ibgp_v4=peergroup_ibgp_v4,
                    precheck_thresholds=precheck_thresholds,
                    expected_established_sessions=total_session_count,
                    check_ibgp_pnh=(
                        profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R
                    ),
                ),
                postchecks=create_standard_postchecks(
                    postcheck_thresholds=postcheck_thresholds,
                ),
                snapshot_checks=create_standard_snapshot_checks(
                    skip_flap_check=True,
                    skip_uptime_check=True,
                ),
                periodic_tasks=create_standard_periodic_tasks(
                    device_name=device_name,
                    memory_threshold=Gigabyte.GIG_5.value,
                    cpu_util_terminate_on_error=False,
                    memory_terminate_on_error=False,
                ),
                stages=[
                    create_plane_aware_bgp_session_oscillation_stage(
                        ipv4_peer_regex=".*IPV4_IBGP.*",  # IPv4 iBGP session regex
                        ipv6_peer_regex=".*IPV6_IBGP.*",  # IPv6 iBGP session regex
                        test_duration_seconds=3600,  # 1 hour
                        uptime_seconds=30,
                        downtime_seconds=30,
                        sessions_per_plane=16,  # Number of sessions to disrupt per tornado plane
                        ipv4_sessions_per_plane=ibgp_peer_scale_per_plane,  # Total IPv4 sessions per plane
                        ipv6_sessions_per_plane=ibgp_peer_scale_per_plane,  # Total IPv6 sessions per plane
                        tornado_planes=[1, 2, 3, 4],  # Tornado planes to cycle through
                        session_type="eb",  # Target only EB (Edge Border) sessions
                    ),
                ],
            ),
            build_arista_ebb_scale_playbook(
                name="bgp_ibgp_tornado_mp_only_continuous_flapping_test_playbook",
                setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
                prechecks=create_standard_prechecks(
                    peergroup_ibgp_v6=peergroup_ibgp_v6,
                    peergroup_ibgp_v4=peergroup_ibgp_v4,
                    precheck_thresholds=precheck_thresholds,
                    expected_established_sessions=total_session_count,
                    check_ibgp_pnh=(
                        profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R
                    ),
                ),
                postchecks=create_standard_postchecks(
                    postcheck_thresholds=postcheck_thresholds,
                ),
                snapshot_checks=create_standard_snapshot_checks(
                    skip_flap_check=True,
                    skip_uptime_check=True,
                ),
                periodic_tasks=create_standard_periodic_tasks(
                    device_name=device_name,
                    memory_threshold=Gigabyte.GIG_5.value,
                    cpu_util_terminate_on_error=False,
                    memory_terminate_on_error=False,
                ),
                stages=[
                    # Use cycle-based mode with MP-only sessions
                    create_plane_aware_bgp_session_oscillation_stage(
                        ipv4_peer_regex=".*IPV4_IBGP.*",  # IPv4 iBGP session regex
                        ipv6_peer_regex=".*IPV6_IBGP.*",  # IPv6 iBGP session regex
                        test_duration_seconds=1800,  # 30 minutes (shorter for MP-only test)
                        uptime_seconds=20,
                        downtime_seconds=10,
                        sessions_per_plane=ibgp_peer_scale_per_plane,  # Disrupt all sessions per plane
                        ipv4_sessions_per_plane=ibgp_peer_scale_per_plane,  # Total IPv4 sessions per plane
                        ipv6_sessions_per_plane=ibgp_peer_scale_per_plane,  # Total IPv6 sessions per plane
                        tornado_planes=[1, 2, 3, 4],  # Tornado planes for cycling
                        session_type="mp",  # Target only MP (MidPlane) sessions
                    ),
                ],
            ),
            build_arista_ebb_scale_playbook(
                name="bgp_ebgp_route_oscillations",
                setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
                prechecks=create_standard_prechecks(
                    peergroup_ibgp_v6=peergroup_ibgp_v6,
                    peergroup_ibgp_v4=peergroup_ibgp_v4,
                    precheck_thresholds=precheck_thresholds,
                    expected_established_sessions=total_session_count,
                    check_ibgp_pnh=(
                        profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R
                    ),
                ),
                postchecks=create_standard_postchecks(
                    postcheck_thresholds=postcheck_thresholds,
                    check_bgp_convergence=False,
                ),
                snapshot_checks=create_standard_snapshot_checks(),
                periodic_tasks=create_standard_periodic_tasks(
                    device_name=device_name,
                    memory_threshold=Gigabyte.GIG_5.value,
                    cpu_util_terminate_on_error=False,
                    memory_terminate_on_error=False,
                ),
                stages=[
                    create_route_oscillations_stage(
                        device_name=device_name,
                        prefix_pool_regex=".*EBGP.*",
                        prefix_start_index=0,
                        prefix_end_index=500,
                    )
                ],
            ),
            build_arista_ebb_scale_playbook(
                name="bgp_ibgp_route_oscillations",
                setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
                prechecks=create_standard_prechecks(
                    peergroup_ibgp_v6=peergroup_ibgp_v6,
                    peergroup_ibgp_v4=peergroup_ibgp_v4,
                    precheck_thresholds=precheck_thresholds,
                    expected_established_sessions=total_session_count,
                    check_ibgp_pnh=(
                        profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R
                    ),
                ),
                postchecks=create_standard_postchecks(
                    postcheck_thresholds=postcheck_thresholds,
                    check_bgp_convergence=False,
                ),
                snapshot_checks=create_standard_snapshot_checks(),
                periodic_tasks=create_standard_periodic_tasks(
                    device_name=device_name,
                    memory_threshold=Gigabyte.GIG_5.value,
                    cpu_util_terminate_on_error=False,
                    memory_terminate_on_error=False,
                ),
                stages=[
                    create_route_oscillations_stage(
                        device_name=device_name,
                        prefix_pool_regex=".*IBGP.*",
                        prefix_start_index=0,
                        prefix_end_index=100,
                    )
                ],
            ),
            build_arista_ebb_scale_playbook(
                name="bgp_instability_attribute_churn",
                setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
                prechecks=create_standard_prechecks(
                    peergroup_ibgp_v6=peergroup_ibgp_v6,
                    peergroup_ibgp_v4=peergroup_ibgp_v4,
                    precheck_thresholds=precheck_thresholds,
                    expected_established_sessions=total_session_count,
                    check_ibgp_pnh=(
                        profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R
                    ),
                ),
                postchecks=create_standard_postchecks(
                    postcheck_thresholds=postcheck_thresholds,
                    check_bgp_convergence=False,
                ),
                snapshot_checks=create_standard_snapshot_checks(
                    skip_flap_check=True,
                    skip_uptime_check=True,
                ),
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
            ),
            build_arista_ebb_scale_playbook(
                name="bgp_instability_route_storm",
                setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
                postchecks=create_standard_postchecks(
                    postcheck_thresholds=postcheck_thresholds,
                    check_bgp_convergence=False,
                ),
                snapshot_checks=create_standard_snapshot_checks(
                    skip_flap_check=True,
                    skip_uptime_check=True,
                ),
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
                        prefix_end_index=10000,
                        device_group_regex=".*IBGP.*PLANE_1.*",
                        test_duration_seconds=3600,
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
            ),
            build_arista_ebb_scale_playbook(
                name="bgp_longevity_playbook",
                setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
                # prechecks=create_standard_prechecks(
                #     peergroup_ibgp_v6=peergroup_ibgp_v6,
                #     peergroup_ibgp_v4=peergroup_ibgp_v4,
                #     precheck_thresholds=precheck_thresholds,
                #     cpu_baseline=6.0,
                #     check_ibgp_pnh=(
                #         profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R
                #     ),
                # ),
                postchecks=create_standard_postchecks(
                    postcheck_thresholds=postcheck_thresholds,
                    check_bgp_convergence=False,
                ),
                snapshot_checks=create_standard_snapshot_checks(
                    skip_flap_check=True,
                    skip_uptime_check=True,
                ),
                periodic_tasks=create_longevity_periodic_tasks(
                    device_name=device_name,
                    route_churn_frequency=0,
                    local_pref_churn_frequency=0,
                    as_path_drain_frequency=0,
                    origin_churn_frequency=0,
                    community_churn_frequency=60,
                    igp_cost_frequency=0,
                    restart_peers_frequency=0,
                ),
                stages=[
                    create_steps_stage(
                        steps=[
                            create_longevity_step(
                                duration=86400,
                                description="Longevity soak for 86400 seconds",
                            ),
                        ]
                    )
                ],
            ),
            build_arista_ebb_scale_playbook(
                name="bgp_fauu_drain_undrain_playbook",
                setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
                prechecks=create_standard_prechecks(
                    peergroup_ibgp_v6=peergroup_ibgp_v6,
                    peergroup_ibgp_v4=peergroup_ibgp_v4,
                    precheck_thresholds=precheck_thresholds,
                    expected_established_sessions=total_session_count,
                    check_ibgp_pnh=(
                        profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R
                    ),
                ),
                postchecks=create_standard_postchecks(
                    postcheck_thresholds=postcheck_thresholds,
                    check_bgp_convergence=False,
                ),
                snapshot_checks=create_standard_snapshot_checks(
                    skip_flap_check=True,
                ),
                periodic_tasks=create_standard_periodic_tasks(
                    device_name=device_name,
                    memory_threshold=Gigabyte.GIG_5.value,
                    cpu_util_terminate_on_error=False,
                    memory_terminate_on_error=False,
                ),
                stages=[
                    create_fauu_drain_undrain_stage(
                        device_name=device_name,
                        prefix_pool_regex=".*EBGP.*",
                        prefix_end_index=96,
                        tcp_dump_capture_interface_ebgp=ixia_interface_mimic_ebgp,
                        tcp_dump_capture_interface_bgpmon=ixia_interface_mimic_bgp_mon,
                        tcp_dump_capture_interface_ibgp=ixia_interface_mimic_ibgp,
                        soak_time_seconds=300,
                    )
                ],
            ),
            build_arista_ebb_scale_playbook(
                name="bgp_plane_drain_undrain_playbook",
                setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
                prechecks=create_standard_prechecks(
                    peergroup_ibgp_v6=peergroup_ibgp_v6,
                    peergroup_ibgp_v4=peergroup_ibgp_v4,
                    precheck_thresholds=precheck_thresholds,
                    expected_established_sessions=total_session_count,
                    check_ibgp_pnh=(
                        profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R
                    ),
                ),
                postchecks=create_standard_postchecks(
                    postcheck_thresholds=postcheck_thresholds,
                    check_bgp_convergence=False,
                ),
                snapshot_checks=create_standard_snapshot_checks(
                    skip_flap_check=True,
                ),
                periodic_tasks=create_standard_periodic_tasks(
                    device_name=device_name,
                    memory_threshold=Gigabyte.GIG_5.value,
                    cpu_util_terminate_on_error=False,
                    memory_terminate_on_error=False,
                ),
                stages=[
                    *create_plane_drain_undrain_stage(
                        device_name=device_name,
                        prefix_pool_regex=".*IBGP.*PLANE_.*",
                        tcp_dump_capture_interface_bgpmon=ixia_interface_mimic_bgp_mon,
                        tcp_dump_capture_interface_ebgp=ixia_interface_mimic_ebgp,
                        tcp_dump_capture_interface_ibgp=ixia_interface_mimic_ibgp,
                        soak_time_seconds=1200,
                    )
                ],
            ),
            build_arista_ebb_scale_playbook(
                name="bgp_route_registry_prefix_list_runtime_update_playbook",
                setup_steps=create_route_registry_prefix_list_setup_steps(
                    device_name=device_name
                ),
                prechecks=create_standard_prechecks(
                    peergroup_ibgp_v6=peergroup_ibgp_v6,
                    peergroup_ibgp_v4=peergroup_ibgp_v4,
                    precheck_thresholds=precheck_thresholds,
                    cpu_baseline=6.0,
                    expected_established_sessions=total_session_count,
                    check_ibgp_pnh=(
                        profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R
                    ),
                )
                + [
                    create_bgp_route_count_verification_check(
                        json_params={
                            "descriptions_to_ignore": ["IBGP"],
                            "descriptions_to_check": ["EBGP"],
                            "direction": "received",
                            "expected_count": 650,
                            "policy_type": "post_policy",
                        },
                        check_id="startup_bgp_session_verification",
                    ),
                ],
                postchecks=create_standard_postchecks(
                    postcheck_thresholds=postcheck_thresholds,
                    fail_on_eor_expired=False,
                ),
                snapshot_checks=create_standard_snapshot_checks(),
                periodic_tasks=create_standard_periodic_tasks(
                    device_name=device_name,
                    memory_threshold=Gigabyte.GIG_5.value,
                    cpu_util_terminate_on_error=False,
                    memory_terminate_on_error=False,
                ),
                stages=[
                    create_route_registry_runtime_update_stage(
                        device_name=device_name,
                        ebgp_peer_description="EBGP",
                        prefix_pool_regex=".*EBGP.*",
                        soak_time_seconds=120,
                    )
                ],
            ),
            build_arista_ebb_scale_playbook(
                name="bgp_daemon_restart_test_no_mem_profile_playbook",
                setup_steps=create_bgp_restart_setup_steps(device_name=device_name),
                prechecks=create_standard_prechecks(
                    peergroup_ibgp_v6=peergroup_ibgp_v6,
                    peergroup_ibgp_v4=peergroup_ibgp_v4,
                    precheck_thresholds=precheck_thresholds,
                    cpu_baseline=6.0,
                    check_ibgp_pnh=(
                        profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R
                    ),
                ),
                postchecks=create_standard_postchecks(
                    postcheck_thresholds=postcheck_thresholds,
                    expected_restarted_services=["Bgp"],
                    restart_start_time_jq_var="daemon_restart_time",
                ),
                snapshot_checks=create_standard_snapshot_checks(),
                periodic_tasks=create_standard_periodic_tasks(
                    device_name=device_name,
                    memory_threshold=Gigabyte.GIG_5.value,
                    cpu_util_terminate_on_error=False,
                    memory_terminate_on_error=False,
                ),
                stages=[
                    create_bgp_restart_test_stage(device_name=device_name),
                ],
            ),
            # Test Case 5.2.4: BGP Instability - Multipath Group Oscillations
            # Check: https://docs.google.com/document/d/1Uz34DoQalHHwaR838YANitDR3GwLQXZIqNBW9W3nIk8/edit?tab=t.0#heading=h.gwh00bdildid
            build_arista_ebb_scale_playbook(
                name="bgp_multipath_group_oscillation_playbook",
                setup_steps=create_bgp_instability_setup_steps(device_name=device_name),
                prechecks=create_standard_prechecks(
                    peergroup_ibgp_v6=peergroup_ibgp_v6,
                    peergroup_ibgp_v4=peergroup_ibgp_v4,
                    precheck_thresholds=precheck_thresholds,
                    expected_established_sessions=total_session_count,
                    check_ibgp_pnh=(
                        profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R
                    ),
                ),
                postchecks=create_standard_postchecks(
                    postcheck_thresholds=postcheck_thresholds,
                    check_bgp_convergence=False,
                ),
                snapshot_checks=create_standard_snapshot_checks(skip_flap_check=True),
                periodic_tasks=create_standard_periodic_tasks(
                    device_name=device_name,
                    memory_threshold=Gigabyte.GIG_5.value,
                    cpu_util_terminate_on_error=False,
                    memory_terminate_on_error=False,
                ),
                stages=[
                    create_multipath_group_oscillation_stage(
                        ipv4_peer_regex=".*IPV4_EBGP$",
                        ipv6_peer_regex=".*IPV6_EBGP$",
                        ipv4_session_count=140,  # Baseline next-hop count (actual multipath group size)
                        ipv6_session_count=140,  # Baseline next-hop count (actual multipath group size)
                        test_duration_seconds=1800,  # 1 hour (~12 cycles)
                        oscillation_interval_seconds=280,  # 280s / 2 = 140s wait (GR 120s + 20s buffer)
                        min_peers_to_stop=1,
                        max_peers_to_stop=11,
                    ),
                ],
            ),
        ],
    )
