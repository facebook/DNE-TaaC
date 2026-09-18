# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
"""Lifecycle tests for the Open/R scale KvStore merge TestConfig."""

import json
import unittest

from taac.testconfigs.routing.openr import (
    OPENR_SCALE_KVSTORE_INJECTION_TEST_CONFIG,
    OPENR_SCALE_KVSTORE_MERGE_TEST_CONFIG,
)
from taac.testconfigs.routing.openr.openr_scale_kvstore_merge_test_config import (
    EB02_MGMT_ADDRESS,
    EB04_INBAND_ADDRESS,
    EB04_MGMT_ADDRESS,
    SCALE_TESTER_REMOTE_PATH,
)
from taac.health_check.health_check import types as hc_types


def _params(value) -> dict:
    if value.params is None:
        raise AssertionError("Task must populate params")
    return json.loads(value.params.json_params)


def _step_params(step) -> dict:
    if step.step_params is None:
        raise AssertionError("custom Step must populate step_params")
    return json.loads(step.step_params.json_params)


class OpenRScaleKvStoreMergeTestConfigTest(unittest.TestCase):
    def test_binding_identity_inventory_and_no_ixia(self) -> None:
        config = OPENR_SCALE_KVSTORE_MERGE_TEST_CONFIG
        self.assertEqual("OPENR_SCALE_KVSTORE_MERGE", config.name)
        self.assertEqual("dne.test", config.basset_pool)
        self.assertEqual(
            {"eb04.lab.ash6": True, "eb02.lab.ash6": False},
            {endpoint.name: endpoint.dut for endpoint in config.endpoints},
        )
        self.assertEqual([], list(config.basic_port_configs or []))
        self.assertEqual([], list(config.basic_traffic_item_configs or []))
        self.assertEqual([], list(config.user_defined_traffic_items or []))
        self.assertEqual([], list(config.traffic_items_to_start or []))

    def test_setup_and_teardown_reuse_one_strict_isolation_task(self) -> None:
        config = OPENR_SCALE_KVSTORE_MERGE_TEST_CONFIG
        setup_tasks = list(config.setup_tasks or [])
        teardown_tasks = list(config.teardown_tasks or [])
        self.assertEqual(1, len(setup_tasks))
        self.assertEqual(1, len(teardown_tasks))
        self.assertEqual("openr_scale_isolation", setup_tasks[0].task_name)
        self.assertEqual("openr_scale_isolation", teardown_tasks[0].task_name)
        expected = {
            "hosts": ["eb04.lab.ash6", "eb02.lab.ash6"],
            "helper_hostname": "eb02.lab.ash6",
            "scale_tester_remote_path": SCALE_TESTER_REMOTE_PATH,
            "area": "0",
            "ttl_ms": 30_000,
            "wait_sec": 90,
            "batch_size": 500,
        }
        self.assertEqual(expected, _params(setup_tasks[0]))
        self.assertEqual(expected, _params(teardown_tasks[0]))
        self.assertNotIn("rm", json.dumps(expected))

    def test_injection_uses_helper_binary_and_dut_inband_path(self) -> None:
        config = OPENR_SCALE_KVSTORE_MERGE_TEST_CONFIG
        steps = config.playbooks[0].stages[0].steps
        for step in (steps[0], steps[2]):
            params = _step_params(step)
            self.assertEqual("eb02.lab.ash6", params["helper_name"])
            self.assertEqual("eb04.lab.ash6", params["dut_name"])
            self.assertEqual(EB04_INBAND_ADDRESS, params["dut_host"])
            self.assertEqual(
                [EB04_MGMT_ADDRESS, EB02_MGMT_ADDRESS],
                params["forbidden_dut_hosts"],
            )
            self.assertEqual(SCALE_TESTER_REMOTE_PATH, params["remote_path"])
            self.assertTrue(params["require_binary_present"])

    def test_no_eos_incompatible_health_check_or_postcheck_barrier(self) -> None:
        playbook = OPENR_SCALE_KVSTORE_MERGE_TEST_CONFIG.playbooks[0]
        checks = list(playbook.prechecks or []) + list(playbook.postchecks or [])
        self.assertNotIn(
            hc_types.CheckName.SYSTEMCTL_ACTIVE_STATE_CHECK,
            {check.name for check in checks},
        )
        self.assertEqual([], list(playbook.postchecks or []))

    def test_existing_semantic_test_2_binding_is_preserved(self) -> None:
        config = OPENR_SCALE_KVSTORE_INJECTION_TEST_CONFIG
        self.assertEqual("OPENR_SCALE_KVSTORE_INJECTION", config.name)
        self.assertEqual("dne.test", config.basset_pool)
        self.assertEqual(
            {"eb04.lab.ash6": True, "eb02.lab.ash6": False},
            {endpoint.name: endpoint.dut for endpoint in config.endpoints},
        )
        self.assertEqual([], list(config.setup_tasks or []))
        self.assertEqual(1, len(config.teardown_tasks or []))

        self.assertEqual(1, len(config.playbooks))
        playbook = config.playbooks[0]
        self.assertEqual("openr_scale_kvstore_injection_playbook", playbook.name)
        self.assertEqual(1, len(playbook.stages))
        self.assertEqual(2, len(playbook.stages[0].steps))
        injection = _step_params(playbook.stages[0].steps[0])
        validation = _step_params(playbook.stages[0].steps[1])

        self.assertEqual("openr_scale_injection", injection["custom_step_name"])
        self.assertEqual("eb02.lab.ash6", injection["helper_name"])
        self.assertEqual("eb04.lab.ash6", injection["dut_name"])
        self.assertEqual(EB04_INBAND_ADDRESS, injection["dut_host"])
        self.assertEqual(
            [EB04_MGMT_ADDRESS, EB02_MGMT_ADDRESS],
            injection["forbidden_dut_hosts"],
        )
        self.assertEqual(SCALE_TESTER_REMOTE_PATH, injection["remote_path"])
        self.assertEqual(20250903, injection["prefix_seed"])

        self.assertEqual("openr_scale_kvstore_state", validation["custom_step_name"])
        self.assertEqual("single", validation["checkpoint"])
        self.assertEqual([injection["prefix_seed"]], validation["seeds"])
        self.assertEqual(
            {
                "num_spines": 64,
                "num_leaves": 256,
                "num_control_nodes": 0,
                "num_sites": 20,
                "ecmp_width": 8,
                "prefixes_per_node": 11,
                "dut_role": "leaf",
                "area": "0",
            },
            {
                key: validation[key]
                for key in (
                    "num_spines",
                    "num_leaves",
                    "num_control_nodes",
                    "num_sites",
                    "ecmp_width",
                    "prefixes_per_node",
                    "dut_role",
                    "area",
                )
            },
        )
        for merge_only_field in ("state_key", "action", "owner"):
            self.assertNotIn(merge_only_field, validation)
        self.assertFalse(any("fingerprint" in key for key in validation))
