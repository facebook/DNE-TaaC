# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
Test config for CBAG BAG test for AI BB
"""

import json
import typing as t

from ixia.ixia import types as ixia_types
from taac.health_checks.healthcheck_definitions import (
    create_core_dumps_snapshot_check,
    create_ixia_packet_loss_check,
    create_lldp_check,
    create_port_state_check,
    create_unclean_exit_check,
)
from taac.packet_headers import DSF_RDMA_IB_PACKET_HEADERS
from taac.playbooks.playbook_definitions import (
    create_cbag_disruptive_playbooks,
    create_longevity_playbook,
)
from taac.task_definitions import (
    create_backup_running_config_task,
    create_configure_eos_parallel_bgp_peers_task,
    create_eos_bgp_peer_group_task,
)
from taac.utils.json_thrift_utils import thrift_to_json
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import (
    BasicPortConfig,
    BasicTrafficItemConfig,
    BgpConfig,
    DeviceGroupConfig,
    Endpoint,
    IpAddressesConfig,
    Params,
    RouteScale,
    RouteScaleSpec,
    TestConfig,
    TrafficEndpoint,
)

DSF_L1_PFC_CONFIG = ixia_types.L1Config(
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


def create_basic_port_config(
    endpoint: str,
    starting_ip: str,
    gateway_ip: str,
    local_as: int,
    bgp_peer_type: ixia_types.BgpPeerType,
    starting_prefixes: str,
    bgp_communities: list[str],
    increment_ip: str = "::2",
    gateway_increment_ip: str = "::2",
    mask: int = 127,
    prefix_count: int = 100,
    prefix_length: int = 64,
) -> BasicPortConfig:
    """Create a BasicPortConfig with common defaults."""
    return BasicPortConfig(
        endpoint=endpoint,
        l1_config=DSF_L1_PFC_CONFIG,
        device_group_configs=[
            DeviceGroupConfig(
                device_group_index=0,
                multiplier=1,
                v6_addresses_config=IpAddressesConfig(
                    starting_ip=starting_ip,
                    increment_ip=increment_ip,
                    gateway_starting_ip=gateway_ip,
                    gateway_increment_ip=gateway_increment_ip,
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


# CBAG001 port config data: (port_name, ixia_ip, gateway_ip, starting_prefix)
CBAG001_PORT_CONFIG_DATA = [
    ("Ethernet4/32/1", "2401:db00:11b:d8a0::1", "2401:db00:11b:d8a0::", "6000:1:1::"),
    ("Ethernet4/32/5", "2401:db00:11b:d8a1::1", "2401:db00:11b:d8a1::", "6000:2:1::"),
    ("Ethernet4/36/1", "2401:db00:11b:d8a2::1", "2401:db00:11b:d8a2::", "6000:3:1::"),
    ("Ethernet4/36/5", "2401:db00:11b:d8a3::1", "2401:db00:11b:d8a3::", "6000:4:1::"),
]

# BAG001 port config data: (port_name, ixia_ip, gateway_ip, starting_prefix)
BAG001_PORT_CONFIG_DATA = [
    ("Ethernet4/32/1", "2401:db00:11b:d8b0::1", "2401:db00:11b:d8b0::", "5000:1:1::"),
    ("Ethernet4/32/5", "2401:db00:11b:d8b1::1", "2401:db00:11b:d8b1::", "5000:2:1::"),
    ("Ethernet4/36/1", "2401:db00:11b:d8b2::1", "2401:db00:11b:d8b2::", "5000:3:1::"),
    ("Ethernet4/36/5", "2401:db00:11b:d8b3::1", "2401:db00:11b:d8b3::", "5000:4:1::"),
]

# BAG002 port config data: (port_name, ixia_ip, gateway_ip, starting_prefix)
BAG002_PORT_CONFIG_DATA = [
    ("Ethernet4/32/1", "2401:db00:11b:d8c0::1", "2401:db00:11b:d8c0::", "4000:1:1::"),
    ("Ethernet4/32/5", "2401:db00:11b:d8c1::1", "2401:db00:11b:d8c1::", "4000:2:1::"),
    ("Ethernet4/36/1", "2401:db00:11b:d8c2::1", "2401:db00:11b:d8c2::", "4000:3:1::"),
    ("Ethernet4/36/5", "2401:db00:11b:d8c3::1", "2401:db00:11b:d8c3::", "4000:4:1::"),
]

# IXIA ports
CBAG001_PORTS = [port for port, _, _, _ in CBAG001_PORT_CONFIG_DATA]
BAG001_PORTS = [port for port, _, _, _ in BAG001_PORT_CONFIG_DATA]
BAG002_PORTS = [port for port, _, _, _ in BAG002_PORT_CONFIG_DATA]


def get_direct_ixia_connections(
    ixia_chassis_ip: str,
    ixia_ports: t.List[str],
    device_ports: t.List[str],
) -> t.List[taac_types.DirectIxiaConnection]:
    direct_connections = []

    for ixia_port, device_port in zip(ixia_ports, device_ports):
        direct_connections.append(
            taac_types.DirectIxiaConnection(
                interface=device_port,
                ixia_chassis_ip=ixia_chassis_ip,
                ixia_port=ixia_port,
            )
        )

    return direct_connections


CBAG001_DIRECT_IXIA_CONNECTIONS = get_direct_ixia_connections(
    "2401:db00:2076:30fd::3001",
    ["1/1", "1/2", "1/3", "1/4"],
    ["Ethernet4/32/1", "Ethernet4/32/5", "Ethernet4/36/1", "Ethernet4/36/5"],
)

BAG001_DIRECT_IXIA_CONNECTIONS = get_direct_ixia_connections(
    "2401:db00:2076:30fd::3001",
    ["1/5", "1/6", "1/7", "1/8"],
    ["Ethernet4/32/1", "Ethernet4/32/5", "Ethernet4/36/1", "Ethernet4/36/5"],
)

BAG002_DIRECT_IXIA_CONNECTIONS = get_direct_ixia_connections(
    "2401:db00:2076:30fd::3001",
    ["1/9", "1/10", "1/11", "1/12"],
    ["Ethernet4/32/1", "Ethernet4/32/5", "Ethernet4/36/1", "Ethernet4/36/5"],
)


CBAG_BAG_ENDPOINTS = [
    Endpoint(
        name="cbag001.qzp1",
        dut=True,
        ixia_ports=CBAG001_PORTS,
        direct_ixia_connections=CBAG001_DIRECT_IXIA_CONNECTIONS,
    ),
    Endpoint(
        name="bag001.qzq1",
        dut=False,
        ixia_ports=BAG001_PORTS,
        direct_ixia_connections=BAG001_DIRECT_IXIA_CONNECTIONS,
    ),
    Endpoint(
        name="bag002.qzq1",
        dut=False,
        ixia_ports=BAG002_PORTS,
        direct_ixia_connections=BAG002_DIRECT_IXIA_CONNECTIONS,
    ),
]

CBAG001_TRAFFIC_ENDPOINTS = [
    TrafficEndpoint(
        name=f"cbag001.qzp1:{port}",
        network_group_index=0,
        device_group_index=0,
    )
    for port in CBAG001_PORTS
]

BAG001_TRAFFIC_ENDPOINTS = [
    TrafficEndpoint(
        name=f"bag001.qzq1:{port}",
        network_group_index=0,
        device_group_index=0,
    )
    for port in BAG001_PORTS
]

BAG002_TRAFFIC_ENDPOINTS = [
    TrafficEndpoint(
        name=f"bag002.qzq1:{port}",
        network_group_index=0,
        device_group_index=0,
    )
    for port in BAG002_PORTS
]

LINECARD_AGENTS = ["SandFapNi-Linecard3"]
FABRIC_AGENTS = [
    "SandFabric-Fabric1",
    "SandFabric-Fabric2",
    # "SandFabric-Fabric3",
    # "SandFabric-Fabric4",
    # "SandFabric-Fabric5",
]

LINECARD_MODULES = ["Linecard3"]
FABRIC_MODULES = [
    "Fabric1",
    "Fabric2",
    # "Fabric3",
    # "Fabric4",
    # "Fabric5"
]

CBAG_BAG_TRAFFIC_ITEM_CONFIGS = [
    BasicTrafficItemConfig(
        name="RDMA_CBAG001_TO_BAG001",
        bidirectional=False,
        line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
        line_rate=50,
        src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
        src_endpoints=BAG001_TRAFFIC_ENDPOINTS,
        dest_endpoints=CBAG001_TRAFFIC_ENDPOINTS,
        skip_default_l4_protocol=True,
        traffic_type=ixia_types.TrafficType.IPV6,
        tracking_types=[
            ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM,
            ixia_types.TrafficStatsTrackingType.FLOW_GROUP,
        ],
        packet_headers=DSF_RDMA_IB_PACKET_HEADERS,
        frame_size_settings=ixia_types.FrameSize(
            type=ixia_types.FrameSizeType.CUSTOM_IMIX,
            imix_weight={94: 1, 96: 18, 192: 3, 512: 1, 1200: 1, 4600: 76, 9000: 76},
        ),
    ),
    BasicTrafficItemConfig(
        name="RDMA_CBAG001_TO_BAG002",
        bidirectional=False,
        line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
        line_rate=50,
        src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
        src_endpoints=BAG002_TRAFFIC_ENDPOINTS,
        dest_endpoints=CBAG001_TRAFFIC_ENDPOINTS,
        skip_default_l4_protocol=True,
        traffic_type=ixia_types.TrafficType.IPV6,
        tracking_types=[
            ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM,
            ixia_types.TrafficStatsTrackingType.FLOW_GROUP,
        ],
        packet_headers=DSF_RDMA_IB_PACKET_HEADERS,
        frame_size_settings=ixia_types.FrameSize(
            type=ixia_types.FrameSizeType.CUSTOM_IMIX,
            imix_weight={94: 1, 96: 18, 192: 3, 512: 1, 1200: 1, 4600: 76, 9000: 76},
        ),
    ),
]

CBAG001_BASIC_PORT_CONFIGS = [
    create_basic_port_config(
        endpoint=f"cbag001.qzp1:{port}",
        starting_ip=ixia_ip,
        gateway_ip=gateway_ip,
        local_as=65062,
        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
        starting_prefixes=starting_prefix,
        bgp_communities=["65441:65", "65446:30", "65446:201", "65441:66"],
    )
    for port, ixia_ip, gateway_ip, starting_prefix in CBAG001_PORT_CONFIG_DATA
]

BAG001_BASIC_PORT_CONFIGS = [
    create_basic_port_config(
        endpoint=f"bag001.qzq1:{port}",
        starting_ip=ixia_ip,
        gateway_ip=gateway_ip,
        local_as=65063,
        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
        starting_prefixes=starting_prefix,
        bgp_communities=["65441:129", "65446:30", "65446:201", "65441:130"],
    )
    for port, ixia_ip, gateway_ip, starting_prefix in BAG001_PORT_CONFIG_DATA
]

BAG002_BASIC_PORT_CONFIGS = [
    create_basic_port_config(
        endpoint=f"bag002.qzq1:{port}",
        starting_ip=ixia_ip,
        gateway_ip=gateway_ip,
        local_as=65063,
        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
        starting_prefixes=starting_prefix,
        bgp_communities=["65441:129", "65446:30", "65446:201", "65441:130"],
    )
    for port, ixia_ip, gateway_ip, starting_prefix in BAG002_PORT_CONFIG_DATA
]

CBAG_BAG_BASIC_PORT_CONFIGS = (
    CBAG001_BASIC_PORT_CONFIGS + BAG001_BASIC_PORT_CONFIGS + BAG002_BASIC_PORT_CONFIGS
)

# IXIA peer group configuration
CBAG_IXIA_PEER_GROUP = "PEERGROUP_CBAG_IXIA_V6"
BAG_IXIA_PEER_GROUP = "PEERGROUP_BAG_IXIA_V6"

# Existing inter-device peer groups
CBAG_BAG_PEER_GROUP = ["PEERGROUP_CBAG_BAG_LC03_V6", "PEERGROUP_CBAG_BAG_LC04_V6"]
BAG_CBAG_PEER_GROUP = ["PEERGROUP_BAG_CBAG_LC03_V6"]

CBAG_BAG1_INTERFACES = [f"Ethernet{i}/{j}/1" for i in range(3, 5) for j in range(1, 11)]
CBAG_BAG2_INTERFACES = [
    f"Ethernet{i}/{j}/1" for i in range(3, 5) for j in range(11, 21)
]

BAG_CBAG_INTERFACES = [f"Ethernet3/{j}/1" for j in range(1, 21)]

CBAG_BAG1_IP = [
    [f"2401:db10:11b:db{i:02x}::", f"2401:db10:11b:db{i:02x}::1"] for i in range(0, 20)
]
CBAG_BAG2_IP = [
    [f"2401:db20:11b:db{i:02x}::", f"2401:db20:11b:db{i:02x}::1"] for i in range(0, 20)
]

CBAG_ASN = 65350
BAG_ASN = 65340


def _build_cbag_bgp_peer_config(register=True) -> str:
    config = {}
    for index, port in enumerate(CBAG_BAG1_INTERFACES):
        config[port] = [
            {
                "starting_ip": CBAG_BAG1_IP[index][0],
                "increment_ip": "::2",
                "gateway_starting_ip": CBAG_BAG1_IP[index][1],
                "gateway_increment_ip": "::2",
                "num_sessions": 10,
                "remote_as_4_byte": BAG_ASN,
                "prefix_length": 127,
                "peer_group_name": CBAG_BAG_PEER_GROUP[0]
                if index < 10
                else CBAG_BAG_PEER_GROUP[1],
                "ipv6_unicast": True,
                "ipv4_unicast": False,
                "register": register,
            }
        ]
    for index, port in enumerate(CBAG_BAG2_INTERFACES):
        config[port] = [
            {
                "starting_ip": CBAG_BAG2_IP[index][0],
                "increment_ip": "::2",
                "gateway_starting_ip": CBAG_BAG2_IP[index][1],
                "gateway_increment_ip": "::2",
                "num_sessions": 10,
                "remote_as_4_byte": BAG_ASN,
                "prefix_length": 127,
                "peer_group_name": CBAG_BAG_PEER_GROUP[0]
                if index < 10
                else CBAG_BAG_PEER_GROUP[1],
                "ipv6_unicast": True,
                "ipv4_unicast": False,
                "register": register,
            }
        ]
    return json.dumps(config)


def _build_bag_bgp_peer_config(is_bag1=True, register=True) -> str:
    IP_DOMAIN = CBAG_BAG1_IP if is_bag1 else CBAG_BAG2_IP
    config = {}
    for index, port in enumerate(BAG_CBAG_INTERFACES):
        config[port] = [
            {
                "starting_ip": IP_DOMAIN[index][1],
                "increment_ip": "::2",
                "gateway_starting_ip": IP_DOMAIN[index][0],
                "gateway_increment_ip": "::2",
                "num_sessions": 10,
                "remote_as_4_byte": CBAG_ASN,
                "prefix_length": 127,
                "peer_group_name": BAG_CBAG_PEER_GROUP[0],
                "ipv6_unicast": True,
                "ipv4_unicast": False,
                "register": register,
            }
        ]
    return json.dumps(config)


def _build_ixia_bgp_peers_config(
    port_config_data: list[tuple[str, str, str, str]],
    peer_group_name: str,
    remote_as: int,
    register: bool = True,
) -> str:
    config = {}
    for port, ixia_ip, device_ip, _ in port_config_data:
        config[port] = [
            {
                "starting_ip": device_ip,
                "increment_ip": "::2",
                "gateway_starting_ip": ixia_ip,
                "gateway_increment_ip": "::2",
                "num_sessions": 1,
                "remote_as_4_byte": remote_as,
                "prefix_length": 127,
                "peer_group_name": peer_group_name,
                "ipv6_unicast": True,
                "ipv4_unicast": False,
                "register": register,
            }
        ]
    return json.dumps(config)


CBAG_BAG_SETUP_TASKS = [
    # Backup EOS configs on all devices
    create_backup_running_config_task(
        hostname="cbag001.qzp1",
        backup_file="cbag001_backup_config",
    ),
    create_backup_running_config_task(
        hostname="bag001.qzq1",
        backup_file="bag001_backup_config",
    ),
    create_backup_running_config_task(
        hostname="bag002.qzq1",
        backup_file="bag002_backup_config",
    ),
    # Create IXIA peer groups with PROPAGATE_EVERYTHING on all devices
    create_eos_bgp_peer_group_task(
        hostname="cbag001.qzp1",
        peer_group_name=CBAG_IXIA_PEER_GROUP,
        remote_as=65062,
        activate=True,
        ipv4_unicast=False,
        ipv6_unicast=True,
        route_map_in="PROPAGATE_EVERYTHING",
        route_map_out="PROPAGATE_EVERYTHING",
    ),
    create_eos_bgp_peer_group_task(
        hostname="bag001.qzq1",
        peer_group_name=BAG_IXIA_PEER_GROUP,
        remote_as=65063,
        activate=True,
        ipv4_unicast=False,
        ipv6_unicast=True,
        route_map_in="PROPAGATE_EVERYTHING",
        route_map_out="PROPAGATE_EVERYTHING",
    ),
    create_eos_bgp_peer_group_task(
        hostname="bag002.qzq1",
        peer_group_name=BAG_IXIA_PEER_GROUP,
        remote_as=65063,
        activate=True,
        ipv4_unicast=False,
        ipv6_unicast=True,
        route_map_in="PROPAGATE_EVERYTHING",
        route_map_out="PROPAGATE_EVERYTHING",
    ),
    # Create BGP peers for IXIA connections on all devices
    create_configure_eos_parallel_bgp_peers_task(
        hostname="cbag001.qzp1",
        config_json=json.dumps(
            {
                **json.loads(
                    _build_ixia_bgp_peers_config(
                        CBAG001_PORT_CONFIG_DATA,
                        CBAG_IXIA_PEER_GROUP,
                        65062,
                    )
                ),
                **json.loads(_build_cbag_bgp_peer_config()),
            }
        ),
    ),
    create_configure_eos_parallel_bgp_peers_task(
        hostname="bag001.qzq1",
        config_json=json.dumps(
            {
                **json.loads(
                    _build_ixia_bgp_peers_config(
                        BAG001_PORT_CONFIG_DATA,
                        BAG_IXIA_PEER_GROUP,
                        65063,
                    )
                ),
                **json.loads(_build_bag_bgp_peer_config(is_bag1=True)),
            }
        ),
    ),
    create_configure_eos_parallel_bgp_peers_task(
        hostname="bag002.qzq1",
        config_json=json.dumps(
            {
                **json.loads(
                    _build_ixia_bgp_peers_config(
                        BAG002_PORT_CONFIG_DATA,
                        BAG_IXIA_PEER_GROUP,
                        65063,
                    )
                ),
                **json.loads(_build_bag_bgp_peer_config(is_bag1=False)),
            }
        ),
    ),
    # Allow IXIA prefixes on CBAG-BAG inter-device peergroups (inbound only;
    # devices natively re-advertise eBGP-learned routes so no outbound filter needed)
    # CBAG001: allow BAG IXIA prefixes inbound
    # create_eos_bgp_prefix_list_task(
    #     hostname="cbag001.qzp1",
    #     prefix_list_name="ALLOW_CBAG_BAG_IXIA_V6_IN",
    #     peer_group_name=CBAG_BAG_PEER_GROUP,
    #     prefix="5000::/16",
    #     direction="in",
    #     seq=10,
    # ),
    # create_eos_bgp_prefix_list_task(
    #     hostname="cbag001.qzp1",
    #     prefix_list_name="ALLOW_CBAG_BAG_IXIA_V6_IN",
    #     peer_group_name=CBAG_BAG_PEER_GROUP,
    #     prefix="4000::/16",
    #     direction="in",
    #     seq=20,
    # ),
    # # BAG001: allow CBAG IXIA prefixes inbound
    # create_eos_bgp_prefix_list_task(
    #     hostname="bag001.qzq1",
    #     prefix_list_name="ALLOW_BAG_CBAG_IXIA_V6_IN",
    #     peer_group_name=BAG_CBAG_PEER_GROUP,
    #     prefix="6000::/16",
    #     direction="in",
    #     seq=10,
    # ),
    # # BAG002: allow CBAG IXIA prefixes inbound
    # create_eos_bgp_prefix_list_task(
    #     hostname="bag002.qzq1",
    #     prefix_list_name="ALLOW_BAG_CBAG_IXIA_V6_IN",
    #     peer_group_name=BAG_CBAG_PEER_GROUP,
    #     prefix="6000::/16",
    #     direction="in",
    #     seq=10,
    # ),
]


def create_cbag_bag_test_config(
    test_config_name: str = "CBAG_BAG_TEST_CONFIG",
    longevity_duration: int = 3600 * 12,
) -> TestConfig:
    """
    Create a test configuration for CBAG BAG test for AI BB.

    Args:
        test_config_name: Name of the test configuration
        longevity_duration: Duration in seconds for longevity test

    Returns:
        TestConfig: Complete test configuration
    """
    # TC-level checks moved to playbook level
    _tc_prechecks = [
        create_ixia_packet_loss_check(
            thresholds=[
                hc_types.PacketLossThreshold(
                    str_value="0.1",
                    metric=hc_types.PacketLossMetric.PERCENTAGE,
                ),
            ],
            clear_traffic_stats=True,
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
        create_port_state_check(),
        create_lldp_check(),
        create_unclean_exit_check(),
    ]
    _tc_snapshot_checks = [
        create_core_dumps_snapshot_check(),
    ]

    # Add TC-level checks to generated disruptive playbooks
    _disruptive_playbooks = list(
        create_cbag_disruptive_playbooks(
            device_regexes=["cbag001.qzp1"],
            traffic_items_to_start=[
                "RDMA_CBAG001_TO_BAG001",
                "RDMA_CBAG001_TO_BAG002",
            ],
            fabric_modules=FABRIC_MODULES,
            linecard_modules=LINECARD_MODULES,
            fabric_agents=FABRIC_AGENTS,
            linecard_agents=LINECARD_AGENTS,
            is_sequential=False,
            iteration=10,
        )
    )
    _disruptive_playbooks = [
        _pb(
            prechecks=_tc_prechecks + list(_pb.prechecks or []),
            postchecks=_tc_postchecks + list(_pb.postchecks or []),
            snapshot_checks=_tc_snapshot_checks + list(_pb.snapshot_checks or []),
        )
        for _pb in _disruptive_playbooks
    ]

    return TestConfig(
        name=test_config_name,
        ixia_protocol_verification_timeout=300,
        endpoints=CBAG_BAG_ENDPOINTS,
        setup_tasks=CBAG_BAG_SETUP_TASKS,
        basic_port_configs=CBAG_BAG_BASIC_PORT_CONFIGS,
        basic_traffic_item_configs=CBAG_BAG_TRAFFIC_ITEM_CONFIGS,
        playbooks=[
            create_longevity_playbook(
                playbook_name="test_cbag_bag_longevity",
                longevity_duration=longevity_duration,
                prechecks=_tc_prechecks,
                postchecks=_tc_postchecks,
                snapshot_checks=_tc_snapshot_checks,
                traffic_items_to_start=[
                    "RDMA_CBAG001_TO_BAG001",
                    "RDMA_CBAG001_TO_BAG002",
                ],
            ),
            *_disruptive_playbooks,
        ],
    )


# CBAG_BAG test config instance
CBAG_BAG_TEST_CONFIGS = [create_cbag_bag_test_config()]
