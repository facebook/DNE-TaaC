# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""WEDGE100S_FBOSS_HARDENING TestConfig.

Built from the centralized `get_test_config_wedge100s_fboss_hardening` factory.
"""

from taac.testconfigs.fboss_solution_tests.fboss_hardening_test_config import (
    get_test_config_wedge100s_fboss_hardening,
)

WEDGE100S_FBOSS_HARDENING = get_test_config_wedge100s_fboss_hardening(
    test_config_name="WEDGE100S_FBOSS_HARDENING",
    device_name="rsw004.p003.f02.snc1",
    peergroup_uplink_mimic="RSW_FSW",
    peergroup_downlink_mimic="RSW_SLB",
    ixia_downlink_interface="eth1/27/1",
    ixia_uplink_interface="eth1/28/1",
    ixia_downlink_ic_parent_network_v6="2401:db00:11c:4203",
    ixia_uplink_ic_parent_network_v6="2401:db00:e01e:2302",
    prefix_limit="10000",
    per_peer_max_route_limit="45000",
    downlink_peer_count=50,
    uplink_peer_count=16,
    remote_downlink_as_4byte=65000,
    remote_uplink_as_4byte=4008,
    ixia_downlink_prefix_count_v6=50,
    ixia_downlink_communities=["65520:832", "65529:12730", "65520:822"],
    ixia_uplink_communities=["65520:832", "65529:12730"],
    ixia_uplink_prefix_count_v6=30,
    uplink_peer_tag="FSW",
    downlink_peer_tag="SLB",
    ecmp_group_limit=1000,
    port_id_vlan_map={92: 2000},
    cp_stressing_network_index_prefix_count=10,
    direct_ixia_connections=None,
)
