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
        """A threshold breach with informational=True is a PASS (not FAIL)."""
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


class GenericOdsBaselineExcessTest(unittest.IsolatedAsyncioTestCase):
    TEST_START = 1000.0
    QUERY_END = 1300.0

    def setUp(self) -> None:
        self.check = GenericOdsHealthCheck(logger=MagicMock(spec=ConsoleFileLogger))
        self.device = _make_device("executor")
        self.input = hc_types.BaseHealthCheckIn()
        self.params = {
            "entity_desc": "gtsw1,gtsw2",
            "key_desc": "fboss.agent.eth.discards.sum.60",
            "reduce_desc": "groupby(...),sum",
            "transform_desc": "table(daily)",
            "validation_expr": "<= 10000",
            "baseline_excess_max": 10000,
            "use_test_case_start_time": True,
            "sleep_timer": 0,
            "shorten_pass_url": False,
            "counter_name": "in_discard",
        }

    @staticmethod
    def _series(*test_values: float, straddling: float = 999999.0) -> dict:
        values = {
            700: 10000.0,
            760: 11000.0,
            820: 9000.0,
            880: 12000.0,
            940: 10500.0,
            # This trailing 60-second bucket crosses TEST_START and must not
            # affect either the baseline ceiling or the test peak.
            1020: straddling,
        }
        for timestamp, value in zip((1060, 1120, 1180, 1240), test_values):
            values[timestamp] = value
        return {"counter": values}

    async def _run(self, entity_data: dict, **params):
        ods_data = dict(entity_data)
        with (
            patch(f"{MODULE}.time.time", return_value=self.QUERY_END),
            patch(f"{MODULE}.get_test_case_start_time", return_value=self.TEST_START),
            patch(
                f"{MODULE}.async_query_ods", new=AsyncMock(return_value=ods_data)
            ) as mock_query,
            patch(
                f"{MODULE}.async_generate_ods_url",
                new=AsyncMock(return_value="https://ods/raw"),
            ),
            patch(f"{MODULE}.async_get_fburl_retry", new_callable=AsyncMock),
        ):
            result = await self.check._run(
                self.device, self.input, {**self.params, **params}
            )
        self.assertIsNotNone(mock_query.await_args)
        assert mock_query.await_args is not None
        self.assertEqual(mock_query.await_args.kwargs["start_time"], 580)
        return result

    async def test_ambient_baseline_plus_allowed_excess_passes(self) -> None:
        data = self._series(21000.0, 20000.0, 19000.0)
        result = await self._run({"gtsw1": data, "gtsw2": data})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("baseline=12000", result.message or "")
        self.assertIn("excess=9000", result.message or "")

    async def test_reduced_ods_entity_keys_are_normalized(self) -> None:
        data = self._series(21000.0, 20000.0, 19000.0)
        result = await self._run(
            {
                "HOSTNAME::gtsw1.mwg2:sum": data,
                "HOSTNAME::gtsw2.mwg2:sum": data,
            }
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertNotIn("INCONCLUSIVE", result.message or "")

    async def test_straddling_bucket_is_excluded(self) -> None:
        data = self._series(12000.0, 12000.0, straddling=999999.0)
        result = await self._run({"gtsw1": data, "gtsw2": data})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_hard_transient_excess_fails_after_final_recovery(self) -> None:
        data = self._series(23001.0, 12000.0, 12000.0)
        result = await self._run({"gtsw1": data, "gtsw2": data})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("transient excess", result.message or "")

    async def test_informational_transient_excess_passes_after_recovery(self) -> None:
        data = self._series(23001.0, 12000.0, 12000.0)
        result = await self._run(
            {"gtsw1": data, "gtsw2": data},
            transient_excess_informational=True,
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("[INFORMATIONAL]", result.message or "")

    async def test_final_non_recovery_is_hard_failure_even_if_transient_allowed(
        self,
    ) -> None:
        data = self._series(23001.0, 23001.0, 23001.0)
        result = await self._run(
            {"gtsw1": data, "gtsw2": data},
            transient_excess_informational=True,
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("did not recover", result.message or "")

    async def test_insufficient_baseline_is_explicitly_inconclusive(self) -> None:
        data = {"counter": {760: 1.0, 820: 1.0, 880: 1.0, 940: 1.0, 1060: 1.0}}
        result = await self._run({"gtsw1": data, "gtsw2": data})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.SKIP)
        self.assertIn("[INCONCLUSIVE]", result.message or "")
        self.assertIn("need 5", result.message or "")

    async def test_insufficient_final_samples_is_explicitly_inconclusive(self) -> None:
        data = self._series(12000.0)
        result = await self._run(
            {"gtsw1": data, "gtsw2": data},
            final_bucket_count=2,
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.SKIP)
        self.assertIn("need 2 for the final-state policy", result.message or "")
