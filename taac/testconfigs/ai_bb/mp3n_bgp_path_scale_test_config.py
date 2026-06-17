# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict
"""MP3N RTSW BGP path-scale TestConfigs.

Builds BGP path-scale TestConfig variants for the MP3N RTSW testbed:
EXP1 (1.5M paths, 52-way ECMP), EXP3 (4M paths, 120-way ECMP), and EXP5
(4M paths, 240-way ECMP). Each variant configures Ixia uplink peering
against the RTSW DUT (with FTSW transit), validates BGP convergence,
prefix-limit handling, and CPU/memory under sustained path scale, and
exercises ixia prefix/session flap churn. Used to characterize MP3N
control-plane scaling ceilings.
"""

import json
from dataclasses import dataclass

from ixia.ixia import types as ixia_types
from taac.health_checks.healthcheck_definitions import (
    create_bgp_convergence_check,
    create_core_dumps_snapshot_check,
    create_cpu_utilization_check,
    create_memory_utilization_check,
    create_prefix_limit_check,
    create_service_restart_check,
    create_systemctl_active_state_check,
    create_unclean_exit_check,
)
from taac.playbooks.playbook_definitions import (
    build_mp3n_bgp_path_scale_playbook,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_ixia_api_step,
    create_longevity_step,
    create_service_convergence_step,
    create_service_interruption_step,
    create_toggle_ixia_prefix_session_flap_churn_step,
)
from taac.task_definitions import (
    create_coop_apply_patchers_task,
    create_coop_register_patcher_task,
    create_coop_unregister_patchers_task,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import (
    ConcurrentStep,
    Service,
    ServiceInterruptionTrigger,
    Task,
    TestConfig,
    # TrafficEndpoint,  # Commented out with traffic items
)


# Constants for MP3N BGP path scale test
PEERGROUP_RTSW_IXIA_PATH_SCALE_V6: str = "PEERGROUP_RTSW_IXIA_PATH_SCALE_V6"
PEERGROUP_RTSW_FTSW_V6: str = "PEERGROUP_RTSW_FTSW_V6"

MP3N_L1_CONFIG: ixia_types.L1Config = ixia_types.L1Config(
    enable_fcoe=True,
    flow_control_config=ixia_types.FlowControlConfig(
        pfc_prority_groups_config=ixia_types.PfcPriorityGroupsConfig(
            priority0_pfc_queue=ixia_types.PfcQueue.TWO,
            priority1_pfc_queue=ixia_types.PfcQueue.ONE,
            priority2_pfc_queue=ixia_types.PfcQueue.ZERO,
            priority3_pfc_queue=ixia_types.PfcQueue.THREE,
        ),
        enable_pfc_pause_delay=False,
    ),
)


@dataclass(frozen=True)
class PathScaleExperiment:
    """Defines a single BGP path scale experiment."""

    ecmp_width: int
    prefix_count: int

    @property
    def path_scale(self) -> int:
        return self.ecmp_width * self.prefix_count


@dataclass(frozen=True)
class UplinkConfig:
    """Configuration for an IXIA uplink interface that advertises routes."""

    interface: str
    ic_parent_network_v6: str
    mac_address: str
    peer_count: int | None = None  # None means use experiment.ecmp_width


@dataclass(frozen=True)
class DownlinkConfig:
    """Configuration for an IXIA downlink interface with listener-only peers."""

    interface: str
    ic_parent_network_v6: str
    mac_address: str
    peer_count: int
    peer_group_name: str  # Existing peer group (e.g. PEERGROUP_RTSW_FTSW_V6)
    remote_as_4byte: int  # Downlink AS (can differ from uplink AS)


# BGP path scale experiments to find the path limit
# Path scale = number of peers (ECMP width) * prefix count per peer
PATH_SCALE_EXPERIMENTS: dict[str, PathScaleExperiment] = {
    "exp1_1_5m_ecmp52": PathScaleExperiment(ecmp_width=52, prefix_count=15000),
    "exp3_4m_ecmp120": PathScaleExperiment(ecmp_width=120, prefix_count=10000),
    "exp5_4m_ecmp240": PathScaleExperiment(ecmp_width=240, prefix_count=6565),
}


def _get_rtsw_ixia_peer_group_tasks(device_name: str) -> list[Task]:
    """
    Returns tasks to create a test-specific peer group for path scale testing.
    Creates PEERGROUP_RTSW_IXIA_PATH_SCALE_V6 with policies that accept routes.
    """
    return [
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name="add_peer_group_patcher_PEERGROUP_RTSW_IXIA_PATH_SCALE_V6",
            task_name="add_peer_group_patcher",
            patcher_args={
                "name": PEERGROUP_RTSW_IXIA_PATH_SCALE_V6,
                "description": "BGP peering RTSW to IXIA, IPv6, path scale test",
                "disable_ipv4_afi": "True",
                "disable_ipv6_afi": "False",
                "ingress_policy_name": "PROPAGATE_RTSW_IXIA_PATH_SCALE_IN",
                "egress_policy_name": "PROPAGATE_RTSW_IXIA_PATH_SCALE_OUT",
                "bgp_peer_timers_hold_time_seconds": "30",
                "bgp_peer_timers_keep_alive_seconds": "10",
                "bgp_peer_timers_out_delay_seconds": "0",
                "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                "peer_tag": "IXIA",
                "max_routes": "900000",
                "warning_only": "True",
                "warning_limit": "0",
                "next_hop_self": "True",
                "is_confed_peer": "False",
                "is_passive": "False",
                "v4_over_v6_nexthop": "False",
                "link_bandwidth_bps": "auto",
            },
            py_func_name="add_peer_group_patcher",
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_RTSW_IXIA_PATH_SCALE_IN",
            task_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_RTSW_IXIA_PATH_SCALE_IN",
                "description": "Accept routes from IXIA for path scale test",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_RTSW_IXIA_PATH_SCALE_OUT",
            task_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_RTSW_IXIA_PATH_SCALE_OUT",
                "description": "Egress policy for IXIA path scale test",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_RTSW_IXIA_PATH_SCALE_IN_v6",
            task_name="add_bgp_policy_match_prefix_to_propagate_routes",
            patcher_args={
                "matching_prefix": "5000::/16",
                "in_stmt_name": "PROPAGATE_RTSW_IXIA_PATH_SCALE_IN",
                "out_stmt_name": "RANDOM",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
    ]


def _get_rtsw_ftsw_policy_tasks(device_name: str) -> list[Task]:
    """
    Returns tasks to create policy statements for the existing
    PEERGROUP_RTSW_FTSW_V6 peer group used by downlink listener peers.
    """
    return [
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_RTSW_FTSW_IN",
            task_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_RTSW_FTSW_IN",
                "description": "Accept routes for FTSW downlink",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_RTSW_FTSW_OUT",
            task_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_RTSW_FTSW_OUT",
                "description": "Egress policy for FTSW downlink",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_RTSW_FTSW_OUT_v6",
            task_name="add_bgp_policy_match_prefix_to_propagate_routes",
            patcher_args={
                "matching_prefix": "5000::/16",
                "in_stmt_name": "PROPAGATE_RTSW_FTSW_OUT",
                "out_stmt_name": "RANDOM",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
    ]


def test_config_for_mp3n_bgp_path_scale(
    test_config_name: str,
    device_name: str,
    uplink_configs: list[UplinkConfig],
    remote_as_4byte: int,
    experiment: PathScaleExperiment,
    downlink_configs: list[DownlinkConfig] | None = None,
    longevity_duration_min: int = 5,
    direct_ixia_connections: list[taac_types.DirectIxiaConnection] | None = None,
    basset_pool: str | None = None,
) -> TestConfig:
    """
    MP3N BGP path scale test configuration using multiple BGP peers.

    Tests BGP path scale limits by forming multiple iBGP peers on one or more
    interfaces. Each peer advertises the same prefix set, creating ECMP entries.
    Path scale = number of peers (ECMP width) * prefix count per peer.

    Uplink interfaces advertise routes using the test-created peer group
    PEERGROUP_RTSW_IXIA_PATH_SCALE_V6. Downlink interfaces are listener-only
    peers that use an existing peer group (e.g. PEERGROUP_RTSW_FTSW_V6) and
    do not advertise any routes.

    No traffic or warmboot. Just BGP sessions + route injection + longevity soak + cleanup.

    Args:
        test_config_name: Name identifier for the test config
        device_name: DUT hostname
        uplink_configs: List of uplink interface configurations. Each uplink
            can specify peer_count (default: experiment.ecmp_width). Uplink
            peers advertise routes via a network group.
        remote_as_4byte: Remote AS number (4-byte)
        experiment: PathScaleExperiment defining ECMP width and prefix count
        downlink_configs: Optional list of downlink interface configurations.
            Downlink peers are listeners that use an existing peer group and
            do not advertise routes.
        longevity_duration_min: Longevity soak duration in minutes (default 5)
        direct_ixia_connections: Direct IXIA connection configs for DUT
        basset_pool: Basset pool name
    """
    downlinks = downlink_configs or []

    # Generate peer configs for coop patcher
    peer_configs = []

    # Uplink peers: use PEERGROUP_RTSW_IXIA_PATH_SCALE_V6
    for uplink in uplink_configs:
        prefix = uplink.ic_parent_network_v6
        n_peers = (
            uplink.peer_count
            if uplink.peer_count is not None
            else experiment.ecmp_width
        )
        for i in range(n_peers):
            peer_configs.append(
                {
                    "local_addr": f"{prefix}::a",
                    "peer_addr": f"{prefix}::{0x100 + i:x}",
                    "peer_group_name": PEERGROUP_RTSW_IXIA_PATH_SCALE_V6,
                    "remote_as_4_byte": str(remote_as_4byte),
                    "description": f"ixia_peer_{uplink.interface}_{i}",
                }
            )

    # Downlink peers: use their own existing peer group (listener-only)
    for downlink in downlinks:
        prefix = downlink.ic_parent_network_v6
        for i in range(downlink.peer_count):
            peer_configs.append(
                {
                    "local_addr": f"{prefix}::a",
                    "peer_addr": f"{prefix}::{0x100 + i:x}",
                    "peer_group_name": downlink.peer_group_name,
                    "remote_as_4_byte": str(downlink.remote_as_4byte),
                    "description": f"ixia_peer_{downlink.interface}_{i}",
                }
            )

    # Split direct IXIA connections by interface type for per-port MAC
    uplink_interfaces = {u.interface for u in uplink_configs}
    downlink_interfaces = {d.interface for d in downlinks}
    all_connections = direct_ixia_connections or []

    endpoints = [
        taac_types.Endpoint(
            name=device_name,
            ixia_ports=[u.interface for u in uplink_configs],
            dut=True,
            mac_address=uplink_configs[0].mac_address,
            direct_ixia_connections=[
                c for c in all_connections if c.interface in uplink_interfaces
            ],
        ),
    ]
    if downlinks:
        endpoints.append(
            taac_types.Endpoint(
                name=device_name,
                ixia_ports=[d.interface for d in downlinks],
                dut=True,
                mac_address=downlinks[0].mac_address,
                direct_ixia_connections=[
                    c for c in all_connections if c.interface in downlink_interfaces
                ],
            ),
        )

    basic_port_configs = []

    # Uplink port configs: NDP handler + BGP peers with network group
    for uplink in uplink_configs:
        prefix = uplink.ic_parent_network_v6
        n_peers = (
            uplink.peer_count
            if uplink.peer_count is not None
            else experiment.ecmp_width
        )
        basic_port_configs.append(
            taac_types.BasicPortConfig(
                l1_config=MP3N_L1_CONFIG,
                endpoint=f"{device_name}:{uplink.interface}",
                device_group_configs=[
                    # DG0: NDP handler - single device with N IPv6 addresses.
                    # Tag "NDP_HANDLER" tells ixia.py to create DG with mult=1
                    # and IPv6 stack with mult=n_peers. A single device
                    # responding for all IPs avoids multiplied-device NDP issues.
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        tag_name="NDP_HANDLER",
                        multiplier=n_peers,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{prefix}::100",
                            increment_ip="::1",
                            gateway_starting_ip=f"{prefix}::a",
                            gateway_increment_ip="::",
                            mask=64,
                        ),
                    ),
                    # DG1: BGP peers - N devices, each with 1 IPv6 + BGP.
                    # Same IPs and MAC as DG0. Chained to DG0 so it uses
                    # the parent's resolved NDP/L3 sessions.
                    taac_types.DeviceGroupConfig(
                        device_group_index=1,
                        tag_name="CHAINED_0:BGP_MULTI_PEER",
                        multiplier=n_peers,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{prefix}::100",
                            increment_ip="::1",
                            gateway_starting_ip=f"{prefix}::a",
                            gateway_increment_ip="::",
                            mask=64,
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_as_4byte,
                            local_as_increment=0,
                            enable_4_byte_local_as=True,
                            bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                            is_confed=False,
                            bgp_capabilities=[
                                ixia_types.BgpCapability.IpV6Unicast,
                            ],
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    v6_route_scale=taac_types.RouteScale(
                                        starting_prefixes="6000:dd::",
                                        prefix_length=64,
                                        prefix_step="::",
                                        prefix_count=experiment.prefix_count,
                                        multiplier=1,
                                        bgp_communities=[
                                            "65527:12711",
                                        ],
                                    ),
                                    multiplier=1,
                                    network_group_index=0,
                                ),
                            ],
                        ),
                    ),
                ],
            ),
        )

    # Downlink port configs: NDP handler + BGP peers without network group
    for downlink in downlinks:
        prefix = downlink.ic_parent_network_v6
        basic_port_configs.append(
            taac_types.BasicPortConfig(
                l1_config=MP3N_L1_CONFIG,
                endpoint=f"{device_name}:{downlink.interface}",
                device_group_configs=[
                    # DG0: NDP handler
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        tag_name="NDP_HANDLER",
                        multiplier=downlink.peer_count,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{prefix}::100",
                            increment_ip="::1",
                            gateway_starting_ip=f"{prefix}::a",
                            gateway_increment_ip="::",
                            mask=64,
                        ),
                    ),
                    # DG1: BGP listener peers - no route advertisement
                    taac_types.DeviceGroupConfig(
                        device_group_index=1,
                        tag_name="CHAINED_0:BGP_MULTI_PEER",
                        multiplier=downlink.peer_count,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{prefix}::100",
                            increment_ip="::1",
                            gateway_starting_ip=f"{prefix}::a",
                            gateway_increment_ip="::",
                            mask=64,
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=downlink.remote_as_4byte,
                            local_as_increment=0,
                            enable_4_byte_local_as=True,
                            bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                            is_confed=False,
                            bgp_capabilities=[
                                ixia_types.BgpCapability.IpV6Unicast,
                            ],
                        ),
                    ),
                ],
            ),
        )

    # TC-level checks moved to playbook level
    _tc_prechecks = [
        create_systemctl_active_state_check(
            services_json=["wedge_agent", "bgpd", "fsdb", "qsfp_service"]
        ),
    ]
    _tc_postchecks = [
        create_systemctl_active_state_check(
            services_json=["wedge_agent", "bgpd", "fsdb", "qsfp_service"]
        ),
        create_prefix_limit_check(prefix_limit=str(experiment.prefix_count + 100)),
        create_unclean_exit_check(),
        create_memory_utilization_check(
            threshold=5 * (1024**3),
            threshold_by_service={
                "bgpd": 4.5 * (1024**3),
                "fsdb": 7 * (1024**3),
                "qsfp_service": 2 * (1024**3),
                "fboss_sw_agent": 0.8 * 16 * (1024**3),
                "fboss_hw_agent@0": 8 * (1024**3),
            },
            start_time_jq_var="test_case_start_time",
        ),
        create_cpu_utilization_check(
            threshold=400.0, start_time_jq_var="test_case_start_time"
        ),
        create_service_restart_check(
            services=["wedge_agent", "bgpd", "fsdb", "qsfp_service"]
        ),
    ]
    # TC postchecks without SERVICE_RESTART_CHECK (for playbooks that skip it)
    _tc_postchecks_no_restart = [
        c for c in _tc_postchecks if c.name != hc_types.CheckName.SERVICE_RESTART_CHECK
    ]
    _tc_snapshot_checks = [
        create_core_dumps_snapshot_check(),
    ]

    return TestConfig(
        name=test_config_name,
        ixia_protocol_verification_timeout=10,
        skip_ixia_protocol_verification=True,
        basset_pool=basset_pool,
        endpoints=endpoints,
        setup_tasks=[
            create_coop_unregister_patchers_task(
                hostnames=device_name,
                config_names=["bgpcpp", "agent"],
            ),
        ]
        + _get_rtsw_ixia_peer_group_tasks(device_name)
        + _get_rtsw_ftsw_policy_tasks(device_name)
        + [
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="add_bgp_peers_dut",
                task_name="add_bgp_peers",
                patcher_args={
                    "peer_configs": json.dumps(peer_configs),
                },
                py_func_name="add_bgp_peers",
            ),
            create_coop_apply_patchers_task([device_name]),
        ],
        teardown_tasks=[
            create_coop_unregister_patchers_task(device_name),
            create_coop_apply_patchers_task([device_name]),
        ],
        # Deprecated - define at playbook level
        # periodic_tasks=[],
        basic_port_configs=basic_port_configs,
        # traffic_items_to_start=["BGP_PATH_SCALE_TRAFFIC"],
        # basic_traffic_item_configs=[
        #     taac_types.BasicTrafficItemConfig(
        #         name="BGP_PATH_SCALE_TRAFFIC",
        #         src_endpoints=[
        #             TrafficEndpoint(
        #                 name=f"{device_name}:{downlink.interface}",
        #                 device_group_index=0,
        #             )
        #             for downlink in downlinks
        #         ],
        #         dest_endpoints=[
        #             TrafficEndpoint(
        #                 name=f"{device_name}:{uplink.interface}",
        #                 network_group_index=0,
        #                 device_group_index=1,
        #             )
        #             for uplink in uplink_configs
        #         ],
        #         line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
        #         line_rate=10,
        #         traffic_type=ixia_types.TrafficType.IPV6,
        #         src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
        #         merge_destinations=True,
        #         bidirectional=False,
        #         packet_headers=[
        #             taac_types.PacketHeader(
        #                 query=ixia_types.Query(
        #                     regex="ipv6",
        #                     query_type=ixia_types.QueryType.STACK_TYPE_ID,
        #                 ),
        #             ),
        #         ],
        #     ),
        # ],
        # Deprecated - define at playbook level
        # snapshot_checks (moved to each playbook)
        # Deprecated - define at playbook level
        # postchecks (moved to each playbook)
        # Deprecated - define at playbook level
        # prechecks (moved to each playbook)
        playbooks=[
            build_mp3n_bgp_path_scale_playbook(
                name="test_bgp_path_scale_longevity",
                stages=[
                    create_steps_stage(
                        steps=[
                            create_longevity_step(duration=longevity_duration_min * 60),
                        ],
                    ),
                ],
                prechecks=_tc_prechecks,
                postchecks=[
                    # PointInTimeHealthCheck(
                    #     name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
                    # ),
                    create_bgp_convergence_check(
                        convergence_threshold=600, fail_on_eor_expired=False
                    ),
                ]
                + _tc_postchecks,
                snapshot_checks=_tc_snapshot_checks,
            ),
            build_mp3n_bgp_path_scale_playbook(
                name="test_continuous_agent_restart",
                prechecks=_tc_prechecks,
                postchecks=[
                    create_bgp_convergence_check(
                        convergence_threshold=600, fail_on_eor_expired=False
                    ),
                ]
                + _tc_postchecks_no_restart,
                snapshot_checks=_tc_snapshot_checks,
                stages=[
                    create_steps_stage(
                        steps=[
                            create_service_interruption_step(
                                service=Service.AGENT,
                                trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                            ),
                            create_service_convergence_step(
                                services=[Service.AGENT], timeout=600
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_longevity_step(duration=120),
                        ],
                    ),
                ],
                iteration=1,
            ),
            build_mp3n_bgp_path_scale_playbook(
                name="test_continuous_bgp_restart",
                prechecks=_tc_prechecks,
                postchecks=[
                    create_bgp_convergence_check(
                        convergence_threshold=600, fail_on_eor_expired=False
                    ),
                ]
                + _tc_postchecks_no_restart,
                snapshot_checks=_tc_snapshot_checks,
                stages=[
                    create_steps_stage(
                        steps=[
                            create_service_interruption_step(
                                service=Service.BGP,
                                trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                            ),
                            create_service_convergence_step(
                                services=[Service.AGENT, Service.BGP], timeout=600
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_longevity_step(duration=120),
                        ],
                    ),
                ],
                iteration=1,
            ),
            build_mp3n_bgp_path_scale_playbook(
                name="test_agent_coldboot",
                prechecks=_tc_prechecks,
                stages=[
                    create_steps_stage(
                        steps=[
                            create_service_interruption_step(
                                service=Service.AGENT,
                                trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                                create_cold_boot_file=True,
                            ),
                            create_service_convergence_step(
                                services=[Service.AGENT], timeout=600
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_longevity_step(duration=180),
                        ],
                    ),
                ],
                postchecks=[
                    create_bgp_convergence_check(
                        convergence_threshold=600, fail_on_eor_expired=False
                    ),
                ]
                + _tc_postchecks_no_restart,
                snapshot_checks=_tc_snapshot_checks,
            ),
            build_mp3n_bgp_path_scale_playbook(
                name="test_route_flap",
                prechecks=_tc_prechecks,
                stages=[
                    create_steps_stage(
                        steps=[
                            create_toggle_ixia_prefix_session_flap_churn_step(
                                churn_mode="prefix_flap",
                                enable_prefix_flap=True,
                                is_all_prefix_groups=True,
                                churn_duration_s=1000,
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_toggle_ixia_prefix_session_flap_churn_step(
                                churn_mode="prefix_flap",
                                enable_prefix_flap=False,
                                is_all_prefix_groups=True,
                                churn_duration_s=0,
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_ixia_api_step(
                                api_name="clear_traffic_stats", args_dict={}
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_longevity_step(duration=120),
                        ],
                    ),
                ],
                postchecks=[
                    # PointInTimeHealthCheck(
                    #     name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
                    #     input_json=thrift_to_json(
                    #         hc_types.IxiaPacketLossHealthCheckIn(
                    #             clear_traffic_stats=True,
                    #         )
                    #     ),
                    # ),
                    create_bgp_convergence_check(
                        convergence_threshold=600, fail_on_eor_expired=False
                    ),
                ]
                + _tc_postchecks,
                snapshot_checks=_tc_snapshot_checks,
            ),
            build_mp3n_bgp_path_scale_playbook(
                name="test_session_flap_all_prefixes",
                prechecks=_tc_prechecks,
                stages=[
                    create_steps_stage(
                        steps=[
                            create_toggle_ixia_prefix_session_flap_churn_step(
                                churn_mode="session_flap",
                                enable_session_flap=True,
                                is_all_session_groups=True,
                                churn_duration_s=3600,
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_toggle_ixia_prefix_session_flap_churn_step(
                                churn_mode="session_flap",
                                enable_session_flap=False,
                                is_all_session_groups=True,
                                churn_duration_s=0,
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_ixia_api_step(
                                api_name="clear_traffic_stats", args_dict={}
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_longevity_step(duration=120),
                        ],
                    ),
                ],
                postchecks=[
                    # PointInTimeHealthCheck(
                    #     name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
                    #     input_json=thrift_to_json(
                    #         hc_types.IxiaPacketLossHealthCheckIn(
                    #             clear_traffic_stats=True,
                    #         )
                    #     ),
                    # ),
                    create_bgp_convergence_check(
                        convergence_threshold=600, fail_on_eor_expired=False
                    ),
                ]
                + _tc_postchecks,
                snapshot_checks=_tc_snapshot_checks,
            ),
            build_mp3n_bgp_path_scale_playbook(
                name="test_bgp_path_scale_no_flaps_longevity",
                prechecks=_tc_prechecks,
                stages=[
                    create_steps_stage(
                        steps=[
                            create_toggle_ixia_prefix_session_flap_churn_step(
                                churn_mode="prefix_flap",
                                enable_prefix_flap=False,
                                is_all_prefix_groups=True,
                                churn_duration_s=0,
                            ),
                            create_toggle_ixia_prefix_session_flap_churn_step(
                                churn_mode="session_flap",
                                enable_session_flap=False,
                                is_all_session_groups=True,
                                churn_duration_s=0,
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_longevity_step(duration=1800),
                        ],
                    ),
                ],
                postchecks=[
                    # PointInTimeHealthCheck(
                    #     name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
                    # ),
                    create_bgp_convergence_check(
                        convergence_threshold=600, fail_on_eor_expired=False
                    ),
                ]
                + _tc_postchecks,
                snapshot_checks=_tc_snapshot_checks,
            ),
            build_mp3n_bgp_path_scale_playbook(
                name="test_best_path_recomputation_local_pref_change",
                prechecks=_tc_prechecks,
                stages=[
                    create_steps_stage(
                        steps=[
                            create_ixia_api_step(
                                api_name="set_bgp_local_preference",
                                args_dict={
                                    "local_preference": 50,
                                    "network_group_regex": ".*BGP_PREFIX_V6.*",
                                },
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_longevity_step(duration=60),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_ixia_api_step(
                                api_name="set_bgp_local_preference",
                                args_dict={
                                    "local_preference": 200,
                                    "network_group_regex": ".*BGP_PREFIX_V6.*",
                                },
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_longevity_step(duration=60),
                        ],
                    ),
                ],
                iteration=1,
                postchecks=[
                    # PointInTimeHealthCheck(
                    #     name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
                    # ),
                    create_bgp_convergence_check(
                        convergence_threshold=600, fail_on_eor_expired=False
                    ),
                ]
                + _tc_postchecks,
                snapshot_checks=_tc_snapshot_checks,
            ),
            build_mp3n_bgp_path_scale_playbook(
                name="test_route_flap_all_prefixes_with_bgpd_restart",
                prechecks=_tc_prechecks,
                stages=[
                    create_steps_stage(
                        concurrent=True,
                        concurrent_steps=[
                            ConcurrentStep(
                                steps=[
                                    create_toggle_ixia_prefix_session_flap_churn_step(
                                        churn_mode="prefix_flap",
                                        enable_prefix_flap=True,
                                        is_all_prefix_groups=True,
                                        churn_duration_s=1800,
                                    ),
                                ],
                            ),
                            ConcurrentStep(
                                steps=[
                                    create_service_interruption_step(
                                        service=Service.BGP,
                                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                                    ),
                                ],
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_service_convergence_step(
                                services=[Service.AGENT, Service.BGP]
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_toggle_ixia_prefix_session_flap_churn_step(
                                churn_mode="prefix_flap",
                                enable_prefix_flap=False,
                                is_all_prefix_groups=True,
                                churn_duration_s=0,
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_ixia_api_step(
                                api_name="clear_traffic_stats", args_dict={}
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_longevity_step(duration=120),
                        ],
                    ),
                ],
                postchecks=[
                    create_bgp_convergence_check(
                        convergence_threshold=600, fail_on_eor_expired=False
                    ),
                ]
                + _tc_postchecks_no_restart,
                snapshot_checks=_tc_snapshot_checks,
            ),
            build_mp3n_bgp_path_scale_playbook(
                name="test_session_flap_all_prefixes_with_bgpd_restart",
                prechecks=_tc_prechecks,
                stages=[
                    create_steps_stage(
                        concurrent=True,
                        concurrent_steps=[
                            ConcurrentStep(
                                steps=[
                                    create_toggle_ixia_prefix_session_flap_churn_step(
                                        churn_mode="session_flap",
                                        enable_session_flap=True,
                                        is_all_session_groups=True,
                                        churn_duration_s=1800,
                                    ),
                                ],
                            ),
                            ConcurrentStep(
                                steps=[
                                    create_service_interruption_step(
                                        service=Service.BGP,
                                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                                    ),
                                ],
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_service_convergence_step(
                                services=[Service.AGENT, Service.BGP]
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_toggle_ixia_prefix_session_flap_churn_step(
                                churn_mode="session_flap",
                                enable_session_flap=False,
                                is_all_session_groups=True,
                                churn_duration_s=0,
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_ixia_api_step(
                                api_name="clear_traffic_stats", args_dict={}
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_longevity_step(duration=120),
                        ],
                    ),
                ],
                postchecks=[
                    create_bgp_convergence_check(
                        convergence_threshold=600, fail_on_eor_expired=False
                    ),
                ]
                + _tc_postchecks_no_restart,
                snapshot_checks=_tc_snapshot_checks,
            ),
        ],
    )


# =============================================================================
# Testbed: rtsw002.l1003.c084.ash6
# Uplink: eth1/3/1 -> ixia13 1/9
# Downlink: eth1/3/5 -> ixia13 1/10
# =============================================================================
_RTSW002_DEVICE_NAME: str = "rtsw002.l1003.c084.ash6"
_RTSW002_MAC_ADDRESS_ETH1_3_1: str = "ae:81:b5:03:d6:95"
_RTSW002_MAC_ADDRESS_ETH1_3_5: str = "ae:81:b5:03:d6:96"
_RTSW002_UPLINK_REMOTE_AS: int = 65321
_RTSW002_DOWNLINK_REMOTE_AS: int = 4200000143

_IXIA13_CHASSIS_IP: str = "2401:db00:2066:304b::3002"

_RTSW002_DIRECT_IXIA_CONNECTIONS: list[taac_types.DirectIxiaConnection] = [
    taac_types.DirectIxiaConnection(
        interface="eth1/3/1",
        ixia_chassis_ip=_IXIA13_CHASSIS_IP,
        ixia_port="1/9",
    ),
    taac_types.DirectIxiaConnection(
        interface="eth1/3/5",
        ixia_chassis_ip=_IXIA13_CHASSIS_IP,
        ixia_port="1/10",
    ),
]

# IPv6 network prefixes for the interfaces
_RTSW002_UPLINK_PREFIX_ETH1_3_1: str = "2401:db00:209e:44"  # eth1/3/1
_RTSW002_DOWNLINK_PREFIX_ETH1_3_5: str = "2401:db00:209e:45"  # eth1/3/5


def _create_rtsw002_path_scale_config(
    exp_name: str,
    experiment: PathScaleExperiment,
) -> TestConfig:
    """Create a path scale test config for rtsw002.l1003.c084.ash6."""
    return test_config_for_mp3n_bgp_path_scale(
        test_config_name=f"MP3N_BGP_PATH_SCALE_{exp_name.upper()}",
        device_name=_RTSW002_DEVICE_NAME,
        uplink_configs=[
            UplinkConfig(
                interface="eth1/3/1",
                ic_parent_network_v6=_RTSW002_UPLINK_PREFIX_ETH1_3_1,
                mac_address=_RTSW002_MAC_ADDRESS_ETH1_3_1,
            ),
        ],
        remote_as_4byte=_RTSW002_UPLINK_REMOTE_AS,
        experiment=experiment,
        downlink_configs=[
            DownlinkConfig(
                interface="eth1/3/5",
                ic_parent_network_v6=_RTSW002_DOWNLINK_PREFIX_ETH1_3_5,
                mac_address=_RTSW002_MAC_ADDRESS_ETH1_3_5,
                peer_count=36,
                peer_group_name=PEERGROUP_RTSW_FTSW_V6,
                remote_as_4byte=_RTSW002_DOWNLINK_REMOTE_AS,
            ),
        ],
        direct_ixia_connections=_RTSW002_DIRECT_IXIA_CONNECTIONS,
        basset_pool="networkai.test",
    )


# Experiment instantiations
EXP1_1_5M_ECMP52: TestConfig = _create_rtsw002_path_scale_config(
    "exp1_1_5m_ecmp52", PATH_SCALE_EXPERIMENTS["exp1_1_5m_ecmp52"]
)
EXP3_4M_ECMP120: TestConfig = _create_rtsw002_path_scale_config(
    "exp3_4m_ecmp120", PATH_SCALE_EXPERIMENTS["exp3_4m_ecmp120"]
)
EXP5_4M_ECMP240: TestConfig = _create_rtsw002_path_scale_config(
    "exp5_4m_ecmp240", PATH_SCALE_EXPERIMENTS["exp5_4m_ecmp240"]
)
