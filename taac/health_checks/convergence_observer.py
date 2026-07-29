# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-strict

"""Reusable soft-SLA and hard-timeout convergence observation."""

from __future__ import annotations

import asyncio
import dataclasses
import enum
import time
import typing as t


class ConvergenceOutcome(enum.Enum):
    CONVERGED = "CONVERGED"
    WITHIN_SLA = "WITHIN_SLA"
    CONVERGED_LATE = "CONVERGED_LATE"
    NOT_CONVERGED = "NOT_CONVERGED"


@dataclasses.dataclass(frozen=True)
class ConvergenceSample:
    """One predicate observation.

    ``convergence_time_seconds`` lets a predicate provide a more authoritative
    duration than observer wall time, such as a delta between protocol event
    timestamps. Most predicates should leave it unset.
    """

    converged: bool
    detail: str | None = None
    convergence_time_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.convergence_time_seconds is not None:
            if not self.converged:
                raise ValueError("convergence_time_seconds requires a converged sample")
            if self.convergence_time_seconds < 0:
                raise ValueError("convergence_time_seconds must be non-negative")


@dataclasses.dataclass(frozen=True)
class PredicateError:
    elapsed_seconds: float
    error_type: str
    message: str


@dataclasses.dataclass(frozen=True)
class ConvergenceResult:
    outcome: ConvergenceOutcome
    soft_threshold_seconds: float | None
    hard_timeout_seconds: float
    elapsed_seconds: float
    convergence_time_seconds: float | None
    confirmation_time_seconds: float | None
    attempts: int
    soft_threshold_breached: bool
    last_observation: str | None
    predicate_errors: tuple[PredicateError, ...]


ConvergencePredicate = t.Callable[[], t.Awaitable[ConvergenceSample]]
Clock = t.Callable[[], float]
Sleep = t.Callable[[float], t.Awaitable[None]]


async def observe_convergence(
    predicate: ConvergencePredicate,
    *,
    soft_threshold_seconds: float | None,
    hard_timeout_seconds: float,
    poll_interval_seconds: float,
    stability_window_seconds: float = 0.0,
    predicate_timeout_seconds: float | None = None,
    clock: Clock = time.monotonic,
    sleep: Sleep = asyncio.sleep,
) -> ConvergenceResult:
    """Poll until convergence is confirmed or the hard timeout expires.

    Crossing a configured soft threshold is latched. A later convergence
    observation is therefore diagnostic evidence, not a way to turn the result
    back into a pass. When the threshold is ``None``, the observer is
    measurement-only and returns ``CONVERGED`` without fabricating an SLA.
    Predicate exceptions and timeouts are retained and break stability-window
    continuity because convergence was not successfully observed during that poll.
    """
    _validate_parameters(
        soft_threshold_seconds=soft_threshold_seconds,
        hard_timeout_seconds=hard_timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        stability_window_seconds=stability_window_seconds,
        predicate_timeout_seconds=predicate_timeout_seconds,
    )

    started = clock()
    attempts = 0
    first_satisfied_seconds: float | None = None
    last_observation: str | None = None
    errors: list[PredicateError] = []

    while True:
        before_attempt = max(0.0, clock() - started)
        if attempts > 0 and before_attempt >= hard_timeout_seconds:
            return _not_converged_result(
                soft_threshold_seconds,
                hard_timeout_seconds,
                before_attempt,
                attempts,
                last_observation,
                errors,
            )
        remaining = max(0.0, hard_timeout_seconds - before_attempt)
        attempts += 1
        sample, error = await _invoke_predicate(
            predicate,
            _predicate_timeout(remaining, predicate_timeout_seconds),
        )
        if sample is not None:
            last_observation = sample.detail
        if error is not None:
            elapsed = max(0.0, clock() - started)
            errors.append(
                PredicateError(
                    elapsed_seconds=elapsed,
                    error_type=type(error).__name__,
                    message=str(error),
                )
            )

        elapsed = max(0.0, clock() - started)
        if elapsed > hard_timeout_seconds:
            return _not_converged_result(
                soft_threshold_seconds,
                hard_timeout_seconds,
                elapsed,
                attempts,
                last_observation,
                errors,
            )

        if sample is not None and sample.converged:
            if first_satisfied_seconds is None:
                first_satisfied_seconds = elapsed
            stable_for = elapsed - first_satisfied_seconds
            if stable_for >= stability_window_seconds:
                return _converged_result(
                    sample=sample,
                    first_satisfied_seconds=first_satisfied_seconds,
                    confirmation_time_seconds=elapsed,
                    soft_threshold_seconds=soft_threshold_seconds,
                    hard_timeout_seconds=hard_timeout_seconds,
                    attempts=attempts,
                    last_observation=last_observation,
                    errors=errors,
                )
        else:
            # Stability requires continuous successful observations; an error
            # makes the interval unknown and restarts confirmation.
            first_satisfied_seconds = None

        if elapsed >= hard_timeout_seconds:
            return _not_converged_result(
                soft_threshold_seconds,
                hard_timeout_seconds,
                elapsed,
                attempts,
                last_observation,
                errors,
            )

        sleep_seconds = min(
            poll_interval_seconds,
            hard_timeout_seconds - elapsed,
        )
        if first_satisfied_seconds is not None:
            sleep_seconds = min(
                sleep_seconds,
                max(
                    0.0,
                    stability_window_seconds - (elapsed - first_satisfied_seconds),
                ),
            )
        await sleep(sleep_seconds)


async def _invoke_predicate(
    predicate: ConvergencePredicate,
    timeout_seconds: float,
) -> tuple[ConvergenceSample | None, Exception | None]:
    try:
        return await asyncio.wait_for(predicate(), timeout=timeout_seconds), None
    except asyncio.CancelledError:
        raise
    except Exception as error:
        return None, error


def _predicate_timeout(
    remaining_seconds: float,
    predicate_timeout_seconds: float | None,
) -> float:
    if predicate_timeout_seconds is None:
        return remaining_seconds
    return min(remaining_seconds, predicate_timeout_seconds)


def _converged_result(
    *,
    sample: ConvergenceSample,
    first_satisfied_seconds: float,
    confirmation_time_seconds: float,
    soft_threshold_seconds: float | None,
    hard_timeout_seconds: float,
    attempts: int,
    last_observation: str | None,
    errors: t.Sequence[PredicateError],
) -> ConvergenceResult:
    convergence_time = (
        sample.convergence_time_seconds
        if sample.convergence_time_seconds is not None
        else first_satisfied_seconds
    )
    classification_time = (
        sample.convergence_time_seconds
        if sample.convergence_time_seconds is not None
        else confirmation_time_seconds
    )
    within_sla = (
        soft_threshold_seconds is not None
        and classification_time <= soft_threshold_seconds
    )
    outcome = ConvergenceOutcome.CONVERGED
    if soft_threshold_seconds is not None:
        outcome = (
            ConvergenceOutcome.WITHIN_SLA
            if within_sla
            else ConvergenceOutcome.CONVERGED_LATE
        )
    return ConvergenceResult(
        outcome=outcome,
        soft_threshold_seconds=soft_threshold_seconds,
        hard_timeout_seconds=hard_timeout_seconds,
        elapsed_seconds=confirmation_time_seconds,
        convergence_time_seconds=convergence_time,
        confirmation_time_seconds=confirmation_time_seconds,
        attempts=attempts,
        soft_threshold_breached=(soft_threshold_seconds is not None and not within_sla),
        last_observation=last_observation,
        predicate_errors=tuple(errors),
    )


def _validate_parameters(
    *,
    soft_threshold_seconds: float | None,
    hard_timeout_seconds: float,
    poll_interval_seconds: float,
    stability_window_seconds: float,
    predicate_timeout_seconds: float | None,
) -> None:
    if soft_threshold_seconds is not None and soft_threshold_seconds < 0:
        raise ValueError("soft_threshold_seconds must be non-negative")
    if hard_timeout_seconds <= 0:
        raise ValueError("hard_timeout_seconds must be positive")
    if (
        soft_threshold_seconds is not None
        and hard_timeout_seconds < soft_threshold_seconds
    ):
        raise ValueError(
            "hard_timeout_seconds must be greater than or equal to "
            "soft_threshold_seconds"
        )
    if poll_interval_seconds <= 0:
        raise ValueError("poll_interval_seconds must be positive")
    if stability_window_seconds < 0:
        raise ValueError("stability_window_seconds must be non-negative")
    if predicate_timeout_seconds is not None and predicate_timeout_seconds <= 0:
        raise ValueError("predicate_timeout_seconds must be positive")


def _not_converged_result(
    soft_threshold_seconds: float | None,
    hard_timeout_seconds: float,
    elapsed_seconds: float,
    attempts: int,
    last_observation: str | None,
    errors: t.Sequence[PredicateError],
) -> ConvergenceResult:
    return ConvergenceResult(
        outcome=ConvergenceOutcome.NOT_CONVERGED,
        soft_threshold_seconds=soft_threshold_seconds,
        hard_timeout_seconds=hard_timeout_seconds,
        elapsed_seconds=elapsed_seconds,
        convergence_time_seconds=None,
        confirmation_time_seconds=None,
        attempts=attempts,
        soft_threshold_breached=soft_threshold_seconds is not None,
        last_observation=last_observation,
        predicate_errors=tuple(errors),
    )
