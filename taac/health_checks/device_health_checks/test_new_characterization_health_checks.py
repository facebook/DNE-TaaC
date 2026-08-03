# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import inspect
import typing as t
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from taac.health_checks.device_health_checks.rss_delta_health_check import (
    RssDeltaHealthCheck,
)
from taac.health_check.health_check import types as hc_types

_MIB = 1024 * 1024


def _summary(growth_pct: float = 10.0, restarted: bool = False) -> dict:
    """A well-formed STOP summary: baseline 100MiB -> current 110MiB (10% growth)."""
    return {
        "baseline_bytes": 100 * _MIB,
        "current_bytes": 110 * _MIB,
        "peak_bytes": 112 * _MIB,
        "growth_pct": growth_pct,
        "restarted": restarted,
    }


class NewCharacterizationHealthChecksTest(unittest.TestCase):
    def test_checks_are_concrete(self) -> None:
        # Guards against leaving the abstract _run unimplemented -- a
        # runtime-only instantiation TypeError that the build does not catch
        # (overriding only _run_arista is NOT enough to satisfy the abstract).
        self.assertFalse(inspect.isabstract(RssDeltaHealthCheck))

    def test_check_names(self) -> None:
        self.assertEqual(
            RssDeltaHealthCheck.CHECK_NAME, hc_types.CheckName.RSS_DELTA_CHECK
        )


class RssDeltaHealthCheckRunTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.hc = RssDeltaHealthCheck(logger=MagicMock())

    async def _run(self, check_params: dict) -> hc_types.HealthCheckResult:
        # The reader only reads check_params; obj/input are cast to Any since the
        # test supplies lightweight stand-ins.
        obj = t.cast(t.Any, SimpleNamespace(name="dut"))
        return await self.hc._run(obj, t.cast(t.Any, None), check_params)

    async def test_missing_summary_fails(self) -> None:
        result = await self._run({})
        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("missing", (result.message or "").lower())

    async def test_incomplete_summary_fails(self) -> None:
        # Present but without current_bytes -> treated as not-stashed.
        result = await self._run({"summary": {"baseline_bytes": 100 * _MIB}})
        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)

    async def test_restarted_fails(self) -> None:
        result = await self._run({"summary": _summary(restarted=True)})
        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("restarted", (result.message or "").lower())

    async def test_observe_only_passes_with_metrics(self) -> None:
        result = await self._run({"summary": _summary(growth_pct=10.0)})
        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertIn("observe-only", result.message or "")
        # Uses the STOP-stashed growth_pct directly (full precision).
        self.assertIn("growth=10.0%", result.message or "")

    async def test_gate_under_threshold_passes(self) -> None:
        result = await self._run(
            {"summary": _summary(growth_pct=10.0), "max_growth_pct": 15.0}
        )
        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertIn("within threshold", result.message or "")

    async def test_gate_over_threshold_fails(self) -> None:
        result = await self._run(
            {"summary": _summary(growth_pct=10.0), "max_growth_pct": 5.0}
        )
        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("exceeds threshold", result.message or "")


if __name__ == "__main__":
    unittest.main()
