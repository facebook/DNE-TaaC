# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""BGP++ EBB characteristic ad-hoc testconfigs (egress peer-scale / perf-scaling).

Re-homed here after D111520998 consolidated ``cicd_ebb_int_tc.py`` down to the
8 conveyor-scheduled configs. The bag010 egress peer-scale (perf-scaling case1)
sweep is runnable via the Netcastle CLI (``--test-config``) but is not (yet)
wired into a ``dne_routing`` conveyor node, so it belongs in this ad-hoc
catalog rather than in ``cicd_ebb_int_tc.py`` (which is now the scheduled-only
source of truth).

External consumers import from this member module directly; see README.md §7.
"""

from taac.testconfigs.routing.factories.bgp_ebb_characteristic import (
    create_bgp_ebb_characteristic_performance_scaling_test_config,
    create_bgp_ebb_update_packing_test_config,
)
from taac.testconfigs.routing.physical_inventory import (
    BAG010_ASH6,
    BAG012_ASH6,
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


__all__ = [
    "BAG010_ASH6_SC1_EGRESS_PEER_SCALE_TEST_UPDATE_GROUP_CONFIG",
    "BAG012_UPDATE_PACKING_IXIA11_TEST_CONFIG_UG",
]
