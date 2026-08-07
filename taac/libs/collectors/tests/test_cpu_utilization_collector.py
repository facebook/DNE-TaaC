# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import typing as t
import unittest
from unittest.mock import AsyncMock, MagicMock

from taac.libs.collectors.cpu_utilization_collector import (
    CpuUtilizationCollector,
)


def _make_driver(cpu_ns_by_service: t.Dict[str, t.Any]) -> MagicMock:
    driver = MagicMock()

    async def _run(cmd: str) -> str:
        units = cmd.split("systemctl show ", 1)[1].split(" -p ")[0].split()
        blocks = []
        for unit in units:
            if unit in cpu_ns_by_service:
                blocks.append(
                    f"Id={unit}.service\nLoadState=loaded\nActiveState=active\n"
                    f"CPUUsageNSec={cpu_ns_by_service[unit]}"
                )
            else:
                blocks.append(
                    f"Id={unit}.service\nLoadState=not-found\n"
                    f"ActiveState=inactive\nCPUUsageNSec="
                )
        return "\n\n".join(blocks)

    driver.async_run_cmd_on_shell = AsyncMock(side_effect=_run)
    return driver


class TestCpuUtilizationCollector(unittest.IsolatedAsyncioTestCase):
    async def test_first_poll_produces_none_values(self) -> None:
        """First poll has no baseline -- per_service values should all be None."""
        driver = _make_driver({"agent": 1_000_000_000})
        collector = CpuUtilizationCollector(
            driver=driver, services=["agent"], host="dut1", tmp_path="/dev/null"
        )
        await collector._poll_once()
        self.assertEqual(len(collector.rows), 1)
        self.assertIsNone(collector.rows[0].per_service["agent"])

    async def test_second_poll_computes_delta_pct(self) -> None:
        """Second poll computes CPU% from the ns delta."""
        driver = _make_driver({"agent": 1_000_000_000})
        collector = CpuUtilizationCollector(
            driver=driver, services=["agent"], host="dut1", tmp_path="/dev/null"
        )
        await collector._poll_once()

        collector.driver = _make_driver({"agent": 6_000_000_000})
        await collector._poll_once()

        row = collector.rows[1]
        # 5e9 ns delta over the clamped 1.0s minimum wall_delta -> 500%.
        self.assertEqual(row.per_service["agent"], 500.0)

    async def test_ssh_error_resets_baseline(self) -> None:
        driver = _make_driver({"agent": 1_000_000_000})
        collector = CpuUtilizationCollector(
            driver=driver, services=["agent"], host="dut1", tmp_path="/dev/null"
        )
        await collector._poll_once()

        collector.driver.async_run_cmd_on_shell = AsyncMock(
            side_effect=RuntimeError("SSH down")
        )
        await collector._poll_once()

        collector.driver = _make_driver({"agent": 2_000_000_000})
        await collector._poll_once()
        self.assertIsNone(collector.rows[2].per_service["agent"])

    async def test_stale_baseline_after_long_gap_is_dropped(self) -> None:
        """A gap much larger than the poll interval (e.g. a poll timeout ate
        a cycle) must reset the baseline instead of diluting the delta over
        the whole gap."""
        driver = _make_driver({"agent": 1_000_000_000})
        collector = CpuUtilizationCollector(
            driver=driver,
            services=["agent"],
            host="dut1",
            tmp_path="/dev/null",
            interval_sec=5.0,
        )
        await collector._poll_once()
        self.assertIsNotNone(collector._last_wall)
        # simulate a large gap since the last poll
        collector._last_wall = t.cast(float, collector._last_wall) - 1000

        collector.driver = _make_driver({"agent": 6_000_000_000})
        await collector._poll_once()
        self.assertIsNone(collector.rows[1].per_service["agent"])


if __name__ == "__main__":
    unittest.main()
