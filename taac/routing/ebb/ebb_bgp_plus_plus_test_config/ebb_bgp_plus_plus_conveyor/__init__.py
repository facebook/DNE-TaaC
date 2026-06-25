# pyre-unsafe
"""
EBB BGP++ Conveyor Test Configurations.

This module contains test configurations for running BGP++ tests
in the conveyor CI/CD pipeline for EBB devices.
"""

from taac.testconfigs.routing.ebb.bag002_snc1_test_config import (
    BAG002_SNC1_CONVEYOR_TEST_CONFIG,
)
from taac.testconfigs.routing.ebb.bag010_ash6_test_config import (
    BAG010_ASH6_BGP_STAGE1_CONVEYOR_TEST_CONFIG,
    BAG010_ASH6_BGP_STAGE1_CONVEYOR_TEST_UPDATE_GROUP_CONFIG,
    BAG010_ASH6_CONVEYOR_LONGEVITY_TEST_CONFIG,
    BAG010_ASH6_CONVEYOR_LONGEVITY_TEST_UPDATE_GROUP_CONFIG,
    BAG010_ASH6_DRAIN_CONVEYOR_TEST_CONFIG,
    BAG010_ASH6_DRAIN_CONVEYOR_TEST_UPDATE_GROUP_CONFIG,
    BAG010_ASH6_INSTABILITY_CONVEYOR_TEST_CONFIG,
    BAG010_ASH6_INSTABILITY_CONVEYOR_TEST_UPDATE_GROUP_CONFIG,
    BAG010_ASH6_RUNTIME_UPDATE_CONVEYOR_TEST_CONFIG,
    BAG010_ASH6_RUNTIME_UPDATE_CONVEYOR_TEST_UPDATE_GROUP_CONFIG,
)
from taac.testconfigs.routing.ebb.bag011_ash6_test_config import (
    BAG011_ASH6_BGP_OSCILLATIONS_CONVEYOR_TEST_CONFIG,
    BAG011_ASH6_BGP_OSCILLATIONS_CONVEYOR_TEST_UPDATE_GROUP_CONFIG,
    BAG011_ASH6_BGP_RESTART_CONVEYOR_TEST_CONFIG,
    BAG011_ASH6_BGP_RESTART_CONVEYOR_TEST_UPDATE_GROUP_CONFIG,
    BAG011_ASH6_BGP_STABILITY_CONVEYOR_TEST_CONFIG,
    BAG011_ASH6_BGP_STABILITY_CONVEYOR_TEST_UPDATE_GROUP_CONFIG,
    BAG011_ASH6_BGP_STAGE1_CONVEYOR_TEST_CONFIG,
    BAG011_ASH6_BGP_STAGE1_CONVEYOR_TEST_UPDATE_GROUP_CONFIG,
)
from taac.testconfigs.routing.ebb.bag012_ash6_test_config import (
    BAG012_ASH6_BOUNDED_ECMP_SETS_TEST_UPDATE_GROUP_CONFIG,
    BAG012_ASH6_CONSTANT_ATTRIBUTE_STORAGE_TEST_CONFIG,
    BAG012_ASH6_CONSTANT_ATTRIBUTE_STORAGE_TEST_UPDATE_GROUP_CONFIG,
    BAG012_ASH6_CONVEYOR_TEST_CONFIG,
    BAG012_ASH6_CONVEYOR_TEST_UPDATE_GROUP_CONFIG,
    BAG012_ASH6_PERFORMANCE_SCALING_TEST_CONFIG,
    BAG012_ASH6_PERFORMANCE_SCALING_TEST_UPDATE_GROUP_CONFIG,
    BAG012_ASH6_QUEUE_MEMORY_MONITOR_TEST_CONFIG,
    BAG012_ASH6_QUEUE_MEMORY_MONITOR_TEST_UPDATE_GROUP_CONFIG,
    BGP_UG_NEW_PEER_JOIN_TEST_CONFIG,
)
from taac.testconfigs.routing.ebb.bag013_ash6_test_config import (
    BAG013_ASH6_CONVEYOR_TEST_CONFIG,
    BAG013_ASH6_CONVEYOR_TEST_UPDATE_GROUP_CONFIG,
)


# Aggregated list of all EBB BGP++ conveyor node test configs.
# Ordered by conveyor stage execution (reliability-based):
#
# Stage 1: BAG011 Restart (Tier 1) + BAG012 Const Attr + BAG012 Update Packing (leaf)
# Stage 2: BAG010 MEGA (mixed) + BAG011 Oscillations (Tier 1-2)
# Stage 3: BAG011 Stability (Tier 3) + BAG012 Queue Memory
# Stage 4: BAG010 Longevity (solo)
#
# bag011.ash6 also exposes ``*_UPDATE_GROUP`` variants of all three configs
# (Restart / Oscillations / Stability). Each variant runs the same playbooks
# but dynamically toggles ``enable_update_group=True`` and writes the
# ``update_group_config`` struct (per D100093369) via an in-shell patch of
# ``/mnt/flash/bgpcpp_config`` during BGP++ deployment.
# bag010.ash6 also exposes ``*_UPDATE_GROUP`` variants of all four configs
# (Instability + RuntimeUpdate + Drain + Longevity) following the same
# pattern. The legacy MEGA config has been split into focused per-workload
# configs (instability, runtime-update, drain, longevity) so each can be
# scheduled, debugged, and toggled with ``_UPDATE_GROUP`` independently.
EBB_BGP_PLUS_PLUS_CONVEYOR_NODE_TEST_CONFIGS = [
    BAG002_SNC1_CONVEYOR_TEST_CONFIG,
    # bag010.ash6 — Stage 1 consolidated (attribute_churn + route_storm +
    # runtime_update + multipath_oscillation + pnh_metric_oscillation moved
    # from bag011 for cross-device balance) → Stage 2: longevity.
    BAG010_ASH6_BGP_STAGE1_CONVEYOR_TEST_CONFIG,
    BAG010_ASH6_BGP_STAGE1_CONVEYOR_TEST_UPDATE_GROUP_CONFIG,
    # bag010.ash6 — legacy per-workload configs (kept for one-off debugging
    # and rollback; the dne_routing conveyor no longer schedules these once
    # the cconf cuts over to the Stage 1 / Stage 2 layout)
    BAG010_ASH6_INSTABILITY_CONVEYOR_TEST_CONFIG,
    BAG010_ASH6_RUNTIME_UPDATE_CONVEYOR_TEST_CONFIG,
    BAG010_ASH6_DRAIN_CONVEYOR_TEST_CONFIG,
    BAG010_ASH6_CONVEYOR_LONGEVITY_TEST_CONFIG,
    BAG010_ASH6_INSTABILITY_CONVEYOR_TEST_UPDATE_GROUP_CONFIG,
    BAG010_ASH6_RUNTIME_UPDATE_CONVEYOR_TEST_UPDATE_GROUP_CONFIG,
    BAG010_ASH6_DRAIN_CONVEYOR_TEST_UPDATE_GROUP_CONFIG,
    BAG010_ASH6_CONVEYOR_LONGEVITY_TEST_UPDATE_GROUP_CONFIG,
    # bag011.ash6 — Stage 1 consolidated (Restart + Oscillations + Stability,
    # minus pnh_metric_oscillation moved to bag010).
    BAG011_ASH6_BGP_STAGE1_CONVEYOR_TEST_CONFIG,
    BAG011_ASH6_BGP_STAGE1_CONVEYOR_TEST_UPDATE_GROUP_CONFIG,
    # bag011.ash6 — legacy per-workload configs (kept for one-off debugging
    # and rollback)
    BAG011_ASH6_BGP_RESTART_CONVEYOR_TEST_CONFIG,
    BAG011_ASH6_BGP_OSCILLATIONS_CONVEYOR_TEST_CONFIG,
    BAG011_ASH6_BGP_STABILITY_CONVEYOR_TEST_CONFIG,
    BAG011_ASH6_BGP_RESTART_CONVEYOR_TEST_UPDATE_GROUP_CONFIG,
    BAG011_ASH6_BGP_OSCILLATIONS_CONVEYOR_TEST_UPDATE_GROUP_CONFIG,
    BAG011_ASH6_BGP_STABILITY_CONVEYOR_TEST_UPDATE_GROUP_CONFIG,
    # bag012.ash6 (3 configs: Update Packing, Const Attr, Queue Memory)
    BAG012_ASH6_CONVEYOR_TEST_CONFIG,
    BAG012_ASH6_CONSTANT_ATTRIBUTE_STORAGE_TEST_CONFIG,
    BAG012_ASH6_QUEUE_MEMORY_MONITOR_TEST_CONFIG,
    # bag012.ash6 BGP++ Performance Scaling — single TestConfig with one
    # Playbook whose Stages sweep IBGP egress peer counts [100,200,300,400,500]
    # per AF, advertising 50K v6 + 50K v4 EBGP prefixes per Stage. Each Stage
    # rewrites /mnt/flash/bgpcpp_config in place to the matching peer count.
    BAG012_ASH6_PERFORMANCE_SCALING_TEST_CONFIG,
    # bag012.ash6 _UPDATE_GROUP variants (same playbooks; BGP++ update_group +
    # enableSerializeGroupPdu patched into /mnt/flash/bgpcpp_config during
    # BGP++ deployment so the conveyor qualifies the update-group feature
    # alongside the baseline).
    BAG012_ASH6_CONVEYOR_TEST_UPDATE_GROUP_CONFIG,
    BAG012_ASH6_CONSTANT_ATTRIBUTE_STORAGE_TEST_UPDATE_GROUP_CONFIG,
    BAG012_ASH6_QUEUE_MEMORY_MONITOR_TEST_UPDATE_GROUP_CONFIG,
    BAG012_ASH6_PERFORMANCE_SCALING_TEST_UPDATE_GROUP_CONFIG,
    # bag012.ash6 BGP++ Bounded ECMP Sets (update_group enabled) — converted
    # from EB02-ARISTA_PERFORMANCE_SCALING_TEST_9_BOUNDED_ECMP_SETS. Device
    # setup runs via netcastle's managed shell (no raw SSH). Not yet wired into
    # a conveyor stage (pending a measured run).
    BAG012_ASH6_BOUNDED_ECMP_SETS_TEST_UPDATE_GROUP_CONFIG,
    # BGP++ Update Group "new peer join" qualification (specs 2.4.1 + 2.4.2
    # + 2.4.3 combined into one TestConfig with 3 playbooks sharing the
    # 21-eBGP + 4-iBGP testbed). Ad-hoc; not yet wired into a conveyor stage
    # (do NOT schedule until manually verified on the device).
    BGP_UG_NEW_PEER_JOIN_TEST_CONFIG,
    # bag013.ash6 (ad-hoc, not in conveyor stages).
    # ``_UPDATE_GROUP`` variant adds the Update Group qualification 2.7.2
    # sustained-link-flap playbook (rotates flapping the 3 IXIA ports on
    # independent cadences, asserts no cross-group BGP session disruption).
    BAG013_ASH6_CONVEYOR_TEST_CONFIG,
    BAG013_ASH6_CONVEYOR_TEST_UPDATE_GROUP_CONFIG,
]
