# pyre-unsafe

"""
OSS Test Status Enum

Defines the possible states of a test execution in the OSS environment.

Mirrors Netcastle's TestStatus but without Testpilot dependencies.
Order indicates priority for display (ERROR/FAILED shown first).
"""

from enum import Enum


class OSSTestStatus(str, Enum):
    """
    Test execution status for OSS TAAC tests.

    Mirrors Netcastle's TestStatus but without Testpilot dependencies.
    Order indicates priority for display (ERROR/FAILED shown first).
    """

    ERROR = "ERROR"  # Unexpected exception during test execution
    FAILED = "FAILED"  # Test assertion failed (expected != actual)
    TIMEOUT = "TIMEOUT"  # Test exceeded time limit
    PASSED = "PASSED"  # Test completed successfully
    SKIPPED = "SKIPPED"  # Test was intentionally skipped
    OMITTED = "OMITTED"  # Test was not considered to run (filtered out)
    RETRIED = "RETRIED"  # Previous attempt before a retry that passed

    # Additional infrastructure states (not in the spec but useful)
    SETUP_FAILED = "SETUP_FAILED"  # Test setup failed
    TEARDOWN_FAILED = "TEARDOWN_FAILED"  # Test teardown failed
    TESTBED_FAILED = "TESTBED_FAILED"  # OSSTestbedError (device/testbed connectivity)
    CONNECTION_FAILED = (
        "CONNECTION_FAILED"  # OSSConnectionError (thrift/network connection)
    )
    NOT_RUN = "NOT_RUN"  # Test was not executed

    def __str__(self) -> str:
        """String representation of the status."""
        return self.name

    @property
    def failed(self) -> bool:
        """
        A test is considered "failed" if the status is one of the
        non-passing, non-skipped buckets:
        - FAILED (AssertionError / TestCaseFailure)
        - ERROR (unexpected exception)
        - TIMEOUT
        - SETUP_FAILED / TEARDOWN_FAILED
        - TESTBED_FAILED (OSSTestbedError) / CONNECTION_FAILED (OSSConnectionError)
        """
        return self in (
            OSSTestStatus.FAILED,
            OSSTestStatus.ERROR,
            OSSTestStatus.TIMEOUT,
            OSSTestStatus.SETUP_FAILED,
            OSSTestStatus.TEARDOWN_FAILED,
            OSSTestStatus.TESTBED_FAILED,
            OSSTestStatus.CONNECTION_FAILED,
        )

    @property
    def color(self) -> str:
        """ANSI color codes for terminal output."""
        COLOR_MAP = {
            OSSTestStatus.PASSED: "\x1b[32m",  # GREEN
            OSSTestStatus.FAILED: "\x1b[31m",  # RED
            OSSTestStatus.ERROR: "\x1b[31m",  # RED
            OSSTestStatus.TIMEOUT: "\x1b[33m",  # YELLOW
            OSSTestStatus.SKIPPED: "\x1b[37m",  # WHITE
            OSSTestStatus.OMITTED: "\x1b[37m",  # WHITE
            OSSTestStatus.RETRIED: "\x1b[37m",  # WHITE
            OSSTestStatus.SETUP_FAILED: "\x1b[31m",  # RED
            OSSTestStatus.TEARDOWN_FAILED: "\x1b[33m",  # YELLOW
            OSSTestStatus.TESTBED_FAILED: "\x1b[33m",  # YELLOW (infra, not test regression)
            OSSTestStatus.CONNECTION_FAILED: "\x1b[33m",  # YELLOW (infra, not test regression)
            OSSTestStatus.NOT_RUN: "\x1b[37m",  # WHITE
        }
        return COLOR_MAP.get(self, "\x1b[0m")

    @staticmethod
    def reset_color() -> str:
        """ANSI reset code to return to default terminal color."""
        return "\x1b[0m"

    # Backward compatibility methods
    def is_success(self) -> bool:
        """Check if this status represents a successful test."""
        return self == OSSTestStatus.PASSED

    def is_skipped(self) -> bool:
        """Check if this status represents a skipped/non-final test.

        Includes RETRIED so the original-attempt records produced by
        the retry loop are accounted for in skipped_count and rendered
        with `<skipped>` markup in JUnit output (rather than slipping
        through `tests = passed + failed + errors + skipped`).
        """
        return self in (
            OSSTestStatus.SKIPPED,
            OSSTestStatus.OMITTED,
            OSSTestStatus.NOT_RUN,
            OSSTestStatus.RETRIED,
        )
