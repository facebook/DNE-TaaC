# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
Test Config for BGP++ UPDATE Message Packing Validation

This test validates that BGP++ sends maximally packed UPDATE messages,
where all UPDATE messages except the last in each attribute group are
filled to near the 4096-byte limit.

Test Design - IBGP to EBGP Scenario:
    - IXIA mimics IBGP peers sending routes to the device (Edge Border router)
    - Device advertises these routes to EBGP peers (Fabric Aggregators)
    - Capture UPDATE messages on the EBGP-facing interface
    - Parse tcpdump -v output to extract UPDATE message sizes and NLRI counts
    - Group UPDATEs by normalized attributes (AS_PATH + communities)
    - Validate: all but last UPDATE per group >= 4000 bytes

Test Scenario:
    - Device: eb04.lab.ash6 (Arista 7516, Edge Border)
    - Ingress: Ethernet3/1/3 (IXIA as IBGP peers, sends routes with varied attributes)
    - Egress: Ethernet3/1/1 (Device advertises to EBGP/FA peers, capture here)
    - Routes: 100 IBGP peers × 500 prefixes = 50K total routes
    - Attributes: Varied AS_PATH and communities to create multiple attribute groups
    - Next-hop: Automatically changed to self when advertising IBGP → EBGP

Expected Result:
    All UPDATE messages except the last in each attribute group should be
    >= 4000 bytes (maximal packing). The last UPDATE in each group may be
    smaller as it contains the remaining prefixes.
"""

from typing import List

from ixia.ixia import types as ixia_types
from taac.playbooks.playbook_definitions import (
    create_bgp_update_packing_validation_playbook,
)
from taac.routing.ebb.arista_bgp_plus_plus_performance_scaling_tests.attribute_pool_generator import (
    generate_as_path_pool,
    generate_community_pool,
)
from taac.test_as_a_config.types import (
    BasicPortConfig,
    BgpConfig,
    DeviceGroupConfig,
    Endpoint,
    IpAddressesConfig,
    IxiaConfigCache,
    RouteScale,
    RouteScaleSpec,
    TestConfig,
)


def test_config_bgp_update_packing_validation(
    test_config_name: str,
    device_name: str,
    # IBGP configuration (ingress)
    ixia_interface_mimic_ibgp: str,
    ibgp_local_as: int,
    ixia_ibgp_ic_parent_network_v6: str,
    ixia_ibgp_ic_parent_network_v4: str,
    # EBGP configuration (egress - for capture)
    ixia_interface_mimic_ebgp: str,
    ebgp_remote_as: int,
    ixia_ebgp_ic_parent_network_v6: str,
    ixia_ebgp_ic_parent_network_v4: str,
    # Test parameters
    ibgp_peer_count: int = 10,  # Total IBGP peer count (distribution depends on test_address_families)
    prefixes_per_peer: int = 10000,  # Prefixes per IBGP peer (creates ~25-33 UPDATEs per peer)
    ebgp_peer_count: int = 1,  # Total EBGP peer count (use 1 to avoid duplicate captures)
    # Address family selection
    test_address_families: List[str]
    | None = None,  # [\"ipv4\"], [\"ipv6\"], or [\"ipv4\", \"ipv6\"]
    # Attribute pool configuration
    as_path_pool_size: int = 10,  # Number of unique AS paths
    community_pool_size: int = 20,  # Number of unique communities
    as_path_length: int = 3,  # AS numbers per AS path
    communities_per_route: int = 2,  # Communities per route
    # Route acceptance communities (required for Edge Border acceptance policy)
    ibgp_route_acceptance_communities: List[str]
    | None = None,  # e.g., ["65441:133"] - IBGP acceptance community for Edge Border
    ebgp_route_acceptance_communities: List[str]
    | None = None,  # e.g., ["65526:35724"] - EBGP acceptance community for Edge Border
    # Test control
    capture_duration_seconds: int = 600,  # Capture duration (10 minutes for 100K routes)
    min_packed_size: int = 4000,  # Minimum size for "full" UPDATE messages
    restart_bgp_for_complete_view: bool = True,  # True: Best-case (restart BGP++), False: Real-world (incremental)
    direct_ixia_connections: List | None = None,
    log_collection_timeout: int | None = None,
    oss_mock_device_data=None,
    host_os_type_map=None,
    host_driver_args=None,
    setup_tasks: List | None = None,
    teardown_tasks: List | None = None,
    ixia_config_cache: IxiaConfigCache | None = None,
):
    """
    Create test config for BGP UPDATE message packing validation.

    This test uses IBGP → EBGP scenario where:
    - IXIA mimics IBGP peers sending routes with varied AS_PATH/communities
    - Device (Edge Border) advertises to EBGP peers (Fabric Aggregators)
    - UPDATE messages are captured on EBGP-facing interface (Ethernet3/1/1)
    - Next-hop is automatically changed to self when advertising IBGP → EBGP

    Address Family Selection:
        The test_address_families parameter controls which address families are tested:
        - [\"ipv4\", \"ipv6\"] (default): Tests both address families
          * Device groups: Both IPv4 and IPv6 IBGP/EBGP device groups created
          * Peers split evenly: ibgp_peer_count/2 per AF, ebgp_peer_count/2 per AF
        - [\"ipv6\"]: Tests IPv6 only (recommended for clean results)
          * Device groups: Only IPv6 IBGP/EBGP device groups created
          * All peers are IPv6: ibgp_peer_count IPv6 peers
        - [\"ipv4\"]: Tests IPv4 only
          * Device groups: Only IPv4 IBGP/EBGP device groups created
          * All peers are IPv4: ibgp_peer_count IPv4 peers

    Args:
        test_config_name: Name of the test configuration
        device_name: Device under test (DUT) hostname (e.g., "eb04.lab.ash6")
        ixia_interface_mimic_ibgp: IBGP interface (ingress, e.g., "Ethernet3/1/3")
        ibgp_local_as: IBGP local AS number
        ixia_ibgp_ic_parent_network_v6: IPv6 network for IBGP
        ixia_ibgp_ic_parent_network_v4: IPv4 network for IBGP
        ixia_interface_mimic_ebgp: EBGP interface (egress/capture, e.g., "Ethernet3/1/1")
        ebgp_remote_as: EBGP remote AS number
        ixia_ebgp_ic_parent_network_v6: IPv6 network for EBGP
        ixia_ebgp_ic_parent_network_v4: IPv4 network for EBGP
        ibgp_peer_count: Total IBGP peer count (default: 10)
        prefixes_per_peer: Prefixes per IBGP peer (default: 10000)
            → 10 peers × 10,000 prefixes = 100,000 total routes
            → Each peer generates ~25-33 UPDATEs (at ~300-400 prefixes per 4KB UPDATE)
            → Strong validation: 24-32 non-last UPDATEs per attribute group!
        ebgp_peer_count: Total EBGP peer count (default: 1)
            → Use 1 peer to avoid duplicate UPDATE captures
            → Multiple EBGP peers would result in same UPDATEs captured N times
            → BGP++ packing behavior is independent of number of receiving peers
        test_address_families: Address families to test (default: [\"ipv4\", \"ipv6\"])
            - [\"ipv4\"]: IPv4 only (all peers are IPv4)
            - [\"ipv6\"]: IPv6 only (all peers are IPv6) - recommended
            - [\"ipv4\", \"ipv6\"]: Both (peers split evenly between AFs)
        as_path_pool_size: Number of unique AS paths (default: 10)
        community_pool_size: Number of unique communities (default: 20)
        as_path_length: AS numbers per AS path (default: 3)
        communities_per_route: Communities per route (default: 2)
        ibgp_route_acceptance_communities: Acceptance communities for IBGP routes (default: None)
            → Use when testing IBGP → EBGP (IBGP routes ingress, capture on EBGP)
            → Correct value: ["65441:133"] (IBGP acceptance community)
            → These are added to IBGP routes so device accepts them
        ebgp_route_acceptance_communities: Acceptance communities for EBGP routes (default: None)
            → Use when testing EBGP → IBGP (EBGP routes ingress, capture on IBGP)
            → Correct value: ["65526:35724"] (EBGP acceptance community)
            → These are added to EBGP routes so device accepts them
            → NOTE: For reusability - same function handles both test directions!
            → Acceptance communities are CONSTANT (don't affect attribute grouping)
            → Varying communities from community_pool are ADDED for grouping
        capture_duration_seconds: Capture duration in seconds (default: 600 = 10 minutes)
            → Increased for 100K routes to ensure all UPDATEs are captured
        min_packed_size: Minimum size for "full" UPDATE messages (default: 4000 bytes)
        restart_bgp_for_complete_view: Test mode selection (default: True)
            → True: Best-case mode - Restart BGP++ to ensure complete view
              BGP++ waits for EOR from all peers before best-path computation
              Validates OPTIMAL packing capability
            → False: Real-world mode - No restart, incremental updates
              Routes arrive over time, best-path transitions may occur
              Validates real-world packing behavior
        direct_ixia_connections: Optional direct IXIA connections
        log_collection_timeout: Optional log collection timeout
        host_os_type_map: Optional host OS type mapping
        host_driver_args: Optional host driver arguments

    Returns:
        TestConfig for BGP UPDATE message packing validation
    """
    # Set default address families if not specified
    if test_address_families is None:
        test_address_families = ["ipv4", "ipv6"]  # Default: test both

    # Calculate initial peer counts based on address families
    num_afs = len(test_address_families)
    if num_afs == 2:
        # Testing both AFs: split peers evenly
        initial_ibgp_peer_count = ibgp_peer_count // 2
        initial_ebgp_peer_count = ebgp_peer_count // 2
    elif "ipv4" in test_address_families:
        # IPv4 only: use all peers for IPv4
        initial_ibgp_peer_count = ibgp_peer_count
        initial_ebgp_peer_count = ebgp_peer_count
    else:
        # IPv6 only: use all peers for IPv6
        initial_ibgp_peer_count = ibgp_peer_count
        initial_ebgp_peer_count = ebgp_peer_count

    # Generate attribute pools for varied AS_PATH and communities
    as_path_pool = generate_as_path_pool(
        count=as_path_pool_size,
        base_as=45000,
        as_path_length=as_path_length,
    )

    community_pool = generate_community_pool(
        count=community_pool_size,
        base_community=45100,
    )

    # Determine test direction based on which acceptance communities are provided
    # This allows the function to support both EBGP → IBGP and IBGP → EBGP
    if ebgp_route_acceptance_communities:
        # EBGP → IBGP: Routes from EBGP peers, capture on IBGP peers
        test_direction = "EBGP → IBGP"
    elif ibgp_route_acceptance_communities:
        # IBGP → EBGP: Routes from IBGP peers, capture on EBGP peers
        test_direction = "IBGP → EBGP"
    else:
        raise ValueError(
            "Must specify either ibgp_route_acceptance_communities or "
            "ebgp_route_acceptance_communities to determine test direction"
        )

    # Build IBGP device group configs based on address families
    ibgp_device_groups = []

    # Determine if IBGP peers should advertise routes based on direction
    ibgp_advertises_routes = test_direction == "IBGP → EBGP"

    # Add IPv6 IBGP device group if testing IPv6
    if "ipv6" in test_address_families:
        # Build route scales only if IBGP is the ingress (advertiser)
        ibgp_v6_route_scales = None
        if ibgp_advertises_routes:
            ibgp_v6_route_scales = [
                RouteScaleSpec(
                    v6_route_scale=RouteScale(
                        prefix_name="PREFIX_POOL_IPV6_IBGP",
                        starting_prefixes="5001:db8:1000::",
                        prefix_step="0:0:1::",
                        prefix_length=64,
                        multiplier=1,
                        prefix_count=prefixes_per_peer,
                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                        bgp_communities=[],
                    ),
                    multiplier=1,
                    network_group_index=0,
                )
            ]

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
                    route_scales=ibgp_v6_route_scales,
                ),
            )
        )

    # Add IPv4 IBGP device group if testing IPv4
    if "ipv4" in test_address_families:
        # Build route scales only if IBGP is the ingress (advertiser)
        ibgp_v4_route_scales = None
        if ibgp_advertises_routes:
            ibgp_v4_route_scales = [
                RouteScaleSpec(
                    v4_route_scale=RouteScale(
                        prefix_name="PREFIX_POOL_IPV4_IBGP",
                        starting_prefixes="50.100.0.0",
                        prefix_step="0.0.1.0",
                        prefix_length=24,
                        multiplier=1,
                        prefix_count=prefixes_per_peer,
                        ip_address_family=ixia_types.IpAddressFamily.IPV4,
                        bgp_communities=[],
                    ),
                    multiplier=1,
                    network_group_index=0,
                )
            ]

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
                    route_scales=ibgp_v4_route_scales,
                ),
            )
        )

    # Build EBGP device group configs based on address families
    ebgp_device_groups = []

    # Determine if EBGP peers should advertise routes based on direction
    ebgp_advertises_routes = test_direction == "EBGP → IBGP"

    # Add IPv6 EBGP device group if testing IPv6
    if "ipv6" in test_address_families:
        # Build route scales only if EBGP is the ingress (advertiser)
        ebgp_v6_route_scales = None
        if ebgp_advertises_routes:
            ebgp_v6_route_scales = [
                RouteScaleSpec(
                    v6_route_scale=RouteScale(
                        prefix_name="PREFIX_POOL_IPV6_EBGP",
                        starting_prefixes="5001:db8:1000::",
                        prefix_step="0:0:1::",
                        prefix_length=64,
                        multiplier=1,
                        prefix_count=prefixes_per_peer,
                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                        bgp_communities=[],
                    ),
                    multiplier=1,
                    network_group_index=0,
                )
            ]

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
                    route_scales=ebgp_v6_route_scales,
                ),
            )
        )

    # Add IPv4 EBGP device group if testing IPv4
    if "ipv4" in test_address_families:
        # Build route scales only if EBGP is the ingress (advertiser)
        ebgp_v4_route_scales = None
        if ebgp_advertises_routes:
            ebgp_v4_route_scales = [
                RouteScaleSpec(
                    v4_route_scale=RouteScale(
                        prefix_name="PREFIX_POOL_IPV4_EBGP",
                        starting_prefixes="50.100.0.0",
                        prefix_step="0.0.1.0",
                        prefix_length=24,
                        multiplier=1,
                        prefix_count=prefixes_per_peer,
                        ip_address_family=ixia_types.IpAddressFamily.IPV4,
                        bgp_communities=[],
                    ),
                    multiplier=1,
                    network_group_index=0,
                )
            ]

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
                    route_scales=ebgp_v4_route_scales,
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
                ixia_ports=[
                    ixia_interface_mimic_ibgp,  # IBGP ingress
                    ixia_interface_mimic_ebgp,  # EBGP egress (capture)
                ],
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
        teardown_tasks=teardown_tasks if teardown_tasks else [],
        # Deprecated - define at playbook level
        # prechecks=[],
        # postchecks=[],
        # snapshot_checks=[],
        basic_port_configs=[
            # IBGP configuration (ingress - routes sent here)
            BasicPortConfig(
                endpoint=f"{device_name}:{ixia_interface_mimic_ibgp}",
                device_group_configs=ibgp_device_groups,
            ),
            # EBGP configuration (egress - listeners only, capture here)
            BasicPortConfig(
                endpoint=f"{device_name}:{ixia_interface_mimic_ebgp}",
                device_group_configs=ebgp_device_groups,
            ),
        ],
        playbooks=[
            create_bgp_update_packing_validation_playbook(
                device_name=device_name,
                ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
                ibgp_peer_count=ibgp_peer_count,
                prefixes_per_peer=prefixes_per_peer,
                ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
                ebgp_peer_count=ebgp_peer_count,
                test_address_families=test_address_families,
                as_path_pool=as_path_pool,
                community_pool=community_pool,
                communities_per_route=communities_per_route,
                ibgp_route_acceptance_communities=ibgp_route_acceptance_communities,
                ebgp_route_acceptance_communities=ebgp_route_acceptance_communities,
                capture_duration_seconds=capture_duration_seconds,
                min_packed_size=min_packed_size,
                restart_bgp_for_complete_view=restart_bgp_for_complete_view,
            ),
        ],
        ixia_config_cache=ixia_config_cache,
    )
