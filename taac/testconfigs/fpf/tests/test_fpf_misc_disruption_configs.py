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
  - TC38 (persistent NDP clear): disrupt-window playbook with the 120s ndp-clear
    loop (every 1s) on the observer GTSW carrying the characterized data-plane-
    impact postchecks (lane0 drained + discards spike + congestion 0), then a
    stable-state v2 longevity playbook carrying the strict stable postchecks.
"""

import json
import unittest

from taac.testconfigs.fpf.fpf_tc36_stsw_all_connections_down import (
    DISRUPT_STSW,
    DUT_GTSW,
    EXPECTED_MEMBER_INTERFACES,
    GPU_HOSTS as TC36_GPU_HOSTS,
    INTERFACE_CACHE_KEY,
    LONGEVITY_SEC as TC36_LONGEVITY_SEC,
    MEMBER_NEIGHBOR_PATTERN,
    TEST_CONFIG as TC36,
)
from taac.testconfigs.fpf.fpf_tc37_nic_side_link_flap import (
    CIRCUITS as TC37_CIRCUITS,
    LONGEVITY_SEC as TC37_LONGEVITY_SEC,
    TEST_CONFIG as TC37,
)
from taac.testconfigs.fpf.fpf_tc37b_nic_side_continuous_flap import (
    TEST_CONFIG as TC37B,
)
from taac.testconfigs.fpf.fpf_tc38_persistent_ndp_clear import (
    NDP_CLEAR_CIRCUIT,
    NDP_CLEAR_DURATION_SEC,
    NDP_CLEAR_EVERY_SEC,
    SETTLE_AFTER_CLEAR_SEC,
    TEST_CONFIG as TC38,
)
from taac.testconfigs.fpf.fpf_tc54_stsw_device_drain import (
    DRAIN_TARGET_STSW,
    GPU_HOSTS as TC54_GPU_HOSTS,
    TEST_CONFIG as TC54,
)
from taac.health_check.health_check.types import CheckName
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
# tc36-tc38 must carry. With the 8-STSW split-per-VF injection (rf_vf_groups),
# the single broad "fpf_remote_failure_stable" check is replaced by one per VF
# group, each scoped to that group's own lanes
# ("fpf_remote_failure_stable_<suffix>").
_V2_STABLE_REQUIRED_IDS = {
    "fpf_fsdb_convergence_lane0",
    "fpf_bgp_convergence_lane0",
    "fpf_hrt_convergence_lane0",
    "fpf_hrt_convergence_lane1",
    "fpf_remote_failure_stable_vf1",
    "fpf_remote_failure_stable_vf2",
    "fpf_hrt_postcheck",
}

# Remote-failure DISRUPT check IDs that a config passing ``rf_vf_groups`` produces.
# The unsuffixed "fpf_remote_failure_impacted" is minted only on the non-grouped
# branch; with rf_vf_groups the check is split per VF group. tc36 and tc37 impact
# lane 0, which fpf_rf_vf_groups() places in VF1 (lanes 0-3), so VF1 carries the
# impacted check and both groups carry an unimpacted-stable one.
_RF_DISRUPT_VF_GROUP_IDS = frozenset(
    {
        "fpf_remote_failure_impacted_vf1",
        "fpf_remote_failure_unimpacted_stable_vf1",
        "fpf_remote_failure_unimpacted_stable_vf2",
    }
)


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
        self.assertEqual(params["expected_interfaces"], EXPECTED_MEMBER_INTERFACES)
        self.assertEqual(len(params["expected_interfaces"]), 36)
        self.assertEqual(params["interface_cache_key"], INTERFACE_CACHE_KEY)
        self.assertFalse(params.get("use_cached_interfaces", False))
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
        self.assertEqual(
            _params(enable_steps[0])["expected_interfaces"],
            EXPECTED_MEMBER_INTERFACES,
        )
        self.assertTrue(_params(enable_steps[0])["use_cached_interfaces"])
        enable_index = steps.index(enable_steps[0])
        ensure_index = next(
            index
            for index, step in enumerate(steps)
            if step.name == StepName.CUSTOM_STEP
            and _params(step).get("custom_step_name") == "fpf_ensure_traffic"
        )
        self.assertLess(enable_index, ensure_index)
        self.assertTrue(
            any(
                step.name == StepName.LONGEVITY_STEP
                and _params(step)["duration"] >= 120
                for step in steps[enable_index:ensure_index]
            )
        )
        self.assertNotIn(
            "fpf_host_spray",
            _check_ids(TC36.playbooks[0]),
            "disrupt phase must not fail solely because RDMA died",
        )

        verify = next(
            _params(step)
            for step in steps
            if _params(step).get("custom_step_name") == "fpf_up_port_baseline"
        )
        self.assertEqual(verify["action"], "verify")
        self.assertEqual(
            verify["expected_interfaces_by_device"],
            {DUT_GTSW: EXPECTED_MEMBER_INTERFACES},
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
        missing_rf = _RF_DISRUPT_VF_GROUP_IDS - ids
        self.assertFalse(
            missing_rf, f"disrupt missing remote-failure check IDs: {missing_rf}"
        )
        # Prod-prefix transition (reachable->unreachable on impacted plane).
        self.assertIn("fpf_prod_hrt_prefix_transition", ids)
        # flip_fsdb_session=False -> sessions stay CONNECTED (the "stable"
        # session check), NOT the per-GPU reconciliation "disrupt" check.
        self.assertIn("fpf_hrt_fsdb_session_stable", ids)
        self.assertNotIn("fpf_hrt_fsdb_session_disrupt", ids)
        # flip_discards=False -> NO failing in_discard loss assertion.
        self.assertNotIn("ods_in_discard_loss_expected", ids)
        # All uplinks on lane 0 are intentionally unavailable, so GTSW-side
        # RIB checks must not incorrectly require 4032 there. The untouched
        # observer lane remains strict and the restore playbook checks both.
        self.assertNotIn("fpf_fsdb_convergence_lane0", ids)
        self.assertNotIn("fpf_bgp_convergence_lane0", ids)
        self.assertIn("fpf_fsdb_convergence_lane1", ids)
        self.assertIn("fpf_bgp_convergence_lane1", ids)
        # ods_discard_informational=True -> transient baseline excess is
        # informational for the two DISCARD checks, but final recovery and both
        # CONGESTION checks remain hard.
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
        self.assertEqual(in_dst_null.get("baseline_excess_max"), 10000)
        self.assertEqual(in_discard.get("baseline_excess_max"), 10000)
        self.assertIs(in_dst_null.get("transient_excess_informational"), True)
        self.assertIs(in_discard.get("transient_excess_informational"), True)
        self.assertFalse(in_dst_null.get("informational", False))
        self.assertFalse(in_discard.get("informational", False))
        # Congestion checks stay hard: informational is False (or absent).
        self.assertFalse(in_congestion.get("informational", False))
        self.assertFalse(out_congestion.get("informational", False))

        prod_transition = json.loads(
            by_id["fpf_prod_hrt_prefix_transition"].check_params.json_params
        )
        self.assertEqual(
            prod_transition["impacted_planes_by_host"],
            {TC36_GPU_HOSTS[1]: [0]},
        )
        unaffected = json.loads(
            by_id["fpf_prod_hrt_prefix_unaffected_stability"].check_params.json_params
        )
        self.assertEqual(
            set(unaffected["prefixes_by_host"]),
            {TC36_GPU_HOSTS[0]},
        )

        prod_precheck = next(
            check
            for check in TC36.playbooks[0].prechecks or []
            if check.check_id == "fpf_prod_hrt_prefix_stability_precheck"
        )
        prod_precheck_params = json.loads(prod_precheck.check_params.json_params)
        self.assertFalse(prod_precheck_params["use_test_case_start_time"])
        self.assertEqual(prod_precheck_params["lookback_sec"], 120)
        self.assertEqual(
            set(prod_precheck_params["prefixes_by_host"]),
            {TC36_GPU_HOSTS[1]},
        )

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
        self.assertEqual(
            set(params["expected_interfaces"]), set(EXPECTED_MEMBER_INTERFACES)
        )
        self.assertEqual(len(params["expected_interfaces"]), 36)
        self.assertEqual(params["interface_cache_key"], INTERFACE_CACHE_KEY)
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
        by_id = {c.check_id: c for c in TC36.playbooks[1].postchecks or []}
        bgp_lane1 = json.loads(
            by_id["fpf_bgp_convergence_lane1"].check_params.json_params
        )
        self.assertEqual(bgp_lane1["stability_mode"], "skip_null_strict")
        self.assertTrue(bgp_lane1["require_final_exact"])
        prod_recovery = json.loads(
            by_id["fpf_prod_hrt_prefix_recovery"].check_params.json_params
        )
        self.assertEqual(
            prod_recovery["impacted_planes_by_host"],
            {TC36_GPU_HOSTS[1]: [0]},
        )
        self.assertEqual(
            set(prod_recovery["prefixes_by_host"]),
            {TC36_GPU_HOSTS[1]},
        )
        unaffected = json.loads(
            by_id["fpf_prod_hrt_prefix_unaffected_stability"].check_params.json_params
        )
        self.assertEqual(
            set(unaffected["prefixes_by_host"]),
            {TC36_GPU_HOSTS[0]},
        )


class TestTc37NicSideLinkFlap(unittest.TestCase):
    def test_name_tags_and_two_playbook_shape(self):
        self.assertEqual(TC37.name, "fpf_tc37_nic_side_link_flap")
        self.assertIn("fpf", TC37.tags or [])
        self.assertEqual(len(TC37.playbooks), 2)
        self.assertEqual(TC37.playbooks[0].name, "fpf_tc37_nic_side_link_flap_disrupt")
        self.assertEqual(TC37.playbooks[1].name, "fpf_tc37_nic_side_link_flap_restore")

    def test_single_flap_holds_down_until_explicit_restore(self):
        disrupt_steps = _steps(TC37.playbooks[0])
        restore_steps = _steps(TC37.playbooks[1])

        down = [
            _params(step)
            for step in disrupt_steps
            if _params(step).get("custom_step_name") == "fpf_nic_mstreg_paos"
        ]
        up = [
            _params(step)
            for step in restore_steps
            if _params(step).get("custom_step_name") == "fpf_nic_mstreg_paos"
        ]
        self.assertEqual(len(down), 1)
        self.assertEqual(len(up), 1)
        target = TC37_CIRCUITS[0]
        self.assertEqual(
            (down[0]["host"], down[0]["dev"], down[0]["lane"]),
            (target.z_end_device, target.z_end_gpu_id, target.lane),
        )
        self.assertFalse(down[0]["admin_up"])
        self.assertTrue(up[0]["admin_up"])
        self.assertTrue(up[0]["verify_link_health"])
        self.assertFalse(
            any(
                _params(step).get("custom_step_name") == "fpf_nic_mstreg_flap"
                for step in disrupt_steps
            )
        )

        # The old thrift-admin disable placeholder is GONE.
        admin_steps = [
            s
            for s in disrupt_steps
            if s.name == StepName.CUSTOM_STEP
            and _params(s).get("custom_step_name") == "fpf_set_interface_admin"
        ]
        self.assertEqual(admin_steps, [])

        # The link-event disrupt playbook prepends its own stabilization
        # longevity before the config's settle, so assert the config's settle
        # window is PRESENT among the longevity steps rather than by position.
        longevity_durations = [
            _params(s)["duration"]
            for s in disrupt_steps
            if s.name == StepName.LONGEVITY_STEP
        ]
        self.assertIn(TC37_LONGEVITY_SEC, longevity_durations)

    def test_hard_link_down_contract(self):
        """tc37 mirrors the GTSW interface-disable: FSDB session flips and a
        failing in_discard loss assertion is present (real packet loss)."""
        ids = _check_ids(TC37.playbooks[0])
        self.assertIn("fpf_hrt_bulk_disrupt", ids)
        missing_rf = _RF_DISRUPT_VF_GROUP_IDS - ids
        self.assertFalse(
            missing_rf, f"disrupt missing remote-failure check IDs: {missing_rf}"
        )
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


class TestTc37bNicSideContinuousFlap(unittest.TestCase):
    def test_continuous_config_shape_and_scope(self):
        config = TC37B
        self.assertEqual(config.name, "fpf_tc37b_nic_side_continuous_flap")
        self.assertEqual(
            [playbook.name for playbook in config.playbooks],
            [
                "fpf_tc37b_nic_side_continuous_flap_disrupt",
                "fpf_tc37b_nic_side_continuous_flap_longevity",
            ],
        )

        disrupt_steps = _steps(config.playbooks[0])
        flap = next(
            _params(step)
            for step in disrupt_steps
            if _params(step).get("custom_step_name") == "fpf_nic_mstreg_flap"
        )
        target = TC37_CIRCUITS[0]
        self.assertEqual(
            (flap["host"], flap["dev"], flap["lane"]),
            (target.z_end_device, target.z_end_gpu_id, target.lane),
        )
        self.assertEqual(flap["duration_sec"], 900)
        self.assertEqual(flap["down_time_sec"], 2.0)
        self.assertEqual(flap["up_time_sec"], 2.0)
        self.assertEqual(flap["final_cleanup_timeout_sec"], 120.0)

    def test_continuous_disrupt_is_diagnostic_and_longevity_is_strict(self):
        config = TC37B
        disrupt, longevity = config.playbooks
        disrupt_names = {check.name for check in disrupt.postchecks or []}
        self.assertIn(CheckName.SYSTEMCTL_ACTIVE_STATE_CHECK, disrupt_names)
        self.assertIn(CheckName.UNCLEAN_EXIT_CHECK, disrupt_names)
        self.assertIn(CheckName.DEVICE_CORE_DUMPS_CHECK, disrupt_names)
        self.assertNotIn(CheckName.FPF_HOST_SPRAY_CHECK, disrupt_names)
        disrupt_bgp = [
            check
            for check in disrupt.postchecks or []
            if check.name == CheckName.FPF_BGP_RIB_CONVERGENCE_CHECK
        ]
        self.assertTrue(disrupt_bgp)
        self.assertTrue(
            all(
                json.loads(check.check_params.json_params)["informational"]
                for check in disrupt_bgp
            )
        )

        longevity_ids = _check_ids(longevity)
        self.assertFalse(
            _V2_STABLE_REQUIRED_IDS - longevity_ids,
            "continuous-flap longevity must carry the complete strict state",
        )
        longevity_steps = [_params(step) for step in _steps(longevity)]
        names = [params.get("custom_step_name") for params in longevity_steps]
        self.assertIn("fpf_ensure_traffic", names)
        anchor = names.index("record_fpf_recovered_baseline_time")
        self.assertEqual(longevity_steps[anchor + 1]["duration"], 120)
        self.assertEqual(longevity_steps[anchor + 2]["duration"], 300)
        self.assertIn("fpf_nic_mstreg_verify_link", names)
        self.assertIn("fpf_up_port_baseline", names)

        bgp_checks = [
            check
            for check in longevity.postchecks or []
            if check.name == CheckName.FPF_BGP_RIB_CONVERGENCE_CHECK
        ]
        self.assertTrue(bgp_checks)
        for check in bgp_checks:
            params = json.loads(check.check_params.json_params)
            self.assertEqual(params.get("stability_mode", "strict"), "strict")
            self.assertTrue(params["require_final_exact"])


class TestTc38PersistentNdpClear(unittest.TestCase):
    def test_name_tags_and_two_playbook_shape(self):
        self.assertEqual(TC38.name, "fpf_tc38_persistent_ndp_clear")
        self.assertIn("fpf", TC38.tags or [])
        self.assertEqual(len(TC38.playbooks), 2)
        self.assertEqual(
            TC38.playbooks[0].name, "fpf_tc38_persistent_ndp_clear_disrupt"
        )
        self.assertEqual(TC38.playbooks[1].name, "fpf_tc38_persistent_ndp_clear_stable")

    def test_disrupt_playbook_characterized_checks(self):
        # First playbook now carries the CHARACTERIZED data-plane-impact
        # postchecks (lane0 drains + discards spike + congestion stays 0), not
        # "no checks". The strict stable-state HRT/prefix contract still lives in
        # the second (stable) playbook.
        disrupt_ids = _check_ids(TC38.playbooks[0])
        # ODS discard/congestion checks are always present (not SSH-gated).
        self.assertIn("ndp_clear_ods_in_dst_null", disrupt_ids)
        self.assertIn("ndp_clear_ods_in_discard", disrupt_ids)
        self.assertIn("ndp_clear_ods_in_congestion", disrupt_ids)
        self.assertIn("ndp_clear_ods_out_congestion", disrupt_ids)
        # Second (stable) playbook carries the stable-state checks.
        self.assertTrue(TC38.playbooks[1].postchecks)

    def test_ndp_clear_loop_120s_then_settle(self):
        steps = _steps(TC38.playbooks[0])
        # record-disruption-time -> ndp-clear loop -> settle longevity.
        self.assertEqual(len(steps), 4)
        # Locate the ndp-clear loop step (robust to step ordering).
        loop = next(
            s
            for s in steps
            if s.name == StepName.CUSTOM_STEP
            and _params(s).get("custom_step_name") == "fpf_ndp_clear_loop"
        )
        loop_params = _params(loop)
        self.assertEqual(loop_params["every_sec"], NDP_CLEAR_EVERY_SEC)
        self.assertEqual(loop_params["duration_sec"], NDP_CLEAR_DURATION_SEC)
        self.assertEqual(
            loop_params["target_interface"], NDP_CLEAR_CIRCUIT.a_end_interface
        )
        self.assertEqual(loop_params["neighbor_host"], NDP_CLEAR_CIRCUIT.z_end_device)
        self.assertEqual(NDP_CLEAR_DURATION_SEC, 120)
        # Capacity-calibrated persistent trigger: 30 exact slots over 120s.
        self.assertEqual(NDP_CLEAR_EVERY_SEC, 4)
        self.assertEqual(NDP_CLEAR_DURATION_SEC // NDP_CLEAR_EVERY_SEC, 30)
        # Scoped to the observer GTSW.
        from taac.testconfigs.fpf.fpf_hardening_common import (
            OBSERVER_GTSWS,
        )

        self.assertEqual(list(loop.device_regexes or []), [OBSERVER_GTSWS[0]])

        # Settle longevity is the final step.
        settle = steps[-1]
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

        historical_ids = {
            "fpf_prod_hrt_prefix_stability_precheck",
            "fpf_hrt_system_memory_precheck",
            "fpf_hrt_driver_disconnect_precheck",
        }
        precheck_ids = {
            check.check_id
            for check in (TC38.playbooks[1].prechecks or [])
            if check.check_id
        }
        self.assertTrue(historical_ids.isdisjoint(precheck_ids))

        stable_steps = _steps(TC38.playbooks[1])
        custom_names = [
            _params(step).get("custom_step_name")
            for step in stable_steps
            if step.name == StepName.CUSTOM_STEP
        ]
        self.assertIn("fpf_verify_recovered_state", custom_names)
        self.assertIn("record_fpf_recovered_baseline_time", custom_names)
        self.assertLess(
            custom_names.index("fpf_verify_recovered_state"),
            custom_names.index("record_fpf_recovered_baseline_time"),
        )
        durations = [
            _params(step)["duration"]
            for step in stable_steps
            if step.name == StepName.LONGEVITY_STEP
        ]
        self.assertEqual(durations, [120, 300])


class TestTc54StswDeviceDrain(unittest.TestCase):
    def test_drain_is_fail_closed_grouped_and_checked_in_same_playbook(self):
        self.assertEqual(len(TC54.playbooks), 1)
        playbook = TC54.playbooks[0]
        self.assertEqual(playbook.name, "fpf_tc54_stsw_device_drain_disrupt")
        steps = _steps(playbook)
        custom = [_params(step) for step in steps if step.name == StepName.CUSTOM_STEP]
        drain = next(
            params
            for params in custom
            if params.get("custom_step_name") == "fpf_drain_interface"
        )
        self.assertTrue(drain["is_drain"])
        self.assertEqual(drain["target_device"], DRAIN_TARGET_STSW)
        gate = next(
            params
            for params in custom
            if params.get("custom_step_name") == "fpf_verify_disruption"
        )
        self.assertTrue(gate["expect_drained"])
        self.assertTrue(gate["fail_if_ineffective"])
        injections = [
            _params(step)
            for step in steps
            if step.name == StepName.FPF_BGP_PREFIX_INJECTION_STEP
        ]
        self.assertEqual(len(injections), 2)
        self.assertEqual(
            {params["prefix_base"] for params in injections},
            {"5000:dd::/64", "5000:ee::/64"},
        )
        self.assertTrue(
            all(params["extra_communities"] == ["65446:10"] for params in injections)
        )
        self.assertTrue(
            any(
                step.name == StepName.LONGEVITY_STEP
                and _params(step)["duration"] >= 300
                for step in steps
            )
        )
        ids = _check_ids(playbook)
        self.assertIn("fpf_host_spray", ids)
        self.assertNotIn("fpf_hrt_plane_status_drain", ids)
        self.assertIn("fpf_hrt_plane_status_stsw_control_up", ids)
        plane_check = next(
            check
            for check in playbook.postchecks or []
            if check.check_id == "fpf_hrt_plane_status_stsw_control_up"
        )
        self.assertEqual(
            json.loads(plane_check.check_params.json_params)["mode"], "all_up"
        )

        # An STSW route drain does not drain the host-to-GTSW FSDB transport.
        # Keep sessions and every other product signal strict: only the old
        # plane-status=DRAINED expectation is corrected.
        self.assertIn("fpf_hrt_postcheck", ids)
        self.assertIn("fpf_remote_failure_stable_vf1", ids)
        self.assertIn("fpf_remote_failure_stable_vf2", ids)
        self.assertIn("fpf_prod_hrt_prefix_stability", ids)
        spray_check = next(
            check
            for check in playbook.postchecks or []
            if check.check_id == "fpf_host_spray"
        )
        spray_params = json.loads(spray_check.check_params.json_params)
        self.assertEqual(
            spray_params["impacted_lanes_by_host"],
            {host: ["beth0"] for host in TC54_GPU_HOSTS},
        )
        self.assertEqual(spray_params["impacted_max_gbps"], 10.0)


if __name__ == "__main__":
    unittest.main()
