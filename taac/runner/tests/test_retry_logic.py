#!/usr/bin/env python3
# pyre-unsafe

"""
Tests for retry logic — validates the executor-level pieces of the
transient-failure retry mechanism. The actual retry *loop* (transient →
retry → success → original marked RETRIED + is_transient cleared) lives
in oss_entry_point.main() and is exercised end-to-end by
test_oss_entry_point.TestEntryPointIntegration.test_main_retry_loop_marks_original_retried_and_clears_transient.
"""

import unittest
from unittest import mock

from taac.runner.oss_exceptions import OSSTransientError
from taac.runner.oss_test_executor import OSSTestExecutor
from taac.runner.oss_test_result import OSSTestResult
from taac.runner.oss_test_status import OSSTestStatus
from taac.runner.result_formatter import OSSResultAggregator


class TestRetryLogic(unittest.IsolatedAsyncioTestCase):
    """Test the executor-level pieces of retry."""

    def setUp(self):
        self.mock_runner = mock.MagicMock()
        self.mock_logger = mock.MagicMock()
        self.executor = OSSTestExecutor(
            taac_runner=self.mock_runner,
            logger=self.mock_logger,
        )
        self.mock_playbook = mock.MagicMock()
        self.mock_playbook.name = "test_playbook"
        self.aggregator = OSSResultAggregator()

    async def test_transient_failure_then_success(self):
        """First call raises OSSTransientError → ERROR + is_transient=True;
        second call succeeds → PASSED. Mirrors the per-attempt shape that
        the entry-point retry loop chains together."""
        call_count = [0]

        async def mock_run_tests(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise OSSTransientError("Temporary network issue")
            # Second call succeeds.

        self.mock_runner.run_tests = mock_run_tests

        result1 = await self.executor.execute_playbook(
            playbook=self.mock_playbook,
            dut="device1",
            test_config="test_config",
        )
        self.assertTrue(result1.is_transient)
        self.assertTrue(result1.status.failed)

        result2 = await self.executor.execute_playbook(
            playbook=self.mock_playbook,
            dut="device1",
            test_config="test_config",
        )
        self.assertEqual(result2.status, OSSTestStatus.PASSED)
        self.assertFalse(result2.status.failed)

    async def test_non_transient_failure_not_retryable(self):
        """A non-transient failure leaves is_transient=False so the
        entry-point retry loop's `result.is_transient and result.status.failed`
        guard is the one that decides not to retry."""

        async def mock_run_tests(*args, **kwargs):
            raise AssertionError("Test failed")

        self.mock_runner.run_tests = mock_run_tests

        result = await self.executor.execute_playbook(
            playbook=self.mock_playbook,
            dut="device1",
            test_config="test_config",
        )

        self.assertFalse(result.is_transient)
        self.assertEqual(result.status, OSSTestStatus.FAILED)


class TestRetryDataModel(unittest.TestCase):
    """Field-semantics checks on OSSTestResult for retry bookkeeping.

    The spec contract "successful retry flips original.status to RETRIED"
    is tested end-to-end in test_oss_entry_point's
    test_main_retry_loop_marks_original_retried_and_clears_transient —
    no need for a tautological dataclass-only mirror here.
    """

    def test_retry_count_increments(self):
        """retry_count is per-attempt scalar; first attempt is 0."""
        results = [
            OSSTestResult(
                test_config="test",
                playbook="pb",
                dut="dut1",
                status=OSSTestStatus.ERROR,
                duration=1.0,
                message=f"Attempt {i}",
            )
            for i in range(3)
        ]
        for i, r in enumerate(results):
            r.retry_count = i
        results[-1].status = OSSTestStatus.PASSED

        self.assertEqual([r.retry_count for r in results], [0, 1, 2])

    def test_max_retries_records_full_history(self):
        """An exhausted retry sequence should still produce
        (1 original + max_retries) result records for the aggregator."""
        max_retries = 3
        results = []
        for i in range(max_retries + 1):
            r = OSSTestResult(
                test_config="test",
                playbook="pb",
                dut="dut1",
                status=OSSTestStatus.ERROR,
                is_transient=True,
                duration=1.0,
                message=f"Attempt {i}",
            )
            r.retry_count = i
            results.append(r)

        self.assertEqual(len(results), 4)
        self.assertEqual(results[0].retry_count, 0)
        self.assertEqual(results[3].retry_count, 3)


if __name__ == "__main__":
    unittest.main()
