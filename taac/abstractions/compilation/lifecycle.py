# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

import heapq
import typing as t
from collections.abc import Collection
from dataclasses import dataclass, field
from enum import Enum

from taac.abstractions.compilation.model import ResourceId


class OwnershipMode(str, Enum):
    OWNED = "owned"
    BORROWED = "borrowed"
    SNAPSHOT_RESTORED = "snapshot_restored"


class RestorationMode(str, Enum):
    INVERSE = "inverse"
    NONE = "none"
    FIRST_SNAPSHOT = "first_snapshot"


class ReadinessMode(str, Enum):
    NONE = "none"
    ACKNOWLEDGED = "acknowledged"
    EXACT_READBACK = "exact_readback"
    HEALTH_CHECK = "health_check"


class LifecycleValidationError(ValueError):
    """Raised when lifecycle metadata cannot form a safe dependency plan."""


def _validate_resource_id(resource_id: object, *, field_name: str) -> ResourceId:
    if not isinstance(resource_id, ResourceId):
        raise LifecycleValidationError(f"{field_name} must be a ResourceId")
    return resource_id


@dataclass(frozen=True)
class LifecycleOperation:
    """Task-free lifecycle metadata for one stable resource."""

    resource_id: ResourceId
    ownership: OwnershipMode
    restoration: RestorationMode
    readiness: ReadinessMode = ReadinessMode.NONE
    dependencies: tuple[ResourceId, ...] = ()
    state_changing: bool = True

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        _validate_resource_id(self.resource_id, field_name="resource_id")
        if not isinstance(self.ownership, OwnershipMode):
            raise LifecycleValidationError("ownership must be an OwnershipMode value")
        if not isinstance(self.restoration, RestorationMode):
            raise LifecycleValidationError(
                "restoration must be a RestorationMode value"
            )
        if not isinstance(self.readiness, ReadinessMode):
            raise LifecycleValidationError("readiness must be a ReadinessMode value")
        if not isinstance(self.dependencies, tuple):
            raise LifecycleValidationError("dependencies must be a tuple")
        if not isinstance(self.state_changing, bool):
            raise LifecycleValidationError("state_changing must be a bool")

        seen_dependencies: set[ResourceId] = set()
        for dependency_index, dependency in enumerate(self.dependencies):
            dependency = _validate_resource_id(
                dependency,
                field_name=f"dependencies[{dependency_index}]",
            )
            if dependency == self.resource_id:
                raise LifecycleValidationError(
                    f"resource {self.resource_id} cannot depend on itself"
                )
            if dependency in seen_dependencies:
                raise LifecycleValidationError(
                    f"resource {self.resource_id} repeats dependency {dependency}"
                )
            seen_dependencies.add(dependency)

        if self.ownership is OwnershipMode.BORROWED and self.state_changing:
            raise LifecycleValidationError(
                f"borrowed resource {self.resource_id} cannot change state"
            )

        expected_restoration = self._expected_restoration()
        if self.restoration is not expected_restoration:
            raise LifecycleValidationError(
                f"resource {self.resource_id} with ownership "
                f"{self.ownership.value!r} and state_changing="
                f"{self.state_changing!r} requires restoration "
                f"{expected_restoration.value!r}, got {self.restoration.value!r}"
            )

    def _expected_restoration(self) -> RestorationMode:
        if not self.state_changing or self.ownership is OwnershipMode.BORROWED:
            return RestorationMode.NONE
        if self.ownership is OwnershipMode.SNAPSHOT_RESTORED:
            return RestorationMode.FIRST_SNAPSHOT
        return RestorationMode.INVERSE

    @property
    def teardown_eligible(self) -> bool:
        return self.state_changing and self.ownership in {
            OwnershipMode.OWNED,
            OwnershipMode.SNAPSHOT_RESTORED,
        }


@dataclass(frozen=True)
class LifecyclePlan:
    operations: tuple[LifecycleOperation, ...] = ()
    _ordered_setup: tuple[LifecycleOperation, ...] = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.operations, tuple):
            raise LifecycleValidationError("operations must be a tuple")
        for operation_index, operation in enumerate(self.operations):
            if not isinstance(operation, LifecycleOperation):
                raise LifecycleValidationError(
                    f"operations[{operation_index}] must be a LifecycleOperation"
                )

        operations_by_id: dict[ResourceId, LifecycleOperation] = {}
        for operation in self.operations:
            if operation.resource_id in operations_by_id:
                raise LifecycleValidationError(
                    f"duplicate lifecycle resource ID {operation.resource_id}"
                )
            operations_by_id[operation.resource_id] = operation

        missing_dependencies = tuple(
            (operation.resource_id, dependency)
            for operation in self.operations
            for dependency in operation.dependencies
            if dependency not in operations_by_id
        )
        if missing_dependencies:
            rendered = ", ".join(
                f"{resource_id} -> {dependency}"
                for resource_id, dependency in missing_dependencies
            )
            raise LifecycleValidationError(
                f"missing lifecycle dependencies: {rendered}"
            )

        ordered_setup = self._stable_dependency_order()
        object.__setattr__(self, "_ordered_setup", ordered_setup)

    def _stable_dependency_order(self) -> tuple[LifecycleOperation, ...]:
        declaration_index = {
            operation.resource_id: index
            for index, operation in enumerate(self.operations)
        }
        indegree = {
            operation.resource_id: len(operation.dependencies)
            for operation in self.operations
        }
        dependents: dict[ResourceId, list[ResourceId]] = {
            operation.resource_id: [] for operation in self.operations
        }
        for operation in self.operations:
            for dependency in operation.dependencies:
                dependents[dependency].append(operation.resource_id)

        ready = [
            declaration_index[operation.resource_id]
            for operation in self.operations
            if indegree[operation.resource_id] == 0
        ]
        heapq.heapify(ready)
        ordered: list[LifecycleOperation] = []

        while ready:
            operation_index = heapq.heappop(ready)
            operation = self.operations[operation_index]
            ordered.append(operation)
            for dependent in dependents[operation.resource_id]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    heapq.heappush(ready, declaration_index[dependent])

        if len(ordered) != len(self.operations):
            unresolved = tuple(
                operation.resource_id
                for operation in self.operations
                if indegree[operation.resource_id] > 0
            )
            raise LifecycleValidationError(
                "lifecycle dependency cycle leaves unresolved resources: "
                + ", ".join(str(resource_id) for resource_id in unresolved)
            )
        return tuple(ordered)

    def setup_order(self) -> tuple[LifecycleOperation, ...]:
        return self._ordered_setup

    def teardown_order(self) -> tuple[LifecycleOperation, ...]:
        return tuple(
            operation
            for operation in reversed(self._ordered_setup)
            if operation.teardown_eligible
        )


class MissingSnapshotError(LookupError):
    def __init__(self, resource_id: ResourceId) -> None:
        self.resource_id = resource_id
        super().__init__(f"no first snapshot captured for resource {resource_id}")


@dataclass
class SnapshotStore:
    """Retains the first pre-mutation snapshot for each resource."""

    _snapshots: dict[ResourceId, object] = field(default_factory=dict, init=False)

    def capture_once(self, resource_id: ResourceId, snapshot: object) -> object:
        resource_id = _validate_resource_id(resource_id, field_name="resource_id")
        if resource_id not in self._snapshots:
            self._snapshots[resource_id] = snapshot
        return self._snapshots[resource_id]

    def snapshot_for(self, resource_id: ResourceId) -> object:
        resource_id = _validate_resource_id(resource_id, field_name="resource_id")
        if resource_id not in self._snapshots:
            raise MissingSnapshotError(resource_id)
        return self._snapshots[resource_id]

    def has_snapshot(self, resource_id: ResourceId) -> bool:
        resource_id = _validate_resource_id(resource_id, field_name="resource_id")
        return resource_id in self._snapshots


@dataclass(frozen=True)
class CleanupFailure:
    resource_id: ResourceId
    error: Exception


class CleanupAggregateError(Exception):
    """Preserves the primary failure and every ordered cleanup failure."""

    def __init__(
        self,
        *,
        primary_error: BaseException | None,
        failures: tuple[CleanupFailure, ...],
    ) -> None:
        if not failures:
            raise ValueError("CleanupAggregateError requires cleanup failures")
        self.primary_error = primary_error
        self.failures = failures
        rendered_failures = "; ".join(
            f"{failure.resource_id}: {type(failure.error).__name__}: {failure.error}"
            for failure in failures
        )
        primary = ""
        if primary_error is not None:
            primary = f"primary {type(primary_error).__name__}: {primary_error}; "
        super().__init__(f"{primary}cleanup failures: {rendered_failures}")

    @property
    def cleanup_failures(self) -> tuple[CleanupFailure, ...]:
        return self.failures


class CleanupAction(t.Protocol):
    def __call__(
        self,
        operation: LifecycleOperation,
        snapshot: object | None,
        /,
    ) -> None: ...


def run_cleanup(
    plan: LifecyclePlan,
    cleanup: CleanupAction,
    *,
    completed_resource_ids: Collection[ResourceId] | None = None,
    snapshots: SnapshotStore | None = None,
    primary_error: BaseException | None = None,
) -> None:
    """Runs eligible cleanup in plan order and never hides operational failures."""

    known_ids = frozenset(operation.resource_id for operation in plan.operations)
    if completed_resource_ids is None:
        completed_ids = known_ids
    else:
        completed_ids = frozenset(
            _validate_resource_id(resource_id, field_name="completed_resource_ids")
            for resource_id in completed_resource_ids
        )
        unknown_ids = sorted(completed_ids - known_ids, key=str)
        if unknown_ids:
            raise LifecycleValidationError(
                "completed resources are absent from the lifecycle plan: "
                + ", ".join(str(resource_id) for resource_id in unknown_ids)
            )

    failures: list[CleanupFailure] = []
    for operation in plan.teardown_order():
        if operation.resource_id not in completed_ids:
            continue
        try:
            snapshot: object | None = None
            if operation.restoration is RestorationMode.FIRST_SNAPSHOT:
                if snapshots is None:
                    raise MissingSnapshotError(operation.resource_id)
                snapshot = snapshots.snapshot_for(operation.resource_id)
            cleanup(operation, snapshot)
        except Exception as error:
            failures.append(CleanupFailure(operation.resource_id, error))

    if failures:
        aggregate = CleanupAggregateError(
            primary_error=primary_error,
            failures=tuple(failures),
        )
        if primary_error is None:
            raise aggregate
        raise aggregate from primary_error
    if primary_error is not None:
        raise primary_error
