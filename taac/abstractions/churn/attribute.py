# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""DICE intent and flat-step lowering for BGP attribute churn."""

from __future__ import annotations

import dataclasses
import typing as t

from taac.abstractions.churn.policies import (
    ExecutionPolicy,
    PreparationPolicy,
    RecoveryPolicy,
)
from taac.abstractions.churn.selectors import UniformRowSelection
from taac.abstractions.churn.specs import (
    AttributeFamily,
    AttributePhase,
    ChurnScenario,
    ChurnWorkload,
    Scalar,
)


DEFAULT_ATTRIBUTE_CHURN_GEOMETRY_TIMEOUT_SECONDS = 480.0
DEFAULT_ATTRIBUTE_CHURN_SNAPSHOT_TIMEOUT_SECONDS = 480.0
DEFAULT_ATTRIBUTE_CHURN_DURATION_SECONDS = 3_600
DEFAULT_ATTRIBUTE_CHURN_WORK_RESERVE_SECONDS = 1_500.0
DEFAULT_ATTRIBUTE_CHURN_CLEANUP_TIMEOUT_SECONDS = 720.0
DEFAULT_ATTRIBUTE_CHURN_RESTORE_TIMEOUT_SECONDS = 400.0
DEFAULT_ATTRIBUTE_CHURN_IXIA_RESTORE_TIMEOUT_SECONDS = 120.0
DEFAULT_ATTRIBUTE_CHURN_CANCELLATION_GRACE_SECONDS = 10.0


@dataclasses.dataclass(frozen=True)
class AttributePoolIdentity:
    afi: str
    plane: int
    name: str


@dataclasses.dataclass(frozen=True)
class AttributeTargetSelector:
    prefix_pools: tuple[AttributePoolIdentity, ...]
    peer_count_per_pool: int
    row_selection: UniformRowSelection


@dataclasses.dataclass(frozen=True)
class BlockGeometryExpectation:
    routes_per_block: int
    samples_per_block: int


@dataclasses.dataclass(frozen=True)
class BaselineExpectation:
    block_geometry: BlockGeometryExpectation


@dataclasses.dataclass(frozen=True)
class AttributeChurn:
    scenario: ChurnScenario
    selector: AttributeTargetSelector
    baseline_expectation: BaselineExpectation

    def to_step_params(self) -> dict[str, t.Any]:
        prefix_pool_names: dict[str, dict[str, str]] = {}
        for pool in self.selector.prefix_pools:
            prefix_pool_names.setdefault(pool.afi, {})[str(pool.plane)] = pool.name
        attribute_matrix = {
            family.name: {phase.name: phase.value for phase in family.phases}
            for family in self.scenario.workload.families
        }
        geometry = self.baseline_expectation.block_geometry
        return {
            "scenario_id": self.scenario.scenario_id,
            "prefix_pool_names": prefix_pool_names,
            "attribute_matrix": attribute_matrix,
            "peer_count_per_plane": self.selector.peer_count_per_pool,
            "selected_block_count_per_afi": self.selector.row_selection.rows_per_pool,
            "samples_per_block": geometry.samples_per_block,
            "routes_per_block": geometry.routes_per_block,
            "duration_seconds": self.scenario.execution.duration_seconds,
            "max_iterations": self.scenario.execution.max_iterations,
            "cadence_seconds": self.scenario.execution.cadence_seconds,
            "geometry_timeout_seconds": (
                self.scenario.preparation.initial_resolution_timeout_seconds
            ),
            "snapshot_timeout_seconds": (
                self.scenario.preparation.baseline_capture_timeout_seconds
            ),
            "work_timeout_seconds": self.scenario.preparation.total_timeout_seconds,
            "cleanup_timeout_seconds": self.scenario.recovery.total_timeout_seconds,
            "restore_timeout_seconds": (
                self.scenario.recovery.restore_observation_timeout_seconds
            ),
            "ixia_restore_timeout_seconds": (
                self.scenario.recovery.ixia_restore_timeout_seconds
            ),
            "cancellation_grace_seconds": (
                self.scenario.recovery.cancellation_grace_seconds
            ),
        }

    @classmethod
    def from_step_params(cls, params: t.Mapping[str, t.Any]) -> AttributeChurn:
        family_order = ("med", "origin", "local_pref")
        matrix = t.cast(
            t.Mapping[str, t.Mapping[str, t.Any]], params["attribute_matrix"]
        )
        workload = ChurnWorkload(
            families=tuple(
                AttributeFamily(
                    name=family,
                    phases=tuple(
                        AttributePhase(name=phase, value=t.cast(Scalar, value))
                        for phase, value in matrix[family].items()
                    ),
                )
                for family in family_order
            )
        )
        duration_seconds = float(params["duration_seconds"])
        scenario = ChurnScenario(
            scenario_id=str(params.get("scenario_id", "bgp_ebb_attribute_churn")),
            workload=workload,
            preparation=PreparationPolicy(
                initial_resolution_timeout_seconds=float(
                    params.get(
                        "geometry_timeout_seconds",
                        DEFAULT_ATTRIBUTE_CHURN_GEOMETRY_TIMEOUT_SECONDS,
                    )
                ),
                baseline_capture_timeout_seconds=float(
                    params.get(
                        "snapshot_timeout_seconds",
                        DEFAULT_ATTRIBUTE_CHURN_SNAPSHOT_TIMEOUT_SECONDS,
                    )
                ),
                total_timeout_seconds=float(
                    params.get(
                        "work_timeout_seconds",
                        duration_seconds + DEFAULT_ATTRIBUTE_CHURN_WORK_RESERVE_SECONDS,
                    )
                ),
            ),
            execution=ExecutionPolicy(
                duration_seconds=duration_seconds,
                cadence_seconds=float(params["cadence_seconds"]),
                max_iterations=int(params["max_iterations"]),
            ),
            recovery=RecoveryPolicy(
                total_timeout_seconds=float(
                    params.get(
                        "cleanup_timeout_seconds",
                        DEFAULT_ATTRIBUTE_CHURN_CLEANUP_TIMEOUT_SECONDS,
                    )
                ),
                restore_observation_timeout_seconds=float(
                    params.get(
                        "restore_timeout_seconds",
                        DEFAULT_ATTRIBUTE_CHURN_RESTORE_TIMEOUT_SECONDS,
                    )
                ),
                ixia_restore_timeout_seconds=(
                    float(
                        params.get(
                            "ixia_restore_timeout_seconds",
                            DEFAULT_ATTRIBUTE_CHURN_IXIA_RESTORE_TIMEOUT_SECONDS,
                        )
                    )
                ),
                cancellation_grace_seconds=(
                    float(
                        params.get(
                            "cancellation_grace_seconds",
                            DEFAULT_ATTRIBUTE_CHURN_CANCELLATION_GRACE_SECONDS,
                        )
                    )
                ),
            ),
        )
        pool_names = t.cast(
            t.Mapping[str, t.Mapping[str, str]], params["prefix_pool_names"]
        )
        selector = AttributeTargetSelector(
            prefix_pools=tuple(
                AttributePoolIdentity(
                    afi=afi, plane=plane, name=pool_names[afi][str(plane)]
                )
                for afi in ("ipv4", "ipv6")
                for plane in range(1, 5)
            ),
            peer_count_per_pool=int(params["peer_count_per_plane"]),
            row_selection=UniformRowSelection(
                rows_per_pool=int(params["selected_block_count_per_afi"])
            ),
        )
        return cls(
            scenario=scenario,
            selector=selector,
            baseline_expectation=BaselineExpectation(
                block_geometry=BlockGeometryExpectation(
                    routes_per_block=int(params["routes_per_block"]),
                    samples_per_block=int(params["samples_per_block"]),
                )
            ),
        )
