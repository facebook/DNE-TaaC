# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""Runtime-neutral action contract for reusable churn orchestration."""

from __future__ import annotations

import typing as t

from .context import Deadline
from .result import (
    BaselineSummary,
    CleanupDisposition,
    CycleOutcome,
    EvidenceRefs,
    ExecutionWindow,
    RecoveryOutcome,
)


class ChurnAction(t.Protocol):
    async def validate_precondition(self, deadline: Deadline) -> None: ...

    async def capture_baseline(self, deadline: Deadline) -> BaselineSummary: ...

    def begin_execution(self, window: ExecutionWindow) -> None: ...

    async def run_cycle(self, deadline: Deadline) -> CycleOutcome: ...

    async def stop(self, deadline: Deadline) -> None: ...

    async def restore(self, deadline: Deadline) -> None: ...

    async def verify_restore(self, deadline: Deadline) -> None: ...

    async def recover(self, deadline: Deadline) -> RecoveryOutcome: ...

    def cleanup_disposition(self) -> CleanupDisposition: ...

    def collect_evidence(self) -> EvidenceRefs: ...
