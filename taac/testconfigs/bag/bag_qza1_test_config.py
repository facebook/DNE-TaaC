# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
BAG ASH6 <-> QZA1 Test Configuration

Test config for BAG-to-BAG traffic between bag001.ash6 and bag001.qza1.
Both devices connect to ixia07.netcastle.ash6.

Includes:
- RDMA unidirectional traffic ASH6->QZA1 (95% line rate)
- DSF protocol traffic items (NC, MONITORING, BE, RDMA_IB at 70% line rate)
- BGP session scale: 10 sessions per IXIA port (40 total)
- Longevity playbook
- Disruptive playbooks (device reboot, fabric/linecard restart, agent crash)

IXIA Port Mapping:
  bag001.qza1:Ethernet13/1/1 <-> ixia07.netcastle.ash6:1/13
  bag001.qza1:Ethernet13/2/1 <-> ixia07.netcastle.ash6:1/14
  bag001.ash6:Ethernet3/4/1  <-> ixia07.netcastle.ash6:1/15
  bag001.ash6:Ethernet3/5/1  <-> ixia07.netcastle.ash6:1/16

Visual Topology & Config Schematic:
  https://pxl.cl/9rg8c
"""

import json

from ixia.ixia import types as ixia_types
from taac.health_checks.healthcheck_definitions import (
    create_core_dumps_snapshot_check,
    create_ixia_packet_loss_check,
)
from taac.playbooks.playbook_definitions import (
    create_bag_qza1_longevity_playbook,
    create_bag_qza_agent_terminate_playbooks,
    create_bag_qza_disruptive_playbooks,  # noqa
    create_dsf_proto_ipv6_traffic_config,
    IXIA_ENABLE_PFC_PORT_CONFIG,
)
from taac.task_definitions import (
    create_configure_eos_parallel_bgp_peers_task,
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

BAG_BGP_COMMUNITIES = ["65529:52780", "65529:52779", "65520:52791"]

# =============================================================================
# BGP Session Scale Configuration
# 10 sessions per IXIA port = 40 total (20 per device)
# increment_ip="::100" (256 decimal) avoids IP conflicts with production interfaces
# on the same /64 subnet (QZA1 has 6 production ports using ::0 through ::b)
# Session 0 on each port matches the existing production BGP peer
# =============================================================================
BGP_SESSION_MULTIPLIER = 10
BGP_SESSION_INCREMENT = "::100"
BGP_NEW_SESSIONS_PER_PORT = BGP_SESSION_MULTIPLIER - 1  # 9 new sessions (1 exists)

# =============================================================================
# BAG001.ASH6 Port Config Data: (port_name, ixia_ip, gateway_ip, starting_prefix)
# IXIA simulates bag002.ash6 (a-endpoint)
# =============================================================================
BAG001_ASH6_PORT_CONFIG_DATA = [
    ("Ethernet3/4/1", "2401:db00:206b:d900::", "2401:db00:206b:d900::1", "5000:1:1::"),
    ("Ethernet3/5/1", "2401:db00:206b:d900::2", "2401:db00:206b:d900::3", "5000:2:1::"),
]

# =============================================================================
# BAG001.QZA1 Port Config Data: (port_name, ixia_ip, gateway_ip, starting_prefix)
# IXIA simulates STSW (z-endpoint)
# =============================================================================
BAG001_QZA1_PORT_CONFIG_DATA = [
    ("Ethernet13/1/1", "2401:db00:2d1b:d8d0::1", "2401:db00:2d1b:d8d0::", "6000:1:1::"),
    (
        "Ethernet13/2/1",
        "2401:db00:2d1b:d8d0::3",
        "2401:db00:2d1b:d8d0::2",
        "6000:2:1::",
    ),
]

# IXIA port lists
BAG001_ASH6_IXIA_PORTS = [port for port, _, _, _ in BAG001_ASH6_PORT_CONFIG_DATA]
BAG001_QZA1_IXIA_PORTS = [port for port, _, _, _ in BAG001_QZA1_PORT_CONFIG_DATA]

# =============================================================================
# Endpoints (no direct_ixia_connections — use LLDP/optical switch discovery)
# =============================================================================
BAG_ASH6_QZA_ENDPOINTS = [
    Endpoint(
        name="bag001.ash6",
        dut=False,
        ixia_ports=BAG001_ASH6_IXIA_PORTS,
    ),
    Endpoint(
        name="bag001.qza1",
        dut=True,
        ixia_ports=BAG001_QZA1_IXIA_PORTS,
    ),
]

# =============================================================================
# Individual Traffic Endpoints (for per-port traffic items)
# =============================================================================
ASH6_PORT_3_4_ENDPOINT = TrafficEndpoint(
    name="bag001.ash6:Ethernet3/4/1",
    network_group_index=0,
    device_group_index=0,
)

ASH6_PORT_3_5_ENDPOINT = TrafficEndpoint(
    name="bag001.ash6:Ethernet3/5/1",
    network_group_index=0,
    device_group_index=0,
)

QZA1_PORT_13_1_ENDPOINT = TrafficEndpoint(
    name="bag001.qza1:Ethernet13/1/1",
    network_group_index=0,
    device_group_index=0,
)

QZA1_PORT_13_2_ENDPOINT = TrafficEndpoint(
    name="bag001.qza1:Ethernet13/2/1",
    network_group_index=0,
    device_group_index=0,
)

# =============================================================================
# Traffic Item Configs (ASH6 -> QZA1, per-port 1:1 flows)
# Flow 1: Ethernet3/4/1 -> Ethernet13/1/1
# Flow 2: Ethernet3/5/1 -> Ethernet13/2/1
# =============================================================================
BAG_ASH6_QZA_TRAFFIC_ITEM_CONFIGS = [
    BasicTrafficItemConfig(
        name="RDMA_ASH6_3_4_TO_QZA1_13_1",
        bidirectional=False,
        line_rate=95,
        frame_size_settings=ixia_types.FrameSize(
            type=ixia_types.FrameSizeType.RANDOM,
            random_min=64,
            random_max=9000,
        ),
        src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
        src_endpoints=[ASH6_PORT_3_4_ENDPOINT],
        dest_endpoints=[QZA1_PORT_13_1_ENDPOINT],
        traffic_type=ixia_types.TrafficType.IPV6,
        tracking_types=[
            ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM,
            ixia_types.TrafficStatsTrackingType.FLOW_GROUP,
        ],
    ),
    BasicTrafficItemConfig(
        name="RDMA_ASH6_3_5_TO_QZA1_13_2",
        bidirectional=False,
        line_rate=95,
        frame_size_settings=ixia_types.FrameSize(
            type=ixia_types.FrameSizeType.RANDOM,
            random_min=64,
            random_max=9000,
        ),
        src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
        src_endpoints=[ASH6_PORT_3_5_ENDPOINT],
        dest_endpoints=[QZA1_PORT_13_2_ENDPOINT],
        traffic_type=ixia_types.TrafficType.IPV6,
        tracking_types=[
            ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM,
            ixia_types.TrafficStatsTrackingType.FLOW_GROUP,
        ],
    ),
]

# =============================================================================
# DSF Traffic Item Configs (ASH6 -> QZA1, 70% line rate, per-port per-protocol)
# =============================================================================
BAG_ASH6_QZA_DSF_TRAFFIC_ITEM_CONFIGS = [
    # NC per-port
    create_dsf_proto_ipv6_traffic_config(
        proto="NC",
        src_endpoints=[ASH6_PORT_3_4_ENDPOINT],
        dest_endpoints=[QZA1_PORT_13_1_ENDPOINT],
        name="DSF_NC_3_4_TO_13_1",
        line_rate=70,
    ),
    create_dsf_proto_ipv6_traffic_config(
        proto="NC",
        src_endpoints=[ASH6_PORT_3_5_ENDPOINT],
        dest_endpoints=[QZA1_PORT_13_2_ENDPOINT],
        name="DSF_NC_3_5_TO_13_2",
        line_rate=70,
    ),
    # MONITORING per-port
    create_dsf_proto_ipv6_traffic_config(
        proto="MONITORING",
        src_endpoints=[ASH6_PORT_3_4_ENDPOINT],
        dest_endpoints=[QZA1_PORT_13_1_ENDPOINT],
        name="DSF_MONITORING_3_4_TO_13_1",
        line_rate=70,
    ),
    create_dsf_proto_ipv6_traffic_config(
        proto="MONITORING",
        src_endpoints=[ASH6_PORT_3_5_ENDPOINT],
        dest_endpoints=[QZA1_PORT_13_2_ENDPOINT],
        name="DSF_MONITORING_3_5_TO_13_2",
        line_rate=70,
    ),
    # BE per-port
    create_dsf_proto_ipv6_traffic_config(
        proto="BE",
        src_endpoints=[ASH6_PORT_3_4_ENDPOINT],
        dest_endpoints=[QZA1_PORT_13_1_ENDPOINT],
        name="DSF_BE_3_4_TO_13_1",
        line_rate=70,
    ),
    create_dsf_proto_ipv6_traffic_config(
        proto="BE",
        src_endpoints=[ASH6_PORT_3_5_ENDPOINT],
        dest_endpoints=[QZA1_PORT_13_2_ENDPOINT],
        name="DSF_BE_3_5_TO_13_2",
        line_rate=70,
    ),
    # RDMA_IB per-port
    create_dsf_proto_ipv6_traffic_config(
        proto="RDMA_IB",
        src_endpoints=[ASH6_PORT_3_4_ENDPOINT],
        dest_endpoints=[QZA1_PORT_13_1_ENDPOINT],
        name="DSF_RDMA_IB_3_4_TO_13_1",
        line_rate=70,
    ),
    create_dsf_proto_ipv6_traffic_config(
        proto="RDMA_IB",
        src_endpoints=[ASH6_PORT_3_5_ENDPOINT],
        dest_endpoints=[QZA1_PORT_13_2_ENDPOINT],
        name="DSF_RDMA_IB_3_5_TO_13_2",
        line_rate=70,
    ),
]

# All traffic item configs
BAG_ASH6_QZA_ALL_TRAFFIC_ITEM_CONFIGS = (
    BAG_ASH6_QZA_TRAFFIC_ITEM_CONFIGS + BAG_ASH6_QZA_DSF_TRAFFIC_ITEM_CONFIGS
)

# RDMA traffic item names (started during playbooks)
BAG_ASH6_QZA_RDMA_TRAFFIC_ITEM_NAMES = [
    "RDMA_ASH6_3_4_TO_QZA1_13_1",
    "RDMA_ASH6_3_5_TO_QZA1_13_2",
]

# =============================================================================
# Basic Port Configs (multiplier=10 for BGP session scale)
#
# increment_ip="::100" (256 decimal) avoids IP conflicts with production
# interfaces on the same /64 subnet. With increment=0x100:
#   Port 3/4/1: IXIA IPs ::0, ::100, ::200, ...  Gateways ::1, ::101, ::201, ...
#   Port 3/5/1: IXIA IPs ::2, ::102, ::202, ...  Gateways ::3, ::103, ::203, ...
# =============================================================================


def _create_scaled_port_config(
    endpoint: str,
    starting_ip: str,
    gateway_ip: str,
    local_as: int,
    starting_prefixes: str,
) -> BasicPortConfig:
    """Build a single per-port IXIA config with scaled BGP sessions.

    Generates one IXIA device group with
    ``multiplier=BGP_SESSION_MULTIPLIER`` (10) eBGP peers, each on a
    /127 IPv6 link offset by ``BGP_SESSION_INCREMENT`` (``::100``) to
    avoid collision with production interface IPs on the same /64.
    Each peer advertises 100 IPv6 /64 prefixes tagged with
    :data:`BAG_BGP_COMMUNITIES`.

    Args:
        endpoint: ``"<device>:<port>"`` IXIA endpoint name (e.g.
            ``"bag001.qza1:Ethernet13/1/1"``).
        starting_ip: First IXIA-side IPv6 address; subsequent peers add
            ``::100``.
        gateway_ip: First BAG-side IPv6 gateway address; subsequent
            peers add ``::100``.
        local_as: 4-byte local AS used by the IXIA-emulated peer
            (``4200000009`` for ASH6 a-side, ``65341`` for QZA1 z-side).
        starting_prefixes: First /64 advertised; subsequent prefixes
            step by ``0:0:0:1:0:0:0:0``.

    Returns:
        ``BasicPortConfig`` containing 10 EIBGP peers.
    """
    return BasicPortConfig(
        endpoint=endpoint,
        l1_config=IXIA_ENABLE_PFC_PORT_CONFIG.l1_config,
        device_group_configs=[
            DeviceGroupConfig(
                device_group_index=0,
                multiplier=BGP_SESSION_MULTIPLIER,
                v6_addresses_config=IpAddressesConfig(
                    starting_ip=starting_ip,
                    increment_ip=BGP_SESSION_INCREMENT,
                    gateway_starting_ip=gateway_ip,
                    gateway_increment_ip=BGP_SESSION_INCREMENT,
                    mask=127,
                ),
                v6_bgp_config=BgpConfig(
                    local_as_4_bytes=local_as,
                    enable_4_byte_local_as=True,
                    is_confed=False,
                    bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                    route_scales=[
                        RouteScaleSpec(
                            network_group_index=0,
                            v6_route_scale=RouteScale(
                                multiplier=1,
                                prefix_count=100,
                                prefix_length=64,
                                starting_prefixes=starting_prefixes,
                                prefix_step="0:0:0:1:0:0:0:0",
                                bgp_communities=BAG_BGP_COMMUNITIES,
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                            ),
                        ),
                    ],
                ),
            ),
        ],
    )


BAG001_ASH6_BASIC_PORT_CONFIGS = [
    _create_scaled_port_config(
        endpoint=f"bag001.ash6:{port}",
        starting_ip=ixia_ip,
        gateway_ip=gateway_ip,
        local_as=4200000009,
        starting_prefixes=starting_prefix,
    )
    for port, ixia_ip, gateway_ip, starting_prefix in BAG001_ASH6_PORT_CONFIG_DATA
]

BAG001_QZA1_BASIC_PORT_CONFIGS = [
    _create_scaled_port_config(
        endpoint=f"bag001.qza1:{port}",
        starting_ip=ixia_ip,
        gateway_ip=gateway_ip,
        local_as=65341,
        starting_prefixes=starting_prefix,
    )
    for port, ixia_ip, gateway_ip, starting_prefix in BAG001_QZA1_PORT_CONFIG_DATA
]

BAG_ASH6_QZA_BASIC_PORT_CONFIGS = (
    BAG001_ASH6_BASIC_PORT_CONFIGS + BAG001_QZA1_BASIC_PORT_CONFIGS
)

# =============================================================================
# Disruptive test parameters
#
# bag001.qza1 module inventory (from `show module | json`):
#   Linecards: 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14
#   Fabrics: Fabric1-5 (Fabric6 is fan spinner — skip)
#   Supervisor: slot 1
# =============================================================================
LINECARD_NUMBERS = [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14]
FABRIC_NUMBERS = [1, 2, 3, 4, 5]

FABRIC_MODULES = ["Fabric1"]
LINECARD_MODULES = ["Linecard3"]
FABRIC_AGENTS = ["SandFabric-Fabric1", "SandFabric-Fabric2", "SandFabric-Fabric3"]
LINECARD_AGENTS = ["SandFapNi-Linecard3", "SandFapNi-Linecard4"]


# =============================================================================
# Test Config
# =============================================================================
def create_bag_qza1_test_config(
    test_config_name: str = "BAG_QZA1_TEST_CONFIG",
    longevity_duration: int = 360,
) -> TestConfig:
    """Build the BAG ASH6 <-> QZA1 ``TestConfig``.

    Composes the full longevity + disruptive qualification:

    * Endpoints: ``bag001.ash6`` and ``bag001.qza1`` (both DUTs), 2
      IXIA ports each.
    * Setup: parallel BGP peer creation on both devices, 9 new sessions
      per port (in addition to the existing production peer) using
      ``create_configure_eos_parallel_bgp_peers_task``.
    * Traffic: 2 RDMA flows at 95% line rate plus 8 DSF protocol flows
      (NC / MONITORING / BE / RDMA_IB at 70% line rate).
    * Playbooks: longevity, disruptive (device reboot, fabric/linecard
      restart) targeting ``bag001.qza1`` with 25 iterations, and agent
      terminate playbooks against the ``LINECARD_NUMBERS`` /
      ``FABRIC_NUMBERS`` inventory.
    * TestConfig-level health checks (``DSF_DRAIN_STATE_CHECK``,
      ``IXIA_PACKET_LOSS_CHECK``, ``CORE_DUMPS_CHECK``) are injected
      into every playbook rather than the deprecated TestConfig
      ``prechecks`` / ``postchecks`` / ``snapshot_checks`` fields.

    Args:
        test_config_name: Name registered in ``TestConfig.name``.
        longevity_duration: Duration in seconds for the
            ``create_bag_qza1_longevity_playbook`` step.

    Returns:
        A ``TestConfig`` ready to register in
        ``BAG_QZA1_TEST_CONFIGS`` and consumed by
        ``testconfigs/internal/all.py``.
    """
    # TestConfig-level checks moved to playbook level
    _prechecks = [
        create_ixia_packet_loss_check(
            thresholds=[hc_types.PacketLossThreshold(str_value="0.1")],
            clear_traffic_stats=True,
        ),
    ]
    _postchecks = [
        create_ixia_packet_loss_check(
            thresholds=[
                hc_types.PacketLossThreshold(
                    str_value="0",
                    metric=hc_types.PacketLossMetric.PERCENTAGE,
                ),
            ],
        ),
    ]
    _snapshot_checks = [create_core_dumps_snapshot_check()]

    # Build disruptive playbooks and add TestConfig-level checks to each
    disruptive_playbooks = create_bag_qza_disruptive_playbooks(
        device_regexes=["bag001.qza1"],
        traffic_items_to_start=BAG_ASH6_QZA_RDMA_TRAFFIC_ITEM_NAMES,
        fabric_modules=FABRIC_MODULES,
        linecard_modules=LINECARD_MODULES,
        fabric_agents=FABRIC_AGENTS,
        linecard_agents=LINECARD_AGENTS,
        iteration=25,
    )
    disruptive_playbooks = [
        pb(
            prechecks=_prechecks,
            postchecks=list(pb.postchecks or []) + _postchecks,
            snapshot_checks=list(pb.snapshot_checks or []) + _snapshot_checks,
        )
        for pb in disruptive_playbooks
    ]

    # Setup tasks: configure 9 additional BGP peers per port on each device.
    # Session 0 on each port matches the existing production peer; sessions 1-9
    # are new. IPs offset by BGP_SESSION_INCREMENT (::4) from the existing peer.
    setup_tasks = [
        create_configure_eos_parallel_bgp_peers_task(
            hostname="bag001.ash6",
            config_json=json.dumps(
                {
                    "Ethernet3/4/1": [
                        {
                            "starting_ip": "2401:db00:206b:d900::101",
                            "increment_ip": BGP_SESSION_INCREMENT,
                            "gateway_starting_ip": "2401:db00:206b:d900::100",
                            "gateway_increment_ip": BGP_SESSION_INCREMENT,
                            "num_sessions": BGP_NEW_SESSIONS_PER_PORT,
                            "remote_as_4_byte": 4200000009,
                            "prefix_length": 127,
                            "peer_group_name": "PEERGROUP_BAG_STSW_LC04_V6",
                            "ipv6_unicast": True,
                            "ipv4_unicast": False,
                        }
                    ],
                    "Ethernet3/5/1": [
                        {
                            "starting_ip": "2401:db00:206b:d900::103",
                            "increment_ip": BGP_SESSION_INCREMENT,
                            "gateway_starting_ip": "2401:db00:206b:d900::102",
                            "gateway_increment_ip": BGP_SESSION_INCREMENT,
                            "num_sessions": BGP_NEW_SESSIONS_PER_PORT,
                            "remote_as_4_byte": 4200000009,
                            "prefix_length": 127,
                            "peer_group_name": "PEERGROUP_BAG_STSW_LC04_V6",
                            "ipv6_unicast": True,
                            "ipv4_unicast": False,
                        }
                    ],
                }
            ),
        ),
        create_configure_eos_parallel_bgp_peers_task(
            hostname="bag001.qza1",
            config_json=json.dumps(
                {
                    "Ethernet13/1/1": [
                        {
                            "starting_ip": "2401:db00:2d1b:d8d0::100",
                            "increment_ip": BGP_SESSION_INCREMENT,
                            "gateway_starting_ip": "2401:db00:2d1b:d8d0::101",
                            "gateway_increment_ip": BGP_SESSION_INCREMENT,
                            "num_sessions": BGP_NEW_SESSIONS_PER_PORT,
                            "remote_as_4_byte": 65341,
                            "prefix_length": 127,
                            "peer_group_name": "PEERGROUP_BAG_STSW_LC13_V6",
                            "ipv6_unicast": True,
                            "ipv4_unicast": False,
                            "description": "et1-1-1.stsw013.s003.l201.qza1:T=us:U=facebook",
                        }
                    ],
                    "Ethernet13/2/1": [
                        {
                            "starting_ip": "2401:db00:2d1b:d8d0::102",
                            "increment_ip": BGP_SESSION_INCREMENT,
                            "gateway_starting_ip": "2401:db00:2d1b:d8d0::103",
                            "gateway_increment_ip": BGP_SESSION_INCREMENT,
                            "num_sessions": BGP_NEW_SESSIONS_PER_PORT,
                            "remote_as_4_byte": 65341,
                            "prefix_length": 127,
                            "peer_group_name": "PEERGROUP_BAG_STSW_LC13_V6",
                            "ipv6_unicast": True,
                            "ipv4_unicast": False,
                            "description": "et1-2-1.stsw013.s003.l201.qza1:T=us:U=facebook",
                        }
                    ],
                }
            ),
        ),
    ]

    return TestConfig(
        name=test_config_name,
        endpoints=BAG_ASH6_QZA_ENDPOINTS,
        setup_tasks=setup_tasks,
        basic_port_configs=BAG_ASH6_QZA_BASIC_PORT_CONFIGS,
        basic_traffic_item_configs=BAG_ASH6_QZA_ALL_TRAFFIC_ITEM_CONFIGS,
        playbooks=[
            create_bag_qza1_longevity_playbook(
                longevity_duration=longevity_duration,
                traffic_items_to_start=BAG_ASH6_QZA_RDMA_TRAFFIC_ITEM_NAMES,
                prechecks=_prechecks,
                postchecks=_postchecks,
                snapshot_checks=_snapshot_checks,
            ),
            *disruptive_playbooks,
            *create_bag_qza_agent_terminate_playbooks(
                device_regexes=["bag001.qza1"],
                traffic_items_to_start=BAG_ASH6_QZA_RDMA_TRAFFIC_ITEM_NAMES,
                linecard_numbers=LINECARD_NUMBERS,
                fabric_numbers=FABRIC_NUMBERS,
            ),
        ],
    )


BAG_QZA1_TEST_CONFIGS = [create_bag_qza1_test_config()]
