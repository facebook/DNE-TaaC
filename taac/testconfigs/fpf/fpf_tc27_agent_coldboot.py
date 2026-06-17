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
    create_fpf_start_collectors_task,
    create_fpf_stop_collectors_task,
)
from taac.testconfigs.fpf.fpf_hardening_common import (
    ALLOW_BASELINE_FAILURES,
    create_fpf_endpoints,
    DEFAULT_COMMUNITY_LIST,
    DEFAULT_SUBNET_PREFIX,
    EXPECTED_FSDB_SESSION_COUNT,
    fpf_ib_traffic_tasks,
    FSDB_COLLECTOR_MODE,
    GPU_HOSTS,
    OBSERVER_GTSWS,
    skip_ssh_dependencies,
    SPRAY_HOSTS,
    TRIGGER_STSWS,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import TestConfig

PREFIX_COUNT = 1000
INJECTED_LANES = [0, 1]
PROD_PREFIX_HOST = GPU_HOSTS[0]
PROD_PREFIXES = [get_prefix(PROD_PREFIX_HOST, 0)]
HRT_MEMORY_HOSTS = ["rtptest1555.mwg2", "rtptest1575.mwg2"]
DUT_GTSW = OBSERVER_GTSWS[0]

# Cold boot is disruptive: wait >= 5 min for recovery, and skip the recovery
# transient (settle) so only the recovered steady state is judged.
COLDBOOT_SETTLE_AFTER_SEC = 360
COLDBOOT_STABLE_SETTLE_SEC = 300
COLDBOOT_BGP_RECONVERGE_SLA_SEC = 300.0


def create_fpf_tc27_test_config() -> TestConfig:
    skip_ssh = skip_ssh_dependencies()
    ib_setup, ib_teardown = fpf_ib_traffic_tasks(skip_ssh)
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
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        stabilization_delay_sec=120,
        settle_after_restart_sec=COLDBOOT_SETTLE_AFTER_SEC,
        stable_settle_sec=COLDBOOT_STABLE_SETTLE_SEC,
        bgp_reconverge_sla_sec=COLDBOOT_BGP_RECONVERGE_SLA_SEC,
        skip_ssh_dependent_checks=skip_ssh,
        spray_hosts=None if skip_ssh else SPRAY_HOSTS,
        playbook_name="fpf_tc27_agent_coldboot",
    )
    return TestConfig(
        name="fpf_tc27_agent_coldboot",
        endpoints=create_fpf_endpoints(),
        setup_tasks=[
            *ib_setup,
            create_fpf_start_collectors_task(
                gtsws=OBSERVER_GTSWS,
                hosts=GPU_HOSTS,
                subnet_prefix=DEFAULT_SUBNET_PREFIX,
                prod_prefixes=PROD_PREFIXES,
                prod_prefix_host=PROD_PREFIX_HOST,
                prod_prefix_device_id=0,
                fsdb_mode=FSDB_COLLECTOR_MODE,
                allow_baseline_failures=ALLOW_BASELINE_FAILURES,
            ),
        ],
        teardown_tasks=[
            create_fpf_stop_collectors_task(
                trigger_stsws=TRIGGER_STSWS,
                prefix_count=PREFIX_COUNT,
                community_list=DEFAULT_COMMUNITY_LIST,
            ),
            *ib_teardown,
        ],
        playbooks=[playbook],
        tags=["fpf"],
    )


TEST_CONFIG = create_fpf_tc27_test_config()
