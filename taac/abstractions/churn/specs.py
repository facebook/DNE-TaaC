# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""Typed churn intent authored and validated through DICE."""

from __future__ import annotations

import dataclasses

from .policies import ExecutionPolicy, PreparationPolicy, RecoveryPolicy, SettlePolicy


Scalar = bool | float | int | str


@dataclasses.dataclass(frozen=True)
class AttributePhase:
    name: str
    value: Scalar


@dataclasses.dataclass(frozen=True)
class AttributeFamily:
    name: str
    phases: tuple[AttributePhase, ...]


@dataclasses.dataclass(frozen=True)
class ChurnWorkload:
    families: tuple[AttributeFamily, ...]

    def __post_init__(self) -> None:
        if not self.families:
            raise ValueError("a churn workload requires at least one family")

    @property
    def family_count(self) -> int:
        return len(self.families)


@dataclasses.dataclass(frozen=True)
class ChurnScenario:
    scenario_id: str
    workload: ChurnWorkload
    preparation: PreparationPolicy
    execution: ExecutionPolicy
    recovery: RecoveryPolicy
    pre_churn_settle: SettlePolicy = SettlePolicy()
    post_churn_settle: SettlePolicy = SettlePolicy()
