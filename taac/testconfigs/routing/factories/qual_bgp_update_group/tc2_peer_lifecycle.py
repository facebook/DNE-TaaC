# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Spec 2.2 — Peer Lifecycle Within Update Groups. UG qualification testconfig factory.

Implemented (all three, matching the catalog's implementation_status):
- 2.2.1 Peer Down: Remaining Group Members Unaffected (QUAL-UG-03)
- 2.2.2 Peer Reconnect: Re-Sync from Shadow RIB (QUAL-UG-04)
- 2.2.3 Sustained Group Membership Churn: No Memory Leak (QUAL-UG-05)

Wires all three playbooks on the shared EBB-scale bag conveyor topology (reuses
the tc1 ``build_bag_conveyor_test_config`` helper); select one at runtime with
``--regex``. Session ranges below are 1-based to match IXIA and are sized to
each catalog entry's stated scale (64 / 32 / 32 eBGP sessions).
"""

from taac.abstractions.physical_inventory import PhysicalInventory
from taac.constants import (  # oss-rewrite-touch
    BgpPlusPlusProfile,
    Gigabyte,
)
from taac.playbooks.routing.factories.qual_bgp_update_group.tc2_peer_lifecycle import (
    create_bgp_ug_peer_down_remaining_unaffected_playbook,
    create_bgp_ug_peer_reconnect_shadow_rib_playbook,
    create_bgp_ug_sustained_group_membership_churn_playbook,
)
from taac.testconfigs.routing.factories.qual_bgp_update_group.tc1_distribution_correctness import (
    build_bag_conveyor_test_config,
)
from taac.testconfigs.routing.util.bgp_ebb_constants import (
    EBGP_PEER_COUNT_V4,
    EBGP_PEER_COUNT_V6,
    IBGP_PEER_SCALE_PER_PLANE,
    IXIA_BGP_MON_IC_PARENT_NETWORK,
    IXIA_EBGP_IC_PARENT_NETWORK_V4,
    IXIA_EBGP_IC_PARENT_NETWORK_V6,
    PEERGROUP_EBGP_V4,
    PEERGROUP_EBGP_V6,
    PEERGROUP_IBGP_V4,
    PEERGROUP_IBGP_V6,
)
from taac.testconfigs.routing.util.bgp_ebb_health_checks import (
    BgpMonScope,
    create_standard_prechecks,
)
from taac.test_as_a_config import types as taac_types


# BGP-peer-name regexes matching eBGP peers for the session-drop workload.
# Matched with ``re.search`` against the BGP-peer name. eBGP names carry
# ``EBGP``; cleanly disjoint from iBGP (``IBGP``) and BGP-MON.
_EBGP_PEER_REGEX = r"BGP_PEER_IPV[46]_EBGP$"

# Parent prefixes of every NON-iBGP peer: the eBGP plane (v6 + v4) plus
# BGP-MON. The playbooks pass this as ``parent_prefixes_to_ignore``, so ignoring
# it scopes their "iBGP still Established" assertion to iBGP-only peers.
#
# eBGP v6 is a /80. eBGP v4 uses a /16, not a /24, for the same reason the iBGP
# v4 planes do: 140 peers at stride 2 from 10.163.28.11 run to offset 295 and
# spill past the /24 into 10.163.29.x, so a /24 would leave part of the eBGP
# plane in scope. The /16 is safe because the iBGP v4 planes live on distinct
# second octets (10.164 - 10.171).
_EBGP_PARENT_PREFIXES = [
    f"{IXIA_EBGP_IC_PARENT_NETWORK_V6}::/80",
    f"{'.'.join(IXIA_EBGP_IC_PARENT_NETWORK_V4.split('.')[:2])}.0.0/16",
]

# Spec distribution workload: inject from the imported eBGP IPv6 route pool
# (withdraw + re-advertise while a subset of eBGP peers is down). ``$`` excludes
# the unused ``_DRAIN`` pool (topology is built drain=False).
_EBGP_INJECT_POOL_REGEX = r"PREFIX_POOL_IPV6_EBGP$"

# Total ESTABLISHED sessions on EBB full-scale (BGP-MON excluded, matching
# tc3_backpressure): 280 eBGP (140 V4 + 140 V6) + 992 iBGP (62/plane * 8 * 2)
# = 1272. The precheck asserts this exact count before the drop; without it the
# check defaults to expecting 0 and fails against the fully-up topology.
_EXPECTED_ESTABLISHED_SESSIONS = (
    EBGP_PEER_COUNT_V6 + EBGP_PEER_COUNT_V4 + IBGP_PEER_SCALE_PER_PLANE * 8 * 2
)


def _ebgp_v6_peer_addr(idx: int) -> str:
    """IXIA-side eBGP v6 peer address for the idx-th (0-based) peer.

    Matches the topology's ``_generate_ixia_v6_peer_entries_for_bgpcpp``
    arithmetic (start_offset=0x10, stride=2): parent::{0x11 + 2*idx}. Address
    index i maps to session i, so the start/stop session ranges below select the
    same peers these addresses name.
    """
    return f"{IXIA_EBGP_IC_PARENT_NETWORK_V6}::{0x11 + 2 * idx:x}"


# The route-set-equality verification peers. 2.2.1 drops 1-based sessions 1-64
# and 2.2.2 drops 1-32, i.e. 0-based peer indices 0-63 and 0-31, so 0-based
# indices >= 64 are survivors/never-dropped in BOTH cases.
# Baseline is the top eBGP v6 peer (never dropped); 2.2.1 compares other top
# survivors to it, 2.2.2 compares the reconnected bottom peers (drop-set members)
# to it -- non-vacuous because the baseline never went down.
_SURVIVOR_BASELINE_PEER_ADDR = _ebgp_v6_peer_addr(EBGP_PEER_COUNT_V6 - 1)
_SURVIVOR_TESTED_PEER_ADDRS = [
    _ebgp_v6_peer_addr(i) for i in range(EBGP_PEER_COUNT_V6 - 5, EBGP_PEER_COUNT_V6 - 1)
]
_RECONNECT_BASELINE_PEER_ADDR = _ebgp_v6_peer_addr(EBGP_PEER_COUNT_V6 - 1)
_RECONNECT_TESTED_PEER_ADDRS = [_ebgp_v6_peer_addr(i) for i in range(0, 5)]

# QUAL-UG-03 stops sessions 1-64, and the range is applied to the v4 and v6 peer
# objects alike, so each AFI loses the same count. Asserting the surviving
# Established totals is what turns "the departed peers were removed cleanly"
# into a gate: "the groups still exist" would also hold if the stopped peers
# were still counted as members.
_PEER_DOWN_DROP_START_IDX = 1
_PEER_DOWN_DROP_END_IDX = 64
_PEER_DOWN_DROPPED_PER_AFI = _PEER_DOWN_DROP_END_IDX - _PEER_DOWN_DROP_START_IDX + 1
_PEER_DOWN_EXPECTED_MEMBER_COUNTS = {
    PEERGROUP_EBGP_V4: EBGP_PEER_COUNT_V4 - _PEER_DOWN_DROPPED_PER_AFI,
    PEERGROUP_EBGP_V6: EBGP_PEER_COUNT_V6 - _PEER_DOWN_DROPPED_PER_AFI,
}

# bgpcpp CPU ceiling for the 2.2.1 isolation window, gated on the raw p95
# (100% == one core; bag011 has 12).
#
# Calibrated from a bag011 run of this case: p70=15.1 p80=15.2 p95=17.9
# p99=36.1 peak=51.9, over 146 samples in a 626s window. The body of the
# distribution is flat to p95 and only the tail spikes, so p95 is the stable
# statistic to gate on: at n=146 the p99 is ~1.5 samples and is noise.
#
# 35 is ~2x the observed p95. Tripping it needs CPU roughly doubled across the
# whole window, which is a real regression; a brief spike cannot trip it,
# because a spike lands in p99/peak, not p95. Deliberately loose for now: this
# is calibrated from a single run, and the same case has shown 74s vs 231s
# convergence across runs, so the CPU spread is unlikely to be tighter. Worth
# taking to ~25 once a few more runs confirm the body sits near 15%.
_PEER_DOWN_CPU_P95_GATE_PCT = 35.0

# QUAL-UG-04 asserts the reconnected peers rejoined, so the expected counts are
# the FULL per-group membership, not the reduced set 2.2.1 asserts: the check
# runs after the resync soak, by which point every peer the trigger stopped is
# required to be Established again.
_PEER_RECONNECT_EXPECTED_MEMBER_COUNTS = {
    PEERGROUP_EBGP_V4: EBGP_PEER_COUNT_V4,
    PEERGROUP_EBGP_V6: EBGP_PEER_COUNT_V6,
}


def create_bgp_ug_peer_lifecycle_test_config(
    physical_inventory: PhysicalInventory,
) -> taac_types.TestConfig:
    """Spec 2.2 — Peer Lifecycle Within Update Groups. UG qualification testconfig.

    Wires the three 2.2 lifecycle playbooks on the shared EBB-scale bag conveyor
    topology (reuses tc1's ``build_bag_conveyor_test_config`` helper). Select one
    with ``--regex`` at runtime:

    - 2.2.1 ``bgp_ug_peer_down_remaining_unaffected``: stop 64 eBGP, inject 50
      routes through survivors, soak, assert iBGP Established / UG intact / no
      crash / CPU-load-VmHWM bounded.
    - 2.2.2 ``bgp_ug_peer_reconnect_shadow_rib``: stop 32 eBGP, add 100 routes
      while down, reconnect, assert all sessions re-Established / rejoined UG /
      no crash.
    - 2.2.3 ``bgp_ug_sustained_group_membership_churn``: flap 32 eBGP for ~1 hour
      (4 checkpoints x 15 cycles), assert per-checkpoint stability + bounded
      memory growth (no leak).

    KNOWN GAPS: positive per-peer distribution/resync delta is not asserted
    (bag011 adj-RIB-out=0 under UG, T271301144); IXIA cannot service selects
    under full-scale churn (T282904746), so the churn/inject/reconnect IXIA ops
    are best-effort and 2.2.3's 1-min flap cadence is infra-gated.

    Args:
        physical_inventory: Device physical inventory (BAG011_ASH6 expected)

    Returns:
        TestConfig wiring the 2.2.1/2.2.2/2.2.3 playbooks on the bag conveyor
        topology
    """
    bgp_mon_ignore_prefixes = [f"{IXIA_BGP_MON_IC_PARENT_NETWORK}::/80"]
    # Everything that is NOT an iBGP peer: the eBGP plane (v6 + v4) plus
    # BGP-MON. The playbooks pass this as `parent_prefixes_to_ignore`, so
    # ignoring it scopes their "iBGP still Established" assertion to iBGP-only
    # peers. Building this from the iBGP planes instead would invert the scope
    # and assert that the very eBGP sessions 2.2.1 stops are Established.
    non_ibgp_parent_prefixes = _EBGP_PARENT_PREFIXES + bgp_mon_ignore_prefixes
    ebgp_peer_group_substrings = [PEERGROUP_EBGP_V4, PEERGROUP_EBGP_V6]
    ibgp_peer_group_substrings = [PEERGROUP_IBGP_V4, PEERGROUP_IBGP_V6]

    # Prechecks are identical across the three lifecycle playbooks (same
    # topology + session baseline); build one per playbook so no list is shared.
    def _prechecks():
        return create_standard_prechecks(
            peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
            peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
            expected_established_sessions=_EXPECTED_ESTABLISHED_SESSIONS,
            bgp_mon=BgpMonScope(exclude=True),
            # Precheck runs ~15-20s after the heavy full-scale setup, while bgpcpp
            # is still churning through initial convergence (~1272 sessions / ~1M
            # routes), so the 1-min load transiently exceeds the default 4.0
            # baseline (observed 4.05). Match the postcheck's 12.0 baseline so a
            # post-setup convergence spike does not fail the precheck.
            cpu_baseline=12.0,
            # Run the RIB-FIB consistency precheck against the FibAgent's own
            # programming counters instead of EOS's RIB. On this bgpcpp-without-
            # Open/R deployment the BGP FibAgent programs the ASIC via SDK at
            # AD=10, and those routes never appear in EOS's RIB (async_get_static_
            # routes) at AD=200 -- so the default EOS-sourced comparison reports
            # all ~94.5k routes "missing from Hardware FIB" even though the
            # FibAgent reports num_programmed_routes == num_of_routes with zero
            # failed NHGs. "fibagent" mode validates the real programming state
            # (T283201488). Verified on bag011: 94500/94500 programmed.
            rib_fib_precheck_json_params={"fib_hardware_source": "fibagent"},
        )

    peer_down_playbook = create_bgp_ug_peer_down_remaining_unaffected_playbook(
        device_name=physical_inventory.device_name,
        ebgp_peer_regex=_EBGP_PEER_REGEX,
        ebgp_peer_group_substrings=ebgp_peer_group_substrings,
        ibgp_peer_group_substrings=ibgp_peer_group_substrings,
        non_ibgp_parent_prefixes=non_ibgp_parent_prefixes,
        ebgp_inject_pool_regex=_EBGP_INJECT_POOL_REGEX,
        # QUAL-UG-03 stimulus: "inject 50 routes through survivors".
        inject_route_count=50,
        survivor_baseline_peer_addr=_SURVIVOR_BASELINE_PEER_ADDR,
        survivor_tested_peer_addrs=_SURVIVOR_TESTED_PEER_ADDRS,
        # QUAL-UG-03 scale: "Stop 64 eBGP sessions". IXIA session indices are
        # 1-based, so 1-64 is that set; the range is applied to the v4 and v6
        # peer objects alike.
        #
        # Index 0 is NOT a valid IXIA session. The earlier 0-63 form sent
        # "SessionIndices": "0-1"/"0-63" and left an IxNetwork-internal lock
        # unreleased, wedging the session: the next substantial operation
        # (the distribution inject's on-the-fly apply, ~10 min later) stalled
        # to the 600s Jetty ceiling and returned 504. That was the inject-504
        # -- neither churn volume nor stopped-but-present peers.
        sessions_to_drop_start_idx=_PEER_DOWN_DROP_START_IDX,
        sessions_to_drop_end_idx=_PEER_DOWN_DROP_END_IDX,
        isolation_expected_member_counts=_PEER_DOWN_EXPECTED_MEMBER_COUNTS,
        cpu_gate_threshold_pct=_PEER_DOWN_CPU_P95_GATE_PCT,
        prechecks=_prechecks(),
        vmhwm_threshold_bytes=Gigabyte.GIG_10.value,
    )

    # 2.2.2 Peer Reconnect: Re-Sync from Shadow RIB.
    peer_reconnect_playbook = create_bgp_ug_peer_reconnect_shadow_rib_playbook(
        device_name=physical_inventory.device_name,
        ebgp_peer_regex=_EBGP_PEER_REGEX,
        ebgp_peer_group_substrings=ebgp_peer_group_substrings,
        ibgp_peer_group_substrings=ibgp_peer_group_substrings,
        non_ibgp_parent_prefixes=non_ibgp_parent_prefixes,
        ebgp_inject_pool_regex=_EBGP_INJECT_POOL_REGEX,
        inject_route_count=100,
        reconnect_baseline_peer_addr=_RECONNECT_BASELINE_PEER_ADDR,
        reconnect_tested_peer_addrs=_RECONNECT_TESTED_PEER_ADDRS,
        # QUAL-UG-04 scale: "Stop 32 eBGP peers". Indices are 1-based and
        # inclusive, so 1-32 is exactly 32 sessions.
        sessions_to_reconnect_start_idx=1,
        sessions_to_reconnect_end_idx=32,
        reconnect_expected_member_counts=_PEER_RECONNECT_EXPECTED_MEMBER_COUNTS,
        prechecks=_prechecks(),
        bgp_mon_ignore_prefixes=bgp_mon_ignore_prefixes,
        vmhwm_threshold_bytes=Gigabyte.GIG_10.value,
    )

    # 2.2.3 Sustained Group Membership Churn: No Memory Leak.
    sustained_churn_playbook = create_bgp_ug_sustained_group_membership_churn_playbook(
        device_name=physical_inventory.device_name,
        ebgp_peer_regex=_EBGP_PEER_REGEX,
        ebgp_peer_group_substrings=ebgp_peer_group_substrings,
        ibgp_peer_group_substrings=ibgp_peer_group_substrings,
        non_ibgp_parent_prefixes=non_ibgp_parent_prefixes,
        prechecks=_prechecks(),
        vmhwm_threshold_bytes=Gigabyte.GIG_10.value,
        # QUAL-UG-05 scale: "Flap 32 eBGP peers". Indices are 1-based and
        # inclusive, so 1-32 is exactly 32 sessions.
        sessions_to_flap_start_idx=1,
        sessions_to_flap_end_idx=32,
    )

    return build_bag_conveyor_test_config(
        physical_inventory,
        # Explicit name matching the sibling UG qualification TestConfigs
        # (e.g. BAG011_ASH6_BGP_UG_EDGE_CASES_TEST) and the golden-manifest
        # convention -- NOT _derive_test_config_name (which drops _ASH6 and
        # appends _CONFIG_UG). --test-config resolves against this .name.
        name="BAG011_ASH6_BGP_UG_PEER_LIFECYCLE_TEST",
        playbooks=[
            peer_down_playbook,
            peer_reconnect_playbook,
            sustained_churn_playbook,
        ],
        profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
        enable_update_group=True,
    )
