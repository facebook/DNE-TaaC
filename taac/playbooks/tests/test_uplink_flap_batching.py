# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import json
import unittest

from taac.playbooks.playbook_definitions import (
    _build_uplink_flap_cleanup_steps,
    _build_uplink_flap_cycle_steps,
)
from taac.test_as_a_config import types as taac_types


def _flap_params(step: taac_types.Step) -> dict:
    if step.step_params is None:
        raise AssertionError(f"Step has no params: {step}")
    return json.loads(step.step_params.json_params or "{}")


class UplinkFlapBatchingTest(unittest.TestCase):
    def test_cycle_disables_then_enables_interfaces_in_ordered_pairs(self) -> None:
        interfaces = ["eth1", "eth2", "eth3", "eth4", "eth5"]

        steps = _build_uplink_flap_cycle_steps(
            interfaces_to_flap=interfaces,
            flap_interval_s=8,
            interface_batch_size=2,
        )

        flap_steps = [
            step
            for step in steps
            if step.name == taac_types.StepName.INTERFACE_FLAP_STEP
        ]
        self.assertEqual(
            [
                (False, ["eth1", "eth2"]),
                (False, ["eth3", "eth4"]),
                (False, ["eth5"]),
                (True, ["eth1", "eth2"]),
                (True, ["eth3", "eth4"]),
                (True, ["eth5"]),
            ],
            [
                (params["enable"], params["interfaces"])
                for params in map(_flap_params, flap_steps)
            ],
        )
        self.assertTrue(all(_flap_params(step)["delay"] == 8 for step in flap_steps))

    def test_cleanup_restores_interfaces_in_ordered_pairs(self) -> None:
        steps = _build_uplink_flap_cleanup_steps(
            interfaces_to_flap=["eth1", "eth2", "eth3", "eth4", "eth5"],
            interface_batch_size=2,
        )

        self.assertEqual(
            [
                (True, ["eth1", "eth2"]),
                (True, ["eth3", "eth4"]),
                (True, ["eth5"]),
            ],
            [
                (params["enable"], params["interfaces"])
                for params in map(_flap_params, steps)
            ],
        )
        self.assertTrue(
            all(not _flap_params(step).get("sequential", False) for step in steps)
        )
        self.assertTrue(all(_flap_params(step)["skip_start_traffic"] for step in steps))


if __name__ == "__main__":
    unittest.main()
