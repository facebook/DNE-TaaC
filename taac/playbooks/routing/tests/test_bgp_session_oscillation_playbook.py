# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

import json
import unittest

from taac.playbooks.routing.bgp_ebb_playbooks import (
    get_bgp_ebb_ebgp_session_oscillation_playbook,
    get_bgp_ebb_ibgp_plane_session_oscillation_playbook,
)
from taac.stages.stage_definitions import (
    create_validated_ebgp_session_oscillation_stage,
    create_validated_plane_bgp_session_oscillation_stage,
)
from taac.test_as_a_config import types as taac_types


def _step_payload(step: taac_types.Step) -> dict:
    params = step.step_params
    if params is None or params.json_params is None:
        raise AssertionError("custom step is missing serialized parameters")
    return json.loads(params.json_params)


class BgpSessionOscillationPlaybookTest(unittest.TestCase):
    def test_ebgp_playbook_matches_legacy_stage_for_odd_width(self) -> None:
        playbook = get_bgp_ebb_ebgp_session_oscillation_playbook(
            device_name="dut.example.com",
            peergroup_ibgp_v6="IBGP_V6",
            peergroup_ibgp_v4="IBGP_V4",
            ipv4_session_count=140,
            ipv6_session_count=140,
            expected_established_sessions=1272,
            sessions_per_cycle=71,
            parent_prefixes_to_ignore=["2001:db8:ffff::/80"],
        )
        legacy = create_validated_ebgp_session_oscillation_stage(
            device_name="dut.example.com",
            ipv4_peer_regex=".*IPV4_EBGP$",
            ipv6_peer_regex=".*IPV6_EBGP$",
            ipv4_session_count=140,
            ipv6_session_count=140,
            expected_established_sessions=1272,
            sessions_per_cycle=71,
            parent_prefixes_to_ignore=["2001:db8:ffff::/80"],
        )

        self.assertEqual(1, len(playbook.stages))
        self.assertEqual(1, len(playbook.stages[0].steps))
        self.assertEqual(
            legacy.steps[0].description, playbook.stages[0].steps[0].description
        )
        self.assertEqual(
            _step_payload(legacy.steps[0]),
            _step_payload(playbook.stages[0].steps[0]),
        )

    def test_ebgp_playbook_rejects_width_that_cannot_cover_both_families(
        self,
    ) -> None:
        with self.assertRaises(ValueError):
            get_bgp_ebb_ebgp_session_oscillation_playbook(
                device_name="dut.example.com",
                peergroup_ibgp_v6="IBGP_V6",
                peergroup_ibgp_v4="IBGP_V4",
                ipv4_session_count=140,
                ipv6_session_count=140,
                sessions_per_cycle=1,
            )

    def test_ibgp_playbook_matches_legacy_stage_for_odd_width(self) -> None:
        playbook = get_bgp_ebb_ibgp_plane_session_oscillation_playbook(
            device_name="dut.example.com",
            peergroup_ibgp_v6="IBGP_V6",
            peergroup_ibgp_v4="IBGP_V4",
            ipv4_sessions_per_plane=62,
            ipv6_sessions_per_plane=62,
            expected_established_sessions=1272,
            sessions_per_plane=15,
            tornado_planes=[1, 3],
            session_type="both",
            parent_prefixes_to_ignore=["2001:db8:ffff::/80"],
        )
        legacy = create_validated_plane_bgp_session_oscillation_stage(
            device_name="dut.example.com",
            ipv4_peer_regex=".*IPV4_IBGP.*",
            ipv6_peer_regex=".*IPV6_IBGP.*",
            ipv4_sessions_per_plane=62,
            ipv6_sessions_per_plane=62,
            expected_established_sessions=1272,
            sessions_per_cycle=15,
            tornado_planes=[1, 3],
            session_type="both",
            parent_prefixes_to_ignore=["2001:db8:ffff::/80"],
        )

        self.assertEqual(1, len(playbook.stages))
        self.assertEqual(1, len(playbook.stages[0].steps))
        self.assertEqual(
            legacy.steps[0].description, playbook.stages[0].steps[0].description
        )
        self.assertEqual(
            _step_payload(legacy.steps[0]),
            _step_payload(playbook.stages[0].steps[0]),
        )

    def test_ibgp_playbook_rejects_width_that_cannot_cover_both_families(
        self,
    ) -> None:
        with self.assertRaises(ValueError):
            get_bgp_ebb_ibgp_plane_session_oscillation_playbook(
                device_name="dut.example.com",
                peergroup_ibgp_v6="IBGP_V6",
                peergroup_ibgp_v4="IBGP_V4",
                ipv4_sessions_per_plane=62,
                ipv6_sessions_per_plane=62,
                sessions_per_plane=1,
            )
        with self.assertRaises(ValueError):
            create_validated_plane_bgp_session_oscillation_stage(
                device_name="dut.example.com",
                ipv4_peer_regex=".*IPV4_IBGP.*",
                ipv6_peer_regex=".*IPV6_IBGP.*",
                ipv4_sessions_per_plane=62,
                ipv6_sessions_per_plane=62,
                expected_established_sessions=0,
                sessions_per_cycle=1,
            )

    def test_ibgp_playbook_rejects_empty_plane_selection(self) -> None:
        with self.assertRaises(ValueError):
            get_bgp_ebb_ibgp_plane_session_oscillation_playbook(
                device_name="dut.example.com",
                peergroup_ibgp_v6="IBGP_V6",
                peergroup_ibgp_v4="IBGP_V4",
                ipv4_sessions_per_plane=62,
                ipv6_sessions_per_plane=62,
                tornado_planes=[],
            )
        with self.assertRaises(ValueError):
            create_validated_plane_bgp_session_oscillation_stage(
                device_name="dut.example.com",
                ipv4_peer_regex=".*IPV4_IBGP.*",
                ipv6_peer_regex=".*IPV6_IBGP.*",
                ipv4_sessions_per_plane=62,
                ipv6_sessions_per_plane=62,
                expected_established_sessions=0,
                tornado_planes=[],
            )

    def test_ibgp_playbook_rejects_width_above_available_sessions(self) -> None:
        with self.assertRaises(ValueError):
            get_bgp_ebb_ibgp_plane_session_oscillation_playbook(
                device_name="dut.example.com",
                peergroup_ibgp_v6="IBGP_V6",
                peergroup_ibgp_v4="IBGP_V4",
                ipv4_sessions_per_plane=4,
                ipv6_sessions_per_plane=4,
                sessions_per_plane=10,
            )
        with self.assertRaises(ValueError):
            create_validated_plane_bgp_session_oscillation_stage(
                device_name="dut.example.com",
                ipv4_peer_regex=".*IPV4_IBGP.*",
                ipv6_peer_regex=".*IPV6_IBGP.*",
                ipv4_sessions_per_plane=4,
                ipv6_sessions_per_plane=4,
                expected_established_sessions=0,
                sessions_per_cycle=10,
            )

    def test_ibgp_playbook_rejects_unsupported_session_type(self) -> None:
        with self.assertRaises(ValueError):
            get_bgp_ebb_ibgp_plane_session_oscillation_playbook(
                device_name="dut.example.com",
                peergroup_ibgp_v6="IBGP_V6",
                peergroup_ibgp_v4="IBGP_V4",
                ipv4_sessions_per_plane=62,
                ipv6_sessions_per_plane=62,
                session_type="unsupported",
            )
        with self.assertRaises(ValueError):
            create_validated_plane_bgp_session_oscillation_stage(
                device_name="dut.example.com",
                ipv4_peer_regex=".*IPV4_IBGP.*",
                ipv6_peer_regex=".*IPV6_IBGP.*",
                ipv4_sessions_per_plane=62,
                ipv6_sessions_per_plane=62,
                expected_established_sessions=0,
                session_type="unsupported",
            )
