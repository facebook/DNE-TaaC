# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
"""Unit tests for the Open/R sub-interface adjacency scaling TestConfig factory."""

import json
import unittest

from taac.testconfigs.routing.openr.openr_portchannel_subif_test_config import (
    _CLEANUP_SCRIPT_PATH,
    _script_setup_tasks,
    _script_teardown_tasks,
    _SETUP_SCRIPT_PATH,
    create_openr_portchannel_subif_test_config,
)

_PC = "Port-Channel1910"


def _cmds(task) -> list:
    return json.loads(task.params.json_params)["cmds"]


class ScriptSetupTasksTest(unittest.TestCase):
    def test_single_task_with_full_args(self) -> None:
        """One task that calls the pre-deployed setup script with pc/n/start/octet."""
        tasks = _script_setup_tasks(
            "eb04.lab.ash6", _PC, num_vlans=1024, start_vlan=1, octet=2
        )
        self.assertEqual(len(tasks), 1)
        self.assertEqual(
            _cmds(tasks[0]),
            [f"bash sudo timeout 600 bash {_SETUP_SCRIPT_PATH} {_PC} 1024 1 2"],
        )


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
        """One setup + one teardown task per device, plus endpoints/playbook shape."""
        config = create_openr_portchannel_subif_test_config(num_subinterfaces=4)
        self.assertEqual(config.name, "OPENR_PORTCHANNEL_SUBIF_SCALE_4")
        self.assertEqual(len(config.setup_tasks or []), 2)
        self.assertEqual(len(config.teardown_tasks or []), 2)
        self.assertEqual(len(config.endpoints or []), 2)
        self.assertEqual(len(config.playbooks or []), 1)
        playbook = (config.playbooks or [])[0]
        self.assertEqual(playbook.name, "openr_subif_adjacency_scale_playbook")
        self.assertEqual(len(playbook.postchecks or []), 1)

    def test_skip_teardown_yields_no_teardown_tasks(self) -> None:
        """skip_teardown=True leaves the sub-interfaces in place."""
        config = create_openr_portchannel_subif_test_config(
            num_subinterfaces=4, skip_teardown=True
        )
        self.assertEqual(len(config.teardown_tasks or []), 0)


if __name__ == "__main__":
    unittest.main()
