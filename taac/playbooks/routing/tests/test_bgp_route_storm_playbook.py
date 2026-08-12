# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from taac.constants import BgpPlusPlusProfile
from taac.playbooks.routing.bgp_ebb_playbooks import (
    get_bgp_ebb_route_storm_playbook,
)
from taac.stages.stage_definitions import (
    create_bgp_ebb_route_storm_stage,
)
from taac.steps.step_definitions import (
    create_bgp_route_storm_step,
)
from taac.test_as_a_config import types as taac_types


EXPECTED_POOLS = {
    "ipv4": "PREFIX_POOL_IBGP_IPV4_PLANE_1_REMOTE_EB",
    "ipv6": "PREFIX_POOL_IBGP_IPV6_PLANE_1_REMOTE_EB",
}
EXPECTED_ROWS = [0, 10, 20, 30, 40, 50, 61]


def _locked_step_kwargs() -> dict:
    return {
        "hostname": "dut.example.com",
        "ixia_interface_mimic_ibgp": "Ethernet2",
        "expected_established_sessions": 1272,
        "observer_peer_parent_prefix": "2401:db00:e50d:22:a::/80",
        "prefix_pool_names": EXPECTED_POOLS,
        "peer_count_per_plane": 62,
        "selected_peer_rows": EXPECTED_ROWS,
        "routes_per_peer": 750,
        "samples_per_block": 2,
        "cycles": 60,
        "advertise_seconds": 30,
        "withdraw_seconds": 30,
        "poll_interval_seconds": 5,
        "transition_timeout_seconds": 30,
        "convergence_hard_timeout_seconds": 300,
        "session_establish_timeout_seconds": 300,
        "restore_timeout_seconds": 300,
        "quiet_window_seconds": 120,
        "max_lookup_concurrency": 8,
        "as_path_pool_size": 10,
        "as_path_length": 255,
        "as_set_length": 255,
        "communities_per_route": 32,
        "extended_communities_per_route": 16,
    }


def _step_payload(step: taac_types.Step) -> dict:
    params = step.step_params
    if params is None or params.json_params is None:
        raise AssertionError("custom step is missing serialized parameters")
    return json.loads(params.json_params)


class BgpRouteStormPlaybookTest(unittest.TestCase):
    def test_step_factory_serializes_locked_contract(self) -> None:
        step = create_bgp_route_storm_step(**_locked_step_kwargs())

        self.assertEqual(taac_types.StepName.CUSTOM_STEP, step.name)
        payload = _step_payload(step)
        self.assertEqual("bgp_route_storm", payload["custom_step_name"])
        self.assertEqual(EXPECTED_POOLS, payload["prefix_pool_names"])
        self.assertEqual(EXPECTED_ROWS, payload["selected_peer_rows"])
        self.assertEqual(60, payload["cycles"])
        self.assertEqual(255, payload["as_path_length"])
        self.assertEqual(255, payload["as_set_length"])
        self.assertEqual(32, payload["communities_per_route"])
        self.assertEqual(16, payload["extended_communities_per_route"])
        self.assertEqual(300, payload["convergence_hard_timeout_seconds"])

    def test_step_factory_rejects_heavy_attribute_shape_reduction(self) -> None:
        kwargs = _locked_step_kwargs()
        kwargs["extended_communities_per_route"] = 1

        with self.assertRaisesRegex(ValueError, "16 extended communities"):
            create_bgp_route_storm_step(**kwargs)

    def test_step_factory_requires_hard_timeout_above_transition_timeout(
        self,
    ) -> None:
        kwargs = _locked_step_kwargs()
        kwargs["convergence_hard_timeout_seconds"] = 30

        with self.assertRaisesRegex(ValueError, "must exceed"):
            create_bgp_route_storm_step(**kwargs)

    def test_stage_contains_only_the_failure_safe_custom_step(self) -> None:
        stage = create_bgp_ebb_route_storm_stage(**_locked_step_kwargs())

        self.assertEqual(1, len(stage.steps))
        self.assertEqual(
            "bgp_route_storm", _step_payload(stage.steps[0])["custom_step_name"]
        )

    def test_playbook_wires_exact_geometry_and_supported_shape(self) -> None:
        playbook = get_bgp_ebb_route_storm_playbook(
            device_name="dut.example.com",
            peergroup_ibgp_v6="IBGP_V6",
            peergroup_ibgp_v4="IBGP_V4",
            total_session_count=1272,
            ixia_interface_mimic_ibgp="Ethernet2",
            observer_peer_parent_prefix="2401:db00:e50d:22:a::/80",
            profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
        )

        self.assertEqual(1, len(playbook.stages))
        self.assertEqual(1, len(playbook.stages[0].steps))
        payload = _step_payload(playbook.stages[0].steps[0])
        self.assertEqual(EXPECTED_POOLS, payload["prefix_pool_names"])
        self.assertEqual(EXPECTED_ROWS, payload["selected_peer_rows"])
        self.assertEqual(10_500, len(EXPECTED_ROWS) * payload["routes_per_peer"] * 2)
        self.assertEqual(
            {
                "cycles": 60,
                "advertise_seconds": 30,
                "withdraw_seconds": 30,
                "convergence_hard_timeout_seconds": 300,
                "as_path_pool_size": 10,
                "as_path_length": 255,
                "as_set_length": 255,
                "communities_per_route": 32,
                "extended_communities_per_route": 16,
            },
            {
                key: payload[key]
                for key in (
                    "cycles",
                    "advertise_seconds",
                    "withdraw_seconds",
                    "convergence_hard_timeout_seconds",
                    "as_path_pool_size",
                    "as_path_length",
                    "as_set_length",
                    "communities_per_route",
                    "extended_communities_per_route",
                )
            },
        )

    def test_openr_profile_enables_ibgp_pnh_check(self) -> None:
        target = (
            "neteng.test_infra.dne.taac.playbooks.routing."
            "bgp_ebb_playbooks.get_profile_checks"
        )
        with patch(target) as get_checks:
            get_checks.return_value = SimpleNamespace(
                prechecks=[],
                postchecks=[],
                snapshot_checks=[],
            )
            get_bgp_ebb_route_storm_playbook(
                device_name="dut.example.com",
                peergroup_ibgp_v6="IBGP_V6",
                peergroup_ibgp_v4="IBGP_V4",
                total_session_count=1272,
                ixia_interface_mimic_ibgp="Ethernet2",
                observer_peer_parent_prefix="2401:db00:e50d:22:a::/80",
                profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
            )

        self.assertTrue(get_checks.call_args.args[1].check_ibgp_pnh)
        self.assertFalse(get_checks.call_args.args[1].check_cpu_load_average)
