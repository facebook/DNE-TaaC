# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""Tests for HRT remote-failure stable-state recovery modes."""

import unittest

from taac.libs.fpf.fpf_stress_checks import (
    HrtRemoteFailureCollector,
    HrtRemoteFailureRow,
)


class TestFpfRemoteFailureStable(unittest.TestCase):
    def _collector(self, counts: list[int]) -> HrtRemoteFailureCollector:
        collector = HrtRemoteFailureCollector(hosts=[])
        collector.rows = [
            HrtRemoteFailureRow(
                timestamp=f"2026-08-30T22:00:0{index}+00:00",
                host="twshared1352.03.mwg2",
                device_id=0,
                lane_counts=[count, 0, 0, 0, 0, 0, 0, 0],
                unique=count,
            )
            for index, count in enumerate(counts)
        ]
        return collector

    def test_strict_zero_baseline_passes_when_every_sample_matches(self):
        results = self._collector([0, 0, 0]).evaluate_per_lane_stable(lanes=[0])

        self.assertTrue(results[0].passed)
        self.assertEqual(results[0].expected, 0)

    def test_last_sample_mode_accepts_recovery_to_zero_baseline(self):
        results = self._collector([4032, 0]).evaluate_per_lane_stable(
            lanes=[0],
            last_sample_only=True,
        )

        self.assertTrue(results[0].passed)


if __name__ == "__main__":
    unittest.main()
