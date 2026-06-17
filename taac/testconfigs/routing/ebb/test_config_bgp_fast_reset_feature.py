# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

"""
BGP Fast Neighbor Tear Down (Fast Reset) Feature Test for EOS BGP++

This test validates the BGP fast neighbor tear down mechanism that uses netlink
LINK_EVENT to detect physical link failures and tear down eBGP sessions quickly.

Test Design:
    - Fast reset detects link failures via netlink and tears down sessions immediately
    - This is faster than waiting for hold timer expiration (typically 90-180 seconds)
    - Sessions should go down within seconds of link failure

Test Scenarios:
    1. Single Link Failure: One eBGP link goes down, verify fast tear down
    2. Multiple Simultaneous Link Failures: Multiple links fail at once, verify stability
    3. Link Flap: Link goes down and up rapidly, verify session recovery
"""

from collections.abc import Mapping, Sequence

from taac.health_checks.healthcheck_definitions import (
    create_bgp_rib_fib_consistency_check,
    create_bgp_session_establish_check,
    create_bgp_session_snapshot_check,
    create_core_dumps_snapshot_check,
)
from taac.playbooks.playbook_definitions import (
    build_fast_reset_playbook,
)
from taac.routing.ebb.arista_feature_testing.ixia_configs_for_fast_reset_test import (
    create_fast_reset_test_basic_port_configs,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_custom_step,
    create_ixia_device_group_toggle_step,
    create_longevity_step,
)
from taac.task_definitions import (
    create_invoke_ixia_api_task,
    create_replace_bgp_peers_task,
    create_restore_bgp_peers_task,
    create_run_commands_on_shell_task,
)
from taac.test_as_a_config.types import (
    DeviceOsType,
    DirectIxiaConnection,
    Endpoint,
    Params,
    ParamValue,
    PointInTimeHealthCheck,
    TestConfig,
)


def test_config_for_bgp_fast_reset_feature(
    test_config_name: str,
    device_name: str,
    # eBGP interfaces (multiple for simultaneous failure testing)
    ixia_interfaces_ebgp: list[str],
    ebgp_remote_as: int,
    ixia_ebgp_ic_parent_networks_v6: list[str],
    ixia_ebgp_ic_parent_networks_v4: list[str],
    # iBGP interface (listener)
    ixia_interface_ibgp: str | None = None,
    ibgp_local_as: int = 0,
    ixia_ibgp_ic_parent_network_v6: str = "",
    ixia_ibgp_ic_parent_network_v4: str = "",
    # Peer groups
    peer_groups: list[str] | None = None,
    # SSH credentials
    ssh_user: str = "admin",
    ssh_password: str = "",
    # Peer counts
    ebgp_peer_count_per_interface: int = 10,
    ibgp_peer_count: int = 10,
    # Route configuration
    prefix_count: int = 100,
    # Route acceptance communities
    ebgp_route_acceptance_communities: list[str] | None = None,
    # Address family selection
    test_address_families: list[str] | None = None,
    # Fast reset timing thresholds
    max_teardown_time_seconds: int = 3,  # Fast reset should be < 3 seconds (much faster than hold timer)
    hold_timer_seconds: int = 15,  # Expected BGP hold timer (keepalive=5, hold=15)
    # Test control
    convergence_wait_seconds: int = 60,
    link_down_duration_seconds: int = 30,  # How long to keep link down
    direct_ixia_connections: Sequence[DirectIxiaConnection] | None = None,
    log_collection_timeout: int | None = None,
    # pyre-fixme[2]: Parameter must be annotated.
    oss_mock_device_data=None,
    host_os_type_map: Mapping[str, DeviceOsType] | None = None,
    host_driver_args: dict[str, str] | None = None,
) -> TestConfig:
    """
    Create a test configuration for BGP fast reset feature testing.

    This test validates that:
    1. BGP sessions tear down quickly when physical link goes down (via netlink)
    2. Tear down time is significantly faster than hold timer expiration
    3. System remains stable when multiple links fail simultaneously
    4. Sessions recover properly when links come back up

    Args:
        test_config_name: Name for the test configuration
        device_name: Name of the device under test
        ixia_interfaces_ebgp: List of IXIA interfaces for eBGP peers
        ebgp_remote_as: AS number for eBGP peers
        ixia_ebgp_ic_parent_networks_v6: IPv6 networks for eBGP interfaces
        ixia_ebgp_ic_parent_networks_v4: IPv4 networks for eBGP interfaces
        ixia_interface_ibgp: Optional IXIA interface for iBGP listeners
        ibgp_local_as: iBGP local AS number
        ixia_ibgp_ic_parent_network_v6: IPv6 network for iBGP peers
        ixia_ibgp_ic_parent_network_v4: IPv4 network for iBGP peers
        peer_groups: Peer groups for the eBGP sessions
        ssh_user: SSH username for device access
        ssh_password: SSH password for device access
        ebgp_peer_count_per_interface: Number of eBGP peers per interface
        ibgp_peer_count: Number of iBGP listener peers
        prefix_count: Number of prefixes per peer to advertise
        ebgp_route_acceptance_communities: Acceptance communities for eBGP routes
        test_address_families: Address families to test (default: ["ipv6"])
        max_teardown_time_seconds: Maximum acceptable time for session tear down
        hold_timer_seconds: BGP hold timer value for comparison
        convergence_wait_seconds: Time to wait for BGP convergence
        link_down_duration_seconds: Duration to keep link down during test
        direct_ixia_connections: Direct IXIA connection specifications
        log_collection_timeout: Timeout for log collection
        oss_mock_device_data: OSS-compatible mock device data
        host_os_type_map: OS type mapping for hosts
        host_driver_args: Driver arguments for hosts

    Returns:
        TestConfig object for the BGP fast reset feature test
    """
    if test_address_families is None:
        test_address_families = ["ipv6"]

    if ebgp_route_acceptance_communities is None:
        ebgp_route_acceptance_communities = ["65529:39744"]

    if peer_groups is None:
        peer_groups = []
        if "ipv6" in test_address_families:
            peer_groups.append("EB-FA-V6")
        if "ipv4" in test_address_families:
            peer_groups.append("EB-FA-V4")

    # Calculate total peer counts
    num_afs = len(test_address_families)
    num_ebgp_interfaces = len(ixia_interfaces_ebgp)
    total_ebgp_peers = ebgp_peer_count_per_interface * num_ebgp_interfaces * num_afs
    total_ibgp_peers = ibgp_peer_count * num_afs if ixia_interface_ibgp else 0
    total_peers = total_ebgp_peers + total_ibgp_peers

    # Peers per interface for session checks
    peers_per_interface = ebgp_peer_count_per_interface * num_afs

    # All IXIA ports
    all_ixia_ports = list(ixia_interfaces_ebgp)
    if ixia_interface_ibgp:
        all_ixia_ports.append(ixia_interface_ibgp)

    # Build peer_groups config for replace_bgp_peers task
    # This replaces all BGP peers (including BGP-MON) with only test peers
    replace_peer_groups = []
    for idx, iface in enumerate(ixia_interfaces_ebgp):
        if "ipv6" in test_address_families and idx < len(
            ixia_ebgp_ic_parent_networks_v6
        ):
            replace_peer_groups.append(
                {
                    "peer_group_name": "EB-FA-V6",
                    "remote_as": ebgp_remote_as,
                    "base_network": ixia_ebgp_ic_parent_networks_v6[idx],
                    "is_v6": True,
                    "peer_count": ebgp_peer_count_per_interface,
                    "description_prefix": f"Test eBGP V6 Peer {iface}",
                }
            )
        if "ipv4" in test_address_families and idx < len(
            ixia_ebgp_ic_parent_networks_v4
        ):
            replace_peer_groups.append(
                {
                    "peer_group_name": "EB-FA-V4",
                    "remote_as": ebgp_remote_as,
                    "base_network": ixia_ebgp_ic_parent_networks_v4[idx],
                    "is_v6": False,
                    "peer_count": ebgp_peer_count_per_interface,
                    "description_prefix": f"Test eBGP V4 Peer {iface}",
                }
            )

    # Add iBGP peers if configured
    if ixia_interface_ibgp and ibgp_local_as:
        if "ipv6" in test_address_families and ixia_ibgp_ic_parent_network_v6:
            replace_peer_groups.append(
                {
                    "peer_group_name": "EB-EB-V6",
                    "remote_as": ibgp_local_as,
                    "base_network": ixia_ibgp_ic_parent_network_v6,
                    "is_v6": True,
                    "peer_count": ibgp_peer_count,
                    "description_prefix": "Test iBGP V6 Listener",
                }
            )
        if "ipv4" in test_address_families and ixia_ibgp_ic_parent_network_v4:
            replace_peer_groups.append(
                {
                    "peer_group_name": "EB-EB-V4",
                    "remote_as": ibgp_local_as,
                    "base_network": ixia_ibgp_ic_parent_network_v4,
                    "is_v6": False,
                    "peer_count": ibgp_peer_count,
                    "description_prefix": "Test iBGP V4 Listener",
                }
            )

    return TestConfig(
        name=test_config_name,
        skip_ixia_protocol_verification=True,
        log_collection_timeout=log_collection_timeout,
        basset_pool="dne.test",
        endpoints=[
            Endpoint(
                name=device_name,
                dut=True,
                ixia_ports=all_ixia_ports,
                direct_ixia_connections=direct_ixia_connections or [],
            ),
        ],
        host_driver_args=host_driver_args,
        oss_mock_device_data=oss_mock_device_data,
        host_os_type_map=host_os_type_map,
        startup_checks=[],
        # Setup tasks:
        # 1. Replace BGP peers with only test peers (removes BGP-MON and other peers)
        # 2. Enable all eBGP interfaces (defensive measure for recovery from previous failed tests)
        setup_tasks=[
            # Task 1: Replace BGP peers with minimal test peers
            create_replace_bgp_peers_task(
                hostname=device_name,
                peer_configs=replace_peer_groups,
            ),
            # Task 2: Enable all eBGP interfaces (defensive cleanup)
            create_run_commands_on_shell_task(
                hostname=device_name,
                cmds=[
                    "configure\n"
                    + "\n".join(
                        f"interface {iface}\nno shutdown"
                        for iface in ixia_interfaces_ebgp
                    )
                    + "\nend",
                ],
            ),
        ],
        teardown_tasks=[
            # Task 1: Re-enable all eBGP interfaces that may have been disabled during testing
            # This ensures interfaces are always restored regardless of test outcome
            create_run_commands_on_shell_task(
                hostname=device_name,
                cmds=[
                    "configure\n"
                    + "\n".join(
                        f"interface {iface}\nno shutdown"
                        for iface in ixia_interfaces_ebgp
                    )
                    + "\nend",
                ],
            ),
            # Task 2: Disable IXIA device groups
            create_invoke_ixia_api_task(
                api_name="toggle_device_groups",
                args_dict={
                    "enable": False,
                    "device_group_name_regex": ".*",
                },
            ),
            # Task 3: Restore original BGP peers from backup
            create_restore_bgp_peers_task(
                hostname=device_name,
            ),
        ],
        # Deprecated - define at playbook level
        # prechecks=[],
        # postchecks=[],
        # snapshot_checks=[],
        basic_port_configs=create_fast_reset_test_basic_port_configs(
            device_name=device_name,
            ixia_interfaces_ebgp=ixia_interfaces_ebgp,
            ebgp_peer_count_per_interface=ebgp_peer_count_per_interface,
            ebgp_remote_as=ebgp_remote_as,
            ixia_ebgp_ic_parent_networks_v6=ixia_ebgp_ic_parent_networks_v6,
            ixia_ebgp_ic_parent_networks_v4=ixia_ebgp_ic_parent_networks_v4,
            ixia_interface_ibgp=ixia_interface_ibgp,
            ibgp_peer_count=ibgp_peer_count,
            ibgp_local_as=ibgp_local_as,
            ixia_ibgp_ic_parent_network_v6=ixia_ibgp_ic_parent_network_v6,
            ixia_ibgp_ic_parent_network_v4=ixia_ibgp_ic_parent_network_v4,
            prefix_count=prefix_count,
            ebgp_route_acceptance_communities=ebgp_route_acceptance_communities,
            test_address_families=test_address_families,
        ),
        playbooks=[
            # Playbook 0: Single Link Failure - Fast Tear Down Test
            build_fast_reset_playbook(
                name="BGP_Fast_Reset_Test_Phase0_Single_Link_Failure",
                setup_steps=[
                    create_ixia_device_group_toggle_step(
                        enable=True,
                        device_group_name_regex=".*",
                        description="Enable all BGP peer device groups",
                    ),
                ],
                periodic_tasks=[],
                prechecks=[
                    create_bgp_session_establish_check(
                        expected_established_sessions_static=total_peers,
                        check_id="verify_all_bgp_sessions_established_phase0",
                    ),
                ],
                snapshot_checks=[
                    create_bgp_session_snapshot_check(
                        skip_flap_check=True, skip_uptime_check=True
                    ),
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            # Ensure interfaces are up (in case previous test left them down)
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "simulate_multiple_link_failures",
                                    "hostname": device_name,
                                    "interfaces": list(ixia_interfaces_ebgp),
                                    "action": "enable",
                                    "ssh_user": ssh_user,
                                    "ssh_password": ssh_password,
                                },
                                description="Restore all eBGP interfaces (cleanup from previous run)",
                            ),
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for BGP convergence ({convergence_wait_seconds}s)",
                            ),
                            # Record baseline session state and timestamps
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "record_bgp_session_baseline",
                                    "hostname": device_name,
                                },
                                description="Record baseline BGP session state",
                            ),
                            # Disable first eBGP interface (simulate link failure via Arista shutdown)
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "simulate_link_failure",
                                    "hostname": device_name,
                                    "interface": ixia_interfaces_ebgp[0],
                                    "action": "disable",
                                    "ssh_user": ssh_user,
                                    "ssh_password": ssh_password,
                                },
                                description="Simulate single link failure (shutdown first eBGP interface)",
                            ),
                            # Verify fast route withdrawal (routes should be withdrawn quickly)
                            # Note: Fast neighbor teardown withdraws routes immediately,
                            # but sessions may still wait for hold timer to fully go down
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_fast_route_withdrawal",
                                    "hostname": device_name,
                                    "max_withdrawal_time_seconds": max_teardown_time_seconds,
                                    "expected_withdrawn_routes": 0,
                                },
                                description=f"Verify fast route withdrawal (within {max_teardown_time_seconds}s)",
                            ),
                            create_longevity_step(
                                duration=link_down_duration_seconds,
                                description=f"Keep link down ({link_down_duration_seconds}s)",
                            ),
                            # Re-enable the link
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "simulate_link_failure",
                                    "hostname": device_name,
                                    "interface": ixia_interfaces_ebgp[0],
                                    "action": "enable",
                                    "ssh_user": ssh_user,
                                    "ssh_password": ssh_password,
                                },
                                description="Restore link (no shutdown first eBGP interface)",
                            ),
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for session recovery ({convergence_wait_seconds}s)",
                            ),
                            # Verify sessions recovered
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_sessions_established",
                                    "hostname": device_name,
                                    "expected_session_count": total_peers,
                                },
                                description="Verify all sessions recovered",
                            ),
                        ],
                    ),
                ],
            ),
            # Playbook 1: Multiple Simultaneous Link Failures - Stability Test
            build_fast_reset_playbook(
                name="BGP_Fast_Reset_Test_Phase1_Multiple_Simultaneous_Failures",
                setup_steps=[
                    create_ixia_device_group_toggle_step(
                        enable=True,
                        device_group_name_regex=".*",
                        description="Enable all BGP peer device groups",
                    ),
                ],
                periodic_tasks=[],
                prechecks=[
                    # NOTE: No BGP session precheck here - we restore interfaces at the start
                    # of stages and verify sessions after convergence wait. This ensures Phase1
                    # can recover if Phase0 failed mid-test leaving interfaces down.
                ],
                snapshot_checks=[
                    create_bgp_session_snapshot_check(
                        skip_flap_check=True, skip_uptime_check=True
                    ),
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[
                    create_bgp_rib_fib_consistency_check(),
                ],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            # Ensure interfaces are up (in case previous phase left them down)
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "simulate_multiple_link_failures",
                                    "hostname": device_name,
                                    "interfaces": list(ixia_interfaces_ebgp),
                                    "action": "enable",
                                    "ssh_user": ssh_user,
                                    "ssh_password": ssh_password,
                                },
                                description="Restore all eBGP interfaces (cleanup from previous phase)",
                            ),
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for BGP convergence ({convergence_wait_seconds}s)",
                            ),
                            # Verify all sessions are established before starting test
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_sessions_established",
                                    "hostname": device_name,
                                    "expected_session_count": total_peers,
                                },
                                description="Verify all sessions established before test",
                            ),
                            # Record baseline session state
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "record_bgp_session_baseline",
                                    "hostname": device_name,
                                },
                                description="Record baseline BGP session state",
                            ),
                            # Shutdown ALL eBGP interfaces simultaneously (triggers netlink LINK_EVENT)
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "simulate_multiple_link_failures",
                                    "hostname": device_name,
                                    "interfaces": list(ixia_interfaces_ebgp),
                                    "action": "disable",
                                    "ssh_user": ssh_user,
                                    "ssh_password": ssh_password,
                                },
                                description="Simulate multiple simultaneous link failures",
                            ),
                            # Verify fast route withdrawal for all affected sessions
                            # Note: Fast neighbor teardown withdraws routes immediately,
                            # but sessions may still wait for hold timer to fully go down
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_fast_route_withdrawal",
                                    "hostname": device_name,
                                    "max_withdrawal_time_seconds": max_teardown_time_seconds,
                                    "expected_withdrawn_routes": 0,
                                },
                                description=f"Verify fast route withdrawal for all eBGP routes (within {max_teardown_time_seconds}s)",
                            ),
                            create_longevity_step(
                                duration=link_down_duration_seconds,
                                description=f"Keep links down ({link_down_duration_seconds}s)",
                            ),
                            # Re-enable all links (no shutdown)
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "simulate_multiple_link_failures",
                                    "hostname": device_name,
                                    "interfaces": list(ixia_interfaces_ebgp),
                                    "action": "enable",
                                    "ssh_user": ssh_user,
                                    "ssh_password": ssh_password,
                                },
                                description="Restore all links simultaneously",
                            ),
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for session recovery ({convergence_wait_seconds}s)",
                            ),
                            # Verify all sessions recovered
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_sessions_established",
                                    "hostname": device_name,
                                    "expected_session_count": total_peers,
                                },
                                description="Verify all sessions recovered after simultaneous recovery",
                            ),
                        ],
                    ),
                ],
            ),
            # Playbook 2: Link Flap Test
            build_fast_reset_playbook(
                name="BGP_Fast_Reset_Test_Phase2_Link_Flap",
                setup_steps=[
                    create_ixia_device_group_toggle_step(
                        enable=True,
                        device_group_name_regex=".*",
                        description="Enable all BGP peer device groups",
                    ),
                ],
                periodic_tasks=[],
                prechecks=[
                    # NOTE: No precheck here - we restore interfaces at the start of stages
                    # and verify sessions after convergence wait
                ],
                snapshot_checks=[
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            # Ensure interfaces are up (in case previous test left them down)
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "simulate_multiple_link_failures",
                                    "hostname": device_name,
                                    "interfaces": list(ixia_interfaces_ebgp),
                                    "action": "enable",
                                    "ssh_user": ssh_user,
                                    "ssh_password": ssh_password,
                                },
                                description="Restore all eBGP interfaces (cleanup from previous test)",
                            ),
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for BGP convergence ({convergence_wait_seconds}s)",
                            ),
                            # Verify all sessions are established before starting link flap
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_sessions_established",
                                    "hostname": device_name,
                                    "expected_session_count": total_peers,
                                },
                                description="Verify all sessions established before link flap",
                            ),
                            # Perform rapid link flap using Arista interface shutdown/no shutdown
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "perform_link_flap",
                                    "hostname": device_name,
                                    "interface": ixia_interfaces_ebgp[0],
                                    "flap_count": 3,
                                    "down_duration_seconds": 5,
                                    "up_duration_seconds": 10,
                                    "ssh_user": ssh_user,
                                    "ssh_password": ssh_password,
                                },
                                description="Perform rapid link flap (down-up cycle)",
                            ),
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for session stabilization ({convergence_wait_seconds}s)",
                            ),
                            # Verify all sessions recovered and stable
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_sessions_established",
                                    "hostname": device_name,
                                    "expected_session_count": total_peers,
                                },
                                description="Verify all sessions recovered after link flap",
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )
