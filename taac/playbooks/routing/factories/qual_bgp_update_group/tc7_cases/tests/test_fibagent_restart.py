# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

import json
import typing as t

from later.unittest import TestCase
from taac.health_checks.healthcheck_definitions import (
    create_service_restart_check,
)
from taac.playbooks.routing.factories.qual_bgp_update_group.tc7_cases.fibagent_restart import (
    create_bgp_ug_fibagent_restart_playbook,
)
from taac.testconfigs.routing.util.bgp_ebb_health_checks import (
    create_standard_postchecks,
)
from pyre_extensions import none_throws
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config.types import PointInTimeHealthCheck


_STATE_KEY = "22873c65-1a92-48cb-bda7-9527be4bed42"


def _params(value: t.Any) -> dict[str, t.Any]:
    return json.loads(value.step_params.json_params)


def _task(value: t.Any) -> tuple[dict[str, t.Any], dict[str, t.Any]]:
    task = json.loads(value.input_json)["task"]
    return task, json.loads(task["params"]["json_params"])


def _receiver_scopes() -> dict[str, list[str]]:
    return {
        "ipv4": [f"10.{index // 256}.{index % 256}.1/32" for index in range(496)],
        "ipv6": [f"2401:db00:1::{index + 1}/128" for index in range(496)],
    }


class FibagentRestartPlaybookTest(TestCase):
    def _create_playbook(
        self,
        *,
        route_pools: t.Mapping[str, str] | None = None,
        receiver_scopes: t.Mapping[str, t.Sequence[str]] | None = None,
        postchecks: t.Sequence[PointInTimeHealthCheck] | None = None,
    ) -> t.Any:
        selected_pools = (
            route_pools
            if route_pools is not None
            else {
                "ipv4": "UG_276_EBGP_RUNTIME_V4_100",
                "ipv6": "UG_276_EBGP_RUNTIME_V6_100",
            }
        )
        selected_receivers = (
            receiver_scopes if receiver_scopes is not None else _receiver_scopes()
        )
        return create_bgp_ug_fibagent_restart_playbook(
            device_name="bag012.ash6",
            state_key=_STATE_KEY,
            route_pool_regex_by_afi=selected_pools,
            ibgp_receiver_parent_prefixes_by_afi=selected_receivers,
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
            postchecks=list(postchecks or [PointInTimeHealthCheck()]),
            snapshot_checks=[],
        )

    def test_verifies_trigger_while_monitoring_group_id_continuity(self) -> None:
        playbook = self._create_playbook()

        self.assertEqual("bgp_ug_fibagent_restart", playbook.name)
        self.assertEqual(5, len(playbook.stages))
        capacity_capture = _params(playbook.stages[0].steps[3])
        capture = _params(playbook.stages[0].steps[4])
        restart_stage = playbook.stages[1]
        arm_barrier = _params(restart_stage.concurrent_steps[0].steps[0])
        restart = _params(restart_stage.concurrent_steps[0].steps[1])
        monitor = _params(restart_stage.concurrent_steps[1].steps[0])
        self.assertEqual("group_id", capture["operational_continuity"])
        self.assertEqual(4, capture["expected_group_count"])
        self.assertEqual(1272, capture["expected_session_count"])
        self.assertEqual(["IDLE"], capture["expected_group_states"])
        self.assertEqual("wait_monitor_armed", arm_barrier["action"])
        self.assertEqual(60.0, arm_barrier["timeout_seconds"])
        self.assertEqual("fibagent_restart", restart["action"])
        self.assertEqual(300.0, restart["restart_timeout_seconds"])
        self.assertTrue(restart["require_uptime_change"])
        self.assertEqual("monitor", monitor["action"])
        self.assertEqual("fibagent_restart", monitor["case"])
        self.assertEqual("group_id", monitor["operational_continuity"])
        self.assertEqual(4, monitor["expected_group_count"])
        self.assertEqual(1272, monitor["expected_session_count"])
        self.assertEqual(["IDLE"], monitor["expected_group_states"])
        self.assertTrue(monitor["require_uniform_sent_route_counts"])
        self.assertTrue(monitor["require_equal_sent_route_counts"])
        self.assertEqual(305.0, monitor["duration_seconds"])
        self.assertEqual(
            "hardware_capacity_delta", capacity_capture["custom_step_name"]
        )
        self.assertEqual("capture", capacity_capture["action"])
        self.assertEqual(_STATE_KEY, capacity_capture["state_key"])

    def test_runtime_pools_are_exactly_scoped_to_100_routes(self) -> None:
        playbook = self._create_playbook()

        route_steps = [
            *playbook.stages[0].steps[:2],
            *playbook.stages[3].steps[:2],
            *playbook.stages[3].steps[5:7],
            *playbook.cleanup_steps[-2:],
        ]
        toggles = [_task(step) for step in route_steps]
        self.assertTrue(all(task["ixia_needed"] for task, _ in toggles))
        self.assertTrue(
            all(
                task["task_name"] == "ixia_enable_disable_bgp_prefixes"
                for task, _ in toggles
            )
        )
        self.assertTrue(all(params["prefix_start_index"] == 0 for _, params in toggles))
        self.assertTrue(
            all(params["expected_prefix_pool_count"] == 1 for _, params in toggles)
        )
        prepared = [
            params for _, params in toggles if "target_number_of_addresses" in params
        ]
        operated = [
            params for _, params in toggles if "expected_number_of_addresses" in params
        ]
        self.assertTrue(all("prefix_end_index" not in params for params in prepared))
        self.assertTrue(all(params["prefix_end_index"] == 100 for params in operated))
        self.assertEqual(4, len(prepared))
        self.assertEqual(4, len(operated))
        self.assertTrue(
            all(params["target_number_of_addresses"] == 100 for params in prepared)
        )
        self.assertTrue(
            all(params["expected_number_of_addresses"] == 100 for params in operated)
        )

    def test_requires_semantic_and_route_count_continuity(self) -> None:
        playbook = self._create_playbook()

        validation = playbook.stages[2].steps
        compare = _params(validation[0])
        unchanged = [_params(step) for step in validation[1:3]]
        capacity_compare = _params(validation[3])
        self.assertEqual("group_id", compare["operational_continuity"])
        self.assertTrue(compare["require_uniform_sent_route_counts"])
        self.assertTrue(compare["require_equal_sent_route_counts"])
        self.assertEqual([0, 0], [value["min_delta"] for value in unchanged])
        self.assertEqual([0, 0], [value["max_delta"] for value in unchanged])
        self.assertEqual(
            "hardware_capacity_delta", capacity_compare["custom_step_name"]
        )
        self.assertEqual("compare", capacity_compare["action"])
        self.assertEqual(100, capacity_compare["max_current_delta"])
        self.assertEqual(100, capacity_compare["max_high_watermark_increase"])

    def test_uses_exact_non_origin_receiver_addresses_for_both_afis(self) -> None:
        playbook = self._create_playbook()

        snapshots = [_params(step) for step in playbook.stages[0].steps[5:7]]
        self.assertEqual([496, 496], [len(value["peer_addrs"]) for value in snapshots])
        self.assertTrue(all("peer_parent_prefixes" not in value for value in snapshots))

    def test_runtime_dual_afi_distribution_and_soak_are_exact(self) -> None:
        playbook = self._create_playbook()

        runtime = playbook.stages[3].steps
        advertised = [_params(step) for step in runtime[3:5]]
        restored = [_params(step) for step in runtime[8:10]]
        self.assertEqual(30, _params(runtime[2])["duration"])
        self.assertEqual([100, 100], [value["min_delta"] for value in advertised])
        self.assertEqual([100, 100], [value["max_delta"] for value in advertised])
        self.assertEqual([0, 0], [value["min_delta"] for value in restored])
        self.assertEqual([0, 0], [value["max_delta"] for value in restored])
        capacity_compare = _params(runtime[10])
        self.assertEqual(
            "hardware_capacity_delta", capacity_compare["custom_step_name"]
        )
        self.assertEqual("compare", capacity_compare["action"])
        self.assertEqual(100, capacity_compare["max_current_delta"])
        self.assertEqual(100, capacity_compare["max_high_watermark_increase"])
        soak = playbook.stages[4]
        soak_steps = soak.concurrent_steps[0].steps
        memory_monitor = _params(soak.concurrent_steps[1].steps[0])
        self.assertEqual(1800, _params(soak_steps[0])["duration"])
        soak_compare = _params(soak_steps[1])
        self.assertEqual("group_id", soak_compare["operational_continuity"])
        self.assertEqual("bgp_vmhwm_growth_monitor", memory_monitor["custom_step_name"])
        self.assertEqual(1800, memory_monitor["duration_seconds"])
        self.assertEqual(199_999_999, memory_monitor["growth_threshold_bytes"])

    def test_cleanup_and_strict_postconditions_are_present(self) -> None:
        playbook = self._create_playbook()

        self.assertEqual(
            "2.7.6 capture time-bounded DUT Bgp-<pid> log evidence",
            playbook.setup_steps[0].description,
        )
        self.assertEqual(
            [
                "2.7.6 publish time-bounded DUT Bgp-<pid> log evidence",
                "2.7.6 clear operational Update Group state",
                "2.7.6 clear FEC/ECMP capacity delta baseline",
                "2.7.6 cleanup: idempotently restore the EOS L3 forwarding agent",
                "2.7.6 cleanup: verify the EOS L3 forwarding agent is active",
                "2.7.6 cleanup: allow FibAgent recovery to settle",
                "2.7.6 cleanup: verify inactive 100-route ipv4 pool",
                "2.7.6 cleanup: verify inactive 100-route ipv6 pool",
            ],
            [step.description for step in playbook.cleanup_steps],
        )
        self.assertEqual("clear", _params(playbook.cleanup_steps[1])["action"])
        capacity_clear = _params(playbook.cleanup_steps[2])
        self.assertEqual("hardware_capacity_delta", capacity_clear["custom_step_name"])
        self.assertEqual("clear", capacity_clear["action"])
        recovery = json.loads(playbook.cleanup_steps[3].input_json)
        self.assertEqual(10, recovery["name"])
        self.assertEqual(2, recovery["trigger"])
        active = _params(playbook.cleanup_steps[4])
        self.assertEqual("fibagent_active", active["action"])
        self.assertEqual(300.0, active["active_timeout_seconds"])
        self.assertEqual(30, _params(playbook.cleanup_steps[5])["duration"])
        pre_capacity = [
            (check, json.loads(check.check_params.json_params))
            for check in playbook.prechecks
            if check.check_params is not None
            and check.check_params.json_params
            and check.name == hc_types.CheckName.HARDWARE_CAPACITY_CHECK
        ]
        payloads = [
            json.loads(check.check_params.json_params)
            for check in playbook.postchecks
            if check.check_params is not None and check.check_params.json_params
        ]
        self.assertTrue(
            any(value.get("expected_group_count") == 4 for value in payloads)
        )
        for check_payloads in (
            [
                json.loads(check.check_params.json_params)
                for check in playbook.prechecks
                if check.check_params is not None and check.check_params.json_params
            ],
            payloads,
        ):
            exact_group = next(
                value
                for value in check_payloads
                if value.get("expected_group_count") == 4
            )
            self.assertEqual(["IDLE"], exact_group["expected_group_states"])
        self.assertEqual(1, len(pre_capacity))
        self.assertEqual(
            "baseline_hardware_capacity_collection", pre_capacity[0][0].check_id
        )
        self.assertEqual(2**63 - 1, pre_capacity[0][1]["fec_threshold"])
        self.assertEqual(2**63 - 1, pre_capacity[0][1]["ecmp_threshold"])
        self.assertFalse(pre_capacity[0][1]["check_watermarks"])
        post_capacity = [
            value for value in payloads if value.get("fec_threshold") == 19_999
        ]
        self.assertEqual(1, len(post_capacity))
        self.assertEqual(999, post_capacity[0]["ecmp_threshold"])
        self.assertFalse(post_capacity[0]["check_watermarks"])
        self.assertTrue(
            any(value.get("vmhwm_threshold") == 9_999_999_999 for value in payloads)
        )
        self.assertTrue(any(value.get("services") == ["Bgp"] for value in payloads))
        periodic_names = {task.name for task in playbook.periodic_tasks}
        self.assertNotIn("bgp_queue_backpressure_check", periodic_names)
        self.assertTrue(
            all(task.terminate_on_error for task in playbook.periodic_tasks[:3])
        )

    def test_exempts_only_fibagent_from_standard_restart_guard(self) -> None:
        standard_postchecks = create_standard_postchecks(
            expected_established_session_count=1272,
        )
        inherited_restart_checks = [
            check
            for check in standard_postchecks
            if check.check_params is not None
            and check.check_params.json_params
            and "FibAgent"
            in json.loads(check.check_params.json_params).get("services", [])
        ]
        self.assertEqual(1, len(inherited_restart_checks))
        inherited_restart_check = inherited_restart_checks[0]
        inherited_params = none_throws(inherited_restart_check.check_params)
        inherited_payload = json.loads(none_throws(inherited_params.json_params))
        inherited_payload["custom_marker"] = "preserve"
        original_restart_check = inherited_restart_check
        inherited_restart_check = inherited_restart_check(
            check_params=inherited_params(json_params=json.dumps(inherited_payload))
        )
        standard_postchecks = [
            inherited_restart_check if check is original_restart_check else check
            for check in standard_postchecks
        ]
        inherited_params = none_throws(inherited_restart_check.check_params)
        inherited_jq_params = dict(none_throws(inherited_params.jq_params))
        playbook = self._create_playbook(postchecks=standard_postchecks)
        restart_checks = [
            check
            for check in playbook.postchecks
            if check.check_params is not None
            and check.check_params.json_params
            and "services" in json.loads(check.check_params.json_params)
            and "daemons" in json.loads(check.check_params.json_params)
        ]
        self.assertEqual(1, len(restart_checks))
        replacement = restart_checks[0]
        replacement_params = none_throws(replacement.check_params)
        replacement_payload = json.loads(none_throws(replacement_params.json_params))

        self.assertEqual(["Bgp", "FibAgentBgp"], replacement_payload["services"])
        self.assertEqual(["FibBgpGrpc"], replacement_payload["daemons"])
        self.assertEqual("preserve", replacement_payload["custom_marker"])
        self.assertEqual(inherited_jq_params, replacement_params.jq_params)
        for attribute in ("name", "input_json", "priority", "check_scope", "check_id"):
            self.assertEqual(
                getattr(inherited_restart_check, attribute),
                getattr(replacement, attribute),
            )
        for attribute in ("static_params", "transform_params", "cache_params"):
            self.assertEqual(
                getattr(inherited_params, attribute),
                getattr(replacement_params, attribute),
            )
        self.assertIsNot(inherited_restart_check, replacement)
        self.assertIn(
            "FibAgent",
            json.loads(none_throws(inherited_params.json_params))["services"],
        )

    def test_bare_restart_check_is_preserved_with_separate_bgp_guard(self) -> None:
        bare_check = create_service_restart_check()

        playbook = self._create_playbook(postchecks=[bare_check])
        restart_checks = [
            check for check in playbook.postchecks if check.name == bare_check.name
        ]
        payloads = [
            json.loads(none_throws(none_throws(check.check_params).json_params))
            for check in restart_checks
        ]

        self.assertEqual(2, len(restart_checks))
        self.assertEqual(bare_check, restart_checks[0])
        self.assertEqual({}, payloads[0])
        self.assertEqual(["Bgp"], payloads[1]["services"])
        self.assertEqual(["FibBgpGrpc"], payloads[1]["daemons"])

    def test_fibagent_only_check_is_removed_and_bgp_guard_is_added(self) -> None:
        inherited = create_service_restart_check(
            services=["FibAgent"],
            daemons=["OtherDaemon"],
        )

        playbook = self._create_playbook(postchecks=[inherited])
        payloads = [
            json.loads(none_throws(none_throws(check.check_params).json_params))
            for check in playbook.postchecks
            if check.name == inherited.name
        ]

        self.assertEqual(
            [{"services": ["Bgp"], "daemons": ["FibBgpGrpc"]}],
            payloads,
        )

    def test_fibagent_only_check_without_daemons_is_removed(self) -> None:
        inherited = create_service_restart_check(services=["FibAgent"], daemons=[])

        playbook = self._create_playbook(postchecks=[inherited])
        payloads = [
            json.loads(none_throws(none_throws(check.check_params).json_params))
            for check in playbook.postchecks
            if check.name == inherited.name
        ]

        self.assertEqual(
            [{"services": ["Bgp"], "daemons": ["FibBgpGrpc"]}],
            payloads,
        )

    def test_preserves_unrelated_service_restart_checks(self) -> None:
        playbook = self._create_playbook(
            postchecks=[
                create_service_restart_check(
                    services=["OtherAgent"],
                    daemons=[],
                )
            ]
        )
        payloads = [
            json.loads(check.check_params.json_params)
            for check in playbook.postchecks
            if check.check_params is not None and check.check_params.json_params
        ]
        restart_payloads = [
            value for value in payloads if "services" in value and "daemons" in value
        ]

        self.assertEqual(2, len(restart_payloads))
        self.assertIn({"services": ["OtherAgent"], "daemons": []}, restart_payloads)
        self.assertIn(
            {"services": ["Bgp"], "daemons": ["FibBgpGrpc"]},
            restart_payloads,
        )

    def test_rejects_multiple_inherited_fibagent_restart_checks(self) -> None:
        fibagent_check = create_service_restart_check(
            services=["FibAgent"],
            daemons=[],
        )

        with self.assertRaisesRegex(ValueError, "at most one inherited FibAgent"):
            self._create_playbook(postchecks=[fibagent_check, fibagent_check])

    def test_rejects_malformed_inherited_service_restart_json(self) -> None:
        inherited = create_service_restart_check()
        params = none_throws(inherited.check_params)
        malformed = inherited(check_params=params(json_params="{bad"))

        with self.assertRaisesRegex(ValueError, "malformed json_params"):
            self._create_playbook(postchecks=[malformed])

    def test_rejects_nonobject_inherited_service_restart_json(self) -> None:
        inherited = create_service_restart_check()
        params = none_throws(inherited.check_params)
        malformed = inherited(check_params=params(json_params="[]"))

        with self.assertRaisesRegex(ValueError, "must decode to an object"):
            self._create_playbook(postchecks=[malformed])

    def test_rejects_duplicate_runtime_pools(self) -> None:
        with self.assertRaisesRegex(ValueError, "distinct"):
            self._create_playbook(route_pools={"ipv4": "same", "ipv6": "same"})

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
            ValueError, "2.7.6 ipv4 receivers contain invalid host prefix 'not-an-ip'"
        ):
            self._create_playbook(receiver_scopes=receiver_scopes)
