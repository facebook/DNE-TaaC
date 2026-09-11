# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""Runtime-neutral intent and flat-step lowering for route churn."""

from __future__ import annotations

import dataclasses
import typing as t

from taac.abstractions.churn.policies import (
    ExecutionPolicy,
    PreparationPolicy,
    RecoveryPolicy,
)
from taac.abstractions.churn.specs import (
    ChurnFamily,
    ChurnScenario,
    ChurnWorkload,
)


DEFAULT_ROUTE_CHURN_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_ROUTE_CHURN_TRANSITION_SOFT_THRESHOLD_SECONDS = 60.0
DEFAULT_ROUTE_CHURN_TRANSITION_HARD_TIMEOUT_SECONDS = 300.0
DEFAULT_ROUTE_CHURN_CONFIRMATION_SECONDS = 5.0
DEFAULT_ROUTE_CHURN_RESTORE_SOFT_THRESHOLD_SECONDS = 120.0
DEFAULT_ROUTE_CHURN_RESTORE_HARD_TIMEOUT_SECONDS = 300.0
DEFAULT_ROUTE_CHURN_QUIET_WINDOW_SECONDS = 30.0
DEFAULT_ROUTE_CHURN_MAX_LOOKUP_CONCURRENCY = 8
DEFAULT_ROUTE_CHURN_SAMPLE_PEER_COUNT = 7
DEFAULT_ROUTE_CHURN_SAMPLE_ROUTE_COUNT = 3
DEFAULT_ROUTE_CHURN_LOOKUP_ATTEMPTS = 3
DEFAULT_ROUTE_CHURN_LOOKUP_RETRY_SECONDS = 1.0
DEFAULT_ROUTE_CHURN_MAX_CONSECUTIVE_OBSERVATION_FAILURES = 3
DEFAULT_ROUTE_CHURN_CANCELLATION_GRACE_SECONDS = 10.0


def _json_number(value: float) -> int | float:
    return int(value) if value.is_integer() else value


@dataclasses.dataclass(frozen=True)
class RouteTargetSelector:
    prefix_pool_regex: str
    expected_prefix_pool_names: tuple[str, ...]
    prefix_start_index: int
    prefix_end_index: int
    expected_established_sessions: int
    parent_prefixes_to_ignore: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            self.prefix_start_index < 0
            or self.prefix_end_index <= self.prefix_start_index
        ):
            raise ValueError("prefix range must be nonempty and half-open")


@dataclasses.dataclass(frozen=True)
class RouteCyclePolicy:
    withdraw_seconds: float
    readvertise_seconds: float

    def __post_init__(self) -> None:
        if self.withdraw_seconds <= 0 or self.readvertise_seconds <= 0:
            raise ValueError("withdraw and readvertise durations must be positive")


@dataclasses.dataclass(frozen=True)
class RouteObservationPolicy:
    poll_interval_seconds: float = DEFAULT_ROUTE_CHURN_POLL_INTERVAL_SECONDS
    transition_soft_threshold_seconds: float = (
        DEFAULT_ROUTE_CHURN_TRANSITION_SOFT_THRESHOLD_SECONDS
    )
    transition_hard_timeout_seconds: float = (
        DEFAULT_ROUTE_CHURN_TRANSITION_HARD_TIMEOUT_SECONDS
    )
    confirmation_seconds: float = DEFAULT_ROUTE_CHURN_CONFIRMATION_SECONDS
    restore_soft_threshold_seconds: float = (
        DEFAULT_ROUTE_CHURN_RESTORE_SOFT_THRESHOLD_SECONDS
    )
    restore_hard_timeout_seconds: float = (
        DEFAULT_ROUTE_CHURN_RESTORE_HARD_TIMEOUT_SECONDS
    )
    quiet_window_seconds: float = DEFAULT_ROUTE_CHURN_QUIET_WINDOW_SECONDS
    max_lookup_concurrency: int = DEFAULT_ROUTE_CHURN_MAX_LOOKUP_CONCURRENCY
    sample_peer_count: int = DEFAULT_ROUTE_CHURN_SAMPLE_PEER_COUNT
    sample_route_count: int = DEFAULT_ROUTE_CHURN_SAMPLE_ROUTE_COUNT
    lookup_attempts: int = DEFAULT_ROUTE_CHURN_LOOKUP_ATTEMPTS
    lookup_retry_seconds: float = DEFAULT_ROUTE_CHURN_LOOKUP_RETRY_SECONDS
    max_consecutive_observation_failures: int = (
        DEFAULT_ROUTE_CHURN_MAX_CONSECUTIVE_OBSERVATION_FAILURES
    )
    fail_on_session_flap: bool = True


@dataclasses.dataclass(frozen=True)
class RouteChurn:
    scenario: ChurnScenario
    selector: RouteTargetSelector
    cycle: RouteCyclePolicy
    observation: RouteObservationPolicy = RouteObservationPolicy()

    def to_step_params(self) -> dict[str, t.Any]:
        """Lower typed route intent to the established CustomStep contract."""
        params: dict[str, t.Any] = {
            "prefix_pool_regex": self.selector.prefix_pool_regex,
            "expected_prefix_pool_names": list(
                self.selector.expected_prefix_pool_names
            ),
            "expected_established_sessions": (
                self.selector.expected_established_sessions
            ),
            "prefix_start_index": self.selector.prefix_start_index,
            "prefix_end_index": self.selector.prefix_end_index,
            "withdraw_time": _json_number(self.cycle.withdraw_seconds),
            "readvertise_time": _json_number(self.cycle.readvertise_seconds),
            "test_duration_seconds": _json_number(
                self.scenario.execution.duration_seconds
            ),
            "parent_prefixes_to_ignore": list(self.selector.parent_prefixes_to_ignore),
        }
        optional_defaults: tuple[tuple[str, t.Any, t.Any], ...] = (
            (
                "poll_interval_seconds",
                self.observation.poll_interval_seconds,
                DEFAULT_ROUTE_CHURN_POLL_INTERVAL_SECONDS,
            ),
            (
                "transition_soft_threshold_seconds",
                self.observation.transition_soft_threshold_seconds,
                DEFAULT_ROUTE_CHURN_TRANSITION_SOFT_THRESHOLD_SECONDS,
            ),
            (
                "transition_hard_timeout_seconds",
                self.observation.transition_hard_timeout_seconds,
                DEFAULT_ROUTE_CHURN_TRANSITION_HARD_TIMEOUT_SECONDS,
            ),
            (
                "confirmation_seconds",
                self.observation.confirmation_seconds,
                DEFAULT_ROUTE_CHURN_CONFIRMATION_SECONDS,
            ),
            (
                "restore_soft_threshold_seconds",
                self.observation.restore_soft_threshold_seconds,
                DEFAULT_ROUTE_CHURN_RESTORE_SOFT_THRESHOLD_SECONDS,
            ),
            (
                "restore_hard_timeout_seconds",
                self.observation.restore_hard_timeout_seconds,
                DEFAULT_ROUTE_CHURN_RESTORE_HARD_TIMEOUT_SECONDS,
            ),
            (
                "quiet_window_seconds",
                self.observation.quiet_window_seconds,
                DEFAULT_ROUTE_CHURN_QUIET_WINDOW_SECONDS,
            ),
            (
                "max_lookup_concurrency",
                self.observation.max_lookup_concurrency,
                DEFAULT_ROUTE_CHURN_MAX_LOOKUP_CONCURRENCY,
            ),
            (
                "sample_peer_count",
                self.observation.sample_peer_count,
                DEFAULT_ROUTE_CHURN_SAMPLE_PEER_COUNT,
            ),
            (
                "sample_route_count",
                self.observation.sample_route_count,
                DEFAULT_ROUTE_CHURN_SAMPLE_ROUTE_COUNT,
            ),
            (
                "lookup_attempts",
                self.observation.lookup_attempts,
                DEFAULT_ROUTE_CHURN_LOOKUP_ATTEMPTS,
            ),
            (
                "lookup_retry_seconds",
                self.observation.lookup_retry_seconds,
                DEFAULT_ROUTE_CHURN_LOOKUP_RETRY_SECONDS,
            ),
            (
                "max_consecutive_observation_failures",
                self.observation.max_consecutive_observation_failures,
                DEFAULT_ROUTE_CHURN_MAX_CONSECUTIVE_OBSERVATION_FAILURES,
            ),
            ("fail_on_session_flap", self.observation.fail_on_session_flap, True),
        )
        for name, value, default in optional_defaults:
            if value != default:
                params[name] = (
                    _json_number(value) if isinstance(value, float) else value
                )
        return params

    @classmethod
    def from_step_params(cls, params: t.Mapping[str, t.Any]) -> RouteChurn:
        duration = float(params.get("test_duration_seconds", 120.0))
        withdraw = float(params.get("withdraw_time", 60.0))
        readvertise = float(params.get("readvertise_time", 60.0))
        cycle = RouteCyclePolicy(withdraw, readvertise)
        cycle_seconds = cycle.withdraw_seconds + cycle.readvertise_seconds
        cycle_count = max(1, int(duration // cycle_seconds))
        transition_timeout = float(
            params.get(
                "transition_hard_timeout_seconds",
                DEFAULT_ROUTE_CHURN_TRANSITION_HARD_TIMEOUT_SECONDS,
            )
        )
        return cls(
            scenario=ChurnScenario(
                scenario_id=str(params.get("scenario_id", "bgp_route_oscillation")),
                workload=ChurnWorkload(families=(ChurnFamily(name="routes"),)),
                preparation=PreparationPolicy(
                    initial_resolution_timeout_seconds=transition_timeout,
                    baseline_capture_timeout_seconds=transition_timeout,
                    total_timeout_seconds=(
                        duration + (2.0 * transition_timeout * cycle_count)
                    ),
                ),
                execution=ExecutionPolicy(
                    duration_seconds=duration,
                    cadence_seconds=cycle_seconds,
                    max_iterations=cycle_count,
                ),
                recovery=RecoveryPolicy(
                    total_timeout_seconds=float(
                        params.get(
                            "restore_hard_timeout_seconds",
                            DEFAULT_ROUTE_CHURN_RESTORE_HARD_TIMEOUT_SECONDS,
                        )
                    )
                    + DEFAULT_ROUTE_CHURN_CANCELLATION_GRACE_SECONDS,
                    restore_observation_timeout_seconds=float(
                        params.get(
                            "restore_hard_timeout_seconds",
                            DEFAULT_ROUTE_CHURN_RESTORE_HARD_TIMEOUT_SECONDS,
                        )
                    ),
                    ixia_restore_timeout_seconds=float(
                        params.get(
                            "restore_hard_timeout_seconds",
                            DEFAULT_ROUTE_CHURN_RESTORE_HARD_TIMEOUT_SECONDS,
                        )
                    ),
                    cancellation_grace_seconds=DEFAULT_ROUTE_CHURN_CANCELLATION_GRACE_SECONDS,
                ),
            ),
            selector=RouteTargetSelector(
                prefix_pool_regex=str(params.get("prefix_pool_regex", "")),
                expected_prefix_pool_names=tuple(
                    str(name) for name in params.get("expected_prefix_pool_names", ())
                ),
                prefix_start_index=int(params.get("prefix_start_index", 0)),
                prefix_end_index=int(params.get("prefix_end_index", 1)),
                expected_established_sessions=int(
                    params.get("expected_established_sessions", 0)
                ),
                parent_prefixes_to_ignore=tuple(
                    str(prefix)
                    for prefix in params.get("parent_prefixes_to_ignore", ())
                ),
            ),
            cycle=cycle,
            observation=RouteObservationPolicy(
                poll_interval_seconds=float(
                    params.get(
                        "poll_interval_seconds",
                        DEFAULT_ROUTE_CHURN_POLL_INTERVAL_SECONDS,
                    )
                ),
                transition_soft_threshold_seconds=float(
                    params.get(
                        "transition_soft_threshold_seconds",
                        DEFAULT_ROUTE_CHURN_TRANSITION_SOFT_THRESHOLD_SECONDS,
                    )
                ),
                transition_hard_timeout_seconds=transition_timeout,
                confirmation_seconds=float(
                    params.get(
                        "confirmation_seconds",
                        DEFAULT_ROUTE_CHURN_CONFIRMATION_SECONDS,
                    )
                ),
                restore_soft_threshold_seconds=float(
                    params.get(
                        "restore_soft_threshold_seconds",
                        DEFAULT_ROUTE_CHURN_RESTORE_SOFT_THRESHOLD_SECONDS,
                    )
                ),
                restore_hard_timeout_seconds=float(
                    params.get(
                        "restore_hard_timeout_seconds",
                        DEFAULT_ROUTE_CHURN_RESTORE_HARD_TIMEOUT_SECONDS,
                    )
                ),
                quiet_window_seconds=float(
                    params.get(
                        "quiet_window_seconds",
                        DEFAULT_ROUTE_CHURN_QUIET_WINDOW_SECONDS,
                    )
                ),
                max_lookup_concurrency=int(
                    params.get(
                        "max_lookup_concurrency",
                        DEFAULT_ROUTE_CHURN_MAX_LOOKUP_CONCURRENCY,
                    )
                ),
                sample_peer_count=int(
                    params.get(
                        "sample_peer_count", DEFAULT_ROUTE_CHURN_SAMPLE_PEER_COUNT
                    )
                ),
                sample_route_count=int(
                    params.get(
                        "sample_route_count", DEFAULT_ROUTE_CHURN_SAMPLE_ROUTE_COUNT
                    )
                ),
                lookup_attempts=int(
                    params.get("lookup_attempts", DEFAULT_ROUTE_CHURN_LOOKUP_ATTEMPTS)
                ),
                lookup_retry_seconds=float(
                    params.get(
                        "lookup_retry_seconds",
                        DEFAULT_ROUTE_CHURN_LOOKUP_RETRY_SECONDS,
                    )
                ),
                max_consecutive_observation_failures=int(
                    params.get(
                        "max_consecutive_observation_failures",
                        DEFAULT_ROUTE_CHURN_MAX_CONSECUTIVE_OBSERVATION_FAILURES,
                    )
                ),
                fail_on_session_flap=bool(params.get("fail_on_session_flap", True)),
            ),
        )
