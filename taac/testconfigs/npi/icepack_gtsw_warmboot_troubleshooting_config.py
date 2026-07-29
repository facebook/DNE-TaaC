# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""NPI IcePack GTSW agent-warmboot + RoCE troubleshooting TestConfig.

Single-device config on ``gtsw007.l1001.c085.ash6`` (TH6 IcePack GTSW): run
RoCE (RDMA/IB) traffic from IXIA port ``eth1/1/1`` -> ``eth1/1/3``, warmboot the
FBOSS agent via ``systemctl restart``, wait for agent convergence, hold a
longevity window, then verify zero traffic loss / rate drop / discards and that
only the expected agent-warmboot service cascade restarted. Intended for
hands-on warmboot troubleshooting on a single GTSW.

IXIA is on chassis ``ixia23.netcastle.ash6`` (both ports). The two IXIA-facing
RIFs are ``downlink_1`` (VLAN 2001 / intfID 2001, eth1/1/1) and ``downlink_2``
(VLAN 2002 / intfID 2002, eth1/1/3). Live on 2026-07-28, eth1/1/1 already has
global ``2401:db00:206a:c600::a/64`` but eth1/1/3 (intfID 2002) had an EMPTY
``ipAddresses`` list -> no connected route, so RoCE traffic could not be routed
across the box and IXIA setup failed to build the dst device group. A setup
task therefore provisions eth1/1/3 with ``2401:db00:206a:c602::a/64`` (mirrors
the eth1/1/1 pattern; ``c?00`` -> ``c?02``) via the COOP
``configure_interfaces_ip_addresses`` agent patcher, applied with a warmboot,
and unregistered on teardown.
"""

import json

from ixia.ixia import types as ixia_types
from taac.packet_headers import DSF_RDMA_IB_PACKET_HEADERS
from taac.playbooks.playbook_definitions import (
    create_icepack_gtsw_warmboot_troubleshooting_playbook,
)
from taac.task_definitions import (
    create_coop_apply_patchers_task,
    create_coop_register_patcher_task,
    create_coop_unregister_patchers_task,
)
from taac.testconfigs.fboss_solution_tests.network_ai_test_configs import (
    IXIA_ENABLE_PFC_PORT_CONFIG,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import (
    BasicPortConfig,
    BasicTrafficItemConfig,
    DeviceGroupConfig,
    Endpoint,
    IpAddressesConfig,
    TestConfig,
    TrafficEndpoint,
)

_HOSTNAME = "gtsw007.l1001.c085.ash6"
_SRC_PORT = "eth1/1/1"
_DST_PORT = "eth1/1/3"

_TRAFFIC_ITEM_NAME = "ICEPACK_GTSW007_WARMBOOT_ROCE_TRAFFIC"

# IXIA-emulated-host / switch-gateway addressing per IXIA-facing RIF. Gateways
# match the switch's on-box interface addresses (eth1/1/1 pre-existing;
# eth1/1/3 provisioned by the setup task below).
_SRC_PARENT_V6 = "2401:db00:206a:c600"  # eth1/1/1, VLAN 2001 (downlink_1)
_DST_PARENT_V6 = "2401:db00:206a:c602"  # eth1/1/3, VLAN 2002 (downlink_2)

# Reuse the PFC-enabling L1 config (enable_fcoe + PFC priority->queue map) that
# the shared NSF/PFC configs use, applied per-port so it survives alongside the
# explicit device-group addressing.
_PFC_L1_CONFIG = IXIA_ENABLE_PFC_PORT_CONFIG.l1_config

ICEPACK_GTSW007_WARMBOOT_ENDPOINTS = [
    Endpoint(
        name=_HOSTNAME,
        dut=True,
        ixia_ports=[_SRC_PORT, _DST_PORT],
    ),
]

# Provision eth1/1/3 (intfID 2002 / VLAN 2002) with a global IPv6 so the switch
# has a connected route to the dst IXIA subnet. portID="-1" is a sentinel that
# matches no real port, so the patcher only updates the intfID-2002 RIF and does
# not clobber other VLAN RIFs (which share portID default). Mirrors eth1/1/1's
# address list (keeps the FBOSS well-known link-local + adds the global).
_PROVISION_ETH1_1_3_IP_SETUP_TASKS = [
    create_coop_unregister_patchers_task(_HOSTNAME),
    create_coop_register_patcher_task(
        hostname=_HOSTNAME,
        config_name="agent",
        patcher_name="provision_eth1_1_3_ipv6",
        py_func_name="configure_interfaces_ip_addresses",
        patcher_args={
            _DST_PORT: json.dumps(
                {
                    "ip_addresses": [
                        "fe80::be:face:b00c/64",
                        f"{_DST_PARENT_V6}::a/64",
                    ],
                    "intfId": "2002",
                    "portID": "-1",
                    "vlanId": "2002",
                    "mtu": "9000",
                    "rif_name": "downlink_2",
                }
            )
        },
    ),
    create_coop_apply_patchers_task(
        hostnames=[_HOSTNAME],
        config_name="agent",
        do_warmboot=True,
    ),
]

NPI_ICEPACK_GTSW007_WARMBOOT_TROUBLESHOOTING_TEST_CONFIG = TestConfig(
    name="NPI_ICEPACK_GTSW007_WARMBOOT_TROUBLESHOOTING_TEST_CONFIG",
    basset_pool="networkai.test",
    endpoints=ICEPACK_GTSW007_WARMBOOT_ENDPOINTS,
    # Explicit addressing changes the IXIA topology, so opt out of the
    # content-blind IXIA config cache to avoid a stale session overriding it.
    ixia_config_cache=taac_types.IxiaConfigCache(enabled=False),
    setup_tasks=_PROVISION_ETH1_1_3_IP_SETUP_TASKS,
    teardown_tasks=[
        create_coop_unregister_patchers_task(_HOSTNAME),
    ],
    basic_traffic_item_configs=[
        BasicTrafficItemConfig(
            name=_TRAFFIC_ITEM_NAME,
            src_endpoints=[
                TrafficEndpoint(
                    name=f"{_HOSTNAME}:{_SRC_PORT}",
                    device_group_index=0,
                )
            ],
            dest_endpoints=[
                TrafficEndpoint(
                    name=f"{_HOSTNAME}:{_DST_PORT}",
                    device_group_index=0,
                )
            ],
            line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
            line_rate=50,
            traffic_type=ixia_types.TrafficType.IPV6,
            bidirectional=False,
            packet_headers=DSF_RDMA_IB_PACKET_HEADERS,
            full_mesh=False,
            src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
            frame_size_settings=ixia_types.FrameSize(
                type=ixia_types.FrameSizeType.FIXED,
                fixed_size=4000,
            ),
        )
    ],
    basic_port_configs=[
        BasicPortConfig(
            endpoint=f"{_HOSTNAME}:{_SRC_PORT}",
            l1_config=_PFC_L1_CONFIG,
            device_group_configs=[
                DeviceGroupConfig(
                    device_group_index=0,
                    tag_name="SRC_L3_TRAFFIC",
                    multiplier=1,
                    v6_addresses_config=IpAddressesConfig(
                        starting_ip=f"{_SRC_PARENT_V6}::b",
                        increment_ip="::",
                        gateway_starting_ip=f"{_SRC_PARENT_V6}::a",
                        gateway_increment_ip="::",
                        mask=64,
                    ),
                ),
            ],
        ),
        BasicPortConfig(
            endpoint=f"{_HOSTNAME}:{_DST_PORT}",
            l1_config=_PFC_L1_CONFIG,
            device_group_configs=[
                DeviceGroupConfig(
                    device_group_index=0,
                    tag_name="DST_L3_TRAFFIC",
                    multiplier=1,
                    v6_addresses_config=IpAddressesConfig(
                        starting_ip=f"{_DST_PARENT_V6}::b",
                        increment_ip="::",
                        gateway_starting_ip=f"{_DST_PARENT_V6}::a",
                        gateway_increment_ip="::",
                        mask=64,
                    ),
                ),
            ],
        ),
    ],
    playbooks=[
        create_icepack_gtsw_warmboot_troubleshooting_playbook(
            name="test_icepack_gtsw007_warmboot_troubleshooting",
            traffic_item_name=_TRAFFIC_ITEM_NAME,
        )
    ],
)
