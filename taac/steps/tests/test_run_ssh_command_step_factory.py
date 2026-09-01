# Copyright (c) Meta Platforms, Inc. and affiliates.
"""Unit tests for create_run_ssh_command_step."""

import json
import unittest

from taac.steps.step_definitions import create_run_ssh_command_step
from taac.test_as_a_config.thrift_types import StepName


class CreateRunSshCommandStepTest(unittest.TestCase):
    def test_default_omits_log_output(self):
        step = create_run_ssh_command_step(cmd="hostname")
        self.assertEqual(step.name, StepName.RUN_SSH_COMMAND_STEP)
        self.assertEqual(json.loads(step.step_params.json_params), {"cmd": "hostname"})

    def test_log_output_true_is_encoded(self):
        step = create_run_ssh_command_step(
            cmd="hostname", log_output=True, description="d", step_id="s1"
        )
        self.assertEqual(
            json.loads(step.step_params.json_params),
            {"cmd": "hostname", "log_output": True},
        )
        self.assertEqual(step.description, "d")
        self.assertEqual(step.id, "s1")
