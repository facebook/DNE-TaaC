# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Unit tests for the RBB SRv6 playbook factories (full S02-S28 coverage)."""

import json
import unittest

from taac.playbooks.routing.factories.qual_rbb.rbb_srv6_playbook import (
    create_rbb_srv6_3_usids_playbook,
    create_rbb_srv6_te_baseline_playbook,
)
from taac.test_as_a_config.types import StepName
from taac.testconfigs.routing.util.bgp_rbb_scenario_profiles import (
    SRV6_3_USIDS_PROFILE,
    SRV6_TE_BASELINE_PROFILE,
)


def _all_steps(playbook):
    steps = []
    for stage in playbook.stages or []:
        steps.extend(stage.steps or [])
    return steps


def _run_task_names(playbook):
    names = []
    for step in _all_steps(playbook):
        if step.name == StepName.RUN_TASK_STEP:
            run_task_input = json.loads(step.input_json)
            names.append(run_task_input["task"]["task_name"])
    return names


def _stage_descriptions(playbook):
    return [stage.description or "" for stage in (playbook.stages or [])]


def _joined_descriptions(playbook):
    return " || ".join(_stage_descriptions(playbook))


class RbbSrv6ThreeUsidsPlaybookTest(unittest.TestCase):
    def test_playbook_shape(self) -> None:
        pb = create_rbb_srv6_3_usids_playbook(SRV6_3_USIDS_PROFILE)
        self.assertEqual(pb.name, "bgp_rbb_srv6_3_usids")
        # Full S02-S28 coverage: control-plane + device + IXIA traffic stages.
        self.assertGreaterEqual(len(pb.stages or []), 15)
        self.assertTrue(pb.prechecks)
        self.assertTrue(pb.postchecks)

    def test_control_plane_gates_present(self) -> None:
        # Increment A: core link-up (S02-S05), OpenR (S06/S13), iBGP (S07).
        desc = _joined_descriptions(create_rbb_srv6_3_usids_playbook(SRV6_3_USIDS_PROFILE))
        self.assertIn("S02-S05", desc)
        self.assertIn("S06", desc)
        self.assertIn("S07", desc)

    def test_full_gate_sequence_present(self) -> None:
        desc = _joined_descriptions(create_rbb_srv6_3_usids_playbook(SRV6_3_USIDS_PROFILE))
        for gate in ("S08-S09", "S10", "S11", "S12", "S19", "S21", "S22-S23",
                     "S24-S25", "S26", "S27", "S28"):
            self.assertIn(gate, desc, f"missing gate {gate}")

    def test_uses_registered_rbb_tasks(self) -> None:
        pb = create_rbb_srv6_3_usids_playbook(SRV6_3_USIDS_PROFILE)
        task_names = set(_run_task_names(pb))
        self.assertIn("rbb_srv6_program", task_names)
        self.assertIn("rbb_ixia_edge_l3", task_names)
        self.assertIn("rbb_srv6_direct_route", task_names)
        self.assertIn("rbb_srv6_verify", task_names)
        self.assertIn("rbb_srv6_counter_delta", task_names)

    def test_counter_delta_snapshot_then_assert(self) -> None:
        pb = create_rbb_srv6_3_usids_playbook(SRV6_3_USIDS_PROFILE)
        actions = []
        for step in _all_steps(pb):
            if step.name == StepName.RUN_TASK_STEP:
                task = json.loads(step.input_json)["task"]
                if task["task_name"] == "rbb_srv6_counter_delta":
                    inner = json.loads(task["params"]["json_params"])
                    actions.append(inner["action"])
        # Two snapshots (R1 encap, R2 decap) then two asserts.
        self.assertEqual(actions, ["snapshot", "snapshot", "assert", "assert"])

    def test_direct_route_installed_then_deleted(self) -> None:
        pb = create_rbb_srv6_3_usids_playbook(SRV6_3_USIDS_PROFILE)
        actions = []
        for step in _all_steps(pb):
            if step.name == StepName.RUN_TASK_STEP:
                run_task_input = json.loads(step.input_json)
                task = run_task_input["task"]
                if task["task_name"] == "rbb_srv6_direct_route":
                    inner = json.loads(task["params"]["json_params"])
                    actions.append(inner["action"])
        self.assertEqual(actions, ["install", "delete"])

    def test_has_validation_steps(self) -> None:
        pb = create_rbb_srv6_3_usids_playbook(SRV6_3_USIDS_PROFILE)
        validation_steps = [
            s for s in _all_steps(pb) if s.name == StepName.VALIDATION_STEP
        ]
        # Control-plane (OpenR, iBGP) + traffic loss validations.
        self.assertGreaterEqual(len(validation_steps), 4)

    def test_device_path_only_slice(self) -> None:
        # include_traffic=False → no IXIA traffic / counter-delta, but the
        # control-plane + underlay gates still run (non-destructive).
        pb = create_rbb_srv6_3_usids_playbook(
            SRV6_3_USIDS_PROFILE, include_traffic=False
        )
        task_names = set(_run_task_names(pb))
        self.assertNotIn("rbb_srv6_counter_delta", task_names)
        self.assertNotIn("rbb_ixia_edge_l3", task_names)
        desc = _joined_descriptions(pb)
        self.assertIn("S02-S05", desc)
        self.assertIn("S07", desc)
        self.assertIn("S21", desc)


class RbbSrv6TeBaselinePlaybookTest(unittest.TestCase):
    def test_baseline_has_no_direct_route(self) -> None:
        pb = create_rbb_srv6_te_baseline_playbook(SRV6_TE_BASELINE_PROFILE)
        self.assertNotIn("rbb_srv6_direct_route", _run_task_names(pb))

    def test_baseline_has_control_plane_gates(self) -> None:
        desc = _joined_descriptions(
            create_rbb_srv6_te_baseline_playbook(SRV6_TE_BASELINE_PROFILE)
        )
        self.assertIn("S02-S05", desc)
        self.assertIn("S06", desc)
        self.assertIn("S07", desc)

    def test_baseline_traffic_stage_gated_on_include_traffic(self) -> None:
        # With traffic on, the IXIA edge + baseline-traffic stages are present.
        on = _joined_descriptions(
            create_rbb_srv6_te_baseline_playbook(
                SRV6_TE_BASELINE_PROFILE, include_traffic=True
            )
        )
        self.assertIn("baseline traffic over BGPD-owned SRv6 path", on)
        self.assertIn("enable IXIA-facing L3 edge", on)
        # With traffic off (device-path-only), the IXIA/traffic stages and the
        # IXIA pre/postchecks are skipped so no null-session InvokeIxiaApiStep.
        pb_off = create_rbb_srv6_te_baseline_playbook(
            SRV6_TE_BASELINE_PROFILE, include_traffic=False
        )
        off = _joined_descriptions(pb_off)
        self.assertNotIn("baseline traffic over BGPD-owned SRv6 path", off)
        self.assertNotIn("enable IXIA-facing L3 edge", off)
        self.assertFalse(pb_off.prechecks)
        self.assertFalse(pb_off.postchecks)
        # Control-plane + SRv6-program gates still run device-path-only.
        self.assertIn("S02-S05", off)
        self.assertIn("S07", off)


if __name__ == "__main__":
    unittest.main()
