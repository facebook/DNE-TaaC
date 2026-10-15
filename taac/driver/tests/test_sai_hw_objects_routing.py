# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import asyncio
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from taac.driver.fboss_switch import FbossSwitch


def _client(name: str) -> MagicMock:
    client = MagicMock()
    client.listHwObjects = AsyncMock(return_value=name)

    @asynccontextmanager
    async def ctx():
        yield client

    return ctx()


class SaiHwObjectsRoutingTest(unittest.IsolatedAsyncioTestCase):
    """listHwObjects goes to the agent that serves it: sw_agent rejects it in split mode."""

    async def _hw_objects(self, multi_switch: bool) -> str:
        sw = FbossSwitch.__new__(FbossSwitch)
        sw.hostname = "dut"
        sw.logger = MagicMock()
        sw.async_is_multi_switch = AsyncMock(return_value=multi_switch)
        sw.get_hw_agent_client = AsyncMock(return_value=_client("hw_agent"))
        with patch.object(
            FbossSwitch, "async_agent_client", new_callable=PropertyMock, return_value=_client("sw_agent")
        ):
            return await sw.get_sai_hw_objects()

    async def test_split_agent_queries_hw_agent(self) -> None:
        self.assertEqual(await self._hw_objects(multi_switch=True), "hw_agent")

    async def test_monolithic_agent_queries_the_agent(self) -> None:
        self.assertEqual(await self._hw_objects(multi_switch=False), "sw_agent")

    async def test_run_mode_is_probed_once_for_concurrent_calls(self) -> None:
        sw = FbossSwitch.__new__(FbossSwitch)
        sw.hostname = "dut"
        sw.logger = MagicMock()

        async def _probe() -> bool:
            await asyncio.sleep(0)  # a real thrift probe yields to the other callers
            return True

        sw.async_is_multi_switch = AsyncMock(side_effect=_probe)
        sw.get_hw_agent_client = AsyncMock(side_effect=lambda **_: _client("hw_agent"))
        results = await asyncio.gather(*(sw.get_sai_hw_objects() for _ in range(50)))
        self.assertEqual(set(results), {"hw_agent"})
        self.assertEqual(sw.async_is_multi_switch.await_count, 1)

    async def test_a_failed_probe_is_shared_then_retried(self) -> None:
        sw = FbossSwitch.__new__(FbossSwitch)
        sw.hostname = "dut"
        sw.logger = MagicMock()

        async def _probe() -> bool:
            await asyncio.sleep(0)
            raise RuntimeError("agent down")

        sw.async_is_multi_switch = AsyncMock(side_effect=_probe)
        results = await asyncio.gather(
            *(sw.get_sai_hw_objects() for _ in range(50)), return_exceptions=True
        )
        self.assertTrue(all(isinstance(r, RuntimeError) for r in results))
        self.assertEqual(sw.async_is_multi_switch.await_count, 1)
        with self.assertRaises(RuntimeError):
            await sw.get_sai_hw_objects()
        self.assertEqual(sw.async_is_multi_switch.await_count, 2)


if __name__ == "__main__":
    unittest.main()
