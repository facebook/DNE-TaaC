# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
DSF Hardening Test Configuration for EDSW003.N001.L201.SNC1 with BAG001.SNC1 source

3-port topology adapted from the RDSW pattern in dsf_hardening_test_config.py:
- DUT: edsw003.n001.l201.snc1 (FBOSS, ASN 65062) with two IXIA ports
  - eth1/17/1 (uplink): IXIA peers iBGP and injects 2048 routes at 5000:dd::/64
                        with nexthops on the mimic port
  - eth1/23/1 (mimic):  IXIA hosts MIMIC_BGP_PEER + a disabled
                        NDP_SUPPORTING_NEXTHOP device group (2000 NDP entries)
- Source: bag001.snc1 (Arista/EOS, ASN 65060) with one IXIA port
  - Ethernet5/18/1: IXIA peers eBGP (AS 65063) with bag, advertises 100 source
                    prefixes at 4000:3:2::/64. Traffic flows from this port toward
                    the BGP-injected destinations on edsw003.

Route flow:
  edsw003 receives 5000:dd::/64 from IXIA via uplink iBGP, propagates to bag001
  via the production fabric link. bag001 installs the routes and forwards
  IXIA-source traffic over the fabric to edsw003, which forwards to the
  mimic-port nexthops.

Bag-side BGP setup (no setup_tasks emitted): the IPv6 link addressing
(2401:db00:11b:d8a1::b2/127 on bag, ::b3 on IXIA) and the bag BGP peer-group
that accepts an eBGP session from the IXIA peer are assumed pre-configured in
production on bag001.

Usage:
  buck2 run neteng/netcastle:netcastle_taac -- --team taac \\
    --test-config EDSW003_N001_L201_SNC1_HARDENING_NODE
"""

import json

from ixia.ixia import types as ixia_types
from taac.health_checks.healthcheck_definitions import (
    create_ixia_packet_loss_check,
    create_systemctl_active_state_check,
)
from taac.packet_headers import DSF_RDMA_IB_PACKET_HEADERS
from taac.playbooks.playbook_definitions import (
    create_edsw003_n001_l201_snc1_longevity_playbook,
    create_edsw003_n001_l201_snc1_warmboot_playbook,
    create_edsw_fboss_critical_service_playbook,
    create_ndp_device_group_churn_playbook,
)
from taac.task_definitions import (
    create_coop_apply_patchers_task,
    create_coop_register_patcher_task,
    create_coop_unregister_patchers_task,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import Service, ServiceInterruptionTrigger, TestConfig

# =============================================================================
# Constants
# =============================================================================

DSF_FRAME_SIZES = ixia_types.FrameSize(
    type=ixia_types.FrameSizeType.CUSTOM_IMIX,
    imix_weight={94: 1, 96: 18, 192: 3, 512: 1, 1200: 1, 4600: 76},
)

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

EDSW_BGP_COMMUNITIES = ["65446:30", "65441:1028", "65529:52780", "65529:52779"]
BAG_BGP_COMMUNITIES = ["65529:52780", "65529:52779"]

# Test-created peer group for the IXIA peers. Created fresh via
# add_peer_group_patcher so that add_path=BOTH is set at creation time
# (the deployed COOP can't write add_path onto an existing peer group whose
# field is None — see configure_bgp_peer_group's _patch_object_attribute
# limitation on Optional Thrift enums with no zero value).
PEERGROUP_EDSW_IXIA_HARDENING_V6 = "PEERGROUP_EDSW_IXIA_HARDENING_V6"

TRAFFIC_ITEM_GOLDEN = "golden"
NO_LOSS_TRAFFIC_ITEMS = [TRAFFIC_ITEM_GOLDEN]

# FBOSS RIF type for SYSTEM_PORT interfaces.
SYSTEM_PORT_RIF_TYPE = 2

# FBOSS RIF IDs for edsw003.n001.l201.snc1 IXIA-connected interfaces.
# Confirmed via `fboss2 -H edsw003.n001.l201.snc1 show interface eth1/17/1`
# (RIF fboss2378, VLAN 12) and `... show interface eth1/23/1`
# (RIF fboss2391, VLAN 25).
_EDSW003_UPLINK_INTF_ID = 2378
_EDSW003_UPLINK_PORT_ID = 12
_EDSW003_MIMIC_INTF_ID = 2391
_EDSW003_MIMIC_PORT_ID = 25


# =============================================================================
# Health check helpers
# =============================================================================
def create_ixia_healthcheck(
    no_loss_traffic: list = NO_LOSS_TRAFFIC_ITEMS,
):
    return create_ixia_packet_loss_check(
        thresholds=[
            hc_types.PacketLossThreshold(
                names=list(no_loss_traffic),
                str_value="0.1",
                expect_packet_loss=False,
            )
        ]
    )


# =============================================================================
# Test Config Factory
# =============================================================================
def test_config_for_edsw003_dsf_hardening_with_bag_source(
    test_config_name,
    device_name,
    local_mac_address,
    ixia_uplink_interface,
    ixia_mimic_interface,
    ixia_uplink_ic_parent_network_v6,
    ixia_mimic_ic_parent_network_v6,
    uplink_peer_count,
    remote_uplink_as_4byte,
    is_uplink_peer_confed,
    remote_device_name,
    remote_device_mac_address,
    ixia_remote_interface,
    bag_ixia_starting_ip,
    bag_ixia_gateway_ip,
    bag_ixia_local_as,
    bag_source_starting_prefix,
    direct_ixia_connections=None,
    remote_direct_ixia_connections=None,
    basset_pool=None,
    longevity_duration=240,
):
    """
    DSF hardening test config with BAG001 as the IXIA traffic source.

    See module docstring for topology and route flow details.
    """
    _systemctl_check = create_systemctl_active_state_check()

    _ndp_churn_playbook = create_ndp_device_group_churn_playbook(
        duration_minutes=60,
        toggle_interval_seconds=30,
    )
    _ndp_churn_zero_loss_thresholds = [
        hc_types.PacketLossThreshold(
            str_value="0",
            metric=hc_types.PacketLossMetric.PERCENTAGE,
        ),
    ]
    _ndp_churn_playbook = _ndp_churn_playbook(
        prechecks=[
            create_ixia_packet_loss_check(
                thresholds=_ndp_churn_zero_loss_thresholds,
                clear_traffic_stats=True,
            ),
            _systemctl_check,
        ],
        postchecks=[
            create_ixia_packet_loss_check(
                thresholds=_ndp_churn_zero_loss_thresholds,
                clear_traffic_stats=False,
            ),
            _systemctl_check,
        ],
        snapshot_checks=[],
    )

    _warmboot_playbook = create_edsw003_n001_l201_snc1_warmboot_playbook(
        ixia_healthcheck=create_ixia_healthcheck(),
    )
    _longevity_playbook = create_edsw003_n001_l201_snc1_longevity_playbook(
        ixia_healthcheck=create_ixia_healthcheck(),
        longevity_duration=longevity_duration,
    )

    return TestConfig(
        name=test_config_name,
        # ixia_protocol_verification_timeout=900,
        skip_ixia_protocol_verification=True,
        basset_pool=basset_pool,
        endpoints=[
            taac_types.Endpoint(
                name=device_name,
                ixia_ports=[
                    ixia_uplink_interface,
                    ixia_mimic_interface,
                ],
                dut=True,
                mac_address=local_mac_address,
                direct_ixia_connections=direct_ixia_connections
                if direct_ixia_connections
                else [],
            ),
            taac_types.Endpoint(
                name=remote_device_name,
                ixia_ports=[ixia_remote_interface],
                dut=False,
                mac_address=remote_device_mac_address,
                direct_ixia_connections=remote_direct_ixia_connections
                if remote_direct_ixia_connections
                else [],
            ),
        ],
        setup_tasks=[
            create_coop_unregister_patchers_task(device_name),
            # Create a fresh PEERGROUP_EDSW_IXIA_HARDENING_V6 with add_path=BOTH
            # baked in at creation time. add_peer_group_patcher assigns add_path
            # directly on a new PeerGroup object, sidestepping the
            # _patch_object_attribute limitation that blocks updates to
            # already-existing Optional Thrift enum fields (no zero value).
            # Uses dedicated PROPAGATE_EDSW_IXIA_HARDENING_IN/OUT policies
            # created below, with a 5000::/16 match-prefix on the IN policy
            # (covers the IXIA-injected golden 5000:dd:: and rogue 5000:ee::
            # prefixes).
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"add_peer_group_patcher_{PEERGROUP_EDSW_IXIA_HARDENING_V6}",
                task_name="add_peer_group_patcher",
                py_func_name="add_peer_group_patcher",
                patcher_args={
                    "name": PEERGROUP_EDSW_IXIA_HARDENING_V6,
                    "description": "BGP peering EDSW to IXIA, IPv6, hardening test",
                    "disable_ipv4_afi": "True",
                    "disable_ipv6_afi": "False",
                    "ingress_policy_name": "PROPAGATE_EDSW_IXIA_HARDENING_IN",
                    "egress_policy_name": "PROPAGATE_EDSW_IXIA_HARDENING_OUT",
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
                    "v4_over_v6_nexthop": "False",
                    "link_bandwidth_bps": "auto",
                    "add_path": "BOTH",
                },
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="a_add_bgp_policy_statement_PROPAGATE_EDSW_IXIA_HARDENING_IN",
                task_name="add_bgp_policy_statement",
                py_func_name="add_bgp_policy_statement",
                patcher_args={
                    "name": "PROPAGATE_EDSW_IXIA_HARDENING_IN",
                    "description": "Accept routes from IXIA for hardening test",
                },
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="a_add_bgp_policy_statement_PROPAGATE_EDSW_IXIA_HARDENING_OUT",
                task_name="add_bgp_policy_statement",
                py_func_name="add_bgp_policy_statement",
                patcher_args={
                    "name": "PROPAGATE_EDSW_IXIA_HARDENING_OUT",
                    "description": "Egress policy for IXIA hardening test",
                },
            ),
            # Add 5000::/16 match-prefix term to the IN statement only. The
            # OUT statement is named "RANDOM" so the patcher's OUT branch
            # silently no-ops (IXIA peer doesn't need to receive routes from
            # the DUT for this test).
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_EDSW_IXIA_HARDENING_IN_v6",
                task_name="add_bgp_policy_match_prefix_to_propagate_routes",
                py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
                patcher_args={
                    "matching_prefix": "5000::/16",
                    "in_stmt_name": "PROPAGATE_EDSW_IXIA_HARDENING_IN",
                    "out_stmt_name": "RANDOM",
                },
            ),
            # Add ::a/64 secondary on both eth1/17/1 and eth1/23/1 so IXIA peers
            # at ::100 (in the /64 outside the /127) and route nexthops at
            # ::a000 are on-link from the DUT. Keep BOTH /127 (production link
            # addressing for mock bag040 peer) and /64 (test secondary).
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="agent",
                patcher_name="configure_ixia_ips_with_64_secondary",
                task_name="coop_register_patcher",
                patcher_args={
                    "uplink": json.dumps(
                        {
                            "intfId": _EDSW003_UPLINK_INTF_ID,
                            "portID": _EDSW003_UPLINK_PORT_ID,
                            "vlanId": 0,
                            "mtu": 9000,
                            "ip_addresses": [
                                f"{ixia_uplink_ic_parent_network_v6}::a/64",
                            ],
                            "rif_type": SYSTEM_PORT_RIF_TYPE,
                        }
                    ),
                    "downlink": json.dumps(
                        {
                            "intfId": _EDSW003_MIMIC_INTF_ID,
                            "portID": _EDSW003_MIMIC_PORT_ID,
                            "vlanId": 0,
                            "mtu": 9000,
                            "ip_addresses": [
                                f"{ixia_mimic_ic_parent_network_v6}::a/64",
                            ],
                            "rif_type": SYSTEM_PORT_RIF_TYPE,
                        }
                    ),
                },
                py_func_name="configure_interfaces_ip_addresses",
            ),
            # Add 2 new IXIA BGP peers (one per interface) into
            # PEERGROUP_EDSW_IXIA_HARDENING_V6 using ::a (DUT /64 secondary
            # host) and ::100 (IXIA side, in /64 but outside /127) to avoid
            # colliding
            # with the mock bag040 peer at ::1.
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
                                "local_addr": f"{ixia_uplink_ic_parent_network_v6}::a",
                                "peer_addr": f"{ixia_uplink_ic_parent_network_v6}::100",
                                "peer_group_name": PEERGROUP_EDSW_IXIA_HARDENING_V6,
                                "remote_as_4_byte": str(remote_uplink_as_4byte),
                                "description": "ixia_uplink_eth1_17_1",
                            },
                            {
                                "local_addr": f"{ixia_mimic_ic_parent_network_v6}::a",
                                "peer_addr": f"{ixia_mimic_ic_parent_network_v6}::100",
                                "peer_group_name": PEERGROUP_EDSW_IXIA_HARDENING_V6,
                                "remote_as_4_byte": str(remote_uplink_as_4byte),
                                "description": "ixia_mimic_eth1_23_1",
                            },
                        ]
                    ),
                },
            ),
            create_coop_apply_patchers_task(
                hostnames=[device_name],
                do_warmboot=True,
            ),
        ],
        # teardown_tasks=[
        #     create_coop_unregister_patchers_task(device_name),
        # ],
        basic_port_configs=[
            # 1. Uplink port (eth1/17/1) - iBGP peer + 2048 golden prefixes
            #    Nexthops point to the mimic port /64 so the DUT must forward
            #    via the mimic port to reach the advertised destinations.
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
                                    nexthop_start_value=f"{ixia_mimic_ic_parent_network_v6}::a000",
                                    nexthop_increments="::1",
                                    ecmp_width=2048,
                                    community_list=EDSW_BGP_COMMUNITIES,
                                    network_group_index=0,
                                ),
                                ixia_types.CustomNetworkGroupConfig(
                                    device_group_name="BGP_ROUTE_INJECTOR",
                                    network_group_name="uplink_rogue_prefixes",
                                    network_group_multiplier=32768,
                                    prefix_start_value="5000:ee::",
                                    prefix_length=64,
                                    nexthop_start_value=f"{ixia_mimic_ic_parent_network_v6}::a000",
                                    nexthop_increments="::1",
                                    ecmp_width=2048,
                                    community_list=EDSW_BGP_COMMUNITIES,
                                    network_group_index=1,
                                ),
                            ],
                        ),
                    ),
                ],
            ),
            # 2. Mimic port (eth1/23/1) - paired iBGP peer + NDP nexthop pool
            #    Mirrors the RDSW reference rogue port: the mimic port acts as a
            #    second iBGP peer that advertises the SAME prefix sets as the
            #    uplink port (golden 5000:dd::/64 + rogue 5000:ee::/64) for
            #    ECMP redundancy at the DUT.
            taac_types.BasicPortConfig(
                l1_config=DSF_L1_CONFIG,
                endpoint=f"{device_name}:{ixia_mimic_interface}",
                device_group_configs=[
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        tag_name="MIMIC_BGP_PEER",
                        multiplier=uplink_peer_count,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_mimic_ic_parent_network_v6}::100",
                            increment_ip="::",
                            gateway_starting_ip=f"{ixia_mimic_ic_parent_network_v6}::a",
                            gateway_increment_ip="::",
                            mask=64,
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
                                    device_group_name="MIMIC_BGP_PEER",
                                    network_group_name="MIMIC_BGP_PREFIXES",
                                    network_group_multiplier=2048,
                                    prefix_start_value="5000:dd::",
                                    prefix_length=64,
                                    nexthop_start_value=f"{ixia_mimic_ic_parent_network_v6}::a000",
                                    nexthop_increments="::1",
                                    ecmp_width=2048,
                                    community_list=EDSW_BGP_COMMUNITIES,
                                    network_group_index=0,
                                ),
                                ixia_types.CustomNetworkGroupConfig(
                                    device_group_name="MIMIC_BGP_PEER",
                                    network_group_name="uplink_rogue_prefixes",
                                    network_group_multiplier=32768,
                                    prefix_start_value="5000:ee::",
                                    prefix_length=64,
                                    nexthop_start_value=f"{ixia_mimic_ic_parent_network_v6}::a000",
                                    nexthop_increments="::1",
                                    ecmp_width=2048,
                                    community_list=EDSW_BGP_COMMUNITIES,
                                    network_group_index=1,
                                ),
                            ],
                        ),
                    ),
                    # NDP_SUPPORTING_NEXTHOP device group emulates the ::a000+
                    # nexthop pool that the IXIA-injected 5000:dd::/64 routes
                    # point to. Must be enabled at test start so edsw003 can
                    # resolve NDP and install FIB entries — otherwise the
                    # per-playbook IXIA_PACKET_LOSS_CHECK precheck sees 100%
                    # loss before any disruption runs.
                    taac_types.DeviceGroupConfig(
                        device_group_index=1,
                        tag_name="NDP_SUPPORTING_NEXTHOP",
                        enable=True,
                        multiplier=2000,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_mimic_ic_parent_network_v6}::a000",
                            increment_ip="::1",
                            gateway_starting_ip=f"{ixia_mimic_ic_parent_network_v6}::a",
                            mask=64,
                        ),
                    ),
                ],
            ),
            # 3. BAG source port (bag001:Ethernet5/18/1) - eBGP + source prefixes
            #    Mirrors the hyperport_vrf_bag_n000 pattern: IXIA peers eBGP
            #    with bag (IXIA AS 65063 vs bag's production AS) and advertises
            #    100 source prefixes at 4000:3:2::/64.
            taac_types.BasicPortConfig(
                l1_config=DSF_L1_CONFIG,
                endpoint=f"{remote_device_name}:{ixia_remote_interface}",
                device_group_configs=[
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        multiplier=1,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=bag_ixia_starting_ip,
                            increment_ip="::2",
                            gateway_starting_ip=bag_ixia_gateway_ip,
                            gateway_increment_ip="::2",
                            mask=127,
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=bag_ixia_local_as,
                            enable_4_byte_local_as=True,
                            is_confed=False,
                            bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                            bgp_capabilities=[
                                ixia_types.BgpCapability.IpV6Unicast,
                                ixia_types.BgpCapability.Ipv6UnicastAddPath,
                            ],
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=100,
                                        prefix_length=64,
                                        starting_prefixes=bag_source_starting_prefix,
                                        prefix_step="0:0:0:1:0:0:0:0",
                                        bgp_communities=BAG_BGP_COMMUNITIES,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    ),
                                ),
                            ],
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
                        network_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=0,
                        network_group_index=0,
                    ),
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_mimic_interface}",
                        device_group_index=0,
                        network_group_index=0,
                    ),
                ],
                traffic_type=ixia_types.TrafficType.IPV6,
                tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
                frame_size_settings=DSF_FRAME_SIZES,
                packet_headers=DSF_RDMA_IB_PACKET_HEADERS,
            ),
        ],
        playbooks=[
            _warmboot_playbook,
            _longevity_playbook,
            _ndp_churn_playbook,
            # FBOSS critical-service playbooks (mono-NPU DSF EDSW). Each one
            # interrupts a service on the DUT and verifies IXIA loss + systemctl
            # state pre/post. agent coldboot/crash add a SERVICE_CONVERGENCE_STEP
            # so wedge_agent is back online before checks fire; crash variants
            # also exclude the SIGKILL'd service from UNCLEAN_EXIT_CHECK.
            create_edsw_fboss_critical_service_playbook(
                name="test_agent_warmboot",
                services=[Service.AGENT],
                trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                device_regexes=[device_name],
                traffic_item_to_start=TRAFFIC_ITEM_GOLDEN,
            ),
            create_edsw_fboss_critical_service_playbook(
                name="test_agent_coldboot",
                services=[Service.AGENT],
                trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                device_regexes=[device_name],
                traffic_item_to_start=TRAFFIC_ITEM_GOLDEN,
                create_cold_boot_file=True,
                add_service_convergence=True,
                longevity_duration=180,
                clear_traffic_stats=True,
            ),
            create_edsw_fboss_critical_service_playbook(
                name="test_agent_crash",
                services=[Service.AGENT],
                trigger=ServiceInterruptionTrigger.CRASH,
                device_regexes=[device_name],
                traffic_item_to_start=TRAFFIC_ITEM_GOLDEN,
                clear_traffic_stats=True,
                add_service_convergence=True,
                longevity_duration=180,
                unclean_exit_exclude_services=["wedge_agent"],
            ),
            create_edsw_fboss_critical_service_playbook(
                name="test_bgpd_restart",
                services=[Service.BGP],
                trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                device_regexes=[device_name],
                traffic_item_to_start=TRAFFIC_ITEM_GOLDEN,
            ),
            create_edsw_fboss_critical_service_playbook(
                name="test_bgpd_crash",
                services=[Service.BGP],
                trigger=ServiceInterruptionTrigger.CRASH,
                device_regexes=[device_name],
                traffic_item_to_start=TRAFFIC_ITEM_GOLDEN,
                clear_traffic_stats=True,
                unclean_exit_exclude_services=["bgpd"],
            ),
            create_edsw_fboss_critical_service_playbook(
                name="test_fsdb_restart",
                services=[Service.FSDB],
                trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                device_regexes=[device_name],
                traffic_item_to_start=TRAFFIC_ITEM_GOLDEN,
            ),
            create_edsw_fboss_critical_service_playbook(
                name="test_fsdb_crash",
                services=[Service.FSDB],
                trigger=ServiceInterruptionTrigger.CRASH,
                device_regexes=[device_name],
                traffic_item_to_start=TRAFFIC_ITEM_GOLDEN,
                clear_traffic_stats=True,
                unclean_exit_exclude_services=["fsdb"],
            ),
            create_edsw_fboss_critical_service_playbook(
                name="test_qsfp_restart",
                services=[Service.QSFP_SERVICE],
                trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                device_regexes=[device_name],
                traffic_item_to_start=TRAFFIC_ITEM_GOLDEN,
            ),
            create_edsw_fboss_critical_service_playbook(
                name="test_qsfp_service_crash",
                services=[Service.QSFP_SERVICE],
                trigger=ServiceInterruptionTrigger.CRASH,
                device_regexes=[device_name],
                traffic_item_to_start=TRAFFIC_ITEM_GOLDEN,
                clear_traffic_stats=True,
                unclean_exit_exclude_services=["qsfp_service"],
            ),
            create_edsw_fboss_critical_service_playbook(
                name="test_agent_and_bgpd_restart",
                services=[Service.AGENT, Service.BGP],
                trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                device_regexes=[device_name],
                traffic_item_to_start=TRAFFIC_ITEM_GOLDEN,
                concurrent=True,
            ),
            create_edsw_fboss_critical_service_playbook(
                name="test_agent_and_fsdb_restart",
                services=[Service.AGENT, Service.FSDB],
                trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                device_regexes=[device_name],
                traffic_item_to_start=TRAFFIC_ITEM_GOLDEN,
                concurrent=True,
            ),
            create_edsw_fboss_critical_service_playbook(
                name="test_agent_and_qsfp_service_restart",
                services=[Service.AGENT, Service.QSFP_SERVICE],
                trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                device_regexes=[device_name],
                traffic_item_to_start=TRAFFIC_ITEM_GOLDEN,
                concurrent=True,
            ),
            create_edsw_fboss_critical_service_playbook(
                name="test_bgpd_and_fsdb_restart",
                services=[Service.BGP, Service.FSDB],
                trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                device_regexes=[device_name],
                traffic_item_to_start=TRAFFIC_ITEM_GOLDEN,
                concurrent=True,
            ),
            create_edsw_fboss_critical_service_playbook(
                name="test_fsdb_and_qsfp_service_restart",
                services=[Service.FSDB, Service.QSFP_SERVICE],
                trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                device_regexes=[device_name],
                traffic_item_to_start=TRAFFIC_ITEM_GOLDEN,
                concurrent=True,
            ),
        ],
    )


# =============================================================================
# Config Instance: edsw003.n001.l201.snc1 + bag001.snc1
# =============================================================================
EDSW003_N001_L201_SNC1_HARDENING_NODE = (
    test_config_for_edsw003_dsf_hardening_with_bag_source(
        test_config_name="EDSW003_N001_L201_SNC1_HARDENING_NODE",
        device_name="edsw003.n001.l201.snc1",
        local_mac_address="02:00:00:00:0f:0b",
        ixia_uplink_interface="eth1/17/1",
        ixia_mimic_interface="eth1/23/1",
        ixia_uplink_ic_parent_network_v6="2401:db00:11b:d8c0",
        ixia_mimic_ic_parent_network_v6="2401:db00:11b:d8c1",
        uplink_peer_count=1,
        remote_uplink_as_4byte=65062,
        is_uplink_peer_confed="False",
        remote_device_name="bag001.snc1",
        remote_device_mac_address="02:00:00:00:0f:0b",
        ixia_remote_interface="Ethernet5/18/1",
        bag_ixia_starting_ip="2401:db00:11b:d8a1::b3",
        bag_ixia_gateway_ip="2401:db00:11b:d8a1::b2",
        bag_ixia_local_as=65063,
        bag_source_starting_prefix="5000:3:2::",
        basset_pool="networkai.test.regression",
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
        remote_direct_ixia_connections=[
            taac_types.DirectIxiaConnection(
                interface="Ethernet5/18/1",
                ixia_chassis_ip="2401:db00:116:3167:21a:c5ff:fe01:7173",
                ixia_port="1/2",
            ),
        ],
    )
)
