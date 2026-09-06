# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""TC5: BGP GR — Recovery Within GR Window.

Stop BGP, restart within the 120s GR window. Validate HRT retains all routes
during the GR window and no churn occurs.

Prefixes are injected on ALL 8 STSWs, split per VF group (VF1 5000:dd on
s001-s004 = planes 0-3, VF2 5000:ee on s005-s008 = planes 4-7), via the
fpf_inject_bgp_prefixes SETUP TASK so the netcastle run is self-contained. The
fabric is VF-segregated, so each observer GTSW / lane sees only its own VF
group's count: PREFIX_COUNT = VF_GROUP_PREFIX_COUNT. Collector subnet is 5000::/16
to count both groups. The playbook passes skip_injection=True (no in-playbook
inject) and checks all 8 lanes.
"""

from taac.libs.fpf.fpf_prod_prefix_map import get_prefix
from taac.playbooks.playbook_definitions import (
    create_fpf_hardening_playbook_v2,
)
from taac.steps.step_definitions import (
    create_fpf_record_disruption_time_step,
    create_longevity_step,
    create_service_convergence_step,
    create_service_interruption_step,
)
from taac.task_definitions import (
    create_fpf_inject_vf_groups_task,
    create_fpf_restart_service_task,
    create_fpf_start_collectors_task,
    create_fpf_stop_collectors_task,
    create_fpf_withdraw_vf_groups_task,
)
from taac.testconfigs.fpf.fpf_hardening_common import (
    ALL_LANES,
    ALL_STSWS,
    ALLOW_BASELINE_FAILURES,
    create_fpf_endpoints,
    DEFAULT_COMMUNITY_LIST,
    EXPECTED_FSDB_SESSION_COUNT,
    fpf_ib_traffic_tasks,
    fpf_rf_vf_groups,
    fpf_vf_injection_groups,
    FSDB_COLLECTOR_MODE,
    GPU_HOSTS,
    HRT_MEMORY_HOSTS,
    OBSERVER_GTSWS,
    skip_ssh_dependencies,
    SPRAY_HOSTS,
    TRIGGER_STSWS,
    VF_COLLECTOR_SUBNET,
    VF_GROUP_PREFIX_COUNT,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import TestConfig

INJECTION_GROUPS = fpf_vf_injection_groups()
RF_VF_GROUPS = fpf_rf_vf_groups()
PREFIX_COUNT = VF_GROUP_PREFIX_COUNT
INJECT_SETTLE_SEC = 300
INJECTED_LANES = ALL_LANES
STABILIZATION_DELAY_SEC = 300

PROD_PREFIX_HOST = GPU_HOSTS[0]
PROD_PREFIX_DEVICE_ID = 0
PROD_PREFIXES = [get_prefix(PROD_PREFIX_HOST, PROD_PREFIX_DEVICE_ID)]


def create_fpf_tc05_test_config() -> TestConfig:
    skip_ssh = skip_ssh_dependencies()
    ib_setup, ib_teardown = fpf_ib_traffic_tasks(skip_ssh)
    spray = None if skip_ssh else SPRAY_HOSTS

    disruption_steps = [
        create_service_interruption_step(
            service=taac_types.Service.BGP,
            trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_STOP,
            description="Stop BGP on DUT GTSW",
        ),
        create_longevity_step(
            duration=90,
            description="Wait 90s (within 120s GR window)",
        ),
        create_fpf_record_disruption_time_step(
            description="Record BGP restart time for RIB reconvergence SLA"
        ),
        create_service_interruption_step(
            service=taac_types.Service.BGP,
            trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_START,
            description="Restart BGP on DUT GTSW",
        ),
        create_service_convergence_step(
            services=[taac_types.Service.BGP],
            timeout=300,
            description="Wait for BGP convergence after restart",
        ),
    ]

    playbook = create_fpf_hardening_playbook_v2(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        disruption_steps=disruption_steps,
        stabilization_delay_sec=STABILIZATION_DELAY_SEC,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        playbook_name="fpf_tc05_bgp_gr_within_window",
        prod_prefixes=PROD_PREFIXES,
        skip_ssh_dependent_checks=skip_ssh,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
        # 8-plane: prefixes injected once by the setup task; check all 8 lanes.
        skip_injection=True,
        rf_vf_groups=RF_VF_GROUPS,
        lanes=INJECTED_LANES,
        # bgpd is GR-restarted on the DUT GTSW; assert every pre-established peer
        # re-establishes within the SLA, scoped to the DUT and anchored on bgpd's
        # restart (DUT-only, pre-established-peer reconvergence snapshot).
        assert_bgp_reconvergence=True,
        reconvergence_service="bgpd",
        reconvergence_sla_sec=60.0,
        reconvergence_hosts=[OBSERVER_GTSWS[0]],
        bgp_rib_restart_reconverge=True,
        # fsdb/HRT are coupled: a brief HRT FSDB-session census dip is expected
        # across a GR; skip the postcheck (precheck still asserts 32/32 baseline).
        skip_fsdb_session_postcheck=True,
        # GR-within (graceful, within-window): a within-window graceful restart
        # must NOT break forwarding. The affected BGP RIB uses the restart-aware
        # contract above; MODE B applies to FSDB/HRT checks and tolerates null
        # collection blips while rejecting any non-null degradation signature.
        convergence_blip_mode="skip_null_strict",
    )

    return TestConfig(
        name="fpf_tc05_bgp_gr_within_window",
        endpoints=create_fpf_endpoints(stsws=ALL_STSWS),
        setup_tasks=[
            *ib_setup,
            create_fpf_start_collectors_task(
                gtsws=OBSERVER_GTSWS,
                hosts=GPU_HOSTS,
                subnet_prefix=VF_COLLECTOR_SUBNET,
                prod_prefixes=PROD_PREFIXES,
                prod_prefix_host=PROD_PREFIX_HOST,
                prod_prefix_device_id=PROD_PREFIX_DEVICE_ID,
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


TEST_CONFIG = create_fpf_tc05_test_config()
