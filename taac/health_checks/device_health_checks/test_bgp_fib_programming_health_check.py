# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from neteng.netcastle.logger import ConsoleFileLogger
from taac.constants import TestDevice
from taac.health_checks.device_health_checks import (
    bgp_fib_programming_health_check as health_check_module,
)
from taac.health_checks.device_health_checks.bgp_fib_programming_health_check import (
    BgpFibProgrammingCheck,
)
from taac.health_check.health_check import types as hc_types


class BgpFibProgrammingCheckTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.health_check = BgpFibProgrammingCheck(
            logger=MagicMock(spec=ConsoleFileLogger)
        )
        self.health_check.driver = AsyncMock()
        self.health_check.driver.async_read_file.return_value = "active BGP log"
        self.device = MagicMock(spec=TestDevice)
        self.input = hc_types.BaseHealthCheckIn()

    async def test_forwards_time_window_to_archive_reader(self) -> None:
        with (
            patch.object(
                health_check_module.arista_utils,
                "get_daemon_pid",
                new=AsyncMock(return_value="26775"),
            ),
            patch.object(
                health_check_module.arista_utils,
                "get_archived_agent_logs",
                new=AsyncMock(return_value="archived BGP log"),
            ) as archived_logs,
            patch.object(
                self.health_check,
                "_parse_convergence_time",
                new=AsyncMock(return_value=1.0),
            ),
        ):
            result = await self.health_check._run_arista(
                self.device,
                self.input,
                {"start_time": 100, "end_time": 200},
            )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        archived_logs.assert_awaited_once_with(
            self.health_check.driver,
            "Bgp",
            "26775",
            start_time=100,
            end_time=200,
        )
