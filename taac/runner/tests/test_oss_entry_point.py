#!/usr/bin/env python3
# pyre-unsafe

"""
Unit tests for OSS Entry Point CLI

Tests the command-line interface and basic functionality of the OSS Entry Point.
"""

import json
import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import TestCase
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from taac.runner import oss_entry_point
from taac.runner.cli_parser import create_argument_parser
from taac.runner.oss_return_code import OSSReturnCode
from taac.runner.oss_test_result import OSSTestResult
from taac.runner.oss_test_status import OSSTestStatus
from taac.runner.result_formatter import OSSResultAggregator
from taac.test_as_a_config import types as taac_types


class TestCLIParser(TestCase):
    """Test CLI argument parsing."""

    def test_required_arguments(self):
        """Test that required arguments are present."""
        parser = create_argument_parser()

        # Test with all required args
        args = parser.parse_args(
            [
                "--test-configs",
                "test1.py",
                "test2.py",
                "--dut",
                "device1",
                "--ixia-api-server",
                "10.0.0.1",
            ]
        )

        self.assertEqual(args.test_configs, ["test1.py", "test2.py"])
        self.assertEqual(args.duts, ["device1"])
        self.assertEqual(args.ixia_api_server, "10.0.0.1")

    def test_output_format_argument(self):
        """Test --output-format argument."""
        parser = create_argument_parser()

        # Test json format
        args = parser.parse_args(
            [
                "--test-configs",
                "test.py",
                "--dut",
                "dev1",
                "--ixia-api-server",
                "10.0.0.1",
                "--output-format",
                "json",
            ]
        )
        self.assertEqual(args.output_format, "json")

        # Test junit format
        args = parser.parse_args(
            [
                "--test-configs",
                "test.py",
                "--dut",
                "dev1",
                "--ixia-api-server",
                "10.0.0.1",
                "--output-format",
                "junit",
            ]
        )
        self.assertEqual(args.output_format, "junit")

        # Test default (text)
        args = parser.parse_args(
            [
                "--test-configs",
                "test.py",
                "--dut",
                "dev1",
                "--ixia-api-server",
                "10.0.0.1",
            ]
        )
        self.assertEqual(args.output_format, "text")

    def test_all_specified_arguments_exist(self):
        """Test that all arguments from spec exist."""
        parser = create_argument_parser()

        args = parser.parse_args(
            [
                "--test-configs",
                "test.py",
                "--dut",
                "device1",
                "--ixia-api-server",
                "10.0.0.1",
            ]
        )

        # Verify all required attributes exist
        self.assertTrue(hasattr(args, "test_configs"))
        self.assertTrue(hasattr(args, "duts"))
        self.assertTrue(hasattr(args, "ixia_api_server"))
        self.assertTrue(hasattr(args, "ixia_session_id"))
        self.assertTrue(hasattr(args, "skip_ixia_setup"))
        self.assertTrue(hasattr(args, "skip_ixia_cleanup"))
        self.assertTrue(hasattr(args, "skip_testbed_isolation"))
        self.assertTrue(hasattr(args, "skip_setup_tasks"))
        self.assertTrue(hasattr(args, "skip_teardown_tasks"))
        self.assertTrue(hasattr(args, "log_level"))
        self.assertTrue(hasattr(args, "log_file"))
        self.assertTrue(hasattr(args, "dry_run"))
        self.assertTrue(hasattr(args, "output_format"))
        self.assertTrue(hasattr(args, "json_output"))
        self.assertTrue(hasattr(args, "junit_output"))


class TestExitCodes(TestCase):
    """Test that exit codes match specification."""

    def test_exit_codes_match_spec(self):
        """Verify exit codes match the specification."""
        # Success
        self.assertEqual(OSSReturnCode.SUCCESS, 0)

        # User errors (1-127)
        self.assertEqual(OSSReturnCode.USER_ERROR, 1)
        self.assertEqual(OSSReturnCode.TEST_CASE_FAILURE, 2)
        self.assertEqual(OSSReturnCode.INVALID_INPUT, 3)
        self.assertEqual(OSSReturnCode.NO_TESTS_FOUND, 4)
        self.assertEqual(OSSReturnCode.CONFIG_ERROR, 5)

        # Infrastructure errors (128+)
        self.assertEqual(OSSReturnCode.INFRA_ERROR, 128)
        self.assertEqual(OSSReturnCode.TESTBED_ERROR, 129)
        self.assertEqual(OSSReturnCode.TRANSIENT_ERROR, 130)
        self.assertEqual(OSSReturnCode.TIMEOUT_ERROR, 131)
        self.assertEqual(OSSReturnCode.CONNECTION_ERROR, 132)

        # Test helper methods
        self.assertTrue(OSSReturnCode.SUCCESS.is_success())
        self.assertFalse(OSSReturnCode.TEST_CASE_FAILURE.is_success())

        self.assertTrue(OSSReturnCode.TEST_CASE_FAILURE.is_user_error())
        self.assertFalse(OSSReturnCode.INFRA_ERROR.is_user_error())

        self.assertTrue(OSSReturnCode.INFRA_ERROR.is_infra_error())
        self.assertFalse(OSSReturnCode.TEST_CASE_FAILURE.is_infra_error())


class TestResultFormatter(TestCase):
    """Test result formatting (JSON and JUnit XML)."""

    def test_json_output_format(self):
        """Test JSON output format generation."""
        aggregator = OSSResultAggregator()

        # Add test results
        result = OSSTestResult(
            test_config="test_config.py",
            playbook="playbook1",
            dut="device1",
            status=OSSTestStatus.PASSED,
        )
        result.mark_complete(OSSTestStatus.PASSED, "Test passed")
        aggregator.add_result(result)

        # Write to temporary file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json_path = f.name

        try:
            aggregator.to_json(json_path)

            # Verify JSON is valid
            with open(json_path, "r") as f:
                data = json.load(f)

            self.assertIn("summary", data)
            self.assertIn("results", data)
            self.assertEqual(len(data["results"]), 1)
            self.assertEqual(data["summary"]["total"], 1)
            self.assertEqual(data["summary"]["passed"], 1)
        finally:
            if os.path.exists(json_path):
                os.unlink(json_path)

    def test_junit_xml_output_format(self):
        """Test JUnit XML output format generation."""
        aggregator = OSSResultAggregator()

        # Add passed and failed test results
        result1 = OSSTestResult(
            test_config="test_config.py",
            playbook="playbook1",
            dut="device1",
            status=OSSTestStatus.PASSED,
        )
        result1.mark_complete(OSSTestStatus.PASSED, "Test passed")
        aggregator.add_result(result1)

        result2 = OSSTestResult(
            test_config="test_config.py",
            playbook="playbook2",
            dut="device2",
            status=OSSTestStatus.FAILED,
        )
        result2.mark_complete(OSSTestStatus.FAILED, "Test failed")
        result2.traceback = "Error traceback"
        aggregator.add_result(result2)

        # Write to temporary file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False) as f:
            junit_path = f.name

        try:
            aggregator.to_junit_xml(junit_path)

            # Verify XML is valid
            tree = ET.parse(junit_path)
            root = tree.getroot()

            self.assertEqual(root.tag, "testsuites")
            self.assertEqual(root.get("tests"), "2")
            self.assertEqual(root.get("failures"), "1")

            # Check testsuite structure
            testsuite = root.find("testsuite")
            self.assertIsNotNone(testsuite)
            self.assertEqual(testsuite.get("name"), "TAAC_OSS_Tests")

            # Check testcases
            testcases = testsuite.findall("testcase")
            self.assertEqual(len(testcases), 2)

            # Verify failure element exists
            failures = testsuite.findall(".//failure")
            self.assertEqual(len(failures), 1)
        finally:
            if os.path.exists(junit_path):
                os.unlink(junit_path)


class TestEntryPointIntegration(TestCase):
    """Integration tests for main() function with mocked TaacRunner.

    These tests verify end-to-end integration of the entry point with
    OSSTestExecutor and ensure parameter passing is correct.

    NOTE: These tests require the TAAC infrastructure (taac.test_as_a_config
    module) and must be run in the Docker environment.
    """

    def _create_minimal_test_config(self):
        """Create a minimal test config for testing."""
        return taac_types.TestConfig(
            name="minimal_test",
            playbooks=[
                taac_types.Playbook(
                    name="test_playbook",
                    stages=[
                        taac_types.Stage(
                            steps=[],  # Empty steps for simplicity
                        ),
                    ],
                ),
            ],
        )

    @patch("taac.runner.oss_entry_point.OSSTestExecutor")
    @patch("taac.libs.taac_runner.TaacRunner")
    @patch("taac.runner.oss_entry_point.load_test_config")
    def test_main_calls_execute_playbook_with_correct_parameter_names(
        self, mock_load_config, mock_taac_runner_class, mock_executor_class
    ):
        """Test that main() calls execute_playbook() with correct parameter names.

        This is a regression test for the bug where we called execute_playbook
        with test_config_name= instead of test_config=.
        """
        # Setup mock config
        test_config = self._create_minimal_test_config()
        mock_load_config.return_value = test_config

        # Setup mock TaacRunner with async methods
        mock_runner = Mock()

        # Mock async methods to return coroutines
        async def mock_async_setup():
            pass

        async def mock_async_teardown():
            pass

        mock_runner.async_test_setUp = Mock(side_effect=lambda: mock_async_setup())
        mock_runner.async_test_tearDown = Mock(
            side_effect=lambda: mock_async_teardown()
        )
        mock_taac_runner_class.return_value = mock_runner

        # Setup mock executor
        mock_executor = Mock()
        mock_executor_class.return_value = mock_executor

        # execute_playbook is async — production code awaits it. Use
        # AsyncMock so awaiting the call returns the result rather than
        # raising TypeError on a plain Mock's non-coroutine return.
        mock_result = OSSTestResult(
            playbook="test_playbook",
            dut="dummy-device",
            status=OSSTestStatus.PASSED,
            test_config="minimal_test",
            duration=1.0,
        )
        mock_executor.execute_playbook = AsyncMock(return_value=mock_result)

        # Create temp config file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            config_path = f.name
            f.write("test_config = None")  # Dummy, we mock load_test_config

        try:
            # Call main
            with patch(
                "sys.argv",
                [
                    "oss_entry_point.py",
                    "--test-configs",
                    config_path,
                    "--dut",
                    "dummy-device",
                    "--ixia-api-server",
                    "10.0.0.1",
                ],
            ):
                exit_code = oss_entry_point.main()

            # Verify execute_playbook was called
            self.assertTrue(mock_executor.execute_playbook.called)

            # CRITICAL: Verify the parameter name is 'test_config' not 'test_config_name'
            call_kwargs = mock_executor.execute_playbook.call_args.kwargs
            self.assertIn(
                "test_config",
                call_kwargs,
                "execute_playbook must be called with 'test_config' parameter",
            )
            self.assertNotIn(
                "test_config_name",
                call_kwargs,
                "execute_playbook should NOT be called with 'test_config_name'",
            )

            # Verify exit code is SUCCESS
            self.assertEqual(exit_code, OSSReturnCode.SUCCESS)

        finally:
            if os.path.exists(config_path):
                os.unlink(config_path)

    @patch("taac.runner.oss_entry_point.OSSTestExecutor")
    @patch("taac.libs.taac_runner.TaacRunner")
    @patch("taac.runner.oss_entry_point.load_test_config")
    def test_main_executes_multiple_playbooks_and_duts(
        self, mock_load_config, mock_taac_runner_class, mock_executor_class
    ):
        """Test that main() executes all playbook × DUT combinations."""
        # Setup mock config with 2 playbooks
        test_config = taac_types.TestConfig(
            name="multi_test",
            playbooks=[
                taac_types.Playbook(
                    name="playbook1", stages=[taac_types.Stage(steps=[])]
                ),
                taac_types.Playbook(
                    name="playbook2", stages=[taac_types.Stage(steps=[])]
                ),
            ],
        )
        mock_load_config.return_value = test_config

        # Setup mocks with async methods
        mock_runner = Mock()

        async def mock_async_setup():
            pass

        async def mock_async_teardown():
            pass

        mock_runner.async_test_setUp = Mock(side_effect=lambda: mock_async_setup())
        mock_runner.async_test_tearDown = Mock(
            side_effect=lambda: mock_async_teardown()
        )
        mock_taac_runner_class.return_value = mock_runner

        mock_executor = Mock()
        mock_executor_class.return_value = mock_executor

        # execute_playbook is async — see note above.
        mock_result = OSSTestResult(
            playbook="test",
            dut="device",
            status=OSSTestStatus.PASSED,
            test_config="multi_test",
            duration=1.0,
        )
        mock_executor.execute_playbook = AsyncMock(return_value=mock_result)

        # Create temp config file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            config_path = f.name
            f.write("test_config = None")

        try:
            # Call main with 2 DUTs
            with patch(
                "sys.argv",
                [
                    "oss_entry_point.py",
                    "--test-configs",
                    config_path,
                    "--dut",
                    "device1",
                    "device2",
                    "--ixia-api-server",
                    "10.0.0.1",
                ],
            ):
                exit_code = oss_entry_point.main()

            # Verify execute_playbook was called 4 times (2 playbooks × 2 DUTs)
            self.assertEqual(mock_executor.execute_playbook.call_count, 4)

            # Verify setUp and tearDown were called
            mock_runner.async_test_setUp.assert_called_once()
            mock_runner.async_test_tearDown.assert_called_once()

            # Verify exit code is SUCCESS
            self.assertEqual(exit_code, OSSReturnCode.SUCCESS)

        finally:
            if os.path.exists(config_path):
                os.unlink(config_path)

    @patch("taac.runner.oss_entry_point.OSSTestExecutor")
    @patch("taac.libs.taac_runner.TaacRunner")
    @patch("taac.runner.oss_entry_point.load_test_config")
    def test_main_retry_loop_marks_original_retried_and_clears_transient(
        self,
        mock_load_config,
        mock_taac_runner_class,
        mock_executor_class,
    ):
        """End-to-end retry-loop coverage: transient failure on attempt 1,
        success on attempt 2, --retry 1.

        Verifies the spec contract that PR #31 fixed:
        - original result.status becomes RETRIED
        - original result.is_transient is cleared on retry success
        - aggregator.get_exit_code() returns SUCCESS (0), NOT
          TRANSIENT_ERROR (130) — the bug Mabel flagged on #31.

        Pure dataclass-and-mock tests can't catch this; the loop lives in
        main() between execute_playbook calls.
        """
        test_config = self._create_minimal_test_config()
        mock_load_config.return_value = test_config

        mock_runner = Mock()

        async def mock_async_setup():
            pass

        async def mock_async_teardown():
            pass

        mock_runner.async_test_setUp = Mock(side_effect=lambda: mock_async_setup())
        mock_runner.async_test_tearDown = Mock(
            side_effect=lambda: mock_async_teardown()
        )
        mock_taac_runner_class.return_value = mock_runner

        mock_executor = Mock()
        mock_executor_class.return_value = mock_executor

        transient_result = OSSTestResult(
            test_config="minimal_test",
            playbook="test_playbook",
            dut="dummy-device",
            status=OSSTestStatus.ERROR,
            is_transient=True,
            duration=0.1,
            message="Temporary network issue",
            exception_type="OSSTransientError",
        )
        retry_pass_result = OSSTestResult(
            test_config="minimal_test",
            playbook="test_playbook",
            dut="dummy-device",
            status=OSSTestStatus.PASSED,
            is_transient=False,
            duration=0.1,
            message="",
        )
        mock_executor.execute_playbook = AsyncMock(
            side_effect=[transient_result, retry_pass_result],
        )

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            config_path = f.name
            f.write("test_config = None")

        try:
            with patch(
                "sys.argv",
                [
                    "oss_entry_point.py",
                    "--test-configs",
                    config_path,
                    "--dut",
                    "dummy-device",
                    "--ixia-api-server",
                    "10.0.0.1",
                    "--retry",
                    "1",
                ],
            ):
                exit_code = oss_entry_point.main()

            # Two execute_playbook calls: 1 original + 1 retry.
            self.assertEqual(mock_executor.execute_playbook.call_count, 2)

            # Original transient_result was mutated in-place by main().
            self.assertEqual(transient_result.status, OSSTestStatus.RETRIED)
            self.assertFalse(
                transient_result.is_transient,
                "PR #31 fix: retry success must clear is_transient on the "
                "original so get_exit_code doesn't return TRANSIENT_ERROR",
            )

            # Full recovery → exit 0, not 130.
            self.assertEqual(exit_code, OSSReturnCode.SUCCESS)
        finally:
            if os.path.exists(config_path):
                os.unlink(config_path)

    @patch("taac.runner.oss_entry_point.OSSTestExecutor")
    @patch("taac.libs.taac_runner.TaacRunner")
    @patch("taac.runner.oss_entry_point.load_test_config")
    def test_main_setup_crash_marks_remaining_combos(
        self,
        mock_load_config,
        mock_taac_runner_class,
        mock_executor_class,
    ):
        """Coverage for the entry-point error handler at the lifecycle
        boundary: when async_test_setUp() raises, _run_lifecycle bubbles
        the exception past asyncio.run(), the outer except branch
        classifies it via classify_exception, and *every* playbook×dut
        combo that never produced a result gets a synthetic result with
        the classified status. Mabel-thread-#7 follow-up: previously
        untested path."""
        test_config = taac_types.TestConfig(
            name="multi_test",
            playbooks=[
                taac_types.Playbook(
                    name="playbook1", stages=[taac_types.Stage(steps=[])]
                ),
                taac_types.Playbook(
                    name="playbook2", stages=[taac_types.Stage(steps=[])]
                ),
            ],
        )
        mock_load_config.return_value = test_config

        mock_runner = Mock()

        async def mock_async_setup():
            raise RuntimeError("setUp crashed: thrift connection refused")

        async def mock_async_teardown():
            pass

        mock_runner.async_test_setUp = Mock(side_effect=lambda: mock_async_setup())
        mock_runner.async_test_tearDown = Mock(
            side_effect=lambda: mock_async_teardown()
        )
        mock_taac_runner_class.return_value = mock_runner

        # execute_playbook should never be reached — setUp dies first.
        mock_executor = Mock()
        mock_executor.execute_playbook = AsyncMock()
        mock_executor_class.return_value = mock_executor

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            config_path = f.name
            f.write("test_config = None")

        try:
            with patch(
                "sys.argv",
                [
                    "oss_entry_point.py",
                    "--test-configs",
                    config_path,
                    "--dut",
                    "device1",
                    "device2",
                    "--ixia-api-server",
                    "10.0.0.1",
                ],
            ):
                exit_code = oss_entry_point.main()

            # setUp crash → execute_playbook never called.
            self.assertEqual(mock_executor.execute_playbook.call_count, 0)

            # 2 playbooks × 2 DUTs = 4 synthetic error records.
            self.assertEqual(exit_code, OSSReturnCode.TEST_CASE_FAILURE)
        finally:
            if os.path.exists(config_path):
                os.unlink(config_path)


if __name__ == "__main__":
    import unittest

    unittest.main()
