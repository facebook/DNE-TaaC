# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""EB02_ARISTA_BGP_QUEUE_MEMORY_MONITOR_IPV6_50EBGP_25IBGP_WITH_FLAPPING — EBB B17 TestConfig.

Built from the centralized
`test_config_bgp_queue_memory_monitoring_with_route_scale` factory.
"""

import json
import os

from taac.testconfigs.routing.ebb.test_config_queue_memory_monitor import (
    test_config_bgp_queue_memory_monitoring_with_route_scale,
)
from taac.test_as_a_config import types as taac_types

# Lab device credential (internal-only TAAC test environment).
# Same shared lab account; not a real production secret. Override via env var
# if rotated. pragma: allowlist secret
_LAB_DEVICE_PASSWORD = os.environ.get("TAAC_EBB_LAB_DEVICE_PASSWORD", "dnepit")

EB02_ARISTA_BGP_QUEUE_MEMORY_MONITOR_IPV6_50EBGP_25IBGP_WITH_FLAPPING_TEST_CONFIG = test_config_bgp_queue_memory_monitoring_with_route_scale(
    test_config_name="EB02_ARISTA_BGP_QUEUE_MEMORY_MONITOR_IPV6_50EBGP_25IBGP_WITH_FLAPPING",
    device_name="eb02.lab.ash6",
    # IBGP configuration (EB-EB peers)
    ixia_interface_mimic_ibgp="Ethernet3/1/5",
    ibgp_local_as=64981,  # Same AS as device (IBGP/EB-EB)
    ixia_ibgp_ic_parent_network_v6="2401:db00:e50d:11:9",
    ixia_ibgp_ic_parent_network_v4="10.164.28",
    # EBGP configuration (Fabric Aggregator peers)
    ixia_interface_mimic_ebgp="Ethernet3/1/3",
    ebgp_remote_as=65334,  # Fabric Aggregator AS
    ixia_ebgp_ic_parent_network_v6="2401:db00:e50d:11:8",
    ixia_ebgp_ic_parent_network_v4="10.163.28",
    # Test parameters
    ibgp_peer_count=50,
    ebgp_peer_count=50,
    prefixes_per_ebgp_peer=15000,
    ip_version="both",
    # Route acceptance communities
    ebgp_route_acceptance_communities=["65529:39744"],  # EBGP acceptance for EB
    # Monitoring parameters
    monitoring_duration_minutes=30,
    monitoring_interval_seconds=60,
    # Route flapping parameters
    flap_uptime_seconds=15,
    flap_downtime_seconds=15,
    # Dynamic peer configuration
    ssh_user="admin",
    ssh_password=_LAB_DEVICE_PASSWORD,
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
            interface="Ethernet3/1/3",  # EBGP interface
            ixia_chassis_ip="2401:db00:2066:303b::3001",
            ixia_port="6/2",
        ),
        taac_types.DirectIxiaConnection(
            interface="Ethernet3/1/5",  # IBGP interface
            ixia_chassis_ip="2401:db00:2066:303b::3001",
            ixia_port="6/3",
        ),
    ],
)
