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


@dataclasses.dataclass(frozen=True)
class RouteStormTargetSelector:
    ixia_interface_mimic_ibgp: str
    observer_peer_parent_prefix: str
    ipv4_prefix_pool_name: str
    ipv6_prefix_pool_name: str
    peer_count_per_plane: int
    selected_peer_rows: tuple[int, ...]

    def __post_init__(self) -> None:
        if (
            not self.ixia_interface_mimic_ibgp
            or not self.observer_peer_parent_prefix
            or not self.ipv4_prefix_pool_name
            or not self.ipv6_prefix_pool_name
        ):
            raise ValueError("route-storm selectors must be non-empty")
        if self.selected_peer_rows != tuple(sorted(set(self.selected_peer_rows))):
            raise ValueError("selected_peer_rows must be unique and sorted")
        if any(
            row < 0 or row >= self.peer_count_per_plane
            for row in self.selected_peer_rows
        ):
            raise ValueError("selected_peer_rows must be in range")


@dataclasses.dataclass(frozen=True)
class RouteStormGeometry:
    routes_per_peer: int
    samples_per_block: int


@dataclasses.dataclass(frozen=True)
class RouteStormCyclePolicy:
    cycles: int
    advertise_seconds: int
    withdraw_seconds: int


@dataclasses.dataclass(frozen=True)
class RouteStormObservationPolicy:
    poll_interval_seconds: int
    convergence_hard_timeout_seconds: int
    session_establish_timeout_seconds: int
    restore_timeout_seconds: int
    quiet_window_seconds: int
    max_lookup_concurrency: int


@dataclasses.dataclass(frozen=True)
class RouteStormHeavySetup:
    hard_timeout_seconds: int
    route_batch_rows: int


@dataclasses.dataclass(frozen=True)
class RouteStormAttributeShape:
    as_path_pool_size: int
    as_path_length: int
    as_set_length: int
    communities_per_route: int
    extended_communities_per_route: int

    def __post_init__(self) -> None:
        if (
            self.as_path_length != 255
            or self.as_set_length != 255
            or self.extended_communities_per_route != 16
        ):
            raise ValueError(
                "CICD-EBB-11 requires 255-AS AS_SEQUENCE and AS_SET segments "
                "plus 16 extended communities"
            )


@dataclasses.dataclass(frozen=True)
class RouteStorm:
    expected_established_sessions: int
    selector: RouteStormTargetSelector
    geometry: RouteStormGeometry
    cycle: RouteStormCyclePolicy
    observation: RouteStormObservationPolicy
    heavy_setup: RouteStormHeavySetup
    attributes: RouteStormAttributeShape
    bounded_validation: bool = False

    def __post_init__(self) -> None:
        numeric_values = (
            self.expected_established_sessions,
            self.selector.peer_count_per_plane,
            self.geometry.routes_per_peer,
            self.geometry.samples_per_block,
            self.cycle.cycles,
            self.cycle.advertise_seconds,
            self.cycle.withdraw_seconds,
            self.observation.poll_interval_seconds,
            self.observation.convergence_hard_timeout_seconds,
            self.heavy_setup.hard_timeout_seconds,
            self.heavy_setup.route_batch_rows,
            self.observation.session_establish_timeout_seconds,
            self.observation.restore_timeout_seconds,
            self.observation.quiet_window_seconds,
            self.observation.max_lookup_concurrency,
            self.attributes.as_path_pool_size,
            self.attributes.as_path_length,
            self.attributes.as_set_length,
            self.attributes.communities_per_route,
            self.attributes.extended_communities_per_route,
        )
        if any(value <= 0 for value in numeric_values):
            raise ValueError("BGP route-storm numeric parameters must be positive")
        route_path_count = (
            len(self.selector.selected_peer_rows) * self.geometry.routes_per_peer * 2
        )
        if route_path_count != 10_500:
            raise ValueError(
                "CICD-EBB-11 requires exactly 10,500 dual-stack route paths"
            )

    def to_step_params(self) -> dict[str, t.Any]:
        """Lower typed route-storm intent to the established flat contract."""
        params: dict[str, t.Any] = {
            "ixia_interface_mimic_ibgp": self.selector.ixia_interface_mimic_ibgp,
            "observer_peer_parent_prefix": self.selector.observer_peer_parent_prefix,
            "prefix_pool_names": {
                "ipv4": self.selector.ipv4_prefix_pool_name,
                "ipv6": self.selector.ipv6_prefix_pool_name,
            },
            "selected_peer_rows": list(self.selector.selected_peer_rows),
        }
        if self.bounded_validation:
            params["bounded_validation"] = True
        params.update(
            {
                "expected_established_sessions": self.expected_established_sessions,
                "peer_count_per_plane": self.selector.peer_count_per_plane,
                "routes_per_peer": self.geometry.routes_per_peer,
                "samples_per_block": self.geometry.samples_per_block,
                "cycles": self.cycle.cycles,
                "advertise_seconds": self.cycle.advertise_seconds,
                "withdraw_seconds": self.cycle.withdraw_seconds,
                "poll_interval_seconds": self.observation.poll_interval_seconds,
                "convergence_hard_timeout_seconds": self.observation.convergence_hard_timeout_seconds,
                "heavy_setup_hard_timeout_seconds": self.heavy_setup.hard_timeout_seconds,
                "heavy_route_batch_rows": self.heavy_setup.route_batch_rows,
                "session_establish_timeout_seconds": self.observation.session_establish_timeout_seconds,
                "restore_timeout_seconds": self.observation.restore_timeout_seconds,
                "quiet_window_seconds": self.observation.quiet_window_seconds,
                "max_lookup_concurrency": self.observation.max_lookup_concurrency,
                "as_path_pool_size": self.attributes.as_path_pool_size,
                "as_path_length": self.attributes.as_path_length,
                "as_set_length": self.attributes.as_set_length,
                "communities_per_route": self.attributes.communities_per_route,
                "extended_communities_per_route": self.attributes.extended_communities_per_route,
            }
        )
        return params

    @classmethod
    def from_step_params(cls, params: t.Mapping[str, t.Any]) -> RouteStorm:
        pool_names = t.cast(t.Mapping[str, str], params["prefix_pool_names"])
        return cls(
            expected_established_sessions=params["expected_established_sessions"],
            selector=RouteStormTargetSelector(
                ixia_interface_mimic_ibgp=params["ixia_interface_mimic_ibgp"],
                observer_peer_parent_prefix=params["observer_peer_parent_prefix"],
                ipv4_prefix_pool_name=pool_names["ipv4"],
                ipv6_prefix_pool_name=pool_names["ipv6"],
                peer_count_per_plane=params["peer_count_per_plane"],
                selected_peer_rows=tuple(params["selected_peer_rows"]),
            ),
            geometry=RouteStormGeometry(
                routes_per_peer=params["routes_per_peer"],
                samples_per_block=params["samples_per_block"],
            ),
            cycle=RouteStormCyclePolicy(
                cycles=params["cycles"],
                advertise_seconds=params["advertise_seconds"],
                withdraw_seconds=params["withdraw_seconds"],
            ),
            observation=RouteStormObservationPolicy(
                poll_interval_seconds=params["poll_interval_seconds"],
                convergence_hard_timeout_seconds=params[
                    "convergence_hard_timeout_seconds"
                ],
                session_establish_timeout_seconds=params[
                    "session_establish_timeout_seconds"
                ],
                restore_timeout_seconds=params["restore_timeout_seconds"],
                quiet_window_seconds=params["quiet_window_seconds"],
                max_lookup_concurrency=params["max_lookup_concurrency"],
            ),
            heavy_setup=RouteStormHeavySetup(
                hard_timeout_seconds=params["heavy_setup_hard_timeout_seconds"],
                route_batch_rows=params["heavy_route_batch_rows"],
            ),
            attributes=RouteStormAttributeShape(
                as_path_pool_size=params["as_path_pool_size"],
                as_path_length=params["as_path_length"],
                as_set_length=params["as_set_length"],
                communities_per_route=params["communities_per_route"],
                extended_communities_per_route=params["extended_communities_per_route"],
            ),
            bounded_validation=params.get("bounded_validation", False),
        )
