# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""BGP++ EBB characteristic ad-hoc testconfigs (SC1 egress peer-scale + SC2 constant-storage ingress + SC3 transient-memory route-scale).

Re-homed here after D111520998 consolidated ``cicd_ebb_int_tc.py`` down to the
8 conveyor-scheduled configs. The bag010 egress peer-scale (perf-scaling case1)
sweep is runnable via the Netcastle CLI (``--test-config``) but is not (yet)
wired into a ``dne_routing`` conveyor node, so it belongs in this ad-hoc
catalog rather than in ``cicd_ebb_int_tc.py`` (which is now the scheduled-only
source of truth).

External consumers import from this member module directly; see README.md §7.
"""

from taac.abstractions.physical_inventory import (
    BAG010_ASH6,
    BAG012_ASH6,
)
from taac.testconfigs.routing.factories.bgp_ebb_characteristic import (
    create_bgp_ebb_characteristic_constant_attribute_storage_ingress_test_config,
    create_bgp_ebb_characteristic_performance_scaling_test_config,
    create_bgp_ebb_characteristic_transient_memory_route_scale_test_config,
    create_bgp_ebb_update_packing_test_config,
)


# ─── bag010.ash6 — SC1 Egress peer-scale (scale & characteristics case 1) ─
# PhysicalInventory-driven characteristic factory (2-port, no BGP-MON); bag010 relies on
# the device-default router-id (no pinned router_id on the physical_inventory). Ad-hoc:
# resolvable via ``--test-config`` but not scheduled on a conveyor node. All SC
# tests run with update-group enabled, so only the ``_UPDATE_GROUP`` variant is
# kept; the non-UG base config was removed as dead weight. The TestConfig.name
# is ``BAG010_ASH6_SC1_EGRESS_PEER_SCALE_TEST_UPDATE_GROUP``.
BAG010_ASH6_SC1_EGRESS_PEER_SCALE_TEST_UPDATE_GROUP_CONFIG = (
    create_bgp_ebb_characteristic_performance_scaling_test_config(
        BAG010_ASH6, enable_update_group=True
    )
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


# ─── bag010.ash6 — SC2 Constant Attribute Storage (INGRESS-ONLY, char-2) ─
# Testbed-driven factory: the BAG012 varying-combinations engine made
# ingress-only + non-vacuous. 8 eBGP peers advertise 800K paths; routes are
# accepted into the RIB (route_registry cleared + acceptance community) but the
# nexthop is left unresolvable -> received+accepted, never advertised (NO iBGP
# egress). Sweeps the unique attribute COMBINATIONS (100K→800K) at fixed 800K
# paths; steady memory must stay ~constant. Acceptance gate (RECEIVED count) is
# blocking; the memory-variance gate is permissive. Ad-hoc: resolvable via
# --test-config. The TestConfig.name is
# ``BAG010_ASH6_SC2_CONSTANT_ATTRIBUTE_STORAGE_INGRESS_TEST_UPDATE_GROUP``.
BAG010_ASH6_SC2_CONSTANT_ATTRIBUTE_STORAGE_INGRESS_TEST_UPDATE_GROUP_CONFIG = (
    create_bgp_ebb_characteristic_constant_attribute_storage_ingress_test_config(
        BAG010_ASH6, enable_update_group=True
    )
)


# ─── bag010.ash6 — SC3 Transient Memory (route-scale sweep, WITH egress) ─
# Testbed-driven factory (the former SC2 route-scale sweep + egress). Fixes both
# peer counts (eBGP=2 ingress, iBGP=500 egress, RESOLVABLE, advertised) and
# sweeps the ingress ROUTE count (10K→50K). The PRIMARY signal is the TRANSIENT
# memory (peak high-watermark - stable steady-state); it must stay ~flat as
# routes scale (bgpd bounds it via update-queue backpressure). The
# deduplicator-size check rides along as a bonus. Both gates expose a
# blocking|permissive mode flag (default permissive). Ad-hoc: resolvable via
# --test-config but not scheduled on a conveyor node. All SC tests run with
# update-group enabled, so only the ``_UPDATE_GROUP`` variant is kept. The
# TestConfig.name is ``BAG010_ASH6_SC3_TRANSIENT_MEMORY_ROUTE_SCALE_TEST_UPDATE_GROUP``.
BAG010_ASH6_SC3_TRANSIENT_MEMORY_ROUTE_SCALE_TEST_UPDATE_GROUP_CONFIG = (
    create_bgp_ebb_characteristic_transient_memory_route_scale_test_config(
        BAG010_ASH6, enable_update_group=True
    )
)


__all__ = [
    "BAG010_ASH6_SC1_EGRESS_PEER_SCALE_TEST_UPDATE_GROUP_CONFIG",
    "BAG010_ASH6_SC2_CONSTANT_ATTRIBUTE_STORAGE_INGRESS_TEST_UPDATE_GROUP_CONFIG",
    "BAG010_ASH6_SC3_TRANSIENT_MEMORY_ROUTE_SCALE_TEST_UPDATE_GROUP_CONFIG",
    "BAG012_UPDATE_PACKING_IXIA11_TEST_CONFIG_UG",
]
