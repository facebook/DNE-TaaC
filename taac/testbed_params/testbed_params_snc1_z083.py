# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
from taac.test_as_a_config.types import Endpoint, TrafficEndpoint

MULTI_NODE_PFC_NODES = ["rdsw001.u000.c083.snc1", "rdsw003.u000.c083.snc1"]
RDSW_IXIA_PORTS = [
    "eth1/1/1",
    "eth1/2/1",
]

SNC1_Z083_MTIA_MULTI_NODE_PFC_END_POINTS = [
    Endpoint(
        name=MULTI_NODE_PFC_NODES[0],
        dut=True,
        ixia_ports=RDSW_IXIA_PORTS,
    ),
    Endpoint(
        name=MULTI_NODE_PFC_NODES[1],
        ixia_ports=RDSW_IXIA_PORTS,
    ),
]

SNC1_Z083_MTIA_MULTI_NODE_PFC_TRAFFIC_SRC_ENDPOINTS = [
    TrafficEndpoint(name=f"{MULTI_NODE_PFC_NODES[0]}:{RDSW_IXIA_PORTS[0]}"),
    TrafficEndpoint(name=f"{MULTI_NODE_PFC_NODES[0]}:{RDSW_IXIA_PORTS[1]}"),
    TrafficEndpoint(name=f"{MULTI_NODE_PFC_NODES[1]}:{RDSW_IXIA_PORTS[0]}"),
    TrafficEndpoint(name=f"{MULTI_NODE_PFC_NODES[0]}:{RDSW_IXIA_PORTS[0]}"),
]

SNC1_Z083_MTIA_MULTI_NODE_PFC_TRAFFIC_DST_ENDPOINTS = [
    TrafficEndpoint(name=f"{MULTI_NODE_PFC_NODES[1]}:{RDSW_IXIA_PORTS[1]}"),
]
