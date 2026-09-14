# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""Runtime-neutral intent and flat-step lowering for BGP session churn."""

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


DEFAULT_SESSION_POLL_INTERVAL_SECONDS = 2.0
DEFAULT_SESSION_TRANSITION_SOFT_THRESHOLD_SECONDS = 30.0
DEFAULT_SESSION_TRANSITION_HARD_TIMEOUT_SECONDS = 60.0
DEFAULT_SESSION_CONFIRMATION_SECONDS = 2.0
DEFAULT_SESSION_RESTORE_SOFT_THRESHOLD_SECONDS = 120.0
DEFAULT_SESSION_RESTORE_HARD_TIMEOUT_SECONDS = 300.0
DEFAULT_SESSION_IXIA_RESTORE_TIMEOUT_PER_GROUP_SECONDS = 30.0
DEFAULT_SESSION_IXIA_RESTORE_TIMEOUT_FLOOR_SECONDS = 60.0
DEFAULT_SESSION_RPC_TIMEOUT_SECONDS = 30.0
DEFAULT_SESSION_MAX_CONSECUTIVE_SNAPSHOT_FAILURES = 3
DEFAULT_SESSION_RESTORE_WATCHDOG_MARGIN_SECONDS = 60.0


def _json_number(value: float) -> int | float:
    return int(value) if value.is_integer() else value


@dataclasses.dataclass(frozen=True)
class SessionTargetGroup:
    name: str
    peer_regex: str
    session_count: int
    sessions_per_cycle: int

    def __post_init__(self) -> None:
        if not self.name or not self.peer_regex:
            raise ValueError("session group name and peer_regex must be non-empty")
        if self.session_count <= 0:
            raise ValueError("session_count must be positive")
        if not 0 < self.sessions_per_cycle <= self.session_count:
            raise ValueError(
                "sessions_per_cycle must be positive and no larger than session_count"
            )

    def to_step_params(self) -> dict[str, t.Any]:
        return {
            "name": self.name,
            "peer_regex": self.peer_regex,
            "session_count": self.session_count,
            "sessions_per_cycle": self.sessions_per_cycle,
        }


@dataclasses.dataclass(frozen=True)
class SessionCyclePolicy:
    uptime_seconds: float
    downtime_seconds: float
    schedule: tuple[tuple[str, ...], ...]

    def __post_init__(self) -> None:
        if self.uptime_seconds <= 0 or self.downtime_seconds <= 0:
            raise ValueError("session uptime and downtime must be positive")


@dataclasses.dataclass(frozen=True)
class SessionObservationPolicy:
    poll_interval_seconds: float = DEFAULT_SESSION_POLL_INTERVAL_SECONDS
    transition_soft_threshold_seconds: float = (
        DEFAULT_SESSION_TRANSITION_SOFT_THRESHOLD_SECONDS
    )
    transition_hard_timeout_seconds: float = (
        DEFAULT_SESSION_TRANSITION_HARD_TIMEOUT_SECONDS
    )
    confirmation_seconds: float = DEFAULT_SESSION_CONFIRMATION_SECONDS
    restore_soft_threshold_seconds: float = (
        DEFAULT_SESSION_RESTORE_SOFT_THRESHOLD_SECONDS
    )
    restore_hard_timeout_seconds: float = DEFAULT_SESSION_RESTORE_HARD_TIMEOUT_SECONDS
    ixia_restore_timeout_seconds_per_group: float = (
        DEFAULT_SESSION_IXIA_RESTORE_TIMEOUT_PER_GROUP_SECONDS
    )
    ixia_restore_timeout_floor_seconds: float = (
        DEFAULT_SESSION_IXIA_RESTORE_TIMEOUT_FLOOR_SECONDS
    )
    session_rpc_timeout_seconds: float = DEFAULT_SESSION_RPC_TIMEOUT_SECONDS
    max_consecutive_snapshot_failures: int = (
        DEFAULT_SESSION_MAX_CONSECUTIVE_SNAPSHOT_FAILURES
    )


@dataclasses.dataclass(frozen=True)
class SessionChurn:
    scenario: ChurnScenario
    groups: tuple[SessionTargetGroup, ...]
    cycle: SessionCyclePolicy
    expected_established_sessions: int
    parent_prefixes_to_ignore: tuple[str, ...] = ()
    observation: SessionObservationPolicy = SessionObservationPolicy()

    def __post_init__(self) -> None:
        if not self.groups:
            raise ValueError("session churn requires at least one target group")
        names = tuple(group.name for group in self.groups)
        if len(set(names)) != len(names):
            raise ValueError("session group names must be unique")
        if not self.cycle.schedule or any(not entry for entry in self.cycle.schedule):
            raise ValueError("session churn schedule must contain non-empty entries")
        unknown = {
            name for entry in self.cycle.schedule for name in entry if name not in names
        }
        if unknown:
            raise ValueError(f"session churn schedule has unknown groups: {unknown}")

    def to_step_params(self) -> dict[str, t.Any]:
        params: dict[str, t.Any] = {
            "session_groups": [group.to_step_params() for group in self.groups],
            "cycle_schedule": [list(names) for names in self.cycle.schedule],
            "expected_established_sessions": self.expected_established_sessions,
            "test_duration_seconds": _json_number(
                self.scenario.execution.duration_seconds
            ),
            "uptime_seconds": _json_number(self.cycle.uptime_seconds),
            "downtime_seconds": _json_number(self.cycle.downtime_seconds),
            "parent_prefixes_to_ignore": list(self.parent_prefixes_to_ignore),
        }
        optional_defaults: tuple[tuple[str, t.Any, t.Any], ...] = (
            (
                "poll_interval_seconds",
                self.observation.poll_interval_seconds,
                DEFAULT_SESSION_POLL_INTERVAL_SECONDS,
            ),
            (
                "transition_soft_threshold_seconds",
                self.observation.transition_soft_threshold_seconds,
                DEFAULT_SESSION_TRANSITION_SOFT_THRESHOLD_SECONDS,
            ),
            (
                "transition_hard_timeout_seconds",
                self.observation.transition_hard_timeout_seconds,
                DEFAULT_SESSION_TRANSITION_HARD_TIMEOUT_SECONDS,
            ),
            (
                "confirmation_seconds",
                self.observation.confirmation_seconds,
                DEFAULT_SESSION_CONFIRMATION_SECONDS,
            ),
            (
                "restore_soft_threshold_seconds",
                self.observation.restore_soft_threshold_seconds,
                DEFAULT_SESSION_RESTORE_SOFT_THRESHOLD_SECONDS,
            ),
            (
                "restore_hard_timeout_seconds",
                self.observation.restore_hard_timeout_seconds,
                DEFAULT_SESSION_RESTORE_HARD_TIMEOUT_SECONDS,
            ),
            (
                "ixia_restore_timeout_seconds_per_group",
                self.observation.ixia_restore_timeout_seconds_per_group,
                DEFAULT_SESSION_IXIA_RESTORE_TIMEOUT_PER_GROUP_SECONDS,
            ),
            (
                "ixia_restore_timeout_floor_seconds",
                self.observation.ixia_restore_timeout_floor_seconds,
                DEFAULT_SESSION_IXIA_RESTORE_TIMEOUT_FLOOR_SECONDS,
            ),
            (
                "session_rpc_timeout_seconds",
                self.observation.session_rpc_timeout_seconds,
                DEFAULT_SESSION_RPC_TIMEOUT_SECONDS,
            ),
            (
                "max_consecutive_snapshot_failures",
                self.observation.max_consecutive_snapshot_failures,
                DEFAULT_SESSION_MAX_CONSECUTIVE_SNAPSHOT_FAILURES,
            ),
        )
        for name, value, default in optional_defaults:
            if value != default:
                params[name] = (
                    _json_number(value) if isinstance(value, float) else value
                )
        return params

    @classmethod
    def from_step_params(cls, params: t.Mapping[str, t.Any]) -> SessionChurn:
        groups = tuple(
            SessionTargetGroup(
                name=str(group["name"]),
                peer_regex=str(group["peer_regex"]),
                session_count=int(group["session_count"]),
                sessions_per_cycle=int(group["sessions_per_cycle"]),
            )
            for group in params.get("session_groups", ())
        )
        duration = float(params.get("test_duration_seconds", 60.0))
        uptime = float(params.get("uptime_seconds", 30.0))
        downtime = float(params.get("downtime_seconds", 30.0))
        transition_timeout = float(
            params.get(
                "transition_hard_timeout_seconds",
                DEFAULT_SESSION_TRANSITION_HARD_TIMEOUT_SECONDS,
            )
        )
        ixia_restore_floor = float(
            params.get(
                "ixia_restore_timeout_floor_seconds",
                DEFAULT_SESSION_IXIA_RESTORE_TIMEOUT_FLOOR_SECONDS,
            )
        )
        ixia_restore_per_group = float(
            params.get(
                "ixia_restore_timeout_seconds_per_group",
                DEFAULT_SESSION_IXIA_RESTORE_TIMEOUT_PER_GROUP_SECONDS,
            )
        )
        restore_timeout = float(
            params.get(
                "restore_hard_timeout_seconds",
                DEFAULT_SESSION_RESTORE_HARD_TIMEOUT_SECONDS,
            )
        )
        rpc_timeout = float(
            params.get(
                "session_rpc_timeout_seconds",
                DEFAULT_SESSION_RPC_TIMEOUT_SECONDS,
            )
        )
        schedule = params.get("cycle_schedule")
        if schedule is None:
            schedule = [[group.name for group in groups]]
        cycle = SessionCyclePolicy(
            uptime_seconds=uptime,
            downtime_seconds=downtime,
            schedule=tuple(tuple(str(name) for name in names) for names in schedule),
        )
        cycle_seconds = cycle.uptime_seconds + cycle.downtime_seconds
        cycle_count = max(1, int(duration // cycle_seconds))
        recovery_total = (
            max(ixia_restore_floor, len(groups) * ixia_restore_per_group)
            + restore_timeout
            + rpc_timeout
            + DEFAULT_SESSION_RESTORE_WATCHDOG_MARGIN_SECONDS
        )
        return cls(
            scenario=ChurnScenario(
                scenario_id=str(params.get("scenario_id", "bgp_session_oscillation")),
                workload=ChurnWorkload(families=(ChurnFamily(name="sessions"),)),
                preparation=PreparationPolicy(
                    initial_resolution_timeout_seconds=transition_timeout,
                    baseline_capture_timeout_seconds=rpc_timeout,
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
                    total_timeout_seconds=recovery_total,
                    restore_observation_timeout_seconds=restore_timeout,
                    ixia_restore_timeout_seconds=max(
                        ixia_restore_floor, len(groups) * ixia_restore_per_group
                    ),
                    cancellation_grace_seconds=(
                        DEFAULT_SESSION_RESTORE_WATCHDOG_MARGIN_SECONDS
                    ),
                ),
            ),
            groups=groups,
            cycle=cycle,
            expected_established_sessions=int(
                params.get("expected_established_sessions", 0)
            ),
            parent_prefixes_to_ignore=tuple(
                str(prefix) for prefix in params.get("parent_prefixes_to_ignore", ())
            ),
            observation=SessionObservationPolicy(
                poll_interval_seconds=float(
                    params.get(
                        "poll_interval_seconds", DEFAULT_SESSION_POLL_INTERVAL_SECONDS
                    )
                ),
                transition_soft_threshold_seconds=float(
                    params.get(
                        "transition_soft_threshold_seconds",
                        DEFAULT_SESSION_TRANSITION_SOFT_THRESHOLD_SECONDS,
                    )
                ),
                transition_hard_timeout_seconds=transition_timeout,
                confirmation_seconds=float(
                    params.get(
                        "confirmation_seconds", DEFAULT_SESSION_CONFIRMATION_SECONDS
                    )
                ),
                restore_soft_threshold_seconds=float(
                    params.get(
                        "restore_soft_threshold_seconds",
                        DEFAULT_SESSION_RESTORE_SOFT_THRESHOLD_SECONDS,
                    )
                ),
                restore_hard_timeout_seconds=restore_timeout,
                ixia_restore_timeout_seconds_per_group=ixia_restore_per_group,
                ixia_restore_timeout_floor_seconds=ixia_restore_floor,
                session_rpc_timeout_seconds=rpc_timeout,
                max_consecutive_snapshot_failures=int(
                    params.get(
                        "max_consecutive_snapshot_failures",
                        DEFAULT_SESSION_MAX_CONSECUTIVE_SNAPSHOT_FAILURES,
                    )
                ),
            ),
        )
