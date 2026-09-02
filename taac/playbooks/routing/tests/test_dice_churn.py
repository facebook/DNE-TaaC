# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""Contract tests for the unified DICE churn playbook renderer."""

from __future__ import annotations

import unittest

from taac.abstractions.churn.playbook import (
    attribute_churn_spec,
    ChurnImplementation,
    route_churn_spec,
    session_churn_spec,
)
from taac.playbooks.routing.dice_churn import (
    create_dice_unified_churn_playbook,
)
from taac.test_as_a_config import types as taac_types


class DiceUnifiedChurnPlaybookTest(unittest.TestCase):
    def test_all_churn_families_use_the_same_renderer_contract(self) -> None:
        cases = (
            (attribute_churn_spec, ChurnImplementation.ATTRIBUTE),
            (session_churn_spec, ChurnImplementation.SESSION),
            (route_churn_spec, ChurnImplementation.ROUTE),
        )
        for spec_factory, implementation in cases:
            with self.subTest(implementation=implementation):
                stage = taac_types.Stage(steps=[])
                spec = spec_factory(
                    playbook_name=f"{implementation.value}_churn",
                    device="dut0",
                    action_factory=lambda stage=stage: [stage],
                    setup_steps=(),
                    prechecks=(),
                    postchecks=(),
                    snapshot_checks=(),
                    periodic_tasks=(),
                )

                playbook = create_dice_unified_churn_playbook(spec=spec)

                self.assertEqual(implementation, spec.implementation)
                self.assertEqual(f"{implementation.value}_churn", playbook.name)
                self.assertEqual([stage], playbook.stages)

    def test_action_factory_must_produce_a_stage(self) -> None:
        spec = route_churn_spec(
            playbook_name="route_churn",
            device="dut0",
            action_factory=lambda: (),
            setup_steps=(),
            prechecks=(),
            postchecks=(),
            snapshot_checks=(),
            periodic_tasks=(),
        )
        with self.assertRaisesRegex(ValueError, "returned no stages"):
            create_dice_unified_churn_playbook(spec=spec)
