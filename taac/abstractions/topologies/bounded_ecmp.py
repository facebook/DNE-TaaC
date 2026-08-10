# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from taac.abstractions.compatibility.eos_bgpcpp_compatibility import (
    PEERGROUP_EBGP_V4,
    PEERGROUP_EBGP_V6,
    PEERGROUP_IBGP_V4,
    PEERGROUP_IBGP_V6,
)
from taac.abstractions.compatibility.legacy_ebb_binding import (
    IXIA_EBGP_IC_PARENT_NETWORK_V4,
    IXIA_EBGP_IC_PARENT_NETWORK_V6,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
)
from taac.abstractions.compatibility.legacy_ebb_topology import (
    EBGP_REMOTE_AS,
    IBGP_REMOTE_AS,
)
from taac.abstractions.routing_semantics import PeerRelationship
from taac.abstractions.topology import (
    AddressPlan,
    BgpPeerGroup,
    DeviceGroupSpec,
    EndpointSpec,
    FormulaicPrefixSource,
    IxiaDeviceGroupChild,
    IxiaPortAssignment,
    LogicalTopology,
    NextHopIntent,
    NextHopMode,
    OpenRMode,
    PeerPrefixDistribution,
    PrefixAdvertisement,
    PrefixAllocation,
    PrefixMembership,
    PrefixSet,
    RouteAttributeDistribution,
    RouteAttributePool,
    RouteSender,
    RoutingDeviceConfig,
    SelfNextHopRealization,
    StandardCommunity,
)


BOUNDED_ECMP_PEER_COUNT = 128
BOUNDED_ECMP_PREFIX_COUNT = 5_000

BOUNDED_ECMP_PORT_MAP = {"ebgp": 0, "ibgp": 1}
BOUNDED_ECMP_PARENT_NETWORKS = {
    "ebgp_v6": IXIA_EBGP_IC_PARENT_NETWORK_V6,
    "ebgp_v4": IXIA_EBGP_IC_PARENT_NETWORK_V4,
    "ibgp_v6": IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
    "ibgp_v4": IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
}
BOUNDED_ECMP_AS_NUMBERS = {
    "ebgp": EBGP_REMOTE_AS,
    "ibgp": IBGP_REMOTE_AS,
}

BOUNDED_ECMP_EBGP_V6_PEER_GROUP = BgpPeerGroup(
    name=PEERGROUP_EBGP_V6,
    remote_asn="ebgp",
)
BOUNDED_ECMP_EBGP_V4_PEER_GROUP = BgpPeerGroup(
    name=PEERGROUP_EBGP_V4,
    remote_asn="ebgp",
)
BOUNDED_ECMP_IBGP_V6_PEER_GROUP = BgpPeerGroup(
    name=PEERGROUP_IBGP_V6,
    local_asn="ibgp",
    remote_asn="ibgp",
    enable_graceful_restart=False,
)
BOUNDED_ECMP_IBGP_V4_PEER_GROUP = BgpPeerGroup(
    name=PEERGROUP_IBGP_V4,
    local_asn="ibgp",
    remote_asn="ibgp",
    enable_graceful_restart=False,
)
BOUNDED_ECMP_PEER_GROUPS = {
    peer_group.name: peer_group
    for peer_group in (
        BOUNDED_ECMP_EBGP_V6_PEER_GROUP,
        BOUNDED_ECMP_EBGP_V4_PEER_GROUP,
        BOUNDED_ECMP_IBGP_V6_PEER_GROUP,
        BOUNDED_ECMP_IBGP_V4_PEER_GROUP,
    )
}

BOUNDED_ECMP_ROUTE_ATTRIBUTES = RouteAttributePool(
    community_rows=((StandardCommunity(asn=65529, value=39744),),),
    distribution=RouteAttributeDistribution.ROUND_ROBIN,
)

BOUNDED_ECMP_EBGP_V6_PREFIX_SET = PrefixSet(
    name="bounded_ecmp_ebgp_v6",
    afi="v6",
    source=FormulaicPrefixSource(
        start_prefix="2001:db8:1000::",
        prefix_step=1 << 64,
        prefix_length=64,
        count=BOUNDED_ECMP_PREFIX_COUNT,
        parent_network="2001:db8::/32",
    ),
)
BOUNDED_ECMP_EBGP_V4_PREFIX_SET = PrefixSet(
    name="bounded_ecmp_ebgp_v4",
    afi="v4",
    source=FormulaicPrefixSource(
        start_prefix="10.100.0.0",
        prefix_step=1 << 8,
        prefix_length=24,
        count=BOUNDED_ECMP_PREFIX_COUNT,
        parent_network="10.0.0.0/8",
    ),
)

BOUNDED_ECMP_EBGP_V6_ADVERTISEMENT = PrefixAdvertisement(
    name="bounded_ecmp_ebgp_v6_routes",
    prefix_set=BOUNDED_ECMP_EBGP_V6_PREFIX_SET.name,
    allocation=PrefixAllocation(
        prefixes_per_peer=BOUNDED_ECMP_PREFIX_COUNT,
        peer_distribution=PeerPrefixDistribution.SHARED,
        network_group_index=0,
    ),
    membership=PrefixMembership(
        start_index=0,
        prefix_count=BOUNDED_ECMP_PREFIX_COUNT,
    ),
    next_hop=NextHopIntent(
        mode=NextHopMode.SELF,
        self_realization=(SelfNextHopRealization.ADVERTISING_SESSION_LOCAL_ADDRESS),
    ),
    route_attributes=BOUNDED_ECMP_ROUTE_ATTRIBUTES,
)
BOUNDED_ECMP_EBGP_V4_ADVERTISEMENT = PrefixAdvertisement(
    name="bounded_ecmp_ebgp_v4_routes",
    prefix_set=BOUNDED_ECMP_EBGP_V4_PREFIX_SET.name,
    allocation=PrefixAllocation(
        prefixes_per_peer=BOUNDED_ECMP_PREFIX_COUNT,
        peer_distribution=PeerPrefixDistribution.SHARED,
        network_group_index=0,
    ),
    membership=PrefixMembership(
        start_index=0,
        prefix_count=BOUNDED_ECMP_PREFIX_COUNT,
    ),
    next_hop=NextHopIntent(
        mode=NextHopMode.SELF,
        self_realization=(SelfNextHopRealization.ADVERTISING_SESSION_LOCAL_ADDRESS),
    ),
    route_attributes=BOUNDED_ECMP_ROUTE_ATTRIBUTES,
)

_EBGP_PORT_ASSIGNMENT = IxiaPortAssignment(
    logical_role="ebgp",
    reuse_group="bounded_ecmp_ebgp",
)
_IBGP_PORT_ASSIGNMENT = IxiaPortAssignment(
    logical_role="ibgp",
    reuse_group="bounded_ecmp_ibgp",
)


def _ebgp_children(afi: str, legacy_afi: str) -> tuple[IxiaDeviceGroupChild, ...]:
    return tuple(
        IxiaDeviceGroupChild(
            name=f"bounded_ecmp_ebgp_{afi}_set{ordinal + 1}",
            ordinal=ordinal,
            start_index=start_index,
            peer_count=peer_count,
            legacy_ixia_device_group_name=(
                f"DEVICE_GROUP_{legacy_afi}_EBGP_SET{ordinal + 1}"
            ),
            legacy_ixia_bgp_peer_name=(f"BGP_PEER_{legacy_afi}_EBGP_SET{ordinal + 1}"),
            legacy_ixia_prefix_pool_name=(
                f"PREFIX_POOL_{legacy_afi}_EBGP_SET{ordinal + 1}"
            ),
            legacy_ixia_device_group_index=legacy_index,
        )
        for ordinal, (start_index, peer_count, legacy_index) in enumerate(
            ((0, 42, 0), (42, 42, 1), (84, 44, 2))
            if afi == "v6"
            else ((0, 42, 3), (42, 42, 4), (84, 44, 5))
        )
    )


def _ibgp_child(
    afi: str, legacy_afi: str, legacy_index: int
) -> tuple[IxiaDeviceGroupChild, ...]:
    return (
        IxiaDeviceGroupChild(
            name=f"bounded_ecmp_ibgp_{afi}",
            ordinal=0,
            start_index=0,
            peer_count=BOUNDED_ECMP_PEER_COUNT,
            legacy_ixia_device_group_name=f"DEVICE_GROUP_{legacy_afi}_IBGP",
            legacy_ixia_bgp_peer_name=f"BGP_PEER_{legacy_afi}_IBGP",
            legacy_ixia_device_group_index=legacy_index,
        ),
    )


BOUNDED_ECMP = LogicalTopology(
    name="bounded_ecmp",
    legacy_profile="bounded_ecmp",
    endpoints=(
        EndpointSpec(name="dut0", role="dut", kind="dut", setup_mode="full"),
        EndpointSpec(name="ixia", role="trafficgen", kind="ixia", setup_mode="full"),
    ),
    device_groups=(
        DeviceGroupSpec(
            name="dg_bounded_ecmp_ebgp_v6",
            role="ebgp",
            peer_relationship=PeerRelationship.EXTERNAL,
            afi="v6",
            peer_count=BOUNDED_ECMP_PEER_COUNT,
            address_plan=AddressPlan(
                afi="v6",
                parent_network_key="ebgp_v6",
                a_offset=16,
                z_offset=17,
                stride=2,
                prefix_length=127,
            ),
            peer_group=BOUNDED_ECMP_EBGP_V6_PEER_GROUP,
            prefix_advertisements=(BOUNDED_ECMP_EBGP_V6_ADVERTISEMENT,),
            port_assignment=_EBGP_PORT_ASSIGNMENT,
            ixia_children=_ebgp_children("v6", "IPV6"),
        ),
        DeviceGroupSpec(
            name="dg_bounded_ecmp_ebgp_v4",
            role="ebgp",
            peer_relationship=PeerRelationship.EXTERNAL,
            afi="v4",
            peer_count=BOUNDED_ECMP_PEER_COUNT,
            address_plan=AddressPlan(
                afi="v4",
                parent_network_key="ebgp_v4",
                a_offset=10,
                z_offset=11,
                stride=2,
                prefix_length=31,
            ),
            peer_group=BOUNDED_ECMP_EBGP_V4_PEER_GROUP,
            prefix_advertisements=(BOUNDED_ECMP_EBGP_V4_ADVERTISEMENT,),
            port_assignment=_EBGP_PORT_ASSIGNMENT,
            ixia_children=_ebgp_children("v4", "IPV4"),
        ),
        DeviceGroupSpec(
            name="dg_bounded_ecmp_ibgp_v6",
            role="ibgp",
            peer_relationship=PeerRelationship.INTERNAL,
            afi="v6",
            peer_count=BOUNDED_ECMP_PEER_COUNT,
            address_plan=AddressPlan(
                afi="v6",
                parent_network_key="ibgp_v6",
                a_offset=16,
                z_offset=17,
                stride=2,
                prefix_length=127,
            ),
            peer_group=BOUNDED_ECMP_IBGP_V6_PEER_GROUP,
            port_assignment=_IBGP_PORT_ASSIGNMENT,
            ixia_children=_ibgp_child("v6", "IPV6", 0),
        ),
        DeviceGroupSpec(
            name="dg_bounded_ecmp_ibgp_v4",
            role="ibgp",
            peer_relationship=PeerRelationship.INTERNAL,
            afi="v4",
            peer_count=BOUNDED_ECMP_PEER_COUNT,
            address_plan=AddressPlan(
                afi="v4",
                parent_network_key="ibgp_v4",
                a_offset=10,
                z_offset=11,
                stride=2,
                prefix_length=31,
            ),
            peer_group=BOUNDED_ECMP_IBGP_V4_PEER_GROUP,
            port_assignment=_IBGP_PORT_ASSIGNMENT,
            ixia_children=_ibgp_child("v4", "IPV4", 1),
        ),
    ),
    device_config=RoutingDeviceConfig(
        update_group_enable=True,
        openr_mode=OpenRMode.NONE,
    ),
    peer_groups=tuple(BOUNDED_ECMP_PEER_GROUPS.values()),
    prefix_sets=(
        BOUNDED_ECMP_EBGP_V6_PREFIX_SET,
        BOUNDED_ECMP_EBGP_V4_PREFIX_SET,
    ),
    route_senders=(
        RouteSender(
            device_group="dg_bounded_ecmp_ebgp_v6",
            prefix_advertisement=BOUNDED_ECMP_EBGP_V6_ADVERTISEMENT.name,
        ),
        RouteSender(
            device_group="dg_bounded_ecmp_ebgp_v4",
            prefix_advertisement=BOUNDED_ECMP_EBGP_V4_ADVERTISEMENT.name,
        ),
    ),
)


__all__ = (
    "BOUNDED_ECMP",
    "BOUNDED_ECMP_AS_NUMBERS",
    "BOUNDED_ECMP_EBGP_V4_ADVERTISEMENT",
    "BOUNDED_ECMP_EBGP_V4_PEER_GROUP",
    "BOUNDED_ECMP_EBGP_V4_PREFIX_SET",
    "BOUNDED_ECMP_EBGP_V6_ADVERTISEMENT",
    "BOUNDED_ECMP_EBGP_V6_PEER_GROUP",
    "BOUNDED_ECMP_EBGP_V6_PREFIX_SET",
    "BOUNDED_ECMP_IBGP_V4_PEER_GROUP",
    "BOUNDED_ECMP_IBGP_V6_PEER_GROUP",
    "BOUNDED_ECMP_PARENT_NETWORKS",
    "BOUNDED_ECMP_PEER_COUNT",
    "BOUNDED_ECMP_PEER_GROUPS",
    "BOUNDED_ECMP_PORT_MAP",
    "BOUNDED_ECMP_PREFIX_COUNT",
    "BOUNDED_ECMP_ROUTE_ATTRIBUTES",
)
