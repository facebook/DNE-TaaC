# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
from ixia.ixia import types as ixia_types
from taac.test_as_a_config.types import BasicPortConfig, Endpoint, TrafficEndpoint


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

# RDSW <> IXIA Portmap
# https://docs.google.com/spreadsheets/d/1jQBGk_J1dtOt7tN7xCsjlEVsN6lnTgDw_F7UPLM74rc/edit?gid=533362369#gid=533362369
RDSW_IXIA_PORTS = [
    "eth1/11/1",
    "eth1/13/1",
    "eth1/15/1",
    "eth1/17/1",
    "eth1/20/1",
    "eth1/22/1",
    "eth1/24/1",
    "eth1/26/1",
]

# DTSW001 <> IXIA Portmap
# https://docs.google.com/spreadsheets/d/1jQBGk_J1dtOt7tN7xCsjlEVsN6lnTgDw_F7UPLM74rc/edit?gid=1658188089#gid=1658188089
DTSW001_IXIA_PORTS = [
    "eth1/3/1",
    "eth1/11/1",
    "eth1/19/1",
    "eth1/51/1",
]

# ----------------------------------------
# RDSW001 C087 SINGLE NODE 4 PORT Scenario
# ----------------------------------------

# eth ports chosen to be on different cores
RDSW_SINGLE_NODE_4PRT_IXIA_SRC_PORTS = ["eth1/11/1", "eth1/15/1", "eth1/20/1"]
RDSW_SINGLE_NODE_4PRT_IXIA_DST_PORTS = ["eth1/26/1"]

SNC1_C087_DSF_DTSW_RDSW001_SINGLE_NODE_ENDPOINTS = [
    Endpoint(
        name="rdsw001.u001.c087.snc1",
        ixia_ports=RDSW_SINGLE_NODE_4PRT_IXIA_SRC_PORTS
        + RDSW_SINGLE_NODE_4PRT_IXIA_DST_PORTS,
        dut=True,
    ),
]

SNC1_C087_DSF_DTSW_RDSW001_SINGLE_NODE_SRC_TRAFFIC_ENDPOINTS = [
    TrafficEndpoint(
        name=f"rdsw001.u001.c087.snc1:{port}",
    )
    for port in RDSW_SINGLE_NODE_4PRT_IXIA_SRC_PORTS
]

SNC1_C087_DSF_DTSW_RDSW001_SINGLE_NODE_DST_TRAFFIC_ENDPOINTS = [
    TrafficEndpoint(
        name=f"rdsw001.u001.c087.snc1:{port}",
    )
    for port in RDSW_SINGLE_NODE_4PRT_IXIA_DST_PORTS
]

# -----------------------------------
# DTSW001 SINGLE NODE 4 PORT Scenario
# -----------------------------------
DTSW_SINGLE_NODE_4PRT_IXIA_SRC_PORTS = ["eth1/3/1", "eth1/11/1", "eth1/51/1"]  # ITM0
DTSW_SINGLE_NODE_4PRT_IXIA_DST_PORTS = ["eth1/19/1"]  # ITM1

SNC1_C087_DSF_DTSW_DTSW001_SINGLE_NODE_ENDPOINTS = [
    Endpoint(
        name="dtsw001.snc1",
        ixia_ports=DTSW_SINGLE_NODE_4PRT_IXIA_SRC_PORTS
        + DTSW_SINGLE_NODE_4PRT_IXIA_DST_PORTS,
        dut=True,
    ),
]

SNC1_C087_DSF_DTSW_DTSW001_SINGLE_NODE_SRC_TRAFFIC_ENDPOINTS = [
    TrafficEndpoint(
        name=f"dtsw001.snc1:{port}",
    )
    for port in DTSW_SINGLE_NODE_4PRT_IXIA_SRC_PORTS
]

SNC1_C087_DSF_DTSW_DTSW001_SINGLE_NODE_DST_TRAFFIC_ENDPOINTS = [
    TrafficEndpoint(
        name=f"dtsw001.snc1:{port}",
    )
    for port in DTSW_SINGLE_NODE_4PRT_IXIA_DST_PORTS
]

# -------------------------------------------------------
# RDSW001 C087 to RDSW001 C088 MULTI NODE 4 PORT Scenario
# -------------------------------------------------------

RDSW001_C087_RDSW001_C088_MULTI_NODE_4PRT_IXIA_SRC_PORTS = [
    "eth1/11/1",
    "eth1/15/1",
    "eth1/20/1",
]
RDSW001_C087_RDSW001_C088_MULTI_NODE_4PRT_IXIA_DST_PORTS = ["eth1/26/1"]

SNC1_DSF_DTSW_RDSW001_C087_RDSW001_C088_MULTI_NODE_ENDPOINTS = [
    Endpoint(
        name="rdsw001.u001.c087.snc1",
        ixia_ports=RDSW001_C087_RDSW001_C088_MULTI_NODE_4PRT_IXIA_SRC_PORTS,
        dut=True,
    ),
    Endpoint(
        name="rdsw001.u001.c088.snc1",
        ixia_ports=RDSW001_C087_RDSW001_C088_MULTI_NODE_4PRT_IXIA_DST_PORTS,
    ),
]

SNC1_DSF_DTSW_RDSW001_C087_RDSW001_C088_MULTI_NODE_SRC_TRAFFIC_ENDPOINTS = [
    TrafficEndpoint(
        name=f"rdsw001.u001.c087.snc1:{port}",
    )
    for port in RDSW001_C087_RDSW001_C088_MULTI_NODE_4PRT_IXIA_SRC_PORTS
]

SNC1_DSF_DTSW_RDSW001_C087_RDSW001_C088_MULTI_NODE_DST_TRAFFIC_ENDPOINTS = [
    TrafficEndpoint(
        name=f"rdsw001.u001.c088.snc1:{port}",
    )
    for port in RDSW001_C087_RDSW001_C088_MULTI_NODE_4PRT_IXIA_DST_PORTS
]


# ---------------------------------------------------
# MP3BA Longevitiy and Consecutive Warmboots Scenario
# ---------------------------------------------------
RDSW_IXIA_PORTS = [
    "eth1/11/1",
    "eth1/13/1",
    "eth1/15/1",
    "eth1/17/1",
    "eth1/20/1",
    "eth1/22/1",
    "eth1/24/1",
    "eth1/26/1",
]

SNC1_DSF_DTSW_C087_C088_ENDPOINTS = [
    Endpoint(
        name="dtsw001.snc1",
        dut=True,  # MP3BA Device
    ),
    Endpoint(
        name="rdsw001.u001.c087.snc1",
        ixia_ports=RDSW_IXIA_PORTS,
    ),
    Endpoint(
        name="rdsw002.u001.c087.snc1",
        ixia_ports=RDSW_IXIA_PORTS,
    ),
    Endpoint(
        name="rdsw003.u001.c087.snc1",
        ixia_ports=RDSW_IXIA_PORTS,
    ),
    # Endpoint(
    #     name="rdsw004.u001.c087.snc1",
    #     ixia_ports=RDSW_IXIA_PORTS,
    # ),
    # Endpoint(
    #     name="rdsw001.u001.c088.snc1",
    #     ixia_ports=RDSW_IXIA_PORTS,
    # ),
    Endpoint(
        name="rdsw002.u001.c088.snc1",
        ixia_ports=RDSW_IXIA_PORTS,
    ),
    Endpoint(
        name="rdsw003.u001.c088.snc1",
        ixia_ports=RDSW_IXIA_PORTS,
    ),
    Endpoint(
        name="rdsw004.u001.c088.snc1",
        ixia_ports=RDSW_IXIA_PORTS,
    ),
]

SNC1_DSF_DTSW_C087_C088_TRAFFIC_ENDPOINTS = [
    TrafficEndpoint(
        name=f"rdsw001.u001.c087.snc1:{port}",
    )
    for port in RDSW_IXIA_PORTS
]
SNC1_DSF_DTSW_C087_C088_TRAFFIC_ENDPOINTS.extend(
    TrafficEndpoint(
        name=f"rdsw002.u001.c087.snc1:{port}",
    )
    for port in RDSW_IXIA_PORTS
)
SNC1_DSF_DTSW_C087_C088_TRAFFIC_ENDPOINTS.extend(
    TrafficEndpoint(
        name=f"rdsw003.u001.c087.snc1:{port}",
    )
    for port in RDSW_IXIA_PORTS
)
# SNC1_DSF_DTSW_C087_C088_TRAFFIC_ENDPOINTS.extend(
#     TrafficEndpoint(
#         name=f"rdsw004.u001.c087.snc1:{port}",
#     )
#     for port in RDSW_IXIA_PORTS
# )
# SNC1_DSF_DTSW_C087_C088_TRAFFIC_ENDPOINTS.extend(
#     TrafficEndpoint(
#         name=f"rdsw001.u001.c088.snc1:{port}",
#     )
#     for port in RDSW_IXIA_PORTS
# )
SNC1_DSF_DTSW_C087_C088_TRAFFIC_ENDPOINTS.extend(
    TrafficEndpoint(
        name=f"rdsw002.u001.c088.snc1:{port}",
    )
    for port in RDSW_IXIA_PORTS
)
SNC1_DSF_DTSW_C087_C088_TRAFFIC_ENDPOINTS.extend(
    TrafficEndpoint(
        name=f"rdsw003.u001.c088.snc1:{port}",
    )
    for port in RDSW_IXIA_PORTS
)
SNC1_DSF_DTSW_C087_C088_TRAFFIC_ENDPOINTS.extend(
    TrafficEndpoint(
        name=f"rdsw004.u001.c088.snc1:{port}",
    )
    for port in RDSW_IXIA_PORTS
)
