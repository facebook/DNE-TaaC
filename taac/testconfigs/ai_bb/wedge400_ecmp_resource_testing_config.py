# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe

"""
Wedge400 ECMP Resource Testing Configuration.

Testbed: TBD
Platform: Wedge400

This configuration is for ECMP resource testing on Wedge400 platform.
Based on dsf_hardening_test_config.py IXIA configuration.
"""

import json

from ixia.ixia import types as ixia_types
from taac.health_checks.healthcheck_definitions import (
    create_core_dumps_snapshot_check,
    create_prefix_limit_check,
    create_systemctl_active_state_check,
)
from taac.packet_headers import DSF_RDMA_IB_PACKET_HEADERS
from taac.playbooks.playbook_definitions import (
    create_ecmp_groups_playbooks,
    create_ecmp_members_playbooks,
    create_spillover_testing_playbooks,
)
from taac.task_definitions import (
    create_coop_apply_patchers_task,
    create_coop_register_patcher_task,
    create_coop_unregister_patchers_task,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import Params, Playbook, TestConfig


# Peer group constants
PEERGROUP_RTSW_IXIA_V6 = "PEERGROUP_RTSW_IXIA_V6"


# =============================================================================
# SECTION 2: L1 AND FRAME SIZE CONFIGURATIONS
# =============================================================================
DSF_FRAME_SIZES = ixia_types.FrameSize(
    type=ixia_types.FrameSizeType.CUSTOM_IMIX,
    imix_weight={94: 1, 96: 18, 192: 3, 512: 1, 1200: 1, 4600: 76},
)

DSF_L1_CONFIG = ixia_types.L1Config(
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


# =============================================================================
# SECTION 4.2: ECMP MEMBERS PLAYBOOKS HELPER FUNCTION
# =============================================================================
def get_rtsw_ixia_peer_group_tasks(device_name):
    """
    Returns the RTSW IXIA peer group configuration tasks.
    This configures the peer group for uplink eBGP peering.
    """
    return [
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name="add_peer_group_patcher_PEERGROUP_RTSW_IXIA_V6",
            task_name="add_peer_group_patcher",
            patcher_args={
                "name": PEERGROUP_RTSW_IXIA_V6,
                "description": "eBGP peering from RTSW to IXIA, IPv6 sessions",
                "disable_ipv4_afi": "True",
                "disable_ipv6_afi": "False",
                "ingress_policy_name": "PROPAGATE_RTSW_IXIA_IN",
                "egress_policy_name": "PROPAGATE_RTSW_IXIA_OUT",
                "bgp_peer_timers_hold_time_seconds": "30",
                "bgp_peer_timers_keep_alive_seconds": "10",
                "bgp_peer_timers_out_delay_seconds": "0",
                "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                "peer_tag": "IXIA",
                "max_routes": "900000",
                "warning_only": "True",
                "warning_limit": "0",
                "next_hop_self": "False",
                "add_path": "BOTH",
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
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_RTSW_IXIA_IN",
            task_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_RTSW_IXIA_IN",
                "description": "Policy for RTSW IXIA IN",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_RTSW_IXIA_OUT",
            task_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_RTSW_IXIA_OUT",
                "description": "Policy for RTSW IXIA OUT",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_RTSW_IXIA_IN_v6",
            task_name="add_bgp_policy_match_prefix_to_propagate_routes",
            patcher_args={
                "matching_prefix": "5000::/16",
                "in_stmt_name": "PROPAGATE_RTSW_IXIA_IN",
                "out_stmt_name": "RANDOM",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
    ]


# =============================================================================
# SECTION 6: TEST CONFIG FACTORY FUNCTION
# =============================================================================
def test_config_for_wedge400_ecmp_resource_testing(
    test_config_name,
    device_name,
    local_mac_address,
    ixia_downlink_interface,
    ixia_rogue_interface,
    peergroup_uplink_mimic_v6,
    ixia_downlink_ic_parent_network_v6,
    ixia_rogue_ic_parent_network_v6,
    prefix_limit,
    per_peer_max_route_limit,
    uplink_peer_count,
    remote_uplink_as_4byte,
    is_uplink_peer_confed,
    ixia_nexthop_supporting_ndp_network,
    ixia_nexthop_supporting_ndp_gateway,
    playbooks=None,
    direct_ixia_connections=None,
    basset_pool=None,
    ixia_remote_interface=None,
    ixia_remote_ic_parent_network_v6=None,
):
    """
    Wedge400 ECMP Resource Testing configuration.

    This is a configuration for ECMP resource testing on Wedge400 platform
    with the following characteristics:
    - iBGP uplink peering only (no downlink BGP)
    - Rogue interface for ECMP stressor with NDP support
    - Simplified traffic patterns for testing topology
    """
    # TestConfig-level checks moved to playbook level
    tc_prechecks = [
        create_systemctl_active_state_check(
            services=[
                hc_types.Service.WEDGE_AGENT,
                hc_types.Service.BGPD,
                hc_types.Service.QSFP_SERVICE,
                hc_types.Service.FSDB,
                hc_types.Service.FBOSS_SW_AGENT,
                hc_types.Service.FBOSS_HW_AGENT_0,
            ],
        ),
    ]

    tc_postchecks = [
        create_systemctl_active_state_check(
            services=[
                hc_types.Service.WEDGE_AGENT,
                hc_types.Service.BGPD,
                hc_types.Service.QSFP_SERVICE,
                hc_types.Service.FSDB,
                hc_types.Service.FBOSS_SW_AGENT,
                hc_types.Service.FBOSS_HW_AGENT_0,
            ],
        ),
        create_prefix_limit_check(prefix_limit=prefix_limit),
    ]

    tc_snapshot_checks = [
        create_core_dumps_snapshot_check(),
    ]

    def _add_tc_checks_to_playbook(pb: Playbook) -> Playbook:
        """Add former TestConfig-level checks to a playbook."""
        new_prechecks = tc_prechecks + list(pb.prechecks or [])
        new_postchecks = list(pb.postchecks or []) + tc_postchecks

        if pb.skip_test_config_snapshot_checks:
            new_snapshot_checks = list(pb.snapshot_checks or [])
        else:
            new_snapshot_checks = list(pb.snapshot_checks or []) + tc_snapshot_checks

        return pb(
            prechecks=new_prechecks,
            postchecks=new_postchecks,
            snapshot_checks=new_snapshot_checks,
            skip_test_config_snapshot_checks=False,
        )

    def _add_tc_checks_to_playbooks(
        playbooks: list[Playbook],
    ) -> list[Playbook]:
        return [_add_tc_checks_to_playbook(pb) for pb in playbooks]

    # Build endpoints list - all ports on single DUT device
    endpoints = [
        taac_types.Endpoint(
            name=device_name,
            ixia_ports=[
                ixia_downlink_interface,
                ixia_rogue_interface,
                ixia_remote_interface,  # 4th port also on DUT
            ],
            dut=True,
            mac_address=local_mac_address,
            direct_ixia_connections=direct_ixia_connections
            if direct_ixia_connections
            else [],
        ),
    ]

    return TestConfig(
        name=test_config_name,
        ixia_protocol_verification_timeout=10,
        skip_ixia_protocol_verification=True,
        basset_pool=basset_pool,
        endpoints=endpoints,
        setup_tasks=[
            create_coop_unregister_patchers_task(device_name),
        ]
        + get_rtsw_ixia_peer_group_tasks(device_name)
        + [
            # Add BGP peers for DUT device (Gold, Silver, Rouge on rogue interface)
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="add_bgp_peers_dut",
                task_name="add_bgp_peers",
                patcher_args={
                    "peer_configs": json.dumps(
                        [
                            {
                                "local_addr": f"{ixia_rogue_ic_parent_network_v6}::a",
                                "peer_addr": f"{ixia_rogue_ic_parent_network_v6}::b",
                                "peer_group_name": PEERGROUP_RTSW_IXIA_V6,
                                "remote_as_4_byte": str(remote_uplink_as_4byte),
                                "description": "ixia_session_gold",
                            },
                            {
                                "local_addr": f"{ixia_rogue_ic_parent_network_v6}::a",
                                "peer_addr": f"{ixia_rogue_ic_parent_network_v6}::c",
                                "peer_group_name": PEERGROUP_RTSW_IXIA_V6,
                                "remote_as_4_byte": str(remote_uplink_as_4byte),
                                "description": "ixia_session_silver",
                            },
                            {
                                "local_addr": f"{ixia_rogue_ic_parent_network_v6}::a",
                                "peer_addr": f"{ixia_rogue_ic_parent_network_v6}::d",
                                "peer_group_name": PEERGROUP_RTSW_IXIA_V6,
                                "remote_as_4_byte": str(remote_uplink_as_4byte),
                                "description": "ixia_session_rouge",
                            },
                        ]
                    ),
                },
                py_func_name="add_bgp_peers",
            ),
            create_coop_apply_patchers_task(
                hostnames=[device_name],
                do_warmboot=True,
            ),
        ],
        teardown_tasks=[
            create_coop_unregister_patchers_task(device_name),
        ],
        # Deprecated - define at playbook level
        # periodic_tasks=[],
        basic_traffic_item_configs=[
            taac_types.BasicTrafficItemConfig(
                name=f"{ixia_downlink_interface.upper().replace('/', '_')}_TO_DLB_GOLDEN_TRAFFIC",
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_rogue_interface}",
                        device_group_index=0,
                        network_group_index=0,
                    ),
                ],
                bidirectional=False,
                merge_destinations=True,
                line_rate=10,
                frame_size_settings=ixia_types.FrameSize(
                    type=ixia_types.FrameSizeType.FIXED,
                    fixed_size=1024,
                ),
                src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
                traffic_type=ixia_types.TrafficType.IPV6,
                tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
                # Use RDMA-IB headers (AR=1, RoCEv2/UDP 4791, TC2/DSCP 56) so
                # traffic is DLB-eligible on TH3. Plain IPv6 packets bypass DLB
                # even on DLB-programmed groups.
                packet_headers=DSF_RDMA_IB_PACKET_HEADERS,
            ),
            # Silver traffic: remote interface -> Silver network group (SILVER_BGP_PREFIXES)
            taac_types.BasicTrafficItemConfig(
                name=f"{ixia_remote_interface.upper().replace('/', '_')}_TO_SILVER_TRAFFIC",
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_remote_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_rogue_interface}",
                        device_group_index=1,
                        network_group_index=0,
                    ),
                ],
                bidirectional=False,
                merge_destinations=True,
                line_rate=10,
                frame_size_settings=ixia_types.FrameSize(
                    type=ixia_types.FrameSizeType.FIXED,
                    fixed_size=1024,
                ),
                src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
                traffic_type=ixia_types.TrafficType.IPV6,
                tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
                # Use RDMA-IB headers (AR=1, RoCEv2/UDP 4791, TC2/DSCP 56) so
                # traffic is DLB-eligible on TH3. Plain IPv6 packets bypass DLB
                # even on DLB-programmed groups.
                packet_headers=DSF_RDMA_IB_PACKET_HEADERS,
            ),
            # Rouge traffic: remote interface -> Rouge network group (ROUGE_BGP_PREFIXES)
            taac_types.BasicTrafficItemConfig(
                name=f"{ixia_remote_interface.upper().replace('/', '_')}_TO_ROUGE_TRAFFIC",
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_remote_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_rogue_interface}",
                        device_group_index=2,
                        network_group_index=0,
                    ),
                ],
                bidirectional=False,
                merge_destinations=True,
                line_rate=10,
                frame_size_settings=ixia_types.FrameSize(
                    type=ixia_types.FrameSizeType.FIXED,
                    fixed_size=1024,
                ),
                src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
                traffic_type=ixia_types.TrafficType.IPV6,
                tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
                # Use RDMA-IB headers (AR=1, RoCEv2/UDP 4791, TC2/DSCP 56) so
                # traffic is DLB-eligible on TH3. Plain IPv6 packets bypass DLB
                # even on DLB-programmed groups.
                packet_headers=DSF_RDMA_IB_PACKET_HEADERS,
            ),
        ],
        basic_port_configs=[
            # Downlink port config (no BGP, just L2/L3 connectivity)
            taac_types.BasicPortConfig(
                l1_config=DSF_L1_CONFIG,
                endpoint=f"{device_name}:{ixia_downlink_interface}",
                device_group_configs=[
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        tag_name="DOWNLINK_L3_TRAFFIC",
                        multiplier=1,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_downlink_ic_parent_network_v6}::b",
                            increment_ip="::",
                            gateway_starting_ip=f"{ixia_downlink_ic_parent_network_v6}::a",
                            gateway_increment_ip="::",
                            mask=64,
                        ),
                    ),
                ],
            ),
            # Rogue port config (ECMP stressor with BGP peering and NDP support)
            taac_types.BasicPortConfig(
                l1_config=DSF_L1_CONFIG,
                endpoint=f"{device_name}:{ixia_rogue_interface}",
                device_group_configs=[
                    # Device group 0: DLB resource (Gold) - BGP config (ENABLED by default for traffic)
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        tag_name="DLB_resource(Gold)",
                        enable=True,
                        multiplier=1,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_rogue_ic_parent_network_v6}::b",
                            increment_ip="::",
                            gateway_starting_ip=f"{ixia_rogue_ic_parent_network_v6}::a",
                            gateway_increment_ip="::",
                            mask=64,
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_uplink_as_4byte,
                            local_as_increment=0,
                            enable_4_byte_local_as=True,
                            bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                            is_confed=is_uplink_peer_confed == "True",
                            bgp_capabilities=[
                                ixia_types.BgpCapability.IpV6Unicast,
                                ixia_types.BgpCapability.Ipv6UnicastAddPath,
                            ],
                            custom_network_group_configs=[
                                ixia_types.CustomNetworkGroupConfig(
                                    device_group_name="DLB_resource(Gold)",
                                    network_group_name="DLB_golden_prefixes",
                                    network_group_multiplier=7000,
                                    prefix_start_value="5000:dd::",
                                    prefix_length=64,
                                    nexthop_start_value=ixia_nexthop_supporting_ndp_network,
                                    nexthop_increments="::1",
                                    ecmp_width=64,
                                    community_list=["65446:30"],
                                    network_group_index=0,
                                ),
                            ],
                        ),
                    ),
                    # Device group 1: Non-DLB resource (Silver) - BGP config (ENABLED by default)
                    taac_types.DeviceGroupConfig(
                        device_group_index=1,
                        tag_name="NoN_DLB_resource(silver)",
                        enable=True,
                        multiplier=1,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_rogue_ic_parent_network_v6}::c",
                            increment_ip="::",
                            gateway_starting_ip=f"{ixia_rogue_ic_parent_network_v6}::a",
                            gateway_increment_ip="::",
                            mask=64,
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_uplink_as_4byte,
                            local_as_increment=0,
                            enable_4_byte_local_as=True,
                            bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                            is_confed=is_uplink_peer_confed == "True",
                            bgp_capabilities=[
                                ixia_types.BgpCapability.IpV6Unicast,
                                ixia_types.BgpCapability.Ipv6UnicastAddPath,
                            ],
                            custom_network_group_configs=[
                                ixia_types.CustomNetworkGroupConfig(
                                    device_group_name="NoN_DLB_resource(silver)",
                                    network_group_name="SILVER_BGP_PREFIXES",
                                    network_group_multiplier=34500,
                                    prefix_start_value="5000:ee::",
                                    prefix_length=64,
                                    nexthop_start_value="2401:db00:206a:1::a001",
                                    nexthop_increments="::2",
                                    ecmp_width=25,
                                    community_list=["65446:30"],
                                    network_group_index=0,
                                ),
                            ],
                        ),
                    ),
                    # Device group 2: Non-DLB resource (Rouge) - BGP config (ENABLED by default)
                    taac_types.DeviceGroupConfig(
                        device_group_index=2,
                        tag_name="NoN_DLB_resource(Rouge)",
                        enable=True,
                        multiplier=1,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_rogue_ic_parent_network_v6}::d",
                            increment_ip="::",
                            gateway_starting_ip=f"{ixia_rogue_ic_parent_network_v6}::a",
                            gateway_increment_ip="::",
                            mask=64,
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_uplink_as_4byte,
                            local_as_increment=0,
                            enable_4_byte_local_as=True,
                            bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                            is_confed=is_uplink_peer_confed == "True",
                            bgp_capabilities=[
                                ixia_types.BgpCapability.IpV6Unicast,
                                ixia_types.BgpCapability.Ipv6UnicastAddPath,
                            ],
                            custom_network_group_configs=[
                                ixia_types.CustomNetworkGroupConfig(
                                    device_group_name="NoN_DLB_resource(Rouge)",
                                    network_group_name="ROUGE_BGP_PREFIXES",
                                    network_group_multiplier=7000,
                                    prefix_start_value="5000:ff::",
                                    prefix_length=64,
                                    nexthop_start_value="2401:db00:206a:1::a001",
                                    nexthop_increments="::3",
                                    ecmp_width=64,
                                    community_list=["65446:30"],
                                    network_group_index=0,
                                ),
                            ],
                        ),
                    ),
                    # Device group 3: NDP supporting nexthop (NO BGP) - ENABLED by default
                    taac_types.DeviceGroupConfig(
                        device_group_index=3,
                        tag_name="NDP_SUPPORTING_NEXTHOP",
                        multiplier=2000,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=ixia_nexthop_supporting_ndp_network,
                            increment_ip="::1",
                            gateway_starting_ip=ixia_nexthop_supporting_ndp_gateway,
                            mask=64,
                        ),
                    ),
                ],
            ),
            # Remote (4th) port config - on same DUT device
            taac_types.BasicPortConfig(
                l1_config=DSF_L1_CONFIG,
                endpoint=f"{device_name}:{ixia_remote_interface}",
                device_group_configs=[
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        tag_name="REMOTE_L3_TRAFFIC",
                        enable=True,
                        multiplier=1,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_remote_ic_parent_network_v6}::b",
                            increment_ip="::",
                            gateway_starting_ip=f"{ixia_remote_ic_parent_network_v6}::a",
                            gateway_increment_ip="::",
                            mask=64,
                        ),
                    ),
                ],
            ),
        ],
        # Deprecated - define at playbook level
        # snapshot_checks=[
        #     SnapshotHealthCheck(name=hc_types.CheckName.CORE_DUMPS_CHECK),
        # ],
        # Deprecated - define at playbook level
        # postchecks=[
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.SYSTEMCTL_ACTIVE_STATE_CHECK,
        #         ...
        #     ),
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.PREFIX_LIMIT_CHECK,
        #         ...
        #     ),
        # ],
        # Deprecated - define at playbook level
        # prechecks=[
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.SYSTEMCTL_ACTIVE_STATE_CHECK,
        #         ...
        #     ),
        # ],
        playbooks=_add_tc_checks_to_playbooks(
            create_ecmp_groups_playbooks(ixia_downlink_interface, ixia_remote_interface)
            + create_ecmp_members_playbooks(
                ixia_downlink_interface, ixia_remote_interface
            )
            + create_spillover_testing_playbooks(
                ixia_downlink_interface, ixia_remote_interface
            )
        ),
    )


# =============================================================================
# SECTION 7: TEST CONFIG INSTANCES
# =============================================================================

# IXIA Chassis IP for rtsw001.l1003.c084.ash6 testbed
# All ports connected to ixia12.netcastle.ash6
IXIA12_CHASSIS_IP: str = "2401:db00:2066:304b::3003"

# IXIA Chassis IP for rtsw001.u001.c081.ash6 testbed
# All ports connected to ixia06.netcastle.ash6
IXIA06_CHASSIS_IP: str = "2401:db00:2066:3037::3006"

# Test config for rtsw001.l1003.c084.ash6 (Wedge400 ECMP Resource Testing)
# Interface to IXIA mapping:
#   eth1/1/1 -> ixia12 1/9  (Downlink/Source)     Gateway: 2401:db00:209e::a
#   eth1/2/1 -> ixia12 1/11 (Rogue/BGP + ECMP)    Gateway: 2401:db00:209e:2::a
#   eth1/2/5 -> ixia12 1/12 (Remote)              Gateway: 2401:db00:209e:3::a
RTSW001_L1003_C084_ECMP_RESOURCE_TESTING: TestConfig = (
    test_config_for_wedge400_ecmp_resource_testing(
        test_config_name="RTSW001_L1003_C084_ECMP_RESOURCE_TESTING",
        device_name="rtsw001.l1003.c084.ash6",
        local_mac_address="02:00:00:00:00:01",  # TODO: Update with actual MAC address
        ixia_downlink_interface="eth1/1/1",
        ixia_rogue_interface="eth1/2/1",
        peergroup_uplink_mimic_v6=PEERGROUP_RTSW_IXIA_V6,
        ixia_downlink_ic_parent_network_v6="2401:db00:209e:0",
        ixia_rogue_ic_parent_network_v6="2401:db00:209e:2",
        prefix_limit="75000",
        per_peer_max_route_limit="25000",
        uplink_peer_count=1,
        remote_uplink_as_4byte=4200000005,  # eBGP
        is_uplink_peer_confed="False",
        ixia_nexthop_supporting_ndp_network="2401:db00:209e:2::a001",
        ixia_nexthop_supporting_ndp_gateway="2401:db00:209e:2::a",
        basset_pool="taac_netcastle_ash6",
        direct_ixia_connections=[
            taac_types.DirectIxiaConnection(
                interface="eth1/1/1",  # Downlink interface
                ixia_chassis_ip=IXIA12_CHASSIS_IP,
                ixia_port="1/9",
            ),
            taac_types.DirectIxiaConnection(
                interface="eth1/2/1",  # Rogue interface (BGP + ECMP)
                ixia_chassis_ip=IXIA12_CHASSIS_IP,
                ixia_port="1/11",
            ),
            taac_types.DirectIxiaConnection(
                interface="eth1/2/5",  # Remote (4th) interface
                ixia_chassis_ip=IXIA12_CHASSIS_IP,
                ixia_port="1/12",
            ),
        ],
        ixia_remote_interface="eth1/2/5",
        ixia_remote_ic_parent_network_v6="2401:db00:209e:3",
    )
)

# Test config for rtsw001.u001.c081.ash6 (Wedge400 ECMP Resource Testing)
# Interface to IXIA mapping:
#   eth2/1/1 -> ixia06 1/19 (Downlink/Source)     Gateway: 2401:db00:206a::a
#   eth2/3/1 -> ixia06 1/20 (Rogue/BGP + ECMP)    Gateway: 2401:db00:206a:1::a
#   eth3/1/1 -> ixia06 1/11 (Remote)              Gateway: 2401:db00:206a:8::a
RTSW001_U001_C081_ECMP_RESOURCE_TESTING: TestConfig = (
    test_config_for_wedge400_ecmp_resource_testing(
        test_config_name="RTSW001_U001_C081_ECMP_RESOURCE_TESTING",
        device_name="rtsw001.u001.c081.ash6",
        local_mac_address="02:00:00:00:00:01",  # TODO: Update with actual MAC address
        ixia_downlink_interface="eth2/1/1",
        ixia_rogue_interface="eth2/3/1",
        peergroup_uplink_mimic_v6=PEERGROUP_RTSW_IXIA_V6,
        ixia_downlink_ic_parent_network_v6="2401:db00:206a:0",
        ixia_rogue_ic_parent_network_v6="2401:db00:206a:1",
        prefix_limit="75000",
        per_peer_max_route_limit="25000",
        uplink_peer_count=1,
        remote_uplink_as_4byte=4200000005,  # eBGP
        is_uplink_peer_confed="False",
        ixia_nexthop_supporting_ndp_network="2401:db00:206a:1::a001",
        ixia_nexthop_supporting_ndp_gateway="2401:db00:206a:1::a",
        basset_pool="taac_netcastle_ash6",
        direct_ixia_connections=[
            taac_types.DirectIxiaConnection(
                interface="eth2/1/1",  # Downlink interface
                ixia_chassis_ip=IXIA06_CHASSIS_IP,
                ixia_port="1/19",
            ),
            taac_types.DirectIxiaConnection(
                interface="eth2/3/1",  # Rogue interface (BGP + ECMP)
                ixia_chassis_ip=IXIA06_CHASSIS_IP,
                ixia_port="1/20",
            ),
            taac_types.DirectIxiaConnection(
                interface="eth3/1/1",  # Remote interface
                ixia_chassis_ip=IXIA06_CHASSIS_IP,
                ixia_port="1/11",
            ),
        ],
        ixia_remote_interface="eth3/1/1",
        ixia_remote_ic_parent_network_v6="2401:db00:206a:8",
    )
)
