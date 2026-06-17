# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
SNC Single Node Topology EDSW003 Test Configuration

This module provides configuration for testing SNC Single Node Topology on EDSW003.
It sets up BGP peering, traffic generation, and health checks for network testing.
"""

from ixia.ixia import types as ixia_types
from taac.health_checks.healthcheck_definitions import (
    create_drain_state_check,
    create_ixia_packet_loss_check,
    create_unclean_exit_check,
)
from taac.playbooks.playbook_definitions import (
    create_hyperport_snc_bag_longevity_playbook,
    get_hyperport_bag_disruptive_playbooks,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config.types import (
    BasicPortConfig,
    BasicTrafficItemConfig,
    BgpConfig,
    DeviceGroupConfig,
    Endpoint,
    IpAddressesConfig,
    RouteScale,
    RouteScaleSpec,
    TestConfig,
    TrafficEndpoint,
)


# Re-export `get_hyperport_bag_disruptive_playbooks` for backward compatibility —
# external consumer testconfigs/hyperport/hyperport_vrf_bag_test_configs.py imports
# it from this module. Module-level imports above already make it available.


# BGP Communities
EDSW_BGP_COMMUNITIES = ["65446:30", "65441:1028", "65529:52780", "65529:52779"]
BAG_BGP_COMMUNITIES = ["65529:52780", "65529:52779"]


def create_basic_port_config(
    endpoint: str,
    starting_ip: str,
    gateway_ip: str,
    local_as: int,
    bgp_peer_type: ixia_types.BgpPeerType,
    starting_prefixes: str,
    bgp_communities: list[str],
    mask: int = 127,
    prefix_count: int = 100,
    prefix_length: int = 64,
    l1_config: ixia_types.L1Config | None = None,
) -> BasicPortConfig:
    """Create a BasicPortConfig with common defaults."""
    return BasicPortConfig(
        endpoint=endpoint,
        l1_config=l1_config,
        device_group_configs=[
            DeviceGroupConfig(
                device_group_index=0,
                multiplier=1,
                v6_addresses_config=IpAddressesConfig(
                    starting_ip=starting_ip,
                    increment_ip="::2",
                    gateway_starting_ip=gateway_ip,
                    gateway_increment_ip="::2",
                    mask=mask,
                ),
                v6_bgp_config=BgpConfig(
                    local_as_4_bytes=local_as,
                    enable_4_byte_local_as=True,
                    is_confed=False,
                    bgp_peer_type=bgp_peer_type,
                    route_scales=[
                        RouteScaleSpec(
                            network_group_index=0,
                            v6_route_scale=RouteScale(
                                multiplier=1,
                                prefix_count=prefix_count,
                                prefix_length=prefix_length,
                                starting_prefixes=starting_prefixes,
                                prefix_step="0:0:0:1:0:0:0:0",
                                bgp_communities=bgp_communities,
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                            ),
                        ),
                    ],
                ),
            ),
        ],
    )


# EDSW003 N000 Port Config Data: (port_name, ixia_ip, gateway_ip, starting_prefix)
EDSW003_N000_PORT_CONFIG_DATA = [
    ("eth1/17/1", "2401:db00:11b:d8a0::1", "2401:db00:11b:d8a0::", "6000:1:1::"),
    ("eth1/23/1", "2401:db00:11b:d8a1::1", "2401:db00:11b:d8a1::", "6000:1:2::"),
]

# EDSW003 N001 Port Config Data: (port_name, ixia_ip, gateway_ip, starting_prefix)
EDSW003_N001_PORT_CONFIG_DATA = [
    ("eth1/17/1", "2401:db00:11b:d8c0::1", "2401:db00:11b:d8c0::", "6000:2:1::"),
    ("eth1/23/1", "2401:db00:11b:d8c1::1", "2401:db00:11b:d8c1::", "6000:2:2::"),
]

# Source BAG Port Config Data: (port_name, ixia_ip, gateway_ip, starting_prefix)
# All source ports advertise the same prefix
BAG_SOURCE_PORT_CONFIG_DATA = [
    ("Ethernet5/9/1", "2401:db00:11b:d8a1::a1", "2401:db00:11b:d8a1::a0", "4000:3:2::"),
    (
        "Ethernet5/10/1",
        "2401:db00:11b:d8a1::a3",
        "2401:db00:11b:d8a1::a2",
        "4000:3:2::",
    ),
    (
        "Ethernet5/11/1",
        "2401:db00:11b:d8a1::a5",
        "2401:db00:11b:d8a1::a4",
        "4000:3:2::",
    ),
    (
        "Ethernet5/12/1",
        "2401:db00:11b:d8a1::a7",
        "2401:db00:11b:d8a1::a6",
        "4000:3:2::",
    ),
]

# Destination BAG Port Config Data: (port_name, ixia_ip, gateway_ip, starting_prefix)
# All destination ports advertise the same prefix
BAG_DEST_PORT_CONFIG_DATA = [
    (
        "Ethernet5/13/1",
        "2401:db00:11b:d8a1::a9",
        "2401:db00:11b:d8a1::a8",
        "4000:3:1::",
    ),
    (
        "Ethernet5/14/1",
        "2401:db00:11b:d8a1::ab",
        "2401:db00:11b:d8a1::aa",
        "4000:3:1::",
    ),
    (
        "Ethernet5/15/1",
        "2401:db00:11b:d8a1::ad",
        "2401:db00:11b:d8a1::ac",
        "4000:3:1::",
    ),
    (
        "Ethernet5/16/1",
        "2401:db00:11b:d8a1::af",
        "2401:db00:11b:d8a1::ae",
        "4000:3:1::",
    ),
]

# Combined BAG Port Config Data (for backward compatibility)
BAG_PORT_CONFIG_DATA = BAG_SOURCE_PORT_CONFIG_DATA + BAG_DEST_PORT_CONFIG_DATA

# EDSW003 IXIA Ports (derived from port config data)
EDSW003_N000_IXIA_PORTS = [port for port, _, _, _ in EDSW003_N000_PORT_CONFIG_DATA]
EDSW003_N001_IXIA_PORTS = [port for port, _, _, _ in EDSW003_N001_PORT_CONFIG_DATA]

# Source BAG IXIA Ports
BAG_SOURCE_IXIA_PORTS = [port for port, _, _, _ in BAG_SOURCE_PORT_CONFIG_DATA]

# Destination BAG IXIA Ports
BAG_DEST_IXIA_PORTS = [port for port, _, _, _ in BAG_DEST_PORT_CONFIG_DATA]

# Combined (keep existing for compatibility)
BAG_HYPERPORT_IXIA_PORTS = BAG_SOURCE_IXIA_PORTS + BAG_DEST_IXIA_PORTS

# Hyperport Endpoints
HYPERPORT_EDSW003_ENDPOINTS = [
    Endpoint(
        name="edsw003.n000.l201.snc1",
        dut=True,
        ixia_ports=EDSW003_N000_IXIA_PORTS,
    ),
    Endpoint(
        name="edsw003.n001.l201.snc1",
        dut=True,
        ixia_ports=EDSW003_N001_IXIA_PORTS,
    ),
]

HYPERPORT_BAG_ENDPOINTS = [
    Endpoint(
        name="bag001.snc1",
        dut=True,
        ixia_ports=BAG_HYPERPORT_IXIA_PORTS,
    ),
]

HYPERPORT_ALL_ENDPOINTS = HYPERPORT_EDSW003_ENDPOINTS + HYPERPORT_BAG_ENDPOINTS

# Traffic Endpoints for EDSW003 N000
EDSW003_N000_TRAFFIC_ENDPOINTS = [
    TrafficEndpoint(
        name=f"edsw003.n000.l201.snc1:{port}",
        network_group_index=0,
        device_group_index=0,
    )
    for port in EDSW003_N000_IXIA_PORTS
]

# Traffic Endpoints for EDSW003 N001
EDSW003_N001_TRAFFIC_ENDPOINTS = [
    TrafficEndpoint(
        name=f"edsw003.n001.l201.snc1:{port}",
        network_group_index=0,
        device_group_index=0,
    )
    for port in EDSW003_N001_IXIA_PORTS
]

# Individual Traffic Endpoints for N000
N000_PORT_17_1_ENDPOINT = TrafficEndpoint(
    name="edsw003.n000.l201.snc1:eth1/17/1",
    network_group_index=0,
    device_group_index=0,
)

N000_PORT_23_1_ENDPOINT = TrafficEndpoint(
    name="edsw003.n000.l201.snc1:eth1/23/1",
    network_group_index=0,
    device_group_index=0,
)

# Individual Traffic Endpoints for N001
N001_PORT_17_1_ENDPOINT = TrafficEndpoint(
    name="edsw003.n001.l201.snc1:eth1/17/1",
    network_group_index=0,
    device_group_index=0,
)

N001_PORT_23_1_ENDPOINT = TrafficEndpoint(
    name="edsw003.n001.l201.snc1:eth1/23/1",
    network_group_index=0,
    device_group_index=0,
)

# Traffic Endpoints for Source BAG
BAG_SOURCE_TRAFFIC_ENDPOINTS = [
    TrafficEndpoint(
        name=f"bag001.snc1:{port}",
        network_group_index=0,
        device_group_index=0,
    )
    for port in BAG_SOURCE_IXIA_PORTS
]

# Traffic Endpoints for Destination BAG
BAG_DEST_TRAFFIC_ENDPOINTS = [
    TrafficEndpoint(
        name=f"bag001.snc1:{port}",
        network_group_index=0,
        device_group_index=0,
    )
    for port in BAG_DEST_IXIA_PORTS
]

# Combined (keep existing for compatibility)
BAG_HYPERPORT_TRAFFIC_ENDPOINTS = (
    BAG_SOURCE_TRAFFIC_ENDPOINTS + BAG_DEST_TRAFFIC_ENDPOINTS
)

# Traffic Item Configs
# BAG Source to Destination Traffic Item
BAG_TRAFFIC_ITEM_CONFIG = BasicTrafficItemConfig(
    name="BGP_BAG_SOURCE_TO_DEST",
    bidirectional=False,
    merge_destinations=False,
    line_rate=95,
    frame_size_settings=ixia_types.FrameSize(
        type=ixia_types.FrameSizeType.RANDOM,
        random_min=64,
        random_max=9000,
    ),
    src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
    src_endpoints=BAG_SOURCE_TRAFFIC_ENDPOINTS,
    dest_endpoints=BAG_DEST_TRAFFIC_ENDPOINTS,
    traffic_type=ixia_types.TrafficType.IPV6,
    tracking_types=[
        ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM,
        ixia_types.TrafficStatsTrackingType.FLOW_GROUP,
    ],
)

HYPERPORT_TRAFFIC_ITEM_CONFIGS = [
    BasicTrafficItemConfig(
        name="BGP_N000_17_TO_N001_17",
        bidirectional=True,
        merge_destinations=False,
        line_rate=95,
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
        line_rate=95,
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
        line_rate=95,
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
        line_rate=95,
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
    BAG_TRAFFIC_ITEM_CONFIG,
]

HYPERPORT_TRAFFIC_ITEM_MAP = {
    "BGP_N000_17_TO_N001_17": "BGP_N000_17_TO_N001_17",
    "BGP_N000_23_TO_N001_23": "BGP_N000_23_TO_N001_23",
    "BGP_N000_23_TO_N001_17": "BGP_N000_23_TO_N001_17",
    "BGP_N000_17_TO_N001_23": "BGP_N000_17_TO_N001_23",
    "BGP_BAG_SOURCE_TO_DEST": "BGP_BAG_SOURCE_TO_DEST",
}

# Hyperport BasicPortConfigs for EDSW003 N000 with BGP (AS 65061)
HYPERPORT_EDSW003_N000_BASIC_PORT_CONFIGS = [
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

# Hyperport BasicPortConfigs for EDSW003 N001 with BGP (AS 65062)
HYPERPORT_EDSW003_N001_BASIC_PORT_CONFIGS = [
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

# Combined EDSW003 BasicPortConfigs
HYPERPORT_EDSW003_BASIC_PORT_CONFIGS = (
    HYPERPORT_EDSW003_N000_BASIC_PORT_CONFIGS
    + HYPERPORT_EDSW003_N001_BASIC_PORT_CONFIGS
)

# Source BAG BasicPortConfigs (AS 65063)
HYPERPORT_BAG_SOURCE_BASIC_PORT_CONFIGS = [
    create_basic_port_config(
        endpoint=f"bag001.snc1:{port}",
        starting_ip=ixia_ip,
        gateway_ip=gateway_ip,
        local_as=65063,
        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
        starting_prefixes=prefix,
        bgp_communities=BAG_BGP_COMMUNITIES,
    )
    for port, ixia_ip, gateway_ip, prefix in BAG_SOURCE_PORT_CONFIG_DATA
]

# Destination BAG BasicPortConfigs (AS 65063)
HYPERPORT_BAG_DEST_BASIC_PORT_CONFIGS = [
    create_basic_port_config(
        endpoint=f"bag001.snc1:{port}",
        starting_ip=ixia_ip,
        gateway_ip=gateway_ip,
        local_as=65063,
        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
        starting_prefixes=prefix,
        bgp_communities=BAG_BGP_COMMUNITIES,
    )
    for port, ixia_ip, gateway_ip, prefix in BAG_DEST_PORT_CONFIG_DATA
]

# Combined (keep existing for compatibility)
HYPERPORT_BAG_BASIC_PORT_CONFIGS = (
    HYPERPORT_BAG_SOURCE_BASIC_PORT_CONFIGS + HYPERPORT_BAG_DEST_BASIC_PORT_CONFIGS
)

# Combined Hyperport BasicPortConfigs
HYPERPORT_ALL_BASIC_PORT_CONFIGS = (
    HYPERPORT_BAG_BASIC_PORT_CONFIGS + HYPERPORT_EDSW003_BASIC_PORT_CONFIGS
)


def create_hyperport_snc_bag_test_config(
    test_config_name: str = "HYPERPORT_SNC_BAG_TEST_CONFIGS",
    basset_pool: str = "networkai.test",
    longevity_duration: int = 360,
) -> TestConfig:
    """
    Create a test configuration for Hyperport SNC EDSW003.

    Args:
        test_config_name: Name of the test configuration
        basset_pool: Basset pool name
        longevity_duration: Duration in seconds for longevity test

    Returns:
        TestConfig: Complete test configuration
    """
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

    # Add TC-level checks to generated disruptive playbooks
    _disruptive_playbooks = list(
        get_hyperport_bag_disruptive_playbooks(
            traffic_items_to_start=[
                HYPERPORT_TRAFFIC_ITEM_MAP["BGP_N000_17_TO_N001_17"],
                HYPERPORT_TRAFFIC_ITEM_MAP["BGP_N000_23_TO_N001_23"],
            ],
            device_regexes=["bag001.snc1"],
        )
    )
    _disruptive_playbooks = [
        _pb(
            prechecks=list(_pb.prechecks or []) + _tc_prechecks,
            postchecks=list(_pb.postchecks or []) + _tc_postchecks,
        )
        for _pb in _disruptive_playbooks
    ]

    return TestConfig(
        name=test_config_name,
        ixia_protocol_verification_timeout=300,
        basset_pool=basset_pool,
        endpoints=HYPERPORT_ALL_ENDPOINTS,
        setup_tasks=[],
        basic_port_configs=HYPERPORT_ALL_BASIC_PORT_CONFIGS,
        basic_traffic_item_configs=HYPERPORT_TRAFFIC_ITEM_CONFIGS,
        # Deprecated - define at playbook level
        # postchecks (moved to each playbook)
        # Deprecated - define at playbook level
        # prechecks (moved to each playbook)
        playbooks=[
            create_hyperport_snc_bag_longevity_playbook(
                traffic_items_to_start=[
                    HYPERPORT_TRAFFIC_ITEM_MAP["BGP_N000_17_TO_N001_17"],
                    HYPERPORT_TRAFFIC_ITEM_MAP["BGP_N000_23_TO_N001_23"],
                ],
                longevity_duration=longevity_duration,
                prechecks=_tc_prechecks,
                postchecks=_tc_postchecks,
            ),
            *_disruptive_playbooks,
        ],
    )


# Hyperport test configuration instance
HYPERPORT_SNC_BAG_TEST_CONFIGS = [create_hyperport_snc_bag_test_config()]
