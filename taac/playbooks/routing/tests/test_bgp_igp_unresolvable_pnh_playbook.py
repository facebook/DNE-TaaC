# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

import json
import unittest

from taac.constants import BgpPlusPlusProfile
from taac.playbooks.routing.bgp_ebb_playbooks import (
    get_bgp_ebb_igp_unresolvable_pnh_playbook,
)
from taac.test_as_a_config import types as taac_types


def _step_payload(step: taac_types.Step) -> dict:
    params = step.step_params
    if params is None or params.json_params is None:
        raise AssertionError("custom step is missing serialized parameters")
    return json.loads(params.json_params)


class BgpIgpUnresolvablePnhPlaybookTest(unittest.TestCase):
    def test_playbook_wires_geometry_full_restore_and_fallback_cleanup(self) -> None:
        local_link = {
            "ifName": "po1",
            "ipv4": "10.0.0.1",
            "ipv6": "fe80::1",
            "metric": 10,
        }
        other_link = {
            "ifName": "po1",
            "ipv4": "10.0.0.2",
            "ipv6": "fe80::2",
            "metric": 10,
        }
        playbook = get_bgp_ebb_igp_unresolvable_pnh_playbook(
            device_name="dut.example.com",
            peergroup_ibgp_v6="IBGP_V6",
            peergroup_ibgp_v4="IBGP_V4",
            local_link=local_link,
            other_link=other_link,
            expected_established_sessions=1272,
            profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
            count=63,
            step_size=2,
        )

        self.assertEqual(1, len(playbook.stages))
        self.assertEqual(1, len(playbook.stages[0].steps))
        payload = _step_payload(playbook.stages[0].steps[0])
        self.assertEqual("bgp_igp_unresolvable_pnh", payload["custom_step_name"])
        self.assertEqual(63, payload["count"])
        self.assertEqual(2, payload["step"])
        self.assertEqual(20, payload["delete_count"])
        self.assertEqual(4, len(payload["restore_start_ipv4s"]))
        self.assertEqual(4, len(payload["restore_start_ipv6s"]))
        self.assertEqual(local_link, payload["local_link"])
        self.assertEqual(other_link, payload["other_link"])
        self.assertIsNotNone(playbook.cleanup_steps)
        assert playbook.cleanup_steps is not None
        self.assertEqual(1, len(playbook.cleanup_steps))
