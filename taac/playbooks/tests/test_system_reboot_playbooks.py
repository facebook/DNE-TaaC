# Copyright (c) Meta Platforms, Inc. and affiliates.

import json
import unittest

from taac.playbooks import playbook_definitions
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types


class SystemRebootPlaybooksTest(unittest.TestCase):
    def test_builds_reboot_and_isolated_stability_playbooks(self) -> None:
        factory = getattr(playbook_definitions, "create_system_reboot_playbooks", None)
        self.assertIsNotNone(factory)
        if factory is None:
            return

        precheck = taac_types.PointInTimeHealthCheck(
            name=hc_types.CheckName.BGP_SESSION_ESTABLISH_CHECK
        )
        postcheck = taac_types.PointInTimeHealthCheck(
            name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK
        )
        playbooks = factory(
            name="test_system_reboot_bmc_full",
            trigger=taac_types.SystemRebootTrigger.FULL_SYSTEM_REBOOT,
            is_rsw=True,
            iteration=1,
            recovery_prechecks=[precheck],
            recovery_postchecks=[postcheck],
            stability_prechecks=[precheck],
            stability_postchecks=[postcheck],
            traffic_items_to_start=["ROUTED_TRAFFIC"],
            recovery_duration_s=240,
            stability_duration_s=300,
        )

        self.assertEqual(
            [playbook.name for playbook in playbooks],
            [
                "test_system_reboot_bmc_full",
                "test_system_reboot_bmc_full_stability",
            ],
        )
        self.assertEqual(
            json.loads(playbooks[0].stages[0].steps[0].input_json)["trigger"],
            taac_types.SystemRebootTrigger.FULL_SYSTEM_REBOOT,
        )
        for playbook in playbooks:
            self.assertEqual(playbook.iteration, 1)
            self.assertEqual(playbook.traffic_items_to_start, ["ROUTED_TRAFFIC"])
        self.assertEqual(playbooks[0].prechecks, [precheck])
        self.assertEqual(playbooks[0].postchecks, [postcheck])
        self.assertEqual(playbooks[1].prechecks, [precheck])
        self.assertEqual(playbooks[1].postchecks, [postcheck])

        recovery_step_names = [
            step.name for stage in playbooks[0].stages for step in stage.steps
        ]
        self.assertNotIn(taac_types.StepName.DRAIN_UNDRAIN_STEP, recovery_step_names)
        self.assertNotIn(taac_types.StepName.VALIDATION_STEP, recovery_step_names)
        self.assertEqual(
            json.loads(playbooks[0].stages[-1].steps[-1].step_params.json_params)[
                "duration"
            ],
            240,
        )
        self.assertEqual(
            json.loads(playbooks[1].stages[0].steps[0].step_params.json_params)[
                "duration"
            ],
            300,
        )

    def test_non_rsw_reboot_validates_drain_and_undrains(self) -> None:
        factory = playbook_definitions.create_system_reboot_playbooks
        playbooks = factory(
            name="test_system_reboot_bmc_full",
            trigger=taac_types.SystemRebootTrigger.FULL_SYSTEM_REBOOT,
            is_rsw=False,
        )

        recovery_steps = [step for stage in playbooks[0].stages for step in stage.steps]
        self.assertIn(
            taac_types.StepName.VALIDATION_STEP,
            [step.name for step in recovery_steps],
        )
        self.assertIn(
            taac_types.StepName.DRAIN_UNDRAIN_STEP,
            [step.name for step in recovery_steps],
        )


if __name__ == "__main__":
    unittest.main()
