# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

import ipaddress
import typing as t
from bisect import bisect_right
from dataclasses import dataclass

from taac.abstractions.topology.attributes import (
    AsPathSequence,
    ResolvedRouteProperties,
    RouteAttributeDistribution,
    RouteAttributePool,
)
from taac.abstractions.topology.model import PrefixAdvertisement
from taac.abstractions.topology.prefix import (
    FormulaicPrefixSource,
    NextHopDistribution,
    NextHopMode,
    PeerPrefixDistribution,
    PrefixSet,
)

_IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
_T = t.TypeVar("_T")


def _step_as_int(value: int | str, version: int) -> int:
    if isinstance(value, int):
        return value
    parsed = ipaddress.ip_address(value)
    if parsed.version != version:
        raise ValueError("step AFI does not match its starting address")
    return int(parsed)


def _address_from_int(value: int, version: int) -> _IPAddress:
    if version == 4:
        return ipaddress.IPv4Address(value)
    return ipaddress.IPv6Address(value)


class FormulaicPrefixSequence(t.Sequence[str]):
    def __init__(self, source: FormulaicPrefixSource) -> None:
        if (
            isinstance(source.count, bool)
            or not isinstance(source.count, int)
            or source.count <= 0
        ):
            raise ValueError("formulaic prefix count must be a positive integer")
        excluded = tuple(source.excluded_indices)
        candidate_span = source.count + len(excluded)
        if (
            any(
                isinstance(index, bool) or not isinstance(index, int)
                for index in excluded
            )
            or any(left >= right for left, right in zip(excluded, excluded[1:]))
            or any(index < 0 or index >= candidate_span for index in excluded)
        ):
            raise ValueError(
                "excluded indices must be unique, sorted, and inside the candidate span"
            )
        self.source = source
        self._start = ipaddress.ip_address(source.start_prefix)
        self._step = _step_as_int(source.prefix_step, self._start.version)
        self._excluded_logical_indices = tuple(
            candidate_index - ordinal
            for ordinal, candidate_index in enumerate(excluded)
        )

    def __len__(self) -> int:
        return self.source.count

    @t.overload
    def __getitem__(self, index: int) -> str: ...

    @t.overload
    def __getitem__(self, index: slice) -> tuple[str, ...]: ...

    def __getitem__(self, index: int | slice) -> str | tuple[str, ...]:
        if isinstance(index, slice):
            return tuple(self[offset] for offset in range(*index.indices(len(self))))
        logical_index = index + len(self) if index < 0 else index
        if logical_index < 0 or logical_index >= len(self):
            raise IndexError(index)
        candidate_index = logical_index + bisect_right(
            self._excluded_logical_indices,
            logical_index,
        )
        return str(
            _address_from_int(
                int(self._start) + candidate_index * self._step,
                self._start.version,
            )
        )


class FormulaicAddressSequence(t.Sequence[str]):
    def __init__(self, start: str, step: int | str, count: int) -> None:
        self._start = ipaddress.ip_address(start)
        self._step = _step_as_int(step, self._start.version)
        self._count = count

    def __len__(self) -> int:
        return self._count

    @t.overload
    def __getitem__(self, index: int) -> str: ...

    @t.overload
    def __getitem__(self, index: slice) -> tuple[str, ...]: ...

    def __getitem__(self, index: int | slice) -> str | tuple[str, ...]:
        if isinstance(index, slice):
            return tuple(self[offset] for offset in range(*index.indices(len(self))))
        normalized = index + len(self) if index < 0 else index
        if normalized < 0 or normalized >= len(self):
            raise IndexError(index)
        return str(
            _address_from_int(
                int(self._start) + normalized * self._step,
                self._start.version,
            )
        )


@dataclass(frozen=True)
class ResolvedRoutePath:
    prefix: str
    prefix_length: int
    next_hop: str
    route_properties: ResolvedRouteProperties


@dataclass(frozen=True)
class ResolvedPrefixSet:
    spec: PrefixSet
    prefixes: FormulaicPrefixSequence

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def afi(self) -> str:
        return self.spec.afi


class ResolvedRoutePathSequence(t.Sequence[ResolvedRoutePath]):
    def __init__(
        self,
        *,
        advertisement: PrefixAdvertisement,
        prefix_set: ResolvedPrefixSet,
        peer_index: int,
        self_next_hop: str,
        next_hops: t.Sequence[str] | None,
    ) -> None:
        self.advertisement = advertisement
        self.prefix_set = prefix_set
        self.peer_index = peer_index
        self.self_next_hop = self_next_hop
        self.next_hops = next_hops

    def __len__(self) -> int:
        return self.advertisement.allocation.prefixes_per_peer

    @t.overload
    def __getitem__(self, index: int) -> ResolvedRoutePath: ...

    @t.overload
    def __getitem__(self, index: slice) -> tuple[ResolvedRoutePath, ...]: ...

    def __getitem__(
        self,
        index: int | slice,
    ) -> ResolvedRoutePath | tuple[ResolvedRoutePath, ...]:
        if isinstance(index, slice):
            return tuple(self[offset] for offset in range(*index.indices(len(self))))
        slot = index + len(self) if index < 0 else index
        if slot < 0 or slot >= len(self):
            raise IndexError(index)
        allocation = self.advertisement.allocation
        membership = self.advertisement.membership
        relative_prefix_index = (
            slot
            if allocation.peer_distribution == PeerPrefixDistribution.SHARED
            else self.peer_index * allocation.prefixes_per_peer + slot
        )
        prefix_index = membership.start_index + relative_prefix_index
        if prefix_index < 0 or prefix_index >= len(self.prefix_set.prefixes):
            raise IndexError(
                f"advertisement {self.advertisement.name!r} resolved prefix index "
                f"{prefix_index} outside prefix set {self.prefix_set.name!r} with "
                f"{len(self.prefix_set.prefixes)} entries; membership starts at "
                f"{membership.start_index} and relative index is "
                f"{relative_prefix_index}"
            )
        return ResolvedRoutePath(
            prefix=self.prefix_set.prefixes[prefix_index],
            prefix_length=self.prefix_set.spec.source.prefix_length,
            next_hop=self._next_hop(slot, relative_prefix_index),
            route_properties=self._route_properties(relative_prefix_index),
        )

    def _route_properties(self, prefix_ordinal: int) -> ResolvedRouteProperties:
        pool = self.advertisement.route_attributes
        if pool is None:
            return ResolvedRouteProperties()
        if pool.distribution is not RouteAttributeDistribution.ROUND_ROBIN:
            raise ValueError(
                f"unsupported route-attribute distribution {pool.distribution!r}"
            )
        return ResolvedRouteProperties(
            community_row=self._select_row(pool.community_rows, prefix_ordinal),
            extended_community_row=self._select_row(
                pool.extended_community_rows,
                prefix_ordinal,
            ),
            as_path=self._select_as_path(pool, prefix_ordinal),
        )

    @staticmethod
    def _select_row(rows: tuple[tuple[_T, ...], ...], index: int) -> tuple[_T, ...]:
        return rows[index % len(rows)] if rows else ()

    @staticmethod
    def _select_as_path(
        pool: RouteAttributePool,
        index: int,
    ) -> AsPathSequence | None:
        return pool.as_paths[index % len(pool.as_paths)] if pool.as_paths else None

    def _next_hop(self, slot: int, relative_prefix_index: int) -> str:
        intent = self.advertisement.next_hop
        if intent.mode == NextHopMode.SELF:
            return self.self_next_hop
        if self.next_hops is None:
            raise ValueError(
                f"advertisement {self.advertisement.name!r} has no resolved "
                "next-hop sequence"
            )
        if intent.distribution is None:
            raise ValueError(
                f"advertisement {self.advertisement.name!r} has no next-hop distribution"
            )
        if intent.distribution == NextHopDistribution.SHARED:
            index = 0
        elif intent.distribution == NextHopDistribution.PER_PEER:
            index = self.peer_index
        elif intent.distribution == NextHopDistribution.PER_PREFIX:
            index = relative_prefix_index
        elif intent.distribution == NextHopDistribution.PER_PEER_PREFIX:
            index = self.peer_index * len(self) + slot
        else:
            raise ValueError(
                f"unsupported next-hop distribution {intent.distribution!r}"
            )
        if index < 0 or index >= len(self.next_hops):
            raise IndexError(
                f"advertisement {self.advertisement.name!r} resolved next-hop "
                f"index {index} outside {len(self.next_hops)} entries for "
                f"{intent.distribution.value} distribution"
            )
        return self.next_hops[index]


@dataclass(frozen=True)
class ResolvedPrefixAdvertisement:
    spec: PrefixAdvertisement
    prefix_set: ResolvedPrefixSet
    paths_by_peer: tuple[ResolvedRoutePathSequence, ...]

    @property
    def name(self) -> str:
        return self.spec.name

    def path_at(self, peer_index: int, prefix_index: int) -> ResolvedRoutePath:
        return self.paths_by_peer[peer_index][prefix_index]
