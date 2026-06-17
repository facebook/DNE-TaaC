# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from neteng.fboss.ctrl.thrift_types import DsfSessionState, DsfSessionThrift
from neteng.test_infra.dne.taac.constants import TestDevice, TestTopology
from taac.health_checks.dsf_health_checks.dsf_fsdb_session_health_check import (
    DsfFsdbSessionHealthCheck,
)
from taac.utils.oss_taac_lib_utils import ConsoleFileLogger
from taac.health_check.health_check import types as hc_types


class TestDsfFsdbSessionHealthCheck(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        """Set up test fixtures."""
        self.logger = MagicMock(spec=ConsoleFileLogger)
        self.health_check = DsfFsdbSessionHealthCheck(logger=self.logger)

        # Create mock devices
        self.device1 = MagicMock(spec=TestDevice)
        self.device1.name = "rdsw001.u000.c083.snc1"
        self.device2 = MagicMock(spec=TestDevice)
        self.device2.name = "rdsw002.u000.c083.snc1"

        # Create mock topology
        self.topology = MagicMock(spec=TestTopology)
        self.topology.devices = [self.device1, self.device2]
        self.topology.device_names = [
            self.device1.name,
            self.device2.name,
        ]

        # Mock driver
        self.mock_driver1 = AsyncMock()
        self.mock_driver2 = AsyncMock()

        # Mock health check input
        self.health_check_input = hc_types.BaseHealthCheckIn()

        # Mock DSF sessions data
        self.established_sessions_at_switch_1 = [
            DsfSessionThrift(
                remoteName=f"{self.device2.name}::2401:db00:e011:850::d:2",
                state=DsfSessionState.ESTABLISHED,
                lastEstablishedAt=1755581099,
            ),
        ]

        self.established_sessions_at_switch_2 = [
            DsfSessionThrift(
                remoteName=f"{self.device1.name}::2401:db00:e011:850::e:2",
                state=DsfSessionState.ESTABLISHED,
                lastEstablishedAt=1755581098,
            ),
        ]

        self.failed_sessions_at_switch_1 = [
            DsfSessionThrift(
                remoteName=f"{self.device2.name}::2401:db00:e011:850::d:2",
                state=DsfSessionState.CONNECT,
            ),
        ]

        # Mock switch ID mapping
        self.switch_id_mapping = {
            1: self.device1.name,
            2: self.device2.name,
        }

        # Setup mock driver
        def _mock_get_driver_side_effect(hostname):
            if hostname == self.device1.name:
                return self.mock_driver1
            elif hostname == self.device2.name:
                return self.mock_driver2

        self._mock_get_driver_side_effect = _mock_get_driver_side_effect

    @patch(
        "neteng.test_infra.dne.taac.health_checks.dsf_health_checks.dsf_fsdb_session_health_check.async_get_device_driver"
    )
    async def test_dsf_session_check_passing(self, mock_get_driver):
        """Test DSF session health check with all sessions established."""

        mock_get_driver.side_effect = self._mock_get_driver_side_effect
        self.mock_driver1.async_get_dsf_cluster_switch_id_mapping.return_value = (
            self.switch_id_mapping
        )

        self.mock_driver1.async_get_dsf_sessions.return_value = (
            self.established_sessions_at_switch_1
        )
        self.mock_driver2.async_get_dsf_sessions.return_value = (
            self.established_sessions_at_switch_2
        )

        # Run the health check
        result = await self.health_check._run(
            self.topology, self.health_check_input, {}
        )

        # Verify the result
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIsNone(result.message)

        # Verify mock calls
        self.mock_driver1.async_get_dsf_cluster_switch_id_mapping.assert_called_once()
        self.mock_driver1.async_get_dsf_sessions.assert_called_once()
        self.mock_driver2.async_get_dsf_sessions.assert_called_once()

    @patch(
        "neteng.test_infra.dne.taac.health_checks.dsf_health_checks.dsf_fsdb_session_health_check.async_get_device_driver"
    )
    async def test_dsf_session_check_failing(self, mock_get_driver):
        """Test DSF session health check with failed sessions."""
        # Setup mock driver
        mock_get_driver.side_effect = self._mock_get_driver_side_effect
        self.mock_driver1.async_get_dsf_cluster_switch_id_mapping.return_value = (
            self.switch_id_mapping
        )
        self.mock_driver1.async_get_dsf_sessions.return_value = (
            self.failed_sessions_at_switch_1
        )
        self.mock_driver2.async_get_dsf_sessions.return_value = (
            self.established_sessions_at_switch_2
        )

        # Run the health check
        result = await self.health_check._run(
            self.topology, self.health_check_input, {}
        )

        # Verify the result
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn(
            "DSF session is not established from rdsw001.u000.c083.snc1 towards rdsw002.u000.c083.snc1",
            result.message,
        )

        # Verify mock calls
        self.mock_driver1.async_get_dsf_cluster_switch_id_mapping.assert_called_once()
        self.mock_driver1.async_get_dsf_sessions.assert_called_once()
        self.mock_driver2.async_get_dsf_sessions.assert_called_once()
