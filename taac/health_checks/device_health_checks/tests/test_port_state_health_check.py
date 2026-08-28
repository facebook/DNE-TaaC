# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from neteng.netcastle.logger import ConsoleFileLogger
from taac.constants import TestDevice
from taac.health_checks.device_health_checks.port_state_health_check import (
    PortStateHealthCheck,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types


_MODULE = (
    "neteng.test_infra.dne.taac.health_checks.device_health_checks"
    ".port_state_health_check"
)


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


class PortStateHealthCheckSkipTest(unittest.IsolatedAsyncioTestCase):
    """A check that examines no interface must not report PASS.

    `TestDevice.interfaces` is only populated for links whose neighbor is also a
    declared endpoint, so a single-endpoint TestConfig leaves it empty and every
    validation loop becomes a no-op. This previously returned PASS: observed on
    bag001.snc1, which passed at PRE_TEST while it had 0 links up.
    """

    def setUp(self) -> None:
        self.logger = MagicMock(spec=ConsoleFileLogger)
        self.health_check = PortStateHealthCheck(logger=self.logger)
        self.health_check.driver = AsyncMock()
        self.input = hc_types.BaseHealthCheckIn()

    async def test_skips_when_device_has_no_interfaces(self) -> None:
        device = _make_device("bag001.snc1", [])
        result = await self.health_check._run(device, self.input, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.SKIP)
        self.assertIsNotNone(result.message)
        self.assertIn("asserted nothing", result.message or "")
        # The device must not even be queried when there is nothing to check.
        self.health_check.driver.async_get_all_interfaces_operational_status.assert_not_awaited()

    async def test_does_not_skip_when_additional_interfaces_given(self) -> None:
        """`additional_interfaces` is a real expectation source, so honour it."""
        device = _make_device("bag001.snc1", [])
        self.health_check.driver.async_get_all_interfaces_operational_status.return_value = {
            "Ethernet5/1/1": True
        }
        self.health_check.driver.async_get_all_interfaces_admin_status.return_value = {
            "Ethernet5/1/1": True
        }
        result = await self.health_check._run(
            device,
            self.input,
            {
                "additional_interfaces": [
                    {"switch_name": "bag001.snc1", "interface_name": "Ethernet5/1/1"}
                ]
            },
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_passes_when_topology_interface_is_up(self) -> None:
        """The SKIP guard must not change behaviour when there is work to do."""
        device = _make_device(
            "bag001.snc1", [_make_test_interface("Ethernet5/1/1", "bag001.snc1")]
        )
        self.health_check.driver.async_get_all_interfaces_operational_status.return_value = {
            "Ethernet5/1/1": True
        }
        result = await self.health_check._run(device, self.input, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_fails_when_topology_interface_is_down(self) -> None:
        """The case that matters: a real expectation, and the link is down.

        This check RETURNS a FAIL result rather than raising, so assert on the
        status. `async_everpaste_str` is patched because it needs network, which
        the test target disallows.
        """
        device = _make_device(
            "bag001.snc1", [_make_test_interface("Ethernet5/1/1", "bag001.snc1")]
        )
        self.health_check.driver.async_get_all_interfaces_operational_status.return_value = {
            "Ethernet5/1/1": False
        }
        with patch(
            f"{_MODULE}.async_everpaste_str",
            AsyncMock(return_value="https://everpaste"),
        ):
            result = await self.health_check._run(device, self.input, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("Ethernet5/1/1", result.message or "")
