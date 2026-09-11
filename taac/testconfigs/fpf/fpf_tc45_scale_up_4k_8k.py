# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""TC45: scale both VF groups from 4,000 to 8,000 prefixes per plane."""

from taac.health_checks.healthcheck_definitions import (
    create_fpf_bgp_rib_convergence_check,
    create_fpf_fsdb_ribmap_convergence_check,
    create_fpf_host_spray_check,
    create_fpf_hrt_bulk_convergence_check,
    create_fpf_hrt_fsdb_session_check,
    create_fpf_hrt_remote_failure_convergence_check,
)
from taac.libs.fpf.fpf_prod_prefix_map import get_prefix
from taac.libs.fpf.fpf_thresholds import ACTIVE
from taac.playbooks.playbook_definitions import (
    create_fpf_hardening_playbook_v2,
)
from taac.steps.step_definitions import (
    create_fpf_bgp_prefix_injection_step,
    create_fpf_record_mutation_time_step,
    create_longevity_step,
    create_validation_step,
)
from taac.task_definitions import (
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
    FSDB_COLLECTOR_MODE,
    GPU_HOSTS,
    HRT_MEMORY_HOSTS,
    OBSERVER_GTSWS,
    skip_ib_traffic,
    skip_ssh_dependencies,
    SPRAY_HOSTS,
    VF1_PREFIX_BASE,
    VF1_STSWS,
    VF2_PREFIX_BASE,
    VF2_STSWS,
    VF_COLLECTOR_SUBNET,
)
from taac.test_as_a_config.types import TestConfig

SCALE_LOW = 4000
SCALE_HIGH = 8000
SCALE_BATCH_SIZE = 252
SETTLE_SEC = 120
LONGEVITY_SEC = 300
INJECTED_LANES = fpf_hrt_lanes()
HRT_DEVICE_IDS = fpf_hrt_device_ids()
HRT_VF_DEVICE_IDS = fpf_hrt_vf_device_ids(HRT_DEVICE_IDS)
RF_VF_GROUPS = fpf_rf_vf_groups(
    active_lanes=INJECTED_LANES,
    device_ids_by_vf=(HRT_VF_DEVICE_IDS if HRT_DEVICE_IDS != [0] else None),
)
IB_TRAFFIC_CONFIG = fpf_ib_traffic_config()
HIGH_GROUPS = [
    {
        "devices": VF1_STSWS,
        "prefix_base": VF1_PREFIX_BASE,
        "count": SCALE_HIGH,
        "community_list": DEFAULT_COMMUNITY_LIST,
        "batch_size": SCALE_BATCH_SIZE,
    },
    {
        "devices": VF2_STSWS,
        "prefix_base": VF2_PREFIX_BASE,
        "count": SCALE_HIGH,
        "community_list": DEFAULT_COMMUNITY_LIST,
        "batch_size": SCALE_BATCH_SIZE,
    },
]
PROD_PREFIX_HOST = GPU_HOSTS[0]
PROD_PREFIX_DEVICE_ID = 0
PROD_PREFIXES = [get_prefix(PROD_PREFIX_HOST, PROD_PREFIX_DEVICE_ID)]
PROD_PREFIXES_BY_HOST = {host: PROD_PREFIXES for host in GPU_HOSTS}


def _inject_both_vfs(count: int, label: str) -> list:
    return [
        create_fpf_bgp_prefix_injection_step(
            devices=devices,
            prefix_base=prefix_base,
            count=count,
            batch_size=SCALE_BATCH_SIZE,
            community_list=DEFAULT_COMMUNITY_LIST,
            description=f"{label}: {count} prefixes from {prefix_base}",
        )
        for devices, prefix_base in (
            (VF1_STSWS, VF1_PREFIX_BASE),
            (VF2_STSWS, VF2_PREFIX_BASE),
        )
    ]


def _scale_checkpoint_checks(spray_hosts: list[str] | None) -> list:
    """Strict 4K boundary checks before TC45 starts the 8K mutation."""
    checks = []
    for lane_id, gtsw in enumerate(OBSERVER_GTSWS):
        lane_map = {str(lane_id): gtsw}
        checks.extend(
            [
                create_fpf_fsdb_ribmap_convergence_check(
                    lane_map=lane_map,
                    expected_matched=SCALE_LOW,
                    use_live_collectors=True,
                    use_mutation_time=True,
                    require_final_exact=True,
                    signal1_e2e_max_sec=ACTIVE.convergence_signal1_e2e_max_sec,
                    signal2_local_max_sec=ACTIVE.convergence_signal2_local_max_sec,
                    signal3_stability_duration_sec=(
                        ACTIVE.convergence_signal3_stability_duration_sec
                    ),
                    check_id=f"fpf_tc45_4k_fsdb_lane{lane_id}",
                ),
                create_fpf_bgp_rib_convergence_check(
                    lane_map=lane_map,
                    expected_matched=SCALE_LOW,
                    use_live_collectors=True,
                    use_mutation_time=True,
                    require_final_exact=True,
                    signal1_e2e_max_sec=ACTIVE.convergence_signal1_e2e_max_sec,
                    signal2_local_max_sec=ACTIVE.convergence_signal2_local_max_sec,
                    signal3_stability_duration_sec=(
                        ACTIVE.convergence_signal3_stability_duration_sec
                    ),
                    check_id=f"fpf_tc45_4k_bgp_lane{lane_id}",
                ),
            ]
        )
    for lane_id in INJECTED_LANES:
        checks.append(
            create_fpf_hrt_bulk_convergence_check(
                lanes=[lane_id],
                device_ids=HRT_DEVICE_IDS,
                expected_per_lane={str(lane_id): SCALE_LOW},
                use_live_collectors=True,
                use_mutation_time=True,
                require_final_exact=True,
                signal1_e2e_max_sec=ACTIVE.convergence_signal1_e2e_max_sec,
                signal2_local_max_sec=ACTIVE.convergence_signal2_local_max_sec,
                signal3_stability_duration_sec=(
                    ACTIVE.convergence_signal3_stability_duration_sec
                ),
                check_id=f"fpf_tc45_4k_hrt_lane{lane_id}",
            )
        )
    for group in RF_VF_GROUPS:
        group_lanes = [int(lane) for lane in group["lanes"]]
        checks.append(
            create_fpf_hrt_remote_failure_convergence_check(
                lanes=group_lanes,
                device_ids=group.get("device_ids", [0]),
                expected_per_lane={str(lane): 0 for lane in group_lanes},
                direction="scale_recovery",
                use_live_collectors=True,
                use_mutation_time=True,
                collector_name=f"hrt_remote_failure_{group['suffix']}",
                check_id=f"fpf_tc45_4k_remote_failure_{group['suffix']}",
            )
        )
    checks.append(
        create_fpf_hrt_fsdb_session_check(
            hosts=GPU_HOSTS,
            expected_session_count=EXPECTED_FSDB_SESSION_COUNT,
            device_ids=HRT_DEVICE_IDS if HRT_DEVICE_IDS != [0] else None,
            planes_per_device=4 if HRT_DEVICE_IDS != [0] else None,
            check_id="fpf_tc45_4k_hrt_sessions",
        )
    )
    if spray_hosts:
        checks.append(
            create_fpf_host_spray_check(
                hosts=spray_hosts,
                lookback_sec=60,
                check_id="fpf_tc45_4k_traffic",
            )
        )
    return checks


def create_fpf_tc45_test_config() -> TestConfig:
    skip_ssh = skip_ssh_dependencies()
    skip_ib = skip_ib_traffic()
    ib_setup, ib_teardown = fpf_ib_traffic_tasks(
        skip_ssh, skip_ib, traffic_config=IB_TRAFFIC_CONFIG
    )
    spray = None if skip_ssh or skip_ib else SPRAY_HOSTS

    ramp_playbook = create_fpf_hardening_playbook_v2(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=ALL_STSWS,
        soak_duration_sec=0,
        stabilization_delay_sec=0,
        prefix_count=SCALE_HIGH,
        community_list=DEFAULT_COMMUNITY_LIST,
        prod_prefixes=PROD_PREFIXES,
        prod_prefixes_by_host=PROD_PREFIXES_BY_HOST,
        skip_ssh_dependent_checks=skip_ssh,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
        ib_traffic_config=IB_TRAFFIC_CONFIG if spray else None,
        disruption_steps=[
            create_fpf_record_mutation_time_step(
                description="Record TC45 4K scale-baseline mutation time"
            ),
            *_inject_both_vfs(SCALE_LOW, "Scale baseline"),
            create_longevity_step(
                duration=SETTLE_SEC,
                description=f"Settle {SETTLE_SEC}s at {SCALE_LOW} prefixes",
            ),
            create_validation_step(
                point_in_time_checks=_scale_checkpoint_checks(spray),
                description=(
                    "Validate exact 4K device/VF counts, HRT 32/32, RF recovery, "
                    "and live RDMA traffic"
                ),
            ),
            create_fpf_record_mutation_time_step(
                description="Record TC45 4K-to-8K mutation time"
            ),
            *_inject_both_vfs(SCALE_HIGH, "Scale up"),
            create_longevity_step(
                duration=SETTLE_SEC,
                description=f"Settle {SETTLE_SEC}s at {SCALE_HIGH} prefixes",
            ),
        ],
        playbook_name="fpf_tc45_scale_up_4k_8k_disrupt",
        lanes=INJECTED_LANES,
        hrt_device_ids=HRT_DEVICE_IDS,
        skip_injection=True,
        rf_vf_groups=RF_VF_GROUPS,
        prod_prefix_precheck_lookback_sec=SETTLE_SEC,
        scale_mutation_mode=True,
    )
    longevity_playbook = create_fpf_hardening_playbook_v2(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=ALL_STSWS,
        soak_duration_sec=LONGEVITY_SEC,
        stabilization_delay_sec=SETTLE_SEC,
        prefix_count=SCALE_HIGH,
        community_list=DEFAULT_COMMUNITY_LIST,
        playbook_name="fpf_tc45_scale_up_4k_8k_longevity",
        prod_prefixes=PROD_PREFIXES,
        prod_prefixes_by_host=PROD_PREFIXES_BY_HOST,
        skip_ssh_dependent_checks=skip_ssh,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
        ib_traffic_config=IB_TRAFFIC_CONFIG if spray else None,
        lanes=INJECTED_LANES,
        hrt_device_ids=HRT_DEVICE_IDS,
        skip_injection=True,
        rf_vf_groups=RF_VF_GROUPS,
        prod_prefix_precheck_lookback_sec=SETTLE_SEC,
    )
    return TestConfig(
        name="fpf_tc45_scale_up_4k_8k",
        endpoints=create_fpf_endpoints(stsws=ALL_STSWS),
        setup_tasks=[
            create_fpf_withdraw_vf_groups_task(groups=HIGH_GROUPS),
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
                rf_vf_groups=RF_VF_GROUPS,
            ),
        ],
        teardown_tasks=[
            create_fpf_withdraw_vf_groups_task(groups=HIGH_GROUPS),
            create_fpf_restart_service_task(devices=ALL_STSWS, service="BGP"),
            create_fpf_stop_collectors_task(
                trigger_stsws=ALL_STSWS,
                withdraw=False,
                community_list=DEFAULT_COMMUNITY_LIST,
            ),
            *ib_teardown,
        ],
        playbooks=[ramp_playbook, longevity_playbook],
        tags=["fpf"],
    )


TEST_CONFIG = create_fpf_tc45_test_config()
