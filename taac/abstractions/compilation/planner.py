# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

from dataclasses import dataclass, field

from taac.abstractions.compilation.eb_policy_presets import (
    resolve_eb_policy_preset,
)
from taac.abstractions.compilation.ixia_planner import plan_ixia
from taac.abstractions.compilation.legacy_ixia_identity import (
    LegacyIxiaIdentitySidecar,
)
from taac.abstractions.compilation.model import (
    AddressFamily,
    BgpAdjacencyPlan,
    ComponentPlan,
    DesiredPresence,
    DutLinkPlan,
    DutPlan,
    EndpointPlan,
    EndpointSetupMode,
    InterfacePlan,
    OpenRDesiredMode,
    OpenRPlan,
    PhysicalInterfacePlan,
    PolicyBinding,
    PolicyDirection,
    PolicyPlan,
    ResourceId,
    RolePolicyKey,
    RoutingConfigPlan,
    TopologyCompilationPlan,
)
from taac.abstractions.compilation.report import (
    CompileReport,
    ResourceDisposition,
    ResourceReport,
)
from taac.abstractions.compilation.resource_ids import (
    adjacency_resource_id,
    component_resource_id,
    endpoint_resource_id,
    interface_resource_id,
    is_dut_endpoint,
    link_resource_id,
    openr_resource_id,
    physical_interface_resource_id,
    policy_binding_resource_id,
    policy_resource_id,
    role_policy_resource_id,
    routing_config_resource_id,
)
from taac.abstractions.component_semantics import (
    ComponentDesiredState,
    ComponentReadinessRequirement,
    ComponentReconcileMode,
    ComponentRole,
)
from taac.abstractions.physical_interface_semantics import (
    PhysicalInterfaceGroupKind,
    PhysicalInterfaceProfile,
)
from taac.abstractions.topology.model import (
    BoundDeviceGroup,
    BoundRoutingConfig,
    BoundTopology,
    EndpointSpec,
    resolve_endpoint_routing_drivers,
    ResolvedIxiaPortAssignment,
    RoutingDeviceConfig,
)


@dataclass(frozen=True)
class PlanningResult:
    plan: TopologyCompilationPlan
    report: CompileReport
    legacy_ixia_identity: LegacyIxiaIdentitySidecar = field(
        default_factory=LegacyIxiaIdentitySidecar
    )

    def __post_init__(self) -> None:
        self.report.validate(self.plan.iter_resource_ids())
        self.legacy_ixia_identity.validate(self.plan.ixia.iter_resource_ids())


class UnsupportedTrafficFlowIntentError(ValueError):
    pass


@dataclass
class _InterfaceAccumulator:
    resource_id: ResourceId
    endpoint_id: ResourceId
    logical_port_role: str
    afi: AddressFamily
    bound_interface: str | None
    physical_interface_id: ResourceId | None
    link_ids: list[ResourceId]
    addresses: list[str]

    def add(
        self,
        link_id: ResourceId,
        bound_interface: str | None,
        physical_interface_id: ResourceId | None,
        addresses: tuple[str, ...],
    ) -> None:
        if (
            self.bound_interface is not None
            and bound_interface is not None
            and self.bound_interface != bound_interface
        ):
            raise ValueError(
                f"logical interface {self.resource_id} resolves to multiple "
                "physical interfaces"
            )
        if self.bound_interface is None:
            self.bound_interface = bound_interface
        if self.physical_interface_id != physical_interface_id:
            raise ValueError(
                f"logical interface {self.resource_id} resolves to multiple "
                "physical interface owners"
            )
        if link_id not in self.link_ids:
            self.link_ids.append(link_id)
        for address in addresses:
            if address not in self.addresses:
                self.addresses.append(address)

    def freeze(self) -> InterfacePlan:
        return InterfacePlan(
            resource_id=self.resource_id,
            endpoint_id=self.endpoint_id,
            link_ids=tuple(self.link_ids),
            logical_port_role=self.logical_port_role,
            afi=self.afi,
            addresses=tuple(self.addresses),
            bound_interface=self.bound_interface,
            physical_interface_id=self.physical_interface_id,
        )


@dataclass
class _PhysicalInterfaceAccumulator:
    resource_id: ResourceId
    endpoint_id: ResourceId
    group_kind: PhysicalInterfaceGroupKind
    logical_key: str
    bound_interface: str
    profile: PhysicalInterfaceProfile
    link_ids: list[ResourceId]

    def add(
        self,
        bound_interface: str,
        profile: PhysicalInterfaceProfile,
        link_id: ResourceId,
    ) -> None:
        if (bound_interface, profile) != (self.bound_interface, self.profile):
            raise ValueError(
                f"physical interface {self.resource_id} has conflicting bindings "
                "or profiles"
            )
        if link_id not in self.link_ids:
            self.link_ids.append(link_id)

    def freeze(self) -> PhysicalInterfacePlan:
        return PhysicalInterfacePlan(
            resource_id=self.resource_id,
            endpoint_id=self.endpoint_id,
            group_kind=self.group_kind,
            logical_key=self.logical_key,
            link_ids=tuple(self.link_ids),
            bound_interface=self.bound_interface,
            profile=self.profile,
        )


class BoundTopologyPlanner:
    """Builds common semantic plans without invoking a compiler or renderer."""

    def plan(self, bound: BoundTopology) -> PlanningResult:
        if bound.logical_topology.traffic_flows:
            raise UnsupportedTrafficFlowIntentError(
                "traffic-flow compilation is outside the Phase 1.5 IXIA lane"
            )
        endpoint_specs = {
            endpoint.name: endpoint for endpoint in bound.logical_topology.endpoints
        }
        endpoints = _endpoint_plans(bound)
        links = _link_plans(bound)
        interfaces = _interface_plans(bound, endpoint_specs)
        physical_interfaces = _physical_interface_plans(bound, endpoint_specs)
        adjacencies = _adjacency_plans(bound, endpoint_specs)
        declared_policies = tuple(
            PolicyPlan(
                resource_id=policy_resource_id(policy.name),
                logical_name=policy.name,
            )
            for policy in bound.logical_topology.policies
        )
        role_policies, policy_bindings = _role_policy_plans(
            bound,
            endpoint_specs,
        )
        routing_configs = _routing_config_plans(bound, endpoint_specs)
        components = _component_plans(routing_configs)
        openr = _openr_plans(bound, endpoint_specs)
        ixia = plan_ixia(bound, endpoint_specs)

        plan = TopologyCompilationPlan(
            dut=DutPlan(
                endpoints=endpoints,
                links=links,
                physical_interfaces=physical_interfaces,
                interfaces=interfaces,
                adjacencies=adjacencies,
                policies=(*declared_policies, *role_policies),
                policy_bindings=policy_bindings,
                routing_configs=routing_configs,
                components=components,
                openr=openr,
            ),
            ixia=ixia.plan,
        )
        return PlanningResult(
            plan=plan,
            report=_compile_report(plan),
            legacy_ixia_identity=ixia.legacy_identity,
        )


def _endpoint_plans(bound: BoundTopology) -> tuple[EndpointPlan, ...]:
    return tuple(
        EndpointPlan(
            resource_id=endpoint_resource_id(endpoint.name),
            logical_name=endpoint.name,
            role=endpoint.role,
            kind=endpoint.kind,
            backend=bound.endpoint_os.get(
                endpoint.name,
                endpoint.required_os or "unknown",
            ),
            is_dut=is_dut_endpoint(endpoint),
            physical_identifier=_physical_identifier(bound, endpoint),
            setup_mode=EndpointSetupMode(endpoint.setup_mode),
            network_role=bound.endpoint_network_roles.get(endpoint.name),
        )
        for endpoint in bound.logical_topology.endpoints
    )


def _link_plans(bound: BoundTopology) -> tuple[DutLinkPlan, ...]:
    return tuple(
        DutLinkPlan(
            resource_id=link_resource_id(device_group.name),
            a_endpoint_id=endpoint_resource_id(device_group.spec.a_endpoint),
            z_endpoint_id=endpoint_resource_id(device_group.spec.z_endpoint),
            afi=_address_family(device_group.afi),
            logical_port_role=_logical_port_role(device_group),
            peer_count=device_group.peer_count,
            parent_network=device_group.parent_network,
        )
        for device_group in bound.device_groups
    )


def _interface_plans(
    bound: BoundTopology,
    endpoint_specs: dict[str, EndpointSpec],
) -> tuple[InterfacePlan, ...]:
    accumulators: dict[
        tuple[str, str, AddressFamily],
        _InterfaceAccumulator,
    ] = {}
    for device_group in bound.device_groups:
        endpoint_name, bound_interface, addresses, _ = _dut_side(
            device_group,
            endpoint_specs,
        )
        afi = _address_family(device_group.afi)
        logical_port_role = _logical_port_role(device_group)
        physical_interface_id = _physical_interface_id(
            endpoint_name,
            device_group.port_assignment,
        )
        key = (endpoint_name, logical_port_role, afi)
        accumulator = accumulators.get(key)
        if accumulator is None:
            accumulator = _InterfaceAccumulator(
                resource_id=interface_resource_id(
                    endpoint_name,
                    logical_port_role,
                    afi,
                ),
                endpoint_id=endpoint_resource_id(endpoint_name),
                logical_port_role=logical_port_role,
                afi=afi,
                bound_interface=bound_interface,
                physical_interface_id=physical_interface_id,
                link_ids=[],
                addresses=[],
            )
            accumulators[key] = accumulator
        accumulator.add(
            link_resource_id(device_group.name),
            bound_interface,
            physical_interface_id,
            addresses,
        )
    return tuple(accumulator.freeze() for accumulator in accumulators.values())


def _physical_interface_plans(
    bound: BoundTopology,
    endpoint_specs: dict[str, EndpointSpec],
) -> tuple[PhysicalInterfacePlan, ...]:
    accumulators: dict[ResourceId, _PhysicalInterfaceAccumulator] = {}
    connection_owners: dict[tuple[ResourceId, str], ResourceId] = {}
    for device_group in bound.device_groups:
        _add_physical_interface(
            accumulators,
            connection_owners,
            device_group,
            endpoint_specs,
        )
    return tuple(accumulator.freeze() for accumulator in accumulators.values())


def _add_physical_interface(
    accumulators: dict[ResourceId, _PhysicalInterfaceAccumulator],
    connection_owners: dict[tuple[ResourceId, str], ResourceId],
    device_group: BoundDeviceGroup,
    endpoint_specs: dict[str, EndpointSpec],
) -> None:
    assignment = device_group.port_assignment
    if assignment is None:
        return
    endpoint_name, bound_interface, _, _ = _dut_side(
        device_group,
        endpoint_specs,
    )
    if bound_interface is None:
        raise ValueError(
            f"device group {device_group.name!r} has no bound DUT interface"
        )
    endpoint_id = endpoint_resource_id(endpoint_name)
    group_kind, logical_key = _physical_interface_group(assignment)
    resource_id = physical_interface_resource_id(
        endpoint_id,
        group_kind,
        logical_key,
    )
    _claim_physical_connection(
        connection_owners,
        endpoint_id,
        bound_interface,
        resource_id,
    )
    accumulator = accumulators.get(resource_id)
    if accumulator is None:
        accumulator = _PhysicalInterfaceAccumulator(
            resource_id=resource_id,
            endpoint_id=endpoint_id,
            group_kind=group_kind,
            logical_key=logical_key,
            bound_interface=bound_interface,
            profile=assignment.physical_interface_profile,
            link_ids=[],
        )
        accumulators[resource_id] = accumulator
    accumulator.add(
        bound_interface,
        assignment.physical_interface_profile,
        link_resource_id(device_group.name),
    )


def _claim_physical_connection(
    owners: dict[tuple[ResourceId, str], ResourceId],
    endpoint_id: ResourceId,
    bound_interface: str,
    resource_id: ResourceId,
) -> None:
    connection = (endpoint_id, bound_interface)
    prior_owner = owners.get(connection)
    if prior_owner is not None and prior_owner != resource_id:
        raise ValueError(
            f"physical connection {connection!r} resolves to multiple logical "
            "interface groups"
        )
    owners[connection] = resource_id


def _physical_interface_id(
    endpoint_name: str,
    assignment: ResolvedIxiaPortAssignment | None,
) -> ResourceId | None:
    if assignment is None:
        return None
    group_kind, logical_key = _physical_interface_group(assignment)
    return physical_interface_resource_id(
        endpoint_resource_id(endpoint_name),
        group_kind,
        logical_key,
    )


def _physical_interface_group(
    assignment: ResolvedIxiaPortAssignment,
) -> tuple[PhysicalInterfaceGroupKind, str]:
    if assignment.reuse_group is not None:
        return PhysicalInterfaceGroupKind.REUSE_GROUP, assignment.reuse_group
    return PhysicalInterfaceGroupKind.LOGICAL_ROLE, assignment.logical_role


def _adjacency_plans(
    bound: BoundTopology,
    endpoint_specs: dict[str, EndpointSpec],
) -> tuple[BgpAdjacencyPlan, ...]:
    adjacencies: list[BgpAdjacencyPlan] = []
    for device_group in bound.device_groups:
        _, _, _, dut_is_a = _dut_side(device_group, endpoint_specs)
        for ordinal, peer in enumerate(device_group.peers):
            adjacencies.append(
                BgpAdjacencyPlan(
                    resource_id=adjacency_resource_id(
                        device_group.name,
                        ordinal,
                    ),
                    link_id=link_resource_id(device_group.name),
                    ordinal=ordinal,
                    afi=_address_family(device_group.afi),
                    local_address=peer.a_ip if dut_is_a else peer.z_ip,
                    peer_address=peer.z_ip if dut_is_a else peer.a_ip,
                    local_asn=device_group.local_asn,
                    remote_asn=device_group.remote_asn,
                    desired_presence=(
                        DesiredPresence.ABSENT
                        if device_group.dut_neighbor_absent
                        else DesiredPresence.PRESENT
                    ),
                    relationship=device_group.peer_relationship,
                )
            )
    return tuple(adjacencies)


def _role_policy_plans(
    bound: BoundTopology,
    endpoint_specs: dict[str, EndpointSpec],
) -> tuple[tuple[PolicyPlan, ...], tuple[PolicyBinding, ...]]:
    policies_by_key: dict[RolePolicyKey, PolicyPlan] = {}
    bindings: list[PolicyBinding] = []
    for device_group in bound.device_groups:
        endpoint_name, _, _, _ = _dut_side(device_group, endpoint_specs)
        local_role = bound.endpoint_network_roles.get(endpoint_name)
        if local_role is None or device_group.dut_neighbor_absent:
            continue
        relationship = device_group.peer_relationship
        if relationship is None:
            raise ValueError(
                f"device group {device_group.name!r} has no peer relationship"
            )
        afi = _address_family(device_group.afi)
        for ordinal in range(device_group.peer_count):
            adjacency_id = adjacency_resource_id(device_group.name, ordinal)
            for direction in PolicyDirection:
                key = RolePolicyKey(
                    local_role=local_role,
                    relationship=relationship,
                    afi=afi,
                    direction=direction,
                )
                preset = resolve_eb_policy_preset(key)
                policy_id = role_policy_resource_id(key)
                if key not in policies_by_key:
                    policies_by_key[key] = PolicyPlan(
                        resource_id=policy_id,
                        logical_name=preset.semantic_id,
                        preset=preset,
                    )
                bindings.append(
                    PolicyBinding(
                        resource_id=policy_binding_resource_id(
                            adjacency_id,
                            direction,
                        ),
                        adjacency_id=adjacency_id,
                        policy_id=policy_id,
                        direction=direction,
                    )
                )
    return tuple(policies_by_key.values()), tuple(bindings)


def _routing_config_plans(
    bound: BoundTopology,
    endpoint_specs: dict[str, EndpointSpec],
) -> tuple[RoutingConfigPlan, ...]:
    _validate_bound_routing_configs(bound, endpoint_specs)
    config = bound.device_config or bound.logical_topology.device_config
    plans: list[RoutingConfigPlan] = []
    for endpoint in bound.logical_topology.endpoints:
        if not is_dut_endpoint(endpoint):
            continue
        drivers = resolve_endpoint_routing_drivers(
            endpoint.name,
            bound.device_groups,
            bound.routing_drivers,
        )
        if not drivers:
            if endpoint.name in bound.routing_configs:
                raise ValueError(
                    f"DUT endpoint {endpoint.name!r} has a bound routing config "
                    "but no routing driver"
                )
            continue
        if len(drivers) != 1:
            raise ValueError(
                f"DUT endpoint {endpoint.name!r} resolves to multiple routing "
                f"drivers: {drivers!r}"
            )
        bound_config = bound.routing_configs.get(endpoint.name)
        if bound_config is None:
            raise ValueError(
                f"DUT endpoint {endpoint.name!r} has no bound routing config"
            )
        if bound_config.routing_driver != drivers[0]:
            raise ValueError(
                f"DUT endpoint {endpoint.name!r} bound routing config driver "
                f"{bound_config.routing_driver!r} does not match {drivers[0]!r}"
            )
        plans.append(
            RoutingConfigPlan(
                resource_id=routing_config_resource_id(endpoint.name),
                endpoint_id=endpoint_resource_id(endpoint.name),
                routing_driver=drivers[0],
                source=bound_config.source,
                required_features=_required_routing_features(config),
            )
        )
    return tuple(plans)


def _validate_bound_routing_configs(
    bound: BoundTopology,
    endpoint_specs: dict[str, EndpointSpec],
) -> None:
    if any(not isinstance(name, str) for name in bound.routing_configs):
        raise TypeError("bound routing config endpoint names must be strings")
    dut_endpoint_names = {
        name for name, endpoint in endpoint_specs.items() if is_dut_endpoint(endpoint)
    }
    unknown_endpoint_names = tuple(
        sorted(set(bound.routing_configs) - dut_endpoint_names)
    )
    if unknown_endpoint_names:
        raise ValueError(
            "bound routing configs target unknown or non-DUT endpoints: "
            f"{unknown_endpoint_names!r}"
        )
    for endpoint_name, routing_config in bound.routing_configs.items():
        if not isinstance(routing_config, BoundRoutingConfig):
            raise TypeError(f"bound routing config for {endpoint_name!r} must be typed")


def _openr_plans(
    bound: BoundTopology,
    endpoint_specs: dict[str, EndpointSpec],
) -> tuple[OpenRPlan, ...]:
    del endpoint_specs
    config = bound.device_config or bound.logical_topology.device_config
    mode = OpenRDesiredMode(config.openr_mode.value)
    return tuple(
        OpenRPlan(
            resource_id=openr_resource_id(endpoint.name),
            endpoint_id=endpoint_resource_id(endpoint.name),
            mode=mode,
        )
        for endpoint in bound.logical_topology.endpoints
        if is_dut_endpoint(endpoint)
    )


def _component_plans(
    routing_configs: tuple[RoutingConfigPlan, ...],
) -> tuple[ComponentPlan, ...]:
    role = ComponentRole.ROUTING_CONTROL_PLANE
    return tuple(
        ComponentPlan(
            resource_id=component_resource_id(routing_config.endpoint_id, role),
            endpoint_id=routing_config.endpoint_id,
            role=role,
            desired_state=ComponentDesiredState.RUNNING,
            reconcile_mode=ComponentReconcileMode.RESTART_AFTER_CONFIGURATION,
            readiness=ComponentReadinessRequirement.ACKNOWLEDGED,
            depends_on=(routing_config.resource_id,),
        )
        for routing_config in routing_configs
    )


def _compile_report(plan: TopologyCompilationPlan) -> CompileReport:
    resource_reports = tuple(
        _resource_report(resource.resource_id, resource)
        for resource in plan.iter_resources()
    )
    report = CompileReport(resource_reports=resource_reports)
    report.validate(plan.iter_resource_ids())
    return report


def _resource_report(resource_id: ResourceId, resource: object) -> ResourceReport:
    if isinstance(resource, OpenRPlan) and resource.mode is OpenRDesiredMode.NONE:
        return ResourceReport(
            resource_id=resource_id,
            required=False,
            disposition=ResourceDisposition.SKIPPED,
            reason="logical topology explicitly disables OpenR",
        )
    return ResourceReport(
        resource_id=resource_id,
        required=True,
        disposition=ResourceDisposition.EMITTED,
    )


def _physical_identifier(
    bound: BoundTopology,
    endpoint: EndpointSpec,
) -> str | None:
    resolved = bound.resolved_endpoints.get(endpoint.name, {})
    identifier_field = resolved.get("physical_identifier_field")
    if not isinstance(identifier_field, str):
        return None
    resolved_value = resolved.get(identifier_field)
    if isinstance(resolved_value, str):
        return resolved_value
    inventory = bound.physical_inventory
    if inventory is None:
        return None
    inventory_value = getattr(inventory, identifier_field, None)
    return inventory_value if isinstance(inventory_value, str) else None


def _dut_side(
    device_group: BoundDeviceGroup,
    endpoint_specs: dict[str, EndpointSpec],
) -> tuple[str, str | None, tuple[str, ...], bool]:
    a_endpoint = endpoint_specs[device_group.spec.a_endpoint]
    z_endpoint = endpoint_specs[device_group.spec.z_endpoint]
    if device_group.a_interface is not None:
        return (
            a_endpoint.name,
            device_group.a_interface,
            device_group.a_ips,
            True,
        )
    if device_group.z_interface is not None:
        return (
            z_endpoint.name,
            device_group.z_interface,
            device_group.z_ips,
            False,
        )
    if is_dut_endpoint(a_endpoint) and not is_dut_endpoint(z_endpoint):
        return a_endpoint.name, None, device_group.a_ips, True
    if is_dut_endpoint(z_endpoint) and not is_dut_endpoint(a_endpoint):
        return z_endpoint.name, None, device_group.z_ips, False
    raise ValueError(
        f"device group {device_group.name!r} does not identify one DUT endpoint"
    )


def _logical_port_role(device_group: BoundDeviceGroup) -> str:
    assignment = device_group.port_assignment
    return assignment.logical_role if assignment is not None else device_group.role


def _required_routing_features(config: RoutingDeviceConfig) -> tuple[str, ...]:
    features: list[str] = []
    for feature, enabled in (
        ("update_group_enable", config.update_group_enable),
        ("enable_next_hop_tracking", config.enable_next_hop_tracking),
        (
            "enable_dynamic_policy_evaluation",
            config.enable_dynamic_policy_evaluation,
        ),
    ):
        if enabled:
            features.append(feature)
    for feature, value in (
        ("route_limit", config.route_limit),
        ("prefix_limit", config.prefix_limit),
        ("per_peer_max_route_limit", config.per_peer_max_route_limit),
        ("graceful_restart_timer_s", config.graceful_restart_timer_s),
    ):
        if value is not None:
            features.append(feature)
    return tuple(features)


def _address_family(afi: str) -> AddressFamily:
    return AddressFamily(afi)
