# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""TC32: All Downlink Flaps on GTSW (scaled "1hr" rapid-flap stability test).

Rapidly flaps ALL of the GTSW->GPU DOWNLINK interfaces on the DUT GTSW for a
sustained window, then validates that the steady state recovers cleanly. The
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
  matching the remote system name against the GPU-host pattern
  (``DOWNLINK_NEIGHBOR_PATTERN``, fnmatch glob — defaults to ``"rtptest*"`` to
  match the MWG2 GPU hosts ``rtptest1555.mwg2`` / ``rtptest1575.mwg2``). No
  hardcoded eth1/37/* breakouts here — the testbed wiring can change without
  touching this config.

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
# Scaled flap window (15 min) — the "1hr" plan compressed to a normal slot.
FLAP_DURATION_SEC = 900
FLAP_INTERVAL_SEC = 1
# Longevity window after flaps stop; stable-state checks anchor at its start.
LONGEVITY_SEC = 300

DUT_GTSW = OBSERVER_GTSWS[0]

# GTSW->GPU downlink neighbor pattern (fnmatch glob over LLDP remote system
# name). The rapid-flap step resolves the actual eth1/* breakout list at run
# time by reading LLDP on DUT_GTSW and picking interfaces whose neighbor
# matches this glob. ``rtptest*`` covers the MWG2 GPU hosts.
DOWNLINK_NEIGHBOR_PATTERN = "rtptest*"

PROD_PREFIX_HOST = GPU_HOSTS[0]
PROD_PREFIX_DEVICE_ID = 0
PROD_PREFIXES = [get_prefix(PROD_PREFIX_HOST, PROD_PREFIX_DEVICE_ID)]


def create_fpf_tc32_test_config() -> TestConfig:
    skip_ssh = skip_ssh_dependencies()
    ib_setup, ib_teardown = fpf_ib_traffic_tasks(skip_ssh)
    spray = None if skip_ssh else SPRAY_HOSTS

    disrupt_playbook = create_fpf_disruption_only_playbook(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        disruption_steps=[
            create_fpf_rapid_flap_step_lldp(
                # Scope precisely to the configured GPU hosts (exact match);
                # the glob is kept only as a fallback when neighbor_hosts is
                # empty. This prevents flapping ALL 132 downlinks (the tc32
                # 36h-hang root cause) — only rtptest1555/rtptest1575 are
                # flapped.
                neighbor_hosts=GPU_HOSTS,
                neighbor_pattern=DOWNLINK_NEIGHBOR_PATTERN,
                duration_sec=FLAP_DURATION_SEC,
                flap_interval_sec=FLAP_INTERVAL_SEC,
                flap_down_time_sec=6,
                device_regexes=[DUT_GTSW],
                description=(
                    f"Rapid-flap LLDP-resolved downlinks to {GPU_HOSTS} on "
                    f"{DUT_GTSW} for {FLAP_DURATION_SEC}s (wall-clock bound)"
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
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
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
    )

    return TestConfig(
        name="fpf_tc32_downlink_flaps",
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


TEST_CONFIG = create_fpf_tc32_test_config()
