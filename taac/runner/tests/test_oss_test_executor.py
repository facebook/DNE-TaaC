#!/usr/bin/env python3
# pyre-unsafe

"""
Tests for OSSTestExecutor — validates per-playbook execution and exception
handling. execute_playbook() is an async coroutine driven from the same
event loop as setUp/tearDown, so these tests use IsolatedAsyncioTestCase
and async mocks for run_tests to match the production call shape.
"""

import unittest
from unittest import mock

from taac.constants import TestCaseFailure
from taac.runner.oss_exceptions import (
    OSSConfigError,
    OSSTestbedError,
    OSSTransientError,
)
from taac.runner.oss_test_executor import OSSTestExecutor
from taac.runner.oss_test_status import OSSTestStatus


class TestOSSTestExecutor(unittest.IsolatedAsyncioTestCase):
    """Test OSSTestExecutor exception handling and result creation."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_runner = mock.MagicMock()
        self.mock_logger = mock.MagicMock()
        self.executor = OSSTestExecutor(
            taac_runner=self.mock_runner,
            logger=self.mock_logger,
        )
        self.mock_playbook = mock.MagicMock()
        self.mock_playbook.name = "test_playbook"

    @staticmethod
    def _async_raise(exc):
        """Return an async coroutine function that raises `exc` when awaited.

        run_tests is awaited (not asyncio.run'd) inside execute_playbook, so
        mocks must be async-callable to surface exceptions through the
        await — a plain `def` would either return None or raise too early.
        """

        async def _coro(*args, **kwargs):
            raise exc

        return _coro

    async def test_successful_execution_returns_passed(self):
        async def mock_run_tests(*args, **kwargs):
            pass

        self.mock_runner.run_tests = mock_run_tests

        result = await self.executor.execute_playbook(
            playbook=self.mock_playbook,
            dut="device1",
            test_config="test_config",
        )

        self.assertEqual(result.status, OSSTestStatus.PASSED)
        self.assertEqual(result.playbook, "test_playbook")
        self.assertEqual(result.dut, "device1")
        self.assertEqual(result.test_config, "test_config")
        self.assertFalse(result.is_transient)

    async def test_assertion_error_returns_failed(self):
        self.mock_runner.run_tests = self._async_raise(
            AssertionError("Test assertion failed")
        )
        result = await self.executor.execute_playbook(
            playbook=self.mock_playbook,
            dut="device1",
            test_config="test_config",
        )
        self.assertEqual(result.status, OSSTestStatus.FAILED)
        self.assertIn("Test assertion failed", result.message)
        self.assertEqual(result.exception_type, "AssertionError")
        self.assertFalse(result.is_transient)

    async def test_test_case_failure_returns_failed(self):
        """TAAC raises TestCaseFailure (not AssertionError) for real test
        failures — confirms classify_exception routes it to FAILED so
        JUnit emits <failure>, not <error>."""
        self.mock_runner.run_tests = self._async_raise(
            TestCaseFailure("Postcheck failed")
        )
        result = await self.executor.execute_playbook(
            playbook=self.mock_playbook,
            dut="device1",
            test_config="test_config",
        )
        self.assertEqual(result.status, OSSTestStatus.FAILED)
        self.assertIn("Postcheck failed", result.message)
        self.assertEqual(result.exception_type, "TestCaseFailure")
        self.assertFalse(result.is_transient)

    async def test_timeout_error_returns_timeout(self):
        self.mock_runner.run_tests = self._async_raise(TimeoutError("Test timed out"))
        result = await self.executor.execute_playbook(
            playbook=self.mock_playbook,
            dut="device1",
            test_config="test_config",
        )
        self.assertEqual(result.status, OSSTestStatus.TIMEOUT)
        self.assertIn("Test timed out", result.message)
        self.assertFalse(result.is_transient)

    async def test_testbed_error_returns_error_status(self):
        self.mock_runner.run_tests = self._async_raise(
            OSSTestbedError("Device unreachable")
        )
        result = await self.executor.execute_playbook(
            playbook=self.mock_playbook,
            dut="device1",
            test_config="test_config",
        )
        self.assertEqual(result.status, OSSTestStatus.ERROR)
        self.assertIn("Device unreachable", result.message)
        self.assertEqual(result.exception_type, "OSSTestbedError")
        self.assertFalse(result.is_transient)

    async def test_transient_error_marks_as_transient(self):
        self.mock_runner.run_tests = self._async_raise(
            OSSTransientError("Temporary network issue")
        )
        result = await self.executor.execute_playbook(
            playbook=self.mock_playbook,
            dut="device1",
            test_config="test_config",
        )
        self.assertEqual(result.status, OSSTestStatus.ERROR)
        self.assertIn("Temporary network issue", result.message)
        self.assertTrue(result.is_transient)

    async def test_config_error_returns_error_status(self):
        self.mock_runner.run_tests = self._async_raise(
            OSSConfigError("Invalid configuration")
        )
        result = await self.executor.execute_playbook(
            playbook=self.mock_playbook,
            dut="device1",
            test_config="test_config",
        )
        self.assertEqual(result.status, OSSTestStatus.ERROR)
        self.assertFalse(result.is_transient)


if __name__ == "__main__":
    unittest.main()
