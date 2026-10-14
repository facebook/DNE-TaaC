# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

import json
import unittest

from taac.testconfigs.routing.openr import (
    OPENR_SCALE_DUT_COLD_BOOT,
)


def _params(value) -> dict:
    if value.params is None:
        raise AssertionError("Task must populate params")
    json_params = value.params.json_params
    if json_params is None:
        raise AssertionError("Task must populate JSON params")
    return json.loads(json_params)


def _step_params(value) -> dict:
    if value.step_params is None:
        raise AssertionError("Step must populate step_params")
    json_params = value.step_params.json_params
    if json_params is None:
        raise AssertionError("Step must populate JSON params")
    return json.loads(json_params)


class OpenRScaleDutColdBootFactoryTest(unittest.TestCase):
    def test_binding_and_isolated_cleanup(self) -> None:
        config = OPENR_SCALE_DUT_COLD_BOOT
        endpoints = config.endpoints
        setup_tasks = config.setup_tasks
        teardown_tasks = config.teardown_tasks
        assert endpoints is not None
        assert setup_tasks is not None
        assert teardown_tasks is not None
        self.assertEqual("OPENR_SCALE_DUT_COLD_BOOT", config.name)
        self.assertEqual(
            {"eb04.lab.ash6": True, "eb02.lab.ash6": False},
            {endpoint.name: endpoint.dut for endpoint in endpoints},
        )
        self.assertEqual(
            ["openr_scale_isolation", "openr_scale_cold_boot_fixture"],
            [task.task_name for task in setup_tasks],
        )
        self.assertEqual(
            ["openr_scale_cold_boot_fixture", "openr_scale_isolation"],
            [task.task_name for task in teardown_tasks],
        )
        self.assertEqual(_params(setup_tasks[0]), _params(teardown_tasks[1]))
        fixture_setup = _params(setup_tasks[1])
        fixture_cleanup = _params(teardown_tasks[0])
        self.assertEqual("setup", fixture_setup.pop("action"))
        self.assertEqual("cleanup", fixture_cleanup.pop("action"))
        self.assertEqual(fixture_setup, fixture_cleanup)
        self.assertEqual(64, fixture_setup["num_subinterfaces"])
        self.assertEqual(100, fixture_setup["start_vlan"])

    def test_full_fabric_profile(self) -> None:
        playbooks = OPENR_SCALE_DUT_COLD_BOOT.playbooks
        assert playbooks is not None
        playbook = playbooks[0]
        injection = _step_params(playbook.stages[0].steps[0])
        self.assertEqual(
            {
                "num_spines": 64,
                "num_leaves": 256,
                "num_sites": 20,
                "num_prefixes_per_node": 11,
                "prefix_seed": 20250903,
                "interfaces": [
                    "po1910",
                    *(f"po1910.{vlan}" for vlan in range(100, 164)),
                ],
            },
            {
                key: injection[key]
                for key in (
                    "num_spines",
                    "num_leaves",
                    "num_sites",
                    "num_prefixes_per_node",
                    "prefix_seed",
                    "interfaces",
                )
            },
        )
        periodic_tasks = playbook.periodic_tasks
        assert periodic_tasks is not None
        periodic = periodic_tasks[0]
        params_list = periodic.params_list
        assert params_list is not None
        params_json = params_list[0].json_params
        assert params_json is not None
        self.assertEqual(1, periodic.interval)
        self.assertFalse(periodic.terminate_on_error)
        self.assertEqual(
            {"hostname": "eb04.lab.ash6", "profile": "cold_boot_64_256_leaf"},
            json.loads(params_json),
        )
        cold_boot_actions = [
            params["action"]
            for step in playbook.stages[0].steps
            if (params := _step_params(step)).get("custom_step_name")
            == "openr_scale_cold_boot"
        ]
        self.assertEqual(
            ["baseline", "mark_reboot", "activate", "recover", "finalize"],
            cold_boot_actions,
        )
