# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""Tests for FSDB ribMap restart-time selection."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from taac.health_checks.device_health_checks.fpf_fsdb_ribmap_convergence_health_check import (
    FpfFsdbRibmapConvergenceHealthCheck,
)
from taac.libs.fpf.fpf_collector_registry import (
    clear_all,
    get_disruption_time,
    get_restart_time,
    set_disruption_time,
    set_restart_time,
)

_MODULE = (
    "neteng.test_infra.dne.taac.health_checks.device_health_checks."
    "fpf_fsdb_ribmap_convergence_health_check"
)


class TestFpfFsdbRibmapRestartTime(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        clear_all()
        self.addCleanup(clear_all)

    def test_restart_and_disruption_times_are_independent(self):
        set_disruption_time(100.0)
        set_restart_time(200.0)

        self.assertEqual(get_disruption_time(), 100.0)
        self.assertEqual(get_restart_time(), 200.0)

    async def _run(self, use_restart_time: bool, include_window_end: bool = True):
        health_check = FpfFsdbRibmapConvergenceHealthCheck(logger=MagicMock())
        evaluator = AsyncMock(
            return_value=(
                [(0, "gtsw001.l1002.c087.mwg2", True, 4.0, 1, "ok")],
                300.0,
            )
        )
        with (
            patch(f"{_MODULE}.get_restart_time", return_value=200.0),
            patch(f"{_MODULE}.get_disruption_time", return_value=100.0),
            patch(f"{_MODULE}.get_test_case_start_time", return_value=50.0),
            patch(f"{_MODULE}.wait_for_restart_reconverge", evaluator),
            patch(
                f"{_MODULE}.everpaste_details_suffix",
                new=AsyncMock(return_value=""),
            ),
        ):
            check_params = {
                "use_restart_time": use_restart_time,
                "reconverge_sla_sec": 20.0,
            }
            if include_window_end:
                check_params["window_end"] = 300.0
            await health_check._evaluate_restart_reconverge(
                collector=MagicMock(),
                lane_map={0: "gtsw001.l1002.c087.mwg2"},
                expected=4032,
                check_params=check_params,
                default_sla_sec=20.0,
            )
        return evaluator.call_args.kwargs

    async def test_uses_separate_restart_time_when_requested(self):
        kwargs = await self._run(use_restart_time=True)
        self.assertEqual(kwargs["disruption_ts"], 200.0)
        self.assertEqual(kwargs["reconverge_sla_sec"], 20.0)

    async def test_preserves_legacy_disruption_time_default(self):
        kwargs = await self._run(use_restart_time=False)
        self.assertEqual(kwargs["disruption_ts"], 100.0)

    async def test_live_restart_waits_without_fixed_window_end(self):
        kwargs = await self._run(use_restart_time=True, include_window_end=False)
        self.assertIsNone(kwargs["window_end"])


if __name__ == "__main__":
    unittest.main()
