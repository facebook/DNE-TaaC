# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

from __future__ import annotations

import argparse
import os
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from taac.utils.driver_compatibility_checker.netos_healthcheck_compatibility_checker import (
    CheckStatus,
    DeviceResult,
    FbossOsType,
    FbossSystemctlServiceName,
    run_checks,
    run_device_checks,
)


class _FakeDriver:
    def __init__(
        self,
        *,
        route_events_available: bool = True,
        delete_events_available: bool = True,
    ) -> None:
        self.route_events_available = route_events_available
        self.delete_events_available = delete_events_available
        self.restart_calls: list[str] = []
        self.log_reads = 0

    async def async_get_fboss_os_type(self) -> FbossOsType:
        return FbossOsType.NETOS_NATIVE

    async def async_get_log_source_command(
        self, log_file_path: str, start_time: str | None = None
    ) -> str:
        return f"journalctl --since '{start_time}' -u netos.service.fboss_sw_agent"

    async def async_read_log_file(
        self,
        log_file_path: str,
        *,
        start_time: int | None = None,
        end_time: int | None = None,
        grep_pattern: str | None = None,
        tail_lines: int | None = None,
    ) -> str:
        self.log_reads += 1
        return "I0924 20:00:00.000001 1 SwSwitch.cpp:1] healthy\n"

    async def async_get_systemctl_service_name(self, service: object) -> str:
        return f"netos.service.fboss_{str(service)}"

    async def async_run_cmd_on_shell(self, command: str) -> str:
        if command.startswith("systemctl show"):
            return "LoadState=loaded\nActiveState=active\nSubState=running\n"
        if "awk -v start=" in command:
            if not self.route_events_available:
                return "NONE\n"
            if "total_added" in command and "added > 0" in command:
                return "METRICS 120 0 2 1.000000 20:00:00.000001 20:00:01.000001\n"
            if not self.delete_events_available:
                return "NONE\n"
            return "METRICS 0 120 2 1.000000 20:00:00.000001 20:00:01.000001\n"
        if "tail -n 1" in command:
            return "I0924 20:00:00.000001 1 SwSwitch.cpp:1] healthy\n"
        return ""

    async def async_restart_service(self, service: FbossSystemctlServiceName) -> None:
        self.restart_calls.append(str(service))
        self.route_events_available = True

    async def async_wait_for_bgp_convergence(self, timeout: int) -> None:
        return None


class NetosHealthcheckCompatibilityCheckerTest(unittest.IsolatedAsyncioTestCase):
    @patch(
        "neteng.test_infra.dne.taac.utils.driver_compatibility_checker."
        "netos_healthcheck_compatibility_checker."
        "run_device_checks",
        new_callable=AsyncMock,
    )
    @patch(
        "neteng.test_infra.dne.taac.utils.driver_compatibility_checker."
        "netos_healthcheck_compatibility_checker."
        "async_get_device_driver",
        new_callable=AsyncMock,
    )
    async def test_run_checks_forces_lab_ssh_before_creating_driver(
        self,
        get_driver: AsyncMock,
        run_device: AsyncMock,
    ) -> None:
        get_driver.return_value = _FakeDriver()
        run_device.return_value = DeviceResult(
            hostname="native.example",
            os_type="native_netos",
            checks=(),
        )
        args = argparse.Namespace(
            device=["native.example"],
            lookback_seconds=3600,
            generate_route_events=False,
            timeout=300,
        )

        with patch.dict("os.environ", {}, clear=True):
            await run_checks(args)
            self.assertEqual("1", os.environ["TAAC_SSH_VIA_LAB_SSH"])

        get_driver.assert_awaited_once_with("native.example")

    async def test_runs_all_live_healthcheck_paths(self) -> None:
        driver = _FakeDriver()

        result = await run_device_checks(
            "native.example",
            driver,
            now=datetime(2026, 9, 24, 20, 30),
            lookback_seconds=3600,
            generate_route_events=False,
        )

        self.assertEqual("native_netos", result.os_type)
        self.assertEqual(
            {
                "journal_mapping": CheckStatus.PASS,
                "log_parsing": CheckStatus.PASS,
                "route_convergence": CheckStatus.PASS,
                "service_health": CheckStatus.PASS,
            },
            {check.name: check.status for check in result.checks},
        )
        self.assertEqual(1, driver.log_reads)
        self.assertEqual([], driver.restart_calls)

    async def test_generates_route_events_only_when_requested_and_missing(self) -> None:
        driver = _FakeDriver(route_events_available=False)

        result = await run_device_checks(
            "native.example",
            driver,
            now=datetime(2026, 9, 24, 20, 30),
            lookback_seconds=3600,
            generate_route_events=True,
        )

        route_result = next(
            check for check in result.checks if check.name == "route_convergence"
        )
        self.assertEqual(CheckStatus.PASS, route_result.status)
        self.assertEqual(1, len(driver.restart_calls))

    async def test_route_parser_passes_when_only_add_events_exist(self) -> None:
        driver = _FakeDriver(delete_events_available=False)

        result = await run_device_checks(
            "native.example",
            driver,
            now=datetime(2026, 9, 24, 20, 30),
            lookback_seconds=3600,
            generate_route_events=False,
        )

        route_result = next(
            check for check in result.checks if check.name == "route_convergence"
        )
        self.assertEqual(CheckStatus.PASS, route_result.status)
        self.assertIn("missing=DELETE", route_result.details)


if __name__ == "__main__":
    unittest.main()
