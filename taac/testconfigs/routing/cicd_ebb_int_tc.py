# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""EBB integration testconfigs scheduled on the CICD conveyor.

Successor to ``conveyor_node_test_configs.py`` under
``routing/ebb/ebb_bgp_plus_plus_test_config/ebb_bgp_plus_plus_conveyor/``.
Holds bag conveyor testconfigs and is aggregated into
``EBB_BGP_PLUS_PLUS_CONVEYOR_NODE_TEST_CONFIGS``.

External consumers import via ``testconfigs.routing`` root; see README.md §7.

Source of truth
---------------
This file is the source of truth for the ``dne_routing`` conveyor's per-node
TestConfigs. Every constant declared here is scheduled by a node in
``configerator/source/nettools/ebb/release_engineering/conveyor_config/
dne_routing.conveyor_config.cconf``. Each definition carries an inline
``# CONVEYOR: dne_routing / <node_name>`` marker so the linkage is visible at
the definition site and grep-able across the repo.

Constant naming follows README.md §5:
``{PHYSICAL_INVENTORY}_{FACTORY}_TEST_CONFIG[_UG|_TOPOLOGY_SMOKE|...]``. The PHYSICAL_INVENTORY
segment drops any DC suffix (e.g. ``BAG010`` not ``BAG010_ASH6``) — the DC
lives on the PhysicalInventory instance in ``physical_inventory.py``, not in the catalog constant.

To bring back a previously-removed config, add a one-line factory call
following the same shape (factories in ``factories/bgp_ebb_{full_scale,
characteristic}.py`` are unchanged) plus the inline ``CONVEYOR:`` marker
identifying which conveyor node consumes it.
"""

from taac.testconfigs.routing.factories.bgp_ebb_characteristic import (
    create_bgp_ebb_characteristic_bounded_ecmp_sets_test_config,
    create_bgp_ebb_constant_attribute_storage_test_config,
    create_bgp_ebb_queue_memory_monitor_test_config,
    create_bgp_ebb_update_packing_test_config,
)
from taac.testconfigs.routing.factories.bgp_ebb_full_scale import (
    create_bgp_ebb_stage1_test_config,
    create_ebb_drain_test_config,
    create_ebb_longevity_test_config,
    create_ebb_stage1_consolidated_test_config,
)
from taac.testconfigs.routing.physical_inventory import (
    BAG010_ASH6,
    BAG011_ASH6,
    BAG012_ASH6,
)


# ─── BAG010 conveyor configs ─────────────────────────────────────────────────
# CONVEYOR: dne_routing / bag010_instability_node (regex bgp_instability_)
# CONVEYOR: dne_routing / bag010_runtime_node     (regex pnh_metric_oscillation|multipath_group_oscillation|route_registry_prefix_list_runtime_update)
BAG010_STAGE1_CONSOLIDATED_TEST_CONFIG = create_ebb_stage1_consolidated_test_config(
    BAG010_ASH6
)
# CONVEYOR: dne_routing / bag010_drain_node       (regex bgp_fauu_drain_undrain_playbook)
BAG010_DRAIN_TEST_CONFIG_UG = create_ebb_drain_test_config(
    BAG010_ASH6, enable_update_group=True
)
# CONVEYOR: dne_routing / bag010_longevity_node
BAG010_LONGEVITY_TEST_CONFIG = create_ebb_longevity_test_config(BAG010_ASH6)


# ─── BAG011 conveyor configs ─────────────────────────────────────────────────
# NB: bag011 uses ``create_bgp_ebb_stage1_test_config`` — a DIFFERENT factory
# from bag010's ``create_ebb_stage1_consolidated_test_config``. Both compose
# "Stage 1 consolidated" playbook sets, but bag011's playbooks are Restart +
# Oscillations + Stability (matches the bag011 conveyor node regexes) while
# bag010's are attribute_churn + route_storm + runtime_update + oscillations.
# Don't collapse to a single factory without redesigning both playbook sets.
# CONVEYOR: dne_routing / bag011_restart_ebgp_node    (regex daemon_restart|cold_start|bgp_ebgp_)
# CONVEYOR: dne_routing / bag011_ibgp_stability_node  (regex bgp_ibgp_|unresolvable_pnhs|nexthop_group_count)
BAG011_STAGE1_CONSOLIDATED_TEST_CONFIG = create_bgp_ebb_stage1_test_config(BAG011_ASH6)


# ─── BAG012 conveyor configs ─────────────────────────────────────────────────
# bag012 wires only 2 IXIA ports (no BGP-MON) so its factories live in
# ``factories/bgp_ebb_characteristic.py`` rather than the full-scale EBB
# factories which require a BGP-MON port.
# CONVEYOR: dne_routing / bag012_update_packing_node
BAG012_UPDATE_PACKING_TEST_CONFIG_UG = create_bgp_ebb_update_packing_test_config(
    BAG012_ASH6, enable_update_group=True
)
# CONVEYOR: dne_routing / bag012_cas_node
BAG012_CONSTANT_ATTRIBUTE_STORAGE_TEST_CONFIG = (
    create_bgp_ebb_constant_attribute_storage_test_config(BAG012_ASH6)
)
# CONVEYOR: dne_routing / bag012_qmm_node
BAG012_QUEUE_MEMORY_MONITOR_TEST_CONFIG = (
    create_bgp_ebb_queue_memory_monitor_test_config(BAG012_ASH6)
)
# CONVEYOR: dne_routing / bag012_bounded_ecmp_node
BAG012_BOUNDED_ECMP_SETS_TEST_CONFIG_UG = (
    create_bgp_ebb_characteristic_bounded_ecmp_sets_test_config(BAG012_ASH6)
)


__all__ = [
    "BAG010_DRAIN_TEST_CONFIG_UG",
    "BAG010_LONGEVITY_TEST_CONFIG",
    "BAG010_STAGE1_CONSOLIDATED_TEST_CONFIG",
    "BAG011_STAGE1_CONSOLIDATED_TEST_CONFIG",
    "BAG012_BOUNDED_ECMP_SETS_TEST_CONFIG_UG",
    "BAG012_CONSTANT_ATTRIBUTE_STORAGE_TEST_CONFIG",
    "BAG012_QUEUE_MEMORY_MONITOR_TEST_CONFIG",
    "BAG012_UPDATE_PACKING_TEST_CONFIG_UG",
]
