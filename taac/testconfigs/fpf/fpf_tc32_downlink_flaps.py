# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""TC32: All Downlink Flaps on GTSW (scaled "1hr" rapid-flap stability test).

Rapidly flaps the exact four GTSW->GPU downlinks from the DUT GTSW to the
configured traffic-server host for a sustained window, then validates that the
steady state recovers cleanly. The
original test plan calls for a 1-hour flap soak; this config runs a SCALED
version (15 min rapid flaps + 5 min longevity) so it fits a normal test slot
while still exercising the same churn path (continuous FSDB ribMap updates and
DOCA prog/unprog on the GPU side).

Two-playbook "longevity-anchored health check" pattern:
  1. Disruption-only playbook (NO checks): step1 rapid-flaps the downlinks for
     900s, step2 settles for a 300s longevity window.
  2. Stable-state v2 hardening playbook (soak 300s, no disruption steps): the
     TaacRunner stamps a FRESH test_case_start_time at the start of THIS
     playbook, so every stable-state health check (prod-prefix, HRT mem/driver,
     host-spray, convergence/session) anchors its query window at LONGEVITY
     START with the SAME stable-state expectations as fpf_stress_test_config.
     The noisy flap window is excluded.

Downlink interface selection (runtime LLDP):
  Uses ``create_fpf_rapid_flap_step_lldp`` so the GTSW->GPU downlink set is
  resolved at step run time by enumerating LLDP neighbors on the DUT GTSW and
  matching the remote system name against the exact configured GPU host. TC32
  requires the exact four-interface bundle anchored by the environment-aware
  GPU0 circuit and fails before disruption if LLDP returns a different scope.

Usage:
  buck2 run neteng/netcastle:netcastle_taac -- \\
    --team taac --test-config fpf_tc32_downlink_flaps \\
    --dev --skip-basset-reservation --skip-testbed-isolation \\
    --debug --continue-on-precheck-failure --skip-fboss-rsyslog
"""

from taac.libs.fpf.fpf_prod_prefix_map import get_prefix
from taac.playbooks.playbook_definitions import (
    create_fpf_disruption_only_playbook,
    create_fpf_hardening_playbook_v2,
)
from taac.steps.step_definitions import (
    create_fpf_rapid_flap_step_lldp,
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
from taac.test_as_a_config.types import TestConfig

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
# Scaled flap window (15 min) — the "1hr" plan compressed to a normal slot.
FLAP_DURATION_SEC = 900
FLAP_INTERVAL_SEC = 1
# Longevity window after flaps stop; stable-state checks anchor at its start.
LONGEVITY_SEC = 300

DUT_GTSW = OBSERVER_GTSWS[0]
FLAP_HOST = GPU_HOSTS[0]

PROD_PREFIX_HOST = GPU_HOSTS[0]
PROD_PREFIX_DEVICE_ID = 0
PROD_PREFIXES = [get_prefix(PROD_PREFIX_HOST, PROD_PREFIX_DEVICE_ID)]


def create_fpf_tc32_test_config() -> TestConfig:
    # Resolve environment-dependent topology inside the factory so repeated
    # construction cannot reuse a stale import-time interface/recovery map.
    flap_interfaces = fpf_gpu_downlink_interfaces()
    nic_recovery_by_interface = fpf_nic_recovery_by_interface(
        gtsw=DUT_GTSW,
        host=FLAP_HOST,
        interfaces=flap_interfaces,
    )
    skip_ssh = skip_ssh_dependencies()
    skip_ib = skip_ib_traffic()
    ib_setup, ib_teardown = fpf_ib_traffic_tasks(
        skip_ssh,
        skip_ib,
        traffic_config=IB_TRAFFIC_CONFIG,
    )
    spray = None if skip_ssh or skip_ib else SPRAY_HOSTS

    disrupt_playbook = create_fpf_disruption_only_playbook(
        gtsws=ALL_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=ALL_STSWS,
        disruption_steps=[
            create_fpf_rapid_flap_step_lldp(
                # Scope precisely to the configured GPU hosts (exact match);
                # exact host selector prevents flapping ALL 132 downlinks (the tc32
                # 36h-hang root cause) — only rtptest1544/rtptest1575 are
                # flapped.
                neighbor_hosts=[FLAP_HOST],
                duration_sec=FLAP_DURATION_SEC,
                flap_interval_sec=FLAP_INTERVAL_SEC,
                # Symmetric cycle: enable -> 6s up -> disable -> 6s down.
                flap_down_time_sec=6,
                flap_up_time_sec=6,
                fail_closed=True,
                expected_interfaces=flap_interfaces,
                require_exact_neighbor_hosts=True,
                nic_recovery_by_interface=nic_recovery_by_interface,
                device_regexes=[DUT_GTSW],
                description=(
                    f"Rapid-flap exact LLDP circuits {DUT_GTSW} "
                    f"{flap_interfaces} -> {FLAP_HOST} for "
                    f"{FLAP_DURATION_SEC}s (wall-clock bound)"
                ),
            ),
            create_longevity_step(
                duration=LONGEVITY_SEC,
                description=f"Settle {LONGEVITY_SEC}s after downlink flaps stop",
            ),
        ],
        playbook_name="fpf_tc32_downlink_flaps_disrupt",
    )

    # Stable-state longevity playbook: same expectations as the stress config.
    # All HCs anchor at this playbook's (longevity) start time.
    longevity_playbook = create_fpf_hardening_playbook_v2(
        gtsws=ALL_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=ALL_STSWS,
        soak_duration_sec=LONGEVITY_SEC,
        stabilization_delay_sec=0,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        playbook_name="fpf_tc32_downlink_flaps_longevity",
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
        name="fpf_tc32_downlink_flaps",
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


TEST_CONFIG = create_fpf_tc32_test_config()
