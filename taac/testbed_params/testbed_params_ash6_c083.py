# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
from ixia.ixia import types as ixia_types
from taac.test_as_a_config.types import (
    BasicPortConfig,
    BasicTrafficItemConfig,
    Endpoint,
    TrafficEndpoint,
)


TRAFFIC_ITEM_CONFIGS = []
TRAFFIC_ITEM_MAP = {}

from taac.packet_headers import DSF_RDMA_PACKET_HEADERS

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
RTSW001_L101_IXIA_PORTS = [
    "eth1/19/1",
    "eth1/19/5",
]
RTSW002_L101_IXIA_PORTS = [
    "eth1/19/1",
    "eth1/19/5",
]
RTSW003_L101_IXIA_PORTS = [
    "eth1/19/1",
    "eth1/19/5",
]

RTSW001_L102_IXIA_PORTS = [
    "eth1/1/1",
    "eth1/1/5",
]
RTSW002_L102_IXIA_PORTS = [
    "eth1/1/1",
    "eth1/1/5",
]
RTSW003_L102_IXIA_PORTS = [
    "eth1/1/1",
    "eth1/1/5",
]
ASH6_C083_NSF_END_POINTS = [
    Endpoint(
        name="rtsw001.l101.c083.ash6",
        ixia_ports=RTSW003_L101_IXIA_PORTS,
    ),
    Endpoint(
        name="rtsw002.l101.c083.ash6",
        ixia_ports=RTSW003_L101_IXIA_PORTS,
    ),
    Endpoint(
        name="rtsw003.l101.c083.ash6",
        ixia_ports=RTSW003_L101_IXIA_PORTS,
    ),
    Endpoint(
        name="rtsw001.l102.c083.ash6",
        dut=True,
        ixia_ports=RTSW001_L102_IXIA_PORTS,
    ),
    Endpoint(
        name="rtsw002.l102.c083.ash6",
        ixia_ports=RTSW002_L102_IXIA_PORTS,
    ),
    Endpoint(
        name="rtsw003.l102.c083.ash6",
        ixia_ports=RTSW003_L102_IXIA_PORTS,
    ),
]

ASH6_C083_NSF_FULL_MESH_TRAFFIC_ENDPOINTS = [
    TrafficEndpoint(
        name=f"rtsw001.l101.c083.ash6:{port}",
    )
    for port in RTSW001_L101_IXIA_PORTS
]
ASH6_C083_NSF_FULL_MESH_TRAFFIC_ENDPOINTS.extend(
    TrafficEndpoint(
        name=f"rtsw002.l101.c083.ash6:{port}",
    )
    for port in RTSW002_L101_IXIA_PORTS
)
ASH6_C083_NSF_FULL_MESH_TRAFFIC_ENDPOINTS.extend(
    TrafficEndpoint(
        name=f"rtsw003.l101.c083.ash6:{port}",
    )
    for port in RTSW003_L101_IXIA_PORTS
)
ASH6_C083_NSF_FULL_MESH_TRAFFIC_ENDPOINTS.extend(
    TrafficEndpoint(
        name=f"rtsw001.l102.c083.ash6:{port}",
    )
    for port in RTSW001_L102_IXIA_PORTS
)
ASH6_C083_NSF_FULL_MESH_TRAFFIC_ENDPOINTS.extend(
    TrafficEndpoint(
        name=f"rtsw002.l102.c083.ash6:{port}",
    )
    for port in RTSW002_L102_IXIA_PORTS
)
ASH6_C083_NSF_FULL_MESH_TRAFFIC_ENDPOINTS.extend(
    TrafficEndpoint(
        name=f"rtsw003.l102.c083.ash6:{port}",
    )
    for port in RTSW003_L102_IXIA_PORTS
)


RTSW001_L101_SINGLE_NODE_IXIA_SRC_PORTS = [
    "eth1/1/1",
    "eth1/2/1",
    "eth1/3/1",
]
RTSW001_L101_SINGLE_NODE_IXIA_DST_PORTS = [
    "eth1/17/5",
]

ASH6_C083_NSF_SINGLE_NODE_END_POINTS = [
    Endpoint(
        name="rtsw001.l101.c083.ash6",
        ixia_ports=RTSW001_L101_SINGLE_NODE_IXIA_SRC_PORTS
        + RTSW001_L101_SINGLE_NODE_IXIA_DST_PORTS,
        dut=True,
    ),
]

NSF_ASH6_SINGLE_NODE_TEST_TRAFFIC_SRC_ENDPOINTS = [
    TrafficEndpoint(
        name=f"rtsw001.l101.c083.ash6:{port}",
    )
    for port in RTSW001_L101_SINGLE_NODE_IXIA_SRC_PORTS
]
NSF_ASH6_SINGLE_NODE_TEST_TRAFFIC_DST_ENDPOINTS = [
    TrafficEndpoint(
        name=f"rtsw001.l101.c083.ash6:{port}",
    )
    for port in RTSW001_L101_SINGLE_NODE_IXIA_DST_PORTS
]

NSF_MP3BA_RTSW001_L101_SINGLE_NODE_IXIA_SRC_PORTS = [
    "eth1/17/1",
    "eth1/18/1",
    "eth1/19/1",
]

NSF_MP3BA_RTSW001_L101_SINGLE_NODE_IXIA_DST_PORTS = [
    "eth1/3/1",
]

ASH6_C083_NSF_MP3BA_SINGLE_NODE_END_POINTS = [
    Endpoint(
        name="rtsw003.l102.c083.ash6",
        ixia_ports=NSF_MP3BA_RTSW001_L101_SINGLE_NODE_IXIA_SRC_PORTS
        + NSF_MP3BA_RTSW001_L101_SINGLE_NODE_IXIA_DST_PORTS,
        dut=True,
    ),
]

NSF_MP3BA_ASH6_SINGLE_NODE_TEST_TRAFFIC_SRC_ENDPOINTS = [
    TrafficEndpoint(
        name=f"rtsw003.l102.c083.ash6:{port}",
    )
    for port in NSF_MP3BA_RTSW001_L101_SINGLE_NODE_IXIA_SRC_PORTS
]

NSF_MP3BA_ASH6_SINGLE_NODE_TEST_TRAFFIC_DST_ENDPOINTS = [
    TrafficEndpoint(
        name=f"rtsw003.l102.c083.ash6:{port}",
    )
    for port in NSF_MP3BA_RTSW001_L101_SINGLE_NODE_IXIA_DST_PORTS
]

RTSW001_L101_MULTI_NODE_4PRT_IXIA_SRC_PORTS = [
    "eth1/3/5",
]
RTSW002_L101_MULTI_NODE_4PRT_IXIA_SRC_PORTS = [
    "eth1/3/5",
]
RTSW003_L101_MULTI_NODE_4PRT_IXIA_SRC_PORTS = [
    "eth1/3/5",
]
RTSW001_L102_MULTI_NODE_4PRT_IXIA_DST_PORTS = [
    "eth1/3/5",
]

ASH6_C083_NSF_MULTI_NODE_4PRT_END_POINTS = [
    Endpoint(
        name="rtsw001.l101.c083.ash6",
        ixia_ports=RTSW001_L101_MULTI_NODE_4PRT_IXIA_SRC_PORTS,
        dut=False,
    ),
    Endpoint(
        name="rtsw002.l101.c083.ash6",
        ixia_ports=RTSW002_L101_MULTI_NODE_4PRT_IXIA_SRC_PORTS,
        dut=False,
    ),
    Endpoint(
        name="rtsw003.l101.c083.ash6",
        ixia_ports=RTSW003_L101_MULTI_NODE_4PRT_IXIA_SRC_PORTS,
        dut=False,
    ),
    Endpoint(
        name="rtsw001.l102.c083.ash6",
        ixia_ports=RTSW001_L102_MULTI_NODE_4PRT_IXIA_DST_PORTS,
        dut=True,
    ),
]

NSF_ASH6_MULTI_NODE_4PRT_TEST_TRAFFIC_SRC_ENDPOINTS = [
    TrafficEndpoint(
        name=f"rtsw001.l101.c083.ash6:{port}",
    )
    for port in RTSW001_L101_MULTI_NODE_4PRT_IXIA_SRC_PORTS
]
NSF_ASH6_MULTI_NODE_4PRT_TEST_TRAFFIC_SRC_ENDPOINTS.extend(
    TrafficEndpoint(
        name=f"rtsw002.l101.c083.ash6:{port}",
    )
    for port in RTSW002_L101_MULTI_NODE_4PRT_IXIA_SRC_PORTS
)
NSF_ASH6_MULTI_NODE_4PRT_TEST_TRAFFIC_SRC_ENDPOINTS.extend(
    TrafficEndpoint(
        name=f"rtsw003.l101.c083.ash6:{port}",
    )
    for port in RTSW003_L101_MULTI_NODE_4PRT_IXIA_SRC_PORTS
)
NSF_ASH6_MULTI_NODE_4PRT_TEST_TRAFFIC_DST_ENDPOINTS = [
    TrafficEndpoint(
        name=f"rtsw001.l102.c083.ash6:{port}",
    )
    for port in RTSW001_L102_MULTI_NODE_4PRT_IXIA_DST_PORTS
]

NSF_MP3BA_RTSW001A_L101_MULTI_NODE_4PRT_IXIA_SRC_PORTS = [
    "eth1/17/1",
]
NSF_MP3BA_RTSW001B_L101_MULTI_NODE_4PRT_IXIA_SRC_PORTS = [
    "eth1/18/1",
]
NSF_MP3BA_RTSW001C_L101_MULTI_NODE_4PRT_IXIA_SRC_PORTS = [
    "eth1/19/1",
]
NSF_MP3BA_RTSW003_L102_MULTI_NODE_4PRT_IXIA_DST_PORTS = [
    "eth1/3/1",
]

ASH6_C083_NSF_MP3BA_MULTI_NODE_4PRT_END_POINTS = [
    Endpoint(
        name="rtsw001.l101.c083.ash6",
        ixia_ports=NSF_MP3BA_RTSW001A_L101_MULTI_NODE_4PRT_IXIA_SRC_PORTS,
        dut=False,
    ),
    Endpoint(
        name="rtsw001.l101.c083.ash6",
        ixia_ports=NSF_MP3BA_RTSW001B_L101_MULTI_NODE_4PRT_IXIA_SRC_PORTS,
        dut=False,
    ),
    Endpoint(
        name="rtsw001.l101.c083.ash6",
        ixia_ports=NSF_MP3BA_RTSW001C_L101_MULTI_NODE_4PRT_IXIA_SRC_PORTS,
        dut=False,
    ),
    Endpoint(
        name="rtsw001.l102.c083.ash6",
        ixia_ports=NSF_MP3BA_RTSW003_L102_MULTI_NODE_4PRT_IXIA_DST_PORTS,
        dut=True,
    ),
]

NSF_MP3BA_ASH6_MULTI_NODE_4PRT_TEST_TRAFFIC_SRC_ENDPOINTS = [
    TrafficEndpoint(
        name=f"rtsw001.l101.c083.ash6:{port}",
    )
    for port in NSF_MP3BA_RTSW001A_L101_MULTI_NODE_4PRT_IXIA_SRC_PORTS
]
NSF_MP3BA_ASH6_MULTI_NODE_4PRT_TEST_TRAFFIC_SRC_ENDPOINTS.extend(
    TrafficEndpoint(
        name=f"rtsw001.l101.c083.ash6:{port}",
    )
    for port in NSF_MP3BA_RTSW001B_L101_MULTI_NODE_4PRT_IXIA_SRC_PORTS
)
NSF_MP3BA_ASH6_MULTI_NODE_4PRT_TEST_TRAFFIC_SRC_ENDPOINTS.extend(
    TrafficEndpoint(
        name=f"rtsw001.l101.c083.ash6:{port}",
    )
    for port in NSF_MP3BA_RTSW001C_L101_MULTI_NODE_4PRT_IXIA_SRC_PORTS
)
NSF_MP3BA_ASH6_MULTI_NODE_4PRT_TEST_TRAFFIC_DST_ENDPOINTS = [
    TrafficEndpoint(
        name=f"rtsw001.l102.c083.ash6:{port}",
    )
    for port in NSF_MP3BA_RTSW003_L102_MULTI_NODE_4PRT_IXIA_DST_PORTS
]

ASH6_C083_NSF_MP3BA_MESH_IXIA_PORTS = [
    "eth1/3/1",
    "eth1/3/5",
]

ASH6_C083_NSF_MP3BA_MESH_ENDPOINTS = [
    Endpoint(
        name="rtsw001.l101.c083.ash6",
        ixia_ports=ASH6_C083_NSF_MP3BA_MESH_IXIA_PORTS,
    ),
    Endpoint(
        name="rtsw002.l101.c083.ash6",
        ixia_ports=ASH6_C083_NSF_MP3BA_MESH_IXIA_PORTS,
    ),
    Endpoint(
        name="rtsw003.l101.c083.ash6",
        ixia_ports=ASH6_C083_NSF_MP3BA_MESH_IXIA_PORTS,
    ),
    Endpoint(
        name="rtsw001.l102.c083.ash6",
        ixia_ports=ASH6_C083_NSF_MP3BA_MESH_IXIA_PORTS,
    ),
    Endpoint(
        name="rtsw002.l102.c083.ash6",
        ixia_ports=ASH6_C083_NSF_MP3BA_MESH_IXIA_PORTS,
    ),
    Endpoint(
        name="rtsw003.l102.c083.ash6",
        dut=True,  # MP3BA Device
        ixia_ports=ASH6_C083_NSF_MP3BA_MESH_IXIA_PORTS,
    ),
    Endpoint(
        name="ftsw001.l101.c083.ash6",
        dut=True,  # MP3BA Device
    ),
    Endpoint(
        name="stsw003.s002.l201.ash6",
        dut=True,  # MP3BA Device
    ),
]

ASH6_C083_NSF_MP3BA_MESH_TRAFFIC_ENDPOINTS = [
    TrafficEndpoint(
        name=f"rtsw001.l101.c083.ash6:{port}",
    )
    for port in ASH6_C083_NSF_MP3BA_MESH_IXIA_PORTS
]
ASH6_C083_NSF_MP3BA_MESH_TRAFFIC_ENDPOINTS.extend(
    TrafficEndpoint(
        name=f"rtsw002.l101.c083.ash6:{port}",
    )
    for port in ASH6_C083_NSF_MP3BA_MESH_IXIA_PORTS
)
ASH6_C083_NSF_MP3BA_MESH_TRAFFIC_ENDPOINTS.extend(
    TrafficEndpoint(
        name=f"rtsw003.l101.c083.ash6:{port}",
    )
    for port in ASH6_C083_NSF_MP3BA_MESH_IXIA_PORTS
)
ASH6_C083_NSF_MP3BA_MESH_TRAFFIC_ENDPOINTS.extend(
    TrafficEndpoint(
        name=f"rtsw001.l102.c083.ash6:{port}",
    )
    for port in ASH6_C083_NSF_MP3BA_MESH_IXIA_PORTS
)
ASH6_C083_NSF_MP3BA_MESH_TRAFFIC_ENDPOINTS.extend(
    TrafficEndpoint(
        name=f"rtsw002.l102.c083.ash6:{port}",
    )
    for port in ASH6_C083_NSF_MP3BA_MESH_IXIA_PORTS
)
ASH6_C083_NSF_MP3BA_MESH_TRAFFIC_ENDPOINTS.extend(
    TrafficEndpoint(
        name=f"rtsw003.l102.c083.ash6:{port}",
    )
    for port in ASH6_C083_NSF_MP3BA_MESH_IXIA_PORTS
)

ASH6_C083_NSF_MP3BA_MESH_TRAFFIC_ITEM_CONFIG = [
    BasicTrafficItemConfig(
        src_endpoints=ASH6_C083_NSF_MP3BA_MESH_TRAFFIC_ENDPOINTS,
        name="FULL_MESH_POD1",
        line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
        line_rate=50,
        traffic_type=ixia_types.TrafficType.IPV6,
        bidirectional=False,
        packet_headers=DSF_RDMA_PACKET_HEADERS,
        full_mesh=True,
        src_dest_mesh=ixia_types.SrcDestMeshType.FULL_MESH,
        frame_size_settings=DSF_FRAME_SIZES,
    )
]


TRAFFIC_ITEM_CONFIGS.append(
    BasicTrafficItemConfig(
        src_endpoints=ASH6_C083_NSF_FULL_MESH_TRAFFIC_ENDPOINTS,
        name="FULL_MESH_POD1",
        line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
        line_rate=50,
        traffic_type=ixia_types.TrafficType.IPV6,
        bidirectional=False,
        packet_headers=DSF_RDMA_PACKET_HEADERS,
        full_mesh=True,
        src_dest_mesh=ixia_types.SrcDestMeshType.FULL_MESH,
        frame_size_settings=DSF_FRAME_SIZES,
    )
)
TRAFFIC_ITEM_MAP["FULL_MESH_POD1"] = "FULL_MESH_POD1"
