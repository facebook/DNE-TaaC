# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""FBOSS_BGP_HARDENING_FAUU_UU002 — CICD_TC TestConfig.

CICD_TC conveyor node binding (per `scripts/triage/dne_taac_checker.py`).
Built from the centralized `test_config_for_1_ixia_bgp_and_fboss_platform_hardening_in_conveyor` factory.
"""

from taac.testconfigs.fboss_solution_tests.test_config_for_2_ixia_bgp_and_fboss_platform_hardening_in_conveyor import (
    test_config_for_1_ixia_bgp_and_fboss_platform_hardening_in_conveyor,
)

FBOSS_BGP_HARDENING_FAUU_UU002_TEST_CONFIG = (
    test_config_for_1_ixia_bgp_and_fboss_platform_hardening_in_conveyor(
        test_config_name="FBOSS_BGP_HARDENING_FAUU_UU002",
        device_name="fa003-uu002.qzd1",
        local_mac_address="b6:92:fe:9d:8d:e5",
        ixia_uplink_interface="eth6/13/1",
        peergroup_uplink_mimic_v6="PEERGROUP_FAUU_EB_V6",
        peergroup_uplink_mimic_v4="PEERGROUP_FAUU_EB_V4",
        route_map_uplink_ingress="PROPAGATE_FAUU_EB_IN",
        route_map_uplink_egress="PROPAGATE_FAUU_EB_OUT",
        ixia_uplink_ic_parent_network_v6="2401:db00:e50d:11:9",
        prefix_limit="75000",
        per_peer_max_route_limit="25000",
        uplink_peer_count=8,
        remote_uplink_as_4byte=65272,
        is_uplink_peer_confed="False",
        ixia_uplink_prefix_count_v6=25000,
        ixia_uplink_communities=[
            "65441:133",
            "65442:135",
            "65526:35724",
        ],
        uplink_peer_tag="EB",
        basset_pool="dne.regression",
        v6_uplink_prefix="6000",
    )
)
