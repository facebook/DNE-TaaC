# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""
IXIA port configurations for BGP MED (Multi-Exit Discriminator) feature testing.

This module provides IXIA device group configurations for testing the BGP MED
attribute in EOS BGP++.

Test Design - EBGP to IBGP Scenario:
    - IXIA mimics EBGP peers (same AS) sending routes with different MED values
    - Device compares MED and selects lower MED as best path
    - IXIA mimics IBGP peers as listeners to verify best path selection
    - Routes with lower MED should be selected as best

MED Behavior:
    - Lower MED is preferred (opposite of weight)
    - MED is only compared between routes from the same neighboring AS
    - Default MED is typically 0 or missing (implementation dependent)
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


def create_med_test_basic_port_configs(
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
    ebgp_route_acceptance_communities: list[str] | None = None,
    # Address family selection
    test_address_families: list[str] | None = None,
) -> list[BasicPortConfig]:
    """
    Create basic port configurations for BGP MED feature testing.

    This function generates IXIA port configurations with:
    - eBGP interface: Two device groups (same AS) advertising routes with different MED
      * Group 1: Routes with high MED (less preferred)
      * Group 2: Routes with low MED (preferred) - same prefixes as group 1
    - iBGP interface: Listener peers to verify best path selection

    Args:
        device_name: Name of the device under test
        ixia_interface_ebgp: IXIA interface for eBGP peers (ingress)
        ebgp_peer_count_group1: Number of eBGP peers in group 1 (high MED)
        ebgp_peer_count_group2: Number of eBGP peers in group 2 (low MED)
        ebgp_remote_as: eBGP remote AS number (same for both groups)
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

    # Build eBGP device groups (ingress - advertise routes with different MED)
    ebgp_device_groups: list[DeviceGroupConfig] = []
    device_group_index = 0

    # eBGP Group 1 - High MED (less preferred)
    if "ipv6" in test_address_families:
        ebgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV6_EBGP_MED_HIGH",
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
                    bgp_peer_name="BGP_PEER_IPV6_EBGP_MED_HIGH",
                    local_as_4_bytes=ebgp_remote_as,
                    enable_4_byte_local_as=True,
                    enable_graceful_restart=False,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                    bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                    route_scales=[
                        RouteScaleSpec(
                            v6_route_scale=RouteScale(
                                prefix_name="PREFIX_POOL_IPV6_EBGP_MED_HIGH",
                                starting_prefixes="2001:db8:3000::",
                                prefix_step="0:0:1::",
                                prefix_length=64,
                                multiplier=1,
                                prefix_count=prefix_count,
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                bgp_communities=ebgp_route_acceptance_communities,
                                # MED is set dynamically via ixia_modify_bgp_prefixes_med_value task
                            ),
                            multiplier=1,
                            network_group_index=0,
                        ),
                        # NO_MED prefix pool - routes without MED set
                        RouteScaleSpec(
                            v6_route_scale=RouteScale(
                                prefix_name="PREFIX_POOL_IPV6_EBGP_NO_MED",
                                starting_prefixes="2001:db8:4000::",
                                prefix_step="0:0:1::",
                                prefix_length=64,
                                multiplier=1,
                                prefix_count=prefix_count,
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                bgp_communities=ebgp_route_acceptance_communities,
                                # No MED set - will use default
                            ),
                            multiplier=1,
                            network_group_index=1,
                        ),
                    ],
                ),
            )
        )
        device_group_index += 1

    # eBGP Group 2 - Low MED (preferred)
    if "ipv6" in test_address_families:
        # Calculate starting IP for group 2 based on group 1 count
        group2_start_offset = 0x10 + (ebgp_peer_count_group1 * 2)
        group2_peer_start = (
            f"{ixia_ebgp_ic_parent_network_v6}::{group2_start_offset + 1:x}"
        )
        group2_gw_start = f"{ixia_ebgp_ic_parent_network_v6}::{group2_start_offset:x}"

        ebgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV6_EBGP_MED_LOW",
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
                    bgp_peer_name="BGP_PEER_IPV6_EBGP_MED_LOW",
                    local_as_4_bytes=ebgp_remote_as,
                    enable_4_byte_local_as=True,
                    enable_graceful_restart=False,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                    bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                    route_scales=[
                        RouteScaleSpec(
                            v6_route_scale=RouteScale(
                                prefix_name="PREFIX_POOL_IPV6_EBGP_MED_LOW",
                                # Same prefixes as MED_HIGH for comparison
                                starting_prefixes="2001:db8:3000::",
                                prefix_step="0:0:1::",
                                prefix_length=64,
                                multiplier=1,
                                prefix_count=prefix_count,
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                bgp_communities=ebgp_route_acceptance_communities,
                                # MED is set dynamically via ixia_modify_bgp_prefixes_med_value task
                            ),
                            multiplier=1,
                            network_group_index=0,
                        ),
                        # Low MED version of NO_MED prefixes for MED vs no-MED test
                        RouteScaleSpec(
                            v6_route_scale=RouteScale(
                                prefix_name="PREFIX_POOL_IPV6_EBGP_MED_LOW_VS_NOMED",
                                starting_prefixes="2001:db8:4000::",
                                prefix_step="0:0:1::",
                                prefix_length=64,
                                multiplier=1,
                                prefix_count=prefix_count,
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                bgp_communities=ebgp_route_acceptance_communities,
                                # MED is set dynamically via ixia_modify_bgp_prefixes_med_value task
                            ),
                            multiplier=1,
                            network_group_index=1,
                        ),
                        # NO_MED prefix pool for Group 2 - for ECMP test
                        RouteScaleSpec(
                            v6_route_scale=RouteScale(
                                prefix_name="PREFIX_POOL_IPV6_EBGP_NO_MED_G2",
                                starting_prefixes="2001:db8:4000::",
                                prefix_step="0:0:1::",
                                prefix_length=64,
                                multiplier=1,
                                prefix_count=prefix_count,
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                bgp_communities=ebgp_route_acceptance_communities,
                                # No MED set - will use default
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
        # eBGP Group 1 - IPv4 - High MED
        ebgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV4_EBGP_MED_HIGH",
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
                    bgp_peer_name="BGP_PEER_IPV4_EBGP_MED_HIGH",
                    local_as_4_bytes=ebgp_remote_as,
                    enable_4_byte_local_as=True,
                    enable_graceful_restart=False,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                    bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                    route_scales=[
                        RouteScaleSpec(
                            v4_route_scale=RouteScale(
                                prefix_name="PREFIX_POOL_IPV4_EBGP_MED_HIGH",
                                starting_prefixes="10.150.0.0",
                                prefix_step="0.1.0.0",
                                prefix_length=24,
                                multiplier=1,
                                prefix_count=prefix_count,
                                ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                bgp_communities=ebgp_route_acceptance_communities,
                                # MED is set dynamically via ixia_modify_bgp_prefixes_med_value task
                            ),
                            multiplier=1,
                            network_group_index=0,
                        ),
                        # NO_MED prefix pool
                        RouteScaleSpec(
                            v4_route_scale=RouteScale(
                                prefix_name="PREFIX_POOL_IPV4_EBGP_NO_MED",
                                starting_prefixes="10.250.0.0",
                                prefix_step="0.1.0.0",
                                prefix_length=24,
                                multiplier=1,
                                prefix_count=prefix_count,
                                ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                bgp_communities=ebgp_route_acceptance_communities,
                                # No MED set
                            ),
                            multiplier=1,
                            network_group_index=1,
                        ),
                    ],
                ),
            )
        )
        device_group_index += 1

        # eBGP Group 2 - IPv4 - Low MED
        group2_v4_start_offset = 16 + (ebgp_peer_count_group1 * 2)
        group2_v4_peer_start = (
            f"{ixia_ebgp_ic_parent_network_v4}.{group2_v4_start_offset + 1}"
        )
        group2_v4_gw_start = (
            f"{ixia_ebgp_ic_parent_network_v4}.{group2_v4_start_offset}"
        )

        ebgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV4_EBGP_MED_LOW",
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
                    bgp_peer_name="BGP_PEER_IPV4_EBGP_MED_LOW",
                    local_as_4_bytes=ebgp_remote_as,
                    enable_4_byte_local_as=True,
                    enable_graceful_restart=False,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                    bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                    route_scales=[
                        RouteScaleSpec(
                            v4_route_scale=RouteScale(
                                prefix_name="PREFIX_POOL_IPV4_EBGP_MED_LOW",
                                # Same prefixes as MED_HIGH for comparison
                                starting_prefixes="10.150.0.0",
                                prefix_step="0.1.0.0",
                                prefix_length=24,
                                multiplier=1,
                                prefix_count=prefix_count,
                                ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                bgp_communities=ebgp_route_acceptance_communities,
                                # MED is set dynamically via ixia_modify_bgp_prefixes_med_value task
                            ),
                            multiplier=1,
                            network_group_index=0,
                        ),
                        # Low MED version of NO_MED prefixes
                        RouteScaleSpec(
                            v4_route_scale=RouteScale(
                                prefix_name="PREFIX_POOL_IPV4_EBGP_MED_LOW_VS_NOMED",
                                starting_prefixes="10.250.0.0",
                                prefix_step="0.1.0.0",
                                prefix_length=24,
                                multiplier=1,
                                prefix_count=prefix_count,
                                ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                bgp_communities=ebgp_route_acceptance_communities,
                                # MED is set dynamically via ixia_modify_bgp_prefixes_med_value task
                            ),
                            multiplier=1,
                            network_group_index=1,
                        ),
                        # NO_MED prefix pool for Group 2 - for ECMP test
                        RouteScaleSpec(
                            v4_route_scale=RouteScale(
                                prefix_name="PREFIX_POOL_IPV4_EBGP_NO_MED_G2",
                                starting_prefixes="10.250.0.0",
                                prefix_step="0.1.0.0",
                                prefix_length=24,
                                multiplier=1,
                                prefix_count=prefix_count,
                                ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                bgp_communities=ebgp_route_acceptance_communities,
                                # No MED set
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
        # eBGP configuration (ingress - routes sent here with different MED)
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
