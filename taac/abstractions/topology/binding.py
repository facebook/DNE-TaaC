# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe

from __future__ import annotations

import ipaddress
import typing as t
from dataclasses import dataclass, fields, replace

from taac.abstractions.config_artifact_semantics import (
    ConfigArtifactRef,
)
from taac.abstractions.physical_interface_semantics import (
    PhysicalInterfaceProfile,
)
from taac.abstractions.routing_semantics import (
    NetworkRole,
    PeerRelationship,
)
from taac.abstractions.topology.address import AddressPlan
from taac.abstractions.topology.model import (
    BgpPeerGroup,
    BoundDeviceGroup,
    BoundIxiaDeviceGroupChild,
    BoundRoutingConfig,
    BoundTopology,
    DeviceGroupPartition,
    DeviceGroupSpec,
    EndpointSpec,
    IxiaDeviceGroupChild,
    LogicalTopology,
    OpenRMode,
    PrefixAdvertisement,
    resolve_endpoint_routing_drivers,
    ResolvedDeviceGroupProvenance,
    ResolvedIxiaPortAssignment,
    ResolvedPeer,
    RouteSender,
    RoutingDeviceConfig,
)
from taac.abstractions.topology.prefix import (
    NextHopDistribution,
    NextHopMode,
    PeerPrefixDistribution,
)
from taac.abstractions.topology.routes import (
    FormulaicAddressSequence,
    FormulaicPrefixSequence,
    ResolvedPrefixAdvertisement,
    ResolvedPrefixSet,
    ResolvedRoutePathSequence,
)
from taac.abstractions.validation import (
    collect_routing_device_config_issues,
    IXIA_MAX_4BYTE_ASN,
    TopologyValidationError,
    ValidationIssue,
)

_TRAFFIC_ENDPOINT_KINDS = frozenset({"ixia", "traffic", "trafficgen"})
_TRAFFIC_ENDPOINT_ROLES = frozenset({"ixia", "traffic", "trafficgen"})
_IXIA_4BYTE_ASN_MAX = IXIA_MAX_4BYTE_ASN
_EOS_SECONDARY_IP_LIMIT_PER_INTERFACE_AFI = 500
_LEGACY_PEER_RELATIONSHIPS = {
    "uplink": PeerRelationship.EXTERNAL,
    "ebgp": PeerRelationship.EXTERNAL,
    "ebgp_ug_ctrl": PeerRelationship.EXTERNAL,
    "ebgp_ug_held": PeerRelationship.EXTERNAL,
    "ebgp_ug_disp": PeerRelationship.EXTERNAL,
    "ebgp_ug_spare": PeerRelationship.EXTERNAL,
    "ebgp_fast": PeerRelationship.EXTERNAL,
    "ebgp_slow": PeerRelationship.EXTERNAL,
    "ibgp": PeerRelationship.INTERNAL,
    "ibgp_dc_p1": PeerRelationship.INTERNAL,
    "ibgp_dc_p2": PeerRelationship.INTERNAL,
    "ibgp_dc_p3": PeerRelationship.INTERNAL,
    "ibgp_dc_p4": PeerRelationship.INTERNAL,
    "ibgp_mp_p1": PeerRelationship.INTERNAL,
    "ibgp_mp_p2": PeerRelationship.INTERNAL,
    "ibgp_mp_p3": PeerRelationship.INTERNAL,
    "ibgp_mp_p4": PeerRelationship.INTERNAL,
    "ibgp_ug_keep_initial": PeerRelationship.INTERNAL,
    "ibgp_ug_keep_mutated": PeerRelationship.INTERNAL,
    "ibgp_ug_var1": PeerRelationship.INTERNAL,
    "ibgp_ug_var2": PeerRelationship.INTERNAL,
    "bgpmon": PeerRelationship.MONITOR,
}
_DEVICE_CONFIG_OVERRIDDEN_FIELDS_ATTR = "_taac_overridden_fields"
_DEVICE_CONFIG_FIELDS = tuple(
    config_field
    for config_field in fields(RoutingDeviceConfig)
    if not config_field.name.startswith("_")
)
_COMPACT_IXIA_PROFILES = frozenset(
    {"ebb_full_scale", "ipv6_update_packing", "ug_new_peer_join"}
)
_COMPACT_IXIA_PREFIX_LENGTHS = {"v4": 31, "v6": 127}
_IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
_IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


@dataclass
class _BindingContext:
    physical_inventory: t.Any
    port_map: t.Mapping[str, int]
    parent_networks: t.Mapping[str, str]
    peer_groups: t.Mapping[str, BgpPeerGroup | str]
    as_numbers: t.Mapping[str, int]
    endpoint_by_name: t.Mapping[str, EndpointSpec]
    endpoint_os: t.Mapping[str, str]
    bound_ips: dict[str, tuple[str, str]]
    peer_cidrs: list[tuple[_IPNetwork, str, str]]
    issues: list[ValidationIssue]


@dataclass(frozen=True)
class _BoundTopologyMappings:
    resolved_endpoints: t.Mapping[str, t.Mapping[str, t.Any]]
    resolved_device_groups: t.Mapping[str, t.Mapping[str, t.Any]]
    endpoint_network_roles: t.Mapping[str, NetworkRole]
    routing_drivers: t.Mapping[str, str]
    ixia_ports: t.Mapping[str, str]
    interfaces: t.Mapping[str, str]
    as_numbers: t.Mapping[str, int]
    peer_groups_by_device_group: t.Mapping[str, BgpPeerGroup | str]
    legacy_names: t.Mapping[str, str]


@dataclass(frozen=True)
class _ResolvedDeviceGroupPorts:
    a_endpoint: EndpointSpec
    z_endpoint: EndpointSpec
    dut_interface: str | None
    ixia_port: str | None
    port_assignment: ResolvedIxiaPortAssignment | None


@dataclass(frozen=True)
class _ResolvedDeviceGroupAddresses:
    parent_network: str | None
    parent_network_source: str | None
    a_ips: tuple[str, ...]
    z_ips: tuple[str, ...]
    peers: tuple[ResolvedPeer, ...]


@dataclass(frozen=True)
class _ResolvedDeviceGroupBgp:
    peer_group: BgpPeerGroup | str | None
    local_asn: int | None
    local_asn_source: str | None
    remote_asn: int | None
    remote_asn_source: str | None


def bind_logical_topology_to_inventory(
    *,
    logical_topology: LogicalTopology,
    physical_inventory: t.Any,
    port_map: t.Mapping[str, int],
    parent_networks: t.Mapping[str, str] | None = None,
    peer_groups: t.Mapping[str, BgpPeerGroup | str] | None = None,
    as_numbers: t.Mapping[str, int] | None = None,
    device_config_override: RoutingDeviceConfig | None = None,
) -> BoundTopology:
    logical_topology.validate()

    context = _build_binding_context(
        logical_topology=logical_topology,
        physical_inventory=physical_inventory,
        port_map=port_map,
        parent_networks=parent_networks or {},
        peer_groups=peer_groups or {},
        as_numbers=as_numbers or {},
    )
    bound_dgs = _bind_device_groups(logical_topology.device_groups, context)
    _validate_resolved_port_graph(bound_dgs, context.issues)
    resolved_prefix_sets = _resolve_prefix_sets(logical_topology)
    bound_dgs = _bind_prefix_advertisements(
        bound_dgs,
        resolved_prefix_sets,
        context.issues,
    )
    bound_dgs = _bind_ixia_children(bound_dgs)
    _validate_resolved_partitions(bound_dgs, context.issues)
    _validate_legacy_device_group_indices(bound_dgs, context.issues)
    resolved_route_senders = _resolve_route_senders(logical_topology.route_senders)
    _validate_eos_secondary_ip_limits(bound_dgs, context.issues)
    device_config = _merge_device_config(
        logical_topology.device_config,
        device_config_override,
    )
    context.issues.extend(collect_routing_device_config_issues(device_config))
    _validate_openr_standalone_inputs(
        device_config,
        physical_inventory,
        context.issues,
    )

    if context.issues:
        raise TopologyValidationError(logical_topology.name, context.issues)

    return _build_bound_topology(
        logical_topology=logical_topology,
        context=context,
        bound_dgs=bound_dgs,
        resolved_prefix_sets=resolved_prefix_sets,
        device_config=device_config,
        resolved_route_senders=resolved_route_senders,
    )


def _build_binding_context(
    *,
    logical_topology: LogicalTopology,
    physical_inventory: t.Any,
    port_map: t.Mapping[str, int],
    parent_networks: t.Mapping[str, str],
    peer_groups: t.Mapping[str, BgpPeerGroup | str],
    as_numbers: t.Mapping[str, int],
) -> _BindingContext:
    issues: list[ValidationIssue] = []

    _validate_physical_inventory(logical_topology, physical_inventory, issues)
    endpoint_by_name = {
        endpoint.name: endpoint for endpoint in logical_topology.endpoints
    }
    endpoint_os = {
        endpoint.name: _resolve_endpoint_os(endpoint, physical_inventory, issues)
        for endpoint in logical_topology.endpoints
    }
    return _BindingContext(
        physical_inventory=physical_inventory,
        port_map=port_map,
        parent_networks=parent_networks,
        peer_groups=peer_groups,
        as_numbers=as_numbers,
        endpoint_by_name=endpoint_by_name,
        endpoint_os=endpoint_os,
        bound_ips={},
        peer_cidrs=[],
        issues=issues,
    )


def _bind_device_groups(
    device_groups: t.Sequence[DeviceGroupSpec],
    context: _BindingContext,
) -> list[BoundDeviceGroup]:
    return [
        _bind_device_group(dg=dg, index=index, context=context)
        for index, dg in enumerate(device_groups)
    ]


def _resolve_prefix_sets(
    logical_topology: LogicalTopology,
) -> dict[str, ResolvedPrefixSet]:
    return {
        prefix_set.name: ResolvedPrefixSet(
            spec=prefix_set,
            prefixes=FormulaicPrefixSequence(prefix_set.source),
        )
        for prefix_set in logical_topology.prefix_sets
    }


def _bind_prefix_advertisements(
    bound_dgs: t.Sequence[BoundDeviceGroup],
    prefix_sets: t.Mapping[str, ResolvedPrefixSet],
    issues: list[ValidationIssue],
) -> list[BoundDeviceGroup]:
    result = []
    for dg_index, bound_dg in enumerate(bound_dgs):
        resolved = []
        for advertisement_index, advertisement in enumerate(
            bound_dg.spec.prefix_advertisements
        ):
            path = (
                f"device_groups[{dg_index}]."
                f"prefix_advertisements[{advertisement_index}]"
            )
            try:
                resolved.append(
                    _resolve_prefix_advertisement(
                        bound_dg,
                        advertisement,
                        prefix_sets,
                    )
                )
            except KeyError:
                issues.append(
                    ValidationIssue(
                        path=f"{path}.prefix_set",
                        code="unknown_prefix_set",
                        message=(
                            f"prefix advertisement references unknown prefix set "
                            f"{advertisement.prefix_set!r}"
                        ),
                    )
                )
            except ValueError as error:
                issues.append(
                    ValidationIssue(
                        path=path,
                        code="invalid_prefix_advertisement_resolution",
                        message=str(error),
                    )
                )
        result.append(
            replace(
                bound_dg,
                prefix_advertisements=tuple(resolved),
            )
        )
    return result


def _bind_ixia_children(
    bound_dgs: t.Sequence[BoundDeviceGroup],
) -> list[BoundDeviceGroup]:
    return [
        replace(
            bound_dg,
            ixia_children=tuple(
                _bind_ixia_child(bound_dg, child)
                for child in bound_dg.spec.ixia_children
            ),
        )
        for bound_dg in bound_dgs
    ]


def _bind_ixia_child(
    parent: BoundDeviceGroup,
    child: IxiaDeviceGroupChild,
) -> BoundIxiaDeviceGroupChild:
    start = child.start_index
    end = start + child.peer_count
    return BoundIxiaDeviceGroupChild(
        spec=child,
        peers=parent.peers[start:end],
        prefix_advertisements=_slice_ixia_child_advertisements(
            t.cast(
                t.Sequence[ResolvedPrefixAdvertisement],
                parent.prefix_advertisements,
            ),
            child,
        ),
    )


def _slice_ixia_child_advertisements(
    advertisements: t.Sequence[ResolvedPrefixAdvertisement],
    child: IxiaDeviceGroupChild,
) -> tuple[ResolvedPrefixAdvertisement, ...]:
    start = child.start_index
    end = start + child.peer_count
    return tuple(
        replace(
            advertisement,
            spec=(
                advertisement.spec
                if child.legacy_ixia_prefix_pool_name is None
                else replace(
                    advertisement.spec,
                    legacy_ixia_name=child.legacy_ixia_prefix_pool_name,
                )
            ),
            paths_by_peer=advertisement.paths_by_peer[start:end],
        )
        for advertisement in advertisements
    )


def _resolve_prefix_advertisement(
    bound_dg: BoundDeviceGroup,
    advertisement: PrefixAdvertisement,
    prefix_sets: t.Mapping[str, ResolvedPrefixSet],
) -> ResolvedPrefixAdvertisement:
    prefix_set = prefix_sets[advertisement.prefix_set]
    effective_advertisement = (
        advertisement
        if advertisement.route_attributes is not None
        or bound_dg.spec.route_attributes is None
        else replace(
            advertisement,
            route_attributes=bound_dg.spec.route_attributes,
        )
    )
    next_hops = _resolve_advertisement_next_hops(bound_dg, advertisement)
    return ResolvedPrefixAdvertisement(
        spec=effective_advertisement,
        prefix_set=prefix_set,
        paths_by_peer=tuple(
            ResolvedRoutePathSequence(
                advertisement=effective_advertisement,
                prefix_set=prefix_set,
                peer_index=peer_index,
                self_next_hop=next_hop,
                next_hops=next_hops,
            )
            for peer_index, next_hop in enumerate(bound_dg.z_ips)
        ),
    )


def _resolve_advertisement_next_hops(
    bound_dg: BoundDeviceGroup,
    advertisement: t.Any,
) -> t.Sequence[str] | None:
    intent = advertisement.next_hop
    if intent.mode == NextHopMode.SELF:
        return None
    count = _next_hop_count(
        intent.distribution,
        bound_dg.peer_count,
        advertisement.allocation.prefixes_per_peer,
        advertisement.membership.prefix_count,
    )
    if intent.mode == NextHopMode.FORMULAIC:
        source = intent.formulaic_source
        if source is None:
            raise ValueError(
                f"advertisement {advertisement.name!r} uses formulaic next hops "
                "without a formulaic source"
            )
        return FormulaicAddressSequence(source.start, source.step, count)
    if intent.mode == NextHopMode.EXPLICIT:
        source = intent.explicit_source
        if source is None:
            raise ValueError(
                f"advertisement {advertisement.name!r} uses explicit next hops "
                "without an explicit source"
            )
        if len(source.addresses) != count:
            raise ValueError(
                f"advertisement {advertisement.name!r} requires {count} explicit "
                f"next hops for {intent.distribution.value}, got "
                f"{len(source.addresses)}"
            )
        return source.addresses
    raise ValueError(
        f"advertisement {advertisement.name!r} uses unsupported next-hop mode "
        f"{intent.mode!r}"
    )


def _next_hop_count(
    distribution: NextHopDistribution | None,
    peer_count: int,
    prefixes_per_peer: int,
    distinct_prefix_count: int,
) -> int:
    if distribution == NextHopDistribution.SHARED:
        return 1
    if distribution == NextHopDistribution.PER_PEER:
        return peer_count
    if distribution == NextHopDistribution.PER_PREFIX:
        return distinct_prefix_count
    if distribution == NextHopDistribution.PER_PEER_PREFIX:
        return peer_count * prefixes_per_peer
    raise ValueError(f"unsupported next-hop distribution {distribution!r}")


def _build_bound_topology(
    *,
    logical_topology: LogicalTopology,
    context: _BindingContext,
    bound_dgs: t.Sequence[BoundDeviceGroup],
    resolved_prefix_sets: t.Mapping[str, ResolvedPrefixSet],
    device_config: RoutingDeviceConfig,
    resolved_route_senders: t.Sequence[RouteSender],
) -> BoundTopology:
    mappings = _build_bound_topology_mappings(
        logical_topology=logical_topology,
        physical_inventory=context.physical_inventory,
        bound_dgs=bound_dgs,
        endpoint_os=context.endpoint_os,
    )

    return BoundTopology(
        logical_topology=logical_topology,
        physical_inventory=context.physical_inventory,
        device_groups=tuple(bound_dgs),
        device_config=device_config,
        resolved_endpoints=mappings.resolved_endpoints,
        resolved_device_groups=mappings.resolved_device_groups,
        endpoint_os=context.endpoint_os,
        endpoint_network_roles=mappings.endpoint_network_roles,
        routing_configs=_bound_routing_configs(
            logical_topology,
            context.physical_inventory,
            bound_dgs,
            mappings.routing_drivers,
        ),
        routing_drivers=mappings.routing_drivers,
        ixia_ports=mappings.ixia_ports,
        interfaces=mappings.interfaces,
        as_numbers=mappings.as_numbers,
        peer_groups_by_device_group=mappings.peer_groups_by_device_group,
        legacy_names=mappings.legacy_names,
        port_map=dict(context.port_map),
        parent_networks=dict(context.parent_networks),
        resolved_prefix_sets=dict(resolved_prefix_sets),
        resolved_route_senders=tuple(resolved_route_senders),
    )


def _bound_routing_configs(
    logical_topology: LogicalTopology,
    physical_inventory: t.Any,
    bound_dgs: t.Sequence[BoundDeviceGroup],
    routing_drivers: t.Mapping[str, str],
) -> dict[str, BoundRoutingConfig]:
    artifact_by_driver = getattr(
        physical_inventory,
        "routing_config_artifacts",
        {},
    )
    if not isinstance(artifact_by_driver, dict):
        raise TypeError("routing_config_artifacts must be a dict")
    configs = {}
    for endpoint in logical_topology.endpoints:
        if not _endpoint_is_dut(endpoint):
            continue
        drivers = resolve_endpoint_routing_drivers(
            endpoint.name,
            bound_dgs,
            routing_drivers,
        )
        if len(drivers) > 1:
            raise ValueError(
                f"DUT endpoint {endpoint.name!r} resolves to multiple routing drivers: "
                f"{drivers!r}"
            )
        if not drivers:
            continue
        driver = drivers[0]
        source = artifact_by_driver.get(driver)
        if source is not None and not isinstance(source, ConfigArtifactRef):
            raise TypeError(
                f"routing config artifact for {driver!r} must be a ConfigArtifactRef"
            )
        configs[endpoint.name] = BoundRoutingConfig(
            routing_driver=driver,
            source=source,
        )
    return configs


def _resolve_route_senders(
    route_senders: t.Sequence[RouteSender],
) -> tuple[RouteSender, ...]:
    return tuple(route_senders)


def _validate_resolved_port_graph(  # noqa: C901
    bound_dgs: t.Sequence[BoundDeviceGroup],
    issues: list[ValidationIssue],
) -> None:
    connection_owner: dict[tuple[str, str], tuple[int, ResolvedIxiaPortAssignment]] = {}
    interface_owner: dict[str, str] = {}
    ixia_port_owner: dict[str, str] = {}
    reuse_group_connection: dict[str, tuple[str, str]] = {}
    for index, device_group in enumerate(bound_dgs):
        assignment = device_group.port_assignment
        if assignment is None:
            continue
        path = f"device_groups[{index}].port_assignment.reuse_group"
        connection = (assignment.dut_interface, assignment.ixia_port)
        prior_port = interface_owner.get(assignment.dut_interface)
        if prior_port is not None and prior_port != assignment.ixia_port:
            issues.append(
                ValidationIssue(
                    path=(
                        "physical_inventory.ixia_ports"
                        f"[{assignment.physical_inventory_index}]"
                    ),
                    code="ambiguous_physical_port_connection",
                    message="one DUT interface resolves to multiple IXIA ports",
                )
            )
        if prior_port is None:
            interface_owner[assignment.dut_interface] = assignment.ixia_port
        prior_interface = ixia_port_owner.get(assignment.ixia_port)
        if prior_interface is not None and prior_interface != assignment.dut_interface:
            issues.append(
                ValidationIssue(
                    path=(
                        "physical_inventory.ixia_ports"
                        f"[{assignment.physical_inventory_index}]"
                    ),
                    code="ambiguous_physical_port_connection",
                    message="one IXIA port resolves to multiple DUT interfaces",
                )
            )
        if prior_interface is None:
            ixia_port_owner[assignment.ixia_port] = assignment.dut_interface

        reuse_group = assignment.reuse_group
        if reuse_group is not None:
            prior_connection = reuse_group_connection.get(reuse_group)
            if prior_connection is not None and prior_connection != connection:
                issues.append(
                    ValidationIssue(
                        path=path,
                        code="port_reuse_group_connection_mismatch",
                        message=(
                            f"reuse group {reuse_group!r} is already assigned to a "
                            "different physical connection"
                        ),
                    )
                )
            if prior_connection is None:
                reuse_group_connection[reuse_group] = connection

        prior = connection_owner.get(connection)
        if prior is None:
            connection_owner[connection] = (index, assignment)
            continue
        _, prior_assignment = prior
        if prior_assignment.reuse_group is None or reuse_group is None:
            issues.append(
                ValidationIssue(
                    path=path,
                    code="physical_port_reuse_not_allowed",
                    message=(
                        "sharing a physical IXIA connection requires a nonempty "
                        "reuse group on every device group"
                    ),
                )
            )
        elif prior_assignment.reuse_group != reuse_group:
            issues.append(
                ValidationIssue(
                    path=path,
                    code="physical_port_reuse_group_mismatch",
                    message="all device groups sharing a connection need one reuse group",
                )
            )


def _validate_resolved_partitions(
    bound_dgs: t.Sequence[BoundDeviceGroup],
    issues: list[ValidationIssue],
) -> None:
    families: dict[str, list[tuple[int, BoundDeviceGroup, DeviceGroupPartition]]] = {}
    for index, device_group in enumerate(bound_dgs):
        partition = device_group.partition
        if partition is not None:
            families.setdefault(partition.family, []).append(
                (index, device_group, partition)
            )
    for family, members in families.items():
        ordered = sorted(members, key=lambda member: member[2].ordinal)
        reference_index, reference_group, _ = ordered[0]
        geometry_matches = True
        for index, device_group, _ in ordered[1:]:
            mismatch_field = _partition_geometry_mismatch(
                reference_group,
                device_group,
            )
            if mismatch_field is not None:
                geometry_matches = False
                issues.append(
                    ValidationIssue(
                        path=f"device_groups[{index}].{mismatch_field}",
                        code="partition_geometry_mismatch",
                        message=(
                            f"partition family {family!r} geometry differs from "
                            f"device_groups[{reference_index}]"
                        ),
                    )
                )
        if geometry_matches:
            _validate_explicit_partition_address_windows(family, ordered, issues)


def _partition_geometry_mismatch(
    reference: BoundDeviceGroup,
    candidate: BoundDeviceGroup,
) -> str | None:
    comparisons = (
        ("afi", reference.afi, candidate.afi),
        (
            "address_plan.prefix_length",
            reference.spec.address_plan.prefix_length,
            candidate.spec.address_plan.prefix_length,
        ),
        (
            "address_plan.mask",
            reference.spec.address_plan.mask,
            candidate.spec.address_plan.mask,
        ),
        (
            "address_plan.stride",
            _address_plan_step(reference.spec.address_plan),
            _address_plan_step(candidate.spec.address_plan),
        ),
        (
            "address_plan.a_ips",
            bool(reference.spec.address_plan.a_ips),
            bool(candidate.spec.address_plan.a_ips),
        ),
        (
            "address_plan.z_ips",
            bool(reference.spec.address_plan.z_ips),
            bool(candidate.spec.address_plan.z_ips),
        ),
        ("parent_network", reference.parent_network, candidate.parent_network),
        ("peer_group", reference.peer_group, candidate.peer_group),
        ("port_assignment", reference.port_assignment, candidate.port_assignment),
        (
            "prefix_advertisements",
            tuple(
                _advertisement_geometry(ad)
                for ad in reference.spec.prefix_advertisements
            ),
            tuple(
                _advertisement_geometry(ad)
                for ad in candidate.spec.prefix_advertisements
            ),
        ),
    )
    for field_name, reference_value, candidate_value in comparisons:
        if reference_value != candidate_value:
            return field_name
    return None


def _validate_explicit_partition_address_windows(
    family: str,
    ordered: t.Sequence[tuple[int, BoundDeviceGroup, DeviceGroupPartition]],
    issues: list[ValidationIssue],
) -> None:
    _, reference, reference_partition = ordered[0]
    if not reference.spec.address_plan.a_ips:
        return
    if not reference.a_ips or not reference.z_ips:
        return
    step_value, _ = _address_plan_step(reference.spec.address_plan)
    try:
        step = _offset_to_int(step_value, default=2)
        base_a = int(ipaddress.ip_address(reference.a_ips[0])) - (
            reference_partition.start_index * step
        )
        base_z = int(ipaddress.ip_address(reference.z_ips[0])) - (
            reference_partition.start_index * step
        )
    except (TypeError, ValueError) as error:
        issues.append(
            ValidationIssue(
                path=(f"device_groups[{ordered[0][0]}].address_plan.explicit_ips"),
                code="invalid_partition_address",
                message=(
                    f"partition family {family!r} has an invalid explicit "
                    f"address window: {error}"
                ),
            )
        )
        return
    for group_index, device_group, partition in ordered:
        if (
            len(device_group.a_ips) != device_group.peer_count
            or len(device_group.z_ips) != device_group.peer_count
        ):
            continue
        for peer_index in range(device_group.peer_count):
            global_index = partition.start_index + peer_index
            for side, addresses, base in (
                ("a_ips", device_group.a_ips, base_a),
                ("z_ips", device_group.z_ips, base_z),
            ):
                try:
                    actual = int(ipaddress.ip_address(addresses[peer_index]))
                except (TypeError, ValueError) as error:
                    issues.append(
                        ValidationIssue(
                            path=(
                                f"device_groups[{group_index}].address_plan."
                                f"{side}[{peer_index}]"
                            ),
                            code="invalid_partition_address",
                            message=(
                                f"partition family {family!r} has an invalid "
                                f"explicit address: {error}"
                            ),
                        )
                    )
                    continue
                expected = base + global_index * step
                if actual == expected:
                    continue
                issues.append(
                    ValidationIssue(
                        path=(
                            f"device_groups[{group_index}].address_plan."
                            f"{side}[{peer_index}]"
                        ),
                        code=(
                            "partition_address_overlap"
                            if actual < expected
                            else "partition_address_gap"
                        ),
                        message=(
                            f"explicit address window for partition family {family!r} "
                            "must be contiguous and nonoverlapping"
                        ),
                    )
                )


def _advertisement_geometry(advertisement: t.Any) -> tuple[t.Any, ...]:
    shared_membership = (
        (
            advertisement.membership.start_index,
            advertisement.membership.prefix_count,
        )
        if advertisement.allocation.peer_distribution is PeerPrefixDistribution.SHARED
        else None
    )
    return (
        advertisement.prefix_set,
        advertisement.allocation.prefixes_per_peer,
        advertisement.allocation.peer_distribution,
        shared_membership,
    )


def _validate_legacy_device_group_indices(
    bound_dgs: t.Sequence[BoundDeviceGroup],
    issues: list[ValidationIssue],
) -> None:
    indices_by_connection: dict[tuple[str, str], dict[int, str]] = {}
    for group_index, device_group in enumerate(bound_dgs):
        assignment = device_group.port_assignment
        if assignment is None:
            continue
        connection = (assignment.dut_interface, assignment.ixia_port)
        leaves = (
            tuple(
                (
                    child.spec.legacy_ixia_device_group_index,
                    (
                        f"device_groups[{group_index}].ixia_children[{child_index}]"
                        ".legacy_ixia_device_group_index"
                    ),
                )
                for child_index, child in enumerate(device_group.ixia_children)
            )
            if device_group.ixia_children
            else (
                (
                    device_group.legacy_ixia_device_group_index,
                    f"device_groups[{group_index}].legacy_ixia_device_group_index",
                ),
            )
        )
        for legacy_index, path in leaves:
            if legacy_index is None:
                continue
            prior_path = indices_by_connection.setdefault(connection, {}).get(
                legacy_index
            )
            if prior_path is not None:
                issues.append(
                    ValidationIssue(
                        path=path,
                        code="duplicate_ixia_device_group_index",
                        message=(
                            f"legacy IXIA index {legacy_index} is already used by "
                            f"{prior_path} on this connection"
                        ),
                    )
                )
            else:
                indices_by_connection[connection][legacy_index] = path


def _validate_bound_endpoint_resolution(
    bound: BoundTopology,
    endpoint: EndpointSpec,
    issues: list[ValidationIssue],
) -> None:
    if endpoint.name not in bound.endpoint_os:
        issues.append(
            ValidationIssue(
                path=f"endpoint_os.{endpoint.name}",
                code="unresolved_endpoint_os",
                message="bound endpoint has no resolved backend OS",
            )
        )
    resolved_endpoint = bound.resolved_endpoints.get(endpoint.name)
    if resolved_endpoint is None:
        issues.append(
            ValidationIssue(
                path=f"resolved_endpoints.{endpoint.name}",
                code="missing_resolved_endpoint",
                message="bound endpoint has no resolved physical identifier",
            )
        )
        return
    identifier_field = resolved_endpoint.get("physical_identifier_field")
    if identifier_field not in {"device_name", "ixia_chassis_ip"}:
        issues.append(
            ValidationIssue(
                path=(f"resolved_endpoints.{endpoint.name}.physical_identifier_field"),
                code="unresolved_endpoint_physical_identifier",
                message="bound endpoint has no resolved physical identifier field",
            )
        )
    elif not getattr(bound.physical_inventory, identifier_field, None):
        issues.append(
            ValidationIssue(
                path=f"resolved_endpoints.{endpoint.name}.physical_identifier",
                code="unresolved_endpoint_physical_identifier",
                message="bound endpoint has no resolved physical identifier",
            )
        )


def _validate_bound_endpoint_network_role(
    endpoint_name: str,
    network_role: NetworkRole,
    endpoint_by_name: t.Mapping[str, EndpointSpec],
    issues: list[ValidationIssue],
) -> None:
    endpoint = endpoint_by_name.get(endpoint_name)
    if endpoint is None:
        issues.append(
            ValidationIssue(
                path=f"endpoint_network_roles.{endpoint_name}",
                code="unknown_endpoint_network_role",
                message="network role references an unknown logical endpoint",
            )
        )
    elif not _endpoint_is_dut(endpoint):
        issues.append(
            ValidationIssue(
                path=f"endpoint_network_roles.{endpoint_name}",
                code="traffic_endpoint_network_role",
                message="network-device roles may only be assigned to DUT endpoints",
            )
        )
    if not isinstance(network_role, NetworkRole):
        issues.append(
            ValidationIssue(
                path=f"endpoint_network_roles.{endpoint_name}",
                code="invalid_endpoint_network_role",
                message="bound endpoint network role must be a NetworkRole",
            )
        )


def _validate_inventory_network_role(
    bound: BoundTopology,
    issues: list[ValidationIssue],
) -> None:
    inventory_network_role = getattr(bound.physical_inventory, "network_role", None)
    if not isinstance(inventory_network_role, NetworkRole):
        return
    for endpoint in bound.logical_topology.endpoints:
        if (
            _endpoint_is_dut(endpoint)
            and bound.endpoint_network_roles.get(endpoint.name)
            is not inventory_network_role
        ):
            issues.append(
                ValidationIssue(
                    path=f"endpoint_network_roles.{endpoint.name}",
                    code="missing_endpoint_network_role",
                    message="DUT endpoint did not retain the inventory network role",
                )
            )


def _validate_bound_endpoints(
    bound: BoundTopology,
    issues: list[ValidationIssue],
) -> None:
    if not bound.endpoint_os:
        issues.append(
            ValidationIssue(
                path="endpoint_os",
                code="missing_bound_endpoint_os",
                message="bound logical topology has no resolved endpoint backends",
            )
        )
    for endpoint in bound.logical_topology.endpoints:
        _validate_bound_endpoint_resolution(bound, endpoint, issues)
    for endpoint_name, endpoint_os in bound.endpoint_os.items():
        if endpoint_os == "unknown":
            issues.append(
                ValidationIssue(
                    path=f"endpoint_os.{endpoint_name}",
                    code="unresolved_endpoint_os",
                    message="bound endpoint has unresolved backend OS",
                )
            )
    endpoint_by_name = {
        endpoint.name: endpoint for endpoint in bound.logical_topology.endpoints
    }
    for endpoint_name, network_role in bound.endpoint_network_roles.items():
        _validate_bound_endpoint_network_role(
            endpoint_name,
            network_role,
            endpoint_by_name,
            issues,
        )
    _validate_inventory_network_role(bound, issues)


def validate_bound_topology_for_compile(bound: BoundTopology) -> None:  # noqa: C901
    issues: list[ValidationIssue] = []
    _validate_bound_endpoints(bound, issues)
    _validate_bound_prefix_intent(bound, issues)
    _validate_bound_device_config(bound, issues)
    if not bound.device_groups:
        issues.append(
            ValidationIssue(
                path="device_groups",
                code="missing_bound_device_groups",
                message="bound logical topology has no resolved device groups",
            )
        )
    for index, dg in enumerate(bound.device_groups):
        _validate_bound_legacy_bgp_peer_name(dg, index, bound, issues)
        _validate_bound_ixia_children(dg, index, bound, issues)
        if dg.peer_relationship is not None and not isinstance(
            dg.peer_relationship,
            PeerRelationship,
        ):
            issues.append(
                ValidationIssue(
                    path=f"device_groups[{index}].peer_relationship",
                    code="invalid_peer_relationship",
                    message="bound peer relationship must be a PeerRelationship",
                )
            )
        if (
            NetworkRole.EB in bound.endpoint_network_roles.values()
            and dg.peer_relationship is None
        ):
            issues.append(
                ValidationIssue(
                    path=f"device_groups[{index}].peer_relationship",
                    code="missing_peer_relationship",
                    message="EB adjacencies require a normalized peer relationship",
                )
            )
        if (
            dg.spec.peer_relationship is not None
            and dg.peer_relationship is not dg.spec.peer_relationship
        ):
            issues.append(
                ValidationIssue(
                    path=f"device_groups[{index}].peer_relationship",
                    code="resolved_peer_relationship_mismatch",
                    message="bound peer relationship differs from logical intent",
                )
            )
        if dg.route_attributes != dg.spec.route_attributes:
            issues.append(
                ValidationIssue(
                    path=f"device_groups[{index}].route_attributes",
                    code="resolved_route_attributes_mismatch",
                    message="bound group route attributes differ from logical intent",
                )
            )
        if dg.partition != dg.spec.partition:
            issues.append(
                ValidationIssue(
                    path=f"device_groups[{index}].partition",
                    code="resolved_partition_mismatch",
                    message="bound partition differs from logical intent",
                )
            )
        if dg.legacy_ixia_device_group_index != dg.spec.legacy_ixia_device_group_index:
            issues.append(
                ValidationIssue(
                    path=f"device_groups[{index}].legacy_ixia_device_group_index",
                    code="resolved_ixia_device_group_index_mismatch",
                    message="bound IXIA index differs from logical intent",
                )
            )
        _validate_bound_ixia_snapshot(dg, index, bound, issues)
        provenance = dg.provenance
        if provenance is None:
            issues.append(
                ValidationIssue(
                    path=f"device_groups[{index}].provenance",
                    code="missing_bind_provenance",
                    message="bound device group has no immutable bind provenance",
                )
            )
        else:
            for field_name, value in (
                ("parent_network", provenance.parent_network),
                ("local_asn", provenance.local_asn),
                ("remote_asn", provenance.remote_asn),
            ):
                if getattr(dg, field_name) != value:
                    issues.append(
                        ValidationIssue(
                            path=f"device_groups[{index}].{field_name}",
                            code=f"post_bind_{field_name}_replacement",
                            message=f"bound {field_name} changed after resolution",
                        )
                    )
        if not dg.routing_driver:
            issues.append(
                ValidationIssue(
                    path=f"device_groups[{index}].routing_driver",
                    code="missing_routing_driver",
                    message="bound device group has no routing driver",
                )
            )
        peer_column_lengths = (
            len(dg.a_ips),
            len(dg.z_ips),
            len(dg.peer_cidrs),
        )
        if any(length != dg.peer_count for length in peer_column_lengths):
            issues.append(
                ValidationIssue(
                    path=f"device_groups[{index}].peers",
                    code="resolved_peer_count_mismatch",
                    message=(
                        f"bound device group declares {dg.peer_count} peers but "
                        "contains resolved A/Z/CIDR columns with lengths "
                        f"{peer_column_lengths}"
                    ),
                )
            )
            continue
        for peer_index, peer in enumerate(dg.peers):
            try:
                a_ip = ipaddress.ip_address(peer.a_ip)
                z_ip = ipaddress.ip_address(peer.z_ip)
                peer_cidr = (
                    None
                    if peer.peer_cidr is None
                    else ipaddress.ip_network(peer.peer_cidr)
                )
            except (TypeError, ValueError):
                issues.append(
                    ValidationIssue(
                        path=f"device_groups[{index}].peers[{peer_index}]",
                        code="invalid_resolved_peer",
                        message="resolved peer row contains an invalid IP or CIDR",
                    )
                )
                continue
            if peer_cidr is not None and (
                a_ip not in peer_cidr or z_ip not in peer_cidr
            ):
                issues.append(
                    ValidationIssue(
                        path=(f"device_groups[{index}].peers[{peer_index}].peer_cidr"),
                        code="resolved_peer_cidr_disagreement",
                        message=(
                            f"resolved A/Z addresses {peer.a_ip} and {peer.z_ip} "
                            f"do not both belong to {peer.peer_cidr}"
                        ),
                    )
                )
        if bound.logical_topology.legacy_profile in _COMPACT_IXIA_PROFILES:
            _validate_compact_ixia_peer_sequence(dg, index, issues)
    _validate_resolved_port_graph(bound.device_groups, issues)
    _validate_resolved_partitions(bound.device_groups, issues)
    _validate_legacy_device_group_indices(bound.device_groups, issues)
    if tuple(bound.logical_topology.route_senders) != bound.resolved_route_senders:
        issues.append(
            ValidationIssue(
                path="resolved_route_senders",
                code="resolved_route_sender_mismatch",
                message="bound route senders differ from logical intent",
            )
        )
    if issues:
        raise TopologyValidationError(bound.logical_topology.name, issues)


def _validate_bound_device_config(
    bound: BoundTopology,
    issues: list[ValidationIssue],
) -> None:
    device_config = bound.device_config
    if device_config is None:
        issues.append(
            ValidationIssue(
                path="device_config",
                code="missing_bound_device_config",
                message="bound logical topology has no resolved device config",
            )
        )
        return
    issues.extend(collect_routing_device_config_issues(device_config))
    _validate_openr_standalone_inputs(
        device_config,
        bound.physical_inventory,
        issues,
    )


def _validate_bound_ixia_children(
    device_group: BoundDeviceGroup,
    group_index: int,
    bound: BoundTopology,
    issues: list[ValidationIssue],
) -> None:
    authored = (
        bound.logical_topology.device_groups[group_index].ixia_children
        if group_index < len(bound.logical_topology.device_groups)
        else ()
    )
    path = f"device_groups[{group_index}].ixia_children"
    if device_group.spec.ixia_children != authored:
        issues.append(
            ValidationIssue(
                path=path,
                code="post_bind_ixia_children_replacement",
                message="bound parent child intent changed after resolution",
            )
        )
    if len(device_group.ixia_children) != len(authored):
        issues.append(
            ValidationIssue(
                path=path,
                code="resolved_ixia_child_count_mismatch",
                message="resolved IXIA child count differs from logical intent",
            )
        )
        return
    if not authored:
        return
    parent_peers = device_group.peers
    for child_index, (child, child_spec) in enumerate(
        zip(device_group.ixia_children, authored, strict=True)
    ):
        child_path = f"{path}[{child_index}]"
        if child.spec != child_spec:
            issues.append(
                ValidationIssue(
                    path=f"{child_path}.spec",
                    code="resolved_ixia_child_spec_mismatch",
                    message="resolved IXIA child metadata differs from logical intent",
                )
            )
        start = child_spec.start_index
        end = start + child_spec.peer_count
        if child.peers != parent_peers[start:end]:
            issues.append(
                ValidationIssue(
                    path=f"{child_path}.peers",
                    code="post_bind_ixia_child_peer_replacement",
                    message="resolved IXIA child peer slice changed after binding",
                )
            )
        expected_advertisements = _slice_ixia_child_advertisements(
            t.cast(
                t.Sequence[ResolvedPrefixAdvertisement],
                device_group.prefix_advertisements,
            ),
            child_spec,
        )
        if child.prefix_advertisements != expected_advertisements:
            issues.append(
                ValidationIssue(
                    path=f"{child_path}.prefix_advertisements",
                    code="post_bind_ixia_child_advertisement_replacement",
                    message=(
                        "resolved IXIA child advertisements are not the inherited "
                        "parent slices"
                    ),
                )
            )


def _validate_bound_legacy_bgp_peer_name(
    device_group: BoundDeviceGroup,
    group_index: int,
    bound: BoundTopology,
    issues: list[ValidationIssue],
) -> None:
    authored_bgp_peer_name = (
        bound.logical_topology.device_groups[group_index].legacy_ixia_bgp_peer_name
        if group_index < len(bound.logical_topology.device_groups)
        else None
    )
    if (
        device_group.spec.legacy_ixia_bgp_peer_name == authored_bgp_peer_name
        and device_group.legacy_ixia_bgp_peer_name == authored_bgp_peer_name
    ):
        return
    issues.append(
        ValidationIssue(
            path=f"device_groups[{group_index}].legacy_ixia_bgp_peer_name",
            code="post_bind_legacy_ixia_bgp_peer_name_replacement",
            message="bound legacy IXIA BGP peer name changed after resolution",
        )
    )


def _validate_bound_ixia_snapshot(
    device_group: BoundDeviceGroup,
    group_index: int,
    bound: BoundTopology,
    issues: list[ValidationIssue],
) -> None:
    path = f"device_groups[{group_index}].port_assignment"
    authored = device_group.spec.port_assignment
    assignment = device_group.port_assignment
    if authored is None or assignment is None:
        if authored != assignment or device_group.ixia_port is not None:
            issues.append(
                ValidationIssue(
                    path=path,
                    code="resolved_port_assignment_mismatch",
                    message="resolved assignment differs from logical intent",
                )
            )
        return
    if assignment.logical_role != authored.logical_role:
        issues.append(
            ValidationIssue(
                path=f"{path}.logical_role",
                code="resolved_port_assignment_mismatch",
                message="resolved logical port role differs from logical intent",
            )
        )
    if assignment.reuse_group != authored.reuse_group:
        issues.append(
            ValidationIssue(
                path=f"{path}.reuse_group",
                code="resolved_port_assignment_mismatch",
                message="resolved port reuse group differs from logical intent",
            )
        )
    if assignment.endpoint_label_style is not authored.endpoint_label_style:
        issues.append(
            ValidationIssue(
                path=f"{path}.endpoint_label_style",
                code="resolved_port_assignment_mismatch",
                message="resolved endpoint label style differs from logical intent",
            )
        )
    if (
        any(
            interface != assignment.dut_interface
            for interface in (
                device_group.a_interface,
                device_group.z_interface,
            )
            if interface is not None
        )
        or device_group.ixia_port != assignment.ixia_port
    ):
        issues.append(
            ValidationIssue(
                path=path,
                code="resolved_port_assignment_mismatch",
                message="resolved assignment disagrees with scalar port fields",
            )
        )
    expected_index = bound.port_map.get(authored.logical_role)
    ixia_ports = getattr(bound.physical_inventory, "ixia_ports", None) or ()
    inventory_pair: tuple[t.Any, ...] | None = None
    if (
        isinstance(assignment.physical_inventory_index, int)
        and not isinstance(assignment.physical_inventory_index, bool)
        and 0 <= assignment.physical_inventory_index < len(ixia_ports)
    ):
        entry = ixia_ports[assignment.physical_inventory_index]
        if isinstance(entry, (tuple, list)):
            inventory_pair = tuple(entry)
    if expected_index != assignment.physical_inventory_index or inventory_pair != (
        assignment.dut_interface,
        assignment.ixia_port,
    ):
        issues.append(
            ValidationIssue(
                path=f"{path}.physical_inventory_index",
                code="resolved_port_assignment_mismatch",
                message="resolved inventory index or connection was replaced",
            )
        )
    expected_profile = _physical_interface_profile(
        bound.physical_inventory,
        assignment.dut_interface,
        f"physical_inventory.ixia_ports[{assignment.physical_inventory_index}]",
        issues,
    )
    if (
        expected_profile is not None
        and expected_profile != assignment.physical_interface_profile
    ):
        issues.append(
            ValidationIssue(
                path=f"{path}.physical_interface_profile",
                code="resolved_port_assignment_mismatch",
                message="resolved physical interface profile was replaced",
            )
        )


def _validate_bound_prefix_intent(  # noqa: C901
    bound: BoundTopology,
    issues: list[ValidationIssue],
) -> None:
    expected_set_names = {
        prefix_set.name for prefix_set in bound.logical_topology.prefix_sets
    }
    if set(bound.resolved_prefix_sets) != expected_set_names:
        issues.append(
            ValidationIssue(
                path="resolved_prefix_sets",
                code="resolved_prefix_set_mismatch",
                message="bound prefix-set names disagree with logical topology intent",
            )
        )
    for dg_index, device_group in enumerate(bound.device_groups):
        expected = device_group.spec.prefix_advertisements
        resolved = device_group.prefix_advertisements
        if len(resolved) != len(expected):
            issues.append(
                ValidationIssue(
                    path=f"device_groups[{dg_index}].prefix_advertisements",
                    code="resolved_prefix_advertisement_count_mismatch",
                    message="bound advertisement count disagrees with authored intent",
                )
            )
            continue
        for ad_index, (authored, advertisement) in enumerate(
            zip(expected, resolved, strict=True)
        ):
            path = f"device_groups[{dg_index}].prefix_advertisements[{ad_index}]"
            expected_spec = (
                authored
                if authored.route_attributes is not None
                or device_group.spec.route_attributes is None
                else replace(
                    authored,
                    route_attributes=device_group.spec.route_attributes,
                )
            )
            if advertisement.spec != expected_spec:
                issues.append(
                    ValidationIssue(
                        path=path,
                        code="resolved_prefix_advertisement_mismatch",
                        message="bound advertisement does not retain authored intent",
                    )
                )
                continue
            if advertisement.prefix_set is not bound.resolved_prefix_sets.get(
                authored.prefix_set
            ):
                issues.append(
                    ValidationIssue(
                        path=f"{path}.prefix_set",
                        code="resolved_prefix_set_identity_mismatch",
                        message="advertisement does not reference the canonical resolved set",
                    )
                )
            if len(advertisement.paths_by_peer) != device_group.peer_count:
                issues.append(
                    ValidationIssue(
                        path=f"{path}.paths_by_peer",
                        code="resolved_route_peer_count_mismatch",
                        message="resolved route sequences do not match peer count",
                    )
                )
                continue
            for peer_index, paths in enumerate(advertisement.paths_by_peer):
                if len(paths) != authored.allocation.prefixes_per_peer:
                    issues.append(
                        ValidationIssue(
                            path=f"{path}.paths_by_peer[{peer_index}]",
                            code="resolved_route_count_mismatch",
                            message="resolved route sequence has incorrect cardinality",
                        )
                    )
                    continue
                if paths:
                    for route in (paths[0], paths[-1]):
                        try:
                            prefix = ipaddress.ip_address(route.prefix)
                            next_hop = ipaddress.ip_address(route.next_hop)
                        except ValueError:
                            issues.append(
                                ValidationIssue(
                                    path=f"{path}.paths_by_peer[{peer_index}]",
                                    code="invalid_resolved_route_path",
                                    message="resolved route sample contains an invalid address",
                                )
                            )
                            break
                        expected_version = 4 if device_group.afi == "v4" else 6
                        if (
                            prefix.version != expected_version
                            or next_hop.version != expected_version
                        ):
                            issues.append(
                                ValidationIssue(
                                    path=f"{path}.paths_by_peer[{peer_index}]",
                                    code="resolved_route_afi_mismatch",
                                    message="resolved route sample disagrees with device-group AFI",
                                )
                            )
                            break


def _validate_compact_ixia_peer_sequence(
    device_group: BoundDeviceGroup,
    group_index: int,
    issues: list[ValidationIssue],
) -> None:
    peers = device_group.peers
    if not peers:
        return
    try:
        first_a_ip = ipaddress.ip_address(peers[0].a_ip)
        first_z_ip = ipaddress.ip_address(peers[0].z_ip)
    except (TypeError, ValueError):
        return

    expected_prefix_length = _COMPACT_IXIA_PREFIX_LENGTHS.get(device_group.afi)
    reported_prefix_mismatch = False
    for peer_index, peer in enumerate(peers):
        path = f"device_groups[{group_index}].peers[{peer_index}]"
        if peer.peer_cidr is None:
            issues.append(
                ValidationIssue(
                    path=f"{path}.peer_cidr",
                    code="missing_compiler_peer_cidr",
                    message="compact IXIA peer lowering requires a resolved peer CIDR",
                )
            )
            continue
        try:
            a_ip = ipaddress.ip_address(peer.a_ip)
            z_ip = ipaddress.ip_address(peer.z_ip)
            peer_cidr = ipaddress.ip_network(peer.peer_cidr)
        except (TypeError, ValueError):
            continue
        try:
            expected_a_ip = first_a_ip + (peer_index * 2)
            expected_z_ip = first_z_ip + (peer_index * 2)
        except ValueError:
            issues.append(
                ValidationIssue(
                    path=path,
                    code="resolved_peer_sequence_wrap",
                    message="compact +2 IXIA peer sequence exceeds the AFI range",
                )
            )
            continue
        if a_ip != expected_a_ip or z_ip != expected_z_ip:
            issues.append(
                ValidationIssue(
                    path=path,
                    code="resolved_peer_sequence_disagreement",
                    message=(
                        "resolved peer row does not match the compact +2 IXIA "
                        "sequence emitted by the compiler"
                    ),
                )
            )
        if (
            expected_prefix_length is not None
            and peer_cidr.prefixlen != expected_prefix_length
            and not reported_prefix_mismatch
        ):
            issues.append(
                ValidationIssue(
                    path=f"{path}.peer_cidr",
                    code="resolved_peer_prefix_length_disagreement",
                    message=(
                        "resolved peer CIDR prefix length differs from the mask "
                        "emitted by the compiler"
                    ),
                )
            )
            reported_prefix_mismatch = True


def _bind_device_group(
    *,
    dg: DeviceGroupSpec,
    index: int,
    context: _BindingContext,
) -> BoundDeviceGroup:
    path = f"device_groups[{index}]"
    base_role = _base_role(dg.role)
    peer_relationship = _resolve_peer_relationship(dg, path, context)

    ports = _resolve_device_group_ports(dg, base_role, path, context)
    addresses = _resolve_device_group_addresses(dg, base_role, path, context)
    bgp = _resolve_device_group_bgp(
        dg,
        base_role,
        peer_relationship,
        path,
        context,
    )
    return _build_bound_device_group(
        dg,
        ports,
        addresses,
        bgp,
        peer_relationship,
        context,
    )


def _resolve_peer_relationship(
    dg: DeviceGroupSpec,
    path: str,
    context: _BindingContext,
) -> PeerRelationship | None:
    relationship = dg.peer_relationship
    if relationship is not None and not isinstance(relationship, PeerRelationship):
        context.issues.append(
            ValidationIssue(
                path=f"{path}.peer_relationship",
                code="invalid_peer_relationship",
                message="peer relationship must be a PeerRelationship",
            )
        )
        return None
    if relationship is not None:
        return relationship
    relationship = _LEGACY_PEER_RELATIONSHIPS.get(dg.role)
    if (
        relationship is None
        and getattr(context.physical_inventory, "network_role", None) is NetworkRole.EB
    ):
        context.issues.append(
            ValidationIssue(
                path=f"{path}.peer_relationship",
                code="missing_peer_relationship",
                message=(
                    "EB device groups require an explicit peer relationship; "
                    "the raw role has no exact compatibility mapping"
                ),
            )
        )
    return relationship


def _resolve_device_group_ports(
    dg: DeviceGroupSpec,
    base_role: str,
    path: str,
    context: _BindingContext,
) -> _ResolvedDeviceGroupPorts:
    a_endpoint = context.endpoint_by_name[dg.a_endpoint]
    z_endpoint = context.endpoint_by_name[dg.z_endpoint]

    dut_interface = None
    ixia_port = None
    resolved_assignment = None
    has_ixia_endpoint = _endpoint_is_ixia(a_endpoint) or _endpoint_is_ixia(z_endpoint)
    if has_ixia_endpoint:
        authored_assignment = dg.port_assignment
        if authored_assignment is None:
            return _ResolvedDeviceGroupPorts(
                a_endpoint=a_endpoint,
                z_endpoint=z_endpoint,
                dut_interface=None,
                ixia_port=None,
                port_assignment=None,
            )
        port_index = _resolve_port_index(
            authored_assignment.logical_role,
            context.port_map,
            path,
            context.issues,
        )
        if port_index is not None:
            dut_interface, ixia_port, interface_profile = _resolve_ixia_port(
                context.physical_inventory,
                port_index,
                f"{path}.port_assignment.logical_role",
                context.issues,
            )
            if (
                dut_interface is not None
                and ixia_port is not None
                and interface_profile is not None
            ):
                resolved_assignment = ResolvedIxiaPortAssignment(
                    logical_role=authored_assignment.logical_role,
                    dut_interface=dut_interface,
                    ixia_port=ixia_port,
                    physical_inventory_index=port_index,
                    reuse_group=authored_assignment.reuse_group,
                    physical_interface_profile=interface_profile,
                    endpoint_label_style=authored_assignment.endpoint_label_style,
                )
    return _ResolvedDeviceGroupPorts(
        a_endpoint=a_endpoint,
        z_endpoint=z_endpoint,
        dut_interface=dut_interface,
        ixia_port=ixia_port,
        port_assignment=resolved_assignment,
    )


def _resolve_device_group_addresses(
    dg: DeviceGroupSpec,
    base_role: str,
    path: str,
    context: _BindingContext,
) -> _ResolvedDeviceGroupAddresses:
    generated_address_plan = not (dg.address_plan.a_ips or dg.address_plan.z_ips)
    parent_network, parent_network_source = (
        _resolve_parent_network(
            dg,
            base_role,
            context.parent_networks,
            path,
            context.issues,
        )
        if generated_address_plan
        else (None, None)
    )
    a_ips, z_ips = _resolve_address_plan(
        dg.address_plan,
        parent_network,
        dg.peer_count,
        dg.afi,
        f"{path}.address_plan",
        context.issues,
    )
    _record_duplicate_ips(
        context.bound_ips,
        dg.name,
        a_ips + z_ips,
        f"{path}.address_plan",
        generated=generated_address_plan,
        issues=context.issues,
    )
    peers = _resolve_peer_cidrs(
        peer_cidrs=context.peer_cidrs,
        dg_name=dg.name,
        a_ips=a_ips,
        z_ips=z_ips,
        address_plan=dg.address_plan,
        afi=dg.afi,
        path=f"{path}.address_plan",
        generated=generated_address_plan,
        issues=context.issues,
    )
    return _ResolvedDeviceGroupAddresses(
        parent_network=parent_network,
        parent_network_source=parent_network_source,
        a_ips=a_ips,
        z_ips=z_ips,
        peers=peers,
    )


def _resolve_device_group_bgp(
    dg: DeviceGroupSpec,
    base_role: str,
    peer_relationship: PeerRelationship | None,
    path: str,
    context: _BindingContext,
) -> _ResolvedDeviceGroupBgp:
    peer_group = _resolve_peer_group(dg, context.peer_groups, path, context.issues)
    remote_asn, remote_asn_source = _resolve_device_group_remote_asn(
        dg,
        base_role,
        peer_group,
        path,
        context,
    )
    local_asn, local_asn_source = _resolve_local_asn(
        peer_group,
        context.as_numbers,
        context.physical_inventory,
        path,
        context.issues,
    )
    _validate_standard_bgp_role_asn_relationship(
        dg=dg,
        peer_relationship=peer_relationship,
        local_network_role=getattr(context.physical_inventory, "network_role", None),
        local_asn=local_asn,
        local_asn_source=local_asn_source,
        remote_asn=remote_asn,
        path=path,
        issues=context.issues,
    )
    return _ResolvedDeviceGroupBgp(
        peer_group=peer_group,
        local_asn=local_asn,
        local_asn_source=local_asn_source,
        remote_asn=remote_asn,
        remote_asn_source=remote_asn_source,
    )


def _resolve_device_group_remote_asn(
    dg: DeviceGroupSpec,
    base_role: str,
    peer_group: BgpPeerGroup | str | None,
    path: str,
    context: _BindingContext,
) -> tuple[int | None, str | None]:
    if isinstance(dg.peer_group, str) and peer_group is None:
        return None, None
    return _resolve_remote_asn(
        dg,
        base_role,
        peer_group,
        context.as_numbers,
        path,
        context.issues,
    )


def _build_bound_device_group(
    dg: DeviceGroupSpec,
    ports: _ResolvedDeviceGroupPorts,
    addresses: _ResolvedDeviceGroupAddresses,
    bgp: _ResolvedDeviceGroupBgp,
    peer_relationship: PeerRelationship | None,
    context: _BindingContext,
) -> BoundDeviceGroup:
    a_os = context.endpoint_os[dg.a_endpoint]
    z_os = context.endpoint_os[dg.z_endpoint]

    return BoundDeviceGroup(
        spec=dg,
        a_interface=ports.dut_interface if _endpoint_is_dut(ports.a_endpoint) else None,
        z_interface=ports.dut_interface if _endpoint_is_dut(ports.z_endpoint) else None,
        ixia_port=ports.ixia_port,
        a_ips=addresses.a_ips,
        z_ips=addresses.z_ips,
        peer_cidrs=tuple(peer.peer_cidr for peer in addresses.peers),
        a_os=a_os,
        z_os=z_os,
        routing_driver=dg.routing_driver or _default_routing_driver(a_os),
        parent_network=addresses.parent_network,
        local_asn=bgp.local_asn,
        remote_asn=bgp.remote_asn,
        peer_group=bgp.peer_group,
        legacy_ixia_tag_name=dg.legacy_ixia_tag_name,
        legacy_ixia_bgp_peer_name=dg.legacy_ixia_bgp_peer_name,
        legacy_ixia_device_group_name=dg.legacy_ixia_device_group_name,
        port_assignment=ports.port_assignment,
        partition=dg.partition,
        legacy_ixia_device_group_index=dg.legacy_ixia_device_group_index,
        route_attributes=dg.route_attributes,
        peer_relationship=peer_relationship,
        provenance=ResolvedDeviceGroupProvenance(
            parent_network=addresses.parent_network,
            parent_network_source=addresses.parent_network_source,
            local_asn=bgp.local_asn,
            local_asn_source=bgp.local_asn_source,
            remote_asn=bgp.remote_asn,
            remote_asn_source=bgp.remote_asn_source,
        ),
    )


def _build_bound_topology_mappings(
    *,
    logical_topology: LogicalTopology,
    physical_inventory: t.Any,
    bound_dgs: t.Sequence[BoundDeviceGroup],
    endpoint_os: t.Mapping[str, str],
) -> _BoundTopologyMappings:
    interfaces: dict[str, str] = {}
    for bound_dg in bound_dgs:
        interface = bound_dg.a_interface or bound_dg.z_interface
        if interface is not None:
            interfaces[bound_dg.name] = interface

    network_role = getattr(physical_inventory, "network_role", None)
    endpoint_network_roles = {
        endpoint.name: network_role
        for endpoint in logical_topology.endpoints
        if _endpoint_is_dut(endpoint) and isinstance(network_role, NetworkRole)
    }

    return _BoundTopologyMappings(
        endpoint_network_roles=endpoint_network_roles,
        resolved_endpoints={
            endpoint.name: {
                "os": endpoint_os[endpoint.name],
                "device_name": (
                    getattr(physical_inventory, "device_name", None)
                    if _endpoint_is_dut(endpoint)
                    else None
                ),
                "physical_identifier_field": (
                    "device_name" if _endpoint_is_dut(endpoint) else "ixia_chassis_ip"
                ),
            }
            for endpoint in logical_topology.endpoints
        },
        resolved_device_groups={
            bound_dg.name: {
                "a_interface": bound_dg.a_interface,
                "z_interface": bound_dg.z_interface,
                "ixia_port": bound_dg.ixia_port,
                "a_ips": bound_dg.a_ips,
                "z_ips": bound_dg.z_ips,
                "routing_driver": bound_dg.routing_driver,
            }
            for bound_dg in bound_dgs
        },
        routing_drivers={
            bound_dg.name: bound_dg.routing_driver
            for bound_dg in bound_dgs
            if bound_dg.routing_driver is not None
        },
        ixia_ports={
            bound_dg.name: bound_dg.ixia_port
            for bound_dg in bound_dgs
            if bound_dg.ixia_port
        },
        interfaces=interfaces,
        as_numbers={
            bound_dg.name: bound_dg.remote_asn
            for bound_dg in bound_dgs
            if bound_dg.remote_asn is not None
        },
        peer_groups_by_device_group={
            bound_dg.name: bound_dg.peer_group
            for bound_dg in bound_dgs
            if bound_dg.peer_group is not None
        },
        legacy_names={
            bound_dg.name: bound_dg.legacy_ixia_tag_name
            for bound_dg in bound_dgs
            if bound_dg.legacy_ixia_tag_name
        },
    )


def _validate_physical_inventory(
    logical_topology: LogicalTopology,
    physical_inventory: t.Any,
    issues: list[ValidationIssue],
) -> None:
    network_role = getattr(physical_inventory, "network_role", None)
    if network_role is not None and not isinstance(network_role, NetworkRole):
        issues.append(
            ValidationIssue(
                path="physical_inventory.network_role",
                code="invalid_physical_inventory_field",
                message="physical_inventory.network_role must be a NetworkRole",
            )
        )
    if not getattr(physical_inventory, "device_name", None):
        issues.append(
            ValidationIssue(
                path="physical_inventory.device_name",
                code="missing_physical_inventory_field",
                message="physical_inventory.device_name is required",
            )
        )
    endpoint_by_name = {
        endpoint.name: endpoint for endpoint in logical_topology.endpoints
    }
    if any(
        _endpoint_is_ixia(endpoint_by_name.get(dg.a_endpoint))
        or _endpoint_is_ixia(endpoint_by_name.get(dg.z_endpoint))
        for dg in logical_topology.device_groups
    ):
        if not getattr(physical_inventory, "ixia_chassis_ip", None):
            issues.append(
                ValidationIssue(
                    path="physical_inventory.ixia_chassis_ip",
                    code="missing_physical_inventory_field",
                    message="physical_inventory.ixia_chassis_ip is required for IXIA device groups",
                )
            )
        if not getattr(physical_inventory, "ixia_ports", None):
            issues.append(
                ValidationIssue(
                    path="physical_inventory.ixia_ports",
                    code="missing_ixia_ports",
                    message="physical_inventory.ixia_ports is required for IXIA device groups",
                )
            )
    if getattr(physical_inventory, "dut_bgp_as", None) is None:
        issues.append(
            ValidationIssue(
                path="physical_inventory.dut_bgp_as",
                code="missing_physical_inventory_field",
                message="physical_inventory.dut_bgp_as is required",
            )
        )
    else:
        _validate_asn_value(
            getattr(physical_inventory, "dut_bgp_as", None),
            "physical_inventory.dut_bgp_as",
            issues,
            label="physical_inventory.dut_bgp_as",
        )


def _resolve_endpoint_os(
    endpoint: EndpointSpec,
    physical_inventory: t.Any,
    issues: list[ValidationIssue],
) -> str:
    if endpoint.required_os:
        return endpoint.required_os
    if not _endpoint_is_dut(endpoint):
        return "ixia"

    for attr in ("os", "platform", "backend", "device_os"):
        backend = getattr(physical_inventory, attr, None)
        if backend is None:
            continue
        backend_value = str(backend)
        if backend_value:
            return _normalize_backend(
                backend_value,
                f"endpoints.{endpoint.name}",
                attr,
                issues,
            )
        issues.append(
            ValidationIssue(
                path=f"endpoints.{endpoint.name}",
                code="missing_physical_inventory_backend",
                message=f"PhysicalInventory.{attr} is set to an empty backend value",
            )
        )
        return "unknown"
    if getattr(physical_inventory, "bgpcpp_configerator_path", None):
        return "eos"
    if getattr(physical_inventory, "fboss_agent_configerator_path", None):
        return "fboss"

    issues.append(
        ValidationIssue(
            path=f"endpoints.{endpoint.name}",
            code="missing_physical_inventory_backend",
            message="DUT endpoint needs PhysicalInventory.os, platform, backend, or configerator path",
        )
    )
    return "unknown"


def _resolve_port_index(
    logical_role: str,
    port_map: t.Mapping[str, int],
    path: str,
    issues: list[ValidationIssue],
) -> int | None:
    if logical_role in port_map:
        port_index = port_map[logical_role]
        if isinstance(port_index, bool) or not isinstance(port_index, int):
            issues.append(
                ValidationIssue(
                    path=f"{path}.port_assignment.logical_role",
                    code="invalid_port_map_index",
                    message="port_map values must be integer inventory indices",
                )
            )
            return None
        return port_index
    issues.append(
        ValidationIssue(
            path=f"{path}.port_assignment.logical_role",
            code="missing_port_map_role",
            message=(
                f"logical role {logical_role!r} is not in port_map; available roles: "
                f"{sorted(port_map)}"
            ),
        )
    )
    return None


def _resolve_ixia_port(
    physical_inventory: t.Any,
    port_index: int,
    path: str,
    issues: list[ValidationIssue],
) -> tuple[str | None, str | None, PhysicalInterfaceProfile | None]:
    ixia_ports = getattr(physical_inventory, "ixia_ports", None) or []
    if not ixia_ports:
        return None, None, None
    if port_index < 0 or port_index >= len(ixia_ports):
        issues.append(
            ValidationIssue(
                path=path,
                code="port_map_index_out_of_range",
                message=(
                    f"port index {port_index} is out of range for "
                    f"{len(ixia_ports)} IXIA ports"
                ),
            )
        )
        return None, None, None
    ixia_port_entry = ixia_ports[port_index]
    if not isinstance(ixia_port_entry, (tuple, list)) or len(ixia_port_entry) != 2:
        issues.append(
            ValidationIssue(
                path=f"physical_inventory.ixia_ports[{port_index}]",
                code="malformed_ixia_port",
                message=("IXIA port entries must be (dut_interface, ixia_port) pairs"),
            )
        )
        return None, None, None
    dut_interface, ixia_port = ixia_port_entry
    if not isinstance(dut_interface, str) or not isinstance(ixia_port, str):
        issues.append(
            ValidationIssue(
                path=f"physical_inventory.ixia_ports[{port_index}]",
                code="malformed_ixia_port",
                message="IXIA port entries must contain string interface names",
            )
        )
        return None, None, None
    profile = _physical_interface_profile(
        physical_inventory,
        dut_interface,
        f"physical_inventory.ixia_ports[{port_index}]",
        issues,
    )
    return dut_interface, ixia_port, profile


def _physical_interface_profile(
    physical_inventory: t.Any,
    dut_interface: str,
    path: str,
    issues: list[ValidationIssue],
) -> PhysicalInterfaceProfile | None:
    profiles = getattr(physical_inventory, "physical_interface_profiles", None)
    if isinstance(profiles, dict):
        profile = profiles.get(dut_interface)
    else:
        profile = getattr(
            physical_inventory,
            "default_physical_interface_profile",
            None,
        )
    if isinstance(profile, PhysicalInterfaceProfile):
        return profile
    issues.append(
        ValidationIssue(
            path=f"{path}.physical_interface_profile",
            code="missing_physical_interface_profile",
            message=(
                f"DUT interface {dut_interface!r} requires a typed physical "
                "interface profile"
            ),
        )
    )
    return None


def _resolve_parent_network(
    dg: DeviceGroupSpec,
    base_role: str,
    parent_networks: t.Mapping[str, str],
    path: str,
    issues: list[ValidationIssue],
) -> tuple[str | None, str | None]:
    if dg.address_plan.parent_network:
        return dg.address_plan.parent_network, "address_plan.parent_network"

    keys = [
        dg.address_plan.parent_network_key,
        f"{dg.role}_{dg.afi}",
        f"{base_role}_{dg.afi}",
    ]
    for key in keys:
        if key and key in parent_networks:
            return parent_networks[key], f"parent_networks[{key!r}]"

    issues.append(
        ValidationIssue(
            path=f"{path}.address_plan.parent_network_key",
            code="missing_parent_network",
            message=(
                f"no parent network found for keys {[key for key in keys if key]}; "
                f"available keys: {sorted(parent_networks)}"
            ),
        )
    )
    return None, None


def _resolve_address_plan(
    address_plan: AddressPlan,
    parent_network: str | None,
    peer_count: int,
    afi: str,
    path: str,
    issues: list[ValidationIssue],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if address_plan.a_ips or address_plan.z_ips:
        a_ips = tuple(address_plan.a_ips)
        z_ips = tuple(address_plan.z_ips)
        _validate_bound_ip_count(a_ips, peer_count, f"{path}.a_ips", issues)
        _validate_bound_ip_count(z_ips, peer_count, f"{path}.z_ips", issues)
        return a_ips, z_ips

    if not parent_network:
        return (), ()

    try:
        base = _parse_parent_base(parent_network, afi)
        if (afi == "v4" and base.version != 4) or (afi == "v6" and base.version != 6):
            issues.append(
                ValidationIssue(
                    path=f"{path}.parent_network",
                    code="parent_network_afi_mismatch",
                    message=f"parent network {parent_network!r} does not match {afi}",
                )
            )
            return (), ()
        a_offset = _offset_to_int(
            address_plan.a_offset,
            default=10 if afi == "v4" else 16,
        )
        z_offset = _offset_to_int(address_plan.z_offset, default=a_offset + 1)
        step_value, _step_attr = _address_plan_step(address_plan)
        stride = _offset_to_int(step_value, default=2)
        start_index = address_plan.start_index
        a_ips = tuple(
            str(base + a_offset + (start_index + index) * stride)
            for index in range(peer_count)
        )
        z_ips = tuple(
            str(base + z_offset + (start_index + index) * stride)
            for index in range(peer_count)
        )
        _validate_generated_ips_within_parent_network(
            parent_network,
            a_ips,
            z_ips,
            path,
            issues,
        )
    except ValueError as error:
        issues.append(
            ValidationIssue(
                path=path,
                code="invalid_address_plan",
                message=str(error),
            )
        )
        return (), ()

    _validate_bound_ip_count(a_ips, peer_count, f"{path}.a_ips", issues)
    _validate_bound_ip_count(z_ips, peer_count, f"{path}.z_ips", issues)
    return a_ips, z_ips


def _validate_generated_ips_within_parent_network(
    parent_network: str,
    a_ips: tuple[str, ...],
    z_ips: tuple[str, ...],
    path: str,
    issues: list[ValidationIssue],
) -> None:
    if "/" not in parent_network:
        return

    network = ipaddress.ip_network(parent_network, strict=False)
    for side, ips in (("a_ips", a_ips), ("z_ips", z_ips)):
        for index, ip in enumerate(ips):
            address = ipaddress.ip_address(ip)
            if address not in network:
                issues.append(
                    ValidationIssue(
                        path=f"{path}.{side}[{index}]",
                        code="address_out_of_bounds",
                        message=(
                            f"generated {side[:-1]} IP {ip} is outside "
                            f"parent network {network}"
                        ),
                    )
                )


def _resolve_peer_group(
    dg: DeviceGroupSpec,
    peer_groups: t.Mapping[str, BgpPeerGroup | str],
    path: str,
    issues: list[ValidationIssue],
) -> BgpPeerGroup | str | None:
    peer_group = dg.peer_group
    if isinstance(peer_group, str):
        if peer_group in peer_groups:
            return peer_groups[peer_group]
        issues.append(
            ValidationIssue(
                path=f"{path}.peer_group",
                code="missing_peer_group",
                message=(
                    f"peer group {peer_group!r} is not in peer_groups; "
                    f"available keys: {sorted(peer_groups)}"
                ),
            )
        )
        return None
    return peer_group


def _resolve_remote_asn(
    dg: DeviceGroupSpec,
    base_role: str,
    peer_group: BgpPeerGroup | str | None,
    as_numbers: t.Mapping[str, int],
    path: str,
    issues: list[ValidationIssue],
) -> tuple[int | None, str | None]:
    if isinstance(peer_group, BgpPeerGroup):
        if isinstance(peer_group.remote_asn, int):
            return (
                _validated_asn_or_none(
                    peer_group.remote_asn,
                    f"{path}.peer_group.remote_asn",
                    issues,
                    label="peer_group.remote_asn",
                ),
                "peer_group.remote_asn",
            )
        if isinstance(peer_group.remote_asn, str):
            if peer_group.remote_asn in as_numbers:
                return (
                    _validated_asn_or_none(
                        as_numbers[peer_group.remote_asn],
                        f"{path}.peer_group.remote_asn",
                        issues,
                        label=f"as_numbers[{peer_group.remote_asn!r}]",
                    ),
                    f"as_numbers[{peer_group.remote_asn!r}]",
                )
            issues.append(
                ValidationIssue(
                    path=f"{path}.peer_group.remote_asn",
                    code="missing_as_number",
                    message=(
                        f"ASN key {peer_group.remote_asn!r} is not in as_numbers; "
                        f"available keys: {sorted(as_numbers)}"
                    ),
                )
            )
            return None, None
        return None, None

    for key in (dg.role, base_role):
        if key in as_numbers:
            return (
                _validated_asn_or_none(
                    as_numbers[key],
                    f"{path}.role",
                    issues,
                    label=f"as_numbers[{key!r}]",
                ),
                f"as_numbers[{key!r}]",
            )
    issues.append(
        ValidationIssue(
            path=f"{path}.role",
            code="missing_as_number",
            message=(
                f"no ASN found for role {dg.role!r} or base role {base_role!r}; "
                f"available keys: {sorted(as_numbers)}"
            ),
        )
    )
    return None, None


def _resolve_local_asn(
    peer_group: BgpPeerGroup | str | None,
    as_numbers: t.Mapping[str, int],
    physical_inventory: t.Any,
    path: str,
    issues: list[ValidationIssue],
) -> tuple[int | None, str | None]:
    if isinstance(peer_group, BgpPeerGroup) and peer_group.local_asn is not None:
        if isinstance(peer_group.local_asn, int):
            return (
                _validated_asn_or_none(
                    peer_group.local_asn,
                    f"{path}.peer_group.local_asn",
                    issues,
                    label="peer_group.local_asn",
                ),
                "peer_group.local_asn",
            )
        if isinstance(peer_group.local_asn, str):
            if peer_group.local_asn in as_numbers:
                return (
                    _validated_asn_or_none(
                        as_numbers[peer_group.local_asn],
                        f"{path}.peer_group.local_asn",
                        issues,
                        label=f"as_numbers[{peer_group.local_asn!r}]",
                    ),
                    f"as_numbers[{peer_group.local_asn!r}]",
                )
            issues.append(
                ValidationIssue(
                    path=f"{path}.peer_group.local_asn",
                    code="missing_as_number",
                    message=(
                        f"ASN key {peer_group.local_asn!r} is not in as_numbers; "
                        f"available keys: {sorted(as_numbers)}"
                    ),
                )
            )
            return None, None
        _validate_asn_value(
            peer_group.local_asn,
            f"{path}.peer_group.local_asn",
            issues,
            label="peer_group.local_asn",
        )
        return None, None
    inventory_asn = _valid_asn_or_none(getattr(physical_inventory, "dut_bgp_as", None))
    return (
        inventory_asn,
        "physical_inventory.dut_bgp_as" if inventory_asn is not None else None,
    )


def _validate_asn_value(
    value: t.Any,
    path: str,
    issues: list[ValidationIssue],
    *,
    label: str,
) -> bool:
    if isinstance(value, bool) or not isinstance(value, int):
        issues.append(
            ValidationIssue(
                path=path,
                code="invalid_asn",
                message=f"{label} must be an integer ASN",
            )
        )
        return False
    if value <= 0 or value > _IXIA_4BYTE_ASN_MAX:
        issues.append(
            ValidationIssue(
                path=path,
                code="invalid_asn",
                message=(f"{label} must be between 1 and {_IXIA_4BYTE_ASN_MAX}"),
            )
        )
        return False
    return True


def _validated_asn_or_none(
    value: t.Any,
    path: str,
    issues: list[ValidationIssue],
    *,
    label: str,
) -> int | None:
    if _validate_asn_value(value, path, issues, label=label):
        return value
    return None


def _valid_asn_or_none(value: t.Any) -> int | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
        or value > _IXIA_4BYTE_ASN_MAX
    ):
        return None
    return value


def _validate_standard_bgp_role_asn_relationship(
    *,
    dg: DeviceGroupSpec,
    peer_relationship: PeerRelationship | None,
    local_network_role: NetworkRole | None,
    local_asn: int | None,
    local_asn_source: str | None,
    remote_asn: int | None,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    if local_asn is None or remote_asn is None:
        return
    if peer_relationship is PeerRelationship.INTERNAL and local_asn != remote_asn:
        if _is_eb_inventory_identity_asn_fallback(
            local_network_role=local_network_role,
            local_asn_source=local_asn_source,
        ):
            return
        issues.append(
            ValidationIssue(
                path=f"{path}.role",
                code="asn_relationship_mismatch",
                message=(
                    f"{dg.role!r} peers must use the local ASN "
                    f"{local_asn}, got remote ASN {remote_asn}"
                ),
            )
        )
    if (
        peer_relationship
        in {
            PeerRelationship.EXTERNAL,
            PeerRelationship.MONITOR,
        }
        and local_asn == remote_asn
    ):
        issues.append(
            ValidationIssue(
                path=f"{path}.role",
                code="asn_relationship_mismatch",
                message=(
                    f"{dg.role!r} peers must use a remote ASN different "
                    f"from local ASN {local_asn}"
                ),
            )
        )


def _is_eb_inventory_identity_asn_fallback(
    *,
    local_network_role: NetworkRole | None,
    local_asn_source: str | None,
) -> bool:
    # The current EB inventory ASN identifies the physical fixture, while the
    # fetched routing artifact owns the protocol-local ASN.
    return (
        local_network_role is NetworkRole.EB
        and local_asn_source == "physical_inventory.dut_bgp_as"
    )


def _record_duplicate_ips(
    bound_ips: dict[str, tuple[str, str]],
    dg_name: str,
    ips: t.Iterable[str],
    path: str,
    *,
    generated: bool,
    issues: list[ValidationIssue],
) -> None:
    current_dg_ips: set[str] = set()
    source = "generated" if generated else "explicit"
    for ip in ips:
        if ip in current_dg_ips:
            issues.append(
                ValidationIssue(
                    path=path,
                    code=f"duplicate_{source}_ip",
                    message=f"{source} IP {ip} appears more than once in {dg_name}",
                )
            )
            continue
        current_dg_ips.add(ip)
        if ip in bound_ips:
            existing_dg_name, existing_source = bound_ips[ip]
            issues.append(
                ValidationIssue(
                    path=path,
                    code=f"duplicate_{source}_ip",
                    message=(
                        f"{source} IP {ip} also appears as {existing_source} IP "
                        f"in {existing_dg_name}"
                    ),
                )
            )
        else:
            bound_ips[ip] = (dg_name, source)


def _resolve_peer_cidrs(
    *,
    peer_cidrs: list[tuple[_IPNetwork, str, str]],
    dg_name: str,
    a_ips: tuple[str, ...],
    z_ips: tuple[str, ...],
    address_plan: AddressPlan,
    afi: str,
    path: str,
    generated: bool,
    issues: list[ValidationIssue],
) -> tuple[ResolvedPeer, ...]:
    if len(a_ips) != len(z_ips):
        issues.append(
            ValidationIssue(
                path=f"{path}.peer_cidrs",
                code="peer_cidr_count_mismatch",
                message=(
                    "cannot build peer CIDRs from mismatched A/Z IP counts: "
                    f"{len(a_ips)} A-side, {len(z_ips)} Z-side"
                ),
            )
        )
        return ()
    prefix_length = _effective_peer_prefix_length(
        address_plan,
        afi,
        generated,
        path,
        issues,
    )
    if prefix_length is None:
        return tuple(
            ResolvedPeer(a_ip=a_ip, z_ip=z_ip, peer_cidr=None)
            for a_ip, z_ip in zip(a_ips, z_ips, strict=True)
        )
    if generated:
        _validate_generated_peer_stride(
            address_plan,
            afi,
            prefix_length,
            path,
            issues,
        )

    resolved_peers: list[ResolvedPeer] = []
    for index, (a_ip, z_ip) in enumerate(zip(a_ips, z_ips, strict=True)):
        peer_cidr = _peer_cidr_for_pair(
            a_ip,
            z_ip,
            prefix_length,
            f"{path}.z_ips[{index}]",
            issues,
        )
        if peer_cidr is not None:
            _record_peer_cidr(
                peer_cidrs,
                peer_cidr,
                dg_name,
                f"{path}.peer_cidrs[{index}]",
                issues,
            )
        resolved_peers.append(
            ResolvedPeer(
                a_ip=a_ip,
                z_ip=z_ip,
                peer_cidr=str(peer_cidr) if peer_cidr is not None else None,
            )
        )
    return tuple(resolved_peers)


def _effective_peer_prefix_length(
    address_plan: AddressPlan,
    afi: str,
    generated: bool,
    path: str,
    issues: list[ValidationIssue],
) -> int | None:
    if address_plan.prefix_length is not None:
        return _validate_peer_prefix_length(
            address_plan.prefix_length,
            afi,
            f"{path}.prefix_length",
            issues,
        )
    if address_plan.mask is not None:
        try:
            parsed_mask = int(address_plan.mask)
        except (TypeError, ValueError):
            issues.append(
                ValidationIssue(
                    path=f"{path}.mask",
                    code="invalid_prefix_length",
                    message="mask must be numeric",
                )
            )
            return None
        return _validate_peer_prefix_length(
            parsed_mask,
            afi,
            f"{path}.mask",
            issues,
        )
    if not generated:
        return None
    return 31 if afi == "v4" else 127


def _validate_peer_prefix_length(
    prefix_length: t.Any,
    afi: str,
    path: str,
    issues: list[ValidationIssue],
) -> int | None:
    max_prefix = 32 if afi == "v4" else 128
    if (
        isinstance(prefix_length, bool)
        or not isinstance(prefix_length, int)
        or prefix_length < 0
        or prefix_length > max_prefix
    ):
        issues.append(
            ValidationIssue(
                path=path,
                code="invalid_prefix_length",
                message=f"prefix_length must be between 0 and {max_prefix}",
            )
        )
        return None
    return prefix_length


def _validate_generated_peer_stride(
    address_plan: AddressPlan,
    afi: str,
    prefix_length: int,
    address_plan_path: str,
    issues: list[ValidationIssue],
) -> None:
    step_value, step_attr = _address_plan_step(address_plan)
    try:
        stride = _offset_to_int(step_value, default=2)
    except ValueError:
        issues.append(
            ValidationIssue(
                path=f"{address_plan_path}.{step_attr}",
                code="invalid_stride_value",
                message=f"{step_attr} value must be a valid integer or IP address offset",
            )
        )
        return
    if stride <= 0:
        return

    subnet_size = 1 << ((32 if afi == "v4" else 128) - prefix_length)
    if stride < subnet_size:
        issues.append(
            ValidationIssue(
                path=f"{address_plan_path}.{step_attr}",
                code="incompatible_peer_subnet_stride",
                message=(
                    f"{step_attr} {stride} is smaller than /{prefix_length} "
                    f"peer subnet size {subnet_size}"
                ),
            )
        )


def _peer_cidr_for_pair(
    a_ip: str,
    z_ip: str,
    prefix_length: int,
    path: str,
    issues: list[ValidationIssue],
) -> _IPNetwork | None:
    try:
        a_network = ipaddress.ip_interface(f"{a_ip}/{prefix_length}").network
        z_network = ipaddress.ip_interface(f"{z_ip}/{prefix_length}").network
    except ValueError as error:
        issues.append(
            ValidationIssue(
                path=path,
                code="invalid_peer_cidr",
                message=str(error),
            )
        )
        return None
    if a_network != z_network:
        issues.append(
            ValidationIssue(
                path=path,
                code="peer_cidr_mismatch",
                message=(
                    f"A/Z peer addresses {a_ip} and {z_ip} are not in "
                    f"the same /{prefix_length} CIDR"
                ),
            )
        )
        return None
    return a_network


def _record_peer_cidr(
    peer_cidrs: list[tuple[_IPNetwork, str, str]],
    peer_cidr: _IPNetwork,
    dg_name: str,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    for existing_cidr, existing_dg, existing_path in peer_cidrs:
        if peer_cidr.version == existing_cidr.version and peer_cidr.overlaps(
            existing_cidr
        ):
            issues.append(
                ValidationIssue(
                    path=path,
                    code="peer_cidr_overlap",
                    message=(
                        f"peer CIDR {peer_cidr} for {dg_name} overlaps "
                        f"{existing_cidr} from {existing_dg} at {existing_path}"
                    ),
                )
            )
            return
    peer_cidrs.append((peer_cidr, dg_name, path))


def _validate_bound_ip_count(
    ips: tuple[str, ...],
    peer_count: int,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    if len(ips) != peer_count:
        issues.append(
            ValidationIssue(
                path=path,
                code="ip_count_mismatch",
                message=f"expected {peer_count} IPs, got {len(ips)}",
            )
        )


def _validate_eos_secondary_ip_limits(
    bound_dgs: t.Sequence[BoundDeviceGroup],
    issues: list[ValidationIssue],
) -> None:
    counts: dict[tuple[str, str], int] = {}
    sources: dict[tuple[str, str], list[str]] = {}

    for dg in bound_dgs:
        _record_eos_secondary_ip_count(
            interface=dg.a_interface,
            endpoint_os=dg.a_os,
            afi=dg.afi,
            ips=dg.a_ips,
            dg_name=dg.name,
            counts=counts,
            sources=sources,
        )
        _record_eos_secondary_ip_count(
            interface=dg.z_interface,
            endpoint_os=dg.z_os,
            afi=dg.afi,
            ips=dg.z_ips,
            dg_name=dg.name,
            counts=counts,
            sources=sources,
        )

    for interface, afi in sorted(counts):
        count = counts[(interface, afi)]
        if count <= _EOS_SECONDARY_IP_LIMIT_PER_INTERFACE_AFI:
            continue
        issues.append(
            ValidationIssue(
                path=f"interfaces[{interface}].{afi}",
                code="eos_secondary_ip_limit_exceeded",
                message=(
                    f"EOS interface {interface} has {count} {afi} DUT-side "
                    f"peer IPs across device groups "
                    f"{', '.join(sources[(interface, afi)])}; limit is "
                    f"{_EOS_SECONDARY_IP_LIMIT_PER_INTERFACE_AFI}"
                ),
                hint=(
                    "Split peers across additional interfaces or reduce peer_count "
                    "so one EOS interface/AFI stays within the platform limit."
                ),
            )
        )


def _record_eos_secondary_ip_count(
    *,
    interface: str | None,
    endpoint_os: str | None,
    afi: str,
    ips: tuple[str, ...],
    dg_name: str,
    counts: dict[tuple[str, str], int],
    sources: dict[tuple[str, str], list[str]],
) -> None:
    if endpoint_os != "eos" or not interface or not ips:
        return
    key = (interface, afi)
    counts[key] = counts.get(key, 0) + len(ips)
    sources.setdefault(key, []).append(dg_name)


def _merge_device_config(
    base: RoutingDeviceConfig,
    override: RoutingDeviceConfig | None,
) -> RoutingDeviceConfig:
    if override is None:
        return base

    defaults = RoutingDeviceConfig()
    overridden_fields = frozenset(
        getattr(override, _DEVICE_CONFIG_OVERRIDDEN_FIELDS_ATTR, ())
    )
    values = {}
    for config_field in _DEVICE_CONFIG_FIELDS:
        value = getattr(override, config_field.name)
        if config_field.name in overridden_fields or value != getattr(
            defaults, config_field.name
        ):
            values[config_field.name] = value
    if not values:
        return base
    return replace(base, **values)


def _effective_openr_inputs(
    device_config: RoutingDeviceConfig,
    physical_inventory: t.Any,
) -> dict[str, t.Any]:
    return {
        "openr_configerator_path": (
            device_config.openr_configerator_path
            or getattr(physical_inventory, "openr_configerator_path", None)
        ),
        "openr_standalone_link": (
            device_config.openr_standalone_link
            or getattr(physical_inventory, "openr_standalone_link", None)
        ),
    }


def _validate_openr_standalone_inputs(
    device_config: RoutingDeviceConfig,
    physical_inventory: t.Any,
    issues: list[ValidationIssue],
) -> None:
    if device_config.openr_mode is not OpenRMode.STANDALONE:
        return
    effective_inputs = _effective_openr_inputs(device_config, physical_inventory)
    for field_name, effective_value in effective_inputs.items():
        if effective_value:
            continue
        issues.append(
            ValidationIssue(
                path=f"device_config.{field_name}",
                code="missing_openr_standalone_input",
                message=(
                    "OpenR STANDALONE mode requires "
                    f"{field_name} from device config or PhysicalInventory"
                ),
            )
        )
    link = effective_inputs.get("openr_standalone_link")
    device_name = getattr(physical_inventory, "device_name", None)
    if link is not None and link.owner.hostname != device_name:
        issues.append(
            ValidationIssue(
                path="device_config.openr_standalone_link.owner.hostname",
                code="invalid_openr_standalone_owner",
                message=(
                    "OpenR standalone link owner must match PhysicalInventory; "
                    f"got {link.owner.hostname!r} for {device_name!r}"
                ),
            )
        )


def _parse_parent_base(parent_network: str, afi: str) -> _IPAddress:
    if afi == "v4":
        network = parent_network
        if "/" in network:
            return ipaddress.ip_network(network, strict=False).network_address
        if network.count(".") == 2:
            network = f"{network}.0"
        return ipaddress.IPv4Address(network)
    if "/" in parent_network:
        return ipaddress.ip_network(parent_network, strict=False).network_address
    if "::" not in parent_network and parent_network.count(":") < 7:
        parent_network = f"{parent_network}::"
    return ipaddress.IPv6Address(parent_network)


def _offset_to_int(value: int | str | None, *, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    try:
        return int(ipaddress.ip_address(value))
    except ValueError:
        return int(value, 0)


def _address_plan_step(address_plan: AddressPlan) -> tuple[int | str | None, str]:
    if address_plan.increment is not None:
        return address_plan.increment, "increment"
    return address_plan.stride, "stride"


def _default_routing_driver(endpoint_os: str | None) -> str | None:
    if endpoint_os == "eos":
        return "bgpcpp"
    if endpoint_os == "fboss":
        return "fboss"
    return None


def _base_role(role: str) -> str:
    return role.split("_", 1)[0]


def _endpoint_is_dut(endpoint: EndpointSpec) -> bool:
    return endpoint.role == "dut" or (
        endpoint.kind == "dut" and endpoint.role not in _TRAFFIC_ENDPOINT_ROLES
    )


def _endpoint_is_ixia(endpoint: EndpointSpec | None) -> bool:
    return endpoint is not None and (
        endpoint.role in _TRAFFIC_ENDPOINT_ROLES
        or (endpoint.kind in _TRAFFIC_ENDPOINT_KINDS and endpoint.role != "dut")
    )


def _normalize_backend(
    value: str,
    path: str,
    attr: str,
    issues: list[ValidationIssue],
) -> str:
    normalized = value.lower()
    matches: list[str] = []
    if "fboss" in normalized:
        matches.append("fboss")
    if "eos" in normalized or "arista" in normalized:
        matches.append("eos")
    if "ixia" in normalized:
        matches.append("ixia")
    if len(matches) > 1:
        issues.append(
            ValidationIssue(
                path=path,
                code="ambiguous_physical_inventory_backend",
                message=(
                    f"PhysicalInventory.{attr} value {value!r} matches multiple backend "
                    f"families: {', '.join(matches)}"
                ),
            )
        )
        return "unknown"
    if matches:
        return matches[0]
    return "unknown"
