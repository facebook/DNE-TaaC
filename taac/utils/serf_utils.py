# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
TAAC Serf Utils - Abstraction layer for hostname/IP lookups.

This module provides OSS-compatible implementations of serf utility functions
that can work in both Meta (using Serf Device Cache) and OSS environments
(using CSV-based device info).
"""

import os
import typing as t

# Environment variable to control OSS mode
TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

# Only import Meta-internal types when not in OSS mode
if not TAAC_OSS:
    from facebook.core_systems.network_interface import types as ni_types


async def async_get_serf_device_mac_address(
    hostname: str,
) -> t.Optional[str]:
    """
    Abstraction layer for getting MAC address of a device.

    Uses TAAC_OSS environment variable to determine implementation:
    - OSS mode (TAAC_OSS=1): Uses CSV-based device info lookup
    - Meta mode (default): Uses Serf Device Cache

    Args:
        hostname: Device hostname to look up

    Returns:
        MAC address string if found, None otherwise
    """
    if TAAC_OSS:
        return await _async_get_serf_device_mac_address_oss(hostname)
    else:
        from neteng.netcastle.utils.serf_utils import async_resolve_serf_device

        nic_type = ni_types.NetworkInterfaceType.ETH0

        serf_device = await async_resolve_serf_device(hostname)
        if serf_device and serf_device.nics:
            for nic in serf_device.nics:
                if nic.type == nic_type:
                    return nic.mac
        return None


async def async_get_ip_from_hostname(hostname: str) -> str:
    """
    Abstraction layer for getting IP address from hostname.

    Uses TAAC_OSS environment variable to determine implementation:
    - OSS mode (TAAC_OSS=1): Uses CSV-based device info lookup, falls back to DNS
    - Meta mode (default): Uses Serf Device Cache

    Args:
        hostname: Device hostname to look up

    Returns:
        IP address string
    """
    if TAAC_OSS:
        return await _async_get_ip_from_hostname_oss(hostname)
    else:
        from neteng.netcastle.utils.serf_utils import (
            async_get_ip_from_hostname as netcastle_async_get_ip_from_hostname,
        )

        return await netcastle_async_get_ip_from_hostname(hostname)


async def async_get_hostname_from_ip(ip_addr: str) -> str:
    """
    Abstraction layer for getting hostname from IP address.

    Uses TAAC_OSS environment variable to determine implementation:
    - OSS mode (TAAC_OSS=1): Uses CSV-based device info lookup, falls back to DNS
    - Meta mode (default): Uses Serf Device Cache

    Args:
        ip_addr: IP address to look up

    Returns:
        Hostname string
    """
    if TAAC_OSS:
        return await _async_get_hostname_from_ip_oss(ip_addr)
    else:
        from neteng.netcastle.utils.serf_utils import (
            async_get_hostname_from_ip as netcastle_async_get_hostname_from_ip,
        )

        return await netcastle_async_get_hostname_from_ip(ip_addr)


async def _async_get_ip_from_hostname_oss(hostname: str) -> str:
    """
    OSS implementation: Get IP address from hostname using CSV lookup.

    Falls back to DNS resolution if not found in CSV.

    Args:
        hostname: Device hostname to look up

    Returns:
        IP address string (empty string if not found)
    """
    from taac.oss_topology_info.device_info_loader import (
        get_ip_from_hostname_oss,
    )
    from taac.utils.oss_taac_lib_utils import get_ipv6_for_host

    # Try CSV lookup first
    ip = get_ip_from_hostname_oss(hostname)
    if ip:
        return ip

    # Fallback to DNS resolution
    dns_result = get_ipv6_for_host(hostname)
    return dns_result if dns_result else ""


async def _async_get_hostname_from_ip_oss(ip_addr: str) -> str:
    """
    OSS implementation: Get hostname from IP address using CSV lookup.

    Falls back to reverse DNS resolution if not found in CSV.

    Args:
        ip_addr: IP address to look up

    Returns:
        Hostname string
    """
    import socket

    from taac.oss_topology_info.device_info_loader import (
        get_hostname_from_ip_oss,
    )

    # Try CSV lookup first
    hostname = get_hostname_from_ip_oss(ip_addr)
    if hostname:
        return hostname

    # Fallback to reverse DNS lookup
    try:
        hostname, _, _ = socket.gethostbyaddr(ip_addr)
        return hostname
    except socket.herror:
        # Return empty string if reverse DNS fails (matching Serf behavior)
        return ""


async def _async_get_serf_device_mac_address_oss(
    hostname: str,
) -> t.Optional[str]:
    """
    OSS implementation: Get MAC address from hostname using CSV lookup.

    Note: In OSS mode, only the default NIC (ETH0) MAC is stored in CSV.

    Args:
        hostname: Device hostname to look up

    Returns:
        MAC address string if found, None otherwise
    """
    from taac.oss_topology_info.device_info_loader import (
        get_mac_from_hostname_oss,
    )

    return get_mac_from_hostname_oss(hostname)
