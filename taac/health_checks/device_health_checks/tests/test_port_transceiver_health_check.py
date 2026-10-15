# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import unittest
from unittest.mock import AsyncMock, MagicMock

from taac.constants import TestDevice
from taac.health_checks.device_health_checks.port_transceiver_health_check import (
    PortTransceiverHealthCheck,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types


def _make_device(name: str, interfaces: list) -> MagicMock:
    device = MagicMock(spec=TestDevice)
    device.name = name
    device.interfaces = interfaces
    return device


def _make_test_interface(
    interface_name: str, switch_name: str
) -> taac_types.TestInterface:
    return taac_types.TestInterface(
        interface_name=interface_name,
        switch_name=switch_name,
    )


def _make_transceiver_info(present: bool) -> MagicMock:
    info = MagicMock()
    info.tcvrState.present = present
    return info


class PortTransceiverHealthCheckTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.logger = MagicMock()
        self.health_check = PortTransceiverHealthCheck(logger=self.logger)
        self.health_check.driver = AsyncMock()
        self.input = hc_types.BaseHealthCheckIn()

    async def test_skips_when_device_has_no_interfaces(self) -> None:
        device = _make_device("dut1", [])
        result = await self.health_check._run(device, self.input, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.SKIP)
        self.health_check.driver.async_get_all_interface_to_qsfp_info_mapping.assert_not_awaited()

    async def test_passes_when_transceiver_present(self) -> None:
        device = _make_device(
            "dut1", [_make_test_interface("eth1/1/1", "dut1")]
        )
        self.health_check.driver.async_get_all_interface_to_qsfp_info_mapping.return_value = {
            "eth1/1/1": _make_transceiver_info(present=True)
        }
        result = await self.health_check._run(device, self.input, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_fails_when_transceiver_absent(self) -> None:
        device = _make_device(
            "dut1", [_make_test_interface("eth1/1/1", "dut1")]
        )
        self.health_check.driver.async_get_all_interface_to_qsfp_info_mapping.return_value = {
            "eth1/1/1": _make_transceiver_info(present=False)
        }
        result = await self.health_check._run(device, self.input, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("eth1/1/1", result.message or "")

    async def test_fails_when_transceiver_missing_from_mapping(self) -> None:
        device = _make_device(
            "dut1", [_make_test_interface("eth1/1/1", "dut1")]
        )
        self.health_check.driver.async_get_all_interface_to_qsfp_info_mapping.return_value = {}
        result = await self.health_check._run(device, self.input, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)

    async def test_passes_when_absence_expected_and_confirmed(self) -> None:
        device = _make_device("dut1", [])
        self.health_check.driver.async_get_all_interface_to_qsfp_info_mapping.return_value = {
            "eth1/1/1": _make_transceiver_info(present=False)
        }
        result = await self.health_check._run(
            device,
            self.input,
            {"interfaces": ["eth1/1/1"], "expected_present": False},
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_fails_when_absence_expected_but_still_present(self) -> None:
        device = _make_device("dut1", [])
        self.health_check.driver.async_get_all_interface_to_qsfp_info_mapping.return_value = {
            "eth1/1/1": _make_transceiver_info(present=True)
        }
        result = await self.health_check._run(
            device,
            self.input,
            {"interfaces": ["eth1/1/1"], "expected_present": False},
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("eth1/1/1", result.message or "")

    async def test_explicit_interfaces_narrows_instead_of_widening(self) -> None:
        # Snake circuits: both ends share a hostname, so `obj.interfaces` has
        # several present, healthy ports. Pulling one transceiver and passing
        # only that interface must not assert absence on the others too.
        device = _make_device(
            "dut1",
            [
                _make_test_interface("eth1/1/1", "dut1"),
                _make_test_interface("eth1/64/5", "dut1"),
            ],
        )
        self.health_check.driver.async_get_all_interface_to_qsfp_info_mapping.return_value = {
            "eth1/1/1": _make_transceiver_info(present=False),
            "eth1/64/5": _make_transceiver_info(present=True),
        }
        result = await self.health_check._run(
            device,
            self.input,
            {"interfaces": ["eth1/1/1"], "expected_present": False},
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
