# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from taac.abstractions.topology import (
    AddressPlan,
    BgpPeerGroup,
    DeviceGroupSpec,
    EndpointSpec,
    FormulaicPrefixSource,
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
    StandardCommunity,
)
from taac.testconfigs.routing.util.bgp_ebb_constants import (
    EBGP_REMOTE_AS,
    IBGP_REMOTE_AS,
    IXIA_EBGP_IC_PARENT_NETWORK_V4,
    IXIA_EBGP_IC_PARENT_NETWORK_V6,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
    PEERGROUP_EBGP_V4,
    PEERGROUP_EBGP_V6,
    PEERGROUP_IBGP_V4,
    PEERGROUP_IBGP_V6,
)


EGRESS_PEER_SCALE_SWEEP_PEER_COUNTS = (100, 200, 300, 400, 500)
EGRESS_PEER_SCALE_PREFIX_COUNT = 50_000

EGRESS_PEER_SCALE_PORT_MAP = {"ebgp": 0, "ibgp": 1}
EGRESS_PEER_SCALE_PARENT_NETWORKS = {
    "ebgp_v6": IXIA_EBGP_IC_PARENT_NETWORK_V6,
    "ebgp_v4": IXIA_EBGP_IC_PARENT_NETWORK_V4,
    "ibgp_v6": IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
    "ibgp_v4": IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
}
EGRESS_PEER_SCALE_AS_NUMBERS = {
    "ebgp": EBGP_REMOTE_AS,
    "ibgp": IBGP_REMOTE_AS,
}

EGRESS_PEER_SCALE_EBGP_V6_PEER_GROUP = BgpPeerGroup(
    name=PEERGROUP_EBGP_V6,
    remote_asn="ebgp",
)
EGRESS_PEER_SCALE_EBGP_V4_PEER_GROUP = BgpPeerGroup(
    name=PEERGROUP_EBGP_V4,
    remote_asn="ebgp",
)
EGRESS_PEER_SCALE_IBGP_V6_PEER_GROUP = BgpPeerGroup(
    name=PEERGROUP_IBGP_V6,
    local_asn="ibgp",
    remote_asn="ibgp",
    enable_graceful_restart=False,
)
EGRESS_PEER_SCALE_IBGP_V4_PEER_GROUP = BgpPeerGroup(
    name=PEERGROUP_IBGP_V4,
    local_asn="ibgp",
    remote_asn="ibgp",
    enable_graceful_restart=False,
)
EGRESS_PEER_SCALE_PEER_GROUPS = {
    peer_group.name: peer_group
    for peer_group in (
        EGRESS_PEER_SCALE_EBGP_V6_PEER_GROUP,
        EGRESS_PEER_SCALE_EBGP_V4_PEER_GROUP,
        EGRESS_PEER_SCALE_IBGP_V6_PEER_GROUP,
        EGRESS_PEER_SCALE_IBGP_V4_PEER_GROUP,
    )
}

EGRESS_PEER_SCALE_ROUTE_ATTRIBUTES = RouteAttributePool(
    community_rows=((StandardCommunity(asn=65529, value=39744),),),
    distribution=RouteAttributeDistribution.ROUND_ROBIN,
)

EGRESS_PEER_SCALE_EBGP_V6_PREFIX_SET = PrefixSet(
    name="egress_peer_scale_ebgp_v6",
    afi="v6",
    source=FormulaicPrefixSource(
        start_prefix="2402:db00::",
        prefix_step=1 << 64,
        prefix_length=64,
        count=EGRESS_PEER_SCALE_PREFIX_COUNT,
        parent_network="2402:db00::/32",
    ),
)
EGRESS_PEER_SCALE_EBGP_V4_PREFIX_SET = PrefixSet(
    name="egress_peer_scale_ebgp_v4",
    afi="v4",
    source=FormulaicPrefixSource(
        start_prefix="120.0.0.0",
        prefix_step=1 << 8,
        prefix_length=24,
        count=EGRESS_PEER_SCALE_PREFIX_COUNT,
        parent_network="120.0.0.0/8",
    ),
)

EGRESS_PEER_SCALE_EBGP_V6_ADVERTISEMENT = PrefixAdvertisement(
    name="egress_peer_scale_ebgp_v6_routes",
    prefix_set=EGRESS_PEER_SCALE_EBGP_V6_PREFIX_SET.name,
    allocation=PrefixAllocation(
        prefixes_per_peer=EGRESS_PEER_SCALE_PREFIX_COUNT,
        peer_distribution=PeerPrefixDistribution.SHARED,
        network_group_index=0,
    ),
    membership=PrefixMembership(
        start_index=0,
        prefix_count=EGRESS_PEER_SCALE_PREFIX_COUNT,
    ),
    next_hop=NextHopIntent(mode=NextHopMode.SELF),
    route_attributes=EGRESS_PEER_SCALE_ROUTE_ATTRIBUTES,
    legacy_ixia_name="PREFIX_POOL_IPV6_EBGP",
)
EGRESS_PEER_SCALE_EBGP_V4_ADVERTISEMENT = PrefixAdvertisement(
    name="egress_peer_scale_ebgp_v4_routes",
    prefix_set=EGRESS_PEER_SCALE_EBGP_V4_PREFIX_SET.name,
    allocation=PrefixAllocation(
        prefixes_per_peer=EGRESS_PEER_SCALE_PREFIX_COUNT,
        peer_distribution=PeerPrefixDistribution.SHARED,
        network_group_index=0,
    ),
    membership=PrefixMembership(
        start_index=0,
        prefix_count=EGRESS_PEER_SCALE_PREFIX_COUNT,
    ),
    next_hop=NextHopIntent(mode=NextHopMode.SELF),
    route_attributes=EGRESS_PEER_SCALE_ROUTE_ATTRIBUTES,
    legacy_ixia_name="PREFIX_POOL_IPV4_EBGP",
)

_EBGP_PORT_ASSIGNMENT = IxiaPortAssignment(
    logical_role="ebgp",
    reuse_group="egress_peer_scale_ebgp",
)
_IBGP_PORT_ASSIGNMENT = IxiaPortAssignment(
    logical_role="ibgp",
    reuse_group="egress_peer_scale_ibgp",
)

EGRESS_PEER_SCALE = LogicalTopology(
    name="egress_peer_scale",
    legacy_profile="egress_peer_scale",
    endpoints=(
        EndpointSpec(name="dut0", role="dut", kind="dut", setup_mode="full"),
        EndpointSpec(name="ixia", role="trafficgen", kind="ixia", setup_mode="full"),
    ),
    device_groups=(
        DeviceGroupSpec(
            name="dg_egress_peer_scale_ebgp_v6",
            role="ebgp",
            afi="v6",
            peer_count=1,
            address_plan=AddressPlan(
                afi="v6",
                parent_network_key="ebgp_v6",
                stride=2,
                prefix_length=127,
            ),
            peer_group=EGRESS_PEER_SCALE_EBGP_V6_PEER_GROUP,
            prefix_advertisements=(EGRESS_PEER_SCALE_EBGP_V6_ADVERTISEMENT,),
            legacy_ixia_bgp_peer_name="BGP_PEER_IPV6_EBGP",
            legacy_ixia_device_group_name="DEVICE_GROUP_IPV6_EBGP",
            port_assignment=_EBGP_PORT_ASSIGNMENT,
            legacy_ixia_device_group_index=0,
        ),
        DeviceGroupSpec(
            name="dg_egress_peer_scale_ebgp_v4",
            role="ebgp",
            afi="v4",
            peer_count=1,
            address_plan=AddressPlan(
                afi="v4",
                parent_network_key="ebgp_v4",
                stride=2,
                prefix_length=31,
            ),
            peer_group=EGRESS_PEER_SCALE_EBGP_V4_PEER_GROUP,
            prefix_advertisements=(EGRESS_PEER_SCALE_EBGP_V4_ADVERTISEMENT,),
            legacy_ixia_bgp_peer_name="BGP_PEER_IPV4_EBGP",
            legacy_ixia_device_group_name="DEVICE_GROUP_IPV4_EBGP",
            port_assignment=_EBGP_PORT_ASSIGNMENT,
            legacy_ixia_device_group_index=1,
        ),
        DeviceGroupSpec(
            name="dg_egress_peer_scale_ibgp_v6",
            role="ibgp",
            afi="v6",
            peer_count=max(EGRESS_PEER_SCALE_SWEEP_PEER_COUNTS),
            address_plan=AddressPlan(
                afi="v6",
                parent_network_key="ibgp_v6",
                stride=2,
                prefix_length=127,
            ),
            peer_group=EGRESS_PEER_SCALE_IBGP_V6_PEER_GROUP,
            legacy_ixia_bgp_peer_name="BGP_PEER_IPV6_IBGP",
            legacy_ixia_device_group_name="DEVICE_GROUP_IPV6_IBGP",
            port_assignment=_IBGP_PORT_ASSIGNMENT,
            legacy_ixia_device_group_index=0,
        ),
        DeviceGroupSpec(
            name="dg_egress_peer_scale_ibgp_v4",
            role="ibgp",
            afi="v4",
            peer_count=max(EGRESS_PEER_SCALE_SWEEP_PEER_COUNTS),
            address_plan=AddressPlan(
                afi="v4",
                parent_network_key="ibgp_v4",
                stride=2,
                prefix_length=31,
            ),
            peer_group=EGRESS_PEER_SCALE_IBGP_V4_PEER_GROUP,
            legacy_ixia_bgp_peer_name="BGP_PEER_IPV4_IBGP",
            legacy_ixia_device_group_name="DEVICE_GROUP_IPV4_IBGP",
            port_assignment=_IBGP_PORT_ASSIGNMENT,
            legacy_ixia_device_group_index=1,
        ),
    ),
    device_config=RoutingDeviceConfig(
        update_group_enable=False,
        openr_mode=OpenRMode.NONE,
    ),
    peer_groups=tuple(EGRESS_PEER_SCALE_PEER_GROUPS.values()),
    prefix_sets=(
        EGRESS_PEER_SCALE_EBGP_V6_PREFIX_SET,
        EGRESS_PEER_SCALE_EBGP_V4_PREFIX_SET,
    ),
    route_senders=(
        RouteSender(
            device_group="dg_egress_peer_scale_ebgp_v6",
            prefix_advertisement=EGRESS_PEER_SCALE_EBGP_V6_ADVERTISEMENT.name,
        ),
        RouteSender(
            device_group="dg_egress_peer_scale_ebgp_v4",
            prefix_advertisement=EGRESS_PEER_SCALE_EBGP_V4_ADVERTISEMENT.name,
        ),
    ),
)


__all__ = (
    "EGRESS_PEER_SCALE",
    "EGRESS_PEER_SCALE_AS_NUMBERS",
    "EGRESS_PEER_SCALE_EBGP_V4_ADVERTISEMENT",
    "EGRESS_PEER_SCALE_EBGP_V4_PEER_GROUP",
    "EGRESS_PEER_SCALE_EBGP_V4_PREFIX_SET",
    "EGRESS_PEER_SCALE_EBGP_V6_ADVERTISEMENT",
    "EGRESS_PEER_SCALE_EBGP_V6_PEER_GROUP",
    "EGRESS_PEER_SCALE_EBGP_V6_PREFIX_SET",
    "EGRESS_PEER_SCALE_IBGP_V4_PEER_GROUP",
    "EGRESS_PEER_SCALE_IBGP_V6_PEER_GROUP",
    "EGRESS_PEER_SCALE_PARENT_NETWORKS",
    "EGRESS_PEER_SCALE_PEER_GROUPS",
    "EGRESS_PEER_SCALE_PORT_MAP",
    "EGRESS_PEER_SCALE_PREFIX_COUNT",
    "EGRESS_PEER_SCALE_ROUTE_ATTRIBUTES",
    "EGRESS_PEER_SCALE_SWEEP_PEER_COUNTS",
)
