# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
Hyperport VRF BAG Test Configuration

This module provides configuration for testing Hyperport BAG with per-VRF
traffic routing. Source ports (Ethernet5/9-12) are in vrf1 and destination
ports (Ethernet5/13-16) are in vrf2, each with unique prefixes to enable
individual 1:1 port-to-port traffic flows through the VRFs.

Static routes on bag001:
  vrf1:  ipv6 route 4000:3:1::/48 2401:db00:11b:d8a1::91
  vrf2:  ipv6 route vrf dest_bag 4000:3:2::/48 2401:db00:11b:d8a1::99

All sub-prefixes fall within the /48 supernets so no static route changes
are needed.
"""

from ixia.ixia import types as ixia_types
from taac.health_checks.healthcheck_definitions import (
    create_core_dumps_snapshot_check,
    create_drain_state_check,
    create_ixia_packet_loss_check,
    create_unclean_exit_check,
)
from taac.playbooks.playbook_definitions import (
    create_dsf_proto_ipv6_traffic_config,
    create_hyperport_vrf_bag_longevity_playbook,
    create_pfc_pause_traffic_config,
    create_playbook_pfc_congestion,
    create_playbook_pfc_congestion_non_pfc_traffic,
    create_playbook_pfc_non_congestion,
    create_playbook_wd,
    get_pfc_wd_params,
    IXIA_ENABLE_PFC_PORT_CONFIG,
)
from taac.testconfigs.hyperport.hyperport_snc_bag_test_configs import (
    BAG_BGP_COMMUNITIES,
    create_basic_port_config,
    EDSW003_N000_PORT_CONFIG_DATA,
    EDSW003_N001_PORT_CONFIG_DATA,
    EDSW_BGP_COMMUNITIES,
    get_hyperport_bag_disruptive_playbooks,
    HYPERPORT_EDSW003_ENDPOINTS,
    N000_PORT_17_1_ENDPOINT,
    N000_PORT_23_1_ENDPOINT,
    N001_PORT_17_1_ENDPOINT,
    N001_PORT_23_1_ENDPOINT,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import (
    BasicTrafficItemConfig,
    Endpoint,
    Playbook,
    TestConfig,
    TrafficEndpoint,
)


# Source BAG Port Config Data: (port_name, ixia_ip, gateway_ip, starting_prefix)
VRF_BAG_SOURCE_PORT_CONFIG_DATA = [
    (
        "Ethernet5/9/1",
        "2401:db00:11b:d8a1::a1",
        "2401:db00:11b:d8a1::a0",
        "4000:3:2:1000::",
    ),
    (
        "Ethernet5/10/1",
        "2401:db00:11b:d8a1::a3",
        "2401:db00:11b:d8a1::a2",
        "4000:3:2:2000::",
    ),
    (
        "Ethernet5/11/1",
        "2401:db00:11b:d8a1::a5",
        "2401:db00:11b:d8a1::a4",
        "4000:3:2:3000::",
    ),
    (
        "Ethernet5/12/1",
        "2401:db00:11b:d8a1::a7",
        "2401:db00:11b:d8a1::a6",
        "4000:3:2:4000::",
    ),
]

# Destination BAG Port Config Data: (port_name, ixia_ip, gateway_ip, starting_prefix)

VRF_BAG_DEST_PORT_CONFIG_DATA = [
    (
        "Ethernet5/13/1",
        "2401:db00:11b:d8a1::a9",
        "2401:db00:11b:d8a1::a8",
        "4000:3:1:1000::",
    ),
    (
        "Ethernet5/14/1",
        "2401:db00:11b:d8a1::ab",
        "2401:db00:11b:d8a1::aa",
        "4000:3:1:2000::",
    ),
    (
        "Ethernet5/15/1",
        "2401:db00:11b:d8a1::ad",
        "2401:db00:11b:d8a1::ac",
        "4000:3:1:3000::",
    ),
    (
        "Ethernet5/16/1",
        "2401:db00:11b:d8a1::af",
        "2401:db00:11b:d8a1::ae",
        "4000:3:1:4000::",
    ),
]

# Combined BAG Port Config Data
VRF_BAG_PORT_CONFIG_DATA = (
    VRF_BAG_SOURCE_PORT_CONFIG_DATA + VRF_BAG_DEST_PORT_CONFIG_DATA
)

# Source BAG IXIA Ports
VRF_BAG_SOURCE_IXIA_PORTS = [port for port, _, _, _ in VRF_BAG_SOURCE_PORT_CONFIG_DATA]

# Destination BAG IXIA Ports
VRF_BAG_DEST_IXIA_PORTS = [port for port, _, _, _ in VRF_BAG_DEST_PORT_CONFIG_DATA]

# Combined BAG IXIA Ports
VRF_BAG_IXIA_PORTS = VRF_BAG_SOURCE_IXIA_PORTS + VRF_BAG_DEST_IXIA_PORTS

# EDSW003 IXIA Ports (reuse from parent config)
EDSW003_N000_IXIA_PORTS = [port for port, _, _, _ in EDSW003_N000_PORT_CONFIG_DATA]
EDSW003_N001_IXIA_PORTS = [port for port, _, _, _ in EDSW003_N001_PORT_CONFIG_DATA]

# VRF BAG Endpoint
VRF_BAG_ENDPOINTS = [
    Endpoint(
        name="bag001.snc1",
        dut=True,
        ixia_ports=VRF_BAG_IXIA_PORTS,
    ),
]

VRF_ALL_ENDPOINTS = HYPERPORT_EDSW003_ENDPOINTS + VRF_BAG_ENDPOINTS

# Individual Traffic Endpoints for Source BAG ports
BAG_SRC_PORT_9_ENDPOINT = TrafficEndpoint(
    name="bag001.snc1:Ethernet5/9/1",
    network_group_index=0,
    device_group_index=0,
)

BAG_SRC_PORT_10_ENDPOINT = TrafficEndpoint(
    name="bag001.snc1:Ethernet5/10/1",
    network_group_index=0,
    device_group_index=0,
)

BAG_SRC_PORT_11_ENDPOINT = TrafficEndpoint(
    name="bag001.snc1:Ethernet5/11/1",
    network_group_index=0,
    device_group_index=0,
)

BAG_SRC_PORT_12_ENDPOINT = TrafficEndpoint(
    name="bag001.snc1:Ethernet5/12/1",
    network_group_index=0,
    device_group_index=0,
)

# Individual Traffic Endpoints for Destination BAG ports
BAG_DEST_PORT_13_ENDPOINT = TrafficEndpoint(
    name="bag001.snc1:Ethernet5/13/1",
    network_group_index=0,
    device_group_index=0,
)

BAG_DEST_PORT_14_ENDPOINT = TrafficEndpoint(
    name="bag001.snc1:Ethernet5/14/1",
    network_group_index=0,
    device_group_index=0,
)

BAG_DEST_PORT_15_ENDPOINT = TrafficEndpoint(
    name="bag001.snc1:Ethernet5/15/1",
    network_group_index=0,
    device_group_index=0,
)

BAG_DEST_PORT_16_ENDPOINT = TrafficEndpoint(
    name="bag001.snc1:Ethernet5/16/1",
    network_group_index=0,
    device_group_index=0,
)

# 1:1 Port-to-Port Traffic Items (src -> dest via VRFs)
# Port 9 -> 13, Port 10 -> 14, Port 11 -> 15, Port 12 -> 16
VRF_BAG_PORT_PAIRS = [
    ("BGP_BAG_P9_TO_P13_99PCT", BAG_SRC_PORT_9_ENDPOINT, BAG_DEST_PORT_13_ENDPOINT),
    ("BGP_BAG_P10_TO_P14_99PCT", BAG_SRC_PORT_10_ENDPOINT, BAG_DEST_PORT_14_ENDPOINT),
    ("BGP_BAG_P11_TO_P15_99PCT", BAG_SRC_PORT_11_ENDPOINT, BAG_DEST_PORT_15_ENDPOINT),
    ("BGP_BAG_P12_TO_P16_99PCT", BAG_SRC_PORT_12_ENDPOINT, BAG_DEST_PORT_16_ENDPOINT),
]

VRF_BAG_TRAFFIC_ITEM_CONFIGS = [
    create_dsf_proto_ipv6_traffic_config(
        proto="RDMA_IB",
        src_endpoints=[BAG_SRC_PORT_9_ENDPOINT],
        dest_endpoints=[BAG_DEST_PORT_13_ENDPOINT],
        name="BGP_BAG_P9_TO_P13_99PCT",
        line_rate=99,
    ),
    create_dsf_proto_ipv6_traffic_config(
        proto="RDMA_IB",
        src_endpoints=[BAG_SRC_PORT_10_ENDPOINT],
        dest_endpoints=[BAG_DEST_PORT_14_ENDPOINT],
        name="BGP_BAG_P10_TO_P14_99PCT",
        line_rate=99,
    ),
    create_dsf_proto_ipv6_traffic_config(
        proto="RDMA_IB",
        src_endpoints=[BAG_SRC_PORT_11_ENDPOINT],
        dest_endpoints=[BAG_DEST_PORT_15_ENDPOINT],
        name="BGP_BAG_P11_TO_P15_99PCT",
        line_rate=99,
    ),
    create_dsf_proto_ipv6_traffic_config(
        proto="RDMA_IB",
        src_endpoints=[BAG_SRC_PORT_12_ENDPOINT],
        dest_endpoints=[BAG_DEST_PORT_16_ENDPOINT],
        name="BGP_BAG_P12_TO_P16_99PCT",
        line_rate=99,
    ),
]

# EDSW003 traffic items (same as original hyperport config)
VRF_EDSW_TRAFFIC_ITEM_CONFIGS = [
    BasicTrafficItemConfig(
        name="BGP_N000_17_TO_N001_17",
        bidirectional=True,
        merge_destinations=False,
        line_rate=99,
        frame_size_settings=ixia_types.FrameSize(
            type=ixia_types.FrameSizeType.RANDOM,
            random_min=64,
            random_max=9000,
        ),
        src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
        src_endpoints=[N000_PORT_17_1_ENDPOINT],
        dest_endpoints=[N001_PORT_17_1_ENDPOINT],
        traffic_type=ixia_types.TrafficType.IPV6,
        tracking_types=[
            ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM,
            ixia_types.TrafficStatsTrackingType.FLOW_GROUP,
        ],
    ),
    BasicTrafficItemConfig(
        name="BGP_N000_23_TO_N001_23",
        bidirectional=True,
        merge_destinations=False,
        line_rate=99,
        frame_size_settings=ixia_types.FrameSize(
            type=ixia_types.FrameSizeType.RANDOM,
            random_min=64,
            random_max=9000,
        ),
        src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
        src_endpoints=[N000_PORT_23_1_ENDPOINT],
        dest_endpoints=[N001_PORT_23_1_ENDPOINT],
        traffic_type=ixia_types.TrafficType.IPV6,
        tracking_types=[
            ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM,
            ixia_types.TrafficStatsTrackingType.FLOW_GROUP,
        ],
    ),
    BasicTrafficItemConfig(
        name="BGP_N000_23_TO_N001_17",
        bidirectional=True,
        merge_destinations=False,
        line_rate=99,
        frame_size_settings=ixia_types.FrameSize(
            type=ixia_types.FrameSizeType.RANDOM,
            random_min=64,
            random_max=9000,
        ),
        src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
        src_endpoints=[N000_PORT_23_1_ENDPOINT],
        dest_endpoints=[N001_PORT_17_1_ENDPOINT],
        traffic_type=ixia_types.TrafficType.IPV6,
        tracking_types=[
            ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM,
            ixia_types.TrafficStatsTrackingType.FLOW_GROUP,
        ],
    ),
    BasicTrafficItemConfig(
        name="BGP_N000_17_TO_N001_23",
        bidirectional=True,
        merge_destinations=False,
        line_rate=99,
        frame_size_settings=ixia_types.FrameSize(
            type=ixia_types.FrameSizeType.RANDOM,
            random_min=64,
            random_max=9000,
        ),
        src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
        src_endpoints=[N000_PORT_17_1_ENDPOINT],
        dest_endpoints=[N001_PORT_23_1_ENDPOINT],
        traffic_type=ixia_types.TrafficType.IPV6,
        tracking_types=[
            ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM,
            ixia_types.TrafficStatsTrackingType.FLOW_GROUP,
        ],
    ),
]

# EDSW003 BasicPortConfigs (reuse create_basic_port_config from parent)
VRF_EDSW003_N000_BASIC_PORT_CONFIGS = [
    create_basic_port_config(
        endpoint=f"edsw003.n000.l201.snc1:{port}",
        starting_ip=ixia_ip,
        gateway_ip=gateway_ip,
        local_as=65061,
        bgp_peer_type=ixia_types.BgpPeerType.IBGP,
        starting_prefixes=prefix,
        bgp_communities=EDSW_BGP_COMMUNITIES,
    )
    for port, ixia_ip, gateway_ip, prefix in EDSW003_N000_PORT_CONFIG_DATA
]

VRF_EDSW003_N001_BASIC_PORT_CONFIGS = [
    create_basic_port_config(
        endpoint=f"edsw003.n001.l201.snc1:{port}",
        starting_ip=ixia_ip,
        gateway_ip=gateway_ip,
        local_as=65062,
        bgp_peer_type=ixia_types.BgpPeerType.IBGP,
        starting_prefixes=prefix,
        bgp_communities=EDSW_BGP_COMMUNITIES,
    )
    for port, ixia_ip, gateway_ip, prefix in EDSW003_N001_PORT_CONFIG_DATA
]

VRF_EDSW003_BASIC_PORT_CONFIGS = (
    VRF_EDSW003_N000_BASIC_PORT_CONFIGS + VRF_EDSW003_N001_BASIC_PORT_CONFIGS
)

# Source BAG BasicPortConfigs (AS 65063, EBGP)
VRF_BAG_SOURCE_BASIC_PORT_CONFIGS = [
    create_basic_port_config(
        endpoint=f"bag001.snc1:{port}",
        starting_ip=ixia_ip,
        gateway_ip=gateway_ip,
        local_as=65063,
        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
        starting_prefixes=prefix,
        bgp_communities=BAG_BGP_COMMUNITIES,
        prefix_count=1000,
        l1_config=IXIA_ENABLE_PFC_PORT_CONFIG.l1_config,
    )
    for port, ixia_ip, gateway_ip, prefix in VRF_BAG_SOURCE_PORT_CONFIG_DATA
]

# Destination BAG BasicPortConfigs (AS 65063, EBGP)
VRF_BAG_DEST_BASIC_PORT_CONFIGS = [
    create_basic_port_config(
        endpoint=f"bag001.snc1:{port}",
        starting_ip=ixia_ip,
        gateway_ip=gateway_ip,
        local_as=65063,
        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
        starting_prefixes=prefix,
        bgp_communities=BAG_BGP_COMMUNITIES,
        prefix_count=1000,
        l1_config=IXIA_ENABLE_PFC_PORT_CONFIG.l1_config,
    )
    for port, ixia_ip, gateway_ip, prefix in VRF_BAG_DEST_PORT_CONFIG_DATA
]

# Combined BAG BasicPortConfigs
VRF_BAG_BASIC_PORT_CONFIGS = (
    VRF_BAG_SOURCE_BASIC_PORT_CONFIGS + VRF_BAG_DEST_BASIC_PORT_CONFIGS
)

# All BasicPortConfigs
VRF_ALL_BASIC_PORT_CONFIGS = VRF_BAG_BASIC_PORT_CONFIGS + VRF_EDSW003_BASIC_PORT_CONFIGS

# PFC source traffic endpoints (first 3 source ports for congestion testing)
VRF_PFC_SRC_ENDPOINTS = [
    BAG_SRC_PORT_9_ENDPOINT,
    BAG_SRC_PORT_10_ENDPOINT,
    BAG_SRC_PORT_11_ENDPOINT,
]

# PFC destination traffic endpoint (1 destination port to create congestion)
VRF_PFC_DST_ENDPOINTS = [BAG_DEST_PORT_13_ENDPOINT]

# All BAG source and destination endpoints for DSF traffic items
VRF_BAG_ALL_SRC_ENDPOINTS = [
    BAG_SRC_PORT_9_ENDPOINT,
    BAG_SRC_PORT_10_ENDPOINT,
    BAG_SRC_PORT_11_ENDPOINT,
    BAG_SRC_PORT_12_ENDPOINT,
]

VRF_BAG_ALL_DST_ENDPOINTS = [
    BAG_DEST_PORT_13_ENDPOINT,
    BAG_DEST_PORT_14_ENDPOINT,
    BAG_DEST_PORT_15_ENDPOINT,
    BAG_DEST_PORT_16_ENDPOINT,
]

# DSF traffic items at 70% line rate (NC, Monitoring, BE, RDMA with IB header)
VRF_DSF_TRAFFIC_ITEM_CONFIGS = [
    create_dsf_proto_ipv6_traffic_config(
        proto="NC",
        src_endpoints=VRF_BAG_ALL_SRC_ENDPOINTS,
        dest_endpoints=VRF_BAG_ALL_DST_ENDPOINTS,
        name="DSF_NC_70PCT",
        line_rate=70,
    ),
    create_dsf_proto_ipv6_traffic_config(
        proto="MONITORING",
        src_endpoints=VRF_BAG_ALL_SRC_ENDPOINTS,
        dest_endpoints=VRF_BAG_ALL_DST_ENDPOINTS,
        name="DSF_MONITORING_70PCT",
        line_rate=70,
    ),
    create_dsf_proto_ipv6_traffic_config(
        proto="BE",
        src_endpoints=VRF_BAG_ALL_SRC_ENDPOINTS,
        dest_endpoints=VRF_BAG_ALL_DST_ENDPOINTS,
        name="DSF_BE_70PCT",
        line_rate=70,
    ),
    create_dsf_proto_ipv6_traffic_config(
        proto="RDMA_IB",
        src_endpoints=VRF_BAG_ALL_SRC_ENDPOINTS,
        dest_endpoints=VRF_BAG_ALL_DST_ENDPOINTS,
        name="DSF_RDMA_IB_70PCT",
        line_rate=70,
    ),
]

# EDSW003 N000 to BAG cross-traffic items (ports 17,23 -> BAG ports 13,14)
VRF_EDSW_TO_BAG_TRAFFIC_ITEM_CONFIGS = [
    BasicTrafficItemConfig(
        name="BGP_N000_17_TO_BAG_13",
        bidirectional=True,
        merge_destinations=False,
        line_rate=99,
        frame_size_settings=ixia_types.FrameSize(
            type=ixia_types.FrameSizeType.RANDOM,
            random_min=64,
            random_max=9000,
        ),
        src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
        src_endpoints=[N000_PORT_17_1_ENDPOINT],
        dest_endpoints=[BAG_DEST_PORT_13_ENDPOINT],
        traffic_type=ixia_types.TrafficType.IPV6,
        tracking_types=[
            ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM,
            ixia_types.TrafficStatsTrackingType.FLOW_GROUP,
        ],
    ),
    BasicTrafficItemConfig(
        name="BGP_N000_17_TO_BAG_14",
        bidirectional=True,
        merge_destinations=False,
        line_rate=99,
        frame_size_settings=ixia_types.FrameSize(
            type=ixia_types.FrameSizeType.RANDOM,
            random_min=64,
            random_max=9000,
        ),
        src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
        src_endpoints=[N000_PORT_17_1_ENDPOINT],
        dest_endpoints=[BAG_DEST_PORT_14_ENDPOINT],
        traffic_type=ixia_types.TrafficType.IPV6,
        tracking_types=[
            ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM,
            ixia_types.TrafficStatsTrackingType.FLOW_GROUP,
        ],
    ),
    BasicTrafficItemConfig(
        name="BGP_N000_23_TO_BAG_13",
        bidirectional=True,
        merge_destinations=False,
        line_rate=99,
        frame_size_settings=ixia_types.FrameSize(
            type=ixia_types.FrameSizeType.RANDOM,
            random_min=64,
            random_max=9000,
        ),
        src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
        src_endpoints=[N000_PORT_23_1_ENDPOINT],
        dest_endpoints=[BAG_DEST_PORT_13_ENDPOINT],
        traffic_type=ixia_types.TrafficType.IPV6,
        tracking_types=[
            ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM,
            ixia_types.TrafficStatsTrackingType.FLOW_GROUP,
        ],
    ),
    BasicTrafficItemConfig(
        name="BGP_N000_23_TO_BAG_14",
        bidirectional=True,
        merge_destinations=False,
        line_rate=99,
        frame_size_settings=ixia_types.FrameSize(
            type=ixia_types.FrameSizeType.RANDOM,
            random_min=64,
            random_max=9000,
        ),
        src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
        src_endpoints=[N000_PORT_23_1_ENDPOINT],
        dest_endpoints=[BAG_DEST_PORT_14_ENDPOINT],
        traffic_type=ixia_types.TrafficType.IPV6,
        tracking_types=[
            ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM,
            ixia_types.TrafficStatsTrackingType.FLOW_GROUP,
        ],
    ),
]

# VRF BAG 100% line rate RDMA IB traffic items (same port pairs as VRF_BAG_TRAFFIC_ITEM_CONFIGS)
VRF_BAG_TRAFFIC_ITEM_CONFIGS_100PCT = [
    create_dsf_proto_ipv6_traffic_config(
        proto="RDMA_IB",
        src_endpoints=[BAG_SRC_PORT_9_ENDPOINT],
        dest_endpoints=[BAG_DEST_PORT_13_ENDPOINT],
        name="BGP_BAG_P9_TO_P13_100PCT",
        line_rate=100,
    ),
    create_dsf_proto_ipv6_traffic_config(
        proto="RDMA_IB",
        src_endpoints=[BAG_SRC_PORT_10_ENDPOINT],
        dest_endpoints=[BAG_DEST_PORT_14_ENDPOINT],
        name="BGP_BAG_P10_TO_P14_100PCT",
        line_rate=100,
    ),
    create_dsf_proto_ipv6_traffic_config(
        proto="RDMA_IB",
        src_endpoints=[BAG_SRC_PORT_11_ENDPOINT],
        dest_endpoints=[BAG_DEST_PORT_15_ENDPOINT],
        name="BGP_BAG_P11_TO_P15_100PCT",
        line_rate=100,
    ),
    create_dsf_proto_ipv6_traffic_config(
        proto="RDMA_IB",
        src_endpoints=[BAG_SRC_PORT_12_ENDPOINT],
        dest_endpoints=[BAG_DEST_PORT_16_ENDPOINT],
        name="BGP_BAG_P12_TO_P16_100PCT",
        line_rate=100,
    ),
]

# All traffic item configs
VRF_ALL_TRAFFIC_ITEM_CONFIGS = (
    VRF_EDSW_TRAFFIC_ITEM_CONFIGS
    + VRF_BAG_TRAFFIC_ITEM_CONFIGS
    + VRF_DSF_TRAFFIC_ITEM_CONFIGS
    + VRF_EDSW_TO_BAG_TRAFFIC_ITEM_CONFIGS
    + VRF_BAG_TRAFFIC_ITEM_CONFIGS_100PCT
)

VRF_TRAFFIC_ITEM_MAP = {
    "BGP_N000_17_TO_N001_17": "BGP_N000_17_TO_N001_17",
    "BGP_N000_23_TO_N001_23": "BGP_N000_23_TO_N001_23",
    "BGP_N000_23_TO_N001_17": "BGP_N000_23_TO_N001_17",
    "BGP_N000_17_TO_N001_23": "BGP_N000_17_TO_N001_23",
    "BGP_BAG_P9_TO_P13_99PCT": "BGP_BAG_P9_TO_P13_99PCT",
    "BGP_BAG_P10_TO_P14_99PCT": "BGP_BAG_P10_TO_P14_99PCT",
    "BGP_BAG_P11_TO_P15_99PCT": "BGP_BAG_P11_TO_P15_99PCT",
    "BGP_BAG_P12_TO_P16_99PCT": "BGP_BAG_P12_TO_P16_99PCT",
    "DSF_NC_70PCT": "DSF_NC_70PCT",
    "DSF_MONITORING_70PCT": "DSF_MONITORING_70PCT",
    "DSF_BE_70PCT": "DSF_BE_70PCT",
    "DSF_RDMA_IB_70PCT": "DSF_RDMA_IB_70PCT",
    "BGP_N000_17_TO_BAG_13": "BGP_N000_17_TO_BAG_13",
    "BGP_N000_17_TO_BAG_14": "BGP_N000_17_TO_BAG_14",
    "BGP_N000_23_TO_BAG_13": "BGP_N000_23_TO_BAG_13",
    "BGP_N000_23_TO_BAG_14": "BGP_N000_23_TO_BAG_14",
    "BGP_BAG_P9_TO_P13_100PCT": "BGP_BAG_P9_TO_P13_100PCT",
    "BGP_BAG_P10_TO_P14_100PCT": "BGP_BAG_P10_TO_P14_100PCT",
    "BGP_BAG_P11_TO_P15_100PCT": "BGP_BAG_P11_TO_P15_100PCT",
    "BGP_BAG_P12_TO_P16_100PCT": "BGP_BAG_P12_TO_P16_100PCT",
}


def get_vrf_bag_pfc_playbooks(
    port_speed: int = 800,
    traffic_duration: int = 60,
) -> tuple[list[Playbook], list[taac_types.BasicTrafficItemConfig]]:
    """
    Generate PFC test playbooks and traffic configs for Hyperport VRF BAG testing.

    Uses 3 source BAG ports (Ethernet5/9-11) sending to 1 destination BAG port
    (Ethernet5/13) to create congestion scenarios. Also includes a 4th source
    port (Ethernet5/12) reused as the first source for PFC watchdog testing.

    The PFC playbooks include:
    - PFC congestion: Equal slowdown with multiple RDMA streams
    - PFC non-congestion: No PFC frames with single stream below capacity
    - PFC congestion with non-PFC traffic: Lossless RDMA + lossy BE mix
    - PFC watchdog (high-rate): Watchdog should kick in
    - PFC watchdog (transient): Watchdog should not kick in at lower rate
    - PFC watchdog non-impact on TC1: PFC pause storm should not affect BE

    Args:
        port_speed: Port speed in Gbps (400 or 800)
        traffic_duration: Duration in seconds for congestion test traffic

    Returns:
        Tuple of (playbooks list, pfc traffic item configs list)
    """
    wd_params = get_pfc_wd_params(port_speed)
    pfc_pause_frame_rates = wd_params["pfc_pause_frame_rates"]

    # Source endpoints for PFC: first 3 for congestion, 4th reused as first for WD
    src_endpoints = list(VRF_PFC_SRC_ENDPOINTS)
    dst_endpoints = list(VRF_PFC_DST_ENDPOINTS)

    # Create RDMA traffic items: 3x 90% line rate for congestion
    rdma_90pct_traffic_items_names = []
    pfc_traffic_item_configs = []
    for i, src_endpoint in enumerate(src_endpoints, 1):
        name = f"TEST_RDMA_TRAFFIC_90PCT_P{i}_TO_P4"
        pfc_traffic_item_configs.append(
            create_dsf_proto_ipv6_traffic_config(
                proto="RDMA",
                src_endpoints=[src_endpoint],
                dest_endpoints=dst_endpoints,
                name=name,
                line_rate=90,
            )
        )
        rdma_90pct_traffic_items_names.append(name)

    # Create RDMA traffic items: 3x 30% line rate for non-congestion/mixed tests
    rdma_30pct_traffic_items_names = []
    for i, src_endpoint in enumerate(src_endpoints, 1):
        name = f"TEST_RDMA_TRAFFIC_30PCT_P{i}_TO_P4"
        pfc_traffic_item_configs.append(
            create_dsf_proto_ipv6_traffic_config(
                proto="RDMA",
                src_endpoints=[src_endpoint],
                dest_endpoints=dst_endpoints,
                name=name,
                line_rate=30,
            )
        )
        rdma_30pct_traffic_items_names.append(name)

    # Create BE 24% line rate traffic from a single source port
    be_traffic_item_name = "TEST_BE_24_TRAFFIC"
    pfc_traffic_item_configs.append(
        create_dsf_proto_ipv6_traffic_config(
            proto="BE",
            src_endpoints=[src_endpoints[1]],
            dest_endpoints=dst_endpoints,
            name=be_traffic_item_name,
            line_rate=24,
        )
    )

    # Create PFC pause traffic configs for watchdog testing
    for fr in pfc_pause_frame_rates:
        pfc_traffic_item_configs.append(
            create_pfc_pause_traffic_config(
                src_endpoints=src_endpoints[:1],
                dest_endpoints=dst_endpoints,
                name=f"TRAFFIC_TC2_PFC_PAUSE_{fr}FPS",
                line_rate=fr,
            )
        )

    # Build PFC playbooks
    playbooks = [
        # PFC congestion: equal slowdown with 3x RDMA 90% streams
        create_playbook_pfc_congestion(
            name="test_pfc_functionality_congestion_and_voq_credit_fairness",
            rdma_traffic_items_names=rdma_90pct_traffic_items_names,
            src_endpoints=src_endpoints,
            dst_endpoints=dst_endpoints,
            traffic_duration=traffic_duration,
        ),
        # PFC non-congestion: single RDMA 90% stream, no PFC expected
        create_playbook_pfc_non_congestion(
            name="test_pfc_functionality_non_congestion",
            rdma_traffic_items_names=rdma_90pct_traffic_items_names,
            src_endpoints=src_endpoints,
            dst_endpoints=dst_endpoints,
            traffic_duration=traffic_duration,
        ),
        # PFC congestion with non-PFC traffic: RDMA lossless + BE lossy mix
        create_playbook_pfc_congestion_non_pfc_traffic(
            name="test_pfc_functionality_congestion_non_tc2_traffic",
            pfc_traffic_items_names=rdma_30pct_traffic_items_names,
            be_traffic_item_name=be_traffic_item_name,
            src_endpoints=src_endpoints,
            dst_endpoints=dst_endpoints,
            traffic_duration=traffic_duration,
        ),
        # PFC watchdog: high-rate PFC pause should trigger watchdog
        create_playbook_wd(
            name="test_tc2_pfc_wd_functionality",
            description="Watchdog should kick in during high-rate PFC Pause traffic",
            interfaces_to_check=src_endpoints[:1],
            min_in_pfc_value=wd_params["wd_pfc_threshold_high"],
            wd_metric_comparison_type=hc_types.ComparisonType.GREATER_THAN,
            traffic_items_to_start=[wd_params["tc2_wd_traffic_item_high"]],
        ),
        # PFC watchdog transient: low-rate PFC pause should not trigger watchdog
        create_playbook_wd(
            name="test_tc2_pfc_wd_functionality_transient",
            description="Watchdog should not kick in during low-rate PFC Pause traffic",
            interfaces_to_check=src_endpoints[:1],
            min_in_pfc_value=wd_params["wd_pfc_threshold_low"],
            wd_metric_comparison_type=hc_types.ComparisonType.EQUAL_TO,
            traffic_items_to_start=[wd_params["tc2_wd_traffic_item_low"]],
        ),
        # PFC watchdog non-impact: PFC pause storm should not affect BE traffic
        create_playbook_wd(
            name="test_tc2_pfc_wd_functionality_non_impact_tc1",
            description="PFC Pause storm traffic should not impact TC1",
            interfaces_to_check=src_endpoints[:1],
            min_in_pfc_value=wd_params["wd_pfc_threshold_high"],
            wd_metric_comparison_type=hc_types.ComparisonType.GREATER_THAN,
            traffic_items_to_start=[
                wd_params["tc2_wd_traffic_item_high"],
                be_traffic_item_name,
            ],
            packetlosscheck=True,
        ),
    ]

    return playbooks, pfc_traffic_item_configs


def create_hyperport_vrf_bag_test_config(
    test_config_name: str = "HYPERPORT_VRF_BAG_TEST_CONFIGS",
    basset_pool: str = "networkai.test",
    longevity_duration: int = 360,
    port_speed: int = 800,
) -> TestConfig:
    """
    Create a test configuration for Hyperport VRF BAG testing.

    Uses unique per-port prefixes and 1:1 port-to-port traffic items
    to route traffic through two VRFs on bag001. Includes PFC congestion
    and watchdog playbooks using source BAG ports.

    Args:
        test_config_name: Name of the test configuration
        basset_pool: Basset pool name
        longevity_duration: Duration in seconds for longevity test
        port_speed: Port speed in Gbps (400 or 800) for PFC watchdog thresholds

    Returns:
        TestConfig: Complete test configuration
    """
    pfc_playbooks, pfc_traffic_item_configs = get_vrf_bag_pfc_playbooks(
        port_speed=port_speed,
    )

    # TC-level checks moved to playbook level
    _tc_prechecks = [
        create_drain_state_check(),
        create_ixia_packet_loss_check(
            thresholds=[hc_types.PacketLossThreshold(str_value="0.1")],
        ),
    ]
    _tc_postchecks = [
        create_ixia_packet_loss_check(
            thresholds=[
                hc_types.PacketLossThreshold(
                    str_value="0",
                    metric=hc_types.PacketLossMetric.PERCENTAGE,
                ),
            ],
            clear_traffic_stats=True,
        ),
        create_unclean_exit_check(),
    ]
    _tc_snapshot_checks = [create_core_dumps_snapshot_check()]

    # Add TC-level checks to generated disruptive playbooks
    _disruptive_playbooks = list(
        get_hyperport_bag_disruptive_playbooks(
            traffic_items_to_start=[
                VRF_TRAFFIC_ITEM_MAP["BGP_BAG_P9_TO_P13_99PCT"],
                VRF_TRAFFIC_ITEM_MAP["BGP_BAG_P10_TO_P14_99PCT"],
                VRF_TRAFFIC_ITEM_MAP["BGP_BAG_P11_TO_P15_99PCT"],
                VRF_TRAFFIC_ITEM_MAP["BGP_BAG_P12_TO_P16_99PCT"],
            ],
            device_regexes=["bag001.snc1"],
        )
    )
    _disruptive_playbooks = [
        _pb(
            prechecks=list(_pb.prechecks or []) + _tc_prechecks,
            postchecks=list(_pb.postchecks or []) + _tc_postchecks,
            snapshot_checks=list(_pb.snapshot_checks or []) + _tc_snapshot_checks,
        )
        for _pb in _disruptive_playbooks
    ]

    # Add TC-level checks to PFC playbooks
    pfc_playbooks = [
        _pb(
            prechecks=list(_pb.prechecks or []) + _tc_prechecks,
            postchecks=list(_pb.postchecks or []) + _tc_postchecks,
            snapshot_checks=list(_pb.snapshot_checks or []) + _tc_snapshot_checks,
        )
        for _pb in pfc_playbooks
    ]

    return TestConfig(
        name=test_config_name,
        basset_pool=basset_pool,
        endpoints=VRF_ALL_ENDPOINTS,
        setup_tasks=[],
        basic_port_configs=VRF_ALL_BASIC_PORT_CONFIGS,
        basic_traffic_item_configs=(
            VRF_ALL_TRAFFIC_ITEM_CONFIGS + pfc_traffic_item_configs
        ),
        # Deprecated - define at playbook level
        # postchecks (moved to each playbook)
        # Deprecated - define at playbook level
        # prechecks (moved to each playbook)
        # Deprecated - define at playbook level
        # snapshot_checks (moved to each playbook)
        playbooks=[
            create_hyperport_vrf_bag_longevity_playbook(
                traffic_items_to_start=[
                    VRF_TRAFFIC_ITEM_MAP["BGP_BAG_P9_TO_P13_99PCT"],
                    VRF_TRAFFIC_ITEM_MAP["BGP_BAG_P10_TO_P14_99PCT"],
                    VRF_TRAFFIC_ITEM_MAP["BGP_BAG_P11_TO_P15_99PCT"],
                    VRF_TRAFFIC_ITEM_MAP["BGP_BAG_P12_TO_P16_99PCT"],
                    VRF_TRAFFIC_ITEM_MAP["DSF_NC_70PCT"],
                    VRF_TRAFFIC_ITEM_MAP["DSF_MONITORING_70PCT"],
                    VRF_TRAFFIC_ITEM_MAP["DSF_BE_70PCT"],
                    VRF_TRAFFIC_ITEM_MAP["DSF_RDMA_IB_70PCT"],
                    VRF_TRAFFIC_ITEM_MAP["BGP_N000_17_TO_BAG_13"],
                    VRF_TRAFFIC_ITEM_MAP["BGP_N000_17_TO_BAG_14"],
                    VRF_TRAFFIC_ITEM_MAP["BGP_N000_23_TO_BAG_13"],
                    VRF_TRAFFIC_ITEM_MAP["BGP_N000_23_TO_BAG_14"],
                    VRF_TRAFFIC_ITEM_MAP["BGP_BAG_P9_TO_P13_100PCT"],
                    VRF_TRAFFIC_ITEM_MAP["BGP_BAG_P10_TO_P14_100PCT"],
                    VRF_TRAFFIC_ITEM_MAP["BGP_BAG_P11_TO_P15_100PCT"],
                    VRF_TRAFFIC_ITEM_MAP["BGP_BAG_P12_TO_P16_100PCT"],
                ],
                longevity_duration=longevity_duration,
                prechecks=_tc_prechecks,
                postchecks=_tc_postchecks,
                snapshot_checks=_tc_snapshot_checks,
            ),
            *_disruptive_playbooks,
            *pfc_playbooks,
        ],
    )


# Hyperport VRF BAG test configuration instance
HYPERPORT_VRF_BAG_TEST_CONFIGS = [create_hyperport_vrf_bag_test_config()]
