# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

import ipaddress
from dataclasses import replace

from taac.abstractions.topologies.ebb_full_scale import (
    EBB_AS_NUMBERS,
    EBB_FULL_SCALE_PORT_MAP,
    ebb_full_scale_topology,
    EBB_PARENT_NETWORKS,
    EBB_PEER_GROUPS,
)
from taac.abstractions.topology import (
    DeviceGroupPartition,
    DeviceGroupSpec,
    ExtendedCommunity,
    ExtendedCommunityKind,
    FormulaicNextHopSource,
    NextHopDistribution,
    NextHopIntent,
    NextHopMode,
    OpenRMode,
    PeerPrefixDistribution,
    PrefixMembership,
    RouteAttributeDistribution,
    RouteAttributePool,
    RouteScaleMode,
    RouteSender,
    StandardCommunity,
    TaskCompatibilityProfile,
)

_PREFIXES_PER_PEER = 750
_UG_BACKPRESSURE_BASE = ebb_full_scale_topology(
    openr_mode=OpenRMode.NONE,
    include_bgpmon=False,
    include_legacy_community_rows=False,
)

UG_BACKPRESSURE_PORT_MAP = dict(EBB_FULL_SCALE_PORT_MAP)
UG_BACKPRESSURE_PARENT_NETWORKS = {
    key: value for key, value in EBB_PARENT_NETWORKS.items() if key != "bgpmon_v6"
}
UG_BACKPRESSURE_PEER_GROUPS = {
    name: peer_group
    for name, peer_group in EBB_PEER_GROUPS.items()
    if peer_group in _UG_BACKPRESSURE_BASE.peer_groups
}
UG_BACKPRESSURE_AS_NUMBERS = {
    name: asn for name, asn in EBB_AS_NUMBERS.items() if name != "bgpmon"
}

UG_BACKPRESSURE_STORM_ROUTE_ATTRIBUTES = RouteAttributePool(
    community_rows=tuple(
        (
            StandardCommunity(asn=65531, value=50300),
            StandardCommunity(asn=65529, value=30000 + index),
        )
        for index in range(32)
    ),
    extended_community_rows=tuple(
        (
            ExtendedCommunity(
                kind=ExtendedCommunityKind.ROUTE_TARGET,
                administrator=65529,
                assigned_number=40000 + index,
            ),
        )
        for index in range(16)
    ),
    distribution=RouteAttributeDistribution.ROUND_ROBIN,
)

_BASE_DEVICE_GROUPS = {
    device_group.name: device_group
    for device_group in _UG_BACKPRESSURE_BASE.device_groups
}


def _offset_address(address: str, step: int | str, offset: int) -> str:
    parsed = ipaddress.ip_address(address)
    step_value = step if isinstance(step, int) else int(ipaddress.ip_address(step))
    return str(type(parsed)(int(parsed) + step_value * offset))


def _slice_next_hop(
    next_hop: NextHopIntent,
    *,
    start_index: int,
    peer_count: int,
) -> NextHopIntent:
    if next_hop.mode is NextHopMode.SELF:
        return next_hop
    if next_hop.distribution is not NextHopDistribution.PER_PEER:
        raise ValueError("EBB backpressure next hops must be distributed per peer")
    if next_hop.mode is NextHopMode.FORMULAIC:
        source = next_hop.formulaic_source
        if source is None:
            raise ValueError("formulaic next-hop intent is missing its source")
        return replace(
            next_hop,
            formulaic_source=FormulaicNextHopSource(
                start=_offset_address(source.start, source.step, start_index),
                step=source.step,
                parent_network=source.parent_network,
            ),
        )
    explicit_source = next_hop.explicit_source
    if explicit_source is None:
        raise ValueError("explicit next-hop intent is missing its source")
    addresses = explicit_source.addresses[start_index : start_index + peer_count]
    if len(addresses) != peer_count:
        raise ValueError("explicit next-hop source does not cover its partition")
    return replace(
        next_hop,
        explicit_source=replace(explicit_source, addresses=addresses),
    )


def _legacy_prefix_name(device_group_name: str) -> str:
    if "_IBGP_" in device_group_name:
        afi, suffix = device_group_name.removeprefix("DEVICE_GROUP_").split(
            "_IBGP_",
            1,
        )
        return f"PREFIX_POOL_IBGP_{afi}_{suffix}"
    return device_group_name.replace("DEVICE_GROUP_", "PREFIX_POOL_", 1)


def _partitioned_leaf(
    base_name: str,
    *,
    suffix: str | None,
    ordinal: int,
    start_index: int,
    peer_count: int,
    total_peer_count: int,
    legacy_index: int,
    route_attributes: RouteAttributePool | None = None,
) -> DeviceGroupSpec:
    base = _BASE_DEVICE_GROUPS[base_name]
    if len(base.prefix_advertisements) != 1:
        raise ValueError(f"partitioned EBB group {base_name!r} needs one advertisement")
    name = base.name if suffix is None else f"{base.name}_{suffix.lower()}"
    legacy_device_group_name = base.legacy_ixia_device_group_name
    if legacy_device_group_name is None:
        raise ValueError(f"partitioned EBB group {base_name!r} needs a legacy name")
    if suffix is not None:
        legacy_device_group_name = f"{legacy_device_group_name}_{suffix}"
    advertisement = base.prefix_advertisements[0]
    distribution = advertisement.allocation.peer_distribution
    membership = (
        advertisement.membership
        if distribution is PeerPrefixDistribution.SHARED
        else PrefixMembership(
            start_index=start_index * _PREFIXES_PER_PEER,
            prefix_count=peer_count * _PREFIXES_PER_PEER,
        )
    )
    partitioned_advertisement = replace(
        advertisement,
        name=f"{name}_routes",
        allocation=replace(
            advertisement.allocation,
            route_scale_mode=RouteScaleMode.WINDOWED,
        ),
        membership=membership,
        next_hop=_slice_next_hop(
            advertisement.next_hop,
            start_index=start_index,
            peer_count=peer_count,
        ),
        route_attributes=route_attributes,
        legacy_ixia_name=_legacy_prefix_name(legacy_device_group_name),
        requires_route_mutation=True,
    )
    return replace(
        base,
        name=name,
        peer_count=peer_count,
        address_plan=replace(base.address_plan, start_index=start_index),
        prefix_advertisements=(partitioned_advertisement,),
        legacy_ixia_tag_name=legacy_device_group_name.replace(
            "DEVICE_GROUP_",
            "BGP_PEER_",
            1,
        ),
        legacy_ixia_device_group_name=legacy_device_group_name,
        partition=DeviceGroupPartition(
            family=base.name,
            ordinal=ordinal,
            start_index=start_index,
            total_peer_count=total_peer_count,
        ),
        legacy_ixia_device_group_index=legacy_index,
    )


def _unpartitioned_leaf(base_name: str, legacy_index: int) -> DeviceGroupSpec:
    return replace(
        _BASE_DEVICE_GROUPS[base_name],
        legacy_ixia_device_group_index=legacy_index,
    )


def _ibgp_plane_leaves(plane: int) -> tuple[DeviceGroupSpec, ...]:
    base_index = (plane - 1) * 6
    v6_dc = f"dg_ibgp_v6_dc_p{plane}"
    v4_dc = f"dg_ibgp_v4_dc_p{plane}"
    return (
        _partitioned_leaf(
            v6_dc,
            suffix=None,
            ordinal=0,
            start_index=0,
            peer_count=60,
            total_peer_count=62,
            legacy_index=base_index,
        ),
        _partitioned_leaf(
            v6_dc,
            suffix="DRAIN",
            ordinal=1,
            start_index=60,
            peer_count=2,
            total_peer_count=62,
            legacy_index=base_index + 1,
            route_attributes=(
                UG_BACKPRESSURE_STORM_ROUTE_ATTRIBUTES if plane == 1 else None
            ),
        ),
        _unpartitioned_leaf(f"dg_ibgp_v6_mp_p{plane}", base_index + 2),
        _partitioned_leaf(
            v4_dc,
            suffix=None,
            ordinal=0,
            start_index=0,
            peer_count=60,
            total_peer_count=62,
            legacy_index=base_index + 3,
        ),
        _partitioned_leaf(
            v4_dc,
            suffix="DRAIN",
            ordinal=1,
            start_index=60,
            peer_count=2,
            total_peer_count=62,
            legacy_index=base_index + 4,
        ),
        _unpartitioned_leaf(f"dg_ibgp_v4_mp_p{plane}", base_index + 5),
    )


_UPLINK_LEAVES = (
    _partitioned_leaf(
        "dg_ebgp_v6",
        suffix=None,
        ordinal=0,
        start_index=0,
        peer_count=116,
        total_peer_count=140,
        legacy_index=0,
    ),
    _partitioned_leaf(
        "dg_ebgp_v6",
        suffix="SLOW",
        ordinal=1,
        start_index=116,
        peer_count=20,
        total_peer_count=140,
        legacy_index=4,
    ),
    _partitioned_leaf(
        "dg_ebgp_v6",
        suffix="DRAIN",
        ordinal=2,
        start_index=136,
        peer_count=4,
        total_peer_count=140,
        legacy_index=1,
    ),
    _partitioned_leaf(
        "dg_ebgp_v4",
        suffix=None,
        ordinal=0,
        start_index=0,
        peer_count=136,
        total_peer_count=140,
        legacy_index=2,
    ),
    _partitioned_leaf(
        "dg_ebgp_v4",
        suffix="DRAIN",
        ordinal=1,
        start_index=136,
        peer_count=4,
        total_peer_count=140,
        legacy_index=3,
    ),
)

_IBGP_LEAVES = tuple(
    leaf for plane in range(1, 5) for leaf in _ibgp_plane_leaves(plane)
)

UG_BACKPRESSURE = replace(
    _UG_BACKPRESSURE_BASE,
    name="ug_backpressure",
    legacy_profile=None,
    task_compatibility_profile=TaskCompatibilityProfile.UG_BACKPRESSURE,
    device_groups=(*_UPLINK_LEAVES, *_IBGP_LEAVES),
    device_config=replace(
        _UG_BACKPRESSURE_BASE.device_config,
        update_group_enable=True,
    ),
    route_senders=(
        RouteSender(
            device_group="dg_ibgp_v6_dc_p1_drain",
            prefix_advertisement="dg_ibgp_v6_dc_p1_drain_routes",
        ),
    ),
)


__all__ = (
    "UG_BACKPRESSURE",
    "UG_BACKPRESSURE_AS_NUMBERS",
    "UG_BACKPRESSURE_PARENT_NETWORKS",
    "UG_BACKPRESSURE_PEER_GROUPS",
    "UG_BACKPRESSURE_PORT_MAP",
    "UG_BACKPRESSURE_STORM_ROUTE_ATTRIBUTES",
)
