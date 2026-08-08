# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

import json
import typing as t

from later.unittest import TestCase
from taac.playbooks.routing.factories.qual_bgp_update_group.tc7_cases.peer_flapping import (
    create_bgp_ug_bgp_peer_flapping_playbook,
)
from taac.test_as_a_config.types import PointInTimeHealthCheck, ValidationStage


_STATE_KEY = "ccbd5a49-2b13-46b7-ae2b-858f315eab65"


def _params(value: t.Any) -> dict[str, t.Any]:
    return json.loads(value.step_params.json_params)


def _task_params(value: t.Any) -> dict[str, t.Any]:
    task = json.loads(value.input_json)["task"]
    return json.loads(task["params"]["json_params"])


class PeerFlappingPlaybookTest(TestCase):
    def _receivers(self) -> list[str]:
        return [
            *(f"10.0.{index // 256}.{index % 256}/32" for index in range(496)),
            *(f"2401:db00::{index:x}/128" for index in range(496)),
        ]

    def _create_playbook(
        self,
        *,
        device_name: str = "bag012.ash6",
        peer_regex: str = r"^BGP_PEER_IPV(?:4|6)_EBGP$",
        churn_prefix_pool_regexes: t.Sequence[str] | None = None,
    ) -> t.Any:
        return create_bgp_ug_bgp_peer_flapping_playbook(
            device_name=device_name,
            peer_regex=peer_regex,
            reserved_peer_addresses=["192.0.2.1", "2001:db8::1"],
            churn_prefix_pool_regexes=(
                [
                    "UG_273_EBGP_V4_RUNTIME_20",
                    "UG_273_EBGP_V6_RUNTIME_20",
                ]
                if churn_prefix_pool_regexes is None
                else churn_prefix_pool_regexes
            ),
            receiver_parent_prefixes=self._receivers(),
            state_key=_STATE_KEY,
            prechecks=[PointInTimeHealthCheck()],
            postchecks=[PointInTimeHealthCheck()],
            snapshot_checks=[],
        )

    def test_periodic_signals_exclude_queue_blocks_during_peer_churn(self) -> None:
        periodic_by_name = {
            task.name: task for task in self._create_playbook().periodic_tasks
        }

        self.assertNotIn("bgp_queue_backpressure_check", periodic_by_name)
        self.assertIn("bgpd_cpu_load_average_check", periodic_by_name)
        self.assertIn("bgpd_mem_util_check", periodic_by_name)
        self.assertIn("process_monitor_check", periodic_by_name)

    def test_builds_exact_trigger_and_validation_chain(self) -> None:
        playbook = self._create_playbook()

        baseline = playbook.stages[0]
        disruption_stage = playbook.stages[1]
        update_group_gate = json.loads(baseline.steps[3].input_json)
        capture = _params(baseline.steps[4])
        memory_snapshot = _params(baseline.steps[5])
        disruption = _params(disruption_stage.steps[0])
        compare = _params(playbook.stages[2].steps[0])
        memory_verify = _params(playbook.stages[2].steps[1])
        self.assertEqual("bgp_ug_bgp_peer_flapping", playbook.name)
        self.assertEqual(
            "2.7.3 capture time-bounded DUT Bgp-<pid> log evidence",
            playbook.setup_steps[0].description,
        )
        self.assertEqual(
            "2.7.3 publish time-bounded DUT Bgp-<pid> log evidence",
            playbook.cleanup_steps[0].description,
        )
        self.assertEqual(3, len(playbook.stages))
        self.assertEqual(1, len(update_group_gate["point_in_time_checks"]))
        exact_group_gate = json.loads(
            update_group_gate["point_in_time_checks"][0]["check_params"]["json_params"]
        )
        self.assertEqual(int(ValidationStage.PRE_TEST), update_group_gate["stage"])
        self.assertTrue(exact_group_gate["expect_enabled"])
        self.assertEqual(4, exact_group_gate["expected_group_count"])
        self.assertEqual(["IDLE"], exact_group_gate["expected_group_states"])
        self.assertEqual(
            {
                "EB-FA-V4": 140,
                "EB-FA-V6": 140,
                "EB-EB-V4": 496,
                "EB-EB-V6": 496,
            },
            exact_group_gate["expected_member_counts"],
        )
        self.assertEqual(
            {
                "EB-FA-V4": "ipv4",
                "EB-FA-V6": "ipv6",
                "EB-EB-V4": "ipv4",
                "EB-EB-V6": "ipv6",
            },
            exact_group_gate["expected_afi_by_substring"],
        )
        self.assertEqual(
            dict.fromkeys(("EB-FA-V4", "EB-FA-V6", "EB-EB-V4", "EB-EB-V6"), 0),
            exact_group_gate["expected_out_delay_seconds_by_substring"],
        )
        self.assertEqual("capture", capture["action"])
        self.assertEqual(1272, capture["expected_session_count"])
        self.assertEqual(["IDLE"], capture["expected_group_states"])
        self.assertFalse(disruption_stage.concurrent)
        self.assertEqual("fixed_peer_flap", disruption["action"])
        self.assertEqual(2713, disruption["seed"])
        self.assertEqual(2, len(disruption["reserved_peer_addresses"]))
        self.assertEqual(1800, disruption["duration_seconds"])
        self.assertEqual(2, len(disruption["churn_prefix_pool_regexes"]))
        self.assertEqual(992, disruption["expected_receiver_count"])
        self.assertEqual(20, disruption["expected_route_delta"])
        self.assertEqual(992, len(disruption["receiver_parent_prefixes"]))
        self.assertNotIn("capture_interface", disruption)
        self.assertNotIn("receiver_source_pairs", disruption)
        self.assertEqual(60, disruption["route_period_seconds"])
        self.assertEqual(10, disruption["route_active_seconds"])
        self.assertEqual(30, disruption["expected_route_cycles"])
        self.assertEqual(600, disruption["restore_timeout_seconds"])
        self.assertEqual(5, disruption["start_headroom_seconds"])
        self.assertIn(
            "post-withdraw route baseline",
            disruption_stage.steps[0].description,
        )
        self.assertIn(
            "per-cycle Update Group announcement/withdrawal counters",
            disruption_stage.steps[0].description,
        )
        self.assertEqual("snapshot_bgp_vmhwm", memory_snapshot["custom_step_name"])
        self.assertEqual(f"{_STATE_KEY}:vmhwm", memory_snapshot["snapshot_key"])
        self.assertEqual("verify_bgp_vmhwm_growth", memory_verify["custom_step_name"])
        self.assertEqual(memory_snapshot["snapshot_key"], memory_verify["snapshot_key"])
        self.assertEqual(199_999_999, memory_verify["growth_threshold_bytes"])
        self.assertEqual("compare", compare["action"])
        self.assertEqual(4, compare["expected_group_count"])
        self.assertEqual(1272, compare["expected_session_count"])
        self.assertEqual(["IDLE"], compare["expected_group_states"])

    def test_shared_pools_resize_to_twenty_and_cleanup_restores_capacity(self) -> None:
        playbook = self._create_playbook()

        baseline = [_task_params(step) for step in playbook.stages[0].steps[:2]]
        cleanup = [_task_params(step) for step in playbook.cleanup_steps[1:3]]
        clear = _params(playbook.cleanup_steps[3])
        self.assertEqual(
            [20, 20], [value["target_number_of_addresses"] for value in baseline]
        )
        self.assertEqual(
            [[100], [100]],
            [value["allowed_current_number_of_addresses"] for value in baseline],
        )
        self.assertEqual(
            [100, 100], [value["target_number_of_addresses"] for value in cleanup]
        )
        self.assertEqual(
            [[20, 100], [20, 100]],
            [value["allowed_current_number_of_addresses"] for value in cleanup],
        )
        self.assertTrue(all(not value["enable"] for value in [*baseline, *cleanup]))
        self.assertTrue(
            all("prefix_end_index" not in value for value in [*baseline, *cleanup])
        )
        self.assertTrue(
            all(
                value["safe_number_of_addresses"] == 100
                for value in [*baseline, *cleanup]
            )
        )
        self.assertEqual("clear", clear["action"])
        self.assertEqual(_STATE_KEY, clear["state_key"])

    def test_adds_exact_group_load_memory_crash_and_periodic_gates(self) -> None:
        playbook = self._create_playbook()

        precheck_payloads = [
            json.loads(check.check_params.json_params)
            for check in playbook.prechecks
            if check.check_params is not None and check.check_params.json_params
        ]
        self.assertFalse(
            any(
                payload.get("expected_group_count") == 4
                for payload in precheck_payloads
            )
        )

        payloads = [
            json.loads(check.check_params.json_params)
            for check in playbook.postchecks
            if check.check_params is not None and check.check_params.json_params
        ]
        exact_group = next(
            payload for payload in payloads if payload.get("expected_group_count") == 4
        )
        self.assertEqual(
            {
                "EB-FA-V4": "ipv4",
                "EB-FA-V6": "ipv6",
                "EB-EB-V4": "ipv4",
                "EB-EB-V6": "ipv6",
            },
            exact_group["expected_afi_by_substring"],
        )
        self.assertEqual(["IDLE"], exact_group["expected_group_states"])
        self.assertTrue(
            any(
                payload.get("expected_out_delay_seconds_by_substring")
                == {
                    "EB-FA-V4": 0,
                    "EB-FA-V6": 0,
                    "EB-EB-V4": 0,
                    "EB-EB-V6": 0,
                }
                for payload in payloads
            )
        )
        self.assertIn({"baseline": 12.0}, payloads)
        self.assertTrue(
            any(payload.get("vmhwm_threshold") == 9_999_999_999 for payload in payloads)
        )
        self.assertTrue(any(payload.get("services") == ["Bgp"] for payload in payloads))
        periodic_by_name = {task.name: task for task in playbook.periodic_tasks}
        self.assertEqual(30, periodic_by_name["bgpd_cpu_load_average_check"].interval)
        self.assertTrue(
            periodic_by_name["bgpd_cpu_load_average_check"].terminate_on_error
        )
        self.assertTrue(periodic_by_name["bgpd_cpu_util_check"].terminate_on_error)
        self.assertTrue(periodic_by_name["bgpd_mem_util_check"].terminate_on_error)

    def test_rejects_receiver_scope_without_both_afis(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly 992 unique"):
            create_bgp_ug_bgp_peer_flapping_playbook(
                device_name="bag012.ash6",
                peer_regex=r"^BGP_PEER_IPV(?:4|6)_EBGP$",
                reserved_peer_addresses=["192.0.2.1", "2001:db8::1"],
                churn_prefix_pool_regexes=["v4", "v6"],
                receiver_parent_prefixes=self._receivers()[:496],
                state_key=_STATE_KEY,
                prechecks=[],
                postchecks=[],
                snapshot_checks=[],
            )

    def test_rejects_invalid_churn_pool_regex(self) -> None:
        with self.assertRaisesRegex(ValueError, "churn pool regex '\\[' is invalid"):
            self._create_playbook(churn_prefix_pool_regexes=["[", "valid-v6"])

    def test_rejects_empty_churn_pool_regex(self) -> None:
        for pool_regex in ("", "   "):
            with (
                self.subTest(pool_regex=pool_regex),
                self.assertRaisesRegex(
                    ValueError, "churn pool regex must be non-empty"
                ),
            ):
                self._create_playbook(
                    churn_prefix_pool_regexes=[pool_regex, "valid-v6"]
                )

    def test_rejects_invalid_peer_regex(self) -> None:
        with self.assertRaisesRegex(ValueError, "peer regex '\\[' is invalid"):
            self._create_playbook(peer_regex="[")

    def test_rejects_empty_device_name(self) -> None:
        for device_name in ("", "   "):
            with (
                self.subTest(device_name=device_name),
                self.assertRaisesRegex(
                    ValueError, "2.7.3 device_name must be non-empty"
                ),
            ):
                self._create_playbook(device_name=device_name)

    def test_rejects_reserved_advertisers_without_dual_afi(self) -> None:
        with self.assertRaisesRegex(ValueError, "one IPv4 and one IPv6 peer"):
            create_bgp_ug_bgp_peer_flapping_playbook(
                device_name="bag012.ash6",
                peer_regex=r"^BGP_PEER_IPV(?:4|6)_EBGP$",
                reserved_peer_addresses=["192.0.2.1", "192.0.2.2"],
                churn_prefix_pool_regexes=["v4", "v6"],
                receiver_parent_prefixes=self._receivers(),
                state_key=_STATE_KEY,
                prechecks=[],
                postchecks=[],
                snapshot_checks=[],
            )

    def test_rejects_malformed_reserved_advertiser_with_context(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "reserved stable advertiser 'not-an-ip' is not a valid IP address",
        ):
            create_bgp_ug_bgp_peer_flapping_playbook(
                device_name="bag012.ash6",
                peer_regex=r"^BGP_PEER_IPV(?:4|6)_EBGP$",
                reserved_peer_addresses=["not-an-ip", "2001:db8::1"],
                churn_prefix_pool_regexes=["v4", "v6"],
                receiver_parent_prefixes=self._receivers(),
                state_key=_STATE_KEY,
                prechecks=[],
                postchecks=[],
                snapshot_checks=[],
            )

    def test_rejects_malformed_receiver_prefix_with_context(self) -> None:
        receivers = self._receivers()
        receivers[0] = "not-a-prefix"
        with self.assertRaisesRegex(
            ValueError,
            "receiver prefix 'not-a-prefix' is not a valid IP prefix",
        ):
            create_bgp_ug_bgp_peer_flapping_playbook(
                device_name="bag012.ash6",
                peer_regex=r"^BGP_PEER_IPV(?:4|6)_EBGP$",
                reserved_peer_addresses=["192.0.2.1", "2001:db8::1"],
                churn_prefix_pool_regexes=["v4", "v6"],
                receiver_parent_prefixes=receivers,
                state_key=_STATE_KEY,
                prechecks=[],
                postchecks=[],
                snapshot_checks=[],
            )
