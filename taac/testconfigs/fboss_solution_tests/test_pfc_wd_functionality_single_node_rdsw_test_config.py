# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""TEST_PFC_WD_FUNCTIONALITY_SINGLE_NODE_RDSW TestConfig.

Built from the centralized `gen_pfc_wd_functionality_test_configs` factory.
"""

from taac.testconfigs.fboss_solution_tests.network_ai_test_configs import (
    gen_pfc_wd_functionality_test_configs,
)
from taac.test_as_a_config import types as taac_types

RDSW001_C084_SNC1 = [
    taac_types.Endpoint(
        name="rdsw003.u001.c084.snc1",
        dut=True,
        ixia_ports=["eth1/11/1", "eth1/15/1"],
    )
]

RDSW001_C084_SNC1_SRC_ENDPOINTS = [
    taac_types.TrafficEndpoint(name="rdsw003.u001.c084.snc1:eth1/11/1")
]

RDSW001_C084_SNC1_DST_ENDPOINTS = [
    taac_types.TrafficEndpoint(name="rdsw003.u001.c084.snc1:eth1/15/1")
]

TEST_PFC_WD_FUNCTIONALITY_SINGLE_NODE_RDSW = gen_pfc_wd_functionality_test_configs(
    test_config_name="TEST_PFC_WD_FUNCTIONALITY_SINGLE_NODE_RDSW",
    endpoints=RDSW001_C084_SNC1,
    basset_pool="fboss",
    src_endpoints=RDSW001_C084_SNC1_SRC_ENDPOINTS,
    dst_endpoints=RDSW001_C084_SNC1_DST_ENDPOINTS,
)
