# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""TC14: GTSW Device Drain at Scale.

Full GTSW device drain at prefix scale. After drain, the HRT remote-failure
collector observes negative-route counts rising from 0 to the injected prefix
count on the drained lane. After undrain, counts return to 0. Both transitions
must complete within the convergence SLA.
"""

from taac.health_checks.healthcheck_definitions import (
    create_fpf_hrt_remote_failure_convergence_check,
)
from taac.playbooks.playbook_definitions import (
    create_fpf_hardening_playbook,
)
from taac.steps.step_definitions import (
    create_drain_undrain_step,
    create_longevity_step,
)
from taac.testconfigs.fpf.fpf_hardening_common import (
    create_fpf_endpoints,
    DEFAULT_REMOTE_FAILURE_LANES,
    DRAIN_CONVERGENCE_SLA_SEC,
    GPU_HOSTS,
    HARDENING_PREFIX_COUNT,
    OBSERVER_GTSWS,
    TRIGGER_STSWS,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import TestConfig

DRAIN_TARGET_GTSW = OBSERVER_GTSWS[0]
DRAIN_TARGET_LANE = 0


def create_fpf_tc14_test_config() -> TestConfig:
    disruption_steps = [
        create_drain_undrain_step(
            drain=True,
            drain_handler=taac_types.DrainHandler.LOCAL_DRAINER,
            description=f"Drain {DRAIN_TARGET_GTSW} via local drainer",
        ),
        create_longevity_step(
            duration=150,
            description="Wait for drain convergence",
        ),
        create_drain_undrain_step(
            drain=False,
            drain_handler=taac_types.DrainHandler.LOCAL_DRAINER,
            description=f"Undrain {DRAIN_TARGET_GTSW} via local drainer",
        ),
        create_longevity_step(
            duration=150,
            description="Wait for recovery convergence",
        ),
    ]

    remote_failure_postchecks = [
        create_fpf_hrt_remote_failure_convergence_check(
            lanes=[DRAIN_TARGET_LANE],
            expected_per_lane={str(DRAIN_TARGET_LANE): HARDENING_PREFIX_COUNT},
            direction="drain",
            max_convergence_sec=DRAIN_CONVERGENCE_SLA_SEC,
            use_live_collectors=True,
            check_id=f"fpf_remote_failure_drain_lane{DRAIN_TARGET_LANE}",
        ),
        create_fpf_hrt_remote_failure_convergence_check(
            lanes=[DRAIN_TARGET_LANE],
            expected_per_lane={str(DRAIN_TARGET_LANE): HARDENING_PREFIX_COUNT},
            direction="recovery",
            max_convergence_sec=DRAIN_CONVERGENCE_SLA_SEC,
            use_live_collectors=True,
            check_id=f"fpf_remote_failure_recovery_lane{DRAIN_TARGET_LANE}",
        ),
    ]

    unaffected_lanes = [
        lane for lane in DEFAULT_REMOTE_FAILURE_LANES if lane != DRAIN_TARGET_LANE
    ]
    if unaffected_lanes:
        remote_failure_postchecks.append(
            create_fpf_hrt_remote_failure_convergence_check(
                lanes=unaffected_lanes,
                expected_per_lane={str(lane): 0 for lane in unaffected_lanes},
                direction="drain",
                max_convergence_sec=DRAIN_CONVERGENCE_SLA_SEC,
                use_live_collectors=True,
                check_id="fpf_remote_failure_unaffected_lanes",
            ),
        )

    playbook = create_fpf_hardening_playbook(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        disruption_steps=disruption_steps,
        disruption_duration_sec=450,
        prefix_count=HARDENING_PREFIX_COUNT,
        additional_postchecks=remote_failure_postchecks,
        playbook_name="fpf_tc14_gtsw_device_drain",
    )

    return TestConfig(
        name="fpf_tc14_gtsw_device_drain",
        endpoints=create_fpf_endpoints(),
        playbooks=[playbook],
    )


TEST_CONFIG = create_fpf_tc14_test_config()
