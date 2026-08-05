# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import json
import typing as t
import uuid

from later.unittest import TestCase
from taac.steps.step_definitions import (
    create_bgp_lifecycle_convergence_step,
    create_bgp_update_group_state_step,
    create_verified_fibagent_restart_step,
    create_verify_bgp_sent_route_count_delta_step,
    create_verify_fibagent_active_step,
)
from pyre_extensions import none_throws


class BgpUpdateGroupRecoveryStepDefinitionsTest(TestCase):
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

    def test_fibagent_wrappers_use_verified_actions(self) -> None:
        restart = create_verified_fibagent_restart_step(
            "bag012.ash6", require_uptime_change=True
        )
        active = create_verify_fibagent_active_step("bag012.ash6")

        restart_params = json.loads(
            none_throws(none_throws(restart.step_params).json_params)
        )
        active_params = json.loads(
            none_throws(none_throws(active.step_params).json_params)
        )
        self.assertEqual("fibagent_restart", restart_params["action"])
        self.assertTrue(restart_params["require_uptime_change"])
        self.assertEqual("fibagent_active", active_params["action"])

    def test_fibagent_restart_rejects_nonboolean_uptime_requirement(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be a boolean"):
            create_verified_fibagent_restart_step(
                "bag012.ash6", require_uptime_change=t.cast(bool, 1)
            )
