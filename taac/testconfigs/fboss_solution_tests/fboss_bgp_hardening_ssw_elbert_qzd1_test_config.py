# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""FBOSS_BGP_HARDENING_SSW_ELBERT_QZD1 — TestConfig.

Built from the centralized `test_config_for_2_ixia_bgp_and_fboss_platform_hardening_in_conveyor`
factory. Identities (peer-groups, route-maps, IXIA parent networks, ASNs, MAC) mirror the
`SSW_ELBERT_QZD1` physical inventory in
`abstractions/physical_inventory/routing_dcn_testbed.py`.

This dedicated binding opts into and selects only the requested BGP longevity
playbooks:

- `test_bgp_longevity_local_pref_churn`
- `test_bgp_longevity_bgpd_crash`
- `test_bgp_longevity_ndp_device_group_toggle`

The unrelated neighbor-uplink flap cases are intentionally excluded, so their
NetOS FSW peer is not part of this test topology and DUT health checks stay
scoped to the SSW under test.
"""

from taac.playbooks.playbook_definitions import (
    BGP_HARDENING_TIMING_PROFILES,
)
from taac.testconfigs.fboss_solution_tests.test_config_for_2_ixia_bgp_and_fboss_platform_hardening_in_conveyor import (
    test_config_for_2_ixia_bgp_and_fboss_platform_hardening_in_conveyor,
)

_NPI_TIMING = BGP_HARDENING_TIMING_PROFILES["npi"]

FBOSS_BGP_HARDENING_SSW_ELBERT_QZD1_TEST_CONFIG = (
    test_config_for_2_ixia_bgp_and_fboss_platform_hardening_in_conveyor(
        test_config_name="FBOSS_BGP_HARDENING_SSW_ELBERT_QZD1",
        device_name="ssw001.s002.f01.qzd1",
        local_mac_address="2a:e7:1d:21:b5:3b",
        ixia_downlink_interface="eth7/16/1",
        ixia_uplink_interface="eth8/16/1",
        peergroup_uplink_mimic_v6="PEERGROUP_SSW_FADU_V6",
        peergroup_uplink_mimic_v4="PEERGROUP_SSW_FADU_V4",
        peergroup_downlink_mimic_v6="PEERGROUP_SSW_FSW_V6",
        peergroup_downlink_mimic_v4="PEERGROUP_SSW_FSW_V4",
        peergroup_rogue_mimic_v6="PEERGROUP_SSW_FADU_V6",  # Setting Same as uplink
        route_map_uplink_ingress="PROPAGATE_SSW_FADU_IN",
        route_map_uplink_egress="PROPAGATE_SSW_FADU_OUT",
        route_map_downlink_ingress="PROPAGATE_SSW_FSW_IN",
        route_map_downlink_egress="PROPAGATE_SSW_FSW_OUT",
        route_map_rogue_ingress="PROPAGATE_SSW_FADU_IN",
        route_map_rogue_egress="PROPAGATE_SSW_FSW_OUT",
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
        is_rogue_peer_confed="False",  # Setting Same as uplink
        ixia_downlink_prefix_count_v6=10000,
        ixia_uplink_prefix_count_v6=10000,
        ixia_rogue_prefix_count_v6=17500,
        ixia_downlink_prefix_count_v4=7500,
        ixia_uplink_prefix_count_v4=7500,
        ixia_rogue_prefix_count_v4=17500,
        ixia_uplink_good_ndp_network="2401:db00:e50d:1101:9",
        ixia_downlink_good_ndp_network="2401:db00:e50d:1101:8",
        ixia_downlink_communities=[
            "65529:34814",
            "65441:131",
        ],
        ixia_uplink_communities=[
            "65441:261",
        ],
        downlink_peer_tag="FSW",
        uplink_peer_tag="FADU",
        ecmp_group_limit=1520,
        good_ndp_entries_uplink=200,
        good_ndp_entries_downlink=200,
        rogue_ndp_entries=200,
        good_arp_entries=500,
        rogue_arp_entries=1500,
        good_mac_entry_count=100,
        rogue_mac_entry_count=200,
        bgp_induced_ecmp_group_count=50,
        bgpd_restart_no_of_interations=5,
        wedge_agent_restart_no_of_interations=5,
        basset_pool="dne.regression",
        ecmp_member_limit=11500,
        include_bgp_longevity_playbooks=True,
        bgp_longevity_local_pref_cycles=_NPI_TIMING["local_pref_cycles"],
        bgp_longevity_local_pref_churn_interval_s=_NPI_TIMING[
            "local_pref_churn_interval_s"
        ],
        bgp_longevity_bgpd_crash_iterations=_NPI_TIMING["bgpd_crash_iterations"],
        bgp_longevity_bgpd_crash_recovery_wait_s=_NPI_TIMING[
            "bgpd_crash_recovery_wait_s"
        ],
        bgp_longevity_ndp_cycles=_NPI_TIMING["ndp_toggle_cycles"],
        bgp_longevity_ndp_uptime_s=_NPI_TIMING["ndp_uptime_s"],
        bgp_longevity_ndp_downtime_s=_NPI_TIMING["ndp_downtime_s"],
        playbooks_selected=[
            "test_bgp_longevity_local_pref_churn",
            "test_bgp_longevity_bgpd_crash",
            "test_bgp_longevity_ndp_device_group_toggle",
        ],
    )
)
