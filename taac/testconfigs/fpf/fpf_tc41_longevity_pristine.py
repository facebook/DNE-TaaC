# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""TC41: Pristine longevity (companion baseline for the cont-flap configs).

A PRISTINE control test: no disruption at all. Injects the test prefixes on ALL
8 STSW planes (VF1 5000:dd on planes 0-3, VF2 5000:ee on planes 4-7), brings up
RDMA traffic, lets everything settle, then runs the SAME stable-state longevity
contract (create_fpf_hardening_playbook_v2) used by fpf_stress_test_config and as
the recovery half of the flap configs. Running this clean isolates "is the steady
state healthy on its own" from "did the disruption break it".

Usage:
  TAAC_SSH_VIA_LAB_SSH=1 buck2 run neteng/netcastle:netcastle_taac -- \\
    --team taac --test-config fpf_tc41_longevity_pristine \\
    --dev --skip-basset-reservation --skip-testbed-isolation \\
    --debug --continue-on-precheck-failure --skip-fboss-rsyslog
"""

from taac.libs.fpf.fpf_prod_prefix_map import get_prefix
from taac.playbooks.playbook_definitions import (
    create_fpf_hardening_playbook_v2,
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
# teardown, so the playbook passes skip_injection=True.
INJECTION_GROUPS = fpf_vf_injection_groups()
RF_VF_GROUPS = fpf_rf_vf_groups()
PREFIX_COUNT = VF_GROUP_PREFIX_COUNT
INJECT_SETTLE_SEC = 300
INJECTED_LANES = ALL_LANES
# Bake/stability window then a longevity soak — pristine, no disruption.
STABILIZATION_DELAY_SEC = 300
LONGEVITY_SEC = 300

PROD_PREFIX_HOST = GPU_HOSTS[0]
PROD_PREFIX_DEVICE_ID = 0
# Monitor the prod HRT prefix on BOTH GPU hosts (each host originates its own /64
# VF1 prefix). The collector task starts one prod-prefix + plane-status collector
# per host; FpfProdHrtPrefixStabilityHealthCheck / FpfHrtPlaneStatusHealthCheck
# discover all per-host collectors and assert each host independently.
PROD_PREFIXES_BY_HOST = {
    host: [get_prefix(host, PROD_PREFIX_DEVICE_ID)] for host in GPU_HOSTS
}
# Flattened list retained as the v2-playbook truthiness gate (enables the
# prod-prefix + plane-status postchecks).
PROD_PREFIXES = [pfx for pfxs in PROD_PREFIXES_BY_HOST.values() for pfx in pfxs]


def create_fpf_tc41_test_config() -> TestConfig:
    skip_ssh = skip_ssh_dependencies()
    ib_setup, ib_teardown = fpf_ib_traffic_tasks(skip_ssh)
    spray = None if skip_ssh else SPRAY_HOSTS

    playbook = create_fpf_hardening_playbook_v2(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        soak_duration_sec=LONGEVITY_SEC,
        stabilization_delay_sec=STABILIZATION_DELAY_SEC,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        playbook_name="fpf_tc41_longevity_pristine",
        prod_prefixes=PROD_PREFIXES,
        prod_prefixes_by_host=PROD_PREFIXES_BY_HOST,
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
        name="fpf_tc41_longevity_pristine",
        endpoints=create_fpf_endpoints(stsws=ALL_STSWS),
        setup_tasks=[
            *ib_setup,
            create_fpf_start_collectors_task(
                gtsws=OBSERVER_GTSWS,
                hosts=GPU_HOSTS,
                subnet_prefix=VF_COLLECTOR_SUBNET,
                prod_prefixes_by_host=PROD_PREFIXES_BY_HOST,
                prod_prefix_device_id=PROD_PREFIX_DEVICE_ID,
                fsdb_session_hosts=GPU_HOSTS,
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


TEST_CONFIG = create_fpf_tc41_test_config()
