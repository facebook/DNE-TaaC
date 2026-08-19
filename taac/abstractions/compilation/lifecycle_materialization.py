# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

from taac.abstractions.compilation.dut import (
    DutLifecycleFragment,
    DutLifecycleRenderResult,
)
from taac.abstractions.compilation.lifecycle import LifecyclePlan
from taac.abstractions.compilation.model import (
    DutPlan,
    ResourceId,
)


class LifecycleTaskMaterializationError(ValueError):
    """Raised when task materialization changes validated lifecycle ownership."""


def _fragment_ids(
    result: DutLifecycleRenderResult[object],
) -> tuple[ResourceId, ...]:
    return tuple(fragment.operation_id for fragment in result.fragments)


def _lane_signature(
    fragment: DutLifecycleFragment[object],
) -> tuple[bool, bool]:
    return (bool(fragment.pre_ixia_tasks), bool(fragment.post_ixia_tasks))


def _lane_cardinality(
    fragment: DutLifecycleFragment[object],
) -> tuple[int, int]:
    return (len(fragment.pre_ixia_tasks), len(fragment.post_ixia_tasks))


def _cleanup_groups(
    result: DutLifecycleRenderResult[object],
) -> tuple[tuple[ResourceId, ...], ...]:
    return tuple(fragment.operation_ids for fragment in result.cleanup_fragments)


def _validate_non_null_tasks(result: DutLifecycleRenderResult[object]) -> None:
    setup_tasks = tuple(
        task
        for fragment in result.fragments
        for task in (*fragment.pre_ixia_tasks, *fragment.post_ixia_tasks)
    )
    cleanup_tasks = tuple(fragment.task for fragment in result.cleanup_fragments)
    if any(task is None for task in (*setup_tasks, *cleanup_tasks)):
        raise LifecycleTaskMaterializationError(
            "materialized lifecycle tasks must be non-null"
        )


def validate_lifecycle_task_materialization(
    plan: DutPlan,
    lifecycle: LifecyclePlan,
    intents: DutLifecycleRenderResult[object],
    tasks: DutLifecycleRenderResult[object],
) -> None:
    """Proves task lowering preserves intent coverage, lanes, and cleanup groups."""

    intents.validate(plan, lifecycle)
    if tasks.consumed_operation_ids != intents.consumed_operation_ids:
        raise LifecycleTaskMaterializationError(
            "materialized lifecycle operation coverage drift: "
            f"expected={intents.consumed_operation_ids}, "
            f"actual={tasks.consumed_operation_ids}"
        )
    if _fragment_ids(tasks) != _fragment_ids(intents):
        raise LifecycleTaskMaterializationError(
            "materialized lifecycle fragment order drift"
        )
    expected_lanes = tuple(_lane_signature(fragment) for fragment in intents.fragments)
    actual_lanes = tuple(_lane_signature(fragment) for fragment in tasks.fragments)
    if actual_lanes != expected_lanes:
        raise LifecycleTaskMaterializationError(
            f"materialized lifecycle lane drift: expected={expected_lanes}, "
            f"actual={actual_lanes}"
        )
    expected_cardinality = tuple(
        _lane_cardinality(fragment) for fragment in intents.fragments
    )
    actual_cardinality = tuple(
        _lane_cardinality(fragment) for fragment in tasks.fragments
    )
    if any(
        actual_pre < expected_pre or actual_post < expected_post
        for (expected_pre, expected_post), (actual_pre, actual_post) in zip(
            expected_cardinality,
            actual_cardinality,
            strict=True,
        )
    ):
        raise LifecycleTaskMaterializationError(
            "materialized lifecycle intent cardinality drift: "
            f"minimum={expected_cardinality}, actual={actual_cardinality}"
        )
    if _cleanup_groups(tasks) != _cleanup_groups(intents):
        raise LifecycleTaskMaterializationError(
            "materialized lifecycle cleanup grouping drift"
        )
    _validate_non_null_tasks(tasks)
    tasks.validate(plan, lifecycle)


__all__ = (
    "LifecycleTaskMaterializationError",
    "validate_lifecycle_task_materialization",
)
