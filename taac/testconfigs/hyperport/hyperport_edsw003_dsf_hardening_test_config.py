# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
DSF Hardening Test Configuration for EDSW003.N001.L201.SNC1

Adapted from dsf_hardening_test_config.py (RDSW pattern) for EDSW with 2 IXIA ports.
EDSW003.N001 uplinks to BAG in the DSF SNC topology.

Topology:
  IXIA (downlink) -- eth1/17/1 -- [EDSW003.N001] -- eth1/23/1 -- IXIA (uplink, iBGP peer)

IXIA simulates an iBGP peer (same AS 65062) on the uplink port, injecting
routes with community 65446:30. Traffic flows downlink→uplink through the DUT.

IXIA Port Mapping (from hyperport_snc_bag_test_configs.py):
  edsw003.n001.l201.snc1:eth1/17/1  -- downlink (L3 traffic, no BGP)
  edsw003.n001.l201.snc1:eth1/23/1  -- uplink (iBGP peer, route injection)

BGP Config (confirmed via fboss2 show config running bgp):
  EDSW003.N001 ASN: 65062
  Peer group: PEERGROUP_EDSW_BAG_V6 (already exists on device)
  Ingress policy: PROPAGATE_EVERYTHING
  Egress policy: PROPAGATE_EVERYTHING
Usage:
  buck2 run neteng/netcastle:netcastle_taac -- --team taac \
    --test-config EDSW003_N001_L201_SNC1_DSF_HARDENING \
    --dev --debug \
    --skip-basset-reservation --skip-testbed-isolation \
    --skip-failed-setup-cleanup --skip-ixia-cleanup \
    --skip-teardown-task --regex 'longevity' \
    --ixia-api-server 2401:db00:116:3167:21a:c5ff:fe01:7173
"""

import json

from ixia.ixia import types as ixia_types
from taac.packet_headers import DSF_RDMA_PACKET_HEADERS
from taac.playbooks.playbook_definitions import (
    create_edsw003_dsf_hardening_agent_warmboot_playbook,
    create_edsw003_dsf_hardening_longevity_playbook,
    HYPERPORT_EDSW003_DSF_HARDENING_TRAFFIC_ITEM_GOLDEN as TRAFFIC_ITEM_GOLDEN,
)
from taac.task_definitions import (
    create_coop_apply_patchers_task,
    create_coop_register_patcher_task,
    create_coop_unregister_patchers_task,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import TestConfig

# =============================================================================
# Constants
# =============================================================================

# DSF frame sizes (standard DSF IMIX)
DSF_FRAME_SIZES = ixia_types.FrameSize(
    type=ixia_types.FrameSizeType.CUSTOM_IMIX,
    imix_weight={94: 1, 96: 18, 192: 3, 512: 1, 1200: 1, 4600: 76},
)

# DSF L1 config with PFC queue mapping
DSF_L1_CONFIG = ixia_types.L1Config(
    enable_fcoe=True,
    flow_control_config=ixia_types.FlowControlConfig(
        pfc_prority_groups_config=ixia_types.PfcPriorityGroupsConfig(
            priority0_pfc_queue=ixia_types.PfcQueue.TWO,
            priority1_pfc_queue=ixia_types.PfcQueue.ONE,
            priority2_pfc_queue=ixia_types.PfcQueue.ZERO,
            priority3_pfc_queue=ixia_types.PfcQueue.THREE,
        ),
        enable_pfc_pause_delay=False,
    ),
)

# EDSW BGP communities for route injection
EDSW_BGP_COMMUNITIES = ["65446:30", "65441:1028", "65529:52780", "65529:52779"]


# =============================================================================
# Test Config Factory (2-port DSF hardening, no rogue/NDP stressor)
# =============================================================================
def test_config_for_dsf_hardening_2port(
    test_config_name,
    device_name,
    local_mac_address,
    ixia_downlink_interface,
    ixia_uplink_interface,
    peergroup_uplink_v6,
    ixia_downlink_ic_parent_network_v6,
    ixia_uplink_ic_parent_network_v6,
    prefix_limit,
    per_peer_max_route_limit,
    uplink_peer_count,
    remote_uplink_as_4byte,
    is_uplink_peer_confed,
    playbooks=None,
    direct_ixia_connections=None,
    basset_pool=None,
):
    """
    DSF hardening test config for 2-port EDSW variant.

    - Downlink port: L3 traffic, no BGP
    - Uplink port: iBGP peer, route injection

    COOP patcher adds an IXIA BGP peer to the existing peer group.
    IXIA injects 2048 golden prefixes (5000:dd::/64) via iBGP on the uplink.
    Traffic flows from downlink to uplink destinations.
    Agent warmboot playbook validates service convergence and packet loss.
    """
    return TestConfig(
        name=test_config_name,
        ixia_protocol_verification_timeout=900,
        # skip_ixia_protocol_verification=True,
        basset_pool=basset_pool,
        endpoints=[
            taac_types.Endpoint(
                name=device_name,
                ixia_ports=[
                    ixia_downlink_interface,
                    ixia_uplink_interface,
                ],
                dut=True,
                mac_address=local_mac_address,
                direct_ixia_connections=direct_ixia_connections
                if direct_ixia_connections
                else [],
            ),
        ],
        setup_tasks=[
            create_coop_unregister_patchers_task(device_name),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="add_bgp_peers_dut",
                task_name="add_bgp_peers",
                py_func_name="add_bgp_peers",
                patcher_args={
                    "peer_configs": json.dumps(
                        [
                            {
                                "local_addr": f"{ixia_uplink_ic_parent_network_v6}::",
                                "peer_addr": f"{ixia_uplink_ic_parent_network_v6}::1",
                                "peer_group_name": peergroup_uplink_v6,
                                "remote_as_4_byte": str(remote_uplink_as_4byte),
                                "description": "ixia_session",
                            }
                        ]
                    ),
                },
            ),
            create_coop_apply_patchers_task(
                hostnames=[device_name],
                do_warmboot=True,
            ),
        ],
        teardown_tasks=[
            create_coop_unregister_patchers_task(device_name),
        ],
        # Deprecated - define at playbook level
        # periodic_tasks=[],
        basic_port_configs=[
            # Downlink port (L3 traffic, no BGP)
            taac_types.BasicPortConfig(
                l1_config=DSF_L1_CONFIG,
                endpoint=f"{device_name}:{ixia_downlink_interface}",
                device_group_configs=[
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        tag_name="DOWNLINK_L3_TRAFFIC",
                        multiplier=1,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_downlink_ic_parent_network_v6}::1",
                            increment_ip="::",
                            gateway_starting_ip=f"{ixia_downlink_ic_parent_network_v6}::",
                            gateway_increment_ip="::",
                            mask=127,
                        ),
                    ),
                ],
            ),
            # Uplink port (iBGP peer, route injection)
            taac_types.BasicPortConfig(
                l1_config=DSF_L1_CONFIG,
                endpoint=f"{device_name}:{ixia_uplink_interface}",
                device_group_configs=[
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        tag_name="BGP_ROUTE_INJECTOR",
                        multiplier=uplink_peer_count,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_uplink_ic_parent_network_v6}::1",
                            increment_ip="::",
                            gateway_starting_ip=f"{ixia_uplink_ic_parent_network_v6}::",
                            gateway_increment_ip="::",
                            mask=127,
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_uplink_as_4byte,
                            local_as_increment=0,
                            enable_4_byte_local_as=True,
                            bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                            is_confed=is_uplink_peer_confed == "True",
                            bgp_capabilities=[
                                ixia_types.BgpCapability.IpV6Unicast,
                                ixia_types.BgpCapability.Ipv6UnicastAddPath,
                            ],
                            custom_network_group_configs=[
                                ixia_types.CustomNetworkGroupConfig(
                                    device_group_name="BGP_ROUTE_INJECTOR",
                                    network_group_name="uplink_golden_prefixes",
                                    network_group_multiplier=2048,
                                    prefix_start_value="5000:dd::",
                                    prefix_length=64,
                                    nexthop_start_value=f"{ixia_uplink_ic_parent_network_v6}::1",
                                    nexthop_increments="::1",
                                    ecmp_width=1,
                                    community_list=EDSW_BGP_COMMUNITIES,
                                    network_group_index=0,
                                ),
                            ],
                        ),
                    ),
                ],
            ),
        ],
        traffic_items_to_start=[f"(?!{device_name.upper()}_HIGH_QUEUE_BGP_CP_TRAFFIC)"],
        basic_traffic_item_configs=[
            taac_types.BasicTrafficItemConfig(
                name=TRAFFIC_ITEM_GOLDEN,
                bidirectional=False,
                merge_destinations=True,
                line_rate=30,
                line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
                src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=0,
                        network_group_index=0,
                    ),
                ],
                traffic_type=ixia_types.TrafficType.IPV6,
                tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
                frame_size_settings=DSF_FRAME_SIZES,
                packet_headers=DSF_RDMA_PACKET_HEADERS,
            ),
        ],
        # Deprecated - define at playbook level
        # snapshot_checks (moved to each playbook)
        # Deprecated - define at playbook level
        # postchecks (moved to each playbook)
        # Deprecated - define at playbook level
        # prechecks (moved to each playbook)
        playbooks=[
            create_edsw003_dsf_hardening_longevity_playbook(
                device_name=device_name,
                prefix_limit=prefix_limit,
            ),
            create_edsw003_dsf_hardening_agent_warmboot_playbook(
                device_name=device_name,
                prefix_limit=prefix_limit,
            ),
        ],
    )


# =============================================================================
# Config Instance: edsw003.n001.l201.snc1
# =============================================================================
EDSW003_N001_DSF_HARDENING_TEST_CONFIGS = [
    test_config_for_dsf_hardening_2port(
        test_config_name="EDSW003_N001_L201_SNC1_DSF_HARDENING",
        device_name="edsw003.n001.l201.snc1",
        local_mac_address="02:00:00:00:0f:0b",
        ixia_downlink_interface="eth1/17/1",
        ixia_uplink_interface="eth1/23/1",
        peergroup_uplink_v6="PEERGROUP_EDSW_BAG_V6",
        ixia_downlink_ic_parent_network_v6="2401:db00:11b:d8c0",
        ixia_uplink_ic_parent_network_v6="2401:db00:11b:d8c1",
        prefix_limit="75000",
        per_peer_max_route_limit="25000",
        uplink_peer_count=1,
        remote_uplink_as_4byte=65062,
        is_uplink_peer_confed="False",
        basset_pool="networkai.test",
        direct_ixia_connections=[
            taac_types.DirectIxiaConnection(
                interface="eth1/17/1",
                ixia_chassis_ip="2401:db00:116:3167:21a:c5ff:fe01:7173",
                ixia_port="1/5",
            ),
            taac_types.DirectIxiaConnection(
                interface="eth1/23/1",
                ixia_chassis_ip="2401:db00:116:3167:21a:c5ff:fe01:7173",
                ixia_port="1/6",
            ),
        ],
    )
]
