#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import ipaddress
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Union

from neteng.test_infra.ixia.ixnetwork_restpy.ixia_config_thrift import (
    types as ixia_config_types,
)
from neteng.test_infra.ixia.ixnetwork_restpy.ixia_config_thrift.types import (
    RAW_TRAFFIC_TYPE_MAP,
)


@dataclass
class Nexthops:
    NextHopId: int
    Metadata: int


CHECK_CURRENT_IS_DIRTY_SERVICES = ["agent", "openr", "bgpcpp", "qsfp"]


class AristaSystemAgentPrepend(Enum):
    STRATA = "Strata"
    SAND = "SandFapNi"


class AristaRoutingAgents(Enum):
    GATED = "Rib"
    MULTI_AGENT = "Bgp"


class AristaFixedSystemAgent(Enum):
    STRATA_FIXEDSYSTEM = "Strata-FixedSystem"
    SAND_FIXEDSYSTEM = "SandFapNi-FixedSystem"


class AristaL3ForwardingAgent(Enum):
    STRATA = "StrataL3"
    SAND = "SandL3Unicast"


class AristaFabricAgentPrepend(Enum):
    SAND = "SandFabric"
    STRATA = "Strata"


class AristaSwitchcardAgentPrepend(Enum):
    STRATA = "Strata"


class AristaModelNames(Enum):
    DCS7368 = "7368"
    DCS7808 = "7808"
    DCS7812 = "7812"
    DCS7816 = "7816"
    DCS7304 = "7304"


class AristaStrataModel(Enum):
    DCS7368 = "7368"
    DCS7304 = "7304"


class AristaSandModel(Enum):
    DCS7808 = "7808"
    DCS7812 = "7812"
    DCS7816 = "7816"


class AristaSingleChipModular(Enum):
    DCS7368 = "7368"


class AristaPlatformType(Enum):
    STRATA = "Strata"
    SAND = "SAND"


class AristaCriticalAgents(Enum):
    # If operating in routing protocol mode ribd
    SYSTEM_AGENT = "DummySystemAgent"
    L3_FORWARDING_AGENT = "DummyForwardingAgent"
    FABRIC_AGENT = "DummyFabricAgent"
    # If operating in routing protocol mode multi-agent
    ROUTING_AGENT = "Rib"
    EBRA = "Ebra"
    XCVR_AGENT = "XcvrAgent"
    ARISTA_CUSTOM_AGENTS = "CustomAgents"


# Critical Sand agents to monitor for unexpected restarts.
# Per-linecard (SandFapNi-LinecardX) and per-fabric (SandFabric-FabricY)
# agents are discovered dynamically via the driver at runtime.
ARISTA_CRITICAL_SAND_AGENTS = [
    # Hardware writers
    "AsicResourceMgrSand-Default",
    "AsicResourceMgrSand-Route",
    "AsicResourceMgrSand-Priority",
    # Sand platform agents
    "SandL3Ni",
    "SandRoute",
    "SandAdj",
    "SandTunnelNi",
    "SandMpls",
    "SandSystemAcl",
    "SandPolicyPbr",
    "SandPolicyQos",
    "SandPolicyAcl",
    # Monitoring/LAG
    "SandDanz",
    "SandLag",
    "Lag",
    # Other critical agents
    "SandTm",
    "SandLanz",
    "Snmp",
    "XcvrAgent",
]


class ConfigPatcherAction(Enum):
    REGISTER = 0
    UNREGISTER = 1


class OlympicQoSClass(Enum):
    """
    Enums for the Olympic QoS classes
    """

    BRONZE = 4
    SILVER = 0
    GOLD = 1
    ICP = 6
    NC = 7


class BgpPeerAction(Enum):
    # Enables BGP session on intf/peer
    ENABLE = 0

    # Shutdown BGP session on intf/peer
    SHUT = 1

    # Restart BGP session on intf/peer
    RESTART = 2


class BgpConvergencePhase(Enum):
    INGRESS_PROCESSING_TIME = 0
    RIB_COMPUTATION_TIME = 1
    FIB_SYNC_TIME = 2
    EGRESS_PROCESSING_TIME = 3


#####################
# GENERIC CONSTANTS #
#####################


class DeviceDrainState(Enum):
    DRAINED = 0
    UNDRAINED = 1
    NON_DRAINABLE = 2


class DrainScope(Enum):
    DEVICE = 0
    LINECARD = 1
    INTERFACE = 2


class DrainType(Enum):
    DRAIN = 0
    UNDRAIN = 1


DNE_LOGGER_NAME = "neteng.test_infra.dne"

# https://fburl.com/serviceusers/dtrhq49l
DNE_TEST_REGRESSION_FBID = 89002005311231
DRAIN_UNDRAIN_TEST_TASK = "T30333506"  # Unified Drainer Task
DRAIN_UNDRAIN_LOCAL_DRAINER_TEST_TASK = "T181574747"

# ECMP HASH CHECK CONSTANTS

EGRESS_TRAFFIC_STATS_HEADER = [
    "HOSTNAME",
    "ECMP_PATH",
    "NUM_OF_ECMP_PATHS",
    "INTERFACE_NAME",
    "BASELINE_RATE",
    "ACTUAL_RATE",
    "RATE_DELTA",
]


# The maximum egress traffic rate cannot exceed the mean by more than 10%
P_MAX_THRESHOLD = 1.4

# The minimum egress traffic rate cannot be lesser than the mean by
# anything more than 10%
P_MIN_THRESHOLD = 1.4

# The normalized standard deviation from the mean should be less than 12 %
COEFF_OF_VAR_THRESHOLD = 14  # in %

ECMP_HASH_TABLE_HEADER = [
    "HOSTNAME",
    "AVG INTF UTIL",
    "HASH_METRICS",
    "OUTLIERS",
    "EGRESS_TRAFFIC_DISTRIBUTION",
]

HW_AGENT_BASE_PORT: int = 5931
HW_SW_AGENT_TIMEOUT: int = 10
DEFAULT_TIMEOUT_HW_AGENT = 10000  # milliseconds


class CpuQueue(Enum):
    HIGH = "HIGH"
    MID = "MID"
    LOW = "LOW"


@dataclass
class RawTrafficItemInfo:
    traffic_type: ixia_config_types.RawTrafficType
    cpu_queue: CpuQueue
    traffic_rate: int = 300


HOST_BOUND_CPU_TRAFFIC: Dict[str, RawTrafficItemInfo] = {
    RAW_TRAFFIC_TYPE_MAP[
        ixia_config_types.RawTrafficType.TCP_DIR_CONN_HOST
    ]: RawTrafficItemInfo(
        traffic_type=ixia_config_types.RawTrafficType.TCP_DIR_CONN_HOST,
        cpu_queue=CpuQueue.LOW,
        traffic_rate=2000,
    ),
    RAW_TRAFFIC_TYPE_MAP[
        ixia_config_types.RawTrafficType.TCP_REMOTE_SUBNET
    ]: RawTrafficItemInfo(
        traffic_type=ixia_config_types.RawTrafficType.TCP_REMOTE_SUBNET,
        cpu_queue=CpuQueue.MID,
        traffic_rate=2000,
    ),
}
CPU_BOUND_TRAFFIC: Dict[str, RawTrafficItemInfo] = {
    RAW_TRAFFIC_TYPE_MAP[ixia_config_types.RawTrafficType.BGP_CP]: RawTrafficItemInfo(
        traffic_type=ixia_config_types.RawTrafficType.BGP_CP,
        cpu_queue=CpuQueue.HIGH,
        traffic_rate=300,
    ),
    RAW_TRAFFIC_TYPE_MAP[
        ixia_config_types.RawTrafficType.ICMPV6_REQ
    ]: RawTrafficItemInfo(
        traffic_type=ixia_config_types.RawTrafficType.ICMPV6_REQ,
        cpu_queue=CpuQueue.MID,
        traffic_rate=200,
    ),
    RAW_TRAFFIC_TYPE_MAP[ixia_config_types.RawTrafficType.LLDP]: RawTrafficItemInfo(
        traffic_type=ixia_config_types.RawTrafficType.LLDP,
        cpu_queue=CpuQueue.MID,
        traffic_rate=200,
    ),
    RAW_TRAFFIC_TYPE_MAP[ixia_config_types.RawTrafficType.DHCPV6]: RawTrafficItemInfo(
        traffic_type=ixia_config_types.RawTrafficType.DHCPV6,
        cpu_queue=CpuQueue.MID,
        traffic_rate=200,
    ),
    RAW_TRAFFIC_TYPE_MAP[ixia_config_types.RawTrafficType.ARP]: RawTrafficItemInfo(
        traffic_type=ixia_config_types.RawTrafficType.ARP,
        cpu_queue=CpuQueue.HIGH,
        traffic_rate=200,
    ),
}

ALL_RAW_TRAFFIC_ITEMS_TO_TEST = {**CPU_BOUND_TRAFFIC, **HOST_BOUND_CPU_TRAFFIC}
# PACKET LOSS CONSTANTS
PACKET_LOSS_SAME_TIER_CHANGE = 100  # in ms
PACKET_LOSS_ONE_TIER_ABOVE_CHANGE = 200  # in ms
PACKET_LOSS_TWO_TIER_ABOVE_CHANGE = 500  # in ms
PACKET_LOSS_MULTI_TIER_CHANGE = 500  # in ms
PACKET_LOSS_THRESHOLD_PER_INTF_FLAP = 330  # in ms
PACKET_LOSS_THRESHOLD_SYSTEM_REBOOT = 100  # in ms
PACKET_LOSS_THRESHOLD_BGP_FLAP = 150  # in ms
PKT_LOSS_CONVERGENCE_SPR = 7000  # in ms
PKT_LOSS_CONVERGENCE_BGP = 4000  # in ms
MAX_INTF_PACKET_LOSS = 5000  # in ms
COLD_BOOT_PACKET_DROPS_THRESHOLD = 1000  # number of packets
SYSTEM_REBOOT_PACKET_DROPS_THRESHOLD = 4000  # number of packets
BGP_GR_TIMEOUT = 120  # in seconds

WAIT_FOR_DEVICE_UP_AFTER_REBOOT = 240  # in seconds

# Retryable timeout for interface related health checks
INTERFACE_CHECKS_RETRYABLE_TIMOUT: int = 480  # 8*60 seconds

TEST_CASE_RETRIES_COUNT = 3
TEST_CASE_RETRY_WAIT_DURATION = 5 * 60  # in seconds

DURATION_BETWEEN_AGENT_KILLS = 5  # in seconds
DURATION_BETWEEN_AGENT_RESTARTS = 5  # in seconds

PING_COUNT = 5  # number of probes to be sent for ping test
PING_TIMEOUT = 30  # ping test timeout in seconds

DATE_TIME_FORMAT = "%Y-%m-%d %H:%M:%S.%f"

DNE_LAB_SMC_TIER = "dne.test"
DNE_STANDALONE_SMC_TIER = "dne.standalone"
DNE_INFRA_SMC_TIER = "dne.infra"

NET_AI_DSF = "netcastle.lab.dsf"
NET_AI_LAB_SMC_TIER = "networkai.test"
NET_AI_LAB_REGRESSION_SMC_TIER = "networkai.test.regression"
FBOSS_LAB_SMC_TIER = "netcastle.lab.fboss"

SYSTEM_DATE_THRESHOLD = 300

# T35844114
NETCASTLE_BOT = "svc-netcastle_bot"


# Used by Config patcher for persistent changes to agent configs in FBOSS
DNE_TEST_REGRESSION_NAME = "DNE_TEST_REGRESSION"

GLACIER_MINIPACK_MODEL_NAME = "DCS-7368X-128-BND-D"

BAD_COMMAND_OUTPUTS = ["Invalid input", "Authorization denied"]


GENERIC_JSON_OUTPUT_TYPE = Dict[str, dict]

INTF_NOT_FOUND_MSG = (
    "Interface {} does not seem to exist. Please double check if this is expected. "
)

INVALID_IP_MSG = (
    "Failed to validate local and remote IP(v4/v6) addresses and VRF on {}."
)

# ODS Keys to get CPU Utilization of Device
CPU_UTIL_KEY = "system.cpu-util-pct"

# ODS Keys to get get MEM Utilization of Device
MEM_UTIL_KEY = "system.mem-util-pct"

# FBOSS Local Drainer constants
LOCAL_DRAINER_PORT = 10701

FABRIC_CARD_KEY = "FC"

BMC_KEY = "BMC"

LINE_CARD_KEY = "LC"

ARISTA_LC_RE = re.compile(r"Linecard\d+")

BANDWIDTH_KEY: str = "bandwidth"

################################
# Cisco RELATED CONSTANTS #
################################

DUMMY_CISCO_HOSTNAME: str = "msw1af.01.fml1"

CISCO_INTF_PROPERTIES: str = "Cisco-IOS-XR-ifmgr-oper:interface-properties"
CISCO_INTF_STATS: str = "Cisco-IOS-XR-infra-statsd-oper:infra-statistics"
CISCO_DEVICE_ID: str = "device-id"
CISCO_LLDP_OPER: str = "Cisco-IOS-XR-ethernet-lldp-oper:lldp"
CISCO_LLDP_NEIGHBOR: str = "lldp-neighbor"
CISCO_RECEIVING_INTF: str = "receiving-interface-name"
CISCO_REMOTE_INTF: str = "port-id-detail"
CISCO_PLATFORM_OPER: str = "Cisco-IOS-XR-platform-oper:platform"
CISCO_OPER_STATE: str = "oper-state"
CISCO_LC_OPER_STATE_UP: str = "IOS XR RUN"
CISCO_FC_OPER_STATE_UP: str = "OPERATIONAL"
CISCO_LINE_STATE_UP: str = "im-state-up"
CISCO_BGP_PROC: str = "Cisco-IOS-XR-ipv4-bgp-oper:bgp"
CISCO_FIB_CLR_CMD: str = "clear cef ipv6 vrf all"

CISCO_LINE_STATE_KEY: str = "actual-line-state"

LOCATION_VIEW: str = "locationview"

INTERFACE_CONST: str = "interface"

# TODO(nishigrandhi): Find the critical core dumps for cisco
CISCO_CRITICAL_CORE_DUMPS: List[str] = ["test_dump"]

CISCO_BGP_ESTAB: str = "bgp-st-estab"

CONN_LOCAL_ADDR: str = "connection-local-address"

NEIGHBOR_ADDR: str = "neighbor-address"

CISCO_BGP_PROC_INFO_CMD: str = "sh yang operational ipv4-bgp-oper:bgp instances instance instance-active default-vrf process-info JSON"
CISCO_BGP_NEIGHBOR_INFO_CMD: str = "sh yang operational ipv4-bgp-oper:bgp instances instance instance-active default-vrf neighbors neighbor connection-local-address JSON"
CISCO_BGP_NEIGHBOR_STATE_CMD: str = "sh yang operational ipv4-bgp-oper:bgp instances instance instance-active default-vrf neighbors neighbor connection-state JSON"

CISCO_LC_REGEX = r"\d/\d{1,2}/CPU\d$"

CISCO_RP_REGEX = r"\d/RP\d/CPU\d$"


class CiscoBGPReset(Enum):
    HARD_RESET = "clear bgp *"
    SOFT_RESET = "clear bgp ipv6 unicast * soft in \nclear bgp ipv6 unicast * soft in"


CISCO_STATIC_DRAIN_ROUT_POLICIES_CONF_PATH = (
    "neteng/network_ai/static_drain_route_maps/device_drain_route_map"
)

################################
# ARISTA EOS RELATED CONSTANTS #
################################

ADMIN_LOGIN = "admin"

ARISTA_BGP_SUMMARY_HEADER = [
    "PeerIP",
    "MyIP",
    "LocalAS",
    "RemoteAS",
    "PeerState",
    "Uptime",
    "Desc",
]
NON_EXISTENT_IP = [ipaddress.ip_address("0.0.0.0"), ipaddress.ip_address("::")]

SNC_VIRTUAL_SSW = "2401:db00:116:301f::6f"

ARISTA_WAIT_HITFUL_PROCESS_DISRUPTION = 150  # in secs
ARISTA_WAIT_HITLESS_PROCESS_DISRUPTION = 2  # in secs
ARISTA_PACKET_LOSS_THRESHOLD_SYSTEM_AGENT_RESTART = 100  # in ms
ARISTA_PACKET_LOSS_THRESHOLD_L3_FORWARDING_AGENT_RESTART = 90  # in ms
ARISTA_PACKET_LOSS_THRESHOLD_FABRIC_AGENT_RESTART = 100
ARISTA_MAX_WAIT_AFTER_SERVICE_START = 15

WAIT_TIME_AFTER_PROCESS_DISRUPTION = 240  # in secs

# fsdb takes ~4 secs to initialize. adding some buffer time
FSDB_INITIALIZATION_WAIT_TIME = 5  # in secs
QSFP_INITIALIZATION_WAIT_TIME = 60  # in secs

GENERIC_INITIALIZATION_WAIT_TME = 60  # in secs
SKIP_INITIALIZATION = 0

BGP_ROUTE_PROPAGATION_WAIT_TIME_POST_CONVERGENCE = 5  # in secs

PORT_DOWN_TIME: int = 5
CPU_PORT_UP_TIME: int = 300
# https://fburl.com/2zfpzxwb
ARISTA_PROMPT_REGEX = "[\\w.]+(\\(s\\d+\\))?(\\(config.*\\))?[#>]\\s*"

ARISTA_HW_COUNTERS_GET_MAP = {
    AristaModelNames.DCS7808: "show hardware counter drop | json",
    AristaModelNames.DCS7812: "show hardware counter drop | json",
    AristaModelNames.DCS7816: "show hardware counter drop | json",
}
ARISTA_HW_COUNTERS_CLR_MAP = {
    AristaModelNames.DCS7808: "clear hardware counter drop",
    AristaModelNames.DCS7812: "clear hardware counter drop",
    AristaModelNames.DCS7816: "clear hardware counter drop",
}

ARISTA_CRITICAL_CORE_DUMPS = [
    "strata",
    "rib",
    "xcvr",
    "qos",
    "ebra",
    "coredump",
    "linecard",
]


###########################
# FBOSS RELATED CONSTANTS #
###########################

COOP_PORT: int = 6969

DEFAULT_COOP_TIMEOUT: int = 120

FBOSS_COOP_TIER: str = "fboss.coop"

# Sample subswitches: fsw004-lc101.p023.f01.atn3, fsw004-fc003.p007.f01.frc3
GALAXY_WEDGE_RE_PATTERN = re.compile(
    r"(^fsw[\d]{3})(-[fl]{1}c[\d]{3})(.p[\d]{3}.f[\d]{2}.[a-z]{3}[\d])", re.IGNORECASE
)
DEFAULT_AGENT_REMOTE_PORT = 5909

FBOSS_AGENT_TIER: str = "fboss.agent"

DEFAULT_BCM_REMOTE_PORT = 5909

DEFAULT_FBAGENT_PORT = 4026

DEFAULT_THRIFT_TIMEOUT = 120  # in seconds

ALLOWED_FBOSS_AGENTS = ["bgpd", "coop", "qsfp_service", "wedge_agent"]

AGENT_CONFIG_PATCHER_NAME = "agent"

BGP_CONFIG_PATCHER_NAME = "bgp"

# A method in https://fburl.com/diffusion/316gf9z6
CHANGE_PORT_ADMIN_PATCHER_METHOD_NAME = "change_port_admin_state"
ADD_STATIC_ROUTES_PATCHER_METHOD_NAME = "add_static_routes"
SET_PORTCHANNEL_MINLINK_CAPACTIY_METHOD_NAME = "set_port_channel_min_link_capacity"

DNE_TEST_SET_MIN_LINK_CAPACITY_VALUE_PATCHER_METHOD_NAME = (
    "set_port_channel_min_link_capacity"
)

DNE_TEST_SET_MIN_LINK_CAPACITY_VALUE_FOR_ALL_PORT_CHANNEL_PATCHER_METHOD_NAME = (
    "set_all_port_channel_min_link_capacity"
)

DNE_TEST_CREATE_PEER_GROUP_PATCHER_METHOD_NAME = "add_peer_group_patcher"

DNE_TEST_SETUP_AGG_PORT = "setup_agg_port"

DNE_TEST_REMOVE_AGG_PORT = "remove_agg_port"

CHANGE_SPEED_PATCHER = "change_speed"
CHANGE_MTU_PATCHER = "change_mtu"

BGP_SUMMARY_HEADER = [
    "PeerIP",
    "MyIP",
    "LocalAS",
    "RemoteAS",
    "PeerState",
    "Uptime",
    "Description",
    "PR",
    "PS",
]


EGRESS_RATE_KEY = "{}.out_bytes.rate.60"

INGRESS_RATE_KEY = "{}.in_bytes.rate.60"

EGRESS_PKT_RATE_KEY = "{}.out_unicast_pkts.rate.60"

INGRESS_PKT_RATE_KEY = "{}.in_unicast_pkts.rate.60"

_ONE_MBPS = 10**6

WEDGE_POWER_CMD = "/usr/local/bin/wedge_power.sh"
FPGA_VER_CMD = "/usr/local/bin/fpga_ver.sh"

INTERFACE_COUNTER_KEYS = [
    "in_bytes.rate.60",  # Ingress rate with load interval of 1 minute
    "out_bytes.rate.60",  # Egress rate with load interval of 1 minute
    "in_bytes.rate.600",  # Ingress rate with load interval of 10 minutes
    "out_bytes.rate.600",  # Egress rate with load interval of 10 minutes
]

INTERFACE_ERROR_COUNTER_KEYS = [
    "out_errors.sum.60",  # output errors with load interval of 1 minute
    "out_errors.sum.600",  # output errors with load interval of 10 minute
    "in_errors.sum.60",  # input errors with load interval of 1 minute
    "in_errors.sum.600",  # input errors with load interval of 10 minute
]
INTERFACE_FLAP_COUNTER_KEYS = [
    "link_state.flap.sum.60",  # link flap sum with load interval of 1 minute
    "link_state.flap.sum.600",  # link flap sum with load interval of 10 minute
    "link_state.flap.sum.3600",  # link flap sum with load interval of 1 hour
]

FBOSS_CRITICAL_CORE_DUMPS = ["fboss", "openr", "bgp", "qsfp", "agent", "fsdb"]

# list of substrings that will not necessiate failing a test despite being related
FBOSS_CRITICAL_CORE_NON_SELECTOR = [
    "neighbor_watch",
    "updater",
    "fbagent",
    "dogpile",  # Not critical based on info seen here - (https://fburl.com/wiki/uo3ofd2v)
]

NETCASTLE_PROD_PODS = ["p005.f02.snc1", "p006.f02.snc1"]

DNE_REGRESSION_BASSET_POOL_NAME = "dne.regression"

# MNPU SMC tiers
FBOSS_MULTI_SWITCH_SMC_TIER: str = "fboss.multi_switch"
FBOSS_CPP_WEDGE_AGENT_WRAPPER_SMC_TIER: str = "fboss.cpp_wedge_agent_wrapper"


class SystemctlServiceStatus(Enum):
    # Service is running
    ACTIVE = 0
    # Service stopped with previous run successful or not found on device
    INACTIVE = 1
    # Previous run was not successful
    FAILED = 2
    # Service reloading, activating, deactivating
    TRANSITIONING = 3


class AristaAgentStatus(Enum):
    # Service is running
    ACTIVE = 0
    # Service stopped with previous run successful or not found on device
    INACTIVE = 1


# FIB Agent Port used by openr client
OPENR_FIB_AGENT_PORT = 5909
OPENR_FIB_AGENT_MTLS_PORT = 5912
BGP_FIB_AGENT_MTLS_PORT = 5913


# FIB Agent Port used by openr client
OPENR_THRIFT_CALL_TIMEOUT = 100

DEFAULT_OPENR_PORT = 2018
DEFAULT_BGP_PORT = 6909
DEFAULT_TIMEOUT = 5000  # milliseconds

FIB_COUNT_ALLOWED_OFFSET: float = 0.95

DEFAULT_MEMORIZE_TIME: float = 24 * 60 * 60  # 24 hours


@dataclass(frozen=True)
class OpenrKvStoreDetails:
    key: str
    originator_id: str
    version: str


SWITCH_CONF_BASE_DIR = "/var/facebook/dne"
SERVICE_LOCAL_BASE_DIR = "neteng/netcastle/teams/dne_regression/scripts"

BCM_SAI_FEATURE_FLAG = "/etc/fboss/features/sai_bcm/current/on"

# FROM DNE STRUCT


class ArpNdpState(Enum):
    INCOMPLETE = 0
    REACHABLE = 1


class BgpSessionState(Enum):
    UNSTABLE = 0
    STABLE = 1


class DrainJobType(Enum):
    DRAIN = 0
    UNDRAIN = 1


class DisruptiveEvent(Enum):
    INTERFACE_DISABLE = "link_down"
    BGP_NEIGHBORSHIP_FLAP = "bgp_neighborship_flap"
    PROCESS_RESTART = "process_restart"
    SYSTEM_REBOOT = "system_reboot"
    DRAIN_UNDRAIN = "drain_undrain"
    INTERFACE_ENABLE = "link_up"
    SYSTEM_STRESS = "system_stress"
    SAME_TIER_CHANGE = "same_tier_change"
    ONE_TIER_AWAY_CHANGE = "one_tier_away_change"
    TWO_TIER_AWAY_CHANGE = "two_tier_away_change"
    MULTI_TIER_CHANGE = "multi_tier_change"
    CONVERGENCE_INTERFACE_ENABLE = "convergence_interface_enable"


class InterfaceEventState(Enum):
    UNSTABLE = 0
    STABLE = 1


class OtherSystemctlServiceName(Enum):
    RSYSLOG = "rsyslog"


class FbossSystemctlServiceName(Enum):
    AGENT = "wedge_agent"
    BGP = "bgpd"
    QSFP = "qsfp_service"
    OPENR = "openr"
    CONFIGERATOR_PROXY = "configerator_proxy2"
    CONFIGERATOR_FUSE = "configerator_fuse"
    SMC_PROXY = "smc_proxy"
    FBOSS_SW_AGENT = "fboss_sw_agent"
    FSDB = "fsdb"
    FBOSS_HW_AGENT_0 = "fboss_hw_agent@0"
    FBOSS_HW_AGENT_1 = "fboss_hw_agent@1"
    COOP = "coop"


class ModuleType(Enum):
    LINECARD = "LineCard"
    FABRICCARD = "FabricCard"
    BMC = "BMC"
    ROUTEPROC = "RouteProcessor"
    FANTRAY = "FanTray"
    SUPERVISOR = "Supervisor"


@dataclass
class ModuleInfo:
    """Structured info for a single hardware module from 'show module | json'."""

    slot: str
    module_type: ModuleType
    model_name: str
    status: str
    port_count: int
    serial_number: str
    type_description: str


# TODO: remove this
SystemctlServiceName = Union[FbossSystemctlServiceName, OtherSystemctlServiceName]

Service = Union[
    AristaCriticalAgents, OtherSystemctlServiceName, FbossSystemctlServiceName
]


@dataclass
class ServiceStatusCounters:
    start_time: int
    restart_count: int
    status: SystemctlServiceStatus


@dataclass
class NextHopAttributes:
    nh_addr: str
    nh_ifname: str
    nh_weight: int
    nh_port_name: str
    nh_port_speed: int


# NOTE: (harshalsh) to revisit uptime usage
@dataclass
class AristaAgentStatusCounters:
    uptime: str
    restart_count: int
    status: AristaAgentStatus


@dataclass(frozen=True)
class SwitchLldpData:
    remote_device_name: str
    remote_intf_name: str


class IpAddress(Enum):
    IPV4 = 0
    IPV6 = 1
    ipv4 = "ipv4"
    ipv6 = "ipv6"


class LinecardPowerState(Enum):
    POWER_OFF = 0
    POWER_ON = 1


class SystemAvailability(Enum):
    UNREACHABLE = 0
    REACHABLE = 1


class ProcessRestartType(Enum):
    AGENT_WARMBOOT = 0
    AGENT_COLDBOOT = 1
    BGPCPP_RESTART = 2
    OPENR_RESTART = 3
    QSFP_SERVICE_RESTART = 4
    WEDGE_AGENT_CRASH = 5
    QSFP_SERVICE_CRASH = 6
    BGPCPP_CRASH = 7
    OPENR_CRASH = 8
    # TODO: Categorize the below once as ProcessShut dataclass
    OPENR_SHUT = 9
    BGP_SHUT = 10
    # ARISTA
    ARISTA_ROUTING_AGENT_RESTART = 11
    ARISTA_CHIP_AGENT_RESTART = 12
    ARISTA_XCVR_RESTART = 13
    ARISTA_EBRA_RESTART = 14
    ARISTA_L3_FORWARDING_AGENT_RESTART = 15
    ARISTA_FABRIC_AGENT_RESTART = 16
    ARISTA_ROUTING_AGENT_CRASH = 17
    ARISTA_CHIP_AGENT_CRASH = 18
    ARISTA_XCVR_CRASH = 19
    ARISTA_EBRA_CRASH = 20
    ARISTA_L3_FORWARDING_AGENT_CRASH = 21
    ARISTA_FABRIC_AGENT_CRASH = 22

    FSDB_RESTART = 30
    FBOSS_SW_AGENT_RESTART = 31
    FBOSS_HW_AGENT_0_RESTART = 32
    FBOSS_SW_AGENT_CRASH = 33
    FBOSS_HW_AGENT_0_CRASH = 34


class ProcessDisruptionType(Enum):
    """
    ODS Key substrings to identify the protocol being used in SLO Testing
    """

    # equivalent of 'systemctl restart <process>'
    RESTART = "restart"
    # equivalent of 'systemctl stop <process>' beyond hold down timer
    SHUTDOWN = "shutdown"
    # equivalent of 'systemctl start <process>' && 'systemctl stop <process>'
    UNGRACEFUL_RESTART = "stop & start"
    # equivalent of 'kill -9 <process>'
    CRASH = "kill"
    # equivalent of 'systemctl stop <process>'
    STOP = "stop"
    # equivalent of 'systemctl start <process>'
    START = "start"


@dataclass
class ProcessRestartInfo:
    process_restart_type: ProcessRestartType
    service: Union[SystemctlServiceName, AristaCriticalAgents]
    initialization_wait_time: float = WAIT_TIME_AFTER_PROCESS_DISRUPTION  # 240 seconds
    expected_loss: float = 0
    disruptive_if_dut_non_redundant: bool = False


@dataclass
class ProcessRestartInput:
    device_name: str
    process_restart_type: ProcessRestartType
    process_disruption_type: ProcessDisruptionType
    # If not None, overrides the default initialization wait time
    initialization_wait_time_override: Optional[float] = None


PROCESS_RESTART_INFO_MAP = {
    # Fboss Restart
    ProcessRestartType.BGPCPP_RESTART: ProcessRestartInfo(
        process_restart_type=ProcessRestartType.BGPCPP_RESTART,
        service=FbossSystemctlServiceName.BGP,
        initialization_wait_time=SKIP_INITIALIZATION,
    ),
    ProcessRestartType.OPENR_RESTART: ProcessRestartInfo(
        process_restart_type=ProcessRestartType.OPENR_RESTART,
        service=FbossSystemctlServiceName.OPENR,
    ),
    ProcessRestartType.QSFP_SERVICE_RESTART: ProcessRestartInfo(
        process_restart_type=ProcessRestartType.QSFP_SERVICE_RESTART,
        service=FbossSystemctlServiceName.QSFP,
        initialization_wait_time=QSFP_INITIALIZATION_WAIT_TIME,
    ),
    ProcessRestartType.FSDB_RESTART: ProcessRestartInfo(
        process_restart_type=ProcessRestartType.FSDB_RESTART,
        service=FbossSystemctlServiceName.FSDB,
        initialization_wait_time=FSDB_INITIALIZATION_WAIT_TIME,
    ),
    # Fboss Warmboot
    ProcessRestartType.AGENT_WARMBOOT: ProcessRestartInfo(
        process_restart_type=ProcessRestartType.AGENT_WARMBOOT,
        service=FbossSystemctlServiceName.AGENT,
        initialization_wait_time=SKIP_INITIALIZATION,
    ),
    ProcessRestartType.FBOSS_SW_AGENT_RESTART: ProcessRestartInfo(
        process_restart_type=ProcessRestartType.FBOSS_SW_AGENT_RESTART,
        service=FbossSystemctlServiceName.FBOSS_SW_AGENT,
        initialization_wait_time=SKIP_INITIALIZATION,
    ),
    # Fboss Coldboot
    ProcessRestartType.AGENT_COLDBOOT: ProcessRestartInfo(
        process_restart_type=ProcessRestartType.AGENT_COLDBOOT,
        service=FbossSystemctlServiceName.AGENT,
        disruptive_if_dut_non_redundant=True,
        initialization_wait_time=SKIP_INITIALIZATION,
    ),
    ProcessRestartType.FBOSS_HW_AGENT_0_RESTART: ProcessRestartInfo(
        process_restart_type=ProcessRestartType.FBOSS_HW_AGENT_0_RESTART,
        service=FbossSystemctlServiceName.FBOSS_HW_AGENT_0,
        disruptive_if_dut_non_redundant=True,
        initialization_wait_time=SKIP_INITIALIZATION,
    ),
    # Fboss Crash
    ProcessRestartType.WEDGE_AGENT_CRASH: ProcessRestartInfo(
        process_restart_type=ProcessRestartType.WEDGE_AGENT_CRASH,
        service=FbossSystemctlServiceName.AGENT,
        disruptive_if_dut_non_redundant=True,
        initialization_wait_time=SKIP_INITIALIZATION,
    ),
    ProcessRestartType.FBOSS_SW_AGENT_CRASH: ProcessRestartInfo(
        process_restart_type=ProcessRestartType.FBOSS_SW_AGENT_CRASH,
        service=FbossSystemctlServiceName.FBOSS_SW_AGENT,
        disruptive_if_dut_non_redundant=True,
        initialization_wait_time=SKIP_INITIALIZATION,
    ),
    ProcessRestartType.FBOSS_HW_AGENT_0_CRASH: ProcessRestartInfo(
        process_restart_type=ProcessRestartType.FBOSS_HW_AGENT_0_CRASH,
        service=FbossSystemctlServiceName.FBOSS_HW_AGENT_0,
        disruptive_if_dut_non_redundant=True,
        initialization_wait_time=SKIP_INITIALIZATION,
    ),
    ProcessRestartType.QSFP_SERVICE_CRASH: ProcessRestartInfo(
        process_restart_type=ProcessRestartType.QSFP_SERVICE_CRASH,
        service=FbossSystemctlServiceName.QSFP,
        initialization_wait_time=QSFP_INITIALIZATION_WAIT_TIME,
        disruptive_if_dut_non_redundant=True,
    ),
    ProcessRestartType.BGPCPP_CRASH: ProcessRestartInfo(
        process_restart_type=ProcessRestartType.BGPCPP_CRASH,
        service=FbossSystemctlServiceName.BGP,
    ),
    ProcessRestartType.OPENR_CRASH: ProcessRestartInfo(
        process_restart_type=ProcessRestartType.OPENR_CRASH,
        service=FbossSystemctlServiceName.OPENR,
        disruptive_if_dut_non_redundant=True,
    ),
    # General Shutdown
    ProcessRestartType.OPENR_SHUT: ProcessRestartInfo(
        process_restart_type=ProcessRestartType.OPENR_SHUT,
        service=FbossSystemctlServiceName.OPENR,
    ),
    # Arista Restart
    ProcessRestartType.ARISTA_ROUTING_AGENT_RESTART: ProcessRestartInfo(
        process_restart_type=ProcessRestartType.ARISTA_ROUTING_AGENT_RESTART,
        service=AristaCriticalAgents.ROUTING_AGENT,
        initialization_wait_time=ARISTA_WAIT_HITFUL_PROCESS_DISRUPTION,
        disruptive_if_dut_non_redundant=True,
    ),
    ProcessRestartType.ARISTA_CHIP_AGENT_RESTART: ProcessRestartInfo(
        process_restart_type=ProcessRestartType.ARISTA_CHIP_AGENT_RESTART,
        service=AristaCriticalAgents.SYSTEM_AGENT,
        initialization_wait_time=ARISTA_WAIT_HITFUL_PROCESS_DISRUPTION,
        disruptive_if_dut_non_redundant=True,
    ),
    ProcessRestartType.ARISTA_XCVR_RESTART: ProcessRestartInfo(
        process_restart_type=ProcessRestartType.ARISTA_XCVR_RESTART,
        service=AristaCriticalAgents.XCVR_AGENT,
        initialization_wait_time=ARISTA_WAIT_HITFUL_PROCESS_DISRUPTION,
    ),
    ProcessRestartType.ARISTA_EBRA_RESTART: ProcessRestartInfo(
        process_restart_type=ProcessRestartType.ARISTA_EBRA_RESTART,
        service=AristaCriticalAgents.EBRA,
        initialization_wait_time=ARISTA_WAIT_HITFUL_PROCESS_DISRUPTION,
    ),
    ProcessRestartType.ARISTA_L3_FORWARDING_AGENT_RESTART: ProcessRestartInfo(
        process_restart_type=ProcessRestartType.ARISTA_L3_FORWARDING_AGENT_RESTART,
        service=AristaCriticalAgents.L3_FORWARDING_AGENT,
        initialization_wait_time=ARISTA_WAIT_HITFUL_PROCESS_DISRUPTION,
        disruptive_if_dut_non_redundant=True,
    ),
    ProcessRestartType.ARISTA_FABRIC_AGENT_RESTART: ProcessRestartInfo(
        process_restart_type=ProcessRestartType.ARISTA_FABRIC_AGENT_RESTART,
        service=AristaCriticalAgents.FABRIC_AGENT,
        initialization_wait_time=ARISTA_WAIT_HITFUL_PROCESS_DISRUPTION,
        disruptive_if_dut_non_redundant=True,
    ),
    # Arista Crash
    ProcessRestartType.ARISTA_ROUTING_AGENT_CRASH: ProcessRestartInfo(
        process_restart_type=ProcessRestartType.ARISTA_ROUTING_AGENT_CRASH,
        service=AristaCriticalAgents.ROUTING_AGENT,
        initialization_wait_time=ARISTA_WAIT_HITFUL_PROCESS_DISRUPTION,
        disruptive_if_dut_non_redundant=True,
    ),
    ProcessRestartType.ARISTA_CHIP_AGENT_CRASH: ProcessRestartInfo(
        process_restart_type=ProcessRestartType.ARISTA_CHIP_AGENT_CRASH,
        service=AristaCriticalAgents.SYSTEM_AGENT,
        initialization_wait_time=ARISTA_WAIT_HITFUL_PROCESS_DISRUPTION,
        disruptive_if_dut_non_redundant=True,
    ),
    ProcessRestartType.ARISTA_XCVR_CRASH: ProcessRestartInfo(
        process_restart_type=ProcessRestartType.ARISTA_XCVR_CRASH,
        service=AristaCriticalAgents.XCVR_AGENT,
        initialization_wait_time=ARISTA_WAIT_HITFUL_PROCESS_DISRUPTION,
    ),
    ProcessRestartType.ARISTA_EBRA_CRASH: ProcessRestartInfo(
        process_restart_type=ProcessRestartType.ARISTA_EBRA_CRASH,
        service=AristaCriticalAgents.EBRA,
        initialization_wait_time=ARISTA_WAIT_HITFUL_PROCESS_DISRUPTION,
    ),
    ProcessRestartType.ARISTA_L3_FORWARDING_AGENT_CRASH: ProcessRestartInfo(
        process_restart_type=ProcessRestartType.ARISTA_L3_FORWARDING_AGENT_CRASH,
        service=AristaCriticalAgents.L3_FORWARDING_AGENT,
        initialization_wait_time=ARISTA_WAIT_HITFUL_PROCESS_DISRUPTION,
        disruptive_if_dut_non_redundant=True,
    ),
    ProcessRestartType.ARISTA_FABRIC_AGENT_CRASH: ProcessRestartInfo(
        process_restart_type=ProcessRestartType.ARISTA_FABRIC_AGENT_CRASH,
        service=AristaCriticalAgents.FABRIC_AGENT,
        initialization_wait_time=ARISTA_WAIT_HITFUL_PROCESS_DISRUPTION,
        disruptive_if_dut_non_redundant=True,
    ),
}

# TODO: move this info to ProcessRestartInfo
EXPECTED_LOSS_DISRUPTIVE_EVENT_REDUNDANT_DUT = {
    ProcessRestartType.ARISTA_ROUTING_AGENT_RESTART.value: PACKET_LOSS_THRESHOLD_BGP_FLAP,
    ProcessRestartType.ARISTA_ROUTING_AGENT_CRASH.value: PACKET_LOSS_THRESHOLD_BGP_FLAP,
    ProcessRestartType.ARISTA_CHIP_AGENT_RESTART.value: ARISTA_PACKET_LOSS_THRESHOLD_SYSTEM_AGENT_RESTART,
    ProcessRestartType.ARISTA_CHIP_AGENT_CRASH.value: ARISTA_PACKET_LOSS_THRESHOLD_SYSTEM_AGENT_RESTART,
    ProcessRestartType.ARISTA_L3_FORWARDING_AGENT_CRASH.value: ARISTA_PACKET_LOSS_THRESHOLD_L3_FORWARDING_AGENT_RESTART,
    ProcessRestartType.ARISTA_L3_FORWARDING_AGENT_RESTART.value: ARISTA_PACKET_LOSS_THRESHOLD_L3_FORWARDING_AGENT_RESTART,
    ProcessRestartType.ARISTA_FABRIC_AGENT_CRASH.value: ARISTA_PACKET_LOSS_THRESHOLD_FABRIC_AGENT_RESTART,
    ProcessRestartType.ARISTA_FABRIC_AGENT_RESTART.value: ARISTA_PACKET_LOSS_THRESHOLD_FABRIC_AGENT_RESTART,
    ProcessRestartType.AGENT_COLDBOOT.value: 5,
    ProcessRestartType.FBOSS_HW_AGENT_0_RESTART.value: 5,
    ProcessRestartType.FBOSS_HW_AGENT_0_CRASH.value: 5,
    ProcessRestartType.FBOSS_SW_AGENT_CRASH.value: 5,
    ProcessRestartType.WEDGE_AGENT_CRASH.value: 5,
    ProcessRestartType.OPENR_CRASH.value: 120,
}

NON_DISRUPTIVE_ACTION = {
    ProcessRestartType.ARISTA_XCVR_RESTART,
    ProcessRestartType.ARISTA_EBRA_RESTART,
    ProcessRestartType.ARISTA_XCVR_CRASH,
    ProcessRestartType.ARISTA_EBRA_CRASH,
    ProcessRestartType.BGPCPP_RESTART,
    ProcessRestartType.BGPCPP_CRASH,
    ProcessRestartType.QSFP_SERVICE_RESTART,
    ProcessRestartType.AGENT_WARMBOOT,
    ProcessRestartType.FBOSS_SW_AGENT_RESTART,
    ProcessRestartType.OPENR_RESTART,
    ProcessRestartType.FSDB_RESTART,
}

# These are all the actions/ events that shouldn't result in a
# BGP neighborship to flap on any port.
NON_BGP_NEIGH_DISRUPTIVE_ACTION = {
    # ProcessRestartType.QSFP_SERVICE_RESTART,
    ProcessRestartType.ARISTA_XCVR_RESTART,
    ProcessRestartType.ARISTA_EBRA_RESTART,
    ProcessRestartType.ARISTA_FABRIC_AGENT_RESTART,
    ProcessRestartType.ARISTA_XCVR_CRASH,
    ProcessRestartType.ARISTA_EBRA_CRASH,
    ProcessRestartType.ARISTA_FABRIC_AGENT_CRASH,
}


class SystemRebootMethod(Enum):
    FULL_SYSTEM_REBOOT = 1
    BMC_POWER_RESET = 2
    BMC_MICROSERVER_ONLY_RESET = 3


class InterfaceFlapMethod(Enum):
    # Flap interface with a Thrift call
    THRIFT_PORT_STATE_CHANGE = "_bounce_specific_interface_using_port_enable_command"
    # Flap interface with wedge_qsfp_util -tx_disable/-tx_enable
    FBOSS_WEDGE_QSFP_UTIL_TX = "_bounce_specific_interface_using_wedge_qsfp_util_tx"
    # Flap interface with wedge_qsfp_util -set_low_power/-clear_low_power
    FBOSS_WEDGE_QSFP_UTIL_POWER = (
        "_bounce_specific_interface_using_wedge_qsfp_util_low_power"
    )
    FBOSS_BCM_SHELL = "_bounce_specific_interface_using_bcm_shell"


class FbpkgPackageName(Enum):
    AGENT = "neteng.fboss.wedge_agent"
    AGENT_CSCO = "neteng.fboss.wedge_agent_csco"
    BGP = "neteng.fboss.wedge_bgpd"
    QSFP_SERVICE = "neteng.fboss.qsfp_service"
    OPENR = "openr"
    FSDB = "neteng.fboss.fsdb"


@dataclass
class HwCounters:
    device_name: str
    # This contains type of hardware counter as key and
    # individual line_card/fabric_module and number of drops
    # of that type in the specific module as values
    hw_drops: Dict[str, Dict[str, int]]


@dataclass
class PortCounters:
    device_name: str
    interface_name: str
    out_discards: int
    out_error: int
    in_discards: int
    in_error: int


@dataclass
class CoreDumpFiles:
    """
    Comprises of the list of core dump and non core dump files
    """

    critical_core_dumps: List[str] = field(default_factory=list)
    non_critical_core_dumps: List[str] = field(default_factory=list)


@dataclass
class EcmpHashMetrics:
    pmax: float
    pmin: float
    cv: float
    std_dev: float
    arista_max_min_coeff: float
    baseline_rate_bps: float


@dataclass
class InterfaceInfo:
    port_id: int
    vlan_id: int


def create_fadu_route_attribute_policy(
    WT_1: int,
    WT_2: int,
):
    FADU_ROUTE_ATTRIBUTE_POLICY = {
        "policy": {
            "statements": {
                "cte_testing": {
                    "matcher": {
                        "community_list": {
                            "boolean_operator": 2,
                            "communities": [
                                {
                                    "community": {
                                        "asn": 65529,
                                        "community": 0,
                                        "value": 666,
                                    },
                                    "match_type": 0,
                                },
                                {
                                    "community": {
                                        "asn": 65529,
                                        "community": 0,
                                        "value": 667,
                                    },
                                    "match_type": 0,
                                },
                            ],
                        }
                    },
                    "actions": {
                        "set_ucmp_weights": {
                            "nexthop_weight_actions": [
                                {
                                    "path_matchers": [
                                        {
                                            "community_list": {
                                                "boolean_operator": 1,
                                                "communities": [
                                                    {
                                                        "community": {
                                                            "asn": 65529,
                                                            "community": 0,
                                                            "value": 666,
                                                        },
                                                        "match_type": 0,
                                                    },
                                                ],
                                            }
                                        },
                                    ],
                                    "weight": {WT_1},
                                },
                                {
                                    "path_matchers": [
                                        {
                                            "community_list": {
                                                "boolean_operator": 1,
                                                "communities": [
                                                    {
                                                        "community": {
                                                            "asn": 65529,
                                                            "community": 0,
                                                            "value": 667,
                                                        },
                                                        "match_type": 0,
                                                    },
                                                ],
                                            }
                                        },
                                    ],
                                    "weight": {WT_2},
                                },
                            ],
                            "apply_all_actions_or_fallback_to_ecmp": False,
                        }
                    },
                }
            }
        }
    }
    return json.dumps(FADU_ROUTE_ATTRIBUTE_POLICY)


CONVERGENCE_TEST_EVENTS = [
    DisruptiveEvent.SAME_TIER_CHANGE,
    DisruptiveEvent.MULTI_TIER_CHANGE,
    DisruptiveEvent.CONVERGENCE_INTERFACE_ENABLE,
    DisruptiveEvent.ONE_TIER_AWAY_CHANGE,
    DisruptiveEvent.TWO_TIER_AWAY_CHANGE,
]
CONVERGENCE_TEST_LINK_SHUT = [
    DisruptiveEvent.SAME_TIER_CHANGE,
    DisruptiveEvent.MULTI_TIER_CHANGE,
    DisruptiveEvent.CONVERGENCE_INTERFACE_ENABLE,
    DisruptiveEvent.ONE_TIER_AWAY_CHANGE,
    DisruptiveEvent.TWO_TIER_AWAY_CHANGE,
]


@dataclass
class EcmpGroup:
    """
    This class helps to hold data regarding ECMP group.

    ecmp_group_id: ECMP group id
    l3_ecmp_flags: the flags set by the asic (for the full list of flags: https://fburl.com/code/x6iftplx).
        0x10 is ECMP and 0x100 is UCMP.
    max_path: the maximum number of interfaces that this ECMP group can hold
    interfaces: list of interfaces that are part of this ECMP group
    """

    ecmp_group_id: int
    l3_ecmp_flags: str
    max_path: int
    interfaces: List[int]


class UpdateSwitchOption(Enum):
    AGENT_CONFIG = "agent_config"
    UPDATE_BINARY = "update_binary"  # update binary only as to force both agent and qsfp binary to be updated
    QSFP_CONFIG = "qsfp_config"
    LOGGING_CONFIG = "logging_config"


FSDB_PORT: int = 5908
