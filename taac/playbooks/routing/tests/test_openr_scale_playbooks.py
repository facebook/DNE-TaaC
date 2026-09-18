# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

import json
import typing as t
import unittest

from taac.playbooks.routing.openr_scale_playbooks import (
    get_openr_scale_kvstore_injection_playbook,
)


def _step_params(step: object) -> dict[str, t.Any]:
    step_params = getattr(step, "step_params", None)
    json_params = getattr(step_params, "json_params", None)
    if not isinstance(json_params, str):
        raise AssertionError("custom step is missing serialized parameters")
    return t.cast(dict[str, t.Any], json.loads(json_params))


class OpenRScalePlaybookTest(unittest.TestCase):
    def test_injection_precedes_single_validation_with_shared_topology(self) -> None:
        playbook = get_openr_scale_kvstore_injection_playbook(
            helper_name="helper.example.com",
            dut_name="dut.example.com",
            dut_inband_address="2001:db8::1",
            dut_mgmt_addresses=["2001:db8::2"],
            num_spines=2,
            num_leaves=3,
            num_control_nodes=1,
            num_sites=4,
            ecmp_width=5,
            prefixes_per_node=6,
            dut_role="spine",
            area="area-7",
            prefix_seed=8,
        )

        self.assertEqual([], list(playbook.postchecks or ()))
        self.assertEqual(1, len(playbook.stages))
        self.assertEqual(2, len(playbook.stages[0].steps))
        injection = _step_params(playbook.stages[0].steps[0])
        validation = _step_params(playbook.stages[0].steps[1])
        self.assertEqual(
            {
                "custom_step_name": "openr_scale_injection",
                "num_spines": 2,
                "num_leaves": 3,
                "num_super_spines": 1,
                "num_sites": 4,
                "num_prefixes_per_node": 6,
                "dut_role": "spine",
                "area": "area-7",
                "prefix_seed": 8,
                "extra_flags": ["--num_pods=5"],
            },
            {
                key: injection[key]
                for key in (
                    "custom_step_name",
                    "num_spines",
                    "num_leaves",
                    "num_super_spines",
                    "num_sites",
                    "num_prefixes_per_node",
                    "dut_role",
                    "area",
                    "prefix_seed",
                    "extra_flags",
                )
            },
        )
        self.assertEqual(
            {
                "custom_step_name": "openr_scale_kvstore_state",
                "seeds": [8],
                "num_spines": 2,
                "num_leaves": 3,
                "num_control_nodes": 1,
                "num_sites": 4,
                "ecmp_width": 5,
                "prefixes_per_node": 6,
                "dut_role": "spine",
                "area": "area-7",
                "checkpoint": "single",
            },
            {
                key: validation[key]
                for key in (
                    "custom_step_name",
                    "seeds",
                    "num_spines",
                    "num_leaves",
                    "num_control_nodes",
                    "num_sites",
                    "ecmp_width",
                    "prefixes_per_node",
                    "dut_role",
                    "area",
                    "checkpoint",
                )
            },
        )
        for merge_only_field in ("state_key", "action", "owner"):
            self.assertNotIn(merge_only_field, validation)
        self.assertFalse(any("fingerprint" in key for key in validation))
