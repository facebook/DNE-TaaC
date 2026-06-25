# pyre-unsafe

"""
OSS Return Code Enum

Defines the exit codes for the OSS TAAC entry point.

Convention (POSIX convention):
- 0: Success
- 1-127: User errors (test failures, invalid input)
- 128+: Infrastructure errors
"""

from enum import IntEnum


class OSSReturnCode(IntEnum):
    """
    Exit codes for OSS TAAC entry point.

    Convention:
    - 0: Success
    - 1-127: User errors (test failures, invalid input)
    - 128+: Infrastructure errors
    """

    # Success
    SUCCESS = 0

    # User Errors (1-127)
    USER_ERROR = 1  # Unclassified user error
    TEST_CASE_FAILURE = 2  # One or more tests failed
    INVALID_INPUT = 3  # Invalid CLI arguments or config
    NO_TESTS_FOUND = 4  # No test cases discovered
    CONFIG_ERROR = 5  # Test config loading failed

    # Infrastructure Errors (128+)
    INFRA_ERROR = 128  # Unclassified infra error
    TESTBED_ERROR = 129  # Device/testbed connectivity issue
    TRANSIENT_ERROR = 130  # Transient error (retry-able)
    TIMEOUT_ERROR = 131  # Global timeout exceeded
    CONNECTION_ERROR = 132  # Thrift connection failed

    def is_success(self) -> bool:
        """Check if this return code indicates success."""
        return self == OSSReturnCode.SUCCESS

    def is_user_error(self) -> bool:
        """Check if this return code indicates a user error (1-127)."""
        return 1 <= self.value <= 127

    def is_infra_error(self) -> bool:
        """Check if this return code indicates an infrastructure error (128+)."""
        return self.value >= 128

    def __str__(self) -> str:
        """String representation of the return code."""
        return f"{self.name} ({self.value})"
