# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
Test Config for BGP++ Constant Total Paths Test

This test validates that BGP++ memory depends ONLY on unique attributes,
NOT on how routes are distributed across peers.

Test Design - Constant Total Paths:
    Maintains a CONSTANT total number of ingress paths (default: 400K) across
    all test iterations by adjusting prefix count per peer.

    Peer counts represent TOTAL sessions (IPv4 + IPv6 combined):
        peer_count=8 means 4 IPv4 peers + 4 IPv6 peers = 8 total sessions

    Example with constant_total_paths=400K:
        8 peers (4v4+4v6)   × 50,000 prefixes/peer = 400K total paths
        16 peers (8v4+8v6)  × 25,000 prefixes/peer = 400K total paths
        32 peers (16v4+16v6) × 12,500 prefixes/peer = 400K total paths
        64 peers (32v4+32v6) × 6,250 prefixes/peer  = 400K total paths
        128 peers (64v4+64v6) × 3,125 prefixes/peer  = 400K total paths

    All 400K paths use attributes from the SAME limited pools:
        - 100 unique AS paths
        - 50 unique communities
        - 50 unique extended communities

    Attribute Assignment Modes:
        Sequential (randomize_attributes=False, default):
            - Paths cycle through attribute pools in order: 0,1,2...N,0,1,2...
            - Predictable, evenly distributed attribute usage
            - Best for testing minimum attribute storage efficiency
            - Example with 4 routes, 2 AS paths {AS1, AS2}, 2 communities {C1, C2}:
              Route 0 → {AS1, C1}
              Route 1 → {AS2, C2}
              Route 2 → {AS1, C1}  (reuses same combination)
              Route 3 → {AS2, C2}  (reuses same combination)
            - Result: 2 unique attribute combinations, maximum reuse

        Random (randomize_attributes=True):
            - Each path randomly picks attributes from pools
            - Creates maximum diversity within pool constraints
            - Best for testing realistic/extreme attribute distribution
            - Use random_seed parameter for reproducible results
            - Example with 4 routes, 2 AS paths {AS1, AS2}, 2 communities {C1, C2}:
              Route 0 → {AS1, C1}
              Route 1 → {AS1, C2}
              Route 2 → {AS2, C1}
              Route 3 → {AS2, C2}
            - Result: 4 unique attribute combinations (all possible combos)

        Key Validation:
            Both modes use the SAME individual attributes (2 AS paths, 2 communities)
            but create DIFFERENT combinations (2 combos vs 4 combos).
            If memory is the same → proves memory depends on individual values, not combinations!

    Expected Result:
        Memory should remain CONSTANT across all iterations since:
        - Total paths are constant (400K)
        - Unique attribute pools are constant
        - Only the distribution across peers changes

    This proves BGP++ memory depends on unique attributes, not peer count!
"""

from typing import List

from ixia.ixia import types as ixia_types
from taac.playbooks.playbook_definitions import (
    build_case2_playbook,
)
from taac.routing.ebb.arista_bgp_plus_plus_performance_scaling_tests.attribute_pool_generator import (
    generate_as_path_pool,
    generate_community_pool,
    generate_extended_community_pool,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import create_custom_step
from taac.test_as_a_config.types import (
    BasicPortConfig,
    BgpConfig,
    DeviceGroupConfig,
    Endpoint,
    IpAddressesConfig,
    RouteScale,
    RouteScaleSpec,
    Task,
    TestConfig,
)


def test_config_constant_attribute_storage_on_eos(
    test_config_name: str,
    device_name: str,
    ixia_interface_mimic_ebgp: str,
    ebgp_remote_as: int,
    ixia_ebgp_ic_parent_network_v6: str,
    ixia_ebgp_ic_parent_network_v4: str,
    ebgp_peer_counts: List[int],  # e.g., [8, 16, 32, 64, 128]
    constant_total_paths: int = 400000,  # Constant total ingress paths across all iterations
    # Attribute pool sizes - control for baseline vs attack tests
    as_path_pool_size: int = 100,  # Number of unique AS paths (100 = baseline, 800K = attack)
    community_pool_size: int = 50,  # Number of unique communities (50 = baseline)
    extended_community_pool_size: int = 50,  # Number of unique ext-communities (50 = baseline)
    as_path_length: int = 4,  # Number of AS numbers per AS path
    constant_acceptance_communities: List[str] | None = None,  # e.g., ["65529:39744"]
    max_communities_per_route_from_pool: int
    | None = None,  # Optional limit (default: use all)
    randomize_attributes: bool = False,  # Enable random attribute assignment
    random_seed: int = 42,  # Random seed for reproducibility
    test_route_withdrawal: bool = False,  # Test route withdrawal and memory cleanup
    withdrawal_wait_minutes: int = 3,  # Wait time after withdrawal
    dump_attribute_assignments: bool = True,  # Dump attribute assignments for verification (default: True)
    soak_time_minutes: int = 10,
    direct_ixia_connections: List | None = None,
    log_collection_timeout: int | None = None,
    oss_mock_device_data=None,
    host_os_type_map=None,
    host_driver_args=None,
):
    """
    Create test config for BGP++ constant total paths test on Arista EOS.

    This test uses ONLY EBGP peers (no IBGP) to prove that memory usage depends
    only on unique attributes, NOT on how routes are distributed across peers.

    Test Design - Constant Total Paths:
        The custom step maintains constant total ingress paths (default: 400K)
        by calculating prefix_count = constant_total_paths / peer_count for each iteration.

        Example with constant_total_paths=400K and peer_count=8:
            8 total peers = 4 IPv4 + 4 IPv6
            prefix_count = 400K / 8 = 50,000 per peer
            Total: 4 IPv4 peers x 50K + 4 IPv6 peers x 50K = 400K paths

    Baseline vs High Diversity Tests:
        Baseline Test (Default):
            as_path_pool_size=100, community_pool_size=50, extended_community_pool_size=50
            Expected: ~2300 MB constant across all peer counts

        High Diversity Test (Maximum Unique Attributes):
            as_path_pool_size=800000, community_pool_size=50, extended_community_pool_size=50
            Expected: ~4500 MB constant across all peer counts (higher but still constant)
            Proves: Memory depends on unique AS paths, not peer distribution

    Attribute Assignment Modes:
        Sequential (randomize_attributes=False):
            - Paths cycle through attribute pools in order: 0,1,2...N,0,1,2...
            - Predictable, evenly distributed attribute usage
            - Best for testing minimum attribute storage efficiency

        Random (randomize_attributes=True):
            - Each path randomly picks attributes from pools
            - Creates maximum diversity within pool constraints
            - Best for testing realistic/extreme attribute distribution
            - Use random_seed for reproducible tests

    Args:
        test_config_name: Name of the test configuration
        device_name: Device under test (DUT) hostname
        ixia_interface_mimic_ebgp: Interface for EBGP peers
        ebgp_remote_as: EBGP remote AS number
        ixia_ebgp_ic_parent_network_v6: IPv6 network for EBGP
        ixia_ebgp_ic_parent_network_v4: IPv4 network for EBGP
        ebgp_peer_counts: List of TOTAL peer counts to test (e.g., [8, 16, 32])
                          Each count is split evenly: N/2 IPv4 + N/2 IPv6
        constant_total_paths: Total ingress paths to maintain across iterations (default: 400000)
        as_path_pool_size: Number of unique AS paths (default: 100 for baseline, 800000 for high diversity)
        community_pool_size: Number of unique communities (default: 50)
        extended_community_pool_size: Number of unique ext-communities (default: 50)
        as_path_length: Number of AS numbers per AS path (default: 4)
        constant_acceptance_communities: Communities required by BGP policy (e.g., ["65529:39744"])
        max_communities_per_route_from_pool: Optional limit on communities per route from pool
        randomize_attributes: If True, randomly assign attributes; if False, cycle sequentially (default: False)
        random_seed: Random seed for reproducible random attribute assignment (default: 42)
        test_route_withdrawal: Test route withdrawal and memory cleanup (default: False)
        withdrawal_wait_minutes: Wait time after withdrawal (default: 3)
        dump_attribute_assignments: Dump attribute assignments for verification (default: True)
        soak_time_minutes: Soak time in minutes (default: 10)
        direct_ixia_connections: Optional direct IXIA connections
        log_collection_timeout: Optional log collection timeout
        host_os_type_map: Optional host OS type mapping
        host_driver_args: Optional host driver arguments

    Returns:
        TestConfig for the constant total paths test
    """
    # Start with minimal peer count for initial Ixia configuration
    # Custom step will dynamically adjust during test iterations
    initial_ebgp_peer_count = 1

    # Generate attribute pools using provided parameters
    # For baseline test: as_path_pool_size=100 (default)
    # For high diversity test: as_path_pool_size=800000 (pass as parameter)
    as_path_pool = generate_as_path_pool(
        count=as_path_pool_size,
        base_as=65000,
        as_path_length=as_path_length,
    )

    community_pool = generate_community_pool(
        count=community_pool_size,
        base_community=65000,
    )

    extended_community_pool = generate_extended_community_pool(
        count=extended_community_pool_size,
        base_rt=65000,
    )

    # Build ixia_ports list (only EBGP for this test)
    ixia_ports = [ixia_interface_mimic_ebgp]

    return TestConfig(
        name=test_config_name,
        skip_ixia_protocol_verification=True,
        log_collection_timeout=log_collection_timeout,
        basset_pool="dne.test",
        endpoints=[
            Endpoint(
                name=device_name,
                dut=True,
                ixia_ports=ixia_ports,  # Dynamic: EBGP + optional IBGP
                direct_ixia_connections=direct_ixia_connections
                if direct_ixia_connections
                else [],
            ),
        ],
        host_driver_args=host_driver_args,
        oss_mock_device_data=oss_mock_device_data,
        host_os_type_map=host_os_type_map,
        startup_checks=[],
        setup_tasks=[],
        teardown_tasks=[],
        # Deprecated - define at playbook level
        # prechecks=[],
        # postchecks=[],
        # snapshot_checks=[],
        basic_port_configs=[
            # EBGP configuration only - IBGP is not needed for this test
            BasicPortConfig(
                endpoint=f"{device_name}:{ixia_interface_mimic_ebgp}",
                device_group_configs=[
                    DeviceGroupConfig(
                        device_group_name="DEVICE_GROUP_IPV6_EBGP",
                        device_group_index=0,
                        multiplier=initial_ebgp_peer_count,
                        v6_addresses_config=IpAddressesConfig(
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
                            bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                            route_scales=[
                                RouteScaleSpec(
                                    v6_route_scale=RouteScale(
                                        prefix_name="PREFIX_POOL_IPV6_EBGP",
                                        starting_prefixes="2001:db8:1000::",
                                        prefix_step="0:0:1::",  # Increment subnet ID for /64 prefixes
                                        prefix_length=64,
                                        multiplier=1,
                                        prefix_count=1,  # Start with just 1 prefix, custom step will scale
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                        bgp_communities=[],
                                    ),
                                    multiplier=1,
                                    network_group_index=0,
                                )
                            ],
                        ),
                    ),
                    DeviceGroupConfig(
                        device_group_name="DEVICE_GROUP_IPV4_EBGP",
                        device_group_index=1,
                        multiplier=initial_ebgp_peer_count,
                        v4_addresses_config=IpAddressesConfig(
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
                            bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                            route_scales=[
                                RouteScaleSpec(
                                    v4_route_scale=RouteScale(
                                        prefix_name="PREFIX_POOL_IPV4_EBGP",
                                        starting_prefixes="10.100.0.0",
                                        prefix_step="0.0.1.0",
                                        prefix_length=24,
                                        multiplier=1,
                                        prefix_count=1,  # Start with just 1 prefix, custom step will scale
                                        ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                        bgp_communities=[],
                                    ),
                                    multiplier=1,
                                    network_group_index=0,
                                )
                            ],
                        ),
                    ),
                ],
            ),
        ],
        playbooks=[
            build_case2_playbook(
                name="bgp_plus_plus_constant_attribute_storage_test",
                description="Test BGP++ constant attribute storage with varying EBGP peers and prefix counts",
                stages=[
                    create_steps_stage(
                        steps=[
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "test_constant_attribute_storage_eos_bgp_plus_plus",
                                    "hostname": device_name,
                                    "ixia_interface_mimic_ebgp": ixia_interface_mimic_ebgp,
                                    "ebgp_peer_counts": ebgp_peer_counts,
                                    "constant_total_paths": constant_total_paths,
                                    "soak_time_minutes": soak_time_minutes,
                                    "attribute_pool_as_paths": as_path_pool,
                                    "attribute_pool_communities": community_pool,
                                    "attribute_pool_extended_communities": extended_community_pool,
                                    # Constant acceptance communities - must be present on ALL routes
                                    # This community is required by device BGP policy to accept routes
                                    "attach_communities_for_ebgp_prefixes": constant_acceptance_communities,
                                    # Optional: limit number of communities from pool per route (default: use all)
                                    "max_communities_per_route_from_pool": max_communities_per_route_from_pool,
                                    # Randomization settings for attribute assignment
                                    "randomize_attributes": randomize_attributes,
                                    "random_seed": random_seed,
                                    # Route withdrawal testing
                                    "test_route_withdrawal": test_route_withdrawal,
                                    "withdrawal_wait_minutes": withdrawal_wait_minutes,
                                    # Attribute assignment verification
                                    "dump_attribute_assignments": dump_attribute_assignments,
                                }
                            ),
                        ],
                    )
                ],
            ),
        ],
    )


def test_config_constant_attribute_storage_varying_combinations_on_eos(
    test_config_name: str,
    device_name: str,
    ixia_interface_mimic_ebgp: str,
    ebgp_remote_as: int,
    ixia_ebgp_ic_parent_network_v6: str,
    ixia_ebgp_ic_parent_network_v4: str,
    unique_combination_counts: List[int],  # e.g., [100_000, 200_000, ..., 800_000]
    # IBGP parameters
    ixia_interface_mimic_ibgp: str | None = None,  # Interface for IBGP peers
    ibgp_local_as: int | None = None,  # IBGP local AS number
    ixia_ibgp_ic_parent_network_v6: str | None = None,  # IPv6 network for IBGP
    ixia_ibgp_ic_parent_network_v4: str | None = None,  # IPv4 network for IBGP
    # Existing parameters
    constant_ebgp_peer_count: int = 8,  # Total EBGP peer count (distribution depends on test_address_families)
    constant_ibgp_peer_count: int = 2,  # Total IBGP peer count (distribution depends on test_address_families)
    constant_total_paths: int = 800_000,  # Fixed at 800K paths total
    # Address family selection
    test_address_families: List[str]
    | None = None,  # ["ipv4"], ["ipv6"], or ["ipv4", "ipv6"]
    # Configurable base attribute pool sizes
    base_as_path_pool_size: int = 100,  # Number of unique AS paths in pool
    base_community_pool_size: int = 100,  # Number of unique communities in pool
    base_extended_community_pool_size: int = 100,  # Number of unique ext-communities in pool
    constant_acceptance_communities: List[str] | None = None,  # e.g., ["65529:39744"]
    max_communities_per_route_from_pool: int
    | None = None,  # Optional limit (default: use all)
    random_seed: int = 42,  # Random seed for reproducibility
    test_route_withdrawal: bool = False,  # Test route withdrawal and memory cleanup
    withdrawal_wait_minutes: int = 3,  # Wait time after withdrawal
    dump_attribute_assignments: bool = False,  # Dump attribute assignments for verification
    soak_time_minutes: int = 10,
    direct_ixia_connections: List | None = None,
    log_collection_timeout: int | None = None,
    # Device-level BGP peer group names
    peergroup_ebgp_v6: str | None = None,
    peergroup_ebgp_v4: str | None = None,
    peergroup_ibgp_v6: str | None = None,
    peergroup_ibgp_v4: str | None = None,
    ssh_password: str = "",
    setup_tasks: List[Task] | None = None,
    oss_mock_device_data=None,
    host_os_type_map=None,
    host_driver_args=None,
):
    """
    Test CONSTANT attribute storage with varying unique attribute-set combination counts.

    This test proves that BGP++ memory remains CONSTANT and depends on base attribute
    pool sizes, NOT on the number of unique combinations created from those pools.

    Test Design - Constant Attribute Storage (Varying Combinations):
        CONSTANT across all iterations:
        - EBGP peers: configurable count (default: 8) sending 800K routes total
          * Peer distribution depends on test_address_families parameter:
            - Both AFs (default): 4 IPv4 + 4 IPv6 peers (100K routes per peer)
            - IPv6 only: 8 IPv6 peers (100K routes per peer)
            - IPv4 only: 8 IPv4 peers (100K routes per peer)
        - IBGP peers: configurable count (default: 2) as listeners-only (no routes sent)
          * Peer distribution follows same pattern as EBGP
        - Base attribute pools (configurable):
          * AS numbers: default 100 (each AS path uses 5 AS numbers)
          * Communities: default 100 (each route uses 5 from pool + constant acceptance communities)
          * Extended communities: default 100 (each route uses 1)

        VARIABLE:
        - Number of unique attribute-set combinations: 100K → 800K

        Example iterations (IPv6 only with 8 peers):
            Iteration 1: 100K unique combinations
                - Generate 100K different combos from base pools
                - 8 IPv6 EBGP peers advertise 100K routes each = 800K total paths
                - Routes reuse combinations (each combo used ~8 times)
                - RIB shows: 100K unique combos across 800K paths

            Iteration 2: 200K unique combinations
                - Generate 200K different combos from base pools
                - Same 800K total paths
                - Each combo used ~4 times
                - RIB shows: 200K unique combos across 800K paths

            ...

            Iteration 8: 800K unique combinations (worst case)
                - Generate 800K different combos from base pools
                - Maximum diversity - nearly unique per route
                - Each combo used ~1 time
                - RIB shows: 800K unique combos across 800K paths

    Expected Result:
        Memory should remain CONSTANT from 100K → 800K unique combinations since:
        - Base pools are constant (configurable, default: 100 AS numbers, 100 comm, 100 ext-comm)
        - Total paths are constant (800K from EBGP)
        - Only the diversity of combinations changes

        This proves BGP++ uses CONSTANT attribute storage based on pool sizes,
        not combination count!

    Address Family Selection:
        The test_address_families parameter controls which address families are tested:
        - ["ipv4", "ipv6"] (default): Tests both address families
          * Device groups: Both IPv4 and IPv6 EBGP/IBGP device groups created
          * Peers split evenly: constant_ebgp_peer_count/2 per AF
        - ["ipv6"]: Tests IPv6 only (recommended for clean results)
          * Device groups: Only IPv6 EBGP/IBGP device groups created
          * All peers are IPv6: constant_ebgp_peer_count IPv6 peers
        - ["ipv4"]: Tests IPv4 only
          * Device groups: Only IPv4 EBGP/IBGP device groups created
          * All peers are IPv4: constant_ebgp_peer_count IPv4 peers

    Args:
        test_config_name: Name of the test configuration
        device_name: Device under test (DUT) hostname
        ixia_interface_mimic_ebgp: Interface for EBGP peers
        ebgp_remote_as: EBGP remote AS number
        ixia_ebgp_ic_parent_network_v6: IPv6 network for EBGP
        ixia_ebgp_ic_parent_network_v4: IPv4 network for EBGP
        unique_combination_counts: List of unique combo counts to test (e.g., [100_000, 200_000, ..., 800_000])
        ixia_interface_mimic_ibgp: Interface for IBGP peers (optional)
        ibgp_local_as: IBGP local AS number (optional)
        ixia_ibgp_ic_parent_network_v6: IPv6 network for IBGP (optional)
        ixia_ibgp_ic_parent_network_v4: IPv4 network for IBGP (optional)
        constant_ebgp_peer_count: Fixed EBGP peer count across iterations (default: 8)
        constant_ibgp_peer_count: Fixed IBGP peer count across iterations (default: 2)
        constant_total_paths: Fixed total paths across iterations (default: 800_000)
        test_address_families: Address families to test (default: ["ipv4", "ipv6"])
            - ["ipv4"]: IPv4 only (all peers are IPv4)
            - ["ipv6"]: IPv6 only (all peers are IPv6) - recommended for clean 1:1 combo mapping
            - ["ipv4", "ipv6"]: Both (peers split evenly between AFs)
        base_as_path_pool_size: Number of unique AS numbers in pool (default: 100)
        base_community_pool_size: Number of unique communities in pool (default: 100)
        base_extended_community_pool_size: Number of unique ext-communities in pool (default: 100)
        constant_acceptance_communities: Communities required by BGP policy (e.g., ["65529:39744"])
        max_communities_per_route_from_pool: Optional limit on communities per route from pool
        random_seed: Random seed for reproducible combination generation (default: 42)
        test_route_withdrawal: Test route withdrawal and memory cleanup (default: False)
        withdrawal_wait_minutes: Wait time after withdrawal (default: 3)
        dump_attribute_assignments: Dump attribute assignments for verification (default: False)
        soak_time_minutes: Soak time in minutes (default: 10)
        direct_ixia_connections: Optional direct IXIA connections
        log_collection_timeout: Optional log collection timeout
        host_os_type_map: Optional host OS type mapping
        host_driver_args: Optional host driver arguments

    Returns:
        TestConfig for constant attribute storage test with varying combination counts
    """
    # Set default address families if not specified
    if test_address_families is None:
        test_address_families = ["ipv4", "ipv6"]  # Default: test both

    # Calculate initial peer counts based on address families
    num_afs = len(test_address_families)
    if num_afs == 2:
        # Testing both AFs: split peers evenly
        initial_ebgp_peer_count = constant_ebgp_peer_count // 2
        initial_ibgp_peer_count = constant_ibgp_peer_count // 2
    elif "ipv4" in test_address_families:
        # IPv4 only: use all peers for IPv4
        initial_ebgp_peer_count = constant_ebgp_peer_count
        initial_ibgp_peer_count = constant_ibgp_peer_count
    else:
        # IPv6 only: use all peers for IPv6
        initial_ebgp_peer_count = constant_ebgp_peer_count
        initial_ibgp_peer_count = constant_ibgp_peer_count

    # Build ixia_ports list dynamically
    ixia_ports = [ixia_interface_mimic_ebgp]
    if ixia_interface_mimic_ibgp:
        ixia_ports.append(ixia_interface_mimic_ibgp)

    # Build EBGP device group configs based on address families
    ebgp_device_groups = []

    # Add IPv6 device group if testing IPv6
    if "ipv6" in test_address_families:
        ebgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV6_EBGP",
                device_group_index=len(ebgp_device_groups),
                multiplier=initial_ebgp_peer_count,
                v6_addresses_config=IpAddressesConfig(
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
                    bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                    route_scales=[
                        RouteScaleSpec(
                            v6_route_scale=RouteScale(
                                prefix_name="PREFIX_POOL_IPV6_EBGP",
                                starting_prefixes="2001:db8:1000::",
                                prefix_step="0:0:1::",
                                prefix_length=64,
                                multiplier=1,
                                prefix_count=constant_total_paths
                                // constant_ebgp_peer_count,  # Will be updated dynamically
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                bgp_communities=[],
                            ),
                            multiplier=1,
                            network_group_index=0,
                        )
                    ],
                ),
            )
        )

    # Add IPv4 device group if testing IPv4
    if "ipv4" in test_address_families:
        ebgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV4_EBGP",
                device_group_index=len(ebgp_device_groups),
                multiplier=initial_ebgp_peer_count,
                v4_addresses_config=IpAddressesConfig(
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
                    bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                    route_scales=[
                        RouteScaleSpec(
                            v4_route_scale=RouteScale(
                                prefix_name="PREFIX_POOL_IPV4_EBGP",
                                starting_prefixes="50.100.0.0",
                                prefix_step="0.0.1.0",
                                prefix_length=24,
                                multiplier=1,
                                prefix_count=constant_total_paths
                                // constant_ebgp_peer_count,  # Will be updated dynamically
                                ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                bgp_communities=[],
                            ),
                            multiplier=1,
                            network_group_index=0,
                        )
                    ],
                ),
            )
        )

    # Build IBGP device group configs based on address families (if IBGP is configured)
    ibgp_device_groups = []
    if (
        ixia_interface_mimic_ibgp
        and ibgp_local_as
        and ixia_ibgp_ic_parent_network_v6
        and ixia_ibgp_ic_parent_network_v4
    ):
        # Add IPv6 IBGP device group if testing IPv6
        if "ipv6" in test_address_families:
            ibgp_device_groups.append(
                DeviceGroupConfig(
                    device_group_name="DEVICE_GROUP_IPV6_IBGP",
                    device_group_index=len(ibgp_device_groups),
                    multiplier=initial_ibgp_peer_count,
                    v6_addresses_config=IpAddressesConfig(
                        starting_ip=f"{ixia_ibgp_ic_parent_network_v6}::11",
                        increment_ip="0:0:0:0::2",
                        gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v6}::10",
                        gateway_increment_ip="0:0:0:0::2",
                        start_index=0,
                    ),
                    v6_bgp_config=BgpConfig(
                        bgp_peer_name="BGP_PEER_IPV6_IBGP",
                        local_as_4_bytes=ibgp_local_as,
                        enable_4_byte_local_as=True,
                        bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                        # IBGP listeners only - no routes advertised
                    ),
                )
            )

        # Add IPv4 IBGP device group if testing IPv4
        if "ipv4" in test_address_families:
            ibgp_device_groups.append(
                DeviceGroupConfig(
                    device_group_name="DEVICE_GROUP_IPV4_IBGP",
                    device_group_index=len(ibgp_device_groups),
                    multiplier=initial_ibgp_peer_count,
                    v4_addresses_config=IpAddressesConfig(
                        starting_ip=f"{ixia_ibgp_ic_parent_network_v4}.11",
                        increment_ip="0.0.0.2",
                        gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v4}.10",
                        gateway_increment_ip="0.0.0.2",
                        mask=31,
                        start_index=0,
                    ),
                    v4_bgp_config=BgpConfig(
                        bgp_peer_name="BGP_PEER_IPV4_IBGP",
                        local_as_4_bytes=ibgp_local_as,
                        enable_4_byte_local_as=True,
                        bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                        # IBGP listeners only - no routes advertised
                    ),
                )
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
                ixia_ports=ixia_ports,  # Dynamic: EBGP + optional IBGP
                direct_ixia_connections=direct_ixia_connections
                if direct_ixia_connections
                else [],
            ),
        ],
        host_driver_args=host_driver_args,
        oss_mock_device_data=oss_mock_device_data,
        host_os_type_map=host_os_type_map,
        startup_checks=[],
        setup_tasks=setup_tasks if setup_tasks else [],
        teardown_tasks=[],
        # Deprecated - define at playbook level
        # prechecks=[],
        # postchecks=[],
        # snapshot_checks=[],
        basic_port_configs=[
            BasicPortConfig(
                endpoint=f"{device_name}:{ixia_interface_mimic_ebgp}",
                device_group_configs=ebgp_device_groups,  # Use dynamically built device groups
            ),
            *(
                [
                    BasicPortConfig(
                        endpoint=f"{device_name}:{ixia_interface_mimic_ibgp}",
                        device_group_configs=ibgp_device_groups,  # Use dynamically built device groups
                    ),
                ]
                if ibgp_device_groups  # Only add IBGP config if device groups were created
                else []
            ),
        ],
        playbooks=[
            build_case2_playbook(
                name="bgp_plus_plus_constant_attribute_storage_varying_combinations_test",
                description="Test BGP++ constant attribute storage with varying unique combination counts",
                stages=[
                    create_steps_stage(
                        steps=[
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "test_constant_attribute_storage_varying_combinations_eos_bgp_plus_plus",
                                    "hostname": device_name,
                                    "ixia_interface_mimic_ebgp": ixia_interface_mimic_ebgp,
                                    "constant_ebgp_peer_count": constant_ebgp_peer_count,
                                    "constant_ibgp_peer_count": constant_ibgp_peer_count,
                                    "ixia_interface_mimic_ibgp": ixia_interface_mimic_ibgp,
                                    "constant_total_paths": constant_total_paths,
                                    "unique_combination_counts": unique_combination_counts,
                                    "test_address_families": test_address_families,
                                    "soak_time_minutes": soak_time_minutes,
                                    # Base attribute pool sizes (custom step will generate pools)
                                    "base_as_path_pool_size": base_as_path_pool_size,
                                    "base_community_pool_size": base_community_pool_size,
                                    "base_extended_community_pool_size": base_extended_community_pool_size,
                                    # Per-route attribute constraints
                                    "as_path_length": 5,  # 5 AS numbers per path
                                    "communities_per_route": 5,  # 5 communities per route
                                    "extended_communities_per_route": 1,  # 1 extended community per route
                                    "attach_communities_for_ebgp_prefixes": constant_acceptance_communities,
                                    "max_communities_per_route_from_pool": max_communities_per_route_from_pool,
                                    "random_seed": random_seed,
                                    "test_route_withdrawal": test_route_withdrawal,
                                    "withdrawal_wait_minutes": withdrawal_wait_minutes,
                                    "dump_attribute_assignments": dump_attribute_assignments,
                                    # Device-level BGP peer config (only when no setup_tasks;
                                    # when setup_tasks are provided, peers are configured
                                    # declaratively via setup tasks)
                                    **(
                                        {
                                            "ebgp_remote_as": ebgp_remote_as,
                                            "ibgp_remote_as": ibgp_local_as,
                                            "ixia_ebgp_ic_parent_network_v6": ixia_ebgp_ic_parent_network_v6,
                                            "ixia_ebgp_ic_parent_network_v4": ixia_ebgp_ic_parent_network_v4,
                                            "ixia_ibgp_ic_parent_network_v6": ixia_ibgp_ic_parent_network_v6,
                                            "ixia_ibgp_ic_parent_network_v4": ixia_ibgp_ic_parent_network_v4,
                                            "peergroup_ebgp_v6": peergroup_ebgp_v6,
                                            "peergroup_ebgp_v4": peergroup_ebgp_v4,
                                            "peergroup_ibgp_v6": peergroup_ibgp_v6,
                                            "peergroup_ibgp_v4": peergroup_ibgp_v4,
                                            "ssh_password": ssh_password,
                                        }
                                        if setup_tasks is None
                                        else {}
                                    ),
                                }
                            ),
                        ],
                    )
                ],
            ),
        ],
    )
