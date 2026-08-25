# Copyright (c) Meta Platforms, Inc. and affiliates.

"""Unit tests for OpenrSparkNeighborHealthCheck."""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock

from neteng.netcastle.logger import ConsoleFileLogger
from taac.constants import TestDevice
from taac.health_checks.device_health_checks.openr_spark_neighbor_health_check import (
    OpenrSparkNeighborHealthCheck,
)
from taac.health_checks.healthcheck_definitions import (
    create_openr_spark_neighbor_check,
)
from taac.health_check.health_check import types as hc_types


def _neighbor(
    node_name: str, state: str = "ESTABLISHED", local_if_name: str = "po1910.1"
) -> MagicMock:
    """Build a fake Spark neighbor exposing .nodeName, .state, .localIfName."""
    neighbor = MagicMock()
    neighbor.nodeName = node_name
    neighbor.state = state
    neighbor.localIfName = local_if_name
    return neighbor


class TestOpenrSparkNeighborHealthCheck(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.logger = MagicMock(spec=ConsoleFileLogger)
        self.health_check = OpenrSparkNeighborHealthCheck(logger=self.logger)
        self.health_check.driver = AsyncMock()
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "eb04.lab.ash6"
        # Empty so expected count is not derived from topology unless requested.
        self.device.interfaces = []
        self.input = hc_types.BaseHealthCheckIn()

    async def test_exact_count_all_established_returns_pass(self):
        """N ESTABLISHED neighbors matching expected_neighbor_count → PASS."""
        self.health_check.driver.async_get_openr_spark_neighbors.return_value = [
            _neighbor("eb02.lab.ash6-1"),
            _neighbor("eb02.lab.ash6-2"),
            _neighbor("eb02.lab.ash6-3"),
        ]
        result = await self.health_check._run(
            self.device, self.input, {"expected_neighbor_count": 3}
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_count_mismatch_returns_fail(self):
        """Fewer ESTABLISHED neighbors than expected → FAIL."""
        self.health_check.driver.async_get_openr_spark_neighbors.return_value = [
            _neighbor("eb02.lab.ash6-1"),
            _neighbor("eb02.lab.ash6-2"),
        ]
        result = await self.health_check._run(
            self.device, self.input, {"expected_neighbor_count": 3}
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("found 2", result.message)

    async def test_non_established_neighbor_returns_fail(self):
        """A neighbor not in ESTABLISHED state → FAIL naming the state."""
        self.health_check.driver.async_get_openr_spark_neighbors.return_value = [
            _neighbor("eb02.lab.ash6-1"),
            _neighbor("eb02.lab.ash6-2", state="RESTART"),
        ]
        result = await self.health_check._run(
            self.device, self.input, {"expected_neighbor_count": 2}
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("RESTART", result.message)

    async def test_allow_zero_with_no_neighbors_returns_pass(self):
        """allow_zero=True with 0 neighbors → PASS."""
        self.health_check.driver.async_get_openr_spark_neighbors.return_value = []
        result = await self.health_check._run(
            self.device, self.input, {"allow_zero": True}
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)


class TestCreateOpenrSparkNeighborCheckFactory(unittest.TestCase):
    def test_json_payload_matches_expected(self):
        """Factory serializes params into the JSON payload that _run reads."""
        check = create_openr_spark_neighbor_check(
            expected_neighbor_count=42,
            retry_count=5,
        )
        self.assertEqual(check.name, hc_types.CheckName.OPENR_SPARK_NEIGHBOR_CHECK)
        payload = json.loads(check.check_params.json_params)
        self.assertEqual(
            payload,
            {"expected_neighbor_count": 42, "retry_count": 5},
        )


if __name__ == "__main__":
    unittest.main()
