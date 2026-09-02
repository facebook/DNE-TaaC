# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""Device-independent churn lifecycle policies."""

from __future__ import annotations

import dataclasses
import enum


class DeadlineMode(enum.StrEnum):
    STRICT_DEADLINE = "strict_deadline"


class SettleMode(enum.StrEnum):
    NONE = "none"
    FIXED_DURATION = "fixed_duration"
    UNTIL_CONVERGED = "until_converged"
    FIXED_THEN_CONVERGED = "fixed_then_converged"


@dataclasses.dataclass(frozen=True)
class PreparationPolicy:
    initial_resolution_timeout_seconds: float
    baseline_capture_timeout_seconds: float
    total_timeout_seconds: float


@dataclasses.dataclass(frozen=True)
class ExecutionPolicy:
    duration_seconds: float = 3_600.0
    cadence_seconds: float = 60.0
    max_iterations: int = 100_000
    deadline_mode: DeadlineMode = DeadlineMode.STRICT_DEADLINE


@dataclasses.dataclass(frozen=True)
class RecoveryPolicy:
    total_timeout_seconds: float = 720.0
    restore_observation_timeout_seconds: float = 400.0
    ixia_restore_timeout_seconds: float = 120.0
    cancellation_grace_seconds: float = 10.0


@dataclasses.dataclass(frozen=True)
class SettleCondition:
    name: str
    observation_timeout_seconds: float


@dataclasses.dataclass(frozen=True)
class SettlePolicy:
    mode: SettleMode = SettleMode.NONE
    fixed_duration_seconds: float = 0.0
    conditions: tuple[SettleCondition, ...] = ()
    convergence_timeout_seconds: float = 0.0
    poll_interval_seconds: float = 10.0
    stable_window_seconds: float = 0.0
    max_consecutive_observation_errors: int = 3
