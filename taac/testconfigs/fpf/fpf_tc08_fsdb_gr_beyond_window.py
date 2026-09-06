# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""TC8: FSDB GR — Expiry Beyond GR Window.

Unlike the loop-kill tests (tc51), this STOPS fsdb continuously on the DUT GTSW
(gtsw001 = lane 0) and holds it down past the ~120s FSDB graceful-restart hold.
Because HRT's disconnected_gr_hold timer only resets when HRT RECONNECTS, a
continuous stop lets the timer EXPIRE → lane-0 routes are purged → beth0 egress
DRAINS on the impacted GPU host. Other lanes (beth1-3) are unaffected.

Stop duration = 240s (120s GR window + 120s settle), so we stop at least 2 min
past the 120s mark; the host-spray check then reads lane 0 over the post-GR tail
([disruption+120, disruption+240]) with the default avg(1m),latest transform, so
the "latest 1-minute" reading reflects the fully-drained state, not the GR-hold
transient. Within-window behavior (stop < 120s, lane 0 keeps spraying) is the
tc7 companion.

Prefixes are injected on ALL 8 STSWs, split per VF group (VF1 5000:dd on
s001-s004 = planes 0-3, VF2 5000:ee on s005-s008 = planes 4-7), via the
fpf_inject_bgp_prefixes SETUP TASK so the netcastle run is self-contained. The
fabric is VF-segregated, so each observer GTSW / lane sees only its own VF
group's count: PREFIX_COUNT = VF_GROUP_PREFIX_COUNT. Collector subnet is 5000::/16
to count both groups. The playbook passes skip_injection=True (no in-playbook
inject) and checks all 8 lanes.

Requires ib_write_bw traffic flowing so the per-lane beth egress is observable.
"""

from taac.health_checks.healthcheck_definitions import (
    create_fpf_host_spray_check,
)
from taac.libs.fpf.fpf_prod_prefix_map import get_prefix
from taac.playbooks.playbook_definitions import (
    create_fpf_hardening_playbook_v2,
)
from taac.steps.step_definitions import (
    create_fpf_record_disruption_time_step,
    create_fpf_record_restart_time_step,
    create_longevity_step,
    create_service_convergence_step,
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

INJECTION_GROUPS = fpf_vf_injection_groups()
RF_VF_GROUPS = fpf_rf_vf_groups()
PREFIX_COUNT = VF_GROUP_PREFIX_COUNT
INJECT_SETTLE_SEC = 300
INJECTED_LANES = ALL_LANES
STABILIZATION_DELAY_SEC = 300

PROD_PREFIX_HOST = GPU_HOSTS[0]
PROD_PREFIX_DEVICE_ID = 0
PROD_PREFIXES = [get_prefix(PROD_PREFIX_HOST, PROD_PREFIX_DEVICE_ID)]

GR_WINDOW_SEC = 120
# Stop >= 2 min past the 120s GR mark so lane 0 is fully drained + settled.
STOP_DURATION_SEC = GR_WINDOW_SEC + 120  # 240s
SPRAY_FLOOR_GBPS = 75.0
SPRAY_IMPACTED_MAX_GBPS = 10.0
# FSDB re-enable converges routes quickly, but the lane-0 RDMA (beth0) traffic
# re-ramps slower (observed 2-7min). Settle this long after recovery so the
# generic host-spray's avg(1m),latest reads the recovered state and positively
# asserts lane-0 data-plane recovery. Bump if beth0 is still ramping on rerun.
POST_RECOVERY_SETTLE_SEC = 300


def create_fpf_tc08_test_config() -> TestConfig:
    skip_ssh = skip_ssh_dependencies()
    ib_setup, ib_teardown = fpf_ib_traffic_tasks(skip_ssh)
    spray = None if skip_ssh else SPRAY_HOSTS

    disruption_steps = [
        create_fpf_record_disruption_time_step(
            description="Record FSDB-stop disruption time (anchors the spray window)"
        ),
        create_service_interruption_step(
            service=taac_types.Service.FSDB,
            trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_STOP,
            description="Stop FSDB on DUT GTSW (held down past GR window)",
        ),
        create_longevity_step(
            duration=STOP_DURATION_SEC,
            description=(
                f"Hold FSDB down {STOP_DURATION_SEC}s "
                f"(>{GR_WINDOW_SEC}s GR window — lane-0 routes purge, beth0 drains)"
            ),
        ),
        create_fpf_record_restart_time_step(
            description="Record FSDB restart time for ribMap reconvergence SLA"
        ),
        create_service_interruption_step(
            service=taac_types.Service.FSDB,
            trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_START,
            description="Restart FSDB on DUT GTSW after GR expiry",
        ),
        create_service_convergence_step(
            services=[taac_types.Service.FSDB],
            timeout=600,
            description="Wait for FSDB convergence after GR expiry recovery",
        ),
        create_longevity_step(
            duration=POST_RECOVERY_SETTLE_SEC,
            description=(
                f"Settle {POST_RECOVERY_SETTLE_SEC}s after FSDB recovery for "
                "lane-0 data-plane (beth0) re-ramp before host-spray asserts "
                "the floor"
            ),
        ),
    ]

    postchecks = []
    if spray:
        # CONTRACT: an fsdb disruption on the DUT GTSW impacts ONLY the LOCAL DUT
        # host cabled to it (gtsw001 -> GPU_HOSTS[0]); the remote DUT host's beth0
        # rides a different plane-0 GTSW and keeps spraying. So over the POST-GR
        # tail [disruption+120, disruption+240] (fsdb still stopped), assert lane 0
        # (beth0) is DRAINED (<10 Gbps) on the LOCAL host ONLY, while every other
        # lane/host stays sprayed (>75 Gbps). window_offset_sec skips the GR-hold
        # transient; the default avg(1m),latest reads the fully-drained state.
        postchecks.append(
            create_fpf_host_spray_check(
                hosts=SPRAY_HOSTS,
                min_egress_gbps=SPRAY_FLOOR_GBPS,
                impacted_lanes_by_host={GPU_HOSTS[0]: ["beth0"]},
                impacted_max_gbps=SPRAY_IMPACTED_MAX_GBPS,
                window_from_disruption_time=True,
                window_offset_sec=GR_WINDOW_SEC,
                window_duration_sec=STOP_DURATION_SEC - GR_WINDOW_SEC,
                label=(
                    "[fsdb-stop >GR] local-host lane0(beth0) drained <10G; "
                    "all other lanes/hosts spray >75G (fsdb=local-only)"
                ),
                check_id="fpf_tc08_host_spray_lane0_drained",
            )
        )

    playbook = create_fpf_hardening_playbook_v2(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        disruption_steps=disruption_steps,
        stabilization_delay_sec=STABILIZATION_DELAY_SEC,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        additional_postchecks=postchecks,
        playbook_name="fpf_tc08_fsdb_gr_beyond_window",
        prod_prefixes=PROD_PREFIXES,
        skip_ssh_dependent_checks=skip_ssh,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
        # CONTRACT: fsdb is LOCAL-only — only the DUT-cabled host's (GPU_HOSTS[0])
        # beth0 drains then recovers. Rather than exempt beth0 from the generic
        # floor, the POST_RECOVERY_SETTLE step above lets the host-spray's
        # avg(1m),latest read AFTER the beth0 re-ramp, so the generic floor
        # positively ASSERTS lane-0 recovery on all 4 lanes (recovery is monotonic).
        # The dedicated fpf_tc08_host_spray_lane0_drained check still asserts beth0
        # DRAINED during the stop window [+120,+240] (the during-disruption signal).
        # 8-plane: prefixes injected once by the setup task; check all 8 lanes.
        skip_injection=True,
        rf_vf_groups=RF_VF_GROUPS,
        lanes=INJECTED_LANES,
        # fsdb is GR-restarted (beyond the GR window) on the DUT GTSW; anchor
        # reconvergence on fsdb's restart. If fsdb does not bounce the BGP
        # sessions, convergence clamps to 0 — a clean pass. Scoped to the DUT.
        assert_bgp_reconvergence=True,
        reconvergence_service="fsdb",
        reconvergence_sla_sec=60.0,
        reconvergence_hosts=[OBSERVER_GTSWS[0]],
        # Use a separate pre-START timestamp for ribMap recovery. The pre-STOP
        # disruption timestamp above remains the anchor for the drain window.
        fsdb_rib_restart_reconverge=True,
        # fsdb/HRT are coupled: the HRT FSDB-session census dips while fsdb
        # re-subscribes after the GR — expected, not a fault. Skip the postcheck
        # (precheck still asserts the 32/32 baseline).
        skip_fsdb_session_postcheck=True,
        # GR-beyond (DISRUPTIVE: routes purge past the GR window): the affected
        # FSDB ribMap uses the restart-aware contract above. MODE A applies to
        # the unaffected BGP and HRT checks and asserts only that the LAST
        # in-window sample returns to the golden value.
        convergence_blip_mode="last_sample",
        # Expected mid-disruption STSW packet loss to purged lane-0 dests —
        # informational, not a hard fail (user-confirmed).
        ods_discard_informational=True,
    )

    return TestConfig(
        name="fpf_tc08_fsdb_gr_beyond_window",
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
        playbooks=[playbook],
        tags=["fpf"],
    )


TEST_CONFIG = create_fpf_tc08_test_config()
