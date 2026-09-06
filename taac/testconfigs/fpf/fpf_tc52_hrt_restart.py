# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""TC52: Restart HostReachTracker (HRT) on the BE node, expect clean recovery.

Restarts the HRT service (``systemctl restart metalos.wds.hostreachtracker``) on
the GPU/BE host, waits 2 minutes for HRT to re-subscribe to FSDB and rebuild its
sessions, then requires production-prefix state to recover within 30 seconds
from the first complete sample after restart completion/final observed outage
and remain healthy at the final valid sample. Bulk and remote-failure checks
tolerate outage errors only on the restarted host; the unaffected host and all
valid samples stay strict. A second, no-churn longevity playbook confirms the
recovered state stays clean.

HRT runs on the rtptest host, NOT on a FBOSS switch, so the restart goes through
the host-SSH path (lab-ssh as root), the same transport used by the ib-traffic /
NIC-flap host steps — see ``fpf_restart_hrt`` in custom_step.py.

Two-playbook structure (both full stable-state v2 — same as fpf_stress_test_config):
  1. Disrupt playbook: inject + stabilize, record restart initiation, restart
     HRT, settle 120s, then validate bounded production-prefix recovery plus the
     remaining stable-state checks.
  2. Longevity playbook: stable-state soak (no churn) — confirms the recovered
     state holds.

Usage:
  TAAC_SSH_VIA_LAB_SSH=1 buck2 run neteng/netcastle:netcastle_taac -- \\
    --team taac --test-config fpf_tc52_hrt_restart \\
    --dev --skip-basset-reservation --skip-testbed-isolation \\
    --debug --continue-on-precheck-failure --skip-fboss-rsyslog
"""

from taac.libs.fpf.fpf_prod_prefix_map import get_prefix
from taac.playbooks.playbook_definitions import (
    create_fpf_hardening_playbook_v2,
)
from taac.steps.step_definitions import (
    create_fpf_record_restart_completion_time_step,
    create_fpf_record_restart_time_step,
    create_fpf_restart_hrt_step,
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
from taac.test_as_a_config.types import TestConfig

# 8-plane VF-group injection (VF1 5000:dd on s001-s004 = planes 0-3, VF2 5000:ee
# on s005-s008 = planes 4-7); injected once by the setup task, withdrawn in
# teardown, so the playbooks pass skip_injection=True.
INJECTION_GROUPS = fpf_vf_injection_groups()
RF_VF_GROUPS = fpf_rf_vf_groups()
PREFIX_COUNT = VF_GROUP_PREFIX_COUNT
INJECT_SETTLE_SEC = 120
INJECTED_LANES = ALL_LANES
STABILIZATION_DELAY_SEC = 120
# HRT re-subscribes to FSDB on all 8 GTSWs and rebuilds its 32 sessions after a
# restart — wait 2 min before the postchecks judge the recovered state.
POST_RESTART_SETTLE_SEC = 120
LONGEVITY_SEC = 300

# HRT runs on the BE node we observe (rtptest1544 = GPU_HOSTS[0]).
HRT_RESTART_HOSTS = [GPU_HOSTS[0]]

PROD_PREFIX_HOST = GPU_HOSTS[0]
PROD_PREFIX_DEVICE_ID = 0
PROD_PREFIXES = [get_prefix(PROD_PREFIX_HOST, PROD_PREFIX_DEVICE_ID)]


def create_fpf_tc52_test_config() -> TestConfig:
    skip_ssh = skip_ssh_dependencies()
    ib_setup, ib_teardown = fpf_ib_traffic_tasks(skip_ssh)
    spray = None if skip_ssh else SPRAY_HOSTS

    # Playbook 1: restart HRT, tolerate its expected collection outage, and
    # require full production-prefix recovery within 30s from the first complete
    # post-restart sample. Other postchecks retain their existing contracts.
    disrupt_playbook = create_fpf_hardening_playbook_v2(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        soak_duration_sec=0,
        stabilization_delay_sec=STABILIZATION_DELAY_SEC,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        prod_prefixes=PROD_PREFIXES,
        skip_ssh_dependent_checks=skip_ssh,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
        disruption_steps=[
            create_fpf_record_restart_time_step(
                description=(
                    "Record HRT restart initiation for production-prefix recovery SLA"
                )
            ),
            create_fpf_restart_hrt_step(
                hosts=HRT_RESTART_HOSTS,
                description=(
                    f"Restart HostReachTracker on {HRT_RESTART_HOSTS} "
                    f"(systemctl restart metalos.wds.hostreachtracker)"
                ),
            ),
            create_fpf_record_restart_completion_time_step(
                description=(
                    "Record HRT restart completion for post-outage recovery eligibility"
                )
            ),
            create_longevity_step(
                duration=POST_RESTART_SETTLE_SEC,
                description=(
                    f"Settle {POST_RESTART_SETTLE_SEC}s for HRT to re-subscribe "
                    f"and rebuild its 32 FSDB sessions"
                ),
            ),
        ],
        playbook_name="fpf_tc52_hrt_restart_disrupt",
        # 8-plane: prefixes injected once by the setup task; check all 8 lanes.
        skip_injection=True,
        rf_vf_groups=RF_VF_GROUPS,
        lanes=INJECTED_LANES,
        prod_prefix_restart_recovery_sla_sec=30.0,
        hrt_restart_tolerant_hosts=HRT_RESTART_HOSTS,
        # Expected mid-disruption STSW packet loss to purged lane-0 dests —
        # informational, not a hard fail (user-confirmed).
        ods_discard_informational=True,
    )

    # Playbook 2: no-churn stable-state soak — confirms the recovered state holds.
    longevity_playbook = create_fpf_hardening_playbook_v2(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        soak_duration_sec=LONGEVITY_SEC,
        stabilization_delay_sec=STABILIZATION_DELAY_SEC,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        playbook_name="fpf_tc52_hrt_restart_longevity",
        prod_prefixes=PROD_PREFIXES,
        skip_ssh_dependent_checks=skip_ssh,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
        # 8-plane: prefixes injected once by the setup task; check all 8 lanes.
        skip_injection=True,
        rf_vf_groups=RF_VF_GROUPS,
        lanes=INJECTED_LANES,
    )

    return TestConfig(
        name="fpf_tc52_hrt_restart",
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


TEST_CONFIG = create_fpf_tc52_test_config()
