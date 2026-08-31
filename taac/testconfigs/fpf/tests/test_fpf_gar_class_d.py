# Copyright (c) Meta Platforms, Inc. and affiliates.

import json
import unittest

from taac.testconfigs.fpf.fpf_gar_class_d import (
    GAR_PREFIX_COUNT,
    PLANE1_SOURCE,
    PLANE1_SPINE,
    PLANE2_SPINE,
    TEST_CONFIG,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config.types import StepName


def _steps(playbook):
    return [step for stage in playbook.stages for step in (stage.steps or [])]


def _params(value) -> dict:
    assert value.step_params is not None
    assert value.step_params.json_params is not None
    return json.loads(value.step_params.json_params)


def _check_params(playbook, check_name) -> list[dict]:
    params = []
    for check in playbook.postchecks or []:
        if check.name != check_name:
            continue
        assert check.check_params is not None
        assert check.check_params.json_params is not None
        params.append(json.loads(check.check_params.json_params))
    return params


class TestFpfGarClassDConfig(unittest.TestCase):
    def test_all_disruption_and_recovery_playbooks_exist(self) -> None:
        self.assertEqual(
            [playbook.name for playbook in TEST_CONFIG.playbooks],
            [
                "fpf_gar_d1_gtsw_plane1_drain",
                "fpf_gar_d1_gtsw_plane1_drain_recovery",
                "fpf_gar_d2_stsw_plane1_drain",
                "fpf_gar_d2_stsw_plane1_drain_recovery",
                "fpf_gar_d3_gtsw_stsw_plane1_drain",
                "fpf_gar_d3_gtsw_stsw_plane1_drain_recovery",
                "fpf_gar_d4_gtsw_plane1_stsw_plane2_drain",
                "fpf_gar_d4_gtsw_plane1_stsw_plane2_drain_recovery",
            ],
        )

    def test_scale_is_injected_as_load_but_not_asserted_for_device_drain(
        self,
    ) -> None:
        setup_tasks = TEST_CONFIG.setup_tasks or []
        self.assertGreaterEqual(len(setup_tasks), 2)
        assert setup_tasks[1].params is not None
        assert setup_tasks[1].params.json_params is not None
        setup = json.loads(setup_tasks[1].params.json_params)
        self.assertEqual(setup["groups"][0]["count"], GAR_PREFIX_COUNT)
        self.assertEqual(
            len(setup["groups"][0]["devices"]),
            3,
        )
        for playbook in TEST_CONFIG.playbooks:
            checks = {check.name for check in (playbook.postchecks or [])}
            self.assertIn(hc_types.CheckName.FPF_GAR_VF_CAPACITY_CHECK, checks)
            self.assertNotIn(
                hc_types.CheckName.FPF_GAR_SCALE_CAPACITY_CHECK,
                checks,
            )

    def test_recovery_is_not_blocked_by_the_disruption_vf_result(self) -> None:
        for playbook in TEST_CONFIG.playbooks:
            precheck_names = {check.name for check in (playbook.prechecks or [])}
            postcheck_names = {check.name for check in (playbook.postchecks or [])}
            if playbook.name.endswith("_recovery"):
                self.assertNotIn(
                    hc_types.CheckName.FPF_GAR_VF_CAPACITY_CHECK,
                    precheck_names,
                )
            else:
                self.assertIn(
                    hc_types.CheckName.FPF_GAR_VF_CAPACITY_CHECK,
                    precheck_names,
                )
            self.assertIn(
                hc_types.CheckName.FPF_GAR_VF_CAPACITY_CHECK,
                postcheck_names,
            )

    def test_systemctl_check_retries_during_drain_recovery(self) -> None:
        for playbook in TEST_CONFIG.playbooks:
            for checks in (playbook.prechecks, playbook.postchecks):
                systemctl_check = next(
                    check
                    for check in (checks or [])
                    if check.name == hc_types.CheckName.SYSTEMCTL_ACTIVE_STATE_CHECK
                )
                assert systemctl_check.check_params is not None
                assert systemctl_check.check_params.json_params is not None
                params = json.loads(systemctl_check.check_params.json_params)
                self.assertEqual(params["retry_count"], 12)
                self.assertEqual(params["retry_delay_seconds"], 10)
                self.assertEqual(params["retry_delay_multiplier"], 1)

    def test_source_device_drain_reinjects_after_drain_and_undrain(self) -> None:
        disrupt = TEST_CONFIG.playbooks[0]
        recovery = TEST_CONFIG.playbooks[1]
        self.assertEqual(
            [step.name for step in _steps(disrupt)],
            [StepName.CUSTOM_STEP, StepName.FPF_BGP_PREFIX_INJECTION_STEP],
        )
        self.assertIn("65446:10", _params(_steps(disrupt)[1])["communities"])
        self.assertEqual(
            _params(_steps(recovery)[1])["community_list"],
            "gtsw",
        )

    def test_stsw_only_drain_does_not_reinject_on_a_non_originator(self) -> None:
        disrupt = next(
            playbook
            for playbook in TEST_CONFIG.playbooks
            if playbook.name == "fpf_gar_d2_stsw_plane1_drain"
        )
        self.assertEqual(
            [step.name for step in _steps(disrupt)], [StepName.CUSTOM_STEP]
        )

    def test_d2_keeps_vf_and_marks_remote_path_drained(self) -> None:
        playbook = next(
            playbook
            for playbook in TEST_CONFIG.playbooks
            if playbook.name == "fpf_gar_d2_stsw_plane1_drain"
        )
        params = _check_params(playbook, hc_types.CheckName.FPF_GAR_VF_CAPACITY_CHECK)[
            0
        ]
        plane1 = params["pairs"][0]
        self.assertEqual(plane1["expected_capacity"], 36)
        self.assertEqual(plane1["expected_spine_capacity"], 36)
        self.assertEqual(plane1["observer_required_communities"], ["65446:10"])
        self.assertEqual(plane1["spine_forbidden_communities"], ["65446:10"])
        self.assertIn("rack_id", plane1["observer_required_bgp_topology_fields"])

    def test_d4_drains_plane1_source_and_plane2_spine_together(self) -> None:
        playbook = next(
            playbook
            for playbook in TEST_CONFIG.playbooks
            if playbook.name == "fpf_gar_d4_gtsw_plane1_stsw_plane2_drain"
        )
        trigger = _params(_steps(playbook)[0])
        self.assertEqual(trigger["devices"], [PLANE1_SOURCE, PLANE2_SPINE])
        self.assertTrue(trigger["is_drain"])

        params = _check_params(playbook, hc_types.CheckName.FPF_GAR_VF_CAPACITY_CHECK)[
            0
        ]
        plane1, plane2, plane4 = params["pairs"]
        self.assertEqual(plane1["expected_capacity"], 36)
        self.assertEqual(plane1["expected_spine_capacity"], 36)
        self.assertEqual(plane2["expected_capacity"], 36)
        self.assertEqual(plane2["expected_spine_capacity"], 36)
        self.assertEqual(plane4["expected_capacity"], 36)
        self.assertEqual(plane1["spine_required_communities"], ["65446:10"])
        self.assertEqual(plane1["observer_required_communities"], ["65446:10"])
        self.assertEqual(plane2["spine_forbidden_communities"], ["65446:10"])
        self.assertEqual(plane2["observer_required_communities"], ["65446:10"])
        self.assertEqual(plane4["observer_forbidden_communities"], ["65446:10"])

    def test_drain_state_checks_are_independently_scoped(self) -> None:
        playbook = next(
            playbook
            for playbook in TEST_CONFIG.playbooks
            if playbook.name == "fpf_gar_d3_gtsw_stsw_plane1_drain"
        )
        drain_params = _check_params(
            playbook,
            hc_types.CheckName.DRAIN_STATE_CHECK,
        )
        expected = {
            params["device_name"]: params["expected_drained"] for params in drain_params
        }
        self.assertTrue(expected[PLANE1_SOURCE])
        self.assertTrue(expected[PLANE1_SPINE])
        self.assertFalse(expected[PLANE2_SPINE])
        self.assertFalse(playbook.override_duplicate_checks)


if __name__ == "__main__":
    unittest.main()
