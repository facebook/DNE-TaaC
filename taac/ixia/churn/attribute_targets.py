# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""IXIA discovery and snapshot primitives for BGP attribute targets."""

from __future__ import annotations

import re
import typing as t

from taac.constants import TestCaseFailure
from taac.ixia.churn.attribute_operations import normalize_boolean
from taac.ixia.churn.attribute_state import IxiaAttributePoolState
from taac.ixia.route_geometry import (
    IxiaOverlayVector,
    IxiaValueVector,
)


def discover_named_prefix_pools(
    ixia: t.Any, requested_names: t.Sequence[str]
) -> dict[str, t.Any]:
    prefix_pool_regex = (
        "^(?:" + "|".join(re.escape(name) for name in requested_names) + ")$"
    )
    matches = ixia.get_prefix_pools_by_regexes(prefix_pool_regex=prefix_pool_regex)
    pools_by_name: dict[str, t.Any] = {}
    duplicate_matches: set[str] = set()
    for pool in matches:
        name = str(getattr(pool, "Name", ""))
        if name in pools_by_name:
            duplicate_matches.add(name)
        pools_by_name[name] = pool
    if duplicate_matches:
        raise TestCaseFailure(
            f"IXIA pool discovery returned duplicate names: {sorted(duplicate_matches)}"
        )
    expected_names = set(requested_names)
    actual_names = set(pools_by_name)
    if actual_names != expected_names:
        raise TestCaseFailure(
            "IXIA pool discovery mismatch: "
            f"missing={sorted(expected_names - actual_names)}; "
            f"unexpected={sorted(actual_names - expected_names)}"
        )
    return pools_by_name


def mapped_peer_addresses(
    ixia: t.Any,
    pool: t.Any,
    normalize_address: t.Callable[[t.Any], str],
) -> tuple[str, ...]:
    return tuple(
        normalize_address(value)
        for value in ixia.map_prefix_pool_to_bgp_peer(pool).parent.Address.Values
    )


def route_property(pool: t.Any, afi: str) -> t.Any:
    collection = pool.BgpIPRouteProperty if afi == "ipv4" else pool.BgpV6IPRouteProperty
    values = collection.find()
    if len(values) != 1:
        raise TestCaseFailure(f"expected one {afi} BGP route property")
    return values[0]


def capture_value_vector(handle: t.Any, rows: int, label: str) -> IxiaValueVector:
    return IxiaValueVector.capture(handle, rows, label)


def capture_topology_vector(
    handle: t.Any,
    rows: int,
    label: str,
    expected: t.Any,
    *,
    boolean: bool = False,
) -> IxiaOverlayVector:
    vector = IxiaOverlayVector.capture(handle, rows, label)
    observed = vector.baseline_value(0)
    matches = (
        normalize_boolean(observed) == bool(expected)
        if boolean
        else str(observed).lower() == str(expected).lower()
    )
    if not matches:
        raise TestCaseFailure(
            f"{label} live base {observed!r} does not match topology "
            f"baseline {expected!r}"
        )
    return vector


def is_flat_pool(pool: t.Any, peer_count: int, routes_per_peer: int) -> bool:
    return (
        int(pool.Count) == peer_count * routes_per_peer
        and int(pool.NumberOfAddresses) == 1
    )


def capture_value_pool_state(
    *,
    pool: t.Any,
    route: t.Any,
    afi: str,
    plane: int,
    rows: tuple[int, ...],
    peer_ranges: tuple[tuple[int, int, str], ...],
    physical_row_count: int,
) -> IxiaAttributePoolState:
    return IxiaAttributePoolState(
        afi=afi,
        plane=plane,
        name=str(getattr(pool, "Name", "")),
        pool=pool,
        route=route,
        rows=rows,
        peer_ranges=peer_ranges,
        local_pref=capture_value_vector(
            route.LocalPreference, physical_row_count, "LocalPreference"
        ),
        med_enabled=capture_value_vector(
            route.EnableMultiExitDiscriminator,
            physical_row_count,
            "MED enable",
        ),
        med=capture_value_vector(
            route.MultiExitDiscriminator, physical_row_count, "MED"
        ),
        origin=capture_value_vector(route.Origin, physical_row_count, "Origin"),
    )


def capture_topology_pool_state(
    *,
    pool: t.Any,
    route: t.Any,
    afi: str,
    plane: int,
    rows: tuple[int, ...],
    peer_ranges: tuple[tuple[int, int, str], ...],
    physical_row_count: int,
    local_pref: t.Any,
    med: t.Any,
    origin: t.Any,
) -> IxiaAttributePoolState:
    return IxiaAttributePoolState(
        afi=afi,
        plane=plane,
        name=str(getattr(pool, "Name", "")),
        pool=pool,
        route=route,
        rows=rows,
        peer_ranges=peer_ranges,
        local_pref=capture_topology_vector(
            route.LocalPreference,
            physical_row_count,
            "LocalPreference",
            local_pref,
        ),
        med_enabled=capture_topology_vector(
            route.EnableMultiExitDiscriminator,
            physical_row_count,
            "MED enable",
            med is not None,
            boolean=True,
        ),
        # IXIA can retain any backing MED value while advertisement is disabled.
        # Capture that value for exact restore without assigning it semantics.
        med=(
            capture_topology_vector(
                route.MultiExitDiscriminator,
                physical_row_count,
                "MED",
                med,
            )
            if med is not None
            else IxiaOverlayVector.capture(
                route.MultiExitDiscriminator,
                physical_row_count,
                "MED",
            )
        ),
        origin=capture_topology_vector(
            route.Origin,
            physical_row_count,
            "Origin",
            origin,
        ),
    )
