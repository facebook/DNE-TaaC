# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""TestConfig builders for BGP/FBOSS platform hardening on 1- and 2-IXIA-chassis topologies.

Provides ``test_config_for_2_ixia_bgp_and_fboss_platform_hardening_in_conveyor`` (uplink
+ downlink + rogue) and ``test_config_for_1_ixia_bgp_and_fboss_platform_hardening_in_conveyor``
(uplink-only) along with the FAUU EB peer-group / per-direction BGP-config task helpers.
Used by the per-platform conveyor entry points (Wedge100S, Wedge400C).
"""

import json

from ixia.ixia import types as ixia_types
from taac.constants import (
    ARP_SOFT_LIMIT,
    BROADCAST_DST_MAC_ADDRESS,
    DEFAULT_SRC_MAC_ADDRESS,
    MAC_SOFT_LIMIT,
    NDP_SOFT_LIMIT,
    ROGUE_SRC_MAC_ADDRESS,
)
from taac.health_checks.healthcheck_definitions import (
    create_bgp_convergence_check,
    create_bgp_rib_fib_consistency_check,
    create_bgp_session_snapshot_check,
    create_core_dumps_snapshot_check,
    create_cpu_utilization_check,
    create_device_core_dumps_check,
    create_ixia_packet_loss_check,
    create_l2_entry_threshold_check,
    create_memory_utilization_check,
    create_prefix_limit_check,
    create_service_restart_check,
    create_unclean_exit_check,
)
from taac.packet_headers import BGP_CP_TRAFFIC_PACKET_HEADERS
from taac.playbooks.playbook_definitions import (
    build_2_ixia_hardening_playbook,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_ecmp_member_static_route_step,
    create_ixia_api_step,
    create_longevity_step,
    create_service_convergence_step,
    create_service_interruption_step,
)
from taac.task_definitions import (
    create_configure_parallel_bgp_peers_task,
    create_coop_apply_patchers_task,
    create_coop_apply_patchers_v2_task,
    create_coop_register_patcher_task,
    create_coop_unregister_patchers_task,
    create_run_commands_on_shell_task,
    create_wait_for_bgp_convergence_task,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import Service, TestConfig


def get_fauu_eb_peer_group_tasks(device_name):
    """
    Returns the common FAUU EB peer group configuration tasks for devices with "uu" in the name.
    This is shared between both get_bgp_peer_config_tasks and get_bgp_peer_config_tasks_uplink_only.
    """
    return [
        create_coop_register_patcher_task(
            hostname=device_name,
            config_names=[
                "bgpcpp",
            ],
            patcher_name="add_peer_group_patcher_PEERGROUP_FAUU_EB_V6",
            py_func_name="add_peer_group_patcher",
            patcher_args={
                "name": "PEERGROUP_FAUU_EB_V6",
                "description": "BGP peering from FAUU to EB, IPV6 sessions",
                "next_hop_self": "True",
                "disable_ipv4_afi": "True",
                "disable_ipv6_afi": "False",
                "is_confed_peer": "False",
                "ingress_policy_name": "PROPAGATE_FAUU_EB_IN",
                "egress_policy_name": "PROPAGATE_FAUU_EB_OUT",
                "bgp_peer_timers_hold_time_seconds": "30",
                "bgp_peer_timers_keep_alive_seconds": "10",
                "bgp_peer_timers_out_delay_seconds": "7",
                "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                "peer_tag": "EB",
                "max_routes": "90000",
                "warning_only": "True",
                "warning_limit": "0",
                "link_bandwidth_bps": "auto",
                "v4_over_v6_nexthop": "False",
                "is_passive": "False",
                "receive_link_bandwidth": "1",
            },
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_names=[
                "bgpcpp_softdrain",
            ],
            patcher_name="add_peer_group_patcher_PEERGROUP_FAUU_EB_V6",
            py_func_name="add_peer_group_patcher",
            patcher_args={
                "name": "PEERGROUP_FAUU_EB_V6",
                "description": "BGP peering from FAUU to EB, IPV6 sessions",
                "next_hop_self": "True",
                "disable_ipv4_afi": "True",
                "disable_ipv6_afi": "False",
                "is_confed_peer": "False",
                "ingress_policy_name": "PROPAGATE_FAUU_EB_IN",
                "egress_policy_name": "PROPAGATE_FAUU_EB_OUT_DRAIN",
                "bgp_peer_timers_hold_time_seconds": "30",
                "bgp_peer_timers_keep_alive_seconds": "10",
                "bgp_peer_timers_out_delay_seconds": "7",
                "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                "peer_tag": "EB",
                "max_routes": "90000",
                "warning_only": "True",
                "warning_limit": "0",
                "link_bandwidth_bps": "auto",
                "v4_over_v6_nexthop": "False",
                "is_passive": "False",
                "receive_link_bandwidth": "1",
            },
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_names=[
                "bgpcpp",
                "bgpcpp_softdrain",
            ],
            patcher_name="add_peer_group_patcher_PEERGROUP_FAUU_EB_V4",
            py_func_name="add_peer_group_patcher",
            patcher_args={
                "name": "PEERGROUP_FAUU_EB_V4",
                "description": "BGP peering from FAUU to EB, IPV4 sessions",
                "next_hop_self": "True",
                "disable_ipv4_afi": "False",
                "disable_ipv6_afi": "True",
                "is_confed_peer": "False",
                "ingress_policy_name": "PROPAGATE_FAUU_EB_IN",
                "egress_policy_name": "PROPAGATE_FAUU_EB_OUT",
                "bgp_peer_timers_hold_time_seconds": "30",
                "bgp_peer_timers_keep_alive_seconds": "10",
                "bgp_peer_timers_out_delay_seconds": "7",
                "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                "peer_tag": "EB",
                "max_routes": "90000",
                "warning_only": "True",
                "warning_limit": "0",
                "link_bandwidth_bps": "auto",
                "v4_over_v6_nexthop": "False",
                "is_passive": "False",
                "receive_link_bandwidth": "1",
            },
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_names=[
                "bgpcpp",
                "bgpcpp_softdrain",
            ],
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_FAUU_EB_IN",
            py_func_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_FAUU_EB_IN",
                "description": "Policy for EB IN",
            },
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_names=[
                "bgpcpp",
            ],
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_FAUU_EB_OUT",
            py_func_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_FAUU_EB_OUT",
                "description": "Policy for EB OUT",
            },
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_names=[
                "bgpcpp_softdrain",
            ],
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_FAUU_EB_OUT_DRAIN",
            py_func_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_FAUU_EB_OUT_DRAIN",
                "description": "Policy for EB OUT Drain",
            },
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_names=[
                "bgpcpp",
                "bgpcpp_softdrain",
            ],
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FAUU_EB_IN_v6",
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
            patcher_args={
                "matching_prefix": "6000::/16",
                "in_stmt_name": "PROPAGATE_FAUU_EB_IN",
                "out_stmt_name": "RANDOM",
            },
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_names=[
                "bgpcpp",
                "bgpcpp_softdrain",
            ],
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FAUU_EB_IN_v6_bgp_ecmp",
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
            patcher_args={
                "matching_prefix": "7000::/16",
                "in_stmt_name": "PROPAGATE_FAUU_EB_IN",
                "out_stmt_name": "RANDOM",
            },
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_names=[
                "bgpcpp",
                "bgpcpp_softdrain",
            ],
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FAUU_EB_IN_v6_bgp_ecmp",
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
            patcher_args={
                "matching_prefix": "102.0.0.0/8",
                "in_stmt_name": "PROPAGATE_FAUU_EB_IN",
                "out_stmt_name": "RANDOM",
            },
        ),
    ]


def get_bgp_peer_config_tasks_uplink_only(
    device_name,
    peergroup_uplink_mimic_v6,
    peergroup_uplink_mimic_v4,
    is_uplink_peer_confed,
    per_peer_max_route_limit,
    uplink_peer_tag,
    route_map_uplink_ingress,
    route_map_uplink_egress,
    ecmp_group_overflow_prefix,
):
    """
    Returns the list of BGP peer configuration tasks for uplink only configuration.
    This is a simplified version of get_bgp_peer_config_tasks that only handles uplink peers.
    """
    tasks = []

    # Add FAUU EB peer groups if device name contains "uu"
    if "uu" in device_name:
        tasks.extend(get_fauu_eb_peer_group_tasks(device_name))

    # Add the uplink-only tasks
    tasks.extend(
        [
            create_coop_register_patcher_task(
                hostname=device_name,
                config_names=[
                    "bgpcpp",
                    "bgpcpp_softdrain",
                ],
                patcher_name=f"update_peer_group_patcher_{peergroup_uplink_mimic_v6}_Uplink",
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
            create_coop_register_patcher_task(
                hostname=device_name,
                config_names=[
                    "bgpcpp",
                ],
                patcher_name=f"add_peer_group_patcher_{peergroup_uplink_mimic_v4}",
                py_func_name="add_peer_group_patcher",
                patcher_args={
                    "name": peergroup_uplink_mimic_v4,
                    "description": "BGP peering from SSW to FSW, IPv4 sessions",
                    "next_hop_self": "True",
                    "disable_ipv4_afi": "False",
                    "disable_ipv6_afi": "True",
                    "is_confed_peer": is_uplink_peer_confed,
                    "peer_tag": uplink_peer_tag,
                    "ingress_policy_name": route_map_uplink_ingress,
                    "egress_policy_name": route_map_uplink_egress,
                    "bgp_peer_timers_hold_time_seconds": "30",
                    "bgp_peer_timers_keep_alive_seconds": "10",
                    "bgp_peer_timers_out_delay_seconds": "7",
                    "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                    "max_routes": per_peer_max_route_limit,
                    "warning_only": "True",
                    "warning_limit": "0",
                    "link_bandwidth_bps": "auto",
                    "v4_over_v6_nexthop": "False",
                    "is_passive": "False",
                },
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_names=[
                    "bgpcpp_softdrain",
                ],
                patcher_name=f"add_peer_group_patcher_{peergroup_uplink_mimic_v4}",
                py_func_name="add_peer_group_patcher",
                patcher_args={
                    "name": peergroup_uplink_mimic_v4,
                    "description": "BGP peering from SSW to FSW, IPv4 sessions",
                    "next_hop_self": "True",
                    "disable_ipv4_afi": "False",
                    "disable_ipv6_afi": "True",
                    "is_confed_peer": is_uplink_peer_confed,
                    "peer_tag": uplink_peer_tag,
                    "ingress_policy_name": route_map_uplink_ingress,
                    "egress_policy_name": route_map_uplink_egress + "_DRAIN",
                    "bgp_peer_timers_hold_time_seconds": "30",
                    "bgp_peer_timers_keep_alive_seconds": "10",
                    "bgp_peer_timers_out_delay_seconds": "7",
                    "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                    "max_routes": per_peer_max_route_limit,
                    "warning_only": "True",
                    "warning_limit": "0",
                    "link_bandwidth_bps": "auto",
                    "v4_over_v6_nexthop": "False",
                    "is_passive": "False",
                },
            ),
            create_wait_for_bgp_convergence_task(hostnames=[device_name]),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_names=[
                    "bgpcpp",
                    "bgpcpp_softdrain",
                ],
                patcher_name=f"add_bgp_policy_match_prefix_to_propagate_routes_{route_map_uplink_ingress}",
                py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
                patcher_args={
                    "matching_prefix": f"{ecmp_group_overflow_prefix}::/16",
                    "in_stmt_name": route_map_uplink_ingress,
                    "out_stmt_name": "RANDOM",
                },
            ),
            create_coop_apply_patchers_v2_task(
                hostnames=[device_name],
                apply_patcher_method=taac_types.ApplyPatcherMethod.BGP_RESTART.value,
            ),
        ]
    )
    return tasks


def get_bgp_peer_config_tasks(
    device_name,
    peergroup_downlink_mimic_v6,
    peergroup_uplink_mimic_v6,
    peergroup_uplink_mimic_v4,
    peergroup_downlink_mimic_v4,
    is_downlink_peer_confed,
    is_uplink_peer_confed,
    per_peer_max_route_limit,
    uplink_peer_tag,
    downlink_peer_tag,
    route_map_uplink_ingress,
    route_map_uplink_egress,
    route_map_downlink_ingress,
    route_map_downlink_egress,
    ecmp_group_overflow_prefix,
    v6_uplink_prefix,
):
    """
    Returns the list of BGP peer configuration tasks that were originally part of list b in
    test_config_for_2_ixia_bgp_and_fboss_platform_hardening_in_conveyor.py
    """
    tasks = []

    # Add FAUU EB peer groups if device name contains "uu"
    if "uu" in device_name:
        tasks.extend(get_fauu_eb_peer_group_tasks(device_name))

    # Add the original tasks
    tasks.extend(
        [
            create_coop_register_patcher_task(
                hostname=device_name,
                config_names=[
                    "bgpcpp",
                    "bgpcpp_softdrain",
                ],
                patcher_name="update_peer_group_patcher_V6_Downlink",
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
            # Task(
            #     task_name="coop_register_patcher",
            #     params=Params(
            #         json_params=json.dumps(
            #             {
            #                 "hostname": device_name,
            #                 "config_name": "bgpcpp",
            #                 "patcher_name": f"update_peer_group_patcher_{peergroup_uplink_mimic_v6}_Uplink",
            #                 "py_func_name": "configure_bgp_peer_group",
            #                 "patcher_args": json.dumps(
            #                     {
            #                         "name": peergroup_uplink_mimic_v6,
            #                         "attributes_to_update_json": json.dumps(
            #                             {
            #                                 "disable_ipv4_afi": "True",
            #                                 "v4_over_v6_nexthop": "False",
            #                                 "is_passive": "False",
            #                                 "is_confed_peer": is_uplink_peer_confed,
            #                                 "max_routes": per_peer_max_route_limit,
            #                             }
            #                         ),
            #                     }
            #                 ),
            #             },
            #         )
            #     ),
            # ),
            # Task(
            #     task_name="coop_register_patcher",
            #     params=Params(
            #         json_params=json.dumps(
            #             {
            #                 "hostname": device_name,
            #                 "config_name": "bgpcpp",
            #                 "patcher_name": f"add_peer_group_patcher_{peergroup_uplink_mimic_v4}",
            #                 "py_func_name": "add_peer_group_patcher",
            #                 "patcher_args": json.dumps(
            #                     {
            #                         "name": peergroup_uplink_mimic_v4,
            #                         "description": "BGP peering from SSW to FSW, IPv4 sessions",
            #                         "next_hop_self": "True",
            #                         "disable_ipv4_afi": "False",
            #                         "disable_ipv6_afi": "True",
            #                         "is_confed_peer": is_uplink_peer_confed,
            #                         "peer_tag": uplink_peer_tag,
            #                         "ingress_policy_name": route_map_uplink_ingress,
            #                         "egress_policy_name": route_map_uplink_egress,
            #                         "bgp_peer_timers_hold_time_seconds": "30",
            #                         "bgp_peer_timers_keep_alive_seconds": "10",
            #                         "bgp_peer_timers_out_delay_seconds": "7",
            #                         "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
            #                         "max_routes": per_peer_max_route_limit,
            #                         "warning_only": "True",
            #                         "warning_limit": "0",
            #                         "link_bandwidth_bps": "auto",
            #                         "v4_over_v6_nexthop": "False",
            #                         "is_passive": "False",
            #                     }
            #                 ),
            #             },
            #         )
            #     ),
            # ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_names=[
                    "bgpcpp",
                ],
                patcher_name=f"add_peer_group_patcher_{peergroup_downlink_mimic_v6}",
                py_func_name="add_peer_group_patcher",
                patcher_args={
                    "name": peergroup_downlink_mimic_v6,
                    "description": "BGP peering from RSW to FSW, IPv4 sessions",
                    "next_hop_self": "True",
                    "disable_ipv4_afi": "False",
                    "disable_ipv6_afi": "True",
                    "is_confed_peer": is_downlink_peer_confed,
                    "ingress_policy_name": route_map_downlink_ingress,
                    "egress_policy_name": route_map_downlink_egress,
                    "bgp_peer_timers_hold_time_seconds": "30",
                    "bgp_peer_timers_keep_alive_seconds": "10",
                    "bgp_peer_timers_out_delay_seconds": "7",
                    "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                    "peer_tag": downlink_peer_tag,
                    "max_routes": per_peer_max_route_limit,
                    "warning_only": "True",
                    "warning_limit": "0",
                    "link_bandwidth_bps": "auto",
                    "v4_over_v6_nexthop": "False",
                    "is_passive": "False",
                },
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_names=[
                    "bgpcpp_softdrain",
                ],
                patcher_name=f"add_peer_group_patcher_{peergroup_downlink_mimic_v6}",
                py_func_name="add_peer_group_patcher",
                patcher_args={
                    "name": peergroup_downlink_mimic_v6,
                    "description": "BGP peering from RSW to FSW, IPv4 sessions",
                    "next_hop_self": "True",
                    "disable_ipv4_afi": "False",
                    "disable_ipv6_afi": "True",
                    "is_confed_peer": is_downlink_peer_confed,
                    "ingress_policy_name": route_map_downlink_ingress,
                    "egress_policy_name": route_map_downlink_egress + "_DRAIN",
                    "bgp_peer_timers_hold_time_seconds": "30",
                    "bgp_peer_timers_keep_alive_seconds": "10",
                    "bgp_peer_timers_out_delay_seconds": "7",
                    "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                    "peer_tag": downlink_peer_tag,
                    "max_routes": per_peer_max_route_limit,
                    "warning_only": "True",
                    "warning_limit": "0",
                    "link_bandwidth_bps": "auto",
                    "v4_over_v6_nexthop": "False",
                    "is_passive": "False",
                },
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_names=[
                    "bgpcpp",
                ],
                patcher_name=f"add_peer_group_patcher_{peergroup_uplink_mimic_v4}",
                py_func_name="add_peer_group_patcher",
                patcher_args={
                    "name": peergroup_uplink_mimic_v4,
                    "description": "BGP peering from SSW to FSW, IPv4 sessions",
                    "next_hop_self": "True",
                    "disable_ipv4_afi": "False",
                    "disable_ipv6_afi": "True",
                    "is_confed_peer": is_uplink_peer_confed,
                    "peer_tag": uplink_peer_tag,
                    "ingress_policy_name": route_map_uplink_ingress,
                    "egress_policy_name": route_map_uplink_egress,
                    "bgp_peer_timers_hold_time_seconds": "30",
                    "bgp_peer_timers_keep_alive_seconds": "10",
                    "bgp_peer_timers_out_delay_seconds": "7",
                    "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                    "max_routes": per_peer_max_route_limit,
                    "warning_only": "True",
                    "warning_limit": "0",
                    "link_bandwidth_bps": "auto",
                    "v4_over_v6_nexthop": "False",
                    "is_passive": "False",
                },
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_names=[
                    "bgpcpp_softdrain",
                ],
                patcher_name=f"add_peer_group_patcher_{peergroup_uplink_mimic_v4}",
                py_func_name="add_peer_group_patcher",
                patcher_args={
                    "name": peergroup_uplink_mimic_v4,
                    "description": "BGP peering from SSW to FSW, IPv4 sessions",
                    "next_hop_self": "True",
                    "disable_ipv4_afi": "False",
                    "disable_ipv6_afi": "True",
                    "is_confed_peer": is_uplink_peer_confed,
                    "peer_tag": uplink_peer_tag,
                    "ingress_policy_name": route_map_uplink_ingress,
                    "egress_policy_name": route_map_uplink_egress + "_DRAIN",
                    "bgp_peer_timers_hold_time_seconds": "30",
                    "bgp_peer_timers_keep_alive_seconds": "10",
                    "bgp_peer_timers_out_delay_seconds": "7",
                    "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                    "max_routes": per_peer_max_route_limit,
                    "warning_only": "True",
                    "warning_limit": "0",
                    "link_bandwidth_bps": "auto",
                    "v4_over_v6_nexthop": "False",
                    "is_passive": "False",
                },
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_names=[
                    "bgpcpp",
                ],
                patcher_name=f"add_peer_group_patcher_{peergroup_downlink_mimic_v4}",
                py_func_name="add_peer_group_patcher",
                patcher_args={
                    "name": peergroup_downlink_mimic_v4,
                    "description": "BGP peering from RSW to FSW, IPv4 sessions",
                    "next_hop_self": "True",
                    "disable_ipv4_afi": "False",
                    "disable_ipv6_afi": "True",
                    "is_confed_peer": is_downlink_peer_confed,
                    "ingress_policy_name": route_map_downlink_ingress,
                    "egress_policy_name": route_map_downlink_egress,
                    "bgp_peer_timers_hold_time_seconds": "30",
                    "bgp_peer_timers_keep_alive_seconds": "10",
                    "bgp_peer_timers_out_delay_seconds": "7",
                    "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                    "peer_tag": downlink_peer_tag,
                    "max_routes": per_peer_max_route_limit,
                    "warning_only": "True",
                    "warning_limit": "0",
                    "link_bandwidth_bps": "auto",
                    "v4_over_v6_nexthop": "False",
                    "is_passive": "False",
                },
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_names=[
                    "bgpcpp_softdrain",
                ],
                patcher_name=f"add_peer_group_patcher_{peergroup_downlink_mimic_v4}",
                py_func_name="add_peer_group_patcher",
                patcher_args={
                    "name": peergroup_downlink_mimic_v4,
                    "description": "BGP peering from RSW to FSW, IPv4 sessions",
                    "next_hop_self": "True",
                    "disable_ipv4_afi": "False",
                    "disable_ipv6_afi": "True",
                    "is_confed_peer": is_downlink_peer_confed,
                    "ingress_policy_name": route_map_downlink_ingress,
                    "egress_policy_name": route_map_downlink_egress + "_DRAIN",
                    "bgp_peer_timers_hold_time_seconds": "30",
                    "bgp_peer_timers_keep_alive_seconds": "10",
                    "bgp_peer_timers_out_delay_seconds": "7",
                    "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                    "peer_tag": downlink_peer_tag,
                    "max_routes": per_peer_max_route_limit,
                    "warning_only": "True",
                    "warning_limit": "0",
                    "link_bandwidth_bps": "auto",
                    "v4_over_v6_nexthop": "False",
                    "is_passive": "False",
                },
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_names=[
                    "bgpcpp",
                    "bgpcpp_softdrain",
                ],
                patcher_name=f"add_bgp_policy_match_prefix_to_propagate_routes_{route_map_downlink_ingress}",
                py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
                patcher_args={
                    "matching_prefix": f"{ecmp_group_overflow_prefix}::/16",
                    "in_stmt_name": route_map_downlink_ingress,
                    "out_stmt_name": "RANDOM",
                },
            ),
            create_wait_for_bgp_convergence_task(hostnames=[device_name]),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_names=[
                    "bgpcpp",
                ],
                patcher_name=f"add_bgp_policy_match_prefix_to_propagate_routes_{route_map_uplink_ingress}",
                py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
                patcher_args={
                    "matching_prefix": f"{ecmp_group_overflow_prefix}::/16",
                    "in_stmt_name": route_map_uplink_ingress,
                    "out_stmt_name": "RANDOM",
                },
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_names=[
                    "bgpcpp_softdrain",
                ],
                patcher_name=f"add_bgp_policy_match_prefix_to_propagate_routes_{route_map_uplink_ingress}",
                py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
                patcher_args={
                    "matching_prefix": f"{ecmp_group_overflow_prefix}::/16",
                    "in_stmt_name": route_map_uplink_ingress + "_DRAIN",
                    "out_stmt_name": "RANDOM",
                },
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_names=[
                    "bgpcpp",
                    "bgpcpp_softdrain",
                ],
                patcher_name=f"add_bgp_policy_match_prefix_to_propagate_routes_{route_map_uplink_ingress}_uplink",
                py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
                patcher_args={
                    "matching_prefix": f"{v6_uplink_prefix}::/16",
                    "in_stmt_name": route_map_uplink_ingress,
                    "out_stmt_name": "RANDOM",
                },
            ),
            create_coop_apply_patchers_task(
                hostnames=[device_name],
                config_name="bgpcpp",
            ),
        ]
    )
    return tasks


def test_config_for_2_ixia_bgp_and_fboss_platform_hardening_in_conveyor(
    test_config_name,
    device_name,
    local_mac_address,
    ixia_downlink_interface,
    ixia_uplink_interface,
    peergroup_uplink_mimic_v6,
    peergroup_uplink_mimic_v4,
    peergroup_downlink_mimic_v6,
    peergroup_downlink_mimic_v4,
    peergroup_rogue_mimic_v6,
    route_map_uplink_ingress,
    route_map_uplink_egress,
    route_map_downlink_ingress,
    route_map_downlink_egress,
    route_map_rogue_ingress,
    route_map_rogue_egress,
    ixia_downlink_ic_parent_network_v6,
    ixia_uplink_ic_parent_network_v6,
    ixia_rogue_ic_parent_network_v6,
    ixia_downlink_ic_parent_network_v4,
    ixia_uplink_ic_parent_network_v4,
    ixia_rogue_ic_parent_network_v4,
    good_ndp_entry_network_v6,
    rogue_ndp_entry_network_v6,
    good_arp_entry_network_v4,
    rogue_arp_entry_network_v4,
    prefix_limit,
    per_peer_max_route_limit,
    downlink_peer_count,
    uplink_peer_count,
    rogue_peer_count,
    remote_downlink_as_4byte,
    remote_uplink_as_4byte,
    remote_rogue_as_4byte,
    is_uplink_peer_confed,
    is_downlink_peer_confed,
    is_rogue_peer_confed,
    ixia_downlink_prefix_count_v6,
    ixia_uplink_prefix_count_v6,
    ixia_rogue_prefix_count_v6,
    ixia_downlink_prefix_count_v4,
    ixia_uplink_prefix_count_v4,
    ixia_rogue_prefix_count_v4,
    ixia_downlink_communities,
    ixia_uplink_communities,
    uplink_peer_tag,
    downlink_peer_tag,
    ecmp_group_limit,
    good_ndp_entries_uplink,
    good_ndp_entries_downlink,  # should be >200 as it is also used to stress ECMP with static route
    rogue_ndp_entries,
    good_arp_entries,
    rogue_arp_entries,
    good_mac_entry_count,
    rogue_mac_entry_count,
    bgp_induced_ecmp_group_count,
    ixia_uplink_good_ndp_network,
    ixia_downlink_good_ndp_network,
    ndp_entry_limit=NDP_SOFT_LIMIT,
    arp_entry_limit=ARP_SOFT_LIMIT,
    mac_entry_limit=MAC_SOFT_LIMIT,
    bgpd_rss_limit=5,
    bgpd_cache_size_limit=4000,
    bgpd_restart_no_of_interations=1,
    wedge_agent_restart_no_of_interations=1,
    direct_ixia_connections=None,
    basset_pool=None,
    ecmp_group_overflow_prefix="7000",  # 7000:1:f::/64
    v6_uplink_prefix="6000",
    v6_session_flapping_prefix="6000",
    v6_prefix_flapping_prefix="6000",
    v4_uplink_prefix="102",
    v4_downlink_prefix="101",
    v6_downlink_prefix="3000",
    ecmp_member_limit=11500,
    ecmp_member_test_member_limit=11950,
    ecmp_member_test_group_limit=1300,
):
    """Build the BGP/FBOSS platform-hardening conveyor TestConfig for two IXIA chassis.

    Sister to ``test_config_for_bgp_and_fboss_platform_hardening_in_conveyor`` (single
    IXIA), this variant wires the DUT to two IXIA chassis: one downlink + one uplink +
    one rogue interface. Configures uplink/downlink/rogue BGP peer groups (V4 + V6 SAFI),
    ingress/egress route policies, ECMP overflow prefixes, NDP/ARP/MAC stress entries,
    and PTP server endpoints for time-accuracy verification under hardening churn.

    The function takes ~70 keyword arguments because it is the sole entry point for
    multi-IXIA conveyor TestConfigs across Wedge100S/Wedge400C; per-platform constants
    are passed in by callers.

    Args:
        test_config_name: Name to register in the TestConfig (CLI-callable).
        device_name: DUT hostname.
        local_mac_address: Local MAC for the DUT side of IXIA peering.
        ixia_downlink_interface / ixia_uplink_interface: DUT-facing IXIA ports
            (one per chassis).
        peergroup_*_mimic_v6 / _v4: BGP peer-group names per direction and AFI.
        route_map_*_ingress / _egress: Inbound/outbound policy per direction.
        ixia_*_ic_parent_network_v6 / _v4: IXIA-side parent IPs per interface.
        good_ndp_entry_network_v6 / rogue_ndp_entry_network_v6: NDP source nets.
        good_arp_entry_network_v4 / rogue_arp_entry_network_v4: ARP source nets.
        prefix_limit / per_peer_max_route_limit: Per-peer prefix/route caps.
        downlink_peer_count / uplink_peer_count / rogue_peer_count: Mimic peer counts.
        remote_*_as_4byte: Remote AS numbers (4-byte) per direction.
        is_*_peer_confed: Whether each peer is a confederation peer.
        ixia_*_prefix_count_v6 / _v4: Prefixes per peer.
        ixia_downlink_communities / ixia_uplink_communities: BGP community lists.
        uplink_peer_tag / downlink_peer_tag: Logical peer-group tags.
        ecmp_group_limit: ECMP-group cap on the DUT.
        good_ndp_entries_uplink / good_ndp_entries_downlink: Real NDP entry counts;
            downlink should be >200 (also doubles as ECMP stress).
        rogue_ndp_entries / good_arp_entries / rogue_arp_entries: Other entry counts.
        good_mac_entry_count / rogue_mac_entry_count: MAC entries to inject.
        bgp_induced_ecmp_group_count: BGP-induced ECMP group target.
        ixia_uplink_good_ndp_network / ixia_downlink_good_ndp_network: NDP source nets.
        playbooks: Optional explicit playbook list; default is hardening + longevity.
        ndp_entry_limit / arp_entry_limit / mac_entry_limit: L2/L3 table limits.
        bgpd_rss_limit / bgpd_cache_size_limit: BGPd resource limits.
        bgpd_restart_no_of_interations / wedge_agent_restart_no_of_interations:
            Restart iteration counts (sic — preserves historical typo).
        direct_ixia_connections: Optional explicit direct-IXIA connection mapping.
        basset_pool: Override basset pool selection.
        ecmp_group_overflow_prefix / v6_uplink_prefix / v4_session_flapping_prefix /
        v6_prefix_flapping_prefix / v4_uplink_prefix / v4_downlink_prefix /
        v6_downlink_prefix: Prefix string roots used to construct test prefixes.
        ecmp_member_limit / ecmp_member_test_member_limit / ecmp_member_test_group_limit:
            ECMP member sizing parameters for the dedicated ECMP test phase.

    Returns:
        TestConfig: The two-IXIA-chassis hardening conveyor TestConfig.
    """
    ptp_configs = [
        ixia_types.PTPConfig(
            server_endpoint=ixia_types.PTPEndpoint(
                name=f"{device_name}:{ixia_uplink_interface}",
                device_group_index=0,
            ),
            client_endpoints=[
                ixia_types.PTPEndpoint(
                    name=f"{device_name}:{ixia_downlink_interface}",
                    device_group_index=0,
                ),
            ],
            communication_mode=ixia_types.PTPCommunicationMode.UNICAST,
            step_mode=ixia_types.PTPStepMode.TWO_STEP,
        ),
    ]

    # TestConfig-level checks moved to playbook level
    _tc_prechecks = [
        create_ixia_packet_loss_check(
            thresholds=[
                hc_types.PacketLossThreshold(
                    names=[
                        "GOOD_BUT_LOSSY_NDP_TRAFFIC",
                        "LOSSY_ROGUE_NDP_TRAFFIC",
                    ],
                    expect_packet_loss=True,
                ),
                hc_types.PacketLossThreshold(
                    names=[
                        "V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
                        "V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
                    ],
                    str_value="0.1",
                    expect_packet_loss=False,
                ),
            ],
        ),
        create_prefix_limit_check(prefix_limit=prefix_limit),
        create_memory_utilization_check(
            threshold=10 * (1024**3), start_time_jq_var="test_case_start_time"
        ),
    ]
    _tc_postchecks = [
        create_device_core_dumps_check(),
        create_ixia_packet_loss_check(
            thresholds=[
                hc_types.PacketLossThreshold(
                    names=[
                        "GOOD_BUT_LOSSY_NDP_TRAFFIC",
                        "LOSSY_ROGUE_NDP_TRAFFIC",
                    ],
                    expect_packet_loss=True,
                ),
                hc_types.PacketLossThreshold(
                    names=[
                        "V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
                        "V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
                    ],
                    # todo (change this)
                    expect_packet_loss=False,
                ),
            ],
        ),
        create_prefix_limit_check(prefix_limit=prefix_limit),
        create_unclean_exit_check(),
        create_cpu_utilization_check(
            threshold=400.0, start_time_jq_var="test_case_start_time"
        ),
        create_service_restart_check(),
    ]
    _tc_snapshot_checks = [
        create_core_dumps_snapshot_check(),
    ]

    return TestConfig(
        name=test_config_name,
        ixia_protocol_verification_timeout=1200,  # todo remove this (should be 300)
        skip_ixia_protocol_verification=True,
        basset_pool=basset_pool,
        ptp_configs=ptp_configs,
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
            # Task(
            #     task_name="coop_register_patcher",
            #     params=Params(
            #         json_params=json.dumps(
            #             {
            #                 "hostname": device_name,
            #                 "config_names": ["bgpcpp", "bgpcpp_softdrain", ],
            #                 "patcher_name": "a_remove_bgp_peers",
            #                 "py_func_name": "remove_bgp_peers",
            #                 "patcher_args": json.dumps({"delete_all": "True"}),
            #             }
            #         ),
            #     ),
            # ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_names=[
                    "bgpcpp",
                    "bgpcpp_softdrain",
                ],
                patcher_name="configure_bgp_switch_limit",
                py_func_name="configure_bgp_switch_limit",
                patcher_args={
                    "prefix_limit": prefix_limit,
                },
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="agent",
                patcher_name="enable_port_all_ixia_ports",
                py_func_name="change_port_admin_state",
                patcher_args={
                    f"{ixia_uplink_interface}": "enable",
                    f"{ixia_downlink_interface}": "enable",
                },
            ),
        ]
        + get_bgp_peer_config_tasks(
            device_name=device_name,
            peergroup_downlink_mimic_v6=peergroup_downlink_mimic_v6,
            peergroup_uplink_mimic_v6=peergroup_uplink_mimic_v6,
            peergroup_uplink_mimic_v4=peergroup_uplink_mimic_v4,
            peergroup_downlink_mimic_v4=peergroup_downlink_mimic_v4,
            is_downlink_peer_confed=is_downlink_peer_confed,
            is_uplink_peer_confed=is_uplink_peer_confed,
            per_peer_max_route_limit=per_peer_max_route_limit,
            uplink_peer_tag=uplink_peer_tag,
            downlink_peer_tag=downlink_peer_tag,
            route_map_uplink_ingress=route_map_uplink_ingress,
            route_map_uplink_egress=route_map_uplink_egress,
            route_map_downlink_ingress=route_map_downlink_ingress,
            route_map_downlink_egress=route_map_downlink_egress,
            ecmp_group_overflow_prefix=ecmp_group_overflow_prefix,
            v6_uplink_prefix=v6_uplink_prefix,
        )
        + [
            # Task(
            #     task_name="add_stress_static_routes",
            #     params=Params(
            #         json_params=json.dumps(
            #             {
            #                 "hostname": device_name,
            #                 "nh_prefix_1": f"{ixia_uplink_good_ndp_network}::a000/80",
            #                 "nh_prefix_2": f"{ixia_downlink_good_ndp_network}::a000/80",
            #                 "lb_prefix_agg": "6000:ab::/32",
            #                 "nh_common_last_hextet": "a000",
            #                 "route_count": ecmp_group_limit,
            #             }
            #         ),
            #     ),
            # ),
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
                            {
                                "starting_ip": f"{ixia_downlink_ic_parent_network_v4}.0",
                                "increment_ip": "0.0.0.2",
                                "prefix_length": 31,
                                "description": "Downlink IPv4 Peers",
                                "peer_group_name": peergroup_downlink_mimic_v4,
                                "num_sessions": downlink_peer_count,
                                "remote_as_4_byte": remote_downlink_as_4byte,
                                "remote_as_4_byte_step": 1,
                                "gateway_starting_ip": f"{ixia_downlink_ic_parent_network_v4}.1",
                                "gateway_increment_ip": "0.0.0.2",
                            },
                            {
                                "starting_ip": f"{rogue_arp_entry_network_v4}.0.1",
                                "increment_ip": "0.0.0.1",
                                "prefix_length": 16,
                                "description": "Downlink IPv4 Address Creation for ROGUE ARP",
                                "peer_group_name": peergroup_downlink_mimic_v4,
                                "num_sessions": 1,
                                "remote_as_4_byte": remote_downlink_as_4byte,
                                "gateway_starting_ip": f"{rogue_arp_entry_network_v4}.0.1",
                                "gateway_increment_ip": "0.0.0.1",
                                "config_only_interface_ip": True,
                            },
                        ]
                        + [
                            {
                                "starting_ip": f"{ixia_rogue_ic_parent_network_v6}::f00",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "Rogue route flap IPv6 Peers",
                                "peer_group_name": peergroup_rogue_mimic_v6,
                                "num_sessions": rogue_peer_count,
                                "remote_as_4_byte": remote_rogue_as_4byte,
                                "remote_as_4_byte_step": 1,
                                "gateway_starting_ip": f"{ixia_rogue_ic_parent_network_v6}::f01",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            {
                                "starting_ip": f"{ixia_rogue_ic_parent_network_v6}::e00",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "Rogue session flap IPv6 Peers",
                                "peer_group_name": peergroup_rogue_mimic_v6,
                                "num_sessions": rogue_peer_count,
                                "remote_as_4_byte": remote_rogue_as_4byte,
                                "remote_as_4_byte_step": 1,
                                "gateway_starting_ip": f"{ixia_rogue_ic_parent_network_v6}::e01",
                                "gateway_increment_ip": "0:0:0:0::2",
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
                            {
                                "starting_ip": f"{ixia_uplink_ic_parent_network_v6}::400",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "Uplink IPv6 Peers - for BGP Induced ECMP - 1 ",
                                "peer_group_name": peergroup_uplink_mimic_v6,
                                "num_sessions": bgp_induced_ecmp_group_count,
                                "remote_as_4_byte": remote_uplink_as_4byte,
                                "remote_as_4_byte_step": 0,
                                "gateway_starting_ip": f"{ixia_uplink_ic_parent_network_v6}::401",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            {
                                "starting_ip": f"{ixia_uplink_ic_parent_network_v6}::500",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "Uplink IPv6 Peers - for BGP Induced ECMP - 2",
                                "peer_group_name": peergroup_uplink_mimic_v6,
                                "num_sessions": bgp_induced_ecmp_group_count,
                                "remote_as_4_byte": remote_uplink_as_4byte,
                                "remote_as_4_byte_step": 0,
                                "gateway_starting_ip": f"{ixia_uplink_ic_parent_network_v6}::501",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            {
                                "starting_ip": f"{ixia_uplink_ic_parent_network_v4}.0",
                                "increment_ip": "0.0.0.2",
                                "prefix_length": 31,
                                "description": "Uplink IPv4 Peers",
                                "peer_group_name": peergroup_uplink_mimic_v4,
                                "num_sessions": uplink_peer_count,
                                "remote_as_4_byte": remote_uplink_as_4byte,
                                "remote_as_4_byte_step": 0,
                                "gateway_starting_ip": f"{ixia_uplink_ic_parent_network_v4}.1",
                                "gateway_increment_ip": "0.0.0.2",
                            },
                            {
                                "starting_ip": f"{good_arp_entry_network_v4}.0.1",
                                "increment_ip": "0.0.0.1",
                                "prefix_length": 16,
                                "description": "Downlink IPv4 Address Creation for GOOD ARP",
                                "peer_group_name": peergroup_uplink_mimic_v4,
                                "num_sessions": 1,
                                "remote_as_4_byte": remote_uplink_as_4byte,
                                "gateway_starting_ip": f"{good_arp_entry_network_v4}.0.1",
                                "gateway_increment_ip": "0.0.0.1",
                                "config_only_interface_ip": True,
                            },
                        ]
                    }
                ),
            ),
            create_coop_apply_patchers_v2_task(
                hostnames=[device_name],
                apply_patcher_method=taac_types.ApplyPatcherMethod.AGENT_WARMBOOT.value,
            ),
        ],
        teardown_tasks=[
            create_coop_unregister_patchers_task(device_name),
            create_run_commands_on_shell_task(
                hostname=device_name,
                cmds=["pkill memory_pressure"],
            ),
        ],
        # periodic_tasks=[
        #     PeriodicTask(
        #         name="invoke_concurrent_thrift_requests",
        #         task=Task(
        #             task_name="invoke_concurrent_thrift_requests",
        #             params=Params(
        #                 json_params=json.dumps(
        #                     {
        #                         "hostname": device_name,
        #                         "driver_apis_to_args": {
        #                             "async_do_rapid_interface_flaps": {
        #                                 "interface_names": ("eth2/1/1",),
        #                                 "interval_to_link_up": 5,
        #                                 "total_flaps": 100,
        #                             },
        #                             "get_bgp_table_length": {},
        #                             "get_bgp_sessions_count": {},
        #                         },
        #                         "num_concurrent_requests_by_api": {
        #                             "get_bgp_table_length": 1000,
        #                             "get_bgp_sessions_count": 1000,
        #                         },
        #                     }
        #                 ),
        #             ),
        #         ),
        #     ),
        # ],
        basic_port_configs=[
            taac_types.BasicPortConfig(
                endpoint=f"{device_name}:{ixia_downlink_interface}",
                device_group_configs=[
                    # downlink Ipv6
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
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
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=ixia_downlink_prefix_count_v6,
                                        prefix_length=64,
                                        starting_prefixes=f"{v6_downlink_prefix}:1::",
                                        prefix_step="0:0:0:0::0",
                                        bgp_communities=ixia_downlink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    ),
                                ),
                            ],
                        ),
                    ),
                    # Downlink IPv4
                    taac_types.DeviceGroupConfig(
                        device_group_index=1,
                        multiplier=downlink_peer_count,
                        v4_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_downlink_ic_parent_network_v4}.1",
                            increment_ip="0.0.0.2",
                            gateway_starting_ip=f"{ixia_downlink_ic_parent_network_v4}.0",
                            gateway_increment_ip="0.0.0.2",
                            mask=31,
                        ),
                        v4_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_downlink_as_4byte,
                            local_as_increment=1,
                            enable_4_byte_local_as=True,
                            is_confed=is_downlink_peer_confed == "True",
                            bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v4_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=ixia_downlink_prefix_count_v4,
                                        prefix_length=24,
                                        starting_prefixes=f"{v4_downlink_prefix}.1.0.0",
                                        prefix_step="0.0.0.0",
                                        bgp_communities=ixia_downlink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                    ),
                                ),
                            ],
                        ),
                    ),
                    # NDP stessor downlink
                    taac_types.DeviceGroupConfig(
                        device_group_index=2,
                        multiplier=good_ndp_entries_downlink,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_downlink_good_ndp_network}::a000",
                            increment_ip="::1",
                            gateway_starting_ip=f"{ixia_downlink_good_ndp_network}::1",
                            mask=80,
                        ),
                    ),
                    # Arp stress downlink
                    taac_types.DeviceGroupConfig(
                        device_group_index=3,
                        multiplier=1,
                        v4_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{rogue_arp_entry_network_v4}.0.100",
                            increment_ip="0.0.0.1",
                            gateway_starting_ip=f"{rogue_arp_entry_network_v4}.0.1",
                            mask=16,
                        ),
                    ),
                    taac_types.DeviceGroupConfig(
                        device_group_index=4,
                        multiplier=rogue_peer_count,
                        tag_name="ROGUE_PREFIX_FLAP",
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_rogue_ic_parent_network_v6}::f01",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_rogue_ic_parent_network_v6}::f00",
                            gateway_increment_ip="0:0:0:0::2",
                            mask=127,
                        ),
                        # Prefix flaps
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_rogue_as_4byte,
                            local_as_increment=1,
                            enable_4_byte_local_as=True,
                            is_confed=is_rogue_peer_confed == "True",
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=ixia_rogue_prefix_count_v6,
                                        prefix_length=64,
                                        starting_prefixes=f"{v6_prefix_flapping_prefix}:f::",
                                        prefix_step="0:0:0:0::0",
                                        bgp_communities=ixia_downlink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                        prefix_flap_config=ixia_types.BgpFlapConfig(
                                            uptime_in_sec=15, downtime_in_sec=15
                                        ),
                                    ),
                                ),
                            ],
                        ),
                    ),
                    taac_types.DeviceGroupConfig(
                        device_group_index=5,
                        multiplier=rogue_peer_count,
                        tag_name="ROGUE_SESSION_FLAP",
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_rogue_ic_parent_network_v6}::e01",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_rogue_ic_parent_network_v6}::e00",
                            gateway_increment_ip="0:0:0:0::2",
                            mask=127,
                        ),
                        # Prefix flaps
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_rogue_as_4byte,
                            local_as_increment=1,
                            enable_4_byte_local_as=True,
                            is_confed=is_rogue_peer_confed == "True",
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            peer_flap_config=ixia_types.BgpFlapConfig(
                                uptime_in_sec=15, downtime_in_sec=15
                            ),
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=ixia_rogue_prefix_count_v6,
                                        prefix_length=64,
                                        starting_prefixes=f"{v6_prefix_flapping_prefix}:e::",
                                        prefix_step="0:0:0:0::0",
                                        bgp_communities=ixia_downlink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    ),
                                ),
                            ],
                        ),
                    ),
                ],
            ),
            taac_types.BasicPortConfig(
                endpoint=f"{device_name}:{ixia_uplink_interface}",
                device_group_configs=[
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
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
                            is_confed=is_uplink_peer_confed == "True",
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=ixia_uplink_prefix_count_v6,
                                        prefix_length=64,
                                        starting_prefixes=f"{v6_uplink_prefix}:1::",
                                        prefix_step="0:0:0:0::0",
                                        bgp_communities=ixia_uplink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    ),
                                ),
                            ],
                        ),
                    ),
                    taac_types.DeviceGroupConfig(
                        device_group_index=1,
                        multiplier=uplink_peer_count,
                        v4_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_uplink_ic_parent_network_v4}.1",
                            increment_ip="0.0.0.2",
                            gateway_starting_ip=f"{ixia_uplink_ic_parent_network_v4}.0",
                            gateway_increment_ip="0.0.0.2",
                            mask=31,
                        ),
                        v4_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_uplink_as_4byte,
                            local_as_increment=0,
                            enable_4_byte_local_as=True,
                            is_confed=is_uplink_peer_confed == "True",
                            bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v4_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=ixia_uplink_prefix_count_v4,
                                        prefix_length=24,
                                        starting_prefixes=f"{v4_uplink_prefix}.1.0.0",
                                        prefix_step="0.0.0.0",
                                        bgp_communities=ixia_uplink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                    ),
                                ),
                            ],
                        ),
                    ),
                    taac_types.DeviceGroupConfig(
                        device_group_index=2,
                        multiplier=good_ndp_entries_uplink,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_uplink_good_ndp_network}::a000",
                            increment_ip="::1",
                            gateway_starting_ip=f"{ixia_uplink_good_ndp_network}::1",
                            mask=80,
                        ),
                    ),
                    taac_types.DeviceGroupConfig(
                        device_group_index=3,
                        multiplier=good_arp_entries,
                        v4_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{good_arp_entry_network_v4}.0.100",
                            increment_ip="0.0.0.1",
                            gateway_starting_ip=f"{good_arp_entry_network_v4}.0.1",
                            mask=16,
                        ),
                    ),
                    taac_types.DeviceGroupConfig(
                        device_group_index=4,
                        enable=True,
                        multiplier=bgp_induced_ecmp_group_count,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_uplink_ic_parent_network_v6}::401",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_uplink_ic_parent_network_v6}::400",
                            gateway_increment_ip="0:0:0:0::2",
                            mask=80,
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_uplink_as_4byte,
                            local_as_increment=0,
                            enable_4_byte_local_as=True,
                            is_confed=is_uplink_peer_confed == "True",
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=1,
                                        prefix_length=64,
                                        starting_prefixes=f"{ecmp_group_overflow_prefix}:1:f::",
                                        prefix_step="0:0:0:1::0",
                                        bgp_communities=ixia_uplink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    ),
                                ),
                            ],
                        ),
                    ),
                    taac_types.DeviceGroupConfig(
                        device_group_index=5,
                        enable=False,
                        multiplier=bgp_induced_ecmp_group_count,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_uplink_ic_parent_network_v6}::501",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_uplink_ic_parent_network_v6}::500",
                            gateway_increment_ip="0:0:0:0::2",
                            mask=80,
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_uplink_as_4byte,
                            local_as_increment=0,
                            enable_4_byte_local_as=True,
                            is_confed=is_uplink_peer_confed == "True",
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=1,
                                        prefix_length=64,
                                        starting_prefixes=f"{ecmp_group_overflow_prefix}:1:f::",
                                        prefix_step="0:0:0:1::0",
                                        bgp_communities=ixia_uplink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    ),
                                ),
                            ],
                        ),
                    ),
                ],
            ),
        ],
        traffic_items_to_start=["(?!HIGH_QUEUE_BGP_CP_TRAFFIC)"],
        basic_traffic_item_configs=[
            taac_types.BasicTrafficItemConfig(
                name=f"{device_name.upper()}_V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
                bidirectional=True,
                merge_destinations=True,
                line_rate=10,
                src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        network_group_index=0,
                        device_group_index=0,
                    )
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        network_group_index=0,
                        device_group_index=0,
                    )
                ],
                traffic_type=ixia_types.TrafficType.IPV6,
                tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
            ),
            taac_types.BasicTrafficItemConfig(
                name=f"{device_name.upper()}_V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
                bidirectional=True,
                merge_destinations=True,
                line_rate=10,
                src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        network_group_index=0,
                        device_group_index=1,
                    )
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        network_group_index=0,
                        device_group_index=1,
                    )
                ],
                traffic_type=ixia_types.TrafficType.IPV4,
                tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
            ),
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                    )
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                    ),
                ],
                name="HIGH_QUEUE_BGP_CP_TRAFFIC",
                line_rate=70,
                traffic_type=ixia_types.TrafficType.RAW,
                tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
                bidirectional=False,
                packet_headers=BGP_CP_TRAFFIC_PACKET_HEADERS,
            ),
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                    ),
                ],
                name="GOOD_BUT_LOSSY_NDP_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
                # traffic_type=ixia_types.TrafficType.RAW,
                traffic_type=ixia_types.TrafficType.RAW,
                allow_self_destined=True,
                bidirectional=False,
                packet_headers=[
                    taac_types.PacketHeader(
                        query=ixia_types.Query(
                            regex="^ethernet$",
                            query_type=ixia_types.QueryType.STACK_TYPE_ID,
                        ),
                        fields=[
                            taac_types.Field(
                                query=ixia_types.Query(regex="Destination MAC Address"),
                                attrs_json=json.dumps(
                                    {
                                        "ValueType": "increment",
                                        "StartValue": BROADCAST_DST_MAC_ADDRESS,
                                        "StepValue": "00:00:00:00:00:00",
                                        "CountValue": 1,
                                    }
                                ),
                            ),
                            taac_types.Field(
                                query=ixia_types.Query(regex="Source MAC Address"),
                                attrs_json=json.dumps(
                                    {
                                        "ValueType": "increment",
                                        "StartValue": DEFAULT_SRC_MAC_ADDRESS,
                                        "StepValue": "00:00:00:00:00:01",
                                        "CountValue": good_mac_entry_count,
                                    }
                                ),
                            ),
                        ],
                    ),
                ],
            ),
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                    ),
                ],
                name="LOSSY_ROGUE_NDP_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
                # ip_address_family=ixia_types.IpAddrFamily.RAW,
                traffic_type=ixia_types.TrafficType.RAW,
                allow_self_destined=True,
                bidirectional=False,
                packet_headers=[
                    taac_types.PacketHeader(
                        query=ixia_types.Query(
                            regex="^ethernet$",
                            query_type=ixia_types.QueryType.STACK_TYPE_ID,
                        ),
                        fields=[
                            taac_types.Field(
                                query=ixia_types.Query(regex="Destination MAC Address"),
                                attrs_json=json.dumps(
                                    {
                                        "ValueType": "increment",
                                        "StartValue": BROADCAST_DST_MAC_ADDRESS,
                                        "StepValue": "00:00:00:00:00:00",
                                        "CountValue": 1,
                                    }
                                ),
                            ),
                            taac_types.Field(
                                query=ixia_types.Query(regex="Source MAC Address"),
                                attrs_json=json.dumps(
                                    {
                                        "ValueType": "increment",
                                        "StartValue": ROGUE_SRC_MAC_ADDRESS,
                                        "StepValue": "00:00:00:00:00:01",
                                        "CountValue": 1,
                                    }
                                ),
                            ),
                        ],
                    ),
                ],
            ),
        ],
        # Deprecated - define at playbook level
        # snapshot_checks=[
        #     # SnapshotHealthCheck(name=hc_types.CheckName.BGP_PEER_ROUTE_CHECK),
        #     create_core_dumps_snapshot_check(),
        # ],
        # Deprecated - define at playbook level
        # postchecks=[
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.DEVICE_CORE_DUMPS_CHECK,
        #         ...
        #     ),
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
        #         ...
        #     ),
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.PREFIX_LIMIT_CHECK,
        #         ...
        #     ),
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.UNCLEAN_EXIT_CHECK,
        #         ...
        #     ),
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.CPU_UTILIZATION_CHECK,
        #         ...
        #     ),
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.SERVICE_RESTART_CHECK,
        #         ...
        #     ),
        # ],
        # Deprecated - define at playbook level
        # prechecks=[
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
        #         ...
        #     ),
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.PREFIX_LIMIT_CHECK,
        #         ...
        #     ),
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.MEMORY_UTILIZATION_CHECK,
        #         ...
        #     ),
        # ],
        playbooks=[
            # Playbook(
            #     name="test_cgroup_system_slice_oom_kill_policy",
            #     postchecks=[
            #         PointInTimeHealthCheck(
            #             name=hc_types.CheckName.OOMD_KILL_CHECK,
            #             check_params=Params(
            #                 jq_params={
            #                     "start_time": ".test_case_start_time",
            #                 },
            #                 json_params=json.dumps(
            #                     {
            #                         "expected_oom_kills": {
            #                             "system.slice": ["memory-pressure"]
            #                         }
            #                     }
            #                 ),
            #             ),
            #         )
            #     ],
            #     stages=[
            #         Stage(
            #             steps=[
            #                 Step(
            #                     name=StepName.ALLOCATE_CGROUP_SLICE_MEMORY_STEP,
            #                     step_params=Params(
            #                         json_params=json.dumps(
            #                             {
            #                                 "total_memory_pct_decimal": 0.25,
            #                                 "slice_name": "system",
            #                                 "duration": 180,
            #                                 "minimum_memory_allocation": 1048
            #                                 * 10,  # 10gb
            #                                 "oom_score_adj": 1000,
            #                             }
            #                         ),
            #                     ),
            #                 ),
            #                 Step(
            #                     name=StepName.LONGEVITY_STEP,
            #                     step_params=Params(json_params='{"duration": 300}'),
            #                 ),
            #             ]
            #         )
            #     ],
            # ),
            build_2_ixia_hardening_playbook(
                name="test_hardening_of_ndp_overload_entries",
                prechecks=_tc_prechecks,
                snapshot_checks=_tc_snapshot_checks,
                cleanup_steps=[
                    create_ixia_api_step(
                        api_name="configure_ipv6_entries",
                        args_dict={
                            "device_group_regex": f".*{ixia_downlink_interface.upper()}.*",
                            "prefix_count": good_ndp_entries_downlink,
                            "toggle_all_ipv6_ipv4_only_protocol": True,
                        },
                    ),
                ],
                stages=[
                    create_steps_stage(
                        steps=[
                            # Ensuring the protocol is up
                            create_ixia_api_step(
                                api_name="configure_ipv6_entries",
                                args_dict={
                                    "device_group_regex": f".*{ixia_downlink_interface.upper()}.*",
                                    "prefix_count": good_ndp_entries_downlink,
                                    "toggle_all_ipv6_ipv4_only_protocol": True,
                                },
                            ),
                            create_ixia_api_step(
                                api_name="configure_ipv6_entries",
                                args_dict={
                                    "device_group_regex": f".*{ixia_uplink_interface.upper()}.*",
                                    "prefix_count": good_ndp_entries_uplink,
                                    "toggle_all_ipv6_ipv4_only_protocol": True,
                                },
                            ),
                            # Now overshoot the rogue entries
                            create_ixia_api_step(
                                api_name="configure_ipv6_entries",
                                args_dict={
                                    "device_group_regex": f".*{ixia_downlink_interface.upper()}.*",
                                    "prefix_count": rogue_ndp_entries,
                                    "toggle_all_ipv6_ipv4_only_protocol": True,
                                },
                            ),
                            create_longevity_step(duration=600),
                        ]
                    )
                ],
                postchecks=[
                    create_l2_entry_threshold_check(
                        ndp_entry_upper_lower_threshold=[
                            ndp_entry_limit,
                            good_ndp_entries_uplink + good_ndp_entries_downlink,
                        ],
                    ),
                ]
                + _tc_postchecks,
            ),
            build_2_ixia_hardening_playbook(
                name="test_hardening_of_arp_overload_entries",
                prechecks=_tc_prechecks,
                snapshot_checks=_tc_snapshot_checks,
                cleanup_steps=[
                    create_ixia_api_step(
                        api_name="configure_ipv4_entries",
                        args_dict={
                            "device_group_regex": f".*{ixia_downlink_interface.upper()}.*",
                            "prefix_count": 1,
                            "toggle_all_ipv6_ipv4_only_protocol": True,
                        },
                    ),
                ],
                stages=[
                    create_steps_stage(
                        steps=[
                            create_ixia_api_step(
                                api_name="configure_ipv4_entries",
                                args_dict={
                                    "device_group_regex": f".*{ixia_downlink_interface.upper()}.*",
                                    "prefix_count": 1,
                                    "toggle_all_ipv6_ipv4_only_protocol": True,
                                },
                            ),
                            create_ixia_api_step(
                                api_name="configure_ipv4_entries",
                                args_dict={
                                    "device_group_regex": f".*{ixia_uplink_interface.upper()}.*",
                                    "prefix_count": good_arp_entries,
                                    "toggle_all_ipv6_ipv4_only_protocol": True,
                                },
                            ),
                            # Now overshoot the rogue entries
                            create_ixia_api_step(
                                api_name="configure_ipv4_entries",
                                args_dict={
                                    "device_group_regex": f".*{ixia_downlink_interface.upper()}.*",
                                    "prefix_count": rogue_arp_entries,
                                    "toggle_all_ipv6_ipv4_only_protocol": True,
                                },
                            ),
                            create_longevity_step(duration=600),
                        ]
                    )
                ],
                postchecks=[
                    create_l2_entry_threshold_check(
                        arp_entry_upper_lower_threshold=[
                            arp_entry_limit,
                            good_arp_entries,
                        ],
                    ),
                ]
                + _tc_postchecks,
            ),
            build_2_ixia_hardening_playbook(
                name="test_hardening_of_mac_overload_entries",
                # Order is the following:
                # 1. stages get executed (pre-checks from test-config)
                # 2. post-checks will be from test-config by default OR overridden by adding post-checks at playbook (not step)
                #
                prechecks=_tc_prechecks,
                snapshot_checks=_tc_snapshot_checks,
                cleanup_steps=[
                    create_ixia_api_step(
                        api_name="configure_traffic_item_src_mac_entry_count",
                        args_dict={
                            "traffic_item_name": "LOSSY_ROGUE_NDP_TRAFFIC",
                            "src_mac_entry_count": 1,
                        },
                    ),
                ],
                stages=[
                    create_steps_stage(
                        steps=[
                            create_ixia_api_step(
                                api_name="configure_traffic_item_src_mac_entry_count",
                                args_dict={
                                    "traffic_item_name": "LOSSY_ROGUE_NDP_TRAFFIC",
                                    "src_mac_entry_count": rogue_mac_entry_count,
                                },
                            ),
                            create_longevity_step(duration=100),
                        ],
                    )
                ],
                postchecks=[
                    create_l2_entry_threshold_check(
                        mac_entry_upper_lower_threshold=[
                            mac_entry_limit,
                            good_mac_entry_count
                            + good_ndp_entries_uplink
                            + good_ndp_entries_downlink
                            + good_arp_entries,
                        ],
                    ),
                ]
                + _tc_postchecks,
            ),
            build_2_ixia_hardening_playbook(
                name="test_agent_warmboot",
                prechecks=_tc_prechecks,
                stages=[
                    create_steps_stage(
                        iteration=wedge_agent_restart_no_of_interations,
                        steps=[
                            create_service_interruption_step(
                                service=taac_types.Service.AGENT,
                            ),
                            create_service_convergence_step(
                                services=[Service.AGENT, Service.BGP],
                            ),
                        ],
                    ),
                ],
                postchecks=[
                    create_bgp_convergence_check(),
                    create_bgp_rib_fib_consistency_check(
                        extra_json_params={
                            "parent_prefixes_to_ignore": ["103.0.0.0/8", "6000:1::/32"]
                        }
                    ),
                ]
                + _tc_postchecks,
            ),
            build_2_ixia_hardening_playbook(
                name="test_bgpd_restart",
                prechecks=_tc_prechecks,
                stages=[
                    create_steps_stage(
                        iteration=bgpd_restart_no_of_interations,
                        steps=[
                            create_service_interruption_step(
                                service=taac_types.Service.BGP,
                            ),
                            create_service_convergence_step(),
                        ],
                    ),
                ],
                postchecks=[
                    create_bgp_convergence_check(),
                    create_bgp_rib_fib_consistency_check(
                        extra_json_params={
                            "parent_prefixes_to_ignore": ["103.0.0.0/8", "6000:1::/32"]
                        }
                    ),
                ]
                + _tc_postchecks,
            ),
            build_2_ixia_hardening_playbook(
                name="test_5_min_longevity",
                prechecks=_tc_prechecks,
                postchecks=_tc_postchecks,
                snapshot_checks=_tc_snapshot_checks,
                stages=[
                    create_steps_stage(
                        steps=[create_longevity_step(duration=300)],
                    )
                ],
            ),
            build_2_ixia_hardening_playbook(
                name="test_bgp_session_flap_half_of_uplink_and_downlink_peers",
                iteration=5,
                prechecks=_tc_prechecks,
                snapshot_checks=_tc_snapshot_checks,
                postchecks=[
                    create_ixia_packet_loss_check(
                        thresholds=[
                            hc_types.PacketLossThreshold(
                                names=[
                                    "GOOD_BUT_LOSSY_NDP_TRAFFIC",
                                    "LOSSY_ROGUE_NDP_TRAFFIC",
                                ],
                                expect_packet_loss=True,
                            ),
                            hc_types.PacketLossThreshold(
                                names=[
                                    "V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
                                    "V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
                                ],
                                expect_packet_loss=False,
                            ),
                        ],
                    ),
                ]
                + _tc_postchecks,
                cleanup_steps=[
                    create_ixia_api_step(
                        api_name="start_bgp_peers",
                        args_dict={
                            "start": True,
                            "regex": f".*{ixia_uplink_interface.upper()}.*",
                            "session_end_idx": int(uplink_peer_count / 2),
                        },
                    ),
                ],
                stages=[
                    create_steps_stage(
                        steps=[
                            create_ixia_api_step(
                                api_name="start_bgp_peers",
                                args_dict={
                                    "start": False,
                                    "regex": f".*{ixia_uplink_interface.upper()}.*",
                                    "session_end_idx": int(uplink_peer_count / 2),
                                },
                            ),
                            create_longevity_step(duration=100),
                        ]
                    ),
                ],
            ),
            build_2_ixia_hardening_playbook(
                name="test_bgp_route_flap_for_half_of_uplink_and_downlink_peers",
                iteration=5,
                prechecks=_tc_prechecks,
                snapshot_checks=_tc_snapshot_checks,
                postchecks=[
                    create_ixia_packet_loss_check(
                        thresholds=[
                            hc_types.PacketLossThreshold(
                                names=[
                                    "GOOD_BUT_LOSSY_NDP_TRAFFIC",
                                    "LOSSY_ROGUE_NDP_TRAFFIC",
                                ],
                                expect_packet_loss=True,
                            ),
                            hc_types.PacketLossThreshold(
                                names=[
                                    "V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
                                    "V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
                                ],
                                expect_packet_loss=False,
                            ),
                        ],
                    ),
                ]
                + _tc_postchecks,
                cleanup_steps=[
                    create_ixia_api_step(
                        api_name="configure_bgp_prefixes",
                        args_dict={
                            "enable": True,
                            "network_group_regex": f".*{ixia_uplink_interface.upper()}.*",
                            "session_end_idx": int(uplink_peer_count / 2),
                        },
                    ),
                ],
                stages=[
                    create_steps_stage(
                        steps=[
                            create_ixia_api_step(
                                api_name="configure_bgp_prefixes",
                                args_dict={
                                    "enable": False,
                                    "network_group_regex": f".*{ixia_uplink_interface.upper()}.*",
                                    "session_end_idx": int(uplink_peer_count / 2),
                                },
                            ),
                            create_longevity_step(duration=100),
                        ]
                    ),
                ],
            ),
            build_2_ixia_hardening_playbook(
                name="test_bgp_malformed_packet_test",
                iteration=1,
                prechecks=_tc_prechecks,
                snapshot_checks=_tc_snapshot_checks,
                postchecks=[
                    create_ixia_packet_loss_check(
                        clear_traffic_stats=True,
                        thresholds=[
                            hc_types.PacketLossThreshold(
                                names=[
                                    "GOOD_BUT_LOSSY_NDP_TRAFFIC",
                                    "LOSSY_ROGUE_NDP_TRAFFIC",
                                ],
                                expect_packet_loss=True,
                            ),
                            hc_types.PacketLossThreshold(
                                names=[
                                    "V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
                                    "V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
                                ],
                                expect_packet_loss=False,
                            ),
                        ],
                    ),
                ]
                + _tc_postchecks,
                cleanup_steps=[],
                stages=[
                    create_steps_stage(
                        steps=[
                            create_ixia_api_step(
                                api_name="bounce_bgp_next_hop_attribute",
                                args_dict={
                                    "enable": False,
                                    "network_group_regex": f".*{ixia_uplink_interface.upper()}.*",
                                },
                            ),
                            create_ixia_api_step(
                                api_name="bounce_bgp_next_hop_attribute",
                                args_dict={
                                    "enable": False,
                                    "network_group_regex": f".*{ixia_downlink_interface.upper()}.*",
                                },
                            ),
                            create_longevity_step(duration=120),
                            create_ixia_api_step(
                                api_name="bounce_bgp_next_hop_attribute",
                                args_dict={
                                    "enable": True,
                                    "network_group_regex": f".*{ixia_uplink_interface.upper()}.*",
                                },
                            ),
                            create_ixia_api_step(
                                api_name="bounce_bgp_next_hop_attribute",
                                args_dict={
                                    "enable": True,
                                    "network_group_regex": f".*{ixia_downlink_interface.upper()}.*",
                                },
                            ),
                            create_longevity_step(duration=200),
                        ]
                    ),
                ],
            ),
            build_2_ixia_hardening_playbook(
                iteration=1,
                name="test_ecmp_member_overload_limit",
                prechecks=_tc_prechecks,
                postchecks=_tc_postchecks,
                snapshot_checks=_tc_snapshot_checks,
                cleanup_steps=[
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "enable": False,
                            "device_group_name_regex": "D5",
                        },
                    ),
                    create_ecmp_member_static_route_step(
                        delete_patcher_and_exit_step=True,
                    ),
                    create_service_interruption_step(
                        service=taac_types.Service.AGENT,
                    ),
                    create_service_convergence_step(
                        services=[Service.AGENT, Service.BGP],
                    ),
                    create_ecmp_member_static_route_step(
                        max_ecmp_group=ecmp_group_limit,
                        description=None,
                    ),
                ],
                stages=[
                    create_steps_stage(
                        steps=[
                            create_ecmp_member_static_route_step(
                                delete_patcher_and_exit_step=True,
                            ),
                            create_service_interruption_step(
                                service=taac_types.Service.AGENT,
                            ),
                            create_service_convergence_step(
                                services=[Service.AGENT, Service.BGP],
                            ),
                            create_ecmp_member_static_route_step(
                                max_ecmp_group=ecmp_member_test_group_limit,
                                description=None,
                            ),
                            create_ixia_api_step(
                                api_name="toggle_device_groups",
                                args_dict={
                                    "enable": True,
                                    "device_group_name_regex": "D5",
                                },
                            ),
                            create_longevity_step(duration=600),
                        ],
                    )
                ],
            ),
            build_2_ixia_hardening_playbook(
                iteration=1,
                name="test_ecmp_group_overload_limit",
                prechecks=_tc_prechecks,
                postchecks=_tc_postchecks,
                snapshot_checks=_tc_snapshot_checks,
                cleanup_steps=[
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "enable": False,
                            "device_group_name_regex": "D5",
                        },
                    ),
                ],
                stages=[
                    create_steps_stage(
                        steps=[
                            create_ixia_api_step(
                                api_name="toggle_device_groups",
                                args_dict={
                                    "enable": True,
                                    "device_group_name_regex": "D5",
                                },
                            ),
                            create_longevity_step(duration=100),
                        ],
                    )
                ],
            ),
            build_2_ixia_hardening_playbook(
                name="test_cpu_high_priority_queue_overload",
                prechecks=_tc_prechecks,
                postchecks=_tc_postchecks,
                snapshot_checks=_tc_snapshot_checks
                + [
                    create_bgp_session_snapshot_check(
                        parent_prefixes_to_ignore=[
                            f"{ixia_rogue_ic_parent_network_v6}::/80",
                            f"{ixia_rogue_ic_parent_network_v4}.0/16",
                        ],
                        pre_snapshot_checkpoint_id="stage.test_cpu_high_priority_queue_overload.step.sleep_120_secs_after_disabling_bgp_cp_traffic.end",
                    ),
                    create_bgp_session_snapshot_check(
                        parent_prefixes_to_ignore=[
                            f"{ixia_rogue_ic_parent_network_v6}::/80",
                            f"{ixia_rogue_ic_parent_network_v4}.0/16",
                        ],
                        skip_flap_check=True,
                        post_snapshot_checkpoint_id="stage.test_cpu_high_priority_queue_overload.step.sleep_120_secs_after_disabling_bgp_cp_traffic.end",
                    ),
                ],
                stages=[
                    create_steps_stage(
                        stage_id="test_cpu_high_priority_queue_overload",
                        steps=[
                            create_ixia_api_step(
                                api_name="enable_traffic",
                                args_dict={
                                    "regexes": ["HIGH_QUEUE_BGP_CP_TRAFFIC"],
                                    "enable": True,
                                },
                            ),
                            create_longevity_step(duration=150),
                            create_ixia_api_step(
                                api_name="enable_traffic",
                                args_dict={
                                    "regexes": ["HIGH_QUEUE_BGP_CP_TRAFFIC"],
                                    "enable": False,
                                },
                            ),
                            create_longevity_step(
                                duration=120,
                                step_id="sleep_120_secs_after_disabling_bgp_cp_traffic",
                            ),
                            create_ixia_api_step(
                                api_name="clear_traffic_stats",
                                args_dict={},
                            ),
                            create_longevity_step(duration=30),
                        ],
                    )
                ],
            ),
            build_2_ixia_hardening_playbook(
                name="test_qsfp_service_restart",
                prechecks=_tc_prechecks,
                stages=[
                    create_steps_stage(
                        iteration=5,
                        steps=[
                            create_service_interruption_step(
                                service=taac_types.Service.QSFP_SERVICE,
                            ),
                            create_service_convergence_step(),
                        ],
                    ),
                ],
                postchecks=[
                    create_bgp_convergence_check(),
                    create_bgp_rib_fib_consistency_check(
                        extra_json_params={
                            "parent_prefixes_to_ignore": ["103.0.0.0/8", "6000:1::/32"]
                        }
                    ),
                ]
                + _tc_postchecks,
            ),
            build_2_ixia_hardening_playbook(
                name="test_fsdb_restart",
                prechecks=_tc_prechecks,
                stages=[
                    create_steps_stage(
                        iteration=5,
                        steps=[
                            create_service_interruption_step(
                                service=taac_types.Service.FSDB,
                            ),
                            create_longevity_step(duration=10),
                        ],
                    ),
                ],
                postchecks=[
                    create_bgp_convergence_check(),
                    create_bgp_rib_fib_consistency_check(
                        extra_json_params={
                            "parent_prefixes_to_ignore": ["103.0.0.0/8", "6000:1::/32"]
                        }
                    ),
                ]
                + _tc_postchecks,
            ),
        ],
    )


def test_config_for_1_ixia_bgp_and_fboss_platform_hardening_in_conveyor(
    test_config_name,
    device_name,
    local_mac_address,
    ixia_uplink_interface,
    peergroup_uplink_mimic_v6,
    peergroup_uplink_mimic_v4,
    route_map_uplink_ingress,
    route_map_uplink_egress,
    ixia_uplink_ic_parent_network_v6,
    prefix_limit,
    per_peer_max_route_limit,
    uplink_peer_count,
    remote_uplink_as_4byte,
    is_uplink_peer_confed,
    ixia_uplink_prefix_count_v6,
    ixia_uplink_communities,
    uplink_peer_tag,
    direct_ixia_connections=None,
    basset_pool=None,
    ecmp_group_overflow_prefix="7000",
    v6_uplink_prefix="6000",
):
    """Build the BGP/FBOSS hardening conveyor TestConfig for one IXIA chassis (uplink-only).

    Stripped-down sibling of
    ``test_config_for_2_ixia_bgp_and_fboss_platform_hardening_in_conveyor`` with only an
    uplink peer-group (no downlink/rogue) and only IPv6 SAFI. Used for smoke-style
    qualification on smaller testbeds where two IXIA ports are not available.

    Args:
        test_config_name: Name to register in the TestConfig (CLI-callable).
        device_name: DUT hostname.
        local_mac_address: Local MAC for the DUT side of IXIA peering.
        ixia_uplink_interface: DUT-facing IXIA uplink port.
        peergroup_uplink_mimic_v6 / _v4: Uplink BGP peer-group names.
        route_map_uplink_ingress / _egress: Uplink ingress/egress policies.
        ixia_uplink_ic_parent_network_v6: IXIA-side parent IPv6 network.
        prefix_limit / per_peer_max_route_limit: Per-peer prefix/route caps.
        uplink_peer_count: Number of mimic uplink peers.
        remote_uplink_as_4byte: Remote AS number (4-byte).
        is_uplink_peer_confed: Whether uplink peers are confederation peers.
        ixia_uplink_prefix_count_v6: Prefixes per uplink peer.
        ixia_uplink_communities: BGP community lists for uplink advertisements.
        uplink_peer_tag: Logical peer-group tag.
        direct_ixia_connections: Optional explicit direct-IXIA connection mapping.
        basset_pool: Override basset pool selection.
        ecmp_group_overflow_prefix / v6_uplink_prefix: Prefix string roots.

    Returns:
        TestConfig: The single-IXIA-chassis hardening conveyor TestConfig.
    """
    return TestConfig(
        name=test_config_name,
        ixia_protocol_verification_timeout=200,  # todo remove this (should be 300)
        skip_ixia_protocol_verification=True,
        basset_pool=basset_pool,
        endpoints=[
            taac_types.Endpoint(
                name=device_name,
                ixia_ports=[
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
                config_names=[
                    "bgpcpp",
                    "bgpcpp_softdrain",
                ],
                patcher_name="configure_bgp_switch_limit",
                py_func_name="configure_bgp_switch_limit",
                patcher_args={
                    "prefix_limit": prefix_limit,
                },
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="agent",
                patcher_name="enable_port_all_ixia_ports",
                py_func_name="change_port_admin_state",
                patcher_args={
                    f"{ixia_uplink_interface}": "enable",
                },
            ),
        ]
        + get_bgp_peer_config_tasks_uplink_only(
            device_name=device_name,
            peergroup_uplink_mimic_v6=peergroup_uplink_mimic_v6,
            peergroup_uplink_mimic_v4=peergroup_uplink_mimic_v4,
            is_uplink_peer_confed=is_uplink_peer_confed,
            per_peer_max_route_limit=per_peer_max_route_limit,
            uplink_peer_tag=uplink_peer_tag,
            route_map_uplink_ingress=route_map_uplink_ingress,
            route_map_uplink_egress=route_map_uplink_egress,
            ecmp_group_overflow_prefix=ecmp_group_overflow_prefix,
        )
        + [
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
                        ]
                    }
                ),
            ),
            create_coop_apply_patchers_v2_task(
                hostnames=[device_name],
                apply_patcher_method=taac_types.ApplyPatcherMethod.AGENT_WARMBOOT.value,
            ),
        ],
        teardown_tasks=[
            create_coop_unregister_patchers_task(device_name),
            create_run_commands_on_shell_task(
                hostname=device_name,
                cmds=["pkill memory_pressure"],
            ),
        ],
        basic_port_configs=[
            taac_types.BasicPortConfig(
                endpoint=f"{device_name}:{ixia_uplink_interface}",
                device_group_configs=[
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
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
                            is_confed=is_uplink_peer_confed == "True",
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=ixia_uplink_prefix_count_v6,
                                        prefix_length=64,
                                        starting_prefixes=f"{v6_uplink_prefix}:1::",
                                        prefix_step="0:0:0:0::0",
                                        bgp_communities=ixia_uplink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    ),
                                ),
                            ],
                        ),
                    ),
                ],
            ),
        ],
        traffic_items_to_start=["(?!HIGH_QUEUE_BGP_CP_TRAFFIC)"],
        basic_traffic_item_configs=[],
        # Deprecated - define at playbook level
        # postchecks=[
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.DEVICE_CORE_DUMPS_CHECK,
        #         ...
        #     ),
        # ],
        # Deprecated - define at playbook level
        # prechecks=[],
        playbooks=[
            build_2_ixia_hardening_playbook(
                name="test_5_min_longevity",
                postchecks=[
                    create_device_core_dumps_check(),
                ],
                stages=[
                    create_steps_stage(
                        steps=[create_longevity_step(duration=300)],
                    )
                ],
            ),
        ],
    )
