# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""TC29: FSDB graceful-restart timer — stop fsdb 30s, re-enable within the step.

Stops ``fsdb`` (systemctl stop) on gtsw001, waits 30s (well within the FSDB
graceful-restart grace window), then re-enables it (systemctl start) — all inside
one disruption step group. fsdb owns lane 0 (gtsw001 -> lane 0).

Within the grace period the routing state is held, so nothing structurally
changes EXCEPT that the HRT FSDB-session census shows lane 0 of all 4 GPUs
NOT-CONNECTED for the ~30s the daemon is stopped (the thrift session drops), then
recovers when fsdb comes back. So the session-stat check runs in disruption mode:
32 -> 28 on lane 0 during the stop, recover to 32 (hold >= 30s).

Two-playbook "longevity-anchored health check" structure:

  Playbook 1 (disruption-only): inject prefixes, stabilize, record disruption
    time, stop fsdb, 30s longevity, start fsdb, then a 120s post-re-enable settle
    so the session-stat collector window spans the 28 -> 32 recovery. POSTCHECKS:
    (a) HRT session-stat in disruption mode (32 -> 28 on lane 0 -> recover, hold
    >= 60s); (b) host-spray
    with all_samples=True — track EVERY sample on EVERY beth lane (beth0-3) of both
    rtptest hosts across the window (sustained per-lane egress floor + fairness;
    the data plane should stay clean since GR holds forwarding state).

  Playbook 2 (stable-state longevity, 5 min): full stable-state hardening
    contract; the runner re-stamps test_case_start_time at its start so all its
    HCs (including session-stat in STABLE mode = 32, no churn) anchor at longevity
    start.

ASSUMPTIONS:
  - GR grace-period behavior: within the grace window forwarding state is held, so
    the only observable change is the HRT thrift FSDB session for lane 0 going
    NOT-CONNECTED for the 30s stop. We therefore model it identically to a brief
    lane impairment: expected_connected_during=28 (32-4) with recovery.
  - recovery_min_sec=60 — the post-re-enable 120s settle inside the disrupt
    playbook gives the collector ample window to observe a full 60s of held
    recovery after the sessions return to 32.
  - lookback_sec=900 anchors at Playbook-1 start and spans
    stabilize(120)+stop(30)+reenable-settle(120); 900s comfortably covers it.
  - host-spray all_samples=True is the per-sample sustained-fairness assertion the
    spec calls for (track all samples for all beths of both hosts).

Headless run stops/starts fsdb via SSH/systemctl — kick off from a
Kerberos-ticketed terminal. With SSH skipped, the host-spray postcheck is dropped.

Usage:
  buck2 run neteng/netcastle:netcastle_taac -- \\
    --team taac --test-config fpf_tc29_fsdb_gr_stop30_reenable \\
    --dev --skip-basset-reservation --skip-testbed-isolation \\
    --debug --continue-on-precheck-failure --skip-fboss-rsyslog
"""

from taac.health_checks.healthcheck_definitions import (
    create_fpf_host_spray_check,
    create_fpf_hrt_session_stat_check,
)
from taac.libs.fpf.fpf_prod_prefix_map import get_prefix
from taac.playbooks.playbook_definitions import (
    create_fpf_disrupt_window_playbook,
    create_fpf_hardening_playbook_v2,
)
from taac.steps.step_definitions import (
    create_fpf_record_disruption_time_step,
    create_longevity_step,
    create_service_interruption_step,
)
from taac.task_definitions import (
    create_fpf_inject_vf_groups_task,
    create_fpf_restart_service_task,
    create_fpf_start_collectors_task,
    create_fpf_stop_collectors_task,
    create_fpf_withdraw_vf_groups_task,
)
from taac.testconfigs.fpf.fpf_hardening_common import (
    ALL_STSWS,
    ALLOW_BASELINE_FAILURES,
    create_fpf_endpoints,
    DEFAULT_COMMUNITY_LIST,
    EXPECTED_FSDB_SESSION_COUNT,
    fpf_hrt_device_ids,
    fpf_hrt_lanes,
    fpf_hrt_vf_device_ids,
    fpf_ib_traffic_config,
    fpf_ib_traffic_tasks,
    fpf_rf_vf_groups,
    fpf_vf_injection_groups,
    FSDB_COLLECTOR_MODE,
    GPU_HOSTS,
    HRT_MEMORY_HOSTS,
    OBSERVER_GTSWS,
    skip_ib_traffic,
    skip_ssh_dependencies,
    SPRAY_HOSTS,
    VF_COLLECTOR_SUBNET,
    VF_GROUP_PREFIX_COUNT,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import TestConfig

PREFIX_COUNT = VF_GROUP_PREFIX_COUNT
INJECTION_GROUPS = fpf_vf_injection_groups()
INJECTED_LANES = fpf_hrt_lanes()
HRT_DEVICE_IDS = fpf_hrt_device_ids()
HRT_VF_DEVICE_IDS = fpf_hrt_vf_device_ids(HRT_DEVICE_IDS)
RF_VF_GROUPS = fpf_rf_vf_groups(
    active_lanes=INJECTED_LANES,
    device_ids_by_vf=(HRT_VF_DEVICE_IDS if HRT_DEVICE_IDS != [0] else None),
)
IB_TRAFFIC_CONFIG = fpf_ib_traffic_config()
STABILIZATION_DELAY_SEC = 120
STOP_DURATION_SEC = 30
# Post-re-enable settle held WITHIN the disrupt playbook so the session-stat
# collector window captures the 28 -> 32 recovery (the run's Signal2 "did not
# recover" was the observation window ending before the re-enabled sessions
# returned to 32). Must comfortably exceed RECOVERY_MIN_SEC.
REENABLE_SETTLE_SEC = 120
LONGEVITY_SOAK_SEC = 300
SESSION_LOOKBACK_SEC = 900
RECOVERY_MIN_SEC = 60

DUT_GTSW = OBSERVER_GTSWS[0]
IMPACTED_LANES = [0]
CONNECTED_DURING = EXPECTED_FSDB_SESSION_COUNT - 4  # 28

PROD_PREFIX_HOST = GPU_HOSTS[0]
PROD_PREFIX_DEVICE_ID = 0
PROD_PREFIXES = [get_prefix(PROD_PREFIX_HOST, PROD_PREFIX_DEVICE_ID)]
PROD_PREFIXES_BY_HOST = {host: PROD_PREFIXES for host in GPU_HOSTS}
IMPACTED_TUPLES = (
    {GPU_HOSTS[0]: {str(device_id): [0] for device_id in HRT_VF_DEVICE_IDS[0]}}
    if HRT_DEVICE_IDS != [0]
    else None
)


def create_fpf_tc29_test_config() -> TestConfig:
    skip_ssh = skip_ssh_dependencies()
    skip_ib = skip_ib_traffic()
    spray = None if skip_ssh or skip_ib else SPRAY_HOSTS
    ib_setup, ib_teardown = fpf_ib_traffic_tasks(
        skip_ssh, skip_ib, traffic_config=IB_TRAFFIC_CONFIG
    )

    # --- Playbook 1: stop 30s / re-enable, session-stat + host-spray postchecks.
    disrupt_steps = [
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
            intentional_stop=True,
            device_regexes=[DUT_GTSW],
            description=f"systemctl stop fsdb on {DUT_GTSW}",
        ),
        create_longevity_step(
            duration=STOP_DURATION_SEC,
            description=(
                f"Hold fsdb stopped {STOP_DURATION_SEC}s (within the GR grace window)"
            ),
        ),
        create_service_interruption_step(
            service=taac_types.Service.FSDB,
            trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_START,
            device_regexes=[DUT_GTSW],
            description=f"systemctl start fsdb on {DUT_GTSW} (re-enable)",
        ),
        create_longevity_step(
            duration=REENABLE_SETTLE_SEC,
            description=(
                f"Settle {REENABLE_SETTLE_SEC}s after re-enabling fsdb so the "
                f"session-stat collector captures the 28 -> 32 recovery"
            ),
        ),
    ]
    postchecks = [
        create_fpf_hrt_session_stat_check(
            mode="disruption",
            expected_connected=EXPECTED_FSDB_SESSION_COUNT,
            expected_connected_during=CONNECTED_DURING,
            impacted_lanes=(IMPACTED_LANES if HRT_DEVICE_IDS == [0] else None),
            impacted_tuples_by_host_device=IMPACTED_TUPLES,
            recovery_min_sec=RECOVERY_MIN_SEC,
            lookback_sec=SESSION_LOOKBACK_SEC,
            check_id="fpf_tc29_fsdb_gr_stop30_session_stat",
        ),
    ]
    if not skip_ssh:
        postchecks.append(
            create_fpf_host_spray_check(
                hosts=SPRAY_HOSTS,
                all_samples=True,
                lookback_sec=SESSION_LOOKBACK_SEC,
                check_id="fpf_tc29_fsdb_gr_stop30_host_spray",
            )
        )
    disrupt_playbook = create_fpf_disrupt_window_playbook(
        playbook_name="fpf_tc29_fsdb_gr_stop30_disrupt",
        disruption_steps=disrupt_steps,
        postchecks=postchecks,
    )

    # --- Playbook 2: full stable-state longevity (5 min). ---
    longevity_playbook = create_fpf_hardening_playbook_v2(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=ALL_STSWS,
        soak_duration_sec=LONGEVITY_SOAK_SEC,
        stabilization_delay_sec=0,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        playbook_name="fpf_tc29_fsdb_gr_stop30_longevity",
        prod_prefixes=PROD_PREFIXES,
        prod_prefixes_by_host=PROD_PREFIXES_BY_HOST,
        skip_ssh_dependent_checks=skip_ssh,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
        ib_traffic_config=IB_TRAFFIC_CONFIG if spray else None,
        lanes=INJECTED_LANES,
        hrt_device_ids=HRT_DEVICE_IDS,
        skip_injection=True,
        rf_vf_groups=RF_VF_GROUPS,
    )

    return TestConfig(
        name="fpf_tc29_fsdb_gr_stop30_reenable",
        endpoints=create_fpf_endpoints(stsws=ALL_STSWS),
        setup_tasks=[
            *ib_setup,
            create_fpf_start_collectors_task(
                gtsws=OBSERVER_GTSWS,
                hosts=GPU_HOSTS,
                hrt_device_ids=HRT_DEVICE_IDS,
                hrt_plane_ids=INJECTED_LANES,
                subnet_prefix=VF_COLLECTOR_SUBNET,
                prod_prefixes_by_host=PROD_PREFIXES_BY_HOST,
                prod_prefix_device_id=PROD_PREFIX_DEVICE_ID,
                fsdb_mode=FSDB_COLLECTOR_MODE,
                allow_baseline_failures=ALLOW_BASELINE_FAILURES,
                enable_fsdb_session_collector=True,
                fsdb_session_host=GPU_HOSTS[0],
                fsdb_session_expected=EXPECTED_FSDB_SESSION_COUNT,
                rf_vf_groups=RF_VF_GROUPS,
            ),
            create_fpf_inject_vf_groups_task(groups=INJECTION_GROUPS, settle_sec=120),
        ],
        teardown_tasks=[
            create_fpf_withdraw_vf_groups_task(groups=INJECTION_GROUPS),
            create_fpf_restart_service_task(devices=ALL_STSWS, service="BGP"),
            create_fpf_stop_collectors_task(
                trigger_stsws=ALL_STSWS,
                withdraw=False,
                community_list=DEFAULT_COMMUNITY_LIST,
            ),
            *ib_teardown,
        ],
        playbooks=[disrupt_playbook, longevity_playbook],
        tags=["fpf"],
    )


TEST_CONFIG = create_fpf_tc29_test_config()
