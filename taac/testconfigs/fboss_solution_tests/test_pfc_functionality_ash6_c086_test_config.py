# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""TEST_PFC_FUNCTIONALITY_ASH6_C086 TestConfig.

Built from the centralized `gen_pfc_functionality_test_configs` factory.
"""

from taac.testconfigs.fboss_solution_tests.network_ai_test_configs import (
    gen_pfc_functionality_test_configs,
)
from taac.test_as_a_config import types as taac_types

ASH6_C086 = [
    taac_types.Endpoint(
        name="rdsw002.u001.c086.ash6",
    ),
    taac_types.Endpoint(
        name="rdsw004.u001.c086.ash6",
    ),
    taac_types.Endpoint(
        name="rdsw006.u001.c086.ash6",
    ),
    taac_types.Endpoint(
        name="rdsw008.u001.c086.ash6",
        dut=True,
    ),
    taac_types.Endpoint(
        name="rdsw010.u001.c086.ash6",
    ),
]

ASH6_C086_SRC_ENDPOINTS = [
    taac_types.TrafficEndpoint(name="rdsw002.u001.c086.ash6:eth1/11/1"),
    taac_types.TrafficEndpoint(name="rdsw006.u001.c086.ash6:eth1/11/1"),
    taac_types.TrafficEndpoint(name="rdsw008.u001.c086.ash6:eth1/11/1"),
    taac_types.TrafficEndpoint(name="rdsw004.u001.c086.ash6:eth1/11/1"),
    taac_types.TrafficEndpoint(name="rdsw004.u001.c086.ash6:eth1/15/1"),
]


ASH6_C086_DST_ENDPOINTS = [
    taac_types.TrafficEndpoint(name="rdsw010.u001.c086.ash6:eth1/11/1")
    for _ in range(5)
]

TEST_PFC_FUNCTIONALITY_ASH6_C086 = gen_pfc_functionality_test_configs(
    test_config_name="TEST_PFC_FUNCTIONALITY_ASH6_C086",
    endpoints=ASH6_C086,
    basset_pool="dsf",
    src_endpoints=ASH6_C086_SRC_ENDPOINTS,
    dst_endpoints=ASH6_C086_DST_ENDPOINTS,
)
