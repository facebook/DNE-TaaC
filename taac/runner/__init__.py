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

OSS mode is established HERE, not in ``oss_entry_point.main()``.
``taac.utils.oss_taac_lib_utils`` evaluates ``TAAC_OSS`` at IMPORT time and
uses it to decide whether to import the Meta-internal ``neteng.netcastle``
logger. ``oss_entry_point`` imports the TAAC runtime at module scope, so by
the time ``main()`` ran the flag had already been read — assigning it there
was too late, and a real OSS container (no ``neteng`` package) died with
``ModuleNotFoundError: No module named 'neteng'``. It only appeared to work
because the container entrypoint and the customer both exported
``TAAC_OSS=1`` beforehand.

This package's ``__init__`` executes before any ``taac.*`` runtime module is
imported, which makes it the earliest correct place. ``setdefault`` (rather
than an unconditional assignment) preserves the documented ``-e TAAC_OSS=0``
override, matching ``docker/taac-entrypoint.sh``.
"""

import os

os.environ.setdefault("TAAC_OSS", "1")

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
