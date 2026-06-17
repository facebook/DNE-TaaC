# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""TEST_SINGLE_NODE_QOS_TRAFFIC TestConfig.

Single-node QoS traffic test config for rdsw001.u001.c084.snc1, exercising NC,
RDMA, BE, and MONITORING traffic classes via the centralized
`create_qos_playbooks` factory.
"""

from ixia.ixia import types as ixia_types
from taac.packet_headers import (
    DSF_BE_PACKET_HEADERS,
    DSF_MONITORING_PACKET_HEADERS,
    DSF_NC_PACKET_HEADERS,
    DSF_RDMA_PACKET_HEADERS,
)
from taac.testconfigs.fboss_solution_tests.network_ai_test_configs import (
    create_qos_playbooks,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import TestConfig

IXIA_ENABLE_PFC_PORT_CONFIG = taac_types.BasicPortConfig(
    l1_config=ixia_types.L1Config(
        enable_fcoe=True,
        flow_control_config=ixia_types.FlowControlConfig(
            pfc_prority_groups_config=ixia_types.PfcPriorityGroupsConfig(
                priority0_pfc_queue=ixia_types.PfcQueue.ZERO,
                priority1_pfc_queue=ixia_types.PfcQueue.ONE,
                priority2_pfc_queue=ixia_types.PfcQueue.TWO,
                priority3_pfc_queue=ixia_types.PfcQueue.THREE,
            ),
            enable_pfc_pause_delay=False,
        ),
    )
)

RDSW001_U001_C084_SNC1_QOS_TRAFFIC_ITEM_CONFIGS = [
    taac_types.BasicTrafficItemConfig(
        src_endpoints=[
            taac_types.TrafficEndpoint(
                name="rdsw001.u001.c084.snc1:eth1/13/1",
            ),
        ],
        dest_endpoints=[
            taac_types.TrafficEndpoint(
                name="rdsw001.u001.c084.snc1:eth1/17/1",
            ),
        ],
        name="TEST_NC_70_TRAFFIC",
        line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
        line_rate=70,
        traffic_type=ixia_types.TrafficType.IPV6,
        bidirectional=False,
        packet_headers=DSF_NC_PACKET_HEADERS,
        full_mesh=False,
        src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
        frame_size_settings=ixia_types.FrameSize(
            type=ixia_types.FrameSizeType.CUSTOM_IMIX,
            imix_weight={94: 1, 96: 18, 192: 3, 512: 1, 1200: 1, 4600: 76},
        ),
    ),
    taac_types.BasicTrafficItemConfig(
        src_endpoints=[
            taac_types.TrafficEndpoint(
                name="rdsw001.u001.c084.snc1:eth1/11/1",
            ),
        ],
        dest_endpoints=[
            taac_types.TrafficEndpoint(
                name="rdsw001.u001.c084.snc1:eth1/17/1",
            ),
        ],
        name="TEST_RDMA_70_TRAFFIC",
        line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
        line_rate=70,
        traffic_type=ixia_types.TrafficType.IPV6,
        bidirectional=False,
        packet_headers=DSF_RDMA_PACKET_HEADERS,
        full_mesh=False,
        src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
        frame_size_settings=ixia_types.FrameSize(
            type=ixia_types.FrameSizeType.CUSTOM_IMIX,
            imix_weight={94: 1, 96: 18, 192: 3, 512: 1, 1200: 1, 4600: 76},
        ),
    ),
    taac_types.BasicTrafficItemConfig(
        src_endpoints=[
            taac_types.TrafficEndpoint(
                name="rdsw001.u001.c084.snc1:eth1/15/1",
            ),
        ],
        dest_endpoints=[
            taac_types.TrafficEndpoint(
                name="rdsw001.u001.c084.snc1:eth1/17/1",
            ),
        ],
        name="TEST_BE_70_TRAFFIC",
        line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
        line_rate=70,
        traffic_type=ixia_types.TrafficType.IPV6,
        bidirectional=False,
        packet_headers=DSF_BE_PACKET_HEADERS,
        full_mesh=False,
        src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
        frame_size_settings=ixia_types.FrameSize(
            type=ixia_types.FrameSizeType.CUSTOM_IMIX,
            imix_weight={94: 1, 96: 18, 192: 3, 512: 1, 1200: 1, 4600: 76},
        ),
    ),
    taac_types.BasicTrafficItemConfig(
        src_endpoints=[
            taac_types.TrafficEndpoint(
                name="rdsw001.u001.c084.snc1:eth1/15/1",
            ),
        ],
        dest_endpoints=[
            taac_types.TrafficEndpoint(
                name="rdsw001.u001.c084.snc1:eth1/17/1",
            ),
        ],
        name="TEST_MONITORING_70_TRAFFIC",
        line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
        line_rate=70,
        traffic_type=ixia_types.TrafficType.IPV6,
        bidirectional=False,
        packet_headers=DSF_MONITORING_PACKET_HEADERS,
        full_mesh=False,
        src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
        frame_size_settings=ixia_types.FrameSize(
            type=ixia_types.FrameSizeType.CUSTOM_IMIX,
            imix_weight={94: 1, 96: 18, 192: 3, 512: 1, 1200: 1, 4600: 76},
        ),
    ),
]
TEST_SINGLE_NODE_QOS_TRAFFIC_TEST_CONFIG = TestConfig(
    name="TEST_SINGLE_NODE_QOS_TRAFFIC",
    basset_pool="fboss",
    endpoints=[
        taac_types.Endpoint(
            name="rdsw001.u001.c084.snc1",
            dut=True,
            ixia_ports=["eth1/11/1", "eth1/13/1", "eth1/15/1", "eth1/17/1"],
        )
    ],
    default_basic_port_config=IXIA_ENABLE_PFC_PORT_CONFIG,
    basic_traffic_item_configs=RDSW001_U001_C084_SNC1_QOS_TRAFFIC_ITEM_CONFIGS,
    playbooks=create_qos_playbooks(
        traffic_items={
            "NC": RDSW001_U001_C084_SNC1_QOS_TRAFFIC_ITEM_CONFIGS[0],
            "RDMA": RDSW001_U001_C084_SNC1_QOS_TRAFFIC_ITEM_CONFIGS[1],
            "BE": RDSW001_U001_C084_SNC1_QOS_TRAFFIC_ITEM_CONFIGS[2],
            "MONITORING": RDSW001_U001_C084_SNC1_QOS_TRAFFIC_ITEM_CONFIGS[3],
        },
    ),
)
