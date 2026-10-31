# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import gzip
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from taac.utils.oss_taac_lib_utils import ConsoleFileLogger
from taac.constants import TestDevice
from taac.health_checks.device_health_checks.route_convergence_time_health_check import (
    RouteConvergenceMetrics,
    RouteConvergenceTimeHealthCheck,
)
from taac.health_check.health_check import types as hc_types


# Internal and OSS trees import this module under different package roots.
_MODULE = RouteConvergenceTimeHealthCheck.__module__


class TestRouteConvergenceTimeHealthCheck(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        """Set up test fixtures."""
        self.logger = MagicMock(spec=ConsoleFileLogger)
        self.mock_ixia = MagicMock()
        self.health_check = RouteConvergenceTimeHealthCheck(
            logger=self.logger, ixia=self.mock_ixia
        )
        self.health_check.driver = AsyncMock()
        self.health_check.driver.async_get_log_source_command = AsyncMock(
            side_effect=lambda path, **_kwargs: f"zcat -f {path}"
        )

        self.device = MagicMock(spec=TestDevice)
        self.device.name = "rtsw002.l1003.c084.ash6"

        self.health_check_input = hc_types.BaseHealthCheckIn()

    async def test_resolve_default_log_file_oss(self):
        self.health_check.driver.async_run_cmd_on_shell.return_value = (
            "/var/facebook/logs/fboss/fboss_sw_agent.log\n"
        )
        path = await self.health_check._resolve_log_file(None)
        self.assertEqual(path, "/var/facebook/logs/fboss/fboss_sw_agent.log")
        command = self.health_check.driver.async_run_cmd_on_shell.call_args.args[0]
        self.assertIn("test -r", command)
        self.assertIn("/var/facebook/logs/wedge_agent.log", command)
        self.assertIn(path, command)

    async def test_resolve_explicit_log_file(self):
        self.assertEqual(
            await self.health_check._resolve_log_file("/custom/agent.log"),
            "/custom/agent.log",
        )
        self.health_check.driver.async_run_cmd_on_shell.assert_not_called()

    async def test_missing_default_log_fails_before_toggling(self):
        self.health_check.driver.async_run_cmd_on_shell.return_value = ""
        result = await self.health_check._run(
            self.device,
            self.health_check_input,
            {"network_group_regex": ".*CONTIGUOUS.*"},
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.ERROR)
        self.assertIn("readable agent log", result.message)
        self.mock_ixia.activate_deactivate_bgp_prefix.assert_not_called()

    async def test_find_oss_archive_logs(self):
        archive = "/var/facebook/logs/fboss/archive/fboss_sw_agent.log-202609161235.gz"
        self.health_check.driver.async_run_cmd_on_shell.return_value = archive
        live = "/var/facebook/logs/fboss/fboss_sw_agent.log"
        self.assertEqual(
            await self.health_check._find_log_files("202609161234", live),
            [archive, live],
        )
        command = self.health_check.driver.async_run_cmd_on_shell.call_args.args[0]
        self.assertIn("fboss_sw_agent.log-*.gz", command)

    async def test_real_log_parser_filters_operation_date_and_fraction(self):
        cases = [
            ("202609162359 23:59:58.500000", [
                ("0915", "23:59:59.000000", 900),
                ("0916", "23:59:58.400000", 900),
                ("0916", "23:59:59.000000", 100),
                ("0917", "00:00:01.000000", 200),
            ]),
            ("202609161430 14:30:00.500000", [
                ("0915", "14:30:01.000000", 900),
                ("0916", "14:30:00.400000", 900),
                ("0916", "14:30:01.000000", 100),
                ("0916", "14:30:03.000000", 200),
            ]),
            ("202612312359 23:59:58.500000", [
                ("1230", "23:59:59.000000", 900),
                ("1231", "23:59:58.400000", 900),
                ("1231", "23:59:59.000000", 100),
                ("0101", "00:00:01.000000", 200),
            ]),
        ]
        for operation in ["ADD", "DELETE"]:
            for captured_start, records in cases:
                with (
                    self.subTest(operation=operation, start=captured_start),
                    tempfile.NamedTemporaryFile(mode="w") as log,
                ):
                    for day, clock, count in records:
                        added, deleted = (count, 0) if operation == "ADD" else (0, count)
                        log.write(
                            f"V{day} {clock} 123 RouteUpdateWrapper.cpp:139] "
                            f" Routes added: {added} Routes deleted: {deleted} "
                            "Duration 0 us \n"
                        )
                    log.flush()

                    async def run_command(command):
                        if command.startswith("date "):
                            return captured_start
                        if command.startswith("ls "):
                            return ""
                        return subprocess.run(
                            command, shell=True, check=True,
                            capture_output=True, text=True,
                        ).stdout

                    self.health_check.driver.async_run_cmd_on_shell.side_effect = run_command
                    result = await self.health_check._run_single_operation(
                        operation_type=operation,
                        network_group_regex=".*CONTIGUOUS.*",
                        time_threshold=35,
                        wait_time_seconds=0,
                        log_file=log.name,
                        start_time_file="/tmp/toggle_start_time",
                        iteration=1,
                    )
                    self.assertTrue(result["passed"])
                    self.assertEqual(result["routes"], 300)
                    # Measured from the captured toggle start to the last batch.
                    self.assertAlmostEqual(result["time"], 2.5)

    async def test_midnight_rotation_preserves_threshold_failure(self):
        for operation in ["ADD", "DELETE"]:
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as directory:
                live = Path(directory) / "fboss_sw_agent.log"
                archive = Path(directory) / "fboss_sw_agent.log-202609170000.gz"
                added, deleted = (100, 0) if operation == "ADD" else (0, 100)
                message = (
                    " 123 RouteUpdateWrapper.cpp:139] "
                    f" Routes added: {added} Routes deleted: {deleted} Duration 0 us \n"
                )
                with gzip.open(archive, "wt") as log:
                    log.write("V0916 23:59:50.000000" + message)
                live.write_text("V0917 00:00:40.000000" + message)

                async def run_command(command):
                    if command.startswith("date "):
                        return "202609162359 23:59:49.000000"
                    if command.startswith("ls "):
                        return str(archive)
                    return subprocess.run(
                        command, shell=True, check=True, capture_output=True, text=True
                    ).stdout

                self.health_check.driver.async_run_cmd_on_shell.side_effect = run_command
                result = await self.health_check._run_single_operation(
                    operation_type=operation,
                    network_group_regex=".*CONTIGUOUS.*",
                    time_threshold=35,
                    wait_time_seconds=0,
                    log_file=str(live),
                    start_time_file="/tmp/toggle_start_time",
                    iteration=1,
                    archive_dir=directory,
                )
                self.assertFalse(result["passed"])
                self.assertEqual(result["routes"], 200)
                # Toggle start 23:59:49 -> last batch 00:00:40.
                self.assertAlmostEqual(result["time"], 51.0)
                self.assertIn("> 35s", result["message"])

    async def test_programming_failures_prevent_partial_route_pass(self):
        batch = (
            "V0916 14:01:32.702458 270970 RouteUpdateWrapper.cpp:139] "
            " Routes added: 45109 Routes deleted: 0 Duration 0 us \n"
        )
        failure = (
            "V0916 14:01:33.341749 270970 ThriftHandler.cpp:900] "
            '[0x7fae800045b0] addUnicastRoutes thrift request failed in 563ms. '
            'params: clientName="BGPD",\n'
        )
        cases = [
            ("captured_partial_add", batch, failure, True, "ADD", False),
            ("sync_failure", batch, failure.replace("addUnicastRoutes", "syncFib"),
             True, "ADD", False),
            ("delete_failure_without_batches", "",
             failure.replace("addUnicastRoutes", "deleteUnicastRoutes"),
             True, "DELETE", False),
            ("archive_failure", batch, failure, True, "ADD", True),
            ("later_success_does_not_erase_failure", batch,
             failure + failure.replace("failed", "succeeded"), True, "ADD", False),
            ("other_client", batch, failure.replace('"BGPD"', '"OPENR"'),
             False, "ADD", False),
            ("unrelated_rpc", batch, failure.replace("addUnicastRoutes", "getRouteTable"),
             False, "ADD", False),
            ("nested_rpc_not_double_counted", batch,
             failure.replace("addUnicastRoutes", "addUnicastRoutesInVrf"),
             False, "ADD", False),
            ("previous_day", batch, failure.replace("V0916", "V0915"),
             False, "ADD", False),
            ("before_capture_same_second", batch,
             failure.replace("14:01:33.341749", "14:01:29.844286"),
             False, "ADD", False),
        ]
        for name, batches, events, rejected, operation, archived in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                live = Path(directory) / "fboss_sw_agent.log"
                archive = Path(directory) / "fboss_sw_agent.log-202609161402.gz"
                live.write_text(batches + ("" if archived else events))
                if archived:
                    with gzip.open(archive, "wt") as log:
                        log.write(events)

                async def run_command(command):
                    if command.startswith("date "):
                        return "202609161401 14:01:29.844287"
                    if command.startswith("ls "):
                        return str(archive) if archived else ""
                    return subprocess.run(
                        command, shell=True, check=True, capture_output=True, text=True
                    ).stdout

                self.health_check.driver.async_run_cmd_on_shell.side_effect = run_command
                result = await self.health_check._run_single_operation(
                    operation_type=operation,
                    network_group_regex=".*CONTIGUOUS.*",
                    time_threshold=60,
                    wait_time_seconds=0,
                    log_file=str(live),
                    start_time_file="/tmp/toggle_start_time",
                    iteration=1,
                    archive_dir=directory,
                )
                self.assertEqual(result["passed"], not rejected)
                if rejected:
                    self.assertIn("BGPD route programming failed", result["message"])
                    self.assertIn("14:01:33.341749", result["message"])
                else:
                    self.assertEqual(result["routes"], 45109)

    async def test_captured_rsw_route_batches(self):
        # Captured from a rotated fboss_sw_agent.log on an RSW DUT.
        # This bounded sample validates parsing, not a complete toggle window.
        captured = (
            "V0916 09:00:11.993492 110473 RouteUpdateWrapper.cpp:139]"
            "  Routes added: 500 Routes deleted: 0 Duration 0 us \n"
            "V0916 09:00:13.110069 110473 RouteUpdateWrapper.cpp:139]"
            "  Routes added: 1000 Routes deleted: 0 Duration 0 us \n"
            "V0916 09:00:14.082492 110473 RouteUpdateWrapper.cpp:139]"
            "  Routes added: 0 Routes deleted: 1000 Duration 0 us \n"
            "V0916 09:00:26.948840 110473 RouteUpdateWrapper.cpp:139]"
            "  Routes added: 500 Routes deleted: 0 Duration 0 us \n"
            "V0916 09:00:27.985219 110473 RouteUpdateWrapper.cpp:139]"
            "  Routes added: 500 Routes deleted: 0 Duration 0 us \n"
            "V0916 09:00:29.121992 110473 RouteUpdateWrapper.cpp:139]"
            "  Routes added: 1000 Routes deleted: 0 Duration 0 us \n"
            "V0916 09:00:30.184435 110473 RouteUpdateWrapper.cpp:139]"
            "  Routes added: 557 Routes deleted: 0 Duration 0 us \n"
            "V0916 09:00:42.007332 110473 RouteUpdateWrapper.cpp:139]"
            "  Routes added: 500 Routes deleted: 0 Duration 0 us \n"
        )
        with tempfile.NamedTemporaryFile(mode="w") as log:
            log.write(captured)
            log.flush()

            async def run_command(command):
                return subprocess.run(
                    command, shell=True, check=True, capture_output=True, text=True
                ).stdout

            self.health_check.driver.async_run_cmd_on_shell.side_effect = run_command
            metrics = await self.health_check._get_route_convergence_metrics(
                log_files=[log.name],
                operation_type="ADD",
                start_time_str="09:00:00",
                time_threshold=35,
            )
            self.assertIsNotNone(metrics)
            self.assertEqual(metrics.total_routes_added, 4557)
            self.assertEqual(metrics.total_routes_deleted, 1000)
            self.assertEqual(metrics.num_batches, 7)
            self.assertAlmostEqual(metrics.total_state_update_time_sec, 30.013840)

    async def test_real_log_parser_preserves_threshold_failure(self):
        # Actual RouteUpdateWrapper.cpp::printStats format, including durations.
        # Both operations must still fail if observed batches span >35 seconds.
        for operation, counts in [("ADD", (100, 0)), ("DELETE", (0, 100))]:
            with (
                self.subTest(operation=operation),
                tempfile.NamedTemporaryFile(mode="w") as log,
            ):
                for ts in ["14:30:01.000000", "14:30:41.500000"]:
                    log.write(
                        f"I0916 {ts} 123 RouteUpdateWrapper.cpp:139] "
                        f" Routes added: {counts[0]} Routes deleted: {counts[1]} "
                        "Duration 1000 us \n"
                    )
                log.flush()

                async def run_command(command):
                    if command.startswith("date "):
                        return "202609161430 14:30:00.000000"
                    if command.startswith("ls "):
                        return ""
                    return subprocess.run(
                        command, shell=True, check=True, capture_output=True, text=True
                    ).stdout

                self.health_check.driver.async_run_cmd_on_shell.side_effect = run_command
                result = await self.health_check._run_single_operation(
                    operation_type=operation,
                    network_group_regex=".*CONTIGUOUS.*",
                    time_threshold=35,
                    wait_time_seconds=0,
                    log_file=log.name,
                    start_time_file="/tmp/toggle_start_time",
                    iteration=1,
                )
                self.assertFalse(result["passed"])
                self.assertEqual(result["routes"], 200)
                # Toggle start 14:30:00 -> last batch 14:30:41.5.
                self.assertAlmostEqual(result["time"], 41.5)
                self.assertIn("> 35s", result["message"])

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
                "/var/facebook/logs/wedge_agent.log",
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
                "/var/facebook/logs/wedge_agent.log",
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
                f"{_MODULE}.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            patch(
                f"{_MODULE}.time.monotonic",
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
                f"{_MODULE}.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            patch(
                f"{_MODULE}.time.monotonic",
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
                "log_file": "/var/facebook/logs/wedge_agent.log",
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
