# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Tests for target-scoped BGP skip-null and RF window boundaries."""

import asyncio
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from taac.constants import TestDevice
from taac.health_checks.device_health_checks import (
    fpf_remote_prefix_lifecycle_health_check as lifecycle_health_check,
)
from taac.health_checks.device_health_checks.fpf_bgp_rib_convergence_health_check import (
    FpfBgpRibConvergenceHealthCheck,
)
from taac.health_checks.device_health_checks.fpf_hrt_remote_failure_convergence_health_check import (
    FpfHrtRemoteFailureConvergenceHealthCheck,
)
from taac.libs.fpf import fpf_stress_checks
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


class RemotePrefixLifecycleSeriesTest(unittest.TestCase):
    def _evaluate(self, rows, *, expected=0, transition=True):
        evaluator = getattr(
            fpf_stress_checks,
            "evaluate_exact_lifecycle_series",
            None,
        )
        self.assertIsNotNone(
            evaluator,
            "remote-prefix lifecycle evaluator must exist",
        )
        return evaluator(
            rows,
            expected=expected,
            anchor_ts=WINDOW_START,
            deadline_sec=120.0,
            value_getter=lambda row: row.matched,
            transition=transition,
        )

    def test_error_row_numeric_zero_never_counts_as_absence(self):
        result = self._evaluate(
            [
                SimpleNamespace(
                    timestamp=_ts(5),
                    matched=0,
                    notes="error: PUBLISHER_NOT_READY",
                    valid=True,
                ),
                SimpleNamespace(
                    timestamp=_ts(10),
                    matched=1000,
                    notes="",
                    valid=True,
                ),
            ]
        )

        self.assertFalse(result.passed)
        self.assertIsNone(result.first_exact_sec)
        self.assertEqual(result.error_count, 1)

    def test_transition_requires_exact_by_deadline_and_exact_final(self):
        result = self._evaluate(
            [
                SimpleNamespace(timestamp=_ts(10), matched=1000, notes="", valid=True),
                SimpleNamespace(timestamp=_ts(30), matched=0, notes="", valid=True),
                SimpleNamespace(timestamp=_ts(60), matched=0, notes="", valid=True),
            ]
        )

        self.assertTrue(result.passed)
        self.assertEqual(result.first_exact_sec, 30.0)
        self.assertEqual(result.final, 0)

    def test_valid_regression_after_exact_is_never_ignored(self):
        result = self._evaluate(
            [
                SimpleNamespace(timestamp=_ts(20), matched=0, notes="", valid=True),
                SimpleNamespace(timestamp=_ts(40), matched=7, notes="", valid=True),
            ]
        )

        self.assertFalse(result.passed)
        self.assertIn("regressed", result.detail)

    def test_present_mode_requires_every_valid_sample_exact(self):
        result = self._evaluate(
            [
                SimpleNamespace(timestamp=_ts(5), matched=999, notes="", valid=True),
                SimpleNamespace(timestamp=_ts(10), matched=1000, notes="", valid=True),
            ],
            expected=1000,
            transition=False,
        )

        self.assertFalse(result.passed)


class RemotePrefixLifecycleBarrierTest(unittest.IsolatedAsyncioTestCase):
    async def test_waits_for_fresh_sample_after_phase_boundary(self):
        wait_for_fresh = getattr(
            lifecycle_health_check,
            "wait_for_fresh_lifecycle_samples",
            None,
        )
        self.assertIsNotNone(wait_for_fresh)
        collector = SimpleNamespace(
            rows=[
                SimpleNamespace(
                    timestamp=_ts(-1),
                    request_end_epoch=WINDOW_START - 1,
                    valid=True,
                    notes="",
                    host="twshared1352.03.mwg2",
                )
            ]
        )

        async def publish_fresh_sample():
            await asyncio.sleep(0.01)
            collector.rows.append(
                SimpleNamespace(
                    timestamp=_ts(1),
                    request_end_epoch=WINDOW_START + 1,
                    valid=True,
                    notes="",
                    host="twshared1352.03.mwg2",
                )
            )

        publisher = asyncio.create_task(publish_fresh_sample())
        passed, missing = await wait_for_fresh(
            [
                (
                    "hrt@1352/dev0",
                    collector,
                    lambda row: row.host == "twshared1352.03.mwg2",
                )
            ],
            anchor_ts=WINDOW_START,
            timeout_sec=0.2,
            poll_interval_sec=0.005,
        )
        await publisher
        self.assertTrue(passed)
        self.assertEqual(missing, [])

    async def test_no_fresh_sample_remains_fail_closed(self):
        wait_for_fresh = getattr(
            lifecycle_health_check,
            "wait_for_fresh_lifecycle_samples",
            None,
        )
        self.assertIsNotNone(wait_for_fresh)
        collector = SimpleNamespace(
            rows=[
                SimpleNamespace(
                    timestamp=_ts(-1),
                    request_end_epoch=WINDOW_START - 1,
                    valid=True,
                    notes="",
                )
            ]
        )
        passed, missing = await wait_for_fresh(
            [("hrt@1352/dev0", collector, lambda _row: True)],
            anchor_ts=WINDOW_START,
            timeout_sec=0.01,
            poll_interval_sec=0.001,
        )
        self.assertFalse(passed)
        self.assertEqual(missing, ["hrt@1352/dev0"])


class BgpSkipNullTargetScopeTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.health_check = FpfBgpRibConvergenceHealthCheck(logger=MagicMock())
        self.device = MagicMock(spec=TestDevice)

    async def _run(
        self,
        rows: list[BgpRibRow],
        *,
        stability_mode: str = "skip_null_strict",
        informational: bool = False,
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
            return await self.health_check._run(
                self.device,
                hc_types.BaseHealthCheckIn(),
                {
                    "lane_map": {"0": TARGET},
                    "expected_matched": EXPECTED,
                    "use_live_collectors": True,
                    "window_start": WINDOW_START,
                    "window_end": WINDOW_START + 80,
                    "signal1_e2e_max_sec": 60.0,
                    "signal2_local_max_sec": 60.0,
                    "signal3_stability_duration_sec": 60.0,
                    "stability_mode": stability_mode,
                    "informational": informational,
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

    async def test_disrupt_diagnostic_preserves_partial_and_null_as_non_gating(self):
        rows = [
            BgpRibRow(_ts(10), TARGET, 0, 0),
            BgpRibRow(_ts(20), TARGET, EXPECTED // 2, EXPECTED // 2),
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
            BgpRibRow(_ts(70), TARGET, EXPECTED, EXPECTED),
        ]
        diagnostic = await self._run(
            rows,
            stability_mode="strict",
            informational=True,
            host_timeout_timestamps={TARGET: [WINDOW_START + 45]},
        )
        strict = await self._run(
            rows,
            stability_mode="strict",
            informational=False,
            host_timeout_timestamps={TARGET: [WINDOW_START + 45]},
        )

        self.assertEqual(diagnostic.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("[INFORMATIONAL]", diagnostic.message)
        self.assertEqual(strict.status, hc_types.HealthCheckStatus.FAIL)

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
                recovery_stability_sec=60.0,
                check_params={
                    "window_end": WINDOW_START + 200,
                    "only_hosts": ["host"],
                },
            )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertEqual(
            collector.evaluate_per_lane_window.call_args.kwargs[
                "recovery_stability_sec"
            ],
            60.0,
        )
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
