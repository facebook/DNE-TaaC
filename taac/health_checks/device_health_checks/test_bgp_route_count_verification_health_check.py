# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from neteng.netcastle.logger import ConsoleFileLogger
from taac.constants import TestDevice
from taac.health_checks.device_health_checks.bgp_route_count_verification_health_check import (
    BgpRouteCountVerificationHealthCheck,
)
from taac.health_check.health_check import types as hc_types


class BgpRouteCountVerificationHealthCheckTest(unittest.IsolatedAsyncioTestCase):
    def _health_check(
        self,
    ) -> tuple[BgpRouteCountVerificationHealthCheck, AsyncMock]:
        health_check = BgpRouteCountVerificationHealthCheck(
            logger=MagicMock(spec=ConsoleFileLogger)
        )
        driver = AsyncMock()
        health_check.driver = driver
        return health_check, driver

    async def test_bgp_inactive_falls_back_before_peer_group_resolution(self) -> None:
        health_check, driver = self._health_check()
        driver.async_execute_show_json_on_shell.side_effect = Exception("BGP inactive")
        device = MagicMock(spec=TestDevice)
        device.name = "dut.example.com"
        health_input = hc_types.BaseHealthCheckIn()
        expected = hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
        )

        with patch.object(
            health_check,
            "_run",
            new=AsyncMock(return_value=expected),
        ) as thrift_check:
            result = await health_check._run_arista(
                device,
                health_input,
                {
                    "exact_peer_group_names": ["EB-FA-V6", "EB-FA-V4"],
                    "expected_count": 750,
                },
            )

        self.assertEqual(expected, result)
        thrift_check.assert_awaited_once()
        driver.bgp.assert_not_awaited()

    async def test_raw_payload_rejects_mixed_peer_selectors(self) -> None:
        device = MagicMock(spec=TestDevice)
        device.name = "dut.example.com"
        health_input = hc_types.BaseHealthCheckIn()
        params = {
            "descriptions_to_check": ["EBGP"],
            "exact_peer_group_names": ["EB-FA-V6", "EB-FA-V4"],
            "expected_count": 750,
        }

        for method_name in ("_run", "_run_arista"):
            health_check, driver = self._health_check()
            with self.subTest(method_name=method_name):
                result = await getattr(health_check, method_name)(
                    device,
                    health_input,
                    params,
                )

            self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
            self.assertIn("mutually exclusive", result.message)
            driver.async_get_bgp_sessions.assert_not_awaited()
            driver.async_execute_show_json_on_shell.assert_not_awaited()

    async def test_exact_peer_groups_resolve_without_update_group_api(self) -> None:
        health_check, driver = self._health_check()
        bgp_helper = driver.bgp.return_value
        bgp_helper.async_get_running_config_struct.return_value = SimpleNamespace(
            peers=[
                SimpleNamespace(
                    peer_group_name="EB-FA-V6",
                    peer_addr="2001:db8::1",
                ),
                SimpleNamespace(
                    peer_group_name="EB-FA-V4",
                    peer_addr="192.0.2.1",
                ),
            ],
        )
        bgp_helper.async_get_update_group_info = AsyncMock()

        selected = await health_check._resolve_peer_group_addresses(
            "dut.example.com",
            ["EB-FA-V6", "EB-FA-V4"],
        )

        self.assertEqual({"2001:db8::1", "192.0.2.1"}, selected)
        driver.bgp.assert_awaited_once_with()
        bgp_helper.async_get_running_config_struct.assert_awaited_once_with()
        bgp_helper.async_get_update_group_info.assert_not_awaited()

    async def test_exact_peer_group_failure_includes_config_diagnostics(
        self,
    ) -> None:
        health_check, driver = self._health_check()
        bgp_helper = driver.bgp.return_value
        bgp_helper.async_get_running_config_struct.return_value = SimpleNamespace(
            peers=[
                SimpleNamespace(
                    peer_group_name="EB-FA-V6",
                    peer_addr="2001:db8::1",
                )
            ],
        )

        with self.assertRaises(RuntimeError) as error:
            await health_check._resolve_peer_group_addresses(
                "dut.example.com",
                ["EB-FA-V6", "EB-FA-V4"],
            )

        message = str(error.exception)
        self.assertIn("missing=['EB-FA-V4']", message)
        self.assertIn("observed=['EB-FA-V6']", message)
        self.assertIn("configured_peers=1", message)

    async def test_arista_exact_selector_reports_no_matching_peers_as_error(
        self,
    ) -> None:
        health_check, driver = self._health_check()
        driver.async_execute_show_json_on_shell.return_value = {
            "vrfs": {
                "default": {
                    "peers": {
                        "2001:db8::9": {
                            "description": "unselected",
                            "peerState": "Established",
                            "prefixReceived": 750,
                        }
                    }
                }
            }
        }
        device = MagicMock(spec=TestDevice)
        device.name = "dut.example.com"

        with patch.object(
            health_check,
            "_resolve_peer_group_addresses",
            new=AsyncMock(return_value={"2001:db8::1"}),
        ):
            result = await health_check._run_arista(
                device,
                hc_types.BaseHealthCheckIn(),
                {
                    "exact_peer_group_names": ["EB-FA-V6", "EB-FA-V4"],
                    "expected_count": 750,
                },
            )

        self.assertEqual(hc_types.HealthCheckStatus.ERROR, result.status)
        self.assertIn("No established peers matched", result.message or "")
