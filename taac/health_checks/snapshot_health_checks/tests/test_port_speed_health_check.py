# Copyright (c) Meta Platforms, Inc. and affiliates.

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from taac.constants import TestDevice
from taac.health_checks.constants import Snapshot
from taac.health_checks.snapshot_health_checks.port_speed_health_check import (
    PortSpeedHealtchCheck,
)
from taac.utils.oss_taac_lib_utils import ConsoleFileLogger
from pyre_extensions import none_throws
from taac.health_check.health_check import types as hc_types


_HOSTNAME = "switch.example"


class PortSpeedSnapshotHealthCheckTest(unittest.IsolatedAsyncioTestCase):
    async def _compare(
        self, pre: dict[str, int], post: dict[str, int]
    ) -> hc_types.HealthCheckResult:
        device = MagicMock(spec=TestDevice)
        device.name = _HOSTNAME
        check = PortSpeedHealtchCheck(
            obj=device,
            input=hc_types.BaseHealthCheckIn(),
            pre_snapshot_checkpoint_id="pre",
            post_snapshot_checkpoint_id="post",
            check_params={},
            logger=MagicMock(spec=ConsoleFileLogger),
        )
        return await check.compare_snapshots(
            obj=device,
            input=hc_types.BaseHealthCheckIn(),
            check_params={},
            pre_snapshot=Snapshot(data=pre, timestamp=1),
            post_snapshot=Snapshot(data=post, timestamp=2),
        )

    async def test_unchanged_speeds_pass(self) -> None:
        result = await self._compare(
            {"eth1/1/1": 200, "eth1/1/5": 200}, {"eth1/1/1": 200, "eth1/1/5": 200}
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_changed_speed_reports_gbps_values(self) -> None:
        result = await self._compare({"eth1/1/1": 200}, {"eth1/1/1": 100})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn(
            "Speed Before Test: 200G and Speed After Test: 100G",
            none_throws(result.message),
        )

    async def test_missing_post_port_fails(self) -> None:
        result = await self._compare({"eth1/1/1": 200}, {"eth1/1/5": 200})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn(
            "Port eth1/1/1 not found in post snapshot", none_throws(result.message)
        )
