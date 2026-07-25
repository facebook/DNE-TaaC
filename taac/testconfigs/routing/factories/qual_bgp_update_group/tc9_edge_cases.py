# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Spec 2.9 — Edge Cases and Adversarial Scenarios. UG qualification testconfig factory.

Bundles the WITHOUT_OPEN_R section-2.9 edge-case playbooks onto one shared
EBB-scale conveyor topology (one IXIA setup, one catalog constant), selected
at run time via ``--regex 'bgp_ug_<usecase>'``. The bundle currently wires
2.9.7 (empty group); the remaining WITHOUT_OPEN_R sub-specs (2.9.1 / 2.9.3 /
2.9.6) land incrementally as their playbook factories in
``playbooks/routing/factories/qual_bgp_update_group/tc9_edge_cases.py`` are
implemented, each added to the ``playbooks=[...]`` list below. 2.9.2
(simultaneous disruptions) and 2.9.4 (dual-stack isolation) are each their
OWN TestConfig below -- both need WITH_OPEN_R (2.9.4's per-AFI distribution
checks read the PS gauge, which is only non-zero when Open/R resolves the
iBGP next-hops so the DUT actually advertises). Spec 2.9.5 is excluded
(struck through in the plan).

Target physical inventories: BAG011_ASH6 for the edge-cases bundle (2.9.7) /
2.9.4 / 2.9.2, and BAG013_ASH6 for 2.9.6 staggered-startup (both EBB conveyor
nodes). Reuses the shared ``build_bag_conveyor_test_config`` builder from tc1
for the full-scale
topology (140 eBGP + ~500 iBGP, ``include_bgp_mon=False`` — UG qualification
never exercises BGP-MON); the Open/R profile is chosen per-TestConfig.
"""

from ixia.ixia import types as ixia_types
from taac.abstractions.topology import (
    BgpPolicy,
    FormulaicPrefixSource,
    NextHopIntent,
    NextHopMode,
    PeerPrefixDistribution,
    PrefixAdvertisement,
    PrefixAllocation,
    PrefixMembership,
    PrefixSet,
)
from taac.constants import (
    BgpPlusPlusProfile,
    DEFAULT_OPENR_START_IPV4S,
    DEFAULT_OPENR_START_IPV6S,
    Gigabyte,
)
from taac.health_checks.healthcheck_definitions import (
    create_bgp_session_establish_check,
    create_bgp_update_group_check,
    create_cpu_utilization_check,
    create_drain_state_check,
    create_memory_utilization_check,
)
from taac.playbooks.routing.factories.qual_bgp_update_group.tc9_edge_cases import (
    create_bgp_ug_best_path_change_playbook,
    create_bgp_ug_dual_stack_isolation_playbook,
    create_bgp_ug_empty_group_playbook,
    create_bgp_ug_simultaneous_disruptions_playbook,
    create_bgp_ug_staggered_startup_playbook,
)
from taac.testconfigs.routing.factories.qual_bgp_update_group.tc1_distribution_correctness import (
    build_bag_conveyor_test_config,
)
from taac.testconfigs.routing.physical_inventory import (
    PhysicalInventory,
)
from taac.testconfigs.routing.util.bgp_ebb_constants import (
    EBGP_REMOTE_AS,
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
    PEERGROUP_EBGP_V4,
    PEERGROUP_EBGP_V6,
    PEERGROUP_IBGP_V4,
    PEERGROUP_IBGP_V6,
)
from taac.test_as_a_config import types as taac_types


# =============================================================================
# BGP UG edge cases (spec 2.9) — bag011 conveyor logical_topology.
# =============================================================================

# BGP-peer-name regexes that select every eBGP / iBGP peer built by
# ``create_ebb_scale_basic_port_configs`` (see bgp_ebb_ixia_config.py). The
# playbook empties / recovers the update groups by STOPPING and STARTING these
# peers' BGP sessions (``start_bgp_peers``), NOT by toggling their DeviceGroups
# -- toggling de-materializes the IXIA-imported eBGP route ranges so recovery
# would advertise nothing (see the playbook's ``_flap_bgp_peers`` docstring).
# Matched with ``re.search`` against the BGP-peer name; the trailing ``$``
# anchors precisely. eBGP names carry ``EBGP``; iBGP names carry ``IBGP`` --
# cleanly disjoint, and neither matches the BGP-MON peer.
_EBGP_PEER_REGEX = r"BGP_PEER_IPV[46]_EBGP$"
_IBGP_PEER_REGEX = r"BGP_PEER_IPV[46]_IBGP_PLANE_\d+_REMOTE_(?:EB|MP)$"

# Parent prefixes of every NON-eBGP peer (all 8 iBGP planes, v6 + v4, plus
# BGP-MON). The 2.9.7 playbook ignores these when asserting the eBGP group
# actually emptied, so the session-establish check sees ONLY eBGP peers and can
# assert 0 Established. Mirrors tc7's ``_BAG013_IBGP_PEER_SUBNETS`` CIDR choices:
# iBGP v6 is a /80 per plane; iBGP v4 uses a /16 per plane because the /31 peer
# scale spills past the /24 boundary (e.g. 10.164.28.x into 10.164.29.x).
_IBGP_V6_PARENT_PREFIXES = [
    f"{net}::/80"
    for net in (
        IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
        IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE2,
        IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE3,
        IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE4,
        IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE1,
        IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE2,
        IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE3,
        IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE4,
    )
]
_IBGP_V4_PARENT_PREFIXES = [
    # "10.164.28" -> "10.164.0.0/16"
    f"{'.'.join(net.split('.')[:2])}.0.0/16"
    for net in (
        IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
        IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE2,
        IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE3,
        IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE4,
        IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE1,
        IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE2,
        IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE3,
        IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE4,
    )
]


# Spec step 3: inject from the plane-1 iBGP v6 route pool (withdraw +
# re-advertise the prefixes while the eBGP group is empty).
_IBGP_INJECT_POOL_REGEX = "PREFIX_POOL_IBGP_IPV6_PLANE_1_REMOTE_EB"
# Spec step 10 (dump-compare on recovery): compare two plane-1 iBGP peers in the
# same update group. Mirrors tc1's 2.1.1 dump-compare on this same logical_topology.
_IBGP_DUMP_PEER_REGEX = "BGP_PEER_IPV6_IBGP_PLANE_1_REMOTE_EB"
_IBGP_DUMP_SESSION_INDICES = [1, 2]

# Spec step 8 + "full route re-sync" (recovery re-advertise): the imported eBGP
# prefix pools. IXIA does NOT re-advertise these one-shot ``ImportBgpRoutes``
# prefixes when the eBGP sessions come back up, so the playbook withdraws +
# re-advertises this pool at recovery to force IXIA to re-send them, restoring the
# DUT's eBGP RIB for redistribution (see the playbook recovery notes). ``$``
# excludes the unused ``_DRAIN`` pools (topology is built drain=False).
_EBGP_PREFIX_POOL_REGEX = r"PREFIX_POOL_IPV[46]_EBGP$"

# Spec pre-condition 3 ("record update group count") + pass-criteria "groups
# re-created correctly" / "no stale group entries". The EBB-scale UG topology
# on bag011 forms exactly 4 update groups at steady state (v6/v4 x eBGP/iBGP);
# observed on hardware (baseline 4 -> 2 when eBGP empties -> 0 all-empty -> 4 on
# recovery). Asserted at the baseline precheck (records the baseline) and again
# on recovery (must return to baseline -- a higher count would mean a stale
# group survived the empty period).
_EXPECTED_UPDATE_GROUP_COUNT = 4


# --- 2.9.2 Simultaneous Disruptions ---
# Route churn targets the v6 eBGP prefix pool; attribute churn targets the plane-1
# v6 iBGP prefix pool; random flaps span both eBGP AFI peers. ``$`` excludes the
# unused ``_DRAIN`` pools/peers (the bag conveyor topology is built drain=False).
_SIMUL_EBGP_ROUTE_POOL_REGEX = r"PREFIX_POOL_IPV6_EBGP$"
_SIMUL_IBGP_ATTR_POOL_REGEX = "PREFIX_POOL_IBGP_IPV6_PLANE_1_REMOTE_EB"
_SIMUL_EBGP_FLAP_PEER_REGEX = r"BGP_PEER_IPV[46]_EBGP$"
# Spec 2.9.2 pass-criterion 4: VmHWM growth (M_after - M_before) < 500 MB.
_SIMUL_VMHWM_GROWTH_THRESHOLD_BYTES = 500 * 1024 * 1024


# --- 2.9.4 Dual-Stack Isolation ---
# v6 side: WITHDRAW existing prefixes from the MAIN eBGP v6 import pool (spec
# steps 5/8; imported pools support per-index Active, so index-slicing works).
# v4 side: ADVERTISE genuinely-NEW prefixes from dedicated SPARE eBGP v4 pools,
# inline-generated via ``RouteScale`` (no CSV). HW confirmed a RouteScale-
# generated pool is toggled Active WHOLE-pool (per network-group, not per-index),
# so we use TWO exactly-sized pools instead of index-slicing one: SPARE_A (500,
# spec step 1) and SPARE_B (100, spec step 8). Both are made inactive at baseline
# (setup withdraws them) then advertised WHOLE on top of the untouched existing
# 750 -- a real addition (step 1: 749 -> 1249). ``$`` anchors each regex to its
# pool (not the main ``PREFIX_POOL_IPV4_EBGP``, and not each other).
_DUAL_STACK_EBGP_V4_STEP1_POOL_REGEX = r"PREFIX_POOL_IPV4_EBGP_SPARE_A$"
_DUAL_STACK_EBGP_V4_STEP8_POOL_REGEX = r"PREFIX_POOL_IPV4_EBGP_SPARE_B$"
_DUAL_STACK_EBGP_V6_POOL_REGEX = r"PREFIX_POOL_IPV6_EBGP$"

# Two spare eBGP v4 pools of distinct /24s generated beyond the main pool's
# 120.0-120.2 span but inside the DUT's 120/8 EB-PRIVATE-PREFIXES accept
# aggregate (HW-confirmed: 120.100.x is accepted + re-advertised, delta was
# exactly +count with no replication). Zero ``prefix_step`` = IXNetwork
# increments by one /24 per prefix (the perf-scaling pattern). Each carries the
# accept communities the main v4 routes carry (so the DUT re-advertises them to
# iBGP v4) PLUS the spec 2.9.4 marker 65529:44444. SPARE_A = 500 (step 1):
# 120.100.0.0 .. 120.101.243.0; SPARE_B = 100 (step 8): 120.104.0.0 .. 120.104.99.0
# (disjoint from A). If a first HW run shows the range spans past 120/8 or the
# delta differs, adjust the starts/counts here.
_DUAL_STACK_SPARE_V4_STEP1_COUNT = 500
_DUAL_STACK_SPARE_V4_STEP8_COUNT = 100
_DUAL_STACK_SPARE_V4_COMMUNITIES = [
    "65529:39744",  # EB-PRIVATE-PREFIXES accept community
    "65060:10012",  # ADVERTISED-FROM-DC accept community
    "65530:50320",  # anycast accept community
    "65529:44444",  # spec 2.9.4 marker community
]


def _extra_formulaic_advertisement(
    *,
    prefix_name: str,
    afi: str,
    start_prefix: str,
    parent_network: str,
    prefix_step: int,
    prefix_length: int,
    prefix_count: int,
    network_group_index: int,
    communities: list[str],
) -> tuple[PrefixSet, PrefixAdvertisement]:
    intent_name = prefix_name.lower()
    prefix_set = PrefixSet(
        name=intent_name,
        afi=afi,
        source=FormulaicPrefixSource(
            start_prefix=start_prefix,
            prefix_step=prefix_step,
            prefix_length=prefix_length,
            count=prefix_count,
            parent_network=parent_network,
        ),
    )
    return prefix_set, PrefixAdvertisement(
        name=f"{intent_name}_advertisement",
        prefix_set=prefix_set.name,
        allocation=PrefixAllocation(
            prefixes_per_peer=prefix_count,
            peer_distribution=PeerPrefixDistribution.SHARED,
            network_group_index=network_group_index,
        ),
        membership=PrefixMembership(start_index=0, prefix_count=prefix_count),
        next_hop=NextHopIntent(mode=NextHopMode.SELF),
        policy=BgpPolicy(
            name=f"{intent_name}_policy",
            communities=tuple(communities),
        ),
        legacy_ixia_name=prefix_name,
    )


_DUAL_STACK_SPARE_V4_INTENTS = (
    _extra_formulaic_advertisement(
        prefix_name="PREFIX_POOL_IPV4_EBGP_SPARE_A",
        afi="v4",
        start_prefix="120.100.0.0",
        parent_network="120.0.0.0/8",
        prefix_step=1 << 8,
        prefix_length=24,
        prefix_count=_DUAL_STACK_SPARE_V4_STEP1_COUNT,
        network_group_index=1,
        communities=_DUAL_STACK_SPARE_V4_COMMUNITIES,
    ),
    _extra_formulaic_advertisement(
        prefix_name="PREFIX_POOL_IPV4_EBGP_SPARE_B",
        afi="v4",
        start_prefix="120.104.0.0",
        parent_network="120.0.0.0/8",
        prefix_step=1 << 8,
        prefix_length=24,
        prefix_count=_DUAL_STACK_SPARE_V4_STEP8_COUNT,
        network_group_index=2,
        communities=_DUAL_STACK_SPARE_V4_COMMUNITIES,
    ),
)
# ─── Spec 2.9.1 Best-Path Change During Active Distribution ─────────────────
# Two eBGP "competing sets" (carved off the eBGP v4 peer budget by the topology
# split in bgp_ebb_ixia_config.py) advertise the SAME 500 v4 prefixes. Set A
# prepends its AS 3x (long AS-PATH -> less preferred); Set B does not prepend
# (short -> preferred). AS-PATH LENGTH is the DNE-approved discriminator
# (LOCAL_PREF is non-transitive over eBGP + EB-FA-IN sets no LP -- on-device dump
# P2421451582). Advertising/withdrawing Set B flips the best path B<->A.
_BESTPATH_SET_PEER_COUNT = 10  # eBGP peers per competing set (Set A + Set B)
_BESTPATH_PREFIX_COUNT = 500
_BESTPATH_POOL_A_REGEX = r"PREFIX_POOL_IPV4_EBGP_BESTPATH_A$"
_BESTPATH_POOL_B_REGEX = r"PREFIX_POOL_IPV4_EBGP_BESTPATH_B$"
# Same 500 /24 NLRI for both sets, in the 120/8 EB-PRIVATE accept aggregate
# (disjoint from 2.9.4's 120.100/120.104), carrying the accept communities the DUT
# re-advertises to iBGP v4 (HW-confirmed on 120/8 in 2.9.4) + a filter marker. Kept
# OFF the anycast-VIP combo so EB-FA-IN's own AS_PATH_PREPEND terms do not
# re-prepend and skew the length we set.
_BESTPATH_STARTING_PREFIX = "120.130.0.0"
_BESTPATH_PREFIX_LENGTH = 24
_BESTPATH_COMMUNITIES = [
    "65529:39744",  # EB-PRIVATE-PREFIXES accept community
    "65060:10012",  # ADVERTISED-FROM-DC accept community
    "65530:50320",  # anycast accept community
    "65529:44444",  # marker (filtering only)
]
# Set A prepends its own AS 3x (received AS-PATH length ~4 vs Set B's ~1 -> B wins).
_BESTPATH_SET_A_AS_PREPEND = [[EBGP_REMOTE_AS, EBGP_REMOTE_AS, EBGP_REMOTE_AS]]
# STRICT criterion-1 (DUT-side best-path convergence): the 500 competing /24s are
# contiguous blocks from 120.130.0.0 (500 * /24 = 128000 addrs < a /15's 131072), so
# they all fall within this /15. The DUT Loc-RIB check scopes to it to exclude the
# ~93k background fabric routes (none of which are in 120/8). Set A prepends
# EBGP_REMOTE_AS this many extra times vs Set B, so the winner's best-path
# EBGP_REMOTE_AS count == baseline - delta.
_BESTPATH_TEST_PREFIX_PARENTS = ["120.130.0.0/15"]
_BESTPATH_AS_PATH_DELTA = len(_BESTPATH_SET_A_AS_PREPEND[0])


def _bestpath_route_scales(
    pool_name: str, as_path_prepend: list[list[int]] | None
) -> list[taac_types.RouteScaleSpec]:
    """One inline v4 pool of the 500 competing prefixes for a best-path set.
    ``as_path_prepend=None`` -> short AS-PATH (Set B, preferred); a prepend segment
    -> long AS-PATH (Set A, less preferred). Same NLRI for both sets (distinct pool
    names) so the DUT holds two competing paths per prefix."""
    return [
        taac_types.RouteScaleSpec(
            network_group_index=1,
            v4_route_scale=taac_types.RouteScale(
                prefix_name=pool_name,
                starting_prefixes=_BESTPATH_STARTING_PREFIX,
                prefix_step="0.0.0.0",
                prefix_length=_BESTPATH_PREFIX_LENGTH,
                prefix_count=_BESTPATH_PREFIX_COUNT,
                multiplier=1,
                ip_address_family=ixia_types.IpAddressFamily.IPV4,
                bgp_communities=list(_BESTPATH_COMMUNITIES),
                as_path_prepend_numbers=as_path_prepend,
            ),
        ),
    ]


# ─── Spec 2.9.1 IPv6 leg ────────────────────────────────────────────────────
# Same best-path competition on the eBGP v6 budget so 2.9.1 exercises the change
# on BOTH AFIs (v6 forms its own update groups). WITHOUT_OPEN_R + next-hop-self
# resolves v6 next-hops deterministically, so v6 runs STRICT from the start (no
# cold-start XFAIL needed). Same accept communities (AFI-agnostic) + same AS-PATH
# discriminator (Set A prepends EBGP_REMOTE_AS 3x). Test pool = 500 unique /64s in
# the v6 EB-PRIVATE accept aggregate 2401:db00:11:2000::/52 (fabric const
# TestPrefixes.EB_PRIVATE_PREFIX), in a sub-range disjoint from 2.9.6's v6 pools.
_BESTPATH_POOL_A_REGEX_V6 = r"PREFIX_POOL_IPV6_EBGP_BESTPATH_A$"
_BESTPATH_POOL_B_REGEX_V6 = r"PREFIX_POOL_IPV6_EBGP_BESTPATH_B$"
_BESTPATH_STARTING_PREFIX_V6 = "2401:db00:11:2800::"
_BESTPATH_PREFIX_STEP_V6 = "0:0:0:1::"  # one /64 per prefix, inside the EB-PRIVATE /52
_BESTPATH_PREFIX_LENGTH_V6 = 64
# 500 /64s from ::2800 span 4th-group 0x2800..0x29f3, all inside this /54 (0x2800..
# 0x2bff = 1024 /64s). The /54 has slack, so the checks ALSO filter to exactly /64
# (test_prefix_length_v6) to drop any aggregate/summary route the /54 over-matches --
# the first HW run saw 509 vs 500 in the /54, closed by the /64 filter.
_BESTPATH_TEST_PREFIX_PARENTS_V6 = ["2401:db00:11:2800::/54"]


def _bestpath_route_scales_v6(
    pool_name: str, as_path_prepend: list[list[int]] | None
) -> list[taac_types.RouteScaleSpec]:
    """IPv6 mirror of ``_bestpath_route_scales`` -- one inline v6 pool of the 500
    competing /64s for a best-path set (Set A long AS-PATH / Set B short)."""
    return [
        taac_types.RouteScaleSpec(
            network_group_index=1,
            v6_route_scale=taac_types.RouteScale(
                prefix_name=pool_name,
                starting_prefixes=_BESTPATH_STARTING_PREFIX_V6,
                prefix_step=_BESTPATH_PREFIX_STEP_V6,
                prefix_length=_BESTPATH_PREFIX_LENGTH_V6,
                prefix_count=_BESTPATH_PREFIX_COUNT,
                multiplier=1,
                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                bgp_communities=list(_BESTPATH_COMMUNITIES),
                as_path_prepend_numbers=as_path_prepend,
            ),
        ),
    ]


# The four AFI-split peer-groups on the EBB-scale conveyor logical_topology. IPv4 and IPv6
# peers form SEPARATE update groups, so each peer-group maps to a single-AFI,
# AFI-pure update group -- asserting that is the core dual-stack-isolation proof
# (``expected_afi_by_substring``). ``expected_group_count`` is the same 4 the
# empty-group precheck records; member counts are the hardware baseline (iBGP
# 62x8 = 496 per AFI; eBGP 140 per AFI; 4 groups / 1272 members total). If the
# topology differs, the baseline structure check fails loudly with the observed
# counts -- then pin these from the dump.
_DUAL_STACK_AFI_PEER_GROUPS = [
    PEERGROUP_IBGP_V4,
    PEERGROUP_IBGP_V6,
    PEERGROUP_EBGP_V4,
    PEERGROUP_EBGP_V6,
]
_DUAL_STACK_EXPECTED_AFI_BY_SUBSTRING = {
    PEERGROUP_IBGP_V4: "ipv4",
    PEERGROUP_IBGP_V6: "ipv6",
    PEERGROUP_EBGP_V4: "ipv4",
    PEERGROUP_EBGP_V6: "ipv6",
}
_DUAL_STACK_EXPECTED_MEMBER_COUNTS = {
    PEERGROUP_IBGP_V4: 496,
    PEERGROUP_IBGP_V6: 496,
    PEERGROUP_EBGP_V4: 140,
    PEERGROUP_EBGP_V6: 140,
}


# --- 2.9.6 Staggered Peer Startup ---
# 140 eBGP sessions PER AFI (one peer object per AFI). The spec's 50/100/130 waves
# are SYMMETRIC per-AFI session-index ranges (1-based, inclusive) applied to the
# combined v4+v6 eBGP regex: 25/AFI -> 50/AFI -> 65/AFI = 50 -> 100 -> 130 combined
# (280 total). Cumulative eBGP UG members PER AFI after each wave: 25 -> 75 -> 140.
_STAGGERED_WAVES = [(1, 25), (26, 75), (76, 140)]
_STAGGERED_CUMULATIVE_MEMBERS_PER_AFI = [25, 75, 140]
# eBGP peer-address parent prefixes for the STRICT per-peer distribution verifies
# (criteria 1-2 uniform + criterion-3 delta; the same subnet-selection 2.9.4 uses
# for iBGP). eBGP v6 = a /80; eBGP v4 = a /16 (the 140 /31 peers spill past the /24,
# same reasoning as the iBGP v4 parents).
_EBGP_V6_PARENT_PREFIXES = [f"{IXIA_EBGP_IC_PARENT_NETWORK_V6}::/80"]
_EBGP_V4_PARENT_PREFIXES = [
    f"{'.'.join(IXIA_EBGP_IC_PARENT_NETWORK_V4.split('.')[:2])}.0.0/16"
]

# --- Genuinely-new inject pools (measurable at the eBGP egress) -----------------
# The between-wave "dump-growth" injects (spec step 5) and the final runtime inject
# (spec step 6) need UNIQUE NLRI: the existing plane iBGP CSV pools share NLRI across
# all four planes, so a plane-1 withdraw/re-advertise is a no-op at the DUT->eBGP
# egress (the other planes keep the NLRI alive). So each measurable inject uses a
# DEDICATED RouteScale pool with unique NLRI in the AFI's EB-PRIVATE accept aggregate
# + the accept communities the real DC routes carry, so the DUT re-advertises it
# iBGP->eBGP. HW-VALIDATED on bag013 2026-07-23: the v4 final pool landed a clean +50
# at every eBGP v4 peer (a RouteScale route resolves its next-hop under next-hop-self).
# RouteScale pools toggle Active WHOLE-pool (not per-index), so each inject step is
# its own whole-pool toggle -> one pool per inject.
#
# EB-PRIVATE accept aggregates (from the fabric policy consts in
# neteng/emulation/emulator/utils/fabric/consts.py): v4 = 120/8 (HW-confirmed
# re-advertised in 2.9.4); v6 = 2401:db00:11:2000::/52 (TestPrefixes.EB_PRIVATE_PREFIX).
# Accept communities are AFI-agnostic. v4 ranges are disjoint from 2.9.4's
# 120.100/120.104 and 2.9.1's 120.130; v6 uses unique /64s inside the EB-PRIVATE /52.
_STAGGERED_INJECT_PER_WAVE = 100  # spec step 5: 100 new routes per wave gap
_STAGGERED_FINAL_INJECT_COUNT = 50  # spec step 6: 50 more after all peers up
_STAGGERED_INJECT_COMMUNITIES = [
    "65529:39744",  # EB-PRIVATE-PREFIXES accept (CommunityConsts.COMM_EB_PRIVATE_PREFIXES)
    "65060:10012",  # ADVERTISED-FROM-DC (marks a DC-origin route for eBGP export)
    "65530:50320",  # anycast accept community
]
# Final runtime inject (criterion 3 -- runtime distribution reaches ALL 280 peers):
# a v4 pool AND a v6 pool, so the +N is measured on BOTH eBGP AFIs.
_STAGGERED_RUNTIME_INJECT_POOL_REGEX = r"PREFIX_POOL_IBGP_IPV4_PLANE_1_INJECT$"
_STAGGERED_RUNTIME_INJECT_V6_POOL_REGEX = r"PREFIX_POOL_IBGP_IPV6_PLANE_1_INJECT$"
# Between-wave dump-growth injects (criterion 1 -- late-wave peers get the accumulated
# dump): one dedicated v4 pool per wave gap, advertised whole after its wave, so a
# late wave's initial dump measurably includes the earlier waves' injects.
_STAGGERED_WAVE_INJECT_POOL_REGEXES = [
    r"PREFIX_POOL_IBGP_IPV4_PLANE_1_WAVE1_INJECT$",
    r"PREFIX_POOL_IBGP_IPV4_PLANE_1_WAVE2_INJECT$",
]


def _staggered_v4_inject_pool(
    prefix_name: str, starting_prefix: str, count: int, network_group_index: int
) -> tuple[PrefixSet, PrefixAdvertisement]:
    """One inline v4 inject pool (unique /24s in 120/8 + accept communities)."""
    return _extra_formulaic_advertisement(
        prefix_name=prefix_name,
        afi="v4",
        start_prefix=starting_prefix,
        parent_network="120.0.0.0/8",
        prefix_step=1 << 8,
        prefix_length=24,
        prefix_count=count,
        network_group_index=network_group_index,
        communities=_STAGGERED_INJECT_COMMUNITIES,
    )


# v4 inline pools on plane-1's iBGP v4 DC peer (distinct network_group_index each,
# alongside the CSV import at index 0): final (120.150), wave1 (120.151), wave2
# (120.152).
_STAGGERED_V4_INTENTS = (
    _staggered_v4_inject_pool(
        "PREFIX_POOL_IBGP_IPV4_PLANE_1_INJECT",
        "120.150.0.0",
        _STAGGERED_FINAL_INJECT_COUNT,
        1,
    ),
    _staggered_v4_inject_pool(
        "PREFIX_POOL_IBGP_IPV4_PLANE_1_WAVE1_INJECT",
        "120.151.0.0",
        _STAGGERED_INJECT_PER_WAVE,
        2,
    ),
    _staggered_v4_inject_pool(
        "PREFIX_POOL_IBGP_IPV4_PLANE_1_WAVE2_INJECT",
        "120.152.0.0",
        _STAGGERED_INJECT_PER_WAVE,
        3,
    ),
)
# v6 inline pool on plane-1's iBGP v6 DC peer: the final inject (unique /64s within
# the v6 EB-PRIVATE /52), so criterion 3 covers the eBGP v6 peers too.
_STAGGERED_V6_INTENTS = (
    _extra_formulaic_advertisement(
        prefix_name="PREFIX_POOL_IBGP_IPV6_PLANE_1_INJECT",
        afi="v6",
        start_prefix="2401:db00:11:2000::",
        parent_network="2401:db00:11:2000::/52",
        prefix_step=1 << 64,
        prefix_length=64,
        prefix_count=_STAGGERED_FINAL_INJECT_COUNT,
        network_group_index=1,
        communities=_STAGGERED_INJECT_COMMUNITIES,
    ),
)


def _edge_cases_prechecks(
    bgp_mon_ignore_prefixes,
    establish_retry_count=None,
    establish_retry_delay_seconds=None,
    establish_retry_delay_multiplier=None,
):
    """Prechecks for the 2.9 edge-cases TestConfig.

    Hand-rolled (rather than the exact-count ``create_standard_prechecks``)
    for the same reasons tc7 hand-rolls bag013's: the bag conveyor DUTs run
    BGP-MON peers that IXIA does not emulate under UG qualification, so we
    drop the BGP-MON parent prefix from the session count and assert
    "no non-established peers among the non-MON set" rather than an exact
    session total (which drifts per bag node).

    ``establish_retry_*`` are opt-in and default to ``None`` (single-shot;
    byte-identical golden for existing callers). When a caller passes them, the
    session-establish precheck POLLS (re-fetching live data each attempt) rather
    than snapshotting once. Useful whenever the full-scale ~1272-session topology
    needs time to reach Established after setup and a single sample would be
    premature -- for two distinct reasons: (a) the WITHOUT_OPEN_R next-hop-self
    setups (e.g. 2.9.6, the first opt-in caller) restart the control-plane Bgp
    daemon on a fresh bring-up; and (b) the WITH_OPEN_R edge-case setups whose tail
    (Open/R route inject + the ``iptables`` EOS_BGP firewall re-open) finalizes BGP
    reachability only ~20s before prechecks run.
    """
    return [
        create_bgp_session_establish_check(
            parent_prefixes_to_ignore=bgp_mon_ignore_prefixes,
            retry_count=establish_retry_count,
            retry_delay_seconds=establish_retry_delay_seconds,
            retry_delay_multiplier=establish_retry_delay_multiplier,
        ),
        create_drain_state_check(),
        create_memory_utilization_check(
            threshold=Gigabyte.GIG_5.value,
            start_time_jq_var="test_case_start_time",
        ),
        create_cpu_utilization_check(
            threshold=400.0, start_time_jq_var="test_case_start_time"
        ),
        # Confirm BGP++ ``update_group`` is active on the running daemon before
        # the edge-case scenarios start, and record the baseline update-group
        # count (spec pre-condition 3) so the recovery check can assert the
        # count returns to it.
        create_bgp_update_group_check(
            expect_enabled=True,
            expected_group_count=_EXPECTED_UPDATE_GROUP_COUNT,
        ),
    ]


def create_bgp_ug_edge_cases_test_config(
    physical_inventory: PhysicalInventory,
) -> taac_types.TestConfig:
    """BGP++ Update Group qualification spec 2.9 (Edge Cases) TestConfig.

    Bundles the WITHOUT_OPEN_R section-2.9 edge-case playbooks on the shared
    EBB-scale bag conveyor logical_topology. ``enable_update_group=True`` is baked in
    (UG MUST be on for these specs). Wires the 2.9.7 empty-group playbook; the
    remaining WITHOUT_OPEN_R sub-specs are added to ``playbooks`` as they are
    implemented. (2.9.4 dual-stack isolation is its own WITH_OPEN_R TestConfig,
    ``create_bgp_ug_dual_stack_isolation_test_config``.)
    """
    bgp_mon_ignore_prefixes = [f"{IXIA_BGP_MON_IC_PARENT_NETWORK}::/80"]
    # Everything that is NOT an eBGP peer: all iBGP planes (v6 + v4) plus
    # BGP-MON. Lets the playbook scope its "eBGP actually emptied" assertion to
    # eBGP-only peers.
    non_ebgp_parent_prefixes = (
        _IBGP_V6_PARENT_PREFIXES + _IBGP_V4_PARENT_PREFIXES + bgp_mon_ignore_prefixes
    )

    empty_group_playbook = create_bgp_ug_empty_group_playbook(
        device_name=physical_inventory.device_name,
        ebgp_peer_regex=_EBGP_PEER_REGEX,
        ibgp_peer_regex=_IBGP_PEER_REGEX,
        ibgp_v6_peer_group=PEERGROUP_IBGP_V6,
        ebgp_v6_peer_group=PEERGROUP_EBGP_V6,
        prechecks=_edge_cases_prechecks(bgp_mon_ignore_prefixes),
        bgp_mon_ignore_prefixes=bgp_mon_ignore_prefixes,
        non_ebgp_parent_prefixes=non_ebgp_parent_prefixes,
        # Spec step 3 (inject iBGP routes while eBGP empty) + step 10 (recovery
        # dump-compare on two plane-1 iBGP peers; iBGP DUT iface = ixia_ports[1]).
        ibgp_inject_pool_regex=_IBGP_INJECT_POOL_REGEX,
        ibgp_dump_capture_interface=physical_inventory.ixia_ports[1][0],
        ibgp_dump_peer_regex=_IBGP_DUMP_PEER_REGEX,
        ibgp_dump_session_indices=_IBGP_DUMP_SESSION_INDICES,
        # Assert the update-group count returns to baseline on recovery (spec:
        # groups re-created correctly, no stale/orphaned groups).
        expected_recovered_group_count=_EXPECTED_UPDATE_GROUP_COUNT,
        # Force IXIA to re-advertise the imported eBGP routes at recovery (session
        # -up alone does not re-send them), so the DUT relearns its eBGP RIB and
        # can redistribute to iBGP for the step-10 dump + full route re-sync.
        ebgp_prefix_pool_regex=_EBGP_PREFIX_POOL_REGEX,
        # Spec pass-criterion "VmHWM below 10 GB" -- bag011 is Arista, where the
        # standard memory postcheck can only sample RSS deltas; this reads
        # bgpcpp /proc VmHWM directly and asserts the 10 GiB ceiling.
        vmhwm_threshold_bytes=Gigabyte.GIG_10.value,
    )

    return build_bag_conveyor_test_config(
        physical_inventory,
        name="BAG011_ASH6_BGP_UG_EDGE_CASES_TEST",
        playbooks=[empty_group_playbook],
        profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
        enable_update_group=True,
    )


def create_bgp_ug_dual_stack_isolation_test_config(
    physical_inventory: PhysicalInventory,
) -> taac_types.TestConfig:
    """BGP++ Update Group qualification spec 2.9.4 (Dual-Stack Isolation)
    TestConfig -- its OWN WITH_OPEN_R config on the bag conveyor logical_topology.

    Verifies STRICT AFI isolation: v4 and v6 peers form separate, AFI-pure
    update groups (structural, via ``expected_afi_by_substring``), and a route
    op on one AFI moves only that AFI's per-peer distribution (the ``PS`` gauge
    on the iBGP peers, selected by peer-group) while the other AFI stays flat,
    with no cross-AFI flap/crash. See ``create_bgp_ug_dual_stack_isolation_playbook``.

    WITH_OPEN_R (not the WITHOUT_OPEN_R edge-cases bundle): the per-AFI
    distribution checks read ``postpolicy_sent_prefix_count``, which is only
    non-zero once Open/R resolves the iBGP next-hops so the DUT actually
    advertises (WITHOUT_OPEN_R leaves the routes inactive and the DUT advertises
    ~0). WITH_OPEN_R does not change the 4-update-group / session baseline -- it
    only adds the Open/R daemon, Port-Channel, and injected baseline routes.

    KNOWN SIGNAL: the IPv6 distribution checks (spec steps 5 and the v6 half of
    step 8) FAIL on bag011 today -- a bgpcpp IPv6 connected-next-hop-resolution
    defect keeps iBGP v6 PS at 0 (tracking-doc appendix Part B). That failure is
    the intended surfacing of the defect, not a test bug; the v4 distribution and
    all isolation checks pass, and the whole test passes once the defect is fixed.
    """
    bgp_mon_ignore_prefixes = [f"{IXIA_BGP_MON_IC_PARENT_NETWORK}::/80"]
    dual_stack_isolation_playbook = create_bgp_ug_dual_stack_isolation_playbook(
        device_name=physical_inventory.device_name,
        afi_peer_group_substrings=_DUAL_STACK_AFI_PEER_GROUPS,
        expected_group_count=_EXPECTED_UPDATE_GROUP_COUNT,
        expected_member_counts=_DUAL_STACK_EXPECTED_MEMBER_COUNTS,
        expected_afi_by_substring=_DUAL_STACK_EXPECTED_AFI_BY_SUBSTRING,
        # Select the whole iBGP AFI update group by peer-group (no address
        # enumeration): EB-EB-V4 / EB-EB-V6.
        # Scope the per-AFI PS distribution checks to the iBGP peers by peer
        # ADDRESS subnet (session.peer_group is not the AFI peer-group name on
        # bag011 -- the update-group object has EB-EB-V4 but the session field
        # does not). The v4 plane /16s and v6 plane /80s are AFI-specific.
        ibgp_v4_peer_parent_prefixes=_IBGP_V4_PARENT_PREFIXES,
        ibgp_v6_peer_parent_prefixes=_IBGP_V6_PARENT_PREFIXES,
        ebgp_v4_step1_pool_regex=_DUAL_STACK_EBGP_V4_STEP1_POOL_REGEX,
        ebgp_v4_step8_pool_regex=_DUAL_STACK_EBGP_V4_STEP8_POOL_REGEX,
        ebgp_v6_prefix_pool_regex=_DUAL_STACK_EBGP_V6_POOL_REGEX,
        prechecks=_edge_cases_prechecks(bgp_mon_ignore_prefixes),
        bgp_mon_ignore_prefixes=bgp_mon_ignore_prefixes,
        # Extra-safety absolute VmHWM ceiling (consistent with the other UG tests).
        vmhwm_absolute_threshold_bytes=Gigabyte.GIG_10.value,
    )

    return build_bag_conveyor_test_config(
        physical_inventory,
        name="BAG011_ASH6_BGP_UG_DUAL_STACK_ISOLATION_TEST",
        playbooks=[dual_stack_isolation_playbook],
        # WITH_OPEN_R so the iBGP next-hops resolve and the DUT advertises --
        # the precondition for the per-AFI PS distribution checks.
        profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
        enable_update_group=True,
        # Build the spare inline-generated v4 pool (the genuinely-new prefixes
        # the playbook advertises for spec step 1/8) on the eBGP v4 device group.
        extra_prefix_sets=tuple(
            prefix_set for prefix_set, _ in _DUAL_STACK_SPARE_V4_INTENTS
        ),
        extra_prefix_advertisements={
            "dg_ebgp_v4": tuple(
                advertisement for _, advertisement in _DUAL_STACK_SPARE_V4_INTENTS
            )
        },
    )


def create_bgp_ug_simultaneous_disruptions_test_config(
    physical_inventory: PhysicalInventory,
    *,
    smoke: bool = False,
) -> taac_types.TestConfig:
    """BGP++ Update Group qualification spec 2.9.2 (Simultaneous Disruptions
    Across All Groups) TestConfig on the bag conveyor logical_topology.

    Runs the four concurrent disruption tracks (eBGP route churn with varying
    communities, random eBGP session flaps without graceful restart, IGP-metric
    oscillation via Open/R, iBGP LOCAL_PREF churn) + a monitor track + a VmHWM
    growth gate, then a convergence-verify stage. See
    ``create_bgp_ug_simultaneous_disruptions_playbook``.

    Unlike the WITHOUT_OPEN_R edge-cases bundle, 2.9.2 is its OWN TestConfig on
    the ``WITH_OPEN_R`` profile: the IGP-instability track oscillates Open/R
    adjacency metrics, which needs a running Open/R daemon + the baseline Open/R
    route injection that ``get_common_setup_tasks`` only wires under that profile.
    The eBGP peers are built graceful-restart-off so their flaps are real "without
    graceful restart" events (spec). WITH_OPEN_R does not change the 4-update-group
    or the eBGP+iBGP session baseline -- it only adds the Open/R daemon,
    Port-Channel, injected routes, and the OpenR-variant IXIA route CSVs.

    ``smoke=True`` builds a short (3-min disruption) variant with the same shape
    for validating the machinery on hardware before the full 30-min run.
    """
    bgp_mon_ignore_prefixes = [f"{IXIA_BGP_MON_IC_PARENT_NETWORK}::/80"]
    # Everything that is NOT an iBGP peer (both eBGP AFIs + BGP-MON): lets the
    # monitor scope its "iBGP stays Established" check to iBGP only, since eBGP is
    # intentionally being flapped. eBGP v6 uses a /80; eBGP v4 uses a /16 because
    # the 140 /31 peers spill past the /24 (same reasoning as the iBGP v4 parents).
    non_ibgp_parent_prefixes = [
        f"{IXIA_EBGP_IC_PARENT_NETWORK_V6}::/80",
        f"{'.'.join(IXIA_EBGP_IC_PARENT_NETWORK_V4.split('.')[:2])}.0.0/16",
    ] + bgp_mon_ignore_prefixes

    if smoke:
        name = "BAG011_ASH6_BGP_UG_SIMULTANEOUS_DISRUPTIONS_SMOKE"
        disruption_duration_s = 180
        convergence_quiesce_s = 60
        route_churn_interval_s = 30
        session_flap_interval_s = 60
        attr_churn_interval_s = 30
        monitor_interval_s = 60
        igp_frequency_s = 30
    else:
        name = "BAG011_ASH6_BGP_UG_SIMULTANEOUS_DISRUPTIONS_TEST"
        disruption_duration_s = 1800
        convergence_quiesce_s = 300
        route_churn_interval_s = 60
        session_flap_interval_s = 120
        attr_churn_interval_s = 60
        monitor_interval_s = 120
        igp_frequency_s = 60

    openr_link = physical_inventory.openr_standalone_link
    assert openr_link is not None, "OpenR playbook requires a standalone link"
    playbook = create_bgp_ug_simultaneous_disruptions_playbook(
        device_name=physical_inventory.device_name,
        ebgp_route_pool_regex=_SIMUL_EBGP_ROUTE_POOL_REGEX,
        ibgp_attr_pool_regex=_SIMUL_IBGP_ATTR_POOL_REGEX,
        ebgp_flap_peer_regex=_SIMUL_EBGP_FLAP_PEER_REGEX,
        # METRIC_OSCILLATION must act on the SAME routes the WITH_OPEN_R setup
        # injects, which uses the DEFAULT start-IP lists + count=63/step=2 (the
        # playbook's igp defaults), so pass the DEFAULT lists here too.
        openr_start_ipv4s=DEFAULT_OPENR_START_IPV4S,
        openr_start_ipv6s=DEFAULT_OPENR_START_IPV6S,
        openr_local_link=openr_link.kv_link(openr_link.owner),
        openr_other_link=openr_link.kv_link(openr_link.helper),
        non_ibgp_parent_prefixes=non_ibgp_parent_prefixes,
        vmhwm_growth_threshold_bytes=_SIMUL_VMHWM_GROWTH_THRESHOLD_BYTES,
        prechecks=_edge_cases_prechecks(bgp_mon_ignore_prefixes),
        bgp_mon_ignore_prefixes=bgp_mon_ignore_prefixes,
        # Extra-safety absolute ceiling (consistent with 2.9.7); the growth gate
        # is the actual 2.9.2 pass-criterion.
        vmhwm_absolute_threshold_bytes=Gigabyte.GIG_10.value,
        disruption_duration_s=disruption_duration_s,
        convergence_quiesce_s=convergence_quiesce_s,
        route_churn_interval_s=route_churn_interval_s,
        session_flap_interval_s=session_flap_interval_s,
        attr_churn_interval_s=attr_churn_interval_s,
        monitor_interval_s=monitor_interval_s,
        igp_frequency_s=igp_frequency_s,
    )

    return build_bag_conveyor_test_config(
        physical_inventory,
        name=name,
        playbooks=[playbook],
        # WITH_OPEN_R so the IGP-instability track has a running Open/R daemon +
        # injected baseline routes to oscillate.
        profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
        enable_update_group=True,
        # Spec: flap eBGP sessions "without graceful restart".
        ebgp_graceful_restart=False,
    )


def create_bgp_ug_staggered_startup_test_config(
    physical_inventory: PhysicalInventory,
) -> taac_types.TestConfig:
    """BGP++ Update Group qualification spec 2.9.6 (Staggered Peer Startup)
    TestConfig -- its OWN WITHOUT_OPEN_R config on the bag conveyor topology,
    resolving next-hops via the next-hop-self infra (no Open/R daemon).

    Brings the eBGP peers up in three staggered waves (50/100/130, realized as
    symmetric 25/50/65-per-AFI session-index ranges applied to the combined v4+v6
    eBGP regex) on top of the stable iBGP source, injecting new iBGP routes between
    waves, and verifies the eBGP update group grows correctly as the late peers
    join and attach (25 -> 75 -> 140 members/AFI), iBGP stays Established
    throughout, and nothing crashes. Select via
    ``--test-config BAG013_ASH6_BGP_UG_STAGGERED_STARTUP_TEST``. See
    ``create_bgp_ug_staggered_startup_playbook``.

    Per-peer route distribution (spec pass-criteria 1-3) is STRICT on BOTH AFIs:
    criterion 1 (late waves get the accumulated dump) via a per-peer +N accumulation
    delta -- the between-wave injects use DEDICATED genuinely-new v4 pools (one per
    wave gap) so the count measurably grows, and the uniform check proves late waves
    share it; criteria 1-2 (identical counts) via a per-peer PS-gauge uniform check on
    v4 AND v6; criterion 3 (runtime +N reaches ALL 280) via a per-peer +N delta after
    a runtime inject of a DEDICATED unique-NLRI pool per AFI (v4 in 120/8, v6 in the
    2401:db00:11:2000::/52 EB-PRIVATE aggregate). The v6 uniform check keeps an escape
    hatch to XFAIL for the cold-start next-hop slowness (off by default). The PS gauge
    is used rather than ``getPostfilterAdvertisedNetworks`` (SET equality) because the
    latter is vacuous under an Update Group (T271301144).

    HW-VALIDATED on bag013 2026-07-23 (strict PASS of the v4 uniform + v4 criterion-3
    core): 140 eBGP v4 peers uniform + non-zero @45750, 140 eBGP v6 peers @45716,
    criterion-3 +50 v4 delta on all peers, waves 25->75->140/AFI, no crash, no stale.
    The v6 criterion-3 inject + the between-wave accumulation deltas are new (this
    revision) and pending their first HW run.

    Uses WITHOUT_OPEN_R + the next-hop-self resolution infra (D113330327): IXIA
    advertises each route with next-hop = the peer's own connected IP
    (``ebgp_next_hop_self`` / ``ibgp_next_hop_self``) and the DUT resolves it from
    interface state via the ``bgp_resolve_nexthops_from_interface_state`` bgpcpp
    gflag (``resolve_nexthops_from_interface_state``) -- so the next-hops resolve and
    the DUT advertises with NO Open/R daemon (dropping the cores / ~118s route-inject
    / iptables settle-race the Open/R tail caused), HW-confirmed advertising the full
    RIB to every eBGP peer. It does not change the 4-update-group / eBGP+iBGP session
    baseline.
    """
    bgp_mon_ignore_prefixes = [f"{IXIA_BGP_MON_IC_PARENT_NETWORK}::/80"]
    # Everything that is NOT an iBGP peer (both eBGP AFIs + BGP-MON): scopes the
    # "iBGP stays Established" checks to iBGP while eBGP is only partially up during
    # the waves. Same construction as 2.9.2's non_ibgp_parent_prefixes.
    non_ibgp_parent_prefixes = (
        _EBGP_V6_PARENT_PREFIXES + _EBGP_V4_PARENT_PREFIXES + bgp_mon_ignore_prefixes
    )

    staggered_startup_playbook = create_bgp_ug_staggered_startup_playbook(
        device_name=physical_inventory.device_name,
        ebgp_peer_regex=_EBGP_PEER_REGEX,
        ibgp_peer_regex=_IBGP_PEER_REGEX,
        ibgp_v6_peer_group=PEERGROUP_IBGP_V6,
        ebgp_v4_peer_group=PEERGROUP_EBGP_V4,
        ebgp_v6_peer_group=PEERGROUP_EBGP_V6,
        waves=_STAGGERED_WAVES,
        cumulative_members_per_afi=_STAGGERED_CUMULATIVE_MEMBERS_PER_AFI,
        non_ibgp_parent_prefixes=non_ibgp_parent_prefixes,
        # Between-wave dump-growth injects: one DEDICATED unique-NLRI v4 pool per wave
        # gap, advertised whole so a late wave's initial dump measurably includes the
        # earlier waves' injects (criterion 1).
        ibgp_wave_inject_pool_regexes=_STAGGERED_WAVE_INJECT_POOL_REGEXES,
        inject_per_wave=_STAGGERED_INJECT_PER_WAVE,
        final_inject_count=_STAGGERED_FINAL_INJECT_COUNT,
        # Criterion-3 runtime inject: DEDICATED unique-NLRI pools (v4 + v6), advertised
        # whole so the +N is measurable at each eBGP AFI egress (all 280 peers).
        ibgp_runtime_inject_pool_regex=_STAGGERED_RUNTIME_INJECT_POOL_REGEX,
        ibgp_v6_runtime_inject_pool_regex=_STAGGERED_RUNTIME_INJECT_V6_POOL_REGEX,
        # STRICT per-peer distribution verify scopes (by peer-address subnet):
        # criteria 1-2 (non-zero + uniform) for BOTH v4 and v6, and the criterion-3
        # +N delta (v4 only -- the dedicated inject pool is v4). v6 is STRICT: it
        # passed HW on bag013 2026-07-23 (@45716 uniform), so the XFAIL escape hatch
        # is left OFF (default). Re-enable it here only if a fresh cold build regresses
        # on v6 (eBGP IPv6 /127 next-hop cold-start, Appendix B).
        ebgp_v4_peer_parent_prefixes=_EBGP_V4_PARENT_PREFIXES,
        ebgp_v6_peer_parent_prefixes=_EBGP_V6_PARENT_PREFIXES,
        # Opt into the session-establish precheck RETRY: the ~1272-session
        # full-scale topology needs time to reach Established after the
        # control-plane Bgp restart, so poll for ~3 min instead of one snapshot.
        # (WITHOUT_OPEN_R drops the Open/R-inject + iptables settle-race that caused
        # the earlier all-IDLE precheck failures, but the large session count on a
        # fresh bring-up still warrants the retry.)
        prechecks=_edge_cases_prechecks(
            bgp_mon_ignore_prefixes,
            establish_retry_count=12,
            establish_retry_delay_seconds=15.0,
            establish_retry_delay_multiplier=1.0,
        ),
        bgp_mon_ignore_prefixes=bgp_mon_ignore_prefixes,
        # Extra-safety absolute VmHWM ceiling (consistent with the other UG tests).
        vmhwm_absolute_threshold_bytes=Gigabyte.GIG_10.value,
    )

    return build_bag_conveyor_test_config(
        physical_inventory,
        name="BAG013_ASH6_BGP_UG_STAGGERED_STARTUP_TEST",
        playbooks=[staggered_startup_playbook],
        # WITHOUT_OPEN_R + next-hop-self (D113330327): IXIA advertises next-hop =
        # the peer's connected IP and the DUT resolves it from interface state via
        # the bgpcpp gflag -- so the iBGP next-hops resolve and the DUT advertises
        # with no Open/R daemon (the precondition for measuring per-peer
        # distribution). First consumer of the infra; HW-unverified.
        profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
        ebgp_next_hop_self=True,
        ibgp_next_hop_self=True,
        resolve_nexthops_from_interface_state=True,
        enable_update_group=True,
        # Dedicated unique-NLRI inject pools on plane-1's iBGP DC peers -- the
        # genuinely-new sources for the measurable injects the shared-CSV planes cannot
        # provide. v4: the two between-wave dump-growth pools + the final runtime pool.
        # v6: the final runtime pool (so criterion 3 covers the eBGP v6 peers too).
        extra_prefix_sets=tuple(
            prefix_set
            for prefix_set, _ in (*_STAGGERED_V4_INTENTS, *_STAGGERED_V6_INTENTS)
        ),
        extra_prefix_advertisements={
            "dg_ibgp_v4_dc_p1": tuple(
                advertisement for _, advertisement in _STAGGERED_V4_INTENTS
            ),
            "dg_ibgp_v6_dc_p1": tuple(
                advertisement for _, advertisement in _STAGGERED_V6_INTENTS
            ),
        },
    )


def create_bgp_ug_best_path_change_test_config(
    testbed: PhysicalInventory,
) -> taac_types.TestConfig:
    """BGP++ Update Group qualification spec 2.9.1 (Best-Path Change During Active
    Distribution) TestConfig -- its OWN WITHOUT_OPEN_R config on the bag conveyor
    topology, using the next-hop-self resolution infra (D113330327).

    Two eBGP "competing sets" (carved off the eBGP v4 peer budget by the topology
    split) advertise the SAME 500 v4 prefixes -- Set A long AS-PATH, Set B short
    (preferred). DUAL-AFI: the same competition also runs on the eBGP v6 sets (500 v6
    /64s in the EB-PRIVATE aggregate), so the best-path change is exercised on both
    v4 and v6 (each forms its own update groups); v6 runs strict from the start since
    next-hop-self resolves v6 next-hops deterministically under WITHOUT_OPEN_R. The
    playbook advertises Set A, then re-advertises the same prefixes
    from Set B (best-path change A->B), then rapidly alternates the winner every 10s
    for 5 min, asserting no crash / no session disruption / update group intact / no
    stale routes throughout. AS-PATH length is the DNE-approved discriminator
    (LOCAL_PREF is non-transitive over eBGP and bag013's EB-FA-IN sets no LP --
    on-device dump P2421451582). Select via
    ``--test-config BAG013_ASH6_BGP_UG_BEST_PATH_CHANGE_TEST``. See
    ``create_bgp_ug_best_path_change_playbook``.

    WITHOUT_OPEN_R + next-hop-self so the DUT resolves next-hops and advertises the
    test prefixes with no Open/R daemon. STRICT criterion-1 is asserted DUT-side: the
    playbook baselines Set A's best-path AS-PATH (Set A alone) and then asserts, via
    the DUT Loc-RIB best path, that every test prefix converged to Set B after the
    flip and after the final settle (none stuck on Set A). This verifies the DUT
    best-path SELECTION (Loc-RIB); under Update Group the DUT distributes that one
    best path to all group members by construction (per-peer adj-RIB-out is not
    independently read -- deferred, T271301144). The iBGP v4 PS
    gauge is also probed (measure-first) as a next-hop-self / no-route-loss
    diagnostic (a count cannot see a best-path flip). HW-UNVERIFIED (IXIA down): this
    run also exercises the next-hop-self path (incl. whether the inline test pool's
    next-hop resolves under next-hop-self).
    """
    bgp_mon_ignore_prefixes = [f"{IXIA_BGP_MON_IC_PARENT_NETWORK}::/80"]
    best_path_change_playbook = create_bgp_ug_best_path_change_playbook(
        device_name=testbed.device_name,
        ebgp_bestpath_a_pool_regex=_BESTPATH_POOL_A_REGEX,
        ebgp_bestpath_b_pool_regex=_BESTPATH_POOL_B_REGEX,
        ibgp_v4_peer_parent_prefixes=_IBGP_V4_PARENT_PREFIXES,
        test_prefix_count=_BESTPATH_PREFIX_COUNT,
        # STRICT criterion-1: assert (via the DUT Loc-RIB best path, self-calibrated
        # against Set A's baseline) that every test prefix converged to Set B (short
        # AS-PATH), none stuck on Set A. discriminator = the competing sets' eBGP AS;
        # delta = Set A's extra prepends; scoped to the test /15 so the ~93k
        # background routes are excluded.
        test_prefix_parents=_BESTPATH_TEST_PREFIX_PARENTS,
        discriminator_asn=EBGP_REMOTE_AS,
        best_path_as_path_delta=_BESTPATH_AS_PATH_DELTA,
        # The 500 competing v4 prefixes are all /24; match only /24s under the /15 so
        # any aggregate/summary route in that range is excluded (count == injected set).
        test_prefix_length=_BESTPATH_PREFIX_LENGTH,
        # IPv6 leg: same best-path competition on the eBGP v6 sets + v6 strict
        # convergence (scoped to the v6 test /54) + v6 PS probe. Runs STRICT from the
        # start -- next-hop-self resolves v6 next-hops deterministically under
        # WITHOUT_OPEN_R, so there is no cold-start distribution delay. Same
        # discriminator ASN (65334) + delta (3) as v4 (shared).
        ebgp_bestpath_a_pool_regex_v6=_BESTPATH_POOL_A_REGEX_V6,
        ebgp_bestpath_b_pool_regex_v6=_BESTPATH_POOL_B_REGEX_V6,
        ibgp_v6_peer_parent_prefixes=_IBGP_V6_PARENT_PREFIXES,
        test_prefix_parents_v6=_BESTPATH_TEST_PREFIX_PARENTS_V6,
        # The 500 competing v6 prefixes are all /64; match only /64s under the /54 so
        # the handful of non-/64 aggregates the /54 over-matched (the HW run saw 509 vs
        # 500) are excluded.
        test_prefix_length_v6=_BESTPATH_PREFIX_LENGTH_V6,
        # Per-peer distribution check (the "better" gate): read each iBGP peer's
        # advertised adj-RIB-out (getPostfilterAdvertisedNetworks) and assert every peer
        # got Set B. v4 is STRICT: HW confirmed all 496 iBGP peers were advertised all
        # 500 test prefixes (advertised_total 1249 = 749 baseline + 500 test), Set B,
        # AS-PATH delta intact. v6 stays XFAIL due to a THRIFT-API blind spot, NOT a
        # device problem: getPostfilterAdvertisedNetworks under-reports v6 (returns 9 of
        # 509 test prefixes; advertised_total 758 vs the CLI's 1258), while the device
        # CLI ("advertised post-policy") confirms the DUT advertises all 509 v6 test
        # prefixes to every peer -- matching its Loc-RIB. So v6 per-peer distribution is
        # actually healthy; it just isn't measurable via this thrift API yet. v6
        # distribution is still covered by the v6 device-side (Loc-RIB) strict check +
        # the sent-route-count (PS) checks. See the [peer-advertised]
        # advertised_total/in_parent/matched diagnostics in the run logs.
        per_peer_check=True,
        per_peer_expected_fail_v4=False,
        per_peer_expected_fail_v6=True,
        per_peer_expected_fail_reason=(
            "v6 thrift getPostfilterAdvertisedNetworks under-reports advertised routes "
            "(returns 9 of 509; CLI confirms the DUT advertises all 509) -- API blind "
            "spot, not a device gap; tracked in T281417842, pending a thrift fix / "
            "alternate reader"
        ),
        # Retry the establish precheck: the ~1272-session full-scale topology needs
        # time to reach Established after the control-plane Bgp restart (as 2.9.6).
        prechecks=_edge_cases_prechecks(
            bgp_mon_ignore_prefixes,
            establish_retry_count=12,
            establish_retry_delay_seconds=15.0,
            establish_retry_delay_multiplier=1.0,
        ),
        bgp_mon_ignore_prefixes=bgp_mon_ignore_prefixes,
        vmhwm_absolute_threshold_bytes=Gigabyte.GIG_10.value,
    )
    return build_bag_conveyor_test_config(
        testbed,
        name="BAG013_ASH6_BGP_UG_BEST_PATH_CHANGE_TEST",
        playbooks=[best_path_change_playbook],
        # WITHOUT_OPEN_R + next-hop-self (D113330327): resolve next-hops from
        # interface state so the DUT advertises the test prefixes (no Open/R).
        profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
        enable_update_group=True,
        ebgp_next_hop_self=True,
        ibgp_next_hop_self=True,
        resolve_nexthops_from_interface_state=True,
        # Two competing eBGP v4 sets (10 peers each, carved off the eBGP v4 budget)
        # advertising the same 500 NLRI -- Set A long AS-PATH, Set B short.
        ebgp_v4_bestpath_set_peer_count=_BESTPATH_SET_PEER_COUNT,
        ebgp_v4_bestpath_route_scales_a=_bestpath_route_scales(
            "PREFIX_POOL_IPV4_EBGP_BESTPATH_A", _BESTPATH_SET_A_AS_PREPEND
        ),
        ebgp_v4_bestpath_route_scales_b=_bestpath_route_scales(
            "PREFIX_POOL_IPV4_EBGP_BESTPATH_B", None
        ),
        # Two competing eBGP v6 sets (mirror of v4) so 2.9.1 exercises the best-path
        # change on both AFIs. Same peer count + AS-PATH prepend; v6 inline test pool.
        ebgp_v6_bestpath_set_peer_count=_BESTPATH_SET_PEER_COUNT,
        ebgp_v6_bestpath_route_scales_a=_bestpath_route_scales_v6(
            "PREFIX_POOL_IPV6_EBGP_BESTPATH_A", _BESTPATH_SET_A_AS_PREPEND
        ),
        ebgp_v6_bestpath_route_scales_b=_bestpath_route_scales_v6(
            "PREFIX_POOL_IPV6_EBGP_BESTPATH_B", None
        ),
    )


__all__ = [
    "create_bgp_ug_best_path_change_test_config",
    "create_bgp_ug_dual_stack_isolation_test_config",
    "create_bgp_ug_edge_cases_test_config",
    "create_bgp_ug_simultaneous_disruptions_test_config",
    "create_bgp_ug_staggered_startup_test_config",
]
