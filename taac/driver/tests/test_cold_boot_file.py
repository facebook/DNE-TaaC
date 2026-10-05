#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""The commands that set and clear the agent's one-shot cold-boot flags.

Which files those are depends on the DUT: the monolithic wedge_agent wrapper
reads ``cold_boot_once_<idx>``, while the split agents each read their own
flag and ignore that one entirely. See FBOSS_COLD_BOOT_ONCE_FILE in
``taac/constants.py``.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from neteng.fboss.ctrl.types import BootType
from taac.constants import (
    FBOSS_COLD_BOOT_ONCE_FILE,
    FBOSS_COLD_BOOT_ONCE_GLOB,
    FBOSS_COLD_BOOT_ONCE_GLOBS,
    FBOSS_SPLIT_SW_COLD_BOOT_ONCE_FILE,
    FBOSS_WARM_BOOT_DIR,
)
from taac.driver.driver_constants import FbossSystemctlServiceName
from taac.driver.fboss_switch import FbossSwitch


class ColdBootFileTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.switch = FbossSwitch("dut1", logger=MagicMock())
        # Held separately from the attribute, which is typed as a real method:
        # the mock's await assertions are only reachable through this handle.
        self.run_cmd = AsyncMock()
        self.switch.async_run_cmd_on_shell = self.run_cmd

    def _touched_files(self) -> list:
        self.run_cmd.assert_awaited_once()
        await_args = self.run_cmd.await_args
        if await_args is None:
            raise AssertionError("async_run_cmd_on_shell was never awaited")
        cmd = await_args.args[0]
        prefix = "touch "
        self.assertTrue(cmd.startswith(prefix), cmd)
        return cmd[len(prefix) :].split()

    async def test_create_touches_the_flag_on_a_monolithic_dut(self) -> None:
        # Regression: this command used to end in a dangling '&&', a shell
        # syntax error, so the touch never ran and nothing raised.
        # The monolithic path is the fallback taken when the agent cannot
        # report NPU indices, so drive that seam directly. Mocking
        # async_is_multi_switch alone leaves async_get_hw_agent_switch_indices
        # live, and whether it happens to raise depends on the environment --
        # which makes this assertion pass or fail by accident.
        self.switch.async_is_multi_switch = AsyncMock(return_value=False)
        self.switch.async_get_hw_agent_switch_indices = AsyncMock(
            side_effect=Exception("monolithic DUT: no hw agent indices")
        )
        await self.switch.async_create_cold_boot_file()
        self.assertEqual(self._touched_files(), [FBOSS_COLD_BOOT_ONCE_FILE])

    async def test_create_touches_a_flag_per_agent_on_a_split_dut(self) -> None:
        """The fix: the monolithic flag alone leaves a split DUT warm-booting."""
        self.switch.async_is_multi_switch = AsyncMock(return_value=True)
        self.switch.async_get_hw_agent_switch_indices = AsyncMock(return_value=[0])
        await self.switch.async_create_cold_boot_file()
        touched = self._touched_files()
        self.assertEqual(
            touched,
            [
                FBOSS_SPLIT_SW_COLD_BOOT_ONCE_FILE,
                f"{FBOSS_WARM_BOOT_DIR}/hw_cold_boot_once_0",
            ],
        )
        self.assertNotIn(FBOSS_COLD_BOOT_ONCE_FILE, touched)

    async def test_create_covers_every_npu_on_a_multi_npu_dut(self) -> None:
        """A hw agent left without a flag warm boots while the rest go cold."""
        self.switch.async_is_multi_switch = AsyncMock(return_value=True)
        self.switch.async_get_hw_agent_switch_indices = AsyncMock(return_value=[0, 1])
        await self.switch.async_create_cold_boot_file()
        self.assertEqual(
            self._touched_files(),
            [
                FBOSS_SPLIT_SW_COLD_BOOT_ONCE_FILE,
                f"{FBOSS_WARM_BOOT_DIR}/hw_cold_boot_once_0",
                f"{FBOSS_WARM_BOOT_DIR}/hw_cold_boot_once_1",
            ],
        )

    async def test_remove_clears_monolithic_and_split_flags(self) -> None:
        await self.switch.async_remove_cold_boot_file()
        self.run_cmd.assert_awaited_once_with(
            f"rm -f {' '.join(FBOSS_COLD_BOOT_ONCE_GLOBS)}"
        )

    async def test_remove_does_not_need_a_live_agent(self) -> None:
        """Globbed, so clearing works with the agent down -- when it matters most."""
        self.switch.async_is_multi_switch = AsyncMock(
            side_effect=AssertionError("must not probe the agent")
        )
        await self.switch.async_remove_cold_boot_file()
        self.run_cmd.assert_awaited_once()

    def test_globs_leave_the_qsfp_service_flag_alone(self) -> None:
        """qsfp_service owns cold_boot_once_qsfp_service in the same dir."""
        for glob in FBOSS_COLD_BOOT_ONCE_GLOBS:
            self.assertNotIn("qsfp", glob)

    def test_the_sw_glob_catches_the_legacy_flag(self) -> None:
        """`sw_cold_boot_once_0` is probed but never self-cleared by the agent."""
        self.assertTrue(
            any(
                glob.endswith("sw_cold_boot_once*")
                for glob in FBOSS_COLD_BOOT_ONCE_GLOBS
            )
        )

    def test_the_monolithic_glob_is_still_cleared(self) -> None:
        self.assertIn(FBOSS_COLD_BOOT_ONCE_GLOB, FBOSS_COLD_BOOT_ONCE_GLOBS)

    async def test_hw_agent_restart_flags_only_that_hw_agent(self) -> None:
        """An unconsumed sw/hw1 flag would cold boot their next warm restart."""
        self.switch.async_get_hw_agent_switch_indices = AsyncMock(
            side_effect=AssertionError("must not enumerate NPUs")
        )
        await self.switch.async_create_cold_boot_file(
            FbossSystemctlServiceName.FBOSS_HW_AGENT_0
        )
        self.assertEqual(
            self._touched_files(), [f"{FBOSS_WARM_BOOT_DIR}/hw_cold_boot_once_0"]
        )

    async def test_sw_agent_restart_flags_only_the_sw_agent(self) -> None:
        await self.switch.async_create_cold_boot_file(
            FbossSystemctlServiceName.FBOSS_SW_AGENT
        )
        self.assertEqual(self._touched_files(), [FBOSS_SPLIT_SW_COLD_BOOT_ONCE_FILE])

    async def test_agent_restart_still_flags_every_agent(self) -> None:
        self.switch.async_get_hw_agent_switch_indices = AsyncMock(return_value=[0, 1])
        await self.switch.async_create_cold_boot_file(FbossSystemctlServiceName.AGENT)
        self.assertEqual(
            self._touched_files(),
            [
                FBOSS_SPLIT_SW_COLD_BOOT_ONCE_FILE,
                f"{FBOSS_WARM_BOOT_DIR}/hw_cold_boot_once_0",
                f"{FBOSS_WARM_BOOT_DIR}/hw_cold_boot_once_1",
            ],
        )


def _async_cm(client: object) -> MagicMock:
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


class HwAgentSwitchIndicesTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.switch = FbossSwitch("dut1", logger=MagicMock())
        self.client = MagicMock()
        patcher = patch.object(
            FbossSwitch,
            "async_agent_client",
            new_callable=PropertyMock,
            return_value=_async_cm(self.client),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run_states(self, switch_ids: list) -> None:
        self.switch.async_get_multi_switch_run_state = AsyncMock(
            return_value=MagicMock(hwIndexToRunState=dict.fromkeys(switch_ids))
        )

    async def test_maps_switch_ids_to_switch_indices(self) -> None:
        """hwIndexToRunState is keyed by SwitchID, not by switch index."""
        self._run_states([101, 100])
        self.client.getSwitchIdToSwitchInfo = AsyncMock(
            return_value={100: MagicMock(switchIndex=0), 101: MagicMock(switchIndex=1)}
        )
        self.assertEqual(await self.switch.async_get_hw_agent_switch_indices(), [0, 1])

    async def test_unmapped_switch_id_raises(self) -> None:
        self._run_states([100])
        self.client.getSwitchIdToSwitchInfo = AsyncMock(return_value={})
        with self.assertRaises(Exception) as ctx:
            await self.switch.async_get_hw_agent_switch_indices()
        self.assertIn("100", str(ctx.exception))


class AssertWarmBootedTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.switch = FbossSwitch("dut1", logger=MagicMock())
        self.sw_client = MagicMock()
        self.hw_clients = {0: MagicMock(), 1: MagicMock()}
        patcher = patch.object(
            FbossSwitch,
            "async_agent_client",
            new_callable=PropertyMock,
            return_value=_async_cm(self.sw_client),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.switch.get_hw_agent_client = AsyncMock(
            side_effect=lambda switch_index: _async_cm(self.hw_clients[switch_index])
        )

    def _boot_types(self, sw: BootType, hw0: BootType, hw1: BootType) -> None:
        self.sw_client.getBootType = AsyncMock(return_value=sw)
        self.hw_clients[0].getBootType = AsyncMock(return_value=hw0)
        self.hw_clients[1].getBootType = AsyncMock(return_value=hw1)

    async def test_all_warm_passes(self) -> None:
        self._boot_types(BootType.WARM_BOOT, BootType.WARM_BOOT, BootType.WARM_BOOT)
        await self.switch._async_assert_warm_booted([0, 1], set())

    async def test_unflagged_cold_hw_agent_fails(self) -> None:
        """A hw agent that lost its warm boot state still reaches a good run state."""
        self._boot_types(BootType.WARM_BOOT, BootType.WARM_BOOT, BootType.COLD_BOOT)
        with self.assertRaises(Exception) as ctx:
            await self.switch._async_assert_warm_booted([0, 1], set())
        self.assertIn("fboss_hw_agent@1=COLD_BOOT", str(ctx.exception))

    async def test_unflagged_cold_sw_agent_fails(self) -> None:
        self._boot_types(BootType.COLD_BOOT, BootType.WARM_BOOT, BootType.WARM_BOOT)
        with self.assertRaisesRegex(Exception, "fboss_sw_agent=COLD_BOOT"):
            await self.switch._async_assert_warm_booted([0, 1], set())

    async def test_flagged_agents_are_allowed_to_cold_boot(self) -> None:
        self._boot_types(BootType.COLD_BOOT, BootType.COLD_BOOT, BootType.COLD_BOOT)
        await self.switch._async_assert_warm_booted(
            [0, 1],
            {
                f"{FBOSS_SPLIT_SW_COLD_BOOT_ONCE_FILE}_0",
                f"{FBOSS_WARM_BOOT_DIR}/hw_cold_boot_once_0",
                f"{FBOSS_WARM_BOOT_DIR}/hw_cold_boot_once_1",
            },
        )
        self.sw_client.getBootType.assert_not_awaited()

    async def test_present_flags_are_read_from_the_dut(self) -> None:
        self.switch.async_run_cmd_on_shell = AsyncMock(
            return_value=f"{FBOSS_SPLIT_SW_COLD_BOOT_ONCE_FILE}\n\n"
        )
        self.assertEqual(
            await self.switch._async_present_cold_boot_flags(),
            {FBOSS_SPLIT_SW_COLD_BOOT_ONCE_FILE},
        )


if __name__ == "__main__":
    unittest.main()
