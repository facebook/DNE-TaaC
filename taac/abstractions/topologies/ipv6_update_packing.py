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
    OpenRMode,
    PeerPrefixDistribution,
    PrefixAdvertisement,
    PrefixAllocation,
    PrefixMembership,
    PrefixSet,
    RouteSender,
    RoutingDeviceConfig,
)
from taac.testconfigs.routing.util.bgp_ebb_constants import (
    EBGP_REMOTE_AS,
    IBGP_REMOTE_AS,
    IXIA_EBGP_IC_PARENT_NETWORK_V6,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
)


IPV6_UPDATE_PACKING_PORT_MAP = {"ebgp": 0, "ibgp": 1}
IPV6_UPDATE_PACKING_PARENT_NETWORKS = {
    "ebgp_v6": IXIA_EBGP_IC_PARENT_NETWORK_V6,
    "ibgp_v6": IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
}
IPV6_UPDATE_PACKING_AS_NUMBERS = {
    "ebgp": EBGP_REMOTE_AS,
    "ibgp": IBGP_REMOTE_AS,
}

IPV6_UPDATE_PACKING_EBGP_PEER_GROUP = BgpPeerGroup(
    name="EB-FA-V6",
    remote_asn="ebgp",
    hold_timer_s=30,
    keepalive_timer_s=10,
    enable_graceful_restart=True,
)
IPV6_UPDATE_PACKING_IBGP_PEER_GROUP = BgpPeerGroup(
    name="EB-EB-V6",
    local_asn="ibgp",
    remote_asn="ibgp",
    hold_timer_s=30,
    keepalive_timer_s=10,
    enable_graceful_restart=True,
)
IPV6_UPDATE_PACKING_PEER_GROUPS = {
    IPV6_UPDATE_PACKING_EBGP_PEER_GROUP.name: (IPV6_UPDATE_PACKING_EBGP_PEER_GROUP),
    IPV6_UPDATE_PACKING_IBGP_PEER_GROUP.name: (IPV6_UPDATE_PACKING_IBGP_PEER_GROUP),
}

IPV6_UPDATE_PACKING_PREFIX_SET = PrefixSet(
    name="ipv6_update_packing",
    afi="v6",
    source=FormulaicPrefixSource(
        start_prefix="5001:db8:1000::",
        prefix_step=1 << 80,
        prefix_length=64,
        count=10_000,
        parent_network="5001:db8::/32",
    ),
)
IPV6_UPDATE_PACKING_ADVERTISEMENT = PrefixAdvertisement(
    name="ipv6_update_packing_ebgp_routes",
    prefix_set=IPV6_UPDATE_PACKING_PREFIX_SET.name,
    allocation=PrefixAllocation(
        prefixes_per_peer=10_000,
        peer_distribution=PeerPrefixDistribution.SHARED,
        network_group_index=0,
    ),
    membership=PrefixMembership(start_index=0, prefix_count=10_000),
    legacy_ixia_name="PREFIX_POOL_IPV6_EBGP",
)

IPV6_UPDATE_PACKING = LogicalTopology(
    name="ipv6_update_packing",
    legacy_profile="ipv6_update_packing",
    endpoints=(
        EndpointSpec(name="dut0", role="dut", kind="dut", setup_mode="full"),
        EndpointSpec(name="ixia", role="trafficgen", kind="ixia", setup_mode="full"),
    ),
    device_groups=(
        DeviceGroupSpec(
            name="dg_ipv6_update_packing_ibgp",
            role="ibgp",
            afi="v6",
            peer_count=1,
            address_plan=AddressPlan(
                afi="v6",
                parent_network_key="ibgp_v6",
                stride=2,
                prefix_length=127,
                start_index=0,
            ),
            peer_group=IPV6_UPDATE_PACKING_IBGP_PEER_GROUP,
            legacy_ixia_bgp_peer_name="BGP_PEER_IPV6_IBGP",
            legacy_ixia_device_group_name="DEVICE_GROUP_IPV6_IBGP",
            port_assignment=IxiaPortAssignment(logical_role="ibgp"),
            legacy_ixia_device_group_index=0,
        ),
        DeviceGroupSpec(
            name="dg_ipv6_update_packing_ebgp",
            role="ebgp",
            afi="v6",
            peer_count=10,
            address_plan=AddressPlan(
                afi="v6",
                parent_network_key="ebgp_v6",
                stride=2,
                prefix_length=127,
                start_index=0,
            ),
            peer_group=IPV6_UPDATE_PACKING_EBGP_PEER_GROUP,
            prefix_advertisements=(IPV6_UPDATE_PACKING_ADVERTISEMENT,),
            legacy_ixia_bgp_peer_name="BGP_PEER_IPV6_EBGP",
            legacy_ixia_device_group_name="DEVICE_GROUP_IPV6_EBGP",
            port_assignment=IxiaPortAssignment(logical_role="ebgp"),
            legacy_ixia_device_group_index=0,
        ),
    ),
    device_config=RoutingDeviceConfig(
        update_group_enable=False,
        openr_mode=OpenRMode.NONE,
    ),
    peer_groups=(
        IPV6_UPDATE_PACKING_IBGP_PEER_GROUP,
        IPV6_UPDATE_PACKING_EBGP_PEER_GROUP,
    ),
    prefix_sets=(IPV6_UPDATE_PACKING_PREFIX_SET,),
    route_senders=(
        RouteSender(
            device_group="dg_ipv6_update_packing_ebgp",
            prefix_advertisement=IPV6_UPDATE_PACKING_ADVERTISEMENT.name,
        ),
    ),
)


__all__ = (
    "IPV6_UPDATE_PACKING",
    "IPV6_UPDATE_PACKING_ADVERTISEMENT",
    "IPV6_UPDATE_PACKING_AS_NUMBERS",
    "IPV6_UPDATE_PACKING_EBGP_PEER_GROUP",
    "IPV6_UPDATE_PACKING_IBGP_PEER_GROUP",
    "IPV6_UPDATE_PACKING_PARENT_NETWORKS",
    "IPV6_UPDATE_PACKING_PEER_GROUPS",
    "IPV6_UPDATE_PACKING_PORT_MAP",
    "IPV6_UPDATE_PACKING_PREFIX_SET",
)
