# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

import ipaddress
import typing as t
from dataclasses import dataclass

from taac.abstractions.compilation.legacy_ixia_identity import (
    LegacyIxiaAdvertisementIdentity,
    LegacyIxiaGroupIdentity,
    LegacyIxiaIdentitySidecar,
    LegacyIxiaSessionIdentity,
)
from taac.abstractions.compilation.model import (
    AddressFamily,
    IxiaAdvertisementPlan,
    IxiaAsPathPlan,
    IxiaAttributeValue,
    IxiaBgpSessionPlan,
    IxiaDeviceGroupPlan,
    IxiaExtendedCommunityPlan,
    IxiaNextHopDistribution,
    IxiaNextHopMode,
    IxiaNextHopPlan,
    IxiaPeerPrefixDistribution,
    IxiaPlan,
    IxiaPortPlan,
    IxiaPrefixWindowPlan,
    IxiaRouteAttributeDistribution,
    IxiaRouteAttributePoolPlan,
    IxiaRouteScaleMode,
    IxiaSelfNextHopRealization,
    IxiaStandardCommunityPlan,
    ResourceId,
)
from taac.abstractions.compilation.resource_ids import (
    adjacency_resource_id,
    endpoint_resource_id,
    is_dut_endpoint,
    ixia_advertisement_resource_id,
    ixia_device_group_resource_id,
    ixia_port_resource_id,
    ixia_session_resource_id,
    link_resource_id,
)
from taac.abstractions.ixia_semantics import (
    IxiaBgpCapability,
    IxiaEndpointPortLabelStyle,
)
from taac.abstractions.routing_semantics import PeerRelationship
from taac.abstractions.topology.attributes import (
    RouteAttributePool,
)
from taac.abstractions.topology.model import (
    BgpPeerGroup,
    BgpPolicy,
    BoundDeviceGroup,
    BoundIxiaDeviceGroupChild,
    BoundTopology,
    EndpointSpec,
    IxiaBgpSessionIntent,
    ResolvedPeer,
    ResolvedPrefixAdvertisementLike,
)
from taac.abstractions.topology.prefix import NextHopIntent


@dataclass(frozen=True)
class IxiaPlanningResult:
    plan: IxiaPlan
    legacy_identity: LegacyIxiaIdentitySidecar

    def __post_init__(self) -> None:
        self.legacy_identity.validate(self.plan.iter_resource_ids())


@dataclass
class _IxiaPortAccumulator:
    resource_id: ResourceId
    logical_role: str
    dut_endpoint_id: ResourceId
    traffic_endpoint_id: ResourceId
    dut_physical_identifier: str
    chassis_identifier: str
    dut_interface: str
    ixia_port: str
    physical_inventory_index: int
    reuse_group: str | None
    endpoint_label_style: IxiaEndpointPortLabelStyle
    link_ids: list[ResourceId]

    def add(
        self,
        device_group: BoundDeviceGroup,
        endpoints: _IxiaEndpoints,
    ) -> None:
        assignment = device_group.port_assignment
        if assignment is None:
            raise ValueError("IXIA port accumulation requires a bound assignment")
        if assignment.endpoint_label_style is not self.endpoint_label_style:
            raise ValueError(
                f"IXIA port {self.resource_id} has conflicting endpoint label styles"
            )
        actual = (
            endpoint_resource_id(endpoints.dut.name),
            endpoint_resource_id(endpoints.traffic.name),
            endpoints.dut_physical_identifier,
            endpoints.chassis_identifier,
            assignment.dut_interface,
            assignment.ixia_port,
            assignment.physical_inventory_index,
            assignment.reuse_group,
        )
        expected = (
            self.dut_endpoint_id,
            self.traffic_endpoint_id,
            self.dut_physical_identifier,
            self.chassis_identifier,
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
            dut_endpoint_id=self.dut_endpoint_id,
            traffic_endpoint_id=self.traffic_endpoint_id,
            dut_physical_identifier=self.dut_physical_identifier,
            chassis_identifier=self.chassis_identifier,
            dut_interface=self.dut_interface,
            ixia_port=self.ixia_port,
            physical_inventory_index=self.physical_inventory_index,
            reuse_group=self.reuse_group,
            endpoint_label_style=self.endpoint_label_style,
        )


@dataclass(frozen=True)
class _IxiaEndpoints:
    dut: EndpointSpec
    traffic: EndpointSpec
    dut_is_a: bool
    dut_physical_identifier: str
    chassis_identifier: str


@dataclass(frozen=True)
class _IxiaInstance:
    child_name: str | None
    peer_start_index: int
    peers: tuple[ResolvedPeer, ...]
    advertisements: tuple[ResolvedPrefixAdvertisementLike, ...]
    device_group_name: str | None
    bgp_peer_name: str | None
    tag_name: str | None
    device_group_index: int | None
    prefix_name: str | None


def plan_ixia(
    bound: BoundTopology,
    endpoint_specs: dict[str, EndpointSpec],
) -> IxiaPlanningResult:
    resolved_device_groups = tuple(
        (device_group, _ixia_endpoints(bound, device_group, endpoint_specs))
        for device_group in bound.device_groups
        if device_group.port_assignment is not None
    )
    ports = _ixia_port_plans(resolved_device_groups)
    device_groups: list[IxiaDeviceGroupPlan] = []
    sessions: list[IxiaBgpSessionPlan] = []
    advertisements: list[IxiaAdvertisementPlan] = []
    group_identities: list[LegacyIxiaGroupIdentity] = []
    session_identities: list[LegacyIxiaSessionIdentity] = []
    advertisement_identities: list[LegacyIxiaAdvertisementIdentity] = []

    for device_group, endpoints in resolved_device_groups:
        assignment = device_group.port_assignment
        if assignment is None:
            raise ValueError("resolved IXIA device group has no port assignment")
        relationship = device_group.peer_relationship
        if relationship is None:
            raise ValueError(
                f"IXIA device group {device_group.name!r} has no peer relationship"
            )
        bgp_behavior = _bgp_behavior(device_group)
        for instance in _ixia_instances(device_group):
            device_group_id = ixia_device_group_resource_id(
                device_group.name,
                instance.child_name,
            )
            session_id = ixia_session_resource_id(
                device_group.name,
                instance.child_name,
            )
            device_groups.append(
                IxiaDeviceGroupPlan(
                    resource_id=device_group_id,
                    link_id=link_resource_id(device_group.name),
                    port_id=ixia_port_resource_id(assignment.logical_role),
                    afi=AddressFamily(device_group.afi),
                    peer_count=len(instance.peers),
                    local_asn=device_group.remote_asn,
                    remote_asn=device_group.local_asn,
                    parent_network=device_group.parent_network,
                    peer_start_index=instance.peer_start_index,
                )
            )
            sessions.append(
                IxiaBgpSessionPlan(
                    resource_id=session_id,
                    device_group_id=device_group_id,
                    adjacency_ids=tuple(
                        adjacency_resource_id(
                            device_group.name,
                            instance.peer_start_index + ordinal,
                        )
                        for ordinal in range(len(instance.peers))
                    ),
                    local_addresses=tuple(
                        peer.z_ip if endpoints.dut_is_a else peer.a_ip
                        for peer in instance.peers
                    ),
                    peer_addresses=tuple(
                        peer.a_ip if endpoints.dut_is_a else peer.z_ip
                        for peer in instance.peers
                    ),
                    peer_cidrs=tuple(peer.peer_cidr for peer in instance.peers),
                    relationship=relationship,
                    capabilities=bgp_behavior.capabilities,
                    address_prefix_length=bgp_behavior.address_prefix_length,
                    address_step=bgp_behavior.address_step,
                    address_start_index=bgp_behavior.address_start_index,
                    enable_four_byte_local_as=True,
                    hold_timer_s=bgp_behavior.hold_timer_s,
                    keepalive_timer_s=bgp_behavior.keepalive_timer_s,
                    enable_graceful_restart=bgp_behavior.enable_graceful_restart,
                )
            )
            _append_identity(
                group_identities,
                session_identities,
                device_group_id,
                session_id,
                instance,
            )
            for advertisement in instance.advertisements:
                advertisement_id = ixia_advertisement_resource_id(
                    device_group.name,
                    advertisement.spec.name,
                    instance.child_name,
                )
                advertisements.append(
                    _advertisement_plan(
                        advertisement_id,
                        device_group_id,
                        device_group,
                        instance,
                        advertisement,
                    )
                )
                prefix_name = (
                    instance.prefix_name or advertisement.spec.legacy_ixia_name
                )
                if prefix_name:
                    advertisement_identities.append(
                        LegacyIxiaAdvertisementIdentity(
                            resource_id=advertisement_id,
                            prefix_name=prefix_name,
                        )
                    )

    plan = IxiaPlan(
        ports=ports,
        device_groups=tuple(device_groups),
        bgp_sessions=tuple(sessions),
        advertisements=tuple(advertisements),
    )
    return IxiaPlanningResult(
        plan=plan,
        legacy_identity=LegacyIxiaIdentitySidecar(
            group_identities=tuple(group_identities),
            session_identities=tuple(session_identities),
            advertisement_identities=tuple(advertisement_identities),
        ),
    )


def _ixia_port_plans(
    resolved_device_groups: t.Sequence[tuple[BoundDeviceGroup, _IxiaEndpoints]],
) -> tuple[IxiaPortPlan, ...]:
    accumulators: dict[str, _IxiaPortAccumulator] = {}
    for device_group, endpoints in resolved_device_groups:
        assignment = device_group.port_assignment
        if assignment is None:
            raise ValueError("resolved IXIA device group has no port assignment")
        accumulator = accumulators.get(assignment.logical_role)
        if accumulator is None:
            accumulator = _IxiaPortAccumulator(
                resource_id=ixia_port_resource_id(assignment.logical_role),
                logical_role=assignment.logical_role,
                dut_endpoint_id=endpoint_resource_id(endpoints.dut.name),
                traffic_endpoint_id=endpoint_resource_id(endpoints.traffic.name),
                dut_physical_identifier=endpoints.dut_physical_identifier,
                chassis_identifier=endpoints.chassis_identifier,
                dut_interface=assignment.dut_interface,
                ixia_port=assignment.ixia_port,
                physical_inventory_index=assignment.physical_inventory_index,
                reuse_group=assignment.reuse_group,
                endpoint_label_style=assignment.endpoint_label_style,
                link_ids=[],
            )
            accumulators[assignment.logical_role] = accumulator
        accumulator.add(device_group, endpoints)
    return tuple(accumulator.freeze() for accumulator in accumulators.values())


@dataclass(frozen=True)
class _BgpBehavior:
    capabilities: tuple[IxiaBgpCapability, ...]
    address_prefix_length: int
    address_step: int
    address_start_index: int
    hold_timer_s: int
    keepalive_timer_s: int
    enable_graceful_restart: bool


def _bgp_behavior(device_group: BoundDeviceGroup) -> _BgpBehavior:
    peer_group = device_group.peer_group
    intent = (
        peer_group.ixia_session
        if isinstance(peer_group, BgpPeerGroup)
        else IxiaBgpSessionIntent()
    )
    configured_graceful_restart = (
        peer_group.enable_graceful_restart
        if isinstance(peer_group, BgpPeerGroup)
        else None
    )
    return _BgpBehavior(
        capabilities=(intent.capabilities or _default_bgp_capabilities(device_group)),
        address_prefix_length=(
            intent.address_prefix_length
            if intent.address_prefix_length is not None
            else _default_address_prefix_length(device_group)
        ),
        address_step=(
            intent.address_step
            if intent.address_step is not None
            else _ip_step(device_group.spec.address_plan.stride, device_group.afi)
        ),
        address_start_index=(
            intent.address_start_index
            if intent.address_start_index is not None
            else (
                device_group.partition.start_index
                if device_group.partition is not None
                else 0
            )
        ),
        hold_timer_s=intent.hold_timer_s,
        keepalive_timer_s=intent.keepalive_timer_s,
        enable_graceful_restart=(
            intent.enable_graceful_restart
            if intent.enable_graceful_restart is not None
            else (
                configured_graceful_restart
                if configured_graceful_restart is not None
                else True
            )
        ),
    )


def _default_bgp_capabilities(
    device_group: BoundDeviceGroup,
) -> tuple[IxiaBgpCapability, ...]:
    if device_group.peer_relationship is PeerRelationship.MONITOR:
        return (
            IxiaBgpCapability.IPV6_UNICAST,
            IxiaBgpCapability.IPV4_UNICAST,
            IxiaBgpCapability.IPV4_UNICAST_ADD_PATH,
            IxiaBgpCapability.IPV6_UNICAST_ADD_PATH,
            IxiaBgpCapability.NEXT_HOP_ENCODING,
        )
    return (
        IxiaBgpCapability.IPV4_UNICAST
        if device_group.afi == "v4"
        else IxiaBgpCapability.IPV6_UNICAST,
    )


def _default_address_prefix_length(device_group: BoundDeviceGroup) -> int:
    if device_group.afi == "v6":
        return 64
    peer_cidr = device_group.peers[0].peer_cidr
    if peer_cidr is None:
        raise ValueError(
            f"IPv4 IXIA device group {device_group.name!r} has no peer CIDR"
        )
    return int(peer_cidr.rsplit("/", 1)[1])


def _advertisement_plan(
    advertisement_id: ResourceId,
    device_group_id: ResourceId,
    device_group: BoundDeviceGroup,
    instance: _IxiaInstance,
    advertisement: ResolvedPrefixAdvertisementLike,
) -> IxiaAdvertisementPlan:
    spec = advertisement.spec
    source = advertisement.prefix_set.spec.source
    allocation = spec.allocation
    policy = spec.policy
    prefixes = advertisement.prefix_set.prefixes
    membership_start_index = spec.membership.start_index
    if not 0 <= membership_start_index < len(prefixes):
        raise ValueError(
            f"IXIA advertisement {spec.name!r} membership start index "
            f"{membership_start_index} is outside its {len(prefixes)} "
            "materialized prefixes"
        )
    return IxiaAdvertisementPlan(
        resource_id=advertisement_id,
        device_group_id=device_group_id,
        logical_name=spec.name,
        prefix_set_name=spec.prefix_set,
        afi=AddressFamily(device_group.afi),
        route_count=allocation.distinct_prefix_count(len(instance.peers)),
        prefix_window=IxiaPrefixWindowPlan(
            source_start=source.start_prefix,
            source_step=_ip_step(source.prefix_step, device_group.afi),
            source_count=source.count,
            source_excluded_indices=source.excluded_indices,
            membership_start_index=spec.membership.start_index,
            membership_prefix_count=spec.membership.prefix_count,
            starting_prefix=prefixes[membership_start_index],
            prefix_length=source.prefix_length,
            prefixes_per_peer=allocation.prefixes_per_peer,
            peer_distribution=IxiaPeerPrefixDistribution(
                allocation.peer_distribution.value
            ),
            network_group_index=allocation.network_group_index,
            route_scale_mode=IxiaRouteScaleMode(allocation.route_scale_mode.value),
        ),
        next_hop=_next_hop_plan(spec.next_hop, device_group.afi),
        attributes=_scalar_attributes(spec.attributes),
        route_attributes=_route_attribute_plan(spec.route_attributes),
        policy_communities=(
            tuple(policy.communities) if isinstance(policy, BgpPolicy) else ()
        ),
        requires_route_mutation=spec.requires_route_mutation,
    )


def _next_hop_plan(intent: NextHopIntent, afi: str) -> IxiaNextHopPlan:
    mode = IxiaNextHopMode(intent.mode.value)
    if mode is not IxiaNextHopMode.SELF and intent.self_realization is not None:
        raise ValueError("non-self IXIA next hop cannot carry a self realization")
    distribution = (
        IxiaNextHopDistribution(intent.distribution.value)
        if intent.distribution is not None
        else None
    )
    if mode is IxiaNextHopMode.FORMULAIC:
        formula = intent.formulaic_source
        if formula is None:
            raise ValueError("formulaic IXIA next-hop intent has no source")
        return IxiaNextHopPlan(
            mode=mode,
            distribution=distribution,
            formulaic_start=formula.start,
            formulaic_step=_ip_step(formula.step, afi),
        )
    if mode is IxiaNextHopMode.EXPLICIT:
        explicit = intent.explicit_source
        if explicit is None:
            raise ValueError("explicit IXIA next-hop intent has no source")
        return IxiaNextHopPlan(
            mode=mode,
            distribution=distribution,
            explicit_addresses=explicit.addresses,
        )
    return IxiaNextHopPlan(
        mode=mode,
        self_realization=(
            IxiaSelfNextHopRealization(intent.self_realization.value)
            if intent.self_realization is not None
            else None
        ),
    )


def _route_attribute_plan(
    pool: RouteAttributePool | None,
) -> IxiaRouteAttributePoolPlan | None:
    if pool is None:
        return None
    return IxiaRouteAttributePoolPlan(
        community_rows=tuple(
            tuple(
                IxiaStandardCommunityPlan(asn=community.asn, value=community.value)
                for community in row
            )
            for row in pool.community_rows
        ),
        extended_community_rows=tuple(
            tuple(
                IxiaExtendedCommunityPlan(
                    kind=community.kind.value,
                    administrator=community.administrator,
                    assigned_number=community.assigned_number,
                )
                for community in row
            )
            for row in pool.extended_community_rows
        ),
        as_paths=tuple(IxiaAsPathPlan(asns=path.asns) for path in pool.as_paths),
        distribution=IxiaRouteAttributeDistribution(pool.distribution.value),
    )


def _scalar_attributes(
    attributes: tuple[tuple[str, object], ...],
) -> tuple[tuple[str, IxiaAttributeValue], ...]:
    normalized: list[tuple[str, IxiaAttributeValue]] = []
    for name, value in attributes:
        if type(value) not in (str, int, float, bool, type(None)):
            raise ValueError(
                f"IXIA advertisement attribute {name!r} has unsupported "
                f"value type {type(value).__name__}"
            )
        normalized.append((name, t.cast(IxiaAttributeValue, value)))
    return tuple(normalized)


def _append_identity(
    group_identities: list[LegacyIxiaGroupIdentity],
    session_identities: list[LegacyIxiaSessionIdentity],
    device_group_id: ResourceId,
    session_id: ResourceId,
    instance: _IxiaInstance,
) -> None:
    if (
        instance.device_group_name is not None
        or instance.tag_name is not None
        or instance.device_group_index is not None
    ):
        group_identities.append(
            LegacyIxiaGroupIdentity(
                resource_id=device_group_id,
                device_group_name=instance.device_group_name,
                tag_name=instance.tag_name,
                device_group_index=instance.device_group_index,
            )
        )
    if instance.bgp_peer_name is not None:
        session_identities.append(
            LegacyIxiaSessionIdentity(
                resource_id=session_id,
                bgp_peer_name=instance.bgp_peer_name,
            )
        )


def _ixia_instances(device_group: BoundDeviceGroup) -> tuple[_IxiaInstance, ...]:
    if device_group.ixia_children:
        return tuple(
            _ixia_child_instance(child) for child in device_group.ixia_children
        )
    raw_tag_name = device_group.legacy_ixia_tag_name
    device_group_name = device_group.legacy_ixia_device_group_name
    return (
        _IxiaInstance(
            child_name=None,
            peer_start_index=0,
            peers=device_group.peers,
            advertisements=device_group.prefix_advertisements,
            device_group_name=device_group_name,
            bgp_peer_name=(device_group.legacy_ixia_bgp_peer_name or raw_tag_name),
            tag_name=raw_tag_name if device_group_name is None else None,
            device_group_index=device_group.legacy_ixia_device_group_index,
            prefix_name=None,
        ),
    )


def _ixia_child_instance(child: BoundIxiaDeviceGroupChild) -> _IxiaInstance:
    return _IxiaInstance(
        child_name=child.name,
        peer_start_index=child.spec.start_index,
        peers=child.peers,
        advertisements=child.prefix_advertisements,
        device_group_name=child.spec.legacy_ixia_device_group_name,
        bgp_peer_name=child.spec.legacy_ixia_bgp_peer_name,
        tag_name=None,
        device_group_index=child.spec.legacy_ixia_device_group_index,
        prefix_name=child.spec.legacy_ixia_prefix_pool_name,
    )


def _ixia_endpoints(
    bound: BoundTopology,
    device_group: BoundDeviceGroup,
    endpoint_specs: dict[str, EndpointSpec],
) -> _IxiaEndpoints:
    a_endpoint = endpoint_specs[device_group.spec.a_endpoint]
    z_endpoint = endpoint_specs[device_group.spec.z_endpoint]
    if is_dut_endpoint(a_endpoint) and not is_dut_endpoint(z_endpoint):
        dut, traffic, dut_is_a = a_endpoint, z_endpoint, True
    elif is_dut_endpoint(z_endpoint) and not is_dut_endpoint(a_endpoint):
        dut, traffic, dut_is_a = z_endpoint, a_endpoint, False
    else:
        raise ValueError(
            f"device group {device_group.name!r} does not identify one DUT and "
            "one traffic endpoint"
        )
    dut_identifier = _physical_identifier(bound, dut)
    chassis_identifier = _physical_identifier(bound, traffic)
    if not dut_identifier or not chassis_identifier:
        raise ValueError(
            f"device group {device_group.name!r} has unresolved DUT or IXIA identity"
        )
    return _IxiaEndpoints(
        dut=dut,
        traffic=traffic,
        dut_is_a=dut_is_a,
        dut_physical_identifier=dut_identifier,
        chassis_identifier=chassis_identifier,
    )


def _physical_identifier(bound: BoundTopology, endpoint: EndpointSpec) -> str | None:
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


def _ip_step(value: int | str, afi: str) -> int:
    if isinstance(value, int):
        return value
    parsed = ipaddress.ip_address(value)
    if parsed.version != (4 if afi == "v4" else 6):
        raise ValueError(f"step {value!r} does not match afi={afi!r}")
    return int(parsed)


__all__ = (
    "IxiaPlanningResult",
    "plan_ixia",
)
