# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from taac.tasks.periodic_tasks import (
    CounterThresholdBreach,
    CounterThresholdTask,
)
from taac.health_check.health_check import types as hc_types

PERIODIC_TASKS_PATH = "neteng.test_infra.dne.taac.tasks.periodic_tasks"

_KEY = "bgpd.process.memory.rss.bytes"
_FIVE_GB = 5 * (1024**3)


def _driver_returning(value: float) -> MagicMock:
    driver = MagicMock(spec=["async_get_counter"])
    driver.async_get_counter = AsyncMock(return_value=value)
    return driver


class CounterThresholdTaskTest(unittest.IsolatedAsyncioTestCase):
    """fail_on_breach gating behavior of the counter-utilization periodic task."""

    def setUp(self) -> None:
        self.logger = MagicMock()
        self.task = CounterThresholdTask(hostname="bag012.ash6", logger=self.logger)

    def _params(self, fail_on_breach: bool) -> dict:
        return {
            "hostname": "bag012.ash6",
            "key": _KEY,
            "threshold": _FIVE_GB,
            "fail_on_breach": fail_on_breach,
        }

    async def _run_with_counter(self, value: float, fail_on_breach: bool) -> None:
        driver = _driver_returning(value)
        with patch(
            f"{PERIODIC_TASKS_PATH}.async_get_device_driver",
            AsyncMock(return_value=driver),
        ):
            await self.task.run(self._params(fail_on_breach))

    async def test_breach_raises_when_fail_on_breach(self) -> None:
        # A mid-run sample above threshold must raise so the worker terminates.
        with self.assertRaises(CounterThresholdBreach):
            await self._run_with_counter(_FIVE_GB + 1, fail_on_breach=True)

    async def test_breach_only_warns_when_flag_off(self) -> None:
        # Default (flag off): a breach is non-gating — warn + record for the
        # final check, never raise.
        await self._run_with_counter(_FIVE_GB + 1, fail_on_breach=False)
        self.logger.warning.assert_called()
        self.assertEqual(len(self.task._data), 1)

    async def test_within_threshold_no_raise(self) -> None:
        # Under threshold: no raise even with the flag on; sample recorded.
        await self._run_with_counter(_FIVE_GB - 1, fail_on_breach=True)
        self.assertEqual(len(self.task._data), 1)

    async def test_collection_error_swallowed_no_raise(self) -> None:
        # A collection failure must NOT be confused with a breach — it is logged
        # and swallowed (the fail_on_breach raise lives outside the try/except).
        with patch(
            f"{PERIODIC_TASKS_PATH}.async_get_device_driver",
            AsyncMock(side_effect=ConnectionError("device unreachable")),
        ):
            await self.task.run(self._params(fail_on_breach=True))
        self.logger.error.assert_called()
        self.assertEqual(len(self.task._data), 0)

        result = await self.task.run_final_check()
        if result is None:
            raise AssertionError("counter final check returned no result")
        self.assertEqual(hc_types.HealthCheckStatus.ERROR, result.status)
        self.assertIn("collection_errors=1", result.message)
        self.assertIn("ConnectionError: device unreachable", result.message)

    async def test_transient_collection_error_is_retained_after_valid_sample(
        self,
    ) -> None:
        params = self._params(fail_on_breach=False)
        with patch(
            f"{PERIODIC_TASKS_PATH}.async_get_device_driver",
            AsyncMock(side_effect=ConnectionError("transient")),
        ):
            await self.task._run(params)

        with patch(
            f"{PERIODIC_TASKS_PATH}.async_get_device_driver",
            AsyncMock(return_value=_driver_returning(_FIVE_GB - 1)),
        ):
            await self.task._run(params)

        result = await self.task.run_final_check()
        if result is None:
            raise AssertionError("counter final check returned no result")
        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertIn("collection_errors=1", result.message)
        self.assertIn("ConnectionError: transient", result.message)
