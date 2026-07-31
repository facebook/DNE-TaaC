# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Spec 2.5 — Multi-Group Formation Correctness. UG qualification testconfig factories.

Implemented:
- 2.5.1 Multiple Groups Formed for Different Outbound Policies -- its OWN
  WITHOUT_OPEN_R + next-hop-self config on the bag conveyor topology (4 update
  groups: one per peer-group x AFI).

The umbrella skeleton factory ``create_bgp_ug_multigroup_formation_test_config``
(empty-playbook placeholder) is retained for now; 2.5.2 (scale withdraw) will
replace it once implemented.
"""

from taac.abstractions.physical_inventory import PhysicalInventory
from neteng.test_infra.dne.taac.constants import BgpPlusPlusProfile, Gigabyte
from taac.playbooks.routing.factories.qual_bgp_update_group.tc5_multigroup_formation import (
    create_bgp_ug_multiple_groups_outbound_policies_playbook,
)
from taac.testconfigs.routing.factories.qual_bgp_update_group.tc1_distribution_correctness import (
    build_bag_conveyor_test_config,
)
from taac.testconfigs.routing.factories.qual_bgp_update_group.tc9_edge_cases import (
    _DUAL_STACK_EXPECTED_MEMBER_COUNTS,
    _edge_cases_prechecks,
    _extra_formulaic_advertisement,
    _IBGP_V4_PARENT_PREFIXES,
    _IBGP_V6_PARENT_PREFIXES,
    _NOTIF_INJECT_ROUTE_ATTRIBUTES,
    _STAGGERED_INJECT_COMMUNITIES,
)
from taac.testconfigs.routing.util.bgp_ebb_constants import (
    IXIA_BGP_MON_IC_PARENT_NETWORK,
    PEERGROUP_EBGP_V4,
    PEERGROUP_EBGP_V6,
    PEERGROUP_IBGP_V4,
    PEERGROUP_IBGP_V6,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import Endpoint, TestConfig

# The DUT (a conveyor node) carries two baseline BGP-MON neighbors (ASN 64001, under
# IXIA_BGP_MON_IC_PARENT_NETWORK) that never establish on a conveyor node
# (production-normal). BGP-MON is NOT emulated or tested here, but those DUT-side
# neighbors still show up as IDLE sessions, so the establish precheck must ignore them
# -- exactly as every 2.9.x edge-case test does. (Our earlier warm 2.5.1 run passed
# because it ignored them; the clean rip-out dropped the ignore, which reds the
# precheck at 1272/1274 -- HW run 2026-07-30.)
_BGP_MON_IGNORE_PREFIXES = [f"{IXIA_BGP_MON_IC_PARENT_NETWORK}::/80"]


# =============================================================================
# Spec 2.5.1 Multiple Groups Formed for Different Outbound Policies
# =============================================================================
# The four update groups the EBB-scale conveyor topology forms at steady state:
# one per (peer-group x AFI). BGP-MON is NOT tested (DNE: monitor peers do not
# establish on the bag013 conveyor node), so the builder uses its default topology
# and there is no 5th add-path group.
_MULTIGROUP_EXPECTED_GROUP_COUNT = 4
# Member baselines: iBGP 62x8 = 496 / AFI, eBGP 140 / AFI (from the shared
# dual-stack baseline). If the topology differs, the STRICT group-formation
# structure check fails loudly with the observed counts.
_MULTIGROUP_EXPECTED_MEMBER_COUNTS = {
    PEERGROUP_IBGP_V6: _DUAL_STACK_EXPECTED_MEMBER_COUNTS[PEERGROUP_IBGP_V6],
    PEERGROUP_IBGP_V4: _DUAL_STACK_EXPECTED_MEMBER_COUNTS[PEERGROUP_IBGP_V4],
    PEERGROUP_EBGP_V6: _DUAL_STACK_EXPECTED_MEMBER_COUNTS[PEERGROUP_EBGP_V6],
    PEERGROUP_EBGP_V4: _DUAL_STACK_EXPECTED_MEMBER_COUNTS[PEERGROUP_EBGP_V4],
}
# Each peer-group's update group is keyed on its egress policy: iBGP on EB-EB-OUT,
# eBGP on EB-FA-OUT (the live golden values, same as the eb03 2.1.1 dump).
_MULTIGROUP_EXPECTED_POLICY_NAMES = {
    PEERGROUP_IBGP_V6: ["EB-EB-OUT"],
    PEERGROUP_IBGP_V4: ["EB-EB-OUT"],
    PEERGROUP_EBGP_V6: ["EB-FA-OUT"],
    PEERGROUP_EBGP_V4: ["EB-FA-OUT"],
}

# 100 genuinely-new v6 eBGP routes injected during the distribution stage, so the
# +N distribution to the iBGP-v6 group is measurable and the cross-AFI
# no-leak (iBGP-v4 unchanged) is provable. Dedicated unique NLRI in the v6
# EB-PRIVATE accept aggregate 2401:db00:11:2000::/52 (TestPrefixes.EB_PRIVATE_PREFIX),
# starting at ::2100 -- disjoint from every other v6 EB-PRIVATE inject pool on
# master (2.9.6 2000-2031, 2.9.1 2800::/54, 2.9.8 ::2c00, 2.9.3 ::2e00, and the
# 2.6.1 ::2400/::2600 draft). Carries the accept communities the real DC routes
# carry (so the DUT re-advertises it eBGP->iBGP) + the eBGP DG's mandatory
# route-attribute schema. Attached to the eBGP v6 device group ("dg_ebgp_v6").
_MULTIGROUP_INJECT_ROUTE_COUNT = 100
_MULTIGROUP_V6_INJECT_POOL_REGEX = r"PREFIX_POOL_IPV6_EBGP_MULTIGROUP_INJECT$"
_MULTIGROUP_V6_INJECT_PREFIX_SET, _MULTIGROUP_V6_INJECT_ADVERTISEMENT = (
    _extra_formulaic_advertisement(
        prefix_name="PREFIX_POOL_IPV6_EBGP_MULTIGROUP_INJECT",
        afi="v6",
        start_prefix="2401:db00:11:2100::",
        parent_network="2401:db00:11:2000::/52",
        prefix_step=1 << 64,  # one /64 per prefix
        prefix_length=64,
        prefix_count=_MULTIGROUP_INJECT_ROUTE_COUNT,
        network_group_index=1,
        communities=_STAGGERED_INJECT_COMMUNITIES,
        attributes=_NOTIF_INJECT_ROUTE_ATTRIBUTES,
    )
)


def create_bgp_ug_multiple_groups_outbound_policies_test_config(
    physical_inventory: PhysicalInventory,
) -> taac_types.TestConfig:
    """BGP++ Update Group qualification spec 2.5.1 (Multiple Groups Formed for
    Different Outbound Policies) TestConfig -- its OWN WITHOUT_OPEN_R +
    next-hop-self config on the bag conveyor topology.

    Verifies (spec 2.5.1): peers with different outbound policies form SEPARATE
    update groups (EB-EB-V4/V6 iBGP on EB-EB-OUT, EB-FA-V4/V6 eBGP on EB-FA-OUT --
    4 groups total); routes distributed within a group reach all members identically
    (crit 2); no cross-AFI leak (crit 3 -- v6 routes do not appear in the iBGP-v4
    group). See ``create_bgp_ug_multiple_groups_outbound_policies_playbook``.

    All checks are STRICT. Group formation (crit 1) + cross-AFI no-leak (crit 3) are
    structural; the +N distribution (crit 2) was HW-validated 2026-07-29 (all 496
    iBGP-v6 peers received +100 uniformly at the 30s settle). BGP-MON is NOT tested
    (DNE-confirmed: monitor peers do not establish on bag013), so there is no add-path
    (crit-4) stage and no 5th group.

    The builder defaults to the standard EBB_FULL_SCALE graph (no BGP-MON DG /
    3rd port). WITHOUT_OPEN_R + next-hop-self (D113330327) so the DUT resolves
    next-hops from interface state and advertises with no Open/R daemon -- the
    precondition for the per-peer PS-gauge distribution checks (consistent with
    2.9.1/2.9.3/2.9.6/2.9.8).
    """
    assert len(physical_inventory.ixia_ports) >= 2, (
        "2.5.1 requires >= 2 IXIA ports (eBGP + iBGP); BGP-MON is not tested."
    )

    multigroup_playbook = create_bgp_ug_multiple_groups_outbound_policies_playbook(
        device_name=physical_inventory.device_name,
        ibgp_v6_peer_group=PEERGROUP_IBGP_V6,
        ibgp_v4_peer_group=PEERGROUP_IBGP_V4,
        ebgp_v6_peer_group=PEERGROUP_EBGP_V6,
        ebgp_v4_peer_group=PEERGROUP_EBGP_V4,
        expected_member_counts=_MULTIGROUP_EXPECTED_MEMBER_COUNTS,
        expected_policy_names=_MULTIGROUP_EXPECTED_POLICY_NAMES,
        expected_group_count=_MULTIGROUP_EXPECTED_GROUP_COUNT,
        # PS-gauge distribution scopes (by peer-address subnet, AFI-specific).
        ibgp_v6_peer_parent_prefixes=_IBGP_V6_PARENT_PREFIXES,
        ibgp_v4_peer_parent_prefixes=_IBGP_V4_PARENT_PREFIXES,
        ebgp_v6_inject_pool_regex=_MULTIGROUP_V6_INJECT_POOL_REGEX,
        inject_route_count=_MULTIGROUP_INJECT_ROUTE_COUNT,
        # Retry the establish precheck: the WITHOUT_OPEN_R + next-hop-self setup
        # restarts the control-plane Bgp daemon on a fresh bring-up, so the full-scale
        # topology needs time to reach Established (the 2.9.x settle-race finding).
        prechecks=_edge_cases_prechecks(
            _BGP_MON_IGNORE_PREFIXES,
            establish_retry_count=12,
            establish_retry_delay_seconds=15.0,
            establish_retry_delay_multiplier=1.0,
            expected_group_count=_MULTIGROUP_EXPECTED_GROUP_COUNT,
        ),
        vmhwm_absolute_threshold_bytes=Gigabyte.GIG_10.value,
    )

    return build_bag_conveyor_test_config(
        physical_inventory,
        name="BAG013_ASH6_BGP_UG_MULTIPLE_GROUPS_TEST",
        playbooks=[multigroup_playbook],
        profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
        enable_update_group=True,
        # BGP-MON is not tested (DNE: monitor peers do not establish on bag013): the
        # builder defaults to the standard EBB_FULL_SCALE topology (no BGP-MON DG).
        # WITHOUT_OPEN_R + next-hop-self (D113330327): resolve next-hops from
        # interface state so the DUT advertises the test prefixes (no Open/R) -- the
        # precondition for the per-peer PS-gauge distribution checks.
        ebgp_next_hop_self=True,
        ibgp_next_hop_self=True,
        resolve_nexthops_from_interface_state=True,
        # The genuinely-new v6 inject pool staged on the eBGP v6 device group so the
        # DUT receives + re-advertises the 100 new routes to the iBGP v6 group.
        extra_prefix_sets=(_MULTIGROUP_V6_INJECT_PREFIX_SET,),
        extra_prefix_advertisements={
            "dg_ebgp_v6": (_MULTIGROUP_V6_INJECT_ADVERTISEMENT,)
        },
    )


def create_bgp_ug_multigroup_formation_test_config(
    physical_inventory: PhysicalInventory,
) -> taac_types.TestConfig:
    """Spec 2.5 — Multi-Group Formation Correctness. SKELETON qualification testconfig.

    Empty-playbook umbrella placeholder retained for the catalog surface; 2.5.2
    (scale withdraw) will replace it once implemented. 2.5.1 has its own dedicated
    factory (``create_bgp_ug_multiple_groups_outbound_policies_test_config``).
    """
    return TestConfig(
        name="BGP_UG_MULTIGROUP_FORMATION_TEST",
        endpoints=[
            Endpoint(
                name=physical_inventory.device_name,
                dut=True,
                ixia_ports=[physical_inventory.ixia_ports[0][0]]
                if physical_inventory.ixia_ports
                else [],
            ),
        ],
        playbooks=[],
    )
