# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""OSS-safe NetWhoAmI device-identity lookup.

In Meta mode this resolves a host's identity via the internal NetWhoAmI service
and returns the live ``netwhoami.types.NetWhoAmI`` thrift object. In OSS mode
(``TAAC_OSS=1``) it returns a lightweight, duck-typed stand-in that exposes the
same attribute surface callers rely on (``.name`` and enum-style fields whose
``.name`` yields the symbolic value, e.g. ``nw.hw.name == "MORGAN800CC"``), built
either from registered OSS mock data or as a minimal name-only fallback.

All Meta-only imports (``neteng.netwhoami``, ``netwhoami``, ``nettools``) are
loaded lazily inside the ``if not TAAC_OSS`` guard so this module is shippable.
"""

from __future__ import annotations

import os
import typing as t
from dataclasses import dataclass, field

from taac.test_as_a_config import types as taac_types

TAAC_OSS: bool = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

# Registered OSS mock device data keyed by hostname (string fields only).
OSS_MOCK_DEVICE_DATA: t.Dict[str, taac_types.MockDeviceInfo] = {}

# Simple async-safe memoization (replaces libfb's memoize_timed, which is not
# OSS-shippable). Maps hostname -> resolved identity for the process lifetime.
_WHOAMI_CACHE: t.Dict[str, t.Any] = {}


@dataclass
class _OssEnumValue:
    """Duck-types a thrift enum member: exposes ``.name`` like ``Hardware.X``."""

    name: str


@dataclass
class _OssNetWhoAmI:
    """OSS stand-in for ``netwhoami.types.NetWhoAmI``.

    Enum-style fields are wrapped in ``_OssEnumValue`` so callers that read
    ``nw.hw.name`` / ``nw.role.name`` / ``nw.operating_system.name`` work
    identically against this object and the real thrift type.
    """

    name: str
    hw: t.Optional[_OssEnumValue] = None
    role: t.Optional[_OssEnumValue] = None
    operating_system: t.Optional[_OssEnumValue] = None
    asic: t.Optional[_OssEnumValue] = None
    routing_protocol: t.Optional[_OssEnumValue] = None
    dc_type: t.Optional[_OssEnumValue] = None
    network_area_type: t.Optional[_OssEnumValue] = None
    network_type: t.Optional[_OssEnumValue] = None
    dc: t.Optional[str] = None
    region: t.Optional[str] = None
    asset_id: t.Optional[int] = None
    ai_zone: str = field(default="")


def add_oss_mock_device_data(host: str, device_info: taac_types.MockDeviceInfo) -> None:
    """Register OSS-compatible mock device data (string fields) for a host."""
    OSS_MOCK_DEVICE_DATA[host] = device_info


def _enum(value: t.Optional[str]) -> t.Optional[_OssEnumValue]:
    return _OssEnumValue(name=value) if value else None


def _oss_whoami_from_mock(device_info: taac_types.MockDeviceInfo) -> _OssNetWhoAmI:
    """Build an OSS NetWhoAmI stand-in from string-field MockDeviceInfo."""
    return _OssNetWhoAmI(
        name=device_info.name,
        hw=_enum(getattr(device_info, "hardware", "")),
        role=_enum(getattr(device_info, "role", "")),
        operating_system=_enum(getattr(device_info, "operating_system", "")),
        asic=_enum(getattr(device_info, "asic", "")),
        routing_protocol=_enum(getattr(device_info, "routing_protocol", "")),
        dc_type=_enum(getattr(device_info, "dc_type", "")),
        network_area_type=_enum(getattr(device_info, "network_area_type", "")),
        network_type=_enum(getattr(device_info, "network_type", "")),
        dc=getattr(device_info, "dc", "") or None,
        region=getattr(device_info, "region", "") or None,
        asset_id=getattr(device_info, "asset_id", None) or None,
    )


async def fetch_whoami(host: str) -> t.Any:
    """Resolve a host's device identity.

    Returns a ``netwhoami.types.NetWhoAmI`` in Meta mode, or an ``_OssNetWhoAmI``
    stand-in in OSS mode. The result is cached per-host for the process lifetime.
    """
    if host in _WHOAMI_CACHE:
        return _WHOAMI_CACHE[host]

    # OSS-registered mock data always wins (works in both modes).
    if host in OSS_MOCK_DEVICE_DATA:
        result = _oss_whoami_from_mock(OSS_MOCK_DEVICE_DATA[host])
        _WHOAMI_CACHE[host] = result
        return result

    if TAAC_OSS:
        # OSS, host not mocked: minimal name-only identity.
        result = _OssNetWhoAmI(name=host)
        _WHOAMI_CACHE[host] = result
        return result

    # Meta path: all internal imports are lazy and live under the guard.
    if not TAAC_OSS:
        from neteng.netwhoami import fetch
        from netwhoami import types as netwhoami_types

        try:
            result = (await fetch.fetch_one(host))._to_py3()
        except Exception:
            result = netwhoami_types.NetWhoAmI(name=host)
        _WHOAMI_CACHE[host] = result
        return result
