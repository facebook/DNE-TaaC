# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

import json
import unittest

from taac.playbooks.routing.openr_update_loss_playbooks import (
    get_openr_update_loss_playbook,
)


def _params(step) -> dict:
    if step.step_params is None or step.step_params.json_params is None:
        return {}
    return json.loads(step.step_params.json_params)


class OpenRUpdateLossPlaybookTest(unittest.TestCase):
    def setUp(self) -> None:
        self.playbook = get_openr_update_loss_playbook(
            dut_name="eb04.lab.ash6",
            helper_name="eb02.lab.ash6",
            dut_inband_address="2401:db00:e50d:11:8::10",
            dut_mgmt_addresses=["2401:db00:2066:304a::1005"],
        )

    def test_sequence_brackets_one_freeze_with_validation(self) -> None:
        steps = self.playbook.stages[0].steps
        self.assertEqual("openr_update_loss_playbook", self.playbook.name)
        self.assertEqual(
            [
                "CUSTOM_STEP",
                "CUSTOM_STEP",
                "CUSTOM_STEP",
                "LONGEVITY_STEP",
                "CUSTOM_STEP",
                "VALIDATION_STEP",
            ],
            [step.name.name for step in steps],
        )
        self.assertEqual(
            ["openr_scale_injection", "openr_update_loss_validation"],
            [_params(steps[index])["custom_step_name"] for index in (0, 1)],
        )
        self.assertEqual("ready", _params(steps[1])["action"])
        validate = _params(steps[4])
        self.assertEqual("openr_update_loss_validation", validate["custom_step_name"])
        self.assertEqual("validate", validate["action"])
        self.assertEqual(20, _params(steps[3])["duration"])
        restart_description = steps[5].description
        assert restart_description is not None
        self.assertIn("not restarted", restart_description)

    def test_injection_is_small_background_with_simulated_neighbors(self) -> None:
        injection = _params(self.playbook.stages[0].steps[0])

        self.assertTrue(injection["background"])
        self.assertTrue(injection["simulate_neighbors"])
        self.assertFalse(injection["verify_routes"])
        self.assertEqual(["po1910"], injection["interfaces"])
        self.assertEqual(4, injection["num_spines"])
        self.assertEqual(10, injection["num_leaves"])
        self.assertEqual(1800, injection["run_duration_sec"])
        self.assertEqual(
            [
                "--num_pods=1",
                "--num_fake_keys_per_node=0",
                "--fake_key_version_bump_interval_sec=0",
            ],
            injection["extra_flags"],
        )

    def test_freeze_runs_full_full_disjoint_metric_rebuilds(self) -> None:
        steps = self.playbook.stages[0].steps
        freeze = _params(steps[2])
        burst = freeze["during_pause_shell_cmd"]

        self.assertEqual("openr_fibagent_pause", freeze["custom_step_name"])
        self.assertEqual("eb04.lab.ash6", freeze["dut_name"])
        self.assertEqual("FibAgent", freeze["agent"])
        self.assertEqual(1.0, freeze["pause_seconds"])
        for fragment in (
            "increase-link-metric --yes --quiet po1910 50",
            "increase-link-metric --yes --quiet po1910 60",
            "increase-link-metric --yes --quiet po1911 70",
        ):
            self.assertIn(fragment, burst)
        # Two sleeps separate the three pushes past the debounce window.
        self.assertEqual(2, burst.count("sleep 2"))
        self.assertLess(
            burst.index("po1910 50"),
            burst.index("po1910 60"),
        )
        self.assertLess(
            burst.index("po1910 60"),
            burst.index("po1911 70"),
        )
        # The validator echoes the same stimulus into failure evidence.
        self.assertEqual(burst, _params(steps[4])["stimulus_cmd"])
