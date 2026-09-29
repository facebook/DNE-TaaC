# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""EBB CICD lifecycle bindings scheduled on the ``dne_routing`` conveyor.

The lifecycle layout schedules full-scale coverage plus a first promotion-gating
wave of one scale-and-characteristic case per scheduled device. Stage 1
partitions the retained Non-UG Playbooks into four runtime-balanced groups. The
former BAG010 through BAG013 logical tracks run on NRQEB006 through NRQEB009
with matching TestConfig and Conveyor identities while preserving every
Playbook list. Catalog governance lives in
``fbcode/neteng/test_infra/routing_qualification/catalogs/taac/bgp_ebb_catalog.yaml``.
"""

from taac.abstractions.physical_inventory import (
    BAG011_ASH6,
    BAG012_ASH6,
    BAG013_ASH6,
    NRQEB006_ASH6,
    NRQEB007_ASH6,
    NRQEB008_ASH6,
    NRQEB009_ASH6,
)
from taac.abstractions.topologies.bounded_ecmp import (
    BOUNDED_ECMP_PARENT_NETWORKS_IXIA03,
)
from taac.abstractions.topologies.ebb_full_scale import (
    EBB_NEXT_HOPS_IXIA03,
    EBB_PARENT_NETWORKS_IXIA03,
)
from taac.abstractions.topologies.egress_peer_scale import (
    EGRESS_PEER_SCALE_PARENT_NETWORKS_IXIA03,
)
from taac.abstractions.topologies.ipv6_update_packing import (
    IPV6_UPDATE_PACKING_PARENT_NETWORKS_IXIA03,
)
from taac.constants import BgpPlusPlusProfile
from taac.testconfigs.routing.factories.bgp_ebb_characteristic import (
    create_bgp_ebb_characteristic_bounded_ecmp_sc9_test_config,
    create_bgp_ebb_characteristic_bounded_ecmp_sets_test_config,
    create_bgp_ebb_characteristic_constant_attribute_storage_ingress_test_config,
    create_bgp_ebb_characteristic_performance_scaling_test_config,
    create_bgp_ebb_characteristic_transient_memory_route_scale_test_config,
    create_bgp_ebb_queue_memory_monitor_test_config,
    create_bgp_ebb_update_packing_test_config,
)
from taac.testconfigs.routing.factories.bgp_ebb_full_scale import (
    create_bgp_ebb_full_scale_test_config,
)


_OPENR_STANDALONE = BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R

# Stage 1: retain only the reviewed Non-UG cases selected for daily execution.
# Each config lists its playbooks inline so what a Conveyor node runs is
# readable at the node, without resolving a shared constant. The promotion-
# gating UG configs remain unchanged; a rebalanced Non-UG case can therefore
# have its UG coverage on a different scheduled device.
# CONVEYOR: dne_routing / nrqeb006_stage1_node
NRQEB006_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG = create_bgp_ebb_full_scale_test_config(
    NRQEB006_ASH6,
    name="NRQEB006_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG",
    playbooks_selected=[
        "bgp_ebb_route_registry_runtime_update_playbook",
        "bgp_ebb_daemon_restart_playbook",
    ],
    profile=_OPENR_STANDALONE,
    enable_update_group=False,
    parent_networks=EBB_PARENT_NETWORKS_IXIA03,
    next_hops=EBB_NEXT_HOPS_IXIA03,
)

NRQEB006_STAGE1_FULL_SCALE_TEST_CONFIG_UG = create_bgp_ebb_full_scale_test_config(
    NRQEB006_ASH6,
    name="NRQEB006_STAGE1_FULL_SCALE_TEST_CONFIG_UG",
    playbooks_selected=[
        "bgp_ebb_route_registry_runtime_update_playbook",
        "bgp_ebb_daemon_restart_playbook",
        "bgp_ebb_cold_start_playbook",
        "bgp_ebb_longevity_playbook",
    ],
    profile=_OPENR_STANDALONE,
    enable_update_group=True,
    parent_networks=EBB_PARENT_NETWORKS_IXIA03,
    next_hops=EBB_NEXT_HOPS_IXIA03,
)

# CONVEYOR: dne_routing / nrqeb007_stage1_node
# Reviewed overlapping or calibrating cases are omitted here while the UG
# config below retains them.
NRQEB007_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG = create_bgp_ebb_full_scale_test_config(
    NRQEB007_ASH6,
    name="NRQEB007_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG",
    playbooks_selected=[
        "bgp_ebb_attribute_churn_playbook",
        "bgp_ebb_fauu_drain_undrain_playbook",
    ],
    profile=_OPENR_STANDALONE,
    enable_update_group=False,
    parent_networks=EBB_PARENT_NETWORKS_IXIA03,
    next_hops=EBB_NEXT_HOPS_IXIA03,
)

NRQEB007_STAGE1_FULL_SCALE_TEST_CONFIG_UG = create_bgp_ebb_full_scale_test_config(
    NRQEB007_ASH6,
    name="NRQEB007_STAGE1_FULL_SCALE_TEST_CONFIG_UG",
    playbooks_selected=[
        "bgp_ebb_attribute_churn_playbook",
        "bgp_ebb_fauu_drain_undrain_playbook",
        "bgp_ebb_plane_drain_undrain_playbook",
        "bgp_ebb_ibgp_route_oscillation_playbook",
    ],
    profile=_OPENR_STANDALONE,
    enable_update_group=True,
    parent_networks=EBB_PARENT_NETWORKS_IXIA03,
    next_hops=EBB_NEXT_HOPS_IXIA03,
)

# CONVEYOR: dne_routing / nrqeb008_stage1_node
NRQEB008_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG = create_bgp_ebb_full_scale_test_config(
    NRQEB008_ASH6,
    name="NRQEB008_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG",
    playbooks_selected=[
        "bgp_ebb_ebgp_session_oscillation_playbook",
        "bgp_ebb_cold_start_playbook",
    ],
    profile=_OPENR_STANDALONE,
    enable_update_group=False,
    parent_networks=EBB_PARENT_NETWORKS_IXIA03,
    next_hops=EBB_NEXT_HOPS_IXIA03,
)

NRQEB008_STAGE1_FULL_SCALE_TEST_CONFIG_UG = create_bgp_ebb_full_scale_test_config(
    NRQEB008_ASH6,
    name="NRQEB008_STAGE1_FULL_SCALE_TEST_CONFIG_UG",
    playbooks_selected=[
        "bgp_ebb_route_storm_playbook",
        "bgp_ebb_multipath_group_oscillation_playbook",
        "bgp_ebb_igp_pnh_metric_oscillation_playbook",
        "bgp_ebb_ebgp_session_oscillation_playbook",
    ],
    profile=_OPENR_STANDALONE,
    enable_update_group=True,
    parent_networks=EBB_PARENT_NETWORKS_IXIA03,
    next_hops=EBB_NEXT_HOPS_IXIA03,
)

# CONVEYOR: dne_routing / nrqeb009_stage1_node
NRQEB009_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG = create_bgp_ebb_full_scale_test_config(
    NRQEB009_ASH6,
    name="NRQEB009_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG",
    playbooks_selected=[
        "bgp_ebb_ebgp_route_oscillation_playbook",
        "bgp_ebb_igp_unresolvable_pnh_playbook",
    ],
    profile=_OPENR_STANDALONE,
    enable_update_group=False,
    parent_networks=EBB_PARENT_NETWORKS_IXIA03,
    next_hops=EBB_NEXT_HOPS_IXIA03,
)

NRQEB009_STAGE1_FULL_SCALE_TEST_CONFIG_UG = create_bgp_ebb_full_scale_test_config(
    NRQEB009_ASH6,
    name="NRQEB009_STAGE1_FULL_SCALE_TEST_CONFIG_UG",
    playbooks_selected=[
        "bgp_ebb_ebgp_route_oscillation_playbook",
        "bgp_ebb_ibgp_plane_session_oscillation_playbook",
        "bgp_ebb_igp_unresolvable_pnh_playbook",
        "bgp_ebb_nexthop_group_count_threshold_playbook",
    ],
    profile=_OPENR_STANDALONE,
    enable_update_group=True,
    parent_networks=EBB_PARENT_NETWORKS_IXIA03,
    next_hops=EBB_NEXT_HOPS_IXIA03,
)


# First characteristic promotion-gating wave: one node per scheduled device.
# These TestConfigs intentionally use runtime selectors that do not encode the
# inventory's site suffix.
# CONVEYOR: dne_routing / nrqeb006_characteristics_wave1_node
NRQEB006_SC2_CONSTANT_ATTRIBUTE_STORAGE_INGRESS_TEST_CONFIG_UG = (
    create_bgp_ebb_characteristic_constant_attribute_storage_ingress_test_config(
        NRQEB006_ASH6,
        enable_update_group=True,
        name_override="NRQEB006_SC2_CONSTANT_ATTRIBUTE_STORAGE_INGRESS_TEST_CONFIG_UG",
        include_direct_ixia_connections=True,
    )
)

# CONVEYOR: dne_routing / nrqeb007_characteristics_wave1_node
NRQEB007_SC3_TRANSIENT_MEMORY_ROUTE_SCALE_TEST_CONFIG_UG = (
    create_bgp_ebb_characteristic_transient_memory_route_scale_test_config(
        NRQEB007_ASH6,
        enable_update_group=True,
        name_override="NRQEB007_SC3_TRANSIENT_MEMORY_ROUTE_SCALE_TEST_CONFIG_UG",
        parent_networks=EGRESS_PEER_SCALE_PARENT_NETWORKS_IXIA03,
        include_direct_ixia_connections=True,
    )
)

# CONVEYOR: dne_routing / nrqeb008_characteristics_wave1_node
NRQEB008_SC1_EGRESS_PEER_SCALE_TEST_CONFIG_UG = (
    create_bgp_ebb_characteristic_performance_scaling_test_config(
        NRQEB008_ASH6,
        enable_update_group=True,
        name_override="NRQEB008_SC1_EGRESS_PEER_SCALE_TEST_CONFIG_UG",
        parent_networks=EGRESS_PEER_SCALE_PARENT_NETWORKS_IXIA03,
    )
)

# CONVEYOR: dne_routing / nrqeb009_characteristics_wave1_node
NRQEB009_SC9_BOUNDED_ECMP_SETS_TEST_CONFIG_UG = (
    create_bgp_ebb_characteristic_bounded_ecmp_sc9_test_config(
        NRQEB009_ASH6,
        enable_update_group=True,
        name_override="NRQEB009_SC9_BOUNDED_ECMP_SETS_TEST_CONFIG_UG",
        parent_networks=BOUNDED_ECMP_PARENT_NETWORKS_IXIA03,
    )
)

# Second characteristic promotion-gating wave. EBB-21 has its own logical
# topology and TestConfig so Conveyor can schedule it independently after the
# NRQEB008 Wave 1 node. The no-OpenR profile keeps this binding on one device;
# directly connected IXIA next hops are resolved from interface state.
# CONVEYOR: dne_routing / nrqeb008_characteristics_wave2_node
NRQEB008_SC5_UPDATE_PACKING_TEST_CONFIG_UG = create_bgp_ebb_update_packing_test_config(
    NRQEB008_ASH6,
    enable_update_group=True,
    name_override="NRQEB008_SC5_UPDATE_PACKING_TEST_CONFIG_UG",
    profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
    min_advertised_nlri=50000,
    parent_networks=IPV6_UPDATE_PACKING_PARENT_NETWORKS_IXIA03,
)


# Legacy retained scale-and-characteristic selectors. They stay registered for
# compatibility but are not the first-wave Conveyor bindings above.
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
    "BAG011_QUEUE_MEMORY_MONITOR_TEST_CONFIG_UG",
    "NRQEB007_SC3_TRANSIENT_MEMORY_ROUTE_SCALE_TEST_CONFIG_UG",
    "NRQEB007_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG",
    "NRQEB007_STAGE1_FULL_SCALE_TEST_CONFIG_UG",
    "NRQEB008_SC1_EGRESS_PEER_SCALE_TEST_CONFIG_UG",
    "NRQEB008_SC5_UPDATE_PACKING_TEST_CONFIG_UG",
    "NRQEB008_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG",
    "NRQEB008_STAGE1_FULL_SCALE_TEST_CONFIG_UG",
    "BAG012_UPDATE_PACKING_TEST_CONFIG_UG",
    "BAG013_BOUNDED_ECMP_SETS_TEST_CONFIG_UG",
    "NRQEB009_SC9_BOUNDED_ECMP_SETS_TEST_CONFIG_UG",
    "NRQEB009_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG",
    "NRQEB009_STAGE1_FULL_SCALE_TEST_CONFIG_UG",
    "NRQEB006_SC2_CONSTANT_ATTRIBUTE_STORAGE_INGRESS_TEST_CONFIG_UG",
    "NRQEB006_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG",
    "NRQEB006_STAGE1_FULL_SCALE_TEST_CONFIG_UG",
]
