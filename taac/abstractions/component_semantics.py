# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from enum import Enum


class ComponentRole(str, Enum):
    ROUTING_CONTROL_PLANE = "routing_control_plane"


class ComponentDesiredState(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"


class ComponentReconcileMode(str, Enum):
    NONE = "none"
    RESTART_AFTER_CONFIGURATION = "restart_after_configuration"


class ComponentReadinessRequirement(str, Enum):
    NONE = "none"
    ACKNOWLEDGED = "acknowledged"
    HEALTHY = "healthy"


__all__ = (
    "ComponentDesiredState",
    "ComponentReadinessRequirement",
    "ComponentReconcileMode",
    "ComponentRole",
)
