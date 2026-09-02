# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""Typed, runtime-neutral playbook composition contracts for churn families."""

from __future__ import annotations

import dataclasses
import enum
import typing as t


ActionT = t.TypeVar("ActionT")
CheckT = t.TypeVar("CheckT")
PeriodicTaskT = t.TypeVar("PeriodicTaskT")
SnapshotCheckT = t.TypeVar("SnapshotCheckT")
StepT = t.TypeVar("StepT")


class ChurnImplementation(enum.StrEnum):
    ATTRIBUTE = "attribute"
    SESSION = "session"
    ROUTE = "route"


@dataclasses.dataclass(frozen=True)
class ChurnPlaybookSpec(
    t.Generic[ActionT, CheckT, PeriodicTaskT, SnapshotCheckT, StepT]
):
    playbook_name: str
    device: str
    implementation: ChurnImplementation
    action_factory: t.Callable[[], t.Sequence[ActionT]]
    setup_steps: t.Sequence[StepT]
    prechecks: t.Sequence[CheckT]
    postchecks: t.Sequence[CheckT]
    snapshot_checks: t.Sequence[SnapshotCheckT]
    periodic_tasks: t.Sequence[PeriodicTaskT]
    cleanup_steps: t.Sequence[StepT] = ()


def _churn_playbook_spec(
    *,
    playbook_name: str,
    device: str,
    implementation: ChurnImplementation,
    action_factory: t.Callable[[], t.Sequence[ActionT]],
    setup_steps: t.Sequence[StepT],
    prechecks: t.Sequence[CheckT],
    postchecks: t.Sequence[CheckT],
    snapshot_checks: t.Sequence[SnapshotCheckT],
    periodic_tasks: t.Sequence[PeriodicTaskT],
    cleanup_steps: t.Sequence[StepT],
) -> ChurnPlaybookSpec[ActionT, CheckT, PeriodicTaskT, SnapshotCheckT, StepT]:
    return ChurnPlaybookSpec(
        playbook_name=playbook_name,
        device=device,
        implementation=implementation,
        action_factory=action_factory,
        setup_steps=tuple(setup_steps),
        prechecks=tuple(prechecks),
        postchecks=tuple(postchecks),
        snapshot_checks=tuple(snapshot_checks),
        periodic_tasks=tuple(periodic_tasks),
        cleanup_steps=tuple(cleanup_steps),
    )


def attribute_churn_spec(
    *,
    playbook_name: str,
    device: str,
    action_factory: t.Callable[[], t.Sequence[ActionT]],
    setup_steps: t.Sequence[StepT],
    prechecks: t.Sequence[CheckT],
    postchecks: t.Sequence[CheckT],
    snapshot_checks: t.Sequence[SnapshotCheckT],
    periodic_tasks: t.Sequence[PeriodicTaskT],
    cleanup_steps: t.Sequence[StepT] = (),
) -> ChurnPlaybookSpec[ActionT, CheckT, PeriodicTaskT, SnapshotCheckT, StepT]:
    return _churn_playbook_spec(
        playbook_name=playbook_name,
        device=device,
        implementation=ChurnImplementation.ATTRIBUTE,
        action_factory=action_factory,
        setup_steps=setup_steps,
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
        periodic_tasks=periodic_tasks,
        cleanup_steps=cleanup_steps,
    )


def session_churn_spec(
    *,
    playbook_name: str,
    device: str,
    action_factory: t.Callable[[], t.Sequence[ActionT]],
    setup_steps: t.Sequence[StepT],
    prechecks: t.Sequence[CheckT],
    postchecks: t.Sequence[CheckT],
    snapshot_checks: t.Sequence[SnapshotCheckT],
    periodic_tasks: t.Sequence[PeriodicTaskT],
    cleanup_steps: t.Sequence[StepT] = (),
) -> ChurnPlaybookSpec[ActionT, CheckT, PeriodicTaskT, SnapshotCheckT, StepT]:
    return _churn_playbook_spec(
        playbook_name=playbook_name,
        device=device,
        implementation=ChurnImplementation.SESSION,
        action_factory=action_factory,
        setup_steps=setup_steps,
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
        periodic_tasks=periodic_tasks,
        cleanup_steps=cleanup_steps,
    )


def route_churn_spec(
    *,
    playbook_name: str,
    device: str,
    action_factory: t.Callable[[], t.Sequence[ActionT]],
    setup_steps: t.Sequence[StepT],
    prechecks: t.Sequence[CheckT],
    postchecks: t.Sequence[CheckT],
    snapshot_checks: t.Sequence[SnapshotCheckT],
    periodic_tasks: t.Sequence[PeriodicTaskT],
    cleanup_steps: t.Sequence[StepT] = (),
) -> ChurnPlaybookSpec[ActionT, CheckT, PeriodicTaskT, SnapshotCheckT, StepT]:
    return _churn_playbook_spec(
        playbook_name=playbook_name,
        device=device,
        implementation=ChurnImplementation.ROUTE,
        action_factory=action_factory,
        setup_steps=setup_steps,
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
        periodic_tasks=periodic_tasks,
        cleanup_steps=cleanup_steps,
    )
