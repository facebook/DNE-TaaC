#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Pins the settle window between agent convergence and the warmboot postchecks.

Convergence only means the agent reported ``SwitchRunState.CONFIGURED``, which
is not the same as LLDP neighbors -- soft state wiped by the restart and
relearned only as neighbors re-advertise. See ``SNAKE_AGENT_LLDP_SETTLE_S``.
"""

import json
import unittest

from taac.playbooks.playbook_definitions import (
    gen_snake_playbooks,
    SNAKE_AGENT_LLDP_SETTLE_S,
)
from taac.test_as_a_config import types as taac_types


class SnakeWarmbootSettleTest(unittest.TestCase):
    def setUp(self) -> None:
        playbooks = gen_snake_playbooks(hostname="dut1", iteration=1)
        self.warmboot = next(
            pb for pb in playbooks if pb.name == "test_snake_agent_warmboot"
        )

    def test_settle_step_follows_convergence(self) -> None:
        """A wait must sit between convergence and the postchecks.

        Asserted as relative order, not position, so appending a step to the
        stage doesn't break it -- only reordering these two does.
        """
        names = [s.name for s in self.warmboot.stages[0].steps]
        self.assertIn(taac_types.StepName.SERVICE_CONVERGENCE_STEP, names)
        self.assertIn(taac_types.StepName.LONGEVITY_STEP, names)
        self.assertLess(
            names.index(taac_types.StepName.SERVICE_CONVERGENCE_STEP),
            names.index(taac_types.StepName.LONGEVITY_STEP),
        )

    def test_settle_step_holds_for_the_lldp_window(self) -> None:
        settle = [
            s
            for s in self.warmboot.stages[0].steps
            if s.name == taac_types.StepName.LONGEVITY_STEP
        ]
        self.assertEqual(len(settle), 1)
        params = json.loads(settle[0].step_params.json_params)
        self.assertEqual(params["duration"], SNAKE_AGENT_LLDP_SETTLE_S)


if __name__ == "__main__":
    unittest.main()
