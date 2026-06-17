# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import functools
import json
import typing as t
from dataclasses import dataclass, field
from enum import Enum

from ixia.ixia import types as ixia_types
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types


MAC_SOFT_LIMIT = 5300
ARP_SOFT_LIMIT = 1280
NDP_SOFT_LIMIT = 4000
MAX_ECMP_MEMBER_COUNT = 16000
MAX_ECMP_GROUP_COUNT = 1536

# BGP++ routes are installed with admin distance of 200
BGP_PLUS_PLUS_ADMIN_DISTANCE = 200

# Open/R routes are installed with admin distance of 10
OPENR_ADMIN_DISTANCE = 10

DNE_LOG_DIR: str = "/var/facebook/dne"
RSYSLOG_AGENT_FILE: str = "/etc/rsyslog.d/00-agent-log.conf"
FBOSS_LOG_DIR: str = "/var/facebook/logs/fboss"

TEST_AS_A_CONFIG_NAME: str = "taac"

TAAC_HEALTH_CHECK_SCUBA_TABLE = "taac_health_checks"
TAAC_UTP_RESULTS_SCUBA_TABLE: str = "taac_utp_results"
TAAC_EBB_BGP_PLUS_PLUS_SCABLE_TABLE = "ebb_bgp_plus_plus_test_results"

FAILED_HC_STATUSES: t.List[hc_types.HealthCheckStatus] = [
    hc_types.HealthCheckStatus.FAIL,
    hc_types.HealthCheckStatus.ERROR,
]

ISOLATE_TEST_BED_CONNECTIVITY_PATCHER_NAME: str = "isolate_test_bed_connectivity"
TAAC_TEST_CONFIG_CONFIGERATOR_PATH: str = "neteng/taac/test_configs/{test_config_name}"


OS_TO_DEVICE_OS_TYPE_MAP: t.Dict[str, taac_types.DeviceOsType] = {
    "FBOSS": taac_types.DeviceOsType.FBOSS,
    "EOS": taac_types.DeviceOsType.ARISTA_OS,
    "ARISTA_OS": taac_types.DeviceOsType.ARISTA_OS,
    "CISCO_OS": taac_types.DeviceOsType.CISCO,
    "IOSXR": taac_types.DeviceOsType.IOSXR,
}


class FbossPackage(Enum):
    """
    Possible values used by the NetPipelineService to represent various packages:
    - fboss_agent
    - fboss_agent_config_disruptive
    - fboss_agent_config
    - fboss_bgp
    - fboss_bgp_config
    - fboss_bgp_config_disruptive
    - fboss_asic_sdk
    - fboss_kernel
    - openr
    - fboss_openr_config
    """

    AGENT = "fboss_agent"
    AGENT_CSCO = "fboss_agent_csco"
    BGP = "fboss_bgp"
    QSFP = "fboss_qsfp_service"
    OPENR = "openr"
    FSDB = "fboss_fsdb"
    AGENT_CONFIG = "fboss_agent_config"
    AGENT_CONFIG_DISRUPTIVE = "fboss_agent_config_disruptive"
    BGP_CONFIG = "fboss_bgp_config"
    BGP_CONFIG_DISRUPTIVE = "fboss_bgp_config_disruptive"
    OPENR_CONFIG = "fboss_openr_config"


class ChurnMode(Enum):
    ENABLE_SESSION_FLAP = 1
    DISABLE_SESSION_FLAP = 2
    ENABLE_PREFIX_FLAP = 3
    DISABLE_PREFIX_FLAP = 4


@dataclass
class HealthCheckResult:
    start_time: str
    end_time: str
    hostname: str
    role: str
    platform: str
    test_name: str
    check_name: str
    check_status: hc_types.HealthCheckStatus
    message: str


@dataclass
class Attributes:
    pass


@dataclass
class BgpSessionConfig(Attributes):
    uplink_bgp_peers: int
    downlink_bgp_peers: int


class BgpPathScales(Enum):
    PATH_SCALE_1_POINT_25_MILLION = 1250000
    PATH_SCALE_2_MILLION = 2000000
    PATH_SCALE_2_POINT_75_MILLION = 2750000
    PATH_SCALE_3_POINT_5_MILLION = 3500000


class DCType(Enum):
    DCTYPE_1 = 1
    DCTYPE_F = 2
    DCTYPE_ILD_COMPACT = 3
    DCTYPE_ILD_STANDARD = 4


class BgpSessionKeys(Enum):
    UPLINK = "uplink_bgp_sessions"
    DOWNLINK = "downlink_bgp_sessions"


@dataclass
class TestDevice:
    name: str
    attributes: taac_types.SwitchAttributes
    interfaces: t.List[taac_types.TestInterface] = field(default_factory=list)
    ixia_interfaces: t.List[taac_types.TestInterface] = field(default_factory=list)
    unused_interfaces: t.List[str] = field(default_factory=list)

    @property
    def neighbors(self) -> t.List[str]:
        return list(
            {
                interface.neighbor_switch_name
                for interface in self.interfaces
                if interface.neighbor_switch_name
            }
        )

    @property
    def all_interfaces(self) -> t.List[taac_types.TestInterface]:
        return self.interfaces + self.ixia_interfaces

    def get_interface_by_name(self, name: str) -> taac_types.TestInterface:
        for interface in self.all_interfaces:
            if interface.interface_name == name:
                return interface
        raise ValueError(f"Interface '{name}' not found on device '{self.name}'")

    def __hash__(self) -> int:
        return hash(self.name)


@dataclass
class TestTopology:
    devices: t.List[TestDevice] = field(default_factory=list)

    _name_to_device: t.Dict[str, TestDevice] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self._name_to_device = {device.name: device for device in self.devices}

    def get_device_by_name(self, name: str) -> TestDevice:
        try:
            return self._name_to_device[name]
        except KeyError:
            raise ValueError(f"Device '{name}' not found in topology")

    def get_devices_by_role(self, role: str) -> t.List[TestDevice]:
        return [device for device in self.devices if device.attributes.role == role]

    def get_device_neighbors(self, name: str) -> t.List[TestDevice]:
        device = self.get_device_by_name(name)
        return list(
            {self.get_device_by_name(neighbor) for neighbor in device.neighbors}
        )

    def get_interface_by_name(self, name: str) -> taac_types.TestInterface:
        device_name, interface_name = name.split(":")
        device = self.get_device_by_name(device_name)
        return device.get_interface_by_name(interface_name)

    @functools.cached_property
    def device_names(self) -> t.List[str]:
        return [device.name for device in self.devices]


@dataclass
class TestResult:
    hostnames: str
    test_case_name: str
    start_time: str
    end_time: str
    platforms: t.Optional[str] = None
    check_name: t.Optional[str] = None
    check_stage: t.Optional[str] = None
    test_status: t.Optional[str] = None
    message: t.Optional[str] = None


@dataclass
class PeriodicCheckResult:
    name: str
    status: hc_types.HealthCheckStatus
    message: str


CUBISM_DASH_DIVE_URL: str = "https://www.internalfb.com/canvas/dive/cubism?"
CUBISM_OVERVIEW_URL: str = "https://www.internalfb.com/intern/cubism/{group_name}/?"


IXIA_LLDP_PEERS: t.Dict[str, str] = {
    "ares1-my23040002": "ixia03.netcastle.ash6",
    "ares1-my24280007": "ixia06.netcastle.ash6",
    "ares1-my23070008": "ixia07.netcastle.ash6",
    "ares1-my24290003": "ixia08.netcastle.ash6",
    "ares1-my24520006": "ixia09.netcastle.ash6",
    "ares1-my24520012": "ixia10.netcastle.ash6",
    "ares1-my23470002": "ixia05.netcastle.ash7",
    "ares1-my23060002": "ixia05.netcastle.snc1",
    "ares1-my23340001": "ixia06.netcastle.snc1",
    "ares1-my23360007": "ixia07.netcastle.snc1",
    "ares1-my23110019": "ixia09.netcastle.snc1",
    "ares1-my24200002": "ixia10.netcastle.snc1",
    "ares1-my24290004": "ixia11.netcastle.snc1",
    "ares1-my23320001": "ixia12.netcastle.snc1",
    "ares1-my24440003": "ixia13.netcastle.snc1",
    "ares1-my24440005": "ixia14.netcastle.snc1",
    "ares1-my24410008": "ixia15.netcastle.snc1",
    "ares1-my24470002": "ixia16.netcastle.snc1",
    "ares1-my24520014": "ixia17.netcastle.snc1",
    "ares1-my22510003": "ixia04.netcastle.snc1",
    "xgs12-g0860052": "ixia02.dne.snc1",
}


#############################################################
#                  Arista Daemon Control                   #
#############################################################

# Default execution scripts for Arista daemon control
ARISTA_DAEMON_EXEC_SCRIPTS: t.Dict[str, str] = {
    "Bgp": "/usr/sbin/run_bgpcpp.sh",
    "FibAgent": "/usr/bin/AristaFibAgent --admin_distance=10 --net_acl_checker_module_enable --net_acl_checker_module_enforce=false --net_static_file_acl=/usr/facebook/thrift_acls/FibAgent.json --undefok=net_service_identity,net_static_file_acl,net_acl_checker_module_enable,net_acl_checker_module_enforce,net_auth_checker_kill_switch_file --use_agent_config=1 --net_service_identity=FibAgent_lab",
    "FibAgentBgp": "/usr/bin/AristaFibAgent --agent_config_path=/mnt/fb/agent_configs/fib_agent_bgp.conf --admin_distance=10 --net_acl_checker_module_enable --net_acl_checker_module_enforce=false --net_static_file_acl=/usr/facebook/thrift_acls/FibAgent.json --undefok=net_service_identity,net_static_file_acl,net_acl_checker_module_enable,net_acl_checker_module_enforce,net_auth_checker_kill_switch_file --use_agent_config=1 --net_service_identity=FibAgent_lab",
    "FibBgpGrpc": "/usr/bin/EosSdkRpc --listen 0.0.0.0:9545 --nobfd",
    "FibGrpc": "/usr/bin/EosSdkRpc --listen 0.0.0.0:9544 --nobfd",
    "RouteGrpc": "/usr/bin/EosSdkRpc --listen 0.0.0.0:9547 --nobfd",
    "Openr": "/usr/sbin/run_openr.sh",
    "BgpTcpdump": '/bin/sh -c \\"stdbuf -oL /sbin/tcpdump -i {interface} -n -s 0 port {bgp_port} -v | stdbuf -oL grep -E -B 2 \\\\\\"{message_type}\\\\\\" | tee {capture_file}\\"',
}

# Arista BGP++ daemon mappings for EOS devices
# Maps service names to their actual process names and log file patterns
ARISTA_BGP_PLUS_PLUS_DAEMON_MAPPINGS: t.Dict[str, t.Dict[str, t.Any]] = {
    "Bgp": {
        "processes": ["bgpcpp"],
        "log_pattern": "Bgp-{pid}",
    },
    "Fib": {
        "processes": ["AristaFibAgent"],
        "log_pattern": "FibAgentBgp-{pid}",
    },
}


#############################################################
#                  Traffic Generator                        #
#############################################################


LLDP_DEST_MULTICAST_MAC: str = "01:80:c2:00:00:0e"
LACP_DEST_MULTICAST_MAC: str = "01:80:C2:00:00:02"
# Random mac address, not specific to any particular traffic item/ixia port or device
DEFAULT_SRC_MAC_ADDRESS: str = "00:e1:01:00:00:01"
ROGUE_SRC_MAC_ADDRESS: str = "00:f1:01:00:00:01"

# Broadcast mac address
BROADCAST_DST_MAC_ADDRESS: str = "ff:ff:ff:ff:ff:ff"

# NDP (Neighbor Discovery Protocol) Constants
# Solicited-node multicast MAC prefix (33:33:ff:XX:XX:XX)
NDP_SOLICITED_NODE_MULTICAST_MAC: str = "33:33:ff:00:00:01"
# All-nodes multicast MAC (33:33:00:00:00:01) for NA
NDP_ALL_NODES_MULTICAST_MAC: str = "33:33:00:00:00:01"
# All-routers multicast MAC (33:33:00:00:00:02) for RS
NDP_ALL_ROUTERS_MULTICAST_MAC: str = "33:33:00:00:00:02"

# NDP Multicast IPv6 Addresses
# Solicited-node multicast address prefix
NDP_SOLICITED_NODE_MULTICAST_IPV6: str = "ff02::1:ff00:1"
# All-nodes multicast address (ff02::1)
NDP_ALL_NODES_MULTICAST_IPV6: str = "ff02::1"
# All-routers multicast address (ff02::2)
NDP_ALL_ROUTERS_MULTICAST_IPV6: str = "ff02::2"

# Link-local address prefix for NDP testing
NDP_IXIA_LINK_LOCAL_IPV6: str = "fe80::e1:1:0:1"

# ICMPv4 Message Types (RFC 792)
ICMPV4_TYPE_ECHO_REPLY: int = 0  # Echo Reply
ICMPV4_TYPE_DEST_UNREACHABLE: int = 3  # Destination Unreachable
ICMPV4_TYPE_ECHO_REQUEST: int = 8  # Echo Request
ICMPV4_TYPE_TIME_EXCEEDED: int = 11  # Time Exceeded (TTL Exceeded)

# ICMPv6 NDP Message Types (RFC 4861)
ICMPV6_TYPE_NS: int = 135  # Neighbor Solicitation
ICMPV6_TYPE_NA: int = 136  # Neighbor Advertisement
ICMPV6_TYPE_RS: int = 133  # Router Solicitation
ICMPV6_TYPE_RA: int = 134  # Router Advertisement

# ICMPv6 Non-NDP Message Types (RFC 4443)
ICMPV6_TYPE_DEST_UNREACHABLE: int = 1  # Destination Unreachable
ICMPV6_TYPE_PACKET_TOO_BIG: int = 2  # Packet Too Big
ICMPV6_TYPE_TIME_EXCEEDED: int = 3  # Time Exceeded
ICMPV6_TYPE_ECHO_REQUEST: int = 128  # Echo Request
ICMPV6_TYPE_ECHO_REPLY: int = 129  # Echo Reply

# DSCP 48 = Traffic Class 192 (48 << 2 for ECN bits)
NDP_DSCP_48_TRAFFIC_CLASS: int = 192


# BGP Protocol Constants
class BgpMessageType(Enum):
    """BGP message types as defined in RFC 4271."""

    OPEN = 1
    UPDATE = 2
    NOTIFICATION = 3
    KEEPALIVE = 4
    ROUTE_REFRESH = 5


class BgpPlusPlusProfile(Enum):
    """BGP++ test profile types for route file selection."""

    BGP_PLUS_PLUS_WITHOUT_OPEN_R = "bgp_plus_plus_without_open_r"
    BGP_PLUS_PLUS_WITH_OPEN_R = "bgp_plus_plus_with_open_r"


# Centralized BGP message type mapping - ONLY standard BGP message types 1-5
# All other message types will be ignored in analysis
BGP_MESSAGE_TYPES: t.Dict[int, str] = {
    BgpMessageType.OPEN.value: "OPEN",  # Type 1
    BgpMessageType.UPDATE.value: "UPDATE",  # Type 2
    BgpMessageType.NOTIFICATION.value: "NOTIFICATION",  # Type 3
    BgpMessageType.KEEPALIVE.value: "KEEPALIVE",  # Type 4
    BgpMessageType.ROUTE_REFRESH.value: "ROUTE-REFRESH",  # Type 5
}

BGP_PORT: str = "179"
RDMA_PORT: str = "4791"
DHCPV6_MULTICAST_ADDR: str = "fe80::a00:27ff:fefe:8f95"
DHCPV6_SERVER_MULTICAST_ADDR: str = "ff02::1:2"
DHCPV6_SERVER_PORT: str = "547"
DHCPV6_RELAY_PORT: str = "546"
DHCPV4_BROADCAST_ADDR: str = "255.255.255.255"
DHCPV4_CLIENT_PORT: str = "68"
DHCPV4_SERVER_PORT: str = "67"
# DHCP Relay/Helper address from agent config (dhcpRelayAddressV4)
DHCPV4_RELAY_SERVER_ADDR: str = "10.127.255.67"


IXIA_PREFIX_STEP_IP_V6 = "0:1:0:0:0:0:0:0"
IXIA_PREFIX_STEP_IP_V4 = "0.0.0.1"

LABS_WITH_INBAND_CONNECTIVITY: t.List[str] = ["snc1"]

DEFAULT_PREFIX_LEN_V4 = 24
DEFAULT_PREFIX_LEN_V6 = 64
IXIA_STARTING_IP_INCREMENT_V6 = "0:0:0:0:0:0:0:1"
IXIA_GATEWAY_IP_INCREMENT_V6 = "0:0:0:0:0:0:0:0"
IXIA_STARTING_IP_INCREMENT_V4 = "0.0.0.1"
IXIA_GATEWAY_IP_INCREMENT_V4 = "0.0.0.0"
IXIA_PREFIX_STEP_IP_V6 = "0:1:0:0:0:0:0:0"
IXIA_PREFIX_STEP_IP_V4 = "0.0.0.1"

DEVICE_ROLE_IXIA_ASN_MAP = {
    # For SSW roles, Ixia take the ASN of FSW
    "SSW": 65403,
    # For FSW roles, Ixia takes the ASN of SSW
    "FSW": 65301,
    # For FADU roles, Ixia takes the ASN of SSW
    "FADU": 64903,
    # For RSW role, Ixia takes the ASN of Hosts
    "RSW": 65000,
    # For FAUU role, Ixia takes the ASN of Hosts
    "FAUU": 64964,
}


class Gigabyte(Enum):
    """
    Enum representing different gigabyte values in bytes.
    """

    GIG_2 = 2 * (1024**3)
    GIG_4 = 4 * (1024**3)
    GIG_4_POINT_1 = int(4.1 * (1024**3))
    GIG_4_POINT_2 = int(4.2 * (1024**3))
    GIG_4_POINT_3 = int(4.3 * (1024**3))
    GIG_4_POINT_5 = int(4.5 * (1024**3))
    GIG_4_POINT_6 = int(4.6 * (1024**3))
    GIG_4_POINT_7 = int(4.7 * (1024**3))
    GIG_4_POINT_8 = int(4.8 * (1024**3))
    GIG_5 = 5 * (1024**3)
    GIG_6 = 6 * (1024**3)
    GIG_7 = 7 * (1024**3)
    GIG_8 = 8 * (1024**3)
    GIG_9 = 9 * (1024**3)
    GIG_10 = 10 * (1024**3)


# CPU core counts for hardware platforms (logical CPUs including hyperthreading)
ARISTA_7808_CPU_COUNT = 12


DEFAULT_TCP_PACKER_HEADER: taac_types.PacketHeader = taac_types.PacketHeader(
    query=ixia_types.Query(regex="^TCP$"),
    append_to_query=ixia_types.Query(regex="^IP.*"),
    fields=[
        taac_types.Field(
            query=ixia_types.Query(regex="Source-Port"),
            attrs_json=json.dumps(
                {
                    "Auto": False,
                    "ValueType": "increment",
                    "StartValue": 10000,
                    "StepValue": 1,
                    "CountValue": 10000,
                }
            ),
        ),
        taac_types.Field(
            query=ixia_types.Query(regex="Dest-Port"),
            attrs_json=json.dumps(
                {
                    "Auto": False,
                    "ValueType": "increment",
                    "StartValue": 20000,
                    "StepValue": 1,
                    "CountValue": 10000,
                }
            ),
        ),
    ],
)


@dataclass
class L1ConfigOverride:
    endpoints: t.List[str]
    l1_config: ixia_types.L1Config


@dataclass
class LldpInfo:
    local_interface: str
    neighbor_hostname: str
    neighbor_platform: str
    neighbor_interface: str
    parent_interface: t.Optional[str] = None
    neighbor_parent_interface: t.Optional[str] = None


# Log lines to grep for fboss log file
# https://fburl.com/code/w9ue746c
VALIDATE_ECMP_GROUP_OVERFLOW = "Invalid route update"
VALIDATE_ARP_OVERFLOW = "ARP table overflow"
ROUTE_UPDATE_TIME = "Update state took"
ROUTE_UPDATE_PREFIX_COUNT = "Routes added:"
CURRENT_ECMP_RESOURCE_LIMITS = "ECMP resource limits"
UNCLEAN_EXIT = "SIGABRT"
NDP_ARP_OVERFLOW = "Failed to program neighbor entry"
AGENT_BOOT_TYPE = "Boot type:"
AGENT_SIGNAL_15_RECEIVED = "Received exit signal 15"
AGENT_EXIT_CODE = "Agent exited with exit code"
BGP_STATE_TRANSITION = "state transition: ESTABLISHED"
FSDB_NBR_DISAPPER = "FSDB: neighbor disappeared:"
NDP_PROGRAMMING_ENTRY = "ManagedNeigbhor::createObject"
BGP_SYNCING_ROUTES_TO_AGENT = "Start syncFib..."  # seen in bgpg.log
BGP_DETECTING_AGENT_RESTART = "Detect agent restart"
BGPD_CODE_SUBCODE_FROM_PEER = "Notification from peer"
BGPD_GR_HELPER_MODE = "enter GR helper"
FSDB_SIGNATURE_AFTER_RESTART = "LoggingStatsPublisher::publishStats started"
#############################################################
#                  Custom Exceptions                        #
#############################################################


#############################################################
#                  Open/R Route Configuration               #
#############################################################

# Default Open/R route configuration constants
DEFAULT_OPENR_START_IPV4S = [
    "20.164.28.10",
    "20.165.28.10",
    "20.166.28.10",
    "20.167.28.10",
]

DEFAULT_OPENR_START_IPV6S = [
    "2401:db00:e80d:11:9::10",
    "2401:db00:e80d:11:10::10",
    "2401:db00:e80d:11:11::10",
    "2401:db00:e80d:11:12::10",
]

DEFAULT_LOCAL_LINK = {
    "ipv4": "10.131.98.236",
    "ipv6": "fe80::eba:a7f:fd01",
    "ifName": "po100212",
    "weight": 0,
    "metric": 10,
}

DEFAULT_OTHER_LINK = {
    "ipv4": "10.131.98.237",
    "ipv6": "fe80::eba:a7f:fd00",
    "ifName": "po100212",
    "weight": 0,
    "metric": 10,
}


#############################################################
#                  Custom Exceptions                        #
#############################################################


class OpenRRouteAction(Enum):
    """Different actions that can be taken on the routes."""

    INJECT = "inject"
    DELETE = "delete"
    CHURN = "churn"
    METRIC_OSCILLATION = "metric_oscillation"
    UDATE_METRIC = "update"


class ProvisioningOperation(Enum):
    """Device provisioning operation types."""

    PROVISION = "provision"
    UNPROVISION = "unprovision"


class TestCaseFailure(Exception):
    def __init__(self, message: str = "", is_postcheck_failure: bool = False) -> None:
        super().__init__(message)
        self.is_postcheck_failure = is_postcheck_failure


class WaitException(Exception):
    pass


class WaitTimeoutException(Exception):
    pass


@dataclass
class IxiaEndpointInfo:
    """
    Tracks a connection from an IXIA asset to a lab device.
    Used in ixia_utils and traffic_generator.
    """

    ixia_chassis_ip: str
    ixia_slot_num: str
    ixia_port_num: str
    remote_device_name: str
    remote_intf_name: str
    ixia_hostname: t.Optional[str] = None
    ixia_starting_ip: t.Optional[str] = None
    remote_intf_prefix: t.Optional[t.Tuple[str, int]] = None
    is_logical_port: bool = False

    def __eq__(self, other):
        if not isinstance(other, IxiaEndpointInfo):
            return False
        return (
            self.remote_device_name == other.remote_device_name
            and self.remote_intf_name == other.remote_intf_name
        )

    def __hash__(self):
        return hash((self.remote_device_name, self.remote_intf_name))
