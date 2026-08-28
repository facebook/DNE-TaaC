# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
Test config for CBAG <-> BAG001 RDMA test for AI BB.

Focused single-peer variant of cbag_bag_test_config: runs RDMA traffic between
cbag001.qzp1 and bag001.qzq1 only (bag002 excluded). Reuses the endpoints, port
configs, peer groups, and BGP-peer builders from cbag_bag_test_config so this
config stays in sync with that testbed.

Traffic is a set of RDMA incast items: each bag001.qzq1 source port sends to a
single cbag001.qzp1 destination port (Ethernet4/32/1), each with its own line
rate. Frame size and packet headers match the RDMA items in cbag_bag_test_config.
"""

import json

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
from taac.testconfigs.ai_bb.cbag_bag_test_config import (
    _build_bag_bgp_peer_config,
    _build_cbag_bgp_peer_config,
    _build_ixia_bgp_peers_config,
    BAG001_BASIC_PORT_CONFIGS,
    BAG001_PORT_CONFIG_DATA,
    BAG001_TRAFFIC_ENDPOINTS,
    BAG_ASN,
    BAG_IXIA_PEER_GROUP,
    CBAG001_BASIC_PORT_CONFIGS,
    CBAG001_PORT_CONFIG_DATA,
    CBAG001_TRAFFIC_ENDPOINTS,
    CBAG_ASN,
    CBAG_BAG1_INTERFACES,
    CBAG_BAG_ENDPOINTS,
    CBAG_IXIA_PEER_GROUP,
    create_basic_port_config,
    FABRIC_AGENTS,
    FABRIC_MODULES,
    LINECARD_AGENTS,
    LINECARD_MODULES,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config.types import (
    BasicTrafficItemConfig,
    TestConfig,
    TrafficEndpoint,
)

# IXIA-facing local ASNs (match cbag_bag_test_config)
CBAG_IXIA_LOCAL_AS = 65062
BAG_IXIA_LOCAL_AS = 65063

CBAG_BAG_BENCHMARK_PEERGROUP = "PEERGROUP_CBAG_BAG_ACCEPT_EVERYTHING"

# Only this cbag<->bag link carries BGP for the benchmark. It is index 0 of both
# CBAG_BAG1_INTERFACES and BAG_CBAG_INTERFACES, so both sides resolve to the same
# /127 pair (CBAG_BAG1_IP[0]).
CBAG_BAG_BENCHMARK_INTERFACES = ["Ethernet3/1/1"]

# IXIA ports carrying benchmark traffic. Both devices use the same port names.
CBAG_BAG001_BENCHMARK_IXIA_PORTS = ["Ethernet4/32/1", "Ethernet4/32/5"]

# Reuse cbag001 + bag001 endpoints, dropping bag002
CBAG_BAG001_ENDPOINTS = [
    endpoint
    for endpoint in CBAG_BAG_ENDPOINTS
    if endpoint.name in ("cbag001.qzp1", "bag001.qzq1")
]

# The traffic generator reads an IPv6 address off every port in Endpoint.ixia_ports,
# so an endpoint must not advertise ports that the setup tasks never address.
CBAG_BAG001_BENCHMARK_ENDPOINTS = [
    endpoint(
        ixia_ports=CBAG_BAG001_BENCHMARK_IXIA_PORTS,
        direct_ixia_connections=[
            connection
            # pyrefly: ignore [not-iterable]
            for connection in endpoint.direct_ixia_connections
            if connection.interface in CBAG_BAG001_BENCHMARK_IXIA_PORTS
        ],
    )
    for endpoint in CBAG_BAG001_ENDPOINTS
]


def _benchmark_port_config_data(
    port_config_data: list[tuple[str, str, str, str]],
) -> list[tuple[str, str, str, str]]:
    """Select the benchmark IXIA ports by name, in CBAG_BAG001_BENCHMARK_IXIA_PORTS order."""
    by_port = {entry[0]: entry for entry in port_config_data}
    return [by_port[port] for port in CBAG_BAG001_BENCHMARK_IXIA_PORTS]


def _benchmark_traffic_endpoints(
    traffic_endpoints: list[TrafficEndpoint],
) -> list[TrafficEndpoint]:
    """Keep only the benchmark ports, preserving order so ONE_TO_ONE pairs line up."""
    suffixes = tuple(f":{port}" for port in CBAG_BAG001_BENCHMARK_IXIA_PORTS)
    return [
        traffic_endpoint
        for traffic_endpoint in traffic_endpoints
        if traffic_endpoint.name.endswith(suffixes)
    ]


CBAG001_BENCHMARK_PORT_CONFIG_DATA = _benchmark_port_config_data(
    CBAG001_PORT_CONFIG_DATA
)
BAG001_BENCHMARK_PORT_CONFIG_DATA = _benchmark_port_config_data(BAG001_PORT_CONFIG_DATA)

# RDMA incast traffic: each bag001.qzq1 source port sends to a single cbag001.qzp1
# destination port. Frame size / packet headers match the RDMA items in
# cbag_bag_test_config.
CBAG001_INCAST_DEST_PORT = "Ethernet4/32/1"

# (traffic_item_name, bag001 source port, line rate percent)
CBAG_BAG001_INCAST_TRAFFIC_DATA = [
    ("RDMA_BAG001_4_32_5_TO_CBAG001", "Ethernet4/32/5", 50),
    ("RDMA_BAG001_4_36_1_TO_CBAG001", "Ethernet4/36/1", 40),
    ("RDMA_BAG001_4_32_1_TO_CBAG001", "Ethernet4/32/1", 50),
    ("RDMA_BAG001_4_36_5_TO_CBAG001", "Ethernet4/36/5", 50),
]

# Subset of incast items the playbooks start
CBAG_BAG001_TRAFFIC_ITEMS_TO_START = [
    "RDMA_BAG001_4_32_5_TO_CBAG001",
    "RDMA_BAG001_4_36_1_TO_CBAG001",
]


def _build_incast_traffic_item(
    name: str, src_port: str, line_rate: int
) -> BasicTrafficItemConfig:
    """Single-flow RDMA incast item: bag001 src_port -> cbag001 dest port."""
    return BasicTrafficItemConfig(
        name=name,
        bidirectional=False,
        line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
        line_rate=line_rate,
        src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
        src_endpoints=[
            TrafficEndpoint(
                name=f"bag001.qzq1:{src_port}",
                network_group_index=0,
                device_group_index=0,
            )
        ],
        dest_endpoints=[
            TrafficEndpoint(
                name=f"cbag001.qzp1:{CBAG001_INCAST_DEST_PORT}",
                network_group_index=0,
                device_group_index=0,
            )
        ],
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
    )


CBAG_BAG001_TRAFFIC_ITEM_CONFIGS = [
    _build_incast_traffic_item(name, src_port, line_rate)
    for name, src_port, line_rate in CBAG_BAG001_INCAST_TRAFFIC_DATA
]

CBAG_BAG001_BASIC_PORT_CONFIGS = CBAG001_BASIC_PORT_CONFIGS + BAG001_BASIC_PORT_CONFIGS


def _build_cbag_bag001_inter_device_peers() -> dict:
    """cbag001 inter-device BGP peers scoped to the bag001-facing links only.

    Reuses _build_cbag_bgp_peer_config (which configures both the bag001- and
    bag002-facing interfaces) and keeps only the bag001-facing ports.
    """
    all_peers = json.loads(_build_cbag_bgp_peer_config())
    return {port: all_peers[port] for port in CBAG_BAG1_INTERFACES}


def _build_cbag_bag001_benchmark_inter_device_peers(port_config: str) -> dict:
    """Inter-device BGP peers scoped to the single benchmark link.

    Takes the JSON emitted by _build_cbag_bgp_peer_config / _build_bag_bgp_peer_config
    (which cover every cbag<->bag interface) and keeps only CBAG_BAG_BENCHMARK_INTERFACES.
    Those builders hardcode the production peer groups, so the peer group is
    overridden here to the ACCEPT_EVERYTHING group that setup creates.
    """
    all_peers = json.loads(port_config)
    return {
        port: [
            {**peer, "peer_group_name": CBAG_BAG_BENCHMARK_PEERGROUP}
            for peer in all_peers[port]
        ]
        for port in CBAG_BAG_BENCHMARK_INTERFACES
    }


CBAG_BAG001_SETUP_TASKS = [
    # Backup EOS configs on both devices
    create_backup_running_config_task(
        hostname="cbag001.qzp1",
        backup_file="cbag001_backup_config",
    ),
    create_backup_running_config_task(
        hostname="bag001.qzq1",
        backup_file="bag001_backup_config",
    ),
    # Create IXIA peer groups with PROPAGATE_EVERYTHING on both devices
    create_eos_bgp_peer_group_task(
        hostname="cbag001.qzp1",
        peer_group_name=CBAG_IXIA_PEER_GROUP,
        remote_as=CBAG_IXIA_LOCAL_AS,
        activate=True,
        ipv4_unicast=False,
        ipv6_unicast=True,
        route_map_in="PROPAGATE_EVERYTHING",
        route_map_out="PROPAGATE_EVERYTHING",
    ),
    create_eos_bgp_peer_group_task(
        hostname="bag001.qzq1",
        peer_group_name=BAG_IXIA_PEER_GROUP,
        remote_as=BAG_IXIA_LOCAL_AS,
        activate=True,
        ipv4_unicast=False,
        ipv6_unicast=True,
        route_map_in="PROPAGATE_EVERYTHING",
        route_map_out="PROPAGATE_EVERYTHING",
    ),
    # Create BGP peers for IXIA + inter-device connections on both devices
    create_configure_eos_parallel_bgp_peers_task(
        hostname="cbag001.qzp1",
        config_json=json.dumps(
            {
                **json.loads(
                    _build_ixia_bgp_peers_config(
                        CBAG001_PORT_CONFIG_DATA,
                        CBAG_IXIA_PEER_GROUP,
                        CBAG_IXIA_LOCAL_AS,
                    )
                ),
                **_build_cbag_bag001_inter_device_peers(),
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
                        BAG_IXIA_LOCAL_AS,
                    )
                ),
                **json.loads(_build_bag_bgp_peer_config(is_bag1=True)),
            }
        ),
    ),
]


def create_cbag_bag001_test_config(
    test_config_name: str = "CBAG_BAG001_TEST_CONFIG",
    longevity_duration: int = 3600 * 12,
) -> TestConfig:
    """
    Create a CBAG <-> BAG001 RDMA test configuration for AI BB.

    Args:
        test_config_name: Name of the test configuration
        longevity_duration: Duration in seconds for longevity test

    Returns:
        TestConfig: Complete test configuration
    """
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

    _disruptive_playbooks = list(
        create_cbag_disruptive_playbooks(
            device_regexes=["cbag001.qzp1"],
            traffic_items_to_start=CBAG_BAG001_TRAFFIC_ITEMS_TO_START,
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
        endpoints=CBAG_BAG001_ENDPOINTS,
        setup_tasks=CBAG_BAG001_SETUP_TASKS,
        basic_port_configs=CBAG_BAG001_BASIC_PORT_CONFIGS,
        basic_traffic_item_configs=CBAG_BAG001_TRAFFIC_ITEM_CONFIGS,
        playbooks=[
            create_longevity_playbook(
                playbook_name="test_cbag_bag001_longevity",
                longevity_duration=longevity_duration,
                # prechecks=_tc_prechecks,
                # postchecks=_tc_postchecks,
                snapshot_checks=_tc_snapshot_checks,
                traffic_items_to_start=CBAG_BAG001_TRAFFIC_ITEMS_TO_START,
            ),
            *_disruptive_playbooks,
        ],
    )


# CBAG_BAG001 test config instance
CBAG_BAG001_TEST_CONFIGS = [create_cbag_bag001_test_config()]

CBAG001_BENCHMARK_BASIC_PORT_CONFIGS = [
    create_basic_port_config(
        endpoint=f"cbag001.qzp1:{port}",
        starting_ip=ixia_ip,
        gateway_ip=gateway_ip,
        local_as=CBAG_IXIA_LOCAL_AS,
        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
        starting_prefixes=starting_prefix,
        bgp_communities=[],
    )
    for port, ixia_ip, gateway_ip, starting_prefix in CBAG001_BENCHMARK_PORT_CONFIG_DATA
]

BAG001_BENCHMARK_BASIC_PORT_CONFIGS = [
    create_basic_port_config(
        endpoint=f"bag001.qzq1:{port}",
        starting_ip=ixia_ip,
        gateway_ip=gateway_ip,
        local_as=BAG_IXIA_LOCAL_AS,
        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
        starting_prefixes=starting_prefix,
        bgp_communities=[],
    )
    for port, ixia_ip, gateway_ip, starting_prefix in BAG001_BENCHMARK_PORT_CONFIG_DATA
]

CBAG_BAG001_BENCHMARK_BASIC_PORT_CONFIGS = (
    CBAG001_BENCHMARK_BASIC_PORT_CONFIGS + BAG001_BENCHMARK_BASIC_PORT_CONFIGS
)

CBAG_BAG1_BENCHMARK_TRAFFIC_ITEM_CONFIGS = [
    BasicTrafficItemConfig(
        name="RDMA_CBAG001_TO_BAG001",
        bidirectional=False,
        line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
        line_rate=99,
        src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
        src_endpoints=_benchmark_traffic_endpoints(BAG001_TRAFFIC_ENDPOINTS),
        dest_endpoints=_benchmark_traffic_endpoints(CBAG001_TRAFFIC_ENDPOINTS),
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


CBAG_BAG001_BENCHMARK_SETUP_TASKS = [
    # Backup EOS configs on both devices
    create_backup_running_config_task(
        hostname="cbag001.qzp1",
        backup_file="cbag001_backup_config",
    ),
    create_backup_running_config_task(
        hostname="bag001.qzq1",
        backup_file="bag001_backup_config",
    ),
    # Create IXIA peer groups with PROPAGATE_EVERYTHING on both devices
    create_eos_bgp_peer_group_task(
        hostname="cbag001.qzp1",
        peer_group_name=CBAG_IXIA_PEER_GROUP,
        remote_as=CBAG_IXIA_LOCAL_AS,
        activate=True,
        ipv4_unicast=False,
        ipv6_unicast=True,
        route_map_in="PROPAGATE_EVERYTHING",
        route_map_out="PROPAGATE_EVERYTHING",
    ),
    create_eos_bgp_peer_group_task(
        hostname="bag001.qzq1",
        peer_group_name=BAG_IXIA_PEER_GROUP,
        remote_as=BAG_IXIA_LOCAL_AS,
        activate=True,
        ipv4_unicast=False,
        ipv6_unicast=True,
        route_map_in="PROPAGATE_EVERYTHING",
        route_map_out="PROPAGATE_EVERYTHING",
    ),
    # Create CBAG_BAG peer group with PROPAGATE_EVERYTHING on both devices
    create_eos_bgp_peer_group_task(
        hostname="cbag001.qzp1",
        peer_group_name=CBAG_BAG_BENCHMARK_PEERGROUP,
        remote_as=BAG_ASN,
        activate=True,
        ipv4_unicast=False,
        ipv6_unicast=True,
        route_map_in="PROPAGATE_EVERYTHING",
        route_map_out="PROPAGATE_EVERYTHING",
    ),
    create_eos_bgp_peer_group_task(
        hostname="bag001.qzq1",
        peer_group_name=CBAG_BAG_BENCHMARK_PEERGROUP,
        remote_as=CBAG_ASN,
        activate=True,
        ipv4_unicast=False,
        ipv6_unicast=True,
        route_map_in="PROPAGATE_EVERYTHING",
        route_map_out="PROPAGATE_EVERYTHING",
    ),
    create_configure_eos_parallel_bgp_peers_task(
        hostname="cbag001.qzp1",
        config_json=json.dumps(
            {
                **json.loads(
                    _build_ixia_bgp_peers_config(
                        CBAG001_BENCHMARK_PORT_CONFIG_DATA,
                        CBAG_IXIA_PEER_GROUP,
                        CBAG_IXIA_LOCAL_AS,
                    )
                ),
                **_build_cbag_bag001_benchmark_inter_device_peers(
                    _build_cbag_bgp_peer_config()
                ),
            }
        ),
    ),
    create_configure_eos_parallel_bgp_peers_task(
        hostname="bag001.qzq1",
        config_json=json.dumps(
            {
                **json.loads(
                    _build_ixia_bgp_peers_config(
                        BAG001_BENCHMARK_PORT_CONFIG_DATA,
                        BAG_IXIA_PEER_GROUP,
                        BAG_IXIA_LOCAL_AS,
                    )
                ),
                **_build_cbag_bag001_benchmark_inter_device_peers(
                    _build_bag_bgp_peer_config(is_bag1=True)
                ),
            }
        ),
    ),
]


def create_cbag_bag001_benchmarking_test_config(
    test_config_name: str = "CBAG_BAG001_BENCHMARK_TEST_CONFIG",
    longevity_duration: int = 300,
) -> TestConfig:
    """
    Create a CBAG <-> BAG001 RDMA test config for AI BB.
    Used for benchmarking Millisecond loss during OLS Protection Switching

    Args:
        test_config_name: Name of the test configuration
        longevity_duration: Duration in seconds for longevity test

    Returns:
        TestConfig: Complete test configuration

    """

    return TestConfig(
        name=test_config_name,
        ixia_protocol_verification_timeout=300,
        endpoints=CBAG_BAG001_BENCHMARK_ENDPOINTS,
        setup_tasks=CBAG_BAG001_BENCHMARK_SETUP_TASKS,
        basic_port_configs=CBAG_BAG001_BENCHMARK_BASIC_PORT_CONFIGS,
        basic_traffic_item_configs=CBAG_BAG1_BENCHMARK_TRAFFIC_ITEM_CONFIGS,
        playbooks=[
            create_longevity_playbook(
                playbook_name="test_cbag_bag001_longevity",
                longevity_duration=longevity_duration,
                traffic_items_to_start=["RDMA_CBAG001_TO_BAG001"],
            ),
        ],
    )


# CBAG_BAG001_BENCHMARK test config instance
CBAG_BAG001_TEST_CONFIGS.append(create_cbag_bag001_benchmarking_test_config())
