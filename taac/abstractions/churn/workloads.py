# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""Typed, runtime-neutral contracts for the remaining EBB churn families."""

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


def _scenario(
    *,
    scenario_id: str,
    family: str,
    duration_seconds: float,
    cadence_seconds: float,
    recovery_seconds: float,
) -> ChurnScenario:
    if duration_seconds <= 0 or cadence_seconds <= 0:
        raise ValueError("churn duration and cadence must be positive")
    return ChurnScenario(
        scenario_id=scenario_id,
        workload=ChurnWorkload(families=(ChurnFamily(name=family),)),
        preparation=PreparationPolicy(
            initial_resolution_timeout_seconds=recovery_seconds,
            baseline_capture_timeout_seconds=recovery_seconds,
            total_timeout_seconds=duration_seconds + recovery_seconds,
        ),
        execution=ExecutionPolicy(
            duration_seconds=duration_seconds,
            cadence_seconds=cadence_seconds,
            max_iterations=max(1, int(duration_seconds // cadence_seconds)),
        ),
        recovery=RecoveryPolicy(
            total_timeout_seconds=recovery_seconds,
            restore_observation_timeout_seconds=recovery_seconds,
            ixia_restore_timeout_seconds=recovery_seconds,
            cancellation_grace_seconds=10.0,
        ),
    )


def _validate_igp_inputs(
    *,
    hostname: str,
    local_link: t.Mapping[str, t.Any],
    other_link: t.Mapping[str, t.Any],
    count: int,
    step: int,
) -> None:
    if not hostname or not local_link or not other_link:
        raise ValueError("IGP churn requires hostname and both link definitions")
    if count <= 0 or step <= 0:
        raise ValueError("IGP churn count and step must be positive")


def _validated_plane_starts(
    ipv4_starts: t.Sequence[str],
    ipv6_starts: t.Sequence[str],
    *,
    label: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    ipv4 = tuple(ipv4_starts)
    ipv6 = tuple(ipv6_starts)
    if not ipv4 or len(ipv4) != len(ipv6):
        raise ValueError(f"{label} IPv4 and IPv6 plane counts must match")
    return ipv4, ipv6


@dataclasses.dataclass(frozen=True)
class LongevityCommunityChurn:
    scenario: ChurnScenario
    prefix_pool_regex: str
    community_count: int

    @classmethod
    def create(
        cls,
        *,
        duration_seconds: int,
        cadence_seconds: int,
        prefix_pool_regex: str = ".*IBGP.*PLANE_4.*",
        community_count: int = 5,
    ) -> LongevityCommunityChurn:
        if prefix_pool_regex != ".*IBGP.*PLANE_4.*":
            raise ValueError(
                "prefix_pool_regex must select the topology-authored EBB Plane-4 pools"
            )
        if community_count <= 0:
            raise ValueError("community_count must be positive")
        return cls(
            scenario=_scenario(
                scenario_id="bgp_ebb_longevity_community_churn",
                family="community",
                duration_seconds=duration_seconds,
                cadence_seconds=cadence_seconds,
                recovery_seconds=240.0,
            ),
            prefix_pool_regex=prefix_pool_regex,
            community_count=community_count,
        )

    def to_step_params(self) -> dict[str, t.Any]:
        return {
            "prefix_pool_regex": self.prefix_pool_regex,
            "community_count": self.community_count,
            "duration_seconds": int(self.scenario.execution.duration_seconds),
            "cadence_seconds": int(self.scenario.execution.cadence_seconds),
        }


@dataclasses.dataclass(frozen=True)
class MultipathChurn:
    scenario: ChurnScenario
    hostname: str
    ipv4_peer_regex: str
    ipv6_peer_regex: str
    ipv4_session_count: int
    ipv6_session_count: int
    oscillation_interval_seconds: int
    min_peers_to_stop: int
    max_peers_to_stop: int
    cycle_count: int | None = None
    expected_min_baseline_width: int | None = None
    expected_max_baseline_width: int | None = None
    min_multipath_width: int | None = None
    prefix_subnets: tuple[str, ...] = ()
    probe_prefixes_per_afi: int = 2
    poll_interval_seconds: float = 5
    stable_sample_count: int = 2
    bgp_read_timeout_seconds: float = 30

    @classmethod
    def create(
        cls,
        *,
        hostname: str,
        ipv4_peer_regex: str,
        ipv6_peer_regex: str,
        ipv4_session_count: int,
        ipv6_session_count: int,
        test_duration_seconds: int,
        oscillation_interval_seconds: int,
        min_peers_to_stop: int,
        max_peers_to_stop: int,
        cycle_count: int | None = None,
        expected_min_baseline_width: int | None = None,
        expected_max_baseline_width: int | None = None,
        min_multipath_width: int | None = None,
        prefix_subnets: t.Sequence[str] = (),
        probe_prefixes_per_afi: int = 2,
        poll_interval_seconds: float = 5,
        stable_sample_count: int = 2,
        bgp_read_timeout_seconds: float = 30,
    ) -> MultipathChurn:
        if oscillation_interval_seconds <= 0:
            raise ValueError("oscillation_interval_seconds must be positive")
        if cycle_count is not None and cycle_count <= 0:
            raise ValueError("cycle_count must be positive when provided")
        configured_cycles = cycle_count if cycle_count is not None else 6
        if test_duration_seconds // oscillation_interval_seconds != configured_cycles:
            raise ValueError(
                "multipath oscillation duration must contain the configured cycles"
            )
        if min_peers_to_stop < 1 or max_peers_to_stop < min_peers_to_stop:
            raise ValueError("peer-stop range must satisfy 1 <= min <= max")
        if max_peers_to_stop > min(ipv4_session_count, ipv6_session_count):
            raise ValueError("peer-stop range exceeds the configured session count")
        return cls(
            scenario=_scenario(
                scenario_id="bgp_ebb_multipath_oscillation",
                family="multipath",
                duration_seconds=test_duration_seconds,
                cadence_seconds=oscillation_interval_seconds,
                recovery_seconds=600.0,
            ),
            hostname=hostname,
            ipv4_peer_regex=ipv4_peer_regex,
            ipv6_peer_regex=ipv6_peer_regex,
            ipv4_session_count=ipv4_session_count,
            ipv6_session_count=ipv6_session_count,
            oscillation_interval_seconds=oscillation_interval_seconds,
            min_peers_to_stop=min_peers_to_stop,
            max_peers_to_stop=max_peers_to_stop,
            cycle_count=cycle_count,
            expected_min_baseline_width=expected_min_baseline_width,
            expected_max_baseline_width=expected_max_baseline_width,
            min_multipath_width=min_multipath_width,
            prefix_subnets=tuple(prefix_subnets),
            probe_prefixes_per_afi=probe_prefixes_per_afi,
            poll_interval_seconds=poll_interval_seconds,
            stable_sample_count=stable_sample_count,
            bgp_read_timeout_seconds=bgp_read_timeout_seconds,
        )

    def to_step_params(self) -> dict[str, t.Any]:
        params: dict[str, t.Any] = {
            "hostname": self.hostname,
            "ipv4_peer_regex": self.ipv4_peer_regex,
            "ipv6_peer_regex": self.ipv6_peer_regex,
            "ipv4_session_count": self.ipv4_session_count,
            "ipv6_session_count": self.ipv6_session_count,
            "test_duration_seconds": int(self.scenario.execution.duration_seconds),
            "oscillation_interval_seconds": self.oscillation_interval_seconds,
            "min_peers_to_stop": self.min_peers_to_stop,
            "max_peers_to_stop": self.max_peers_to_stop,
            "expected_min_baseline_width": self.expected_min_baseline_width,
            "expected_max_baseline_width": self.expected_max_baseline_width,
            "min_multipath_width": self.min_multipath_width,
            "prefix_subnets": list(self.prefix_subnets),
            "probe_prefixes_per_afi": self.probe_prefixes_per_afi,
            "poll_interval_seconds": self.poll_interval_seconds,
            "stable_sample_count": self.stable_sample_count,
            "bgp_read_timeout_seconds": self.bgp_read_timeout_seconds,
        }
        if self.cycle_count is not None:
            params["cycle_count"] = self.cycle_count
        return params


@dataclasses.dataclass(frozen=True)
class IgpMetricChurn:
    scenario: ChurnScenario
    hostname: str
    start_ipv4s: tuple[str, ...]
    start_ipv6s: tuple[str, ...]
    local_link: t.Mapping[str, t.Any]
    other_link: t.Mapping[str, t.Any]
    count: int
    step: int
    frequency: int

    @classmethod
    def create(
        cls,
        *,
        hostname: str,
        start_ipv4s: t.Sequence[str],
        start_ipv6s: t.Sequence[str],
        local_link: t.Mapping[str, t.Any],
        other_link: t.Mapping[str, t.Any],
        count: int,
        step: int,
        duration: int,
        frequency: int,
    ) -> IgpMetricChurn:
        _validate_igp_inputs(
            hostname=hostname,
            local_link=local_link,
            other_link=other_link,
            count=count,
            step=step,
        )
        ipv4_starts, ipv6_starts = _validated_plane_starts(
            start_ipv4s,
            start_ipv6s,
            label="Open/R",
        )
        return cls(
            scenario=_scenario(
                scenario_id="bgp_ebb_igp_pnh_metric_oscillation",
                family="igp_metric",
                duration_seconds=duration,
                cadence_seconds=frequency,
                recovery_seconds=600.0,
            ),
            hostname=hostname,
            start_ipv4s=ipv4_starts,
            start_ipv6s=ipv6_starts,
            local_link=local_link,
            other_link=other_link,
            count=count,
            step=step,
            frequency=frequency,
        )

    def to_step_params(self) -> dict[str, t.Any]:
        return {
            "hostname": self.hostname,
            "start_ipv4s": list(self.start_ipv4s),
            "start_ipv6s": list(self.start_ipv6s),
            "local_link": dict(self.local_link),
            "other_link": dict(self.other_link),
            "count": self.count,
            "step": self.step,
            "duration": int(self.scenario.execution.duration_seconds),
            "frequency": self.frequency,
        }


@dataclasses.dataclass(frozen=True)
class IgpUnresolvableChurn:
    scenario: ChurnScenario
    hostname: str
    start_ipv4s: tuple[str, ...]
    start_ipv6s: tuple[str, ...]
    restore_start_ipv4s: tuple[str, ...]
    restore_start_ipv6s: tuple[str, ...]
    local_link: t.Mapping[str, t.Any]
    other_link: t.Mapping[str, t.Any]
    count: int
    step: int
    delete_count: int
    update_timeout_seconds: int
    stability_duration_seconds: int
    expected_in_scope_sessions: int
    parent_prefixes_to_ignore: tuple[str, ...] = ()
    convergence_stability_polls: int = 3
    convergence_stability_max_seconds: int = 300

    @classmethod
    def create(
        cls,
        *,
        hostname: str,
        start_ipv4s: t.Sequence[str],
        start_ipv6s: t.Sequence[str],
        restore_start_ipv4s: t.Sequence[str],
        restore_start_ipv6s: t.Sequence[str],
        local_link: t.Mapping[str, t.Any],
        other_link: t.Mapping[str, t.Any],
        count: int,
        step: int,
        delete_count: int,
        update_timeout_seconds: int,
        stability_duration_seconds: int,
        expected_in_scope_sessions: int,
        parent_prefixes_to_ignore: t.Sequence[str] = (),
        convergence_stability_polls: int = 3,
        convergence_stability_max_seconds: int = 300,
    ) -> IgpUnresolvableChurn:
        if expected_in_scope_sessions <= 0:
            raise ValueError("expected_in_scope_sessions must be positive")
        _validate_igp_inputs(
            hostname=hostname,
            local_link=local_link,
            other_link=other_link,
            count=count,
            step=step,
        )
        selected_ipv4, selected_ipv6 = _validated_plane_starts(
            start_ipv4s,
            start_ipv6s,
            label="selected",
        )
        restore_ipv4, restore_ipv6 = _validated_plane_starts(
            restore_start_ipv4s,
            restore_start_ipv6s,
            label="restore",
        )
        if not set(selected_ipv4).issubset(restore_ipv4) or not set(
            selected_ipv6
        ).issubset(restore_ipv6):
            raise ValueError("full restore starts must contain all selected starts")
        if delete_count <= 0 or delete_count > count:
            raise ValueError("delete_count must be within the configured route count")
        if (
            update_timeout_seconds <= 0
            or stability_duration_seconds <= 0
            or convergence_stability_polls < 0
            or convergence_stability_max_seconds <= 0
        ):
            raise ValueError(
                "IGP churn timeouts must be positive and stability polls "
                "must be nonnegative"
            )
        active_duration = (
            update_timeout_seconds
            + convergence_stability_max_seconds
            + stability_duration_seconds
        )
        return cls(
            scenario=_scenario(
                scenario_id="bgp_ebb_igp_unresolvable_pnh",
                family="igp_unresolvable",
                duration_seconds=active_duration,
                cadence_seconds=active_duration,
                recovery_seconds=600.0,
            ),
            hostname=hostname,
            start_ipv4s=selected_ipv4,
            start_ipv6s=selected_ipv6,
            restore_start_ipv4s=restore_ipv4,
            restore_start_ipv6s=restore_ipv6,
            local_link=local_link,
            other_link=other_link,
            count=count,
            step=step,
            delete_count=delete_count,
            update_timeout_seconds=update_timeout_seconds,
            stability_duration_seconds=stability_duration_seconds,
            expected_in_scope_sessions=expected_in_scope_sessions,
            parent_prefixes_to_ignore=tuple(parent_prefixes_to_ignore),
            convergence_stability_polls=convergence_stability_polls,
            convergence_stability_max_seconds=convergence_stability_max_seconds,
        )

    def to_step_params(self) -> dict[str, t.Any]:
        return {
            "hostname": self.hostname,
            "start_ipv4s": list(self.start_ipv4s),
            "start_ipv6s": list(self.start_ipv6s),
            "restore_start_ipv4s": list(self.restore_start_ipv4s),
            "restore_start_ipv6s": list(self.restore_start_ipv6s),
            "local_link": dict(self.local_link),
            "other_link": dict(self.other_link),
            "count": self.count,
            "step": self.step,
            "delete_count": self.delete_count,
            "update_timeout_seconds": self.update_timeout_seconds,
            "stability_duration_seconds": self.stability_duration_seconds,
            "expected_in_scope_sessions": self.expected_in_scope_sessions,
            "parent_prefixes_to_ignore": list(self.parent_prefixes_to_ignore),
            "convergence_stability_polls": self.convergence_stability_polls,
            "convergence_stability_max_seconds": (
                self.convergence_stability_max_seconds
            ),
        }
