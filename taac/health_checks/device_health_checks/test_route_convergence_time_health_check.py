# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from neteng.netcastle.logger import ConsoleFileLogger
from taac.constants import TestDevice
from taac.health_checks.device_health_checks.route_convergence_time_health_check import (
    RouteConvergenceMetrics,
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
        self.assertEqual(result, "14:30:45.123456")

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
        # With DELETE→ADD order, 1 iteration needs per operation:
        # capture start time (stamp + HH:MM:SS.us) + list archives + awk output
        self.health_check.driver.async_run_cmd_on_shell = AsyncMock(
            side_effect=[
                # Iter 1 DELETE - capture start time
                "202601011430 14:30:00.000000",
                # Iter 1 DELETE - list archives (none rotated)
                "",
                # Iter 1 DELETE - awk output
                "METRICS 0 1000 5 5.000000 14:30:00 14:30:05",
                # Iter 1 ADD - capture start time
                "202601011430 14:30:10.000000",
                # Iter 1 ADD - list archives (none rotated)
                "",
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
                "202601011430 14:30:00.000000",
                # Iter 1 DELETE - list archives (none rotated)
                "",
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
                "202601011430 14:30:00.000000",
                # List archives (none rotated)
                "",
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
                "202601011430 14:30:00.000000",
                # List archives (none rotated)
                "",
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
        self.assertEqual(result["time"], 8.0)
        self.assertEqual(result["routes"], 5000)

    async def test_run_single_operation_toggle_failure(self):
        """Test _run_single_operation when IXIA toggle fails."""
        self.health_check.driver.async_run_cmd_on_shell = AsyncMock(
            return_value="202601011430 14:30:00.000000"
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
            return_value="202601011430 14:30:00.000000"
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
                "202601011430 14:30:00.000000",
                # List archives (none rotated)
                "",
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

    async def test_run_single_operation_polls_until_expected_routes_arrive(self):
        """A delayed complete log sample should satisfy the original SLA."""
        self.health_check.driver.async_run_cmd_on_shell = AsyncMock(
            side_effect=[
                "202601011430 14:30:00.000000",
                "",
                "METRICS 500 0 1 0.000000 14:30:05.000000 14:30:05.000000",
                "",
                "METRICS 1000 0 2 8.000000 14:30:05.000000 14:30:08.000000",
            ]
        )

        with (
            patch(
                "neteng.test_infra.dne.taac.health_checks.device_health_checks."
                "route_convergence_time_health_check.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            patch(
                "neteng.test_infra.dne.taac.health_checks.device_health_checks."
                "route_convergence_time_health_check.time.monotonic",
                return_value=0.0,
            ),
        ):
            result = await self.health_check._run_single_operation(
                operation_type="ADD",
                network_group_regex=".*CONTIGUOUS.*",
                time_threshold=35,
                wait_time_seconds=0,
                log_file="/var/facebook/logs/wedge_agent.log",
                start_time_file="/tmp/toggle_start_time",
                iteration=1,
                expected_route_count=1000,
                observation_timeout_seconds=10,
                observation_poll_interval_seconds=1,
            )

        self.assertTrue(result["passed"])
        self.assertEqual(result["routes"], 1000)

    async def test_run_single_operation_fails_on_incomplete_route_count(self):
        """A partial route sample must fail when observation time expires."""
        self.health_check.driver.async_run_cmd_on_shell = AsyncMock(
            side_effect=[
                "202601011430 14:30:00.000000",
                "",
                "METRICS 500 0 1 0.000000 14:30:05.000000 14:30:05.000000",
                "",
                "METRICS 500 0 1 0.000000 14:30:05.000000 14:30:05.000000",
            ]
        )

        with (
            patch(
                "neteng.test_infra.dne.taac.health_checks.device_health_checks."
                "route_convergence_time_health_check.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            patch(
                "neteng.test_infra.dne.taac.health_checks.device_health_checks."
                "route_convergence_time_health_check.time.monotonic",
                side_effect=[0.0, 0.0, 11.0],
            ),
        ):
            result = await self.health_check._run_single_operation(
                operation_type="ADD",
                network_group_regex=".*CONTIGUOUS.*",
                time_threshold=35,
                wait_time_seconds=0,
                log_file="/var/facebook/logs/wedge_agent.log",
                start_time_file="/tmp/toggle_start_time",
                iteration=1,
                expected_route_count=1000,
                observation_timeout_seconds=10,
                observation_poll_interval_seconds=1,
            )

        self.assertFalse(result["passed"])
        self.assertIn("observed 500/1000 routes", result["message"])

    async def test_run_single_operation_uses_toggle_to_completion_time(self):
        """A late single batch must not appear as zero-second convergence."""
        self.health_check.driver.async_run_cmd_on_shell = AsyncMock(
            side_effect=[
                "202601011430 14:30:00.000000",
                "",
                "METRICS 1000 0 1 0.000000 14:30:40.000000 14:30:40.000000",
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
            expected_route_count=1000,
            observation_timeout_seconds=0,
        )

        self.assertFalse(result["passed"])
        self.assertEqual(result["time"], 40.0)
        self.assertIn("40.000s > 35s", result["message"])

    async def test_run_logs_each_failed_operation(self):
        """A failed operation should be visible before the aggregate result."""
        self.health_check._run_single_operation = AsyncMock(
            side_effect=[
                {"passed": True, "time": 1.0, "routes": 1000},
                {"passed": False, "message": "No ADD operations found in logs"},
            ]
        )

        result = await self.health_check._run(
            self.device,
            self.health_check_input,
            {
                "network_group_regex": ".*CONTIGUOUS.*",
                "iterations": 1,
                "wait_time_seconds": 0,
            },
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.logger.error.assert_called_once_with(
            "[Iter 1] ADD FAILED: No ADD operations found in logs"
        )

    # =========================================================================
    # Tests for _capture_start_time (async)
    # =========================================================================
    async def test_capture_start_time_parses_stamp_and_hhmmss(self):
        """Test _capture_start_time splits the stamp and HH:MM:SS parts."""
        self.health_check.driver.async_run_cmd_on_shell = AsyncMock(
            return_value="202607170952 09:52:15.879279\n"
        )

        hhmmss, stamp = await self.health_check._capture_start_time(
            "/tmp/toggle_start_time"
        )

        self.assertEqual(hhmmss, "09:52:15.879279")
        self.assertEqual(stamp, "202607170952")

    async def test_capture_start_time_malformed_returns_none(self):
        """Test _capture_start_time returns (None, None) on malformed output."""
        # No space between stamp and time -> time part is empty -> total failure.
        self.health_check.driver.async_run_cmd_on_shell = AsyncMock(
            return_value="14:30:00.000000"
        )

        hhmmss, stamp = await self.health_check._capture_start_time(
            "/tmp/toggle_start_time"
        )

        self.assertIsNone(hhmmss)
        self.assertIsNone(stamp)

    async def test_capture_start_time_empty_returns_none(self):
        """Test _capture_start_time returns (None, None) on empty output."""
        self.health_check.driver.async_run_cmd_on_shell = AsyncMock(return_value="")

        hhmmss, stamp = await self.health_check._capture_start_time(
            "/tmp/toggle_start_time"
        )

        self.assertIsNone(hhmmss)
        self.assertIsNone(stamp)

    # =========================================================================
    # Tests for _find_log_files (async)
    # =========================================================================
    async def test_find_log_files_no_stamp_returns_live_log_only(self):
        """Test _find_log_files skips archive discovery when start_stamp is None."""
        self.health_check.driver.async_run_cmd_on_shell = AsyncMock()

        files = await self.health_check._find_log_files(
            None, "/var/facebook/logs/wedge_agent.log"
        )

        self.assertEqual(files, ["/var/facebook/logs/wedge_agent.log"])
        self.health_check.driver.async_run_cmd_on_shell.assert_not_called()

    async def test_find_log_files_no_archives_returns_live_log_only(self):
        """Test _find_log_files returns just the live log when no archives match."""
        self.health_check.driver.async_run_cmd_on_shell = AsyncMock(return_value="")

        files = await self.health_check._find_log_files(
            "202607170952", "/var/facebook/logs/wedge_agent.log"
        )

        self.assertEqual(files, ["/var/facebook/logs/wedge_agent.log"])

    async def test_find_log_files_selects_covering_archives_in_order(self):
        """Test _find_log_files selects covering archives, sorted, live log last."""
        archive_dir = "/var/facebook/logs/fboss/archive"
        # Two archives whose stamp >= start (relevant), one older (excluded), and
        # a snapshots log that must never match.
        self.health_check.driver.async_run_cmd_on_shell = AsyncMock(
            return_value="\n".join(
                [
                    f"{archive_dir}/wedge_agent.log-202607170955.gz",
                    f"{archive_dir}/wedge_agent.log-202607170953.gz",
                    f"{archive_dir}/wedge_agent.log-202607170948.gz",
                    f"{archive_dir}/wedge_agent_snapshots.log-202607170955.gz",
                ]
            )
        )

        files = await self.health_check._find_log_files(
            "202607170952", "/var/facebook/logs/wedge_agent.log", archive_dir
        )

        self.assertEqual(
            files,
            [
                f"{archive_dir}/wedge_agent.log-202607170953.gz",
                f"{archive_dir}/wedge_agent.log-202607170955.gz",
                "/var/facebook/logs/wedge_agent.log",
            ],
        )

    async def test_find_log_files_listing_failure_falls_back(self):
        """Test _find_log_files falls back to the live log if listing fails."""
        self.health_check.driver.async_run_cmd_on_shell = AsyncMock(
            side_effect=Exception("ssh error")
        )

        files = await self.health_check._find_log_files(
            "202607170952", "/var/facebook/logs/wedge_agent.log"
        )

        self.assertEqual(files, ["/var/facebook/logs/wedge_agent.log"])

    # =========================================================================
    # Tests for _hhmmss_to_sec
    # =========================================================================
    def test_hhmmss_to_sec(self):
        """Test _hhmmss_to_sec converts timestamps (with/without fraction)."""
        self.assertAlmostEqual(
            RouteConvergenceTimeHealthCheck._hhmmss_to_sec("01:02:03"), 3723.0
        )
        self.assertAlmostEqual(
            RouteConvergenceTimeHealthCheck._hhmmss_to_sec("00:00:08.500000"), 8.5
        )

    # =========================================================================
    # Tests for _merge_metrics
    # =========================================================================
    def test_merge_metrics_sums_and_widens_window(self):
        """Test _merge_metrics sums counts and spans base-first to extra-last."""
        base = RouteConvergenceMetrics(
            total_routes_deleted=1000,
            num_batches=3,
            total_state_update_time_sec=0.2,
            first_batch_time="10:00:00.100000",
            last_batch_time="10:00:00.300000",
        )
        extra = RouteConvergenceMetrics(
            total_routes_deleted=500,
            num_batches=2,
            total_state_update_time_sec=0.1,
            first_batch_time="10:00:05.000000",
            last_batch_time="10:00:05.400000",
        )

        merged = self.health_check._merge_metrics(base, extra)

        self.assertEqual(merged.total_routes_deleted, 1500)
        self.assertEqual(merged.num_batches, 5)
        self.assertEqual(merged.first_batch_time, "10:00:00.100000")
        self.assertEqual(merged.last_batch_time, "10:00:05.400000")
        # Wall-clock is recomputed from the widened window, not summed.
        self.assertAlmostEqual(merged.total_state_update_time_sec, 5.3, places=4)

    def test_merge_metrics_midnight_straddle(self):
        """Test _merge_metrics stays positive when the window crosses midnight.

        base (earlier file) ends at 23:59:50 and extra (later file) starts at
        00:00:05, so a lexicographic min/max would report a ~24h wall-clock. The
        file-ordered window must instead yield the true ~15s duration.
        """
        base = RouteConvergenceMetrics(
            total_routes_deleted=100,
            num_batches=1,
            first_batch_time="23:59:50.000000",
            last_batch_time="23:59:50.000000",
        )
        extra = RouteConvergenceMetrics(
            total_routes_deleted=200,
            num_batches=1,
            first_batch_time="00:00:05.000000",
            last_batch_time="00:00:05.000000",
        )

        merged = self.health_check._merge_metrics(base, extra)

        self.assertEqual(merged.first_batch_time, "23:59:50.000000")
        self.assertEqual(merged.last_batch_time, "00:00:05.000000")
        self.assertAlmostEqual(merged.total_state_update_time_sec, 15.0, places=4)

    # =========================================================================
    # Tests for _get_route_convergence_metrics (async, multi-file merge)
    # =========================================================================
    async def test_get_route_convergence_metrics_merges_across_files(self):
        """Test metrics from an archive and the live log are merged."""
        self.health_check.driver.async_run_cmd_on_shell = AsyncMock(
            side_effect=[
                # Archive scan
                "METRICS 0 1000 3 0.200000 10:00:00.100000 10:00:00.300000",
                # Live log scan
                "METRICS 0 500 2 0.100000 10:00:05.000000 10:00:05.400000",
            ]
        )

        metrics = await self.health_check._get_route_convergence_metrics(
            log_files=[
                "/var/facebook/logs/fboss/archive/wedge_agent.log-202601011000.gz",
                "/var/facebook/logs/wedge_agent.log",
            ],
            operation_type="DELETE",
            start_time_str="10:00:00",
            time_threshold=35,
        )

        self.assertIsNotNone(metrics)
        self.assertEqual(metrics.total_routes_deleted, 1500)
        self.assertEqual(metrics.num_batches, 5)
        self.assertAlmostEqual(metrics.total_state_update_time_sec, 5.3, places=4)

    async def test_get_route_convergence_metrics_none_when_all_empty(self):
        """Test None is returned when no file yields operations."""
        self.health_check.driver.async_run_cmd_on_shell = AsyncMock(
            side_effect=["NONE", ""]
        )

        metrics = await self.health_check._get_route_convergence_metrics(
            log_files=[
                "/var/facebook/logs/fboss/archive/wedge_agent.log-202601011000.gz",
                "/var/facebook/logs/wedge_agent.log",
            ],
            operation_type="ADD",
            start_time_str="10:00:00",
            time_threshold=35,
        )

        self.assertIsNone(metrics)
