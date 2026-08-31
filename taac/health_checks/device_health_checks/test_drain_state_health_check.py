# Copyright (c) Meta Platforms, Inc. and affiliates.

import typing as t
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from taac.constants import TestDevice
from taac.driver.driver_constants import DeviceDrainState
from taac.health_checks.device_health_checks.drain_state_health_check import (
    DrainStateHealthCheck,
)
from taac.health_check.health_check import types as hc_types


class DrainStateHealthCheckTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.check = DrainStateHealthCheck(logger=MagicMock())
        self.check.driver = SimpleNamespace(_async_is_onbox_drained_helper=AsyncMock())
        self.device = t.cast(
            TestDevice,
            SimpleNamespace(name="gtsw001.l1002.c087.mwg2"),
        )

    async def test_expected_drained_passes(self) -> None:
        self.check.driver._async_is_onbox_drained_helper.return_value = (
            DeviceDrainState.DRAINED
        )

        result = await self.check._run(
            self.device,
            hc_types.BaseHealthCheckIn(),
            {"expected_drained": True},
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_expected_undrained_fails_when_drained(self) -> None:
        self.check.driver._async_is_onbox_drained_helper.return_value = (
            DeviceDrainState.DRAINED
        )

        result = await self.check._run(
            self.device,
            hc_types.BaseHealthCheckIn(),
            {"expected_drained": False},
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("expected undrained", result.message or "")

    async def test_device_scope_skips_other_devices(self) -> None:
        result = await self.check._run(
            self.device,
            hc_types.BaseHealthCheckIn(),
            {"device_name": "gtsw002.l1002.c087.mwg2"},
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.SKIP)
        self.check.driver._async_is_onbox_drained_helper.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
