# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from taac.abstractions.compilation.dut import (
    DutLifecycleCleanupFragment,
    DutLifecycleFragment,
    DutLifecycleRenderResult,
)
from taac.abstractions.compilation.lifecycle import LifecyclePlan
from taac.abstractions.compilation.model import (
    DutPlan,
    PhysicalInterfacePlan,
    ResourceId,
)
from taac.abstractions.eos_bgpcpp_renderer import (
    EosPhysicalLifecycleCleanupIntent,
    EosPhysicalLifecycleTaskIntent,
    EosRoutingConfigLifecycleCleanupIntent,
    EosRoutingConfigLifecycleTaskIntent,
)
from taac.task_definitions import (
    create_arista_create_file_from_config_task,
    create_eos_compiler_lifecycle_task,
    create_validate_bgpcpp_config_on_device_task,
)
from taac.test_as_a_config import types as taac_types


class UnsupportedEosBgpCppLifecycleMaterializationError(ValueError):
    pass


def _operation_key(operation_id: ResourceId) -> str:
    return str(operation_id)


def _task(
    *,
    action: str,
    hostname: str,
    ixia_needed: bool,
    params: t.Mapping[str, object],
) -> taac_types.Task:
    return create_eos_compiler_lifecycle_task(
        hostname=hostname,
        action=action,
        ixia_needed=ixia_needed,
        **params,
    )


def _physical_by_id(plan: DutPlan) -> dict[ResourceId, PhysicalInterfacePlan]:
    return {physical.resource_id: physical for physical in plan.physical_interfaces}


def _materialize_physical_intent(
    intent: EosPhysicalLifecycleTaskIntent,
) -> taac_types.Task:
    return _task(
        action="physical_apply",
        hostname=intent.hostname,
        ixia_needed=False,
        params={
            "operation_id": _operation_key(intent.operation_id),
            "interface": intent.interface,
            "aggregate_gbps": intent.aggregate_gbps,
            "lane_count": intent.lane_count,
            "ipv4_cidrs": list(intent.ipv4_cidrs),
            "ipv6_cidrs": list(intent.ipv6_cidrs),
        },
    )


def _materialize_routing_config_intent(
    intent: EosRoutingConfigLifecycleTaskIntent,
) -> tuple[taac_types.Task, ...]:
    common_params = {
        "operation_id": _operation_key(intent.operation_id),
        "destination": intent.destination,
    }
    return (
        _task(
            action="routing_config_snapshot",
            hostname=intent.hostname,
            ixia_needed=True,
            params=common_params,
        ),
        create_arista_create_file_from_config_task(
            hostname=intent.hostname,
            configerator_path=intent.source.path,
            file_path=intent.destination,
            ixia_needed=True,
        ),
        create_validate_bgpcpp_config_on_device_task(
            hostname=intent.hostname,
            config_path=intent.destination,
            ixia_needed=True,
        ),
        _task(
            action="routing_config_verify",
            hostname=intent.hostname,
            ixia_needed=True,
            params={
                **common_params,
                "source_path": intent.source.path,
            },
        ),
    )


def _materialize_post_ixia_task(task: object) -> tuple[object, ...]:
    if isinstance(task, EosRoutingConfigLifecycleTaskIntent):
        return _materialize_routing_config_intent(task)
    return (task,)


def _materialize_fragment(
    fragment: DutLifecycleFragment[object],
) -> DutLifecycleFragment[object]:
    return DutLifecycleFragment(
        operation_id=fragment.operation_id,
        pre_ixia_tasks=tuple(
            _materialize_physical_intent(task)
            if isinstance(task, EosPhysicalLifecycleTaskIntent)
            else task
            for task in fragment.pre_ixia_tasks
        ),
        post_ixia_tasks=tuple(
            materialized
            for task in fragment.post_ixia_tasks
            for materialized in _materialize_post_ixia_task(task)
        ),
    )


def _materialize_physical_cleanup(
    plan: DutPlan,
    intent: EosPhysicalLifecycleCleanupIntent,
) -> taac_types.Task:
    physical_by_id = _physical_by_id(plan)
    try:
        operations = [
            {
                "operation_id": _operation_key(operation_id),
                "interface": physical_by_id[operation_id].bound_interface,
            }
            for operation_id in intent.operation_ids
        ]
    except KeyError as error:
        raise UnsupportedEosBgpCppLifecycleMaterializationError(
            f"physical cleanup references unknown operation {error.args[0]}"
        ) from error
    return _task(
        action="physical_restore",
        hostname=intent.hostname,
        ixia_needed=False,
        params={"operations": operations},
    )


def _materialize_cleanup_fragment(
    plan: DutPlan,
    fragment: DutLifecycleCleanupFragment[object],
) -> DutLifecycleCleanupFragment[object]:
    task = fragment.task
    if isinstance(task, EosPhysicalLifecycleCleanupIntent):
        materialized_task: object = _materialize_physical_cleanup(plan, task)
    elif isinstance(task, EosRoutingConfigLifecycleCleanupIntent):
        materialized_task = _task(
            action="routing_config_restore",
            hostname=task.hostname,
            ixia_needed=False,
            params={
                "operation_id": _operation_key(task.operation_id),
                "destination": task.destination,
            },
        )
    else:
        materialized_task = task
    return DutLifecycleCleanupFragment(
        operation_ids=fragment.operation_ids,
        task=materialized_task,
    )


@dataclass(frozen=True)
class EosBgpCppLifecycleTaskMaterializer:
    """Incrementally lowers EOS lifecycle intent into executable TAAC tasks."""

    def materialize(
        self,
        plan: DutPlan,
        lifecycle: LifecyclePlan,
        intents: DutLifecycleRenderResult[object],
    ) -> DutLifecycleRenderResult[object]:
        del lifecycle
        return DutLifecycleRenderResult(
            consumed_operation_ids=intents.consumed_operation_ids,
            fragments=tuple(
                _materialize_fragment(fragment) for fragment in intents.fragments
            ),
            cleanup_fragments=tuple(
                _materialize_cleanup_fragment(plan, fragment)
                for fragment in intents.cleanup_fragments
            ),
        )


__all__ = (
    "EosBgpCppLifecycleTaskMaterializer",
    "UnsupportedEosBgpCppLifecycleMaterializationError",
)
