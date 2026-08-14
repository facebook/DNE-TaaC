# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from taac.abstractions.compatibility.eos_bgpcpp_compatibility import (
    EBB_BGPCPP_LOGGING_CONFIG,
)
from taac.abstractions.compatibility.legacy_ebb_binding import (
    IXIA_EBGP_IC_PARENT_NETWORK_V6,
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
    BgpPolicy,
    DeviceGroupSpec,
    EndpointSpec,
    FormulaicPrefixSource,
    IxiaBgpSessionIntent,
    IxiaEndpointPortLabelStyle,
    IxiaPortAssignment,
    LogicalTopology,
    OpenRMode,
    PeerPrefixDistribution,
    PrefixAdvertisement,
    PrefixAllocation,
    PrefixMembership,
    PrefixSet,
    RoutingDeviceConfig,
)

UG_NEW_PEER_JOIN_PORT_MAP = {"ebgp": 0, "ibgp": 1}
_UG_EBGP_PORT_ASSIGNMENT = IxiaPortAssignment(
    logical_role="ebgp",
    reuse_group="ug_ebgp",
    endpoint_label_style=IxiaEndpointPortLabelStyle.CHASSIS_PORT,
)
_UG_IBGP_PORT_ASSIGNMENT = IxiaPortAssignment(
    logical_role="ibgp",
    reuse_group="ug_ibgp",
    endpoint_label_style=IxiaEndpointPortLabelStyle.CHASSIS_PORT,
)
UG_NEW_PEER_JOIN_PARENT_NETWORKS = {
    "ug_ebgp_v6": IXIA_EBGP_IC_PARENT_NETWORK_V6,
    "ug_ibgp_v6": IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
}
UG_NEW_PEER_JOIN_AS_NUMBERS = {
    "ebgp": EBGP_REMOTE_AS,
    "ibgp": IBGP_REMOTE_AS,
}

_UG_IXIA_BGP_SESSION = IxiaBgpSessionIntent(address_prefix_length=127)

UG_EBGP_PEER_GROUP = BgpPeerGroup(
    name="EB-FA-V6",
    remote_asn="ebgp",
    hold_timer_s=30,
    keepalive_timer_s=10,
    enable_graceful_restart=True,
    ixia_session=_UG_IXIA_BGP_SESSION,
)
UG_IBGP_PEER_GROUP = BgpPeerGroup(
    name="EB-EB-V6",
    local_asn="ibgp",
    remote_asn="ibgp",
    hold_timer_s=30,
    keepalive_timer_s=10,
    enable_graceful_restart=True,
    ixia_session=_UG_IXIA_BGP_SESSION,
)
UG_NEW_PEER_JOIN_PEER_GROUPS = {
    UG_EBGP_PEER_GROUP.name: UG_EBGP_PEER_GROUP,
    UG_IBGP_PEER_GROUP.name: UG_IBGP_PEER_GROUP,
}

UG_INITIAL_COMMUNITY = "65529:39744"
UG_MUTATED_COMMUNITY = "65531:50200"
UG_BASE_SENDER_COMMUNITIES = (
    "65060:10012",
    "65140:65529",
    "65520:503",
    "65529:11610",
    UG_INITIAL_COMMUNITY,
    "65530:50300",
    "65530:50320",
    "65530:50800",
)
UG_MUTATED_SENDER_COMMUNITIES = tuple(
    UG_MUTATED_COMMUNITY if community == UG_INITIAL_COMMUNITY else community
    for community in UG_BASE_SENDER_COMMUNITIES
)

UG_BASE_SENDER_POLICY = BgpPolicy(
    name="ug_base_sender_communities",
    communities=UG_BASE_SENDER_COMMUNITIES,
)
UG_MUTATED_SENDER_POLICY = BgpPolicy(
    name="ug_mutated_sender_communities",
    communities=UG_MUTATED_SENDER_COMMUNITIES,
)

UG_KEEP_PREFIX_SET = PrefixSet(
    name="ug_keep",
    afi="v6",
    source=FormulaicPrefixSource(
        start_prefix="2401:db00:1000::",
        prefix_step=1,
        prefix_length=128,
        count=300,
        parent_network="2401:db00:1000::/64",
    ),
)
UG_VAR1_PREFIX_SET = PrefixSet(
    name="ug_var1",
    afi="v6",
    source=FormulaicPrefixSource(
        start_prefix="2401:db00:2000::",
        prefix_step=1,
        prefix_length=128,
        count=200,
        parent_network="2401:db00:2000::/64",
    ),
)
UG_VAR2_PREFIX_SET = PrefixSet(
    name="ug_var2",
    afi="v6",
    source=FormulaicPrefixSource(
        start_prefix="2401:db00:3000::",
        prefix_step=1,
        prefix_length=128,
        count=50,
        parent_network="2401:db00:3000::/64",
    ),
)


def _ug_advertisement(
    *,
    name: str,
    prefix_set: PrefixSet,
    policy: BgpPolicy,
) -> PrefixAdvertisement:
    return PrefixAdvertisement(
        name=name,
        prefix_set=prefix_set.name,
        allocation=PrefixAllocation(
            prefixes_per_peer=prefix_set.source.count,
            peer_distribution=PeerPrefixDistribution.SHARED,
        ),
        membership=PrefixMembership(
            start_index=0,
            prefix_count=prefix_set.source.count,
        ),
        policy=policy,
    )


UG_NEW_PEER_JOIN = LogicalTopology(
    name="ug_new_peer_join",
    legacy_profile="ug_new_peer_join",
    endpoints=(
        EndpointSpec(name="dut0", role="dut", kind="dut", setup_mode="full"),
        EndpointSpec(name="ixia", role="trafficgen", kind="ixia", setup_mode="full"),
    ),
    device_groups=(
        DeviceGroupSpec(
            name="dg_ug_ebgp_ctrl",
            role="ebgp_ug_ctrl",
            peer_relationship=PeerRelationship.EXTERNAL,
            afi="v6",
            peer_count=4,
            address_plan=AddressPlan(
                afi="v6",
                parent_network_key="ug_ebgp_v6",
                stride=2,
                prefix_length=127,
                start_index=0,
            ),
            peer_group=UG_EBGP_PEER_GROUP,
            legacy_ixia_tag_name="BGP_PEER_IPV6_EBGP_UG_CTRL",
            port_assignment=_UG_EBGP_PORT_ASSIGNMENT,
            legacy_ixia_device_group_index=0,
        ),
        DeviceGroupSpec(
            name="dg_ug_ebgp_held",
            role="ebgp_ug_held",
            peer_relationship=PeerRelationship.EXTERNAL,
            afi="v6",
            peer_count=1,
            address_plan=AddressPlan(
                afi="v6",
                parent_network_key="ug_ebgp_v6",
                stride=2,
                prefix_length=127,
                start_index=4,
            ),
            peer_group=UG_EBGP_PEER_GROUP,
            legacy_ixia_tag_name="BGP_PEER_IPV6_EBGP_UG_HELD",
            port_assignment=_UG_EBGP_PORT_ASSIGNMENT,
            legacy_ixia_device_group_index=1,
        ),
        DeviceGroupSpec(
            name="dg_ug_ebgp_disp",
            role="ebgp_ug_disp",
            peer_relationship=PeerRelationship.EXTERNAL,
            afi="v6",
            peer_count=16,
            address_plan=AddressPlan(
                afi="v6",
                parent_network_key="ug_ebgp_v6",
                stride=2,
                prefix_length=127,
                start_index=5,
            ),
            peer_group=UG_EBGP_PEER_GROUP,
            legacy_ixia_tag_name="BGP_PEER_IPV6_EBGP_UG_DISP",
            port_assignment=_UG_EBGP_PORT_ASSIGNMENT,
            legacy_ixia_device_group_index=2,
        ),
        DeviceGroupSpec(
            name="dg_ug_ibgp_keep_initial",
            role="ibgp_ug_keep_initial",
            peer_relationship=PeerRelationship.INTERNAL,
            afi="v6",
            peer_count=1,
            address_plan=AddressPlan(
                afi="v6",
                parent_network_key="ug_ibgp_v6",
                stride=2,
                prefix_length=127,
                start_index=0,
            ),
            peer_group=UG_IBGP_PEER_GROUP,
            prefix_advertisements=(
                _ug_advertisement(
                    name="ug_keep_initial",
                    prefix_set=UG_KEEP_PREFIX_SET,
                    policy=UG_BASE_SENDER_POLICY,
                ),
            ),
            legacy_ixia_tag_name="BGP_PEER_IPV6_IBGP_UG_B_KEEP",
            port_assignment=_UG_IBGP_PORT_ASSIGNMENT,
            legacy_ixia_device_group_index=0,
        ),
        DeviceGroupSpec(
            name="dg_ug_ibgp_keep_mutated",
            role="ibgp_ug_keep_mutated",
            peer_relationship=PeerRelationship.INTERNAL,
            afi="v6",
            peer_count=1,
            address_plan=AddressPlan(
                afi="v6",
                parent_network_key="ug_ibgp_v6",
                stride=2,
                prefix_length=127,
                start_index=1,
            ),
            peer_group=UG_IBGP_PEER_GROUP,
            prefix_advertisements=(
                _ug_advertisement(
                    name="ug_keep_mutated",
                    prefix_set=UG_KEEP_PREFIX_SET,
                    policy=UG_MUTATED_SENDER_POLICY,
                ),
            ),
            legacy_ixia_tag_name="BGP_PEER_IPV6_IBGP_UG_B_KEEP_MUTATED",
            port_assignment=_UG_IBGP_PORT_ASSIGNMENT,
            legacy_ixia_device_group_index=1,
        ),
        DeviceGroupSpec(
            name="dg_ug_ibgp_var1",
            role="ibgp_ug_var1",
            peer_relationship=PeerRelationship.INTERNAL,
            afi="v6",
            peer_count=1,
            address_plan=AddressPlan(
                afi="v6",
                parent_network_key="ug_ibgp_v6",
                stride=2,
                prefix_length=127,
                start_index=2,
            ),
            peer_group=UG_IBGP_PEER_GROUP,
            prefix_advertisements=(
                _ug_advertisement(
                    name="ug_var1",
                    prefix_set=UG_VAR1_PREFIX_SET,
                    policy=UG_BASE_SENDER_POLICY,
                ),
            ),
            legacy_ixia_tag_name="BGP_PEER_IPV6_IBGP_UG_B_VAR1",
            port_assignment=_UG_IBGP_PORT_ASSIGNMENT,
            legacy_ixia_device_group_index=2,
        ),
        DeviceGroupSpec(
            name="dg_ug_ibgp_var2",
            role="ibgp_ug_var2",
            peer_relationship=PeerRelationship.INTERNAL,
            afi="v6",
            peer_count=1,
            address_plan=AddressPlan(
                afi="v6",
                parent_network_key="ug_ibgp_v6",
                stride=2,
                prefix_length=127,
                start_index=3,
            ),
            peer_group=UG_IBGP_PEER_GROUP,
            prefix_advertisements=(
                _ug_advertisement(
                    name="ug_var2",
                    prefix_set=UG_VAR2_PREFIX_SET,
                    policy=UG_BASE_SENDER_POLICY,
                ),
            ),
            legacy_ixia_tag_name="BGP_PEER_IPV6_IBGP_UG_B_VAR2",
            port_assignment=_UG_IBGP_PORT_ASSIGNMENT,
            legacy_ixia_device_group_index=3,
        ),
    ),
    device_config=RoutingDeviceConfig(
        update_group_enable=True,
        bgpcpp_logging_config_override=EBB_BGPCPP_LOGGING_CONFIG,
        openr_mode=OpenRMode.NONE,
    ),
    peer_groups=(UG_EBGP_PEER_GROUP, UG_IBGP_PEER_GROUP),
    policies=(UG_BASE_SENDER_POLICY, UG_MUTATED_SENDER_POLICY),
    prefix_sets=(UG_KEEP_PREFIX_SET, UG_VAR1_PREFIX_SET, UG_VAR2_PREFIX_SET),
)

# =============================================================================
# UG_ADD_PEER_DYNAMIC (spec 2.4.4 -- New Peer Added Dynamically via addPeer API)
#
# A DEDICATED topology for 2.4.4 so the shared UG_NEW_PEER_JOIN constant (and its
# bag012 BGP_UG_NEW_PEER_JOIN_TEST_CONFIG) stay byte-identical to master. It is
# UG_NEW_PEER_JOIN PLUS one spare eBGP receiver whose DUT /127 interface IP + IXIA
# session are provisioned like ctrl/held/disp, but whose DUT BGP *neighbor* is
# ABSENT from the static bgpcpp config at baseline -- the 2.4.4 playbook creates
# it at runtime via the addPeers control-plane thrift RPC. eBGP peer indices 0-20
# are taken (ctrl 0-3, held 4, disp 5-20); 21 is next. dg index 3 is next.
#
# It shares the compiler handler with UG_NEW_PEER_JOIN via
# ``legacy_profile="ug_new_peer_join"`` (see ``_is_ug_new_peer_join``); the spare
# is handled there as an OPTIONAL (0-or-1) eBGP group, so the spare-free
# UG_NEW_PEER_JOIN render is unchanged.
_UG_EBGP_SPARE_DG = DeviceGroupSpec(
    name="dg_ug_ebgp_spare",
    role="ebgp_ug_spare",
    peer_relationship=PeerRelationship.EXTERNAL,
    afi="v6",
    peer_count=1,
    address_plan=AddressPlan(
        afi="v6",
        parent_network_key="ug_ebgp_v6",
        stride=2,
        prefix_length=127,
        start_index=21,
    ),
    peer_group=UG_EBGP_PEER_GROUP,
    legacy_ixia_tag_name="BGP_PEER_IPV6_EBGP_UG_SPARE",
    port_assignment=_UG_EBGP_PORT_ASSIGNMENT,
    legacy_ixia_device_group_index=3,
    # DUT interface /127 + IXIA session provisioned, but NO baseline DUT BGP
    # neighbor -- spec 2.4.4 creates it at runtime via addPeers (skipped in the
    # bgpcpp peer plan; still present in the interface plan for the gateway IP).
    dut_neighbor_absent=True,
)

UG_ADD_PEER_DYNAMIC = LogicalTopology(
    name="ug_add_peer_dynamic",
    # Shared handler: same legacy_profile => routes through the ug_new_peer_join
    # compiler path (the spare is optional there).
    legacy_profile="ug_new_peer_join",
    endpoints=UG_NEW_PEER_JOIN.endpoints,
    device_groups=UG_NEW_PEER_JOIN.device_groups + (_UG_EBGP_SPARE_DG,),
    device_config=UG_NEW_PEER_JOIN.device_config,
    peer_groups=UG_NEW_PEER_JOIN.peer_groups,
    policies=UG_NEW_PEER_JOIN.policies,
    prefix_sets=UG_NEW_PEER_JOIN.prefix_sets,
)

__all__ = (
    "UG_ADD_PEER_DYNAMIC",
    "UG_BASE_SENDER_COMMUNITIES",
    "UG_INITIAL_COMMUNITY",
    "UG_MUTATED_COMMUNITY",
    "UG_MUTATED_SENDER_COMMUNITIES",
    "UG_NEW_PEER_JOIN",
    "UG_NEW_PEER_JOIN_AS_NUMBERS",
    "UG_NEW_PEER_JOIN_PARENT_NETWORKS",
    "UG_NEW_PEER_JOIN_PEER_GROUPS",
    "UG_NEW_PEER_JOIN_PORT_MAP",
)
