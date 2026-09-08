# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import base64
import hashlib
import json
import re

from ixia.ixia import types as ixia_thrift
from taac.health_checks.healthcheck_definitions import (
    create_bgp_session_establish_check,
    create_bgp_session_snapshot_check,
    create_core_dumps_snapshot_check,
    create_cpu_queue_snapshot_check,
    create_device_core_dumps_check,
    create_fpf_ods_counter_check,
    create_ixia_packet_loss_check,
    create_ixia_traffic_rate_check,
    create_unclean_exit_check,
)
from taac.packet_headers import (
    BGP_CP_V6_GLOBAL_DSCP48_TRAFFIC_PACKET_HEADERS,
    DHCP_V6_LL_DSCP48_TRAFFIC_PACKET_HEADERS,
    LACP_SLOW_TIMER_TRAFFIC_PACKET_HEADERS,
    LLDP_TRAFFIC_PACKET_HEADERS,
    NDP_NS_MULTICAST_TRAFFIC_PACKET_HEADERS,
)
from taac.playbooks.playbook_definitions import (
    create_access_policy_playbook,
    create_hatch_chaos_soak_playbook,
    create_stable_state_validation_playbook,
)
from taac.stages.stage_definitions import (
    create_concurrent_steps_stage,
    create_longevity_stage,
    create_steps_stage,
)
from taac.steps.step_definitions import (
    create_drain_undrain_step,
    create_dummy_step,
    create_fpf_rapid_flap_step,
    create_interface_flap_step,
    create_longevity_step,
    create_regenerate_traffic_step,
    create_run_commands_on_shell_step,
    create_run_task_step,
    create_service_convergence_step,
    create_service_interruption_step,
    create_stop_traffic_step,
    create_system_reboot_step,
    create_validation_step,
    create_verify_port_operational_state_step,
    create_verify_port_speed_step_v2,
)
from taac.task_definitions import create_run_task
from taac.utils.test_config_utils import (
    create_raw_arp_request_traffic_item,
)
from taac.health_check.health_check import types as hc_thrift
from taac.test_as_a_config import types as taac_thrift


TEST_CONFIG_NAME = "QZD1_HATCH_STABLE_STATE"
PLAYBOOK_NAME = "test_stable_state_acl_traffic_matrix"
CHAOS_PLAYBOOK_NAME = "test_hatch_chaos_soak"

W400C_DUT = "rsw001.p006.f01.qzd1"
DUT = W400C_DUT
IXIA_CHASSIS_IP = "2401:db00:116:3006:21a:c5ff:fe01:6f54"
DUT_MAC = "76:d4:dd:40:0e:10"

W400_TEST_CONFIG_NAME = "QZD1_W400_HATCH_STABLE_STATE"
W400_PLAYBOOK_NAME = "test_w400_stable_state_acl_traffic_matrix"
W400_CHAOS_PLAYBOOK_NAME = "test_w400_hatch_chaos_soak"

W400_DUT = "rsw002.p005.f01.qzd1"
W400_DUT_MAC = "c2:18:50:b8:b8:c4"

FBOSS10_IPV6_BY_DUT: dict[str, str] = {
    DUT: "2401:db00:e501:f105::",
    W400_DUT: "2401:db00:e501:f104:1::",
}

# QZD1 (rsw001) port roles: A restricted, B blocked, C unconstrained.
PORT_A = "eth1/13/1"
PORT_B = "eth1/15/1"
PORT_C = "eth1/17/1"
SPEED_FLIP_PORT = "eth1/9/1"
UNRELATED_LINK_DRAIN_PORTS = ("eth1/1/1", "eth1/3/1")

SPEED_FLIP_PATCHER_NAME = "qzd1_hatch_access_policy_speed_200g"
SPEED_FLIP_200G_PROFILE = "PROFILE_200G_4_PAM4_RS544X2N_COPPER"

# W400 (rsw002) carries the same roles on different ports.
W400_PORT_A = "eth1/20/1"
W400_PORT_B = "eth1/25/1"
W400_PORT_C = "eth1/10/1"

# --------------------------------------------------------------------------
# Chaos-soak wiring (overnight warmboot x policy-transition overlap campaign)
# --------------------------------------------------------------------------
# The chaos ports are deliberately EMPTY CAGES (no transceiver, link down) on
# both DUTs.  Rationale:
#   * The 3 IXIA ports must keep a STATIC policy for the whole soak, otherwise
#     the expected traffic matrix moves under us and cumulative loss becomes
#     unreadable.  Flapping an IXIA port every 6s would destroy the very signal
#     the soak is measuring.
#   * The live BGP uplinks (fsw001/fsw002) must not be touched -- they are the
#     only healthy sessions on either box, and they are the BGP health signal.
#   * What this campaign actually stresses is the CONFIG path (policy render,
#     patcher application, agent state programming) racing an agent warmboot.
#     An admin disable/enable exercises all of that with or without a laser.
# Verified `Not Present` / down on BOTH rsw002.p005 and rsw001.p006, and all of
# eth1/1/1..eth1/48/1 are present in both agent configs, so setAccessPolicy
# accepts them.
ACCESS_POLICY_STATE_UNCONSTRAINED = 1  # "C"
ACCESS_POLICY_STATE_RESTRICTED = 2  # "R"
ACCESS_POLICY_STATE_BLOCKED = 3  # "B"

CHAOS_SOAK_SECONDS = 8 * 60 * 60
# Backstop must outlive the daemon's own --duration so a clean run exits 0 and
# only a WEDGED daemon trips the timeout path.  See _chaos_unit_file().
CHAOS_BACKSTOP_SECONDS = CHAOS_SOAK_SECONDS + 30 * 60
CHAOS_WARMBOOT_INTERVAL_SECONDS = 150  # 2.5 min
CHAOS_FLAP_INTERVAL_SECONDS = 6

CHAOS_REMOTE_DIR = "/var/lib/hatch_chaos"
CHAOS_UNIT_NAME = "hatch-chaos.service"
CHAOS_UNIT_PATH = f"/etc/systemd/system/{CHAOS_UNIT_NAME}"
CHAOS_DAEMON_PATH = f"{CHAOS_REMOTE_DIR}/chaosd.py"
CHAOS_RESTORE_PATH = f"{CHAOS_REMOTE_DIR}/restore.sh"
CHAOS_EVENT_LOG = f"{CHAOS_REMOTE_DIR}/events.jsonl"


class ChaosPorts:
    """The 4 extra (non-IXIA) ports driven by the chaos daemon on one device.

    Exactly 4 ports: 2 start Restricted, 2 start Unconstrained.  The SAME 4
    ports are both admin-flapped every CHAOS_FLAP_INTERVAL_SECONDS and cycled
    through the R/C transition matrix -- there is no separate cycle pool.
    """

    def __init__(self, restricted, unconstrained):
        self.restricted = list(restricted)
        self.unconstrained = list(unconstrained)

    @property
    def all_ports(self):
        return self.restricted + self.unconstrained


# Kept per-device on purpose: W400C's eth1/17/1 is IXIA Port C while on W400 it
# is an empty cage, so the two boxes do not share a safe pool even though these
# particular numbers happen to be free on both.
W400_CHAOS_PORTS = ChaosPorts(
    restricted=("eth1/30/1", "eth1/31/1"),
    unconstrained=("eth1/32/1", "eth1/33/1"),
)

W400C_CHAOS_PORTS = ChaosPorts(
    restricted=("eth1/30/1", "eth1/31/1"),
    unconstrained=("eth1/32/1", "eth1/33/1"),
)

# fsw004 on both pods is chronically unstable (restart loop; links flap on their
# own).  Its peers must not be allowed to fail the BGP snapshot check.
BGP_PEER_PREFIXES_TO_IGNORE = ["2401:db00:e50e:1104::", "2401:db00:e50e:1004::"]


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
        ("RAW_TCP_SYN_U_TO_R_EXPECT_ALLOW", port_c, port_a, 40012),
        ("RAW_TCP_SYN_U_TO_B_EXPECT_BLOCK", port_c, port_b, 40013),
    ]


def _udp_traffic_items(port_a, port_b, port_c):
    return [
        ("UDP443_R_TO_U_EXPECT_BLOCK", port_a, port_c, 443, 40014),
        ("UDP443_B_TO_U_EXPECT_BLOCK", port_b, port_c, 443, 40015),
        ("UDP443_U_TO_B_EXPECT_BLOCK", port_c, port_b, 443, 40016),
        ("UDP443_U_TO_R_EXPECT_ALLOW", port_c, port_a, 443, 40017),
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
        ("RAW_BGP_R", port_a, port_b, bgp_syn_headers, False),
        ("RAW_BGP_B", port_b, port_c, bgp_syn_headers, False),
        ("RAW_BGP_U", port_c, port_a, bgp_syn_headers, False),
        (
            "RAW_DHCPV6_R",
            port_a,
            port_b,
            DHCP_V6_LL_DSCP48_TRAFFIC_PACKET_HEADERS,
            False,
        ),
        (
            "RAW_DHCPV6_B",
            port_b,
            port_c,
            DHCP_V6_LL_DSCP48_TRAFFIC_PACKET_HEADERS,
            False,
        ),
        (
            "RAW_DHCPV6_U",
            port_c,
            port_a,
            DHCP_V6_LL_DSCP48_TRAFFIC_PACKET_HEADERS,
            False,
        ),
        (
            "RAW_NDP_R",
            port_a,
            port_b,
            NDP_NS_MULTICAST_TRAFFIC_PACKET_HEADERS,
            False,
        ),
        (
            "RAW_NDP_B",
            port_b,
            port_c,
            NDP_NS_MULTICAST_TRAFFIC_PACKET_HEADERS,
            False,
        ),
        (
            "RAW_NDP_U",
            port_c,
            port_a,
            NDP_NS_MULTICAST_TRAFFIC_PACKET_HEADERS,
            False,
        ),
        ("RAW_LLDP_R", port_a, port_b, LLDP_TRAFFIC_PACKET_HEADERS, False),
        ("RAW_LLDP_B", port_b, port_c, LLDP_TRAFFIC_PACKET_HEADERS, False),
        ("RAW_LLDP_U", port_c, port_a, LLDP_TRAFFIC_PACKET_HEADERS, False),
        ("RAW_LACP_R", port_a, port_b, LACP_SLOW_TIMER_TRAFFIC_PACKET_HEADERS, True),
        ("RAW_LACP_B", port_b, port_c, LACP_SLOW_TIMER_TRAFFIC_PACKET_HEADERS, True),
        ("RAW_LACP_U", port_c, port_a, LACP_SLOW_TIMER_TRAFFIC_PACKET_HEADERS, True),
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
    "UDP443_U_TO_R_EXPECT_ALLOW",
    "RAW_TCP_SYN_U_TO_R_EXPECT_ALLOW",
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

BLOCKED_UDP_TRAFFIC_ITEMS = [
    "UDP443_R_TO_U_EXPECT_BLOCK",
    "UDP443_B_TO_U_EXPECT_BLOCK",
    "UDP443_U_TO_B_EXPECT_BLOCK",
]

BLOCKED_TRAFFIC_ITEMS = (
    BLOCKED_TCP_TRAFFIC_ITEMS
    + BLOCKED_UDP_TRAFFIC_ITEMS
    + [
        "RAW_TCP_SYN_R_TO_B_EXPECT_BLOCK",
        "RAW_TCP_SYN_R_TO_U_EXPECT_BLOCK",
        "RAW_TCP_SYN_B_TO_U_EXPECT_BLOCK",
        "RAW_TCP_SYN_U_TO_B_EXPECT_BLOCK",
    ]
)

# The chaos soak deliberately holds Port B UNCONSTRAINED, not Blocked, so its
# streams keep transmitting for the whole 8h (a Blocked port is admin-disabled,
# which drops its IXIA streams to tx=0 and they do NOT auto-resume when it comes
# back -- `start` reports "already running" while sending nothing, which reads
# as a false 0% loss).
#
# That makes the static expectation a 5/12 split rather than the stable-state
# 3/14: only the five R-ingress flows are denied, because Restricted permits
# TCP/443 but denies TCP-SYN, TCP/22 and UDP.  Everything else forwards.
# Reusing BLOCKED_TRAFFIC_ITEMS here fails PRE_TEST immediately, since every
# B-sourced item flows at line rate while B is Unconstrained.
CHAOS_BLOCKED_TRAFFIC_ITEMS = [
    "TCP22_R_TO_B_EXPECT_BLOCK",
    "TCP22_R_TO_U_EXPECT_BLOCK",
    "UDP443_R_TO_U_EXPECT_BLOCK",
    "RAW_TCP_SYN_R_TO_B_EXPECT_BLOCK",
    "RAW_TCP_SYN_R_TO_U_EXPECT_BLOCK",
]

CHAOS_ALLOWED_TRAFFIC_ITEMS = [
    "TCP22_U_TO_R_EXPECT_ALLOW",
    "TCP22_U_TO_B_EXPECT_BLOCK",
    "TCP443_R_TO_B_EXPECT_ALLOW",
    "TCP443_R_TO_U_EXPECT_ALLOW",
    "TCP443_B_TO_R_EXPECT_BLOCK",
    "TCP443_B_TO_U_EXPECT_BLOCK",
    "UDP443_B_TO_U_EXPECT_BLOCK",
    "UDP443_U_TO_B_EXPECT_BLOCK",
    "UDP443_U_TO_R_EXPECT_BLOCK",
    "RAW_TCP_SYN_B_TO_U_EXPECT_BLOCK",
    "RAW_TCP_SYN_U_TO_R_EXPECT_BLOCK",
    "RAW_TCP_SYN_U_TO_B_EXPECT_BLOCK",
]

R_U_DATA_PLANE_TRAFFIC_ITEMS = [
    "TCP22_U_TO_R_EXPECT_ALLOW",
    "TCP22_R_TO_U_EXPECT_BLOCK",
    "TCP443_R_TO_U_EXPECT_ALLOW",
    "UDP443_R_TO_U_EXPECT_BLOCK",
    "UDP443_U_TO_R_EXPECT_ALLOW",
    "RAW_TCP_SYN_R_TO_U_EXPECT_BLOCK",
    "RAW_TCP_SYN_U_TO_R_EXPECT_ALLOW",
]
RESTRICTED_R_U_LOSSLESS_TRAFFIC_ITEMS = [
    # Access policy is enforced on ingress. U-to-R traffic enters the
    # Unconstrained port, while TCP/443 is explicitly allowed from R-to-U.
    "TCP22_U_TO_R_EXPECT_ALLOW",
    "TCP443_R_TO_U_EXPECT_ALLOW",
    "UDP443_U_TO_R_EXPECT_ALLOW",
    "RAW_TCP_SYN_U_TO_R_EXPECT_ALLOW",
]
RESTRICTED_R_U_BLOCKED_TRAFFIC_ITEMS = [
    "TCP22_R_TO_U_EXPECT_BLOCK",
    "UDP443_R_TO_U_EXPECT_BLOCK",
    "RAW_TCP_SYN_R_TO_U_EXPECT_BLOCK",
]
SPLIT_AGENT_CRITICAL_SERVICES = [
    "fboss_sw_agent",
    "fboss_hw_agent@0",
    "bgpd",
    "fsdb",
    "qsfp_service",
    "openr",
]
MONOLITHIC_AGENT_CRITICAL_SERVICES = [
    "wedge_agent",
    "bgpd",
    "fsdb",
    "qsfp_service",
    "openr",
]


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


def _raw_tcp_syn_headers(
    destination_port,
    source_port,
    dut_mac=DUT_MAC,
    destination_ipv6=None,
):
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
                    attrs_json=json.dumps(
                        {
                            "ValueType": "singleValue",
                            "SingleValue": destination_ipv6,
                        }
                        if destination_ipv6 is not None
                        else {"ValueType": "valueList"}
                    ),
                    references=(
                        {}
                        if destination_ipv6 is not None
                        else {
                            "ValueList": taac_thrift.Reference(
                                type=taac_thrift.ReferenceType.DST_IPV6_ADDRESS,
                                data_type=taac_thrift.DataType.LIST,
                            )
                        }
                    ),
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


def _raw_udp_headers(
    destination_port,
    source_port,
    dut_mac=DUT_MAC,
    destination_ipv6=None,
):
    return [
        *_raw_tcp_syn_headers(
            destination_port=destination_port,
            source_port=source_port,
            dut_mac=dut_mac,
            destination_ipv6=destination_ipv6,
        )[:-1],
        taac_thrift.PacketHeader(
            query=ixia_thrift.Query(
                regex="udp",
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


def _raw_cpu_traffic_item(
    name,
    source_port,
    destination_port,
    packet_headers,
    allow_self_destined,
    dut=DUT,
):
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
        allow_self_destined=allow_self_destined,
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


def _stable_check_id(prefix, values):
    normalized = [
        re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") for value in sorted(values)
    ]
    suffix = f"_plus_{len(normalized) - 2}" if len(normalized) > 2 else ""
    summary_limit = 48 - len(suffix)
    summary = "_".join(normalized[:2])[:summary_limit] + suffix
    digest = hashlib.sha256("\0".join(sorted(values)).encode()).hexdigest()[:6]
    return f"{prefix}_{summary[:48]}_{digest}"


def _unclean_exit_check(dut=W400C_DUT, exclude_services=None):
    excluded = set(exclude_services or [])
    critical_services = (
        SPLIT_AGENT_CRITICAL_SERVICES
        if dut == W400C_DUT
        else MONOLITHIC_AGENT_CRITICAL_SERVICES
    )
    services = [service for service in critical_services if service not in excluded]
    return create_unclean_exit_check(
        # Exclusions are scenario-specific. Keep the check identity stable for
        # the device's critical-service set so snapshots remain comparable.
        check_id=_stable_check_id("access_policy_unclean_exit", critical_services),
        services=services,
        sleep_timer=0,
    )


def _traffic_loss_check(allowed=None, blocked=None):
    thresholds = []
    allowed_names = allowed if allowed is not None else ALLOWED_TRAFFIC_ITEMS
    blocked_names = blocked if blocked is not None else BLOCKED_TRAFFIC_ITEMS
    if allowed_names:
        thresholds.append(
            hc_thrift.PacketLossThreshold(
                names=allowed_names,
                str_value="0",
                metric=hc_thrift.PacketLossMetric.PERCENTAGE,
                comparison=hc_thrift.ComparisonType.EQUAL_TO,
            )
        )
    if blocked_names:
        thresholds.append(
            hc_thrift.PacketLossThreshold(
                names=blocked_names,
                str_value="100",
                metric=hc_thrift.PacketLossMetric.PERCENTAGE,
                comparison=hc_thrift.ComparisonType.EQUAL_TO,
            )
        )
    if not thresholds:
        raise ValueError("At least one allowed or blocked traffic item is required")
    return create_ixia_packet_loss_check(
        check_id=_stable_check_id(
            "acl_traffic_loss_percentage",
            [f"allow:{name}" for name in allowed_names]
            + [f"block:{name}" for name in blocked_names],
        ),
        clear_traffic_stats=True,
        sleep_time=15,
        thresholds=thresholds,
    )


def _set_access_policy_step(dut, policies, description, *, start_traffic=True):
    return create_run_task_step(
        task_name="coop_set_access_policy",
        params_dict={"hostname": dut, "policies": policies},
        description=description,
        start_traffic=start_traffic,
    )


def _access_policy_hardware_check_step(
    dut, expectations, description, *, start_traffic=True
):
    return create_run_task_step(
        task_name="validate_access_policy_hardware",
        params_dict={
            "hostname": dut,
            "expectations": expectations,
            # W400C programs access policy through the SAI PORT ingress-ACL
            # bind point.  Passing it explicitly also lets an all-Unconstrained
            # state be validated, where no programmed port remains from which
            # the validator could infer the mechanism.
            "mechanism": "port-bindpoint",
        },
        description=description,
        start_traffic=start_traffic,
    )


def _bgp_established_check(
    restarted=False, expected_sessions=4, max_session_uptime_sec=600
):
    return create_bgp_session_establish_check(
        expected_established_sessions=expected_sessions,
        max_session_uptime_sec=max_session_uptime_sec if restarted else None,
        retry_count=12,
        retry_delay_seconds=10,
        retry_delay_multiplier=1,
    )


def _common_postchecks(
    *,
    traffic_check,
    dut=W400C_DUT,
    restarted=False,
    expected_bgp_sessions=4,
    max_session_uptime_sec=600,
):
    return [
        traffic_check,
        _bgp_established_check(
            restarted=restarted,
            expected_sessions=expected_bgp_sessions,
            max_session_uptime_sec=max_session_uptime_sec,
        ),
        _unclean_exit_check(dut),
        create_device_core_dumps_check(),
    ]


def _snapshot_checks(dut, restarted=False):
    bgp_check = (
        create_bgp_session_snapshot_check(
            skip_flap_check=True,
            skip_uptime_check=True,
            assert_reconvergence=True,
            max_convergence_sec=120,
            convergence_service=(
                "fboss_sw_agent" if dut == W400C_DUT else "wedge_agent"
            ),
            reconvergence_hosts=[dut],
        )
        if restarted
        else create_bgp_session_snapshot_check()
    )
    return [bgp_check, create_core_dumps_snapshot_check()]


def _policy_cleanup_steps(dut, port_a, port_b, port_c):
    return [
        _set_access_policy_step(
            dut,
            {
                port_a: "UNCONSTRAINED",
                port_b: "UNCONSTRAINED",
                port_c: "UNCONSTRAINED",
            },
            "Restore all IXIA-facing ports to Unconstrained",
            start_traffic=False,
        )
    ]


def _transition_playbooks(dut, port_a, port_b, port_c):
    all_unconstrained = {
        port_a: "UNCONSTRAINED",
        port_b: "UNCONSTRAINED",
        port_c: "UNCONSTRAINED",
    }
    restricted = {port_a: "RESTRICTED"}
    restricted_with_blocked = {
        port_a: "RESTRICTED",
        port_b: "BLOCKED",
    }
    cleanup_steps = _policy_cleanup_steps(dut, port_a, port_b, port_c)
    restricted_traffic = _traffic_loss_check(
        RESTRICTED_R_U_LOSSLESS_TRAFFIC_ITEMS,
        RESTRICTED_R_U_BLOCKED_TRAFFIC_ITEMS,
    )
    # Names containing EXPECT_BLOCK describe their Restricted-mode behavior.
    # Once R is Unconstrained, every selected R-U flow must be lossless.
    unconstrained_traffic = _traffic_loss_check(R_U_DATA_PLANE_TRAFFIC_ITEMS, [])

    def policy_step(policy, description, *, start_traffic=True):
        return _set_access_policy_step(
            dut,
            policy,
            description,
            start_traffic=start_traffic,
        )

    def hardware_step(mode):
        return _access_policy_hardware_check_step(
            dut,
            {port_a: mode},
            f"Validate {mode} Agent and hardware state on {port_a}",
        )

    def blocked_port_step():
        return create_verify_port_operational_state_step(
            interfaces=[port_b],
            operational_state=False,
            description=f"Validate Blocked port {port_b} is operationally down",
            device_regexes=[dut],
        )

    def reset_and_restart_traffic_steps():
        return [
            create_regenerate_traffic_step(),
            create_longevity_step(
                duration=30,
                description="Establish a fresh IXIA measurement window",
            ),
        ]

    return [
        create_access_policy_playbook(
            name="test_access_policy_unconstrained_to_restricted",
            description="Transition R from Unconstrained to Restricted and validate forwarding and control-plane stability.",
            device_regexes=[dut],
            traffic_items_to_start=R_U_DATA_PLANE_TRAFFIC_ITEMS,
            prechecks=[_bgp_established_check()],
            postchecks=_common_postchecks(traffic_check=restricted_traffic),
            snapshot_checks=_snapshot_checks(dut),
            cleanup_steps=cleanup_steps,
            stages=[
                create_steps_stage(
                    steps=[
                        policy_step(
                            all_unconstrained, "Prepare all IXIA ports as Unconstrained"
                        ),
                        policy_step(
                            restricted, "Transition R from Unconstrained to Restricted"
                        ),
                        create_longevity_step(
                            duration=120,
                            description="Hold Restricted state for convergence",
                        ),
                        hardware_step("restricted"),
                    ]
                )
            ],
        ),
        create_access_policy_playbook(
            name="test_access_policy_restricted_to_unconstrained",
            description="Validate Restricted traffic mid-test, transition R to Unconstrained, and validate all R-U traffic lossless.",
            device_regexes=[dut],
            traffic_items_to_start=R_U_DATA_PLANE_TRAFFIC_ITEMS,
            prechecks=[_bgp_established_check()],
            postchecks=_common_postchecks(traffic_check=unconstrained_traffic),
            snapshot_checks=_snapshot_checks(dut),
            cleanup_steps=cleanup_steps,
            stages=[
                create_steps_stage(
                    steps=[
                        policy_step(
                            all_unconstrained, "Prepare all IXIA ports as Unconstrained"
                        ),
                        policy_step(restricted, "Prepare R as Restricted"),
                        create_longevity_step(
                            duration=30,
                            description="Establish Restricted traffic baseline",
                        ),
                        create_validation_step(
                            point_in_time_checks=[restricted_traffic],
                            description="Validate Restricted R-U traffic before transition",
                        ),
                        hardware_step("restricted"),
                        policy_step(
                            {port_a: "UNCONSTRAINED"}, "Transition R to Unconstrained"
                        ),
                        create_longevity_step(
                            duration=120,
                            description="Hold for policy convergence before final traffic validation",
                        ),
                        hardware_step("unconstrained"),
                    ]
                )
            ],
        ),
        create_access_policy_playbook(
            name="test_access_policy_unconstrained_restricted_blocked_restricted",
            description=(
                "Transition port R from Unconstrained to Restricted to Blocked, "
                "verify that Blocked disables the port, then return it to "
                "Restricted and validate the normal R-U stable state."
            ),
            device_regexes=[dut],
            traffic_items_to_start=R_U_DATA_PLANE_TRAFFIC_ITEMS,
            prechecks=[_bgp_established_check()],
            postchecks=_common_postchecks(traffic_check=restricted_traffic),
            snapshot_checks=_snapshot_checks(dut),
            cleanup_steps=cleanup_steps,
            stages=[
                create_steps_stage(
                    steps=[
                        policy_step(
                            all_unconstrained,
                            "Prepare all IXIA ports as Unconstrained",
                        ),
                        policy_step(
                            restricted,
                            "Transition R from Unconstrained to Restricted",
                        ),
                        create_stop_traffic_step(),
                        policy_step(
                            {port_a: "BLOCKED"},
                            "Transition R from Restricted to Blocked",
                            start_traffic=False,
                        ),
                        create_verify_port_operational_state_step(
                            interfaces=[port_a],
                            operational_state=False,
                            description=(
                                f"Mid-test: validate Blocked port {port_a} is "
                                "operationally down"
                            ),
                            device_regexes=[dut],
                        ),
                        create_validation_step(
                            point_in_time_checks=[_bgp_established_check()],
                            description=(
                                "Mid-test: validate BGP remains stable while R is "
                                "Blocked"
                            ),
                            start_traffic=False,
                        ),
                        create_stop_traffic_step(),
                        policy_step(
                            {port_a: "RESTRICTED"},
                            "Transition R from Blocked back to Restricted",
                            start_traffic=False,
                        ),
                        create_longevity_step(
                            duration=120,
                            description=(
                                "Wait two minutes for Restricted policy and port "
                                "convergence"
                            ),
                            start_traffic=False,
                        ),
                        *reset_and_restart_traffic_steps(),
                        hardware_step("restricted"),
                    ]
                )
            ],
        ),
        create_access_policy_playbook(
            name="test_access_policy_unconstrained_blocked_unconstrained",
            description=(
                "Transition port R from Unconstrained to Blocked, verify that "
                "the port is disabled, then return it to Unconstrained and "
                "validate every selected R-U flow at zero-percent loss."
            ),
            device_regexes=[dut],
            traffic_items_to_start=R_U_DATA_PLANE_TRAFFIC_ITEMS,
            prechecks=[_bgp_established_check()],
            postchecks=_common_postchecks(traffic_check=unconstrained_traffic),
            snapshot_checks=_snapshot_checks(dut),
            cleanup_steps=cleanup_steps,
            stages=[
                create_steps_stage(
                    steps=[
                        policy_step(
                            all_unconstrained,
                            "Prepare all IXIA ports as Unconstrained",
                        ),
                        create_stop_traffic_step(),
                        policy_step(
                            {port_a: "BLOCKED"},
                            "Transition R from Unconstrained to Blocked",
                            start_traffic=False,
                        ),
                        create_verify_port_operational_state_step(
                            interfaces=[port_a],
                            operational_state=False,
                            description=(
                                f"Mid-test: validate Blocked port {port_a} is "
                                "operationally down"
                            ),
                            device_regexes=[dut],
                        ),
                        create_validation_step(
                            point_in_time_checks=[_bgp_established_check()],
                            description=(
                                "Mid-test: validate BGP remains stable while R is "
                                "Blocked"
                            ),
                            start_traffic=False,
                        ),
                        create_stop_traffic_step(),
                        policy_step(
                            {port_a: "UNCONSTRAINED"},
                            "Transition R from Blocked back to Unconstrained",
                            start_traffic=False,
                        ),
                        create_longevity_step(
                            duration=120,
                            description=(
                                "Wait two minutes for Unconstrained policy and port "
                                "convergence"
                            ),
                            start_traffic=False,
                        ),
                        *reset_and_restart_traffic_steps(),
                        hardware_step("unconstrained"),
                    ]
                )
            ],
        ),
        create_access_policy_playbook(
            name="test_access_policy_unconstrained_to_restricted_agent_warmboot",
            description="Transition R to Restricted, warmboot Agent, and validate policy stickiness.",
            device_regexes=[dut],
            traffic_items_to_start=R_U_DATA_PLANE_TRAFFIC_ITEMS,
            prechecks=[_bgp_established_check()],
            postchecks=_common_postchecks(
                traffic_check=restricted_traffic, restarted=True
            ),
            snapshot_checks=_snapshot_checks(dut, restarted=True),
            cleanup_steps=cleanup_steps,
            stages=[
                create_steps_stage(
                    steps=[
                        policy_step(
                            all_unconstrained, "Prepare all IXIA ports as Unconstrained"
                        ),
                        policy_step(
                            restricted_with_blocked,
                            "Transition R to Restricted and B to Blocked",
                        ),
                        create_service_interruption_step(
                            service=taac_thrift.Service.AGENT, device_regexes=[dut]
                        ),
                        create_service_convergence_step(
                            services=[
                                taac_thrift.Service.AGENT,
                                taac_thrift.Service.BGP,
                            ],
                            timeout=300,
                            device_regexes=[dut],
                        ),
                        create_longevity_step(
                            duration=120, description="Hold after Agent warmboot"
                        ),
                        hardware_step("restricted"),
                        blocked_port_step(),
                    ]
                )
            ],
        ),
        create_access_policy_playbook(
            name="test_access_policy_unconstrained_to_restricted_blocked_agent_coldboot",
            description=(
                "Transition R to Restricted and B to Blocked, coldboot Agent, "
                "then validate policy and stable-state recovery."
            ),
            device_regexes=[dut],
            traffic_items_to_start=R_U_DATA_PLANE_TRAFFIC_ITEMS,
            prechecks=[_bgp_established_check()],
            postchecks=_common_postchecks(
                traffic_check=restricted_traffic,
                restarted=True,
                max_session_uptime_sec=600,
            ),
            # Coldboot intentionally restarts the routing stack. Validate BGP
            # recovery explicitly in postchecks and independently compare cores.
            snapshot_checks=[create_core_dumps_snapshot_check()],
            cleanup_steps=cleanup_steps,
            stages=[
                create_steps_stage(
                    steps=[
                        policy_step(
                            all_unconstrained,
                            "Prepare all IXIA ports as Unconstrained",
                        ),
                        policy_step(
                            restricted_with_blocked,
                            "Transition R to Restricted and B to Blocked",
                        ),
                        create_longevity_step(
                            duration=30,
                            description="Establish the Restricted traffic baseline",
                        ),
                        create_validation_step(
                            point_in_time_checks=[restricted_traffic],
                            description=(
                                "Validate Restricted R-U traffic before Agent coldboot"
                            ),
                        ),
                        hardware_step("restricted"),
                        blocked_port_step(),
                        create_service_interruption_step(
                            service=taac_thrift.Service.AGENT,
                            trigger=taac_thrift.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                            create_cold_boot_file=True,
                            device_regexes=[dut],
                            description="Coldboot Agent with the one-shot cold-boot marker",
                        ),
                        create_service_convergence_step(
                            services=[
                                taac_thrift.Service.AGENT,
                                taac_thrift.Service.BGP,
                            ],
                            timeout=600,
                            device_regexes=[dut],
                            description="Wait for Agent and BGP after coldboot",
                        ),
                        create_stop_traffic_step(),
                        create_regenerate_traffic_step(),
                        create_longevity_step(
                            duration=120,
                            description=(
                                "Measure the recovered Restricted stable state for "
                                "two minutes"
                            ),
                        ),
                        hardware_step("restricted"),
                        blocked_port_step(),
                    ]
                )
            ],
        ),
        create_access_policy_playbook(
            name="test_access_policy_unconstrained_to_restricted_blocked_device_reboot",
            description=(
                "Transition R to Restricted and B to Blocked, reboot the device, "
                "then validate policy and stable-state recovery."
            ),
            device_regexes=[dut],
            traffic_items_to_start=R_U_DATA_PLANE_TRAFFIC_ITEMS,
            prechecks=[_bgp_established_check()],
            postchecks=_common_postchecks(
                traffic_check=restricted_traffic,
                restarted=True,
                max_session_uptime_sec=600,
            ),
            # A full reboot intentionally restarts BGP. Validate its recovered
            # count and uptime explicitly, while independently comparing cores.
            snapshot_checks=[create_core_dumps_snapshot_check()],
            cleanup_steps=cleanup_steps,
            stages=[
                create_steps_stage(
                    steps=[
                        policy_step(
                            all_unconstrained,
                            "Prepare all IXIA ports as Unconstrained",
                        ),
                        policy_step(
                            restricted_with_blocked,
                            "Transition R to Restricted and B to Blocked",
                        ),
                        create_longevity_step(
                            duration=30,
                            description="Establish the Restricted traffic baseline",
                        ),
                        create_validation_step(
                            point_in_time_checks=[restricted_traffic],
                            description=(
                                "Validate Restricted R-U traffic before device reboot"
                            ),
                        ),
                        hardware_step("restricted"),
                        blocked_port_step(),
                        create_system_reboot_step(
                            trigger=taac_thrift.SystemRebootTrigger.FULL_SYSTEM_REBOOT,
                            description="Perform a full device reboot",
                        ),
                        create_service_convergence_step(
                            services=[
                                taac_thrift.Service.AGENT,
                                taac_thrift.Service.BGP,
                            ],
                            timeout=900,
                            device_regexes=[dut],
                            description="Wait for Agent and BGP after device reboot",
                        ),
                        create_stop_traffic_step(),
                        create_regenerate_traffic_step(),
                        create_longevity_step(
                            duration=120,
                            description=(
                                "Measure the recovered Restricted stable state for "
                                "two minutes"
                            ),
                        ),
                        hardware_step("restricted"),
                        blocked_port_step(),
                    ]
                )
            ],
        ),
        create_access_policy_playbook(
            name="test_access_policy_restricted_to_unconstrained_agent_warmboot",
            description="Transition R to Unconstrained, warmboot Agent, and validate policy removal stickiness.",
            device_regexes=[dut],
            traffic_items_to_start=R_U_DATA_PLANE_TRAFFIC_ITEMS,
            prechecks=[_bgp_established_check()],
            postchecks=_common_postchecks(
                traffic_check=unconstrained_traffic, restarted=True
            ),
            snapshot_checks=_snapshot_checks(dut, restarted=True),
            cleanup_steps=cleanup_steps,
            stages=[
                create_steps_stage(
                    steps=[
                        policy_step(
                            all_unconstrained, "Prepare all IXIA ports as Unconstrained"
                        ),
                        policy_step(
                            restricted_with_blocked,
                            "Prepare R as Restricted and B as Blocked",
                        ),
                        create_longevity_step(
                            duration=30,
                            description="Establish Restricted traffic baseline",
                        ),
                        create_validation_step(
                            point_in_time_checks=[restricted_traffic],
                            description="Validate Restricted R-U traffic before transition",
                        ),
                        hardware_step("restricted"),
                        policy_step(
                            {port_a: "UNCONSTRAINED"}, "Transition R to Unconstrained"
                        ),
                        create_service_interruption_step(
                            service=taac_thrift.Service.AGENT, device_regexes=[dut]
                        ),
                        create_service_convergence_step(
                            services=[
                                taac_thrift.Service.AGENT,
                                taac_thrift.Service.BGP,
                            ],
                            timeout=300,
                            device_regexes=[dut],
                        ),
                        create_longevity_step(
                            duration=120, description="Hold after Agent warmboot"
                        ),
                        hardware_step("unconstrained"),
                        blocked_port_step(),
                    ]
                )
            ],
        ),
        create_access_policy_playbook(
            name="test_access_policy_agent_warmboot_then_restricted_to_unconstrained",
            description=(
                "Warmboot Agent while R is Restricted, validate recovery, then "
                "transition R to Unconstrained and validate policy removal."
            ),
            device_regexes=[dut],
            traffic_items_to_start=R_U_DATA_PLANE_TRAFFIC_ITEMS,
            prechecks=[_bgp_established_check()],
            postchecks=_common_postchecks(
                traffic_check=unconstrained_traffic, restarted=True
            ),
            snapshot_checks=_snapshot_checks(dut, restarted=True),
            cleanup_steps=cleanup_steps,
            stages=[
                create_steps_stage(
                    steps=[
                        policy_step(
                            all_unconstrained,
                            "Prepare all IXIA ports as Unconstrained",
                        ),
                        policy_step(
                            restricted_with_blocked,
                            "Prepare R as Restricted and B as Blocked",
                        ),
                        create_longevity_step(
                            duration=30,
                            description="Establish Restricted traffic baseline",
                        ),
                        create_validation_step(
                            point_in_time_checks=[restricted_traffic],
                            description="Validate Restricted R-U traffic before warmboot",
                        ),
                        hardware_step("restricted"),
                        create_service_interruption_step(
                            service=taac_thrift.Service.AGENT,
                            device_regexes=[dut],
                        ),
                        create_service_convergence_step(
                            services=[
                                taac_thrift.Service.AGENT,
                                taac_thrift.Service.BGP,
                            ],
                            timeout=300,
                            device_regexes=[dut],
                        ),
                        create_longevity_step(
                            duration=120,
                            description="Hold Restricted state after Agent warmboot",
                        ),
                        create_validation_step(
                            point_in_time_checks=[restricted_traffic],
                            description="Validate Restricted traffic after Agent warmboot",
                        ),
                        hardware_step("restricted"),
                        policy_step(
                            {port_a: "UNCONSTRAINED"},
                            "Transition R from Restricted to Unconstrained",
                        ),
                        create_longevity_step(
                            duration=120,
                            description="Hold Unconstrained state for convergence",
                        ),
                        hardware_step("unconstrained"),
                        blocked_port_step(),
                    ]
                )
            ],
        ),
        create_access_policy_playbook(
            name="test_access_policy_agent_warmboot_then_unconstrained_to_restricted",
            description=(
                "Warmboot Agent while R is Unconstrained, validate recovery, then "
                "transition R to Restricted and validate policy programming."
            ),
            device_regexes=[dut],
            traffic_items_to_start=R_U_DATA_PLANE_TRAFFIC_ITEMS,
            prechecks=[_bgp_established_check()],
            postchecks=_common_postchecks(
                traffic_check=restricted_traffic, restarted=True
            ),
            snapshot_checks=_snapshot_checks(dut, restarted=True),
            cleanup_steps=cleanup_steps,
            stages=[
                create_steps_stage(
                    steps=[
                        policy_step(
                            all_unconstrained,
                            "Prepare all IXIA ports as Unconstrained",
                        ),
                        create_longevity_step(
                            duration=30,
                            description="Establish Unconstrained traffic baseline",
                        ),
                        create_validation_step(
                            point_in_time_checks=[unconstrained_traffic],
                            description=(
                                "Validate Unconstrained R-U traffic before warmboot"
                            ),
                        ),
                        hardware_step("unconstrained"),
                        create_service_interruption_step(
                            service=taac_thrift.Service.AGENT,
                            device_regexes=[dut],
                        ),
                        create_service_convergence_step(
                            services=[
                                taac_thrift.Service.AGENT,
                                taac_thrift.Service.BGP,
                            ],
                            timeout=300,
                            device_regexes=[dut],
                        ),
                        create_longevity_step(
                            duration=120,
                            description="Hold Unconstrained state after Agent warmboot",
                        ),
                        create_validation_step(
                            point_in_time_checks=[unconstrained_traffic],
                            description=(
                                "Validate Unconstrained traffic after Agent warmboot"
                            ),
                        ),
                        hardware_step("unconstrained"),
                        policy_step(
                            restricted_with_blocked,
                            "Transition R to Restricted and B to Blocked",
                        ),
                        create_longevity_step(
                            duration=120,
                            description="Hold Restricted state for convergence",
                        ),
                        hardware_step("restricted"),
                        blocked_port_step(),
                    ]
                )
            ],
        ),
        create_access_policy_playbook(
            name="test_access_policy_restricted_blocked_repeated_agent_crash_10m",
            description=(
                "Keep R Restricted and B Blocked while crashing Agent every 30 "
                "seconds for ten minutes, then validate full stable-state recovery."
            ),
            device_regexes=[dut],
            traffic_items_to_start=R_U_DATA_PLANE_TRAFFIC_ITEMS,
            prechecks=[_bgp_established_check()],
            postchecks=[
                restricted_traffic,
                _bgp_established_check(restarted=True),
                _unclean_exit_check(
                    dut,
                    exclude_services=[
                        "wedge_agent",
                        "fboss_sw_agent",
                        "fboss_hw_agent@0",
                    ],
                ),
                create_device_core_dumps_check(),
            ],
            # Repeated intentional crashes make a single restart timestamp an
            # invalid basis for the generic BGP snapshot reconvergence check.
            # The postcheck above validates four established sessions and
            # recent uptime after the final crash; retain the independent core
            # comparison here.
            snapshot_checks=[create_core_dumps_snapshot_check()],
            cleanup_steps=cleanup_steps,
            stages=[
                create_steps_stage(
                    steps=[
                        policy_step(
                            all_unconstrained,
                            "Prepare all IXIA ports as Unconstrained",
                        ),
                        policy_step(
                            restricted_with_blocked,
                            "Prepare R as Restricted and B as Blocked",
                        ),
                        create_longevity_step(
                            duration=30,
                            description="Establish the Restricted traffic baseline",
                        ),
                        create_validation_step(
                            point_in_time_checks=[restricted_traffic],
                            description="Validate Restricted R-U traffic before crashes",
                        ),
                        hardware_step("restricted"),
                        blocked_port_step(),
                    ]
                ),
                create_steps_stage(
                    iteration=20,
                    description=(
                        "Crash Agent every 30 seconds for ten minutes without "
                        "overlapping explicit restart operations"
                    ),
                    steps=[
                        create_service_interruption_step(
                            service=taac_thrift.Service.AGENT,
                            trigger=taac_thrift.ServiceInterruptionTrigger.CRASH,
                            device_regexes=[dut],
                            description="Crash Agent with SIGKILL",
                        ),
                        create_longevity_step(
                            duration=30,
                            description="Hold 30 seconds before the next Agent crash",
                        ),
                    ],
                ),
                create_steps_stage(
                    steps=[
                        create_service_convergence_step(
                            services=[
                                taac_thrift.Service.AGENT,
                                taac_thrift.Service.BGP,
                            ],
                            timeout=600,
                            device_regexes=[dut],
                            description=(
                                "Wait for Agent and BGP convergence after the crash "
                                "campaign"
                            ),
                        ),
                        create_stop_traffic_step(),
                        create_regenerate_traffic_step(),
                        create_longevity_step(
                            duration=120,
                            description=(
                                "Measure the recovered Restricted stable state for "
                                "two minutes"
                            ),
                        ),
                        hardware_step("restricted"),
                        blocked_port_step(),
                    ]
                ),
            ],
        ),
    ]


def _restricted_port_flap_playbooks(dut, port_a, port_b, port_c):
    """Validate Restricted-policy stickiness across single and rapid flaps."""
    all_unconstrained = {
        port_a: "UNCONSTRAINED",
        port_b: "UNCONSTRAINED",
        port_c: "UNCONSTRAINED",
    }
    restricted_policies = {
        port_a: "RESTRICTED",
        port_b: "UNCONSTRAINED",
        port_c: "UNCONSTRAINED",
    }
    restricted_traffic = _traffic_loss_check(
        RESTRICTED_R_U_LOSSLESS_TRAFFIC_ITEMS,
        RESTRICTED_R_U_BLOCKED_TRAFFIC_ITEMS,
    )
    deny_only_traffic = _traffic_loss_check(
        [],
        RESTRICTED_R_U_BLOCKED_TRAFFIC_ITEMS,
    )
    flap_method = taac_thrift.InterfaceFlapMethod.THRIFT_PORT_STATE_CHANGE

    def prepare_steps(*, block_port_b=False):
        policies = dict(restricted_policies)
        if block_port_b:
            policies[port_b] = "BLOCKED"
        steps = [
            _set_access_policy_step(
                dut,
                all_unconstrained,
                "Prepare all IXIA ports as Unconstrained",
                start_traffic=False,
            ),
            _set_access_policy_step(
                dut,
                policies,
                (
                    "Prepare R as Restricted and B as Blocked"
                    if block_port_b
                    else "Prepare R as Restricted"
                ),
                start_traffic=False,
            ),
            _access_policy_hardware_check_step(
                dut,
                {port_a: "restricted"},
                "Validate Restricted SW/HW state before port disruption",
                start_traffic=False,
            ),
            create_validation_step(
                point_in_time_checks=[_bgp_established_check()],
                stage=taac_thrift.ValidationStage.PRE_TEST,
                description="Validate four-session BGP baseline",
                start_traffic=False,
            ),
            create_longevity_step(
                duration=30,
                description="Start R-U traffic and establish Restricted baseline",
            ),
            create_validation_step(
                point_in_time_checks=[restricted_traffic],
                description="Validate full Restricted traffic baseline",
            ),
        ]
        if block_port_b:
            steps.append(
                create_verify_port_operational_state_step(
                    interfaces=[port_b],
                    operational_state=False,
                    description=f"Validate Blocked port {port_b} is down",
                    device_regexes=[dut],
                )
            )
        return steps

    def mid_and_fresh_post_steps(recovery_seconds=30):
        return [
            create_validation_step(
                point_in_time_checks=[deny_only_traffic],
                description=(
                    "Mid-test: require every Restricted deny flow to remain at "
                    "100% loss; transient loss on allow flows is tolerated"
                ),
            ),
            create_run_task_step(
                task_name="ixia_stop_traffic_and_wait",
                params_dict={"wait_seconds": 0},
                description="Stop traffic and clear the disruption window",
                ixia_needed=True,
                start_traffic=False,
            ),
            create_longevity_step(
                duration=recovery_seconds,
                description="Restart traffic and establish a fresh recovery window",
            ),
            _access_policy_hardware_check_step(
                dut,
                {port_a: "restricted"},
                "Validate Restricted SW/HW state after port disruption",
            ),
        ]

    cleanup_steps = [
        create_interface_flap_step(
            enable=True,
            interfaces=[port_a],
            interface_flap_method=flap_method,
            delay=0,
            description=f"Ensure {port_a} is enabled during cleanup",
            start_traffic=False,
        ),
        *_policy_cleanup_steps(dut, port_a, port_b, port_c),
    ]

    return [
        create_access_policy_playbook(
            name="test_access_policy_restricted_single_port_flap",
            description=(
                "Disable Restricted port R once, hold it down for six seconds, "
                "enable it, and validate deny-path and full traffic recovery."
            ),
            device_regexes=[dut],
            traffic_items_to_start=R_U_DATA_PLANE_TRAFFIC_ITEMS,
            prechecks=[],
            postchecks=_common_postchecks(traffic_check=restricted_traffic),
            snapshot_checks=_snapshot_checks(dut),
            cleanup_steps=cleanup_steps,
            stages=[
                create_steps_stage(
                    steps=prepare_steps()
                    + [
                        create_interface_flap_step(
                            enable=False,
                            interfaces=[port_a],
                            interface_flap_method=flap_method,
                            delay=0,
                            description=f"Disable Restricted port {port_a}",
                            start_traffic=False,
                        ),
                        create_longevity_step(
                            duration=6,
                            description="Hold Restricted port down for six seconds",
                            start_traffic=False,
                        ),
                        create_interface_flap_step(
                            enable=True,
                            interfaces=[port_a],
                            interface_flap_method=flap_method,
                            delay=0,
                            description=f"Enable Restricted port {port_a}",
                            start_traffic=False,
                        ),
                    ]
                    + mid_and_fresh_post_steps()
                )
            ],
        ),
        create_access_policy_playbook(
            name="test_access_policy_restricted_rapid_port_flaps_15m",
            description=(
                "Rapid-flap Restricted port R every six seconds for 15 minutes "
                "and validate deny-path stickiness and full traffic recovery."
            ),
            device_regexes=[dut],
            traffic_items_to_start=R_U_DATA_PLANE_TRAFFIC_ITEMS,
            prechecks=[],
            postchecks=_common_postchecks(traffic_check=restricted_traffic),
            snapshot_checks=_snapshot_checks(dut),
            cleanup_steps=cleanup_steps,
            stages=[
                create_steps_stage(steps=prepare_steps()),
                create_steps_stage(
                    steps=[
                        create_fpf_rapid_flap_step(
                            interfaces_by_device={dut: [port_a]},
                            duration_sec=900,
                            flap_interval_sec=6,
                            device_regexes=[dut],
                            description=(
                                f"Rapid-flap Restricted port {port_a} every six "
                                "seconds for 15 minutes"
                            ),
                        )
                    ]
                ),
                create_steps_stage(steps=mid_and_fresh_post_steps()),
            ],
        ),
        create_access_policy_playbook(
            name="test_access_policy_restricted_rapid_port_flaps_with_agent_warmboot",
            description=(
                "Rapid-flap Restricted port R every six seconds for 15 minutes "
                "and warmboot Agent concurrently at minute ten."
            ),
            device_regexes=[dut],
            traffic_items_to_start=R_U_DATA_PLANE_TRAFFIC_ITEMS,
            prechecks=[],
            postchecks=_common_postchecks(
                traffic_check=restricted_traffic,
                restarted=True,
                max_session_uptime_sec=1800,
            ),
            snapshot_checks=_snapshot_checks(dut, restarted=True),
            cleanup_steps=cleanup_steps,
            stages=[
                create_steps_stage(steps=prepare_steps(block_port_b=True)),
                create_concurrent_steps_stage(
                    step_tracks=[
                        [
                            create_fpf_rapid_flap_step(
                                interfaces_by_device={dut: [port_a]},
                                duration_sec=900,
                                flap_interval_sec=6,
                                device_regexes=[dut],
                                description=(
                                    f"Rapid-flap Restricted port {port_a} every "
                                    "six seconds for 15 minutes"
                                ),
                            )
                        ],
                        [
                            create_longevity_step(
                                duration=600,
                                description=(
                                    "Wait until minute ten of the rapid-flap window"
                                ),
                                start_traffic=False,
                            ),
                            create_service_interruption_step(
                                service=taac_thrift.Service.AGENT,
                                device_regexes=[dut],
                                description=(
                                    "Warmboot Agent during Restricted rapid flaps"
                                ),
                                start_traffic=False,
                            ),
                            create_service_convergence_step(
                                services=[
                                    taac_thrift.Service.AGENT,
                                    taac_thrift.Service.BGP,
                                ],
                                timeout=300,
                                device_regexes=[dut],
                                description=(
                                    "Wait for Agent and BGP convergence after warmboot"
                                ),
                                start_traffic=False,
                            ),
                        ],
                    ],
                    description=(
                        "Run 15-minute Restricted rapid flaps with Agent warmboot "
                        "at minute ten"
                    ),
                ),
                create_steps_stage(
                    steps=mid_and_fresh_post_steps(recovery_seconds=120)
                    + [
                        create_verify_port_operational_state_step(
                            interfaces=[port_b],
                            operational_state=False,
                            description=(
                                f"Validate Blocked port {port_b} remains down "
                                "after Agent warmboot"
                            ),
                            device_regexes=[dut],
                        )
                    ]
                ),
            ],
        ),
    ]


def _speed_flip_playbooks(dut, port_a, port_b, port_c, speed_flip_port):
    """Validate access-policy programming across a non-IXIA port speed flip."""
    all_unconstrained = {
        port_a: "UNCONSTRAINED",
        port_b: "UNCONSTRAINED",
        port_c: "UNCONSTRAINED",
        speed_flip_port: "UNCONSTRAINED",
    }
    restricted = {
        port_a: "RESTRICTED",
        port_b: "BLOCKED",
        speed_flip_port: "RESTRICTED",
    }
    restricted_traffic = _traffic_loss_check(
        RESTRICTED_R_U_LOSSLESS_TRAFFIC_ITEMS,
        RESTRICTED_R_U_BLOCKED_TRAFFIC_ITEMS,
    )

    def register_200g_speed_patcher_step(description):
        return create_run_task_step(
            task_name="coop_register_patcher",
            params_dict={
                "hostname": dut,
                "config_name": "agent",
                "patcher_name": SPEED_FLIP_PATCHER_NAME,
                "py_func_name": "change_speed",
                "patcher_args": json.dumps(
                    {
                        "intfs": speed_flip_port,
                        "profile_id": SPEED_FLIP_200G_PROFILE,
                        "speed": "TWOHUNDREDG",
                    }
                ),
                "patcher_desc": (
                    "Set the Hatch access-policy speed-flip validation port to 200G"
                ),
            },
            description=description,
            start_traffic=False,
        )

    def unregister_200g_speed_patcher_step(description):
        return create_run_task_step(
            task_name="coop_unregister_patchers",
            params_dict={
                "hostname": dut,
                "config_names": ["agent"],
                "regex": f"^{SPEED_FLIP_PATCHER_NAME}$",
            },
            description=description,
            start_traffic=False,
        )

    def warmboot_and_converge_steps(description, *, wait_for_bgp=True):
        services = [taac_thrift.Service.AGENT]
        if wait_for_bgp:
            services.append(taac_thrift.Service.BGP)
        return [
            create_service_interruption_step(
                service=taac_thrift.Service.AGENT,
                description=description,
                device_regexes=[dut],
                start_traffic=False,
            ),
            create_service_convergence_step(
                services=services,
                timeout=300,
                description=(
                    "Wait for Agent and BGP convergence"
                    if wait_for_bgp
                    else "Wait for Agent convergence at the temporary 200G state"
                ),
                device_regexes=[dut],
                start_traffic=False,
            ),
        ]

    def restore_speed_and_policy_steps():
        return [
            unregister_200g_speed_patcher_step(
                "Remove the 200G speed patcher during cleanup"
            ),
            *warmboot_and_converge_steps(
                "Warmboot Agent to restore the original 100G configuration"
            ),
            _set_access_policy_step(
                dut,
                all_unconstrained,
                "Restore access-policy ports to Unconstrained",
                start_traffic=False,
            ),
            create_verify_port_speed_step_v2(
                ports=[speed_flip_port],
                speed_to_verify=100,
                description=f"Verify {speed_flip_port} restored to 100G",
                start_traffic=False,
            ),
        ]

    def common_preparation_steps():
        return [
            _set_access_policy_step(
                dut,
                all_unconstrained,
                "Prepare all access-policy ports as Unconstrained",
                start_traffic=False,
            ),
            create_verify_port_speed_step_v2(
                ports=[speed_flip_port],
                speed_to_verify=100,
                description=f"Verify {speed_flip_port} starts at 100G",
                start_traffic=False,
            ),
            _set_access_policy_step(
                dut,
                restricted,
                (
                    f"Set {port_a} and {speed_flip_port} to Restricted and "
                    f"{port_b} to Blocked"
                ),
                start_traffic=False,
            ),
            _access_policy_hardware_check_step(
                dut,
                {port_a: "restricted", speed_flip_port: "restricted"},
                "Validate both Restricted ports in Agent and uncached hardware",
                start_traffic=False,
            ),
            create_verify_port_operational_state_step(
                interfaces=[port_b],
                operational_state=False,
                description=f"Validate Blocked port {port_b} is down",
                device_regexes=[dut],
            ),
            create_longevity_step(
                duration=30,
                description="Establish the Restricted R-U traffic baseline",
            ),
            create_validation_step(
                point_in_time_checks=[restricted_traffic],
                stage=taac_thrift.ValidationStage.MID_TEST,
                description="Validate Restricted R-U traffic before the speed change",
            ),
        ]

    return [
        create_access_policy_playbook(
            name="test_access_policy_restricted_non_ixia_port_speed_to_200g_warmboot",
            description=(
                f"Put {speed_flip_port} in Restricted mode, apply a COOP 200G "
                "copper-profile patcher, warmboot Agent, and verify policy "
                "stickiness on both Restricted ports without disturbing R-U traffic."
            ),
            device_regexes=[dut],
            traffic_items_to_start=R_U_DATA_PLANE_TRAFFIC_ITEMS,
            prechecks=[_bgp_established_check()],
            postchecks=_common_postchecks(
                traffic_check=restricted_traffic,
                restarted=True,
                expected_bgp_sessions=3,
            ),
            # The 100G -> 200G speed change intentionally removes one BGP
            # adjacency. Core-dump comparison remains valid, but a BGP
            # before/after identity comparison does not.
            snapshot_checks=[create_core_dumps_snapshot_check()],
            cleanup_steps=restore_speed_and_policy_steps(),
            stages=[
                create_steps_stage(
                    steps=[
                        *common_preparation_steps(),
                        register_200g_speed_patcher_step(
                            f"Register the COOP 200G speed patcher for {speed_flip_port}"
                        ),
                        *warmboot_and_converge_steps(
                            "Warmboot Agent to activate the 200G speed patcher",
                            wait_for_bgp=False,
                        ),
                        create_longevity_step(
                            duration=120,
                            description="Hold the 200G state after Agent warmboot",
                        ),
                        create_verify_port_speed_step_v2(
                            ports=[speed_flip_port],
                            speed_to_verify=200,
                            description=f"Verify {speed_flip_port} is at 200G",
                        ),
                        _access_policy_hardware_check_step(
                            dut,
                            {port_a: "restricted", speed_flip_port: "restricted"},
                            "Verify both Restricted bindings survived the speed change and warmboot",
                        ),
                        create_verify_port_operational_state_step(
                            interfaces=[port_b],
                            operational_state=False,
                            description=(
                                f"Verify Blocked port {port_b} remains down after "
                                "the speed-change warmboot"
                            ),
                            device_regexes=[dut],
                        ),
                    ]
                )
            ],
        ),
        create_access_policy_playbook(
            name="test_access_policy_remove_speed_patcher_to_100g_warmboot",
            description=(
                f"Remove the COOP 200G patcher for {speed_flip_port}, return that "
                "port to Unconstrained, warmboot Agent, and verify the original "
                "100G state while the primary Restricted port remains programmed."
            ),
            device_regexes=[dut],
            traffic_items_to_start=R_U_DATA_PLANE_TRAFFIC_ITEMS,
            prechecks=[_bgp_established_check()],
            postchecks=_common_postchecks(
                traffic_check=restricted_traffic, restarted=True
            ),
            # The setup intentionally transitions the link 100G -> 200G before
            # restoring it to 100G, so original BGP-session identity is not a
            # valid lifecycle invariant. The postcheck still requires all four
            # sessions to recover after the final warmboot.
            snapshot_checks=[create_core_dumps_snapshot_check()],
            cleanup_steps=restore_speed_and_policy_steps(),
            stages=[
                create_steps_stage(
                    steps=[
                        *common_preparation_steps(),
                        register_200g_speed_patcher_step(
                            f"Prepare {speed_flip_port} at 200G through COOP"
                        ),
                        *warmboot_and_converge_steps(
                            "Warmboot Agent to establish the 200G starting state",
                            wait_for_bgp=False,
                        ),
                        create_verify_port_speed_step_v2(
                            ports=[speed_flip_port],
                            speed_to_verify=200,
                            description=f"Verify {speed_flip_port} reached 200G",
                        ),
                        _set_access_policy_step(
                            dut,
                            {speed_flip_port: "UNCONSTRAINED"},
                            f"Remove Restricted policy from {speed_flip_port}",
                            start_traffic=False,
                        ),
                        unregister_200g_speed_patcher_step(
                            f"Remove the 200G speed patcher from {speed_flip_port}"
                        ),
                        *warmboot_and_converge_steps(
                            "Warmboot Agent to restore the original 100G configuration"
                        ),
                        create_longevity_step(
                            duration=120,
                            description="Hold the restored 100G state after warmboot",
                        ),
                        create_verify_port_speed_step_v2(
                            ports=[speed_flip_port],
                            speed_to_verify=100,
                            description=f"Verify {speed_flip_port} returned to 100G",
                        ),
                        _access_policy_hardware_check_step(
                            dut,
                            {
                                port_a: "restricted",
                                speed_flip_port: "unconstrained",
                            },
                            "Verify only the primary port remains Restricted in hardware",
                        ),
                        create_verify_port_operational_state_step(
                            interfaces=[port_b],
                            operational_state=False,
                            description=(
                                f"Verify Blocked port {port_b} remains down after "
                                "the speed-restoration warmboot"
                            ),
                            device_regexes=[dut],
                        ),
                    ]
                )
            ],
        ),
    ]


def _link_down_policy_transition_playbook(dut, port_a, port_b, port_c):
    """Apply Restricted policy while the protected port is disabled."""
    all_unconstrained = {
        port_a: "UNCONSTRAINED",
        port_b: "UNCONSTRAINED",
        port_c: "UNCONSTRAINED",
    }
    restricted_traffic = _traffic_loss_check(
        RESTRICTED_R_U_LOSSLESS_TRAFFIC_ITEMS,
        RESTRICTED_R_U_BLOCKED_TRAFFIC_ITEMS,
    )
    unconstrained_traffic = _traffic_loss_check(R_U_DATA_PLANE_TRAFFIC_ITEMS, [])
    return create_access_policy_playbook(
        name="test_access_policy_unconstrained_to_restricted_while_port_disabled",
        description=(
            "Start with R Unconstrained, disable it, apply Restricted policy while "
            "down, re-enable it, restart traffic, and validate the final state as "
            "a normal Restricted port."
        ),
        device_regexes=[dut],
        traffic_items_to_start=R_U_DATA_PLANE_TRAFFIC_ITEMS,
        prechecks=[_bgp_established_check()],
        postchecks=_common_postchecks(traffic_check=restricted_traffic),
        snapshot_checks=_snapshot_checks(dut),
        cleanup_steps=[
            create_interface_flap_step(
                enable=True,
                interfaces=[port_a],
                interface_flap_method=taac_thrift.InterfaceFlapMethod.THRIFT_PORT_STATE_CHANGE,
                description=f"Ensure {port_a} is enabled during cleanup",
                start_traffic=False,
            ),
            *_policy_cleanup_steps(dut, port_a, port_b, port_c),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    _set_access_policy_step(
                        dut,
                        all_unconstrained,
                        "Prepare all IXIA-facing ports as Unconstrained",
                        start_traffic=False,
                    ),
                    create_longevity_step(
                        duration=30,
                        description="Start traffic and establish the Unconstrained baseline",
                    ),
                    create_validation_step(
                        point_in_time_checks=[unconstrained_traffic],
                        stage=taac_thrift.ValidationStage.MID_TEST,
                        description="Validate all selected R-U traffic is lossless before the trigger",
                    ),
                    create_interface_flap_step(
                        enable=False,
                        interfaces=[port_a],
                        interface_flap_method=taac_thrift.InterfaceFlapMethod.THRIFT_PORT_STATE_CHANGE,
                        description=f"Disable Unconstrained port {port_a}",
                        start_traffic=False,
                    ),
                    create_longevity_step(
                        duration=30,
                        description="Hold the port disabled before changing policy",
                        start_traffic=False,
                    ),
                    _set_access_policy_step(
                        dut,
                        {port_a: "RESTRICTED"},
                        f"Apply Restricted policy to disabled port {port_a}",
                        start_traffic=False,
                    ),
                    create_interface_flap_step(
                        enable=True,
                        interfaces=[port_a],
                        interface_flap_method=taac_thrift.InterfaceFlapMethod.THRIFT_PORT_STATE_CHANGE,
                        description=f"Re-enable Restricted port {port_a}",
                        start_traffic=False,
                    ),
                    create_run_task_step(
                        task_name="ixia_stop_traffic_and_wait",
                        params_dict={"wait_seconds": 0},
                        description="Stop traffic and clear the transition window",
                        ixia_needed=True,
                        start_traffic=False,
                    ),
                    create_longevity_step(
                        duration=120,
                        description="Restart traffic and hold the final Restricted state",
                    ),
                    _access_policy_hardware_check_step(
                        dut,
                        {port_a: "restricted"},
                        f"Validate Restricted Agent and hardware state on {port_a}",
                    ),
                ]
            )
        ],
    )


# --------------------------------------------------------------------------
# Chaos daemon: on-box trigger engine
# --------------------------------------------------------------------------
# Runs as a HOST systemd unit (NOT inside netos.service.fwdstack) so it
# outlives every agent restart, and shells into the container for each device
# command.  Verified on rsw002: a host unit keeps its PID and an unbroken
# heartbeat across `fboss-updater restart agent`, and can drive thriftdbg /
# fboss2 / fboss-updater inside the container throughout.
#
# The daemon owns TIMING only.  All assertions live in the TAAC pre/post and
# snapshot health checks, plus the JSONL this writes (retrieved at teardown) so
# a red run can be pinned to the exact overlap that produced it.
_CHAOS_DAEMON_SOURCE = r'''#!/usr/bin/env python3
"""Hatch access-policy chaos daemon.

Continuously overlaps agent warmboots with access-policy transitions and port
flaps, to expose transient races between COOP config render and agent restart.
Writes one JSON object per event to the configured event log.
"""
import json
import os
import random
import re
import shlex
import subprocess
import sys
import threading
import time
from datetime import datetime

CFG = json.load(open(os.environ.get("CHAOS_CONFIG", "/var/lib/hatch_chaos/config.json")))
EVENT_LOG = CFG["event_log"]
UNCONSTRAINED, RESTRICTED, BLOCKED = 1, 2, 3

_log_lock = threading.Lock()
_stop = threading.Event()
# Hard invariant from the campaign spec: never two overlapping agent restarts.
_warmboot_lock = threading.Lock()


def _now():
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def emit(event, **kw):
    kw["event"] = event
    kw["ts"] = _now()
    kw["mono"] = round(time.monotonic(), 3)
    line = json.dumps(kw, sort_keys=True)
    with _log_lock:
        with open(EVENT_LOG, "a") as fh:
            fh.write(line + "\n")
            fh.flush()
    print(line, flush=True)


def dev(cmd, timeout=150):
    """Run one device command.

    This daemon runs INSIDE netos.service.fwdstack, where fboss2, thriftdbg and
    fboss-updater are already on PATH -- no `machinectl` hop.  That is forced by
    the TAAC deploy path: run_commands_on_shell lands in this container (port
    222), so the unit and this process must live here too.
    """
    try:
        p = subprocess.run(
            ["/bin/bash", "-c", cmd], capture_output=True, text=True, timeout=timeout
        )
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "TimeoutExpired"
    except Exception as exc:  # noqa: BLE001
        return 125, "", repr(exc)


def set_policy(pairs):
    body = {"request": {"policies": [{"port_name": p, "state": s} for p, s in pairs]}}
    cmd = (
        "thriftdbg sendRequest setAccessPolicy %s --host ::1 --port 6969 "
        "--request_timeout_ms 90000" % shlex.quote(json.dumps(body))
    )
    t0 = time.monotonic()
    rc, out, err = dev(cmd, timeout=CFG["policy_outer_timeout_sec"])
    return rc, round(time.monotonic() - t0, 3), (err or out)[-300:]


def get_policy():
    rc, out, _ = dev(
        "thriftdbg sendRequest getAccessPolicy '{}' --host ::1 --port 6969 "
        "--request_timeout_ms 20000"
    )
    return dict(re.findall(r'\{"port_name":"([^"]+)","state":"([A-Z]+)"\}', out))


def hw_state(ports):
    """Platform-specific programmed state for the given ports.

    Parses the switch state properly rather than regexing it.  A regex anchored
    on portName does NOT work: the class field sits thousands of characters
    further into each port object (past the queues/aqms arrays), so a bounded
    window either misses it or matches the NEXT port's value.  Measured: the
    old regex returned None for every port even when userMetaData was set.

    getCurrentStateJSON returns a JSON *string* containing JSON, hence the
    double decode.
    """
    rc, out, _ = dev(
        "thriftdbg sendRequest getCurrentStateJSON '{\"path\":\"portMaps\"}' "
        "--host ::1 --port 5909 --request_timeout_ms 30000",
        timeout=60,
    )
    field = CFG["hw_field"]
    found = dict.fromkeys(ports)
    try:
        i = out.find('"')
        if i < 0:
            return found
        doc = json.loads(out[i:].strip())
        if isinstance(doc, str):
            doc = json.loads(doc)
    except Exception as exc:  # noqa: BLE001
        found["_parse_error"] = repr(exc)[:120]
        return found

    def walk(obj):
        if isinstance(obj, dict):
            if "portName" in obj:
                yield obj
            for v in obj.values():
                yield from walk(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from walk(v)

    wanted = set(ports)
    for port_obj in walk(doc):
        name = port_obj.get("portName")
        if name in wanted:
            found[name] = port_obj.get(field)
    return found


def port_admin(port, enable):
    verb = "enable" if enable else "disable"
    # fboss2 hangs forever without a TTY unless stdin is closed -- see the
    # patcher-CLI finding; the same applies to every fboss2 subcommand here.
    rc, out, err = dev(
        "fboss2 set port %s state %s --yes </dev/null" % (port, verb), timeout=60
    )
    return rc


def port_states():
    rc, out, _ = dev(
        "fboss2 show port </dev/null | sed -e 's/\\x1b\\[[0-9;]*m//g'", timeout=60
    )
    states = {}
    for line in out.splitlines():
        f = line.split()
        if len(f) >= 4 and f[1].startswith("eth"):
            states[f[1]] = (f[2], f[3])
    return states


def bgp_established():
    rc, out, _ = dev(
        "ss -tn state established '( sport = :179 or dport = :179 )' | grep -c e50e",
        timeout=45,
    )
    try:
        return int(out.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        return -1


def boot_counters():
    rc, out, _ = dev(
        "thriftdbg sendRequest getRegexCounters "
        "'{\"regex\":\"^(warm_boot|cold_boot)\\\\.sum$\"}' "
        "--host ::1 --port 5909 --request_timeout_ms 20000",
        timeout=60,
    )
    return dict(
        (k, int(v)) for k, v in re.findall(r'"(warm_boot|cold_boot)\.sum":(\d+)', out)
    )


def agent_ready(deadline_sec=300):
    end = time.monotonic() + deadline_sec
    while time.monotonic() < end and not _stop.is_set():
        rc, _, _ = dev(
            "thriftdbg sendRequest getRegexCounters '{\"regex\":\"^warm_boot\\\\.sum$\"}' "
            "--host ::1 --port 5909 --request_timeout_ms 5000",
            timeout=25,
        )
        if rc == 0:
            return True
        time.sleep(5)
    return False


# ---------------------------------------------------------------- flap worker
def flap_worker():
    """Admin-flap the 4 chaos flap ports forever.

    NOTE: setAccessPolicy triggers a full config re-render from base+patchers,
    which silently re-enables any port that was admin-disabled via `fboss2 set
    port`.  That is expected here (it is extra churn), but it must be recorded
    rather than scored as a flap failure -- hence FLAP_STOLEN_BY_POLICY.
    """
    ports = CFG["flap_ports"]
    n = 0
    while not _stop.is_set():
        n += 1
        for p in ports:
            if _stop.is_set():
                return
            port_admin(p, enable=False)
        _stop.wait(CFG["flap_interval_sec"])
        observed = port_states()
        stolen = [
            p for p in ports if observed.get(p, ("", ""))[0].lower() == "enabled"
        ]
        if stolen:
            emit("FLAP_STOLEN_BY_POLICY", iteration=n, ports=stolen)
        for p in ports:
            port_admin(p, enable=True)
        _stop.wait(CFG["flap_interval_sec"])


# ------------------------------------------------------- transition matrix
def transitions():
    """R/C transition kinds, one per warmboot iteration, over the same 4 ports.

    R = Restricted, C = Unconstrained.  `r_side` are the 2 ports that start
    Restricted, `c_side` the 2 that start Unconstrained.  The two *_ON_DISABLED
    variants admin-disable the target ports first, so the policy change lands on
    a port that is already down.

    Each kind returns (name, [(port, state)], ports_to_disable_first).  The
    cycle always ends by restoring the baseline split, so a kind is never
    interpreted relative to whatever the previous kind left behind.
    """
    r_side = CFG["restricted_ports"]
    c_side = CFG["unconstrained_ports"]
    every = r_side + c_side
    return [
        ("ADD_ALL_TO_R", [(p, RESTRICTED) for p in every], []),
        ("REMOVE_ALL_FROM_R", [(p, UNCONSTRAINED) for p in every], []),
        ("R_TO_C", [(p, UNCONSTRAINED) for p in r_side], []),
        ("C_TO_R", [(p, RESTRICTED) for p in c_side], []),
        ("C_TO_R_ON_DISABLED", [(p, RESTRICTED) for p in c_side], list(c_side)),
        ("R_TO_C_ON_DISABLED", [(p, UNCONSTRAINED) for p in r_side], list(r_side)),
    ]


def baseline_pairs():
    return [(p, RESTRICTED) for p in CFG["restricted_ports"]] + [
        (p, UNCONSTRAINED) for p in CFG["unconstrained_ports"]
    ]


PHASES = ("BEFORE", "DURING", "AFTER")


def phase_offset(phase, rnd):
    """Offset of the policy op relative to warmboot dispatch, in seconds.

    Jittered inside each bucket so an 8h soak densifies coverage instead of
    re-testing three identical points ~190 times each.
    """
    if phase == "BEFORE":
        return -rnd.uniform(0.2, 8.0)
    if phase == "DURING":
        return rnd.uniform(0.2, 9.0)
    return rnd.uniform(40.0, 90.0)


def run_cycle(idx, rnd):
    kinds = transitions()
    kind, pairs, to_disable = kinds[idx % len(kinds)]
    phase = PHASES[(idx // len(kinds)) % len(PHASES)]
    offset = phase_offset(phase, rnd)

    for p in to_disable:
        port_admin(p, enable=False)

    pre_boots = boot_counters()
    pre_bgp = bgp_established()
    result = {}

    def do_policy(anchor):
        delay = offset - (time.monotonic() - anchor)
        if delay > 0:
            _stop.wait(delay)
        actual = round(time.monotonic() - anchor, 3)
        rc, dur, msg = set_policy(pairs)
        result.update(policy_rc=rc, policy_sec=dur, actual_offset_sec=actual)
        if rc != 0:
            result["policy_error"] = msg

    with _warmboot_lock:
        if phase == "BEFORE":
            # Policy lands first, then we WAIT the lead time before warmbooting.
            # (Firing the policy and immediately warmbooting collapses every
            # BEFORE iteration onto the same ~2s offset, which defeats the
            # point of sweeping.)
            lead = abs(offset)
            p_start = time.monotonic()
            rc, dur, msg = set_policy(pairs)
            result.update(policy_rc=rc, policy_sec=dur)
            if rc != 0:
                result["policy_error"] = msg
            remaining = lead - (time.monotonic() - p_start)
            if remaining > 0:
                _stop.wait(remaining)
            t0 = time.monotonic()
            result["actual_offset_sec"] = round(p_start - t0, 3)  # negative
            wb_rc, _, wb_err = dev(
                "fboss-updater restart agent --boot-type 2", timeout=240
            )
        else:
            t0 = time.monotonic()
            th = threading.Thread(target=do_policy, args=(t0,), daemon=True)
            th.start()
            wb_rc, _, wb_err = dev(
                "fboss-updater restart agent --boot-type 2", timeout=240
            )
            th.join(timeout=CFG["policy_outer_timeout_sec"] + 60)

        ready = agent_ready()
        _stop.wait(20)

        readback = get_policy()
        expected = {
            p: {UNCONSTRAINED: "UNCONSTRAINED", RESTRICTED: "RESTRICTED",
                BLOCKED: "BLOCKED"}[s]
            for p, s in pairs
        }
        mismatch = {
            p: {"want": v, "got": readback.get(p)}
            for p, v in expected.items()
            if readback.get(p) != v
        }
        post_boots = boot_counters()
        post_bgp = bgp_established()

        verdict = "PASS"
        if wb_rc != 0 or not ready:
            verdict = "BOOT_FAILURE"
        elif result.get("policy_rc") not in (0, None):
            verdict = "CONTROL_PLANE"
        elif mismatch:
            verdict = "READBACK_MISMATCH"
        elif post_boots.get("warm_boot") != 1 or post_boots.get("cold_boot") != 0:
            verdict = "BOOT_TYPE_UNEXPECTED"

        emit(
            "CYCLE",
            iteration=idx,
            kind=kind,
            phase=phase,
            intended_offset_sec=round(offset, 3),
            verdict=verdict,
            warmboot_rc=wb_rc,
            agent_ready=ready,
            readback_mismatch=mismatch or None,
            pre_boots=pre_boots,
            post_boots=post_boots,
            bgp_pre=pre_bgp,
            bgp_post=post_bgp,
            hw=hw_state([p for p, _ in pairs]),
            **result,
        )

    for p in to_disable:
        port_admin(p, enable=True)

    # Restore the 2R/2C split so the next kind is evaluated against a known
    # baseline rather than whatever this one left behind.
    rc, dur, msg = set_policy(baseline_pairs())
    if rc != 0:
        emit("BASELINE_RESTORE_FAILED", iteration=idx, rc=rc, sec=dur, error=msg)


def main():
    duration = CFG["duration_sec"]
    rnd = random.Random(CFG.get("seed", 20260903))
    open(EVENT_LOG, "a").close()
    emit("CAMPAIGN_START", config=CFG)

    baseline = baseline_pairs()
    rc, dur, msg = set_policy(baseline)
    emit("BASELINE_POLICY", rc=rc, sec=dur, pairs=baseline, error=None if rc == 0 else msg)

    flapper = threading.Thread(target=flap_worker, daemon=True)
    flapper.start()

    end = time.monotonic() + duration
    idx = 0
    while time.monotonic() < end and not _stop.is_set():
        cycle_start = time.monotonic()
        try:
            run_cycle(idx, rnd)
        except Exception as exc:  # noqa: BLE001  keep going; record the failure
            emit("CYCLE_EXCEPTION", iteration=idx, error=repr(exc))
        idx += 1
        remaining = CFG["warmboot_interval_sec"] - (time.monotonic() - cycle_start)
        if remaining > 0:
            _stop.wait(remaining)

    _stop.set()
    flapper.join(timeout=30)
    emit("CAMPAIGN_END", iterations=idx)
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


_CHAOS_RESTORE_SOURCE = r"""#!/bin/bash
# ExecStopPost hook: always return the box to a sane state, including when the
# RuntimeMaxSec backstop kills a wedged daemon.  Verified to run on the timeout
# path as well as on clean exit, both host-side and in-container.
#
# Runs INSIDE netos.service.fwdstack, so thriftdbg/fboss2 are on PATH directly.
CFG=/var/lib/hatch_chaos/config.json
LOG=/var/lib/hatch_chaos/restore.log
PORTS=$(python3 -c "
import json
c=json.load(open('$CFG'))
print(' '.join(c['restricted_ports']+c['unconstrained_ports']))
" 2>/dev/null)
[ -z "$PORTS" ] && { echo "$(date -Is) restore: no ports in config" >>"$LOG"; exit 0; }

POLICIES=""
for p in $PORTS; do
  [ -n "$POLICIES" ] && POLICIES="$POLICIES,"
  POLICIES="$POLICIES{\"port_name\":\"$p\",\"state\":1}"
done

{
  echo "$(date -Is) restore: ports -> UNCONSTRAINED + enabled: $PORTS"
  thriftdbg sendRequest setAccessPolicy \
    "{\"request\":{\"policies\":[$POLICIES]}}" \
    --host ::1 --port 6969 --request_timeout_ms 90000
  # Serial on purpose: concurrent `fboss2 set port state` races and silently
  # drops writes (measured -- 3 of 4 enables lost when run in parallel).
  for p in $PORTS; do fboss2 set port "$p" state enable --yes </dev/null; done
  echo "$(date -Is) restore hook completed"
} >>"$LOG" 2>&1
exit 0
"""


def _chaos_unit_file():
    """systemd unit for the chaos daemon.

    The daemon self-exits 0 at its own --duration, so a clean soak leaves the
    unit `inactive (success)`.  RuntimeMaxSec sits 30 min beyond that as a pure
    dead-man switch: if it ever fires, the unit goes `failed (timeout)` and that
    unambiguously means the daemon wedged.  ExecStopPost restores either way.
    """
    return f"""[Unit]
Description=FBOSS Hatch access-policy chaos soak (auto-expires)

[Service]
Type=simple
Environment=CHAOS_CONFIG={CHAOS_REMOTE_DIR}/config.json
ExecStart=/usr/bin/python3 {CHAOS_DAEMON_PATH}
ExecStopPost={CHAOS_RESTORE_PATH}
RuntimeMaxSec={CHAOS_BACKSTOP_SECONDS}
Restart=no
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""


def _chaos_config_json(platform, chaos_ports):
    """Per-device daemon config.  Keeps the daemon source identical everywhere."""
    return json.dumps(
        {
            "event_log": CHAOS_EVENT_LOG,
            "duration_sec": CHAOS_SOAK_SECONDS,
            "warmboot_interval_sec": CHAOS_WARMBOOT_INTERVAL_SECONDS,
            "flap_interval_sec": CHAOS_FLAP_INTERVAL_SECONDS,
            "policy_outer_timeout_sec": 120,
            # W400 programs the port class in userMetaData; W400C uses an ACL
            # bindpoint and leaves Metadata at 0 in both U and R.
            "hw_field": (
                "userMetaData" if platform == "W400" else "ingressAclTableName"
            ),
            # Exactly 4 ports: the same set is flapped and cycled.
            "restricted_ports": chaos_ports.restricted,
            "unconstrained_ports": chaos_ports.unconstrained,
            "flap_ports": chaos_ports.all_ports,
        },
        indent=2,
        sort_keys=True,
    )


def _write_file_cmd(remote_path, content):
    """Shell command that materialises `content` at `remote_path`, base64-safe.

    Deliberately NOT the `scp_file` task.  Measured on rsw002: `scp_file` uses
    ParamikoClient and lands on the HOST, while `run_commands_on_shell` uses
    ssh port 222 and lands INSIDE netos.service.fwdstack -- a file written by
    the former is literally invisible to the latter.  Mixing them would scp the
    unit to the host and then `systemctl start` it in the container, where it
    does not exist.  Everything therefore goes through one namespace.

    base64 also avoids the quoting mangling that heredocs suffer through
    nested shells ($$ and $(...) get eaten).
    """
    blob = base64.b64encode(content.encode("utf-8")).decode("ascii")
    return f"printf %s {blob} | base64 -d > {remote_path}"


def _write_file_step(dut, remote_path, content, what):
    return create_run_commands_on_shell_step(
        device_name=dut,
        cmds=[_write_file_cmd(remote_path, content)],
        description=f"Deploy {what} -> {remote_path}",
    )


def _chaos_start_stage(dut, platform, chaos_ports):
    """Deploy and start the chaos daemon.

    Deliberately a STAGE, not a TestConfig setup_task.  setup_tasks are
    TestConfig-scoped, so they would run for every playbook in this file and --
    worse -- they run BEFORE prechecks, which would mean the "baseline"
    prechecks were measured on a box already warmbooting every 2.5 min with
    ports flapping.  As a first stage the chaos starts only after a clean
    baseline has been recorded, and only for this playbook.
    """
    return create_steps_stage(
        stage_id="chaos_start",
        description="Deploy and start the on-box chaos daemon.",
        steps=[
            create_run_commands_on_shell_step(
                device_name=dut,
                cmds=[
                    f"mkdir -p {CHAOS_REMOTE_DIR}",
                    # Never inherit a previous run's unit or event log.
                    f"systemctl stop {CHAOS_UNIT_NAME} || true",
                    f"systemctl reset-failed {CHAOS_UNIT_NAME} || true",
                    f"rm -f {CHAOS_EVENT_LOG}",
                ],
                description="Clear any residue from a previous chaos run.",
            ),
            _write_file_step(dut, CHAOS_DAEMON_PATH, _CHAOS_DAEMON_SOURCE, "chaosd.py"),
            _write_file_step(
                dut, CHAOS_RESTORE_PATH, _CHAOS_RESTORE_SOURCE, "restore.sh"
            ),
            _write_file_step(
                dut,
                f"{CHAOS_REMOTE_DIR}/config.json",
                _chaos_config_json(platform, chaos_ports),
                f"{platform} daemon config",
            ),
            _write_file_step(dut, CHAOS_UNIT_PATH, _chaos_unit_file(), "systemd unit"),
            create_run_commands_on_shell_step(
                device_name=dut,
                cmds=[
                    f"chmod +x {CHAOS_DAEMON_PATH} {CHAOS_RESTORE_PATH}",
                    # Fail loudly here rather than starting a half-deployed
                    # daemon: everything we just wrote must actually parse.
                    'python3 -c "import py_compile;'
                    f" py_compile.compile('{CHAOS_DAEMON_PATH}', doraise=True)\"",
                    f"bash -n {CHAOS_RESTORE_PATH}",
                    'python3 -c "import json;'
                    f" json.load(open('{CHAOS_REMOTE_DIR}/config.json'))\"",
                    "systemctl daemon-reload",
                    # Deliberately NOT `enable`d: a chaos daemon must never
                    # come back on its own after a reboot.
                    f"systemctl start {CHAOS_UNIT_NAME}",
                    f"systemctl is-active {CHAOS_UNIT_NAME}",
                ],
                description="Validate the deployed files, then start the daemon.",
            ),
        ],
    )


def _chaos_stop_stage(dut):
    """Stop the daemon, restore ports, and retrieve the verdict log.

    Must complete BEFORE postchecks run, so the post-soak traffic/BGP/core
    assertions are made against a quiesced box rather than mid-chaos.
    """
    return create_steps_stage(
        stage_id="chaos_stop",
        description="Stop chaos, restore ports, collect the event log.",
        steps=[
            create_run_commands_on_shell_step(
                device_name=dut,
                cmds=[
                    # Stopping runs ExecStopPost, which restores every chaos
                    # port to Unconstrained and re-enables it.
                    f"systemctl stop {CHAOS_UNIT_NAME} || true",
                    f"systemctl reset-failed {CHAOS_UNIT_NAME} || true",
                    f"cat {CHAOS_REMOTE_DIR}/restore.log 2>/dev/null || true",
                ],
                description="Stop chaos daemon and run the restore hook.",
            ),
            # NOTE: no scp-from-device step here.  The `scp_file` task only
            # pushes local->device (it reads params["remote_path"]
            # unconditionally and ignores `direction`), so a from-device
            # variant would KeyError.  The verdict log is instead dumped into
            # the run log below and left on the box at CHAOS_EVENT_LOG.
            create_run_commands_on_shell_step(
                device_name=dut,
                cmds=[
                    f"echo '--- chaos verdict summary ({CHAOS_EVENT_LOG}) ---'",
                    # Per-verdict counts first, then any non-PASS iteration in
                    # full, so a red run points straight at the offending
                    # overlap without needing the whole file.
                    f'grep -o \'"verdict": "[A-Z_]*"\' {CHAOS_EVENT_LOG} '
                    "| sort | uniq -c || true",
                    f'grep -v \'"verdict": "PASS"\' {CHAOS_EVENT_LOG} || true',
                    f"wc -l {CHAOS_EVENT_LOG} || true",
                ],
                description="Dump the chaos verdict summary into the run log.",
            ),
            create_run_commands_on_shell_step(
                device_name=dut,
                cmds=[
                    f"rm -f {CHAOS_UNIT_PATH}",
                    "systemctl daemon-reload",
                ],
                description="Remove the chaos unit from the device.",
            ),
        ],
    )


def _unrelated_link_drain_playbook(
    dut,
    port_a,
    port_b,
    port_c,
    drain_interfaces,
):
    """Verify an unrelated bulk link drain does not alter R-port behavior."""
    restricted_traffic = _traffic_loss_check(
        RESTRICTED_R_U_LOSSLESS_TRAFFIC_ITEMS,
        RESTRICTED_R_U_BLOCKED_TRAFFIC_ITEMS,
    )
    restricted_policies = {
        port_a: "RESTRICTED",
        port_b: "UNCONSTRAINED",
        port_c: "UNCONSTRAINED",
    }

    def stable_state_checks(*, restarted=False):
        return [
            restricted_traffic,
            _bgp_established_check(restarted=restarted),
            _unclean_exit_check(dut),
            create_device_core_dumps_check(),
        ]

    return create_access_policy_playbook(
        name="test_access_policy_unrelated_link_drain_undrain",
        description=(
            f"Keep {port_a} Restricted while bulk-draining unrelated links "
            f"{list(drain_interfaces)}, then bulk-undrain them and verify the "
            "Restricted R-U traffic and health contract in both phases."
        ),
        device_regexes=[dut],
        traffic_items_to_start=R_U_DATA_PLANE_TRAFFIC_ITEMS,
        prechecks=[_bgp_established_check()],
        postchecks=stable_state_checks(),
        # A hard interface drain must not restart BGP. Compare cores and retain
        # the original session-uptime baseline across both drain transitions.
        snapshot_checks=[create_core_dumps_snapshot_check()],
        cleanup_steps=[
            create_drain_undrain_step(
                drain=False,
                drain_handler=taac_thrift.DrainHandler.LOCAL_DRAINER,
                interfaces=list(drain_interfaces),
                hard_drain_interfaces=True,
                description="Ensure all unrelated links are undrained",
                start_traffic=False,
            ),
            *_policy_cleanup_steps(dut, port_a, port_b, port_c),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_drain_undrain_step(
                        drain=False,
                        drain_handler=taac_thrift.DrainHandler.LOCAL_DRAINER,
                        interfaces=list(drain_interfaces),
                        hard_drain_interfaces=True,
                        description=f"Ensure unrelated links start undrained: {list(drain_interfaces)}",
                        start_traffic=False,
                    ),
                    _set_access_policy_step(
                        dut,
                        restricted_policies,
                        f"Keep {port_a} Restricted and the other IXIA ports Unconstrained",
                        start_traffic=False,
                    ),
                    _access_policy_hardware_check_step(
                        dut,
                        {port_a: "restricted"},
                        f"Validate Restricted Agent and hardware state on {port_a}",
                        start_traffic=False,
                    ),
                    create_run_task_step(
                        task_name="ixia_stop_traffic_and_wait",
                        params_dict={"wait_seconds": 0},
                        description="Stop traffic to reset the measurement window",
                        ixia_needed=True,
                        start_traffic=False,
                    ),
                    create_longevity_step(
                        duration=30,
                        description="Restart traffic and establish the Restricted baseline",
                    ),
                    create_validation_step(
                        point_in_time_checks=stable_state_checks(),
                        stage=taac_thrift.ValidationStage.MID_TEST,
                        description="Validate the Restricted baseline before link drain",
                    ),
                    create_drain_undrain_step(
                        drain=True,
                        drain_handler=taac_thrift.DrainHandler.LOCAL_DRAINER,
                        interfaces=list(drain_interfaces),
                        description=f"Bulk drain unrelated links {list(drain_interfaces)}",
                        hard_drain_interfaces=True,
                        start_traffic=False,
                    ),
                    create_longevity_step(
                        duration=120,
                        description="Hold the drained state for two minutes",
                    ),
                    _access_policy_hardware_check_step(
                        dut,
                        {port_a: "restricted"},
                        f"Verify {port_a} remains Restricted while unrelated links are drained",
                    ),
                    create_validation_step(
                        point_in_time_checks=stable_state_checks(),
                        stage=taac_thrift.ValidationStage.MID_TEST,
                        description="Validate stable state after unrelated link drain",
                    ),
                    create_drain_undrain_step(
                        drain=False,
                        drain_handler=taac_thrift.DrainHandler.LOCAL_DRAINER,
                        interfaces=list(drain_interfaces),
                        description=f"Bulk undrain unrelated links {list(drain_interfaces)}",
                        hard_drain_interfaces=True,
                        start_traffic=False,
                    ),
                    create_longevity_step(
                        duration=120,
                        description="Hold the recovered state for two minutes",
                    ),
                    _access_policy_hardware_check_step(
                        dut,
                        {port_a: "restricted"},
                        f"Verify {port_a} remains Restricted after link undrain",
                    ),
                ]
            )
        ],
    )


def _cpu_stress_playbooks(dut, port_a, port_b, port_c):
    cleanup_steps = _policy_cleanup_steps(dut, port_a, port_b, port_c)
    queue_expectations = {
        "RAW_LLDP_R": ([2], [2], [0, 7]),
        "RAW_LACP_R": ([], [], [0, 2, 7]),
        # Preserve ARP as a strict negative-safety test.  The known device
        # behavior is expected to fail this contract; do not waive the BGP or
        # unexpected CPU-queue signals merely to make the playbook pass.
        "RAW_ARP_R": ([], [], [0, 2, 7]),
        # DHCPv6 stress is intentionally disruptive on this platform. Unlike
        # LLDP, it does not produce a material MID-queue signal; the contract is
        # a BGP flap during stress followed by full recovery after traffic stops.
        "RAW_DHCPV6_R": ([], [], [0, 2, 7]),
        "RAW_BGP_R": ([], [], [0, 2, 7]),
        "RAW_NDP_R": ([7], [7], [0, 2]),
        # Thrift traffic to the device-local fboss10 address is classified into
        # the MID CPU queue on W400C.  A live five-minute run measured ~9.3K
        # packets/s on queue 2, so the shared 1K packets/s floor is deliberately
        # conservative while still rejecting background-only traffic.
        "TCP_SYN_5909_R": ([2], [2], [0, 7]),
        # UDP/5909 is not admitted by the Restricted ACL even though its
        # destination is fboss10. It must increment the ingress ACL-discard
        # counter without reaching any CPU queue.
        "UDP_5909_R": ([], [], [0, 2, 7]),
    }
    expected_bgp_flap_items = {
        "RAW_BGP_R",
        "RAW_DHCPV6_R",
        "RAW_NDP_R",
    }
    restricted_policies = {
        port_a: "RESTRICTED",
        port_b: "UNCONSTRAINED",
        port_c: "UNCONSTRAINED",
    }
    playbooks = []
    for traffic_item, (active, active_discards, inactive) in queue_expectations.items():
        expects_bgp_flap = traffic_item in expected_bgp_flap_items
        playbook_description = (
            f"Run {traffic_item} for five minutes, prove that BGP flapped "
            "during stress, then stop traffic and validate recovery."
            if expects_bgp_flap
            else f"Run {traffic_item} for five minutes and "
            "validate CPU queue/discard signals and BGP stability."
        )
        stage_steps = [
            _set_access_policy_step(
                dut,
                restricted_policies,
                "Prepare Restricted CPU-stress ingress",
                start_traffic=False,
            ),
            create_validation_step(
                point_in_time_checks=[_bgp_established_check()],
                stage=taac_thrift.ValidationStage.PRE_TEST,
                description="Validate BGP baseline before CPU stress",
                start_traffic=False,
            ),
            _access_policy_hardware_check_step(
                dut,
                {port_a: "restricted"},
                "Validate Restricted SW/HW state before CPU stress",
                start_traffic=False,
            ),
        ]
        stage_steps.append(
            create_longevity_step(
                duration=300,
                description=f"Run {traffic_item} for five minutes",
            )
        )
        tx_rate_check = create_ixia_traffic_rate_check(
            thresholds=[
                hc_thrift.TrafficRateThreshold(
                    names=[traffic_item],
                    value=1,
                    threshold_type=hc_thrift.ThresholdType.PERCENT,
                    metric=hc_thrift.TrafficRateMetric.TX_RATE,
                )
            ],
            base_bandwidth_gbps=200,
        )
        acl_discard_check = create_fpf_ods_counter_check(
            entity_desc=dut,
            key_desc=f"fboss.agent.{port_a}.in_acl_discards.sum.60",
            validation_expr=">= 1000000",
            aggregate="max",
            counter_name=f"{port_a} Restricted ACL discards for {traffic_item}",
            check_id=f"{traffic_item.lower()}_restricted_acl_discards",
            min_ods_query_duration=300,
        )
        if expects_bgp_flap:
            stage_steps.extend(
                [
                    create_validation_step(
                        point_in_time_checks=[
                            tx_rate_check,
                            *(
                                [acl_discard_check]
                                if traffic_item == "RAW_BGP_R"
                                else []
                            ),
                            create_bgp_session_establish_check(
                                max_established_sessions=3,
                                retry_count=12,
                                retry_delay_seconds=10,
                                retry_delay_multiplier=1,
                            ),
                        ],
                        description=(
                            f"Confirm {traffic_item} reduced the Established "
                            "BGP session count below four"
                        ),
                    ),
                    create_run_task_step(
                        task_name="ixia_stop_traffic_and_wait",
                        params_dict={"wait_seconds": 300},
                        description=(
                            f"Stop {traffic_item} and hold a five-minute BGP "
                            "recovery window"
                        ),
                        ixia_needed=True,
                        start_traffic=False,
                    ),
                    create_validation_step(
                        point_in_time_checks=[
                            create_bgp_session_establish_check(
                                expected_established_sessions=4,
                                session_restarted_after_jq_var="test_case_start_time",
                                retry_count=12,
                                retry_delay_seconds=10,
                                retry_delay_multiplier=1,
                            ),
                            _unclean_exit_check(dut),
                            create_device_core_dumps_check(),
                        ],
                        stage=taac_thrift.ValidationStage.POST_TEST,
                        description=(
                            "Validate four recovered BGP sessions and fresh "
                            f"uptime while {traffic_item} remains stopped"
                        ),
                        start_traffic=False,
                    ),
                ]
            )
        playbooks.append(
            create_access_policy_playbook(
                name=f"test_access_policy_cpu_{traffic_item.lower()}",
                description=playbook_description,
                device_regexes=[dut],
                traffic_items_to_start=[traffic_item],
                # Policy and a traffic-off BGP baseline are established inside
                # the stage so high-rate traffic cannot start before its ingress
                # mode is programmed.
                prechecks=[],
                postchecks=(
                    []
                    if expects_bgp_flap
                    else [
                        tx_rate_check,
                        _bgp_established_check(),
                        _unclean_exit_check(dut),
                        create_device_core_dumps_check(),
                        *(
                            [acl_discard_check]
                            if traffic_item in {"RAW_BGP_R", "UDP_5909_R"}
                            else []
                        ),
                    ]
                ),
                snapshot_checks=[
                    create_bgp_session_snapshot_check(
                        skip_flap_check=True if expects_bgp_flap else None,
                        skip_uptime_check=True if expects_bgp_flap else None,
                    ),
                    create_core_dumps_snapshot_check(),
                    create_cpu_queue_snapshot_check(
                        active_queues=active,
                        active_discard_queues=active_discards,
                        no_discard_queues=(
                            inactive if traffic_item == "UDP_5909_R" else None
                        ),
                        inactive_queues=inactive,
                        inactive_max_pps_per_queue=dict.fromkeys(inactive, 500),
                        active_min_out_pps_per_queue=dict.fromkeys(
                            active, 500 if expects_bgp_flap else 1000
                        ),
                    ),
                ],
                cleanup_steps=[
                    create_run_task_step(
                        task_name="ixia_stop_traffic_and_wait",
                        params_dict={"wait_seconds": 0},
                        description=f"Leave {traffic_item} stress traffic stopped",
                        ixia_needed=True,
                        start_traffic=False,
                    )
                ]
                + cleanup_steps,
                stages=[create_steps_stage(steps=stage_steps)],
            )
        )
    return playbooks


def _build_test_config(
    name,
    dut,
    dut_mac,
    chassis_ip,
    ports,
    ixia_ports,
    addressing,
    playbook_name,
    platform=None,
    chaos_ports=None,
    chaos_playbook_name=None,
):
    """Assemble one stable-state access-policy TestConfig.

    Args:
        ports: (port_a, port_b, port_c) -- restricted, blocked, unconstrained.
        ixia_ports: chassis-side port for each of `ports`, in the same order.
        addressing: (starting_ip, gateway, mask) for each of `ports`, same order.
    """
    port_a, port_b, port_c = ports
    fboss10_ipv6 = FBOSS10_IPV6_BY_DUT[dut]
    traffic_items = _traffic_items(port_a, port_b, port_c)
    raw_tcp_syn_items = _raw_tcp_syn_traffic_items(port_a, port_b, port_c)
    udp_items = _udp_traffic_items(port_a, port_b, port_c)
    arp_items = _disabled_arp_traffic_items(port_a, port_b, port_c)
    blocked = (
        BLOCKED_TCP_TRAFFIC_ITEMS
        + [item[0] for item in udp_items]
        + [item[0] for item in raw_tcp_syn_items]
    )
    traffic_to_start = (
        [item[0] for item in traffic_items]
        + [item[0] for item in udp_items]
        + [item[0] for item in raw_tcp_syn_items]
    )
    is_w400c = dut == W400C_DUT
    stable_allowed = R_U_DATA_PLANE_TRAFFIC_ITEMS
    stable_blocked = []
    return taac_thrift.TestConfig(
        name=name,
        basset_pool="dne.test",
        ignore_circuit_fbnet_status=True,
        # Traffic items are part of this test's contract, including the disabled
        # CPU-control-plane items retained for manual activation.  Avoid loading a
        # topology-only cache that may predate those traffic-item definitions.
        ixia_config_cache=taac_thrift.IxiaConfigCache(enabled=False),
        # This access-policy config validates forwarding with explicit IXIA
        # traffic health checks.  Avoid the setup-time protocol-stat snapshot:
        # it uses the chassis-global DefaultSnapshotSettings resource and can
        # contend with other session readers even though protocols started.
        skip_ixia_protocol_verification=True,
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
        # Access policy can administratively disable an IXIA-facing port.  It
        # must be cleared before IXIA protocol readiness, which runs before any
        # playbook stage.  The typed COOP API performs Agent config activation.
        setup_tasks=[
            create_run_task(
                task_name="coop_set_access_policy",
                params_dict={
                    "hostname": dut,
                    "policies": {
                        port_a: "UNCONSTRAINED",
                        port_b: "UNCONSTRAINED",
                        port_c: "UNCONSTRAINED",
                    },
                },
                ixia_needed=False,
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
            _raw_traffic_item(
                item_name,
                source,
                destination,
                _raw_tcp_syn_headers(
                    destination_port=5909,
                    source_port=source_port,
                    dut_mac=dut_mac,
                    destination_ipv6=fboss10_ipv6,
                ),
                1,
                False,
                400,
                dut,
            )
            for item_name, source, destination, source_port in (
                ("TCP_SYN_5909_R", port_a, port_b, 40018),
                ("TCP_SYN_5909_B", port_b, port_c, 40019),
                ("TCP_SYN_5909_U", port_c, port_a, 40020),
            )
        ]
        + [
            _raw_traffic_item(
                item_name,
                source,
                destination,
                _raw_udp_headers(
                    destination_port=5909,
                    source_port=source_port,
                    dut_mac=dut_mac,
                    destination_ipv6=fboss10_ipv6,
                ),
                1,
                False,
                400,
                dut,
            )
            for item_name, source, destination, source_port in (
                ("UDP_5909_R", port_a, port_b, 40021),
                ("UDP_5909_B", port_b, port_c, 40022),
                ("UDP_5909_U", port_c, port_a, 40023),
            )
        ]
        + [
            _raw_cpu_traffic_item(
                item_name,
                source,
                destination,
                headers,
                allow_self_destined,
                dut,
            )
            for (
                item_name,
                source,
                destination,
                headers,
                allow_self_destined,
            ) in _disabled_cpu_traffic_items(port_a, port_b, port_c)
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
                    "Stable-state validation of the all-Unconstrained R/U "
                    "traffic baseline. No DUT state is changed."
                ),
                device_regexes=[dut],
                # Traffic sourced from or destined to a Blocked port is omitted:
                # that port is administratively disabled and IXIA cannot resolve
                # its endpoint.  The traffic definitions remain available for
                # targeted/manual use.
                traffic_items_to_start=R_U_DATA_PLANE_TRAFFIC_ITEMS,
                prechecks=[
                    _unclean_exit_check(dut),
                    _traffic_loss_check(
                        stable_allowed,
                        stable_blocked,
                    ),
                ],
                postchecks=[
                    _unclean_exit_check(dut),
                    _traffic_loss_check(
                        stable_allowed,
                        stable_blocked,
                    ),
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
        ]
        + (
            [
                create_hatch_chaos_soak_playbook(
                    name=chaos_playbook_name,
                    device_regexes=[dut],
                    traffic_items_to_start=traffic_to_start,
                    stages=[
                        _chaos_start_stage(dut, platform, chaos_ports),
                        create_longevity_stage(
                            duration=CHAOS_SOAK_SECONDS, stage_id="chaos_soak"
                        ),
                        _chaos_stop_stage(dut),
                    ],
                    prechecks=[
                        _unclean_exit_check(),
                        # NOT the stable-state 3/14 split -- see
                        # CHAOS_*_TRAFFIC_ITEMS: the soak holds Port B
                        # Unconstrained, so the static expectation is 5/12.
                        _traffic_loss_check(
                            CHAOS_ALLOWED_TRAFFIC_ITEMS, CHAOS_BLOCKED_TRAFFIC_ITEMS
                        ),
                    ],
                    postchecks=[
                        _unclean_exit_check(),
                        _traffic_loss_check(
                            CHAOS_ALLOWED_TRAFFIC_ITEMS, CHAOS_BLOCKED_TRAFFIC_ITEMS
                        ),
                        create_device_core_dumps_check(),
                    ],
                    snapshot_checks=[
                        create_core_dumps_snapshot_check(),
                        # fsw004 flaps independently of anything this test does,
                        # so its peers must not be able to fail the run.
                        # Flap/uptime signals do not apply either -- the daemon
                        # restarts the agent ~190 times.
                        create_bgp_session_snapshot_check(
                            parent_prefixes_to_ignore=BGP_PEER_PREFIXES_TO_IGNORE,
                            skip_flap_check=True,
                            skip_uptime_check=True,
                        ),
                    ],
                )
            ]
            if chaos_ports
            else []
        )
        + (
            _transition_playbooks(dut, port_a, port_b, port_c)
            + _restricted_port_flap_playbooks(dut, port_a, port_b, port_c)
            + _speed_flip_playbooks(dut, port_a, port_b, port_c, SPEED_FLIP_PORT)
            + [_link_down_policy_transition_playbook(dut, port_a, port_b, port_c)]
            + [
                _unrelated_link_drain_playbook(
                    dut,
                    port_a,
                    port_b,
                    port_c,
                    UNRELATED_LINK_DRAIN_PORTS,
                )
            ]
            + _cpu_stress_playbooks(dut, port_a, port_b, port_c)
            if is_w400c
            else []
        ),
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
    platform="W400C",
    chaos_ports=W400C_CHAOS_PORTS,
    chaos_playbook_name=CHAOS_PLAYBOOK_NAME,
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
    platform="W400",
    chaos_ports=W400_CHAOS_PORTS,
    chaos_playbook_name=W400_CHAOS_PLAYBOOK_NAME,
)
