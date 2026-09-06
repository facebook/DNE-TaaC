# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""Generic bounded orchestration over a device-independent churn action."""

from __future__ import annotations

import asyncio
import time

from .action import ChurnAction
from .context import Deadline
from .result import (
    ChurnRunOutcome,
    CycleOutcome,
    CycleState,
    ExecutionWindow,
    RecoveryOutcome,
)
from .specs import ChurnScenario, ChurnWorkload


class IncompleteCycleError(RuntimeError):
    pass


class ChurnRunError(RuntimeError):
    def __init__(
        self,
        primary_error: BaseException | None,
        recovery_error: BaseException | None,
        outcome: ChurnRunOutcome,
    ) -> None:
        super().__init__(
            f"churn failed: primary={primary_error!r}; recovery={recovery_error!r}"
        )
        self.primary_error = primary_error
        self.recovery_error = recovery_error
        self.outcome = outcome


class BoundedChurnRunner:
    def __init__(self) -> None:
        self.last_outcome: ChurnRunOutcome | None = None

    def execution_window(
        self,
        scenario: ChurnScenario,
        *,
        started_at_monotonic: float | None = None,
    ) -> ExecutionWindow:
        started = (
            time.monotonic() if started_at_monotonic is None else started_at_monotonic
        )
        duration = scenario.execution.duration_seconds
        if duration <= 0:
            raise ValueError("execution duration must be positive")
        return ExecutionWindow(
            started_at_monotonic=started,
            deadline_monotonic=started + duration,
            family_budget_seconds=duration / scenario.workload.family_count,
        )

    async def run_cycles(
        self,
        action: ChurnAction,
        workload: ChurnWorkload,
        window: ExecutionWindow,
    ) -> tuple[CycleOutcome, ...]:
        outcomes: list[CycleOutcome] = []
        await self._run_cycles_into(action, workload, window, outcomes)
        return tuple(outcomes)

    async def _run_cycles_into(
        self,
        action: ChurnAction,
        workload: ChurnWorkload,
        window: ExecutionWindow,
        outcomes: list[CycleOutcome],
    ) -> None:
        for index, family in enumerate(workload.families):
            family_deadline = min(
                window.deadline_monotonic,
                window.started_at_monotonic
                + (window.family_budget_seconds * (index + 1)),
            )
            outcome = await action.run_cycle(
                Deadline(
                    phase=f"execution.{family.name}",
                    expires_at_monotonic=family_deadline,
                )
            )
            outcomes.append(outcome)
            if outcome.state is not CycleState.COMPLETED:
                break

    async def run(
        self, action: ChurnAction, scenario: ChurnScenario
    ) -> ChurnRunOutcome:
        self.last_outcome = None
        primary_error: BaseException | None = None
        baseline = None
        cycles: tuple[CycleOutcome, ...] = ()
        completed_cycles: list[CycleOutcome] = []
        window: ExecutionWindow | None = None
        work_started = time.monotonic()
        preparation_deadline = Deadline(
            "preparation",
            work_started + scenario.preparation.total_timeout_seconds,
        )
        work_timeout = asyncio.timeout(scenario.preparation.total_timeout_seconds)
        try:
            async with work_timeout:
                await action.validate_precondition(preparation_deadline)
                baseline = await action.capture_baseline(preparation_deadline)
                window = self.execution_window(scenario)
                action.begin_execution(window)
                await self._run_cycles_into(
                    action,
                    scenario.workload,
                    window,
                    completed_cycles,
                )
                cycles = tuple(completed_cycles)
                incomplete = next(
                    (
                        cycle
                        for cycle in cycles
                        if cycle.state is not CycleState.COMPLETED
                    ),
                    None,
                )
                if incomplete is not None:
                    raise IncompleteCycleError(
                        f"cycle {incomplete.name} ended in {incomplete.state.value}"
                    )
        except asyncio.TimeoutError as error:
            if work_timeout.expired():
                primary_error = TimeoutError(
                    "churn work deadline exceeded: "
                    f"budget_seconds={scenario.preparation.total_timeout_seconds:.3f}; "
                    f"elapsed_seconds={time.monotonic() - work_started:.3f}"
                )
                primary_error.__cause__ = error
            else:
                primary_error = error
        except (Exception, asyncio.CancelledError) as error:
            primary_error = error
        cycles = tuple(completed_cycles)
        recovery_deadline = Deadline(
            "recovery", time.monotonic() + scenario.recovery.total_timeout_seconds
        )
        recovery = await self._recover(action, recovery_deadline)
        if baseline is None and primary_error is None:
            primary_error = RuntimeError("baseline capture did not complete")
        outcome = ChurnRunOutcome(
            baseline=baseline,
            cycles=cycles,
            cleanup=action.cleanup_disposition(),
            evidence=action.collect_evidence(),
            execution_window=window,
            primary_error=primary_error,
            recovery_error=recovery.error,
            cleanup_cancellation=recovery.cancellation,
        )
        self.last_outcome = outcome
        self._raise_failures(
            primary_error,
            recovery.error,
            recovery.cancellation,
            outcome,
        )
        return outcome

    async def _recover(
        self, action: ChurnAction, deadline: Deadline
    ) -> RecoveryOutcome:
        try:
            return await action.recover(deadline)
        except asyncio.CancelledError as error:
            return RecoveryOutcome(cancellation=error)
        except Exception as error:
            return RecoveryOutcome(error=error)

    @staticmethod
    def _raise_failures(
        primary_error: BaseException | None,
        recovery_error: BaseException | None,
        cleanup_cancellation: BaseException | None,
        outcome: ChurnRunOutcome,
    ) -> None:
        cancellation = next(
            (
                error
                for error in (
                    primary_error,
                    cleanup_cancellation,
                    recovery_error,
                )
                if isinstance(error, asyncio.CancelledError)
            ),
            None,
        )
        if cancellation is not None:
            secondary = next(
                (
                    error
                    for error in (recovery_error, primary_error)
                    if error is not None and error is not cancellation
                ),
                None,
            )
            if secondary is not None:
                cancellation.add_note(f"secondary error: {secondary!r}")
                raise cancellation from secondary
            raise cancellation
        if primary_error is not None or recovery_error is not None:
            raise ChurnRunError(primary_error, recovery_error, outcome)
