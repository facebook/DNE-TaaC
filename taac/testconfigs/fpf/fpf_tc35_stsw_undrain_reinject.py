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
    HRT_MEMORY_HOSTS,
    OBSERVER_GTSWS,
    skip_ssh_dependencies,
    SPRAY_HOSTS,
    TRIGGER_STSWS,
)
from taac.test_as_a_config.types import TestConfig

PREFIX_COUNT = 1000
LONGEVITY_SEC = 300

# STSW plane to undrain (the first trigger STSW: stsw001.s001.l202.mwg2).
UNDRAIN_TARGET_STSW = TRIGGER_STSWS[0]

PROD_PREFIX_HOST = GPU_HOSTS[0]
PROD_PREFIX_DEVICE_ID = 0
PROD_PREFIXES = [get_prefix(PROD_PREFIX_HOST, PROD_PREFIX_DEVICE_ID)]


def create_fpf_tc35_test_config() -> TestConfig:
    skip_ssh = skip_ssh_dependencies()
    ib_setup, ib_teardown = fpf_ib_traffic_tasks(skip_ssh)
    spray = None if skip_ssh else SPRAY_HOSTS

    disrupt_steps = [
        *create_fpf_stsw_drain_and_reinject_steps(
            stsw=UNDRAIN_TARGET_STSW,
            drained=False,
            trigger_stsws=TRIGGER_STSWS,
            prefix_count=PREFIX_COUNT,
            community_list=DEFAULT_COMMUNITY_LIST,
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
        skip_ssh_dependent_checks=skip_ssh,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
    )

    return TestConfig(
        name="fpf_tc35_stsw_undrain_reinject",
        endpoints=create_fpf_endpoints(),
        setup_tasks=[
            *ib_setup,
            create_fpf_start_collectors_task(
                gtsws=OBSERVER_GTSWS,
                hosts=GPU_HOSTS,
                subnet_prefix=DEFAULT_SUBNET_PREFIX,
                prod_prefixes=PROD_PREFIXES,
                prod_prefix_host=PROD_PREFIX_HOST,
                prod_prefix_device_id=PROD_PREFIX_DEVICE_ID,
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
        playbooks=[disrupt_playbook, longevity_playbook],
        tags=["fpf"],
    )


TEST_CONFIG = create_fpf_tc35_test_config()
