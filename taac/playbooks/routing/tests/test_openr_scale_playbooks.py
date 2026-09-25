# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

import json
import typing as t
import unittest

from taac.playbooks.routing.openr_scale_playbooks import (
    get_openr_scale_kvstore_injection_playbook,
    get_openr_scale_kvstore_merge_playbook,
)
from openr.tests.scale.scripts.scale_key_names import (
    bbf_simple_node_names,
    expected_key_set,
)


def _step_params(step: object) -> dict[str, t.Any]:
    step_params = getattr(step, "step_params", None)
    json_params = getattr(step_params, "json_params", None)
    if not isinstance(json_params, str):
        raise AssertionError("custom step is missing serialized parameters")
    return t.cast(dict[str, t.Any], json.loads(json_params))


class OpenRScalePlaybookTest(unittest.TestCase):
    def test_performance_brackets_injection_before_semantic_validation(self) -> None:
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
        self.assertEqual(4, len(playbook.stages[0].steps))
        self.assertEqual(
            [
                "openr_scale_performance",
                "openr_scale_injection",
                "openr_scale_performance",
                "openr_scale_kvstore_state",
            ],
            [
                _step_params(step)["custom_step_name"]
                for step in playbook.stages[0].steps
            ],
        )
        self.assertEqual(
            ["start", "validate"],
            [
                _step_params(playbook.stages[0].steps[index])["action"]
                for index in (0, 2)
            ],
        )
        injection = _step_params(playbook.stages[0].steps[1])
        validation = _step_params(playbook.stages[0].steps[3])
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
        cleanup_steps = list(playbook.cleanup_steps or [])
        self.assertEqual(1, len(cleanup_steps))
        self.assertEqual(
            {
                "custom_step_name": "openr_scale_performance_cleanup",
                "action": "cleanup",
                "dut_name": "dut.example.com",
                "profile": "kvstore_injection",
                "phase": "single",
                "state_key": "openr_scale_test_2_performance",
            },
            _step_params(cleanup_steps[0]),
        )


_HELPER = "helper.example.com"
_DUT = "dut.example.com"
_DUT_INBAND = "2001:db8::10"
_MGMT_ADDRESSES = ["2001:db8::11", "2001:db8::12"]
_REMOTE_PATH = "/mnt/flash/scale_test_server"
_SEED_A = 20250903
_SEED_B = 20250904
_NUM_SPINES = 64
_NUM_LEAVES = 256
_NUM_CONTROL_NODES = 0
_NUM_SITES = 20
_ECMP_WIDTH = 8
_PREFIXES_PER_NODE = 11
_STATE_KEY = "openr_scale_kvstore_merge_adjacency_fingerprints"


def _playbook(
    num_spines: int = _NUM_SPINES,
    num_leaves: int = _NUM_LEAVES,
    num_control_nodes: int = _NUM_CONTROL_NODES,
    num_sites: int = _NUM_SITES,
    ecmp_width: int = _ECMP_WIDTH,
    prefixes_per_node: int = _PREFIXES_PER_NODE,
    seed_a: int = _SEED_A,
    seed_b: int = _SEED_B,
) -> t.Any:
    return get_openr_scale_kvstore_merge_playbook(
        helper_name=_HELPER,
        dut_name=_DUT,
        dut_inband_address=_DUT_INBAND,
        dut_mgmt_addresses=_MGMT_ADDRESSES,
        scale_tester_remote_path=_REMOTE_PATH,
        num_spines=num_spines,
        num_leaves=num_leaves,
        num_control_nodes=num_control_nodes,
        num_sites=num_sites,
        ecmp_width=ecmp_width,
        prefixes_per_node=prefixes_per_node,
        seed_a=seed_a,
        seed_b=seed_b,
        area="0",
        state_key=_STATE_KEY,
        injection_run_duration_sec=5,
        injection_timeout_sec=120,
    )


def _params(step: t.Any) -> dict[str, t.Any]:
    if step.step_params is None:
        raise AssertionError("custom Step must populate step_params")
    return t.cast(dict[str, t.Any], json.loads(step.step_params.json_params))


class OpenRScaleKvStoreMergePlaybookTest(unittest.TestCase):
    def test_sequence_has_independent_performance_brackets_for_a_and_b(self) -> None:
        playbook = _playbook()
        self.assertEqual("openr_scale_kvstore_merge_playbook", playbook.name)
        self.assertEqual([], list(playbook.prechecks or []))
        self.assertEqual([], list(playbook.postchecks or []))
        self.assertEqual([], list(playbook.snapshot_checks or []))
        self.assertEqual(1, len(playbook.stages))
        self.assertEqual(
            [
                "openr_scale_performance",
                "openr_scale_injection",
                "openr_scale_performance",
                "openr_scale_kvstore_state",
                "openr_scale_performance",
                "openr_scale_injection",
                "openr_scale_performance",
                "openr_scale_kvstore_state",
            ],
            [_params(step)["custom_step_name"] for step in playbook.stages[0].steps],
        )
        self.assertEqual(
            ["after_a", "after_b"],
            [
                _params(playbook.stages[0].steps[index])["checkpoint"]
                for index in (3, 7)
            ],
        )
        self.assertEqual(
            [
                ("start", "after_a"),
                ("validate", "after_a"),
                ("start", "after_b"),
                ("validate", "after_b"),
            ],
            [
                (
                    _params(playbook.stages[0].steps[index])["action"],
                    _params(playbook.stages[0].steps[index])["phase"],
                )
                for index in (0, 2, 4, 6)
            ],
        )

    def test_injections_use_distinct_identities_and_exact_runtime_flags(self) -> None:
        steps = _playbook().stages[0].steps
        injection_a = _params(steps[1])
        injection_b = _params(steps[5])

        self.assertEqual(
            [_SEED_A, _SEED_B], [injection_a["prefix_seed"], injection_b["prefix_seed"]]
        )
        self.assertNotEqual(injection_a["jq_var_prefix"], injection_b["jq_var_prefix"])
        for params in (injection_a, injection_b):
            self.assertEqual(["--num_pods=8"], params["extra_flags"])
            self.assertEqual(5, params["run_duration_sec"])
            self.assertEqual(120, params["run_timeout_sec"])
            self.assertEqual("bbf-simple", params["topology_type"])
            self.assertEqual(_NUM_CONTROL_NODES, params["num_super_spines"])
            self.assertEqual(_NUM_SITES, params["num_sites"])
            self.assertFalse(params["simulate_neighbors"])
            self.assertFalse(params["verify_routes"])
            self.assertNotIn("expected_received_key_vals_delta", params)

    def test_updated_expectations_are_derived_from_exact_key_sets(self) -> None:
        nodes = bbf_simple_node_names(
            _NUM_SPINES,
            _NUM_LEAVES,
            _NUM_CONTROL_NODES,
            _NUM_SITES,
            "leaf",
        )
        expected_a = expected_key_set(nodes, _SEED_A, _PREFIXES_PER_NODE)
        expected_b = expected_key_set(nodes, _SEED_B, _PREFIXES_PER_NODE)
        steps = _playbook().stages[0].steps

        self.assertEqual(4_068, len(expected_a))
        self.assertEqual(3_729, len(expected_b - expected_a))
        self.assertEqual(
            len(expected_a),
            _params(steps[1])["expected_updated_key_vals_delta"],
        )
        self.assertEqual(
            len(expected_b - expected_a),
            _params(steps[5])["expected_updated_key_vals_delta"],
        )

    def test_state_barriers_share_one_local_identity_and_cleanup_is_local(self) -> None:
        playbook = _playbook()
        steps = playbook.stages[0].steps
        state_a = _params(steps[3])
        state_b = _params(steps[7])
        self.assertEqual([_SEED_A], state_a["seeds"])
        self.assertEqual([_SEED_A, _SEED_B], state_b["seeds"])
        self.assertEqual(_STATE_KEY, state_a["state_key"])
        self.assertEqual(_STATE_KEY, state_b["state_key"])

        cleanup_steps = list(playbook.cleanup_steps or [])
        self.assertEqual(3, len(cleanup_steps))
        self.assertEqual(
            [
                {
                    "custom_step_name": "openr_scale_kvstore_state_cleanup",
                    "state_key": _STATE_KEY,
                },
                {
                    "custom_step_name": "openr_scale_performance_cleanup",
                    "action": "cleanup",
                    "dut_name": _DUT,
                    "profile": "kvstore_merge",
                    "phase": "after_b",
                    "state_key": f"{_STATE_KEY}_performance",
                },
                {
                    "custom_step_name": "openr_scale_performance_cleanup",
                    "action": "cleanup",
                    "dut_name": _DUT,
                    "profile": "kvstore_merge",
                    "phase": "after_a",
                    "state_key": f"{_STATE_KEY}_performance",
                },
            ],
            [_params(step) for step in cleanup_steps],
        )
