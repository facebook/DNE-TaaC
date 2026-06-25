#!/usr/bin/env python3
# pyre-unsafe

"""
Tests for exception classification logic - validates classify_exception() mapping.
"""

import unittest

from taac.constants import TestCaseFailure
from taac.runner.oss_exception_classifier import (
    classify_exception,
)
from taac.runner.oss_exceptions import (
    OSSConfigError,
    OSSTestbedError,
    OSSTransientError,
)
from taac.runner.oss_test_status import OSSTestStatus


class TestClassifyException(unittest.TestCase):
    """Test classify_exception() for all exception types."""

    def test_assertion_error_maps_to_failed(self):
        """Test AssertionError → (FAILED, False)."""
        exc = AssertionError("Test failed")
        status, is_transient = classify_exception(exc)

        self.assertEqual(status, OSSTestStatus.FAILED)
        self.assertFalse(is_transient)

    def test_test_case_failure_maps_to_failed(self):
        """TestCaseFailure (taac/constants.py) is what TAAC playbooks
        actually raise on a failed health check — not AssertionError.
        Must classify as FAILED so JUnit emits <failure> not <error>."""
        exc = TestCaseFailure("Postcheck regression")
        status, is_transient = classify_exception(exc)

        self.assertEqual(status, OSSTestStatus.FAILED)
        self.assertFalse(is_transient)

    def test_timeout_error_maps_to_timeout(self):
        """Test TimeoutError → (TIMEOUT, False)."""
        exc = TimeoutError("Operation timed out")
        status, is_transient = classify_exception(exc)

        self.assertEqual(status, OSSTestStatus.TIMEOUT)
        self.assertFalse(is_transient)

    def test_connection_error_not_transient_by_default(self):
        """Test ConnectionError → (ERROR, False) unless wrapped in OSSTransientError."""
        exc = ConnectionError("Connection refused")
        status, is_transient = classify_exception(exc)

        self.assertEqual(status, OSSTestStatus.ERROR)
        # Not transient unless explicitly wrapped in OSSTransientError
        self.assertFalse(is_transient)

    def test_os_error_not_transient_by_default(self):
        """Test OSError → (ERROR, False) unless wrapped in OSSTransientError."""
        exc = OSError("Network unreachable")
        status, is_transient = classify_exception(exc)

        self.assertEqual(status, OSSTestStatus.ERROR)
        # Not transient unless explicitly wrapped in OSSTransientError
        self.assertFalse(is_transient)

    def test_config_error_not_transient(self):
        """Test OSSConfigError → (ERROR, False)."""
        exc = OSSConfigError("Invalid config")
        status, is_transient = classify_exception(exc)

        self.assertEqual(status, OSSTestStatus.ERROR)
        self.assertFalse(is_transient)

    def test_testbed_error_not_transient(self):
        """Test OSSTestbedError → (ERROR, False)."""
        exc = OSSTestbedError("Device unreachable")
        status, is_transient = classify_exception(exc)

        self.assertEqual(status, OSSTestStatus.ERROR)
        self.assertFalse(is_transient)

    def test_transient_error_is_transient(self):
        """Test OSSTransientError → (ERROR, True)."""
        exc = OSSTransientError("Temporary issue")
        status, is_transient = classify_exception(exc)

        self.assertEqual(status, OSSTestStatus.ERROR)
        self.assertTrue(is_transient)

    def test_generic_exception_maps_to_error(self):
        """Test generic Exception → (ERROR, False)."""
        exc = Exception("Unknown error")
        status, is_transient = classify_exception(exc)

        self.assertEqual(status, OSSTestStatus.ERROR)
        self.assertFalse(is_transient)

    def test_value_error_maps_to_error(self):
        """Test ValueError → (ERROR, False)."""
        exc = ValueError("Invalid value")
        status, is_transient = classify_exception(exc)

        self.assertEqual(status, OSSTestStatus.ERROR)
        self.assertFalse(is_transient)

    def test_key_error_maps_to_error(self):
        """Test KeyError → (ERROR, False)."""
        exc = KeyError("missing_key")
        status, is_transient = classify_exception(exc)

        self.assertEqual(status, OSSTestStatus.ERROR)
        self.assertFalse(is_transient)

    def test_runtime_error_maps_to_error(self):
        """Test RuntimeError → (ERROR, False)."""
        exc = RuntimeError("Runtime error occurred")
        status, is_transient = classify_exception(exc)

        self.assertEqual(status, OSSTestStatus.ERROR)
        self.assertFalse(is_transient)


class TestOSSExceptions(unittest.TestCase):
    """Test custom exception classes."""

    def test_oss_config_error_is_exception(self):
        """Test OSSConfigError is a proper Exception."""
        exc = OSSConfigError("test")
        self.assertIsInstance(exc, Exception)
        self.assertEqual(str(exc), "test")

    def test_oss_testbed_error_is_exception(self):
        """Test OSSTestbedError is a proper Exception."""
        exc = OSSTestbedError("test")
        self.assertIsInstance(exc, Exception)
        self.assertEqual(str(exc), "test")

    def test_oss_transient_error_is_exception(self):
        """Test OSSTransientError is a proper Exception."""
        exc = OSSTransientError("test")
        self.assertIsInstance(exc, Exception)
        self.assertEqual(str(exc), "test")


if __name__ == "__main__":
    unittest.main()
