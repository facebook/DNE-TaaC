# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
from ixia.ixia import types as ixia_types
from taac.packet_headers import DSF_RDMA_PACKET_HEADERS
from taac.test_as_a_config.types import (
    BasicPortConfig,
    BasicTrafficItemConfig,
    Endpoint,
    TrafficEndpoint,
)


TRAFFIC_ITEM_CONFIGS = []
TRAFFIC_ITEM_MAP = {}

DSF_FRAME_SIZES = ixia_types.FrameSize(
    type=ixia_types.FrameSizeType.CUSTOM_IMIX,
    imix_weight={94: 1, 96: 18, 192: 3, 512: 1, 1200: 1, 4600: 76},
)

IXIA_ENABLE_PFC_PORT_CONFIG = BasicPortConfig(
    l1_config=ixia_types.L1Config(
        enable_fcoe=True,
        flow_control_config=ixia_types.FlowControlConfig(
            pfc_prority_groups_config=ixia_types.PfcPriorityGroupsConfig(
                priority0_pfc_queue=ixia_types.PfcQueue.TWO,
                priority1_pfc_queue=ixia_types.PfcQueue.ONE,
                priority2_pfc_queue=ixia_types.PfcQueue.ZERO,
                priority3_pfc_queue=ixia_types.PfcQueue.THREE,
            ),
            enable_pfc_pause_delay=False,
        ),
    )
)

# SUSW <> IXIA Portmap
SUSW001_C083_IXIA_PORTS = [
    "eth1/1/1",
    "eth1/2/1",
    "eth1/7/1",
    "eth1/8/1",
]

SNC1_C083_SUSW001_ENDPOINTS = [
    Endpoint(
        name="susw001.c083.snc1",
        dut=True,
        ixia_needed=True,
        ixia_ports=SUSW001_C083_IXIA_PORTS,
    ),
]

SNC1_C083_SUSW001_TRAFFIC_ENDPOINTS = [
    TrafficEndpoint(
        name=f"susw001.c083.snc1:{port}",
    )
    for port in SUSW001_C083_IXIA_PORTS
]

TRAFFIC_ITEM_CONFIGS.append(
    BasicTrafficItemConfig(
        src_endpoints=SNC1_C083_SUSW001_TRAFFIC_ENDPOINTS,
        dest_endpoints=SNC1_C083_SUSW001_TRAFFIC_ENDPOINTS,
        traffic_type=ixia_types.TrafficType.IPV6,
        name="FULL_MESH_TRAFFIC_FOR_SUSW",
        line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
        line_rate=90,
        bidirectional=True,
        packet_headers=DSF_RDMA_PACKET_HEADERS,
        full_mesh=True,
        src_dest_mesh=ixia_types.SrcDestMeshType.FULL_MESH,
        frame_size_settings=DSF_FRAME_SIZES,
    )
)

TRAFFIC_ITEM_MAP["FULL_MESH_TRAFFIC_FOR_SUSW"] = "FULL_MESH_TRAFFIC_FOR_SUSW"
