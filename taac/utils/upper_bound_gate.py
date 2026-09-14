# Copyright (c) Meta Platforms, Inc. and affiliates.

from __future__ import annotations

import dataclasses
import typing as t


@dataclasses.dataclass(frozen=True)
class UpperBoundObservation:
    metric: str
    value: float
    threshold: float

    @property
    def passed(self) -> bool:
        return self.value <= self.threshold


@dataclasses.dataclass(frozen=True)
class UpperBoundGateResult:
    observations: tuple[UpperBoundObservation, ...]
    missing_metrics: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.missing_metrics and all(
            observation.passed for observation in self.observations
        )


def evaluate_upper_bound_gates(
    values: t.Mapping[str, object], thresholds: t.Mapping[str, float]
) -> UpperBoundGateResult:
    """Evaluate independent upper bounds with AND semantics.

    Missing or non-numeric observations fail the aggregate gate so callers
    cannot silently pass when a configured signal was not collected.
    """
    observations: list[UpperBoundObservation] = []
    missing_metrics: list[str] = []
    for metric, threshold in thresholds.items():
        value = values.get(metric)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            missing_metrics.append(metric)
            continue
        observations.append(
            UpperBoundObservation(
                metric=metric,
                value=float(value),
                threshold=threshold,
            )
        )
    return UpperBoundGateResult(
        observations=tuple(observations),
        missing_metrics=tuple(missing_metrics),
    )
