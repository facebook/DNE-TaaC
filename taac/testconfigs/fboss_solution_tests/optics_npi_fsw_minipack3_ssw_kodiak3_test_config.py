# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""OPTICS_NPI_FSW_MINIPACK3_SSW_KODIAK3 — CICD_TC TestConfig.

CICD_TC conveyor node binding (per `scripts/triage/dne_taac_checker.py`).
Built from the centralized `create_optics_npi_test_config` factory.
"""

from taac.testconfigs.fboss_solution_tests.fboss_optics_npi_test_config import (
    create_optics_npi_test_config,
)

OPTICS_NPI_FSW_MINIPACK3_SSW_KODIAK3_TEST_CONFIG = create_optics_npi_test_config(
    test_config_name="OPTICS_NPI_FSW_MINIPACK3_SSW_KODIAK3_TEST_CONFIGS",
    dut_device_name="fsw001.p002.m001.qzr1",
    dut_device_mac_address="c2:18:50:9c:1f:1d",
    ixia_connected_interface_in_dut="eth1/63/1",
    z_end_device_name="ssw001.s001.m001.qzr1",
    ixia_connected_interface_in_z_end_device="eth1/63/1",
    route_map_uplink_ingress="PROPAGATE_SSW_XSW_IN",
    route_map_uplink_egress="PROPAGATE_SSW_XSW_OUT",
    route_map_downlink_ingress="PROPAGATE_FSW_RSW_IN",
    route_map_downlink_egress="PROPAGATE_FSW_RSW_OUT",
    peergroup_uplink_mimic_v6="PEERGROUP_SSW_XSW_V6",
    peergroup_downlink_mimic_v6="PEERGROUP_FSW_RSW_V6",
    peergroup_uplink_mimic_v4="PEERGROUP_SSW_XSW_V4",
    peergroup_downlink_mimic_v4="PEERGROUP_FSW_RSW_V4",
    ixia_uplink_ic_parent_network_v6="2401:db00:e50d:11:9",
    ixia_downlink_ic_parent_network_v6="2401:db00:e50d:11:8",
    ixia_uplink_ic_parent_network_v4="10.164.28",
    ixia_downlink_ic_parent_network_v4="10.163.28",
    is_uplink_peer_confed="False",
    is_downlink_peer_confed="True",
    uplink_peer_tag="FADU",
    downlink_peer_tag="RSW",
    remote_uplink_as_4byte=65000,
    remote_downlink_as_4byte=2000,
    prefix_limit="70000",
    per_peer_max_route_limit="20000",
    downlink_peer_count=4,
    uplink_peer_count=4,
    ixia_uplink_prefix_count_v6=5000,
    ixia_downlink_prefix_count_v6=5000,
    ixia_uplink_prefix_count_v4=5000,
    ixia_downlink_prefix_count_v4=5000,
    ixia_uplink_communities=[
        "65441:10439",
    ],
    ixia_downlink_communities=[
        "65441:194",
        "65441:9001",
        "65441:9002",
        "65441:9003",
        "65441:9004",
        "65441:9005",
    ],
    basset_pool="dne.test",
)
