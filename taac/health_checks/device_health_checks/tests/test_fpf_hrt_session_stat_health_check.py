# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe
"""Unit tests for FpfHrtSessionStatHealthCheck.

The health check is a pure postcheck over the single ``hrt_fsdb_session``
collector (which holds ALL hosts; the check iterates its hosts). These tests
patch ``get_collector`` to return a synthetic collector whose
``hosts_in_window`` names the host(s) and whose ``evaluate_window`` /
``evaluate_recovery_hold`` return canned, windowed results (simulating 32->28
drop + recovery, never-recover, never-drop, no-samples, and the stable-state
steady / dip cases), so correctness is proven without devices.

``everpaste_details_suffix`` (network) is patched to a no-op so the check logic
is exercised in isolation.
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
GPU_HOST = "rtptest1544.mwg2"


def _make_collector(
    window_result: FsdbSessionWindowResult,
    recovery=(True, 90.0, "recovered to 32 and held for 90.0s (>= 60s floor)"),
    timeout_count: int = 0,
    hosts=(GPU_HOST,),
) -> MagicMock:
    collector = MagicMock()
    collector.hosts = list(hosts)
    collector.hosts_in_window.return_value = list(hosts)
    collector.evaluate_window.return_value = window_result
    collector.evaluate_recovery_hold.return_value = recovery
    collector.timeout_count_in_window.return_value = timeout_count
    collector.format_window_table.return_value = "(table)"
    return collector


class TestFpfHrtSessionStatHealthCheck(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.logger = MagicMock()
        self.health_check = FpfHrtSessionStatHealthCheck(logger=self.logger)
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "gtsw001.l1002.c087.mwg2"
        # Patch the network-bound everpaste suffix to a no-op for all tests.
        patcher = patch(
            f"{HC_MODULE}.everpaste_details_suffix",
            new=AsyncMock(return_value=""),
        )
        self.addCleanup(patcher.stop)
        patcher.start()
        # Default: no disruption verified ineffective, fixed window.
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
        # Default: no disruption time recorded.
        dt_patcher = patch(f"{HC_MODULE}.get_disruption_time", return_value=0.0)
        self.addCleanup(dt_patcher.stop)
        dt_patcher.start()

    async def _run(self, collector, params):
        # The check reads the single "hrt_fsdb_session" collector via
        # get_collector(); None models an empty registry.
        with patch(f"{HC_MODULE}.get_collector", return_value=collector):
            return await self.health_check._run(
                self.device, hc_types.BaseHealthCheckIn(), params
            )

    # ---- disruption mode ---------------------------------------------------

    async def test_disruption_drop_then_recover_pass(self):
        """32->28 during kill window + churn on L0 + recovered >=60s -> PASS."""
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
        collector = _make_collector(res)
        params = {
            "mode": "disruption",
            "expected_connected": 32,
            "expected_connected_during": 28,
            "impacted_lanes": [0],
            "recovery_min_sec": 60,
        }
        result = await self._run(collector, params)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_disruption_uses_exact_device_local_plane_churn(self):
        """A healthy dev0/L0 cannot satisfy the impacted dev1/L0 tuple."""
        res = FsdbSessionWindowResult(
            host=GPU_HOST,
            samples=40,
            error_samples=0,
            min_connected=31,
            max_connected=32,
            last_connected=32,
            reached_expected=True,
            impacted_tuple_churn={"dev1/L0": True},
            detail="dev1/L0 churned",
        )
        collector = _make_collector(res)
        params = {
            "mode": "disruption",
            "expected_connected": 32,
            "expected_connected_during": 31,
            "impacted_tuples_by_host_device": {GPU_HOST: {"1": [0]}},
            "recovery_min_sec": 60,
        }

        result = await self._run(collector, params)

        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        kwargs = collector.evaluate_window.call_args.kwargs
        self.assertEqual(kwargs["impacted_tuples_by_device"], {"1": [0]})
        self.assertIn("dev1/L0=yes", result.message)

    async def test_disruption_never_recovers_fail(self):
        """Dropped to 28 with churn but never recovered to 32 -> FAIL."""
        res = FsdbSessionWindowResult(
            host=GPU_HOST,
            samples=40,
            error_samples=0,
            min_connected=28,
            max_connected=31,
            last_connected=28,
            reached_expected=False,
            impacted_lane_churn={0: True},
            detail="connected min=28 max=31 last=28",
        )
        collector = _make_collector(
            res,
            recovery=(
                False,
                0.0,
                "did not recover by window end (last=28, expected 32)",
            ),
        )
        params = {
            "mode": "disruption",
            "expected_connected": 32,
            "expected_connected_during": 28,
            "impacted_lanes": [0],
        }
        result = await self._run(collector, params)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("Signal2", result.message)

    async def test_disruption_never_drops_fail(self):
        """Count never dropped (stayed 32, no churn) -> FAIL (disruption ineffective)."""
        res = FsdbSessionWindowResult(
            host=GPU_HOST,
            samples=40,
            error_samples=0,
            min_connected=32,
            max_connected=32,
            last_connected=32,
            reached_expected=True,
            impacted_lane_churn={0: False},
            detail="connected min=32 max=32 last=32",
        )
        collector = _make_collector(res)
        params = {
            "mode": "disruption",
            "expected_connected": 32,
            "expected_connected_during": 28,
            "impacted_lanes": [0],
        }
        result = await self._run(collector, params)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("Signal1", result.message)

    async def test_disruption_no_samples_skip(self):
        """No in-window samples -> SKIP."""
        res = FsdbSessionWindowResult(
            host=GPU_HOST,
            samples=0,
            error_samples=0,
            min_connected=None,
            max_connected=None,
            last_connected=None,
            reached_expected=False,
            detail="no non-null in-window samples",
        )
        collector = _make_collector(res)
        params = {"mode": "disruption", "impacted_lanes": [0]}
        result = await self._run(collector, params)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.SKIP)

    async def test_disruption_inconclusive_skip(self):
        """Disruption verified ineffective -> SKIP before evaluating."""
        with patch(
            f"{HC_MODULE}.disruption_inconclusive_skip",
            return_value="INCONCLUSIVE — disruption did not take effect",
        ):
            res = FsdbSessionWindowResult(
                host=GPU_HOST,
                samples=10,
                error_samples=0,
                min_connected=32,
                max_connected=32,
                last_connected=32,
                reached_expected=True,
            )
            collector = _make_collector(res)
            result = await self._run(
                collector, {"mode": "disruption", "impacted_lanes": [0]}
            )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.SKIP)
        self.assertIn("INCONCLUSIVE", result.message)

    async def test_disruption_poll_timeout_fail(self):
        """A poll timeout (null data) in window -> FAIL even if signals pass."""
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
        collector = _make_collector(res, timeout_count=2)
        params = {
            "mode": "disruption",
            "impacted_lanes": [0],
            "expected_connected_during": 28,
        }
        result = await self._run(collector, params)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("null data", result.message)

    # ---- stable mode -------------------------------------------------------

    async def test_stable_steady_pass(self):
        """Steady 32 across the window -> PASS."""
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
        collector = _make_collector(res)
        result = await self._run(
            collector, {"mode": "stable", "expected_connected": 32}
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_stable_dip_fail(self):
        """A dip below 32 during a 'stable' window -> FAIL."""
        res = FsdbSessionWindowResult(
            host=GPU_HOST,
            samples=50,
            error_samples=0,
            min_connected=30,
            max_connected=32,
            last_connected=32,
            reached_expected=True,
            detail="connected min=30 max=32 last=32",
        )
        collector = _make_collector(res)
        result = await self._run(
            collector, {"mode": "stable", "expected_connected": 32}
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)

    async def test_stable_no_samples_skip(self):
        """No samples in a stable window -> SKIP."""
        res = FsdbSessionWindowResult(
            host=GPU_HOST,
            samples=0,
            error_samples=0,
            min_connected=None,
            max_connected=None,
            last_connected=None,
            reached_expected=False,
            detail="no non-null in-window samples",
        )
        collector = _make_collector(res)
        result = await self._run(collector, {"mode": "stable"})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.SKIP)

    async def test_stable_message_names_window_and_impacted_lane(self):
        """The stable PASS message includes the window span + impacted lane(s)."""
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
        collector = _make_collector(res)
        result = await self._run(
            collector,
            {"mode": "stable", "expected_connected": 28, "impacted_lanes": [0]},
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("L0", result.message)
        self.assertIn("window", result.message)
        self.assertIn("connected min=28", result.message)

    # ---- window_from_disruption_time --------------------------------------

    async def test_window_from_disruption_time_scopes_window(self):
        """window_from_disruption_time scopes evaluate_window to
        [disruption_time, disruption_time + window_duration_sec]."""
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
        collector = _make_collector(res)
        with (
            patch(f"{HC_MODULE}.get_collector", return_value=collector),
            patch(f"{HC_MODULE}.get_disruption_time", return_value=7000.0),
        ):
            result = await self.health_check._run(
                self.device,
                hc_types.BaseHealthCheckIn(),
                {
                    "mode": "stable",
                    "expected_connected": 28,
                    "impacted_lanes": [0],
                    "window_from_disruption_time": True,
                    "window_duration_sec": 180,
                },
            )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        kwargs = collector.evaluate_window.call_args.kwargs
        self.assertEqual(kwargs["window_start"], 7000.0)
        self.assertEqual(kwargs["window_end"], 7180.0)

    async def test_window_from_disruption_time_falls_back_when_unset(self):
        """When no disruption time was recorded (0.0), the normal window is used."""
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
        collector = _make_collector(res)
        # get_disruption_time defaults to 0.0 via setUp patch.
        result = await self._run(
            collector,
            {
                "mode": "stable",
                "expected_connected": 28,
                "impacted_lanes": [0],
                "window_from_disruption_time": True,
                "window_duration_sec": 180,
            },
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        kwargs = collector.evaluate_window.call_args.kwargs
        # Falls back to tc_start (1000.0), not the disruption window.
        self.assertEqual(kwargs["window_start"], 1000.0)

    # ---- misc --------------------------------------------------------------

    # ---- multi-host (single collector holds all hosts) --------------------

    async def test_multi_host_all_steady_pass(self):
        """One collector, two hosts, both steady at 32 -> aggregate PASS."""
        host_a = "rtptest1544.mwg2"
        host_b = "rtptest1575.mwg2"

        def _res(host):
            return FsdbSessionWindowResult(
                host=host,
                samples=50,
                error_samples=0,
                min_connected=32,
                max_connected=32,
                last_connected=32,
                reached_expected=True,
                detail=f"connected min=32 max=32 last=32 ({host})",
            )

        collector = _make_collector(_res(host_a), hosts=(host_a, host_b))
        collector.evaluate_window.side_effect = lambda **kw: _res(kw["host"])
        result = await self._run(
            collector, {"mode": "stable", "expected_connected": 32}
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn(host_a, result.message)
        self.assertIn(host_b, result.message)

    async def test_multi_host_one_fails_aggregate_fail(self):
        """One collector, two hosts; host B dips -> aggregate FAIL."""
        host_a = "rtptest1544.mwg2"
        host_b = "rtptest1575.mwg2"

        def _res(host):
            dip = host == host_b
            return FsdbSessionWindowResult(
                host=host,
                samples=50,
                error_samples=0,
                min_connected=30 if dip else 32,
                max_connected=32,
                last_connected=32,
                reached_expected=True,
                detail=f"connected ({host})",
            )

        collector = _make_collector(_res(host_a), hosts=(host_a, host_b))
        collector.evaluate_window.side_effect = lambda **kw: _res(kw["host"])
        result = await self._run(
            collector, {"mode": "stable", "expected_connected": 32}
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn(host_b, result.message)

    async def test_no_collector_skip(self):
        """No registered collector -> SKIP."""
        result = await self._run(None, {"mode": "disruption"})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.SKIP)
        self.assertIn("No live HRT FSDB-session collector", result.message)

    def test_check_scope_is_default(self):
        self.assertEqual(
            FpfHrtSessionStatHealthCheck.CHECK_SCOPE, hc_types.Scope.DEFAULT
        )
