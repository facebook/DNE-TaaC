# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe

"""
RTSW SNC1 Testbed — IXIA EBGP Test Configs
FBOSS RTSW devices peering with IXIA traffic generators.

Testbed Topology (rtsw001):
  rtsw001 eth1/19/1 (2401:db00:11b:4400::a/64) → Ixia 1/37, AS 65006
  rtsw001 eth1/21/1 (2401:db00:11b:4800::a/64) → Ixia 1/27, AS 65007

RTSW BGP config is applied via COOP patchers (setup_tasks).
IXIA config is applied by TAAC framework (basic_port_configs).

Note: rtsw001 had a COOP "full override" issue on 2026-04-09 that blocked
bgpcpp patchers. Retry if the issue is resolved. The rtsw002 sibling
testbed configuration lives in `rtsw002_longevity_test_config.py`
(Phase 3-161 relocation; orphan, not in INTERNAL_TEST_CONFIGS).
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


# NOTE: The RTSW002_* chain that previously lived here (lines 59-340)
# was relocated to `rtsw002_longevity_test_config.py` in Phase 3-161.
# It was orphan code — defined but never registered in
# INTERNAL_TEST_CONFIGS — so it was carved out into its own file and
# re-exported via the package `__init__.py` for future use without
# changing the golden manifest hash.

# ============================================================
# Device: rtsw001.c082.f00.snc1 (RTSW, FBOSS Minipack2/W400)
#
# IXIA Port Mappings (from LLDP after ixia02 reboot):
#   eth1/19/1 → Ixia 1/37 (200G)
#   eth1/21/1 → Ixia 1/27 (200G)
#
# RTSW Interface IPs (existing, no changes):
#   eth1/19/1: 2401:db00:11b:4400::a/64 (VLAN 2002)
#   eth1/21/1: 2401:db00:11b:4800::a/64 (VLAN 2003)
#
# IXIA IPs (on same /64 subnet):
#   Ixia 1/37: 2401:db00:11b:4400::10
#   Ixia 1/27: 2401:db00:11b:4800::10
#
# NOTE: rtsw001 had COOP "full override" issue on 2026-04-09.
#       Retry if issue is resolved.
# ============================================================

IXIA_CHASSIS_IP = "2401:db00:116:3019::3000"

RTSW001_DEVICE_NAME = "rtsw001.c082.f00.snc1"
RTSW001_DEVICE_FQDN = "rtsw001.c082.f00.snc1.tfbnw.net"

RTSW001_IXIA_PORTS = ["eth1/19/1", "eth1/21/1"]

RTSW001_DIRECT_IXIA_CONNECTIONS = [
    taac_types.DirectIxiaConnection(
        interface="eth1/19/1",
        ixia_chassis_ip=IXIA_CHASSIS_IP,
        ixia_port="1/37",
    ),
    taac_types.DirectIxiaConnection(
        interface="eth1/21/1",
        ixia_chassis_ip=IXIA_CHASSIS_IP,
        ixia_port="1/27",
    ),
]

RTSW001_ENDPOINTS = [
    taac_types.Endpoint(
        name=RTSW001_DEVICE_NAME,
        dut=True,
        ixia_needed=True,
        ixia_ports=RTSW001_IXIA_PORTS,
        direct_ixia_connections=RTSW001_DIRECT_IXIA_CONNECTIONS,
    ),
]

RTSW001_SRC_TRAFFIC_ENDPOINTS = [
    TrafficEndpoint(name=f"{RTSW001_DEVICE_NAME}:eth1/19/1"),
]

RTSW001_DST_TRAFFIC_ENDPOINTS = [
    TrafficEndpoint(name=f"{RTSW001_DEVICE_NAME}:eth1/21/1"),
]

RTSW001_SETUP_TASKS = (
    [
        create_coop_unregister_patchers_task(RTSW001_DEVICE_NAME),
    ]
    + get_rtsw_ixia_peer_group_tasks(RTSW001_DEVICE_NAME)
    + [
        create_coop_apply_patchers_task(
            hostnames=[RTSW001_DEVICE_NAME],
            config_name="bgpcpp",
        ),
        create_configure_parallel_bgp_peers_task(
            hostname=RTSW001_DEVICE_NAME,
            configure_vlans_patcher_name="configure_vlans_ixia_port1",
            add_bgp_peers_patcher_name="add_bgp_peers_ixia_port1",
            config_json=json.dumps(
                {
                    "eth1/19/1": [
                        {
                            "starting_ip": "2401:db00:11b:4400::a",
                            "increment_ip": "::",
                            "prefix_length": 64,
                            "description": "IXIA port 1/37 (AS 65006)",
                            "peer_group_name": "PEERGROUP_RTSW_IXIA_V6",
                            "num_sessions": 1,
                            "remote_as_4_byte": 65006,
                            "remote_as_4_byte_step": 0,
                            "gateway_starting_ip": "2401:db00:11b:4400::10",
                            "gateway_increment_ip": "::",
                        },
                    ]
                }
            ),
        ),
        create_configure_parallel_bgp_peers_task(
            hostname=RTSW001_DEVICE_NAME,
            configure_vlans_patcher_name="configure_vlans_ixia_port2",
            add_bgp_peers_patcher_name="add_bgp_peers_ixia_port2",
            config_json=json.dumps(
                {
                    "eth1/21/1": [
                        {
                            "starting_ip": "2401:db00:11b:4800::a",
                            "increment_ip": "::",
                            "prefix_length": 64,
                            "description": "IXIA port 1/27 (AS 65007)",
                            "peer_group_name": "PEERGROUP_RTSW_IXIA_V6",
                            "num_sessions": 1,
                            "remote_as_4_byte": 65007,
                            "remote_as_4_byte_step": 0,
                            "gateway_starting_ip": "2401:db00:11b:4800::10",
                            "gateway_increment_ip": "::",
                        },
                    ]
                }
            ),
        ),
        # Re-add CTSW iBGP peers (cleared by coop_unregister_patchers at start)
        create_coop_register_patcher_task(
            hostname=RTSW001_DEVICE_NAME,
            config_name="bgpcpp",
            patcher_name="add_bgp_peers_ctsw_ibgp",
            task_name="add_bgp_peers",
            py_func_name="add_bgp_peers",
            patcher_args={
                "peer_configs": json.dumps(
                    [
                        {
                            "local_addr": "2401:db00:e011:258:1000::1",
                            "peer_addr": "2401:db00:e011:258:1000::0",
                            "peer_group_name": "PEERGROUP_RTSW_CTSW_V6",
                            "remote_as_4_byte": "65392",
                            "description": "ctsw001 FH0/1/0/12",
                        },
                        {
                            "local_addr": "2401:db00:e011:251:1000::1",
                            "peer_addr": "2401:db00:e011:251:1000::0",
                            "peer_group_name": "PEERGROUP_RTSW_CTSW_V6",
                            "remote_as_4_byte": "65392",
                            "description": "ctsw002 FH0/0/0/0",
                        },
                    ]
                ),
            },
        ),
        create_coop_apply_patchers_task(
            hostnames=[RTSW001_DEVICE_NAME],
            do_warmboot=True,
        ),
    ]
)

RTSW001_TEARDOWN_TASKS = [
    create_coop_unregister_patchers_task(RTSW001_DEVICE_NAME),
]

RTSW001_PORT_CONFIGS = [
    taac_types.BasicPortConfig(
        endpoint=f"{RTSW001_DEVICE_FQDN}:eth1/19/1",
        device_group_configs=[
            taac_types.DeviceGroupConfig(
                device_group_index=0,
                v6_addresses_config=taac_types.IpAddressesConfig(
                    starting_ip="2401:db00:11b:4400::10",
                    increment_ip="::",
                    gateway_starting_ip="2401:db00:11b:4400::a",
                    gateway_increment_ip="::",
                    mask=64,
                ),
                v6_bgp_config=taac_types.BgpConfig(
                    local_as_4_bytes=65006,
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
    taac_types.BasicPortConfig(
        endpoint=f"{RTSW001_DEVICE_FQDN}:eth1/21/1",
        device_group_configs=[
            taac_types.DeviceGroupConfig(
                device_group_index=0,
                v6_addresses_config=taac_types.IpAddressesConfig(
                    starting_ip="2401:db00:11b:4800::10",
                    increment_ip="::",
                    gateway_starting_ip="2401:db00:11b:4800::a",
                    gateway_increment_ip="::",
                    mask=64,
                ),
                v6_bgp_config=taac_types.BgpConfig(
                    local_as_4_bytes=65007,
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

RTSW001_TRAFFIC_ITEM_CONFIGS = [
    taac_types.BasicTrafficItemConfig(
        name="RTSW001_SNC1_TRAFFIC",
        src_endpoints=RTSW001_SRC_TRAFFIC_ENDPOINTS,
        dest_endpoints=RTSW001_DST_TRAFFIC_ENDPOINTS,
        line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
        line_rate=50,
        traffic_type=ixia_types.TrafficType.IPV6,
        bidirectional=True,
    ),
]

RTSW001_IXIA_PACKET_LOSS_CHECK = create_ixia_packet_loss_check(
    thresholds=[
        hc_types.PacketLossThreshold(
            names=["RTSW001_SNC1_TRAFFIC"],
            str_value="0",
            metric=hc_types.PacketLossMetric.PERCENTAGE,
        ),
    ],
)

RTSW001_LONGEVITY_TEST_CONFIG = TestConfig(
    name="RTSW001_LONGEVITY_TEST_CONFIG",
    basset_pool="dne.regression",
    endpoints=RTSW001_ENDPOINTS,
    basic_traffic_item_configs=RTSW001_TRAFFIC_ITEM_CONFIGS,
    basic_port_configs=RTSW001_PORT_CONFIGS,
    setup_tasks=RTSW001_SETUP_TASKS,
    teardown_tasks=RTSW001_TEARDOWN_TASKS,
    playbooks=[
        create_rtsw_longevity_playbook(
            rtsw_id=1,
            ixia_packet_loss_check=RTSW001_IXIA_PACKET_LOSS_CHECK,
        ),
    ],
)

RTSW001_TEST_CONFIGS = [
    RTSW001_LONGEVITY_TEST_CONFIG,
]
