# Copyright (c) Meta Platforms, Inc. and affiliates.

from __future__ import annotations

"""Pure verdict logic for the EBB separable-policy A/B sweep."""

import math
import typing as t
from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyEvaluationMeasurement:
    prefix_count: int
    total_hits: int
    total_runs: int
    total_time_us: float

    def validate(self) -> None:
        if self.prefix_count <= 0:
            raise ValueError("prefix_count must be positive")
        if self.total_hits <= 0:
            raise ValueError(
                f"policy measurement at {self.prefix_count} prefixes has no hits"
            )
        if self.total_runs <= 0:
            raise ValueError(
                f"policy measurement at {self.prefix_count} prefixes has no runs"
            )
        if not math.isfinite(self.total_time_us) or self.total_time_us <= 0:
            raise ValueError(
                f"policy measurement at {self.prefix_count} prefixes has invalid "
                f"processing time {self.total_time_us!r}"
            )


@dataclass(frozen=True)
class PolicyEvaluationVerdict:
    passed: bool
    baseline_slope_us_per_10k: float
    candidate_slope_us_per_10k: float
    slope_overhead_us_per_10k: float
    max_absolute_overhead_us: float
    overhead_us_by_prefix_count: t.Mapping[int, float]


def _index_measurements(
    measurements: t.Iterable[PolicyEvaluationMeasurement],
    *,
    arm: str,
) -> dict[int, PolicyEvaluationMeasurement]:
    indexed: dict[int, PolicyEvaluationMeasurement] = {}
    for measurement in measurements:
        measurement.validate()
        if measurement.prefix_count in indexed:
            raise ValueError(
                f"{arm} has duplicate measurement for {measurement.prefix_count} prefixes"
            )
        indexed[measurement.prefix_count] = measurement
    return indexed


def _slope_us_per_10k(
    measurements: t.Mapping[int, PolicyEvaluationMeasurement],
) -> float:
    xs = [float(prefix_count) for prefix_count in sorted(measurements)]
    ys = [measurements[int(prefix_count)].total_time_us for prefix_count in xs]
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    denominator = sum((x - x_mean) ** 2 for x in xs)
    if denominator <= 0:
        raise ValueError("at least two distinct prefix counts are required")
    slope_us_per_prefix = (
        sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denominator
    )
    return slope_us_per_prefix * 10_000.0


def evaluate_policy_evaluation_sweep(
    *,
    baseline: t.Iterable[PolicyEvaluationMeasurement],
    candidate: t.Iterable[PolicyEvaluationMeasurement],
    expected_prefix_counts: t.Iterable[int],
    max_absolute_overhead_us: float,
    max_slope_overhead_us_per_10k: float,
) -> PolicyEvaluationVerdict:
    """Compare complete accept-all and separable-policy sweeps.

    ``total_time_us`` follows the BGP policy-stat contract (runs × average
    evaluation time).  The absolute gate catches a uniformly expensive policy;
    the least-squares slope delta catches route-count-dependent growth.
    """
    if not math.isfinite(max_absolute_overhead_us) or max_absolute_overhead_us < 0:
        raise ValueError("max_absolute_overhead_us must be finite and non-negative")
    if (
        not math.isfinite(max_slope_overhead_us_per_10k)
        or max_slope_overhead_us_per_10k < 0
    ):
        raise ValueError(
            "max_slope_overhead_us_per_10k must be finite and non-negative"
        )

    expected = tuple(expected_prefix_counts)
    if len(expected) < 2 or any(value <= 0 for value in expected):
        raise ValueError(
            "expected_prefix_counts must contain two or more positive points"
        )
    if len(frozenset(expected)) != len(expected):
        raise ValueError("expected_prefix_counts must be unique")
    expected_set = frozenset(expected)

    baseline_by_count = _index_measurements(baseline, arm="baseline")
    candidate_by_count = _index_measurements(candidate, arm="candidate")
    for arm, actual in (
        ("baseline", frozenset(baseline_by_count)),
        ("candidate", frozenset(candidate_by_count)),
    ):
        if actual != expected_set:
            raise ValueError(
                f"{arm} prefix counts {sorted(actual)} do not match expected "
                f"{sorted(expected_set)}"
            )

    overheads = {
        prefix_count: (
            candidate_by_count[prefix_count].total_time_us
            - baseline_by_count[prefix_count].total_time_us
        )
        for prefix_count in sorted(expected_set)
    }
    max_overhead = max(overheads.values())
    baseline_slope = _slope_us_per_10k(baseline_by_count)
    candidate_slope = _slope_us_per_10k(candidate_by_count)
    slope_overhead = candidate_slope - baseline_slope
    passed = (
        max_overhead <= max_absolute_overhead_us
        and slope_overhead <= max_slope_overhead_us_per_10k
    )
    return PolicyEvaluationVerdict(
        passed=passed,
        baseline_slope_us_per_10k=baseline_slope,
        candidate_slope_us_per_10k=candidate_slope,
        slope_overhead_us_per_10k=slope_overhead,
        max_absolute_overhead_us=max_overhead,
        overhead_us_by_prefix_count=overheads,
    )


__all__ = (
    "PolicyEvaluationMeasurement",
    "PolicyEvaluationVerdict",
    "evaluate_policy_evaluation_sweep",
)
