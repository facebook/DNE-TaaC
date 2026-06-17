# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import ipaddress
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from facebook.network.Address.thrift_types import BinaryAddress
from neteng.fboss.ctrl.thrift_types import NdpEntryThrift
from taac.constants import TestTopology
from taac.health_checks.topology_health_checks.ndp_health_check import (
    NdpHealthCheck,
)
from taac.utils.oss_taac_lib_utils import ConsoleFileLogger
from taac.health_check.health_check import types as hc_types


class TestNdpHealthCheck(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        """Set up test fixtures."""
        self.logger = MagicMock(spec=ConsoleFileLogger)
        self.health_check = NdpHealthCheck(logger=self.logger)

        # Create a mock topology with test devices
        self.topology = MagicMock(spec=TestTopology)
        self.topology.devices = [MagicMock()]
        self.topology.devices[0].name = "test_device"
        self.topology.device_names = ["rdsw001", "rdsw002"]

        # Create a mock input
        self.input = MagicMock(spec=hc_types.BaseHealthCheckIn)

        # Create test check params
        self.check_params = {}

        # Mock switch ID mapping - for two switches
        self.switch_id_mapping = {
            1: "rdsw001",
            2: "rdsw002",
        }

        # IPv6 addresses for testing
        # Link local address (should be ignored in dynamic entry count)
        self.link_local_addr = ipaddress.IPv6Address("fe80::212:1ff:fe00:1")

        # Non-link local address (should be counted in dynamic entry count)
        self.global_addr = ipaddress.IPv6Address("2401:db00:11a:8000::1")

        # Static entry address
        self.static_addr = ipaddress.IPv6Address("2401:db00:e011:850::d00:2")

    def _create_ndp_entry(
        self,
        ip_addr: ipaddress.IPv6Address,
        state: str,
        switch_id=None,
        mac: str = "00:12:01:00:00:01",
    ):
        """Helper to create NDP entries for testing."""
        # Convert IPv6Address to bytes for BinaryAddress
        ip_bytes = ip_addr.packed

        entry = NdpEntryThrift(
            ip=BinaryAddress(addr=ip_bytes),
            mac=mac,
            state=state,
        )
        if switch_id is not None:
            # Create new entry with switchId
            entry = NdpEntryThrift(
                ip=BinaryAddress(addr=ip_bytes),
                mac=mac,
                state=state,
                switchId=switch_id,
            )
        return entry

    @patch(
        "neteng.test_infra.dne.taac.health_checks.topology_health_checks.ndp_health_check.async_get_device_driver"
    )
    async def test_health_check_pass_all_static_entries_and_dynamic_count_match(
        self, mock_get_device_driver
    ):
        """Test 1: Health check passes when all switches have static entries for all switches
        and dynamic entries match reachable entries count."""
        # Mock device driver
        mock_driver = AsyncMock()
        mock_get_device_driver.return_value = mock_driver

        # Mock switch ID mapping
        mock_driver.async_get_dsf_cluster_switch_id_mapping.return_value = (
            self.switch_id_mapping
        )

        # Create NDP tables for both switches
        # Switch 1 (rdsw001) NDP table:
        # - Static entries for both switches (1 and 2)
        # - 2 dynamic entries (should match 2 reachable entries from switch 2)
        switch1_ndp_table = [
            # Static entries for all switches in topology
            self._create_ndp_entry(self.static_addr, "STATIC", switch_id=1),
            self._create_ndp_entry(self.static_addr + 1, "STATIC", switch_id=2),
            # Dynamic entries
            self._create_ndp_entry(self.global_addr, "DYNAMIC", switch_id=2),
            self._create_ndp_entry(self.global_addr + 1, "DYNAMIC", switch_id=2),
        ]

        # Switch 2 (rdsw002) NDP table:
        # - Static entries for both switches (1 and 2)
        # - 2 reachable entries (will be counted for switch 1's dynamic validation)
        # - 1 dynamic entry (should match 1 reachable entry from switch 1)
        switch2_ndp_table = [
            # Static entries for all switches in topology
            self._create_ndp_entry(self.static_addr, "STATIC", switch_id=1),
            self._create_ndp_entry(self.static_addr + 1, "STATIC", switch_id=2),
            # Reachable entries (non-link local, will be counted for other switches)
            self._create_ndp_entry(self.global_addr, "REACHABLE"),
            self._create_ndp_entry(self.global_addr + 1, "REACHABLE"),
            # Link local reachable entry (should be ignored)
            self._create_ndp_entry(self.link_local_addr, "REACHABLE"),
        ]
        mock_driver.async_get_ndp_table.side_effect = [
            switch1_ndp_table,
            switch2_ndp_table,
        ]

        # Call the run method
        result = await self.health_check.run(
            obj=self.topology,
            input=self.input,
            default_input=self.input,
            check_params=self.check_params,
        )

        # Verify result is PASS
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.topology_health_checks.ndp_health_check.async_get_device_driver"
    )
    async def test_health_check_fail_missing_static_entries(
        self, mock_get_device_driver
    ):
        """Test 2: Health check fails when one switch does not have static entries for all switches."""
        # Mock device driver
        mock_driver = AsyncMock()
        mock_get_device_driver.return_value = mock_driver

        # Mock switch ID mapping
        mock_driver.async_get_dsf_cluster_switch_id_mapping.return_value = (
            self.switch_id_mapping
        )

        # Create NDP tables for both switches
        # Switch 1 (rdsw001) NDP table: Missing static entry for switch 2
        switch1_ndp_table = [
            # Only static entry for switch 1 (missing switch 2)
            self._create_ndp_entry(self.static_addr, "STATIC", switch_id=1),
            # Some dynamic entries
            self._create_ndp_entry(self.global_addr, "DYNAMIC", switch_id=2),
        ]

        # Switch 2 (rdsw002) NDP table: Has all static entries
        switch2_ndp_table = [
            # Static entries for all switches
            self._create_ndp_entry(self.static_addr, "STATIC", switch_id=1),
            self._create_ndp_entry(self.static_addr + 1, "STATIC", switch_id=2),
            # Some reachable entries
            self._create_ndp_entry(self.global_addr, "REACHABLE"),
        ]

        mock_driver.async_get_ndp_table.side_effect = [
            switch1_ndp_table,
            switch2_ndp_table,
        ]

        # Call the run method
        result = await self.health_check.run(
            obj=self.topology,
            input=self.input,
            default_input=self.input,
            check_params=self.check_params,
        )

        # Verify result is FAIL with appropriate message
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("Static NDP discrepancy found on rdsw001", result.message)
        self.assertIn("rdsw002", result.message)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.topology_health_checks.ndp_health_check.async_get_device_driver"
    )
    async def test_health_check_fail_dynamic_count_mismatch(
        self, mock_get_device_driver
    ):
        """Test 3: Health check fails when dynamic entries count does not match reachable entries count."""
        # Mock device driver
        mock_driver = AsyncMock()
        mock_get_device_driver.return_value = mock_driver

        # Mock switch ID mapping
        mock_driver.async_get_dsf_cluster_switch_id_mapping.return_value = (
            self.switch_id_mapping
        )

        # Create NDP tables for both switches
        # Switch 1 (rdsw001) NDP table:
        # - Static entries for all switches (correct)
        # - 3 dynamic entries (but switch 2 has only 1 reachable entry -> mismatch)
        switch1_ndp_table = [
            # Static entries for all switches
            self._create_ndp_entry(self.static_addr, "STATIC", switch_id=1),
            self._create_ndp_entry(self.static_addr + 1, "STATIC", switch_id=2),
            # 3 dynamic entries
            self._create_ndp_entry(self.global_addr, "DYNAMIC", switch_id=2),
            self._create_ndp_entry(self.global_addr + 1, "DYNAMIC", switch_id=2),
            self._create_ndp_entry(self.global_addr + 2, "DYNAMIC", switch_id=2),
        ]

        # Switch 2 (rdsw002) NDP table:
        # - Static entries for all switches (correct)
        # - Only 1 reachable entry (switch 1 expects 3 dynamic entries to match this)
        switch2_ndp_table = [
            # Static entries for all switches
            self._create_ndp_entry(self.static_addr, "STATIC", switch_id=1),
            self._create_ndp_entry(self.static_addr + 1, "STATIC", switch_id=2),
            # Only 1 reachable entry (non-link local)
            self._create_ndp_entry(self.global_addr, "REACHABLE"),
            # Some link local reachable entries (should be ignored)
            self._create_ndp_entry(self.link_local_addr, "REACHABLE"),
        ]

        mock_driver.async_get_ndp_table.side_effect = [
            switch1_ndp_table,
            switch2_ndp_table,
        ]

        # Call the run method
        result = await self.health_check.run(
            obj=self.topology,
            input=self.input,
            default_input=self.input,
            check_params=self.check_params,
        )

        # Verify result is FAIL with appropriate message
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("Dynamic NDP mismatch on rdsw001", result.message)
        self.assertIn("expected 1, got 3", result.message)
