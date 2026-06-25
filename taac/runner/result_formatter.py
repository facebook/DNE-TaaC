# pyre-unsafe

"""
Result Formatter

Collects and summarizes test results, formats output as JSON, JUnit XML, or text.
"""

import json
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, List

from taac.runner.oss_return_code import OSSReturnCode
from taac.runner.oss_test_result import OSSTestResult
from taac.runner.oss_test_status import OSSTestStatus


class OSSResultAggregator:
    """
    Aggregates and summarizes test results.

    Collects results from multiple test executions and provides
    summary statistics and exit code determination.
    """

    def __init__(self) -> None:
        """Initialize the result aggregator."""
        self.results: List[OSSTestResult] = []

    def add_result(self, result: OSSTestResult) -> None:
        """
        Add a test result to the aggregator.

        Args:
            result: Test result to add
        """
        self.results.append(result)

    def add_results(self, results: List[OSSTestResult]) -> None:
        """
        Add multiple test results to the aggregator.

        Args:
            results: List of test results to add
        """
        self.results.extend(results)

    @property
    def total_count(self) -> int:
        """Total number of test results."""
        return len(self.results)

    def count_by_status(self) -> Dict[OSSTestStatus, int]:
        """Count of results by status."""
        from collections import Counter

        counter = Counter(r.status for r in self.results)
        return dict(counter)

    @property
    def passed_count(self) -> int:
        """Number of passed tests."""
        return sum(1 for r in self.results if r.status == OSSTestStatus.PASSED)

    @property
    def failed_count(self) -> int:
        """Number of failed tests."""
        return sum(1 for r in self.results if r.status.failed)

    @property
    def skipped_count(self) -> int:
        """Number of skipped tests.

        Mirrors OSSTestStatus.is_skipped() — SKIPPED + OMITTED + NOT_RUN —
        so the suite-level `skipped=` attribute in to_junit_xml() agrees
        with the per-testcase `<skipped>` markup branch (which uses
        is_skipped()). Otherwise an OMITTED result would emit `<skipped>`
        but not be counted in the suite total, breaking
        `tests = passed + failed + errors + skipped`.
        """
        return sum(1 for r in self.results if r.status.is_skipped())

    @property
    def has_failures(self) -> bool:
        """Check if any results have failures."""
        return any(r.status.failed for r in self.results)

    @property
    def has_transient_errors(self) -> bool:
        """Check if any results are flagged transient (retry-able)."""
        return any(r.is_transient for r in self.results)

    @property
    def has_infra_errors(self) -> bool:
        """Check if any results landed on an infra-class status.

        Covers TESTBED_FAILED, CONNECTION_FAILED, SETUP_FAILED, plus
        transient-flagged ERROR results. Distinguished from
        has_transient_errors above — transient ⊂ infra, not equal.
        """
        return any(
            r.status
            in (
                OSSTestStatus.TESTBED_FAILED,
                OSSTestStatus.CONNECTION_FAILED,
                OSSTestStatus.SETUP_FAILED,
            )
            or r.is_transient
            for r in self.results
        )

    @property
    def all_passed(self) -> bool:
        """Check if all tests passed."""
        return all(r.status == OSSTestStatus.PASSED for r in self.results)

    def get_summary(self) -> Dict[str, int]:
        """
        Get summary statistics of all results.

        Returns:
            Dictionary with counts for each status
        """
        summary = {
            "total": self.total_count,
            "passed": self.passed_count,
            "failed": sum(1 for r in self.results if r.status == OSSTestStatus.FAILED),
            "error": sum(1 for r in self.results if r.status == OSSTestStatus.ERROR),
            "skipped": self.skipped_count,
            "setup_failed": sum(
                1 for r in self.results if r.status == OSSTestStatus.SETUP_FAILED
            ),
            "teardown_failed": sum(
                1 for r in self.results if r.status == OSSTestStatus.TEARDOWN_FAILED
            ),
            "testbed_failed": sum(
                1 for r in self.results if r.status == OSSTestStatus.TESTBED_FAILED
            ),
            "connection_failed": sum(
                1 for r in self.results if r.status == OSSTestStatus.CONNECTION_FAILED
            ),
            "timeout": sum(
                1 for r in self.results if r.status == OSSTestStatus.TIMEOUT
            ),
            "retried": sum(
                1 for r in self.results if r.status == OSSTestStatus.RETRIED
            ),
        }

        return summary

    def get_exit_code(self) -> OSSReturnCode:
        """
        Determine the appropriate exit code based on results.

        Returns:
            Exit code for the CLI
        """
        if not self.results:
            return OSSReturnCode.NO_TESTS_FOUND

        # Real test failures (FAILED / non-transient ERROR) dominate
        # infra-class signals: a run of 49 FAILED + 1 TIMEOUT should
        # exit TEST_CASE_FAILURE (2), not TIMEOUT_ERROR (131). Callers
        # keying on "2 == real test regression, 128+ == environment"
        # must not see real regressions masked by an infra blip on a
        # sibling result.
        #
        # Transient-flagged ERRORs are excluded from this check —
        # they're infra-class (retry-able), and routing them through
        # TEST_CASE_FAILURE would shadow TRANSIENT_ERROR (130).
        # Testbed/connection errors land in their own statuses
        # (TESTBED_FAILED / CONNECTION_FAILED), so they're not in this
        # tuple either; classify_exception produces those directly.
        if any(
            result.status == OSSTestStatus.FAILED
            or (result.status == OSSTestStatus.ERROR and not result.is_transient)
            for result in self.results
        ):
            return OSSReturnCode.TEST_CASE_FAILURE

        # No real test failure — map remaining infra-class signals to
        # their dedicated codes. Order is specific → generic.
        if any(
            result.status == OSSTestStatus.TESTBED_FAILED for result in self.results
        ):
            return OSSReturnCode.TESTBED_ERROR
        if any(
            result.status == OSSTestStatus.CONNECTION_FAILED for result in self.results
        ):
            return OSSReturnCode.CONNECTION_ERROR
        if any(result.status == OSSTestStatus.TIMEOUT for result in self.results):
            return OSSReturnCode.TIMEOUT_ERROR
        if any(result.is_transient for result in self.results):
            return OSSReturnCode.TRANSIENT_ERROR
        if any(result.status == OSSTestStatus.SETUP_FAILED for result in self.results):
            return OSSReturnCode.INFRA_ERROR

        # Catch-all for any remaining status.failed (e.g. TEARDOWN_FAILED)
        # that didn't match a more specific bucket above.
        if any(result.status.failed for result in self.results):
            return OSSReturnCode.TEST_CASE_FAILURE

        # All tests passed or skipped
        return OSSReturnCode.SUCCESS

    def to_json(self, filepath: str) -> None:
        """
        Write results to a JSON file.

        Args:
            filepath: Path to the output JSON file
        """
        data = {
            "summary": self.get_summary(),
            "results": [result.to_dict() for result in self.results],
        }

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

    def to_junit_xml(self, filepath: str) -> None:
        """
        Write results to a JUnit XML file.

        Args:
            filepath: Path to the output JUnit XML file
        """
        summary = self.get_summary()

        # Create root testsuites element. TIMEOUT folds into the `errors`
        # bucket (mirrors the `<error>` element emitted per-testcase below)
        # so the suite-level totals stay consistent with both the per-test
        # markup and get_exit_code (where TIMEOUT now routes to TIMEOUT_ERROR).
        errors_count = (
            summary["error"]
            + summary["setup_failed"]
            + summary["teardown_failed"]
            + summary["timeout"]
        )
        testsuites = ET.Element("testsuites")
        testsuites.set("tests", str(summary["total"]))
        testsuites.set("failures", str(summary["failed"]))
        testsuites.set("errors", str(errors_count))
        testsuites.set("skipped", str(summary["skipped"]))

        # Create a testsuite element
        testsuite = ET.SubElement(testsuites, "testsuite")
        testsuite.set("name", "TAAC_OSS_Tests")
        testsuite.set("tests", str(summary["total"]))
        testsuite.set("failures", str(summary["failed"]))
        testsuite.set("errors", str(errors_count))
        testsuite.set("skipped", str(summary["skipped"]))
        testsuite.set("timestamp", datetime.now().isoformat())

        # Add testcase elements for each result
        for result in self.results:
            testcase = ET.SubElement(testsuite, "testcase")
            testcase.set("name", f"{result.playbook}_{result.dut}")
            testcase.set("classname", result.test_config)

            if result.duration:
                testcase.set("time", f"{result.duration:.3f}")

            # Add failure/error/skipped elements based on status
            if result.status == OSSTestStatus.FAILED:
                failure = ET.SubElement(testcase, "failure")
                failure.set("message", result.message or "Test failed")
                if result.traceback:
                    failure.text = result.traceback
            elif result.status in (
                OSSTestStatus.ERROR,
                OSSTestStatus.SETUP_FAILED,
                OSSTestStatus.TEARDOWN_FAILED,
                OSSTestStatus.TIMEOUT,
            ):
                error = ET.SubElement(testcase, "error")
                error.set("message", result.message or "Test error")
                if result.traceback:
                    error.text = result.traceback
            elif result.status.is_skipped():
                skipped = ET.SubElement(testcase, "skipped")
                skipped.set("message", result.message or "Test skipped")

        # Write to file
        tree = ET.ElementTree(testsuites)
        ET.indent(tree, space="  ")  # Pretty-print
        tree.write(filepath, encoding="utf-8", xml_declaration=True)

    def print_summary(self, logger) -> None:
        """
        Print a summary of results to the logger.

        Args:
            logger: Logger instance to use for output
        """
        summary = self.get_summary()

        logger.info("=" * 60)
        logger.info("TEST SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Total Tests: {summary['total']}")
        logger.info(f"Passed: {summary['passed']}")
        logger.info(f"Failed: {summary['failed']}")
        logger.info(f"Error: {summary['error']}")
        logger.info(f"Setup Failed: {summary['setup_failed']}")
        logger.info(f"Teardown Failed: {summary['teardown_failed']}")
        logger.info(f"Timeout: {summary['timeout']}")
        logger.info(f"Skipped: {summary['skipped']}")
        logger.info("=" * 60)

        # Print individual results
        for result in self.results:
            logger.info(str(result))
