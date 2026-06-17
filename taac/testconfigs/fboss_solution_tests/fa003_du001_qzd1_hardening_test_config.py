# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""FA003_DU001_QZD1_HARDENING — Non-CICD residue TestConfig.

Built from the centralized
`test_config_for_2_ixia_bgp_and_fboss_platform_hardening_in_conveyor` factory.
The original `test_config_name` string ("fa003_du001.qzd1_hardening") is preserved
verbatim so the golden manifest hash is unchanged.
"""

from taac.testconfigs.fboss_solution_tests.test_config_for_2_ixia_bgp_and_fboss_platform_hardening_in_conveyor import (
    test_config_for_2_ixia_bgp_and_fboss_platform_hardening_in_conveyor,
)

FA003_DU001_QZD1_HARDENING_TEST_CONFIG = (
    test_config_for_2_ixia_bgp_and_fboss_platform_hardening_in_conveyor(
        test_config_name="fa003_du001.qzd1_hardening",
        device_name="fa001-du003.qzd1",
        local_mac_address="3a:38:a6:ff:c3:6d",
        ixia_downlink_interface="eth6/16/1",
        ixia_uplink_interface="eth7/16/1",
        peergroup_uplink_mimic_v6="PEERGROUP_FADU_FAUU_V6",
        peergroup_uplink_mimic_v4="PEERGROUP_FADU_FAUU_V4",
        peergroup_rogue_mimic_v6="PEERGROUP_FADU_FAUU_V6",  # Setting Same as uplink
        peergroup_downlink_mimic_v6="PEERGROUP_FADU_SSW_V6",
        peergroup_downlink_mimic_v4="PEERGROUP_FADU_SSW_V4",
        route_map_uplink_ingress="PROPAGATE_FADU_FAUU_IN",
        route_map_uplink_egress="PROPAGATE_FADU_FAUU_OUT",
        route_map_downlink_ingress="PROPAGATE_FADU_SSW_IN",
        route_map_downlink_egress="PROPAGATE_FADU_SSW_OUT",
        route_map_rogue_ingress="PROPAGATE_FADU_FAUU_IN",  # Setting Same as uplink
        route_map_rogue_egress="PROPAGATE_FADU_SSW_OUT",  # Setting Same as uplink
        ixia_downlink_ic_parent_network_v6="2401:db00:e50d:10:8",
        ixia_uplink_ic_parent_network_v6="2401:db00:e50d:10:9",
        ixia_rogue_ic_parent_network_v6="2401:db00:e50d:10:10",
        ixia_downlink_ic_parent_network_v4="10.153.28",
        ixia_uplink_ic_parent_network_v4="10.154.28",
        ixia_rogue_ic_parent_network_v4="10.155.28",
        good_ndp_entry_network_v6="2401:db00:e50d:10:9",
        rogue_ndp_entry_network_v6="2401:db00:e50d:10:8",
        good_arp_entry_network_v4="192.168",
        rogue_arp_entry_network_v4="193.168",
        prefix_limit="75000",
        per_peer_max_route_limit="25000",
        downlink_peer_count=36,
        uplink_peer_count=8,
        rogue_peer_count=50,
        remote_downlink_as_4byte=64901,
        remote_uplink_as_4byte=7010,
        remote_rogue_as_4byte=64901,
        is_uplink_peer_confed="True",
        is_downlink_peer_confed="False",
        is_rogue_peer_confed="True",  # Setting Same as uplink
        ixia_downlink_prefix_count_v6=5000,
        ixia_uplink_prefix_count_v6=15000,
        ixia_rogue_prefix_count_v6=7500,
        ixia_downlink_prefix_count_v4=7000,
        ixia_uplink_prefix_count_v4=15000,
        ixia_rogue_prefix_count_v4=7500,
        ixia_uplink_good_ndp_network="2401:db00:e50d:1001:9",
        ixia_downlink_good_ndp_network="2401:db00:e50d:1001:8",
        ixia_downlink_communities=[
            "65441:132",
            "65442:133",
            "65529:26730",
        ],
        ixia_uplink_communities=[
            "65526:35724",
            "65441:134",
            "65442:135",
        ],
        downlink_peer_tag="SSW",
        uplink_peer_tag="FAUU",
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
        basset_pool="dne.regression",
        ecmp_member_limit=11500,
        v6_uplink_prefix="6100",
    )
)
