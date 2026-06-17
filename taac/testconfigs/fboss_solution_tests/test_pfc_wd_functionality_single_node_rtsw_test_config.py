# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""TEST_PFC_WD_FUNCTIONALITY_SINGLE_NODE_RTSW TestConfig.

Built from the centralized `gen_pfc_wd_functionality_test_configs` factory.
"""

from taac.testconfigs.fboss_solution_tests.network_ai_test_configs import (
    gen_pfc_wd_functionality_test_configs,
)
from taac.test_as_a_config import types as taac_types

RTSW011_SNC1 = [
    taac_types.Endpoint(
        name="rtsw011.c081.f00.snc1",
        dut=True,
    )
]

RTSW011_SNC1_SRC_ENDPOINTS = [
    taac_types.TrafficEndpoint(name="rtsw011.c081.f00.snc1:eth2/1/1")
]

RTSW011_SNC1_DST_ENDPOINTS = [
    taac_types.TrafficEndpoint(name="rtsw011.c081.f00.snc1:eth2/5/1")
]

TEST_PFC_WD_FUNCTIONALITY_SINGLE_NODE_RTSW = gen_pfc_wd_functionality_test_configs(
    test_config_name="TEST_PFC_WD_FUNCTIONALITY_SINGLE_NODE_RTSW",
    endpoints=RTSW011_SNC1,
    basset_pool="fboss",
    src_endpoints=RTSW011_SNC1_SRC_ENDPOINTS,
    dst_endpoints=RTSW011_SNC1_DST_ENDPOINTS,
)
