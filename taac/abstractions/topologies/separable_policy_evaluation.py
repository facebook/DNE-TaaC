# Copyright (c) Meta Platforms, Inc. and affiliates.

from __future__ import annotations

"""Logical topology for EBB characteristic 8 policy-cost evaluation.

The two policy arms intentionally share this exact route geometry.  One IPv4
and one IPv6 eBGP session advertise the same 50K-route, single-attribute
population; the Playbook activates prefixes in bounded half-open windows.
"""

from taac.abstractions.compatibility.eos_bgpcpp_compatibility import (
    PEERGROUP_EBGP_V4,
    PEERGROUP_EBGP_V6,
)
from taac.abstractions.compatibility.legacy_ebb_binding import (
    IXIA03_EBGP_IC_PARENT_NETWORK_V4,
    IXIA03_EBGP_IC_PARENT_NETWORK_V6,
    IXIA_EBGP_IC_PARENT_NETWORK_V4,
    IXIA_EBGP_IC_PARENT_NETWORK_V6,
)
from taac.abstractions.compatibility.legacy_ebb_topology import (
    EBGP_REMOTE_AS,
)
from taac.abstractions.routing_semantics import PeerRelationship
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
    SelfNextHopRealization,
    StandardCommunity,
)


SEPARABLE_POLICY_EVALUATION_PREFIX_COUNT = 50_000
SEPARABLE_POLICY_EVALUATION_SWEEP = (10_000, 20_000, 30_000, 40_000, 50_000)

SEPARABLE_POLICY_EVALUATION_PORT_MAP = {"ebgp": 0}
SEPARABLE_POLICY_EVALUATION_PARENT_NETWORKS = {
    "ebgp_v6": IXIA_EBGP_IC_PARENT_NETWORK_V6,
    "ebgp_v4": IXIA_EBGP_IC_PARENT_NETWORK_V4,
}
SEPARABLE_POLICY_EVALUATION_PARENT_NETWORKS_IXIA03 = {
    "ebgp_v6": IXIA03_EBGP_IC_PARENT_NETWORK_V6,
    "ebgp_v4": IXIA03_EBGP_IC_PARENT_NETWORK_V4,
}
SEPARABLE_POLICY_EVALUATION_AS_NUMBERS = {"ebgp": EBGP_REMOTE_AS}

SEPARABLE_POLICY_EVALUATION_EBGP_V6_PEER_GROUP = BgpPeerGroup(
    name=PEERGROUP_EBGP_V6,
    remote_asn="ebgp",
)
SEPARABLE_POLICY_EVALUATION_EBGP_V4_PEER_GROUP = BgpPeerGroup(
    name=PEERGROUP_EBGP_V4,
    remote_asn="ebgp",
)
SEPARABLE_POLICY_EVALUATION_PEER_GROUPS = {
    peer_group.name: peer_group
    for peer_group in (
        SEPARABLE_POLICY_EVALUATION_EBGP_V6_PEER_GROUP,
        SEPARABLE_POLICY_EVALUATION_EBGP_V4_PEER_GROUP,
    )
}

# Every route carries the same EBB-accepted community.  Keeping the attribute
# population constant is the defining control for G1-8.
SEPARABLE_POLICY_EVALUATION_ROUTE_ATTRIBUTES = RouteAttributePool(
    community_rows=((StandardCommunity(asn=65529, value=39744),),),
    distribution=RouteAttributeDistribution.ROUND_ROBIN,
)

SEPARABLE_POLICY_EVALUATION_V6_PREFIX_SET = PrefixSet(
    name="separable_policy_evaluation_v6",
    afi="v6",
    source=FormulaicPrefixSource(
        start_prefix="2402:db00::",
        prefix_step=1 << 64,
        prefix_length=64,
        count=SEPARABLE_POLICY_EVALUATION_PREFIX_COUNT,
        parent_network="2402:db00::/32",
    ),
)
SEPARABLE_POLICY_EVALUATION_V4_PREFIX_SET = PrefixSet(
    name="separable_policy_evaluation_v4",
    afi="v4",
    source=FormulaicPrefixSource(
        start_prefix="120.0.0.0",
        prefix_step=1 << 8,
        prefix_length=24,
        count=SEPARABLE_POLICY_EVALUATION_PREFIX_COUNT,
        parent_network="120.0.0.0/8",
    ),
)


def _advertisement(
    *, name: str, prefix_set: str, legacy_ixia_name: str
) -> PrefixAdvertisement:
    return PrefixAdvertisement(
        name=name,
        prefix_set=prefix_set,
        allocation=PrefixAllocation(
            prefixes_per_peer=SEPARABLE_POLICY_EVALUATION_PREFIX_COUNT,
            peer_distribution=PeerPrefixDistribution.SHARED,
            network_group_index=0,
        ),
        membership=PrefixMembership(
            start_index=0,
            prefix_count=SEPARABLE_POLICY_EVALUATION_PREFIX_COUNT,
        ),
        next_hop=NextHopIntent(
            mode=NextHopMode.SELF,
            self_realization=SelfNextHopRealization.ADVERTISING_SESSION_LOCAL_ADDRESS,
        ),
        route_attributes=SEPARABLE_POLICY_EVALUATION_ROUTE_ATTRIBUTES,
        legacy_ixia_name=legacy_ixia_name,
    )


SEPARABLE_POLICY_EVALUATION_V6_ADVERTISEMENT = _advertisement(
    name="separable_policy_evaluation_v6_routes",
    prefix_set=SEPARABLE_POLICY_EVALUATION_V6_PREFIX_SET.name,
    legacy_ixia_name="PREFIX_POOL_IPV6_EBGP",
)
SEPARABLE_POLICY_EVALUATION_V4_ADVERTISEMENT = _advertisement(
    name="separable_policy_evaluation_v4_routes",
    prefix_set=SEPARABLE_POLICY_EVALUATION_V4_PREFIX_SET.name,
    legacy_ixia_name="PREFIX_POOL_IPV4_EBGP",
)

_EBGP_PORT_ASSIGNMENT = IxiaPortAssignment(
    logical_role="ebgp",
    reuse_group="separable_policy_evaluation_ebgp",
)

SEPARABLE_POLICY_EVALUATION = LogicalTopology(
    name="separable_policy_evaluation",
    legacy_profile=None,
    endpoints=(
        EndpointSpec(name="dut0", role="dut", kind="dut", setup_mode="full"),
        EndpointSpec(name="ixia", role="trafficgen", kind="ixia", setup_mode="full"),
    ),
    device_groups=(
        DeviceGroupSpec(
            name="dg_separable_policy_evaluation_v6",
            role="ebgp",
            peer_relationship=PeerRelationship.EXTERNAL,
            afi="v6",
            peer_count=1,
            address_plan=AddressPlan(
                afi="v6",
                parent_network_key="ebgp_v6",
                stride=2,
                prefix_length=127,
            ),
            peer_group=SEPARABLE_POLICY_EVALUATION_EBGP_V6_PEER_GROUP,
            prefix_advertisements=(SEPARABLE_POLICY_EVALUATION_V6_ADVERTISEMENT,),
            legacy_ixia_bgp_peer_name="BGP_PEER_IPV6_EBGP",
            legacy_ixia_device_group_name="DEVICE_GROUP_IPV6_EBGP",
            port_assignment=_EBGP_PORT_ASSIGNMENT,
            legacy_ixia_device_group_index=0,
        ),
        DeviceGroupSpec(
            name="dg_separable_policy_evaluation_v4",
            role="ebgp",
            peer_relationship=PeerRelationship.EXTERNAL,
            afi="v4",
            peer_count=1,
            address_plan=AddressPlan(
                afi="v4",
                parent_network_key="ebgp_v4",
                stride=2,
                prefix_length=31,
            ),
            peer_group=SEPARABLE_POLICY_EVALUATION_EBGP_V4_PEER_GROUP,
            prefix_advertisements=(SEPARABLE_POLICY_EVALUATION_V4_ADVERTISEMENT,),
            legacy_ixia_bgp_peer_name="BGP_PEER_IPV4_EBGP",
            legacy_ixia_device_group_name="DEVICE_GROUP_IPV4_EBGP",
            port_assignment=_EBGP_PORT_ASSIGNMENT,
            legacy_ixia_device_group_index=1,
        ),
    ),
    device_config=RoutingDeviceConfig(
        update_group_enable=False,
        openr_mode=OpenRMode.NONE,
    ),
    peer_groups=(
        SEPARABLE_POLICY_EVALUATION_EBGP_V6_PEER_GROUP,
        SEPARABLE_POLICY_EVALUATION_EBGP_V4_PEER_GROUP,
    ),
    prefix_sets=(
        SEPARABLE_POLICY_EVALUATION_V6_PREFIX_SET,
        SEPARABLE_POLICY_EVALUATION_V4_PREFIX_SET,
    ),
    route_senders=(
        RouteSender(
            device_group="dg_separable_policy_evaluation_v6",
            prefix_advertisement=SEPARABLE_POLICY_EVALUATION_V6_ADVERTISEMENT.name,
        ),
        RouteSender(
            device_group="dg_separable_policy_evaluation_v4",
            prefix_advertisement=SEPARABLE_POLICY_EVALUATION_V4_ADVERTISEMENT.name,
        ),
    ),
)


__all__ = (
    "SEPARABLE_POLICY_EVALUATION",
    "SEPARABLE_POLICY_EVALUATION_AS_NUMBERS",
    "SEPARABLE_POLICY_EVALUATION_PARENT_NETWORKS",
    "SEPARABLE_POLICY_EVALUATION_PARENT_NETWORKS_IXIA03",
    "SEPARABLE_POLICY_EVALUATION_PEER_GROUPS",
    "SEPARABLE_POLICY_EVALUATION_PORT_MAP",
    "SEPARABLE_POLICY_EVALUATION_PREFIX_COUNT",
    "SEPARABLE_POLICY_EVALUATION_SWEEP",
)
