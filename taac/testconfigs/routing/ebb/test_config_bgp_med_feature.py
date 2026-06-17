# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

"""
BGP MED (Multi-Exit Discriminator) Feature Test for EOS BGP++

This test validates the BGP MED attribute functionality in EOS BGP++.

Test Design - EBGP to IBGP Scenario:
    - IXIA mimics EBGP peers (same AS) sending routes with different MED values
    - Device compares MED and selects lower MED as best path
    - IXIA mimics IBGP peers as listeners to verify best path selection
    - Routes with lower MED should be selected as best

MED Behavior:
    - Lower MED is preferred (opposite of weight)
    - MED is only compared between routes from the same neighboring AS
    - Default MED is typically 0 or missing (implementation dependent)

Test Scenario:
    1. Create 2 eBGP device groups on ingress interface (same AS)
       - Group 1: Advertises routes with high MED (100)
       - Group 2: Advertises SAME routes with low MED (10)
    2. Create iBGP listener peers on egress interface
    3. Routes from group 2 (MED 10) should be selected as best
    4. Withdraw routes from group 2
    5. Verify routes from group 1 (MED 100) are now selected as best
"""

from collections.abc import Mapping, Sequence

from taac.health_checks.healthcheck_definitions import (
    create_bgp_rib_fib_consistency_check,
    create_bgp_session_establish_check,
    create_bgp_session_snapshot_check,
    create_core_dumps_snapshot_check,
    create_next_hop_count_check,
)
from taac.playbooks.playbook_definitions import (
    build_bgp_med_playbook,
)
from taac.routing.ebb.arista_feature_testing.ixia_configs_for_med_test import (
    create_med_test_basic_port_configs,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_advertise_withdraw_prefixes_step,
    create_bgp_prefixes_med_value_step,
    create_custom_step,
    create_ixia_device_group_toggle_step,
    create_ixia_packet_capture_step,
    create_longevity_step,
    create_run_task_step,
)
from taac.task_definitions import (
    create_disable_med_comparison_task,
    create_invoke_ixia_api_task,
    create_ixia_enable_disable_bgp_prefixes_task,
    create_replace_bgp_peers_task,
    create_restore_bgp_peers_task,
)
from taac.test_as_a_config.types import (
    DeviceOsType,
    DirectIxiaConnection,
    Endpoint,
    Step,
    Task,
    TestConfig,
)


def test_config_for_bgp_med_feature(
    test_config_name: str,
    device_name: str,
    # eBGP interface (ingress - routes come in here)
    ixia_interface_ebgp: str,
    ebgp_remote_as: int,
    ixia_ebgp_ic_parent_network_v6: str,
    ixia_ebgp_ic_parent_network_v4: str,
    # iBGP interface (egress - listeners)
    ixia_interface_ibgp: str,
    ibgp_local_as: int,
    ixia_ibgp_ic_parent_network_v6: str,
    ixia_ibgp_ic_parent_network_v4: str,
    # SSH credentials
    ssh_user: str = "admin",
    ssh_password: str = "",
    # Peer counts
    ebgp_peer_count_group1: int = 50,
    ebgp_peer_count_group2: int = 50,
    ibgp_peer_count: int = 50,
    # Route configuration
    prefix_count: int = 100,
    # MED configuration
    med_low: int = 10,
    med_high: int = 100,
    # Route acceptance communities
    ebgp_route_acceptance_communities: list[str] | None = None,
    # Address family selection
    test_address_families: list[str] | None = None,
    # Test control
    convergence_wait_seconds: int = 120,
    direct_ixia_connections: Sequence[DirectIxiaConnection] | None = None,
    log_collection_timeout: int | None = None,
    # pyre-fixme[24]: Generic type `dict` expects 2 type parameters, use
    #  `typing.Dict[<key type>, <value type>]` to avoid runtime subscripting errors.
    oss_mock_device_data: dict | None = None,
    host_os_type_map: Mapping[str, DeviceOsType] | None = None,
    host_driver_args: dict[str, str] | None = None,
) -> TestConfig:
    """
    Create a test configuration for BGP MED feature testing.

    This test validates that:
    1. Routes with lower MED are preferred over routes with higher MED
    2. When lower-MED routes are withdrawn, higher-MED routes become best
    3. MED is correctly compared between routes from the same AS

    Test Design - EBGP to IBGP Scenario:
        - eBGP interface: Two device groups (same AS) advertise same routes with different MED
        - Device selects lower MED as best path
        - iBGP interface: Listener peers receive best routes

    Args:
        test_config_name: Name for the test configuration
        device_name: Name of the device under test
        ixia_interface_ebgp: IXIA interface for eBGP peers (ingress)
        ebgp_remote_as: AS number for eBGP peers (same for both groups)
        ixia_ebgp_ic_parent_network_v6: IPv6 network for eBGP peers
        ixia_ebgp_ic_parent_network_v4: IPv4 network for eBGP peers
        ixia_interface_ibgp: IXIA interface for iBGP peers (egress/listeners)
        ibgp_local_as: AS number for iBGP peers (same as DUT)
        ixia_ibgp_ic_parent_network_v6: IPv6 network for iBGP peers
        ixia_ibgp_ic_parent_network_v4: IPv4 network for iBGP peers
        ssh_user: SSH username for device access (default: admin)
        ssh_password: SSH password for device access
        ebgp_peer_count_group1: Number of eBGP peers in group 1 (high MED)
        ebgp_peer_count_group2: Number of eBGP peers in group 2 (low MED)
        ibgp_peer_count: Number of iBGP listener peers
        prefix_count: Number of prefixes per peer to advertise
        med_low: Low MED value (preferred, default 10)
        med_high: High MED value (less preferred, default 100)
        ebgp_route_acceptance_communities: Acceptance communities for eBGP routes
        test_address_families: Address families to test (default: ["ipv6"])
        convergence_wait_seconds: Time to wait for BGP convergence
        direct_ixia_connections: Direct IXIA connection specifications
        log_collection_timeout: Timeout for log collection
        host_os_type_map: OS type mapping for hosts
        host_driver_args: Driver arguments for hosts

    Returns:
        TestConfig object for the BGP MED feature test
    """
    if test_address_families is None:
        test_address_families = ["ipv6"]

    if ebgp_route_acceptance_communities is None:
        ebgp_route_acceptance_communities = ["65529:39744"]

    # Calculate total peer count for session checks
    num_afs = len(test_address_families)
    total_ebgp_peers = (ebgp_peer_count_group1 + ebgp_peer_count_group2) * num_afs
    total_ibgp_peers = ibgp_peer_count * num_afs
    total_peers = total_ebgp_peers + total_ibgp_peers

    # Total eBGP peers per AF for device config (both MED groups combined)
    total_ebgp_per_af = ebgp_peer_count_group1 + ebgp_peer_count_group2

    # Build peer_groups config for replace_bgp_peers task
    peer_groups = []
    if "ipv6" in test_address_families:
        # eBGP IPv6 peers
        peer_groups.append(
            {
                "peer_group_name": "EB-FA-V6",
                "remote_as": ebgp_remote_as,
                "base_network": ixia_ebgp_ic_parent_network_v6,
                "is_v6": True,
                "peer_count": total_ebgp_per_af,
                "description_prefix": "eBGP V6 Peer",
            }
        )
        # iBGP IPv6 peers
        peer_groups.append(
            {
                "peer_group_name": "EB-EB-V6",
                "remote_as": ibgp_local_as,
                "base_network": ixia_ibgp_ic_parent_network_v6,
                "is_v6": True,
                "peer_count": ibgp_peer_count,
                "description_prefix": "iBGP V6 Listener",
            }
        )
    if "ipv4" in test_address_families:
        # eBGP IPv4 peers
        peer_groups.append(
            {
                "peer_group_name": "EB-FA-V4",
                "remote_as": ebgp_remote_as,
                "base_network": ixia_ebgp_ic_parent_network_v4,
                "is_v6": False,
                "peer_count": total_ebgp_per_af,
                "description_prefix": "eBGP V4 Peer",
            }
        )
        # iBGP IPv4 peers
        peer_groups.append(
            {
                "peer_group_name": "EB-EB-V4",
                "remote_as": ibgp_local_as,
                "base_network": ixia_ibgp_ic_parent_network_v4,
                "is_v6": False,
                "peer_count": ibgp_peer_count,
                "description_prefix": "iBGP V4 Listener",
            }
        )

    # Build setup tasks for EOS BGP++ device
    # Note: MED comparison is NOT enabled in setup - Phase 0 tests behavior without it
    setup_tasks: list[Task] = [
        # Task 1: Replace BGP peers with minimal test peers
        create_replace_bgp_peers_task(
            hostname=device_name,
            peer_configs=peer_groups,
        ),
        # Task 2: Disable prefix pools initially
        create_ixia_enable_disable_bgp_prefixes_task(
            enable=False,
            prefix_pool_regex="PREFIX_POOL_.*",
            prefix_start_index=0,
        ),
    ]

    # Helper to create enable_med_comparison step
    def create_enable_med_comparison_step(
        description: str = "Enable MED comparison in BGP++ settings",
    ) -> Step:
        return create_run_task_step(
            task_name="enable_med_comparison",
            params_dict={
                "hostname": device_name,
                "enable_med_missing_as_worst": False,
                "ssh_user": ssh_user,
                "ssh_password": ssh_password,
                "reload_bgp": True,
            },
            description=description,
        )

    # Helper to create disable_med_comparison step
    def create_disable_med_comparison_step(
        description: str = "Disable MED comparison in BGP++ settings",
    ) -> Step:
        return create_run_task_step(
            task_name="disable_med_comparison",
            params_dict={
                "hostname": device_name,
                "ssh_user": ssh_user,
                "ssh_password": ssh_password,
                "reload_bgp": True,
            },
            description=description,
        )

    # Helper to enable MED missing as worst (for MED vs No-MED test)
    def create_enable_med_missing_as_worst_step(
        description: str = "Enable 'treat missing MED as worst' in BGP++ settings",
    ) -> Step:
        return create_run_task_step(
            task_name="enable_med_comparison",
            params_dict={
                "hostname": device_name,
                "enable_med_missing_as_worst": True,
                "ssh_user": ssh_user,
                "ssh_password": ssh_password,
                "reload_bgp": True,
            },
            description=description,
        )

    # Helper to disable MED missing as worst (reset to default behavior)
    def create_disable_med_missing_as_worst_step(
        description: str = "Disable 'treat missing MED as worst' in BGP++ settings",
    ) -> Step:
        return create_run_task_step(
            task_name="enable_med_comparison",
            params_dict={
                "hostname": device_name,
                "enable_med_missing_as_worst": False,
                "ssh_user": ssh_user,
                "ssh_password": ssh_password,
                "reload_bgp": True,
            },
            description=description,
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
                ixia_ports=[ixia_interface_ebgp, ixia_interface_ibgp],
                direct_ixia_connections=direct_ixia_connections or [],
            ),
        ],
        host_driver_args=host_driver_args,
        oss_mock_device_data=oss_mock_device_data,
        host_os_type_map=host_os_type_map,
        startup_checks=[],
        setup_tasks=setup_tasks,
        teardown_tasks=[
            create_invoke_ixia_api_task(
                api_name="toggle_device_groups",
                args_dict={
                    "enable": False,
                    "device_group_name_regex": ".*",
                },
            ),
            # Restore original BGP peers from backup
            create_restore_bgp_peers_task(
                hostname=device_name,
            ),
            # Disable MED comparison (restore default behavior)
            create_disable_med_comparison_task(
                hostname=device_name,
                ssh_user=ssh_user,
                ssh_password=ssh_password,
            ),
        ],
        # Deprecated - define at playbook level
        # prechecks=[],
        # postchecks=[],
        # snapshot_checks=[],
        basic_port_configs=create_med_test_basic_port_configs(
            device_name=device_name,
            # eBGP interface (ingress)
            ixia_interface_ebgp=ixia_interface_ebgp,
            ebgp_peer_count_group1=ebgp_peer_count_group1,
            ebgp_peer_count_group2=ebgp_peer_count_group2,
            ebgp_remote_as=ebgp_remote_as,
            ixia_ebgp_ic_parent_network_v6=ixia_ebgp_ic_parent_network_v6,
            ixia_ebgp_ic_parent_network_v4=ixia_ebgp_ic_parent_network_v4,
            # iBGP interface (egress - listeners)
            ixia_interface_ibgp=ixia_interface_ibgp,
            ibgp_peer_count=ibgp_peer_count,
            ibgp_local_as=ibgp_local_as,
            ixia_ibgp_ic_parent_network_v6=ixia_ibgp_ic_parent_network_v6,
            ixia_ibgp_ic_parent_network_v4=ixia_ibgp_ic_parent_network_v4,
            # Route configuration
            prefix_count=prefix_count,
            ebgp_route_acceptance_communities=ebgp_route_acceptance_communities,
            test_address_families=test_address_families,
        ),
        playbooks=[
            # Playbook 0: MED comparison DISABLED - verify MED is ignored
            # This validates that when enable_med_comparison is NOT set,
            # the device ignores MED values and forms ECMP with both paths
            build_bgp_med_playbook(
                name="BGP_MED_Test_Phase0_MED_Comparison_Disabled",
                setup_steps=[
                    # First disable MED comparison to ensure it's off
                    create_disable_med_comparison_step(
                        description="Disable MED comparison for Phase 0 ECMP test"
                    ),
                    create_ixia_device_group_toggle_step(
                        enable=True,
                        device_group_name_regex=".*",
                        description="Enable all BGP peer device groups",
                    ),
                    # Set MED values on prefix pools
                    create_bgp_prefixes_med_value_step(
                        prefix_pool_regex="PREFIX_POOL_.*_MED_HIGH$",
                        prefix_start_index=0,
                        med_value=med_high,
                        description=f"Set MED {med_high} on HIGH MED prefix pools",
                    ),
                    create_bgp_prefixes_med_value_step(
                        prefix_pool_regex="PREFIX_POOL_.*_MED_LOW$",
                        prefix_start_index=0,
                        med_value=med_low,
                        description=f"Set MED {med_low} on LOW MED prefix pools",
                    ),
                    create_bgp_prefixes_med_value_step(
                        prefix_pool_regex="PREFIX_POOL_.*_MED_LOW_VS_NOMED$",
                        prefix_start_index=0,
                        med_value=med_low,
                        description=f"Set MED {med_low} on LOW MED vs NOMED prefix pools",
                    ),
                    # Advertise routes
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_HIGH$",
                        prefix_start_index=0,
                        description=f"Advertise routes from eBGP Group 1 (MED {med_high})",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_LOW$",
                        prefix_start_index=0,
                        description=f"Advertise routes from eBGP Group 2 (MED {med_low})",
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
                postchecks=[
                    # Verify ECMP - routes should have 2+ next-hops since MED is ignored
                    create_next_hop_count_check(
                        min_nexthop_count=2,
                        prefix_subnets=["2001:db8:3000::/48", "10.200.0.0/16"],
                        check_id="verify_ecmp_med_ignored",
                    ),
                ],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for BGP convergence ({convergence_wait_seconds}s)",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_med_ignored",
                                    "hostname": device_name,
                                    "prefix_filter": "2001:db8:3000::",
                                    "expected_med_low": med_low,
                                    "expected_med_high": med_high,
                                },
                                description="Verify MED is IGNORED - both MED values should be in RIB (ECMP)",
                            ),
                        ],
                    ),
                ],
            ),
            # Playbook 1: Enable MED comparison, then verify lower MED is best
            build_bgp_med_playbook(
                name="BGP_MED_Test_Phase1_Both_Groups_Active",
                setup_steps=[
                    # First enable MED comparison
                    create_enable_med_comparison_step(
                        description="Enable MED comparison for best path selection"
                    ),
                ],
                periodic_tasks=[],
                prechecks=[
                    create_bgp_session_establish_check(
                        expected_established_sessions_static=total_peers,
                        check_id="verify_all_bgp_sessions_established",
                    ),
                ],
                snapshot_checks=[
                    create_bgp_session_snapshot_check(
                        skip_flap_check=True, skip_uptime_check=True
                    ),
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[
                    create_bgp_session_establish_check(
                        expected_established_sessions_static=total_peers,
                        check_id="verify_bgp_sessions_after_advertisement",
                    ),
                ],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            # Note: No PCAP capture in Phase 1 because routes are already
                            # established from Phase 0. PCAP verification is in Phase 6.
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for BGP convergence ({convergence_wait_seconds}s)",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_med_best_path",
                                    "hostname": device_name,
                                    "expected_med": med_low,
                                    "prefix_filter": "2001:db8:3000::",
                                },
                                description=f"Verify routes with MED {med_low} are selected as best",
                            ),
                        ],
                    ),
                ],
            ),
            # Playbook 2: Withdraw low MED - verify high MED becomes best
            build_bgp_med_playbook(
                name="BGP_MED_Test_Phase2_LowMED_Withdrawn",
                setup_steps=[
                    # Start capture BEFORE withdrawal so we capture the updates
                    create_ixia_packet_capture_step(
                        device_name=device_name,
                        interface=ixia_interface_ibgp,
                        mode="start",
                        capture_filter="tcp port 179",
                        capture_id="phase2_med_capture",
                        description="Start capture on iBGP interface for Phase 2",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_LOW$",
                        prefix_start_index=0,
                        description=f"Withdraw routes from eBGP Group 2 (MED {med_low})",
                    ),
                ],
                periodic_tasks=[],
                prechecks=[],
                snapshot_checks=[
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[
                    create_bgp_rib_fib_consistency_check(),
                ],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for withdrawal convergence ({convergence_wait_seconds}s)",
                            ),
                            # Stop and save packet capture
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_ibgp,
                                mode="stop",
                                capture_id="phase2_med_capture",
                                description="Stop capture on iBGP interface",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_ibgp,
                                mode="save",
                                capture_id="phase2_med_capture",
                                pcap_filename="bgp_med_phase2.pcap",
                                description="Save Phase 2 packet capture",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_med_best_path",
                                    "hostname": device_name,
                                    "expected_med": med_high,
                                    "prefix_filter": "2001:db8:3000::",
                                },
                                description=f"Verify routes with MED {med_high} are now best",
                            ),
                            # Verify MED in captured packets
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_med_in_pcap",
                                    "pcap_filename": "bgp_med_phase2.pcap",
                                    "expected_med": med_high,
                                    "min_updates_with_med": 1,
                                },
                                description=f"Verify MED {med_high} in PCAP sent to iBGP",
                            ),
                        ],
                    ),
                ],
            ),
            # Playbook 3: Re-advertise low MED - verify low MED is best again
            build_bgp_med_playbook(
                name="BGP_MED_Test_Phase3_LowMED_Readvertised",
                setup_steps=[
                    # Start capture BEFORE re-advertisement so we capture the updates
                    create_ixia_packet_capture_step(
                        device_name=device_name,
                        interface=ixia_interface_ibgp,
                        mode="start",
                        capture_filter="tcp port 179",
                        capture_id="phase3_med_capture",
                        description="Start capture on iBGP interface for Phase 3",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_LOW$",
                        prefix_start_index=0,
                        description=f"Re-advertise routes from eBGP Group 2 (MED {med_low})",
                    ),
                ],
                periodic_tasks=[],
                prechecks=[],
                snapshot_checks=[
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[
                    create_bgp_rib_fib_consistency_check(),
                ],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for re-advertisement convergence ({convergence_wait_seconds}s)",
                            ),
                            # Stop and save packet capture
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_ibgp,
                                mode="stop",
                                capture_id="phase3_med_capture",
                                description="Stop capture on iBGP interface",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_ibgp,
                                mode="save",
                                capture_id="phase3_med_capture",
                                pcap_filename="bgp_med_phase3.pcap",
                                description="Save Phase 3 packet capture",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_med_best_path",
                                    "hostname": device_name,
                                    "expected_med": med_low,
                                    "prefix_filter": "2001:db8:3000::",
                                },
                                description=f"Verify routes with MED {med_low} are best again",
                            ),
                            # Verify MED in captured packets
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_med_in_pcap",
                                    "pcap_filename": "bgp_med_phase3.pcap",
                                    "expected_med": med_low,
                                    "min_updates_with_med": 1,
                                },
                                description=f"Verify MED {med_low} in PCAP sent to iBGP",
                            ),
                        ],
                    ),
                ],
            ),
            # Playbook 4: MED vs No-MED - verify explicit MED beats default
            # When enable_med_missing_as_worst is true, routes with no MED are treated
            # as having the highest (worst) MED value, so explicit MED wins
            build_bgp_med_playbook(
                name="BGP_MED_Test_Phase4_MED_Vs_NoMED",
                setup_steps=[
                    # Enable "treat missing MED as worst" so explicit MED beats no-MED
                    create_enable_med_missing_as_worst_step(
                        description="Enable 'missing MED as worst' for MED vs No-MED test"
                    ),
                    # Withdraw MED_HIGH and MED_LOW routes
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_HIGH$",
                        prefix_start_index=0,
                        description="Withdraw high MED routes",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_LOW$",
                        prefix_start_index=0,
                        description="Withdraw low MED routes",
                    ),
                    # Start capture BEFORE advertising so we capture the updates
                    create_ixia_packet_capture_step(
                        device_name=device_name,
                        interface=ixia_interface_ibgp,
                        mode="start",
                        capture_filter="tcp port 179",
                        capture_id="phase4_med_capture",
                        description="Start capture on iBGP interface for Phase 4",
                    ),
                    # Advertise NO_MED routes (no MED attribute set)
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_NO_MED$",
                        prefix_start_index=0,
                        description="Advertise routes with no MED (default)",
                    ),
                    # Advertise MED_LOW_VS_NOMED routes (low MED on same prefixes)
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_LOW_VS_NOMED",
                        prefix_start_index=0,
                        description=f"Advertise same routes with MED {med_low}",
                    ),
                ],
                periodic_tasks=[],
                prechecks=[],
                snapshot_checks=[
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[
                    create_bgp_rib_fib_consistency_check(),
                ],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for convergence ({convergence_wait_seconds}s)",
                            ),
                            # Stop and save packet capture
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_ibgp,
                                mode="stop",
                                capture_id="phase4_med_capture",
                                description="Stop capture on iBGP interface",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_ibgp,
                                mode="save",
                                capture_id="phase4_med_capture",
                                pcap_filename="bgp_med_phase4.pcap",
                                description="Save Phase 4 packet capture",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_med_best_path",
                                    "hostname": device_name,
                                    "expected_med": med_low,
                                    "prefix_filter": "2001:db8:4000::",
                                },
                                description=f"Verify routes with explicit MED {med_low} vs no MED",
                            ),
                            # Verify MED in captured packets
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_med_in_pcap",
                                    "pcap_filename": "bgp_med_phase4.pcap",
                                    "expected_med": med_low,
                                    "min_updates_with_med": 1,
                                },
                                description=f"Verify MED {med_low} in PCAP sent to iBGP",
                            ),
                        ],
                    ),
                ],
            ),
            # Playbook 4a: Reset enable_med_missing_as_worst=false
            # Verify that missing MED is treated as 0 (not worst), so no-MED beats MED > 0
            build_bgp_med_playbook(
                name="BGP_MED_Test_Phase4a_NoMED_As_Zero",
                setup_steps=[
                    # Start capture BEFORE config change to capture any updates
                    create_ixia_packet_capture_step(
                        device_name=device_name,
                        interface=ixia_interface_ibgp,
                        mode="start",
                        capture_filter="tcp port 179",
                        capture_id="phase4a_med_capture",
                        description="Start capture on iBGP interface for Phase 4a",
                    ),
                    # Disable "treat missing MED as worst" - missing MED is now 0
                    create_disable_med_missing_as_worst_step(
                        description="Reset 'missing MED as worst' to false - no-MED treated as 0"
                    ),
                    # Routes from Phase 4 are still active:
                    # - PREFIX_POOL_.*_NO_MED (no MED, treated as 0)
                    # - PREFIX_POOL_.*_MED_LOW_VS_NOMED (MED=10)
                    # Now no-MED (0) should beat MED=10
                ],
                periodic_tasks=[],
                prechecks=[],
                snapshot_checks=[
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[
                    create_bgp_rib_fib_consistency_check(),
                ],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for convergence after config change ({convergence_wait_seconds}s)",
                            ),
                            # Stop and save packet capture
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_ibgp,
                                mode="stop",
                                capture_id="phase4a_med_capture",
                                description="Stop capture on iBGP interface",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_ibgp,
                                mode="save",
                                capture_id="phase4a_med_capture",
                                pcap_filename="bgp_med_phase4a.pcap",
                                description="Save Phase 4a packet capture",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_med_best_path",
                                    "hostname": device_name,
                                    # When missing MED is treated as 0, best path has MED=0
                                    "expected_med": 0,
                                    "prefix_filter": "2001:db8:4000::",
                                },
                                description="Verify no-MED (treated as 0) beats explicit MED > 0",
                            ),
                            # Note: Best path has no MED attribute, so we skip PCAP MED verification
                            # When a route has no MED, it won't appear in PCAP with MED=0
                            # The RIB verification above is sufficient for this test case
                        ],
                    ),
                ],
            ),
            # Playbook 4b: MED=0 explicitly set vs higher MED
            # Verify that explicit MED=0 beats higher MED values
            build_bgp_med_playbook(
                name="BGP_MED_Test_Phase4b_MED_Zero_Best",
                setup_steps=[
                    # Withdraw current routes
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_NO_MED$",
                        prefix_start_index=0,
                        description="Withdraw no-MED routes",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_LOW_VS_NOMED",
                        prefix_start_index=0,
                        description="Withdraw MED low vs no-MED routes",
                    ),
                    # Set MED=0 on one prefix pool and MED=high on another
                    # Both advertising the same prefixes from MED_HIGH/MED_LOW pools
                    create_bgp_prefixes_med_value_step(
                        prefix_pool_regex="PREFIX_POOL_.*_MED_LOW$",
                        prefix_start_index=0,
                        med_value=0,  # Explicit MED=0
                        description="Set explicit MED=0 on LOW MED prefix pools",
                    ),
                    # Start capture BEFORE advertising so we capture the updates
                    create_ixia_packet_capture_step(
                        device_name=device_name,
                        interface=ixia_interface_ibgp,
                        mode="start",
                        capture_filter="tcp port 179",
                        capture_id="phase4b_med_capture",
                        description="Start capture on iBGP interface for Phase 4b",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_HIGH$",
                        prefix_start_index=0,
                        description=f"Advertise routes with MED {med_high}",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_LOW$",
                        prefix_start_index=0,
                        description="Advertise routes with explicit MED=0",
                    ),
                ],
                periodic_tasks=[],
                prechecks=[],
                snapshot_checks=[
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[
                    create_bgp_rib_fib_consistency_check(),
                ],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for convergence ({convergence_wait_seconds}s)",
                            ),
                            # Stop and save packet capture
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_ibgp,
                                mode="stop",
                                capture_id="phase4b_med_capture",
                                description="Stop capture on iBGP interface",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_ibgp,
                                mode="save",
                                capture_id="phase4b_med_capture",
                                pcap_filename="bgp_med_phase4b.pcap",
                                description="Save Phase 4b packet capture",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_med_best_path",
                                    "hostname": device_name,
                                    "expected_med": 0,
                                    "prefix_filter": "2001:db8:3000::",
                                },
                                description="Verify explicit MED=0 beats higher MED values",
                            ),
                            # Verify MED in captured packets
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_med_in_pcap",
                                    "pcap_filename": "bgp_med_phase4b.pcap",
                                    "expected_med": 0,
                                    "min_updates_with_med": 1,
                                },
                                description="Verify MED=0 in PCAP sent to iBGP",
                            ),
                        ],
                    ),
                ],
            ),
            # Playbook 4c: Test MED ordering with three values
            # Verify correct preference: 0 < 10 < 100 (lower is better)
            build_bgp_med_playbook(
                name="BGP_MED_Test_Phase4c_MED_Ordering",
                setup_steps=[
                    # Withdraw all and re-advertise with original MED values
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_LOW$",
                        prefix_start_index=0,
                        description="Withdraw MED=0 routes",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_HIGH$",
                        prefix_start_index=0,
                        description="Withdraw MED high routes",
                    ),
                    # Reset MED_LOW to original value
                    create_bgp_prefixes_med_value_step(
                        prefix_pool_regex="PREFIX_POOL_.*_MED_LOW$",
                        prefix_start_index=0,
                        med_value=med_low,  # Back to original (10)
                        description=f"Reset MED to {med_low} on LOW MED prefix pools",
                    ),
                    # Set MED_HIGH to intermediate value (50)
                    create_bgp_prefixes_med_value_step(
                        prefix_pool_regex="PREFIX_POOL_.*_MED_HIGH$",
                        prefix_start_index=0,
                        med_value=50,  # Intermediate MED
                        description="Set MED=50 on HIGH MED prefix pools",
                    ),
                    # Start capture BEFORE advertising so we capture the updates
                    create_ixia_packet_capture_step(
                        device_name=device_name,
                        interface=ixia_interface_ibgp,
                        mode="start",
                        capture_filter="tcp port 179",
                        capture_id="phase4c_med_capture",
                        description="Start capture on iBGP interface for Phase 4c",
                    ),
                    # Advertise both - MED=10 should win over MED=50
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_HIGH$",
                        prefix_start_index=0,
                        description="Advertise routes with MED=50",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_LOW$",
                        prefix_start_index=0,
                        description=f"Advertise routes with MED={med_low}",
                    ),
                ],
                periodic_tasks=[],
                prechecks=[],
                snapshot_checks=[
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[
                    create_bgp_rib_fib_consistency_check(),
                ],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for convergence ({convergence_wait_seconds}s)",
                            ),
                            # Stop and save packet capture
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_ibgp,
                                mode="stop",
                                capture_id="phase4c_med_capture",
                                description="Stop capture on iBGP interface",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_ibgp,
                                mode="save",
                                capture_id="phase4c_med_capture",
                                pcap_filename="bgp_med_phase4c.pcap",
                                description="Save Phase 4c packet capture",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_med_best_path",
                                    "hostname": device_name,
                                    "expected_med": med_low,
                                    "prefix_filter": "2001:db8:3000::",
                                },
                                description=f"Verify MED={med_low} beats MED=50",
                            ),
                            # Verify MED in captured packets
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_med_in_pcap",
                                    "pcap_filename": "bgp_med_phase4c.pcap",
                                    "expected_med": med_low,
                                    "min_updates_with_med": 1,
                                },
                                description=f"Verify MED {med_low} in PCAP sent to iBGP",
                            ),
                        ],
                    ),
                ],
            ),
            # Playbook 4d: Restore MED_HIGH to original value for remaining tests
            build_bgp_med_playbook(
                name="BGP_MED_Test_Phase4d_Restore_MED_Values",
                setup_steps=[
                    # Reset MED_HIGH back to original value for subsequent tests
                    create_bgp_prefixes_med_value_step(
                        prefix_pool_regex="PREFIX_POOL_.*_MED_HIGH$",
                        prefix_start_index=0,
                        med_value=med_high,  # Back to original (100)
                        description=f"Reset MED to {med_high} on HIGH MED prefix pools",
                    ),
                    # Withdraw routes to clean up for next phase
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_LOW$",
                        prefix_start_index=0,
                        description="Withdraw MED low routes",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_HIGH$",
                        prefix_start_index=0,
                        description="Withdraw MED high routes",
                    ),
                ],
                periodic_tasks=[],
                prechecks=[],
                snapshot_checks=[
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            create_longevity_step(
                                duration=30,
                                description="Wait for cleanup (30s)",
                            ),
                        ],
                    ),
                ],
            ),
            # Playbook 5: ECMP Test - both groups advertise without MED
            build_bgp_med_playbook(
                name="BGP_MED_Test_Phase5_ECMP_Equal_MED",
                setup_steps=[
                    # Withdraw all MED routes
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_LOW_VS_NOMED",
                        prefix_start_index=0,
                        description="Withdraw MED low vs no-MED routes",
                    ),
                    # Advertise NO_MED routes from Group 1
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_NO_MED$",
                        prefix_start_index=0,
                        description="Advertise routes from Group 1 with no MED",
                    ),
                    # Advertise NO_MED_G2 routes from Group 2
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_NO_MED_G2",
                        prefix_start_index=0,
                        description="Advertise same routes from Group 2 with no MED",
                    ),
                ],
                periodic_tasks=[],
                prechecks=[],
                snapshot_checks=[
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[
                    create_bgp_rib_fib_consistency_check(),
                    # Verify ECMP - routes should have 2+ next-hops
                    create_next_hop_count_check(
                        min_nexthop_count=2,
                        prefix_subnets=["2001:db8:4000::/48", "10.250.0.0/16"],
                        check_id="verify_ecmp_equal_med",
                    ),
                ],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for convergence ({convergence_wait_seconds}s)",
                            ),
                        ],
                    ),
                ],
            ),
            # Playbook 6: Packet Capture - Verify MED is sent to iBGP peers
            build_bgp_med_playbook(
                name="BGP_MED_Test_Phase6_Verify_MED_Sent_To_IBGP",
                setup_steps=[
                    # Withdraw all routes first to start clean
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*",
                        prefix_start_index=0,
                        description="Withdraw all routes to reset state",
                    ),
                ],
                periodic_tasks=[],
                prechecks=[
                    create_bgp_session_establish_check(
                        expected_established_sessions_static=total_peers,
                        check_id="verify_bgp_sessions_before_capture",
                    ),
                ],
                snapshot_checks=[
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            # Start packet capture on iBGP interface
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_ibgp,
                                mode="start",
                                capture_filter="tcp port 179",
                                capture_id="med_ibgp_capture",
                                description="Start capture on iBGP interface for MED verification",
                            ),
                            # Wait briefly for capture to initialize
                            create_longevity_step(
                                duration=5,
                                description="Wait for capture to initialize (5s)",
                            ),
                            # Advertise routes with MED
                            create_advertise_withdraw_prefixes_step(
                                device_name=device_name,
                                advertise=True,
                                prefix_pool_regex="PREFIX_POOL_.*_MED_LOW$",
                                prefix_start_index=0,
                                description=f"Advertise routes with MED {med_low}",
                            ),
                            # Wait for routes to be sent to iBGP
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for routes to propagate to iBGP ({convergence_wait_seconds}s)",
                            ),
                            # Stop packet capture
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_ibgp,
                                mode="stop",
                                capture_id="med_ibgp_capture",
                                description="Stop capture on iBGP interface",
                            ),
                            # Save packet capture
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_ibgp,
                                mode="save",
                                capture_id="med_ibgp_capture",
                                pcap_filename="bgp_med_ibgp.pcap",
                                description="Save iBGP packet capture",
                            ),
                            # Verify MED is in the captured packets
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_med_in_pcap",
                                    "pcap_filename": "bgp_med_ibgp.pcap",
                                    "expected_med": med_low,
                                    "min_updates_with_med": 1,
                                },
                                description="Verify MED attribute is present in BGP updates to iBGP",
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )
