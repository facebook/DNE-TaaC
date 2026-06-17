# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""Unit tests for TmReconciliationFiringHealthCheck verdict matrix + signal probing."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from neteng.netcastle.logger import ConsoleFileLogger
from taac.constants import TestDevice
from taac.health_checks.device_health_checks.tm_reconciliation_firing_health_check import (
    TmReconciliationFiringHealthCheck,
)
from taac.health_check.health_check import types as hc_types


_BASE_CHECK_PARAMS = {
    "expected_to_fire": True,
    "require_both_signals": False,
    "log_file_path": "/var/facebook/logs/fboss/wedge_agent.log",
    "firing_pattern": "Starting to delete all probed data from kernel",
    "ods_key": "fboss.agent.probed_state_cleanup_status",
    "start_time": 1700000000,
    "end_time": 1700000300,
}


def _make_check():
    logger = MagicMock(spec=ConsoleFileLogger)
    check = TmReconciliationFiringHealthCheck(logger=logger)
    check.driver = AsyncMock()
    return check


def _make_device():
    device = MagicMock(spec=TestDevice)
    device.name = "test-host.tfbnw.net"
    return device


def _mock_log(check, fired):
    """Patch _log_fired to return the given bool."""
    check._log_fired = AsyncMock(return_value=fired)


def _mock_ods(fired):
    """Build an async_query_ods return value that signals fired/not fired."""
    if not fired:
        return {}
    return {"test-host": {"fboss.agent.probed_state_cleanup_status": {1700000050: 1}}}


class TmReconciliationFiringHealthCheckTest(unittest.IsolatedAsyncioTestCase):
    """Verdict matrix coverage per project_p41_taac_hc_design.md §1."""

    def setUp(self):
        self.check = _make_check()
        self.device = _make_device()
        self.input = hc_types.BaseHealthCheckIn()

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "tm_reconciliation_firing_health_check.async_query_ods"
    )
    async def test_expected_fire_both_signals_returns_pass(self, mock_ods):
        """expected=True, log=True, ods=True → PASS."""
        _mock_log(self.check, fired=True)
        mock_ods.return_value = _mock_ods(fired=True)
        result = await self.check._run(self.device, self.input, _BASE_CHECK_PARAMS)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("both signals agree", result.message)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "tm_reconciliation_firing_health_check.async_query_ods"
    )
    async def test_expected_fire_neither_signal_returns_fail(self, mock_ods):
        """expected=True, log=False, ods=False → FAIL."""
        _mock_log(self.check, fired=False)
        mock_ods.return_value = _mock_ods(fired=False)
        result = await self.check._run(self.device, self.input, _BASE_CHECK_PARAMS)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("expected firing, none seen", result.message)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "tm_reconciliation_firing_health_check.async_query_ods"
    )
    async def test_expected_fire_log_only_returns_warn_pass(self, mock_ods):
        """expected=True, log=True, ods=False, require_both=False → PASS (WARN)."""
        _mock_log(self.check, fired=True)
        mock_ods.return_value = _mock_ods(fired=False)
        result = await self.check._run(self.device, self.input, _BASE_CHECK_PARAMS)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("WARN", result.message)
        self.assertIn("signal disagreement", result.message)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "tm_reconciliation_firing_health_check.async_query_ods"
    )
    async def test_expected_fire_log_only_strict_returns_fail(self, mock_ods):
        """expected=True, log=True, ods=False, require_both=True → FAIL."""
        _mock_log(self.check, fired=True)
        mock_ods.return_value = _mock_ods(fired=False)
        params = {**_BASE_CHECK_PARAMS, "require_both_signals": True}
        result = await self.check._run(self.device, self.input, params)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("signal disagreement", result.message)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "tm_reconciliation_firing_health_check.async_query_ods"
    )
    async def test_not_expected_neither_signal_returns_pass(self, mock_ods):
        """expected=False, log=False, ods=False → PASS."""
        _mock_log(self.check, fired=False)
        mock_ods.return_value = _mock_ods(fired=False)
        params = {**_BASE_CHECK_PARAMS, "expected_to_fire": False}
        result = await self.check._run(self.device, self.input, params)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("no firing as expected", result.message)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "tm_reconciliation_firing_health_check.async_query_ods"
    )
    async def test_not_expected_both_signals_returns_fail(self, mock_ods):
        """expected=False, log=True, ods=True → FAIL (unexpected firing)."""
        _mock_log(self.check, fired=True)
        mock_ods.return_value = _mock_ods(fired=True)
        params = {**_BASE_CHECK_PARAMS, "expected_to_fire": False}
        result = await self.check._run(self.device, self.input, params)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("unexpected firing", result.message)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "tm_reconciliation_firing_health_check.async_query_ods"
    )
    async def test_not_expected_ods_only_returns_warn_pass(self, mock_ods):
        """expected=False, log=False, ods=True → PASS (WARN, likely sticky ODS)."""
        _mock_log(self.check, fired=False)
        mock_ods.return_value = _mock_ods(fired=True)
        params = {**_BASE_CHECK_PARAMS, "expected_to_fire": False}
        result = await self.check._run(self.device, self.input, params)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("WARN", result.message)


class TmReconciliationFiringOdsParsingTest(unittest.IsolatedAsyncioTestCase):
    """Direct tests for the ODS sample parsing path."""

    def setUp(self):
        self.check = _make_check()
        self.device = _make_device()

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "tm_reconciliation_firing_health_check.async_query_ods"
    )
    async def test_ods_value_1_returns_true(self, mock_ods):
        """A single value=1 sample anywhere in the series counts as fired."""
        mock_ods.return_value = {"h": {"k": {1700000050: 1}}}
        self.assertTrue(await self.check._ods_fired(self.device, "k", 0, 100))

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "tm_reconciliation_firing_health_check.async_query_ods"
    )
    async def test_ods_only_zero_values_returns_false(self, mock_ods):
        """All-zero series counts as not fired."""
        mock_ods.return_value = {"h": {"k": {1700000050: 0, 1700000110: 0}}}
        self.assertFalse(await self.check._ods_fired(self.device, "k", 0, 100))

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "tm_reconciliation_firing_health_check.async_query_ods"
    )
    async def test_ods_empty_response_returns_false(self, mock_ods):
        """Empty ODS response (no samples) counts as not fired."""
        mock_ods.return_value = {}
        self.assertFalse(await self.check._ods_fired(self.device, "k", 0, 100))

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "tm_reconciliation_firing_health_check.async_query_ods"
    )
    async def test_ods_entity_strips_tfbnw_suffix(self, mock_ods):
        """ODS entity is the device fqdn with `.tfbnw.net` stripped."""
        mock_ods.return_value = {}
        await self.check._ods_fired(self.device, "k", 0, 100)
        mock_ods.assert_called_once()
        kwargs = mock_ods.call_args.kwargs
        self.assertEqual(kwargs["entity_desc"], "test-host")
