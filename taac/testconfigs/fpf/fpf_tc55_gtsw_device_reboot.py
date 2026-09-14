# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

"""TC55: full GTSW device reboot (FULL_SYSTEM_REBOOT) on the DUT GTSW.

Reboots the whole DUT GTSW box (gtsw001, which owns lane 0), waits 5 minutes for
it to come back up, then asserts recovery. Unlike tc27 (agent coldboot, which
only restarts wedge_agent with the cold-boot file), this power-cycles the entire
switch.

Two-playbook structure (per design):
  Playbook 1 (DISRUPT): inject + stabilize + record + REBOOT + 5-min come-up,
    then assert the disrupted-state contract. The reboot churns every per-lane
    HRT/RDMA collector on lane 0 for the whole window, so the disrupt postchecks
    reuse the SAME allowances as the service-kill contract
    (``build_kill_disrupt_postchecks``): the per-lane session-stat + host-spray
    collectors are NOT asserted here, and lane-0 churn is tolerated. The contract
    is modelled on the wedge_agent kill (``killed_service="wedge_agent"``)
    because a full reboot, like a wedge_agent coldboot, takes bgp + ports + every
    service DOWN with a legitimately "unclean" teardown — so bgp-establish,
    port-state, bgp-RIB convergence, and unclean-exit are NOT asserted in this
    churn window; only the service-agnostic safety signals (systemctl minus the
    bounced services, core dumps, HRT mem/driver, ODS congestion) are checked.
  Playbook 2 (RECOVERY UNDRAIN, strict): explicitly undrains the rebooted GTSW,
    verifies the readback, settles, restores RDMA if it collapsed, then requires
    full sessions/routes/traffic and every port that was UP before reboot.

DESIGN NOTES (to validate/tune on the first hardware run):
  - ``create_system_reboot_step`` does not carry an explicit device target; the
    runner scopes it via the playbook/endpoints. VERIFY it targets only the DUT
    GTSW before the first hardware run.

NOTE: this config is BUILD-validated only; it has NOT been run on hardware.

Usage:
  buck2 run neteng/netcastle:netcastle_taac -- \\
    --team taac --test-config fpf_tc55_gtsw_device_reboot \\
    --dev --skip-basset-reservation --skip-testbed-isolation \\
    --debug --continue-on-precheck-failure --skip-fboss-rsyslog
"""

from taac.health_checks.healthcheck_definitions import (
    create_drain_state_check,
    create_fpf_host_spray_check,
)
from taac.libs.fpf.fpf_prod_prefix_map import get_prefix
from taac.playbooks.playbook_definitions import (
    create_fpf_disrupt_window_playbook,
    create_fpf_hardening_playbook_v2,
)
from taac.steps.step_definitions import (
    create_fpf_drain_interface_step,
    create_fpf_record_disruption_time_step,
    create_fpf_up_port_baseline_step,
    create_fpf_verify_disruption_step,
    create_longevity_step,
    create_system_reboot_step,
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
    TRIGGER_STSWS,
    VF_COLLECTOR_SUBNET,
    VF_GROUP_PREFIX_COUNT,
)
from taac.testconfigs.fpf.fpf_kill_contract import (
    build_kill_disrupt_postchecks,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import TestConfig

# 8-plane VF-group injection (VF1 5000:dd on s001-s004 = planes 0-3, VF2 5000:ee
# on s005-s008 = planes 4-7); injected once by the setup task, withdrawn in
# teardown, so the longevity playbook passes skip_injection=True.
INJECTION_GROUPS = fpf_vf_injection_groups()
PREFIX_COUNT = VF_GROUP_PREFIX_COUNT
INJECTED_LANES = fpf_hrt_lanes()
HRT_DEVICE_IDS = fpf_hrt_device_ids()
HRT_VF_DEVICE_IDS = fpf_hrt_vf_device_ids(HRT_DEVICE_IDS)
RF_VF_GROUPS = fpf_rf_vf_groups(
    active_lanes=INJECTED_LANES,
    device_ids_by_vf=(HRT_VF_DEVICE_IDS if HRT_DEVICE_IDS != [0] else None),
)
IB_TRAFFIC_CONFIG = fpf_ib_traffic_config()
INJECT_SETTLE_SEC = 300
STABILIZATION_DELAY_SEC = 120
REBOOT_COMEUP_SEC = 300  # 5 min for the box to reboot + rejoin the fabric
LONGEVITY_SOAK_SEC = 300
LONGEVITY_SETTLE_SEC = 120
RECOVERED_BASELINE_QUALIFICATION_SEC = 120
UP_PORT_BASELINE_KEY = "tc55_pre_reboot_up_ports"
SESSION_LOOKBACK_SEC = 1000

# A full reboot takes bgp + ports + every service DOWN with an unclean teardown,
# exactly like the wedge_agent coldboot — so the disrupt window uses the
# wedge_agent kill contract (no bgp/ports/unclean-exit asserts mid-churn). Full
# recovery is verified in the strict longevity playbook. lane 0 = gtsw001.
REBOOT_CONTRACT_SERVICE = "wedge_agent"

PROD_PREFIX_HOST = GPU_HOSTS[0]
PROD_PREFIX_DEVICE_ID = 0
PROD_PREFIXES = [get_prefix(PROD_PREFIX_HOST, PROD_PREFIX_DEVICE_ID)]
PROD_PREFIXES_BY_HOST = {host: PROD_PREFIXES for host in GPU_HOSTS}


def create_fpf_tc55_test_config() -> TestConfig:
    skip_ssh = skip_ssh_dependencies()
    skip_ib = skip_ib_traffic()
    ib_setup, ib_teardown = fpf_ib_traffic_tasks(
        skip_ssh, skip_ib, traffic_config=IB_TRAFFIC_CONFIG
    )
    spray = None if skip_ssh or skip_ib else SPRAY_HOSTS

    # Prefixes are injected once by the setup task (8-plane VF groups), so the
    # disrupt window only stabilizes/records/reboots/comes-up.
    disrupt_steps = [
        create_fpf_up_port_baseline_step(
            action="capture",
            devices=[OBSERVER_GTSWS[0]],
            baseline_key=UP_PORT_BASELINE_KEY,
            device_regexes=[OBSERVER_GTSWS[0]],
        ),
        create_longevity_step(
            duration=STABILIZATION_DELAY_SEC,
            description=f"Stabilize {STABILIZATION_DELAY_SEC}s before the reboot",
        ),
        create_fpf_record_disruption_time_step(
            description="Record GTSW reboot disruption time"
        ),
        create_system_reboot_step(
            trigger=taac_types.SystemRebootTrigger.FULL_SYSTEM_REBOOT,
            description="FULL_SYSTEM_REBOOT of the DUT GTSW",
            device_regexes=[OBSERVER_GTSWS[0]],
        ),
        create_longevity_step(
            duration=REBOOT_COMEUP_SEC,
            description=f"Wait {REBOOT_COMEUP_SEC}s for the GTSW to come back up",
        ),
    ]

    disrupt_postchecks = build_kill_disrupt_postchecks(
        killed_service=REBOOT_CONTRACT_SERVICE,
        observer_gtsws=OBSERVER_GTSWS,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
        kill_duration_sec=REBOOT_COMEUP_SEC,
        prefix_count=PREFIX_COUNT,
        skip_ssh=skip_ssh,
        expected_fsdb_total=EXPECTED_FSDB_SESSION_COUNT,
        session_lookback_sec=SESSION_LOOKBACK_SEC,
    )
    disrupt_postchecks.append(
        create_drain_state_check(
            expected_drained=True,
            device_name=OBSERVER_GTSWS[0],
            check_id="gtsw_reboot_drained_state",
        )
    )
    if spray:
        disrupt_postchecks.append(
            create_fpf_host_spray_check(
                hosts=spray,
                impacted_lanes_by_host={host: ["beth0"] for host in spray},
                impacted_max_gbps=10.0,
                window_from_disruption_time=True,
                check_id="gtsw_reboot_drained_traffic",
            )
        )

    disrupt_playbook = create_fpf_disrupt_window_playbook(
        playbook_name="fpf_tc55_gtsw_device_reboot_disrupt",
        disruption_steps=disrupt_steps,
        spray_hosts=spray,
        ib_traffic_config=IB_TRAFFIC_CONFIG if spray else None,
        postchecks=disrupt_postchecks,
    )

    longevity_playbook = create_fpf_hardening_playbook_v2(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        disruption_steps=[
            create_fpf_drain_interface_step(
                interfaces=[],
                drain=False,
                target_device=OBSERVER_GTSWS[0],
                description="Undrain the rebooted GTSW before recovery",
            ),
            create_fpf_verify_disruption_step(
                interfaces=[],
                mode="device_drain",
                expect_drained=False,
                fail_if_ineffective=True,
                target_device=OBSERVER_GTSWS[0],
                description="Fail-closed readback: rebooted GTSW is undrained",
            ),
            create_longevity_step(
                duration=LONGEVITY_SETTLE_SEC,
                description="Settle after undraining the rebooted GTSW",
            ),
        ],
        soak_duration_sec=0,
        stabilization_delay_sec=0,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        playbook_name="fpf_tc55_gtsw_device_reboot_recovery_undrain",
        prod_prefixes=PROD_PREFIXES,
        prod_prefixes_by_host=PROD_PREFIXES_BY_HOST,
        skip_ssh_dependent_checks=skip_ssh,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
        convergence_settle_sec=LONGEVITY_SETTLE_SEC,
        # 8-plane: prefixes injected once by the setup task; check all 8 lanes.
        skip_injection=True,
        rf_vf_groups=RF_VF_GROUPS,
        hrt_device_ids=HRT_DEVICE_IDS,
        ib_traffic_config=IB_TRAFFIC_CONFIG if spray else None,
        lanes=INJECTED_LANES,
        recovered_baseline_qualification_sec=RECOVERED_BASELINE_QUALIFICATION_SEC,
        final_validation_steps=[
            create_longevity_step(
                duration=LONGEVITY_SOAK_SEC,
                description="Strict stable-state soak after reboot undrain recovery",
            ),
            create_fpf_up_port_baseline_step(
                action="verify",
                devices=[OBSERVER_GTSWS[0]],
                baseline_key=UP_PORT_BASELINE_KEY,
                device_regexes=[OBSERVER_GTSWS[0]],
            ),
        ],
    )

    return TestConfig(
        name="fpf_tc55_gtsw_device_reboot",
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
                enable_fsdb_session_collector=True,
                fsdb_session_hosts=GPU_HOSTS,
                fsdb_session_expected=EXPECTED_FSDB_SESSION_COUNT,
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
        playbooks=[disrupt_playbook, longevity_playbook],
        tags=["fpf"],
    )


TEST_CONFIG = create_fpf_tc55_test_config()
