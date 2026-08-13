# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

import ipaddress
import typing as t
from dataclasses import dataclass
from enum import Enum

from taac.abstractions.compilation.dut import (
    DutEndpointBaseFragment,
    DutEndpointBaseRenderResult,
    DutHostOsFragment,
    DutHostOsRenderResult,
    DutLifecycleCleanupFragment,
    DutLifecycleFragment,
    DutLifecycleRenderResult,
)
from taac.abstractions.compilation.lifecycle import (
    LifecycleOperation,
    LifecyclePlan,
    OwnershipMode,
    ReadinessMode,
    RestorationMode,
)
from taac.abstractions.compilation.model import (
    AddressFamily,
    ComponentPlan,
    DutPlan,
    EndpointPlan,
    EndpointSetupMode,
    OpenRDesiredMode,
    PhysicalInterfacePlan,
    ResourceId,
    ResourceKind,
    RoutingConfigPlan,
)
from taac.abstractions.component_semantics import (
    ComponentDesiredState,
    ComponentReadinessRequirement,
    ComponentReconcileMode,
    ComponentRole,
)
from taac.abstractions.config_artifact_semantics import (
    ConfigArtifactProvider,
    ConfigArtifactRef,
)
from pyre_extensions import none_throws
from taac.test_as_a_config import types as taac_types


class UnsupportedEosBgpCppHostOsRenderingError(ValueError):
    pass


class UnsupportedEosBgpCppEndpointBaseRenderingError(ValueError):
    pass


class UnsupportedEosBgpCppLifecycleRenderingError(ValueError):
    pass


class EosPhysicalLifecycleAction(str, Enum):
    REALIZE_AND_VERIFY = "realize_and_verify"


class EosRoutingConfigLifecycleAction(str, Enum):
    INSTALL_AND_VERIFY = "install_and_verify"


class EosRoutingComponentLifecycleAction(str, Enum):
    RECONCILE_AND_ACKNOWLEDGE = "reconcile_and_acknowledge"


_EOS_BGPCPP_CONFIG_DESTINATION = "/mnt/flash/bgpcpp_config"


@dataclass(frozen=True)
class EosPhysicalLifecycleTaskIntent:
    action: EosPhysicalLifecycleAction
    hostname: str
    operation_id: ResourceId
    interface: str
    aggregate_gbps: int
    lane_count: int
    ipv4_cidrs: tuple[str, ...]
    ipv6_cidrs: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.action is not EosPhysicalLifecycleAction.REALIZE_AND_VERIFY:
            raise TypeError("EOS physical lifecycle action must be typed")
        if not self.hostname or not self.interface:
            raise ValueError("EOS physical hostname and interface must be nonempty")
        if self.operation_id.kind is not ResourceKind.PHYSICAL_INTERFACE:
            raise ValueError(
                "EOS physical lifecycle operation must target an interface"
            )
        for name, value in (
            ("aggregate_gbps", self.aggregate_gbps),
            ("lane_count", self.lane_count),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"EOS physical {name} must be a positive integer")
        _validate_cidrs(self.ipv4_cidrs, version=4)
        _validate_cidrs(self.ipv6_cidrs, version=6)


@dataclass(frozen=True)
class EosPhysicalLifecycleCleanupIntent:
    hostname: str
    operation_ids: tuple[ResourceId, ...]

    def __post_init__(self) -> None:
        if not self.hostname:
            raise ValueError("EOS physical cleanup hostname must be nonempty")
        if not self.operation_ids:
            raise ValueError("EOS physical cleanup must target an operation")
        if len(frozenset(self.operation_ids)) != len(self.operation_ids):
            raise ValueError("EOS physical cleanup operation IDs must be unique")
        if any(
            operation_id.kind is not ResourceKind.PHYSICAL_INTERFACE
            for operation_id in self.operation_ids
        ):
            raise ValueError("EOS physical cleanup must target physical interfaces")


@dataclass(frozen=True)
class EosRoutingConfigLifecycleTaskIntent:
    action: EosRoutingConfigLifecycleAction
    hostname: str
    operation_id: ResourceId
    source: ConfigArtifactRef
    destination: str
    required_features: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.action is not EosRoutingConfigLifecycleAction.INSTALL_AND_VERIFY:
            raise TypeError("EOS routing-config lifecycle action must be typed")
        _validate_routing_config_intent_fields(
            self.hostname,
            self.operation_id,
            self.destination,
        )
        if not isinstance(self.source, ConfigArtifactRef):
            raise TypeError("EOS routing-config source must be typed")
        if self.source.provider is not ConfigArtifactProvider.CONFIGERATOR:
            raise ValueError("EOS routing-config source must be Configerator-owned")
        if not isinstance(self.required_features, tuple) or any(
            not isinstance(feature, str) or not feature
            for feature in self.required_features
        ):
            raise ValueError(
                "EOS routing-config required features must be nonempty strings"
            )
        if len(frozenset(self.required_features)) != len(self.required_features):
            raise ValueError("EOS routing-config required features must be unique")


@dataclass(frozen=True)
class EosRoutingConfigLifecycleCleanupIntent:
    hostname: str
    operation_id: ResourceId
    destination: str

    def __post_init__(self) -> None:
        _validate_routing_config_intent_fields(
            self.hostname,
            self.operation_id,
            self.destination,
        )


@dataclass(frozen=True)
class EosRoutingDaemonIntent:
    name: str
    enabled: bool
    dependencies: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("EOS routing daemon name must be nonempty")
        if not isinstance(self.enabled, bool):
            raise TypeError("EOS routing daemon enabled state must be a bool")
        if not isinstance(self.dependencies, tuple) or any(
            not isinstance(dependency, str) or not dependency
            for dependency in self.dependencies
        ):
            raise ValueError("EOS routing daemon dependencies must be names")
        if self.name in self.dependencies:
            raise ValueError("EOS routing daemon cannot depend on itself")
        if len(frozenset(self.dependencies)) != len(self.dependencies):
            raise ValueError("EOS routing daemon dependencies must be unique")


@dataclass(frozen=True)
class EosRoutingStartupOptionIntent:
    daemon: str
    name: str
    value: str

    def __post_init__(self) -> None:
        if any(
            not isinstance(field, str) or not field
            for field in (self.daemon, self.name, self.value)
        ):
            raise ValueError("EOS routing startup option fields must be nonempty")


@dataclass(frozen=True)
class EosRoutingComponentLifecycleTaskIntent:
    action: EosRoutingComponentLifecycleAction
    hostname: str
    operation_id: ResourceId
    routing_config_id: ResourceId
    daemons: tuple[EosRoutingDaemonIntent, ...]
    startup_options: tuple[EosRoutingStartupOptionIntent, ...]

    def __post_init__(self) -> None:
        if (
            self.action
            is not EosRoutingComponentLifecycleAction.RECONCILE_AND_ACKNOWLEDGE
        ):
            raise TypeError("EOS routing-component lifecycle action must be typed")
        _validate_routing_component_intent_fields(
            self.hostname,
            self.operation_id,
            self.routing_config_id,
            self.daemons,
            self.startup_options,
        )


@dataclass(frozen=True)
class EosRoutingComponentLifecycleCleanupIntent:
    hostname: str
    operation_id: ResourceId
    daemon_names: tuple[str, ...]
    startup_option_keys: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.hostname, str) or not self.hostname:
            raise ValueError("EOS routing-component hostname must be nonempty")
        if self.operation_id.kind is not ResourceKind.COMPONENT:
            raise ValueError(
                "EOS routing-component lifecycle operation must target component"
            )
        if (
            not isinstance(self.daemon_names, tuple)
            or not self.daemon_names
            or any(not isinstance(name, str) or not name for name in self.daemon_names)
        ):
            raise ValueError("EOS routing-component cleanup requires daemon names")
        if len(frozenset(self.daemon_names)) != len(self.daemon_names):
            raise ValueError("EOS routing-component cleanup daemons must be unique")
        if not isinstance(self.startup_option_keys, tuple) or any(
            len(key) != 2
            or any(not isinstance(value, str) or not value for value in key)
            for key in self.startup_option_keys
        ):
            raise ValueError("EOS routing-component cleanup option keys are invalid")
        if len(frozenset(self.startup_option_keys)) != len(self.startup_option_keys):
            raise ValueError("EOS routing-component cleanup option keys must be unique")


@dataclass(frozen=True)
class EosBgpCppHostOsRenderer:
    """Lowers EOS/BGP++ host-OS metadata in shadow mode."""

    def render(
        self,
        plan: DutPlan,
    ) -> DutHostOsRenderResult[taac_types.DeviceOsType]:
        endpoint, physical_identifier = _required_eos_dut_endpoint(
            plan,
            subject="host-OS",
            error_type=UnsupportedEosBgpCppHostOsRenderingError,
        )

        result = DutHostOsRenderResult(
            owned_endpoint_ids=(endpoint.resource_id,),
            fragments=(
                DutHostOsFragment(
                    endpoint_id=endpoint.resource_id,
                    physical_identifier=physical_identifier,
                    os_type=taac_types.DeviceOsType.ARISTA_FBOSS,
                ),
            ),
        )
        result.validate(plan)
        return result


@dataclass(frozen=True)
class EosBgpCppEndpointBaseRenderer:
    """Lowers EOS-owned endpoint fields without IXIA wiring."""

    def render(
        self,
        plan: DutPlan,
    ) -> DutEndpointBaseRenderResult[taac_types.Endpoint]:
        endpoint, physical_identifier = _required_eos_dut_endpoint(
            plan,
            subject="endpoint-base",
            error_type=UnsupportedEosBgpCppEndpointBaseRenderingError,
        )
        result = DutEndpointBaseRenderResult(
            owned_endpoint_ids=(endpoint.resource_id,),
            fragments=(
                DutEndpointBaseFragment(
                    endpoint_id=endpoint.resource_id,
                    physical_identifier=physical_identifier,
                    endpoint=taac_types.Endpoint(
                        name=physical_identifier,
                        dut=True,
                    ),
                ),
            ),
        )
        result.validate(plan)
        return result


@dataclass(frozen=True)
class EosBgpCppLifecycleRenderer:
    """Lowers exact EOS lifecycle intent without artifact authority."""

    def render(
        self,
        plan: DutPlan,
        lifecycle: LifecyclePlan,
    ) -> DutLifecycleRenderResult[object]:
        endpoint, hostname = _required_eos_dut_endpoint(
            plan,
            subject="lifecycle",
            error_type=UnsupportedEosBgpCppLifecycleRenderingError,
        )
        physical_by_id = {
            physical.resource_id: physical for physical in plan.physical_interfaces
        }
        routing_config = _required_routing_config(plan, endpoint)
        component = _required_routing_component(plan, endpoint, routing_config)
        _require_openr_none(plan, endpoint)
        supported_kinds = {
            ResourceKind.COMPONENT,
            ResourceKind.PHYSICAL_INTERFACE,
            ResourceKind.ROUTING_CONFIG,
        }
        operations = tuple(
            operation
            for operation in lifecycle.setup_order()
            if operation.resource_id.kind in supported_kinds
        )
        expected_ids = (
            (
                *tuple(physical_by_id),
                routing_config.resource_id,
                component.resource_id,
            )
            if endpoint.setup_mode is EndpointSetupMode.FULL
            else ()
        )
        operation_ids = tuple(operation.resource_id for operation in operations)
        if len(operation_ids) != len(expected_ids) or frozenset(
            operation_ids
        ) != frozenset(expected_ids):
            raise UnsupportedEosBgpCppLifecycleRenderingError(
                "EOS/BGP++ lifecycle coverage mismatch: "
                f"expected={expected_ids}, actual={operation_ids}"
            )

        fragments = tuple(
            self._render_fragment(
                plan,
                hostname,
                physical_by_id,
                routing_config,
                component,
                operation,
            )
            for operation in operations
        )
        teardown_ids = tuple(
            operation.resource_id
            for operation in lifecycle.teardown_order()
            if operation.resource_id.kind in supported_kinds
        )
        expected_teardown_ids = tuple(reversed(operation_ids))
        if teardown_ids != expected_teardown_ids:
            raise UnsupportedEosBgpCppLifecycleRenderingError(
                "EOS/BGP++ cleanup must reverse setup order: "
                f"expected={expected_teardown_ids}, actual={teardown_ids}"
            )
        result = DutLifecycleRenderResult[object](
            consumed_operation_ids=operation_ids,
            fragments=fragments,
            cleanup_fragments=self._render_cleanup_fragments(
                hostname,
                teardown_ids,
            ),
        )
        result.validate(plan, lifecycle)
        return result

    def _render_fragment(
        self,
        plan: DutPlan,
        hostname: str,
        physical_by_id: dict[ResourceId, PhysicalInterfacePlan],
        routing_config: RoutingConfigPlan,
        component: ComponentPlan,
        operation: LifecycleOperation,
    ) -> DutLifecycleFragment[object]:
        if operation.resource_id.kind is ResourceKind.COMPONENT:
            return self._render_routing_component_fragment(
                hostname,
                component,
                operation,
            )
        if operation.resource_id.kind is ResourceKind.ROUTING_CONFIG:
            return self._render_routing_config_fragment(
                plan,
                hostname,
                routing_config,
                operation,
            )
        physical = physical_by_id[operation.resource_id]
        _validate_physical_operation(operation)
        ipv4_cidrs, ipv6_cidrs = _physical_cidrs(plan, physical.resource_id)
        return DutLifecycleFragment(
            operation_id=physical.resource_id,
            pre_ixia_tasks=(
                EosPhysicalLifecycleTaskIntent(
                    action=EosPhysicalLifecycleAction.REALIZE_AND_VERIFY,
                    hostname=hostname,
                    operation_id=physical.resource_id,
                    interface=physical.bound_interface,
                    aggregate_gbps=physical.profile.rate.aggregate_gbps,
                    lane_count=physical.profile.rate.lane_count,
                    ipv4_cidrs=ipv4_cidrs,
                    ipv6_cidrs=ipv6_cidrs,
                ),
            ),
        )

    def _render_routing_config_fragment(
        self,
        plan: DutPlan,
        hostname: str,
        routing_config: RoutingConfigPlan,
        operation: LifecycleOperation,
    ) -> DutLifecycleFragment[object]:
        physical_ids = tuple(
            physical.resource_id
            for physical in plan.physical_interfaces
            if physical.endpoint_id == routing_config.endpoint_id
        )
        _validate_routing_config_operation(
            operation,
            routing_config,
            physical_ids,
        )
        source = none_throws(routing_config.source)
        return DutLifecycleFragment(
            operation_id=routing_config.resource_id,
            post_ixia_tasks=(
                EosRoutingConfigLifecycleTaskIntent(
                    action=EosRoutingConfigLifecycleAction.INSTALL_AND_VERIFY,
                    hostname=hostname,
                    operation_id=routing_config.resource_id,
                    source=source,
                    destination=_EOS_BGPCPP_CONFIG_DESTINATION,
                    required_features=routing_config.required_features,
                ),
            ),
        )

    def _render_routing_component_fragment(
        self,
        hostname: str,
        component: ComponentPlan,
        operation: LifecycleOperation,
    ) -> DutLifecycleFragment[object]:
        _validate_routing_component_operation(operation, component)
        daemons = _eos_routing_daemons()
        startup_options = _eos_routing_startup_options()
        return DutLifecycleFragment(
            operation_id=component.resource_id,
            post_ixia_tasks=(
                EosRoutingComponentLifecycleTaskIntent(
                    action=(
                        EosRoutingComponentLifecycleAction.RECONCILE_AND_ACKNOWLEDGE
                    ),
                    hostname=hostname,
                    operation_id=component.resource_id,
                    routing_config_id=component.depends_on[0],
                    daemons=daemons,
                    startup_options=startup_options,
                ),
            ),
        )

    def _render_cleanup_fragments(
        self,
        hostname: str,
        teardown_ids: tuple[ResourceId, ...],
    ) -> tuple[DutLifecycleCleanupFragment[object], ...]:
        component_ids = tuple(
            operation_id
            for operation_id in teardown_ids
            if operation_id.kind is ResourceKind.COMPONENT
        )
        routing_config_ids = tuple(
            operation_id
            for operation_id in teardown_ids
            if operation_id.kind is ResourceKind.ROUTING_CONFIG
        )
        physical_ids = tuple(
            operation_id
            for operation_id in teardown_ids
            if operation_id.kind is ResourceKind.PHYSICAL_INTERFACE
        )
        if teardown_ids != (*component_ids, *routing_config_ids, *physical_ids):
            raise UnsupportedEosBgpCppLifecycleRenderingError(
                "EOS/BGP++ cleanup must restore components, config, then interfaces"
            )
        daemons = _eos_routing_daemons()
        startup_options = _eos_routing_startup_options()
        return (
            *(
                DutLifecycleCleanupFragment(
                    operation_ids=(operation_id,),
                    task=EosRoutingComponentLifecycleCleanupIntent(
                        hostname=hostname,
                        operation_id=operation_id,
                        daemon_names=tuple(daemon.name for daemon in daemons),
                        startup_option_keys=tuple(
                            (option.daemon, option.name) for option in startup_options
                        ),
                    ),
                )
                for operation_id in component_ids
            ),
            *(
                DutLifecycleCleanupFragment(
                    operation_ids=(operation_id,),
                    task=EosRoutingConfigLifecycleCleanupIntent(
                        hostname=hostname,
                        operation_id=operation_id,
                        destination=_EOS_BGPCPP_CONFIG_DESTINATION,
                    ),
                )
                for operation_id in routing_config_ids
            ),
            *(
                (
                    DutLifecycleCleanupFragment(
                        operation_ids=physical_ids,
                        task=EosPhysicalLifecycleCleanupIntent(
                            hostname=hostname,
                            operation_ids=physical_ids,
                        ),
                    ),
                )
                if physical_ids
                else ()
            ),
        )


def _required_routing_config(
    plan: DutPlan,
    endpoint: EndpointPlan,
) -> RoutingConfigPlan:
    if len(plan.routing_configs) != 1:
        raise UnsupportedEosBgpCppLifecycleRenderingError(
            "EOS/BGP++ lifecycle rendering requires exactly one routing config; "
            f"found {len(plan.routing_configs)}"
        )
    routing_config = plan.routing_configs[0]
    if routing_config.endpoint_id != endpoint.resource_id:
        raise UnsupportedEosBgpCppLifecycleRenderingError(
            f"routing config {routing_config.resource_id} targets "
            f"{routing_config.endpoint_id}, expected {endpoint.resource_id}"
        )
    if routing_config.routing_driver != "bgpcpp":
        raise UnsupportedEosBgpCppLifecycleRenderingError(
            f"routing config {routing_config.resource_id} has unsupported driver "
            f"{routing_config.routing_driver!r}"
        )
    source = routing_config.source
    if endpoint.setup_mode is EndpointSetupMode.FULL and source is None:
        raise UnsupportedEosBgpCppLifecycleRenderingError(
            f"routing config {routing_config.resource_id} has no artifact source"
        )
    if (
        source is not None
        and source.provider is not ConfigArtifactProvider.CONFIGERATOR
    ):
        raise UnsupportedEosBgpCppLifecycleRenderingError(
            f"routing config {routing_config.resource_id} has unsupported source "
            f"provider {source.provider.value!r}"
        )
    return routing_config


def _required_routing_component(
    plan: DutPlan,
    endpoint: EndpointPlan,
    routing_config: RoutingConfigPlan,
) -> ComponentPlan:
    if len(plan.components) != 1:
        raise UnsupportedEosBgpCppLifecycleRenderingError(
            "EOS/BGP++ lifecycle rendering requires exactly one routing component; "
            f"found {len(plan.components)}"
        )
    component = plan.components[0]
    expected = (
        endpoint.resource_id,
        ComponentRole.ROUTING_CONTROL_PLANE,
        ComponentDesiredState.RUNNING,
        ComponentReconcileMode.RESTART_AFTER_CONFIGURATION,
        ComponentReadinessRequirement.ACKNOWLEDGED,
        (routing_config.resource_id,),
    )
    actual = (
        component.endpoint_id,
        component.role,
        component.desired_state,
        component.reconcile_mode,
        component.readiness,
        component.depends_on,
    )
    if actual != expected:
        raise UnsupportedEosBgpCppLifecycleRenderingError(
            f"component {component.resource_id} has unsupported routing-control-plane "
            f"contract: expected={expected}, actual={actual}"
        )
    return component


def _require_openr_none(plan: DutPlan, endpoint: EndpointPlan) -> None:
    openr_plans = tuple(
        openr for openr in plan.openr if openr.endpoint_id == endpoint.resource_id
    )
    if len(openr_plans) != 1 or openr_plans[0].mode is not OpenRDesiredMode.NONE:
        actual = tuple((openr.resource_id, openr.mode) for openr in openr_plans)
        raise UnsupportedEosBgpCppLifecycleRenderingError(
            "EOS/BGP++ routing-component lifecycle requires one OpenR NONE plan; "
            f"actual={actual}"
        )


def _validate_routing_component_operation(
    operation: LifecycleOperation,
    component: ComponentPlan,
) -> None:
    expected = (
        component.resource_id,
        OwnershipMode.SNAPSHOT_RESTORED,
        RestorationMode.FIRST_SNAPSHOT,
        ReadinessMode.ACKNOWLEDGED,
        component.depends_on,
        True,
    )
    actual = (
        operation.resource_id,
        operation.ownership,
        operation.restoration,
        operation.readiness,
        operation.dependencies,
        operation.state_changing,
    )
    if actual != expected:
        raise UnsupportedEosBgpCppLifecycleRenderingError(
            f"routing-component operation {operation.resource_id} has unsupported "
            f"lifecycle contract: expected={expected}, actual={actual}"
        )


def _eos_routing_daemons() -> tuple[EosRoutingDaemonIntent, ...]:
    return (
        EosRoutingDaemonIntent(name="FibGrpc", enabled=True),
        EosRoutingDaemonIntent(name="FibBgpGrpc", enabled=True),
        EosRoutingDaemonIntent(
            name="FibAgent",
            enabled=True,
            dependencies=("FibGrpc",),
        ),
        EosRoutingDaemonIntent(
            name="FibAgentBgp",
            enabled=True,
            dependencies=("FibBgpGrpc",),
        ),
        EosRoutingDaemonIntent(name="Openr", enabled=False),
        EosRoutingDaemonIntent(
            name="Bgp",
            enabled=True,
            dependencies=("FibAgent", "FibAgentBgp"),
        ),
    )


def _eos_routing_startup_options() -> tuple[EosRoutingStartupOptionIntent, ...]:
    return (
        EosRoutingStartupOptionIntent(
            daemon="Bgp",
            name="bgp_resolve_nexthops_from_interface_state",
            value="true",
        ),
    )


def _validate_routing_component_intent_fields(
    hostname: str,
    operation_id: ResourceId,
    routing_config_id: ResourceId,
    daemons: tuple[EosRoutingDaemonIntent, ...],
    startup_options: tuple[EosRoutingStartupOptionIntent, ...],
) -> None:
    if not isinstance(hostname, str) or not hostname:
        raise ValueError("EOS routing-component hostname must be nonempty")
    if operation_id.kind is not ResourceKind.COMPONENT:
        raise ValueError(
            "EOS routing-component lifecycle operation must target component"
        )
    if routing_config_id.kind is not ResourceKind.ROUTING_CONFIG:
        raise ValueError("EOS routing component must depend on routing config")
    if (
        not isinstance(daemons, tuple)
        or not daemons
        or any(not isinstance(daemon, EosRoutingDaemonIntent) for daemon in daemons)
    ):
        raise ValueError("EOS routing component requires typed daemon intent")
    daemon_names = tuple(daemon.name for daemon in daemons)
    if len(frozenset(daemon_names)) != len(daemon_names):
        raise ValueError("EOS routing daemon names must be unique")
    seen_daemons: set[str] = set()
    for daemon in daemons:
        missing = tuple(
            dependency
            for dependency in daemon.dependencies
            if dependency not in seen_daemons
        )
        if missing:
            raise ValueError(
                f"EOS routing daemon {daemon.name!r} has unordered dependencies "
                f"{missing}"
            )
        seen_daemons.add(daemon.name)
    if not isinstance(startup_options, tuple) or any(
        not isinstance(option, EosRoutingStartupOptionIntent)
        for option in startup_options
    ):
        raise ValueError("EOS routing startup options must be typed")
    option_keys = tuple((option.daemon, option.name) for option in startup_options)
    if len(frozenset(option_keys)) != len(option_keys):
        raise ValueError("EOS routing startup option keys must be unique")
    enabled_daemons = frozenset(daemon.name for daemon in daemons if daemon.enabled)
    unknown_options = tuple(key for key in option_keys if key[0] not in enabled_daemons)
    if unknown_options:
        raise ValueError(
            f"EOS routing startup options target disabled daemons {unknown_options}"
        )


def _validate_routing_config_operation(
    operation: LifecycleOperation,
    routing_config: RoutingConfigPlan,
    physical_ids: tuple[ResourceId, ...],
) -> None:
    expected = (
        routing_config.resource_id,
        OwnershipMode.SNAPSHOT_RESTORED,
        RestorationMode.FIRST_SNAPSHOT,
        ReadinessMode.EXACT_READBACK,
        physical_ids,
        True,
    )
    actual = (
        operation.resource_id,
        operation.ownership,
        operation.restoration,
        operation.readiness,
        operation.dependencies,
        operation.state_changing,
    )
    dependencies_match = len(operation.dependencies) == len(physical_ids) and frozenset(
        operation.dependencies
    ) == frozenset(physical_ids)
    if (
        actual[:4] != expected[:4]
        or not dependencies_match
        or actual[5:] != expected[5:]
    ):
        raise UnsupportedEosBgpCppLifecycleRenderingError(
            f"routing-config operation {operation.resource_id} has unsupported "
            f"lifecycle contract: expected={expected}, actual={actual}"
        )


def _validate_routing_config_intent_fields(
    hostname: str,
    operation_id: ResourceId,
    destination: str,
) -> None:
    if not isinstance(hostname, str) or not hostname:
        raise ValueError("EOS routing-config hostname must be nonempty")
    if operation_id.kind is not ResourceKind.ROUTING_CONFIG:
        raise ValueError("EOS routing-config lifecycle operation must target config")
    if (
        not isinstance(destination, str)
        or not destination.startswith("/")
        or not destination.isascii()
        or any(
            not (character.isalnum() or character in "/._-")
            for character in destination
        )
    ):
        raise ValueError("EOS routing-config destination must be a safe absolute path")


def _validate_physical_operation(operation: LifecycleOperation) -> None:
    expected = (
        OwnershipMode.SNAPSHOT_RESTORED,
        RestorationMode.FIRST_SNAPSHOT,
        ReadinessMode.EXACT_READBACK,
        (),
        True,
    )
    actual = (
        operation.ownership,
        operation.restoration,
        operation.readiness,
        operation.dependencies,
        operation.state_changing,
    )
    if actual != expected:
        raise UnsupportedEosBgpCppLifecycleRenderingError(
            f"physical operation {operation.resource_id} has unsupported lifecycle "
            f"contract: expected={expected}, actual={actual}"
        )


def _physical_cidrs(
    plan: DutPlan,
    physical_id: ResourceId,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    ipv4_cidrs: list[str] = []
    ipv6_cidrs: list[str] = []
    interfaces = tuple(
        interface
        for interface in plan.interfaces
        if interface.physical_interface_id == physical_id
    )
    if not interfaces:
        raise UnsupportedEosBgpCppLifecycleRenderingError(
            f"physical operation {physical_id} has no logical interface members"
        )
    seen_cidrs: set[str] = set()
    for interface in interfaces:
        expected_addresses = tuple(
            adjacency.local_address
            for adjacency in plan.adjacencies
            if adjacency.link_id in interface.link_ids
        )
        actual_addresses = tuple(
            str(ipaddress.ip_interface(cidr).ip) for cidr in interface.addresses
        )
        if actual_addresses != expected_addresses:
            raise UnsupportedEosBgpCppLifecycleRenderingError(
                f"logical interface {interface.resource_id} address coverage mismatch: "
                f"expected={expected_addresses}, actual={actual_addresses}"
            )
        target = ipv4_cidrs if interface.afi is AddressFamily.IPV4 else ipv6_cidrs
        for cidr in interface.addresses:
            if cidr in seen_cidrs:
                raise UnsupportedEosBgpCppLifecycleRenderingError(
                    f"physical operation {physical_id} repeats CIDR {cidr!r}"
                )
            seen_cidrs.add(cidr)
            target.append(cidr)
    return tuple(ipv4_cidrs), tuple(ipv6_cidrs)


def _validate_cidrs(cidrs: tuple[str, ...], *, version: int) -> None:
    if not isinstance(cidrs, tuple):
        raise TypeError("EOS physical CIDRs must be tuples")
    if len(frozenset(cidrs)) != len(cidrs):
        raise ValueError("EOS physical CIDRs must be unique")
    for cidr in cidrs:
        parsed = ipaddress.ip_interface(cidr)
        if parsed.version != version or str(parsed) != cidr:
            raise ValueError(
                f"EOS physical CIDR {cidr!r} must be canonical IPv{version}"
            )


TUnsupportedRenderingError = t.TypeVar(
    "TUnsupportedRenderingError",
    bound=ValueError,
)


def _required_eos_dut_endpoint(
    plan: DutPlan,
    *,
    subject: str,
    error_type: type[TUnsupportedRenderingError],
) -> tuple[EndpointPlan, str]:
    endpoints = tuple(endpoint for endpoint in plan.endpoints if endpoint.is_dut)
    if len(endpoints) != 1:
        raise error_type(
            f"EOS/BGP++ {subject} rendering requires exactly one DUT endpoint; "
            f"found {len(endpoints)}"
        )
    endpoint = endpoints[0]
    if endpoint.backend != "eos":
        raise error_type(
            f"DUT endpoint {endpoint.resource_id} has unsupported backend "
            f"{endpoint.backend!r}"
        )
    physical_identifier = endpoint.physical_identifier
    if not physical_identifier:
        raise error_type(
            f"DUT endpoint {endpoint.resource_id} has no physical identifier"
        )
    return endpoint, physical_identifier


__all__ = (
    "EosBgpCppEndpointBaseRenderer",
    "EosBgpCppHostOsRenderer",
    "EosBgpCppLifecycleRenderer",
    "EosPhysicalLifecycleAction",
    "EosPhysicalLifecycleCleanupIntent",
    "EosPhysicalLifecycleTaskIntent",
    "EosRoutingConfigLifecycleAction",
    "EosRoutingConfigLifecycleCleanupIntent",
    "EosRoutingConfigLifecycleTaskIntent",
    "EosRoutingComponentLifecycleAction",
    "EosRoutingComponentLifecycleCleanupIntent",
    "EosRoutingComponentLifecycleTaskIntent",
    "EosRoutingDaemonIntent",
    "EosRoutingStartupOptionIntent",
    "UnsupportedEosBgpCppEndpointBaseRenderingError",
    "UnsupportedEosBgpCppHostOsRenderingError",
    "UnsupportedEosBgpCppLifecycleRenderingError",
)
