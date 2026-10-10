# Copyright (c) Meta Platforms, Inc. and affiliates.

import json
import unittest

from taac.playbooks import playbook_definitions
from taac.test_as_a_config import types as taac_types


_DUT = "ssw003.s001.m001.qzr1"
_PEER = "fsw003.p002.m001.qzr1"
_ENDPOINTS = {
    _DUT: ["eth1/10/1", "eth1/10/5"],
    _PEER: ["eth1/3/1", "eth1/3/5"],
}


def _health_check_params(speed: int) -> dict[str, object]:
    return {
        hostname: {
            "interfaces": [
                {"interface_name": interface, "expected_speed": speed}
                for interface in interfaces
            ]
        }
        for hostname, interfaces in _ENDPOINTS.items()
    }


def _step_params(step: taac_types.Step) -> dict[str, object]:
    params = step.step_params
    if params is None or params.json_params is None:
        return {}
    return json.loads(params.json_params)


class ReusableSpeedFlipPlaybookTest(unittest.TestCase):
    def test_builds_bidirectional_sequence_with_scoped_oper_checks(self) -> None:
        factory = getattr(
            playbook_definitions,
            "create_bidirectional_speed_flip_playbook",
            None,
        )
        self.assertIsNotNone(factory)
        if factory is None:
            return

        target_trigger = taac_types.Stage(description="target trigger")
        baseline_trigger = taac_types.Stage(description="baseline trigger")
        playbook = factory(
            name="SPEED_FLIP_TEST",
            endpoints=_ENDPOINTS,
            target_speed_in_gbps=100,
            baseline_health_check_params=_health_check_params(200),
            target_health_check_params=_health_check_params(100),
            patcher_name="change_speed_test_100",
            target_port_cage_count=1,
            target_trigger_stages=[target_trigger],
            baseline_trigger_stages=[baseline_trigger],
            iteration=3,
        )

        self.assertEqual(playbook.name, "SPEED_FLIP_TEST")
        self.assertEqual(playbook.iteration, 3)
        self.assertEqual(len(playbook.stages), 6)
        self.assertEqual(playbook.stages[2], target_trigger)
        self.assertEqual(playbook.stages[5], baseline_trigger)

        register_params = _step_params(playbook.stages[0].steps[0])
        self.assertTrue(register_params["register_patcher"])
        self.assertEqual(register_params["speed_in_gbps"], 100)
        self.assertEqual(register_params["target_port_cage_count"], 1)
        self.assertEqual(register_params["endpoints"], _ENDPOINTS)

        target_oper_steps = playbook.stages[1].steps[:-1]
        self.assertEqual(len(target_oper_steps), 2)
        self.assertEqual(target_oper_steps[0].device_regexes, [_DUT])
        self.assertEqual(target_oper_steps[1].device_regexes, [_PEER])
        self.assertEqual(
            _step_params(target_oper_steps[0])["interfaces"],
            _ENDPOINTS[_DUT],
        )
        self.assertEqual(
            _step_params(target_oper_steps[1])["interfaces"],
            _ENDPOINTS[_PEER],
        )

        unregister_params = _step_params(playbook.stages[3].steps[0])
        self.assertFalse(unregister_params["register_patcher"])
        self.assertEqual(unregister_params["patcher_name"], "change_speed_test_100")

        cleanup_steps = list(playbook.cleanup_steps or [])
        self.assertEqual(len(cleanup_steps), 1)
        self.assertFalse(_step_params(cleanup_steps[0])["register_patcher"])

    def test_test_config_wrapper_preserves_cleanup_steps(self) -> None:
        factory = getattr(
            playbook_definitions,
            "create_bidirectional_speed_flip_playbook",
            None,
        )
        self.assertIsNotNone(factory)
        if factory is None:
            return

        playbook = factory(
            name="SPEED_FLIP_TEST",
            endpoints=_ENDPOINTS,
            target_speed_in_gbps=100,
            baseline_health_check_params=_health_check_params(200),
            target_health_check_params=_health_check_params(100),
            patcher_name="change_speed_test_100",
            target_port_cage_count=1,
        )
        wrapped = playbook_definitions.create_speed_flip_test_config_playbook(
            built_playbook=playbook,
            snapshot_checks=[],
        )

        self.assertEqual(wrapped.cleanup_steps, playbook.cleanup_steps)
