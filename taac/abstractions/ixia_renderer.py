# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

import ipaddress
import typing as t
from dataclasses import dataclass
from enum import Enum

from ixia.ixia import types as ixia_types
from taac.abstractions.compilation.ixia_presentation import (
    IxiaAdvertisementPresentation,
    IxiaDeviceGroupPresentation,
    IxiaPortPresentation,
    IxiaPresentationError,
    IxiaSessionPresentation,
    resolve_ixia_advertisement_presentation,
    resolve_ixia_device_group_presentation,
    resolve_ixia_port_presentations,
    resolve_ixia_session_presentation,
)
from taac.abstractions.compilation.legacy_ixia_identity import (
    LegacyIxiaGroupIdentity,
    LegacyIxiaIdentitySidecar,
    LegacyIxiaSessionIdentity,
)
from taac.abstractions.compilation.model import (
    AddressFamily,
    IxiaAdvertisementPlan,
    IxiaBgpSessionPlan,
    IxiaDeviceGroupPlan,
    IxiaNextHopDistribution,
    IxiaNextHopMode,
    IxiaPeerPrefixDistribution,
    IxiaPortPlan,
    IxiaRouteAttributeDistribution,
    IxiaRouteScaleMode,
    IxiaSelfNextHopRealization,
    ResourceId,
)
from taac.abstractions.compilation.traffic_generator import (
    TrafficGeneratorDeviceGroupConfigFragment,
    TrafficGeneratorDirectConnectionFragment,
    TrafficGeneratorEndpointPatch,
    TrafficGeneratorEndpointRenderRequest,
    TrafficGeneratorEndpointRenderResult,
    TrafficGeneratorIxiaPortFragment,
    TrafficGeneratorLifecycleFragment,
    TrafficGeneratorLifecycleSlot,
    TrafficGeneratorPortBaseFragment,
    TrafficGeneratorPortBaseRenderRequest,
    TrafficGeneratorPortBaseRenderResult,
    TrafficGeneratorPortDeviceGroupFragment,
    TrafficGeneratorPortDeviceGroupRenderRequest,
    TrafficGeneratorPortDeviceGroupRenderResult,
    TrafficGeneratorRenderRequest,
    TrafficGeneratorRenderResult,
)
from taac.abstractions.ixia_semantics import IxiaBgpCapability
from taac.abstractions.routing_semantics import PeerRelationship
from taac.task_definitions import create_invoke_ixia_api_task
from taac.test_as_a_config import types as taac_types


class UnsupportedIxiaRenderingError(ValueError):
    pass


class _IxiaRenderingCapability(str, Enum):
    INITIAL_IPV6 = "initial_ipv6"
    COMPACT_NAMED_IPV6 = "compact_named_ipv6"
    PARTITIONED_DUAL_STACK = "partitioned_dual_stack"
    PARTITIONED_DUAL_STACK_WITH_MONITOR = "partitioned_dual_stack_with_monitor"


_MONITOR_BGP_CAPABILITIES = (
    IxiaBgpCapability.IPV6_UNICAST,
    IxiaBgpCapability.IPV4_UNICAST,
    IxiaBgpCapability.IPV4_UNICAST_ADD_PATH,
    IxiaBgpCapability.IPV6_UNICAST_ADD_PATH,
    IxiaBgpCapability.NEXT_HOP_ENCODING,
)


_PEER_PAIR_PREFIX_LENGTH_BY_CAPABILITY = {
    _IxiaRenderingCapability.INITIAL_IPV6: 127,
    _IxiaRenderingCapability.COMPACT_NAMED_IPV6: 127,
}


@dataclass(frozen=True)
class SharedIxiaEndpointRenderer:
    """Lowers IXIA-owned endpoint fields independently of session capabilities."""

    def render(
        self,
        request: TrafficGeneratorEndpointRenderRequest,
    ) -> TrafficGeneratorEndpointRenderResult:
        endpoint_patches = tuple(
            _endpoint_patch(request, activation.endpoint_id)
            for activation in request.endpoint_activations
            if activation.emit_endpoint_patch
        )
        result = TrafficGeneratorEndpointRenderResult(
            consumed_endpoint_ids=tuple(
                activation.endpoint_id for activation in request.endpoint_activations
            ),
            consumed_port_ids=tuple(
                port_request.port.resource_id for port_request in request.ports
            ),
            endpoint_patches=endpoint_patches,
        )
        result.validate(request)
        return result


@dataclass(frozen=True)
class SharedIxiaPortBaseRenderer:
    """Lowers the BasicPortConfig endpoint field from normalized IXIA ports."""

    def render(
        self,
        request: TrafficGeneratorPortBaseRenderRequest,
    ) -> TrafficGeneratorPortBaseRenderResult[taac_types.BasicPortConfig]:
        fragments = tuple(_port_base_fragment(port) for port in request.active_ports())
        result = TrafficGeneratorPortBaseRenderResult(
            consumed_port_ids=tuple(port.resource_id for port in request.ports),
            fragments=fragments,
        )
        result.validate(request)
        return result


@dataclass(frozen=True)
class SharedIxiaPortDeviceGroupRenderer:
    """Lowers supported IXIA device-group bodies by normalized port ID."""

    def render(
        self,
        request: TrafficGeneratorPortDeviceGroupRenderRequest,
    ) -> TrafficGeneratorPortDeviceGroupRenderResult[taac_types.DeviceGroupConfig]:
        capability = _validated_capability(request)
        fragments = tuple(
            _port_device_group_fragment(request, port, capability)
            for port in request.active_ports()
        )
        result = TrafficGeneratorPortDeviceGroupRenderResult(
            referenced_resource_ids=request.plan.iter_resource_ids(),
            fragments=fragments,
        )
        result.validate(request)
        return result


@dataclass(frozen=True)
class SharedIxiaRenderer:
    """Lowers capability-supported IXIA semantics without DUT-platform input."""

    def render(
        self,
        request: TrafficGeneratorRenderRequest,
    ) -> TrafficGeneratorRenderResult:
        capability = _validated_capability(request)
        activation_by_endpoint = {
            activation.endpoint_id: activation
            for activation in request.endpoint_activations
        }
        basic_port_configs = tuple(
            _basic_port_config(request, port, capability)
            for port in request.plan.ports
            if activation_by_endpoint[port.dut_endpoint_id].emit_basic_port_configs
        )
        endpoint_patches = tuple(
            _full_renderer_endpoint_patch(
                request,
                activation.endpoint_id,
                capability,
            )
            for activation in request.endpoint_activations
            if activation.emit_endpoint_patch
        )
        result = TrafficGeneratorRenderResult(
            consumed_resource_ids=request.plan.iter_resource_ids(),
            basic_port_configs=basic_port_configs,
            endpoint_patches=endpoint_patches,
            lifecycle_fragments=_traffic_generator_lifecycle_fragments(
                request,
                capability,
            ),
        )
        result.validate(request)
        return result


def _traffic_generator_lifecycle_fragments(
    request: TrafficGeneratorRenderRequest,
    capability: _IxiaRenderingCapability,
) -> tuple[TrafficGeneratorLifecycleFragment, ...]:
    lifecycle_is_active = any(
        activation.emit_lifecycle for activation in request.endpoint_activations
    )
    requires_configuration = lifecycle_is_active and any(
        advertisement.prefix_window.route_scale_mode is IxiaRouteScaleMode.FLAT
        or advertisement.requires_route_mutation
        for advertisement in request.plan.advertisements
    )
    if not requires_configuration:
        return ()
    if not _is_partitioned_dual_stack_capability(capability):
        _unsupported("formulaic IXIA route setup requires partitioned dual-stack")
    return (
        TrafficGeneratorLifecycleFragment(
            slot=TrafficGeneratorLifecycleSlot.CONFIGURATION,
            tasks=(
                create_invoke_ixia_api_task(
                    api_name="configure_formulaic_bgp_routes",
                    args_dict={"mutations": _partitioned_route_mutations(request)},
                ),
            ),
        ),
    )


def _port_base_fragment(
    port: IxiaPortPlan,
) -> TrafficGeneratorPortBaseFragment[taac_types.BasicPortConfig]:
    physical_endpoint = f"{port.dut_physical_identifier}:{port.dut_interface}"
    basic_port_config = taac_types.BasicPortConfig(endpoint=physical_endpoint)
    if (
        basic_port_config.l1_config is not None
        or basic_port_config.device_group_configs is not None
    ):
        raise RuntimeError("BasicPortConfig base overlaps unowned IXIA fields")
    return TrafficGeneratorPortBaseFragment(
        port_id=port.resource_id,
        dut_endpoint_id=port.dut_endpoint_id,
        physical_endpoint=physical_endpoint,
        basic_port_config=basic_port_config,
    )


def _port_device_group_fragment(
    request: TrafficGeneratorRenderRequest,
    port: IxiaPortPlan,
    capability: _IxiaRenderingCapability,
) -> TrafficGeneratorPortDeviceGroupFragment[taac_types.DeviceGroupConfig]:
    groups = _capability_port_groups(request, port, capability)
    sessions_by_group = _sessions_by_group(request)
    return TrafficGeneratorPortDeviceGroupFragment(
        port_id=port.resource_id,
        device_groups=tuple(
            TrafficGeneratorDeviceGroupConfigFragment(
                device_group_id=group.resource_id,
                session_id=sessions_by_group[group.resource_id].resource_id,
                advertisement_ids=tuple(
                    advertisement.resource_id
                    for advertisement in request.plan.advertisements
                    if advertisement.device_group_id == group.resource_id
                ),
                device_group_config=_device_group_config(
                    request,
                    group,
                    capability,
                ),
            )
            for group in groups
        ),
    )


def _validated_capability(
    request: TrafficGeneratorRenderRequest,
) -> _IxiaRenderingCapability:
    capability = _select_capability(request)
    _validate_capability(request, capability)
    return capability


def _validate_capability(
    request: TrafficGeneratorRenderRequest,
    capability: _IxiaRenderingCapability,
) -> None:
    if capability is _IxiaRenderingCapability.INITIAL_IPV6:
        _validate_initial_ipv6_capability(request)
    elif capability is _IxiaRenderingCapability.COMPACT_NAMED_IPV6:
        _validate_compact_named_ipv6_capability(request)
    else:
        _validate_partitioned_dual_stack_capability(
            request,
            include_monitor=(
                capability
                is _IxiaRenderingCapability.PARTITIONED_DUAL_STACK_WITH_MONITOR
            ),
        )


def _select_capability(
    request: TrafficGeneratorRenderRequest,
) -> _IxiaRenderingCapability:
    session_shapes = frozenset(
        (session.capabilities, session.address_prefix_length)
        for session in request.plan.bgp_sessions
    )
    if session_shapes == {
        ((IxiaBgpCapability.IPV6_UNICAST,), 127),
    }:
        return _IxiaRenderingCapability.INITIAL_IPV6
    if session_shapes == {
        (
            (
                IxiaBgpCapability.IPV4_UNICAST,
                IxiaBgpCapability.IPV6_UNICAST,
            ),
            64,
        ),
    }:
        return _IxiaRenderingCapability.COMPACT_NAMED_IPV6
    partitioned_dual_stack_shapes = {
        ((IxiaBgpCapability.IPV6_UNICAST,), 64),
        ((IxiaBgpCapability.IPV4_UNICAST,), 31),
    }
    if session_shapes == partitioned_dual_stack_shapes:
        return _IxiaRenderingCapability.PARTITIONED_DUAL_STACK
    if session_shapes == partitioned_dual_stack_shapes | {
        (_MONITOR_BGP_CAPABILITIES, 64),
    }:
        return _IxiaRenderingCapability.PARTITIONED_DUAL_STACK_WITH_MONITOR
    _unsupported("IXIA plan is outside the shared renderer semantic capabilities")


def _is_partitioned_dual_stack_capability(
    capability: _IxiaRenderingCapability,
) -> bool:
    return capability in {
        _IxiaRenderingCapability.PARTITIONED_DUAL_STACK,
        _IxiaRenderingCapability.PARTITIONED_DUAL_STACK_WITH_MONITOR,
    }


def _validate_initial_ipv6_capability(
    request: TrafficGeneratorRenderRequest,
) -> None:
    sessions_by_group = _sessions_by_group(request)
    _resolved_port_presentations(request)
    for port in request.plan.ports:
        _validate_unique_group_indices(request, port)
    for group in request.plan.device_groups:
        if group.afi is not AddressFamily.IPV6:
            _unsupported(
                f"IXIA group {group.resource_id} is outside the initial IPv6 capability"
            )
        if group.peer_start_index != 0:
            _unsupported(f"IXIA group {group.resource_id} has unsupported peer slicing")
        session = sessions_by_group.get(group.resource_id)
        if session is None:
            _unsupported(f"IXIA group {group.resource_id} has no BGP session")
        _validate_initial_ipv6_session(group, session)
        _validate_tag_identity(request.legacy_identity, group, session)
    for advertisement in request.plan.advertisements:
        group = next(
            group
            for group in request.plan.device_groups
            if group.resource_id == advertisement.device_group_id
        )
        _validate_initial_ipv6_advertisement(
            request.legacy_identity,
            group,
            advertisement,
        )


def _validate_compact_named_ipv6_capability(
    request: TrafficGeneratorRenderRequest,
) -> None:
    _validate_compact_shape_and_activation(request)
    sessions_by_group = _sessions_by_group(request)
    ordered_groups = _compact_ordered_groups(request)
    groups_by_relationship = _compact_groups_by_relationship(
        request,
        sessions_by_group,
    )
    _validate_compact_relationship_geometry(
        request,
        sessions_by_group,
        ordered_groups,
        groups_by_relationship,
    )


def _validate_compact_shape_and_activation(
    request: TrafficGeneratorRenderRequest,
) -> None:
    if (
        len(request.plan.ports) != 2
        or len(request.plan.device_groups) != 2
        or len(request.plan.bgp_sessions) != 2
        or len(request.plan.advertisements) != 1
    ):
        _unsupported("compact named IPv6 lowering requires its two-group shape")
    if any(
        not activation.emit_endpoint_patch or not activation.emit_basic_port_configs
        for activation in request.endpoint_activations
    ):
        _unsupported(
            "compact named IPv6 lowering does not support suppressed realization"
        )


def _compact_ordered_groups(
    request: TrafficGeneratorRenderRequest,
) -> tuple[IxiaDeviceGroupPlan, ...]:
    ordered_groups: list[IxiaDeviceGroupPlan] = []
    presentations_by_port_id = _resolved_port_presentations(request)
    for port in request.plan.ports:
        if (
            presentations_by_port_id[port.resource_id].endpoint_ixia_port_label
            != port.dut_interface
        ):
            _unsupported(
                f"IXIA port {port.resource_id} requires DUT-interface presentation"
            )
        groups = tuple(
            group
            for group in request.plan.device_groups
            if group.port_id == port.resource_id
        )
        if len(groups) != 1:
            _unsupported(
                f"IXIA port {port.resource_id} requires exactly one device group"
            )
        ordered_groups.append(groups[0])
        _validate_unique_group_indices(request, port)
    return tuple(ordered_groups)


def _compact_groups_by_relationship(
    request: TrafficGeneratorRenderRequest,
    sessions_by_group: dict[ResourceId, IxiaBgpSessionPlan],
) -> dict[PeerRelationship, IxiaDeviceGroupPlan]:
    groups_by_relationship: dict[PeerRelationship, IxiaDeviceGroupPlan] = {}
    for group in request.plan.device_groups:
        if group.afi is not AddressFamily.IPV6 or group.peer_start_index != 0:
            _unsupported(
                f"IXIA group {group.resource_id} is outside compact named IPv6 lowering"
            )
        session = sessions_by_group.get(group.resource_id)
        if session is None:
            _unsupported(f"IXIA group {group.resource_id} has no BGP session")
        if session.relationship in groups_by_relationship:
            _unsupported(
                "compact named IPv6 lowering requires one internal and one "
                "external group"
            )
        groups_by_relationship[session.relationship] = group
        _validate_compact_named_ipv6_session(group, session)
        _validate_named_identity(request.legacy_identity, group, session)
    return groups_by_relationship


def _validate_compact_relationship_geometry(
    request: TrafficGeneratorRenderRequest,
    sessions_by_group: dict[ResourceId, IxiaBgpSessionPlan],
    ordered_groups: tuple[IxiaDeviceGroupPlan, ...],
    groups_by_relationship: dict[PeerRelationship, IxiaDeviceGroupPlan],
) -> None:
    if set(groups_by_relationship) != {
        PeerRelationship.EXTERNAL,
        PeerRelationship.INTERNAL,
    }:
        _unsupported(
            "compact named IPv6 lowering requires one internal and one external group"
        )
    if tuple(
        sessions_by_group[group.resource_id].relationship for group in ordered_groups
    ) != (PeerRelationship.INTERNAL, PeerRelationship.EXTERNAL) or tuple(
        session.relationship for session in request.plan.bgp_sessions
    ) != (
        PeerRelationship.INTERNAL,
        PeerRelationship.EXTERNAL,
    ):
        _unsupported(
            "compact named IPv6 lowering requires internal then external ordering"
        )
    internal = groups_by_relationship[PeerRelationship.INTERNAL]
    external = groups_by_relationship[PeerRelationship.EXTERNAL]
    if internal.peer_count != 1 or external.peer_count != 10:
        _unsupported("compact named IPv6 lowering requires 1 internal and 10 peers")
    if any(
        advertisement.device_group_id == internal.resource_id
        for advertisement in request.plan.advertisements
    ):
        _unsupported("compact named IPv6 internal group must not advertise routes")
    advertisement = request.plan.advertisements[0]
    if advertisement.device_group_id != external.resource_id:
        _unsupported("compact named IPv6 routes must belong to the external group")
    _validate_compact_named_ipv6_advertisement(
        request.legacy_identity,
        advertisement,
    )


def _validate_partitioned_dual_stack_capability(
    request: TrafficGeneratorRenderRequest,
    *,
    include_monitor: bool,
) -> None:
    expected_port_count = 3 if include_monitor else 2
    if (
        len(request.plan.ports) != expected_port_count
        or not request.plan.device_groups
        or len(request.plan.bgp_sessions) != len(request.plan.device_groups)
        or any(
            not activation.emit_basic_port_configs
            for activation in request.endpoint_activations
        )
    ):
        _unsupported(
            "partitioned dual-stack lowering requires "
            f"{expected_port_count} active ports and one session per group"
        )
    sessions_by_group = _sessions_by_group(request)
    if tuple(session.device_group_id for session in request.plan.bgp_sessions) != tuple(
        group.resource_id for group in request.plan.device_groups
    ):
        _unsupported("partitioned dual-stack sessions must follow group plan order")
    mutation_group_ids = frozenset(
        advertisement.device_group_id
        for advertisement in request.plan.advertisements
        if advertisement.requires_route_mutation
    )
    groups_by_relationship = _partitioned_groups_by_relationship(
        request,
        sessions_by_group,
        include_monitor=include_monitor,
        mutation_group_ids=mutation_group_ids,
    )
    for relationship, groups in groups_by_relationship.items():
        if relationship is PeerRelationship.MONITOR:
            _validate_partitioned_monitor_group(request, groups)
        else:
            _validate_partitioned_peer_windows(
                groups,
                sessions_by_group,
                relationship,
                mutation_group_ids,
            )
    _validate_partitioned_advertisements(request, sessions_by_group)
    _validate_partitioned_presentation_uniqueness(request)


def _partitioned_groups_by_relationship(
    request: TrafficGeneratorRenderRequest,
    sessions_by_group: dict[ResourceId, IxiaBgpSessionPlan],
    *,
    include_monitor: bool,
    mutation_group_ids: frozenset[ResourceId],
) -> dict[PeerRelationship, tuple[IxiaDeviceGroupPlan, ...]]:
    groups_by_relationship: dict[
        PeerRelationship,
        tuple[IxiaDeviceGroupPlan, ...],
    ] = {}
    for port in request.plan.ports:
        groups = _plan_order_port_groups(request, port)
        if not groups:
            _unsupported(f"IXIA port {port.resource_id} has no device groups")
        relationships = {
            sessions_by_group[group.resource_id].relationship for group in groups
        }
        if len(relationships) != 1:
            _unsupported(f"IXIA port {port.resource_id} mixes peer relationships")
        relationship = next(iter(relationships))
        allowed_relationships = {
            PeerRelationship.EXTERNAL,
            PeerRelationship.INTERNAL,
        }
        if include_monitor:
            allowed_relationships.add(PeerRelationship.MONITOR)
        if (
            relationship not in allowed_relationships
            or relationship in groups_by_relationship
        ):
            _unsupported(
                "partitioned dual-stack lowering requires one port per supported "
                "peer relationship"
            )
        _validate_unique_partitioned_group_indices(request, port)
        for group in groups:
            session = sessions_by_group[group.resource_id]
            _validate_partitioned_session(
                group,
                session,
                relationship,
                requires_route_mutation=group.resource_id in mutation_group_ids,
            )
            _validate_partitioned_named_identity(
                request,
                group,
                session,
            )
        groups_by_relationship[relationship] = groups
    expected_relationships = {
        PeerRelationship.EXTERNAL,
        PeerRelationship.INTERNAL,
    }
    if include_monitor:
        expected_relationships.add(PeerRelationship.MONITOR)
    if set(groups_by_relationship) != expected_relationships:
        _unsupported("partitioned dual-stack lowering has the wrong peer relationships")
    return groups_by_relationship


def _validate_partitioned_monitor_group(
    request: TrafficGeneratorRenderRequest,
    groups: tuple[IxiaDeviceGroupPlan, ...],
) -> None:
    if (
        len(groups) != 1
        or groups[0].afi is not AddressFamily.IPV6
        or groups[0].peer_start_index != 0
        or any(
            advertisement.device_group_id == groups[0].resource_id
            for advertisement in request.plan.advertisements
        )
    ):
        _unsupported(
            "partitioned dual-stack monitor lowering requires one route-free IPv6 group"
        )


def _validate_partitioned_peer_windows(
    groups: tuple[IxiaDeviceGroupPlan, ...],
    sessions_by_group: dict[ResourceId, IxiaBgpSessionPlan],
    relationship: PeerRelationship,
    mutation_group_ids: frozenset[ResourceId],
) -> None:
    if {group.afi for group in groups} != {AddressFamily.IPV4, AddressFamily.IPV6}:
        _unsupported(f"partitioned {relationship.value} groups require IPv4 and IPv6")
    for afi in (AddressFamily.IPV6, AddressFamily.IPV4):
        parent_networks = {group.parent_network for group in groups if group.afi is afi}
        for parent_network in parent_networks:
            windows = sorted(
                (
                    _partitioned_peer_window(
                        group,
                        sessions_by_group[group.resource_id],
                        requires_route_mutation=(
                            group.resource_id in mutation_group_ids
                        ),
                    )
                    for group in groups
                    if group.afi is afi and group.parent_network == parent_network
                ),
                key=lambda window: (window[0], window[1]),
            )
            if windows[0][0] != 0:
                _unsupported(
                    f"partitioned {relationship.value} {afi.value} peer windows "
                    f"for {parent_network!r} must start at zero"
                )
            for (_, previous_end, _), (start, _, resource_id) in zip(
                windows,
                windows[1:],
            ):
                if start < previous_end:
                    _unsupported(
                        f"IXIA group {resource_id} has an overlapping peer window"
                    )


def _partitioned_peer_window(
    group: IxiaDeviceGroupPlan,
    session: IxiaBgpSessionPlan,
    *,
    requires_route_mutation: bool,
) -> tuple[int, int, ResourceId]:
    # Zero is the default in each independent legacy source; a nonzero value
    # identifies the partition origin supplied by that source.
    declared_starts = frozenset(
        start
        for start in (group.peer_start_index, session.address_start_index)
        if start != 0
    )
    if len(declared_starts) > 1:
        _unsupported(
            f"IXIA group {group.resource_id} has conflicting peer window starts"
        )
    if session.address_start_index != 0 and not requires_route_mutation:
        _unsupported(
            f"IXIA session {session.resource_id} is outside partitioned "
            "dual-stack lowering"
        )
    start = next(iter(declared_starts), 0)
    return (
        start,
        start + group.peer_count,
        group.resource_id,
    )


def _validate_partitioned_session(
    group: IxiaDeviceGroupPlan,
    session: IxiaBgpSessionPlan,
    relationship: PeerRelationship,
    *,
    requires_route_mutation: bool,
) -> None:
    expected_capabilities = (
        _MONITOR_BGP_CAPABILITIES
        if relationship is PeerRelationship.MONITOR
        else (
            (
                IxiaBgpCapability.IPV4_UNICAST
                if group.afi is AddressFamily.IPV4
                else IxiaBgpCapability.IPV6_UNICAST
            ),
        )
    )
    expected_prefix_length = 31 if group.afi is AddressFamily.IPV4 else 64
    if (
        group.peer_count <= 0
        or group.local_asn is None
        or session.relationship is not relationship
        or session.capabilities != expected_capabilities
        or session.address_prefix_length != expected_prefix_length
        or session.address_step != 2
        or (
            session.address_start_index != 0
            and group.peer_start_index == 0
            and not requires_route_mutation
        )
        or not session.enable_four_byte_local_as
        or session.hold_timer_s != 30
        or session.keepalive_timer_s != 10
        or session.enable_graceful_restart
        is not (relationship is PeerRelationship.EXTERNAL)
        or len(session.local_addresses) != group.peer_count
        or len(session.peer_addresses) != group.peer_count
        or len(session.peer_cidrs) != group.peer_count
    ):
        _unsupported(
            f"IXIA session {session.resource_id} is outside partitioned "
            "dual-stack lowering"
        )
    _validate_partitioned_session_addresses(group, session)


def _validate_partitioned_session_addresses(
    group: IxiaDeviceGroupPlan,
    session: IxiaBgpSessionPlan,
) -> None:
    version = 4 if group.afi is AddressFamily.IPV4 else 6
    peer_prefix_length = 31 if version == 4 else 127
    local_addresses = tuple(
        _required_ip_address(session.resource_id, address, version)
        for address in session.local_addresses
    )
    peer_addresses = tuple(
        _required_ip_address(session.resource_id, address, version)
        for address in session.peer_addresses
    )
    for label, addresses in (("local", local_addresses), ("peer", peer_addresses)):
        start = int(addresses[0])
        if any(
            int(address) != start + session.address_step * ordinal
            for ordinal, address in enumerate(addresses)
        ):
            _unsupported(
                f"IXIA session {session.resource_id} {label} addresses are not an "
                "arithmetic progression"
            )
    for local, peer, peer_cidr in zip(
        local_addresses,
        peer_addresses,
        session.peer_cidrs,
        strict=True,
    ):
        _validate_partitioned_peer_pair(
            session.resource_id,
            local,
            peer,
            peer_cidr,
            version,
            peer_prefix_length,
        )


def _validate_partitioned_peer_pair(
    session_id: ResourceId,
    local: ipaddress.IPv4Address | ipaddress.IPv6Address,
    peer: ipaddress.IPv4Address | ipaddress.IPv6Address,
    peer_cidr: str | None,
    version: int,
    prefix_length: int,
) -> None:
    if peer_cidr is None:
        _unsupported(f"IXIA session {session_id} has no peer CIDR")
    try:
        parsed_cidr = ipaddress.ip_interface(peer_cidr)
    except ValueError:
        _unsupported(f"IXIA session {session_id} has an invalid peer CIDR")
    if (
        parsed_cidr.version != version
        or parsed_cidr.network.prefixlen != prefix_length
        or local == peer
        or local not in parsed_cidr.network
        or peer not in parsed_cidr.network
    ):
        _unsupported(
            f"IXIA session {session_id} addresses do not form a distinct peer pair"
        )


def _required_ip_address(
    resource_id: ResourceId,
    address: str,
    version: int,
    *,
    subject: str = "session",
) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        _unsupported(f"IXIA {subject} {resource_id} contains an invalid address")
    if parsed.version != version:
        _unsupported(f"IXIA {subject} {resource_id} contains the wrong address family")
    return parsed


def _validate_partitioned_advertisements(
    request: TrafficGeneratorRenderRequest,
    sessions_by_group: dict[ResourceId, IxiaBgpSessionPlan],
) -> None:
    actual_group_ids = tuple(
        advertisement.device_group_id for advertisement in request.plan.advertisements
    )
    if len(frozenset(actual_group_ids)) != len(actual_group_ids):
        _unsupported(
            "partitioned dual-stack lowering requires at most one advertisement "
            "per device group"
        )
    groups_by_id = {group.resource_id: group for group in request.plan.device_groups}
    if any(group_id not in groups_by_id for group_id in actual_group_ids):
        _unsupported("partitioned advertisement references an unknown device group")
    for advertisement in request.plan.advertisements:
        relationship = sessions_by_group[advertisement.device_group_id].relationship
        allowed_relationships = {PeerRelationship.EXTERNAL}
        if (
            advertisement.prefix_window.route_scale_mode is IxiaRouteScaleMode.FLAT
            or advertisement.requires_route_mutation
        ):
            allowed_relationships.add(PeerRelationship.INTERNAL)
        if relationship not in allowed_relationships:
            _unsupported(
                f"partitioned {advertisement.prefix_window.route_scale_mode.value} "
                "advertisements have an unsupported peer relationship"
            )
        _validate_partitioned_advertisement(
            groups_by_id[advertisement.device_group_id],
            sessions_by_group[advertisement.device_group_id],
            advertisement,
        )


def _validate_partitioned_advertisement(
    group: IxiaDeviceGroupPlan,
    session: IxiaBgpSessionPlan,
    advertisement: IxiaAdvertisementPlan,
) -> None:
    _validate_partitioned_prefix_window(group, session, advertisement)
    _validate_partitioned_next_hop(group, advertisement)
    _validate_partitioned_route_attributes(advertisement)


def _validate_partitioned_prefix_window(
    group: IxiaDeviceGroupPlan,
    session: IxiaBgpSessionPlan,
    advertisement: IxiaAdvertisementPlan,
) -> None:
    prefix_window = advertisement.prefix_window
    expected_prefix_length = 24 if group.afi is AddressFamily.IPV4 else 64
    address_bits = 32 if group.afi is AddressFamily.IPV4 else 128
    expected_source_step = 1 << (address_bits - expected_prefix_length)
    expected_route_count = (
        prefix_window.prefixes_per_peer
        if prefix_window.peer_distribution is IxiaPeerPrefixDistribution.SHARED
        else group.peer_count * prefix_window.prefixes_per_peer
    )
    if (
        advertisement.afi is not group.afi
        or advertisement.route_count != expected_route_count
        or advertisement.route_count != prefix_window.membership_prefix_count
        or prefix_window.source_step != expected_source_step
        or prefix_window.prefix_length != expected_prefix_length
    ):
        _unsupported(
            f"IXIA advertisement {advertisement.resource_id} is outside "
            "partitioned dual-stack lowering"
        )
    try:
        source_address = ipaddress.ip_address(prefix_window.source_start)
        starting_prefix = ipaddress.ip_address(prefix_window.starting_prefix)
    except ValueError:
        _unsupported(
            f"IXIA advertisement {advertisement.resource_id} has an invalid prefix"
        )
    expected_version = 4 if group.afi is AddressFamily.IPV4 else 6
    candidate_span = prefix_window.source_count + len(
        prefix_window.source_excluded_indices
    )
    expected_start = int(source_address) + expected_source_step * (
        _retained_candidate_index(
            prefix_window.membership_start_index,
            prefix_window.source_excluded_indices,
        )
    )
    if (
        source_address.version != expected_version
        or starting_prefix.version != expected_version
        or int(starting_prefix) != expected_start
    ):
        _unsupported(
            f"IXIA advertisement {advertisement.resource_id} has the wrong family"
        )
    source_value = int(source_address)
    if (
        source_value % expected_source_step != 0
        or source_value + expected_source_step * (candidate_span - 1)
        >= 1 << address_bits
    ):
        _unsupported(
            f"IXIA advertisement {advertisement.resource_id} has invalid prefix "
            "source geometry"
        )
    if prefix_window.route_scale_mode is IxiaRouteScaleMode.WINDOWED:
        if advertisement.requires_route_mutation:
            _validate_mutation_windowed_partitioned_prefix_window(
                group,
                session,
                advertisement,
            )
        else:
            _validate_windowed_partitioned_prefix_window(advertisement)


def _validate_mutation_windowed_partitioned_prefix_window(
    group: IxiaDeviceGroupPlan,
    session: IxiaBgpSessionPlan,
    advertisement: IxiaAdvertisementPlan,
) -> None:
    prefix_window = advertisement.prefix_window
    peer_start_index, _peer_end_index, _resource_id = _partitioned_peer_window(
        group,
        session,
        requires_route_mutation=True,
    )
    expected_membership_start = (
        0
        if prefix_window.peer_distribution is IxiaPeerPrefixDistribution.SHARED
        else peer_start_index * prefix_window.prefixes_per_peer
    )
    if prefix_window.membership_start_index != expected_membership_start:
        _unsupported(
            f"IXIA advertisement {advertisement.resource_id} has unsupported "
            "mutation windowed route geometry"
        )


def _validate_windowed_partitioned_prefix_window(
    advertisement: IxiaAdvertisementPlan,
) -> None:
    prefix_window = advertisement.prefix_window
    if (
        advertisement.route_count != prefix_window.source_count
        or advertisement.route_count != prefix_window.prefixes_per_peer
        or prefix_window.source_excluded_indices
        or prefix_window.membership_start_index != 0
        or prefix_window.membership_prefix_count != prefix_window.source_count
        or prefix_window.starting_prefix != prefix_window.source_start
        or prefix_window.peer_distribution is not IxiaPeerPrefixDistribution.SHARED
        or advertisement.attributes
        or advertisement.policy_communities
    ):
        _unsupported(
            f"IXIA advertisement {advertisement.resource_id} has unsupported "
            "windowed route geometry"
        )


def _retained_candidate_index(
    logical_index: int,
    excluded_indices: tuple[int, ...],
) -> int:
    candidate_index = logical_index
    for excluded_index in sorted(excluded_indices):
        if excluded_index > candidate_index:
            break
        candidate_index += 1
    return candidate_index


def _validate_partitioned_next_hop(
    group: IxiaDeviceGroupPlan,
    advertisement: IxiaAdvertisementPlan,
) -> None:
    next_hop = advertisement.next_hop
    if next_hop.mode is IxiaNextHopMode.SELF:
        if (
            advertisement.prefix_window.route_scale_mode is IxiaRouteScaleMode.WINDOWED
            and next_hop.self_realization
            is not IxiaSelfNextHopRealization.ADVERTISING_SESSION_LOCAL_ADDRESS
        ):
            _unsupported(
                f"IXIA advertisement {advertisement.resource_id} requires a "
                "session-local self next hop"
            )
        return
    if (
        advertisement.prefix_window.route_scale_mode is not IxiaRouteScaleMode.FLAT
        and not advertisement.requires_route_mutation
    ) or next_hop.distribution is None:
        _unsupported(
            f"IXIA advertisement {advertisement.resource_id} has unsupported "
            "next-hop lowering"
        )
    expected_count = _partitioned_next_hop_count(group, advertisement)
    if next_hop.mode is IxiaNextHopMode.EXPLICIT:
        if len(next_hop.explicit_addresses) != expected_count:
            _unsupported(
                f"IXIA advertisement {advertisement.resource_id} has the wrong "
                "explicit next-hop cardinality"
            )
        for address in next_hop.explicit_addresses:
            _validate_partitioned_next_hop_address(group, advertisement, address)
        return
    if next_hop.mode is not IxiaNextHopMode.FORMULAIC:
        _unsupported(
            f"IXIA advertisement {advertisement.resource_id} has an unsupported "
            "next-hop mode"
        )
    assert next_hop.formulaic_start is not None
    assert next_hop.formulaic_step is not None
    start = _validate_partitioned_next_hop_address(
        group,
        advertisement,
        next_hop.formulaic_start,
    )
    if int(start) + next_hop.formulaic_step * (expected_count - 1) >= (
        1 << start.max_prefixlen
    ):
        _unsupported(
            f"IXIA advertisement {advertisement.resource_id} has overflowing "
            "formulaic next hops"
        )


def _partitioned_next_hop_count(
    group: IxiaDeviceGroupPlan,
    advertisement: IxiaAdvertisementPlan,
) -> int:
    distribution = advertisement.next_hop.distribution
    if distribution is IxiaNextHopDistribution.SHARED:
        return 1
    if distribution is IxiaNextHopDistribution.PER_PEER:
        return group.peer_count
    if distribution is IxiaNextHopDistribution.PER_PREFIX:
        return advertisement.route_count
    if distribution is IxiaNextHopDistribution.PER_PEER_PREFIX:
        return group.peer_count * advertisement.prefixes_per_peer
    raise RuntimeError("validated partitioned next-hop distribution is missing")


def _validate_partitioned_next_hop_address(
    group: IxiaDeviceGroupPlan,
    advertisement: IxiaAdvertisementPlan,
    address: str,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    parsed = _required_ip_address(
        advertisement.resource_id,
        address,
        4 if group.afi is AddressFamily.IPV4 else 6,
        subject="advertisement",
    )
    return parsed


def _validate_partitioned_route_attributes(
    advertisement: IxiaAdvertisementPlan,
) -> None:
    attributes = advertisement.route_attributes
    if advertisement.prefix_window.route_scale_mode is IxiaRouteScaleMode.WINDOWED:
        if advertisement.requires_route_mutation:
            valid = attributes is None or (
                bool(attributes.community_rows or attributes.extended_community_rows)
                and all(attributes.community_rows)
                and all(attributes.extended_community_rows)
                and len(frozenset(attributes.community_rows))
                == len(attributes.community_rows)
                and len(frozenset(attributes.extended_community_rows))
                == len(attributes.extended_community_rows)
                and not attributes.as_paths
                and attributes.distribution
                is IxiaRouteAttributeDistribution.ROUND_ROBIN
            )
        else:
            valid = (
                attributes is not None
                and len(attributes.community_rows) == 1
                and bool(attributes.community_rows[0])
                and not attributes.extended_community_rows
                and not attributes.as_paths
                and attributes.distribution
                is IxiaRouteAttributeDistribution.ROUND_ROBIN
            )
    else:
        valid = attributes is None or (
            not attributes.extended_community_rows
            and all(attributes.community_rows)
            and attributes.distribution is IxiaRouteAttributeDistribution.ROUND_ROBIN
        )
    if not valid:
        _unsupported(
            f"IXIA advertisement {advertisement.resource_id} has unsupported "
            "route attributes"
        )


def _validate_partitioned_named_identity(
    request: TrafficGeneratorRenderRequest,
    group: IxiaDeviceGroupPlan,
    session: IxiaBgpSessionPlan,
) -> None:
    identity = _partitioned_group_presentation(request, group)
    session_identity = _partitioned_session_presentation(
        request.legacy_identity,
        session,
    )
    if (
        identity.device_group_name is None
        or identity.tag_name is not None
        or not session_identity.bgp_peer_name
    ):
        _unsupported(
            f"IXIA group {group.resource_id} requires named presentation identity"
        )


def _partitioned_group_presentation(
    request: TrafficGeneratorRenderRequest,
    group: IxiaDeviceGroupPlan,
) -> IxiaDeviceGroupPresentation:
    try:
        return resolve_ixia_device_group_presentation(
            request.plan,
            request.legacy_identity,
            group,
        )
    except IxiaPresentationError as error:
        _unsupported(str(error))


def _partitioned_session_presentation(
    legacy_identity: LegacyIxiaIdentitySidecar,
    session: IxiaBgpSessionPlan,
) -> IxiaSessionPresentation:
    try:
        return resolve_ixia_session_presentation(legacy_identity, session)
    except IxiaPresentationError as error:
        _unsupported(str(error))


def _partitioned_advertisement_presentation(
    legacy_identity: LegacyIxiaIdentitySidecar,
    advertisement: IxiaAdvertisementPlan,
) -> IxiaAdvertisementPresentation:
    try:
        return resolve_ixia_advertisement_presentation(
            legacy_identity,
            advertisement,
        )
    except IxiaPresentationError as error:
        _unsupported(str(error))


def _validate_partitioned_presentation_uniqueness(
    request: TrafficGeneratorRenderRequest,
) -> None:
    group_names = tuple(
        presentation.device_group_name
        for group in request.plan.device_groups
        if (
            presentation := _partitioned_group_presentation(request, group)
        ).device_group_name
        is not None
    )
    session_names = tuple(
        _partitioned_session_presentation(
            request.legacy_identity,
            session,
        ).bgp_peer_name
        for session in request.plan.bgp_sessions
    )
    advertisement_names = tuple(
        _partitioned_advertisement_presentation(
            request.legacy_identity,
            advertisement,
        ).prefix_name
        for advertisement in request.plan.advertisements
    )
    for subject, names in (
        ("device-group", group_names),
        ("BGP peer", session_names),
        ("prefix", advertisement_names),
    ):
        if len(frozenset(names)) != len(names):
            _unsupported(
                f"partitioned IXIA {subject} presentation names must be unique"
            )


def _validate_initial_ipv6_session(
    group: IxiaDeviceGroupPlan,
    session: IxiaBgpSessionPlan,
) -> None:
    if group.local_asn is None:
        _unsupported(f"IXIA group {group.resource_id} has no local ASN")
    if len(session.local_addresses) != group.peer_count:
        _unsupported(
            f"IXIA session {session.resource_id} address count does not match its group"
        )
    if (
        session.relationship
        not in {PeerRelationship.EXTERNAL, PeerRelationship.INTERNAL}
        or session.capabilities != (IxiaBgpCapability.IPV6_UNICAST,)
        or session.address_prefix_length != 127
        or session.address_step != 2
        or session.address_start_index != 0
        or not session.enable_four_byte_local_as
        or session.hold_timer_s != 30
        or session.keepalive_timer_s != 10
        or not session.enable_graceful_restart
    ):
        _unsupported(
            f"IXIA session {session.resource_id} is outside the initial IPv6 "
            "session capability"
        )
    _validate_ipv6_session_addresses(
        session,
        _IxiaRenderingCapability.INITIAL_IPV6,
    )


def _validate_compact_named_ipv6_session(
    group: IxiaDeviceGroupPlan,
    session: IxiaBgpSessionPlan,
) -> None:
    if group.local_asn is None or len(session.local_addresses) != group.peer_count:
        _unsupported(f"IXIA session {session.resource_id} lacks complete group inputs")
    if (
        session.relationship
        not in {PeerRelationship.EXTERNAL, PeerRelationship.INTERNAL}
        or session.capabilities
        != (
            IxiaBgpCapability.IPV4_UNICAST,
            IxiaBgpCapability.IPV6_UNICAST,
        )
        or session.address_prefix_length != 64
        or session.address_step != 2
        or session.address_start_index != 0
        or not session.enable_four_byte_local_as
        or session.hold_timer_s != 30
        or session.keepalive_timer_s != 10
        or not session.enable_graceful_restart
    ):
        _unsupported(
            f"IXIA session {session.resource_id} is outside compact named IPv6 "
            "session lowering"
        )
    _validate_ipv6_session_addresses(
        session,
        _IxiaRenderingCapability.COMPACT_NAMED_IPV6,
    )


def _validate_ipv6_session_addresses(
    session: IxiaBgpSessionPlan,
    capability: _IxiaRenderingCapability,
) -> None:
    parsed_local = tuple(
        _required_ipv6_address(session.resource_id, address)
        for address in session.local_addresses
    )
    parsed_peer = tuple(
        _required_ipv6_address(session.resource_id, address)
        for address in session.peer_addresses
    )
    for label, addresses in (("local", parsed_local), ("peer", parsed_peer)):
        start = int(addresses[0])
        if any(
            int(address) != start + session.address_step * ordinal
            for ordinal, address in enumerate(addresses)
        ):
            _unsupported(
                f"IXIA session {session.resource_id} {label} addresses are not an "
                "arithmetic progression"
            )
    for local, peer, peer_cidr in zip(
        parsed_local,
        parsed_peer,
        session.peer_cidrs,
        strict=True,
    ):
        if peer_cidr is None:
            _unsupported(f"IXIA session {session.resource_id} has no peer CIDR")
        parsed_cidr = ipaddress.ip_interface(peer_cidr)
        peer_pair_prefix_length = _PEER_PAIR_PREFIX_LENGTH_BY_CAPABILITY[capability]
        if (
            parsed_cidr.version != 6
            or parsed_cidr.network.prefixlen != peer_pair_prefix_length
            or local == peer
            or local not in parsed_cidr.network
            or peer not in parsed_cidr.network
        ):
            _unsupported(
                f"IXIA session {session.resource_id} addresses do not form a "
                "distinct IPv6 peer pair"
            )


def _required_ipv6_address(
    session_id: ResourceId,
    address: str,
) -> ipaddress.IPv6Address:
    parsed = ipaddress.ip_address(address)
    if not isinstance(parsed, ipaddress.IPv6Address):
        _unsupported(f"IXIA session {session_id} contains a non-IPv6 address")
    return parsed


def _validate_tag_identity(
    legacy_identity: LegacyIxiaIdentitySidecar,
    group: IxiaDeviceGroupPlan,
    session: IxiaBgpSessionPlan,
) -> None:
    identity = _required_group_identity(legacy_identity, group.resource_id)
    if (
        identity.tag_name is None
        or identity.device_group_name is not None
        or identity.device_group_index is None
    ):
        _unsupported(f"IXIA group {group.resource_id} has unsupported identity data")
    if legacy_identity.session_identity(session.resource_id) is None:
        _unsupported(f"IXIA session {session.resource_id} has no BGP peer identity")


def _validate_named_identity(
    legacy_identity: LegacyIxiaIdentitySidecar,
    group: IxiaDeviceGroupPlan,
    session: IxiaBgpSessionPlan,
) -> None:
    identity = _required_group_identity(legacy_identity, group.resource_id)
    if (
        identity.device_group_name is None
        or identity.tag_name is not None
        or identity.device_group_index != 0
    ):
        _unsupported(f"IXIA group {group.resource_id} has unsupported identity data")
    if legacy_identity.session_identity(session.resource_id) is None:
        _unsupported(f"IXIA session {session.resource_id} has no BGP peer identity")


def _validate_unique_group_indices(
    request: TrafficGeneratorRenderRequest,
    port: IxiaPortPlan,
) -> None:
    indices = tuple(
        _required_group_index(request.legacy_identity, group.resource_id)
        for group in request.plan.device_groups
        if group.port_id == port.resource_id
    )
    if len(frozenset(indices)) != len(indices):
        _unsupported(f"IXIA port {port.resource_id} has duplicate device-group indices")


def _validate_unique_partitioned_group_indices(
    request: TrafficGeneratorRenderRequest,
    port: IxiaPortPlan,
) -> None:
    indices = tuple(
        _partitioned_group_presentation(request, group).device_group_index
        for group in request.plan.device_groups
        if group.port_id == port.resource_id
    )
    if len(frozenset(indices)) != len(indices):
        _unsupported(f"IXIA port {port.resource_id} has duplicate device-group indices")


def _validate_initial_ipv6_advertisement(
    legacy_identity: LegacyIxiaIdentitySidecar,
    group: IxiaDeviceGroupPlan,
    advertisement: IxiaAdvertisementPlan,
) -> None:
    if advertisement.afi is not AddressFamily.IPV6:
        _unsupported(f"IXIA advertisement {advertisement.resource_id} is not IPv6")
    if advertisement.next_hop.mode is not IxiaNextHopMode.SELF:
        _unsupported(
            f"IXIA advertisement {advertisement.resource_id} has unsupported "
            f"next-hop mode {advertisement.next_hop.mode.value}"
        )
    if advertisement.next_hop.self_realization is not None:
        _unsupported(
            f"IXIA advertisement {advertisement.resource_id} has unsupported "
            "self next-hop realization"
        )
    if advertisement.attributes or advertisement.route_attributes is not None:
        _unsupported(
            f"IXIA advertisement {advertisement.resource_id} has unsupported "
            "route attributes"
        )
    if advertisement.prefix_window.source_excluded_indices:
        _unsupported(
            f"IXIA advertisement {advertisement.resource_id} has sparse prefixes"
        )
    prefix_window = advertisement.prefix_window
    if (
        group.peer_count != 1
        or prefix_window.source_step != 1
        or prefix_window.membership_start_index != 0
        or prefix_window.membership_prefix_count != prefix_window.source_count
        or prefix_window.starting_prefix != prefix_window.source_start
        or prefix_window.prefix_length != 128
        or prefix_window.prefixes_per_peer != prefix_window.source_count
        or prefix_window.peer_distribution is not IxiaPeerPrefixDistribution.SHARED
        or prefix_window.network_group_index != 0
        or advertisement.route_count != prefix_window.source_count
        or legacy_identity.advertisement_identity(advertisement.resource_id) is not None
    ):
        _unsupported(
            f"IXIA advertisement {advertisement.resource_id} is outside the initial "
            "IPv6 route capability"
        )
    for address in (prefix_window.source_start, prefix_window.starting_prefix):
        if not isinstance(ipaddress.ip_address(address), ipaddress.IPv6Address):
            _unsupported(f"IXIA advertisement {advertisement.resource_id} is not IPv6")


def _validate_compact_named_ipv6_advertisement(
    legacy_identity: LegacyIxiaIdentitySidecar,
    advertisement: IxiaAdvertisementPlan,
) -> None:
    prefix_window = advertisement.prefix_window
    identity = legacy_identity.advertisement_identity(advertisement.resource_id)
    if advertisement.next_hop.self_realization is not None:
        _unsupported(
            f"IXIA advertisement {advertisement.resource_id} has unsupported "
            "self next-hop realization"
        )
    if (
        advertisement.afi is not AddressFamily.IPV6
        or advertisement.next_hop.mode is not IxiaNextHopMode.SELF
        or advertisement.attributes
        or advertisement.route_attributes is not None
        or advertisement.policy_communities
        or prefix_window.source_start != "5001:db8:1000::"
        or prefix_window.source_step != 1 << 80
        or prefix_window.source_count != 10_000
        or prefix_window.source_excluded_indices
        or prefix_window.membership_start_index != 0
        or prefix_window.membership_prefix_count != 10_000
        or prefix_window.starting_prefix != "5001:db8:1000::"
        or prefix_window.prefix_length != 64
        or prefix_window.prefixes_per_peer != 10_000
        or prefix_window.peer_distribution is not IxiaPeerPrefixDistribution.SHARED
        or prefix_window.network_group_index != 0
        or advertisement.route_count != 10_000
        or identity is None
    ):
        _unsupported(
            f"IXIA advertisement {advertisement.resource_id} is outside compact "
            "named IPv6 route lowering"
        )


def _sessions_by_group(
    request: TrafficGeneratorRenderRequest,
) -> dict[ResourceId, IxiaBgpSessionPlan]:
    sessions: dict[ResourceId, IxiaBgpSessionPlan] = {}
    for session in request.plan.bgp_sessions:
        if session.device_group_id in sessions:
            _unsupported(
                f"IXIA group {session.device_group_id} has multiple BGP sessions"
            )
        sessions[session.device_group_id] = session
    return sessions


def _basic_port_config(
    request: TrafficGeneratorRenderRequest,
    port: IxiaPortPlan,
    capability: _IxiaRenderingCapability,
) -> taac_types.BasicPortConfig:
    groups = _capability_port_groups(request, port, capability)
    return taac_types.BasicPortConfig(
        endpoint=f"{port.dut_physical_identifier}:{port.dut_interface}",
        device_group_configs=[
            _device_group_config(request, group, capability) for group in groups
        ],
    )


def _ordered_port_groups(
    request: TrafficGeneratorRenderRequest,
    port: IxiaPortPlan,
) -> tuple[IxiaDeviceGroupPlan, ...]:
    plan_order = _plan_order_port_groups(request, port)
    compatibility_order = tuple(
        sorted(
            plan_order,
            key=lambda group: _required_group_index(
                request.legacy_identity,
                group.resource_id,
            ),
        )
    )
    if tuple(group.resource_id for group in compatibility_order) != tuple(
        group.resource_id for group in plan_order
    ):
        _unsupported(
            f"IXIA port {port.resource_id} plan order does not match "
            "compatibility device-group order"
        )
    return plan_order


def _capability_port_groups(
    request: TrafficGeneratorRenderRequest,
    port: IxiaPortPlan,
    capability: _IxiaRenderingCapability,
) -> tuple[IxiaDeviceGroupPlan, ...]:
    if _is_partitioned_dual_stack_capability(capability):
        if _port_has_flat_route_scale(request, port):
            return tuple(
                sorted(
                    _plan_order_port_groups(request, port),
                    key=lambda group: _partitioned_group_order_index(request, group),
                )
            )
        return _plan_order_port_groups(request, port)
    return _ordered_port_groups(request, port)


def _port_has_flat_route_scale(
    request: TrafficGeneratorRenderRequest,
    port: IxiaPortPlan,
) -> bool:
    group_ids = frozenset(
        group.resource_id
        for group in request.plan.device_groups
        if group.port_id == port.resource_id
    )
    return any(
        advertisement.device_group_id in group_ids
        and advertisement.prefix_window.route_scale_mode is IxiaRouteScaleMode.FLAT
        for advertisement in request.plan.advertisements
    )


def _partitioned_group_order_index(
    request: TrafficGeneratorRenderRequest,
    group: IxiaDeviceGroupPlan,
) -> int:
    index = _partitioned_group_presentation(request, group).device_group_index
    if index is None:
        _unsupported(f"IXIA group {group.resource_id} has no device-group index")
    return index


def _plan_order_port_groups(
    request: TrafficGeneratorRenderRequest,
    port: IxiaPortPlan,
) -> tuple[IxiaDeviceGroupPlan, ...]:
    return tuple(
        group
        for group in request.plan.device_groups
        if group.port_id == port.resource_id
    )


def _device_group_config(
    request: TrafficGeneratorRenderRequest,
    group: IxiaDeviceGroupPlan,
    capability: _IxiaRenderingCapability,
) -> taac_types.DeviceGroupConfig:
    session = next(
        session
        for session in request.plan.bgp_sessions
        if session.device_group_id == group.resource_id
    )
    if _is_partitioned_dual_stack_capability(capability):
        return _partitioned_dual_stack_device_group_config(
            request,
            group,
            _partitioned_group_presentation(request, group),
            session,
            _partitioned_session_presentation(
                request.legacy_identity,
                session,
            ),
        )
    identity = _required_group_identity(
        request.legacy_identity,
        group.resource_id,
    )
    session_identity = _required_session_identity(
        request.legacy_identity,
        session.resource_id,
    )
    if capability is _IxiaRenderingCapability.COMPACT_NAMED_IPV6:
        advertisements = tuple(
            advertisement
            for advertisement in request.plan.advertisements
            if advertisement.device_group_id == group.resource_id
        )
        route_scales = (
            [
                _compact_named_ipv6_route_scale(
                    request.legacy_identity,
                    advertisements[0],
                )
            ]
            if advertisements
            else None
        )
        return taac_types.DeviceGroupConfig(
            device_group_name=identity.device_group_name,
            device_group_index=identity.device_group_index,
            multiplier=group.peer_count,
            v6_addresses_config=taac_types.IpAddressesConfig(
                starting_ip=session.local_addresses[0],
                increment_ip=_legacy_v6_address_step(session.address_step),
                gateway_starting_ip=session.peer_addresses[0],
                gateway_increment_ip=_legacy_v6_address_step(session.address_step),
                mask=None,
                start_index=session.address_start_index,
            ),
            v6_bgp_config=taac_types.BgpConfig(
                bgp_peer_name=session_identity.bgp_peer_name,
                local_as_4_bytes=group.local_asn,
                enable_4_byte_local_as=session.enable_four_byte_local_as,
                bgp_peer_type=_BGP_PEER_TYPES[session.relationship],
                bgp_capabilities=[
                    _BGP_CAPABILITIES[capability] for capability in session.capabilities
                ],
                hold_timer=session.hold_timer_s,
                keepalive_timer=session.keepalive_timer_s,
                route_scales=route_scales,
                enable_graceful_restart=session.enable_graceful_restart,
            ),
        )
    return taac_types.DeviceGroupConfig(
        device_group_index=identity.device_group_index,
        tag_name=identity.tag_name,
        multiplier=group.peer_count,
        v6_addresses_config=taac_types.IpAddressesConfig(
            starting_ip=session.local_addresses[0],
            increment_ip=_legacy_v6_address_step(session.address_step),
            gateway_starting_ip=session.peer_addresses[0],
            gateway_increment_ip=_legacy_v6_address_step(session.address_step),
            mask=session.address_prefix_length,
            start_index=session.address_start_index,
        ),
        v6_bgp_config=taac_types.BgpConfig(
            bgp_peer_name=session_identity.bgp_peer_name,
            local_as_4_bytes=group.local_asn,
            enable_4_byte_local_as=session.enable_four_byte_local_as,
            bgp_peer_type=_BGP_PEER_TYPES[session.relationship],
            bgp_capabilities=[
                _BGP_CAPABILITIES[capability] for capability in session.capabilities
            ],
            hold_timer=session.hold_timer_s,
            keepalive_timer=session.keepalive_timer_s,
            route_scales=[
                _route_scale(request.legacy_identity, group, advertisement)
                for advertisement in request.plan.advertisements
                if advertisement.device_group_id == group.resource_id
            ],
            enable_graceful_restart=session.enable_graceful_restart,
        ),
    )


def _partitioned_dual_stack_device_group_config(
    request: TrafficGeneratorRenderRequest,
    group: IxiaDeviceGroupPlan,
    identity: IxiaDeviceGroupPresentation,
    session: IxiaBgpSessionPlan,
    session_identity: IxiaSessionPresentation,
) -> taac_types.DeviceGroupConfig:
    address_config = _partitioned_address_config(request, group, session)
    bgp_config = _partitioned_bgp_config(
        request,
        group,
        session,
        session_identity,
    )
    return taac_types.DeviceGroupConfig(
        device_group_name=identity.device_group_name,
        device_group_index=identity.device_group_index,
        multiplier=group.peer_count,
        v4_addresses_config=(
            address_config if group.afi is AddressFamily.IPV4 else None
        ),
        v6_addresses_config=(
            address_config if group.afi is AddressFamily.IPV6 else None
        ),
        v4_bgp_config=(bgp_config if group.afi is AddressFamily.IPV4 else None),
        v6_bgp_config=(bgp_config if group.afi is AddressFamily.IPV6 else None),
    )


def _partitioned_address_config(
    request: TrafficGeneratorRenderRequest,
    group: IxiaDeviceGroupPlan,
    session: IxiaBgpSessionPlan,
) -> taac_types.IpAddressesConfig:
    port_group_ids = frozenset(
        candidate.resource_id
        for candidate in request.plan.device_groups
        if candidate.port_id == group.port_id
    )
    port_requires_configuration = any(
        advertisement.device_group_id in port_group_ids
        and (
            advertisement.prefix_window.route_scale_mode is IxiaRouteScaleMode.FLAT
            or advertisement.requires_route_mutation
        )
        for advertisement in request.plan.advertisements
    )
    group_advertises = any(
        advertisement.device_group_id == group.resource_id
        for advertisement in request.plan.advertisements
    )
    return taac_types.IpAddressesConfig(
        starting_ip=_partitioned_address_origin(
            session.local_addresses[0],
            session.address_step,
            session.address_start_index,
        ),
        increment_ip=(
            "0.0.0.2"
            if group.afi is AddressFamily.IPV4
            else _legacy_v6_address_step(session.address_step)
        ),
        gateway_starting_ip=_partitioned_address_origin(
            session.peer_addresses[0],
            session.address_step,
            session.address_start_index,
        ),
        gateway_increment_ip=(
            "0.0.0.2"
            if group.afi is AddressFamily.IPV4
            else _legacy_v6_address_step(session.address_step)
        ),
        mask=(
            session.address_prefix_length if group.afi is AddressFamily.IPV4 else None
        ),
        start_index=(
            session.address_start_index
            if (
                not port_requires_configuration
                or group_advertises
                or session.relationship is PeerRelationship.MONITOR
            )
            else None
        ),
    )


def _partitioned_address_origin(
    address: str,
    step: int,
    start_index: int,
) -> str:
    parsed = ipaddress.ip_address(address)
    origin = int(parsed) - step * start_index
    if origin < 0:
        _unsupported(f"IXIA address {address!r} underflows its start index")
    return str(type(parsed)(origin))


def _partitioned_bgp_config(
    request: TrafficGeneratorRenderRequest,
    group: IxiaDeviceGroupPlan,
    session: IxiaBgpSessionPlan,
    session_identity: IxiaSessionPresentation,
) -> taac_types.BgpConfig:
    advertisements = tuple(
        advertisement
        for advertisement in request.plan.advertisements
        if advertisement.device_group_id == group.resource_id
    )
    if len(advertisements) > 1:
        _unsupported(
            f"IXIA group {group.resource_id} has multiple partitioned advertisements"
        )
    bgp_params: dict[str, t.Any] = {
        "bgp_peer_name": session_identity.bgp_peer_name,
        "local_as_4_bytes": group.local_asn,
        "enable_4_byte_local_as": session.enable_four_byte_local_as,
        "bgp_capabilities": [
            _BGP_CAPABILITIES[capability] for capability in session.capabilities
        ],
        "bgp_peer_type": _BGP_PEER_TYPES[session.relationship],
    }
    if advertisements:
        bgp_params["route_scales"] = [
            _partitioned_dual_stack_route_scale(
                request.legacy_identity,
                group,
                advertisements[0],
            )
        ]
    if not session.enable_graceful_restart:
        bgp_params["enable_graceful_restart"] = False
    return taac_types.BgpConfig(**bgp_params)


def _partitioned_dual_stack_route_scale(
    legacy_identity: LegacyIxiaIdentitySidecar,
    group: IxiaDeviceGroupPlan,
    advertisement: IxiaAdvertisementPlan,
) -> taac_types.RouteScaleSpec:
    identity = _partitioned_advertisement_presentation(
        legacy_identity,
        advertisement,
    )
    prefix_window = advertisement.prefix_window
    flat = prefix_window.route_scale_mode is IxiaRouteScaleMode.FLAT
    route_multiplier = prefix_window.prefixes_per_peer if flat else 1
    route_prefix_count = 1 if flat else prefix_window.prefixes_per_peer
    route_step = (
        prefix_window.source_step
        if flat or group.peer_count == 1
        else (
            0
            if prefix_window.peer_distribution is IxiaPeerPrefixDistribution.SHARED
            else prefix_window.source_step * prefix_window.prefixes_per_peer
        )
    )
    route_scale = taac_types.RouteScale(
        prefix_name=identity.prefix_name,
        prefix_count=route_prefix_count,
        prefix_length=prefix_window.prefix_length,
        starting_prefixes=prefix_window.starting_prefix,
        prefix_step=_partitioned_route_step(group, advertisement, route_step),
        multiplier=route_multiplier,
        as_path_prepend_numbers=_partitioned_as_paths(advertisement),
        bgp_communities=_partitioned_initial_route_communities(advertisement),
        ip_address_family=(
            ixia_types.IpAddressFamily.IPV4
            if group.afi is AddressFamily.IPV4
            else ixia_types.IpAddressFamily.IPV6
        ),
        set_next_hop_type=(
            ixia_types.SetNextHopType.SAME_AS_LOCAL_IP
            if advertisement.next_hop.mode is IxiaNextHopMode.SELF
            else None
        ),
    )
    return taac_types.RouteScaleSpec(
        network_group_index=prefix_window.network_group_index,
        multiplier=route_multiplier,
        v4_route_scale=(route_scale if group.afi is AddressFamily.IPV4 else None),
        v6_route_scale=(route_scale if group.afi is AddressFamily.IPV6 else None),
    )


def _partitioned_route_step(
    group: IxiaDeviceGroupPlan,
    advertisement: IxiaAdvertisementPlan,
    route_step: int,
) -> str:
    if route_step == 0:
        if group.afi is AddressFamily.IPV4:
            return "0.0.0.0"
        return "::" if advertisement.requires_route_mutation else "0:0:0:0:0:0:0:0"
    address_type = (
        ipaddress.IPv4Address
        if group.afi is AddressFamily.IPV4
        else ipaddress.IPv6Address
    )
    return str(address_type(route_step))


def _partitioned_initial_route_communities(
    advertisement: IxiaAdvertisementPlan,
) -> list[str]:
    """Return communities applied during initial IXIA route-scale creation.

    Mutation advertisements start with a neutral route scale. Their validated
    attribute rows are emitted by `_partitioned_route_attribute_mutation` into
    the `configure_formulaic_bgp_routes` lifecycle task.
    """
    if advertisement.policy_communities:
        return list(advertisement.policy_communities)
    if advertisement.requires_route_mutation:
        return []
    attributes = advertisement.route_attributes
    if attributes is None or not attributes.community_rows:
        return []
    first_row = attributes.community_rows[0]
    communities = (
        first_row[:1]
        if advertisement.prefix_window.route_scale_mode is IxiaRouteScaleMode.FLAT
        else first_row
    )
    return [f"{community.asn}:{community.value}" for community in communities]


def _partitioned_as_paths(
    advertisement: IxiaAdvertisementPlan,
) -> list[list[int]] | None:
    attributes = advertisement.route_attributes
    if attributes is None or not attributes.as_paths:
        return None
    return [list(path.asns) for path in attributes.as_paths]


def _partitioned_route_mutations(
    request: TrafficGeneratorRenderRequest,
) -> list[dict[str, t.Any]]:
    groups_by_id = {group.resource_id: group for group in request.plan.device_groups}
    return [
        _partitioned_route_mutation(
            request,
            groups_by_id[advertisement.device_group_id],
            advertisement,
        )
        for advertisement in request.plan.advertisements
    ]


def _partitioned_route_mutation(
    request: TrafficGeneratorRenderRequest,
    group: IxiaDeviceGroupPlan,
    advertisement: IxiaAdvertisementPlan,
) -> dict[str, t.Any]:
    group_identity = _partitioned_group_presentation(request, group)
    advertisement_identity = _partitioned_advertisement_presentation(
        request.legacy_identity,
        advertisement,
    )
    mutation: dict[str, t.Any] = {
        "device_group_name": group_identity.device_group_name,
        "prefix_pool_name": advertisement_identity.prefix_name,
        "afi": group.afi.value,
        "peer_count": group.peer_count,
        "prefixes_per_peer": advertisement.prefixes_per_peer,
        "flat_prefix_geometry": (
            advertisement.prefix_window.route_scale_mode is IxiaRouteScaleMode.FLAT
        ),
        "prefix": _partitioned_prefix_mutation(advertisement),
        "next_hop": _partitioned_next_hop_mutation(advertisement),
        "attributes": dict(advertisement.attributes),
    }
    route_attributes = _partitioned_route_attribute_mutation(advertisement)
    if route_attributes is not None:
        mutation["route_attributes"] = route_attributes
    return mutation


def _partitioned_prefix_mutation(
    advertisement: IxiaAdvertisementPlan,
) -> dict[str, t.Any]:
    prefix_window = advertisement.prefix_window
    raw_start_index = _retained_candidate_index(
        prefix_window.membership_start_index,
        prefix_window.source_excluded_indices,
    )
    raw_end_index = _retained_candidate_index(
        prefix_window.membership_start_index
        + prefix_window.membership_prefix_count
        - 1,
        prefix_window.source_excluded_indices,
    )
    # `count` is the retained cardinality; the IXIA runtime scans
    # `count + len(excluded_indices)` raw candidates before filtering.
    return {
        "start": prefix_window.starting_prefix,
        "step": prefix_window.source_step,
        "count": prefix_window.membership_prefix_count,
        "excluded_indices": [
            index - raw_start_index
            for index in prefix_window.source_excluded_indices
            if raw_start_index <= index <= raw_end_index
        ],
        "distribution": prefix_window.peer_distribution.value,
    }


def _partitioned_next_hop_mutation(
    advertisement: IxiaAdvertisementPlan,
) -> dict[str, t.Any] | None:
    next_hop = advertisement.next_hop
    if next_hop.mode is IxiaNextHopMode.SELF:
        return None
    assert next_hop.distribution is not None
    if next_hop.mode is IxiaNextHopMode.FORMULAIC:
        assert next_hop.formulaic_start is not None
        assert next_hop.formulaic_step is not None
        return {
            "kind": "formulaic",
            "start": next_hop.formulaic_start,
            "step": next_hop.formulaic_step,
            "distribution": next_hop.distribution.value,
        }
    return {
        "kind": "explicit",
        "addresses": list(next_hop.explicit_addresses),
        "distribution": next_hop.distribution.value,
    }


def _partitioned_route_attribute_mutation(
    advertisement: IxiaAdvertisementPlan,
) -> dict[str, t.Any] | None:
    attributes = advertisement.route_attributes
    if attributes is None:
        return None
    return {
        "distribution": attributes.distribution.value,
        "community_rows": [
            [f"{community.asn}:{community.value}" for community in row]
            for row in attributes.community_rows
        ],
        "extended_community_rows": [
            [
                (
                    f"{community.kind}:{community.administrator}:"
                    f"{community.assigned_number}"
                )
                for community in row
            ]
            for row in attributes.extended_community_rows
        ],
    }


def _compact_named_ipv6_route_scale(
    legacy_identity: LegacyIxiaIdentitySidecar,
    advertisement: IxiaAdvertisementPlan,
) -> taac_types.RouteScaleSpec:
    identity = legacy_identity.advertisement_identity(advertisement.resource_id)
    if identity is None:
        _unsupported(
            f"IXIA advertisement {advertisement.resource_id} has no prefix identity"
        )
    prefix_window = advertisement.prefix_window
    return taac_types.RouteScaleSpec(
        v6_route_scale=taac_types.RouteScale(
            prefix_name=identity.prefix_name,
            starting_prefixes=prefix_window.starting_prefix,
            prefix_step=str(ipaddress.IPv6Address(prefix_window.source_step)),
            prefix_length=prefix_window.prefix_length,
            multiplier=1,
            prefix_count=prefix_window.prefixes_per_peer,
            ip_address_family=ixia_types.IpAddressFamily.IPV6,
            bgp_communities=[],
        ),
        multiplier=1,
        network_group_index=prefix_window.network_group_index,
    )


def _route_scale(
    legacy_identity: LegacyIxiaIdentitySidecar,
    group: IxiaDeviceGroupPlan,
    advertisement: IxiaAdvertisementPlan,
) -> taac_types.RouteScaleSpec:
    identity = legacy_identity.advertisement_identity(advertisement.resource_id)
    prefix_window = advertisement.prefix_window
    route_step = (
        prefix_window.source_step
        if group.peer_count == 1
        else (
            0
            if prefix_window.peer_distribution is IxiaPeerPrefixDistribution.SHARED
            else prefix_window.source_step * prefix_window.prefixes_per_peer
        )
    )
    route_scale = taac_types.RouteScale(
        prefix_name=identity.prefix_name if identity is not None else None,
        prefix_count=prefix_window.prefixes_per_peer,
        prefix_length=prefix_window.prefix_length,
        starting_prefixes=prefix_window.starting_prefix,
        prefix_step=_legacy_v6_route_step(route_step, group.peer_count),
        multiplier=1,
        as_path_prepend_numbers=None,
        bgp_communities=list(advertisement.policy_communities),
        ip_address_family=ixia_types.IpAddressFamily.IPV6,
        set_next_hop_type=None,
    )
    return taac_types.RouteScaleSpec(
        network_group_index=prefix_window.network_group_index,
        multiplier=1,
        v6_route_scale=route_scale,
    )


def _endpoint_patch(
    request: TrafficGeneratorEndpointRenderRequest,
    endpoint_id: ResourceId,
) -> TrafficGeneratorEndpointPatch:
    ports = request.endpoint_ports(endpoint_id)
    direct_connection_ports = request.direct_connection_ports(endpoint_id)
    return TrafficGeneratorEndpointPatch(
        endpoint_id=endpoint_id,
        ixia_port_fragments=tuple(
            TrafficGeneratorIxiaPortFragment(
                port_id=port_request.port.resource_id,
                label=port_request.ixia_port_label,
            )
            for port_request in ports
        ),
        direct_connection_fragments=tuple(
            TrafficGeneratorDirectConnectionFragment(
                port_id=port_request.port.resource_id,
                connection=taac_types.DirectIxiaConnection(
                    interface=port_request.port.dut_interface,
                    ixia_chassis_ip=port_request.port.chassis_identifier,
                    ixia_port=port_request.port.ixia_port,
                ),
            )
            for port_request in direct_connection_ports
        ),
    )


def _full_renderer_endpoint_patch(
    request: TrafficGeneratorRenderRequest,
    endpoint_id: ResourceId,
    capability: _IxiaRenderingCapability,
) -> TrafficGeneratorEndpointPatch:
    ports = tuple(
        port for port in request.plan.ports if port.dut_endpoint_id == endpoint_id
    )
    presentations_by_port_id = _resolved_port_presentations(request)
    labels = tuple(
        presentations_by_port_id[port.resource_id].endpoint_ixia_port_label
        for port in ports
    )
    direct_connection_ports = (
        tuple(
            sorted(
                ports,
                key=lambda port: _compact_port_relationship_order(request, port),
            )
        )
        if capability is _IxiaRenderingCapability.COMPACT_NAMED_IPV6
        else ports
    )
    return TrafficGeneratorEndpointPatch(
        endpoint_id=endpoint_id,
        ixia_port_fragments=tuple(
            TrafficGeneratorIxiaPortFragment(port_id=port.resource_id, label=label)
            for port, label in zip(ports, labels, strict=True)
        ),
        direct_connection_fragments=tuple(
            TrafficGeneratorDirectConnectionFragment(
                port_id=port.resource_id,
                connection=taac_types.DirectIxiaConnection(
                    interface=port.dut_interface,
                    ixia_chassis_ip=port.chassis_identifier,
                    ixia_port=port.ixia_port,
                ),
            )
            for port in direct_connection_ports
        ),
    )


def _compact_port_relationship_order(
    request: TrafficGeneratorRenderRequest,
    port: IxiaPortPlan,
) -> int:
    group = next(
        group
        for group in request.plan.device_groups
        if group.port_id == port.resource_id
    )
    session = next(
        session
        for session in request.plan.bgp_sessions
        if session.device_group_id == group.resource_id
    )
    return 0 if session.relationship is PeerRelationship.EXTERNAL else 1


def _resolved_port_presentations(
    request: TrafficGeneratorRenderRequest,
) -> dict[ResourceId, IxiaPortPresentation]:
    try:
        return {
            presentation.resource_id: presentation
            for presentation in resolve_ixia_port_presentations(
                request.plan,
                request.legacy_identity,
            )
        }
    except IxiaPresentationError as error:
        _unsupported(str(error))


def _required_group_identity(
    legacy_identity: LegacyIxiaIdentitySidecar,
    resource_id: ResourceId,
) -> LegacyIxiaGroupIdentity:
    identity = legacy_identity.group_identity(resource_id)
    if identity is None:
        _unsupported(f"IXIA group {resource_id} has no legacy identity")
    return identity


def _required_group_index(
    legacy_identity: LegacyIxiaIdentitySidecar,
    resource_id: ResourceId,
) -> int:
    identity = _required_group_identity(legacy_identity, resource_id)
    if identity.device_group_index is None:
        _unsupported(f"IXIA group {resource_id} has no legacy index")
    return identity.device_group_index


def _required_session_identity(
    legacy_identity: LegacyIxiaIdentitySidecar,
    resource_id: ResourceId,
) -> LegacyIxiaSessionIdentity:
    identity = legacy_identity.session_identity(resource_id)
    if identity is None:
        _unsupported(f"IXIA session {resource_id} has no legacy identity")
    return identity


def _legacy_v6_address_step(step: int) -> str:
    if step != 2:
        _unsupported(f"IXIA address step {step} has no legacy IPv6 encoding")
    return "0:0:0:0::2"


def _legacy_v6_route_step(step: int, peer_count: int) -> str:
    if peer_count == 1 and step == 1:
        return "0:0:0:0::1"
    return str(ipaddress.IPv6Address(step))


def _unsupported(message: str) -> t.NoReturn:
    raise UnsupportedIxiaRenderingError(message)


_BGP_CAPABILITIES = {
    IxiaBgpCapability.IPV4_UNICAST: ixia_types.BgpCapability.IpV4Unicast,
    IxiaBgpCapability.IPV6_UNICAST: ixia_types.BgpCapability.IpV6Unicast,
    IxiaBgpCapability.IPV4_UNICAST_ADD_PATH: (
        ixia_types.BgpCapability.Ipv4UnicastAddPath
    ),
    IxiaBgpCapability.IPV6_UNICAST_ADD_PATH: (
        ixia_types.BgpCapability.Ipv6UnicastAddPath
    ),
    IxiaBgpCapability.NEXT_HOP_ENCODING: (
        ixia_types.BgpCapability.NHEncodingCapabilities
    ),
}

_BGP_PEER_TYPES = {
    PeerRelationship.EXTERNAL: ixia_types.BgpPeerType.EBGP,
    PeerRelationship.INTERNAL: ixia_types.BgpPeerType.IBGP,
    PeerRelationship.MONITOR: ixia_types.BgpPeerType.EBGP,
}


__all__ = (
    "SharedIxiaEndpointRenderer",
    "SharedIxiaPortBaseRenderer",
    "SharedIxiaPortDeviceGroupRenderer",
    "SharedIxiaRenderer",
    "UnsupportedIxiaRenderingError",
)
