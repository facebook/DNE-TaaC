# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""
IXIA port configurations for BGP fast neighbor tear down (fast reset) testing.

This module provides IXIA device group configurations for testing the BGP
fast neighbor tear down mechanism in EOS BGP++.

Test Design:
    - Fast reset uses netlink LINK_EVENT to detect physical link failures
    - When a directly connected eBGP peer's link goes down, BGP should tear
      down the session immediately (within seconds) rather than waiting for
      hold timer expiration (typically 90-180 seconds)

Test Scenarios:
    1. Single Link Failure: One eBGP peer link goes down, verify fast tear down
    2. Multiple Simultaneous Failures: Multiple links fail at once, verify stability
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


def create_fast_reset_test_basic_port_configs(
    device_name: str,
    # eBGP interface configuration
    ixia_interfaces_ebgp: list[str],
    ebgp_peer_count_per_interface: int,
    ebgp_remote_as: int,
    ixia_ebgp_ic_parent_networks_v6: list[str],
    ixia_ebgp_ic_parent_networks_v4: list[str],
    # iBGP interface (listener)
    ixia_interface_ibgp: str | None = None,
    ibgp_peer_count: int = 0,
    ibgp_local_as: int = 0,
    ixia_ibgp_ic_parent_network_v6: str = "",
    ixia_ibgp_ic_parent_network_v4: str = "",
    # Route configuration
    prefix_count: int = 100,
    ebgp_route_acceptance_communities: list[str] | None = None,
    # Address family selection
    test_address_families: list[str] | None = None,
) -> list[BasicPortConfig]:
    """
    Create basic port configurations for BGP fast reset testing.

    This function generates IXIA port configurations with:
    - Multiple eBGP interfaces for testing simultaneous link failures
    - Optional iBGP listener interface for route propagation verification

    Args:
        device_name: Name of the device under test
        ixia_interfaces_ebgp: List of IXIA interfaces for eBGP peers
        ebgp_peer_count_per_interface: Number of eBGP peers per interface
        ebgp_remote_as: eBGP remote AS number
        ixia_ebgp_ic_parent_networks_v6: IPv6 networks for each eBGP interface
        ixia_ebgp_ic_parent_networks_v4: IPv4 networks for each eBGP interface
        ixia_interface_ibgp: Optional IXIA interface for iBGP listeners
        ibgp_peer_count: Number of iBGP listener peers
        ibgp_local_as: iBGP local AS number
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

    basic_port_configs: list[BasicPortConfig] = []

    # Create eBGP port configurations for each interface
    for idx, ixia_interface in enumerate(ixia_interfaces_ebgp):
        ebgp_device_groups: list[DeviceGroupConfig] = []
        device_group_index = 0

        if "ipv6" in test_address_families:
            v6_network = ixia_ebgp_ic_parent_networks_v6[idx]
            ebgp_device_groups.append(
                DeviceGroupConfig(
                    device_group_name=f"DEVICE_GROUP_IPV6_EBGP_FAST_RESET_{idx}",
                    device_group_index=device_group_index,
                    multiplier=ebgp_peer_count_per_interface,
                    v6_addresses_config=IpAddressesConfig(
                        starting_ip=f"{v6_network}::11",
                        increment_ip="0:0:0:0::2",
                        gateway_starting_ip=f"{v6_network}::10",
                        gateway_increment_ip="0:0:0:0::2",
                        start_index=0,
                    ),
                    v6_bgp_config=BgpConfig(
                        bgp_peer_name=f"BGP_PEER_IPV6_EBGP_FAST_RESET_{idx}",
                        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                        local_as_4_bytes=ebgp_remote_as,
                        enable_4_byte_local_as=True,
                        enable_graceful_restart=False,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        route_scales=[
                            RouteScaleSpec(
                                v6_route_scale=RouteScale(
                                    prefix_name=f"PREFIX_POOL_IPV6_EBGP_FAST_RESET_{idx}",
                                    starting_prefixes=f"2001:db8:{0x1000 + idx * 0x100:x}::",
                                    prefix_step="0:0:1::",
                                    prefix_length=64,
                                    multiplier=1,
                                    prefix_count=prefix_count,
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    bgp_communities=ebgp_route_acceptance_communities,
                                ),
                                multiplier=1,
                                network_group_index=0,
                            ),
                        ],
                    ),
                )
            )
            device_group_index += 1

        if "ipv4" in test_address_families:
            v4_network = ixia_ebgp_ic_parent_networks_v4[idx]
            # Parse the network to get base (e.g., "10.0.0" from "10.0.0.0")
            network_parts = v4_network.rsplit(".", 1)
            base_network = network_parts[0] if len(network_parts) > 1 else v4_network

            ebgp_device_groups.append(
                DeviceGroupConfig(
                    device_group_name=f"DEVICE_GROUP_IPV4_EBGP_FAST_RESET_{idx}",
                    device_group_index=device_group_index,
                    multiplier=ebgp_peer_count_per_interface,
                    v4_addresses_config=IpAddressesConfig(
                        starting_ip=f"{base_network}.17",
                        increment_ip="0.0.0.2",
                        gateway_starting_ip=f"{base_network}.16",
                        gateway_increment_ip="0.0.0.2",
                        mask=31,
                        start_index=0,
                    ),
                    v4_bgp_config=BgpConfig(
                        bgp_peer_name=f"BGP_PEER_IPV4_EBGP_FAST_RESET_{idx}",
                        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                        local_as_4_bytes=ebgp_remote_as,
                        enable_4_byte_local_as=True,
                        enable_graceful_restart=False,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                        route_scales=[
                            RouteScaleSpec(
                                v4_route_scale=RouteScale(
                                    prefix_name=f"PREFIX_POOL_IPV4_EBGP_FAST_RESET_{idx}",
                                    starting_prefixes=f"10.{100 + idx}.0.0",
                                    prefix_step="0.0.1.0",
                                    prefix_length=24,
                                    multiplier=1,
                                    prefix_count=prefix_count,
                                    ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                    bgp_communities=ebgp_route_acceptance_communities,
                                ),
                                multiplier=1,
                                network_group_index=0,
                            ),
                        ],
                    ),
                )
            )
            device_group_index += 1

        basic_port_configs.append(
            BasicPortConfig(
                endpoint=f"{device_name}:{ixia_interface}",
                device_group_configs=ebgp_device_groups,
            )
        )

    # Create iBGP listener port configuration if specified
    if ixia_interface_ibgp and ibgp_peer_count > 0:
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
                        bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                        local_as_4_bytes=ibgp_local_as,
                        enable_4_byte_local_as=True,
                        enable_graceful_restart=False,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        # No route_scales - listeners only
                    ),
                )
            )
            ibgp_device_group_index += 1

        if "ipv4" in test_address_families:
            v4_network = ixia_ibgp_ic_parent_network_v4
            network_parts = v4_network.rsplit(".", 1)
            base_network = network_parts[0] if len(network_parts) > 1 else v4_network

            ibgp_device_groups.append(
                DeviceGroupConfig(
                    device_group_name="DEVICE_GROUP_IPV4_IBGP_LISTENER",
                    device_group_index=ibgp_device_group_index,
                    multiplier=ibgp_peer_count,
                    v4_addresses_config=IpAddressesConfig(
                        starting_ip=f"{base_network}.17",
                        increment_ip="0.0.0.2",
                        gateway_starting_ip=f"{base_network}.16",
                        gateway_increment_ip="0.0.0.2",
                        mask=31,
                        start_index=0,
                    ),
                    v4_bgp_config=BgpConfig(
                        bgp_peer_name="BGP_PEER_IPV4_IBGP_LISTENER",
                        bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                        local_as_4_bytes=ibgp_local_as,
                        enable_4_byte_local_as=True,
                        enable_graceful_restart=False,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                        # No route_scales - listeners only
                    ),
                )
            )
            ibgp_device_group_index += 1

        basic_port_configs.append(
            BasicPortConfig(
                endpoint=f"{device_name}:{ixia_interface_ibgp}",
                device_group_configs=ibgp_device_groups,
            )
        )

    return basic_port_configs
