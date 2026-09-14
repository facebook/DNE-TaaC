# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""TC38: Persistent NDP Clear — Port UP, NDP DOWN.

Repeatedly flushes the exact GPU-facing GTSW circuit's NDP entries while every
port stays UP, so neighbor resolution is forced to re-converge continuously
under sustained clearing — the "the link is fine but the neighbor cache keeps
getting wiped" failure. The disruption is a 120s loop of circuit-scoped
sw-agent ``flushNeighborEntries`` Thrift calls (every 4s) on the observer GTSW,
followed by a 120s settle, then a recovered-state qualification and stable-state
v2 longevity playbook whose health checks anchor after exact recovery. The 4s
cadence is capacity-calibrated from live direct-RPC measurements (worst observed
just under 3s); each clear must finish before the next slot.

CHARACTERIZED EXPECTATIONS (per the test owner):
  A persistent NDP clear DOES perturb the DATA plane on the cleared GTSW's lane
  (gtsw001 = lane 0): the neighbor cache is wiped continuously, so lane 0 black-
  holes until each re-resolve and in_dst_null / in_discard discards spike, while
  congestion discards stay 0. Lane 0's own egress is immaterial during the
  disrupt window, so it is IGNORED there (not asserted); only beth1-3 are held to
  the spray floor. The CONTROL-plane HRT/TAAC collectors must NOT be disrupted at
  all — they hold to the full strict stable-state contract (all samples).

  Realized via the two-playbook pattern:
    1. disrupt-window: ndp-clear loop (120s) + settle (120s), with the
       data-plane-impact postchecks (lane0 ignored; beth1-3 spray; in_dst_null /
       in_discard captured informational; congestion == 0).
    2. stable-state v2: full strict stable-state HCs, anchored at longevity start
       (the runner stamps a fresh test_case_start_time), so the HRT/prefix
       collectors assert no disruption once the cache is re-resolved — and lane 0
       is verified recovered here.

  NOTE: the disrupt-window postchecks here are BUILD-validated only and not yet
  run on hardware; the discard thresholds should be confirmed and tuned on the
  first hardware run.

Usage:
  TAAC_FPF_SKIP_SSH_DEPS=1 buck2 run neteng/netcastle:netcastle_taac -- \\
    --team taac --test-config fpf_tc38_persistent_ndp_clear \\
    --dev --skip-basset-reservation --skip-testbed-isolation \\
    --debug --continue-on-precheck-failure --skip-fboss-rsyslog
"""

from taac.health_checks.healthcheck_definitions import (
    create_fpf_host_spray_check,
    create_fpf_ods_counter_check,
)
from taac.libs.fpf.fpf_prod_prefix_map import get_prefix
from taac.playbooks.playbook_definitions import (
    create_fpf_disrupt_window_playbook,
    create_fpf_hardening_playbook_v2,
)
from taac.steps.step_definitions import (
    create_fpf_ndp_clear_loop_step,
    create_fpf_record_disruption_time_step,
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
    HRT_MEMORY_HOSTS,
    OBSERVER_GTSWS,
    skip_ib_traffic,
    skip_ssh_dependencies,
    TRIGGER_STSWS,
    VF_COLLECTOR_SUBNET,
    VF_GROUP_PREFIX_COUNT,
)
from taac.test_as_a_config.types import TestConfig

# 8-plane VF-group injection (VF1 5000:dd on s001-s004 = planes 0-3, VF2 5000:ee
# on s005-s008 = planes 4-7); injected once by the setup task, withdrawn in
# teardown, so the stable-state playbook passes skip_injection=True.
INJECTION_GROUPS = fpf_vf_injection_groups()
PREFIX_COUNT = VF_GROUP_PREFIX_COUNT
INJECT_SETTLE_SEC = 300
INJECTED_LANES = fpf_hrt_lanes()
HRT_DEVICE_IDS = fpf_hrt_device_ids()
HRT_VF_DEVICE_IDS = fpf_hrt_vf_device_ids(HRT_DEVICE_IDS)
RF_VF_GROUPS = fpf_rf_vf_groups(
    active_lanes=INJECTED_LANES,
    device_ids_by_vf=(HRT_VF_DEVICE_IDS if HRT_DEVICE_IDS != [0] else None),
)
IB_TRAFFIC_CONFIG = fpf_ib_traffic_config()
STABILIZATION_DELAY_SEC = 300
NDP_CLEAR_EVERY_SEC = 4
NDP_CLEAR_DURATION_SEC = 120
SETTLE_AFTER_CLEAR_SEC = 120
LONGEVITY_SEC = 300

PROD_PREFIX_HOST = GPU_HOSTS[0]
PROD_PREFIX_DEVICE_ID = 0
PROD_PREFIXES = [get_prefix(PROD_PREFIX_HOST, PROD_PREFIX_DEVICE_ID)]
PROD_PREFIXES_BY_HOST = {host: PROD_PREFIXES for host in GPU_HOSTS}
NDP_CLEAR_CIRCUIT = Circuit(
    a_end_device=OBSERVER_GTSWS[0],
    a_end_interface=fpf_link_drain_interface(GPU_HOSTS),
    z_end_device=GPU_HOSTS[0],
    z_end_gpu_id=0,
)

# Characterized data-plane impact of a persistent NDP clear on the DUT GTSW
# (gtsw001 = lane 0): the neighbor cache is wiped continuously, so lane 0 (beth0)
# is perturbed (ignored during the disrupt window) and in_dst_null / in_discard
# discards spike, while congestion discards stay 0.
SPRAY_FLOOR_GBPS = 75.0
DISCARD_FLOOR = 10000
_ODS_REDUCE = r"groupby(entity, (\S+?\.\S+?)\..*, %1),sum"
_ODS_IN_DST_NULL_KEY = (
    r"regex(fboss.agent.eth.*discards.sum.60),filter(.*in_dst_null.*)"
)
_ODS_IN_DISCARD_KEY = r"regex(fboss.agent.eth.*discards.sum.60),filter(.*in_discard.*)"
_ODS_IN_CONGESTION_KEY = (
    r"regex(fboss.agent.eth.*congestion.*sum.60),filter(.*in_congestion_discards.sum.*)"
)
_ODS_OUT_CONGESTION_KEY = r"regex(fboss.agent.eth.*congestion.*sum.60),filter(.*out_congestion_discards.sum.*)"


def _ndp_clear_disrupt_postchecks(spray_hosts, skip_ssh):
    """Characterized disrupt-window contract for the persistent NDP clear.

    Data plane: lane 0 (beth0) is ignored on every spray host (its egress is
    immaterial while its GTSW's neighbor cache is wiped) while beth1-3 must keep
    spraying; in_dst_null + in_discard discards are captured (informational) and
    congestion discards must stay 0. The HRT/TAAC control-plane collectors are
    asserted at FULL stable-state strength in the longevity playbook (a neighbor-
    cache wipe must not perturb HRT/prefix convergence).
    """
    ods_entity_desc = ",".join(OBSERVER_GTSWS)
    checks = [
        create_fpf_ods_counter_check(
            entity_desc=ods_entity_desc,
            key_desc=_ODS_IN_DST_NULL_KEY,
            validation_expr=f">= {DISCARD_FLOOR}",
            reduce_desc=_ODS_REDUCE,
            aggregate="max",
            require="any",
            informational=True,
            counter_name="in_dst_null discards (captured)",
            check_id="ndp_clear_ods_in_dst_null",
        ),
        create_fpf_ods_counter_check(
            entity_desc=ods_entity_desc,
            key_desc=_ODS_IN_DISCARD_KEY,
            validation_expr=f">= {DISCARD_FLOOR}",
            reduce_desc=_ODS_REDUCE,
            aggregate="max",
            require="any",
            informational=True,
            counter_name="in_discard discards (captured)",
            check_id="ndp_clear_ods_in_discard",
        ),
        create_fpf_ods_counter_check(
            entity_desc=ods_entity_desc,
            key_desc=_ODS_IN_CONGESTION_KEY,
            validation_expr="<= 0",
            reduce_desc=_ODS_REDUCE,
            counter_name="in_congestion discards (must be 0)",
            check_id="ndp_clear_ods_in_congestion",
        ),
        create_fpf_ods_counter_check(
            entity_desc=ods_entity_desc,
            key_desc=_ODS_OUT_CONGESTION_KEY,
            validation_expr="<= 0",
            reduce_desc=_ODS_REDUCE,
            counter_name="out_congestion discards (must be 0)",
            check_id="ndp_clear_ods_out_congestion",
        ),
    ]
    if spray_hosts:
        checks.append(
            create_fpf_host_spray_check(
                hosts=spray_hosts,
                min_egress_gbps=SPRAY_FLOOR_GBPS,
                # Lane 0 (beth0) faces the GTSW being NDP-cleared; its egress is
                # immaterial during the disrupt window, so EXCLUDE it entirely
                # (no floor/spread/drain assertion). Only beth1-3 are held to the
                # >75G spray floor. Lane 0 is verified in the longevity playbook.
                excluded_lanes_by_host={
                    NDP_CLEAR_CIRCUIT.z_end_device: [NDP_CLEAR_CIRCUIT.nic_interface]
                },
                window_from_disruption_time=True,
                window_duration_sec=NDP_CLEAR_DURATION_SEC,
                label=(
                    "[ndp-clear] lane0(beth0) ignored (cache wiped); "
                    "lanes1-3 spray >75G"
                ),
                check_id="ndp_clear_host_spray",
            )
        )
    return checks


def create_fpf_tc38_test_config() -> TestConfig:
    skip_ssh = skip_ssh_dependencies()
    skip_ib = skip_ib_traffic()
    ib_setup, ib_teardown = fpf_ib_traffic_tasks(
        skip_ssh, skip_ib, traffic_config=IB_TRAFFIC_CONFIG
    )
    spray = (
        None
        if skip_ssh or skip_ib
        else [IB_TRAFFIC_CONFIG["server"], *IB_TRAFFIC_CONFIG["clients"]]
    )

    # Disrupt-window playbook: record the disruption moment, run the sustained
    # NDP clear on the observer GTSW, settle, then assert the CHARACTERIZED
    # data-plane-impact contract across the window (lane0 ignored + discards +
    # congestion==0). The control-plane HRT/TAAC collectors are held to full
    # stable-state strength in the longevity playbook below.
    disrupt_playbook = create_fpf_disrupt_window_playbook(
        playbook_name="fpf_tc38_persistent_ndp_clear_disrupt",
        disruption_steps=[
            create_fpf_record_disruption_time_step(
                description="Record NDP-clear disruption time (anchors spray window)"
            ),
            create_fpf_ndp_clear_loop_step(
                target_interface=NDP_CLEAR_CIRCUIT.a_end_interface,
                neighbor_host=NDP_CLEAR_CIRCUIT.z_end_device,
                every_sec=NDP_CLEAR_EVERY_SEC,
                duration_sec=NDP_CLEAR_DURATION_SEC,
                device_regexes=[OBSERVER_GTSWS[0]],
                description=(
                    f"Persistent NDP clear every {NDP_CLEAR_EVERY_SEC}s for "
                    f"{NDP_CLEAR_DURATION_SEC}s on {OBSERVER_GTSWS[0]} "
                    f"(ports stay UP)"
                ),
            ),
            create_longevity_step(
                duration=SETTLE_AFTER_CLEAR_SEC,
                description=(
                    f"Settle {SETTLE_AFTER_CLEAR_SEC}s after the NDP-clear loop "
                    f"before the stable-state window"
                ),
            ),
        ],
        postchecks=_ndp_clear_disrupt_postchecks(spray, skip_ssh),
        spray_hosts=spray,
        ib_traffic_config=IB_TRAFFIC_CONFIG if spray else None,
    )

    # Stable-state v2 longevity: PROVISIONAL — all HCs assert the converged
    # steady state, anchored at this playbook's start (post-clear).
    stable_playbook = create_fpf_hardening_playbook_v2(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        soak_duration_sec=LONGEVITY_SEC,
        stabilization_delay_sec=STABILIZATION_DELAY_SEC,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        playbook_name="fpf_tc38_persistent_ndp_clear_stable",
        prod_prefixes=PROD_PREFIXES,
        prod_prefixes_by_host=PROD_PREFIXES_BY_HOST,
        skip_ssh_dependent_checks=skip_ssh,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
        ib_traffic_config=IB_TRAFFIC_CONFIG if spray else None,
        # Check all 8 injected lanes (not just the default [0,1]).
        lanes=INJECTED_LANES,
        # Prefixes injected once by the setup task (8-STSW split-per-VF).
        skip_injection=True,
        rf_vf_groups=RF_VF_GROUPS,
        hrt_device_ids=HRT_DEVICE_IDS,
        recovered_baseline_qualification_sec=120,
    )

    setup_tasks = [*ib_setup]
    teardown_tasks = [*ib_teardown]
    setup_tasks.append(
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
            rf_vf_groups=RF_VF_GROUPS,
        )
    )
    # Inject the two VF prefix groups on all 8 STSWs once (after collectors
    # start), persisting across both the disrupt-window and stable playbooks.
    setup_tasks.append(
        create_fpf_inject_vf_groups_task(
            groups=INJECTION_GROUPS,
            settle_sec=INJECT_SETTLE_SEC,
        )
    )
    teardown_tasks.append(create_fpf_withdraw_vf_groups_task(groups=INJECTION_GROUPS))
    # Robust catch-all: restart bgpd on all 8 STSWs to clear injected + any
    # leftover prefixes (reloads persistent config).
    teardown_tasks.append(
        create_fpf_restart_service_task(devices=ALL_STSWS, service="BGP")
    )
    teardown_tasks.append(
        create_fpf_stop_collectors_task(
            trigger_stsws=TRIGGER_STSWS,
            withdraw=False,
            community_list=DEFAULT_COMMUNITY_LIST,
        )
    )

    return TestConfig(
        name="fpf_tc38_persistent_ndp_clear",
        endpoints=create_fpf_endpoints(stsws=ALL_STSWS),
        setup_tasks=setup_tasks,
        teardown_tasks=teardown_tasks,
        playbooks=[disrupt_playbook, stable_playbook],
        tags=["fpf"],
    )


TEST_CONFIG = create_fpf_tc38_test_config()
