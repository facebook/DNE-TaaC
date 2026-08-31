# Copyright (c) Meta Platforms, Inc. and affiliates.

import json
import typing as t
import unittest

from taac.testconfigs.fpf.fpf_gar_class_a import (
    GAR_PREFIX_COUNT,
    INJECTION_GROUPS,
    L1002_PLANE3_CAPACITY,
    PRODUCTION_VF_PREFIX,
    TEST_CONFIG,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config.types import StepName


def _gar_checks(playbook):
    validation_step = playbook.stages[0].steps[0]
    assert validation_step.name == StepName.VALIDATION_STEP
    validation_input = json.loads(validation_step.input_json)
    return validation_input["point_in_time_checks"]


def _health_check_params(check) -> dict:
    assert check.check_params is not None
    assert check.check_params.json_params is not None
    return json.loads(check.check_params.json_params)


class TestFpfGarClassAConfig(unittest.TestCase):
    def test_all_class_a_playbooks_are_present(self) -> None:
        self.assertEqual(
            [playbook.name for playbook in TEST_CONFIG.playbooks],
            [
                "fpf_gar_a1_topology_info_all_planes",
                "fpf_gar_a2_stsw_capacity_add_path",
                "fpf_gar_a3_remote_rib_fib_capacity",
                "fpf_gar_a4_multi_pod_origination",
            ],
        )

    def test_all_24_switches_are_endpoints_and_only_controller_is_dut(self) -> None:
        self.assertEqual(len(TEST_CONFIG.endpoints), 24)
        self.assertEqual(
            [endpoint.name for endpoint in TEST_CONFIG.endpoints if endpoint.dut],
            ["gtsw001.l1002.c087.mwg2"],
        )
        self.assertEqual(len({endpoint.name for endpoint in TEST_CONFIG.endpoints}), 24)

    def test_setup_injects_four_direction_and_vf_groups(self) -> None:
        self.assertEqual(len(INJECTION_GROUPS), 4)
        self.assertEqual(
            [group["prefix_base"] for group in INJECTION_GROUPS],
            [
                "5000:ca::/64",
                "5000:cb::/64",
                "5000:cc::/64",
                "5000:cd::/64",
            ],
        )
        for group in INJECTION_GROUPS:
            self.assertEqual(len(t.cast(list[str], group["devices"])), 4)
            self.assertEqual(group["count"], GAR_PREFIX_COUNT)
            self.assertEqual(group["batch_size"], 100)
            self.assertEqual(group["community_list"], "gtsw")

    def test_a1_a2_a3_cover_all_eight_forward_planes(self) -> None:
        expected_scopes = ["topology_info", "bgp", "remote_rib_fib"]
        for playbook, expected_scope in zip(TEST_CONFIG.playbooks[:3], expected_scopes):
            checks = [
                check
                for check in _gar_checks(playbook)
                if check["name"] == hc_types.CheckName.FPF_GAR_SCALE_CAPACITY_CHECK
            ]
            self.assertEqual(len(checks), 2)
            pairs = [
                pair
                for check in checks
                for pair in json.loads(check["check_params"]["json_params"])["pairs"]
            ]
            self.assertEqual(len(pairs), 8)
            self.assertEqual(
                {pair["validation_scope"] for pair in pairs}, {expected_scope}
            )
            self.assertEqual(
                {pair["source"] for pair in pairs},
                {f"gtsw{plane:03d}.l1002.c087.mwg2" for plane in range(1, 9)},
            )

    def test_a4_covers_both_pods_all_planes(self) -> None:
        checks = [
            check
            for check in _gar_checks(TEST_CONFIG.playbooks[3])
            if check["name"] == hc_types.CheckName.FPF_GAR_SCALE_CAPACITY_CHECK
        ]
        self.assertEqual(len(checks), 4)
        pairs = [
            pair
            for check in checks
            for pair in json.loads(check["check_params"]["json_params"])["pairs"]
        ]
        self.assertEqual(len(pairs), 16)
        self.assertEqual({pair["validation_scope"] for pair in pairs}, {"full"})
        directions = {
            (pair["source"].split(".")[1], pair["observer"].split(".")[1])
            for pair in pairs
        }
        self.assertEqual(directions, {("l1002", "l1001"), ("l1001", "l1002")})

    def test_plane_three_asymmetry_is_encoded(self) -> None:
        checks = [
            check
            for check in _gar_checks(TEST_CONFIG.playbooks[3])
            if check["name"] == hc_types.CheckName.FPF_GAR_SCALE_CAPACITY_CHECK
        ]
        pairs = [
            pair
            for check in checks
            for pair in json.loads(check["check_params"]["json_params"])["pairs"]
            if pair["name"].startswith("plane-3-")
        ]
        forward = next(pair for pair in pairs if "l1002-to-l1001" in pair["name"])
        reverse = next(pair for pair in pairs if "l1001-to-l1002" in pair["name"])
        self.assertEqual(forward["expected_capacity"], L1002_PLANE3_CAPACITY)
        self.assertEqual(forward["observer_path_count"], 36)
        self.assertEqual(forward["observer_forwarding_count"], L1002_PLANE3_CAPACITY)
        self.assertEqual(reverse["expected_capacity"], 36)
        self.assertEqual(reverse["observer_path_count"], L1002_PLANE3_CAPACITY)
        self.assertEqual(reverse["observer_forwarding_count"], L1002_PLANE3_CAPACITY)

    def test_every_playbook_validates_production_vf_and_full_scale(self) -> None:
        for playbook in TEST_CONFIG.playbooks:
            checks = _gar_checks(playbook)
            names = [check["name"] for check in checks]
            self.assertEqual(
                names.count(hc_types.CheckName.FPF_GAR_VF_CAPACITY_CHECK),
                1,
            )
            self.assertGreaterEqual(
                names.count(hc_types.CheckName.FPF_GAR_SCALE_CAPACITY_CHECK),
                2,
            )
            vf_check = next(
                check
                for check in checks
                if check["name"] == hc_types.CheckName.FPF_GAR_VF_CAPACITY_CHECK
            )
            params = json.loads(vf_check["check_params"]["json_params"])
            self.assertEqual(params["prefixes"], [PRODUCTION_VF_PREFIX])
            self.assertEqual(len(params["pairs"]), 4)
            self.assertEqual(
                {pair["source_route_mode"] for pair in params["pairs"]}, {"vf"}
            )

    def test_ssh_dependent_health_checks_are_not_disabled(self) -> None:
        required = {
            hc_types.CheckName.SYSTEMCTL_ACTIVE_STATE_CHECK,
            hc_types.CheckName.UNCLEAN_EXIT_CHECK,
            hc_types.CheckName.DEVICE_CORE_DUMPS_CHECK,
        }
        for playbook in TEST_CONFIG.playbooks:
            self.assertTrue(
                required.issubset({check.name for check in (playbook.prechecks or [])})
            )
            self.assertTrue(
                required.issubset({check.name for check in (playbook.postchecks or [])})
            )

    def test_all_switches_must_be_undrained_before_validation(self) -> None:
        expected_devices = {endpoint.name for endpoint in TEST_CONFIG.endpoints}
        for playbook in TEST_CONFIG.playbooks:
            self.assertFalse(playbook.override_duplicate_checks)
            drain_checks = [
                check
                for check in (playbook.prechecks or [])
                if check.name == hc_types.CheckName.DRAIN_STATE_CHECK
            ]
            self.assertEqual(len(drain_checks), 24)
            params = [_health_check_params(check) for check in drain_checks]
            self.assertEqual({item["device_name"] for item in params}, expected_devices)
            self.assertEqual({item["expected_drained"] for item in params}, {False})


if __name__ == "__main__":
    unittest.main()
