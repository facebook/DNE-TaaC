# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-strict

import json
from types import SimpleNamespace
from unittest.mock import patch

import later.unittest
from taac.playbooks.routing.bgp_ebb_playbooks import (
    get_bgp_ebb_longevity_playbook,
)
from taac.stages.stage_definitions import (
    create_longevity_churn_stage,
)
from taac.steps.step_definitions import (
    create_bgp_longevity_community_churn_step,
)
from taac.test_as_a_config import types as taac_types


def _payload(step: taac_types.Step) -> dict:
    params = step.step_params
    if params is None or params.json_params is None:
        raise AssertionError("custom step is missing serialized parameters")
    return json.loads(params.json_params)


class BgpLongevityPlaybookTest(later.unittest.TestCase):
    def test_step_factory_serializes_wall_clock_contract(self) -> None:
        step = create_bgp_longevity_community_churn_step(
            duration_seconds=14_400,
            cadence_seconds=60,
        )

        self.assertEqual(taac_types.StepName.CUSTOM_STEP, step.name)
        self.assertEqual(
            {
                "custom_step_name": "bgp_longevity_community_churn",
                "prefix_pool_regex": ".*IBGP.*PLANE_4.*",
                "community_count": 5,
                "duration_seconds": 14_400,
                "cadence_seconds": 60,
            },
            _payload(step),
        )

    def test_step_factory_rejects_invalid_parameters(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive integers"):
            create_bgp_longevity_community_churn_step(
                duration_seconds=0,
                cadence_seconds=60,
            )
        with self.assertRaisesRegex(ValueError, "prefix_pool_regex"):
            create_bgp_longevity_community_churn_step(
                duration_seconds=60,
                cadence_seconds=60,
                prefix_pool_regex=".*EBGP.*",
            )

    def test_stage_runs_churn_then_quiesces_for_final_validation(self) -> None:
        stage = create_longevity_churn_stage(test_duration_seconds=14_400)

        self.assertEqual(2, len(stage.steps))
        self.assertEqual(
            "bgp_longevity_community_churn",
            _payload(stage.steps[0])["custom_step_name"],
        )
        description = stage.steps[1].description
        if description is None:
            self.fail("quiesce step is missing a description")
        self.assertIn("Quiesce 300s", description)

    def test_playbook_duration_is_the_churn_window(self) -> None:
        target = (
            "neteng.test_infra.dne.taac.playbooks.routing."
            "bgp_ebb_playbooks.get_profile_checks"
        )
        with patch(target) as get_checks:
            get_checks.return_value = SimpleNamespace(
                prechecks=[], postchecks=[], snapshot_checks=[]
            )
            playbook = get_bgp_ebb_longevity_playbook(
                device_name="dut.example.com",
                duration=7_200,
                community_churn_frequency=30,
            )

        payload = _payload(playbook.stages[0].steps[0])
        self.assertEqual(7_200, payload["duration_seconds"])
        self.assertEqual(30, payload["cadence_seconds"])
        self.assertFalse(get_checks.call_args.args[1].check_bgp_convergence)
        self.assertFalse(playbook.periodic_tasks)
