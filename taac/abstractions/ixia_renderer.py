# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

import ipaddress
import typing as t
from dataclasses import dataclass

from ixia.ixia import types as ixia_types
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
    IxiaNextHopMode,
    IxiaPeerPrefixDistribution,
    IxiaPortPlan,
    ResourceId,
)
from taac.abstractions.compilation.traffic_generator import (
    TrafficGeneratorDirectConnectionFragment,
    TrafficGeneratorEndpointPatch,
    TrafficGeneratorIxiaPortFragment,
    TrafficGeneratorRenderRequest,
    TrafficGeneratorRenderResult,
)
from taac.abstractions.ixia_semantics import IxiaBgpCapability
from taac.abstractions.routing_semantics import PeerRelationship
from taac.test_as_a_config import types as taac_types


class UnsupportedIxiaRenderingError(ValueError):
    pass


@dataclass(frozen=True)
class SharedIxiaRenderer:
    """Lowers capability-supported IXIA semantics without DUT-platform input."""

    def render(
        self,
        request: TrafficGeneratorRenderRequest,
    ) -> TrafficGeneratorRenderResult:
        _validate_initial_ipv6_capability(request)
        activation_by_endpoint = {
            activation.endpoint_id: activation
            for activation in request.endpoint_activations
        }
        basic_port_configs = tuple(
            _basic_port_config(request, port)
            for port in request.plan.ports
            if activation_by_endpoint[port.dut_endpoint_id].emit_basic_port_configs
        )
        endpoint_patches = tuple(
            _endpoint_patch(request, activation.endpoint_id)
            for activation in request.endpoint_activations
            if activation.emit_endpoint_patch
        )
        result = TrafficGeneratorRenderResult(
            consumed_resource_ids=request.plan.iter_resource_ids(),
            basic_port_configs=basic_port_configs,
            endpoint_patches=endpoint_patches,
        )
        result.validate(request)
        return result


def _validate_initial_ipv6_capability(
    request: TrafficGeneratorRenderRequest,
) -> None:
    sessions_by_group = _sessions_by_group(request)
    for port in request.plan.ports:
        if request.legacy_identity.port_identity(port.resource_id) is None:
            _unsupported(f"IXIA port {port.resource_id} has no endpoint label identity")
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
    _validate_ipv6_session_addresses(session)


def _validate_ipv6_session_addresses(session: IxiaBgpSessionPlan) -> None:
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
        if (
            parsed_cidr.version != 6
            or parsed_cidr.network.prefixlen != session.address_prefix_length
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
) -> taac_types.BasicPortConfig:
    groups = sorted(
        (
            group
            for group in request.plan.device_groups
            if group.port_id == port.resource_id
        ),
        key=lambda group: _required_group_index(
            request.legacy_identity,
            group.resource_id,
        ),
    )
    return taac_types.BasicPortConfig(
        endpoint=f"{port.dut_physical_identifier}:{port.dut_interface}",
        device_group_configs=[_device_group_config(request, group) for group in groups],
    )


def _device_group_config(
    request: TrafficGeneratorRenderRequest,
    group: IxiaDeviceGroupPlan,
) -> taac_types.DeviceGroupConfig:
    identity = _required_group_identity(
        request.legacy_identity,
        group.resource_id,
    )
    session = next(
        session
        for session in request.plan.bgp_sessions
        if session.device_group_id == group.resource_id
    )
    session_identity = _required_session_identity(
        request.legacy_identity,
        session.resource_id,
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
    request: TrafficGeneratorRenderRequest,
    endpoint_id: ResourceId,
) -> TrafficGeneratorEndpointPatch:
    ports = tuple(
        port for port in request.plan.ports if port.dut_endpoint_id == endpoint_id
    )
    labels = tuple(
        _required_port_label(request.legacy_identity, port.resource_id)
        for port in ports
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
            for port in ports
        ),
    )


def _required_port_label(
    legacy_identity: LegacyIxiaIdentitySidecar,
    resource_id: ResourceId,
) -> str:
    identity = legacy_identity.port_identity(resource_id)
    if identity is None:
        _unsupported(f"IXIA port {resource_id} has no endpoint label identity")
    return identity.endpoint_ixia_port_label


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
    IxiaBgpCapability.IPV6_UNICAST: ixia_types.BgpCapability.IpV6Unicast,
}

_BGP_PEER_TYPES = {
    PeerRelationship.EXTERNAL: ixia_types.BgpPeerType.EBGP,
    PeerRelationship.INTERNAL: ixia_types.BgpPeerType.IBGP,
}


__all__ = (
    "SharedIxiaRenderer",
    "UnsupportedIxiaRenderingError",
)
