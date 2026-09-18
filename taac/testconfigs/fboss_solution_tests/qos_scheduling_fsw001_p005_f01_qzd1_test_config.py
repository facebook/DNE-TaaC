# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""First-wave QoS scheduling TestConfig for fsw001.p005.f01.qzd1."""

import json

from taac.task_definitions import (
    create_configure_parallel_bgp_peers_task,
    create_coop_register_patcher_task,
    create_invoke_ixia_api_task,
    create_run_commands_on_shell_task,
    create_wait_for_agent_convergence_task,
)
from taac.testconfigs.fboss_solution_tests.qos_scheduling_test_config import (
    test_config_qos_scheduling,
)
from taac.test_as_a_config import types as taac_types


_BASE_TEST_CONFIG = test_config_qos_scheduling(
    test_config_name="QOS_SCHEDULING_FSW001_P005_F01_QZD1",
    device_name="fsw001.p005.f01.qzd1",
    local_mac_address="fc:59:c0:46:22:36",
    ixia_downlink_interface="eth8/16/1",
    ixia_uplink_interface="eth9/16/1",
    ixia_rogue_interface="eth7/16/1",
    peergroup_uplink_mimic_v6="PEERGROUP_FSW_SSW_V6",
    peergroup_uplink_mimic_v4="PEERGROUP_FSW_SSW_V4",
    peergroup_downlink_mimic_v6="PEERGROUP_FSW_RSW_V6",
    peergroup_downlink_mimic_v4="PEERGROUP_FSW_RSW_V4",
    peergroup_rogue_mimic_v6="PEERGROUP_FSW_SSW_V6",
    peergroup_rogue_mimic_v4="PEERGROUP_FSW_SSW_V4",
    route_map_uplink_ingress="PROPAGATE_FSW_SSW_IN",
    route_map_uplink_egress="PROPAGATE_FSW_SSW_OUT",
    route_map_downlink_ingress="PROPAGATE_FSW_RSW_IN",
    route_map_downlink_egress="PROPAGATE_FSW_RSW_OUT",
    route_map_rogue_ingress="PROPAGATE_FSW_SSW_IN",
    route_map_rogue_egress="PROPAGATE_FSW_RSW_OUT",
    ixia_downlink_ic_parent_network_v6="2401:db00:e50d:11:8",
    ixia_uplink_ic_parent_network_v6="2401:db00:e50d:11:9",
    ixia_rogue_ic_parent_network_v6="2401:db00:e50d:11:10",
    ixia_downlink_ic_parent_network_v4="10.163.28",
    ixia_uplink_ic_parent_network_v4="10.164.28",
    ixia_rogue_ic_parent_network_v4="10.165.28",
    good_ndp_entry_network_v6="2401:db00:e50d:11:9",
    rogue_ndp_entry_network_v6="2401:db00:e50d:11:8",
    good_arp_entry_network_v4="192.168",
    rogue_arp_entry_network_v4="193.168",
    prefix_limit="75000",
    per_peer_max_route_limit="25000",
    downlink_peer_count=1,
    uplink_peer_count=1,
    rogue_peer_count=1,
    remote_downlink_as_4byte=2000,
    remote_uplink_as_4byte=65000,
    remote_rogue_as_4byte=2500,
    is_uplink_peer_confed="False",
    is_downlink_peer_confed="True",
    is_rogue_peer_confed="False",
    ixia_downlink_prefix_count_v6=100,
    ixia_uplink_prefix_count_v6=100,
    ixia_rogue_prefix_count_v6=100,
    ixia_downlink_prefix_count_v4=100,
    ixia_uplink_prefix_count_v4=100,
    ixia_rogue_prefix_count_v4=100,
    ixia_downlink_communities=[
        "65441:194",
        "65441:9001",
        "65441:9002",
        "65441:9003",
        "65441:9004",
        "65441:9005",
    ],
    ixia_uplink_communities=[
        "65441:196",
        "65441:9001",
        "65441:9002",
        "65441:9003",
        "65441:9004",
        "65441:9005",
    ],
    downlink_peer_tag="RSW",
    uplink_peer_tag="SSW",
    ecmp_group_limit=1520,
    good_ndp_entries_uplink=1,
    good_ndp_entries_downlink=1,
    rogue_ndp_entries=1,
    good_arp_entries=1,
    rogue_arp_entries=1,
    good_mac_entry_count=1,
    rogue_mac_entry_count=1,
    bgp_induced_ecmp_group_count=1,
    ixia_uplink_good_ndp_network="2401:db00:e50d:1101:9",
    ixia_downlink_good_ndp_network="2401:db00:e50d:1101:8",
    basset_pool="dne.test",
    ixia_congestion_interface="eth6/16/1",
    ixia_congestion_ic_parent_network_v6="2401:db00:e50d:11:11",
    congestion_peer_as_4byte=65000,
    congestion_prefix_count_v6=100,
    congestion_prefix_start_v6="2401:db00:e50d:1101:10::",
    is_congestion_peer_confed="False",
    additional_setup_tasks=[
        create_configure_parallel_bgp_peers_task(
            hostname="fsw001.p005.f01.qzd1",
            configure_vlans_patcher_name="configure_vlans_patcher_name_congestion",
            add_bgp_peers_patcher_name="add_bgp_peers_patcher_name_congestion",
            config_json=json.dumps(
                {
                    "eth6/16/1": [
                        {
                            "starting_ip": "2401:db00:e50d:11:11::10",
                            "increment_ip": "0:0:0:0::2",
                            "prefix_length": 127,
                            "description": "Congestion IPv6 Peer",
                            "peer_group_name": "PEERGROUP_FSW_SSW_V6",
                            "num_sessions": 1,
                            "remote_as_4_byte": 65000,
                            "remote_as_4_byte_step": 0,
                            "gateway_starting_ip": "2401:db00:e50d:11:11::11",
                            "gateway_increment_ip": "0:0:0:0::2",
                        },
                    ]
                }
            ),
        ),
        create_coop_register_patcher_task(
            hostname="fsw001.p005.f01.qzd1",
            config_name="agent",
            patcher_name="enable_eth6_16_1",
            task_name="coop_register_patcher",
            patcher_args={"eth6/16/1": "enable"},
            py_func_name="change_port_admin_state",
        ),
        create_invoke_ixia_api_task(
            api_name="stop_protocols_and_wait",
            args_dict={"timeout_seconds": 120, "poll_seconds": 2},
        ),
        create_invoke_ixia_api_task(
            api_name="start_and_verify_protocols",
            args_dict={},
        ),
    ],
)

_TEST_CONFIG_FIELDS = dict(_BASE_TEST_CONFIG)
_TEST_CONFIG_FIELDS["ixia_protocol_verification_timeout"] = 60
_TEST_CONFIG_FIELDS["endpoints"] = [
    taac_types.Endpoint(
        name=endpoint.name,
        ixia_needed=endpoint.ixia_needed,
        ixia_ports=endpoint.ixia_ports,
        dut=endpoint.dut,
        direct_ixia_connections=[
            taac_types.DirectIxiaConnection(
                interface="eth9/16/1",
                ixia_chassis_ip="2401:db00:116:3006:21a:c5ff:fe01:314c",
                ixia_port="3/5",
            ),
            taac_types.DirectIxiaConnection(
                interface="eth6/16/1",
                ixia_chassis_ip="2401:db00:116:3006:21a:c5ff:fe01:314c",
                ixia_port="6/4",
            ),
            taac_types.DirectIxiaConnection(
                interface="eth8/16/1",
                ixia_chassis_ip="2401:db00:116:3006:21a:c5ff:fe01:314c",
                ixia_port="10/3",
            ),
        ],
    )
    for endpoint in _BASE_TEST_CONFIG.endpoints
]
_TEST_CONFIG_FIELDS["setup_tasks"] = [
    create_run_commands_on_shell_task(
        hostname="fsw001.p005.f01.qzd1",
        cmds=[
            "fboss_local_drainer undrain; "
            "fboss_local_drainer is_drained; [ $? -eq 162 ]"
        ],
        validate_output=True,
    ),
    *[
        task
        for task in _BASE_TEST_CONFIG.setup_tasks
        if task.task_name
        not in {"add_stress_static_routes", "allocate_cgroup_slice_memory"}
    ],
    create_run_commands_on_shell_task(
        hostname="fsw001.p005.f01.qzd1",
        cmds=[
            "touch /dev/shm/fboss/warm_boot/cold_boot_once_0 && "
            "sudo systemctl restart wedge_agent"
        ],
        validate_output=True,
    ),
    create_wait_for_agent_convergence_task(
        hostnames="fsw001.p005.f01.qzd1",
        timeout=600,
        interval=5,
    ),
]
QOS_SCHEDULING_FSW001_P005_F01_QZD1_TEST_CONFIG = taac_types.TestConfig(
    **_TEST_CONFIG_FIELDS
)
