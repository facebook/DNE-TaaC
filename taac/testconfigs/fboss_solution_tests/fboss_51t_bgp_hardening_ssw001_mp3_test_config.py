# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""FBOSS_51T_BGP_HARDENING_SSW001_MP3 — Non-CICD residue TestConfig.

Built from the centralized `test_config_for_bgp_and_fboss_platform_hardening_in_conveyor`
factory. Scale parameters preserve the original `SCALE_REDUCED_BGP_PATHS` values
from `internal_test_configs.py` verbatim (inlined at extraction time).
"""

from taac.testconfigs.fboss_solution_tests.fboss_bgp_and_platform_hardening_conveyor import (
    test_config_for_bgp_and_fboss_platform_hardening_in_conveyor,
)

FBOSS_51T_BGP_HARDENING_SSW001_MP3_TEST_CONFIG = (
    test_config_for_bgp_and_fboss_platform_hardening_in_conveyor(
        test_config_name="FBOSS_51T_BGP_HARDENING_SSW001_MP3",
        device_name="ssw001.s001.m001.qzr1",
        local_mac_address="B4:DB:91:95:FE:13",
        ixia_downlink_interface="eth1/63/1",
        ixia_uplink_interface="eth1/64/1",
        peergroup_uplink_mimic_v6="PEERGROUP_SSW_XSW_V6",
        peergroup_uplink_mimic_v4="PEERGROUP_SSW_XSW_V4",
        peergroup_downlink_mimic_v6="PEERGROUP_SSW_FSW_V6",
        peergroup_downlink_mimic_v4="PEERGROUP_SSW_FSW_V4",
        peergroup_rogue_mimic_v6="PEERGROUP_SSW_XSW_V6",  # Setting Same as uplink
        peergroup_rogue_mimic_v4="PEERGROUP_SSW_XSW_V4",  # Setting Same as uplink
        route_map_uplink_ingress="PROPAGATE_SSW_XSW_IN",
        route_map_uplink_egress="PROPAGATE_SSW_XSW_OUT",
        route_map_downlink_ingress="PROPAGATE_SSW_FSW_IN",
        route_map_downlink_egress="PROPAGATE_SSW_FSW_OUT",
        route_map_rogue_ingress="PROPAGATE_SSW_XSW_IN",  # Setting Same as uplink
        route_map_rogue_egress="PROPAGATE_SSW_XSW_OUT",  # Setting Same as uplink
        ixia_downlink_ic_parent_network_v6="2401:db00:e50d:12:8",
        ixia_uplink_ic_parent_network_v6="2401:db00:e50d:12:9",
        ixia_rogue_ic_parent_network_v6="2401:db00:e50d:12:10",
        ixia_downlink_ic_parent_network_v4="10.163.29",
        ixia_uplink_ic_parent_network_v4="10.164.29",
        ixia_rogue_ic_parent_network_v4="10.165.29",
        good_ndp_entry_network_v6="2401:db00:e50d:12:9",
        rogue_ndp_entry_network_v6="2401:db00:e50d:12:8",
        good_arp_entry_network_v4="192.168",
        rogue_arp_entry_network_v4="193.168",
        prefix_limit="75000",
        per_peer_max_route_limit="25000",
        downlink_peer_count=20,
        uplink_peer_count=20,
        rogue_peer_count=20,
        remote_downlink_as_4byte=7001,
        remote_uplink_as_4byte=65272,
        remote_rogue_as_4byte=7001,
        is_uplink_peer_confed="False",
        is_downlink_peer_confed="False",
        is_rogue_peer_confed="False",  # Setting Same as uplink
        ixia_downlink_prefix_count_v6=10000,
        ixia_uplink_prefix_count_v6=10000,
        ixia_rogue_prefix_count_v6=17500,
        ixia_downlink_prefix_count_v4=7500,
        ixia_uplink_prefix_count_v4=7500,
        ixia_rogue_prefix_count_v4=17500,
        ixia_uplink_good_ndp_network="2401:db00:e50d:1201:9",
        ixia_downlink_good_ndp_network="2401:db00:e50d:1201:8",
        ixia_downlink_communities=[
            "65529:34814",
            "65441:131",
            "65446:201",
        ],
        ixia_uplink_communities=[
            "65441:15556",
            "65441:261",
        ],
        downlink_peer_tag="FSW",
        uplink_peer_tag="XSW",
        ecmp_group_limit=50,
        ecmp_member_limit=500,
        ecmp_member_test_group_limit=50,
        ecmp_member_test_member_limit=500,
        good_ndp_entries_uplink=250,
        good_ndp_entries_downlink=200,
        rogue_ndp_entries=10000,
        good_arp_entries=500,
        rogue_arp_entries=1500,
        good_mac_entry_count=100,
        rogue_mac_entry_count=200,
        bgp_induced_ecmp_group_count=50,
        bgpd_restart_no_of_interations=5,
        wedge_agent_restart_no_of_interations=5,
        basset_pool="dne.test",
    )
)
