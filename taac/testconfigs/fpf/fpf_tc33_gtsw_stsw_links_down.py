# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""TC33: All 36 GTSW-STSW Links Down (scaled rapid-flap stability test).

Rapidly flaps the GTSW->STSW UPLINK interfaces on the DUT GTSW for a sustained
window, then validates that the steady state recovers cleanly. GTSW<->STSW link
flaps churn the GTSW's FSDB ribMap (BGP path churn on the spine side) WITHOUT
changing the VF prefix set, so on the GPU/HRT side this should be a non-event
(HRT updates its local ribMap copy but does NOT prog/unprog DOCA). The scaled
window (15 min rapid flaps + 5 min longevity) exercises the same churn path as
the full "36 links down" plan within a normal test slot.

Two-playbook phase-correct pattern:
  1. Disrupt playbook captures the exact pre-test UP-port set, rapidly flaps the
     uplinks for 900s, settles 120s, and checks only non-traffic safety signals.
  2. Longevity playbook restores RDMA if it collapsed, qualifies the recovered
     state for 120s, soaks for 300s, and requires every captured port to be UP.

Uplink interface selection (runtime LLDP):
  Uses ``create_fpf_rapid_flap_step_lldp`` so the GTSW->STSW uplink set is
  resolved at step run time from LLDP on the DUT GTSW, matching the remote
  system name against the STSW pattern (``UPLINK_NEIGHBOR_PATTERN``, fnmatch
  glob — defaults to ``"stsw*"``). No hardcoded eth1/41/* breakouts here, so
  the full 36x400G GTSW-STSW fabric is exercised as the testbed exposes it.

Usage:
  buck2 run neteng/netcastle:netcastle_taac -- \\
    --team taac --test-config fpf_tc33_gtsw_stsw_links_down \\
    --dev --skip-basset-reservation --skip-testbed-isolation \\
    --debug --continue-on-precheck-failure --skip-fboss-rsyslog
"""

from taac.libs.fpf.fpf_prod_prefix_map import get_prefix
from taac.playbooks.playbook_definitions import (
    create_fpf_disrupt_window_playbook,
    create_fpf_hardening_playbook_v2,
)
from taac.steps.step_definitions import (
    create_fpf_rapid_flap_step_lldp,
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
# Scaled flap window (15 min) compressed to a normal slot.
FLAP_DURATION_SEC = 900
FLAP_INTERVAL_SEC = 1
RECOVERED_BASELINE_LOOKBACK_SEC = 120
# Strict stable-state soak after the recovered-state qualification.
LONGEVITY_SEC = 300
DISRUPT_SETTLE_SEC = 120
UP_PORT_BASELINE_KEY = "tc33_pre_disruption_up_ports"

DUT_GTSW = OBSERVER_GTSWS[0]

# GTSW->STSW uplink neighbor pattern (fnmatch glob over LLDP remote system
# name). The rapid-flap step resolves the actual eth1/* uplink breakout list at
# run time by reading LLDP on DUT_GTSW and picking interfaces whose neighbor
# matches this glob. ``stsw*`` covers all spine neighbors.
UPLINK_NEIGHBOR_PATTERN = "stsw*"

PROD_PREFIX_HOST = GPU_HOSTS[0]
PROD_PREFIX_DEVICE_ID = 0
PROD_PREFIXES = [get_prefix(PROD_PREFIX_HOST, PROD_PREFIX_DEVICE_ID)]
PROD_PREFIXES_BY_HOST = {host: PROD_PREFIXES for host in GPU_HOSTS}


def create_fpf_tc33_test_config() -> TestConfig:
    skip_ssh = skip_ssh_dependencies()
    skip_ib = skip_ib_traffic()
    ib_setup, ib_teardown = fpf_ib_traffic_tasks(
        skip_ssh, skip_ib, traffic_config=IB_TRAFFIC_CONFIG
    )
    spray = None if skip_ssh or skip_ib else SPRAY_HOSTS

    disrupt_playbook = create_fpf_disrupt_window_playbook(
        postchecks=build_flap_disrupt_postchecks(
            observer_gtsws=OBSERVER_GTSWS,
            hrt_memory_hosts=HRT_MEMORY_HOSTS,
            prefix_count=PREFIX_COUNT,
            skip_ssh=skip_ssh,
            include_route_convergence=False,
        ),
        disruption_steps=[
            create_fpf_up_port_baseline_step(
                action="capture",
                devices=[DUT_GTSW],
                baseline_key=UP_PORT_BASELINE_KEY,
                device_regexes=[DUT_GTSW],
            ),
            create_fpf_rapid_flap_step_lldp(
                # tc33 intentionally flaps ALL gtsw001 STSW uplinks (the
                # spine-side glob is the desired scope). Now wall-clock bound +
                # 6s down-time per flap so the soak stops on time.
                neighbor_pattern=UPLINK_NEIGHBOR_PATTERN,
                duration_sec=FLAP_DURATION_SEC,
                flap_interval_sec=FLAP_INTERVAL_SEC,
                # Symmetric cycle: enable -> 6s up -> disable -> 6s down.
                flap_down_time_sec=6,
                flap_up_time_sec=6,
                device_regexes=[DUT_GTSW],
                description=(
                    f"Rapid-flap ALL LLDP-resolved GTSW-STSW uplinks "
                    f"(neighbors~={UPLINK_NEIGHBOR_PATTERN!r}) on {DUT_GTSW} "
                    f"for {FLAP_DURATION_SEC}s (wall-clock bound)"
                ),
            ),
            create_longevity_step(
                duration=DISRUPT_SETTLE_SEC,
                description=f"Settle {DISRUPT_SETTLE_SEC}s after uplink flaps stop",
            ),
        ],
        playbook_name="fpf_tc33_gtsw_stsw_links_down_disrupt",
    )

    longevity_playbook = create_fpf_hardening_playbook_v2(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=ALL_STSWS,
        soak_duration_sec=LONGEVITY_SEC,
        stabilization_delay_sec=0,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        playbook_name="fpf_tc33_gtsw_stsw_links_down_longevity",
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
        recovered_baseline_qualification_sec=120,
        final_validation_steps=[
            create_fpf_up_port_baseline_step(
                action="verify",
                devices=[DUT_GTSW],
                baseline_key=UP_PORT_BASELINE_KEY,
                device_regexes=[DUT_GTSW],
            )
        ],
    )

    return TestConfig(
        name="fpf_tc33_gtsw_stsw_links_down",
        endpoints=create_fpf_endpoints(stsws=ALL_STSWS),
        setup_tasks=[
            *ib_setup,
            create_fpf_start_collectors_task(
                gtsws=OBSERVER_GTSWS,
                hosts=GPU_HOSTS,
                hrt_device_ids=HRT_DEVICE_IDS,
                hrt_plane_ids=INJECTED_LANES,
                fsdb_session_hosts=GPU_HOSTS,
                subnet_prefix=VF_COLLECTOR_SUBNET,
                prod_prefixes_by_host=PROD_PREFIXES_BY_HOST,
                prod_prefix_device_id=PROD_PREFIX_DEVICE_ID,
                fsdb_mode=FSDB_COLLECTOR_MODE,
                allow_baseline_failures=ALLOW_BASELINE_FAILURES,
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
        playbooks=[disrupt_playbook, longevity_playbook],
        tags=["fpf"],
    )


TEST_CONFIG = create_fpf_tc33_test_config()
