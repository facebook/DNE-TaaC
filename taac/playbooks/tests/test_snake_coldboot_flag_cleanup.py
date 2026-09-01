#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Where the coldboot playbook clears the agent's one-shot cold-boot flag.

It belongs in ``cleanup_steps`` (run in the runner's ``finally``) rather than in
the stage: the agent reads the flag during init and ``systemctl restart``
returns before that, so clearing mid-stage could downgrade the cold boot to a
warm one -- and a stage that aborts is exactly when a stale flag is likeliest.
"""

import json
import unittest

from taac.constants import FBOSS_COLD_BOOT_ONCE_GLOBS
from taac.playbooks.playbook_definitions import gen_snake_playbooks
from taac.test_as_a_config import types as taac_types


class SnakeColdbootFlagCleanupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.coldboot = next(
            pb
            for pb in gen_snake_playbooks(hostname="dut1", iteration=1)
            if pb.name == "test_snake_agent_coldboot"
        )

    def test_flag_is_cleared_in_cleanup_steps(self) -> None:
        cmds = [
            json.loads(s.step_params.json_params).get("cmd")
            for s in (self.coldboot.cleanup_steps or [])
            if s.name == taac_types.StepName.RUN_SSH_COMMAND_STEP
        ]
        self.assertIn(f"rm -f {' '.join(FBOSS_COLD_BOOT_ONCE_GLOBS)}", cmds)

    def test_cleanup_clears_the_split_agent_flags_too(self) -> None:
        """Leaving sw_cold_boot_once behind cold boots every subsequent run."""
        cleanup_cmds = " ".join(
            json.loads(s.step_params.json_params).get("cmd") or ""
            for s in (self.coldboot.cleanup_steps or [])
            if s.name == taac_types.StepName.RUN_SSH_COMMAND_STEP
        )
        self.assertIn("sw_cold_boot_once", cleanup_cmds)
        self.assertIn("hw_cold_boot_once_", cleanup_cmds)

    def test_flag_is_not_cleared_mid_stage(self) -> None:
        """Clearing before the agent has read it would silently warm-boot."""
        self.assertNotIn(
            taac_types.StepName.RUN_SSH_COMMAND_STEP,
            [s.name for s in self.coldboot.stages[0].steps],
        )


if __name__ == "__main__":
    unittest.main()
