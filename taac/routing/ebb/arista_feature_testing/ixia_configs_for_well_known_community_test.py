# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""
IXIA port configurations for RFC 1997 well-known community feature testing.

Simplified topology — 5 eBGP + 5 iBGP peers, always up:
    - eBGP port: 1 device group with 5 peers, all advertising routes with
      ALL 4 community types (NO_EXPORT, NO_ADVERTISE, NO_EXPORT_SUBCONFED,
      BASELINE) using distinct prefix ranges.
    - iBGP port: 1 device group with 5 peers, same setup.

All sessions stay up throughout the test. The custom verification step
checks filtering per-community by matching on prefix ranges.

RFC 1997 Well-Known Community Behavior Matrix:
    NO_EXPORT (65535:65281)         -> suppressed to EBGP only
    NO_ADVERTISE (65535:65282)      -> suppressed to ANY peer
    NO_EXPORT_SUBCONFED (65535:65283) -> suppressed to EBGP and ConfedEBGP

Guarded by feature flag: --enable_well_known_community_filter=true
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

# RFC 1997 well-known communities in numeric ASN:value form
NO_EXPORT_COMMUNITY: str = "65535:65281"
NO_ADVERTISE_COMMUNITY: str = "65535:65282"
NO_EXPORT_SUBCONFED_COMMUNITY: str = "65535:65283"


def create_well_known_community_test_basic_port_configs(
    device_name: str,
    # eBGP interface
    ixia_interface_ebgp: str,
    ebgp_peer_count: int,
    ebgp_remote_as: int,
    ixia_ebgp_ic_parent_network_v6: str,
    ixia_ebgp_ic_parent_network_v4: str,
    # iBGP interface
    ixia_interface_ibgp: str,
    ibgp_peer_count: int,
    ibgp_local_as: int,
    ixia_ibgp_ic_parent_network_v6: str,
    ixia_ibgp_ic_parent_network_v4: str,
    # Route configuration
    prefix_count: int = 100,
    ebgp_route_acceptance_communities: list[str] | None = None,
    # Address family selection
    test_address_families: list[str] | None = None,
) -> list[BasicPortConfig]:
    """
    Create IXIA port configs for RFC 1997 well-known community testing.

    Simple topology: 5 eBGP peers + 5 iBGP peers, always up.
    Each peer advertises ALL 4 community types via distinct prefix ranges.

    eBGP prefix ranges:
        NO_EXPORT:          2001:db8:3000::/64  (100 prefixes)
        NO_ADVERTISE:       2001:db8:4000::/64  (100 prefixes)
        NO_EXPORT_SUBCONFED:2001:db8:5000::/64  (100 prefixes)
        BASELINE:           2001:db8:6000::/64  (100 prefixes)

    iBGP prefix ranges:
        NO_EXPORT:          2001:db8:7000::/64  (100 prefixes)
        NO_ADVERTISE:       2001:db8:8000::/64  (100 prefixes)
        NO_EXPORT_SUBCONFED:2001:db8:9000::/64  (100 prefixes)
        BASELINE:           2001:db8:a000::/64  (100 prefixes)
    """
    if test_address_families is None:
        test_address_families = ["ipv6"]

    if ebgp_route_acceptance_communities is None:
        ebgp_route_acceptance_communities = []

    # Community sets: well-known community + route acceptance community
    no_export_communities = [
        NO_EXPORT_COMMUNITY,
    ] + ebgp_route_acceptance_communities
    no_advertise_communities = [
        NO_ADVERTISE_COMMUNITY,
    ] + ebgp_route_acceptance_communities
    no_export_subconfed_communities = [
        NO_EXPORT_SUBCONFED_COMMUNITY,
    ] + ebgp_route_acceptance_communities
    baseline_communities = list(ebgp_route_acceptance_communities)

    # ======================================================================
    # eBGP device group — 1 group with ebgp_peer_count peers
    # All peers advertise ALL 4 community prefix pools simultaneously
    # ======================================================================
    ebgp_device_groups: list[DeviceGroupConfig] = []

    if "ipv6" in test_address_families:
        ebgp_route_scales = [
            RouteScaleSpec(
                v6_route_scale=RouteScale(
                    prefix_name="PREFIX_POOL_IPV6_EBGP_NO_EXPORT",
                    starting_prefixes="2001:db8:3000::",
                    prefix_step="0:0:1::",
                    prefix_length=64,
                    multiplier=1,
                    prefix_count=prefix_count,
                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                    bgp_communities=no_export_communities,
                ),
                multiplier=1,
                network_group_index=0,
            ),
            RouteScaleSpec(
                v6_route_scale=RouteScale(
                    prefix_name="PREFIX_POOL_IPV6_EBGP_NO_ADVERTISE",
                    starting_prefixes="2001:db8:4000::",
                    prefix_step="0:0:1::",
                    prefix_length=64,
                    multiplier=1,
                    prefix_count=prefix_count,
                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                    bgp_communities=no_advertise_communities,
                ),
                multiplier=1,
                network_group_index=1,
            ),
            RouteScaleSpec(
                v6_route_scale=RouteScale(
                    prefix_name="PREFIX_POOL_IPV6_EBGP_NO_EXPORT_SUBCONFED",
                    starting_prefixes="2001:db8:5000::",
                    prefix_step="0:0:1::",
                    prefix_length=64,
                    multiplier=1,
                    prefix_count=prefix_count,
                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                    bgp_communities=no_export_subconfed_communities,
                ),
                multiplier=1,
                network_group_index=2,
            ),
            RouteScaleSpec(
                v6_route_scale=RouteScale(
                    prefix_name="PREFIX_POOL_IPV6_EBGP_BASELINE",
                    starting_prefixes="2001:db8:6000::",
                    prefix_step="0:0:1::",
                    prefix_length=64,
                    multiplier=1,
                    prefix_count=prefix_count,
                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                    bgp_communities=baseline_communities,
                ),
                multiplier=1,
                network_group_index=3,
            ),
        ]

        ebgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV6_EBGP",
                device_group_index=0,
                multiplier=ebgp_peer_count,
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
                    enable_graceful_restart=False,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                    bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                    route_scales=ebgp_route_scales,
                ),
            )
        )

    if "ipv4" in test_address_families:
        ebgp_route_scales_v4 = [
            RouteScaleSpec(
                v4_route_scale=RouteScale(
                    prefix_name="PREFIX_POOL_IPV4_EBGP_NO_EXPORT",
                    starting_prefixes="10.30.0.0",
                    prefix_step="0.1.0.0",
                    prefix_length=24,
                    multiplier=1,
                    prefix_count=prefix_count,
                    ip_address_family=ixia_types.IpAddressFamily.IPV4,
                    bgp_communities=no_export_communities,
                ),
                multiplier=1,
                network_group_index=0,
            ),
            RouteScaleSpec(
                v4_route_scale=RouteScale(
                    prefix_name="PREFIX_POOL_IPV4_EBGP_NO_ADVERTISE",
                    starting_prefixes="10.40.0.0",
                    prefix_step="0.1.0.0",
                    prefix_length=24,
                    multiplier=1,
                    prefix_count=prefix_count,
                    ip_address_family=ixia_types.IpAddressFamily.IPV4,
                    bgp_communities=no_advertise_communities,
                ),
                multiplier=1,
                network_group_index=1,
            ),
            RouteScaleSpec(
                v4_route_scale=RouteScale(
                    prefix_name="PREFIX_POOL_IPV4_EBGP_NO_EXPORT_SUBCONFED",
                    starting_prefixes="10.50.0.0",
                    prefix_step="0.1.0.0",
                    prefix_length=24,
                    multiplier=1,
                    prefix_count=prefix_count,
                    ip_address_family=ixia_types.IpAddressFamily.IPV4,
                    bgp_communities=no_export_subconfed_communities,
                ),
                multiplier=1,
                network_group_index=2,
            ),
            RouteScaleSpec(
                v4_route_scale=RouteScale(
                    prefix_name="PREFIX_POOL_IPV4_EBGP_BASELINE",
                    starting_prefixes="10.60.0.0",
                    prefix_step="0.1.0.0",
                    prefix_length=24,
                    multiplier=1,
                    prefix_count=prefix_count,
                    ip_address_family=ixia_types.IpAddressFamily.IPV4,
                    bgp_communities=baseline_communities,
                ),
                multiplier=1,
                network_group_index=3,
            ),
        ]

        ebgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV4_EBGP",
                device_group_index=1,
                multiplier=ebgp_peer_count,
                v4_addresses_config=IpAddressesConfig(
                    starting_ip=f"{ixia_ebgp_ic_parent_network_v4}.17",
                    increment_ip="0.0.0.2",
                    gateway_starting_ip=f"{ixia_ebgp_ic_parent_network_v4}.16",
                    gateway_increment_ip="0.0.0.2",
                    mask=31,
                    start_index=0,
                ),
                v4_bgp_config=BgpConfig(
                    bgp_peer_name="BGP_PEER_IPV4_EBGP",
                    local_as_4_bytes=ebgp_remote_as,
                    enable_4_byte_local_as=True,
                    enable_graceful_restart=False,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                    bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                    route_scales=ebgp_route_scales_v4,
                ),
            )
        )

    # ======================================================================
    # iBGP device group — 1 group with ibgp_peer_count peers
    # All peers advertise ALL 4 community prefix pools simultaneously
    # ======================================================================
    ibgp_device_groups: list[DeviceGroupConfig] = []

    if "ipv6" in test_address_families:
        ibgp_route_scales = [
            RouteScaleSpec(
                v6_route_scale=RouteScale(
                    prefix_name="PREFIX_POOL_IPV6_IBGP_NO_EXPORT",
                    starting_prefixes="2001:db8:7000::",
                    prefix_step="0:0:1::",
                    prefix_length=64,
                    multiplier=1,
                    prefix_count=prefix_count,
                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                    bgp_communities=no_export_communities,
                ),
                multiplier=1,
                network_group_index=0,
            ),
            RouteScaleSpec(
                v6_route_scale=RouteScale(
                    prefix_name="PREFIX_POOL_IPV6_IBGP_NO_ADVERTISE",
                    starting_prefixes="2001:db8:8000::",
                    prefix_step="0:0:1::",
                    prefix_length=64,
                    multiplier=1,
                    prefix_count=prefix_count,
                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                    bgp_communities=no_advertise_communities,
                ),
                multiplier=1,
                network_group_index=1,
            ),
            RouteScaleSpec(
                v6_route_scale=RouteScale(
                    prefix_name="PREFIX_POOL_IPV6_IBGP_NO_EXPORT_SUBCONFED",
                    starting_prefixes="2001:db8:9000::",
                    prefix_step="0:0:1::",
                    prefix_length=64,
                    multiplier=1,
                    prefix_count=prefix_count,
                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                    bgp_communities=no_export_subconfed_communities,
                ),
                multiplier=1,
                network_group_index=2,
            ),
            RouteScaleSpec(
                v6_route_scale=RouteScale(
                    prefix_name="PREFIX_POOL_IPV6_IBGP_BASELINE",
                    starting_prefixes="2001:db8:a000::",
                    prefix_step="0:0:1::",
                    prefix_length=64,
                    multiplier=1,
                    prefix_count=prefix_count,
                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                    bgp_communities=baseline_communities,
                ),
                multiplier=1,
                network_group_index=3,
            ),
        ]

        ibgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV6_IBGP",
                device_group_index=0,
                multiplier=ibgp_peer_count,
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
                    enable_graceful_restart=False,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                    bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                    route_scales=ibgp_route_scales,
                ),
            )
        )

    if "ipv4" in test_address_families:
        ibgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV4_IBGP",
                device_group_index=1,
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
                    bgp_peer_name="BGP_PEER_IPV4_IBGP",
                    local_as_4_bytes=ibgp_local_as,
                    enable_4_byte_local_as=True,
                    enable_graceful_restart=False,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                    bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                ),
            )
        )

    return [
        BasicPortConfig(
            endpoint=f"{device_name}:{ixia_interface_ebgp}",
            device_group_configs=ebgp_device_groups,
        ),
        BasicPortConfig(
            endpoint=f"{device_name}:{ixia_interface_ibgp}",
            device_group_configs=ibgp_device_groups,
        ),
    ]
