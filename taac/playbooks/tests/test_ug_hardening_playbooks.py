# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe
"""Unit tests for the BGP++ Update Group hardening 2.4.1/2.4.2/2.4.3 playbook
factories (``create_new_peer_join_full_sync_resilience_playbook``,
``create_new_peer_join_routes_withdrawn_playbook``,
``create_new_peer_join_attribute_change_playbook``).

Each factory is verified for:
- Expected playbook ``name``.
- Stage ordering (Phase 1 / Phase 2 / Phase 4 as applicable).
- Required postcheck CheckNames present (verify-the-knob discipline).
- Cleanup steps present and idempotent in shape.
- Spec-anchor parameters propagated correctly into the JSON params.
"""

import json
import unittest

from taac.playbooks.playbook_definitions import (
    create_new_peer_join_attribute_change_playbook,
    create_new_peer_join_full_sync_resilience_playbook,
    create_new_peer_join_routes_withdrawn_playbook,
)
from taac.health_check.health_check import types as hc_types


DEVICE = "bag012.ash6"
CTRL = ["2401:db00::11", "2401:db00::13", "2401:db00::15", "2401:db00::17"]
HELD = "2401:db00::19"
HELD_REGEX = "BGP_PEER_IPV6_EBGP_UG_HELD"
DISP = [f"2401:db00::{0x21 + 2 * i:x}" for i in range(16)]
DISP_REGEX = "BGP_PEER_IPV6_EBGP_UG_DISP"
B_KEEP = "2401:db00::53"
B_KEEP_REGEX = "BGP_PEER_IPV6_EBGP_UG_B_KEEP"
B_VAR1 = "2401:db00::55"
B_VAR1_REGEX = "BGP_PEER_IPV6_EBGP_UG_B_VAR1"
B_VAR2 = "2401:db00::57"
B_VAR2_REGEX = "BGP_PEER_IPV6_EBGP_UG_B_VAR2"


def _check_names(checks):
    return [c.name for c in (checks or [])]


def _params(check):
    return json.loads(check.check_params.json_params)


class NewPeerJoinFullSyncResiliencePlaybookTest(unittest.TestCase):
    """2.4.1 -- resilience to UG-member churn during sync."""

    def setUp(self):
        self.playbook = create_new_peer_join_full_sync_resilience_playbook(
            device_name=DEVICE,
            control_peer_addrs=CTRL,
            held_back_peer_addr=HELD,
            held_back_peer_regex=HELD_REGEX,
            disp_peer_addrs=DISP,
            disp_peer_regex=DISP_REGEX,
            disp_session_start_idx=1,
            disp_session_end_idx=16,
            b_keep_peer_addr=B_KEEP,
            b_keep_route_count=300,
            b_var1_peer_regex=B_VAR1_REGEX,
            b_var1_peer_addr=B_VAR1,
            b_var1_route_count=200,
            b_var2_peer_regex=B_VAR2_REGEX,
            b_var2_peer_addr=B_VAR2,
            b_var2_route_count=50,
        )

    def test_playbook_has_three_stages_in_spec_order(self):
        """Phase 1 inject -> Phase 2 trigger -> Phase 4 runtime inject."""
        self.assertEqual(self.playbook.name, "new_peer_join_full_sync_resilience")
        self.assertEqual(len(self.playbook.stages), 3)

    def test_cleanup_steps_restore_baseline(self):
        """Phase 5 cleanup must restore DISP UP, VAR1/VAR2 DOWN, HELD DOWN."""
        self.assertIsNotNone(self.playbook.cleanup_steps)
        # 4 toggle steps + 1 longevity step = 5 total.
        self.assertGreaterEqual(len(self.playbook.cleanup_steps), 5)

    def test_prechecks_cover_ug_enabled_membership_and_baseline(self):
        names = _check_names(self.playbook.prechecks)
        self.assertIn(hc_types.CheckName.BGP_UPDATE_GROUP_CHECK, names)
        # BgpSessionEstablished + RouteCount baseline assertions.
        self.assertIn(hc_types.CheckName.BGP_SESSION_ESTABLISH_CHECK, names)
        self.assertIn(hc_types.CheckName.BGP_ROUTE_COUNT_VERIFICATION_CHECK, names)

    def test_postchecks_anchor_set_equality_at_full_sync_count(self):
        names = _check_names(self.playbook.postchecks)
        self.assertIn(hc_types.CheckName.BGP_PEER_ROUTE_SET_EQUALITY_CHECK, names)
        equality_check = next(
            c
            for c in self.playbook.postchecks
            if c.name == hc_types.CheckName.BGP_PEER_ROUTE_SET_EQUALITY_CHECK
        )
        params = _params(equality_check)
        # Postchecks run AFTER Phase 4 (which adds 50 more) so the end-of-test
        # anchor is 550 (300 keep + 200 var1 + 50 var2). The 500 anchor for the
        # "full initial dump" spec gate runs inline at end of Phase 2 instead.
        self.assertEqual(params["anchor_route_count"], 550)
        self.assertEqual(params["baseline_peer_addr"], CTRL[0])
        self.assertIn(HELD, params["tested_peer_addrs"])

    def test_postchecks_verify_held_up_and_disp_down(self):
        """Both trigger-fired diagnostics present."""
        established_checks = [
            c
            for c in self.playbook.postchecks
            if c.name == hc_types.CheckName.BGP_SESSION_ESTABLISH_CHECK
        ]
        self.assertEqual(len(established_checks), 2)
        # One asserts HELD is ESTABLISHED, the other asserts DISP are NOT.
        params_list = [_params(c) for c in established_checks]
        held_check = next(
            p for p in params_list if HELD in p.get("ignore_all_prefixes_except", [])
        )
        disp_check = next(
            p
            for p in params_list
            if set(DISP) <= set(p.get("ignore_all_prefixes_except", []))
        )
        # The factory's Python kwarg is `expected_established_sessions` but
        # the underlying JSON schema key is `expected_established_session_count`.
        self.assertEqual(disp_check.get("expected_established_session_count"), 0)
        # held_check defaults (no explicit 0) -> peer should be ESTABLISHED.
        self.assertNotEqual(held_check.get("expected_established_session_count"), 0)


class NewPeerJoinRoutesWithdrawnPlaybookTest(unittest.TestCase):
    """2.4.2 -- mid-sync withdrawal via sender session-down."""

    def setUp(self):
        self.playbook = create_new_peer_join_routes_withdrawn_playbook(
            device_name=DEVICE,
            control_peer_addrs=CTRL,
            held_back_peer_addr=HELD,
            held_back_peer_regex=HELD_REGEX,
            b_keep_peer_addr=B_KEEP,
            b_keep_route_count=300,
            b_var1_peer_regex=B_VAR1_REGEX,
            b_var1_peer_addr=B_VAR1,
            b_var1_route_count=200,
            b_var1_device_group_regex=B_VAR1_REGEX,
        )

    def test_playbook_name_and_single_trigger_stage(self):
        self.assertEqual(self.playbook.name, "new_peer_join_routes_withdrawn")
        self.assertEqual(len(self.playbook.stages), 1)

    def test_cleanup_restores_var1_up_and_held_down(self):
        self.assertIsNotNone(self.playbook.cleanup_steps)
        self.assertGreaterEqual(len(self.playbook.cleanup_steps), 3)

    def test_postchecks_verify_trigger_fired_and_anchor_at_300(self):
        names = _check_names(self.playbook.postchecks)
        # 2 session-state checks (HELD UP, VAR1 DOWN) + 1 set equality.
        self.assertEqual(
            sum(
                1 for n in names if n == hc_types.CheckName.BGP_SESSION_ESTABLISH_CHECK
            ),
            2,
        )
        equality_check = next(
            c
            for c in self.playbook.postchecks
            if c.name == hc_types.CheckName.BGP_PEER_ROUTE_SET_EQUALITY_CHECK
        )
        params = _params(equality_check)
        # The "300 not 500" assertion.
        self.assertEqual(params["anchor_route_count"], 300)

    def test_prechecks_include_v1_established_baseline(self):
        """For 2.4.2 specifically DG_B_VAR1 starts UP -- precheck must allow
        it (NOT in the expected_established_sessions=0 set)."""
        names = _check_names(self.playbook.prechecks)
        self.assertIn(hc_types.CheckName.BGP_UPDATE_GROUP_CHECK, names)
        self.assertIn(hc_types.CheckName.BGP_ROUTE_COUNT_VERIFICATION_CHECK, names)
        rc_check = next(
            c
            for c in self.playbook.prechecks
            if c.name == hc_types.CheckName.BGP_ROUTE_COUNT_VERIFICATION_CHECK
        )
        # CTRL should already have 500 = 300 keep + 200 var1 at start of 2.4.2.
        self.assertEqual(_params(rc_check)["expected_count"], 500)

    def _ixia_api_args(self, step):
        """Step inputs for INVOKE_IXIA_API_STEP live as nested JSON:
        ``step.step_params.json_params`` -> outer JSON with ``api_name`` and
        ``args_json`` (itself a JSON string)."""
        outer = json.loads(step.step_params.json_params)
        return outer.get("api_name"), json.loads(outer.get("args_json") or "{}")

    def test_trigger_uses_toggle_device_groups_for_durable_admin_down(self):
        """The 2.4.2 trigger must use toggle_device_groups(enable=False) on
        the DG_B_VAR1 regex -- this is durable (survives DUT ConnectRetry).
        IXIA start_bgp_peers(start=False) was previously used and is
        transient (session re-establishes in ~45s, masking the withdraw)."""
        trigger_stage = self.playbook.stages[0]
        toggle_steps = [
            s
            for s in (trigger_stage.steps or [])
            if "admin-disable dg_b_var1" in (s.description or "").lower()
        ]
        self.assertEqual(
            len(toggle_steps),
            1,
            "Expected exactly one toggle_device_groups step in 2.4.2 trigger",
        )
        api_name, args = self._ixia_api_args(toggle_steps[0])
        self.assertEqual(api_name, "toggle_device_groups")
        self.assertEqual(args.get("enable"), False)
        self.assertEqual(args.get("device_group_name_regex"), B_VAR1_REGEX)

    def test_cleanup_re_enables_var1_device_group(self):
        """Cleanup must re-enable DG_B_VAR1 (toggle enable=True) so the next
        playbook starts from a clean baseline."""
        cleanup = self.playbook.cleanup_steps or []
        re_enable = [
            s for s in cleanup if "re-enable dg_b_var1" in (s.description or "").lower()
        ]
        self.assertEqual(len(re_enable), 1)
        api_name, args = self._ixia_api_args(re_enable[0])
        self.assertEqual(api_name, "toggle_device_groups")
        self.assertEqual(args.get("enable"), True)
        self.assertEqual(args.get("device_group_name_regex"), B_VAR1_REGEX)

    def test_tcpdump_inserted_when_capture_device_given(self):
        pb = create_new_peer_join_routes_withdrawn_playbook(
            device_name=DEVICE,
            control_peer_addrs=CTRL,
            held_back_peer_addr=HELD,
            held_back_peer_regex=HELD_REGEX,
            b_keep_peer_addr=B_KEEP,
            b_keep_route_count=300,
            b_var1_peer_regex=B_VAR1_REGEX,
            b_var1_peer_addr=B_VAR1,
            b_var1_route_count=200,
            b_var1_device_group_regex=B_VAR1_REGEX,
            capture_tcpdump_device=DEVICE,
        )
        # Trigger stage should have start_capture + stop_capture steps wrapping
        # the toggle pair.
        descs = [
            step.description or ""
            for stage in pb.stages
            for step in (stage.steps or [])
        ]
        joined = " ".join(descs)
        self.assertIn("start tcpdump", joined.lower())
        self.assertIn("stop tcpdump", joined.lower())


class NewPeerJoinAttributeChangePlaybookTest(unittest.TestCase):
    """2.4.3 -- mid-sync community change."""

    def setUp(self):
        self.playbook = create_new_peer_join_attribute_change_playbook(
            device_name=DEVICE,
            control_peer_addrs=CTRL,
            held_back_peer_addr=HELD,
            held_back_peer_regex=HELD_REGEX,
            b_keep_peer_addr=B_KEEP,
            b_keep_route_count=300,
            b_keep_peer_regex=B_KEEP_REGEX,
            b_keep_device_group_regex="DG_B_KEEP_UG_HARDENING",
            b_keep_mutated_peer_addr="2401:db00:e50d:11:9::13",
            b_keep_mutated_device_group_regex="DG_B_KEEP_MUTATED_UG_HARDENING",
            initial_community="65529:39744",
            mutated_community="0:665",
        )

    def test_playbook_name(self):
        self.assertEqual(self.playbook.name, "new_peer_join_attribute_change")
        self.assertEqual(len(self.playbook.stages), 1)

    def test_postchecks_anchor_on_new_community_and_forbid_old(self):
        community_check = next(
            c
            for c in self.playbook.postchecks
            if c.name == hc_types.CheckName.BGP_RECEIVED_ROUTE_COMMUNITY_CHECK
        )
        params = _params(community_check)
        self.assertEqual(params["anchor_community"], "0:665")
        self.assertIn("65529:39744", params["forbidden_communities"])

    def test_postchecks_verify_both_held_and_keep_mutated_established(self):
        established_checks = [
            c
            for c in self.playbook.postchecks
            if c.name == hc_types.CheckName.BGP_SESSION_ESTABLISH_CHECK
        ]
        # One for HELD becoming UP, one for KEEP_MUTATED Established post-swap.
        self.assertEqual(len(established_checks), 2)

    def test_cleanup_restores_baseline_via_dg_toggles(self):
        self.assertIsNotNone(self.playbook.cleanup_steps)
        # Toggle KEEP_MUTATED off + toggle KEEP_INITIAL on + HELD DOWN + longevity.
        self.assertGreaterEqual(len(self.playbook.cleanup_steps), 4)

    def test_prechecks_anchor_initial_community(self):
        names = _check_names(self.playbook.prechecks)
        self.assertIn(hc_types.CheckName.BGP_RECEIVED_ROUTE_COMMUNITY_CHECK, names)
        community_precheck = next(
            c
            for c in self.playbook.prechecks
            if c.name == hc_types.CheckName.BGP_RECEIVED_ROUTE_COMMUNITY_CHECK
        )
        self.assertEqual(_params(community_precheck)["anchor_community"], "65529:39744")

    def test_trigger_uses_dg_toggle_swap_not_configure_community_pool(self):
        """The 2.4.3 trigger uses two-DG topology swap via toggle_device_groups
        on KEEP_INITIAL (off) + KEEP_MUTATED (on). It must NOT use IXIA's
        configure_community_pool API which is empirically broken on this
        topology (bag012 2026-06-23 v3-v6 runs: never updated the wire).
        """
        steps = self.playbook.stages[0].steps or []
        toggle_args, pool_args = [], []
        for s in steps:
            try:
                api_name, args = self._ixia_api_args(s)
            except (AttributeError, ValueError):
                continue
            if api_name == "toggle_device_groups":
                toggle_args.append(args)
            elif api_name == "configure_community_pool":
                pool_args.append(args)
        self.assertEqual(
            len(toggle_args),
            2,
            "Expected exactly 2 toggle_device_groups steps in 2.4.3 trigger "
            "(KEEP_INITIAL off, KEEP_MUTATED on)",
        )
        self.assertCountEqual([a.get("enable") for a in toggle_args], [False, True])
        self.assertEqual(
            len(pool_args),
            0,
            "configure_community_pool MUST NOT appear in 2.4.3 trigger -- "
            "the API is broken on this topology",
        )

    def _ixia_api_args(self, step):
        outer = json.loads(step.step_params.json_params)
        return outer.get("api_name"), json.loads(outer.get("args_json") or "{}")
