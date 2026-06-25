#!/usr/bin/env python3
# pyre-unsafe

"""
Tests for OSSTestStatus enum - validates status values and properties.
"""

import unittest

from taac.runner.oss_test_status import OSSTestStatus


class TestOSSTestStatus(unittest.TestCase):
    """Test OSSTestStatus enum values and behavior."""

    def test_all_status_values_exist(self):
        """Test all required status values are defined."""
        self.assertIsNotNone(OSSTestStatus.PASSED)
        self.assertIsNotNone(OSSTestStatus.FAILED)
        self.assertIsNotNone(OSSTestStatus.ERROR)
        self.assertIsNotNone(OSSTestStatus.TIMEOUT)
        self.assertIsNotNone(OSSTestStatus.SKIPPED)
        self.assertIsNotNone(OSSTestStatus.OMITTED)
        self.assertIsNotNone(OSSTestStatus.RETRIED)

        # Enhancements beyond spec
        self.assertIsNotNone(OSSTestStatus.SETUP_FAILED)
        self.assertIsNotNone(OSSTestStatus.TEARDOWN_FAILED)
        self.assertIsNotNone(OSSTestStatus.NOT_RUN)

    def test_passed_is_not_failed(self):
        """Test PASSED status has failed=False."""
        self.assertFalse(OSSTestStatus.PASSED.failed)

    def test_failed_statuses_have_failed_true(self):
        """Test all failure statuses have failed=True."""
        self.assertTrue(OSSTestStatus.FAILED.failed)
        self.assertTrue(OSSTestStatus.ERROR.failed)
        self.assertTrue(OSSTestStatus.TIMEOUT.failed)
        self.assertTrue(OSSTestStatus.SETUP_FAILED.failed)
        self.assertTrue(OSSTestStatus.TEARDOWN_FAILED.failed)

    def test_skipped_and_omitted_not_failed(self):
        """Test SKIPPED and OMITTED have failed=False."""
        self.assertFalse(OSSTestStatus.SKIPPED.failed)
        self.assertFalse(OSSTestStatus.OMITTED.failed)

    def test_retried_not_failed(self):
        """Test RETRIED status has failed=False (original attempt failed but retry passed)."""
        self.assertFalse(OSSTestStatus.RETRIED.failed)

    def test_not_run_not_failed(self):
        """Test NOT_RUN status has failed=False."""
        self.assertFalse(OSSTestStatus.NOT_RUN.failed)

    def test_color_property_returns_string(self):
        """Test color property returns a string (ANSI code)."""
        for status in OSSTestStatus:
            self.assertIsInstance(status.color, str)

    def test_string_representation(self):
        """Test __str__ returns the status name."""
        self.assertEqual(str(OSSTestStatus.PASSED), "PASSED")
        self.assertEqual(str(OSSTestStatus.FAILED), "FAILED")
        self.assertEqual(str(OSSTestStatus.ERROR), "ERROR")

    def test_status_equality(self):
        """Test status comparison."""
        self.assertEqual(OSSTestStatus.PASSED, OSSTestStatus.PASSED)
        self.assertNotEqual(OSSTestStatus.PASSED, OSSTestStatus.FAILED)


if __name__ == "__main__":
    unittest.main()
