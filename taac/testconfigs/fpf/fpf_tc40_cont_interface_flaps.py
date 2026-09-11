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
  1. Disrupt playbook captures the exact UP-port set across all eight GTSWs,
     performs the parallel flap for 900s, settles 120s, and evaluates only
     non-traffic safety signals.
  2. Longevity playbook restores RDMA if it collapsed, qualifies recovery for
     120s, soaks for 300s, and requires every captured port to be UP.

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
    create_fpf_up_port_baseline_step,
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
    OBSERVER_GTSWS,
    skip_ib_traffic,
    skip_ssh_dependencies,
    SPRAY_HOSTS,
    VF_COLLECTOR_SUBNET,
    VF_GROUP_PREFIX_COUNT,
)
from taac.test_as_a_config import types as taac_types
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
DISRUPT_SETTLE_SEC = 120
UP_PORT_BASELINE_KEY = "tc40_family_pre_disruption_up_ports"
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


def create_fpf_cont_interface_flaps_test_config(
    *,
    test_name: str,
    flap_duration_sec: int = FLAP_DURATION_SEC,
    churn_service: taac_types.Service | None = None,
    churn_action: str = "restart",
    churn_every_sec: int = 120,
    churn_initial_delay_sec: int = 0,
    churn_recovery_timeout_sec: int = 0,
    retry_final_cleanup_after_churn: bool = False,
    observe_prod_prefix_on_all_hosts: bool = False,
) -> TestConfig:
    """Build TC40's strict contract, optionally with concurrent service churn."""
    skip_ssh = skip_ssh_dependencies()
    skip_ib = skip_ib_traffic()
    ib_setup, ib_teardown = fpf_ib_traffic_tasks(
        skip_ssh,
        skip_ib,
        traffic_config=IB_TRAFFIC_CONFIG,
    )
    spray = None if skip_ssh or skip_ib else SPRAY_HOSTS
    prod_prefixes_by_host = (
        {host: PROD_PREFIXES for host in GPU_HOSTS}
        if observe_prod_prefix_on_all_hosts
        else None
    )
    disrupt_playbook = create_fpf_disrupt_window_playbook(
        postchecks=build_flap_disrupt_postchecks(
            observer_gtsws=ALL_GTSWS,
            hrt_memory_hosts=HRT_MEMORY_HOSTS,
            prefix_count=PREFIX_COUNT,
            skip_ssh=skip_ssh,
            include_route_convergence=False,
        ),
        disruption_steps=[
            create_fpf_up_port_baseline_step(
                action="capture",
                devices=ALL_GTSWS,
                baseline_key=UP_PORT_BASELINE_KEY,
                device_regexes=[OBSERVER_GTSWS[0]],
            ),
            create_fpf_multi_gtsw_rapid_flap_step(
                gtsws=ALL_GTSWS,
                neighbor_hosts=[FLAP_HOST],
                duration_sec=flap_duration_sec,
                flap_up_time_sec=FLAP_UP_SEC,
                flap_down_time_sec=FLAP_DOWN_SEC,
                fail_closed=True,
                expected_interfaces=FLAP_INTERFACES,
                require_exact_neighbor_hosts=True,
                nic_recovery_by_gtsw_interface=NIC_RECOVERY_BY_GTSW_INTERFACE,
                churn_service=churn_service,
                churn_action=churn_action,
                churn_every_sec=churn_every_sec,
                churn_initial_delay_sec=churn_initial_delay_sec,
                churn_recovery_timeout_sec=churn_recovery_timeout_sec,
                churn_devices=ALL_GTSWS if churn_service is not None else None,
                retry_final_cleanup_after_churn=retry_final_cleanup_after_churn,
                description=(
                    f"Parallel rapid-flap exact links {FLAP_INTERFACES} facing "
                    f"{FLAP_HOST} across "
                    f"{len(ALL_GTSWS)} GTSWs for {flap_duration_sec}s "
                    f"(up={FLAP_UP_SEC}s/down={FLAP_DOWN_SEC}s)"
                    + (
                        f" + {churn_action} {churn_service.name} every "
                        f"{churn_every_sec}s"
                        + (
                            f" after an initial {churn_initial_delay_sec}s"
                            if churn_initial_delay_sec > 0
                            else ""
                        )
                        if churn_service is not None
                        else ""
                    )
                ),
            ),
            create_longevity_step(
                duration=DISRUPT_SETTLE_SEC,
                description=f"Settle {DISRUPT_SETTLE_SEC}s after flaps stop",
            ),
        ],
        playbook_name=f"{test_name}_disrupt",
    )

    longevity_playbook = create_fpf_hardening_playbook_v2(
        gtsws=ALL_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=ALL_STSWS,
        soak_duration_sec=LONGEVITY_SEC,
        stabilization_delay_sec=0,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        playbook_name=f"{test_name}_longevity",
        prod_prefixes=PROD_PREFIXES,
        prod_prefix_host=PROD_PREFIX_HOST,
        prod_prefixes_by_host=prod_prefixes_by_host,
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
        recovered_baseline_qualification_sec=120,
        final_validation_steps=[
            create_fpf_up_port_baseline_step(
                action="verify",
                devices=ALL_GTSWS,
                baseline_key=UP_PORT_BASELINE_KEY,
                device_regexes=[OBSERVER_GTSWS[0]],
            )
        ],
    )

    return TestConfig(
        name=test_name,
        endpoints=create_fpf_endpoints(stsws=ALL_STSWS),
        setup_tasks=[
            *ib_setup,
            create_fpf_start_collectors_task(
                gtsws=ALL_GTSWS,
                hosts=GPU_HOSTS,
                hrt_device_ids=HRT_DEVICE_IDS,
                hrt_plane_ids=INJECTED_LANES,
                fsdb_session_hosts=GPU_HOSTS,
                subnet_prefix=VF_COLLECTOR_SUBNET,
                prod_prefixes=(
                    None if observe_prod_prefix_on_all_hosts else PROD_PREFIXES
                ),
                prod_prefixes_by_host=prod_prefixes_by_host,
                prod_prefix_host=(
                    None if observe_prod_prefix_on_all_hosts else PROD_PREFIX_HOST
                ),
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


def create_fpf_tc40_test_config() -> TestConfig:
    return create_fpf_cont_interface_flaps_test_config(
        test_name="fpf_tc40_cont_interface_flaps"
    )


TEST_CONFIG = create_fpf_tc40_test_config()
