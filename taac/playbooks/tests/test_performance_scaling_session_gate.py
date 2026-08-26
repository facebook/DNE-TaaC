# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""The perf-scaling egress-peer sweep gates each iteration on all expected BGP
sessions reaching Established before advertising prefixes.

Guards the per-iteration session-establish check wired into
``create_performance_scaling_egress_peer_sweep_playbook``: each sweep Stage must
carry exactly one gating validation step whose expected established-session count
equals that Stage's ``total_peer_count`` (2*n IBGP v6+v4 + 2*ebgp_peer_count
EBGP), placed right before the convergence (prefix-advertise + measure) step.
"""

import json
import unittest

from taac.playbooks.playbook_definitions import (
    create_performance_scaling_egress_peer_sweep_playbook,
)
from taac.test_as_a_config.types import StepName

_AGGREGATOR_STAGE_ID = "egress_sweep_aggregator"
_EBGP_PEER_COUNT = 1


class PerfScalingSessionGateTest(unittest.TestCase):
    def _sweep_playbook(self, egress_peer_counts):
        return create_performance_scaling_egress_peer_sweep_playbook(
            device_name="bag010.ash6",
            egress_peer_counts=egress_peer_counts,
            prefix_count=50000,
            ebgp_peer_count=_EBGP_PEER_COUNT,
        )

    def _sweep_stages(self, playbook):
        return [s for s in playbook.stages if s.id != _AGGREGATOR_STAGE_ID]

    def test_each_sweep_stage_gates_on_expected_session_count(self) -> None:
        counts = [100, 200, 300]
        stages = self._sweep_stages(self._sweep_playbook(counts))
        self.assertEqual(len(stages), len(counts))
        for stage, n in zip(stages, counts):
            expected = 2 * n + 2 * _EBGP_PEER_COUNT
            validation_steps = [
                st for st in stage.steps if st.name == StepName.VALIDATION_STEP
            ]
            self.assertEqual(
                len(validation_steps),
                1,
                f"stage {stage.id} must have exactly one session gate",
            )
            self.assertIn(
                str(expected),
                validation_steps[0].input_json or "",
                f"stage {stage.id} must gate on {expected} expected sessions",
            )

    def test_session_gate_immediately_precedes_convergence(self) -> None:
        # Sessions are validated after the device/IXIA reload and before the
        # convergence step advertises prefixes; the convergence step is last.
        stage = self._sweep_stages(self._sweep_playbook([100]))[0]
        self.assertGreaterEqual(len(stage.steps), 2)
        self.assertEqual(stage.steps[-2].name, StepName.VALIDATION_STEP)

    def test_cpu_burst_observation_exceeds_two_minute_gate(self) -> None:
        stage = self._sweep_stages(self._sweep_playbook([100]))[0]
        params = json.loads(stage.steps[-1].step_params.json_params)

        self.assertEqual(180, params["advertisement_settle_seconds"])
