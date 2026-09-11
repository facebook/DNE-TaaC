# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""TC45: scale both VF groups from 4,000 to 8,000 prefixes per plane."""

from taac.libs.fpf.fpf_prod_prefix_map import get_prefix
from taac.playbooks.playbook_definitions import (
    create_fpf_hardening_playbook_v2,
)
from taac.steps.step_definitions import (
    create_fpf_bgp_prefix_injection_step,
    create_longevity_step,
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
            *_inject_both_vfs(SCALE_LOW, "Scale baseline"),
            create_longevity_step(
                duration=SETTLE_SEC,
                description=f"Settle {SETTLE_SEC}s at {SCALE_LOW} prefixes",
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
