# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""FBOSS_BGP_HARDENING_MINIPACK3 — CICD_TC TestConfig.

CICD_TC conveyor node binding (per `scripts/triage/dne_taac_checker.py`).
Built from the centralized `test_config_for_2_ixia_bgp_and_fboss_platform_hardening_in_conveyor` factory.
"""

from taac.testconfigs.fboss_solution_tests.test_config_for_2_ixia_bgp_and_fboss_platform_hardening_in_conveyor import (
    test_config_for_2_ixia_bgp_and_fboss_platform_hardening_in_conveyor,
)

FBOSS_BGP_HARDENING_MINIPACK3_TEST_CONFIG = (
    test_config_for_2_ixia_bgp_and_fboss_platform_hardening_in_conveyor(
        test_config_name="FBOSS_BGP_HARDENING_MINIPACK3",
        device_name="xsw003.x001.qzr1",
        local_mac_address="B6:DB:91:95:FE:2E",
        ixia_downlink_interface="eth1/63/1",
        ixia_uplink_interface="eth1/64/1",
        peergroup_uplink_mimic_v6="PEERGROUP_XSW_MA_V6",
        peergroup_uplink_mimic_v4="PEERGROUP_XSW_MA_V4",
        peergroup_rogue_mimic_v6="PEERGROUP_XSW_MA_V6",  # Setting Same as uplink
        peergroup_downlink_mimic_v6="PEERGROUP_XSW_SSW_V6",
        peergroup_downlink_mimic_v4="PEERGROUP_XSW_SSW_V4",
        route_map_uplink_ingress="PROPAGATE_XSW_MA_IN",
        route_map_uplink_egress="PROPAGATE_XSW_MA_OUT",
        route_map_downlink_ingress="PROPAGATE_XSW_SSW_IN",
        route_map_downlink_egress="PROPAGATE_XSW_SSW_OUT",
        route_map_rogue_ingress="PROPAGATE_XSW_MA_IN",  # Setting Same as uplink
        route_map_rogue_egress="PROPAGATE_XSW_SSW_OUT",  # Setting Same as uplink
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
        downlink_peer_count=36,
        uplink_peer_count=8,
        rogue_peer_count=50,
        remote_downlink_as_4byte=7001,
        remote_uplink_as_4byte=65272,
        remote_rogue_as_4byte=7001,
        is_uplink_peer_confed="False",
        is_downlink_peer_confed="False",
        is_rogue_peer_confed="False",  # Setting Same as uplink
        ixia_downlink_prefix_count_v6=5000,
        ixia_uplink_prefix_count_v6=25000,
        ixia_rogue_prefix_count_v6=7500,
        ixia_downlink_prefix_count_v4=7000,
        ixia_uplink_prefix_count_v4=15000,
        ixia_rogue_prefix_count_v4=7500,
        ixia_uplink_good_ndp_network="2401:db00:e50d:1101:9",
        ixia_downlink_good_ndp_network="2401:db00:e50d:1101:8",
        ixia_downlink_communities=[
            "65529:34814",
            "65441:131",
            "65446:201",
            "65441:15108",
        ],
        ixia_uplink_communities=[
            "65441:15556",
            "65441:261",
            "65441:15555",
        ],
        downlink_peer_tag="SSW",
        uplink_peer_tag="MA",
        ecmp_group_limit=1520,
        good_ndp_entries_uplink=3200,
        good_ndp_entries_downlink=200,
        rogue_ndp_entries=6000,
        good_arp_entries=500,
        rogue_arp_entries=1500,
        good_mac_entry_count=100,
        rogue_mac_entry_count=200,
        bgp_induced_ecmp_group_count=50,
        bgpd_restart_no_of_interations=5,
        wedge_agent_restart_no_of_interations=5,
        basset_pool="dne.test",
        ecmp_member_limit=11500,
    )
)
