# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from taac.abstractions.compilation.lifecycle import LifecyclePlan
from taac.abstractions.compilation.model import (
    DutPlan,
    ResourceId,
    ResourceKind,
)


THostOs_co = t.TypeVar("THostOs_co", covariant=True)
TEndpoint_co = t.TypeVar("TEndpoint_co", covariant=True)
TLifecycleTask_co = t.TypeVar("TLifecycleTask_co", covariant=True)


@dataclass(frozen=True)
class DutHostOsFragment(t.Generic[THostOs_co]):
    endpoint_id: ResourceId
    physical_identifier: str
    os_type: THostOs_co

    def __post_init__(self) -> None:
        if self.endpoint_id.kind is not ResourceKind.ENDPOINT:
            raise ValueError(
                f"DUT host-OS fragment {self.endpoint_id} must reference an endpoint"
            )
        if not self.physical_identifier:
            raise ValueError("DUT host-OS physical identifier must be nonempty")
        if self.os_type is None:
            raise ValueError("DUT host-OS type must be present")


@dataclass(frozen=True)
class DutHostOsRenderResult(t.Generic[THostOs_co]):
    owned_endpoint_ids: tuple[ResourceId, ...]
    fragments: tuple[DutHostOsFragment[THostOs_co], ...] = ()

    def __post_init__(self) -> None:
        _validate_unique_ids("DUT host-OS result", self.owned_endpoint_ids)
        _validate_unique_ids(
            "DUT host-OS fragment",
            tuple(fragment.endpoint_id for fragment in self.fragments),
        )
        physical_identifiers = tuple(
            fragment.physical_identifier for fragment in self.fragments
        )
        if len(frozenset(physical_identifiers)) != len(physical_identifiers):
            raise ValueError("DUT host-OS physical identifiers must be unique")

    @property
    def host_os_type_map(self) -> dict[str, THostOs_co]:
        return {
            fragment.physical_identifier: fragment.os_type
            for fragment in self.fragments
        }

    def validate(self, plan: DutPlan) -> None:
        expected_endpoints = tuple(
            endpoint for endpoint in plan.endpoints if endpoint.is_dut
        )
        expected_ids = tuple(endpoint.resource_id for endpoint in expected_endpoints)
        _validate_exact_coverage(
            "DUT host-OS result",
            expected_ids,
            self.owned_endpoint_ids,
        )
        _validate_exact_coverage(
            "DUT host-OS fragment",
            expected_ids,
            tuple(fragment.endpoint_id for fragment in self.fragments),
        )
        endpoints_by_id = {
            endpoint.resource_id: endpoint for endpoint in expected_endpoints
        }
        for fragment in self.fragments:
            expected_identifier = endpoints_by_id[
                fragment.endpoint_id
            ].physical_identifier
            if fragment.physical_identifier != expected_identifier:
                raise ValueError(
                    f"DUT host-OS fragment {fragment.endpoint_id} physical identifier "
                    f"mismatch: expected={expected_identifier!r}, "
                    f"actual={fragment.physical_identifier!r}"
                )


@dataclass(frozen=True)
class DutEndpointBaseFragment(t.Generic[TEndpoint_co]):
    endpoint_id: ResourceId
    physical_identifier: str
    endpoint: TEndpoint_co

    def __post_init__(self) -> None:
        if self.endpoint_id.kind is not ResourceKind.ENDPOINT:
            raise ValueError(
                f"DUT endpoint-base fragment {self.endpoint_id} must reference "
                "an endpoint"
            )
        if not self.physical_identifier:
            raise ValueError("DUT endpoint-base physical identifier must be nonempty")
        if self.endpoint is None:
            raise ValueError("DUT endpoint-base value must be present")


@dataclass(frozen=True)
class DutEndpointBaseRenderResult(t.Generic[TEndpoint_co]):
    owned_endpoint_ids: tuple[ResourceId, ...]
    fragments: tuple[DutEndpointBaseFragment[TEndpoint_co], ...] = ()

    def __post_init__(self) -> None:
        _validate_unique_ids("DUT endpoint-base result", self.owned_endpoint_ids)
        _validate_unique_ids(
            "DUT endpoint-base fragment",
            tuple(fragment.endpoint_id for fragment in self.fragments),
        )
        physical_identifiers = tuple(
            fragment.physical_identifier for fragment in self.fragments
        )
        if len(frozenset(physical_identifiers)) != len(physical_identifiers):
            raise ValueError("DUT endpoint-base physical identifiers must be unique")

    @property
    def base_endpoints(self) -> tuple[TEndpoint_co, ...]:
        return tuple(fragment.endpoint for fragment in self.fragments)

    def validate(self, plan: DutPlan) -> None:
        expected_endpoints = tuple(
            endpoint for endpoint in plan.endpoints if endpoint.is_dut
        )
        expected_ids = tuple(endpoint.resource_id for endpoint in expected_endpoints)
        _validate_exact_coverage(
            "DUT endpoint-base result",
            expected_ids,
            self.owned_endpoint_ids,
        )
        _validate_exact_coverage(
            "DUT endpoint-base fragment",
            expected_ids,
            tuple(fragment.endpoint_id for fragment in self.fragments),
        )
        endpoints_by_id = {
            endpoint.resource_id: endpoint for endpoint in expected_endpoints
        }
        for fragment in self.fragments:
            expected_identifier = endpoints_by_id[
                fragment.endpoint_id
            ].physical_identifier
            if fragment.physical_identifier != expected_identifier:
                raise ValueError(
                    f"DUT endpoint-base fragment {fragment.endpoint_id} physical "
                    f"identifier mismatch: expected={expected_identifier!r}, "
                    f"actual={fragment.physical_identifier!r}"
                )


@dataclass(frozen=True)
class DutLifecycleFragment(t.Generic[TLifecycleTask_co]):
    operation_id: ResourceId
    pre_ixia_tasks: tuple[TLifecycleTask_co, ...] = ()
    post_ixia_tasks: tuple[TLifecycleTask_co, ...] = ()

    def __post_init__(self) -> None:
        if not self.pre_ixia_tasks and not self.post_ixia_tasks:
            raise ValueError(
                f"DUT lifecycle fragment {self.operation_id} must emit a task"
            )


@dataclass(frozen=True)
class DutLifecycleCleanupFragment(t.Generic[TLifecycleTask_co]):
    operation_ids: tuple[ResourceId, ...]
    task: TLifecycleTask_co

    def __post_init__(self) -> None:
        if not self.operation_ids:
            raise ValueError("DUT lifecycle cleanup fragment must target an operation")
        _validate_unique_ids(
            "DUT lifecycle cleanup fragment",
            self.operation_ids,
        )


@dataclass(frozen=True)
class DutLifecycleRenderResult(t.Generic[TLifecycleTask_co]):
    consumed_operation_ids: tuple[ResourceId, ...]
    fragments: tuple[DutLifecycleFragment[TLifecycleTask_co], ...] = ()
    cleanup_fragments: tuple[DutLifecycleCleanupFragment[TLifecycleTask_co], ...] = ()

    def __post_init__(self) -> None:
        _validate_unique_ids(
            "DUT lifecycle result",
            self.consumed_operation_ids,
        )
        _validate_unique_ids(
            "DUT lifecycle fragment",
            tuple(fragment.operation_id for fragment in self.fragments),
        )

    @property
    def pre_ixia_tasks(self) -> tuple[TLifecycleTask_co, ...]:
        return tuple(
            task for fragment in self.fragments for task in fragment.pre_ixia_tasks
        )

    @property
    def post_ixia_tasks(self) -> tuple[TLifecycleTask_co, ...]:
        return tuple(
            task for fragment in self.fragments for task in fragment.post_ixia_tasks
        )

    @property
    def cleanup_tasks(self) -> tuple[TLifecycleTask_co, ...]:
        return tuple(fragment.task for fragment in self.cleanup_fragments)

    def validate(self, plan: DutPlan, lifecycle: LifecyclePlan) -> None:
        plan_ids = frozenset(resource.resource_id for resource in plan.iter_resources())
        lifecycle_ids = tuple(
            operation.resource_id for operation in lifecycle.setup_order()
        )
        unexpected = tuple(
            operation_id
            for operation_id in self.consumed_operation_ids
            if operation_id not in plan_ids or operation_id not in lifecycle_ids
        )
        if unexpected:
            raise ValueError(
                "DUT lifecycle result consumes unknown operations: "
                + ", ".join(str(operation_id) for operation_id in unexpected)
            )
        _validate_exact_coverage(
            "DUT lifecycle fragment",
            self.consumed_operation_ids,
            tuple(fragment.operation_id for fragment in self.fragments),
        )
        expected_order = tuple(
            operation_id
            for operation_id in lifecycle_ids
            if operation_id in self.consumed_operation_ids
        )
        if self.consumed_operation_ids != expected_order:
            raise ValueError(
                "DUT lifecycle result must follow lifecycle setup order: "
                f"expected={expected_order}, actual={self.consumed_operation_ids}"
            )
        expected_cleanup_order = tuple(
            operation.resource_id
            for operation in lifecycle.teardown_order()
            if operation.resource_id in self.consumed_operation_ids
        )
        cleanup_order = tuple(
            operation_id
            for fragment in self.cleanup_fragments
            for operation_id in fragment.operation_ids
        )
        if cleanup_order != expected_cleanup_order:
            raise ValueError(
                "DUT lifecycle cleanup must follow lifecycle teardown order: "
                f"expected={expected_cleanup_order}, actual={cleanup_order}"
            )


def _validate_unique_ids(subject: str, resource_ids: tuple[ResourceId, ...]) -> None:
    if len(frozenset(resource_ids)) != len(resource_ids):
        raise ValueError(f"{subject} resource IDs must be unique")


def _validate_exact_coverage(
    subject: str,
    expected: tuple[ResourceId, ...],
    actual: tuple[ResourceId, ...],
) -> None:
    _validate_unique_ids(subject, actual)
    missing = tuple(
        resource_id for resource_id in expected if resource_id not in actual
    )
    unexpected = tuple(
        resource_id for resource_id in actual if resource_id not in expected
    )
    if missing or unexpected:
        raise ValueError(
            f"{subject} coverage mismatch: missing={missing}, unexpected={unexpected}"
        )


__all__ = (
    "DutEndpointBaseFragment",
    "DutEndpointBaseRenderResult",
    "DutHostOsFragment",
    "DutHostOsRenderResult",
    "DutLifecycleCleanupFragment",
    "DutLifecycleFragment",
    "DutLifecycleRenderResult",
)
