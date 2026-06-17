# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""NetworkAI hardening TestConfig builders + supporting IXIA health checks.

Provides the IXIA packet-loss split health checks (steady-state, etc.) and pre-defined
service-restart step lists used by the NetworkAI hardening conveyor TestConfig that
exercises agent/BGP/FSDB/QSFP service restarts under directional traffic.
"""

import json

from ixia.ixia import types as ixia_types
from taac.health_checks.constants import (
    SERVICES_TO_MONITOR_DURING_AGENT_RESTART,
    SERVICES_TO_MONITOR_DURING_BGP_RESTART,
    SERVICES_TO_MONITOR_DURING_FSDB_RESTART,
    SERVICES_TO_MONITOR_DURING_QSFP_SERVICE_RESTART,
)
from taac.health_checks.healthcheck_definitions import (
    create_bgp_session_establish_check,
    create_ixia_packet_loss_check_traffic_split,
    create_service_restart_check,
)
from taac.playbooks.playbook_definitions import (
    create_network_ai_hardening_agent_warmboot_playbook,
)
from taac.steps.step_definitions import (
    create_service_restart_steps,
)
from taac.task_definitions import (
    create_configure_parallel_bgp_peers_task,
    create_coop_apply_patchers_task,
    create_coop_register_patcher_task,
    create_coop_unregister_patchers_task,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import TestConfig

# Constants for Network AI hardening test
PEERGROUP_RTSW_FTSW_V6 = "PEERGROUP_RTSW_FTSW_V6"
PEERGROUP_RTSW_IXIA_V6 = "PEERGROUP_RTSW_IXIA_V6"

# Scale-reduced BGP paths constants
SCALE_REDUCED_BGP_PATHS = {
    "downlink_peer_count": 50,
    "uplink_peer_count": 50,
    "ixia_downlink_prefix_count_v6": 50,
    "ixia_uplink_prefix_count_v6": 50,
    "ixia_downlink_prefix_count_v4": 50,
    "ixia_uplink_prefix_count_v4": 50,
}

BGP_SESSION_HEALTHCHECK_NO_V6_LOSS_EXPECTED = create_bgp_session_establish_check(
    ignore_all_prefixes_except=[
        # Generate 50 IPv6 addresses with 8:: subnet (11,13,15,17,19,1b,...)
        f"2401:db00:e50d:11:8::{i:x}"
        for i in range(17, 117, 2)
    ]
    + [
        # Generate 50 IPv6 addresses with 9:: subnet, same hex pattern
        f"2401:db00:e50d:11:9::{i:x}"
        for i in range(17, 117, 2)
    ],
    verbose=True,
)


def create_service_restart_health_check(services_to_monitor):
    """
    Create a service restart monitoring check.

    Args:
        services_to_monitor: List of services to monitor during restart

    Returns:
        PointInTimeHealthCheck configured for service restart monitoring
    """
    return create_service_restart_check(services=services_to_monitor)


AGENT_RESTART_SERVICE_CHECK = create_service_restart_health_check(
    SERVICES_TO_MONITOR_DURING_AGENT_RESTART
)

BGP_RESTART_SERVICE_CHECK = create_service_restart_health_check(
    SERVICES_TO_MONITOR_DURING_BGP_RESTART
)

FSDB_RESTART_SERVICE_CHECK = create_service_restart_health_check(
    SERVICES_TO_MONITOR_DURING_FSDB_RESTART
)

QSFP_SERVICE_RESTART_SERVICE_CHECK = create_service_restart_health_check(
    SERVICES_TO_MONITOR_DURING_QSFP_SERVICE_RESTART
)


def create_ixia_healthcheck(
    device_name: str, expect_loss_traffic: list, no_loss_traffic: list
):
    """Build an IXIA packet-loss health check that splits traffic into expect/no-loss buckets.

    Thin wrapper around ``create_ixia_packet_loss_check_traffic_split`` that lets callers
    declare which traffic items are tolerated to lose packets and which must remain
    lossless during the health check window.

    Args:
        device_name: Device hostname for the underlying packet-loss check.
        expect_loss_traffic: Traffic-item names that may lose packets.
        no_loss_traffic: Traffic-item names that must remain lossless.

    Returns:
        IxiaPacketLossHealthCheck: Configured packet-loss health check.
    """
    return create_ixia_packet_loss_check_traffic_split(
        device_name=device_name,
        expect_loss_traffic=expect_loss_traffic,
        no_loss_traffic=no_loss_traffic,
    )


def get_ixia_healthcheck_stable_state(device_name: str):
    """IXIA health check enforcing no-loss on V6 directional + V6 L3 traffic in steady state.

    Tolerates loss only on the ``GOOD_BUT_LOSSY_NDP_TRAFFIC`` item (which may drop NDP
    requests by design). Used as the steady-state postcheck for NetworkAI hardening
    playbooks.

    Args:
        device_name: Device hostname for the underlying packet-loss check.
    """
    return create_ixia_healthcheck(
        device_name,
        expect_loss_traffic=["GOOD_BUT_LOSSY_NDP_TRAFFIC"],
        no_loss_traffic=[
            "V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
            "V6_LAYER3_TRAFFIC_DOWNLINK_AND_UPLINK",
        ],
    )


# Pre-defined step lists for common service restarts
BGP_RESTART_STEPS = create_service_restart_steps(taac_types.Service.BGP)
AGENT_RESTART_STEPS = create_service_restart_steps(taac_types.Service.AGENT)


def get_rtsw_ixia_peer_group_tasks(device_name):
    """
    Returns the common RTSW IXIA peer group configuration tasks for devices with "rtsw" in the name.
    This is shared between both get_bgp_peer_config_tasks and get_bgp_peer_config_tasks_downlinks.
    """
    return [
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name="add_peer_group_patcher_PEERGROUP_RTSW_IXIA_V6",
            task_name="add_peer_group_patcher",
            py_func_name="add_peer_group_patcher",
            patcher_args={
                "name": PEERGROUP_RTSW_IXIA_V6,
                "description": "BGP peering from RTSW to IXIA, IPV6 sessions",
                "next_hop_self": "True",
                "disable_ipv4_afi": "True",
                "disable_ipv6_afi": "False",
                "is_confed_peer": "False",
                "ingress_policy_name": "PROPAGATE_RTSW_IXIA_IN",
                "egress_policy_name": "PROPAGATE_RTSW_IXIA_OUT",
                "bgp_peer_timers_hold_time_seconds": "30",
                "bgp_peer_timers_keep_alive_seconds": "10",
                "bgp_peer_timers_out_delay_seconds": "7",
                "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                "peer_tag": "IXIA",
                "max_routes": "90000",
                "warning_only": "True",
                "warning_limit": "0",
                "link_bandwidth_bps": "auto",
                "v4_over_v6_nexthop": "False",
                "is_passive": "False",
                "receive_link_bandwidth": "1",
                "add_path": "BOTH",
            },
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_RTSW_IXIA_IN",
            task_name="add_bgp_policy_statement",
            py_func_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_RTSW_IXIA_IN",
                "description": "Policy for RTSW IXIA IN",
            },
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_RTSW_IXIA_OUT",
            task_name="add_bgp_policy_statement",
            py_func_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_RTSW_IXIA_OUT",
                "description": "Policy for RTSW IXIA OUT",
            },
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_RTSW_IXIA_IN_v6",
            task_name="add_bgp_policy_match_prefix_to_propagate_routes",
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
            patcher_args={
                "matching_prefix": "6000::/16",
                "in_stmt_name": "PROPAGATE_RTSW_IXIA_IN",
                "out_stmt_name": "RANDOM",
            },
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_RTSW_IXIA_OUT_v6",
            task_name="add_bgp_policy_match_prefix_to_propagate_routes",
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
            patcher_args={
                "matching_prefix": "7000::/16",
                "in_stmt_name": "PROPAGATE_RTSW_IXIA_IN",
                "out_stmt_name": "RANDOM",
            },
        ),
    ]


def get_bgp_peer_config_tasks_downlinks(
    device_name,
    peergroup_downlink_mimic_v6,
    is_downlink_peer_confed,
    per_peer_max_route_limit,
    downlink_peer_tag,
    route_map_downlink_ingress,
    route_map_downlink_egress,
    ecmp_group_overflow_prefix,
):
    """
    Returns the list of BGP peer configuration tasks for downlink only configuration.
    This is a simplified version of get_bgp_peer_config_tasks that only handles downlink peers.
    """
    tasks = []

    # Add RTSW IXIA peer groups if device name contains "rtsw"
    if "rtsw" in device_name:
        tasks.extend(get_rtsw_ixia_peer_group_tasks(device_name))

    # Add the downlink-only tasks
    tasks.extend(
        [
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"update_peer_group_patcher_{peergroup_downlink_mimic_v6}_Downlink",
                task_name="configure_bgp_peer_group",
                py_func_name="configure_bgp_peer_group",
                patcher_args={
                    "name": peergroup_downlink_mimic_v6,
                    "attributes_to_update_json": json.dumps(
                        {
                            "disable_ipv4_afi": "True",
                            "v4_over_v6_nexthop": "False",
                            "is_passive": "False",
                            "is_confed_peer": is_downlink_peer_confed,
                            "max_routes": per_peer_max_route_limit,
                        }
                    ),
                },
            ),
        ]
    )

    return tasks


def test_config_for_network_ai_hardening_in_conveyor(
    test_config_name,
    device_name,
    local_mac_address,
    ixia_downlink_interface,
    ixia_uplink_interface,
    ixia_ecmp_stressor_interface,
    peergroup_uplink_mimic_v6,
    peergroup_downlink_mimic_v6,
    ixia_downlink_ic_parent_network_v6,
    ixia_uplink_ic_parent_network_v6,
    ixia_ecmp_ic_parent_network_v6,
    prefix_limit,
    per_peer_max_route_limit,
    downlink_peer_count,
    uplink_peer_count,
    remote_downlink_as_4byte,
    remote_uplink_as_4byte,
    is_uplink_peer_confed,
    is_downlink_peer_confed,
    ixia_uplink_good_ndp_network,
    ixia_downlink_good_ndp_network,
    ixia_nexthop_supporting_ndp_network,
    playbooks=None,
    direct_ixia_connections=None,
    basset_pool=None,
):
    """
    Network AI hardening test configuration.

    This is a replicated and modified version of test_config_for_bgp_and_fboss_platform_hardening_in_conveyor
    with the following changes:
    - Removed static routes patchers and bgp_induced_ecmp_group_count usage
    - Removed all rogue-related components (rogue peers, traffic, etc.)
    - Simplified playbooks (can be empty list)
    """
    return TestConfig(
        name=test_config_name,
        ixia_protocol_verification_timeout=10,
        skip_ixia_protocol_verification=True,
        basset_pool=basset_pool,
        endpoints=[
            taac_types.Endpoint(
                name=device_name,
                ixia_ports=[
                    ixia_downlink_interface,
                    ixia_uplink_interface,
                    ixia_ecmp_stressor_interface,
                ],
                dut=True,
                mac_address=local_mac_address,
                direct_ixia_connections=direct_ixia_connections
                if direct_ixia_connections
                else [],
            ),
        ],
        setup_tasks=[
            # create_coop_unregister_patchers_task(device_name),
            # create_coop_apply_patchers_task([device_name], do_warmboot=True),
            # create_wait_for_agent_convergence_task([device_name]),
            # create_coop_register_patcher_task(
            #     hostname=device_name,
            #     config_name="bgpcpp",
            #     patcher_name="configure_bgp_switch_limit",
            #     task_name="configure_bgp_switch_limit",
            #     py_func_name="configure_bgp_switch_limit",
            #     patcher_args={
            #         "prefix_limit": prefix_limit,
            #     },
            # ),
        ]
        + get_bgp_peer_config_tasks_downlinks(
            device_name=device_name,
            peergroup_downlink_mimic_v6=peergroup_downlink_mimic_v6,
            is_downlink_peer_confed=is_downlink_peer_confed,
            per_peer_max_route_limit=per_peer_max_route_limit,
            downlink_peer_tag="IXIA",
            route_map_downlink_ingress="PROPAGATE_RTSW_IXIA_IN",
            route_map_downlink_egress="PROPAGATE_RTSW_IXIA_OUT",
            ecmp_group_overflow_prefix="7000",
        )
        + [
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="agent",
                patcher_name="enable_port_all_ixia_ports",
                task_name="change_port_admin_state",
                py_func_name="change_port_admin_state",
                patcher_args={
                    f"{ixia_uplink_interface}": "enable",
                    f"{ixia_downlink_interface}": "enable",
                    f"{ixia_ecmp_stressor_interface}": "enable",
                },
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"update_peer_group_patcher_{peergroup_uplink_mimic_v6}_Uplink",
                task_name="configure_bgp_peer_group",
                py_func_name="configure_bgp_peer_group",
                patcher_args={
                    "name": peergroup_uplink_mimic_v6,
                    "attributes_to_update_json": json.dumps(
                        {
                            "disable_ipv4_afi": "True",
                            "v4_over_v6_nexthop": "False",
                            "is_passive": "False",
                            "is_confed_peer": is_uplink_peer_confed,
                            "max_routes": per_peer_max_route_limit,
                        }
                    ),
                },
            ),
            create_configure_parallel_bgp_peers_task(
                hostname=device_name,
                configure_vlans_patcher_name="configure_vlans_patcher_name_downlink",
                add_bgp_peers_patcher_name="add_bgp_peers_patcher_name_downlink",
                config_json=json.dumps(
                    {
                        ixia_downlink_interface: [
                            {
                                "starting_ip": f"{ixia_downlink_ic_parent_network_v6}::10",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "Downlink IPv6 Peers",
                                "peer_group_name": peergroup_downlink_mimic_v6,
                                "num_sessions": downlink_peer_count,
                                "remote_as_4_byte": remote_downlink_as_4byte,
                                "remote_as_4_byte_step": 1,
                                "gateway_starting_ip": f"{ixia_downlink_ic_parent_network_v6}::11",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            {
                                "starting_ip": f"{ixia_downlink_good_ndp_network}::1",
                                "increment_ip": "0:0:0:0::0",
                                "prefix_length": 80,
                                "description": "Downlink IPv6 NDP Peers",
                                "peer_group_name": peergroup_downlink_mimic_v6,
                                "num_sessions": 1,
                                "remote_as_4_byte": remote_downlink_as_4byte,
                                "remote_as_4_byte_step": 0,
                                "gateway_starting_ip": f"{ixia_downlink_good_ndp_network}::2",
                                "gateway_increment_ip": "0:0:0:0::2",
                                "config_only_interface_ip": True,
                            },
                        ]
                    }
                ),
            ),
            create_configure_parallel_bgp_peers_task(
                hostname=device_name,
                configure_vlans_patcher_name="configure_vlans_patcher_name_uplink",
                add_bgp_peers_patcher_name="add_bgp_peers_patcher_name_uplink",
                config_json=json.dumps(
                    {
                        ixia_uplink_interface: [
                            {
                                "starting_ip": f"{ixia_uplink_ic_parent_network_v6}::10",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "Uplink IPv6 Peers",
                                "peer_group_name": peergroup_uplink_mimic_v6,
                                "num_sessions": uplink_peer_count,
                                "remote_as_4_byte": remote_uplink_as_4byte,
                                "remote_as_4_byte_step": 0,
                                "gateway_starting_ip": f"{ixia_uplink_ic_parent_network_v6}::11",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            {
                                "starting_ip": f"{ixia_uplink_good_ndp_network}::1",
                                "increment_ip": "0:0:0:0::0",
                                "prefix_length": 80,
                                "description": "NDP stressor",
                                "peer_group_name": peergroup_uplink_mimic_v6,
                                "num_sessions": 1,
                                "remote_as_4_byte": remote_uplink_as_4byte,
                                "remote_as_4_byte_step": 0,
                                "gateway_starting_ip": f"{ixia_uplink_ic_parent_network_v6}::2",
                                "gateway_increment_ip": "0:0:0:0::0",
                                "config_only_interface_ip": True,
                            },
                        ]
                    }
                ),
            ),
            create_configure_parallel_bgp_peers_task(
                hostname=device_name,
                configure_vlans_patcher_name="configure_vlans_patcher_name_ecmp_stressor",
                add_bgp_peers_patcher_name="add_bgp_peers_patcher_name_ecmp_stressor",
                config_json=json.dumps(
                    {
                        ixia_ecmp_stressor_interface: [
                            {
                                "starting_ip": f"{ixia_ecmp_ic_parent_network_v6}::10",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "ECMP Stressor IPv6 Peers",
                                "peer_group_name": PEERGROUP_RTSW_IXIA_V6,
                                "num_sessions": 2,
                                "remote_as_4_byte": remote_downlink_as_4byte,
                                "remote_as_4_byte_step": 0,
                                "gateway_starting_ip": f"{ixia_ecmp_ic_parent_network_v6}::11",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            {
                                "starting_ip": f"{ixia_nexthop_supporting_ndp_network}::1",
                                "increment_ip": "0:0:0:0::0",
                                "prefix_length": 80,
                                "description": "ECMP NDP stressor",
                                "peer_group_name": PEERGROUP_RTSW_IXIA_V6,
                                "num_sessions": 1,
                                "remote_as_4_byte": remote_downlink_as_4byte,
                                "remote_as_4_byte_step": 0,
                                "gateway_starting_ip": f"{ixia_nexthop_supporting_ndp_network}::a000",
                                "gateway_increment_ip": "0:0:0:0::0",
                                "config_only_interface_ip": True,
                            },
                        ]
                    }
                ),
            ),
            create_coop_apply_patchers_task(
                [device_name],
                do_warmboot=True,
            ),
            # create_wait_for_agent_convergence_task([device_name]),
            # Task(
            #     task_name="allocate_cgroup_slice_memory",
            #     params=Params(
            #         json_params=json.dumps(
            #             {
            #                 "hostname": device_name,
            #                 "workload_slice_based_total_memory_decimal": 0.25,
            #                 "slice_name": "workload",
            #             }
            #         ),
            #     ),
            #     run_post_ixia_setup=True,
            # ),
        ],
        teardown_tasks=[
            create_coop_unregister_patchers_task(device_name),
        ],
        # Deprecated - define at playbook level
        # periodic_tasks=[],
        basic_port_configs=[
            taac_types.BasicPortConfig(
                endpoint=f"{device_name}:{ixia_downlink_interface}",
                device_group_configs=[
                    # downlink IPv6 - NO_V6_PACKET_LOSS_EXPECTED
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        tag_name="DOWNLINK_NO_V6_PACKET_LOSS_EXPECTED",
                        multiplier=downlink_peer_count,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_downlink_ic_parent_network_v6}::11",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_downlink_ic_parent_network_v6}::10",
                            gateway_increment_ip="0:0:0:0::2",
                            mask=127,
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_downlink_as_4byte,
                            local_as_increment=1,
                            enable_4_byte_local_as=True,
                            is_confed=is_downlink_peer_confed == "True",
                            bgp_capabilities=[
                                ixia_types.BgpCapability.IpV6Unicast,
                            ],
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=SCALE_REDUCED_BGP_PATHS[
                                            "ixia_downlink_prefix_count_v6"
                                        ],
                                        prefix_length=64,
                                        starting_prefixes="7000:1::",
                                        prefix_step="0:0:0:0::0",
                                        bgp_communities=[],
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    ),
                                ),
                            ],
                        ),
                    ),
                    # NDP stressor downlink - DOWNLINK_NDP_STRESSOR
                    taac_types.DeviceGroupConfig(
                        device_group_index=1,
                        tag_name="DOWNLINK_NDP_STRESSOR",
                        multiplier=20,  # good_ndp_entries_downlink equivalent
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_downlink_good_ndp_network}::a000",
                            increment_ip="::1",
                            gateway_starting_ip=f"{ixia_downlink_good_ndp_network}::1",
                            mask=80,
                        ),
                    ),
                ],
            ),
            taac_types.BasicPortConfig(
                endpoint=f"{device_name}:{ixia_uplink_interface}",
                device_group_configs=[
                    # uplink IPv6 - NO_V6_PACKET_LOSS_EXPECTED
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        tag_name="NO_V6_PACKET_LOSS_EXPECTED",
                        multiplier=uplink_peer_count,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_uplink_ic_parent_network_v6}::11",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_uplink_ic_parent_network_v6}::10",
                            gateway_increment_ip="0:0:0:0::2",
                            mask=127,
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_uplink_as_4byte,
                            local_as_increment=0,
                            enable_4_byte_local_as=True,
                            bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                            is_confed=is_uplink_peer_confed == "True",
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=SCALE_REDUCED_BGP_PATHS[
                                            "ixia_uplink_prefix_count_v6"
                                        ],
                                        prefix_length=64,
                                        starting_prefixes="6000:1::",
                                        prefix_step="0:0:0:0::0",
                                        bgp_communities=[
                                            "65441:259",
                                            "65442:260",
                                            "65446:30",
                                            "65456:259",
                                            "65456:260",
                                            "65457:257",
                                            "65457:258",
                                            "65527:12711",
                                        ],
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    ),
                                ),
                            ],
                        ),
                    ),
                    # NDP stressor uplink - UPLINK_NDP_STRESSOR
                    taac_types.DeviceGroupConfig(
                        device_group_index=1,
                        tag_name="UPLINK_NDP_STRESSOR",
                        multiplier=20,  # good_ndp_entries_uplink equivalent
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_uplink_good_ndp_network}::a000",
                            increment_ip="::1",
                            gateway_starting_ip=f"{ixia_uplink_good_ndp_network}::1",
                            mask=80,
                        ),
                    ),
                ],
            ),
            taac_types.BasicPortConfig(
                endpoint=f"{device_name}:{ixia_ecmp_stressor_interface}",
                device_group_configs=[
                    # ECMP stressor IPv6 - NO_V6_PACKET_LOSS_EXPECTED
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        tag_name="MULTI_NETWORK_GROUP_GOLDEN",
                        multiplier=1,  # num_sessions = 1 as requested
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_ecmp_ic_parent_network_v6}::11",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_ecmp_ic_parent_network_v6}::10",
                            gateway_increment_ip="0:0:0:0::2",
                            mask=127,
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_downlink_as_4byte,
                            local_as_increment=0,
                            enable_4_byte_local_as=True,
                            is_confed=is_downlink_peer_confed
                            == "True",  # Use downlink confed setting
                            bgp_capabilities=[
                                ixia_types.BgpCapability.IpV6Unicast,
                                ixia_types.BgpCapability.Ipv6UnicastAddPath,
                            ],
                            # Multi Network Group Configuration for ECMP Stressor
                            # multi_network_group_config=taac_types.MultiNetworkGroupConfig(
                            #     network_group_names=[
                            #         f"ecmp_network_group_{i}"
                            #         for i in range(
                            #             3, 46
                            #         )  # Range from 3 to 45 (similar to NSF hardening)
                            #     ],
                            #     prefix_list=[
                            #         f"6000:ee:{i:x}::"
                            #         for i in range(
                            #             3, 46
                            #         )  # Generate unique prefixes for ECMP
                            #     ],
                            #     community_list=["65446:301"],  # Community as requested
                            #     network_group_multiplier=10,  # Similar to NSF hardening
                            #     ipv6_next_hop_start_id_list=[
                            #         f"2401:db00:209a:62::a{i:03x}"
                            #         for i in range(3, 46)  # Use ECMP network base
                            #     ],
                            # ),
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=SCALE_REDUCED_BGP_PATHS[
                                            "ixia_downlink_prefix_count_v6"
                                        ],  # Use downlink prefix count similar to downlink config
                                        prefix_length=64,
                                        starting_prefixes="6000:ee::",  # Use unique prefix range for ECMP
                                        prefix_step="0:0:0:0::0",
                                        bgp_communities=[
                                            "65441:133",
                                            "65442:133",
                                            "65446:30",
                                            "65456:132",
                                            "65456:133",
                                            "65456:259",
                                            "65456:260",
                                            "65457:129",
                                            "65457:130",
                                            "65457:257",
                                            "65457:258",
                                            "65529:52781",
                                            "65529:52791",
                                        ],
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    ),
                                ),
                            ],
                        ),
                    ),
                    # Additional MULTI_NETWORK_GROUP device group
                    taac_types.DeviceGroupConfig(
                        device_group_index=1,
                        tag_name="NDP_SUPPORTING_NEXTHOP",
                        multiplier=2000,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_nexthop_supporting_ndp_network}::a000",
                            increment_ip="::1",
                            gateway_starting_ip=f"{ixia_nexthop_supporting_ndp_network}::1",
                            mask=80,
                        ),
                    ),
                    taac_types.DeviceGroupConfig(
                        device_group_index=2,
                        tag_name="MULTI_NETWORK_GROUP_ROGUE",
                        multiplier=1,  # num_sessions = 1 as requested
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_ecmp_ic_parent_network_v6}::13",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_ecmp_ic_parent_network_v6}::12",
                            gateway_increment_ip="0:0:0:0::2",
                            mask=127,
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_downlink_as_4byte,
                            local_as_increment=0,
                            enable_4_byte_local_as=True,
                            is_confed=is_downlink_peer_confed
                            == "True",  # Use downlink confed setting
                            bgp_capabilities=[
                                ixia_types.BgpCapability.IpV6Unicast,
                                ixia_types.BgpCapability.Ipv6UnicastAddPath,
                            ],
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=SCALE_REDUCED_BGP_PATHS[
                                            "ixia_downlink_prefix_count_v6"
                                        ],  # Use downlink prefix count similar to downlink config
                                        prefix_length=64,
                                        starting_prefixes="6000:dd::",  # Use unique prefix range for ECMP
                                        prefix_step="0:0:0:0::0",
                                        bgp_communities=[
                                            "65441:133",
                                            "65442:133",
                                            "65446:30",
                                            "65456:132",
                                            "65456:133",
                                            "65456:259",
                                            "65456:260",
                                            "65457:129",
                                            "65457:130",
                                            "65457:257",
                                            "65457:258",
                                            "65529:52781",
                                            "65529:52791",
                                        ],
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    ),
                                ),
                            ],
                        ),
                    ),
                ],
            ),
        ],
        traffic_items_to_start=[f"(?!{device_name.upper()}_HIGH_QUEUE_BGP_CP_TRAFFIC)"],
        basic_traffic_item_configs=[],
        # Deprecated - define at playbook level
        # snapshot_checks=[
        #     SnapshotHealthCheck(name=hc_types.CheckName.CORE_DUMPS_CHECK),
        # ],
        # Deprecated - define at playbook level
        # postchecks=[
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.SYSTEMCTL_ACTIVE_STATE_CHECK,
        #     ),
        #     get_ixia_healthcheck_stable_state(device_name),
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.PREFIX_LIMIT_CHECK,
        #         check_params=Params(
        #             json_params=json.dumps(
        #                 {
        #                     "prefix_limit": prefix_limit,
        #                 }
        #             )
        #         ),
        #     ),
        #     BGP_SESSION_HEALTHCHECK_NO_V6_LOSS_EXPECTED,
        # ],
        # Deprecated - define at playbook level
        # prechecks=[
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.SYSTEMCTL_ACTIVE_STATE_CHECK,
        #     ),
        #     get_ixia_healthcheck_stable_state(device_name),
        #     BGP_SESSION_HEALTHCHECK_NO_V6_LOSS_EXPECTED,
        # ],
        playbooks=[
            create_network_ai_hardening_agent_warmboot_playbook(
                ixia_stable_state_healthcheck=get_ixia_healthcheck_stable_state(
                    device_name
                ),
                bgp_session_healthcheck=BGP_SESSION_HEALTHCHECK_NO_V6_LOSS_EXPECTED,
                agent_restart_service_check=AGENT_RESTART_SERVICE_CHECK,
                prefix_limit=prefix_limit,
            ),
        ],
    )


# Create the object as requested using the specified parameters
RTSW002_L101_C083_HARDENING_NODE = test_config_for_network_ai_hardening_in_conveyor(
    test_config_name="RTSW002_L101_C083_HARDENING_NODE",
    device_name="rtsw002.l101.c083.ash6",
    local_mac_address="b6:db:91:95:fe:34",
    ixia_downlink_interface="eth1/3/1",
    ixia_uplink_interface="eth1/3/5",
    ixia_ecmp_stressor_interface="eth1/18/1",
    peergroup_uplink_mimic_v6=PEERGROUP_RTSW_FTSW_V6,
    peergroup_downlink_mimic_v6=PEERGROUP_RTSW_IXIA_V6,
    ixia_downlink_ic_parent_network_v6="2401:db00:e50d:11:8",
    ixia_uplink_ic_parent_network_v6="2401:db00:e50d:11:9",
    ixia_ecmp_ic_parent_network_v6="2401:db00:e50d:11:a",
    prefix_limit="75000",
    per_peer_max_route_limit="25000",
    downlink_peer_count=SCALE_REDUCED_BGP_PATHS["downlink_peer_count"],
    uplink_peer_count=SCALE_REDUCED_BGP_PATHS["uplink_peer_count"],
    remote_downlink_as_4byte=65321,  # EBGP
    remote_uplink_as_4byte=4200000131,  # IBGP
    is_uplink_peer_confed="False",
    is_downlink_peer_confed="False",
    ixia_uplink_good_ndp_network="2401:db00:e50d:1101:9",
    ixia_downlink_good_ndp_network="2401:db00:e50d:1101:8",
    ixia_nexthop_supporting_ndp_network="2401:db00:e50d:1101:a",
    basset_pool="networkai.test",
)


RTSW001_L101_C083_HARDENING_NODE = test_config_for_network_ai_hardening_in_conveyor(
    test_config_name="RTSW001_L101_C083_HARDENING_NODE",
    device_name="rtsw001.l101.c083.ash6",
    local_mac_address="b6:db:91:95:fe:19",
    ixia_downlink_interface="eth1/2/1",
    ixia_uplink_interface="eth1/2/5",
    ixia_ecmp_stressor_interface="eth1/18/1",
    peergroup_uplink_mimic_v6=PEERGROUP_RTSW_FTSW_V6,
    peergroup_downlink_mimic_v6=PEERGROUP_RTSW_IXIA_V6,
    ixia_downlink_ic_parent_network_v6="2401:db00:e50d:11:6",
    ixia_uplink_ic_parent_network_v6="2401:db00:e50d:11:7",
    ixia_ecmp_ic_parent_network_v6="2401:db00:e50d:11:a",
    prefix_limit="75000",
    per_peer_max_route_limit="25000",
    downlink_peer_count=SCALE_REDUCED_BGP_PATHS["downlink_peer_count"],
    uplink_peer_count=SCALE_REDUCED_BGP_PATHS["uplink_peer_count"],
    remote_downlink_as_4byte=65321,  # EBGP
    remote_uplink_as_4byte=4200000131,  # IBGP
    is_uplink_peer_confed="False",
    is_downlink_peer_confed="False",
    ixia_uplink_good_ndp_network="2401:db00:e50d:1101:7",
    ixia_downlink_good_ndp_network="2401:db00:e50d:1101:6",
    ixia_nexthop_supporting_ndp_network="2401:db00:e50d:1101:a",
    basset_pool="networkai.test",
)


RTSW003_L101_C083_HARDENING_NODE = test_config_for_network_ai_hardening_in_conveyor(
    test_config_name="RTSW003_L101_C083_HARDENING_NODE",
    device_name="rtsw003.l101.c083.ash6",
    local_mac_address="ae:81:b5:03:41:41",
    ixia_downlink_interface="eth1/3/1",
    ixia_uplink_interface="eth1/3/5",
    ixia_ecmp_stressor_interface="eth1/18/1",
    peergroup_uplink_mimic_v6=PEERGROUP_RTSW_FTSW_V6,
    peergroup_downlink_mimic_v6=PEERGROUP_RTSW_IXIA_V6,
    ixia_downlink_ic_parent_network_v6="2401:db00:e50d:11:c",
    ixia_uplink_ic_parent_network_v6="2401:db00:e50d:11:d",
    ixia_ecmp_ic_parent_network_v6="2401:db00:e50d:11:a",
    prefix_limit="75000",
    per_peer_max_route_limit="25000",
    downlink_peer_count=SCALE_REDUCED_BGP_PATHS["downlink_peer_count"],
    uplink_peer_count=SCALE_REDUCED_BGP_PATHS["uplink_peer_count"],
    remote_downlink_as_4byte=65321,  # EBGP
    remote_uplink_as_4byte=4200000131,  # IBGP
    is_uplink_peer_confed="False",
    is_downlink_peer_confed="False",
    ixia_uplink_good_ndp_network="2401:db00:e50d:1101:d",
    ixia_downlink_good_ndp_network="2401:db00:e50d:1101:c",
    ixia_nexthop_supporting_ndp_network="2401:db00:e50d:1101:a",
    basset_pool="networkai.test",
)
