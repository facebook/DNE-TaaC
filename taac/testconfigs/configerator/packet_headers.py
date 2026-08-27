# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import json

from ixia.ixia import types as ixia_thrift
from taac.health_check.health_check import types as hc_thrift
from taac.test_as_a_config import types as taac_thrift


LLDP_DEST_MULTICAST_MAC: str = "01:80:c2:00:00:0e"
LACP_DEST_MULTICAST_MAC: str = "01:80:C2:00:00:02"
# Random mac address, not specific to any particular traffic item/ixia port or device
DEFAULT_SRC_MAC_ADDRESS: str = "00:11:01:00:00:01"
ROGUE_SRC_MAC_ADDRESS: str = "00:f1:01:00:00:01"

# Broadcast mac address
BROADCAST_DST_MAC_ADDRESS: str = "ff:ff:ff:ff:ff:ff"

BGP_PORT: str = "179"
RDMA_PORT: str = "4791"
DHCPV6_MULTICAST_ADDR: str = "fe80::a00:27ff:fefe:8f95"
DHCPV6_SERVER_MULTICAST_ADDR: str = "ff02::1:2"
DHCPV6_SERVER_PORT: str = "547"
DHCPV6_RELAY_PORT: str = "546"


#############################################################
#                        Raw Traffic                        #
#############################################################

PFC_PAUSE_PACKET_HEADERS = [
    taac_thrift.PacketHeader(
        query=ixia_thrift.Query(
            regex="pfcPause", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
        fields=[
            taac_thrift.Field(
                query=ixia_thrift.Query(
                    regex="priority_enable_vector",
                ),
                attrs_json=json.dumps(
                    {
                        "SingleValue": 4,
                    }
                ),
            ),
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="PFC Queue 0"),
                attrs_json=json.dumps(
                    {
                        "SingleValue": 0,
                    }
                ),
            ),
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="PFC Queue 2"),
                attrs_json=json.dumps(
                    {
                        "SingleValue": "ffff",
                    }
                ),
            ),
        ],
        append_to_query=ixia_thrift.Query(
            regex="^ethernet$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
    ),
    taac_thrift.PacketHeader(
        query=ixia_thrift.Query(
            regex="^ethernet$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
        remove_from_stack=True,
    ),
]


def create_generic_pfc_pause_packet_headers(priority_enable_vector, pfc_queue):
    """PFC pause headers with a specific queue paused (all 8 queues explicitly set).

    Args:
        priority_enable_vector: IXIA hex-field value selecting priorities for flow control.
            Prefer a hexadecimal string for values above 9.
        pfc_queue: Integer (0-7) specifying which queue to pause (set to "ffff"),
            all other queues are set to 0
    """
    return [
        taac_thrift.PacketHeader(
            query=ixia_thrift.Query(
                regex="pfcPause",
                query_type=ixia_thrift.QueryType.STACK_TYPE_ID,
            ),
            fields=[
                taac_thrift.Field(
                    query=ixia_thrift.Query(regex="priority_enable_vector"),
                    attrs_json=json.dumps({"SingleValue": priority_enable_vector}),
                ),
            ]
            + [
                taac_thrift.Field(
                    query=ixia_thrift.Query(regex=f"PFC Queue {i}"),
                    attrs_json=json.dumps(
                        {"SingleValue": "ffff" if i == pfc_queue else 0}
                    ),
                )
                for i in range(8)
            ],
            append_to_query=ixia_thrift.Query(
                regex="^ethernet$",
                query_type=ixia_thrift.QueryType.STACK_TYPE_ID,
            ),
        ),
        taac_thrift.PacketHeader(
            query=ixia_thrift.Query(
                regex="^ethernet$",
                query_type=ixia_thrift.QueryType.STACK_TYPE_ID,
            ),
            remove_from_stack=True,
        ),
    ]


TC2_PFC_PAUSE_PACKET_HEADERS = create_generic_pfc_pause_packet_headers(4, 2)
TC0_PFC_PAUSE_PACKET_HEADERS = create_generic_pfc_pause_packet_headers("01", 0)
TC6_PFC_PAUSE_PACKET_HEADERS = create_generic_pfc_pause_packet_headers("40", 6)


LLDP_TRAFFIC_PACKET_HEADERS = [
    taac_thrift.PacketHeader(
        query=ixia_thrift.Query(
            regex="^ethernet$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
        fields=[
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="Destination MAC Address"),
                attrs_json=json.dumps(
                    {
                        "ValueType": "increment",
                        "StartValue": LLDP_DEST_MULTICAST_MAC,
                        "StepValue": "00:00:00:00:00:00",
                        "CountValue": 1,
                    }
                ),
            ),
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="Source MAC Address"),
                attrs_json=json.dumps(
                    {
                        "ValueType": "increment",
                        "StartValue": DEFAULT_SRC_MAC_ADDRESS,
                        "StepValue": "00:00:00:00:00:00",
                        "CountValue": 1,
                    }
                ),
            ),
        ],
    ),
    taac_thrift.PacketHeader(
        query=ixia_thrift.Query(
            regex="^lldp$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
        append_to_query=ixia_thrift.Query(
            regex="^ethernet$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
    ),
]

LACP_SLOW_TIMER_TRAFFIC_PACKET_HEADERS = [
    taac_thrift.PacketHeader(
        query=ixia_thrift.Query(
            regex="^ethernet$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
        fields=[
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="Ethernet-Type"),
                attrs_json=json.dumps(
                    {"Auto": False, "SingleValue": "8809"}  # Slow Protocols: 0x8809
                ),
            ),
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="Destination MAC Address"),
                attrs_json=json.dumps(
                    {
                        "ValueType": "increment",
                        "StartValue": LACP_DEST_MULTICAST_MAC,
                        "StepValue": "00:00:00:00:00:00",
                        "CountValue": 1,
                    }
                ),
            ),
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="Source MAC Address"),
                attrs_json=json.dumps(
                    {
                        "ValueType": "increment",
                        "StartValue": DEFAULT_SRC_MAC_ADDRESS,
                        "StepValue": "00:00:00:00:00:00",
                        "CountValue": 1,
                    }
                ),
            ),
        ],
    ),
    taac_thrift.PacketHeader(
        query=ixia_thrift.Query(
            regex="^lacp$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
        append_to_query=ixia_thrift.Query(
            regex="^ethernet$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
    ),
]


ARP_TRAFFIC_PACKET_HEADERS = [
    taac_thrift.PacketHeader(
        query=ixia_thrift.Query(
            regex="^ethernet$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
        fields=[
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="Ethernet-Type"),
                attrs_json=json.dumps({"Auto": False, "SingleValue": "0806"}),
            ),
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="Destination MAC Address"),
                attrs_json=json.dumps(
                    {
                        "ValueType": "increment",
                        "StepValue": "00:00:00:00:00:00",
                        "CountValue": 1,
                    }
                ),
                references={
                    "StartValue": taac_thrift.Reference(
                        type=taac_thrift.ReferenceType.DST_MAC_ADDRESS
                    ),
                },
            ),
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="Source MAC Address"),
                attrs_json=json.dumps(
                    {
                        "ValueType": "increment",
                        "StartValue": DEFAULT_SRC_MAC_ADDRESS,
                        "StepValue": "00:00:00:00:00:00",
                        "CountValue": 1,
                    }
                ),
            ),
        ],
    ),
    taac_thrift.PacketHeader(
        query=ixia_thrift.Query(
            regex="^lldp$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
        append_to_query=ixia_thrift.Query(
            regex="^ethernet$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
    ),
]

ICMP_V6_REQUEST_TRAFFIC_PACKET_HEADERS = [
    taac_thrift.PacketHeader(
        query=ixia_thrift.Query(
            regex="^ethernet$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
        fields=[
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="Destination MAC Address"),
                attrs_json=json.dumps(
                    {
                        "ValueType": "increment",
                        "StepValue": "00:00:00:00:00:00",
                        "CountValue": 1,
                    }
                ),
                references={
                    "StartValue": taac_thrift.Reference(
                        type=taac_thrift.ReferenceType.DST_MAC_ADDRESS
                    ),
                },
            ),
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="Source MAC Address"),
                attrs_json=json.dumps(
                    {
                        "ValueType": "increment",
                        "StartValue": DEFAULT_SRC_MAC_ADDRESS,
                        "StepValue": "00:00:00:00:00:00",
                        "CountValue": 1,
                    }
                ),
            ),
        ],
    ),
    taac_thrift.PacketHeader(
        query=ixia_thrift.Query(
            regex="^ipv6$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
        append_to_query=ixia_thrift.Query(
            regex="^ethernet$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
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
                    ),
                },
            ),
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="Destination Address"),
                attrs_json=json.dumps(
                    {
                        "ValueType": "valueList",
                    }
                ),
                references={
                    "ValueList": taac_thrift.Reference(
                        type=taac_thrift.ReferenceType.DST_GATEWAY_IPV6_ADDRESS,
                        data_type=taac_thrift.DataType.LIST,
                    ),
                },
            ),
        ],
    ),
    taac_thrift.PacketHeader(
        query=ixia_thrift.Query(
            regex="icmpv6", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
        append_to_query=ixia_thrift.Query(
            regex="ipv6", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
    ),
]

BGP_CP_TRAFFIC_PACKET_HEADERS = [
    taac_thrift.PacketHeader(
        query=ixia_thrift.Query(
            regex="^ethernet$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
        fields=[
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="Destination MAC Address"),
                attrs_json=json.dumps(
                    {
                        "ValueType": "increment",
                        "StepValue": "00:00:00:00:00:00",
                        "CountValue": 1,
                    }
                ),
                references={
                    "StartValue": taac_thrift.Reference(
                        type=taac_thrift.ReferenceType.DST_MAC_ADDRESS
                    ),
                },
            ),
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="Source MAC Address"),
                attrs_json=json.dumps(
                    {
                        "ValueType": "increment",
                        "StartValue": DEFAULT_SRC_MAC_ADDRESS,
                        "StepValue": "00:00:00:00:00:00",
                        "CountValue": 1,
                    }
                ),
            ),
        ],
    ),
    taac_thrift.PacketHeader(
        query=ixia_thrift.Query(
            regex="^ipv6$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
        append_to_query=ixia_thrift.Query(
            regex="^ethernet$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
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
                    ),
                },
            ),
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="Destination Address"),
                attrs_json=json.dumps(
                    {
                        "ValueType": "valueList",
                    }
                ),
                references={
                    "ValueList": taac_thrift.Reference(
                        type=taac_thrift.ReferenceType.SRC_GATEWAY_IPV6_ADDRESS,
                        data_type=taac_thrift.DataType.LIST,
                    ),
                },
            ),
        ],
    ),
    taac_thrift.PacketHeader(
        query=ixia_thrift.Query(
            regex="tcp", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
        append_to_query=ixia_thrift.Query(
            regex="ipv6", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
        fields=[
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="TCP-Source-Port"),
                attrs_json=json.dumps(
                    {
                        "Auto": False,
                        "ValueType": "valueList",
                        "ValueList": [BGP_PORT],
                    }
                ),
            ),
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="TCP-Dest-Port"),
                attrs_json=json.dumps(
                    {
                        "Auto": False,
                        "SingleValue": BGP_PORT,
                    }
                ),
            ),
        ],
    ),
]


DHCP_V6_TRAFFIC_PACKET_HEADERS = [
    taac_thrift.PacketHeader(
        query=ixia_thrift.Query(
            regex="^ethernet$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
        fields=[
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="Destination MAC Address"),
                attrs_json=json.dumps(
                    {
                        "ValueType": "increment",
                        "StepValue": "00:00:00:00:00:00",
                        "CountValue": 1,
                    }
                ),
                references={
                    "StartValue": taac_thrift.Reference(
                        type=taac_thrift.ReferenceType.DST_MAC_ADDRESS
                    ),
                },
            ),
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="Source MAC Address"),
                attrs_json=json.dumps(
                    {
                        "ValueType": "increment",
                        "StartValue": DEFAULT_SRC_MAC_ADDRESS,
                        "StepValue": "00:00:00:00:00:00",
                        "CountValue": 1,
                    }
                ),
            ),
        ],
    ),
    taac_thrift.PacketHeader(
        query=ixia_thrift.Query(
            regex="^ipv6$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
        append_to_query=ixia_thrift.Query(
            regex="^ethernet$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
        fields=[
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="Source Address"),
                attrs_json=json.dumps(
                    {
                        "ValueType": "increment",
                        "StartValue": DHCPV6_MULTICAST_ADDR,
                        "StepValue": "::1",
                        "CountValue": 1,
                    }
                ),
            ),
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="Destination Address"),
                attrs_json=json.dumps(
                    {
                        "ValueType": "valueList",
                        "ValueList": [DHCPV6_SERVER_MULTICAST_ADDR],
                    }
                ),
            ),
        ],
    ),
    taac_thrift.PacketHeader(
        query=ixia_thrift.Query(
            regex="^udp$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
        append_to_query=ixia_thrift.Query(
            regex="ipv6", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
        fields=[
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="UDP-Source-Port"),
                attrs_json=json.dumps(
                    {
                        "Auto": False,
                        "ValueType": "valueList",
                        "ValueList": [DHCPV6_RELAY_PORT],
                    }
                ),
            ),
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="UDP-Dest-Port"),
                attrs_json=json.dumps(
                    {
                        "Auto": False,
                        "SingleValue": DHCPV6_SERVER_PORT,
                    }
                ),
            ),
        ],
    ),
]

DSF_MONITORING_PACKET_HEADERS = [
    taac_thrift.PacketHeader(
        query=ixia_thrift.Query(
            regex="^ipv6$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
        fields=[
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="Traffic Class"),
                attrs_json=json.dumps(
                    {
                        "SingleValue": 120,
                    }
                ),
            ),
        ],
    ),
    taac_thrift.PacketHeader(
        query=ixia_thrift.Query(
            regex="^udp$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
        append_to_query=ixia_thrift.Query(
            regex="ipv6", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
    ),
]


DSF_NC_PACKET_HEADERS = [
    taac_thrift.PacketHeader(
        query=ixia_thrift.Query(
            regex="^ipv6$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
        fields=[
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="Traffic Class"),
                attrs_json=json.dumps(
                    {
                        "SingleValue": 192,
                    }
                ),
            ),
        ],
    ),
    taac_thrift.PacketHeader(
        query=ixia_thrift.Query(
            regex="^udp$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
        append_to_query=ixia_thrift.Query(
            regex="ipv6", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
    ),
]

DEFAULT_IPV6_HEADER = [
    taac_thrift.PacketHeader(
        query=ixia_thrift.Query(
            regex="ipv6", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
    ),
]

DSF_BE_PACKET_HEADERS = [
    taac_thrift.PacketHeader(
        query=ixia_thrift.Query(
            regex="^udp$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
        append_to_query=ixia_thrift.Query(
            regex="ipv6", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
    ),
]

DSF_RDMA_PACKET_HEADERS = [
    taac_thrift.PacketHeader(
        query=ixia_thrift.Query(
            regex="^ethernet$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
        fields=[
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="PFC Queue"),
                attrs_json=json.dumps(
                    {
                        "SingleValue": 0,
                    }
                ),
            ),
        ],
    ),
    taac_thrift.PacketHeader(
        query=ixia_thrift.Query(
            regex="^ipv6$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
        fields=[
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="Traffic Class"),
                attrs_json=json.dumps(
                    {
                        "SingleValue": 224,
                    }
                ),
            ),
        ],
    ),
    taac_thrift.PacketHeader(
        query=ixia_thrift.Query(
            regex="^udp$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
        fields=[
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="UDP-Dest-Port"),
                attrs_json=json.dumps(
                    {
                        "Auto": False,
                        "SingleValue": RDMA_PORT,
                    }
                ),
            ),
        ],
        append_to_query=ixia_thrift.Query(
            regex="ipv6", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
    ),
]

HOP_LIMIT_1_IPV6_TRAFFIC_PACKET_HEADERS = [
    taac_thrift.PacketHeader(
        query=ixia_thrift.Query(
            regex="^ethernet$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
        fields=[
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="Destination MAC Address"),
                attrs_json=json.dumps(
                    {
                        "ValueType": "increment",
                        "StepValue": "00:00:00:00:00:00",
                        "CountValue": 1,
                    }
                ),
                references={
                    "StartValue": taac_thrift.Reference(
                        type=taac_thrift.ReferenceType.DST_MAC_ADDRESS
                    ),
                },
            ),
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="Source MAC Address"),
                attrs_json=json.dumps(
                    {
                        "ValueType": "increment",
                        "StartValue": DEFAULT_SRC_MAC_ADDRESS,
                        "StepValue": "00:00:00:00:00:00",
                        "CountValue": 1,
                    }
                ),
            ),
        ],
    ),
    taac_thrift.PacketHeader(
        query=ixia_thrift.Query(
            regex="^ipv6$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
        append_to_query=ixia_thrift.Query(
            regex="^ethernet$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
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
                    ),
                },
            ),
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="Destination Address"),
                attrs_json=json.dumps(
                    {
                        "ValueType": "valueList",
                    }
                ),
                references={
                    "ValueList": taac_thrift.Reference(
                        type=taac_thrift.ReferenceType.SRC_IPV6_ADDRESS,
                        data_type=taac_thrift.DataType.LIST,
                    ),
                },
            ),
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="Hop Limit"),
                attrs_json=json.dumps(
                    {
                        "SingleValue": "1",
                    }
                ),
            ),
        ],
    ),
]


HOP_LIMIT_0_IPV6_TRAFFIC_PACKET_HEADERS = [
    taac_thrift.PacketHeader(
        query=ixia_thrift.Query(
            regex="^ethernet$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
        fields=[
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="Destination MAC Address"),
                attrs_json=json.dumps(
                    {
                        "ValueType": "increment",
                        "StepValue": "00:00:00:00:00:00",
                        "CountValue": 1,
                    }
                ),
                references={
                    "StartValue": taac_thrift.Reference(
                        type=taac_thrift.ReferenceType.DST_MAC_ADDRESS
                    ),
                },
            ),
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="Source MAC Address"),
                attrs_json=json.dumps(
                    {
                        "ValueType": "increment",
                        "StartValue": DEFAULT_SRC_MAC_ADDRESS,
                        "StepValue": "00:00:00:00:00:00",
                        "CountValue": 1,
                    }
                ),
            ),
        ],
    ),
    taac_thrift.PacketHeader(
        query=ixia_thrift.Query(
            regex="^ipv6$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
        ),
        append_to_query=ixia_thrift.Query(
            regex="^ethernet$", query_type=ixia_thrift.QueryType.STACK_TYPE_ID
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
                    ),
                },
            ),
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="Destination Address"),
                attrs_json=json.dumps(
                    {
                        "ValueType": "valueList",
                    }
                ),
                references={
                    "ValueList": taac_thrift.Reference(
                        type=taac_thrift.ReferenceType.SRC_IPV6_ADDRESS,
                        data_type=taac_thrift.DataType.LIST,
                    ),
                },
            ),
            taac_thrift.Field(
                query=ixia_thrift.Query(regex="Hop Limit"),
                attrs_json=json.dumps(
                    {
                        "SingleValue": "0",
                    }
                ),
            ),
        ],
    ),
]
