# pyre-unsafe
"""
BGP DC Common Building Blocks
==============================

Domain-specific stage and health-check composition for BGP DC tests.

Step helpers (sequences, do_continuous_sequence helper, duration scalars) were
migrated to ``steps/step_definitions.py`` in Phase 7-B22. Stages and the
SKIP_BGPD_MAIN_CORE_DUMP_CHECK constant remain here as the BGP DC-specific
stage/HC composition layer.

HOW TO USE
----------
    from taac.routing.dc_routing.bgp_dc.common import (
        DISABLE_PREFIX_FLAPS_STAGE,
        DISABLE_SESSION_FLAPS_STAGE,
        BGP_RESTART_STAGE,
        SKIP_BGPD_MAIN_CORE_DUMP_CHECK,
    )

For step sequences and duration constants, import from step_definitions instead:
    from taac.steps.step_definitions import (
        ROGUE_PREFIX_SESSION_FLAP_STEPS,
        wait_time_after_disable_churn_s,
        do_continuous_sequence,
    )
"""

from taac.health_checks.healthcheck_definitions import (
    create_device_core_dumps_check,
)
from taac.routing.dc_routing.bgp_dc.shared_constants import (
    AGENT_RESTART_STEPS,
    BGP_RESTART_STEPS,
)
from taac.stages.stage_definitions import (
    create_attribute_churn_stage,
    create_steps_stage,
)
from taac.steps.step_definitions import (
    bgp_restart_count,
    create_toggle_ixia_prefix_session_flap_churn_step,
    duration_frequent_best_path_computation_s,
    local_pref_churn_interval_s,
    wait_time_after_disable_churn_s,
)


# =============================================================================
# Shared Stages
# =============================================================================
# Pre-built Stage objects used across multiple BGP DC playbooks.

# Stage that churns local preference on all prefix pools to trigger
# frequent best-path recomputation on the DUT.
FREQUENT_BEST_PATH_COMPUTATION_STAGE = create_attribute_churn_stage(
    prefix_pool_regex=".*",
    prefix_pool_regex_as_path=".*",
    prefix_start_index=0,
    churn_time=local_pref_churn_interval_s,
    local_pref_iters=duration_frequent_best_path_computation_s
    // local_pref_churn_interval_s,
    med_iters=0,
    origin_iters=0,
    as_path_iters=0,
)

# Stage that restarts BGP bgp_restart_count times.
BGP_RESTART_STAGE = create_steps_stage(
    iteration=bgp_restart_count,
    steps=BGP_RESTART_STEPS,
)

# Stage that restarts the wedge_agent bgp_restart_count times.
AGENT_RESTART_STAGE = create_steps_stage(
    iteration=bgp_restart_count,
    steps=AGENT_RESTART_STEPS,
)

# Stage that disables ALL session flaps (used before prefix-only tests
# to ensure session churn doesn't interfere).
DISABLE_SESSION_FLAPS_STAGE = create_steps_stage(
    steps=[
        create_toggle_ixia_prefix_session_flap_churn_step(
            churn_mode="session_flap",
            enable_session_flap=False,
            is_all_session_groups=True,
            churn_duration_s=wait_time_after_disable_churn_s,
        ),
    ]
)

# Stage that disables ALL prefix flaps (used before session-only tests
# to ensure prefix churn doesn't interfere).
DISABLE_PREFIX_FLAPS_STAGE = create_steps_stage(
    steps=[
        create_toggle_ixia_prefix_session_flap_churn_step(
            churn_mode="prefix_flap",
            enable_prefix_flap=False,
            is_all_prefix_groups=True,
            churn_duration_s=wait_time_after_disable_churn_s,
        ),
    ]
)


# =============================================================================
# Shared Health Checks
# =============================================================================

# Health check that skips bgpd_main core dump detection.
# Use this when bgpd_main core dumps are expected (e.g., after force-kill tests).
SKIP_BGPD_MAIN_CORE_DUMP_CHECK = create_device_core_dumps_check(
    core_dumps_to_ignore=["bgpd_main"],
)
