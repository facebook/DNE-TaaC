# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""
IXIA port configurations for BGP enforce_first_as feature testing.

This module provides IXIA device group configurations for testing the BGP
enforce_first_as security feature in EOS BGP++.

Test Design:
    - enforce_first_as validates that the first AS in AS_PATH matches the peer's remote AS
    - When enabled, routes with mismatched first AS are rejected
    - Routes from eBGP peers should have AS_PATH starting with the peer's AS

Test Scenario:
    1. Create eBGP device groups (all with same local_as to establish sessions):
       - Group 1 (VALID): No AS prepend → AS_PATH = "65334" (just local AS)
       - Group 2 (INVALID): AS prepend with different AS → AS_PATH = "65000 65334"
         (first AS is 65000, which doesn't match peer's remote AS)
    2. Create iBGP listener peers on egress interface
    3. With enforce_first_as=false: Both groups' routes accepted
    4. With enforce_first_as=true: Only valid group's routes accepted
"""

from ixia.ixia import types as ixia_types
from taac.test_as_a_config.types import (
    BasicPortConfig,
    BgpConfig,
    DeviceGroupConfig,
    IpAddressesConfig,
    RouteScale,
    RouteScaleSpec,
)


def create_enforce_first_as_test_basic_port_configs(
    device_name: str,
    # eBGP interface (ingress - routes come in here)
    ixia_interface_ebgp: str,
    ebgp_peer_count_valid: int,
    ebgp_peer_count_invalid: int,
    ebgp_remote_as: int,  # The AS that DUT expects and IXIA uses for session (e.g., 65334)
    wrong_first_as: int,  # The wrong AS to prepend for invalid routes (e.g., 65000)
    ixia_ebgp_ic_parent_network_v6: str,
    ixia_ebgp_ic_parent_network_v4: str,
    # iBGP interface (egress - listeners)
    ixia_interface_ibgp: str,
    ibgp_peer_count: int,
    ibgp_local_as: int,
    ixia_ibgp_ic_parent_network_v6: str,
    ixia_ibgp_ic_parent_network_v4: str,
    # Route configuration
    prefix_count: int,
    ebgp_route_acceptance_communities: list[str] | None = None,
    # Address family selection
    test_address_families: list[str] | None = None,
) -> list[BasicPortConfig]:
    """
    Create basic port configurations for BGP enforce_first_as feature testing.

    This function generates IXIA port configurations with:
    - eBGP interface: Two device groups both using the same local_as (for session establishment)
      * Valid Group: No AS prepending → AS_PATH = local_as only (e.g., "65334")
      * Invalid Group: AS prepending with wrong_first_as → AS_PATH = "65000 65334"
        When enforce_first_as is enabled, routes with first AS != remote_as are rejected
    - iBGP interface: Listener peers to verify route propagation

    Args:
        device_name: Name of the device under test
        ixia_interface_ebgp: IXIA interface for eBGP peers (ingress)
        ebgp_peer_count_valid: Number of eBGP peers with valid AS_PATH
        ebgp_peer_count_invalid: Number of eBGP peers with invalid AS_PATH
        ebgp_remote_as: eBGP remote AS number (used for session and valid routes)
        wrong_first_as: AS number to prepend for invalid routes (different from remote_as)
        ixia_ebgp_ic_parent_network_v6: IPv6 network for eBGP peers
        ixia_ebgp_ic_parent_network_v4: IPv4 network for eBGP peers
        ixia_interface_ibgp: IXIA interface for iBGP peers (egress/listeners)
        ibgp_peer_count: Number of iBGP listener peers
        ibgp_local_as: iBGP local AS number (same as DUT)
        ixia_ibgp_ic_parent_network_v6: IPv6 network for iBGP peers
        ixia_ibgp_ic_parent_network_v4: IPv4 network for iBGP peers
        prefix_count: Number of prefixes to advertise per peer
        ebgp_route_acceptance_communities: Acceptance communities for eBGP routes
        test_address_families: Address families to test (default: ["ipv6"])

    Returns:
        List of BasicPortConfig objects for IXIA configuration
    """
    if test_address_families is None:
        test_address_families = ["ipv6"]

    if ebgp_route_acceptance_communities is None:
        ebgp_route_acceptance_communities = []

    # Build eBGP device groups (ingress - advertise routes)
    ebgp_device_groups: list[DeviceGroupConfig] = []
    device_group_index = 0

    # eBGP Group 1 - VALID AS (routes accepted with or without enforce_first_as)
    # These peers use the correct AS that matches DUT's expected remote AS
    if "ipv6" in test_address_families:
        ebgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV6_EBGP_VALID_AS",
                device_group_index=device_group_index,
                multiplier=ebgp_peer_count_valid,
                v6_addresses_config=IpAddressesConfig(
                    starting_ip=f"{ixia_ebgp_ic_parent_network_v6}::11",
                    increment_ip="0:0:0:0::2",
                    gateway_starting_ip=f"{ixia_ebgp_ic_parent_network_v6}::10",
                    gateway_increment_ip="0:0:0:0::2",
                    start_index=0,
                ),
                v6_bgp_config=BgpConfig(
                    bgp_peer_name="BGP_PEER_IPV6_EBGP_VALID_AS",
                    local_as_4_bytes=ebgp_remote_as,
                    enable_4_byte_local_as=True,
                    enable_graceful_restart=False,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                    bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                    route_scales=[
                        RouteScaleSpec(
                            v6_route_scale=RouteScale(
                                prefix_name="PREFIX_POOL_IPV6_EBGP_VALID_AS",
                                starting_prefixes="2001:db8:1000::",
                                prefix_step="0:0:1::",
                                prefix_length=64,
                                multiplier=1,
                                prefix_count=prefix_count,
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                bgp_communities=ebgp_route_acceptance_communities,
                                # No AS path prepend - AS_PATH will be just [ebgp_remote_as]
                            ),
                            multiplier=1,
                            network_group_index=0,
                        ),
                    ],
                ),
            )
        )
        device_group_index += 1

    # eBGP Group 2 - INVALID AS (routes rejected when enforce_first_as=true)
    # These peers use a different AS - the AS_PATH will start with this AS
    # When enforce_first_as is enabled, DUT will reject because first AS doesn't match
    if "ipv6" in test_address_families:
        # Calculate starting IP for group 2 based on group 1 count
        group2_start_offset = 0x10 + (ebgp_peer_count_valid * 2)
        group2_peer_start = (
            f"{ixia_ebgp_ic_parent_network_v6}::{group2_start_offset + 1:x}"
        )
        group2_gw_start = f"{ixia_ebgp_ic_parent_network_v6}::{group2_start_offset:x}"

        ebgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV6_EBGP_INVALID_AS",
                device_group_index=device_group_index,
                multiplier=ebgp_peer_count_invalid,
                v6_addresses_config=IpAddressesConfig(
                    starting_ip=group2_peer_start,
                    increment_ip="0:0:0:0::2",
                    gateway_starting_ip=group2_gw_start,
                    gateway_increment_ip="0:0:0:0::2",
                    start_index=0,
                ),
                v6_bgp_config=BgpConfig(
                    bgp_peer_name="BGP_PEER_IPV6_EBGP_INVALID_AS",
                    # Use the same remote AS for session establishment
                    local_as_4_bytes=ebgp_remote_as,
                    enable_4_byte_local_as=True,
                    enable_graceful_restart=False,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                    bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                    # DO_NOT_INCLUDE_LOCAL_AS prevents IXIA from prepending its local AS
                    # This allows the as_path_prepend_numbers to be the first AS in path
                    as_set_mode=ixia_types.BgpAsSetMode.DO_NOT_INCLUDE_LOCAL_AS,
                    route_scales=[
                        RouteScaleSpec(
                            v6_route_scale=RouteScale(
                                prefix_name="PREFIX_POOL_IPV6_EBGP_INVALID_AS",
                                # Different prefix range to easily identify
                                starting_prefixes="2001:db8:2000::",
                                prefix_step="0:0:1::",
                                prefix_length=64,
                                multiplier=1,
                                prefix_count=prefix_count,
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                bgp_communities=ebgp_route_acceptance_communities,
                                # Prepend wrong_first_as to AS_PATH
                                # AS_PATH will be [wrong_first_as, ebgp_remote_as]
                                # First AS won't match peer's remote AS, so rejected
                                as_path_prepend_numbers=[[wrong_first_as]],
                            ),
                            multiplier=1,
                            network_group_index=0,
                        ),
                    ],
                ),
            )
        )
        device_group_index += 1

    # IPv4 eBGP groups
    if "ipv4" in test_address_families:
        # eBGP Group 1 - IPv4 - Valid AS
        ebgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV4_EBGP_VALID_AS",
                device_group_index=device_group_index,
                multiplier=ebgp_peer_count_valid,
                v4_addresses_config=IpAddressesConfig(
                    starting_ip=f"{ixia_ebgp_ic_parent_network_v4}.17",
                    increment_ip="0.0.0.2",
                    gateway_starting_ip=f"{ixia_ebgp_ic_parent_network_v4}.16",
                    gateway_increment_ip="0.0.0.2",
                    mask=31,
                    start_index=0,
                ),
                v4_bgp_config=BgpConfig(
                    bgp_peer_name="BGP_PEER_IPV4_EBGP_VALID_AS",
                    local_as_4_bytes=ebgp_remote_as,
                    enable_4_byte_local_as=True,
                    enable_graceful_restart=False,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                    bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                    route_scales=[
                        RouteScaleSpec(
                            v4_route_scale=RouteScale(
                                prefix_name="PREFIX_POOL_IPV4_EBGP_VALID_AS",
                                starting_prefixes="10.100.0.0",
                                prefix_step="0.0.1.0",
                                prefix_length=24,
                                multiplier=1,
                                prefix_count=prefix_count,
                                ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                bgp_communities=ebgp_route_acceptance_communities,
                                # No AS path prepend - AS_PATH will be just [ebgp_remote_as]
                            ),
                            multiplier=1,
                            network_group_index=0,
                        ),
                    ],
                ),
            )
        )
        device_group_index += 1

        # eBGP Group 2 - IPv4 - Invalid AS
        group2_v4_start_offset = 16 + (ebgp_peer_count_valid * 2)
        group2_v4_peer_start = (
            f"{ixia_ebgp_ic_parent_network_v4}.{group2_v4_start_offset + 1}"
        )
        group2_v4_gw_start = (
            f"{ixia_ebgp_ic_parent_network_v4}.{group2_v4_start_offset}"
        )

        ebgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV4_EBGP_INVALID_AS",
                device_group_index=device_group_index,
                multiplier=ebgp_peer_count_invalid,
                v4_addresses_config=IpAddressesConfig(
                    starting_ip=group2_v4_peer_start,
                    increment_ip="0.0.0.2",
                    gateway_starting_ip=group2_v4_gw_start,
                    gateway_increment_ip="0.0.0.2",
                    mask=31,
                    start_index=0,
                ),
                v4_bgp_config=BgpConfig(
                    bgp_peer_name="BGP_PEER_IPV4_EBGP_INVALID_AS",
                    # Use the same remote AS for session establishment
                    local_as_4_bytes=ebgp_remote_as,
                    enable_4_byte_local_as=True,
                    enable_graceful_restart=False,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                    bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                    # DO_NOT_INCLUDE_LOCAL_AS prevents IXIA from prepending its local AS
                    # This allows the as_path_prepend_numbers to be the first AS in path
                    as_set_mode=ixia_types.BgpAsSetMode.DO_NOT_INCLUDE_LOCAL_AS,
                    route_scales=[
                        RouteScaleSpec(
                            v4_route_scale=RouteScale(
                                prefix_name="PREFIX_POOL_IPV4_EBGP_INVALID_AS",
                                starting_prefixes="10.200.0.0",
                                prefix_step="0.0.1.0",
                                prefix_length=24,
                                multiplier=1,
                                prefix_count=prefix_count,
                                ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                bgp_communities=ebgp_route_acceptance_communities,
                                # Prepend wrong_first_as to AS_PATH
                                # AS_PATH will be [wrong_first_as, ebgp_remote_as]
                                # First AS won't match peer's remote AS, so rejected
                                as_path_prepend_numbers=[[wrong_first_as]],
                            ),
                            multiplier=1,
                            network_group_index=0,
                        ),
                    ],
                ),
            )
        )
        device_group_index += 1

    # Build iBGP device groups (egress - listeners only, no routes)
    ibgp_device_groups: list[DeviceGroupConfig] = []
    ibgp_device_group_index = 0

    if "ipv6" in test_address_families:
        ibgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV6_IBGP_LISTENER",
                device_group_index=ibgp_device_group_index,
                multiplier=ibgp_peer_count,
                v6_addresses_config=IpAddressesConfig(
                    starting_ip=f"{ixia_ibgp_ic_parent_network_v6}::11",
                    increment_ip="0:0:0:0::2",
                    gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v6}::10",
                    gateway_increment_ip="0:0:0:0::2",
                    start_index=0,
                ),
                v6_bgp_config=BgpConfig(
                    bgp_peer_name="BGP_PEER_IPV6_IBGP_LISTENER",
                    local_as_4_bytes=ibgp_local_as,
                    enable_4_byte_local_as=True,
                    enable_graceful_restart=False,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                    bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                    # No route_scales - listeners only
                ),
            )
        )
        ibgp_device_group_index += 1

    if "ipv4" in test_address_families:
        ibgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV4_IBGP_LISTENER",
                device_group_index=ibgp_device_group_index,
                multiplier=ibgp_peer_count,
                v4_addresses_config=IpAddressesConfig(
                    starting_ip=f"{ixia_ibgp_ic_parent_network_v4}.17",
                    increment_ip="0.0.0.2",
                    gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v4}.16",
                    gateway_increment_ip="0.0.0.2",
                    mask=31,
                    start_index=0,
                ),
                v4_bgp_config=BgpConfig(
                    bgp_peer_name="BGP_PEER_IPV4_IBGP_LISTENER",
                    local_as_4_bytes=ibgp_local_as,
                    enable_4_byte_local_as=True,
                    enable_graceful_restart=False,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                    bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                    # No route_scales - listeners only
                ),
            )
        )
        ibgp_device_group_index += 1

    basic_configs: list[BasicPortConfig] = [
        # eBGP configuration (ingress - routes sent here)
        BasicPortConfig(
            endpoint=f"{device_name}:{ixia_interface_ebgp}",
            device_group_configs=ebgp_device_groups,
        ),
        # iBGP configuration (egress - listeners only)
        BasicPortConfig(
            endpoint=f"{device_name}:{ixia_interface_ibgp}",
            device_group_configs=ibgp_device_groups,
        ),
    ]
    return basic_configs
