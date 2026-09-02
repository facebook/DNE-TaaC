# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import json

from ixia.ixia import types as ixia_thrift
from taac.health_checks.healthcheck_definitions import (
    create_ixia_packet_loss_check,
    create_unclean_exit_check,
)
from taac.packet_headers import (
    BGP_CP_V6_GLOBAL_DSCP48_TRAFFIC_PACKET_HEADERS,
    DHCP_V6_LL_DSCP48_TRAFFIC_PACKET_HEADERS,
    NDP_NS_MULTICAST_TRAFFIC_PACKET_HEADERS,
)
from taac.playbooks.playbook_definitions import (
    create_stable_state_validation_playbook,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import create_dummy_step
from taac.utils.test_config_utils import (
    create_raw_arp_request_traffic_item,
)
from taac.health_check.health_check import types as hc_thrift
from taac.test_as_a_config import types as taac_thrift


TEST_CONFIG_NAME = "QZD1_HATCH_STABLE_STATE"
PLAYBOOK_NAME = "test_stable_state_acl_traffic_matrix"

DUT = "rsw001.p006.f01.qzd1"
IXIA_CHASSIS_IP = "2401:db00:116:3006:21a:c5ff:fe01:6f54"
DUT_MAC = "76:d4:dd:40:0e:10"

W400_TEST_CONFIG_NAME = "QZD1_W400_HATCH_STABLE_STATE"
W400_PLAYBOOK_NAME = "test_w400_stable_state_acl_traffic_matrix"

W400_DUT = "rsw002.p005.f01.qzd1"
W400_DUT_MAC = "c2:18:50:b8:b8:c4"

# QZD1 (rsw001) port roles: A restricted, B blocked, C unconstrained.
PORT_A = "eth1/13/1"
PORT_B = "eth1/15/1"
PORT_C = "eth1/17/1"

# W400 (rsw002) carries the same roles on different ports.
W400_PORT_A = "eth1/20/1"
W400_PORT_B = "eth1/25/1"
W400_PORT_C = "eth1/10/1"


def _traffic_items(port_a, port_b, port_c):
    return [
        ("TCP22_U_TO_R_EXPECT_ALLOW", port_c, port_a, 22, 40001),
        ("TCP22_U_TO_B_EXPECT_BLOCK", port_c, port_b, 22, 40002),
        ("TCP22_R_TO_B_EXPECT_BLOCK", port_a, port_b, 22, 40003),
        ("TCP22_R_TO_U_EXPECT_BLOCK", port_a, port_c, 22, 40004),
        ("TCP443_R_TO_B_EXPECT_ALLOW", port_a, port_b, 443, 40005),
        ("TCP443_R_TO_U_EXPECT_ALLOW", port_a, port_c, 443, 40006),
        ("TCP443_B_TO_R_EXPECT_BLOCK", port_b, port_a, 443, 40007),
        ("TCP443_B_TO_U_EXPECT_BLOCK", port_b, port_c, 443, 40008),
    ]


def _raw_tcp_syn_traffic_items(port_a, port_b, port_c):
    return [
        ("RAW_TCP_SYN_R_TO_B_EXPECT_BLOCK", port_a, port_b, 40009),
        ("RAW_TCP_SYN_R_TO_U_EXPECT_BLOCK", port_a, port_c, 40010),
        ("RAW_TCP_SYN_B_TO_U_EXPECT_BLOCK", port_b, port_c, 40011),
        ("RAW_TCP_SYN_U_TO_R_EXPECT_BLOCK", port_c, port_a, 40012),
        ("RAW_TCP_SYN_U_TO_B_EXPECT_BLOCK", port_c, port_b, 40013),
    ]


def _udp_traffic_items(port_a, port_b, port_c):
    return [
        ("UDP443_R_TO_U_EXPECT_BLOCK", port_a, port_c, 443, 40014),
        ("UDP443_B_TO_U_EXPECT_BLOCK", port_b, port_c, 443, 40015),
        ("UDP443_U_TO_B_EXPECT_BLOCK", port_c, port_b, 443, 40016),
        ("UDP443_U_TO_R_EXPECT_BLOCK", port_c, port_a, 443, 40017),
    ]


def _bgp_syn_packet_headers():
    """Add SYN to the shared BGP header without changing the global constant."""
    headers = []
    for header in BGP_CP_V6_GLOBAL_DSCP48_TRAFFIC_PACKET_HEADERS:
        if header.query.regex != "tcp":
            headers.append(header)
            continue
        headers.append(
            taac_thrift.PacketHeader(
                query=header.query,
                append_to_query=header.append_to_query,
                fields=[
                    *(header.fields or []),
                    taac_thrift.Field(
                        query=ixia_thrift.Query(regex="^SYN$"),
                        attrs_json=json.dumps(
                            {
                                "ValueType": "singleValue",
                                "SingleValue": 1,
                            }
                        ),
                    ),
                ],
                remove_from_stack=header.remove_from_stack,
            )
        )
    return headers


def _disabled_cpu_traffic_items(port_a, port_b, port_c):
    bgp_syn_headers = _bgp_syn_packet_headers()
    return [
        ("RAW_BGP_R", port_a, port_b, bgp_syn_headers),
        ("RAW_BGP_B", port_b, port_c, bgp_syn_headers),
        ("RAW_BGP_U", port_c, port_a, bgp_syn_headers),
        ("RAW_DHCPV6_R", port_a, port_b, DHCP_V6_LL_DSCP48_TRAFFIC_PACKET_HEADERS),
        ("RAW_DHCPV6_B", port_b, port_c, DHCP_V6_LL_DSCP48_TRAFFIC_PACKET_HEADERS),
        ("RAW_DHCPV6_U", port_c, port_a, DHCP_V6_LL_DSCP48_TRAFFIC_PACKET_HEADERS),
        ("RAW_NDP_R", port_a, port_b, NDP_NS_MULTICAST_TRAFFIC_PACKET_HEADERS),
        ("RAW_NDP_B", port_b, port_c, NDP_NS_MULTICAST_TRAFFIC_PACKET_HEADERS),
        ("RAW_NDP_U", port_c, port_a, NDP_NS_MULTICAST_TRAFFIC_PACKET_HEADERS),
    ]


def _disabled_arp_traffic_items(port_a, port_b, port_c):
    return [
        ("RAW_ARP_R", port_a, port_b),
        ("RAW_ARP_B", port_b, port_c),
        ("RAW_ARP_U", port_c, port_a),
    ]


TRAFFIC_ITEMS = _traffic_items(PORT_A, PORT_B, PORT_C)
RAW_TCP_SYN_TRAFFIC_ITEMS = _raw_tcp_syn_traffic_items(PORT_A, PORT_B, PORT_C)
UDP_TRAFFIC_ITEMS = _udp_traffic_items(PORT_A, PORT_B, PORT_C)

ALLOWED_TRAFFIC_ITEMS = [
    "TCP22_U_TO_R_EXPECT_ALLOW",
    "TCP443_R_TO_B_EXPECT_ALLOW",
    "TCP443_R_TO_U_EXPECT_ALLOW",
]

# Port-independent: the raw-SYN names are appended per config, since those
# tuples are built from that device's ports.
BLOCKED_TCP_TRAFFIC_ITEMS = [
    "TCP22_U_TO_B_EXPECT_BLOCK",
    "TCP22_R_TO_B_EXPECT_BLOCK",
    "TCP22_R_TO_U_EXPECT_BLOCK",
    "TCP443_B_TO_R_EXPECT_BLOCK",
    "TCP443_B_TO_U_EXPECT_BLOCK",
]

BLOCKED_UDP_TRAFFIC_ITEMS = [item[0] for item in UDP_TRAFFIC_ITEMS]

BLOCKED_TRAFFIC_ITEMS = (
    BLOCKED_TCP_TRAFFIC_ITEMS
    + BLOCKED_UDP_TRAFFIC_ITEMS
    + [item[0] for item in RAW_TCP_SYN_TRAFFIC_ITEMS]
)


def _tcp_syn_headers(destination_port, source_port):
    return [
        taac_thrift.PacketHeader(
            query=ixia_thrift.Query(
                regex="tcp",
                query_type=ixia_thrift.QueryType.STACK_TYPE_ID,
            ),
            append_to_query=ixia_thrift.Query(
                regex="ipv6",
                query_type=ixia_thrift.QueryType.STACK_TYPE_ID,
            ),
            fields=[
                taac_thrift.Field(
                    query=ixia_thrift.Query(regex="TCP-Source-Port"),
                    attrs_json=json.dumps(
                        {
                            "Auto": False,
                            "ValueType": "singleValue",
                            "SingleValue": source_port,
                        }
                    ),
                ),
                taac_thrift.Field(
                    query=ixia_thrift.Query(regex="TCP-Dest-Port"),
                    attrs_json=json.dumps(
                        {
                            "Auto": False,
                            "ValueType": "singleValue",
                            "SingleValue": destination_port,
                        }
                    ),
                ),
                taac_thrift.Field(
                    query=ixia_thrift.Query(regex="^SYN$"),
                    attrs_json=json.dumps(
                        {
                            "ValueType": "singleValue",
                            "SingleValue": 1,
                        }
                    ),
                ),
            ],
        )
    ]


def _udp_headers(destination_port, source_port):
    return [
        taac_thrift.PacketHeader(
            query=ixia_thrift.Query(
                regex="^udp$",
                query_type=ixia_thrift.QueryType.STACK_TYPE_ID,
            ),
            append_to_query=ixia_thrift.Query(
                regex="ipv6",
                query_type=ixia_thrift.QueryType.STACK_TYPE_ID,
            ),
            fields=[
                taac_thrift.Field(
                    query=ixia_thrift.Query(regex="UDP-Source-Port"),
                    attrs_json=json.dumps(
                        {
                            "Auto": False,
                            "ValueType": "singleValue",
                            "SingleValue": source_port,
                        }
                    ),
                ),
                taac_thrift.Field(
                    query=ixia_thrift.Query(regex="UDP-Dest-Port"),
                    attrs_json=json.dumps(
                        {
                            "Auto": False,
                            "ValueType": "singleValue",
                            "SingleValue": destination_port,
                        }
                    ),
                ),
            ],
        )
    ]


def _raw_tcp_syn_headers(destination_port, source_port, dut_mac=DUT_MAC):
    return [
        taac_thrift.PacketHeader(
            query=ixia_thrift.Query(
                regex="^ethernet$",
                query_type=ixia_thrift.QueryType.STACK_TYPE_ID,
            ),
            fields=[
                taac_thrift.Field(
                    query=ixia_thrift.Query(regex="Destination MAC Address"),
                    attrs_json=json.dumps(
                        {
                            "ValueType": "singleValue",
                            "SingleValue": dut_mac,
                        }
                    ),
                ),
                taac_thrift.Field(
                    query=ixia_thrift.Query(regex="Source MAC Address"),
                    attrs_json=json.dumps({"ValueType": "singleValue"}),
                    references={
                        "SingleValue": taac_thrift.Reference(
                            type=taac_thrift.ReferenceType.SRC_MAC_ADDRESS
                        )
                    },
                ),
            ],
        ),
        taac_thrift.PacketHeader(
            query=ixia_thrift.Query(
                regex="^ipv6$",
                query_type=ixia_thrift.QueryType.STACK_TYPE_ID,
            ),
            append_to_query=ixia_thrift.Query(
                regex="^ethernet$",
                query_type=ixia_thrift.QueryType.STACK_TYPE_ID,
            ),
            fields=[
                taac_thrift.Field(
                    query=ixia_thrift.Query(regex="Source Address"),
                    attrs_json=json.dumps(
                        {
                            "ValueType": "increment",
                            "StepValue": "::1",
                            "CountValue": 1,
                        }
                    ),
                    references={
                        "StartValue": taac_thrift.Reference(
                            type=taac_thrift.ReferenceType.SRC_IPV6_ADDRESS
                        )
                    },
                ),
                taac_thrift.Field(
                    query=ixia_thrift.Query(regex="Destination Address"),
                    attrs_json=json.dumps({"ValueType": "valueList"}),
                    references={
                        "ValueList": taac_thrift.Reference(
                            type=taac_thrift.ReferenceType.DST_IPV6_ADDRESS,
                            data_type=taac_thrift.DataType.LIST,
                        )
                    },
                ),
            ],
        ),
        taac_thrift.PacketHeader(
            query=ixia_thrift.Query(
                regex="tcp",
                query_type=ixia_thrift.QueryType.STACK_TYPE_ID,
            ),
            append_to_query=ixia_thrift.Query(
                regex="ipv6",
                query_type=ixia_thrift.QueryType.STACK_TYPE_ID,
            ),
            fields=[
                taac_thrift.Field(
                    query=ixia_thrift.Query(regex="TCP-Source-Port"),
                    attrs_json=json.dumps(
                        {
                            "Auto": False,
                            "ValueType": "singleValue",
                            "SingleValue": source_port,
                        }
                    ),
                ),
                taac_thrift.Field(
                    query=ixia_thrift.Query(regex="TCP-Dest-Port"),
                    attrs_json=json.dumps(
                        {
                            "Auto": False,
                            "ValueType": "singleValue",
                            "SingleValue": destination_port,
                        }
                    ),
                ),
                taac_thrift.Field(
                    query=ixia_thrift.Query(regex="^SYN$"),
                    attrs_json=json.dumps(
                        {
                            "ValueType": "singleValue",
                            "SingleValue": 1,
                        }
                    ),
                ),
            ],
        ),
    ]


def _traffic_endpoint(port, dut=DUT):
    return taac_thrift.TrafficEndpoint(
        name=f"{dut}:{port}",
        device_group_index=0,
    )


def _traffic_item(
    name, source_port, destination_port, tcp_port, source_tcp_port, dut=DUT
):
    return taac_thrift.BasicTrafficItemConfig(
        name=name,
        bidirectional=False,
        line_rate=1,
        line_rate_type=ixia_thrift.RateType.PERCENT_LINE_RATE,
        src_dest_mesh=ixia_thrift.SrcDestMeshType.ONE_TO_ONE,
        src_endpoints=[_traffic_endpoint(source_port, dut)],
        dest_endpoints=[_traffic_endpoint(destination_port, dut)],
        traffic_type=ixia_thrift.TrafficType.IPV6,
        frame_size_settings=ixia_thrift.FrameSize(
            type=ixia_thrift.FrameSizeType.FIXED,
            fixed_size=400,
        ),
        tracking_types=[ixia_thrift.TrafficStatsTrackingType.TRAFFIC_ITEM],
        packet_headers=_tcp_syn_headers(tcp_port, source_tcp_port),
        skip_default_l4_protocol=True,
    )


def _udp_traffic_item(
    name, source_port, destination_port, udp_port, source_udp_port, dut=DUT
):
    return taac_thrift.BasicTrafficItemConfig(
        name=name,
        bidirectional=False,
        line_rate=1,
        line_rate_type=ixia_thrift.RateType.PERCENT_LINE_RATE,
        src_dest_mesh=ixia_thrift.SrcDestMeshType.ONE_TO_ONE,
        src_endpoints=[_traffic_endpoint(source_port, dut)],
        dest_endpoints=[_traffic_endpoint(destination_port, dut)],
        traffic_type=ixia_thrift.TrafficType.IPV6,
        frame_size_settings=ixia_thrift.FrameSize(
            type=ixia_thrift.FrameSizeType.FIXED,
            fixed_size=400,
        ),
        tracking_types=[ixia_thrift.TrafficStatsTrackingType.TRAFFIC_ITEM],
        packet_headers=_udp_headers(udp_port, source_udp_port),
        skip_default_l4_protocol=True,
    )


def _raw_traffic_item(
    name,
    source_port,
    destination_port,
    packet_headers,
    line_rate,
    enabled,
    frame_size,
    dut=DUT,
):
    return taac_thrift.BasicTrafficItemConfig(
        name=name,
        enabled=enabled,
        bidirectional=False,
        line_rate=line_rate,
        line_rate_type=ixia_thrift.RateType.PERCENT_LINE_RATE,
        src_dest_mesh=ixia_thrift.SrcDestMeshType.ONE_TO_ONE,
        src_endpoints=[_traffic_endpoint(source_port, dut)],
        dest_endpoints=[_traffic_endpoint(destination_port, dut)],
        traffic_type=ixia_thrift.TrafficType.RAW,
        frame_size_settings=ixia_thrift.FrameSize(
            type=ixia_thrift.FrameSizeType.FIXED,
            fixed_size=frame_size,
        ),
        tracking_types=[ixia_thrift.TrafficStatsTrackingType.TRAFFIC_ITEM],
        packet_headers=packet_headers,
    )


def _raw_cpu_traffic_item(name, source_port, destination_port, packet_headers, dut=DUT):
    return taac_thrift.BasicTrafficItemConfig(
        src_endpoints=[
            taac_thrift.TrafficEndpoint(
                name=f"{dut}:{source_port}",
                network_group_index=0,
                device_group_index=0,
            )
        ],
        dest_endpoints=[
            taac_thrift.TrafficEndpoint(
                name=f"{dut}:{destination_port}",
                network_group_index=0,
                device_group_index=0,
            )
        ],
        name=name,
        enabled=False,
        line_rate_type=ixia_thrift.RateType.PERCENT_LINE_RATE,
        line_rate=5,
        traffic_type=ixia_thrift.TrafficType.RAW,
        bidirectional=False,
        skip_default_l4_protocol=True,
        packet_headers=packet_headers,
    )


def _port_config(port, starting_ip, gateway, mask, dut=DUT):
    return taac_thrift.BasicPortConfig(
        endpoint=f"{dut}:{port}",
        device_group_configs=[
            taac_thrift.DeviceGroupConfig(
                device_group_index=0,
                multiplier=1,
                v6_addresses_config=taac_thrift.IpAddressesConfig(
                    starting_ip=starting_ip,
                    increment_ip="0:0:0:0:0:0:0:1",
                    gateway_starting_ip=gateway,
                    gateway_increment_ip="0:0:0:0:0:0:0:0",
                    mask=mask,
                ),
            )
        ],
    )


def _unclean_exit_check():
    return create_unclean_exit_check(
        check_id="agent_fsdb_bgp_qsfp_unclean_exit",
        services=["wedge_agent", "fsdb", "bgpd", "qsfp_service"],
        sleep_timer=0,
    )


def _traffic_loss_check(allowed=None, blocked=None):
    return create_ixia_packet_loss_check(
        check_id="acl_traffic_loss_percentage",
        clear_traffic_stats=True,
        sleep_time=15,
        thresholds=[
            hc_thrift.PacketLossThreshold(
                names=allowed if allowed is not None else ALLOWED_TRAFFIC_ITEMS,
                str_value="0",
                metric=hc_thrift.PacketLossMetric.PERCENTAGE,
                comparison=hc_thrift.ComparisonType.EQUAL_TO,
            ),
            hc_thrift.PacketLossThreshold(
                names=blocked if blocked is not None else BLOCKED_TRAFFIC_ITEMS,
                str_value="100",
                metric=hc_thrift.PacketLossMetric.PERCENTAGE,
                comparison=hc_thrift.ComparisonType.EQUAL_TO,
            ),
        ],
    )


def _build_test_config(
    name,
    dut,
    dut_mac,
    chassis_ip,
    ports,
    ixia_ports,
    addressing,
    playbook_name,
):
    """Assemble one stable-state access-policy TestConfig.

    Args:
        ports: (port_a, port_b, port_c) -- restricted, blocked, unconstrained.
        ixia_ports: chassis-side port for each of `ports`, in the same order.
        addressing: (starting_ip, gateway, mask) for each of `ports`, same order.
    """
    port_a, port_b, port_c = ports
    traffic_items = _traffic_items(port_a, port_b, port_c)
    raw_tcp_syn_items = _raw_tcp_syn_traffic_items(port_a, port_b, port_c)
    udp_items = _udp_traffic_items(port_a, port_b, port_c)
    arp_items = _disabled_arp_traffic_items(port_a, port_b, port_c)
    blocked = (
        BLOCKED_TCP_TRAFFIC_ITEMS
        + [item[0] for item in udp_items]
        + [item[0] for item in raw_tcp_syn_items]
    )
    return taac_thrift.TestConfig(
        name=name,
        basset_pool="dne.test",
        ignore_circuit_fbnet_status=True,
        # Traffic items are part of this test's contract, including the disabled
        # CPU-control-plane items retained for manual activation.  Avoid loading a
        # topology-only cache that may predate those traffic-item definitions.
        ixia_config_cache=taac_thrift.IxiaConfigCache(enabled=False),
        endpoints=[
            taac_thrift.Endpoint(
                name=dut,
                dut=True,
                mac_address=dut_mac,
                ixia_needed=True,
                ixia_ports=[port_a, port_b, port_c],
                direct_ixia_connections=[
                    taac_thrift.DirectIxiaConnection(
                        interface=port,
                        ixia_chassis_ip=chassis_ip,
                        ixia_port=ixia_port,
                    )
                    for port, ixia_port in zip(ports, ixia_ports)
                ],
            )
        ],
        basic_port_configs=[
            _port_config(port, starting_ip, gateway, mask, dut)
            for port, (starting_ip, gateway, mask) in zip(ports, addressing)
        ],
        basic_traffic_item_configs=[
            _traffic_item(
                item_name, source, destination, tcp_port, source_tcp_port, dut
            )
            for item_name, source, destination, tcp_port, source_tcp_port in traffic_items
        ]
        + [
            _udp_traffic_item(
                item_name, source, destination, udp_port, source_udp_port, dut
            )
            for item_name, source, destination, udp_port, source_udp_port in udp_items
        ]
        + [
            _raw_traffic_item(
                item_name,
                source,
                destination,
                _raw_tcp_syn_headers(22, source_tcp_port, dut_mac),
                1,
                True,
                400,
                dut,
            )
            for item_name, source, destination, source_tcp_port in raw_tcp_syn_items
        ]
        + [
            _raw_cpu_traffic_item(item_name, source, destination, headers, dut)
            for item_name, source, destination, headers in _disabled_cpu_traffic_items(
                port_a, port_b, port_c
            )
        ]
        + [
            create_raw_arp_request_traffic_item(
                name=item_name,
                source_endpoint=f"{dut}:{source}",
                destination_endpoint=f"{dut}:{destination}",
                line_rate_type=ixia_thrift.RateType.PERCENT_LINE_RATE,
                line_rate=5,
                enabled=False,
            )
            for item_name, source, destination in arp_items
        ],
        playbooks=[
            create_stable_state_validation_playbook(
                name=playbook_name,
                description=(
                    "Stable-state validation of the Restricted, Blocked, and "
                    "Unconstrained port ACL traffic matrix. No DUT state is changed."
                ),
                device_regexes=[dut],
                traffic_items_to_start=[item[0] for item in traffic_items]
                + [item[0] for item in udp_items]
                + [item[0] for item in raw_tcp_syn_items],
                prechecks=[
                    _unclean_exit_check(),
                    _traffic_loss_check(ALLOWED_TRAFFIC_ITEMS, blocked),
                ],
                postchecks=[
                    _unclean_exit_check(),
                    _traffic_loss_check(ALLOWED_TRAFFIC_ITEMS, blocked),
                ],
                stages=[
                    create_steps_stage(
                        stage_id="stable_state_noop",
                        description="No-op stage between pre- and post-validation.",
                        steps=[
                            create_dummy_step(
                                description="Intentionally make no DUT changes.",
                            )
                        ],
                    )
                ],
            )
        ],
    )


test_config = _build_test_config(
    name=TEST_CONFIG_NAME,
    dut=DUT,
    dut_mac=DUT_MAC,
    chassis_ip=IXIA_CHASSIS_IP,
    ports=(PORT_A, PORT_B, PORT_C),
    ixia_ports=("1/135", "1/138", "1/137"),
    addressing=(
        ("2401:db00:e50e:1205::30", "2401:db00:e50e:1205::31", 127),
        ("2401:db00:e50e:1305::30", "2401:db00:e50e:1305::31", 127),
        ("2401:db00:501c:500::100", "2401:db00:501c:500::a", 64),
    ),
    playbook_name=PLAYBOOK_NAME,
)

w400_test_config = _build_test_config(
    name=W400_TEST_CONFIG_NAME,
    dut=W400_DUT,
    dut_mac=W400_DUT_MAC,
    chassis_ip=IXIA_CHASSIS_IP,
    ports=(W400_PORT_A, W400_PORT_B, W400_PORT_C),
    ixia_ports=("1/143", "1/144", "1/142"),
    # All three W400 ports are downlinks in the same vlan 2000 broadcast
    # domain, so they share one /64 and one gateway.
    addressing=(
        ("2401:db00:501c:401::2", "2401:db00:501c:401::a", 64),
        ("2401:db00:501c:401::3", "2401:db00:501c:401::a", 64),
        ("2401:db00:501c:401::1", "2401:db00:501c:401::a", 64),
    ),
    playbook_name=W400_PLAYBOOK_NAME,
)
