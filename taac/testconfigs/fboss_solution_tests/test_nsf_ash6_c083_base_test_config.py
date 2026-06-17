# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""TEST_NSF_ASH6_C083_BASE TestConfig.

Built from the centralized `gen_ash6_c083_base_test_configs` factory.
"""

from taac.testconfigs.fboss_solution_tests.network_ai_test_configs import (
    gen_ash6_c083_base_test_configs,
)

TEST_NSF_ASH6_C083_BASE = gen_ash6_c083_base_test_configs()
