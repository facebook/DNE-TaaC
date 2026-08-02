# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""BGP++ EBB characteristic ad-hoc testconfigs (SC1/SC2/SC3/SC4/SC6/SC9).

Re-homed here after D111520998 consolidated ``cicd_ebb_int_tc.py`` down to the
8 conveyor-scheduled configs. The bag010 egress peer-scale (perf-scaling case1)
sweep is runnable via the Netcastle CLI (``--test-config``) but is not (yet)
wired into a ``dne_routing`` conveyor node, so it belongs in this ad-hoc
lifecycle binding module rather than in ``cicd_ebb_int_tc.py`` (which is now
the scheduled-only source of truth).

External consumers import from this member module directly; see
``fbcode/neteng/test_infra/routing_qualification/docs/taac/TESTCONFIGS.md``.
"""

from taac.abstractions.physical_inventory import (
    BAG010_ASH6,
    BAG012_ASH6,
)
from taac.testconfigs.routing.factories.bgp_ebb_characteristic import (
    create_bgp_ebb_characteristic_constant_attribute_storage_ingress_test_config,
    create_bgp_ebb_characteristic_performance_scaling_test_config,
    create_bgp_ebb_characteristic_route_churn_processing_test_config,
    create_bgp_ebb_characteristic_transient_memory_peer_scale_test_config,
    create_bgp_ebb_characteristic_transient_memory_route_scale_test_config,
    create_bgp_ebb_update_packing_test_config,
)


# ─── bag012.ash6 — Update Packing against ixia11 (Ethernet3/36) ───────────
# Same test as BAG012_UPDATE_PACKING_TEST_CONFIG_UG, with a distinct name for
# existing ad-hoc callers. Both configs use BAG012_ASH6's canonical ixia11 wiring.
# ``name_override`` gives it a distinct TestConfig.name; without it the factory
# would derive ``BAG012_UPDATE_PACKING_TEST_CONFIG_UG`` from the shared
# device_name and collide with the scheduled config. Ad-hoc: select via
# ``--test-config BAG012_UPDATE_PACKING_IXIA11_TEST_CONFIG_UG``; not on the
# dne_routing conveyor.
BAG012_UPDATE_PACKING_IXIA11_TEST_CONFIG_UG = create_bgp_ebb_update_packing_test_config(
    BAG012_ASH6,
    enable_update_group=True,
    name_override="BAG012_UPDATE_PACKING_IXIA11_TEST_CONFIG_UG",
)


# ═══════════════════════════════════════════════════════════════════════════
# bag010.ash6 — SC1/SC2/SC3/SC4/SC6/SC9 characteristic tests (re-homed from
# the retired bag010 bindings). Each factory derives TestConfig.name from
# ``testbed.device_name`` (→ ``BAG010_ASH6_SC*_*``) and threads the lab SSH
# auth + mock device data from the BAG010_ASH6 inventory (2-port: eBGP
# Ethernet3/36/1, iBGP Ethernet3/36/2; no BGP-MON). All are ad-hoc: resolvable
# via ``--test-config``, NOT scheduled on a dne_routing conveyor node. Per-SC
# spec link, topology, and fixed-vs-swept knobs are documented on each below.
# ═══════════════════════════════════════════════════════════════════════════


# ═══ SC1 · Constant Computation with Scale of Related Peers (char-1) ═════════
# Spec: https://docs.google.com/document/d/1lQeFLtIPaCgaOdjA7c70MHd8DiI1gMi5KnClF1lXUMY/edit?tab=t.jl9byfofjxc7#heading=h.jw39vb2b49lz
#
# PhysicalInventory-driven perf-scaling factory. One eBGP source feeds a fixed
# route set; the iBGP EGRESS fan-out ("related peers", one update-group) is
# swept. Because the group shares a single computed RIB-out, per-update
# computation must stay ~constant as the related-peer count grows (update-group
# amortization). This is the EGRESS complement to SC4's ingress-sender sweep.
#
#   IXIA eBGP ×1 ══▶ bag010 (DUT) ══▶ iBGP egress ×N  (one update-group)
#     fixed routes     router-id: device-default      [N swept]
#
#   ┌─ FIXED ──────────────────┬─ DYNAMIC (swept) ───────────────┐
#   │ eBGP ingress = 1         │ iBGP egress (related) peers     │
#   │ route count  = fixed     │   — fan-out swept, one UG       │
#   │ router-id    = default   │                                 │
#   └──────────────────────────┴─────────────────────────────────┘
#   SIGNAL: per-update compute ~flat as related-peer count grows (UG amortized)
#   name  : BAG010_ASH6_SC1_EGRESS_PEER_SCALE_TEST_UPDATE_GROUP
BAG010_ASH6_SC1_EGRESS_PEER_SCALE_TEST_UPDATE_GROUP_CONFIG = (
    create_bgp_ebb_characteristic_performance_scaling_test_config(
        BAG010_ASH6, enable_update_group=True
    )
)


# ═══ SC2 · Constant Storage with Unique Attributes (char-2 · INGRESS-ONLY) ══
# Spec: https://docs.google.com/document/d/1lQeFLtIPaCgaOdjA7c70MHd8DiI1gMi5KnClF1lXUMY/edit?tab=t.wi1dm2q4vgfn#heading=h.vrwesbixasg6
#
# BAG012 varying-combinations engine, made ingress-only + non-vacuous. eBGP
# peers advertise a fixed 800K paths, ACCEPTED into the RIB (route_registry
# cleared + acceptance community) but with an UNRESOLVABLE nexthop — received +
# accepted yet NEVER advertised (no iBGP egress). Steady-state memory must stay
# ~constant regardless of how many distinct attribute sets back those 800K paths.
#
#   IXIA eBGP ×8 ══▶ bag010 (DUT) accept→RIB ──╳ nexthop unresolvable
#     800K paths      route_registry cleared   └─▶ never advertised
#
#   ┌─ FIXED ──────────────────┬─ DYNAMIC (swept) ───────────────┐
#   │ eBGP peers  = 8          │ unique attribute combinations:  │
#   │ total paths = 800K       │      100K → 800K                │
#   │ nexthop     = unresolv.  │                                 │
#   │ iBGP egress = none       │                                 │
#   └──────────────────────────┴─────────────────────────────────┘
#   GATES : acceptance (RECEIVED)=BLOCKING · mem-growth (≤ k^0.5)=BLOCKING
#   name  : BAG010_ASH6_SC2_CONSTANT_ATTRIBUTE_STORAGE_INGRESS_TEST_UPDATE_GROUP
BAG010_ASH6_SC2_CONSTANT_ATTRIBUTE_STORAGE_INGRESS_TEST_UPDATE_GROUP_CONFIG = (
    create_bgp_ebb_characteristic_constant_attribute_storage_ingress_test_config(
        BAG010_ASH6, enable_update_group=True
    )
)


# ═══ SC3 · Transient Memory Independent of Route Scale (char-3 · WITH egress) ═
# Spec: https://docs.google.com/document/d/1lQeFLtIPaCgaOdjA7c70MHd8DiI1gMi5KnClF1lXUMY/edit?tab=t.pmfwpf67zvce#heading=h.fj1dfjmslnla
#
# Testbed-driven route-scale sweep WITH egress. Both peer counts are pinned
# (eBGP=2 ingress, iBGP=500 egress; nexthops RESOLVABLE and advertised) and the
# ingress ROUTE count is swept. PRIMARY signal is the TRANSIENT memory (peak
# high-watermark − stable steady-state); it must stay ~flat as routes scale
# because bgpd bounds the burst via update-queue backpressure. A deduplicator-
# size check rides along as a bonus.
#
#   IXIA eBGP ×2 ══▶ bag010 (DUT) ══▶ iBGP egress ×500  (resolvable, advertised)
#     routes swept     full ingress → egress path
#
#   ┌─ FIXED ──────────────────┬─ DYNAMIC (swept) ───────────────┐
#   │ eBGP ingress = 2         │ ingress route count:            │
#   │ iBGP egress  = 500       │    10K → 50K                    │
#   │ nexthop      = resolved  │                                 │
#   └──────────────────────────┴─────────────────────────────────┘
#   SIGNAL: transient memory (peak − stable) ~flat as routes scale
#   GATES : transient-memory + dedup-size, both mode-flagged (default permissive)
#   name  : BAG010_ASH6_SC3_TRANSIENT_MEMORY_ROUTE_SCALE_TEST_UPDATE_GROUP
BAG010_ASH6_SC3_TRANSIENT_MEMORY_ROUTE_SCALE_TEST_UPDATE_GROUP_CONFIG = (
    create_bgp_ebb_characteristic_transient_memory_route_scale_test_config(
        BAG010_ASH6, enable_update_group=True
    )
)


# ═══ SC4 · Transient Memory (Almost) Independent of Peer Scale (char-4) ══════
# Spec: https://docs.google.com/document/d/1lQeFLtIPaCgaOdjA7c70MHd8DiI1gMi5KnClF1lXUMY/edit?tab=t.d0pctwqjofhp#heading=h.686jq5bx98vj
#
# INGRESS complement to SC1 (which sweeps egress). V6-ONLY (SC2 ingress parity):
# the eBGP INGRESS sender count is swept while the iBGP egress fan-out and the
# per-sender prefix set are held fixed. Every sender advertises the SAME 50K v6
# prefixes, so the unique-prefix table is fixed and only PATH multiplicity grows;
# the port peaks at 16×50K = 800K imported routes — matching SC2 and well under
# IxNetwork's 5M-routes/port cap (the retired dual-stack [4,16,32,64] design
# ×2-doubled to 6.4M and tripped it).
#
#   IXIA eBGP ×N (v6) ══▶ bag010 (DUT) ══▶ iBGP egress ×500  (fixed, advertised)
#     50K prefixes each     peak 16×50K = 800K              [N swept]
#
#   ┌─ FIXED ──────────────────┬─ DYNAMIC (swept) ───────────────┐
#   │ iBGP egress   = 500      │ eBGP ingress senders (v6):      │
#   │ prefixes/send = 50K v6   │    [1, 2, 4, 8, 16]             │
#   │ nexthop       = resolved │    → peak 800K imported         │
#   └──────────────────────────┴─────────────────────────────────┘
#   SIGNAL: transient memory ~flat as sender count grows (queue backpressure)
#   name  : BAG010_ASH6_SC4_TRANSIENT_MEMORY_PEER_SCALE_TEST_UPDATE_GROUP
BAG010_ASH6_SC4_TRANSIENT_MEMORY_PEER_SCALE_TEST_UPDATE_GROUP_CONFIG = (
    create_bgp_ebb_characteristic_transient_memory_peer_scale_test_config(
        BAG010_ASH6, enable_update_group=True
    )
)


# ═══ SC6 · Churn Processing Independent of Route/Attribute Scale (char-6) ════
# Spec: https://docs.google.com/document/d/1lQeFLtIPaCgaOdjA7c70MHd8DiI1gMi5KnClF1lXUMY/edit?tab=t.rkrbeqkkjqz3#heading=h.t1eoix5y3kfc
#
# Reuses the EB02 churn-P(N) engine (IPv6-only iBGP injection, 100-route churn
# batches) with bag010 device setup (interface-state nexthop gflag + Centralized
# Route Filter cleared). The total route scale is swept; at each scale the engine
# oscillates a 100-route churn and measures convergence. Update-group is applied
# via a post-replace config-patch task (the engine uses
# create_replace_bgp_peers_task, not topology binding): the patch flips the
# global bgp_setting_config flag and the persisted peers are re-grouped on the
# daemon restart.
#
#   IXIA iBGP inject ══▶ bag010 (DUT): churn 100 routes/batch, measure converge
#     route scale swept    (interface-state nexthop · CRF cleared)
#
#   ┌─ FIXED ──────────────────┬─ DYNAMIC (swept) ───────────────┐
#   │ churn batch  = 100       │ total route scale:              │
#   │ inject       = iBGP v6   │     5K → 50K                    │
#   │ nexthop      = iface-st. │                                 │
#   └──────────────────────────┴─────────────────────────────────┘
#   GATES : per-scale convergence (observe-first, 700s budget) + egress-queue
#           backpressure task (permissive default, observe until calibrated)
#   name  : BAG010_ASH6_SC6_CHURN_PROCESSING_TEST_UPDATE_GROUP
BAG010_ASH6_SC6_CHURN_PROCESSING_TEST_UPDATE_GROUP_CONFIG = (
    create_bgp_ebb_characteristic_route_churn_processing_test_config(
        BAG010_ASH6, enable_update_group=True
    )
)


__all__ = [
    "BAG012_UPDATE_PACKING_IXIA11_TEST_CONFIG_UG",
    "BAG010_ASH6_SC1_EGRESS_PEER_SCALE_TEST_UPDATE_GROUP_CONFIG",
    "BAG010_ASH6_SC2_CONSTANT_ATTRIBUTE_STORAGE_INGRESS_TEST_UPDATE_GROUP_CONFIG",
    "BAG010_ASH6_SC3_TRANSIENT_MEMORY_ROUTE_SCALE_TEST_UPDATE_GROUP_CONFIG",
    "BAG010_ASH6_SC4_TRANSIENT_MEMORY_PEER_SCALE_TEST_UPDATE_GROUP_CONFIG",
    "BAG010_ASH6_SC6_CHURN_PROCESSING_TEST_UPDATE_GROUP_CONFIG",
]
