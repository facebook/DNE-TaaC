# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
from ixia.ixia import types as ixia_types
from taac.test_as_a_config.types import (
    BasicPortConfig,
    BasicTrafficItemConfig,
    BgpConfig,
    DeviceGroupConfig,
    Endpoint,
    IpAddressesConfig,
    RouteScale,
    RouteScaleSpec,
    TrafficEndpoint,
)

TRAFFIC_ITEM_CONFIGS = []
TRAFFIC_ITEM_MAP = {}

from taac.packet_headers import DSF_RDMA_PACKET_HEADERS

DSF_FRAME_SIZES = ixia_types.FrameSize(
    type=ixia_types.FrameSizeType.CUSTOM_IMIX,
    imix_weight={94: 1, 96: 18, 192: 3, 512: 1, 1200: 1, 4600: 76},
)

IXIA_L1_PFC_PORT_CONFIG = ixia_types.L1Config(
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

EDSW001_N000_IXIA_PORTS = [
    "eth1/20/1",
]
EDSW002_N000_IXIA_PORTS = [
    "eth1/20/1",
]
EDSW001_N001_IXIA_PORTS = [
    "eth1/20/1",
]
EDSW002_N001_IXIA_PORTS = [
    "eth1/20/1",
]
BAG001_IXIA_PORTS = [
    "Ethernet3/12/1",
    "Ethernet4/12/1",
    "Ethernet4/14/1",
    "Ethernet4/32/1",
]

BAG_SINGLE_NODE_TEST_ENDPOINTS = [
    Endpoint(
        name="bag001.snc1",
        dut=True,
        ixia_ports=BAG001_IXIA_PORTS,
    ),
]

BAG_SNC1_END_POINTS = [
    Endpoint(
        name="edsw001.n000.l201.snc1",
        dut=True,
        ixia_ports=EDSW001_N000_IXIA_PORTS,
    ),
    Endpoint(
        name="edsw002.n000.l201.snc1",
        ixia_ports=EDSW002_N000_IXIA_PORTS,
    ),
    Endpoint(
        name="edsw001.n001.l201.snc1",
        dut=True,
        ixia_ports=EDSW001_N000_IXIA_PORTS,
    ),
    Endpoint(
        name="edsw002.n001.l201.snc1",
        ixia_ports=EDSW002_N000_IXIA_PORTS,
    ),
    Endpoint(
        name="bag001.snc1",
        dut=True,
        ixia_ports=BAG001_IXIA_PORTS,
    ),
]

PLANE1_TRAFFIC_ENDPOINTS = [
    TrafficEndpoint(
        name=f"edsw001.n000.l201.snc1:{port}",
        network_group_index=0,
    )
    for port in EDSW001_N000_IXIA_PORTS
]
PLANE1_TRAFFIC_ENDPOINTS.extend(
    TrafficEndpoint(
        name=f"edsw002.n000.l201.snc1:{port}",
        network_group_index=0,
    )
    for port in EDSW002_N000_IXIA_PORTS
)

PLANE2_TRAFFIC_ENDPOINTS = [
    TrafficEndpoint(
        name=f"edsw001.n001.l201.snc1:{port}",
        network_group_index=0,
    )
    for port in EDSW001_N001_IXIA_PORTS
]
PLANE2_TRAFFIC_ENDPOINTS.extend(
    TrafficEndpoint(
        name=f"edsw002.n001.l201.snc1:{port}",
        network_group_index=0,
    )
    for port in EDSW002_N001_IXIA_PORTS
)

BAG001_SINGLE_NODE_TEST_TRAFFIC_SRC_ENDPOINTS = [
    TrafficEndpoint(
        name=f"bag001.snc1:{port}",
    )
    for port in BAG001_IXIA_PORTS[:-1]
]

BAG001_SINGLE_NODE_TEST_TRAFFIC_DST_ENDPOINTS = [
    TrafficEndpoint(
        name=f"bag001.snc1:{port}",
    )
    for port in BAG001_IXIA_PORTS[-1:]
]

BAG001_SINGLE_NODE_TEST_FULL_TRAFFIC_ENDPOINTS = [
    TrafficEndpoint(
        name=f"bag001.snc1:{port}",
    )
    for port in BAG001_IXIA_PORTS
]

TRAFFIC_ITEM_CONFIGS.append(
    BasicTrafficItemConfig(
        src_endpoints=PLANE1_TRAFFIC_ENDPOINTS,
        dest_endpoints=PLANE2_TRAFFIC_ENDPOINTS,
        traffic_type=ixia_types.TrafficType.IPV6,
        name="PLANE1_TO_PLANE2_ALL_PORTS",
        line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
        line_rate=90,
        bidirectional=True,
        packet_headers=DSF_RDMA_PACKET_HEADERS,
        full_mesh=False,
        src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
        frame_size_settings=DSF_FRAME_SIZES,
    )
)

TRAFFIC_ITEM_CONFIGS.append(
    BasicTrafficItemConfig(
        src_endpoints=BAG001_SINGLE_NODE_TEST_FULL_TRAFFIC_ENDPOINTS,
        dest_endpoints=BAG001_SINGLE_NODE_TEST_FULL_TRAFFIC_ENDPOINTS,
        traffic_type=ixia_types.TrafficType.IPV6,
        name="FULL_MESH_TRAFFIC_FOR_SINGEL_BAG001_SNC1",
        line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
        line_rate=90,
        bidirectional=True,
        packet_headers=DSF_RDMA_PACKET_HEADERS,
        full_mesh=True,
        src_dest_mesh=ixia_types.SrcDestMeshType.FULL_MESH,
        frame_size_settings=DSF_FRAME_SIZES,
    )
)

TRAFFIC_ITEM_MAP["PLANE1_TO_PLANE2_ALL_PORTS"] = "PLANE1_TO_PLANE2_ALL_PORTS"
TRAFFIC_ITEM_MAP["FULL_MESH_TRAFFIC_FOR_SINGEL_BAG001_SNC1"] = (
    "FULL_MESH_TRAFFIC_FOR_SINGEL_BAG001_SNC1"
)

PLANE1_PLANE2_PORT_CONFIGS = [
    BasicPortConfig(
        endpoint="edsw001.n000.l201.snc1:eth1/20/1",
        l1_config=IXIA_L1_PFC_PORT_CONFIG,
        device_group_configs=[
            DeviceGroupConfig(
                device_group_index=0,
                multiplier=1,
                v6_addresses_config=IpAddressesConfig(),
                v6_bgp_config=BgpConfig(
                    local_as_4_bytes=65061,
                    enable_4_byte_local_as=True,
                    is_confed=False,
                    bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                    route_scales=[
                        RouteScaleSpec(
                            network_group_index=0,
                            v6_route_scale=RouteScale(
                                multiplier=1,
                                prefix_count=100,
                                prefix_length=64,
                                starting_prefixes="4000:1:1::",
                                prefix_step="0:0:0:1:0:0:0:0",
                                bgp_communities=[
                                    "65446:30",
                                    "65441:1028",
                                ],
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                            ),
                        ),
                    ],
                ),
            ),
        ],
    ),
    BasicPortConfig(
        endpoint="edsw002.n000.l201.snc1:eth1/20/1",
        l1_config=IXIA_L1_PFC_PORT_CONFIG,
        device_group_configs=[
            DeviceGroupConfig(
                device_group_index=0,
                multiplier=1,
                v6_addresses_config=IpAddressesConfig(),
                v6_bgp_config=BgpConfig(
                    local_as_4_bytes=65061,
                    enable_4_byte_local_as=True,
                    is_confed=False,
                    bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                    route_scales=[
                        RouteScaleSpec(
                            network_group_index=0,
                            v6_route_scale=RouteScale(
                                multiplier=1,
                                prefix_count=100,
                                prefix_length=64,
                                starting_prefixes="4000:1:2::",
                                prefix_step="0:0:0:1:0:0:0:0",
                                bgp_communities=[
                                    "65446:30",
                                    "65441:1028",
                                ],
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                            ),
                        ),
                    ],
                ),
            ),
        ],
    ),
    BasicPortConfig(
        endpoint="edsw001.n001.l201.snc1:eth1/20/1",
        l1_config=IXIA_L1_PFC_PORT_CONFIG,
        device_group_configs=[
            DeviceGroupConfig(
                device_group_index=0,
                multiplier=1,
                v6_addresses_config=IpAddressesConfig(),
                v6_bgp_config=BgpConfig(
                    local_as_4_bytes=65062,
                    enable_4_byte_local_as=True,
                    is_confed=False,
                    bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                    route_scales=[
                        RouteScaleSpec(
                            network_group_index=0,
                            v6_route_scale=RouteScale(
                                multiplier=1,
                                prefix_count=100,
                                prefix_length=64,
                                starting_prefixes="4000:2:1::",
                                prefix_step="0:0:0:1:0:0:0:0",
                                bgp_communities=[
                                    "65446:30",
                                    "65441:1028",
                                ],
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                            ),
                        ),
                    ],
                ),
            ),
        ],
    ),
    BasicPortConfig(
        endpoint="edsw002.n001.l201.snc1:eth1/20/1",
        l1_config=IXIA_L1_PFC_PORT_CONFIG,
        device_group_configs=[
            DeviceGroupConfig(
                device_group_index=0,
                multiplier=1,
                v6_addresses_config=IpAddressesConfig(),
                v6_bgp_config=BgpConfig(
                    local_as_4_bytes=65062,
                    enable_4_byte_local_as=True,
                    is_confed=False,
                    bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                    route_scales=[
                        RouteScaleSpec(
                            network_group_index=0,
                            v6_route_scale=RouteScale(
                                multiplier=1,
                                prefix_count=100,
                                prefix_length=64,
                                starting_prefixes="4000:2:2::",
                                prefix_step="0:0:0:1:0:0:0:0",
                                bgp_communities=[
                                    "65446:30",
                                    "65441:1028",
                                ],
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                            ),
                        ),
                    ],
                ),
            ),
        ],
    ),
]

BAG001_SINGLE_NODE_TEST_BASIC_PORT_CONFIGS = [
    BasicPortConfig(
        endpoint="bag001.snc1:Ethernet3/12/1",
        l1_config=IXIA_L1_PFC_PORT_CONFIG,
        device_group_configs=[
            DeviceGroupConfig(
                device_group_index=0,
                multiplier=1,
                v6_addresses_config=IpAddressesConfig(
                    starting_ip="2401:db00:11b:d8a1::17",
                    increment_ip="::2",
                    gateway_starting_ip="2401:db00:11b:d8a1::16",
                    gateway_increment_ip="::2",
                    mask=127,
                ),
            ),
        ],
    ),
    BasicPortConfig(
        endpoint="bag001.snc1:Ethernet4/12/1",
        l1_config=IXIA_L1_PFC_PORT_CONFIG,
        device_group_configs=[
            DeviceGroupConfig(
                device_group_index=0,
                multiplier=1,
                v6_addresses_config=IpAddressesConfig(
                    starting_ip="2401:db00:11b:d8a1::5f",
                    increment_ip="::2",
                    gateway_starting_ip="2401:db00:11b:d8a1::5e",
                    gateway_increment_ip="::2",
                    mask=127,
                ),
            ),
        ],
    ),
    BasicPortConfig(
        endpoint="bag001.snc1:Ethernet4/14/1",
        l1_config=IXIA_L1_PFC_PORT_CONFIG,
        device_group_configs=[
            DeviceGroupConfig(
                device_group_index=0,
                multiplier=1,
                v6_addresses_config=IpAddressesConfig(
                    starting_ip="2401:db00:11b:d8a1::63",
                    increment_ip="::2",
                    gateway_starting_ip="2401:db00:11b:d8a1::62",
                    gateway_increment_ip="::2",
                    mask=127,
                ),
            ),
        ],
    ),
    BasicPortConfig(
        endpoint="bag001.snc1:Ethernet4/32/1",
        l1_config=IXIA_L1_PFC_PORT_CONFIG,
        device_group_configs=[
            DeviceGroupConfig(
                device_group_index=0,
                multiplier=1,
                v6_addresses_config=IpAddressesConfig(
                    starting_ip="2401:db00:11b:d8a1::87",
                    increment_ip="::2",
                    gateway_starting_ip="2401:db00:11b:d8a1::86",
                    gateway_increment_ip="::2",
                    mask=127,
                ),
            ),
        ],
    ),
]

BAG_SNC1_BASIC_PORT_CONFIGS = (
    BAG001_SINGLE_NODE_TEST_BASIC_PORT_CONFIGS + PLANE1_PLANE2_PORT_CONFIGS
)
