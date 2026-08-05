# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

import ipaddress
import json
import typing as t

from later.unittest import TestCase
from taac.health_checks.healthcheck_definitions import (
    create_device_core_dumps_check,
)
from taac.playbooks.routing.factories.qual_bgp_update_group.tc7_cases.cold_start import (
    create_bgp_ug_cold_start_playbook,
)


_STATE_KEY = "720744eb-b19f-4bc8-9105-cdc986ea4050"


def _params(value: t.Any) -> dict[str, t.Any]:
    return json.loads(value.step_params.json_params)


def _ixia_args(value: t.Any) -> dict[str, t.Any]:
    return json.loads(_params(value)["args_json"])


def _task_params(value: t.Any) -> dict[str, t.Any]:
    task = json.loads(value.input_json)["task"]
    return json.loads(task["params"]["json_params"])


def _all_peer_addresses() -> list[str]:
    ipv4_start = ipaddress.ip_address("10.0.0.1")
    ipv6_start = ipaddress.ip_address("2001:db8::1")
    return [
        *(str(ipv4_start + index) for index in range(636)),
        *(str(ipv6_start + index) for index in range(636)),
    ]


def _receiver_scopes() -> dict[str, list[str]]:
    return {
        "ipv4": [f"10.{index // 256}.{index % 256}.1/32" for index in range(496)],
        "ipv6": [f"2401:db00:1::{index + 1}/128" for index in range(496)],
    }


class ColdStartPlaybookTest(TestCase):
    def _create_playbook(
        self,
        *,
        receiver_scopes: t.Mapping[str, t.Sequence[str]] | None = None,
        route_pools: t.Mapping[str, str] | None = None,
        all_peer_addresses: t.Sequence[str] | None = None,
    ) -> t.Any:
        return create_bgp_ug_cold_start_playbook(
            device_name="bag012.ash6",
            state_key=_STATE_KEY,
            device_group_regex="^dg_.*$",
            capture_interfaces=["Ethernet3/36/1", "Ethernet3/36/2"],
            dut_source_addresses=_all_peer_addresses(),
            runtime_update_interfaces=["Ethernet3/36/2"],
            route_pool_regex_by_afi=(
                {
                    "ipv4": "UG_275_EBGP_RUNTIME_V4_100",
                    "ipv6": "UG_275_EBGP_RUNTIME_V6_100",
                }
                if route_pools is None
                else route_pools
            ),
            ibgp_receiver_host_prefixes_by_afi=(
                receiver_scopes if receiver_scopes is not None else _receiver_scopes()
            ),
            all_peer_addresses=(
                _all_peer_addresses()
                if all_peer_addresses is None
                else all_peer_addresses
            ),
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
            prechecks=[create_device_core_dumps_check()],
            postchecks=[create_device_core_dumps_check()],
            snapshot_checks=[],
        )

    def test_builds_verified_zero_state_and_exact_18_group_trigger(self) -> None:
        playbook = self._create_playbook()

        self.assertEqual(
            ("bgp_ug_cold_start", 7), (playbook.name, len(playbook.stages))
        )
        semantic_capture = _params(playbook.stages[0].steps[4])
        all_peer_snapshot = _params(playbook.stages[0].steps[7])
        disable_args = _ixia_args(playbook.stages[0].steps[-1])
        cold_zero_steps = playbook.stages[1].steps
        daemon_disable = _task_params(cold_zero_steps[0])
        daemon_enable = _task_params(cold_zero_steps[1])
        zero = _params(cold_zero_steps[3])
        self.assertEqual(
            ("capture", 1272),
            (semantic_capture["action"], semantic_capture["expected_session_count"]),
        )
        self.assertEqual(1272, len(all_peer_snapshot["peer_addrs"]))
        self.assertEqual(
            (False, 18), (disable_args["enable"], disable_args["expected_match_count"])
        )
        self.assertEqual(
            ("disable", "enable"), (daemon_disable["action"], daemon_enable["action"])
        )
        self.assertEqual(
            ("verify_zero", 1272, 180.0),
            (
                zero["action"],
                zero["expected_configured_session_count"],
                zero["timeout_seconds"],
            ),
        )

    def test_forms_groups_concurrently_with_verified_enable(self) -> None:
        playbook = self._create_playbook()

        formation_stage = playbook.stages[2]
        formation = _params(formation_stage.concurrent_steps[0].steps[0])
        arm_barrier = _params(formation_stage.concurrent_steps[1].steps[0])
        wire_start = _params(formation_stage.concurrent_steps[1].steps[1])
        t0 = _params(formation_stage.concurrent_steps[1].steps[2])
        enable_args = _ixia_args(formation_stage.concurrent_steps[1].steps[3])
        convergence_step = formation_stage.concurrent_steps[1].steps[4]
        convergence = _params(convergence_step)
        self.assertTrue(formation_stage.concurrent)
        self.assertEqual(
            ("formation_monitor", 4, 1272, 600.0),
            (
                formation["action"],
                formation["expected_group_count"],
                formation["expected_session_count"],
                formation["timeout_seconds"],
            ),
        )
        self.assertEqual(
            ("wait_formation_monitor_armed", 60.0),
            (arm_barrier["action"], arm_barrier["timeout_seconds"]),
        )
        self.assertEqual(
            (
                "bgp_cold_start_wire_monitor",
                "start",
                ["Ethernet3/36/1", "Ethernet3/36/2"],
                1272,
            ),
            (
                wire_start["custom_step_name"],
                wire_start["action"],
                wire_start["capture_interfaces"],
                len(wire_start["dut_source_addresses"]),
            ),
        )
        self.assertEqual(
            ("record_jq_timestamp", "bgp_cold_start_formation_t0"),
            (t0["custom_step_name"], t0["var_name"]),
        )
        self.assertEqual(
            (True, 18), (enable_args["enable"], enable_args["expected_match_count"])
        )
        self.assertEqual(
            (1272, 600.0, 5.0, ".bgp_cold_start_formation_t0"),
            (
                convergence["expected_established_sessions"],
                convergence["convergence_hard_timeout_seconds"],
                convergence["convergence_poll_interval_seconds"],
                convergence_step.step_params.jq_params[
                    "convergence_trigger_time_seconds"
                ],
            ),
        )

    def test_enforces_semantic_all_peer_stability_runtime_and_soak(self) -> None:
        playbook = self._create_playbook()

        compare = _params(playbook.stages[3].steps[0])
        all_peer_parity = _params(playbook.stages[3].steps[1])
        capacity_compare = _params(playbook.stages[3].steps[2])
        formation_checkpoint = _params(playbook.stages[3].steps[3])
        stable_snapshot = _params(playbook.stages[3].steps[4])
        stability_wait = _params(playbook.stages[3].steps[5])
        stable_compare = _params(playbook.stages[3].steps[6])
        stable_parity = _params(playbook.stages[3].steps[7])
        runtime = playbook.stages[4].steps
        advertised_pools = [_task_params(step) for step in runtime[0:2]]
        advertise_settle = _params(runtime[2])
        advertised = [_params(step) for step in runtime[3:5]]
        withdrawn_pools = [_task_params(step) for step in runtime[5:7]]
        restored = [_params(step) for step in runtime[8:10]]
        quiet_rebaseline = _params(runtime[10])
        self.assertEqual(
            ("compare", True, False),
            (
                compare["action"],
                compare["require_uniform_sent_route_counts"],
                compare["require_equal_sent_route_counts"],
            ),
        )
        self.assertEqual(
            (0, 0, 1272, 600.0, 5.0, 30.0),
            (
                all_peer_parity["min_delta"],
                all_peer_parity["max_delta"],
                len(all_peer_parity["peer_addrs"]),
                all_peer_parity["convergence_hard_timeout_seconds"],
                all_peer_parity["convergence_poll_interval_seconds"],
                all_peer_parity["convergence_stability_window_seconds"],
            ),
        )
        self.assertEqual(
            ".bgp_cold_start_formation_t0",
            playbook.stages[3]
            .steps[1]
            .step_params.jq_params["convergence_trigger_time_seconds"],
        )
        self.assertEqual(
            ("compare", 100, 100),
            (
                capacity_compare["action"],
                capacity_compare["max_current_delta"],
                capacity_compare["max_high_watermark_increase"],
            ),
        )
        self.assertEqual(
            ("bgp_cold_start_wire_monitor", "checkpoint"),
            (
                formation_checkpoint["custom_step_name"],
                formation_checkpoint["action"],
            ),
        )
        self.assertEqual(
            (1272, 30, "compare", False, 0, 0, 1272),
            (
                len(stable_snapshot["peer_addrs"]),
                stability_wait["duration"],
                stable_compare["action"],
                stable_compare["require_equal_sent_route_counts"],
                stable_parity["min_delta"],
                stable_parity["max_delta"],
                len(stable_parity["peer_addrs"]),
            ),
        )
        self.assertEqual(
            (
                "bgp_cold_start_wire_monitor",
                "rebaseline",
                ["Ethernet3/36/2"],
            ),
            (
                quiet_rebaseline["custom_step_name"],
                quiet_rebaseline["action"],
                quiet_rebaseline["runtime_update_interfaces"],
            ),
        )
        self.assertTrue(
            all(
                (
                    params["prefix_start_index"],
                    params["prefix_end_index"],
                    params["expected_prefix_pool_count"],
                )
                == (0, 100, 1)
                for params in [*advertised_pools, *withdrawn_pools]
            )
        )
        self.assertEqual(
            (30, [100, 100], [496, 496], [0, 0]),
            (
                advertise_settle["duration"],
                [value["min_delta"] for value in advertised],
                [len(value["peer_addrs"]) for value in advertised],
                [value["max_delta"] for value in restored],
            ),
        )
        wire_verify = _params(playbook.stages[6].steps[0])
        self.assertEqual(
            ("bgp_cold_start_wire_monitor", "verify", 1800.0),
            (
                wire_verify["custom_step_name"],
                wire_verify["action"],
                wire_verify["minimum_post_t1_duration_seconds"],
            ),
        )

        soak = playbook.stages[5]
        memory = _params(soak.concurrent_steps[0].steps[0])
        semantic_monitor = _params(soak.concurrent_steps[1].steps[0])
        final_compare = _params(soak.concurrent_steps[1].steps[1])
        self.assertTrue(soak.concurrent)
        self.assertEqual(
            ("bgp_vmhwm_growth_monitor", 1800.0, 199_999_999),
            (
                memory["custom_step_name"],
                memory["duration_seconds"],
                memory["growth_threshold_bytes"],
            ),
        )
        self.assertEqual(
            ("strict", 1800.0, 30.0, "compare", True, False),
            (
                semantic_monitor["case"],
                semantic_monitor["duration_seconds"],
                semantic_monitor["poll_interval_seconds"],
                final_compare["action"],
                final_compare["require_uniform_sent_route_counts"],
                final_compare["require_equal_sent_route_counts"],
            ),
        )

    def test_post_formation_oracle_preserves_semantics_without_counter_equality(
        self,
    ) -> None:
        playbook = self._create_playbook()

        compares = (
            _params(playbook.stages[3].steps[0]),
            _params(playbook.stages[3].steps[6]),
            _params(playbook.stages[5].concurrent_steps[1].steps[1]),
        )
        for compare in compares:
            with self.subTest(compare=compare):
                self.assertEqual("compare", compare["action"])
                self.assertEqual(4, compare["expected_group_count"])
                self.assertEqual(1272, compare["expected_session_count"])
                self.assertTrue(compare["require_uniform_sent_route_counts"])
                self.assertFalse(compare["require_equal_sent_route_counts"])

        stable_parity_step = playbook.stages[3].steps[7]
        stable_parity = _params(stable_parity_step)
        self.assertNotIn("convergence_hard_timeout_seconds", stable_parity)
        self.assertNotIn("convergence_trigger_time_seconds", stable_parity)
        self.assertFalse(stable_parity_step.step_params.jq_params)

    def test_cleanup_restores_18_groups_and_strict_gates(self) -> None:
        playbook = self._create_playbook()

        self.assertEqual(9, len(playbook.cleanup_steps))
        self.assertEqual(
            "2.7.5 capture time-bounded DUT Bgp-<pid> log evidence",
            playbook.setup_steps[0].description,
        )
        self.assertEqual(
            "2.7.5 publish time-bounded DUT Bgp-<pid> log evidence",
            playbook.cleanup_steps[0].description,
        )
        wire_cleanup = _params(playbook.cleanup_steps[1])
        state_cleanup = _params(playbook.cleanup_steps[2])
        capacity_cleanup = _params(playbook.cleanup_steps[3])
        daemon_restore = _task_params(playbook.cleanup_steps[4])
        restore_args = _ixia_args(playbook.cleanup_steps[5])
        cleanup_pools = [_task_params(step) for step in playbook.cleanup_steps[6:8]]
        convergence = _params(playbook.cleanup_steps[8])
        self.assertEqual(
            ("bgp_cold_start_wire_monitor", "cleanup"),
            (wire_cleanup["custom_step_name"], wire_cleanup["action"]),
        )
        self.assertEqual(
            ("clear", "clear"), (state_cleanup["action"], capacity_cleanup["action"])
        )
        self.assertEqual("enable", daemon_restore["action"])
        self.assertEqual(
            (True, 18), (restore_args["enable"], restore_args["expected_match_count"])
        )
        self.assertTrue(
            all(
                (
                    params["enable"],
                    params["target_number_of_addresses"],
                    params["allowed_current_number_of_addresses"],
                    params["safe_number_of_addresses"],
                    params["expected_prefix_pool_count"],
                    "prefix_end_index" in params,
                )
                == (False, 100, [100], 100, 1, False)
                for params in cleanup_pools
            )
        )
        self.assertEqual(1272, convergence["expected_established_sessions"])
        pre_payloads = [
            json.loads(check.check_params.json_params)
            for check in playbook.prechecks
            if check.check_params is not None and check.check_params.json_params
        ]
        checks_with_payloads = [
            (check, json.loads(check.check_params.json_params))
            for check in playbook.postchecks
            if check.check_params is not None and check.check_params.json_params
        ]
        payloads = [payload for _, payload in checks_with_payloads]
        self.assertTrue(
            any(value.get("expected_group_count") == 4 for value in payloads)
        )
        pre_capacity = [
            value for value in pre_payloads if value.get("fec_threshold") == 9_999
        ]
        self.assertEqual(
            (1, 999, False),
            (
                len(pre_capacity),
                pre_capacity[0]["ecmp_threshold"],
                pre_capacity[0]["check_watermarks"],
            ),
        )
        post_capacity = [
            value for value in payloads if value.get("fec_threshold") == 19_999
        ]
        self.assertEqual(
            (1, 999, False, 19_999, 999),
            (
                len(post_capacity),
                post_capacity[0]["ecmp_threshold"],
                post_capacity[0]["check_watermarks"],
                post_capacity[0]["fec_high_watermark_threshold"],
                post_capacity[0]["ecmp_high_watermark_threshold"],
            ),
        )
        self.assertTrue(
            any(value.get("vmhwm_threshold") == 9_999_999_999 for value in payloads)
        )
        periodic_names = {task.name for task in playbook.periodic_tasks}
        self.assertNotIn("bgp_queue_backpressure_check", periodic_names)
        self.assertTrue(
            all(task.terminate_on_error for task in playbook.periodic_tasks[:3])
        )

        restart_checks = [
            (check, payload)
            for check, payload in checks_with_payloads
            if payload.get("services") == ["Bgp"]
            and payload.get("daemons") == ["FibBgpGrpc"]
        ]
        self.assertEqual(2, len(restart_checks))
        intentional = next(
            item
            for item in restart_checks
            if item[1].get("expected_restarted_services") == ["Bgp"]
        )
        post_restart = next(
            item
            for item in restart_checks
            if "expected_restarted_services" not in item[1]
        )
        self.assertEqual(
            (".bgp_cold_start_restart_time", ".bgp_cold_start_restart_time"),
            (
                intentional[0].check_params.jq_params["restart_start_time"],
                post_restart[0].check_params.jq_params["start_time"],
            ),
        )

    def test_rejects_non_dual_afi_runtime_pools(self) -> None:
        with self.assertRaisesRegex(ValueError, "ipv4 and ipv6"):
            self._create_playbook(route_pools={"ipv4": "only-v4"})

    def test_rejects_receiver_cardinality_other_than_496(self) -> None:
        receiver_scopes = _receiver_scopes()
        receiver_scopes["ipv4"].pop()

        with self.assertRaisesRegex(ValueError, "exactly 496 unique ipv4"):
            self._create_playbook(receiver_scopes=receiver_scopes)

    def test_rejects_broad_receiver_subnets(self) -> None:
        receiver_scopes = _receiver_scopes()
        receiver_scopes["ipv6"][0] = "2401:db00:1::/64"

        with self.assertRaisesRegex(ValueError, "individual host"):
            self._create_playbook(receiver_scopes=receiver_scopes)

    def test_rejects_malformed_receiver_with_case_context(self) -> None:
        receiver_scopes = _receiver_scopes()
        receiver_scopes["ipv4"][0] = "not-an-ip"

        with self.assertRaisesRegex(
            ValueError, "2.7.5 ipv4 receivers contain invalid host prefix 'not-an-ip'"
        ):
            self._create_playbook(receiver_scopes=receiver_scopes)

    def test_rejects_empty_or_duplicate_route_pool_regexes(self) -> None:
        for route_pools in (
            {"ipv4": "", "ipv6": "v6"},
            {"ipv4": "same", "ipv6": "same"},
        ):
            with self.subTest(route_pools=route_pools):
                with self.assertRaisesRegex(
                    ValueError, "2 distinct non-empty route-pool regexes"
                ):
                    self._create_playbook(route_pools=route_pools)

    def test_rejects_all_peer_cardinality_other_than_1272(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly 1272 unique peers"):
            self._create_playbook(all_peer_addresses=_all_peer_addresses()[:-1])

    def test_rejects_wrong_all_peer_afi_cardinality(self) -> None:
        addresses = _all_peer_addresses()
        addresses[-1] = "192.0.2.1"

        with self.assertRaisesRegex(ValueError, "636 IPv4 and 636 IPv6"):
            self._create_playbook(all_peer_addresses=addresses)

    def test_rejects_malformed_all_peer_address(self) -> None:
        addresses = _all_peer_addresses()
        addresses[0] = "not-an-ip"

        with self.assertRaisesRegex(ValueError, "invalid address 'not-an-ip'"):
            self._create_playbook(all_peer_addresses=addresses)
