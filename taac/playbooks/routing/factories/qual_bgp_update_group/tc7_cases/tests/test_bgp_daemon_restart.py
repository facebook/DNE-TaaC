# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

import ipaddress
import json
import typing as t

from later.unittest import TestCase
from taac.health_checks.healthcheck_definitions import (
    create_device_core_dumps_check,
)
from taac.playbooks.routing.factories.qual_bgp_update_group.tc7_cases.bgp_daemon_restart import (
    create_bgp_ug_bgp_daemon_restart_playbook,
)
from taac.testconfigs.routing.util.bgp_ebb_health_checks import (
    create_standard_postchecks,
)
from taac.test_as_a_config.types import PointInTimeHealthCheck


_STATE_KEY = "6d20955f-9e58-45cd-a54e-61192b7ff70d"


def _params(value: t.Any) -> dict[str, t.Any]:
    return json.loads(value.step_params.json_params)


def _task(value: t.Any) -> tuple[dict[str, t.Any], dict[str, t.Any]]:
    task = json.loads(value.input_json)["task"]
    return task, json.loads(task["params"]["json_params"])


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


class BgpDaemonRestartPlaybookTest(TestCase):
    def _create_playbook(
        self,
        *,
        postchecks: t.Sequence[PointInTimeHealthCheck] | None = None,
        receiver_scopes: t.Mapping[str, t.Sequence[str]] | None = None,
        parent_prefixes_to_ignore: t.Sequence[str] = (),
        route_pool_regex_by_afi: t.Mapping[str, str] | None = None,
    ) -> t.Any:
        return create_bgp_ug_bgp_daemon_restart_playbook(
            device_name="bag012.ash6",
            state_key=_STATE_KEY,
            route_pool_regex_by_afi=(
                route_pool_regex_by_afi
                if route_pool_regex_by_afi is not None
                else {
                    "ipv4": "UG_274_EBGP_RUNTIME_V4_100",
                    "ipv6": "UG_274_EBGP_RUNTIME_V6_100",
                }
            ),
            ibgp_receiver_host_prefixes_by_afi=(
                receiver_scopes if receiver_scopes is not None else _receiver_scopes()
            ),
            all_peer_addresses=_all_peer_addresses(),
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
            postchecks=list(
                postchecks
                if postchecks is not None
                else [create_device_core_dumps_check()]
            ),
            snapshot_checks=[],
            parent_prefixes_to_ignore=parent_prefixes_to_ignore,
        )

    def test_rejects_invalid_route_pool_regex(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            r"contains invalid regex '\['",
        ):
            self._create_playbook(
                route_pool_regex_by_afi={
                    "ipv4": "[",
                    "ipv6": "UG_274_EBGP_RUNTIME_V6_100",
                }
            )

    def test_builds_verified_restart_and_stability_chain(self) -> None:
        playbook = self._create_playbook()

        self.assertEqual("bgp_ug_bgp_daemon_restart", playbook.name)
        self.assertEqual(5, len(playbook.stages))
        capacity_capture = _params(playbook.stages[0].steps[3])
        capture = _params(playbook.stages[0].steps[4])
        all_peer_snapshot = _params(playbook.stages[0].steps[7])
        restart_steps = playbook.stages[1].steps
        disable_task, disable = _task(restart_steps[0])
        wait = _params(restart_steps[1])
        enable_task, enable = _task(restart_steps[2])
        restart_timestamp = _params(restart_steps[3])
        convergence = _params(restart_steps[4])
        compare = _params(playbook.stages[2].steps[0])
        all_peer_parity = _params(playbook.stages[2].steps[1])
        capacity_compare = _params(playbook.stages[2].steps[2])
        stable_snapshot = _params(playbook.stages[2].steps[3])
        stability_wait = _params(playbook.stages[2].steps[4])
        stable_compare = _params(playbook.stages[2].steps[5])
        stable_parity = _params(playbook.stages[2].steps[6])
        self.assertEqual(
            "hardware_capacity_delta", capacity_capture["custom_step_name"]
        )
        self.assertEqual("capture", capacity_capture["action"])
        self.assertEqual("capture", capture["action"])
        self.assertEqual(1272, capture["expected_session_count"])
        self.assertEqual(["IDLE"], capture["expected_group_states"])
        self.assertEqual(1272, len(all_peer_snapshot["peer_addrs"]))
        self.assertEqual(_all_peer_addresses(), all_peer_snapshot["peer_addrs"])
        self.assertEqual(
            [
                "Disable Bgp daemon",
                "Sleep for 5 seconds",
                "Enable Bgp daemon",
                "Record daemon restart completion time",
                "Observe exact BGP lifecycle convergence",
            ],
            [step.description for step in restart_steps],
        )
        self.assertEqual("arista_daemon_control", disable_task["task_name"])
        self.assertEqual(
            {
                "hostname": "bag012.ash6",
                "daemon_name": "Bgp",
                "action": "disable",
            },
            disable,
        )
        self.assertEqual(5, wait["duration"])
        self.assertEqual("arista_daemon_control", enable_task["task_name"])
        self.assertEqual(
            {
                "hostname": "bag012.ash6",
                "daemon_name": "Bgp",
                "action": "enable",
            },
            enable,
        )
        self.assertEqual("record_jq_timestamp", restart_timestamp["custom_step_name"])
        self.assertEqual("daemon_restart_time", restart_timestamp["var_name"])
        self.assertEqual(1272, convergence["expected_established_sessions"])
        self.assertEqual(600.0, convergence["convergence_soft_threshold_seconds"])
        self.assertEqual(600.0, convergence["convergence_hard_timeout_seconds"])
        self.assertEqual(
            "test_bgp_lifecycle_convergence", convergence["custom_step_name"]
        )
        self.assertEqual("bag012.ash6", convergence["hostname"])
        self.assertEqual([], convergence["parent_prefixes_to_ignore"])
        self.assertTrue(convergence["require_initialized"])
        self.assertEqual(5.0, convergence["convergence_poll_interval_seconds"])
        self.assertEqual("compare", compare["action"])
        self.assertEqual(["IDLE"], compare["expected_group_states"])
        self.assertEqual(0, all_peer_parity["min_delta"])
        self.assertEqual(0, all_peer_parity["max_delta"])
        self.assertEqual(1272, len(all_peer_parity["peer_addrs"]))
        self.assertEqual(_all_peer_addresses(), all_peer_parity["peer_addrs"])
        self.assertEqual(
            f"{_STATE_KEY}:all-1272-peers", all_peer_parity["snapshot_key"]
        )
        self.assertEqual(
            "hardware_capacity_delta", capacity_compare["custom_step_name"]
        )
        self.assertEqual("compare", capacity_compare["action"])
        self.assertEqual(100, capacity_compare["max_current_delta"])
        self.assertEqual(100, capacity_compare["max_high_watermark_increase"])
        self.assertEqual(_all_peer_addresses(), stable_snapshot["peer_addrs"])
        self.assertEqual(
            f"{_STATE_KEY}:stable-all-1272-peers",
            stable_snapshot["snapshot_key"],
        )
        self.assertEqual(30, stability_wait["duration"])
        self.assertEqual("compare", stable_compare["action"])
        self.assertEqual(0, stable_parity["min_delta"])
        self.assertEqual(0, stable_parity["max_delta"])
        self.assertEqual(_all_peer_addresses(), stable_parity["peer_addrs"])
        self.assertEqual(
            f"{_STATE_KEY}:stable-all-1272-peers", stable_parity["snapshot_key"]
        )

    def test_runtime_routes_gate_all_496_peers_in_both_afis(self) -> None:
        playbook = self._create_playbook()

        expected_receivers = {
            afi: [str(ipaddress.ip_network(scope).network_address) for scope in scopes]
            for afi, scopes in _receiver_scopes().items()
        }
        snapshots = [_params(step) for step in playbook.stages[0].steps[5:7]]
        route_steps = playbook.stages[3].steps
        advertise_tasks = [_task(step) for step in route_steps[0:2]]
        advertise_settle = _params(route_steps[2])
        advertised = [_params(step) for step in route_steps[3:5]]
        withdraw_tasks = [_task(step) for step in route_steps[5:7]]
        restored = [_params(step) for step in route_steps[8:10]]
        self.assertEqual(
            [f"{_STATE_KEY}:ipv4", f"{_STATE_KEY}:ipv6"],
            [value["snapshot_key"] for value in snapshots],
        )
        self.assertEqual(
            [expected_receivers["ipv4"], expected_receivers["ipv6"]],
            [value["peer_addrs"] for value in snapshots],
        )
        self.assertEqual(
            ["ixia_enable_disable_bgp_prefixes"] * 2,
            [task["task_name"] for task, _ in advertise_tasks],
        )
        self.assertEqual(
            [True, True], [task["ixia_needed"] for task, _ in advertise_tasks]
        )
        self.assertEqual(
            [True, True], [params["enable"] for _, params in advertise_tasks]
        )
        self.assertEqual(
            ["UG_274_EBGP_RUNTIME_V4_100", "UG_274_EBGP_RUNTIME_V6_100"],
            [params["prefix_pool_regex"] for _, params in advertise_tasks],
        )
        self.assertEqual(
            [0, 0], [params["prefix_start_index"] for _, params in advertise_tasks]
        )
        self.assertEqual(
            [100, 100], [params["prefix_end_index"] for _, params in advertise_tasks]
        )
        self.assertEqual(
            [1, 1],
            [params["expected_prefix_pool_count"] for _, params in advertise_tasks],
        )
        self.assertEqual(30, advertise_settle["duration"])
        self.assertEqual(
            [False, False], [params["enable"] for _, params in withdraw_tasks]
        )
        self.assertEqual(
            ["ixia_enable_disable_bgp_prefixes"] * 2,
            [task["task_name"] for task, _ in withdraw_tasks],
        )
        self.assertEqual(
            [True, True], [task["ixia_needed"] for task, _ in withdraw_tasks]
        )
        self.assertEqual(
            ["UG_274_EBGP_RUNTIME_V4_100", "UG_274_EBGP_RUNTIME_V6_100"],
            [params["prefix_pool_regex"] for _, params in withdraw_tasks],
        )
        self.assertEqual(
            [0, 0], [params["prefix_start_index"] for _, params in withdraw_tasks]
        )
        self.assertEqual(
            [100, 100], [params["prefix_end_index"] for _, params in withdraw_tasks]
        )
        self.assertEqual(
            [1, 1],
            [params["expected_prefix_pool_count"] for _, params in withdraw_tasks],
        )
        self.assertEqual([100, 100], [value["min_delta"] for value in advertised])
        self.assertEqual([100, 100], [value["max_delta"] for value in advertised])
        self.assertEqual([0, 0], [value["min_delta"] for value in restored])
        self.assertEqual([0, 0], [value["max_delta"] for value in restored])
        self.assertEqual([496, 496], [len(value["peer_addrs"]) for value in advertised])
        self.assertEqual(
            [expected_receivers["ipv4"], expected_receivers["ipv6"]],
            [value["peer_addrs"] for value in advertised],
        )
        self.assertEqual(
            [f"{_STATE_KEY}:ipv4", f"{_STATE_KEY}:ipv6"],
            [value["snapshot_key"] for value in advertised],
        )
        self.assertEqual(
            [expected_receivers["ipv4"], expected_receivers["ipv6"]],
            [value["peer_addrs"] for value in restored],
        )
        self.assertEqual(
            [f"{_STATE_KEY}:ipv4", f"{_STATE_KEY}:ipv6"],
            [value["snapshot_key"] for value in restored],
        )
        self.assertTrue(
            all("peer_parent_prefixes" not in value for value in advertised)
        )
        soak = playbook.stages[4]
        soak_wait = _params(soak.concurrent_steps[0].steps[0])
        soak_compare = _params(soak.concurrent_steps[0].steps[1])
        memory_monitor = _params(soak.concurrent_steps[1].steps[0])
        self.assertTrue(soak.concurrent)
        self.assertEqual(1800, soak_wait["duration"])
        self.assertEqual("compare", soak_compare["action"])
        self.assertEqual("bgp_vmhwm_growth_monitor", memory_monitor["custom_step_name"])
        self.assertEqual(1800, memory_monitor["duration_seconds"])
        self.assertEqual(199_999_999, memory_monitor["growth_threshold_bytes"])

    def test_cleanup_and_resource_gates_are_mandatory(self) -> None:
        playbook = self._create_playbook(
            postchecks=create_standard_postchecks(
                expected_established_session_count=1272,
            )
        )

        self.assertEqual(
            "2.7.4 capture time-bounded DUT Bgp-<pid> log evidence",
            playbook.setup_steps[0].description,
        )
        self.assertEqual(
            [
                "2.7.4 publish time-bounded DUT Bgp-<pid> log evidence",
                "2.7.4 clear semantic Update Group state",
                "2.7.4 clear FEC/ECMP capacity delta baseline",
                "2.7.4 cleanup: verify inactive 100-route ipv4 pool",
                "2.7.4 cleanup: verify inactive 100-route ipv6 pool",
                "2.7.4 cleanup: idempotently enable Bgp",
                "2.7.4 cleanup: restore all 1272 BGP sessions",
            ],
            [step.description for step in playbook.cleanup_steps],
        )
        cleanup_convergence = _params(playbook.cleanup_steps[6])
        self.assertEqual(1272, cleanup_convergence["expected_established_sessions"])
        state_cleanup = _params(playbook.cleanup_steps[1])
        capacity_cleanup = _params(playbook.cleanup_steps[2])
        self.assertEqual("clear", state_cleanup["action"])
        self.assertEqual(
            "hardware_capacity_delta", capacity_cleanup["custom_step_name"]
        )
        self.assertEqual("clear", capacity_cleanup["action"])
        pre_payloads = [
            json.loads(check.check_params.json_params)
            for check in playbook.prechecks
            if check.check_params is not None and check.check_params.json_params
        ]
        payloads = [
            json.loads(check.check_params.json_params)
            for check in playbook.postchecks
            if check.check_params is not None and check.check_params.json_params
        ]
        self.assertEqual(
            1, sum(value.get("expected_group_count") == 4 for value in payloads)
        )
        for check_payloads in (pre_payloads, payloads):
            exact_group = next(
                value
                for value in check_payloads
                if value.get("expected_group_count") == 4
            )
            self.assertEqual(["IDLE"], exact_group["expected_group_states"])
        pre_capacity = [
            value for value in pre_payloads if value.get("fec_threshold") == 9_999
        ]
        self.assertEqual(1, len(pre_capacity))
        self.assertEqual(999, pre_capacity[0]["ecmp_threshold"])
        self.assertEqual(2**63 - 1, pre_capacity[0]["max_ecmp_level1"])
        self.assertEqual(2**63 - 1, pre_capacity[0]["max_ecmp_level2"])
        self.assertEqual(2**63 - 1, pre_capacity[0]["max_ecmp_level3"])
        self.assertEqual(100, pre_capacity[0]["watermark_delta_threshold"])
        self.assertFalse(pre_capacity[0]["check_watermarks"])
        self.assertNotIn("fec_high_watermark_threshold", pre_capacity[0])
        self.assertNotIn("ecmp_high_watermark_threshold", pre_capacity[0])
        post_capacity = [
            value for value in payloads if value.get("fec_threshold") == 19_999
        ]
        self.assertEqual(1, len(post_capacity))
        self.assertEqual(999, post_capacity[0]["ecmp_threshold"])
        self.assertEqual(2**63 - 1, post_capacity[0]["max_ecmp_level1"])
        self.assertEqual(2**63 - 1, post_capacity[0]["max_ecmp_level2"])
        self.assertEqual(2**63 - 1, post_capacity[0]["max_ecmp_level3"])
        self.assertEqual(100, post_capacity[0]["watermark_delta_threshold"])
        self.assertFalse(post_capacity[0]["check_watermarks"])
        self.assertEqual(19_999, post_capacity[0]["fec_high_watermark_threshold"])
        self.assertEqual(999, post_capacity[0]["ecmp_high_watermark_threshold"])
        self.assertEqual(
            1, sum(value.get("fec_threshold") == 19_999 for value in payloads)
        )
        self.assertEqual(
            1,
            sum(value.get("vmhwm_threshold") == 9_999_999_999 for value in payloads),
        )
        self.assertEqual(1, sum(value.get("baseline") == 12.0 for value in payloads))
        restart_checks = [
            check
            for check in playbook.postchecks
            if check.check_params is not None
            and check.check_params.json_params
            and json.loads(check.check_params.json_params).get(
                "expected_restarted_services"
            )
        ]
        self.assertEqual(1, len(restart_checks))
        restart_check = restart_checks[0]
        restart_payload = json.loads(restart_check.check_params.json_params)
        self.assertEqual(["Bgp"], restart_payload["expected_restarted_services"])
        self.assertEqual(
            ["Bgp", "FibAgent", "FibAgentBgp"], restart_payload["services"]
        )
        self.assertEqual(["FibBgpGrpc"], restart_payload["daemons"])
        self.assertEqual(
            ".daemon_restart_time",
            restart_check.check_params.jq_params["restart_start_time"],
        )
        self.assertEqual(
            ".test_case_start_time",
            restart_check.check_params.jq_params["start_time"],
        )
        periodic_names = {task.name for task in playbook.periodic_tasks}
        self.assertNotIn("bgp_queue_backpressure_check", periodic_names)
        self.assertTrue(
            all(task.terminate_on_error for task in playbook.periodic_tasks[:3])
        )

    def test_rejects_incomplete_all_peer_route_parity_scope(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly 1272 unique peers"):
            create_bgp_ug_bgp_daemon_restart_playbook(
                device_name="bag012.ash6",
                state_key=_STATE_KEY,
                route_pool_regex_by_afi={"ipv4": "v4", "ipv6": "v6"},
                ibgp_receiver_host_prefixes_by_afi={
                    "ipv4": ["10.0.0.0/8"],
                    "ipv6": ["2401:db00:1::/64"],
                },
                all_peer_addresses=_all_peer_addresses()[:-1],
                peer_group_substrings=[],
                expected_member_counts={},
                expected_afi_by_substring={},
                prechecks=[],
                postchecks=[],
                snapshot_checks=[],
            )

    def test_threads_non_test_prefix_exclusion_through_restart_and_cleanup(
        self,
    ) -> None:
        playbook = self._create_playbook(
            parent_prefixes_to_ignore=["2401:db00:e50d:22:a::/80"]
        )

        restart_convergence = _params(playbook.stages[1].steps[-1])
        cleanup_convergence = _params(playbook.cleanup_steps[-1])
        expected = ["2401:db00:e50d:22:a::/80"]
        self.assertEqual(expected, restart_convergence["parent_prefixes_to_ignore"])
        self.assertEqual(expected, cleanup_convergence["parent_prefixes_to_ignore"])

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
            ValueError, "2.7.4 ipv4 receivers contain invalid host prefix 'not-an-ip'"
        ):
            self._create_playbook(receiver_scopes=receiver_scopes)
