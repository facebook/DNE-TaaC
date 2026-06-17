# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Single-DUT FBOSS BGP++ + platform hardening conveyor TestConfig builder.

Centralizes the giant ``test_config_for_bgp_and_fboss_platform_hardening_in_conveyor``
factory and its supporting IXIA-healthcheck helpers used by the conveyor runs that
exercise BGPd/wedge_agent restart, mass session toggle, NDP/ARP/MAC stress, and ECMP
overflow on Wedge100S/Wedge400C platforms.
"""

import json
import logging

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
    create_bgp_session_snapshot_check,
    create_core_dumps_snapshot_check,
    create_cpu_utilization_check,
    create_device_core_dumps_check,
    create_l2_entry_threshold_check,
    create_memory_utilization_check,
    create_oomd_kill_check,
    create_prefix_limit_check,
    create_service_restart_check,
    create_systemctl_active_state_check,
    create_unclean_exit_check,
)
from taac.packet_headers import BGP_CP_TRAFFIC_PACKET_HEADERS
from taac.playbooks.playbook_definitions import (
    AGENT_RESTART_SERVICE_CHECK,
    build_hardening_conveyor_playbook,
    create_agent_coldboot_playbook,
    create_agent_crash_playbook,
    create_agent_warmboot_playbook,
    create_bgpd_crash_playbook,
    create_bgpd_restart_playbook,
    create_fsdb_crash_playbook,
    create_fsdb_restart_playbook,
    create_openr_crash_playbook,
    create_openr_restart_playbook,
    create_qsfp_service_crash_playbook,
    create_qsfp_service_restart_playbook,
    TEST_AGENT_AND_BGPD_RESTART_PLAYBOOK,
    TEST_AGENT_AND_FSDB_RESTART_PLAYBOOK,
    TEST_AGENT_AND_QSFP_SERVICE_RESTART_PLAYBOOK,
    TEST_BGPD_AND_FSDB_RESTART_PLAYBOOK,
    TEST_FBOSS_HW_AGENT_0_CRASH_PLAYBOOK,
    TEST_FBOSS_HW_AGENT_0_RESTART_PLAYBOOK,
    TEST_FBOSS_SW_AGENT_AND_HW_AGENT_0_CRASH_PLAYBOOK,
    TEST_FBOSS_SW_AGENT_AND_HW_AGENT_0_RESTART_PLAYBOOK,
    TEST_FBOSS_SW_AGENT_CRASH_PLAYBOOK,
    TEST_FBOSS_SW_AGENT_WARMBOOT_PLAYBOOK,
    TEST_FSDB_AND_QSFP_SERVICE_RESTART_PLAYBOOK,
    TEST_SW_AGENT_AND_WEDGE_AGENT_RESTART_PLAYBOOK,
)

# Re-exported for backward compatibility with non-bgp_dc consumers
# (network_ai_hardening_test_config, dsf_hardening_test_config_playbooks,
# mp3n_gar_test_config, etc.). Phase 5.0d (B2) extracted these symbols to
# routing/dc_routing/bgp_dc/shared_constants.py to break the bgp_dc layering
# inversion.
from taac.routing.dc_routing.bgp_dc.shared_constants import (  # noqa: F401
    AGENT_RESTART_STEPS,
    BGP_RESTART_STEPS,
    BGP_SESSION_HEALTHCHECK_NO_V6_LOSS_EXPECTED,
    create_ixia_packet_loss_check_traffic_split,
    get_ixia_healthcheck_ignore_cpu_and_v4_directional_traffic,
    get_ixia_healthcheck_stable_state,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_allocate_cgroup_memory_step,
    create_ecmp_member_static_route_step,
    create_ixia_api_step,
    create_longevity_step,
    create_mass_bgp_peer_toggle_step,
    create_service_convergence_step,
    create_service_interruption_step,
    create_toggle_ixia_prefix_session_flap_step,
)
from taac.task_definitions import (
    create_add_stress_static_routes_task,
    create_allocate_cgroup_slice_memory_task,
    create_allow_all_v4_peer_group_patcher_tasks,
    create_configure_parallel_bgp_peers_task,
    create_coop_apply_patchers_task,
    create_coop_register_patcher_task,
    create_coop_unregister_patchers_task,
    create_run_commands_on_shell_task,
    create_wait_for_agent_convergence_task,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import Service, ServiceInterruptionTrigger, TestConfig


def _apply_tc_checks_to_playbooks(
    playbooks, tc_prechecks, tc_postchecks, tc_snapshot_checks
):
    """Merge TestConfig-level checks into each playbook.

    For each playbook, append tc_prechecks/tc_postchecks/tc_snapshot_checks
    to the playbook's existing checks (if any).
    """
    return [
        pb(
            prechecks=list(pb.prechecks or []) + tc_prechecks,
            postchecks=list(pb.postchecks or []) + tc_postchecks,
            snapshot_checks=list(pb.snapshot_checks or []) + tc_snapshot_checks,
        )
        for pb in playbooks
    ]


# Policy term that unconditionally accepts all routes (ALWAYS match, no actions
# → bgpd defaults to PERMIT).
_PERMIT_ALL_POLICY_TERM = {
    "name": "RULE_ACCEPT_ALL",
    "description": "Unconditionally accept all prefixes",
    "policy_match_entries": {
        "name": "",
        "description": "",
        "match_logic_type": 1,
        "match_entries": [
            {
                "type": 20,  # ALWAYS
                "match_logic_type": 0,
            }
        ],
    },
}

# Symbols extracted to routing/dc_routing/bgp_dc/shared_constants.py to break
# the bgp_dc layering inversion (Phase 5.0d B2). Re-exported above for
# backward compatibility with non-bgp_dc consumers:
#   - BGP_SESSION_HEALTHCHECK_NO_V6_LOSS_EXPECTED
#   - BGP_RESTART_STEPS, AGENT_RESTART_STEPS
#   - create_ixia_packet_loss_check_traffic_split
#   - get_ixia_healthcheck_ignore_cpu_and_v4_directional_traffic
#   - get_ixia_healthcheck_stable_state


def get_ixia_healthcheck_track_only_v6_directional_bgp_traffic(device_name: str):
    """IXIA health check that only enforces no-loss on V6 directional BGP traffic.

    Tolerates loss on NDP/V4 directional + V6 layer-3 traffic items; used during BGP++
    restart and similar phases where only V6 directional traffic is expected to remain
    forwardable.

    Args:
        device_name: Device hostname for the underlying packet-loss check.
    """
    return create_ixia_packet_loss_check_traffic_split(
        device_name,
        expect_loss_traffic=[
            "GOOD_BUT_LOSSY_NDP_TRAFFIC",
            "LOSSY_ROGUE_NDP_TRAFFIC",
            "V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
            "V6_LAYER3_TRAFFIC_DOWNLINK_AND_UPLINK",
        ],
        no_loss_traffic=["V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK"],
    )


def get_ixia_healthcheck_ignore_v4_and_v6_traffic(device_name: str):
    """IXIA health check that only enforces no-loss on V6 layer-3 directional traffic.

    Tolerates loss on NDP and both V4/V6 directional BGP traffic. Used in phases where
    BGP sessions are intentionally torn down but layer-3 forwarding via static routes
    must remain.

    Args:
        device_name: Device hostname for the underlying packet-loss check.
    """
    return create_ixia_packet_loss_check_traffic_split(
        device_name,
        expect_loss_traffic=[
            "GOOD_BUT_LOSSY_NDP_TRAFFIC",
            "LOSSY_ROGUE_NDP_TRAFFIC",
            "V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
            "V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
        ],
        no_loss_traffic=[
            "V6_LAYER3_TRAFFIC_DOWNLINK_AND_UPLINK",
        ],
    )


def get_ixia_healthcheck_ignore_ndp_traffic(device_name: str):
    """IXIA health check that enforces no-loss on V4 and V6 directional BGP traffic.

    Tolerates loss only on the NDP traffic items (good-but-lossy and rogue NDP). Used
    when steady-state BGP forwarding is expected but NDP table churn is in progress.

    Args:
        device_name: Device hostname for the underlying packet-loss check.
    """
    return create_ixia_packet_loss_check_traffic_split(
        device_name,
        expect_loss_traffic=["GOOD_BUT_LOSSY_NDP_TRAFFIC", "LOSSY_ROGUE_NDP_TRAFFIC"],
        no_loss_traffic=[
            "V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
            "V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
        ],
    )


# Pre-defined step lists for common service restarts


def create_building_block_playbooks(
    duration_mass_bgp_toggle_hr,
    longevity_duration_hr,
    stable_state_duration_hours,
    rogue_interface_name,
    total_run_time,
):
    """Build the per-iteration list of long-running BGP/platform hardening playbooks.

    A single "building block" is one mass-BGP-toggle + longevity + stable-state cycle.
    The total runtime is divided into ``num_iterations`` building blocks; the function
    raises if the total is not an exact multiple. Used by the BGP/FBOSS platform
    hardening conveyor TestConfig to compose its disruption schedule.

    Args:
        duration_mass_bgp_toggle_hr: Hours spent toggling all BGP sessions per iteration.
        longevity_duration_hr: Hours of steady-state longevity traffic per iteration.
        stable_state_duration_hours: Hours of stable-state validation per iteration.
        rogue_interface_name: Interface used as the rogue-traffic source (case-folded).
        total_run_time: Required total wall time in hours; must divide evenly by the
            sum of the three durations.

    Returns:
        list[Playbook]: Playbook list to attach to the TestConfig.

    Raises:
        ValueError: If ``total_run_time`` is not a multiple of the per-iteration cost.
    """
    rogue_interface_name = rogue_interface_name.upper()
    time_per_building_block = (
        duration_mass_bgp_toggle_hr
        + longevity_duration_hr
        + stable_state_duration_hours
    )
    if total_run_time % time_per_building_block != 0:
        raise ValueError(
            "Total run time must be a multiple of the time per building block"
        )
    num_iterations = int(total_run_time // time_per_building_block)
    playbooks = []
    for i in range(1, num_iterations + 1):
        building_block_step = [
            create_toggle_ixia_prefix_session_flap_step(
                bgp_peer_group_name_regex=f"BGP_PEER_V4_D1_{rogue_interface_name}",
                network_group_name_regex=f"BGP_PREFIX_V6_N0_D0_{rogue_interface_name}",
                stable_state_duration_hours=stable_state_duration_hours,
            ),
            create_mass_bgp_peer_toggle_step(
                device_group_name_regex=rogue_interface_name,
                toggle_time_interval_s=100,
                total_step_time_hours=duration_mass_bgp_toggle_hr,
            ),
            create_longevity_step(duration=longevity_duration_hr * 60),
        ]
        for step in building_block_step:
            playbook_name = f"test_chronos_{step.name.name.lower()}_iteration_{i}"
            playbooks.append(
                build_hardening_conveyor_playbook(
                    name=playbook_name,
                    stages=[
                        create_steps_stage(
                            steps=[step],
                        )
                    ],
                )
            )
        logging.getLogger(__name__).debug(
            f"Generated playbooks: {[p.name for p in playbooks]}"
        )
    return playbooks


# =============================================================================
# Shared BGP DC builders
# =============================================================================
# These helpers build the parts of a BGP DC TestConfig that are common to
# both the platform-hardening flavor (with IXIA traffic) and the pure BGP DC
# flavor (no traffic). They are pure functions — given the same inputs they
# produce the same outputs.
#
# IMPORTANT: These helpers are added as DEAD CODE in this diff. No existing
# callers have been switched to use them yet. Switching the callers
# (test_config_for_bgp_and_fboss_platform_hardening_in_conveyor in this
# file, and build_bgp_dc_test_config in the chronos node test
# config file) is a separate change that should be verified with snapshot
# tests against a known-good baseline.


def build_bgp_dc_endpoints(
    device_name,
    ixia_downlink_interface,
    ixia_uplink_interface,
    local_mac_address,
    direct_ixia_connections=None,
):
    """Build the standard BGP DC `endpoints` list (single DUT, two IXIA ports)."""
    return [
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
    ]


def build_bgp_dc_teardown_tasks(device_name):
    """Build the standard BGP DC teardown tasks."""
    return [
        create_coop_unregister_patchers_task(device_name),
        create_run_commands_on_shell_task(
            hostname=device_name,
            cmds=["pkill memory_pressure"],
        ),
    ]


def build_bgp_dc_setup_tasks(
    *,
    device_name,
    ixia_downlink_interface,
    ixia_uplink_interface,
    ixia_downlink_ic_parent_network_v6,
    ixia_uplink_ic_parent_network_v6,
    ixia_rogue_ic_parent_network_v6,
    ixia_downlink_ic_parent_network_v4,
    ixia_uplink_ic_parent_network_v4,
    ixia_rogue_ic_parent_network_v4,
    ixia_uplink_good_ndp_network,
    ixia_downlink_good_ndp_network,
    rogue_arp_entry_network_v4,
    good_arp_entry_network_v4,
    peergroup_uplink_mimic_v6,
    peergroup_uplink_mimic_v4,
    peergroup_downlink_mimic_v6,
    peergroup_downlink_mimic_v4,
    peergroup_rogue_mimic_v6,
    peergroup_rogue_mimic_v4,
    route_map_uplink_ingress,
    route_map_uplink_egress,
    route_map_downlink_ingress,
    route_map_downlink_egress,
    is_uplink_peer_confed,
    is_downlink_peer_confed,
    uplink_peer_tag,
    downlink_peer_tag,
    prefix_limit,
    per_peer_max_route_limit,
    downlink_peer_count,
    uplink_peer_count,
    rogue_peer_count,
    remote_downlink_as_4byte,
    remote_uplink_as_4byte,
    remote_rogue_as_4byte,
    bgp_induced_ecmp_group_count,
    ecmp_group_limit,
    ecmp_member_limit,
    good_ndp_entries_uplink,
    ecmp_group_overflow_prefix,
    allow_all_v4_policies,
    additional_setup_tasks,
):
    """Build the standard BGP DC setup_tasks list (COOP patchers, peer groups,
    parallel BGP peers, static-route stress, cgroup memory allocation).

    Mirrors the inline block in
    ``test_config_for_bgp_and_fboss_platform_hardening_in_conveyor`` exactly
    (verbatim copy, parameterized).
    """
    ixia_downlink_source_ipv6 = f"{ixia_downlink_ic_parent_network_v6}::11"
    return [
        create_coop_unregister_patchers_task(device_name),
        create_coop_apply_patchers_task(
            hostnames=[device_name],
        ),
        create_wait_for_agent_convergence_task([device_name]),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name="a_remove_bgp_peers",
            task_name="coop_register_patcher",
            patcher_args={"delete_all": "True"},
            py_func_name="remove_bgp_peers",
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name="configure_bgp_switch_limit",
            task_name="coop_register_patcher",
            patcher_args={
                "prefix_limit": prefix_limit,
            },
            py_func_name="configure_bgp_switch_limit",
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="agent",
            patcher_name="enable_port_all_ixia_ports",
            task_name="coop_register_patcher",
            patcher_args={
                f"{ixia_uplink_interface}": "enable",
                f"{ixia_downlink_interface}": "enable",
            },
            py_func_name="change_port_admin_state",
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="agent",
            patcher_name="configure_sflow_mirror_sampling",
            task_name="coop_register_patcher",
            patcher_args={
                "name": "sflow_mirror",
                "destination_ip": ixia_downlink_source_ipv6,
                "sample_rate": "100",
                "udp_src_port": "6343",
                "udp_dst_port": "6343",
            },
            py_func_name="configure_ingress_sflow_mirror_sampling",
        ),
        # PROPAGATE_EVERYTHING ingress/egress policies for downlink
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name=f"a_add_bgp_policy_statement_PROPAGATE_EVERYTHING_{peergroup_downlink_mimic_v6}_IN",
            task_name="coop_register_patcher",
            patcher_args={
                "name": f"PROPAGATE_EVERYTHING_{peergroup_downlink_mimic_v6}_IN",
                "description": "Ingress policy - accept all prefixes",
                "policy_entries": json.dumps([_PERMIT_ALL_POLICY_TERM]),
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name=f"a_add_bgp_policy_statement_PROPAGATE_EVERYTHING_{peergroup_downlink_mimic_v6}_OUT",
            task_name="coop_register_patcher",
            patcher_args={
                "name": f"PROPAGATE_EVERYTHING_{peergroup_downlink_mimic_v6}_OUT",
                "description": "Egress policy - advertise all prefixes",
                "policy_entries": json.dumps([_PERMIT_ALL_POLICY_TERM]),
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name="update_peer_group_patcher_V6_Downlink",
            task_name="coop_register_patcher",
            patcher_args={
                "name": peergroup_downlink_mimic_v6,
                "attributes_to_update_json": json.dumps(
                    {
                        "disable_ipv4_afi": "True",
                        "v4_over_v6_nexthop": "False",
                        "is_passive": "False",
                        "is_confed_peer": is_downlink_peer_confed,
                        "max_routes": per_peer_max_route_limit,
                        "ingress_policy_name": f"PROPAGATE_EVERYTHING_{peergroup_downlink_mimic_v6}_IN",
                        "egress_policy_name": f"PROPAGATE_EVERYTHING_{peergroup_downlink_mimic_v6}_OUT",
                    }
                ),
            },
            py_func_name="configure_bgp_peer_group",
        ),
        # PROPAGATE_EVERYTHING ingress/egress policies for uplink
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name=f"a_add_bgp_policy_statement_PROPAGATE_EVERYTHING_{peergroup_uplink_mimic_v6}_IN",
            task_name="coop_register_patcher",
            patcher_args={
                "name": f"PROPAGATE_EVERYTHING_{peergroup_uplink_mimic_v6}_IN",
                "description": "Ingress policy - accept all prefixes",
                "policy_entries": json.dumps([_PERMIT_ALL_POLICY_TERM]),
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name=f"a_add_bgp_policy_statement_PROPAGATE_EVERYTHING_{peergroup_uplink_mimic_v6}_OUT",
            task_name="coop_register_patcher",
            patcher_args={
                "name": f"PROPAGATE_EVERYTHING_{peergroup_uplink_mimic_v6}_OUT",
                "description": "Egress policy - advertise all prefixes",
                "policy_entries": json.dumps([_PERMIT_ALL_POLICY_TERM]),
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name=f"update_peer_group_patcher_{peergroup_uplink_mimic_v6}_Uplink",
            task_name="coop_register_patcher",
            patcher_args={
                "name": peergroup_uplink_mimic_v6,
                "attributes_to_update_json": json.dumps(
                    {
                        "disable_ipv4_afi": "True",
                        "v4_over_v6_nexthop": "False",
                        "is_passive": "False",
                        "is_confed_peer": is_uplink_peer_confed,
                        "max_routes": per_peer_max_route_limit,
                        "ingress_policy_name": f"PROPAGATE_EVERYTHING_{peergroup_uplink_mimic_v6}_IN",
                        "egress_policy_name": f"PROPAGATE_EVERYTHING_{peergroup_uplink_mimic_v6}_OUT",
                    }
                ),
            },
            py_func_name="configure_bgp_peer_group",
        ),
        *(
            create_allow_all_v4_peer_group_patcher_tasks(
                hostname=device_name,
                peer_group_name=peergroup_uplink_mimic_v4,
                peer_tag=uplink_peer_tag,
                is_confed_peer=is_uplink_peer_confed,
                per_peer_max_route_limit=per_peer_max_route_limit,
                policy_entries_json=json.dumps([_PERMIT_ALL_POLICY_TERM]),
            )
            + create_allow_all_v4_peer_group_patcher_tasks(
                hostname=device_name,
                peer_group_name=peergroup_downlink_mimic_v4,
                peer_tag=downlink_peer_tag,
                is_confed_peer=is_downlink_peer_confed,
                per_peer_max_route_limit=per_peer_max_route_limit,
                policy_entries_json=json.dumps([_PERMIT_ALL_POLICY_TERM]),
            )
            if allow_all_v4_policies
            else [
                create_coop_register_patcher_task(
                    hostname=device_name,
                    config_name="bgpcpp",
                    patcher_name=f"add_peer_group_patcher_{peergroup_uplink_mimic_v4}",
                    task_name="coop_register_patcher",
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
                    py_func_name="add_peer_group_patcher",
                ),
                create_coop_register_patcher_task(
                    hostname=device_name,
                    config_name="bgpcpp",
                    patcher_name=f"add_peer_group_patcher_{peergroup_downlink_mimic_v4}",
                    task_name="coop_register_patcher",
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
                    py_func_name="add_peer_group_patcher",
                ),
                create_coop_register_patcher_task(
                    hostname=device_name,
                    config_name="bgpcpp",
                    patcher_name=f"add_bgp_policy_match_prefix_to_propagate_routes_{route_map_downlink_ingress}",
                    task_name="coop_register_patcher",
                    patcher_args={
                        "matching_prefix": f"{ecmp_group_overflow_prefix}::/16",
                        "in_stmt_name": route_map_downlink_ingress,
                        "out_stmt_name": "RANDOM",
                    },
                    py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
                ),
                create_coop_register_patcher_task(
                    hostname=device_name,
                    config_name="bgpcpp",
                    patcher_name=f"add_bgp_policy_match_prefix_to_propagate_routes_{route_map_uplink_ingress}",
                    task_name="coop_register_patcher",
                    patcher_args={
                        "matching_prefix": f"{ecmp_group_overflow_prefix}::/16",
                        "in_stmt_name": route_map_uplink_ingress,
                        "out_stmt_name": "RANDOM",
                    },
                    py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
                ),
            ]
        ),
        create_add_stress_static_routes_task(
            hostname=device_name,
            max_ecmp_group=ecmp_group_limit,
            max_ecmp_members=ecmp_member_limit,
            nh_prefix_1=f"{ixia_uplink_good_ndp_network}::/80",
            lb_prefix_agg="6000:ab::/32",
            device_group_count=good_ndp_entries_uplink,
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
                        {
                            "starting_ip": f"{ixia_rogue_ic_parent_network_v6}::10",
                            "increment_ip": "0:0:0:0::2",
                            "prefix_length": 127,
                            "description": "Rogue IPv6 Peers",
                            "peer_group_name": peergroup_rogue_mimic_v6,
                            "num_sessions": rogue_peer_count,
                            "remote_as_4_byte": remote_rogue_as_4byte,
                            "remote_as_4_byte_step": 1,
                            "gateway_starting_ip": f"{ixia_rogue_ic_parent_network_v6}::11",
                            "gateway_increment_ip": "0:0:0:0::2",
                        },
                        {
                            "starting_ip": f"{ixia_rogue_ic_parent_network_v4}.0",
                            "increment_ip": "0.0.0.2",
                            "prefix_length": 31,
                            "description": "Rogue IPv4 Peers",
                            "peer_group_name": peergroup_rogue_mimic_v4,
                            "num_sessions": rogue_peer_count,
                            "remote_as_4_byte": remote_rogue_as_4byte,
                            "remote_as_4_byte_step": 1,
                            "gateway_starting_ip": f"{ixia_rogue_ic_parent_network_v4}.1",
                            "gateway_increment_ip": "0.0.0.2",
                        },
                    ]
                }
            ),
        ),
        *(additional_setup_tasks or []),
        create_coop_apply_patchers_task(
            hostnames=[device_name],
        ),
        create_wait_for_agent_convergence_task([device_name]),
        create_allocate_cgroup_slice_memory_task(
            hostname=device_name,
            slice_name="workload",
            run_post_ixia_setup=True,
            workload_slice_based_total_memory_decimal=0.25,
        ),
    ]


def build_bgp_dc_basic_port_configs(
    *,
    device_name,
    ixia_downlink_interface,
    ixia_uplink_interface,
    ixia_downlink_ic_parent_network_v6,
    ixia_uplink_ic_parent_network_v6,
    ixia_rogue_ic_parent_network_v6,
    ixia_downlink_ic_parent_network_v4,
    ixia_uplink_ic_parent_network_v4,
    ixia_rogue_ic_parent_network_v4,
    ixia_downlink_good_ndp_network,
    ixia_uplink_good_ndp_network,
    rogue_arp_entry_network_v4,
    good_arp_entry_network_v4,
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
    bgp_induced_ecmp_group_count,
    good_ndp_entries_uplink,
    good_ndp_entries_downlink,
    good_arp_entries,
    uplink_bgp_peer_type,
    ecmp_group_overflow_prefix,
    v6_uplink_prefix,
    v4_session_flapping_prefix,
    v6_prefix_flapping_prefix,
    v4_uplink_prefix,
    v4_downlink_prefix,
    v6_downlink_prefix,
):
    """Build the standard BGP DC basic_port_configs (downlink + uplink BasicPortConfigs
    with all BGP DeviceGroupConfigs: NO_*_PACKET_LOSS_EXPECTED, NDP/ARP stressors,
    BGP_INDUCED_ECMP, ROGUE_PREFIX_FLAP, ROGUE_SESSION_FLAP).

    Mirrors the inline block in
    ``test_config_for_bgp_and_fboss_platform_hardening_in_conveyor`` exactly
    (verbatim copy, parameterized).
    """
    ixia_downlink_source_ipv6 = f"{ixia_downlink_ic_parent_network_v6}::11"
    return [
        taac_types.BasicPortConfig(
            endpoint=f"{device_name}:{ixia_downlink_interface}",
            device_group_configs=[
                # downlink Ipv6
                taac_types.DeviceGroupConfig(
                    device_group_index=0,
                    tag_name="NO_V6_PACKET_LOSS_EXPECTED",
                    multiplier=downlink_peer_count,
                    v6_addresses_config=taac_types.IpAddressesConfig(
                        starting_ip=ixia_downlink_source_ipv6,
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
                        hold_timer=30,
                        keepalive_timer=10,
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
                    tag_name="NO_PACKET_LOSS_EXPECTED",
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
                        hold_timer=30,
                        keepalive_timer=10,
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
                    tag_name="DOWNLINK_NDP_STRESSOR",
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
                    tag_name="DOWNLINK_ARP_STRESSOR",
                    multiplier=1,
                    v4_addresses_config=taac_types.IpAddressesConfig(
                        starting_ip=f"{rogue_arp_entry_network_v4}.0.100",
                        increment_ip="0.0.0.1",
                        gateway_starting_ip=f"{rogue_arp_entry_network_v4}.0.1",
                        mask=16,
                    ),
                ),
            ],
        ),
        taac_types.BasicPortConfig(
            endpoint=f"{device_name}:{ixia_uplink_interface}",
            device_group_configs=[
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
                        is_confed=is_uplink_peer_confed == "True",
                        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        hold_timer=30,
                        keepalive_timer=10,
                        bgp_peer_type=uplink_bgp_peer_type,
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
                    tag_name="NO_PACKET_LOSS_EXPECTED",
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
                        hold_timer=30,
                        keepalive_timer=10,
                        bgp_peer_type=uplink_bgp_peer_type,
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
                    tag_name="UPLINK_NDP_STRESSOR",
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
                    tag_name="UPLINK_ARP_STRESSOR",
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
                    tag_name="UPLINK_BGP_INDUCED_ECMP_1",
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
                        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        hold_timer=30,
                        keepalive_timer=10,
                        bgp_peer_type=uplink_bgp_peer_type,
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
                    tag_name="UPLINK_BGP_INDUCED_ECMP_2",
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
                        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        hold_timer=30,
                        keepalive_timer=10,
                        bgp_peer_type=uplink_bgp_peer_type,
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
                    device_group_index=6,
                    tag_name="ROGUE_PREFIX_FLAP",
                    multiplier=rogue_peer_count,
                    v6_addresses_config=taac_types.IpAddressesConfig(
                        starting_ip=f"{ixia_rogue_ic_parent_network_v6}::11",
                        increment_ip="0:0:0:0::2",
                        gateway_starting_ip=f"{ixia_rogue_ic_parent_network_v6}::10",
                        gateway_increment_ip="0:0:0:0::2",
                        mask=127,
                    ),
                    v6_bgp_config=taac_types.BgpConfig(
                        local_as_4_bytes=remote_rogue_as_4byte,
                        local_as_increment=1,
                        enable_4_byte_local_as=True,
                        is_confed=is_rogue_peer_confed == "True",
                        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        hold_timer=30,
                        keepalive_timer=10,
                        route_scales=[
                            taac_types.RouteScaleSpec(
                                network_group_index=0,
                                v6_route_scale=taac_types.RouteScale(
                                    multiplier=1,
                                    prefix_count=ixia_rogue_prefix_count_v6,
                                    prefix_length=64,
                                    starting_prefixes=f"{v6_prefix_flapping_prefix}:f::",
                                    prefix_step="0:0:0:0::0",
                                    bgp_communities=ixia_uplink_communities,
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
                    device_group_index=7,
                    tag_name="ROGUE_SESSION_FLAP",
                    multiplier=rogue_peer_count,
                    v4_addresses_config=taac_types.IpAddressesConfig(
                        starting_ip=f"{ixia_rogue_ic_parent_network_v4}.1",
                        increment_ip="0.0.0.2",
                        gateway_starting_ip=f"{ixia_rogue_ic_parent_network_v4}.0",
                        gateway_increment_ip="0.0.0.2",
                        mask=31,
                    ),
                    v4_bgp_config=taac_types.BgpConfig(
                        local_as_4_bytes=remote_rogue_as_4byte,
                        local_as_increment=1,
                        enable_4_byte_local_as=True,
                        is_confed=is_rogue_peer_confed == "True",
                        bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                        hold_timer=30,
                        keepalive_timer=10,
                        peer_flap_config=ixia_types.BgpFlapConfig(
                            uptime_in_sec=120, downtime_in_sec=15
                        ),
                        route_scales=[
                            taac_types.RouteScaleSpec(
                                network_group_index=0,
                                v4_route_scale=taac_types.RouteScale(
                                    multiplier=1,
                                    prefix_count=ixia_rogue_prefix_count_v4,
                                    prefix_length=24,
                                    starting_prefixes=f"{v4_session_flapping_prefix}.1.0.0",
                                    prefix_step="0.0.0.0",
                                    bgp_communities=ixia_uplink_communities,
                                    ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                ),
                            ),
                        ],
                    ),
                ),
            ],
        ),
    ]


def build_bgp_dc_tc_prechecks(prefix_limit, *, include_traffic_check, device_name=None):
    """Build the standard BGP DC TestConfig prechecks list. When
    ``include_traffic_check`` is True, the IXIA stable-state check is included
    (requires ``device_name``).

    Mirrors the inline `tc_prechecks` block in
    ``test_config_for_bgp_and_fboss_platform_hardening_in_conveyor`` exactly
    when ``include_traffic_check=True``.
    """
    return [
        create_systemctl_active_state_check(),
        *(
            [get_ixia_healthcheck_stable_state(device_name)]
            if include_traffic_check
            else []
        ),
        create_prefix_limit_check(prefix_limit=prefix_limit),
        create_unclean_exit_check(),
        create_memory_utilization_check(
            threshold=5 * (1024**3),
            threshold_by_service={
                "bgpd": 4.5 * (1024**3),
                "fsdb": 7 * (1024**3),
                "qsfp_service": 2 * (1024**3),
                "fboss_sw_agent": 12 * (1024**3),
                "fboss_hw_agent@0": 8 * (1024**3),
            },
            start_time_jq_var="test_case_start_time",
        ),
        BGP_SESSION_HEALTHCHECK_NO_V6_LOSS_EXPECTED,
    ]


def build_bgp_dc_tc_postchecks(
    prefix_limit, *, include_traffic_check, device_name=None
):
    """Build the standard BGP DC TestConfig postchecks list. When
    ``include_traffic_check`` is True, the IXIA stable-state check is included
    (requires ``device_name``).

    Mirrors the inline `tc_postchecks` block in
    ``test_config_for_bgp_and_fboss_platform_hardening_in_conveyor`` exactly
    when ``include_traffic_check=True``.
    """
    return [
        create_systemctl_active_state_check(),
        create_device_core_dumps_check(),
        *(
            [get_ixia_healthcheck_stable_state(device_name)]
            if include_traffic_check
            else []
        ),
        create_prefix_limit_check(prefix_limit=prefix_limit),
        BGP_SESSION_HEALTHCHECK_NO_V6_LOSS_EXPECTED,
        create_unclean_exit_check(),
        create_memory_utilization_check(
            threshold=5 * (1024**3),
            threshold_by_service={
                "bgpd": 4.5 * (1024**3),
                "fsdb": 5 * (1024**3),
                "qsfp_service": 2 * (1024**3),
                "fboss_sw_agent": 12 * (1024**3),
                "fboss_hw_agent@0": 8 * (1024**3),
            },
            start_time_jq_var="test_case_start_time",
        ),
        create_cpu_utilization_check(
            threshold=400.0, start_time_jq_var="test_case_start_time"
        ),
        create_service_restart_check(),
    ]


def test_config_for_bgp_and_fboss_platform_hardening_in_conveyor(
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
    peergroup_rogue_mimic_v4,
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
    playbooks=None,
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
    v4_session_flapping_prefix="103",
    v6_prefix_flapping_prefix="6000",
    v4_uplink_prefix="102",
    v4_downlink_prefix="101",
    v6_downlink_prefix="3000",
    ecmp_member_limit=11500,
    ecmp_member_test_member_limit=11950,
    ecmp_member_test_group_limit=1300,
    process_restart_iterations=25,
    additional_setup_tasks=None,
    allow_all_v4_policies=False,
    uplink_bgp_peer_type=None,
    skip_playbooks=None,
):
    """Build the conveyor TestConfig for combined BGP++ and FBOSS platform hardening.

    Constructs a complete single-DUT TestConfig for the BGP/platform hardening conveyor
    against one IXIA chassis: configures uplink/downlink/rogue BGP peer groups (V4 + V6
    SAFI), sets policy/route maps, generates good-and-rogue NDP/ARP/MAC entries to stress
    L2/L3 tables, programs ECMP overflow prefixes, and attaches the disruption playbooks
    that exercise BGPd/wedge_agent restarts, mass session toggles, and longevity.

    The function takes ~80 keyword arguments because it is the sole entry point for both
    Wedge100S and Wedge400C hardening conveyor configs. Most parameters are
    self-describing (peer-group names, route-map names, prefix counts, peer counts) and
    are derived from per-platform constants in the caller.

    Args:
        test_config_name: Name to register in TestConfig (CLI-callable).
        device_name: DUT hostname.
        local_mac_address: Local MAC for the DUT side of IXIA peering.
        ixia_downlink_interface: DUT-facing IXIA port for downlink BGP peers.
        ixia_uplink_interface: DUT-facing IXIA port for uplink BGP peers.
        peergroup_uplink_mimic_v6 / _v4: Uplink BGP peer-group names for IPv6/IPv4.
        peergroup_downlink_mimic_v6 / _v4: Downlink BGP peer-group names.
        peergroup_rogue_mimic_v6 / _v4: Rogue/external BGP peer-group names.
        route_map_uplink_ingress / _egress: Inbound/outbound policy on uplink peers.
        route_map_downlink_ingress / _egress: Inbound/outbound policy on downlink peers.
        route_map_rogue_ingress / _egress: Inbound/outbound policy on rogue peers.
        ixia_downlink_ic_parent_network_v6 / _v4: IXIA-side parent IP for downlink IC.
        ixia_uplink_ic_parent_network_v6 / _v4: IXIA-side parent IP for uplink IC.
        ixia_rogue_ic_parent_network_v6 / _v4: IXIA-side parent IP for rogue IC.
        good_ndp_entry_network_v6 / rogue_ndp_entry_network_v6: NDP entry source nets.
        good_arp_entry_network_v4 / rogue_arp_entry_network_v4: ARP entry source nets.
        prefix_limit: Per-peer prefix limit programmed on the DUT.
        per_peer_max_route_limit: Per-peer max-route guard.
        downlink_peer_count / uplink_peer_count / rogue_peer_count: Number of mimic
            BGP peers in each direction.
        remote_downlink_as_4byte / remote_uplink_as_4byte / remote_rogue_as_4byte:
            Remote AS numbers (4-byte) for each peer group.
        is_uplink_peer_confed / is_downlink_peer_confed / is_rogue_peer_confed:
            Whether the peer is a confederation peer (vs. external).
        ixia_*_prefix_count_v6 / _v4: Prefix counts to advertise per peer group.
        ixia_downlink_communities / ixia_uplink_communities: BGP community lists.
        uplink_peer_tag / downlink_peer_tag: Logical tags for peer-group selection.
        ecmp_group_limit: ECMP-group cap programmed on the DUT.
        good_ndp_entries_uplink / good_ndp_entries_downlink: Real NDP entry counts.
            Downlink should be >200 since it also doubles as ECMP stress via static routes.
        rogue_ndp_entries / good_arp_entries / rogue_arp_entries: Other entry counts.
        good_mac_entry_count / rogue_mac_entry_count: MAC entries to inject.
        bgp_induced_ecmp_group_count: BGP-induced ECMP group target.
        ixia_uplink_good_ndp_network / ixia_downlink_good_ndp_network: NDP source nets.
        playbooks: Optional explicit playbook list. If ``None``, a default longevity +
            hardening playbook chain is built.
        ndp_entry_limit / arp_entry_limit / mac_entry_limit: L2/L3 table limits;
            default to soft limits from ``constants``.
        bgpd_rss_limit / bgpd_cache_size_limit: BGPd resource limits.
        bgpd_restart_no_of_interations / wedge_agent_restart_no_of_interations:
            Iteration counts for BGPd / wedge_agent restart playbooks (sic — preserves
            historical typo in arg name).
        direct_ixia_connections: Optional explicit direct IXIA connection mapping.
        basset_pool: Override basset pool selection.
        ecmp_group_overflow_prefix / v6_uplink_prefix / v4_session_flapping_prefix /
        v6_prefix_flapping_prefix / v4_uplink_prefix / v4_downlink_prefix /
        v6_downlink_prefix: Prefix string roots used to construct test prefixes.
        ecmp_member_limit / ecmp_member_test_member_limit / ecmp_member_test_group_limit:
            ECMP member sizing parameters for the dedicated ECMP test phase.
        process_restart_iterations: Iterations for the process-restart phase.
        additional_setup_tasks: Extra setup tasks to run before the playbook chain.
        allow_all_v4_policies: When ``True``, all V4 traffic is accepted (used for
            pre-V4-policy DUTs).
        uplink_bgp_peer_type: Optional override for uplink BGP peer type (e.g., RSW).
        skip_playbooks: Optional set of playbook names to skip.

    Returns:
        TestConfig: The fully-built conveyor TestConfig.
    """
    ixia_downlink_source_ipv6 = f"{ixia_downlink_ic_parent_network_v6}::11"
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
    tc_snapshot_checks = [
        create_core_dumps_snapshot_check(),
    ]
    tc_postchecks = [
        create_systemctl_active_state_check(),
        create_device_core_dumps_check(),
        get_ixia_healthcheck_stable_state(device_name),
        create_prefix_limit_check(prefix_limit=prefix_limit),
        BGP_SESSION_HEALTHCHECK_NO_V6_LOSS_EXPECTED,
        create_unclean_exit_check(),
        create_memory_utilization_check(
            threshold=5 * (1024**3),
            threshold_by_service={
                "bgpd": 4.5 * (1024**3),
                "fsdb": 5 * (1024**3),
                "qsfp_service": 2 * (1024**3),
                "fboss_sw_agent": 9 * (1024**3),
                "fboss_hw_agent@0": 8 * (1024**3),
            },
            start_time_jq_var="test_case_start_time",
        ),
        create_cpu_utilization_check(
            threshold=400.0, start_time_jq_var="test_case_start_time"
        ),
        create_service_restart_check(),
    ]
    tc_prechecks = [
        create_systemctl_active_state_check(),
        get_ixia_healthcheck_stable_state(device_name),
        create_prefix_limit_check(prefix_limit=prefix_limit),
        create_unclean_exit_check(),
        create_memory_utilization_check(
            threshold=5 * (1024**3),
            threshold_by_service={
                "bgpd": 4.5 * (1024**3),
                "fsdb": 7 * (1024**3),
                "qsfp_service": 2 * (1024**3),
                "fboss_sw_agent": 12 * (1024**3),
                "fboss_hw_agent@0": 8 * (1024**3),
            },
            start_time_jq_var="test_case_start_time",
        ),
        BGP_SESSION_HEALTHCHECK_NO_V6_LOSS_EXPECTED,
    ]

    return TestConfig(
        name=test_config_name,
        ixia_protocol_verification_timeout=300,  # todo remove this (should be 300)
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
            create_coop_apply_patchers_task(
                hostnames=[device_name],
            ),
            create_wait_for_agent_convergence_task([device_name]),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="a_remove_bgp_peers",
                task_name="coop_register_patcher",
                patcher_args={"delete_all": "True"},
                py_func_name="remove_bgp_peers",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="configure_bgp_switch_limit",
                task_name="coop_register_patcher",
                patcher_args={
                    "prefix_limit": prefix_limit,
                },
                py_func_name="configure_bgp_switch_limit",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="agent",
                patcher_name="enable_port_all_ixia_ports",
                task_name="coop_register_patcher",
                patcher_args={
                    f"{ixia_uplink_interface}": "enable",
                    f"{ixia_downlink_interface}": "enable",
                },
                py_func_name="change_port_admin_state",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="agent",
                patcher_name="configure_sflow_mirror_sampling",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": "sflow_mirror",
                    "destination_ip": ixia_downlink_source_ipv6,
                    "sample_rate": "100",
                    "udp_src_port": "6343",
                    "udp_dst_port": "6343",
                },
                py_func_name="configure_ingress_sflow_mirror_sampling",
            ),
            # PROPAGATE_EVERYTHING ingress/egress policies for downlink
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"a_add_bgp_policy_statement_PROPAGATE_EVERYTHING_{peergroup_downlink_mimic_v6}_IN",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": f"PROPAGATE_EVERYTHING_{peergroup_downlink_mimic_v6}_IN",
                    "description": "Ingress policy - accept all prefixes",
                    "policy_entries": json.dumps([_PERMIT_ALL_POLICY_TERM]),
                },
                py_func_name="add_bgp_policy_statement",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"a_add_bgp_policy_statement_PROPAGATE_EVERYTHING_{peergroup_downlink_mimic_v6}_OUT",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": f"PROPAGATE_EVERYTHING_{peergroup_downlink_mimic_v6}_OUT",
                    "description": "Egress policy - advertise all prefixes",
                    "policy_entries": json.dumps([_PERMIT_ALL_POLICY_TERM]),
                },
                py_func_name="add_bgp_policy_statement",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="update_peer_group_patcher_V6_Downlink",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": peergroup_downlink_mimic_v6,
                    "attributes_to_update_json": json.dumps(
                        {
                            "disable_ipv4_afi": "True",
                            "v4_over_v6_nexthop": "False",
                            "is_passive": "False",
                            "is_confed_peer": is_downlink_peer_confed,
                            "max_routes": per_peer_max_route_limit,
                            "ingress_policy_name": f"PROPAGATE_EVERYTHING_{peergroup_downlink_mimic_v6}_IN",
                            "egress_policy_name": f"PROPAGATE_EVERYTHING_{peergroup_downlink_mimic_v6}_OUT",
                        }
                    ),
                },
                py_func_name="configure_bgp_peer_group",
            ),
            # PROPAGATE_EVERYTHING ingress/egress policies for uplink
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"a_add_bgp_policy_statement_PROPAGATE_EVERYTHING_{peergroup_uplink_mimic_v6}_IN",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": f"PROPAGATE_EVERYTHING_{peergroup_uplink_mimic_v6}_IN",
                    "description": "Ingress policy - accept all prefixes",
                    "policy_entries": json.dumps([_PERMIT_ALL_POLICY_TERM]),
                },
                py_func_name="add_bgp_policy_statement",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"a_add_bgp_policy_statement_PROPAGATE_EVERYTHING_{peergroup_uplink_mimic_v6}_OUT",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": f"PROPAGATE_EVERYTHING_{peergroup_uplink_mimic_v6}_OUT",
                    "description": "Egress policy - advertise all prefixes",
                    "policy_entries": json.dumps([_PERMIT_ALL_POLICY_TERM]),
                },
                py_func_name="add_bgp_policy_statement",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"update_peer_group_patcher_{peergroup_uplink_mimic_v6}_Uplink",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": peergroup_uplink_mimic_v6,
                    "attributes_to_update_json": json.dumps(
                        {
                            "disable_ipv4_afi": "True",
                            "v4_over_v6_nexthop": "False",
                            "is_passive": "False",
                            "is_confed_peer": is_uplink_peer_confed,
                            "max_routes": per_peer_max_route_limit,
                            "ingress_policy_name": f"PROPAGATE_EVERYTHING_{peergroup_uplink_mimic_v6}_IN",
                            "egress_policy_name": f"PROPAGATE_EVERYTHING_{peergroup_uplink_mimic_v6}_OUT",
                        }
                    ),
                },
                py_func_name="configure_bgp_peer_group",
            ),
            *(
                create_allow_all_v4_peer_group_patcher_tasks(
                    hostname=device_name,
                    peer_group_name=peergroup_uplink_mimic_v4,
                    peer_tag=uplink_peer_tag,
                    is_confed_peer=is_uplink_peer_confed,
                    per_peer_max_route_limit=per_peer_max_route_limit,
                    policy_entries_json=json.dumps([_PERMIT_ALL_POLICY_TERM]),
                )
                + create_allow_all_v4_peer_group_patcher_tasks(
                    hostname=device_name,
                    peer_group_name=peergroup_downlink_mimic_v4,
                    peer_tag=downlink_peer_tag,
                    is_confed_peer=is_downlink_peer_confed,
                    per_peer_max_route_limit=per_peer_max_route_limit,
                    policy_entries_json=json.dumps([_PERMIT_ALL_POLICY_TERM]),
                )
                if allow_all_v4_policies
                else [
                    create_coop_register_patcher_task(
                        hostname=device_name,
                        config_name="bgpcpp",
                        patcher_name=f"add_peer_group_patcher_{peergroup_uplink_mimic_v4}",
                        task_name="coop_register_patcher",
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
                        py_func_name="add_peer_group_patcher",
                    ),
                    create_coop_register_patcher_task(
                        hostname=device_name,
                        config_name="bgpcpp",
                        patcher_name=f"add_peer_group_patcher_{peergroup_downlink_mimic_v4}",
                        task_name="coop_register_patcher",
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
                        py_func_name="add_peer_group_patcher",
                    ),
                    create_coop_register_patcher_task(
                        hostname=device_name,
                        config_name="bgpcpp",
                        patcher_name=f"add_bgp_policy_match_prefix_to_propagate_routes_{route_map_downlink_ingress}",
                        task_name="coop_register_patcher",
                        patcher_args={
                            "matching_prefix": f"{ecmp_group_overflow_prefix}::/16",
                            "in_stmt_name": route_map_downlink_ingress,
                            "out_stmt_name": "RANDOM",
                        },
                        py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
                    ),
                    create_coop_register_patcher_task(
                        hostname=device_name,
                        config_name="bgpcpp",
                        patcher_name=f"add_bgp_policy_match_prefix_to_propagate_routes_{route_map_uplink_ingress}",
                        task_name="coop_register_patcher",
                        patcher_args={
                            "matching_prefix": f"{ecmp_group_overflow_prefix}::/16",
                            "in_stmt_name": route_map_uplink_ingress,
                            "out_stmt_name": "RANDOM",
                        },
                        py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
                    ),
                ]
            ),
            create_add_stress_static_routes_task(
                hostname=device_name,
                max_ecmp_group=ecmp_group_limit,
                max_ecmp_members=ecmp_member_limit,
                nh_prefix_1=f"{ixia_uplink_good_ndp_network}::/80",
                lb_prefix_agg="6000:ab::/32",
                device_group_count=good_ndp_entries_uplink,
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
                            {
                                "starting_ip": f"{ixia_rogue_ic_parent_network_v6}::10",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "Rogue IPv6 Peers",
                                "peer_group_name": peergroup_rogue_mimic_v6,
                                "num_sessions": rogue_peer_count,
                                "remote_as_4_byte": remote_rogue_as_4byte,
                                "remote_as_4_byte_step": 1,
                                "gateway_starting_ip": f"{ixia_rogue_ic_parent_network_v6}::11",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            {
                                "starting_ip": f"{ixia_rogue_ic_parent_network_v4}.0",
                                "increment_ip": "0.0.0.2",
                                "prefix_length": 31,
                                "description": "Rogue IPv4 Peers",
                                "peer_group_name": peergroup_rogue_mimic_v4,
                                "num_sessions": rogue_peer_count,
                                "remote_as_4_byte": remote_rogue_as_4byte,
                                "remote_as_4_byte_step": 1,
                                "gateway_starting_ip": f"{ixia_rogue_ic_parent_network_v4}.1",
                                "gateway_increment_ip": "0.0.0.2",
                            },
                        ]
                    }
                ),
            ),
            *(additional_setup_tasks or []),
            create_coop_apply_patchers_task(
                hostnames=[device_name],
            ),
            create_wait_for_agent_convergence_task([device_name]),
            # Task(
            #     task_name="wait_for_bgp_convergence",
            #     params=Params(
            #         json_params=json.dumps(
            #             {
            #                 "hostnames": [device_name],
            #             }
            #         ),
            #     ),
            # ),
            create_allocate_cgroup_slice_memory_task(
                hostname=device_name,
                slice_name="workload",
                run_post_ixia_setup=True,
                workload_slice_based_total_memory_decimal=0.25,
            ),
        ],
        teardown_tasks=[
            create_coop_unregister_patchers_task(device_name),
            create_run_commands_on_shell_task(
                hostname=device_name,
                cmds=["pkill memory_pressure"],
            ),
        ],
        # Deprecated - define at playbook level
        # periodic_tasks=[],
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
        basic_port_configs=[
            taac_types.BasicPortConfig(
                endpoint=f"{device_name}:{ixia_downlink_interface}",
                device_group_configs=[
                    # downlink Ipv6
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        tag_name="NO_V6_PACKET_LOSS_EXPECTED",
                        multiplier=downlink_peer_count,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=ixia_downlink_source_ipv6,
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
                            hold_timer=30,
                            keepalive_timer=10,
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
                        tag_name="NO_PACKET_LOSS_EXPECTED",
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
                            hold_timer=30,
                            keepalive_timer=10,
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
                        tag_name="DOWNLINK_NDP_STRESSOR",
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
                        tag_name="DOWNLINK_ARP_STRESSOR",
                        multiplier=1,
                        v4_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{rogue_arp_entry_network_v4}.0.100",
                            increment_ip="0.0.0.1",
                            gateway_starting_ip=f"{rogue_arp_entry_network_v4}.0.1",
                            mask=16,
                        ),
                    ),
                ],
            ),
            taac_types.BasicPortConfig(
                endpoint=f"{device_name}:{ixia_uplink_interface}",
                device_group_configs=[
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
                            is_confed=is_uplink_peer_confed == "True",
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            hold_timer=30,
                            keepalive_timer=10,
                            bgp_peer_type=uplink_bgp_peer_type,
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
                        tag_name="NO_PACKET_LOSS_EXPECTED",
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
                            hold_timer=30,
                            keepalive_timer=10,
                            bgp_peer_type=uplink_bgp_peer_type,
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
                        tag_name="UPLINK_NDP_STRESSOR",
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
                        tag_name="UPLINK_ARP_STRESSOR",
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
                        tag_name="UPLINK_BGP_INDUCED_ECMP_1",
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
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            hold_timer=30,
                            keepalive_timer=10,
                            bgp_peer_type=uplink_bgp_peer_type,
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
                        tag_name="UPLINK_BGP_INDUCED_ECMP_2",
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
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            hold_timer=30,
                            keepalive_timer=10,
                            bgp_peer_type=uplink_bgp_peer_type,
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
                        device_group_index=6,
                        tag_name="ROGUE_PREFIX_FLAP",
                        multiplier=rogue_peer_count,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_rogue_ic_parent_network_v6}::11",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_rogue_ic_parent_network_v6}::10",
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
                            hold_timer=30,
                            keepalive_timer=10,
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=ixia_rogue_prefix_count_v6,
                                        prefix_length=64,
                                        starting_prefixes=f"{v6_prefix_flapping_prefix}:f::",
                                        prefix_step="0:0:0:0::0",
                                        bgp_communities=ixia_uplink_communities,
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
                        device_group_index=7,
                        tag_name="ROGUE_SESSION_FLAP",
                        multiplier=rogue_peer_count,
                        v4_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_rogue_ic_parent_network_v4}.1",
                            increment_ip="0.0.0.2",
                            gateway_starting_ip=f"{ixia_rogue_ic_parent_network_v4}.0",
                            gateway_increment_ip="0.0.0.2",
                            mask=31,
                        ),
                        # Session flaps
                        v4_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_rogue_as_4byte,
                            local_as_increment=1,
                            enable_4_byte_local_as=True,
                            is_confed=is_rogue_peer_confed == "True",
                            bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                            hold_timer=30,
                            keepalive_timer=10,
                            peer_flap_config=ixia_types.BgpFlapConfig(
                                uptime_in_sec=120, downtime_in_sec=15
                            ),
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v4_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=ixia_rogue_prefix_count_v4,
                                        prefix_length=24,
                                        starting_prefixes=f"{v4_session_flapping_prefix}.1.0.0",
                                        prefix_step="0.0.0.0",
                                        bgp_communities=ixia_uplink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                    ),
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
                name=f"{device_name.upper()}_V6_LAYER3_TRAFFIC_DOWNLINK_AND_UPLINK",
                bidirectional=True,
                merge_destinations=True,
                line_rate=10,
                src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=2,
                    )
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=2,
                    )
                ],
                traffic_type=ixia_types.TrafficType.IPV6,
                tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
            ),
            taac_types.BasicTrafficItemConfig(
                name=f"{device_name.upper()}_V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
                bidirectional=True,
                merge_destinations=True,
                line_rate=10,
                src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
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
                src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
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
                name=f"{device_name.upper()}_HIGH_QUEUE_BGP_CP_TRAFFIC",
                line_rate=70,
                traffic_type=ixia_types.TrafficType.RAW,
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
                name=f"{device_name.upper()}_GOOD_BUT_LOSSY_NDP_TRAFFIC",
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
                name=f"{device_name.upper()}_LOSSY_ROGUE_NDP_TRAFFIC",
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
        # snapshot_checks=tc_snapshot_checks,
        # Deprecated - define at playbook level
        # postchecks=tc_postchecks,
        # Deprecated - define at playbook level
        # prechecks=tc_prechecks,
        playbooks=_apply_tc_checks_to_playbooks(
            playbooks=[
                pb
                for pb in (
                    playbooks
                    if playbooks
                    else [
                        build_hardening_conveyor_playbook(
                            name="test_cgroup_system_slice_oom_kill_policy",
                            postchecks=[
                                create_oomd_kill_check(
                                    expected_oom_kills={
                                        "system.slice": ["memory-pressure"]
                                    },
                                ),
                            ],
                            stages=[
                                create_steps_stage(
                                    steps=[
                                        create_allocate_cgroup_memory_step(
                                            total_memory_pct_decimal=0.25,
                                            slice_name="system",
                                            duration=180,
                                            minimum_memory_allocation=1048 * 10,  # 10gb
                                            oom_score_adj=1000,
                                        ),
                                        create_longevity_step(duration=300),
                                    ]
                                )
                            ],
                        ),
                        build_hardening_conveyor_playbook(
                            name="test_hardening_of_ndp_overload_entries",
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
                                    ndp_entry_upper_lower_threshold=(
                                        ndp_entry_limit,
                                        good_ndp_entries_uplink
                                        + good_ndp_entries_downlink,
                                    ),
                                ),
                                get_ixia_healthcheck_stable_state(device_name),
                            ],
                        ),
                        build_hardening_conveyor_playbook(
                            name="test_hardening_of_arp_overload_entries",
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
                                    arp_entry_upper_lower_threshold=(
                                        arp_entry_limit,
                                        good_arp_entries,
                                    ),
                                ),
                            ],
                        ),
                        # NOTE: This works only for RSWs due to feature issue
                        build_hardening_conveyor_playbook(
                            name="test_hardening_of_mac_overload_entries",
                            # Order is the following:
                            # 1. stages get executed (pre-checks from test-config)
                            # 2. post-checks will be from test-config by default OR overridden by adding post-checks at playbook (not step)
                            #
                            cleanup_steps=[
                                create_ixia_api_step(
                                    api_name="configure_traffic_item_src_mac_entry_count",
                                    args_dict={
                                        "src_mac_entry_count": 1,
                                        "traffic_item_regex": f".*_{ixia_downlink_interface.upper()}_.*",
                                    },
                                ),
                            ],
                            stages=[
                                create_steps_stage(
                                    steps=[
                                        create_ixia_api_step(
                                            api_name="configure_traffic_item_src_mac_entry_count",
                                            args_dict={
                                                "src_mac_entry_count": rogue_mac_entry_count,
                                                "traffic_item_regex": f".*_{ixia_downlink_interface.upper()}_.*",
                                            },
                                        ),
                                        create_longevity_step(duration=100),
                                    ],
                                )
                            ],
                            postchecks=[
                                create_l2_entry_threshold_check(
                                    mac_entry_upper_lower_threshold=(
                                        mac_entry_limit,
                                        good_mac_entry_count
                                        + good_ndp_entries_uplink
                                        + good_ndp_entries_downlink
                                        + good_arp_entries,
                                    ),
                                ),
                            ],
                        ),
                        create_agent_warmboot_playbook(
                            iteration=wedge_agent_restart_no_of_interations,
                        ),
                        create_bgpd_restart_playbook(
                            iteration=bgpd_restart_no_of_interations,
                            ixia_rogue_ic_parent_network_v6=ixia_rogue_ic_parent_network_v6,
                            ixia_rogue_ic_parent_network_v4=ixia_rogue_ic_parent_network_v4,
                        ),
                        build_hardening_conveyor_playbook(
                            name="test_bgp_malformed_packet_test",
                            iteration=1,
                            postchecks=[
                                get_ixia_healthcheck_ignore_cpu_and_v4_directional_traffic(
                                    device_name
                                ),
                            ],
                            cleanup_steps=[],
                            stages=[
                                create_steps_stage(
                                    steps=[
                                        create_ixia_api_step(
                                            api_name="bounce_bgp_next_hop_attribute",
                                            args_dict={
                                                "enable": False,
                                                "network_group_regex": "NO_PACKET_LOSS_EXPECTED|ECMP_1",
                                            },
                                        ),
                                        create_ixia_api_step(
                                            api_name="bounce_bgp_next_hop_attribute",
                                            args_dict={
                                                "enable": False,
                                                "network_group_regex": "NO_PACKET_LOSS_EXPECTED|ECMP_1",
                                            },
                                        ),
                                        create_longevity_step(duration=1000),
                                        create_ixia_api_step(
                                            api_name="bounce_bgp_next_hop_attribute",
                                            args_dict={
                                                "enable": True,
                                                "network_group_regex": "NO_PACKET_LOSS_EXPECTED|ECMP_1",
                                            },
                                        ),
                                        create_ixia_api_step(
                                            api_name="bounce_bgp_next_hop_attribute",
                                            args_dict={
                                                "enable": True,
                                                "network_group_regex": "NO_PACKET_LOSS_EXPECTED|ECMP_1",
                                            },
                                        ),
                                        create_longevity_step(duration=200),
                                    ]
                                ),
                            ],
                        ),
                        build_hardening_conveyor_playbook(
                            iteration=1,
                            name="test_ecmp_member_overload_limit",
                            postchecks=[
                                AGENT_RESTART_SERVICE_CHECK,
                            ],
                            cleanup_steps=[
                                create_ixia_api_step(
                                    api_name="toggle_device_groups",
                                    args_dict={
                                        "enable": False,
                                        "device_group_name_regex": "ECMP_2",
                                    },
                                ),
                                create_ecmp_member_static_route_step(
                                    delete_patcher_and_exit_step=True,
                                ),
                                create_service_interruption_step(
                                    service=Service.AGENT,
                                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                                ),
                                create_service_convergence_step(
                                    services=[Service.AGENT, Service.BGP],
                                ),
                                create_ecmp_member_static_route_step(
                                    max_ecmp_group=ecmp_group_limit,
                                    max_ecmp_members=ecmp_member_limit,
                                    nh_prefix_1=f"{ixia_uplink_good_ndp_network}::/80",
                                    lb_prefix_agg="6000:ab::/32",
                                    device_group_count=good_ndp_entries_uplink,
                                    delete_patcher_and_exit_step=False,
                                ),
                            ],
                            stages=[
                                create_steps_stage(
                                    steps=[
                                        create_ecmp_member_static_route_step(
                                            delete_patcher_and_exit_step=True,
                                        ),
                                        create_service_interruption_step(
                                            service=Service.AGENT,
                                            trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                                        ),
                                        create_service_convergence_step(
                                            services=[Service.AGENT, Service.BGP],
                                        ),
                                        create_ecmp_member_static_route_step(
                                            max_ecmp_group=ecmp_member_test_group_limit,
                                            max_ecmp_members=ecmp_member_test_member_limit,
                                            nh_prefix_1=f"{ixia_uplink_good_ndp_network}::/80",
                                            lb_prefix_agg="6000:ab::/32",
                                            device_group_count=good_ndp_entries_uplink,
                                            delete_patcher_and_exit_step=False,
                                        ),
                                        create_ixia_api_step(
                                            api_name="toggle_device_groups",
                                            args_dict={
                                                "enable": True,
                                                "device_group_name_regex": "ECMP_2",
                                            },
                                        ),
                                        create_longevity_step(duration=600),
                                    ],
                                )
                            ],
                        ),
                        build_hardening_conveyor_playbook(
                            iteration=1,
                            name="test_ecmp_group_overload_limit",
                            cleanup_steps=[
                                create_ixia_api_step(
                                    api_name="toggle_device_groups",
                                    args_dict={
                                        "enable": False,
                                        "device_group_name_regex": "ECMP_2",
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
                                                "device_group_name_regex": "ECMP_2",
                                            },
                                        ),
                                        create_longevity_step(duration=100),
                                    ],
                                )
                            ],
                        ),
                        build_hardening_conveyor_playbook(
                            name="test_cpu_high_priority_queue_overload",
                            snapshot_checks=[
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
                                                "regexes": [
                                                    "HIGH_QUEUE_BGP_CP_TRAFFIC"
                                                ],
                                                "enable": True,
                                            },
                                        ),
                                        create_longevity_step(duration=150),
                                        create_ixia_api_step(
                                            api_name="enable_traffic",
                                            args_dict={
                                                "regexes": [
                                                    "HIGH_QUEUE_BGP_CP_TRAFFIC"
                                                ],
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
                        create_qsfp_service_restart_playbook(
                            iteration=process_restart_iterations,
                        ),
                        create_fsdb_restart_playbook(
                            iteration=process_restart_iterations,
                        ),
                        create_openr_restart_playbook(
                            iteration=process_restart_iterations,
                        ),
                        create_agent_coldboot_playbook(
                            iteration=process_restart_iterations,
                        ),
                        create_agent_crash_playbook(
                            iteration=process_restart_iterations,
                        ),
                        create_bgpd_crash_playbook(
                            iteration=process_restart_iterations,
                        ),
                        create_openr_crash_playbook(
                            iteration=process_restart_iterations,
                        ),
                        create_qsfp_service_crash_playbook(
                            iteration=process_restart_iterations,
                        ),
                        create_fsdb_crash_playbook(
                            iteration=process_restart_iterations,
                        ),
                        TEST_FBOSS_SW_AGENT_WARMBOOT_PLAYBOOK,
                        TEST_FBOSS_SW_AGENT_CRASH_PLAYBOOK,
                        TEST_FBOSS_HW_AGENT_0_RESTART_PLAYBOOK,
                        TEST_FBOSS_HW_AGENT_0_CRASH_PLAYBOOK,
                        TEST_FBOSS_SW_AGENT_AND_HW_AGENT_0_RESTART_PLAYBOOK,
                        TEST_FBOSS_SW_AGENT_AND_HW_AGENT_0_CRASH_PLAYBOOK,
                        TEST_BGPD_AND_FSDB_RESTART_PLAYBOOK,
                        TEST_AGENT_AND_BGPD_RESTART_PLAYBOOK,
                        TEST_AGENT_AND_FSDB_RESTART_PLAYBOOK,
                        TEST_AGENT_AND_QSFP_SERVICE_RESTART_PLAYBOOK,
                        TEST_FSDB_AND_QSFP_SERVICE_RESTART_PLAYBOOK,
                        TEST_SW_AGENT_AND_WEDGE_AGENT_RESTART_PLAYBOOK,
                    ]
                )
                if pb.name not in (skip_playbooks or [])
            ],
            tc_prechecks=tc_prechecks,
            tc_postchecks=tc_postchecks,
            tc_snapshot_checks=tc_snapshot_checks,
        ),
    )
