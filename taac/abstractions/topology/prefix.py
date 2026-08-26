# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


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
