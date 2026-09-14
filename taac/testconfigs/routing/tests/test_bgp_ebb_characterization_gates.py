# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

import json
import unittest

from taac.abstractions.physical_inventory import BAG011_ASH6
from taac.testconfigs.routing.factories.bgp_ebb_full_scale import (
    create_bgp_ebb_full_scale_test_config,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config.types import Playbook, PointInTimeHealthCheck, TestConfig


_PLAYBOOK_NAMES = (
    "bgp_ebb_daemon_restart_playbook",
    "bgp_ebb_cold_start_playbook",
    "bgp_ebb_ebgp_session_oscillation_playbook",
    "bgp_ebb_ibgp_plane_session_oscillation_playbook",
    "bgp_ebb_ebgp_route_oscillation_playbook",
    "bgp_ebb_ibgp_route_oscillation_playbook",
    "bgp_ebb_igp_pnh_metric_oscillation_playbook",
    "bgp_ebb_igp_unresolvable_pnh_playbook",
    "bgp_ebb_multipath_group_oscillation_playbook",
    "bgp_ebb_attribute_churn_playbook",
    "bgp_ebb_route_storm_playbook",
    "bgp_ebb_route_registry_runtime_update_playbook",
    "bgp_ebb_fauu_drain_undrain_playbook",
    "bgp_ebb_plane_drain_undrain_playbook",
    "bgp_ebb_longevity_playbook",
    "bgp_ebb_nexthop_group_count_threshold_playbook",
)

_UG_GATES = {
    "bgp_ebb_attribute_churn_playbook": ({"80": 5.0, "95": 60.0}, 10.0),
    "bgp_ebb_route_storm_playbook": ({"80": 35.0, "95": 100.0}, 10.0),
    "bgp_ebb_multipath_group_oscillation_playbook": (
        {"80": 6.0, "95": 70.0},
        10.0,
    ),
    "bgp_ebb_igp_pnh_metric_oscillation_playbook": (
        {"80": 30.0, "95": 100.0},
        10.0,
    ),
    "bgp_ebb_longevity_playbook": ({"80": 150.0, "95": 180.0}, 35.0),
    "bgp_ebb_ebgp_route_oscillation_playbook": (
        {"80": 60.0, "95": 160.0},
        10.0,
    ),
    "bgp_ebb_ibgp_route_oscillation_playbook": (
        {"80": 90.0, "95": 160.0},
        10.0,
    ),
    "bgp_ebb_igp_unresolvable_pnh_playbook": (
        {"80": 4.0, "95": 5.0},
        10.0,
    ),
}

_NON_UG_GATES = {
    "bgp_ebb_attribute_churn_playbook": ({"80": 140.0, "95": 150.0}, 10.0),
    "bgp_ebb_ebgp_route_oscillation_playbook": (
        {"80": 140.0, "95": 190.0},
        10.0,
    ),
    "bgp_ebb_igp_unresolvable_pnh_playbook": (
        {"80": 7.0, "95": 140.0},
        10.0,
    ),
}


def _check(
    playbook: Playbook, check_name: hc_types.CheckName
) -> PointInTimeHealthCheck | None:
    matches = [check for check in playbook.postchecks or [] if check.name == check_name]
    if not matches:
        return None
    if len(matches) != 1:
        raise AssertionError(
            f"{playbook.name} has {len(matches)} {check_name.name} checks"
        )
    return matches[0]


def _params(check: PointInTimeHealthCheck) -> dict[str, object]:
    if check.check_params is None:
        raise AssertionError(f"{check.name.name} has no check parameters")
    return json.loads(check.check_params.json_params or "{}")


class BgpEbbCharacterizationGatesTest(unittest.TestCase):
    def _config(self, enable_update_group: bool) -> TestConfig:
        return create_bgp_ebb_full_scale_test_config(
            BAG011_ASH6,
            name=(
                "BAG011_CHARACTERIZATION_UG_TEST"
                if enable_update_group
                else "BAG011_CHARACTERIZATION_NON_UG_TEST"
            ),
            playbooks_selected=list(_PLAYBOOK_NAMES),
            enable_update_group=enable_update_group,
        )

    def _assert_gates(
        self,
        enable_update_group: bool,
        expected_gates: dict[str, tuple[dict[str, float], float]],
    ) -> None:
        playbooks = {
            playbook.name: playbook
            for playbook in self._config(enable_update_group).playbooks
        }
        self.assertEqual(set(_PLAYBOOK_NAMES), set(playbooks))

        for playbook_name, playbook in playbooks.items():
            with self.subTest(playbook=playbook_name):
                cpu_check = _check(playbook, hc_types.CheckName.CPU_PERCENTILE_CHECK)
                rss_check = _check(playbook, hc_types.CheckName.RSS_DELTA_CHECK)
                if playbook_name == "bgp_ebb_daemon_restart_playbook":
                    self.assertIsNone(cpu_check)
                    self.assertIsNone(rss_check)
                    continue

                self.assertIsNotNone(cpu_check)
                self.assertIsNotNone(rss_check)
                if playbook_name != "bgp_ebb_cold_start_playbook":
                    stage_ids = {stage.id for stage in playbook.stages or []}
                    phase = (
                        "soak"
                        if playbook_name == "bgp_ebb_longevity_playbook"
                        else "workload"
                    )
                    self.assertIn(f"{phase}_characterization_start", stage_ids)
                    self.assertIn(f"{phase}_characterization_stop", stage_ids)
                cpu_params = _params(cpu_check)
                rss_params = _params(rss_check)
                expected = expected_gates.get(playbook_name)
                if expected is None:
                    self.assertNotIn("gate_thresholds_pct", cpu_params)
                    self.assertNotIn("gate_threshold_pct", cpu_params)
                    self.assertNotIn("max_growth_pct", rss_params)
                    continue

                expected_cpu, expected_rss = expected
                self.assertEqual(expected_cpu, cpu_params["gate_thresholds_pct"])
                self.assertEqual(expected_rss, rss_params["max_growth_pct"])

    def test_update_group_uses_all_calibrated_gates(self) -> None:
        self._assert_gates(True, _UG_GATES)

    def test_non_update_group_gates_only_measured_playbooks(self) -> None:
        self._assert_gates(False, _NON_UG_GATES)
