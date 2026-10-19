# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

import json
import unittest

from taac.testconfigs.routing.openr import OPENR_UPDATE_LOSS


def _task_params(task) -> dict:
    return json.loads(task.params.json_params)


def _step_params(step) -> dict:
    if step.step_params is None or step.step_params.json_params is None:
        return {}
    return json.loads(step.step_params.json_params)


class OpenRUpdateLossTestConfigTest(unittest.TestCase):
    def test_binding_targets_the_dut_only_and_no_ixia(self) -> None:
        config = OPENR_UPDATE_LOSS

        self.assertEqual("OPENR_UPDATE_LOSS", config.name)
        self.assertEqual(
            {"eb04.lab.ash6": True},
            {endpoint.name: endpoint.dut for endpoint in config.endpoints},
        )
        self.assertEqual([], list(config.basic_port_configs or []))
        self.assertEqual([], list(config.basic_traffic_item_configs or []))
        self.assertEqual(
            ["openr_update_loss_playbook"],
            [playbook.name for playbook in config.playbooks or []],
        )

    def test_setup_stages_isolation_fixture_programming_and_cleanup(self) -> None:
        setup = list(OPENR_UPDATE_LOSS.setup_tasks or [])

        self.assertEqual(
            [
                "openr_scale_isolation",
                "openr_scale_link_fixture",
                "openr_fib_programming",
                "run_commands_on_shell",
            ],
            [task.task_name for task in setup],
        )
        fixture = _task_params(setup[1])
        self.assertEqual("setup", fixture["action"])
        self.assertEqual("Ethernet3/10/1", fixture["member_interface"])
        self.assertEqual(1910, fixture["original_port_channel_id"])
        self.assertEqual(1911, fixture["test_port_channel_id"])
        self.assertEqual(
            {
                "eb02.lab.ash6": "10.165.28.12/31",
                "eb04.lab.ash6": "10.165.28.13/31",
            },
            fixture["ipv4_cidrs_by_device"],
        )
        self.assertEqual("enable", _task_params(setup[2])["action"])

    def test_teardown_restores_config_and_links_after_key_expiry(self) -> None:
        teardown = list(OPENR_UPDATE_LOSS.teardown_tasks or [])

        self.assertEqual(
            [
                "run_commands_on_shell",
                "openr_scale_isolation",
                "openr_fib_programming",
                "openr_scale_link_fixture",
            ],
            [task.task_name for task in teardown],
        )
        self.assertEqual("disable", _task_params(teardown[2])["action"])
        cleanup = _task_params(teardown[3])
        self.assertEqual("cleanup", cleanup["action"])
        self.assertEqual("Ethernet3/10/1", cleanup["member_interface"])
        self.assertEqual(1910, cleanup["original_port_channel_id"])
        self.assertEqual(1911, cleanup["test_port_channel_id"])

    def test_injection_targets_the_inband_address(self) -> None:
        injection = _step_params(OPENR_UPDATE_LOSS.playbooks[0].stages[0].steps[0])

        self.assertEqual("eb02.lab.ash6", injection["helper_name"])
        self.assertEqual("eb04.lab.ash6", injection["dut_name"])
        self.assertEqual("2401:db00:e50d:11:8::10", injection["dut_host"])
