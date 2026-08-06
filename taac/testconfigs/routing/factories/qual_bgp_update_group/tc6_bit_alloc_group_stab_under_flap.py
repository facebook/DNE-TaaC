# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Spec 2.6 — Bit Allocation and Group Stability Under Flaps. UG qualification testconfig factory.

Implemented:
- 2.6.1 Repeated Peer Flaps — Group Remains Stable

Its OWN WITHOUT_OPEN_R config on the bag conveyor topology (bag013.ash6),
resolving next-hops via the next-hop-self infra (D113330327) -- no Open/R
daemon -- so the iBGP next-hops resolve and the DUT re-advertises the
distribution inject to every eBGP peer. Reuses the shared full-scale
``build_bag_conveyor_test_config`` builder + the 2.9 edge-case prechecks /
DICE inject-pool helper. Select via
``--test-config BAG013_ASH6_BGP_UG_REPEATED_PEER_FLAPS_TEST`` (or a scenario
regex ``--regex 'bgp_ug_repeated_peer_flaps'``).
"""

from taac.abstractions.physical_inventory import PhysicalInventory
from taac.constants import (  # oss-rewrite-touch
    BgpPlusPlusProfile,
    Gigabyte,
)
from taac.playbooks.routing.factories.qual_bgp_update_group.tc6_bit_alloc_group_stab_under_flap import (
    create_bgp_ug_repeated_peer_flaps_group_stable_playbook,
)
from taac.testconfigs.routing.factories.qual_bgp_update_group.tc1_distribution_correctness import (
    build_bag_conveyor_test_config,
)

# Reuse the HW-proven 2.9 edge-case testconfig helpers + constants (same package):
# the DICE inject-pool builder, the retrying prechecks, the eBGP peer/parent regexes,
# the mandatory eBGP route-attribute schema, the accept community set, and the
# baseline UG-count / member-count expectations. Importing (rather than re-declaring)
# keeps 2.6.1 byte-consistent with the sibling 2.9.x tests it mirrors.
from taac.testconfigs.routing.factories.qual_bgp_update_group.tc9_edge_cases import (
    _DUAL_STACK_EXPECTED_MEMBER_COUNTS,
    _EBGP_PEER_REGEX,
    _EBGP_V4_PARENT_PREFIXES,
    _EBGP_V4_PEER_REGEX,
    _EBGP_V6_PARENT_PREFIXES,
    _EBGP_V6_PEER_REGEX,
    _edge_cases_prechecks,
    _EXPECTED_UPDATE_GROUP_COUNT,
    _extra_formulaic_advertisement,
    _NOTIF_INJECT_ROUTE_ATTRIBUTES,
    _STAGGERED_INJECT_COMMUNITIES,
)
from taac.testconfigs.routing.util.bgp_ebb_constants import (
    IXIA_BGP_MON_IC_PARENT_NETWORK,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
    PEERGROUP_EBGP_V4,
    PEERGROUP_EBGP_V6,
    PEERGROUP_IBGP_V6,
)
from taac.test_as_a_config import types as taac_types


# --- 2.6.1 Repeated Peer Flaps -----------------------------------------------
# Spec step 5: distribute 200 genuinely-new routes/AFI to every eBGP peer (incl the
# 32 that flapped). Injected iBGP-side (dg_ibgp_v4_dc_p1 / dg_ibgp_v6_dc_p1) so the
# DUT re-advertises them to eBGP under next-hop-self -- an eBGP-side inject would NOT
# be re-sent to other eBGP peers. Dedicated unique-NLRI pools (the shared-CSV planes
# would be a no-op at the DUT->eBGP egress). NOTE: the formulaic-route validator
# (taac_ixia _prepare_formulaic_bgp_routes) requires med/local_pref/origin on EVERY
# advertisement -- iBGP-DC pools included -- so these carry the same schema as the
# eBGP pools (an empty schema fails with "missing route attribute 'med'").
_FLAP_INJECT_ROUTE_COUNT = 200
# Spec step 2: 10 advertise / 10 withdraw every 30s from the REMAINING eBGP peers.
# eBGP-side (dg_ebgp_v4 / dg_ebgp_v6) so the routes originate at the eBGP peers; a
# SHARED distribution means every eBGP peer sources the pool and the shut flapped
# peers naturally drop out. eBGP-DG pools MUST carry the mandatory route-attribute
# schema (``_NOTIF_INJECT_ROUTE_ATTRIBUTES``) or the DICE compiler rejects them.
_FLAP_CHURN_ROUTE_COUNT = 10
# Accept communities so the DUT accepts + re-advertises the pools (AFI-agnostic; the
# same 3-entry accept set 2.9.1/2.9.3/2.9.6 use).
_FLAP_ACCEPT_COMMUNITIES = list(_STAGGERED_INJECT_COMMUNITIES)

# NLRI ranges DISJOINT from every sibling test. v4 in the 120/8 EB-PRIVATE accept
# aggregate, avoiding 120.100/104 (2.9.4), 120.130 (2.9.1), 120.150-152 (2.9.6),
# 120.160 (2.9.8), 120.170 (2.9.3): 200-inject = 120.180.0.0 (-> 120.180.199.0),
# 10-churn = 120.181.0.0 (-> 120.181.9.0). v6 inside the EB-PRIVATE /52
# 2401:db00:11:2000::/52 (4th hextet 0x2000-0x2fff), avoiding ::2000 (2.9.6), ::2800
# (2.9.1), ::2c00 (2.9.8), ::2e00 (2.9.3): 200-inject = ::2400 (-> ::24c7), 10-churn
# = ::2600 (-> ::2609). All stay inside their accept aggregates.
_FLAP_INJECT_V4_POOL_REGEX = r"PREFIX_POOL_IBGP_IPV4_PLANE_1_FLAP_INJECT$"
_FLAP_INJECT_V6_POOL_REGEX = r"PREFIX_POOL_IBGP_IPV6_PLANE_1_FLAP_INJECT$"
_FLAP_CHURN_V4_POOL_REGEX = r"PREFIX_POOL_IPV4_EBGP_FLAP_CHURN$"
_FLAP_CHURN_V6_POOL_REGEX = r"PREFIX_POOL_IPV6_EBGP_FLAP_CHURN$"
# COMBINED v4|v6 churn regex: one advertise/withdraw op toggles BOTH pools (2 ops/cycle
# = the flap's rate, so churn=flap co-terminates) -- ixia_enable_disable_bgp_prefixes
# toggles every pool the regex matches in a single apply.
_FLAP_CHURN_COMBINED_POOL_REGEX = r"PREFIX_POOL_IPV[46]_EBGP_FLAP_CHURN$"
# Inject-SOURCE peer subnets (iBGP plane-1 DC peers, where the 200-route inject pools
# are advertised) for the crit-2 distribution PROBE's RECEIVED scope -- so a 0-delta run
# shows whether the DUT even RECEIVED the inject vs failed to re-advertise it.
_INJECT_SOURCE_PARENT_PREFIXES = [
    f"{IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1}.0/24",
    f"{IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1}::/80",
]

# iBGP-side 200-route inject pools (unique NLRI, accept communities + the mandatory
# med/local_pref/origin route-attribute schema the validator requires on all pools).
_FLAP_INJECT_V4_INTENTS = (
    _extra_formulaic_advertisement(
        prefix_name="PREFIX_POOL_IBGP_IPV4_PLANE_1_FLAP_INJECT",
        afi="v4",
        start_prefix="120.180.0.0",
        parent_network="120.0.0.0/8",
        prefix_step=1 << 8,  # one /24 per prefix
        prefix_length=24,
        prefix_count=_FLAP_INJECT_ROUTE_COUNT,
        network_group_index=1,
        communities=_FLAP_ACCEPT_COMMUNITIES,
        attributes=_NOTIF_INJECT_ROUTE_ATTRIBUTES,
    ),
)
_FLAP_INJECT_V6_INTENTS = (
    _extra_formulaic_advertisement(
        prefix_name="PREFIX_POOL_IBGP_IPV6_PLANE_1_FLAP_INJECT",
        afi="v6",
        start_prefix="2401:db00:11:2400::",
        parent_network="2401:db00:11:2000::/52",
        prefix_step=1 << 64,  # one /64 per prefix
        prefix_length=64,
        prefix_count=_FLAP_INJECT_ROUTE_COUNT,
        network_group_index=1,
        communities=_FLAP_ACCEPT_COMMUNITIES,
        attributes=_NOTIF_INJECT_ROUTE_ATTRIBUTES,
    ),
)
# eBGP-side 10-route churn pools (unique NLRI, accept communities + the mandatory
# eBGP route-attribute schema).
_FLAP_CHURN_V4_INTENTS = (
    _extra_formulaic_advertisement(
        prefix_name="PREFIX_POOL_IPV4_EBGP_FLAP_CHURN",
        afi="v4",
        start_prefix="120.181.0.0",
        parent_network="120.0.0.0/8",
        prefix_step=1 << 8,  # one /24 per prefix
        prefix_length=24,
        prefix_count=_FLAP_CHURN_ROUTE_COUNT,
        network_group_index=1,
        communities=_FLAP_ACCEPT_COMMUNITIES,
        attributes=_NOTIF_INJECT_ROUTE_ATTRIBUTES,
    ),
)
_FLAP_CHURN_V6_INTENTS = (
    _extra_formulaic_advertisement(
        prefix_name="PREFIX_POOL_IPV6_EBGP_FLAP_CHURN",
        afi="v6",
        start_prefix="2401:db00:11:2600::",
        parent_network="2401:db00:11:2000::/52",
        prefix_step=1 << 64,  # one /64 per prefix
        prefix_length=64,
        prefix_count=_FLAP_CHURN_ROUTE_COUNT,
        network_group_index=1,
        communities=_FLAP_ACCEPT_COMMUNITIES,
        attributes=_NOTIF_INJECT_ROUTE_ATTRIBUTES,
    ),
)


def create_bgp_ug_bit_alloc_group_stab_under_flap_test_config(
    testbed: PhysicalInventory,
) -> taac_types.TestConfig:
    """BGP++ Update Group qualification spec 2.6.1 (Repeated Peer Flaps -- Group
    Remains Stable) TestConfig -- its OWN WITHOUT_OPEN_R config on the bag conveyor
    topology, resolving next-hops via the next-hop-self infra (no Open/R daemon).

    Rapidly flaps the SAME 32 eBGP sessions/AFI x50 (fixed contiguous range 1..32)
    while concurrently churning 10 advertise / 10 withdraw every 30s from the
    remaining peers, then brings the 32 stably back up and verifies the update group
    re-formed with all 140 members/AFI, distribution reaches every eBGP peer (incl the
    flapped 32) via a 200-route iBGP-side inject, and the daemon did not crash /
    corrupt the group (composite proxy) under bounded VmHWM growth + load. Select via
    ``--test-config BAG013_ASH6_BGP_UG_REPEATED_PEER_FLAPS_TEST``. See
    ``create_bgp_ug_repeated_peer_flaps_group_stable_playbook``.

    Distribution (criterion 2) is COUNT-ONLY via the PS gauge -- XFAIL on BOTH AFIs for
    now. ``getPostfilterAdvertisedNetworks`` set-equality is vacuous under an Update Group
    (T271301144), so the delta + uniform PS checks are the UG-safe substitute. crit-2 is
    TIME-bound at scale: HW 2026-07-29 read 0 delta at a 180s settle, but the device
    reached baseline+200 (per-eBGP PS 46500 -> 46700 on both AFIs, route in the RIB
    best-path carrying community 65529:39744) ~12-20 min post-inject -- so the DUT DOES
    re-advertise the 200 injected iBGP routes to every eBGP peer, just slowly after the
    50-cycle flap storm (NOT egress, NOT the once-suspected D32 formulaic-inject
    regression). The playbook uses a SINGLE MERGED 900s settle (both AFIs) to cover the
    observed convergence + a diagnostic PROBE logging received-vs-sent around the inject;
    crit-2 stays XFAIL (escape hatches on) until a run lands the +200 delta within the
    window, then the hatches drop. Criteria 1/3/4/5/6 are enforced. Criterion 3 (no
    bit-allocation corruption) is the composite proxy
    (group count + member counts + all-Established + distribution + no crash) --
    DNE-approved as the interim (2026-07-27); the direct signal (a freeConsumerBit
    double-free log/counter) is a DNE follow-up, not available yet. Criterion 4 (VmHWM
    growth < 200 MB) uses a WHOLE-TEST point-read bracket (snapshot bgpcpp VmHWM on the
    cold daemon in the prime stage, verify as the final stage), only meaningful when
    bgpcpp is freshly reloaded -- the 2.6.1 precondition ("reload BGP daemon"; the full
    setup starts it fresh); reusing a running daemon masks the monotonic high-water. It
    stays LOOSE for now (``vmhwm_growth_expected_fail=True``: breach flagged, not failed)
    while the 200-MB bar settles. See the playbook docstring. Uses WITHOUT_OPEN_R + the
    next-hop-self resolution infra (D113330327), the precondition for the DUT
    re-advertising the inject to eBGP.
    """
    bgp_mon_ignore_prefixes = [f"{IXIA_BGP_MON_IC_PARENT_NETWORK}::/80"]
    # Everything that is NOT an iBGP peer (both eBGP AFIs + BGP-MON): scopes the
    # "iBGP stays Established" monitor check to iBGP while eBGP is flapping. Same
    # construction as 2.9.6's non_ibgp_parent_prefixes.
    non_ibgp_parent_prefixes = (
        _EBGP_V6_PARENT_PREFIXES + _EBGP_V4_PARENT_PREFIXES + bgp_mon_ignore_prefixes
    )

    repeated_peer_flaps_playbook = create_bgp_ug_repeated_peer_flaps_group_stable_playbook(
        device_name=testbed.device_name,
        ebgp_peer_regex=_EBGP_PEER_REGEX,
        ebgp_v4_peer_group=PEERGROUP_EBGP_V4,
        ebgp_v6_peer_group=PEERGROUP_EBGP_V6,
        ibgp_v6_peer_group=PEERGROUP_IBGP_V6,
        # Per-AFI eBGP peer-name regexes for the criterion-1 per-peer IDENTITY check:
        # the flapped 32/AFI target addresses are resolved at runtime from these and
        # asserted back in the correct update group (right peer-group + AFI,
        # Established, JOINED_RUNNING) -- the genuine identity check the aggregate
        # 140/AFI count only proxies.
        ebgp_v4_peer_regex=_EBGP_V4_PEER_REGEX,
        ebgp_v6_peer_regex=_EBGP_V6_PEER_REGEX,
        non_ibgp_parent_prefixes=non_ibgp_parent_prefixes,
        # Step-2 churn: ONE combined v4|v6 regex so each advertise/withdraw toggles both
        # dedicated eBGP-side pools in a single op (2 ops/cycle = the flap's rate). churn
        # cycles default to flap_cycles in the playbook, so the churn spans the whole flap.
        churn_pool_regexes=[_FLAP_CHURN_COMBINED_POOL_REGEX],
        churn_route_count=_FLAP_CHURN_ROUTE_COUNT,
        # Step-5 distribution: dedicated unique-NLRI iBGP-side 200-route pools (v4 + v6)
        # so the DUT re-advertises to every eBGP peer under next-hop-self.
        ibgp_inject_pool_regex=_FLAP_INJECT_V4_POOL_REGEX,
        ibgp_v6_inject_pool_regex=_FLAP_INJECT_V6_POOL_REGEX,
        inject_route_count=_FLAP_INJECT_ROUTE_COUNT,
        # Per-peer distribution verify scopes (by peer-address subnet), BOTH AFIs.
        ebgp_v4_peer_parent_prefixes=_EBGP_V4_PARENT_PREFIXES,
        ebgp_v6_peer_parent_prefixes=_EBGP_V6_PARENT_PREFIXES,
        # crit-2 distribution PROBE (diagnostic, never fails): log the DUT's RECEIVED
        # count on the iBGP plane-1 inject-source peers + its SENT count to the eBGP
        # peers, around the inject + after the settle, so a 0-delta run shows
        # received-vs-readvertised (settle-too-short vs egress vs not-received).
        inject_source_parent_prefixes=_INJECT_SOURCE_PARENT_PREFIXES,
        # DISTRIBUTION (criterion 2) is STRICT on BOTH AFIs. HW run 2026-07-31 confirmed
        # it: the convergence poll landed all 280 eBGP peers at baseline+200 (per-eBGP
        # PS 46500 -> 46700, both AFIs), verify_bgp_sent_route_count_delta failures=0,
        # converging in ~61s (WITHIN_SLA under the 120s soft / 300s hard cap). The
        # earlier 0-delta was only a too-short 30s settle post-flap -- the inject IS
        # re-advertised, just time-bound at 1272-session scale after the 50-cycle storm
        # (NOT egress, NOT the refuted D32 formulaic-inject regression). The playbook's
        # ``*_distribution_expected_fail`` params stay default-off as a manual escape hatch
        # if a future run regresses; the probe still logs the received-vs-sent trajectory.
        # Post-recovery membership = the full 140/AFI baseline (NOT 32 -- the spec
        # verifies ALL members back) + the 4-group baseline.
        expected_ebgp_member_count_per_afi=_DUAL_STACK_EXPECTED_MEMBER_COUNTS[
            PEERGROUP_EBGP_V4
        ],
        expected_group_count=_EXPECTED_UPDATE_GROUP_COUNT,
        # Opt into the session-establish precheck RETRY: the ~1272-session full-scale
        # topology needs time to reach Established after the control-plane Bgp restart
        # (WITHOUT_OPEN_R + next-hop-self bring-up), so poll for ~3 min.
        prechecks=_edge_cases_prechecks(
            bgp_mon_ignore_prefixes,
            establish_retry_count=12,
            establish_retry_delay_seconds=15.0,
            establish_retry_delay_multiplier=1.0,
        ),
        bgp_mon_ignore_prefixes=bgp_mon_ignore_prefixes,
        # LOOSE criterion 4 for now: the whole-test VmHWM verify (point-read bracket)
        # still MEASURES + LOGS VmHWM growth and FLAGS a >200-MB breach (XFAIL), but does
        # NOT fail the test on it -- the 200-MB bar is not yet firm (pending the DNE
        # memory-bar discussion; 2.9.2 exceeded its 500-MB bar). A restart/crash still
        # fails. Flip to False to enforce the 200-MB gate once the bar is settled.
        vmhwm_growth_expected_fail=True,
        # Extra-safety absolute VmHWM ceiling (consistent with the other UG tests) --
        # separate from the criterion-4 200-MB growth gate.
        vmhwm_absolute_threshold_bytes=Gigabyte.GIG_10.value,
    )

    return build_bag_conveyor_test_config(
        testbed,
        name="BAG013_ASH6_BGP_UG_REPEATED_PEER_FLAPS_TEST",
        playbooks=[repeated_peer_flaps_playbook],
        # WITHOUT_OPEN_R + next-hop-self (D113330327): IXIA advertises next-hop = the
        # peer's connected IP and the DUT resolves it from interface state via the
        # bgpcpp gflag -- so the iBGP next-hops resolve and the DUT re-advertises the
        # inject to eBGP with no Open/R daemon (the precondition for measuring per-peer
        # distribution to the flapped peers).
        profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
        ebgp_next_hop_self=True,
        ibgp_next_hop_self=True,
        enable_update_group=True,
        # Dedicated unique-NLRI pools: the 200-route inject on plane-1's iBGP DC peers
        # (v4 + v6) + the 10-route churn on the eBGP uplinks (v4 + v6).
        extra_prefix_sets=tuple(
            prefix_set
            for prefix_set, _ in (
                *_FLAP_INJECT_V4_INTENTS,
                *_FLAP_INJECT_V6_INTENTS,
                *_FLAP_CHURN_V4_INTENTS,
                *_FLAP_CHURN_V6_INTENTS,
            )
        ),
        extra_prefix_advertisements={
            "dg_ibgp_v4_dc_p1": tuple(
                advertisement for _, advertisement in _FLAP_INJECT_V4_INTENTS
            ),
            "dg_ibgp_v6_dc_p1": tuple(
                advertisement for _, advertisement in _FLAP_INJECT_V6_INTENTS
            ),
            "dg_ebgp_v4": tuple(
                advertisement for _, advertisement in _FLAP_CHURN_V4_INTENTS
            ),
            "dg_ebgp_v6": tuple(
                advertisement for _, advertisement in _FLAP_CHURN_V6_INTENTS
            ),
        },
    )
