# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""Unit tests for FpfStalePrefixHealthCheck."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from neteng.netcastle.logger import ConsoleFileLogger
from taac.constants import TestDevice
from taac.health_checks.device_health_checks.fpf_stale_prefix_health_check import (
    FpfStalePrefixHealthCheck,
)
from taac.health_check.health_check import types as hc_types


class TestFpfStalePrefixHealthCheck(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.logger = MagicMock(spec=ConsoleFileLogger)
        self.health_check = FpfStalePrefixHealthCheck(logger=self.logger)
        self.health_check.driver = AsyncMock()
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "gtsw001.l1002.c087.mwg2"

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks"
        ".fpf_stale_prefix_health_check.get_bgp_rib"
    )
    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks"
        ".fpf_stale_prefix_health_check._count_matching"
    )
    async def test_no_stale_prefixes_returns_pass(
        self, mock_count_matching, mock_get_bgp_rib
    ):
        """Zero matching prefixes should return PASS."""
        mock_get_bgp_rib.return_value = []
        mock_count_matching.return_value = 0

        input_data = hc_types.BaseHealthCheckIn()
        result = await self.health_check._run(self.device, input_data, {})

        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("No stale test prefixes", result.message)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks"
        ".fpf_stale_prefix_health_check.get_bgp_rib"
    )
    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks"
        ".fpf_stale_prefix_health_check._count_matching"
    )
    async def test_stale_prefixes_found_returns_fail(
        self, mock_count_matching, mock_get_bgp_rib
    ):
        """Non-zero matching prefixes should return FAIL."""
        mock_get_bgp_rib.return_value = [MagicMock()]
        mock_count_matching.return_value = 5

        input_data = hc_types.BaseHealthCheckIn()
        result = await self.health_check._run(self.device, input_data, {})

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("5 stale test prefix", result.message)
        self.assertIn("Clean up", result.message)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks"
        ".fpf_stale_prefix_health_check.get_bgp_rib"
    )
    async def test_connection_error_returns_skip(self, mock_get_bgp_rib):
        """ConnectionError from get_bgp_rib should return SKIP."""
        mock_get_bgp_rib.side_effect = ConnectionError("refused")

        input_data = hc_types.BaseHealthCheckIn()
        result = await self.health_check._run(self.device, input_data, {})

        self.assertEqual(result.status, hc_types.HealthCheckStatus.SKIP)
        self.assertIn("Connection error", result.message)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks"
        ".fpf_stale_prefix_health_check.get_bgp_rib"
    )
    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks"
        ".fpf_stale_prefix_health_check._count_matching"
    )
    async def test_custom_subnet_prefix_is_used(
        self, mock_count_matching, mock_get_bgp_rib
    ):
        """A custom subnet_prefix in check_params should be used."""
        mock_get_bgp_rib.return_value = []
        mock_count_matching.return_value = 0

        input_data = hc_types.BaseHealthCheckIn()
        result = await self.health_check._run(
            self.device,
            input_data,
            {"subnet_prefix": "2001:db8::/32"},
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("2001:db8::/32", result.message)

    async def test_invalid_subnet_prefix_returns_error(self):
        """An invalid subnet_prefix should return ERROR."""
        input_data = hc_types.BaseHealthCheckIn()
        result = await self.health_check._run(
            self.device,
            input_data,
            {"subnet_prefix": "not-a-valid-subnet"},
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.ERROR)
        self.assertIn("Invalid subnet_prefix", result.message)

    async def test_rtptest_host_returns_skip(self):
        """GPU hosts (rtptest) should return SKIP — BGP RIB check is for switches only."""
        self.device.name = "rtptest1544.mwg2"
        input_data = hc_types.BaseHealthCheckIn()
        result = await self.health_check._run(self.device, input_data, {})

        self.assertEqual(result.status, hc_types.HealthCheckStatus.SKIP)
        self.assertIn("not applicable to GPU host", result.message)
