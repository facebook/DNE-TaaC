# pyre-unsafe

"""
OSS Entry Point Package

This package provides the standalone OSS CLI entry point for running TAAC
tests. It is designed for external users and vendors who need to run TAAC
tests in non-Meta environments.

Main Components:
- oss_entry_point.py: Main CLI entry point
- cli_parser.py: Argument parsing
- oss_test_status.py: Test status enum
- oss_return_code.py: Exit code enum
- oss_test_result.py: Test result dataclass
- result_formatter.py: Result collection and summarization
- oss_test_executor.py: Test execution + retry logic
- oss_exceptions.py: OSS-specific exception classes
- oss_exception_classifier.py: Maps exceptions → OSSTestStatus + infra/user split
"""

__all__ = [
    "oss_entry_point",
    "cli_parser",
    "oss_test_status",
    "oss_return_code",
    "oss_test_result",
    "result_formatter",
    "oss_test_executor",
    "oss_exceptions",
    "oss_exception_classifier",
]
