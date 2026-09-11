# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe
"""Structural coverage for the narrow TC50 and broad TC58 kill scopes."""

import json
import unittest

from taac.testconfigs.fpf import (
    fpf_shared_injection_suite,
    fpf_tc50_wedge_agent_kill_5s_10min,
    fpf_tc58_multi_fboss_process_kill_15s_5min,
)
from taac.test_as_a_config.types import Service


def _playbook(config, name):
    return next(playbook for playbook in config.playbooks if playbook.name == name)


def _step_params(playbook, custom_step_name: str) -> dict:
    return next(
        params
        for stage in playbook.stages
        for step in stage.steps or []
        if step.step_params is not None and step.step_params.json_params is not None
        for params in [json.loads(step.step_params.json_params)]
        if params.get("custom_step_name") == custom_step_name
    )


class TestFpfProcessKillConfigs(unittest.TestCase):
    def _assert_tc50_narrow(self, config) -> None:
        disrupt = _playbook(config, "fpf_tc50_wedge_agent_kill_5s_10min_disrupt")
        params = _step_params(disrupt, "fpf_repeated_sw_hw_agent_crash")
        self.assertEqual(params["process_names"], ["fboss_sw_agent", "fboss_hw_agent"])
        self.assertEqual(
            params["recovery_services"],
            [
                int(Service.FBOSS_SW_AGENT.value),
                int(Service.FBOSS_HW_AGENT_0.value),
            ],
        )
        self.assertEqual(params["every_sec"], 15)
        self.assertEqual(params["duration_sec"], 300)
        self.assertEqual(params["recovery_timeout_sec"], 120)
        self.assertNotIn("service", params)
        self.assertNotIn("qsfp_service", params["process_names"])

    def _assert_tc58_broad(self, config) -> None:
        disrupt = _playbook(
            config,
            "fpf_tc58_multi_fboss_process_kill_15s_5min_disrupt",
        )
        params = _step_params(disrupt, "fpf_repeated_service_crash")
        self.assertEqual(params["service"], int(Service.AGENT.value))
        self.assertEqual(params["every_sec"], 15)
        self.assertEqual(params["duration_sec"], 300)

    def test_standalone_tc50_is_narrow_and_tc58_preserves_broad_trigger(self):
        tc50 = fpf_tc50_wedge_agent_kill_5s_10min.TEST_CONFIG
        tc58 = fpf_tc58_multi_fboss_process_kill_15s_5min.TEST_CONFIG
        self.assertEqual(tc50.name, "fpf_tc50_wedge_agent_kill_5s_10min")
        self.assertEqual(tc58.name, "fpf_tc58_multi_fboss_process_kill_15s_5min")
        self._assert_tc50_narrow(tc50)
        self._assert_tc58_broad(tc58)

        self.assertEqual(tc50.setup_tasks, tc58.setup_tasks)
        self.assertEqual(tc50.teardown_tasks, tc58.teardown_tasks)
        self.assertEqual(
            tc50.playbooks[0].postchecks,
            tc58.playbooks[0].postchecks,
        )
        self.assertEqual(
            tc50.playbooks[1].postchecks,
            tc58.playbooks[1].postchecks,
        )

    def test_shared_suite_exposes_both_distinct_kill_scopes(self):
        config = fpf_shared_injection_suite.TEST_CONFIG
        self._assert_tc50_narrow(config)
        self._assert_tc58_broad(config)


if __name__ == "__main__":
    unittest.main()
