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
from unittest.mock import AsyncMock, MagicMock

from taac.constants import (
    FBOSS_COLD_BOOT_ONCE_FILE,
    FBOSS_COLD_BOOT_ONCE_GLOB,
    FBOSS_COLD_BOOT_ONCE_GLOBS,
    FBOSS_SPLIT_SW_COLD_BOOT_ONCE_FILE,
)
from taac.driver.fboss_switch import FbossSwitch


class ColdBootFileTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.switch = FbossSwitch("dut1", logger=MagicMock())
        self.switch.async_run_cmd_on_shell = AsyncMock()

    def _touched_files(self) -> list:
        self.switch.async_run_cmd_on_shell.assert_awaited_once()
        cmd = self.switch.async_run_cmd_on_shell.await_args.args[0]
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
                "/dev/shm/fboss/warm_boot/hw_cold_boot_once_0",
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
                "/dev/shm/fboss/warm_boot/hw_cold_boot_once_0",
                "/dev/shm/fboss/warm_boot/hw_cold_boot_once_1",
            ],
        )

    async def test_remove_clears_monolithic_and_split_flags(self) -> None:
        await self.switch.async_remove_cold_boot_file()
        self.switch.async_run_cmd_on_shell.assert_awaited_once_with(
            f"rm -f {' '.join(FBOSS_COLD_BOOT_ONCE_GLOBS)}"
        )

    async def test_remove_does_not_need_a_live_agent(self) -> None:
        """Globbed, so clearing works with the agent down -- when it matters most."""
        self.switch.async_is_multi_switch = AsyncMock(
            side_effect=AssertionError("must not probe the agent")
        )
        await self.switch.async_remove_cold_boot_file()
        self.switch.async_run_cmd_on_shell.assert_awaited_once()

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


if __name__ == "__main__":
    unittest.main()
