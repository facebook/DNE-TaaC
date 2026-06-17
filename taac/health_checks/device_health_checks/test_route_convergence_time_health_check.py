# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import unittest
from unittest.mock import AsyncMock, MagicMock

from neteng.netcastle.logger import ConsoleFileLogger
from taac.constants import TestDevice
from taac.health_checks.device_health_checks.route_convergence_time_health_check import (
    RouteConvergenceTimeHealthCheck,
)
from taac.health_check.health_check import types as hc_types


class TestRouteConvergenceTimeHealthCheck(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        """Set up test fixtures."""
        self.logger = MagicMock(spec=ConsoleFileLogger)
        self.mock_ixia = MagicMock()
        self.health_check = RouteConvergenceTimeHealthCheck(
            logger=self.logger, ixia=self.mock_ixia
        )
        self.health_check.driver = AsyncMock()

        self.device = MagicMock(spec=TestDevice)
        self.device.name = "rtsw002.l1003.c084.ash6"

        self.health_check_input = hc_types.BaseHealthCheckIn()

    # =========================================================================
    # Tests for _parse_start_time_to_hhmmss
    # =========================================================================
    def test_parse_start_time_hhmmss_format(self):
        """Test parsing HH:MM:SS format."""
        result = self.health_check._parse_start_time_to_hhmmss("14:30:45")
        self.assertEqual(result, "14:30:45")

    def test_parse_start_time_hhmmss_with_microseconds(self):
        """Test parsing HH:MM:SS.microseconds format."""
        result = self.health_check._parse_start_time_to_hhmmss("14:30:45.123456")
        self.assertEqual(result, "14:30:45")

    def test_parse_start_time_hhmm_format(self):
        """Test parsing HH:MM format."""
        result = self.health_check._parse_start_time_to_hhmmss("14:30")
        self.assertEqual(result, "14:30:00")

    def test_parse_start_time_none(self):
        """Test parsing None input returns None."""
        result = self.health_check._parse_start_time_to_hhmmss(None)
        self.assertIsNone(result)

    def test_parse_start_time_epoch_int(self):
        """Test parsing epoch seconds as int."""
        result = self.health_check._parse_start_time_to_hhmmss(0)
        self.assertIsNotNone(result)
        # Epoch 0 should produce a valid HH:MM:SS string
        self.assertRegex(result, r"\d{1,2}:\d{2}:\d{2}")

    def test_parse_start_time_epoch_float(self):
        """Test parsing epoch seconds as float."""
        result = self.health_check._parse_start_time_to_hhmmss(1700000000.0)
        self.assertIsNotNone(result)
        self.assertRegex(result, r"\d{1,2}:\d{2}:\d{2}")

    def test_parse_start_time_epoch_string(self):
        """Test parsing epoch seconds as string."""
        result = self.health_check._parse_start_time_to_hhmmss("1700000000")
        self.assertIsNotNone(result)
        self.assertRegex(result, r"\d{1,2}:\d{2}:\d{2}")

    # =========================================================================
    # Tests for _parse_awk_output
    # =========================================================================
    def test_parse_awk_output_valid_metrics(self):
        """Test parsing valid METRICS output."""
        output = "METRICS 1000 0 5 12.345678 14:30:00.000000 14:30:12.345678"
        result = self.health_check._parse_awk_output(output, "ADD")
        self.assertIsNotNone(result)
        self.assertEqual(result.total_routes_added, 1000)
        self.assertEqual(result.total_routes_deleted, 0)
        self.assertEqual(result.num_batches, 5)
        self.assertAlmostEqual(result.total_state_update_time_sec, 12.345678, places=4)
        self.assertEqual(result.first_batch_time, "14:30:00.000000")
        self.assertEqual(result.last_batch_time, "14:30:12.345678")

    def test_parse_awk_output_none_result(self):
        """Test parsing NONE output."""
        result = self.health_check._parse_awk_output("NONE", "ADD")
        self.assertIsNone(result)

    def test_parse_awk_output_empty_string(self):
        """Test parsing empty output."""
        result = self.health_check._parse_awk_output("", "DELETE")
        self.assertIsNone(result)

    def test_parse_awk_output_delete_metrics(self):
        """Test parsing valid METRICS output for DELETE operation."""
        output = "METRICS 0 5000 10 8.500000 10:00:00.000000 10:00:08.500000"
        result = self.health_check._parse_awk_output(output, "DELETE")
        self.assertIsNotNone(result)
        self.assertEqual(result.total_routes_added, 0)
        self.assertEqual(result.total_routes_deleted, 5000)
        self.assertEqual(result.num_batches, 10)
        self.assertAlmostEqual(result.total_state_update_time_sec, 8.5, places=4)

    # =========================================================================
    # Tests for _run (async)
    # =========================================================================
    async def test_run_ixia_not_available(self):
        """Test _run returns ERROR when IXIA client is not available."""
        # Setup: health check without ixia
        health_check = RouteConvergenceTimeHealthCheck(logger=self.logger, ixia=None)
        health_check.driver = AsyncMock()

        # Execute
        result = await health_check._run(
            self.device,
            self.health_check_input,
            {"network_group_regex": ".*CONTIGUOUS.*"},
        )

        # Assert
        self.assertEqual(result.status, hc_types.HealthCheckStatus.ERROR)
        self.assertIn("IXIA client not available", result.message)

    async def test_run_missing_network_group_regex(self):
        """Test _run returns ERROR when network_group_regex is missing."""
        result = await self.health_check._run(
            self.device,
            self.health_check_input,
            {},
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.ERROR)
        self.assertIn("network_group_regex", result.message)

    async def test_run_all_iterations_pass(self):
        """Test _run returns PASS when all DELETE/ADD iterations succeed."""
        # Setup: mock driver returns valid time and metrics
        # With DELETE→ADD order, 1 iteration needs:
        # Iter 1 DELETE: capture start time + awk output
        # Iter 1 ADD: capture start time + awk output
        self.health_check.driver.async_run_cmd_on_shell = AsyncMock(
            side_effect=[
                # Iter 1 DELETE - capture start time
                "14:30:00.000000",
                # Iter 1 DELETE - awk output
                "METRICS 0 1000 5 5.000000 14:30:00 14:30:05",
                # Iter 1 ADD - capture start time
                "14:30:10.000000",
                # Iter 1 ADD - awk output
                "METRICS 1000 0 5 8.000000 14:30:10 14:30:18",
            ]
        )

        result = await self.health_check._run(
            self.device,
            self.health_check_input,
            {
                "network_group_regex": ".*CONTIGUOUS.*",
                "iterations": 1,
                "time_threshold": 35,
                "wait_time_seconds": 0,
            },
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("PASSED", result.message)

    async def test_run_fails_when_threshold_exceeded(self):
        """Test _run returns FAIL when convergence time exceeds threshold."""
        self.health_check.driver.async_run_cmd_on_shell = AsyncMock(
            side_effect=[
                # Iter 1 DELETE - capture start time
                "14:30:00.000000",
                # Iter 1 DELETE - awk output showing time > threshold
                "METRICS 0 1000 5 50.000000 14:30:00 14:30:50",
            ]
        )

        result = await self.health_check._run(
            self.device,
            self.health_check_input,
            {
                "network_group_regex": ".*CONTIGUOUS.*",
                "iterations": 1,
                "time_threshold": 35,
                "wait_time_seconds": 0,
            },
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("FAILED", result.message)

    # =========================================================================
    # Tests for _run_single_operation (async)
    # =========================================================================
    async def test_run_single_operation_add_pass(self):
        """Test _run_single_operation for successful ADD."""
        self.health_check.driver.async_run_cmd_on_shell = AsyncMock(
            side_effect=[
                # Capture start time
                "14:30:00.000000",
                # AWK output
                "METRICS 1000 0 5 10.000000 14:30:00 14:30:10",
            ]
        )

        result = await self.health_check._run_single_operation(
            operation_type="ADD",
            network_group_regex=".*CONTIGUOUS.*",
            time_threshold=35,
            wait_time_seconds=0,
            log_file="/var/facebook/logs/wedge_agent.log",
            start_time_file="/tmp/toggle_start_time",
            iteration=1,
        )

        self.assertTrue(result["passed"])
        self.assertEqual(result["time"], 10.0)
        self.assertEqual(result["routes"], 1000)

    async def test_run_single_operation_delete_pass(self):
        """Test _run_single_operation for successful DELETE."""
        self.health_check.driver.async_run_cmd_on_shell = AsyncMock(
            side_effect=[
                # Capture start time
                "14:30:00.000000",
                # AWK output
                "METRICS 0 5000 10 8.500000 14:30:00 14:30:08",
            ]
        )

        result = await self.health_check._run_single_operation(
            operation_type="DELETE",
            network_group_regex=".*CONTIGUOUS.*",
            time_threshold=35,
            wait_time_seconds=0,
            log_file="/var/facebook/logs/wedge_agent.log",
            start_time_file="/tmp/toggle_start_time",
            iteration=1,
        )

        self.assertTrue(result["passed"])
        self.assertEqual(result["time"], 8.5)
        self.assertEqual(result["routes"], 5000)

    async def test_run_single_operation_toggle_failure(self):
        """Test _run_single_operation when IXIA toggle fails."""
        self.health_check.driver.async_run_cmd_on_shell = AsyncMock(
            return_value="14:30:00.000000"
        )
        self.mock_ixia.activate_deactivate_bgp_prefix.side_effect = Exception(
            "IXIA connection lost"
        )

        result = await self.health_check._run_single_operation(
            operation_type="ADD",
            network_group_regex=".*CONTIGUOUS.*",
            time_threshold=35,
            wait_time_seconds=0,
            log_file="/var/facebook/logs/wedge_agent.log",
            start_time_file="/tmp/toggle_start_time",
            iteration=1,
        )

        self.assertFalse(result["passed"])
        self.assertIn("Toggle failed", result["message"])

    async def test_run_single_operation_no_start_time(self):
        """Test _run_single_operation when start time capture fails."""
        self.health_check.driver.async_run_cmd_on_shell = AsyncMock(return_value="")

        result = await self.health_check._run_single_operation(
            operation_type="ADD",
            network_group_regex=".*CONTIGUOUS.*",
            time_threshold=35,
            wait_time_seconds=0,
            log_file="/var/facebook/logs/wedge_agent.log",
            start_time_file="/tmp/toggle_start_time",
            iteration=1,
        )

        self.assertFalse(result["passed"])
        self.assertIn("start time", result["message"])

    async def test_run_single_operation_ixia_not_available(self):
        """Test _run_single_operation when IXIA is None."""
        health_check = RouteConvergenceTimeHealthCheck(logger=self.logger, ixia=None)
        health_check.driver = AsyncMock()
        health_check.driver.async_run_cmd_on_shell = AsyncMock(
            return_value="14:30:00.000000"
        )

        result = await health_check._run_single_operation(
            operation_type="ADD",
            network_group_regex=".*CONTIGUOUS.*",
            time_threshold=35,
            wait_time_seconds=0,
            log_file="/var/facebook/logs/wedge_agent.log",
            start_time_file="/tmp/toggle_start_time",
            iteration=1,
        )

        self.assertFalse(result["passed"])
        self.assertIn("IXIA client not available", result["message"])

    async def test_run_single_operation_no_operations_in_logs(self):
        """Test _run_single_operation when no operations are found in logs."""
        self.health_check.driver.async_run_cmd_on_shell = AsyncMock(
            side_effect=[
                # Capture start time
                "14:30:00.000000",
                # AWK output - no operations found
                "NONE",
            ]
        )

        result = await self.health_check._run_single_operation(
            operation_type="ADD",
            network_group_regex=".*CONTIGUOUS.*",
            time_threshold=35,
            wait_time_seconds=0,
            log_file="/var/facebook/logs/wedge_agent.log",
            start_time_file="/tmp/toggle_start_time",
            iteration=1,
        )

        self.assertFalse(result["passed"])
        self.assertIn("No ADD operations found", result["message"])
