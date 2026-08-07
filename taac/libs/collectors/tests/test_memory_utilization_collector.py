# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import typing as t
import unittest
from unittest.mock import AsyncMock, MagicMock

from taac.libs.collectors.memory_utilization_collector import (
    MemoryUtilizationCollector,
)


def _make_driver(mem_by_service: t.Dict[str, t.Any]) -> MagicMock:
    driver = MagicMock()

    async def _run(cmd: str) -> str:
        units = cmd.split("systemctl show ", 1)[1].split(" -p ")[0].split()
        blocks = []
        for unit in units:
            if unit in mem_by_service:
                blocks.append(
                    f"Id={unit}.service\nLoadState=loaded\nActiveState=active\n"
                    f"MemoryCurrent={mem_by_service[unit]}"
                )
            else:
                blocks.append(
                    f"Id={unit}.service\nLoadState=not-found\n"
                    f"ActiveState=inactive\nMemoryCurrent="
                )
        return "\n\n".join(blocks)

    driver.async_run_cmd_on_shell = AsyncMock(side_effect=_run)
    return driver


class TestMemoryUtilizationCollector(unittest.IsolatedAsyncioTestCase):
    async def test_poll_stores_bytes_directly(self) -> None:
        """Memory stores the raw MemoryCurrent value -- no delta."""
        driver = _make_driver({"agent": 100_000_000})
        collector = MemoryUtilizationCollector(
            driver=driver, services=["agent"], host="dut1", tmp_path="/dev/null"
        )
        await collector._poll_once()
        self.assertEqual(len(collector.rows), 1)
        self.assertEqual(collector.rows[0].per_service["agent"], 100_000_000)

    async def test_not_set_memory_current_produces_none(self) -> None:
        """systemd reports '[not set]' for MemoryCurrent when cgroup is missing."""
        driver = MagicMock()
        driver.async_run_cmd_on_shell = AsyncMock(
            return_value=(
                "Id=agent.service\nLoadState=loaded\nActiveState=active\n"
                "MemoryCurrent=[not set]"
            )
        )
        collector = MemoryUtilizationCollector(
            driver=driver, services=["agent"], host="dut1", tmp_path="/dev/null"
        )
        await collector._poll_once()
        self.assertIsNone(collector.rows[0].per_service["agent"])


if __name__ == "__main__":
    unittest.main()
