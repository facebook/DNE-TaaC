# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

import typing as t

from taac.abstractions.topology.model import (
    BoundTopology,
    OpenRMode,
    OpenRSetupSequence,
    ResolvedDeviceGroup,
    ResolvedEndpoint,
    ResolvedIntentReport,
    ResolvedIxiaDeviceGroupChild,
    ResolvedOpenRIntent,
)
from pyre_extensions import none_throws


def inspect_resolved_intent(bound: BoundTopology) -> ResolvedIntentReport:
    bound.validate_for_compile()
    device_config = none_throws(bound.device_config)
    openr_mode = device_config.openr_mode
    if openr_mode is OpenRMode.NONE:
        openr_setup_sequence = OpenRSetupSequence.NONE
    elif openr_mode is OpenRMode.STANDALONE:
        openr_setup_sequence = OpenRSetupSequence.STANDALONE_SYNTHETIC_INJECTION
    elif openr_mode is OpenRMode.PEER:
        openr_setup_sequence = OpenRSetupSequence.PEER_DAEMON
    else:
        t.assert_never(openr_mode)
    endpoints = tuple(
        ResolvedEndpoint(
            name=endpoint.name,
            role=endpoint.role,
            kind=endpoint.kind,
            backend=bound.endpoint_os[endpoint.name],
            physical_identifier=getattr(
                bound.physical_inventory,
                bound.resolved_endpoints[endpoint.name]["physical_identifier_field"],
                None,
            ),
        )
        for endpoint in bound.logical_topology.endpoints
    )
    device_groups = tuple(
        ResolvedDeviceGroup(
            name=device_group.name,
            role=device_group.role,
            afi=device_group.afi,
            a_endpoint=device_group.spec.a_endpoint,
            z_endpoint=device_group.spec.z_endpoint,
            a_interface=device_group.a_interface,
            z_interface=device_group.z_interface,
            ixia_port=device_group.ixia_port,
            routing_driver=device_group.routing_driver,
            parent_network=device_group.parent_network,
            local_asn=device_group.local_asn,
            remote_asn=device_group.remote_asn,
            peer_group=device_group.peer_group,
            legacy_ixia_tag_name=device_group.legacy_ixia_tag_name,
            legacy_ixia_bgp_peer_name=device_group.legacy_ixia_bgp_peer_name,
            legacy_ixia_device_group_name=(device_group.legacy_ixia_device_group_name),
            peers=device_group.peers,
            prefix_advertisements=device_group.prefix_advertisements,
            port_assignment=device_group.port_assignment,
            partition=device_group.partition,
            legacy_ixia_device_group_index=(
                device_group.legacy_ixia_device_group_index
            ),
            route_attributes=device_group.route_attributes,
            provenance=device_group.provenance,
            ixia_children=tuple(
                ResolvedIxiaDeviceGroupChild(
                    name=child.spec.name,
                    parent_name=device_group.name,
                    ordinal=child.spec.ordinal,
                    start_index=child.spec.start_index,
                    role=device_group.role,
                    afi=device_group.afi,
                    a_endpoint=device_group.spec.a_endpoint,
                    z_endpoint=device_group.spec.z_endpoint,
                    a_interface=device_group.a_interface,
                    z_interface=device_group.z_interface,
                    ixia_port=device_group.ixia_port,
                    routing_driver=device_group.routing_driver,
                    parent_network=device_group.parent_network,
                    local_asn=device_group.local_asn,
                    remote_asn=device_group.remote_asn,
                    peer_group=device_group.peer_group,
                    legacy_ixia_device_group_name=(
                        child.spec.legacy_ixia_device_group_name
                    ),
                    legacy_ixia_bgp_peer_name=(child.spec.legacy_ixia_bgp_peer_name),
                    legacy_ixia_device_group_index=(
                        child.spec.legacy_ixia_device_group_index
                    ),
                    legacy_ixia_prefix_pool_name=(
                        child.spec.legacy_ixia_prefix_pool_name
                    ),
                    peers=child.peers,
                    prefix_advertisements=child.prefix_advertisements,
                    port_assignment=device_group.port_assignment,
                    route_attributes=device_group.route_attributes,
                    provenance=device_group.provenance,
                )
                for child in device_group.ixia_children
            ),
        )
        for device_group in bound.device_groups
    )
    return ResolvedIntentReport(
        logical_topology_name=bound.logical_topology.name,
        endpoints=endpoints,
        device_groups=device_groups,
        openr=ResolvedOpenRIntent(
            mode=openr_mode,
            setup_sequence=openr_setup_sequence,
        ),
        prefix_sets=tuple(
            bound.resolved_prefix_sets[prefix_set.name]
            for prefix_set in bound.logical_topology.prefix_sets
        ),
        route_senders=bound.resolved_route_senders,
    )
