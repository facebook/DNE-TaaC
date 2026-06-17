# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""EB02_ARISTA_CONSTANT_ATTRIBUTE_STORAGE_VARYING_COMBINATIONS_TEST — EBB B17 TestConfig.

Built from the centralized
`test_config_constant_attribute_storage_varying_combinations_on_eos` factory.
"""

import json
import os

from taac.testconfigs.routing.ebb.test_config_performance_scaling_case2 import (
    test_config_constant_attribute_storage_varying_combinations_on_eos,
)
from taac.test_as_a_config import types as taac_types

# Lab device credential (internal-only TAAC test environment).
# Same shared lab account; not a real production secret. Override via env var
# if rotated. pragma: allowlist secret
_LAB_DEVICE_PASSWORD = os.environ.get("TAAC_EBB_LAB_DEVICE_PASSWORD", "dnepit")

EB02_ARISTA_CONSTANT_ATTRIBUTE_STORAGE_VARYING_COMBINATIONS_TEST_CONFIG = test_config_constant_attribute_storage_varying_combinations_on_eos(
    test_config_name="EB02_ARISTA_CONSTANT_ATTRIBUTE_STORAGE_VARYING_COMBINATIONS_TEST",
    device_name="eb02.lab.ash6",
    ixia_interface_mimic_ebgp="Ethernet3/1/3",
    ebgp_remote_as=65334,
    ixia_ebgp_ic_parent_network_v6="2401:db00:e50d:11:8",
    ixia_ebgp_ic_parent_network_v4="10.163.28",
    # IBGP interface and parameters
    ixia_interface_mimic_ibgp="Ethernet3/1/5",
    ibgp_local_as=64981,  # Same AS as device (IBGP)
    ixia_ibgp_ic_parent_network_v6="2401:db00:e50d:11:9",
    ixia_ibgp_ic_parent_network_v4="10.164.28",
    # Fixed: 8 EBGP peers (4 IPv4 + 4 IPv6)
    constant_ebgp_peer_count=8,
    # Fixed: 2 IBGP peers (1 IPv4 + 1 IPv6) - listeners only
    constant_ibgp_peer_count=2,
    # Fixed: 800K total paths (100K per peer from EBGP only)
    constant_total_paths=800_000,
    # Variable: unique combination counts - testing single iteration first
    unique_combination_counts=[
        100_000,  # Iteration 1: Low diversity - validate everything works before full run
        200_000,  # Iteration 2: Medium diversity - validate everything works before full run
        400_000,  # Iteration 3: High diversity - validate everything works before full run
        600_000,  # Iteration 4: Full run - validate everything works before full run
        800_000,  # Iteration 4: Full run - validate everything works before full run
    ],
    soak_time_minutes=2,
    # IMPORTANT: Enable attribute dumping for verification (critical data)
    dump_attribute_assignments=True,
    test_address_families=["ipv6"],
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
            interface="Ethernet3/1/3",  # EBGP interface
            ixia_chassis_ip="2401:db00:2066:303b::3001",
            ixia_port="6/2",
        ),
        taac_types.DirectIxiaConnection(
            interface="Ethernet3/1/5",  # IBGP interface (matches ixia_interface_mimic_ibgp)
            ixia_chassis_ip="2401:db00:2066:303b::3001",
            ixia_port="6/3",
        ),
    ],
    # Constant acceptance community (required by device BGP policy)
    constant_acceptance_communities=["65529:39744"],
    # Optional limit for communities from pool
    max_communities_per_route_from_pool=5,
    random_seed=42,
    # Device-level BGP peer group names (for replace_bgp_peers task)
    peergroup_ebgp_v6="EB-FA-V6",
    peergroup_ebgp_v4="EB-FA-V4",
    peergroup_ibgp_v6="EB-EB-V6",
    peergroup_ibgp_v4="EB-EB-V4",
    ssh_password=_LAB_DEVICE_PASSWORD,
)
