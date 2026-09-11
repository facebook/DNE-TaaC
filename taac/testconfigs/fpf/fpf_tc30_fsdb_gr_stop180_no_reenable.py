# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""TC30: FSDB GR timer beyond window — stop fsdb 5min, do NOT re-enable.

Stops ``fsdb`` (systemctl stop) on gtsw001 and holds it stopped for 300s (5m) —
beyond the FSDB graceful-restart grace window — and never starts it back. The 5m
hold IS the observation window (there is NO separate longevity playbook). fsdb
owns lane 0 (gtsw001 -> lane 0 = ``beth0`` on the GPU NIC hosts), so past GR expiry
lane 0 of all 4 GPUs stays withdrawn and the impaired steady state persists,
exactly like an interface disable that is left down (compare to the fpf_tc15
interface-disable DISRUPT playbook): bulk/fsdb on lane 0 withdrawn, remote-failure
shows the impacted lane, the HRT CONNECTED FSDB-session census settles at 28
(32 - 4) and STAYS there with no recovery, AND — the added data-plane signal —
beth0 egress DRAINS (< 10 Gbps) on the GPU host cabled to gtsw001 while its
lanes 1-3 keep spraying (> 75 Gbps). The other GPU host's beth0 lands on a
DIFFERENT plane-0 GTSW (confirmed by LLDP: only GPU_HOSTS[0] neighbors gtsw001),
so it is UNAFFECTED — all 4 of its lanes hold > 75 Gbps, which also validates
that the disruption's blast radius stays local to the host on gtsw001.

Two distinct timescales (validated on the testbed — keep them separate):
  - Control plane (the FSDB session census): the transition is IMMEDIATE. On
    `systemctl stop fsdb` the per-host CONNECTED count drops 32 -> 28 (lane 0 of
    all 4 GPUs goes to 0) within ~4s. It does NOT wait for the GR grace window —
    the ~120s grace is purely a routes/data-plane forwarding hold. The session
    collector confirms: only the single poll captured AT the stop instant reads
    32; every later sample reads 28. So the stays-down session check skips the
    first SESSION_WINDOW_OFFSET_SEC (10s) to exclude that boundary sample and
    asserts a clean steady 28.
  - Data plane (beth0 egress): held by GR for ~120s, then purged. The host-spray
    check therefore reads at the END of the 5m hold with an avg(30s),latest
    transform — well past the purge, with a tight averaging window so the drained
    reading isn't smeared across the transition.

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
  requirement — i.e. the impaired census holds steady at 28. To scope that window
  to AFTER the stop (so the pre-stop 32 samples are excluded), the stays-down
  checks set window_from_disruption_time=True + window_duration_sec=
  STOP_DURATION_SEC, so they evaluate exactly [disruption_time,
  disruption_time+300] — the 5m hold. The session check additionally sets
  window_offset_sec=10 to drop the stop-instant boundary sample. The host-spray
  check uses the same scoped window (latest avg(30s) at the END of the hold) to
  assert the lane-0-drained / lanes-1-3-hold data-plane state.

  Two-playbook structure is kept: a disruption playbook (inject/stabilize/stop/
  hold 300s) that CARRIES the stays-down postchecks, followed by a minimal
  no-step playbook (preserves the structure, carries no checks). There is no
  stable-state hardening longevity here: fsdb is intentionally left down, so the
  FULL stable contract (which expects 32) does not apply.

ASSUMPTIONS:
  - mode="stable" + expected_connected=28 is the supported "stays at 28, no
    recovery" mapping (disruption mode cannot express "no recovery"; see above).
  - The FSDB session census drops to 28 within ~4s of the stop (control-plane
    transition is immediate); window_offset_sec=10 excludes the stop-instant
    boundary sample so the stable check sees a clean steady 28.
  - The 300s hold exceeds the FSDB GR window (~120s), so lane 0 routes are fully
    purged within the hold; the end-of-hold avg(30s),latest reading shows beth0
    drained.
  - window_from_disruption_time scopes both stays-down checks to the 5m hold
    ([disruption_time, disruption_time+300]), excluding pre-stop healthy samples.

Headless run stops fsdb via SSH/systemctl — kick off from a Kerberos-ticketed
terminal.

Usage:
  buck2 run neteng/netcastle:netcastle_taac -- \\
    --team taac --test-config fpf_tc30_fsdb_gr_stop180_no_reenable \\
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
    create_fpf_stays_down_assertion_playbook,
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
    Circuit,
    create_fpf_endpoints,
    DEFAULT_COMMUNITY_LIST,
    EXPECTED_FSDB_SESSION_COUNT,
    fpf_hrt_device_ids,
    fpf_hrt_lanes,
    fpf_hrt_vf_device_ids,
    fpf_ib_traffic_config,
    fpf_ib_traffic_tasks,
    fpf_link_drain_interface,
    fpf_rf_vf_groups,
    fpf_vf_injection_groups,
    FSDB_COLLECTOR_MODE,
    GPU_HOSTS,
    OBSERVER_GTSWS,
    skip_ib_traffic,
    skip_ssh_dependencies,
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
# 5min (300s) hold >> GR window (~120s): the data-plane route purge (~120s) fully
# settles, so the lane-0 drained reading is taken well after the transition.
STOP_DURATION_SEC = 300
SESSION_LOOKBACK_SEC = 900
# The FSDB session census drops to 28 within ~4s of the stop (the control-plane
# transition is IMMEDIATE; the ~120s GR grace applies only to routes/data-plane).
# Skip the first 10s so the stable window excludes the single boundary sample
# captured at the exact stop instant (which still reads 32, pre-drop).
SESSION_WINDOW_OFFSET_SEC = 10
# tc30-specific host-spray transform: average the last 30s (not 1m) and take the
# latest sample, so the drained-lane reading isn't smeared across the route-purge
# transition.
HOST_SPRAY_TRANSFORM_DESC = "formula(/ $1 125000000),avg(30s),latest"

DUT_GTSW = OBSERVER_GTSWS[0]
# Only the GPU host whose lane-0 (beth0) uplink is physically cabled to DUT_GTSW
# (gtsw001) sees its beth0 drain when gtsw001's fsdb is stopped — confirmed by
# the environment-selected circuit. The OTHER GPU host
# (GPU_HOSTS[1]) lands its beth0 on a different plane-0 GTSW, so it is UNAFFECTED
# and keeps spraying on all 4 lanes — it serves as the blast-radius-containment
# control. GPU_HOSTS[0] is the config's primary host (also the prod-prefix and
# fsdb-session host), so it is the one cabled to DUT_GTSW.
DUT_CIRCUIT = Circuit(
    a_end_device=DUT_GTSW,
    a_end_interface=fpf_link_drain_interface(GPU_HOSTS),
    z_end_device=GPU_HOSTS[0],
    z_end_gpu_id=0,
)
DUT_HOST = DUT_CIRCUIT.z_end_device
IMPACTED_LANES = [0]
# Steady impaired census after GR expiry on lane 0 of all 4 GPUs: 32 - 4 = 28.
CONNECTED_STAYS_AT = EXPECTED_FSDB_SESSION_COUNT - 4  # 28

PROD_PREFIX_HOST = GPU_HOSTS[0]
PROD_PREFIX_DEVICE_ID = 0
PROD_PREFIXES = [get_prefix(PROD_PREFIX_HOST, PROD_PREFIX_DEVICE_ID)]
PROD_PREFIXES_BY_HOST = {host: PROD_PREFIXES for host in GPU_HOSTS}
IMPACTED_TUPLES = (
    {
        DUT_HOST: {
            str(device_id): [DUT_CIRCUIT.lane] for device_id in HRT_VF_DEVICE_IDS[0]
        }
    }
    if HRT_DEVICE_IDS != [0]
    else None
)


def create_fpf_tc30_test_config() -> TestConfig:
    skip_ssh = skip_ssh_dependencies()
    skip_ib = skip_ib_traffic()
    ib_setup, ib_teardown = fpf_ib_traffic_tasks(
        skip_ssh, skip_ib, traffic_config=IB_TRAFFIC_CONFIG
    )

    # --- Playbook 1: disruption-only (inject/stabilize/stop/hold), NO checks. ---
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
    # The 5m hold IS the observation window (no separate longevity playbook).
    # Both stays-down postchecks are scoped to that hold via
    # window_from_disruption_time=True + window_duration_sec=STOP_DURATION_SEC, so
    # they evaluate [disruption_time, disruption_time+300] only — the pre-stop 32
    # samples are excluded (and the session check skips the first 10s boundary).
    disrupt_playbook = create_fpf_disrupt_window_playbook(
        playbook_name="fpf_tc30_fsdb_gr_stop180_disrupt",
        disruption_steps=disrupt_steps,
        postchecks=[
            create_fpf_hrt_session_stat_check(
                # mode="stable" asserts the census holds steady (min==max) at the
                # impaired count with NO recovery requirement — the supported
                # "stays at 28, no recovery" mapping (see module docstring).
                # Window scoped to the 180s hold via the disruption time.
                mode="stable",
                expected_connected=CONNECTED_STAYS_AT,
                impacted_lanes=IMPACTED_LANES,
                impacted_tuples_by_host_device=IMPACTED_TUPLES,
                window_from_disruption_time=True,
                window_offset_sec=SESSION_WINDOW_OFFSET_SEC,
                window_duration_sec=STOP_DURATION_SEC,
                check_id="fpf_tc30_fsdb_gr_stop180_session_stat",
            ),
            # Data-plane "more color": over the SAME hold window, lane 0 (beth0)
            # is drained < 10 Gbps ONLY on the GPU host cabled to gtsw001
            # (DUT_HOST) — routes purged past GR — while its lanes 1-3 keep
            # spraying > 75 Gbps. The OTHER GPU host is unaffected (its beth0
            # lands on a different plane-0 GTSW), so all 4 of its lanes stay
            # > 75 Gbps; this doubles as a blast-radius-containment control.
            create_fpf_host_spray_check(
                hosts=GPU_HOSTS,
                impacted_lanes_by_host={DUT_HOST: [DUT_CIRCUIT.nic_interface]},
                impacted_max_gbps=10.0,
                min_egress_gbps=75.0,
                transform_desc=HOST_SPRAY_TRANSFORM_DESC,
                window_from_disruption_time=True,
                window_duration_sec=STOP_DURATION_SEC,
                label=(
                    "[fsdb-down window @5min, avg30s] DUT-host lane0(beth0) "
                    "drained <10Gbps + its lanes1-3 >75Gbps; other host all "
                    "4 lanes >75Gbps (containment)"
                ),
                check_id="fpf_tc30_fsdb_gr_stop180_host_spray",
            ),
        ],
        spray_hosts=(None if skip_ssh or skip_ib else GPU_HOSTS),
        ib_traffic_config=(None if skip_ssh or skip_ib else IB_TRAFFIC_CONFIG),
    )

    # --- Playbook 2: no steps — the 180s hold above is the observation window.
    # Kept to preserve the two-playbook structure; carries no checks. ---
    stays_down_playbook = create_fpf_stays_down_assertion_playbook(
        playbook_name="fpf_tc30_fsdb_gr_stop180_stays_down",
        stays_down_steps=[],
        postchecks=[],
    )

    return TestConfig(
        name="fpf_tc30_fsdb_gr_stop180_no_reenable",
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
        playbooks=[disrupt_playbook, stays_down_playbook],
        tags=["fpf"],
    )


TEST_CONFIG = create_fpf_tc30_test_config()
