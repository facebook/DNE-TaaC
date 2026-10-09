# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from taac.constants import TestDevice
from taac.health_checks.device_health_checks import (
    prefix_limit_health_check as _module,
)
from taac.health_checks.device_health_checks.prefix_limit_health_check import (
    PrefixLimitHealthCheck,
)
from taac.health_check.health_check import types as hc_types

IMPORTED_IN_TAAC_OSS_MODE = _module.TAAC_OSS


class _PrefixLimitTestBase(unittest.IsolatedAsyncioTestCase):
    TAAC_OSS: bool = False

    def setUp(self) -> None:
        patcher = patch.object(_module, "TAAC_OSS", self.TAAC_OSS)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.health_check = PrefixLimitHealthCheck(logger=MagicMock())
        self.health_check.driver = AsyncMock()
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "dut1"
        self.input = hc_types.BaseHealthCheckIn()

    async def _run(self, check_params: dict) -> hc_types.HealthCheckResult:
        return await self.health_check._run(self.device, self.input, check_params)


class InternalPrefixLimitTest(_PrefixLimitTestBase):
    """FIB entries learned via BGP must not exceed the prefix limit."""

    async def test_fib_count_uses_modern_bgp_client(self) -> None:
        if IMPORTED_IN_TAAC_OSS_MODE:
            self.assertFalse(hasattr(_module, "FibClient"))
            return

        self.assertTrue(hasattr(_module, "FibClient"))
        self.health_check.driver.async_get_bgp_originated_routes.return_value = [
            object()
        ]
        self.health_check.driver.async_get_route_table_by_client.return_value = [
            object(),
            object(),
            object(),
        ]

        self.assertEqual(2, await self.health_check.async_get_fib_table_entries_count())
        self.health_check.driver.async_get_route_table_by_client.assert_awaited_once_with(
            _module.FibClient.BGP.value
        )

    async def test_fib_within_limit_returns_pass(self) -> None:
        self.health_check.async_get_fib_table_entries_count = AsyncMock(
            return_value=5000
        )
        result = await self._run({"prefix_limit": 10000})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_fib_exceeds_limit_returns_fail(self) -> None:
        self.health_check.async_get_fib_table_entries_count = AsyncMock(
            return_value=15000
        )
        result = await self._run({"prefix_limit": 10000})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)

    async def test_fib_at_exact_limit_returns_pass(self) -> None:
        self.health_check.async_get_fib_table_entries_count = AsyncMock(
            return_value=10000
        )
        result = await self._run({"prefix_limit": 10000})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_fallback_to_driver_prefix_limit(self) -> None:
        self.health_check.async_get_fib_table_entries_count = AsyncMock(
            return_value=5000
        )
        self.health_check.driver.async_get_bgp_prefix_limit = AsyncMock(
            return_value=10000
        )
        result = await self._run({})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)


class OssPrefixLimitTest(_PrefixLimitTestBase):
    """bgpd's configured prefix limit must equal the expected one."""

    TAAC_OSS = True

    async def test_matching_limit_returns_pass(self) -> None:
        self.health_check.driver.async_get_bgp_prefix_limit = AsyncMock(
            return_value=74000
        )
        result = await self._run({"prefix_limit": "74000"})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_mismatched_limit_returns_fail(self) -> None:
        self.health_check.driver.async_get_bgp_prefix_limit = AsyncMock(
            return_value=50000
        )
        result = await self._run({"prefix_limit": "74000"})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("50000", result.message or "")

    async def test_unset_limit_returns_fail(self) -> None:
        self.health_check.driver.async_get_bgp_prefix_limit = AsyncMock(
            return_value=None
        )
        result = await self._run({"prefix_limit": "74000"})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)

    async def test_missing_expected_limit_returns_skip(self) -> None:
        result = await self._run({})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.SKIP)
        self.health_check.driver.async_get_bgp_prefix_limit.assert_not_awaited()

    async def test_non_integer_expected_limit_returns_error(self) -> None:
        result = await self._run({"prefix_limit": "lots"})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.ERROR)

    async def test_driver_without_accessor_returns_error(self) -> None:
        self.health_check.driver = object()
        result = await self._run({"prefix_limit": "74000"})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.ERROR)

    async def test_does_not_count_fib_entries(self) -> None:
        self.health_check.async_get_fib_table_entries_count = AsyncMock()
        self.health_check.driver.async_get_bgp_prefix_limit = AsyncMock(
            return_value=74000
        )
        await self._run({"prefix_limit": "74000"})
        self.health_check.async_get_fib_table_entries_count.assert_not_awaited()
