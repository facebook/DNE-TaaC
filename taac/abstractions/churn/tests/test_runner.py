# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""Contract coverage for the DICE-owned bounded churn runner."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from later.unittest import TestCase
from taac.abstractions.churn.context import (
    Deadline,
    DeadlineExceeded,
)
from taac.abstractions.churn.policies import (
    ExecutionPolicy,
    PreparationPolicy,
    RecoveryPolicy,
)
from taac.abstractions.churn.result import (
    BaselineSummary,
    CleanupDisposition,
    CleanupState,
    CycleOutcome,
    CycleState,
    EvidenceRefs,
    ExecutionWindow,
    RecoveryOutcome,
)
from taac.abstractions.churn.runner import (
    BoundedChurnRunner,
    ChurnRunError,
)
from taac.abstractions.churn.specs import (
    AttributeFamily,
    AttributePhase,
    ChurnScenario,
    ChurnWorkload,
)


def _scenario() -> ChurnScenario:
    workload = ChurnWorkload(
        families=tuple(
            AttributeFamily(name=name, phases=(AttributePhase("reference", 100),))
            for name in ("med", "origin", "local_pref")
        )
    )
    return ChurnScenario(
        scenario_id="scenario",
        workload=workload,
        preparation=PreparationPolicy(10.0, 20.0, 30.0),
        execution=ExecutionPolicy(duration_seconds=90.0),
        recovery=RecoveryPolicy(total_timeout_seconds=40.0),
    )


class _FakeAction:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.deadlines: list[Deadline] = []
        self.run_error: BaseException | None = None
        self.run_error_at_cycle: int | None = None
        self.cycle_calls = 0
        self.restore_error: BaseException | None = None
        self.cleanup_cancellation: asyncio.CancelledError | None = None

    async def validate_precondition(self, deadline: Deadline) -> None:
        self.calls.append("validate")
        self.deadlines.append(deadline)

    async def capture_baseline(self, deadline: Deadline) -> BaselineSummary:
        self.calls.append("baseline")
        self.deadlines.append(deadline)
        return BaselineSummary(target_count=56, sampled_prefix_count=112)

    def begin_execution(self, window: ExecutionWindow) -> None:
        self.calls.append("begin_execution")

    async def run_cycle(self, deadline: Deadline) -> CycleOutcome:
        self.calls.append(f"cycle:{deadline.phase}")
        self.deadlines.append(deadline)
        self.cycle_calls += 1
        if self.run_error is not None and (
            self.run_error_at_cycle is None
            or self.cycle_calls == self.run_error_at_cycle
        ):
            raise self.run_error
        return CycleOutcome(deadline.phase, CycleState.COMPLETED, 2)

    async def stop(self, deadline: Deadline) -> None:
        self.calls.append("stop")
        self.deadlines.append(deadline)

    async def restore(self, deadline: Deadline) -> None:
        self.calls.append("restore")
        self.deadlines.append(deadline)
        if self.restore_error is not None:
            raise self.restore_error

    async def verify_restore(self, deadline: Deadline) -> None:
        self.calls.append("verify_restore")
        self.deadlines.append(deadline)

    async def recover(self, deadline: Deadline) -> RecoveryOutcome:
        first_error: BaseException | None = None
        for operation in (self.stop, self.restore, self.verify_restore):
            try:
                await operation(deadline)
            except (Exception, asyncio.CancelledError) as error:
                if first_error is None:
                    first_error = error
        return RecoveryOutcome(
            error=first_error,
            cancellation=self.cleanup_cancellation,
        )

    def cleanup_disposition(self) -> CleanupDisposition:
        return CleanupDisposition(CleanupState.RESTORED, True, True)

    def collect_evidence(self) -> EvidenceRefs:
        return EvidenceRefs()


class BoundedChurnRunnerTest(TestCase):
    async def test_runs_three_family_cycles_with_partitioned_deadlines(self) -> None:
        action = _FakeAction()
        runner = BoundedChurnRunner()
        scenario = _scenario()
        window = runner.execution_window(scenario, started_at_monotonic=100.0)

        outcomes = await runner.run_cycles(action, scenario.workload, window)

        self.assertEqual(3, len(outcomes))
        self.assertEqual(
            [130.0, 160.0, 190.0],
            [deadline.expires_at_monotonic for deadline in action.deadlines],
        )

    async def test_full_lifecycle_restores_after_success(self) -> None:
        action = _FakeAction()

        result = await BoundedChurnRunner().run(action, _scenario())

        self.assertEqual(CleanupState.RESTORED, result.cleanup.state)
        self.assertEqual(
            [
                "validate",
                "baseline",
                "begin_execution",
                "cycle:execution.med",
                "cycle:execution.origin",
                "cycle:execution.local_pref",
                "stop",
                "restore",
                "verify_restore",
            ],
            action.calls,
        )

    async def test_primary_and_recovery_failures_are_preserved(self) -> None:
        action = _FakeAction()
        action.run_error = RuntimeError("work")
        action.restore_error = ValueError("restore")
        runner = BoundedChurnRunner()

        with self.assertRaises(ChurnRunError) as context:
            await runner.run(action, _scenario())

        self.assertIs(action.run_error, context.exception.primary_error)
        self.assertIs(action.restore_error, context.exception.recovery_error)
        self.assertIs(context.exception.outcome, runner.last_outcome)
        self.assertIn("verify_restore", action.calls)

    async def test_completed_cycles_are_preserved_when_later_cycle_fails(
        self,
    ) -> None:
        action = _FakeAction()
        action.run_error = RuntimeError("second cycle failed")
        action.run_error_at_cycle = 2
        runner = BoundedChurnRunner()

        with self.assertRaises(ChurnRunError) as context:
            await runner.run(action, _scenario())

        self.assertEqual(
            ["execution.med"],
            [cycle.name for cycle in context.exception.outcome.cycles],
        )

    async def test_cancellation_still_runs_complete_recovery(self) -> None:
        action = _FakeAction()
        action.run_error = asyncio.CancelledError()

        with self.assertRaises(asyncio.CancelledError):
            await BoundedChurnRunner().run(action, _scenario())

        self.assertEqual(["stop", "restore", "verify_restore"], action.calls[-3:])

    async def test_cleanup_cancellation_is_preserved_in_partial_outcome(self) -> None:
        action = _FakeAction()
        action.cleanup_cancellation = asyncio.CancelledError()
        runner = BoundedChurnRunner()

        with self.assertRaises(asyncio.CancelledError):
            await runner.run(action, _scenario())

        if runner.last_outcome is None:
            self.fail("runner did not retain its terminal outcome")
        self.assertIs(
            action.cleanup_cancellation,
            runner.last_outcome.cleanup_cancellation,
        )


class DeadlineTest(unittest.TestCase):
    def test_remaining_clamps_to_phase_budget(self) -> None:
        with patch(
            "neteng.test_infra.dne.taac.abstractions.churn.context.time.monotonic",
            return_value=10.0,
        ):
            deadline = Deadline("phase", 15.0)
            self.assertEqual(5.0, deadline.remaining(20.0))
            self.assertEqual(2.0, deadline.remaining(2.0))

    def test_remaining_fails_without_one_last_call(self) -> None:
        with patch(
            "neteng.test_infra.dne.taac.abstractions.churn.context.time.monotonic",
            return_value=15.0,
        ):
            with self.assertRaisesRegex(DeadlineExceeded, "phase"):
                Deadline("phase", 15.0).remaining(20.0)

    def test_ensure_remaining_fails_after_deadline(self) -> None:
        with patch(
            "neteng.test_infra.dne.taac.abstractions.churn.context.time.monotonic",
            return_value=15.0,
        ):
            with self.assertRaisesRegex(DeadlineExceeded, "phase"):
                Deadline("phase", 15.0).ensure_remaining(20.0)
