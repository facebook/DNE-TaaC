# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""TC31: FSDB final recovery — enable fsdb, then 5-min stable-state longevity.

Starts ``fsdb`` (systemctl start) on gtsw001 and then runs the FULL stable-state
hardening contract over a 5-minute longevity. This is the RECOVERY config meant to
run AFTER fpf_tc30 (which leaves fsdb stopped). Once fsdb is back, lane 0 of all 4
GPUs re-establishes, so the HRT CONNECTED FSDB-session census returns to 32 and the
entire fabric is back to stable state.

Two-playbook "longevity-anchored health check" structure (mirrors tc28/tc32) —
this is REQUIRED here: tc30 leaves fsdb DOWN, so when this config starts the
fabric is NOT yet in stable state. If the stable-state prechecks
(SYSTEMCTL_ACTIVE_STATE / BGP_SESSION_ESTABLISH) ran BEFORE the fsdb enable they
would false-fail (the hardware run failed exactly this way). Splitting into two
playbooks moves all prechecks AFTER the enable+settle:

  Playbook 1 (disruption-only, create_fpf_disruption_only_playbook): systemctl
    start fsdb on gtsw001 + a settle longevity. NO checks.

  Playbook 2 (stable-state longevity, create_fpf_hardening_playbook_v2, 5 min):
    the FULL stable-state hardening contract (HRT bulk/remote-failure/prod-prefix/
    plane-status no-churn, BGP RIB + FSDB ribMap converged, host-spray
    floor+fairness, generic device checks), PLUS the HRT session-stat check in
    STABLE mode asserting the census is back to 32 with no churn. The runner
    re-stamps test_case_start_time at THIS playbook's start, so every precheck and
    postcheck anchors at longevity start — AFTER the enable+settle.

ASSUMPTIONS:
  - This config is run after fpf_tc30 left fsdb down; if fsdb is already up, the
    enable step is a no-op and the stable contract still holds.
  - The settle window after the enable (Playbook 1) lets the 32nd session
    re-establish before Playbook 2's prechecks/assertions begin.

Headless run starts fsdb via SSH/systemctl — kick off from a Kerberos-ticketed
terminal.

Usage:
  buck2 run neteng/netcastle:netcastle_taac -- \\
    --team taac --test-config fpf_tc31_fsdb_enable_recover \\
    --dev --skip-basset-reservation --skip-testbed-isolation \\
    --debug --continue-on-precheck-failure --skip-fboss-rsyslog
"""

from taac.health_checks.healthcheck_definitions import (
    create_fpf_hrt_session_stat_check,
)
from taac.libs.fpf.fpf_prod_prefix_map import get_prefix
from taac.playbooks.playbook_definitions import (
    create_fpf_disruption_only_playbook,
    create_fpf_hardening_playbook_v2,
)
from taac.steps.step_definitions import (
    create_longevity_step,
    create_service_interruption_step,
)
from taac.task_definitions import (
    create_fpf_start_collectors_task,
    create_fpf_stop_collectors_task,
)
from taac.testconfigs.fpf.fpf_hardening_common import (
    ALLOW_BASELINE_FAILURES,
    create_fpf_endpoints,
    DEFAULT_COMMUNITY_LIST,
    DEFAULT_SUBNET_PREFIX,
    EXPECTED_FSDB_SESSION_COUNT,
    fpf_ib_traffic_tasks,
    FSDB_COLLECTOR_MODE,
    GPU_HOSTS,
    HRT_MEMORY_HOSTS,
    OBSERVER_GTSWS,
    skip_ssh_dependencies,
    SPRAY_HOSTS,
    TRIGGER_STSWS,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import TestConfig

PREFIX_COUNT = 1000
ENABLE_SETTLE_SEC = 120
LONGEVITY_SOAK_SEC = 300

DUT_GTSW = OBSERVER_GTSWS[0]

PROD_PREFIX_HOST = GPU_HOSTS[0]
PROD_PREFIX_DEVICE_ID = 0
PROD_PREFIXES = [get_prefix(PROD_PREFIX_HOST, PROD_PREFIX_DEVICE_ID)]


def create_fpf_tc31_test_config() -> TestConfig:
    skip_ssh = skip_ssh_dependencies()
    spray = None if skip_ssh else SPRAY_HOSTS
    ib_setup, ib_teardown = fpf_ib_traffic_tasks(skip_ssh)

    # --- Playbook 1: disruption-only — enable fsdb + settle, NO checks. ---
    disrupt_playbook = create_fpf_disruption_only_playbook(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        disruption_steps=[
            create_service_interruption_step(
                service=taac_types.Service.FSDB,
                trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_START,
                device_regexes=[DUT_GTSW],
                description=f"systemctl start fsdb on {DUT_GTSW} (recover)",
            ),
            create_longevity_step(
                duration=ENABLE_SETTLE_SEC,
                description=(
                    f"Settle {ENABLE_SETTLE_SEC}s after enabling fsdb; "
                    f"expect the 32nd session to re-establish"
                ),
            ),
        ],
        playbook_name="fpf_tc31_fsdb_enable_recover_disrupt",
    )

    # --- Playbook 2: full stable-state longevity (5 min). Prechecks now run
    # AFTER the enable+settle above. ---
    longevity_playbook = create_fpf_hardening_playbook_v2(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        soak_duration_sec=LONGEVITY_SOAK_SEC,
        stabilization_delay_sec=0,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        playbook_name="fpf_tc31_fsdb_enable_recover_longevity",
        prod_prefixes=PROD_PREFIXES,
        skip_ssh_dependent_checks=skip_ssh,
        # All 32 sessions must be back after the enable; assert as a single census
        # signal in STABLE mode (steady 32, no churn).
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        additional_postchecks=[
            create_fpf_hrt_session_stat_check(
                mode="stable",
                expected_connected=EXPECTED_FSDB_SESSION_COUNT,
                check_id="fpf_tc31_fsdb_enable_recover_session_stat",
            ),
        ],
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
    )

    return TestConfig(
        name="fpf_tc31_fsdb_enable_recover",
        endpoints=create_fpf_endpoints(),
        setup_tasks=[
            *ib_setup,
            create_fpf_start_collectors_task(
                gtsws=OBSERVER_GTSWS,
                hosts=GPU_HOSTS,
                subnet_prefix=DEFAULT_SUBNET_PREFIX,
                prod_prefixes=PROD_PREFIXES,
                prod_prefix_host=PROD_PREFIX_HOST,
                prod_prefix_device_id=PROD_PREFIX_DEVICE_ID,
                fsdb_mode=FSDB_COLLECTOR_MODE,
                allow_baseline_failures=ALLOW_BASELINE_FAILURES,
                enable_fsdb_session_collector=True,
                fsdb_session_host=GPU_HOSTS[0],
                fsdb_session_expected=EXPECTED_FSDB_SESSION_COUNT,
            ),
        ],
        teardown_tasks=[
            create_fpf_stop_collectors_task(
                trigger_stsws=TRIGGER_STSWS,
                prefix_count=PREFIX_COUNT,
                community_list=DEFAULT_COMMUNITY_LIST,
            ),
            *ib_teardown,
        ],
        # Strict order: disruption (enable+settle) first, then stable-state
        # longevity whose prechecks run AFTER recovery.
        playbooks=[disrupt_playbook, longevity_playbook],
        tags=["fpf"],
    )


TEST_CONFIG = create_fpf_tc31_test_config()
