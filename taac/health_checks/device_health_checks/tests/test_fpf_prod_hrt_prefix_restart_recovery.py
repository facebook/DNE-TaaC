# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""Tests for production-prefix recovery after an HRT restart."""

import unittest
from datetime import datetime, timedelta, timezone

from taac.health_checks.device_health_checks.fpf_prod_hrt_prefix_stability_health_check import (
    _evaluate_host_restart_recovery,
)
from taac.libs.fpf.fpf_prod_hrt_prefix import PrefixReachability
from taac.libs.fpf.fpf_stress_checks import ProdHrtPrefixRow

HOST = "twshared1352.03.mwg2"
PREFIX_A = "2401:db00:eef0:1100::/56"
PREFIX_B = "2401:db00:eef0:1200::/56"
BASE = datetime(2026, 8, 29, 18, 0, 0, tzinfo=timezone.utc)
RESTART_TS = BASE.timestamp()


def _timestamp(offset_sec: float) -> str:
    return (BASE + timedelta(seconds=offset_sec)).strftime("%Y-%m-%d %H:%M:%S.%f%z")


def _state(reachable, unreachable) -> PrefixReachability:
    return PrefixReachability(
        reachable_planes=list(reachable),
        drained_planes=[],
        unreachable_planes=list(unreachable),
        plane_up=[0, 1, 2, 3],
        plane_down=[],
        device_ids=[0],
    )


GOOD_A = _state([0, 1, 2, 3], [])
BAD_A = _state([1, 2, 3], [0])
GOOD_B = _state([], [0, 1, 2, 3])
BAD_B = _state([0], [1, 2, 3])


def _row(offset_sec: float, prefixes) -> ProdHrtPrefixRow:
    return ProdHrtPrefixRow(
        timestamp=_timestamp(offset_sec),
        host=HOST,
        prefixes=prefixes,
    )


class _Collector:
    def __init__(self, rows):
        self.rows = rows

    def get_rows_in_window(self, window_start, window_end):
        return self.rows


class TestFpfProdHrtPrefixRestartRecovery(unittest.TestCase):
    def _evaluate(self, rows, prefixes=None, sla=30.0, completion_offset=None):
        return _evaluate_host_restart_recovery(
            host=HOST,
            collector=_Collector(rows),
            window_start=RESTART_TS - 60,
            window_end=RESTART_TS + 120,
            target_norms=set(prefixes) if prefixes else None,
            restart_ts=RESTART_TS,
            max_recovery_sec=sla,
            restart_completion_ts=(
                RESTART_TS + completion_offset
                if completion_offset is not None
                else None
            ),
        )

    def test_historical_8_808_second_recovery_passes(self):
        result = self._evaluate(
            [
                _row(-1, {PREFIX_A: GOOD_A}),
                _row(0.5, {}),
                _row(2, {PREFIX_A: BAD_A}),
                _row(10.808, {PREFIX_A: GOOD_A}),
                _row(20, {PREFIX_A: GOOD_A}),
            ]
        )

        self.assertEqual(result.status, "PASS")
        self.assertTrue(any("8.808s" in note for note in result.notes))
        self.assertTrue(any("ignored 1" in note for note in result.notes))

    def test_recovery_beyond_30_seconds_fails(self):
        result = self._evaluate(
            [
                _row(-1, {PREFIX_A: GOOD_A}),
                _row(1, {PREFIX_A: BAD_A}),
                _row(32, {PREFIX_A: GOOD_A}),
            ]
        )

        self.assertEqual(result.status, "FAIL")
        self.assertTrue(
            any("> 30.0s SLA" in issue for issue in result.compliance_issues)
        )

    def test_no_valid_post_restart_data_fails(self):
        result = self._evaluate(
            [_row(-1, {PREFIX_A: GOOD_A}), _row(1, {}), _row(5, {})]
        )

        self.assertEqual(result.status, "FAIL")
        self.assertIn("no complete valid post-restart sample", result.compliance_issues)

    def test_no_complete_baseline_fails(self):
        result = self._evaluate([_row(1, {PREFIX_A: GOOD_A})], prefixes=[PREFIX_A])

        self.assertEqual(result.status, "FAIL")
        self.assertTrue(
            any(
                "no complete pre-restart baseline" in issue
                for issue in result.compliance_issues
            )
        )

    def test_no_full_recovery_fails(self):
        result = self._evaluate(
            [_row(-1, {PREFIX_A: GOOD_A}), _row(1, {PREFIX_A: BAD_A})]
        )

        self.assertEqual(result.status, "FAIL")
        self.assertTrue(
            any(
                "recovered all monitored prefixes" in issue
                for issue in result.compliance_issues
            )
        )

    def test_final_valid_sample_regression_fails(self):
        result = self._evaluate(
            [
                _row(-1, {PREFIX_A: GOOD_A}),
                _row(1, {PREFIX_A: BAD_A}),
                _row(5, {PREFIX_A: GOOD_A}),
                _row(10, {PREFIX_A: BAD_A}),
            ]
        )

        self.assertEqual(result.status, "FAIL")
        self.assertTrue(
            any(
                "final valid sample regressed" in issue
                for issue in result.compliance_issues
            )
        )

    def test_first_valid_sample_already_healthy_passes_at_zero_seconds(self):
        result = self._evaluate(
            [_row(-1, {PREFIX_A: GOOD_A}), _row(3, {PREFIX_A: GOOD_A})]
        )

        self.assertEqual(result.status, "PASS")
        self.assertTrue(any("0.000s" in note for note in result.notes))

    def test_multiple_prefixes_wait_for_slowest_full_recovery(self):
        result = self._evaluate(
            [
                _row(-1, {PREFIX_A: GOOD_A, PREFIX_B: GOOD_B}),
                _row(0.5, {PREFIX_A: BAD_A}),
                _row(1, {PREFIX_A: BAD_A, PREFIX_B: BAD_B}),
                _row(5, {PREFIX_A: GOOD_A, PREFIX_B: BAD_B}),
                _row(9, {PREFIX_A: GOOD_A, PREFIX_B: GOOD_B}),
            ]
        )

        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.n_prefixes, 2)
        self.assertTrue(any("8.000s" in note for note in result.notes))
        self.assertTrue(any("ignored 1" in note for note in result.notes))

    def test_pre_outage_race_sample_cannot_anchor_recovery(self):
        result = self._evaluate(
            [
                _row(-1, {PREFIX_A: GOOD_A}),
                _row(0.03, {PREFIX_A: GOOD_A}),
                _row(1, {}),
                _row(10, {PREFIX_A: BAD_A}),
                _row(25.338, {PREFIX_A: GOOD_A}),
            ],
            completion_offset=0.5,
        )

        self.assertEqual(result.status, "PASS")
        self.assertTrue(any("15.338s" in note for note in result.notes))

    def test_completion_marker_excludes_pre_completion_healthy_sample(self):
        result = self._evaluate(
            [
                _row(-1, {PREFIX_A: GOOD_A}),
                _row(0.03, {PREFIX_A: GOOD_A}),
                _row(8, {PREFIX_A: BAD_A}),
                _row(20, {PREFIX_A: GOOD_A}),
            ],
            completion_offset=5,
        )

        self.assertEqual(result.status, "PASS")
        self.assertTrue(any("12.000s" in note for note in result.notes))


if __name__ == "__main__":
    unittest.main()
