# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from taac.abstractions.ixia_semantics import (
    validate_ixia_peer_prefix_exclusion_ranges,
)


class PeerPrefixDistribution(str, Enum):
    SHARED = "shared"
    DISJOINT = "disjoint"


class RouteScaleMode(str, Enum):
    WINDOWED = "windowed"
    FLAT = "flat"


class NextHopMode(str, Enum):
    SELF = "self"
    FORMULAIC = "formulaic"
    EXPLICIT = "explicit"


class SelfNextHopRealization(str, Enum):
    ADVERTISING_SESSION_LOCAL_ADDRESS = "advertising_session_local_address"


class NextHopDistribution(str, Enum):
    SHARED = "shared"
    PER_PEER = "per_peer"
    PER_PREFIX = "per_prefix"
    PER_PEER_PREFIX = "per_peer_prefix"


@dataclass(frozen=True)
class PeerPrefixExclusionBlock:
    prefix_start_index: int
    prefix_count: int
    peer_indices: tuple[int, ...]

    def __post_init__(self) -> None:
        if (
            isinstance(self.prefix_start_index, bool)
            or not isinstance(self.prefix_start_index, int)
            or self.prefix_start_index < 0
        ):
            raise ValueError("peer-prefix exclusion start index must be non-negative")
        if (
            isinstance(self.prefix_count, bool)
            or not isinstance(self.prefix_count, int)
            or self.prefix_count <= 0
        ):
            raise ValueError("peer-prefix exclusion count must be positive")
        if not self.peer_indices:
            raise ValueError("peer-prefix exclusion block must name at least one peer")
        if any(
            isinstance(peer_index, bool)
            or not isinstance(peer_index, int)
            or peer_index < 0
            for peer_index in self.peer_indices
        ):
            raise ValueError("peer-prefix exclusion indices must be non-negative")
        if tuple(sorted(set(self.peer_indices))) != self.peer_indices:
            raise ValueError("peer-prefix exclusion indices must be sorted and unique")


@dataclass(frozen=True)
class PeerPrefixActivation:
    """Sparse IXIA route-cell intent; unspecified peer-prefix cells stay active."""

    exclusion_blocks: tuple[PeerPrefixExclusionBlock, ...]

    def __post_init__(self) -> None:
        if not self.exclusion_blocks:
            raise ValueError("peer-prefix activation requires exclusion blocks")
        validate_ixia_peer_prefix_exclusion_ranges(
            tuple(
                (block.prefix_start_index, block.prefix_count)
                for block in self.exclusion_blocks
            )
        )

    def validate_geometry(self, *, peer_count: int, prefixes_per_peer: int) -> None:
        validate_ixia_peer_prefix_exclusion_ranges(
            tuple(
                (block.prefix_start_index, block.prefix_count)
                for block in self.exclusion_blocks
            ),
            prefixes_per_peer=prefixes_per_peer,
        )
        for block in self.exclusion_blocks:
            if block.peer_indices[-1] >= peer_count:
                raise ValueError(
                    "peer-prefix exclusion block references a peer outside the "
                    "device group"
                )
            if len(block.peer_indices) >= peer_count:
                raise ValueError(
                    "peer-prefix exclusion block must leave at least one active peer"
                )


@dataclass(frozen=True)
class FormulaicPrefixSource:
    start_prefix: str
    prefix_step: int | str
    prefix_length: int
    count: int
    parent_network: str
    excluded_indices: tuple[int, ...] = ()


@dataclass(frozen=True)
class PrefixSet:
    name: str
    afi: str
    source: FormulaicPrefixSource


@dataclass(frozen=True)
class PrefixMembership:
    start_index: int
    prefix_count: int


@dataclass(frozen=True)
class PrefixAllocation:
    prefixes_per_peer: int
    peer_distribution: PeerPrefixDistribution
    network_group_index: int = 0
    route_scale_mode: RouteScaleMode = RouteScaleMode.WINDOWED

    def distinct_prefix_count(self, peer_count: int) -> int:
        if self.peer_distribution == PeerPrefixDistribution.SHARED:
            return self.prefixes_per_peer
        return peer_count * self.prefixes_per_peer


@dataclass(frozen=True)
class FormulaicNextHopSource:
    start: str
    step: int | str
    parent_network: str


@dataclass(frozen=True)
class ExplicitNextHopSource:
    addresses: tuple[str, ...]
    parent_network: str


@dataclass(frozen=True)
class NextHopIntent:
    mode: NextHopMode = NextHopMode.SELF
    distribution: NextHopDistribution | None = None
    formulaic_source: FormulaicNextHopSource | None = None
    explicit_source: ExplicitNextHopSource | None = None
    description: str | None = None
    self_realization: SelfNextHopRealization | None = None
