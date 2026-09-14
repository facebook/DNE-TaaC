# pyre-unsafe
"""npi_cpu_036/037/038 snapshot checkpoints must name the stage they run in."""
import json
import unittest

from taac.playbooks.playbook_definitions import create_cpu_queue_playbooks

UNH = {
    "npi_cpu_036_unh_dir_conn_host_to_low_queue",
    "npi_cpu_037_unh_remote_subnet_to_low_queue",
    "npi_cpu_038_unh_remote_host_route_to_low_queue",
}


class UnhPuntCheckpointTest(unittest.TestCase):
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
                for c in pb.snapshot_checks
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
            loss = [c for c in pb.postchecks if "PACKET_LOSS" in str(c.name)]
            self.assertEqual(len(loss), 1, pb.name)
            thresholds = json.loads(loss[0].input_json)["thresholds"]
            self.assertEqual([t["str_value"] for t in thresholds], ["90000"], pb.name)
