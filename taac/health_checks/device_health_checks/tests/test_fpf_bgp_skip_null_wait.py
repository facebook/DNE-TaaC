# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Tests for target-scoped BGP skip-null and RF window boundaries."""

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from taac.constants import TestDevice
from taac.health_checks.device_health_checks.fpf_bgp_rib_convergence_health_check import (
    FpfBgpRibConvergenceHealthCheck,
)
from taac.health_checks.device_health_checks.fpf_hrt_remote_failure_convergence_health_check import (
    FpfHrtRemoteFailureConvergenceHealthCheck,
)
from taac.libs.fpf.fpf_stress_checks import (
    BgpRibCollector,
    BgpRibRow,
    PerLaneResult,
)
from taac.health_check.health_check import types as hc_types

BGP_MODULE = (
    "neteng.test_infra.dne.taac.health_checks.device_health_checks."
    "fpf_bgp_rib_convergence_health_check"
)
REMOTE_MODULE = (
    "neteng.test_infra.dne.taac.health_checks.device_health_checks."
    "fpf_hrt_remote_failure_convergence_health_check"
)
WINDOW_START = 1_700_000_000.0
TARGET = "gtsw001.l1002.c087.mwg2"
UNRELATED = "gtsw009.l1002.c087.mwg2"
EXPECTED = 4032


def _ts(offset_sec: float) -> str:
    return datetime.fromtimestamp(WINDOW_START + offset_sec, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S.%f%z"
    )


class BgpSkipNullTargetScopeTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.health_check = FpfBgpRibConvergenceHealthCheck(logger=MagicMock())
        self.device = MagicMock(spec=TestDevice)

    async def _run(
        self,
        rows: list[BgpRibRow],
        *,
        stability_mode: str = "skip_null_strict",
        timeout_timestamps: list[float] | None = None,
        host_timeout_timestamps: dict[str, list[float]] | None = None,
    ) -> hc_types.HealthCheckResult:
        collector = BgpRibCollector(
            gtsws=[TARGET, UNRELATED], subnet_prefix="5000::/16"
        )
        collector.rows = rows
        collector.timeout_timestamps = timeout_timestamps or []
        collector.host_timeout_timestamps = host_timeout_timestamps or {}
        with (
            patch(f"{BGP_MODULE}.get_collector", return_value=collector),
            patch(f"{BGP_MODULE}.get_test_case_start_time", return_value=WINDOW_START),
            patch(
                f"{BGP_MODULE}.everpaste_details_suffix",
                new=AsyncMock(return_value=""),
            ),
        ):
            return await self.health_check._evaluate_from_live_collector(
                lane_map={0: TARGET},
                expected=EXPECTED,
                check_params={
                    "window_start": WINDOW_START,
                    "window_end": WINDOW_START + 80,
                    "signal1_e2e_max_sec": 60.0,
                    "signal2_local_max_sec": 60.0,
                    "signal3_stability_duration_sec": 60.0,
                    "stability_mode": stability_mode,
                },
            )

    async def test_unrelated_device_timeout_is_ignored(self):
        result = await self._run(
            [BgpRibRow(_ts(10), TARGET, EXPECTED, EXPECTED)],
            host_timeout_timestamps={UNRELATED: [WINDOW_START + 5]},
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_target_no_data_fails(self):
        result = await self._run(
            [BgpRibRow(_ts(10), UNRELATED, EXPECTED, EXPECTED)],
            host_timeout_timestamps={TARGET: [WINDOW_START + 5]},
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("INSUFFICIENT MEASUREMENT", result.message)
        self.assertIn(TARGET, result.message)

    async def test_target_recovery_after_deadline_fails(self):
        result = await self._run([BgpRibRow(_ts(70), TARGET, EXPECTED, EXPECTED)])

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)

    async def test_target_dirty_final_sample_fails(self):
        result = await self._run(
            [
                BgpRibRow(_ts(10), TARGET, EXPECTED, EXPECTED),
                BgpRibRow(_ts(20), TARGET, EXPECTED - 1, EXPECTED - 1),
            ]
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)

    async def test_strict_mode_retains_global_timeout_failure(self):
        result = await self._run(
            [BgpRibRow(_ts(10), TARGET, EXPECTED, EXPECTED)],
            stability_mode="strict",
            timeout_timestamps=[WINDOW_START + 5],
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)

    async def test_strict_mode_retains_target_timeout_failure(self):
        result = await self._run(
            [BgpRibRow(_ts(10), TARGET, EXPECTED, EXPECTED)],
            stability_mode="strict",
            host_timeout_timestamps={TARGET: [WINDOW_START + 5]},
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)

    async def test_strict_timeout_started_inside_window_fails(self):
        result = await self._run(
            [
                BgpRibRow(_ts(10), TARGET, EXPECTED, EXPECTED),
                BgpRibRow(
                    _ts(45),
                    TARGET,
                    0,
                    0,
                    notes="error: poll timeout (30s)",
                    request_start_epoch=WINDOW_START + 15,
                    request_end_epoch=WINDOW_START + 45,
                    duration_sec=30.0,
                ),
            ],
            stability_mode="strict",
            host_timeout_timestamps={TARGET: [WINDOW_START + 45]},
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("1 target/global poll timeout", result.message)
        self.assertIn("charged", result.message)

    async def test_strict_timeout_started_before_window_is_excluded(self):
        result = await self._run(
            [
                BgpRibRow(
                    _ts(5),
                    TARGET,
                    0,
                    0,
                    notes="error: poll timeout (30s)",
                    request_start_epoch=WINDOW_START - 25,
                    request_end_epoch=WINDOW_START + 5,
                    duration_sec=30.0,
                ),
                BgpRibRow(_ts(10), TARGET, EXPECTED, EXPECTED),
            ],
            stability_mode="strict",
            host_timeout_timestamps={TARGET: [WINDOW_START + 5]},
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_live_skip_null_requests_target_aware_wait(self):
        collector = BgpRibCollector(gtsws=[TARGET], subnet_prefix="5000::/16")
        collector.rows = [BgpRibRow(_ts(10), TARGET, EXPECTED, EXPECTED)]
        waiter = AsyncMock(return_value=WINDOW_START + 80)
        with (
            patch(f"{BGP_MODULE}.get_collector", return_value=collector),
            patch(f"{BGP_MODULE}.get_test_case_start_time", return_value=WINDOW_START),
            patch(f"{BGP_MODULE}.wait_for_target_rib_rows", new=waiter),
            patch(
                f"{BGP_MODULE}.everpaste_details_suffix",
                new=AsyncMock(return_value=""),
            ),
        ):
            result = await self.health_check._evaluate_from_live_collector(
                lane_map={0: TARGET},
                expected=EXPECTED,
                check_params={
                    "signal1_e2e_max_sec": 300.0,
                    "signal2_local_max_sec": 60.0,
                    "signal3_stability_duration_sec": 60.0,
                    "stability_mode": "skip_null_strict",
                },
            )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertEqual(set(waiter.call_args.kwargs["target_devices"]), {TARGET})
        self.assertEqual(waiter.call_args.kwargs["deadline"], WINDOW_START + 300)


class RemoteFailureWindowBoundaryTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.health_check = FpfHrtRemoteFailureConvergenceHealthCheck(
            logger=MagicMock()
        )
        self.device = MagicMock(spec=TestDevice)

    async def _window_start(self, disruption_time: float) -> float:
        collector = MagicMock()
        collector.evaluate_per_lane_window.return_value = [
            PerLaneResult(
                lane=0,
                device="host/dev0/L0",
                check_type="HRT remote_failure stable",
                passed=True,
                expected=0,
                actual=0,
            )
        ]
        collector.timeout_count_in_window.return_value = 0
        with (
            patch(f"{REMOTE_MODULE}.get_collector", return_value=collector),
            patch(
                f"{REMOTE_MODULE}.get_test_case_start_time",
                return_value=WINDOW_START,
            ),
            patch(
                f"{REMOTE_MODULE}.get_disruption_time",
                return_value=disruption_time,
            ),
            patch(
                f"{REMOTE_MODULE}.everpaste_details_suffix",
                new=AsyncMock(return_value=""),
            ),
        ):
            result = await self.health_check._evaluate_from_live_collector(
                lanes=[0],
                device_ids=[0],
                expected_per_lane={0: 0},
                direction="stable_skip_null_strict",
                max_convergence_sec=120,
                check_params={
                    "window_end": WINDOW_START + 200,
                    "only_hosts": ["host"],
                },
            )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        return collector.evaluate_per_lane_window.call_args.kwargs["window_start"]

    async def test_stale_prior_playbook_disruption_is_excluded(self):
        self.assertEqual(
            await self._window_start(WINDOW_START - 100),
            WINDOW_START,
        )

    async def test_current_playbook_disruption_is_retained(self):
        self.assertEqual(
            await self._window_start(WINDOW_START + 20),
            WINDOW_START + 20,
        )


if __name__ == "__main__":
    unittest.main()
