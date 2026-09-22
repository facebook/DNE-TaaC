# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe
"""npi_cpu_036/037/038 snapshot checkpoints must name the stage they run in."""

import json
import unittest

from taac.playbooks.playbook_definitions import (
    create_cpu_queue_playbooks,
)

UNH = {
    "npi_cpu_036_unh_dir_conn_host_to_low_queue",
    "npi_cpu_037_unh_remote_subnet_to_low_queue",
    "npi_cpu_038_unh_remote_host_route_to_low_queue",
}


class UnhPuntCheckpointTest(unittest.TestCase):
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
