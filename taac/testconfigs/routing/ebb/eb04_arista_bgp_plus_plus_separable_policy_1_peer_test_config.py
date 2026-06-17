# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""EB04_ARISTA_BGP_PLUS_PLUS_SEPARABLE_POLICY_1_PEER — EBB B17 TestConfig.

Built from the centralized
`test_config_for_bgp_plus_plus_on_ebb_arista_separable_policy` factory.
"""

import json
import os

from taac.testconfigs.routing.ebb.test_config_performance_scaling_case8 import (
    test_config_for_bgp_plus_plus_on_ebb_arista_separable_policy,
)
from taac.test_as_a_config import types as taac_types

# Lab device credential (internal-only TAAC test environment).
# Same shared lab account; not a real production secret. Override via env var
# if rotated. pragma: allowlist secret
_LAB_DEVICE_PASSWORD = os.environ.get("TAAC_EBB_LAB_DEVICE_PASSWORD", "dnepit")

EB04_ARISTA_BGP_PLUS_PLUS_SEPARABLE_POLICY_1_PEER_TEST_CONFIG = (
    test_config_for_bgp_plus_plus_on_ebb_arista_separable_policy(
        test_config_name="EB04_ARISTA_BGP_PLUS_PLUS_SEPARABLE_POLICY_1_PEER",
        host_driver_args={
            "eb04.lab.ash6": json.dumps(
                {"username": "admin", "password": _LAB_DEVICE_PASSWORD}
            ),
        },
        oss_mock_device_data={
            "eb04.lab.ash6": taac_types.MockDeviceInfo(
                name="eb04.lab.ash6",
                hardware="ARISTA_7516",
                role="EB",
                operating_system="EOS",
                dc="ash6",
                region="ash",
                asset_id=12345,
                asic="JERICHO",
                routing_protocol="BGP",
                dc_type="ONE",
                network_area="BACKBONE",
                network_area_type="BACKBONE",
            ),
        },
        host_os_type_map={"eb04.lab.ash6": taac_types.DeviceOsType.ARISTA_FBOSS},
        device_name="eb04.lab.ash6",
        ixia_interface_mimic_ebgp="Ethernet3/1/1",
        ebgp_remote_as=65334,
        ebgp_peer_count_v4=1,
        ebgp_peer_count_v6=1,
        ixia_ebgp_ic_parent_network_v6="2401:db00:e50d:11:8",
        ixia_ebgp_ic_parent_network_v4="10.163.28",
        direct_ixia_connections=[
            taac_types.DirectIxiaConnection(
                interface="Ethernet3/1/1",  # EBGP interface
                ixia_chassis_ip="2401:db00:2066:303b::3001",
                ixia_port="6/7",
            ),
        ],
        prefix_count=50000,
    )
)
