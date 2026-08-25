# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

from dataclasses import dataclass

from taac.abstractions.artifacts import CompiledTaacArtifacts
from taac.abstractions.compilation.basic_port_composition import (
    BasicPortCompositionResult,
)
from taac.abstractions.compilation.dut import (
    DutHostOsRenderResult,
    DutLifecycleRenderResult,
)
from taac.abstractions.compilation.endpoint_composition import (
    EndpointCompositionResult,
)
from taac.abstractions.compilation.lifecycle import LifecyclePlan
from taac.abstractions.compilation.model import (
    ResourceId,
    TopologyCompilationPlan,
)
from taac.abstractions.compilation.traffic_generator import (
    TrafficGeneratorLifecycleSlot,
    TrafficGeneratorRenderResult,
)
from taac.test_as_a_config import types as taac_types


class NativeArtifactAssemblyError(ValueError):
    """Raised when native artifact ownership cannot be assembled exactly."""


@dataclass(frozen=True)
class NativeArtifactAssemblyRequest:
    plan: TopologyCompilationPlan
    lifecycle: LifecyclePlan
    endpoints: EndpointCompositionResult[object]
    host_os: DutHostOsRenderResult[object]
    dut_lifecycle: DutLifecycleRenderResult[object]
    basic_ports: BasicPortCompositionResult[object]
    traffic_generator: TrafficGeneratorRenderResult


@dataclass(frozen=True)
class NativeTaacArtifactAssembler:
    def assemble(
        self,
        request: NativeArtifactAssemblyRequest,
    ) -> CompiledTaacArtifacts:
        _validate_resource_ownership(request)
        endpoints = _validated_endpoints(request)
        basic_port_configs = _validated_basic_ports(request)
        setup_tasks = _scheduled_setup_tasks(request)
        teardown_tasks = _validated_tasks(
            "DUT teardown",
            request.dut_lifecycle.cleanup_tasks,
        )
        return CompiledTaacArtifacts(
            endpoints=endpoints,
            host_os_type_map=request.host_os.host_os_type_map,
            setup_tasks=setup_tasks,
            teardown_tasks=teardown_tasks,
            basic_port_configs=basic_port_configs,
            basic_traffic_item_configs=list(
                request.traffic_generator.basic_traffic_item_configs
            ),
        )


def _validate_resource_ownership(request: NativeArtifactAssemblyRequest) -> None:
    expected_endpoint_ids = tuple(
        endpoint.resource_id
        for endpoint in request.plan.dut.endpoints
        if endpoint.is_dut
    )
    _require_exact_order(
        "native endpoint ownership",
        expected_endpoint_ids,
        request.endpoints.endpoint_ids,
    )
    _require_exact_order(
        "native host-OS ownership",
        expected_endpoint_ids,
        request.host_os.owned_endpoint_ids,
    )
    _require_exact_order(
        "native lifecycle ownership",
        tuple(operation.resource_id for operation in request.lifecycle.setup_order()),
        request.dut_lifecycle.consumed_operation_ids,
        allow_subset=True,
    )
    _require_exact_order(
        "native traffic-generator ownership",
        request.plan.ixia.iter_resource_ids(),
        request.traffic_generator.consumed_resource_ids,
    )
    endpoint_identifiers = tuple(
        fragment.physical_identifier for fragment in request.endpoints.fragments
    )
    if endpoint_identifiers != tuple(request.host_os.host_os_type_map):
        raise NativeArtifactAssemblyError(
            "native endpoint and host-OS ownership must use the same physical order"
        )


def _validated_endpoints(
    request: NativeArtifactAssemblyRequest,
) -> list[taac_types.Endpoint]:
    endpoints: list[taac_types.Endpoint] = []
    patch_ids = tuple(
        patch.endpoint_id for patch in request.traffic_generator.endpoint_patches
    )
    if len(frozenset(patch_ids)) != len(patch_ids):
        raise NativeArtifactAssemblyError(
            "native endpoint IXIA projection ownership is duplicated"
        )
    patches_by_id = {
        patch.endpoint_id: patch for patch in request.traffic_generator.endpoint_patches
    }
    for fragment in request.endpoints.fragments:
        endpoint = fragment.endpoint
        if not isinstance(endpoint, taac_types.Endpoint):
            raise NativeArtifactAssemblyError(
                f"native endpoint {fragment.endpoint_id} is not a TAAC Endpoint"
            )
        patch = patches_by_id.get(fragment.endpoint_id)
        if patch is None:
            raise NativeArtifactAssemblyError(
                f"native endpoint {fragment.endpoint_id} has no IXIA projection"
            )
        if endpoint.ixia_ports != list(patch.ixia_ports) or (
            endpoint.direct_ixia_connections != list(patch.direct_ixia_connections)
        ):
            raise NativeArtifactAssemblyError(
                f"native endpoint {fragment.endpoint_id} has mixed IXIA ownership"
            )
        endpoints.append(endpoint)
    if tuple(patches_by_id) != request.endpoints.endpoint_ids:
        raise NativeArtifactAssemblyError(
            "native endpoint IXIA projection coverage mismatch"
        )
    return endpoints


def _validated_basic_ports(
    request: NativeArtifactAssemblyRequest,
) -> list[taac_types.BasicPortConfig]:
    configs: list[taac_types.BasicPortConfig] = []
    for fragment in request.basic_ports.fragments:
        config = fragment.basic_port_config
        if not isinstance(config, taac_types.BasicPortConfig):
            raise NativeArtifactAssemblyError(
                f"native IXIA port {fragment.port_id} is not a TAAC BasicPortConfig"
            )
        configs.append(config)
    if tuple(configs) != request.traffic_generator.basic_port_configs:
        raise NativeArtifactAssemblyError(
            "native basic-port renderers have duplicate or mixed ownership"
        )
    return configs


def _scheduled_setup_tasks(
    request: NativeArtifactAssemblyRequest,
) -> list[taac_types.Task]:
    pre_ixia = _validated_tasks(
        "DUT pre-IXIA",
        request.dut_lifecycle.pre_ixia_tasks,
        ixia_needed=False,
    )
    traffic_generator = _validated_traffic_generator_tasks(request)
    post_ixia = _validated_tasks(
        "DUT post-IXIA",
        request.dut_lifecycle.post_ixia_tasks,
        ixia_needed=True,
    )
    return [*pre_ixia, *traffic_generator, *post_ixia]


def _validated_traffic_generator_tasks(
    request: NativeArtifactAssemblyRequest,
) -> list[taac_types.Task]:
    tasks: list[taac_types.Task] = []
    for fragment in request.traffic_generator.lifecycle_fragments:
        if fragment.slot is not TrafficGeneratorLifecycleSlot.CONFIGURATION:
            raise NativeArtifactAssemblyError(
                f"unsupported traffic-generator lifecycle slot {fragment.slot}"
            )
        tasks.extend(
            _validated_tasks(
                "traffic-generator configuration",
                fragment.tasks,
                ixia_needed=True,
            )
        )
    return tasks


def _validated_tasks(
    subject: str,
    tasks: tuple[object, ...],
    *,
    ixia_needed: bool | None = None,
) -> list[taac_types.Task]:
    result: list[taac_types.Task] = []
    for task in tasks:
        if not isinstance(task, taac_types.Task):
            raise NativeArtifactAssemblyError(f"{subject} contains a non-Task value")
        if ixia_needed is not None and task.ixia_needed is not ixia_needed:
            raise NativeArtifactAssemblyError(
                f"{subject} task {task.task_name} has lifecycle lane drift"
            )
        result.append(task)
    return result


def _require_exact_order(
    subject: str,
    expected: tuple[ResourceId, ...],
    actual: tuple[ResourceId, ...],
    *,
    allow_subset: bool = False,
) -> None:
    if len(frozenset(actual)) != len(actual):
        raise NativeArtifactAssemblyError(f"{subject} is duplicated")
    expected_actual = (
        tuple(resource_id for resource_id in expected if resource_id in actual)
        if allow_subset
        else expected
    )
    if actual != expected_actual:
        expected_description = (
            f"{expected_actual} (subset of {expected})"
            if allow_subset
            else str(expected_actual)
        )
        raise NativeArtifactAssemblyError(
            f"{subject} mismatch: expected={expected_description}, actual={actual}"
        )


__all__ = (
    "NativeArtifactAssemblyError",
    "NativeArtifactAssemblyRequest",
    "NativeTaacArtifactAssembler",
)
