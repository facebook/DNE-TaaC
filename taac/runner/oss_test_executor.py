# pyre-unsafe

"""
OSS Test Executor

Executes TAAC tests and produces OSSTestResult objects. Wraps
TaacRunner so each per-(playbook, dut) call is captured as an
individual OSSTestResult, with exception → status mapping centralized
in classify_exception().
"""

import asyncio
import time
import traceback
from typing import List

from taac.runner.oss_exception_classifier import (
    classify_exception,
)
from taac.runner.oss_exceptions import (
    OSSConfigError,
    OSSInfrastructureError,
    OSSSetupError,
    OSSTeardownError,
    OSSTestbedError,
    OSSTestExecutionError,
    OSSTransientError,
)
from taac.runner.oss_test_result import OSSTestResult
from taac.runner.oss_test_status import OSSTestStatus
from taac.test_as_a_config import types as taac_types


class OSSTestExecutor:
    """
    Executes TAAC tests and produces OSSTestResult objects.

    Wraps TaacRunner and handles exception classification. Exception →
    status mapping lives in classify_exception()
    (oss_exception_classifier.py) — single source of truth so the
    inline-ladder version and the classifier can't drift.
    """

    def __init__(self, taac_runner, logger):
        """
        Initialize the test executor.

        Args:
            taac_runner: TaacRunner instance to execute tests
            logger: Logger instance for output
        """
        self._taac_runner = taac_runner
        self._logger = logger

    async def execute_playbook(
        self,
        playbook: taac_types.Playbook,
        dut: str,
        test_config: str,
    ) -> OSSTestResult:
        """
        Execute a single playbook against a DUT.

        Async coroutine. Caller is expected to drive this from the same
        event loop that drove async_test_setUp / async_test_tearDown so
        resources (connection pools, async context managers) created by
        setUp survive to run_tests + tearDown.

        classify_exception() is the single source of truth for
        exception → status mapping (see oss_exception_classifier.py).
        On any escape, log at the right level for the resulting status
        (errors at ERROR, transients at WARNING) and capture
        exception_type / message / traceback.

        Args:
            playbook: Playbook to execute
            dut: Device under test hostname
            test_config: Test config name

        Returns:
            OSSTestResult for this playbook execution
        """
        start_time = time.time()
        status = OSSTestStatus.PASSED
        message = ""
        stacktrace = ""
        exception_type = None
        exception_message = None
        is_transient = False

        try:
            self._logger.info(f"Executing playbook '{playbook.name}' on {dut}")
            # Call run_tests one (playbook, dut) at a time rather than batching
            # the whole grid into a single run_tests(all_playbooks, all_duts):
            # batching collapses every cell of the grid into TaacRunner's
            # collective pass/fail, so a single failure would mark every cell
            # FAILED. The per-cell call surfaces individual status / duration /
            # exception for each (playbook, dut) — what the OSSTestResult model
            # is designed to capture. Validated end-to-end via the live-device
            # smoke (uname against fboss101 + fboss102, 2/2 PASSED).
            await self._taac_runner.run_tests([playbook], [dut])
            self._logger.info(f"Playbook '{playbook.name}' PASSED on {dut}")
        except Exception as e:
            status, is_transient = classify_exception(e)
            exception_type = type(e).__name__
            exception_message = str(e)
            stacktrace = traceback.format_exc()
            message = f"{exception_type}: {e}"
            log = self._logger.warning if is_transient else self._logger.error
            log(f"Playbook '{playbook.name}' {status.name} on {dut}: {e}")

        duration = time.time() - start_time

        return OSSTestResult(
            test_config=test_config,
            playbook=playbook.name,
            dut=dut,
            status=status,
            duration=duration,
            message=message,
            traceback=stacktrace,
            exception_type=exception_type,
            exception_message=exception_message,
            is_transient=is_transient,
            log_file=self._logger.get_log_file()
            if hasattr(self._logger, "get_log_file")
            else None,
        )

    @staticmethod
    def map_exception_to_status(exception: Exception) -> OSSTestStatus:
        """
        Map an exception to a test status.

        Args:
            exception: The exception that was raised

        Returns:
            Appropriate test status for the exception
        """
        if isinstance(exception, OSSSetupError):
            return OSSTestStatus.SETUP_FAILED
        elif isinstance(exception, OSSTeardownError):
            return OSSTestStatus.TEARDOWN_FAILED
        elif isinstance(exception, (OSSInfrastructureError, OSSTestbedError)):
            return OSSTestStatus.SETUP_FAILED
        elif isinstance(exception, OSSConfigError):
            return OSSTestStatus.ERROR
        elif isinstance(exception, OSSTestExecutionError):
            return OSSTestStatus.FAILED
        elif isinstance(exception, asyncio.TimeoutError):
            return OSSTestStatus.TIMEOUT
        elif isinstance(exception, AssertionError):
            return OSSTestStatus.FAILED
        else:
            return OSSTestStatus.ERROR

    @staticmethod
    async def execute_with_exception_handling(
        result: OSSTestResult,
        coro,
        logger,
    ) -> OSSTestResult:
        """
        Execute a coroutine and handle exceptions.

        Args:
            result: Test result object to update
            coro: Coroutine to execute
            logger: Logger instance

        Returns:
            Updated test result
        """
        try:
            await coro
            result.mark_complete(OSSTestStatus.PASSED, "Test completed successfully")
        except Exception as e:
            status = OSSTestExecutor.map_exception_to_status(e)
            tb = traceback.format_exc()
            result.exception = e
            result.traceback = tb
            result.mark_complete(status, str(e))
            logger.error(f"Test failed with {status}: {e}")
            logger.debug(f"Traceback:\n{tb}")

        return result

    @staticmethod
    def execute_with_retry(
        func,
        max_retries: int = 0,
        logger=None,
    ):
        """
        Execute a function with retry logic for transient errors.

        Args:
            func: Function to execute
            max_retries: Maximum number of retries
            logger: Logger instance

        Returns:
            Result of the function

        Raises:
            The last exception if all retries fail
        """
        last_exception = None

        # Clamp negatives to 0 so a stray `--retry -1` doesn't fall
        # through `range(0)` straight into `raise last_exception` with
        # last_exception still None (which raises TypeError).
        max_retries = max(0, max_retries)
        for attempt in range(max_retries + 1):
            try:
                return func()
            except OSSTransientError as e:
                last_exception = e
                if attempt < max_retries:
                    if logger:
                        logger.warning(
                            f"Transient error on attempt {attempt + 1}/{max_retries + 1}: {e}"
                        )
                        logger.info(f"Retrying...")
                else:
                    if logger:
                        logger.error(f"All {max_retries + 1} attempts failed")
            except Exception as e:
                # Non-transient errors should not be retried
                raise

        # If we get here, all retries failed
        raise last_exception
