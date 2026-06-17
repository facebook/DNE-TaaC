# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""RTSW002 SNC1 longevity test config (orphan, not registered).

Carved out of `rtsw_snc1_test_config.py` during Phase 3-161 of the TAAC
restructuring effort. The 13 RTSW002_* constants relocated here were
defined alongside the RTSW001 chain but were never registered in
`INTERNAL_TEST_CONFIGS` (the active aggregator only re-exports
`RTSW001_LONGEVITY_TEST_CONFIG` / `RTSW001_TEST_CONFIGS`). The
RTSW002 chain therefore had no live consumer — Option A was chosen over
deletion: migrate the orphan to its own file and re-export it from the
package `__init__.py` so the symbols remain importable for future use,
without changing the golden manifest hash.

Testbed Topology (rtsw002):
  rtsw002 eth2/1/1 (2401:db00:11b:4001::a/64) -> Ixia 1/47, AS 65008
  rtsw002 eth2/5/1 (2401:db00:11b:4801::a/64) -> Ixia 1/45, AS 65009

RTSW BGP config is applied via COOP patchers (setup_tasks).
IXIA config is applied by TAAC framework (basic_port_configs).

Note: rtsw001 has COOP "full override" issue blocking bgpcpp patchers.
Using rtsw002 which works with COOP patchers.
"""

import json

from ixia.ixia import types as ixia_types
from taac.health_checks.healthcheck_definitions import (
    create_ixia_packet_loss_check,
)
from taac.playbooks.playbook_definitions import (
    create_rtsw_longevity_playbook,
)
from taac.task_definitions import (
    create_configure_parallel_bgp_peers_task,
    create_coop_apply_patchers_task,
    create_coop_register_patcher_task,
    create_coop_unregister_patchers_task,
)
from taac.testconfigs.fboss_solution_tests.network_ai_hardening_test_config import (
    get_rtsw_ixia_peer_group_tasks,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import TestConfig, TrafficEndpoint


# ============================================================
# Device: rtsw002.c082.f00.snc1 (RTSW, FBOSS Minipack2/W400)
#
# IXIA Port Mappings (from LLDP after ixia02 reboot):
#   eth2/1/1 -> Ixia 1/47 (200G)
#   eth2/5/1 -> Ixia 1/45 (200G)
#
# RTSW Interface IPs (existing, no changes):
#   eth2/1/1: 2401:db00:11b:4001::a/64 (VLAN 2001)
#   eth2/5/1: 2401:db00:11b:4801::a/64 (VLAN 2003)
#
# IXIA IPs (on same /64 subnet):
#   Ixia 1/47: 2401:db00:11b:4001::10
#   Ixia 1/45: 2401:db00:11b:4801::10
# ============================================================

RTSW002_DEVICE_NAME = "rtsw002.c082.f00.snc1"
RTSW002_DEVICE_FQDN = "rtsw002.c082.f00.snc1.tfbnw.net"
IXIA_CHASSIS_IP = "2401:db00:116:3019::3000"

RTSW002_IXIA_PORTS = ["eth2/1/1", "eth2/5/1"]

# Direct IXIA connections — bypasses LLDP discovery
RTSW002_DIRECT_IXIA_CONNECTIONS = [
    taac_types.DirectIxiaConnection(
        interface="eth2/1/1",
        ixia_chassis_ip=IXIA_CHASSIS_IP,
        ixia_port="1/47",
    ),
    taac_types.DirectIxiaConnection(
        interface="eth2/5/1",
        ixia_chassis_ip=IXIA_CHASSIS_IP,
        ixia_port="1/45",
    ),
]

# Endpoint definition
RTSW002_ENDPOINTS = [
    taac_types.Endpoint(
        name=RTSW002_DEVICE_NAME,
        dut=True,
        ixia_needed=True,
        ixia_ports=RTSW002_IXIA_PORTS,
        direct_ixia_connections=RTSW002_DIRECT_IXIA_CONNECTIONS,
    ),
]

# Traffic endpoints
RTSW002_SRC_TRAFFIC_ENDPOINTS = [
    TrafficEndpoint(name=f"{RTSW002_DEVICE_NAME}:eth2/1/1"),
]

RTSW002_DST_TRAFFIC_ENDPOINTS = [
    TrafficEndpoint(name=f"{RTSW002_DEVICE_NAME}:eth2/5/1"),
]

# ============================================================
# Setup Tasks — COOP patchers to configure BGP on rtsw002
# ============================================================

RTSW002_SETUP_TASKS = (
    [
        create_coop_unregister_patchers_task(RTSW002_DEVICE_NAME),
    ]
    + get_rtsw_ixia_peer_group_tasks(RTSW002_DEVICE_NAME)
    + [
        # Apply peer group patchers to bgpd
        create_coop_apply_patchers_task(
            hostnames=[RTSW002_DEVICE_NAME],
            config_name="bgpcpp",
        ),
        # Configure BGP peer on eth2/1/1 (IXIA AS 65008)
        create_configure_parallel_bgp_peers_task(
            hostname=RTSW002_DEVICE_NAME,
            configure_vlans_patcher_name="configure_vlans_ixia_port1",
            add_bgp_peers_patcher_name="add_bgp_peers_ixia_port1",
            config_json=json.dumps(
                {
                    "eth2/1/1": [
                        {
                            "starting_ip": "2401:db00:11b:4001::a",
                            "increment_ip": "::",
                            "prefix_length": 64,
                            "description": "IXIA port 1/47 (AS 65008)",
                            "peer_group_name": "PEERGROUP_RTSW_IXIA_V6",
                            "num_sessions": 1,
                            "remote_as_4_byte": 65008,
                            "remote_as_4_byte_step": 0,
                            "gateway_starting_ip": "2401:db00:11b:4001::10",
                            "gateway_increment_ip": "::",
                        },
                    ]
                }
            ),
        ),
        # Configure BGP peer on eth2/5/1 (IXIA AS 65009)
        create_configure_parallel_bgp_peers_task(
            hostname=RTSW002_DEVICE_NAME,
            configure_vlans_patcher_name="configure_vlans_ixia_port2",
            add_bgp_peers_patcher_name="add_bgp_peers_ixia_port2",
            config_json=json.dumps(
                {
                    "eth2/5/1": [
                        {
                            "starting_ip": "2401:db00:11b:4801::a",
                            "increment_ip": "::",
                            "prefix_length": 64,
                            "description": "IXIA port 1/45 (AS 65009)",
                            "peer_group_name": "PEERGROUP_RTSW_IXIA_V6",
                            "num_sessions": 1,
                            "remote_as_4_byte": 65009,
                            "remote_as_4_byte_step": 0,
                            "gateway_starting_ip": "2401:db00:11b:4801::10",
                            "gateway_increment_ip": "::",
                        },
                    ]
                }
            ),
        ),
        # Re-add CTSW iBGP peers (cleared by coop_unregister_patchers at start)
        # These are needed for CTSW↔RTSW traffic flow during qualification
        create_coop_register_patcher_task(
            hostname=RTSW002_DEVICE_NAME,
            config_name="bgpcpp",
            patcher_name="add_bgp_peers_ctsw_ibgp",
            task_name="add_bgp_peers",
            py_func_name="add_bgp_peers",
            patcher_args={
                "peer_configs": json.dumps(
                    [
                        {
                            "local_addr": "2401:db00:e011:250:1000::91",
                            "peer_addr": "2401:db00:e011:250:1000::90",
                            "peer_group_name": "PEERGROUP_RTSW_CTSW_V6",
                            "remote_as_4_byte": "65392",
                            "description": "ctsw001 FH0/1/0/0",
                        },
                        {
                            "local_addr": "2401:db00:e011:251:1000::d",
                            "peer_addr": "2401:db00:e011:251:1000::c",
                            "peer_group_name": "PEERGROUP_RTSW_CTSW_V6",
                            "remote_as_4_byte": "65392",
                            "description": "ctsw002 FH0/0/0/3",
                        },
                    ]
                ),
            },
        ),
        # Apply all patchers with warmboot
        create_coop_apply_patchers_task(
            hostnames=[RTSW002_DEVICE_NAME],
            do_warmboot=True,
        ),
    ]
)

# Teardown tasks
RTSW002_TEARDOWN_TASKS = [
    create_coop_unregister_patchers_task(RTSW002_DEVICE_NAME),
]

# ============================================================
# IXIA Port Configs (IXIA side BGP)
# Note: endpoint uses FQDN for FBOSS devices
# ============================================================

RTSW002_PORT_CONFIGS = [
    # Port eth2/1/1 — IXIA AS 65008
    taac_types.BasicPortConfig(
        endpoint=f"{RTSW002_DEVICE_FQDN}:eth2/1/1",
        device_group_configs=[
            taac_types.DeviceGroupConfig(
                device_group_index=0,
                v6_addresses_config=taac_types.IpAddressesConfig(
                    starting_ip="2401:db00:11b:4001::10",
                    increment_ip="::",
                    gateway_starting_ip="2401:db00:11b:4001::a",
                    gateway_increment_ip="::",
                    mask=64,
                ),
                v6_bgp_config=taac_types.BgpConfig(
                    local_as_4_bytes=65008,
                    enable_4_byte_local_as=True,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                    route_scales=[
                        taac_types.RouteScaleSpec(
                            v6_route_scale=taac_types.RouteScale(
                                multiplier=1,
                                prefix_count=100,
                                prefix_length=64,
                                starting_prefixes="5000:5::",
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                            ),
                        )
                    ],
                    graceful_restart_timer=180,
                ),
            )
        ],
    ),
    # Port eth2/5/1 — IXIA AS 65009
    taac_types.BasicPortConfig(
        endpoint=f"{RTSW002_DEVICE_FQDN}:eth2/5/1",
        device_group_configs=[
            taac_types.DeviceGroupConfig(
                device_group_index=0,
                v6_addresses_config=taac_types.IpAddressesConfig(
                    starting_ip="2401:db00:11b:4801::10",
                    increment_ip="::",
                    gateway_starting_ip="2401:db00:11b:4801::a",
                    gateway_increment_ip="::",
                    mask=64,
                ),
                v6_bgp_config=taac_types.BgpConfig(
                    local_as_4_bytes=65009,
                    enable_4_byte_local_as=True,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                    route_scales=[
                        taac_types.RouteScaleSpec(
                            v6_route_scale=taac_types.RouteScale(
                                multiplier=1,
                                prefix_count=100,
                                prefix_length=64,
                                starting_prefixes="5000:6::",
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                            ),
                        )
                    ],
                    graceful_restart_timer=180,
                ),
            )
        ],
    ),
]

# Traffic item config
RTSW002_TRAFFIC_ITEM_CONFIGS = [
    taac_types.BasicTrafficItemConfig(
        name="RTSW002_SNC1_TRAFFIC",
        src_endpoints=RTSW002_SRC_TRAFFIC_ENDPOINTS,
        dest_endpoints=RTSW002_DST_TRAFFIC_ENDPOINTS,
        line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
        line_rate=50,
        traffic_type=ixia_types.TrafficType.IPV6,
        bidirectional=True,
    ),
]

# Packet loss check
RTSW002_IXIA_PACKET_LOSS_CHECK = create_ixia_packet_loss_check(
    thresholds=[
        hc_types.PacketLossThreshold(
            names=["RTSW002_SNC1_TRAFFIC"],
            str_value="0",
            metric=hc_types.PacketLossMetric.PERCENTAGE,
        ),
    ],
)

# ============================================================
# Test Config: Longevity test
# ============================================================

RTSW002_LONGEVITY_TEST_CONFIG = TestConfig(
    name="RTSW002_LONGEVITY_TEST_CONFIG",
    basset_pool="dne.regression",
    endpoints=RTSW002_ENDPOINTS,
    basic_traffic_item_configs=RTSW002_TRAFFIC_ITEM_CONFIGS,
    basic_port_configs=RTSW002_PORT_CONFIGS,
    setup_tasks=RTSW002_SETUP_TASKS,
    teardown_tasks=RTSW002_TEARDOWN_TASKS,
    playbooks=[
        create_rtsw_longevity_playbook(
            rtsw_id=2,
            ixia_packet_loss_check=RTSW002_IXIA_PACKET_LOSS_CHECK,
        ),
    ],
)

RTSW002_TEST_CONFIGS = [
    RTSW002_LONGEVITY_TEST_CONFIG,
]
