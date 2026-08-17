# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

import json
import unittest

from taac.constants import BgpPlusPlusProfile
from taac.playbooks.routing.bgp_ebb_playbooks import (
    get_bgp_ebb_multipath_group_oscillation_playbook,
)
from taac.stages.stage_definitions import (
    create_multipath_group_oscillation_stage,
)
from taac.testconfigs.routing.util.bgp_ebb_constants import (
    IXIA_BGP_MON_IC_PARENT_NETWORK,
)
from taac.test_as_a_config import types as taac_types


def _ixia_args(step: taac_types.Step) -> dict:
    params = step.step_params
    if params is None or params.json_params is None:
        raise AssertionError("IXIA step is missing serialized parameters")
    payload = json.loads(params.json_params)
    return json.loads(payload["args_json"])


def _step_params(step: taac_types.Step) -> dict:
    params = step.step_params
    if params is None or params.json_params is None:
        raise AssertionError("step is missing serialized parameters")
    return json.loads(params.json_params)


class BgpMultipathGroupOscillationPlaybookTest(unittest.TestCase):
    def test_stage_uses_path_aware_targeted_probe_workflow(self) -> None:
        stage = create_multipath_group_oscillation_stage(
            hostname="dut.example.com", oscillation_interval_seconds=280
        )

        self.assertEqual(2, len(stage.steps))
        workflow = _step_params(stage.steps[1])
        self.assertEqual("bgp_multipath_oscillation", workflow["custom_step_name"])
        self.assertEqual("dut.example.com", workflow["hostname"])
        self.assertEqual(1800, workflow["test_duration_seconds"])
        self.assertEqual(280, workflow["oscillation_interval_seconds"])
        self.assertEqual(1, workflow["min_peers_to_stop"])
        self.assertEqual(11, workflow["max_peers_to_stop"])
        self.assertEqual(2, workflow["probe_prefixes_per_afi"])
        self.assertEqual(2, workflow["stable_sample_count"])
        self.assertEqual(30, workflow["bgp_read_timeout_seconds"])

    def test_stage_requires_dual_stack_baseline_wide_enough_for_max_delta(
        self,
    ) -> None:
        stage = create_multipath_group_oscillation_stage(
            hostname="dut.example.com", oscillation_interval_seconds=280
        )
        baseline = stage.steps[0]

        self.assertIsNotNone(baseline.input_json)
        payload = json.loads(baseline.input_json or "{}")
        self.assertTrue(payload["fail_fast"])
        params = json.loads(
            payload["point_in_time_checks"][0]["check_params"]["json_params"]
        )
        self.assertEqual(["ipv4", "ipv6"], params["required_address_families"])
        self.assertEqual(12, params["expected_min_baseline_width"])

    def test_stage_rejects_invalid_peer_and_cycle_geometry(self) -> None:
        with self.assertRaisesRegex(ValueError, "peer-stop range"):
            create_multipath_group_oscillation_stage(
                hostname="dut.example.com", min_peers_to_stop=12, max_peers_to_stop=11
            )
        with self.assertRaisesRegex(ValueError, "configured session count"):
            create_multipath_group_oscillation_stage(
                hostname="dut.example.com", ipv4_session_count=10, max_peers_to_stop=11
            )
        with self.assertRaisesRegex(ValueError, "configured cycles"):
            create_multipath_group_oscillation_stage(
                hostname="dut.example.com", test_duration_seconds=60
            )
        with self.assertRaisesRegex(ValueError, "configured cycles"):
            create_multipath_group_oscillation_stage(
                hostname="dut.example.com",
                test_duration_seconds=1400,
                oscillation_interval_seconds=280,
            )

    def test_stage_allows_one_full_budget_validation_cycle(self) -> None:
        stage = create_multipath_group_oscillation_stage(
            hostname="dut.example.com",
            test_duration_seconds=280,
            oscillation_interval_seconds=280,
            cycle_count=1,
        )

        workflow = _step_params(stage.steps[1])
        self.assertEqual(1, workflow["cycle_count"])

    def test_playbook_adds_strict_fallback_cleanup_for_both_afis(self) -> None:
        playbook = get_bgp_ebb_multipath_group_oscillation_playbook(
            device_name="dut.example.com",
            peergroup_ibgp_v6="IBGP_V6",
            peergroup_ibgp_v4="IBGP_V4",
            expected_established_sessions=42,
            profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
        )

        cleanup_steps = playbook.cleanup_steps
        assert cleanup_steps is not None
        self.assertEqual(3, len(cleanup_steps))
        restore_args = _ixia_args(cleanup_steps[0])
        self.assertEqual(
            [".*IPV4_EBGP$", ".*IPV6_EBGP$"],
            [target["regex"] for target in restore_args["peer_ranges"]],
        )
        self.assertEqual(
            [140, 140],
            [target["session_end_idx"] for target in restore_args["peer_ranges"]],
        )
        self.assertEqual(140, _step_params(cleanup_steps[1])["duration"])

        validation = json.loads(cleanup_steps[2].input_json or "{}")
        point_checks = validation["point_in_time_checks"]
        self.assertEqual(2, len(point_checks))
        check_params = [
            json.loads(check["check_params"]["json_params"]) for check in point_checks
        ]
        session_params = next(
            params
            for params in check_params
            if "expected_established_session_count" in params
        )
        width_params = next(
            params for params in check_params if params.get("use_discovered_width")
        )
        self.assertEqual(42, session_params["expected_established_session_count"])
        self.assertEqual(
            [f"{IXIA_BGP_MON_IC_PARENT_NETWORK}::/80"],
            session_params["parent_prefixes_to_ignore"],
        )
        self.assertEqual(0, width_params["peers_stopped_delta"])
        self.assertTrue(width_params["use_discovered_prefixes"])
        self.assertTrue(width_params["use_discovered_width"])
