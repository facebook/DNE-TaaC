# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""FBOSS hardening TestConfig builders for Wedge100S and Wedge400C.

Provides ``get_test_config_wedge400c_fboss_hardening`` and
``get_test_config_wedge100s_fboss_hardening`` plus the supporting
``create_change_vlan_pyfuncs`` helper. Both TestConfigs run the FBOSS hardening
3-minute longevity playbook over a single-DUT mimic BGP topology.
"""

import json

from ixia.ixia import types as ixia_types
from taac.playbooks.playbook_definitions import (
    create_fboss_hardening_3_min_longevity_playbook,
)
from taac.task_definitions import (
    create_add_stress_static_routes_task,
    create_configure_parallel_bgp_peers_task,
    create_coop_apply_patchers_task,
    create_coop_register_patcher_task,
    create_wait_for_agent_convergence_task,
)
from taac.test_as_a_config.types import (
    BasicPortConfig,
    BasicTrafficItemConfig,
    BgpConfig,
    DeviceGroupConfig,
    Endpoint,
    IpAddressesConfig,
    RouteScale,
    RouteScaleSpec,
    TestConfig,
    TrafficEndpoint,
)


def get_test_config_wedge400c_fboss_hardening(
    test_config_name,
    device_name,
    peergroup_uplink_mimic,
    peergroup_downlink_mimic,
    ixia_downlink_interface,
    ixia_uplink_interface,
    ixia_downlink_ic_parent_network_v6,
    ixia_uplink_ic_parent_network_v6,
    prefix_limit,
    per_peer_max_route_limit,
    downlink_peer_count,
    uplink_peer_count,
    remote_downlink_as_4byte,
    remote_uplink_as_4byte,
    ixia_downlink_prefix_count_v6,
    ixia_downlink_communities,
    ixia_uplink_communities,
    ixia_uplink_prefix_count_v6,
    uplink_peer_tag,
    downlink_peer_tag,
    ecmp_group_limit,
    port_id_vlan_map,
    cp_stressing_network_index_prefix_count,
    direct_ixia_connections=None,
):
    """Build the Wedge400C FBOSS hardening TestConfig.

    Single-DUT TestConfig for the Wedge400C platform that drives the
    ``create_fboss_hardening_3_min_longevity_playbook`` over an uplink/downlink mimic
    BGP topology with V6 prefixes and communities. Used to qualify FBOSS agent stability
    on Wedge400C in the ``dne.test`` basset pool.

    Args:
        test_config_name: Name to register in the TestConfig (CLI-callable).
        device_name: Wedge400C DUT hostname.
        peergroup_uplink_mimic / peergroup_downlink_mimic: BGP peer-group names.
        ixia_downlink_interface / ixia_uplink_interface: DUT-facing IXIA ports.
        ixia_downlink_ic_parent_network_v6 / ixia_uplink_ic_parent_network_v6:
            IXIA-side parent IPv6 networks per interface.
        prefix_limit / per_peer_max_route_limit: Per-peer prefix/route limits.
        downlink_peer_count / uplink_peer_count: Mimic peer counts.
        remote_downlink_as_4byte / remote_uplink_as_4byte: Remote AS numbers (4-byte).
        ixia_downlink_prefix_count_v6 / ixia_uplink_prefix_count_v6: Prefixes per peer.
        ixia_downlink_communities / ixia_uplink_communities: BGP community lists.
        uplink_peer_tag / downlink_peer_tag: Logical tags for peer-group selection.
        ecmp_group_limit: ECMP-group cap programmed on the DUT.
        port_id_vlan_map: Mapping from port ID to VLAN; consumed by VLAN-change pyfuncs.
        cp_stressing_network_index_prefix_count: Prefix count used by the control-plane
            stressing test phase.
        direct_ixia_connections: Optional explicit direct-IXIA connection mapping.

    Returns:
        TestConfig: Wedge400C hardening TestConfig.
    """
    return TestConfig(
        name=test_config_name,
        basset_pool="dne.test",
        endpoints=[
            Endpoint(
                name=device_name,
                ixia_ports=[ixia_downlink_interface, ixia_uplink_interface],
                dut=True,
                direct_ixia_connections=direct_ixia_connections
                if direct_ixia_connections
                else [],
            ),
        ],
        setup_tasks=[
            # *create_change_vlan_pyfuncs(port_id_vlan_map, device_name),
            # create_coop_register_patcher_task(
            #     hostname=device_name,
            #     config_name="bgpcpp",
            #     patcher_name="a_remove_bgp_peers",
            #     task_name="remove_bgp_peers",
            #     patcher_args={"delete_all": "True"},
            # ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="agent",
                patcher_name="change_port_vlan_1",
                task_name="change_port_vlan",
                patcher_args={
                    "81": "2000",
                },
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="agent",
                patcher_name="change_port_vlan_2",
                task_name="change_port_vlan",
                patcher_args={
                    "89": "2000",
                },
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="agent",
                patcher_name="change_port_vlan_3",
                task_name="change_port_vlan",
                patcher_args={
                    "121": "2000",
                },
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="configure_bgp_switch_limit",
                task_name="configure_bgp_switch_limit",
                patcher_args={
                    "prefix_limit": prefix_limit,
                },
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="update_peer_group_patcher_RSW-FSW-V6_Uplink",
                task_name="configure_bgp_peer_group",
                patcher_args={
                    "name": "RSW-FSW-V6",
                    "attributes_to_update_json": json.dumps(
                        {
                            "disable_ipv4_afi": "True",
                            "v4_over_v6_nexthop": "False",
                            "is_passive": "False",
                        }
                    ),
                },
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="add_peer_group_patcher_RSW-FSW-V4",
                task_name="add_peer_group_patcher",
                patcher_args={
                    "name": "RSW-FSW-V4",
                    "description": "BGP peering Uplink IPv4 sessions",
                    "next_hop_self": "True",
                    "disable_ipv4_afi": "False",
                    "disable_ipv6_afi": "True",
                    "is_confed_peer": "True",
                    "peer_tag": uplink_peer_tag,
                    "ingress_policy_name": f"PROPAGATE_{peergroup_uplink_mimic}_IN",
                    "egress_policy_name": f"PROPAGATE_{peergroup_uplink_mimic}_OUT",
                    "bgp_peer_timers_hold_time_seconds": "30",
                    "bgp_peer_timers_keep_alive_seconds": "10",
                    "bgp_peer_timers_out_delay_seconds": "7",
                    "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                    "max_routes": per_peer_max_route_limit,
                    "warning_only": "True",
                    "warning_limit": "0",
                    "link_bandwidth_bps": "auto",
                    "v4_over_v6_nexthop": "False",
                    "is_passive": "False",
                },
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_RSW_SLB_IN",
                task_name="add_bgp_policy_match_prefix_to_propagate_routes",
                patcher_args={
                    "matching_prefix": "5000::/16",
                    "in_stmt_name": "PROPAGATE_RSW_SLB_IN",
                    "out_stmt_name": "RANDOM",
                },
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_RSW_FSW_OUT",
                task_name="add_bgp_policy_match_prefix_to_propagate_routes",
                patcher_args={
                    "matching_prefix": "5000::/16",
                    "in_stmt_name": "RANDOM",
                    "out_stmt_name": "PROPAGATE_RSW_FSW_OUT",
                },
            ),
            create_coop_apply_patchers_task(
                hostnames=[device_name],
                config_name="bgpcpp",
            ),
            create_add_stress_static_routes_task(
                hostname=device_name,
                route_count=ecmp_group_limit,
                nh_prefix_1=f"{ixia_uplink_ic_parent_network_v6}::a000/80",
                nh_prefix_2=f"{ixia_downlink_ic_parent_network_v6}::a000/64",
                lb_prefix_agg="6000:ab::/32",
                nh_common_last_hextet="a000",
            ),
            create_wait_for_agent_convergence_task(
                hostnames=[device_name],
            ),
            create_configure_parallel_bgp_peers_task(
                hostname=device_name,
                configure_vlans_patcher_name="configure_vlans_patcher_name_uplink",
                add_bgp_peers_patcher_name="add_bgp_peers_patcher_name_uplink",
                config_json=json.dumps(
                    {
                        ixia_uplink_interface: [
                            {
                                "starting_ip": f"{ixia_uplink_ic_parent_network_v6}::10",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "Uplink IPv6 Peers",
                                "peer_group_name": "RSW-FSW-V6",
                                "num_sessions": uplink_peer_count,
                                "remote_as_4_byte": remote_uplink_as_4byte,
                                "remote_as_4_byte_step": 0,
                                "gateway_starting_ip": f"{ixia_uplink_ic_parent_network_v6}::11",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            {
                                "starting_ip": "10.164.28.0",
                                "increment_ip": "0.0.0.2",
                                "prefix_length": 31,
                                "description": "Uplink IPv4 Peers",
                                "peer_group_name": "RSW-FSW-V4",
                                "num_sessions": uplink_peer_count,
                                "remote_as_4_byte": remote_uplink_as_4byte,
                                "remote_as_4_byte_step": 0,
                                "gateway_starting_ip": "10.164.28.1",
                                "gateway_increment_ip": "0.0.0.2",
                            },
                        ]
                    }
                ),
            ),
            create_coop_apply_patchers_task(
                hostnames=[device_name],
                do_warmboot=True,
            ),
        ],
        teardown_tasks=[
            # create_coop_unregister_patchers_task(
            #     hostnames=device_name,
            # ),
        ],
        basic_port_configs=[
            BasicPortConfig(
                endpoint=f"{device_name}:{ixia_downlink_interface}",
                device_group_configs=[
                    DeviceGroupConfig(
                        device_group_index=0,
                        multiplier=downlink_peer_count,
                        v6_addresses_config=IpAddressesConfig(
                            starting_ip=f"{ixia_downlink_ic_parent_network_v6}::11",
                            increment_ip="0:0:0:0::2",
                            # todo(remove hardcoding)
                            gateway_starting_ip=f"{ixia_downlink_ic_parent_network_v6}::a",
                            gateway_increment_ip="0:0:0:0::0",
                            mask=64,
                        ),
                        v6_bgp_config=BgpConfig(
                            local_as_4_bytes=remote_downlink_as_4byte,
                            local_as_increment=0,
                            enable_4_byte_local_as=True,
                            is_confed=False,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            route_scales=[
                                RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=RouteScale(
                                        multiplier=1,
                                        prefix_count=ixia_downlink_prefix_count_v6,
                                        prefix_length=64,
                                        starting_prefixes="4000:a::",
                                        prefix_step="0:0:1:0::0",
                                        bgp_communities=ixia_downlink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    ),
                                ),
                                RouteScaleSpec(
                                    network_group_index=1,
                                    v6_route_scale=RouteScale(
                                        multiplier=1,
                                        prefix_count=cp_stressing_network_index_prefix_count,
                                        prefix_length=64,
                                        starting_prefixes="5000:ff::",
                                        prefix_step="0:0:1:0::0",
                                        bgp_communities=[
                                            "65529:666",
                                        ],
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    ),
                                ),
                            ],
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_index=1,
                        multiplier=200,
                        v6_addresses_config=IpAddressesConfig(
                            starting_ip=f"{ixia_downlink_ic_parent_network_v6}::a000",
                            increment_ip="::1",
                            gateway_starting_ip=f"{ixia_downlink_ic_parent_network_v6}::a",
                            mask=64,
                        ),
                    ),
                ],
            ),
            BasicPortConfig(
                endpoint=f"{device_name}:{ixia_uplink_interface}",
                device_group_configs=[
                    DeviceGroupConfig(
                        device_group_index=0,
                        multiplier=uplink_peer_count,
                        v6_addresses_config=IpAddressesConfig(
                            starting_ip=f"{ixia_uplink_ic_parent_network_v6}::11",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_uplink_ic_parent_network_v6}::10",
                            gateway_increment_ip="0:0:0:0::2",
                            mask=127,
                        ),
                        v6_bgp_config=BgpConfig(
                            local_as_4_bytes=remote_uplink_as_4byte,
                            local_as_increment=0,
                            enable_4_byte_local_as=True,
                            is_confed=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            route_scales=[
                                RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=RouteScale(
                                        multiplier=1,
                                        prefix_count=ixia_uplink_prefix_count_v6,
                                        prefix_length=64,
                                        starting_prefixes="4000:b::",
                                        prefix_step="0:0:1:0::0",
                                        bgp_communities=ixia_uplink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    ),
                                ),
                            ],
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_index=1,
                        multiplier=uplink_peer_count,
                        v4_addresses_config=IpAddressesConfig(
                            starting_ip="10.164.28.1",
                            increment_ip="0.0.0.2",
                            gateway_starting_ip="10.164.28.0",
                            gateway_increment_ip="0.0.0.2",
                            mask=31,
                        ),
                        v4_bgp_config=BgpConfig(
                            local_as_4_bytes=remote_uplink_as_4byte,
                            local_as_increment=0,
                            enable_4_byte_local_as=True,
                            is_confed=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                            route_scales=[
                                RouteScaleSpec(
                                    network_group_index=0,
                                    v4_route_scale=RouteScale(
                                        multiplier=1,
                                        # todo: Change hardcoding
                                        prefix_count=1000,
                                        prefix_length=30,
                                        starting_prefixes="10.100.75.0",
                                        prefix_step="0.0.0.0",
                                        bgp_communities=ixia_uplink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                    ),
                                ),
                            ],
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_index=2,
                        multiplier=3200,
                        v6_addresses_config=IpAddressesConfig(
                            starting_ip=f"{ixia_uplink_ic_parent_network_v6}::a000",
                            increment_ip="::1",
                            gateway_starting_ip=f"{ixia_uplink_ic_parent_network_v6}::1",
                            mask=80,
                        ),
                    ),
                ],
            ),
        ],
        basic_traffic_item_configs=[
            BasicTrafficItemConfig(
                name="V6_DIRECTIONAL_TRAFFIC_FOR_AMONG_NETWORK_GROUP_0",
                bidirectional=True,
                merge_destinations=True,
                line_rate=10,
                src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
                src_endpoints=[
                    TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        network_group_index=0,
                    )
                ],
                dest_endpoints=[
                    TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        network_group_index=0,
                    )
                ],
                traffic_type=ixia_types.TrafficType.IPV6,
                tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
            ),
            # BasicTrafficItemConfig(
            #     name="V4_DIRECTIONAL_TRAFFIC_FOR_AMONG_NETWORK_GROUP_0",
            #     bidirectional=True,
            #     merge_destinations=True,
            #     line_rate=10,
            #     src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
            #     src_endpoints=QZD_SINGLE_NODE_CONVEYOUR_UPLINK_ENPOINTS_V4,
            #     dest_endpoints=QZD_SINGLE_NODE_CONVEYOUR_DOWNLINK_ENPOINTS_V4,
            #     traffic_type=ixia_types.TrafficType.IPV4,
            #     tracking_types=[
            #         ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM
            #     ],
            # ),
        ],
        # Deprecated - define at playbook level
        # postchecks=[
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
        #         input_json=thrift_to_json(
        #             hc_types.IxiaPacketLossHealthCheckIn(
        #                 thresholds=[hc_types.PacketLossThreshold(str_value="0.1")],
        #                 clear_traffic_stats=True,
        #             )
        #         ),
        #     ),
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.UNCLEAN_EXIT_CHECK,
        #         check_params=Params(
        #             jq_params={
        #                 "start_time": ".test_case_start_time",
        #             }
        #         ),
        #     ),
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.MEMORY_UTILIZATION_CHECK,
        #         check_params=Params(
        #             json_params=json.dumps(
        #                 {
        #                     "threshold": Gigabyte.GIG_4_POINT_3.value,
        #                 }
        #             ),
        #         ),
        #     ),
        # ],
        # Deprecated - define at playbook level
        # prechecks=[
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
        #         input_json=thrift_to_json(
        #             hc_types.IxiaPacketLossHealthCheckIn(
        #                 clear_traffic_stats=True,
        #             )
        #         ),
        #     ),
        # ],
        playbooks=[
            create_fboss_hardening_3_min_longevity_playbook(),
        ],
    )


def create_change_vlan_pyfuncs(port_id_vlan_map, device_name):
    """Build per-port VLAN-change COOP patcher tasks.

    Generates one ``register_patcher`` task per (port_id, vlan) pair so the COOP harness
    can re-apply per-port VLAN changes during FBOSS hardening setup.

    Args:
        port_id_vlan_map: Mapping from port ID (int) to target VLAN (int).
        device_name: Hostname to register the patchers against.

    Returns:
        list: COOP register-patcher task pyfuncs, one per port_id.
    """
    pyfuncs = []
    for port_id, vlan in port_id_vlan_map.items():
        pyfunc = create_coop_register_patcher_task(
            hostname=device_name,
            config_name="agent",
            patcher_name=f"change_port_vlan_{port_id}",
            task_name="change_port_vlan",
            patcher_args={
                str(port_id): str(vlan),
            },
        )
        pyfuncs.append(pyfunc)
    return pyfuncs


def get_test_config_wedge100s_fboss_hardening(
    test_config_name,
    device_name,
    peergroup_uplink_mimic,
    peergroup_downlink_mimic,
    ixia_downlink_interface,
    ixia_uplink_interface,
    ixia_downlink_ic_parent_network_v6,
    ixia_uplink_ic_parent_network_v6,
    prefix_limit,
    per_peer_max_route_limit,
    downlink_peer_count,
    uplink_peer_count,
    remote_downlink_as_4byte,
    remote_uplink_as_4byte,
    ixia_downlink_prefix_count_v6,
    ixia_downlink_communities,
    ixia_uplink_communities,
    ixia_uplink_prefix_count_v6,
    uplink_peer_tag,
    downlink_peer_tag,
    ecmp_group_limit,
    port_id_vlan_map,
    cp_stressing_network_index_prefix_count,
    direct_ixia_connections=None,
):
    """Build the Wedge100S FBOSS hardening TestConfig.

    Parallel of ``get_test_config_wedge400c_fboss_hardening`` for the older Wedge100S
    platform; same uplink/downlink mimic BGP topology, V6 prefixes/communities, and
    longevity playbook, but pinned to Wedge100S setup tasks (most of which are commented
    out historically and re-enabled per qualification campaign).

    Args:
        test_config_name: Name to register in the TestConfig (CLI-callable).
        device_name: Wedge100S DUT hostname.
        peergroup_uplink_mimic / peergroup_downlink_mimic: BGP peer-group names.
        ixia_downlink_interface / ixia_uplink_interface: DUT-facing IXIA ports.
        ixia_downlink_ic_parent_network_v6 / ixia_uplink_ic_parent_network_v6:
            IXIA-side parent IPv6 networks per interface.
        prefix_limit / per_peer_max_route_limit: Per-peer prefix/route limits.
        downlink_peer_count / uplink_peer_count: Mimic peer counts.
        remote_downlink_as_4byte / remote_uplink_as_4byte: Remote AS numbers (4-byte).
        ixia_downlink_prefix_count_v6 / ixia_uplink_prefix_count_v6: Prefixes per peer.
        ixia_downlink_communities / ixia_uplink_communities: BGP community lists.
        uplink_peer_tag / downlink_peer_tag: Logical tags for peer-group selection.
        ecmp_group_limit: ECMP-group cap programmed on the DUT.
        port_id_vlan_map: Mapping from port ID to VLAN; consumed by VLAN-change pyfuncs.
        cp_stressing_network_index_prefix_count: Prefix count used by the control-plane
            stressing test phase.
        direct_ixia_connections: Optional explicit direct-IXIA connection mapping.

    Returns:
        TestConfig: Wedge100S hardening TestConfig.
    """
    return TestConfig(
        name=test_config_name,
        basset_pool="dne.test",
        endpoints=[
            Endpoint(
                name=device_name,
                ixia_ports=[ixia_downlink_interface, ixia_uplink_interface],
                dut=True,
                direct_ixia_connections=direct_ixia_connections
                if direct_ixia_connections
                else [],
            ),
        ],
        setup_tasks=[
            # create_coop_register_patcher_task(
            #     hostname=device_name,
            #     config_name="bgpcpp",
            #     patcher_name="a_remove_bgp_peers",
            #     task_name="remove_bgp_peers",
            #     patcher_args={"delete_all": "True"},
            # ),
            # *create_change_vlan_pyfuncs(port_id_vlan_map, device_name),
            # create_coop_register_patcher_task(
            #     hostname=device_name,
            #     config_name="bgpcpp",
            #     patcher_name="configure_bgp_switch_limit",
            #     task_name="configure_bgp_switch_limit",
            #     patcher_args={
            #         "prefix_limit": prefix_limit,
            #     },
            # ),
            # create_coop_register_patcher_task(
            #     hostname=device_name,
            #     config_name="bgpcpp",
            #     patcher_name="update_peer_group_patcher_RSW-FSW-V6_Uplink",
            #     task_name="configure_bgp_peer_group",
            #     patcher_args={
            #         "name": "RSW-FSW-V6",
            #         "attributes_to_update_json": json.dumps(
            #             {
            #                 "disable_ipv4_afi": "True",
            #                 "v4_over_v6_nexthop": "False",
            #                 "is_passive": "False",
            #             }
            #         ),
            #     },
            # ),
            # create_coop_register_patcher_task(
            #     hostname=device_name,
            #     config_name="bgpcpp",
            #     patcher_name="add_peer_group_patcher_RSW-FSW-V4",
            #     task_name="add_peer_group_patcher",
            #     patcher_args={
            #         "name": "RSW-FSW-V4",
            #         "description": "BGP peering Uplink IPv4 sessions",
            #         "next_hop_self": "True",
            #         "disable_ipv4_afi": "False",
            #         "disable_ipv6_afi": "True",
            #         "is_confed_peer": "True",
            #         "peer_tag": uplink_peer_tag,
            #         "ingress_policy_name": f"PROPAGATE_{peergroup_uplink_mimic}_IN",
            #         "egress_policy_name": f"PROPAGATE_{peergroup_uplink_mimic}_OUT",
            #         "bgp_peer_timers_hold_time_seconds": "30",
            #         "bgp_peer_timers_keep_alive_seconds": "10",
            #         "bgp_peer_timers_out_delay_seconds": "7",
            #         "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
            #         "max_routes": per_peer_max_route_limit,
            #         "warning_only": "True",
            #         "warning_limit": "0",
            #         "link_bandwidth_bps": "auto",
            #         "v4_over_v6_nexthop": "False",
            #         "is_passive": "False",
            #     },
            # ),
            # create_coop_register_patcher_task(
            #     hostname=device_name,
            #     config_name="bgpcpp",
            #     patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_RSW_SLB_IN",
            #     task_name="add_bgp_policy_match_prefix_to_propagate_routes",
            #     patcher_args={
            #         "matching_prefix": "5000::/16",
            #         "in_stmt_name": "PROPAGATE_RSW_SLB_IN",
            #         "out_stmt_name": "RANDOM",
            #     },
            # ),
            # create_coop_register_patcher_task(
            #     hostname=device_name,
            #     config_name="bgpcpp",
            #     patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_RSW_FSW_OUT",
            #     task_name="add_bgp_policy_match_prefix_to_propagate_routes",
            #     patcher_args={
            #         "matching_prefix": "5000::/16",
            #         "in_stmt_name": "RANDOM",
            #         "out_stmt_name": "PROPAGATE_RSW_FSW_OUT",
            #     },
            # ),
            # create_coop_apply_patchers_task(
            #     hostnames=[device_name],
            #     config_name="bgpcpp",
            # ),
            # Task(
            #     task_name="add_stress_static_routes",
            #     params=Params(
            #         json_params=json.dumps(
            #             {
            #                 "hostname": device_name,
            #                 "nh_prefix_1": f"{ixia_uplink_ic_parent_network_v6}::a000/80",
            #                 "nh_prefix_2": f"{ixia_downlink_ic_parent_network_v6}::a000/64",
            #                 "lb_prefix_agg": "6000:ab::/32",
            #                 "nh_common_last_hextet": "a000",
            #                 "route_count": ecmp_group_limit,
            #             }
            #         ),
            #     ),
            # ),
            # create_wait_for_agent_convergence_task(
            #     hostnames=[device_name],
            # ),
            # Task(
            #     task_name="configure_parallel_bgp_peers",
            #     params=Params(
            #         json_params=json.dumps(
            #             {
            #                 "hostname": device_name,
            #                 "configure_vlans_patcher_name": "configure_vlans_patcher_name_uplink",
            #                 "add_bgp_peers_patcher_name": "add_bgp_peers_patcher_name_uplink",
            #                 "config_json": json.dumps(
            #                     {
            #                         ixia_uplink_interface: [
            #                             {
            #                                 "starting_ip": f"{ixia_uplink_ic_parent_network_v6}::10",
            #                                 "increment_ip": "0:0:0:0::2",
            #                                 "prefix_length": 127,
            #                                 "description": "Uplink IPv6 Peers",
            #                                 "peer_group_name": "RSW-FSW-V6",
            #                                 "num_sessions": uplink_peer_count,
            #                                 "remote_as_4_byte": remote_uplink_as_4byte,
            #                                 "remote_as_4_byte_step": 0,
            #                                 "gateway_starting_ip": f"{ixia_uplink_ic_parent_network_v6}::11",
            #                                 "gateway_increment_ip": "0:0:0:0::2",
            #                             },
            #                             {
            #                                 "starting_ip": "10.164.28.0",
            #                                 "increment_ip": "0.0.0.2",
            #                                 "prefix_length": 31,
            #                                 "description": "Uplink IPv4 Peers",
            #                                 "peer_group_name": "RSW-FSW-V4",
            #                                 "num_sessions": uplink_peer_count,
            #                                 "remote_as_4_byte": remote_uplink_as_4byte,
            #                                 "remote_as_4_byte_step": 0,
            #                                 "gateway_starting_ip": "10.164.28.1",
            #                                 "gateway_increment_ip": "0.0.0.2",
            #                             },
            #                         ]
            #                     }
            #                 ),
            #             }
            #         ),
            #     ),
            # ),
            # Task(
            #     task_name="coop_apply_patchers",
            #     params=Params(
            #         json_params=json.dumps(
            #             {
            #                 "hostnames": [device_name],
            #                 "do_warmboot": True,
            #             }
            #         ),
            #     ),
            # ),
        ],
        teardown_tasks=[
            # create_coop_unregister_patchers_task(
            #     hostnames=device_name,
            # ),
        ],
        basic_port_configs=[
            BasicPortConfig(
                endpoint=f"{device_name}:{ixia_downlink_interface}",
                device_group_configs=[
                    DeviceGroupConfig(
                        device_group_index=0,
                        multiplier=downlink_peer_count,
                        v6_addresses_config=IpAddressesConfig(
                            starting_ip=f"{ixia_downlink_ic_parent_network_v6}::11",
                            increment_ip="0:0:0:0::2",
                            # todo(remove hardcoding)
                            gateway_starting_ip=f"{ixia_downlink_ic_parent_network_v6}::a",
                            gateway_increment_ip="0:0:0:0::0",
                            mask=64,
                        ),
                        v6_bgp_config=BgpConfig(
                            local_as_4_bytes=remote_downlink_as_4byte,
                            local_as_increment=0,
                            enable_4_byte_local_as=True,
                            is_confed=False,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            route_scales=[
                                RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=RouteScale(
                                        multiplier=1,
                                        prefix_count=ixia_downlink_prefix_count_v6,
                                        prefix_length=64,
                                        starting_prefixes="4000:a::",
                                        prefix_step="0:0:1:0::0",
                                        bgp_communities=ixia_downlink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    ),
                                ),
                                RouteScaleSpec(
                                    network_group_index=1,
                                    v6_route_scale=RouteScale(
                                        multiplier=25,
                                        prefix_count=cp_stressing_network_index_prefix_count,
                                        prefix_length=64,
                                        starting_prefixes="5000:ff::",
                                        prefix_step="0:0:1:0::0",
                                        bgp_communities=[
                                            "65529:666",
                                        ],
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    ),
                                ),
                            ],
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_index=1,
                        multiplier=200,
                        v6_addresses_config=IpAddressesConfig(
                            starting_ip=f"{ixia_downlink_ic_parent_network_v6}::a000",
                            increment_ip="::1",
                            gateway_starting_ip=f"{ixia_downlink_ic_parent_network_v6}::a",
                            mask=64,
                        ),
                    ),
                ],
            ),
            BasicPortConfig(
                endpoint=f"{device_name}:{ixia_uplink_interface}",
                device_group_configs=[
                    DeviceGroupConfig(
                        device_group_index=0,
                        multiplier=uplink_peer_count,
                        v6_addresses_config=IpAddressesConfig(
                            starting_ip=f"{ixia_uplink_ic_parent_network_v6}::11",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_uplink_ic_parent_network_v6}::10",
                            gateway_increment_ip="0:0:0:0::2",
                            mask=127,
                        ),
                        v6_bgp_config=BgpConfig(
                            local_as_4_bytes=remote_uplink_as_4byte,
                            local_as_increment=0,
                            enable_4_byte_local_as=True,
                            is_confed=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            route_scales=[
                                RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=RouteScale(
                                        multiplier=1,
                                        prefix_count=ixia_uplink_prefix_count_v6,
                                        prefix_length=64,
                                        starting_prefixes="4000:b::",
                                        prefix_step="0:0:1:0::0",
                                        bgp_communities=ixia_uplink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    ),
                                ),
                            ],
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_index=1,
                        multiplier=uplink_peer_count,
                        v4_addresses_config=IpAddressesConfig(
                            starting_ip="10.164.28.1",
                            increment_ip="0.0.0.2",
                            gateway_starting_ip="10.164.28.0",
                            gateway_increment_ip="0.0.0.2",
                            mask=31,
                        ),
                        v4_bgp_config=BgpConfig(
                            local_as_4_bytes=remote_uplink_as_4byte,
                            local_as_increment=0,
                            enable_4_byte_local_as=True,
                            is_confed=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                            route_scales=[
                                RouteScaleSpec(
                                    network_group_index=0,
                                    v4_route_scale=RouteScale(
                                        multiplier=1,
                                        # todo: Change hardcoding
                                        prefix_count=1000,
                                        prefix_length=30,
                                        starting_prefixes="10.100.75.0",
                                        prefix_step="0.0.0.0",
                                        bgp_communities=ixia_uplink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                    ),
                                ),
                            ],
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_index=2,
                        multiplier=3200,
                        v6_addresses_config=IpAddressesConfig(
                            starting_ip=f"{ixia_uplink_ic_parent_network_v6}::a000",
                            increment_ip="::1",
                            gateway_starting_ip=f"{ixia_uplink_ic_parent_network_v6}::d",
                            mask=80,
                        ),
                    ),
                ],
            ),
        ],
        basic_traffic_item_configs=[
            BasicTrafficItemConfig(
                name="V6_DIRECTIONAL_TRAFFIC_FOR_AMONG_NETWORK_GROUP_0",
                bidirectional=True,
                merge_destinations=True,
                line_rate=10,
                src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
                src_endpoints=[
                    TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        network_group_index=0,
                    )
                ],
                dest_endpoints=[
                    TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        network_group_index=0,
                    )
                ],
                traffic_type=ixia_types.TrafficType.IPV6,
                tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
            ),
            # BasicTrafficItemConfig(
            #     name="V4_DIRECTIONAL_TRAFFIC_FOR_AMONG_NETWORK_GROUP_0",
            #     bidirectional=True,
            #     merge_destinations=True,
            #     line_rate=10,
            #     src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
            #     src_endpoints=QZD_SINGLE_NODE_CONVEYOUR_UPLINK_ENPOINTS_V4,
            #     dest_endpoints=QZD_SINGLE_NODE_CONVEYOUR_DOWNLINK_ENPOINTS_V4,
            #     traffic_type=ixia_types.TrafficType.IPV4,
            #     tracking_types=[
            #         ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM
            #     ],
            # ),
        ],
        # Deprecated - define at playbook level
        # postchecks=[
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
        #         input_json=thrift_to_json(
        #             hc_types.IxiaPacketLossHealthCheckIn(
        #                 thresholds=[hc_types.PacketLossThreshold(str_value="0.1")],
        #                 clear_traffic_stats=True,
        #             )
        #         ),
        #     ),
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.UNCLEAN_EXIT_CHECK,
        #         check_params=Params(
        #             jq_params={
        #                 "start_time": ".test_case_start_time",
        #             }
        #         ),
        #     ),
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.MEMORY_UTILIZATION_CHECK,
        #         check_params=Params(
        #             json_params=json.dumps(
        #                 {
        #                     "threshold": Gigabyte.GIG_4_POINT_3.value,
        #                 }
        #             ),
        #         ),
        #     ),
        # ],
        # Deprecated - define at playbook level
        # prechecks=[
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
        #         input_json=thrift_to_json(
        #             hc_types.IxiaPacketLossHealthCheckIn(
        #                 clear_traffic_stats=True,
        #             )
        #         ),
        #     ),
        # ],
        playbooks=[
            create_fboss_hardening_3_min_longevity_playbook(),
        ],
    )
