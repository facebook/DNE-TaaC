# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

"""
BGP enforce_first_as Feature Test for EOS BGP++

This test validates the BGP enforce_first_as security feature in EOS BGP++.

Test Design:
    - enforce_first_as validates that the first AS in AS_PATH matches the peer's remote AS
    - When enabled, routes with mismatched first AS are rejected
    - Routes from eBGP peers should have AS_PATH starting with the peer's AS

Test Scenario:
    1. Create 2 eBGP device groups on ingress interface:
       - Group 1 (VALID): Routes with correct AS_PATH (first AS = peer's AS)
       - Group 2 (INVALID): Routes with wrong first AS in AS_PATH
    2. Create iBGP listener peers on egress interface
    3. Phase 0: With enforce_first_as=false, both routes should be accepted
    4. Phase 1: With enforce_first_as=true, only valid routes should be accepted,
       invalid routes should be rejected and reject counter should increment
"""

from collections.abc import Mapping, Sequence

from taac.health_checks.healthcheck_definitions import (
    create_bgp_rib_fib_consistency_check,
    create_bgp_session_establish_check,
    create_bgp_session_snapshot_check,
    create_core_dumps_snapshot_check,
)
from taac.playbooks.playbook_definitions import (
    build_enforce_first_as_playbook,
)
from taac.routing.ebb.arista_feature_testing.ixia_configs_for_enforce_first_as_test import (
    create_enforce_first_as_test_basic_port_configs,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_advertise_withdraw_prefixes_step,
    create_custom_step,
    create_ixia_device_group_toggle_step,
    create_longevity_step,
    create_run_task_step,
)
from taac.task_definitions import (
    create_invoke_ixia_api_task,
    create_ixia_enable_disable_bgp_prefixes_task,
    create_replace_bgp_peers_task,
    create_restore_bgp_peers_task,
    create_set_peer_group_enforce_first_as_task,
)
from taac.test_as_a_config.types import (
    DeviceOsType,
    DirectIxiaConnection,
    Endpoint,
    ParamValue,
    PointInTimeHealthCheck,
    Step,
    Task,
    TestConfig,
)


def test_config_for_bgp_enforce_first_as_feature(
    test_config_name: str,
    device_name: str,
    # eBGP interface (ingress - routes come in here)
    ixia_interface_ebgp: str,
    ebgp_remote_as: int,
    wrong_first_as: int,  # The wrong AS to prepend for invalid routes
    ixia_ebgp_ic_parent_network_v6: str,
    ixia_ebgp_ic_parent_network_v4: str,
    # iBGP interface (egress - listeners)
    ixia_interface_ibgp: str,
    ibgp_local_as: int,
    ixia_ibgp_ic_parent_network_v6: str,
    ixia_ibgp_ic_parent_network_v4: str,
    # Peer groups to configure enforce_first_as on
    peer_groups: list[str] | None = None,
    # SSH credentials
    ssh_user: str = "admin",
    ssh_password: str = "",
    # Peer counts
    ebgp_peer_count_valid: int = 10,
    ebgp_peer_count_invalid: int = 10,
    ibgp_peer_count: int = 10,
    # Route configuration
    prefix_count: int = 100,
    # Route acceptance communities
    ebgp_route_acceptance_communities: list[str] | None = None,
    # Address family selection
    test_address_families: list[str] | None = None,
    # Test control
    convergence_wait_seconds: int = 120,
    direct_ixia_connections: Sequence[DirectIxiaConnection] | None = None,
    log_collection_timeout: int | None = None,
    # pyre-fixme[2]: Parameter must be annotated.
    oss_mock_device_data=None,
    host_os_type_map: Mapping[str, DeviceOsType] | None = None,
    host_driver_args: dict[str, str] | None = None,
) -> TestConfig:
    """
    Create a test configuration for BGP enforce_first_as feature testing.

    This test validates that:
    1. With enforce_first_as=false: All routes are accepted regardless of AS_PATH
    2. With enforce_first_as=true: Only routes with correct first AS are accepted
    3. Routes with wrong first AS are rejected and reject counter increments

    Test Design:
        - eBGP interface: Two device groups (same remote AS for session establishment)
          * Valid group: Routes with AS_PATH = [ebgp_remote_as] (correct)
          * Invalid group: Routes with AS_PATH = [wrong_first_as, ebgp_remote_as]
        - iBGP interface: Listener peers to verify route propagation

    Args:
        test_config_name: Name for the test configuration
        device_name: Name of the device under test
        ixia_interface_ebgp: IXIA interface for eBGP peers (ingress)
        ebgp_remote_as: AS number for eBGP peers (same for both groups)
        wrong_first_as: Wrong AS number to prepend for invalid routes
        ixia_ebgp_ic_parent_network_v6: IPv6 network for eBGP peers
        ixia_ebgp_ic_parent_network_v4: IPv4 network for eBGP peers
        ixia_interface_ibgp: IXIA interface for iBGP peers (egress/listeners)
        ibgp_local_as: AS number for iBGP peers (same as DUT)
        ixia_ibgp_ic_parent_network_v6: IPv6 network for iBGP peers
        ixia_ibgp_ic_parent_network_v4: IPv4 network for iBGP peers
        peer_groups: Peer groups to configure enforce_first_as on (default: EB-FA-V6, EB-FA-V4)
        ssh_user: SSH username for device access (default: admin)
        ssh_password: SSH password for device access
        ebgp_peer_count_valid: Number of eBGP peers with valid AS_PATH
        ebgp_peer_count_invalid: Number of eBGP peers with invalid AS_PATH
        ibgp_peer_count: Number of iBGP listener peers
        prefix_count: Number of prefixes per peer to advertise
        ebgp_route_acceptance_communities: Acceptance communities for eBGP routes
        test_address_families: Address families to test (default: ["ipv6"])
        convergence_wait_seconds: Time to wait for BGP convergence
        direct_ixia_connections: Direct IXIA connection specifications
        log_collection_timeout: Timeout for log collection
        oss_mock_device_data: OSS-compatible mock device data
        host_os_type_map: OS type mapping for hosts
        host_driver_args: Driver arguments for hosts

    Returns:
        TestConfig object for the BGP enforce_first_as feature test
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

    # Calculate total peer count for session checks
    num_afs = len(test_address_families)
    total_ebgp_peers = (ebgp_peer_count_valid + ebgp_peer_count_invalid) * num_afs
    total_ibgp_peers = ibgp_peer_count * num_afs
    total_peers = total_ebgp_peers + total_ibgp_peers

    # Total eBGP peers per AF for device config (both groups combined)
    total_ebgp_per_af = ebgp_peer_count_valid + ebgp_peer_count_invalid

    # Calculate expected route counts (prefixes * peers per group * address families)
    expected_valid_routes = prefix_count * ebgp_peer_count_valid * num_afs
    expected_invalid_routes = prefix_count * ebgp_peer_count_invalid * num_afs

    # Build prefix filters based on address families being tested
    valid_prefix_filters: list[str] = []
    invalid_prefix_filters: list[str] = []
    if "ipv6" in test_address_families:
        valid_prefix_filters.append("2001:db8:10")
        invalid_prefix_filters.append("2001:db8:20")
    if "ipv4" in test_address_families:
        # Use broader filter to match all IPv4 prefixes (10.100-10.199 and 10.200-10.255)
        valid_prefix_filters.append("10.1")
        invalid_prefix_filters.append("10.2")

    # Build peer_groups config for replace_bgp_peers task
    peer_group_configs = []
    if "ipv6" in test_address_families:
        # eBGP IPv6 peers
        peer_group_configs.append(
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
        peer_group_configs.append(
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
        peer_group_configs.append(
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
        peer_group_configs.append(
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
    # Note: enforce_first_as is NOT enabled in setup - Phase 0 tests behavior without it
    setup_tasks: list[Task] = [
        # Task 1: Replace BGP peers with minimal test peers
        create_replace_bgp_peers_task(
            hostname=device_name,
            peer_configs=peer_group_configs,
        ),
        # Task 2: Disable prefix pools initially
        create_ixia_enable_disable_bgp_prefixes_task(
            enable=False,
            prefix_pool_regex="PREFIX_POOL_.*",
            prefix_start_index=0,
        ),
    ]

    # Helper to create set_peer_group_enforce_first_as step
    def create_set_enforce_first_as_step(
        enable: bool,
        description: str | None = None,
    ) -> Step:
        action = "Enable" if enable else "Disable"
        if description is None:
            description = f"{action} enforce_first_as on peer groups: {peer_groups}"

        return create_run_task_step(
            task_name="set_peer_group_enforce_first_as",
            params_dict={
                "hostname": device_name,
                "peer_groups": peer_groups,
                "enforce_first_as": enable,
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
            # Disable enforce_first_as (restore default behavior)
            create_set_peer_group_enforce_first_as_task(
                hostname=device_name,
                peer_groups=peer_groups,
                enforce_first_as=False,
                ssh_user=ssh_user,
                ssh_password=ssh_password,
            ),
        ],
        # Deprecated - define at playbook level
        # prechecks=[],
        # postchecks=[],
        # snapshot_checks=[],
        basic_port_configs=create_enforce_first_as_test_basic_port_configs(
            device_name=device_name,
            # eBGP interface (ingress)
            ixia_interface_ebgp=ixia_interface_ebgp,
            ebgp_peer_count_valid=ebgp_peer_count_valid,
            ebgp_peer_count_invalid=ebgp_peer_count_invalid,
            ebgp_remote_as=ebgp_remote_as,
            wrong_first_as=wrong_first_as,
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
            # Playbook 0: enforce_first_as=false - verify all routes are accepted
            build_enforce_first_as_playbook(
                name="BGP_Enforce_First_AS_Test_Phase0_Feature_Disabled",
                setup_steps=[
                    # First disable enforce_first_as to ensure it's off
                    create_set_enforce_first_as_step(
                        enable=False,
                        description="Disable enforce_first_as for Phase 0 test",
                    ),
                    create_ixia_device_group_toggle_step(
                        enable=True,
                        device_group_name_regex=".*",
                        description="Enable all BGP peer device groups",
                    ),
                    # Advertise routes from both valid and invalid AS groups
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_EBGP_VALID_AS$",
                        prefix_start_index=0,
                        description="Advertise routes from VALID AS group",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_EBGP_INVALID_AS$",
                        prefix_start_index=0,
                        description="Advertise routes from INVALID AS group",
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
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for BGP convergence ({convergence_wait_seconds}s)",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_enforce_first_as_routes",
                                    "hostname": device_name,
                                    "enforce_first_as_enabled": False,
                                    "valid_prefix_filters": valid_prefix_filters,
                                    "invalid_prefix_filters": invalid_prefix_filters,
                                    "expected_valid_route_count": expected_valid_routes,
                                    "expected_invalid_route_count": expected_invalid_routes,
                                },
                                description="Verify ALL routes accepted (enforce_first_as disabled)",
                            ),
                        ],
                    ),
                ],
            ),
            # Playbook 1: Enable enforce_first_as - verify only valid routes accepted
            build_enforce_first_as_playbook(
                name="BGP_Enforce_First_AS_Test_Phase1_Feature_Enabled",
                setup_steps=[
                    # Enable device groups first (needed when running Phase 1 independently)
                    create_ixia_device_group_toggle_step(
                        enable=True,
                        device_group_name_regex=".*",
                        description="Enable all BGP peer device groups",
                    ),
                    # Advertise VALID routes (needed when running Phase 1 independently)
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_EBGP_VALID_AS$",
                        prefix_start_index=0,
                        description="Advertise routes from VALID AS group",
                    ),
                    # Get baseline reject count before enabling
                    create_custom_step(
                        params_dict={
                            "custom_step_name": "get_enforce_first_as_rejects_baseline",
                            "hostname": device_name,
                        },
                        description="Get baseline enforce_first_as reject count",
                    ),
                    # Enable enforce_first_as
                    create_set_enforce_first_as_step(
                        enable=True,
                        description="Enable enforce_first_as for Phase 1 test",
                    ),
                ],
                periodic_tasks=[],
                prechecks=[
                    create_bgp_session_establish_check(
                        expected_established_sessions_static=total_peers,
                        check_id="verify_all_bgp_sessions_established_phase1",
                    ),
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
                            # Withdraw invalid routes first
                            create_advertise_withdraw_prefixes_step(
                                device_name=device_name,
                                advertise=False,
                                prefix_pool_regex="PREFIX_POOL_.*_EBGP_INVALID_AS$",
                                prefix_start_index=0,
                                description="Withdraw INVALID AS routes",
                            ),
                            create_longevity_step(
                                duration=30,
                                description="Wait for withdrawal (30s)",
                            ),
                            # Re-advertise invalid routes - now should be rejected
                            create_advertise_withdraw_prefixes_step(
                                device_name=device_name,
                                advertise=True,
                                prefix_pool_regex="PREFIX_POOL_.*_EBGP_INVALID_AS$",
                                prefix_start_index=0,
                                description="Re-advertise INVALID AS routes",
                            ),
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for BGP convergence ({convergence_wait_seconds}s)",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_enforce_first_as_routes",
                                    "hostname": device_name,
                                    "enforce_first_as_enabled": True,
                                    "valid_prefix_filters": valid_prefix_filters,
                                    "invalid_prefix_filters": invalid_prefix_filters,
                                    "expected_valid_route_count": expected_valid_routes,
                                    "expected_invalid_route_count": 0,
                                },
                                description="Verify only VALID routes accepted (enforce_first_as enabled)",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_enforce_first_as_rejects_increased",
                                    "hostname": device_name,
                                    "min_rejects": 1,
                                },
                                description="Verify enforce_first_as reject counter increased",
                            ),
                        ],
                    ),
                ],
            ),
            # Playbook 2: Re-advertise invalid routes - verify they're still rejected
            build_enforce_first_as_playbook(
                name="BGP_Enforce_First_AS_Test_Phase2_Readvertise_Invalid",
                setup_steps=[
                    # Enable device groups first (needed when running Phase 2 independently)
                    create_ixia_device_group_toggle_step(
                        enable=True,
                        device_group_name_regex=".*",
                        description="Enable all BGP peer device groups",
                    ),
                    # Advertise VALID routes (needed when running Phase 2 independently)
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_EBGP_VALID_AS$",
                        prefix_start_index=0,
                        description="Advertise routes from VALID AS group",
                    ),
                    # Enable enforce_first_as (needed when running Phase 2 independently)
                    create_set_enforce_first_as_step(
                        enable=True,
                        description="Enable enforce_first_as for Phase 2 test",
                    ),
                    # Withdraw and re-advertise invalid routes
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_EBGP_INVALID_AS$",
                        prefix_start_index=0,
                        description="Withdraw INVALID AS routes",
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
                                description="Wait for withdrawal (30s)",
                            ),
                            # Get current reject count before re-advertising
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "get_enforce_first_as_rejects_baseline",
                                    "hostname": device_name,
                                },
                                description="Get current enforce_first_as reject count",
                            ),
                            # Re-advertise invalid routes
                            create_advertise_withdraw_prefixes_step(
                                device_name=device_name,
                                advertise=True,
                                prefix_pool_regex="PREFIX_POOL_.*_EBGP_INVALID_AS$",
                                prefix_start_index=0,
                                description="Re-advertise INVALID AS routes",
                            ),
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for re-advertisement ({convergence_wait_seconds}s)",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_enforce_first_as_routes",
                                    "hostname": device_name,
                                    "enforce_first_as_enabled": True,
                                    "valid_prefix_filters": valid_prefix_filters,
                                    "invalid_prefix_filters": invalid_prefix_filters,
                                    "expected_valid_route_count": expected_valid_routes,
                                    "expected_invalid_route_count": 0,
                                },
                                description="Verify INVALID routes still rejected after re-advertise",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_enforce_first_as_rejects_increased",
                                    "hostname": device_name,
                                    "min_rejects": 1,
                                },
                                description="Verify reject counter increased again",
                            ),
                        ],
                    ),
                ],
            ),
            # Playbook 3: Disable enforce_first_as - verify invalid routes now accepted
            build_enforce_first_as_playbook(
                name="BGP_Enforce_First_AS_Test_Phase3_Feature_Disabled_Again",
                setup_steps=[
                    # Enable device groups first (needed when running Phase 3 independently)
                    create_ixia_device_group_toggle_step(
                        enable=True,
                        device_group_name_regex=".*",
                        description="Enable all BGP peer device groups",
                    ),
                    # Advertise VALID routes (needed when running Phase 3 independently)
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_EBGP_VALID_AS$",
                        prefix_start_index=0,
                        description="Advertise routes from VALID AS group",
                    ),
                    # Advertise INVALID routes (needed when running Phase 3 independently)
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_EBGP_INVALID_AS$",
                        prefix_start_index=0,
                        description="Advertise routes from INVALID AS group",
                    ),
                    # Disable enforce_first_as
                    create_set_enforce_first_as_step(
                        enable=False,
                        description="Disable enforce_first_as for Phase 3 test",
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
                                description=f"Wait for BGP convergence ({convergence_wait_seconds}s)",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_enforce_first_as_routes",
                                    "hostname": device_name,
                                    "enforce_first_as_enabled": False,
                                    "valid_prefix_filters": valid_prefix_filters,
                                    "invalid_prefix_filters": invalid_prefix_filters,
                                    "expected_valid_route_count": expected_valid_routes,
                                    "expected_invalid_route_count": expected_invalid_routes,
                                },
                                description="Verify ALL routes accepted again (enforce_first_as disabled)",
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )
