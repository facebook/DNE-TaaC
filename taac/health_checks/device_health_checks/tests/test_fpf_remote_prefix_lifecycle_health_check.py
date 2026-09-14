# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from taac.constants import TestDevice
from taac.health_checks.device_health_checks.fpf_remote_prefix_lifecycle_health_check import (
    _allowed_error_interval,
    FpfRemotePrefixLifecycleHealthCheck,
)
from taac.health_check.health_check import types as hc_types

HC_MODULE = (
    "neteng.test_infra.dne.taac.health_checks.device_health_checks."
    "fpf_remote_prefix_lifecycle_health_check"
)
WINDOW_START = 1_700_000_000.0
RUNNER = "gtsw001.l1002.c087.mwg2"


def _ts(offset_sec: float) -> str:
    return datetime.fromtimestamp(WINDOW_START + offset_sec, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S.%f%z"
    )


class FpfRemotePrefixLifecycleHealthCheckTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.health_check = FpfRemotePrefixLifecycleHealthCheck(logger=MagicMock())
        self.device = MagicMock(spec=TestDevice)
        self.device.name = RUNNER

    async def _run(
        self,
        params: dict,
        *,
        collector: object | None = None,
    ) -> hc_types.HealthCheckResult:
        with (
            patch(
                f"{HC_MODULE}.time.time",
                side_effect=[WINDOW_START + 20, WINDOW_START + 30],
            ),
            patch(f"{HC_MODULE}.get_collector", return_value=collector),
            patch(f"{HC_MODULE}.get_test_case_start_time", return_value=0.0),
            patch(
                f"{HC_MODULE}.everpaste_details_suffix",
                new=AsyncMock(return_value=""),
            ),
        ):
            return await self.health_check._run(
                self.device,
                hc_types.BaseHealthCheckIn(),
                params,
            )

    async def test_non_runner_device_skips(self) -> None:
        self.device.name = "gtsw002.l1002.c087.mwg2"

        result = await self._run({"runner_device": RUNNER})

        self.assertEqual(result.status, hc_types.HealthCheckStatus.SKIP)

    async def test_unknown_mode_fails(self) -> None:
        result = await self._run({"mode": "unexpected"})

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("Unknown lifecycle mode", str(result.message))

    async def test_missing_transition_anchor_fails(self) -> None:
        with patch(f"{HC_MODULE}.get_restart_completion_time", return_value=0.0):
            result = await self._run({"mode": "withdrawn"})

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("No recorded anchor timestamp", str(result.message))

    async def test_missing_collector_fails(self) -> None:
        result = await self._run(
            {
                "mode": "present",
                "scalar_expectations": [["bgp", RUNNER, 1000]],
            }
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("1 exact lifecycle assertion", str(result.message))

    async def test_scalar_rows_are_filtered_to_expected_device(self) -> None:
        collector = SimpleNamespace(
            rows=[
                SimpleNamespace(
                    timestamp=_ts(25),
                    gtsw=RUNNER,
                    matched=1000,
                    valid=True,
                    notes="",
                ),
                SimpleNamespace(
                    timestamp=_ts(26),
                    gtsw="gtsw009.l1002.c087.mwg2",
                    matched=0,
                    valid=True,
                    notes="",
                ),
            ]
        )

        result = await self._run(
            {
                "mode": "present",
                "scalar_expectations": [["bgp", RUNNER, 1000]],
            },
            collector=collector,
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_short_lane_counts_fail_without_exception(self) -> None:
        collector = SimpleNamespace(
            rows=[
                SimpleNamespace(
                    timestamp=_ts(25),
                    host="rtptest1544.mwg2",
                    device_id=0,
                    plane_ids=[0],
                    lane_counts=[],
                    valid=True,
                    notes="",
                )
            ]
        )

        result = await self._run(
            {
                "mode": "present",
                "hrt_expectations": [
                    {
                        "collector": "hrt",
                        "expected": {"rtptest1544.mwg2": {"0": [1000]}},
                    }
                ],
            },
            collector=collector,
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)

    def test_allowed_interval_ignores_malformed_timestamp(self) -> None:
        rows = [
            SimpleNamespace(timestamp="not-a-timestamp", valid=True, notes=""),
            SimpleNamespace(
                timestamp=_ts(10),
                valid=True,
                notes="",
            ),
        ]

        self.assertEqual(
            _allowed_error_interval(rows, WINDOW_START, WINDOW_START + 5),
            ((WINDOW_START, WINDOW_START + 10),),
        )


if __name__ == "__main__":
    unittest.main()
