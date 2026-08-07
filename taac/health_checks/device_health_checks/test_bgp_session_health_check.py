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
    async def test_transient_exception_is_retried_then_error(self, mock_sleep):
        """A raised exception (transient data-fetch failure) is retried for
        every check, and surfaces as ERROR after retries are exhausted."""
        self.health_check._run = AsyncMock(side_effect=RuntimeError("driver failure"))

        result = await self.health_check.run(
            self.device,
            self.input,
            self.input,
            {"retry_count": 3, "retry_delay_seconds": 5.0},
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.ERROR)
        self.assertEqual(self.health_check._run.call_count, 4)
        self.assertEqual(mock_sleep.call_count, 3)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.abstract_health_check.asyncio.sleep",
        new_callable=AsyncMock,
    )
    async def test_transient_exception_then_pass_recovers(self, mock_sleep):
        """A transient exception followed by a PASS recovers (no ERROR)."""
        self.health_check._run = AsyncMock(
            side_effect=[RuntimeError("driver blip"), self._make_pass_result()]
        )

        result = await self.health_check.run(
            self.device,
            self.input,
            self.input,
            {"retry_count": 3, "retry_delay_seconds": 5.0},
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertEqual(self.health_check._run.call_count, 2)
        mock_sleep.assert_called_once_with(5.0)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.abstract_health_check.asyncio.sleep",
        new_callable=AsyncMock,
    )
    async def test_returned_error_is_not_retried(self, mock_sleep):
        """A returned (non-raised) ERROR verdict is terminal — not retried."""
        error_result = hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.ERROR,
            message="explicit error verdict",
        )
        self.health_check._run = AsyncMock(return_value=error_result)

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
    async def test_static_check_fail_not_retried(self, mock_sleep):
        """A check with RETRY_ON_FAIL = False (static) does not retry a FAIL."""
        self.health_check._run = AsyncMock(return_value=self._make_fail_result())

        with patch.object(BgpSessionEstablishedHealthCheck, "RETRY_ON_FAIL", False):
            result = await self.health_check.run(
                self.device,
                self.input,
                self.input,
                {"retry_count": 3, "retry_delay_seconds": 5.0},
            )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
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


# eBGP peers hang off the IXIA parent; iBGP planes live elsewhere. UG 2.2.1
# scopes its isolation check to iBGP by ignoring this parent.
_EBGP_PARENT = "2401:db00:e50d:11:8::/80"
_EBGP_PEERS = ["2401:db00:e50d:11:8::11", "2401:db00:e50d:11:8::13"]
_IBGP_PEERS = ["2401:db00:e50d:20::1", "2401:db00:e50d:20::2"]


class PeerScopeFilterTest(unittest.TestCase):
    """_peer_in_scope is the single definition of "in scope".

    The verdict loop and the peer-identity check both route through it so they
    cannot drift apart.
    """

    def test_peer_under_an_ignored_parent_is_out_of_scope(self):
        self.assertFalse(
            BgpSessionEstablishedHealthCheck._peer_in_scope(
                _EBGP_PEERS[0], [_EBGP_PARENT], None
            )
        )

    def test_peer_outside_an_ignored_parent_stays_in_scope(self):
        self.assertTrue(
            BgpSessionEstablishedHealthCheck._peer_in_scope(
                _IBGP_PEERS[0], [_EBGP_PARENT], None
            )
        )

    def test_allowlist_admits_only_exact_matches(self):
        allow = [_IBGP_PEERS[0]]
        self.assertTrue(
            BgpSessionEstablishedHealthCheck._peer_in_scope(_IBGP_PEERS[0], None, allow)
        )
        self.assertFalse(
            BgpSessionEstablishedHealthCheck._peer_in_scope(_IBGP_PEERS[1], None, allow)
        )

    def test_no_filters_admits_every_peer(self):
        self.assertTrue(
            BgpSessionEstablishedHealthCheck._peer_in_scope(_EBGP_PEERS[0], None, None)
        )
        self.assertTrue(
            BgpSessionEstablishedHealthCheck._peer_in_scope(_IBGP_PEERS[0], [], [])
        )


class ValidatePeerIdentityScopeTest(unittest.TestCase):
    """The expected set must be filtered by the same scope as the actual set.

    ``expected_peers`` is every configured peer, while ``established_sessions``
    has already been narrowed by the caller's filters. Comparing the two
    unfiltered reported every out-of-scope peer as missing: on bag011 that was
    a bogus "Missing expected peers (280)" warning on a healthy run
    (1272 configured - 992 in scope).
    """

    def setUp(self):
        self.logger = MagicMock(spec=ConsoleFileLogger)
        self.health_check = BgpSessionEstablishedHealthCheck(logger=self.logger)
        self.expected = dict.fromkeys(_EBGP_PEERS + _IBGP_PEERS, "fc00::1")

    def _validate(self, established_peers):
        return self.health_check._validate_peer_identity(
            self.expected,
            [
                _make_bgp_session(peer, TBgpPeerState.ESTABLISHED, my_addr="fc00::1")
                for peer in established_peers
            ],
            "bag011.ash6",
            [_EBGP_PARENT],
            None,
        )

    def test_out_of_scope_peers_are_not_reported_missing(self):
        # Caller scoped to iBGP, so the eBGP peers are absent by design.
        self.assertEqual([], self._validate(_IBGP_PEERS))

    def test_in_scope_peer_that_is_genuinely_absent_is_still_reported(self):
        # The scope filter must not blanket-silence the missing-peer warning.
        warnings = self._validate([_IBGP_PEERS[0]])
        self.assertEqual(1, len(warnings))
        self.assertIn("Missing 1 expected peers", warnings[0])
        self.assertIn(_IBGP_PEERS[1], warnings[0])


if __name__ == "__main__":
    unittest.main()
