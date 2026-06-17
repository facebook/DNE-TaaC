# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
from __future__ import annotations

import os
import re
import typing as t
from typing import cast

from taac.oss_topology_info.circuit_info_loader import (
    DesiredCircuitRecord,
    get_circuits_for_hostname_oss,
)
from taac.utils.oss_taac_asyncio_decorators import (
    memoize_forever as async_memoize_forever,
    memoize_timed as async_memoize_timed,
)
from taac.utils.skynet_oss_adapters import (
    convert_to_skynet_desired_circuit,
)

# Environment variable to control OSS mode
TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

# Only import Meta-internal modules when not in OSS mode
if not TAAC_OSS:
    from neteng.netcastle.utils.skynet_utils import (
        async_get_device_info_from_fbnet,
        get_skynet_thrift_client,
    )
    from nettools.skynet.Query import types as query_types
    from nettools.skynet.SkynetStructs import types as skynet_types
else:

    class _UnavailableSkynetTypes:
        def __getattr__(self, attr: str) -> t.Any:  # pragma: no cover - guard
            raise RuntimeError("Skynet Query/Struct types are unavailable in OSS mode")

    query_types = cast(t.Any, _UnavailableSkynetTypes())  # pyre-ignore[31]
    skynet_types = cast(t.Any, _UnavailableSkynetTypes())  # pyre-ignore[31]


SKYNET_TIER: str = "skynet_thrift"


def get_skynet_circuit_query_filter(
    name, standard_hostname, ignore_ckt_status: bool = False
) -> t.Any:
    """
    Query filters to be used for fetching the device circuit information
    Name: field which corresponding to the name of the device
    standard_hostname: hostname of the test device whose circuit info is being fetched

    Returns Query type which will be used to fetch the device information
    """
    exprs = [
        query_types.Expr(
            name=name, op=query_types.Op.EQUAL, values=[standard_hostname]
        ),
    ]
    if not ignore_ckt_status:
        exprs.append(
            query_types.Expr(name="status", op=query_types.Op.EQUAL, values=["3"])
        )

    return query_types.Query(
        exprs=exprs,
    )


@async_memoize_timed(3600)
async def async_get_skynet_desired_circuit(
    standard_hostname: str, ignore_ckt_status: bool = False
) -> t.List[t.Any]:
    """
    For a given device reserved for the test-run, skynet query for its production circuits
    are done to capture the circuit information such as the interface name, device name and
    its vendor name on both the local and remote side
    """
    if TAAC_OSS:
        circuits = await async_get_skynet_desired_circuit_oss(
            standard_hostname, ignore_ckt_status=ignore_ckt_status
        )
        return _convert_oss_circuits_to_skynet_types(circuits)

    fields = [
        "a_endpoint.name",
        "a_endpoint.device.name",
        "a_endpoint.device.desired_platform.os_type_name",
        "z_endpoint.name",
        "z_endpoint.device.name",
        "z_endpoint.device.desired_platform.os_type_name",
        "a_endpoint.aggregated_interface.name",
        "z_endpoint.aggregated_interface.name",
        "status",
        "role.name",
    ]
    a_query = get_skynet_circuit_query_filter(
        "z_endpoint.device.name",
        standard_hostname,
        ignore_ckt_status=ignore_ckt_status,
    )
    z_query = get_skynet_circuit_query_filter(
        "a_endpoint.device.name",
        standard_hostname,
        ignore_ckt_status=ignore_ckt_status,
    )
    async with get_skynet_thrift_client() as client:
        return list(await client.getDesiredCircuit(a_query, fields=fields)) + list(
            await client.getDesiredCircuit(z_query, fields=fields)
        )


@async_memoize_timed(3600)
async def async_get_skynet_desired_circuit_oss(
    standard_hostname: str, ignore_ckt_status: bool = False
) -> t.List[DesiredCircuitRecord]:
    """OSS implementation returning CSV-backed circuit records."""

    return get_circuits_for_hostname_oss(
        standard_hostname, ignore_ckt_status=ignore_ckt_status
    )


def _convert_oss_circuits_to_skynet_types(
    circuits: t.Iterable[DesiredCircuitRecord],
) -> t.List[t.Any]:
    if TAAC_OSS:
        return [convert_to_skynet_desired_circuit(circuit) for circuit in circuits]

    return []


@async_memoize_timed(3600)
async def async_get_device_name(fabric_alias: str) -> t.Optional[str]:
    """
    Given the fabric alias of a hostname, this stub will be used to fetch
    the standard_hostname and vendor/platform OS information from FBNET
    """
    if "rsw" not in fabric_alias or re.compile(r"\.m\d{3}\.").search(fabric_alias):
        return fabric_alias
    fields = ["name"]

    query = query_types.Query(
        exprs=[
            query_types.Expr(
                name="fabric_alias", op=query_types.Op.EQUAL, values=[fabric_alias]
            )
        ]
    )

    async with get_skynet_thrift_client() as client:
        # pyrefly: ignore [bad-argument-type]
        result = await client.getDesiredNetworkSwitch(query, fields=fields)
        if result:
            return result[0].name


async def async_get_fabric_aliases(
    standard_hostnames: t.List[str],
) -> t.Dict[str, str]:
    """
    Given the list of standard hostnames, this will be used to create a map
    of the standard hostnames to fabric alias names.

    NOTE: For all non-rsws the standard hostname and fabric_alias names are same

    For RSWs:
        - standard_hostname: rsw007.p007.f01.frc3
        - fabric_alias: rsw1af.21.frc3
    """
    name_to_fabric_alias: t.Dict[str, str] = {}
    fields = ["name", "fabric_alias"]
    query = query_types.Query(
        exprs=[
            query_types.Expr(
                name="name", op=query_types.Op.EQUAL, values=standard_hostnames
            )
        ]
    )

    async with get_skynet_thrift_client() as client:
        # pyrefly: ignore [bad-argument-type]
        result = await client.getDesiredNetworkSwitch(query, fields=fields)
        for res in result:
            # {standard_hostname : fabric_alias}
            # pyre-fixme[6]: For 1st argument expected `str` but got `Optional[str]`.
            # pyre-fixme[6]: For 2nd argument expected `str` but got `Optional[str]`.
            name_to_fabric_alias[res.name] = res.fabric_alias
        return name_to_fabric_alias


@async_memoize_timed(3600)
async def async_get_vendor_info_from_fbnet(device_name: str) -> t.Optional[str]:
    """
    Given the device_name, queries FBNet to return the vendor name
    """
    device_info = await async_get_device_info_from_fbnet(
        device_name, "desired_platform.os_type_name"
    )
    if device_info and device_info.desired_platform:
        return device_info.desired_platform.os_type_name


@async_memoize_forever
async def get_skynet_device_role(entity: str) -> t.Optional[str]:
    """
    Abstraction layer for getting device role from Skynet.

    Uses TAAC_OSS environment variable to determine implementation:
    - OSS mode (TAAC_OSS=1): Uses CSV-based device info lookup
    - Meta mode (default): Uses Skynet Thrift client

    Args:
        entity: Device hostname/entity name to look up

    Returns:
        Device role string if found, None otherwise
    """
    if TAAC_OSS:
        return await _get_skynet_device_role_oss(entity)
    else:
        fields = ["name", "device_role.name"]
        query = query_types.Query(
            exprs=[
                query_types.Expr(name="name", op=query_types.Op.EQUAL, values=[entity])
            ]
        )
        async with get_skynet_thrift_client() as client:
            try:
                # pyrefly: ignore [bad-argument-type]
                resp = await client.getDesiredNetworkDevice(query, fields)
            except Exception:
                return None

            for device in resp:
                if device.name and device.name == entity:
                    if device_role := device.device_role:
                        return device_role.name
        return None


async def _get_skynet_device_role_oss(entity: str) -> t.Optional[str]:
    """
    OSS implementation: Get device role from hostname using CSV lookup.

    Args:
        entity: Device hostname/entity name to look up

    Returns:
        Device role string if found, None otherwise
    """
    from taac.oss_topology_info.device_info_loader import (
        get_role_from_hostname_oss,
    )

    return get_role_from_hostname_oss(entity)


async def async_get_skynet_primary_ipv6(hostname: str) -> t.Optional[str]:
    """
    Get primary ipv6 address from skynet
    """
    fields = ["primary_ipv6"]
    query = query_types.Query(
        exprs=[
            query_types.Expr(name="name", op=query_types.Op.EQUAL, values=[hostname])
        ]
    )
    async with get_skynet_thrift_client() as client:
        # pyrefly: ignore [bad-argument-type]
        result = await client.getDesiredNetworkSwitch(query, fields=fields)
        if result:
            return result[0].primary_ipv6
