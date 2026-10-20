# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from taac.constants import TestDevice
from taac.health_checks.device_health_checks.l2_entry_threshold_health_check import (
    L2EntryThresholdHealthCheck,
)
from taac.health_check.health_check import types as hc_types


class L2EntryThresholdObserveDeadlineTest(unittest.IsolatedAsyncioTestCase):
    async def test_ndp_observation_that_hangs_is_bounded_and_nonfatal(self) -> None:
        async def hang() -> list:
            await asyncio.sleep(3600)
            return []

        check = L2EntryThresholdHealthCheck(logger=MagicMock())
        check.driver = AsyncMock()
        check.driver.async_get_ndp_table.side_effect = hang
        device = MagicMock(spec=TestDevice)
        device.name = "test-host"
        empty = hc_types.BaseHealthCheckIn()

        with patch(
            "taac.health_checks.device_health_checks.l2_entry_threshold_health_check.DEFAULT_THRIFT_TIMEOUT",
            0.01,
        ):
            result = await asyncio.wait_for(
                check.run(
                    device,
                    empty,
                    empty,
                    {
                        "ndp_entry_observe_only": True,
                        "retry_count": 1,
                        "retry_delay_seconds": 0,
                    },
                ),
                10,
            )

        self.assertEqual(2, check.driver.async_get_ndp_table.await_count)
        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertIn("timed out", result.message or "")
