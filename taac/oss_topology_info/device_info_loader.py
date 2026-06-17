# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
Device info loader for OSS topology lookups.

This module provides functions to load device information from CSV files
and perform hostname-to-IP, IP-to-hostname, hostname-to-MAC, hostname-to-role,
and hostname-to-operating_system lookups for OSS environments.
"""

import csv
import os
import typing as t
from dataclasses import dataclass

from taac.utils.oss_taac_lib_utils import memoize_forever


# Default path to device info CSV (relative to this module)
DEFAULT_DEVICE_INFO_PATH = os.path.join(os.path.dirname(__file__), "device_info.csv")

# Environment variable to override device info path
DEVICE_INFO_PATH_ENV = "TAAC_DEVICE_INFO_PATH"


@dataclass
class DeviceInfo:
    """Device information loaded from CSV."""

    hostname: str
    ipv6_address: str
    ipv4_address: t.Optional[str] = None
    mac_address: t.Optional[str] = None
    role: t.Optional[str] = None
    operating_system: t.Optional[str] = None


@dataclass
class DeviceInfoMaps:
    """Collection of lookup maps for device information."""

    hostname_to_ip: t.Dict[str, str]
    ip_to_hostname: t.Dict[str, str]
    hostname_to_mac: t.Dict[str, str]
    hostname_to_role: t.Dict[str, str]
    hostname_to_os: t.Dict[str, str]
    hostname_to_device_info: t.Dict[str, DeviceInfo]


@memoize_forever
def load_device_info(
    csv_path: t.Optional[str] = None,
) -> t.Tuple[
    t.Dict[str, str],
    t.Dict[str, str],
    t.Dict[str, str],
    t.Dict[str, str],
    t.Dict[str, str],
]:
    """
    Load device information from CSV file.

    The CSV file should have the format:
    hostname,ipv6_address,ipv4_address,mac_address,role,operating_system

    Lines starting with # are treated as comments and skipped.

    Args:
        csv_path: Path to the CSV file. If None, uses TAAC_DEVICE_INFO_PATH
                  environment variable or falls back to default location.

    Returns:
        Tuple of (hostname_to_ip, ip_to_hostname, hostname_to_mac, hostname_to_role,
                  hostname_to_os) dictionaries
    """
    if csv_path is None:
        csv_path = os.environ.get(DEVICE_INFO_PATH_ENV, DEFAULT_DEVICE_INFO_PATH)

    hostname_to_ip: t.Dict[str, str] = {}
    ip_to_hostname: t.Dict[str, str] = {}
    hostname_to_mac: t.Dict[str, str] = {}
    hostname_to_role: t.Dict[str, str] = {}
    hostname_to_os: t.Dict[str, str] = {}
    hostname_to_hardware: t.Dict[str, str] = {}

    if not os.path.exists(csv_path):
        # Return empty dicts if file doesn't exist - fallback to DNS/other methods
        # pyre-fixme[7]: Expected `Tuple[Dict[str, str], Dict[str, str], Dict[str,
        #  str], Dict[str, str], Dict[str, str]]` but got `Tuple[Dict[str, str],
        #  Dict[str, str], Dict[str, str], Dict[str, str], Dict[str, str], Dict[str,
        #  str]]`. Expected has length 5, but actual has length 6.
        return (
            hostname_to_ip,
            ip_to_hostname,
            hostname_to_mac,
            hostname_to_role,
            hostname_to_os,
            hostname_to_hardware,
        )

    with open(csv_path, "r") as f:
        reader = csv.reader(f)
        for row in reader:
            # Skip empty lines and comments
            if not row or row[0].startswith("#"):
                continue

            # Expected format: hostname,ipv6_address,ipv4_address,mac_address,role,operating_system,hardware
            if len(row) >= 2:
                hostname = row[0].strip().lower()
                ipv6_address = row[1].strip()

                if hostname and ipv6_address:
                    hostname_to_ip[hostname] = ipv6_address
                    ip_to_hostname[ipv6_address] = hostname

                # Also index by IPv4 if provided
                if len(row) >= 3:
                    ipv4_address = row[2].strip()
                    if ipv4_address:
                        ip_to_hostname[ipv4_address] = hostname

                # Index MAC address if provided
                if len(row) >= 4:
                    mac_address = row[3].strip()
                    if mac_address:
                        hostname_to_mac[hostname] = mac_address

                # Index role if provided
                if len(row) >= 5:
                    role = row[4].strip()
                    if role:
                        hostname_to_role[hostname] = role

                # Index operating_system if provided
                if len(row) >= 6:
                    operating_system = row[5].strip()
                    if operating_system:
                        hostname_to_os[hostname] = operating_system

                # Index hardware if provided
                if len(row) >= 7:
                    hardware = row[6].strip()
                    if hardware:
                        hostname_to_hardware[hostname] = hardware

    # pyre-fixme[7]: Expected `Tuple[Dict[str, str], Dict[str, str], Dict[str, str],
    #  Dict[str, str], Dict[str, str]]` but got `Tuple[Dict[str, str], Dict[str, str],
    #  Dict[str, str], Dict[str, str], Dict[str, str], Dict[str, str]]`. Expected has
    #  length 5, but actual has length 6.
    return (
        hostname_to_ip,
        ip_to_hostname,
        hostname_to_mac,
        hostname_to_role,
        hostname_to_os,
        hostname_to_hardware,
    )


def get_ip_from_hostname_oss(hostname: str) -> t.Optional[str]:
    """Get IP address from hostname using CSV lookup."""
    # pyre-fixme[23]: Unable to unpack 5 values, 6 were expected.
    hostname_to_ip, _, _, _, _, _ = load_device_info()
    normalized = hostname.strip().lower()
    return hostname_to_ip.get(normalized)


def get_hostname_from_ip_oss(ip_addr: str) -> t.Optional[str]:
    """Get hostname from IP address using CSV lookup."""
    # pyre-fixme[23]: Unable to unpack 5 values, 6 were expected.
    _, ip_to_hostname, _, _, _, _ = load_device_info()
    return ip_to_hostname.get(ip_addr.strip())


def get_mac_from_hostname_oss(hostname: str) -> t.Optional[str]:
    """Get MAC address from hostname using CSV lookup."""
    # pyre-fixme[23]: Unable to unpack 5 values, 6 were expected.
    _, _, hostname_to_mac, _, _, _ = load_device_info()
    normalized = hostname.strip().lower()
    return hostname_to_mac.get(normalized)


def get_role_from_hostname_oss(hostname: str) -> t.Optional[str]:
    """Get device role from hostname using CSV lookup."""
    # pyre-fixme[23]: Unable to unpack 5 values, 6 were expected.
    _, _, _, hostname_to_role, _, _ = load_device_info()
    normalized = hostname.strip().lower()
    return hostname_to_role.get(normalized)


def get_operating_system_from_hostname_oss(hostname: str) -> t.Optional[str]:
    """Get operating system from hostname using CSV lookup."""
    # pyre-fixme[23]: Unable to unpack 5 values, 6 were expected.
    _, _, _, _, hostname_to_os, _ = load_device_info()
    normalized = hostname.strip().lower()
    return hostname_to_os.get(normalized)


def get_hardware_from_hostname_oss(hostname: str) -> t.Optional[str]:
    """Get hardware platform from hostname using CSV lookup."""
    # pyre-fixme[23]: Unable to unpack 5 values, 6 were expected.
    _, _, _, _, _, hostname_to_hardware = load_device_info()
    normalized = hostname.strip().lower()
    return hostname_to_hardware.get(normalized)
