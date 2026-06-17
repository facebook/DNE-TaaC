# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

"""
BGP Weight Feature Test for EOS BGP++

This test validates the BGP weight attribute functionality in EOS BGP++.

Test Design - EBGP to IBGP Scenario:
    - IXIA mimics EBGP peers sending routes with different communities
    - Device applies weight based on community matching in ingress policy (EB-FA-IN)
    - IXIA mimics IBGP peers as listeners to verify best path selection
    - Routes with higher weight should be selected as best

Test Scenario:
    1. Create 2 eBGP device groups on ingress interface
       - Group 1: Advertises routes with community for weight 10
       - Group 2: Advertises SAME routes with community for weight 20
    2. Create iBGP listener peers on egress interface
    3. Apply BGP++ policy that matches communities and sets weight:
       - Match community 65001:10 -> set weight 10
       - Match community 65001:20 -> set weight 20
    4. Routes from group 2 (weight 20) should be selected as best
    5. Withdraw routes from group 2
    6. Verify routes from group 1 (weight 10) are now selected as best

BGP Weight Attribute:
    - Weight is used for local path selection
    - Higher weight is preferred
    - Weight is set via BGP++ policy (type=15, weight_action)
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
    build_bgp_weight_playbook,
)
from taac.routing.ebb.arista_feature_testing.ixia_configs_for_weight_test import (
    create_weight_test_basic_port_configs,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_advertise_withdraw_prefixes_step,
    create_custom_step,
    create_ixia_device_group_toggle_step,
    create_longevity_step,
)
from taac.task_definitions import (
    create_add_bgp_weight_policy_task,
    create_invoke_ixia_api_task,
    create_ixia_enable_disable_bgp_prefixes_task,
    create_replace_bgp_peers_task,
    create_restore_bgp_peers_task,
)
from taac.test_as_a_config.types import (
    DeviceOsType,
    DirectIxiaConnection,
    Endpoint,
    ParamValue,
    PointInTimeHealthCheck,
    Task,
    TestConfig,
)


def test_config_for_bgp_weight_feature(
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
    # Policy configuration
    target_policy: str = "EB-FA-IN",
    ssh_user: str = "admin",
    ssh_password: str = "",
    # Peer counts
    ebgp_peer_count_group1: int = 50,
    ebgp_peer_count_group2: int = 50,
    ibgp_peer_count: int = 10,
    # Route configuration
    prefix_count: int = 100,
    # Weight configuration
    weight_low: int = 10,
    weight_high: int = 20,
    weight_low_community: str = "65001:10",
    weight_high_community: str = "65001:20",
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
    Create a test configuration for BGP weight feature testing.

    This test validates that:
    1. Routes with higher weight are preferred over routes with lower weight
    2. When higher-weight routes are withdrawn, lower-weight routes become best
    3. Weight is correctly applied via BGP++ policy matching BGP communities

    Test Design - EBGP to IBGP Scenario:
        - eBGP interface: Two device groups advertise same routes with different communities
        - Device applies weight based on community matching in ingress policy
        - iBGP interface: Listener peers receive best routes

    Args:
        test_config_name: Name for the test configuration
        device_name: Name of the device under test
        ixia_interface_ebgp: IXIA interface for eBGP peers (ingress)
        ebgp_remote_as: AS number for eBGP peers
        ixia_ebgp_ic_parent_network_v6: IPv6 network for eBGP peers
        ixia_ebgp_ic_parent_network_v4: IPv4 network for eBGP peers
        ixia_interface_ibgp: IXIA interface for iBGP peers (egress/listeners)
        ibgp_local_as: AS number for iBGP peers (same as DUT)
        ixia_ibgp_ic_parent_network_v6: IPv6 network for iBGP peers
        ixia_ibgp_ic_parent_network_v4: IPv4 network for iBGP peers
        target_policy: Target policy to add weight entries to (default: EB-FA-IN)
        ssh_user: SSH username for device access (default: admin)
        ssh_password: SSH password for device access
        ebgp_peer_count_group1: Number of eBGP peers in group 1 (lower weight)
        ebgp_peer_count_group2: Number of eBGP peers in group 2 (higher weight)
        ibgp_peer_count: Number of iBGP listener peers
        prefix_count: Number of prefixes per peer to advertise
        weight_low: Weight value for group 1 routes (default 10)
        weight_high: Weight value for group 2 routes (default 20)
        weight_low_community: Community that maps to lower weight
        weight_high_community: Community that maps to higher weight
        ebgp_route_acceptance_communities: Acceptance communities for eBGP routes
        test_address_families: Address families to test (default: ["ipv6"])
        convergence_wait_seconds: Time to wait for BGP convergence
        direct_ixia_connections: Direct IXIA connection specifications
        log_collection_timeout: Timeout for log collection
        host_os_type_map: OS type mapping for hosts
        host_driver_args: Driver arguments for hosts

    Returns:
        TestConfig object for the BGP weight feature test
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

    # Total eBGP peers per AF for device config (both weight groups combined)
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

    # Build community to weight mapping
    community_weight_map = {
        weight_low_community: weight_low,
        weight_high_community: weight_high,
    }

    # Build setup tasks for EOS BGP++ device
    setup_tasks: list[Task] = [
        # Task 1: Replace BGP peers with minimal test peers
        create_replace_bgp_peers_task(
            hostname=device_name,
            peer_configs=peer_groups,
        ),
        # Task 2: Add weight policy entries to the target policy
        create_add_bgp_weight_policy_task(
            hostname=device_name,
            target_policy=target_policy,
            community_weight_map=community_weight_map,
            ssh_user=ssh_user,
            ssh_password=ssh_password,
        ),
        # Task 3: Disable prefix pools initially
        create_ixia_enable_disable_bgp_prefixes_task(
            enable=False,
            prefix_pool_regex="PREFIX_POOL_.*",
            prefix_start_index=0,
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
        ],
        # Deprecated - define at playbook level
        # prechecks=[],
        # postchecks=[],
        # snapshot_checks=[],
        basic_port_configs=create_weight_test_basic_port_configs(
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
            weight_10_community=weight_low_community,
            weight_20_community=weight_high_community,
            ebgp_route_acceptance_communities=ebgp_route_acceptance_communities,
            test_address_families=test_address_families,
        ),
        playbooks=[
            # Playbook 1: Both groups advertise - verify higher weight is best
            build_bgp_weight_playbook(
                name="BGP_Weight_Test_Phase1_Both_Groups_Active",
                setup_steps=[
                    create_ixia_device_group_toggle_step(
                        enable=True,
                        device_group_name_regex=".*",
                        description="Enable all BGP peer device groups",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_WEIGHT_10",
                        prefix_start_index=0,
                        description=f"Advertise routes from eBGP Group 1 (weight {weight_low})",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_WEIGHT_20",
                        prefix_start_index=0,
                        description=f"Advertise routes from eBGP Group 2 (weight {weight_high})",
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
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for BGP convergence ({convergence_wait_seconds}s)",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_weight_best_path",
                                    "hostname": device_name,
                                    "expected_weight": weight_high,
                                    "expected_community": weight_high_community,
                                },
                                description=f"Verify routes with weight {weight_high} are selected as best",
                            ),
                        ],
                    ),
                ],
            ),
            # Playbook 2: Withdraw Group 2 - verify lower weight becomes best
            build_bgp_weight_playbook(
                name="BGP_Weight_Test_Phase2_Group2_Withdrawn",
                setup_steps=[
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_WEIGHT_20",
                        prefix_start_index=0,
                        description=f"Withdraw routes from eBGP Group 2 (weight {weight_high})",
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
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_weight_best_path",
                                    "hostname": device_name,
                                    "expected_weight": weight_low,
                                    "expected_community": weight_low_community,
                                },
                                description=f"Verify routes with weight {weight_low} are now best",
                            ),
                        ],
                    ),
                ],
            ),
            # Playbook 3: Re-advertise Group 2 - verify higher weight is best again
            build_bgp_weight_playbook(
                name="BGP_Weight_Test_Phase3_Group2_Readvertised",
                setup_steps=[
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_WEIGHT_20",
                        prefix_start_index=0,
                        description=f"Re-advertise routes from eBGP Group 2 (weight {weight_high})",
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
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_weight_best_path",
                                    "hostname": device_name,
                                    "expected_weight": weight_high,
                                    "expected_community": weight_high_community,
                                },
                                description=f"Verify routes with weight {weight_high} are best again",
                            ),
                        ],
                    ),
                ],
            ),
            # Playbook 4: Weight vs No-Weight - verify explicit weight beats default weight
            # This tests that routes with explicit weight (20) are preferred over
            # routes with no weight set (default weight 0)
            build_bgp_weight_playbook(
                name="BGP_Weight_Test_Phase4_Weight_Vs_NoWeight",
                setup_steps=[
                    # First withdraw all WEIGHT_10 and WEIGHT_20 routes
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_WEIGHT_10",
                        prefix_start_index=0,
                        description="Withdraw weight 10 routes",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_WEIGHT_20$",
                        prefix_start_index=0,
                        description="Withdraw weight 20 routes",
                    ),
                    # Advertise NO_WEIGHT routes (only acceptance community, default weight 0)
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_NO_WEIGHT$",
                        prefix_start_index=0,
                        description="Advertise routes with no weight (default weight 0)",
                    ),
                    # Advertise WEIGHT_20_VS_NOWEIGHT routes (same prefixes with weight 20)
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_WEIGHT_20_VS_NOWEIGHT",
                        prefix_start_index=0,
                        description=f"Advertise same routes with weight {weight_high}",
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
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_weight_best_path",
                                    "hostname": device_name,
                                    "expected_weight": weight_high,
                                    "expected_community": weight_high_community,
                                    # Use the NO_WEIGHT prefix range for verification
                                    "prefix_filter": "2001:db8:2000::",
                                },
                                description=f"Verify routes with weight {weight_high} are selected over default weight (0)",
                            ),
                        ],
                    ),
                ],
            ),
            # Playbook 5: ECMP Test - both groups advertise without weight community
            # When both groups have default weight (0), both routes should be selected as best
            build_bgp_weight_playbook(
                name="BGP_Weight_Test_Phase5_ECMP_Equal_Weight",
                setup_steps=[
                    # Withdraw all weighted routes first
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_WEIGHT_10",
                        prefix_start_index=0,
                        description="Withdraw weight 10 routes",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_WEIGHT_20$",
                        prefix_start_index=0,
                        description="Withdraw weight 20 routes",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_WEIGHT_20_VS_NOWEIGHT",
                        prefix_start_index=0,
                        description="Withdraw weight 20 vs no-weight routes",
                    ),
                    # Advertise NO_WEIGHT routes from Group 1 (default weight 0)
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_NO_WEIGHT$",
                        prefix_start_index=0,
                        description="Advertise routes from Group 1 with no weight (default 0)",
                    ),
                    # Advertise NO_WEIGHT_G2 routes from Group 2 (same prefixes, default weight 0)
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_NO_WEIGHT_G2",
                        prefix_start_index=0,
                        description="Advertise same routes from Group 2 with no weight (default 0)",
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
                        prefix_subnets=[
                            "2001:db8:2000::/48",
                            "10.200.0.0/16",
                        ],
                        check_id="verify_ecmp_equal_weight",
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
        ],
    )
