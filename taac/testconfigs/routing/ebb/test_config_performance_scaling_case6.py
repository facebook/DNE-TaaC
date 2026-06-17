# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Arista BGP++ performance scaling test case 6: route churn.

Builds TestConfigs that exercise Arista BGP++ under sustained route churn:
IXIA peers repeatedly advertise and withdraw prefixes while DUT memory,
CPU, RIB/FIB consistency, and BGP convergence are sampled. Provides both
a fixed-peer churn config (`test_config_for_bgp_plus_plus_on_ebb_arista_route_churn`)
and a prefix-scaling churn variant (`test_config_for_route_churn_prefix_scaling`).
"""

import typing as t

from taac.constants import Gigabyte
from taac.health_checks.healthcheck_definitions import (
    create_bgp_convergence_check,
    create_bgp_rib_fib_consistency_check,
    create_bgp_session_establish_check,
    create_bgp_session_snapshot_check,
    create_core_dumps_snapshot_check,
)
from taac.playbooks.playbook_definitions import (
    build_case6_playbook,
)
from taac.routing.ebb.arista_bgp_plus_plus_performance_scaling_tests.ixia_configs_for_tests import (
    create_ebb_route_churn_test_basic_port_configs,
)
from taac.routing.ebb.ebb_bgp_plus_plus_test_config.common_periodic_tasks import (
    create_standard_periodic_tasks,
)
from taac.stages.stage_definitions import (
    create_bgp_restart_test_stage,
    create_steps_stage,
)
from taac.steps.step_definitions import (
    create_custom_step,
    create_ixia_api_step,
    create_ixia_packet_capture_step,
    create_longevity_step,
)
from taac.task_definitions import (
    create_configure_bgpcpp_startup_task,
    create_replace_bgp_peers_task,
    create_run_commands_on_shell_task,
)
from taac.test_as_a_config.types import Endpoint, TestConfig


def test_config_for_bgp_plus_plus_on_ebb_arista_route_churn(
    test_config_name: str,
    device_name: str,
    ixia_interface_mimic_ebgp: str,
    ixia_interface_mimic_ibgp: str,
    ebgp_peer_count: int,
    ibgp_peer_count: int,
    ebgp_remote_as: int,
    ibgp_remote_as: int,
    ixia_ebgp_ic_parent_network_v6: str,
    ixia_ibgp_ic_parent_network_v6: str,
    direct_ixia_connections: list,
    prefixes: int,
    churn_count: int,
    initial_convergence_time_seconds: int = 600,
    log_collection_timeout=None,
    oss_mock_device_data=None,
    host_os_type_map=None,
    host_driver_args=None,
    # Dynamic peer configuration (optional)
    ssh_user: str | None = None,
    ssh_password: str | None = None,
    peergroup_ebgp_v6: str = "EB-FA-V6",
    peergroup_ibgp_v6: str = "EB-EB-V6",
):
    """Build the case-6 (route churn) BGP++ TestConfig at a fixed peer count.

    Configures EBGP + IBGP peer groups via bgpcpp dynamic peer replacement
    (or a static configerator config when `ssh_user`/`ssh_password` are not
    supplied), then runs `build_case6_playbook` which churns `churn_count`
    iterations of advertise/withdraw on `prefixes` routes. Used to verify
    that BGP++ memory and CPU stay bounded under sustained route churn.

    Args:
        test_config_name: Final name of the produced TestConfig.
        device_name: DUT hostname (Arista EBB).
        ixia_interface_mimic_ebgp / ixia_interface_mimic_ibgp: IXIA port
            names used as EBGP/IBGP peer endpoints.
        ebgp_peer_count / ibgp_peer_count: Per-AFI peer counts (v6 only).
        ebgp_remote_as / ibgp_remote_as: Remote ASNs.
        ixia_ebgp_ic_parent_network_v6 / ixia_ibgp_ic_parent_network_v6:
            Parent networks for IXIA-side prefix generation.
        direct_ixia_connections: Optional direct IXIA-port connection list.
        prefixes: Prefix count to churn per iteration.
        churn_count: Number of advertise/withdraw cycles.
        initial_convergence_time_seconds: Wait between peer-up and the
            first churn iteration.
        log_collection_timeout / oss_mock_device_data / host_os_type_map /
        host_driver_args: Optional overrides for OSS harness wiring.
        ssh_user / ssh_password: When both supplied, use dynamic bgpcpp peer
            replacement; otherwise copy a pre-baked configerator file.
        peergroup_ebgp_v6 / peergroup_ibgp_v6: Peer-group names.

    Returns:
        TestConfig: The case-6 route-churn TestConfig (consumed via
        `testconfigs.routing.ebb`).
    """
    total_bgp_peers = ibgp_peer_count + ebgp_peer_count

    # Build setup_tasks based on whether dynamic peer config is provided
    if ssh_user is not None and ssh_password is not None:
        setup_tasks = [
            create_configure_bgpcpp_startup_task(
                hostname=device_name,
                flags={
                    "agent_thrift_recv_timeout_ms": "160000",
                },
                ssh_user=ssh_user,
                ssh_password=ssh_password,
            ),
            create_replace_bgp_peers_task(
                hostname=device_name,
                peer_configs=[
                    {
                        "peer_group_name": peergroup_ebgp_v6,
                        "remote_as": ebgp_remote_as,
                        "base_network": ixia_ebgp_ic_parent_network_v6,
                        "is_v6": True,
                        "peer_count": ebgp_peer_count,
                        "start_offset": 16,
                    },
                    {
                        "peer_group_name": peergroup_ibgp_v6,
                        "remote_as": ibgp_remote_as,
                        "base_network": ixia_ibgp_ic_parent_network_v6,
                        "is_v6": True,
                        "peer_count": ibgp_peer_count,
                        "start_offset": 16,
                    },
                ],
            ),
        ]
    else:
        setup_tasks = [
            create_run_commands_on_shell_task(
                hostname=device_name,
                cmds=[
                    f"bash sudo cp /mnt/flash/bgpcpp_config_test_case6_{total_bgp_peers}_total_bgp_peers /mnt/flash/bgpcpp_config"
                ],
            ),
        ]

    return TestConfig(
        name=test_config_name,
        skip_ixia_protocol_verification=True,
        log_collection_timeout=log_collection_timeout,
        basset_pool="dne.test",
        endpoints=[
            Endpoint(
                name=device_name,
                dut=True,
                ixia_ports=[ixia_interface_mimic_ebgp, ixia_interface_mimic_ibgp],
                direct_ixia_connections=(
                    direct_ixia_connections if direct_ixia_connections else []
                ),
            ),
        ],
        host_driver_args=host_driver_args,
        oss_mock_device_data=oss_mock_device_data,
        host_os_type_map=host_os_type_map,
        startup_checks=[],
        setup_tasks=setup_tasks,
        teardown_tasks=[],
        # Deprecated - define at playbook level
        # prechecks=[],
        # postchecks=[],
        # snapshot_checks=[],
        basic_port_configs=create_ebb_route_churn_test_basic_port_configs(
            device_name=device_name,
            ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
            ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
            ebgp_peer_count_v6=ebgp_peer_count,
            ibgp_peer_count_v6=ibgp_peer_count,
            ebgp_remote_as=ebgp_remote_as,
            ibgp_remote_as=ibgp_remote_as,
            initial_prefix_count=prefixes,
            churn_count=churn_count,
            ixia_ebgp_ic_parent_network_v6=ixia_ebgp_ic_parent_network_v6,
            ixia_ibgp_ic_parent_network_v6=ixia_ibgp_ic_parent_network_v6,
        ),
        playbooks=[
            build_case6_playbook(
                name="bgp_plus_plus_arista_route_churn_test",
                description="Test BGP++ Convergence time with route churn",
                snapshot_checks=[
                    create_core_dumps_snapshot_check(),
                    create_bgp_session_snapshot_check(
                        skip_flap_check=True, skip_uptime_check=True
                    ),
                ],
                periodic_tasks=create_standard_periodic_tasks(
                    device_name=device_name,
                    memory_threshold=Gigabyte.GIG_5.value,
                    cpu_util_terminate_on_error=False,
                    memory_terminate_on_error=False,
                ),
                prechecks=[],
                postchecks=[
                    create_bgp_session_establish_check(
                        expected_established_sessions_static=ibgp_peer_count
                        + ebgp_peer_count,
                        check_id="startup_bgp_session_verification",
                    ),
                    create_bgp_rib_fib_consistency_check(),
                    create_bgp_convergence_check(
                        convergence_threshold=700,
                        check_id="postcheck_bgp_convergence_time",
                    ),
                ],
                stages=[
                    create_steps_stage(
                        steps=[
                            create_ixia_api_step(
                                api_name="set_bgp_local_preference",
                                args_dict={
                                    "local_preference": 100,
                                    "prefix_pool_regex": ".*IPV6_IBGP.*",
                                },
                            ),
                        ]
                    ),
                    create_bgp_restart_test_stage(
                        device_name=device_name,
                        convergence_wait_seconds=initial_convergence_time_seconds,
                    ),
                    create_steps_stage(
                        steps=[
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_mimic_ebgp,
                                mode="start",
                                capture_id="arista_route_churn_ebgp",
                                description="Start IXIA packet capture for route churn - eBGP",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_mimic_ibgp,
                                mode="start",
                                capture_id="arista_route_churn_ibgp",
                                description="Start IXIA packet capture for route churn - iBGP",
                            ),
                            create_longevity_step(
                                duration=5,
                                description="Brief pause to ensure IXIA capture is ready - 5 seconds",
                            ),
                            create_ixia_api_step(
                                api_name="set_bgp_local_preference",
                                args_dict={
                                    "local_preference": 50,
                                    "prefix_pool_regex": ".*PEER_1_FIRST_100.*",
                                },
                            ),
                            create_longevity_step(
                                duration=600,
                                description="Soak after churn for 600 seconds",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_mimic_ebgp,
                                mode="stop",
                                capture_id="arista_route_churn_ebgp",
                                description="Stop IXIA packet capture for route churn - eBGP",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_mimic_ibgp,
                                mode="stop",
                                capture_id="arista_route_churn_ibgp",
                                description="Stop IXIA packet capture for route churn - iBGP",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_mimic_ebgp,
                                mode="save",
                                pcap_filename="bgp_arista_churn_ebgp.pcap",
                                capture_id="arista_route_churn_ebgp",
                                description="Save IXIA packet capture for route churn - eBGP",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_mimic_ibgp,
                                mode="save",
                                pcap_filename="bgp_arista_churn_ibgp.pcap",
                                capture_id="arista_route_churn_ibgp",
                                description="Save IXIA packet capture for route churn - iBGP",
                            ),
                            # packet capture analysis steps for route churn
                            create_custom_step(
                                description="Analyze route churn convergence time - eBGP",
                                params_dict={
                                    "custom_step_name": "check_route_churn_convergence",
                                    "pcap_filename": "bgp_arista_churn_ebgp.pcap",
                                    "phase": "route_churn_ebgp",
                                    "max_convergence_time_seconds": 300,
                                },
                            ),
                            create_custom_step(
                                description="Analyze route churn convergence time - iBGP",
                                params_dict={
                                    "custom_step_name": "check_route_churn_convergence",
                                    "pcap_filename": "bgp_arista_churn_ibgp.pcap",
                                    "phase": "route_churn_ibgp",
                                    "max_convergence_time_seconds": 300,
                                },
                            ),
                            # packet capture steps for route churn revert
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_mimic_ebgp,
                                mode="start",
                                capture_id="arista_route_churn_revert_ebgp",
                                description="Start IXIA packet capture for route churn revert - eBGP",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_mimic_ibgp,
                                mode="start",
                                capture_id="arista_route_churn_revert_ibgp",
                                description="Start IXIA packet capture for route churn revert - iBGP",
                            ),
                            create_longevity_step(
                                duration=5,
                                description="Brief pause to ensure IXIA capture is ready - 5 seconds",
                            ),
                            create_ixia_api_step(
                                api_name="set_bgp_local_preference",
                                args_dict={
                                    "local_preference": 100,
                                    "prefix_pool_regex": ".*PEER_1_FIRST_100.*",
                                },
                            ),
                            create_longevity_step(
                                duration=600,
                                description="Soak after churn revert for 600 seconds",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_mimic_ebgp,
                                mode="stop",
                                capture_id="arista_route_churn_revert_ebgp",
                                description="Stop IXIA packet capture for route churn revert - eBGP",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_mimic_ibgp,
                                mode="stop",
                                capture_id="arista_route_churn_revert_ibgp",
                                description="Stop IXIA packet capture for route churn revert - iBGP",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_mimic_ebgp,
                                mode="save",
                                pcap_filename="bgp_arista_churn_revert_ebgp.pcap",
                                capture_id="arista_route_churn_revert_ebgp",
                                description="Save IXIA packet capture for route churn revert - eBGP",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_mimic_ibgp,
                                mode="save",
                                pcap_filename="bgp_arista_churn_revert_ibgp.pcap",
                                capture_id="arista_route_churn_revert_ibgp",
                                description="Save IXIA packet capture for route churn revert - iBGP",
                            ),
                            # packet capture analysis steps for route churn revert
                            create_custom_step(
                                description="Analyze route churn revert convergence time - eBGP",
                                params_dict={
                                    "custom_step_name": "check_route_churn_convergence",
                                    "pcap_filename": "bgp_arista_churn_revert_ebgp.pcap",
                                    "phase": "route_churn_revert_ebgp",
                                    "max_convergence_time_seconds": 300,
                                },
                            ),
                            create_custom_step(
                                description="Analyze route churn revert convergence time - iBGP",
                                params_dict={
                                    "custom_step_name": "check_route_churn_convergence",
                                    "pcap_filename": "bgp_arista_churn_revert_ibgp.pcap",
                                    "phase": "route_churn_revert_ibgp",
                                    "max_convergence_time_seconds": 300,
                                },
                            ),
                            create_longevity_step(
                                duration=100,
                                description="Sleep for 100 seconds for FIB Sync",
                            ),
                        ]
                    ),
                ],
            ),
        ],
    )


def test_config_for_route_churn_prefix_scaling(
    test_config_name: str,
    device_name: str,
    ixia_interface_mimic_ebgp: str,
    ixia_interface_mimic_ibgp: str,
    ebgp_peer_count: int,
    ibgp_peer_count: int,
    ebgp_remote_as: int,
    ibgp_remote_as: int,
    ixia_ebgp_ic_parent_network_v6: str,
    ixia_ibgp_ic_parent_network_v6: str,
    direct_ixia_connections: list[t.Any],
    prefix_configs: list[tuple[int, int]],
    churn_count: int = 100,
    soak_duration_seconds: int = 600,
    max_convergence_time_seconds: int = 300,
    log_collection_timeout: int | None = None,
    oss_mock_device_data: t.Any = None,
    host_os_type_map: t.Any = None,
    host_driver_args: t.Any = None,
    ssh_user: str = "admin",
    ssh_password: str = "dnepit",
    peergroup_ebgp_v6: str = "EB-FA-V6",
    peergroup_ibgp_v6: str = "EB-EB-V6",
) -> TestConfig:
    """
    Create a single TestConfig for route churn testing across multiple prefix scales.

    Instead of creating separate TestConfigs for each prefix count, this function
    creates one TestConfig that uses a custom step to iterate through all prefix
    counts defined in prefix_configs.

    Args:
        prefix_configs: List of (prefix_count, convergence_time) tuples.
            e.g. [(30000, 480), (35000, 540), (40000, 600), (45000, 660), (50000, 720)]
        churn_count: Number of routes to churn (default: 100)
        soak_duration_seconds: Soak time after churn (default: 600)
        max_convergence_time_seconds: Threshold for pass/fail (default: 300)
    """
    # Use the max prefix count from prefix_configs for initial IXIA setup
    max_prefix_count = max(pc for pc, _ in prefix_configs)

    setup_tasks = [
        create_configure_bgpcpp_startup_task(
            hostname=device_name,
            flags={
                "agent_thrift_recv_timeout_ms": "160000",
            },
            ssh_user=ssh_user,
            ssh_password=ssh_password,
        ),
        create_replace_bgp_peers_task(
            hostname=device_name,
            peer_configs=[
                {
                    "peer_group_name": peergroup_ebgp_v6,
                    "remote_as": ebgp_remote_as,
                    "base_network": ixia_ebgp_ic_parent_network_v6,
                    "is_v6": True,
                    "peer_count": ebgp_peer_count,
                    "start_offset": 16,
                },
                {
                    "peer_group_name": peergroup_ibgp_v6,
                    "remote_as": ibgp_remote_as,
                    "base_network": ixia_ibgp_ic_parent_network_v6,
                    "is_v6": True,
                    "peer_count": ibgp_peer_count,
                    "start_offset": 16,
                },
            ],
        ),
    ]

    return TestConfig(
        name=test_config_name,
        skip_ixia_protocol_verification=True,
        log_collection_timeout=log_collection_timeout,
        basset_pool="dne.test",
        endpoints=[
            Endpoint(
                name=device_name,
                dut=True,
                ixia_ports=[ixia_interface_mimic_ebgp, ixia_interface_mimic_ibgp],
                direct_ixia_connections=(
                    direct_ixia_connections if direct_ixia_connections else []
                ),
            ),
        ],
        host_driver_args=host_driver_args,
        oss_mock_device_data=oss_mock_device_data,
        host_os_type_map=host_os_type_map,
        startup_checks=[],
        setup_tasks=setup_tasks,
        teardown_tasks=[],
        # Deprecated - define at playbook level
        # prechecks=[],
        # postchecks=[],
        # snapshot_checks=[],
        basic_port_configs=create_ebb_route_churn_test_basic_port_configs(
            device_name=device_name,
            ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
            ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
            ebgp_peer_count_v6=ebgp_peer_count,
            ibgp_peer_count_v6=ibgp_peer_count,
            ebgp_remote_as=ebgp_remote_as,
            ibgp_remote_as=ibgp_remote_as,
            initial_prefix_count=max_prefix_count,
            churn_count=churn_count,
            ixia_ebgp_ic_parent_network_v6=ixia_ebgp_ic_parent_network_v6,
            ixia_ibgp_ic_parent_network_v6=ixia_ibgp_ic_parent_network_v6,
        ),
        playbooks=[
            build_case6_playbook(
                name="bgp_plus_plus_route_churn_prefix_scaling_test",
                description="Test BGP++ route churn convergence across multiple prefix scales",
                snapshot_checks=[
                    create_core_dumps_snapshot_check(),
                    create_bgp_session_snapshot_check(
                        skip_flap_check=True, skip_uptime_check=True
                    ),
                ],
                periodic_tasks=create_standard_periodic_tasks(
                    device_name=device_name,
                    memory_threshold=Gigabyte.GIG_5.value,
                    cpu_util_terminate_on_error=False,
                    memory_terminate_on_error=False,
                ),
                prechecks=[],
                postchecks=[
                    create_bgp_session_establish_check(
                        expected_established_sessions_static=ibgp_peer_count
                        + ebgp_peer_count,
                        check_id="startup_bgp_session_verification",
                    ),
                    create_bgp_rib_fib_consistency_check(),
                    create_bgp_convergence_check(
                        convergence_threshold=700,
                        check_id="postcheck_bgp_convergence_time",
                    ),
                ],
                stages=[
                    create_steps_stage(
                        steps=[
                            create_custom_step(
                                description="Route churn scaling test across multiple prefix counts",
                                params_dict={
                                    "custom_step_name": "test_bgp_route_churn_scaling_eos_bgp_plus_plus",
                                    "prefix_configs": [
                                        list(pc) for pc in prefix_configs
                                    ],
                                    "churn_count": churn_count,
                                    "soak_duration_seconds": soak_duration_seconds,
                                    "max_convergence_time_seconds": max_convergence_time_seconds,
                                    "hostname": device_name,
                                    "ixia_interface_ebgp": ixia_interface_mimic_ebgp,
                                    "ixia_interface_ibgp": ixia_interface_mimic_ibgp,
                                },
                            ),
                        ]
                    ),
                ],
            ),
        ],
    )
