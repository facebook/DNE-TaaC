# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""FBOSS EBB scale TestConfig builders.

Builds full-scale BGP++ TestConfigs for FBOSS-based EBB devices, both with
and without BGP MON peering. Wires up COOP patchers, BGP policy injection,
multi-plane IBGP/EBGP peer scaling, and a multi-playbook stress profile
(BGP daemon restart, coldboot, stability endurance, 72hr longevity, plus
multi-day longevity with periodic IXIA BGP randomization). Also exposes
reusable playbook factories (`test_bgpd_restart`, `test_bgpd_coldboot`,
`test_bgpd_stability_endurance`) shared across EBB scale TestConfigs.
"""

import json

from ixia.ixia import types as ixia_types
from taac.constants import Gigabyte
from taac.health_checks.healthcheck_definitions import (
    create_cpu_utilization_check,
    create_memory_utilization_check,
)
from taac.playbooks.playbook_definitions import (
    build_ebb_scale_playbook,
)
from taac.routing.ebb.ebb_bgp_plus_plus_test_config.common_health_checks import (
    BGP_STANDARD_POSTCHECKS,
    BGP_STANDARD_PRECHECKS,
    BGP_STANDARD_SNAPSHOT_CHECKS,
)
from taac.routing.ebb.ebb_bgp_plus_plus_test_config.ixia_config_for_ebb_scale import (
    create_ebb_scale_basic_port_configs,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_longevity_step,
    create_service_convergence_step,
    create_service_interruption_step,
    create_validation_step,
)
from taac.task_definitions import (
    create_configure_parallel_bgp_peers_task,
    create_coop_apply_patchers_task,
    create_coop_register_patcher_task,
    create_coop_unregister_patchers_task,
    create_inject_bgp_policy_statements_task,
    create_ixia_randomize_bgp_prefix_local_preference_task,
    create_ixia_restart_bgp_sessions_task,
    create_periodic_task_shell,
    create_run_commands_on_shell_task,
    create_scp_file_template_task,
    create_wait_for_agent_convergence_task,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import (
    BasicPortConfig,
    BgpConfig,
    DeviceGroupConfig,
    Endpoint,
    IpAddressesConfig,
    Params,
    Playbook,
    Service,
    ServiceInterruptionTrigger,
    TestConfig,
    ValidationStage,
)


def test_bgpd_restart(
    iterations: int = 1,
    prechecks: list | None = None,
    postchecks: list | None = None,
    snapshot_checks: list | None = None,
) -> Playbook:
    return build_ebb_scale_playbook(
        name="test_bgpd_restart",
        prechecks=prechecks or [],
        postchecks=postchecks or [],
        snapshot_checks=snapshot_checks or [],
        stages=[
            create_steps_stage(
                iteration=iterations,
                steps=[
                    create_service_interruption_step(
                        service=Service.BGP,
                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(
                        services=[Service.BGP],
                        service_convergence_timeout={Service.BGP: 600},
                    ),
                    create_longevity_step(duration=600),
                ],
            ),
        ],
    )


def test_bgpd_coldboot(
    iterations: int = 1,
    name: str = "test_bgpd_coldboot",
    prechecks: list | None = None,
    postchecks: list | None = None,
    snapshot_checks: list | None = None,
) -> Playbook:
    return build_ebb_scale_playbook(
        prechecks=prechecks or [],
        postchecks=postchecks or [],
        snapshot_checks=snapshot_checks or [],
        name=name,
        stages=[
            create_steps_stage(
                iteration=iterations,
                steps=[
                    # Step 1: Stop BGP service
                    create_service_interruption_step(
                        service=Service.BGP,
                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_STOP,
                    ),
                    # Step 2: Wait for 5 minutes
                    create_longevity_step(duration=300),
                    # Step 3: Check CPU and memory utilization are stable
                    create_validation_step(
                        point_in_time_checks=[
                            create_cpu_utilization_check(
                                threshold=400.0,
                                threshold_by_service={"bgpd": 100.0},
                            ),
                            create_memory_utilization_check(
                                threshold=Gigabyte.GIG_5.value,
                            ),
                        ],
                        stage=ValidationStage.MID_TEST,
                    ),
                    # Step 4: Start BGP service
                    create_service_interruption_step(
                        service=Service.BGP,
                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_START,
                    ),
                    # Step 5: Wait for BGP service convergence
                    create_service_convergence_step(
                        services=[Service.BGP],
                        service_convergence_timeout={Service.BGP: 600},
                    ),
                    create_longevity_step(duration=600),
                ],
            ),
        ],
    )


def test_bgpd_stability_endurance(
    prechecks: list | None = None,
    postchecks: list | None = None,
    snapshot_checks: list | None = None,
) -> Playbook:
    """Wrapper function that runs BGP coldboot test 10 times for endurance testing."""
    return test_bgpd_coldboot(
        iterations=10,
        name="test_bgpd_stability_endurance",
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
    )


def test_config_for_bgp_plus_plus_ebb_with_bgp_mon(
    test_config_name,
    device_name,
    peergroup_ibgp_v6,
    peergroup_ebgp_v6,
    peergroup_ibgp_v4,
    peergroup_ebgp_v4,
    peergroup_bgp_mon,
    ixia_interface_mimic_ebgp,
    ixia_interface_mimic_ibgp,
    ixia_interface_mimic_bgp_mon,
    ibgp_remote_as,
    ebgp_remote_as,
    bgp_mon_remote_as,
    ebgp_peer_count_v4,
    ebgp_peer_count_v6,
    bgp_mon_peer_count,
    unqiue_prefix_limit,
    total_path_limit,
    ixia_ebgp_ic_parent_network_v6,
    ixia_ebgp_ic_parent_network_v4,
    ixia_ibgp_ic_parent_network_v6_dc_plane1,
    ixia_ibgp_ic_parent_network_v6_dc_plane2,
    ixia_ibgp_ic_parent_network_v6_dc_plane3,
    ixia_ibgp_ic_parent_network_v6_dc_plane4,
    ixia_ibgp_ic_parent_network_v6_mp_plane1,
    ixia_ibgp_ic_parent_network_v6_mp_plane2,
    ixia_ibgp_ic_parent_network_v6_mp_plane3,
    ixia_ibgp_ic_parent_network_v6_mp_plane4,
    ixia_ibgp_ic_parent_network_v4_dc_plane1,
    ixia_ibgp_ic_parent_network_v4_dc_plane2,
    ixia_ibgp_ic_parent_network_v4_dc_plane3,
    ixia_ibgp_ic_parent_network_v4_dc_plane4,
    ixia_ibgp_ic_parent_network_v4_mp_plane1,
    ixia_ibgp_ic_parent_network_v4_mp_plane2,
    ixia_ibgp_ic_parent_network_v4_mp_plane3,
    ixia_ibgp_ic_parent_network_v4_mp_plane4,
    ixia_bgp_mon_ic_parent_network,
    ixia_ebgp_communities,
    ixia_ibgp_communities,
    ebgp_ingress_policy_name,
    ebgp_egress_policy_name,
    ibgp_ingress_policy_name,
    ibgp_egress_policy_name,
    bgp_mon_ingress_policy_name,
    bgp_mon_egress_policy_name,
    ibgp_peer_scale_per_plane,
    local_as_4_byte,
    bgp_router_id,
    ibgp_peer_to_drain_per_plane: int = 2,
    ebgp_peer_to_drain: int = 4,
    bgpd_restart_no_of_interations: int = 1,
    log_collection_timeout: int = 600,
    direct_ixia_connections=None,
):
    """Build a full-scale FBOSS EBB BGP++ TestConfig with BGP MON peers.

    Wires up COOP patcher unregister/register, BGP policy statement
    injection, parallel BGP peer configuration across 4 planes (DC + MP) for
    IBGP/EBGP/BGP MON, and a multi-day longevity stress profile composed of
    `test_bgpd_restart`, `test_bgpd_coldboot`, `test_bgpd_stability_endurance`
    (10x coldboot), 72hr longevity, and 300000-minute longevity with hourly
    IXIA BGP session restarts (random IBGP + EBGP sessions).

    Args:
        test_config_name: Final name of the produced TestConfig.
        device_name: DUT hostname (FBOSS EBB device).
        peergroup_* / ixia_interface_mimic_* / *_remote_as / *_peer_count_* /
        ixia_*_ic_parent_network_* / ixia_*_communities / *_ingress_policy_name /
        *_egress_policy_name / ibgp_peer_scale_per_plane / local_as_4_byte /
        bgp_router_id: Peer scaling and policy knobs mirroring
            `arista_ebb_scale_test_config.test_config_for_bgp_plus_plus_on_ebb_arista_with_bgp_mon`
            but targeting FBOSS bgpd via COOP patchers (see file-level docstring).
        unqiue_prefix_limit / total_path_limit: Route scale knobs (historical
            typo in `unqiue_*` preserved).
        ibgp_peer_to_drain_per_plane / ebgp_peer_to_drain: Drain-stage knobs.
        bgpd_restart_no_of_interations: Iteration count for `test_bgpd_restart`.
        log_collection_timeout: Per-stage log collection timeout (seconds).
        direct_ixia_connections: Optional direct IXIA-port connection list.

    Returns:
        TestConfig: The FBOSS EBB scale TestConfig (with BGP MON), consumed
        by callers via `testconfigs.routing.ebb`.
    """
    return TestConfig(
        name=test_config_name,
        skip_ixia_protocol_verification=True,
        ixia_protocol_verification_timeout=900,
        log_collection_timeout=log_collection_timeout,
        basset_pool="dne.test",
        endpoints=[
            Endpoint(
                name=device_name,
                dut=True,
                ixia_ports=[
                    ixia_interface_mimic_ebgp,
                    ixia_interface_mimic_ibgp,
                    ixia_interface_mimic_bgp_mon,
                ],
                direct_ixia_connections=direct_ixia_connections
                if direct_ixia_connections
                else [],
            ),
        ],
        setup_tasks=[
            create_coop_unregister_patchers_task(device_name),
            create_scp_file_template_task(
                hostname=device_name,
                remote_path="/etc/packages/neteng-fboss-bgpd/current/bgpd.service",
                file_template="systemd_bgp_service",
                template_params={
                    "max_rss_size": "10",
                    "bgp_policy_cache_size": "200000",
                    "platform": "dev",
                },
            ),
            create_run_commands_on_shell_task(
                device_name,
                [
                    "systemctl restart bgpd",
                    "systemctl daemon-reload",
                ],
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="agent",
                patcher_name="enable_ixia_port",
                task_name="change_port_admin_state",
                patcher_args={
                    ixia_interface_mimic_ebgp: "enable",
                    ixia_interface_mimic_ibgp: "enable",
                    ixia_interface_mimic_bgp_mon: "enable",
                },
                py_func_name="change_port_admin_state",
            ),
            # Remove all the bgp peers present in the device first
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="a_remove_bgp_peers",
                task_name="remove_bgp_peers",
                patcher_args={"delete_all": "True"},
                py_func_name="remove_bgp_peers",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="apply_bgp_ebb_settings",
                task_name="bgp_feature_canary",
                patcher_args={
                    "local_as_4_byte": str(local_as_4_byte),
                    "local_confed_as_4_byte": "0",
                    "count_confeds_in_as_path_len": "False",
                    "eor_time_s": "120",
                    "router-id": bgp_router_id,
                },
                py_func_name="bgp_feature_canary",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="configure_bgp_switch_limit",
                task_name="configure_bgp_switch_limit",
                patcher_args={
                    "prefix_limit": str(unqiue_prefix_limit),
                    "total_path_limit": str(total_path_limit),
                },
                py_func_name="configure_bgp_switch_limit",
            ),
            create_inject_bgp_policy_statements_task(
                hostname=device_name,
                config_path="taac/test_bgp_policies/ebb_policy_in_fboss_format.json",
                config_name="bgpcpp",
            ),
            create_coop_apply_patchers_task([device_name], "bgpcpp"),
            create_wait_for_agent_convergence_task([device_name]),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"add_peer_group_patcher_{peergroup_ebgp_v6}",
                task_name="add_peer_group_patcher",
                patcher_args={
                    "name": peergroup_ebgp_v6,
                    "description": "BGP V6 peering for EBGP",
                    "next_hop_self": "True",
                    "disable_ipv4_afi": "True",
                    "disable_ipv6_afi": "False",
                    "is_confed_peer": "False",
                    "ingress_policy_name": ebgp_ingress_policy_name,
                    "egress_policy_name": ebgp_egress_policy_name,
                    "bgp_peer_timers_hold_time_seconds": "15",
                    "bgp_peer_timers_keep_alive_seconds": "5",
                    "bgp_peer_timers_out_delay_seconds": "3",
                    "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                    "peer_tag": "EBGP",
                    "max_routes": "20000",
                    "warning_only": "True",
                    "warning_limit": "15000",
                    "link_bandwidth_bps": "auto",
                    "v4_over_v6_nexthop": "False",
                    "is_passive": "False",
                },
                py_func_name="add_peer_group_patcher",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"add_peer_group_patcher_{peergroup_ibgp_v6}",
                task_name="add_peer_group_patcher",
                patcher_args={
                    "name": peergroup_ibgp_v6,
                    "description": "BGP V6 peering for IBGP",
                    "next_hop_self": "True",
                    "disable_ipv4_afi": "True",
                    "disable_ipv6_afi": "False",
                    "is_confed_peer": "False",
                    "ingress_policy_name": ibgp_ingress_policy_name,
                    "egress_policy_name": ibgp_egress_policy_name,
                    "bgp_peer_timers_hold_time_seconds": "15",
                    "bgp_peer_timers_keep_alive_seconds": "5",
                    "bgp_peer_timers_out_delay_seconds": "3",
                    "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                    "peer_tag": "IBGP",
                    "max_routes": "20000",
                    "warning_only": "True",
                    "warning_limit": "15000",
                    "link_bandwidth_bps": "auto",
                    "v4_over_v6_nexthop": "False",
                    "is_passive": "False",
                },
                py_func_name="add_peer_group_patcher",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"add_peer_group_patcher_{peergroup_ebgp_v4}",
                task_name="add_peer_group_patcher",
                patcher_args={
                    "name": peergroup_ebgp_v4,
                    "description": "BGP V4 peering for EBGP",
                    "next_hop_self": "True",
                    "disable_ipv4_afi": "False",
                    "disable_ipv6_afi": "True",
                    "is_confed_peer": "False",
                    "ingress_policy_name": ebgp_ingress_policy_name,
                    "egress_policy_name": ebgp_egress_policy_name,
                    "bgp_peer_timers_hold_time_seconds": "15",
                    "bgp_peer_timers_keep_alive_seconds": "5",
                    "bgp_peer_timers_out_delay_seconds": "3",
                    "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                    "peer_tag": "EBGP",
                    "max_routes": "20000",
                    "warning_only": "True",
                    "warning_limit": "15000",
                    "link_bandwidth_bps": "auto",
                    "v4_over_v6_nexthop": "False",
                    "is_passive": "False",
                },
                py_func_name="add_peer_group_patcher",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"add_peer_group_patcher_{peergroup_ibgp_v4}",
                task_name="add_peer_group_patcher",
                patcher_args={
                    "name": peergroup_ibgp_v4,
                    "description": "BGP V4 peering for IBGP",
                    "next_hop_self": "True",
                    "disable_ipv4_afi": "False",
                    "disable_ipv6_afi": "True",
                    "is_confed_peer": "False",
                    "ingress_policy_name": ibgp_ingress_policy_name,
                    "egress_policy_name": ibgp_egress_policy_name,
                    "bgp_peer_timers_hold_time_seconds": "15",
                    "bgp_peer_timers_keep_alive_seconds": "5",
                    "bgp_peer_timers_out_delay_seconds": "3",
                    "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                    "peer_tag": "IBGP",
                    "max_routes": "20000",
                    "warning_only": "True",
                    "warning_limit": "15000",
                    "link_bandwidth_bps": "auto",
                    "v4_over_v6_nexthop": "False",
                    "is_passive": "False",
                },
                py_func_name="add_peer_group_patcher",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"add_peer_group_patcher_{peergroup_bgp_mon}",
                task_name="add_peer_group_patcher",
                patcher_args={
                    "name": peergroup_bgp_mon,
                    "description": "BGP-MON",
                    "next_hop_self": "True",
                    "disable_ipv4_afi": "False",
                    "disable_ipv6_afi": "False",
                    "is_confed_peer": "False",
                    "ingress_policy_name": bgp_mon_ingress_policy_name,
                    "egress_policy_name": bgp_mon_egress_policy_name,
                    "bgp_peer_timers_hold_time_seconds": "15",
                    "bgp_peer_timers_keep_alive_seconds": "5",
                    "bgp_peer_timers_out_delay_seconds": "3",
                    "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                    "peer_tag": "IBGP",
                    "max_routes": "20000",
                    "warning_only": "True",
                    "warning_limit": "15000",
                    "link_bandwidth_bps": "auto",
                    "v4_over_v6_nexthop": "True",
                    "is_passive": "False",
                    "add_path": "BOTH",
                },
                py_func_name="add_peer_group_patcher",
            ),
            create_coop_apply_patchers_task([device_name], "bgpcpp"),
            create_wait_for_agent_convergence_task([device_name]),
            create_configure_parallel_bgp_peers_task(
                hostname=device_name,
                configure_vlans_patcher_name="configure_vlans_patcher_name_ebgp",
                add_bgp_peers_patcher_name="add_bgp_peers_patcher_name_ebgp",
                config_json=json.dumps(
                    {
                        ixia_interface_mimic_ebgp: [
                            {
                                "starting_ip": f"{ixia_ebgp_ic_parent_network_v6}::10",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "EBGP IPv6 Peers",
                                "peer_group_name": peergroup_ebgp_v6,
                                "num_sessions": ebgp_peer_count_v6,
                                "remote_as_4_byte": ebgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ebgp_ic_parent_network_v6}::11",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            {
                                "starting_ip": f"{ixia_ebgp_ic_parent_network_v4}.10",
                                "increment_ip": "0.0.0.2",
                                "prefix_length": 31,
                                "description": "EBGP IPv4 Peers",
                                "peer_group_name": peergroup_ebgp_v4,
                                "num_sessions": ebgp_peer_count_v4,
                                "remote_as_4_byte": ebgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ebgp_ic_parent_network_v4}.11",
                                "gateway_increment_ip": "0.0.0.2",
                            },
                        ]
                    }
                ),
            ),
            create_configure_parallel_bgp_peers_task(
                hostname=device_name,
                configure_vlans_patcher_name="configure_vlans_patcher_name_bgp_mon",
                add_bgp_peers_patcher_name="add_bgp_peers_patcher_name_bgp_mon",
                config_json=json.dumps(
                    {
                        ixia_interface_mimic_bgp_mon: [
                            {
                                "starting_ip": f"{ixia_bgp_mon_ic_parent_network}::10",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "bgp-mon",
                                "peer_group_name": peergroup_bgp_mon,
                                "num_sessions": bgp_mon_peer_count,
                                "remote_as_4_byte": bgp_mon_remote_as,
                                "gateway_starting_ip": f"{ixia_bgp_mon_ic_parent_network}::11",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                        ]
                    }
                ),
            ),
            create_wait_for_agent_convergence_task([device_name]),
            create_configure_parallel_bgp_peers_task(
                hostname=device_name,
                configure_vlans_patcher_name="configure_vlans_patcher_name_ibgp",
                add_bgp_peers_patcher_name="add_bgp_peers_patcher_name_ibgp",
                config_json=json.dumps(
                    {
                        ixia_interface_mimic_ibgp: [
                            {
                                "starting_ip": f"{ixia_ibgp_ic_parent_network_v6_dc_plane1}::10",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "IBGP DC IPv6 Peers - Set 1",
                                "peer_group_name": peergroup_ibgp_v6,
                                "num_sessions": ibgp_peer_scale_per_plane,
                                "remote_as_4_byte": ibgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ibgp_ic_parent_network_v6_dc_plane1}::11",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            {
                                "starting_ip": f"{ixia_ibgp_ic_parent_network_v6_dc_plane2}::10",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "IBGP DC IPv6 Peers - Set 2",
                                "peer_group_name": peergroup_ibgp_v6,
                                "num_sessions": ibgp_peer_scale_per_plane,
                                "remote_as_4_byte": ibgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ibgp_ic_parent_network_v6_dc_plane2}::11",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            {
                                "starting_ip": f"{ixia_ibgp_ic_parent_network_v6_dc_plane3}::10",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "IBGP DC IPv6 Peers - Set 3",
                                "peer_group_name": peergroup_ibgp_v6,
                                "num_sessions": ibgp_peer_scale_per_plane,
                                "remote_as_4_byte": ibgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ibgp_ic_parent_network_v6_dc_plane3}::11",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            {
                                "starting_ip": f"{ixia_ibgp_ic_parent_network_v6_dc_plane4}::10",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "IBGP DC IPv6 Peers - Set 4",
                                "peer_group_name": peergroup_ibgp_v6,
                                "num_sessions": ibgp_peer_scale_per_plane,
                                "remote_as_4_byte": ibgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ibgp_ic_parent_network_v6_dc_plane4}::11",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            {
                                "starting_ip": f"{ixia_ibgp_ic_parent_network_v6_mp_plane1}::10",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "IBGP MP IPv6 Peers - Set 1",
                                "peer_group_name": peergroup_ibgp_v6,
                                "num_sessions": ibgp_peer_scale_per_plane,
                                "remote_as_4_byte": ibgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ibgp_ic_parent_network_v6_mp_plane1}::11",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            {
                                "starting_ip": f"{ixia_ibgp_ic_parent_network_v6_mp_plane2}::10",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "IBGP MP IPv6 Peers - Set 2",
                                "peer_group_name": peergroup_ibgp_v6,
                                "num_sessions": ibgp_peer_scale_per_plane,
                                "remote_as_4_byte": ibgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ibgp_ic_parent_network_v6_mp_plane2}::11",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            {
                                "starting_ip": f"{ixia_ibgp_ic_parent_network_v6_mp_plane3}::10",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "IBGP MP IPv6 Peers - Set 3",
                                "peer_group_name": peergroup_ibgp_v6,
                                "num_sessions": ibgp_peer_scale_per_plane,
                                "remote_as_4_byte": ibgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ibgp_ic_parent_network_v6_mp_plane3}::11",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            {
                                "starting_ip": f"{ixia_ibgp_ic_parent_network_v6_mp_plane4}::10",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "IBGP MP IPv6 Peers - Set 4",
                                "peer_group_name": peergroup_ibgp_v6,
                                "num_sessions": ibgp_peer_scale_per_plane,
                                "remote_as_4_byte": ibgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ibgp_ic_parent_network_v6_mp_plane4}::11",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            {
                                "starting_ip": f"{ixia_ibgp_ic_parent_network_v4_dc_plane1}.10",
                                "increment_ip": "0.0.0.2",
                                "prefix_length": 31,
                                "description": "IBGP DC IPv4 Peers - Set 1",
                                "peer_group_name": peergroup_ibgp_v4,
                                "num_sessions": ibgp_peer_scale_per_plane,
                                "remote_as_4_byte": ibgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ibgp_ic_parent_network_v4_dc_plane1}.11",
                                "gateway_increment_ip": "0.0.0.2",
                            },
                            {
                                "starting_ip": f"{ixia_ibgp_ic_parent_network_v4_dc_plane2}.10",
                                "increment_ip": "0.0.0.2",
                                "prefix_length": 31,
                                "description": "IBGP DC IPv4 Peers - Set 2",
                                "peer_group_name": peergroup_ibgp_v4,
                                "num_sessions": ibgp_peer_scale_per_plane,
                                "remote_as_4_byte": ibgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ibgp_ic_parent_network_v4_dc_plane2}.11",
                                "gateway_increment_ip": "0.0.0.2",
                            },
                            {
                                "starting_ip": f"{ixia_ibgp_ic_parent_network_v4_dc_plane3}.10",
                                "increment_ip": "0.0.0.2",
                                "prefix_length": 31,
                                "description": "IBGP DC IPv4 Peers - Set 3",
                                "peer_group_name": peergroup_ibgp_v4,
                                "num_sessions": ibgp_peer_scale_per_plane,
                                "remote_as_4_byte": ibgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ibgp_ic_parent_network_v4_dc_plane3}.11",
                                "gateway_increment_ip": "0.0.0.2",
                            },
                            {
                                "starting_ip": f"{ixia_ibgp_ic_parent_network_v4_dc_plane4}.10",
                                "increment_ip": "0.0.0.2",
                                "prefix_length": 31,
                                "description": "IBGP DC IPv4 Peers - Set 4",
                                "peer_group_name": peergroup_ibgp_v4,
                                "num_sessions": ibgp_peer_scale_per_plane,
                                "remote_as_4_byte": ibgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ibgp_ic_parent_network_v4_dc_plane4}.11",
                                "gateway_increment_ip": "0.0.0.2",
                            },
                            {
                                "starting_ip": f"{ixia_ibgp_ic_parent_network_v4_mp_plane1}.10",
                                "increment_ip": "0.0.0.2",
                                "prefix_length": 31,
                                "description": "IBGP MP IPv4 Peers - Set1",
                                "peer_group_name": peergroup_ibgp_v4,
                                "num_sessions": ibgp_peer_scale_per_plane,
                                "remote_as_4_byte": ibgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ibgp_ic_parent_network_v4_mp_plane1}.11",
                                "gateway_increment_ip": "0.0.0.2",
                            },
                            {
                                "starting_ip": f"{ixia_ibgp_ic_parent_network_v4_mp_plane2}.10",
                                "increment_ip": "0.0.0.2",
                                "prefix_length": 31,
                                "description": "IBGP MP IPv4 Peers - Set2",
                                "peer_group_name": peergroup_ibgp_v4,
                                "num_sessions": ibgp_peer_scale_per_plane,
                                "remote_as_4_byte": ibgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ibgp_ic_parent_network_v4_mp_plane2}.11",
                                "gateway_increment_ip": "0.0.0.2",
                            },
                            {
                                "starting_ip": f"{ixia_ibgp_ic_parent_network_v4_mp_plane3}.10",
                                "increment_ip": "0.0.0.2",
                                "prefix_length": 31,
                                "description": "IBGP MP IPv4 Peers - Set3",
                                "peer_group_name": peergroup_ibgp_v4,
                                "num_sessions": ibgp_peer_scale_per_plane,
                                "remote_as_4_byte": ibgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ibgp_ic_parent_network_v4_mp_plane3}.11",
                                "gateway_increment_ip": "0.0.0.2",
                            },
                            {
                                "starting_ip": f"{ixia_ibgp_ic_parent_network_v4_mp_plane4}.10",
                                "increment_ip": "0.0.0.2",
                                "prefix_length": 31,
                                "description": "IBGP MP IPv4 Peers - Set4",
                                "peer_group_name": peergroup_ibgp_v4,
                                "num_sessions": ibgp_peer_scale_per_plane,
                                "remote_as_4_byte": ibgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ibgp_ic_parent_network_v4_mp_plane4}.11",
                                "gateway_increment_ip": "0.0.0.2",
                            },
                        ]
                    }
                ),
            ),
            create_coop_apply_patchers_task([device_name], "bgpcpp"),
            create_coop_apply_patchers_task([device_name], do_warmboot=True),
        ],
        teardown_tasks=[
            create_coop_unregister_patchers_task(device_name),
        ],
        basic_port_configs=create_ebb_scale_basic_port_configs(
            device_name=device_name,
            ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
            ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
            ixia_interface_mimic_bgp_mon=ixia_interface_mimic_bgp_mon,
            ebgp_peer_count_v6=ebgp_peer_count_v6,
            ebgp_peer_count_v4=ebgp_peer_count_v4,
            ebgp_peer_to_drain=ebgp_peer_to_drain,
            ibgp_peer_scale_per_plane=ibgp_peer_scale_per_plane,
            ibgp_peer_to_drain_per_plane=ibgp_peer_to_drain_per_plane,
            bgp_mon_peer_count=bgp_mon_peer_count,
            ebgp_remote_as=ebgp_remote_as,
            ibgp_remote_as=ibgp_remote_as,
            bgp_mon_remote_as=bgp_mon_remote_as,
            ixia_ebgp_ic_parent_network_v6=ixia_ebgp_ic_parent_network_v6,
            ixia_ebgp_ic_parent_network_v4=ixia_ebgp_ic_parent_network_v4,
            ixia_ibgp_ic_parent_network_v6_dc_plane1=ixia_ibgp_ic_parent_network_v6_dc_plane1,
            ixia_ibgp_ic_parent_network_v6_dc_plane2=ixia_ibgp_ic_parent_network_v6_dc_plane2,
            ixia_ibgp_ic_parent_network_v6_dc_plane3=ixia_ibgp_ic_parent_network_v6_dc_plane3,
            ixia_ibgp_ic_parent_network_v6_dc_plane4=ixia_ibgp_ic_parent_network_v6_dc_plane4,
            ixia_ibgp_ic_parent_network_v6_mp_plane1=ixia_ibgp_ic_parent_network_v6_mp_plane1,
            ixia_ibgp_ic_parent_network_v6_mp_plane2=ixia_ibgp_ic_parent_network_v6_mp_plane2,
            ixia_ibgp_ic_parent_network_v6_mp_plane3=ixia_ibgp_ic_parent_network_v6_mp_plane3,
            ixia_ibgp_ic_parent_network_v6_mp_plane4=ixia_ibgp_ic_parent_network_v6_mp_plane4,
            ixia_ibgp_ic_parent_network_v4_dc_plane1=ixia_ibgp_ic_parent_network_v4_dc_plane1,
            ixia_ibgp_ic_parent_network_v4_dc_plane2=ixia_ibgp_ic_parent_network_v4_dc_plane2,
            ixia_ibgp_ic_parent_network_v4_dc_plane3=ixia_ibgp_ic_parent_network_v4_dc_plane3,
            ixia_ibgp_ic_parent_network_v4_dc_plane4=ixia_ibgp_ic_parent_network_v4_dc_plane4,
            ixia_ibgp_ic_parent_network_v4_mp_plane1=ixia_ibgp_ic_parent_network_v4_mp_plane1,
            ixia_ibgp_ic_parent_network_v4_mp_plane2=ixia_ibgp_ic_parent_network_v4_mp_plane2,
            ixia_ibgp_ic_parent_network_v4_mp_plane3=ixia_ibgp_ic_parent_network_v4_mp_plane3,
            ixia_ibgp_ic_parent_network_v4_mp_plane4=ixia_ibgp_ic_parent_network_v4_mp_plane4,
            ixia_bgp_mon_ic_parent_network=ixia_bgp_mon_ic_parent_network,
            multiplier=750,
        ),
        # Deprecated - define at playbook level
        # prechecks=BGP_STANDARD_PRECHECKS,
        # postchecks=BGP_STANDARD_POSTCHECKS,
        # snapshot_checks=BGP_STANDARD_SNAPSHOT_CHECKS,
        playbooks=[
            build_ebb_scale_playbook(
                prechecks=BGP_STANDARD_PRECHECKS,
                postchecks=BGP_STANDARD_POSTCHECKS,
                snapshot_checks=BGP_STANDARD_SNAPSHOT_CHECKS,
                periodic_tasks=[
                    taac_types.PeriodicTask(
                        name="create_ixia_bgp_prefix_churn_every_10_minutes",
                        interval=600,
                        task=create_periodic_task_shell(
                            task_name="ixia_enable_disable_bgp_prefixes",
                        ),
                        params_list=[
                            Params(
                                json_params=json.dumps(
                                    {
                                        "prefix_pool_regex": ".*IBGP.*",
                                        "prefix_end_index": 25,
                                        "enable": False,
                                    }
                                ),
                            ),
                            Params(
                                json_params=json.dumps(
                                    {
                                        "prefix_pool_regex": ".*IBGP.*",
                                        "prefix_end_index": 25,
                                        "enable": True,
                                    }
                                ),
                            ),
                        ],
                    ),
                    taac_types.PeriodicTask(
                        name="randomize_ixia_bgp_prefix_local_preference_every_10_minutes",
                        interval=600,
                        task=create_ixia_randomize_bgp_prefix_local_preference_task(
                            prefix_pool_regex=".*IBGP.*",
                            prefix_start_index=25,
                            prefix_end_index=50,
                            start_value=90,
                            end_value=121,
                        ),
                    ),
                    taac_types.PeriodicTask(
                        name="fluctuate_ixia_bgp_prefix_origin_every_10_minutes",
                        interval=600,
                        task=create_periodic_task_shell(
                            task_name="ixia_modify_bgp_prefixes_origin_value",
                        ),
                        params_list=[
                            Params(
                                json_params=json.dumps(
                                    {
                                        "prefix_pool_regex": ".*IBGP.*",
                                        "prefix_start_index": 50,
                                        "prefix_end_index": 75,
                                        "origin_value": "incomplete",
                                    }
                                ),
                            ),
                            Params(
                                json_params=json.dumps(
                                    {
                                        "prefix_pool_regex": ".*IBGP.*",
                                        "prefix_start_index": 50,
                                        "prefix_end_index": 75,
                                        "origin_value": "igp",
                                    }
                                ),
                            ),
                        ],
                    ),
                    taac_types.PeriodicTask(
                        name="drain_undrain_ixia_bgp_peers_every_60_minutes",
                        interval=3600,  # 60 minutes
                        task=create_periodic_task_shell(
                            task_name="ixia_drain_undrain_bgp_peers",
                            ixia_needed=True,
                        ),
                        params_list=[
                            Params(
                                json_params=json.dumps(
                                    {"prefix_pool_regex": ".*DRAIN.*", "drain": True}
                                ),
                            ),
                            Params(
                                json_params=json.dumps(
                                    {"prefix_pool_regex": ".*DRAIN.*", "drain": False}
                                ),
                            ),
                        ],
                    ),
                    taac_types.PeriodicTask(
                        name="restart_ibgp_bgp_sessions_every_hour",
                        task=create_ixia_restart_bgp_sessions_task(
                            bgp_peer_regex=r"\b(?!\w*DRAIN\w*)\w*IBGP\w*\b",
                            random_session_num=2,
                        ),
                        interval=3600,  # 60 minutes
                    ),
                    taac_types.PeriodicTask(
                        name="restart_ebgp_bgp_sessions_every_hour",
                        task=create_ixia_restart_bgp_sessions_task(
                            bgp_peer_regex=r"\b(?!\w*DRAIN\w*)\w*EBGP\w*\b",
                            random_session_num=4,
                        ),
                        interval=3600,  # 60 minutes
                    ),
                ],
                name="test_48_hr_longevity",
                stages=[
                    create_steps_stage(
                        steps=[create_longevity_step(duration=172800)],
                    )
                ],
            ),
            test_bgpd_restart(
                bgpd_restart_no_of_interations,
                prechecks=BGP_STANDARD_PRECHECKS,
                postchecks=BGP_STANDARD_POSTCHECKS,
                snapshot_checks=BGP_STANDARD_SNAPSHOT_CHECKS,
            ),
            test_bgpd_coldboot(
                prechecks=BGP_STANDARD_PRECHECKS,
                postchecks=BGP_STANDARD_POSTCHECKS,
                snapshot_checks=BGP_STANDARD_SNAPSHOT_CHECKS,
            ),
            test_bgpd_stability_endurance(
                prechecks=BGP_STANDARD_PRECHECKS,
                postchecks=BGP_STANDARD_POSTCHECKS,
                snapshot_checks=BGP_STANDARD_SNAPSHOT_CHECKS,
            ),
            build_ebb_scale_playbook(
                name="test_72hr_longevity",
                prechecks=BGP_STANDARD_PRECHECKS,
                postchecks=BGP_STANDARD_POSTCHECKS,
                snapshot_checks=BGP_STANDARD_SNAPSHOT_CHECKS,
                stages=[
                    create_steps_stage(
                        steps=[create_longevity_step(duration=259200)],
                    )
                ],
            ),
        ],
    )


def test_config_for_bgp_plus_plus_ebb(
    test_config_name,
    device_name,
    peergroup_ibgp_v6,
    peergroup_ebgp_v6,
    peergroup_ibgp_v4,
    peergroup_ebgp_v4,
    ixia_interface_mimic_ebgp,
    ixia_interface_mimic_ibgp,
    ibgp_remote_as,
    ebgp_remote_as,
    ebgp_peer_count_v4,
    ebgp_peer_count_v6,
    unqiue_prefix_limit,
    total_path_limit,
    ixia_ebgp_ic_parent_network_v6,
    ixia_ebgp_ic_parent_network_v4,
    ixia_ibgp_ic_parent_network_v6_dc_plane1,
    ixia_ibgp_ic_parent_network_v6_dc_plane2,
    ixia_ibgp_ic_parent_network_v6_dc_plane3,
    ixia_ibgp_ic_parent_network_v6_dc_plane4,
    ixia_ibgp_ic_parent_network_v6_mp_plane1,
    ixia_ibgp_ic_parent_network_v6_mp_plane2,
    ixia_ibgp_ic_parent_network_v6_mp_plane3,
    ixia_ibgp_ic_parent_network_v6_mp_plane4,
    ixia_ibgp_ic_parent_network_v4_dc_plane1,
    ixia_ibgp_ic_parent_network_v4_dc_plane2,
    ixia_ibgp_ic_parent_network_v4_dc_plane3,
    ixia_ibgp_ic_parent_network_v4_dc_plane4,
    ixia_ibgp_ic_parent_network_v4_mp_plane1,
    ixia_ibgp_ic_parent_network_v4_mp_plane2,
    ixia_ibgp_ic_parent_network_v4_mp_plane3,
    ixia_ibgp_ic_parent_network_v4_mp_plane4,
    ixia_ebgp_communities,
    ixia_ibgp_communities,
    ebgp_ingress_policy_name,
    ebgp_egress_policy_name,
    ibgp_ingress_policy_name,
    ibgp_egress_policy_name,
    ibgp_peer_scale_per_plane,
    local_as_4_byte,
    bgp_router_id,
    ibgp_peer_to_drain_per_plane: int = 2,
    ebgp_peer_to_drain: int = 4,
    bgpd_restart_no_of_interations: int = 1,
    log_collection_timeout: int = 600,
):
    """Build a full-scale FBOSS EBB BGP++ TestConfig without BGP MON peers.

    Sibling of `test_config_for_bgp_plus_plus_ebb_with_bgp_mon` minus the
    BGP MON peer group and its IXIA port. Same multi-day longevity stress
    profile: BGP daemon restart, coldboot, 10x coldboot stability endurance,
    72hr longevity, and 300000-minute longevity with hourly random IBGP/EBGP
    session restarts.

    Args:
        test_config_name: Final name of the produced TestConfig.
        device_name: DUT hostname (FBOSS EBB device).
        peergroup_* / ixia_interface_mimic_* / *_remote_as / *_peer_count_* /
        ixia_*_ic_parent_network_* / ixia_*_communities / *_ingress_policy_name /
        *_egress_policy_name / ibgp_peer_scale_per_plane / local_as_4_byte /
        bgp_router_id / unqiue_prefix_limit / total_path_limit: Peer scaling
            and policy knobs (see sibling builder for details).
        ibgp_peer_to_drain_per_plane / ebgp_peer_to_drain: Drain-stage knobs.
        bgpd_restart_no_of_interations: Iteration count for `test_bgpd_restart`.
        log_collection_timeout: Per-stage log collection timeout (seconds).

    Returns:
        TestConfig: The FBOSS EBB scale TestConfig (no BGP MON), consumed
        by callers via `testconfigs.routing.ebb`.
    """
    return TestConfig(
        name=test_config_name,
        skip_ixia_protocol_verification=True,
        ixia_protocol_verification_timeout=900,
        log_collection_timeout=log_collection_timeout,
        basset_pool="dne.test",
        endpoints=[
            Endpoint(
                name=device_name,
                dut=True,
                ixia_ports=[
                    ixia_interface_mimic_ebgp,
                    ixia_interface_mimic_ibgp,
                ],
            ),
        ],
        setup_tasks=[
            create_coop_unregister_patchers_task(device_name),
            create_scp_file_template_task(
                hostname=device_name,
                remote_path="/etc/packages/neteng-fboss-bgpd/current/bgpd.service",
                file_template="systemd_bgp_service",
                template_params={
                    "max_rss_size": "10",
                    "bgp_policy_cache_size": "200000",
                    "platform": "dev",
                },
            ),
            create_run_commands_on_shell_task(
                device_name,
                [
                    "systemctl restart bgpd",
                    "systemctl daemon-reload",
                ],
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="agent",
                patcher_name="enable_ixia_port",
                task_name="change_port_admin_state",
                patcher_args={
                    ixia_interface_mimic_ebgp: "enable",
                    ixia_interface_mimic_ibgp: "enable",
                },
                py_func_name="change_port_admin_state",
            ),
            # Remove all the bgp peers present in the device first
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="a_remove_bgp_peers",
                task_name="remove_bgp_peers",
                patcher_args={"delete_all": "True"},
                py_func_name="remove_bgp_peers",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="apply_bgp_ebb_settings",
                task_name="bgp_feature_canary",
                patcher_args={
                    "local_as_4_byte": str(local_as_4_byte),
                    "local_confed_as_4_byte": "0",
                    "count_confeds_in_as_path_len": "False",
                    "eor_time_s": "120",
                    "router-id": bgp_router_id,
                },
                py_func_name="bgp_feature_canary",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="configure_bgp_switch_limit",
                task_name="configure_bgp_switch_limit",
                patcher_args={
                    "prefix_limit": str(unqiue_prefix_limit),
                    "total_path_limit": str(total_path_limit),
                },
                py_func_name="configure_bgp_switch_limit",
            ),
            create_inject_bgp_policy_statements_task(
                hostname=device_name,
                config_path="taac/test_bgp_policies/ebb_policy_in_fboss_format.json",
                config_name="bgpcpp",
            ),
            create_coop_apply_patchers_task([device_name], "bgpcpp"),
            create_wait_for_agent_convergence_task([device_name]),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"add_peer_group_patcher_{peergroup_ebgp_v6}",
                task_name="add_peer_group_patcher",
                patcher_args={
                    "name": peergroup_ebgp_v6,
                    "description": "BGP V6 peering for EBGP",
                    "next_hop_self": "True",
                    "disable_ipv4_afi": "True",
                    "disable_ipv6_afi": "False",
                    "is_confed_peer": "False",
                    "ingress_policy_name": ebgp_ingress_policy_name,
                    "egress_policy_name": ebgp_egress_policy_name,
                    "bgp_peer_timers_hold_time_seconds": "15",
                    "bgp_peer_timers_keep_alive_seconds": "5",
                    "bgp_peer_timers_out_delay_seconds": "3",
                    "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                    "peer_tag": "EBGP",
                    "max_routes": "20000",
                    "warning_only": "True",
                    "warning_limit": "15000",
                    "link_bandwidth_bps": "auto",
                    "v4_over_v6_nexthop": "False",
                    "is_passive": "False",
                },
                py_func_name="add_peer_group_patcher",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"add_peer_group_patcher_{peergroup_ibgp_v6}",
                task_name="add_peer_group_patcher",
                patcher_args={
                    "name": peergroup_ibgp_v6,
                    "description": "BGP V6 peering for IBGP",
                    "next_hop_self": "True",
                    "disable_ipv4_afi": "True",
                    "disable_ipv6_afi": "False",
                    "is_confed_peer": "False",
                    "ingress_policy_name": ibgp_ingress_policy_name,
                    "egress_policy_name": ibgp_egress_policy_name,
                    "bgp_peer_timers_hold_time_seconds": "15",
                    "bgp_peer_timers_keep_alive_seconds": "5",
                    "bgp_peer_timers_out_delay_seconds": "3",
                    "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                    "peer_tag": "IBGP",
                    "max_routes": "20000",
                    "warning_only": "True",
                    "warning_limit": "15000",
                    "link_bandwidth_bps": "auto",
                    "v4_over_v6_nexthop": "False",
                    "is_passive": "False",
                },
                py_func_name="add_peer_group_patcher",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"add_peer_group_patcher_{peergroup_ebgp_v4}",
                task_name="add_peer_group_patcher",
                patcher_args={
                    "name": peergroup_ebgp_v4,
                    "description": "BGP V4 peering for EBGP",
                    "next_hop_self": "True",
                    "disable_ipv4_afi": "False",
                    "disable_ipv6_afi": "True",
                    "is_confed_peer": "False",
                    "ingress_policy_name": ebgp_ingress_policy_name,
                    "egress_policy_name": ebgp_egress_policy_name,
                    "bgp_peer_timers_hold_time_seconds": "15",
                    "bgp_peer_timers_keep_alive_seconds": "5",
                    "bgp_peer_timers_out_delay_seconds": "3",
                    "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                    "peer_tag": "EBGP",
                    "max_routes": "20000",
                    "warning_only": "True",
                    "warning_limit": "15000",
                    "link_bandwidth_bps": "auto",
                    "v4_over_v6_nexthop": "False",
                    "is_passive": "False",
                },
                py_func_name="add_peer_group_patcher",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"add_peer_group_patcher_{peergroup_ibgp_v4}",
                task_name="add_peer_group_patcher",
                patcher_args={
                    "name": peergroup_ibgp_v4,
                    "description": "BGP V4 peering for IBGP",
                    "next_hop_self": "True",
                    "disable_ipv4_afi": "False",
                    "disable_ipv6_afi": "True",
                    "is_confed_peer": "False",
                    "ingress_policy_name": ibgp_ingress_policy_name,
                    "egress_policy_name": ibgp_egress_policy_name,
                    "bgp_peer_timers_hold_time_seconds": "15",
                    "bgp_peer_timers_keep_alive_seconds": "5",
                    "bgp_peer_timers_out_delay_seconds": "3",
                    "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                    "peer_tag": "IBGP",
                    "max_routes": "20000",
                    "warning_only": "True",
                    "warning_limit": "15000",
                    "link_bandwidth_bps": "auto",
                    "v4_over_v6_nexthop": "False",
                    "is_passive": "False",
                },
                py_func_name="add_peer_group_patcher",
            ),
            create_coop_apply_patchers_task([device_name], "bgpcpp"),
            create_wait_for_agent_convergence_task([device_name]),
            create_configure_parallel_bgp_peers_task(
                hostname=device_name,
                configure_vlans_patcher_name="configure_vlans_patcher_name_ebgp",
                add_bgp_peers_patcher_name="add_bgp_peers_patcher_name_ebgp",
                config_json=json.dumps(
                    {
                        ixia_interface_mimic_ebgp: [
                            {
                                "starting_ip": f"{ixia_ebgp_ic_parent_network_v6}::10",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "EBGP IPv6 Peers",
                                "peer_group_name": peergroup_ebgp_v6,
                                "num_sessions": ebgp_peer_count_v6,
                                "remote_as_4_byte": ebgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ebgp_ic_parent_network_v6}::11",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            {
                                "starting_ip": f"{ixia_ebgp_ic_parent_network_v4}.10",
                                "increment_ip": "0.0.0.2",
                                "prefix_length": 31,
                                "description": "EBGP IPv4 Peers",
                                "peer_group_name": peergroup_ebgp_v4,
                                "num_sessions": ebgp_peer_count_v4,
                                "remote_as_4_byte": ebgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ebgp_ic_parent_network_v4}.11",
                                "gateway_increment_ip": "0.0.0.2",
                            },
                        ]
                    }
                ),
            ),
            create_wait_for_agent_convergence_task([device_name]),
            create_configure_parallel_bgp_peers_task(
                hostname=device_name,
                configure_vlans_patcher_name="configure_vlans_patcher_name_ibgp",
                add_bgp_peers_patcher_name="add_bgp_peers_patcher_name_ibgp",
                config_json=json.dumps(
                    {
                        ixia_interface_mimic_ibgp: [
                            {
                                "starting_ip": f"{ixia_ibgp_ic_parent_network_v6_dc_plane1}::10",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "IBGP DC IPv6 Peers - Set 1",
                                "peer_group_name": peergroup_ibgp_v6,
                                "num_sessions": ibgp_peer_scale_per_plane,
                                "remote_as_4_byte": ibgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ibgp_ic_parent_network_v6_dc_plane1}::11",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            {
                                "starting_ip": f"{ixia_ibgp_ic_parent_network_v6_dc_plane2}::10",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "IBGP DC IPv6 Peers - Set 2",
                                "peer_group_name": peergroup_ibgp_v6,
                                "num_sessions": ibgp_peer_scale_per_plane,
                                "remote_as_4_byte": ibgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ibgp_ic_parent_network_v6_dc_plane2}::11",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            {
                                "starting_ip": f"{ixia_ibgp_ic_parent_network_v6_dc_plane3}::10",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "IBGP DC IPv6 Peers - Set 3",
                                "peer_group_name": peergroup_ibgp_v6,
                                "num_sessions": ibgp_peer_scale_per_plane,
                                "remote_as_4_byte": ibgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ibgp_ic_parent_network_v6_dc_plane3}::11",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            {
                                "starting_ip": f"{ixia_ibgp_ic_parent_network_v6_dc_plane4}::10",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "IBGP DC IPv6 Peers - Set 4",
                                "peer_group_name": peergroup_ibgp_v6,
                                "num_sessions": ibgp_peer_scale_per_plane,
                                "remote_as_4_byte": ibgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ibgp_ic_parent_network_v6_dc_plane4}::11",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            {
                                "starting_ip": f"{ixia_ibgp_ic_parent_network_v6_mp_plane1}::10",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "IBGP MP IPv6 Peers - Set 1",
                                "peer_group_name": peergroup_ibgp_v6,
                                "num_sessions": ibgp_peer_scale_per_plane,
                                "remote_as_4_byte": ibgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ibgp_ic_parent_network_v6_mp_plane1}::11",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            {
                                "starting_ip": f"{ixia_ibgp_ic_parent_network_v6_mp_plane2}::10",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "IBGP MP IPv6 Peers - Set 2",
                                "peer_group_name": peergroup_ibgp_v6,
                                "num_sessions": ibgp_peer_scale_per_plane,
                                "remote_as_4_byte": ibgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ibgp_ic_parent_network_v6_mp_plane2}::11",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            {
                                "starting_ip": f"{ixia_ibgp_ic_parent_network_v6_mp_plane3}::10",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "IBGP MP IPv6 Peers - Set 3",
                                "peer_group_name": peergroup_ibgp_v6,
                                "num_sessions": ibgp_peer_scale_per_plane,
                                "remote_as_4_byte": ibgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ibgp_ic_parent_network_v6_mp_plane3}::11",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            {
                                "starting_ip": f"{ixia_ibgp_ic_parent_network_v6_mp_plane4}::10",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "IBGP MP IPv6 Peers - Set 4",
                                "peer_group_name": peergroup_ibgp_v6,
                                "num_sessions": ibgp_peer_scale_per_plane,
                                "remote_as_4_byte": ibgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ibgp_ic_parent_network_v6_mp_plane4}::11",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            {
                                "starting_ip": f"{ixia_ibgp_ic_parent_network_v4_dc_plane1}.10",
                                "increment_ip": "0.0.0.2",
                                "prefix_length": 31,
                                "description": "IBGP DC IPv4 Peers - Set 1",
                                "peer_group_name": peergroup_ibgp_v4,
                                "num_sessions": ibgp_peer_scale_per_plane,
                                "remote_as_4_byte": ibgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ibgp_ic_parent_network_v4_dc_plane1}.11",
                                "gateway_increment_ip": "0.0.0.2",
                            },
                            {
                                "starting_ip": f"{ixia_ibgp_ic_parent_network_v4_dc_plane2}.10",
                                "increment_ip": "0.0.0.2",
                                "prefix_length": 31,
                                "description": "IBGP DC IPv4 Peers - Set 2",
                                "peer_group_name": peergroup_ibgp_v4,
                                "num_sessions": ibgp_peer_scale_per_plane,
                                "remote_as_4_byte": ibgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ibgp_ic_parent_network_v4_dc_plane2}.11",
                                "gateway_increment_ip": "0.0.0.2",
                            },
                            {
                                "starting_ip": f"{ixia_ibgp_ic_parent_network_v4_dc_plane3}.10",
                                "increment_ip": "0.0.0.2",
                                "prefix_length": 31,
                                "description": "IBGP DC IPv4 Peers - Set 3",
                                "peer_group_name": peergroup_ibgp_v4,
                                "num_sessions": ibgp_peer_scale_per_plane,
                                "remote_as_4_byte": ibgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ibgp_ic_parent_network_v4_dc_plane3}.11",
                                "gateway_increment_ip": "0.0.0.2",
                            },
                            {
                                "starting_ip": f"{ixia_ibgp_ic_parent_network_v4_dc_plane4}.10",
                                "increment_ip": "0.0.0.2",
                                "prefix_length": 31,
                                "description": "IBGP DC IPv4 Peers - Set 4",
                                "peer_group_name": peergroup_ibgp_v4,
                                "num_sessions": ibgp_peer_scale_per_plane,
                                "remote_as_4_byte": ibgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ibgp_ic_parent_network_v4_dc_plane4}.11",
                                "gateway_increment_ip": "0.0.0.2",
                            },
                            {
                                "starting_ip": f"{ixia_ibgp_ic_parent_network_v4_mp_plane1}.10",
                                "increment_ip": "0.0.0.2",
                                "prefix_length": 31,
                                "description": "IBGP MP IPv4 Peers - Set1",
                                "peer_group_name": peergroup_ibgp_v4,
                                "num_sessions": ibgp_peer_scale_per_plane,
                                "remote_as_4_byte": ibgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ibgp_ic_parent_network_v4_mp_plane1}.11",
                                "gateway_increment_ip": "0.0.0.2",
                            },
                            {
                                "starting_ip": f"{ixia_ibgp_ic_parent_network_v4_mp_plane2}.10",
                                "increment_ip": "0.0.0.2",
                                "prefix_length": 31,
                                "description": "IBGP MP IPv4 Peers - Set2",
                                "peer_group_name": peergroup_ibgp_v4,
                                "num_sessions": ibgp_peer_scale_per_plane,
                                "remote_as_4_byte": ibgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ibgp_ic_parent_network_v4_mp_plane2}.11",
                                "gateway_increment_ip": "0.0.0.2",
                            },
                            {
                                "starting_ip": f"{ixia_ibgp_ic_parent_network_v4_mp_plane3}.10",
                                "increment_ip": "0.0.0.2",
                                "prefix_length": 31,
                                "description": "IBGP MP IPv4 Peers - Set3",
                                "peer_group_name": peergroup_ibgp_v4,
                                "num_sessions": ibgp_peer_scale_per_plane,
                                "remote_as_4_byte": ibgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ibgp_ic_parent_network_v4_mp_plane3}.11",
                                "gateway_increment_ip": "0.0.0.2",
                            },
                            {
                                "starting_ip": f"{ixia_ibgp_ic_parent_network_v4_mp_plane4}.10",
                                "increment_ip": "0.0.0.2",
                                "prefix_length": 31,
                                "description": "IBGP MP IPv4 Peers - Set4",
                                "peer_group_name": peergroup_ibgp_v4,
                                "num_sessions": ibgp_peer_scale_per_plane,
                                "remote_as_4_byte": ibgp_remote_as,
                                "gateway_starting_ip": f"{ixia_ibgp_ic_parent_network_v4_mp_plane4}.11",
                                "gateway_increment_ip": "0.0.0.2",
                            },
                        ]
                    }
                ),
            ),
            create_coop_apply_patchers_task([device_name], "bgpcpp"),
            create_coop_apply_patchers_task([device_name], do_warmboot=True),
        ],
        teardown_tasks=[
            create_coop_unregister_patchers_task(device_name),
        ],
        basic_port_configs=[
            BasicPortConfig(
                endpoint=f"{device_name}:{ixia_interface_mimic_ebgp}",
                device_group_configs=[
                    DeviceGroupConfig(
                        device_group_name="DEVICE_GROUP_IPV6_EBGP",
                        device_group_index=0,
                        multiplier=ebgp_peer_count_v6 - ebgp_peer_to_drain,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_ebgp_ic_parent_network_v6}::11",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_ebgp_ic_parent_network_v6}::10",
                            gateway_increment_ip="0:0:0:0::2",
                            start_index=0,
                        ),
                        v6_bgp_config=BgpConfig(
                            bgp_peer_name="BGP_PEER_IPV6_EBGP",
                            local_as_4_bytes=ebgp_remote_as,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                            import_bgp_routes_params_list=[
                                ixia_types.ImportBgpRoutesParams(
                                    prefix_pool_name="PREFIX_POOL_IPV6_EBGP",
                                    multiplier=750,
                                    bgp_route_import_file_path="ipv6_routes_ebgp_enhanced.csv",
                                    import_file_type=ixia_types.BgpRouteImportFileType.CSV,
                                    network_group_index=0,
                                    bgp_attribute_configs=[
                                        ixia_types.BgpAttributeConfig(
                                            attribute=ixia_types.BgpAttribute.COMMUNITIES,
                                            file_path="ipv6_routes_ebgp_communities_enhanced.csv",
                                            distribution_type=ixia_types.DistribitionType.ROUND_ROBIN,
                                        )
                                    ],
                                    start_index=0,
                                    end_index=ebgp_peer_count_v6 - ebgp_peer_to_drain,
                                )
                            ],
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_name="DEVICE_GROUP_IPV6_EBGP_DRAIN",
                        device_group_index=1,
                        multiplier=ebgp_peer_to_drain,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_ebgp_ic_parent_network_v6}::11",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_ebgp_ic_parent_network_v6}::10",
                            gateway_increment_ip="0:0:0:0::2",
                            start_index=ebgp_peer_count_v6 - ebgp_peer_to_drain,
                        ),
                        v6_bgp_config=BgpConfig(
                            bgp_peer_name="BGP_PEER_IPV6_EBGP_DRAIN",
                            local_as_4_bytes=ebgp_remote_as,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                            import_bgp_routes_params_list=[
                                ixia_types.ImportBgpRoutesParams(
                                    prefix_pool_name="PREFIX_POOL_IPV6_EBGP_DRAIN",
                                    multiplier=750,
                                    bgp_route_import_file_path="ipv6_routes_ebgp_enhanced.csv",
                                    import_file_type=ixia_types.BgpRouteImportFileType.CSV,
                                    network_group_index=0,
                                    bgp_attribute_configs=[
                                        ixia_types.BgpAttributeConfig(
                                            attribute=ixia_types.BgpAttribute.COMMUNITIES,
                                            file_path="ipv6_routes_ebgp_communities_enhanced.csv",
                                            distribution_type=ixia_types.DistribitionType.ROUND_ROBIN,
                                        )
                                    ],
                                    start_index=ebgp_peer_count_v6 - ebgp_peer_to_drain,
                                    end_index=ebgp_peer_count_v6,  # non-inclusive
                                )
                            ],
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_name="DEVICE_GROUP_IPV4_EBGP",
                        device_group_index=2,
                        multiplier=ebgp_peer_count_v4 - ebgp_peer_to_drain,
                        v4_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_ebgp_ic_parent_network_v4}.11",
                            increment_ip="0.0.0.2",
                            gateway_starting_ip=f"{ixia_ebgp_ic_parent_network_v4}.10",
                            gateway_increment_ip="0.0.0.2",
                            mask=31,
                            start_index=0,
                        ),
                        v4_bgp_config=BgpConfig(
                            bgp_peer_name="BGP_PEER_IPV4_EBGP",
                            local_as_4_bytes=ebgp_remote_as,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                            bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                            import_bgp_routes_params_list=[
                                ixia_types.ImportBgpRoutesParams(
                                    prefix_pool_name="PREFIX_POOL_IPV4_EBGP",
                                    multiplier=750,
                                    bgp_route_import_file_path="ipv4_routes_ebgp_enhanced.csv",
                                    import_file_type=ixia_types.BgpRouteImportFileType.CSV,
                                    network_group_index=0,
                                    bgp_attribute_configs=[
                                        ixia_types.BgpAttributeConfig(
                                            attribute=ixia_types.BgpAttribute.COMMUNITIES,
                                            file_path="ipv4_routes_ebgp_communities_enhanced.csv",
                                            distribution_type=ixia_types.DistribitionType.ROUND_ROBIN,
                                        )
                                    ],
                                )
                            ],
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_name="DEVICE_GROUP_IPV4_EBGP_DRAIN",
                        device_group_index=3,
                        multiplier=ebgp_peer_to_drain,
                        v4_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_ebgp_ic_parent_network_v4}.11",
                            increment_ip="0.0.0.2",
                            gateway_starting_ip=f"{ixia_ebgp_ic_parent_network_v4}.10",
                            gateway_increment_ip="0.0.0.2",
                            mask=31,
                            start_index=ebgp_peer_count_v4 - ebgp_peer_to_drain,
                        ),
                        v4_bgp_config=BgpConfig(
                            bgp_peer_name="BGP_PEER_IPV4_EBGP_DRAIN",
                            local_as_4_bytes=ebgp_remote_as,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                            bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                            import_bgp_routes_params_list=[
                                ixia_types.ImportBgpRoutesParams(
                                    prefix_pool_name="PREFIX_POOL_IPV4_EBGP_DRAIN",
                                    multiplier=750,
                                    bgp_route_import_file_path="ipv4_routes_ebgp_enhanced.csv",
                                    import_file_type=ixia_types.BgpRouteImportFileType.CSV,
                                    network_group_index=0,
                                    bgp_attribute_configs=[
                                        ixia_types.BgpAttributeConfig(
                                            attribute=ixia_types.BgpAttribute.COMMUNITIES,
                                            file_path="ipv4_routes_ebgp_communities_enhanced.csv",
                                            distribution_type=ixia_types.DistribitionType.ROUND_ROBIN,
                                        )
                                    ],
                                    start_index=ebgp_peer_count_v4 - ebgp_peer_to_drain,
                                    end_index=ebgp_peer_count_v4,  # non-inclusive
                                )
                            ],
                        ),
                    ),
                ],
            ),
            BasicPortConfig(
                endpoint=f"{device_name}:{ixia_interface_mimic_ibgp}",
                device_group_configs=[
                    DeviceGroupConfig(
                        device_group_name="DEVICE_GROUP_IPV6_IBGP_PLANE_1",
                        device_group_index=0,
                        multiplier=ibgp_peer_scale_per_plane
                        - ibgp_peer_to_drain_per_plane,
                        v6_addresses_config=IpAddressesConfig(
                            starting_ip=f"{ixia_ibgp_ic_parent_network_v6_dc_plane1}::11",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v6_dc_plane1}::10",
                            gateway_increment_ip="0:0:0:0::2",
                            start_index=0,
                        ),
                        v6_bgp_config=BgpConfig(
                            bgp_peer_name="BGP_PEER_IPV6_IBGP_PLANE_1",
                            local_as_4_bytes=ibgp_remote_as,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                            import_bgp_routes_params_list=[
                                ixia_types.ImportBgpRoutesParams(
                                    multiplier=750,
                                    bgp_route_import_file_path="ipv6_routes_plane_1_enhanced.csv",
                                    import_file_type=ixia_types.BgpRouteImportFileType.CSV,
                                    network_group_index=0,
                                    bgp_attribute_configs=[
                                        ixia_types.BgpAttributeConfig(
                                            attribute=ixia_types.BgpAttribute.COMMUNITIES,
                                            file_path="ipv6_routes_communities_plane_1_enhanced.csv",
                                            distribution_type=ixia_types.DistribitionType.ROUND_ROBIN,
                                        )
                                    ],
                                    prefix_pool_name="PREFIX_POOL_IBGP_IPV6_PLANE_1",
                                    start_index=0,
                                    end_index=ibgp_peer_scale_per_plane
                                    - ibgp_peer_to_drain_per_plane,
                                )
                            ],
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_name="DEVICE_GROUP_IPV6_IBGP_PLANE_1_DRAIN",
                        device_group_index=1,
                        multiplier=ibgp_peer_to_drain_per_plane,
                        v6_addresses_config=IpAddressesConfig(
                            starting_ip=f"{ixia_ibgp_ic_parent_network_v6_dc_plane1}::11",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v6_dc_plane1}::10",
                            gateway_increment_ip="0:0:0:0::2",
                            start_index=ibgp_peer_scale_per_plane
                            - ibgp_peer_to_drain_per_plane,
                        ),
                        v6_bgp_config=BgpConfig(
                            bgp_peer_name="BGP_PEER_IPV6_IBGP_PLANE_1_DRAIN",
                            local_as_4_bytes=ibgp_remote_as,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                            import_bgp_routes_params_list=[
                                ixia_types.ImportBgpRoutesParams(
                                    multiplier=750,
                                    bgp_route_import_file_path="ipv6_routes_plane_1_enhanced.csv",
                                    import_file_type=ixia_types.BgpRouteImportFileType.CSV,
                                    network_group_index=0,
                                    bgp_attribute_configs=[
                                        ixia_types.BgpAttributeConfig(
                                            attribute=ixia_types.BgpAttribute.COMMUNITIES,
                                            file_path="ipv6_routes_communities_plane_1_enhanced.csv",
                                            distribution_type=ixia_types.DistribitionType.ROUND_ROBIN,
                                        )
                                    ],
                                    prefix_pool_name="PREFIX_POOL_IBGP_IPV6_PLANE_1_DRAIN",
                                    start_index=ibgp_peer_scale_per_plane
                                    - ibgp_peer_to_drain_per_plane,
                                    end_index=ibgp_peer_scale_per_plane,  # non-inclusive
                                )
                            ],
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_index=2,
                        device_group_name="DEVICE_GROUP_IPV6_IBGP_PLANE_2",
                        multiplier=ibgp_peer_scale_per_plane
                        - ibgp_peer_to_drain_per_plane,
                        v6_addresses_config=IpAddressesConfig(
                            starting_ip=f"{ixia_ibgp_ic_parent_network_v6_dc_plane2}::11",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v6_dc_plane2}::10",
                            gateway_increment_ip="0:0:0:0::2",
                            start_index=0,
                        ),
                        v6_bgp_config=BgpConfig(
                            bgp_peer_name="BGP_PEER_IPV6_IBGP_PLANE_2",
                            local_as_4_bytes=ibgp_remote_as,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                            import_bgp_routes_params_list=[
                                ixia_types.ImportBgpRoutesParams(
                                    multiplier=750,
                                    bgp_route_import_file_path="ipv6_routes_plane_2_enhanced.csv",
                                    import_file_type=ixia_types.BgpRouteImportFileType.CSV,
                                    network_group_index=0,
                                    bgp_attribute_configs=[
                                        ixia_types.BgpAttributeConfig(
                                            attribute=ixia_types.BgpAttribute.COMMUNITIES,
                                            file_path="ipv6_routes_communities_plane_2_enhanced.csv",
                                            distribution_type=ixia_types.DistribitionType.ROUND_ROBIN,
                                        )
                                    ],
                                    prefix_pool_name="PREFIX_POOL_IBGP_IPV6_PLANE_2",
                                    start_index=0,
                                    end_index=ibgp_peer_scale_per_plane
                                    - ibgp_peer_to_drain_per_plane,
                                )
                            ],
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_index=3,
                        device_group_name="DEVICE_GROUP_IPV6_IBGP_PLANE_2_DRAIN",
                        multiplier=ibgp_peer_to_drain_per_plane,
                        v6_addresses_config=IpAddressesConfig(
                            starting_ip=f"{ixia_ibgp_ic_parent_network_v6_dc_plane2}::11",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v6_dc_plane2}::10",
                            gateway_increment_ip="0:0:0:0::2",
                            start_index=ibgp_peer_scale_per_plane
                            - ibgp_peer_to_drain_per_plane,
                        ),
                        v6_bgp_config=BgpConfig(
                            bgp_peer_name="BGP_PEER_IPV6_IBGP_PLANE_2_DRAIN",
                            local_as_4_bytes=ibgp_remote_as,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                            import_bgp_routes_params_list=[
                                ixia_types.ImportBgpRoutesParams(
                                    multiplier=750,
                                    bgp_route_import_file_path="ipv6_routes_plane_2_enhanced.csv",
                                    import_file_type=ixia_types.BgpRouteImportFileType.CSV,
                                    network_group_index=0,
                                    bgp_attribute_configs=[
                                        ixia_types.BgpAttributeConfig(
                                            attribute=ixia_types.BgpAttribute.COMMUNITIES,
                                            file_path="ipv6_routes_communities_plane_2_enhanced.csv",
                                            distribution_type=ixia_types.DistribitionType.ROUND_ROBIN,
                                        )
                                    ],
                                    prefix_pool_name="PREFIX_POOL_IBGP_IPV6_PLANE_2_DRAIN",
                                    start_index=ibgp_peer_scale_per_plane
                                    - ibgp_peer_to_drain_per_plane,
                                    end_index=ibgp_peer_scale_per_plane,  # non-inclusive
                                )
                            ],
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_index=4,
                        device_group_name="DEVICE_GROUP_IPV6_IBGP_PLANE_3",
                        multiplier=ibgp_peer_scale_per_plane
                        - ibgp_peer_to_drain_per_plane,
                        v6_addresses_config=IpAddressesConfig(
                            starting_ip=f"{ixia_ibgp_ic_parent_network_v6_dc_plane3}::11",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v6_dc_plane3}::10",
                            gateway_increment_ip="0:0:0:0::2",
                            start_index=0,
                        ),
                        v6_bgp_config=BgpConfig(
                            bgp_peer_name="BGP_PEER_IPV6_IBGP_PLANE_3",
                            local_as_4_bytes=ibgp_remote_as,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                            import_bgp_routes_params_list=[
                                ixia_types.ImportBgpRoutesParams(
                                    multiplier=750,
                                    bgp_route_import_file_path="ipv6_routes_plane_3_enhanced.csv",
                                    import_file_type=ixia_types.BgpRouteImportFileType.CSV,
                                    network_group_index=0,
                                    bgp_attribute_configs=[
                                        ixia_types.BgpAttributeConfig(
                                            attribute=ixia_types.BgpAttribute.COMMUNITIES,
                                            file_path="ipv6_routes_communities_plane_3_enhanced.csv",
                                            distribution_type=ixia_types.DistribitionType.ROUND_ROBIN,
                                        )
                                    ],
                                    prefix_pool_name="PREFIX_POOL_IBGP_IPV6_PLANE_3",
                                    start_index=0,
                                    end_index=ibgp_peer_scale_per_plane
                                    - ibgp_peer_to_drain_per_plane,
                                )
                            ],
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_index=5,
                        device_group_name="DEVICE_GROUP_IPV6_IBGP_PLANE_3_DRAIN",
                        multiplier=ibgp_peer_to_drain_per_plane,
                        v6_addresses_config=IpAddressesConfig(
                            starting_ip=f"{ixia_ibgp_ic_parent_network_v6_dc_plane3}::11",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v6_dc_plane3}::10",
                            gateway_increment_ip="0:0:0:0::2",
                            start_index=ibgp_peer_scale_per_plane
                            - ibgp_peer_to_drain_per_plane,
                        ),
                        v6_bgp_config=BgpConfig(
                            bgp_peer_name="BGP_PEER_IPV6_IBGP_PLANE_3_DRAIN",
                            local_as_4_bytes=ibgp_remote_as,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                            import_bgp_routes_params_list=[
                                ixia_types.ImportBgpRoutesParams(
                                    multiplier=750,
                                    bgp_route_import_file_path="ipv6_routes_plane_3_enhanced.csv",
                                    import_file_type=ixia_types.BgpRouteImportFileType.CSV,
                                    network_group_index=0,
                                    bgp_attribute_configs=[
                                        ixia_types.BgpAttributeConfig(
                                            attribute=ixia_types.BgpAttribute.COMMUNITIES,
                                            file_path="ipv6_routes_communities_plane_3_enhanced.csv",
                                            distribution_type=ixia_types.DistribitionType.ROUND_ROBIN,
                                        )
                                    ],
                                    prefix_pool_name="PREFIX_POOL_IBGP_IPV6_PLANE_3_DRAIN",
                                    start_index=ibgp_peer_scale_per_plane
                                    - ibgp_peer_to_drain_per_plane,
                                    end_index=ibgp_peer_scale_per_plane,  # non-inclusive
                                )
                            ],
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_index=6,
                        device_group_name="DEVICE_GROUP_IPV6_IBGP_PLANE_4",
                        multiplier=ibgp_peer_scale_per_plane
                        - ibgp_peer_to_drain_per_plane,
                        v6_addresses_config=IpAddressesConfig(
                            starting_ip=f"{ixia_ibgp_ic_parent_network_v6_dc_plane4}::11",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v6_dc_plane4}::10",
                            gateway_increment_ip="0:0:0:0::2",
                            start_index=0,
                        ),
                        v6_bgp_config=BgpConfig(
                            bgp_peer_name="BGP_PEER_IPV6_IBGP_PLANE_4",
                            local_as_4_bytes=ibgp_remote_as,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                            import_bgp_routes_params_list=[
                                ixia_types.ImportBgpRoutesParams(
                                    multiplier=750,
                                    bgp_route_import_file_path="ipv6_routes_plane_4_enhanced.csv",
                                    import_file_type=ixia_types.BgpRouteImportFileType.CSV,
                                    network_group_index=0,
                                    bgp_attribute_configs=[
                                        ixia_types.BgpAttributeConfig(
                                            attribute=ixia_types.BgpAttribute.COMMUNITIES,
                                            file_path="ipv6_routes_communities_plane_4_enhanced.csv",
                                            distribution_type=ixia_types.DistribitionType.ROUND_ROBIN,
                                        )
                                    ],
                                    prefix_pool_name="PREFIX_POOL_IBGP_IPV6_PLANE_4",
                                    start_index=0,
                                    end_index=ibgp_peer_scale_per_plane
                                    - ibgp_peer_to_drain_per_plane,
                                )
                            ],
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_index=7,
                        device_group_name="DEVICE_GROUP_IPV6_IBGP_PLANE_4_DRAIN",
                        multiplier=ibgp_peer_to_drain_per_plane,
                        v6_addresses_config=IpAddressesConfig(
                            starting_ip=f"{ixia_ibgp_ic_parent_network_v6_dc_plane4}::11",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v6_dc_plane4}::10",
                            gateway_increment_ip="0:0:0:0::2",
                            start_index=ibgp_peer_scale_per_plane
                            - ibgp_peer_to_drain_per_plane,
                        ),
                        v6_bgp_config=BgpConfig(
                            bgp_peer_name="BGP_PEER_IPV6_IBGP_PLANE_4_DRAIN",
                            local_as_4_bytes=ibgp_remote_as,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                            import_bgp_routes_params_list=[
                                ixia_types.ImportBgpRoutesParams(
                                    multiplier=750,
                                    bgp_route_import_file_path="ipv6_routes_plane_4_enhanced.csv",
                                    import_file_type=ixia_types.BgpRouteImportFileType.CSV,
                                    network_group_index=0,
                                    bgp_attribute_configs=[
                                        ixia_types.BgpAttributeConfig(
                                            attribute=ixia_types.BgpAttribute.COMMUNITIES,
                                            file_path="ipv6_routes_communities_plane_4_enhanced.csv",
                                            distribution_type=ixia_types.DistribitionType.ROUND_ROBIN,
                                        )
                                    ],
                                    prefix_pool_name="PREFIX_POOL_IBGP_IPV6_PLANE_4_DRAIN",
                                    start_index=ibgp_peer_scale_per_plane
                                    - ibgp_peer_to_drain_per_plane,
                                    end_index=ibgp_peer_scale_per_plane,  # non-inclusive
                                )
                            ],
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_index=8,
                        multiplier=ibgp_peer_scale_per_plane,
                        v6_addresses_config=IpAddressesConfig(
                            starting_ip=f"{ixia_ibgp_ic_parent_network_v6_mp_plane1}::11",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v6_mp_plane1}::10",
                            gateway_increment_ip="0:0:0:0::2",
                        ),
                        v6_bgp_config=BgpConfig(
                            local_as_4_bytes=ibgp_remote_as,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_index=9,
                        multiplier=ibgp_peer_scale_per_plane,
                        v6_addresses_config=IpAddressesConfig(
                            starting_ip=f"{ixia_ibgp_ic_parent_network_v6_mp_plane2}::11",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v6_mp_plane2}::10",
                            gateway_increment_ip="0:0:0:0::2",
                        ),
                        v6_bgp_config=BgpConfig(
                            local_as_4_bytes=ibgp_remote_as,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_index=10,
                        multiplier=ibgp_peer_scale_per_plane,
                        v6_addresses_config=IpAddressesConfig(
                            starting_ip=f"{ixia_ibgp_ic_parent_network_v6_mp_plane3}::11",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v6_mp_plane3}::10",
                            gateway_increment_ip="0:0:0:0::2",
                        ),
                        v6_bgp_config=BgpConfig(
                            local_as_4_bytes=ibgp_remote_as,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_index=11,
                        multiplier=ibgp_peer_scale_per_plane,
                        v6_addresses_config=IpAddressesConfig(
                            starting_ip=f"{ixia_ibgp_ic_parent_network_v6_mp_plane4}::11",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v6_mp_plane4}::10",
                            gateway_increment_ip="0:0:0:0::2",
                        ),
                        v6_bgp_config=BgpConfig(
                            local_as_4_bytes=ibgp_remote_as,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_index=12,
                        device_group_name="DEVICE_GROUP_IPV4_IBGP_PLANE_1",
                        multiplier=ibgp_peer_scale_per_plane
                        - ibgp_peer_to_drain_per_plane,
                        v4_addresses_config=IpAddressesConfig(
                            starting_ip=f"{ixia_ibgp_ic_parent_network_v4_dc_plane1}.11",
                            increment_ip="0.0.0.2",
                            gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v4_dc_plane1}.10",
                            gateway_increment_ip="0.0.0.2",
                            mask=31,
                            start_index=0,
                        ),
                        v4_bgp_config=BgpConfig(
                            local_as_4_bytes=ibgp_remote_as,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                            bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                            import_bgp_routes_params_list=[
                                ixia_types.ImportBgpRoutesParams(
                                    multiplier=750,
                                    bgp_route_import_file_path="ipv4_routes_plane_1_enhanced.csv",
                                    import_file_type=ixia_types.BgpRouteImportFileType.CSV,
                                    network_group_index=0,
                                    bgp_attribute_configs=[
                                        ixia_types.BgpAttributeConfig(
                                            attribute=ixia_types.BgpAttribute.COMMUNITIES,
                                            file_path="ipv4_routes_communities_plane_1_enhanced.csv",
                                            distribution_type=ixia_types.DistribitionType.ROUND_ROBIN,
                                        )
                                    ],
                                    prefix_pool_name="PREFIX_POOL_IBGP_IPV4_PLANE_1",
                                    start_index=0,
                                    end_index=ibgp_peer_scale_per_plane
                                    - ibgp_peer_to_drain_per_plane,
                                )
                            ],
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_index=13,
                        device_group_name="DEVICE_GROUP_IPV4_IBGP_PLANE_1_DRAIN",
                        multiplier=ibgp_peer_to_drain_per_plane,
                        v4_addresses_config=IpAddressesConfig(
                            starting_ip=f"{ixia_ibgp_ic_parent_network_v4_dc_plane1}.11",
                            increment_ip="0.0.0.2",
                            gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v4_dc_plane1}.10",
                            gateway_increment_ip="0.0.0.2",
                            mask=31,
                            start_index=ibgp_peer_scale_per_plane
                            - ibgp_peer_to_drain_per_plane,
                        ),
                        v4_bgp_config=BgpConfig(
                            local_as_4_bytes=ibgp_remote_as,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                            bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                            import_bgp_routes_params_list=[
                                ixia_types.ImportBgpRoutesParams(
                                    multiplier=750,
                                    bgp_route_import_file_path="ipv4_routes_plane_1_enhanced.csv",
                                    import_file_type=ixia_types.BgpRouteImportFileType.CSV,
                                    network_group_index=0,
                                    bgp_attribute_configs=[
                                        ixia_types.BgpAttributeConfig(
                                            attribute=ixia_types.BgpAttribute.COMMUNITIES,
                                            file_path="ipv4_routes_communities_plane_1_enhanced.csv",
                                            distribution_type=ixia_types.DistribitionType.ROUND_ROBIN,
                                        )
                                    ],
                                    prefix_pool_name="PREFIX_POOL_IBGP_IPV4_PLANE_1_DRAIN",
                                    start_index=ibgp_peer_scale_per_plane
                                    - ibgp_peer_to_drain_per_plane,
                                    end_index=ibgp_peer_scale_per_plane,  # non-inclusive
                                )
                            ],
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_index=14,
                        device_group_name="DEVICE_GROUP_IPV4_IBGP_PLANE_2",
                        multiplier=ibgp_peer_scale_per_plane
                        - ibgp_peer_to_drain_per_plane,
                        v4_addresses_config=IpAddressesConfig(
                            starting_ip=f"{ixia_ibgp_ic_parent_network_v4_dc_plane2}.11",
                            increment_ip="0.0.0.2",
                            gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v4_dc_plane2}.10",
                            gateway_increment_ip="0.0.0.2",
                            mask=31,
                            start_index=0,
                        ),
                        v4_bgp_config=BgpConfig(
                            local_as_4_bytes=ibgp_remote_as,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                            bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                            import_bgp_routes_params_list=[
                                ixia_types.ImportBgpRoutesParams(
                                    multiplier=750,
                                    bgp_route_import_file_path="ipv4_routes_plane_2_enhanced.csv",
                                    import_file_type=ixia_types.BgpRouteImportFileType.CSV,
                                    network_group_index=0,
                                    bgp_attribute_configs=[
                                        ixia_types.BgpAttributeConfig(
                                            attribute=ixia_types.BgpAttribute.COMMUNITIES,
                                            file_path="ipv4_routes_communities_plane_2_enhanced.csv",
                                            distribution_type=ixia_types.DistribitionType.ROUND_ROBIN,
                                        )
                                    ],
                                    prefix_pool_name="PREFIX_POOL_IBGP_IPV4_PLANE_2",
                                    start_index=0,
                                    end_index=ibgp_peer_scale_per_plane
                                    - ibgp_peer_to_drain_per_plane,
                                )
                            ],
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_index=15,
                        device_group_name="DEVICE_GROUP_IPV4_IBGP_PLANE_2_DRAIN",
                        multiplier=ibgp_peer_to_drain_per_plane,
                        v4_addresses_config=IpAddressesConfig(
                            starting_ip=f"{ixia_ibgp_ic_parent_network_v4_dc_plane2}.11",
                            increment_ip="0.0.0.2",
                            gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v4_dc_plane2}.10",
                            gateway_increment_ip="0.0.0.2",
                            mask=31,
                            start_index=ibgp_peer_scale_per_plane
                            - ibgp_peer_to_drain_per_plane,
                        ),
                        v4_bgp_config=BgpConfig(
                            local_as_4_bytes=ibgp_remote_as,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                            bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                            import_bgp_routes_params_list=[
                                ixia_types.ImportBgpRoutesParams(
                                    multiplier=750,
                                    bgp_route_import_file_path="ipv4_routes_plane_2_enhanced.csv",
                                    import_file_type=ixia_types.BgpRouteImportFileType.CSV,
                                    network_group_index=0,
                                    bgp_attribute_configs=[
                                        ixia_types.BgpAttributeConfig(
                                            attribute=ixia_types.BgpAttribute.COMMUNITIES,
                                            file_path="ipv4_routes_communities_plane_2_enhanced.csv",
                                            distribution_type=ixia_types.DistribitionType.ROUND_ROBIN,
                                        )
                                    ],
                                    prefix_pool_name="PREFIX_POOL_IBGP_IPV4_PLANE_2_DRAIN",
                                    start_index=ibgp_peer_scale_per_plane
                                    - ibgp_peer_to_drain_per_plane,
                                    end_index=ibgp_peer_scale_per_plane,
                                )
                            ],
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_index=16,
                        device_group_name="DEVICE_GROUP_IPV4_IBGP_PLANE_3",
                        multiplier=ibgp_peer_scale_per_plane
                        - ibgp_peer_to_drain_per_plane,
                        v4_addresses_config=IpAddressesConfig(
                            starting_ip=f"{ixia_ibgp_ic_parent_network_v4_dc_plane3}.11",
                            increment_ip="0.0.0.2",
                            gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v4_dc_plane3}.10",
                            gateway_increment_ip="0.0.0.2",
                            mask=31,
                            start_index=0,
                        ),
                        v4_bgp_config=BgpConfig(
                            local_as_4_bytes=ibgp_remote_as,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                            bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                            import_bgp_routes_params_list=[
                                ixia_types.ImportBgpRoutesParams(
                                    multiplier=750,
                                    bgp_route_import_file_path="ipv4_routes_plane_3_enhanced.csv",
                                    import_file_type=ixia_types.BgpRouteImportFileType.CSV,
                                    network_group_index=0,
                                    bgp_attribute_configs=[
                                        ixia_types.BgpAttributeConfig(
                                            attribute=ixia_types.BgpAttribute.COMMUNITIES,
                                            file_path="ipv4_routes_communities_plane_3_enhanced.csv",
                                            distribution_type=ixia_types.DistribitionType.ROUND_ROBIN,
                                        )
                                    ],
                                    prefix_pool_name="PREFIX_POOL_IBGP_IPV4_PLANE_3",
                                    start_index=0,
                                    end_index=ibgp_peer_scale_per_plane
                                    - ibgp_peer_to_drain_per_plane,
                                )
                            ],
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_index=17,
                        device_group_name="DEVICE_GROUP_IPV4_IBGP_PLANE_3_DRAIN",
                        multiplier=ibgp_peer_to_drain_per_plane,
                        v4_addresses_config=IpAddressesConfig(
                            starting_ip=f"{ixia_ibgp_ic_parent_network_v4_dc_plane3}.11",
                            increment_ip="0.0.0.2",
                            gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v4_dc_plane3}.10",
                            gateway_increment_ip="0.0.0.2",
                            mask=31,
                            start_index=ibgp_peer_scale_per_plane
                            - ibgp_peer_to_drain_per_plane,
                        ),
                        v4_bgp_config=BgpConfig(
                            local_as_4_bytes=ibgp_remote_as,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                            bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                            import_bgp_routes_params_list=[
                                ixia_types.ImportBgpRoutesParams(
                                    multiplier=750,
                                    bgp_route_import_file_path="ipv4_routes_plane_3_enhanced.csv",
                                    import_file_type=ixia_types.BgpRouteImportFileType.CSV,
                                    network_group_index=0,
                                    bgp_attribute_configs=[
                                        ixia_types.BgpAttributeConfig(
                                            attribute=ixia_types.BgpAttribute.COMMUNITIES,
                                            file_path="ipv4_routes_communities_plane_3_enhanced.csv",
                                            distribution_type=ixia_types.DistribitionType.ROUND_ROBIN,
                                        )
                                    ],
                                    prefix_pool_name="PREFIX_POOL_IBGP_IPV4_PLANE_3_DRAIN",
                                    end_index=ibgp_peer_scale_per_plane,
                                    start_index=ibgp_peer_scale_per_plane
                                    - ibgp_peer_to_drain_per_plane,
                                )
                            ],
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_index=18,
                        device_group_name="DEVICE_GROUP_IPV4_IBGP_PLANE_4",
                        multiplier=ibgp_peer_scale_per_plane
                        - ibgp_peer_to_drain_per_plane,
                        v4_addresses_config=IpAddressesConfig(
                            starting_ip=f"{ixia_ibgp_ic_parent_network_v4_dc_plane4}.11",
                            increment_ip="0.0.0.2",
                            gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v4_dc_plane4}.10",
                            gateway_increment_ip="0.0.0.2",
                            mask=31,
                            start_index=0,
                        ),
                        v4_bgp_config=BgpConfig(
                            local_as_4_bytes=ibgp_remote_as,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                            bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                            import_bgp_routes_params_list=[
                                ixia_types.ImportBgpRoutesParams(
                                    multiplier=750,
                                    bgp_route_import_file_path="ipv4_routes_plane_4_enhanced.csv",
                                    import_file_type=ixia_types.BgpRouteImportFileType.CSV,
                                    network_group_index=0,
                                    bgp_attribute_configs=[
                                        ixia_types.BgpAttributeConfig(
                                            attribute=ixia_types.BgpAttribute.COMMUNITIES,
                                            file_path="ipv4_routes_communities_plane_4_enhanced.csv",
                                            distribution_type=ixia_types.DistribitionType.ROUND_ROBIN,
                                        )
                                    ],
                                    prefix_pool_name="PREFIX_POOL_IBGP_IPV4_PLANE_4",
                                    start_index=0,
                                    end_index=ibgp_peer_scale_per_plane
                                    - ibgp_peer_to_drain_per_plane,
                                )
                            ],
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_index=19,
                        device_group_name="DEVICE_GROUP_IPV4_IBGP_PLANE_4_DRAIN",
                        multiplier=ibgp_peer_to_drain_per_plane,
                        v4_addresses_config=IpAddressesConfig(
                            starting_ip=f"{ixia_ibgp_ic_parent_network_v4_dc_plane4}.11",
                            increment_ip="0.0.0.2",
                            gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v4_dc_plane4}.10",
                            gateway_increment_ip="0.0.0.2",
                            mask=31,
                            start_index=ibgp_peer_scale_per_plane
                            - ibgp_peer_to_drain_per_plane,
                        ),
                        v4_bgp_config=BgpConfig(
                            local_as_4_bytes=ibgp_remote_as,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                            bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                            import_bgp_routes_params_list=[
                                ixia_types.ImportBgpRoutesParams(
                                    multiplier=750,
                                    bgp_route_import_file_path="ipv4_routes_plane_4_enhanced.csv",
                                    import_file_type=ixia_types.BgpRouteImportFileType.CSV,
                                    network_group_index=0,
                                    bgp_attribute_configs=[
                                        ixia_types.BgpAttributeConfig(
                                            attribute=ixia_types.BgpAttribute.COMMUNITIES,
                                            file_path="ipv4_routes_communities_plane_4_enhanced.csv",
                                            distribution_type=ixia_types.DistribitionType.ROUND_ROBIN,
                                        )
                                    ],
                                    prefix_pool_name="PREFIX_POOL_IBGP_IPV4_PLANE_4_DRAIN",
                                    end_index=ibgp_peer_scale_per_plane,
                                    start_index=ibgp_peer_scale_per_plane
                                    - ibgp_peer_to_drain_per_plane,
                                )
                            ],
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_index=20,
                        multiplier=ibgp_peer_scale_per_plane,
                        v4_addresses_config=IpAddressesConfig(
                            starting_ip=f"{ixia_ibgp_ic_parent_network_v4_mp_plane1}.11",
                            increment_ip="0.0.0.2",
                            gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v4_mp_plane1}.10",
                            gateway_increment_ip="0.0.0.2",
                            mask=31,
                        ),
                        v4_bgp_config=BgpConfig(
                            local_as_4_bytes=ibgp_remote_as,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                            bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_index=21,
                        multiplier=ibgp_peer_scale_per_plane,
                        v4_addresses_config=IpAddressesConfig(
                            starting_ip=f"{ixia_ibgp_ic_parent_network_v4_mp_plane2}.11",
                            increment_ip="0.0.0.2",
                            gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v4_mp_plane2}.10",
                            gateway_increment_ip="0.0.0.2",
                            mask=31,
                        ),
                        v4_bgp_config=BgpConfig(
                            local_as_4_bytes=ibgp_remote_as,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                            bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_index=22,
                        multiplier=ibgp_peer_scale_per_plane,
                        v4_addresses_config=IpAddressesConfig(
                            starting_ip=f"{ixia_ibgp_ic_parent_network_v4_mp_plane3}.11",
                            increment_ip="0.0.0.2",
                            gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v4_mp_plane3}.10",
                            gateway_increment_ip="0.0.0.2",
                            mask=31,
                        ),
                        v4_bgp_config=BgpConfig(
                            local_as_4_bytes=ibgp_remote_as,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                            bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_index=23,
                        multiplier=ibgp_peer_scale_per_plane,
                        v4_addresses_config=IpAddressesConfig(
                            starting_ip=f"{ixia_ibgp_ic_parent_network_v4_mp_plane4}.11",
                            increment_ip="0.0.0.2",
                            gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v4_mp_plane4}.10",
                            gateway_increment_ip="0.0.0.2",
                            mask=31,
                        ),
                        v4_bgp_config=BgpConfig(
                            local_as_4_bytes=ibgp_remote_as,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                            bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                        ),
                    ),
                ],
            ),
        ],
        # Deprecated - define at playbook level
        # prechecks=BGP_STANDARD_PRECHECKS,
        # snapshot_checks=BGP_STANDARD_SNAPSHOT_CHECKS,
        # postchecks=BGP_STANDARD_POSTCHECKS,
        playbooks=[
            build_ebb_scale_playbook(
                prechecks=BGP_STANDARD_PRECHECKS,
                postchecks=BGP_STANDARD_POSTCHECKS,
                snapshot_checks=BGP_STANDARD_SNAPSHOT_CHECKS,
                periodic_tasks=[
                    taac_types.PeriodicTask(
                        name="create_ixia_bgp_prefix_churn_every_10_minutes",
                        interval=600,
                        task=create_periodic_task_shell(
                            task_name="ixia_enable_disable_bgp_prefixes",
                        ),
                        params_list=[
                            Params(
                                json_params=json.dumps(
                                    {
                                        "prefix_pool_regex": ".*IBGP.*",
                                        "prefix_end_index": 25,
                                        "enable": False,
                                    }
                                ),
                            ),
                            Params(
                                json_params=json.dumps(
                                    {
                                        "prefix_pool_regex": ".*IBGP.*",
                                        "prefix_end_index": 25,
                                        "enable": True,
                                    }
                                ),
                            ),
                        ],
                    ),
                    taac_types.PeriodicTask(
                        name="randomize_ixia_bgp_prefix_local_preference_every_10_minutes",
                        interval=600,
                        task=create_ixia_randomize_bgp_prefix_local_preference_task(
                            prefix_pool_regex=".*IBGP.*",
                            prefix_start_index=25,
                            prefix_end_index=50,
                            start_value=90,
                            end_value=121,
                        ),
                    ),
                    taac_types.PeriodicTask(
                        name="fluctuate_ixia_bgp_prefix_origin_every_10_minutes",
                        interval=600,
                        task=create_periodic_task_shell(
                            task_name="ixia_modify_bgp_prefixes_origin_value",
                        ),
                        params_list=[
                            Params(
                                json_params=json.dumps(
                                    {
                                        "prefix_pool_regex": ".*IBGP.*",
                                        "prefix_start_index": 50,
                                        "prefix_end_index": 75,
                                        "origin_value": "incomplete",
                                    }
                                ),
                            ),
                            Params(
                                json_params=json.dumps(
                                    {
                                        "prefix_pool_regex": ".*IBGP.*",
                                        "prefix_start_index": 50,
                                        "prefix_end_index": 75,
                                        "origin_value": "igp",
                                    }
                                ),
                            ),
                        ],
                    ),
                    taac_types.PeriodicTask(
                        name="drain_undrain_ixia_bgp_peers_every_60_minutes",
                        interval=3600,  # 60 minutes
                        task=create_periodic_task_shell(
                            task_name="ixia_drain_undrain_bgp_peers",
                            ixia_needed=True,
                        ),
                        params_list=[
                            Params(
                                json_params=json.dumps(
                                    {"prefix_pool_regex": ".*DRAIN.*", "drain": True}
                                ),
                            ),
                            Params(
                                json_params=json.dumps(
                                    {"prefix_pool_regex": ".*DRAIN.*", "drain": False}
                                ),
                            ),
                        ],
                    ),
                    taac_types.PeriodicTask(
                        name="restart_ibgp_bgp_sessions_every_hour",
                        task=create_ixia_restart_bgp_sessions_task(
                            bgp_peer_regex=r"\b(?!\w*DRAIN\w*)\w*IBGP\w*\b",
                            random_session_num=2,
                        ),
                        interval=3600,  # 60 minutes
                    ),
                    taac_types.PeriodicTask(
                        name="restart_ebgp_bgp_sessions_every_hour",
                        task=create_ixia_restart_bgp_sessions_task(
                            bgp_peer_regex=r"\b(?!\w*DRAIN\w*)\w*EBGP\w*\b",
                            random_session_num=4,
                        ),
                        interval=3600,  # 60 minutes
                    ),
                ],
                name="test_300000_min_longevity",
                stages=[
                    create_steps_stage(
                        steps=[create_longevity_step(duration=18000)],
                    )
                ],
            ),
            test_bgpd_restart(
                bgpd_restart_no_of_interations,
                prechecks=BGP_STANDARD_PRECHECKS,
                postchecks=BGP_STANDARD_POSTCHECKS,
                snapshot_checks=BGP_STANDARD_SNAPSHOT_CHECKS,
            ),
            test_bgpd_coldboot(
                prechecks=BGP_STANDARD_PRECHECKS,
                postchecks=BGP_STANDARD_POSTCHECKS,
                snapshot_checks=BGP_STANDARD_SNAPSHOT_CHECKS,
            ),
            test_bgpd_stability_endurance(
                prechecks=BGP_STANDARD_PRECHECKS,
                postchecks=BGP_STANDARD_POSTCHECKS,
                snapshot_checks=BGP_STANDARD_SNAPSHOT_CHECKS,
            ),
            build_ebb_scale_playbook(
                name="test_72hr_longevity",
                prechecks=BGP_STANDARD_PRECHECKS,
                postchecks=BGP_STANDARD_POSTCHECKS,
                snapshot_checks=BGP_STANDARD_SNAPSHOT_CHECKS,
                stages=[
                    create_steps_stage(
                        steps=[create_longevity_step(duration=259200)],
                    )
                ],
            ),
        ],
    )
