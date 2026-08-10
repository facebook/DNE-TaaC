# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

from dataclasses import dataclass

from taac.abstractions.compilation.model import (
    AddressFamily,
    BgpAdjacencyPlan,
    DesiredPresence,
    DutLinkPlan,
    DutPlan,
    EndpointPlan,
    EndpointSetupMode,
    InterfacePlan,
    IxiaAdvertisementPlan,
    IxiaBgpSessionPlan,
    IxiaDeviceGroupPlan,
    IxiaPlan,
    IxiaPortPlan,
    OpenRDesiredMode,
    OpenRPlan,
    PolicyPlan,
    ResourceId,
    ResourceKind,
    RoutingConfigPlan,
    TopologyCompilationPlan,
)
from taac.abstractions.compilation.report import (
    CompileReport,
    ResourceDisposition,
    ResourceReport,
)
from taac.abstractions.topology.model import (
    BgpPeerGroup,
    BoundDeviceGroup,
    BoundIxiaDeviceGroupChild,
    BoundTopology,
    EndpointSpec,
    ResolvedPeer,
    ResolvedPrefixAdvertisementLike,
    RoutingDeviceConfig,
)


_TRAFFIC_ENDPOINT_ROLES = frozenset({"ixia", "traffic", "trafficgen"})


def endpoint_resource_id(logical_name: str) -> ResourceId:
    return ResourceId(ResourceKind.ENDPOINT, (logical_name,))


def link_resource_id(device_group_name: str) -> ResourceId:
    return ResourceId(ResourceKind.LINK, (device_group_name,))


def interface_resource_id(
    endpoint_name: str,
    logical_port_role: str,
    afi: AddressFamily,
) -> ResourceId:
    return ResourceId(
        ResourceKind.INTERFACE,
        (endpoint_name, logical_port_role, afi.value),
    )


def adjacency_resource_id(device_group_name: str, ordinal: int) -> ResourceId:
    return ResourceId(
        ResourceKind.BGP_ADJACENCY,
        (device_group_name, str(ordinal)),
    )


def policy_resource_id(logical_name: str) -> ResourceId:
    return ResourceId(ResourceKind.POLICY, (logical_name,))


def routing_config_resource_id(endpoint_name: str) -> ResourceId:
    return ResourceId(ResourceKind.ROUTING_CONFIG, (endpoint_name,))


def openr_resource_id(endpoint_name: str) -> ResourceId:
    return ResourceId(ResourceKind.OPENR, (endpoint_name,))


def ixia_port_resource_id(logical_role: str) -> ResourceId:
    return ResourceId(ResourceKind.IXIA_PORT, (logical_role,))


def ixia_device_group_resource_id(
    device_group_name: str,
    child_name: str | None = None,
) -> ResourceId:
    return ResourceId(
        ResourceKind.IXIA_DEVICE_GROUP,
        _ixia_instance_path(device_group_name, child_name),
    )


def ixia_session_resource_id(
    device_group_name: str,
    child_name: str | None = None,
) -> ResourceId:
    return ResourceId(
        ResourceKind.IXIA_BGP_SESSION,
        _ixia_instance_path(device_group_name, child_name),
    )


def ixia_advertisement_resource_id(
    device_group_name: str,
    logical_name: str,
    child_name: str | None = None,
) -> ResourceId:
    return ResourceId(
        ResourceKind.IXIA_ADVERTISEMENT,
        (*_ixia_instance_path(device_group_name, child_name), logical_name),
    )


@dataclass(frozen=True)
class PlanningResult:
    plan: TopologyCompilationPlan
    report: CompileReport

    def __post_init__(self) -> None:
        self.report.validate(self.plan.iter_resource_ids())


@dataclass
class _InterfaceAccumulator:
    resource_id: ResourceId
    endpoint_id: ResourceId
    logical_port_role: str
    afi: AddressFamily
    bound_interface: str | None
    link_ids: list[ResourceId]
    addresses: list[str]

    def add(
        self,
        link_id: ResourceId,
        bound_interface: str | None,
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
        )


@dataclass
class _IxiaPortAccumulator:
    resource_id: ResourceId
    logical_role: str
    dut_interface: str
    ixia_port: str
    physical_inventory_index: int
    reuse_group: str | None
    link_ids: list[ResourceId]

    def add(self, device_group: BoundDeviceGroup) -> None:
        assignment = device_group.port_assignment
        if assignment is None:
            raise ValueError("IXIA port accumulation requires a bound assignment")
        actual = (
            assignment.dut_interface,
            assignment.ixia_port,
            assignment.physical_inventory_index,
            assignment.reuse_group,
        )
        expected = (
            self.dut_interface,
            self.ixia_port,
            self.physical_inventory_index,
            self.reuse_group,
        )
        if actual != expected:
            raise ValueError(
                f"logical IXIA port {self.resource_id} resolves to multiple "
                "physical connections"
            )
        link_id = link_resource_id(device_group.name)
        if link_id not in self.link_ids:
            self.link_ids.append(link_id)

    def freeze(self) -> IxiaPortPlan:
        return IxiaPortPlan(
            resource_id=self.resource_id,
            logical_role=self.logical_role,
            link_ids=tuple(self.link_ids),
            dut_interface=self.dut_interface,
            ixia_port=self.ixia_port,
            physical_inventory_index=self.physical_inventory_index,
            reuse_group=self.reuse_group,
        )


@dataclass(frozen=True)
class _IxiaInstance:
    child_name: str | None
    peer_start_index: int
    peers: tuple[ResolvedPeer, ...]
    advertisements: tuple[ResolvedPrefixAdvertisementLike, ...]


class BoundTopologyPlanner:
    """Builds common semantic plans without invoking a compiler or renderer."""

    def plan(self, bound: BoundTopology) -> PlanningResult:
        endpoint_specs = {
            endpoint.name: endpoint for endpoint in bound.logical_topology.endpoints
        }
        endpoints = _endpoint_plans(bound)
        links = _link_plans(bound)
        interfaces = _interface_plans(bound, endpoint_specs)
        adjacencies = _adjacency_plans(bound, endpoint_specs)
        policies = tuple(
            PolicyPlan(
                resource_id=policy_resource_id(policy.name),
                logical_name=policy.name,
            )
            for policy in bound.logical_topology.policies
        )
        routing_configs = _routing_config_plans(bound, endpoint_specs)
        openr = _openr_plans(bound, endpoint_specs)
        ports = _ixia_port_plans(bound)
        ixia_device_groups, sessions, advertisements = _ixia_session_plans(
            bound,
            endpoint_specs,
        )

        plan = TopologyCompilationPlan(
            dut=DutPlan(
                endpoints=endpoints,
                links=links,
                interfaces=interfaces,
                adjacencies=adjacencies,
                policies=policies,
                policy_bindings=(),
                routing_configs=routing_configs,
                components=(),
                openr=openr,
            ),
            ixia=IxiaPlan(
                ports=ports,
                device_groups=ixia_device_groups,
                bgp_sessions=sessions,
                advertisements=advertisements,
            ),
        )
        return PlanningResult(plan=plan, report=_compile_report(plan))


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
            physical_identifier=_physical_identifier(bound, endpoint),
            setup_mode=EndpointSetupMode(endpoint.setup_mode),
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
                link_ids=[],
                addresses=[],
            )
            accumulators[key] = accumulator
        accumulator.add(
            link_resource_id(device_group.name),
            bound_interface,
            addresses,
        )
    return tuple(accumulator.freeze() for accumulator in accumulators.values())


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
                    peer_group=_peer_group_name(device_group.peer_group),
                    desired_presence=(
                        DesiredPresence.ABSENT
                        if device_group.dut_neighbor_absent
                        else DesiredPresence.PRESENT
                    ),
                )
            )
    return tuple(adjacencies)


def _routing_config_plans(
    bound: BoundTopology,
    endpoint_specs: dict[str, EndpointSpec],
) -> tuple[RoutingConfigPlan, ...]:
    config = bound.device_config or bound.logical_topology.device_config
    plans: list[RoutingConfigPlan] = []
    for endpoint in bound.logical_topology.endpoints:
        if not _is_dut_endpoint(endpoint):
            continue
        drivers = _endpoint_routing_drivers(bound, endpoint.name)
        if not drivers:
            continue
        if len(drivers) != 1:
            raise ValueError(
                f"DUT endpoint {endpoint.name!r} resolves to multiple routing "
                f"drivers: {drivers!r}"
            )
        plans.append(
            RoutingConfigPlan(
                resource_id=routing_config_resource_id(endpoint.name),
                endpoint_id=endpoint_resource_id(endpoint.name),
                routing_driver=drivers[0],
                required_features=_required_routing_features(config),
            )
        )
    return tuple(plans)


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
        if _is_dut_endpoint(endpoint)
    )


def _ixia_port_plans(bound: BoundTopology) -> tuple[IxiaPortPlan, ...]:
    accumulators: dict[str, _IxiaPortAccumulator] = {}
    for device_group in bound.device_groups:
        assignment = device_group.port_assignment
        if assignment is None:
            continue
        accumulator = accumulators.get(assignment.logical_role)
        if accumulator is None:
            accumulator = _IxiaPortAccumulator(
                resource_id=ixia_port_resource_id(assignment.logical_role),
                logical_role=assignment.logical_role,
                dut_interface=assignment.dut_interface,
                ixia_port=assignment.ixia_port,
                physical_inventory_index=assignment.physical_inventory_index,
                reuse_group=assignment.reuse_group,
                link_ids=[],
            )
            accumulators[assignment.logical_role] = accumulator
        accumulator.add(device_group)
    return tuple(accumulator.freeze() for accumulator in accumulators.values())


def _ixia_session_plans(
    bound: BoundTopology,
    endpoint_specs: dict[str, EndpointSpec],
) -> tuple[
    tuple[IxiaDeviceGroupPlan, ...],
    tuple[IxiaBgpSessionPlan, ...],
    tuple[IxiaAdvertisementPlan, ...],
]:
    device_groups: list[IxiaDeviceGroupPlan] = []
    sessions: list[IxiaBgpSessionPlan] = []
    advertisements: list[IxiaAdvertisementPlan] = []
    for device_group in bound.device_groups:
        assignment = device_group.port_assignment
        if assignment is None:
            continue
        _, _, _, dut_is_a = _dut_side(device_group, endpoint_specs)
        for instance in _ixia_instances(device_group):
            device_group_id = ixia_device_group_resource_id(
                device_group.name,
                instance.child_name,
            )
            device_groups.append(
                IxiaDeviceGroupPlan(
                    resource_id=device_group_id,
                    link_id=link_resource_id(device_group.name),
                    port_id=ixia_port_resource_id(assignment.logical_role),
                    afi=_address_family(device_group.afi),
                    peer_count=len(instance.peers),
                    local_asn=device_group.remote_asn,
                    remote_asn=device_group.local_asn,
                    parent_network=device_group.parent_network,
                )
            )
            sessions.append(
                IxiaBgpSessionPlan(
                    resource_id=ixia_session_resource_id(
                        device_group.name,
                        instance.child_name,
                    ),
                    device_group_id=device_group_id,
                    adjacency_ids=tuple(
                        adjacency_resource_id(
                            device_group.name,
                            instance.peer_start_index + ordinal,
                        )
                        for ordinal in range(len(instance.peers))
                    ),
                    local_addresses=tuple(
                        peer.z_ip if dut_is_a else peer.a_ip for peer in instance.peers
                    ),
                    peer_addresses=tuple(
                        peer.a_ip if dut_is_a else peer.z_ip for peer in instance.peers
                    ),
                    peer_group=_peer_group_name(device_group.peer_group),
                )
            )
            for advertisement in instance.advertisements:
                allocation = advertisement.spec.allocation
                advertisements.append(
                    IxiaAdvertisementPlan(
                        resource_id=ixia_advertisement_resource_id(
                            device_group.name,
                            advertisement.spec.name,
                            instance.child_name,
                        ),
                        device_group_id=device_group_id,
                        logical_name=advertisement.spec.name,
                        prefix_set_name=advertisement.spec.prefix_set,
                        afi=_address_family(device_group.afi),
                        route_count=allocation.distinct_prefix_count(
                            len(instance.peers)
                        ),
                        prefixes_per_peer=allocation.prefixes_per_peer,
                        prefix_length=(
                            advertisement.prefix_set.spec.source.prefix_length
                        ),
                    )
                )
    return tuple(device_groups), tuple(sessions), tuple(advertisements)


def _ixia_instances(device_group: BoundDeviceGroup) -> tuple[_IxiaInstance, ...]:
    if not device_group.ixia_children:
        return (
            _IxiaInstance(
                child_name=None,
                peer_start_index=0,
                peers=device_group.peers,
                advertisements=device_group.prefix_advertisements,
            ),
        )
    return tuple(_ixia_child_instance(child) for child in device_group.ixia_children)


def _ixia_child_instance(child: BoundIxiaDeviceGroupChild) -> _IxiaInstance:
    return _IxiaInstance(
        child_name=child.name,
        peer_start_index=child.spec.start_index,
        peers=child.peers,
        advertisements=child.prefix_advertisements,
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
    if _is_dut_endpoint(a_endpoint) and not _is_dut_endpoint(z_endpoint):
        return a_endpoint.name, None, device_group.a_ips, True
    if _is_dut_endpoint(z_endpoint) and not _is_dut_endpoint(a_endpoint):
        return z_endpoint.name, None, device_group.z_ips, False
    raise ValueError(
        f"device group {device_group.name!r} does not identify one DUT endpoint"
    )


def _logical_port_role(device_group: BoundDeviceGroup) -> str:
    assignment = device_group.port_assignment
    return assignment.logical_role if assignment is not None else device_group.role


def _endpoint_routing_drivers(
    bound: BoundTopology,
    endpoint_name: str,
) -> tuple[str, ...]:
    drivers: list[str] = []
    for device_group in bound.device_groups:
        if endpoint_name not in {
            device_group.spec.a_endpoint,
            device_group.spec.z_endpoint,
        }:
            continue
        driver = device_group.routing_driver or bound.routing_drivers.get(
            device_group.name
        )
        if driver is not None and driver not in drivers:
            drivers.append(driver)
    return tuple(drivers)


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


def _peer_group_name(peer_group: BgpPeerGroup | str | None) -> str | None:
    return peer_group.name if isinstance(peer_group, BgpPeerGroup) else peer_group


def _address_family(afi: str) -> AddressFamily:
    return AddressFamily(afi)


def _is_dut_endpoint(endpoint: EndpointSpec) -> bool:
    return endpoint.role == "dut" or (
        endpoint.kind == "dut" and endpoint.role not in _TRAFFIC_ENDPOINT_ROLES
    )


def _ixia_instance_path(
    device_group_name: str,
    child_name: str | None,
) -> tuple[str, ...]:
    return (
        (device_group_name,) if child_name is None else (device_group_name, child_name)
    )
