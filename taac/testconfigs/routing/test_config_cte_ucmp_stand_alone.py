# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""
CTE UCMP Stand-Alone Test Configuration

Tests CTE-triggered UCMP weight changes via thrift API on fsw003.p003.f01.qzd1.

Topology:
=========
  DUT: fsw003.p003.f01.qzd1

  Uplink (eth7/16/1):
    - 1 IXIA device group (multiplier=1) as traffic source
    - eBGP peer (AS 65000), advertises source prefixes

  Downlink (eth8/16/1):
    - 3 device groups (DC1, DC2, DC3), each with 4 peers (multiplier=4)
    - Simulates 3 downlink switches, each with 4 links
    - All 3 DGs advertise the SAME VIP prefix pool (2402:db00:1100::/64)
    - Differentiated by AS_PATH prepending (DC1_ASN=50001, DC2_ASN=50002, DC3_ASN=50003)
    - Confed peers (AS 2000)

Test Flow:
==========
  Playbook 0 (Baseline ECMP Verification):
    - Verify all 12 BGP sessions are established
    - Verify ECMP works (all 12 nexthops weight 0, even traffic distribution)
    - Verify zero packet loss

  Playbook 1 (UCMP Random Weight Iterations, N=10):
    Each iteration cycles through 3 stages:
    - Stage 1 (Set): Generate random weights W1,W2,W3 (1-5) → thrift SET → verify RIB
    - Stage 2 (Delete + Re-set): thrift CLEAR → thrift SET same W1,W2,W3 → verify RIB
    - Stage 3 (Update): Generate NEW W4,W5,W6 → thrift SET (overwrite) → verify RIB
"""

import json

from ixia.ixia import types as ixia_types
from taac.playbooks.playbook_definitions import (
    create_baseline_ecmp_playbook,
    create_ucmp_iteration_playbook,
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

# ============================================================================
# Device & Topology Constants (from best_path_eval for fsw003.p003.f01.qzd1)
# ============================================================================

DEVICE_NAME = "fsw003.p003.f01.qzd1"
LOCAL_MAC_ADDRESS = "b6:a9:fc:34:2b:41"
IXIA_UPLINK_INTERFACE = "eth7/16/1"
IXIA_DOWNLINK_INTERFACE = "eth8/16/1"

# BGP peer groups and route maps
PEERGROUP_UPLINK_V6 = "PEERGROUP_FSW_SSW_V6"
PEERGROUP_DOWNLINK_V6 = "PEERGROUP_FSW_RSW_V6"
ROUTE_MAP_UPLINK_INGRESS = "PROPAGATE_FSW_SSW_IN"
ROUTE_MAP_UPLINK_EGRESS = "PROPAGATE_FSW_SSW_OUT"
ROUTE_MAP_DOWNLINK_INGRESS = "PROPAGATE_FSW_RSW_IN"
ROUTE_MAP_DOWNLINK_EGRESS = "PROPAGATE_FSW_RSW_OUT"
UPLINK_PEER_TAG = "SSW"
DOWNLINK_PEER_TAG = "RSW"

# IP addressing
IXIA_UPLINK_IC_PARENT_NETWORK_V6 = "2401:db00:e50d:11:9"
IXIA_DOWNLINK_IC_PARENT_NETWORK_V6 = "2401:db00:e50d:11:8"

# AS numbers
REMOTE_UPLINK_AS = 65000
REMOTE_DOWNLINK_AS = 2000
IS_UPLINK_PEER_CONFED = "False"
IS_DOWNLINK_PEER_CONFED = "True"

# Communities
IXIA_UPLINK_COMMUNITIES = [
    "65441:196",
    "65441:9001",
    "65441:9002",
    "65441:9003",
    "65441:9004",
    "65441:9005",
]
IXIA_DOWNLINK_COMMUNITIES = [
    "65441:194",
    "65441:260",  # VIP community — required for UCMP policy matching
    "65441:9001",
    "65441:9002",
    "65441:9003",
    "65441:9004",
    "65441:9005",
]

# Direct IXIA connections
DIRECT_IXIA_CONNECTIONS = [
    taac_types.DirectIxiaConnection(
        interface="eth7/16/1",
        ixia_chassis_ip="2401:db00:0116:303b:0000:0000:0000:0100",
        ixia_port="6/2",
    ),
    taac_types.DirectIxiaConnection(
        interface="eth8/16/1",
        ixia_chassis_ip="2401:db00:0116:303b:0000:0000:0000:0100",
        ixia_port="3/3",
    ),
]

# ============================================================================
# UCMP Test Constants
# ============================================================================

VIP_COMMUNITY = "65441:260"
VIP_V6 = "2402:db00:1100::/64"
VIP_V6_PREFIX = "2402:db00:1100"

DC1_ASN = 50001
DC2_ASN = 50002
DC3_ASN = 50003
DC_ASNS = [DC1_ASN, DC2_ASN, DC3_ASN]

PEERS_PER_DC = 4
TOTAL_DOWNLINK_PEERS = PEERS_PER_DC * len(DC_ASNS)  # 12
NUM_ITERATIONS = 10

PER_PEER_MAX_ROUTE_LIMIT = "10000"
PREFIX_COUNT_V6 = 1000


# ============================================================================
# Downlink Device Group Configs (3 DCs × 4 peers each)
# ============================================================================


def _create_downlink_device_groups() -> list[taac_types.DeviceGroupConfig]:
    """Create 3 downlink DGs, each with 4 peers, advertising same VIP prefix."""
    dgs = []
    for i, dc_asn in enumerate(DC_ASNS):
        # Each DG gets a separate IP range on the downlink subnet
        # DG0: starts at ::11, DG1: starts at ::19, DG2: starts at ::21
        ixia_start = 0x11 + i * (PEERS_PER_DC * 2)
        gw_start = 0x10 + i * (PEERS_PER_DC * 2)

        dgs.append(
            taac_types.DeviceGroupConfig(
                device_group_index=i,
                device_group_name=f"IXIA_DC{i + 1}_ADVERTISER",
                multiplier=PEERS_PER_DC,
                v6_addresses_config=taac_types.IpAddressesConfig(
                    starting_ip=f"{IXIA_DOWNLINK_IC_PARENT_NETWORK_V6}::{ixia_start:x}",
                    increment_ip="0:0:0:0::2",
                    gateway_starting_ip=f"{IXIA_DOWNLINK_IC_PARENT_NETWORK_V6}::{gw_start:x}",
                    gateway_increment_ip="0:0:0:0::2",
                    mask=127,
                ),
                v6_bgp_config=taac_types.BgpConfig(
                    local_as_4_bytes=REMOTE_DOWNLINK_AS + i * PEERS_PER_DC,
                    local_as_increment=1,
                    enable_4_byte_local_as=True,
                    is_confed=True,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                    route_scales=[
                        taac_types.RouteScaleSpec(
                            network_group_index=0,
                            multiplier=1,
                            v6_route_scale=taac_types.RouteScale(
                                prefix_name=f"VIP_V6_DC{i + 1}",
                                starting_prefixes=f"{VIP_V6_PREFIX}::",
                                prefix_length=64,
                                multiplier=1,
                                prefix_count=PREFIX_COUNT_V6,
                                prefix_step="0:0:0:0::",
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                bgp_communities=IXIA_DOWNLINK_COMMUNITIES,
                                as_path_prepend_numbers=[[dc_asn]],
                            ),
                        ),
                    ],
                ),
            )
        )
    return dgs


# ============================================================================
# Main TestConfig
# ============================================================================

CTE_UCMP_STAND_ALONE = TestConfig(
    name="CTE_UCMP_STAND_ALONE",
    skip_ixia_protocol_verification=True,
    basset_pool="dne.test",
    basset_reservation_time_hr=4,
    log_collection_timeout=180,
    endpoints=[
        taac_types.Endpoint(
            name=DEVICE_NAME,
            ixia_ports=[IXIA_UPLINK_INTERFACE, IXIA_DOWNLINK_INTERFACE],
            dut=True,
            mac_address=LOCAL_MAC_ADDRESS,
            direct_ixia_connections=DIRECT_IXIA_CONNECTIONS,
        ),
    ],
    # Deprecated - define at playbook level
    # prechecks - moved to playbook level
    # postchecks - moved to playbook level
    # snapshot_checks - moved to playbook level
    # ================================================================
    # Setup Tasks (COOP patchers from best_path_eval)
    # ================================================================
    setup_tasks=[
        # ---- Step 1: Clean slate ----
        create_coop_unregister_patchers_task(DEVICE_NAME),
        create_coop_apply_patchers_task(hostnames=[DEVICE_NAME]),
        create_wait_for_agent_convergence_task([DEVICE_NAME]),
        # ---- Step 2: Remove existing BGP peers ----
        create_coop_register_patcher_task(
            hostname=DEVICE_NAME,
            config_name="bgpcpp",
            patcher_name="a_remove_bgp_peers",
            task_name="coop_register_patcher",
            patcher_args={"delete_all": "True"},
            py_func_name="remove_bgp_peers",
        ),
        # ---- Step 3: Enable IXIA ports ----
        create_coop_register_patcher_task(
            hostname=DEVICE_NAME,
            config_name="agent",
            patcher_name="enable_port_all_ixia_ports",
            task_name="coop_register_patcher",
            patcher_args={
                IXIA_UPLINK_INTERFACE: "enable",
                IXIA_DOWNLINK_INTERFACE: "enable",
            },
            py_func_name="change_port_admin_state",
        ),
        # ---- Step 4: Update peer groups ----
        create_coop_register_patcher_task(
            hostname=DEVICE_NAME,
            config_name="bgpcpp",
            patcher_name="update_peer_group_patcher_V6_Downlink",
            task_name="coop_register_patcher",
            patcher_args={
                "name": PEERGROUP_DOWNLINK_V6,
                "attributes_to_update_json": json.dumps(
                    {
                        "disable_ipv4_afi": "True",
                        "v4_over_v6_nexthop": "False",
                        "is_passive": "False",
                        "is_confed_peer": IS_DOWNLINK_PEER_CONFED,
                        "max_routes": PER_PEER_MAX_ROUTE_LIMIT,
                    }
                ),
            },
            py_func_name="configure_bgp_peer_group",
        ),
        create_coop_register_patcher_task(
            hostname=DEVICE_NAME,
            config_name="bgpcpp",
            patcher_name=f"update_peer_group_patcher_{PEERGROUP_UPLINK_V6}_Uplink",
            task_name="coop_register_patcher",
            patcher_args={
                "name": PEERGROUP_UPLINK_V6,
                "attributes_to_update_json": json.dumps(
                    {
                        "disable_ipv4_afi": "True",
                        "v4_over_v6_nexthop": "False",
                        "is_passive": "False",
                        "is_confed_peer": IS_UPLINK_PEER_CONFED,
                        "max_routes": PER_PEER_MAX_ROUTE_LIMIT,
                    }
                ),
            },
            py_func_name="configure_bgp_peer_group",
        ),
        # ---- Step 5: Configure DUT VLANs and BGP peers ----
        # Uplink: 1 eBGP peer
        create_configure_parallel_bgp_peers_task(
            hostname=DEVICE_NAME,
            configure_vlans_patcher_name="configure_vlans_patcher_uplink",
            add_bgp_peers_patcher_name="add_bgp_peers_patcher_uplink",
            config_json=json.dumps(
                {
                    IXIA_UPLINK_INTERFACE: [
                        {
                            "starting_ip": f"{IXIA_UPLINK_IC_PARENT_NETWORK_V6}::10",
                            "increment_ip": "0:0:0:0::2",
                            "prefix_length": 127,
                            "description": "Uplink IPv6 Peer (EBGP)",
                            "peer_group_name": PEERGROUP_UPLINK_V6,
                            "num_sessions": 1,
                            "remote_as_4_byte": REMOTE_UPLINK_AS,
                            "remote_as_4_byte_step": 1,
                            "gateway_starting_ip": f"{IXIA_UPLINK_IC_PARENT_NETWORK_V6}::11",
                            "gateway_increment_ip": "0:0:0:0::2",
                        },
                    ],
                }
            ),
        ),
        # Downlink: 12 confed peers (3 DCs × 4 peers)
        create_configure_parallel_bgp_peers_task(
            hostname=DEVICE_NAME,
            configure_vlans_patcher_name="configure_vlans_patcher_downlink",
            add_bgp_peers_patcher_name="add_bgp_peers_patcher_downlink",
            config_json=json.dumps(
                {
                    IXIA_DOWNLINK_INTERFACE: [
                        {
                            "starting_ip": f"{IXIA_DOWNLINK_IC_PARENT_NETWORK_V6}::10",
                            "increment_ip": "0:0:0:0::2",
                            "prefix_length": 127,
                            "description": "Downlink IPv6 Peers (Confed, 3 DCs × 4 links)",
                            "peer_group_name": PEERGROUP_DOWNLINK_V6,
                            "num_sessions": TOTAL_DOWNLINK_PEERS,
                            "remote_as_4_byte": REMOTE_DOWNLINK_AS,
                            "remote_as_4_byte_step": 1,
                            "gateway_starting_ip": f"{IXIA_DOWNLINK_IC_PARENT_NETWORK_V6}::11",
                            "gateway_increment_ip": "0:0:0:0::2",
                        },
                    ],
                }
            ),
        ),
        # ---- Step 6: Apply all registered patchers ----
        create_coop_apply_patchers_task(hostnames=[DEVICE_NAME]),
        create_wait_for_agent_convergence_task([DEVICE_NAME]),
    ],
    # ================================================================
    # IXIA Port Configs
    # ================================================================
    basic_port_configs=[
        # ---- UPLINK PORT: Traffic source ----
        taac_types.BasicPortConfig(
            endpoint=f"{DEVICE_NAME}:{IXIA_UPLINK_INTERFACE}",
            device_group_configs=[
                taac_types.DeviceGroupConfig(
                    device_group_index=0,
                    multiplier=1,
                    v6_addresses_config=taac_types.IpAddressesConfig(
                        starting_ip=f"{IXIA_UPLINK_IC_PARENT_NETWORK_V6}::11",
                        increment_ip="0:0:0:0::2",
                        gateway_starting_ip=f"{IXIA_UPLINK_IC_PARENT_NETWORK_V6}::10",
                        gateway_increment_ip="0:0:0:0::2",
                        mask=127,
                    ),
                    v6_bgp_config=taac_types.BgpConfig(
                        local_as_4_bytes=REMOTE_UPLINK_AS,
                        local_as_increment=1,
                        enable_4_byte_local_as=True,
                        is_confed=False,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        route_scales=[
                            taac_types.RouteScaleSpec(
                                network_group_index=0,
                                multiplier=1,
                                v6_route_scale=taac_types.RouteScale(
                                    prefix_name="SOURCE_V6_UPLINK",
                                    starting_prefixes="2402:db00:1200::",
                                    prefix_length=64,
                                    multiplier=1,
                                    prefix_count=PREFIX_COUNT_V6,
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    bgp_communities=IXIA_UPLINK_COMMUNITIES,
                                ),
                            ),
                        ],
                    ),
                ),
            ],
        ),
        # ---- DOWNLINK PORT: 3 DCs × 4 peers ----
        taac_types.BasicPortConfig(
            endpoint=f"{DEVICE_NAME}:{IXIA_DOWNLINK_INTERFACE}",
            device_group_configs=_create_downlink_device_groups(),
        ),
    ],
    # ================================================================
    # Traffic Items
    # ================================================================
    basic_traffic_item_configs=[
        taac_types.BasicTrafficItemConfig(
            name="UCMP_STAND_ALONE_TRAFFIC",
            bidirectional=False,
            merge_destinations=True,
            line_rate=10,
            src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
            src_endpoints=[
                taac_types.TrafficEndpoint(
                    name=f"{DEVICE_NAME}:{IXIA_UPLINK_INTERFACE}",
                    device_group_index=0,
                    network_group_index=0,
                ),
            ],
            dest_endpoints=[
                taac_types.TrafficEndpoint(
                    name=f"{DEVICE_NAME}:{IXIA_DOWNLINK_INTERFACE}",
                    device_group_index=0,
                    network_group_index=0,
                ),
                taac_types.TrafficEndpoint(
                    name=f"{DEVICE_NAME}:{IXIA_DOWNLINK_INTERFACE}",
                    device_group_index=1,
                    network_group_index=0,
                ),
                taac_types.TrafficEndpoint(
                    name=f"{DEVICE_NAME}:{IXIA_DOWNLINK_INTERFACE}",
                    device_group_index=2,
                    network_group_index=0,
                ),
            ],
            traffic_type=ixia_types.TrafficType.IPV6,
            tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
        ),
    ],
    # ================================================================
    # Playbooks
    # ================================================================
    playbooks=[
        create_baseline_ecmp_playbook(),
        create_ucmp_iteration_playbook(),
    ],
)
