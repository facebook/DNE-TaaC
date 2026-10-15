# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from taac.tasks.periodic_tasks import ThriftStressPeriodicTask
from taac.tasks.thrift_stress_payloads import READ_ONLY_FBOSS_APIS


def _make_fboss_driver() -> MagicMock:
    names = [c.method for c in READ_ONLY_FBOSS_APIS]
    driver = MagicMock(spec=names)
    for name in names:
        setattr(driver, name, AsyncMock(return_value=42))
    return driver


async def _hang(*args, **kwargs):
    await asyncio.sleep(3600)


async def _run(driver) -> dict:
    task = ThriftStressPeriodicTask(hostname="dut", logger=MagicMock())
    with patch(
        "taac.tasks.periodic_tasks.async_get_device_driver",
        AsyncMock(return_value=driver),
    ):
        await task.run({"hostname": "dut", "requests_per_api": 2, "burst_timeout_s": 1.0})
    burst = next(iter(task._data.values()))
    return {k: burst[k] for k in ("total", "success", "failures", "timed_out")}


class ThriftStressBurstTimeoutTest(unittest.IsolatedAsyncioTestCase):
    """A burst that times out keeps the results of the calls that finished."""

    async def test_one_hung_call_does_not_erase_the_others(self) -> None:
        driver = _make_fboss_driver()
        driver.get_bgp_table_length = AsyncMock(side_effect=_hang)
        driver.get_bgp_sessions_count = AsyncMock(side_effect=RuntimeError("rate limited"))
        # 7 APIs * 2 = 14: 2 hang, 2 raise, 10 return.
        self.assertEqual(
            await _run(driver), {"total": 14, "success": 10, "failures": 2, "timed_out": 2}
        )

    async def test_fully_hung_burst_is_all_timed_out(self) -> None:
        driver = _make_fboss_driver()
        for call in READ_ONLY_FBOSS_APIS:
            setattr(driver, call.method, AsyncMock(side_effect=_hang))
        self.assertEqual(
            await _run(driver), {"total": 14, "success": 0, "failures": 0, "timed_out": 14}
        )

    async def test_a_call_that_cancels_itself_counts_as_a_failure(self) -> None:
        driver = _make_fboss_driver()
        driver.get_bgp_sessions_count = AsyncMock(side_effect=asyncio.CancelledError())
        self.assertEqual(
            await _run(driver), {"total": 14, "success": 12, "failures": 2, "timed_out": 0}
        )

    async def test_cancelling_the_burst_cancels_its_calls(self) -> None:
        driver = _make_fboss_driver()
        for call in READ_ONLY_FBOSS_APIS:
            setattr(driver, call.method, AsyncMock(side_effect=_hang))
        task = ThriftStressPeriodicTask(hostname="dut", logger=MagicMock())
        with patch(
            "taac.tasks.periodic_tasks.async_get_device_driver",
            AsyncMock(return_value=driver),
        ):
            burst = asyncio.ensure_future(
                task.run({"hostname": "dut", "requests_per_api": 2, "burst_timeout_s": 60.0})
            )
            await asyncio.sleep(0.1)
            burst.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await burst
        await asyncio.sleep(0)
        current = asyncio.current_task()
        self.assertFalse([t for t in asyncio.all_tasks() if t is not current and not t.done()])


if __name__ == "__main__":
    unittest.main()
