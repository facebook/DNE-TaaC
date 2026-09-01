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
from taac.health_check.health_check import types as hc_thrift
from taac.test_as_a_config import types as taac_thrift


TEST_CONFIG_NAME = "QZD1_HATCH_STABLE_STATE"
PLAYBOOK_NAME = "test_stable_state_acl_traffic_matrix"

DUT = "rsw001.p006.f01.qzd1"
IXIA_CHASSIS_IP = "2401:db00:116:3006:21a:c5ff:fe01:6f54"
DUT_MAC = "76:d4:dd:40:0e:10"

PORT_A = "eth1/13/1"
PORT_B = "eth1/15/1"
PORT_C = "eth1/17/1"

TRAFFIC_ITEMS = [
    ("TCP22_U_TO_R_EXPECT_ALLOW", PORT_C, PORT_A, 22, 40001),
    ("TCP22_U_TO_B_EXPECT_BLOCK", PORT_C, PORT_B, 22, 40002),
    ("TCP22_R_TO_B_EXPECT_BLOCK", PORT_A, PORT_B, 22, 40003),
    ("TCP22_R_TO_U_EXPECT_BLOCK", PORT_A, PORT_C, 22, 40004),
    ("TCP443_R_TO_B_EXPECT_ALLOW", PORT_A, PORT_B, 443, 40005),
    ("TCP443_R_TO_U_EXPECT_ALLOW", PORT_A, PORT_C, 443, 40006),
    ("TCP443_B_TO_R_EXPECT_BLOCK", PORT_B, PORT_A, 443, 40007),
    ("TCP443_B_TO_U_EXPECT_BLOCK", PORT_B, PORT_C, 443, 40008),
]

RAW_TCP_SYN_TRAFFIC_ITEMS = [
    ("RAW_TCP_SYN_R_TO_B_EXPECT_BLOCK", PORT_A, PORT_B, 40009),
    ("RAW_TCP_SYN_R_TO_U_EXPECT_BLOCK", PORT_A, PORT_C, 40010),
    ("RAW_TCP_SYN_B_TO_U_EXPECT_BLOCK", PORT_B, PORT_C, 40011),
]

DISABLED_CPU_TRAFFIC_ITEMS = [
    (
        "RAW_BGP_R",
        PORT_A,
        PORT_B,
        BGP_CP_V6_GLOBAL_DSCP48_TRAFFIC_PACKET_HEADERS,
    ),
    (
        "RAW_BGP_B",
        PORT_B,
        PORT_C,
        BGP_CP_V6_GLOBAL_DSCP48_TRAFFIC_PACKET_HEADERS,
    ),
    (
        "RAW_BGP_U",
        PORT_C,
        PORT_A,
        BGP_CP_V6_GLOBAL_DSCP48_TRAFFIC_PACKET_HEADERS,
    ),
    (
        "RAW_DHCPV6_R",
        PORT_A,
        PORT_B,
        DHCP_V6_LL_DSCP48_TRAFFIC_PACKET_HEADERS,
    ),
    (
        "RAW_DHCPV6_B",
        PORT_B,
        PORT_C,
        DHCP_V6_LL_DSCP48_TRAFFIC_PACKET_HEADERS,
    ),
    (
        "RAW_DHCPV6_U",
        PORT_C,
        PORT_A,
        DHCP_V6_LL_DSCP48_TRAFFIC_PACKET_HEADERS,
    ),
    (
        "RAW_NDP_R",
        PORT_A,
        PORT_B,
        NDP_NS_MULTICAST_TRAFFIC_PACKET_HEADERS,
    ),
    (
        "RAW_NDP_B",
        PORT_B,
        PORT_C,
        NDP_NS_MULTICAST_TRAFFIC_PACKET_HEADERS,
    ),
    (
        "RAW_NDP_U",
        PORT_C,
        PORT_A,
        NDP_NS_MULTICAST_TRAFFIC_PACKET_HEADERS,
    ),
]

ALLOWED_TRAFFIC_ITEMS = [
    "TCP22_U_TO_R_EXPECT_ALLOW",
    "TCP443_R_TO_B_EXPECT_ALLOW",
    "TCP443_R_TO_U_EXPECT_ALLOW",
]

BLOCKED_TRAFFIC_ITEMS = [
    "TCP22_U_TO_B_EXPECT_BLOCK",
    "TCP22_R_TO_B_EXPECT_BLOCK",
    "TCP22_R_TO_U_EXPECT_BLOCK",
    "TCP443_B_TO_R_EXPECT_BLOCK",
    "TCP443_B_TO_U_EXPECT_BLOCK",
] + [item[0] for item in RAW_TCP_SYN_TRAFFIC_ITEMS]


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


def _raw_tcp_syn_headers(destination_port, source_port):
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
                            "SingleValue": DUT_MAC,
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


def _traffic_endpoint(port):
    return taac_thrift.TrafficEndpoint(
        name=f"{DUT}:{port}",
        device_group_index=0,
    )


def _traffic_item(name, source_port, destination_port, tcp_port, source_tcp_port):
    return taac_thrift.BasicTrafficItemConfig(
        name=name,
        bidirectional=False,
        line_rate=1,
        line_rate_type=ixia_thrift.RateType.PERCENT_LINE_RATE,
        src_dest_mesh=ixia_thrift.SrcDestMeshType.ONE_TO_ONE,
        src_endpoints=[_traffic_endpoint(source_port)],
        dest_endpoints=[_traffic_endpoint(destination_port)],
        traffic_type=ixia_thrift.TrafficType.IPV6,
        frame_size_settings=ixia_thrift.FrameSize(
            type=ixia_thrift.FrameSizeType.FIXED,
            fixed_size=400,
        ),
        tracking_types=[ixia_thrift.TrafficStatsTrackingType.TRAFFIC_ITEM],
        packet_headers=_tcp_syn_headers(tcp_port, source_tcp_port),
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
):
    return taac_thrift.BasicTrafficItemConfig(
        name=name,
        enabled=enabled,
        bidirectional=False,
        line_rate=line_rate,
        line_rate_type=ixia_thrift.RateType.PERCENT_LINE_RATE,
        src_dest_mesh=ixia_thrift.SrcDestMeshType.ONE_TO_ONE,
        src_endpoints=[_traffic_endpoint(source_port)],
        dest_endpoints=[_traffic_endpoint(destination_port)],
        traffic_type=ixia_thrift.TrafficType.RAW,
        frame_size_settings=ixia_thrift.FrameSize(
            type=ixia_thrift.FrameSizeType.FIXED,
            fixed_size=frame_size,
        ),
        tracking_types=[ixia_thrift.TrafficStatsTrackingType.TRAFFIC_ITEM],
        packet_headers=packet_headers,
    )


def _raw_cpu_traffic_item(name, source_port, destination_port, packet_headers):
    return taac_thrift.BasicTrafficItemConfig(
        src_endpoints=[
            taac_thrift.TrafficEndpoint(
                name=f"{DUT}:{source_port}",
                network_group_index=0,
                device_group_index=0,
            )
        ],
        dest_endpoints=[
            taac_thrift.TrafficEndpoint(
                name=f"{DUT}:{destination_port}",
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


def _port_config(port, starting_ip, gateway, mask):
    return taac_thrift.BasicPortConfig(
        endpoint=f"{DUT}:{port}",
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


def _traffic_loss_check():
    return create_ixia_packet_loss_check(
        check_id="acl_traffic_loss_percentage",
        clear_traffic_stats=True,
        sleep_time=15,
        thresholds=[
            hc_thrift.PacketLossThreshold(
                names=ALLOWED_TRAFFIC_ITEMS,
                str_value="0",
                metric=hc_thrift.PacketLossMetric.PERCENTAGE,
                comparison=hc_thrift.ComparisonType.EQUAL_TO,
            ),
            hc_thrift.PacketLossThreshold(
                names=BLOCKED_TRAFFIC_ITEMS,
                str_value="100",
                metric=hc_thrift.PacketLossMetric.PERCENTAGE,
                comparison=hc_thrift.ComparisonType.EQUAL_TO,
            ),
        ],
    )


test_config = taac_thrift.TestConfig(
    name=TEST_CONFIG_NAME,
    basset_pool="dne.test",
    ignore_circuit_fbnet_status=True,
    # Traffic items are part of this test's contract, including the disabled
    # CPU-control-plane items retained for manual activation.  Avoid loading a
    # topology-only cache that may predate those traffic-item definitions.
    ixia_config_cache=taac_thrift.IxiaConfigCache(enabled=False),
    endpoints=[
        taac_thrift.Endpoint(
            name=DUT,
            dut=True,
            mac_address=DUT_MAC,
            ixia_needed=True,
            ixia_ports=[PORT_A, PORT_B, PORT_C],
            direct_ixia_connections=[
                taac_thrift.DirectIxiaConnection(
                    interface=PORT_A,
                    ixia_chassis_ip=IXIA_CHASSIS_IP,
                    ixia_port="1/135",
                ),
                taac_thrift.DirectIxiaConnection(
                    interface=PORT_B,
                    ixia_chassis_ip=IXIA_CHASSIS_IP,
                    ixia_port="1/138",
                ),
                taac_thrift.DirectIxiaConnection(
                    interface=PORT_C,
                    ixia_chassis_ip=IXIA_CHASSIS_IP,
                    ixia_port="1/137",
                ),
            ],
        )
    ],
    basic_port_configs=[
        _port_config(
            PORT_A,
            "2401:db00:e50e:1205::30",
            "2401:db00:e50e:1205::31",
            127,
        ),
        _port_config(
            PORT_B,
            "2401:db00:e50e:1305::30",
            "2401:db00:e50e:1305::31",
            127,
        ),
        _port_config(
            PORT_C,
            "2401:db00:501c:500::100",
            "2401:db00:501c:500::a",
            64,
        ),
    ],
    basic_traffic_item_configs=[
        _traffic_item(name, source, destination, tcp_port, source_tcp_port)
        for name, source, destination, tcp_port, source_tcp_port in TRAFFIC_ITEMS
    ]
    + [
        _raw_traffic_item(
            name,
            source,
            destination,
            _raw_tcp_syn_headers(22, source_tcp_port),
            1,
            True,
            400,
        )
        for name, source, destination, source_tcp_port in RAW_TCP_SYN_TRAFFIC_ITEMS
    ]
    + [
        _raw_cpu_traffic_item(name, source, destination, headers)
        for name, source, destination, headers in DISABLED_CPU_TRAFFIC_ITEMS
    ],
    playbooks=[
        create_stable_state_validation_playbook(
            name=PLAYBOOK_NAME,
            description=(
                "Stable-state validation of the Restricted, Blocked, and "
                "Unconstrained port ACL traffic matrix. No DUT state is changed."
            ),
            device_regexes=[DUT],
            traffic_items_to_start=[item[0] for item in TRAFFIC_ITEMS]
            + [item[0] for item in RAW_TCP_SYN_TRAFFIC_ITEMS],
            prechecks=[_unclean_exit_check(), _traffic_loss_check()],
            postchecks=[_unclean_exit_check(), _traffic_loss_check()],
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
