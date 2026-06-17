# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""Unit tests for BgpSessionEstablishedHealthCheck."""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from neteng.fboss.bgp_thrift.types import TBgpPeerState
from neteng.netcastle.logger import ConsoleFileLogger
from taac.constants import TestDevice
from taac.health_checks.device_health_checks.bgp_session_health_check import (
    BgpSessionEstablishedHealthCheck,
)
from taac.health_checks.healthcheck_definitions import (
    create_bgp_session_establish_check,
)
from taac.health_check.health_check import types as hc_types


def _make_bgp_session(
    peer_addr, state, my_addr="fc00::1", uptime=1000, remote_as=65000
):
    session = MagicMock()
    session.peer_addr = peer_addr
    session.my_addr = my_addr
    session.uptime = uptime
    session.peer.peer_state = state
    session.peer.remote_as = remote_as
    return session


class TestBgpSessionEstablishedHealthCheck(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.logger = MagicMock(spec=ConsoleFileLogger)
        self.health_check = BgpSessionEstablishedHealthCheck(logger=self.logger)
        self.health_check.driver = AsyncMock()
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "rsw001.p001.f01.ash6"
        self.input = hc_types.BaseHealthCheckIn()

    async def test_all_sessions_established_returns_pass(self):
        """All BGP sessions established should return PASS."""
        self.health_check.driver.async_get_bgp_sessions = AsyncMock(
            return_value=[
                _make_bgp_session("2401:db00::1", TBgpPeerState.ESTABLISHED),
                _make_bgp_session("2401:db00::2", TBgpPeerState.ESTABLISHED),
            ]
        )
        result = await self.health_check._run(self.device, self.input, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_non_established_session_returns_fail(self):
        """A non-established session should return FAIL."""
        self.health_check.driver.async_get_bgp_sessions = AsyncMock(
            return_value=[
                _make_bgp_session("2401:db00::1", TBgpPeerState.ESTABLISHED),
                _make_bgp_session("2401:db00::2", TBgpPeerState.ACTIVE),
            ]
        )
        result = await self.health_check._run(self.device, self.input, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)

    async def test_no_sessions_returns_fail(self):
        """No BGP sessions should return FAIL."""
        self.health_check.driver.async_get_bgp_sessions = AsyncMock(return_value=[])
        result = await self.health_check._run(self.device, self.input, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)

    async def test_parent_prefixes_to_ignore_skips_matching_sessions(self):
        """Sessions matching parent_prefixes_to_ignore should be excluded."""
        self.health_check.driver.async_get_bgp_sessions = AsyncMock(
            return_value=[
                _make_bgp_session("2401:db00::1", TBgpPeerState.ESTABLISHED),
                _make_bgp_session("10.0.0.1", TBgpPeerState.ACTIVE),
            ]
        )
        result = await self.health_check._run(
            self.device,
            self.input,
            {"parent_prefixes_to_ignore": ["10.0.0.0/24"]},
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_expected_count_mismatch_returns_fail(self):
        """When expected_established_session_count doesn't match, should FAIL."""
        self.health_check.driver.async_get_bgp_sessions = AsyncMock(
            return_value=[
                _make_bgp_session("2401:db00::1", TBgpPeerState.ESTABLISHED),
            ]
        )
        result = await self.health_check._run(
            self.device,
            self.input,
            {"expected_established_session_count": 5},
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)


class TestHealthCheckRetry(unittest.IsolatedAsyncioTestCase):
    """Tests for the configurable per-check retry logic in run()."""

    def setUp(self):
        self.logger = MagicMock(spec=ConsoleFileLogger)
        self.health_check = BgpSessionEstablishedHealthCheck(logger=self.logger)
        self.health_check.driver = AsyncMock()
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "bag011.ash6"
        self.device.attributes = MagicMock()
        self.device.attributes.operating_system = "FBOSS"
        self.input = hc_types.BaseHealthCheckIn()

    def _make_fail_result(self, message="session mismatch"):
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.FAIL,
            message=message,
        )

    def _make_pass_result(self, message="all sessions established"):
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=message,
        )

    @patch(
        "neteng.test_infra.dne.taac.health_checks.abstract_health_check.asyncio.sleep",
        new_callable=AsyncMock,
    )
    async def test_no_retry_params_backward_compat(self, mock_sleep):
        """Without retry keys in check_params, check runs exactly once."""
        self.health_check._run = AsyncMock(return_value=self._make_fail_result())

        result = await self.health_check.run(self.device, self.input, self.input, {})

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertEqual(self.health_check._run.call_count, 1)
        mock_sleep.assert_not_called()

    @patch(
        "neteng.test_infra.dne.taac.health_checks.abstract_health_check.asyncio.sleep",
        new_callable=AsyncMock,
    )
    async def test_retry_on_fail_then_pass(self, mock_sleep):
        """FAIL on first attempt, PASS on second — overall result is PASS."""
        self.health_check._run = AsyncMock(
            side_effect=[self._make_fail_result(), self._make_pass_result()]
        )

        result = await self.health_check.run(
            self.device,
            self.input,
            self.input,
            {"retry_count": 2, "retry_delay_seconds": 5.0},
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertEqual(self.health_check._run.call_count, 2)
        mock_sleep.assert_called_once_with(5.0)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.abstract_health_check.asyncio.sleep",
        new_callable=AsyncMock,
    )
    async def test_retry_exhausted_returns_annotated_fail(self, mock_sleep):
        """All retries exhausted — FAIL with annotation in message."""
        self.health_check._run = AsyncMock(return_value=self._make_fail_result())

        result = await self.health_check.run(
            self.device,
            self.input,
            self.input,
            {"retry_count": 3, "retry_delay_seconds": 1.0},
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertEqual(self.health_check._run.call_count, 4)
        self.assertIn("[Failed after 3 retries]", result.message)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.abstract_health_check.asyncio.sleep",
        new_callable=AsyncMock,
    )
    async def test_no_retry_on_pass(self, mock_sleep):
        """PASS on first attempt — no retry even with retry_count > 0."""
        self.health_check._run = AsyncMock(return_value=self._make_pass_result())

        result = await self.health_check.run(
            self.device,
            self.input,
            self.input,
            {"retry_count": 3, "retry_delay_seconds": 5.0},
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertEqual(self.health_check._run.call_count, 1)
        mock_sleep.assert_not_called()

    @patch(
        "neteng.test_infra.dne.taac.health_checks.abstract_health_check.asyncio.sleep",
        new_callable=AsyncMock,
    )
    async def test_no_retry_on_error(self, mock_sleep):
        """Exception in _run → ERROR status, no retry."""
        self.health_check._run = AsyncMock(side_effect=RuntimeError("driver failure"))

        result = await self.health_check.run(
            self.device,
            self.input,
            self.input,
            {"retry_count": 3, "retry_delay_seconds": 5.0},
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.ERROR)
        self.assertEqual(self.health_check._run.call_count, 1)
        mock_sleep.assert_not_called()

    @patch(
        "neteng.test_infra.dne.taac.health_checks.abstract_health_check.asyncio.sleep",
        new_callable=AsyncMock,
    )
    async def test_retry_delay_backoff(self, mock_sleep):
        """Verify delay increases with retry_delay_multiplier."""
        self.health_check._run = AsyncMock(return_value=self._make_fail_result())

        await self.health_check.run(
            self.device,
            self.input,
            self.input,
            {
                "retry_count": 3,
                "retry_delay_seconds": 10.0,
                "retry_delay_multiplier": 1.5,
            },
        )

        self.assertEqual(mock_sleep.call_count, 3)
        delays = [call.args[0] for call in mock_sleep.call_args_list]
        self.assertAlmostEqual(delays[0], 10.0)
        self.assertAlmostEqual(delays[1], 15.0)
        self.assertAlmostEqual(delays[2], 22.5)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.abstract_health_check.asyncio.sleep",
        new_callable=AsyncMock,
    )
    async def test_no_retry_on_skip(self, mock_sleep):
        """SKIP from _run — no retry even with retry_count > 0."""
        skip_result = hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.SKIP,
            message="check not applicable",
        )
        self.health_check._run = AsyncMock(return_value=skip_result)

        result = await self.health_check.run(
            self.device,
            self.input,
            self.input,
            {"retry_count": 3, "retry_delay_seconds": 5.0},
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.SKIP)
        self.assertEqual(self.health_check._run.call_count, 1)
        mock_sleep.assert_not_called()

    @patch(
        "neteng.test_infra.dne.taac.health_checks.abstract_health_check.asyncio.sleep",
        new_callable=AsyncMock,
    )
    async def test_retry_exhausted_preserves_original_message(self, mock_sleep):
        """Annotated fail message must contain the original failure detail."""
        self.health_check._run = AsyncMock(
            return_value=self._make_fail_result("expected 1287, found 1285")
        )

        result = await self.health_check.run(
            self.device,
            self.input,
            self.input,
            {"retry_count": 2, "retry_delay_seconds": 1.0},
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("[Failed after 2 retries]", result.message)
        self.assertIn("expected 1287, found 1285", result.message)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.abstract_health_check.asyncio.sleep",
        new_callable=AsyncMock,
    )
    async def test_negative_retry_count_clamped_to_zero(self, mock_sleep):
        """Negative retry_count should be clamped to 0 (single-shot)."""
        self.health_check._run = AsyncMock(return_value=self._make_fail_result())

        result = await self.health_check.run(
            self.device,
            self.input,
            self.input,
            {"retry_count": -1, "retry_delay_seconds": 5.0},
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertEqual(self.health_check._run.call_count, 1)
        mock_sleep.assert_not_called()


class TestCreateBgpSessionEstablishCheckRetryParams(unittest.TestCase):
    """Tests for retry kwargs in the factory function."""

    def test_factory_retry_params_in_json(self):
        """Retry params should appear in json_params of the check."""
        check = create_bgp_session_establish_check(
            expected_established_sessions=1287,
            retry_count=3,
            retry_delay_seconds=10.0,
            retry_delay_multiplier=1.5,
        )

        self.assertIsNotNone(check.check_params)
        self.assertIsNotNone(check.check_params.json_params)
        payload = json.loads(check.check_params.json_params)
        self.assertEqual(payload["retry_count"], 3)
        self.assertEqual(payload["retry_delay_seconds"], 10.0)
        self.assertEqual(payload["retry_delay_multiplier"], 1.5)

    def test_factory_no_retry_params_omitted(self):
        """When retry kwargs are not provided, they should not appear in json."""
        check = create_bgp_session_establish_check(
            expected_established_sessions=1287,
        )

        self.assertIsNotNone(check.check_params)
        self.assertIsNotNone(check.check_params.json_params)
        payload = json.loads(check.check_params.json_params)
        self.assertNotIn("retry_count", payload)
        self.assertNotIn("retry_delay_seconds", payload)
        self.assertNotIn("retry_delay_multiplier", payload)


if __name__ == "__main__":
    unittest.main()
