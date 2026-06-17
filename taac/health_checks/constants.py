# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import re
import typing as t
from dataclasses import dataclass

from taac.health_check.health_check import types as hc_types


@dataclass
class Snapshot:
    timestamp: int
    data: t.Any = None


DAILY_TABLE_TRANSFORM_DESC: str = "table(daily)"

FB_OOMD_LOG_PATH: str = "/var/facebook/logs/fb-oomd.log"

# FBOSS core dump configuration
FBOSS_CORE_DUMP_PATH: str = "/var/tmp/cores/"
FBOSS_CRITICAL_CORE_DUMPS: t.List[str] = [
    "fboss",
    "openr",
    "bgp",
    "qsfp",
    "agent",
    "fsdb",
    "mem",
]

# EOS/Arista core dump configuration
EOS_CORE_DUMP_PATH: str = "/var/core/"
# Pattern: core.<pid>.<epoch_timestamp>.<exec_name>.gz
# Example: core.4020.1725628991.Bgp-main.gz
EOS_CORE_DUMP_FILENAME_REGEX: re.Pattern = re.compile(
    r"core\.(?P<pid>\d+)\.(?P<timestamp>\d+)\.(?P<exec_name>.+)\.(?:gz|xz)"
)
EOS_CRITICAL_CORE_DUMPS: t.List[str] = [
    "bgpcpp",  # BGP++ process
    "peer_manager",  # BGP++ peer manager
    # "openr",  # OpenR routing daemon
    "FibAgent",  # FibAgent process
    "AristaFibAgent",  # FibBgpAgent process
    # "Sysdb",  # System database
    # "ProcMgr",  # Process manager
]

CORE_DUMP_IGNORE_WORDS: t.List[str] = [
    "neighbor_watch",
    "updater",
    "fbagent",
    "dynocat",
    "dogpile",
]

# Base service definitions
_ALL_SERVICES: t.Set[str] = {
    "wedge_agent",
    "bgpd",
    "qsfp_service",
    "fsdb",
    "openr",
    "fboss_sw_agent",
    "fboss_hw_agent@0",
    # "coop",
}

# Core services that typically remain stable during various restarts (excluding agent and bgp services)
_CORE_SERVICES_EXCLUDING_AGENT_ROUTING_PROTOCOL_SERVICES: t.Set[str] = {
    "fsdb",
    "qsfp_service",
    "coop",
}


def _get_services_excluding(exclude_services: t.Set[str]) -> t.List[str]:
    """Helper function to get services list excluding specified services."""
    return sorted(_ALL_SERVICES - exclude_services)


# Public service lists
DEFAULT_SERVICE_NAMES: t.List[str] = sorted(_ALL_SERVICES)

SERVICES_TO_MONITOR_DURING_FSDB_RESTART: t.List[str] = _get_services_excluding({"fsdb"})

SERVICES_TO_MONITOR_DURING_QSFP_SERVICE_RESTART: t.List[str] = _get_services_excluding(
    {"qsfp_service"}
)

SERVICES_TO_MONITOR_DURING_AGENT_RESTART: t.List[str] = sorted(
    _CORE_SERVICES_EXCLUDING_AGENT_ROUTING_PROTOCOL_SERVICES
)

SERVICES_TO_MONITOR_DURING_BGP_RESTART: t.List[str] = _get_services_excluding({"bgpd"})

SERVICES_TO_MONITOR_DURING_OPENR_RESTART: t.List[str] = _get_services_excluding(
    {"openr"}
)

# Services expected to restart during agent warmboot
SERVICES_EXPECTED_TO_RESTART_DURING_AGENT_WARMBOOT: t.List[str] = sorted(
    _ALL_SERVICES - _CORE_SERVICES_EXCLUDING_AGENT_ROUTING_PROTOCOL_SERVICES
)


# Arista hardware capacity health check constants
ARISTA_DEFAULT_FEC_THRESHOLD: int = 10000
ARISTA_DEFAULT_ECMP_THRESHOLD: int = 1000
ARISTA_DEFAULT_MAX_ECMP_LEVEL1: int = 5
ARISTA_DEFAULT_MAX_ECMP_LEVEL2: int = 500
ARISTA_DEFAULT_MAX_ECMP_LEVEL3: int = 0
ARISTA_DEFAULT_WATERMARK_DELTA_THRESHOLD: int = 100
ARISTA_DEFAULT_CHECK_WATERMARKS: bool = True

COMPARISON_OPERATORS = {
    hc_types.ComparisonType.LESS_THAN: lambda x, y: x < y,
    hc_types.ComparisonType.GREATER_THAN: lambda x, y: x > y,
    hc_types.ComparisonType.EQUAL_TO: lambda x, y: x == y,
    hc_types.ComparisonType.LESS_THAN_EQUAL_TO: lambda x, y: x <= y,
    hc_types.ComparisonType.GREATER_THAN_EQUAL_TO: lambda x, y: x >= y,
    hc_types.ComparisonType.BETWEEN: lambda x, y, z: y <= x <= z,
}
