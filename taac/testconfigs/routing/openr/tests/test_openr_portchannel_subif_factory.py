# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
"""Unit tests for the Open/R sub-interface adjacency scaling TestConfig factory."""

import json
import unittest

from taac.testconfigs.routing.openr.openr_portchannel_subif_test_config import (
    _CLEANUP_SCRIPT_PATH,
    _script_teardown_tasks,
    create_openr_portchannel_subif_test_config,
)

_PC = "Port-Channel1910"


def _task_params(task) -> dict:
    return json.loads(task.params.json_params)


def _cmds(task) -> list:
    return _task_params(task)["cmds"]


class ScriptTeardownTasksTest(unittest.TestCase):
    def test_single_task_with_args_no_octet(self) -> None:
        """One task that calls the pre-deployed cleanup script (no octet arg)."""
        tasks = _script_teardown_tasks(
            "eb02.lab.ash6", _PC, num_vlans=1024, start_vlan=1
        )
        self.assertEqual(len(tasks), 1)
        self.assertEqual(
            _cmds(tasks[0]),
            [f"bash sudo timeout 600 bash {_CLEANUP_SCRIPT_PATH} {_PC} 1024 1"],
        )


class TestConfigStructureTest(unittest.TestCase):
    def test_golden_structure(self) -> None:
        """Setup runs in-playbook while teardown remains lifecycle-guaranteed."""
        config = create_openr_portchannel_subif_test_config(num_subinterfaces=4)
        self.assertEqual(config.name, "OPENR_PORTCHANNEL_SUBIF_SCALE_4")
        self.assertEqual([], list(config.setup_tasks or ()))
        self.assertEqual(len(config.teardown_tasks or []), 2)
        for task in config.teardown_tasks or []:
            self.assertEqual("run_commands_on_shell", task.task_name)
            self.assertTrue(_task_params(task)["validate_output"])
            self.assertIsNotNone(task.hostname)
        self.assertEqual(
            [
                f"bash sudo timeout 600 bash {_CLEANUP_SCRIPT_PATH} {_PC} 4 1",
            ],
            _cmds((config.teardown_tasks or [])[0]),
        )
        self.assertEqual(
            [
                f"bash sudo timeout 600 bash {_CLEANUP_SCRIPT_PATH} {_PC} 4 1",
            ],
            _cmds((config.teardown_tasks or [])[1]),
        )
        self.assertEqual(len(config.endpoints or []), 2)
        self.assertEqual(len(config.playbooks or []), 1)
        playbook = (config.playbooks or [])[0]
        self.assertEqual(playbook.name, "openr_subif_adjacency_scale_playbook")
        self.assertEqual([], list(playbook.postchecks or ()))
        self.assertEqual(5, len(playbook.stages[0].steps))

    def test_skip_teardown_yields_no_teardown_tasks(self) -> None:
        """skip_teardown=True leaves the sub-interfaces in place."""
        config = create_openr_portchannel_subif_test_config(
            num_subinterfaces=4, skip_teardown=True
        )
        self.assertEqual(len(config.teardown_tasks or []), 0)


if __name__ == "__main__":
    unittest.main()
