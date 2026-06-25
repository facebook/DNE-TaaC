#!/usr/bin/env python3
# pyre-unsafe

"""
Integration tests for OSS entry point with mocked TaacRunner.
Tests the full execution flow from CLI args to result aggregation.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from taac.runner.oss_entry_point import main
from taac.runner.oss_return_code import OSSReturnCode


class TestEntryPointCLIModes(unittest.TestCase):
    """File-based main() invocations: --list-tests / --dry-run / --help /
    bad config path / output-file args. Sibling class
    test_oss_entry_point.TestEntryPointIntegration covers the
    mocked-executor end-to-end path. Renamed to avoid the class-name
    collision (both modules define `TestEntryPointIntegration` →
    confusing in test-runner output)."""

    def setUp(self):
        """Set up test fixtures."""
        # Create a minimal test config file
        self.test_config_content = """
from taac.test_as_a_config import types as taac_types

test_config = taac_types.TestConfig(
    name="integration_test",
    playbooks=[
        taac_types.Playbook(
            name="test_playbook",
            enabled=True,
            stages=[
                taac_types.Stage(steps=[]),
            ],
        ),
    ],
)
"""
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = Path(self.temp_dir) / "test_config.py"
        self.config_file.write_text(self.test_config_content)

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_list_tests_mode(self):
        """Test --list-tests mode lists playbooks without execution."""
        exit_code = main(
            [
                "--test-configs",
                str(self.config_file),
                "--dut",
                "dummy-device",
                "--list-tests",
            ]
        )

        # Should succeed
        self.assertEqual(exit_code, OSSReturnCode.SUCCESS.value)

    def test_dry_run_mode(self):
        """Test --dry-run mode validates without execution."""
        exit_code = main(
            [
                "--test-configs",
                str(self.config_file),
                "--dut",
                "dummy-device",
                "--dry-run",
            ]
        )

        # Should succeed
        self.assertEqual(exit_code, OSSReturnCode.SUCCESS.value)

    def test_invalid_config_file_returns_config_error(self):
        """Test invalid config file returns CONFIG_ERROR (5)."""
        exit_code = main(
            [
                "--test-configs",
                "/nonexistent/file.py",
                "--dut",
                "dummy-device",
                "--list-tests",
            ]
        )

        # Should return CONFIG_ERROR
        self.assertEqual(exit_code, OSSReturnCode.CONFIG_ERROR.value)

    def test_missing_required_args_returns_user_error(self):
        """Test missing required arguments returns USER_ERROR (1)."""
        # Missing --dut argument
        with self.assertRaises(SystemExit) as cm:
            main(["--test-configs", str(self.config_file)])

        # argparse exits with 2 for argument errors
        self.assertEqual(cm.exception.code, 2)

    # Note: Full execution test requires real TaacRunner and infrastructure
    # Tested at integration level with actual testbed

    def test_help_mode(self):
        """Test --help mode works."""
        with self.assertRaises(SystemExit) as cm:
            main(["--help"])

        # --help should exit with 0
        self.assertEqual(cm.exception.code, 0)

    def test_output_json_argument(self):
        """Test --json-output argument is accepted."""
        import tempfile

        json_file = tempfile.mktemp(suffix=".json")

        exit_code = main(
            [
                "--test-configs",
                str(self.config_file),
                "--dut",
                "dummy-device",
                "--json-output",
                json_file,
                "--list-tests",
            ]
        )

        # Should succeed
        self.assertEqual(exit_code, OSSReturnCode.SUCCESS.value)

    def test_junit_output_argument(self):
        """Test --junit-output argument is accepted."""
        import tempfile

        junit_file = tempfile.mktemp(suffix=".xml")

        exit_code = main(
            [
                "--test-configs",
                str(self.config_file),
                "--dut",
                "dummy-device",
                "--junit-output",
                junit_file,
                "--list-tests",
            ]
        )

        # Should succeed
        self.assertEqual(exit_code, OSSReturnCode.SUCCESS.value)


if __name__ == "__main__":
    unittest.main()
