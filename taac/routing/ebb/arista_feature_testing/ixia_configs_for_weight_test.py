# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""
IXIA port configurations for BGP weight feature testing.

This module provides IXIA device group configurations for testing the BGP weight
attribute in EOS BGP++.

Test Design - EBGP to IBGP Scenario:
    - IXIA mimics EBGP peers sending routes to the device with different communities
    - Device applies weight based on community matching in ingress policy (EB-FA-IN)
    - IXIA mimics IBGP peers as listeners to verify best path selection
    - Routes with higher weight should be selected as best

The DUT must have policies configured that:
- Match community 65001:10 -> set weight 10
- Match community 65001:20 -> set weight 20
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


def create_weight_test_basic_port_configs(
    device_name: str,
    # eBGP interface (ingress - routes come in here)
    ixia_interface_ebgp: str,
    ebgp_peer_count_group1: int,
    ebgp_peer_count_group2: int,
    ebgp_remote_as: int,
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
    weight_10_community: str = "65001:10",
    weight_20_community: str = "65001:20",
    ebgp_route_acceptance_communities: list[str] | None = None,
    # Address family selection
    test_address_families: list[str] | None = None,
) -> list[BasicPortConfig]:
    """
    Create basic port configurations for BGP weight feature testing.

    This function generates IXIA port configurations with:
    - eBGP interface: Two device groups advertising routes with different communities
      * Group 1: Routes with community for weight 10
      * Group 2: Routes with community for weight 20 (same prefixes as group 1)
    - iBGP interface: Listener peers to verify best path selection

    Args:
        device_name: Name of the device under test
        ixia_interface_ebgp: IXIA interface for eBGP peers (ingress)
        ebgp_peer_count_group1: Number of eBGP peers in group 1 (weight 10)
        ebgp_peer_count_group2: Number of eBGP peers in group 2 (weight 20)
        ebgp_remote_as: eBGP remote AS number
        ixia_ebgp_ic_parent_network_v6: IPv6 network for eBGP peers
        ixia_ebgp_ic_parent_network_v4: IPv4 network for eBGP peers
        ixia_interface_ibgp: IXIA interface for iBGP peers (egress/listeners)
        ibgp_peer_count: Number of iBGP listener peers
        ibgp_local_as: iBGP local AS number (same as DUT)
        ixia_ibgp_ic_parent_network_v6: IPv6 network for iBGP peers
        ixia_ibgp_ic_parent_network_v4: IPv4 network for iBGP peers
        prefix_count: Number of prefixes to advertise per peer
        weight_10_community: BGP community for routes with weight 10
        weight_20_community: BGP community for routes with weight 20
        ebgp_route_acceptance_communities: Acceptance communities for eBGP routes
        test_address_families: Address families to test (default: ["ipv6"])

    Returns:
        List of BasicPortConfig objects for IXIA configuration
    """
    if test_address_families is None:
        test_address_families = ["ipv6"]

    if ebgp_route_acceptance_communities is None:
        ebgp_route_acceptance_communities = []

    # Build eBGP device groups (ingress - advertise routes with different communities)
    ebgp_device_groups: list[DeviceGroupConfig] = []
    device_group_index = 0

    # eBGP Group 1 - Weight 10 (lower preference)
    # Also includes NO_WEIGHT prefix pool for testing weight vs default weight
    if "ipv6" in test_address_families:
        # Communities for weight 10 routes
        weight_10_communities = [
            weight_10_community
        ] + ebgp_route_acceptance_communities

        # Communities for no-weight routes (only acceptance community, no weight community)
        # These routes will get default weight (0)
        no_weight_communities = list(ebgp_route_acceptance_communities)

        ebgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV6_EBGP_WEIGHT_10",
                device_group_index=device_group_index,
                multiplier=ebgp_peer_count_group1,
                v6_addresses_config=IpAddressesConfig(
                    starting_ip=f"{ixia_ebgp_ic_parent_network_v6}::11",
                    increment_ip="0:0:0:0::2",
                    gateway_starting_ip=f"{ixia_ebgp_ic_parent_network_v6}::10",
                    gateway_increment_ip="0:0:0:0::2",
                    start_index=0,
                ),
                v6_bgp_config=BgpConfig(
                    bgp_peer_name="BGP_PEER_IPV6_EBGP_WEIGHT_10",
                    local_as_4_bytes=ebgp_remote_as,
                    enable_4_byte_local_as=True,
                    enable_graceful_restart=False,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                    bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                    route_scales=[
                        RouteScaleSpec(
                            v6_route_scale=RouteScale(
                                prefix_name="PREFIX_POOL_IPV6_EBGP_WEIGHT_10",
                                starting_prefixes="2001:db8:1000::",
                                prefix_step="0:0:1::",
                                prefix_length=64,
                                multiplier=1,
                                prefix_count=prefix_count,
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                bgp_communities=weight_10_communities,
                            ),
                            multiplier=1,
                            network_group_index=0,
                        ),
                        # NO_WEIGHT prefix pool - same prefixes but no weight community
                        # Uses different prefix range to avoid overlap
                        RouteScaleSpec(
                            v6_route_scale=RouteScale(
                                prefix_name="PREFIX_POOL_IPV6_EBGP_NO_WEIGHT",
                                starting_prefixes="2001:db8:2000::",
                                prefix_step="0:0:1::",
                                prefix_length=64,
                                multiplier=1,
                                prefix_count=prefix_count,
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                bgp_communities=no_weight_communities,
                            ),
                            multiplier=1,
                            network_group_index=1,
                        ),
                    ],
                ),
            )
        )
        device_group_index += 1

    # eBGP Group 2 - Weight 20 (higher preference)
    # Also includes prefix pools for weight vs no-weight and ECMP tests
    if "ipv6" in test_address_families:
        # Communities for weight 20 routes
        weight_20_communities = [
            weight_20_community
        ] + ebgp_route_acceptance_communities

        # No-weight communities for Group 2 (for ECMP test)
        no_weight_communities_g2 = list(ebgp_route_acceptance_communities)

        # Calculate starting IP for group 2 based on group 1 count
        # Group 1 uses addresses starting from ::11 with step of 2
        # After ebgp_peer_count_group1 peers, next address is:
        # 0x11 + (ebgp_peer_count_group1 * 2) = 17 + (25 * 2) = 17 + 50 = 67 = 0x43
        # Gateway is even (0x42), peer is odd (0x43)
        group2_start_offset = 0x10 + (ebgp_peer_count_group1 * 2)
        group2_peer_start = (
            f"{ixia_ebgp_ic_parent_network_v6}::{group2_start_offset + 1:x}"
        )
        group2_gw_start = f"{ixia_ebgp_ic_parent_network_v6}::{group2_start_offset:x}"

        ebgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV6_EBGP_WEIGHT_20",
                device_group_index=device_group_index,
                multiplier=ebgp_peer_count_group2,
                v6_addresses_config=IpAddressesConfig(
                    starting_ip=group2_peer_start,
                    increment_ip="0:0:0:0::2",
                    gateway_starting_ip=group2_gw_start,
                    gateway_increment_ip="0:0:0:0::2",
                    start_index=0,
                ),
                v6_bgp_config=BgpConfig(
                    bgp_peer_name="BGP_PEER_IPV6_EBGP_WEIGHT_20",
                    local_as_4_bytes=ebgp_remote_as,
                    enable_4_byte_local_as=True,
                    enable_graceful_restart=False,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                    bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                    route_scales=[
                        RouteScaleSpec(
                            v6_route_scale=RouteScale(
                                prefix_name="PREFIX_POOL_IPV6_EBGP_WEIGHT_20",
                                # Same prefixes as WEIGHT_10 for weight comparison
                                starting_prefixes="2001:db8:1000::",
                                prefix_step="0:0:1::",
                                prefix_length=64,
                                multiplier=1,
                                prefix_count=prefix_count,
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                bgp_communities=weight_20_communities,
                            ),
                            multiplier=1,
                            network_group_index=0,
                        ),
                        # Weight 20 version of NO_WEIGHT prefixes for weight vs no-weight test
                        # Same prefix range as NO_WEIGHT pool (2001:db8:2000::) but with weight 20 community
                        RouteScaleSpec(
                            v6_route_scale=RouteScale(
                                prefix_name="PREFIX_POOL_IPV6_EBGP_WEIGHT_20_VS_NOWEIGHT",
                                starting_prefixes="2001:db8:2000::",
                                prefix_step="0:0:1::",
                                prefix_length=64,
                                multiplier=1,
                                prefix_count=prefix_count,
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                bgp_communities=weight_20_communities,
                            ),
                            multiplier=1,
                            network_group_index=1,
                        ),
                        # NO_WEIGHT prefix pool for Group 2 - for ECMP test
                        # Same prefix range as Group 1's NO_WEIGHT, no weight community
                        # When both groups advertise without weight → ECMP
                        RouteScaleSpec(
                            v6_route_scale=RouteScale(
                                prefix_name="PREFIX_POOL_IPV6_EBGP_NO_WEIGHT_G2",
                                starting_prefixes="2001:db8:2000::",
                                prefix_step="0:0:1::",
                                prefix_length=64,
                                multiplier=1,
                                prefix_count=prefix_count,
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                bgp_communities=no_weight_communities_g2,
                            ),
                            multiplier=1,
                            network_group_index=2,
                        ),
                    ],
                ),
            )
        )
        device_group_index += 1

    # IPv4 eBGP groups
    if "ipv4" in test_address_families:
        weight_10_communities = [
            weight_10_community
        ] + ebgp_route_acceptance_communities
        weight_20_communities = [
            weight_20_community
        ] + ebgp_route_acceptance_communities
        # No-weight routes (only acceptance community)
        no_weight_communities_v4 = list(ebgp_route_acceptance_communities)

        # eBGP Group 1 - IPv4 - Weight 10
        # Device uses start_offset=16, so local=.16, peer=.17
        # Also includes NO_WEIGHT prefix pool for testing weight vs default weight
        ebgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV4_EBGP_WEIGHT_10",
                device_group_index=device_group_index,
                multiplier=ebgp_peer_count_group1,
                v4_addresses_config=IpAddressesConfig(
                    starting_ip=f"{ixia_ebgp_ic_parent_network_v4}.17",
                    increment_ip="0.0.0.2",
                    gateway_starting_ip=f"{ixia_ebgp_ic_parent_network_v4}.16",
                    gateway_increment_ip="0.0.0.2",
                    mask=31,
                    start_index=0,
                ),
                v4_bgp_config=BgpConfig(
                    bgp_peer_name="BGP_PEER_IPV4_EBGP_WEIGHT_10",
                    local_as_4_bytes=ebgp_remote_as,
                    enable_4_byte_local_as=True,
                    enable_graceful_restart=False,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                    bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                    route_scales=[
                        RouteScaleSpec(
                            v4_route_scale=RouteScale(
                                prefix_name="PREFIX_POOL_IPV4_EBGP_WEIGHT_10",
                                starting_prefixes="10.100.0.0",
                                prefix_step="0.1.0.0",
                                prefix_length=24,
                                multiplier=1,
                                prefix_count=prefix_count,
                                ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                bgp_communities=weight_10_communities,
                            ),
                            multiplier=1,
                            network_group_index=0,
                        ),
                        # NO_WEIGHT prefix pool - no weight community, only acceptance community
                        RouteScaleSpec(
                            v4_route_scale=RouteScale(
                                prefix_name="PREFIX_POOL_IPV4_EBGP_NO_WEIGHT",
                                starting_prefixes="10.200.0.0",
                                prefix_step="0.1.0.0",
                                prefix_length=24,
                                multiplier=1,
                                prefix_count=prefix_count,
                                ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                bgp_communities=no_weight_communities_v4,
                            ),
                            multiplier=1,
                            network_group_index=1,
                        ),
                    ],
                ),
            )
        )
        device_group_index += 1

        # eBGP Group 2 - IPv4 - Weight 20
        # Calculate starting IP for group 2 based on group 1 count
        # Device uses start_offset=16, so group 1 starts at .16/.17
        # After ebgp_peer_count_group1 peers, next address is:
        # 16 + (ebgp_peer_count_group1 * 2) = 16 + (1 * 2) = 18
        # Gateway is even (18), peer is odd (19)
        group2_v4_start_offset = 16 + (ebgp_peer_count_group1 * 2)
        group2_v4_peer_start = (
            f"{ixia_ebgp_ic_parent_network_v4}.{group2_v4_start_offset + 1}"
        )
        group2_v4_gw_start = (
            f"{ixia_ebgp_ic_parent_network_v4}.{group2_v4_start_offset}"
        )

        ebgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV4_EBGP_WEIGHT_20",
                device_group_index=device_group_index,
                multiplier=ebgp_peer_count_group2,
                v4_addresses_config=IpAddressesConfig(
                    starting_ip=group2_v4_peer_start,
                    increment_ip="0.0.0.2",
                    gateway_starting_ip=group2_v4_gw_start,
                    gateway_increment_ip="0.0.0.2",
                    mask=31,
                    start_index=0,
                ),
                v4_bgp_config=BgpConfig(
                    bgp_peer_name="BGP_PEER_IPV4_EBGP_WEIGHT_20",
                    local_as_4_bytes=ebgp_remote_as,
                    enable_4_byte_local_as=True,
                    enable_graceful_restart=False,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                    bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                    route_scales=[
                        RouteScaleSpec(
                            v4_route_scale=RouteScale(
                                prefix_name="PREFIX_POOL_IPV4_EBGP_WEIGHT_20",
                                # Same prefixes as WEIGHT_10 for weight comparison
                                starting_prefixes="10.100.0.0",
                                prefix_step="0.1.0.0",
                                prefix_length=24,
                                multiplier=1,
                                prefix_count=prefix_count,
                                ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                bgp_communities=weight_20_communities,
                            ),
                            multiplier=1,
                            network_group_index=0,
                        ),
                        # Weight 20 version of NO_WEIGHT prefixes for weight vs no-weight test
                        RouteScaleSpec(
                            v4_route_scale=RouteScale(
                                prefix_name="PREFIX_POOL_IPV4_EBGP_WEIGHT_20_VS_NOWEIGHT",
                                starting_prefixes="10.200.0.0",
                                prefix_step="0.1.0.0",
                                prefix_length=24,
                                multiplier=1,
                                prefix_count=prefix_count,
                                ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                bgp_communities=weight_20_communities,
                            ),
                            multiplier=1,
                            network_group_index=1,
                        ),
                        # NO_WEIGHT prefix pool for Group 2 - for ECMP test
                        # Same prefix range as Group 1's NO_WEIGHT, no weight community
                        RouteScaleSpec(
                            v4_route_scale=RouteScale(
                                prefix_name="PREFIX_POOL_IPV4_EBGP_NO_WEIGHT_G2",
                                starting_prefixes="10.200.0.0",
                                prefix_step="0.1.0.0",
                                prefix_length=24,
                                multiplier=1,
                                prefix_count=prefix_count,
                                ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                bgp_communities=no_weight_communities_v4,
                            ),
                            multiplier=1,
                            network_group_index=2,
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
        # Device uses start_offset=16, so local=.16, peer=.17
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
        # eBGP configuration (ingress - routes sent here with different communities)
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
