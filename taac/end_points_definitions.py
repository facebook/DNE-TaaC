# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
from taac.test_as_a_config.types import TrafficEndpoint


QZD_FAUU_HIGHER_LAYER_TESTING_ENPOINTS = [
    TrafficEndpoint(
        name="fa002-uu001.qzd1:eth6/13/1",
    ),
    TrafficEndpoint(
        name="fa002-uu002.qzd1:eth6/13/1",
    ),
    TrafficEndpoint(
        name="fa002-uu003.qzd1:eth6/13/1",
    ),
    TrafficEndpoint(
        name="fa002-uu004.qzd1:eth6/13/1",
    ),
    TrafficEndpoint(
        name="fa001-uu001.qzd1:eth6/13/1",
    ),
    TrafficEndpoint(
        name="fa001-uu002.qzd1:eth6/15/1",
    ),
    TrafficEndpoint(
        name="fa001-uu003.qzd1:eth6/13/1",
    ),
    TrafficEndpoint(
        name="fa001-uu004.qzd1:eth6/13/1",
    ),
]

QZD_SSW_HIGHER_LAYER_TESTING_ENPOINTS = [
    TrafficEndpoint(
        name="ssw002.s002.f01.qzd1:eth8/16/1",
    )
]

QZD_SINGLE_NODE_CONVEYOUR_UPLINK_ENPOINTS_V6 = [
    TrafficEndpoint(name="fsw003.p003.f01.qzd1:eth9/16/1", network_group_index=0)
]

QZD_SINGLE_NODE_CONVEYOUR_DOWNLINK_ENPOINTS_V6 = [
    TrafficEndpoint(name="fsw003.p003.f01.qzd1:eth8/16/1", network_group_index=0)
]


QZD_SINGLE_NODE_CONVEYOUR_UPLINK_ENPOINTS_V4 = [
    TrafficEndpoint(
        name="fsw003.p003.f01.qzd1:eth9/16/1",
        device_group_index=1,
        network_group_index=0,
    )
]

QZD_SINGLE_NODE_CONVEYOUR_DOWNLINK_ENPOINTS_V4 = [
    TrafficEndpoint(
        name="fsw003.p003.f01.qzd1:eth8/16/1",
        device_group_index=1,
        network_group_index=0,
    )
]
