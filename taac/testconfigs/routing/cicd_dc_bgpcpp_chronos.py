# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""BGP-DC chronos_node CICD lifecycle bindings (Wave 3B).

Sole source of the four BGP-DC chronos_node bindings scheduled on the
CICD conveyor. Each binding calls
:func:`create_bgp_dc_chronos_node_test_config` with the target physical_inventory +
per-binding overrides (playbook selection, framework-validation scale
reductions). The internal ``TestConfig.name`` string on every binding is
preserved verbatim from the pre-Wave-3B source so the golden manifest
stays byte-identical.

External consumers under ``testconfigs/fboss_solution_tests/chronos_node_*``
re-export the module-level constants defined here.
"""

from __future__ import annotations

from taac.abstractions.physical_inventory import (
    FSW_FUJI_QZD1,
    SSW_ELBERT_QZD1,
)
from taac.testconfigs.routing.factories.bgp_dc_chronos_node import (
    create_bgp_dc_chronos_node_test_config,
)


# ─── CHRONOS_NODE_FSW_FUJI ────────────────────────────────────────────────
# Runs 11 playbooks against the Fuji FSW (2× longevity vs restart mix).
CHRONOS_NODE_FSW_FUJI_TEST_CONFIG = create_bgp_dc_chronos_node_test_config(
    FSW_FUJI_QZD1,
    name="CHRONOS_NODE_FSW_FUJI",
    playbooks_selected=[
        "test_agent_restart",
        "test_bgp_restart",
        "test_longevity_prefix_flap_all_prefixes",
        "test_longevity_activate_deactivate_all_prefixes",
        "test_longevity_session_flap_all_prefixes",
        "test_longevity_prefix_flap_all_prefixes_plus_bgp_restart",
        "test_longevity_session_flap_all_prefixes_plus_bgp_restart",
        "test_longevity_rogue_prefix_session_enable",
        "test_longevity_no_prefix_no_session_flap",
        "test_longevity_continuous_toggle_device_group",
        "test_longevity_frequent_best_path_computation",
    ],
)

# ─── CHRONOS_NODE_FULL_SCALE_SSW_ELBERT_QZD1 ──────────────────────────────
# Full-scale longevity mix on the Elbert SSW.
CHRONOS_NODE_FULL_SCALE_SSW_ELBERT_QZD1_TEST_CONFIG = (
    create_bgp_dc_chronos_node_test_config(
        SSW_ELBERT_QZD1,
        name="CHRONOS_NODE_FULL_SCALE_SSW_ELBERT_QZD1",
        playbooks_selected=[
            "test_longevity_prefix_flap_all_prefixes",
            "test_longevity_activate_deactivate_all_prefixes",
            "test_longevity_session_flap_all_prefixes",
            "test_longevity_prefix_flap_all_prefixes_plus_bgp_restart",
            "test_longevity_session_flap_all_prefixes_plus_bgp_restart",
            "test_longevity_rogue_prefix_session_enable",
            "test_longevity_no_prefix_no_session_flap",
            "test_longevity_continuous_toggle_device_group",
        ],
    )
)

# ─── CHRONOS_NODE_FULL_SCALE_SSW_ELBERT_RESTART_QZD1 ──────────────────────
# Elbert SSW restart-only sibling — same topology as the QZD1 variant above.
CHRONOS_NODE_FULL_SCALE_SSW_ELBERT_RESTART_QZD1_TEST_CONFIG = (
    create_bgp_dc_chronos_node_test_config(
        SSW_ELBERT_QZD1,
        name="CHRONOS_NODE_FULL_SCALE_SSW_ELBERT_RESTART_QZD1",
        playbooks_selected=["test_agent_restart", "test_bgp_restart"],
    )
)

# ─── CHRONOS_NODE_FRAMEWORK_VALIDATION_AGENT_RESTART_QZD1 ────────────────
# Fast framework-validation smoke test. NOT an FBOSS product test — same
# stack as the full-scale QZD1 config above, drastically reduced scale
# so it completes fast. The ``ecmp_group_limit`` * 2 == ``ecmp_member_limit``
# invariant (see notes in the pre-Wave-3B source) is preserved verbatim.
CHRONOS_NODE_FRAMEWORK_VALIDATION_AGENT_RESTART_QZD1_TEST_CONFIG = (
    create_bgp_dc_chronos_node_test_config(
        SSW_ELBERT_QZD1,
        name="CHRONOS_NODE_FRAMEWORK_VALIDATION_AGENT_RESTART_QZD1",
        # Reduced scale (load-bearing for the agent-restart run)
        prefix_limit="5000",
        per_peer_max_route_limit="2000",
        downlink_peer_count=2,
        uplink_peer_count=2,
        rogue_peer_count=2,
        ixia_downlink_prefix_count_v6=50,
        ixia_uplink_prefix_count_v6=50,
        ixia_rogue_prefix_count_v6=50,
        ixia_downlink_prefix_count_v4=50,
        ixia_uplink_prefix_count_v4=50,
        ixia_rogue_prefix_count_v4=50,
        # Reduced platform entry / ecmp counts
        ecmp_group_limit=10,
        ecmp_member_limit=20,
        good_ndp_entries_uplink=10,
        good_ndp_entries_downlink=10,
        rogue_ndp_entries=20,
        good_arp_entries=10,
        rogue_arp_entries=20,
        good_mac_entry_count=10,
        rogue_mac_entry_count=20,
        bgp_induced_ecmp_group_count=5,
        # Single quick playbook + fast-convergence + one-shot restart
        playbooks_selected=["test_agent_restart"],
        wedge_agent_restart_no_of_interations=1,
        convergence_wait_timeout=120,
        convergence_wait_interval=5,
    )
)


__all__ = [
    "CHRONOS_NODE_FRAMEWORK_VALIDATION_AGENT_RESTART_QZD1_TEST_CONFIG",
    "CHRONOS_NODE_FSW_FUJI_TEST_CONFIG",
    "CHRONOS_NODE_FULL_SCALE_SSW_ELBERT_QZD1_TEST_CONFIG",
    "CHRONOS_NODE_FULL_SCALE_SSW_ELBERT_RESTART_QZD1_TEST_CONFIG",
]
