# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe

"""Render DICE churn specifications into the flat TAAC Playbook contract."""

from __future__ import annotations

from taac.abstractions.churn.playbook import ChurnPlaybookSpec
from taac.test_as_a_config.types import Playbook


def create_dice_unified_churn_playbook(*, spec: ChurnPlaybookSpec) -> Playbook:
    if not spec.playbook_name:
        raise ValueError("a churn playbook requires a name")
    if not spec.device:
        raise ValueError("a churn playbook requires a device")

    stages = list(spec.action_factory())
    if not stages:
        raise ValueError(
            f"{spec.implementation.value} churn action factory returned no stages"
        )

    fields = {
        "name": spec.playbook_name,
        "setup_steps": list(spec.setup_steps),
        "prechecks": list(spec.prechecks),
        "postchecks": list(spec.postchecks),
        "snapshot_checks": list(spec.snapshot_checks),
        "periodic_tasks": list(spec.periodic_tasks),
        "stages": stages,
    }
    if spec.cleanup_steps:
        fields["cleanup_steps"] = list(spec.cleanup_steps)
    return Playbook(**fields)
