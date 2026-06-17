# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""QZD_SINGLE_NODE_TOPOLOGY_MIMIC_EBB_TEST_FULL_SCALE — EBB B17 TestConfig.

Built from the centralized `test_config_for_bgp_plus_plus_ebb` factory.
"""

from taac.testconfigs.routing.ebb.fboss_ebb_scale_test_config import (
    test_config_for_bgp_plus_plus_ebb,
)

QZD_SINGLE_NODE_TOPOLOGY_MIMIC_EBB_TEST_FULL_SCALE_TEST_CONFIG = (
    test_config_for_bgp_plus_plus_ebb(
        test_config_name="QZD_SINGLE_NODE_TOPOLOGY_MIMIC_EBB_TEST_FULL_SCALE",
        device_name="fsw003.p003.f01.qzd1",
        peergroup_ibgp_v6="EB-EB-V6",
        peergroup_ebgp_v6="EB-FA-V6",
        peergroup_ibgp_v4="EB-EB-V4",
        peergroup_ebgp_v4="EB-FA-V4",
        ixia_interface_mimic_ebgp="eth8/16/1",
        ixia_interface_mimic_ibgp="eth9/16/1",
        ibgp_remote_as=64981,
        ebgp_remote_as=65334,
        ebgp_peer_count_v4=140,
        ebgp_peer_count_v6=140,
        unqiue_prefix_limit=130000,
        total_path_limit=20000000,
        ixia_ebgp_ic_parent_network_v6="2401:db00:e50d:11:8",
        ixia_ebgp_ic_parent_network_v4="10.163.28",
        ixia_ibgp_ic_parent_network_v6_dc_plane1="2401:db00:e50d:11:9",
        ixia_ibgp_ic_parent_network_v6_dc_plane2="2401:db00:e50d:11:10",
        ixia_ibgp_ic_parent_network_v6_dc_plane3="2401:db00:e50d:11:11",
        ixia_ibgp_ic_parent_network_v6_dc_plane4="2401:db00:e50d:11:12",
        ixia_ibgp_ic_parent_network_v6_mp_plane1="2401:db00:e50d:11:13",
        ixia_ibgp_ic_parent_network_v6_mp_plane2="2401:db00:e50d:11:14",
        ixia_ibgp_ic_parent_network_v6_mp_plane3="2401:db00:e50d:11:15",
        ixia_ibgp_ic_parent_network_v6_mp_plane4="2401:db00:e50d:11:16",
        ixia_ibgp_ic_parent_network_v4_dc_plane1="10.164.28",
        ixia_ibgp_ic_parent_network_v4_dc_plane2="10.165.28",
        ixia_ibgp_ic_parent_network_v4_dc_plane3="10.166.28",
        ixia_ibgp_ic_parent_network_v4_dc_plane4="10.167.28",
        ixia_ibgp_ic_parent_network_v4_mp_plane1="10.168.28",
        ixia_ibgp_ic_parent_network_v4_mp_plane2="10.169.28",
        ixia_ibgp_ic_parent_network_v4_mp_plane3="10.170.28",
        ixia_ibgp_ic_parent_network_v4_mp_plane4="10.171.28",
        ixia_ebgp_communities=[
            "65529:39744",
            "65530:50700",
            "65527:36706",
            "65520:523",
            "65140:65527",
            "65060:10012",
        ],
        ixia_ibgp_communities=[
            "65060:10012",
            "65140:65529",
            "65520:503",
            "65529:11610",
            "65529:39744",
            "65530:50300",
            "65530:50320",
            "65530:50800",
        ],
        ebgp_ingress_policy_name="PROPAGATE_FSW_SSW_IN",
        ebgp_egress_policy_name="PROPAGATE_FSW_SSW_OUT",
        ibgp_ingress_policy_name="PROPAGATE_FSW_RSW_IN",
        ibgp_egress_policy_name="PROPAGATE_FSW_RSW_OUT",
        ibgp_peer_scale_per_plane=63,
        local_as_4_byte=64981,
        bgp_router_id="129.134.63.224",
    )
)
