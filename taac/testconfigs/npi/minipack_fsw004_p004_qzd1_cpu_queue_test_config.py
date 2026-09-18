# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""Minipack/Tomahawk3 CPU-queue qualification on fsw004.p004.f01.qzd1."""

from taac.testconfigs.npi.cpu_queue_test_config import (
    create_npi_cpu_queue_test_config,
)
from taac.testconfigs.npi.minipack_cpu_queue_constants import (
    MINIPACK_CPU_QUEUE_PLAYBOOKS,
)


MINIPACK_FSW004_P004_QZD1_CPU_QUEUE_TEST_CONFIG = create_npi_cpu_queue_test_config(
    test_config_name="MINIPACK_FSW004_P004_QZD1_CPU_QUEUE_TEST_CONFIG",
    device_name="fsw004.p004.f01.qzd1",
    local_mac_address="c2:18:50:99:93:41",
    ixia_downlink_interface="eth7/16/1",
    ixia_uplink_interface="eth9/16/1",
    ixia_rogue_interface="eth8/16/1",
    peergroup_uplink_mimic_v6="PEERGROUP_FSW_SSW_V6",
    peergroup_downlink_mimic_v6="PEERGROUP_FSW_RSW_V6",
    peergroup_uplink_mimic_v4="PEERGROUP_FSW_SSW_V4",
    peergroup_downlink_mimic_v4="PEERGROUP_FSW_RSW_V4",
    peergroup_rogue_mimic_v6="PEERGROUP_FSW_SSW_V6",
    peergroup_rogue_mimic_v4="PEERGROUP_FSW_SSW_V4",
    route_map_uplink_ingress="PROPAGATE_FSW_SSW_IN",
    route_map_uplink_egress="PROPAGATE_FSW_SSW_OUT",
    route_map_downlink_ingress="PROPAGATE_FSW_RSW_IN",
    route_map_downlink_egress="PROPAGATE_FSW_RSW_OUT",
    route_map_rogue_ingress="PROPAGATE_FSW_SSW_IN",
    route_map_rogue_egress="PROPAGATE_FSW_SSW_OUT",
    ixia_downlink_ic_parent_network_v6="2401:db00:e50d:11:8",
    ixia_uplink_ic_parent_network_v6="2401:db00:e50d:11:9",
    ixia_rogue_ic_parent_network_v6="2401:db00:e50d:11:10",
    ixia_downlink_ic_parent_network_v4="10.163.28",
    ixia_uplink_ic_parent_network_v4="10.164.29",
    ixia_rogue_ic_parent_network_v4="10.165.28",
    unique_prefix_limit="5000",
    per_peer_max_route_limit="20000",
    downlink_peer_count=8,
    uplink_peer_count=8,
    rogue_peer_count=0,
    remote_uplink_as_4byte=65000,
    remote_downlink_as_4byte=2000,
    remote_as_4_byte_step=1,
    remote_rogue_as_4byte=2500,
    is_uplink_peer_confed="False",
    is_downlink_peer_confed="True",
    is_rogue_peer_confed="False",
    ixia_downlink_prefix_count_v6=500,
    ixia_uplink_prefix_count_v6=500,
    ixia_rogue_prefix_count_v6=0,
    ixia_downlink_prefix_count_v4=500,
    ixia_uplink_prefix_count_v4=500,
    ixia_rogue_prefix_count_v4=0,
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
    uplink_peer_tag="SSW",
    downlink_peer_tag="RSW",
    basset_pool="dne.regression",
    low_queue=0,
    mid_queue=2,
    high_queue=9,
    playbooks_selected=MINIPACK_CPU_QUEUE_PLAYBOOKS,
    restore_soft_drain=True,
)


__all__ = ["MINIPACK_FSW004_P004_QZD1_CPU_QUEUE_TEST_CONFIG"]
