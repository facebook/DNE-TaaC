# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from neteng.netcastle.logger import ConsoleFileLogger
from taac.constants import TestDevice
from taac.health_checks.device_health_checks.generic_ods_health_check import (
    GenericOdsHealthCheck,
)
from taac.health_check.health_check import types as hc_types

MODULE = (
    "neteng.test_infra.dne.taac.health_checks.device_health_checks."
    "generic_ods_health_check"
)


def _make_device(name: str) -> MagicMock:
    device = MagicMock(spec=TestDevice)
    device.name = name
    return device


class GenericOdsHealthCheckFburlTest(unittest.IsolatedAsyncioTestCase):
    """GenericOdsHealthCheck must only shorten the ODS URL through the throttled
    fburl tier on FAIL; PASS and SKIP keep the raw (still clickable) ODS URL and
    make zero fburl calls."""

    def setUp(self) -> None:
        self.check = GenericOdsHealthCheck(logger=MagicMock(spec=ConsoleFileLogger))
        self.device = _make_device("dev1")
        self.input = hc_types.BaseHealthCheckIn()
        self.check_params = {
            "key_desc": "fboss.some.counter",
            "sleep_timer": 0,
            "validation_expr": "< 100",
        }

    @patch(
        f"{MODULE}.async_get_fburl_retry",
        new_callable=AsyncMock,
        return_value="https://fburl.com/x",
    )
    @patch(
        f"{MODULE}.async_generate_ods_url",
        new_callable=AsyncMock,
        return_value="https://ods/raw",
    )
    @patch(f"{MODULE}.eval_jq", return_value={})
    @patch(f"{MODULE}.async_query_ods", new_callable=AsyncMock)
    async def test_pass_does_not_call_fburl(
        self, mock_query, mock_jq, mock_ods_url, mock_fburl
    ) -> None:
        mock_query.return_value = {"dev1": {"fboss.some.counter": {"100": 50.0}}}
        result = await self.check._run(self.device, self.input, self.check_params)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("https://ods/raw", result.message or "")
        mock_fburl.assert_not_awaited()

    @patch(
        f"{MODULE}.async_get_fburl_retry",
        new_callable=AsyncMock,
        return_value="https://fburl.com/x",
    )
    @patch(
        f"{MODULE}.async_generate_ods_url",
        new_callable=AsyncMock,
        return_value="https://ods/raw",
    )
    @patch(f"{MODULE}.eval_jq", return_value={"100": 150.0})
    @patch(f"{MODULE}.async_query_ods", new_callable=AsyncMock)
    async def test_fail_calls_fburl_once(
        self, mock_query, mock_jq, mock_ods_url, mock_fburl
    ) -> None:
        mock_query.return_value = {"dev1": {"fboss.some.counter": {"100": 150.0}}}
        result = await self.check._run(self.device, self.input, self.check_params)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("https://fburl.com/x", result.message or "")
        mock_fburl.assert_awaited_once_with("https://ods/raw")

    @patch(
        f"{MODULE}.async_get_fburl_retry",
        new_callable=AsyncMock,
        return_value="https://fburl.com/x",
    )
    @patch(
        f"{MODULE}.async_generate_ods_url",
        new_callable=AsyncMock,
        return_value="https://ods/raw",
    )
    @patch(f"{MODULE}.eval_jq", return_value={"100": 150.0})
    @patch(f"{MODULE}.async_query_ods", new_callable=AsyncMock)
    async def test_informational_breach_reports_pass(
        self, mock_query, mock_jq, mock_ods_url, mock_fburl
    ) -> None:
        """A threshold breach with informational=True is a PASS (not FAIL), with
        an [INFORMATIONAL] message — used for expected transient discards during
        a disruptive restart/coldboot."""
        mock_query.return_value = {"dev1": {"fboss.some.counter": {"100": 150.0}}}
        params = {**self.check_params, "informational": True}
        result = await self.check._run(self.device, self.input, params)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("[INFORMATIONAL]", result.message or "")

    @patch(
        f"{MODULE}.async_get_fburl_retry",
        new_callable=AsyncMock,
        return_value="https://fburl.com/x",
    )
    @patch(
        f"{MODULE}.async_generate_ods_url",
        new_callable=AsyncMock,
        return_value="https://ods/raw",
    )
    @patch(f"{MODULE}.async_query_ods", new_callable=AsyncMock)
    async def test_skip_no_data_does_not_call_fburl(
        self, mock_query, mock_ods_url, mock_fburl
    ) -> None:
        mock_query.return_value = {}
        result = await self.check._run(self.device, self.input, self.check_params)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.SKIP)
        self.assertIn("https://ods/raw", result.message or "")
        mock_fburl.assert_not_awaited()
