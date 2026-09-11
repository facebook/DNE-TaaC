# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""TC35: Cascaded STSW Plane Drain + GTSW Device Drain — case 2 (UNDRAIN).

Undrains an STSW plane via the on-box LOCAL_DRAINER, then re-injects the FPF
prefixes on the trigger STSWs (undrain always re-injects; the base community
list is used with NO drain-marker, so the plane returns to fully preferred).
After a 5-minute longevity settle, the steady state is validated against the
ordinary STABLE-STATE expectation contract (same as fpf_stress_test_config):
the previously-drained plane is fully reachable again, all sessions up, no loss.

Two-playbook "longevity-anchored health check" pattern:
  1. Disruption-only playbook (NO checks): the STSW undrain+reinject step pair,
     then a 300s longevity settle.
  2. Stable-state v2 hardening playbook (soak 300s): every stable-state health
     check anchors at LONGEVITY START with the SAME stable-state expectations as
     fpf_stress_test_config (no drain-specific plane/recovery knobs — by undrain
     end the fabric is back to baseline).

ASSUMPTIONS (documented):
  - On undrain, create_fpf_stsw_drain_and_reinject_steps re-injects with the
    base community_list and ignores any drain_community, so none is passed here.

Usage:
  buck2 run neteng/netcastle:netcastle_taac -- \\
    --team taac --test-config fpf_tc35_stsw_undrain_reinject \\
    --dev --skip-basset-reservation --skip-testbed-isolation \\
    --debug --continue-on-precheck-failure --skip-fboss-rsyslog
"""

from taac.libs.fpf.fpf_prod_prefix_map import get_prefix
from taac.playbooks.playbook_definitions import (
    create_fpf_disruption_only_playbook,
    create_fpf_hardening_playbook_v2,
)
from taac.steps.step_definitions import (
    create_fpf_stsw_drain_and_reinject_steps,
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
from taac.test_as_a_config.types import TestConfig

# 8-plane VF-group injection (VF1 5000:dd on s001-s004 = planes 0-3, VF2 5000:ee
# on s005-s008 = planes 4-7), injected once by the setup task and withdrawn in
# teardown. The undrain step below re-injects the same per-group count
# (VF_GROUP_PREFIX_COUNT) across all 8 STSWs with the base community.
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
TRIGGER_STSWS = ALL_STSWS
LONGEVITY_SEC = 300

# STSW plane to undrain (the first STSW plane: stsw001.s001.l202.mwg2).
UNDRAIN_TARGET_STSW = TRIGGER_STSWS[0]

PROD_PREFIX_HOST = GPU_HOSTS[0]
PROD_PREFIX_DEVICE_ID = 0
PROD_PREFIXES = [get_prefix(PROD_PREFIX_HOST, PROD_PREFIX_DEVICE_ID)]
PROD_PREFIXES_BY_HOST = {host: PROD_PREFIXES for host in GPU_HOSTS}


def create_fpf_tc35_test_config() -> TestConfig:
    skip_ssh = skip_ssh_dependencies()
    skip_ib = skip_ib_traffic()
    ib_setup, ib_teardown = fpf_ib_traffic_tasks(
        skip_ssh, skip_ib, traffic_config=IB_TRAFFIC_CONFIG
    )
    spray = None if skip_ssh or skip_ib else SPRAY_HOSTS

    disrupt_steps = [
        *create_fpf_stsw_drain_and_reinject_steps(
            stsw=UNDRAIN_TARGET_STSW,
            drained=False,
            trigger_stsws=TRIGGER_STSWS,
            prefix_count=PREFIX_COUNT,
            community_list=DEFAULT_COMMUNITY_LIST,
            injection_groups=INJECTION_GROUPS,
        ),
        create_longevity_step(
            duration=LONGEVITY_SEC,
            description=(
                f"Settle {LONGEVITY_SEC}s after STSW {UNDRAIN_TARGET_STSW} "
                "undrain + reinject"
            ),
        ),
    ]

    disrupt_playbook = create_fpf_disruption_only_playbook(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        disruption_steps=disrupt_steps,
        playbook_name="fpf_tc35_stsw_undrain_reinject_disrupt",
    )

    # Stable-state longevity playbook: same expectations as the stress config.
    longevity_playbook = create_fpf_hardening_playbook_v2(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        soak_duration_sec=LONGEVITY_SEC,
        stabilization_delay_sec=0,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        playbook_name="fpf_tc35_stsw_undrain_reinject_longevity",
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
        # Prefixes injected once by the setup task (8-STSW split-per-VF); the
        # undrain step re-injects them with the base community.
        skip_injection=True,
        rf_vf_groups=RF_VF_GROUPS,
        hrt_device_ids=HRT_DEVICE_IDS,
    )

    return TestConfig(
        name="fpf_tc35_stsw_undrain_reinject",
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
                rf_vf_groups=RF_VF_GROUPS,
            ),
            create_fpf_inject_vf_groups_task(
                groups=INJECTION_GROUPS,
                settle_sec=INJECT_SETTLE_SEC,
            ),
        ],
        teardown_tasks=[
            create_fpf_withdraw_vf_groups_task(groups=INJECTION_GROUPS),
            # Robust catch-all: restart bgpd on all 8 STSWs to clear injected +
            # any leftover prefixes (reloads persistent config).
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


TEST_CONFIG = create_fpf_tc35_test_config()
