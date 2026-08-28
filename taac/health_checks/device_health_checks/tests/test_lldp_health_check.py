# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from neteng.netcastle.logger import ConsoleFileLogger
from taac.constants import TestDevice
from taac.driver.driver_constants import SwitchLldpData
from taac.health_checks.device_health_checks.lldp_health_check import (
    is_fabric_interface,
    LldpHealthCheck,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types


def _make_test_interface(
    interface_name: str,
    switch_name: str,
    neighbor_switch_name: str,
    neighbor_interface_name: str,
) -> taac_types.TestInterface:
    return taac_types.TestInterface(
        interface_name=interface_name,
        switch_name=switch_name,
        neighbor_switch_name=neighbor_switch_name,
        neighbor_interface_name=neighbor_interface_name,
        neighbor_display_name=f"{neighbor_switch_name}.tfbnw.net:{neighbor_interface_name}",
    )


def _make_device(
    name: str,
    interfaces: list,
) -> MagicMock:
    device = MagicMock(spec=TestDevice)
    device.name = name
    device.interfaces = interfaces
    return device


class TestIsFabricInterface(unittest.TestCase):
    def test_fabric_interface(self):
        self.assertTrue(is_fabric_interface("fab1/1/1"))
        self.assertTrue(is_fabric_interface("fabric0"))

    def test_non_fabric_interface(self):
        self.assertFalse(is_fabric_interface("Ethernet3/1/1"))
        self.assertFalse(is_fabric_interface("eth1/1/1"))


class TestLldpHealthCheckHelpers(unittest.TestCase):
    def setUp(self):
        self.logger = MagicMock(spec=ConsoleFileLogger)
        self.health_check = LldpHealthCheck(logger=self.logger)
        self.health_check.driver = AsyncMock()

    def test_get_enabled_and_disabled_no_disabled(self):
        interfaces = [
            _make_test_interface(
                "Ethernet3/1/1", "bag001.qza1", "bag001.ash6", "Ethernet5/1/1"
            ),
            _make_test_interface(
                "Ethernet3/2/1", "bag001.qza1", "bag001.ash6", "Ethernet5/2/1"
            ),
        ]
        device = _make_device("bag001.qza1", interfaces)

        enabled, disabled = self.health_check._get_enabled_and_disabled_interfaces(
            device, {}
        )
        self.assertEqual(len(enabled), 2)
        self.assertEqual(len(disabled), 0)

    def test_get_enabled_and_disabled_with_disabled_switch_name(self):
        interfaces = [
            _make_test_interface(
                "Ethernet3/1/1", "bag001.qza1", "bag001.ash6", "Ethernet5/1/1"
            ),
            _make_test_interface(
                "Ethernet3/2/1", "bag001.qza1", "bag001.ash6", "Ethernet5/2/1"
            ),
        ]
        device = _make_device("bag001.qza1", interfaces)

        disabled_intf = taac_types.TestInterface(
            interface_name="Ethernet3/1/1",
            switch_name="bag001.qza1",
            neighbor_switch_name="bag001.ash6",
            neighbor_interface_name="Ethernet5/1/1",
        )
        check_params = {"disabled_interfaces": [disabled_intf]}

        enabled, disabled = self.health_check._get_enabled_and_disabled_interfaces(
            device, check_params
        )
        self.assertEqual(len(enabled), 1)
        self.assertEqual(enabled[0].interface_name, "Ethernet3/2/1")
        self.assertEqual(len(disabled), 1)

    def test_get_enabled_and_disabled_with_disabled_neighbor_switch_name(self):
        interfaces = [
            _make_test_interface(
                "Ethernet5/1/1", "bag001.ash6", "bag001.qza1", "Ethernet3/1/1"
            ),
        ]
        device = _make_device("bag001.ash6", interfaces)

        disabled_intf = taac_types.TestInterface(
            interface_name="Ethernet3/1/1",
            switch_name="bag001.qza1",
            neighbor_switch_name="bag001.ash6",
            neighbor_interface_name="Ethernet5/1/1",
        )
        check_params = {"disabled_interfaces": [disabled_intf]}

        enabled, disabled = self.health_check._get_enabled_and_disabled_interfaces(
            device, check_params
        )
        self.assertEqual(len(enabled), 0)

    def test_fabric_interfaces_excluded(self):
        interfaces = [
            _make_test_interface(
                "Ethernet3/1/1", "bag001.qza1", "bag001.ash6", "Ethernet5/1/1"
            ),
            _make_test_interface("fab1/1/1", "bag001.qza1", "bag001.ash6", "fab2/1/1"),
        ]
        device = _make_device("bag001.qza1", interfaces)

        enabled, disabled = self.health_check._get_enabled_and_disabled_interfaces(
            device, {}
        )
        self.assertEqual(len(enabled), 1)
        self.assertEqual(enabled[0].interface_name, "Ethernet3/1/1")


EVERPASTE_PATCH = "neteng.test_infra.dne.taac.health_checks.device_health_checks.lldp_health_check.async_everpaste_str"


class TestLldpHealthCheckRun(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.logger = MagicMock(spec=ConsoleFileLogger)
        self.health_check = LldpHealthCheck(logger=self.logger)
        self.health_check.driver = AsyncMock()
        self.input = hc_types.BaseHealthCheckIn()

        self.interfaces = [
            _make_test_interface(
                "Ethernet3/1/1", "bag001.qza1", "bag001.ash6", "Ethernet5/1/1"
            ),
            _make_test_interface(
                "Ethernet3/9/1", "bag001.qza1", "stsw003.s001.l201.qza1", "eth1/1/1"
            ),
        ]
        self.device = _make_device("bag001.qza1", self.interfaces)

    async def test_run_all_neighbors_match(self):
        self.health_check.driver.async_get_lldp_neighbors.return_value = {
            "Ethernet3/1/1": SwitchLldpData(
                remote_device_name="bag001.ash6",
                remote_intf_name="Ethernet5/1/1",
            ),
            "Ethernet3/9/1": SwitchLldpData(
                remote_device_name="stsw003.s001.l201.qza1",
                remote_intf_name="eth1/1/1",
            ),
        }

        result = await self.health_check._run(self.device, self.input, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    @patch(
        EVERPASTE_PATCH, new_callable=AsyncMock, return_value="https://everpaste/test"
    )
    async def test_run_missing_lldp_neighbor(self, mock_everpaste):
        self.health_check.driver.async_get_lldp_neighbors.return_value = {
            "Ethernet3/1/1": SwitchLldpData(
                remote_device_name="bag001.ash6",
                remote_intf_name="Ethernet5/1/1",
            ),
        }

        with self.assertRaises(Exception) as ctx:
            await self.health_check._run(self.device, self.input, {})
        self.assertIn("expected to be UP", str(ctx.exception))
        self.assertIn("Ethernet3/9/1", str(ctx.exception))

    @patch(
        EVERPASTE_PATCH, new_callable=AsyncMock, return_value="https://everpaste/test"
    )
    async def test_run_wrong_lldp_neighbor(self, mock_everpaste):
        self.health_check.driver.async_get_lldp_neighbors.return_value = {
            "Ethernet3/1/1": SwitchLldpData(
                remote_device_name="bag001.ash6",
                remote_intf_name="Ethernet5/1/1",
            ),
            "Ethernet3/9/1": SwitchLldpData(
                remote_device_name="stsw003.s001.l201.qza1",
                remote_intf_name="eth1/2/1",
            ),
        }

        with self.assertRaises(Exception) as ctx:
            await self.health_check._run(self.device, self.input, {})
        self.assertIn("expects LLDP neighbor", str(ctx.exception))
        self.assertIn("eth1/2/1", str(ctx.exception))

    @patch(
        EVERPASTE_PATCH, new_callable=AsyncMock, return_value="https://everpaste/test"
    )
    async def test_run_disabled_interface_has_lldp(self, mock_everpaste):
        disabled_intf = taac_types.TestInterface(
            interface_name="Ethernet3/1/1",
            switch_name="bag001.qza1",
            neighbor_switch_name="bag001.ash6",
            neighbor_interface_name="Ethernet5/1/1",
        )
        check_params = {"disabled_interfaces": [disabled_intf]}

        self.health_check.driver.async_get_lldp_neighbors.return_value = {
            "Ethernet3/1/1": SwitchLldpData(
                remote_device_name="bag001.ash6",
                remote_intf_name="Ethernet5/1/1",
            ),
            "Ethernet3/9/1": SwitchLldpData(
                remote_device_name="stsw003.s001.l201.qza1",
                remote_intf_name="eth1/1/1",
            ),
        }

        with self.assertRaises(Exception) as ctx:
            await self.health_check._run(self.device, self.input, check_params)
        self.assertIn("expected to be DOWN", str(ctx.exception))

    async def test_run_disabled_interface_no_lldp_passes(self):
        disabled_intf = taac_types.TestInterface(
            interface_name="Ethernet3/1/1",
            switch_name="bag001.qza1",
            neighbor_switch_name="bag001.ash6",
            neighbor_interface_name="Ethernet5/1/1",
        )
        check_params = {"disabled_interfaces": [disabled_intf]}

        self.health_check.driver.async_get_lldp_neighbors.return_value = {
            "Ethernet3/9/1": SwitchLldpData(
                remote_device_name="stsw003.s001.l201.qza1",
                remote_intf_name="eth1/1/1",
            ),
        }

        result = await self.health_check._run(self.device, self.input, check_params)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    @patch(
        EVERPASTE_PATCH, new_callable=AsyncMock, return_value="https://everpaste/test"
    )
    async def test_run_multiple_failures_truncated(self, mock_everpaste):
        interfaces = [
            _make_test_interface(
                f"Ethernet3/{i}/1", "bag001.qza1", "bag001.ash6", f"Ethernet5/{i}/1"
            )
            for i in range(1, 8)
        ]
        device = _make_device("bag001.qza1", interfaces)

        self.health_check.driver.async_get_lldp_neighbors.return_value = {}

        with self.assertRaises(Exception) as ctx:
            await self.health_check._run(device, self.input, {})
        self.assertIn("7 issue(s)", str(ctx.exception))
        self.assertIn("+2 more", str(ctx.exception))


class TestLldpHealthCheckRunArista(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.logger = MagicMock(spec=ConsoleFileLogger)
        self.health_check = LldpHealthCheck(logger=self.logger)
        self.health_check.driver = AsyncMock()
        self.input = hc_types.BaseHealthCheckIn()

        self.interfaces = [
            _make_test_interface(
                "Ethernet3/1/1", "bag001.qza1", "bag001.ash6", "Ethernet5/1/1"
            ),
            _make_test_interface(
                "Ethernet3/9/1", "bag001.qza1", "stsw003.s001.l201.qza1", "eth1/1/1"
            ),
        ]
        self.device = _make_device("bag001.qza1", self.interfaces)

    async def test_run_arista_all_neighbors_match(self):
        self.health_check.driver.async_get_lldp_neighbors.return_value = {
            "Ethernet3/1/1": SwitchLldpData(
                remote_device_name="bag001.ash6",
                remote_intf_name="Ethernet5/1/1",
            ),
            "Ethernet3/9/1": SwitchLldpData(
                remote_device_name="stsw003.s001.l201.qza1",
                remote_intf_name="eth1/1/1",
            ),
        }

        result = await self.health_check._run_arista(self.device, self.input, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    @patch(
        EVERPASTE_PATCH, new_callable=AsyncMock, return_value="https://everpaste/test"
    )
    async def test_run_arista_missing_neighbor(self, mock_everpaste):
        self.health_check.driver.async_get_lldp_neighbors.return_value = {
            "Ethernet3/1/1": SwitchLldpData(
                remote_device_name="bag001.ash6",
                remote_intf_name="Ethernet5/1/1",
            ),
        }

        with self.assertRaises(Exception) as ctx:
            await self.health_check._run_arista(self.device, self.input, {})
        self.assertIn("expected to be UP", str(ctx.exception))
        self.assertIn("Ethernet3/9/1", str(ctx.exception))

    @patch(
        EVERPASTE_PATCH, new_callable=AsyncMock, return_value="https://everpaste/test"
    )
    async def test_run_arista_wrong_neighbor(self, mock_everpaste):
        self.health_check.driver.async_get_lldp_neighbors.return_value = {
            "Ethernet3/1/1": SwitchLldpData(
                remote_device_name="wrong_device",
                remote_intf_name="Ethernet5/1/1",
            ),
            "Ethernet3/9/1": SwitchLldpData(
                remote_device_name="stsw003.s001.l201.qza1",
                remote_intf_name="eth1/1/1",
            ),
        }

        with self.assertRaises(Exception) as ctx:
            await self.health_check._run_arista(self.device, self.input, {})
        self.assertIn("expects LLDP neighbor", str(ctx.exception))

    @patch(
        EVERPASTE_PATCH, new_callable=AsyncMock, return_value="https://everpaste/test"
    )
    async def test_run_arista_disabled_interface_has_lldp(self, mock_everpaste):
        disabled_intf = taac_types.TestInterface(
            interface_name="Ethernet3/1/1",
            switch_name="bag001.qza1",
            neighbor_switch_name="bag001.ash6",
            neighbor_interface_name="Ethernet5/1/1",
        )
        check_params = {"disabled_interfaces": [disabled_intf]}

        self.health_check.driver.async_get_lldp_neighbors.return_value = {
            "Ethernet3/1/1": SwitchLldpData(
                remote_device_name="bag001.ash6",
                remote_intf_name="Ethernet5/1/1",
            ),
            "Ethernet3/9/1": SwitchLldpData(
                remote_device_name="stsw003.s001.l201.qza1",
                remote_intf_name="eth1/1/1",
            ),
        }

        with self.assertRaises(Exception) as ctx:
            await self.health_check._run_arista(self.device, self.input, check_params)
        self.assertIn("expected to be DOWN", str(ctx.exception))

    async def test_run_arista_with_eos_to_eos_neighbors(self):
        interfaces = [
            _make_test_interface(
                "Ethernet5/5/1", "bag001.qza1", "bag001.qzb1", "Ethernet5/19/1"
            ),
            _make_test_interface(
                "Ethernet3/1/1", "bag001.qza1", "bag001.ash6", "Ethernet5/1/1"
            ),
        ]
        device = _make_device("bag001.qza1", interfaces)

        self.health_check.driver.async_get_lldp_neighbors.return_value = {
            "Ethernet5/5/1": SwitchLldpData(
                remote_device_name="bag001.qzb1",
                remote_intf_name="Ethernet5/19/1",
            ),
            "Ethernet3/1/1": SwitchLldpData(
                remote_device_name="bag001.ash6",
                remote_intf_name="Ethernet5/1/1",
            ),
        }

        result = await self.health_check._run_arista(device, self.input, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_run_arista_with_fqdn_neighbor(self):
        interfaces = [
            _make_test_interface(
                "Ethernet3/9/1", "bag001.qza1", "stsw003.s001.l201.qza1", "eth1/1/1"
            ),
        ]
        device = _make_device("bag001.qza1", interfaces)

        self.health_check.driver.async_get_lldp_neighbors.return_value = {
            "Ethernet3/9/1": SwitchLldpData(
                remote_device_name="stsw003.s001.l201.qza1",
                remote_intf_name="eth1/1/1",
            ),
        }

        result = await self.health_check._run_arista(device, self.input, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)


class TestLldpHealthCheckDispatch(unittest.IsolatedAsyncioTestCase):
    """Verify the base class dispatches to _run_arista for EOS devices."""

    def setUp(self):
        self.logger = MagicMock(spec=ConsoleFileLogger)
        self.health_check = LldpHealthCheck(logger=self.logger)
        self.input = hc_types.BaseHealthCheckIn()

    @patch(
        "neteng.test_infra.dne.taac.health_checks.abstract_health_check.async_get_device_driver"
    )
    async def test_eos_device_dispatches_to_run_arista(self, mock_get_driver):
        mock_driver = AsyncMock()
        mock_get_driver.return_value = mock_driver
        mock_driver.async_get_lldp_neighbors.return_value = {
            "Ethernet3/1/1": SwitchLldpData(
                remote_device_name="bag001.ash6",
                remote_intf_name="Ethernet5/1/1",
            ),
        }

        interfaces = [
            _make_test_interface(
                "Ethernet3/1/1", "bag001.qza1", "bag001.ash6", "Ethernet5/1/1"
            ),
        ]
        device = _make_device("bag001.qza1", interfaces)
        device.attributes = MagicMock()
        device.attributes.operating_system = "EOS"

        result = await self.health_check.run_wrapper(
            obj=device,
            input=self.input,
            default_input=self.input,
            check_params={},
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.abstract_health_check.async_get_device_driver"
    )
    async def test_fboss_device_dispatches_to_run(self, mock_get_driver):
        mock_driver = AsyncMock()
        mock_get_driver.return_value = mock_driver
        mock_driver.async_get_lldp_neighbors.return_value = {
            "eth1/1/1": SwitchLldpData(
                remote_device_name="rsw001.p001.f01.abc",
                remote_intf_name="eth1/2/1",
            ),
        }

        interfaces = [
            _make_test_interface(
                "eth1/1/1", "rsw001.p001.f01.abc", "rsw001.p001.f01.abc", "eth1/2/1"
            ),
        ]
        device = _make_device("rsw001.p001.f01.abc", interfaces)
        device.attributes = MagicMock()
        device.attributes.operating_system = "FBOSS"

        result = await self.health_check.run_wrapper(
            obj=device,
            input=self.input,
            default_input=self.input,
            check_params={},
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)


class TestLldpHealthCheckSkipsWhenNothingToValidate(unittest.IsolatedAsyncioTestCase):
    """A check that examines no interface must not report PASS.

    `TestDevice.interfaces` is only populated for links whose neighbor is also a
    declared endpoint, so a single-endpoint TestConfig leaves it empty and the
    validation loop becomes a no-op. This previously returned PASS: observed on
    bag001.snc1, which passed at PRE_TEST while it had 0 links up and 0 LLDP
    neighbors.
    """

    def setUp(self):
        self.logger = MagicMock(spec=ConsoleFileLogger)
        self.health_check = LldpHealthCheck(logger=self.logger)
        self.health_check.driver = AsyncMock()
        self.input = hc_types.BaseHealthCheckIn()

    async def test_skips_when_device_has_no_interfaces(self):
        device = _make_device("bag001.snc1", [])
        result = await self.health_check._run(device, self.input, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.SKIP)
        self.assertIsNotNone(result.message)
        self.assertIn("asserted nothing", result.message or "")
        # The device must not even be queried when there is nothing to check.
        self.health_check.driver.async_get_lldp_neighbors.assert_not_awaited()

    async def test_arista_path_skips_too(self):
        device = _make_device("bag001.snc1", [])
        result = await self.health_check._run_arista(device, self.input, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.SKIP)

    async def test_skips_when_only_ixia_interfaces(self):
        """IXIA links are excluded from LLDP validation, so they cannot rescue it."""
        device = _make_device(
            "bag001.snc1",
            [
                _make_test_interface(
                    "Ethernet5/9/1", "bag001.snc1", "ixia13.netcastle.snc1", "1/1"
                )
            ],
        )
        result = await self.health_check._run(device, self.input, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.SKIP)

    async def test_still_passes_with_a_real_neighbor(self):
        """The SKIP guard must not change behaviour when there is work to do."""
        device = _make_device(
            "bag001.snc1",
            [
                _make_test_interface(
                    "Ethernet5/1/1",
                    "bag001.snc1",
                    "edsw003.n000.l201.snc1",
                    "eth1/15/1",
                )
            ],
        )
        self.health_check.driver.async_get_lldp_neighbors.return_value = {
            "Ethernet5/1/1": SwitchLldpData(
                remote_device_name="edsw003.n000.l201.snc1",
                remote_intf_name="eth1/15/1",
            ),
        }
        result = await self.health_check._run(device, self.input, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_skips_when_disabled_interfaces_belong_to_another_device(self):
        """Device-scoping regression guard.

        `disabled_interfaces` from check_params is device-UNSCOPED. If the SKIP
        guard tested that raw list, a TestConfig disabling interfaces on device
        B would bypass the SKIP for device A -- which has no interfaces of its
        own -- and hand back the vacuous PASS this guard exists to prevent.
        """
        device = _make_device("bag001.snc1", [])
        check_params = {
            "disabled_interfaces": [
                {
                    "interface_name": "Ethernet1/1/1",
                    "switch_name": "someone-else.snc1",
                    "neighbor_switch_name": "another-device.snc1",
                    "neighbor_interface_name": "Ethernet2/2/2",
                }
            ]
        }
        result = await self.health_check._run(device, self.input, check_params)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.SKIP)
        self.health_check.driver.async_get_lldp_neighbors.assert_not_awaited()

    async def test_does_not_skip_when_disabled_interface_is_this_device(self):
        """A disabled interface on THIS device is real work, so do not skip."""
        device = _make_device("bag001.snc1", [])
        check_params = {
            "disabled_interfaces": [
                {
                    "interface_name": "Ethernet5/1/1",
                    "switch_name": "bag001.snc1",
                    "neighbor_switch_name": "edsw003.n000.l201.snc1",
                    "neighbor_interface_name": "eth1/15/1",
                }
            ]
        }
        self.health_check.driver.async_get_lldp_neighbors.return_value = {}
        result = await self.health_check._run(device, self.input, check_params)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.health_check.driver.async_get_lldp_neighbors.assert_awaited()

    async def test_skips_when_only_the_neighbor_side_matches_this_device(self):
        """Neighbor-side-only entries are not work for THIS device.

        `async_validate_lldp_neighbors` looks up `interface.interface_name`,
        which is a local port only on the entry's `switch_name` side. When we
        match solely via `neighbor_switch_name`, that name belongs to the other
        device, so nothing about this device would be validated -- SKIP is the
        honest answer rather than a PASS that inspected nothing.
        """
        device = _make_device("bag001.snc1", [])
        check_params = {
            "disabled_interfaces": [
                {
                    "interface_name": "eth1/15/1",
                    "switch_name": "edsw003.n000.l201.snc1",
                    "neighbor_switch_name": "bag001.snc1",
                    "neighbor_interface_name": "Ethernet5/1/1",
                }
            ]
        }
        result = await self.health_check._run(device, self.input, check_params)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.SKIP)
        self.health_check.driver.async_get_lldp_neighbors.assert_not_awaited()
