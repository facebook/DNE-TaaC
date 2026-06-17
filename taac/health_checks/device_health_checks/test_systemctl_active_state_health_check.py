# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""Unit tests for SystemctlActiveStateHealthCheck."""

import unittest
from unittest.mock import AsyncMock, MagicMock

from neteng.netcastle.logger import ConsoleFileLogger
from taac.constants import TestDevice
from taac.health_checks.device_health_checks.systemctl_active_state_health_check import (
    SystemctlActiveStateHealthCheck,
)
from taac.health_check.health_check import types as hc_types


class TestSystemctlActiveStateHealthCheck(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.logger = MagicMock(spec=ConsoleFileLogger)
        self.health_check = SystemctlActiveStateHealthCheck(logger=self.logger)
        self.health_check.driver = AsyncMock()
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "rsw001.p001.f01.ash6"

    async def test_all_services_active_returns_pass(self):
        """All services active should return PASS."""
        self.health_check.driver.async_run_cmd_on_shell = AsyncMock(
            return_value="LoadState=loaded\nActiveState=active\nSubState=running\n"
        )
        input_data = hc_types.SystemctlActiveStateHealthCheckIn()
        result = await self.health_check._run(self.device, input_data, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_inactive_service_returns_fail(self):
        """An inactive service should return FAIL with the service name."""
        self.health_check.driver.async_run_cmd_on_shell = AsyncMock(
            return_value="LoadState=loaded\nActiveState=inactive\nSubState=dead\n"
        )
        input_data = hc_types.SystemctlActiveStateHealthCheckIn(
            services=[hc_types.Service.WEDGE_AGENT],
        )
        result = await self.health_check._run(self.device, input_data, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("not active", result.message)

    async def test_disabled_service_is_skipped(self):
        """A disabled service (UnitFileState=disabled) should be treated as active."""
        self.health_check.driver.async_run_cmd_on_shell = AsyncMock(
            return_value="LoadState=loaded\nUnitFileState=disabled\nActiveState=inactive\n"
        )
        input_data = hc_types.SystemctlActiveStateHealthCheckIn(
            services=[hc_types.Service.WEDGE_AGENT],
        )
        result = await self.health_check._run(self.device, input_data, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_not_loaded_service_is_skipped(self):
        """A service that is not loaded should be treated as active (skipped)."""
        self.health_check.driver.async_run_cmd_on_shell = AsyncMock(
            return_value="LoadState=not-found\nActiveState=inactive\n"
        )
        input_data = hc_types.SystemctlActiveStateHealthCheckIn(
            services=[hc_types.Service.WEDGE_AGENT],
        )
        result = await self.health_check._run(self.device, input_data, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_mixed_services_reports_inactive_ones(self):
        """Only inactive services should appear in the failure message."""

        async def mock_cmd(cmd):
            if "wedge_agent" in cmd:
                return "LoadState=loaded\nActiveState=active\n"
            return "LoadState=loaded\nActiveState=inactive\n"

        self.health_check.driver.async_run_cmd_on_shell = AsyncMock(
            side_effect=mock_cmd
        )
        input_data = hc_types.SystemctlActiveStateHealthCheckIn(
            services=[hc_types.Service.WEDGE_AGENT, hc_types.Service.BGPD],
        )
        result = await self.health_check._run(self.device, input_data, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn(self.device.name, result.message)


if __name__ == "__main__":
    unittest.main()
