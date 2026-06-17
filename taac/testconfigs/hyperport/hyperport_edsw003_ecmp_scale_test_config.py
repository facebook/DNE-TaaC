# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
ECMP Scale Test Configuration for EDSW003.N001.L201.SNC1 (3-port topology)

Adapts the RDSW DSF hardening 3-port pattern (dsf_hardening_test_config.py)
for EDSW003 using a borrowed downlink port from neighboring BAG001.SNC1.

The 3-port topology is required because a DUT physical port can only reliably
support 1 MAC address. Wide ECMP (2048 nexthops) requires NDP resolution on a
separate port from the BGP peer — the "rogue" port.

Topology:
  IXIA (downlink, traffic src) -- BAG001:Ethernet5/9/1 -- [BAG001] -- [EDSW003.N001]
  IXIA (uplink, BGP + AddPath) -- eth1/23/1 -- [EDSW003.N001]
  IXIA (rogue, NDP + traffic sink) -- eth1/17/1 -- [EDSW003.N001]

Traffic flow:
  IXIA -> BAG001:Eth5/9/1 -> BAG001 -> EDSW003 -> ECMP(2048) -> eth1/17/1 -> IXIA

ECMP Scale:
  512 ECMP groups (prefixes), each with 2048 nexthops (sliding window)
  Total unique nexthops: 2560 (m1 through m2560)
  Adjacent groups overlap by 2047 members (99.95%)

IXIA Port Mapping:
  bag001.snc1:Ethernet5/9/1 -> chassis TBD port TBD (downlink / traffic source)
  edsw003.n001.l201.snc1:eth1/23/1 -> chassis 2401:db00:116:3167:... port 1/6 (uplink)
  edsw003.n001.l201.snc1:eth1/17/1 -> chassis 2401:db00:116:3167:... port 1/5 (rogue)

Reference:
  Design doc: https://docs.google.com/document/d/101KOJvWA4C7CrkqHsqHYw2NtQHEJBG-Vwyj1manxc4o
  DSF hardening (RDSW): fbcode/neteng/test_infra/dne/taac/ai_bb/dsf/dsf_hardening_test_config.py

Usage:
  buck2 run neteng/netcastle:netcastle_taac -- --team taac \\
    --test-config EDSW003_N001_ECMP_SCALE_3PORT \\
    --dev --debug \\
    --skip-basset-reservation --skip-testbed-isolation \\
    --skip-failed-setup-cleanup --skip-ixia-cleanup \\
    --regex 'longevity' \\
    --ixia-api-server 2401:db00:116:3167:21a:c5ff:fe01:7173
"""

import json

from ixia.ixia import types as ixia_types
from taac.health_checks.healthcheck_definitions import (
    create_bgp_convergence_check,
    create_core_dumps_snapshot_check,
    create_cpu_utilization_check,
    create_ecmp_group_and_member_count_check,
    create_ixia_packet_loss_check,
    create_memory_utilization_check,
    create_prefix_limit_check,
    create_service_restart_check,
    create_systemctl_active_state_check,
    create_unclean_exit_check,
)
from taac.packet_headers import DSF_RDMA_PACKET_HEADERS
from taac.playbooks.playbook_definitions import (
    create_edsw_agent_warmboot_with_ndp_playbook,
    create_ndp_device_group_churn_playbook,
)
from taac.task_definitions import (
    create_coop_apply_patchers_task,
    create_coop_register_patcher_task,
    create_coop_unregister_patchers_task,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import TestConfig


# =============================================================================
# Constants
# =============================================================================

PEERGROUP_EDSW_IXIA_ECMP_SCALE_V6 = "PEERGROUP_EDSW_IXIA_ECMP_SCALE_V6"

TRAFFIC_ITEM_GOLDEN = "golden"

# FBOSS RIF type for SYSTEM_PORT interfaces
SYSTEM_PORT_RIF_TYPE = 2

# DSF L1 config with PFC queue mapping (required for RDMA)
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

# DSF IMIX frame sizes
DSF_FRAME_SIZES = ixia_types.FrameSize(
    type=ixia_types.FrameSizeType.CUSTOM_IMIX,
    imix_weight={94: 1, 96: 18, 192: 3, 512: 1, 1200: 1, 4600: 76},
)

# EDSW BGP communities for route injection
EDSW_BGP_COMMUNITIES = ["65446:30", "65441:1028", "65529:52780", "65529:52779"]


# =============================================================================
# IXIA Health Check
# =============================================================================


def _create_ixia_healthcheck():
    return create_ixia_packet_loss_check(
        thresholds=[
            hc_types.PacketLossThreshold(
                names=[TRAFFIC_ITEM_GOLDEN],
                expect_packet_loss=True,
            ),
        ],
    )


# =============================================================================
# COOP Patcher Tasks
# =============================================================================


def _get_ecmp_scale_peer_group_tasks(device_name: str) -> list:
    """Create PEERGROUP_EDSW_IXIA_ECMP_SCALE_V6 with policies that accept routes."""
    return [
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name="add_peer_group_patcher_PEERGROUP_EDSW_IXIA_ECMP_SCALE_V6",
            task_name="add_peer_group_patcher",
            patcher_args={
                "name": PEERGROUP_EDSW_IXIA_ECMP_SCALE_V6,
                "description": "BGP peering EDSW to IXIA, IPv6, ECMP scale test",
                "disable_ipv4_afi": "True",
                "disable_ipv6_afi": "False",
                "ingress_policy_name": "PROPAGATE_EDSW_IXIA_ECMP_SCALE_IN",
                "egress_policy_name": "PROPAGATE_EDSW_IXIA_ECMP_SCALE_OUT",
                "bgp_peer_timers_hold_time_seconds": "30",
                "bgp_peer_timers_keep_alive_seconds": "10",
                "bgp_peer_timers_out_delay_seconds": "0",
                "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                "peer_tag": "IXIA",
                "max_routes": "900000",
                "warning_only": "True",
                "warning_limit": "0",
                "next_hop_self": "True",
                "is_confed_peer": "False",
                "is_passive": "False",
                "add_path": "BOTH",
                "v4_over_v6_nexthop": "False",
                "link_bandwidth_bps": "auto",
            },
            py_func_name="add_peer_group_patcher",
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_EDSW_IXIA_ECMP_SCALE_IN",
            task_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_EDSW_IXIA_ECMP_SCALE_IN",
                "description": "Accept routes from IXIA for ECMP scale test",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_EDSW_IXIA_ECMP_SCALE_OUT",
            task_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_EDSW_IXIA_ECMP_SCALE_OUT",
                "description": "Egress policy for IXIA ECMP scale test",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_ecmp_scale_in_v6",
            task_name="add_bgp_policy_match_prefix_to_propagate_routes",
            patcher_args={
                "matching_prefix": "5000::/16",
                "in_stmt_name": "PROPAGATE_EDSW_IXIA_ECMP_SCALE_IN",
                "out_stmt_name": "RANDOM",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
    ]


# =============================================================================
# 3-Port ECMP Scale Test Config Factory
# =============================================================================


def test_config_for_edsw_ecmp_scale_3port(
    test_config_name,
    device_name,
    local_mac_address,
    ixia_uplink_interface,
    ixia_rogue_interface,
    ixia_uplink_ic_parent_network_v6,
    ixia_rogue_ic_parent_network_v6,
    uplink_peer_count,
    remote_as_4byte,
    ecmp_width,
    prefix_count,
    prefix_limit,
    uplink_intf_id,
    uplink_port_id,
    rogue_intf_id,
    rogue_port_id,
    # Remote (downlink) device
    remote_device_name,
    remote_device_mac_address,
    ixia_remote_interface,
    ixia_remote_ic_parent_network_v6,
    # IXIA connections
    direct_ixia_connections=None,
    remote_direct_ixia_connections=None,
    basset_pool=None,
):
    """
    3-port ECMP scale test for EDSW using the DSF hardening topology.

    Topology:
      Remote device (downlink)  -> traffic source
      DUT uplink               -> BGP_ROUTE_INJECTOR with CustomNetworkGroupConfig
      DUT rogue                -> MIMIC_BGP_PEER + NDP_SUPPORTING_NEXTHOP

    The uplink port advertises prefixes with ecmp_width nexthops each via
    AddPath. Nexthops point to the rogue port's subnet. The rogue port has
    NDP responders for those nexthops and a mirror BGP stack (never UP) for
    IXIA merge_destinations support.

    Traffic flows: remote -> DUT -> ECMP(2048) -> rogue -> IXIA.
    """

    # Single BGP peer on uplink for CustomNetworkGroupConfig route injection.
    # local_addr uses ::a (the /64 secondary address on EDSW SYSTEM_PORT RIFs),
    # matching the EDSW path scale config pattern.
    peer_configs = [
        {
            "local_addr": f"{ixia_uplink_ic_parent_network_v6}::a",
            "peer_addr": f"{ixia_uplink_ic_parent_network_v6}::100",
            "peer_group_name": PEERGROUP_EDSW_IXIA_ECMP_SCALE_V6,
            "remote_as_4_byte": str(remote_as_4byte),
            "description": f"ixia_ecmp_scale_{ixia_uplink_interface}",
        }
    ]

    return TestConfig(
        name=test_config_name,
        ixia_protocol_verification_timeout=10,
        skip_ixia_protocol_verification=True,
        basset_pool=basset_pool,
        endpoints=[
            # DUT: EDSW003 with uplink + rogue
            taac_types.Endpoint(
                name=device_name,
                ixia_ports=[
                    ixia_uplink_interface,
                    ixia_rogue_interface,
                ],
                dut=True,
                mac_address=local_mac_address,
                direct_ixia_connections=direct_ixia_connections or [],
            ),
            # Remote: BAG001 with downlink (traffic source)
            taac_types.Endpoint(
                name=remote_device_name,
                ixia_ports=[ixia_remote_interface],
                dut=False,
                mac_address=remote_device_mac_address,
                direct_ixia_connections=remote_direct_ixia_connections or [],
            ),
        ],
        setup_tasks=[
            create_coop_unregister_patchers_task(device_name),
        ]
        + _get_ecmp_scale_peer_group_tasks(device_name)
        + [
            # Add /64 secondary addresses on uplink and rogue RIFs.
            # EDSW interfaces are SYSTEM_PORT type with /127 subnets.
            # Uplink: BGP peer at ::100 needs /64 for NDP.
            # Rogue: NDP_SUPPORTING_NEXTHOP at ::a000+ needs /64.
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="agent",
                patcher_name="configure_ixia_ips_for_ecmp_scale_3port",
                task_name="coop_register_patcher",
                patcher_args={
                    "uplink": json.dumps(
                        {
                            "intfId": uplink_intf_id,
                            "portID": uplink_port_id,
                            "vlanId": 0,
                            "mtu": 9000,
                            "ip_addresses": [
                                f"{ixia_uplink_ic_parent_network_v6}::/127",
                                f"{ixia_uplink_ic_parent_network_v6}::a/64",
                            ],
                            "rif_type": SYSTEM_PORT_RIF_TYPE,
                        }
                    ),
                    "rogue": json.dumps(
                        {
                            "intfId": rogue_intf_id,
                            "portID": rogue_port_id,
                            "vlanId": 0,
                            "mtu": 9000,
                            "ip_addresses": [
                                f"{ixia_rogue_ic_parent_network_v6}::/127",
                                f"{ixia_rogue_ic_parent_network_v6}::a/64",
                            ],
                            "rif_type": SYSTEM_PORT_RIF_TYPE,
                        }
                    ),
                },
                py_func_name="configure_interfaces_ip_addresses",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="add_bgp_peers_dut",
                task_name="add_bgp_peers",
                patcher_args={
                    "peer_configs": json.dumps(peer_configs),
                },
                py_func_name="add_bgp_peers",
            ),
            create_coop_apply_patchers_task(
                hostnames=[device_name],
                do_warmboot=True,
            ),
        ],
        teardown_tasks=[
            create_coop_unregister_patchers_task(device_name),
            create_coop_apply_patchers_task([device_name]),
        ],
        periodic_tasks=[],
        basic_port_configs=[
            # --- Remote device port: downlink traffic source ---
            taac_types.BasicPortConfig(
                l1_config=DSF_L1_CONFIG,
                endpoint=f"{remote_device_name}:{ixia_remote_interface}",
                device_group_configs=[
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        tag_name="DOWNLINK_L3_TRAFFIC",
                        multiplier=1,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_remote_ic_parent_network_v6}::a000",
                            increment_ip="::",
                            gateway_starting_ip=f"{ixia_remote_ic_parent_network_v6}::",
                            gateway_increment_ip="::",
                            mask=64,
                        ),
                    ),
                ],
            ),
            # --- Uplink port: BGP_ROUTE_INJECTOR with AddPath ---
            # Single BGP peer advertises prefixes with ecmp_width nexthops each.
            # Nexthops point to the rogue port's subnet.
            taac_types.BasicPortConfig(
                l1_config=DSF_L1_CONFIG,
                endpoint=f"{device_name}:{ixia_uplink_interface}",
                device_group_configs=[
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        tag_name="BGP_ROUTE_INJECTOR",
                        multiplier=uplink_peer_count,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_uplink_ic_parent_network_v6}::100",
                            increment_ip="::",
                            gateway_starting_ip=f"{ixia_uplink_ic_parent_network_v6}::a",
                            gateway_increment_ip="::",
                            mask=64,
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_as_4byte,
                            local_as_increment=0,
                            enable_4_byte_local_as=True,
                            bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                            is_confed=False,
                            bgp_capabilities=[
                                ixia_types.BgpCapability.IpV6Unicast,
                                ixia_types.BgpCapability.Ipv6UnicastAddPath,
                            ],
                            custom_network_group_configs=[
                                # Golden prefixes: ecmp_width nexthops per prefix
                                ixia_types.CustomNetworkGroupConfig(
                                    device_group_name="BGP_ROUTE_INJECTOR",
                                    network_group_name="uplink_golden_prefixes",
                                    network_group_multiplier=prefix_count,
                                    prefix_start_value="5000:dd::",
                                    prefix_length=64,
                                    nexthop_start_value=f"{ixia_rogue_ic_parent_network_v6}::a000",
                                    nexthop_increments="::1",
                                    ecmp_width=ecmp_width,
                                    community_list=EDSW_BGP_COMMUNITIES,
                                    network_group_index=0,
                                ),
                            ],
                        ),
                    ),
                ],
            ),
            # --- Rogue port: MIMIC_BGP_PEER + NDP_SUPPORTING_NEXTHOP ---
            # DG0: Mirror of uplink BGP stack (never expected UP, satisfies
            #      IXIA merge_destinations requirement).
            # DG1: NDP responders for all nexthop addresses. Disabled by default,
            #      enabled during test to allow controlled NDP churn.
            taac_types.BasicPortConfig(
                l1_config=DSF_L1_CONFIG,
                endpoint=f"{device_name}:{ixia_rogue_interface}",
                device_group_configs=[
                    # DG0: MIMIC_BGP_PEER — dummy BGP stack matching uplink
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        tag_name="MIMIC_BGP_PEER",
                        multiplier=uplink_peer_count,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_uplink_ic_parent_network_v6}::100",
                            increment_ip="::",
                            gateway_starting_ip=f"{ixia_uplink_ic_parent_network_v6}::a",
                            gateway_increment_ip="::",
                            mask=64,
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_as_4byte,
                            local_as_increment=0,
                            enable_4_byte_local_as=True,
                            bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                            is_confed=False,
                            bgp_capabilities=[
                                ixia_types.BgpCapability.IpV6Unicast,
                                ixia_types.BgpCapability.Ipv6UnicastAddPath,
                            ],
                            custom_network_group_configs=[
                                ixia_types.CustomNetworkGroupConfig(
                                    device_group_name="MIMIC_BGP_PEER",
                                    network_group_name="MIMIC_BGP_PREFIXES",
                                    network_group_multiplier=prefix_count,
                                    prefix_start_value="5000:dd::",
                                    prefix_length=64,
                                    nexthop_start_value=f"{ixia_rogue_ic_parent_network_v6}::a000",
                                    nexthop_increments="::1",
                                    ecmp_width=ecmp_width,
                                    community_list=EDSW_BGP_COMMUNITIES,
                                    network_group_index=0,
                                ),
                            ],
                        ),
                    ),
                    # DG1: NDP_SUPPORTING_NEXTHOP — provides NDP resolution
                    # for ecmp_width nexthop addresses. The sliding window
                    # model needs ecmp_width + (prefix_count - 1) unique
                    # members, but start with ecmp_width + 512 = 2560.
                    taac_types.DeviceGroupConfig(
                        device_group_index=1,
                        tag_name="NDP_SUPPORTING_NEXTHOP",
                        enable=False,
                        multiplier=ecmp_width + 512,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_rogue_ic_parent_network_v6}::a000",
                            increment_ip="::1",
                            gateway_starting_ip=f"{ixia_rogue_ic_parent_network_v6}::a",
                            mask=64,
                        ),
                    ),
                ],
            ),
        ],
        traffic_items_to_start=[TRAFFIC_ITEM_GOLDEN],
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
                        name=f"{remote_device_name}:{ixia_remote_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=0,
                        network_group_index=0,
                    ),
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_rogue_interface}",
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
        snapshot_checks=[
            create_core_dumps_snapshot_check(),
        ],
        postchecks=[
            create_systemctl_active_state_check(),
            _create_ixia_healthcheck(),
            create_ecmp_group_and_member_count_check(
                ecmp_member_count=16000,
                ecmp_group_count=1536,
            ),
            create_prefix_limit_check(prefix_limit=prefix_limit),
            create_unclean_exit_check(),
            create_memory_utilization_check(
                threshold=5 * (1024**3),
                threshold_by_service={
                    "bgpd": 4.5 * (1024**3),
                    "fsdb": 7 * (1024**3),
                    "qsfp_service": 2 * (1024**3),
                    "wedge_agent": 0.8 * 16 * (1024**3),
                },
                start_time_jq_var="test_case_start_time",
            ),
            create_cpu_utilization_check(
                threshold=100.0,
                start_time_jq_var="test_case_start_time",
            ),
            create_service_restart_check(
                services=[
                    "wedge_agent",
                    "bgpd",
                    "fsdb",
                    "qsfp_service",
                ],
            ),
        ],
        prechecks=[
            create_systemctl_active_state_check(),
        ],
        playbooks=[
            # --- Agent warmboot with NDP enable + traffic validation ---
            # Adapted from DSF hardening warmboot playbook
            create_edsw_agent_warmboot_with_ndp_playbook(
                ixia_healthcheck=_create_ixia_healthcheck(),
            ),
            # --- NDP device group churn (60 min, 30s interval) ---
            create_ndp_device_group_churn_playbook(
                duration_minutes=60,
                toggle_interval_seconds=30,
                name="test_ndp_device_group_churn",
                postchecks=[
                    create_bgp_convergence_check(
                        fail_on_eor_expired=False,
                        convergence_threshold=600,
                    ),
                    create_ecmp_group_and_member_count_check(
                        ecmp_member_count=16000,
                        ecmp_group_count=1536,
                    ),
                ],
            ),
        ],
    )


# =============================================================================
# Testbed: edsw003.n001.l201.snc1 (DUT) + bag001.snc1 (remote/downlink)
#
# DUT ports:
#   eth1/23/1 -> IXIA port 1/6 (uplink: BGP route injector)
#   eth1/17/1 -> IXIA port 1/5 (rogue: NDP + MIMIC_BGP)
# Remote port:
#   bag001.snc1:Ethernet5/9/1 -> IXIA TBD (downlink: traffic source)
#
# TODO: Fill in BAG001 IXIA chassis IP and port from `ixia_port_cli`
# =============================================================================

_EDSW003_DEVICE_NAME = "edsw003.n001.l201.snc1"
_EDSW003_MAC_ADDRESS = "02:00:00:00:0f:0b"
_EDSW003_UPLINK_REMOTE_AS = 65321

_BAG001_DEVICE_NAME = "bag001.snc1"
_BAG001_MAC_ADDRESS = "02:00:00:00:0f:0b"

_IXIA_CHASSIS_IP = "2401:db00:116:3167:21a:c5ff:fe01:7173"

# EDSW003 N001 network prefixes
_EDSW003_UPLINK_PREFIX = "2401:db00:11b:d8c1"  # eth1/23/1
_EDSW003_ROGUE_PREFIX = "2401:db00:11b:d8c0"  # eth1/17/1

# BAG001 downlink network prefix (from hyperport_snc_bag_test_configs.py)
_BAG001_DOWNLINK_PREFIX = "2401:db00:11b:d8a1"  # Ethernet5/9/1

# FBOSS RIF IDs (from: fboss2 -H edsw003.n001.l201.snc1 show config running agent)
_EDSW003_UPLINK_INTF_ID = 2391  # intfID for eth1/23/1 (SYSTEM_PORT type)
_EDSW003_UPLINK_PORT_ID = 25  # logicalID for eth1/23/1
_EDSW003_ROGUE_INTF_ID = 2378  # intfID for eth1/17/1 (SYSTEM_PORT type)
_EDSW003_ROGUE_PORT_ID = 12  # logicalID for eth1/17/1


EDSW003_N001_ECMP_SCALE_3PORT = test_config_for_edsw_ecmp_scale_3port(
    test_config_name="EDSW003_N001_ECMP_SCALE_3PORT",
    device_name=_EDSW003_DEVICE_NAME,
    local_mac_address=_EDSW003_MAC_ADDRESS,
    ixia_uplink_interface="eth1/23/1",
    ixia_rogue_interface="eth1/17/1",
    ixia_uplink_ic_parent_network_v6=_EDSW003_UPLINK_PREFIX,
    ixia_rogue_ic_parent_network_v6=_EDSW003_ROGUE_PREFIX,
    uplink_peer_count=1,
    remote_as_4byte=_EDSW003_UPLINK_REMOTE_AS,
    ecmp_width=2048,
    prefix_count=512,
    prefix_limit="75000",
    uplink_intf_id=_EDSW003_UPLINK_INTF_ID,
    uplink_port_id=_EDSW003_UPLINK_PORT_ID,
    rogue_intf_id=_EDSW003_ROGUE_INTF_ID,
    rogue_port_id=_EDSW003_ROGUE_PORT_ID,
    remote_device_name=_BAG001_DEVICE_NAME,
    remote_device_mac_address=_BAG001_MAC_ADDRESS,
    ixia_remote_interface="Ethernet5/9/1",
    ixia_remote_ic_parent_network_v6=_BAG001_DOWNLINK_PREFIX,
    direct_ixia_connections=[
        taac_types.DirectIxiaConnection(
            interface="eth1/23/1",  # Uplink
            ixia_chassis_ip=_IXIA_CHASSIS_IP,
            ixia_port="1/6",
        ),
        taac_types.DirectIxiaConnection(
            interface="eth1/17/1",  # Rogue
            ixia_chassis_ip=_IXIA_CHASSIS_IP,
            ixia_port="1/5",
        ),
    ],
    # TODO: Fill in BAG001 IXIA chassis IP and port.
    # Run: buck2 run fbcode//neteng/test_infra/dne/taac/utils:ixia_port_cli -- --device bag001.snc1
    remote_direct_ixia_connections=[
        # taac_types.DirectIxiaConnection(
        #     interface="Ethernet5/9/1",
        #     ixia_chassis_ip="TBD",
        #     ixia_port="TBD",
        # ),
    ],
    basset_pool="networkai.test.regression",
)

EDSW003_N001_ECMP_SCALE_3PORT_TEST_CONFIGS = [
    EDSW003_N001_ECMP_SCALE_3PORT,
]
