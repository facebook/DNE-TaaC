# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

"""TC22: Focused prod-prefix LOCAL-drain check for a DEVICE drain/undrain.

Device-drain counterpart of TC21. Soft-drains the ENTIRE DUT GTSW via the on-box
LOCAL_DRAINER (not a single port) and runs ONLY the production-HRT-prefix
local-drain check — NO test-prefix injection, NO stabilization wait, NO other
health checks.

From the GPU's prefix-reachability view a device drain of the GTSW serving lane 0
is indistinguishable from a link drain of lane 0, so the contract is identical to
TC21:
  - LOCAL prefix (a284): impacted plane (lane 0) -> DRAINED (not unreachable)
    within ``prod_prefix_drain_sla_sec`` (30s) of the recorded drain moment.
  - REMOTE prefix (a16c): NO churn.
  - Undrain: impacted plane returns to reachable within the SLA.

Device drain/undrain use the DEVICE-level LOCAL_DRAINER (empty ``interfaces``);
a device soft-drain does NOT set the per-port isDrained flag, so the gate uses
``mode="device_drain"`` (device-level is_drained()).

Usage:
  TAAC_FPF_SKIP_SSH_DEPS=1 buck2 run neteng/netcastle:netcastle_taac -- \\
    --team taac --test-config fpf_tc22_prod_prefix_drain_device \\
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

LOCAL_HOST = GPU_HOSTS[0]  # rtptest1555.mwg2 (the GTSW serving lane 0 is drained)
REMOTE_HOST = GPU_HOSTS[1]  # rtptest1575.mwg2 (observer, not drained)
PROD_PREFIX_DEVICE_ID = 0
LOCAL_PREFIXES = [get_prefix(LOCAL_HOST, PROD_PREFIX_DEVICE_ID)]
REMOTE_PREFIXES = [get_prefix(REMOTE_HOST, PROD_PREFIX_DEVICE_ID)]
ALL_PROD_PREFIXES = LOCAL_PREFIXES + REMOTE_PREFIXES

# The drained DEVICE is the DUT GTSW serving lane 0 of the LOCAL host's GPU0.
DRAIN_TARGET_GTSW = OBSERVER_GTSWS[0]
IMPACTED_PLANE = 0
IMPACTED_PLANES_BY_HOST = {LOCAL_HOST: [IMPACTED_PLANE]}


def create_fpf_tc22_test_config() -> TestConfig:
    disrupt_playbook = create_fpf_prod_prefix_drain_only_playbook(
        hosts=GPU_HOSTS,
        disruption_steps=[
            # Clean slate: device-undrain first so the impacted plane is reachable
            # at baseline even if a prior aborted run left the GTSW drained. The
            # drain step below overwrites the recorded disruption time, so the SLA
            # is still measured from the real drain moment.
            create_fpf_drain_interface_step(
                interfaces=[],
                drain=False,
                description=f"Pre-undrain DEVICE {DRAIN_TARGET_GTSW} for a clean baseline",
            ),
            create_longevity_step(
                duration=60,
                description="Settle 60s; ensure plane reachable before device drain",
            ),
            # Empty interfaces -> DEVICE-level soft-drain of the whole DUT GTSW.
            create_fpf_drain_interface_step(
                interfaces=[],
                drain=True,
                description=f"Soft-drain DEVICE {DRAIN_TARGET_GTSW} via local drainer",
            ),
            create_fpf_verify_disruption_step(
                interfaces=[],
                mode="device_drain",
                expect_drained=True,
                fail_if_ineffective=True,
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
        playbook_name="fpf_tc22_prod_prefix_drain_device_disrupt",
    )

    restore_playbook = create_fpf_prod_prefix_drain_only_playbook(
        hosts=GPU_HOSTS,
        disruption_steps=[
            create_fpf_drain_interface_step(
                interfaces=[],
                drain=False,
                description=f"Undrain DEVICE {DRAIN_TARGET_GTSW} via local drainer",
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
        playbook_name="fpf_tc22_prod_prefix_drain_device_restore",
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
        name="fpf_tc22_prod_prefix_drain_device",
        endpoints=create_fpf_endpoints(),
        setup_tasks=setup_tasks,
        teardown_tasks=teardown_tasks,
        playbooks=[disrupt_playbook, restore_playbook],
    )


TEST_CONFIG = create_fpf_tc22_test_config()
