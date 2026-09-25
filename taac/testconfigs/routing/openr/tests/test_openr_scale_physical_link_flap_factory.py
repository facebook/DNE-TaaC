# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

import json
import unittest

from taac.testconfigs.routing.openr import (
    OPENR_SCALE_PHYSICAL_LINK_FLAP_TEST_CONFIG,
)


def _task_params(task) -> dict:
    return json.loads(task.params.json_params)


def _step_params(step) -> dict:
    if step.step_params is None or step.step_params.json_params is None:
        return {}
    return json.loads(step.step_params.json_params)


class OpenRScalePhysicalLinkFlapTestConfigTest(unittest.TestCase):
    def test_binding_uses_the_manual_lab_roles_and_no_ixia(self) -> None:
        config = OPENR_SCALE_PHYSICAL_LINK_FLAP_TEST_CONFIG

        self.assertEqual("OPENR_SCALE_PHYSICAL_LINK_FLAP", config.name)
        self.assertEqual(
            {"eb04.lab.ash6": True, "eb02.lab.ash6": False},
            {endpoint.name: endpoint.dut for endpoint in config.endpoints},
        )
        self.assertEqual([], list(config.basic_port_configs or []))
        self.assertEqual([], list(config.basic_traffic_item_configs or []))

    def test_fixture_is_test_scoped_and_teardown_restores_po1910(self) -> None:
        config = OPENR_SCALE_PHYSICAL_LINK_FLAP_TEST_CONFIG
        setup = list(config.setup_tasks or [])
        teardown = list(config.teardown_tasks or [])

        self.assertEqual(
            ["openr_scale_isolation", "openr_scale_link_fixture"],
            [task.task_name for task in setup],
        )
        self.assertEqual(
            ["openr_scale_link_fixture", "openr_scale_isolation"],
            [task.task_name for task in teardown],
        )
        self.assertEqual("setup", _task_params(setup[1])["action"])
        cleanup = _task_params(teardown[0])
        self.assertEqual("cleanup", cleanup["action"])
        self.assertEqual("Ethernet3/10/1", cleanup["member_interface"])
        self.assertEqual(1910, cleanup["original_port_channel_id"])
        self.assertEqual(1911, cleanup["test_port_channel_id"])
        self.assertEqual(
            {
                "eb02.lab.ash6": "10.165.28.12/31",
                "eb04.lab.ash6": "10.165.28.13/31",
            },
            cleanup["ipv4_cidrs_by_device"],
        )

    def test_background_scale_session_matches_the_local_run(self) -> None:
        injection = _step_params(
            OPENR_SCALE_PHYSICAL_LINK_FLAP_TEST_CONFIG.playbooks[0].stages[0].steps[1]
        )

        self.assertEqual("eb02.lab.ash6", injection["helper_name"])
        self.assertEqual("eb04.lab.ash6", injection["dut_name"])
        self.assertEqual("2401:db00:e50d:11:8::10", injection["dut_host"])
        self.assertEqual(64, injection["num_spines"])
        self.assertEqual(252, injection["num_leaves"])
        self.assertTrue(injection["background"])
        self.assertFalse(injection["simulate_neighbors"])
        self.assertFalse(injection["verify_routes"])
