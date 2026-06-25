#!/usr/bin/env python3
# pyre-unsafe

"""
Tests for OSSTestResult dataclass - validates fields and methods.
"""

import time
import unittest
from datetime import datetime

from taac.runner.oss_test_result import OSSTestResult
from taac.runner.oss_test_status import OSSTestStatus


class TestOSSTestResult(unittest.TestCase):
    """Test OSSTestResult dataclass."""

    def test_initialization_with_required_fields(self):
        """Test OSSTestResult can be initialized with required fields."""
        result = OSSTestResult(
            test_config="test_config",
            playbook="test_playbook",
            dut="device1",
            status=OSSTestStatus.PASSED,
            duration=1.5,
            message="Test passed",
        )

        self.assertEqual(result.test_config, "test_config")
        self.assertEqual(result.playbook, "test_playbook")
        self.assertEqual(result.dut, "device1")
        self.assertEqual(result.status, OSSTestStatus.PASSED)
        self.assertEqual(result.duration, 1.5)
        self.assertEqual(result.message, "Test passed")

    def test_optional_fields_default_to_none(self):
        """Test optional fields default to None."""
        result = OSSTestResult(
            test_config="test",
            playbook="pb",
            dut="dut1",
            status=OSSTestStatus.PASSED,
            duration=1.0,
            message="msg",
        )

        self.assertIsNone(result.exception_type)
        self.assertIsNone(result.exception_message)
        self.assertIsNone(result.stacktrace)
        self.assertIsNone(result.log_file)

    def test_failed_property(self):
        """Test failed property delegates to status.failed."""
        passed_result = OSSTestResult(
            test_config="test",
            playbook="pb",
            dut="dut1",
            status=OSSTestStatus.PASSED,
            duration=1.0,
            message="msg",
        )
        self.assertFalse(passed_result.failed)

        failed_result = OSSTestResult(
            test_config="test",
            playbook="pb",
            dut="dut1",
            status=OSSTestStatus.FAILED,
            duration=1.0,
            message="msg",
        )
        self.assertTrue(failed_result.failed)

    def test_to_dict_serialization(self):
        """Test to_dict() serializes all fields."""
        result = OSSTestResult(
            test_config="test_config",
            playbook="test_playbook",
            dut="device1",
            status=OSSTestStatus.PASSED,
            duration=1.5,
            message="Test passed",
            retry_count=0,
            is_transient=False,
        )

        result_dict = result.to_dict()

        self.assertIsInstance(result_dict, dict)
        self.assertEqual(result_dict["test_config"], "test_config")
        self.assertEqual(result_dict["playbook"], "test_playbook")
        self.assertEqual(result_dict["dut"], "device1")
        self.assertEqual(result_dict["status"], "PASSED")
        self.assertEqual(result_dict["duration"], 1.5)

    def test_mark_complete_sets_end_time(self):
        """Test mark_complete() sets end_time and calculates duration."""
        result = OSSTestResult(
            test_config="test",
            playbook="pb",
            dut="dut1",
            status=OSSTestStatus.PASSED,
            duration=0.0,
            message="msg",
        )

        # Set start time using time.time() (not datetime)
        result.start_time = time.time()

        # Sleep briefly to ensure duration > 0
        time.sleep(0.01)

        # Mark complete with status
        result.mark_complete(status=OSSTestStatus.PASSED)

        # Verify end_time is set
        self.assertIsNotNone(result.end_time)
        self.assertGreater(result.duration, 0.0)

    def test_is_transient_default_false(self):
        """Test is_transient defaults to False."""
        result = OSSTestResult(
            test_config="test",
            playbook="pb",
            dut="dut1",
            status=OSSTestStatus.ERROR,
            duration=1.0,
            message="msg",
        )

        self.assertFalse(result.is_transient)

    def test_retry_count_default_zero(self):
        """Test retry_count defaults to 0."""
        result = OSSTestResult(
            test_config="test",
            playbook="pb",
            dut="dut1",
            status=OSSTestStatus.PASSED,
            duration=1.0,
            message="msg",
        )

        self.assertEqual(result.retry_count, 0)

    def test_exception_details_captured(self):
        """Test exception details are captured correctly."""
        result = OSSTestResult(
            test_config="test",
            playbook="pb",
            dut="dut1",
            status=OSSTestStatus.ERROR,
            duration=1.0,
            message="Error occurred",
            exception_type="ValueError",
            exception_message="Invalid value",
            traceback="Traceback...",
        )

        self.assertEqual(result.exception_type, "ValueError")
        self.assertEqual(result.exception_message, "Invalid value")
        self.assertIsNotNone(result.traceback)


if __name__ == "__main__":
    unittest.main()
