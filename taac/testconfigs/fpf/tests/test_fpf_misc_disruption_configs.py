# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe
"""Unit tests for the FPF misc-disruption test configs (TC36-TC38).

These configs build at import time with no device access, so the tests assert
the static TestConfig structure:

  - TC36 (all STSW connections down): two-playbook (disrupt + restore) shape,
    a SINGLE batched thrift admin-disable over the whole STSW->gtsw001 member
    set, and the discard-informational / session-stable HC contract (the
    impacted lane shows up in the REMOTE-FAILURE collector and is WITHDRAWN
    from the bulk/prod collector, no failing in_discard loss assertion).
  - TC37 (NIC-side link flap): two-playbook shape, NIC-side admin flap over the
    impacted beth lane(s), and the hard-link-down HC contract (FSDB session
    flips, in_discard loss expected) like the GTSW interface-disable test.
  - TC38 (persistent NDP clear): disruption-only playbook with the 120s
    ndp-clear loop (every 1s) on the observer GTSW, then a stable-state v2
    longevity playbook carrying the (provisional, stable) postchecks.
"""

import json
import unittest

from taac.testconfigs.fpf.fpf_tc36_stsw_all_connections_down import (
    DISRUPT_STSW,
    DUT_GTSW,
    LONGEVITY_SEC as TC36_LONGEVITY_SEC,
    MEMBER_NEIGHBOR_PATTERN,
    TEST_CONFIG as TC36,
)
from taac.testconfigs.fpf.fpf_tc37_nic_side_link_flap import (
    LONGEVITY_SEC as TC37_LONGEVITY_SEC,
    TEST_CONFIG as TC37,
)
from taac.testconfigs.fpf.fpf_tc38_persistent_ndp_clear import (
    NDP_CLEAR_DURATION_SEC,
    NDP_CLEAR_EVERY_SEC,
    SETTLE_AFTER_CLEAR_SEC,
    TEST_CONFIG as TC38,
)
from taac.test_as_a_config.types import StepName


def _steps(playbook):
    """Flatten the sequential steps out of a playbook's stages."""
    out = []
    for stage in playbook.stages:
        out.extend(stage.steps or [])
    return out


def _params(step) -> dict:
    return json.loads(step.step_params.json_params)


def _check_ids(playbook) -> set:
    return {c.check_id for c in (playbook.postchecks or []) if c.check_id}


def _disrupt_playbook_has_no_checks(tc, test):
    disrupt = tc.playbooks[0]
    test.assertEqual(list(disrupt.prechecks or []), [])
    test.assertEqual(list(disrupt.postchecks or []), [])
    test.assertEqual(list(disrupt.snapshot_checks or []), [])


# Stable-state v2 hardening check IDs that the restore/stable playbooks of
# tc36-tc38 must carry.
_V2_STABLE_REQUIRED_IDS = {
    "fpf_fsdb_convergence_lane0",
    "fpf_bgp_convergence_lane0",
    "fpf_hrt_convergence_lane0",
    "fpf_hrt_convergence_lane1",
    "fpf_remote_failure_stable",
    "fpf_hrt_postcheck",
}


class TestTc36StswAllConnectionsDown(unittest.TestCase):
    def test_name_tags_and_two_playbook_shape(self):
        self.assertEqual(TC36.name, "fpf_tc36_stsw_all_connections_down")
        self.assertIn("fpf", TC36.tags or [])
        self.assertEqual(len(TC36.playbooks), 2)
        self.assertEqual(
            TC36.playbooks[0].name, "fpf_tc36_stsw_all_connections_down_disrupt"
        )
        self.assertEqual(
            TC36.playbooks[1].name, "fpf_tc36_stsw_all_connections_down_restore"
        )
        # The disrupt playbook DOES carry the disrupted-contract postchecks
        # (it is a link-event disrupt playbook, not a bare disruption-only one).
        self.assertTrue(TC36.playbooks[0].postchecks)
        self.assertTrue(TC36.playbooks[1].postchecks)

    def test_single_batched_member_disable_step(self):
        steps = _steps(TC36.playbooks[0])
        custom_steps = [s for s in steps if s.name == StepName.CUSTOM_STEP]
        # LLDP-resolved batched-disable variant (no static member list).
        disable_steps = [
            s
            for s in custom_steps
            if _params(s).get("custom_step_name")
            == "fpf_lldp_batched_set_interface_admin"
            and _params(s).get("is_enable") is False
        ]
        # Exactly ONE batched LLDP-disable step -> "all connections down at once".
        self.assertEqual(len(disable_steps), 1)
        params = _params(disable_steps[0])
        # The step carries a PATTERN, not a static interface list — the
        # member set is resolved at run time on the GTSW from LLDP. The query
        # is GTSW-side now: on gtsw001, resolve uplinks facing stsw001.s001.
        self.assertEqual(params["neighbor_pattern"], MEMBER_NEIGHBOR_PATTERN)
        self.assertEqual(MEMBER_NEIGHBOR_PATTERN, "stsw001.s001*")
        self.assertNotIn("interfaces", params)
        # Scoped to DUT_GTSW (gtsw001) so the LLDP query/disable runs there.
        self.assertEqual(DUT_GTSW, "gtsw001.l1002.c087.mwg2")
        self.assertEqual(list(disable_steps[0].device_regexes or []), [DUT_GTSW])

        # The link-event disrupt playbook prepends its own stabilization
        # longevity (stabilization_delay_sec) before the config's disruption
        # steps, so assert the config's settle window is PRESENT among the
        # longevity steps rather than assuming a position.
        longevity_durations = [
            _params(s)["duration"] for s in steps if s.name == StepName.LONGEVITY_STEP
        ]
        self.assertIn(TC36_LONGEVITY_SEC, longevity_durations)

    def test_restore_reenables_whole_member_set(self):
        steps = _steps(TC36.playbooks[1])
        enable_steps = [
            s
            for s in steps
            if s.name == StepName.CUSTOM_STEP
            and _params(s).get("custom_step_name")
            == "fpf_lldp_batched_set_interface_admin"
            and _params(s).get("is_enable") is True
        ]
        self.assertEqual(len(enable_steps), 1)
        self.assertEqual(
            _params(enable_steps[0])["neighbor_pattern"], MEMBER_NEIGHBOR_PATTERN
        )

    def test_disrupt_stsw_is_plane1_trigger(self):
        self.assertEqual(DISRUPT_STSW, "stsw001.s001.l202.mwg2")

    def test_impacted_lane_in_remote_failure_not_bulk_or_loss(self):
        """tc36 HC contract: impacted lane surfaces in the REMOTE-FAILURE
        collector and is WITHDRAWN from the bulk/prod collector of that lane,
        sessions stay CONNECTED, and there is NO failing in_discard loss
        assertion (discards are informational)."""
        ids = _check_ids(TC36.playbooks[0])
        # Impacted lane is withdrawn from bulk and rises in remote-failure.
        self.assertIn("fpf_hrt_bulk_disrupt", ids)
        self.assertIn("fpf_remote_failure_impacted", ids)
        # Prod-prefix transition (reachable->unreachable on impacted plane).
        self.assertIn("fpf_prod_hrt_prefix_transition", ids)
        # flip_fsdb_session=False -> sessions stay CONNECTED (the "stable"
        # session check), NOT the per-GPU reconciliation "disrupt" check.
        self.assertIn("fpf_hrt_fsdb_session_stable", ids)
        self.assertNotIn("fpf_hrt_fsdb_session_disrupt", ids)
        # flip_discards=False -> NO failing in_discard loss assertion.
        self.assertNotIn("ods_in_discard_loss_expected", ids)
        # ods_discard_informational=True -> the two DISCARD checks are added
        # with informational=True (breach -> [INFORMATIONAL] PASS), and the
        # two CONGESTION checks are added without informational (hard).
        self.assertIn("ods_in_dst_null_discard", ids)
        self.assertIn("ods_in_discard", ids)
        self.assertIn("ods_in_congestion", ids)
        self.assertIn("ods_out_congestion", ids)
        by_id = {c.check_id: c for c in TC36.playbooks[0].postchecks or []}
        in_dst_null = json.loads(
            by_id["ods_in_dst_null_discard"].check_params.json_params
        )
        in_discard = json.loads(by_id["ods_in_discard"].check_params.json_params)
        in_congestion = json.loads(by_id["ods_in_congestion"].check_params.json_params)
        out_congestion = json.loads(
            by_id["ods_out_congestion"].check_params.json_params
        )
        self.assertIs(in_dst_null.get("informational"), True)
        self.assertIs(in_discard.get("informational"), True)
        # Congestion checks stay hard: informational is False (or absent).
        self.assertFalse(in_congestion.get("informational", False))
        self.assertFalse(out_congestion.get("informational", False))

    def test_disrupt_lldp_step_carries_correct_params(self):
        """tc36 disrupt step: single LLDP-resolved batched disable scoped to
        gtsw001 with the per-plane neighbor pattern."""
        steps = _steps(TC36.playbooks[0])
        disable_steps = [
            s
            for s in steps
            if s.name == StepName.CUSTOM_STEP
            and _params(s).get("custom_step_name")
            == "fpf_lldp_batched_set_interface_admin"
            and _params(s).get("is_enable") is False
        ]
        self.assertEqual(len(disable_steps), 1)
        params = _params(disable_steps[0])
        self.assertEqual(params["neighbor_pattern"], "stsw001.s001*")
        # Member set is LLDP-resolved at runtime — no static interfaces list.
        self.assertNotIn("interfaces", params)
        # The step is scoped to the DUT GTSW only.
        self.assertEqual(list(disable_steps[0].device_regexes or []), [DUT_GTSW])

    def test_restore_playbook_carries_v2_stable_check_set(self):
        """The restore (Playbook 2) v2 hardening playbook anchors at its own
        start and carries the stable-state hardening check set."""
        ids = {c.check_id for c in (TC36.playbooks[1].postchecks or []) if c.check_id}
        missing = _V2_STABLE_REQUIRED_IDS - ids
        self.assertFalse(missing, f"restore missing stable check IDs: {missing}")
        # plane_status_check=True + prod_prefix_recovery=True in tc36 restore.
        self.assertIn("fpf_hrt_plane_status_all_up", ids)
        self.assertIn("fpf_prod_hrt_prefix_recovery", ids)


class TestTc37NicSideLinkFlap(unittest.TestCase):
    def test_name_tags_and_two_playbook_shape(self):
        self.assertEqual(TC37.name, "fpf_tc37_nic_side_link_flap")
        self.assertIn("fpf", TC37.tags or [])
        self.assertEqual(len(TC37.playbooks), 2)
        self.assertEqual(TC37.playbooks[0].name, "fpf_tc37_nic_side_link_flap_disrupt")
        self.assertEqual(TC37.playbooks[1].name, "fpf_tc37_nic_side_link_flap_restore")

    def test_nic_side_flap_over_impacted_beth(self):
        steps = _steps(TC37.playbooks[0])
        # tc37 now drives a REAL mstreg PAOS flap (no longer the thrift-admin
        # placeholder). One ``fpf_nic_mstreg_flap`` step on host rtptest, dev=0
        # / lane=1 (BDF 0000:03:00.1) with the configured iteration/interval
        # defaults. The BDF is computed deterministically by the handler — the
        # config only carries host/dev/lane.
        flap_steps = [
            s
            for s in steps
            if s.name == StepName.CUSTOM_STEP
            and _params(s).get("custom_step_name") == "fpf_nic_mstreg_flap"
        ]
        self.assertEqual(len(flap_steps), 1)
        p = _params(flap_steps[0])
        self.assertEqual(p["dev"], 0)
        self.assertEqual(p["lane"], 1)
        self.assertTrue(p["host"].startswith("rtptest"))
        # Defaults wired from the test config.
        self.assertEqual(p["iterations"], 5)
        self.assertEqual(p["interval_sec"], 2.0)

        # The old thrift-admin disable placeholder is GONE.
        admin_steps = [
            s
            for s in steps
            if s.name == StepName.CUSTOM_STEP
            and _params(s).get("custom_step_name") == "fpf_set_interface_admin"
        ]
        self.assertEqual(admin_steps, [])

        # The link-event disrupt playbook prepends its own stabilization
        # longevity before the config's settle, so assert the config's settle
        # window is PRESENT among the longevity steps rather than by position.
        longevity_durations = [
            _params(s)["duration"] for s in steps if s.name == StepName.LONGEVITY_STEP
        ]
        self.assertIn(TC37_LONGEVITY_SEC, longevity_durations)

    def test_hard_link_down_contract(self):
        """tc37 mirrors the GTSW interface-disable: FSDB session flips and a
        failing in_discard loss assertion is present (real packet loss)."""
        ids = _check_ids(TC37.playbooks[0])
        self.assertIn("fpf_hrt_bulk_disrupt", ids)
        self.assertIn("fpf_remote_failure_impacted", ids)
        # flip_fsdb_session=True -> per-GPU reconciliation session check.
        self.assertIn("fpf_hrt_fsdb_session_disrupt", ids)
        self.assertNotIn("fpf_hrt_fsdb_session_stable", ids)
        # flip_discards=True -> real loss assertion present.
        self.assertIn("ods_in_discard_loss_expected", ids)

    def test_loss_expected_check_is_hard_max_any(self):
        """tc37 flip_discards=True path: the loss-expected peak check is hard
        (not informational) and aggregates max/any."""
        by_id = {
            c.check_id: c for c in (TC37.playbooks[0].postchecks or []) if c.check_id
        }
        loss = json.loads(
            by_id["ods_in_discard_loss_expected"].check_params.json_params
        )
        self.assertFalse(loss.get("informational", False))
        self.assertEqual(loss.get("aggregate"), "max")
        self.assertEqual(loss.get("require"), "any")

    def test_restore_playbook_carries_v2_stable_check_set(self):
        ids = {c.check_id for c in (TC37.playbooks[1].postchecks or []) if c.check_id}
        missing = _V2_STABLE_REQUIRED_IDS - ids
        self.assertFalse(missing, f"restore missing stable check IDs: {missing}")
        # tc37 restore is plane_status + recovery (same as tc36).
        self.assertIn("fpf_hrt_plane_status_all_up", ids)
        self.assertIn("fpf_prod_hrt_prefix_recovery", ids)


class TestTc38PersistentNdpClear(unittest.TestCase):
    def test_name_tags_and_two_playbook_shape(self):
        self.assertEqual(TC38.name, "fpf_tc38_persistent_ndp_clear")
        self.assertIn("fpf", TC38.tags or [])
        self.assertEqual(len(TC38.playbooks), 2)
        self.assertEqual(
            TC38.playbooks[0].name, "fpf_tc38_persistent_ndp_clear_disrupt"
        )
        self.assertEqual(TC38.playbooks[1].name, "fpf_tc38_persistent_ndp_clear_stable")

    def test_disruption_only_first_playbook(self):
        # First playbook is disruption-only: no checks at all.
        _disrupt_playbook_has_no_checks(TC38, self)
        # Second (stable) playbook carries the provisional stable-state checks.
        self.assertTrue(TC38.playbooks[1].postchecks)

    def test_ndp_clear_loop_120s_then_settle(self):
        steps = _steps(TC38.playbooks[0])
        # ndp-clear loop -> settle longevity.
        self.assertEqual(len(steps), 2)
        loop = steps[0]
        self.assertEqual(loop.name, StepName.CUSTOM_STEP)
        loop_params = _params(loop)
        self.assertEqual(loop_params["custom_step_name"], "fpf_ndp_clear_loop")
        self.assertEqual(loop_params["every_sec"], NDP_CLEAR_EVERY_SEC)
        self.assertEqual(loop_params["duration_sec"], NDP_CLEAR_DURATION_SEC)
        self.assertEqual(NDP_CLEAR_DURATION_SEC, 120)
        # Per the config docstring, every_sec is 1 (rapid clear).
        self.assertEqual(NDP_CLEAR_EVERY_SEC, 1)
        # Scoped to the observer GTSW.
        from taac.testconfigs.fpf.fpf_hardening_common import (
            OBSERVER_GTSWS,
        )

        self.assertEqual(list(loop.device_regexes or []), [OBSERVER_GTSWS[0]])

        settle = steps[1]
        self.assertEqual(settle.name, StepName.LONGEVITY_STEP)
        self.assertEqual(_params(settle)["duration"], SETTLE_AFTER_CLEAR_SEC)

    def test_stable_playbook_carries_v2_stable_check_set(self):
        """tc38 Playbook 2 (PROVISIONAL stable-state v2 longevity) must carry
        the full stable-state check set, anchored at its own start."""
        ids = {c.check_id for c in (TC38.playbooks[1].postchecks or []) if c.check_id}
        missing = _V2_STABLE_REQUIRED_IDS - ids
        self.assertFalse(missing, f"stable missing check IDs: {missing}")
        # PROVISIONAL: the stable-state contract is used while the NDP-clear
        # behavior is being characterized — no disruption-mode HCs.
        self.assertNotIn("fpf_hrt_bulk_disrupt", ids)
        self.assertNotIn("fpf_hrt_fsdb_session_disrupt", ids)


if __name__ == "__main__":
    unittest.main()
