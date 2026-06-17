# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

"""TC25: wedge_agent (warmboot) process restart on the DUT GTSW.

Restart wedge_agent on gtsw001. A wedge_agent restart also restarts bgpd, so
the expectation matches the BGP restart (TC23):
  - HRT (bulk / remote-failure / prod-prefix / plane-status): NO churn.
  - FSDB ribMap: unchanged.
  - BGP RIB: bgp thrift collector null/unresponsive for a few polls during the
    restart (tolerated); BGP RIB must return to the expected count within
    bgp_restart_reconverge_sla_sec (60s) of the recorded restart moment — whether
    measured from the agent restart or the bgp restart (they coincide).

Headless run restarts wedge_agent via SSH — kick off from a Kerberos-ticketed
terminal.

Usage:
  buck2 run neteng/netcastle:netcastle_taac -- \\
    --team taac --test-config fpf_tc25_wedge_agent_restart \\
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


def create_fpf_tc25_test_config() -> TestConfig:
    skip_ssh = skip_ssh_dependencies()
    ib_setup, ib_teardown = fpf_ib_traffic_tasks(skip_ssh)
    playbook = create_fpf_service_restart_playbook(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        service=taac_types.Service.AGENT,
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
        settle_after_restart_sec=120,
        skip_ssh_dependent_checks=skip_ssh,
        spray_hosts=None if skip_ssh else SPRAY_HOSTS,
        playbook_name="fpf_tc25_wedge_agent_restart",
    )
    return TestConfig(
        name="fpf_tc25_wedge_agent_restart",
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


TEST_CONFIG = create_fpf_tc25_test_config()
