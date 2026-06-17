# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""TC5: BGP GR — Recovery Within GR Window (70k prefixes).

Stop BGP, restart within 120s GR window. Validate HRT retains all 70k
routes during GR window and no churn occurs.
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


def create_fpf_tc05_test_config() -> TestConfig:
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

    playbook = create_fpf_hardening_playbook(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        disruption_steps=disruption_steps,
        disruption_duration_sec=600,
        prefix_count=HARDENING_PREFIX_COUNT,
        playbook_name="fpf_tc05_bgp_gr_within_window",
    )

    return TestConfig(
        name="fpf_tc05_bgp_gr_within_window",
        endpoints=create_fpf_endpoints(),
        playbooks=[playbook],
    )


TEST_CONFIG = create_fpf_tc05_test_config()
