# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""TEST_PFC_FUNCTIONALITY_SNC1_C085 TestConfig.

Built from the centralized `gen_pfc_functionality_test_configs` factory.
"""

from taac.testconfigs.fboss_solution_tests.network_ai_test_configs import (
    gen_pfc_functionality_test_configs,
)
from taac.test_as_a_config import types as taac_types

SNC1_C085 = [
    taac_types.Endpoint(
        name="rdsw001.c085.n001.snc1",
    ),
    taac_types.Endpoint(
        name="rdsw002.c085.n001.snc1",
    ),
    taac_types.Endpoint(
        name="rdsw003.c085.n001.snc1",
    ),
    taac_types.Endpoint(
        name="rdsw004.c085.n001.snc1",
        dut=True,
    ),
    taac_types.Endpoint(
        name="rdsw005.c085.n001.snc1",
    ),
    taac_types.Endpoint(
        name="rdsw006.c085.n001.snc1",
    ),
]

SNC1_C085_SRC_ENDPOINTS = [
    taac_types.TrafficEndpoint(name="rdsw001.c085.n001.snc1:eth1/11/1"),
    taac_types.TrafficEndpoint(name="rdsw002.c085.n001.snc1:eth1/11/1"),
    taac_types.TrafficEndpoint(name="rdsw004.c085.n001.snc1:eth1/11/1"),
    taac_types.TrafficEndpoint(name="rdsw005.c085.n001.snc1:eth1/11/1"),
    taac_types.TrafficEndpoint(name="rdsw005.c085.n001.snc1:eth1/15/1"),
]


SNC1_C085_DST_ENDPOINTS = [
    taac_types.TrafficEndpoint(name="rdsw006.c085.n001.snc1:eth1/11/1")
    for _ in range(5)
]

TEST_PFC_FUNCTIONALITY_SNC1_C085 = gen_pfc_functionality_test_configs(
    test_config_name="TEST_PFC_FUNCTIONALITY_SNC1_C085",
    endpoints=SNC1_C085,
    basset_pool="dsf",
    src_endpoints=SNC1_C085_SRC_ENDPOINTS,
    dst_endpoints=SNC1_C085_DST_ENDPOINTS,
)
