# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import inspect
import json
import typing as t
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from taac.health_checks.device_health_checks.cpu_percentile_health_check import (
    CpuPercentileHealthCheck,
)
from taac.health_checks.device_health_checks.rss_delta_health_check import (
    RssDeltaHealthCheck,
)
from taac.health_checks.healthcheck_definitions import (
    create_cpu_percentile_observe_check,
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


def _cpu_summary(p95: float = 50.0, n: int = 10) -> dict:
    """A well-formed CPU STOP summary with a finite percentile distribution."""
    return {
        "n": n,
        "window_s": 20.0,
        "peak_pct": p95 + 5.0,
        "raw": {"p70": 20.0, "p80": 30.0, "p95": p95, "p99": p95 + 2.0},
        "per_core": None,
        "cores": None,
    }


class NewCharacterizationHealthChecksTest(unittest.TestCase):
    def test_checks_are_concrete(self) -> None:
        # Guards against leaving the abstract _run unimplemented -- a
        # runtime-only instantiation TypeError that the build does not catch
        # (overriding only _run_arista is NOT enough to satisfy the abstract).
        self.assertFalse(inspect.isabstract(CpuPercentileHealthCheck))
        self.assertFalse(inspect.isabstract(RssDeltaHealthCheck))

    def test_check_names(self) -> None:
        self.assertEqual(
            CpuPercentileHealthCheck.CHECK_NAME,
            hc_types.CheckName.CPU_PERCENTILE_CHECK,
        )
        self.assertEqual(
            RssDeltaHealthCheck.CHECK_NAME, hc_types.CheckName.RSS_DELTA_CHECK
        )


class CpuPercentileHealthCheckFactoryTest(unittest.TestCase):
    def test_empty_gate_map_allows_legacy_scalar_gate(self) -> None:
        check = create_cpu_percentile_observe_check(
            gate_threshold_pct=55.0,
            gate_thresholds_pct={},
        )

        check_params = check.check_params
        self.assertIsNotNone(check_params)
        assert check_params is not None
        self.assertIsNotNone(check_params.json_params)
        payload = json.loads(t.cast(str, check_params.json_params))
        self.assertEqual(55.0, payload["gate_threshold_pct"])
        self.assertNotIn("gate_thresholds_pct", payload)

    def test_integral_float_percentile_key_is_normalized(self) -> None:
        check = create_cpu_percentile_observe_check(gate_thresholds_pct={95.0: 60.0})

        check_params = check.check_params
        self.assertIsNotNone(check_params)
        assert check_params is not None
        self.assertIsNotNone(check_params.json_params)
        payload = json.loads(t.cast(str, check_params.json_params))
        self.assertEqual({"95": 60.0}, payload["gate_thresholds_pct"])

    def test_fractional_percentile_key_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be an integer"):
            create_cpu_percentile_observe_check(gate_thresholds_pct={95.5: 60.0})


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


class CpuPercentileHealthCheckRunTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.hc = CpuPercentileHealthCheck(logger=MagicMock())

    async def _run(self, check_params: dict) -> hc_types.HealthCheckResult:
        obj = t.cast(t.Any, SimpleNamespace(name="dut"))
        return await self.hc._run(obj, t.cast(t.Any, None), check_params)

    async def test_missing_summary_fails(self) -> None:
        result = await self._run({})
        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("missing", (result.message or "").lower())

    async def test_zero_sample_inf_summary_fails(self) -> None:
        # Sampler collected nothing: raw is a truthy dict of inf and n=0. Must
        # FAIL loudly rather than PASS with an inf% value in observe-only mode.
        inf = float("inf")
        summary = {
            "n": 0,
            "window_s": 20.0,
            "peak_pct": 0.0,
            "raw": {"p70": inf, "p80": inf, "p95": inf, "p99": inf},
        }
        result = await self._run({"summary": summary})
        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)

    async def test_malformed_non_dict_raw_fails_cleanly(self) -> None:
        # A truthy but non-dict raw (e.g. a list) must produce a clean FAIL, not
        # crash the reporter on raw.values()/raw.items().
        result = await self._run(
            {"summary": {"n": 5, "window_s": 20.0, "peak_pct": 1.0, "raw": [1, 2]}}
        )
        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)

    async def test_observe_only_passes_with_metrics(self) -> None:
        result = await self._run({"summary": _cpu_summary(p95=50.0)})
        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertIn("observe-only", result.message or "")
        self.assertIn("p95=50.0%", result.message or "")

    async def test_gate_under_threshold_passes(self) -> None:
        result = await self._run(
            {"summary": _cpu_summary(p95=50.0), "gate_threshold_pct": 80.0}
        )
        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertIn("within threshold", result.message or "")

    async def test_gate_over_threshold_fails(self) -> None:
        result = await self._run(
            {"summary": _cpu_summary(p95=50.0), "gate_threshold_pct": 40.0}
        )
        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("exceeds", (result.message or "").lower())

    async def test_multiple_gates_pass_and_preserve_all_percentiles(self) -> None:
        result = await self._run(
            {
                "summary": _cpu_summary(p95=50.0),
                "gate_thresholds_pct": {"80": 35.0, "95": 60.0},
            }
        )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        message = result.message or ""
        for percentile in ("p70", "p80", "p95", "p99"):
            self.assertIn(percentile, message)
        self.assertIn("p80=30.0%", message)
        self.assertIn("p95=50.0%", message)
        self.assertIn("threshold=35.0%", message)
        self.assertIn("threshold=60.0%", message)
        self.assertIn("within", message)

    async def test_multiple_gates_fail_when_one_exceeds_threshold(self) -> None:
        result = await self._run(
            {
                "summary": _cpu_summary(p95=50.0),
                "gate_thresholds_pct": {"80": 35.0, "95": 45.0},
            }
        )

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        message = result.message or ""
        self.assertIn("p95=50.0%", message)
        self.assertIn("threshold=45.0%", message)
        self.assertIn("exceeds", message)

    async def test_multiple_gates_fail_when_percentile_was_not_collected(
        self,
    ) -> None:
        result = await self._run(
            {
                "summary": _cpu_summary(p95=50.0),
                "gate_thresholds_pct": {"80": 35.0, "90": 45.0},
            }
        )

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        message = result.message or ""
        self.assertIn("p90", message)
        self.assertIn("not collected", message)

    async def test_multiple_missing_percentiles_use_plural_message(self) -> None:
        result = await self._run(
            {
                "summary": _cpu_summary(p95=50.0),
                "gate_thresholds_pct": {"90": 45.0, "100": 60.0},
            }
        )

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        message = result.message or ""
        self.assertIn("p90, p100", message)
        self.assertIn("percentiles were not collected", message)

    async def test_gate_observations_are_sorted_by_numeric_percentile(self) -> None:
        summary = _cpu_summary(p95=50.0)
        summary["raw"]["p100"] = 60.0
        result = await self._run(
            {
                "summary": summary,
                "gate_thresholds_pct": {"100": 65.0, "80": 35.0},
            }
        )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        message = result.message or ""
        self.assertLess(message.rfind("p80="), message.rfind("p100="))

    async def test_gate_on_uncollected_percentile_fails(self) -> None:
        # Gate requested on a percentile the STOP step never stashed (only
        # p70/p80/p95/p99 collected) must FAIL loudly, not silently PASS.
        result = await self._run(
            {
                "summary": _cpu_summary(p95=50.0),
                "gate_threshold_pct": 40.0,
                "gate_percentile": 90.0,
            }
        )
        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("not collected", (result.message or "").lower())


if __name__ == "__main__":
    unittest.main()
