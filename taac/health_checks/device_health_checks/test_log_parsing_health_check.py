# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""Unit tests for LogParsingHealthCheck (FBOSS `_run` path)."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from neteng.netcastle.logger import ConsoleFileLogger
from taac.constants import TestDevice
from taac.health_checks.device_health_checks import (
    log_parsing_health_check as log_parsing_health_check_module,
)
from taac.health_checks.device_health_checks.log_parsing_health_check import (
    LogParsingHealthCheck,
)
from taac.health_check.health_check import types as hc_types


_SAMPLE_COOP_CONFIG = """\
{
    "agent": {
        "flags": {
            "cleanup_probed_kernel_data": "true",
            "another_flag": "false"
        }
    }
}
"""


class LogParsingHealthCheckTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.logger = MagicMock(spec=ConsoleFileLogger)
        self.health_check = LogParsingHealthCheck(logger=self.logger)
        self.health_check.driver = AsyncMock()
        self.health_check.driver.async_read_file = AsyncMock(
            return_value=_SAMPLE_COOP_CONFIG
        )
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "test-host"
        self.input = hc_types.BaseHealthCheckIn()

    async def test_include_regex_match_returns_pass_with_count_message(self):
        """include_regex with at least one match returns PASS and reports the count."""
        check_params = {
            "log_file_path": "/etc/coop/agent/current",
            "include_regex": r'"cleanup_probed_kernel_data":\s*"true"',
        }
        result = await self.health_check._run(self.device, self.input, check_params)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("1 line(s) matching include regex", result.message)
        self.assertIn("cleanup_probed_kernel_data", result.message)

    async def test_include_regex_no_match_returns_fail(self):
        """include_regex with no matching lines returns FAIL with regex echoed back."""
        never_match = "this_string_should_never_match_xyz123"
        check_params = {
            "log_file_path": "/etc/coop/agent/current",
            "include_regex": never_match,
        }
        result = await self.health_check._run(self.device, self.input, check_params)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn(never_match, result.message)

    async def test_exclude_regex_no_match_returns_pass_with_exclude_regex(self):
        """exclude_regex with no matching lines returns PASS and reports the regex."""
        exclude = "this_string_should_never_match_xyz123"
        check_params = {
            "log_file_path": "/etc/coop/agent/current",
            "exclude_regex": exclude,
        }
        result = await self.health_check._run(self.device, self.input, check_params)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn(exclude, result.message)
        self.assertNotIn("Found", result.message)

    async def test_exclude_regex_match_returns_fail(self):
        """exclude_regex with at least one match returns FAIL with the lines."""
        check_params = {
            "log_file_path": "/etc/coop/agent/current",
            "exclude_regex": r'"cleanup_probed_kernel_data":\s*"true"',
        }
        result = await self.health_check._run(self.device, self.input, check_params)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("matching criteria", result.message)

    async def test_both_regexes_provided_raises(self):
        """Providing both include_regex and exclude_regex is an assertion error."""
        check_params = {
            "log_file_path": "/etc/coop/agent/current",
            "include_regex": "foo",
            "exclude_regex": "bar",
        }
        with self.assertRaises(AssertionError):
            await self.health_check._run(self.device, self.input, check_params)

    async def test_neither_regex_provided_raises(self):
        """Providing neither include_regex nor exclude_regex is an assertion error."""
        check_params = {"log_file_path": "/etc/coop/agent/current"}
        with self.assertRaises(AssertionError):
            await self.health_check._run(self.device, self.input, check_params)

    def _arista_params(self, **overrides):
        params = {
            "agent_name": "Bgp",
            "exclude_regex": "Memory Limit Reached",
        }
        params.update(overrides)
        return params

    async def test_arista_uses_archive_when_live_log_rotated(self):
        self.health_check.driver.async_read_file.side_effect = FileNotFoundError
        with (
            patch.object(
                log_parsing_health_check_module.arista_utils,
                "get_daemon_pid",
                new=AsyncMock(return_value="26775"),
            ),
            patch.object(
                log_parsing_health_check_module.arista_utils,
                "get_archived_agent_logs",
                new=AsyncMock(return_value="healthy archived BGP log"),
            ) as archived_logs,
        ):
            result = await self.health_check._run_arista(
                self.device, self.input, self._arista_params()
            )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        archived_logs.assert_awaited_once_with(self.health_check.driver, "Bgp", "26775")

    async def test_arista_combines_live_and_archived_logs(self):
        self.health_check.driver.async_read_file.return_value = "healthy live BGP log"
        with (
            patch.object(
                log_parsing_health_check_module.arista_utils,
                "get_daemon_pid",
                new=AsyncMock(return_value="26775"),
            ),
            patch.object(
                log_parsing_health_check_module.arista_utils,
                "get_archived_agent_logs",
                new=AsyncMock(return_value="Memory Limit Reached in archive"),
            ),
        ):
            result = await self.health_check._run_arista(
                self.device, self.input, self._arista_params()
            )

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("exclude regex", result.message)

    async def test_arista_archive_error_is_not_hidden_by_live_log(self):
        self.health_check.driver.async_read_file.return_value = "healthy live BGP log"
        with (
            patch.object(
                log_parsing_health_check_module.arista_utils,
                "get_daemon_pid",
                new=AsyncMock(return_value="26775"),
            ),
            patch.object(
                log_parsing_health_check_module.arista_utils,
                "get_archived_agent_logs",
                new=AsyncMock(side_effect=RuntimeError("archive transport failed")),
            ),
        ):
            result = await self.health_check._run_arista(
                self.device, self.input, self._arista_params()
            )

        self.assertEqual(hc_types.HealthCheckStatus.ERROR, result.status)
        self.assertIn("archive transport failed", result.message)

    async def test_arista_archive_error_is_not_hidden_when_live_log_missing(self):
        self.health_check.driver.async_read_file.side_effect = FileNotFoundError
        with (
            patch.object(
                log_parsing_health_check_module.arista_utils,
                "get_daemon_pid",
                new=AsyncMock(return_value="26775"),
            ),
            patch.object(
                log_parsing_health_check_module.arista_utils,
                "get_archived_agent_logs",
                new=AsyncMock(side_effect=RuntimeError("archive read failed")),
            ),
        ):
            result = await self.health_check._run_arista(
                self.device, self.input, self._arista_params()
            )

        self.assertEqual(hc_types.HealthCheckStatus.ERROR, result.status)
        self.assertIn("archive read failed", result.message)

    async def test_arista_errors_when_live_and_archived_logs_are_missing(self):
        self.health_check.driver.async_read_file.side_effect = FileNotFoundError
        with (
            patch.object(
                log_parsing_health_check_module.arista_utils,
                "get_daemon_pid",
                new=AsyncMock(return_value="26775"),
            ),
            patch.object(
                log_parsing_health_check_module.arista_utils,
                "get_archived_agent_logs",
                new=AsyncMock(return_value=""),
            ),
        ):
            result = await self.health_check._run_arista(
                self.device, self.input, self._arista_params()
            )

        self.assertEqual(hc_types.HealthCheckStatus.ERROR, result.status)
        self.assertIn("No live or archived Bgp logs", result.message)

    async def test_arista_rejects_inverted_time_window(self):
        get_pid = AsyncMock(return_value="26775")
        with patch.object(
            log_parsing_health_check_module.arista_utils,
            "get_daemon_pid",
            new=get_pid,
        ):
            result = await self.health_check._run_arista(
                self.device,
                self.input,
                self._arista_params(start_time=200, end_time=100),
            )

        self.assertEqual(hc_types.HealthCheckStatus.ERROR, result.status)
        self.assertIn("must not be earlier", result.message)
        get_pid.assert_not_awaited()
