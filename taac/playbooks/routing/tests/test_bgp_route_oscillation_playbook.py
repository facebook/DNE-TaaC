# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

import json
import unittest

from taac.constants import BgpPlusPlusProfile
from taac.playbooks.routing.bgp_ebb_playbooks import (
    get_bgp_ebb_ebgp_route_oscillation_playbook,
    get_bgp_ebb_ibgp_route_oscillation_playbook,
)
from taac.stages.stage_definitions import (
    create_validated_bgp_route_oscillations_stage,
    create_validated_ebgp_route_oscillations_stage,
)
from taac.test_as_a_config import types as taac_types


EXPECTED_IBGP_POOLS = [
    f"PREFIX_POOL_IBGP_IPV{afi}_PLANE_{plane}_REMOTE_EB"
    for afi in (4, 6)
    for plane in range(1, 5)
]
DEFAULT_BGP_MON_PREFIX = "2401:db00:e50d:22:a::/80"
CUSTOM_PARENT_PREFIX = "2001:db8:ffff::/80"


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
        legacy = create_validated_ebgp_route_oscillations_stage(
            device_name="dut.example.com",
            expected_established_sessions=744,
            parent_prefixes_to_ignore=[DEFAULT_BGP_MON_PREFIX],
        )
        self.assertEqual(
            legacy.steps[0].description, playbook.stages[0].steps[0].description
        )
        self.assertEqual(
            [DEFAULT_BGP_MON_PREFIX],
            payload["parent_prefixes_to_ignore"],
        )
        self.assertEqual(_step_payload(legacy.steps[0]), payload)

    def test_ebgp_playbook_preserves_topology_derived_pool_identity(self) -> None:
        names_by_afi = {
            "ipv4": "ROUTE.POOL[V4]",
            "ipv6": "ROUTE+POOL(V6)",
        }
        playbook = get_bgp_ebb_ebgp_route_oscillation_playbook(
            device_name="dut.example.com",
            peergroup_ibgp_v6="IBGP_V6",
            peergroup_ibgp_v4="IBGP_V4",
            expected_established_sessions=744,
            prefix_pool_regex=r"^(?:ROUTE\.POOL\[V4\]|ROUTE\+POOL\(V6\))$",
            expected_prefix_pool_names=tuple(names_by_afi.values()),
            prefix_pool_names_by_afi=names_by_afi,
        )

        payload = _step_payload(playbook.stages[0].steps[0])
        self.assertEqual(
            r"^(?:ROUTE\.POOL\[V4\]|ROUTE\+POOL\(V6\))$",
            payload["prefix_pool_regex"],
        )
        self.assertEqual(
            list(names_by_afi.values()), payload["expected_prefix_pool_names"]
        )
        self.assertEqual(names_by_afi, payload["prefix_pool_names_by_afi"])

    def test_ibgp_playbook_wires_exact_multi_plane_contract(self) -> None:
        expected_parent_prefixes_to_ignore = [
            CUSTOM_PARENT_PREFIX,
            DEFAULT_BGP_MON_PREFIX,
        ]
        playbook = get_bgp_ebb_ibgp_route_oscillation_playbook(
            device_name="dut.example.com",
            peergroup_ibgp_v6="IBGP_V6",
            peergroup_ibgp_v4="IBGP_V4",
            expected_established_sessions=1272,
            profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
            parent_prefixes_to_ignore=[CUSTOM_PARENT_PREFIX],
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
        self.assertEqual(
            expected_parent_prefixes_to_ignore,
            payload["parent_prefixes_to_ignore"],
        )
        self.assertEqual(
            (0, 750), (payload["prefix_start_index"], payload["prefix_end_index"])
        )
        legacy = create_validated_bgp_route_oscillations_stage(
            device_name="dut.example.com",
            expected_established_sessions=1272,
            prefix_pool_regex=r"^PREFIX_POOL_IBGP_IPV[46]_PLANE_[1-4]_REMOTE_EB$",
            expected_prefix_pool_names=EXPECTED_IBGP_POOLS,
            parent_prefixes_to_ignore=expected_parent_prefixes_to_ignore,
        )
        self.assertEqual(
            legacy.steps[0].description, playbook.stages[0].steps[0].description
        )
        self.assertEqual(_step_payload(legacy.steps[0]), payload)
