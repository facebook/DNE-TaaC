# pyre-unsafe

"""
OSS Exception Classifier

Maps raised exceptions to OSSTestStatus values and classifies them as
infrastructure vs user errors. Kept in its own module (separate from
oss_exceptions.py / oss_test_status.py) so the dependency direction
stays one-way — both source-of-truth modules can be imported here
without either of them needing to import the other.
"""

import asyncio
import unittest
from typing import Tuple

from taac.constants import TestCaseFailure
from taac.runner.oss_exceptions import (
    OSSConnectionError,
    OSSInfrastructureError,
    OSSSetupError,
    OSSTeardownError,
    OSSTestbedError,
    OSSTransientError,
)
from taac.runner.oss_test_status import OSSTestStatus


def get_exception_to_status_map():
    """Get the exception-to-status mapping dict.

    Order is significant — classify_exception iterates this dict and the
    first isinstance() match wins. Put narrower types before broader ones
    (e.g. TestCaseFailure before AssertionError) when an exception class
    could be matched by multiple entries.
    """
    return {
        # TAAC playbooks signal a failed health-check / validation by
        # raising TestCaseFailure (taac/constants.py) — NOT AssertionError.
        # Without this entry, every real test failure falls through to
        # the unknown-Exception branch and gets reported as ERROR, which
        # then JUnit-emits as `<error>` instead of `<failure>`. That makes
        # CI dashboards misclassify genuine regressions as infra flakes.
        TestCaseFailure: OSSTestStatus.FAILED,
        AssertionError: OSSTestStatus.FAILED,
        unittest.SkipTest: OSSTestStatus.SKIPPED,
        # Both the builtin TimeoutError and asyncio.TimeoutError. They
        # alias on Python 3.11+ but are distinct classes on 3.10 and
        # earlier — asyncio raises its own subclass, which wouldn't
        # match a bare `TimeoutError` isinstance check on the older
        # interpreter. Listing both keeps the map runtime-version-
        # agnostic.
        TimeoutError: OSSTestStatus.TIMEOUT,
        asyncio.TimeoutError: OSSTestStatus.TIMEOUT,
        # Infra-class exceptions get dedicated statuses so get_exit_code
        # can route them to the 128+ codes rather than the generic
        # ERROR → TEST_CASE_FAILURE (2) bucket reserved for real test
        # regressions.
        OSSTestbedError: OSSTestStatus.TESTBED_FAILED,
        OSSConnectionError: OSSTestStatus.CONNECTION_FAILED,
        # Transient stays on ERROR — the is_transient flag (set
        # separately in classify_exception below) is the routing signal,
        # and get_exit_code excludes transient-flagged ERRORs from the
        # FAILED/ERROR check so TRANSIENT_ERROR (130) is reachable.
        OSSTransientError: OSSTestStatus.ERROR,
        OSSSetupError: OSSTestStatus.SETUP_FAILED,
        OSSTeardownError: OSSTestStatus.TEARDOWN_FAILED,
    }


def classify_exception(exc: Exception) -> Tuple[OSSTestStatus, bool]:
    """
    Classify an exception into a test status.

    Args:
        exc: The exception to classify

    Returns:
        Tuple of (OSSTestStatus, is_transient)
    """
    is_transient = isinstance(exc, OSSTransientError)

    exception_to_status = get_exception_to_status_map()
    for exc_type, status in exception_to_status.items():
        if isinstance(exc, exc_type):
            return (status, is_transient)

    # Default: unknown exceptions are ERROR
    return (OSSTestStatus.ERROR, False)


def is_infra_error(exc: Exception) -> bool:
    """
    Determine if exception is an infrastructure error vs user error.

    Infrastructure errors:
    - OSSTestbedError (device issues)
    - OSSConnectionError (network issues)
    - OSSTransientError (temporary failures)
    - OSSInfrastructureError (general infra issues)

    User errors:
    - AssertionError (test logic failure)
    - ValueError, TypeError (bad test code)

    Args:
        exc: The exception to classify

    Returns:
        True if this is an infrastructure error, False otherwise
    """
    INFRA_EXCEPTIONS = (
        OSSTestbedError,
        OSSConnectionError,
        OSSTransientError,
        OSSInfrastructureError,
        OSSSetupError,
        OSSTeardownError,
        # builtin ConnectionError (and its subclasses ConnectionResetError /
        # ConnectionRefusedError / etc.). Network code in stdlib + libraries
        # raises this, not OSSConnectionError; classify it as infra so it
        # doesn't get misrouted as a user error.
        ConnectionError,
        OSError,
        IOError,
    )
    return isinstance(exc, INFRA_EXCEPTIONS)
