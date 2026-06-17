# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""Structural + HC-expectation unit tests for the FPF FSDB disruption test configs.

These tests import each config module and assert both:
  (a) the static TestConfig shape: two-playbook ordering, the HRT session-stat
      check mode + expected_connected(_during), the host-spray ``all_samples``
      flag on tc29, FSDB service / trigger used by each step;
  (b) the per-config HEALTH-CHECK EXPECTATIONS extracted from the config's
      playbooks: each longevity playbook (v2) carries the full stable-state
      hardening check set, and the session-stat check (pulled BY check_id from
      the config) PASSes/FAILs under mocked-collector data shaped to the
      documented disruption (32 -> 28 on lane 0 + recovery, etc.).

Mocked-collector simulations follow the pattern in
``test_fpf_hrt_session_stat_health_check.py``: ``get_collector`` is patched to a
synthetic collector whose ``evaluate_window`` / ``evaluate_recovery_hold`` /
``timeout_count_in_window`` / ``format_window_table`` return canned values, so
correctness is proven without devices.
"""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from taac.constants import TestDevice
from taac.health_checks.device_health_checks.fpf_hrt_session_stat_health_check import (
    FpfHrtSessionStatHealthCheck,
)
from taac.libs.fpf.fpf_stress_checks import (
    FsdbSessionWindowResult,
)
from taac.testconfigs.fpf import (
    fpf_tc28_fsdb_kill,
    fpf_tc29_fsdb_gr_stop30_reenable,
    fpf_tc30_fsdb_gr_stop180_no_reenable,
    fpf_tc31_fsdb_enable_recover,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types

_HC_MODULE = (
    "neteng.test_infra.dne.taac.health_checks.device_health_checks"
    ".fpf_hrt_session_stat_health_check"
)
_GPU_HOST = "rtptest1555.mwg2"


def _all_postchecks(playbook):
    return list(playbook.postchecks or [])


def _session_stat_checks(playbook):
    return [
        pc
        for pc in _all_postchecks(playbook)
        if pc.name == hc_types.CheckName.FPF_HRT_SESSION_STAT_CHECK
    ]


def _host_spray_checks(playbook):
    return [
        pc
        for pc in _all_postchecks(playbook)
        if pc.name == hc_types.CheckName.FPF_HOST_SPRAY_CHECK
    ]


def _check_params(check) -> dict:
    return json.loads(check.check_params.json_params)


def _all_steps(playbook):
    steps = []
    for stage in playbook.stages or []:
        steps.extend(stage.steps or [])
    return steps


def _step_names(playbook):
    return [s.name for s in _all_steps(playbook)]


def _checks_by_id(playbook) -> dict:
    return {c.check_id: c for c in (playbook.postchecks or []) if c.check_id}


def _make_session_collector(
    window_result: FsdbSessionWindowResult,
    recovery=(True, 90.0, "recovered to 32 and held for 90.0s (>= floor)"),
    timeout_count: int = 0,
) -> MagicMock:
    """Build a synthetic HRT FSDB-session collector for the session-stat HC."""
    collector = MagicMock()
    collector.host = _GPU_HOST
    collector.evaluate_window.return_value = window_result
    collector.evaluate_recovery_hold.return_value = recovery
    collector.timeout_count_in_window.return_value = timeout_count
    collector.format_window_table.return_value = "(table)"
    return collector


# Stable-state hardening v2 check IDs that EVERY tc28-31 longevity playbook
# must carry (anchored at the longevity playbook start by the runner's
# per-playbook re-stamp of test_case_start_time).
_V2_STABLE_REQUIRED_IDS = {
    # FSDB ribMap + BGP RIB convergence (one per observed lane).
    "fpf_fsdb_convergence_lane0",
    "fpf_bgp_convergence_lane0",
    # HRT bulk convergence on the injected lane(s).
    "fpf_hrt_convergence_lane0",
    "fpf_hrt_convergence_lane1",
    # Steady-state remote-failure.
    "fpf_remote_failure_stable",
    # Prod-prefix stability and per-host FSDB-session postcheck.
    "fpf_prod_hrt_prefix_stability",
    "fpf_hrt_postcheck",
}


class TestFpfTc28FsdbKill(unittest.TestCase):
    def setUp(self):
        self.cfg = fpf_tc28_fsdb_kill.create_fpf_tc28_test_config()

    def test_name_and_tags(self):
        self.assertEqual(self.cfg.name, "fpf_tc28_fsdb_kill")
        self.assertIn("fpf", self.cfg.tags)

    def test_two_playbooks_strict_order(self):
        self.assertEqual(len(self.cfg.playbooks), 2)
        self.assertEqual(self.cfg.playbooks[0].name, "fpf_tc28_fsdb_kill_disrupt")
        self.assertEqual(self.cfg.playbooks[1].name, "fpf_tc28_fsdb_kill_longevity")

    def test_disrupt_playbook_has_repeated_crash_step(self):
        names = _step_names(self.cfg.playbooks[0])
        # repeated-crash, record-disruption, and longevity are all CUSTOM_STEP /
        # LONGEVITY_STEP; assert the crash + injection steps are present.
        self.assertIn(taac_types.StepName.LONGEVITY_STEP, names)
        # at least one CUSTOM_STEP (the repeated fsdb crash + record-disruption).
        self.assertIn(taac_types.StepName.CUSTOM_STEP, names)

    def test_disrupt_session_stat_disruption_mode_28(self):
        checks = _session_stat_checks(self.cfg.playbooks[0])
        self.assertEqual(len(checks), 1)
        params = _check_params(checks[0])
        self.assertEqual(params["mode"], "disruption")
        self.assertEqual(params["expected_connected"], 32)
        self.assertEqual(params["expected_connected_during"], 28)
        self.assertEqual(params["impacted_lanes"], [0])
        self.assertEqual(params["recovery_min_sec"], 60)

    def test_longevity_playbook_has_no_session_stat_disruption(self):
        # The longevity playbook is the stable-state hardening contract; it should
        # not carry a disruption-mode session-stat postcheck of its own.
        for chk in _session_stat_checks(self.cfg.playbooks[1]):
            self.assertNotEqual(_check_params(chk)["mode"], "disruption")

    def test_longevity_playbook_has_v2_stable_check_set(self):
        """Playbook 2 (longevity) is built via create_fpf_hardening_playbook_v2
        and must carry the full stable-state check set (anchored at its own
        start by the runner's per-playbook test_case_start_time re-stamp)."""
        ids = set(_checks_by_id(self.cfg.playbooks[1]).keys())
        self.assertTrue(
            _V2_STABLE_REQUIRED_IDS.issubset(ids),
            f"missing stable check IDs: {_V2_STABLE_REQUIRED_IDS - ids}",
        )


class TestFpfTc29FsdbGrStop30(unittest.TestCase):
    def setUp(self):
        self.cfg = fpf_tc29_fsdb_gr_stop30_reenable.create_fpf_tc29_test_config()

    def test_name_and_order(self):
        self.assertEqual(self.cfg.name, "fpf_tc29_fsdb_gr_stop30_reenable")
        self.assertEqual(len(self.cfg.playbooks), 2)
        self.assertEqual(self.cfg.playbooks[0].name, "fpf_tc29_fsdb_gr_stop30_disrupt")
        self.assertEqual(
            self.cfg.playbooks[1].name, "fpf_tc29_fsdb_gr_stop30_longevity"
        )

    def test_disrupt_has_stop_and_start_steps(self):
        # Two service-interruption steps (stop + start) -> SERVICE_INTERRUPTION_STEP.
        names = _step_names(self.cfg.playbooks[0])
        si_count = sum(
            1 for n in names if n == taac_types.StepName.SERVICE_INTERRUPTION_STEP
        )
        self.assertEqual(si_count, 2)

    def test_session_stat_disruption_recovery_60(self):
        checks = _session_stat_checks(self.cfg.playbooks[0])
        self.assertEqual(len(checks), 1)
        params = _check_params(checks[0])
        self.assertEqual(params["mode"], "disruption")
        self.assertEqual(params["expected_connected_during"], 28)
        self.assertEqual(params["impacted_lanes"], [0])
        # Bumped 30 -> 60: a 120s post-re-enable settle inside the disrupt
        # playbook gives the collector window time to observe the 28 -> 32
        # recovery and a full 60s held floor.
        self.assertEqual(params["recovery_min_sec"], 60)

    def test_disrupt_has_post_reenable_settle(self):
        # FIX 6: a settle longevity step follows the re-enable so the session
        # collector window spans the 28 -> 32 recovery.
        names = _step_names(self.cfg.playbooks[0])
        self.assertEqual(names[-1], taac_types.StepName.LONGEVITY_STEP)

    def test_host_spray_all_samples_true(self):
        # Host-spray postcheck is present (skip_ssh is off in the default unit-test
        # environment) and uses all_samples=True.
        sprays = _host_spray_checks(self.cfg.playbooks[0])
        self.assertEqual(len(sprays), 1)
        params = _check_params(sprays[0])
        self.assertTrue(params.get("all_samples"))
        self.assertEqual(
            sorted(params["hosts"]),
            sorted(fpf_tc29_fsdb_gr_stop30_reenable.SPRAY_HOSTS),
        )

    def test_longevity_playbook_has_v2_stable_check_set(self):
        ids = set(_checks_by_id(self.cfg.playbooks[1]).keys())
        self.assertTrue(
            _V2_STABLE_REQUIRED_IDS.issubset(ids),
            f"missing stable check IDs: {_V2_STABLE_REQUIRED_IDS - ids}",
        )


class TestFpfTc30FsdbGrStop180(unittest.TestCase):
    def setUp(self):
        self.cfg = fpf_tc30_fsdb_gr_stop180_no_reenable.create_fpf_tc30_test_config()

    def test_name_and_order(self):
        self.assertEqual(self.cfg.name, "fpf_tc30_fsdb_gr_stop180_no_reenable")
        self.assertEqual(len(self.cfg.playbooks), 2)
        self.assertEqual(self.cfg.playbooks[0].name, "fpf_tc30_fsdb_gr_stop180_disrupt")
        self.assertEqual(
            self.cfg.playbooks[1].name, "fpf_tc30_fsdb_gr_stop180_stays_down"
        )

    def test_disrupt_has_exactly_one_stop_no_start(self):
        names = _step_names(self.cfg.playbooks[0])
        si_count = sum(
            1 for n in names if n == taac_types.StepName.SERVICE_INTERRUPTION_STEP
        )
        # Exactly one service-interruption step (the stop); fsdb is NOT re-enabled.
        self.assertEqual(si_count, 1)

    def test_disrupt_playbook_has_no_postchecks(self):
        self.assertEqual(_all_postchecks(self.cfg.playbooks[0]), [])

    def test_stays_down_session_stat_stable_28_no_recovery(self):
        checks = _session_stat_checks(self.cfg.playbooks[1])
        self.assertEqual(len(checks), 1)
        params = _check_params(checks[0])
        # "stays at 28, no recovery" -> stable mode, expected_connected=28.
        self.assertEqual(params["mode"], "stable")
        self.assertEqual(params["expected_connected"], 28)


class TestFpfTc31FsdbEnableRecover(unittest.TestCase):
    def setUp(self):
        self.cfg = fpf_tc31_fsdb_enable_recover.create_fpf_tc31_test_config()

    def test_two_playbooks_strict_order(self):
        # FIX 5: restructured to disruption-only (enable+settle) + stable-state
        # longevity, so the stable prechecks run AFTER the enable (not before).
        self.assertEqual(self.cfg.name, "fpf_tc31_fsdb_enable_recover")
        self.assertEqual(len(self.cfg.playbooks), 2)
        self.assertEqual(
            self.cfg.playbooks[0].name, "fpf_tc31_fsdb_enable_recover_disrupt"
        )
        self.assertEqual(
            self.cfg.playbooks[1].name, "fpf_tc31_fsdb_enable_recover_longevity"
        )

    def test_disrupt_playbook_enable_step_no_checks(self):
        # Playbook 1 is disruption-only: the enable step + settle, NO checks.
        disrupt = self.cfg.playbooks[0]
        names = _step_names(disrupt)
        self.assertIn(taac_types.StepName.SERVICE_INTERRUPTION_STEP, names)
        self.assertEqual(names[-1], taac_types.StepName.LONGEVITY_STEP)
        self.assertEqual(_all_postchecks(disrupt), [])
        self.assertEqual(list(disrupt.prechecks or []), [])

    def test_session_stat_stable_32_in_longevity(self):
        # The session-stat stable check now lives in the longevity playbook (2).
        checks = _session_stat_checks(self.cfg.playbooks[1])
        self.assertEqual(len(checks), 1)
        params = _check_params(checks[0])
        self.assertEqual(params["mode"], "stable")
        self.assertEqual(params["expected_connected"], 32)

    def test_longevity_playbook_has_v2_stable_check_set(self):
        ids = set(_checks_by_id(self.cfg.playbooks[1]).keys())
        self.assertTrue(
            _V2_STABLE_REQUIRED_IDS.issubset(ids),
            f"missing stable check IDs: {_V2_STABLE_REQUIRED_IDS - ids}",
        )


class _SessionStatHCExpectationsBase(unittest.IsolatedAsyncioTestCase):
    """Shared scaffolding for driving the session-stat HC with mocked data.

    The check_params are pulled BY check_id from the test config's own
    playbook, so what's exercised is exactly what the config asserts at run
    time.
    """

    async def asyncSetUp(self):
        self.health_check = FpfHrtSessionStatHealthCheck(logger=MagicMock())
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "gtsw001.l1002.c087.mwg2"
        ep_patcher = patch(
            f"{_HC_MODULE}.everpaste_details_suffix",
            new=AsyncMock(return_value=""),
        )
        self.addCleanup(ep_patcher.stop)
        ep_patcher.start()
        skip_patcher = patch(
            f"{_HC_MODULE}.disruption_inconclusive_skip", return_value=None
        )
        self.addCleanup(skip_patcher.stop)
        skip_patcher.start()
        tcs_patcher = patch(
            f"{_HC_MODULE}.get_test_case_start_time", return_value=1000.0
        )
        self.addCleanup(tcs_patcher.stop)
        tcs_patcher.start()

    async def _run_with(self, collector, params):
        with patch(f"{_HC_MODULE}.get_collector", return_value=collector):
            return await self.health_check._run(
                self.device, hc_types.BaseHealthCheckIn(), params
            )

    def _params_from_config(self, playbook, check_id: str) -> dict:
        chk = _checks_by_id(playbook)[check_id]
        return json.loads(chk.check_params.json_params)


class TestTc28Tc29SessionStatHCExpectations(_SessionStatHCExpectationsBase):
    """tc28 + tc29 share the disruption-mode contract: census 32 -> 28 on lane 0
    during the kill / GR-stop, recover to 32 and hold for the configured floor.
    """

    async def test_tc28_drop_then_recover_pass(self):
        cfg = fpf_tc28_fsdb_kill.create_fpf_tc28_test_config()
        params = self._params_from_config(
            cfg.playbooks[0], "fpf_tc28_fsdb_kill_session_stat"
        )
        # 32 stable -> 28 dip on lane 0 -> 32 recovery (held).
        res = FsdbSessionWindowResult(
            host=_GPU_HOST,
            samples=30 + 60 + 25,  # ~115 samples spanning stable+kill+recovery
            error_samples=0,
            min_connected=28,
            max_connected=32,
            last_connected=32,
            reached_expected=True,
            impacted_lane_churn={0: True},
            detail="connected min=28 max=32 last=32",
        )
        result = await self._run_with(_make_session_collector(res), params)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_tc28_never_recovers_fail(self):
        cfg = fpf_tc28_fsdb_kill.create_fpf_tc28_test_config()
        params = self._params_from_config(
            cfg.playbooks[0], "fpf_tc28_fsdb_kill_session_stat"
        )
        # Dropped to 28, climbs to 30 but never reaches 32.
        res = FsdbSessionWindowResult(
            host=_GPU_HOST,
            samples=100,
            error_samples=0,
            min_connected=28,
            max_connected=30,
            last_connected=30,
            reached_expected=False,
            impacted_lane_churn={0: True},
            detail="connected min=28 max=30 last=30",
        )
        result = await self._run_with(
            _make_session_collector(
                res,
                recovery=(
                    False,
                    0.0,
                    "did not recover by window end (last=30, expected 32)",
                ),
            ),
            params,
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("Signal2", result.message)

    async def test_tc29_drop_then_recover_pass(self):
        cfg = fpf_tc29_fsdb_gr_stop30_reenable.create_fpf_tc29_test_config()
        params = self._params_from_config(
            cfg.playbooks[0], "fpf_tc29_fsdb_gr_stop30_session_stat"
        )
        # tc29 now uses a 60s recovery floor (matches tc28) thanks to the
        # post-re-enable settle inside the disrupt playbook.
        self.assertEqual(params["recovery_min_sec"], 60)
        res = FsdbSessionWindowResult(
            host=_GPU_HOST,
            samples=80,
            error_samples=0,
            min_connected=28,
            max_connected=32,
            last_connected=32,
            reached_expected=True,
            impacted_lane_churn={0: True},
            detail="connected min=28 max=32 last=32",
        )
        # Recovered + held 65s >= 60s floor.
        result = await self._run_with(
            _make_session_collector(
                res,
                recovery=(True, 65.0, "recovered to 32 and held 65.0s (>= 60s floor)"),
            ),
            params,
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)


class TestTc30SessionStatHCExpectations(_SessionStatHCExpectationsBase):
    """tc30 ("stays at 28, no recovery"): stable-mode check at 28 — steady
    holds PASS, any climb back toward 32 FAILs the impaired-steady contract."""

    async def test_steady_28_pass(self):
        cfg = fpf_tc30_fsdb_gr_stop180_no_reenable.create_fpf_tc30_test_config()
        params = self._params_from_config(
            cfg.playbooks[1], "fpf_tc30_fsdb_gr_stop180_session_stat"
        )
        self.assertEqual(params["mode"], "stable")
        self.assertEqual(params["expected_connected"], 28)
        res = FsdbSessionWindowResult(
            host=_GPU_HOST,
            samples=40,
            error_samples=0,
            min_connected=28,
            max_connected=28,
            last_connected=28,
            reached_expected=True,
            detail="connected min=28 max=28 last=28",
        )
        result = await self._run_with(_make_session_collector(res), params)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_climbs_back_to_32_fail(self):
        cfg = fpf_tc30_fsdb_gr_stop180_no_reenable.create_fpf_tc30_test_config()
        params = self._params_from_config(
            cfg.playbooks[1], "fpf_tc30_fsdb_gr_stop180_session_stat"
        )
        # The impaired-steady-state contract requires min==max==28; a climb to
        # 32 (fsdb came back unexpectedly) breaks that.
        res = FsdbSessionWindowResult(
            host=_GPU_HOST,
            samples=40,
            error_samples=0,
            min_connected=28,
            max_connected=32,
            last_connected=32,
            reached_expected=True,
            detail="connected min=28 max=32 last=32",
        )
        result = await self._run_with(_make_session_collector(res), params)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)


class TestTc31SessionStatHCExpectations(_SessionStatHCExpectationsBase):
    """tc31: stable-mode @ 32. Steady 32 PASSes; a dip below 32 FAILs."""

    async def test_steady_32_pass(self):
        cfg = fpf_tc31_fsdb_enable_recover.create_fpf_tc31_test_config()
        params = self._params_from_config(
            cfg.playbooks[1], "fpf_tc31_fsdb_enable_recover_session_stat"
        )
        self.assertEqual(params["mode"], "stable")
        self.assertEqual(params["expected_connected"], 32)
        res = FsdbSessionWindowResult(
            host=_GPU_HOST,
            samples=50,
            error_samples=0,
            min_connected=32,
            max_connected=32,
            last_connected=32,
            reached_expected=True,
            detail="connected min=32 max=32 last=32",
        )
        result = await self._run_with(_make_session_collector(res), params)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_dip_to_28_fail(self):
        cfg = fpf_tc31_fsdb_enable_recover.create_fpf_tc31_test_config()
        params = self._params_from_config(
            cfg.playbooks[1], "fpf_tc31_fsdb_enable_recover_session_stat"
        )
        res = FsdbSessionWindowResult(
            host=_GPU_HOST,
            samples=50,
            error_samples=0,
            min_connected=28,
            max_connected=32,
            last_connected=32,
            reached_expected=True,
            detail="connected min=28 max=32 last=32",
        )
        result = await self._run_with(_make_session_collector(res), params)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)


if __name__ == "__main__":
    unittest.main()
