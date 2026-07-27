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

To bring back a previously-removed config, add a factory call with the
appropriate topology and playbook selection plus the inline ``CONVEYOR:``
marker identifying which conveyor node consumes it.
"""

from taac.abstractions.physical_inventory import (
    BAG010_ASH6,
    BAG011_ASH6,
    BAG012_ASH6,
)
from taac.testconfigs.routing.factories.bgp_ebb_characteristic import (
    create_bgp_ebb_characteristic_bounded_ecmp_sets_test_config,
    create_bgp_ebb_constant_attribute_storage_test_config,
    create_bgp_ebb_queue_memory_monitor_test_config,
    create_bgp_ebb_update_packing_test_config,
)
from taac.testconfigs.routing.factories.bgp_ebb_full_scale import (
    create_bgp_ebb_full_scale_test_config,
)


# ─── BAG010 conveyor configs ─────────────────────────────────────────────────
# CONVEYOR: dne_routing / bag010_instability_node
# CONVEYOR: dne_routing / bag010_runtime_node
BAG010_STAGE1_CONSOLIDATED_TEST_CONFIG = create_bgp_ebb_full_scale_test_config(
    BAG010_ASH6,
    name="BAG010_STAGE1_CONSOLIDATED_TEST_CONFIG",
    playbooks_selected=[
        "bgp_ebb_attribute_churn_playbook",
        "bgp_ebb_route_storm_playbook",
        "bgp_ebb_route_registry_runtime_update_playbook",
        "bgp_ebb_multipath_group_oscillation_playbook",
        "bgp_ebb_igp_pnh_metric_oscillation_playbook",
    ],
    enable_update_group=False,
)
# CONVEYOR: dne_routing / bag010_drain_node
BAG010_DRAIN_TEST_CONFIG_UG = create_bgp_ebb_full_scale_test_config(
    BAG010_ASH6,
    name="BAG010_DRAIN_TEST_CONFIG_UG",
    playbooks_selected=[
        "bgp_ebb_fauu_drain_undrain_playbook",
        "bgp_ebb_plane_drain_undrain_playbook",
    ],
)
# CONVEYOR: dne_routing / bag010_longevity_node
BAG010_LONGEVITY_TEST_CONFIG = create_bgp_ebb_full_scale_test_config(
    BAG010_ASH6,
    name="BAG010_LONGEVITY_TEST_CONFIG",
    playbooks_selected=["bgp_ebb_longevity_playbook"],
    enable_update_group=False,
)


# ─── BAG011 conveyor configs ─────────────────────────────────────────────────
# Both bag010 and bag011 bind the same full-scale topology. Their runtime
# arrangements select different playbook subsets from the shared ordered suite.
# CONVEYOR: dne_routing / bag011_restart_ebgp_node
# CONVEYOR: dne_routing / bag011_ibgp_stability_node
BAG011_STAGE1_CONSOLIDATED_TEST_CONFIG = create_bgp_ebb_full_scale_test_config(
    BAG011_ASH6,
    name="BAG011_STAGE1_CONSOLIDATED_TEST_CONFIG",
    playbooks_selected=[
        "bgp_ebb_daemon_restart_playbook",
        "bgp_ebb_cold_start_playbook",
        "bgp_ebb_ebgp_session_oscillation_playbook",
        "bgp_ebb_ebgp_route_oscillation_playbook",
        "bgp_ebb_ibgp_plane_session_oscillation_playbook",
        "bgp_ebb_ibgp_route_oscillation_playbook",
        "bgp_ebb_igp_unresolvable_pnh_playbook",
        "bgp_ebb_nexthop_group_count_threshold_playbook",
    ],
)


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
