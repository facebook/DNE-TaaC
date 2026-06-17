# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""TC38: Persistent NDP Clear — Port UP, NDP DOWN.

Repeatedly flushes the GTSW NDP (neighbor) table while every port stays UP, so
neighbor resolution is forced to re-converge continuously under sustained
clearing — the "the link is fine but the neighbor cache keeps getting wiped"
failure. The disruption is a 120s loop of ``fboss2 clear ndp`` (every 1s) on the
observer GTSW, followed by a 120s longevity, then a stable-state v2 longevity
playbook whose health checks anchor at LONGEVITY START.

PROVISIONAL EXPECTATIONS (documented):
  Per the test owner, the steady-state behavior under a persistent NDP clear is
  UNCERTAIN — it is not yet known whether continuous NDP flushing measurably
  perturbs HRT/prefix convergence once ports stay up. So ALL health checks use
  STABLE-STATE expectations for now (the standard ``create_fpf_hardening_
  playbook_v2`` postchecks, which assert the converged steady state), anchored
  at longevity start via the two-playbook pattern: the disruption-only playbook
  carries NO checks (so nothing measures across the noisy clear window), and the
  runner stamps a fresh ``test_case_start_time`` at the start of the stable-state
  longevity playbook, so its checks naturally measure only the post-clear
  steady state. These expectations are PROVISIONAL and should be tightened (e.g.
  to a churn/transition contract on the impacted lane) once the real behavior is
  characterized on hardware.

Shape:
  playbooks = [
    disruption-only:  ndp-clear loop (120s) + longevity (120s)   # NO checks
    stable-state v2:  inject + stabilize + longevity              # all stable HCs
  ]

Usage:
  TAAC_FPF_SKIP_SSH_DEPS=1 buck2 run neteng/netcastle:netcastle_taac -- \\
    --team taac --test-config fpf_tc38_persistent_ndp_clear \\
    --dev --skip-basset-reservation --skip-testbed-isolation \\
    --debug --continue-on-precheck-failure --skip-fboss-rsyslog
"""

from taac.libs.fpf.fpf_prod_prefix_map import get_prefix
from taac.playbooks.playbook_definitions import (
    create_fpf_disruption_only_playbook,
    create_fpf_hardening_playbook_v2,
)
from taac.steps.step_definitions import (
    create_fpf_ndp_clear_loop_step,
    create_longevity_step,
)
from taac.task_definitions import (
    create_fpf_start_collectors_task,
    create_fpf_start_ib_traffic_task,
    create_fpf_stop_collectors_task,
    create_fpf_stop_ib_traffic_task,
)
from taac.testconfigs.fpf.fpf_hardening_common import (
    ALLOW_BASELINE_FAILURES,
    create_fpf_endpoints,
    DEFAULT_COMMUNITY_LIST,
    DEFAULT_SUBNET_PREFIX,
    EXPECTED_FSDB_SESSION_COUNT,
    FSDB_COLLECTOR_MODE,
    GPU_HOSTS,
    OBSERVER_GTSWS,
    skip_ssh_dependencies,
    TRIGGER_STSWS,
)
from taac.test_as_a_config.types import TestConfig

PREFIX_COUNT = 1000
STABILIZATION_DELAY_SEC = 300
NDP_CLEAR_EVERY_SEC = 1
NDP_CLEAR_DURATION_SEC = 120
SETTLE_AFTER_CLEAR_SEC = 120
LONGEVITY_SEC = 300

PROD_PREFIX_HOST = GPU_HOSTS[0]
PROD_PREFIX_DEVICE_ID = 0
PROD_PREFIXES = [get_prefix(PROD_PREFIX_HOST, PROD_PREFIX_DEVICE_ID)]
HRT_MEMORY_HOSTS = ["rtptest1555.mwg2", "rtptest1575.mwg2"]
IB_TRAFFIC_SERVER = GPU_HOSTS[0]
IB_TRAFFIC_CLIENTS = [GPU_HOSTS[1]]
SPRAY_HOSTS = [IB_TRAFFIC_SERVER, *IB_TRAFFIC_CLIENTS]


def create_fpf_tc38_test_config() -> TestConfig:
    skip_ssh = skip_ssh_dependencies()
    spray = None if skip_ssh else SPRAY_HOSTS

    # Disruption-only playbook: sustained NDP clear on the observer GTSW, then a
    # settle. NO checks here — the noisy clear window is excluded from all HCs.
    disrupt_playbook = create_fpf_disruption_only_playbook(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        disruption_steps=[
            create_fpf_ndp_clear_loop_step(
                every_sec=NDP_CLEAR_EVERY_SEC,
                duration_sec=NDP_CLEAR_DURATION_SEC,
                device_regexes=[OBSERVER_GTSWS[0]],
                description=(
                    f"Persistent NDP clear every {NDP_CLEAR_EVERY_SEC}s for "
                    f"{NDP_CLEAR_DURATION_SEC}s on {OBSERVER_GTSWS[0]} "
                    f"(ports stay UP)"
                ),
            ),
            create_longevity_step(
                duration=SETTLE_AFTER_CLEAR_SEC,
                description=(
                    f"Settle {SETTLE_AFTER_CLEAR_SEC}s after the NDP-clear loop "
                    f"before the stable-state window"
                ),
            ),
        ],
        playbook_name="fpf_tc38_persistent_ndp_clear_disrupt",
    )

    # Stable-state v2 longevity: PROVISIONAL — all HCs assert the converged
    # steady state, anchored at this playbook's start (post-clear).
    stable_playbook = create_fpf_hardening_playbook_v2(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        soak_duration_sec=LONGEVITY_SEC,
        stabilization_delay_sec=STABILIZATION_DELAY_SEC,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        playbook_name="fpf_tc38_persistent_ndp_clear_stable",
        prod_prefixes=PROD_PREFIXES,
        skip_ssh_dependent_checks=skip_ssh,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
    )

    setup_tasks = []
    teardown_tasks = []
    if not skip_ssh:
        setup_tasks.append(
            create_fpf_start_ib_traffic_task(
                server=IB_TRAFFIC_SERVER, clients=IB_TRAFFIC_CLIENTS
            )
        )
        teardown_tasks.append(
            create_fpf_stop_ib_traffic_task(
                server=IB_TRAFFIC_SERVER, clients=IB_TRAFFIC_CLIENTS
            )
        )
    setup_tasks.append(
        create_fpf_start_collectors_task(
            gtsws=OBSERVER_GTSWS,
            hosts=GPU_HOSTS,
            subnet_prefix=DEFAULT_SUBNET_PREFIX,
            prod_prefixes=PROD_PREFIXES,
            prod_prefix_host=PROD_PREFIX_HOST,
            prod_prefix_device_id=PROD_PREFIX_DEVICE_ID,
            fsdb_mode=FSDB_COLLECTOR_MODE,
            allow_baseline_failures=ALLOW_BASELINE_FAILURES,
        )
    )
    teardown_tasks.append(
        create_fpf_stop_collectors_task(
            trigger_stsws=TRIGGER_STSWS,
            prefix_count=PREFIX_COUNT,
            community_list=DEFAULT_COMMUNITY_LIST,
        )
    )

    return TestConfig(
        name="fpf_tc38_persistent_ndp_clear",
        endpoints=create_fpf_endpoints(),
        setup_tasks=setup_tasks,
        teardown_tasks=teardown_tasks,
        playbooks=[disrupt_playbook, stable_playbook],
        tags=["fpf"],
    )


TEST_CONFIG = create_fpf_tc38_test_config()
