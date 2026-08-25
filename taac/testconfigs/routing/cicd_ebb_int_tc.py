# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""EBB CICD lifecycle bindings scheduled on the ``dne_routing`` conveyor.

The lifecycle layout schedules one stage across four BAG devices. Stage 1
partitions the 16 in-scope full-scale Playbooks into four runtime-balanced
groups. Its conveyor bindings run without update groups, while retained UG
counterparts remain available for qualification and comparison. The four
UG-enabled scale-and-characteristic configs remain resolvable for later
onboarding but are not scheduled. Every config uses standalone OpenR. Catalog
governance lives in
``fbcode/neteng/test_infra/routing_qualification/catalogs/taac/bgp_ebb_catalog.yaml``.
"""

from taac.abstractions.physical_inventory import (
    BAG010_ASH6,
    BAG011_ASH6,
    BAG012_ASH6,
    BAG013_ASH6,
)
from taac.constants import BgpPlusPlusProfile
from taac.testconfigs.routing.factories.bgp_ebb_characteristic import (
    create_bgp_ebb_characteristic_bounded_ecmp_sets_test_config,
    create_bgp_ebb_queue_memory_monitor_test_config,
    create_bgp_ebb_update_packing_test_config,
)
from taac.testconfigs.routing.factories.bgp_ebb_full_scale import (
    create_bgp_ebb_full_scale_test_config,
)


_OPENR_STANDALONE = BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R


# Stage 1: four full-scale playbooks per device. BAG010 runs longevity last.
# Each config lists its playbooks inline so what a Conveyor node runs is
# readable at the node, without resolving a shared constant. The UG and Non-UG
# configs for a device are expected to list the same playbooks, BAG011 aside.
# CONVEYOR: dne_routing / bag010_stage1_node
BAG010_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG = create_bgp_ebb_full_scale_test_config(
    BAG010_ASH6,
    name="BAG010_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG",
    playbooks_selected=[
        "bgp_ebb_route_registry_runtime_update_playbook",
        "bgp_ebb_daemon_restart_playbook",
        "bgp_ebb_cold_start_playbook",
        "bgp_ebb_longevity_playbook",
    ],
    profile=_OPENR_STANDALONE,
    enable_update_group=False,
)

BAG010_STAGE1_FULL_SCALE_TEST_CONFIG_UG = create_bgp_ebb_full_scale_test_config(
    BAG010_ASH6,
    name="BAG010_STAGE1_FULL_SCALE_TEST_CONFIG_UG",
    playbooks_selected=[
        "bgp_ebb_route_registry_runtime_update_playbook",
        "bgp_ebb_daemon_restart_playbook",
        "bgp_ebb_cold_start_playbook",
        "bgp_ebb_longevity_playbook",
    ],
    profile=_OPENR_STANDALONE,
    enable_update_group=True,
)

# CONVEYOR: dne_routing / bag011_stage1_node
# The one Stage 1 config that does not match its UG counterpart: plane
# drain/undrain is omitted here because it is a known failure without update
# groups. This node is a non-blocking Conveyor leaf, so that failure gated
# nothing and only cost IXIA and DUT setup time on every run. Coverage is
# unaffected: bag011_stage1_ug_node gates tagging and RPM promotion, and the UG
# config below still runs the playbook.
BAG011_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG = create_bgp_ebb_full_scale_test_config(
    BAG011_ASH6,
    name="BAG011_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG",
    playbooks_selected=[
        "bgp_ebb_attribute_churn_playbook",
        "bgp_ebb_fauu_drain_undrain_playbook",
        "bgp_ebb_ibgp_route_oscillation_playbook",
    ],
    profile=_OPENR_STANDALONE,
    enable_update_group=False,
)

BAG011_STAGE1_FULL_SCALE_TEST_CONFIG_UG = create_bgp_ebb_full_scale_test_config(
    BAG011_ASH6,
    name="BAG011_STAGE1_FULL_SCALE_TEST_CONFIG_UG",
    playbooks_selected=[
        "bgp_ebb_attribute_churn_playbook",
        "bgp_ebb_fauu_drain_undrain_playbook",
        "bgp_ebb_plane_drain_undrain_playbook",
        "bgp_ebb_ibgp_route_oscillation_playbook",
    ],
    profile=_OPENR_STANDALONE,
    enable_update_group=True,
)

# CONVEYOR: dne_routing / bag012_stage1_node
BAG012_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG = create_bgp_ebb_full_scale_test_config(
    BAG012_ASH6,
    name="BAG012_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG",
    playbooks_selected=[
        "bgp_ebb_route_storm_playbook",
        "bgp_ebb_multipath_group_oscillation_playbook",
        "bgp_ebb_igp_pnh_metric_oscillation_playbook",
        "bgp_ebb_ebgp_session_oscillation_playbook",
    ],
    profile=_OPENR_STANDALONE,
    enable_update_group=False,
)

BAG012_STAGE1_FULL_SCALE_TEST_CONFIG_UG = create_bgp_ebb_full_scale_test_config(
    BAG012_ASH6,
    name="BAG012_STAGE1_FULL_SCALE_TEST_CONFIG_UG",
    playbooks_selected=[
        "bgp_ebb_route_storm_playbook",
        "bgp_ebb_multipath_group_oscillation_playbook",
        "bgp_ebb_igp_pnh_metric_oscillation_playbook",
        "bgp_ebb_ebgp_session_oscillation_playbook",
    ],
    profile=_OPENR_STANDALONE,
    enable_update_group=True,
)

# CONVEYOR: dne_routing / bag013_stage1_node
BAG013_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG = create_bgp_ebb_full_scale_test_config(
    BAG013_ASH6,
    name="BAG013_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG",
    playbooks_selected=[
        "bgp_ebb_ebgp_route_oscillation_playbook",
        "bgp_ebb_ibgp_plane_session_oscillation_playbook",
        "bgp_ebb_igp_unresolvable_pnh_playbook",
        "bgp_ebb_nexthop_group_count_threshold_playbook",
    ],
    profile=_OPENR_STANDALONE,
    enable_update_group=False,
)

BAG013_STAGE1_FULL_SCALE_TEST_CONFIG_UG = create_bgp_ebb_full_scale_test_config(
    BAG013_ASH6,
    name="BAG013_STAGE1_FULL_SCALE_TEST_CONFIG_UG",
    playbooks_selected=[
        "bgp_ebb_ebgp_route_oscillation_playbook",
        "bgp_ebb_ibgp_plane_session_oscillation_playbook",
        "bgp_ebb_igp_unresolvable_pnh_playbook",
        "bgp_ebb_nexthop_group_count_threshold_playbook",
    ],
    profile=_OPENR_STANDALONE,
    enable_update_group=True,
)


# Retained scale-and-characteristic configs for later onboarding.
BAG011_QUEUE_MEMORY_MONITOR_TEST_CONFIG_UG = (
    create_bgp_ebb_queue_memory_monitor_test_config(
        BAG011_ASH6,
        enable_update_group=True,
        name_override="BAG011_QUEUE_MEMORY_MONITOR_TEST_CONFIG_UG",
        profile=_OPENR_STANDALONE,
    )
)

BAG012_UPDATE_PACKING_TEST_CONFIG_UG = create_bgp_ebb_update_packing_test_config(
    BAG012_ASH6,
    enable_update_group=True,
    name_override="BAG012_UPDATE_PACKING_TEST_CONFIG_UG",
    profile=_OPENR_STANDALONE,
)

BAG013_BOUNDED_ECMP_SETS_TEST_CONFIG_UG = (
    create_bgp_ebb_characteristic_bounded_ecmp_sets_test_config(
        BAG013_ASH6,
        enable_update_group=True,
        name_override="BAG013_BOUNDED_ECMP_SETS_TEST_CONFIG_UG",
        profile=_OPENR_STANDALONE,
    )
)


__all__ = [
    "BAG010_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG",
    "BAG010_STAGE1_FULL_SCALE_TEST_CONFIG_UG",
    "BAG011_QUEUE_MEMORY_MONITOR_TEST_CONFIG_UG",
    "BAG011_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG",
    "BAG011_STAGE1_FULL_SCALE_TEST_CONFIG_UG",
    "BAG012_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG",
    "BAG012_STAGE1_FULL_SCALE_TEST_CONFIG_UG",
    "BAG012_UPDATE_PACKING_TEST_CONFIG_UG",
    "BAG013_BOUNDED_ECMP_SETS_TEST_CONFIG_UG",
    "BAG013_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG",
    "BAG013_STAGE1_FULL_SCALE_TEST_CONFIG_UG",
]
