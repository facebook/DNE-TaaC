# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""BGP_PLUS_PLUS_VERIFY_CONSTANT_ATTRIBUTE_STORAGE_TEST_CONFIGS — EBB B17 TestConfig.

Built from the centralized
`test_config_to_verify_constant_attribute_storage` factory.
"""

from taac.testconfigs.routing.ebb.test_config_to_verify_constant_attribute_storage import (
    test_config_to_verify_constant_attribute_storage,
)

BGP_PLUS_PLUS_VERIFY_CONSTANT_ATTRIBUTE_STORAGE_TEST_CONFIG = (
    test_config_to_verify_constant_attribute_storage(
        test_config_name="BGP_PLUS_PLUS_VERIFY_CONSTANT_ATTRIBUTE_STORAGE_TEST_CONFIGS",
        device_name="fa001-uu001.qzd1",
        peergroup_ibgp_v6="PEERGROUP_FAUU_FADU_V6_NEW",
        peergroup_ebgp_v6="PEERGROUP_FAUU_EB_V6_NEW",
        peergroup_ibgp_v4="PEERGROUP_FAUU_FADU_V4_NEW",
        peergroup_ebgp_v4="PEERGROUP_FAUU_EB_V4_NEW",
        ixia_interface_mimic_ebgp="eth6/13/1",
        ixia_interface_mimic_ibgp="eth6/15/1",
        ibgp_remote_as=65271,
        ebgp_remote_as=64734,
        ebgp_peer_counts=[1, 4, 16, 64, 128],
        unqiue_prefix_limit=75000,
        total_path_limit=30000000,
        ixia_ebgp_ic_parent_network_v6="2401:db00:e50d:11:8",
        ixia_ibgp_ic_parent_network_v6="2401:db00:e50d:11:9",
        ixia_ebgp_ic_parent_network_v4="10.163.28",
        ixia_ibgp_ic_parent_network_v4="10.164.28",
        ixia_ebgp_communities=["65526:35724"],
        ixia_ibgp_communities=["65441:133"],
        ebgp_ingress_policy_name="PROPAGATE_FAUU_EB_IN",
        ebgp_egress_policy_name="PROPAGATE_FAUU_EB_OUT",
        ibgp_ingress_policy_name="PROPAGATE_FAUU_FADU_IN",
        ibgp_egress_policy_name="PROPAGATE_FAUU_FADU_OUT",
        prefix_counts=[10000],
        ibgp_peer_count=1000,
    )
)
