# Copyright (c) Meta Platforms, Inc. and affiliates.

import json
import unittest

from taac.abstractions.compatibility.eos_bgpcpp_compatibility import (
    build_update_group_setting_override_cmd,
    UPDATE_GROUP_VERIFICATION_CMD,
)
from taac.testconfigs.routing.cicd_ebb_int_tc import (
    BAG010_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG,
    BAG010_STAGE1_FULL_SCALE_TEST_CONFIG_UG,
    BAG011_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG,
    BAG011_STAGE1_FULL_SCALE_TEST_CONFIG_UG,
    BAG012_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG,
    BAG012_STAGE1_FULL_SCALE_TEST_CONFIG_UG,
    BAG013_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG,
    BAG013_STAGE1_FULL_SCALE_TEST_CONFIG_UG,
)


_STAGE1_VARIANT_PAIRS = (
    (
        BAG010_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG,
        BAG010_STAGE1_FULL_SCALE_TEST_CONFIG_UG,
    ),
    (
        BAG011_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG,
        BAG011_STAGE1_FULL_SCALE_TEST_CONFIG_UG,
    ),
    (
        BAG012_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG,
        BAG012_STAGE1_FULL_SCALE_TEST_CONFIG_UG,
    ),
    (
        BAG013_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG,
        BAG013_STAGE1_FULL_SCALE_TEST_CONFIG_UG,
    ),
)


def _shell_commands(config) -> list[str]:
    return [
        command
        for task in config.setup_tasks or []
        if task.task_name == "run_commands_on_shell"
        for command in json.loads(task.params.json_params)["cmds"]
    ]


def _unique_task(config, task_name: str):
    matches = [task for task in config.setup_tasks or [] if task.task_name == task_name]
    if len(matches) != 1:
        raise AssertionError(
            f"expected exactly one {task_name!r} task, found {len(matches)}"
        )
    return matches[0]


class CicdEbbStage1UpdateGroupVariantsTest(unittest.TestCase):
    def test_variants_run_identical_playbooks(self) -> None:
        for non_ug, ug in _STAGE1_VARIANT_PAIRS:
            with self.subTest(non_ug=non_ug.name, ug=ug.name):
                self.assertEqual(
                    [playbook.name for playbook in non_ug.playbooks],
                    [playbook.name for playbook in ug.playbooks],
                )
                self.assertEqual(4, len(non_ug.playbooks))

    def test_variants_apply_and_verify_requested_runtime_state(self) -> None:
        for non_ug, ug in _STAGE1_VARIANT_PAIRS:
            with self.subTest(non_ug=non_ug.name, ug=ug.name):
                non_ug_commands = _shell_commands(non_ug)
                ug_commands = _shell_commands(ug)

                self.assertIn(
                    build_update_group_setting_override_cmd(False), non_ug_commands
                )
                self.assertNotIn(UPDATE_GROUP_VERIFICATION_CMD, non_ug_commands)
                self.assertEqual(
                    "validate_bgpcpp_config_on_device",
                    _unique_task(
                        non_ug,
                        "validate_bgpcpp_config_on_device",
                    ).task_name,
                )
                live_validation = _unique_task(
                    non_ug,
                    "validate_bgpcpp_update_group_state",
                )
                json_params = live_validation.params.json_params
                self.assertIsNotNone(json_params)
                assert json_params is not None
                self.assertEqual(
                    False,
                    json.loads(json_params)["expect_enabled"],
                )
                self.assertNotIn(
                    build_update_group_setting_override_cmd(False), ug_commands
                )
                self.assertNotIn(
                    build_update_group_setting_override_cmd(True), ug_commands
                )
                self.assertIn(UPDATE_GROUP_VERIFICATION_CMD, ug_commands)
                self.assertNotIn(
                    "validate_bgpcpp_update_group_state",
                    [task.task_name for task in ug.setup_tasks or []],
                )
