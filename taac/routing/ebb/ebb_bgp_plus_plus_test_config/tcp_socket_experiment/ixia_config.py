# pyre-unsafe
"""
IXIA BasicPortConfig generation for TCP Socket Experiment.

Provides factory functions to create IXIA BasicPortConfig for both test cases:
    Case 1: 1 IXIA peer → bag012 (BGP++) with 15K prefixes
    Case 2: 140 IXIA peers → bag012 (BGP++) receiving redistributed routes
            + 1 IXIA peer → bag013 (ar-bgp) injecting 15K prefixes

All parameters are configurable — defaults come from constants.py.
"""

import typing as t

from ixia.ixia import types as ixia_types
from taac.test_as_a_config.types import (
    BasicPortConfig,
    BgpConfig,
    DeviceGroupConfig,
    IpAddressesConfig,
    RouteScale,
    RouteScaleSpec,
)


def _build_route_scales_v6(
    prefix_count: int,
    communities: t.Optional[str] = None,
) -> t.List[RouteScaleSpec]:
    """Build RouteScaleSpec for IPv6 route advertisement."""
    if prefix_count <= 0:
        return []
    bgp_communities = [communities] if communities else []
    return [
        RouteScaleSpec(
            v6_route_scale=RouteScale(
                prefix_name="PREFIX_POOL_IPV6",
                starting_prefixes="2620:10d:c0a8::",
                prefix_step="0:0:1::",
                prefix_length=48,
                multiplier=1,
                prefix_count=prefix_count,
                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                bgp_communities=bgp_communities,
            ),
            multiplier=1,
            network_group_index=0,
        )
    ]


def _build_route_scales_v4(
    prefix_count: int,
    communities: t.Optional[str] = None,
) -> t.List[RouteScaleSpec]:
    """Build RouteScaleSpec for IPv4 route advertisement."""
    if prefix_count <= 0:
        return []
    bgp_communities = [communities] if communities else []
    return [
        RouteScaleSpec(
            v4_route_scale=RouteScale(
                prefix_name="PREFIX_POOL_IPV4",
                starting_prefixes="192.168.0.0",
                prefix_step="0.1.0.0",
                prefix_length=24,
                multiplier=1,
                prefix_count=prefix_count,
                ip_address_family=ixia_types.IpAddressFamily.IPV4,
                bgp_communities=bgp_communities,
            ),
            multiplier=1,
            network_group_index=0,
        )
    ]


def create_case1_basic_port_configs(
    device_name: str,
    ixia_interface: str,
    ixia_peer_count: int = 1,
    ixia_as: int = 65300,
    ixia_ipv6_base: str = "2401:db00:e700:11:9",
    ixia_ipv4_base: str = "10.201.28",
    prefix_count: int = 15000,
    communities: t.Optional[str] = None,
) -> t.List[BasicPortConfig]:
    """
    Create IXIA BasicPortConfig for Case 1.

    Case 1 topology (IXIA side):
        IXIA ──(1 BGP session, 15K prefixes)──→ bag012 (BGP++)

    The single IXIA peer injects 15K prefixes into bag012.
    bag012 redistributes these to 140 eBGP sessions towards bag013.

    Args:
        device_name: Hostname of the BGP++ device (bag012)
        ixia_interface: Interface on bag012 connected to IXIA
        ixia_peer_count: Number of IXIA BGP sessions (default: 1)
        ixia_as: IXIA simulated AS number
        ixia_ipv6_base: IPv6 base network for IXIA peering
        ixia_ipv4_base: IPv4 base network for IXIA peering
        prefix_count: Number of prefixes per AF for IXIA to advertise
        communities: BGP community string for routes
    """
    device_groups = []

    # IPv6 device group — IXIA peers towards bag012
    device_groups.append(
        DeviceGroupConfig(
            device_group_name="DEVICE_GROUP_IPV6_IXIA_TO_BGPCPP",
            device_group_index=0,
            multiplier=ixia_peer_count,
            v6_addresses_config=IpAddressesConfig(
                starting_ip=f"{ixia_ipv6_base}::b",
                increment_ip="0:0:0:0::2",
                gateway_starting_ip=f"{ixia_ipv6_base}::a",
                gateway_increment_ip="0:0:0:0::2",
                start_index=0,
            ),
            v6_bgp_config=BgpConfig(
                bgp_peer_name="BGP_PEER_IPV6_IXIA_TO_BGPCPP",
                local_as_4_bytes=ixia_as,
                enable_4_byte_local_as=True,
                enable_graceful_restart=False,
                bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                route_scales=_build_route_scales_v6(prefix_count, communities),
            ),
        ),
    )

    # IPv4 device group — IXIA peers towards bag012
    device_groups.append(
        DeviceGroupConfig(
            device_group_name="DEVICE_GROUP_IPV4_IXIA_TO_BGPCPP",
            device_group_index=1,
            multiplier=ixia_peer_count,
            v4_addresses_config=IpAddressesConfig(
                starting_ip=f"{ixia_ipv4_base}.11",
                increment_ip="0.0.0.2",
                gateway_starting_ip=f"{ixia_ipv4_base}.10",
                gateway_increment_ip="0.0.0.2",
                mask=31,
                start_index=0,
            ),
            v4_bgp_config=BgpConfig(
                bgp_peer_name="BGP_PEER_IPV4_IXIA_TO_BGPCPP",
                local_as_4_bytes=ixia_as,
                enable_4_byte_local_as=True,
                enable_graceful_restart=False,
                bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                route_scales=_build_route_scales_v4(prefix_count, communities),
            ),
        ),
    )

    return [
        BasicPortConfig(
            endpoint=f"{device_name}:{ixia_interface}",
            device_group_configs=device_groups,
        ),
    ]


def create_case2_basic_port_configs(
    bgpcpp_device_name: str,
    bgpcpp_ixia_interface: str,
    arbgp_device_name: str,
    arbgp_ixia_interface: str,
    ixia_peer_count_to_bgpcpp: int = 140,
    ixia_peer_count_to_arbgp: int = 1,
    ixia_as: int = 65300,
    ixia_bgpcpp_ipv6_base: str = "2401:db00:e700:11:9",
    ixia_bgpcpp_ipv4_base: str = "10.201.28",
    ixia_arbgp_ipv6_base: str = "2401:db00:e700:11:10",
    ixia_arbgp_ipv4_base: str = "10.202.28",
    prefix_count: int = 15000,
    communities: t.Optional[str] = None,
) -> t.List[BasicPortConfig]:
    """
    Create IXIA BasicPortConfig for Case 2.

    Case 2 topology (IXIA side):
        IXIA ──(1 session, 15K prefixes)──→ bag013 (ar-bgp)
            bag013 ──(1 iBGP session)──→ bag012 (BGP++)
                bag012 ──(redistributes via eBGP)──→ 140 IXIA peers

    Args:
        bgpcpp_device_name: Hostname of the BGP++ device (bag012)
        bgpcpp_ixia_interface: Interface on bag012 connected to IXIA
        arbgp_device_name: Hostname of the ar-bgp device (bag013)
        arbgp_ixia_interface: Interface on bag013 connected to IXIA
        ixia_peer_count_to_bgpcpp: IXIA sessions towards bag012 (default: 140)
        ixia_peer_count_to_arbgp: IXIA sessions towards bag013 (default: 1)
        ixia_as: IXIA simulated AS number
        ixia_bgpcpp_ipv6_base: IPv6 base for IXIA↔bag012 peering
        ixia_bgpcpp_ipv4_base: IPv4 base for IXIA↔bag012 peering
        ixia_arbgp_ipv6_base: IPv6 base for IXIA↔bag013 peering
        ixia_arbgp_ipv4_base: IPv4 base for IXIA↔bag013 peering
        prefix_count: Number of prefixes per AF for IXIA to inject into ar-bgp
        communities: BGP community string for routes
    """
    configs = []

    # -------------------------------------------------------------------------
    # IXIA → bag012 (BGP++): 140 sessions (receivers — no routes injected)
    # -------------------------------------------------------------------------
    bgpcpp_device_groups = [
        DeviceGroupConfig(
            device_group_name="DEVICE_GROUP_IPV6_IXIA_FROM_BGPCPP",
            device_group_index=0,
            multiplier=ixia_peer_count_to_bgpcpp,
            v6_addresses_config=IpAddressesConfig(
                starting_ip=f"{ixia_bgpcpp_ipv6_base}::b",
                increment_ip="0:0:0:0::2",
                gateway_starting_ip=f"{ixia_bgpcpp_ipv6_base}::a",
                gateway_increment_ip="0:0:0:0::2",
                start_index=0,
            ),
            v6_bgp_config=BgpConfig(
                bgp_peer_name="BGP_PEER_IPV6_IXIA_FROM_BGPCPP",
                local_as_4_bytes=ixia_as,
                enable_4_byte_local_as=True,
                enable_graceful_restart=False,
                bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                route_scales=[],
            ),
        ),
        DeviceGroupConfig(
            device_group_name="DEVICE_GROUP_IPV4_IXIA_FROM_BGPCPP",
            device_group_index=1,
            multiplier=ixia_peer_count_to_bgpcpp,
            v4_addresses_config=IpAddressesConfig(
                starting_ip=f"{ixia_bgpcpp_ipv4_base}.11",
                increment_ip="0.0.0.2",
                gateway_starting_ip=f"{ixia_bgpcpp_ipv4_base}.10",
                gateway_increment_ip="0.0.0.2",
                mask=31,
                start_index=0,
            ),
            v4_bgp_config=BgpConfig(
                bgp_peer_name="BGP_PEER_IPV4_IXIA_FROM_BGPCPP",
                local_as_4_bytes=ixia_as,
                enable_4_byte_local_as=True,
                enable_graceful_restart=False,
                bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                route_scales=[],
            ),
        ),
    ]

    configs.append(
        BasicPortConfig(
            endpoint=f"{bgpcpp_device_name}:{bgpcpp_ixia_interface}",
            device_group_configs=bgpcpp_device_groups,
        )
    )

    # -------------------------------------------------------------------------
    # IXIA → bag013 (ar-bgp): 1 session injecting 15K prefixes
    # -------------------------------------------------------------------------
    arbgp_device_groups = [
        DeviceGroupConfig(
            device_group_name="DEVICE_GROUP_IPV6_IXIA_TO_ARBGP",
            device_group_index=0,
            multiplier=ixia_peer_count_to_arbgp,
            v6_addresses_config=IpAddressesConfig(
                starting_ip=f"{ixia_arbgp_ipv6_base}::b",
                increment_ip="0:0:0:0::2",
                gateway_starting_ip=f"{ixia_arbgp_ipv6_base}::a",
                gateway_increment_ip="0:0:0:0::2",
                start_index=0,
            ),
            v6_bgp_config=BgpConfig(
                bgp_peer_name="BGP_PEER_IPV6_IXIA_TO_ARBGP",
                local_as_4_bytes=ixia_as,
                enable_4_byte_local_as=True,
                enable_graceful_restart=False,
                bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                route_scales=_build_route_scales_v6(prefix_count, communities),
            ),
        ),
        DeviceGroupConfig(
            device_group_name="DEVICE_GROUP_IPV4_IXIA_TO_ARBGP",
            device_group_index=1,
            multiplier=ixia_peer_count_to_arbgp,
            v4_addresses_config=IpAddressesConfig(
                starting_ip=f"{ixia_arbgp_ipv4_base}.11",
                increment_ip="0.0.0.2",
                gateway_starting_ip=f"{ixia_arbgp_ipv4_base}.10",
                gateway_increment_ip="0.0.0.2",
                mask=31,
                start_index=0,
            ),
            v4_bgp_config=BgpConfig(
                bgp_peer_name="BGP_PEER_IPV4_IXIA_TO_ARBGP",
                local_as_4_bytes=ixia_as,
                enable_4_byte_local_as=True,
                enable_graceful_restart=False,
                bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                route_scales=_build_route_scales_v4(prefix_count, communities),
            ),
        ),
    ]

    configs.append(
        BasicPortConfig(
            endpoint=f"{arbgp_device_name}:{arbgp_ixia_interface}",
            device_group_configs=arbgp_device_groups,
        )
    )

    return configs
