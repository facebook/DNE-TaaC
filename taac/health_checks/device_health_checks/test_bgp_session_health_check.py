# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe
"""Unit tests for BgpSessionEstablishedHealthCheck."""

import unittest
from unittest.mock import AsyncMock, MagicMock

from neteng.fboss.bgp_thrift.types import TBgpPeerState
from neteng.netcastle.logger import ConsoleFileLogger
from taac.constants import TestDevice
from taac.health_checks.device_health_checks.bgp_session_health_check import (
    BgpSessionEstablishedHealthCheck,
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

    async def test_ignore_prefixes_skips_matching_sessions(self):
        """Sessions matching ignore_prefixes should be excluded from check."""
        self.health_check.driver.async_get_bgp_sessions = AsyncMock(
            return_value=[
                _make_bgp_session("2401:db00::1", TBgpPeerState.ESTABLISHED),
                _make_bgp_session("10.0.0.1", TBgpPeerState.ACTIVE),
            ]
        )
        result = await self.health_check._run(
            self.device,
            self.input,
            {"ignore_prefixes": ["10.0.0.1"]},
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


if __name__ == "__main__":
    unittest.main()
