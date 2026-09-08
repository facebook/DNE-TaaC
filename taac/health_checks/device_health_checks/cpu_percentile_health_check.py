# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Reporter health check for the BGP++ (``bgpcpp``) CPU percentile characterization.

The measurement is a SPANNING one: a START/STOP collector pair samples process
CPU during a phase (e.g. convergence) and, at STOP, stashes the computed
percentile summary into a jq variable. This point-in-time postcheck reads that
summary and reports it into the POST-HEALTH CHECK RESULTS table so the numbers
are visible run-over-run.

Observe-only by default: with no threshold it always PASSes and puts every
measured percentile in the message. Supply the legacy scalar gate or a
percentile-to-threshold map to gate one or more raw percentiles. A missing
summary (the STOP collector never ran) FAILs loudly -- never a silent pass.
"""

import math
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.utils.upper_bound_gate import evaluate_upper_bound_gates
from taac.health_check.health_check import types as hc_types


class CpuPercentileHealthCheck(AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]):
    CHECK_NAME = hc_types.CheckName.CPU_PERCENTILE_CHECK
    OPERATING_SYSTEMS = ["EOS"]
    LOG_TO_SCUBA = True

    def _format_message(self, summary: t.Dict[str, t.Any], suffix: str) -> str:
        # Guard on isinstance, not truthiness: a malformed non-dict raw/per_core
        # would otherwise crash the reporter on .items()/.get() rather than
        # produce a clean line.
        raw = summary.get("raw")
        raw = raw if isinstance(raw, dict) else {}
        per_core = summary.get("per_core")
        per_core = per_core if isinstance(per_core, dict) else {}
        # Sort on the numeric percentile, not the string key, so a three-digit
        # percentile (e.g. p100) does not sort before p70 lexicographically.
        raw_str = " ".join(
            f"p{k[1:]}={v:.1f}%"
            for k, v in sorted(raw.items(), key=lambda kv: int(kv[0][1:]))
        )
        core_str = ""
        cores = summary.get("cores")
        if per_core and cores:
            pc95 = per_core.get("p95")
            if pc95 is not None:
                core_str = f", per-core/{cores}: p95={pc95:.1f}%"
        return (
            f"{raw_str} (peak={summary.get('peak_pct', 0.0):.1f}% "
            f"n={summary.get('n', 0)} window={summary.get('window_s', 0.0):.0f}s"
            f"{core_str}) {suffix}"
        )

    @staticmethod
    def _gate_thresholds(check_params: t.Dict[str, t.Any]) -> t.Dict[int, float]:
        configured_gates = check_params.get("gate_thresholds_pct")
        if configured_gates is not None:
            if not isinstance(configured_gates, dict):
                raise ValueError("gate_thresholds_pct must be a mapping")
            gates = {
                int(percentile): float(threshold)
                for percentile, threshold in configured_gates.items()
            }
            if any(not math.isfinite(threshold) for threshold in gates.values()):
                raise ValueError("gate thresholds must be finite")
            return gates

        gate_threshold_pct = check_params.get("gate_threshold_pct")
        if gate_threshold_pct is None:
            return {}
        return {
            int(float(check_params.get("gate_percentile", 95.0))): float(
                gate_threshold_pct
            )
        }

    def _evaluate(
        self, obj: TestDevice, check_params: t.Dict[str, t.Any]
    ) -> hc_types.HealthCheckResult:
        summary = check_params.get("summary")
        raw = summary.get("raw") if isinstance(summary, dict) else None
        n_samples = summary.get("n", 0) if isinstance(summary, dict) else 0
        # A truthy `raw` alone is not enough: when the sampler collected zero
        # samples the STOP step still stashes raw={p..: inf} (a truthy dict of
        # non-finite values). A signal we cannot actually measure -- no summary,
        # zero samples, or non-finite percentiles -- must FAIL loudly, even in
        # observe-only mode.
        raw_finite = (
            isinstance(raw, dict)
            and bool(raw)
            and all(
                isinstance(v, (int, float)) and math.isfinite(v) for v in raw.values()
            )
        )
        if not isinstance(summary, dict) or not n_samples or not raw_finite:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    f"CPU percentile summary missing on {obj.name}: the "
                    f"START/STOP collector stashed no finite result "
                    f"(n={n_samples})."
                ),
            )
        self.add_data_to_log(summary)

        try:
            gate_thresholds = self._gate_thresholds(check_params)
        except (TypeError, ValueError) as error:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=self._format_message(
                    summary, f"invalid CPU percentile gate configuration: {error}"
                ),
            )
        if not gate_thresholds:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.PASS,
                message=self._format_message(summary, "(observe-only)"),
            )

        gate_result = evaluate_upper_bound_gates(
            values=raw,
            thresholds={
                f"p{percentile}": threshold
                for percentile, threshold in sorted(gate_thresholds.items())
            },
        )
        observations: t.List[str] = []
        for observation in gate_result.observations:
            relation = "within" if observation.passed else "exceeds"
            observations.append(
                f"{observation.metric}={observation.value:.1f}% {relation} "
                f"threshold={observation.threshold:.1f}%"
            )
        if gate_result.missing_metrics:
            have = ",".join(sorted(raw))
            missing = ", ".join(gate_result.missing_metrics)
            subject = (
                "that percentile was"
                if len(gate_result.missing_metrics) == 1
                else "those percentiles were"
            )
            observations.append(
                f"gate requested on {missing} but {subject} not collected "
                f"(have: {have})"
            )
        status = (
            hc_types.HealthCheckStatus.PASS
            if gate_result.passed
            else hc_types.HealthCheckStatus.FAIL
        )
        return hc_types.HealthCheckResult(
            status=status,
            message=self._format_message(summary, "; ".join(observations)),
        )

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        return self._evaluate(obj, check_params)
