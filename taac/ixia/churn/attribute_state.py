# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""Live IXIA state required to mutate and restore BGP attributes safely."""

from __future__ import annotations

import dataclasses
import typing as t

from taac.ixia.route_geometry import (
    IxiaOverlayVector,
    IxiaValueVector,
)


AttributeVector = IxiaValueVector | IxiaOverlayVector


@dataclasses.dataclass(frozen=True)
class IxiaAttributePoolState:
    afi: str
    plane: int
    name: str
    pool: t.Any
    route: t.Any
    rows: tuple[int, ...]
    peer_ranges: tuple[tuple[int, int, str], ...]
    local_pref: AttributeVector
    med_enabled: AttributeVector
    med: AttributeVector
    origin: AttributeVector
