# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""TC2: BGP Graceful Restart on GTSW at prefix scale.

Trigger BGP GR on a GTSW at prefix scale. Validate HRT retains all routes
during GR window (120s) and no churn occurs.
"""

from taac.playbooks.playbook_definitions import (
    create_fpf_hardening_playbook,
)
from taac.steps.step_definitions import (
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


def create_fpf_tc02_test_config() -> TestConfig:
    disruption_steps = [
        create_service_interruption_step(
            service=taac_types.Service.BGP,
            trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
            description="BGP graceful restart on DUT GTSW",
        ),
    ]

    playbook = create_fpf_hardening_playbook(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        disruption_steps=disruption_steps,
        disruption_duration_sec=300,
        prefix_count=HARDENING_PREFIX_COUNT,
        playbook_name="fpf_tc02_bgp_graceful_restart",
    )

    return TestConfig(
        name="fpf_tc02_bgp_graceful_restart",
        endpoints=create_fpf_endpoints(),
        playbooks=[playbook],
    )


TEST_CONFIG = create_fpf_tc02_test_config()
