# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""TC6: BGP GR — Expiry Beyond GR Window (70k prefixes).

Stop BGP, wait >120s (beyond GR window), restart. Validate HRT purges
routes after GR expiry and reprograms on reconnect.
"""

from taac.playbooks.playbook_definitions import (
    create_fpf_hardening_playbook,
)
from taac.steps.step_definitions import (
    create_longevity_step,
    create_service_convergence_step,
    create_service_interruption_step,
)
from taac.testconfigs.fpf.fpf_hardening_common import (
    create_fpf_endpoints,
    GPU_HOSTS,
    HARDENING_PREFIX_COUNT,
    OBSERVER_GTSWS,
    TRIGGER_STSWS,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import TestConfig


def create_fpf_tc06_test_config() -> TestConfig:
    disruption_steps = [
        create_service_interruption_step(
            service=taac_types.Service.BGP,
            trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_STOP,
            description="Stop BGP on DUT GTSW",
        ),
        create_longevity_step(
            duration=180,
            description="Wait 180s (beyond 120s GR window — routes purged)",
        ),
        create_service_interruption_step(
            service=taac_types.Service.BGP,
            trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_START,
            description="Restart BGP on DUT GTSW after GR expiry",
        ),
        create_service_convergence_step(
            services=[taac_types.Service.BGP],
            timeout=600,
            description="Wait for BGP convergence after GR expiry recovery",
        ),
    ]

    playbook = create_fpf_hardening_playbook(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        disruption_steps=disruption_steps,
        disruption_duration_sec=900,
        prefix_count=HARDENING_PREFIX_COUNT,
        playbook_name="fpf_tc06_bgp_gr_beyond_window",
    )

    return TestConfig(
        name="fpf_tc06_bgp_gr_beyond_window",
        endpoints=create_fpf_endpoints(),
        playbooks=[playbook],
    )


TEST_CONFIG = create_fpf_tc06_test_config()
