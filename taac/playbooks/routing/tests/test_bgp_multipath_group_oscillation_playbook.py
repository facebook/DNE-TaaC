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
    def test_stage_spans_configured_peer_range_and_uses_strict_targeting(self) -> None:
        stage = create_multipath_group_oscillation_stage(
            oscillation_interval_seconds=280
        )

        self.assertEqual(50, len(stage.steps))
        stop_steps = [
            step
            for step in stage.steps
            if step.description is not None and "Stop IPv4" in step.description
        ]
        self.assertEqual(
            [1, 3, 5, 7, 9, 11],
            [_ixia_args(step)["session_end_idx"] for step in stop_steps],
        )
        for step in stop_steps:
            self.assertEqual(1, _ixia_args(step)["expected_peer_count"])
            self.assertTrue(_ixia_args(step)["validate_session_range"])

        wait_steps = [
            step
            for step in stage.steps
            if step.name == taac_types.StepName.LONGEVITY_STEP
        ]
        self.assertEqual(
            1800, sum(_step_params(step)["duration"] for step in wait_steps)
        )
        self.assertEqual(
            [140, 140, 140, 140, 140, 140, 140, 140, 140, 140, 140, 140, 120],
            [_step_params(step)["duration"] for step in wait_steps],
        )

    def test_stage_requires_dual_stack_baseline_wide_enough_for_max_delta(
        self,
    ) -> None:
        stage = create_multipath_group_oscillation_stage(
            oscillation_interval_seconds=280
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
                min_peers_to_stop=12, max_peers_to_stop=11
            )
        with self.assertRaisesRegex(ValueError, "configured session count"):
            create_multipath_group_oscillation_stage(
                ipv4_session_count=10, max_peers_to_stop=11
            )
        with self.assertRaisesRegex(ValueError, "exactly six complete cycles"):
            create_multipath_group_oscillation_stage(test_duration_seconds=60)
        with self.assertRaisesRegex(ValueError, "exactly six complete cycles"):
            create_multipath_group_oscillation_stage(
                test_duration_seconds=1400,
                oscillation_interval_seconds=280,
            )

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
            [11, 11],
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
