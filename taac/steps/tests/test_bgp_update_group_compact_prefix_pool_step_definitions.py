# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import json
import unittest

from taac.steps.step_definitions import (
    create_advertise_withdraw_prefixes_step,
    create_prepare_compact_bgp_prefix_pool_step,
)
from pyre_extensions import none_throws


class BgpUpdateGroupCompactPrefixPoolStepDefinitionsTest(unittest.TestCase):
    def test_prepare_serializes_safe_resize_contract(self) -> None:
        step = create_prepare_compact_bgp_prefix_pool_step(
            device_name="bag012.ash6",
            prefix_pool_regex=r"^PREFIX_POOL_IPV4_EBGP_UG_2_7_RUNTIME$",
            target_number_of_addresses=20,
            allowed_current_number_of_addresses=(100,),
            safe_number_of_addresses=100,
        )
        task = json.loads(none_throws(step.input_json))["task"]
        params = json.loads(task["params"]["json_params"])

        self.assertEqual("ixia_enable_disable_bgp_prefixes", task["task_name"])
        self.assertFalse(params["enable"])
        self.assertEqual(0, params["prefix_start_index"])
        self.assertNotIn("prefix_end_index", params)
        self.assertEqual(20, params["target_number_of_addresses"])
        self.assertEqual([100], params["allowed_current_number_of_addresses"])
        self.assertEqual(100, params["safe_number_of_addresses"])
        self.assertTrue(params["runtime_route_operation"])

    def test_runtime_route_operation_is_opt_in(self) -> None:
        legacy = create_advertise_withdraw_prefixes_step(
            "bag012.ash6",
            True,
            r"^PREFIX_POOL_IPV4_EBGP_UG_2_7_RUNTIME$",
            0,
            expected_prefix_pool_count=1,
        )
        runtime = create_advertise_withdraw_prefixes_step(
            "bag012.ash6",
            True,
            r"^PREFIX_POOL_IPV4_EBGP_UG_2_7_RUNTIME$",
            0,
            expected_prefix_pool_count=1,
            runtime_route_operation=True,
        )

        legacy_task = json.loads(none_throws(legacy.input_json))["task"]
        runtime_task = json.loads(none_throws(runtime.input_json))["task"]
        legacy_params = json.loads(legacy_task["params"]["json_params"])
        runtime_params = json.loads(runtime_task["params"]["json_params"])

        self.assertNotIn("runtime_route_operation", legacy_params)
        self.assertTrue(runtime_params["runtime_route_operation"])
