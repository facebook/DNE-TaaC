# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

import json
import unittest

from taac.playbooks.routing.openr_scale_playbooks import (
    get_openr_scale_physical_link_flap_playbook,
)


def _params(step) -> dict:
    if step.step_params is None or step.step_params.json_params is None:
        return {}
    return json.loads(step.step_params.json_params)


class OpenRScalePhysicalLinkFlapPlaybookTest(unittest.TestCase):
    def setUp(self) -> None:
        self.playbook = get_openr_scale_physical_link_flap_playbook(
            helper_name="eb02.lab.ash6",
            dut_name="eb04.lab.ash6",
            dut_inband_address="2401:db00:e50d:11:8::10",
            dut_mgmt_addresses=["2401:db00:2066:304a::1005"],
            num_spines=64,
            num_leaves=252,
            num_control_nodes=0,
            num_sites=20,
            ecmp_width=8,
            prefixes_per_node=11,
            prefix_seed=20250903,
            area="0",
        )

    def test_one_background_injection_wraps_one_physical_down_up_cycle(self) -> None:
        steps = self.playbook.stages[0].steps
        self.assertEqual("openr_scale_physical_link_flap_playbook", self.playbook.name)
        self.assertEqual(
            [
                "VALIDATION_STEP",
                "CUSTOM_STEP",
                "CUSTOM_STEP",
                "INTERFACE_FLAP_STEP",
                "VALIDATION_STEP",
                "VALIDATION_STEP",
                "CUSTOM_STEP",
                "LONGEVITY_STEP",
                "CUSTOM_STEP",
                "INTERFACE_FLAP_STEP",
                "VALIDATION_STEP",
                "VALIDATION_STEP",
                "CUSTOM_STEP",
                "CUSTOM_STEP",
            ],
            [step.name.name for step in steps],
        )
        self.assertEqual(
            [False, True], [_params(steps[index])["enable"] for index in (3, 9)]
        )
        for index in (3, 9):
            params = _params(steps[index])
            self.assertEqual(["Port-Channel1911"], params["interfaces"])
            self.assertEqual(4, params["interface_flap_method"])
            self.assertEqual("eb02.lab.ash6", params["device_name"])

        for index, expected_count in ((0, 2), (5, 1), (11, 2)):
            validation = json.loads(steps[index].input_json or "{}")
            check = validation["point_in_time_checks"][0]
            self.assertNotEqual(0, check["check_scope"])
            check_params = json.loads(check["check_params"]["json_params"])
            self.assertEqual(expected_count, check_params["expected_neighbor_count"])
            self.assertNotIn("expected_neighbors", check_params)

        for index, expected_up in ((4, False), (10, True)):
            validation = json.loads(steps[index].input_json or "{}")
            check = validation["point_in_time_checks"][0]
            self.assertNotEqual(0, check["check_scope"])
            check_params = json.loads(check["check_params"]["json_params"])
            self.assertEqual(expected_up, check_params["expected_up"])
            self.assertEqual(
                {
                    "eb02.lab.ash6": ["Port-Channel1911"],
                    "eb04.lab.ash6": ["Port-Channel1911"],
                },
                check_params["port_channel_names"],
            )

    def test_scale_session_stays_live_and_disables_background_key_bumps(self) -> None:
        injection = _params(self.playbook.stages[0].steps[1])

        self.assertTrue(injection["background"])
        self.assertEqual(900, injection["run_duration_sec"])
        self.assertEqual(90, injection["background_ready_timeout_sec"])
        self.assertEqual(64, injection["num_spines"])
        self.assertEqual(252, injection["num_leaves"])
        self.assertEqual(
            ["--num_pods=8", "--fake_key_version_bump_interval_sec=0"],
            injection["extra_flags"],
        )

    def test_performance_brackets_down_and_up_independently(self) -> None:
        steps = self.playbook.stages[0].steps
        measurements = [_params(steps[index]) for index in (2, 6, 8, 12)]

        self.assertEqual(
            ["start", "validate", "start", "validate"],
            [params["action"] for params in measurements],
        )
        self.assertEqual(
            ["physical_link_down"] * 2 + ["physical_link_up"] * 2,
            [params["profile"] for params in measurements],
        )
        self.assertEqual(
            ["link_down"] * 2 + ["link_up"] * 2,
            [params["phase"] for params in measurements],
        )
        self.assertEqual(
            ["openr_scale_test_4_performance"] * 4,
            [params["state_key"] for params in measurements],
        )
        self.assertEqual(305, _params(steps[7])["duration"])

        cleanup = [_params(step) for step in self.playbook.cleanup_steps or []]
        self.assertEqual(["link_up", "link_down"], [p["phase"] for p in cleanup])
        self.assertEqual(["cleanup", "cleanup"], [p["action"] for p in cleanup])
