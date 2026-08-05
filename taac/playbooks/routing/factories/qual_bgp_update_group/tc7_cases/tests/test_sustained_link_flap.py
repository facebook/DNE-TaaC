# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

import json
import typing as t

from later.unittest import TestCase
from taac.health_checks.healthcheck_definitions import (
    create_device_core_dumps_check,
)
from taac.playbooks.routing.factories.qual_bgp_update_group.tc7_cases.sustained_link_flap import (
    create_bgp_ug_sustained_link_flap_playbook,
)


_STATE_KEY = "8bc58bd6-e05a-4fae-8be5-71cce2ca6c87"
_PEER_GROUPS = ["EB-FA-V4", "EB-FA-V6", "EB-EB-V4", "EB-EB-V6"]
_MEMBERS = {
    "EB-FA-V4": 140,
    "EB-FA-V6": 140,
    "EB-EB-V4": 496,
    "EB-EB-V6": 496,
}
_AFIS = {
    "EB-FA-V4": "ipv4",
    "EB-FA-V6": "ipv6",
    "EB-EB-V4": "ipv4",
    "EB-EB-V6": "ipv6",
}


class SustainedLinkFlapPlaybookTest(TestCase):
    def _port_tracks(self) -> list[dict[str, t.Any]]:
        return [
            {
                "role": "ebgp",
                "interface": "Ethernet3/36/1",
                "target_peer_subnets": ["2401:db00:eb::/64"],
            },
            {
                "role": "ibgp",
                "interface": "Ethernet3/36/2",
                "target_peer_subnets": ["2401:db00:ib::/64"],
            },
        ]

    def _leg(self, index: int, receiver_count: int) -> dict[str, t.Any]:
        return {
            "source_prefix_pool_regexes": [f"UG_272_HEARTBEAT_{index}"],
            "receiver_parent_prefixes": ["2401:db00:stable::/64"],
            "expected_receiver_count": receiver_count,
            "allowed_unchanged_receiver_count": 0,
            "expected_route_delta": 1,
        }

    def _full_up_heartbeat(self) -> dict[str, t.Any]:
        return {
            "down_roles": [],
            "verification_mode": "route",
            "legs": [
                self._leg(1, 496),
                self._leg(2, 496),
                self._leg(3, 140),
                self._leg(4, 140),
            ],
        }

    @staticmethod
    def _structural(down_roles: list[str], index: int) -> dict[str, t.Any]:
        return {
            "down_roles": down_roles,
            "verification_mode": "structural",
            "structural_reason": f"no-independent-pair-{index}",
        }

    def _heartbeats(self) -> list[dict[str, t.Any]]:
        return [
            self._full_up_heartbeat(),
            self._structural(["ebgp"], 1),
            self._structural(["ibgp"], 2),
            self._structural(["ebgp", "ibgp"], 3),
        ]

    def _create_playbook(
        self,
        heartbeat_scenarios: t.Sequence[t.Mapping[str, t.Any]] | None = None,
    ) -> t.Any:
        return create_bgp_ug_sustained_link_flap_playbook(
            device_name="bag012.ash6",
            port_tracks=self._port_tracks(),
            heartbeat_scenarios=(
                heartbeat_scenarios
                if heartbeat_scenarios is not None
                else self._heartbeats()
            ),
            state_key=_STATE_KEY,
            peer_group_substrings=_PEER_GROUPS,
            expected_member_counts=_MEMBERS,
            expected_afi_by_substring=_AFIS,
            prechecks=[create_device_core_dumps_check()],
            postchecks=[create_device_core_dumps_check()],
            snapshot_checks=[],
        )

    def test_rejects_missing_required_heartbeat_state(self) -> None:
        with self.assertRaisesRegex(ValueError, "full-up plus all three"):
            create_bgp_ug_sustained_link_flap_playbook(
                device_name="bag012.ash6",
                port_tracks=self._port_tracks(),
                heartbeat_scenarios=self._heartbeats()[:-1],
                state_key=_STATE_KEY,
                peer_group_substrings=_PEER_GROUPS,
                expected_member_counts=_MEMBERS,
                expected_afi_by_substring=_AFIS,
                prechecks=[],
                postchecks=[],
                snapshot_checks=[],
            )

    def test_rejects_invalid_allowed_unchanged_receiver_count(self) -> None:
        for value in (-1, True, 1.5):
            with self.subTest(value=value):
                heartbeats = self._heartbeats()
                heartbeats[0]["legs"][0]["allowed_unchanged_receiver_count"] = value
                with self.assertRaisesRegex(ValueError, "non-negative integer"):
                    self._create_playbook(heartbeats)

    def test_rejects_inexact_update_group_membership(self) -> None:
        invalid_members = {**_MEMBERS, "EB-FA-V4": 139}
        with self.assertRaisesRegex(ValueError, "exact 140/140/496/496"):
            create_bgp_ug_sustained_link_flap_playbook(
                device_name="bag012.ash6",
                port_tracks=self._port_tracks(),
                heartbeat_scenarios=self._heartbeats(),
                state_key=_STATE_KEY,
                peer_group_substrings=_PEER_GROUPS,
                expected_member_counts=invalid_members,
                expected_afi_by_substring=_AFIS,
                prechecks=[],
                postchecks=[],
                snapshot_checks=[],
            )

    def test_rejects_non_positive_route_timeout(self) -> None:
        heartbeats = self._heartbeats()
        heartbeats[0]["legs"][0]["route_verification_timeout_seconds"] = 0

        with self.assertRaisesRegex(ValueError, "timeouts must be positive"):
            self._create_playbook(heartbeats)

    def test_rejects_route_leg_on_structural_overlap(self) -> None:
        heartbeats = self._heartbeats()
        heartbeats[1]["legs"] = [self._leg(20, 140)]

        with self.assertRaisesRegex(ValueError, "cannot configure route heartbeat"):
            self._create_playbook(heartbeats)

    def test_disruption_uses_per_event_and_global_recovery_budgets(self) -> None:
        playbook = self._create_playbook()
        params = json.loads(playbook.stages[1].steps[0].step_params.json_params)

        self.assertEqual(
            "2.7.2 capture time-bounded DUT Bgp-<pid> log evidence",
            playbook.setup_steps[0].description,
        )
        self.assertEqual(
            "2.7.2 publish time-bounded DUT Bgp-<pid> log evidence",
            playbook.cleanup_steps[0].description,
        )
        self.assertEqual(30, params["transition_timeout_seconds"])
        self.assertEqual(70, params["recovery_timeout_seconds"])
        self.assertEqual(600, params["global_recovery_timeout_seconds"])
        self.assertEqual(["IDLE"], params["expected_recovered_group_states"])
        self.assertEqual(4, params["expected_recovered_group_count"])
        self.assertEqual(600, params["recovered_group_state_timeout_seconds"])
        self.assertEqual(1, params["recovered_group_state_poll_interval_seconds"])
        self.assertEqual(12, params["heartbeat_timeout_seconds"])
        self.assertEqual(900, params["heartbeat_preparation_timeout_seconds"])
        self.assertEqual(900, params["route_cleanup_timeout_seconds"])
        self.assertEqual(119, params["event_timeout_seconds"])
        self.assertEqual(630, params["cleanup_timeout_seconds"])
        self.assertTrue(
            all(
                leg["route_verification_timeout_seconds"] == 60
                for scenario in params["heartbeat_scenarios"]
                for leg in scenario.get("legs", [])
            )
        )
        self.assertTrue(
            all(
                leg["state_baseline_timeout_seconds"] == 30
                for scenario in params["heartbeat_scenarios"]
                for leg in scenario.get("legs", [])
            )
        )
        self.assertEqual(
            {"ebgp": 2, "ibgp": 2},
            params["checkpoint_group_counts_by_role"],
        )
        self.assertEqual(1272, params["checkpoint_expected_session_count"])
        self.assertNotIn("expected_ingress_policy_by_role", params)

    def test_steady_state_health_checks_require_idle_groups(self) -> None:
        playbook = self._create_playbook()
        for checks in (playbook.prechecks, playbook.postchecks):
            payloads = [
                json.loads(check.check_params.json_params)
                for check in checks
                if check.check_params is not None
                and check.check_params.json_params is not None
            ]
            exact_group = next(
                payload
                for payload in payloads
                if payload.get("expected_group_count") == 4
            )
            self.assertEqual(["IDLE"], exact_group["expected_group_states"])

    def test_periodic_signals_exclude_queue_blocks_from_expected_link_downs(
        self,
    ) -> None:
        playbook = self._create_playbook()
        periodic_by_name = {task.name: task for task in playbook.periodic_tasks}

        self.assertNotIn("bgp_queue_backpressure_check", periodic_by_name)
        self.assertIn("bgpd_cpu_load_average_check", periodic_by_name)
        self.assertIn("bgpd_cpu_util_check", periodic_by_name)
        self.assertIn("bgpd_mem_util_check", periodic_by_name)
        self.assertIn("process_monitor_check", periodic_by_name)
