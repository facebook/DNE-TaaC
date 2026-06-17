# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""EB03 RFC 1997 Well-Known Community Egress Filtering Test — EBB B17 TestConfig.

Validates the BGP well-known community egress filtering feature (D104889972)
enabled on EBB via D105114939 on the eb03.lab.ash6 device.

RFC 1997 Behavior Matrix (on EBB, non-confederation):
    NO_EXPORT (65535:65281)         -> suppressed to EBGP peers only
    NO_ADVERTISE (65535:65282)      -> suppressed to ALL peers
    NO_EXPORT_SUBCONFED (65535:65283) -> suppressed to EBGP peers only
                                       (same as NO_EXPORT on non-confed)

Playbooks:
    1. EB03_RFC1997_NO_EXPORT          - NO_EXPORT filtering validation
    2. EB03_RFC1997_NO_ADVERTISE       - NO_ADVERTISE filtering validation
    3. EB03_RFC1997_NO_EXPORT_SUBCONFED - NO_EXPORT_SUBCONFED filtering
    4. EB03_RFC1997_BASELINE           - Control group (no well-known community)
    5. EB03_RFC1997_FLAG_OFF_REGRESSION - Feature flag off regression test

Device: eb03.lab.ash6
IXIA Chassis: 2401:db00:2066:303b::3001
IXIA Ports:
    - Et3/1/3 -> 6/5 (eBGP)
    - Et3/1/5 -> 6/6 (iBGP)
    - Et3/1/1 -> 6/4 (BGP MON — not used by this test)

Uses only 2 IXIA ports (eBGP + iBGP) with minimal peers (5 per group)
for focused feature validation.
"""

import json
import os

from taac.testconfigs.routing.ebb.test_config_well_known_communities import (
    test_config_for_well_known_communities,
)
from taac.test_as_a_config import types as taac_types

# Lab device credential (internal-only TAAC test environment).
# Same shared lab account; not a real production secret. Override via env var
# if rotated. pragma: allowlist secret
_LAB_DEVICE_PASSWORD = os.environ.get("TAAC_EBB_LAB_DEVICE_PASSWORD", "dnepit")

# =============================================================================
# Device-specific configuration for eb03.lab.ash6
# =============================================================================
DEVICE_NAME = "eb03.lab.ash6"
IXIA_CHASSIS_IP = "2401:db00:2066:303b::3001"

# IXIA interface mappings for eb03.lab.ash6
IXIA_INTERFACE_MIMIC_EBGP = "Ethernet3/1/3"
IXIA_INTERFACE_MIMIC_IBGP = "Ethernet3/1/5"

# IXIA port mappings (chassis slot/port)
IXIA_PORT_EBGP = "6/5"
IXIA_PORT_IBGP = "6/6"

# Network parameters from existing eb03 configs
EBGP_REMOTE_AS = 65334
IBGP_LOCAL_AS = 64981
IXIA_EBGP_IC_PARENT_NETWORK_V6 = "2401:db00:e50d:11:8"
IXIA_EBGP_IC_PARENT_NETWORK_V4 = "10.163.28"
IXIA_IBGP_IC_PARENT_NETWORK_V6 = "2401:db00:e50d:11:9"
IXIA_IBGP_IC_PARENT_NETWORK_V4 = "10.164.28"


EB03_ARISTA_WELL_KNOWN_COMMUNITY_TEST_CONFIG = test_config_for_well_known_communities(
    test_config_name="EB03-ARISTA_RFC1997_WELL_KNOWN_COMMUNITY_FILTER_TEST",
    device_name=DEVICE_NAME,
    # EBGP configuration (ingress - routes with well-known communities)
    ixia_interface_ebgp=IXIA_INTERFACE_MIMIC_EBGP,
    ebgp_remote_as=EBGP_REMOTE_AS,
    ixia_ebgp_ic_parent_network_v6=IXIA_EBGP_IC_PARENT_NETWORK_V6,
    ixia_ebgp_ic_parent_network_v4=IXIA_EBGP_IC_PARENT_NETWORK_V4,
    # IBGP configuration (egress - listeners verify filtering)
    ixia_interface_ibgp=IXIA_INTERFACE_MIMIC_IBGP,
    ibgp_local_as=IBGP_LOCAL_AS,
    ixia_ibgp_ic_parent_network_v6=IXIA_IBGP_IC_PARENT_NETWORK_V6,
    ixia_ibgp_ic_parent_network_v4=IXIA_IBGP_IC_PARENT_NETWORK_V4,
    # Minimal peers for feature validation (1 eBGP per community + 5 iBGP)
    ebgp_peer_count=5,
    ibgp_peer_count=5,
    prefix_count=100,
    ssh_user="admin",
    ssh_password=_LAB_DEVICE_PASSWORD,
    test_address_families=["ipv6"],
    ebgp_route_acceptance_communities=["65529:39744"],
    convergence_wait_seconds=60,
    # Device metadata
    host_driver_args={
        DEVICE_NAME: json.dumps(
            {"username": "admin", "password": _LAB_DEVICE_PASSWORD}
        ),
    },
    oss_mock_device_data={
        DEVICE_NAME: taac_types.MockDeviceInfo(
            name=DEVICE_NAME,
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
    host_os_type_map={DEVICE_NAME: taac_types.DeviceOsType.ARISTA_FBOSS},
    direct_ixia_connections=[
        taac_types.DirectIxiaConnection(
            interface=IXIA_INTERFACE_MIMIC_EBGP,
            ixia_chassis_ip=IXIA_CHASSIS_IP,
            ixia_port=IXIA_PORT_EBGP,
        ),
        taac_types.DirectIxiaConnection(
            interface=IXIA_INTERFACE_MIMIC_IBGP,
            ixia_chassis_ip=IXIA_CHASSIS_IP,
            ixia_port=IXIA_PORT_IBGP,
        ),
    ],
    log_collection_timeout=600,
)
