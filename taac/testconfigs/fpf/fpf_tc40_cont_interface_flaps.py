# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""TC40: Continuous interface flaps across ALL 8 GTSWs facing one GPU host.

Picks ONE rtptest GPU host (GPU_HOSTS[0]) and, on every one of the 8 GTSWs that
host connects to (gtsw001-008.l1002.c087.mwg2), resolves the local interfaces
facing that host via LLDP and rapidly flaps them. All 8 GTSWs flap IN PARALLEL
(asyncio.gather inside one custom step) with a 7s up / 7s down symmetric cycle,
for 15 minutes — maximum cross-plane chaos on the chosen host. After the flaps
stop, a stable-state longevity playbook (same expectations as
fpf_stress_test_config) validates full recovery.

Two-playbook "longevity-anchored health check" pattern:
  1. Disruption-only playbook (NO checks): the multi-GTSW parallel flap (900s),
     then a 300s longevity settle.
  2. Stable-state v2 hardening playbook (soak 300s): every stable-state health
     check anchors at LONGEVITY START with the SAME expectations as the stress
     config; the noisy flap window is excluded.

Usage:
  TAAC_SSH_VIA_LAB_SSH=1 buck2 run neteng/netcastle:netcastle_taac -- \\
    --team taac --test-config fpf_tc40_cont_interface_flaps \\
    --dev --skip-basset-reservation --skip-testbed-isolation \\
    --debug --continue-on-precheck-failure --skip-fboss-rsyslog
"""

from taac.libs.fpf.fpf_prod_prefix_map import get_prefix
from taac.playbooks.playbook_definitions import (
    create_fpf_disrupt_window_playbook,
    create_fpf_hardening_playbook_v2,
)
from taac.steps.step_definitions import (
    create_fpf_multi_gtsw_rapid_flap_step,
    create_longevity_step,
)
from taac.task_definitions import (
    create_fpf_inject_vf_groups_task,
    create_fpf_restart_service_task,
    create_fpf_start_collectors_task,
    create_fpf_stop_collectors_task,
    create_fpf_withdraw_vf_groups_task,
)
from taac.testconfigs.fpf.fpf_flap_contract import (
    build_flap_disrupt_postchecks,
)
from taac.testconfigs.fpf.fpf_hardening_common import (
    ALL_GTSWS,
    ALL_STSWS,
    ALLOW_BASELINE_FAILURES,
    create_fpf_endpoints,
    DEFAULT_COMMUNITY_LIST,
    EXPECTED_FSDB_SESSION_COUNT,
    fpf_gpu_downlink_interfaces,
    fpf_hrt_device_ids,
    fpf_hrt_lanes,
    fpf_hrt_vf_device_ids,
    fpf_ib_traffic_config,
    fpf_ib_traffic_tasks,
    fpf_nic_recovery_by_interface,
    fpf_rf_vf_groups,
    fpf_vf_injection_groups,
    FSDB_COLLECTOR_MODE,
    GPU_HOSTS,
    HRT_MEMORY_HOSTS,
    skip_ib_traffic,
    skip_ssh_dependencies,
    SPRAY_HOSTS,
    VF_COLLECTOR_SUBNET,
    VF_GROUP_PREFIX_COUNT,
)
from taac.test_as_a_config.types import TestConfig

# The setup advertises both VF groups across all eight STSWs exactly once. With
# the twshared 16x252 environment this is 4,032 prefixes per plane.
INJECTION_GROUPS = fpf_vf_injection_groups()
PREFIX_COUNT = VF_GROUP_PREFIX_COUNT
INJECT_SETTLE_SEC = 120
INJECTED_LANES = fpf_hrt_lanes()
HRT_DEVICE_IDS = fpf_hrt_device_ids()
HRT_VF_DEVICE_IDS = fpf_hrt_vf_device_ids(HRT_DEVICE_IDS)
RF_VF_GROUPS = fpf_rf_vf_groups(
    active_lanes=INJECTED_LANES,
    device_ids_by_vf=(HRT_VF_DEVICE_IDS if HRT_DEVICE_IDS != [0] else None),
)
IB_TRAFFIC_CONFIG = fpf_ib_traffic_config()
# 15-min flap window with a symmetric 7s up / 7s down cycle.
FLAP_DURATION_SEC = 900
FLAP_UP_SEC = 7
FLAP_DOWN_SEC = 7
LONGEVITY_SEC = 300
FLAP_HOST = GPU_HOSTS[0]
FLAP_INTERFACES = fpf_gpu_downlink_interfaces()
NIC_RECOVERY_BY_GTSW_INTERFACE = {
    gtsw: fpf_nic_recovery_by_interface(
        gtsw=gtsw,
        host=FLAP_HOST,
        interfaces=FLAP_INTERFACES,
    )
    for gtsw in ALL_GTSWS
}

PROD_PREFIX_HOST = GPU_HOSTS[0]
PROD_PREFIX_DEVICE_ID = 0
PROD_PREFIXES = [get_prefix(PROD_PREFIX_HOST, PROD_PREFIX_DEVICE_ID)]


def create_fpf_tc40_test_config() -> TestConfig:
    skip_ssh = skip_ssh_dependencies()
    skip_ib = skip_ib_traffic()
    ib_setup, ib_teardown = fpf_ib_traffic_tasks(
        skip_ssh,
        skip_ib,
        traffic_config=IB_TRAFFIC_CONFIG,
    )
    spray = None if skip_ssh or skip_ib else SPRAY_HOSTS
    disrupt_playbook = create_fpf_disrupt_window_playbook(
        postchecks=build_flap_disrupt_postchecks(
            observer_gtsws=ALL_GTSWS,
            hrt_memory_hosts=HRT_MEMORY_HOSTS,
            prefix_count=PREFIX_COUNT,
            skip_ssh=skip_ssh,
        ),
        disruption_steps=[
            create_fpf_multi_gtsw_rapid_flap_step(
                gtsws=ALL_GTSWS,
                neighbor_hosts=[FLAP_HOST],
                duration_sec=FLAP_DURATION_SEC,
                flap_up_time_sec=FLAP_UP_SEC,
                flap_down_time_sec=FLAP_DOWN_SEC,
                fail_closed=True,
                expected_interfaces=FLAP_INTERFACES,
                require_exact_neighbor_hosts=True,
                nic_recovery_by_gtsw_interface=NIC_RECOVERY_BY_GTSW_INTERFACE,
                description=(
                    f"Parallel rapid-flap exact links {FLAP_INTERFACES} facing "
                    f"{FLAP_HOST} across "
                    f"{len(ALL_GTSWS)} GTSWs for {FLAP_DURATION_SEC}s "
                    f"(up={FLAP_UP_SEC}s/down={FLAP_DOWN_SEC}s)"
                ),
            ),
            create_longevity_step(
                duration=LONGEVITY_SEC,
                description=f"Settle {LONGEVITY_SEC}s after flaps stop",
            ),
        ],
        playbook_name="fpf_tc40_cont_interface_flaps_disrupt",
    )

    longevity_playbook = create_fpf_hardening_playbook_v2(
        gtsws=ALL_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=ALL_STSWS,
        soak_duration_sec=LONGEVITY_SEC,
        stabilization_delay_sec=0,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        playbook_name="fpf_tc40_cont_interface_flaps_longevity",
        prod_prefixes=PROD_PREFIXES,
        skip_ssh_dependent_checks=skip_ssh,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
        ib_traffic_config=IB_TRAFFIC_CONFIG if spray else None,
        skip_injection=True,
        rf_vf_groups=RF_VF_GROUPS,
        lanes=INJECTED_LANES,
        hrt_device_ids=HRT_DEVICE_IDS,
    )

    return TestConfig(
        name="fpf_tc40_cont_interface_flaps",
        endpoints=create_fpf_endpoints(stsws=ALL_STSWS),
        setup_tasks=[
            *ib_setup,
            create_fpf_start_collectors_task(
                gtsws=ALL_GTSWS,
                hosts=GPU_HOSTS,
                hrt_device_ids=HRT_DEVICE_IDS,
                hrt_plane_ids=INJECTED_LANES,
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
                trigger_stsws=ALL_STSWS,
                community_list=DEFAULT_COMMUNITY_LIST,
                withdraw=False,
            ),
            *ib_teardown,
        ],
        playbooks=[disrupt_playbook, longevity_playbook],
        tags=["fpf"],
    )


TEST_CONFIG = create_fpf_tc40_test_config()
