# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

import json
import unittest

from taac.playbooks.playbook_definitions import (
    create_openr_subif_adjacency_scale_playbook,
)


def _custom_step_params(step) -> dict:
    return json.loads(step.step_params.json_params)


def _task(step) -> tuple[str, str | None, dict]:
    outer = json.loads(step.input_json)
    task = outer["task"]
    return (
        task["task_name"],
        task.get("hostname"),
        json.loads(task["params"]["json_params"]),
    )


def _point_check_params(check) -> dict:
    return json.loads(check.check_params.json_params)


def _validation_check(step) -> dict:
    step_input = json.loads(step.input_json)
    check = step_input["point_in_time_checks"][0]
    return json.loads(check["check_params"]["json_params"])


class OpenRSubifAdjacencyScalePlaybookTest(unittest.TestCase):
    def test_orders_setup_validation_and_performance_steps(self) -> None:
        playbook = create_openr_subif_adjacency_scale_playbook(
            dut_name="dut.example.com",
            peer_name="peer.example.com",
            port_channel="Port-Channel42",
            setup_script_path="/mnt/flash/setup_portchannel_subinterfaces.sh",
            num_subinterfaces=4,
            start_vlan=100,
            dut_octet=2,
            peer_octet=1,
            baseline_neighbor_count=2,
            expected_neighbor_count=5,
            postcheck_retry_count=7,
            postcheck_retry_delay_seconds=2.5,
        )

        self.assertEqual([], list(playbook.postchecks or ()))
        self.assertEqual(
            {
                "expected_neighbor_count": 2,
            },
            _point_check_params((playbook.prechecks or [])[0]),
        )
        self.assertEqual(1, len(playbook.stages))
        steps = playbook.stages[0].steps
        self.assertEqual(5, len(steps))

        performance_start = _custom_step_params(steps[0])
        dut_task_name, dut_outer_hostname, dut_setup = _task(steps[1])
        peer_task_name, peer_outer_hostname, peer_setup = _task(steps[2])
        adjacency_check = _validation_check(steps[3])
        performance_validate = _custom_step_params(steps[4])

        self.assertEqual(
            {
                "custom_step_name": "openr_scale_performance",
                "action": "start",
                "dut_name": "dut.example.com",
                "profile": "subif_adjacency",
                "phase": "subif_adjacency",
                "state_key": "openr_scale_test_1_subif_adjacency_performance",
            },
            performance_start,
        )
        self.assertEqual("run_commands_on_shell", dut_task_name)
        self.assertEqual("dut.example.com", dut_outer_hostname)
        self.assertEqual(
            {
                "hostname": "dut.example.com",
                "cmds": [
                    "bash sudo timeout 600 bash "
                    "/mnt/flash/setup_portchannel_subinterfaces.sh "
                    "Port-Channel42 4 100 2"
                ],
                "validate_output": True,
            },
            dut_setup,
        )
        self.assertEqual("run_commands_on_shell", peer_task_name)
        self.assertEqual("peer.example.com", peer_outer_hostname)
        self.assertEqual(
            {
                "hostname": "peer.example.com",
                "cmds": [
                    "bash sudo timeout 600 bash "
                    "/mnt/flash/setup_portchannel_subinterfaces.sh "
                    "Port-Channel42 4 100 1"
                ],
                "validate_output": True,
            },
            peer_setup,
        )
        self.assertEqual(5, adjacency_check["expected_neighbor_count"])
        self.assertEqual(7, adjacency_check["retry_count"])
        self.assertEqual(2.5, adjacency_check["retry_delay_seconds"])
        self.assertEqual(1.0, adjacency_check["retry_delay_multiplier"])
        self.assertNotEqual(steps[3].name, steps[2].name)
        self.assertEqual(
            {
                "custom_step_name": "openr_scale_performance",
                "action": "validate",
                "dut_name": "dut.example.com",
                "profile": "subif_adjacency",
                "phase": "subif_adjacency",
                "state_key": "openr_scale_test_1_subif_adjacency_performance",
            },
            performance_validate,
        )

        self.assertEqual(1, len(playbook.cleanup_steps or ()))
        self.assertEqual(
            {
                "custom_step_name": "openr_scale_performance_cleanup",
                "action": "cleanup",
                "dut_name": "dut.example.com",
                "profile": "subif_adjacency",
                "phase": "subif_adjacency",
                "state_key": "openr_scale_test_1_subif_adjacency_performance",
            },
            _custom_step_params((playbook.cleanup_steps or [])[0]),
        )
