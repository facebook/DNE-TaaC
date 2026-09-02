# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""Portable target-selection intent for churn scenarios."""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class TargetIdentity:
    namespace: str
    name: str


@dataclasses.dataclass(frozen=True)
class UniformRowSelection:
    rows_per_pool: int = 7

    def __post_init__(self) -> None:
        if self.rows_per_pool <= 0:
            raise ValueError("rows_per_pool must be positive")


@dataclasses.dataclass(frozen=True)
class TargetSelection:
    targets: tuple[TargetIdentity, ...]
    row_selection: UniformRowSelection
