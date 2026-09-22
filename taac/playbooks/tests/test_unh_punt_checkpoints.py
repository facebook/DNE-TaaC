# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe
"""npi_cpu_036/037/038 snapshot checkpoints must name the stage they run in."""

import json
import unittest

from taac.playbooks.playbook_definitions import (
    create_cpu_queue_playbooks,
)
from taac.test_as_a_config import types as taac_types

UNH = {
    "npi_cpu_036_unh_dir_conn_host_to_low_queue",
    "npi_cpu_037_unh_remote_subnet_to_low_queue",
    "npi_cpu_038_unh_remote_host_route_to_low_queue",
}

ASIC_DROP_CASES = UNH | {"npi_cpu_039_mtu_exceed_to_low_queue"}


class UnhPuntCheckpointTest(unittest.TestCase):
    def test_cpu_039_warmboots_to_apply_and_restore_mtu(self) -> None:
        (playbook,) = [
            pb
            for pb in create_cpu_queue_playbooks(0, 2, 9, "eth1/32/1")
            if pb.name == "npi_cpu_039_mtu_exceed_to_low_queue"
        ]

        steps = playbook.stages[0].steps
        warmboot_indices = [
            index
            for index, step in enumerate(steps)
            if step.name == taac_types.StepName.SERVICE_INTERRUPTION_STEP
            and not json.loads(step.input_json or "{}").get(
                "create_cold_boot_file", False
            )
        ]
        convergence_indices = [
            index
            for index, step in enumerate(steps)
            if step.name == taac_types.StepName.SERVICE_CONVERGENCE_STEP
        ]
        ixia_api_steps = []
        custom_step_indices = {}
        mtu_verify_indices = {}
        unregister_index = None
        for index, step in enumerate(steps):
            if (
                step.step_params is not None
                and step.step_params.json_params is not None
            ):
                params = json.loads(step.step_params.json_params)
                if custom_step_name := params.get("custom_step_name"):
                    custom_step_indices[custom_step_name] = index
                    if custom_step_name == "verify_interface_mtu":
                        mtu_verify_indices[params["expected_mtu"]] = index
            if step.name == taac_types.StepName.REGISTER_PATCHER_STEP:
                patcher = json.loads(step.input_json or "{}")
                if patcher.get("name") == "mtu_exceed_patcher" and not patcher.get(
                    "register_patcher", True
                ):
                    unregister_index = index
            if step.name == taac_types.StepName.INVOKE_IXIA_API_STEP:
                if step.step_params is None or step.step_params.json_params is None:
                    self.fail("IXIA API step has no step_params")
                ixia_api_steps.append(
                    (index, json.loads(step.step_params.json_params)["api_name"])
                )

        self.assertEqual(len(warmboot_indices), 2)
        self.assertEqual(len(convergence_indices), 2)
        self.assertIsNotNone(unregister_index)
        self.assertLess(
            custom_step_indices["change_interface_mtu_patcher"],
            warmboot_indices[0],
        )
        self.assertLess(warmboot_indices[0], convergence_indices[0])
        self.assertLess(convergence_indices[0], mtu_verify_indices[1500])
        self.assertLess(unregister_index, warmboot_indices[1])
        self.assertLess(warmboot_indices[1], convergence_indices[1])
        self.assertEqual(
            [api_name for _, api_name in ixia_api_steps],
            [
                "stop_protocols",
                "start_and_verify_protocols",
                "clear_traffic_stats",
            ],
        )
        self.assertLess(convergence_indices[1], ixia_api_steps[0][0])
        self.assertLess(ixia_api_steps[-1][0], mtu_verify_indices[9000])
        self.assertLess(convergence_indices[1], mtu_verify_indices[9000])

        (queue_check,) = [
            check
            for check in playbook.snapshot_checks or []
            if "CPU_QUEUE" in str(check.name)
        ]
        self.assertEqual(
            queue_check.pre_snapshot_checkpoint_id,
            "stage.npi_cpu_039_mtu_exceed_to_low_queue."
            "step.apply_mtu_agent_convergence.end",
        )
        self.assertEqual(
            queue_check.post_snapshot_checkpoint_id,
            "stage.npi_cpu_039_mtu_exceed_to_low_queue."
            "step.mtu_exceed_traffic_window_end.end",
        )

    def test_asic_drop_cases_do_not_expect_cpu_punts(self) -> None:
        playbooks = {
            pb.name: pb
            for pb in create_cpu_queue_playbooks(0, 2, 9, "eth1/32/1")
            if pb.name in ASIC_DROP_CASES
        }

        self.assertEqual(set(playbooks), ASIC_DROP_CASES)
        for name, playbook in playbooks.items():
            queue_checks = [
                check
                for check in playbook.snapshot_checks or []
                if "CPU_QUEUE" in str(check.name)
            ]
            self.assertTrue(queue_checks, name)
            guarded_check = queue_checks[0]
            if guarded_check.input_json is None:
                self.fail(f"{name} CPU queue check has no input_json")
            check_input = json.loads(guarded_check.input_json)
            self.assertEqual(check_input["active_queues"], [], name)
            self.assertCountEqual(check_input["inactive_queues"], [2, 9], name)
            self.assertEqual(
                set(check_input["active_min_out_pps_per_queue"]),
                {"2", "9"},
                name,
            )

    def test_cpu_039_excludes_expected_hardware_drop_from_loss_check(self) -> None:
        (playbook,) = [
            pb
            for pb in create_cpu_queue_playbooks(0, 2, 9, "eth1/32/1")
            if pb.name == "npi_cpu_039_mtu_exceed_to_low_queue"
        ]
        (loss_check,) = [
            check
            for check in playbook.postchecks or []
            if "PACKET_LOSS" in str(check.name)
        ]
        if (
            loss_check.check_params is None
            or loss_check.check_params.json_params is None
        ):
            self.fail("CPU_039 packet-loss postcheck has no check_params")
        self.assertIn(
            "TEST_MTU_EXCEED_IPV6_TRAFFIC",
            json.loads(loss_check.check_params.json_params)["skip_traffic_items"],
        )

    def test_cpu_036_targets_the_directly_connected_host_without_static_route(
        self,
    ) -> None:
        (playbook,) = [
            pb
            for pb in create_cpu_queue_playbooks(0, 2, 9, "eth1/32/1")
            if pb.name == "npi_cpu_036_unh_dir_conn_host_to_low_queue"
        ]

        self.assertEqual(
            playbook.traffic_items_to_start,
            ["TEST_RAW_UNH_DIRECT_CONNECTED_HOST_IPV6_TRAFFIC"],
        )
        custom_step_names = []
        for stage in playbook.stages:
            for step in stage.steps:
                if (
                    step.step_params is not None
                    and step.step_params.json_params is not None
                ):
                    params = json.loads(step.step_params.json_params)
                    if custom_step_name := params.get("custom_step_name"):
                        custom_step_names.append(custom_step_name)
        self.assertNotIn(
            "register_cpu_queue_static_route_patcher",
            custom_step_names,
        )
        self.assertIn("dump_traffic_item_stats", custom_step_names)

    def test_checkpoints_reference_the_playbook_stage(self) -> None:
        pbs = [
            pb
            for pb in create_cpu_queue_playbooks(0, 2, 9, "eth1/32/1")
            if pb.name in UNH
        ]
        self.assertEqual({pb.name for pb in pbs}, UNH)
        for pb in pbs:
            (stage,) = pb.stages
            prefix = f"stage.{stage.id}.step."
            ids = [
                cid
                for c in pb.snapshot_checks or []
                for cid in (c.pre_snapshot_checkpoint_id, c.post_snapshot_checkpoint_id)
                if cid
            ]
            self.assertTrue(ids, pb.name)
            for cid in ids:
                self.assertTrue(cid.startswith(prefix), (pb.name, cid, prefix))

    def test_postcheck_tolerates_the_black_hole_window(self) -> None:
        for pb in create_cpu_queue_playbooks(0, 2, 9, "eth1/32/1"):
            if pb.name not in UNH:
                continue
            loss = [c for c in pb.postchecks or [] if "PACKET_LOSS" in str(c.name)]
            self.assertEqual(len(loss), 1, pb.name)
            input_json = loss[0].input_json
            if input_json is None:
                self.fail(f"{pb.name} packet-loss postcheck has no input_json")
            thresholds = json.loads(input_json)["thresholds"]
            self.assertEqual([t["str_value"] for t in thresholds], ["90000"], pb.name)
            self.assertCountEqual(
                thresholds[0]["names"],
                [
                    "BGP_PREFIX_TRAFFIC",
                    "BGP_PREFIX_TRAFFIC_V4",
                    "IPV6_TRAFFIC",
                    "TEST_RAW_UNH_DIRECT_CONNECTED_HOST_IPV6_TRAFFIC",
                ],
                pb.name,
            )
            check_params = loss[0].check_params
            if check_params is None or check_params.json_params is None:
                self.fail(f"{pb.name} packet-loss postcheck has no check_params")
            self.assertCountEqual(
                json.loads(check_params.json_params)["skip_traffic_items"],
                thresholds[0]["names"],
                pb.name,
            )

    def test_precheck_tolerates_missing_unh_traffic_items(self) -> None:
        for pb in create_cpu_queue_playbooks(0, 2, 9, "eth1/32/1"):
            if pb.name not in UNH:
                continue
            loss = [c for c in pb.prechecks or [] if "PACKET_LOSS" in str(c.name)]
            self.assertEqual(len(loss), 1, pb.name)
            input_json = loss[0].input_json
            check_params = loss[0].check_params
            if input_json is None:
                self.fail(f"{pb.name} packet-loss precheck has no input_json")
            if check_params is None or check_params.json_params is None:
                self.fail(f"{pb.name} packet-loss precheck has no check_params")
            names = json.loads(input_json)["thresholds"][0]["names"]
            self.assertCountEqual(
                names,
                [
                    "BGP_PREFIX_TRAFFIC",
                    "BGP_PREFIX_TRAFFIC_V4",
                    "IPV6_TRAFFIC",
                    "TEST_RAW_UNH_DIRECT_CONNECTED_HOST_IPV6_TRAFFIC",
                ],
                pb.name,
            )
            self.assertCountEqual(
                json.loads(check_params.json_params)["skip_traffic_items"],
                names,
                pb.name,
            )
