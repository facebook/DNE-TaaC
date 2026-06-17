# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import ipaddress
import os
import typing as t

from ixia.ixia import types as ixia_types
from taac.constants import IxiaEndpointInfo
from taac.utils.oss_taac_constants import InsufficientInputError
from taac.utils.oss_taac_lib_utils import (
    ConsoleFileLogger,
    get_root_logger,
    memoize_forever,
    to_fb_uqdn,
)
from taac.utils.serf_utils import async_get_ip_from_hostname

LOGGER: ConsoleFileLogger = get_root_logger()

# Environment variable to control OSS mode
TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")


@memoize_forever
def get_next_available_ipv6_address(
    ip: str,
    mask: int,
    increment: int = 1,
    max_attempts: int = 100,
) -> str:
    """
    Finds the next available IP address in a network range that is greater than the given remote IP address.
    Args:
        ip (str): The IP address prefix.
        mask (int): The prefix length of the IP address.
        increment (int, optional): The increment value to use when searching for the next IP. Defaults to 1.
        max_attempts (int, optional): The maximum number of attempts to find the next IP. Defaults to 1000.
    Returns:
        str: The found next available IP address as a string.
    """
    network_addr = ipaddress.IPv6Network(f"{ip}/{mask}", strict=False)
    target_ip = ipaddress.IPv6Address(ip)
    curr_ip = ipaddress.IPv6Address(network_addr.network_address)
    for _ in range(max_attempts):
        next_ip = curr_ip + increment
        if next_ip > target_ip and next_ip in network_addr:
            return str(next_ip)
        curr_ip = next_ip
    raise InsufficientInputError(
        f"Unable to find the next available IP from the IP {ip}/{mask}"
    )


async def async_create_optical_switch_ixia_connection_assets(
    hostname: str,
) -> t.List[IxiaEndpointInfo]:
    # Lazy imports for OSS compatibility - only needed when this method is called
    from neteng.netcastle.optical_switch.service import thrift_types as op_sw_types
    from neteng.netcastle.optical_switch.utils.common_utils import async_is_ixia
    from neteng.netcastle.utils.optical_switch_utils import (
        async_get_current_connections,
    )

    conns: t.List[op_sw_types.ConnectionEntry] = await async_get_current_connections(
        hostname1=hostname
    )
    ixia_assets: t.List[IxiaEndpointInfo] = []
    for conn in conns:
        if await async_is_ixia(conn.device_b):
            ixia_hostname = (conn.device_b.split(":"))[0]
            remote_device_name, remote_intf_name = conn.device_a.split(":")
            intf_name = conn.device_b.split(":")[1]
        elif await async_is_ixia(conn.device_a):
            ixia_hostname = (conn.device_a.split(":"))[0]
            remote_device_name, remote_intf_name = conn.device_b.split(":")
            intf_name = conn.device_a.split(":")[1]
        else:
            continue
        slot_num, port_num = intf_name.split("/")
        chassis_ip = await async_get_ip_from_hostname(ixia_hostname)
        ixia_assets.append(
            IxiaEndpointInfo(
                ixia_hostname=to_fb_uqdn(ixia_hostname),
                ixia_chassis_ip=chassis_ip,
                ixia_slot_num=slot_num,
                ixia_port_num=port_num,
                remote_device_name=hostname,
                remote_intf_name=remote_intf_name,
                is_logical_port=False,
            )
        )
    return ixia_assets


def fetch_ixia_password_oss() -> str:
    """
    OSS-compatible implementation to fetch Ixia password from a CSV file.

    Reads the password from 'vendor_ixia_pwd.csv' file which should be placed
    in the oss_topology_info directory. The CSV should contain comments starting
    with '#' and a single line with the password value.

    Returns:
        The Ixia password string.

    Raises:
        FileNotFoundError: If the vendor_ixia_pwd.csv file is not found.
        ValueError: If the CSV file exists but doesn't contain a valid password.
    """
    import csv
    from pathlib import Path

    # Look for the CSV file in the oss_topology_info directory
    csv_path = (
        Path(__file__).parent.parent / "oss_topology_info" / "vendor_ixia_pwd.csv"
    )

    if not csv_path.exists():
        raise FileNotFoundError(
            f"Ixia password file not found at: {csv_path}\n"
            "Please create the file 'vendor_ixia_pwd.csv' in the oss_topology_info "
            "directory with a single row containing the Ixia password.\n"
            "Format: password (lines starting with '#' are treated as comments)\n"
            "Example content:\n"
            "# Ixia vendor password\n"
            "your_ixia_password_here"
        )

    try:
        with open(csv_path, "r") as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and comments
                if not line or line.startswith("#"):
                    continue
                # First non-comment, non-empty line is the password
                password = line
                return password

            # If we get here, no valid password was found
            raise ValueError(
                f"Ixia password file at {csv_path} does not contain a valid password.\n"
                "Please add the Ixia password on a new line (lines starting with '#' are comments).\n"
                "Example content:\n"
                "# Ixia vendor password\n"
                "your_ixia_password_here"
            )
    except IOError as e:
        raise ValueError(
            f"Error reading Ixia password file at {csv_path}: {e}\n"
            "Please ensure the file is readable and properly formatted."
        )


def fetch_ixia_password() -> str:
    """
    Abstraction layer for fetching Ixia password.

    Uses TAAC_OSS environment variable to determine implementation:
    - OSS mode (TAAC_OSS=1): Reads password from vendor_ixia_pwd.csv file
    - Meta mode (default): Uses Meta's internal keychain service

    Returns:
        The Ixia password string.

    Raises:
        FileNotFoundError: In OSS mode, if the CSV file is not found.
        ValueError: In OSS mode, if the CSV file is invalid.
        Exception: In Meta mode, if keychain retrieval fails.
    """
    if TAAC_OSS:
        return fetch_ixia_password_oss()
    else:
        # Lazy import for OSS compatibility - only needed when this method is called in Meta mode
        from taac.internal.internal_utils import (
            fetch_ixia_password_internal,
        )

        return fetch_ixia_password_internal()


def get_attr_value(value: t.Any) -> ixia_types.AttrValue:
    """Convert a Python value to an Ixia AttrValue type."""
    if isinstance(value, list):
        if all(isinstance(item, str) for item in value):
            return ixia_types.AttrValue(str_list=value)
        elif all(isinstance(item, int) for item in value):
            return ixia_types.AttrValue(integer_list=value)
    elif isinstance(value, str):
        return ixia_types.AttrValue(str=value)
    elif isinstance(value, int):
        return ixia_types.AttrValue(integer=value)
    elif isinstance(value, bool):
        return ixia_types.AttrValue(boolean=value)
    raise ValueError(f"Unsupported type {type(value)} for value {value}")


async def async_get_ixia_logical_port_oss(
    hostname: str,
    port_number: int,
    username: t.Optional[str] = None,
    password: t.Optional[str] = None,
) -> int:
    """
    OSS-compatible implementation of async_get_ixia_logical_port.

    In OSS mode, simply returns the port number as-is (pass-through).
    This is suitable for OSS environments where the Ixia model lookup
    and resource group APIs may not be available.

    Args:
        hostname: The Ixia chassis hostname (unused in OSS mode)
        port_number: The physical port number
        username: Optional username (unused in OSS mode)
        password: Optional password (unused in OSS mode)

    Returns:
        The port number as-is (pass-through)
    """
    return port_number


async def async_get_ixia_logical_port(
    hostname: str,
    port_number: int,
    username: t.Optional[str] = None,
    password: t.Optional[str] = None,
) -> int:
    """
    Abstraction layer for getting Ixia logical port.

    Uses TAAC_OSS environment variable to determine implementation:
    - OSS mode (TAAC_OSS=1): Returns port_number as-is (pass-through)
    - Meta mode (default): Uses netcastle's async_get_ixia_logical_port

    Args:
        hostname: The Ixia chassis hostname
        port_number: The physical port number
        username: Optional username for Ixia authentication
        password: Optional password for Ixia authentication

    Returns:
        The logical port number
    """
    if TAAC_OSS:
        return await async_get_ixia_logical_port_oss(
            hostname, port_number, username, password
        )
    else:
        # Import here to avoid circular imports and allow OSS mode without netcastle
        from neteng.netcastle.utils.ixia_utils import (
            async_get_ixia_logical_port as netcastle_async_get_ixia_logical_port,
        )

        return await netcastle_async_get_ixia_logical_port(
            hostname, port_number, username, password
        )
