# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""EB02_ARISTA_BGP_UPDATE_PACKING_VALIDATION — EBB B17 TestConfig.

Built from the centralized
`test_config_bgp_update_packing_validation` factory.
"""

import json
import os

from taac.testconfigs.routing.ebb.test_config_update_packing import (
    test_config_bgp_update_packing_validation,
)
from taac.test_as_a_config import types as taac_types

# Lab device credential (internal-only TAAC test environment).
# Same shared lab account; not a real production secret. Override via env var
# if rotated. pragma: allowlist secret
_LAB_DEVICE_PASSWORD = os.environ.get("TAAC_EBB_LAB_DEVICE_PASSWORD", "dnepit")

EB02_ARISTA_BGP_UPDATE_PACKING_VALIDATION_TEST_CONFIG = test_config_bgp_update_packing_validation(
    test_config_name="EB02_ARISTA_BGP_UPDATE_PACKING_VALIDATION",
    device_name="eb02.lab.ash6",
    # EBGP configuration (ingress - routes sent here from Fabric Aggregators)
    ixia_interface_mimic_ebgp="Ethernet3/1/3",
    ebgp_remote_as=65334,  # Fabric Aggregator AS
    ixia_ebgp_ic_parent_network_v6="2401:db00:e50d:11:8",
    ixia_ebgp_ic_parent_network_v4="10.163.28",
    # IBGP configuration (egress - capture UPDATEs to other Edge Borders here)
    ixia_interface_mimic_ibgp="Ethernet3/1/5",
    ibgp_local_as=64981,  # Same AS as device (IBGP/EB-EB)
    ixia_ibgp_ic_parent_network_v6="2401:db00:e50d:11:9",
    ixia_ibgp_ic_parent_network_v4="10.164.28",
    # Test parameters (EBGP → IBGP scenario)
    ebgp_peer_count=10,  # 10 EBGP peers (FAs) sending routes
    prefixes_per_peer=10000,  # 10,000 prefixes per peer = 100,000 total routes
    ibgp_peer_count=1,  # 1 IBGP listener (EB-EB peer, avoid duplicate captures)
    # Address family selection
    test_address_families=["ipv6"],  # IPv6 only - cleanest results
    # Attribute pool configuration (creates attribute variety)
    as_path_pool_size=10,  # 10 unique AS paths
    community_pool_size=20,  # 20 unique communities
    as_path_length=3,  # Each AS path has 3 AS numbers
    communities_per_route=2,  # Each route gets 2 communities
    # Route acceptance communities (EBGP → IBGP direction)
    ebgp_route_acceptance_communities=["65529:39744"],  # EBGP acceptance for EB
    # Test control
    capture_duration_seconds=300,  # 5 minutes capture (100K routes)
    min_packed_size=3500,  # Minimum size for "full" UPDATE messages (relaxed from 4000)
    restart_bgp_for_complete_view=True,  # True: Best-case mode (restart BGP++), False: Real-world mode (incremental)
    # Device configuration
    host_driver_args={
        "eb02.lab.ash6": json.dumps(
            {"username": "admin", "password": _LAB_DEVICE_PASSWORD}
        ),
    },
    oss_mock_device_data={
        "eb02.lab.ash6": taac_types.MockDeviceInfo(
            name="eb02.lab.ash6",
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
    host_os_type_map={"eb02.lab.ash6": taac_types.DeviceOsType.ARISTA_FBOSS},
    direct_ixia_connections=[
        taac_types.DirectIxiaConnection(
            interface="Ethernet3/1/3",  # EBGP interface (routes ingress here)
            ixia_chassis_ip="2401:db00:2066:303b::3001",
            ixia_port="6/2",
        ),
        taac_types.DirectIxiaConnection(
            interface="Ethernet3/1/5",  # IBGP/EB-EB interface (capture UPDATEs here)
            ixia_chassis_ip="2401:db00:2066:303b::3001",
            ixia_port="6/3",
        ),
    ],
)
