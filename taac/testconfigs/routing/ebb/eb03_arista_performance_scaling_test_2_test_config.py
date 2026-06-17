# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""EB03_ARISTA_PERFORMANCE_SCALING_TEST_2 — EBB B17 TestConfig.

Built from the centralized
`test_config_constant_attribute_storage_on_eos` factory.
"""

import json
import os

from taac.testconfigs.routing.ebb.test_config_performance_scaling_case2 import (
    test_config_constant_attribute_storage_on_eos,
)
from taac.test_as_a_config import types as taac_types

# Lab device credential (internal-only TAAC test environment).
# Same shared lab account; not a real production secret. Override via env var
# if rotated. pragma: allowlist secret
_LAB_DEVICE_PASSWORD = os.environ.get("TAAC_EBB_LAB_DEVICE_PASSWORD", "dnepit")

EB03_ARISTA_PERFORMANCE_SCALING_TEST_2_TEST_CONFIG = (
    test_config_constant_attribute_storage_on_eos(
        test_config_name="EB03_ARISTA_PERFORMANCE_SCALING_TEST_2",
        device_name="eb03.lab.ash6",
        ixia_interface_mimic_ebgp="Ethernet3/1/3",
        ebgp_remote_as=65334,
        ixia_ebgp_ic_parent_network_v6="2401:db00:e50d:11:8",
        ixia_ebgp_ic_parent_network_v4="10.163.28",
        ebgp_peer_counts=[128],
        constant_total_paths=800000,
        soak_time_minutes=1,
        host_driver_args={
            "eb03.lab.ash6": json.dumps(
                {"username": "admin", "password": _LAB_DEVICE_PASSWORD}
            ),
        },
        oss_mock_device_data={
            "eb03.lab.ash6": taac_types.MockDeviceInfo(
                name="eb03.lab.ash6",
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
                network_type="EBB",
            ),
        },
        host_os_type_map={"eb03.lab.ash6": taac_types.DeviceOsType.ARISTA_FBOSS},
        direct_ixia_connections=[
            taac_types.DirectIxiaConnection(
                interface="Ethernet3/1/3",  # EBGP interface
                ixia_chassis_ip="2401:db00:2066:303b::3001",
                ixia_port="6/5",
            ),
        ],
        # NEW: Constant acceptance community (required by device BGP policy)
        constant_acceptance_communities=["65529:39744"],
        # NEW: Optional limit for communities from pool (default: use all)
        max_communities_per_route_from_pool=5,
        randomize_attributes=True,
        random_seed=42,
        # IMPORTANT: Enable attribute dumping for verification (critical data)
        dump_attribute_assignments=True,
    )
)
