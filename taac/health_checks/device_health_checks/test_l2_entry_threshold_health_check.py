# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import unittest
from unittest.mock import AsyncMock, MagicMock

from neteng.netcastle.logger import ConsoleFileLogger
from taac.constants import TestDevice
from taac.health_checks.device_health_checks.l2_entry_threshold_health_check import (
    L2EntryThresholdHealthCheck,
)
from taac.health_checks.healthcheck_definitions import (
    create_l2_entry_threshold_check,
)
from taac.health_check.health_check import types as hc_types


class L2EntryThresholdHealthCheckTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.logger = MagicMock(spec=ConsoleFileLogger)
        self.health_check = L2EntryThresholdHealthCheck(logger=self.logger)
        self.health_check.driver = AsyncMock()
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "test-host"
        self.input = hc_types.BaseHealthCheckIn()

    async def test_ndp_observation_requires_rpc_but_does_not_assert_count(self) -> None:
        self.health_check.driver.async_get_ndp_table.return_value = list(range(40_000))

        result = await self.health_check._run(
            self.device,
            self.input,
            {"ndp_entry_observe_only": True},
        )

        self.health_check.driver.async_get_ndp_table.assert_awaited_once()
        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertIn("40000", result.message or "")

    async def test_ndp_observation_retries_transient_rpc_timeout(self) -> None:
        self.health_check.driver.async_get_ndp_table.side_effect = [
            TimeoutError("getNdpTable timed out"),
            [],
        ]

        result = await self.health_check.run(
            self.device,
            self.input,
            self.input,
            {
                "ndp_entry_observe_only": True,
                "retry_count": 1,
                "retry_delay_seconds": 0,
            },
        )

        self.assertEqual(2, self.health_check.driver.async_get_ndp_table.await_count)
        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)

    async def test_ndp_observation_timeout_is_nonfatal_after_retries(self) -> None:
        self.health_check.driver.async_get_ndp_table.side_effect = TimeoutError(
            "getNdpTable timed out"
        )

        result = await self.health_check.run(
            self.device,
            self.input,
            self.input,
            {
                "ndp_entry_observe_only": True,
                "retry_count": 2,
                "retry_delay_seconds": 0,
            },
        )

        self.assertEqual(3, self.health_check.driver.async_get_ndp_table.await_count)
        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertIn("observe-only RPC unavailable", result.message or "")

    def test_observation_factory_encodes_required_ndp_rpc_retries(self) -> None:
        check = create_l2_entry_threshold_check(
            ndp_entry_observe_only=True,
            retry_count=4,
            retry_delay_seconds=3,
        )

        self.assertIsNotNone(check.check_params)
        params = __import__("json").loads(
            check.check_params.json_params if check.check_params else "{}"
        )
        self.assertTrue(params["ndp_entry_observe_only"])
        self.assertEqual(4, params["retry_count"])
        self.assertEqual(3, params["retry_delay_seconds"])


if __name__ == "__main__":
    unittest.main()
