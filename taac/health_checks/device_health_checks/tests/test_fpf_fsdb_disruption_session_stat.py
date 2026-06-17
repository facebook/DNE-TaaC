# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe
"""Focused session-stat-logic tests for the FPF FSDB disruption configs (TC28-31).

These mirror the mocked-collector pattern from
``test_fpf_hrt_session_stat_health_check.py`` but pin down the exact expectations
the four FSDB-disruption configs encode:

  - TC28/TC29 disruption window: census drops to 28 on lane 0 then recovers to 32
    -> PASS; never recovering -> FAIL (the lane-kill must heal).
  - TC30 "stays at 28, no recovery": stable-mode census held steady at 28 -> PASS;
    a census that climbs back toward 32 (i.e. did not stay down) -> FAIL.
  - TC31 recovery: stable-mode census steady at 32 -> PASS.

``get_collector`` is patched to a synthetic collector whose ``evaluate_window`` /
``evaluate_recovery_hold`` return canned windowed results, so correctness is
proven without any device. ``everpaste_details_suffix`` (network) is a no-op.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from taac.constants import TestDevice
from taac.health_checks.device_health_checks.fpf_hrt_session_stat_health_check import (
    FpfHrtSessionStatHealthCheck,
)
from taac.libs.fpf.fpf_stress_checks import (
    FsdbSessionWindowResult,
)
from taac.health_check.health_check import types as hc_types

HC_MODULE = (
    "neteng.test_infra.dne.taac.health_checks.device_health_checks"
    ".fpf_hrt_session_stat_health_check"
)
GPU_HOST = "rtptest1555.mwg2"


def _make_collector(
    window_result: FsdbSessionWindowResult,
    recovery=(True, 90.0, "recovered to 32 and held for 90.0s (>= floor)"),
    timeout_count: int = 0,
) -> MagicMock:
    collector = MagicMock()
    collector.host = GPU_HOST
    collector.evaluate_window.return_value = window_result
    collector.evaluate_recovery_hold.return_value = recovery
    collector.timeout_count_in_window.return_value = timeout_count
    collector.format_window_table.return_value = "(table)"
    return collector


class TestFpfFsdbDisruptionSessionStat(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.logger = MagicMock()
        self.health_check = FpfHrtSessionStatHealthCheck(logger=self.logger)
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "gtsw001.l1002.c087.mwg2"
        ep_patcher = patch(
            f"{HC_MODULE}.everpaste_details_suffix",
            new=AsyncMock(return_value=""),
        )
        self.addCleanup(ep_patcher.stop)
        ep_patcher.start()
        skip_patcher = patch(
            f"{HC_MODULE}.disruption_inconclusive_skip", return_value=None
        )
        self.addCleanup(skip_patcher.stop)
        skip_patcher.start()
        tcs_patcher = patch(
            f"{HC_MODULE}.get_test_case_start_time", return_value=1000.0
        )
        self.addCleanup(tcs_patcher.stop)
        tcs_patcher.start()

    async def _run(self, collector, params):
        with patch(f"{HC_MODULE}.get_collector", return_value=collector):
            return await self.health_check._run(
                self.device, hc_types.BaseHealthCheckIn(), params
            )

    # ---- TC28 / TC29: lane-0 kill drops 32->28 then recovers ---------------

    async def test_tc28_tc29_drop_to_28_then_recover_pass(self):
        res = FsdbSessionWindowResult(
            host=GPU_HOST,
            samples=40,
            error_samples=0,
            min_connected=28,
            max_connected=32,
            last_connected=32,
            reached_expected=True,
            impacted_lane_churn={0: True},
            detail="connected min=28 max=32 last=32",
        )
        result = await self._run(
            _make_collector(res),
            {
                "mode": "disruption",
                "expected_connected": 32,
                "expected_connected_during": 28,
                "impacted_lanes": [0],
                "recovery_min_sec": 30,
            },
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_tc28_tc29_never_recovers_fail(self):
        res = FsdbSessionWindowResult(
            host=GPU_HOST,
            samples=40,
            error_samples=0,
            min_connected=28,
            max_connected=28,
            last_connected=28,
            reached_expected=False,
            impacted_lane_churn={0: True},
            detail="connected min=28 max=28 last=28",
        )
        result = await self._run(
            _make_collector(
                res,
                recovery=(False, 0.0, "did not recover by window end (last=28)"),
            ),
            {
                "mode": "disruption",
                "expected_connected": 32,
                "expected_connected_during": 28,
                "impacted_lanes": [0],
            },
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("Signal2", result.message)

    # ---- TC30: "stays at 28, no recovery" via stable mode @ 28 -------------

    async def test_tc30_stays_at_28_stable_pass(self):
        res = FsdbSessionWindowResult(
            host=GPU_HOST,
            samples=50,
            error_samples=0,
            min_connected=28,
            max_connected=28,
            last_connected=28,
            reached_expected=True,
            detail="connected min=28 max=28 last=28",
        )
        result = await self._run(
            _make_collector(res),
            {"mode": "stable", "expected_connected": 28},
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_tc30_recovered_unexpectedly_fail(self):
        # If the census climbs back toward 32 during the "stays-down" window, the
        # impaired-steady-state contract is violated (min != max != 28).
        res = FsdbSessionWindowResult(
            host=GPU_HOST,
            samples=50,
            error_samples=0,
            min_connected=28,
            max_connected=32,
            last_connected=32,
            reached_expected=True,
            detail="connected min=28 max=32 last=32",
        )
        result = await self._run(
            _make_collector(res),
            {"mode": "stable", "expected_connected": 28},
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)

    # ---- TC31: full recovery, stable @ 32 ---------------------------------

    async def test_tc31_recovered_to_32_stable_pass(self):
        res = FsdbSessionWindowResult(
            host=GPU_HOST,
            samples=50,
            error_samples=0,
            min_connected=32,
            max_connected=32,
            last_connected=32,
            reached_expected=True,
            detail="connected min=32 max=32 last=32",
        )
        result = await self._run(
            _make_collector(res),
            {"mode": "stable", "expected_connected": 32},
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)


if __name__ == "__main__":
    unittest.main()
