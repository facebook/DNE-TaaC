# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""TestConfig builder for FBOSS Optics New Product Introduction (NPI).

Used to qualify candidate optics on a back-to-back DUT + Z-end pair (one IXIA port per
side). Drives BGP peering through the optic under test plus the optics NPI playbook
chain (flap + longevity + traffic verification).
"""

import json

from ixia.ixia import types as ixia_types
from taac.playbooks.playbook_definitions import (
    build_optics_npi_playbooks,
)
from taac.task_definitions import (
    create_configure_parallel_bgp_peers_task,
    create_coop_apply_patchers_task,
    create_coop_register_patcher_task,
    create_coop_unregister_patchers_task,
    create_wait_for_agent_convergence_task,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import TestConfig


def create_optics_npi_test_config(
    test_config_name,
    dut_device_name,
    dut_device_mac_address,
    ixia_connected_interface_in_dut,
    z_end_device_name,
    ixia_connected_interface_in_z_end_device,
    route_map_uplink_ingress,
    route_map_uplink_egress,
    route_map_downlink_ingress,
    route_map_downlink_egress,
    peergroup_uplink_mimic_v6,
    peergroup_downlink_mimic_v6,
    peergroup_uplink_mimic_v4,
    peergroup_downlink_mimic_v4,
    ixia_uplink_ic_parent_network_v6,
    ixia_downlink_ic_parent_network_v6,
    ixia_uplink_ic_parent_network_v4,
    ixia_downlink_ic_parent_network_v4,
    is_uplink_peer_confed,
    is_downlink_peer_confed,
    uplink_peer_tag,
    downlink_peer_tag,
    remote_uplink_as_4byte,
    remote_downlink_as_4byte,
    prefix_limit,
    per_peer_max_route_limit,
    downlink_peer_count,
    uplink_peer_count,
    ixia_uplink_prefix_count_v6,
    ixia_downlink_prefix_count_v6,
    ixia_uplink_prefix_count_v4,
    ixia_downlink_prefix_count_v4,
    ixia_uplink_communities,
    ixia_downlink_communities,
    basset_pool,
):
    """Build a two-DUT optics NPI TestConfig for back-to-back optics qualification.

    Used by the optics New Product Introduction (NPI) flow: a DUT and a Z-end peer are
    connected back-to-back through a candidate optic, with IXIA on a separate port. The
    config sets up uplink/downlink mimic BGP peer groups (V4 + V6 SAFI), then runs the
    ``build_optics_npi_playbooks`` chain (optic flap + longevity + traffic checks).

    Args:
        test_config_name: Name to register in the TestConfig (CLI-callable).
        dut_device_name / dut_device_mac_address: DUT hostname + local MAC.
        ixia_connected_interface_in_dut: DUT port connected to IXIA.
        z_end_device_name: Z-end (peer) hostname.
        ixia_connected_interface_in_z_end_device: Z-end port connected to IXIA.
        route_map_*_ingress / _egress: Inbound/outbound policy per direction.
        peergroup_*_mimic_v6 / _v4: BGP peer-group names per direction and AFI.
        ixia_*_ic_parent_network_v6 / _v4: IXIA-side parent networks per interface.
        is_uplink_peer_confed / is_downlink_peer_confed: Confederation peer flags.
        uplink_peer_tag / downlink_peer_tag: Logical tags for peer-group selection.
        remote_uplink_as_4byte / remote_downlink_as_4byte: Remote AS numbers (4-byte).
        prefix_limit / per_peer_max_route_limit: Per-peer prefix/route caps.
        downlink_peer_count / uplink_peer_count: Mimic peer counts.
        ixia_*_prefix_count_v6 / _v4: Prefix counts to advertise per peer group.
        ixia_uplink_communities / ixia_downlink_communities: BGP community lists.
        basset_pool: Basset pool to reserve devices from.

    Returns:
        TestConfig: Optics NPI TestConfig.
    """
    return TestConfig(
        name=test_config_name,
        basset_pool=basset_pool,
        endpoints=[
            taac_types.Endpoint(
                name=dut_device_name,
                ixia_ports=[ixia_connected_interface_in_dut],
                dut=True,
                mac_address=dut_device_mac_address,
            ),
            taac_types.Endpoint(
                name=z_end_device_name,
                ixia_ports=[ixia_connected_interface_in_z_end_device],
            ),
        ],
        # Deprecated - define at playbook level
        # postchecks=[
        #     PointInTimeHealthCheck(name=hc_types.CheckName.LLDP_CHECK),
        #     PointInTimeHealthCheck(name=hc_types.CheckName.PORT_STATE_CHECK),
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
        #         input_json=thrift_to_json(
        #             hc_types.IxiaPacketLossHealthCheckIn(
        #                 clear_traffic_stats=True,
        #             )
        #         ),
        #     ),
        # ],
        # Deprecated - define at playbook level
        # prechecks=[
        #     PointInTimeHealthCheck(name=hc_types.CheckName.LLDP_CHECK),
        #     PointInTimeHealthCheck(name=hc_types.CheckName.PORT_STATE_CHECK),
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
        #         input_json=thrift_to_json(
        #             hc_types.IxiaPacketLossHealthCheckIn(
        #                 clear_traffic_stats=True,
        #             )
        #         ),
        #     ),
        # ],
        setup_tasks=[
            create_coop_unregister_patchers_task(
                hostnames=[dut_device_name, z_end_device_name],
            ),
            create_coop_register_patcher_task(
                hostname=dut_device_name,
                config_name="bgpcpp",
                patcher_name="configure_bgp_switch_limit",
                task_name="coop_register_patcher",
                patcher_args={
                    "prefix_limit": prefix_limit,
                },
                py_func_name="configure_bgp_switch_limit",
            ),
            create_coop_register_patcher_task(
                hostname=z_end_device_name,
                config_name="bgpcpp",
                patcher_name="configure_bgp_switch_limit",
                task_name="coop_register_patcher",
                patcher_args={
                    "prefix_limit": prefix_limit,
                },
                py_func_name="configure_bgp_switch_limit",
            ),
            create_coop_register_patcher_task(
                hostname=dut_device_name,
                config_name="agent",
                patcher_name="enable_port_all_ixia_ports",
                task_name="coop_register_patcher",
                patcher_args={
                    f"{ixia_connected_interface_in_dut}": "enable",
                },
                py_func_name="change_port_admin_state",
            ),
            create_coop_register_patcher_task(
                hostname=z_end_device_name,
                config_name="agent",
                patcher_name="enable_port_all_ixia_ports",
                task_name="coop_register_patcher",
                patcher_args={
                    f"{ixia_connected_interface_in_z_end_device}": "enable",
                },
                py_func_name="change_port_admin_state",
            ),
            create_coop_register_patcher_task(
                hostname=dut_device_name,
                config_name="bgpcpp",
                patcher_name=f"update_peer_group_patcher_{peergroup_downlink_mimic_v6}_Downlink",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": peergroup_downlink_mimic_v6,
                    "attributes_to_update_json": json.dumps(
                        {
                            "disable_ipv4_afi": "True",
                            "v4_over_v6_nexthop": "False",
                            "is_passive": "False",
                            "is_confed_peer": is_downlink_peer_confed,
                            "max_routes": per_peer_max_route_limit,
                        }
                    ),
                },
                py_func_name="configure_bgp_peer_group",
            ),
            create_coop_register_patcher_task(
                hostname=z_end_device_name,
                config_name="bgpcpp",
                patcher_name=f"update_peer_group_patcher_{peergroup_uplink_mimic_v6}_Uplink",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": peergroup_uplink_mimic_v6,
                    "attributes_to_update_json": json.dumps(
                        {
                            "disable_ipv4_afi": "True",
                            "v4_over_v6_nexthop": "False",
                            "is_passive": "False",
                            "is_confed_peer": is_uplink_peer_confed,
                            "max_routes": per_peer_max_route_limit,
                        }
                    ),
                },
                py_func_name="configure_bgp_peer_group",
            ),
            create_coop_register_patcher_task(
                hostname=z_end_device_name,
                config_name="bgpcpp",
                patcher_name=f"add_peer_group_patcher_{peergroup_uplink_mimic_v4}",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": peergroup_uplink_mimic_v4,
                    "description": f"BGP peering from {uplink_peer_tag} to {z_end_device_name[:3].upper()}, IPv4 sessions",
                    "next_hop_self": "True",
                    "disable_ipv4_afi": "False",
                    "disable_ipv6_afi": "True",
                    "is_confed_peer": is_uplink_peer_confed,
                    "peer_tag": uplink_peer_tag,
                    "ingress_policy_name": route_map_uplink_ingress,
                    "egress_policy_name": route_map_uplink_egress,
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
                py_func_name="add_peer_group_patcher",
            ),
            create_coop_register_patcher_task(
                hostname=dut_device_name,
                config_name="bgpcpp",
                patcher_name=f"add_peer_group_patcher_{peergroup_downlink_mimic_v4}",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": peergroup_downlink_mimic_v4,
                    "description": f"BGP peering from {downlink_peer_tag} to {z_end_device_name[:3].upper()} , IPv4 sessions",
                    "next_hop_self": "True",
                    "disable_ipv4_afi": "False",
                    "disable_ipv6_afi": "True",
                    "is_confed_peer": is_downlink_peer_confed,
                    "ingress_policy_name": route_map_downlink_ingress,
                    "egress_policy_name": route_map_downlink_egress,
                    "bgp_peer_timers_hold_time_seconds": "30",
                    "bgp_peer_timers_keep_alive_seconds": "10",
                    "bgp_peer_timers_out_delay_seconds": "7",
                    "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                    "peer_tag": downlink_peer_tag,
                    "max_routes": per_peer_max_route_limit,
                    "warning_only": "True",
                    "warning_limit": "0",
                    "link_bandwidth_bps": "auto",
                    "v4_over_v6_nexthop": "False",
                    "is_passive": "False",
                },
                py_func_name="add_peer_group_patcher",
            ),
            create_coop_apply_patchers_task(
                hostnames=[dut_device_name, z_end_device_name],
                config_name="bgpcpp",
            ),
            create_configure_parallel_bgp_peers_task(
                hostname=dut_device_name,
                peer_configs=[
                    {
                        "configure_vlans_patcher_name": "configure_vlans_patcher_name_downlink",
                        "add_bgp_peers_patcher_name": "add_bgp_peers_patcher_name_downlink",
                        "config_json": json.dumps(
                            {
                                ixia_connected_interface_in_dut: [
                                    {
                                        "starting_ip": f"{ixia_downlink_ic_parent_network_v6}::10",
                                        "increment_ip": "0:0:0:0::2",
                                        "prefix_length": 127,
                                        "description": "Downlink IPv6 Peers",
                                        "peer_group_name": peergroup_downlink_mimic_v6,
                                        "num_sessions": downlink_peer_count,
                                        "remote_as_4_byte": remote_downlink_as_4byte,
                                        "remote_as_4_byte_step": 1,
                                        "gateway_starting_ip": f"{ixia_downlink_ic_parent_network_v6}::11",
                                        "gateway_increment_ip": "0:0:0:0::2",
                                    },
                                    {
                                        "starting_ip": f"{ixia_downlink_ic_parent_network_v4}.0",
                                        "increment_ip": "0.0.0.2",
                                        "prefix_length": 31,
                                        "description": "Downlink IPv4 Peers",
                                        "peer_group_name": peergroup_downlink_mimic_v4,
                                        "num_sessions": downlink_peer_count,
                                        "remote_as_4_byte": remote_downlink_as_4byte,
                                        "remote_as_4_byte_step": 1,
                                        "gateway_starting_ip": f"{ixia_downlink_ic_parent_network_v4}.1",
                                        "gateway_increment_ip": "0.0.0.2",
                                    },
                                ]
                            }
                        ),
                    }
                ],
            ),
            create_wait_for_agent_convergence_task(
                hostnames=[dut_device_name],
            ),
            create_configure_parallel_bgp_peers_task(
                hostname=z_end_device_name,
                peer_configs=[
                    {
                        "configure_vlans_patcher_name": "configure_vlans_patcher_name_uplink",
                        "add_bgp_peers_patcher_name": "add_bgp_peers_patcher_name_uplink",
                        "config_json": json.dumps(
                            {
                                ixia_connected_interface_in_z_end_device: [
                                    {
                                        "starting_ip": f"{ixia_uplink_ic_parent_network_v6}::10",
                                        "increment_ip": "0:0:0:0::2",
                                        "prefix_length": 127,
                                        "description": "Uplink IPv6 Peers",
                                        "peer_group_name": peergroup_uplink_mimic_v6,
                                        "num_sessions": uplink_peer_count,
                                        "remote_as_4_byte": remote_uplink_as_4byte,
                                        "remote_as_4_byte_step": 0,
                                        "gateway_starting_ip": f"{ixia_uplink_ic_parent_network_v6}::11",
                                        "gateway_increment_ip": "0:0:0:0::2",
                                    },
                                    {
                                        "starting_ip": f"{ixia_uplink_ic_parent_network_v4}.0",
                                        "increment_ip": "0.0.0.2",
                                        "prefix_length": 31,
                                        "description": "Uplink IPv4 Peers",
                                        "peer_group_name": peergroup_uplink_mimic_v4,
                                        "num_sessions": uplink_peer_count,
                                        "remote_as_4_byte": remote_uplink_as_4byte,
                                        "remote_as_4_byte_step": 0,
                                        "gateway_starting_ip": f"{ixia_uplink_ic_parent_network_v4}.1",
                                        "gateway_increment_ip": "0.0.0.2",
                                    },
                                ]
                            }
                        ),
                    }
                ],
            ),
            create_wait_for_agent_convergence_task(
                hostnames=[z_end_device_name],
            ),
            create_coop_apply_patchers_task(
                hostnames=[dut_device_name, z_end_device_name],
                do_warmboot=True,
            ),
        ],
        teardown_tasks=[
            create_coop_unregister_patchers_task(
                hostnames=dut_device_name,
            ),
            create_coop_unregister_patchers_task(
                hostnames=z_end_device_name,
            ),
        ],
        basic_traffic_item_configs=[
            taac_types.BasicTrafficItemConfig(
                name="V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
                bidirectional=True,
                merge_destinations=True,
                line_rate=10,
                src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{z_end_device_name}:{ixia_connected_interface_in_z_end_device}",
                        network_group_index=0,
                        device_group_index=0,
                    )
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{dut_device_name}:{ixia_connected_interface_in_dut}",
                        network_group_index=0,
                        device_group_index=0,
                    )
                ],
                traffic_type=ixia_types.TrafficType.IPV6,
                tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
            ),
            taac_types.BasicTrafficItemConfig(
                name="V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
                bidirectional=True,
                merge_destinations=True,
                line_rate=10,
                src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{z_end_device_name}:{ixia_connected_interface_in_z_end_device}",
                        network_group_index=0,
                        device_group_index=1,
                    )
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{dut_device_name}:{ixia_connected_interface_in_dut}",
                        network_group_index=0,
                        device_group_index=1,
                    )
                ],
                traffic_type=ixia_types.TrafficType.IPV4,
                tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
            ),
        ],
        basic_port_configs=[
            taac_types.BasicPortConfig(
                endpoint=f"{dut_device_name}:{ixia_connected_interface_in_dut}",
                device_group_configs=[
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        multiplier=downlink_peer_count,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_downlink_ic_parent_network_v6}::11",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_downlink_ic_parent_network_v6}::10",
                            gateway_increment_ip="0:0:0:0::2",
                            mask=127,
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_downlink_as_4byte,
                            local_as_increment=1,
                            enable_4_byte_local_as=True,
                            is_confed=is_downlink_peer_confed == "True",
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=ixia_downlink_prefix_count_v6,
                                        prefix_length=64,
                                        starting_prefixes="3000:1::",
                                        prefix_step="0:0:0:0::0",
                                        bgp_communities=ixia_downlink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    ),
                                ),
                            ],
                        ),
                    ),
                    taac_types.DeviceGroupConfig(
                        device_group_index=1,
                        multiplier=downlink_peer_count,
                        v4_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_downlink_ic_parent_network_v4}.1",
                            increment_ip="0.0.0.2",
                            gateway_starting_ip=f"{ixia_downlink_ic_parent_network_v4}.0",
                            gateway_increment_ip="0.0.0.2",
                            mask=31,
                        ),
                        v4_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_downlink_as_4byte,
                            local_as_increment=1,
                            enable_4_byte_local_as=True,
                            is_confed=is_downlink_peer_confed == "True",
                            bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v4_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=ixia_downlink_prefix_count_v4,
                                        prefix_length=24,
                                        starting_prefixes="101.1.0.0",
                                        prefix_step="0.0.0.0",
                                        bgp_communities=ixia_downlink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                    ),
                                ),
                            ],
                        ),
                    ),
                ],
            ),
            taac_types.BasicPortConfig(
                endpoint=f"{z_end_device_name}:{ixia_connected_interface_in_z_end_device}",
                device_group_configs=[
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        multiplier=uplink_peer_count,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_uplink_ic_parent_network_v6}::11",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_uplink_ic_parent_network_v6}::10",
                            gateway_increment_ip="0:0:0:0::2",
                            mask=127,
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_uplink_as_4byte,
                            local_as_increment=0,
                            enable_4_byte_local_as=True,
                            is_confed=is_uplink_peer_confed == "True",
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=ixia_uplink_prefix_count_v6,
                                        prefix_length=64,
                                        starting_prefixes="5000:1::",
                                        prefix_step="0:0:0:0::0",
                                        bgp_communities=ixia_uplink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    ),
                                ),
                            ],
                        ),
                    ),
                    taac_types.DeviceGroupConfig(
                        device_group_index=1,
                        multiplier=uplink_peer_count,
                        v4_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_uplink_ic_parent_network_v4}.1",
                            increment_ip="0.0.0.2",
                            gateway_starting_ip=f"{ixia_uplink_ic_parent_network_v4}.0",
                            gateway_increment_ip="0.0.0.2",
                            mask=31,
                        ),
                        v4_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_uplink_as_4byte,
                            local_as_increment=0,
                            enable_4_byte_local_as=True,
                            is_confed=is_uplink_peer_confed == "True",
                            bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v4_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=ixia_uplink_prefix_count_v4,
                                        prefix_length=24,
                                        starting_prefixes="102.1.0.0",
                                        prefix_step="0.0.0.0",
                                        bgp_communities=ixia_uplink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                    ),
                                ),
                            ],
                        ),
                    ),
                ],
            ),
        ],
        playbooks=build_optics_npi_playbooks(),
    )
