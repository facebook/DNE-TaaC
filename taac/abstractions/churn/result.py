# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""Portable churn outcomes consumed independently of the TAAC runtime."""

from __future__ import annotations

import dataclasses
import enum


class CycleState(enum.StrEnum):
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


class CleanupState(enum.StrEnum):
    NOT_REQUIRED = "not_required"
    RESTORED = "restored"
    UNVERIFIED = "unverified"
    QUARANTINED = "quarantined"


@dataclasses.dataclass(frozen=True)
class BaselineSummary:
    target_count: int
    sampled_prefix_count: int


@dataclasses.dataclass(frozen=True)
class EvidenceRef:
    kind: str
    reference: str


@dataclasses.dataclass(frozen=True)
class EvidenceRefs:
    items: tuple[EvidenceRef, ...] = ()


@dataclasses.dataclass(frozen=True)
class CycleOutcome:
    name: str
    state: CycleState
    completed_iterations: int
    evidence: EvidenceRefs = EvidenceRefs()


@dataclasses.dataclass(frozen=True)
class CleanupDisposition:
    state: CleanupState
    baseline_captured: bool
    mutation_attempted: bool
    reason: str | None = None


@dataclasses.dataclass(frozen=True)
class ExecutionWindow:
    started_at_monotonic: float
    deadline_monotonic: float
    family_budget_seconds: float


@dataclasses.dataclass(frozen=True)
class ChurnRunOutcome:
    baseline: BaselineSummary | None
    cycles: tuple[CycleOutcome, ...]
    cleanup: CleanupDisposition
    evidence: EvidenceRefs
    execution_window: ExecutionWindow | None = None
    primary_error: BaseException | None = None
    recovery_error: BaseException | None = None
    cleanup_cancellation: BaseException | None = None


@dataclasses.dataclass(frozen=True)
class RecoveryOutcome:
    error: BaseException | None = None
    cancellation: BaseException | None = None
