# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""TC30: FSDB GR timer beyond window — stop fsdb 180s, do NOT re-enable.

Stops ``fsdb`` (systemctl stop) on gtsw001 and holds it stopped for 180s — beyond
the FSDB graceful-restart grace window — and never starts it back. fsdb owns lane
0 (gtsw001 -> lane 0), so past GR expiry lane 0 of all 4 GPUs stays withdrawn and
the impaired steady state persists, exactly like an interface disable that is left
down (compare to the fpf_tc15 interface-disable DISRUPT playbook): bulk/fsdb on
lane 0 withdrawn, remote-failure shows the impacted lane, and the HRT CONNECTED
FSDB-session census settles at 28 (32 - 4) and STAYS there with no recovery.

This config is meant to run BEFORE fpf_tc31 (which re-enables fsdb and validates
recovery). It deliberately leaves fsdb DOWN.

Structure & the "stays at 28, no recovery" mapping (READ — this is a deliberate
deviation from a naive single-playbook session-stat check):

  The session-stat check's "disruption" mode ALWAYS evaluates Signal 2 (the count
  must RECOVER to expected_connected and hold for recovery_min_sec). There is no
  knob to disable Signal 2 — even recovery_min_sec=0 still requires the census to
  reach expected_connected (32). Since tc30 never re-enables fsdb, the census never
  returns to 32, so a disruption-mode check would always FAIL on Signal 2. That is
  NOT the contract we want to assert here ("stays at 28").

  The faithful mapping the check actually supports is mode="stable" with
  expected_connected=28: it asserts min==max==28 across the window with NO recovery
  requirement — i.e. the impaired census holds steady at 28. To anchor that window
  AFTER the stop (so the pre-stop 32 samples are excluded), the config uses TWO
  playbooks: a disruption-only playbook (inject/stabilize/stop/180s, NO checks)
  followed by a minimal "stays-down" assertion playbook. The TaacRunner re-stamps
  test_case_start_time at the start of the SECOND playbook, so its stable-mode
  session-stat check (expected_connected=28) anchors at the post-stop window and
  validates "settled at 28, stays at 28" — the no-recovery contract.

  There is no stable-state hardening longevity here: fsdb is intentionally left
  down, so the FULL stable contract (which expects 32) does not apply.

ASSUMPTIONS:
  - mode="stable" + expected_connected=28 is the supported "stays at 28, no
    recovery" mapping (disruption mode cannot express "no recovery"; see above).
  - The 180s hold exceeds the FSDB GR window (~120s), so lane 0 is fully withdrawn
    (purged) by the time the second playbook's window opens; the impaired census is
    a clean steady 28.
  - lookback_sec on the stays-down check anchors at the second playbook's
    test_case_start_time and covers its short assertion longevity.

Headless run stops fsdb via SSH/systemctl — kick off from a Kerberos-ticketed
terminal.

Usage:
  buck2 run neteng/netcastle:netcastle_taac -- \\
    --team taac --test-config fpf_tc30_fsdb_gr_stop180_no_reenable \\
    --dev --skip-basset-reservation --skip-testbed-isolation \\
    --debug --continue-on-precheck-failure --skip-fboss-rsyslog
"""

from taac.health_checks.healthcheck_definitions import (
    create_fpf_hrt_session_stat_check,
)
from taac.libs.fpf.fpf_prod_prefix_map import get_prefix
from taac.playbooks.playbook_definitions import (
    create_fpf_disruption_only_playbook,
    create_fpf_stays_down_assertion_playbook,
)
from taac.steps.step_definitions import (
    create_fpf_bgp_prefix_injection_step,
    create_fpf_record_disruption_time_step,
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
    OBSERVER_GTSWS,
    skip_ssh_dependencies,
    TRIGGER_STSWS,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import TestConfig

PREFIX_COUNT = 1000
STABILIZATION_DELAY_SEC = 120
STOP_DURATION_SEC = 180  # > GR window (~120s): routes purged, stays down.
STAYS_DOWN_ASSERT_SEC = 120  # short longevity for the stable "stays at 28" window.
SESSION_LOOKBACK_SEC = 900

DUT_GTSW = OBSERVER_GTSWS[0]
IMPACTED_LANES = [0]
# Steady impaired census after GR expiry on lane 0 of all 4 GPUs: 32 - 4 = 28.
CONNECTED_STAYS_AT = EXPECTED_FSDB_SESSION_COUNT - 4  # 28

PROD_PREFIX_HOST = GPU_HOSTS[0]
PROD_PREFIX_DEVICE_ID = 0
PROD_PREFIXES = [get_prefix(PROD_PREFIX_HOST, PROD_PREFIX_DEVICE_ID)]


def create_fpf_tc30_test_config() -> TestConfig:
    skip_ssh = skip_ssh_dependencies()
    ib_setup, ib_teardown = fpf_ib_traffic_tasks(skip_ssh)

    # --- Playbook 1: disruption-only (inject/stabilize/stop/hold), NO checks. ---
    disrupt_steps = [
        create_fpf_bgp_prefix_injection_step(
            devices=TRIGGER_STSWS,
            count=PREFIX_COUNT,
            community_list=DEFAULT_COMMUNITY_LIST,
            description=f"Inject {PREFIX_COUNT} test prefixes on the trigger STSWs",
        ),
        create_longevity_step(
            duration=STABILIZATION_DELAY_SEC,
            description=f"Stabilize {STABILIZATION_DELAY_SEC}s before the FSDB stop",
        ),
        create_fpf_record_disruption_time_step(
            description="Record FSDB-stop disruption time"
        ),
        create_service_interruption_step(
            service=taac_types.Service.FSDB,
            trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_STOP,
            device_regexes=[DUT_GTSW],
            description=f"systemctl stop fsdb on {DUT_GTSW} (NOT re-enabled)",
        ),
        create_longevity_step(
            duration=STOP_DURATION_SEC,
            description=(
                f"Hold fsdb stopped {STOP_DURATION_SEC}s "
                f"(beyond GR window — routes purged)"
            ),
        ),
    ]
    disrupt_playbook = create_fpf_disruption_only_playbook(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        disruption_steps=disrupt_steps,
        playbook_name="fpf_tc30_fsdb_gr_stop180_disrupt",
    )

    # --- Playbook 2: "stays at 28" stable assertion, anchored post-stop. ---
    stays_down_steps = [
        create_longevity_step(
            duration=STAYS_DOWN_ASSERT_SEC,
            description=(
                f"Observe the impaired steady state {STAYS_DOWN_ASSERT_SEC}s "
                f"(fsdb stays down; census stays at {CONNECTED_STAYS_AT})"
            ),
        ),
    ]
    stays_down_playbook = create_fpf_stays_down_assertion_playbook(
        playbook_name="fpf_tc30_fsdb_gr_stop180_stays_down",
        stays_down_steps=stays_down_steps,
        postchecks=[
            create_fpf_hrt_session_stat_check(
                # mode="stable" asserts the census holds steady (min==max) at the
                # impaired count with NO recovery requirement — the supported
                # "stays at 28, no recovery" mapping (see module docstring).
                mode="stable",
                expected_connected=CONNECTED_STAYS_AT,
                impacted_lanes=IMPACTED_LANES,
                lookback_sec=SESSION_LOOKBACK_SEC,
                check_id="fpf_tc30_fsdb_gr_stop180_session_stat",
            ),
        ],
    )

    return TestConfig(
        name="fpf_tc30_fsdb_gr_stop180_no_reenable",
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
        playbooks=[disrupt_playbook, stays_down_playbook],
        tags=["fpf"],
    )


TEST_CONFIG = create_fpf_tc30_test_config()
