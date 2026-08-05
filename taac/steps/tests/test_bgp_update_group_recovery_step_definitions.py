# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import json
import typing as t
import uuid

from later.unittest import TestCase
from taac.steps.step_definitions import (
    _validate_sustained_checkpoints,
    _validate_sustained_heartbeats,
    create_advertise_withdraw_prefixes_step,
    create_bgp_agent_log_artifact_step,
    create_bgp_lifecycle_convergence_step,
    create_bgp_update_group_disruption_step,
    create_bgp_update_group_physical_restore_step,
    create_bgp_update_group_state_step,
    create_hardware_capacity_delta_step,
    create_ixia_device_group_toggle_step,
    create_prepare_compact_bgp_prefix_pool_step,
    create_verified_fibagent_restart_step,
    create_verify_bgp_sent_route_count_delta_step,
    create_verify_fibagent_active_step,
)
from pyre_extensions import none_throws


class BgpUpdateGroupRecoveryStepDefinitionsTest(TestCase):
    @staticmethod
    def _sustained_checkpoint_probe_params() -> dict[str, t.Any]:
        return {
            "port_tracks": [
                {
                    "role": "ebgp",
                    "interface": "Ethernet3/36/1",
                    "target_peer_subnets": ["192.0.2.0/24"],
                },
                {
                    "role": "ibgp",
                    "interface": "Ethernet3/37/1",
                    "target_peer_subnets": ["2001:db8::/64"],
                },
            ],
            "checkpoint_group_counts_by_role": {"ebgp": 2, "ibgp": 2},
            "checkpoint_expected_group_count": 4,
            "checkpoint_expected_session_count": 1272,
            "checkpoint_transition_timeout_seconds": 60,
        }

    def test_sustained_checkpoint_probe_accepts_exact_contract(self) -> None:
        expected = self._sustained_checkpoint_probe_params()

        step = create_bgp_update_group_disruption_step(
            "bag012.ash6",
            "sustained_checkpoint_probe",
            action_params=expected,
        )
        params = json.loads(none_throws(none_throws(step.step_params).json_params))

        self.assertEqual("bgp_update_group_disruption", params["custom_step_name"])
        self.assertEqual("bag012.ash6", params["hostname"])
        self.assertEqual("sustained_checkpoint_probe", params["action"])
        for name, value in expected.items():
            self.assertEqual(value, params[name])

    def test_sustained_checkpoint_probe_requires_port_tracks(self) -> None:
        params = self._sustained_checkpoint_probe_params()
        del params["port_tracks"]

        with self.assertRaisesRegex(ValueError, "port_tracks"):
            create_bgp_update_group_disruption_step(
                "bag012.ash6",
                "sustained_checkpoint_probe",
                action_params=params,
            )

    def test_sustained_checkpoint_probe_validates_checkpoint_contract(self) -> None:
        invalid_values = (
            (
                "checkpoint_group_counts_by_role",
                {"ebgp": 2},
                "counts for ebgp and ibgp",
            ),
            (
                "checkpoint_expected_group_count",
                5,
                "equal to the per-role checkpoint group-count sum",
            ),
            (
                "checkpoint_expected_session_count",
                0,
                "must be a positive integer",
            ),
        )
        for name, value, message in invalid_values:
            params = self._sustained_checkpoint_probe_params()
            params[name] = value
            with (
                self.subTest(name=name, value=value),
                self.assertRaisesRegex(ValueError, message),
            ):
                create_bgp_update_group_disruption_step(
                    "bag012.ash6",
                    "sustained_checkpoint_probe",
                    action_params=params,
                )

    def test_lifecycle_prior_trigger_budget_is_opt_in(self) -> None:
        legacy = create_bgp_lifecycle_convergence_step(
            "bag012.ash6",
            1272,
            [],
            600.0,
            5.0,
            convergence_soft_threshold_seconds=600.0,
        )
        bounded = create_bgp_lifecycle_convergence_step(
            "bag012.ash6",
            1272,
            [],
            600.0,
            5.0,
            convergence_soft_threshold_seconds=600.0,
            convergence_trigger_time_jq_var="formation_t0",
        )

        legacy_params = json.loads(
            none_throws(none_throws(legacy.step_params).json_params)
        )
        bounded_params = json.loads(
            none_throws(none_throws(bounded.step_params).json_params)
        )
        self.assertEqual(legacy_params, bounded_params)
        self.assertFalse(none_throws(legacy.step_params).jq_params)
        self.assertEqual(
            {"convergence_trigger_time_seconds": ".formation_t0"},
            none_throws(bounded.step_params).jq_params,
        )

    def test_sent_route_prior_trigger_budget_is_opt_in(self) -> None:
        kwargs = {
            "hostname": "bag012.ash6",
            "snapshot_key": "all-peers",
            "peer_addrs": ["192.0.2.1"],
            "min_delta": 0,
            "max_delta": 0,
            "convergence_hard_timeout_seconds": 600.0,
            "convergence_poll_interval_seconds": 5.0,
            "convergence_stability_window_seconds": 30.0,
        }
        legacy = create_verify_bgp_sent_route_count_delta_step(**kwargs)
        bounded = create_verify_bgp_sent_route_count_delta_step(
            **kwargs,
            convergence_trigger_time_jq_var="formation_t0",
        )

        legacy_params = json.loads(
            none_throws(none_throws(legacy.step_params).json_params)
        )
        bounded_params = json.loads(
            none_throws(none_throws(bounded.step_params).json_params)
        )
        self.assertEqual(legacy_params, bounded_params)
        self.assertFalse(none_throws(legacy.step_params).jq_params)
        self.assertEqual(
            {"convergence_trigger_time_seconds": ".formation_t0"},
            none_throws(bounded.step_params).jq_params,
        )

    def test_bgp_agent_log_artifact_serializes_owned_lifecycle(self) -> None:
        step = create_bgp_agent_log_artifact_step(
            "bag012.ash6",
            "capture",
            "case-2.7.4",
            case_id="2.7.4",
        )
        params = json.loads(none_throws(none_throws(step.step_params).json_params))

        self.assertEqual("bgp_agent_log_artifact", params["custom_step_name"])
        self.assertEqual("bag012.ash6", params["hostname"])
        self.assertEqual("capture", params["action"])
        self.assertEqual("case-2.7.4", params["state_key"])
        self.assertIn("Bgp-<pid>", none_throws(step.description))

    def test_bgp_agent_log_artifact_rejects_invalid_inputs(self) -> None:
        for action in ("", "clear"):
            with self.subTest(action=action):
                with self.assertRaisesRegex(ValueError, "capture or publish"):
                    create_bgp_agent_log_artifact_step(
                        "bag012.ash6",
                        action,
                        "case-2.7.4",
                        case_id="2.7.4",
                    )

    def test_sustained_heartbeat_requires_explicit_down_roles(self) -> None:
        for scenario in ({"verification_mode": "route"}, {"down_roles": 1}, 1):
            with self.subTest(scenario=scenario):
                with self.assertRaisesRegex(
                    ValueError,
                    r"heartbeat_scenarios\[0\].*(explicit|collection-valued) down_roles",
                ):
                    _validate_sustained_heartbeats(
                        "sustained_link_flap",
                        {"heartbeat_scenarios": [scenario]},
                    )

    def test_sustained_heartbeat_accepts_two_port_state_contract(self) -> None:
        legs = [
            {
                "expected_receiver_count": receiver_count,
                "expected_route_delta": 1,
                "receiver_parent_prefixes": [f"192.0.{index}.0/24"],
                "source_prefix_pool_regexes": [f"pool-{index}"],
            }
            for index, receiver_count in enumerate((496, 496, 140, 140), 1)
        ]
        self.assertIsNone(
            _validate_sustained_heartbeats(
                "sustained_link_flap",
                {
                    "heartbeat_scenarios": [
                        {
                            "down_roles": [],
                            "verification_mode": "route",
                            "legs": legs,
                        },
                        *(
                            {
                                "down_roles": list(state),
                                "verification_mode": "structural",
                                "structural_reason": "no legal independent route pair",
                            }
                            for state in (
                                ("ebgp",),
                                ("ibgp",),
                                ("ebgp", "ibgp"),
                            )
                        ),
                    ]
                },
            )
        )

    def test_sustained_checkpoint_contract_accepts_positive_session_scale(
        self,
    ) -> None:
        for expected_sessions in (1272, 1274):
            self.assertIsNone(
                _validate_sustained_checkpoints(
                    {
                        "checkpoint_group_counts_by_role": {"ebgp": 2, "ibgp": 2},
                        "checkpoint_expected_group_count": 4,
                        "checkpoint_expected_session_count": expected_sessions,
                    }
                )
            )
        for invalid_sessions in (0, -1, True, "1272"):
            with (
                self.subTest(invalid_sessions=invalid_sessions),
                self.assertRaisesRegex(ValueError, "must be a positive integer"),
            ):
                _validate_sustained_checkpoints(
                    {
                        "checkpoint_group_counts_by_role": {"ebgp": 2, "ibgp": 2},
                        "checkpoint_expected_group_count": 4,
                        "checkpoint_expected_session_count": invalid_sessions,
                    }
                )

    def test_compact_pool_prepare_serializes_safe_resize_contract(self) -> None:
        step = create_prepare_compact_bgp_prefix_pool_step(
            device_name="bag012.ash6",
            prefix_pool_regex=r"^PREFIX_POOL_IPV4_EBGP_UG_2_7_RUNTIME$",
            target_number_of_addresses=20,
            allowed_current_number_of_addresses=(100,),
            safe_number_of_addresses=100,
        )
        task = json.loads(none_throws(step.input_json))["task"]
        params = json.loads(task["params"]["json_params"])

        self.assertEqual("ixia_enable_disable_bgp_prefixes", task["task_name"])
        self.assertFalse(params["enable"])
        self.assertEqual(0, params["prefix_start_index"])
        self.assertNotIn("prefix_end_index", params)
        self.assertEqual(20, params["target_number_of_addresses"])
        self.assertEqual([100], params["allowed_current_number_of_addresses"])
        self.assertEqual(100, params["safe_number_of_addresses"])
        self.assertTrue(params["runtime_route_operation"])

    def test_runtime_route_operation_is_opt_in(self) -> None:
        legacy = create_advertise_withdraw_prefixes_step(
            "bag012.ash6",
            True,
            r"^PREFIX_POOL_IPV4_EBGP_UG_2_7_RUNTIME$",
            0,
            expected_prefix_pool_count=1,
        )
        runtime = create_advertise_withdraw_prefixes_step(
            "bag012.ash6",
            True,
            r"^PREFIX_POOL_IPV4_EBGP_UG_2_7_RUNTIME$",
            0,
            expected_prefix_pool_count=1,
            runtime_route_operation=True,
        )

        legacy_task = json.loads(none_throws(legacy.input_json))["task"]
        runtime_task = json.loads(none_throws(runtime.input_json))["task"]
        legacy_params = json.loads(legacy_task["params"]["json_params"])
        runtime_params = json.loads(runtime_task["params"]["json_params"])

        self.assertNotIn("runtime_route_operation", legacy_params)
        self.assertTrue(runtime_params["runtime_route_operation"])

    def test_hardware_capacity_delta_serializes_compare_contract(self) -> None:
        state_key = str(uuid.uuid4())
        step = create_hardware_capacity_delta_step(
            "bag012.ash6",
            "compare",
            state_key,
        )
        params = json.loads(none_throws(none_throws(step.step_params).json_params))

        self.assertEqual("hardware_capacity_delta", params["custom_step_name"])
        self.assertEqual("bag012.ash6", params["hostname"])
        self.assertEqual(state_key, params["state_key"])
        self.assertEqual(100, params["max_current_delta"])
        self.assertEqual(100, params["max_high_watermark_increase"])

    def test_hardware_capacity_delta_rejects_bad_key_and_threshold(self) -> None:
        with self.assertRaisesRegex(ValueError, "UUID"):
            create_hardware_capacity_delta_step("bag012.ash6", "capture", "bad")
        for value in (True, -1):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "non-negative integer"):
                    create_hardware_capacity_delta_step(
                        "bag012.ash6",
                        "compare",
                        str(uuid.uuid4()),
                        max_current_delta=value,
                    )

    def test_hardware_capacity_delta_rejects_noncompare_thresholds(self) -> None:
        for action in ("capture", "clear"):
            with self.subTest(action=action):
                with self.assertRaisesRegex(ValueError, "only for compare"):
                    create_hardware_capacity_delta_step(
                        "bag012.ash6",
                        action,
                        str(uuid.uuid4()),
                        max_current_delta=99,
                    )
                with self.assertRaisesRegex(ValueError, "non-negative integer"):
                    create_hardware_capacity_delta_step(
                        "bag012.ash6",
                        action,
                        str(uuid.uuid4()),
                        max_high_watermark_increase=True,
                    )

    def test_device_group_toggle_serializes_exact_match_count(self) -> None:
        step = create_ixia_device_group_toggle_step(
            False,
            "BAG012-DG-.*",
            expected_match_count=19,
        )
        invoke = json.loads(none_throws(none_throws(step.step_params).json_params))
        args = json.loads(invoke["args_json"])

        self.assertEqual(19, args["expected_match_count"])
        self.assertFalse(args["enable"])

    def test_device_group_toggle_rejects_boolean_match_count(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-negative integer"):
            create_ixia_device_group_toggle_step(
                False,
                "BAG012-DG-.*",
                expected_match_count=True,
            )

    def test_device_group_toggle_omits_unspecified_match_count(self) -> None:
        step = create_ixia_device_group_toggle_step(True, "BAG012-DG-.*")
        invoke = json.loads(none_throws(none_throws(step.step_params).json_params))
        args = json.loads(invoke["args_json"])

        self.assertNotIn("expected_match_count", args)

    def test_zero_state_action_is_serialized(self) -> None:
        step = create_bgp_update_group_state_step(
            "bag012.ash6",
            "verify_zero",
            str(uuid.uuid4()),
            action_params={
                "expected_configured_session_count": 1274,
                "timeout_seconds": 0,
            },
        )
        params = json.loads(none_throws(none_throws(step.step_params).json_params))

        self.assertEqual("verify_zero", params["action"])
        self.assertEqual(1274, params["expected_configured_session_count"])
        self.assertEqual(0, params["timeout_seconds"])

    def test_zero_state_action_rejects_negative_timeout(self) -> None:
        with self.assertRaisesRegex(ValueError, "timeout_seconds.*non-negative"):
            create_bgp_update_group_state_step(
                "bag012.ash6",
                "verify_zero",
                str(uuid.uuid4()),
                action_params={"timeout_seconds": -1},
            )

    def test_zero_state_action_rejects_non_integer_configured_count(self) -> None:
        for value in (True, 1.0, "1", 0, -1):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(ValueError, "positive integer"),
            ):
                create_bgp_update_group_state_step(
                    "bag012.ash6",
                    "verify_zero",
                    str(uuid.uuid4()),
                    action_params={"expected_configured_session_count": value},
                )

    def test_formation_arming_barrier_is_serialized(self) -> None:
        step = create_bgp_update_group_state_step(
            "bag012.ash6",
            "wait_formation_monitor_armed",
            str(uuid.uuid4()),
            action_params={"timeout_seconds": 60},
        )
        params = json.loads(none_throws(none_throws(step.step_params).json_params))

        self.assertEqual("wait_formation_monitor_armed", params["action"])
        self.assertEqual(60, params["timeout_seconds"])

    def test_monitor_arming_barrier_is_serialized(self) -> None:
        step = create_bgp_update_group_state_step(
            "bag012.ash6",
            "wait_monitor_armed",
            str(uuid.uuid4()),
            action_params={"timeout_seconds": 60},
        )
        params = json.loads(none_throws(none_throws(step.step_params).json_params))

        self.assertEqual("wait_monitor_armed", params["action"])
        self.assertEqual(60, params["timeout_seconds"])

    def test_positive_action_params_reject_booleans_and_non_finite_values(
        self,
    ) -> None:
        for value in (True, False, float("nan"), float("inf"), 0, -1):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "to be positive"):
                    create_bgp_update_group_state_step(
                        "bag012.ash6",
                        "capture",
                        str(uuid.uuid4()),
                        action_params={"expected_group_count": value},
                    )

    def test_positive_action_params_accept_finite_ints_and_floats(self) -> None:
        for value in (1, 1.5):
            with self.subTest(value=value):
                step = create_bgp_update_group_state_step(
                    "bag012.ash6",
                    "capture",
                    str(uuid.uuid4()),
                    action_params={"timeout_seconds": value},
                )
                params = json.loads(
                    none_throws(none_throws(step.step_params).json_params)
                )

                self.assertEqual(value, params["timeout_seconds"])

    def test_fibagent_and_restore_wrappers_use_verified_actions(self) -> None:
        fib = create_verified_fibagent_restart_step(
            "bag012.ash6", require_uptime_change=True
        )
        active = create_verify_fibagent_active_step("bag012.ash6")
        restore = create_bgp_update_group_physical_restore_step(
            "bag012.ash6",
            [
                {
                    "role": role,
                    "interface": f"Ethernet3/36/{index}",
                    "target_peer_subnets": [f"192.0.{index}.0/24"],
                }
                for index, role in enumerate(("ebgp", "ibgp"), 1)
            ],
        )

        fib_params = json.loads(none_throws(none_throws(fib.step_params).json_params))
        self.assertEqual("fibagent_restart", fib_params["action"])
        self.assertTrue(fib_params["require_uptime_change"])
        self.assertEqual(
            "fibagent_active",
            json.loads(none_throws(none_throws(active.step_params).json_params))[
                "action"
            ],
        )
        self.assertEqual(
            "restore_physical_links",
            json.loads(none_throws(none_throws(restore.step_params).json_params))[
                "action"
            ],
        )

    def test_fibagent_restart_rejects_nonboolean_uptime_requirement(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be a boolean"):
            create_verified_fibagent_restart_step(
                "bag012.ash6", require_uptime_change=t.cast(bool, 1)
            )
