# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""NPI_51T_DVT_MP3_SSW_TEST_CONFIG — TestConfig.

Built from the centralized `create_dctypef_npi_test_config` factory.
Migrated from the inline `DCTYPEF_51T_NPI_TEST_CONFIGS` list in
`internal_test_configs.py` to its own module under `testconfigs/internal/`
to support the TAAC framework restructuring (one TestConfig per file).
"""

from taac.testconfigs.fboss_solution_tests.fboss_dctypef_51t_npi_test_config import (
    create_dctypef_npi_test_config,
)

NPI_51T_DVT_MP3_SSW_TEST_CONFIG = create_dctypef_npi_test_config(
    test_config_name="NPI_51T_DVT_TEST_CONFIG_MP3_SSW",
    device_name="ssw001.s001.m001.qzr1",
    local_mac_address="B4:DB:91:95:FE:13",
    ixia_downlink_interface="eth1/63/1",
    ixia_uplink_interface="eth1/64/1",
    ixia_rogue_interface="8/15/1",
    peergroup_uplink_mimic_v6="PEERGROUP_SSW_XSW_V6",
    peergroup_downlink_mimic_v6="PEERGROUP_SSW_FSW_V6",
    peergroup_uplink_mimic_v4="PEERGROUP_SSW_XSW_V4",
    peergroup_downlink_mimic_v4="PEERGROUP_SSW_FSW_V4",
    peergroup_rogue_mimic_v6="PEERGROUP_SSW_XSW_V6",  # Setting Same as uplink
    peergroup_rogue_mimic_v4="PEERGROUP_SSW_XSW_V4",  # Setting Same as uplink
    route_map_uplink_ingress="PROPAGATE_SSW_XSW_IN",
    route_map_uplink_egress="PROPAGATE_SSW_XSW_OUT",
    route_map_downlink_ingress="PROPAGATE_SSW_FSW_IN",
    route_map_downlink_egress="PROPAGATE_SSW_FSW_OUT",
    route_map_rogue_ingress="PROPAGATE_FSW_SSW_IN",  # Setting Same as uplink
    route_map_rogue_egress="PROPAGATE_FSW_SSW_OUT",  # Setting Same as uplink
    ixia_downlink_ic_parent_network_v6="2401:db00:e50d:11:8",
    ixia_uplink_ic_parent_network_v6="2401:db00:e50d:11:9",
    ixia_rogue_ic_parent_network_v6="2401:db00:e50d:11:10",
    ixia_downlink_ic_parent_network_v4="10.163.28",
    ixia_uplink_ic_parent_network_v4="10.164.28",
    ixia_rogue_ic_parent_network_v4="10.165.28",
    unique_prefix_limit="73000",
    per_peer_max_route_limit="20000",
    downlink_peer_count=32,
    uplink_peer_count=32,
    rogue_peer_count=8,
    remote_uplink_as_4byte=65272,
    remote_downlink_as_4byte=7001,
    remote_as_4_byte_step=1,
    remote_rogue_as_4byte=2500,
    is_uplink_peer_confed="False",
    is_downlink_peer_confed="True",
    is_rogue_peer_confed="False",  # Setting Same as uplink
    ixia_downlink_prefix_count_v6=5000,
    ixia_uplink_prefix_count_v6=5000,
    ixia_rogue_prefix_count_v6=7500,
    ixia_downlink_prefix_count_v4=5000,
    ixia_uplink_prefix_count_v4=5000,
    ixia_rogue_prefix_count_v4=7500,
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
    bgpd_restart_no_of_interations=5,
    wedge_agent_restart_no_of_interations=5,
    basset_pool="dne.test",
)
