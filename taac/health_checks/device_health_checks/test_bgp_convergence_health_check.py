# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""Unit tests for BgpConvergenceHealthCheck, focused on the opt-in
`validate_sequence` initialization-event-order assertion."""

import unittest
from unittest.mock import AsyncMock, MagicMock

from neteng.fboss.bgp_thrift.types import BgpInitializationEvent
from neteng.netcastle.logger import ConsoleFileLogger
from taac.constants import TestDevice
from taac.health_checks.convergence_observer import (
    ConvergenceOutcome,
    ConvergenceResult,
    PredicateError,
)
from taac.health_checks.device_health_checks.bgp_convergence_health_check import (
    BgpConvergenceHealthCheck,
)
from taac.health_check.health_check import types as hc_types


def _full_ordered_events():
    """Canonical happy-path event map (timestamps in ms, monotonic).

    FSDB_SUBSCRIBED is intentionally omitted (not emitted on EOS/bgpcpp).
    """
    return {
        BgpInitializationEvent.INITIALIZING: 0,
        BgpInitializationEvent.AGENT_CONFIGURED: 1000,
        BgpInitializationEvent.PEER_INFO_LOADED: 2000,
        BgpInitializationEvent.ALL_EOR_RECEIVED: 3000,
        BgpInitializationEvent.RIB_COMPUTED: 4000,
        BgpInitializationEvent.FIB_SYNCED: 5000,
        BgpInitializationEvent.EOR_SENT: 6000,
        BgpInitializationEvent.INITIALIZED: 7000,
    }


class BgpConvergenceHealthCheckTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.logger = MagicMock(spec=ConsoleFileLogger)
        self.health_check = BgpConvergenceHealthCheck(logger=self.logger)
        self.health_check.driver = AsyncMock()
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "bag012.ash6"
        self.input = hc_types.BaseHealthCheckIn()

    # ---- _validate_event_sequence (pure helper) ----
    def test_sequence_helper_ok(self):
        self.assertIsNone(
            self.health_check._validate_event_sequence(_full_ordered_events(), "dev")
        )

    def test_sequence_helper_missing_initialized(self):
        events = _full_ordered_events()
        del events[BgpInitializationEvent.INITIALIZED]
        err = self.health_check._validate_event_sequence(events, "dev")
        self.assertIsNotNone(err)
        self.assertIn("INITIALIZED", err)

    def test_sequence_helper_out_of_order(self):
        events = _full_ordered_events()
        # FIB_SYNCED occurs before RIB_COMPUTED -> inversion
        events[BgpInitializationEvent.FIB_SYNCED] = 3500
        err = self.health_check._validate_event_sequence(events, "dev")
        self.assertIsNotNone(err)
        self.assertIn("out of order", err)

    def test_sequence_helper_ignores_absent_intermediate(self):
        """A legitimately-absent intermediate must not fail the sequence."""
        events = _full_ordered_events()
        del events[BgpInitializationEvent.PEER_INFO_LOADED]
        self.assertIsNone(self.health_check._validate_event_sequence(events, "dev"))

    # ---- _run end-to-end ----
    async def test_run_validate_sequence_pass(self):
        self.health_check.driver.async_get_bgp_initialization_events = AsyncMock(
            return_value=_full_ordered_events()
        )
        result = await self.health_check._run(
            self.device, self.input, {"validate_sequence": True}
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_run_validate_sequence_out_of_order_fail(self):
        events = _full_ordered_events()
        events[BgpInitializationEvent.FIB_SYNCED] = 3500
        self.health_check.driver.async_get_bgp_initialization_events = AsyncMock(
            return_value=events
        )
        result = await self.health_check._run(
            self.device, self.input, {"validate_sequence": True}
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("out of order", result.message)

    async def test_run_eor_timer_expired_fail(self):
        events = _full_ordered_events()
        events[BgpInitializationEvent.EOR_TIMER_EXPIRED] = 2500
        self.health_check.driver.async_get_bgp_initialization_events = AsyncMock(
            return_value=events
        )
        result = await self.health_check._run(
            self.device, self.input, {"validate_sequence": True}
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("EOR timer", result.message)

    async def test_run_validate_sequence_false_skips_ordering(self):
        """Default (validate_sequence omitted) preserves prior behavior: an
        out-of-order intermediate still PASSes as long as endpoints + timing
        are healthy."""
        events = _full_ordered_events()
        events[BgpInitializationEvent.FIB_SYNCED] = 3500
        self.health_check.driver.async_get_bgp_initialization_events = AsyncMock(
            return_value=events
        )
        result = await self.health_check._run(self.device, self.input, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_stage_times_absolute_format(self):
        """Stage times report each event's ABSOLUTE time-from-start (ms/1000),
        not a per-stage '+delta', so out-of-order events stay readable."""
        self.health_check.driver.async_get_bgp_initialization_events = AsyncMock(
            return_value=_full_ordered_events()
        )
        result = await self.health_check._run(
            self.device, self.input, {"validate_sequence": True}
        )
        self.assertIn("Stage times:", result.message)
        # Absolute time-from-start per event, not a delta from the previous one.
        self.assertIn("INITIALIZING: 0.00s", result.message)
        self.assertIn("AGENT_CONFIGURED: 1.00s", result.message)
        self.assertIn("INITIALIZED: 7.00s", result.message)
        # The old per-stage delta format ("EVENT: +Xs") must be gone.
        self.assertNotIn(": +", result.message)

    async def test_missing_endpoint_is_polled_until_converged(self):
        partial = _full_ordered_events()
        del partial[BgpInitializationEvent.INITIALIZED]
        self.health_check.driver.async_get_bgp_initialization_events = AsyncMock(
            side_effect=[partial, _full_ordered_events()]
        )

        result = await self.health_check._run(
            self.device,
            self.input,
            {
                "convergence_threshold": 10,
                "hard_timeout_seconds": 10,
                "poll_interval_seconds": 0.001,
            },
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertEqual(
            2,
            self.health_check.driver.async_get_bgp_initialization_events.await_count,
        )
        self.assertIn("outcome=WITHIN_SLA", result.message)

    async def test_event_delta_over_soft_threshold_fails_as_late(self):
        events = _full_ordered_events()
        events[BgpInitializationEvent.INITIALIZED] = 202_000
        self.health_check.driver.async_get_bgp_initialization_events = AsyncMock(
            return_value=events
        )

        result = await self.health_check._run(
            self.device,
            self.input,
            {
                "convergence_threshold": 150,
                "hard_timeout_seconds": 300,
            },
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("outcome=CONVERGED_LATE", result.message)
        self.assertIn("201.00 seconds", result.message)
        self.assertEqual(
            "CONVERGED_LATE",
            self.health_check.data_to_log["convergence_outcome"],
        )

    async def test_reversed_event_timestamps_are_not_convergence(self):
        events = _full_ordered_events()
        events[BgpInitializationEvent.INITIALIZED] = 0
        self.health_check.driver.async_get_bgp_initialization_events = AsyncMock(
            return_value=events
        )

        result = await self.health_check._run(
            self.device,
            self.input,
            {
                "convergence_threshold": 0.005,
                "hard_timeout_seconds": 0.01,
                "poll_interval_seconds": 0.001,
            },
        )

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("event timestamps are reversed", result.message)
        self.assertIn("outcome=NOT_CONVERGED", result.message)
        self.assertIsNone(self.health_check.data_to_log["convergence_time_seconds"])

    async def test_reversed_event_timestamps_are_polled_until_valid(self):
        reversed_events = _full_ordered_events()
        reversed_events[BgpInitializationEvent.INITIALIZED] = 0
        self.health_check.driver.async_get_bgp_initialization_events = AsyncMock(
            side_effect=[reversed_events, _full_ordered_events()]
        )

        result = await self.health_check._run(
            self.device,
            self.input,
            {
                "convergence_threshold": 10,
                "hard_timeout_seconds": 10,
                "poll_interval_seconds": 0.001,
            },
        )

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("event timestamps are reversed", result.message)
        self.assertIn("outcome=WITHIN_SLA", result.message)
        self.assertEqual(
            6.0,
            self.health_check.data_to_log["convergence_time_seconds"],
        )
        self.assertEqual(
            2,
            self.health_check.driver.async_get_bgp_initialization_events.await_count,
        )

    async def test_missing_endpoint_fails_at_hard_timeout(self):
        partial = _full_ordered_events()
        del partial[BgpInitializationEvent.INITIALIZED]
        self.health_check.driver.async_get_bgp_initialization_events = AsyncMock(
            return_value=partial
        )

        result = await self.health_check._run(
            self.device,
            self.input,
            {
                "convergence_threshold": 0.005,
                "hard_timeout_seconds": 0.01,
                "poll_interval_seconds": 0.001,
            },
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("outcome=NOT_CONVERGED", result.message)
        self.assertIn("hard timeout of 0.01 seconds", result.message)

    async def test_eor_failure_is_latched_while_convergence_continues(self):
        partial = _full_ordered_events()
        del partial[BgpInitializationEvent.INITIALIZED]
        partial[BgpInitializationEvent.EOR_TIMER_EXPIRED] = 2500
        self.health_check.driver.async_get_bgp_initialization_events = AsyncMock(
            side_effect=[partial, _full_ordered_events()]
        )

        result = await self.health_check._run(
            self.device,
            self.input,
            {
                "convergence_threshold": 10,
                "hard_timeout_seconds": 10,
                "poll_interval_seconds": 0.001,
            },
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("EOR timer expired", result.message)
        self.assertIn("outcome=WITHIN_SLA", result.message)
        self.assertEqual(
            2,
            self.health_check.driver.async_get_bgp_initialization_events.await_count,
        )

    async def test_sequence_failure_is_latched_while_convergence_continues(self):
        partial = _full_ordered_events()
        del partial[BgpInitializationEvent.INITIALIZED]
        partial[BgpInitializationEvent.FIB_SYNCED] = 3500
        self.health_check.driver.async_get_bgp_initialization_events = AsyncMock(
            side_effect=[partial, _full_ordered_events()]
        )

        result = await self.health_check._run(
            self.device,
            self.input,
            {
                "validate_sequence": True,
                "convergence_threshold": 10,
                "hard_timeout_seconds": 10,
                "poll_interval_seconds": 0.001,
            },
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("out of order", result.message)
        self.assertIn("outcome=WITHIN_SLA", result.message)

    async def test_transient_read_error_is_retained_after_convergence(self):
        self.health_check.driver.async_get_bgp_initialization_events = AsyncMock(
            side_effect=[
                RuntimeError("temporary thrift failure"),
                _full_ordered_events(),
            ]
        )

        result = await self.health_check._run(
            self.device,
            self.input,
            {
                "convergence_threshold": 10,
                "hard_timeout_seconds": 10,
                "poll_interval_seconds": 0.001,
            },
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("predicate_errors=1", result.message)
        self.assertIn("temporary thrift failure", result.message)

    def test_all_predicate_errors_have_distinct_summary(self):
        observation = ConvergenceResult(
            outcome=ConvergenceOutcome.NOT_CONVERGED,
            soft_threshold_seconds=1.0,
            hard_timeout_seconds=2.0,
            elapsed_seconds=2.0,
            convergence_time_seconds=None,
            confirmation_time_seconds=None,
            attempts=1,
            soft_threshold_breached=True,
            last_observation=None,
            predicate_errors=(PredicateError(2.0, "RuntimeError", "read failed"),),
        )

        message = self.health_check._format_result_message(
            observation=observation,
            device_name=self.device.name,
            start_event=BgpInitializationEvent.AGENT_CONFIGURED,
            end_event=BgpInitializationEvent.INITIALIZED,
            semantic_failures=(),
        )

        self.assertIn("could not be observed", message)
        self.assertNotIn("did not publish", message)

    def test_result_message_formats_unconfigured_soft_threshold(self):
        observation = ConvergenceResult(
            outcome=ConvergenceOutcome.CONVERGED,
            soft_threshold_seconds=None,
            hard_timeout_seconds=2.0,
            elapsed_seconds=1.0,
            convergence_time_seconds=1.0,
            confirmation_time_seconds=1.0,
            attempts=1,
            soft_threshold_breached=False,
            last_observation="ready",
            predicate_errors=(),
        )

        message = self.health_check._format_result_message(
            observation=observation,
            device_name=self.device.name,
            start_event=BgpInitializationEvent.AGENT_CONFIGURED,
            end_event=BgpInitializationEvent.INITIALIZED,
            semantic_failures=(),
        )

        self.assertIn("soft_threshold_seconds=none", message)
