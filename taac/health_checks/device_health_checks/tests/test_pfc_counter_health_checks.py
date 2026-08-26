# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from neteng.netcastle.logger import ConsoleFileLogger
from taac.constants import TestDevice
from taac.health_checks.device_health_checks.clear_counters_health_check import (
    ClearCountersHealthCheck,
)
from taac.health_checks.device_health_checks.port_counters_health_check import (
    PortCountersHealthCheck,
)
from taac.health_check.health_check import types as hc_types


def _make_device(name: str = "gtsw001.example", os: str = "FBOSS") -> TestDevice:
    device = MagicMock(spec=TestDevice)
    device.name = name
    device.attributes = MagicMock()
    device.attributes.operating_system = os
    device.attributes.role = "GTSW"
    return device


class TestPfcCounterHealthChecks(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.logger = MagicMock(spec=ConsoleFileLogger)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "clear_counters_health_check.asyncio.sleep",
        new_callable=AsyncMock,
    )
    async def test_fboss_clear_stops_and_restarts_traffic(self, mock_sleep) -> None:
        check = ClearCountersHealthCheck(logger=self.logger)
        check.driver = AsyncMock()
        check.ixia = MagicMock()

        result = await check._run(_make_device(), hc_types.BaseHealthCheckIn(), {})

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        check.ixia.stop_traffic.assert_called_once_with()
        check.driver.async_run_cmd_on_shell.assert_awaited_once_with(
            "fboss2 clear interface counters"
        )
        check.driver.async_execute_show_or_configure_cmd_on_shell.assert_not_awaited()
        check.ixia.start_traffic.assert_called_once_with()
        self.assertEqual(2, mock_sleep.await_count)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "clear_counters_health_check.asyncio.sleep",
        new_callable=AsyncMock,
    )
    async def test_clear_rejects_unsupported_os_and_restarts_traffic(
        self, mock_sleep
    ) -> None:
        check = ClearCountersHealthCheck(logger=self.logger)
        check.driver = AsyncMock()
        check.ixia = MagicMock()

        result = await check._run(
            _make_device(os="UNKNOWN"), hc_types.BaseHealthCheckIn(), {}
        )

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("Unsupported operating system: UNKNOWN", result.message or "")
        check.driver.async_run_cmd_on_shell.assert_not_awaited()
        check.driver.async_execute_show_or_configure_cmd_on_shell.assert_not_awaited()
        check.ixia.start_traffic.assert_called_once_with()
        self.assertEqual(2, mock_sleep.await_count)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "port_counters_health_check.async_get_device_driver",
        new_callable=AsyncMock,
    )
    async def test_remote_target_device_is_checked(self, mock_get_driver) -> None:
        check = PortCountersHealthCheck(logger=self.logger)
        check.driver = AsyncMock()
        remote_driver = AsyncMock()
        remote_driver.async_get_multiple_port_stats.return_value = []
        mock_get_driver.return_value = remote_driver
        threshold = hc_types.PortCountersThreshold(
            interfaces=["gtsw002.example:eth1/1/1"],
            out_discards=0,
            comparison=hc_types.ComparisonType.EQUAL_TO,
        )

        result = await check._run(
            _make_device(),
            hc_types.PortCountersHealthCheckIn(thresholds=[threshold]),
            {},
        )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        check.driver.async_get_multiple_port_stats.assert_not_awaited()
        mock_get_driver.assert_awaited_once_with("gtsw002.example")
        remote_driver.async_get_multiple_port_stats.assert_awaited_once_with(
            ["eth1/1/1"]
        )

    async def test_unqualified_interface_targets_current_device(self) -> None:
        check = PortCountersHealthCheck(logger=self.logger)
        check.driver = AsyncMock()
        check.driver.async_get_multiple_port_stats.return_value = []
        threshold = hc_types.PortCountersThreshold(
            interfaces=["eth1/1/1"],
            out_discards=0,
            comparison=hc_types.ComparisonType.EQUAL_TO,
        )

        result = await check._run(
            _make_device(),
            hc_types.PortCountersHealthCheckIn(thresholds=[threshold]),
            {},
        )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        check.driver.async_get_multiple_port_stats.assert_awaited_once_with(
            ["eth1/1/1"]
        )

    async def test_target_device_matches_fully_qualified_hostname(self) -> None:
        check = PortCountersHealthCheck(logger=self.logger)
        check.driver = AsyncMock()
        check.driver.async_get_multiple_port_stats.return_value = []
        threshold = hc_types.PortCountersThreshold(
            interfaces=["gtsw001.example:eth1/1/1"],
            out_discards=0,
            comparison=hc_types.ComparisonType.EQUAL_TO,
        )

        result = await check._run(
            _make_device(name="gtsw001.example.facebook.com"),
            hc_types.PortCountersHealthCheckIn(thresholds=[threshold]),
            {},
        )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        check.driver.async_get_multiple_port_stats.assert_awaited_once_with(
            ["eth1/1/1"]
        )

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "port_counters_health_check.async_get_device_driver",
        new_callable=AsyncMock,
    )
    async def test_short_hostname_targets_current_device(self, mock_get_driver) -> None:
        check = PortCountersHealthCheck(logger=self.logger)
        check.driver = AsyncMock()
        check.driver.async_get_multiple_port_stats.return_value = []
        threshold = hc_types.PortCountersThreshold(
            interfaces=["gtsw001:eth1/1/1"],
            out_discards=0,
            comparison=hc_types.ComparisonType.EQUAL_TO,
        )

        result = await check._run(
            _make_device(name="gtsw001.l1001.c085.ash6"),
            hc_types.PortCountersHealthCheckIn(thresholds=[threshold]),
            {},
        )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        mock_get_driver.assert_not_awaited()
        check.driver.async_get_multiple_port_stats.assert_awaited_once_with(
            ["eth1/1/1"]
        )

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "clear_counters_health_check.asyncio.sleep",
        new_callable=AsyncMock,
    )
    async def test_fboss_clear_failure_still_restarts_traffic(
        self, _mock_sleep
    ) -> None:
        check = ClearCountersHealthCheck(logger=self.logger)
        check.driver = AsyncMock()
        check.driver.async_run_cmd_on_shell.side_effect = RuntimeError("clear failed")
        check.ixia = MagicMock()

        result = await check._run(_make_device(), hc_types.BaseHealthCheckIn(), {})

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        check.ixia.stop_traffic.assert_called_once_with()
        check.ixia.start_traffic.assert_called_once_with()

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "clear_counters_health_check.asyncio.sleep",
        new_callable=AsyncMock,
    )
    async def test_clear_and_restart_failures_are_both_reported(
        self, _mock_sleep
    ) -> None:
        check = ClearCountersHealthCheck(logger=self.logger)
        check.driver = AsyncMock()
        check.driver.async_run_cmd_on_shell.side_effect = RuntimeError("clear failed")
        check.ixia = MagicMock()
        check.ixia.start_traffic.side_effect = RuntimeError("restart failed")

        result = await check._run(_make_device(), hc_types.BaseHealthCheckIn(), {})

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        message = result.message or ""
        self.assertIn("clear failed", message)
        self.assertIn("restart failed", message)
