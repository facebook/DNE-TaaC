# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
Test config for CPR BC test for AI BB
"""

import json
import typing as t

from ixia.ixia import types as ixia_types
from taac.health_checks.healthcheck_definitions import (
    create_core_dumps_snapshot_check,
    create_ixia_packet_loss_check,
    create_lldp_check,
    create_port_state_check,
)
from taac.playbooks.playbook_definitions import (
    create_bc_disruptive_playbooks,
    create_cpr_disruptive_playbooks,
    create_longevity_playbook,
)
from taac.task_definitions import (
    create_backup_running_config_task,
    create_configure_eos_parallel_bgp_peers_task,
    create_configure_parallel_bgp_peers_task,
    create_coop_apply_patchers_task,
    create_coop_register_patcher_task,
    create_coop_unregister_patchers_task,
    create_eos_bgp_peer_group_task,
    create_wait_for_agent_convergence_task,
    create_wait_for_bgp_convergence_task,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types
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


CPR_IXIA_PEER_GROUP = "PEERGROUP_CPR_IXIA_V6"
BC_IXIA_PEER_GROUP = "PEERGROUP_BC_IXIA_V6"


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
    return BasicPortConfig(
        endpoint=endpoint,
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


# TODO: Fill in real IP addresses, gateways, and prefixes
# CPR001 port config data: (port_name, ixia_ip, gateway_ip, starting_prefix)
CPR001_PORT_CONFIG_DATA = [
    ("Ethernet4/32/1", "2401:db00:11b:e0a0::1", "2401:db00:11b:e0a0::", "6000:1:1::"),
    ("Ethernet4/32/5", "2401:db00:11b:e0a1::1", "2401:db00:11b:e0a1::", "6000:2:1::"),
    ("Ethernet4/36/1", "2401:db00:11b:e0a2::1", "2401:db00:11b:e0a2::", "6000:3:1::"),
    ("Ethernet4/36/5", "2401:db00:11b:e0a3::1", "2401:db00:11b:e0a3::", "6000:4:1::"),
]

# BC001.V001 port config data: (port_name, ixia_ip, gateway_ip, starting_prefix)
BC001_V001_PORT_CONFIG_DATA = [
    ("eth1/62/1", "2401:db00:11b:e0b0::1", "2401:db00:11b:e0b0::", "5000:1:1::"),
    ("eth1/62/5", "2401:db00:11b:e0b1::1", "2401:db00:11b:e0b1::", "5000:2:1::"),
]

# BC001.V004 port config data: (port_name, ixia_ip, gateway_ip, starting_prefix)
BC001_V004_PORT_CONFIG_DATA = [
    ("eth1/62/1", "2401:db00:11b:e0c0::1", "2401:db00:11b:e0c0::", "5000:3:1::"),
    ("eth1/62/5", "2401:db00:11b:e0c1::1", "2401:db00:11b:e0c1::", "5000:4:1::"),
]

# BC002.V001 port config data: (port_name, ixia_ip, gateway_ip, starting_prefix)
BC002_V001_PORT_CONFIG_DATA = [
    ("eth1/62/1", "2401:db00:11b:e0d0::1", "2401:db00:11b:e0d0::", "4000:1:1::"),
    ("eth1/62/5", "2401:db00:11b:e0d1::1", "2401:db00:11b:e0d1::", "4000:2:1::"),
]

# BC002.V004 port config data: (port_name, ixia_ip, gateway_ip, starting_prefix)
BC002_V004_PORT_CONFIG_DATA = [
    ("eth1/62/1", "2401:db00:11b:e0e0::1", "2401:db00:11b:e0e0::", "4000:3:1::"),
    ("eth1/62/5", "2401:db00:11b:e0e1::1", "2401:db00:11b:e0e1::", "4000:4:1::"),
]

# IXIA ports
CPR001_PORTS = [port for port, _, _, _ in CPR001_PORT_CONFIG_DATA]
BC001_V001_PORTS = [port for port, _, _, _ in BC001_V001_PORT_CONFIG_DATA]
BC002_V001_PORTS = [port for port, _, _, _ in BC002_V001_PORT_CONFIG_DATA]
BC001_V004_PORTS = [port for port, _, _, _ in BC001_V004_PORT_CONFIG_DATA]
BC002_V004_PORTS = [port for port, _, _, _ in BC002_V004_PORT_CONFIG_DATA]

BC_DEVICE_NAMES = [
    "bc001.v001.p001.s001.qzq1",
    "bc002.v001.p001.s001.qzq1",
    "bc001.v004.p001.s001.qzq1",
    "bc002.v004.p001.s001.qzq1",
]


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


# TODO: Fill in real IXIA chassis IP and port mappings
CPR001_DIRECT_IXIA_CONNECTIONS = get_direct_ixia_connections(
    "2401:db00:2076:30fe::3001",
    ["1/1", "1/2", "1/3", "1/4"],
    ["Ethernet4/32/1", "Ethernet4/32/5", "Ethernet4/36/1", "Ethernet4/36/5"],
)

BC001_V001_DIRECT_IXIA_CONNECTIONS = get_direct_ixia_connections(
    "2401:db00:2076:30fe::3001",
    ["1/5", "1/6"],
    ["eth1/62/1", "eth1/62/5"],
)

BC002_V001_DIRECT_IXIA_CONNECTIONS = get_direct_ixia_connections(
    "2401:db00:2076:30fe::3001",
    ["1/9", "1/10"],
    ["eth1/62/1", "eth1/62/5"],
)

BC001_V004_DIRECT_IXIA_CONNECTIONS = get_direct_ixia_connections(
    "2401:db00:2076:30fe::3001",
    ["1/7", "1/8"],
    ["eth1/62/1", "eth1/62/5"],
)

BC002_V004_DIRECT_IXIA_CONNECTIONS = get_direct_ixia_connections(
    "2401:db00:2076:30fe::3001",
    ["1/11", "1/12"],
    ["eth1/62/1", "eth1/62/5"],
)


CPR_TEST_ENDPOINTS = [
    Endpoint(
        name="cpr001.qzp1",
        dut=True,
        ixia_ports=CPR001_PORTS,
        direct_ixia_connections=CPR001_DIRECT_IXIA_CONNECTIONS,
    ),
    Endpoint(
        name="bc001.v001.p001.s001.qzq1",
        dut=False,
        ixia_ports=BC001_V001_PORTS,
        direct_ixia_connections=BC001_V001_DIRECT_IXIA_CONNECTIONS,
    ),
    Endpoint(
        name="bc002.v001.p001.s001.qzq1",
        dut=False,
        ixia_ports=BC002_V001_PORTS,
        direct_ixia_connections=BC002_V001_DIRECT_IXIA_CONNECTIONS,
    ),
    Endpoint(
        name="bc001.v004.p001.s001.qzq1",
        dut=False,
        ixia_ports=BC001_V004_PORTS,
        direct_ixia_connections=BC001_V004_DIRECT_IXIA_CONNECTIONS,
    ),
    Endpoint(
        name="bc002.v004.p001.s001.qzq1",
        dut=False,
        ixia_ports=BC002_V004_PORTS,
        direct_ixia_connections=BC002_V004_DIRECT_IXIA_CONNECTIONS,
    ),
]

BC_TEST_ENDPOINTS = [
    Endpoint(
        name="cpr001.qzp1",
        dut=False,
        ixia_ports=CPR001_PORTS,
        direct_ixia_connections=CPR001_DIRECT_IXIA_CONNECTIONS,
    ),
    Endpoint(
        name="bc001.v001.p001.s001.qzq1",
        dut=True,
        ixia_ports=BC001_V001_PORTS,
        direct_ixia_connections=BC001_V001_DIRECT_IXIA_CONNECTIONS,
    ),
    Endpoint(
        name="bc002.v001.p001.s001.qzq1",
        dut=True,
        ixia_ports=BC002_V001_PORTS,
        direct_ixia_connections=BC002_V001_DIRECT_IXIA_CONNECTIONS,
    ),
    Endpoint(
        name="bc001.v004.p001.s001.qzq1",
        dut=True,
        ixia_ports=BC001_V004_PORTS,
        direct_ixia_connections=BC001_V004_DIRECT_IXIA_CONNECTIONS,
    ),
    Endpoint(
        name="bc002.v004.p001.s001.qzq1",
        dut=True,
        ixia_ports=BC002_V004_PORTS,
        direct_ixia_connections=BC002_V004_DIRECT_IXIA_CONNECTIONS,
    ),
]

# Traffic endpoints: 1 CPR port → 2 BC ports per BC device
CPR001_TRAFFIC_ENDPOINT_PORT1 = [
    TrafficEndpoint(
        name="cpr001.qzp1:Ethernet4/32/1",
        network_group_index=0,
        device_group_index=0,
    ),
]

CPR001_TRAFFIC_ENDPOINT_PORT2 = [
    TrafficEndpoint(
        name="cpr001.qzp1:Ethernet4/32/5",
        network_group_index=0,
        device_group_index=0,
    ),
]

CPR001_TRAFFIC_ENDPOINT_PORT3 = [
    TrafficEndpoint(
        name="cpr001.qzp1:Ethernet4/36/1",
        network_group_index=0,
        device_group_index=0,
    ),
]

CPR001_TRAFFIC_ENDPOINT_PORT4 = [
    TrafficEndpoint(
        name="cpr001.qzp1:Ethernet4/36/5",
        network_group_index=0,
        device_group_index=0,
    ),
]

BC001_V001_TRAFFIC_ENDPOINTS = [
    TrafficEndpoint(
        name=f"bc001.v001.p001.s001.qzq1:{port}",
        network_group_index=0,
        device_group_index=0,
    )
    for port in BC001_V001_PORTS
]

BC001_V004_TRAFFIC_ENDPOINTS = [
    TrafficEndpoint(
        name=f"bc001.v004.p001.s001.qzq1:{port}",
        network_group_index=0,
        device_group_index=0,
    )
    for port in BC001_V004_PORTS
]

BC002_V001_TRAFFIC_ENDPOINTS = [
    TrafficEndpoint(
        name=f"bc002.v001.p001.s001.qzq1:{port}",
        network_group_index=0,
        device_group_index=0,
    )
    for port in BC002_V001_PORTS
]

BC002_V004_TRAFFIC_ENDPOINTS = [
    TrafficEndpoint(
        name=f"bc002.v004.p001.s001.qzq1:{port}",
        network_group_index=0,
        device_group_index=0,
    )
    for port in BC002_V004_PORTS
]

LINECARD_AGENTS = ["SandFapNi-Linecard3"]
FABRIC_AGENTS = [
    "SandFabric-Fabric1",
    "SandFabric-Fabric2",
]

LINECARD_MODULES = ["Linecard3"]
FABRIC_MODULES = [
    "Fabric1",
    "Fabric2",
]

TRAFFIC_ITEM_NAMES = [
    "TCP_CPR001_TO_BC001_V001",
    "TCP_CPR001_TO_BC001_V004",
    "TCP_CPR001_TO_BC002_V001",
    "TCP_CPR001_TO_BC002_V004",
]

CPR_BC_TRAFFIC_ITEM_CONFIGS = [
    BasicTrafficItemConfig(
        name="TCP_CPR001_TO_BC001_V001",
        bidirectional=False,
        line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
        line_rate=48,
        src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
        src_endpoints=BC001_V001_TRAFFIC_ENDPOINTS,
        dest_endpoints=CPR001_TRAFFIC_ENDPOINT_PORT1,
        traffic_type=ixia_types.TrafficType.IPV6,
        tracking_types=[
            ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM,
            ixia_types.TrafficStatsTrackingType.FLOW_GROUP,
        ],
        frame_size_settings=ixia_types.FrameSize(
            type=ixia_types.FrameSizeType.FIXED,
            fixed_size=1500,
        ),
    ),
    BasicTrafficItemConfig(
        name="TCP_CPR001_TO_BC001_V004",
        bidirectional=False,
        line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
        line_rate=48,
        src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
        src_endpoints=BC001_V004_TRAFFIC_ENDPOINTS,
        dest_endpoints=CPR001_TRAFFIC_ENDPOINT_PORT2,
        traffic_type=ixia_types.TrafficType.IPV6,
        tracking_types=[
            ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM,
            ixia_types.TrafficStatsTrackingType.FLOW_GROUP,
        ],
        frame_size_settings=ixia_types.FrameSize(
            type=ixia_types.FrameSizeType.FIXED,
            fixed_size=1500,
        ),
    ),
    BasicTrafficItemConfig(
        name="TCP_CPR001_TO_BC002_V001",
        bidirectional=False,
        line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
        line_rate=48,
        src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
        src_endpoints=BC002_V001_TRAFFIC_ENDPOINTS,
        dest_endpoints=CPR001_TRAFFIC_ENDPOINT_PORT3,
        traffic_type=ixia_types.TrafficType.IPV6,
        tracking_types=[
            ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM,
            ixia_types.TrafficStatsTrackingType.FLOW_GROUP,
        ],
        frame_size_settings=ixia_types.FrameSize(
            type=ixia_types.FrameSizeType.FIXED,
            fixed_size=1500,
        ),
    ),
    BasicTrafficItemConfig(
        name="TCP_CPR001_TO_BC002_V004",
        bidirectional=False,
        line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
        line_rate=48,
        src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
        src_endpoints=BC002_V004_TRAFFIC_ENDPOINTS,
        dest_endpoints=CPR001_TRAFFIC_ENDPOINT_PORT4,
        traffic_type=ixia_types.TrafficType.IPV6,
        tracking_types=[
            ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM,
            ixia_types.TrafficStatsTrackingType.FLOW_GROUP,
        ],
        frame_size_settings=ixia_types.FrameSize(
            type=ixia_types.FrameSizeType.FIXED,
            fixed_size=1500,
        ),
    ),
]

# TODO: Fill in real ASN values
CPR001_BASIC_PORT_CONFIGS = [
    create_basic_port_config(
        endpoint=f"cpr001.qzp1:{port}",
        starting_ip=ixia_ip,
        gateway_ip=gateway_ip,
        local_as=65062,
        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
        starting_prefixes=starting_prefix,
        bgp_communities=["65446:201", "65446:30", "65441:129", "65441:130"],
    )
    for port, ixia_ip, gateway_ip, starting_prefix in CPR001_PORT_CONFIG_DATA
]

BC001_V001_BASIC_PORT_CONFIGS = [
    create_basic_port_config(
        endpoint=f"bc001.v001.p001.s001.qzq1:{port}",
        starting_ip=ixia_ip,
        gateway_ip=gateway_ip,
        local_as=65063,
        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
        starting_prefixes=starting_prefix,
        bgp_communities=["65446:201", "65446:30", "65441:65", "65441:66"],
    )
    for port, ixia_ip, gateway_ip, starting_prefix in BC001_V001_PORT_CONFIG_DATA
]

BC001_V004_BASIC_PORT_CONFIGS = [
    create_basic_port_config(
        endpoint=f"bc001.v004.p001.s001.qzq1:{port}",
        starting_ip=ixia_ip,
        gateway_ip=gateway_ip,
        local_as=65063,
        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
        starting_prefixes=starting_prefix,
        bgp_communities=["65446:201", "65446:30", "65441:65", "65441:66"],
    )
    for port, ixia_ip, gateway_ip, starting_prefix in BC001_V004_PORT_CONFIG_DATA
]

BC002_V001_BASIC_PORT_CONFIGS = [
    create_basic_port_config(
        endpoint=f"bc002.v001.p001.s001.qzq1:{port}",
        starting_ip=ixia_ip,
        gateway_ip=gateway_ip,
        local_as=65063,
        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
        starting_prefixes=starting_prefix,
        bgp_communities=["65446:201", "65446:30", "65441:65", "65441:66"],
    )
    for port, ixia_ip, gateway_ip, starting_prefix in BC002_V001_PORT_CONFIG_DATA
]

BC002_V004_BASIC_PORT_CONFIGS = [
    create_basic_port_config(
        endpoint=f"bc002.v004.p001.s001.qzq1:{port}",
        starting_ip=ixia_ip,
        gateway_ip=gateway_ip,
        local_as=65063,
        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
        starting_prefixes=starting_prefix,
        bgp_communities=["65446:201", "65446:30", "65441:65", "65441:66"],
    )
    for port, ixia_ip, gateway_ip, starting_prefix in BC002_V004_PORT_CONFIG_DATA
]

CPR_BC_BASIC_PORT_CONFIGS = (
    CPR001_BASIC_PORT_CONFIGS
    + BC001_V001_BASIC_PORT_CONFIGS
    + BC001_V004_BASIC_PORT_CONFIGS
    + BC002_V001_BASIC_PORT_CONFIGS
    + BC002_V004_BASIC_PORT_CONFIGS
)


def create_bc_ixia_peer_group_patcher(device_name):
    return create_coop_register_patcher_task(
        hostname=device_name,
        config_name="bgpcpp",
        patcher_name=f"add_peer_group_patcher_{BC_IXIA_PEER_GROUP}",
        task_name="coop_register_patcher",
        patcher_args={
            "name": BC_IXIA_PEER_GROUP,
            "description": "BGP peering from BC to IXIA, IPV6 sessions",
            "next_hop_self": "True",
            "disable_ipv4_afi": "True",
            "disable_ipv6_afi": "False",
            "is_confed_peer": "False",
            "ingress_policy_name": "PROPAGATE_EVERYTHING",
            "egress_policy_name": "PROPAGATE_EVERYTHING",
            "bgp_peer_timers_hold_time_seconds": "30",
            "bgp_peer_timers_keep_alive_seconds": "10",
            "bgp_peer_timers_out_delay_seconds": "7",
            "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
            "peer_tag": "FX",
            "max_routes": "90000",
            "warning_only": "True",
            "warning_limit": "0",
            "link_bandwidth_bps": "auto",
            "v4_over_v6_nexthop": "False",
            "is_passive": "False",
            "receive_link_bandwidth": "1",
        },
        py_func_name="add_peer_group_patcher",
    )


def create_speed_flip_patcher_bc(device_name):
    return create_coop_register_patcher_task(
        hostname=device_name,
        config_name="agent",
        patcher_name="configure_port_speed_patcher_ixia_400g",
        task_name="coop_register_patcher",
        patcher_args={
            "port_name": "eth1/62/1,eth1/62/5",
            "speed": "FOURHUNDREDG",
            "profile_id": "PROFILE_400G_4_PAM4_RS544X2N_OPTICAL",
        },
        py_func_name="configure_port_speed_patcher",
    )


def create_bc_ixia_prefix_match_patcher(device_name):
    return create_coop_register_patcher_task(
        hostname=device_name,
        config_name="bgpcpp",
        patcher_name=f"add_bgp_policy_match_prefix_to_propagate_routes_{BC_IXIA_PEER_GROUP}",
        task_name="coop_register_patcher",
        patcher_args={
            "matching_prefix": "6000::/16",
            "in_stmt_name": "PEERGROUP_BC_CPR_V6",
            "out_stmt_name": "RANDOM",
        },
        py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
    )


def create_bc_propagate_all_patcher(device_name):
    return create_coop_register_patcher_task(
        hostname=device_name,
        config_name="bgpcpp",
        patcher_name="a_add_bgp_policy_statement_PROPAGATE_EVERYTHING",
        task_name="coop_register_patcher",
        patcher_args={
            "name": "PROPAGATE_EVERYTHING",
            "description": "Policy for BC IXIA",
            "result": "ACCEPT",
        },
        py_func_name="add_bgp_policy_statement",
    )


def create_cpr_test_config(
    test_config_name: str = "CPR_TEST_CONFIG",
    longevity_duration: int = 3600 * 12,
) -> TestConfig:
    _hostnames = [
        "bc001.v001.p001.s001.qzq1",
        "bc001.v004.p001.s001.qzq1",
        "bc002.v001.p001.s001.qzq1",
        "bc002.v004.p001.s001.qzq1",
    ]
    _tc_prechecks = [
        create_ixia_packet_loss_check(
            thresholds=[
                hc_types.PacketLossThreshold(
                    str_value="0",
                    metric=hc_types.PacketLossMetric.PERCENTAGE,
                ),
            ],
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
        ),
        create_port_state_check(),
        create_lldp_check(),
    ]
    _tc_snapshot_checks = [
        create_core_dumps_snapshot_check(),
    ]

    _disruptive_playbooks = list(
        create_cpr_disruptive_playbooks(
            device_regexes=["cpr001.qzp1"],
            traffic_items_to_start=TRAFFIC_ITEM_NAMES,
            fabric_modules=FABRIC_MODULES,
            linecard_modules=LINECARD_MODULES,
            fabric_agents=FABRIC_AGENTS,
            linecard_agents=LINECARD_AGENTS,
            is_sequential=False,
            iteration=10,
        ),
    )
    _disruptive_playbooks = [
        _pb(
            prechecks=_tc_prechecks + list(_pb.prechecks or []),
            postchecks=_tc_postchecks + list(_pb.postchecks or []),
            snapshot_checks=_tc_snapshot_checks + list(_pb.snapshot_checks or []),
        )
        for _pb in _disruptive_playbooks
    ]

    # TODO: Fill in real BGP peer config values (IPs, ASNs, peer groups)
    # Note: starting_ip/gateway_starting_ip are reversed from IXIA BasicPortConfig
    # (device's own IP as starting_ip, IXIA peer IP as gateway_starting_ip)
    _setup_tasks = [
        create_backup_running_config_task(
            hostname="cpr001.qzp1",
            backup_file="cpr001_backup_config",
        ),
        create_coop_unregister_patchers_task("bc001.v001.p001.s001.qzq1"),
        create_coop_unregister_patchers_task("bc001.v004.p001.s001.qzq1"),
        create_coop_unregister_patchers_task("bc002.v001.p001.s001.qzq1"),
        create_coop_unregister_patchers_task("bc002.v004.p001.s001.qzq1"),
        create_speed_flip_patcher_bc("bc001.v001.p001.s001.qzq1"),
        create_speed_flip_patcher_bc("bc001.v004.p001.s001.qzq1"),
        create_speed_flip_patcher_bc("bc002.v001.p001.s001.qzq1"),
        create_speed_flip_patcher_bc("bc002.v004.p001.s001.qzq1"),
        create_eos_bgp_peer_group_task(
            hostname="cpr001.qzp1",
            peer_group_name=CPR_IXIA_PEER_GROUP,
            local_as=65350,
            ipv4_unicast=False,
            ipv6_unicast=True,
            route_map_in="PROPAGATE_EVERYTHING",
            route_map_out="PROPAGATE_EVERYTHING",
        ),
        # create_eos_bgp_prefix_list_task(
        #     hostname="cpr001.qzp1",
        #     prefix_list_name="ALLOW_CPR_BC_IXIA_V6_IN",
        #     peer_group_name="PEERGROUP_CPR_BC_V6",
        #     prefix="5000::/16",
        #     direction="in",
        #     seq=10,
        # ),
        # create_eos_bgp_prefix_list_task(
        #     hostname="cpr001.qzp1",
        #     prefix_list_name="ALLOW_CPR_BC_IXIA_V6_IN",
        #     peer_group_name="PEERGROUP_CPR_BC_V6",
        #     prefix="4000::/16",
        #     direction="in",
        #     seq=20,
        # ),
        create_bc_propagate_all_patcher("bc001.v001.p001.s001.qzq1"),
        create_bc_propagate_all_patcher("bc001.v004.p001.s001.qzq1"),
        create_bc_propagate_all_patcher("bc002.v001.p001.s001.qzq1"),
        create_bc_propagate_all_patcher("bc002.v004.p001.s001.qzq1"),
        create_bc_ixia_peer_group_patcher("bc001.v001.p001.s001.qzq1"),
        create_bc_ixia_peer_group_patcher("bc002.v001.p001.s001.qzq1"),
        create_bc_ixia_peer_group_patcher("bc001.v004.p001.s001.qzq1"),
        create_bc_ixia_peer_group_patcher("bc002.v004.p001.s001.qzq1"),
        # create_bc_ixia_prefix_match_patcher("bc001.v001.p001.s001.qzq1"),
        # create_bc_ixia_prefix_match_patcher("bc002.v001.p001.s001.qzq1"),
        # create_bc_ixia_prefix_match_patcher("bc001.v004.p001.s001.qzq1"),
        # create_bc_ixia_prefix_match_patcher("bc002.v004.p001.s001.qzq1"),
        create_configure_eos_parallel_bgp_peers_task(
            hostname="cpr001.qzp1",
            config_json=json.dumps(
                {
                    "Ethernet4/32/1": [
                        {
                            "starting_ip": "2401:db00:11b:e0a0::",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:e0a0::1",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 1,
                            "remote_as_4_byte": 65062,
                            "prefix_length": 127,
                            "peer_group_name": CPR_IXIA_PEER_GROUP,
                            "ipv6_unicast": True,
                            "ipv4_unicast": False,
                        }
                    ],
                    "Ethernet4/32/5": [
                        {
                            "starting_ip": "2401:db00:11b:e0a1::",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:e0a1::1",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 1,
                            "remote_as_4_byte": 65062,
                            "prefix_length": 127,
                            "peer_group_name": CPR_IXIA_PEER_GROUP,
                            "ipv6_unicast": True,
                            "ipv4_unicast": False,
                        }
                    ],
                    "Ethernet4/36/1": [
                        {
                            "starting_ip": "2401:db00:11b:e0a2::",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:e0a2::1",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 1,
                            "remote_as_4_byte": 65062,
                            "prefix_length": 127,
                            "peer_group_name": CPR_IXIA_PEER_GROUP,
                            "ipv6_unicast": True,
                            "ipv4_unicast": False,
                        }
                    ],
                    "Ethernet4/36/5": [
                        {
                            "starting_ip": "2401:db00:11b:e0a3::",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:e0a3::1",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 1,
                            "remote_as_4_byte": 65062,
                            "prefix_length": 127,
                            "peer_group_name": CPR_IXIA_PEER_GROUP,
                            "ipv6_unicast": True,
                            "ipv4_unicast": False,
                        }
                    ],
                    "Ethernet3/1/1": [
                        {
                            "starting_ip": "2401:db00:11b:f0a0::",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:f0a0::1",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 40,
                            "remote_as_4_byte": 4210263900,
                            "prefix_length": 127,
                            "peer_group_name": "PEERGROUP_CPR_BC_LC03_V6",
                            "ipv6_unicast": True,
                            "ipv4_unicast": False,
                        }
                    ],
                    "Ethernet3/2/1": [
                        {
                            "starting_ip": "2401:db00:11b:f0a1::",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:f0a1::1",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 40,
                            "remote_as_4_byte": 4210263900,
                            "prefix_length": 127,
                            "peer_group_name": "PEERGROUP_CPR_BC_LC03_V6",
                            "ipv6_unicast": True,
                            "ipv4_unicast": False,
                        }
                    ],
                    "Ethernet3/7/1": [
                        {
                            "starting_ip": "2401:db00:11b:f0a2::",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:f0a2::1",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 40,
                            "remote_as_4_byte": 4210263900,
                            "prefix_length": 127,
                            "peer_group_name": "PEERGROUP_CPR_BC_LC03_V6",
                            "ipv6_unicast": True,
                            "ipv4_unicast": False,
                        }
                    ],
                    "Ethernet3/8/1": [
                        {
                            "starting_ip": "2401:db00:11b:f0a3::",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:f0a3::1",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 40,
                            "remote_as_4_byte": 4210263900,
                            "prefix_length": 127,
                            "peer_group_name": "PEERGROUP_CPR_BC_LC03_V6",
                            "ipv6_unicast": True,
                            "ipv4_unicast": False,
                        }
                    ],
                }
            ),
        ),
        create_configure_parallel_bgp_peers_task(
            hostname="bc001.v001.p001.s001.qzq1",
            configure_vlans_patcher_name="configure_vlans_patcher",
            add_bgp_peers_patcher_name="add_bgp_peers_patcher",
            config_json=json.dumps(
                {
                    "eth1/62/1": [
                        {
                            "starting_ip": "2401:db00:11b:e0b0::",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:e0b0::1",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 1,
                            "remote_as_4_byte": 65063,
                            "prefix_length": 127,
                            "peer_group_name": BC_IXIA_PEER_GROUP,
                        }
                    ],
                    "eth1/62/5": [
                        {
                            "starting_ip": "2401:db00:11b:e0b1::",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:e0b1::1",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 1,
                            "remote_as_4_byte": 65063,
                            "prefix_length": 127,
                            "peer_group_name": BC_IXIA_PEER_GROUP,
                        }
                    ],
                    "eth1/32/1": [
                        {
                            "starting_ip": "2401:db00:11b:f0a0::1",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:f0a0::",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 40,
                            "remote_as_4_byte": 65350,
                            "prefix_length": 127,
                            "peer_group_name": "PEERGROUP_BC_CPR_V6",
                        }
                    ],
                }
            ),
        ),
        create_configure_parallel_bgp_peers_task(
            hostname="bc001.v004.p001.s001.qzq1",
            configure_vlans_patcher_name="configure_vlans_patcher",
            add_bgp_peers_patcher_name="add_bgp_peers_patcher",
            config_json=json.dumps(
                {
                    "eth1/62/1": [
                        {
                            "starting_ip": "2401:db00:11b:e0c0::",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:e0c0::1",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 1,
                            "remote_as_4_byte": 65063,
                            "prefix_length": 127,
                            "peer_group_name": BC_IXIA_PEER_GROUP,
                        }
                    ],
                    "eth1/62/5": [
                        {
                            "starting_ip": "2401:db00:11b:e0c1::",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:e0c1::1",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 1,
                            "remote_as_4_byte": 65063,
                            "prefix_length": 127,
                            "peer_group_name": BC_IXIA_PEER_GROUP,
                        }
                    ],
                    "eth1/32/1": [
                        {
                            "starting_ip": "2401:db00:11b:f0a2::1",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:f0a2::",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 40,
                            "remote_as_4_byte": 65350,
                            "prefix_length": 127,
                            "peer_group_name": "PEERGROUP_BC_CPR_V6",
                        }
                    ],
                }
            ),
        ),
        create_configure_parallel_bgp_peers_task(
            hostname="bc002.v001.p001.s001.qzq1",
            configure_vlans_patcher_name="configure_vlans_patcher",
            add_bgp_peers_patcher_name="add_bgp_peers_patcher",
            config_json=json.dumps(
                {
                    "eth1/62/1": [
                        {
                            "starting_ip": "2401:db00:11b:e0d0::",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:e0d0::1",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 1,
                            "remote_as_4_byte": 65063,
                            "prefix_length": 127,
                            "peer_group_name": BC_IXIA_PEER_GROUP,
                        }
                    ],
                    "eth1/62/5": [
                        {
                            "starting_ip": "2401:db00:11b:e0d1::",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:e0d1::1",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 1,
                            "remote_as_4_byte": 65063,
                            "prefix_length": 127,
                            "peer_group_name": BC_IXIA_PEER_GROUP,
                        }
                    ],
                    "eth1/33/1": [
                        {
                            "starting_ip": "2401:db00:11b:f0a1::1",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:f0a1::",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 40,
                            "remote_as_4_byte": 65350,
                            "prefix_length": 127,
                            "peer_group_name": "PEERGROUP_BC_CPR_V6",
                        }
                    ],
                }
            ),
        ),
        create_configure_parallel_bgp_peers_task(
            hostname="bc002.v004.p001.s001.qzq1",
            configure_vlans_patcher_name="configure_vlans_patcher",
            add_bgp_peers_patcher_name="add_bgp_peers_patcher",
            config_json=json.dumps(
                {
                    "eth1/62/1": [
                        {
                            "starting_ip": "2401:db00:11b:e0e0::",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:e0e0::1",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 1,
                            "remote_as_4_byte": 65063,
                            "prefix_length": 127,
                            "peer_group_name": BC_IXIA_PEER_GROUP,
                        }
                    ],
                    "eth1/62/5": [
                        {
                            "starting_ip": "2401:db00:11b:e0e1::",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:e0e1::1",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 1,
                            "remote_as_4_byte": 65063,
                            "prefix_length": 127,
                            "peer_group_name": BC_IXIA_PEER_GROUP,
                        }
                    ],
                    "eth1/33/1": [
                        {
                            "starting_ip": "2401:db00:11b:f0a3::1",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:f0a3::",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 40,
                            "remote_as_4_byte": 65350,
                            "prefix_length": 127,
                            "peer_group_name": "PEERGROUP_BC_CPR_V6",
                        }
                    ],
                }
            ),
        ),
        create_coop_apply_patchers_task(
            hostnames=_hostnames,
        ),
        create_wait_for_agent_convergence_task(_hostnames),
        create_wait_for_bgp_convergence_task(
            hostnames=_hostnames,
        ),
    ]

    return TestConfig(
        name=test_config_name,
        ixia_protocol_verification_timeout=300,
        endpoints=CPR_TEST_ENDPOINTS,
        setup_tasks=_setup_tasks,
        basic_port_configs=CPR_BC_BASIC_PORT_CONFIGS,
        basic_traffic_item_configs=CPR_BC_TRAFFIC_ITEM_CONFIGS,
        playbooks=[
            create_longevity_playbook(
                playbook_name="test_cpr_bc_longevity",
                traffic_items_to_start=TRAFFIC_ITEM_NAMES,
                longevity_duration=longevity_duration,
                prechecks=_tc_prechecks,
                postchecks=_tc_postchecks,
                snapshot_checks=_tc_snapshot_checks,
            ),
            *_disruptive_playbooks,
        ],
    )


def create_bc_test_config(
    test_config_name: str = "BC_TEST_CONFIG",
    longevity_duration: int = 3600 * 12,
) -> TestConfig:
    _hostnames = [
        "bc001.v001.p001.s001.qzq1",
        "bc001.v004.p001.s001.qzq1",
        "bc002.v001.p001.s001.qzq1",
        "bc002.v004.p001.s001.qzq1",
    ]
    _tc_prechecks = [
        create_ixia_packet_loss_check(
            thresholds=[
                hc_types.PacketLossThreshold(
                    str_value="0",
                    metric=hc_types.PacketLossMetric.PERCENTAGE,
                ),
            ],
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
        ),
        create_port_state_check(),
        create_lldp_check(),
    ]
    _tc_snapshot_checks = [
        create_core_dumps_snapshot_check(),
    ]

    _disruptive_playbooks = list(
        create_bc_disruptive_playbooks(
            device_regexes=[
                "bc001.v001.p001.s001.qzq1",
                "bc002.v001.p001.s001.qzq1",
                "bc001.v004.p001.s001.qzq1",
                "bc002.v004.p001.s001.qzq1",
            ],
            traffic_items_to_start=TRAFFIC_ITEM_NAMES,
            is_sequential=False,
            iteration=10,
        ),
    )
    _disruptive_playbooks = [
        _pb(
            prechecks=_tc_prechecks + list(_pb.prechecks or []),
            postchecks=_tc_postchecks + list(_pb.postchecks or []),
            snapshot_checks=_tc_snapshot_checks + list(_pb.snapshot_checks or []),
        )
        for _pb in _disruptive_playbooks
    ]

    # TODO: Fill in real BGP peer config values (IPs, ASNs, peer groups)
    # Note: starting_ip/gateway_starting_ip are reversed from IXIA BasicPortConfig
    # (device's own IP as starting_ip, IXIA peer IP as gateway_starting_ip)
    _setup_tasks = [
        create_backup_running_config_task(
            hostname="cpr001.qzp1",
            backup_file="cpr001_backup_config",
        ),
        create_coop_unregister_patchers_task("bc001.v001.p001.s001.qzq1"),
        create_coop_unregister_patchers_task("bc001.v004.p001.s001.qzq1"),
        create_coop_unregister_patchers_task("bc002.v001.p001.s001.qzq1"),
        create_coop_unregister_patchers_task("bc002.v004.p001.s001.qzq1"),
        create_speed_flip_patcher_bc("bc001.v001.p001.s001.qzq1"),
        create_speed_flip_patcher_bc("bc001.v004.p001.s001.qzq1"),
        create_speed_flip_patcher_bc("bc002.v001.p001.s001.qzq1"),
        create_speed_flip_patcher_bc("bc002.v004.p001.s001.qzq1"),
        create_eos_bgp_peer_group_task(
            hostname="cpr001.qzp1",
            peer_group_name=CPR_IXIA_PEER_GROUP,
            local_as=65350,
            ipv4_unicast=False,
            ipv6_unicast=True,
            route_map_in="PROPAGATE_EVERYTHING",
            route_map_out="PROPAGATE_EVERYTHING",
        ),
        # create_eos_bgp_prefix_list_task(
        #     hostname="cpr001.qzp1",
        #     prefix_list_name="ALLOW_CPR_BC_IXIA_V6_IN",
        #     peer_group_name="PEERGROUP_CPR_BC_V6",
        #     prefix="5000::/16",
        #     direction="in",
        #     seq=10,
        # ),
        # create_eos_bgp_prefix_list_task(
        #     hostname="cpr001.qzp1",
        #     prefix_list_name="ALLOW_CPR_BC_IXIA_V6_IN",
        #     peer_group_name="PEERGROUP_CPR_BC_V6",
        #     prefix="4000::/16",
        #     direction="in",
        #     seq=20,
        # ),
        create_bc_propagate_all_patcher("bc001.v001.p001.s001.qzq1"),
        create_bc_propagate_all_patcher("bc001.v004.p001.s001.qzq1"),
        create_bc_propagate_all_patcher("bc002.v001.p001.s001.qzq1"),
        create_bc_propagate_all_patcher("bc002.v004.p001.s001.qzq1"),
        create_bc_ixia_peer_group_patcher("bc001.v001.p001.s001.qzq1"),
        create_bc_ixia_peer_group_patcher("bc002.v001.p001.s001.qzq1"),
        create_bc_ixia_peer_group_patcher("bc001.v004.p001.s001.qzq1"),
        create_bc_ixia_peer_group_patcher("bc002.v004.p001.s001.qzq1"),
        # create_bc_ixia_prefix_match_patcher("bc001.v001.p001.s001.qzq1"),
        # create_bc_ixia_prefix_match_patcher("bc002.v001.p001.s001.qzq1"),
        # create_bc_ixia_prefix_match_patcher("bc001.v004.p001.s001.qzq1"),
        # create_bc_ixia_prefix_match_patcher("bc002.v004.p001.s001.qzq1"),
        create_configure_eos_parallel_bgp_peers_task(
            hostname="cpr001.qzp1",
            config_json=json.dumps(
                {
                    "Ethernet4/32/1": [
                        {
                            "starting_ip": "2401:db00:11b:e0a0::",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:e0a0::1",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 1,
                            "remote_as_4_byte": 65062,
                            "prefix_length": 127,
                            "peer_group_name": CPR_IXIA_PEER_GROUP,
                            "ipv6_unicast": True,
                            "ipv4_unicast": False,
                        }
                    ],
                    "Ethernet4/32/5": [
                        {
                            "starting_ip": "2401:db00:11b:e0a1::",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:e0a1::1",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 1,
                            "remote_as_4_byte": 65062,
                            "prefix_length": 127,
                            "peer_group_name": CPR_IXIA_PEER_GROUP,
                            "ipv6_unicast": True,
                            "ipv4_unicast": False,
                        }
                    ],
                    "Ethernet4/36/1": [
                        {
                            "starting_ip": "2401:db00:11b:e0a2::",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:e0a2::1",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 1,
                            "remote_as_4_byte": 65062,
                            "prefix_length": 127,
                            "peer_group_name": CPR_IXIA_PEER_GROUP,
                            "ipv6_unicast": True,
                            "ipv4_unicast": False,
                        }
                    ],
                    "Ethernet4/36/5": [
                        {
                            "starting_ip": "2401:db00:11b:e0a3::",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:e0a3::1",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 1,
                            "remote_as_4_byte": 65062,
                            "prefix_length": 127,
                            "peer_group_name": CPR_IXIA_PEER_GROUP,
                            "ipv6_unicast": True,
                            "ipv4_unicast": False,
                        }
                    ],
                    "Ethernet3/1/1": [
                        {
                            "starting_ip": "2401:db00:11b:f0a0::",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:f0a0::1",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 40,
                            "remote_as_4_byte": 4210263900,
                            "prefix_length": 127,
                            "peer_group_name": "PEERGROUP_CPR_BC_LC03_V6",
                            "ipv6_unicast": True,
                            "ipv4_unicast": False,
                        }
                    ],
                    "Ethernet3/2/1": [
                        {
                            "starting_ip": "2401:db00:11b:f0a1::",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:f0a1::1",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 40,
                            "remote_as_4_byte": 4210263900,
                            "prefix_length": 127,
                            "peer_group_name": "PEERGROUP_CPR_BC_LC03_V6",
                            "ipv6_unicast": True,
                            "ipv4_unicast": False,
                        }
                    ],
                    "Ethernet3/7/1": [
                        {
                            "starting_ip": "2401:db00:11b:f0a2::",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:f0a2::1",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 40,
                            "remote_as_4_byte": 4210263900,
                            "prefix_length": 127,
                            "peer_group_name": "PEERGROUP_CPR_BC_LC03_V6",
                            "ipv6_unicast": True,
                            "ipv4_unicast": False,
                        }
                    ],
                    "Ethernet3/8/1": [
                        {
                            "starting_ip": "2401:db00:11b:f0a3::",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:f0a3::1",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 40,
                            "remote_as_4_byte": 4210263900,
                            "prefix_length": 127,
                            "peer_group_name": "PEERGROUP_CPR_BC_LC03_V6",
                            "ipv6_unicast": True,
                            "ipv4_unicast": False,
                        }
                    ],
                }
            ),
        ),
        create_configure_parallel_bgp_peers_task(
            hostname="bc001.v001.p001.s001.qzq1",
            configure_vlans_patcher_name="configure_vlans_patcher",
            add_bgp_peers_patcher_name="add_bgp_peers_patcher",
            config_json=json.dumps(
                {
                    "eth1/62/1": [
                        {
                            "starting_ip": "2401:db00:11b:e0b0::",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:e0b0::1",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 1,
                            "remote_as_4_byte": 65063,
                            "prefix_length": 127,
                            "peer_group_name": BC_IXIA_PEER_GROUP,
                        }
                    ],
                    "eth1/62/5": [
                        {
                            "starting_ip": "2401:db00:11b:e0b1::",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:e0b1::1",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 1,
                            "remote_as_4_byte": 65063,
                            "prefix_length": 127,
                            "peer_group_name": BC_IXIA_PEER_GROUP,
                        }
                    ],
                    "eth1/32/1": [
                        {
                            "starting_ip": "2401:db00:11b:f0a0::1",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:f0a0::",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 40,
                            "remote_as_4_byte": 65350,
                            "prefix_length": 127,
                            "peer_group_name": "PEERGROUP_BC_CPR_V6",
                        }
                    ],
                }
            ),
        ),
        create_configure_parallel_bgp_peers_task(
            hostname="bc001.v004.p001.s001.qzq1",
            configure_vlans_patcher_name="configure_vlans_patcher",
            add_bgp_peers_patcher_name="add_bgp_peers_patcher",
            config_json=json.dumps(
                {
                    "eth1/62/1": [
                        {
                            "starting_ip": "2401:db00:11b:e0c0::",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:e0c0::1",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 1,
                            "remote_as_4_byte": 65063,
                            "prefix_length": 127,
                            "peer_group_name": BC_IXIA_PEER_GROUP,
                        }
                    ],
                    "eth1/62/5": [
                        {
                            "starting_ip": "2401:db00:11b:e0c1::",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:e0c1::1",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 1,
                            "remote_as_4_byte": 65063,
                            "prefix_length": 127,
                            "peer_group_name": BC_IXIA_PEER_GROUP,
                        }
                    ],
                    "eth1/32/1": [
                        {
                            "starting_ip": "2401:db00:11b:f0a2::1",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:f0a2::",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 40,
                            "remote_as_4_byte": 65350,
                            "prefix_length": 127,
                            "peer_group_name": "PEERGROUP_BC_CPR_V6",
                        }
                    ],
                }
            ),
        ),
        create_configure_parallel_bgp_peers_task(
            hostname="bc002.v001.p001.s001.qzq1",
            configure_vlans_patcher_name="configure_vlans_patcher",
            add_bgp_peers_patcher_name="add_bgp_peers_patcher",
            config_json=json.dumps(
                {
                    "eth1/62/1": [
                        {
                            "starting_ip": "2401:db00:11b:e0d0::",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:e0d0::1",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 1,
                            "remote_as_4_byte": 65063,
                            "prefix_length": 127,
                            "peer_group_name": BC_IXIA_PEER_GROUP,
                        }
                    ],
                    "eth1/62/5": [
                        {
                            "starting_ip": "2401:db00:11b:e0d1::",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:e0d1::1",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 1,
                            "remote_as_4_byte": 65063,
                            "prefix_length": 127,
                            "peer_group_name": BC_IXIA_PEER_GROUP,
                        }
                    ],
                    "eth1/33/1": [
                        {
                            "starting_ip": "2401:db00:11b:f0a1::1",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:f0a1::",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 40,
                            "remote_as_4_byte": 65350,
                            "prefix_length": 127,
                            "peer_group_name": "PEERGROUP_BC_CPR_V6",
                        }
                    ],
                }
            ),
        ),
        create_configure_parallel_bgp_peers_task(
            hostname="bc002.v004.p001.s001.qzq1",
            configure_vlans_patcher_name="configure_vlans_patcher",
            add_bgp_peers_patcher_name="add_bgp_peers_patcher",
            config_json=json.dumps(
                {
                    "eth1/62/1": [
                        {
                            "starting_ip": "2401:db00:11b:e0e0::",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:e0e0::1",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 1,
                            "remote_as_4_byte": 65063,
                            "prefix_length": 127,
                            "peer_group_name": BC_IXIA_PEER_GROUP,
                        }
                    ],
                    "eth1/62/5": [
                        {
                            "starting_ip": "2401:db00:11b:e0e1::",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:e0e1::1",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 1,
                            "remote_as_4_byte": 65063,
                            "prefix_length": 127,
                            "peer_group_name": BC_IXIA_PEER_GROUP,
                        }
                    ],
                    "eth1/33/1": [
                        {
                            "starting_ip": "2401:db00:11b:f0a3::1",
                            "increment_ip": "::2",
                            "gateway_starting_ip": "2401:db00:11b:f0a3::",
                            "gateway_increment_ip": "::2",
                            "num_sessions": 40,
                            "remote_as_4_byte": 65350,
                            "prefix_length": 127,
                            "peer_group_name": "PEERGROUP_BC_CPR_V6",
                        }
                    ],
                }
            ),
        ),
        create_coop_apply_patchers_task(
            hostnames=_hostnames,
        ),
        create_wait_for_agent_convergence_task(_hostnames),
        create_wait_for_bgp_convergence_task(
            hostnames=_hostnames,
        ),
    ]

    return TestConfig(
        name=test_config_name,
        ixia_protocol_verification_timeout=300,
        endpoints=BC_TEST_ENDPOINTS,
        setup_tasks=_setup_tasks,
        basic_port_configs=CPR_BC_BASIC_PORT_CONFIGS,
        basic_traffic_item_configs=CPR_BC_TRAFFIC_ITEM_CONFIGS,
        playbooks=_disruptive_playbooks,
    )


CPR_ZR_LOSS_BENCHMARK_TEST_CONFIGS = TestConfig(
    name="cpr_zr_loss_benchmark",
    ixia_protocol_verification_timeout=300,
    endpoints=[
        Endpoint(
            name="cpr001.qzp1",
            dut=False,
            ixia_ports=["Ethernet4/32/1"],
            direct_ixia_connections=[
                taac_types.DirectIxiaConnection(
                    interface="eth4/32/1",
                    ixia_chassis_ip="2401:db00:2076:30fe::3001",
                    ixia_port="1/1",
                ),
            ],
        ),
        Endpoint(
            name="bc001.v001.p001.s001.qzq1",
            dut=True,
            ixia_ports=["eth1/62/1"],
            direct_ixia_connections=[
                taac_types.DirectIxiaConnection(
                    interface="eth1/62/1",
                    ixia_chassis_ip="2401:db00:2076:30fe::3001",
                    ixia_port="1/5",
                ),
            ],
        ),
        Endpoint(
            name="bc002.v001.p001.s001.qzq1",
            dut=True,
            ixia_ports=["eth1/62/1"],
            direct_ixia_connections=[
                taac_types.DirectIxiaConnection(
                    interface="eth1/62/1",
                    ixia_chassis_ip="2401:db00:2076:30fe::3001",
                    ixia_port="1/9",
                ),
            ],
        ),
    ],
    setup_tasks=[],
    basic_port_configs=[
        BasicPortConfig(
            endpoint="cpr001.qzp1:Ethernet4/32/1",
            device_group_configs=[
                DeviceGroupConfig(
                    device_group_index=0,
                    multiplier=1,
                    v6_addresses_config=IpAddressesConfig(
                        starting_ip="2401:db00:11b:e0a0::1",
                        increment_ip="::2",
                        gateway_starting_ip="2401:db00:11b:e0a0::",
                        gateway_increment_ip="::2",
                        mask=127,
                    ),
                    v6_bgp_config=BgpConfig(
                        local_as_4_bytes=65062,
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
                                    starting_prefixes="6000:1:1::",
                                    prefix_step="0:0:0:1:0:0:0:0",
                                    bgp_communities=[
                                        "65446:201",
                                        "65446:30",
                                        "65441:129",
                                        "65441:130",
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
            endpoint="bc001.v001.p001.s001.qzq1:eth1/62/1",
            device_group_configs=[
                DeviceGroupConfig(
                    device_group_index=0,
                    multiplier=1,
                    v6_addresses_config=IpAddressesConfig(
                        starting_ip="2401:db00:11b:e0b0::1",
                        increment_ip="::2",
                        gateway_starting_ip="2401:db00:11b:e0b0::",
                        gateway_increment_ip="::2",
                        mask=127,
                    ),
                    v6_bgp_config=BgpConfig(
                        local_as_4_bytes=65063,
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
                                    starting_prefixes="5000:1:1::",
                                    prefix_step="0:0:0:1:0:0:0:0",
                                    bgp_communities=[
                                        "65446:201",
                                        "65446:30",
                                        "65441:65",
                                        "65441:66",
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
            endpoint="bc002.v001.p001.s001.qzq1:eth1/62/1",
            device_group_configs=[
                DeviceGroupConfig(
                    device_group_index=0,
                    multiplier=1,
                    v6_addresses_config=IpAddressesConfig(
                        starting_ip="2401:db00:11b:e0d0::1",
                        increment_ip="::2",
                        gateway_starting_ip="2401:db00:11b:e0d0::",
                        gateway_increment_ip="::2",
                        mask=127,
                    ),
                    v6_bgp_config=BgpConfig(
                        local_as_4_bytes=65063,
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
                                    starting_prefixes="5000:1:1::",
                                    prefix_step="0:0:0:1:0:0:0:0",
                                    bgp_communities=[
                                        "65446:201",
                                        "65446:30",
                                        "65441:65",
                                        "65441:66",
                                    ],
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                ),
                            ),
                        ],
                    ),
                ),
            ],
        ),
    ],
    basic_traffic_item_configs=[
        BasicTrafficItemConfig(
            name="TCP_BENCHMARK",
            bidirectional=False,
            line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
            line_rate=99,
            src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
            src_endpoints=[
                TrafficEndpoint(
                    name="cpr001.qzp1:eth4/32/1",
                    network_group_index=0,
                    device_group_index=0,
                )
            ],
            dest_endpoints=[
                TrafficEndpoint(
                    name="bc001.v001.p001.s001.qzq1:eth1/62/1",
                    network_group_index=0,
                    device_group_index=0,
                ),
                TrafficEndpoint(
                    name="bc002.v001.p001.s001.qzq1:eth1/62/1",
                    network_group_index=0,
                    device_group_index=0,
                ),
            ],
            traffic_type=ixia_types.TrafficType.IPV6,
            tracking_types=[
                ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM,
                ixia_types.TrafficStatsTrackingType.FLOW_GROUP,
            ],
            frame_size_settings=ixia_types.FrameSize(
                type=ixia_types.FrameSizeType.FIXED,
                fixed_size=1500,
            ),
            merge_destinations=True,
        ),
    ],
    playbooks=[
        create_longevity_playbook(
            playbook_name="test_cpr_zr_loss_benchmark",
            traffic_items_to_start=["TCP_BENCHMARK"],
            longevity_duration=3600,
        )
    ],
)


CPR_BC_TEST_CONFIGS = [create_cpr_test_config(), create_bc_test_config()]
