# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe
"""Unit tests for FpfHrtPlaneStatusHealthCheck (multi-host, single collector).

The check reads the single ``hrt_plane_status`` collector (which holds ALL
hosts) via ``get_collector`` and evaluates each host present in its rows
independently; the aggregate is FAIL if any host fails, SKIP if every host has
no in-window data, else PASS. These tests patch ``get_collector`` to return one
synthetic collector whose ``hosts_in_window`` names the hosts and whose
``evaluate_all_up_window`` / ``evaluate_drain_window`` (per-host via the ``host``
kwarg) / ``timeout_count_in_window`` return canned results, so correctness is
proven without devices. ``everpaste_details_suffix`` (network) is patched to a
no-op.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from taac.constants import TestDevice
from taac.health_checks.device_health_checks.fpf_hrt_plane_status_health_check import (
    FpfHrtPlaneStatusHealthCheck,
)
from taac.libs.fpf.fpf_stress_checks import PlaneStatusResult
from taac.health_check.health_check import types as hc_types

HC_MODULE = (
    "neteng.test_infra.dne.taac.health_checks.device_health_checks"
    ".fpf_hrt_plane_status_health_check"
)
HOST_A = "rtptest1544.mwg2"
HOST_B = "rtptest1575.mwg2"


def _up_results(num_planes: int = 8) -> list:
    return [
        PlaneStatusResult(
            plane=p,
            passed=True,
            expected_state="UP",
            observed_state="UP",
            samples=10,
            detail="UP across 10 samples",
        )
        for p in range(num_planes)
    ]


def _one_failing(plane: int = 2) -> list:
    results = _up_results()
    results[plane] = PlaneStatusResult(
        plane=plane,
        passed=False,
        expected_state="UP",
        observed_state="DOWN",
        samples=10,
        detail="not UP — saw DOWN",
    )
    return results


def _make_collector(results_by_host: dict, timeout_count: int = 0) -> MagicMock:
    """One collector holding all hosts. ``results_by_host`` maps host -> the
    per-plane result list that host's ``evaluate_*_window(host=...)`` returns."""
    collector = MagicMock()
    collector.device_id = 0
    hosts = list(results_by_host.keys())
    collector.hosts = hosts
    collector.hosts_in_window.return_value = hosts
    collector.evaluate_all_up_window.side_effect = lambda **kw: results_by_host[
        kw["host"]
    ]
    collector.evaluate_drain_window.side_effect = lambda **kw: results_by_host[
        kw["host"]
    ]
    collector.timeout_count_in_window.return_value = timeout_count
    collector.format_window_table.return_value = "(table)"
    return collector


class TestFpfHrtPlaneStatusHealthCheck(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.logger = MagicMock()
        self.health_check = FpfHrtPlaneStatusHealthCheck(logger=self.logger)
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
        dt_patcher = patch(f"{HC_MODULE}.get_disruption_time", return_value=0.0)
        self.addCleanup(dt_patcher.stop)
        dt_patcher.start()

    async def _run(self, collector, params):
        with patch(f"{HC_MODULE}.get_collector", return_value=collector):
            return await self.health_check._run(
                self.device, hc_types.BaseHealthCheckIn(), params
            )

    async def test_both_hosts_all_up_pass(self):
        """Both hosts all-planes-UP -> PASS."""
        collector = _make_collector({HOST_A: _up_results(), HOST_B: _up_results()})
        result = await self._run(collector, {"mode": "all_up"})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn(HOST_A, result.message)
        self.assertIn(HOST_B, result.message)

    async def test_one_host_failing_aggregate_fail(self):
        """One host has a non-UP plane -> aggregate FAIL (both must pass)."""
        collector = _make_collector({HOST_A: _up_results(), HOST_B: _one_failing(2)})
        result = await self._run(collector, {"mode": "all_up"})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn(HOST_B, result.message)
        self.assertIn("dev0/L2", result.message)

    async def test_timeout_fail(self):
        """A poll timeout (null data) -> FAIL."""
        collector = _make_collector(
            {HOST_A: _up_results(), HOST_B: _up_results()}, timeout_count=3
        )
        result = await self._run(collector, {"mode": "all_up"})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("timeout", result.message)

    async def test_all_hosts_no_samples_skip(self):
        """No in-window samples on any host -> SKIP."""
        collector = _make_collector({HOST_A: [], HOST_B: []})
        result = await self._run(collector, {"mode": "all_up"})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.SKIP)

    async def test_drain_mode_impacted_plane_pass(self):
        """drain mode: impacted plane DRAINED, others UP -> PASS."""
        drained = _up_results()
        drained[0] = PlaneStatusResult(
            plane=0,
            passed=True,
            expected_state="DRAINED",
            observed_state="DRAINED",
            samples=10,
            detail="DRAINED by window end",
        )
        collector = _make_collector({HOST_A: drained})
        result = await self._run(collector, {"mode": "drain", "impacted_planes": [0]})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_drain_mode_passes_exact_device_local_plane_scope(self):
        drained = [
            PlaneStatusResult(
                plane=0,
                device_id=1,
                passed=True,
                expected_state="DRAINED",
                observed_state="DRAINED",
                samples=10,
            )
        ]
        collector = _make_collector({HOST_A: drained})
        collector.device_ids = [0, 1]

        result = await self._run(
            collector,
            {
                "mode": "drain",
                "device_ids": [0, 1],
                "expected_planes": [0],
                "impacted_tuples_by_host_device": {HOST_A: {"1": [0]}},
            },
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        kwargs = collector.evaluate_drain_window.call_args.kwargs
        self.assertEqual(kwargs["device_ids"], [0, 1])
        self.assertEqual(kwargs["impacted_tuples_by_device"], {"1": [0]})

    async def test_drain_mode_preserves_explicit_empty_scope_for_other_host(self):
        collector = _make_collector({HOST_A: _up_results(1), HOST_B: _up_results(1)})

        result = await self._run(
            collector,
            {
                "mode": "drain",
                "device_ids": [0],
                "expected_planes": [0],
                "impacted_planes": [0],
                "impacted_tuples_by_host_device": {
                    HOST_A: {"0": [0]},
                    HOST_B: {},
                },
            },
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        calls_by_host = {
            call.kwargs["host"]: call.kwargs
            for call in collector.evaluate_drain_window.call_args_list
        }
        self.assertEqual(calls_by_host[HOST_A]["impacted_tuples_by_device"], {"0": [0]})
        self.assertEqual(calls_by_host[HOST_B]["impacted_tuples_by_device"], {})

    async def test_drain_window_excludes_stale_prior_playbook_timestamp(self):
        collector = _make_collector({HOST_A: _up_results()})
        with patch(f"{HC_MODULE}.get_disruption_time", return_value=900.0):
            await self._run(
                collector,
                {"mode": "drain", "window_end": 1200.0, "impacted_planes": [0]},
            )

        self.assertEqual(collector.hosts_in_window.call_args.args[0], 1000.0)

    async def test_drain_window_retains_current_playbook_timestamp(self):
        collector = _make_collector({HOST_A: _up_results()})
        with patch(f"{HC_MODULE}.get_disruption_time", return_value=1020.0):
            await self._run(
                collector,
                {"mode": "drain", "window_end": 1200.0, "impacted_planes": [0]},
            )

        self.assertEqual(collector.hosts_in_window.call_args.args[0], 1020.0)

    async def test_no_collector_skip(self):
        """No registered collector -> SKIP."""
        result = await self._run(None, {"mode": "all_up"})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.SKIP)
        self.assertIn("No live HRT plane-status collector", result.message)

    def test_check_scope_is_default(self):
        self.assertEqual(
            FpfHrtPlaneStatusHealthCheck.CHECK_SCOPE, hc_types.Scope.DEFAULT
        )


if __name__ == "__main__":
    unittest.main()
