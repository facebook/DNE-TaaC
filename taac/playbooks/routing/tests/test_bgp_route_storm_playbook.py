# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from taac.abstractions.churn.route import RouteStorm
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
_FROZEN_ROUTE_STORM_PARAMS = {
    "ixia_interface_mimic_ibgp": "Ethernet2",
    "observer_peer_parent_prefix": "2401:db00:e50d:22:a::/80",
    "prefix_pool_names": EXPECTED_POOLS,
    "selected_peer_rows": EXPECTED_ROWS,
    "expected_established_sessions": 1272,
    "peer_count_per_plane": 62,
    "routes_per_peer": 750,
    "samples_per_block": 2,
    "cycles": 60,
    "advertise_seconds": 30,
    "withdraw_seconds": 30,
    "poll_interval_seconds": 5,
    "convergence_hard_timeout_seconds": 300,
    "heavy_setup_hard_timeout_seconds": 1_800,
    "heavy_route_batch_rows": 15_750,
    "session_establish_timeout_seconds": 300,
    "restore_timeout_seconds": 300,
    "quiet_window_seconds": 120,
    "max_lookup_concurrency": 1,
    "as_path_pool_size": 10,
    "as_path_length": 255,
    "as_set_length": 255,
    "communities_per_route": 32,
    "extended_communities_per_route": 16,
}
_FROZEN_ROUTE_STORM_PAYLOAD = {
    "custom_step_name": "bgp_route_storm",
    "hostname": "dut.example.com",
    **_FROZEN_ROUTE_STORM_PARAMS,
}


def _locked_route_storm(**overrides: object) -> RouteStorm:
    params = {**_FROZEN_ROUTE_STORM_PARAMS, **overrides}
    return RouteStorm.from_step_params(params)


def _step_json_params(step: taac_types.Step) -> str:
    params = step.step_params
    if params is None or params.json_params is None:
        raise AssertionError("custom step is missing serialized parameters")
    return params.json_params


def _step_payload(step: taac_types.Step) -> dict:
    return json.loads(_step_json_params(step))


class BgpRouteStormPlaybookTest(unittest.TestCase):
    def test_typed_route_storm_round_trips_flat_contract(self) -> None:
        self.assertEqual(
            _FROZEN_ROUTE_STORM_PARAMS,
            _locked_route_storm().to_step_params(),
        )

    def test_step_factory_serializes_locked_contract(self) -> None:
        step = create_bgp_route_storm_step(
            hostname="dut.example.com",
            route_storm=_locked_route_storm(),
        )

        self.assertEqual(taac_types.StepName.CUSTOM_STEP, step.name)
        self.assertEqual(_FROZEN_ROUTE_STORM_PAYLOAD, _step_payload(step))
        self.assertEqual(
            json.dumps(_FROZEN_ROUTE_STORM_PAYLOAD),
            _step_json_params(step),
        )
        self.assertEqual("Run audited dual-stack BGP route storm", step.description)

    def test_typed_route_storm_rejects_heavy_attribute_shape_reduction(self) -> None:
        with self.assertRaisesRegex(ValueError, "16 extended communities"):
            _locked_route_storm(extended_communities_per_route=1)

    def test_typed_route_storm_requires_positive_hard_timeout(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be positive"):
            _locked_route_storm(convergence_hard_timeout_seconds=0)

    def test_bounded_validation_preserves_optional_payload_position(self) -> None:
        params = _locked_route_storm(bounded_validation=True).to_step_params()

        keys = list(params)
        self.assertEqual(
            keys.index("selected_peer_rows") + 1,
            keys.index("bounded_validation"),
        )
        self.assertTrue(params["bounded_validation"])

    def test_stage_contains_only_the_failure_safe_custom_step(self) -> None:
        stage = create_bgp_ebb_route_storm_stage(
            hostname="dut.example.com",
            route_storm=_locked_route_storm(),
        )

        self.assertEqual(1, len(stage.steps))
        self.assertEqual(
            "bgp_route_storm", _step_payload(stage.steps[0])["custom_step_name"]
        )

    def test_playbook_wires_exact_typed_route_storm_contract(self) -> None:
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
        step = playbook.stages[0].steps[0]
        self.assertEqual(_FROZEN_ROUTE_STORM_PAYLOAD, _step_payload(step))
        self.assertEqual(
            json.dumps(_FROZEN_ROUTE_STORM_PAYLOAD),
            _step_json_params(step),
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
