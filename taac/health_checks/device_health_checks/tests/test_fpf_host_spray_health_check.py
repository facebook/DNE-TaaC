# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe
"""Unit tests for FpfHostSprayHealthCheck (default vs all_samples modes)."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from neteng.netcastle.logger import ConsoleFileLogger
from taac.constants import TestDevice
from taac.health_checks.device_health_checks.fpf_host_spray_health_check import (
    FpfHostSprayHealthCheck,
)
from taac.health_check.health_check import types as hc_types

HOST_A = "rtptest1544.mwg2"
HOST_B = "rtptest1543.mwg2"

_MODULE = (
    "neteng.test_infra.dne.taac.health_checks.device_health_checks"
    ".fpf_host_spray_health_check"
)


def _key(lane: int) -> str:
    """ODS key name for a beth lane (e.g. system.beth0.tx-bytes-phy.rate)."""
    return f"system.beth{lane}.tx-bytes-phy.rate"


def _flat_series(lane_vals: dict, ts: int = 1000) -> dict:
    """One host's key_data with a single sample per lane (latest-mode shape)."""
    return {_key(lane): {ts: val} for lane, val in lane_vals.items()}


def _multi_series(lane_to_samples: dict) -> dict:
    """One host's key_data with multiple timestamped samples per lane.

    ``lane_to_samples`` maps lane index -> {ts: gbps}.
    """
    return {_key(lane): dict(samples) for lane, samples in lane_to_samples.items()}


class TestFpfHostSprayHealthCheck(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.logger = MagicMock(spec=ConsoleFileLogger)
        self.health_check = FpfHostSprayHealthCheck(logger=self.logger)
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "gtsw001.l1002.c087.mwg2"

    async def _run(self, ods_data, params):
        """Run the check with async_query_ods / URL helpers mocked out."""
        with (
            patch(f"{_MODULE}.async_query_ods", new=AsyncMock(return_value=ods_data)),
            patch(
                f"{_MODULE}.async_generate_ods_url",
                new=AsyncMock(return_value="raw_url"),
            ),
            patch(
                f"{_MODULE}.async_get_fburl",
                new=AsyncMock(return_value="https://fburl"),
            ),
            patch(
                f"{_MODULE}.get_test_case_start_time", new=MagicMock(return_value=0.0)
            ),
            patch(
                f"{_MODULE}.get_allow_baseline_failures",
                new=MagicMock(return_value=False),
            ),
        ):
            return await self.health_check._run(
                self.device, hc_types.BaseHealthCheckIn(), params
            )

    # ---- default mode (latest sample) -----------------------------------

    async def test_default_mode_pass_uniform_lanes(self):
        """All four lanes healthy and tight -> PASS (latest-sample mode)."""
        ods_data = {
            HOST_A: _flat_series({0: 98.0, 1: 98.5, 2: 99.0, 3: 98.2}),
            HOST_B: _flat_series({0: 97.0, 1: 97.5, 2: 98.0, 3: 97.2}),
        }
        result = await self._run(ods_data, {"hosts": [HOST_A, HOST_B]})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_default_mode_unaffected_by_early_dip(self):
        """A dip in an EARLY sample is ignored in default mode (latest only).

        beth0 dips to 1.0 at ts=1000 but recovers to 98.0 at the latest
        ts=2000; default mode reads only the latest sample, so it PASSES.
        This is the control that proves default behavior is unchanged.
        """
        ods_data = {
            HOST_A: _multi_series(
                {
                    0: {1000: 1.0, 2000: 98.0},
                    1: {1000: 98.0, 2000: 98.5},
                    2: {1000: 98.0, 2000: 99.0},
                    3: {1000: 98.0, 2000: 98.2},
                }
            ),
        }
        result = await self._run(ods_data, {"hosts": [HOST_A]})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    # ---- all_samples mode -----------------------------------------------

    async def test_all_samples_pass_when_every_sample_healthy(self):
        """all_samples=True PASSES when every sample on every lane is healthy."""
        ods_data = {
            HOST_A: _multi_series(
                {
                    0: {1000: 98.0, 2000: 98.4},
                    1: {1000: 98.2, 2000: 98.6},
                    2: {1000: 98.1, 2000: 98.5},
                    3: {1000: 98.3, 2000: 98.7},
                }
            ),
            HOST_B: _multi_series(
                {
                    0: {1000: 97.0, 2000: 97.4},
                    1: {1000: 97.2, 2000: 97.6},
                    2: {1000: 97.1, 2000: 97.5},
                    3: {1000: 97.3, 2000: 97.7},
                }
            ),
        }
        result = await self._run(
            ods_data, {"hosts": [HOST_A, HOST_B], "all_samples": True}
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("sample(s)", result.message)

    async def test_all_samples_fail_on_single_early_dip(self):
        """all_samples=True FAILS if ANY single sample dips below the floor.

        Same data as test_default_mode_unaffected_by_early_dip: beth0 dips to
        1.0 at the FIRST sample then recovers. Default mode passed; all_samples
        mode must FAIL because that one sample violates the floor.
        """
        ods_data = {
            HOST_A: _multi_series(
                {
                    0: {1000: 1.0, 2000: 98.0},
                    1: {1000: 98.0, 2000: 98.5},
                    2: {1000: 98.0, 2000: 99.0},
                    3: {1000: 98.0, 2000: 98.2},
                }
            ),
        }
        result = await self._run(ods_data, {"hosts": [HOST_A], "all_samples": True})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("Signal 1", result.message)

    async def test_all_samples_fail_on_second_host_lane_dip(self):
        """all_samples=True FAILS if any lane on the SECOND host dips on any sample."""
        ods_data = {
            HOST_A: _multi_series(
                {
                    0: {1000: 98.0, 2000: 98.4},
                    1: {1000: 98.2, 2000: 98.6},
                    2: {1000: 98.1, 2000: 98.5},
                    3: {1000: 98.3, 2000: 98.7},
                }
            ),
            HOST_B: _multi_series(
                {
                    0: {1000: 97.0, 2000: 97.4},
                    1: {1000: 97.2, 2000: 97.6},
                    2: {1000: 97.1, 2000: 97.5},
                    # beth3 dips at the SECOND sample.
                    3: {1000: 97.3, 2000: 2.0},
                }
            ),
        }
        result = await self._run(
            ods_data, {"hosts": [HOST_A, HOST_B], "all_samples": True}
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn(HOST_B, result.message)

    async def test_all_samples_transform_drops_latest_reducer(self):
        """all_samples=True must query ODS WITHOUT the ,latest reducer."""
        ods_data = {
            HOST_A: _multi_series(
                {
                    0: {1000: 98.0, 2000: 98.4},
                    1: {1000: 98.2, 2000: 98.6},
                    2: {1000: 98.1, 2000: 98.5},
                    3: {1000: 98.3, 2000: 98.7},
                }
            ),
        }
        mock_query = AsyncMock(return_value=ods_data)
        with (
            patch(f"{_MODULE}.async_query_ods", new=mock_query),
            patch(
                f"{_MODULE}.async_generate_ods_url",
                new=AsyncMock(return_value="raw_url"),
            ),
            patch(
                f"{_MODULE}.async_get_fburl",
                new=AsyncMock(return_value="https://fburl"),
            ),
            patch(
                f"{_MODULE}.get_test_case_start_time", new=MagicMock(return_value=0.0)
            ),
            patch(
                f"{_MODULE}.get_allow_baseline_failures",
                new=MagicMock(return_value=False),
            ),
        ):
            await self.health_check._run(
                self.device,
                hc_types.BaseHealthCheckIn(),
                {"hosts": [HOST_A], "all_samples": True},
            )
        transform = mock_query.await_args.kwargs["transform_desc"]
        self.assertNotIn("latest", transform)

    async def test_default_mode_transform_keeps_latest_reducer(self):
        """Default mode must query ODS WITH the ,latest reducer (unchanged)."""
        ods_data = {HOST_A: _flat_series({0: 98.0, 1: 98.5, 2: 99.0, 3: 98.2})}
        mock_query = AsyncMock(return_value=ods_data)
        with (
            patch(f"{_MODULE}.async_query_ods", new=mock_query),
            patch(
                f"{_MODULE}.async_generate_ods_url",
                new=AsyncMock(return_value="raw_url"),
            ),
            patch(
                f"{_MODULE}.async_get_fburl",
                new=AsyncMock(return_value="https://fburl"),
            ),
            patch(
                f"{_MODULE}.get_test_case_start_time", new=MagicMock(return_value=0.0)
            ),
            patch(
                f"{_MODULE}.get_allow_baseline_failures",
                new=MagicMock(return_value=False),
            ),
        ):
            await self.health_check._run(
                self.device, hc_types.BaseHealthCheckIn(), {"hosts": [HOST_A]}
            )
        transform = mock_query.await_args.kwargs["transform_desc"]
        self.assertIn("latest", transform)

    async def test_no_data_returns_skip(self):
        """Empty ODS result -> SKIP in both modes."""
        result = await self._run({}, {"hosts": [HOST_A], "all_samples": True})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.SKIP)
