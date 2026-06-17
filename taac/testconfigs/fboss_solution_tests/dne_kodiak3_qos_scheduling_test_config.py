# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""DNE_KODIAK3_QOS_SCHEDULING_CICD_NODE — CICD_TC TestConfig.

CICD_TC conveyor node binding (per `scripts/triage/dne_taac_checker.py`).
Built from the centralized `test_config_qos_scheduling` factory.
"""

from taac.testconfigs.fboss_solution_tests.qos_scheduling_test_config import (
    test_config_qos_scheduling,
)


# Local SCALE_REDUCED_BGP_PATHS values (inlined from internal_test_configs.py)
# downlink_peer_count=20, uplink_peer_count=20, rogue_peer_count=20
# ixia_*_prefix_count_v6: down=10000, up=10000, rogue=17500
# ixia_*_prefix_count_v4: down=7500, up=7500, rogue=17500

# Kodiak3 rb002-01.qxt1 - QOS Scheduling CI/CD Node
DNE_KODIAK3_QOS_SCHEDULING_CICD_NODE_TEST_CONFIG = test_config_qos_scheduling(
    test_config_name="DNE_KODIAK3_QOS_SCHEDULING_CICD_NODE",
    device_name="rb002-01.qxt1",
    local_mac_address="b4:ca:dd:5a:84:45",
    ixia_downlink_interface="eth1/63/5",
    ixia_uplink_interface="eth1/64/1",
    ixia_rogue_interface="eth1/64/5",
    peergroup_uplink_mimic_v6="PEERGROUP_RB_RB_V6",
    peergroup_uplink_mimic_v4="PEERGROUP_RB_RB_V4",
    peergroup_downlink_mimic_v6="PEERGROUP_RB_XSW_V6",
    peergroup_downlink_mimic_v4="PEERGROUP_RB_XSW_V4",
    peergroup_rogue_mimic_v6="PEERGROUP_RB_RB_V6",  # Same as uplink
    peergroup_rogue_mimic_v4="PEERGROUP_RB_RB_V4",  # Same as uplink
    route_map_uplink_ingress="PROPAGATE_RB_RB_IN",
    route_map_uplink_egress="PROPAGATE_RB_RB_OUT",
    route_map_downlink_ingress="PROPAGATE_RB_XSW_IN",
    route_map_downlink_egress="PROPAGATE_RB_XSW_OUT",
    route_map_rogue_ingress="PROPAGATE_RB_RB_IN",  # Same as uplink
    route_map_rogue_egress="PROPAGATE_RB_XSW_OUT",  # Same as downlink
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
    downlink_peer_count=20,
    uplink_peer_count=20,
    rogue_peer_count=20,
    remote_downlink_as_4byte=65409,
    remote_uplink_as_4byte=65271,
    remote_rogue_as_4byte=2500,
    is_uplink_peer_confed="False",
    is_downlink_peer_confed="False",
    is_rogue_peer_confed="False",
    ixia_downlink_prefix_count_v6=10000,
    ixia_uplink_prefix_count_v6=10000,
    ixia_rogue_prefix_count_v6=17500,
    ixia_downlink_prefix_count_v4=7500,
    ixia_uplink_prefix_count_v4=7500,
    ixia_rogue_prefix_count_v4=17500,
    ixia_uplink_good_ndp_network="2401:db00:e50d:1101:9",
    ixia_downlink_good_ndp_network="2401:db00:e50d:1101:8",
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
    downlink_peer_tag="XSW",
    uplink_peer_tag="RB",
    ecmp_group_limit=1520,
    good_ndp_entries_uplink=250,
    good_ndp_entries_downlink=200,
    rogue_ndp_entries=10000,
    good_arp_entries=500,
    rogue_arp_entries=1500,
    good_mac_entry_count=100,
    rogue_mac_entry_count=200,
    bgp_induced_ecmp_group_count=50,
    basset_pool="dne.test",
    # Congestion port: reuse the rogue port for congestion traffic.
    ixia_congestion_interface="eth1/64/5",
    ixia_congestion_ic_parent_network_v6="2401:db00:e50d:11:10",
    congestion_peer_as_4byte=2500,
    congestion_prefix_count_v6=100,
    congestion_prefix_start_v6="2401:db00:e50d:1101:10::",
    is_congestion_peer_confed="False",
)
