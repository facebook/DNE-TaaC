# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Unit tests for the RBB SRv6 qualification playbook factory."""

import json
import unittest
from unittest import mock

from taac.health_check.health_check import types as hc_types
from taac.playbooks.routing.factories.qual_rbb.rbb_srv6_playbook import (
    create_rbb_srv6_3_usids_playbook,
)
from taac.test_as_a_config.types import StepName
from taac.testconfigs.routing.util import bgp_rbb_constants as C
from taac.testconfigs.routing.util.bgp_rbb_scenario_profiles import (
    SRV6_3_USIDS_PROFILE,
)
from taac.testconfigs.routing.util.bgp_rbb_topology import (
    CorePortChannel,
    IxiaEdge,
    NodeTopology,
    RbbTopology,
)


def _topology() -> RbbTopology:
    return RbbTopology(
        r1=NodeTopology(
            role="r1",
            hostname="rbb-r1.lab.example",
            core_pcs=(CorePortChannel("port-channel1", ("eth1/1",)),),
            ixia_edges=(IxiaEdge("eth1/5", "1/1"),),
        ),
        r2=NodeTopology(
            role="r2",
            hostname="rbb-r2.lab.example",
            core_pcs=(CorePortChannel("port-channel1", ("eth1/1",)),),
            ixia_edges=(IxiaEdge("eth1/5", "1/2"),),
        ),
        ixia_chassis="rbb-ixia.lab.example",
    )


def _tc1(*, include_traffic: bool):
    return create_rbb_srv6_3_usids_playbook(
        SRV6_3_USIDS_PROFILE,
        include_traffic=include_traffic,
        topology=_topology(),
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
        pb = _tc1(include_traffic=True)
        self.assertEqual(pb.name, "bgp_rbb_srv6_3_usids")
        # Full SRv6 lifecycle: control-plane + route + IXIA traffic stages.
        self.assertGreaterEqual(len(pb.stages or []), 10)
        self.assertTrue(pb.prechecks)
        self.assertTrue(pb.postchecks)

    def test_control_plane_gates_present(self) -> None:
        # Increment A: core link-up (S02-S05), OpenR (S06/S13), iBGP (S07).
        desc = _joined_descriptions(_tc1(include_traffic=True))
        self.assertIn("S02-S05", desc)
        self.assertIn("S06", desc)
        self.assertIn("S07", desc)

    def test_host_specific_bgp_checks_are_not_applied_to_entire_topology(self) -> None:
        # Device health checks default to TOPOLOGY scope. The shipped checks in
        # S07/S16 carry R1-specific peer allowlists, so they must run only on the
        # playbook anchor; explicit rbb_srv6_verify tasks cover both DUTs.
        # A pre-provisioned topology still validates the IXIA-facing sessions;
        # EDGE_EBGP_ENABLED controls setup tasks, not playbook evidence.
        with mock.patch.object(C, "EDGE_EBGP_ENABLED", False):
            pb = _tc1(include_traffic=True)
        for stage_prefix in ("S07", "S16"):
            stage = next(
                stage
                for stage in pb.stages or []
                if (stage.description or "").startswith(stage_prefix)
            )
            validation = next(
                step
                for step in stage.steps or []
                if step.name == StepName.VALIDATION_STEP
            )
            payload = json.loads(validation.input_json)
            checks = payload["point_in_time_checks"]
            self.assertEqual(len(checks), 1)
            self.assertEqual(checks[0]["check_scope"], hc_types.Scope.DEFAULT.value)

    def test_full_gate_sequence_present(self) -> None:
        desc = _joined_descriptions(_tc1(include_traffic=True))
        for gate in (
            "S10",
            "S11",
            "S19",
            "S21",
            "S22-S23",
            "S24-S25",
            "S26",
            "S27",
            "S28",
        ):
            self.assertIn(gate, desc, f"missing gate {gate}")

    def test_uses_registered_rbb_tasks(self) -> None:
        pb = _tc1(include_traffic=True)
        task_names = set(_run_task_names(pb))
        self.assertIn("rbb_srv6_direct_route", task_names)
        self.assertIn("rbb_srv6_verify", task_names)
        self.assertIn("rbb_srv6_counter_delta", task_names)

    def test_counter_delta_snapshot_then_assert(self) -> None:
        pb = _tc1(include_traffic=True)
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
        pb = _tc1(include_traffic=True)
        actions = []
        install_params = None
        for step in _all_steps(pb):
            if step.name == StepName.RUN_TASK_STEP:
                run_task_input = json.loads(step.input_json)
                task = run_task_input["task"]
                if task["task_name"] == "rbb_srv6_direct_route":
                    inner = json.loads(task["params"]["json_params"])
                    actions.append(inner["action"])
                    if inner["action"] == "install":
                        install_params = inner
        self.assertEqual(actions, ["install", "delete"])
        self.assertIsNotNone(install_params)
        self.assertEqual(
            install_params["srv6_segments"],
            [
                "2001:db8:6:27d6:7fff::",
            ],
        )
        self.assertEqual(install_params["srv6_tunnel_id"], "srv6_tunnel")
        self.assertTrue(pb.cleanup_steps)
        cleanup_task = json.loads(pb.cleanup_steps[0].input_json)["task"]
        cleanup_params = json.loads(cleanup_task["params"]["json_params"])
        self.assertEqual(cleanup_task["task_name"], "rbb_srv6_direct_route")
        self.assertEqual(cleanup_params["hostname"], "rbb-r1.lab.example")
        self.assertEqual(cleanup_params["action"], "delete")
        self.assertEqual(
            pb.cleanup_steps[-1].description,
            "Call Ixia API: stop_traffic",
        )

    def test_packet_loss_thresholds_use_percentage_metric(self) -> None:
        pb = _tc1(include_traffic=True)
        loss_checks = []
        for step in _all_steps(pb):
            if step.name != StepName.VALIDATION_STEP:
                continue
            payload = json.loads(step.input_json)
            loss_checks.extend(
                check
                for check in payload["point_in_time_checks"]
                if check["name"] == hc_types.CheckName.IXIA_PACKET_LOSS_CHECK.value
            )
        self.assertTrue(loss_checks)
        for check in loss_checks:
            check_input = json.loads(check["input_json"])
            self.assertTrue(check_input["thresholds"])
            for threshold in check_input["thresholds"]:
                self.assertEqual(
                    threshold["metric"], hc_types.PacketLossMetric.PERCENTAGE.value
                )

    def test_has_validation_steps(self) -> None:
        pb = _tc1(include_traffic=True)
        validation_steps = [
            s for s in _all_steps(pb) if s.name == StepName.VALIDATION_STEP
        ]
        # Control-plane (OpenR, iBGP) + traffic loss validations.
        self.assertGreaterEqual(len(validation_steps), 4)

    def test_s28_restarts_traffic_after_direct_route_delete(self) -> None:
        pb = _tc1(include_traffic=True)
        s28 = next(
            stage
            for stage in pb.stages or []
            if (stage.description or "").startswith("S28")
        )
        descriptions = [step.description or "" for step in s28.steps or []]
        self.assertIn("Clear traffic statistics", descriptions)
        self.assertIn("Call Ixia API: start_traffic", descriptions)
        self.assertIn("S28 post-delete traffic no-loss", descriptions)
        self.assertIn("Call Ixia API: stop_traffic", descriptions)

    def test_device_path_only_slice(self) -> None:
        # include_traffic=False → no IXIA traffic / counter-delta, but the
        # control-plane + underlay gates still run (non-destructive).
        pb = _tc1(include_traffic=False)
        task_names = set(_run_task_names(pb))
        self.assertNotIn("rbb_srv6_counter_delta", task_names)
        desc = _joined_descriptions(pb)
        self.assertIn("S02-S05", desc)
        self.assertIn("S07", desc)
        self.assertIn("S21", desc)
        self.assertEqual(pb.device_regexes, [r"^rbb\-r1\.lab\.example$"])

    def test_default_is_device_only(self) -> None:
        pb = create_rbb_srv6_3_usids_playbook(SRV6_3_USIDS_PROFILE)
        self.assertFalse(pb.prechecks)
        self.assertNotIn("rbb_srv6_counter_delta", _run_task_names(pb))


if __name__ == "__main__":
    unittest.main()
