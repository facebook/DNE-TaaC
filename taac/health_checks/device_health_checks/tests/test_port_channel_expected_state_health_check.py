# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""Unit tests for PortChannelExpectedStateHealthCheck."""

import unittest
from unittest.mock import AsyncMock, MagicMock

from neteng.netcastle.logger import ConsoleFileLogger
from taac.constants import TestDevice
from taac.health_checks.device_health_checks.port_channel_expected_state_health_check import (
    PortChannelExpectedStateHealthCheck,
)
from taac.health_check.health_check import types as hc_types


class TestPortChannelExpectedStateHealthCheckFBOSS(
    unittest.IsolatedAsyncioTestCase,
):
    def setUp(self):
        self.logger = MagicMock(spec=ConsoleFileLogger)
        self.health_check = PortChannelExpectedStateHealthCheck(logger=self.logger)
        self.health_check.driver = AsyncMock()
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "rsw001.p001.f01.ash6"
        self.device.attributes = MagicMock()
        self.device.attributes.operating_system = "FBOSS"
        self.input = hc_types.BaseHealthCheckIn()

    async def test_port_channel_up_expected_up_returns_pass(self):
        """FBOSS: Port channel UP when expected UP should return PASS."""
        pc = MagicMock()
        pc.name = "Port-Channel1"
        pc.isUp = True
        self.health_check.driver.async_get_all_aggregated_port_info = AsyncMock(
            return_value=[pc]
        )
        result = await self.health_check._run(
            self.device,
            self.input,
            {"port_channel_names": {"rsw001.p001.f01.ash6": "Port-Channel1"}},
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("as expected", result.message)

    async def test_port_channel_down_expected_up_returns_fail(self):
        """FBOSS: Port channel DOWN when expected UP should return FAIL."""
        pc = MagicMock()
        pc.name = "Port-Channel1"
        pc.isUp = False
        self.health_check.driver.async_get_all_aggregated_port_info = AsyncMock(
            return_value=[pc]
        )
        result = await self.health_check._run(
            self.device,
            self.input,
            {"port_channel_names": {"rsw001.p001.f01.ash6": "Port-Channel1"}},
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("expected UP but is DOWN", result.message)

    async def test_port_channel_not_found_returns_fail(self):
        """FBOSS: Port channel not found should return FAIL."""
        self.health_check.driver.async_get_all_aggregated_port_info = AsyncMock(
            return_value=[]
        )
        result = await self.health_check._run(
            self.device,
            self.input,
            {"port_channel_names": {"rsw001.p001.f01.ash6": "Port-Channel99"}},
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("not found", result.message)

    async def test_port_channel_down_expected_down_returns_pass(self):
        """FBOSS: Port channel DOWN when expected DOWN should return PASS."""
        pc = MagicMock()
        pc.name = "Port-Channel1"
        pc.isUp = False
        self.health_check.driver.async_get_all_aggregated_port_info = AsyncMock(
            return_value=[pc]
        )
        result = await self.health_check._run(
            self.device,
            self.input,
            {
                "port_channel_names": {"rsw001.p001.f01.ash6": "Port-Channel1"},
                "expected_up": False,
            },
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("as expected", result.message)

    async def test_port_channel_up_expected_down_returns_fail(self):
        """FBOSS: Port channel UP when expected DOWN should return FAIL."""
        pc = MagicMock()
        pc.name = "Port-Channel1"
        pc.isUp = True
        self.health_check.driver.async_get_all_aggregated_port_info = AsyncMock(
            return_value=[pc]
        )
        result = await self.health_check._run(
            self.device,
            self.input,
            {
                "port_channel_names": {"rsw001.p001.f01.ash6": "Port-Channel1"},
                "expected_up": False,
            },
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("expected DOWN but is UP", result.message)

    async def test_device_not_in_mapping_returns_fail(self):
        """FBOSS: Device not in port_channel_names mapping should return FAIL."""
        result = await self.health_check._run(
            self.device,
            self.input,
            {"port_channel_names": {"other-device.ash6": "Port-Channel1"}},
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("not found for", result.message)

    async def test_multiple_port_channels_all_up_returns_pass(self):
        """FBOSS: Multiple port channels all UP when expected UP should return PASS."""
        pc1 = MagicMock()
        pc1.name = "Port-Channel1"
        pc1.isUp = True
        pc2 = MagicMock()
        pc2.name = "Port-Channel2"
        pc2.isUp = True
        self.health_check.driver.async_get_all_aggregated_port_info = AsyncMock(
            return_value=[pc1, pc2]
        )
        result = await self.health_check._run(
            self.device,
            self.input,
            {
                "port_channel_names": {
                    "rsw001.p001.f01.ash6": ["Port-Channel1", "Port-Channel2"]
                }
            },
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("Port-Channel1", result.message)
        self.assertIn("Port-Channel2", result.message)

    async def test_multiple_port_channels_one_down_returns_fail(self):
        """FBOSS: One port channel DOWN out of multiple should return FAIL."""
        pc1 = MagicMock()
        pc1.name = "Port-Channel1"
        pc1.isUp = True
        pc2 = MagicMock()
        pc2.name = "Port-Channel2"
        pc2.isUp = False
        self.health_check.driver.async_get_all_aggregated_port_info = AsyncMock(
            return_value=[pc1, pc2]
        )
        result = await self.health_check._run(
            self.device,
            self.input,
            {
                "port_channel_names": {
                    "rsw001.p001.f01.ash6": ["Port-Channel1", "Port-Channel2"]
                }
            },
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("Port-Channel2", result.message)
        self.assertIn("expected UP but is DOWN", result.message)

    async def test_multiple_port_channels_one_missing_returns_fail(self):
        """FBOSS: One port channel missing out of multiple should return FAIL."""
        pc1 = MagicMock()
        pc1.name = "Port-Channel1"
        pc1.isUp = True
        self.health_check.driver.async_get_all_aggregated_port_info = AsyncMock(
            return_value=[pc1]
        )
        result = await self.health_check._run(
            self.device,
            self.input,
            {
                "port_channel_names": {
                    "rsw001.p001.f01.ash6": ["Port-Channel1", "Port-Channel99"]
                }
            },
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("Port-Channel99", result.message)
        self.assertIn("not found", result.message)


class TestPortChannelExpectedStateHealthCheckEOS(
    unittest.IsolatedAsyncioTestCase,
):
    def setUp(self):
        self.logger = MagicMock(spec=ConsoleFileLogger)
        self.health_check = PortChannelExpectedStateHealthCheck(logger=self.logger)
        self.health_check.driver = AsyncMock()
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "rsw001.p001.f01.ash6"
        self.device.attributes = MagicMock()
        self.device.attributes.operating_system = "EOS"
        self.input = hc_types.BaseHealthCheckIn()

    async def test_port_channel_up_expected_up_returns_pass(self):
        """EOS: Port channel UP when expected UP should return PASS."""
        self.health_check.driver.async_get_port_channel_detailed_info = AsyncMock(
            return_value={
                "portChannels": {
                    "Port-Channel1": {
                        "activePorts": {"Ethernet1": {}, "Ethernet2": {}},
                        "inactiveLag": False,
                    }
                }
            }
        )
        result = await self.health_check._run(
            self.device,
            self.input,
            {"port_channel_names": {"rsw001.p001.f01.ash6": "Port-Channel1"}},
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("as expected", result.message)

    async def test_port_channel_down_expected_up_returns_fail(self):
        """EOS: Port channel DOWN (no active ports) when expected UP should return FAIL."""
        self.health_check.driver.async_get_port_channel_detailed_info = AsyncMock(
            return_value={
                "portChannels": {
                    "Port-Channel1": {
                        "activePorts": {},
                        "inactiveLag": False,
                    }
                }
            }
        )
        result = await self.health_check._run(
            self.device,
            self.input,
            {"port_channel_names": {"rsw001.p001.f01.ash6": "Port-Channel1"}},
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("expected UP but is DOWN", result.message)

    async def test_port_channel_inactive_lag_returns_fail(self):
        """EOS: Port channel with inactiveLag=True when expected UP should return FAIL."""
        self.health_check.driver.async_get_port_channel_detailed_info = AsyncMock(
            return_value={
                "portChannels": {
                    "Port-Channel1": {
                        "activePorts": {"Ethernet1": {}},
                        "inactiveLag": True,
                    }
                }
            }
        )
        result = await self.health_check._run(
            self.device,
            self.input,
            {"port_channel_names": {"rsw001.p001.f01.ash6": "Port-Channel1"}},
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("expected UP but is DOWN", result.message)

    async def test_port_channel_not_found_returns_fail(self):
        """EOS: Port channel not found should return FAIL."""
        self.health_check.driver.async_get_port_channel_detailed_info = AsyncMock(
            return_value={"portChannels": {}}
        )
        result = await self.health_check._run(
            self.device,
            self.input,
            {"port_channel_names": {"rsw001.p001.f01.ash6": "Port-Channel99"}},
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("not found", result.message)

    async def test_port_channel_down_expected_down_returns_pass(self):
        """EOS: Port channel DOWN when expected DOWN should return PASS."""
        self.health_check.driver.async_get_port_channel_detailed_info = AsyncMock(
            return_value={
                "portChannels": {
                    "Port-Channel1": {
                        "activePorts": {},
                        "inactiveLag": False,
                    }
                }
            }
        )
        result = await self.health_check._run(
            self.device,
            self.input,
            {
                "port_channel_names": {"rsw001.p001.f01.ash6": "Port-Channel1"},
                "expected_up": False,
            },
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("as expected", result.message)

    async def test_device_not_in_mapping_returns_fail(self):
        """EOS: Device not in port_channel_names mapping should return FAIL."""
        result = await self.health_check._run(
            self.device,
            self.input,
            {"port_channel_names": {"other-device.ash6": "Port-Channel1"}},
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("not found for", result.message)

    async def test_multiple_port_channels_all_up_returns_pass(self):
        """EOS: Multiple port channels all UP when expected UP should return PASS."""
        self.health_check.driver.async_get_port_channel_detailed_info = AsyncMock(
            return_value={
                "portChannels": {
                    "Port-Channel1": {
                        "activePorts": {"Ethernet1": {}},
                        "inactiveLag": False,
                    },
                    "Port-Channel2": {
                        "activePorts": {"Ethernet2": {}},
                        "inactiveLag": False,
                    },
                }
            }
        )
        result = await self.health_check._run(
            self.device,
            self.input,
            {
                "port_channel_names": {
                    "rsw001.p001.f01.ash6": ["Port-Channel1", "Port-Channel2"]
                }
            },
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("Port-Channel1", result.message)
        self.assertIn("Port-Channel2", result.message)

    async def test_multiple_port_channels_one_down_returns_fail(self):
        """EOS: One port channel DOWN out of multiple should return FAIL."""
        self.health_check.driver.async_get_port_channel_detailed_info = AsyncMock(
            return_value={
                "portChannels": {
                    "Port-Channel1": {
                        "activePorts": {"Ethernet1": {}},
                        "inactiveLag": False,
                    },
                    "Port-Channel2": {
                        "activePorts": {},
                        "inactiveLag": False,
                    },
                }
            }
        )
        result = await self.health_check._run(
            self.device,
            self.input,
            {
                "port_channel_names": {
                    "rsw001.p001.f01.ash6": ["Port-Channel1", "Port-Channel2"]
                }
            },
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("Port-Channel2", result.message)
        self.assertIn("expected UP but is DOWN", result.message)


if __name__ == "__main__":
    unittest.main()
