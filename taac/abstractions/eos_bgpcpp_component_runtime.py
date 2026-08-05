# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from taac.abstractions.validation import (
    TopologyValidationError,
    ValidationIssue,
)


@dataclass(frozen=True)
class ComponentRuntime:
    name: str
    enabled: bool = True
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class ComponentStartupOption:
    component: str
    name: str
    value: str


@dataclass(frozen=True)
class MetaComponentRuntimePlan:
    logical_topology_name: str
    hostname: str
    components: tuple[ComponentRuntime, ...]
    startup_options: tuple[ComponentStartupOption, ...]
    configuration_tasks: tuple[t.Any, ...]
    startup_tasks: tuple[t.Any, ...]


@dataclass(frozen=True)
class ComponentDeploymentTasks:
    configuration_tasks: tuple[t.Any, ...]
    startup_tasks: tuple[t.Any, ...]


class EosDaemonComponentDeployer:
    """Render tasks already resolved from component metadata by the compiler."""

    def build_tasks(
        self,
        plan: MetaComponentRuntimePlan,
    ) -> ComponentDeploymentTasks:
        return ComponentDeploymentTasks(
            configuration_tasks=plan.configuration_tasks,
            startup_tasks=plan.startup_tasks,
        )


class EosContainerComponentDeployer:
    """Reject container deployment until its runtime contract is modeled."""

    def build_tasks(
        self,
        plan: MetaComponentRuntimePlan,
    ) -> t.NoReturn:
        raise TopologyValidationError(
            plan.logical_topology_name,
            [
                ValidationIssue(
                    path="component_deployer",
                    code="container_component_deployment_not_implemented",
                    message=(
                        "EOS container component deployment is not selectable "
                        "until image, mount, readiness, and rollback semantics exist"
                    ),
                )
            ],
        )
