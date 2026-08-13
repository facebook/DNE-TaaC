# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

from taac.abstractions.compilation.lifecycle import (
    LifecycleOperation,
    LifecyclePlan,
    OwnershipMode,
    ReadinessMode,
    RestorationMode,
)
from taac.abstractions.compilation.model import (
    EndpointSetupMode,
    ResourceId,
    TopologyCompilationPlan,
)
from taac.abstractions.component_semantics import (
    ComponentReadinessRequirement,
)


class LifecycleProjectionError(ValueError):
    pass


_COMPONENT_READINESS = {
    ComponentReadinessRequirement.NONE: ReadinessMode.NONE,
    ComponentReadinessRequirement.ACKNOWLEDGED: ReadinessMode.ACKNOWLEDGED,
    ComponentReadinessRequirement.HEALTHY: ReadinessMode.HEALTH_CHECK,
}


def project_lifecycle(plan: TopologyCompilationPlan) -> LifecyclePlan:
    full_endpoint_ids = frozenset(
        endpoint.resource_id
        for endpoint in plan.dut.endpoints
        if endpoint.is_dut and endpoint.setup_mode is EndpointSetupMode.FULL
    )
    _validate_full_interface_ownership(plan, full_endpoint_ids)

    physical_operations = tuple(
        _snapshot_operation(
            physical.resource_id,
            readiness=ReadinessMode.EXACT_READBACK,
        )
        for physical in plan.dut.physical_interfaces
        if physical.endpoint_id in full_endpoint_ids
    )
    physical_ids_by_endpoint = {
        endpoint_id: tuple(
            physical.resource_id
            for physical in plan.dut.physical_interfaces
            if physical.endpoint_id == endpoint_id
        )
        for endpoint_id in full_endpoint_ids
    }
    config_operations = tuple(
        _snapshot_operation(
            config.resource_id,
            dependencies=physical_ids_by_endpoint[config.endpoint_id],
            readiness=ReadinessMode.EXACT_READBACK,
        )
        for config in plan.dut.routing_configs
        if config.endpoint_id in full_endpoint_ids
    )
    component_operations = tuple(
        _snapshot_operation(
            component.resource_id,
            dependencies=component.depends_on,
            readiness=_COMPONENT_READINESS[component.readiness],
        )
        for component in plan.dut.components
        if component.endpoint_id in full_endpoint_ids
    )
    return LifecyclePlan(
        operations=(
            *physical_operations,
            *config_operations,
            *component_operations,
        )
    )


def _snapshot_operation(
    resource_id: ResourceId,
    *,
    dependencies: tuple[ResourceId, ...] = (),
    readiness: ReadinessMode,
) -> LifecycleOperation:
    return LifecycleOperation(
        resource_id=resource_id,
        ownership=OwnershipMode.SNAPSHOT_RESTORED,
        restoration=RestorationMode.FIRST_SNAPSHOT,
        readiness=readiness,
        dependencies=dependencies,
    )


def _validate_full_interface_ownership(
    plan: TopologyCompilationPlan,
    full_endpoint_ids: frozenset[ResourceId],
) -> None:
    for interface in plan.dut.interfaces:
        if (
            interface.endpoint_id in full_endpoint_ids
            and interface.physical_interface_id is None
        ):
            raise LifecycleProjectionError(
                f"full-setup interface {interface.resource_id} has no physical owner"
            )


__all__ = (
    "LifecycleProjectionError",
    "project_lifecycle",
)
