# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Port-channel TestConfig builders (FAUU + DU, QZD1 lab).

Hosts both the legacy fixture-style ``portchannel_test_config()`` and the parameterized
``test_config_for_portchannel`` factory that drive port-channel + BGP qualification on
multi-DUT topologies.
"""

import json

from ixia.ixia import types as ixia_types
from taac.playbooks.playbook_definitions import (
    create_all_lag_playbooks,
    create_test_portchannel_playbook,
)
from taac.task_definitions import (
    create_configure_parallel_bgp_peers_task,
    create_coop_apply_patchers_task,
    create_coop_register_patcher_task,
    create_coop_unregister_patchers_task,
    create_wait_for_agent_convergence_task,
    create_wait_for_bgp_convergence_task,
)
from taac.test_as_a_config.types import (
    BasicPortConfig,
    BasicTrafficItemConfig,
    BgpConfig,
    DeviceGroupConfig,
    DirectIxiaConnection,
    Endpoint,
    IpAddressesConfig,
    RouteScale,
    RouteScaleSpec,
    Task,
    TestConfig,
    TrafficEndpoint,
)


def portchannel_test_config():
    """Build the legacy ``PORTCHANNEL_TEST_CONFIG`` TestConfig.

    Hard-coded two-DUT (fa001-uu004 + fa001-du003) port-channel TestConfig in QZD1 with
    full FAUU-EB BGP peer-group setup (V4 + V6 SAFI), ingress/egress policies, and the
    ``create_test_portchannel_playbook`` chain. Used as a fixture-style harness pre-dating
    the parameterized ``test_config_for_portchannel`` factory; both coexist for backward
    compatibility.

    Returns:
        TestConfig: Two-DUT port-channel TestConfig (basset pool ``dne.test``).
    """
    return TestConfig(
        name="PORTCHANNEL_TEST_CONFIG",
        skip_ixia_protocol_verification=True,
        basset_pool="dne.test",
        endpoints=[
            Endpoint(
                name="fa001-uu004.qzd1",
                ixia_ports=["eth6/13/1"],
                dut=True,
            ),
            Endpoint(
                name="fa001-du003.qzd1",
                ixia_ports=["eth6/16/1"],
                dut=True,
            ),
        ],
        setup_tasks=[
            create_coop_unregister_patchers_task("fa001-uu004.qzd1"),
            create_coop_unregister_patchers_task("fa001-du003.qzd1"),
            create_coop_register_patcher_task(
                hostname="fa001-uu004.qzd1",
                config_name="bgpcpp",
                patcher_name="add_peer_group_patcher_PEERGROUP_FAUU_EB_V6",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": "PEERGROUP_FAUU_EB_V6",
                    "description": "BGP peering from FAUU to EB, IPV6 sessions",
                    "next_hop_self": "True",
                    "disable_ipv4_afi": "True",
                    "disable_ipv6_afi": "False",
                    "is_confed_peer": "False",
                    "ingress_policy_name": "PROPAGATE_FAUU_EB_IN",
                    "egress_policy_name": "PROPAGATE_FAUU_EB_OUT",
                    "bgp_peer_timers_hold_time_seconds": "30",
                    "bgp_peer_timers_keep_alive_seconds": "10",
                    "bgp_peer_timers_out_delay_seconds": "7",
                    "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                    "peer_tag": "EB",
                    "max_routes": "90000",
                    "warning_only": "True",
                    "warning_limit": "0",
                    "link_bandwidth_bps": "auto",
                    "v4_over_v6_nexthop": "False",
                    "is_passive": "False",
                    "receive_link_bandwidth": "1",
                },
                py_func_name="add_peer_group_patcher",
            ),
            create_coop_register_patcher_task(
                hostname="fa001-uu004.qzd1",
                config_name="bgpcpp",
                patcher_name="add_peer_group_patcher_PEERGROUP_FAUU_EB_V4",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": "PEERGROUP_FAUU_EB_V4",
                    "description": "BGP peering from FAUU to EB, IPV4 sessions",
                    "next_hop_self": "True",
                    "disable_ipv4_afi": "False",
                    "disable_ipv6_afi": "True",
                    "is_confed_peer": "False",
                    "ingress_policy_name": "PROPAGATE_FAUU_EB_IN",
                    "egress_policy_name": "PROPAGATE_FAUU_EB_OUT",
                    "bgp_peer_timers_hold_time_seconds": "30",
                    "bgp_peer_timers_keep_alive_seconds": "10",
                    "bgp_peer_timers_out_delay_seconds": "7",
                    "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                    "peer_tag": "EB",
                    "max_routes": "90000",
                    "warning_only": "True",
                    "warning_limit": "0",
                    "link_bandwidth_bps": "auto",
                    "v4_over_v6_nexthop": "False",
                    "is_passive": "False",
                    "receive_link_bandwidth": "1",
                },
                py_func_name="add_peer_group_patcher",
            ),
            create_coop_register_patcher_task(
                hostname="fa001-uu004.qzd1",
                config_name="bgpcpp",
                patcher_name="add_bgp_policy_statement_PROPAGATE_FAUU_EB_IN",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": "PROPAGATE_FAUU_EB_IN",
                    "description": "Policy for EB IN",
                },
                py_func_name="add_bgp_policy_statement",
            ),
            create_coop_register_patcher_task(
                hostname="fa001-uu004.qzd1",
                config_name="bgpcpp",
                patcher_name="a_add_bgp_policy_statement_PROPAGATE_FAUU_EB_OUT",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": "PROPAGATE_FAUU_EB_OUT",
                    "description": "Policy for EB OUT",
                },
                py_func_name="add_bgp_policy_statement",
            ),
            create_coop_register_patcher_task(
                hostname="fa001-uu004.qzd1",
                config_name="bgpcpp",
                patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FAUU_EB_IN_v6",
                task_name="coop_register_patcher",
                patcher_args={
                    "matching_prefix": "5401::/16",
                    "in_stmt_name": "PROPAGATE_FAUU_EB_IN",
                    "out_stmt_name": "PROPAGATE_FAUU_FADU_OUT",
                },
                py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
            ),
            create_coop_register_patcher_task(
                hostname="fa001-uu004.qzd1",
                config_name="bgpcpp",
                patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FAUU_EB_IN_v4",
                task_name="coop_register_patcher",
                patcher_args={
                    "matching_prefix": "10.0.0.0/8",
                    "in_stmt_name": "PROPAGATE_FAUU_EB_IN",
                    "out_stmt_name": "PROPAGATE_FAUU_FADU_OUT",
                },
                py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
            ),
            create_coop_register_patcher_task(
                hostname="fa001-du003.qzd1",
                config_name="bgpcpp",
                patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FADU_FAUU_IN_v6",
                task_name="coop_register_patcher",
                patcher_args={
                    "matching_prefix": "5401::/16",
                    "in_stmt_name": "PROPAGATE_FADU_FAUU_IN",
                    "out_stmt_name": "RANDOM",
                },
                py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
            ),
            create_coop_register_patcher_task(
                hostname="fa001-uu004.qzd1",
                config_name="bgpcpp",
                patcher_name="configure_bgp_switch_limit",
                task_name="coop_register_patcher",
                patcher_args={
                    "prefix_limit": "74000",
                },
                py_func_name="configure_bgp_switch_limit",
            ),
            create_coop_register_patcher_task(
                hostname="fa001-du003.qzd1",
                config_name="bgpcpp",
                patcher_name="configure_bgp_switch_limit",
                task_name="coop_register_patcher",
                patcher_args={
                    "prefix_limit": "74000",
                },
                py_func_name="configure_bgp_switch_limit",
            ),
            create_configure_parallel_bgp_peers_task(
                hostname="fa001-uu004.qzd1",
                configure_vlans_patcher_name="configure_vlans_patcher_portchannel",
                add_bgp_peers_patcher_name="add_bgp_peers_patcher_portchannel",
                config_json=json.dumps(
                    {
                        "eth6/13/1": [
                            # Regular BGP peers
                            {
                                "starting_ip": "2401:db00:e50d:11:8::1",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "BGP Peers to IXIA",
                                "peer_group_name": "PEERGROUP_FAUU_EB_V6",
                                "num_sessions": 50,
                                "remote_as_4_byte": 64734,
                                "remote_as_4_byte_step": 1,
                                "gateway_starting_ip": "2401:db00:e50d:11:8::1",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            # NDP Stressor: JUST IP, NO BGP
                            {
                                "starting_ip": "2401:db00:e50d:11:9::1",
                                "increment_ip": "0:0:0:0::0",
                                "prefix_length": 80,
                                "description": "NDP stressor",
                                "peer_group_name": "PEERGROUP_FAUU_EB_V6",
                                "num_sessions": 1,
                                "remote_as_4_byte": 64734,
                                "remote_as_4_byte_step": 1,
                                "gateway_starting_ip": "2401:db00:e50d:11:9::2",
                                "gateway_increment_ip": "0:0:0:0::0",
                                "config_only_interface_ip": True,
                            },
                            # ARP Stressor
                            {
                                "starting_ip": "192.168.1.1",
                                "increment_ip": "0.0.0.1",
                                "prefix_length": 16,
                                "description": "ARP stressor",
                                "peer_group_name": "PEERGROUP_FAUU_EB_V4",
                                "num_sessions": 1,
                                "remote_as_4_byte": 64734,
                                "gateway_starting_ip": "192.168.1.1",
                                "gateway_increment_ip": "0.0.0.1",
                                "config_only_interface_ip": True,
                            },
                            # BGP Prefix Flap
                            {
                                "starting_ip": "2401:db00:e50d:11:a::1",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "BGP Prefix Flap",
                                "peer_group_name": "PEERGROUP_FAUU_EB_V6",
                                "num_sessions": 10,
                                "remote_as_4_byte": 64734,
                                "remote_as_4_byte_step": 1,
                                "gateway_starting_ip": "2401:db00:e50d:11:a::2",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            # BGP Session Flap
                            {
                                "starting_ip": "192.168.2.1",
                                "increment_ip": "0.0.0.2",
                                "prefix_length": 31,
                                "description": "BGP Session Flap",
                                "peer_group_name": "PEERGROUP_FAUU_EB_V4",
                                "num_sessions": 10,
                                "remote_as_4_byte": 64734,
                                "remote_as_4_byte_step": 1,
                                "gateway_starting_ip": "192.168.2.2",
                                "gateway_increment_ip": "0.0.0.2",
                            },
                        ],
                        # "Port-Channel303": [
                        #     {
                        #         "starting_ip": "2401:db00:e50d:11:f::2",
                        #         "increment_ip": "0:0:0:0::2",
                        #         "prefix_length": 127,
                        #         "description": "DU-UU BGP session",
                        #         "peer_group_name": "PEERGROUP_FAUU_FADU_V6_NEW",
                        #         "num_sessions": 10,
                        #         "remote_as_4_byte": 65271,
                        #         "remote_as_4_byte_step": 1,
                        #         "gateway_starting_ip": "2401:db00:e50d:11:f::1",
                        #         "gateway_increment_ip": "0:0:0:0::2",
                        #     },
                        # ],
                    }
                ),
            ),
            create_configure_parallel_bgp_peers_task(
                hostname="fa001-du003.qzd1",
                configure_vlans_patcher_name="configure_vlans_patcher_portchannel",
                add_bgp_peers_patcher_name="add_bgp_peers_patcher_portchannel",
                config_json=json.dumps(
                    {
                        "eth6/16/1": [
                            {
                                "starting_ip": "2401:db00:e50d:11:d::1",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "BGP Peers to IXIA",
                                "peer_group_name": "PEERGROUP_FADU_SSW_V6",
                                "num_sessions": 10,
                                "remote_as_4_byte": 64901,
                                "remote_as_4_byte_step": 1,
                                "gateway_starting_ip": "2401:db00:e50d:11:d::2",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                        ],
                        # "Port-Channel304": [
                        #     {
                        #         "starting_ip": "2401:db00:e50d:11:f::1",
                        #         "increment_ip": "0:0:0:0::2",
                        #         "prefix_length": 127,
                        #         "description": "DU-UU BGP session",
                        #         "peer_group_name": "PEERGROUP_FADU_FAUU_V6",
                        #         "num_sessions": 10,
                        #         "remote_as_4_byte": 65271,
                        #         "remote_as_4_byte_step": 1,
                        #         "gateway_starting_ip": "2401:db00:e50d:11:f::2",
                        #         "gateway_increment_ip": "0:0:0:0::2",
                        #     },
                        # ],
                    }
                ),
            ),
            create_coop_apply_patchers_task(
                hostnames=["fa001-uu004.qzd1", "fa001-du003.qzd1"],
                do_warmboot=True,
            ),
            create_wait_for_agent_convergence_task(
                ["fa001-uu004.qzd1", "fa001-du003.qzd1"]
            ),
            create_wait_for_bgp_convergence_task(
                hostnames=["fa001-uu004.qzd1", "fa001-du003.qzd1"],
            ),
        ],
        teardown_tasks=[
            create_coop_unregister_patchers_task(
                ["fa001-uu004.qzd1", "fa001-du003.qzd1"]
            ),
        ],
        basic_port_configs=[
            BasicPortConfig(
                endpoint="fa001-uu004.qzd1:eth6/13/1",
                device_group_configs=[
                    DeviceGroupConfig(
                        device_group_index=0,
                        tag_name="PORTCHANNEL_BGP_TEST",
                        multiplier=50,
                        v6_addresses_config=IpAddressesConfig(
                            starting_ip="2401:db00:e50d:11:8::2",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip="2401:db00:e50d:11:8::1",
                            gateway_increment_ip="0:0:0:0::2",
                            mask=127,
                        ),
                        v6_bgp_config=BgpConfig(
                            local_as_4_bytes=64734,
                            local_as_increment=1,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            enable_graceful_restart=True,
                            graceful_restart_timer=120,
                            advertise_end_of_rib=True,
                            route_scales=[
                                RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=RouteScale(
                                        multiplier=1,
                                        prefix_count=24000,
                                        starting_prefixes="5401:db00:1000::",
                                        prefix_step="0:0:0:0::0",
                                        prefix_length=48,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                        bgp_communities=["65526:35724"],
                                    ),
                                ),
                            ],
                        ),
                    ),
                    # NDP Stressor
                    DeviceGroupConfig(
                        device_group_index=1,
                        tag_name="NDP_STRESSOR",
                        multiplier=10000,
                        v6_addresses_config=IpAddressesConfig(
                            starting_ip="2401:db00:e50d:11:9::2",
                            increment_ip="0:0:0:0::1",
                            gateway_starting_ip="2401:db00:e50d:11:9::1",
                            mask=80,
                        ),
                    ),
                    # ARP Stressor
                    DeviceGroupConfig(
                        device_group_index=2,
                        tag_name="ARP_STRESSOR",
                        multiplier=5000,
                        v4_addresses_config=IpAddressesConfig(
                            starting_ip="192.168.1.100",
                            increment_ip="0.0.0.1",
                            gateway_starting_ip="192.168.1.1",
                            gateway_increment_ip="0.0.0.0",
                            mask=16,
                        ),
                    ),
                    # BGP Prefix Flapping
                    DeviceGroupConfig(
                        device_group_index=3,
                        tag_name="BGP_PREFIX_FLAP",
                        multiplier=10,
                        v6_addresses_config=IpAddressesConfig(
                            starting_ip="2401:db00:e50d:11:a::2",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip="2401:db00:e50d:11:a::1",
                            gateway_increment_ip="0:0:0:0::2",
                            mask=127,
                        ),
                        v6_bgp_config=BgpConfig(
                            local_as_4_bytes=64734,
                            local_as_increment=1,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            route_scales=[
                                RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=RouteScale(
                                        multiplier=1,
                                        prefix_count=10000,
                                        starting_prefixes="5401:db00:2000::",
                                        prefix_step="0:0:0:0::0",
                                        prefix_length=48,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                        bgp_communities=["65526:35724"],
                                        prefix_flap_config=ixia_types.BgpFlapConfig(
                                            uptime_in_sec=15,
                                            downtime_in_sec=15,
                                        ),
                                    ),
                                ),
                            ],
                        ),
                    ),
                    # BGP Session Flapping
                    DeviceGroupConfig(
                        device_group_index=4,
                        tag_name="BGP_SESSION_FLAP",
                        multiplier=10,
                        v4_addresses_config=IpAddressesConfig(
                            starting_ip="192.168.2.2",
                            increment_ip="0.0.0.2",
                            gateway_starting_ip="192.168.2.1",
                            gateway_increment_ip="0.0.0.2",
                            mask=31,
                        ),
                        v4_bgp_config=BgpConfig(
                            local_as_4_bytes=64734,
                            local_as_increment=1,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                            peer_flap_config=ixia_types.BgpFlapConfig(
                                uptime_in_sec=120,
                                downtime_in_sec=15,
                            ),
                            route_scales=[
                                RouteScaleSpec(
                                    network_group_index=0,
                                    v4_route_scale=RouteScale(
                                        multiplier=1,
                                        prefix_count=10000,
                                        starting_prefixes="10.1.0.0",
                                        prefix_length=24,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                        bgp_communities=["65526:35724"],
                                    ),
                                ),
                            ],
                        ),
                    ),
                ],
            ),
            BasicPortConfig(
                endpoint="fa001-du003.qzd1:eth6/16/1",
                device_group_configs=[
                    DeviceGroupConfig(
                        device_group_index=0,
                        tag_name="PORTCHANNEL_BGP_TEST",
                        multiplier=10,
                        v6_addresses_config=IpAddressesConfig(
                            starting_ip="2401:db00:e50d:11:d::2",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip="2401:db00:e50d:11:d::1",
                            gateway_increment_ip="0:0:0:0::2",
                            mask=127,
                        ),
                        v6_bgp_config=BgpConfig(
                            local_as_4_bytes=64901,
                            local_as_increment=1,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            enable_graceful_restart=True,
                            graceful_restart_timer=120,
                            advertise_end_of_rib=True,
                            route_scales=[
                                RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=RouteScale(
                                        multiplier=1,
                                        prefix_count=100,
                                        starting_prefixes="7401:db00:1001::",
                                        prefix_step="0:0:0:0::0",
                                        prefix_length=48,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                        bgp_communities=[
                                            "65441:132",
                                            "65442:133",
                                            "65529:26730",
                                        ],
                                    ),
                                ),
                            ],
                        ),
                    ),
                ],
            ),
        ],
        basic_traffic_item_configs=[
            BasicTrafficItemConfig(
                name="MAIN_TRAFFIC_IXIA2_TO_IXIA1",
                src_endpoints=[
                    TrafficEndpoint(
                        name="fa001-du003.qzd1:eth6/16/1",
                        device_group_index=0,
                        network_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    TrafficEndpoint(
                        name="fa001-uu004.qzd1:eth6/13/1",
                        device_group_index=0,
                        network_group_index=0,
                    ),
                ],
                line_rate=50,
                traffic_type=ixia_types.TrafficType.IPV6,
                merge_destinations=False,
                bidirectional=False,
                src_dest_mesh=ixia_types.SrcDestMeshType.FULL_MESH,
            ),
        ],
        traffic_items_to_start=["MAIN_TRAFFIC_IXIA2_TO_IXIA1"],
        # Deprecated - define at playbook level
        # snapshot_checks=[
        #     SnapshotHealthCheck(name=hc_types.CheckName.CORE_DUMPS_CHECK),
        #     # SnapshotHealthCheck(name=hc_types.CheckName.BGP_PEER_ROUTE_CHECK),
        # ],
        # Deprecated - define at playbook level
        # postchecks=[...],
        # Deprecated - define at playbook level
        # prechecks=[...],
        playbooks=[
            create_test_portchannel_playbook(),
        ],
    )


def test_config_for_portchannel(
    test_config_name: str,
    ixia_chassis_ip: str,
    ixia_uu_port: str,
    ixia_du_port: str,
    # UU device (upstream) - topology
    uu_device_name: str,
    uu_ixia_interface: str,
    # DU device (downstream) - topology
    du_device_name: str,
    du_ixia_interface: str,
    # Portchannel config (UU-DU direct BGP peering)
    uu_portchannel_name: str,
    du_portchannel_name: str,
    # Portchannel links
    # 1-1 mapping between UU and DU: e.g. du_portchannel_links[i] and uu_portchannel_links[i] are connected
    uu_portchannel_links: list[str],
    du_portchannel_links: list[str],
    # Portchannel minlink config
    min_link_percentage: float = 0.5,
    min_link_up_percentage: float = 0.75,
    # Mismatch minlink config
    uu_mismatch_min_link: float = 0.5,
    uu_mismatch_min_link_up: float = 0.8,
    du_mismatch_min_link: float = 0.6,
    du_mismatch_min_link_up: float = 0.7,
    # IXIA ASN config
    uu_ixia_as: int = 64734,
    du_ixia_as: int = 64901,
    # UU BGP config
    uu_remote_as: int = 4290000001,
    uu_eb_peergroup_v6: str = "PEERGROUP_FAUU_EB_V6",
    uu_eb_peergroup_v4: str = "PEERGROUP_FAUU_EB_V4",
    uu_eb_ingress_policy: str = "PROPAGATE_FAUU_EB_IN",
    uu_eb_egress_policy: str = "PROPAGATE_FAUU_EB_OUT",
    uu_du_ingress_policy: str = "PROPAGATE_FAUU_FADU_IN",
    uu_du_egress_policy: str = "PROPAGATE_FAUU_FADU_OUT",
    uu_eb_peer_tag: str = "EB",
    uu_du_peer_tag: str = "DU",
    # UU BGP peers IP config
    uu_bgp_v6_starting_ip: str = "2401:db00:e50d:11:8::0",
    uu_bgp_v6_gateway_ip: str = "2401:db00:e50d:11:8::1",
    uu_bgp_v4_starting_ip: str = "192.168.0.0",
    uu_bgp_v4_gateway_ip: str = "192.168.0.1",
    # UU stressor IP config
    uu_ndp_starting_ip: str = "2401:db00:e50d:11:9::0",
    uu_ndp_gateway_ip: str = "2401:db00:e50d:11:9::1",
    uu_arp_starting_ip: str = "192.168.1.0",
    uu_arp_gateway_ip: str = "192.168.1.1",
    # UU BGP flap IP config
    uu_prefix_flap_starting_ip: str = "2401:db00:e50d:11:a::0",
    uu_prefix_flap_gateway_ip: str = "2401:db00:e50d:11:a::1",
    uu_session_flap_starting_ip: str = "192.168.2.0",
    uu_session_flap_gateway_ip: str = "192.168.2.1",
    # UU route scale
    uu_v6_prefix_count: int = 25000,
    uu_v6_starting_prefixes: str = "5401:db00::",
    uu_v4_prefix_count: int = 25000,
    uu_v4_starting_prefixes: str = "10.0.0.0",
    uu_bgp_communities: list[str] = ["65526:35724"],
    uu_prefix_flap_prefix_count: int = 10000,
    uu_prefix_flap_starting_prefixes: str = "6401:db00::",
    uu_session_flap_prefix_count: int = 10000,
    uu_session_flap_starting_prefixes: str = "20.0.0.0",
    # DU BGP config
    du_remote_as: int = 8001,
    du_ssw_peergroup_v6: str = "PEERGROUP_FADU_SSW_V6",
    du_ssw_peergroup_v4: str = "PEERGROUP_FADU_SSW_V4",
    du_ssw_ingress_policy: str = "PROPAGATE_FADU_SSW_IN",
    du_ssw_egress_policy: str = "PROPAGATE_FADU_SSW_OUT",
    du_uu_ingress_policy: str = "PROPAGATE_FADU_FAUU_IN",
    du_uu_egress_policy: str = "PROPAGATE_FADU_FAUU_OUT",
    du_ssw_peer_tag: str = "SSW",
    du_uu_peer_tag: str = "UU",
    # DU BGP peers IP config
    du_bgp_v6_starting_ip: str = "2401:eb00:e50d:11:8::0",
    du_bgp_v6_gateway_ip: str = "2401:eb00:e50d:11:8::1",
    du_bgp_v4_starting_ip: str = "192.168.3.0",
    du_bgp_v4_gateway_ip: str = "192.168.3.1",
    # DU route scale
    du_v6_prefix_count: int = 5000,
    du_v6_starting_prefixes: str = "7401:db00:1001::",
    du_v4_prefix_count: int = 5000,
    du_v4_starting_prefixes: str = "30.0.0.0",
    du_bgp_communities: list[str] = [
        "65441:132",
        "65442:133",
        "65529:26730",
    ],
    # Session counts
    uu_v6_session_count: int = 8,
    uu_v4_session_count: int = 8,
    du_v6_session_count: int = 48,
    du_v4_session_count: int = 48,
    # Scale parameters
    prefix_limit: int = 74000,
    max_routes: int = 90000,
    # Stressor scale
    ndp_stressor_multiplier: int = 10,
    arp_stressor_multiplier: int = 10,
    # BGP flap parameters
    prefix_flap_session_count: int = 10,
    session_flap_session_count: int = 10,
    prefix_flap_uptime: int = 15,
    prefix_flap_downtime: int = 15,
    session_flap_uptime: int = 120,
    session_flap_downtime: int = 15,
    # Portchannel parameters
    portchannel_session_count: int = 48,
    uu_portchannel_bgp_v6_starting_ip: str = "2401:db00:e50d:11:f::0",
    uu_portchannel_bgp_v6_gateway_ip: str = "2401:db00:e50d:11:f::1",
    uu_portchannel_bgp_v4_starting_ip: str = "192.168.10.0",
    uu_portchannel_bgp_v4_gateway_ip: str = "192.168.10.1",
    uu_portchannel_peergroup_v6: str = "PEERGROUP_FAUU_FADU_V6",
    uu_portchannel_peergroup_v4: str = "PEERGROUP_FAUU_FADU_V4",
    du_portchannel_peergroup_v6: str = "PEERGROUP_FADU_FAUU_V6",
    du_portchannel_peergroup_v4: str = "PEERGROUP_FADU_FAUU_V4",
    # Traffic parameters
    traffic_line_rate: int = 50,
    # Optional overrides
    basset_pool: str = "dne.test",
    additional_setup_tasks: list[Task] | None = None,
) -> TestConfig:
    hostnames = [uu_device_name, du_device_name]
    uu_endpoint = f"{uu_device_name}:{uu_ixia_interface}"
    du_endpoint = f"{du_device_name}:{du_ixia_interface}"

    uu_direct_ixia_connections = [
        DirectIxiaConnection(
            interface=uu_ixia_interface,
            ixia_chassis_ip=ixia_chassis_ip,
            ixia_port=ixia_uu_port,
        )
    ]
    du_direct_ixia_connections = [
        DirectIxiaConnection(
            interface=du_ixia_interface,
            ixia_chassis_ip=ixia_chassis_ip,
            ixia_port=ixia_du_port,
        )
    ]

    setup_tasks = [
        create_coop_unregister_patchers_task(uu_device_name),
        create_coop_unregister_patchers_task(du_device_name),
        create_coop_register_patcher_task(
            hostname=uu_device_name,
            config_name="agent",
            patcher_name=f"change_speed_patcher_{uu_ixia_interface.replace('/', '_')}_400g",
            task_name="coop_register_patcher",
            patcher_args={
                "intfs": uu_ixia_interface,
                "speed": "FOURHUNDREDG",
                "profile_id": "PROFILE_400G_4_PAM4_RS544X2N_OPTICAL",
            },
            py_func_name="change_speed",
        ),
        create_coop_register_patcher_task(
            hostname=du_device_name,
            config_name="agent",
            patcher_name=f"change_speed_patcher_{du_ixia_interface.replace('/', '_')}_400g",
            task_name="coop_register_patcher",
            patcher_args={
                "intfs": du_ixia_interface,
                "speed": "FOURHUNDREDG",
                "profile_id": "PROFILE_400G_4_PAM4_RS544X2N_OPTICAL",
            },
            py_func_name="change_speed",
        ),
        create_coop_register_patcher_task(
            hostname=uu_device_name,
            config_name="agent",
            patcher_name=f"set_port_channel_min_link_capacity_{uu_portchannel_name.replace('-', '_')}",
            task_name="coop_register_patcher",
            patcher_args={
                "port_channel_name": uu_portchannel_name,
                "link_percentage": str(min_link_percentage),
                "link_up_percentage": str(min_link_up_percentage),
            },
            py_func_name="set_port_channel_min_link_capacity",
        ),
        create_coop_register_patcher_task(
            hostname=du_device_name,
            config_name="agent",
            patcher_name=f"set_port_channel_min_link_capacity_{du_portchannel_name.replace('-', '_')}",
            task_name="coop_register_patcher",
            patcher_args={
                "port_channel_name": du_portchannel_name,
                "link_percentage": str(min_link_percentage),
                "link_up_percentage": str(min_link_up_percentage),
            },
            py_func_name="set_port_channel_min_link_capacity",
        ),
        create_coop_register_patcher_task(
            hostname=uu_device_name,
            config_name="bgpcpp",
            patcher_name=f"00_add_bgp_policy_statement_{uu_eb_ingress_policy}",
            task_name="coop_register_patcher",
            patcher_args={
                "name": uu_eb_ingress_policy,
                "description": "Policy for EB IN",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname=uu_device_name,
            config_name="bgpcpp",
            patcher_name=f"00_add_bgp_policy_statement_{uu_eb_egress_policy}",
            task_name="coop_register_patcher",
            patcher_args={
                "name": uu_eb_egress_policy,
                "description": "Policy for EB OUT",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname=uu_device_name,
            config_name="bgpcpp",
            patcher_name=f"00_add_peer_group_patcher_{uu_eb_peergroup_v6}",
            task_name="coop_register_patcher",
            patcher_args={
                "name": uu_eb_peergroup_v6,
                "description": "BGP peering from UU to EB, IPV6 sessions",
                "next_hop_self": "True",
                "disable_ipv4_afi": "True",
                "disable_ipv6_afi": "False",
                "is_confed_peer": "False",
                "ingress_policy_name": uu_eb_ingress_policy,
                "egress_policy_name": uu_eb_egress_policy,
                "bgp_peer_timers_hold_time_seconds": "30",
                "bgp_peer_timers_keep_alive_seconds": "10",
                "bgp_peer_timers_out_delay_seconds": "7",
                "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                "peer_tag": uu_eb_peer_tag,
                "max_routes": str(max_routes),
                "warning_only": "True",
                "warning_limit": "0",
                "link_bandwidth_bps": "auto",
                "v4_over_v6_nexthop": "False",
                "is_passive": "False",
                "receive_link_bandwidth": "1",
            },
            py_func_name="add_peer_group_patcher",
        ),
        create_coop_register_patcher_task(
            hostname=uu_device_name,
            config_name="bgpcpp",
            patcher_name=f"00_add_peer_group_patcher_{uu_eb_peergroup_v4}",
            task_name="coop_register_patcher",
            patcher_args={
                "name": uu_eb_peergroup_v4,
                "description": "BGP peering from UU to EB, IPV4 sessions",
                "next_hop_self": "True",
                "disable_ipv4_afi": "False",
                "disable_ipv6_afi": "True",
                "is_confed_peer": "False",
                "ingress_policy_name": uu_eb_ingress_policy,
                "egress_policy_name": uu_eb_egress_policy,
                "bgp_peer_timers_hold_time_seconds": "30",
                "bgp_peer_timers_keep_alive_seconds": "10",
                "bgp_peer_timers_out_delay_seconds": "7",
                "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                "peer_tag": uu_eb_peer_tag,
                "max_routes": str(max_routes),
                "warning_only": "True",
                "warning_limit": "0",
                "link_bandwidth_bps": "auto",
                "v4_over_v6_nexthop": "False",
                "is_passive": "False",
                "receive_link_bandwidth": "1",
            },
            py_func_name="add_peer_group_patcher",
        ),
        # DU SSW peer groups (analogous to UU EB peer groups)
        create_coop_register_patcher_task(
            hostname=du_device_name,
            config_name="bgpcpp",
            patcher_name=f"add_peer_group_patcher_{du_ssw_peergroup_v4}",
            task_name="coop_register_patcher",
            patcher_args={
                "name": du_ssw_peergroup_v4,
                "description": "BGP peering from DU to SSW, IPV4 sessions",
                "next_hop_self": "True",
                "disable_ipv4_afi": "False",
                "disable_ipv6_afi": "True",
                "is_confed_peer": "False",
                "ingress_policy_name": du_ssw_ingress_policy,
                "egress_policy_name": du_ssw_egress_policy,
                "bgp_peer_timers_hold_time_seconds": "30",
                "bgp_peer_timers_keep_alive_seconds": "10",
                "bgp_peer_timers_out_delay_seconds": "7",
                "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                "peer_tag": du_ssw_peer_tag,
                "max_routes": str(max_routes),
                "warning_only": "True",
                "warning_limit": "0",
                "link_bandwidth_bps": "auto",
                "v4_over_v6_nexthop": "False",
                "is_passive": "False",
                "receive_link_bandwidth": "1",
            },
            py_func_name="add_peer_group_patcher",
        ),
        create_coop_register_patcher_task(
            hostname=uu_device_name,
            config_name="bgpcpp",
            patcher_name="configure_bgp_switch_limit",
            task_name="coop_register_patcher",
            patcher_args={
                "prefix_limit": str(prefix_limit),
            },
            py_func_name="configure_bgp_switch_limit",
        ),
        create_coop_register_patcher_task(
            hostname=du_device_name,
            config_name="bgpcpp",
            patcher_name="configure_bgp_switch_limit",
            task_name="coop_register_patcher",
            patcher_args={
                "prefix_limit": str(prefix_limit),
            },
            py_func_name="configure_bgp_switch_limit",
        ),
        # Portchannel peer groups for UU and DU V4
        create_coop_register_patcher_task(
            hostname=uu_device_name,
            config_name="bgpcpp",
            patcher_name=f"add_peer_group_patcher_{uu_portchannel_peergroup_v4}",
            task_name="coop_register_patcher",
            patcher_args={
                "name": uu_portchannel_peergroup_v4,
                "description": "BGP peering from UU to DU, IPV4 sessions",
                "next_hop_self": "True",
                "disable_ipv4_afi": "False",
                "disable_ipv6_afi": "True",
                "is_confed_peer": "True",
                "ingress_policy_name": uu_du_ingress_policy,
                "egress_policy_name": uu_du_egress_policy,
                "bgp_peer_timers_hold_time_seconds": "30",
                "bgp_peer_timers_keep_alive_seconds": "10",
                "bgp_peer_timers_out_delay_seconds": "7",
                "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                "peer_tag": uu_du_peer_tag,
                "max_routes": str(max_routes),
                "warning_only": "True",
                "warning_limit": "0",
                "link_bandwidth_bps": "auto",
                "v4_over_v6_nexthop": "False",
                "is_passive": "False",
                "receive_link_bandwidth": "1",
            },
            py_func_name="add_peer_group_patcher",
        ),
        create_coop_register_patcher_task(
            hostname=du_device_name,
            config_name="bgpcpp",
            patcher_name=f"add_peer_group_patcher_{du_portchannel_peergroup_v4}",
            task_name="coop_register_patcher",
            patcher_args={
                "name": du_portchannel_peergroup_v4,
                "description": "BGP peering from DU to UU, IPV4 sessions",
                "next_hop_self": "True",
                "disable_ipv4_afi": "False",
                "disable_ipv6_afi": "True",
                "is_confed_peer": "True",
                "ingress_policy_name": du_uu_ingress_policy,
                "egress_policy_name": du_uu_egress_policy,
                "bgp_peer_timers_hold_time_seconds": "30",
                "bgp_peer_timers_keep_alive_seconds": "10",
                "bgp_peer_timers_out_delay_seconds": "7",
                "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                "peer_tag": du_uu_peer_tag,
                "max_routes": str(max_routes),
                "warning_only": "True",
                "warning_limit": "0",
                "link_bandwidth_bps": "auto",
                "v4_over_v6_nexthop": "False",
                "is_passive": "False",
                "receive_link_bandwidth": "1",
            },
            py_func_name="add_peer_group_patcher",
        ),
        create_coop_register_patcher_task(
            hostname=uu_device_name,
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FAUU_EB_IN_v4_1",
            task_name="coop_register_patcher",
            patcher_args={
                "matching_prefix": "10.0.0.0/8",
                "in_stmt_name": "PROPAGATE_FAUU_EB_IN",
                "out_stmt_name": "PROPAGATE_FAUU_FADU_OUT",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname=uu_device_name,
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FAUU_EB_IN_v4_2",
            task_name="coop_register_patcher",
            patcher_args={
                "matching_prefix": "20.0.0.0/8",
                "in_stmt_name": "PROPAGATE_FAUU_EB_IN",
                "out_stmt_name": "PROPAGATE_FAUU_FADU_OUT",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname=uu_device_name,
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FAUU_EB_OUT_v4",
            task_name="coop_register_patcher",
            patcher_args={
                "matching_prefix": "30.0.0.0/8",
                "out_stmt_name": "PROPAGATE_FAUU_EB_OUT",
                "in_stmt_name": "PROPAGATE_FAUU_FADU_IN",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname=uu_device_name,
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FAUU_EB_IN_v6_1",
            task_name="coop_register_patcher",
            patcher_args={
                "matching_prefix": "5401::/16",
                "in_stmt_name": "PROPAGATE_FAUU_EB_IN",
                "out_stmt_name": "PROPAGATE_FAUU_FADU_OUT",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname=uu_device_name,
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FAUU_EB_IN_v6_2",
            task_name="coop_register_patcher",
            patcher_args={
                "matching_prefix": "6401::/16",
                "in_stmt_name": "PROPAGATE_FAUU_EB_IN",
                "out_stmt_name": "PROPAGATE_FAUU_FADU_OUT",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname=uu_device_name,
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FAUU_EB_OUT_v6",
            task_name="coop_register_patcher",
            patcher_args={
                "matching_prefix": "7401::/16",
                "out_stmt_name": "PROPAGATE_FAUU_EB_OUT",
                "in_stmt_name": "PROPAGATE_FAUU_FADU_IN",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname=du_device_name,
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FADU_SSW_IN_v4",
            task_name="coop_register_patcher",
            patcher_args={
                "matching_prefix": "30.0.0.0/8",
                "in_stmt_name": "PROPAGATE_FADU_SSW_IN",
                "out_stmt_name": "PROPAGATE_FADU_FAUU_OUT",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname=du_device_name,
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FADU_SSW_OUT_v4_1",
            task_name="coop_register_patcher",
            patcher_args={
                "matching_prefix": "10.0.0.0/8",
                "out_stmt_name": "PROPAGATE_FADU_SSW_OUT",
                "in_stmt_name": "PROPAGATE_FADU_FAUU_IN",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname=du_device_name,
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FADU_SSW_OUT_v4_2",
            task_name="coop_register_patcher",
            patcher_args={
                "matching_prefix": "20.0.0.0/8",
                "out_stmt_name": "PROPAGATE_FADU_SSW_OUT",
                "in_stmt_name": "PROPAGATE_FADU_FAUU_IN",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname=du_device_name,
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FADU_SSW_IN_v6",
            task_name="coop_register_patcher",
            patcher_args={
                "matching_prefix": "7401::/16",
                "in_stmt_name": "PROPAGATE_FADU_SSW_IN",
                "out_stmt_name": "PROPAGATE_FADU_FAUU_OUT",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname=du_device_name,
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FADU_SSW_OUT_v6_1",
            task_name="coop_register_patcher",
            patcher_args={
                "matching_prefix": "5401::/16",
                "out_stmt_name": "PROPAGATE_FADU_SSW_OUT",
                "in_stmt_name": "PROPAGATE_FADU_FAUU_IN",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname=du_device_name,
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FADU_SSW_OUT_v6_2",
            task_name="coop_register_patcher",
            patcher_args={
                "matching_prefix": "6401::/16",
                "out_stmt_name": "PROPAGATE_FADU_SSW_OUT",
                "in_stmt_name": "PROPAGATE_FADU_FAUU_IN",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_configure_parallel_bgp_peers_task(
            hostname=uu_device_name,
            configure_vlans_patcher_name="configure_vlans_patcher_portchannel",
            add_bgp_peers_patcher_name="add_bgp_peers_patcher_portchannel",
            config_json=json.dumps(
                {
                    uu_ixia_interface: [
                        {
                            "starting_ip": uu_bgp_v6_starting_ip,
                            "increment_ip": "0:0:0:0::2",
                            "prefix_length": 127,
                            "description": "Regular IPv6 BGP Peers",
                            "peer_group_name": uu_eb_peergroup_v6,
                            "num_sessions": uu_v6_session_count,
                            "remote_as_4_byte": uu_ixia_as,
                            "remote_as_4_byte_step": 1,
                            "gateway_starting_ip": uu_bgp_v6_gateway_ip,
                            "gateway_increment_ip": "0:0:0:0::2",
                        },
                        {
                            "starting_ip": uu_bgp_v4_starting_ip,
                            "increment_ip": "0.0.0.2",
                            "prefix_length": 31,
                            "description": "Regular IPv4 BGP Peers",
                            "peer_group_name": uu_eb_peergroup_v4,
                            "num_sessions": uu_v4_session_count,
                            "remote_as_4_byte": uu_ixia_as,
                            "remote_as_4_byte_step": 1,
                            "gateway_starting_ip": uu_bgp_v4_gateway_ip,
                            "gateway_increment_ip": "0.0.0.2",
                        },
                        {
                            "starting_ip": uu_ndp_starting_ip,
                            "increment_ip": "0:0:0:0::0",
                            "prefix_length": 80,
                            "description": "NDP stressor",
                            "peer_group_name": uu_eb_peergroup_v6,
                            "num_sessions": 1,
                            "remote_as_4_byte": uu_ixia_as,
                            "remote_as_4_byte_step": 1,
                            "gateway_starting_ip": uu_ndp_gateway_ip,
                            "gateway_increment_ip": "0:0:0:0::0",
                            "config_only_interface_ip": True,
                        },
                        {
                            "starting_ip": uu_arp_starting_ip,
                            "increment_ip": "0.0.0.1",
                            "prefix_length": 16,
                            "description": "ARP stressor",
                            "peer_group_name": uu_eb_peergroup_v4,
                            "num_sessions": 1,
                            "remote_as_4_byte": uu_ixia_as,
                            "gateway_starting_ip": uu_arp_gateway_ip,
                            "gateway_increment_ip": "0.0.0.1",
                            "config_only_interface_ip": True,
                        },
                        {
                            "starting_ip": uu_prefix_flap_starting_ip,
                            "increment_ip": "0:0:0:0::2",
                            "prefix_length": 127,
                            "description": "BGP Prefix Flap",
                            "peer_group_name": uu_eb_peergroup_v6,
                            "num_sessions": prefix_flap_session_count,
                            "remote_as_4_byte": uu_ixia_as,
                            "remote_as_4_byte_step": 1,
                            "gateway_starting_ip": uu_prefix_flap_gateway_ip,
                            "gateway_increment_ip": "0:0:0:0::2",
                        },
                        {
                            "starting_ip": uu_session_flap_starting_ip,
                            "increment_ip": "0.0.0.2",
                            "prefix_length": 31,
                            "description": "BGP Session Flap",
                            "peer_group_name": uu_eb_peergroup_v4,
                            "num_sessions": session_flap_session_count,
                            "remote_as_4_byte": uu_ixia_as,
                            "remote_as_4_byte_step": 1,
                            "gateway_starting_ip": uu_session_flap_gateway_ip,
                            "gateway_increment_ip": "0.0.0.2",
                        },
                    ],
                    uu_portchannel_links[0]: [
                        {
                            "starting_ip": uu_portchannel_bgp_v6_starting_ip,
                            "increment_ip": "0:0:0:0::2",
                            "prefix_length": 127,
                            "description": "UU-DU portchannel IPv6 BGP sessions",
                            "peer_group_name": uu_portchannel_peergroup_v6,
                            "num_sessions": portchannel_session_count,
                            "remote_as_4_byte": uu_remote_as,
                            "remote_as_4_byte_step": 0,
                            "gateway_starting_ip": uu_portchannel_bgp_v6_gateway_ip,
                            "gateway_increment_ip": "0:0:0:0::2",
                        },
                        {
                            "starting_ip": uu_portchannel_bgp_v4_starting_ip,
                            "increment_ip": "0.0.0.2",
                            "prefix_length": 31,
                            "description": "UU-DU Portchannel IPv4 BGP sessions",
                            "peer_group_name": uu_portchannel_peergroup_v4,
                            "num_sessions": portchannel_session_count,
                            "remote_as_4_byte": uu_remote_as,
                            "remote_as_4_byte_step": 0,
                            "gateway_starting_ip": uu_portchannel_bgp_v4_gateway_ip,
                            "gateway_increment_ip": "0.0.0.2",
                        },
                    ],
                }
            ),
        ),
        create_configure_parallel_bgp_peers_task(
            hostname=du_device_name,
            configure_vlans_patcher_name="configure_vlans_patcher_portchannel",
            add_bgp_peers_patcher_name="add_bgp_peers_patcher_portchannel",
            config_json=json.dumps(
                {
                    du_ixia_interface: [
                        {
                            "starting_ip": du_bgp_v6_starting_ip,
                            "increment_ip": "0:0:0:0::2",
                            "prefix_length": 127,
                            "description": "Regular IPv6 BGP Peers",
                            "peer_group_name": du_ssw_peergroup_v6,
                            "num_sessions": du_v6_session_count,
                            "remote_as_4_byte": du_ixia_as,
                            "remote_as_4_byte_step": 1,
                            "gateway_starting_ip": du_bgp_v6_gateway_ip,
                            "gateway_increment_ip": "0:0:0:0::2",
                        },
                        {
                            "starting_ip": du_bgp_v4_starting_ip,
                            "increment_ip": "0.0.0.2",
                            "prefix_length": 31,
                            "description": "Regular IPv4 BGP Peers",
                            "peer_group_name": du_ssw_peergroup_v4,
                            "num_sessions": du_v4_session_count,
                            "remote_as_4_byte": du_ixia_as,
                            "remote_as_4_byte_step": 1,
                            "gateway_starting_ip": du_bgp_v4_gateway_ip,
                            "gateway_increment_ip": "0.0.0.2",
                        },
                    ],
                    du_portchannel_links[0]: [
                        {
                            "starting_ip": uu_portchannel_bgp_v6_gateway_ip,
                            "increment_ip": "0:0:0:0::2",
                            "prefix_length": 127,
                            "description": "DU-UU portchannel BGP sessions",
                            "peer_group_name": du_portchannel_peergroup_v6,
                            "num_sessions": portchannel_session_count,
                            "remote_as_4_byte": du_remote_as,
                            "remote_as_4_byte_step": 0,
                            "gateway_starting_ip": uu_portchannel_bgp_v6_starting_ip,
                            "gateway_increment_ip": "0:0:0:0::2",
                        },
                        {
                            "starting_ip": uu_portchannel_bgp_v4_gateway_ip,
                            "increment_ip": "0.0.0.2",
                            "prefix_length": 31,
                            "description": "DU-UU Portchannel IPv4 BGP sessions",
                            "peer_group_name": du_portchannel_peergroup_v4,
                            "num_sessions": portchannel_session_count,
                            "remote_as_4_byte": du_remote_as,
                            "remote_as_4_byte_step": 0,
                            "gateway_starting_ip": uu_portchannel_bgp_v4_starting_ip,
                            "gateway_increment_ip": "0.0.0.2",
                        },
                    ],
                }
            ),
        ),
        create_coop_apply_patchers_task(
            hostnames=hostnames,
            do_coldboot=True,
        ),
        create_wait_for_agent_convergence_task(hostnames),
        create_wait_for_bgp_convergence_task(
            hostnames=hostnames,
        ),
    ]

    if additional_setup_tasks:
        setup_tasks.extend(additional_setup_tasks)

    basic_port_configs = [
        BasicPortConfig(
            endpoint=uu_endpoint,
            device_group_configs=[
                DeviceGroupConfig(
                    device_group_index=0,
                    tag_name="NO_V6_PACKET_LOSS_EXPECTED",
                    multiplier=uu_v6_session_count,
                    v6_addresses_config=IpAddressesConfig(
                        starting_ip=uu_bgp_v6_gateway_ip,
                        increment_ip="0:0:0:0::2",
                        gateway_starting_ip=uu_bgp_v6_starting_ip,
                        gateway_increment_ip="0:0:0:0::2",
                        mask=127,
                    ),
                    v6_bgp_config=BgpConfig(
                        local_as_4_bytes=uu_ixia_as,
                        local_as_increment=1,
                        enable_4_byte_local_as=True,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        enable_graceful_restart=True,
                        graceful_restart_timer=120,
                        advertise_end_of_rib=True,
                        route_scales=[
                            RouteScaleSpec(
                                network_group_index=0,
                                v6_route_scale=RouteScale(
                                    multiplier=1,
                                    prefix_count=uu_v6_prefix_count,
                                    starting_prefixes=uu_v6_starting_prefixes,
                                    prefix_step="0:0:0:0::0",
                                    prefix_length=48,
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    bgp_communities=uu_bgp_communities,
                                ),
                            ),
                        ],
                    ),
                ),
                DeviceGroupConfig(
                    device_group_index=1,
                    tag_name="NO_V4_PACKET_LOSS_EXPECTED",
                    multiplier=uu_v4_session_count,
                    v4_addresses_config=IpAddressesConfig(
                        starting_ip=uu_bgp_v4_gateway_ip,
                        increment_ip="0.0.0.2",
                        gateway_starting_ip=uu_bgp_v4_starting_ip,
                        gateway_increment_ip="0.0.0.2",
                        mask=31,
                    ),
                    v4_bgp_config=BgpConfig(
                        local_as_4_bytes=uu_ixia_as,
                        local_as_increment=1,
                        enable_4_byte_local_as=True,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                        enable_graceful_restart=True,
                        graceful_restart_timer=120,
                        advertise_end_of_rib=True,
                        route_scales=[
                            RouteScaleSpec(
                                network_group_index=0,
                                v4_route_scale=RouteScale(
                                    multiplier=1,
                                    prefix_count=uu_v4_prefix_count,
                                    starting_prefixes=uu_v4_starting_prefixes,
                                    prefix_step="0.0.0.0",
                                    prefix_length=24,
                                    ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                    bgp_communities=uu_bgp_communities,
                                ),
                            ),
                        ],
                    ),
                ),
                DeviceGroupConfig(
                    device_group_index=2,
                    tag_name="NDP_STRESSOR",
                    multiplier=ndp_stressor_multiplier,
                    v6_addresses_config=IpAddressesConfig(
                        starting_ip=uu_ndp_gateway_ip,
                        increment_ip="0:0:0:0::1",
                        gateway_starting_ip=uu_ndp_starting_ip,
                        mask=80,
                    ),
                ),
                DeviceGroupConfig(
                    device_group_index=3,
                    tag_name="ARP_STRESSOR",
                    multiplier=arp_stressor_multiplier,
                    v4_addresses_config=IpAddressesConfig(
                        starting_ip=uu_arp_gateway_ip,
                        increment_ip="0.0.0.1",
                        gateway_starting_ip=uu_arp_starting_ip,
                        gateway_increment_ip="0.0.0.0",
                        mask=16,
                    ),
                ),
                DeviceGroupConfig(
                    device_group_index=4,
                    tag_name="BGP_PREFIX_FLAP",
                    multiplier=prefix_flap_session_count,
                    v6_addresses_config=IpAddressesConfig(
                        starting_ip=uu_prefix_flap_gateway_ip,
                        increment_ip="0:0:0:0::2",
                        gateway_starting_ip=uu_prefix_flap_starting_ip,
                        gateway_increment_ip="0:0:0:0::2",
                        mask=127,
                    ),
                    v6_bgp_config=BgpConfig(
                        local_as_4_bytes=uu_ixia_as,
                        local_as_increment=1,
                        enable_4_byte_local_as=True,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        route_scales=[
                            RouteScaleSpec(
                                network_group_index=0,
                                v6_route_scale=RouteScale(
                                    multiplier=1,
                                    prefix_count=uu_prefix_flap_prefix_count,
                                    starting_prefixes=uu_prefix_flap_starting_prefixes,
                                    prefix_step="0:0:0:0::0",
                                    prefix_length=48,
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    bgp_communities=uu_bgp_communities,
                                    prefix_flap_config=ixia_types.BgpFlapConfig(
                                        uptime_in_sec=prefix_flap_uptime,
                                        downtime_in_sec=prefix_flap_downtime,
                                    ),
                                ),
                            ),
                        ],
                    ),
                ),
                DeviceGroupConfig(
                    device_group_index=5,
                    tag_name="BGP_SESSION_FLAP",
                    multiplier=session_flap_session_count,
                    v4_addresses_config=IpAddressesConfig(
                        starting_ip=uu_session_flap_gateway_ip,
                        increment_ip="0.0.0.2",
                        gateway_starting_ip=uu_session_flap_starting_ip,
                        gateway_increment_ip="0.0.0.2",
                        mask=31,
                    ),
                    v4_bgp_config=BgpConfig(
                        local_as_4_bytes=uu_ixia_as,
                        local_as_increment=1,
                        enable_4_byte_local_as=True,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                        peer_flap_config=ixia_types.BgpFlapConfig(
                            uptime_in_sec=session_flap_uptime,
                            downtime_in_sec=session_flap_downtime,
                        ),
                        route_scales=[
                            RouteScaleSpec(
                                network_group_index=0,
                                v4_route_scale=RouteScale(
                                    multiplier=1,
                                    prefix_count=uu_session_flap_prefix_count,
                                    starting_prefixes=uu_session_flap_starting_prefixes,
                                    prefix_step="0.0.0.0",
                                    prefix_length=24,
                                    ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                    bgp_communities=uu_bgp_communities,
                                ),
                            ),
                        ],
                    ),
                ),
            ],
        ),
        BasicPortConfig(
            endpoint=du_endpoint,
            device_group_configs=[
                DeviceGroupConfig(
                    device_group_index=0,
                    tag_name="NO_V6_PACKET_LOSS_EXPECTED",
                    multiplier=du_v6_session_count,
                    v6_addresses_config=IpAddressesConfig(
                        starting_ip=du_bgp_v6_gateway_ip,
                        increment_ip="0:0:0:0::2",
                        gateway_starting_ip=du_bgp_v6_starting_ip,
                        gateway_increment_ip="0:0:0:0::2",
                        mask=127,
                    ),
                    v6_bgp_config=BgpConfig(
                        local_as_4_bytes=du_ixia_as,
                        local_as_increment=1,
                        enable_4_byte_local_as=True,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        enable_graceful_restart=True,
                        graceful_restart_timer=120,
                        advertise_end_of_rib=True,
                        route_scales=[
                            RouteScaleSpec(
                                network_group_index=0,
                                v6_route_scale=RouteScale(
                                    multiplier=1,
                                    prefix_count=du_v6_prefix_count,
                                    starting_prefixes=du_v6_starting_prefixes,
                                    prefix_step="0:0:0:0::0",
                                    prefix_length=48,
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    bgp_communities=du_bgp_communities,
                                ),
                            ),
                        ],
                    ),
                ),
                DeviceGroupConfig(
                    device_group_index=1,
                    tag_name="NO_V4_PACKET_LOSS_EXPECTED",
                    multiplier=du_v4_session_count,
                    v4_addresses_config=IpAddressesConfig(
                        starting_ip=du_bgp_v4_gateway_ip,
                        increment_ip="0.0.0.2",
                        gateway_starting_ip=du_bgp_v4_starting_ip,
                        gateway_increment_ip="0.0.0.2",
                        mask=31,
                    ),
                    v4_bgp_config=BgpConfig(
                        local_as_4_bytes=du_ixia_as,
                        local_as_increment=1,
                        enable_4_byte_local_as=True,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                        enable_graceful_restart=True,
                        graceful_restart_timer=120,
                        advertise_end_of_rib=True,
                        route_scales=[
                            RouteScaleSpec(
                                network_group_index=0,
                                v4_route_scale=RouteScale(
                                    multiplier=1,
                                    prefix_count=du_v4_prefix_count,
                                    starting_prefixes=du_v4_starting_prefixes,
                                    prefix_step="0.0.0.0",
                                    prefix_length=24,
                                    ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                    bgp_communities=du_bgp_communities,
                                ),
                            ),
                        ],
                    ),
                ),
            ],
        ),
    ]

    v6_traffic_name = "V6_TRAFFIC_DU_TO_UU"
    v4_traffic_name = "V4_TRAFFIC_DU_TO_UU"
    basic_traffic_item_configs = [
        BasicTrafficItemConfig(
            name=v6_traffic_name,
            src_endpoints=[
                TrafficEndpoint(
                    name=du_endpoint,
                    device_group_index=0,
                    network_group_index=0,
                ),
            ],
            dest_endpoints=[
                TrafficEndpoint(
                    name=uu_endpoint,
                    device_group_index=0,
                    network_group_index=0,
                ),
            ],
            line_rate=traffic_line_rate,
            traffic_type=ixia_types.TrafficType.IPV6,
            merge_destinations=False,
            bidirectional=False,
            src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
        ),
        BasicTrafficItemConfig(
            name=v4_traffic_name,
            src_endpoints=[
                TrafficEndpoint(
                    name=du_endpoint,
                    device_group_index=1,
                    network_group_index=0,
                ),
            ],
            dest_endpoints=[
                TrafficEndpoint(
                    name=uu_endpoint,
                    device_group_index=1,
                    network_group_index=0,
                ),
            ],
            line_rate=traffic_line_rate,
            traffic_type=ixia_types.TrafficType.IPV4,
            merge_destinations=False,
            bidirectional=False,
            src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
        ),
    ]

    playbooks_ = create_all_lag_playbooks(
        dut_name=uu_device_name,
        remote_name=du_device_name,
        dut_port_channel_name=uu_portchannel_name,
        remote_port_channel_name=du_portchannel_name,
        dut_member_interfaces=uu_portchannel_links,
        remote_member_interfaces=du_portchannel_links,
        min_link_percentage=min_link_percentage,
        min_link_up_percentage=min_link_up_percentage,
        dut_mistmatch_min_link_percentage=uu_mismatch_min_link,
        dut_mistmatch_min_link_up_percentage=uu_mismatch_min_link_up,
        remote_mistmatch_min_link_percentage=du_mismatch_min_link,
        remote_mistmatch_min_link_up_percentage=du_mismatch_min_link_up,
    )

    return TestConfig(
        name=test_config_name,
        skip_ixia_protocol_verification=True,
        basset_pool=basset_pool,
        endpoints=[
            Endpoint(
                name=uu_device_name,
                ixia_ports=[uu_ixia_interface],
                dut=True,
                direct_ixia_connections=uu_direct_ixia_connections,
            ),
            Endpoint(
                name=du_device_name,
                ixia_ports=[du_ixia_interface],
                dut=False,
                direct_ixia_connections=du_direct_ixia_connections,
            ),
        ],
        setup_tasks=setup_tasks,
        teardown_tasks=[
            create_coop_unregister_patchers_task(hostnames),
        ],
        basic_port_configs=basic_port_configs,
        basic_traffic_item_configs=basic_traffic_item_configs,
        traffic_items_to_start=[v6_traffic_name, v4_traffic_name],
        playbooks=playbooks_,
    )


KODIAK3_CI_CD_LAG_TEST_CONFIG = test_config_for_portchannel(
    test_config_name="KODIAK3_CI_CD_LAG_TEST_CONFIG",
    ixia_chassis_ip="2401:db00:2066:3036::3001",
    ixia_uu_port="1/1",
    ixia_du_port="1/2",
    # UU device (upstream) - topology
    uu_device_name="fa003-uu001.qza1",
    uu_ixia_interface="eth1/64/5",
    # DU device (downstream) - topology
    du_device_name="fa003-du004.qza1",
    du_ixia_interface="eth1/64/5",
    # Portchannel config (UU-DU direct BGP peering)
    uu_portchannel_name="Port-Channel304",
    du_portchannel_name="Port-Channel301",
    # Portchannel links
    # 1-1 mapping between UU and DU: e.g. du_portchannel_links[i] and uu_portchannel_links[i] are connected
    uu_portchannel_links=["eth1/13/1", "eth1/14/1", "eth1/15/1", "eth1/16/1"],
    du_portchannel_links=["eth1/49/1", "eth1/53/1", "eth1/57/1", "eth1/61/1"],
    # Portchannel minlink config
    min_link_percentage=0.5,
    min_link_up_percentage=0.75,
    # Mismatch minlink config
    uu_mismatch_min_link=0.25,
    uu_mismatch_min_link_up=0.8,
    du_mismatch_min_link=0.5,
    du_mismatch_min_link_up=0.75,
    # IXIA ASN config
    uu_ixia_as=64734,
    du_ixia_as=64901,
    # UU BGP config
    uu_remote_as=7004,
    uu_eb_peergroup_v6="PEERGROUP_FAUU_EB_V6",
    uu_eb_peergroup_v4="PEERGROUP_FAUU_EB_V4",
    uu_eb_ingress_policy="PROPAGATE_FAUU_EB_IN",
    uu_eb_egress_policy="PROPAGATE_FAUU_EB_OUT",
    uu_du_ingress_policy="PROPAGATE_FAUU_FADU_IN",
    uu_du_egress_policy="PROPAGATE_FAUU_FADU_OUT",
    uu_eb_peer_tag="EB",
    uu_du_peer_tag="DU",
    # UU BGP peers IP config
    uu_bgp_v6_starting_ip="2401:db00:e50d:11:8::0",
    uu_bgp_v6_gateway_ip="2401:db00:e50d:11:8::1",
    uu_bgp_v4_starting_ip="192.168.0.0",
    uu_bgp_v4_gateway_ip="192.168.0.1",
    # UU stressor IP config
    uu_ndp_starting_ip="2401:db00:e50d:11:9::0",
    uu_ndp_gateway_ip="2401:db00:e50d:11:9::1",
    uu_arp_starting_ip="192.168.1.0",
    uu_arp_gateway_ip="192.168.1.1",
    # UU BGP flap IP config
    uu_prefix_flap_starting_ip="2401:db00:e50d:11:a::0",
    uu_prefix_flap_gateway_ip="2401:db00:e50d:11:a::1",
    uu_session_flap_starting_ip="192.168.2.0",
    uu_session_flap_gateway_ip="192.168.2.1",
    # UU route scale
    uu_v6_prefix_count=25000,
    uu_v6_starting_prefixes="5401:db00:1000::",
    uu_v4_prefix_count=25000,
    uu_v4_starting_prefixes="10.1.0.0",
    uu_bgp_communities=["65526:35724"],
    uu_prefix_flap_prefix_count=10000,
    uu_prefix_flap_starting_prefixes="5401:db00:2000::",
    uu_session_flap_prefix_count=10000,
    uu_session_flap_starting_prefixes="10.2.0.0",
    # DU BGP config
    du_remote_as=8001,
    du_ssw_peergroup_v6="PEERGROUP_FADU_SSW_V6",
    du_ssw_peergroup_v4="PEERGROUP_FADU_SSW_V4",
    du_ssw_ingress_policy="PROPAGATE_FADU_SSW_IN",
    du_ssw_egress_policy="PROPAGATE_FADU_SSW_OUT",
    du_uu_ingress_policy="PROPAGATE_FADU_FAUU_IN",
    du_uu_egress_policy="PROPAGATE_FADU_FAUU_OUT",
    du_ssw_peer_tag="SSW",
    du_uu_peer_tag="UU",
    # DU BGP peers IP config
    du_bgp_v6_starting_ip="2401:eb00:e50d:11:8::0",
    du_bgp_v6_gateway_ip="2401:eb00:e50d:11:8::1",
    du_bgp_v4_starting_ip="192.168.3.0",
    du_bgp_v4_gateway_ip="192.168.3.1",
    # DU route scale
    du_v6_prefix_count=5000,
    du_v6_starting_prefixes="7401:db00:1001::",
    du_v4_prefix_count=5000,
    du_v4_starting_prefixes="20.1.0.0",
    du_bgp_communities=[
        "65441:132",
        "65442:133",
        "65529:26730",
    ],
    # Session counts
    uu_v6_session_count=8,
    uu_v4_session_count=8,
    du_v6_session_count=48,
    du_v4_session_count=48,
    # Scale parameters
    prefix_limit=74000,
    max_routes=90000,
    # Stressor scale
    ndp_stressor_multiplier=10,
    arp_stressor_multiplier=10,
    # BGP flap parameters
    prefix_flap_session_count=10,
    session_flap_session_count=10,
    prefix_flap_uptime=15,
    prefix_flap_downtime=15,
    session_flap_uptime=120,
    session_flap_downtime=15,
    # Portchannel parameters
    portchannel_session_count=48,
    uu_portchannel_bgp_v6_starting_ip="2401:db00:e50d:11:f::0",
    uu_portchannel_bgp_v6_gateway_ip="2401:db00:e50d:11:f::1",
    uu_portchannel_bgp_v4_starting_ip="192.168.10.0",
    uu_portchannel_bgp_v4_gateway_ip="192.168.10.1",
    uu_portchannel_peergroup_v6="PEERGROUP_FAUU_FADU_V6",
    uu_portchannel_peergroup_v4="PEERGROUP_FAUU_FADU_V4",
    du_portchannel_peergroup_v6="PEERGROUP_FADU_FAUU_V6",
    du_portchannel_peergroup_v4="PEERGROUP_FADU_FAUU_V4",
    # Traffic parameters
    traffic_line_rate=48,
    # Optional overrides
    basset_pool="dne.test",
)


PORTCHANNEL_TEST_CONFIGS = [KODIAK3_CI_CD_LAG_TEST_CONFIG]
