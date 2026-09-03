# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Resolve FBOSS port identity from the on-box platform mapping.

A from-scratch agent config still must not invent port identity: the logical
port ID and the ASIC port profile for an interface name (e.g. ``eth1/6/1`` ->
id 11, profileID 38) are fixed by the platform and live in the box's
``MetaGeneratedPlatformMapping_*.json``. These helpers parse that mapping so the
generator translates interface names -> ``(logicalID, profileID)`` and can
enumerate the full port list, rather than hard-coding platform-specific IDs.

Pure: callers pass the already-parsed mapping ``dict`` (the provisioning task
reads the JSON off the box); nothing here does IO.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

# Profile preference for MORGAN800CC edge/core links: prefer the 400G optical
# profile (38) as seen on the reference boxes, then fall back through the other
# supported profiles. Callers may override per interface.
DEFAULT_PROFILE_PREFERENCE: t.Tuple[int, ...] = (38, 39, 25, 23)


@dataclass(frozen=True)
class PortEntry:
    """One physical port from the platform mapping."""

    logical_id: int
    name: str
    supported_profiles: t.Tuple[int, ...]


def parse_platform_mapping(mapping: t.Mapping[str, t.Any]) -> t.Dict[str, PortEntry]:
    """Parse a platform-mapping JSON dict into ``{iface_name: PortEntry}``.

    The mapping's ``ports`` is a dict keyed by port-id string; each value has a
    ``mapping`` (``id`` / ``name``) and a ``supportedProfiles`` dict keyed by
    profile-id string.
    """
    ports = mapping.get("ports") or {}
    out: t.Dict[str, PortEntry] = {}
    for _key, val in ports.items():
        m = (val or {}).get("mapping") or {}
        name = m.get("name")
        pid = m.get("id")
        if name is None or pid is None:
            continue
        profiles = (val or {}).get("supportedProfiles") or {}
        prof_ids = tuple(sorted(int(p) for p in profiles.keys()))
        out[str(name)] = PortEntry(
            logical_id=int(pid), name=str(name), supported_profiles=prof_ids
        )
    return out


def choose_profile(
    supported: t.Sequence[int],
    preference: t.Sequence[int] = DEFAULT_PROFILE_PREFERENCE,
) -> int:
    """Pick a profile ID from ``supported`` following ``preference`` order."""
    for p in preference:
        if p in supported:
            return p
    if supported:
        return supported[-1]
    raise ValueError("port has no supported profiles in the platform mapping")


def resolve_port(
    port_map: t.Mapping[str, PortEntry],
    iface_name: str,
    preference: t.Sequence[int] = DEFAULT_PROFILE_PREFERENCE,
) -> t.Tuple[int, int]:
    """Resolve ``iface_name`` -> ``(logical_id, profile_id)`` via the mapping."""
    entry = port_map.get(iface_name)
    if entry is None:
        raise KeyError(
            f"interface {iface_name!r} not found in the platform mapping; "
            f"known example ports: {sorted(port_map)[:4]}"
        )
    return entry.logical_id, choose_profile(entry.supported_profiles, preference)


def all_ports(port_map: t.Mapping[str, PortEntry]) -> t.List[PortEntry]:
    """All ports sorted by logical ID (for building the full port list)."""
    return sorted(port_map.values(), key=lambda p: p.logical_id)
