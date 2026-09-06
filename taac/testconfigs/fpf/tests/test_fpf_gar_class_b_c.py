# Copyright (c) Meta Platforms, Inc. and affiliates.

import json
import unittest

from taac.testconfigs.fpf.fpf_gar_class_b_c import (
    GAR_PREFIX_COUNT,
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


def _health_check_params(check) -> dict:
    assert check.check_params is not None
    assert check.check_params.json_params is not None
    return json.loads(check.check_params.json_params)


class TestFpfGarClassBCConfig(unittest.TestCase):
    def test_playbooks_run_once_from_pair_a_source(self) -> None:
        duts = [endpoint.name for endpoint in TEST_CONFIG.endpoints if endpoint.dut]
        self.assertEqual(duts, ["gtsw001.l1002.c087.mwg2"])

    def test_scale_is_injected_and_withdrawn_by_tasks(self) -> None:
        setup_tasks = TEST_CONFIG.setup_tasks or []
        teardown_tasks = TEST_CONFIG.teardown_tasks or []
        self.assertGreaterEqual(len(setup_tasks), 2)
        self.assertGreaterEqual(len(teardown_tasks), 1)
        self.assertEqual(setup_tasks[0].task_name, "fpf_inject_bgp_prefixes")
        self.assertEqual(setup_tasks[1].task_name, "fpf_inject_bgp_prefixes")
        assert setup_tasks[0].params is not None
        assert setup_tasks[0].params.json_params is not None
        assert setup_tasks[1].params is not None
        assert setup_tasks[1].params.json_params is not None
        assert teardown_tasks[0].params is not None
        assert teardown_tasks[0].params.json_params is not None
        cleanup = json.loads(setup_tasks[0].params.json_params)
        injection = json.loads(setup_tasks[1].params.json_params)
        teardown = json.loads(teardown_tasks[0].params.json_params)
        self.assertTrue(cleanup["withdraw"])
        self.assertFalse(injection["withdraw"])
        self.assertTrue(teardown["withdraw"])
        self.assertEqual(len(injection["groups"]), 2)
        self.assertEqual(
            {group["prefix_base"] for group in injection["groups"]},
            {"5000:ca::/64", "5000:cc::/64"},
        )
        for group in injection["groups"]:
            self.assertEqual(group["count"], GAR_PREFIX_COUNT)
            self.assertEqual(group["batch_size"], 100)
            self.assertEqual(len(group["devices"]), 1)
            self.assertEqual(group["community_list"], "gtsw")

    def test_disruption_and_recovery_are_separate_playbooks(self) -> None:
        names = [playbook.name for playbook in TEST_CONFIG.playbooks]
        self.assertEqual(len(names), 34)
        self.assertIn("fpf_gar_b1_admin_down_1", names)
        self.assertIn("fpf_gar_b1_admin_up_1", names)
        self.assertIn("fpf_gar_b7b_admin_down_36", names)
        self.assertIn("fpf_gar_b7b_admin_up_36", names)
        self.assertIn("fpf_gar_bprime6_softdrain_18", names)
        self.assertIn("fpf_gar_bprime6_undrain_18", names)
        self.assertIn("fpf_gar_c1_multi_pair_3_6", names)
        self.assertIn("fpf_gar_c1_multi_pair_3_6_recovery", names)
        self.assertIn("fpf_gar_c2_multi_pair_2_6", names)
        self.assertIn("fpf_gar_c3_multi_pair_4_6", names)

    def test_every_class_b_and_bprime_case_is_automated(self) -> None:
        names = {playbook.name for playbook in TEST_CONFIG.playbooks}
        expected = set()
        for index, count in enumerate((1, 2, 3, 4, 6, 18), start=1):
            expected.update(
                {
                    f"fpf_gar_b{index}_admin_down_{count}",
                    f"fpf_gar_b{index}_admin_up_{count}",
                    f"fpf_gar_bprime{index}_softdrain_{count}",
                    f"fpf_gar_bprime{index}_undrain_{count}",
                }
            )
        expected.update(
            {
                "fpf_gar_b7a_admin_down_35",
                "fpf_gar_b7a_admin_up_35",
                "fpf_gar_b7b_admin_down_36",
                "fpf_gar_b7b_admin_up_36",
            }
        )
        self.assertTrue(expected.issubset(names))

    def test_disruption_playbook_only_disables(self) -> None:
        playbook = next(
            item
            for item in TEST_CONFIG.playbooks
            if item.name == "fpf_gar_b1_admin_down_1"
        )
        steps = _steps(playbook)
        self.assertEqual([step.name for step in steps], [StepName.CUSTOM_STEP])
        self.assertEqual(_params(steps[0])["custom_step_name"], "fpf_gar_set_links")
        self.assertTrue(_params(steps[0])["disrupt"])
        self.assertFalse(playbook.cleanup_steps)

    def test_recovery_playbook_only_enables_and_has_safety_cleanup(self) -> None:
        playbook = next(
            item
            for item in TEST_CONFIG.playbooks
            if item.name == "fpf_gar_b1_admin_up_1"
        )
        steps = _steps(playbook)
        self.assertEqual([step.name for step in steps], [StepName.CUSTOM_STEP])
        self.assertFalse(_params(steps[0])["disrupt"])
        cleanup = list(playbook.cleanup_steps or [])
        self.assertEqual(len(cleanup), 1)
        self.assertFalse(_params(cleanup[0])["disrupt"])

    def test_b7b_asserts_scaled_prefix_pruning(self) -> None:
        playbook = next(
            item
            for item in TEST_CONFIG.playbooks
            if item.name == "fpf_gar_b7b_admin_down_36"
        )
        scale_check = next(
            check
            for check in (playbook.postchecks or [])
            if check.name == hc_types.CheckName.FPF_GAR_SCALE_CAPACITY_CHECK
        )
        params = _health_check_params(scale_check)
        self.assertEqual(params["pairs"][0]["expected_capacity"], 0)
        self.assertEqual(params["prefix_count"], GAR_PREFIX_COUNT)

    def test_b_playbook_monitors_only_the_affected_pair(self) -> None:
        playbook = next(
            item
            for item in TEST_CONFIG.playbooks
            if item.name == "fpf_gar_b1_admin_down_1"
        )
        for check_name in (
            hc_types.CheckName.FPF_GAR_VF_CAPACITY_CHECK,
            hc_types.CheckName.FPF_GAR_SCALE_CAPACITY_CHECK,
        ):
            check = next(
                item for item in (playbook.postchecks or []) if item.name == check_name
            )
            params = _health_check_params(check)
            self.assertEqual(len(params["pairs"]), 1)
            self.assertEqual(params["pairs"][0]["expected_capacity"], 35)

    def test_c_playbook_monitors_both_affected_pairs(self) -> None:
        playbook = next(
            item
            for item in TEST_CONFIG.playbooks
            if item.name == "fpf_gar_c1_multi_pair_3_6"
        )
        scale_checks = [
            check
            for check in (playbook.postchecks or [])
            if check.name == hc_types.CheckName.FPF_GAR_SCALE_CAPACITY_CHECK
        ]
        self.assertEqual(len(scale_checks), 2)
        pairs = [_health_check_params(check)["pairs"][0] for check in scale_checks]
        self.assertEqual([pair["expected_capacity"] for pair in pairs], [33, 30])
        self.assertEqual([pair["observer_path_count"] for pair in pairs], [30, 33])
        self.assertEqual(
            [pair["observer_forwarding_count"] for pair in pairs], [30, 30]
        )
        self.assertEqual(
            [(pair["source"], pair["observer"]) for pair in pairs],
            [
                (
                    "gtsw001.l1001.c087.mwg2",
                    "gtsw001.l1002.c087.mwg2",
                ),
                (
                    "gtsw001.l1002.c087.mwg2",
                    "gtsw001.l1001.c087.mwg2",
                ),
            ],
        )

        trigger = _params(_steps(playbook)[0])
        self.assertEqual(
            [
                (target["device"], len(target["interfaces"]))
                for target in trigger["targets"]
            ],
            [
                ("gtsw001.l1001.c087.mwg2", 3),
                ("gtsw001.l1002.c087.mwg2", 6),
            ],
        )

    def test_required_network_and_gar_health_checks_are_present(self) -> None:
        required = {
            hc_types.CheckName.SYSTEMCTL_ACTIVE_STATE_CHECK,
            hc_types.CheckName.WEDGE_AGENT_CONFIGURED_CHECK,
            hc_types.CheckName.UNCLEAN_EXIT_CHECK,
            hc_types.CheckName.DEVICE_CORE_DUMPS_CHECK,
            hc_types.CheckName.FPF_GAR_VF_CAPACITY_CHECK,
        }
        for playbook in TEST_CONFIG.playbooks:
            self.assertTrue(
                required.issubset({check.name for check in (playbook.prechecks or [])})
            )
            self.assertTrue(
                required.issubset({check.name for check in (playbook.postchecks or [])})
            )
            names = {check.name for check in (playbook.prechecks or [])}
            if "bprime" in playbook.name:
                self.assertNotIn(hc_types.CheckName.FPF_GAR_SCALE_CAPACITY_CHECK, names)
            else:
                self.assertIn(hc_types.CheckName.FPF_GAR_SCALE_CAPACITY_CHECK, names)

        disruption = next(
            item
            for item in TEST_CONFIG.playbooks
            if item.name == "fpf_gar_b1_admin_down_1"
        )
        self.assertFalse(disruption.override_duplicate_checks)
        self.assertIn(
            hc_types.CheckName.BGP_SESSION_ESTABLISH_CHECK,
            {check.name for check in (disruption.prechecks or [])},
        )
        self.assertNotIn(
            hc_types.CheckName.BGP_SESSION_ESTABLISH_CHECK,
            {check.name for check in (disruption.postchecks or [])},
        )
        self.assertIn(
            hc_types.CheckName.PORT_STATE_CHECK,
            {check.name for check in (disruption.prechecks or [])},
        )
        port_check = next(
            check
            for check in (disruption.prechecks or [])
            if check.name == hc_types.CheckName.PORT_STATE_CHECK
        )
        port_params = _health_check_params(port_check)
        self.assertEqual(port_params["retry_count"], 30)
        self.assertEqual(port_params["retry_delay_seconds"], 10)
        self.assertEqual(port_params["retry_delay_multiplier"], 1)
        self.assertNotIn(
            hc_types.CheckName.PORT_STATE_CHECK,
            {check.name for check in (disruption.postchecks or [])},
        )

    def test_softdrain_reinjects_with_drain_then_normal_communities(self) -> None:
        drain = next(
            item
            for item in TEST_CONFIG.playbooks
            if item.name == "fpf_gar_bprime1_softdrain_1"
        )
        drain_steps = _steps(drain)
        self.assertEqual(
            [step.name for step in drain_steps],
            [StepName.CUSTOM_STEP, StepName.FPF_BGP_PREFIX_INJECTION_STEP],
        )
        drain_injection = _params(drain_steps[1])
        self.assertIn("65446:10", drain_injection["communities"])
        self.assertEqual(drain_injection["count"], GAR_PREFIX_COUNT)

        undrain = next(
            item
            for item in TEST_CONFIG.playbooks
            if item.name == "fpf_gar_bprime1_undrain_1"
        )
        undrain_steps = _steps(undrain)
        self.assertEqual(
            [step.name for step in undrain_steps],
            [StepName.CUSTOM_STEP, StepName.FPF_BGP_PREFIX_INJECTION_STEP],
        )
        undrain_injection = _params(undrain_steps[1])
        self.assertEqual(undrain_injection["community_list"], "gtsw")
        self.assertNotIn("communities", undrain_injection)
        cleanup = list(undrain.cleanup_steps or [])
        self.assertEqual(
            [step.name for step in cleanup],
            [StepName.CUSTOM_STEP, StepName.FPF_BGP_PREFIX_INJECTION_STEP],
        )

    def test_disruption_requires_every_switch_to_be_undrained(self) -> None:
        disruption = next(
            item
            for item in TEST_CONFIG.playbooks
            if item.name == "fpf_gar_b1_admin_down_1"
        )
        drain_checks = [
            check
            for check in (disruption.prechecks or [])
            if check.name == hc_types.CheckName.DRAIN_STATE_CHECK
        ]
        self.assertEqual(len(drain_checks), 3)
        params = [_health_check_params(check) for check in drain_checks]
        self.assertEqual(
            {item["device_name"] for item in params},
            {endpoint.name for endpoint in TEST_CONFIG.endpoints},
        )
        self.assertEqual({item["expected_drained"] for item in params}, {False})


if __name__ == "__main__":
    unittest.main()
