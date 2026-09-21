# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Port-channel TestConfig builders.

Hosts the legacy fixture-style ``portchannel_test_config()`` (FAUU + DU, QZD1 lab) and
the parameterized ``test_config_for_portchannel`` factory that drives port-channel +
BGP qualification on any two-device topology.

The factory names its two devices ``uplink``/``downlink`` and peers IXIA into each via
``PEERGROUP_{UPLINK,DOWNLINK}_IXIA_{V6,V4}``, which default to the TAAC
``PROPAGATE_EVERYTHING_IN``/``_OUT`` policies so a new topology only has to supply
devices, interfaces and scale. Callers that need production peer groups and policies
(FAUU+FADU, FAN<>FAN) pass their own names.
"""

import json
import typing as t
from dataclasses import dataclass

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


@dataclass(frozen=True)
class IxiaPortSpec:
    """One physical IXIA connection on one device.

    Grouped rather than passed as parallel lists so the address ranges cannot
    drift out of alignment with the interface they belong to. Every range has to
    be unique across the ports of a device.
    """

    # DUT-side interface, e.g. "eth1/62/1".
    interface: str
    # Chassis slot/port, e.g. "1/13".
    chassis_port: str
    v6_session_count: int
    v4_session_count: int
    bgp_v6_starting_ip: str
    bgp_v6_gateway_ip: str
    bgp_v4_starting_ip: str
    bgp_v4_gateway_ip: str
    # Per session; total advertised is session_count * prefix_count.
    v6_prefix_count: int
    v6_starting_prefixes: str
    v4_prefix_count: int
    v4_starting_prefixes: str


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
    # Uplink device - topology. The role names the IXIA peer groups
    # (PEERGROUP_<role>_IXIA_V6/V4), so it has to match the device's role.
    uplink_device: str,
    uplink_role: str,
    uplink_ixia_ports: list[IxiaPortSpec],
    # Downlink device - topology
    downlink_device: str,
    downlink_role: str,
    downlink_ixia_ports: list[IxiaPortSpec],
    # Portchannel config (uplink-downlink direct BGP peering)
    uplink_portchannel_name: str,
    downlink_portchannel_name: str,
    # Portchannel links
    # 1-1 mapping: downlink_portchannel_links[i] connects to uplink_portchannel_links[i]
    uplink_portchannel_links: list[str],
    downlink_portchannel_links: list[str],
    # Portchannel minlink config
    min_link_percentage: float = 0.5,
    min_link_up_percentage: float = 0.75,
    # Mismatch minlink config
    uplink_mismatch_min_link: float = 0.5,
    uplink_mismatch_min_link_up: float = 0.8,
    downlink_mismatch_min_link: float = 0.6,
    downlink_mismatch_min_link_up: float = 0.7,
    # IXIA ASN config
    uplink_ixia_as: int = 64734,
    downlink_ixia_as: int = 64901,
    # Uplink BGP config
    uplink_remote_as: int = 4290000001,
    uplink_ixia_ingress_policy: str = "PROPAGATE_EVERYTHING_IN",
    uplink_ixia_egress_policy: str = "PROPAGATE_EVERYTHING_OUT",
    uplink_portchannel_ingress_policy: str = "PROPAGATE_FAUU_FADU_IN",
    uplink_portchannel_egress_policy: str = "PROPAGATE_FAUU_FADU_OUT",
    uplink_ixia_peer_tag: str = "IXIA",
    uplink_portchannel_peer_tag: str = "DU",
    # Uplink stressor IP config
    uplink_ndp_starting_ip: str = "2401:db00:e50d:11:9::0",
    uplink_ndp_gateway_ip: str = "2401:db00:e50d:11:9::1",
    uplink_arp_starting_ip: str = "192.168.1.0",
    uplink_arp_gateway_ip: str = "192.168.1.1",
    # Uplink BGP flap IP config
    uplink_prefix_flap_starting_ip: str = "2401:db00:e50d:11:a::0",
    uplink_prefix_flap_gateway_ip: str = "2401:db00:e50d:11:a::1",
    uplink_session_flap_starting_ip: str = "192.168.2.0",
    uplink_session_flap_gateway_ip: str = "192.168.2.1",
    # IXIA stamps these on the routes it originates. With the IXIA peer groups on
    # PROPAGATE_EVERYTHING they no longer gate ingress; they only matter where the
    # portchannel policy below evaluates communities.
    uplink_bgp_communities: list[str] | None = None,
    uplink_prefix_flap_prefix_count: int = 10000,
    uplink_prefix_flap_starting_prefixes: str = "6401:db00::",
    uplink_session_flap_prefix_count: int = 10000,
    uplink_session_flap_starting_prefixes: str = "20.0.0.0",
    # Downlink BGP config
    downlink_remote_as: int = 8001,
    downlink_ixia_ingress_policy: str = "PROPAGATE_EVERYTHING_IN",
    downlink_ixia_egress_policy: str = "PROPAGATE_EVERYTHING_OUT",
    downlink_portchannel_ingress_policy: str = "PROPAGATE_FADU_FAUU_IN",
    downlink_portchannel_egress_policy: str = "PROPAGATE_FADU_FAUU_OUT",
    downlink_ixia_peer_tag: str = "IXIA",
    downlink_portchannel_peer_tag: str = "UU",
    # See uplink_bgp_communities.
    downlink_bgp_communities: list[str] | None = None,
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
    uplink_portchannel_bgp_v6_starting_ip: str = "2401:db00:e50d:11:f::0",
    uplink_portchannel_bgp_v6_gateway_ip: str = "2401:db00:e50d:11:f::1",
    uplink_portchannel_bgp_v4_starting_ip: str = "192.168.10.0",
    uplink_portchannel_bgp_v4_gateway_ip: str = "192.168.10.1",
    uplink_portchannel_peergroup_v6: str = "PEERGROUP_FAUU_FADU_V6",
    uplink_portchannel_peergroup_v4: str = "PEERGROUP_FAUU_FADU_V4",
    downlink_portchannel_peergroup_v6: str = "PEERGROUP_FADU_FAUU_V6",
    downlink_portchannel_peergroup_v4: str = "PEERGROUP_FADU_FAUU_V4",
    # LAG suite pacing. iteration_override pins every playbook to one count
    # instead of its per-playbook default (10-25).
    lag_iteration_override: int | None = None,
    lag_longevity_duration: int = 3600,
    # CIDRs excluded from BGP_SESSION_ESTABLISH_CHECK. Needed where the device
    # carries listen-range peers (e.g. BGP_MONITOR) that never establish.
    bgp_parent_prefixes_to_ignore: list[str] | None = None,
    # Services dropped from SERVICE_RESTART_CHECK on platforms that never
    # deploy them, which would otherwise fail the check on every playbook.
    services_to_skip: list[str] | None = None,
    # Seconds to wait after enabling ports before their state is asserted.
    # Coherent ZR optics need 120-180s to acquire lock.
    link_up_wait_s: int = 10,
    # Traffic parameters
    traffic_line_rate: int = 50,
    # Optional overrides
    basset_pool: str = "dne.test",
    additional_setup_tasks: list[Task] | None = None,
) -> TestConfig:
    hostnames = [uplink_device, downlink_device]
    if uplink_bgp_communities is None:
        uplink_bgp_communities = ["65526:35724"]
    if downlink_bgp_communities is None:
        downlink_bgp_communities = ["65441:132", "65442:133", "65529:26730"]
    uplink_ixia_peergroup_v6 = f"PEERGROUP_{uplink_role}_IXIA_V6"
    uplink_ixia_peergroup_v4 = f"PEERGROUP_{uplink_role}_IXIA_V4"
    downlink_ixia_peergroup_v6 = f"PEERGROUP_{downlink_role}_IXIA_V6"
    downlink_ixia_peergroup_v4 = f"PEERGROUP_{downlink_role}_IXIA_V4"
    # The first port of each side carries the uplink-only stressor and BGP-flap
    # device groups; the rest carry plain V6/V4 sessions.
    uplink_primary = uplink_ixia_ports[0]

    def _endpoint(device: str, port: IxiaPortSpec) -> str:
        return f"{device}:{port.interface}"

    def _direct_connections(ports: list[IxiaPortSpec]) -> list[DirectIxiaConnection]:
        return [
            DirectIxiaConnection(
                interface=port.interface,
                ixia_chassis_ip=ixia_chassis_ip,
                ixia_port=port.chassis_port,
            )
            for port in ports
        ]

    def _speed_patcher_tasks(device: str, ports: list[IxiaPortSpec]) -> list[Task]:
        return [
            create_coop_register_patcher_task(
                hostname=device,
                config_name="agent",
                patcher_name=(
                    f"change_speed_patcher_{port.interface.replace('/', '_')}_400g"
                ),
                task_name="coop_register_patcher",
                patcher_args={
                    "intfs": port.interface,
                    "speed": "FOURHUNDREDG",
                    "profile_id": "PROFILE_400G_4_PAM4_RS544X2N_OPTICAL",
                },
                py_func_name="change_speed",
            )
            for port in ports
        ]

    def _ixia_peer_blocks(
        port: IxiaPortSpec, ixia_as: int, peergroup_v6: str, peergroup_v4: str
    ) -> list[dict[str, t.Any]]:
        return [
            {
                "starting_ip": port.bgp_v6_starting_ip,
                "increment_ip": "0:0:0:0::2",
                "prefix_length": 127,
                "description": "Regular IPv6 BGP Peers",
                "peer_group_name": peergroup_v6,
                "num_sessions": port.v6_session_count,
                "remote_as_4_byte": ixia_as,
                "remote_as_4_byte_step": 1,
                "gateway_starting_ip": port.bgp_v6_gateway_ip,
                "gateway_increment_ip": "0:0:0:0::2",
            },
            {
                "starting_ip": port.bgp_v4_starting_ip,
                "increment_ip": "0.0.0.2",
                "prefix_length": 31,
                "description": "Regular IPv4 BGP Peers",
                "peer_group_name": peergroup_v4,
                "num_sessions": port.v4_session_count,
                "remote_as_4_byte": ixia_as,
                "remote_as_4_byte_step": 1,
                "gateway_starting_ip": port.bgp_v4_gateway_ip,
                "gateway_increment_ip": "0.0.0.2",
            },
        ]

    # Stressors and BGP flap ride the uplink's first port only, so adding ports
    # does not multiply the flap session counts.
    _uplink_extra_peer_blocks: list[dict[str, t.Any]] = [
        {
            "starting_ip": uplink_ndp_starting_ip,
            "increment_ip": "0:0:0:0::0",
            "prefix_length": 80,
            "description": "NDP stressor",
            "peer_group_name": uplink_ixia_peergroup_v6,
            "num_sessions": 1,
            "remote_as_4_byte": uplink_ixia_as,
            "remote_as_4_byte_step": 1,
            "gateway_starting_ip": uplink_ndp_gateway_ip,
            "gateway_increment_ip": "0:0:0:0::0",
            "config_only_interface_ip": True,
        },
        {
            "starting_ip": uplink_arp_starting_ip,
            "increment_ip": "0.0.0.1",
            "prefix_length": 16,
            "description": "ARP stressor",
            "peer_group_name": uplink_ixia_peergroup_v4,
            "num_sessions": 1,
            "remote_as_4_byte": uplink_ixia_as,
            "gateway_starting_ip": uplink_arp_gateway_ip,
            "gateway_increment_ip": "0.0.0.1",
            "config_only_interface_ip": True,
        },
        {
            "starting_ip": uplink_prefix_flap_starting_ip,
            "increment_ip": "0:0:0:0::2",
            "prefix_length": 127,
            "description": "BGP Prefix Flap",
            "peer_group_name": uplink_ixia_peergroup_v6,
            "num_sessions": prefix_flap_session_count,
            "remote_as_4_byte": uplink_ixia_as,
            "remote_as_4_byte_step": 1,
            "gateway_starting_ip": uplink_prefix_flap_gateway_ip,
            "gateway_increment_ip": "0:0:0:0::2",
        },
        {
            "starting_ip": uplink_session_flap_starting_ip,
            "increment_ip": "0.0.0.2",
            "prefix_length": 31,
            "description": "BGP Session Flap",
            "peer_group_name": uplink_ixia_peergroup_v4,
            "num_sessions": session_flap_session_count,
            "remote_as_4_byte": uplink_ixia_as,
            "remote_as_4_byte_step": 1,
            "gateway_starting_ip": uplink_session_flap_gateway_ip,
            "gateway_increment_ip": "0.0.0.2",
        },
    ]

    setup_tasks = [
        create_coop_unregister_patchers_task(uplink_device),
        create_coop_unregister_patchers_task(downlink_device),
        *_speed_patcher_tasks(uplink_device, uplink_ixia_ports),
        *_speed_patcher_tasks(downlink_device, downlink_ixia_ports),
        create_coop_register_patcher_task(
            hostname=uplink_device,
            config_name="agent",
            patcher_name=f"set_port_channel_min_link_capacity_{uplink_portchannel_name.replace('-', '_')}",
            task_name="coop_register_patcher",
            patcher_args={
                "port_channel_name": uplink_portchannel_name,
                "link_percentage": str(min_link_percentage),
                "link_up_percentage": str(min_link_up_percentage),
            },
            py_func_name="set_port_channel_min_link_capacity",
        ),
        create_coop_register_patcher_task(
            hostname=downlink_device,
            config_name="agent",
            patcher_name=f"set_port_channel_min_link_capacity_{downlink_portchannel_name.replace('-', '_')}",
            task_name="coop_register_patcher",
            patcher_args={
                "port_channel_name": downlink_portchannel_name,
                "link_percentage": str(min_link_percentage),
                "link_up_percentage": str(min_link_up_percentage),
            },
            py_func_name="set_port_channel_min_link_capacity",
        ),
        create_coop_register_patcher_task(
            hostname=uplink_device,
            config_name="bgpcpp",
            patcher_name=f"00_add_bgp_policy_statement_{uplink_ixia_ingress_policy}",
            task_name="coop_register_patcher",
            patcher_args={
                "name": uplink_ixia_ingress_policy,
                "description": "Policy for uplink IXIA IN",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname=uplink_device,
            config_name="bgpcpp",
            patcher_name=f"00_add_bgp_policy_statement_{uplink_ixia_egress_policy}",
            task_name="coop_register_patcher",
            patcher_args={
                "name": uplink_ixia_egress_policy,
                "description": "Policy for uplink IXIA OUT",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname=downlink_device,
            config_name="bgpcpp",
            patcher_name=f"00_add_bgp_policy_statement_{downlink_ixia_ingress_policy}",
            task_name="coop_register_patcher",
            patcher_args={
                "name": downlink_ixia_ingress_policy,
                "description": "Policy for downlink IXIA IN",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname=downlink_device,
            config_name="bgpcpp",
            patcher_name=f"00_add_bgp_policy_statement_{downlink_ixia_egress_policy}",
            task_name="coop_register_patcher",
            patcher_args={
                "name": downlink_ixia_egress_policy,
                "description": "Policy for downlink IXIA OUT",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname=uplink_device,
            config_name="bgpcpp",
            patcher_name=f"00_add_peer_group_patcher_{uplink_ixia_peergroup_v6}",
            task_name="coop_register_patcher",
            patcher_args={
                "name": uplink_ixia_peergroup_v6,
                "description": "BGP peering from uplink to IXIA, IPV6 sessions",
                "next_hop_self": "True",
                "disable_ipv4_afi": "True",
                "disable_ipv6_afi": "False",
                "is_confed_peer": "False",
                "ingress_policy_name": uplink_ixia_ingress_policy,
                "egress_policy_name": uplink_ixia_egress_policy,
                "bgp_peer_timers_hold_time_seconds": "30",
                "bgp_peer_timers_keep_alive_seconds": "10",
                "bgp_peer_timers_out_delay_seconds": "7",
                "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                "peer_tag": uplink_ixia_peer_tag,
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
            hostname=uplink_device,
            config_name="bgpcpp",
            patcher_name=f"00_add_peer_group_patcher_{uplink_ixia_peergroup_v4}",
            task_name="coop_register_patcher",
            patcher_args={
                "name": uplink_ixia_peergroup_v4,
                "description": "BGP peering from uplink to IXIA, IPV4 sessions",
                "next_hop_self": "True",
                "disable_ipv4_afi": "False",
                "disable_ipv6_afi": "True",
                "is_confed_peer": "False",
                "ingress_policy_name": uplink_ixia_ingress_policy,
                "egress_policy_name": uplink_ixia_egress_policy,
                "bgp_peer_timers_hold_time_seconds": "30",
                "bgp_peer_timers_keep_alive_seconds": "10",
                "bgp_peer_timers_out_delay_seconds": "7",
                "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                "peer_tag": uplink_ixia_peer_tag,
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
        # Downlink IXIA peer groups (analogous to the uplink pair above).
        create_coop_register_patcher_task(
            hostname=downlink_device,
            config_name="bgpcpp",
            patcher_name=f"00_add_peer_group_patcher_{downlink_ixia_peergroup_v6}",
            task_name="coop_register_patcher",
            patcher_args={
                "name": downlink_ixia_peergroup_v6,
                "description": "BGP peering from downlink to IXIA, IPV6 sessions",
                "next_hop_self": "True",
                "disable_ipv4_afi": "True",
                "disable_ipv6_afi": "False",
                "is_confed_peer": "False",
                "ingress_policy_name": downlink_ixia_ingress_policy,
                "egress_policy_name": downlink_ixia_egress_policy,
                "bgp_peer_timers_hold_time_seconds": "30",
                "bgp_peer_timers_keep_alive_seconds": "10",
                "bgp_peer_timers_out_delay_seconds": "7",
                "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                "peer_tag": downlink_ixia_peer_tag,
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
            hostname=downlink_device,
            config_name="bgpcpp",
            patcher_name=f"00_add_peer_group_patcher_{downlink_ixia_peergroup_v4}",
            task_name="coop_register_patcher",
            patcher_args={
                "name": downlink_ixia_peergroup_v4,
                "description": "BGP peering from downlink to IXIA, IPV4 sessions",
                "next_hop_self": "True",
                "disable_ipv4_afi": "False",
                "disable_ipv6_afi": "True",
                "is_confed_peer": "False",
                "ingress_policy_name": downlink_ixia_ingress_policy,
                "egress_policy_name": downlink_ixia_egress_policy,
                "bgp_peer_timers_hold_time_seconds": "30",
                "bgp_peer_timers_keep_alive_seconds": "10",
                "bgp_peer_timers_out_delay_seconds": "7",
                "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                "peer_tag": downlink_ixia_peer_tag,
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
            hostname=uplink_device,
            config_name="bgpcpp",
            patcher_name="configure_bgp_switch_limit",
            task_name="coop_register_patcher",
            patcher_args={
                "prefix_limit": str(prefix_limit),
            },
            py_func_name="configure_bgp_switch_limit",
        ),
        create_coop_register_patcher_task(
            hostname=downlink_device,
            config_name="bgpcpp",
            patcher_name="configure_bgp_switch_limit",
            task_name="coop_register_patcher",
            patcher_args={
                "prefix_limit": str(prefix_limit),
            },
            py_func_name="configure_bgp_switch_limit",
        ),
        # Portchannel peer groups for UU and DU V4
        *(
            [
                create_coop_register_patcher_task(
                    hostname=uplink_device,
                    config_name="bgpcpp",
                    patcher_name=f"add_peer_group_patcher_{uplink_portchannel_peergroup_v4}",
                    task_name="coop_register_patcher",
                    patcher_args={
                        "name": uplink_portchannel_peergroup_v4,
                        "description": "BGP peering from uplink to downlink, IPV4 sessions",
                        "next_hop_self": "True",
                        "disable_ipv4_afi": "False",
                        "disable_ipv6_afi": "True",
                        "is_confed_peer": "True",
                        "ingress_policy_name": uplink_portchannel_ingress_policy,
                        "egress_policy_name": uplink_portchannel_egress_policy,
                        "bgp_peer_timers_hold_time_seconds": "30",
                        "bgp_peer_timers_keep_alive_seconds": "10",
                        "bgp_peer_timers_out_delay_seconds": "7",
                        "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                        "peer_tag": uplink_portchannel_peer_tag,
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
                    hostname=downlink_device,
                    config_name="bgpcpp",
                    patcher_name=f"add_peer_group_patcher_{downlink_portchannel_peergroup_v4}",
                    task_name="coop_register_patcher",
                    patcher_args={
                        "name": downlink_portchannel_peergroup_v4,
                        "description": "BGP peering from downlink to uplink, IPV4 sessions",
                        "next_hop_self": "True",
                        "disable_ipv4_afi": "False",
                        "disable_ipv6_afi": "True",
                        "is_confed_peer": "True",
                        "ingress_policy_name": downlink_portchannel_ingress_policy,
                        "egress_policy_name": downlink_portchannel_egress_policy,
                        "bgp_peer_timers_hold_time_seconds": "30",
                        "bgp_peer_timers_keep_alive_seconds": "10",
                        "bgp_peer_timers_out_delay_seconds": "7",
                        "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                        "peer_tag": downlink_portchannel_peer_tag,
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
            ]
            if portchannel_session_count
            else []
        ),
        create_coop_register_patcher_task(
            hostname=uplink_device,
            config_name="bgpcpp",
            patcher_name=f"add_bgp_policy_match_prefix_to_propagate_routes_{uplink_ixia_ingress_policy}_v4_1",
            task_name="coop_register_patcher",
            patcher_args={
                "matching_prefix": "10.0.0.0/8",
                "in_stmt_name": uplink_ixia_ingress_policy,
                "out_stmt_name": uplink_portchannel_egress_policy,
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname=uplink_device,
            config_name="bgpcpp",
            patcher_name=f"add_bgp_policy_match_prefix_to_propagate_routes_{uplink_ixia_ingress_policy}_v4_2",
            task_name="coop_register_patcher",
            patcher_args={
                "matching_prefix": "20.0.0.0/8",
                "in_stmt_name": uplink_ixia_ingress_policy,
                "out_stmt_name": uplink_portchannel_egress_policy,
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname=uplink_device,
            config_name="bgpcpp",
            patcher_name=f"add_bgp_policy_match_prefix_to_propagate_routes_{uplink_ixia_egress_policy}_v4",
            task_name="coop_register_patcher",
            patcher_args={
                "matching_prefix": "30.0.0.0/8",
                "out_stmt_name": uplink_ixia_egress_policy,
                "in_stmt_name": uplink_portchannel_ingress_policy,
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname=uplink_device,
            config_name="bgpcpp",
            patcher_name=f"add_bgp_policy_match_prefix_to_propagate_routes_{uplink_ixia_ingress_policy}_v6_1",
            task_name="coop_register_patcher",
            patcher_args={
                "matching_prefix": "5401::/16",
                "in_stmt_name": uplink_ixia_ingress_policy,
                "out_stmt_name": uplink_portchannel_egress_policy,
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname=uplink_device,
            config_name="bgpcpp",
            patcher_name=f"add_bgp_policy_match_prefix_to_propagate_routes_{uplink_ixia_ingress_policy}_v6_2",
            task_name="coop_register_patcher",
            patcher_args={
                "matching_prefix": "6401::/16",
                "in_stmt_name": uplink_ixia_ingress_policy,
                "out_stmt_name": uplink_portchannel_egress_policy,
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname=uplink_device,
            config_name="bgpcpp",
            patcher_name=f"add_bgp_policy_match_prefix_to_propagate_routes_{uplink_ixia_egress_policy}_v6",
            task_name="coop_register_patcher",
            patcher_args={
                "matching_prefix": "7401::/16",
                "out_stmt_name": uplink_ixia_egress_policy,
                "in_stmt_name": uplink_portchannel_ingress_policy,
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname=downlink_device,
            config_name="bgpcpp",
            patcher_name=f"add_bgp_policy_match_prefix_to_propagate_routes_{downlink_ixia_ingress_policy}_v4",
            task_name="coop_register_patcher",
            patcher_args={
                "matching_prefix": "30.0.0.0/8",
                "in_stmt_name": downlink_ixia_ingress_policy,
                "out_stmt_name": downlink_portchannel_egress_policy,
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname=downlink_device,
            config_name="bgpcpp",
            patcher_name=f"add_bgp_policy_match_prefix_to_propagate_routes_{downlink_ixia_egress_policy}_v4_1",
            task_name="coop_register_patcher",
            patcher_args={
                "matching_prefix": "10.0.0.0/8",
                "out_stmt_name": downlink_ixia_egress_policy,
                "in_stmt_name": downlink_portchannel_ingress_policy,
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname=downlink_device,
            config_name="bgpcpp",
            patcher_name=f"add_bgp_policy_match_prefix_to_propagate_routes_{downlink_ixia_egress_policy}_v4_2",
            task_name="coop_register_patcher",
            patcher_args={
                "matching_prefix": "20.0.0.0/8",
                "out_stmt_name": downlink_ixia_egress_policy,
                "in_stmt_name": downlink_portchannel_ingress_policy,
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname=downlink_device,
            config_name="bgpcpp",
            patcher_name=f"add_bgp_policy_match_prefix_to_propagate_routes_{downlink_ixia_ingress_policy}_v6",
            task_name="coop_register_patcher",
            patcher_args={
                "matching_prefix": "7401::/16",
                "in_stmt_name": downlink_ixia_ingress_policy,
                "out_stmt_name": downlink_portchannel_egress_policy,
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname=downlink_device,
            config_name="bgpcpp",
            patcher_name=f"add_bgp_policy_match_prefix_to_propagate_routes_{downlink_ixia_egress_policy}_v6_1",
            task_name="coop_register_patcher",
            patcher_args={
                "matching_prefix": "5401::/16",
                "out_stmt_name": downlink_ixia_egress_policy,
                "in_stmt_name": downlink_portchannel_ingress_policy,
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname=downlink_device,
            config_name="bgpcpp",
            patcher_name=f"add_bgp_policy_match_prefix_to_propagate_routes_{downlink_ixia_egress_policy}_v6_2",
            task_name="coop_register_patcher",
            patcher_args={
                "matching_prefix": "6401::/16",
                "out_stmt_name": downlink_ixia_egress_policy,
                "in_stmt_name": downlink_portchannel_ingress_policy,
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_configure_parallel_bgp_peers_task(
            hostname=uplink_device,
            configure_vlans_patcher_name="configure_vlans_patcher_portchannel",
            add_bgp_peers_patcher_name="add_bgp_peers_patcher_portchannel",
            config_json=json.dumps(
                {
                    **{
                        port.interface: _ixia_peer_blocks(
                            port,
                            uplink_ixia_as,
                            uplink_ixia_peergroup_v6,
                            uplink_ixia_peergroup_v4,
                        )
                        + (_uplink_extra_peer_blocks if port is uplink_primary else [])
                        for port in uplink_ixia_ports
                    },
                    **(
                        {
                            uplink_portchannel_links[0]: [
                                {
                                    "starting_ip": uplink_portchannel_bgp_v6_starting_ip,
                                    "increment_ip": "0:0:0:0::2",
                                    "prefix_length": 127,
                                    "description": "Uplink-downlink portchannel IPv6 BGP sessions",
                                    "peer_group_name": uplink_portchannel_peergroup_v6,
                                    "num_sessions": portchannel_session_count,
                                    "remote_as_4_byte": uplink_remote_as,
                                    "remote_as_4_byte_step": 0,
                                    "gateway_starting_ip": uplink_portchannel_bgp_v6_gateway_ip,
                                    "gateway_increment_ip": "0:0:0:0::2",
                                },
                                {
                                    "starting_ip": uplink_portchannel_bgp_v4_starting_ip,
                                    "increment_ip": "0.0.0.2",
                                    "prefix_length": 31,
                                    "description": "Uplink-downlink portchannel IPv4 BGP sessions",
                                    "peer_group_name": uplink_portchannel_peergroup_v4,
                                    "num_sessions": portchannel_session_count,
                                    "remote_as_4_byte": uplink_remote_as,
                                    "remote_as_4_byte_step": 0,
                                    "gateway_starting_ip": uplink_portchannel_bgp_v4_gateway_ip,
                                    "gateway_increment_ip": "0.0.0.2",
                                },
                            ]
                        }
                        if portchannel_session_count
                        else {}
                    ),
                }
            ),
        ),
        create_configure_parallel_bgp_peers_task(
            hostname=downlink_device,
            configure_vlans_patcher_name="configure_vlans_patcher_portchannel",
            add_bgp_peers_patcher_name="add_bgp_peers_patcher_portchannel",
            config_json=json.dumps(
                {
                    **{
                        port.interface: _ixia_peer_blocks(
                            port,
                            downlink_ixia_as,
                            downlink_ixia_peergroup_v6,
                            downlink_ixia_peergroup_v4,
                        )
                        for port in downlink_ixia_ports
                    },
                    **(
                        {
                            downlink_portchannel_links[0]: [
                                {
                                    "starting_ip": uplink_portchannel_bgp_v6_gateway_ip,
                                    "increment_ip": "0:0:0:0::2",
                                    "prefix_length": 127,
                                    "description": "Downlink-uplink portchannel BGP sessions",
                                    "peer_group_name": downlink_portchannel_peergroup_v6,
                                    "num_sessions": portchannel_session_count,
                                    "remote_as_4_byte": downlink_remote_as,
                                    "remote_as_4_byte_step": 0,
                                    "gateway_starting_ip": uplink_portchannel_bgp_v6_starting_ip,
                                    "gateway_increment_ip": "0:0:0:0::2",
                                },
                                {
                                    "starting_ip": uplink_portchannel_bgp_v4_gateway_ip,
                                    "increment_ip": "0.0.0.2",
                                    "prefix_length": 31,
                                    "description": "Downlink-uplink portchannel IPv4 BGP sessions",
                                    "peer_group_name": downlink_portchannel_peergroup_v4,
                                    "num_sessions": portchannel_session_count,
                                    "remote_as_4_byte": downlink_remote_as,
                                    "remote_as_4_byte_step": 0,
                                    "gateway_starting_ip": uplink_portchannel_bgp_v4_starting_ip,
                                    "gateway_increment_ip": "0.0.0.2",
                                },
                            ]
                        }
                        if portchannel_session_count
                        else {}
                    ),
                }
            ),
        ),
        # Spliced before the apply so callers can register their own patchers.
        *(additional_setup_tasks or []),
        create_coop_apply_patchers_task(
            hostnames=hostnames,
            do_coldboot=True,
        ),
        create_wait_for_agent_convergence_task(hostnames),
        create_wait_for_bgp_convergence_task(
            hostnames=hostnames,
        ),
    ]

    def _port_config(
        device: str,
        port: IxiaPortSpec,
        ixia_as: int,
        communities: list[str],
        with_stressors: bool,
    ) -> BasicPortConfig:
        groups = [
            DeviceGroupConfig(
                device_group_index=0,
                tag_name="NO_V6_PACKET_LOSS_EXPECTED",
                multiplier=port.v6_session_count,
                v6_addresses_config=IpAddressesConfig(
                    starting_ip=port.bgp_v6_gateway_ip,
                    increment_ip="0:0:0:0::2",
                    gateway_starting_ip=port.bgp_v6_starting_ip,
                    gateway_increment_ip="0:0:0:0::2",
                    mask=127,
                ),
                v6_bgp_config=BgpConfig(
                    local_as_4_bytes=ixia_as,
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
                                prefix_count=port.v6_prefix_count,
                                starting_prefixes=port.v6_starting_prefixes,
                                prefix_step="0:0:0:0::0",
                                prefix_length=48,
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                bgp_communities=communities,
                            ),
                        ),
                    ],
                ),
            ),
            DeviceGroupConfig(
                device_group_index=1,
                tag_name="NO_V4_PACKET_LOSS_EXPECTED",
                multiplier=port.v4_session_count,
                v4_addresses_config=IpAddressesConfig(
                    starting_ip=port.bgp_v4_gateway_ip,
                    increment_ip="0.0.0.2",
                    gateway_starting_ip=port.bgp_v4_starting_ip,
                    gateway_increment_ip="0.0.0.2",
                    mask=31,
                ),
                v4_bgp_config=BgpConfig(
                    local_as_4_bytes=ixia_as,
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
                                prefix_count=port.v4_prefix_count,
                                starting_prefixes=port.v4_starting_prefixes,
                                prefix_step="0.0.0.0",
                                prefix_length=24,
                                ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                bgp_communities=communities,
                            ),
                        ),
                    ],
                ),
            ),
        ]
        if with_stressors:
            groups.extend(
                [
                    DeviceGroupConfig(
                        device_group_index=2,
                        tag_name="NDP_STRESSOR",
                        multiplier=ndp_stressor_multiplier,
                        v6_addresses_config=IpAddressesConfig(
                            starting_ip=uplink_ndp_gateway_ip,
                            increment_ip="0:0:0:0::1",
                            gateway_starting_ip=uplink_ndp_starting_ip,
                            mask=80,
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_index=3,
                        tag_name="ARP_STRESSOR",
                        multiplier=arp_stressor_multiplier,
                        v4_addresses_config=IpAddressesConfig(
                            starting_ip=uplink_arp_gateway_ip,
                            increment_ip="0.0.0.1",
                            gateway_starting_ip=uplink_arp_starting_ip,
                            gateway_increment_ip="0.0.0.0",
                            mask=16,
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_index=4,
                        tag_name="BGP_PREFIX_FLAP",
                        multiplier=prefix_flap_session_count,
                        v6_addresses_config=IpAddressesConfig(
                            starting_ip=uplink_prefix_flap_gateway_ip,
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=uplink_prefix_flap_starting_ip,
                            gateway_increment_ip="0:0:0:0::2",
                            mask=127,
                        ),
                        v6_bgp_config=BgpConfig(
                            local_as_4_bytes=ixia_as,
                            local_as_increment=1,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            route_scales=[
                                RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=RouteScale(
                                        multiplier=1,
                                        prefix_count=uplink_prefix_flap_prefix_count,
                                        starting_prefixes=uplink_prefix_flap_starting_prefixes,
                                        prefix_step="0:0:0:0::0",
                                        prefix_length=48,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                        bgp_communities=communities,
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
                            starting_ip=uplink_session_flap_gateway_ip,
                            increment_ip="0.0.0.2",
                            gateway_starting_ip=uplink_session_flap_starting_ip,
                            gateway_increment_ip="0.0.0.2",
                            mask=31,
                        ),
                        v4_bgp_config=BgpConfig(
                            local_as_4_bytes=ixia_as,
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
                                        prefix_count=uplink_session_flap_prefix_count,
                                        starting_prefixes=uplink_session_flap_starting_prefixes,
                                        prefix_step="0.0.0.0",
                                        prefix_length=24,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                        bgp_communities=communities,
                                    ),
                                ),
                            ],
                        ),
                    ),
                ]
            )
        return BasicPortConfig(
            endpoint=_endpoint(device, port), device_group_configs=groups
        )

    basic_port_configs = [
        _port_config(
            uplink_device,
            port,
            uplink_ixia_as,
            uplink_bgp_communities,
            with_stressors=port is uplink_primary,
        )
        for port in uplink_ixia_ports
    ] + [
        _port_config(
            downlink_device,
            port,
            downlink_ixia_as,
            downlink_bgp_communities,
            with_stressors=False,
        )
        for port in downlink_ixia_ports
    ]

    # One traffic item per port pair per AF, so packet loss is attributable to a
    # specific IXIA port rather than pooled across all of them.
    traffic_pairs = list(zip(downlink_ixia_ports, uplink_ixia_ports))
    basic_traffic_item_configs = []
    traffic_item_names = []
    for index, (src_port, dest_port) in enumerate(traffic_pairs):
        for device_group_index, (label, traffic_type) in enumerate(
            (
                ("V6", ixia_types.TrafficType.IPV6),
                ("V4", ixia_types.TrafficType.IPV4),
            )
        ):
            name = f"{label}_TRAFFIC_DOWNLINK_TO_UPLINK_{index}"
            traffic_item_names.append(name)
            basic_traffic_item_configs.append(
                BasicTrafficItemConfig(
                    name=name,
                    src_endpoints=[
                        TrafficEndpoint(
                            name=_endpoint(downlink_device, src_port),
                            device_group_index=device_group_index,
                            network_group_index=0,
                        ),
                    ],
                    dest_endpoints=[
                        TrafficEndpoint(
                            name=_endpoint(uplink_device, dest_port),
                            device_group_index=device_group_index,
                            network_group_index=0,
                        ),
                    ],
                    line_rate=traffic_line_rate,
                    traffic_type=traffic_type,
                    merge_destinations=False,
                    bidirectional=False,
                    src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
                )
            )

    playbooks_ = create_all_lag_playbooks(
        dut_name=uplink_device,
        remote_name=downlink_device,
        dut_port_channel_name=uplink_portchannel_name,
        remote_port_channel_name=downlink_portchannel_name,
        dut_member_interfaces=uplink_portchannel_links,
        remote_member_interfaces=downlink_portchannel_links,
        min_link_percentage=min_link_percentage,
        min_link_up_percentage=min_link_up_percentage,
        dut_mistmatch_min_link_percentage=uplink_mismatch_min_link,
        dut_mistmatch_min_link_up_percentage=uplink_mismatch_min_link_up,
        remote_mistmatch_min_link_percentage=downlink_mismatch_min_link,
        remote_mistmatch_min_link_up_percentage=downlink_mismatch_min_link_up,
        iteration_override=lag_iteration_override,
        longevity_duration=lag_longevity_duration,
        bgp_parent_prefixes_to_ignore=bgp_parent_prefixes_to_ignore,
        services_to_skip=services_to_skip,
        link_up_wait_s=link_up_wait_s,
    )

    return TestConfig(
        name=test_config_name,
        skip_ixia_protocol_verification=True,
        basset_pool=basset_pool,
        endpoints=[
            Endpoint(
                name=uplink_device,
                ixia_ports=[port.interface for port in uplink_ixia_ports],
                dut=True,
                direct_ixia_connections=_direct_connections(uplink_ixia_ports),
            ),
            Endpoint(
                name=downlink_device,
                ixia_ports=[port.interface for port in downlink_ixia_ports],
                dut=False,
                direct_ixia_connections=_direct_connections(downlink_ixia_ports),
            ),
        ],
        setup_tasks=setup_tasks,
        teardown_tasks=[
            create_coop_unregister_patchers_task(hostnames),
        ],
        basic_port_configs=basic_port_configs,
        basic_traffic_item_configs=basic_traffic_item_configs,
        traffic_items_to_start=traffic_item_names,
        playbooks=playbooks_,
    )


KODIAK3_CI_CD_LAG_TEST_CONFIG = test_config_for_portchannel(
    test_config_name="KODIAK3_CI_CD_LAG_TEST_CONFIG",
    ixia_chassis_ip="2401:db00:2066:3036::3001",
    # Uplink device - topology
    uplink_device="fa003-uu001.qza1",
    uplink_role="FAUU",
    uplink_ixia_ports=[
        IxiaPortSpec(
            interface="eth1/64/5",
            chassis_port="1/1",
            v6_session_count=8,
            v4_session_count=8,
            bgp_v6_starting_ip="2401:db00:e50d:11:8::0",
            bgp_v6_gateway_ip="2401:db00:e50d:11:8::1",
            bgp_v4_starting_ip="192.168.0.0",
            bgp_v4_gateway_ip="192.168.0.1",
            v6_prefix_count=25000,
            v6_starting_prefixes="5401:db00:1000::",
            v4_prefix_count=25000,
            v4_starting_prefixes="10.1.0.0",
        )
    ],
    # Downlink device - topology
    downlink_device="fa003-du004.qza1",
    downlink_role="FADU",
    downlink_ixia_ports=[
        IxiaPortSpec(
            interface="eth1/64/5",
            chassis_port="1/2",
            v6_session_count=48,
            v4_session_count=48,
            bgp_v6_starting_ip="2401:eb00:e50d:11:8::0",
            bgp_v6_gateway_ip="2401:eb00:e50d:11:8::1",
            bgp_v4_starting_ip="192.168.3.0",
            bgp_v4_gateway_ip="192.168.3.1",
            v6_prefix_count=5000,
            v6_starting_prefixes="7401:db00:1001::",
            v4_prefix_count=5000,
            v4_starting_prefixes="20.1.0.0",
        )
    ],
    # Portchannel config (uplink-downlink direct BGP peering)
    uplink_portchannel_name="Port-Channel304",
    downlink_portchannel_name="Port-Channel301",
    # Portchannel links
    # 1-1 mapping: downlink_portchannel_links[i] connects to uplink_portchannel_links[i]
    uplink_portchannel_links=["eth1/13/1", "eth1/14/1", "eth1/15/1", "eth1/16/1"],
    downlink_portchannel_links=["eth1/49/1", "eth1/53/1", "eth1/57/1", "eth1/61/1"],
    # Portchannel minlink config
    min_link_percentage=0.5,
    min_link_up_percentage=0.75,
    # Mismatch minlink config
    uplink_mismatch_min_link=0.25,
    uplink_mismatch_min_link_up=0.8,
    downlink_mismatch_min_link=0.5,
    downlink_mismatch_min_link_up=0.75,
    # IXIA ASN config
    uplink_ixia_as=64734,
    downlink_ixia_as=64901,
    # Uplink BGP config
    uplink_remote_as=7004,
    uplink_portchannel_ingress_policy="PROPAGATE_FAUU_FADU_IN",
    uplink_portchannel_egress_policy="PROPAGATE_FAUU_FADU_OUT",
    uplink_portchannel_peer_tag="DU",
    # Uplink stressor IP config
    uplink_ndp_starting_ip="2401:db00:e50d:11:9::0",
    uplink_ndp_gateway_ip="2401:db00:e50d:11:9::1",
    uplink_arp_starting_ip="192.168.1.0",
    uplink_arp_gateway_ip="192.168.1.1",
    # Uplink BGP flap IP config
    uplink_prefix_flap_starting_ip="2401:db00:e50d:11:a::0",
    uplink_prefix_flap_gateway_ip="2401:db00:e50d:11:a::1",
    uplink_session_flap_starting_ip="192.168.2.0",
    uplink_session_flap_gateway_ip="192.168.2.1",
    # Uplink route scale
    uplink_bgp_communities=["65526:35724"],
    uplink_prefix_flap_prefix_count=10000,
    uplink_prefix_flap_starting_prefixes="5401:db00:2000::",
    uplink_session_flap_prefix_count=10000,
    uplink_session_flap_starting_prefixes="10.2.0.0",
    # BGP_SESSION_FLAP peers are cycled 120s up / 15s down on purpose, so a
    # postcheck landing in a down window sees them IDLE and fails the session
    # count. Observed on the FAN<>FAN pair as an intermittent precheck failure.
    bgp_parent_prefixes_to_ignore=["192.168.2.0/24"],
    # Downlink BGP config
    downlink_remote_as=8001,
    downlink_portchannel_ingress_policy="PROPAGATE_FADU_FAUU_IN",
    downlink_portchannel_egress_policy="PROPAGATE_FADU_FAUU_OUT",
    downlink_portchannel_peer_tag="UU",
    downlink_bgp_communities=[
        "65441:132",
        "65442:133",
        "65529:26730",
    ],
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
    uplink_portchannel_bgp_v6_starting_ip="2401:db00:e50d:11:f::0",
    uplink_portchannel_bgp_v6_gateway_ip="2401:db00:e50d:11:f::1",
    uplink_portchannel_bgp_v4_starting_ip="192.168.10.0",
    uplink_portchannel_bgp_v4_gateway_ip="192.168.10.1",
    uplink_portchannel_peergroup_v6="PEERGROUP_FAUU_FADU_V6",
    uplink_portchannel_peergroup_v4="PEERGROUP_FAUU_FADU_V4",
    downlink_portchannel_peergroup_v6="PEERGROUP_FADU_FAUU_V6",
    downlink_portchannel_peergroup_v4="PEERGROUP_FADU_FAUU_V4",
    # Traffic parameters
    traffic_line_rate=48,
    # Optional overrides
    basset_pool="dne.test",
)


# Members are name-identical and cabled 1:1 on both ends (verified via LLDP).
_FAN_FAN_PORTCHANNEL_LINKS: list[str] = [
    f"eth1/{port}/1"
    for port in (
        1,
        4,
        5,
        8,
        9,
        12,
        13,
        16,
        17,
        20,
        21,
        24,
        25,
        28,
        29,
        32,
        33,
        36,
        37,
        40,
        41,
        44,
        45,
        48,
        49,
        52,
        53,
        56,
        57,
        60,
        61,
        64,
    )
]

FAN_FAN_LAG_TEST_CONFIG = test_config_for_portchannel(
    test_config_name="FAN_FAN_LAG_TEST_CONFIG",
    ixia_chassis_ip="2401:db00:2076:30fd:0000:0000:0000:3001",
    # Uplink device - topology (FAN_FAN Z endpoint / spoke).
    # D81712701 sizes an FX device for 128 peers at max scale (1 dctype1 x 8 FADU
    # + 10 dctypef x 12 XSW); that ceiling excludes FX<>BC and FX<>FX, so the two
    # IXIA ports split 128 between them and the LAG keeps its own session on top.
    # Uplink reserves 20 of its 128 for the prefix/session flap groups below.
    uplink_device="fx001.b001.p001.s001.qzq1",
    uplink_role="FX",
    uplink_ixia_ports=[
        IxiaPortSpec(
            interface="eth1/62/1",
            chassis_port="1/13",
            v6_session_count=27,
            v4_session_count=27,
            bgp_v6_starting_ip="2401:db00:e50d:11:8::0",
            bgp_v6_gateway_ip="2401:db00:e50d:11:8::1",
            bgp_v4_starting_ip="192.168.0.0",
            bgp_v4_gateway_ip="192.168.0.1",
            v6_prefix_count=140,
            v6_starting_prefixes="5401:db00::",
            v4_prefix_count=140,
            v4_starting_prefixes="10.0.0.0",
        ),
        IxiaPortSpec(
            interface="eth1/62/5",
            chassis_port="1/14",
            v6_session_count=27,
            v4_session_count=27,
            bgp_v6_starting_ip="2401:db00:e50d:11:b::0",
            bgp_v6_gateway_ip="2401:db00:e50d:11:b::1",
            bgp_v4_starting_ip="192.168.4.0",
            bgp_v4_gateway_ip="192.168.4.1",
            v6_prefix_count=140,
            v6_starting_prefixes="5401:db01::",
            v4_prefix_count=140,
            v4_starting_prefixes="10.128.0.0",
        ),
    ],
    # Downlink device - topology (FAN_FAN A endpoint / hub)
    downlink_device="fx001.b001.p001.s001.qzu1",
    downlink_role="FX",
    downlink_ixia_ports=[
        IxiaPortSpec(
            interface="eth1/62/1",
            chassis_port="1/15",
            v6_session_count=32,
            v4_session_count=32,
            bgp_v6_starting_ip="2401:eb00:e50d:11:8::0",
            bgp_v6_gateway_ip="2401:eb00:e50d:11:8::1",
            bgp_v4_starting_ip="192.168.3.0",
            bgp_v4_gateway_ip="192.168.3.1",
            v6_prefix_count=140,
            v6_starting_prefixes="7401:db00:1001::",
            v4_prefix_count=140,
            v4_starting_prefixes="30.0.0.0",
        ),
        IxiaPortSpec(
            interface="eth1/62/5",
            chassis_port="1/16",
            v6_session_count=32,
            v4_session_count=32,
            bgp_v6_starting_ip="2401:eb00:e50d:11:b::0",
            bgp_v6_gateway_ip="2401:eb00:e50d:11:b::1",
            bgp_v4_starting_ip="192.168.6.0",
            bgp_v4_gateway_ip="192.168.6.1",
            v6_prefix_count=140,
            v6_starting_prefixes="7401:db00:2001::",
            v4_prefix_count=140,
            v4_starting_prefixes="30.128.0.0",
        ),
    ],
    # Portchannel config
    uplink_portchannel_name="Port-Channel4008",
    downlink_portchannel_name="Port-Channel4008",
    uplink_portchannel_links=_FAN_FAN_PORTCHANNEL_LINKS,
    downlink_portchannel_links=_FAN_FAN_PORTCHANNEL_LINKS,
    # Portchannel minlink config: ceil(32 * 0.65) = 21 to stay up,
    # ceil(32 * 0.75) = 24 to come back up.
    min_link_percentage=0.65,
    min_link_up_percentage=0.75,
    # Mismatch minlink config: wide hysteresis on the DUT, baseline on the peer.
    uplink_mismatch_min_link=0.40,
    uplink_mismatch_min_link_up=0.80,
    downlink_mismatch_min_link=0.65,
    downlink_mismatch_min_link_up=0.75,
    # IXIA ASN config
    uplink_ixia_as=64734,
    downlink_ixia_as=64901,
    # FAN<>FAN peering. The IXIA side is left on the factory defaults
    # (PEERGROUP_FX_IXIA_V6/V4 + PROPAGATE_EVERYTHING), so only the production
    # port-channel peer groups and policies need naming here.
    uplink_remote_as=4210264999,
    downlink_remote_as=4210263999,
    uplink_portchannel_ingress_policy="PROPAGATE_FX_FX_IN",
    uplink_portchannel_egress_policy="PROPAGATE_FX_FX_OUT",
    downlink_portchannel_ingress_policy="PROPAGATE_FX_FX_IN",
    downlink_portchannel_egress_policy="PROPAGATE_FX_FX_OUT",
    uplink_portchannel_peergroup_v6="PEERGROUP_FX_FX_Z_ENDPOINT_V6",
    downlink_portchannel_peergroup_v6="PEERGROUP_FX_FX_A_ENDPOINT_V6",
    uplink_portchannel_peer_tag="FX",
    downlink_portchannel_peer_tag="FX",
    # The LAG already carries the device's production FAN<>FAN session, which is
    # the session under test. 0 leaves it alone rather than putting a second
    # set of peers on member port eth1/1/1.
    portchannel_session_count=0,
    prefix_flap_session_count=10,
    session_flap_session_count=10,
    # PEERGROUP_FX_FX_* pre-filters at 20000 routes, so each side advertises
    # under that: uplink 108*140 + 20*200 = 19120, downlink 128*140 = 17920.
    uplink_prefix_flap_prefix_count=200,
    uplink_session_flap_prefix_count=200,
    # FR-HOP6. The only policy that still evaluates these is PROPAGATE_FX_FX_*,
    # whose RULE_COMMUNITY_FILTER_PREF_FX_FR_HOP6_PREF_MATCH_400 admits 65441:11142.
    uplink_bgp_communities=["65441:11142"],
    downlink_bgp_communities=["65441:11142"],
    # Scale parameters as shipped on both boxes; not raised for the test.
    prefix_limit=70000,
    max_routes=20000,
    # Shortened first-pass run: every playbook at 5 iterations and a 10 minute
    # longevity rather than the stock 10-25 iterations and 1 hour.
    lag_iteration_override=5,
    lag_longevity_duration=600,
    # The two production BGP_MONITOR listen-ranges on these FX boxes are prefix
    # entries, not peers, so they sit in IDLE forever and would fail the
    # session-established check against the 129 real sessions.
    bgp_parent_prefixes_to_ignore=[
        "10.127.240.0/23",
        "2401:db00:1ff:c100::/56",
        # BGP_SESSION_FLAP peers, cycled 120s up / 15s down by IXIA on purpose.
        # Any postcheck landing inside a down window sees them IDLE and fails
        # the session count, so they are excluded rather than raced against.
        "192.168.2.0/24",
    ],
    # FX boxes do not run Open/R at all, so the stock service list reports it
    # as restarted on every playbook.
    services_to_skip=["openr"],
    # These links run coherent ZR optics, which take 120-180s to acquire lock
    # after an admin enable. The stock 10s wait fails a link that is still
    # coming up rather than one that is broken.
    link_up_wait_s=300,
    # Traffic parameters
    traffic_line_rate=48,
    # Optional overrides
    basset_pool="dne.test",
    # The FX router-id rule derives the BGP identifier from bytes [4:8] of the
    # device loopback, which for the 2401:db00:ea3c::/48 prefix yields
    # 234.60.16.0 -- inside 224.0.0.0/4. IXIA rejects that with OPEN error
    # "Bad BGP Identifier" (code 2 subcode 3) and every session bounces out of
    # OPEN_CONFIRM. bgpcpp does not enforce it, which is why the production
    # FX<>FX session is unaffected. Pin a valid unicast identifier per device.
    additional_setup_tasks=[
        create_coop_register_patcher_task(
            hostname="fx001.b001.p001.s001.qzq1",
            config_name="bgpcpp",
            patcher_name="00_set_bgp_router_id",
            task_name="coop_register_patcher",
            patcher_args={"router_id": "180.1.1.1"},
            py_func_name="bgp_feature_canary",
        ),
        create_coop_register_patcher_task(
            hostname="fx001.b001.p001.s001.qzu1",
            config_name="bgpcpp",
            patcher_name="00_set_bgp_router_id",
            task_name="coop_register_patcher",
            patcher_args={"router_id": "180.1.1.2"},
            py_func_name="bgp_feature_canary",
        ),
    ],
)


PORTCHANNEL_TEST_CONFIGS = [KODIAK3_CI_CD_LAG_TEST_CONFIG, FAN_FAN_LAG_TEST_CONFIG]
