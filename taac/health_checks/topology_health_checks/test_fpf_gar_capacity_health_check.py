# Copyright (c) Meta Platforms, Inc. and affiliates.

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from neteng.netcastle.logger import ConsoleFileLogger
from taac.constants import TestTopology
from taac.health_checks.topology_health_checks.fpf_gar_capacity_health_check import (
    FpfGarScaleCapacityHealthCheck,
    FpfGarVfCapacityHealthCheck,
)
from taac.health_check.health_check import types as hc_types


class TestFpfGarCapacityHealthCheck(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.logger = MagicMock(spec=ConsoleFileLogger)
        self.topology = MagicMock(spec=TestTopology)
        self.input = hc_types.BaseHealthCheckIn()

    async def test_vf_passes_through_shared_evaluator(self) -> None:
        check = FpfGarVfCapacityHealthCheck(logger=self.logger)
        with patch(
            "neteng.test_infra.dne.taac.health_checks.topology_health_checks."
            "fpf_gar_capacity_health_check.wait_for_gar_prefixes",
            new=AsyncMock(return_value=["remote capacity=35"]),
        ):
            result = await check._run(
                self.topology,
                self.input,
                {
                    "pairs": [{"name": "pair-A"}],
                    "prefixes": ["2401:db00::/64"],
                },
            )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("remote capacity=35", result.message or "")

    async def test_scale_failure_is_a_health_check_failure(self) -> None:
        check = FpfGarScaleCapacityHealthCheck(logger=self.logger)
        with patch(
            "neteng.test_infra.dne.taac.health_checks.topology_health_checks."
            "fpf_gar_capacity_health_check.wait_for_gar_pairs",
            new=AsyncMock(side_effect=RuntimeError("remote GAR weight is 36")),
        ):
            result = await check._run(
                self.topology,
                self.input,
                {
                    "pairs": [{"name": "pair-A"}],
                    "prefix_base": "5000:ca::/64",
                    "prefix_count": 1000,
                },
            )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("remote GAR weight is 36", result.message or "")


if __name__ == "__main__":
    unittest.main()
