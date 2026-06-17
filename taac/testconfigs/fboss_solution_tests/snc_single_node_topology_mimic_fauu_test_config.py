# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""SNC_SINGLE_NODE_TOPOLOGY_MIMIC_FAUU TestConfig.

Single-node BGP++ scale longevity TestConfig that mimics the FAUU multi-
node topology on ssw002.s001.f02.snc1. Builds a multi-port IXIA setup,
applies COOP patchers + parallel BGP peer config, and exercises full
warmboot/coldboot/FSDB/QSPF/BGPD restart playbooks plus longevity stages.
Has skip_advertised_prefixes_check=True (vs. the QZD variant).
"""

import json

from ixia.ixia import types as ixia_types
from taac.constants import Gigabyte
from taac.health_checks.healthcheck_definitions import (
    create_bgp_convergence_check,
    create_bgp_rib_fib_consistency_check,
    create_bgp_session_snapshot_check,
    create_ixia_packet_loss_check,
    create_memory_utilization_check,
    create_next_hop_count_snapshot_check,
    create_prefix_limit_check,
    create_unclean_exit_check,
)
from taac.packet_headers import BGP_CP_TRAFFIC_PACKET_HEADERS
from taac.playbooks.playbook_definitions import (
    build_snc_playbook,
    rebuild_snc_playbook_with_checks,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_ixia_api_step,
    create_longevity_step,
    create_service_convergence_step,
    create_service_interruption_step,
)
from taac.task_definitions import (
    create_configure_parallel_bgp_peers_task,
    create_coop_apply_patchers_task,
    create_coop_register_patcher_task,
    create_coop_unregister_patchers_task,
    create_wait_for_agent_convergence_task,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import Service, ServiceInterruptionTrigger, TestConfig


def _add_checks_to_playbooks(
    playbooks,
    prechecks=None,
    postchecks=None,
    snapshot_checks=None,
):
    """Add common checks to each playbook, merging with any existing checks."""
    return [
        rebuild_snc_playbook_with_checks(
            pb,
            prechecks=prechecks,
            postchecks=postchecks,
            snapshot_checks=snapshot_checks,
        )
        for pb in playbooks
    ]


SNC_SINGLE_NODE_TOPOLOGY_MIMIC_FAUU_TEST_CONFIG = TestConfig(
    name="SNC_SINGLE_NODE_TOPOLOGY_MIMIC_FAUU",
    basset_pool="dne.test",
    skip_advertised_prefixes_check=True,
    endpoints=[
        taac_types.Endpoint(
            name="ssw002.s001.f02.snc1",
            ixia_ports=["eth9/1/1", "eth9/2/1", "eth9/16/1"],
            dut=True,
            mac_address="b6:a9:fc:34:31:20",
        ),
    ],
    setup_tasks=[
        create_coop_unregister_patchers_task(
            hostnames=["ssw002.s001.f02.snc1"],
        ),
        # Remove all the bgp peers present in the device first
        create_coop_register_patcher_task(
            hostname="ssw002.s001.f02.snc1",
            config_name="bgpcpp",
            patcher_name="a_remove_bgp_peers",
            task_name="remove_bgp_peers",
            patcher_args={"delete_all": "True"},
            py_func_name="remove_bgp_peers",
        ),
        create_coop_register_patcher_task(
            hostname="ssw002.s001.f02.snc1",
            config_name="bgpcpp",
            patcher_name="configure_bgp_switch_limit",
            task_name="configure_bgp_switch_limit",
            patcher_args={
                "prefix_limit": "42000",
            },
            py_func_name="configure_bgp_switch_limit",
        ),
        create_coop_register_patcher_task(
            hostname="ssw002.s001.f02.snc1",
            config_name="bgpcpp",
            patcher_name="update_peer_group_patcher_SSW_FSW_V6_Downlink",
            task_name="configure_bgp_peer_group",
            patcher_args={
                "name": "PEERGROUP_SSW_FSW_V6",
                "attributes_to_update_json": json.dumps(
                    {
                        "disable_ipv4_afi": "True",
                        "v4_over_v6_nexthop": "False",
                        "is_passive": "False",
                    }
                ),
            },
            py_func_name="configure_bgp_peer_group",
        ),
        create_coop_register_patcher_task(
            hostname="ssw002.s001.f02.snc1",
            config_name="bgpcpp",
            patcher_name="update_peer_group_patcher_SSW_FADU_V6_Uplink",
            task_name="configure_bgp_peer_group",
            patcher_args={
                "name": "PEERGROUP_SSW_FADU_V6",
                "attributes_to_update_json": json.dumps(
                    {
                        "disable_ipv4_afi": "True",
                        "v4_over_v6_nexthop": "False",
                        "is_passive": "False",
                    }
                ),
            },
            py_func_name="configure_bgp_peer_group",
        ),
        create_coop_register_patcher_task(
            hostname="ssw002.s001.f02.snc1",
            config_name="bgpcpp",
            patcher_name="add_peer_group_patcher_SSW_FADU_V4",
            task_name="add_peer_group_patcher",
            patcher_args={
                "name": "PEERGROUP_SSW_FADU_V4",
                "description": "BGP peering from SSW to FADU, IPv4 sessions",
                "next_hop_self": "True",
                "disable_ipv4_afi": "False",
                "disable_ipv6_afi": "True",
                "is_confed_peer": "False",
                "ingress_policy_name": "PROPAGATE_SSW_FADU_IN",
                "egress_policy_name": "PROPAGATE_SSW_FADU_OUT",
                "bgp_peer_timers_hold_time_seconds": "30",
                "bgp_peer_timers_keep_alive_seconds": "10",
                "bgp_peer_timers_out_delay_seconds": "7",
                "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                "peer_tag": "FADU",
                "max_routes": "45000",
                "warning_only": "True",
                "warning_limit": "0",
                "link_bandwidth_bps": "auto",
                "v4_over_v6_nexthop": "False",
                "is_passive": "False",
            },
            py_func_name="add_peer_group_patcher",
        ),
        create_coop_register_patcher_task(
            hostname="ssw002.s001.f02.snc1",
            config_name="bgpcpp",
            patcher_name="add_peer_group_patcher_SSW_FSW_V4",
            task_name="add_peer_group_patcher",
            patcher_args={
                "name": "PEERGROUP_SSW_FSW_V4",
                "description": "BGP peering from RSW to FSW, IPv4 sessions",
                "next_hop_self": "True",
                "disable_ipv4_afi": "False",
                "disable_ipv6_afi": "True",
                "is_confed_peer": "True",
                "ingress_policy_name": "PROPAGATE_SSW_FSW_IN",
                "egress_policy_name": "PROPAGATE_SSW_FSW_OUT",
                "bgp_peer_timers_hold_time_seconds": "30",
                "bgp_peer_timers_keep_alive_seconds": "10",
                "bgp_peer_timers_out_delay_seconds": "7",
                "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                "peer_tag": "RSW",
                "max_routes": "45000",
                "warning_only": "True",
                "warning_limit": "0",
                "link_bandwidth_bps": "auto",
                "v4_over_v6_nexthop": "False",
                "is_passive": "False",
            },
            py_func_name="add_peer_group_patcher",
        ),
        create_coop_apply_patchers_task(
            hostnames=["ssw002.s001.f02.snc1"],
        ),
        create_configure_parallel_bgp_peers_task(
            hostname="ssw002.s001.f02.snc1",
            configure_vlans_patcher_name="configure_vlans_patcher_name_downlink",
            add_bgp_peers_patcher_name="add_bgp_peers_patcher_name_downlink",
            config_json=json.dumps(
                {
                    "eth9/1/1": [
                        {
                            "starting_ip": "2401:db00:e50d:1202:8::10",
                            "increment_ip": "0:0:0:0::2",
                            "prefix_length": 127,
                            "description": "Downlink IPv6 Peers",
                            "peer_group_name": "PEERGROUP_SSW_FSW_V6",
                            "num_sessions": 36,
                            "remote_as_4_byte": 65406,
                            "remote_as_4_byte_step": 1,
                            "gateway_starting_ip": "2401:db00:e50d:1202:8::11",
                            "gateway_increment_ip": "0:0:0:0::2",
                        },
                        {
                            "starting_ip": "10.163.28.0",
                            "increment_ip": "0.0.0.2",
                            "prefix_length": 31,
                            "description": "Downlink IPv4 Peers",
                            "peer_group_name": "PEERGROUP_SSW_FSW_V4",
                            "num_sessions": 36,
                            "remote_as_4_byte": 65406,
                            "remote_as_4_byte_step": 1,
                            "gateway_starting_ip": "10.163.28.1",
                            "gateway_increment_ip": "0.0.0.2",
                        },
                    ]
                }
            ),
        ),
        create_wait_for_agent_convergence_task(
            hostnames=["ssw002.s001.f02.snc1"],
        ),
        create_configure_parallel_bgp_peers_task(
            hostname="ssw002.s001.f02.snc1",
            configure_vlans_patcher_name="configure_vlans_patcher_name_uplink",
            add_bgp_peers_patcher_name="add_bgp_peers_patcher_name_uplink",
            config_json=json.dumps(
                {
                    "eth9/2/1": [
                        {
                            "starting_ip": "2401:db00:e50d:1202:9::10",
                            "increment_ip": "0:0:0:0::2",
                            "prefix_length": 127,
                            "description": "Uplink IPv6 Peers",
                            "peer_group_name": "PEERGROUP_SSW_FADU_V6",
                            "num_sessions": 8,
                            "remote_as_4_byte": 64574,
                            "remote_as_4_byte_step": 1,
                            "gateway_starting_ip": "2401:db00:e50d:1202:9::11",
                            "gateway_increment_ip": "0:0:0:0::2",
                        },
                        {
                            "starting_ip": "10.164.28.0",
                            "increment_ip": "0.0.0.2",
                            "prefix_length": 31,
                            "description": "Uplink IPv4 Peers",
                            "peer_group_name": "PEERGROUP_SSW_FADU_V4",
                            "num_sessions": 8,
                            "remote_as_4_byte": 64574,
                            "remote_as_4_byte_step": 1,
                            "gateway_starting_ip": "10.164.28.1",
                            "gateway_increment_ip": "0.0.0.2",
                        },
                    ],
                    "eth9/16/1": [
                        {
                            "starting_ip": "2401:db00:e50d:1202:11::10",
                            "increment_ip": "0:0:0:0::2",
                            "prefix_length": 127,
                            "description": "Uplink IPv6 Peers",
                            "peer_group_name": "PEERGROUP_SSW_FADU_V6",
                            "num_sessions": 8,
                            "remote_as_4_byte": 64574,
                            "remote_as_4_byte_step": 1,
                            "gateway_starting_ip": "2401:db00:e50d:1202:11::11",
                            "gateway_increment_ip": "0:0:0:0::2",
                        },
                        {
                            "starting_ip": "10.165.28.0",
                            "increment_ip": "0.0.0.2",
                            "prefix_length": 31,
                            "description": "Uplink IPv4 Peers",
                            "peer_group_name": "PEERGROUP_SSW_FADU_V4",
                            "num_sessions": 8,
                            "remote_as_4_byte": 64574,
                            "remote_as_4_byte_step": 1,
                            "gateway_starting_ip": "10.165.28.1",
                            "gateway_increment_ip": "0.0.0.2",
                        },
                    ],
                }
            ),
        ),
        create_coop_apply_patchers_task(
            hostnames=["ssw002.s001.f02.snc1"],
            do_warmboot=True,
        ),
        create_coop_apply_patchers_task(
            hostnames=["ssw002.s001.f02.snc1"],
            do_warmboot=True,
        ),
    ],
    teardown_tasks=[
        create_coop_unregister_patchers_task(
            hostnames="ssw002.s001.f02.snc1",
        ),
    ],
    basic_port_configs=[
        taac_types.BasicPortConfig(
            endpoint="ssw002.s001.f02.snc1:eth9/1/1",
            device_group_configs=[
                taac_types.DeviceGroupConfig(
                    device_group_index=0,
                    multiplier=36,
                    v6_addresses_config=taac_types.IpAddressesConfig(
                        starting_ip="2401:db00:e50d:1202:8::11",
                        increment_ip="0:0:0:0::2",
                        gateway_starting_ip="2401:db00:e50d:1202:8::10",
                        gateway_increment_ip="0:0:0:0::2",
                    ),
                    v6_bgp_config=taac_types.BgpConfig(
                        local_as_4_bytes=65406,
                        local_as_increment=1,
                        enable_4_byte_local_as=True,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        route_scales=[
                            taac_types.RouteScaleSpec(
                                network_group_index=0,
                                v6_route_scale=taac_types.RouteScale(
                                    multiplier=1,
                                    prefix_count=3388,
                                    prefix_length=64,
                                    starting_prefixes="3000:1::",
                                    prefix_step="0:0:0:0::0",
                                    bgp_communities=["65520:424", "65520:837"],
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    as_path_prepend_numbers=[
                                        [
                                            5000,
                                            5001,
                                            5002,
                                            5003,
                                            5004,
                                            5006,
                                            5007,
                                            5008,
                                        ]
                                    ],
                                ),
                            ),
                            # Adding rogue routes
                            taac_types.RouteScaleSpec(
                                network_group_index=1,
                                v6_route_scale=taac_types.RouteScale(
                                    multiplier=1,
                                    prefix_count=1500,
                                    prefix_length=64,
                                    starting_prefixes="3000:2::",
                                    prefix_step="0:0:0:0::0",
                                    bgp_communities=["65520:424", "65520:837"],
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    as_path_prepend_numbers=[
                                        [
                                            5000,
                                            5001,
                                            5002,
                                            5003,
                                            5004,
                                            5006,
                                            5007,
                                            5008,
                                        ]
                                    ],
                                ),
                            ),
                        ],
                    ),
                ),
                taac_types.DeviceGroupConfig(
                    device_group_index=1,
                    multiplier=36,
                    v4_addresses_config=taac_types.IpAddressesConfig(
                        starting_ip="10.163.28.1",
                        increment_ip="0.0.0.2",
                        gateway_starting_ip="10.163.28.0",
                        gateway_increment_ip="0.0.0.2",
                        mask=31,
                    ),
                    v4_bgp_config=taac_types.BgpConfig(
                        local_as_4_bytes=65406,
                        local_as_increment=1,
                        enable_4_byte_local_as=True,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                        route_scales=[
                            taac_types.RouteScaleSpec(
                                network_group_index=0,
                                v4_route_scale=taac_types.RouteScale(
                                    multiplier=1,
                                    prefix_count=1637,
                                    prefix_length=24,
                                    starting_prefixes="101.1.0.0",
                                    prefix_step="0.0.0.0",
                                    bgp_communities=["65520:424", "65520:837"],
                                    ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                    as_path_prepend_numbers=[
                                        [
                                            5000,
                                            5001,
                                            5002,
                                            5003,
                                            5004,
                                            5006,
                                            5007,
                                            5008,
                                        ]
                                    ],
                                ),
                            ),
                            # Adding rogue routes
                            taac_types.RouteScaleSpec(
                                network_group_index=1,
                                v4_route_scale=taac_types.RouteScale(
                                    multiplier=1,
                                    prefix_count=1500,
                                    prefix_length=24,
                                    starting_prefixes="102.1.0.0",
                                    prefix_step="0.0.0.0",
                                    bgp_communities=["65520:424", "65520:837"],
                                    ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                    as_path_prepend_numbers=[
                                        [
                                            5000,
                                            5001,
                                            5002,
                                            5003,
                                            5004,
                                            5006,
                                            5007,
                                            5008,
                                        ]
                                    ],
                                ),
                            ),
                        ],
                    ),
                ),
            ],
        ),
        taac_types.BasicPortConfig(
            endpoint="ssw002.s001.f02.snc1:eth9/2/1",
            device_group_configs=[
                taac_types.DeviceGroupConfig(
                    device_group_index=0,
                    multiplier=8,
                    v6_addresses_config=taac_types.IpAddressesConfig(
                        starting_ip="2401:db00:e50d:1202:9::11",
                        increment_ip="0:0:0:0::2",
                        gateway_starting_ip="2401:db00:e50d:1202:9::10",
                        gateway_increment_ip="0:0:0:0::2",
                    ),
                    v6_bgp_config=taac_types.BgpConfig(
                        local_as_4_bytes=64574,
                        local_as_increment=1,
                        enable_4_byte_local_as=True,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        route_scales=[
                            taac_types.RouteScaleSpec(
                                network_group_index=0,
                                v6_route_scale=taac_types.RouteScale(
                                    multiplier=1,
                                    prefix_count=12200,
                                    prefix_length=64,
                                    starting_prefixes="5000:1::",
                                    prefix_step="0:0:0:0::0",
                                    bgp_communities=["65520:434", "65520:822"],
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    as_path_prepend_numbers=[
                                        [
                                            5000,
                                            5001,
                                            5002,
                                            5003,
                                            5004,
                                            5006,
                                            5007,
                                            5008,
                                        ]
                                    ],
                                ),
                            ),
                            # Adding rogue routes
                            taac_types.RouteScaleSpec(
                                network_group_index=1,
                                v6_route_scale=taac_types.RouteScale(
                                    multiplier=1,
                                    prefix_count=6000,
                                    prefix_length=64,
                                    starting_prefixes="5000:2::",
                                    prefix_step="0:0:0:0::0",
                                    bgp_communities=["65520:434", "65520:822"],
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    as_path_prepend_numbers=[
                                        [
                                            5000,
                                            5001,
                                            5002,
                                            5003,
                                            5004,
                                            5006,
                                            5007,
                                            5008,
                                        ]
                                    ],
                                ),
                            ),
                        ],
                    ),
                ),
                taac_types.DeviceGroupConfig(
                    device_group_index=1,
                    multiplier=8,
                    v4_addresses_config=taac_types.IpAddressesConfig(
                        starting_ip="10.164.28.1",
                        increment_ip="0.0.0.2",
                        gateway_starting_ip="10.164.28.0",
                        gateway_increment_ip="0.0.0.2",
                        mask=31,
                    ),
                    v4_bgp_config=taac_types.BgpConfig(
                        local_as_4_bytes=64574,
                        local_as_increment=1,
                        enable_4_byte_local_as=True,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                        route_scales=[
                            taac_types.RouteScaleSpec(
                                network_group_index=0,
                                v4_route_scale=taac_types.RouteScale(
                                    multiplier=1,
                                    prefix_count=9500,
                                    prefix_length=24,
                                    starting_prefixes="201.1.0.0",
                                    prefix_step="0.0.0.0",
                                    bgp_communities=["65520:434", "65520:822"],
                                    ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                    as_path_prepend_numbers=[
                                        [
                                            5000,
                                            5001,
                                            5002,
                                            5003,
                                            5004,
                                            5006,
                                            5007,
                                            5008,
                                        ],
                                    ],
                                ),
                            ),
                            # Adding rogue routes
                            taac_types.RouteScaleSpec(
                                network_group_index=1,
                                v4_route_scale=taac_types.RouteScale(
                                    multiplier=1,
                                    prefix_count=6000,
                                    prefix_length=24,
                                    starting_prefixes="202.1.0.0",
                                    prefix_step="0.0.0.0",
                                    bgp_communities=["65520:434", "65520:822"],
                                    ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                    as_path_prepend_numbers=[
                                        [
                                            5000,
                                            5001,
                                            5002,
                                            5003,
                                            5004,
                                            5006,
                                            5007,
                                            5008,
                                        ],
                                    ],
                                ),
                            ),
                        ],
                    ),
                ),
            ],
        ),
        taac_types.BasicPortConfig(
            endpoint="ssw002.s001.f02.snc1:eth9/16/1",
            device_group_configs=[
                taac_types.DeviceGroupConfig(
                    device_group_index=0,
                    multiplier=8,
                    v6_addresses_config=taac_types.IpAddressesConfig(
                        starting_ip="2401:db00:e50d:1202:11::11",
                        increment_ip="0:0:0:0::2",
                        gateway_starting_ip="2401:db00:e50d:1202:11::10",
                        gateway_increment_ip="0:0:0:0::2",
                    ),
                    v6_bgp_config=taac_types.BgpConfig(
                        local_as_4_bytes=64574,
                        local_as_increment=1,
                        enable_4_byte_local_as=True,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        route_scales=[
                            taac_types.RouteScaleSpec(
                                network_group_index=0,
                                v6_route_scale=taac_types.RouteScale(
                                    multiplier=1,
                                    prefix_count=12200,
                                    prefix_length=64,
                                    starting_prefixes="5000:1::",
                                    prefix_step="0:0:0:0::0",
                                    bgp_communities=["65520:434", "65520:822"],
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    as_path_prepend_numbers=[
                                        [
                                            5000,
                                            5001,
                                            5002,
                                            5003,
                                            5004,
                                            5006,
                                            5007,
                                            5008,
                                        ],
                                        [5009],
                                    ],
                                ),
                            ),
                            # Adding rogue routes
                            taac_types.RouteScaleSpec(
                                network_group_index=1,
                                v6_route_scale=taac_types.RouteScale(
                                    multiplier=1,
                                    prefix_count=6000,
                                    prefix_length=64,
                                    starting_prefixes="5000:2::",
                                    prefix_step="0:0:0:0::0",
                                    bgp_communities=["65520:434", "65520:822"],
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    as_path_prepend_numbers=[
                                        [
                                            5000,
                                            5001,
                                            5002,
                                            5003,
                                            5004,
                                            5006,
                                            5007,
                                            5008,
                                        ],
                                        [5009],
                                    ],
                                ),
                            ),
                        ],
                    ),
                ),
                taac_types.DeviceGroupConfig(
                    device_group_index=1,
                    multiplier=8,
                    v4_addresses_config=taac_types.IpAddressesConfig(
                        starting_ip="10.165.28.1",
                        increment_ip="0.0.0.2",
                        gateway_starting_ip="10.165.28.0",
                        gateway_increment_ip="0.0.0.2",
                        mask=31,
                    ),
                    v4_bgp_config=taac_types.BgpConfig(
                        local_as_4_bytes=64574,
                        local_as_increment=1,
                        enable_4_byte_local_as=True,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                        route_scales=[
                            taac_types.RouteScaleSpec(
                                network_group_index=0,
                                v4_route_scale=taac_types.RouteScale(
                                    multiplier=1,
                                    prefix_count=9500,
                                    prefix_length=24,
                                    starting_prefixes="201.1.0.0",
                                    prefix_step="0.0.0.0",
                                    bgp_communities=["65520:434", "65520:822"],
                                    ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                    as_path_prepend_numbers=[
                                        [
                                            5000,
                                            5001,
                                            5002,
                                            5003,
                                            5004,
                                            5006,
                                            5007,
                                            5008,
                                        ],
                                        [5009],
                                    ],
                                ),
                            ),
                            # Adding rogue routes
                            taac_types.RouteScaleSpec(
                                network_group_index=1,
                                v4_route_scale=taac_types.RouteScale(
                                    multiplier=1,
                                    prefix_count=6000,
                                    prefix_length=24,
                                    starting_prefixes="202.1.0.0",
                                    prefix_step="0.0.0.0",
                                    bgp_communities=["65520:434", "65520:822"],
                                    ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                    as_path_prepend_numbers=[
                                        [
                                            5000,
                                            5001,
                                            5002,
                                            5003,
                                            5004,
                                            5006,
                                            5007,
                                            5008,
                                        ],
                                        [5009],
                                    ],
                                ),
                            ),
                        ],
                    ),
                ),
            ],
        ),
    ],
    traffic_items_to_start=["(?!HIGH_QUEUE_BGP_CP_TRAFFIC)"],
    basic_traffic_item_configs=[
        taac_types.BasicTrafficItemConfig(
            src_endpoints=[
                taac_types.TrafficEndpoint(
                    name="ssw002.s001.f02.snc1:eth9/1/1",
                ),
            ],
            dest_endpoints=[
                taac_types.TrafficEndpoint(
                    name="ssw002.s001.f02.snc1:eth9/2/1",
                ),
            ],
            name="HIGH_QUEUE_BGP_CP_TRAFFIC",
            line_rate=10,
            traffic_type=ixia_types.TrafficType.RAW,
            bidirectional=False,
            packet_headers=BGP_CP_TRAFFIC_PACKET_HEADERS,
        ),
        taac_types.BasicTrafficItemConfig(
            name="ETH9/1/1_TO_ETH9/2/1_V6",
            bidirectional=True,
            merge_destinations=True,
            line_rate=10,
            src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
            src_endpoints=[
                taac_types.TrafficEndpoint(
                    name="ssw002.s001.f02.snc1:eth9/1/1", network_group_index=0
                )
            ],
            dest_endpoints=[
                taac_types.TrafficEndpoint(
                    name="ssw002.s001.f02.snc1:eth9/2/1", network_group_index=0
                )
            ],
            traffic_type=ixia_types.TrafficType.IPV6,
            tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
        ),
        taac_types.BasicTrafficItemConfig(
            name="ETH9/1/1_TO_ETH9/16/1_V6",
            bidirectional=False,
            merge_destinations=True,
            line_rate=10,
            src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
            src_endpoints=[
                taac_types.TrafficEndpoint(
                    name="ssw002.s001.f02.snc1:eth9/1/1", network_group_index=0
                )
            ],
            dest_endpoints=[
                taac_types.TrafficEndpoint(
                    name="ssw002.s001.f02.snc1:eth9/16/1", network_group_index=0
                )
            ],
            traffic_type=ixia_types.TrafficType.IPV6,
            tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
        ),
        taac_types.BasicTrafficItemConfig(
            name="ETH9/1/1_TO_ETH9/2/1_V4",
            bidirectional=True,
            merge_destinations=True,
            line_rate=10,
            src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
            src_endpoints=[
                taac_types.TrafficEndpoint(
                    name="ssw002.s001.f02.snc1:eth9/2/1",
                    network_group_index=0,
                    device_group_index=1,
                )
            ],
            dest_endpoints=[
                taac_types.TrafficEndpoint(
                    name="ssw002.s001.f02.snc1:eth9/1/1",
                    network_group_index=0,
                    device_group_index=1,
                )
            ],
            traffic_type=ixia_types.TrafficType.IPV4,
            tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
        ),
        taac_types.BasicTrafficItemConfig(
            name="ETH9/1/1_TO_ETH9/16/1_V4",
            bidirectional=False,
            merge_destinations=True,
            line_rate=10,
            src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
            src_endpoints=[
                taac_types.TrafficEndpoint(
                    name="ssw002.s001.f02.snc1:eth9/1/1",
                    network_group_index=0,
                    device_group_index=1,
                )
            ],
            dest_endpoints=[
                taac_types.TrafficEndpoint(
                    name="ssw002.s001.f02.snc1:eth9/16/1",
                    network_group_index=0,
                    device_group_index=1,
                )
            ],
            traffic_type=ixia_types.TrafficType.IPV4,
            tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
        ),
    ],
    playbooks=_add_checks_to_playbooks(
        [
            build_snc_playbook(
                name="test_cpu_high_priority_queue_overload",
                snapshot_checks=[
                    create_bgp_session_snapshot_check(
                        pre_snapshot_checkpoint_id="stage.test_cpu_high_priority_queue_overload.step.sleep_120_secs_after_disabling_bgp_cp_traffic.end",
                    ),
                    create_bgp_session_snapshot_check(
                        skip_flap_check=True,
                        post_snapshot_checkpoint_id="stage.test_cpu_high_priority_queue_overload.step.sleep_120_secs_after_disabling_bgp_cp_traffic.end",
                    ),
                ],
                stages=[
                    create_steps_stage(
                        stage_id="test_cpu_high_priority_queue_overload",
                        steps=[
                            create_ixia_api_step(
                                "enable_traffic",
                                {
                                    "regexes": ["HIGH_QUEUE_BGP_CP_TRAFFIC"],
                                    "enable": True,
                                },
                            ),
                            create_longevity_step(600),
                            create_ixia_api_step(
                                "enable_traffic",
                                {
                                    "regexes": ["HIGH_QUEUE_BGP_CP_TRAFFIC"],
                                    "enable": False,
                                },
                            ),
                            create_longevity_step(
                                600,
                                step_id="sleep_120_secs_after_disabling_bgp_cp_traffic",
                            ),
                            create_ixia_api_step(
                                "clear_traffic_stats",
                                {},
                            ),
                            create_longevity_step(30),
                        ],
                    )
                ],
            ),
            build_snc_playbook(
                name="test_bgpd_restart",
                postchecks=[
                    create_bgp_convergence_check(),
                    create_memory_utilization_check(
                        threshold=Gigabyte.GIG_4_POINT_3.value,
                        start_time_jq_var="test_case_start_time",
                    ),
                    create_bgp_rib_fib_consistency_check(),
                ],
                stages=[
                    create_steps_stage(
                        steps=[
                            create_service_interruption_step(
                                service=Service.BGP,
                                trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                            ),
                            create_service_convergence_step(),
                        ]
                    ),
                ],
            ),
            build_snc_playbook(
                name="test_agent_warmboot",
                postchecks=[
                    create_bgp_convergence_check(),
                    create_memory_utilization_check(
                        threshold=Gigabyte.GIG_4_POINT_3.value,
                        start_time_jq_var="test_case_start_time",
                    ),
                    create_bgp_rib_fib_consistency_check(),
                ],
                stages=[
                    create_steps_stage(
                        steps=[
                            create_service_interruption_step(
                                service=Service.AGENT,
                                trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                            ),
                            create_service_convergence_step(timeout=120),
                        ]
                    ),
                ],
            ),
            build_snc_playbook(
                name="test_bgp_session_flap_no_change_in_best_path",
                iteration=5,
                cleanup_steps=[
                    create_ixia_api_step(
                        "start_bgp_peers",
                        {
                            "start": True,
                            "regex": ".*ETH9/2/1.*",
                            "session_end_idx": 4,
                        },
                    ),
                ],
                stages=[
                    create_steps_stage(
                        steps=[
                            create_ixia_api_step(
                                "start_bgp_peers",
                                {
                                    "start": False,
                                    "regex": ".*ETH9/2/1.*",
                                    "session_end_idx": 4,
                                },
                            ),
                            create_longevity_step(600),
                            create_ixia_api_step(
                                "clear_traffic_stats",
                                {},
                            ),
                        ]
                    )
                ],
            ),
            build_snc_playbook(
                name="test_bgp_session_flap_changing_best_path",
                iteration=5,
                postchecks=[
                    create_ixia_packet_loss_check(
                        thresholds=[
                            hc_types.PacketLossThreshold(
                                names=[
                                    "ETH9/1/1_TO_ETH9/2/1_V6",
                                    "ETH9/1/1_TO_ETH9/2/1_V4",
                                ],
                                expect_packet_loss=True,
                            ),
                            hc_types.PacketLossThreshold(
                                names=[
                                    "ETH9/1/1_TO_ETH9/16/1_V6",
                                    "ETH9/1/1_TO_ETH9/16/1_V4",
                                ],
                            ),
                        ]
                    ),
                ],
                cleanup_steps=[
                    create_ixia_api_step(
                        "start_bgp_peers",
                        {
                            "start": True,
                            "regex": ".*ETH9/2/1.*",
                        },
                    ),
                ],
                stages=[
                    create_steps_stage(
                        steps=[
                            create_ixia_api_step(
                                "start_bgp_peers",
                                {
                                    "start": False,
                                    "regex": ".*ETH9/2/1.*",
                                },
                            ),
                            create_longevity_step(600),
                            create_ixia_api_step(
                                "clear_traffic_stats",
                                {},
                            ),
                        ]
                    )
                ],
            ),
            build_snc_playbook(
                name="test_route_churn_no_change_in_best_path",
                iteration=5,
                cleanup_steps=[
                    create_ixia_api_step(
                        "configure_bgp_prefixes",
                        {
                            "enable": True,
                            "network_group_regex": ".*ETH9/2/1.*",
                            "session_end_idx": 4,
                        },
                    ),
                ],
                stages=[
                    create_steps_stage(
                        steps=[
                            create_ixia_api_step(
                                "configure_bgp_prefixes",
                                {
                                    "enable": False,
                                    "network_group_regex": ".*ETH9/2/1.*",
                                    "session_end_idx": 4,
                                },
                            ),
                            create_longevity_step(600),
                            create_ixia_api_step(
                                "clear_traffic_stats",
                                {},
                            ),
                        ]
                    )
                ],
            ),
            build_snc_playbook(
                name="test_route_churn_changing_best_path",
                iteration=5,
                postchecks=[
                    create_ixia_packet_loss_check(
                        thresholds=[
                            hc_types.PacketLossThreshold(
                                names=[
                                    "ETH9/1/1_TO_ETH9/2/1_V6",
                                    "ETH9/1/1_TO_ETH9/2/1_V4",
                                ],
                                expect_packet_loss=True,
                            ),
                            hc_types.PacketLossThreshold(
                                names=[
                                    "ETH9/1/1_TO_ETH9/16/1_V6",
                                    "ETH9/1/1_TO_ETH9/16/1_V4",
                                ],
                            ),
                        ]
                    ),
                ],
                cleanup_steps=[
                    create_ixia_api_step(
                        "configure_bgp_prefixes",
                        {
                            "enable": True,
                            "network_group_regex": ".*ETH9/2/1.*",
                        },
                    ),
                ],
                stages=[
                    create_steps_stage(
                        steps=[
                            create_ixia_api_step(
                                "configure_bgp_prefixes",
                                {
                                    "enable": False,
                                    "network_group_regex": ".*ETH9/2/1.*",
                                },
                            ),
                            create_longevity_step(600),
                            create_ixia_api_step(
                                "clear_traffic_stats",
                                {},
                            ),
                        ]
                    )
                ],
            ),
            build_snc_playbook(
                name="test_ingress_policy_evaluation_processing_time",
                traffic_items_to_start=[],
                backup_and_restore_ixia_config=True,
                postchecks=[
                    create_bgp_convergence_check(
                        extra_json_params={
                            "start_event": "3",  # PEER_INFO_LOADED
                            "end_event": "4",  # ALL_EOR_RECEIVED
                        },
                    ),
                ],
                postchecks_to_skip=[
                    hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
                ],
                stages=[
                    create_steps_stage(
                        steps=[
                            create_ixia_api_step(
                                "start_bgp_peers",
                                {
                                    "start": False,
                                    "regex": "^(?!.*ETH9/16/1).*",
                                },
                            ),
                            create_ixia_api_step(
                                "configure_bgp_prefixes",
                                {
                                    "network_group_regex": ".*ETH8/16/1.*",
                                    "prefix_count": 14000,
                                },
                            ),
                            create_service_interruption_step(
                                service=Service.BGP,
                                trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                            ),
                            create_service_convergence_step(),
                        ],
                    )
                ],
            ),
            build_snc_playbook(
                iteration=5,
                name="test_bgp_graceful_restart",
                stages=[
                    create_steps_stage(
                        steps=[
                            create_ixia_api_step(
                                "start_bgp_peers",
                                {
                                    "start": False,
                                    "regex": "ETH9/16/1",
                                },
                            ),
                            create_longevity_step(100),
                            create_ixia_api_step(
                                "start_bgp_peers",
                                {
                                    "start": True,
                                    "regex": "ETH9/16/1",
                                },
                            ),
                        ],
                    )
                ],
            ),
            build_snc_playbook(
                backup_and_restore_ixia_config=True,
                name="test_bgp_graceful_restart_failure_induced_unprogramming_of_routes",
                postchecks=[
                    create_ixia_packet_loss_check(
                        thresholds=[
                            hc_types.PacketLossThreshold(
                                expect_packet_loss=True,
                            )
                        ]
                    ),
                ],
                stages=[
                    create_steps_stage(
                        steps=[
                            create_ixia_api_step(
                                "start_bgp_peers",
                                {
                                    "start": False,
                                    "regex": "ETH9/2/1",
                                },
                            ),
                            create_longevity_step(150),
                        ],
                    )
                ],
            ),
            build_snc_playbook(
                name="test_bgp_graceful_restart_failure_induced_nh_shrink",
                backup_and_restore_ixia_config=True,
                stages=[
                    create_steps_stage(
                        steps=[
                            create_ixia_api_step(
                                "start_bgp_peers",
                                {
                                    "start": False,
                                    "regex": "ETH9/2/1",
                                    "session_end_idx": 4,
                                },
                            ),
                            create_longevity_step(150),
                        ],
                    )
                ],
            ),
            build_snc_playbook(
                name="test_bgp_unqiue_prefix_limit_threshold_test",
                backup_and_restore_ixia_config=True,
                stages=[
                    create_steps_stage(
                        steps=[
                            create_ixia_api_step(
                                "configure_advertised_prefixes",
                                {
                                    "network_group_regex": ".*V6.*ETH9/16/1.*",
                                    "starting_ip": "7000:1::",
                                },
                            ),
                        ],
                    ),
                ],
            ),
            build_snc_playbook(
                name="test_bgp_unqiue_prefix_limit_route_churn_test",
                backup_and_restore_ixia_config=True,
                iteration=5,
                cleanup_steps=[
                    create_ixia_api_step(
                        "configure_bgp_prefixes",
                        {
                            "enable": True,
                            "network_group_regex": ".*ETH9/16/1.*",
                            "session_end_idx": 8,
                        },
                    ),
                ],
                stages=[
                    create_steps_stage(
                        steps=[
                            create_ixia_api_step(
                                "configure_advertised_prefixes",
                                {
                                    "network_group_regex": ".*V6.*ETH9/16/1.*",
                                    "starting_ip": "7000:1::",
                                },
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_ixia_api_step(
                                "configure_bgp_prefixes",
                                {
                                    "enable": False,
                                    "network_group_regex": ".*ETH9/16/1.*",
                                    "session_end_idx": 8,
                                },
                            ),
                            create_longevity_step(600),
                            create_ixia_api_step(
                                "clear_traffic_stats",
                                {},
                            ),
                        ]
                    ),
                ],
            ),
            build_snc_playbook(
                name="test_bgp_unqiue_prefix_limit_session_flap_test",
                backup_and_restore_ixia_config=True,
                iteration=5,
                cleanup_steps=[
                    create_ixia_api_step(
                        "start_bgp_peers",
                        {
                            "start": True,
                            "regex": ".*ETH9/16/1.*",
                        },
                    ),
                ],
                stages=[
                    create_steps_stage(
                        steps=[
                            create_ixia_api_step(
                                "configure_advertised_prefixes",
                                {
                                    "network_group_regex": ".*V6.*ETH9/16/1.*",
                                    "starting_ip": "7000:1::",
                                },
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_ixia_api_step(
                                "start_bgp_peers",
                                {
                                    "start": False,
                                    "regex": ".*ETH9/16/1.*",
                                },
                            ),
                            create_longevity_step(600),
                            create_ixia_api_step(
                                "clear_traffic_stats",
                                {},
                            ),
                        ]
                    ),
                ],
            ),
            build_snc_playbook(
                name="test_6_min_longevity",
                stages=[
                    create_steps_stage(
                        steps=[
                            create_longevity_step(600),
                        ],
                    )
                ],
                snapshot_checks=[create_bgp_session_snapshot_check()],
            ),
        ],
        prechecks=[
            create_prefix_limit_check(),
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=[
                            "ETH9/1/1_TO_ETH9/16/1_V6",
                            "ETH9/1/1_TO_ETH9/16/1_V4",
                        ],
                        expect_packet_loss=True,
                    ),
                ]
            ),
        ],
        postchecks=[
            create_prefix_limit_check(),
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=[
                            "ETH9/1/1_TO_ETH9/16/1_V6",
                            "ETH9/1/1_TO_ETH9/16/1_V4",
                        ],
                        expect_packet_loss=True,
                    ),
                ]
            ),
            create_unclean_exit_check(start_time_jq_var=None),
            create_memory_utilization_check(),
        ],
        snapshot_checks=[
            create_next_hop_count_snapshot_check(),
        ],
    ),
)
