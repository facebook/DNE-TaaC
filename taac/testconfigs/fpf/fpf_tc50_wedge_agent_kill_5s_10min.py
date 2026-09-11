# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""TC50: explicitly SIGKILL split sw+hw agents every 15s for 5 minutes.

The legacy test/config identity is retained for callers, but the trigger is now
narrow and explicit: ``pkill -9 fboss_sw_agent`` followed by
``pkill -9 fboss_hw_agent``. It does not use the multi-switch ``Service.AGENT``
driver path because that expands to the broad ``pkill -9 -f fboss_`` match.

Two-playbook structure:
  Playbook 1 (disrupt-window): inject + stabilize + record + kill loop + settle,
    then assert the DISRUPTED-STATE CONTRACT via
    the same established TC50 disrupted-state health contract, thresholds, and
    traffic expectations. Both targeted kills are attempted per cycle and both
    systemd units must recover ACTIVE.
  Playbook 2 (stable-state longevity, 5 min): full stable-state contract,
    convergence_settle_sec excludes the kill→recovery transient.

Headless execution uses SSH shell commands; kick off from a Kerberos-ticketed
terminal (or set TAAC_SSH_VIA_LAB_SSH=1).

Usage:
  TAAC_SSH_VIA_LAB_SSH=1 buck2 run neteng/netcastle:netcastle_taac -- \\
    --team taac --test-config fpf_tc50_wedge_agent_kill_5s_10min \\
    --dev --skip-basset-reservation --skip-testbed-isolation \\
    --debug --continue-on-precheck-failure --skip-fboss-rsyslog
"""

from taac.libs.fpf.fpf_prod_prefix_map import get_prefix
from taac.playbooks.playbook_definitions import (
    create_fpf_disrupt_window_playbook,
    create_fpf_hardening_playbook_v2,
)
from taac.steps.step_definitions import (
    create_fpf_record_disruption_time_step,
    create_fpf_repeated_service_crash_step,
    create_fpf_repeated_sw_hw_agent_crash_step,
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
from taac.testconfigs.fpf.fpf_kill_contract import (
    build_kill_disrupt_postchecks,
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
KILL_EVERY_SEC = 15  # graceful loop-kill cadence (service recovers between kills)
KILL_DURATION_SEC = 300  # 5 min (campaign-shortened)
STABLE_AFTER_KILL_SEC = 120
LONGEVITY_SOAK_SEC = 300
LONGEVITY_SETTLE_SEC = 60
SESSION_LOOKBACK_SEC = 1000

DUT_GTSW = OBSERVER_GTSWS[0]
KILL_HEALTH_CONTRACT = "wedge_agent"
SW_HW_AGENT_RECOVERY_TIMEOUT_SEC = 120

PROD_PREFIX_HOST = GPU_HOSTS[0]
PROD_PREFIX_DEVICE_ID = 0
PROD_PREFIXES = [get_prefix(PROD_PREFIX_HOST, PROD_PREFIX_DEVICE_ID)]


def create_fpf_agent_kill_test_config(
    *,
    test_name: str,
    broad_multi_fboss_process_kill: bool,
) -> TestConfig:
    skip_ssh = skip_ssh_dependencies()
    ib_setup, ib_teardown = fpf_ib_traffic_tasks(skip_ssh)
    spray = None if skip_ssh else SPRAY_HOSTS

    # Prefixes are injected once by the setup task (8-plane VF groups), so the
    # disrupt window only stabilizes/records/kills/settles.
    if broad_multi_fboss_process_kill:
        kill_label = "broad multi-FBOSS-process"
        kill_step = create_fpf_repeated_service_crash_step(
            service=taac_types.Service.AGENT,
            every_sec=KILL_EVERY_SEC,
            duration_sec=KILL_DURATION_SEC,
            device_regexes=[DUT_GTSW],
            description=(
                "Broad SIGKILL '-f fboss_' match every "
                f"{KILL_EVERY_SEC}s for {KILL_DURATION_SEC}s on {DUT_GTSW}"
            ),
        )
    else:
        kill_label = "fboss_sw_agent+fboss_hw_agent"
        kill_step = create_fpf_repeated_sw_hw_agent_crash_step(
            every_sec=KILL_EVERY_SEC,
            duration_sec=KILL_DURATION_SEC,
            recovery_timeout_sec=SW_HW_AGENT_RECOVERY_TIMEOUT_SEC,
            device_regexes=[DUT_GTSW],
            description=(
                "SIGKILL fboss_sw_agent then fboss_hw_agent every "
                f"{KILL_EVERY_SEC}s for {KILL_DURATION_SEC}s on {DUT_GTSW}"
            ),
        )

    disrupt_steps = [
        create_longevity_step(
            duration=STABILIZATION_DELAY_SEC,
            description=f"Stabilize {STABILIZATION_DELAY_SEC}s before the kill loop",
        ),
        create_fpf_record_disruption_time_step(
            description=f"Record {kill_label}-kill disruption time"
        ),
        kill_step,
        create_longevity_step(
            duration=STABLE_AFTER_KILL_SEC,
            description=f"Stable {STABLE_AFTER_KILL_SEC}s after the kill loop stops",
        ),
    ]

    disrupt_playbook = create_fpf_disrupt_window_playbook(
        playbook_name=f"{test_name}_disrupt",
        disruption_steps=disrupt_steps,
        spray_hosts=spray,
        postchecks=build_kill_disrupt_postchecks(
            killed_service=KILL_HEALTH_CONTRACT,
            observer_gtsws=OBSERVER_GTSWS,
            hrt_memory_hosts=HRT_MEMORY_HOSTS,
            spray_hosts=spray,
            kill_duration_sec=KILL_DURATION_SEC,
            prefix_count=PREFIX_COUNT,
            skip_ssh=skip_ssh,
            expected_fsdb_total=EXPECTED_FSDB_SESSION_COUNT,
            session_lookback_sec=SESSION_LOOKBACK_SEC,
        ),
    )

    longevity_playbook = create_fpf_hardening_playbook_v2(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        soak_duration_sec=LONGEVITY_SOAK_SEC,
        stabilization_delay_sec=0,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        playbook_name=f"{test_name}_longevity",
        prod_prefixes=PROD_PREFIXES,
        skip_ssh_dependent_checks=skip_ssh,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
        convergence_settle_sec=LONGEVITY_SETTLE_SEC,
        # 8-plane: prefixes injected once by the setup task; check all 8 lanes.
        skip_injection=True,
        rf_vf_groups=RF_VF_GROUPS,
        lanes=INJECTED_LANES,
        # wedge_agent kill is DISRUPTIVE: metrics blip mid-window and reconverge
        # by end. MODE A (last_sample) asserts only the last in-window sample
        # holds golden.
        convergence_blip_mode="last_sample",
        # Expected mid-disruption STSW packet loss to purged lane-0 dests —
        # informational, not a hard fail (user-confirmed).
        ods_discard_informational=True,
    )

    return TestConfig(
        name=test_name,
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
                fsdb_session_host=GPU_HOSTS[0],
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
        playbooks=[disrupt_playbook, longevity_playbook],
        tags=["fpf"],
    )


def create_fpf_tc50_test_config() -> TestConfig:
    return create_fpf_agent_kill_test_config(
        test_name="fpf_tc50_wedge_agent_kill_5s_10min",
        broad_multi_fboss_process_kill=False,
    )


TEST_CONFIG = create_fpf_tc50_test_config()
