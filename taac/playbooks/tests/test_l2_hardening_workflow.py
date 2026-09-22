# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import json
import unittest

from taac.playbooks.playbook_definitions import (
    create_hardening_of_arp_overload_10x_with_table_clear_playbook,
    create_hardening_of_arp_overload_entries_playbook,
    create_hardening_of_mac_overload_entries_playbook,
    create_hardening_of_mac_overload_with_agent_churn_playbook,
    create_hardening_of_ndp_overload_entries_playbook,
    create_hardening_of_ndp_overload_with_agent_churn_playbook,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types


def _validation_payload(stage: taac_types.Stage) -> dict:
    validation_steps = [
        step for step in stage.steps if step.name == taac_types.StepName.VALIDATION_STEP
    ]
    if len(validation_steps) != 1:
        raise AssertionError(f"Expected one validation step, got {validation_steps}")
    return json.loads(validation_steps[0].input_json or "{}")


def _step_params_payload(step: taac_types.Step) -> dict:
    if step.step_params is None:
        raise AssertionError(f"Expected step parameters for {step}")
    return json.loads(step.step_params.json_params or "{}")


def _health_check_payload(check: taac_types.PointInTimeHealthCheck) -> dict:
    if check.check_params is None:
        raise AssertionError(f"Expected health-check parameters for {check}")
    return json.loads(check.check_params.json_params or "{}")


class L2HardeningWorkflowTest(unittest.TestCase):
    def _assert_ixia_mutations_skip_traffic_restart(
        self, playbook: taac_types.Playbook
    ) -> None:
        steps = [
            *[step for stage in playbook.stages for step in stage.steps],
            *(playbook.cleanup_steps or []),
        ]
        ixia_steps = [
            step
            for step in steps
            if step.name == taac_types.StepName.INVOKE_IXIA_API_STEP
        ]
        self.assertTrue(ixia_steps)
        for step in ixia_steps:
            self.assertIsNotNone(step.step_params)
            params = json.loads(step.step_params.json_params or "{}")
            self.assertTrue(
                params.get("skip_start_traffic"),
                msg=f"IXIA mutation unexpectedly restarts traffic: {step}",
            )

    def _assert_retrying_ndp_observation(self, stage: taac_types.Stage) -> None:
        serialized = json.dumps(_validation_payload(stage))
        self.assertIn("ndp_entry_observe_only", serialized)
        self.assertIn("retry_count", serialized)
        validation_step = next(
            step
            for step in stage.steps
            if step.name == taac_types.StepName.VALIDATION_STEP
        )
        self.assertIsNotNone(validation_step.step_params)
        step_params = json.loads(validation_step.step_params.json_params or "{}")
        self.assertTrue(step_params.get("skip_start_traffic"))

    def test_plain_arp_overload_normalizes_before_recovery_and_final_check(
        self,
    ) -> None:
        playbook = create_hardening_of_arp_overload_entries_playbook(
            downlink_iface="eth1/1/1",
            uplink_iface="eth1/2/1",
            good_arp_entries=500,
            rogue_arp_entries=12_800,
            settle_duration_s=1,
        )

        self.assertEqual(
            [
                "arp_overload_inject",
                "arp_overload_mid_validation",
                "arp_normalize",
                "arp_recovery_longevity",
            ],
            [stage.id for stage in playbook.stages],
        )

        mid = _validation_payload(playbook.stages[1])
        serialized_mid = json.dumps(mid)
        self.assertIn("resource_accountant_activation", serialized_mid)
        self.assertIn("ndp_entry_observe_only", serialized_mid)
        self.assertIn("arp_entry_observe_only", serialized_mid)
        self.assertIn("retry_count", serialized_mid)
        self.assertIn(".test_case_start_time", serialized_mid)
        self._assert_retrying_ndp_observation(playbook.stages[1])
        self._assert_ixia_mutations_skip_traffic_restart(playbook)

        normalize_params = _step_params_payload(playbook.stages[2].steps[0])
        normalize_args = json.loads(normalize_params["args_json"])
        self.assertEqual(1, normalize_args["prefix_count"])

        longevity_params = _step_params_payload(playbook.stages[3].steps[0])
        self.assertEqual(300, longevity_params["duration"])

        postcheck_payloads = [
            _health_check_payload(check)
            for check in playbook.postchecks or []
            if check.name == hc_types.CheckName.L2_ENTRY_THRESHOLD_CHECK
        ]
        self.assertTrue(
            any("arp_entry_upper_lower_threshold" in p for p in postcheck_payloads)
        )
        self.assertTrue(
            any(p.get("ndp_entry_observe_only") for p in postcheck_payloads)
        )
        self.assertTrue(all(p.get("retry_count", 0) > 0 for p in postcheck_payloads))

    def test_plain_ndp_overload_normalizes_before_recovery(self) -> None:
        playbook = create_hardening_of_ndp_overload_entries_playbook(
            device_name="switch.example",
            downlink_iface="eth1/1/1",
            uplink_iface="eth1/2/1",
            good_ndp_entries_downlink=200,
            good_ndp_entries_uplink=250,
            rogue_ndp_entries=40_000,
            settle_duration_s=1,
        )

        self.assertEqual(
            [
                "ndp_overload_inject",
                "ndp_overload_mid_validation",
                "ndp_normalize",
                "ndp_recovery_longevity",
            ],
            [stage.id for stage in playbook.stages],
        )
        serialized_mid = json.dumps(_validation_payload(playbook.stages[1]))
        self.assertIn("resource_accountant_activation", serialized_mid)
        self.assertIn("ndp_entry_observe_only", serialized_mid)
        self._assert_retrying_ndp_observation(playbook.stages[1])
        self._assert_ixia_mutations_skip_traffic_restart(playbook)

        normalize_params = _step_params_payload(playbook.stages[2].steps[0])
        normalize_args = json.loads(normalize_params["args_json"])
        self.assertEqual(200, normalize_args["prefix_count"])

        postcheck_payloads = [
            _health_check_payload(check)
            for check in playbook.postchecks or []
            if check.name == hc_types.CheckName.L2_ENTRY_THRESHOLD_CHECK
        ]
        self.assertTrue(
            any("ndp_entry_upper_lower_threshold" in p for p in postcheck_payloads)
        )
        self.assertTrue(all(p.get("retry_count", 0) > 0 for p in postcheck_payloads))

    def test_plain_mac_overload_records_count_without_asserting_it(self) -> None:
        playbook = create_hardening_of_mac_overload_entries_playbook(
            downlink_iface="eth1/1/1",
            rogue_mac_entry_count=10_000,
            good_mac_entry_count=100,
            good_ndp_entries_uplink=250,
            good_ndp_entries_downlink=200,
            good_arp_entries=500,
            settle_duration_s=1,
        )

        self.assertEqual(
            [
                "mac_overload_inject",
                "mac_overload_mid_validation",
                "mac_normalize",
                "mac_recovery_longevity",
            ],
            [stage.id for stage in playbook.stages],
        )
        serialized_mid = json.dumps(_validation_payload(playbook.stages[1]))
        self.assertNotIn("resource_accountant_activation", serialized_mid)
        self.assertIn("ndp_entry_observe_only", serialized_mid)
        self.assertIn("mac_entry_observe_only", serialized_mid)
        self._assert_retrying_ndp_observation(playbook.stages[1])
        self._assert_ixia_mutations_skip_traffic_restart(playbook)

        postcheck_payloads = [
            _health_check_payload(check)
            for check in playbook.postchecks or []
            if check.name == hc_types.CheckName.L2_ENTRY_THRESHOLD_CHECK
        ]
        self.assertTrue(
            any(p.get("mac_entry_observe_only") for p in postcheck_payloads)
        )
        self.assertFalse(
            any("mac_entry_upper_lower_threshold" in p for p in postcheck_payloads)
        )
        self.assertTrue(
            any(p.get("ndp_entry_observe_only") for p in postcheck_payloads)
        )

    def test_ndp_churn_has_two_strict_validation_windows_and_recovery(self) -> None:
        playbook = create_hardening_of_ndp_overload_with_agent_churn_playbook(
            device_name="switch.example",
            downlink_iface="eth1/1/1",
            uplink_iface="eth1/2/1",
            good_ndp_entries_downlink=200,
            good_ndp_entries_uplink=250,
            rogue_ndp_entries=40_000,
            restart_duration_s=1,
            restart_period_s=1,
            flap_iterations=1,
            coldboot_iterations=1,
            inject_settle_duration_s=1,
            post_churn_settle_duration_s=1,
            recovery_longevity_s=300,
            include_ixia_stable_state_check=False,
        )

        stage_ids = [stage.id for stage in playbook.stages]
        self.assertIn("ndp_overload_mid_validation", stage_ids)
        self.assertIn("ndp_disruption_window_start", stage_ids)
        self.assertIn("ndp_post_disruption_mid_validation", stage_ids)
        self.assertIn("ndp_normalize", stage_ids)
        self.assertIn("ndp_recovery_longevity", stage_ids)
        self._assert_retrying_ndp_observation(
            playbook.stages[stage_ids.index("ndp_overload_mid_validation")]
        )
        post_disruption = playbook.stages[
            stage_ids.index("ndp_post_disruption_mid_validation")
        ]
        self._assert_retrying_ndp_observation(post_disruption)
        for stage_id in (
            "ndp_overload_mid_validation",
            "ndp_post_disruption_mid_validation",
        ):
            self.assertIn(
                "resource_accountant_activation",
                json.dumps(
                    _validation_payload(playbook.stages[stage_ids.index(stage_id)])
                ),
            )
        serialized_post_disruption = json.dumps(_validation_payload(post_disruption))
        self.assertIn("l2_disruption_start_time", serialized_post_disruption)
        self.assertIn("expected_restarted_services", serialized_post_disruption)

        normalize = playbook.stages[stage_ids.index("ndp_normalize")]
        self.assertIn("l2_recovery_start_time", repr(normalize))
        longevity = playbook.stages[stage_ids.index("ndp_recovery_longevity")]
        longevity_params = _step_params_payload(longevity.steps[0])
        self.assertEqual(300, longevity_params["duration"])
        self.assertIn("l2_recovery_start_time", repr(playbook.postchecks))

    def test_arp_table_clear_validates_overload_disruption_and_recovery(self) -> None:
        playbook = create_hardening_of_arp_overload_10x_with_table_clear_playbook(
            device_name="switch.example",
            downlink_iface="eth1/1/1",
            uplink_iface="eth1/2/1",
            good_arp_entries=500,
            rogue_arp_entries_10x=12_800,
            inject_settle_duration_s=1,
            table_relearn_duration_s=1,
            post_clear_settle_duration_s=1,
            recovery_longevity_s=300,
            include_ixia_stable_state_check=False,
        )

        stage_ids = [stage.id for stage in playbook.stages]
        self.assertEqual(
            [
                "arp_overload_10x_inject",
                "arp_overload_mid_validation",
                "arp_disruption_window_start",
                "arp_table_clear_and_relearn",
                "arp_post_disruption_mid_validation",
                "arp_normalize",
                "arp_recovery_longevity",
            ],
            stage_ids,
        )
        self._assert_retrying_ndp_observation(playbook.stages[1])
        self._assert_retrying_ndp_observation(playbook.stages[4])
        self.assertIn("l2_disruption_start_time", repr(playbook.stages[4]))
        self.assertIn("l2_recovery_start_time", repr(playbook.postchecks))

    def test_mac_churn_records_mac_count_without_final_mac_assertion(self) -> None:
        playbook = create_hardening_of_mac_overload_with_agent_churn_playbook(
            device_name="switch.example",
            downlink_iface="eth1/1/1",
            uplink_iface="eth1/2/1",
            good_mac_entry_count=100,
            rogue_mac_entry_count=10_000,
            good_ndp_entries_uplink=250,
            good_ndp_entries_downlink=200,
            good_arp_entries=500,
            restart_duration_s=1,
            restart_period_s=1,
            flap_iterations=1,
            coldboot_iterations=1,
            inject_settle_duration_s=1,
            post_churn_settle_duration_s=1,
            recovery_longevity_s=300,
            include_ixia_stable_state_check=False,
        )

        stage_ids = [stage.id for stage in playbook.stages]
        self.assertIn("mac_overload_mid_validation", stage_ids)
        self.assertIn("mac_post_disruption_mid_validation", stage_ids)
        self.assertIn("mac_normalize", stage_ids)
        self.assertIn("mac_recovery_longevity", stage_ids)
        self._assert_retrying_ndp_observation(
            playbook.stages[stage_ids.index("mac_overload_mid_validation")]
        )
        self._assert_retrying_ndp_observation(
            playbook.stages[stage_ids.index("mac_post_disruption_mid_validation")]
        )
        for stage_id in (
            "mac_overload_mid_validation",
            "mac_post_disruption_mid_validation",
        ):
            self.assertNotIn(
                "resource_accountant_activation",
                json.dumps(
                    _validation_payload(playbook.stages[stage_ids.index(stage_id)])
                ),
            )
        postchecks = [
            _health_check_payload(check)
            for check in playbook.postchecks or []
            if check.name == hc_types.CheckName.L2_ENTRY_THRESHOLD_CHECK
        ]
        self.assertTrue(any(p.get("mac_entry_observe_only") for p in postchecks))
        self.assertFalse(
            any("mac_entry_upper_lower_threshold" in p for p in postchecks)
        )


if __name__ == "__main__":
    unittest.main()
