# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

"""TC21: Focused prod-prefix LOCAL-drain check for a LINK drain/undrain.

A minimal, fast validation harness that runs ONLY the production-HRT-prefix
local-drain health check around a link drain + undrain — NO test-prefix
injection, NO stabilization wait, and NO other health checks. The production
prefixes are real (already on the fabric), so nothing needs injecting; the
prod-prefix collector started in setup supplies the pre/post-drain samples.

Contract validated (local-vs-remote attribution):
  - LOCAL prefix (rtptest1555's own, a284): the impacted plane (lane 0) must
    transition to DRAINED — and NOT to unreachable/unavailable — within
    ``prod_prefix_drain_sla_sec`` (30s) of the recorded drain moment.
  - REMOTE prefix (rtptest1575's, a16c): NO churn — its reachable plane set is
    unchanged through the drain (draining THIS host's local advert must not move
    a remote destination's reachability).
  - Undrain: the impacted plane returns to reachable within the SLA.

Headless: drain/undrain use the on-box LOCAL_DRAINER (thrift), so this runs
without SSH.

Usage:
  TAAC_FPF_SKIP_SSH_DEPS=1 buck2 run neteng/netcastle:netcastle_taac -- \\
    --team taac --test-config fpf_tc21_prod_prefix_drain_link \\
    --dev --skip-basset-reservation --skip-testbed-isolation \\
    --debug --continue-on-precheck-failure --skip-fboss-rsyslog
"""

from taac.libs.fpf.fpf_prod_prefix_map import get_prefix
from taac.playbooks.playbook_definitions import (
    create_fpf_prod_prefix_drain_only_playbook,
)
from taac.steps.step_definitions import (
    create_fpf_drain_interface_step,
    create_fpf_verify_disruption_step,
    create_longevity_step,
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
    FSDB_COLLECTOR_MODE,
    GPU_HOSTS,
    OBSERVER_GTSWS,
    TRIGGER_STSWS,
)
from taac.test_as_a_config.types import TestConfig

PREFIX_COUNT = 1000
LONGEVITY_SEC = 90

# LOCAL = the drained host's own prefix; REMOTE = the observer host's prefix.
LOCAL_HOST = GPU_HOSTS[0]  # rtptest1555.mwg2 (drained)
REMOTE_HOST = GPU_HOSTS[1]  # rtptest1575.mwg2 (observer, not drained)
PROD_PREFIX_DEVICE_ID = 0
LOCAL_PREFIXES = [get_prefix(LOCAL_HOST, PROD_PREFIX_DEVICE_ID)]
REMOTE_PREFIXES = [get_prefix(REMOTE_HOST, PROD_PREFIX_DEVICE_ID)]
ALL_PROD_PREFIXES = LOCAL_PREFIXES + REMOTE_PREFIXES

# The drained link carries lane 0 of the LOCAL host's GPU0.
DRAIN_INTERFACE = "eth1/45/5"
IMPACTED_PLANE = 0
IMPACTED_PLANES_BY_HOST = {LOCAL_HOST: [IMPACTED_PLANE]}


def create_fpf_tc21_test_config() -> TestConfig:
    disrupt_playbook = create_fpf_prod_prefix_drain_only_playbook(
        hosts=GPU_HOSTS,
        disruption_steps=[
            # Clean slate: undrain first so the impacted plane is reachable at
            # baseline even if a prior aborted run left it drained. The drain
            # step below overwrites the recorded disruption time, so the SLA is
            # still measured from the real drain moment.
            create_fpf_drain_interface_step(
                interfaces=[DRAIN_INTERFACE],
                drain=False,
                description=f"Pre-undrain {DRAIN_INTERFACE} for a clean baseline",
            ),
            create_longevity_step(
                duration=60,
                description="Settle 60s; ensure plane reachable before drain",
            ),
            create_fpf_drain_interface_step(
                interfaces=[DRAIN_INTERFACE],
                drain=True,
                description=f"Soft-drain link {DRAIN_INTERFACE} on {OBSERVER_GTSWS[0]}",
            ),
            create_fpf_verify_disruption_step(
                interfaces=[DRAIN_INTERFACE],
                mode="drain",
                expect_drained=True,
            ),
            create_longevity_step(
                duration=LONGEVITY_SEC,
                description=f"Settle {LONGEVITY_SEC}s; local prefix should drain",
            ),
        ],
        local_prefixes=LOCAL_PREFIXES,
        remote_prefixes=REMOTE_PREFIXES,
        impacted_planes_by_host=IMPACTED_PLANES_BY_HOST,
        mode="local_drain",
        playbook_name="fpf_tc21_prod_prefix_drain_link_disrupt",
    )

    restore_playbook = create_fpf_prod_prefix_drain_only_playbook(
        hosts=GPU_HOSTS,
        disruption_steps=[
            create_fpf_drain_interface_step(
                interfaces=[DRAIN_INTERFACE],
                drain=False,
                description=f"Undrain link {DRAIN_INTERFACE} on {OBSERVER_GTSWS[0]}",
            ),
            create_longevity_step(
                duration=LONGEVITY_SEC,
                description=f"Settle {LONGEVITY_SEC}s; local prefix should recover",
            ),
        ],
        local_prefixes=LOCAL_PREFIXES,
        remote_prefixes=REMOTE_PREFIXES,
        impacted_planes_by_host=IMPACTED_PLANES_BY_HOST,
        mode="local_undrain",
        playbook_name="fpf_tc21_prod_prefix_drain_link_restore",
    )

    setup_tasks = [
        create_fpf_start_collectors_task(
            gtsws=OBSERVER_GTSWS,
            hosts=GPU_HOSTS,
            subnet_prefix=DEFAULT_SUBNET_PREFIX,
            prod_prefixes=ALL_PROD_PREFIXES,
            prod_prefix_host=LOCAL_HOST,
            prod_prefix_device_id=PROD_PREFIX_DEVICE_ID,
            fsdb_mode=FSDB_COLLECTOR_MODE,
            allow_baseline_failures=ALLOW_BASELINE_FAILURES,
        )
    ]
    teardown_tasks = [
        create_fpf_stop_collectors_task(
            trigger_stsws=TRIGGER_STSWS,
            prefix_count=PREFIX_COUNT,
            community_list=DEFAULT_COMMUNITY_LIST,
        )
    ]

    return TestConfig(
        name="fpf_tc21_prod_prefix_drain_link",
        endpoints=create_fpf_endpoints(),
        setup_tasks=setup_tasks,
        teardown_tasks=teardown_tasks,
        playbooks=[disrupt_playbook, restore_playbook],
    )


TEST_CONFIG = create_fpf_tc21_test_config()
