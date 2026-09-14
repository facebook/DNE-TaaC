# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

"""TC27: wedge_agent COLD BOOT on the DUT GTSW (disruptive).

A cold boot wipes forwarding state, so unlike a warmboot/restart it IS
disruptive — treated like a link flap. We wait at least 5 minutes after the cold
boot for full recovery, then assert the recovered steady state:
  - BGP RIB: bgp thrift collector null/unresponsive during the boot (tolerated);
    BGP RIB must return to the expected count within the coldboot reconverge SLA
    (300s) of the recorded cold boot moment.
  - HRT (bulk / remote-failure / prod-prefix / plane-status) and FSDB ribMap: the
    cold-boot recovery transient is skipped via a settle window so only the
    recovered steady state is judged (must be back to no-churn / converged).

Headless run cold-boots wedge_agent via SSH — kick off from a Kerberos-ticketed
terminal.

Usage:
  buck2 run neteng/netcastle:netcastle_taac -- \\
    --team taac --test-config fpf_tc27_agent_coldboot \\
    --dev --skip-basset-reservation --skip-testbed-isolation \\
    --debug --continue-on-precheck-failure --skip-fboss-rsyslog
"""

from taac.libs.fpf.fpf_prod_prefix_map import get_prefix
from taac.playbooks.playbook_definitions import (
    create_fpf_service_restart_playbook,
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
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import TestConfig

# Prefixes injected on ALL 8 STSWs, split per VF group (VF1 5000:dd on s001-s004,
# VF2 5000:ee on s005-s008), via the fpf_inject_bgp_prefixes SETUP TASK — this
# netcastle run is fully self-contained. The fabric is VF-segregated (VF1 only on
# lanes 0-3, VF2 only on lanes 4-7), so each observer GTSW / lane sees only its
# own VF group's count: PREFIX_COUNT = VF_GROUP_PREFIX_COUNT. Collector subnet is
# 5000::/16 to count both groups.
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
TRIGGER_STSWS = ALL_STSWS
PROD_PREFIX_HOST = GPU_HOSTS[0]
PROD_PREFIXES = [get_prefix(PROD_PREFIX_HOST, 0)]
PROD_PREFIXES_BY_HOST = {host: PROD_PREFIXES for host in GPU_HOSTS}
DUT_GTSW = OBSERVER_GTSWS[0]

# Cold boot is disruptive: wait >= 5 min for recovery, and skip the recovery
# transient (settle) so only the recovered steady state is judged.
COLDBOOT_SETTLE_AFTER_SEC = 360
COLDBOOT_STABLE_SETTLE_SEC = 300
COLDBOOT_BGP_RECONVERGE_SLA_SEC = 300.0


def create_fpf_tc27_test_config() -> TestConfig:
    skip_ssh = skip_ssh_dependencies()
    skip_ib = skip_ib_traffic()
    ib_setup, ib_teardown = fpf_ib_traffic_tasks(
        skip_ssh, skip_ib, traffic_config=IB_TRAFFIC_CONFIG
    )
    playbook = create_fpf_service_restart_playbook(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        service=taac_types.Service.AGENT,
        create_cold_boot_file=True,
        restart_device_regexes=[DUT_GTSW],
        affected_rib="bgp",
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        injected_lanes=INJECTED_LANES,
        prod_prefixes=PROD_PREFIXES,
        prod_prefixes_by_host=PROD_PREFIXES_BY_HOST,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        stabilization_delay_sec=120,
        settle_after_restart_sec=COLDBOOT_SETTLE_AFTER_SEC,
        stable_settle_sec=COLDBOOT_STABLE_SETTLE_SEC,
        bgp_reconverge_sla_sec=COLDBOOT_BGP_RECONVERGE_SLA_SEC,
        skip_ssh_dependent_checks=skip_ssh,
        spray_hosts=None if skip_ssh or skip_ib else SPRAY_HOSTS,
        ib_traffic_config=(None if skip_ssh or skip_ib else IB_TRAFFIC_CONFIG),
        # Prefixes injected once by the setup task (8-STSW split-per-VF).
        skip_injection=True,
        rf_vf_groups=RF_VF_GROUPS,
        hrt_device_ids=HRT_DEVICE_IDS,
        # Coldboot fully restarts wedge_agent; assert every pre-established peer
        # re-establishes within the (larger) coldboot SLA, DUT-scoped and anchored
        # on wedge_agent's systemd unit.
        assert_bgp_reconvergence=True,
        # Full agent coldboot re-establishes all BGP sessions in ~207s on hardware
        # (measured); 240s SLA gives headroom over the observed reconvergence.
        reconvergence_sla_sec=240.0,
        # Agent coldboot is DISRUPTIVE: the unaffected-rib / HRT / prod-prefix
        # metrics legitimately blip mid-window while the agent reboots. MODE A
        # (last_sample) asserts only the LAST in-window sample reconverged to the
        # golden value; mid-window drops are ignored.
        convergence_blip_mode="last_sample",
        playbook_name="fpf_tc27_agent_coldboot",
    )
    return TestConfig(
        name="fpf_tc27_agent_coldboot",
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
                prod_prefix_device_id=0,
                fsdb_session_poll_interval_sec=2.0,
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
        playbooks=[playbook],
        tags=["fpf"],
    )


TEST_CONFIG = create_fpf_tc27_test_config()
