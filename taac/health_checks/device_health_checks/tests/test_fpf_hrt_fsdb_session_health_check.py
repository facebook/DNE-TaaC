# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""Unit tests for FpfHrtFsdbSessionHealthCheck."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from neteng.netcastle.logger import ConsoleFileLogger
from taac.constants import TestDevice
from taac.health_checks.device_health_checks.fpf_hrt_fsdb_session_health_check import (
    FpfHrtFsdbSessionHealthCheck,
)
from taac.health_check.health_check import types as hc_types

GPU_HOST = "rtptest1544.mwg2"
CHECK_PARAMS = {"hosts": [GPU_HOST]}


def _make_session(name: str, state: str) -> MagicMock:
    """Create a mock FSDB session with the given name and state."""
    session = MagicMock()
    session.name = name
    session.state = state
    return session


class TestFpfHrtFsdbSessionHealthCheck(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.logger = MagicMock(spec=ConsoleFileLogger)
        self.health_check = FpfHrtFsdbSessionHealthCheck(logger=self.logger)
        self.health_check.driver = AsyncMock()
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "gtsw001.l1002.c087.mwg2"

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks"
        ".fpf_hrt_fsdb_session_health_check.get_hrt_client"
    )
    async def test_all_32_sessions_connected_returns_pass(self, mock_get_hrt_client):
        """All 32 sessions CONNECTED should return PASS."""
        sessions = [_make_session(f"session_{i}", "CONNECTED") for i in range(32)]

        mock_client = AsyncMock()
        mock_client.getFsdbSessions.return_value = sessions
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_get_hrt_client.return_value = mock_client

        input_data = hc_types.BaseHealthCheckIn()
        result = await self.health_check._run(self.device, input_data, CHECK_PARAMS)

        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("32/32", result.message)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks"
        ".fpf_hrt_fsdb_session_health_check.get_hrt_client"
    )
    async def test_disconnected_sessions_returns_fail(self, mock_get_hrt_client):
        """Some disconnected sessions should return FAIL with details."""
        sessions = [_make_session(f"session_{i}", "CONNECTED") for i in range(30)]
        sessions.append(_make_session("session_30", "DISCONNECTED"))
        sessions.append(_make_session("session_31", "DISCONNECTED"))

        mock_client = AsyncMock()
        mock_client.getFsdbSessions.return_value = sessions
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_get_hrt_client.return_value = mock_client

        input_data = hc_types.BaseHealthCheckIn()
        result = await self.health_check._run(self.device, input_data, CHECK_PARAMS)

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("30/32", result.message)
        self.assertIn("CONNECTED", result.message)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks"
        ".fpf_hrt_fsdb_session_health_check.get_hrt_client"
    )
    async def test_connection_failure_returns_skip(self, mock_get_hrt_client):
        """Failure to connect to HRT should return SKIP."""
        mock_get_hrt_client.side_effect = Exception("Connection refused")

        input_data = hc_types.BaseHealthCheckIn()
        result = await self.health_check._run(self.device, input_data, CHECK_PARAMS)

        self.assertEqual(result.status, hc_types.HealthCheckStatus.SKIP)
        self.assertIn("Failed to connect to HRT", result.message)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks"
        ".fpf_hrt_fsdb_session_health_check.get_hrt_client"
    )
    async def test_get_sessions_failure_returns_skip(self, mock_get_hrt_client):
        """Failure during getFsdbSessions should return SKIP."""
        mock_client = AsyncMock()
        mock_client.getFsdbSessions.side_effect = Exception("RPC timeout")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_get_hrt_client.return_value = mock_client

        input_data = hc_types.BaseHealthCheckIn()
        result = await self.health_check._run(self.device, input_data, CHECK_PARAMS)

        self.assertEqual(result.status, hc_types.HealthCheckStatus.SKIP)
        self.assertIn("Failed to get FSDB sessions", result.message)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks"
        ".fpf_hrt_fsdb_session_health_check.get_hrt_client"
    )
    async def test_custom_expected_count(self, mock_get_hrt_client):
        """A custom expected_session_count should be respected."""
        sessions = [_make_session(f"session_{i}", "CONNECTED") for i in range(16)]

        mock_client = AsyncMock()
        mock_client.getFsdbSessions.return_value = sessions
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_get_hrt_client.return_value = mock_client

        input_data = hc_types.BaseHealthCheckIn()
        params = {"hosts": [GPU_HOST], "expected_session_count": 16}
        result = await self.health_check._run(self.device, input_data, params)

        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("16/16", result.message)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks"
        ".fpf_hrt_fsdb_session_health_check.get_hrt_client"
    )
    async def test_fewer_sessions_than_expected_returns_fail(self, mock_get_hrt_client):
        """Fewer total sessions than expected should return FAIL."""
        sessions = [_make_session(f"session_{i}", "CONNECTED") for i in range(20)]

        mock_client = AsyncMock()
        mock_client.getFsdbSessions.return_value = sessions
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_get_hrt_client.return_value = mock_client

        input_data = hc_types.BaseHealthCheckIn()
        result = await self.health_check._run(self.device, input_data, CHECK_PARAMS)

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("expected 32", result.message)

    async def test_no_hosts_returns_skip(self):
        """No hosts in check_params should return SKIP."""
        input_data = hc_types.BaseHealthCheckIn()
        result = await self.health_check._run(self.device, input_data, {})

        self.assertEqual(result.status, hc_types.HealthCheckStatus.SKIP)
        self.assertIn("No GPU hosts", result.message)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks"
        ".fpf_hrt_fsdb_session_health_check.get_hrt_client"
    )
    async def test_multiple_hosts_all_pass(self, mock_get_hrt_client):
        """Multiple hosts all passing should return PASS."""
        sessions = [_make_session(f"session_{i}", "CONNECTED") for i in range(32)]

        mock_client = AsyncMock()
        mock_client.getFsdbSessions.return_value = sessions
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_get_hrt_client.return_value = mock_client

        input_data = hc_types.BaseHealthCheckIn()
        params = {"hosts": ["rtptest1544.mwg2", "rtptest1543.mwg2"]}
        result = await self.health_check._run(self.device, input_data, params)

        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertEqual(mock_get_hrt_client.call_count, 2)

    @staticmethod
    def _grid_sessions(down=None):
        """Full 4x8 session grid with realistic device_id/plane_id; ``down`` is
        {gpu: {lanes}} marked DISCONNECTED."""
        down = down or {}
        out = []
        for gpu in range(4):
            for lane in range(8):
                state = "DISCONNECTED" if lane in down.get(gpu, set()) else "CONNECTED"
                s = MagicMock()
                s.name = f"g{gpu}l{lane}"
                s.device_id = gpu
                s.plane_id = lane
                s.state = state
                out.append(s)
        return out

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks"
        ".fpf_hrt_fsdb_session_health_check.get_hrt_client"
    )
    async def test_interface_disable_impacted_lane_reconciles_pass(
        self, mock_get_hrt_client
    ):
        """GPU0 lane0 disabled -> 31/32 overall and dev0 lane0 DOWN -> PASS."""
        sessions = self._grid_sessions(down={0: {0}})
        mock_client = AsyncMock()
        mock_client.getFsdbSessions.return_value = sessions
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_get_hrt_client.return_value = mock_client

        params = {
            "hosts": [GPU_HOST],
            "impacted_lanes_by_host_gpu": {GPU_HOST: {0: [0]}},
            "reconcile_device_id": 0,
        }
        result = await self.health_check._run(
            self.device, hc_types.BaseHealthCheckIn(), params
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("31/32", result.message)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks"
        ".fpf_hrt_fsdb_session_health_check.get_hrt_client"
    )
    async def test_interface_disable_lane_still_connected_fails(
        self, mock_get_hrt_client
    ):
        """GPU0 lane0 expected down but still CONNECTED -> FAIL (Signal 2)."""
        sessions = self._grid_sessions(down={})  # nothing actually down
        mock_client = AsyncMock()
        mock_client.getFsdbSessions.return_value = sessions
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_get_hrt_client.return_value = mock_client

        params = {
            "hosts": [GPU_HOST],
            "impacted_lanes_by_host_gpu": {GPU_HOST: {0: [0]}},
            "reconcile_device_id": 0,
        }
        result = await self.health_check._run(
            self.device, hc_types.BaseHealthCheckIn(), params
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)

    def test_check_scope_is_default(self):
        """CHECK_SCOPE should be DEFAULT (run once on DUT, not per endpoint)."""
        self.assertEqual(
            FpfHrtFsdbSessionHealthCheck.CHECK_SCOPE, hc_types.Scope.DEFAULT
        )

    async def test_non_rtptest_hosts_filtered_out(self):
        """Non-rtptest hosts should be filtered with a warning."""
        input_data = hc_types.BaseHealthCheckIn()
        params = {"hosts": ["gtsw001.l1002.c087.mwg2"]}
        result = await self.health_check._run(self.device, input_data, params)

        self.assertEqual(result.status, hc_types.HealthCheckStatus.SKIP)
        self.assertIn("No valid rtptest", result.message)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks"
        ".fpf_hrt_fsdb_session_health_check.get_hrt_client"
    )
    async def test_mixed_hosts_only_checks_rtptest(self, mock_get_hrt_client):
        """Only rtptest hosts should be checked; gtsw hosts should be skipped."""
        sessions = [_make_session(f"session_{i}", "CONNECTED") for i in range(32)]

        mock_client = AsyncMock()
        mock_client.getFsdbSessions.return_value = sessions
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_get_hrt_client.return_value = mock_client

        input_data = hc_types.BaseHealthCheckIn()
        params = {"hosts": ["rtptest1544.mwg2", "gtsw001.l1002.c087.mwg2"]}
        result = await self.health_check._run(self.device, input_data, params)

        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertEqual(mock_get_hrt_client.call_count, 1)
        mock_get_hrt_client.assert_called_with("rtptest1544.mwg2")
