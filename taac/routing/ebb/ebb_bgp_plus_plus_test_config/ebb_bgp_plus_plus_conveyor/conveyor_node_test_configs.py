# pyre-unsafe
"""Aggregated EBB BGP++ conveyor node TestConfig list.

Exposes ``EBB_BGP_PLUS_PLUS_CONVEYOR_NODE_TEST_CONFIGS`` — every
BAG002/BAG010/BAG011/BAG012/BAG013 TestConfig referenced by the EBB
conveyor scheduler, in execution order.

Previously this aggregation lived in the package ``__init__.py``,
which meant the eager TestConfig imports ran on *any* attribute
access under ``ebb_bgp_plus_plus_conveyor`` (e.g. importing one
constant from ``.conveyor_constants``). On strict Python that
pulled in every bag-conveyor file and closed a circular import
via ``playbook_definitions`` ↔ ``testconfigs.routing.ebb``. Moving
the aggregation here keeps the package ``__init__`` side-effect
free; consumers that need the aggregated list import it from this
module directly.
"""

# bag010 SC1 egress peer-scale + SC2 constant attribute storage — ad-hoc
# scale-&-characteristics sweeps, runnable via --test-config but not scheduled
# on a conveyor node. Re-homed to testconfigs/routing/adhoc_bgp_ebb_characteristic.py
# after D111520998 pruned cicd_ebb_int_tc.py to the conveyor-scheduled configs only.
from taac.testconfigs.routing.adhoc_bgp_ebb_characteristic import (
    BAG010_ASH6_SC1_EGRESS_PEER_SCALE_TEST_UPDATE_GROUP_CONFIG,
    BAG010_ASH6_SC2_CONSTANT_ATTRIBUTE_STORAGE_INGRESS_TEST_UPDATE_GROUP_CONFIG,
    BAG010_ASH6_SC3_TRANSIENT_MEMORY_ROUTE_SCALE_TEST_UPDATE_GROUP_CONFIG,
    BAG010_ASH6_SC4_TRANSIENT_MEMORY_PEER_SCALE_TEST_UPDATE_GROUP_CONFIG,
    BAG010_ASH6_SC6_CHURN_PROCESSING_TEST_UPDATE_GROUP_CONFIG,
    BAG012_UPDATE_PACKING_IXIA11_TEST_CONFIG_UG,
)

# Post-cleanup: only the 8 configs actually referenced by
# ``dne_routing.conveyor_config.cconf`` remain in ``cicd_ebb_int_tc.py``.
# Every entry below has an inline ``CONVEYOR: dne_routing / <node>`` marker at
# its definition site (see cicd_ebb_int_tc.py) identifying the scheduling node.
from taac.testconfigs.routing.cicd_ebb_int_tc import (
    BAG010_CONSTANT_ATTRIBUTE_STORAGE_TEST_CONFIG_UG,
    BAG010_STAGE1_FULL_SCALE_TEST_CONFIG_UG,
    BAG011_QUEUE_MEMORY_MONITOR_TEST_CONFIG_UG,
    BAG011_STAGE1_FULL_SCALE_TEST_CONFIG_UG,
    BAG012_STAGE1_FULL_SCALE_TEST_CONFIG_UG,
    BAG012_UPDATE_PACKING_TEST_CONFIG_UG,
    BAG013_BOUNDED_ECMP_SETS_TEST_CONFIG_UG,
    BAG013_STAGE1_FULL_SCALE_TEST_CONFIG_UG,
)

# Migrated to the routing framework in Diffs 2 + 3 (Wave 1 Struct-Init):
# BGP_UG_NEW_PEER_JOIN_TEST_CONFIG (bag012 UG) + the two BAG013 conveyor
# TestConfigs (spec 2.1.1 initial-dump + 2.7.2 sustained-link-flap; renamed to
# BAG013_ASH6_BGP_UG_INITIAL_DUMP_IDENTICAL_ROUTES_TEST_CONFIG +
# BAG013_ASH6_BGP_UG_SUSTAINED_LINK_FLAP_TEST_CONFIG at the Python level, but
# the internal TestConfig ``name`` field is preserved verbatim as
# ``BAG013_ASH6_BGP_CONVEYOR_TEST`` / ``..._UPDATE_GROUP`` so the golden
# manifest is byte-wise identical) now live in
# testconfigs/routing/qual_bgp_update_group.py; import via that path.
from taac.testconfigs.routing.qual_bgp_update_group import (
    BAG011_ASH6_BGP_UG_DUAL_STACK_ISOLATION_TEST_CONFIG,
    BAG011_ASH6_BGP_UG_EDGE_CASES_TEST_CONFIG,
    BAG011_ASH6_BGP_UG_SIMULTANEOUS_DISRUPTIONS_TEST_CONFIG,
    BAG013_ASH6_BGP_UG_BACKPRESSURE_TOPOLOGY_SMOKE_CONFIG,
    BAG013_ASH6_BGP_UG_BEST_PATH_CHANGE_TEST_CONFIG,
    BAG013_ASH6_BGP_UG_CPU_QUANT_UG_OFF_TEST_CONFIG,
    BAG013_ASH6_BGP_UG_CPU_QUANT_UG_ON_TEST_CONFIG,
    BAG013_ASH6_BGP_UG_INITIAL_DUMP_IDENTICAL_ROUTES_TEST_CONFIG,
    BAG013_ASH6_BGP_UG_MULTIPLE_GROUPS_TEST_CONFIG,
    BAG013_ASH6_BGP_UG_NOTIFICATION_ISOLATION_TEST_CONFIG,
    BAG013_ASH6_BGP_UG_STAGGERED_STARTUP_TEST_CONFIG,
    BAG013_ASH6_BGP_UG_SUSTAINED_LINK_FLAP_TEST_CONFIG,
    BGP_UG_BACKPRESSURE_TEST_CONFIG,
    BGP_UG_NEW_PEER_JOIN_TEST_CONFIG,
)


# Aggregated list of every TestConfig registered with the routing framework's
# Netcastle registry. Two groups:
#   1. CONVEYOR configs — the 8 from ``cicd_ebb_int_tc.py`` that are scheduled
#      by ``dne_routing.conveyor_config.cconf`` (see the ``CONVEYOR:`` markers
#      in that file for the per-node mapping).
#   2. AD-HOC configs — BGP++ UG qualification testconfigs that are runnable
#      via Netcastle CLI but not (yet) wired into a conveyor node.
EBB_BGP_PLUS_PLUS_CONVEYOR_NODE_TEST_CONFIGS = [
    # Stage 1 — four runtime-balanced full-scale playbooks on each BAG.
    BAG010_STAGE1_FULL_SCALE_TEST_CONFIG_UG,
    BAG011_STAGE1_FULL_SCALE_TEST_CONFIG_UG,
    BAG012_STAGE1_FULL_SCALE_TEST_CONFIG_UG,
    BAG013_STAGE1_FULL_SCALE_TEST_CONFIG_UG,
    # Stage 2 — one scale-and-characteristic workflow on each BAG.
    BAG010_CONSTANT_ATTRIBUTE_STORAGE_TEST_CONFIG_UG,
    BAG011_QUEUE_MEMORY_MONITOR_TEST_CONFIG_UG,
    BAG012_UPDATE_PACKING_TEST_CONFIG_UG,
    BAG013_BOUNDED_ECMP_SETS_TEST_CONFIG_UG,
    # BGP++ Update Group "new peer join" qualification (specs 2.4.1 + 2.4.2
    # + 2.4.3 combined into one TestConfig with 3 playbooks sharing the
    # 21-eBGP + 4-iBGP testbed). Ad-hoc; not yet wired into a conveyor stage
    # (do NOT schedule until manually verified on the device).
    BGP_UG_NEW_PEER_JOIN_TEST_CONFIG,
    # BGP++ UG Backpressure & Blocking Behavior qualification (specs 2.3.1 +
    # 2.3.2 + 2.3.3 + 2.3.4 combined into one TestConfig with 4 playbooks
    # sharing the EBB full-scale topology on bag013). Ad-hoc; not in conveyor.
    BGP_UG_BACKPRESSURE_TEST_CONFIG,
    # Topology-smoke sibling -- 30-min longevity hold on the same testbed,
    # paired with --skip-teardown --skip-ixia-cleanup so the DUT + IXIA
    # session stay live for hands-on inspection. Ad-hoc; not in conveyor.
    BAG013_ASH6_BGP_UG_BACKPRESSURE_TOPOLOGY_SMOKE_CONFIG,
    # bag013.ash6 (ad-hoc, not in conveyor stages).
    # ``_UPDATE_GROUP`` variant adds the Update Group qualification 2.7.2
    # sustained-link-flap playbook (rotates flapping the 3 IXIA ports on
    # independent cadences, asserts no cross-group BGP session disruption)
    # plus the 2.1.1 initial-dump-identical-routes playbook (full parity
    # with eb03.lab.ash6).
    BAG013_ASH6_BGP_UG_INITIAL_DUMP_IDENTICAL_ROUTES_TEST_CONFIG,
    BAG013_ASH6_BGP_UG_SUSTAINED_LINK_FLAP_TEST_CONFIG,
    # bag010.ash6 SC1 egress peer-scale sweep. Ad-hoc: resolvable via
    # --test-config, not wired into a conveyor node. UG-only (all SC run UG).
    BAG010_ASH6_SC1_EGRESS_PEER_SCALE_TEST_UPDATE_GROUP_CONFIG,
    # bag012.ash6 Update Packing bound to ixia11 (Et3/36) instead of the
    # conveyor's ixia03 (Et3/35). Ad-hoc: resolvable via --test-config, not
    # scheduled on a conveyor node.
    BAG012_UPDATE_PACKING_IXIA11_TEST_CONFIG_UG,
    # bag010.ash6 SC2 constant attribute storage (char-2, INGRESS-ONLY) — the
    # BAG012 varying-combinations engine made ingress-only + non-vacuous: 8 eBGP
    # advertise 800K paths, accepted into RIB (route_registry cleared) but nexthop
    # unresolvable (no egress); sweeps unique attribute combinations (100K→800K)
    # and gates memory constancy + a received-count acceptance gate. Ad-hoc;
    # runnable via --test-config, not yet wired into a conveyor node.
    BAG010_ASH6_SC2_CONSTANT_ATTRIBUTE_STORAGE_INGRESS_TEST_UPDATE_GROUP_CONFIG,
    # bag010.ash6 SC3 transient memory (char-3) — the former SC2 route-scale
    # sweep WITH egress (eBGP=2 ingress + iBGP=500 egress, resolvable/advertised),
    # sweeps the ingress route count (10K→50K) and gates on the transient
    # (peak-minus-stable) memory (dedup rides along), update-group enabled.
    # Ad-hoc; runnable via --test-config, not yet wired into a conveyor node.
    BAG010_ASH6_SC3_TRANSIENT_MEMORY_ROUTE_SCALE_TEST_UPDATE_GROUP_CONFIG,
    # bag010.ash6 SC4 transient memory (char-4) — the INGRESS complement of SC1:
    # sweeps the eBGP ingress sender count (per AF, each n → 2*n eBGP peers) at a
    # fixed iBGP egress fan-out + fixed route count, routes resolvable/advertised,
    # and gates on the transient (peak-minus-stable) memory staying ~flat as the
    # sender count grows. Update-group enabled. Ad-hoc; runnable via --test-config,
    # not yet wired into a conveyor node.
    BAG010_ASH6_SC4_TRANSIENT_MEMORY_PEER_SCALE_TEST_UPDATE_GROUP_CONFIG,
    # bag010.ash6 SC6 churn processing P(N) (char-6) — convergence time vs route
    # scale. Reuses the EB02 churn P(N) engine (iBGP-injection IPv6-only, 100-route
    # churn, sweep total route scale 5K→50K) with bag010 device setup (nexthop gflag
    # + CRF cleared). The per-scale convergence gate is observe-first (generous 700s
    # budget); a queue-backpressure periodic task monitors egress-queue backlog
    # (permissive default). Update-group enabled via post-replace config-patch task
    # (global bgp_setting_config flag; persisted peers are re-grouped on restart).
    # Ad-hoc; runnable via --test-config, not yet wired into a conveyor node.
    BAG010_ASH6_SC6_CHURN_PROCESSING_TEST_UPDATE_GROUP_CONFIG,
    # BGP++ UG "edge cases" qualification (spec 2.9) on bag011.ash6. Bundles
    # the section-2.9 adversarial scenarios on the shared EBB full-scale
    # topology (2.9.7 empty-group live today; 2.9.1/2.9.2/2.9.3/2.9.4/2.9.6
    # land incrementally). Ad-hoc; not wired into a conveyor stage (do NOT
    # schedule until manually verified on the device). Select a scenario with
    # ``--regex 'bgp_ug_<usecase>'``.
    BAG011_ASH6_BGP_UG_EDGE_CASES_TEST_CONFIG,
    # BGP++ UG 2.9.2 Simultaneous Disruptions on bag011.ash6 -- its own WITH_OPEN_R
    # TestConfig (the IGP-instability track needs a running Open/R daemon). 30-min
    # run. Ad-hoc; NOT wired into a conveyor stage (do NOT schedule until manually
    # verified on the device).
    BAG011_ASH6_BGP_UG_SIMULTANEOUS_DISRUPTIONS_TEST_CONFIG,
    # BGP++ UG 2.9.4 Dual-Stack Isolation on bag011.ash6 -- its own WITH_OPEN_R
    # TestConfig (per-AFI PS-gauge distribution needs Open/R-resolved next-hops so
    # the DUT advertises). The IPv6 distribution checks fail by design on bag011
    # today (bgpcpp IPv6 next-hop-resolution defect). Ad-hoc; NOT wired into a
    # conveyor stage (do NOT schedule until manually verified on the device).
    BAG011_ASH6_BGP_UG_DUAL_STACK_ISOLATION_TEST_CONFIG,
    # BGP++ UG 2.9.6 Staggered Peer Startup on bag013.ash6 -- its own WITHOUT_OPEN_R
    # TestConfig using the next-hop-self resolution infra (D113330327) so the iBGP
    # next-hops resolve and the DUT advertises with no Open/R daemon. Distribution is
    # STRICT per-peer (criteria 1-2 uniform on both AFIs + criterion-3 v4 delta;
    # HW-validated on bag013). Ad-hoc; NOT wired into a conveyor stage (do NOT
    # schedule until manually verified on the device). Select with
    # ``--regex 'bgp_ug_staggered_startup'``.
    BAG013_ASH6_BGP_UG_STAGGERED_STARTUP_TEST_CONFIG,
    # BGP++ UG 2.9.1 Best-Path Change During Active Distribution on bag013.ash6 --
    # its own WITHOUT_OPEN_R TestConfig using the next-hop-self resolution infra
    # (D113330327). Two eBGP competing sets advertise the same 500 v4 prefixes with
    # different AS-PATH lengths (the DNE-approved discriminator); converge-to-Set-B
    # is measure-first, the adversarial no-crash/stability substance lands. Ad-hoc;
    # NOT wired into a conveyor stage (do NOT schedule until manually verified on the
    # device). Select with ``--regex 'bgp_ug_best_path_change'``.
    BAG013_ASH6_BGP_UG_BEST_PATH_CHANGE_TEST_CONFIG,
    # BGP++ UG 2.9.8 Quantifying CPU reduction on bag013.ash6 -- TWO WITHOUT_OPEN_R
    # + next-hop-self TestConfigs (UG off vs on) running the identical 1-hr dual-AFI
    # (v4 + v6) eBGP churn workload and comparing CPU. Run UG_OFF first (baseline),
    # then UG_ON (its comparison step reads the UG-off metrics file). Ad-hoc; NOT
    # wired into a conveyor stage (do NOT schedule until manually verified on the
    # device).
    BAG013_ASH6_BGP_UG_CPU_QUANT_UG_OFF_TEST_CONFIG,
    BAG013_ASH6_BGP_UG_CPU_QUANT_UG_ON_TEST_CONFIG,
    # BGP++ UG 2.9.3 NOTIFICATION Sent to One Peer -> Group Isolation on
    # bag013.ash6 -- its own WITHOUT_OPEN_R + next-hop-self TestConfig.
    # StopKeepAlive on ONE eBGP session/AFI drives a DUT-originated
    # Hold-Timer-Expired NOTIFICATION; the playbook verifies the drop is isolated
    # to that peer, distribution to everyone else keeps working, and the peer
    # re-syncs on ResumeKeepAlive. Dual-AFI. Ad-hoc; NOT wired into a conveyor
    # stage (do NOT schedule until manually verified on the device). Select with
    # ``--regex 'bgp_ug_notification_isolation'``.
    BAG013_ASH6_BGP_UG_NOTIFICATION_ISOLATION_TEST_CONFIG,
    # BGP++ UG 2.5.1 Multiple Groups Formed for Different Outbound Policies on
    # bag013.ash6 -- its own WITHOUT_OPEN_R + next-hop-self TestConfig on the
    # standard EBB_FULL_SCALE topology (BGP-MON not tested). Verifies each
    # peer-group x AFI is its own update group, no cross-AFI leak, and 4 groups
    # total; all checks STRICT (the +N distribution is convergence-polled). Ad-hoc;
    # NOT wired into a conveyor stage (do NOT schedule until manually verified on
    # the device). Select with ``--regex 'bgp_ug_multiple_groups_outbound_policies'``.
    BAG013_ASH6_BGP_UG_MULTIPLE_GROUPS_TEST_CONFIG,
]
