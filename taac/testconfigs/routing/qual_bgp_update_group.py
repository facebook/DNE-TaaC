# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""BGP Update Group qualification testconfigs — one catalog constant per spec section.

Post-Wave-6 layout: all 7 sub-sections (2.1 through 2.7) have a catalog
constant here. Sections 2.2, 2.5, 2.6 are SKELETON — empty-playbook
TestConfigs establishing the catalog surface pending implementation. See
``factories/qual_bgp_update_group/tc{N}_*.py`` for per-section factories.

Grandfathered Python constant names (referenced from cconf and elsewhere)
retained verbatim alongside the newer spec-anchored names.
"""

from taac.testconfigs.routing.factories.qual_bgp_update_group.tc1_distribution_correctness import (
    create_bgp_ug_distribution_correctness_test_config,
)
from taac.testconfigs.routing.factories.qual_bgp_update_group.tc2_peer_lifecycle import (
    create_bgp_ug_peer_lifecycle_test_config,
)
from taac.testconfigs.routing.factories.qual_bgp_update_group.tc3_backpressure import (
    create_bgp_ug_backpressure_test_config,
)
from taac.testconfigs.routing.factories.qual_bgp_update_group.tc4_new_peer_join import (
    create_bgp_ug_new_peer_join_test_config,
)
from taac.testconfigs.routing.factories.qual_bgp_update_group.tc5_multigroup_formation import (
    create_bgp_ug_multigroup_formation_test_config,
)
from taac.testconfigs.routing.factories.qual_bgp_update_group.tc6_bit_alloc_group_stab_under_flap import (
    create_bgp_ug_bit_alloc_group_stab_under_flap_test_config,
)
from taac.testconfigs.routing.factories.qual_bgp_update_group.tc7_disruption_recovery import (
    create_bgp_ug_disruption_recovery_test_config,
)
from taac.testconfigs.routing.factories.qual_bgp_update_group.tc9_edge_cases import (
    create_bgp_ug_best_path_change_test_config,
    create_bgp_ug_dual_stack_isolation_test_config,
    create_bgp_ug_edge_cases_test_config,
    create_bgp_ug_simultaneous_disruptions_test_config,
    create_bgp_ug_staggered_startup_test_config,
)
from taac.testconfigs.routing.physical_inventory import (
    BAG011_ASH6,
    BAG012_ASH6,
    BAG013_ASH6,
    EB03_LAB_ASH6,
)


# ─── Spec 2.1 Distribution Correctness ──────────────────────────────────
BAG013_ASH6_BGP_UG_INITIAL_DUMP_IDENTICAL_ROUTES_TEST_CONFIG = (
    create_bgp_ug_distribution_correctness_test_config(BAG013_ASH6)
)
EB03_LAB_ASH6_BGP_TEST_UPDATE_GROUP_CONFIG = (
    create_bgp_ug_distribution_correctness_test_config(EB03_LAB_ASH6)
)
# Existing ixia11-named variant retained for ad-hoc callers. Both configs use
# BAG013_ASH6's canonical ixia11 wiring; ``name_override`` prevents a name
# collision with the standard config. Select via
# ``--test-config BAG013_ASH6_BGP_UG_INITIAL_DUMP_IDENTICAL_ROUTES_IXIA11_TEST``;
# not on the dne_routing conveyor.
BAG013_ASH6_BGP_UG_INITIAL_DUMP_IDENTICAL_ROUTES_IXIA11_TEST_CONFIG = (
    create_bgp_ug_distribution_correctness_test_config(
        BAG013_ASH6,
        name_override="BAG013_ASH6_BGP_UG_INITIAL_DUMP_IDENTICAL_ROUTES_IXIA11_TEST",
    )
)

# ─── Spec 2.2 Peer Lifecycle (SKELETON) ─────────────────────────────────
BGP_UG_PEER_LIFECYCLE_TEST_CONFIG = create_bgp_ug_peer_lifecycle_test_config(
    BAG013_ASH6
)

# ─── Spec 2.3 Backpressure ──────────────────────────────────────────────
BGP_UG_BACKPRESSURE_TEST_CONFIG = create_bgp_ug_backpressure_test_config(BAG013_ASH6)
BAG013_ASH6_BGP_UG_BACKPRESSURE_TOPOLOGY_SMOKE_CONFIG = (
    create_bgp_ug_backpressure_test_config(BAG013_ASH6, smoke_only=True)
)
EB03_LAB_ASH6_BGP_UG_BACKPRESSURE_TOPOLOGY_SMOKE_CONFIG = (
    create_bgp_ug_backpressure_test_config(EB03_LAB_ASH6, smoke_only=True)
)

# ─── Spec 2.4 New Peer Join ─────────────────────────────────────────────
BGP_UG_NEW_PEER_JOIN_TEST_CONFIG = create_bgp_ug_new_peer_join_test_config(BAG012_ASH6)

# ─── Spec 2.5 Multi-Group Formation (SKELETON) ──────────────────────────
BGP_UG_MULTIGROUP_FORMATION_TEST_CONFIG = (
    create_bgp_ug_multigroup_formation_test_config(BAG013_ASH6)
)

# ─── Spec 2.6 Bit Allocation Under Flaps (SKELETON) ─────────────────────
BGP_UG_BIT_ALLOC_GROUP_STAB_UNDER_FLAP_TEST_CONFIG = (
    create_bgp_ug_bit_alloc_group_stab_under_flap_test_config(BAG013_ASH6)
)

# ─── Spec 2.7 Disruption and Recovery ───────────────────────────────────
BAG013_ASH6_BGP_UG_SUSTAINED_LINK_FLAP_TEST_CONFIG = (
    create_bgp_ug_disruption_recovery_test_config(BAG013_ASH6)
)

# ─── Spec 2.9 Edge Cases and Adversarial Scenarios ──────────────────────
# Bundles the WITHOUT_OPEN_R section-2.9 edge-case playbooks (2.9.7 empty group
# live today; 2.9.1/2.9.3/2.9.6 land incrementally). Select an individual
# scenario at run time with ``--regex 'bgp_ug_<usecase>'``.
BAG011_ASH6_BGP_UG_EDGE_CASES_TEST_CONFIG = create_bgp_ug_edge_cases_test_config(
    BAG011_ASH6
)

# Spec 2.9.4 Dual-Stack Isolation -- its OWN WITH_OPEN_R TestConfig (the per-AFI
# distribution checks read the PS gauge, non-zero only once Open/R resolves the
# iBGP next-hops so the DUT advertises), separate from the WITHOUT_OPEN_R
# edge-cases bundle. Select via
# ``--test-config BAG011_ASH6_BGP_UG_DUAL_STACK_ISOLATION_TEST``. The IPv6
# distribution checks fail on bag011 today by design (bgpcpp v6 next-hop defect).
BAG011_ASH6_BGP_UG_DUAL_STACK_ISOLATION_TEST_CONFIG = (
    create_bgp_ug_dual_stack_isolation_test_config(BAG011_ASH6)
)

# Spec 2.9.2 Simultaneous Disruptions -- its OWN WITH_OPEN_R TestConfig (the
# IGP-instability track needs a running Open/R daemon + injected baseline routes),
# separate from the WITHOUT_OPEN_R edge-cases bundle. Select via
# ``--test-config BAG011_ASH6_BGP_UG_SIMULTANEOUS_DISRUPTIONS_TEST``. (The factory
# also accepts ``smoke=True`` for a short, ad-hoc machinery-validation variant --
# not committed as a catalog constant to keep the golden/registry surface minimal.)
BAG011_ASH6_BGP_UG_SIMULTANEOUS_DISRUPTIONS_TEST_CONFIG = (
    create_bgp_ug_simultaneous_disruptions_test_config(BAG011_ASH6)
)

# Spec 2.9.6 Staggered Peer Startup on bag013 -- its OWN WITHOUT_OPEN_R TestConfig
# using the next-hop-self resolution infra (D113330327) so the iBGP next-hops
# resolve and the DUT advertises with no Open/R daemon, separate from the
# WITHOUT_OPEN_R edge-cases bundle. Select via
# ``--test-config BAG013_ASH6_BGP_UG_STAGGERED_STARTUP_TEST``. Distribution is
# STRICT per-peer (criteria 1-2 uniform on both AFIs via the eBGP PS gauge +
# criterion-3 v4 +N delta; HW-validated on bag013 2026-07-23).
BAG013_ASH6_BGP_UG_STAGGERED_STARTUP_TEST_CONFIG = (
    create_bgp_ug_staggered_startup_test_config(BAG013_ASH6)
)

# Spec 2.9.1 Best-Path Change During Active Distribution on bag013 -- its OWN
# WITHOUT_OPEN_R TestConfig using the next-hop-self resolution infra (D113330327).
# Two eBGP competing sets (carved off the eBGP v4 peer budget) advertise the same
# 500 v4 prefixes with different AS-PATH lengths (AS-PATH is the DNE-approved
# discriminator; LOCAL_PREF is non-transitive over eBGP + EB-FA-IN sets no LP).
# Select via ``--test-config BAG013_ASH6_BGP_UG_BEST_PATH_CHANGE_TEST``.
# Converge-to-Set-B distribution is measure-first (the playbook probes the iBGP v4
# PS gauge; the adversarial no-crash/stability substance lands unconditionally).
BAG013_ASH6_BGP_UG_BEST_PATH_CHANGE_TEST_CONFIG = (
    create_bgp_ug_best_path_change_test_config(BAG013_ASH6)
)


__all__ = [
    "BAG011_ASH6_BGP_UG_DUAL_STACK_ISOLATION_TEST_CONFIG",
    "BAG011_ASH6_BGP_UG_EDGE_CASES_TEST_CONFIG",
    "BAG011_ASH6_BGP_UG_SIMULTANEOUS_DISRUPTIONS_TEST_CONFIG",
    "BAG013_ASH6_BGP_UG_BACKPRESSURE_TOPOLOGY_SMOKE_CONFIG",
    "BAG013_ASH6_BGP_UG_BEST_PATH_CHANGE_TEST_CONFIG",
    "BAG013_ASH6_BGP_UG_INITIAL_DUMP_IDENTICAL_ROUTES_TEST_CONFIG",
    "BAG013_ASH6_BGP_UG_STAGGERED_STARTUP_TEST_CONFIG",
    "BAG013_ASH6_BGP_UG_SUSTAINED_LINK_FLAP_TEST_CONFIG",
    "BGP_UG_BACKPRESSURE_TEST_CONFIG",
    "BGP_UG_BIT_ALLOC_GROUP_STAB_UNDER_FLAP_TEST_CONFIG",
    "BGP_UG_MULTIGROUP_FORMATION_TEST_CONFIG",
    "BGP_UG_NEW_PEER_JOIN_TEST_CONFIG",
    "BGP_UG_PEER_LIFECYCLE_TEST_CONFIG",
    "EB03_LAB_ASH6_BGP_TEST_UPDATE_GROUP_CONFIG",
    "EB03_LAB_ASH6_BGP_UG_BACKPRESSURE_TOPOLOGY_SMOKE_CONFIG",
]
