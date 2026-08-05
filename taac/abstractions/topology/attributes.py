# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from dataclasses import dataclass
from enum import Enum


class RouteAttributeDistribution(str, Enum):
    ROUND_ROBIN = "round_robin"


class ExtendedCommunityKind(str, Enum):
    ROUTE_TARGET = "rt"


@dataclass(frozen=True)
class StandardCommunity:
    asn: int
    value: int


@dataclass(frozen=True)
class ExtendedCommunity:
    kind: ExtendedCommunityKind
    administrator: int
    assigned_number: int


@dataclass(frozen=True)
class AsPathSequence:
    asns: tuple[int, ...]


@dataclass(frozen=True)
class RouteAttributePool:
    community_rows: tuple[tuple[StandardCommunity, ...], ...] = ()
    extended_community_rows: tuple[tuple[ExtendedCommunity, ...], ...] = ()
    as_paths: tuple[AsPathSequence, ...] = ()
    distribution: RouteAttributeDistribution = RouteAttributeDistribution.ROUND_ROBIN


@dataclass(frozen=True)
class ResolvedRouteProperties:
    community_row: tuple[StandardCommunity, ...] = ()
    extended_community_row: tuple[ExtendedCommunity, ...] = ()
    as_path: AsPathSequence | None = None
