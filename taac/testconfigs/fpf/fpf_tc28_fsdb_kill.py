# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""TC28: Kill FSDB on the DUT GTSW (FSDB unclean exit).

Repeatedly SIGKILLs ``fsdb`` on gtsw001 (every 1s for 60s) so the daemon never
exits gracefully, then settles 2 minutes, then runs a 5-minute stable-state
longevity. fsdb owns lane 0 (gtsw001 -> lane 0), so killing it drops lane 0 of
all 4 GPUs -> the overall HRT CONNECTED FSDB-session census dips 32 -> 28 during
the kill window and must recover to 32 and hold afterwards.

Two-playbook "longevity-anchored health check" structure:

  Playbook 1 (disruption-only): inject test prefixes, stabilize, record the
    disruption moment, repeatedly crash fsdb (1s x 60s) on gtsw001, then a 2-min
    stable longevity. Its single POSTCHECK is the HRT session-stat check in
    disruption mode (32 -> 28 on lane 0 -> recover to 32, hold >= 60s). The
    check anchors via lookback (900s) which spans kill-start -> now.

  Playbook 2 (stable-state longevity, 5 min): the FULL stable-state hardening
    contract (create_fpf_hardening_playbook_v2). The TaacRunner re-stamps
    test_case_start_time at THIS playbook's start, so every HC in it anchors at
    longevity start (the disruption window is excluded) and asserts the recovered
    steady state, including the session-stat check in STABLE mode (32, no churn).

ASSUMPTIONS:
  - lookback_sec=900 on the disruption-mode session-stat postcheck is wide enough
    to cover the inject+stabilize wait, the 60s kill window, AND the 2-min stable
    longevity that follows it within Playbook 1. The check's window is anchored at
    Playbook-1 test_case_start_time and bounded by lookback; 900s comfortably
    covers a ~stabilization(120) + kill(60) + stable(120) sequence.
  - All OTHER health checks are stable-state, anchored at the longevity (Playbook
    2) start by the runner's per-playbook test_case_start_time re-stamp.

Headless run kills fsdb via the driver crash path — kick off from a
Kerberos-ticketed terminal.

Usage:
  buck2 run neteng/netcastle:netcastle_taac -- \\
    --team taac --test-config fpf_tc28_fsdb_kill \\
    --dev --skip-basset-reservation --skip-testbed-isolation \\
    --debug --continue-on-precheck-failure --skip-fboss-rsyslog
"""

from taac.health_checks.healthcheck_definitions import (
    create_fpf_hrt_session_stat_check,
)
from taac.libs.fpf.fpf_prod_prefix_map import get_prefix
from taac.playbooks.playbook_definitions import (
    create_fpf_disrupt_window_playbook,
    create_fpf_hardening_playbook_v2,
)
from taac.steps.step_definitions import (
    create_fpf_record_disruption_time_step,
    create_fpf_repeated_service_crash_step,
    create_longevity_step,
)
from taac.task_definitions import (
    create_fpf_inject_vf_groups_task,
    create_fpf_restart_service_task,
    create_fpf_start_collectors_task,
    create_fpf_stop_collectors_task,
    create_fpf_withdraw_vf_groups_task,
)
from taac.testconfigs.fpf.fpf_hardening_common import (
    ALL_LANES,
    ALL_STSWS,
    ALLOW_BASELINE_FAILURES,
    create_fpf_endpoints,
    DEFAULT_COMMUNITY_LIST,
    EXPECTED_FSDB_SESSION_COUNT,
    fpf_ib_traffic_tasks,
    fpf_rf_vf_groups,
    fpf_vf_injection_groups,
    FSDB_COLLECTOR_MODE,
    GPU_HOSTS,
    HRT_MEMORY_HOSTS,
    OBSERVER_GTSWS,
    skip_ssh_dependencies,
    SPRAY_HOSTS,
    TRIGGER_STSWS,
    VF_COLLECTOR_SUBNET,
    VF_GROUP_PREFIX_COUNT,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import TestConfig

# 8-plane VF-group injection (VF1 5000:dd on s001-s004 = planes 0-3, VF2 5000:ee
# on s005-s008 = planes 4-7); injected once by the setup task, withdrawn in
# teardown, so the longevity playbook passes skip_injection=True.
INJECTION_GROUPS = fpf_vf_injection_groups()
RF_VF_GROUPS = fpf_rf_vf_groups()
INJECTED_LANES = ALL_LANES
PREFIX_COUNT = VF_GROUP_PREFIX_COUNT
INJECT_SETTLE_SEC = 300
STABILIZATION_DELAY_SEC = 120
KILL_EVERY_SEC = 1
KILL_DURATION_SEC = 60
STABLE_AFTER_KILL_SEC = 120
LONGEVITY_SOAK_SEC = 300
SESSION_LOOKBACK_SEC = 900
RECOVERY_MIN_SEC = 60

# fsdb on gtsw001 owns lane 0; killing it impacts lane 0 of all 4 GPUs -> 32-4=28.
DUT_GTSW = OBSERVER_GTSWS[0]
IMPACTED_LANES = [0]
CONNECTED_DURING = EXPECTED_FSDB_SESSION_COUNT - 4  # 28

PROD_PREFIX_HOST = GPU_HOSTS[0]
PROD_PREFIX_DEVICE_ID = 0
PROD_PREFIXES = [get_prefix(PROD_PREFIX_HOST, PROD_PREFIX_DEVICE_ID)]


def create_fpf_tc28_test_config() -> TestConfig:
    skip_ssh = skip_ssh_dependencies()
    spray = None if skip_ssh else SPRAY_HOSTS
    ib_setup, ib_teardown = fpf_ib_traffic_tasks(skip_ssh)

    # --- Playbook 1: disruption-only with a single session-stat postcheck. ---
    # Prefixes are injected once by the setup task (8-plane VF groups), so the
    # disrupt window only stabilizes/records/kills/settles.
    disrupt_steps = [
        create_longevity_step(
            duration=STABILIZATION_DELAY_SEC,
            description=f"Stabilize {STABILIZATION_DELAY_SEC}s before the FSDB kill",
        ),
        create_fpf_record_disruption_time_step(
            description="Record FSDB-kill disruption time"
        ),
        create_fpf_repeated_service_crash_step(
            service=taac_types.Service.FSDB,
            every_sec=KILL_EVERY_SEC,
            duration_sec=KILL_DURATION_SEC,
            device_regexes=[DUT_GTSW],
            description=(
                f"SIGKILL fsdb every {KILL_EVERY_SEC}s for {KILL_DURATION_SEC}s "
                f"on {DUT_GTSW} (unclean exit)"
            ),
        ),
        create_longevity_step(
            duration=STABLE_AFTER_KILL_SEC,
            description=f"Stable {STABLE_AFTER_KILL_SEC}s after the FSDB kill stops",
        ),
    ]
    disrupt_playbook = create_fpf_disrupt_window_playbook(
        playbook_name="fpf_tc28_fsdb_kill_disrupt",
        disruption_steps=disrupt_steps,
        spray_hosts=spray,
        postchecks=[
            create_fpf_hrt_session_stat_check(
                mode="disruption",
                only_hosts=[GPU_HOSTS[0]],
                expected_connected=EXPECTED_FSDB_SESSION_COUNT,
                expected_connected_during=CONNECTED_DURING,
                impacted_lanes=IMPACTED_LANES,
                recovery_min_sec=RECOVERY_MIN_SEC,
                lookback_sec=SESSION_LOOKBACK_SEC,
                check_id="fpf_tc28_fsdb_kill_session_stat",
            ),
        ],
    )

    # --- Playbook 2: full stable-state longevity (5 min). ---
    longevity_playbook = create_fpf_hardening_playbook_v2(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        soak_duration_sec=LONGEVITY_SOAK_SEC,
        stabilization_delay_sec=0,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        playbook_name="fpf_tc28_fsdb_kill_longevity",
        prod_prefixes=PROD_PREFIXES,
        skip_ssh_dependent_checks=skip_ssh,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        # 8-plane: prefixes injected once by the setup task; check all 8 lanes.
        skip_injection=True,
        rf_vf_groups=RF_VF_GROUPS,
        lanes=INJECTED_LANES,
        # fsdb kill is DISRUPTIVE: metrics blip mid-window during the kill and
        # reconverge by end. MODE A (last_sample) asserts only the last in-window
        # sample holds the golden value.
        convergence_blip_mode="last_sample",
        # Expected mid-disruption STSW packet loss to purged lane-0 dests —
        # informational, not a hard fail (user-confirmed).
        ods_discard_informational=True,
    )

    return TestConfig(
        name="fpf_tc28_fsdb_kill",
        endpoints=create_fpf_endpoints(stsws=ALL_STSWS),
        setup_tasks=[
            *ib_setup,
            create_fpf_start_collectors_task(
                gtsws=OBSERVER_GTSWS,
                hosts=GPU_HOSTS,
                subnet_prefix=VF_COLLECTOR_SUBNET,
                prod_prefixes=PROD_PREFIXES,
                prod_prefix_host=PROD_PREFIX_HOST,
                prod_prefix_device_id=PROD_PREFIX_DEVICE_ID,
                fsdb_mode=FSDB_COLLECTOR_MODE,
                allow_baseline_failures=ALLOW_BASELINE_FAILURES,
                enable_fsdb_session_collector=True,
                fsdb_session_hosts=GPU_HOSTS,
                fsdb_session_expected=EXPECTED_FSDB_SESSION_COUNT,
                rf_vf_groups=RF_VF_GROUPS,
            ),
            create_fpf_inject_vf_groups_task(
                groups=INJECTION_GROUPS,
                settle_sec=INJECT_SETTLE_SEC,
            ),
        ],
        teardown_tasks=[
            create_fpf_withdraw_vf_groups_task(groups=INJECTION_GROUPS),
            create_fpf_restart_service_task(devices=ALL_STSWS, service="BGP"),
            create_fpf_stop_collectors_task(
                trigger_stsws=TRIGGER_STSWS,
                withdraw=False,
                community_list=DEFAULT_COMMUNITY_LIST,
            ),
            *ib_teardown,
        ],
        # Strict order: disruption first, then stable-state longevity.
        playbooks=[disrupt_playbook, longevity_playbook],
        tags=["fpf"],
    )


TEST_CONFIG = create_fpf_tc28_test_config()
