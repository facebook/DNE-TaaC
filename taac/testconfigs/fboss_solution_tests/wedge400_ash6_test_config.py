# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe

"""
Wedge400 ASH6 Testbed — SAI Migration Functional Testing

FBOSS Wedge400 (RTSW) with IXIA traffic generators for SAI functional
qualification. Single-node testing focused on hardening and PFC.

Testbed Topology:
  rtsw001.c085.f00.ash6 eth1/1/1 → ixia06:1/13 (400G)
  rtsw001.c085.f00.ash6 eth1/2/1 → ixia06:1/14 (400G)
  rtsw001.c085.f00.ash6 eth1/3/1 → ixia06:1/19 (400G)
  rtsw001.c085.f00.ash6 eth1/4/1 → ixia06:1/20 (400G)

IXIA Chassis: ixia06.netcastle.ash6 (2401:db00:2066:3037::3006)
Optical Switch: calient01.ash6

BGP setup via COOP patchers — IXIA peers with EBGP on all 4 ports.
Traffic flows bidirectionally between port pairs to validate all sessions.
"""

import json

from ixia.ixia import types as ixia_types
from taac.health_checks.healthcheck_definitions import (
    create_bgp_session_snapshot_check,
    create_core_dumps_snapshot_check,
    create_ixia_packet_loss_check,
    create_port_speed_snapshot_check,
    create_systemctl_active_state_check,
)
from taac.packet_headers import (
    DSF_BE_PACKET_HEADERS,
    DSF_MONITORING_PACKET_HEADERS,
    DSF_NC_PACKET_HEADERS,
    DSF_RDMA_IB_PACKET_HEADERS,
)
from taac.playbooks.playbook_definitions import (
    create_pfc_rdma_only_with_clear_counters_playbook,
    create_w400_agent_crash_playbook,
    create_w400_agent_restart_playbook,
    create_w400_bgpd_restart_playbook,
    create_w400_coldboot_playbook,
    create_w400_interface_flap_playbook,
    create_w400_longevity_playbook,
)
from taac.task_definitions import (
    create_configure_parallel_bgp_peers_task,
    create_coop_apply_patchers_task,
    create_coop_unregister_patchers_task,
)
from taac.testconfigs.fboss_solution_tests.network_ai_hardening_test_config import (
    get_rtsw_ixia_peer_group_tasks,
)
from taac.testconfigs.fboss_solution_tests.network_ai_test_configs import (
    gen_pfc_functionality_test_generic_4port_configs,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import TestConfig, TrafficEndpoint


# ============================================================
# Device: rtsw001.c085.f00.ash6 (Wedge400, FBOSS SAI)
#
# IXIA Port Mappings (LLDP verified 2026-04-29):
#   eth1/1/1 → ixia06:1/13 (400G)
#   eth1/2/1 → ixia06:1/14 (400G)
#   eth1/3/1 → ixia06:1/19 (400G)
#   eth1/4/1 → ixia06:1/20 (400G)
#
# Interface IPs assigned via COOP configure_vlans patcher:
#   eth1/1/1: 2401:db00:2066:5001::a/64  IXIA: ::b
#   eth1/2/1: 2401:db00:2066:5002::a/64  IXIA: ::b
#   eth1/3/1: 2401:db00:2066:5003::a/64  IXIA: ::b
#   eth1/4/1: 2401:db00:2066:5004::a/64  IXIA: ::b
# ============================================================

DEVICE_NAME = "rtsw001.c085.f00.ash6"
DEVICE_FQDN = "rtsw001.c085.f00.ash6.tfbnw.net"
IXIA_CHASSIS_IP = "2401:db00:2066:3037::3006"

IXIA_PORTS = ["eth1/1/1", "eth1/2/1", "eth1/3/1", "eth1/4/1"]

DIRECT_IXIA_CONNECTIONS = [
    taac_types.DirectIxiaConnection(
        interface="eth1/1/1",
        ixia_chassis_ip=IXIA_CHASSIS_IP,
        ixia_port="1/13",
    ),
    taac_types.DirectIxiaConnection(
        interface="eth1/2/1",
        ixia_chassis_ip=IXIA_CHASSIS_IP,
        ixia_port="1/14",
    ),
    taac_types.DirectIxiaConnection(
        interface="eth1/3/1",
        ixia_chassis_ip=IXIA_CHASSIS_IP,
        ixia_port="1/19",
    ),
    taac_types.DirectIxiaConnection(
        interface="eth1/4/1",
        ixia_chassis_ip=IXIA_CHASSIS_IP,
        ixia_port="1/20",
    ),
]

ENDPOINTS = [
    taac_types.Endpoint(
        name=DEVICE_NAME,
        dut=True,
        ixia_needed=True,
        ixia_ports=IXIA_PORTS,
        direct_ixia_connections=DIRECT_IXIA_CONNECTIONS,
    ),
]

SRC_TRAFFIC_ENDPOINTS_PAIR1 = [
    TrafficEndpoint(name=f"{DEVICE_NAME}:eth1/1/1"),
]
DST_TRAFFIC_ENDPOINTS_PAIR1 = [
    TrafficEndpoint(name=f"{DEVICE_NAME}:eth1/4/1"),
]
SRC_TRAFFIC_ENDPOINTS_PAIR2 = [
    TrafficEndpoint(name=f"{DEVICE_NAME}:eth1/2/1"),
]
DST_TRAFFIC_ENDPOINTS_PAIR2 = [
    TrafficEndpoint(name=f"{DEVICE_NAME}:eth1/3/1"),
]

# ============================================================
# Interface IP addressing
# ============================================================

PORT_CONFIG = {
    "eth1/1/1": {
        "switch_ip": "2401:db00:2066:5001::a",
        "ixia_ip": "2401:db00:2066:5001::b",
        "prefix_length": 64,
        "ixia_as": 65101,
        "bgp_prefix": "5000:1::",
    },
    "eth1/2/1": {
        "switch_ip": "2401:db00:2066:5002::a",
        "ixia_ip": "2401:db00:2066:5002::b",
        "prefix_length": 64,
        "ixia_as": 65102,
        "bgp_prefix": "5000:2::",
    },
    "eth1/3/1": {
        "switch_ip": "2401:db00:2066:5003::a",
        "ixia_ip": "2401:db00:2066:5003::b",
        "prefix_length": 64,
        "ixia_as": 65103,
        "bgp_prefix": "5000:3::",
    },
    "eth1/4/1": {
        "switch_ip": "2401:db00:2066:5004::a",
        "ixia_ip": "2401:db00:2066:5004::b",
        "prefix_length": 64,
        "ixia_as": 65104,
        "bgp_prefix": "5000:4::",
    },
}

# ============================================================
# Setup Tasks — COOP patchers for EBGP with IXIA
# ============================================================

SETUP_TASKS = (
    [
        create_coop_unregister_patchers_task(DEVICE_NAME),
    ]
    + get_rtsw_ixia_peer_group_tasks(DEVICE_NAME)
    + [
        create_coop_apply_patchers_task(
            hostnames=[DEVICE_NAME],
            config_name="bgpcpp",
        ),
    ]
    + [
        create_configure_parallel_bgp_peers_task(
            hostname=DEVICE_NAME,
            configure_vlans_patcher_name=f"configure_vlans_ixia_{port.replace('/', '_')}",
            add_bgp_peers_patcher_name=f"add_bgp_peers_ixia_{port.replace('/', '_')}",
            config_json=json.dumps(
                {
                    port: [
                        {
                            "starting_ip": cfg["switch_ip"],
                            "increment_ip": "::",
                            "prefix_length": cfg["prefix_length"],
                            "description": f"IXIA EBGP (AS {cfg['ixia_as']})",
                            "peer_group_name": "PEERGROUP_RTSW_IXIA_V6",
                            "num_sessions": 1,
                            "remote_as_4_byte": cfg["ixia_as"],
                            "remote_as_4_byte_step": 0,
                            "gateway_starting_ip": cfg["ixia_ip"],
                            "gateway_increment_ip": "::",
                        },
                    ]
                }
            ),
        )
        for port, cfg in PORT_CONFIG.items()
    ]
    + [
        create_coop_apply_patchers_task(
            hostnames=[DEVICE_NAME],
            do_warmboot=True,
        ),
    ]
)

TEARDOWN_TASKS = [
    create_coop_unregister_patchers_task(DEVICE_NAME),
]

# ============================================================
# IXIA Port Configs (IXIA-side BGP)
# ============================================================

BASIC_PORT_CONFIGS = [
    taac_types.BasicPortConfig(
        endpoint=f"{DEVICE_NAME}:{port}",
        device_group_configs=[
            taac_types.DeviceGroupConfig(
                device_group_index=0,
                v6_addresses_config=taac_types.IpAddressesConfig(
                    starting_ip=str(cfg["ixia_ip"]),
                    increment_ip="::",
                    gateway_starting_ip=str(cfg["switch_ip"]),
                    gateway_increment_ip="::",
                    mask=int(cfg["prefix_length"]),
                ),
                v6_bgp_config=taac_types.BgpConfig(
                    local_as_4_bytes=int(cfg["ixia_as"]),
                    enable_4_byte_local_as=True,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                    route_scales=[
                        taac_types.RouteScaleSpec(
                            v6_route_scale=taac_types.RouteScale(
                                multiplier=1,
                                prefix_count=100,
                                prefix_length=64,
                                starting_prefixes=str(cfg["bgp_prefix"]),
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                            ),
                        )
                    ],
                    graceful_restart_timer=180,
                ),
            )
        ],
    )
    for port, cfg in PORT_CONFIG.items()
]

# ============================================================
# Traffic Items — two bidirectional pairs to exercise all 4 ports
# ============================================================

TRAFFIC_ITEM_CONFIGS = [
    taac_types.BasicTrafficItemConfig(
        name="W400_ASH6_TRAFFIC_PAIR1",
        src_endpoints=SRC_TRAFFIC_ENDPOINTS_PAIR1,
        dest_endpoints=DST_TRAFFIC_ENDPOINTS_PAIR1,
        line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
        line_rate=50,
        traffic_type=ixia_types.TrafficType.IPV6,
        bidirectional=True,
    ),
    taac_types.BasicTrafficItemConfig(
        name="W400_ASH6_TRAFFIC_PAIR2",
        src_endpoints=SRC_TRAFFIC_ENDPOINTS_PAIR2,
        dest_endpoints=DST_TRAFFIC_ENDPOINTS_PAIR2,
        line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
        line_rate=50,
        traffic_type=ixia_types.TrafficType.IPV6,
        bidirectional=True,
    ),
]

# ============================================================
# Shared Health Checks (using factory functions)
# ============================================================

TRAFFIC_ITEM_NAMES = ["W400_ASH6_TRAFFIC_PAIR1", "W400_ASH6_TRAFFIC_PAIR2"]

IXIA_PACKET_LOSS_CHECK = create_ixia_packet_loss_check(
    thresholds=[
        hc_types.PacketLossThreshold(
            names=TRAFFIC_ITEM_NAMES,
            str_value="0",
            metric=hc_types.PacketLossMetric.PERCENTAGE,
        ),
    ]
)

IXIA_PACKET_LOSS_POSTCHECK_CLEAR_STATS = create_ixia_packet_loss_check(
    thresholds=[
        hc_types.PacketLossThreshold(
            names=TRAFFIC_ITEM_NAMES,
            str_value="0",
            metric=hc_types.PacketLossMetric.PERCENTAGE,
        ),
    ],
    clear_traffic_stats=True,
)

SYSTEMCTL_CHECK = create_systemctl_active_state_check()

PORT_SPEED_PARAMS = {"endpoints": {DEVICE_NAME: IXIA_PORTS}}

SNAPSHOT_CHECKS = [
    create_bgp_session_snapshot_check(),
    create_core_dumps_snapshot_check(),
    create_port_speed_snapshot_check(json_params=PORT_SPEED_PARAMS),
]

DISRUPTIVE_SNAPSHOT_CHECKS = [
    create_bgp_session_snapshot_check(skip_flap_check=True, skip_uptime_check=True),
    create_core_dumps_snapshot_check(),
    create_port_speed_snapshot_check(json_params=PORT_SPEED_PARAMS),
]

# ============================================================
# Hardening Test Configs — using playbook factories from playbook_definitions.py
# ============================================================

W400_ASH6_LONGEVITY_TEST_CONFIG = TestConfig(
    name="W400_ASH6_LONGEVITY_TEST_CONFIG",
    basset_pool="dne.test",
    endpoints=ENDPOINTS,
    basic_traffic_item_configs=TRAFFIC_ITEM_CONFIGS,
    basic_port_configs=BASIC_PORT_CONFIGS,
    setup_tasks=SETUP_TASKS,
    teardown_tasks=TEARDOWN_TASKS,
    playbooks=[
        create_w400_longevity_playbook(
            duration=240,
            packet_loss_check=IXIA_PACKET_LOSS_CHECK,
            traffic_items_to_start=TRAFFIC_ITEM_NAMES,
            snapshot_checks=SNAPSHOT_CHECKS,
        ),
    ],
)

W400_ASH6_AGENT_RESTART_TEST_CONFIG = TestConfig(
    name="W400_ASH6_AGENT_RESTART_TEST_CONFIG",
    basset_pool="dne.test",
    endpoints=ENDPOINTS,
    basic_traffic_item_configs=TRAFFIC_ITEM_CONFIGS,
    basic_port_configs=BASIC_PORT_CONFIGS,
    setup_tasks=SETUP_TASKS,
    teardown_tasks=TEARDOWN_TASKS,
    playbooks=[
        create_w400_agent_restart_playbook(
            packet_loss_check=IXIA_PACKET_LOSS_CHECK,
            systemctl_check=SYSTEMCTL_CHECK,
            traffic_items_to_start=TRAFFIC_ITEM_NAMES,
            snapshot_checks=DISRUPTIVE_SNAPSHOT_CHECKS,
        ),
    ],
)

W400_ASH6_COLDBOOT_TEST_CONFIG = TestConfig(
    name="W400_ASH6_COLDBOOT_TEST_CONFIG",
    basset_pool="dne.test",
    endpoints=ENDPOINTS,
    basic_traffic_item_configs=TRAFFIC_ITEM_CONFIGS,
    basic_port_configs=BASIC_PORT_CONFIGS,
    setup_tasks=SETUP_TASKS,
    teardown_tasks=TEARDOWN_TASKS,
    playbooks=[
        create_w400_coldboot_playbook(
            packet_loss_check_clear_stats=IXIA_PACKET_LOSS_POSTCHECK_CLEAR_STATS,
            packet_loss_check=IXIA_PACKET_LOSS_CHECK,
            systemctl_check=SYSTEMCTL_CHECK,
            traffic_items_to_start=TRAFFIC_ITEM_NAMES,
            snapshot_checks=DISRUPTIVE_SNAPSHOT_CHECKS,
        ),
    ],
)

W400_ASH6_AGENT_CRASH_TEST_CONFIG = TestConfig(
    name="W400_ASH6_AGENT_CRASH_TEST_CONFIG",
    basset_pool="dne.test",
    endpoints=ENDPOINTS,
    basic_traffic_item_configs=TRAFFIC_ITEM_CONFIGS,
    basic_port_configs=BASIC_PORT_CONFIGS,
    setup_tasks=SETUP_TASKS,
    teardown_tasks=TEARDOWN_TASKS,
    playbooks=[
        create_w400_agent_crash_playbook(
            packet_loss_check_clear_stats=IXIA_PACKET_LOSS_POSTCHECK_CLEAR_STATS,
            packet_loss_check=IXIA_PACKET_LOSS_CHECK,
            systemctl_check=SYSTEMCTL_CHECK,
            traffic_items_to_start=TRAFFIC_ITEM_NAMES,
            snapshot_checks=DISRUPTIVE_SNAPSHOT_CHECKS,
        ),
    ],
)

W400_ASH6_BGPD_RESTART_TEST_CONFIG = TestConfig(
    name="W400_ASH6_BGPD_RESTART_TEST_CONFIG",
    basset_pool="dne.test",
    endpoints=ENDPOINTS,
    basic_traffic_item_configs=TRAFFIC_ITEM_CONFIGS,
    basic_port_configs=BASIC_PORT_CONFIGS,
    setup_tasks=SETUP_TASKS,
    teardown_tasks=TEARDOWN_TASKS,
    playbooks=[
        create_w400_bgpd_restart_playbook(
            packet_loss_check=IXIA_PACKET_LOSS_CHECK,
            systemctl_check=SYSTEMCTL_CHECK,
            traffic_items_to_start=TRAFFIC_ITEM_NAMES,
            snapshot_checks=DISRUPTIVE_SNAPSHOT_CHECKS,
        ),
    ],
)

W400_ASH6_INTERFACE_FLAP_TEST_CONFIG = TestConfig(
    name="W400_ASH6_INTERFACE_FLAP_TEST_CONFIG",
    basset_pool="dne.test",
    endpoints=ENDPOINTS,
    basic_traffic_item_configs=TRAFFIC_ITEM_CONFIGS,
    basic_port_configs=BASIC_PORT_CONFIGS,
    setup_tasks=SETUP_TASKS,
    teardown_tasks=TEARDOWN_TASKS,
    playbooks=[
        create_w400_interface_flap_playbook(
            interfaces=IXIA_PORTS,
            device_name=DEVICE_NAME,
            packet_loss_check_clear_stats=IXIA_PACKET_LOSS_POSTCHECK_CLEAR_STATS,
            packet_loss_check=IXIA_PACKET_LOSS_CHECK,
            systemctl_check=SYSTEMCTL_CHECK,
            traffic_items_to_start=TRAFFIC_ITEM_NAMES,
            snapshot_checks=DISRUPTIVE_SNAPSHOT_CHECKS,
        ),
    ],
)

# ============================================================
# PFC Testing — 3:1 Incast Topology
# ============================================================

PFC_SRC_ENDPOINTS = [
    TrafficEndpoint(name=f"{DEVICE_NAME}:eth1/1/1"),
    TrafficEndpoint(name=f"{DEVICE_NAME}:eth1/2/1"),
    TrafficEndpoint(name=f"{DEVICE_NAME}:eth1/3/1"),
]

PFC_DST_ENDPOINTS = [
    TrafficEndpoint(name=f"{DEVICE_NAME}:eth1/4/1"),
]

PFC_ENDPOINTS = [
    taac_types.Endpoint(
        name=DEVICE_NAME,
        dut=True,
        ixia_needed=True,
        ixia_ports=IXIA_PORTS,
        direct_ixia_connections=DIRECT_IXIA_CONNECTIONS,
    ),
]

W400_ASH6_PFC_TEST_CONFIG = gen_pfc_functionality_test_generic_4port_configs(
    test_config_name="W400_ASH6_PFC_TEST_CONFIG",
    endpoints=PFC_ENDPOINTS,
    basset_pool="dne.test",
    src_endpoints=PFC_SRC_ENDPOINTS,
    dst_endpoints=PFC_DST_ENDPOINTS,
    port_speed=400,
    basic_port_configs=None,
    is_monitoring_lossless=False,
    traffic_item_headers_map={
        "RDMA": DSF_RDMA_IB_PACKET_HEADERS,
        "BE": DSF_BE_PACKET_HEADERS,
        "NC": DSF_NC_PACKET_HEADERS,
        "MONITORING": DSF_MONITORING_PACKET_HEADERS,
    },
)

# Append RDMA-only debug playbook with FBOSS counter clear before longevity.
# Used to debug T271053421 in_discards investigation — separates trial-traffic
# pollution from real test-traffic counter behavior. TestConfig is an immutable
# thrift-python struct, so we rebuild via the call-with-overrides pattern.
W400_ASH6_PFC_TEST_CONFIG = W400_ASH6_PFC_TEST_CONFIG(
    playbooks=list(W400_ASH6_PFC_TEST_CONFIG.playbooks)
    + [
        create_pfc_rdma_only_with_clear_counters_playbook(
            rdma_90pct_traffic_items_names=[
                "TEST_RDMA_TRAFFIC_90PCT_P1_TO_P4",
                "TEST_RDMA_TRAFFIC_90PCT_P2_TO_P4",
                "TEST_RDMA_TRAFFIC_90PCT_P3_TO_P4",
            ],
            src_endpoints=PFC_SRC_ENDPOINTS,
            dst_endpoints=PFC_DST_ENDPOINTS,
            traffic_duration=60,
        ),
    ],
)

W400_ASH6_TEST_CONFIGS = [
    W400_ASH6_LONGEVITY_TEST_CONFIG,
    W400_ASH6_AGENT_RESTART_TEST_CONFIG,
    W400_ASH6_COLDBOOT_TEST_CONFIG,
    W400_ASH6_AGENT_CRASH_TEST_CONFIG,
    W400_ASH6_BGPD_RESTART_TEST_CONFIG,
    W400_ASH6_INTERFACE_FLAP_TEST_CONFIG,
    W400_ASH6_PFC_TEST_CONFIG,
]
