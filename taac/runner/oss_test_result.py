# pyre-unsafe

"""
OSS Test Result Dataclass

Represents the result of a single test execution.
"""

import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from taac.runner.oss_test_status import OSSTestStatus


@dataclass
class OSSTestResult:
    """
    Result of a single test execution.

    This dataclass captures all relevant information about a test run,
    including status, timing, errors, and metadata.
    """

    # Test identification
    test_config: str  # Name of the test configuration
    playbook: str  # Name of the playbook
    dut: str  # Device under test (hostname or IP)

    # Test outcome
    status: OSSTestStatus  # Final status of the test
    message: str = ""  # Human-readable message (error details, etc.)

    # Timing information
    start_time: float = field(default_factory=time.time)  # Unix timestamp
    end_time: Optional[float] = None  # Unix timestamp
    duration: Optional[float] = None  # Duration in seconds

    # Error information
    exception: Optional[Exception] = None  # Exception that caused failure (if any)
    traceback: Optional[str] = None  # Full traceback (if any)

    stdout: str = ""  # Captured stdout
    stderr: str = ""  # Captured stderr
    exception_type: Optional[str] = None  # Exception class name
    exception_message: Optional[str] = None  # Exception message
    is_transient: bool = False  # Was this a transient error?
    retry_count: int = 0  # Number of retries attempted
    log_file: Optional[str] = None  # Path to log file

    # Metadata
    metadata: Dict[str, str] = field(default_factory=dict)  # Additional metadata

    # Aliases
    @property
    def test_case(self) -> str:
        """Alias for playbook (spec uses test_case)."""
        return self.playbook

    @property
    def stacktrace(self) -> Optional[str]:
        """Alias for traceback (spec uses stacktrace)."""
        return self.traceback

    @property
    def failed(self) -> bool:
        """Check if this test result represents a failure."""
        return self.status.failed

    def mark_complete(self, status: OSSTestStatus, message: str = "") -> None:
        """
        Mark the test as complete with the given status.

        Args:
            status: Final status of the test
            message: Optional message describing the outcome
        """
        self.status = status
        self.message = message
        self.end_time = time.time()
        if self.end_time and self.start_time:
            self.duration = self.end_time - self.start_time

    def to_dict(self) -> Dict:
        """
        Convert the result to a dictionary for JSON serialization.

        Returns:
            Dictionary representation of the result
        """
        return {
            "test_case": self.test_case,
            "test_config": self.test_config,
            "playbook": self.playbook,
            "dut": self.dut,
            "status": str(self.status),
            "message": self.message,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "exception": str(self.exception) if self.exception else None,
            "traceback": self.traceback,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exception_type": self.exception_type,
            "exception_message": self.exception_message,
            "is_transient": self.is_transient,
            "retry_count": self.retry_count,
            "log_file": self.log_file,
            "metadata": self.metadata,
        }

    def summary(self) -> str:
        """One-line summary of the test result.

        ANSI color is emitted only when stdout is a TTY so that
        --log-file output and non-tty CI captures (Jenkins / GHA console
        / redirected stdout) get plain `[NAME]` instead of raw escape
        sequences. Re-checked on every call so test-suite captures
        (which may replace sys.stdout per-test) see the right answer.
        """
        if sys.stdout.isatty():
            color = self.status.color
            reset = OSSTestStatus.reset_color()
        else:
            color = ""
            reset = ""
        duration_str = f"{self.duration:.2f}s" if self.duration is not None else "N/A"
        return f"{color}[{self.status.name}]{reset} {self.test_case} ({duration_str})"

    def detailed_message(self) -> str:
        """Multi-line detailed message."""
        lines = [
            f"Test Case: {self.test_case}",
            f"Test Config: {self.test_config}",
            f"Status: {self.status.name}",
            (
                f"Duration: {self.duration:.2f}s"
                if self.duration is not None
                else "Duration: N/A"
            ),
        ]
        if self.dut:
            lines.append(f"DUT: {self.dut}")
        if self.message:
            lines.append(f"Message: {self.message}")
        if self.exception_type:
            lines.append(f"Exception Type: {self.exception_type}")
        if self.exception_message:
            lines.append(f"Exception Message: {self.exception_message}")
        if self.stacktrace:
            lines.append(f"Stacktrace:\n{self.stacktrace}")
        if self.log_file:
            lines.append(f"Log File: {self.log_file}")
        if self.retry_count > 0:
            lines.append(f"Retry Count: {self.retry_count}")
        if self.is_transient:
            lines.append("Transient: Yes (retry-able)")
        return "\n".join(lines)

    def __str__(self) -> str:
        """String representation of the result."""
        return self.summary()
