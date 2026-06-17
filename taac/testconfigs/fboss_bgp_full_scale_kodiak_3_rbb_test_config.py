# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""FBOSS_BGP_FULL_SCALE_KODIAK_3_RBB_TEST_CONFIG_QXS1.

Conveyor node binding (per `scripts/triage/dne_taac_checker.py`).

Built from the centralized `build_bgp_dc_test_config` factory. Scale parameters
preserve the original `SCALE_REDUCED_BGP_PATHS` values from `internal_test_configs.py`
verbatim (inlined at extraction time).
"""

from taac.testconfigs.fboss_solution_tests.fboss_wide_ecmp_test_config import (
    test_config_wide_ecmp,
)
from taac.testconfigs.internal.fboss_bgp_back_pressure_test_config import (
    test_config_back_pressure,
)
from taac.testconfigs.routing import build_bgp_dc_test_config


FBOSS_BGP_FULL_SCALE_KODIAK_3_RBB_TEST_CONFIG_QXS1 = build_bgp_dc_test_config(
    test_config_name="FBOSS_BGP_FULL_SCALE_KODIAK_3_RBB_TEST_CONFIG_QXS1",
    device_name="rb002-04.qxs1",
    local_mac_address="c2:18:50:9c:1f:1d",
    ixia_downlink_interface="eth1/64/1",
    ixia_uplink_interface="eth1/64/5",
    ixia_rogue_interface="eth9/16/1",
    peergroup_uplink_mimic_v6="PEERGROUP_RB_FADU_V6",
    peergroup_uplink_mimic_v4="PEERGROUP_RB_FADU_V4",
    peergroup_downlink_mimic_v6="PEERGROUP_RB_RB_V6",
    peergroup_downlink_mimic_v4="PEERGROUP_RB_RB_V4",
    peergroup_rogue_mimic_v6="PEERGROUP_RB_RB_V6",  # Setting Same as uplink
    peergroup_rogue_mimic_v4="PEERGROUP_RB_RB_V4",  # Setting Same as uplink
    route_map_uplink_ingress="PROPAGATE_EVERYTHING_PEERGROUP_RB_FADU_V6_IN",
    route_map_uplink_egress="PROPAGATE_EVERYTHING_PEERGROUP_RB_FADU_V6_OUT",
    route_map_downlink_ingress="PROPAGATE_RB_RB_IN",
    route_map_downlink_egress="PROPAGATE_RB_RB_OUT",
    route_map_rogue_ingress="PROPAGATE_RB_RB_IN",  # Setting Same as uplink
    route_map_rogue_egress="PROPAGATE_RB_RB_OUT",  # Setting Same as uplink
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
    ixia_downlink_prefix_count_v6=5000,  # 10000 original
    ixia_uplink_prefix_count_v6=5000,  # 10000 original
    ixia_rogue_prefix_count_v6=2500,  # 17500 original
    ixia_downlink_prefix_count_v4=5000,  # 7500 original
    ixia_uplink_prefix_count_v4=5000,  # 7500 original
    ixia_rogue_prefix_count_v4=2500,  # 17500 original
    ixia_uplink_good_ndp_network="2401:db00:e50d:1101:9",
    ixia_downlink_good_ndp_network="2401:db00:e50d:1101:8",
    ixia_downlink_communities=[
        "65441:66",
    ],
    ixia_uplink_communities=[
        "65441:201",
    ],
    downlink_peer_tag="RSW",
    uplink_peer_tag="SSW",
    ecmp_group_limit=200,
    good_ndp_entries_uplink=100,
    good_ndp_entries_downlink=100,
    rogue_ndp_entries=50,
    good_arp_entries=100,
    rogue_arp_entries=100,
    good_mac_entry_count=100,
    rogue_mac_entry_count=200,
    bgp_induced_ecmp_group_count=50,
    basset_pool="dne.test",
    ecmp_member_limit=5000,
    playbooks_selected=[
        "test_agent_restart",
        "test_bgp_restart",
        "test_bgpd_crash",
        "test_longevity_prefix_flap_all_prefixes",
        "test_longevity_activate_deactivate_all_prefixes",
        "test_longevity_session_flap_all_prefixes",
        "test_longevity_prefix_flap_all_prefixes_plus_bgp_restart",
        "test_longevity_session_flap_all_prefixes_plus_bgp_restart",
        "test_longevity_rogue_prefix_session_enable",
        "test_longevity_no_prefix_no_session_flap",
        "test_longevity_continuous_toggle_device_group",
        "test_longevity_cold_start_with_prefix_and_session_oscillations",
        "test_longevity_frequent_best_path_computation",
    ],
)

FBOSS_WIDE_ECMP_KODIAK_3_RBB_TEST_CONFIG_QXS1 = test_config_wide_ecmp(
    test_config_name="FBOSS_WIDE_ECMP_KODIAK_3_RBB_TEST_CONFIG_QXS1",
    device_name="rb002-03.qxs1",
    local_mac_address="c2:18:50:9c:1f:1d",
    ixia_uplink_interface="eth1/64/1",
    ixia_downlink_interface="eth1/64/5",
    # BGP peering
    peergroup_uplink_mimic_v6="PEERGROUP_RB_FADU_V6",
    peergroup_uplink_mimic_v4="PEERGROUP_RB_FADU_V4",
    peergroup_downlink_mimic_v6="PEERGROUP_RB_RB_V6",
    peergroup_downlink_mimic_v4="PEERGROUP_RB_RB_V4",
    route_map_uplink_ingress="PROPAGATE_EVERYTHING_PEERGROUP_RB_FADU_V6_IN",
    route_map_uplink_egress="PROPAGATE_EVERYTHING_PEERGROUP_RB_FADU_V6_OUT",
    route_map_downlink_ingress="PROPAGATE_RB_RB_IN",
    route_map_downlink_egress="PROPAGATE_RB_RB_OUT",
    uplink_peer_tag="SSW",
    downlink_peer_tag="RSW",
    # IP addressing
    ixia_uplink_ic_parent_network_v6="2401:db00:e50d:11:9",
    ixia_uplink_ic_parent_network_v4="10.164.28",
    ixia_downlink_ic_parent_network_v6="2401:db00:e50d:11:8",
    ixia_downlink_ic_parent_network_v4="10.163.28",
    # AS numbers
    remote_uplink_as_4byte=65271,
    remote_downlink_as_4byte=65409,
    is_uplink_peer_confed="False",
    is_downlink_peer_confed="False",
    # Communities, pool
    ixia_uplink_communities=[
        "65441:201",
    ],
    ixia_downlink_communities=[
        "65441:66",
    ],
    basset_pool="dne.test",
    # ECMP parameters
    max_ecmp_width_per_group=20,
    max_ecmp_member_count=10000,
    # Prefix address space
    v6_uplink_prefix="6000",
    v4_uplink_prefix="102",
    v6_downlink_prefix="3000",
    v4_downlink_prefix="101",
    # Peer route limits
    per_peer_max_route_limit="25000",
)


FBOSS_BGP_BACK_PRESSURE_KODIAK_3_RBB_TEST_CONFIG_QXS1 = test_config_back_pressure(
    test_config_name="FBOSS_BGP_BACK_PRESSURE_KODIAK_3_RBB_TEST_CONFIG_QXS1",
    device_name="rb002-03.qxs1",
    local_mac_address="c2:18:50:9c:1f:1d",
    ixia_uplink_interface="eth1/64/1",
    ixia_downlink_interface="eth1/64/5",
    # BGP peering
    peergroup_uplink_mimic_v6="PEERGROUP_RB_FADU_V6",
    peergroup_uplink_mimic_v4="PEERGROUP_RB_FADU_V4",
    peergroup_downlink_mimic_v6="PEERGROUP_RB_RB_V6",
    peergroup_downlink_mimic_v4="PEERGROUP_RB_RB_V4",
    route_map_uplink_ingress="PROPAGATE_EVERYTHING_PEERGROUP_RB_FADU_V6_IN",
    route_map_uplink_egress="PROPAGATE_EVERYTHING_PEERGROUP_RB_FADU_V6_OUT",
    route_map_downlink_ingress="PROPAGATE_RB_RB_IN",
    route_map_downlink_egress="PROPAGATE_RB_RB_OUT",
    uplink_peer_tag="SSW",
    downlink_peer_tag="RSW",
    # IP addressing
    ixia_uplink_ic_parent_network_v6="2401:db00:e50d:11:9",
    ixia_uplink_ic_parent_network_v4="10.164.28",
    ixia_downlink_ic_parent_network_v6="2401:db00:e50d:11:8",
    ixia_downlink_ic_parent_network_v4="10.163.28",
    # AS numbers
    remote_uplink_as_4byte=65271,
    remote_downlink_as_4byte=65409,
    is_uplink_peer_confed="False",
    is_downlink_peer_confed="False",
    # Communities, pool
    ixia_uplink_communities=[
        "65441:201",
    ],
    ixia_downlink_communities=[
        "65441:66",
    ],
    basset_pool="dne.test",
    # Prefix address space
    v6_uplink_prefix="6000",
    v4_uplink_prefix="102",
    v6_downlink_prefix="3000",
    v4_downlink_prefix="101",
    # Peer route limits
    per_peer_max_route_limit="50000",
    # Control/Experiment group sizing
    control_peer_count=5,
    experiment_peer_count=10,
    control_prefix_count_v6=500,
    control_prefix_count_v4=500,
    experiment_prefix_count_v6=1500,
    experiment_prefix_count_v4=500,
)
