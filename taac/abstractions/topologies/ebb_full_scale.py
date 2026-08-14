# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

import ipaddress
import typing as t
from dataclasses import dataclass, replace

from taac.abstractions.compatibility.eos_bgpcpp_compatibility import (
    EBB_BGPCPP_LOGGING_CONFIG,
    PEERGROUP_BGP_MON,
    PEERGROUP_EBGP_V4,
    PEERGROUP_EBGP_V6,
    PEERGROUP_IBGP_V4,
    PEERGROUP_IBGP_V6,
)
from taac.abstractions.compatibility.legacy_ebb_binding import (
    IXIA03_BGP_MON_IC_PARENT_NETWORK,
    IXIA03_EBGP_IC_PARENT_NETWORK_V4,
    IXIA03_EBGP_IC_PARENT_NETWORK_V6,
    IXIA03_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
    IXIA03_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE2,
    IXIA03_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE3,
    IXIA03_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE4,
    IXIA03_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE1,
    IXIA03_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE2,
    IXIA03_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE3,
    IXIA03_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE4,
    IXIA03_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
    IXIA03_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE2,
    IXIA03_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE3,
    IXIA03_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE4,
    IXIA03_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE1,
    IXIA03_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE2,
    IXIA03_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE3,
    IXIA03_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE4,
    IXIA_BGP_MON_IC_PARENT_NETWORK,
    IXIA_EBGP_IC_PARENT_NETWORK_V4,
    IXIA_EBGP_IC_PARENT_NETWORK_V6,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE2,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE3,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE4,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE1,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE2,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE3,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE4,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE2,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE3,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE4,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE1,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE2,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE3,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE4,
)
from taac.abstractions.compatibility.legacy_ebb_topology import (
    BGP_MON_PEER_COUNT,
    BGP_MON_REMOTE_AS,
    EBB_BGP_HOLD_TIMER_S,
    EBB_BGP_KEEPALIVE_TIMER_S,
    EBB_DEVICE_PER_PEER_MAX_ROUTE_LIMIT,
    EBB_DEVICE_PREFIX_LIMIT,
    EBB_DEVICE_ROUTE_LIMIT,
    EBGP_PEER_COUNT_V4,
    EBGP_PEER_COUNT_V6,
    EBGP_REMOTE_AS,
    IBGP_PEER_SCALE_PER_PLANE,
    IBGP_REMOTE_AS,
)
from taac.abstractions.routing_semantics import PeerRelationship
from taac.abstractions.topologies.ebb_prefix_inventory import (
    EBB_IBGP_V4_EXCLUDED_PREFIX_INDICES,
    EBB_IBGP_V6_EXCLUDED_PREFIX_INDICES,
)
from taac.abstractions.topology import (
    AddressPlan,
    AsPathSequence,
    BgpPeerGroup,
    BgpPolicy,
    DeviceGroupSpec,
    EndpointSpec,
    ExplicitNextHopSource,
    FormulaicNextHopSource,
    FormulaicPrefixSource,
    IxiaPortAssignment,
    LogicalTopology,
    NextHopDistribution,
    NextHopIntent,
    NextHopMode,
    OpenRMode,
    PeerPrefixDistribution,
    PrefixAdvertisement,
    PrefixAllocation,
    PrefixMembership,
    PrefixSet,
    RouteAttributePool,
    RoutingDeviceConfig,
    StandardCommunity,
)

EBB_PARENT_NETWORKS: dict[str, str] = {
    "ebgp_v6": IXIA_EBGP_IC_PARENT_NETWORK_V6,
    "ebgp_v4": IXIA_EBGP_IC_PARENT_NETWORK_V4,
    "ibgp_dc_p1_v6": IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
    "ibgp_dc_p2_v6": IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE2,
    "ibgp_dc_p3_v6": IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE3,
    "ibgp_dc_p4_v6": IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE4,
    "ibgp_mp_p1_v6": IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE1,
    "ibgp_mp_p2_v6": IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE2,
    "ibgp_mp_p3_v6": IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE3,
    "ibgp_mp_p4_v6": IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE4,
    "ibgp_dc_p1_v4": IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
    "ibgp_dc_p2_v4": IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE2,
    "ibgp_dc_p3_v4": IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE3,
    "ibgp_dc_p4_v4": IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE4,
    "ibgp_mp_p1_v4": IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE1,
    "ibgp_mp_p2_v4": IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE2,
    "ibgp_mp_p3_v4": IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE3,
    "ibgp_mp_p4_v4": IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE4,
    "bgpmon_v6": IXIA_BGP_MON_IC_PARENT_NETWORK,
}

# Same topology against the secondary chassis (ixia03) instead of ixia11. The
# addressing has to be swapped alongside the ports: PhysicalInventory
# .for_secondary_ixia() moves which DUT interfaces are driven, but the parent
# networks are what TAAC programs onto the IXIA side, so leaving them at the
# ixia11 defaults would emulate peers the DUT has no gateway for and fail
# looking like a link fault. Keys must mirror EBB_PARENT_NETWORKS exactly.
EBB_PARENT_NETWORKS_IXIA03: dict[str, str] = {
    "ebgp_v6": IXIA03_EBGP_IC_PARENT_NETWORK_V6,
    "ebgp_v4": IXIA03_EBGP_IC_PARENT_NETWORK_V4,
    "ibgp_dc_p1_v6": IXIA03_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
    "ibgp_dc_p2_v6": IXIA03_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE2,
    "ibgp_dc_p3_v6": IXIA03_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE3,
    "ibgp_dc_p4_v6": IXIA03_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE4,
    "ibgp_mp_p1_v6": IXIA03_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE1,
    "ibgp_mp_p2_v6": IXIA03_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE2,
    "ibgp_mp_p3_v6": IXIA03_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE3,
    "ibgp_mp_p4_v6": IXIA03_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE4,
    "ibgp_dc_p1_v4": IXIA03_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
    "ibgp_dc_p2_v4": IXIA03_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE2,
    "ibgp_dc_p3_v4": IXIA03_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE3,
    "ibgp_dc_p4_v4": IXIA03_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE4,
    "ibgp_mp_p1_v4": IXIA03_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE1,
    "ibgp_mp_p2_v4": IXIA03_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE2,
    "ibgp_mp_p3_v4": IXIA03_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE3,
    "ibgp_mp_p4_v4": IXIA03_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE4,
    "bgpmon_v6": IXIA03_BGP_MON_IC_PARENT_NETWORK,
}

EBB_AS_NUMBERS: dict[str, int] = {
    "ebgp": EBGP_REMOTE_AS,
    "ibgp": IBGP_REMOTE_AS,
    "bgpmon": BGP_MON_REMOTE_AS,
}

EBB_ATTRIBUTE_CHURN_AS_PATH = (64512,) * 10
_EBB_ACCEPTANCE_COMMUNITY = StandardCommunity(asn=65529, value=39744)
_EBB_IBGP_ROUTE_ATTRIBUTES = RouteAttributePool(
    community_rows=tuple(
        (
            _EBB_ACCEPTANCE_COMMUNITY,
            StandardCommunity(asn=asn, value=value),
        )
        for asn, value in (
            (65060, 10012),
            (65140, 65529),
            (65520, 503),
            (65529, 11610),
            (65529, 39744),
            (65530, 50300),
            (65530, 50320),
            (65530, 50800),
        )
    ),
)
EBB_LONGEVITY_COMMUNITY_BASELINE_COUNT = len(
    _EBB_IBGP_ROUTE_ATTRIBUTES.community_rows[0]
)
EBB_ATTRIBUTE_CHURN_BASELINE = (
    ("med", 200),
    ("local_pref", 100),
    ("origin", "egp"),
)

EBGP_V6_PEER_GROUP = BgpPeerGroup(
    name=PEERGROUP_EBGP_V6,
    remote_asn="ebgp",
    enable_graceful_restart=True,
)
EBGP_V4_PEER_GROUP = BgpPeerGroup(
    name=PEERGROUP_EBGP_V4,
    remote_asn="ebgp",
    enable_graceful_restart=True,
)
IBGP_V6_PEER_GROUP = BgpPeerGroup(
    name=PEERGROUP_IBGP_V6,
    remote_asn="ibgp",
    enable_graceful_restart=False,
)
IBGP_V4_PEER_GROUP = BgpPeerGroup(
    name=PEERGROUP_IBGP_V4,
    remote_asn="ibgp",
    enable_graceful_restart=False,
)
BGP_MON_PEER_GROUP = BgpPeerGroup(
    name=PEERGROUP_BGP_MON,
    remote_asn="bgpmon",
    enable_graceful_restart=False,
)

EBB_PEER_GROUPS: dict[str, BgpPeerGroup] = {
    PEERGROUP_EBGP_V6: EBGP_V6_PEER_GROUP,
    PEERGROUP_EBGP_V4: EBGP_V4_PEER_GROUP,
    PEERGROUP_IBGP_V6: IBGP_V6_PEER_GROUP,
    PEERGROUP_IBGP_V4: IBGP_V4_PEER_GROUP,
    PEERGROUP_BGP_MON: BGP_MON_PEER_GROUP,
}

EBB_FULL_SCALE_PORT_MAP = {
    "uplink": 0,
    "ibgp": 1,
}
EBB_FULL_SCALE_PORT_MAP_WITH_BGPMON = {
    **EBB_FULL_SCALE_PORT_MAP,
    "bgpmon": 2,
}

_EBB_UPLINK_PORT_ASSIGNMENT = IxiaPortAssignment(
    logical_role="uplink",
    reuse_group="ebb_uplink",
)
_EBB_IBGP_PORT_ASSIGNMENT = IxiaPortAssignment(
    logical_role="ibgp",
    reuse_group="ebb_ibgp",
)
_EBB_BGPMON_PORT_ASSIGNMENT = IxiaPortAssignment(logical_role="bgpmon")

EBB_DEVICE_CONFIG = RoutingDeviceConfig(
    update_group_enable=False,
    bgpcpp_logging_config_override=EBB_BGPCPP_LOGGING_CONFIG,
    enable_next_hop_tracking=True,
    enable_dynamic_policy_evaluation=True,
    openr_mode=OpenRMode.NONE,
    prefix_limit=EBB_DEVICE_PREFIX_LIMIT,
    per_peer_max_route_limit=EBB_DEVICE_PER_PEER_MAX_ROUTE_LIMIT,
    route_limit=EBB_DEVICE_ROUTE_LIMIT,
    bgp_hold_timer_s=EBB_BGP_HOLD_TIMER_S,
    bgp_keepalive_timer_s=EBB_BGP_KEEPALIVE_TIMER_S,
)

EBB_EBGP_V6_PREFIX_SET = PrefixSet(
    name="ebb_ebgp_v6",
    afi="v6",
    source=FormulaicPrefixSource(
        start_prefix="2402:db00::",
        prefix_step=1 << 64,
        prefix_length=64,
        count=750,
        parent_network="2402:db00::/48",
    ),
)
EBB_EBGP_V4_PREFIX_SET = PrefixSet(
    name="ebb_ebgp_v4",
    afi="v4",
    source=FormulaicPrefixSource(
        start_prefix="120.0.0.0",
        prefix_step=1 << 8,
        prefix_length=24,
        count=750,
        parent_network="120.0.0.0/14",
    ),
)
EBB_IBGP_V6_PREFIX_SET = PrefixSet(
    name="ebb_ibgp_v6",
    afi="v6",
    source=FormulaicPrefixSource(
        start_prefix="2001:db8::",
        prefix_step=1 << 64,
        prefix_length=64,
        count=46_500,
        parent_network="2001:db8::/48",
        excluded_indices=EBB_IBGP_V6_EXCLUDED_PREFIX_INDICES,
    ),
)
EBB_IBGP_V4_PREFIX_SET = PrefixSet(
    name="ebb_ibgp_v4",
    afi="v4",
    source=FormulaicPrefixSource(
        start_prefix="11.0.0.0",
        prefix_step=1 << 8,
        prefix_length=24,
        count=46_500,
        parent_network="11.0.0.0/8",
        excluded_indices=EBB_IBGP_V4_EXCLUDED_PREFIX_INDICES,
    ),
)

EBB_PREFIX_SETS = (
    EBB_EBGP_V6_PREFIX_SET,
    EBB_EBGP_V4_PREFIX_SET,
    EBB_IBGP_V6_PREFIX_SET,
    EBB_IBGP_V4_PREFIX_SET,
)
EBB_ACCEPT_POLICY = BgpPolicy(
    name="ebb_accept",
    communities=("65529:39744",),
)


def _lexical_ip_range(start: str, count: int) -> tuple[str, ...]:
    first = ipaddress.ip_address(start)
    # IXIA's legacy EBB pools used string-lexical ordering; retain that observable
    # peer-to-next-hop association instead of silently normalizing numerically.
    return tuple(
        sorted(str(type(first)(int(first) + 2 * index)) for index in range(count))
    )


def _formulaic_next_hop(start: str, parent_network: str) -> NextHopIntent:
    return NextHopIntent(
        mode=NextHopMode.FORMULAIC,
        distribution=NextHopDistribution.PER_PEER,
        formulaic_source=FormulaicNextHopSource(
            start=start,
            step=2,
            parent_network=parent_network,
        ),
        description="externally resolved EBB next hops",
    )


def _explicit_next_hop(start: str, count: int, parent_network: str) -> NextHopIntent:
    return NextHopIntent(
        mode=NextHopMode.EXPLICIT,
        distribution=NextHopDistribution.PER_PEER,
        explicit_source=ExplicitNextHopSource(
            addresses=_lexical_ip_range(start, count),
            parent_network=parent_network,
        ),
        description="externally resolved EBB next hops",
    )


def _sequential_explicit_next_hop(
    start: str,
    count: int,
    parent_network: str,
) -> NextHopIntent:
    first = ipaddress.ip_address(start)
    return NextHopIntent(
        mode=NextHopMode.EXPLICIT,
        distribution=NextHopDistribution.PER_PEER,
        explicit_source=ExplicitNextHopSource(
            addresses=tuple(
                str(type(first)(int(first) + 2 * index)) for index in range(count)
            ),
            parent_network=parent_network,
        ),
        description="legacy per-peer EBB next hops",
    )


@dataclass(frozen=True)
class EbbNextHopScheme:
    """Chassis-specific bases for the next hops emulated peers advertise.

    These are built during topology construction, before ``bind_to_inventory``,
    so they cannot be read from ``parent_networks``. They also are not simply
    the peer subnets: the v6 iBGP next hops deliberately sit on different
    hextets from the peer parents, and the Open/R variants live in their own
    ``20.x`` / ``e80d`` space. What does move together across chassis is the
    numbering *structure*, so only the two bases that differ are captured here.

    Attributes:
        ebgp_v4_network: eBGP /23 base, e.g. ``"10.163.28"``.
        ebgp_v6_network: eBGP /80 base, e.g. ``"2401:db00:e50d:11:8"``.
        ibgp_v4_plane_base: Second octet that plane N counts from, so plane N
            is ``<first>.<base + N>.28.0/24``. Equals the eBGP second octet.
        ibgp_v6_group: Fourth hextet identifying the chassis, e.g. ``"11"``.
    """

    ebgp_v4_network: str
    ebgp_v6_network: str
    ibgp_v4_plane_base: int
    ibgp_v6_group: str


EBB_NEXT_HOPS: EbbNextHopScheme = EbbNextHopScheme(
    ebgp_v4_network=IXIA_EBGP_IC_PARENT_NETWORK_V4,
    ebgp_v6_network=IXIA_EBGP_IC_PARENT_NETWORK_V6,
    ibgp_v4_plane_base=163,
    ibgp_v6_group="11",
)

EBB_NEXT_HOPS_IXIA03: EbbNextHopScheme = EbbNextHopScheme(
    ebgp_v4_network=IXIA03_EBGP_IC_PARENT_NETWORK_V4,
    ebgp_v6_network=IXIA03_EBGP_IC_PARENT_NETWORK_V6,
    ibgp_v4_plane_base=180,
    ibgp_v6_group="33",
)


def _ebb_ibgp_next_hop_source(
    afi: str,
    plane: int,
    openr_mode: OpenRMode,
    next_hops: EbbNextHopScheme = EBB_NEXT_HOPS,
) -> tuple[str, str, bool]:
    if afi not in {"v4", "v6"}:
        raise ValueError(f"EBB iBGP next-hop AFI must be v4 or v6; got {afi!r}")
    if not 1 <= plane <= 4:
        raise ValueError(
            f"EBB iBGP next-hop plane must be between 1 and 4; got {plane}"
        )
    openr_enabled = openr_mode is OpenRMode.STANDALONE
    if afi == "v4":
        first_octet = 20 if openr_enabled else 10
        second_octet = next_hops.ibgp_v4_plane_base + plane
        return (
            f"{first_octet}.{second_octet}.28.10",
            f"{first_octet}.{second_octet}.28.0/24",
            True,
        )

    # Legacy OpenR CSVs and KV injection use the literal slots 9/10/11/12.
    # Non-OpenR DC planes use hexadecimal slots a/b/c/9.
    slot = str(plane + 8) if openr_enabled else f"{9 if plane == 4 else plane + 9:x}"
    fabric = "e80d" if openr_enabled else "e50d"
    start = f"2401:db00:{fabric}:{next_hops.ibgp_v6_group}:{slot}::10"
    return start, str(ipaddress.ip_network(f"{start}/80", strict=False)), False


def ebb_openr_injected_next_hops(
    next_hops: EbbNextHopScheme = EBB_NEXT_HOPS,
) -> tuple[list[str], list[str]]:
    """Return the (v4, v6) plane next hops Open/R must inject reachability for.

    The emulated peers advertise routes whose iBGP next hops come from
    ``_ebb_ibgp_next_hop_source``; those next hops only resolve because Open/R
    injects a route covering each one. Expressing the injection set separately
    from the advertised set lets the two drift, and on a chassis whose scheme
    differs the drift is silent: the routes still arrive and sit in the RIB,
    but none become installable, so the shadow RIB and everything advertised
    downstream collapse to whatever else happens to resolve. Deriving both from
    one scheme is what keeps them in step.

    Args:
        next_hops: Chassis scheme; defaults to ixia11.

    Returns:
        Parallel lists of the four plane start addresses, v4 first.
    """
    v4_starts: list[str] = []
    v6_starts: list[str] = []
    for plane in range(1, 5):
        v4_starts.append(
            _ebb_ibgp_next_hop_source("v4", plane, OpenRMode.STANDALONE, next_hops)[0]
        )
        v6_starts.append(
            _ebb_ibgp_next_hop_source("v6", plane, OpenRMode.STANDALONE, next_hops)[0]
        )
    return v4_starts, v6_starts


def ebb_ibgp_route_next_hops(
    afi: str,
    plane: int,
    peer_count: int,
    openr_mode: OpenRMode,
    next_hops: EbbNextHopScheme = EBB_NEXT_HOPS,
) -> tuple[str, ...]:
    """Return the route next hop associated with each EBB iBGP peer row.

    Args:
        afi: ``"v4"`` or ``"v6"``.
        plane: iBGP plane, 1-4.
        peer_count: Number of peer rows to generate next hops for.
        openr_mode: Selects the Open/R next-hop space when STANDALONE.
        next_hops: Chassis scheme; defaults to ixia11.
    """
    if peer_count < 1:
        raise ValueError(f"EBB iBGP peer count must be positive; got {peer_count}")
    start, _parent, lexical = _ebb_ibgp_next_hop_source(
        afi, plane, openr_mode, next_hops
    )
    if lexical:
        return _lexical_ip_range(start, peer_count)
    first = ipaddress.ip_address(start)
    return tuple(
        str(type(first)(int(first) + 2 * index)) for index in range(peer_count)
    )


def _ebb_next_hop(
    device_group: DeviceGroupSpec,
    openr_mode: OpenRMode,
    next_hops: EbbNextHopScheme = EBB_NEXT_HOPS,
) -> NextHopIntent:
    """Build next hops aligned with legacy route assets and OpenR injection."""
    openr_enabled = openr_mode is OpenRMode.STANDALONE
    if device_group.name == "dg_ebgp_v4":
        ebgp_v4_parent = f"{next_hops.ebgp_v4_network}.0/23"
        return (
            _sequential_explicit_next_hop(
                f"{next_hops.ebgp_v4_network}.11",
                device_group.peer_count,
                ebgp_v4_parent,
            )
            if openr_enabled
            else _explicit_next_hop(
                f"{next_hops.ebgp_v4_network}.10",
                device_group.peer_count,
                ebgp_v4_parent,
            )
        )
    if device_group.name == "dg_ebgp_v6":
        ebgp_v6_parent = f"{next_hops.ebgp_v6_network}::/80"
        return (
            _sequential_explicit_next_hop(
                f"{next_hops.ebgp_v6_network}::11",
                device_group.peer_count,
                ebgp_v6_parent,
            )
            if openr_enabled
            else _explicit_next_hop(
                f"{next_hops.ebgp_v6_network}::10",
                device_group.peer_count,
                ebgp_v6_parent,
            )
        )

    plane = _ebb_plane_number(device_group)
    start, parent, lexical = _ebb_ibgp_next_hop_source(
        device_group.afi, plane, openr_mode, next_hops
    )
    return (
        _explicit_next_hop(start, device_group.peer_count, parent)
        if lexical
        else _formulaic_next_hop(start, parent)
    )


def _ebb_plane_number(device_group: DeviceGroupSpec) -> int:
    _, separator, plane_suffix = device_group.role.rpartition("_p")
    if not separator or not plane_suffix.isdigit():
        raise ValueError(
            "EBB iBGP device-group roles must end in a numeric plane suffix; "
            f"got role={device_group.role!r} for {device_group.name!r}"
        )
    plane = int(plane_suffix)
    if not 1 <= plane <= 4:
        raise ValueError(
            "EBB iBGP device-group plane must be between 1 and 4; "
            f"got role={device_group.role!r} for {device_group.name!r}"
        )
    return plane


def _ebb_advertisement(
    device_group: DeviceGroupSpec,
    openr_mode: OpenRMode,
    *,
    prefix_sets_by_name: t.Mapping[str, PrefixSet],
    ebgp_static_prefix_count: int,
    next_hop_self: bool = False,
    enable_attribute_churn: bool = False,
    include_legacy_community_rows: bool = False,
    next_hops: EbbNextHopScheme = EBB_NEXT_HOPS,
) -> PrefixAdvertisement | None:
    if device_group.name == "dg_ebgp_v4":
        prefix_set = prefix_sets_by_name[EBB_EBGP_V4_PREFIX_SET.name]
        distribution = PeerPrefixDistribution.SHARED
        legacy_name = "PREFIX_POOL_IPV4_EBGP"
    elif device_group.name == "dg_ebgp_v6":
        prefix_set = prefix_sets_by_name[EBB_EBGP_V6_PREFIX_SET.name]
        distribution = PeerPrefixDistribution.SHARED
        legacy_name = "PREFIX_POOL_IPV6_EBGP"
    elif device_group.role.startswith("ibgp_dc_p"):
        prefix_set = prefix_sets_by_name[
            (
                EBB_IBGP_V4_PREFIX_SET.name
                if device_group.afi == "v4"
                else EBB_IBGP_V6_PREFIX_SET.name
            )
        ]
        distribution = PeerPrefixDistribution.DISJOINT
        plane = _ebb_plane_number(device_group)
        legacy_name = (
            f"PREFIX_POOL_IBGP_IPV{4 if device_group.afi == 'v4' else 6}_"
            f"PLANE_{plane}_REMOTE_EB"
        )
    else:
        return None
    advertised_prefix_count = (
        ebgp_static_prefix_count
        if device_group.role == "uplink"
        else prefix_set.source.count
    )
    return PrefixAdvertisement(
        name=f"{device_group.name}_routes",
        prefix_set=prefix_set.name,
        allocation=PrefixAllocation(
            prefixes_per_peer=(
                advertised_prefix_count if device_group.role == "uplink" else 750
            ),
            peer_distribution=distribution,
        ),
        membership=PrefixMembership(
            start_index=0,
            prefix_count=advertised_prefix_count,
        ),
        next_hop=(
            NextHopIntent(mode=NextHopMode.SELF)
            if next_hop_self
            else _ebb_next_hop(device_group, openr_mode, next_hops)
        ),
        policy=EBB_ACCEPT_POLICY if device_group.role == "uplink" else None,
        attributes=(
            EBB_ATTRIBUTE_CHURN_BASELINE
            if enable_attribute_churn and device_group.role.startswith("ibgp_dc_p")
            else (("med", None), ("local_pref", 100), ("origin", "igp"))
        ),
        route_attributes=(
            replace(
                _EBB_IBGP_ROUTE_ATTRIBUTES,
                as_paths=(AsPathSequence(asns=EBB_ATTRIBUTE_CHURN_AS_PATH),),
            )
            if (
                enable_attribute_churn
                and include_legacy_community_rows
                and device_group.role.startswith("ibgp_dc_p")
            )
            else (
                RouteAttributePool(
                    as_paths=(AsPathSequence(asns=EBB_ATTRIBUTE_CHURN_AS_PATH),),
                )
                if enable_attribute_churn and device_group.role.startswith("ibgp_dc_p")
                else (
                    _EBB_IBGP_ROUTE_ATTRIBUTES
                    if include_legacy_community_rows
                    and device_group.role.startswith("ibgp_dc_p")
                    else None
                )
            )
        ),
        legacy_ixia_name=legacy_name,
    )


# Variant A: with bgpmon - 3 physical interfaces, 19 DeviceGroups total.
# Keep this first topology instance explicit so it can be reviewed against
# Appendix 1 without following helper loops or generated DG lists.
_EBB_FULL_SCALE_WITH_BGPMON_BASE = LogicalTopology(
    name="ebb_full_scale_with_bgpmon",
    legacy_profile="ebb_full_scale",
    endpoints=(
        EndpointSpec(name="dut0", role="dut", kind="dut", setup_mode="full"),
        EndpointSpec(name="ixia", role="trafficgen", kind="ixia", setup_mode="full"),
    ),
    device_groups=(
        # eBGP uplink: 2 DGs sharing the uplink physical interface.
        DeviceGroupSpec(
            name="dg_ebgp_v6",
            role="uplink",
            peer_relationship=PeerRelationship.EXTERNAL,
            afi="v6",
            peer_count=EBGP_PEER_COUNT_V6,
            a_endpoint="dut0",
            z_endpoint="ixia",
            address_plan=AddressPlan(
                afi="v6",
                parent_network_key="ebgp_v6",
                stride=2,
                prefix_length=127,
            ),
            peer_group=EBGP_V6_PEER_GROUP,
            legacy_ixia_tag_name="BGP_PEER_IPV6_EBGP",
            legacy_ixia_device_group_name="DEVICE_GROUP_IPV6_EBGP",
            port_assignment=_EBB_UPLINK_PORT_ASSIGNMENT,
            legacy_ixia_device_group_index=0,
        ),
        DeviceGroupSpec(
            name="dg_ebgp_v4",
            role="uplink",
            peer_relationship=PeerRelationship.EXTERNAL,
            afi="v4",
            peer_count=EBGP_PEER_COUNT_V4,
            a_endpoint="dut0",
            z_endpoint="ixia",
            address_plan=AddressPlan(
                afi="v4",
                parent_network_key="ebgp_v4",
                stride=2,
                prefix_length=31,
            ),
            peer_group=EBGP_V4_PEER_GROUP,
            legacy_ixia_tag_name="BGP_PEER_IPV4_EBGP",
            legacy_ixia_device_group_name="DEVICE_GROUP_IPV4_EBGP",
            port_assignment=_EBB_UPLINK_PORT_ASSIGNMENT,
            legacy_ixia_device_group_index=1,
        ),
        # iBGP DC planes 1-4: v6 DGs sharing the iBGP physical interface.
        DeviceGroupSpec(
            name="dg_ibgp_v6_dc_p1",
            role="ibgp_dc_p1",
            peer_relationship=PeerRelationship.INTERNAL,
            afi="v6",
            peer_count=IBGP_PEER_SCALE_PER_PLANE,
            a_endpoint="dut0",
            z_endpoint="ixia",
            address_plan=AddressPlan(
                afi="v6",
                parent_network_key="ibgp_dc_p1_v6",
                stride=2,
                prefix_length=127,
            ),
            peer_group=IBGP_V6_PEER_GROUP,
            legacy_ixia_tag_name="BGP_PEER_IPV6_IBGP_PLANE_1_REMOTE_EB",
            legacy_ixia_device_group_name="DEVICE_GROUP_IPV6_IBGP_PLANE_1_REMOTE_EB",
            port_assignment=_EBB_IBGP_PORT_ASSIGNMENT,
            legacy_ixia_device_group_index=0,
        ),
        DeviceGroupSpec(
            name="dg_ibgp_v6_dc_p2",
            role="ibgp_dc_p2",
            peer_relationship=PeerRelationship.INTERNAL,
            afi="v6",
            peer_count=IBGP_PEER_SCALE_PER_PLANE,
            a_endpoint="dut0",
            z_endpoint="ixia",
            address_plan=AddressPlan(
                afi="v6",
                parent_network_key="ibgp_dc_p2_v6",
                stride=2,
                prefix_length=127,
            ),
            peer_group=IBGP_V6_PEER_GROUP,
            legacy_ixia_tag_name="BGP_PEER_IPV6_IBGP_PLANE_2_REMOTE_EB",
            legacy_ixia_device_group_name="DEVICE_GROUP_IPV6_IBGP_PLANE_2_REMOTE_EB",
            port_assignment=_EBB_IBGP_PORT_ASSIGNMENT,
            legacy_ixia_device_group_index=4,
        ),
        DeviceGroupSpec(
            name="dg_ibgp_v6_dc_p3",
            role="ibgp_dc_p3",
            peer_relationship=PeerRelationship.INTERNAL,
            afi="v6",
            peer_count=IBGP_PEER_SCALE_PER_PLANE,
            a_endpoint="dut0",
            z_endpoint="ixia",
            address_plan=AddressPlan(
                afi="v6",
                parent_network_key="ibgp_dc_p3_v6",
                stride=2,
                prefix_length=127,
            ),
            peer_group=IBGP_V6_PEER_GROUP,
            legacy_ixia_tag_name="BGP_PEER_IPV6_IBGP_PLANE_3_REMOTE_EB",
            legacy_ixia_device_group_name="DEVICE_GROUP_IPV6_IBGP_PLANE_3_REMOTE_EB",
            port_assignment=_EBB_IBGP_PORT_ASSIGNMENT,
            legacy_ixia_device_group_index=8,
        ),
        DeviceGroupSpec(
            name="dg_ibgp_v6_dc_p4",
            role="ibgp_dc_p4",
            peer_relationship=PeerRelationship.INTERNAL,
            afi="v6",
            peer_count=IBGP_PEER_SCALE_PER_PLANE,
            a_endpoint="dut0",
            z_endpoint="ixia",
            address_plan=AddressPlan(
                afi="v6",
                parent_network_key="ibgp_dc_p4_v6",
                stride=2,
                prefix_length=127,
            ),
            peer_group=IBGP_V6_PEER_GROUP,
            legacy_ixia_tag_name="BGP_PEER_IPV6_IBGP_PLANE_4_REMOTE_EB",
            legacy_ixia_device_group_name="DEVICE_GROUP_IPV6_IBGP_PLANE_4_REMOTE_EB",
            port_assignment=_EBB_IBGP_PORT_ASSIGNMENT,
            legacy_ixia_device_group_index=12,
        ),
        # iBGP DC planes 1-4: v4 DGs.
        DeviceGroupSpec(
            name="dg_ibgp_v4_dc_p1",
            role="ibgp_dc_p1",
            peer_relationship=PeerRelationship.INTERNAL,
            afi="v4",
            peer_count=IBGP_PEER_SCALE_PER_PLANE,
            a_endpoint="dut0",
            z_endpoint="ixia",
            address_plan=AddressPlan(
                afi="v4",
                parent_network_key="ibgp_dc_p1_v4",
                stride=2,
                prefix_length=31,
            ),
            peer_group=IBGP_V4_PEER_GROUP,
            legacy_ixia_tag_name="BGP_PEER_IPV4_IBGP_PLANE_1_REMOTE_EB",
            legacy_ixia_device_group_name="DEVICE_GROUP_IPV4_IBGP_PLANE_1_REMOTE_EB",
            port_assignment=_EBB_IBGP_PORT_ASSIGNMENT,
            legacy_ixia_device_group_index=2,
        ),
        DeviceGroupSpec(
            name="dg_ibgp_v4_dc_p2",
            role="ibgp_dc_p2",
            peer_relationship=PeerRelationship.INTERNAL,
            afi="v4",
            peer_count=IBGP_PEER_SCALE_PER_PLANE,
            a_endpoint="dut0",
            z_endpoint="ixia",
            address_plan=AddressPlan(
                afi="v4",
                parent_network_key="ibgp_dc_p2_v4",
                stride=2,
                prefix_length=31,
            ),
            peer_group=IBGP_V4_PEER_GROUP,
            legacy_ixia_tag_name="BGP_PEER_IPV4_IBGP_PLANE_2_REMOTE_EB",
            legacy_ixia_device_group_name="DEVICE_GROUP_IPV4_IBGP_PLANE_2_REMOTE_EB",
            port_assignment=_EBB_IBGP_PORT_ASSIGNMENT,
            legacy_ixia_device_group_index=6,
        ),
        DeviceGroupSpec(
            name="dg_ibgp_v4_dc_p3",
            role="ibgp_dc_p3",
            peer_relationship=PeerRelationship.INTERNAL,
            afi="v4",
            peer_count=IBGP_PEER_SCALE_PER_PLANE,
            a_endpoint="dut0",
            z_endpoint="ixia",
            address_plan=AddressPlan(
                afi="v4",
                parent_network_key="ibgp_dc_p3_v4",
                stride=2,
                prefix_length=31,
            ),
            peer_group=IBGP_V4_PEER_GROUP,
            legacy_ixia_tag_name="BGP_PEER_IPV4_IBGP_PLANE_3_REMOTE_EB",
            legacy_ixia_device_group_name="DEVICE_GROUP_IPV4_IBGP_PLANE_3_REMOTE_EB",
            port_assignment=_EBB_IBGP_PORT_ASSIGNMENT,
            legacy_ixia_device_group_index=10,
        ),
        DeviceGroupSpec(
            name="dg_ibgp_v4_dc_p4",
            role="ibgp_dc_p4",
            peer_relationship=PeerRelationship.INTERNAL,
            afi="v4",
            peer_count=IBGP_PEER_SCALE_PER_PLANE,
            a_endpoint="dut0",
            z_endpoint="ixia",
            address_plan=AddressPlan(
                afi="v4",
                parent_network_key="ibgp_dc_p4_v4",
                stride=2,
                prefix_length=31,
            ),
            peer_group=IBGP_V4_PEER_GROUP,
            legacy_ixia_tag_name="BGP_PEER_IPV4_IBGP_PLANE_4_REMOTE_EB",
            legacy_ixia_device_group_name="DEVICE_GROUP_IPV4_IBGP_PLANE_4_REMOTE_EB",
            port_assignment=_EBB_IBGP_PORT_ASSIGNMENT,
            legacy_ixia_device_group_index=14,
        ),
        # iBGP MP planes 1-4: v6 DGs sharing the iBGP physical interface.
        DeviceGroupSpec(
            name="dg_ibgp_v6_mp_p1",
            role="ibgp_mp_p1",
            peer_relationship=PeerRelationship.INTERNAL,
            afi="v6",
            peer_count=IBGP_PEER_SCALE_PER_PLANE,
            a_endpoint="dut0",
            z_endpoint="ixia",
            address_plan=AddressPlan(
                afi="v6",
                parent_network_key="ibgp_mp_p1_v6",
                stride=2,
                prefix_length=127,
            ),
            peer_group=IBGP_V6_PEER_GROUP,
            legacy_ixia_tag_name="BGP_PEER_IPV6_IBGP_PLANE_1_REMOTE_MP",
            legacy_ixia_device_group_name="DEVICE_GROUP_IPV6_IBGP_PLANE_1_REMOTE_MP",
            port_assignment=_EBB_IBGP_PORT_ASSIGNMENT,
            legacy_ixia_device_group_index=1,
        ),
        DeviceGroupSpec(
            name="dg_ibgp_v6_mp_p2",
            role="ibgp_mp_p2",
            peer_relationship=PeerRelationship.INTERNAL,
            afi="v6",
            peer_count=IBGP_PEER_SCALE_PER_PLANE,
            a_endpoint="dut0",
            z_endpoint="ixia",
            address_plan=AddressPlan(
                afi="v6",
                parent_network_key="ibgp_mp_p2_v6",
                stride=2,
                prefix_length=127,
            ),
            peer_group=IBGP_V6_PEER_GROUP,
            legacy_ixia_tag_name="BGP_PEER_IPV6_IBGP_PLANE_2_REMOTE_MP",
            legacy_ixia_device_group_name="DEVICE_GROUP_IPV6_IBGP_PLANE_2_REMOTE_MP",
            port_assignment=_EBB_IBGP_PORT_ASSIGNMENT,
            legacy_ixia_device_group_index=5,
        ),
        DeviceGroupSpec(
            name="dg_ibgp_v6_mp_p3",
            role="ibgp_mp_p3",
            peer_relationship=PeerRelationship.INTERNAL,
            afi="v6",
            peer_count=IBGP_PEER_SCALE_PER_PLANE,
            a_endpoint="dut0",
            z_endpoint="ixia",
            address_plan=AddressPlan(
                afi="v6",
                parent_network_key="ibgp_mp_p3_v6",
                stride=2,
                prefix_length=127,
            ),
            peer_group=IBGP_V6_PEER_GROUP,
            legacy_ixia_tag_name="BGP_PEER_IPV6_IBGP_PLANE_3_REMOTE_MP",
            legacy_ixia_device_group_name="DEVICE_GROUP_IPV6_IBGP_PLANE_3_REMOTE_MP",
            port_assignment=_EBB_IBGP_PORT_ASSIGNMENT,
            legacy_ixia_device_group_index=9,
        ),
        DeviceGroupSpec(
            name="dg_ibgp_v6_mp_p4",
            role="ibgp_mp_p4",
            peer_relationship=PeerRelationship.INTERNAL,
            afi="v6",
            peer_count=IBGP_PEER_SCALE_PER_PLANE,
            a_endpoint="dut0",
            z_endpoint="ixia",
            address_plan=AddressPlan(
                afi="v6",
                parent_network_key="ibgp_mp_p4_v6",
                stride=2,
                prefix_length=127,
            ),
            peer_group=IBGP_V6_PEER_GROUP,
            legacy_ixia_tag_name="BGP_PEER_IPV6_IBGP_PLANE_4_REMOTE_MP",
            legacy_ixia_device_group_name="DEVICE_GROUP_IPV6_IBGP_PLANE_4_REMOTE_MP",
            port_assignment=_EBB_IBGP_PORT_ASSIGNMENT,
            legacy_ixia_device_group_index=13,
        ),
        # iBGP MP planes 1-4: v4 DGs.
        DeviceGroupSpec(
            name="dg_ibgp_v4_mp_p1",
            role="ibgp_mp_p1",
            peer_relationship=PeerRelationship.INTERNAL,
            afi="v4",
            peer_count=IBGP_PEER_SCALE_PER_PLANE,
            a_endpoint="dut0",
            z_endpoint="ixia",
            address_plan=AddressPlan(
                afi="v4",
                parent_network_key="ibgp_mp_p1_v4",
                stride=2,
                prefix_length=31,
            ),
            peer_group=IBGP_V4_PEER_GROUP,
            legacy_ixia_tag_name="BGP_PEER_IPV4_IBGP_PLANE_1_REMOTE_MP",
            legacy_ixia_device_group_name="DEVICE_GROUP_IPV4_IBGP_PLANE_1_REMOTE_MP",
            port_assignment=_EBB_IBGP_PORT_ASSIGNMENT,
            legacy_ixia_device_group_index=3,
        ),
        DeviceGroupSpec(
            name="dg_ibgp_v4_mp_p2",
            role="ibgp_mp_p2",
            peer_relationship=PeerRelationship.INTERNAL,
            afi="v4",
            peer_count=IBGP_PEER_SCALE_PER_PLANE,
            a_endpoint="dut0",
            z_endpoint="ixia",
            address_plan=AddressPlan(
                afi="v4",
                parent_network_key="ibgp_mp_p2_v4",
                stride=2,
                prefix_length=31,
            ),
            peer_group=IBGP_V4_PEER_GROUP,
            legacy_ixia_tag_name="BGP_PEER_IPV4_IBGP_PLANE_2_REMOTE_MP",
            legacy_ixia_device_group_name="DEVICE_GROUP_IPV4_IBGP_PLANE_2_REMOTE_MP",
            port_assignment=_EBB_IBGP_PORT_ASSIGNMENT,
            legacy_ixia_device_group_index=7,
        ),
        DeviceGroupSpec(
            name="dg_ibgp_v4_mp_p3",
            role="ibgp_mp_p3",
            peer_relationship=PeerRelationship.INTERNAL,
            afi="v4",
            peer_count=IBGP_PEER_SCALE_PER_PLANE,
            a_endpoint="dut0",
            z_endpoint="ixia",
            address_plan=AddressPlan(
                afi="v4",
                parent_network_key="ibgp_mp_p3_v4",
                stride=2,
                prefix_length=31,
            ),
            peer_group=IBGP_V4_PEER_GROUP,
            legacy_ixia_tag_name="BGP_PEER_IPV4_IBGP_PLANE_3_REMOTE_MP",
            legacy_ixia_device_group_name="DEVICE_GROUP_IPV4_IBGP_PLANE_3_REMOTE_MP",
            port_assignment=_EBB_IBGP_PORT_ASSIGNMENT,
            legacy_ixia_device_group_index=11,
        ),
        DeviceGroupSpec(
            name="dg_ibgp_v4_mp_p4",
            role="ibgp_mp_p4",
            peer_relationship=PeerRelationship.INTERNAL,
            afi="v4",
            peer_count=IBGP_PEER_SCALE_PER_PLANE,
            a_endpoint="dut0",
            z_endpoint="ixia",
            address_plan=AddressPlan(
                afi="v4",
                parent_network_key="ibgp_mp_p4_v4",
                stride=2,
                prefix_length=31,
            ),
            peer_group=IBGP_V4_PEER_GROUP,
            legacy_ixia_tag_name="BGP_PEER_IPV4_IBGP_PLANE_4_REMOTE_MP",
            legacy_ixia_device_group_name="DEVICE_GROUP_IPV4_IBGP_PLANE_4_REMOTE_MP",
            port_assignment=_EBB_IBGP_PORT_ASSIGNMENT,
            legacy_ixia_device_group_index=15,
        ),
        # BGP MON: 1 DG on the bgpmon physical interface.
        DeviceGroupSpec(
            name="dg_bgp_mon_v6",
            role="bgpmon",
            peer_relationship=PeerRelationship.MONITOR,
            afi="v6",
            peer_count=BGP_MON_PEER_COUNT,
            a_endpoint="dut0",
            z_endpoint="ixia",
            address_plan=AddressPlan(
                afi="v6",
                parent_network_key="bgpmon_v6",
                stride=2,
                prefix_length=127,
            ),
            peer_group=BGP_MON_PEER_GROUP,
            legacy_ixia_tag_name="BGP_PEER_IPV6_BGP_MON",
            legacy_ixia_device_group_name="DEVICE_GROUP_BGP_MON",
            port_assignment=_EBB_BGPMON_PORT_ASSIGNMENT,
            legacy_ixia_device_group_index=0,
        ),
    ),
    device_config=EBB_DEVICE_CONFIG,
    peer_groups=tuple(EBB_PEER_GROUPS.values()),
)


def _with_ebb_route_intent(
    topology: LogicalTopology,
    openr_mode: OpenRMode,
    *,
    ebgp_graceful_restart: bool = True,
    next_hop_self: bool = False,
    enable_attribute_churn: bool = False,
    include_legacy_community_rows: bool = True,
    ebgp_prefix_count: int = 750,
    ebgp_static_prefix_count: int | None = None,
    extra_prefix_sets: tuple[PrefixSet, ...] = (),
    extra_advertisements: t.Mapping[str, tuple[PrefixAdvertisement, ...]] | None = None,
    next_hops: EbbNextHopScheme = EBB_NEXT_HOPS,
) -> LogicalTopology:
    if ebgp_prefix_count < 750:
        raise ValueError("ebgp_prefix_count must be at least 750")
    static_prefix_count = (
        ebgp_prefix_count
        if ebgp_static_prefix_count is None
        else ebgp_static_prefix_count
    )
    # Equality is the default full-static topology. A smaller explicit value
    # reserves the suffix for runtime route operations such as TC7.
    if static_prefix_count <= 0 or static_prefix_count > ebgp_prefix_count:
        raise ValueError(
            "ebgp_static_prefix_count must be positive and no greater than "
            "ebgp_prefix_count"
        )
    prefix_sets = tuple(
        replace(prefix_set, source=replace(prefix_set.source, count=ebgp_prefix_count))
        if prefix_set.name in {EBB_EBGP_V4_PREFIX_SET.name, EBB_EBGP_V6_PREFIX_SET.name}
        else prefix_set
        for prefix_set in EBB_PREFIX_SETS
    )
    prefix_sets_by_name = {prefix_set.name: prefix_set for prefix_set in prefix_sets}
    extra_advertisements = extra_advertisements or {}
    device_groups = []
    for device_group in topology.device_groups:
        peer_group = device_group.peer_group
        if (
            device_group.role == "uplink"
            and isinstance(peer_group, BgpPeerGroup)
            and peer_group.enable_graceful_restart != ebgp_graceful_restart
        ):
            peer_group = replace(
                peer_group,
                enable_graceful_restart=ebgp_graceful_restart,
            )
        advertisement = _ebb_advertisement(
            device_group,
            openr_mode,
            prefix_sets_by_name=prefix_sets_by_name,
            ebgp_static_prefix_count=static_prefix_count,
            next_hop_self=next_hop_self,
            enable_attribute_churn=enable_attribute_churn,
            include_legacy_community_rows=include_legacy_community_rows,
            next_hops=next_hops,
        )
        additional_advertisements = tuple(
            replace(extra, route_attributes=_EBB_IBGP_ROUTE_ATTRIBUTES)
            if include_legacy_community_rows
            and device_group.role.startswith("ibgp_dc_p")
            and extra.route_attributes is None
            else extra
            for extra in extra_advertisements.get(device_group.name, ())
        )
        device_groups.append(
            replace(
                device_group,
                peer_group=peer_group,
                prefix_advertisements=(
                    ((advertisement,) if advertisement else ())
                    + additional_advertisements
                ),
            )
        )
    # Only STANDALONE injects; leaving the other modes empty keeps the NONE-mode
    # module topologies byte-identical to what they were before this field.
    if openr_mode is OpenRMode.STANDALONE:
        injected_v4, injected_v6 = ebb_openr_injected_next_hops(next_hops)
    else:
        injected_v4, injected_v6 = [], []
    return replace(
        topology,
        device_groups=tuple(device_groups),
        device_config=replace(
            topology.device_config,
            openr_mode=openr_mode,
            openr_injected_start_ipv4s=tuple(injected_v4),
            openr_injected_start_ipv6s=tuple(injected_v6),
        ),
        policies=(EBB_ACCEPT_POLICY,),
        prefix_sets=(*prefix_sets, *extra_prefix_sets),
    )


EBB_FULL_SCALE_WITH_BGPMON = _with_ebb_route_intent(
    _EBB_FULL_SCALE_WITH_BGPMON_BASE,
    openr_mode=OpenRMode.NONE,
)

# Variant B: without bgpmon - 2 physical interfaces, 18 DeviceGroups total.
# This small derived filter keeps the two variants consistent without hiding
# the full Appendix-style listing above.
_EBB_FULL_SCALE_NO_BGPMON_BASE = LogicalTopology(
    name="ebb_full_scale_no_bgpmon",
    legacy_profile="ebb_full_scale",
    endpoints=_EBB_FULL_SCALE_WITH_BGPMON_BASE.endpoints,
    device_groups=tuple(
        dg
        for dg in _EBB_FULL_SCALE_WITH_BGPMON_BASE.device_groups
        if dg.role != "bgpmon" and dg.name != "dg_bgp_mon_v6"
    ),
    device_config=EBB_DEVICE_CONFIG,
    peer_groups=tuple(
        peer_group
        for peer_group in EBB_PEER_GROUPS.values()
        if peer_group.name != PEERGROUP_BGP_MON
    ),
)

EBB_FULL_SCALE_NO_BGPMON = _with_ebb_route_intent(
    _EBB_FULL_SCALE_NO_BGPMON_BASE,
    openr_mode=OpenRMode.NONE,
)


def ebb_full_scale_topology(
    *,
    openr_mode: OpenRMode,
    include_bgpmon: bool = True,
    ebgp_graceful_restart: bool = True,
    next_hop_self: bool = False,
    enable_attribute_churn: bool = False,
    include_legacy_community_rows: bool = True,
    ebgp_prefix_count: int = 750,
    ebgp_static_prefix_count: int | None = None,
    extra_prefix_sets: tuple[PrefixSet, ...] = (),
    extra_advertisements: t.Mapping[str, tuple[PrefixAdvertisement, ...]] | None = None,
    next_hops: EbbNextHopScheme = EBB_NEXT_HOPS,
) -> LogicalTopology:
    base = (
        _EBB_FULL_SCALE_WITH_BGPMON_BASE
        if include_bgpmon
        else _EBB_FULL_SCALE_NO_BGPMON_BASE
    )
    return _with_ebb_route_intent(
        base,
        openr_mode,
        ebgp_graceful_restart=ebgp_graceful_restart,
        next_hop_self=next_hop_self,
        enable_attribute_churn=enable_attribute_churn,
        include_legacy_community_rows=include_legacy_community_rows,
        ebgp_prefix_count=ebgp_prefix_count,
        ebgp_static_prefix_count=ebgp_static_prefix_count,
        extra_prefix_sets=extra_prefix_sets,
        extra_advertisements=extra_advertisements,
        next_hops=next_hops,
    )


__all__ = (
    "BGP_MON_PEER_GROUP",
    "EBB_AS_NUMBERS",
    "EBB_ATTRIBUTE_CHURN_AS_PATH",
    "EBB_ATTRIBUTE_CHURN_BASELINE",
    "EBB_DEVICE_CONFIG",
    "EBB_EBGP_V4_PREFIX_SET",
    "EBB_EBGP_V6_PREFIX_SET",
    "EBB_FULL_SCALE_NO_BGPMON",
    "EBB_FULL_SCALE_PORT_MAP",
    "EBB_FULL_SCALE_PORT_MAP_WITH_BGPMON",
    "EBB_FULL_SCALE_WITH_BGPMON",
    "EBB_IBGP_V4_PREFIX_SET",
    "EBB_IBGP_V6_PREFIX_SET",
    "EBB_LONGEVITY_COMMUNITY_BASELINE_COUNT",
    "EBB_NEXT_HOPS",
    "EBB_NEXT_HOPS_IXIA03",
    "EBB_PARENT_NETWORKS_IXIA03",
    "EbbNextHopScheme",
    "EBB_PARENT_NETWORKS",
    "EBB_PEER_GROUPS",
    "EBB_PREFIX_SETS",
    "EBGP_V4_PEER_GROUP",
    "EBGP_V6_PEER_GROUP",
    "IBGP_V4_PEER_GROUP",
    "IBGP_V6_PEER_GROUP",
    "ebb_full_scale_topology",
    "ebb_ibgp_route_next_hops",
    "ebb_openr_injected_next_hops",
)
