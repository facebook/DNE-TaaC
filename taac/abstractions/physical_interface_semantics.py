# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class PhysicalLinkRate:
    aggregate_gbps: int
    lane_count: int

    def __post_init__(self) -> None:
        _require_positive_int(self.aggregate_gbps, "aggregate_gbps")
        _require_positive_int(self.lane_count, "lane_count")


@dataclass(frozen=True)
class PhysicalInterfaceProfile:
    rate: PhysicalLinkRate

    def __post_init__(self) -> None:
        if not isinstance(self.rate, PhysicalLinkRate):
            raise TypeError("physical interface rate must be typed")


class PhysicalInterfaceGroupKind(str, Enum):
    REUSE_GROUP = "reuse_group"
    LOGICAL_ROLE = "logical_role"


def _require_positive_int(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"physical link {field_name} must be an integer")
    if value <= 0:
        raise ValueError(f"physical link {field_name} must be positive")


__all__ = (
    "PhysicalInterfaceGroupKind",
    "PhysicalInterfaceProfile",
    "PhysicalLinkRate",
)
