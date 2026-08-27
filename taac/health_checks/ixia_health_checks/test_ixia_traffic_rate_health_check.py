# Copyright (c) Meta Platforms, Inc. and affiliates.

import typing as t
from unittest.mock import MagicMock

from later.unittest import TestCase
from taac.health_checks.ixia_health_checks.ixia_traffic_rate_health_check import (
    IxiaTrafficRateHealthCheck,
)
from taac.utils.oss_taac_lib_utils import ConsoleFileLogger
from taac.health_check.health_check import types as hc_types


class IxiaTrafficRateHealthCheckTest(TestCase):
    def setUp(self) -> None:
        self.health_check = IxiaTrafficRateHealthCheck(
            logger=MagicMock(spec=ConsoleFileLogger)
        )
        self.threshold = hc_types.TrafficRateThreshold(
            names=["RDMA"],
            value=90,
            threshold_type=hc_types.ThresholdType.PERCENT,
            metric=hc_types.TrafficRateMetric.TX_RATE,
        )

    def _violations(self, tx_gbps: float, rx_gbps: float) -> list[dict[str, t.Any]]:
        return self.health_check.verify_traffic_rate_threshold(
            [
                {
                    "identifier": "RDMA",
                    "Tx Rate": tx_gbps * 1000,
                    "Rx Rate": rx_gbps * 1000,
                }
            ],
            self.threshold,
            base_bandwidth_gbps=200,
            rate_tolerance_percent=10,
        )

    def test_expected_rate_within_tolerance_passes(self) -> None:
        self.assertEqual([], self._violations(tx_gbps=180, rx_gbps=180))

    def test_tolerance_boundaries_are_inclusive(self) -> None:
        self.assertEqual([], self._violations(tx_gbps=162, rx_gbps=198))

    def test_rate_below_tolerance_fails(self) -> None:
        violations = self._violations(tx_gbps=161.9, rx_gbps=180)

        self.assertEqual(1, len(violations))
        self.assertAlmostEqual(162, violations[0]["Minimum Rate (Gbps)"])
        self.assertAlmostEqual(198, violations[0]["Maximum Rate (Gbps)"])

    def test_rate_above_tolerance_fails(self) -> None:
        violations = self._violations(tx_gbps=180, rx_gbps=198.1)

        self.assertEqual(1, len(violations))

    def test_invalid_tolerance_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "between 0 and 100"):
            self.health_check.verify_traffic_rate_threshold(
                [],
                self.threshold,
                base_bandwidth_gbps=200,
                rate_tolerance_percent=101,
            )

    async def test_run_rejects_invalid_tolerance_from_check_params(self) -> None:
        ixia = MagicMock()
        ixia.has_traffic_items.return_value = True
        ixia.get_latest_stats_traffic.return_value = []

        result = await self.health_check._run(
            ixia,
            hc_types.IxiaTrafficRateHealthCheckIn(thresholds=[self.threshold]),
            {"rate_tolerance_percent": 101},
        )

        self.assertEqual(hc_types.HealthCheckStatus.ERROR, result.status)
        self.assertIn("between 0 and 100", result.message or "")

    def test_legacy_lower_bound_violation_omits_maximum(self) -> None:
        violations = self.health_check.verify_traffic_rate_threshold(
            [
                {
                    "identifier": "RDMA",
                    "Tx Rate": 170_000,
                    "Rx Rate": 180_000,
                }
            ],
            self.threshold,
            base_bandwidth_gbps=200,
        )

        self.assertEqual(1, len(violations))
        self.assertNotIn("Maximum Rate (Gbps)", violations[0])
