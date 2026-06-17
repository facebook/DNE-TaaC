# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""QZD_SINGLE_NODE_TOPOLOGY_MIMIC_FAUU TestConfig.

Single-node BGP++ scale longevity TestConfig that mimics the FAUU multi-
node topology on fsw003.p003.f01.qzd1. Builds a multi-port IXIA setup,
applies COOP patchers + parallel BGP peer config, and exercises full
warmboot/coldboot/FSDB/QSPF/BGPD restart playbooks plus longevity stages.
"""

import json

from ixia.ixia import types as ixia_types
from taac.constants import Gigabyte
from taac.health_checks.healthcheck_definitions import (
    create_bgp_convergence_check,
    create_bgp_rib_fib_consistency_check,
    create_bgp_session_snapshot_check,
    create_device_core_dumps_check,
    create_ixia_packet_loss_check,
    create_log_parsing_check,
    create_memory_utilization_check,
    create_prefix_limit_check,
    create_unclean_exit_check,
)
from taac.playbooks.playbook_definitions import (
    build_qzd_playbook,
    rebuild_qzd_playbook_with_checks,
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
        rebuild_qzd_playbook_with_checks(
            pb,
            prechecks=prechecks,
            postchecks=postchecks,
            snapshot_checks=snapshot_checks,
        )
        for pb in playbooks
    ]


QZD_SINGLE_NODE_TOPOLOGY_MIMIC_FAUU_TEST_CONFIG = TestConfig(
    name="QZD_SINGLE_NODE_TOPOLOGY_MIMIC_FAUU",
    basset_pool="dne.regression",
    endpoints=[
        taac_types.Endpoint(
            name="fsw003.p003.f01.qzd1",
            ixia_ports=["eth8/16/1", "eth9/16/1", "eth7/16/1"],
            dut=True,
        ),
    ],
    setup_tasks=[
        create_coop_unregister_patchers_task("fsw003.p003.f01.qzd1"),
        # Remove all the bgp peers present in the device first
        create_coop_register_patcher_task(
            hostname="fsw003.p003.f01.qzd1",
            config_name="bgpcpp",
            patcher_name="a_remove_bgp_peers",
            task_name="remove_bgp_peers",
            patcher_args={"delete_all": "True"},
            py_func_name="remove_bgp_peers",
        ),
        create_coop_register_patcher_task(
            hostname="fsw003.p003.f01.qzd1",
            config_name="bgpcpp",
            patcher_name="configure_bgp_switch_limit",
            task_name="configure_bgp_switch_limit",
            patcher_args={
                "prefix_limit": "73000",
            },
            py_func_name="configure_bgp_switch_limit",
        ),
        create_coop_register_patcher_task(
            hostname="fsw003.p003.f01.qzd1",
            config_name="bgpcpp",
            patcher_name="update_peer_group_patcher_FSW_RSW_V6_Downlink",
            task_name="configure_bgp_peer_group",
            patcher_args={
                "name": "PEERGROUP_FSW_RSW_V6",
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
            hostname="fsw003.p003.f01.qzd1",
            config_name="bgpcpp",
            patcher_name="update_peer_group_patcher_FSW_SSW_V6_Uplink",
            task_name="configure_bgp_peer_group",
            patcher_args={
                "name": "PEERGROUP_FSW_SSW_V6",
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
            hostname="fsw003.p003.f01.qzd1",
            config_name="bgpcpp",
            patcher_name="add_peer_group_patcher_FSW_SSW_V4",
            task_name="add_peer_group_patcher",
            patcher_args={
                "name": "PEERGROUP_FSW_SSW_V4",
                "description": "BGP peering from SSW to FSW, IPv4 sessions",
                "next_hop_self": "True",
                "disable_ipv4_afi": "False",
                "disable_ipv6_afi": "True",
                "is_confed_peer": "False",
                "ingress_policy_name": "PROPAGATE_FSW_SSW_IN",
                "egress_policy_name": "PROPAGATE_FSW_SSW_OUT",
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
        create_coop_register_patcher_task(
            hostname="fsw003.p003.f01.qzd1",
            config_name="bgpcpp",
            patcher_name="add_peer_group_patcher_FSW_RSW_V4",
            task_name="add_peer_group_patcher",
            patcher_args={
                "name": "PEERGROUP_FSW_RSW_V4",
                "description": "BGP peering from RSW to FSW, IPv4 sessions",
                "next_hop_self": "True",
                "disable_ipv4_afi": "False",
                "disable_ipv6_afi": "True",
                "is_confed_peer": "True",
                "ingress_policy_name": "PROPAGATE_FSW_RSW_IN",
                "egress_policy_name": "PROPAGATE_FSW_RSW_OUT",
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
            hostnames=["fsw003.p003.f01.qzd1"],
            config_name="bgpcpp",
        ),
        create_configure_parallel_bgp_peers_task(
            hostname="fsw003.p003.f01.qzd1",
            configure_vlans_patcher_name="configure_vlans_patcher_name_downlink",
            add_bgp_peers_patcher_name="add_bgp_peers_patcher_name_downlink",
            config_json=json.dumps(
                {
                    "eth8/16/1": [
                        {
                            "starting_ip": "2401:db00:e50d:1202:8::10",
                            "increment_ip": "0:0:0:0::2",
                            "prefix_length": 127,
                            "description": "Downlink IPv6 Peers",
                            "peer_group_name": "PEERGROUP_FSW_RSW_V6",
                            "num_sessions": 48,
                            "remote_as_4_byte": 2000,
                            "remote_as_4_byte_step": 1,
                            "gateway_starting_ip": "2401:db00:e50d:1202:8::11",
                            "gateway_increment_ip": "0:0:0:0::2",
                        },
                        {
                            "starting_ip": "10.163.28.0",
                            "increment_ip": "0.0.0.2",
                            "prefix_length": 31,
                            "description": "Downlink IPv4 Peers",
                            "peer_group_name": "PEERGROUP_FSW_RSW_V4",
                            "num_sessions": 48,
                            "remote_as_4_byte": 2000,
                            "remote_as_4_byte_step": 1,
                            "gateway_starting_ip": "10.163.28.1",
                            "gateway_increment_ip": "0.0.0.2",
                        },
                    ]
                }
            ),
        ),
        create_wait_for_agent_convergence_task(
            hostnames=["fsw003.p003.f01.qzd1"],
        ),
        create_configure_parallel_bgp_peers_task(
            hostname="fsw003.p003.f01.qzd1",
            configure_vlans_patcher_name="configure_vlans_patcher_name_uplink",
            add_bgp_peers_patcher_name="add_bgp_peers_patcher_name_uplink",
            config_json=json.dumps(
                {
                    "eth9/16/1": [
                        {
                            "starting_ip": "2401:db00:e50d:1202:9::10",
                            "increment_ip": "0:0:0:0::2",
                            "prefix_length": 127,
                            "description": "Uplink IPv6 Peers",
                            "peer_group_name": "PEERGROUP_FSW_SSW_V6",
                            "num_sessions": 8,
                            "remote_as_4_byte": 65000,
                            "remote_as_4_byte_step": 1,
                            "gateway_starting_ip": "2401:db00:e50d:1202:9::11",
                            "gateway_increment_ip": "0:0:0:0::2",
                        },
                        {
                            "starting_ip": "10.164.28.0",
                            "increment_ip": "0.0.0.2",
                            "prefix_length": 31,
                            "description": "Uplink IPv4 Peers",
                            "peer_group_name": "PEERGROUP_FSW_SSW_V4",
                            "num_sessions": 8,
                            "remote_as_4_byte": 65000,
                            "remote_as_4_byte_step": 1,
                            "gateway_starting_ip": "10.164.28.1",
                            "gateway_increment_ip": "0.0.0.2",
                        },
                    ],
                    "eth7/16/1": [
                        {
                            "starting_ip": "2401:db00:e50d:1202:10::10",
                            "increment_ip": "0:0:0:0::2",
                            "prefix_length": 127,
                            "description": "Uplink IPv6 Peers",
                            "peer_group_name": "PEERGROUP_FSW_SSW_V6",
                            "num_sessions": 8,
                            "remote_as_4_byte": 65000,
                            "remote_as_4_byte_step": 1,
                            "gateway_starting_ip": "2401:db00:e50d:1202:10::11",
                            "gateway_increment_ip": "0:0:0:0::2",
                        },
                        {
                            "starting_ip": "10.165.28.0",
                            "increment_ip": "0.0.0.2",
                            "prefix_length": 31,
                            "description": "Uplink IPv4 Peers",
                            "peer_group_name": "PEERGROUP_FSW_SSW_V4",
                            "num_sessions": 8,
                            "remote_as_4_byte": 65000,
                            "remote_as_4_byte_step": 1,
                            "gateway_starting_ip": "10.165.28.1",
                            "gateway_increment_ip": "0.0.0.2",
                        },
                    ],
                }
            ),
        ),
        create_coop_apply_patchers_task(
            hostnames=["fsw003.p003.f01.qzd1"],
            do_warmboot=True,
        ),
    ],
    teardown_tasks=[
        create_coop_unregister_patchers_task("fsw003.p003.f01.qzd1"),
    ],
    basic_port_configs=[
        taac_types.BasicPortConfig(
            endpoint="fsw003.p003.f01.qzd1:eth8/16/1",
            device_group_configs=[
                taac_types.DeviceGroupConfig(
                    device_group_index=0,
                    multiplier=48,
                    v6_addresses_config=taac_types.IpAddressesConfig(
                        starting_ip="2401:db00:e50d:1202:8::11",
                        increment_ip="0:0:0:0::2",
                        gateway_starting_ip="2401:db00:e50d:1202:8::10",
                        gateway_increment_ip="0:0:0:0::2",
                    ),
                    v6_bgp_config=taac_types.BgpConfig(
                        local_as_4_bytes=2000,
                        local_as_increment=1,
                        enable_4_byte_local_as=True,
                        is_confed=True,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        route_scales=[
                            taac_types.RouteScaleSpec(
                                network_group_index=0,
                                v6_route_scale=taac_types.RouteScale(
                                    multiplier=1,
                                    prefix_count=5000,
                                    prefix_length=64,
                                    starting_prefixes="3000:1::",
                                    prefix_step="0:0:0:0::0",
                                    bgp_communities=[
                                        "65441:194",
                                        "65441:9001",
                                        "65441:9002",
                                        "65441:9003",
                                        "65441:9004",
                                        "65441:9005",
                                    ],
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
                                    bgp_communities=[
                                        "65441:194",
                                        "65441:9001",
                                        "65441:9002",
                                        "65441:9003",
                                        "65441:9004",
                                        "65441:9005",
                                    ],
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
                    multiplier=48,
                    v4_addresses_config=taac_types.IpAddressesConfig(
                        starting_ip="10.163.28.1",
                        increment_ip="0.0.0.2",
                        gateway_starting_ip="10.163.28.0",
                        gateway_increment_ip="0.0.0.2",
                        mask=31,
                    ),
                    v4_bgp_config=taac_types.BgpConfig(
                        local_as_4_bytes=2000,
                        local_as_increment=1,
                        enable_4_byte_local_as=True,
                        is_confed=True,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                        route_scales=[
                            taac_types.RouteScaleSpec(
                                network_group_index=0,
                                v4_route_scale=taac_types.RouteScale(
                                    multiplier=1,
                                    prefix_count=5000,
                                    prefix_length=24,
                                    starting_prefixes="101.1.0.0",
                                    prefix_step="0.0.0.0",
                                    bgp_communities=[
                                        "65441:194",
                                        "65441:9001",
                                        "65441:9002",
                                        "65441:9003",
                                        "65441:9004",
                                        "65441:9005",
                                    ],
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
                                    bgp_communities=[
                                        "65441:194",
                                        "65441:9001",
                                        "65441:9002",
                                        "65441:9003",
                                        "65441:9004",
                                        "65441:9005",
                                    ],
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
            endpoint="fsw003.p003.f01.qzd1:eth9/16/1",
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
                        local_as_4_bytes=65000,
                        local_as_increment=1,
                        enable_4_byte_local_as=True,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        route_scales=[
                            taac_types.RouteScaleSpec(
                                network_group_index=0,
                                v6_route_scale=taac_types.RouteScale(
                                    multiplier=1,
                                    prefix_count=12000,
                                    prefix_length=64,
                                    starting_prefixes="5000:1::",
                                    prefix_step="0:0:0:0::0",
                                    bgp_communities=[
                                        "65441:196",
                                        "65441:9001",
                                        "65441:9002",
                                        "65441:9003",
                                        "65441:9004",
                                        "65441:9005",
                                    ],
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
                                    prefix_count=4000,
                                    prefix_length=64,
                                    starting_prefixes="5000:2::",
                                    prefix_step="0:0:0:0::0",
                                    bgp_communities=[
                                        "65441:196",
                                        "65441:9001",
                                        "65441:9002",
                                        "65441:9003",
                                        "65441:9004",
                                        "65441:9005",
                                    ],
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
                        local_as_4_bytes=65000,
                        local_as_increment=1,
                        enable_4_byte_local_as=True,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                        route_scales=[
                            taac_types.RouteScaleSpec(
                                network_group_index=0,
                                v4_route_scale=taac_types.RouteScale(
                                    multiplier=1,
                                    prefix_count=12000,
                                    prefix_length=24,
                                    starting_prefixes="201.1.0.0",
                                    prefix_step="0.0.0.0",
                                    bgp_communities=[
                                        "65441:196",
                                        "65441:9001",
                                        "65441:9002",
                                        "65441:9003",
                                        "65441:9004",
                                        "65441:9005",
                                    ],
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
                                    prefix_count=4000,
                                    prefix_length=24,
                                    starting_prefixes="202.1.0.0",
                                    prefix_step="0.0.0.0",
                                    bgp_communities=[
                                        "65441:196",
                                        "65441:9001",
                                        "65441:9002",
                                        "65441:9003",
                                        "65441:9004",
                                        "65441:9005",
                                    ],
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
            endpoint="fsw003.p003.f01.qzd1:eth7/16/1",
            device_group_configs=[
                taac_types.DeviceGroupConfig(
                    device_group_index=0,
                    multiplier=8,
                    v6_addresses_config=taac_types.IpAddressesConfig(
                        starting_ip="2401:db00:e50d:1202:10::11",
                        increment_ip="0:0:0:0::2",
                        gateway_starting_ip="2401:db00:e50d:1202:10::10",
                        gateway_increment_ip="0:0:0:0::2",
                    ),
                    v6_bgp_config=taac_types.BgpConfig(
                        local_as_4_bytes=65000,
                        local_as_increment=1,
                        enable_4_byte_local_as=True,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        route_scales=[
                            taac_types.RouteScaleSpec(
                                network_group_index=0,
                                v6_route_scale=taac_types.RouteScale(
                                    multiplier=1,
                                    prefix_count=12000,
                                    prefix_length=64,
                                    starting_prefixes="5000:1::",
                                    prefix_step="0:0:0:0::0",
                                    bgp_communities=[
                                        "65441:196",
                                        "65441:9001",
                                        "65441:9002",
                                        "65441:9003",
                                        "65441:9004",
                                        "65441:9005",
                                    ],
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
                                    prefix_count=4000,
                                    prefix_length=64,
                                    starting_prefixes="5000:2::",
                                    prefix_step="0:0:0:0::0",
                                    bgp_communities=[
                                        "65441:196",
                                        "65441:9001",
                                        "65441:9002",
                                        "65441:9003",
                                        "65441:9004",
                                        "65441:9005",
                                    ],
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
                        local_as_4_bytes=65000,
                        local_as_increment=1,
                        enable_4_byte_local_as=True,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                        route_scales=[
                            taac_types.RouteScaleSpec(
                                network_group_index=0,
                                v4_route_scale=taac_types.RouteScale(
                                    multiplier=1,
                                    prefix_count=12000,
                                    prefix_length=24,
                                    starting_prefixes="201.1.0.0",
                                    prefix_step="0.0.0.0",
                                    bgp_communities=[
                                        "65441:196",
                                        "65441:9001",
                                        "65441:9002",
                                        "65441:9003",
                                        "65441:9004",
                                        "65441:9005",
                                    ],
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
                                    prefix_count=4000,
                                    prefix_length=24,
                                    starting_prefixes="202.1.0.0",
                                    prefix_step="0.0.0.0",
                                    bgp_communities=[
                                        "65441:196",
                                        "65441:9001",
                                        "65441:9002",
                                        "65441:9003",
                                        "65441:9004",
                                        "65441:9005",
                                    ],
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
    basic_traffic_item_configs=[
        taac_types.BasicTrafficItemConfig(
            name="ETH8/16/1_TO_ETH9/16/1_V6",
            bidirectional=True,
            merge_destinations=True,
            line_rate=10,
            src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
            src_endpoints=[
                taac_types.TrafficEndpoint(
                    name="fsw003.p003.f01.qzd1:eth8/16/1", network_group_index=0
                )
            ],
            dest_endpoints=[
                taac_types.TrafficEndpoint(
                    name="fsw003.p003.f01.qzd1:eth9/16/1", network_group_index=0
                )
            ],
            traffic_type=ixia_types.TrafficType.IPV6,
            tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
        ),
        taac_types.BasicTrafficItemConfig(
            name="ETH8/16/1_TO_ETH7/16/1_V6",
            bidirectional=False,
            merge_destinations=True,
            line_rate=10,
            src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
            src_endpoints=[
                taac_types.TrafficEndpoint(
                    name="fsw003.p003.f01.qzd1:eth8/16/1", network_group_index=0
                )
            ],
            dest_endpoints=[
                taac_types.TrafficEndpoint(
                    name="fsw003.p003.f01.qzd1:eth7/16/1", network_group_index=0
                )
            ],
            traffic_type=ixia_types.TrafficType.IPV6,
            tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
        ),
        taac_types.BasicTrafficItemConfig(
            name="ETH8/16/1_TO_ETH9/16/1_V4",
            bidirectional=True,
            merge_destinations=True,
            line_rate=10,
            src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
            src_endpoints=[
                taac_types.TrafficEndpoint(
                    name="fsw003.p003.f01.qzd1:eth8/16/1",
                    network_group_index=0,
                    device_group_index=1,
                )
            ],
            dest_endpoints=[
                taac_types.TrafficEndpoint(
                    name="fsw003.p003.f01.qzd1:eth9/16/1",
                    network_group_index=0,
                    device_group_index=1,
                )
            ],
            traffic_type=ixia_types.TrafficType.IPV4,
            tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
        ),
        taac_types.BasicTrafficItemConfig(
            name="ETH8/16/1_TO_ETH7/16/1_V4",
            bidirectional=False,
            merge_destinations=True,
            line_rate=10,
            src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
            src_endpoints=[
                taac_types.TrafficEndpoint(
                    name="fsw003.p003.f01.qzd1:eth8/16/1",
                    network_group_index=0,
                    device_group_index=1,
                )
            ],
            dest_endpoints=[
                taac_types.TrafficEndpoint(
                    name="fsw003.p003.f01.qzd1:eth7/16/1",
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
            build_qzd_playbook(
                name="test_bgp_session_flap_no_change_in_best_path",
                iteration=5,
                cleanup_steps=[
                    create_ixia_api_step(
                        "start_bgp_peers",
                        {
                            "start": True,
                            "regex": ".*ETH7/16/1.*",
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
                                    "regex": ".*ETH7/16/1.*",
                                    "session_end_idx": 4,
                                },
                            ),
                            create_longevity_step(150),
                            create_ixia_api_step(
                                "clear_traffic_stats",
                                {},
                            ),
                        ]
                    )
                ],
            ),
            build_qzd_playbook(
                name="test_bgp_session_flap_changing_best_path",
                iteration=5,
                postchecks=[
                    create_ixia_packet_loss_check(
                        thresholds=[
                            hc_types.PacketLossThreshold(
                                names=[
                                    "ETH8/16/1_TO_ETH9/16/1_V6",
                                    "ETH8/16/1_TO_ETH9/16/1_V4",
                                ],
                                expect_packet_loss=True,
                            ),
                            hc_types.PacketLossThreshold(
                                names=[
                                    "ETH8/16/1_TO_ETH7/16/1_V6",
                                    "ETH8/16/1_TO_ETH7/16/1_V4",
                                ],
                            ),
                        ],
                    ),
                ],
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
                                "start_bgp_peers",
                                {
                                    "start": False,
                                    "regex": ".*ETH9/16/1.*",
                                },
                            ),
                            create_longevity_step(150),
                            create_ixia_api_step(
                                "clear_traffic_stats",
                                {},
                            ),
                        ]
                    )
                ],
            ),
            build_qzd_playbook(
                name="test_route_churn_no_change_in_best_path",
                iteration=5,
                cleanup_steps=[
                    create_ixia_api_step(
                        "configure_bgp_prefixes",
                        {
                            "enable": True,
                            "network_group_regex": ".*ETH7/16/1.*",
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
                                    "network_group_regex": ".*ETH7/16/1.*",
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
            build_qzd_playbook(
                name="test_route_churn_changing_best_path",
                iteration=5,
                postchecks=[
                    create_ixia_packet_loss_check(
                        thresholds=[
                            hc_types.PacketLossThreshold(
                                names=[
                                    "ETH8/16/1_TO_ETH9/16/1_V6",
                                    "ETH8/16/1_TO_ETH9/16/1_V4",
                                ],
                                expect_packet_loss=True,
                            ),
                            hc_types.PacketLossThreshold(
                                names=[
                                    "ETH8/16/1_TO_ETH7/16/1_V6",
                                    "ETH8/16/1_TO_ETH7/16/1_V4",
                                ],
                            ),
                        ],
                    ),
                ],
                cleanup_steps=[
                    create_ixia_api_step(
                        "configure_bgp_prefixes",
                        {
                            "enable": True,
                            "network_group_regex": ".*ETH9/16/1.*",
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
                                    "network_group_regex": ".*ETH9/16/1.*",
                                },
                            ),
                            create_longevity_step(180),
                            create_ixia_api_step(
                                "clear_traffic_stats",
                                {},
                            ),
                        ]
                    )
                ],
            ),
            build_qzd_playbook(
                name="test_ingress_policy_evaluation_processing_time",
                traffic_items_to_start=[],
                postchecks=[
                    create_bgp_convergence_check(
                        extra_json_params={"start_event": "3", "end_event": "4"}
                    ),
                ],
                postchecks_to_skip=[
                    hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
                ],
                stages=[
                    create_steps_stage(
                        steps=[
                            create_service_interruption_step(
                                service=Service.BGP,
                                trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                            ),
                            create_service_convergence_step(),
                        ],
                    )
                ],
            ),
            build_qzd_playbook(
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
            build_qzd_playbook(
                name="test_6_min_longevity",
                stages=[
                    create_steps_stage(
                        steps=[
                            create_longevity_step(360),
                        ],
                    )
                ],
                snapshot_checks=[create_bgp_session_snapshot_check()],
            ),
            build_qzd_playbook(
                name="test_bgpd_restart",
                postchecks_to_skip=[
                    hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
                ],
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
            build_qzd_playbook(
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
        ],
        prechecks=[
            create_prefix_limit_check(),
            create_device_core_dumps_check(use_start_time=False),
            create_log_parsing_check(),
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=[
                            "ETH8/16/1_TO_ETH7/16/1_V6",
                            "ETH8/16/1_TO_ETH7/16/1_V4",
                        ],
                        expect_packet_loss=True,
                    ),
                ],
            ),
        ],
        postchecks=[
            create_device_core_dumps_check(use_start_time=False),
            create_log_parsing_check(),
            create_prefix_limit_check(),
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=[
                            "ETH8/16/1_TO_ETH7/16/1_V6",
                            "ETH8/16/1_TO_ETH7/16/1_V4",
                        ],
                        expect_packet_loss=True,
                    ),
                ],
            ),
            create_unclean_exit_check(start_time_jq_var=None),
            create_memory_utilization_check(),
        ],
    ),
)
