# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

import json
import unittest

from taac.playbooks.routing.bgp_ebb_playbooks import (
    get_bgp_ebb_ebgp_route_oscillation_playbook,
)
from taac.test_as_a_config import types as taac_types


def _step_payload(step: taac_types.Step) -> dict:
    params = step.step_params
    if params is None or params.json_params is None:
        raise AssertionError("custom step is missing serialized parameters")
    return json.loads(params.json_params)


class BgpRouteOscillationPlaybookTest(unittest.TestCase):
    def test_ebgp_playbook_wires_complete_compact_blocks(self) -> None:
        playbook = get_bgp_ebb_ebgp_route_oscillation_playbook(
            device_name="dut.example.com",
            peergroup_ibgp_v6="IBGP_V6",
            peergroup_ibgp_v4="IBGP_V4",
            expected_established_sessions=744,
        )

        payload = _step_payload(playbook.stages[0].steps[0])
        self.assertEqual(
            (0, 750),
            (payload["prefix_start_index"], payload["prefix_end_index"]),
        )
