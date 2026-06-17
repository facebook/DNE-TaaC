#!/usr/bin/env python3

# pyre-unsafe

import ipaddress
from dataclasses import dataclass
from enum import Enum


class TrafficState(Enum):
    STARTED = 0
    STOPPED = 1


DESIRED_VPORT_NAME = "VPORT_{port_identifier}"
DESIRED_TOPOLOGY_NAME = "TOPOLOGY_{port_identifier}"
DESIRED_DEVICE_GROUP_NAME = "DEVICE_GROUP_{port_identifier}"
DESIRED_ETHERNET_NAME = "ETHERNET_{port_identifier}"
DESIRED_IPV4_NAME = "IPV4_{port_identifier}"
DESIRED_IPV6_NAME = "IPV6_{port_identifier}"
DESIRED_IPV6_PTP_NAME = "IPV6_PTP_{port_identifier}"
DESIRED_BGP_V4_PEER_NAME = "BGP_PEER_V4_{port_identifier}"
DESIRED_BGP_V6_PEER_NAME = "BGP_PEER_V6_{port_identifier}"
DESIRED_BGP_V4_PREFIX_NAME = "BGP_PREFIX_V4_{port_identifier}_{prefix_name}"
DESIRED_BGP_V6_PREFIX_NAME = "BGP_PREFIX_V6_{port_identifier}_{prefix_name}"
DESIRED_V4_BGP_PREFIX_NAME = "BGP_PREFIX_V4_{port_identifier}"
DESIRED_V6_BGP_PREFIX_NAME = "BGP_PREFIX_V6_{port_identifier}"


# TODO: Store and retrieve them through the secure Keychain Service
# Default Login credentials that will be used ONLY for LINUX API Server types
API_SERVER_USERNAME = "admin"
API_SERVER_PASSWORD = "admin"

# name of fields in PacketLossStats maps to name of fields in ixia traffic flow stats
PACKET_LOSS_FIELDS = {
    "duration": "Packet Loss Duration (ms)",
    "frames_delta": "Frames Delta",
    "percentage": "Loss %",
}


@dataclass
class PacketLossStats:
    duration: float
    frames_delta: int
    percentage: float


ALLOWED_IPV6_ADVERTISEMENTS = [
    ipaddress.ip_network("5000::/16"),
    ipaddress.ip_network("4000::/16"),
    ipaddress.ip_network("6000::/16"),
    ipaddress.ip_network("2001:db8::/32"),
]

ALLOWED_IPV4_ADVERTISEMENTS = [ipaddress.ip_network("10.100.75.0/24")]
