# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""NPI_48V_MINIPACK3_TEST_CONFIGS — TestConfig (dead-code preservation).

This constant lives in the shadowed `DCTYPEF_51T_NPI_TEST_CONFIGS` first-binding
at `internal_test_configs.py:6336`, which is overridden by the second binding
at line 7085. Per Option A (pure path-change refactor invariant), the constant
is migrated verbatim to preserve the original literal; cleanup of the dead
shadow assignment is a separate concern. Golden manifest unchanged (constant
was never reachable).

Built from the centralized `test_config_for_bgp_and_fboss_platform_hardening_in_conveyor`
factory.
"""

from taac.testconfigs.fboss_solution_tests.fboss_bgp_and_platform_hardening_conveyor import (
    test_config_for_bgp_and_fboss_platform_hardening_in_conveyor,
)

NPI_48V_MINIPACK3_TEST_CONFIG = (
    test_config_for_bgp_and_fboss_platform_hardening_in_conveyor(
        test_config_name="NPI_48V_MINIPACK3_TEST_CONFIGS",
        device_name="fsw002.p003.m001.qzr1",
        local_mac_address="c2:18:50:9c:1f:1d",
        ixia_downlink_interface="eth1/25/1",
        ixia_uplink_interface="eth1/28/1",
        peergroup_uplink_mimic_v6="PEERGROUP_FSW_SSW_V6",
        peergroup_uplink_mimic_v4="PEERGROUP_FSW_SSW_V4",
        peergroup_downlink_mimic_v6="PEERGROUP_FSW_RSW_V6",
        peergroup_downlink_mimic_v4="PEERGROUP_FSW_RSW_V4",
        peergroup_rogue_mimic_v6="PEERGROUP_FSW_SSW_V6",  # Setting Same as uplink
        peergroup_rogue_mimic_v4="PEERGROUP_FSW_SSW_V4",  # Setting Same as uplink
        route_map_uplink_ingress="PROPAGATE_FSW_SSW_IN",
        route_map_uplink_egress="PROPAGATE_FSW_SSW_OUT",
        route_map_downlink_ingress="PROPAGATE_FSW_RSW_IN",
        route_map_downlink_egress="PROPAGATE_FSW_RSW_OUT",
        route_map_rogue_ingress="PROPAGATE_FSW_SSW_IN",  # Setting Same as uplink
        route_map_rogue_egress="PROPAGATE_FSW_RSW_OUT",  # Setting Same as uplink
        ixia_downlink_ic_parent_network_v6="2401:db00:e50d:11:8",
        ixia_uplink_ic_parent_network_v6="2401:db00:e50d:11:9",
        ixia_rogue_ic_parent_network_v6="2401:db00:e50d:11:10",
        ixia_downlink_ic_parent_network_v4="10.163.28",
        ixia_uplink_ic_parent_network_v4="10.164.28",
        ixia_rogue_ic_parent_network_v4="10.165.28",
        good_ndp_entry_network_v6="2401:db00:e50d:1102:9",
        rogue_ndp_entry_network_v6="2401:db00:e50d:1102:8",
        good_arp_entry_network_v4="192.168",
        rogue_arp_entry_network_v4="193.168",
        prefix_limit="75000",
        per_peer_max_route_limit="25000",
        downlink_peer_count=36,
        uplink_peer_count=8,
        rogue_peer_count=8,
        remote_downlink_as_4byte=2000,
        remote_uplink_as_4byte=65000,
        remote_rogue_as_4byte=2500,
        is_uplink_peer_confed="False",
        is_downlink_peer_confed="True",
        is_rogue_peer_confed="False",  # Setting Same as uplink
        ixia_downlink_prefix_count_v6=10000,
        ixia_uplink_prefix_count_v6=25000,
        ixia_rogue_prefix_count_v6=7500,
        ixia_downlink_prefix_count_v4=7000,
        ixia_uplink_prefix_count_v4=15000,
        ixia_uplink_good_ndp_network="2401:db00:e50d:1101:9",
        ixia_downlink_good_ndp_network="2401:db00:e50d:1101:8",
        ixia_rogue_prefix_count_v4=7500,
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
        good_ndp_entries_uplink=2000,
        good_ndp_entries_downlink=200,
        rogue_ndp_entries=1000,
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
