# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

import inspect
import json
import typing as t

from later.unittest import TestCase
from taac.playbooks.routing.factories.qual_bgp_update_group.tc7_cases.link_flap_recovery import (
    create_bgp_ug_link_flap_recovery_playbook,
)
from taac.steps.step_definitions import (
    create_bgp_update_group_disruption_step,
)
from taac.test_as_a_config.types import PointInTimeHealthCheck


_STATE_KEY = "df33d5db-9729-4bb4-ae72-f0c240af6f2b"


def _params(value: t.Any) -> dict[str, t.Any]:
    return json.loads(value.step_params.json_params)


def _run_task_args(value: t.Any) -> tuple[str | None, dict[str, t.Any]]:
    outer = json.loads(value.input_json)
    task = outer.get("task") or {}
    inner = (task.get("params") or {}).get("json_params") or ""
    return task.get("task_name"), json.loads(inner) if inner else {}


class LinkFlapRecoveryPlaybookTest(TestCase):
    def _recovered_peers(self) -> list[str]:
        return [f"2401:db00:eb::{index:x}" for index in range(1, 141)]

    def _target_peer_subnets(self) -> list[str]:
        return [
            *(f"10.163.28.{index}/32" for index in range(1, 141)),
            *(f"{address}/128" for address in self._recovered_peers()),
        ]

    def _create_playbook(
        self,
        *,
        down_seconds: int = 30,
        expected_group_count: int = 4,
        target_peer_subnets: t.Sequence[str] | None = None,
        recovered_ebgp_peer_addrs: t.Sequence[str] | None = None,
    ) -> t.Any:
        return create_bgp_ug_link_flap_recovery_playbook(
            device_name="bag012.ash6",
            interface="Ethernet3/36/1",
            target_peer_subnets=(
                self._target_peer_subnets()
                if target_peer_subnets is None
                else target_peer_subnets
            ),
            route_pool_regexes=["PREFIX_POOL_IBGP_IPV6_UG_2_7_RUNTIME$"],
            recovered_ebgp_peer_addrs=(
                self._recovered_peers()
                if recovered_ebgp_peer_addrs is None
                else recovered_ebgp_peer_addrs
            ),
            state_key=_STATE_KEY,
            peer_group_substrings=[
                "EB-FA-V4",
                "EB-FA-V6",
                "EB-EB-V4",
                "EB-EB-V6",
            ],
            expected_member_counts={
                "EB-FA-V4": 140,
                "EB-FA-V6": 140,
                "EB-EB-V4": 496,
                "EB-EB-V6": 496,
            },
            expected_afi_by_substring={
                "EB-FA-V4": "ipv4",
                "EB-FA-V6": "ipv6",
                "EB-EB-V4": "ipv4",
                "EB-EB-V6": "ipv6",
            },
            prechecks=[PointInTimeHealthCheck()],
            postchecks=[PointInTimeHealthCheck()],
            snapshot_checks=[],
            down_seconds=down_seconds,
            expected_group_count=expected_group_count,
        )

    def test_builds_production_trigger_and_semantic_validation_chain(self) -> None:
        playbook = self._create_playbook()

        self.assertEqual("bgp_ug_link_flap_recovery", playbook.name)
        self.assertEqual(3, len(playbook.stages))
        capture = _params(playbook.stages[0].steps[2])
        route_snapshot = _params(playbook.stages[0].steps[3])
        disruption = _params(playbook.stages[1].steps[0])
        monitor_capture = _params(playbook.stages[0].steps[4])
        monitor_compare = _params(playbook.stages[2].steps[2])
        recovered_delta = _params(playbook.stages[2].steps[0])
        compare = _params(playbook.stages[2].steps[1])
        restored_delta = _params(playbook.stages[2].steps[5])
        baseline_task, baseline_withdraw = _run_task_args(playbook.stages[0].steps[0])
        baseline_settle = _params(playbook.stages[0].steps[1])
        self.assertEqual("ixia_enable_disable_bgp_prefixes", baseline_task)
        self.assertEqual(
            "PREFIX_POOL_IBGP_IPV6_UG_2_7_RUNTIME$",
            baseline_withdraw["prefix_pool_regex"],
        )
        self.assertFalse(baseline_withdraw["enable"])
        self.assertNotIn("prefix_end_index", baseline_withdraw)
        self.assertEqual(1, baseline_withdraw["expected_prefix_pool_count"])
        self.assertEqual(50, baseline_withdraw["target_number_of_addresses"])
        self.assertEqual(
            [50, 100], baseline_withdraw["allowed_current_number_of_addresses"]
        )
        self.assertEqual(100, baseline_withdraw["safe_number_of_addresses"])
        self.assertTrue(baseline_withdraw["runtime_route_operation"])
        self.assertEqual(30, baseline_settle["duration"])
        self.assertEqual("capture", capture["action"])
        self.assertEqual(1272, capture["expected_session_count"])
        self.assertEqual(["IDLE"], capture["expected_group_states"])
        self.assertEqual(140, len(route_snapshot["peer_addrs"]))
        self.assertFalse(playbook.stages[1].concurrent)
        self.assertEqual("link_flap_recovery", disruption["action"])
        self.assertEqual(10, disruption["flap_count"])
        self.assertEqual(30, disruption["down_seconds"])
        self.assertEqual(600, disruption["route_verification_timeout_seconds"])
        self.assertEqual(30, disruption["up_seconds"])
        self.assertEqual(60, disruption["transition_timeout_seconds"])
        self.assertEqual(600, disruption["restore_timeout_seconds"])
        self.assertFalse(disruption["verify_down_route_delta"])
        self.assertNotIn("down_route_receiver_addresses", disruption)
        self.assertNotIn("expected_down_receiver_count", disruption)
        self.assertNotIn("expected_down_route_delta", disruption)
        self.assertNotIn("expected_failed_ebgp_prefix_count", disruption)
        self.assertEqual(180, disruption["bgp_hold_timer_seconds"])
        self.assertEqual(["IDLE"], disruption["expected_recovered_group_states"])
        self.assertEqual(4, disruption["expected_recovered_group_count"])
        self.assertEqual(600, disruption["recovered_group_state_timeout_seconds"])
        self.assertEqual(50, disruption["expected_route_delta"])
        self.assertEqual(0, disruption["prefix_start_index"])
        self.assertEqual(50, disruption["prefix_end_index"])
        self.assertEqual(1, disruption["expected_prefix_pool_count"])
        self.assertNotIn("receiver_parent_prefixes", disruption)
        self.assertEqual(140, disruption["expected_recovered_receiver_count"])
        self.assertEqual(
            [f"{address}/128" for address in self._recovered_peers()],
            disruption["recovered_receiver_parent_prefixes"],
        )
        self.assertEqual(
            "bgp_vmhwm_growth_monitor", monitor_capture["custom_step_name"]
        )
        self.assertEqual("capture", monitor_capture["action"])
        self.assertEqual("compare", monitor_compare["action"])
        self.assertEqual(monitor_capture["state_key"], monitor_compare["state_key"])
        self.assertNotIn("duration_seconds", monitor_capture)
        self.assertNotIn("duration_seconds", monitor_compare)
        self.assertEqual(199_999_999, monitor_capture["growth_threshold_bytes"])
        self.assertEqual(50, recovered_delta["min_delta"])
        self.assertEqual(50, recovered_delta["max_delta"])
        self.assertEqual(140, len(recovered_delta["peer_addrs"]))
        self.assertEqual("compare", compare["action"])
        self.assertEqual(_STATE_KEY, compare["state_key"])
        self.assertEqual(["IDLE"], compare["expected_group_states"])
        self.assertEqual(0, restored_delta["min_delta"])
        self.assertEqual(0, restored_delta["max_delta"])

    def test_cleanup_withdraws_runtime_pool_and_clears_state(self) -> None:
        playbook = self._create_playbook()

        capture = _params(playbook.setup_steps[0])
        publish = _params(playbook.cleanup_steps[0])
        withdraw_task, withdraw = _run_task_args(playbook.cleanup_steps[1])
        memory_clear = _params(playbook.cleanup_steps[2])
        clear = _params(playbook.cleanup_steps[3])
        self.assertEqual(
            ("bgp_agent_log_artifact", "capture", _STATE_KEY),
            (
                capture["custom_step_name"],
                capture["action"],
                capture["state_key"],
            ),
        )
        self.assertEqual(
            ("bgp_agent_log_artifact", "publish", _STATE_KEY),
            (
                publish["custom_step_name"],
                publish["action"],
                publish["state_key"],
            ),
        )
        self.assertEqual("ixia_enable_disable_bgp_prefixes", withdraw_task)
        self.assertEqual(
            "PREFIX_POOL_IBGP_IPV6_UG_2_7_RUNTIME$",
            withdraw["prefix_pool_regex"],
        )
        self.assertFalse(withdraw["enable"])
        self.assertNotIn("prefix_end_index", withdraw)
        self.assertEqual(1, withdraw["expected_prefix_pool_count"])
        self.assertEqual(100, withdraw["target_number_of_addresses"])
        self.assertEqual([50, 100], withdraw["allowed_current_number_of_addresses"])
        self.assertEqual(100, withdraw["safe_number_of_addresses"])
        self.assertTrue(withdraw["runtime_route_operation"])
        self.assertEqual("clear", memory_clear["action"])
        self.assertEqual("clear", clear["action"])
        self.assertEqual(_STATE_KEY, clear["state_key"])

    def test_adds_exact_group_load_memory_and_no_restart_gates(self) -> None:
        playbook = self._create_playbook()

        payloads = [
            json.loads(check.check_params.json_params)
            for check in playbook.postchecks
            if check.check_params is not None and check.check_params.json_params
        ]
        pre_payloads = [
            json.loads(check.check_params.json_params)
            for check in playbook.prechecks
            if check.check_params is not None and check.check_params.json_params
        ]
        self.assertIn(
            {
                "baseline": 12.0,
            },
            payloads,
        )
        self.assertTrue(
            any(payload.get("vmhwm_threshold") == 9_999_999_999 for payload in payloads)
        )
        self.assertTrue(
            any(payload.get("expected_group_count") == 4 for payload in payloads)
        )
        for check_payloads in (pre_payloads, payloads):
            exact_group = next(
                payload
                for payload in check_payloads
                if payload.get("expected_group_count") == 4
            )
            self.assertEqual(["IDLE"], exact_group["expected_group_states"])
        self.assertTrue(any(payload.get("services") == ["Bgp"] for payload in payloads))
        periodic_by_name = {task.name: task for task in playbook.periodic_tasks}
        self.assertEqual(30, periodic_by_name["bgpd_cpu_load_average_check"].interval)
        self.assertTrue(
            periodic_by_name["bgpd_cpu_load_average_check"].terminate_on_error
        )
        self.assertTrue(periodic_by_name["bgpd_mem_util_check"].terminate_on_error)
        self.assertIn("bgpd_cpu_util_check", periodic_by_name)
        self.assertIn("process_monitor_check", periodic_by_name)
        self.assertNotIn("bgp_queue_backpressure_check", periodic_by_name)

    def test_rejects_vacuous_runtime_route_scope(self) -> None:
        with self.assertRaisesRegex(ValueError, "route_pool_regexes"):
            create_bgp_ug_link_flap_recovery_playbook(
                device_name="bag012.ash6",
                interface="Ethernet3/36/1",
                target_peer_subnets=self._target_peer_subnets(),
                route_pool_regexes=[],
                recovered_ebgp_peer_addrs=self._recovered_peers(),
                state_key=_STATE_KEY,
                peer_group_substrings=["EB-FA-V4"],
                expected_member_counts={"EB-FA-V4": 140},
                expected_afi_by_substring={"EB-FA-V4": "ipv4"},
                prechecks=[],
                postchecks=[],
                snapshot_checks=[],
            )

    def test_rejects_inexact_target_peer_cohort(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly 280 unique peers"):
            self._create_playbook(target_peer_subnets=self._target_peer_subnets()[:-1])

    def test_rejects_broad_target_peer_subnet(self) -> None:
        target_peers = self._target_peer_subnets()
        target_peers[0] = "10.163.28.0/24"

        with self.assertRaisesRegex(ValueError, "exact /32 or /128 peer hosts"):
            self._create_playbook(target_peer_subnets=target_peers)

    def test_rejects_wrong_target_peer_afi_split(self) -> None:
        target_peers = self._target_peer_subnets()
        target_peers[0] = "2001:db8:ffff::1/128"

        with self.assertRaisesRegex(ValueError, "140 IPv4 and 140 IPv6"):
            self._create_playbook(target_peer_subnets=target_peers)

    def test_rejects_invalid_target_peer_subnet(self) -> None:
        target_peers = self._target_peer_subnets()
        target_peers[0] = "not-a-subnet"

        with self.assertRaisesRegex(ValueError, "contains invalid subnet"):
            self._create_playbook(target_peer_subnets=target_peers)

    def test_rejects_incomplete_recovered_peer_cohort(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly 140 unique peers"):
            create_bgp_ug_link_flap_recovery_playbook(
                device_name="bag012.ash6",
                interface="Ethernet3/36/1",
                target_peer_subnets=self._target_peer_subnets(),
                route_pool_regexes=["PREFIX_POOL_IBGP_IPV6_UG_2_7_RUNTIME$"],
                recovered_ebgp_peer_addrs=self._recovered_peers()[:-1],
                state_key=_STATE_KEY,
                peer_group_substrings=["EB-FA-V4"],
                expected_member_counts={"EB-FA-V4": 140},
                expected_afi_by_substring={"EB-FA-V4": "ipv4"},
                prechecks=[],
                postchecks=[],
                snapshot_checks=[],
            )

    def test_recovered_receiver_count_is_not_a_configurable_factory_knob(
        self,
    ) -> None:
        self.assertNotIn(
            "expected_recovered_receiver_count",
            inspect.signature(create_bgp_ug_link_flap_recovery_playbook).parameters,
        )

    def test_rejects_invalid_recovered_peer_address(self) -> None:
        recovered_peers = self._recovered_peers()
        recovered_peers[0] = "not-an-ip-address"

        with self.assertRaisesRegex(
            ValueError,
            "recovered_ebgp_peer_addrs contains invalid exact address",
        ):
            self._create_playbook(recovered_ebgp_peer_addrs=recovered_peers)

    def test_rejects_ipv4_recovered_peer(self) -> None:
        recovered_peers = self._recovered_peers()
        recovered_peers[0] = "10.0.0.1"

        with self.assertRaisesRegex(ValueError, "must contain only IPv6 peers"):
            self._create_playbook(recovered_ebgp_peer_addrs=recovered_peers)

    def test_rejects_duplicate_recovered_peer_address(self) -> None:
        recovered_peers = self._recovered_peers()
        recovered_peers.append(recovered_peers[0])

        with self.assertRaisesRegex(ValueError, "contains duplicate addresses"):
            self._create_playbook(recovered_ebgp_peer_addrs=recovered_peers)

    def test_rejects_semantically_duplicate_recovered_peer_address(self) -> None:
        recovered_peers = self._recovered_peers()
        recovered_peers[1] = "2401:db00:00eb:0000:0000:0000:0000:0001"

        with self.assertRaisesRegex(ValueError, "contains duplicate addresses"):
            self._create_playbook(recovered_ebgp_peer_addrs=recovered_peers)

    def test_rejects_nonpositive_down_interval(self) -> None:
        with self.assertRaisesRegex(ValueError, "down_seconds.*positive"):
            self._create_playbook(down_seconds=0)

    def test_rejects_down_interval_at_or_beyond_hold_timer(self) -> None:
        for down_seconds in (180, 181):
            with self.subTest(down_seconds=down_seconds):
                with self.assertRaisesRegex(
                    ValueError, "down_seconds must be less than bgp_hold_timer_seconds"
                ):
                    self._create_playbook(down_seconds=down_seconds)

    def test_threads_group_count_into_every_cycle_recovery_gate(self) -> None:
        disruption = _params(
            self._create_playbook(expected_group_count=7).stages[1].steps[0]
        )

        self.assertEqual(7, disruption["expected_recovered_group_count"])

    def test_structural_down_mode_requires_exact_recovery_scope(self) -> None:
        with self.assertRaisesRegex(ValueError, "recovered_receiver_parent_prefixes"):
            create_bgp_update_group_disruption_step(
                device_name="bag012.ash6",
                action="link_flap_recovery",
                action_params={
                    "bgp_hold_timer_seconds": 180,
                    "expected_target_peer_count": 280,
                    "interface": "Ethernet3/36/1",
                    "target_peer_subnets": ["2401:db00:eb::/64"],
                    "first_down_prefix_pool_regexes": ["IBGP_RUNTIME$"],
                    "verify_down_route_delta": False,
                    "expected_route_delta": 50,
                },
            )

    def test_structural_down_mode_requires_boolean_flag(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be a boolean"):
            create_bgp_update_group_disruption_step(
                device_name="bag012.ash6",
                action="link_flap_recovery",
                action_params={
                    "bgp_hold_timer_seconds": 180,
                    "expected_target_peer_count": 280,
                    "interface": "Ethernet3/36/1",
                    "target_peer_subnets": ["2401:db00:eb::/64"],
                    "first_down_prefix_pool_regexes": ["IBGP_RUNTIME$"],
                    "verify_down_route_delta": "false",
                    "recovered_receiver_parent_prefixes": ["2401:db00:eb::1/128"],
                    "expected_recovered_receiver_count": 1,
                    "expected_route_delta": 50,
                },
            )
