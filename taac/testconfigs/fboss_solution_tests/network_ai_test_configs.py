# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Generic NetworkAI TestConfig builders + shared traffic/playbook helpers.

Hosts the cross-platform PFC functionality / PFC-WD TestConfig generators
(``gen_pfc_functionality_test_configs``, ``gen_pfc_wd_functionality_test_configs``),
ASH6 C083 NSF base TestConfigs, and DSF protocol traffic-item factories. Many helpers
re-export from ``playbooks/playbook_definitions`` for backward-compatible imports.
"""

import typing as t

from ixia.ixia import types as ixia_types
from taac.health_checks.healthcheck_definitions import (
    create_packetloss_health_check,
)
from taac.packet_headers import (
    DSF_BE_PACKET_HEADERS,
    DSF_MONITORING_PACKET_HEADERS,
    DSF_NC_PACKET_HEADERS,
    DSF_RDMA_PACKET_HEADERS,
    TC2_PFC_PAUSE_PACKET_HEADERS,
    TC6_PFC_PAUSE_PACKET_HEADERS,
)

# Re-exported from playbooks/helpers/networkai/network_ai_playbooks.py — see Phase 4-43.
from taac.playbooks.playbook_definitions import (  # noqa: F401
    create_dsf_dtsw_mesh_consecutive_warmboot_endurance_playbook,
    create_dsf_dtsw_mesh_longevity_playbook,
    create_dsf_pfc_check,
    create_multi_pfc_congestion_playbook,
    create_packet_loss_check,
    create_pfc_functionality_congestion_non_pfc_traffic,
    create_pfc_functionality_congestion_non_tc2_traffic_playbook,
    create_pfc_functionality_congestion_playbook,
    create_pfc_functionality_congestion_voq_credit_fairness_playbook,
    create_pfc_functionality_incast_playbook,
    create_pfc_functionality_non_congestion_4port_playbook,
    create_pfc_functionality_non_congestion_playbook,
    create_pfc_functionality_port_flap_4port_playbook,
    create_pfc_functionality_port_flap_playbook,
    create_pfc_wd_check,
    create_playbook_wd,
    create_qos_playbook,
    create_qos_playbooks,
    gen_endurance_playbook,
    get_playbook_longevity,
    PLAYBOOKS_TEST,
    TEST_CONTINUOUS_AGENT_WARMBOOT_PLAYBOOK,
)
from taac.testbed_params.testbed_params_ash6_c083 import (
    ASH6_C083_NSF_END_POINTS,
    ASH6_C083_NSF_MP3BA_MESH_ENDPOINTS,
    ASH6_C083_NSF_MP3BA_MESH_TRAFFIC_ITEM_CONFIG,
    ASH6_C083_NSF_MP3BA_MULTI_NODE_4PRT_END_POINTS,
    ASH6_C083_NSF_MP3BA_SINGLE_NODE_END_POINTS,
    ASH6_C083_NSF_MULTI_NODE_4PRT_END_POINTS,
    ASH6_C083_NSF_SINGLE_NODE_END_POINTS,
    NSF_ASH6_MULTI_NODE_4PRT_TEST_TRAFFIC_DST_ENDPOINTS,
    NSF_ASH6_MULTI_NODE_4PRT_TEST_TRAFFIC_SRC_ENDPOINTS,
    NSF_ASH6_SINGLE_NODE_TEST_TRAFFIC_DST_ENDPOINTS,
    NSF_ASH6_SINGLE_NODE_TEST_TRAFFIC_SRC_ENDPOINTS,
    NSF_MP3BA_ASH6_MULTI_NODE_4PRT_TEST_TRAFFIC_DST_ENDPOINTS,
    NSF_MP3BA_ASH6_MULTI_NODE_4PRT_TEST_TRAFFIC_SRC_ENDPOINTS,
    NSF_MP3BA_ASH6_SINGLE_NODE_TEST_TRAFFIC_DST_ENDPOINTS,
    NSF_MP3BA_ASH6_SINGLE_NODE_TEST_TRAFFIC_SRC_ENDPOINTS,
    TRAFFIC_ITEM_CONFIGS as NSF_TRAFFIC_ITEM_CONFIGS,
    TRAFFIC_ITEM_MAP as NSF_TRAFFIC_ITEM_MAP,
)
from taac.testbed_params.testbed_params_dsf_dtsw_snc1_c087_c088 import (
    SNC1_C087_DSF_DTSW_DTSW001_SINGLE_NODE_DST_TRAFFIC_ENDPOINTS,
    SNC1_C087_DSF_DTSW_DTSW001_SINGLE_NODE_ENDPOINTS,
    SNC1_C087_DSF_DTSW_DTSW001_SINGLE_NODE_SRC_TRAFFIC_ENDPOINTS,
    SNC1_C087_DSF_DTSW_RDSW001_SINGLE_NODE_DST_TRAFFIC_ENDPOINTS,
    SNC1_C087_DSF_DTSW_RDSW001_SINGLE_NODE_ENDPOINTS,
    SNC1_C087_DSF_DTSW_RDSW001_SINGLE_NODE_SRC_TRAFFIC_ENDPOINTS,
    SNC1_DSF_DTSW_C087_C088_ENDPOINTS,
    SNC1_DSF_DTSW_C087_C088_TRAFFIC_ENDPOINTS,
    SNC1_DSF_DTSW_RDSW001_C087_RDSW001_C088_MULTI_NODE_DST_TRAFFIC_ENDPOINTS,
    SNC1_DSF_DTSW_RDSW001_C087_RDSW001_C088_MULTI_NODE_ENDPOINTS,
    SNC1_DSF_DTSW_RDSW001_C087_RDSW001_C088_MULTI_NODE_SRC_TRAFFIC_ENDPOINTS,
)
from taac.testbed_params.testbed_params_snc1_z083 import (
    SNC1_Z083_MTIA_MULTI_NODE_PFC_END_POINTS,
    SNC1_Z083_MTIA_MULTI_NODE_PFC_TRAFFIC_DST_ENDPOINTS,
    SNC1_Z083_MTIA_MULTI_NODE_PFC_TRAFFIC_SRC_ENDPOINTS,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import Endpoint, TestConfig, TrafficEndpoint

# There are 4 traffic classes for PFC queues at Meta
# TC1: Default - Lossy (Queue 0, least priority)
# TC2: RDMA - Lossless (Queue 2, PFC-enabled)
# TC6: Monitoring - Lossy (Queue 6) / Lossless (Queue 6, PFC-enabled) on Tahan/SUSW
# TC7: Network Control - Strict priority and Lossy (Queue 7, highest priority)
TRAFFIC_ITEM_HEADERS_MAP = {
    "RDMA": DSF_RDMA_PACKET_HEADERS,
    "BE": DSF_BE_PACKET_HEADERS,
    "NC": DSF_NC_PACKET_HEADERS,
    "MONITORING": DSF_MONITORING_PACKET_HEADERS,
}

DSF_FRAME_SIZES = ixia_types.FrameSize(
    type=ixia_types.FrameSizeType.CUSTOM_IMIX,
    imix_weight={94: 1, 96: 18, 192: 3, 512: 1, 1200: 1, 4600: 76},
)
PFC_PAUSE_FRAME_RATES = [10000, 11000, 13000, 14000, 15000]


# TODO (@madhavirao, @zelda): Fix Packet headers to set the PFC Queue value to avoid hacking the L1 config
IXIA_ENABLE_PFC_PORT_CONFIG = taac_types.BasicPortConfig(
    l1_config=ixia_types.L1Config(
        enable_fcoe=True,
        flow_control_config=ixia_types.FlowControlConfig(
            pfc_prority_groups_config=ixia_types.PfcPriorityGroupsConfig(
                priority0_pfc_queue=ixia_types.PfcQueue.TWO,
                priority1_pfc_queue=ixia_types.PfcQueue.ONE,
                priority2_pfc_queue=ixia_types.PfcQueue.ZERO,
                priority3_pfc_queue=ixia_types.PfcQueue.THREE,
                priority4_pfc_queue=ixia_types.PfcQueue.TWO,
                priority5_pfc_queue=ixia_types.PfcQueue.ONE,
                priority6_pfc_queue=ixia_types.PfcQueue.ZERO,
                priority7_pfc_queue=ixia_types.PfcQueue.THREE,
            ),
            enable_pfc_pause_delay=False,
        ),
    )
)


def gen_pfc_functionality_test_configs(
    test_config_name: str,
    endpoints: t.List[Endpoint],
    basset_pool: str,
    src_endpoints: t.List[TrafficEndpoint],
    dst_endpoints: t.List[TrafficEndpoint],
    is_monitoring_lossless: bool = False,
    qos_loss_threshold: str = "58",
) -> TestConfig:
    """Build the standard NetworkAI PFC functionality TestConfig.

    Generates the full PFC qualification chain (congestion / non-congestion / incast /
    port-flap / watchdog playbooks) keyed off the supplied src/dst endpoint pairs.
    Used to validate PFC lossless behavior on NetworkAI DSF and SUSW topologies.

    Args:
        test_config_name: Name to register in the TestConfig (CLI-callable).
        endpoints: All endpoints in the topology (DUT + peers).
        basset_pool: Basset pool to reserve devices from.
        src_endpoints: Source traffic endpoints (one per traffic item; index 4 is
            also used as the port-flap source).
        dst_endpoints: Destination traffic endpoints (must align 1:1 with sources;
            index ``-1`` is the watchdog interface).
        is_monitoring_lossless: When ``True``, the monitoring traffic class is asserted
            to be lossless.
        qos_loss_threshold: QoS loss threshold (percentage as string) applied to the
            packet-loss health check.

    Returns:
        TestConfig: PFC functionality TestConfig.
    """
    traffic_items_configs = []
    traffic_items_names = []
    qos_traffic_items = {}
    qos_traffic_item_names = {}

    PLAYBOOK_PFC_CONGESTION_NON_TC2_TRAFFIC = [
        create_pfc_functionality_congestion_non_tc2_traffic_playbook(
            traffic_items_names_first_4=traffic_items_names[:4],
            src_endpoints=src_endpoints,
        ),
    ]
    PLAYBOOK_PFC_CONGESTION = [
        create_pfc_functionality_congestion_playbook(
            traffic_items_names=traffic_items_names,
        ),
        create_pfc_functionality_non_congestion_playbook(
            traffic_items_names=traffic_items_names,
            src_endpoints=src_endpoints,
        ),
    ]
    PLAYBOOK_PFC_INCAST = [
        create_pfc_functionality_incast_playbook(
            traffic_items_names=traffic_items_names,
        ),
    ]
    interface_to_flap = src_endpoints[4].name.split(":")[1]
    PLAYBOOK_PFC_PORT_FLAP = [
        create_pfc_functionality_port_flap_playbook(
            traffic_items_names=traffic_items_names,
            interface_to_flap=interface_to_flap,
        ),
    ]
    # For PLAYBOOKS_PFC_WD
    PLAYBOOKS_PFC_WD = [
        create_playbook_wd(
            name="test_pfc_wd_functionality",
            interfaces_to_check=dst_endpoints[-1:],
            min_in_pfc_value=800000,  # with 15000 line rate per sec, 60s duration, ~900k pfc frames should be received; setting to 800k to avoid flakiness
            wd_metric_comparison_type=hc_types.ComparisonType.GREATER_THAN,
            traffic_items_to_start=["TRAFFIC_PFC_PAUSE_15000FPS"],
        ),
    ]

    # For PLAYBOOKS_PFC_WD_TRANSIENT
    PLAYBOOKS_PFC_WD_TRANSIENT = [
        create_playbook_wd(
            name="test_pfc_wd_functionality_transient",
            interfaces_to_check=dst_endpoints[:1],
            min_in_pfc_value=500000,  # with 10000 line rate per sec, 60s duration, ~600k pfc frames should be received; setting to 500k to avoid flakiness
            wd_metric_comparison_type=hc_types.ComparisonType.EQUAL_TO,
            traffic_items_to_start=["TRAFFIC_PFC_PAUSE_10000FPS"],
        ),
    ]

    # For PLAYBOOKS_PFC_WD_NON_IMPACT_TC1
    PLAYBOOKS_PFC_WD_NON_IMPACT_TC1 = [
        create_playbook_wd(
            name="test_pfc_wd_functionality_non_impact_tc1",
            interfaces_to_check=dst_endpoints[-1:],
            min_in_pfc_value=500000,  # with 15000 line rate per sec, 60s duration, ~900k pfc frames should be received; setting to 500k to avoid flakiness
            wd_metric_comparison_type=hc_types.ComparisonType.GREATER_THAN,
            traffic_items_to_start=["TRAFFIC_PFC_PAUSE_15000FPS", "TEST_BE_24_TRAFFIC"],
            packetlosscheck=True,
        ),
    ]
    for iter, (src_endpoint, dst_endpoint) in enumerate(
        zip(src_endpoints, dst_endpoints), 1
    ):
        if iter != 5:
            traffic_items_configs.append(
                taac_types.BasicTrafficItemConfig(
                    src_endpoints=[src_endpoint],
                    dest_endpoints=[dst_endpoint],
                    name=f"TEST_RDMA_24_TRAFFIC_{iter}",
                    line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
                    line_rate=24,
                    traffic_type=ixia_types.TrafficType.IPV6,
                    bidirectional=False,
                    packet_headers=DSF_RDMA_PACKET_HEADERS,
                    full_mesh=False,
                    src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
                    frame_size_settings=DSF_FRAME_SIZES,
                )
            )
            traffic_items_names.append(f"TEST_RDMA_24_TRAFFIC_{iter}")
        else:
            traffic_items_configs.append(
                taac_types.BasicTrafficItemConfig(
                    src_endpoints=[src_endpoint],
                    dest_endpoints=[dst_endpoint],
                    name="TEST_BE_24_TRAFFIC",
                    line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
                    line_rate=24,
                    traffic_type=ixia_types.TrafficType.IPV6,
                    bidirectional=False,
                    packet_headers=DSF_BE_PACKET_HEADERS,
                    full_mesh=False,
                    src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
                    frame_size_settings=DSF_FRAME_SIZES,
                )
            )
            traffic_items_names.append("TEST_BE_24_TRAFFIC")

        traffic_items_configs.append(
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[src_endpoint],
                dest_endpoints=[dst_endpoint],
                name=f"TEST_RDMA_90_TRAFFIC_{iter}",  # Unique name using the iter counter
                line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
                line_rate=90,
                traffic_type=ixia_types.TrafficType.IPV6,
                bidirectional=False,
                packet_headers=DSF_RDMA_PACKET_HEADERS,
                full_mesh=False,
                src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
                frame_size_settings=DSF_FRAME_SIZES,
            )
        )
        traffic_items_names.append(f"TEST_RDMA_90_TRAFFIC_{iter}")
    for p_iter, (src_endpoint, dst_endpoint, proto) in enumerate(
        zip(src_endpoints, dst_endpoints, TRAFFIC_ITEM_HEADERS_MAP.keys()), 1
    ):
        if p_iter > 3:
            p_iter = 1
        qos_basic_traffic_item_config = taac_types.BasicTrafficItemConfig(
            src_endpoints=[src_endpoint],
            dest_endpoints=[dst_endpoint],
            name=f"TEST_{proto}_TRAFFIC_70PCT_P{p_iter}_TO_P4",
            line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
            line_rate=70,
            traffic_type=ixia_types.TrafficType.IPV6,
            bidirectional=False,
            packet_headers=TRAFFIC_ITEM_HEADERS_MAP.get(proto),
            full_mesh=False,
            src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
            frame_size_settings=DSF_FRAME_SIZES,
        )
        traffic_items_configs.append(qos_basic_traffic_item_config)
        qos_traffic_items[proto] = qos_basic_traffic_item_config
        qos_traffic_item_names[proto] = f"TEST_{proto}_TRAFFIC_70PCT_P{p_iter}_TO_P4"

    for FR, (src_endpoint, dst_endpoint) in zip(
        PFC_PAUSE_FRAME_RATES, zip(src_endpoints, dst_endpoints)
    ):
        traffic_items_configs.append(
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[src_endpoint],
                dest_endpoints=[dst_endpoint],
                name=f"TRAFFIC_PFC_PAUSE_{FR}FPS",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=FR,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=TC2_PFC_PAUSE_PACKET_HEADERS,
                full_mesh=False,
                frame_size_settings=ixia_types.FrameSize(
                    type=ixia_types.FrameSizeType.FIXED, fixed_size=64
                ),
                src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
            )
        )
        traffic_items_names.append(f"TRAFFIC_PFC_PAUSE_{FR}FPS")

    return TestConfig(
        name=test_config_name,
        basset_pool=basset_pool,
        endpoints=endpoints,
        default_basic_port_config=IXIA_ENABLE_PFC_PORT_CONFIG,
        basic_traffic_item_configs=traffic_items_configs,
        playbooks=create_qos_playbooks(
            traffic_items=qos_traffic_items,
            is_monitoring_lossless=is_monitoring_lossless,
        )
        + PLAYBOOK_PFC_CONGESTION_NON_TC2_TRAFFIC
        + PLAYBOOK_PFC_CONGESTION
        + PLAYBOOK_PFC_INCAST
        + PLAYBOOK_PFC_PORT_FLAP
        + PLAYBOOKS_PFC_WD
        + PLAYBOOKS_PFC_WD_TRANSIENT
        + PLAYBOOKS_PFC_WD_NON_IMPACT_TC1,
    )


def gen_pfc_wd_functionality_test_configs(
    test_config_name: str,
    endpoints: t.List[Endpoint],
    basset_pool: str,
    src_endpoints: t.List[TrafficEndpoint],
    dst_endpoints: t.List[TrafficEndpoint],
) -> TestConfig:
    """Build the NetworkAI PFC watchdog (PFC-WD) functionality TestConfig.

    Stripped-down sibling of ``gen_pfc_functionality_test_configs`` focused only on the
    PFC watchdog playbooks: steady-state, transient, and non-impact-TC1. Generates the
    two pause-frame traffic items (``TRAFFIC_PFC_PAUSE_10000FPS`` /
    ``TRAFFIC_PFC_PAUSE_15000FPS``) plus the BE-24 traffic item used for the non-impact
    check.

    Args:
        test_config_name: Name to register in the TestConfig (CLI-callable).
        endpoints: All endpoints in the topology.
        basset_pool: Basset pool to reserve devices from.
        src_endpoints: Source traffic endpoints (also passed as the WD interfaces-to-check).
        dst_endpoints: Destination traffic endpoints (must align 1:1 with sources).

    Returns:
        TestConfig: PFC-WD functionality TestConfig.
    """
    traffic_items_configs = []
    traffic_items_names = []
    # For PLAYBOOKS_PFC_WD
    PLAYBOOKS_PFC_WD = [
        create_playbook_wd(
            name="test_pfc_wd_functionality",
            interfaces_to_check=src_endpoints,
            min_in_pfc_value=800000,  # with 15000 line rate per sec, 60s duration, ~900k pfc frames should be received; setting to 800k to avoid flakiness
            wd_metric_comparison_type=hc_types.ComparisonType.GREATER_THAN,
            traffic_items_to_start=["TRAFFIC_PFC_PAUSE_15000FPS"],
        ),
    ]

    # For PLAYBOOKS_PFC_WD_TRANSIENT
    PLAYBOOKS_PFC_WD_TRANSIENT = [
        create_playbook_wd(
            name="test_pfc_wd_functionality_transient",
            interfaces_to_check=src_endpoints,
            min_in_pfc_value=500000,  # with 10000 line rate per sec, 60s duration, ~600k pfc frames should be received; setting to 500k to avoid flakiness
            wd_metric_comparison_type=hc_types.ComparisonType.EQUAL_TO,
            traffic_items_to_start=["TRAFFIC_PFC_PAUSE_10000FPS"],
        ),
    ]

    # For PLAYBOOKS_PFC_WD_NON_IMPACT_TC1
    PLAYBOOKS_PFC_WD_NON_IMPACT_TC1 = [
        create_playbook_wd(
            name="test_pfc_wd_functionality_non_impact_tc1",
            interfaces_to_check=src_endpoints,
            min_in_pfc_value=500000,  # with 15000 line rate per sec, 60s duration, ~900k pfc frames should be received; setting to 500k to avoid flakiness
            wd_metric_comparison_type=hc_types.ComparisonType.GREATER_THAN,
            traffic_items_to_start=["TRAFFIC_PFC_PAUSE_15000FPS", "TEST_BE_24_TRAFFIC"],
            packetlosscheck=True,
        ),
    ]

    for FR in [10000, 15000]:
        traffic_items_configs.append(
            taac_types.BasicTrafficItemConfig(
                src_endpoints=src_endpoints,
                dest_endpoints=dst_endpoints,
                name=f"TRAFFIC_PFC_PAUSE_{FR}FPS",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=FR,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=TC2_PFC_PAUSE_PACKET_HEADERS,
                full_mesh=False,
                frame_size_settings=ixia_types.FrameSize(
                    type=ixia_types.FrameSizeType.FIXED, fixed_size=64
                ),
                src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
            )
        )
        traffic_items_names.append(f"TRAFFIC_PFC_PAUSE_{FR}FPS")
        traffic_items_configs.append(
            taac_types.BasicTrafficItemConfig(
                src_endpoints=src_endpoints,
                dest_endpoints=dst_endpoints,
                name="TEST_BE_24_TRAFFIC",
                line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
                line_rate=24,
                traffic_type=ixia_types.TrafficType.IPV6,
                bidirectional=False,
                packet_headers=DSF_BE_PACKET_HEADERS,
                full_mesh=False,
                src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
                frame_size_settings=DSF_FRAME_SIZES,
            )
        )
        traffic_items_names.append("TEST_BE_24_TRAFFIC")

    return TestConfig(
        name=test_config_name,
        basset_pool=basset_pool,
        endpoints=endpoints,
        default_basic_port_config=IXIA_ENABLE_PFC_PORT_CONFIG,
        basic_traffic_item_configs=traffic_items_configs,
        playbooks=PLAYBOOKS_PFC_WD
        + PLAYBOOKS_PFC_WD_TRANSIENT
        + PLAYBOOKS_PFC_WD_NON_IMPACT_TC1,
    )


def gen_ash6_c083_base_test_configs() -> TestConfig:
    """Build the ``NSF_ASH6_C083_BASE`` base-topology TestConfig.

    NSF (Network Switch Fabric) base topology in ASH6 C083 with full-mesh-pod1 longevity
    traffic for 60s. Used as the lightweight smoke-test config for ASH6 C083 NSF.

    Returns:
        TestConfig: ``NSF_ASH6_C083_BASE`` (basset pool ``networkai.test``).
    """
    return TestConfig(
        name="NSF_ASH6_C083_BASE",
        basset_pool="networkai.test",
        endpoints=ASH6_C083_NSF_END_POINTS,
        default_basic_port_config=IXIA_ENABLE_PFC_PORT_CONFIG,
        basic_traffic_item_configs=NSF_TRAFFIC_ITEM_CONFIGS,
        playbooks=get_playbook_longevity(
            name="test_nsf_ash6_longevity",
            time_in_seconds=60,
            traffic_item_list=[NSF_TRAFFIC_ITEM_MAP["FULL_MESH_POD1"]],
        ),
    )


def gen_mp3ba_ash6_c083_base_test_configs() -> TestConfig:
    """Build the ``NSF_MP3BA_ASH6_C083_BASE`` MP3BA mesh TestConfig.

    Sibling of ``gen_ash6_c083_base_test_configs`` for the MP3BA mesh endpoints in
    ASH6 C083. Adds a 10-iteration continuous-agent-warmboot endurance playbook on top
    of the longevity traffic and merges a packet-loss postcheck into every playbook.

    Returns:
        TestConfig: ``NSF_MP3BA_ASH6_C083_BASE`` (basset pool ``networkai.test``).
    """
    tc_postchecks = [
        create_packetloss_health_check(),
    ]
    playbooks = get_playbook_longevity(
        name="test_nsf_ash6_longevity",
        time_in_seconds=60,
        traffic_item_list=["FULL_MESH_POD1"],
    )
    playbooks.append(
        gen_endurance_playbook(TEST_CONTINUOUS_AGENT_WARMBOOT_PLAYBOOK, 10)
    )
    # Merge TestConfig-level postchecks into each playbook
    playbooks = [
        pb(postchecks=list(pb.postchecks or []) + tc_postchecks) for pb in playbooks
    ]

    return TestConfig(
        name="NSF_MP3BA_ASH6_C083_BASE",
        basset_pool="networkai.test",
        endpoints=ASH6_C083_NSF_MP3BA_MESH_ENDPOINTS,
        default_basic_port_config=IXIA_ENABLE_PFC_PORT_CONFIG,
        basic_traffic_item_configs=ASH6_C083_NSF_MP3BA_MESH_TRAFFIC_ITEM_CONFIG,
        playbooks=playbooks,
        # Deprecated - define at playbook level
        # postchecks=[
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
        #     ),
        # ],
    )


def create_dsf_proto_ipv6_traffic_config(
    proto: str,
    src_endpoints: list[TrafficEndpoint],
    dest_endpoints: list[TrafficEndpoint],
    name: str,
    line_rate: int,
    traffic_item_headers_map: t.Optional[
        t.Dict[str, t.List[taac_types.PacketHeader]]
    ] = None,
) -> taac_types.BasicTrafficItemConfig:
    """Build a DSF protocol-tagged IPv6 traffic-item config (RDMA / NC / BE / Monitoring).

    Selects the appropriate DSF packet headers based on ``proto`` and assembles a 1:1
    src/dst BasicTrafficItemConfig for use by NetworkAI DSF playbooks.

    Args:
        proto: One of ``"RDMA"``, ``"NC"``, ``"BE"``, ``"MONITORING"``. Selects the
            corresponding ``DSF_*_PACKET_HEADERS`` constant.
        src_endpoints: Source traffic endpoints.
        dest_endpoints: Destination traffic endpoints (1:1 with sources).
        name: Traffic-item name to assign.
        line_rate: Percent line rate to drive the traffic item at.

    Returns:
        BasicTrafficItemConfig: Configured DSF protocol traffic item.
    """
    headers_map = traffic_item_headers_map or TRAFFIC_ITEM_HEADERS_MAP
    return taac_types.BasicTrafficItemConfig(
        src_endpoints=src_endpoints,
        dest_endpoints=dest_endpoints,
        name=name,
        line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
        line_rate=line_rate,
        traffic_type=ixia_types.TrafficType.IPV6,
        bidirectional=False,
        packet_headers=headers_map.get(proto),
        full_mesh=False,
        src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
        frame_size_settings=DSF_FRAME_SIZES,
    )


def create_pfc_pause_traffic_config(
    src_endpoints: list[TrafficEndpoint],
    dest_endpoints: list[TrafficEndpoint],
    name: str,
    line_rate: int,
    packet_headers: list[taac_types.PacketHeader] = TC2_PFC_PAUSE_PACKET_HEADERS,
) -> taac_types.BasicTrafficItemConfig:
    """Build a raw PFC-pause traffic-item config at a given frame-per-second line rate.

    Used to inject PFC pause frames into a DSF / SUSW topology for PFC-WD and
    congestion playbooks. Defaults to TC2 pause headers; pass ``packet_headers`` to
    select a different traffic class (e.g. ``TC6_PFC_PAUSE_PACKET_HEADERS``).

    Args:
        src_endpoints: Source endpoints (where pause frames originate).
        dest_endpoints: Destination endpoints.
        name: Traffic-item name to assign.
        line_rate: Frames-per-second line rate.
        packet_headers: PFC pause packet headers (defaults to TC2).

    Returns:
        BasicTrafficItemConfig: Configured PFC-pause traffic item.
    """
    return taac_types.BasicTrafficItemConfig(
        src_endpoints=src_endpoints,
        dest_endpoints=dest_endpoints,
        name=name,
        line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
        line_rate=line_rate,
        traffic_type=ixia_types.TrafficType.RAW,
        bidirectional=False,
        packet_headers=packet_headers,
        full_mesh=False,
        frame_size_settings=ixia_types.FrameSize(
            type=ixia_types.FrameSizeType.FIXED, fixed_size=64
        ),
        src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
    )


def gen_pfc_functionality_test_generic_4port_configs(
    test_config_name: str,
    endpoints: t.List[Endpoint],
    basset_pool: str,
    src_endpoints: t.List[TrafficEndpoint],
    dst_endpoints: t.List[TrafficEndpoint],
    port_speed: int = 400,
    basic_port_configs: t.Optional[t.List[taac_types.BasicPortConfig]] = None,
    is_monitoring_lossless: bool = False,
    qos_loss_threshold: str = "60",
    traffic_item_headers_map: t.Optional[
        t.Dict[str, t.List[taac_types.PacketHeader]]
    ] = None,
) -> TestConfig:
    """
    Tests traffic rate and PFC packet dispersion in mixed-traffic congestion,
    and PFC watchdog kickoff in sustained PFC frames reception.

    The test cases are designed to run with 4 ports (3 source and 1 destination).

    PFC Tests are listed in this sheet - https://fburl.com/gsheet/qhif4j0m

    Args:
        src_endpoints: [P1, P2, P3, P1]
        dst_endpoints: [P4]
        basic_port_configs: None if no BGP config required (e.g. RDSW-FDSW labs)
    """
    headers_map = traffic_item_headers_map or TRAFFIC_ITEM_HEADERS_MAP
    traffic_items_configs = []
    rdma_90pct_traffic_items_names = []
    rdma_30pct_traffic_items_names = []
    monitoring_90pct_traffic_items_names = []
    monitoring_30pct_traffic_items_names = []
    be_24pct_traffic_item_name = "TEST_BE_24_TRAFFIC"
    qos_traffic_item_names = {}
    qos_traffic_items = {}
    if len(src_endpoints) == 3:
        src_endpoints.append(src_endpoints[0])

    if basic_port_configs is None:
        default_basic_port_config = IXIA_ENABLE_PFC_PORT_CONFIG
    else:
        default_basic_port_config = None

    # It takes PORT_SPEED_BPS / (512*65535) PFC frames per second to keep PFC
    # continuously asserted. This comes down to ~12000 frames per sec for 400G
    # and ~24000 frames per sec for 800G.
    if port_speed == 400:
        PFC_PAUSE_FRAME_RATES = [15000, 10000]
        tc2_wd_traffic_item_high = "TRAFFIC_TC2_PFC_PAUSE_15000FPS"
        tc2_wd_traffic_item_low = "TRAFFIC_TC2_PFC_PAUSE_10000FPS"
        tc6_wd_traffic_item_high = "TRAFFIC_TC6_PFC_PAUSE_15000FPS"
        tc6_wd_traffic_item_low = "TRAFFIC_TC6_PFC_PAUSE_10000FPS"
        wd_pfc_threshold_high = 800000  # with 15000 frames per sec, 60s duration, ~900k pfc frames should be received; setting to 800k to avoid flakiness
        wd_pfc_threshold_low = 500000  # with 10000 frames per sec, 60s duration, ~600k pfc frames should be received; setting to 500k to avoid flakiness
    elif port_speed == 800:
        PFC_PAUSE_FRAME_RATES = [30000, 20000]
        tc2_wd_traffic_item_high = "TRAFFIC_TC2_PFC_PAUSE_30000FPS"
        tc2_wd_traffic_item_low = "TRAFFIC_TC2_PFC_PAUSE_20000FPS"
        tc6_wd_traffic_item_high = "TRAFFIC_TC6_PFC_PAUSE_30000FPS"
        tc6_wd_traffic_item_low = "TRAFFIC_TC6_PFC_PAUSE_20000FPS"
        wd_pfc_threshold_high = 1600000  # double of 400G threshold
        wd_pfc_threshold_low = 1000000
    else:
        raise ValueError(
            f"Port speed {port_speed} is not supported by PFC watchdog test"
        )

    # Create 3 RDMA 90% line rate and 3 RDMA 30% line rate traffics
    # from first 3 source ports
    for iter, src_endpoint in enumerate(src_endpoints[:3], 1):
        traffic_items_configs.append(
            create_dsf_proto_ipv6_traffic_config(
                proto="RDMA",
                src_endpoints=[src_endpoint],
                dest_endpoints=dst_endpoints,
                name=f"TEST_RDMA_TRAFFIC_90PCT_P{iter}_TO_P4",
                line_rate=90,
                traffic_item_headers_map=headers_map,
            )
        )
        rdma_90pct_traffic_items_names.append(f"TEST_RDMA_TRAFFIC_90PCT_P{iter}_TO_P4")

        traffic_items_configs.append(
            create_dsf_proto_ipv6_traffic_config(
                proto="RDMA",
                src_endpoints=[src_endpoint],
                dest_endpoints=dst_endpoints,
                name=f"TEST_RDMA_TRAFFIC_30PCT_P{iter}_TO_P4",
                line_rate=30,
                traffic_item_headers_map=headers_map,
            )
        )
        rdma_30pct_traffic_items_names.append(f"TEST_RDMA_TRAFFIC_30PCT_P{iter}_TO_P4")

    # Create 3 Monitoring 90% line rate and 3 Monitoring 30% line rate traffics
    # from first 3 source ports
    # This is used to verify PFC functionality in Monitoring (TC6) on Tahan/SUSW
    for iter, src_endpoint in enumerate(src_endpoints[:3], 1):
        traffic_items_configs.append(
            create_dsf_proto_ipv6_traffic_config(
                proto="MONITORING",
                src_endpoints=[src_endpoint],
                dest_endpoints=dst_endpoints,
                name=f"TEST_MONITORING_TRAFFIC_90PCT_P{iter}_TO_P4",
                line_rate=90,
                traffic_item_headers_map=headers_map,
            )
        )
        monitoring_90pct_traffic_items_names.append(
            f"TEST_MONITORING_TRAFFIC_90PCT_P{iter}_TO_P4"
        )

        traffic_items_configs.append(
            create_dsf_proto_ipv6_traffic_config(
                proto="MONITORING",
                src_endpoints=[src_endpoint],
                dest_endpoints=dst_endpoints,
                name=f"TEST_MONITORING_TRAFFIC_30PCT_P{iter}_TO_P4",
                line_rate=30,
                traffic_item_headers_map=headers_map,
            )
        )
        monitoring_30pct_traffic_items_names.append(
            f"TEST_MONITORING_TRAFFIC_30PCT_P{iter}_TO_P4"
        )

    # Create Backend 24% line rate traffic from a single source port
    traffic_items_configs.append(
        create_dsf_proto_ipv6_traffic_config(
            proto="BE",
            src_endpoints=[src_endpoints[1]],
            dest_endpoints=dst_endpoints,
            name=be_24pct_traffic_item_name,
            line_rate=24,
            traffic_item_headers_map=headers_map,
        )
    )

    # Create QoS testing traffics for four traffic classes, one from each source port
    for it, (src_endpoint, proto) in enumerate(zip(src_endpoints, headers_map), 1):
        p_it = it
        if it > 3:
            p_it = 1
        dsf_proto_ipv6_traffic_config = create_dsf_proto_ipv6_traffic_config(
            proto=proto,
            src_endpoints=[src_endpoint],
            dest_endpoints=dst_endpoints,
            name=f"TEST_{proto}_TRAFFIC_70PCT_P{p_it}_TO_P4",
            line_rate=70,
            traffic_item_headers_map=headers_map,
        )
        traffic_items_configs.append(dsf_proto_ipv6_traffic_config)
        qos_traffic_items[proto] = dsf_proto_ipv6_traffic_config
        qos_traffic_item_names[proto] = f"TEST_{proto}_TRAFFIC_70PCT_P{p_it}_TO_P4"

    # Create a PFC Pause traffic for each frame rate on TC2 and TC6 from the first source port to
    # the destination port
    for FR in PFC_PAUSE_FRAME_RATES:
        traffic_items_configs.append(
            create_pfc_pause_traffic_config(
                src_endpoints=src_endpoints[:1],
                dest_endpoints=dst_endpoints,
                name=f"TRAFFIC_TC2_PFC_PAUSE_{FR}FPS",
                line_rate=FR,
                packet_headers=TC2_PFC_PAUSE_PACKET_HEADERS,
            )
        )
        traffic_items_configs.append(
            create_pfc_pause_traffic_config(
                src_endpoints=src_endpoints[:1],
                dest_endpoints=dst_endpoints,
                name=f"TRAFFIC_TC6_PFC_PAUSE_{FR}FPS",
                line_rate=FR,
                packet_headers=TC6_PFC_PAUSE_PACKET_HEADERS,
            )
        )

    traffic_duration = 60
    PLAYBOOK_PFC_CONGESTION_NON_TC2_TRAFFIC = [
        create_pfc_functionality_congestion_non_pfc_traffic(
            name="test_pfc_functionality_congestion_non_tc2_traffic",
            description="""During congestion with TC2 traffic (lossless RDMA) and
               TC1 traffic (lossy BE), there should be
                 1. No packet loss on RDMA traffics
                 2. High packet loss on BE traffics
                 3. If total TC2 < 100% line rate, then no PFC packets received at src endpoints""",
            pfc_traffic_items_names=rdma_30pct_traffic_items_names,
            be_traffic_item_name=be_24pct_traffic_item_name,
            src_endpoints=src_endpoints,
            dst_endpoints=dst_endpoints,
            traffic_duration=traffic_duration,
            priority=hc_types.Priority.PRIORITY_2,
        ),
    ]

    PLAYBOOK_PFC_CONGESTION_NON_TC6_TRAFFIC = [
        create_pfc_functionality_congestion_non_pfc_traffic(
            name="test_pfc_functionality_congestion_non_tc6_traffic",
            description="""Create TC0 congestion and verify no PFC pause is generated for TC6 traffic on Tahan/SUSW""",
            pfc_traffic_items_names=monitoring_30pct_traffic_items_names,
            be_traffic_item_name=be_24pct_traffic_item_name,
            src_endpoints=src_endpoints,
            dst_endpoints=dst_endpoints,
            traffic_duration=traffic_duration,
            priority=hc_types.Priority.PRIORITY_6,
        ),
    ]

    PLAYBOOK_PFC_CONGESTION = [
        create_pfc_functionality_congestion_voq_credit_fairness_playbook(
            rdma_90pct_traffic_items_names=rdma_90pct_traffic_items_names,
            src_endpoints=src_endpoints,
            dst_endpoints=dst_endpoints,
            traffic_duration=traffic_duration,
        ),
        create_pfc_functionality_non_congestion_4port_playbook(
            rdma_90pct_traffic_items_names=rdma_90pct_traffic_items_names,
            src_endpoints=src_endpoints,
            dst_endpoints=dst_endpoints,
            traffic_duration=traffic_duration,
        ),
    ]

    # Flap the second originating port
    interface_to_flap = src_endpoints[1].name.split(":")[1]
    device_name_of_interface_flap = src_endpoints[1].name.split(":")[0]
    PLAYBOOK_PFC_PORT_FLAP = [
        create_pfc_functionality_port_flap_4port_playbook(
            rdma_90pct_traffic_items_names=rdma_90pct_traffic_items_names,
            src_endpoints=src_endpoints,
            interface_to_flap=interface_to_flap,
            device_name_of_interface_flap=device_name_of_interface_flap,
        ),
    ]

    PLAYBOOKS_TC2_PFC_WD = [
        create_playbook_wd(
            name="test_tc2_pfc_wd_functionality",
            description="Watchdog should kick in during high-rate PFC Pause traffic",
            interfaces_to_check=src_endpoints[:1],
            min_in_pfc_value=wd_pfc_threshold_high,
            wd_metric_comparison_type=hc_types.ComparisonType.GREATER_THAN,
            traffic_items_to_start=[tc2_wd_traffic_item_high],
        ),
    ]

    PLAYBOOKS_TC2_PFC_WD_TRANSIENT = [
        create_playbook_wd(
            name="test_tc2_pfc_wd_functionality_transient",
            description="Watchdog should not kick in during low-rate PFC Pause traffic",
            interfaces_to_check=src_endpoints[:1],
            min_in_pfc_value=wd_pfc_threshold_low,
            wd_metric_comparison_type=hc_types.ComparisonType.EQUAL_TO,
            traffic_items_to_start=[tc2_wd_traffic_item_low],
        ),
    ]

    PLAYBOOKS_TC2_PFC_WD_NON_IMPACT_TC1 = [
        create_playbook_wd(
            name="test_tc2_pfc_wd_functionality_non_impact_tc1",
            description="PFC Pause storm traffic should not impact TC1",
            interfaces_to_check=src_endpoints[:1],
            min_in_pfc_value=wd_pfc_threshold_high,
            wd_metric_comparison_type=hc_types.ComparisonType.GREATER_THAN,
            traffic_items_to_start=[tc2_wd_traffic_item_high, "TEST_BE_24_TRAFFIC"],
            packetlosscheck=True,
        ),
    ]

    PLAYBOOKS_TC6_PFC_WD = [
        create_playbook_wd(
            name="test_tc6_pfc_wd_functionality",
            interfaces_to_check=src_endpoints[:1],
            min_in_pfc_value=wd_pfc_threshold_high,
            wd_metric_comparison_type=hc_types.ComparisonType.GREATER_THAN,
            traffic_items_to_start=[tc6_wd_traffic_item_high],
            priority=hc_types.Priority.PRIORITY_6,
        ),
    ]

    PLAYBOOKS_TC6_PFC_WD_TRANSIENT = [
        create_playbook_wd(
            name="test_tc6_pfc_wd_functionality_transient",
            interfaces_to_check=src_endpoints[:1],
            min_in_pfc_value=wd_pfc_threshold_low,
            wd_metric_comparison_type=hc_types.ComparisonType.EQUAL_TO,
            traffic_items_to_start=[tc6_wd_traffic_item_low],
            priority=hc_types.Priority.PRIORITY_6,
        ),
    ]

    PLAYBOOKS_TC6_PFC_WD_NON_IMPACT_TC1 = [
        create_playbook_wd(
            name="test_tc6_pfc_wd_functionality_non_impact_tc1",
            interfaces_to_check=src_endpoints[:1],
            min_in_pfc_value=wd_pfc_threshold_high,
            wd_metric_comparison_type=hc_types.ComparisonType.GREATER_THAN,
            traffic_items_to_start=[tc6_wd_traffic_item_high, "TEST_BE_24_TRAFFIC"],
            packetlosscheck=True,
            priority=hc_types.Priority.PRIORITY_6,
        ),
    ]

    PLAYBOOK_MULTI_PFC_CONGESTION = [
        create_multi_pfc_congestion_playbook(
            monitoring_90pct_traffic_items_names=monitoring_90pct_traffic_items_names,
            rdma_30pct_traffic_items_names=rdma_30pct_traffic_items_names,
            src_endpoints=src_endpoints,
            traffic_duration=traffic_duration,
        ),
    ]

    PFC_PLAYBOOKS = (
        PLAYBOOKS_TC2_PFC_WD
        + PLAYBOOKS_TC2_PFC_WD_TRANSIENT
        + PLAYBOOKS_TC2_PFC_WD_NON_IMPACT_TC1
        + PLAYBOOK_PFC_CONGESTION_NON_TC2_TRAFFIC
        + PLAYBOOK_PFC_CONGESTION
        + PLAYBOOK_PFC_PORT_FLAP
        + create_qos_playbooks(
            traffic_items=qos_traffic_items,
            is_monitoring_lossless=is_monitoring_lossless,
        )
    )
    # Add more PFC playbooks to verify PFC functionality in Monitoring (TC6) on Tahan/SUSW
    if is_monitoring_lossless:
        PFC_PLAYBOOKS = (
            PFC_PLAYBOOKS
            + PLAYBOOK_PFC_CONGESTION_NON_TC6_TRAFFIC
            + PLAYBOOK_MULTI_PFC_CONGESTION
            + PLAYBOOKS_TC6_PFC_WD
            + PLAYBOOKS_TC6_PFC_WD_TRANSIENT
            + PLAYBOOKS_TC6_PFC_WD_NON_IMPACT_TC1
        )

    return TestConfig(
        name=test_config_name,
        basset_pool=basset_pool,
        endpoints=endpoints,
        default_basic_port_config=default_basic_port_config,
        basic_port_configs=basic_port_configs,
        basic_traffic_item_configs=traffic_items_configs,
        playbooks=PFC_PLAYBOOKS,
    )


NSF_SINGLE_NODE_PFC_TEST_CONFIG = gen_pfc_functionality_test_generic_4port_configs(
    test_config_name="NSF_SINGLE_NODE_PFC_TEST_CONFIG",
    endpoints=ASH6_C083_NSF_SINGLE_NODE_END_POINTS,
    basset_pool="networkai.test",
    src_endpoints=NSF_ASH6_SINGLE_NODE_TEST_TRAFFIC_SRC_ENDPOINTS,
    dst_endpoints=NSF_ASH6_SINGLE_NODE_TEST_TRAFFIC_DST_ENDPOINTS,
    port_speed=400,
    basic_port_configs=None,
)

NSF_MP3BA_SINGLE_NODE_PFC_TEST_CONFIG = (
    gen_pfc_functionality_test_generic_4port_configs(
        test_config_name="NSF_MP3BA_SINGLE_NODE_PFC_TEST_CONFIG",
        endpoints=ASH6_C083_NSF_MP3BA_SINGLE_NODE_END_POINTS,
        basset_pool="networkai.test",
        src_endpoints=NSF_MP3BA_ASH6_SINGLE_NODE_TEST_TRAFFIC_SRC_ENDPOINTS,
        dst_endpoints=NSF_MP3BA_ASH6_SINGLE_NODE_TEST_TRAFFIC_DST_ENDPOINTS,
        port_speed=400,
        basic_port_configs=None,
    )
)

NSF_MULTI_NODE_PFC_TEST_CONFIG = gen_pfc_functionality_test_generic_4port_configs(
    test_config_name="NSF_MULTI_NODE_PFC_TEST_CONFIG",
    endpoints=ASH6_C083_NSF_MULTI_NODE_4PRT_END_POINTS,
    basset_pool="networkai.test",
    src_endpoints=NSF_ASH6_MULTI_NODE_4PRT_TEST_TRAFFIC_SRC_ENDPOINTS,
    dst_endpoints=NSF_ASH6_MULTI_NODE_4PRT_TEST_TRAFFIC_DST_ENDPOINTS,
    port_speed=400,
    basic_port_configs=None,
)

NSF_MP3BA_MULTI_NODE_PFC_TEST_CONFIG = gen_pfc_functionality_test_generic_4port_configs(
    test_config_name="NSF_MP3BA_MULTI_NODE_PFC_TEST_CONFIG",
    endpoints=ASH6_C083_NSF_MP3BA_MULTI_NODE_4PRT_END_POINTS,
    basset_pool="networkai.test",
    src_endpoints=NSF_MP3BA_ASH6_MULTI_NODE_4PRT_TEST_TRAFFIC_SRC_ENDPOINTS,
    dst_endpoints=NSF_MP3BA_ASH6_MULTI_NODE_4PRT_TEST_TRAFFIC_DST_ENDPOINTS,
    port_speed=400,
    basic_port_configs=None,
    qos_loss_threshold="65",
)

SNC1_C087_DSF_DTSW_RDSW001_SINGLE_NODE_PFC_TEST_CONFIG = (
    gen_pfc_functionality_test_generic_4port_configs(
        test_config_name="SNC1_C087_DSF_DTSW_RDSW001_SINGLE_NODE_PFC_TEST_CONFIG",
        endpoints=SNC1_C087_DSF_DTSW_RDSW001_SINGLE_NODE_ENDPOINTS,
        basset_pool="networkai.test",
        src_endpoints=SNC1_C087_DSF_DTSW_RDSW001_SINGLE_NODE_SRC_TRAFFIC_ENDPOINTS,
        dst_endpoints=SNC1_C087_DSF_DTSW_RDSW001_SINGLE_NODE_DST_TRAFFIC_ENDPOINTS,
        port_speed=400,
        basic_port_configs=None,
    )
)

SNC1_C087_DSF_DTSW_DTSW001_SINGLE_NODE_PFC_TEST_CONFIG = (
    gen_pfc_functionality_test_generic_4port_configs(
        test_config_name="SNC1_C087_DSF_DTSW_DTSW001_SINGLE_NODE_PFC_TEST_CONFIG",
        endpoints=SNC1_C087_DSF_DTSW_DTSW001_SINGLE_NODE_ENDPOINTS,
        basset_pool="networkai.test",
        src_endpoints=SNC1_C087_DSF_DTSW_DTSW001_SINGLE_NODE_SRC_TRAFFIC_ENDPOINTS,
        dst_endpoints=SNC1_C087_DSF_DTSW_DTSW001_SINGLE_NODE_DST_TRAFFIC_ENDPOINTS,
        port_speed=800,
        basic_port_configs=None,
    )
)

SNC1_DSF_DTSW_RDSW001_C087_RDSW001_C088_MULTI_NODE_PFC_TEST_CONFIG = gen_pfc_functionality_test_generic_4port_configs(
    test_config_name="SNC1_DSF_DTSW_RDSW001_C087_RDSW001_C088_MULTI_NODE_PFC_TEST_CONFIG",
    endpoints=SNC1_DSF_DTSW_RDSW001_C087_RDSW001_C088_MULTI_NODE_ENDPOINTS,
    basset_pool="networkai.test",
    src_endpoints=SNC1_DSF_DTSW_RDSW001_C087_RDSW001_C088_MULTI_NODE_SRC_TRAFFIC_ENDPOINTS,
    dst_endpoints=SNC1_DSF_DTSW_RDSW001_C087_RDSW001_C088_MULTI_NODE_DST_TRAFFIC_ENDPOINTS,
    port_speed=400,
    basic_port_configs=None,
)

MTIA_PFC_TEST_CONFIG = gen_pfc_functionality_test_generic_4port_configs(
    test_config_name="MTIA_PFC_TEST_CONFIG",
    endpoints=SNC1_Z083_MTIA_MULTI_NODE_PFC_END_POINTS,
    basset_pool="networkai.test",
    src_endpoints=SNC1_Z083_MTIA_MULTI_NODE_PFC_TRAFFIC_SRC_ENDPOINTS,
    dst_endpoints=SNC1_Z083_MTIA_MULTI_NODE_PFC_TRAFFIC_DST_ENDPOINTS,
    port_speed=400,  # IXIA-RDSW link speed
    basic_port_configs=None,
)

SNC1_DSF_DTSW_C087_C088_MESH_LONGEVITY_TEST_CONFIG = TestConfig(
    name="SNC1_DSF_DTSW_C087_C088_MESH_LONGEVITY_TEST_CONFIG",
    basset_pool="networkai.test",
    endpoints=SNC1_DSF_DTSW_C087_C088_ENDPOINTS,
    default_basic_port_config=IXIA_ENABLE_PFC_PORT_CONFIG,
    basic_traffic_item_configs=[
        taac_types.BasicTrafficItemConfig(
            src_endpoints=SNC1_DSF_DTSW_C087_C088_TRAFFIC_ENDPOINTS,
            name="SNC1_DSF_DTSW_C087_C088_FULL_MESH_TRAFFIC",
            line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
            line_rate=50,
            traffic_type=ixia_types.TrafficType.IPV6,
            bidirectional=False,
            packet_headers=DSF_RDMA_PACKET_HEADERS,
            full_mesh=True,
            src_dest_mesh=ixia_types.SrcDestMeshType.FULL_MESH,
            frame_size_settings=DSF_FRAME_SIZES,
        )
    ],
    playbooks=[
        create_dsf_dtsw_mesh_longevity_playbook(
            name="test_snc1_dsf_dtsw_c087_c088_longevity",
            traffic_item_name="SNC1_DSF_DTSW_C087_C088_FULL_MESH_TRAFFIC",
            duration_seconds=600,  # 10 minutes
        ),
        create_dsf_dtsw_mesh_consecutive_warmboot_endurance_playbook(
            name="test_snc1_dsf_dtsw_c087_c088_consecutive_warmboot_endurance",
            traffic_item_name="SNC1_DSF_DTSW_C087_C088_FULL_MESH_TRAFFIC",
            iteration_count=10,
            longevity_duration_seconds=120,
        ),
    ],
)
