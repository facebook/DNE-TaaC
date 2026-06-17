# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""RDSW004 C085 N001 SNC1 DSF hardening TestConfig.

Builds a Conveyor-eligible DSF (Distributed Scheduled Fabric) hardening
TestConfig for the AI BB RDSW004 testbed in C085/N001/SNC1. Exercises a
broad set of disruptive playbooks (warmboot, COOP patcher churn, NDP
device-group churn, FSDB subscriber stress under packet drop) while a
golden RDMA traffic item and an RDSW-to-RDSW same-cluster traffic item
run continuously. Validates that DSF stays consistent across stresses.
"""

import json

from ixia.ixia import types as ixia_types
from taac.health_checks.healthcheck_definitions import (
    create_core_dumps_snapshot_check,
    create_prefix_limit_check,
    create_systemctl_active_state_check,
)
from taac.packet_headers import DSF_RDMA_PACKET_HEADERS
from taac.playbooks.playbook_definitions import (
    create_dsf_hardening_ixia_healthcheck,
    create_dsf_test_agent_warmboot_playbook,
    create_ndp_device_group_churn_playbook,
    DSF_HARDENING_TRAFFIC_ITEM_GOLDEN,
    DSF_HARDENING_TRAFFIC_ITEM_RDSW_RDSW_SAME_CLUSTER,
)
from taac.task_definitions import (
    create_coop_register_patcher_task,
    create_coop_unregister_patchers_task,
    create_run_commands_on_shell_task,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import Params, TestConfig

# Constants for DSF hardening test
PEERGROUP_RDSW_EDSW_V6 = "PEERGROUP_RDSW_EDSW_V6"

# FSDB subscriber clients: maps subscriber ID -> shell command to activate it on the remote device.
# The {dut_mgmt_ip} placeholder is resolved at config generation time.
FSDB_SUBSCRIBER_CLIENTS = {
    "stress_test_client_path": (
        "nohup /tmp/stress_test_client subscribePath agent "
        "--host {dut_mgmt_ip} --consumeDelayMs=300000 --count "
        "> /tmp/stress_test_client.log 2>&1 &"
    ),
    "patch_subscriber": (
        "nohup /tmp/stress_test_client subscribePatch agent "
        "--host {dut_mgmt_ip} --consumeDelayMs=300000 --count "
        "--client_id=patch_subscriber "
        "> /tmp/patch_subscriber.log 2>&1 &"
    ),
}

# Scale-reduced BGP paths constants for DSF
SCALE_REDUCED_BGP_PATHS = {
    "uplink_peer_count": 1,
    "ixia_uplink_prefix_count_v6": 1,
}

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


def get_rdsw_ixia_peer_group_tasks(device_name):
    """
    Returns the RDSW IXIA peer group configuration tasks for DSF devices.
    This configures the peer group for uplink iBGP peering.
    """
    return [
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name="add_peer_group_patcher_PEERGROUP_RDSW_EDSW_V6",
            task_name="add_peer_group_patcher",
            patcher_args={
                "name": PEERGROUP_RDSW_EDSW_V6,
                "description": "BGP peering from RDSW to EDSW, IPv6 sessions",
                "disable_ipv4_afi": "True",
                "disable_ipv6_afi": "False",
                "ingress_policy_name": "PROPAGATE_RDSW_EDSW_IN",
                "egress_policy_name": "PROPAGATE_RDSW_EDSW_OUT",
                "bgp_peer_timers_hold_time_seconds": "30",
                "bgp_peer_timers_keep_alive_seconds": "10",
                "bgp_peer_timers_out_delay_seconds": "0",
                "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                "peer_tag": "EDSW",
                "max_routes": "900000",
                "warning_only": "True",
                "warning_limit": "0",
                "next_hop_self": "True",
                "add_path": "BOTH",
                "is_confed_peer": "False",
                "is_passive": "False",
                "v4_over_v6_nexthop": "False",
                "link_bandwidth_bps": "auto",
            },
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_RDSW_EDSW_IN",
            task_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_RDSW_EDSW_IN",
                "description": "Policy for RDSW EDSW IN",
            },
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_RDSW_EDSW_OUT",
            task_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_RDSW_EDSW_OUT",
                "description": "Policy for RDSW EDSW OUT",
            },
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_RDSW_EDSW_IN_v6",
            task_name="add_bgp_policy_match_prefix_to_propagate_routes",
            patcher_args={
                "matching_prefix": "5000::/16",
                "in_stmt_name": "PROPAGATE_RDSW_EDSW_IN",
                "out_stmt_name": "RANDOM",
            },
        ),
    ]


def test_config_for_dsf_hardening_in_conveyor(
    test_config_name,
    device_name,
    local_mac_address,
    ixia_downlink_interface,
    ixia_uplink_interface,
    ixia_rogue_interface,
    peergroup_uplink_mimic_v6,
    ixia_downlink_ic_parent_network_v6,
    ixia_uplink_ic_parent_network_v6,
    ixia_rogue_ic_parent_network_v6,
    prefix_limit,
    per_peer_max_route_limit,
    uplink_peer_count,
    remote_uplink_as_4byte,
    is_uplink_peer_confed,
    ixia_nexthop_supporting_ndp_network,
    ixia_nexthop_supporting_ndp_gateway,
    playbooks=None,
    direct_ixia_connections=None,
    basset_pool=None,
    remote_device_name=None,
    remote_device_mac_address=None,
    ixia_remote_interface=None,
    remote_direct_ixia_connections=None,
    ixia_remote_ic_parent_network_v6=None,
    dut_mgmt_ip=None,
):
    """
    DSF hardening test configuration.

    This is a configuration for DSF (Data Storage Fabric) hardening tests
    with the following characteristics:
    - iBGP uplink peering only (no downlink BGP)
    - Rogue interface for ECMP stressor with NDP support
    - Simplified traffic patterns for DSF topology
    - A slow FSDB subscriber (stress_test_client) is started on the remote
      device to subscribe to the DUT's agent state path with a high consume
      delay, simulating a slow consumer for hardening validation
    Details:  https://fburl.com/gdoc/e51gjwjk
    """
    # Build endpoints list
    endpoints = [
        taac_types.Endpoint(
            name=device_name,
            ixia_ports=[
                ixia_downlink_interface,
                ixia_uplink_interface,
                ixia_rogue_interface,
            ],
            dut=True,
            mac_address=local_mac_address,
            direct_ixia_connections=(
                direct_ixia_connections if direct_ixia_connections else []
            ),
        ),
        taac_types.Endpoint(
            name=remote_device_name,
            ixia_ports=[ixia_remote_interface],
            dut=False,
            mac_address=remote_device_mac_address,
            direct_ixia_connections=(
                remote_direct_ixia_connections if remote_direct_ixia_connections else []
            ),
        ),
    ]

    # TC-level checks moved to playbook level
    _tc_prechecks = [
        create_systemctl_active_state_check(),
        create_dsf_hardening_ixia_healthcheck(
            device_name,
            expect_loss_traffic=[],
            no_loss_traffic=[DSF_HARDENING_TRAFFIC_ITEM_RDSW_RDSW_SAME_CLUSTER],
            skip_traffic_items=[DSF_HARDENING_TRAFFIC_ITEM_GOLDEN],
        ),
    ]
    _tc_postchecks = [
        create_systemctl_active_state_check(),
        create_dsf_hardening_ixia_healthcheck(device_name),
        create_prefix_limit_check(prefix_limit=prefix_limit),
    ]
    _tc_snapshot_checks = [
        create_core_dumps_snapshot_check(),
    ]

    _ndp_churn_playbook = create_ndp_device_group_churn_playbook(
        duration_minutes=60,
        toggle_interval_seconds=30,
    )
    _ndp_churn_playbook = _ndp_churn_playbook(
        prechecks=_tc_prechecks,
        postchecks=_tc_postchecks,
        snapshot_checks=_tc_snapshot_checks,
    )

    return TestConfig(
        name=test_config_name,
        ixia_protocol_verification_timeout=10,
        skip_ixia_protocol_verification=True,
        basset_pool=basset_pool,
        endpoints=endpoints,
        setup_tasks=[
            create_run_commands_on_shell_task(
                hostname=remote_device_name,
                cmds=[
                    # All FSDB subscriber clients use the same stress_test_client binary,
                    # so a single pkill is sufficient to kill all client PIDs.
                    "pkill -f stress_test_client || true",
                ]
                + [
                    cmd.format(dut_mgmt_ip=dut_mgmt_ip)
                    for cmd in FSDB_SUBSCRIBER_CLIENTS.values()
                ],
            ),
        ],
        teardown_tasks=[
            create_coop_unregister_patchers_task(device_name),
            create_run_commands_on_shell_task(
                hostname=remote_device_name,
                # All FSDB subscriber clients use the same stress_test_client binary,
                # so a single pkill is sufficient to kill all client PIDs.
                cmds=["pkill -f stress_test_client || true"],
            ),
        ],
        # Deprecated - define at playbook level
        # periodic_tasks=[],
        basic_port_configs=[
            # Downlink port config (no BGP, just L2/L3 connectivity)
            taac_types.BasicPortConfig(
                l1_config=DSF_L1_CONFIG,
                endpoint=f"{device_name}:{ixia_downlink_interface}",
                device_group_configs=[
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        tag_name="DOWNLINK_L3_TRAFFIC",
                        multiplier=1,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_downlink_ic_parent_network_v6}::a000",
                            increment_ip="::",
                            gateway_starting_ip=f"{ixia_downlink_ic_parent_network_v6}::",
                            gateway_increment_ip="::",
                            mask=64,
                        ),
                    ),
                ],
            ),
            # Uplink port config (iBGP peering)
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
                            gateway_starting_ip=f"{ixia_uplink_ic_parent_network_v6}::",
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
                                    nexthop_start_value=f"{ixia_rogue_ic_parent_network_v6}::a000",
                                    nexthop_increments="::2",
                                    ecmp_width=2048,
                                    community_list=["65446:30"],
                                    network_group_index=0,
                                ),
                                ixia_types.CustomNetworkGroupConfig(
                                    device_group_name="BGP_ROUTE_INJECTOR",
                                    network_group_name="uplink_rogue_prefixes",
                                    network_group_multiplier=4096,
                                    prefix_start_value="5000:ee::",
                                    prefix_length=64,
                                    nexthop_start_value=f"{ixia_rogue_ic_parent_network_v6}::a000",
                                    nexthop_increments="::1",
                                    ecmp_width=2048,
                                    community_list=["65446:30"],
                                    network_group_index=1,
                                ),
                            ],
                        ),
                    ),
                ],
            ),
            # Rogue port config (ECMP stressor with NDP support)
            taac_types.BasicPortConfig(
                l1_config=DSF_L1_CONFIG,
                endpoint=f"{device_name}:{ixia_rogue_interface}",
                device_group_configs=[
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        tag_name="MIMIC_BGP_PEER",
                        multiplier=uplink_peer_count,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_uplink_ic_parent_network_v6}::100",
                            increment_ip="::",
                            gateway_starting_ip=f"{ixia_uplink_ic_parent_network_v6}::",
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
                                    nexthop_start_value=f"{ixia_rogue_ic_parent_network_v6}::a000",
                                    nexthop_increments="::1",
                                    ecmp_width=2048,
                                    community_list=["65446:30"],
                                    network_group_index=0,
                                ),
                                ixia_types.CustomNetworkGroupConfig(
                                    device_group_name="BGP_ROUTE_INJECTOR",
                                    network_group_name="uplink_rogue_prefixes",
                                    network_group_multiplier=4096,
                                    prefix_start_value="5000:ee::",
                                    prefix_length=64,
                                    nexthop_start_value=f"{ixia_rogue_ic_parent_network_v6}::a000",
                                    nexthop_increments="::1",
                                    ecmp_width=2048,
                                    community_list=["65446:30"],
                                    network_group_index=1,
                                ),
                            ],
                        ),
                    ),
                    # NDP supporting nexthop device group
                    taac_types.DeviceGroupConfig(
                        device_group_index=1,
                        tag_name="NDP_SUPPORTING_NEXTHOP",
                        enable=False,
                        multiplier=2000,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_rogue_ic_parent_network_v6}::a000",
                            increment_ip="::1",
                            gateway_starting_ip=f"{ixia_rogue_ic_parent_network_v6}::",
                            mask=64,
                        ),
                    ),
                ],
            ),
            # Remote device port config
            taac_types.BasicPortConfig(
                l1_config=DSF_L1_CONFIG,
                endpoint=f"{remote_device_name}:{ixia_remote_interface}",
                device_group_configs=[
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        tag_name="remote_port",
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
        ],
        traffic_items_to_start=[f"(?!{device_name.upper()}_HIGH_QUEUE_BGP_CP_TRAFFIC)"],
        basic_traffic_item_configs=[
            taac_types.BasicTrafficItemConfig(
                name=DSF_HARDENING_TRAFFIC_ITEM_GOLDEN,
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
            taac_types.BasicTrafficItemConfig(
                name=DSF_HARDENING_TRAFFIC_ITEM_RDSW_RDSW_SAME_CLUSTER,
                bidirectional=False,
                line_rate=50,
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
                        name=f"{remote_device_name}:{ixia_remote_interface}",
                        device_group_index=0,
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
            create_dsf_test_agent_warmboot_playbook(
                device_name=device_name,
                prefix_limit=prefix_limit,
                fsdb_subscriber_clients=FSDB_SUBSCRIBER_CLIENTS,
            ),
            _ndp_churn_playbook,
        ],
    )


# Create the DSF hardening test config for rdsw004.c085.n001.snc1
RDSW004_C085_N001_SNC1_HARDENING_NODE = test_config_for_dsf_hardening_in_conveyor(
    test_config_name="RDSW004_C085_N001_SNC1_HARDENING_NODE",
    device_name="rdsw004.c085.n001.snc1",
    local_mac_address="02:00:00:00:0f:0b",
    ixia_downlink_interface="eth1/11/1",
    ixia_uplink_interface="eth1/15/1",
    ixia_rogue_interface="eth1/25/1",
    peergroup_uplink_mimic_v6=PEERGROUP_RDSW_EDSW_V6,
    ixia_downlink_ic_parent_network_v6="2401:db00:11b:c460",
    ixia_uplink_ic_parent_network_v6="2401:db00:11b:c464",
    ixia_rogue_ic_parent_network_v6="2401:db00:11b:c46d",
    prefix_limit="75000",
    per_peer_max_route_limit="25000",
    uplink_peer_count=1,
    remote_uplink_as_4byte=4200000005,  # iBGP
    is_uplink_peer_confed="False",
    ixia_nexthop_supporting_ndp_network="2401:db00:11b:c46d::a000",
    ixia_nexthop_supporting_ndp_gateway="2401:db00:11b:c46d::",
    basset_pool="dsf.test",
    direct_ixia_connections=[
        taac_types.DirectIxiaConnection(
            interface="eth1/11/1",  # Downlink interface
            ixia_chassis_ip="2401:db00:116:3006:7ec2:55ff:fee0:fd44",
            ixia_port="1/19",
        ),
        taac_types.DirectIxiaConnection(
            interface="eth1/15/1",  # Uplink interface
            ixia_chassis_ip="2401:db00:116:3006:7ec2:55ff:fee0:fd44",
            ixia_port="1/13",
        ),
        taac_types.DirectIxiaConnection(
            interface="eth1/25/1",  # Rogue interface
            ixia_chassis_ip="2401:db00:116:3006:7ec2:55ff:fee0:fd44",
            ixia_port="1/11",
        ),
    ],
    remote_device_name="rdsw005.c085.n001.snc1",
    remote_device_mac_address="02:00:00:00:0f:0b",
    ixia_remote_interface="eth1/15/1",
    remote_direct_ixia_connections=[
        taac_types.DirectIxiaConnection(
            interface="eth1/15/1",
            ixia_chassis_ip="2401:db00:116:3006:7ec2:55ff:fee0:fd44",
            ixia_port="1/20",
        ),
    ],
    ixia_remote_ic_parent_network_v6="2401:db00:11b:c484",
    dut_mgmt_ip="2401:db00:116:3078::12",
)
