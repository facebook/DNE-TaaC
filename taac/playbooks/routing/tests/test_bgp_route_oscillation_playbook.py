# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

import json
import unittest

from taac.constants import BgpPlusPlusProfile
from taac.playbooks.routing.bgp_ebb_playbooks import (
    get_bgp_ebb_ebgp_route_oscillation_playbook,
    get_bgp_ebb_ibgp_route_oscillation_playbook,
)
from taac.test_as_a_config import types as taac_types


EXPECTED_IBGP_POOLS = [
    f"PREFIX_POOL_IBGP_IPV{afi}_PLANE_{plane}_REMOTE_EB"
    for afi in (4, 6)
    for plane in range(1, 5)
]


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

    def test_ibgp_playbook_wires_exact_multi_plane_contract(self) -> None:
        playbook = get_bgp_ebb_ibgp_route_oscillation_playbook(
            device_name="dut.example.com",
            peergroup_ibgp_v6="IBGP_V6",
            peergroup_ibgp_v4="IBGP_V4",
            expected_established_sessions=1272,
            profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
            parent_prefixes_to_ignore=["2001:db8:ffff::/80"],
        )

        self.assertEqual(1, len(playbook.stages))
        self.assertEqual(1, len(playbook.stages[0].steps))
        payload = _step_payload(playbook.stages[0].steps[0])
        self.assertEqual("bgp_route_oscillation", payload["custom_step_name"])
        self.assertEqual(EXPECTED_IBGP_POOLS, payload["expected_prefix_pool_names"])
        self.assertEqual(
            r"^PREFIX_POOL_IBGP_IPV[46]_PLANE_[1-4]_REMOTE_EB$",
            payload["prefix_pool_regex"],
        )
        self.assertEqual(1272, payload["expected_established_sessions"])
        self.assertEqual(["2001:db8:ffff::/80"], payload["parent_prefixes_to_ignore"])
        self.assertEqual(
            (0, 750), (payload["prefix_start_index"], payload["prefix_end_index"])
        )
