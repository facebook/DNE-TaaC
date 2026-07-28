# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-strict

import asyncio
import unittest

from taac.health_checks.convergence_observer import (
    ConvergenceOutcome,
    ConvergenceSample,
    observe_convergence,
)


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class ConvergenceObserverTest(unittest.IsolatedAsyncioTestCase):
    async def test_measurement_only_mode_converges_without_sla(self) -> None:
        clock = _FakeClock()
        observations = iter([False, False, True])

        async def predicate() -> ConvergenceSample:
            return ConvergenceSample(converged=next(observations))

        result = await observe_convergence(
            predicate,
            soft_threshold_seconds=None,
            hard_timeout_seconds=5,
            poll_interval_seconds=1,
            clock=clock,
            sleep=clock.sleep,
        )

        self.assertEqual(ConvergenceOutcome.CONVERGED, result.outcome)
        self.assertEqual(2.0, result.convergence_time_seconds)
        self.assertFalse(result.soft_threshold_breached)
        self.assertIsNone(result.soft_threshold_seconds)

    async def test_measurement_only_timeout_has_no_soft_breach(self) -> None:
        clock = _FakeClock()

        async def predicate() -> ConvergenceSample:
            return ConvergenceSample(converged=False)

        result = await observe_convergence(
            predicate,
            soft_threshold_seconds=None,
            hard_timeout_seconds=2,
            poll_interval_seconds=1,
            clock=clock,
            sleep=clock.sleep,
        )

        self.assertEqual(ConvergenceOutcome.NOT_CONVERGED, result.outcome)
        self.assertFalse(result.soft_threshold_breached)
        self.assertIsNone(result.soft_threshold_seconds)

    async def test_samples_immediately_and_stops_within_sla(self) -> None:
        clock = _FakeClock()
        calls = 0

        async def predicate() -> ConvergenceSample:
            nonlocal calls
            calls += 1
            return ConvergenceSample(converged=True, detail="ready")

        result = await observe_convergence(
            predicate,
            soft_threshold_seconds=5,
            hard_timeout_seconds=10,
            poll_interval_seconds=1,
            clock=clock,
            sleep=clock.sleep,
        )

        self.assertEqual(ConvergenceOutcome.WITHIN_SLA, result.outcome)
        self.assertEqual(0.0, result.convergence_time_seconds)
        self.assertEqual(1, result.attempts)
        self.assertEqual(1, calls)
        self.assertEqual([], clock.sleeps)

    async def test_converges_before_soft_threshold(self) -> None:
        clock = _FakeClock()
        observations = iter([False, False, True])

        async def predicate() -> ConvergenceSample:
            return ConvergenceSample(converged=next(observations))

        result = await observe_convergence(
            predicate,
            soft_threshold_seconds=5,
            hard_timeout_seconds=10,
            poll_interval_seconds=1,
            clock=clock,
            sleep=clock.sleep,
        )

        self.assertEqual(ConvergenceOutcome.WITHIN_SLA, result.outcome)
        self.assertEqual(2.0, result.convergence_time_seconds)
        self.assertFalse(result.soft_threshold_breached)

    async def test_soft_threshold_is_latched_until_late_convergence(self) -> None:
        clock = _FakeClock()
        observations = iter([False, False, False, True])

        async def predicate() -> ConvergenceSample:
            return ConvergenceSample(converged=next(observations))

        result = await observe_convergence(
            predicate,
            soft_threshold_seconds=2,
            hard_timeout_seconds=5,
            poll_interval_seconds=1,
            clock=clock,
            sleep=clock.sleep,
        )

        self.assertEqual(ConvergenceOutcome.CONVERGED_LATE, result.outcome)
        self.assertEqual(3.0, result.convergence_time_seconds)
        self.assertTrue(result.soft_threshold_breached)
        self.assertEqual(4, result.attempts)

    async def test_stops_at_hard_timeout_without_convergence(self) -> None:
        clock = _FakeClock()

        async def predicate() -> ConvergenceSample:
            return ConvergenceSample(converged=False, detail="not ready")

        result = await observe_convergence(
            predicate,
            soft_threshold_seconds=1,
            hard_timeout_seconds=2,
            poll_interval_seconds=1,
            clock=clock,
            sleep=clock.sleep,
        )

        self.assertEqual(ConvergenceOutcome.NOT_CONVERGED, result.outcome)
        self.assertEqual(2.0, result.elapsed_seconds)
        self.assertIsNone(result.convergence_time_seconds)
        self.assertEqual(2, result.attempts)
        self.assertEqual("not ready", result.last_observation)

    async def test_stability_window_confirms_continuous_convergence(self) -> None:
        clock = _FakeClock()

        async def predicate() -> ConvergenceSample:
            return ConvergenceSample(converged=True)

        result = await observe_convergence(
            predicate,
            soft_threshold_seconds=3,
            hard_timeout_seconds=5,
            poll_interval_seconds=1,
            stability_window_seconds=2,
            clock=clock,
            sleep=clock.sleep,
        )

        self.assertEqual(ConvergenceOutcome.WITHIN_SLA, result.outcome)
        self.assertEqual(0.0, result.convergence_time_seconds)
        self.assertEqual(2.0, result.confirmation_time_seconds)
        self.assertEqual(3, result.attempts)

    async def test_failed_sample_resets_stability_window(self) -> None:
        clock = _FakeClock()
        observations = iter([True, False, True, True, True])

        async def predicate() -> ConvergenceSample:
            return ConvergenceSample(converged=next(observations))

        result = await observe_convergence(
            predicate,
            soft_threshold_seconds=5,
            hard_timeout_seconds=6,
            poll_interval_seconds=1,
            stability_window_seconds=2,
            clock=clock,
            sleep=clock.sleep,
        )

        self.assertEqual(ConvergenceOutcome.WITHIN_SLA, result.outcome)
        self.assertEqual(2.0, result.convergence_time_seconds)
        self.assertEqual(4.0, result.confirmation_time_seconds)

    async def test_predicate_error_resets_stability_window(self) -> None:
        clock = _FakeClock()
        observations = iter([True, RuntimeError("read failed"), True, True, True])

        async def predicate() -> ConvergenceSample:
            observation = next(observations)
            if isinstance(observation, Exception):
                raise observation
            return ConvergenceSample(converged=observation)

        result = await observe_convergence(
            predicate,
            soft_threshold_seconds=5,
            hard_timeout_seconds=6,
            poll_interval_seconds=1,
            stability_window_seconds=2,
            clock=clock,
            sleep=clock.sleep,
        )

        self.assertEqual(ConvergenceOutcome.WITHIN_SLA, result.outcome)
        self.assertEqual(2.0, result.convergence_time_seconds)
        self.assertEqual(4.0, result.confirmation_time_seconds)
        self.assertEqual(1, len(result.predicate_errors))

    async def test_retains_transient_predicate_errors(self) -> None:
        clock = _FakeClock()
        calls = 0

        async def predicate() -> ConvergenceSample:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("temporary read failure")
            return ConvergenceSample(converged=True, detail="recovered")

        result = await observe_convergence(
            predicate,
            soft_threshold_seconds=3,
            hard_timeout_seconds=5,
            poll_interval_seconds=1,
            clock=clock,
            sleep=clock.sleep,
        )

        self.assertEqual(ConvergenceOutcome.WITHIN_SLA, result.outcome)
        self.assertEqual(1, len(result.predicate_errors))
        self.assertEqual("RuntimeError", result.predicate_errors[0].error_type)
        self.assertEqual("temporary read failure", result.predicate_errors[0].message)

    async def test_per_predicate_timeout_is_retained(self) -> None:
        clock = _FakeClock()
        calls = 0

        async def predicate() -> ConvergenceSample:
            nonlocal calls
            calls += 1
            if calls == 1:
                await asyncio.Event().wait()
            return ConvergenceSample(converged=True)

        result = await observe_convergence(
            predicate,
            soft_threshold_seconds=3,
            hard_timeout_seconds=5,
            poll_interval_seconds=1,
            predicate_timeout_seconds=0.001,
            clock=clock,
            sleep=clock.sleep,
        )

        self.assertEqual(ConvergenceOutcome.WITHIN_SLA, result.outcome)
        self.assertEqual(1, len(result.predicate_errors))
        self.assertEqual("TimeoutError", result.predicate_errors[0].error_type)

    async def test_hard_timeout_bounds_a_hanging_predicate(self) -> None:
        async def predicate() -> ConvergenceSample:
            await asyncio.Event().wait()
            return ConvergenceSample(converged=True)

        result = await observe_convergence(
            predicate,
            soft_threshold_seconds=0.005,
            hard_timeout_seconds=0.01,
            poll_interval_seconds=0.001,
        )

        self.assertEqual(ConvergenceOutcome.NOT_CONVERGED, result.outcome)
        self.assertGreaterEqual(result.elapsed_seconds, 0.01)
        self.assertEqual(1, len(result.predicate_errors))
        self.assertEqual("TimeoutError", result.predicate_errors[0].error_type)

    async def test_authoritative_predicate_time_controls_sla(self) -> None:
        clock = _FakeClock()

        async def predicate() -> ConvergenceSample:
            return ConvergenceSample(
                converged=True,
                convergence_time_seconds=7.0,
            )

        result = await observe_convergence(
            predicate,
            soft_threshold_seconds=5,
            hard_timeout_seconds=10,
            poll_interval_seconds=1,
            clock=clock,
            sleep=clock.sleep,
        )

        self.assertEqual(ConvergenceOutcome.CONVERGED_LATE, result.outcome)
        self.assertEqual(7.0, result.convergence_time_seconds)
        self.assertEqual(0.0, result.confirmation_time_seconds)

    async def test_authoritative_time_is_not_replaced_by_observer_delay(self) -> None:
        clock = _FakeClock()

        async def predicate() -> ConvergenceSample:
            await clock.sleep(8)
            return ConvergenceSample(
                converged=True,
                convergence_time_seconds=4.0,
            )

        result = await observe_convergence(
            predicate,
            soft_threshold_seconds=5,
            hard_timeout_seconds=10,
            poll_interval_seconds=1,
            clock=clock,
            sleep=clock.sleep,
        )

        self.assertEqual(ConvergenceOutcome.WITHIN_SLA, result.outcome)
        self.assertEqual(4.0, result.convergence_time_seconds)
        self.assertEqual(8.0, result.confirmation_time_seconds)

    async def test_rejects_invalid_parameters(self) -> None:
        async def predicate() -> ConvergenceSample:
            return ConvergenceSample(converged=True)

        with self.assertRaises(ValueError):
            await observe_convergence(
                predicate,
                soft_threshold_seconds=5,
                hard_timeout_seconds=4,
                poll_interval_seconds=1,
            )
        with self.assertRaises(ValueError):
            await observe_convergence(
                predicate,
                soft_threshold_seconds=1,
                hard_timeout_seconds=2,
                poll_interval_seconds=0,
            )
