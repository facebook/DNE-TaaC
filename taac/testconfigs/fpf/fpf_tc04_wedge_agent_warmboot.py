# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""TC4: Wedge Agent Warm Boot on GTSW at prefix scale.

Warm boot wedge_agent on GTSW. Validate NDP state is preserved, no BGP
route withdrawals, no HRT churn.
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


def create_fpf_tc04_test_config() -> TestConfig:
    disruption_steps = [
        create_service_interruption_step(
            service=taac_types.Service.AGENT,
            trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
            description="Wedge agent warm boot on DUT GTSW",
        ),
    ]

    playbook = create_fpf_hardening_playbook(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        disruption_steps=disruption_steps,
        disruption_duration_sec=600,
        prefix_count=HARDENING_PREFIX_COUNT,
        playbook_name="fpf_tc04_wedge_agent_warmboot",
    )

    return TestConfig(
        name="fpf_tc04_wedge_agent_warmboot",
        endpoints=create_fpf_endpoints(),
        playbooks=[playbook],
    )


TEST_CONFIG = create_fpf_tc04_test_config()
