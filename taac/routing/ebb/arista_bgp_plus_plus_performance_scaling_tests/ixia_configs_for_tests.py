# pyre-unsafe

from ixia.ixia import types as ixia_types
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import (
    BasicPortConfig,
    BgpConfig,
    DeviceGroupConfig,
    IpAddressesConfig,
    RouteScale,
    RouteScaleSpec,
)


def get_bgp_route_file_path(base_filename: str) -> str:
    """
    Helper function to get the correct BGP route file path based on the profile.

    Args:
        base_filename: Base filename (e.g., "ebgp_ipv6.csv", "ibgp_ipv4_p0.csv")

    Returns:
        Complete file path for the route file based on profile
    """
    return f"performance_scaling_profiles/{base_filename}"


def create_ebb_performance_scale_basic_port_configs(
    device_name: str,
    ixia_interface_mimic_ebgp: str,
    ixia_interface_mimic_ibgp: str,
    ebgp_peer_count_v6: int,
    ebgp_peer_count_v4: int,
    ibgp_peer_count_v6: int,
    ibgp_peer_count_v4: int,
    ebgp_remote_as: int,
    ibgp_remote_as: int,
    ixia_ebgp_ic_parent_network_v6: str,
    ixia_ebgp_ic_parent_network_v4: str,
    ixia_ibgp_ic_parent_network_v6: str,
    ixia_ibgp_ic_parent_network_v4: str,
    same_community: bool = False,
) -> list[BasicPortConfig]:
    """
    Create basic port configurations for EBB scale testing with eBGP, iBGP

    This function generates Ixia port configurations for BGP scale testing scenarios including:
    - eBGP peers (IPv4/IPv6)
    - iBGP peers (IPv4/IPv6)

    Args:
        device_name: Name of the device under test
        ixia_interface_mimic_ebgp: Ixia interface for eBGP simulation
        ixia_interface_mimic_ibgp: Ixia interface for iBGP simulation
        ebgp_peer_count_v6: Total number of eBGP IPv6 peers
        ebgp_peer_count_v4: Total number of eBGP IPv4 peers
        ibgp_peer_count_v6: Number of iBGP IPv6 peers
        ibgp_peer_count_v4: Number of iBGP IPv4 peers
        ebgp_remote_as: eBGP remote AS number
        ibgp_remote_as: iBGP remote AS number
        bgp_mon_remote_as: BGP monitoring remote AS number
        ixia_ebgp_ic_parent_network_v6: IPv6 network prefix for eBGP
        ixia_ebgp_ic_parent_network_v4: IPv4 network prefix for eBGP
        ixia_ibgp_ic_parent_network_v6: IPv6 network prefixes for iBGP DC planes
        ixia_ibgp_ic_parent_network_v4: IPv4 network prefixes for iBGP DC planes
        same_community: Whether to use the same community for all prefixes

    Returns:
        List of BasicPortConfig objects for Ixia configuration
    """
    basic_configs: list[BasicPortConfig] = []
    if ebgp_peer_count_v6 != 0 or ebgp_peer_count_v4 != 0:
        ebgp_dgs: list[DeviceGroupConfig] = []
        # Only create the IPv6 EBGP device group when v6 peer count > 0.
        # IXIA's IpAddress Increment SDK call divides by the device-group
        # multiplier and crashes ("Attempted to divide by zero") if a
        # device group is created with multiplier=0.
        if ebgp_peer_count_v6 != 0:
            ebgp_dgs.append(
                DeviceGroupConfig(
                    device_group_name="DEVICE_GROUP_IPV6_EBGP",
                    device_group_index=len(ebgp_dgs),
                    multiplier=ebgp_peer_count_v6,
                    v6_addresses_config=taac_types.IpAddressesConfig(
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
                        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                        import_bgp_routes_params_list=[
                            ixia_types.ImportBgpRoutesParams(
                                prefix_pool_name="PREFIX_POOL_IPV6_EBGP",
                                multiplier=50000,
                                bgp_route_import_file_path=get_bgp_route_file_path(
                                    "ebgp_ipv6_50k_prefixes.csv"
                                ),
                                import_file_type=ixia_types.BgpRouteImportFileType.CSV,
                                network_group_index=0,
                                bgp_attribute_configs=[
                                    ixia_types.BgpAttributeConfig(
                                        attribute=ixia_types.BgpAttribute.COMMUNITIES,
                                        file_path=get_bgp_route_file_path(
                                            "ebgp_ipv6_same_communities_50k.csv"
                                            if same_community
                                            else "ebgp_ipv6_communities_50k.csv"
                                        ),
                                        distribution_type=ixia_types.DistribitionType.ROUND_ROBIN,
                                    )
                                ],
                                bgp_next_hop_modification_type=ixia_types.BgpNextHopModificationType.PRESERVE_FROM_FILE,
                                start_index=0,
                                end_index=ebgp_peer_count_v6,
                            )
                        ],
                    ),
                ),
            )
        # Only create the IPv4 EBGP device group when v4 peer count > 0.
        if ebgp_peer_count_v4 != 0:
            ebgp_dgs.append(
                DeviceGroupConfig(
                    device_group_name="DEVICE_GROUP_IPV4_EBGP",
                    device_group_index=len(ebgp_dgs),
                    multiplier=ebgp_peer_count_v4,
                    v4_addresses_config=taac_types.IpAddressesConfig(
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
                        bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                        import_bgp_routes_params_list=[
                            ixia_types.ImportBgpRoutesParams(
                                prefix_pool_name="PREFIX_POOL_IPV4_EBGP",
                                multiplier=50000,
                                bgp_route_import_file_path=get_bgp_route_file_path(
                                    "ebgp_ipv4_50k_prefixes.csv"
                                ),
                                import_file_type=ixia_types.BgpRouteImportFileType.CSV,
                                network_group_index=0,
                                bgp_attribute_configs=[
                                    ixia_types.BgpAttributeConfig(
                                        attribute=ixia_types.BgpAttribute.COMMUNITIES,
                                        file_path=get_bgp_route_file_path(
                                            "ebgp_ipv4_same_communities_50k.csv"
                                            if same_community
                                            else "ebgp_ipv4_communities_50k.csv"
                                        ),
                                        distribution_type=ixia_types.DistribitionType.ROUND_ROBIN,
                                    )
                                ],
                                bgp_next_hop_modification_type=ixia_types.BgpNextHopModificationType.PRESERVE_FROM_FILE,
                            )
                        ],
                    ),
                ),
            )
        if ebgp_dgs:
            basic_configs.append(
                BasicPortConfig(
                    endpoint=f"{device_name}:{ixia_interface_mimic_ebgp}",
                    device_group_configs=ebgp_dgs,
                ),
            )

    if ibgp_peer_count_v6 != 0 or ibgp_peer_count_v4 != 0:
        ibgp_dgs: list[DeviceGroupConfig] = []
        # Only create the IPv6 IBGP device group when v6 peer count > 0
        # (avoids the IXIA divide-by-zero on multiplier=0).
        if ibgp_peer_count_v6 != 0:
            ibgp_dgs.append(
                DeviceGroupConfig(
                    device_group_name="DEVICE_GROUP_IPV6_IBGP",
                    device_group_index=len(ibgp_dgs),
                    multiplier=ibgp_peer_count_v6,
                    v6_addresses_config=IpAddressesConfig(
                        starting_ip=f"{ixia_ibgp_ic_parent_network_v6}::11",
                        increment_ip="0:0:0:0::2",
                        gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v6}::10",
                        gateway_increment_ip="0:0:0:0::2",
                        start_index=0,
                    ),
                    v6_bgp_config=BgpConfig(
                        bgp_peer_name="BGP_PEER_IPV6_IBGP",
                        local_as_4_bytes=ibgp_remote_as,
                        enable_4_byte_local_as=True,
                        enable_graceful_restart=False,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                    ),
                ),
            )
        # Only create the IPv4 IBGP device group when v4 peer count > 0.
        if ibgp_peer_count_v4 != 0:
            ibgp_dgs.append(
                DeviceGroupConfig(
                    device_group_name="DEVICE_GROUP_IPV4_IBGP",
                    device_group_index=len(ibgp_dgs),
                    multiplier=ibgp_peer_count_v4,
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
                        local_as_4_bytes=ibgp_remote_as,
                        enable_4_byte_local_as=True,
                        enable_graceful_restart=False,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                        bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                    ),
                ),
            )
        if ibgp_dgs:
            basic_configs.append(
                BasicPortConfig(
                    endpoint=f"{device_name}:{ixia_interface_mimic_ibgp}",
                    device_group_configs=ibgp_dgs,
                )
            )
    return basic_configs


def create_ebb_transient_memory_route_peer_scale_basic_port_configs(
    device_name: str,
    ixia_interface_mimic_ebgp: str,
    ixia_interface_mimic_ibgp: str,
    ebgp_peer_count_v6: int,
    ebgp_peer_count_v4: int,
    ibgp_peer_count_v6: int,
    ibgp_peer_count_v4: int,
    ebgp_remote_as: int,
    ibgp_remote_as: int,
    initial_prefix_count: int,
    ixia_ebgp_ic_parent_network_v6: str,
    ixia_ebgp_ic_parent_network_v4: str,
    ixia_ibgp_ic_parent_network_v6: str,
    ixia_ibgp_ic_parent_network_v4: str,
) -> list[BasicPortConfig]:
    """
    Create basic port configurations for EBB scale testing with eBGP, iBGP

    This function generates Ixia port configurations for BGP scale testing scenarios including:
    - eBGP peers (IPv4/IPv6)
    - iBGP peers (IPv4/IPv6)

    Args:
        device_name: Name of the device under test
        ixia_interface_mimic_ebgp: Ixia interface for eBGP simulation
        ixia_interface_mimic_ibgp: Ixia interface for iBGP simulation
        ebgp_peer_count_v6: Total number of eBGP IPv6 peers
        ebgp_peer_count_v4: Total number of eBGP IPv4 peers
        ibgp_peer_count_v6: Number of iBGP IPv6 peers
        ibgp_peer_count_v4: Number of iBGP IPv4 peers
        ebgp_remote_as: eBGP remote AS number
        ibgp_remote_as: iBGP remote AS number
        bgp_mon_remote_as: BGP monitoring remote AS number
        ixia_ebgp_ic_parent_network_v6: IPv6 network prefix for eBGP
        ixia_ebgp_ic_parent_network_v4: IPv4 network prefix for eBGP
        ixia_ibgp_ic_parent_network_v6: IPv6 network prefixes for iBGP DC planes
        ixia_ibgp_ic_parent_network_v4: IPv4 network prefixes for iBGP DC planes

    Returns:
        List of BasicPortConfig objects for Ixia configuration
    """
    basic_configs: list[BasicPortConfig] = [
        BasicPortConfig(
            endpoint=f"{device_name}:{ixia_interface_mimic_ebgp}",
            device_group_configs=[
                DeviceGroupConfig(
                    device_group_name="DEVICE_GROUP_IPV6_EBGP",
                    device_group_index=0,
                    multiplier=ebgp_peer_count_v6,
                    v6_addresses_config=taac_types.IpAddressesConfig(
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
                        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                        route_scales=[
                            RouteScaleSpec(
                                v6_route_scale=RouteScale(
                                    prefix_name="PREFIX_POOL_IPV6_EBGP",
                                    starting_prefixes="2001:db8:1000::",
                                    prefix_step="0:0:0:0:0:0:0:0",
                                    prefix_length=64,
                                    multiplier=1,
                                    prefix_count=initial_prefix_count,
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
                    multiplier=ebgp_peer_count_v4,
                    v4_addresses_config=taac_types.IpAddressesConfig(
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
                        bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                        route_scales=[
                            RouteScaleSpec(
                                v4_route_scale=RouteScale(
                                    prefix_name="PREFIX_POOL_IPV4_EBGP",
                                    starting_prefixes="10.100.0.0",
                                    prefix_step="0.0.0.0",
                                    prefix_length=24,
                                    multiplier=1,
                                    prefix_count=initial_prefix_count,
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
        BasicPortConfig(
            endpoint=f"{device_name}:{ixia_interface_mimic_ibgp}",
            device_group_configs=[
                DeviceGroupConfig(
                    device_group_name="DEVICE_GROUP_IPV6_IBGP",
                    device_group_index=0,
                    multiplier=ibgp_peer_count_v6,
                    v6_addresses_config=IpAddressesConfig(
                        starting_ip=f"{ixia_ibgp_ic_parent_network_v6}::11",
                        increment_ip="0:0:0:0::2",
                        gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v6}::10",
                        gateway_increment_ip="0:0:0:0::2",
                        start_index=0,
                    ),
                    v6_bgp_config=BgpConfig(
                        bgp_peer_name="BGP_PEER_IPV6_IBGP",
                        local_as_4_bytes=ibgp_remote_as,
                        enable_4_byte_local_as=True,
                        enable_graceful_restart=False,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                    ),
                ),
                DeviceGroupConfig(
                    device_group_name="DEVICE_GROUP_IPV4_IBGP",
                    device_group_index=1,
                    multiplier=ibgp_peer_count_v4,
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
                        local_as_4_bytes=ibgp_remote_as,
                        enable_4_byte_local_as=True,
                        enable_graceful_restart=False,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                        bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                    ),
                ),
            ],
        ),
    ]
    return basic_configs


def create_ebb_route_churn_test_basic_port_configs(
    device_name: str,
    ixia_interface_mimic_ebgp: str,
    ixia_interface_mimic_ibgp: str,
    ebgp_peer_count_v6: int,
    ibgp_peer_count_v6: int,
    ebgp_remote_as: int,
    ibgp_remote_as: int,
    initial_prefix_count: int,
    churn_count: int,
    ixia_ebgp_ic_parent_network_v6: str,
    ixia_ibgp_ic_parent_network_v6: str,
) -> list[BasicPortConfig]:
    """
    Create basic port configurations for EBB scale testing with eBGP, iBGP

    This function generates Ixia port configurations for BGP scale testing scenarios including:
    - eBGP peers (IPv6)
    - iBGP peers (IPv6)

    Args:
        device_name: Name of the device under test
        ixia_interface_mimic_ebgp: Ixia interface for eBGP simulation
        ixia_interface_mimic_ibgp: Ixia interface for iBGP simulation
        ebgp_peer_count_v6: Total number of eBGP IPv6 peers
        ibgp_peer_count_v6: Number of iBGP IPv6 peers
        ebgp_remote_as: eBGP remote AS number
        ibgp_remote_as: iBGP remote AS number
        bgp_mon_remote_as: BGP monitoring remote AS number
        ixia_ebgp_ic_parent_network_v6: IPv6 network prefix for eBGP
        ixia_ibgp_ic_parent_network_v6: IPv6 network prefixes for iBGP DC planes

    Returns:
        List of BasicPortConfig objects for Ixia configuration
    """
    basic_configs: list[BasicPortConfig] = [
        BasicPortConfig(
            endpoint=f"{device_name}:{ixia_interface_mimic_ebgp}",
            device_group_configs=[
                DeviceGroupConfig(
                    device_group_name="DEVICE_GROUP_IPV6_EBGP",
                    device_group_index=0,
                    multiplier=ebgp_peer_count_v6,
                    v6_addresses_config=taac_types.IpAddressesConfig(
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
                        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                    ),
                ),
            ],
        ),
        BasicPortConfig(
            endpoint=f"{device_name}:{ixia_interface_mimic_ibgp}",
            device_group_configs=[
                DeviceGroupConfig(
                    device_group_name="DEVICE_GROUP_IPV6_IBGP_PEER_1",
                    device_group_index=0,
                    multiplier=1,
                    v6_addresses_config=IpAddressesConfig(
                        starting_ip=f"{ixia_ibgp_ic_parent_network_v6}::11",
                        increment_ip="0:0:0:0::2",
                        gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v6}::10",
                        gateway_increment_ip="0:0:0:0::2",
                        start_index=0,
                    ),
                    v6_bgp_config=BgpConfig(
                        bgp_peer_name="BGP_PEER_IPV6_IBGP_PEER_1",
                        local_as_4_bytes=ibgp_remote_as,
                        enable_4_byte_local_as=True,
                        enable_graceful_restart=False,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                        route_scales=[
                            RouteScaleSpec(
                                v6_route_scale=RouteScale(
                                    prefix_name="PREFIX_POOL_IPV6_IBGP_PEER_1_FIRST_100",
                                    starting_prefixes="5001:db8:1000::",
                                    prefix_step="0:0:0:0:0:0:0:0",
                                    prefix_length=64,
                                    multiplier=1,
                                    prefix_count=churn_count,
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    bgp_communities=["65529:39744"],
                                ),
                                multiplier=1,
                                network_group_index=0,
                            ),
                            RouteScaleSpec(
                                v6_route_scale=RouteScale(
                                    prefix_name="PREFIX_POOL_IPV6_IBGP_PEER_1_AFTER_100",
                                    starting_prefixes="5001:db8:1000:64::",
                                    prefix_step="0:0:0:0:0:0:0:0",
                                    prefix_length=64,
                                    multiplier=1,
                                    prefix_count=initial_prefix_count - churn_count,
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    bgp_communities=["65529:39744"],
                                ),
                                multiplier=1,
                                network_group_index=1,
                            ),
                        ],
                    ),
                ),
                DeviceGroupConfig(
                    device_group_name="DEVICE_GROUP_IPV6_IBGP_PEER_2_99",
                    device_group_index=1,
                    multiplier=ibgp_peer_count_v6 - 1,
                    v6_addresses_config=IpAddressesConfig(
                        starting_ip=f"{ixia_ibgp_ic_parent_network_v6}::13",
                        increment_ip="0:0:0:0::2",
                        gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v6}::12",
                        gateway_increment_ip="0:0:0:0::2",
                        start_index=0,
                    ),
                    v6_bgp_config=BgpConfig(
                        bgp_peer_name="BGP_PEER_IPV6_IBGP_PEER_2_99",
                        local_as_4_bytes=ibgp_remote_as,
                        enable_4_byte_local_as=True,
                        enable_graceful_restart=False,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                        route_scales=[
                            RouteScaleSpec(
                                v6_route_scale=RouteScale(
                                    prefix_name="PREFIX_POOL_IPV6_IBGP_PEER_2_99",
                                    starting_prefixes="5001:db8:1000::",
                                    prefix_step="0:0:0:0:0:0:0:0",
                                    prefix_length=64,
                                    multiplier=1,
                                    prefix_count=initial_prefix_count,
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    bgp_communities=["65529:39744"],
                                ),
                                multiplier=1,
                                network_group_index=0,
                            ),
                        ],
                    ),
                ),
            ],
        ),
    ]
    return basic_configs


def create_ebb_separable_policy_port_configs(
    device_name: str,
    ixia_interface_mimic_ebgp: str,
    ebgp_peer_count_v6: int,
    ebgp_peer_count_v4: int,
    ebgp_remote_as: int,
    prefix_count: int,
    ixia_ebgp_ic_parent_network_v6: str,
    ixia_ebgp_ic_parent_network_v4: str,
) -> list[BasicPortConfig]:
    """
    Create basic port configurations for EBB separable policy testing with eBGP only.

    This function generates Ixia port configurations for BGP separable policy test scenarios
    with only eBGP peers (IPv4/IPv6), no iBGP peers.

    Args:
        device_name: Name of the device under test
        ixia_interface_mimic_ebgp: Ixia interface for eBGP simulation
        ebgp_peer_count_v6: Total number of eBGP IPv6 peers
        ebgp_peer_count_v4: Total number of eBGP IPv4 peers
        ebgp_remote_as: eBGP remote AS number
        prefix_count: Number of prefixes to advertise per peer
        ixia_ebgp_ic_parent_network_v6: IPv6 network prefix for eBGP
        ixia_ebgp_ic_parent_network_v4: IPv4 network prefix for eBGP

    Returns:
        List of BasicPortConfig objects for Ixia configuration
    """
    basic_configs: list[BasicPortConfig] = [
        BasicPortConfig(
            endpoint=f"{device_name}:{ixia_interface_mimic_ebgp}",
            device_group_configs=[
                DeviceGroupConfig(
                    device_group_name="DEVICE_GROUP_IPV6_EBGP",
                    device_group_index=0,
                    multiplier=ebgp_peer_count_v6,
                    v6_addresses_config=taac_types.IpAddressesConfig(
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
                        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                        route_scales=[
                            RouteScaleSpec(
                                v6_route_scale=RouteScale(
                                    prefix_name="PREFIX_POOL_IPV6_EBGP",
                                    starting_prefixes="2001:db8:1000::",
                                    prefix_step="0:0:0:0:0:0:0:0",
                                    prefix_length=64,
                                    multiplier=1,
                                    prefix_count=prefix_count,
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    bgp_communities=["65529:39744"],
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
                    multiplier=ebgp_peer_count_v4,
                    v4_addresses_config=taac_types.IpAddressesConfig(
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
                        bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                        route_scales=[
                            RouteScaleSpec(
                                v4_route_scale=RouteScale(
                                    prefix_name="PREFIX_POOL_IPV4_EBGP",
                                    starting_prefixes="10.100.0.0",
                                    prefix_step="0.0.0.0",
                                    prefix_length=24,
                                    multiplier=1,
                                    prefix_count=prefix_count,
                                    ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                    bgp_communities=["65529:39744"],
                                ),
                                multiplier=1,
                                network_group_index=0,
                            )
                        ],
                    ),
                ),
            ],
        ),
    ]
    return basic_configs


def create_ebb_bounded_ecmp_sets_port_configs(
    device_name: str,
    ixia_interface_mimic_ebgp: str,
    ixia_interface_mimic_ibgp: str,
    ebgp_peer_count_v6: int,
    ebgp_peer_count_v4: int,
    ibgp_peer_count_v6: int,
    ibgp_peer_count_v4: int,
    ebgp_remote_as: int,
    ibgp_remote_as: int,
    prefix_count: int,
    ixia_ebgp_ic_parent_network_v6: str,
    ixia_ebgp_ic_parent_network_v4: str,
    ixia_ibgp_ic_parent_network_v6: str,
    ixia_ibgp_ic_parent_network_v4: str,
) -> list[BasicPortConfig]:
    """
    Create basic port configurations for EBB scale testing with eBGP, iBGP

    This function generates Ixia port configurations for BGP scale testing scenarios including:
    - eBGP peers (IPv4/IPv6)
    - iBGP peers (IPv4/IPv6)

    Args:
        device_name: Name of the device under test
        ixia_interface_mimic_ebgp: Ixia interface for eBGP simulation
        ixia_interface_mimic_ibgp: Ixia interface for iBGP simulation
        ebgp_peer_count_v6: Total number of eBGP IPv6 peers
        ebgp_peer_count_v4: Total number of eBGP IPv4 peers
        ibgp_peer_count_v6: Number of iBGP IPv6 peers
        ibgp_peer_count_v4: Number of iBGP IPv4 peers
        ebgp_remote_as: eBGP remote AS number
        ibgp_remote_as: iBGP remote AS number
        bgp_mon_remote_as: BGP monitoring remote AS number
        ixia_ebgp_ic_parent_network_v6: IPv6 network prefix for eBGP
        ixia_ebgp_ic_parent_network_v4: IPv4 network prefix for eBGP
        ixia_ibgp_ic_parent_network_v6: IPv6 network prefixes for iBGP DC planes
        ixia_ibgp_ic_parent_network_v4: IPv4 network prefixes for iBGP DC planes

    Returns:
        List of BasicPortConfig objects for Ixia configuration
    """
    basic_configs: list[BasicPortConfig] = [
        BasicPortConfig(
            endpoint=f"{device_name}:{ixia_interface_mimic_ebgp}",
            device_group_configs=[
                DeviceGroupConfig(
                    device_group_name="DEVICE_GROUP_IPV6_EBGP_SET1",
                    device_group_index=0,
                    multiplier=42,
                    v6_addresses_config=taac_types.IpAddressesConfig(
                        starting_ip=f"{ixia_ebgp_ic_parent_network_v6}::11",
                        increment_ip="0:0:0:0::2",
                        gateway_starting_ip=f"{ixia_ebgp_ic_parent_network_v6}::10",
                        gateway_increment_ip="0:0:0:0::2",
                        start_index=0,
                    ),
                    v6_bgp_config=BgpConfig(
                        bgp_peer_name="BGP_PEER_IPV6_EBGP_SET1",
                        local_as_4_bytes=ebgp_remote_as,
                        enable_4_byte_local_as=True,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                        route_scales=[
                            RouteScaleSpec(
                                v6_route_scale=RouteScale(
                                    prefix_name="PREFIX_POOL_IPV6_EBGP_SET1",
                                    starting_prefixes="2001:db8:1000::",
                                    prefix_step="0:0:0:0:0:0:0:0",
                                    prefix_length=64,
                                    multiplier=1,
                                    prefix_count=prefix_count,
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    bgp_communities=["65529:39744"],
                                ),
                                multiplier=1,
                                network_group_index=0,
                            )
                        ],
                    ),
                ),
                DeviceGroupConfig(
                    device_group_name="DEVICE_GROUP_IPV6_EBGP_SET2",
                    device_group_index=1,
                    multiplier=42,
                    v6_addresses_config=taac_types.IpAddressesConfig(
                        starting_ip=f"{ixia_ebgp_ic_parent_network_v6}::65",
                        increment_ip="0:0:0:0::2",
                        gateway_starting_ip=f"{ixia_ebgp_ic_parent_network_v6}::64",
                        gateway_increment_ip="0:0:0:0::2",
                        start_index=0,
                    ),
                    v6_bgp_config=BgpConfig(
                        bgp_peer_name="BGP_PEER_IPV6_EBGP_SET2",
                        local_as_4_bytes=ebgp_remote_as,
                        enable_4_byte_local_as=True,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                        route_scales=[
                            RouteScaleSpec(
                                v6_route_scale=RouteScale(
                                    prefix_name="PREFIX_POOL_IPV6_EBGP_SET2",
                                    starting_prefixes="2001:db8:1000::",
                                    prefix_step="0:0:0:0:0:0:0:0",
                                    prefix_length=64,
                                    multiplier=1,
                                    prefix_count=prefix_count,
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    bgp_communities=["65529:39744"],
                                ),
                                multiplier=1,
                                network_group_index=0,
                            )
                        ],
                    ),
                ),
                DeviceGroupConfig(
                    device_group_name="DEVICE_GROUP_IPV6_EBGP_SET3",
                    device_group_index=2,
                    multiplier=44,
                    v6_addresses_config=taac_types.IpAddressesConfig(
                        starting_ip=f"{ixia_ebgp_ic_parent_network_v6}::b9",
                        increment_ip="0:0:0:0::2",
                        gateway_starting_ip=f"{ixia_ebgp_ic_parent_network_v6}::b8",
                        gateway_increment_ip="0:0:0:0::2",
                        start_index=0,
                    ),
                    v6_bgp_config=BgpConfig(
                        bgp_peer_name="BGP_PEER_IPV6_EBGP_SET3",
                        local_as_4_bytes=ebgp_remote_as,
                        enable_4_byte_local_as=True,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                        route_scales=[
                            RouteScaleSpec(
                                v6_route_scale=RouteScale(
                                    prefix_name="PREFIX_POOL_IPV6_EBGP_SET3",
                                    starting_prefixes="2001:db8:1000::",
                                    prefix_step="0:0:0:0:0:0:0:0",
                                    prefix_length=64,
                                    multiplier=1,
                                    prefix_count=prefix_count,
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    bgp_communities=["65529:39744"],
                                ),
                                multiplier=1,
                                network_group_index=0,
                            )
                        ],
                    ),
                ),
                DeviceGroupConfig(
                    device_group_name="DEVICE_GROUP_IPV4_EBGP_SET1",
                    device_group_index=3,
                    multiplier=42,
                    v4_addresses_config=taac_types.IpAddressesConfig(
                        starting_ip=f"{ixia_ebgp_ic_parent_network_v4}.11",
                        increment_ip="0.0.0.2",
                        gateway_starting_ip=f"{ixia_ebgp_ic_parent_network_v4}.10",
                        gateway_increment_ip="0.0.0.2",
                        mask=31,
                        start_index=0,
                    ),
                    v4_bgp_config=BgpConfig(
                        bgp_peer_name="BGP_PEER_IPV4_EBGP_SET1",
                        local_as_4_bytes=ebgp_remote_as,
                        enable_4_byte_local_as=True,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                        route_scales=[
                            RouteScaleSpec(
                                v4_route_scale=RouteScale(
                                    prefix_name="PREFIX_POOL_IPV4_EBGP_SET1",
                                    starting_prefixes="10.100.0.0",
                                    prefix_step="0.0.0.0",
                                    prefix_length=24,
                                    multiplier=1,
                                    prefix_count=prefix_count,
                                    ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                    bgp_communities=["65529:39744"],
                                ),
                                multiplier=1,
                                network_group_index=0,
                            )
                        ],
                    ),
                ),
                DeviceGroupConfig(
                    device_group_name="DEVICE_GROUP_IPV4_EBGP_SET2",
                    device_group_index=4,
                    multiplier=42,
                    v4_addresses_config=taac_types.IpAddressesConfig(
                        starting_ip=f"{ixia_ebgp_ic_parent_network_v4}.95",
                        increment_ip="0.0.0.2",
                        gateway_starting_ip=f"{ixia_ebgp_ic_parent_network_v4}.94",
                        gateway_increment_ip="0.0.0.2",
                        mask=31,
                        start_index=0,
                    ),
                    v4_bgp_config=BgpConfig(
                        bgp_peer_name="BGP_PEER_IPV4_EBGP_SET2",
                        local_as_4_bytes=ebgp_remote_as,
                        enable_4_byte_local_as=True,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                        route_scales=[
                            RouteScaleSpec(
                                v4_route_scale=RouteScale(
                                    prefix_name="PREFIX_POOL_IPV4_EBGP_SET2",
                                    starting_prefixes="10.100.0.0",
                                    prefix_step="0.0.0.0",
                                    prefix_length=24,
                                    multiplier=1,
                                    prefix_count=prefix_count,
                                    ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                    bgp_communities=["65529:39744"],
                                ),
                                multiplier=1,
                                network_group_index=0,
                            )
                        ],
                    ),
                ),
                DeviceGroupConfig(
                    device_group_name="DEVICE_GROUP_IPV4_EBGP_SET3",
                    device_group_index=5,
                    multiplier=44,
                    v4_addresses_config=taac_types.IpAddressesConfig(
                        starting_ip=f"{ixia_ebgp_ic_parent_network_v4}.179",
                        increment_ip="0.0.0.2",
                        gateway_starting_ip=f"{ixia_ebgp_ic_parent_network_v4}.178",
                        gateway_increment_ip="0.0.0.2",
                        mask=31,
                        start_index=0,
                    ),
                    v4_bgp_config=BgpConfig(
                        bgp_peer_name="BGP_PEER_IPV4_EBGP_SET3",
                        local_as_4_bytes=ebgp_remote_as,
                        enable_4_byte_local_as=True,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                        route_scales=[
                            RouteScaleSpec(
                                v4_route_scale=RouteScale(
                                    prefix_name="PREFIX_POOL_IPV4_EBGP_SET3",
                                    starting_prefixes="10.100.0.0",
                                    prefix_step="0.0.0.0",
                                    prefix_length=24,
                                    multiplier=1,
                                    prefix_count=prefix_count,
                                    ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                    bgp_communities=["65529:39744"],
                                ),
                                multiplier=1,
                                network_group_index=0,
                            )
                        ],
                    ),
                ),
            ],
        ),
        BasicPortConfig(
            endpoint=f"{device_name}:{ixia_interface_mimic_ibgp}",
            device_group_configs=[
                DeviceGroupConfig(
                    device_group_name="DEVICE_GROUP_IPV6_IBGP",
                    device_group_index=0,
                    multiplier=ibgp_peer_count_v6,
                    v6_addresses_config=IpAddressesConfig(
                        starting_ip=f"{ixia_ibgp_ic_parent_network_v6}::11",
                        increment_ip="0:0:0:0::2",
                        gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v6}::10",
                        gateway_increment_ip="0:0:0:0::2",
                        start_index=0,
                    ),
                    v6_bgp_config=BgpConfig(
                        bgp_peer_name="BGP_PEER_IPV6_IBGP",
                        local_as_4_bytes=ibgp_remote_as,
                        enable_4_byte_local_as=True,
                        enable_graceful_restart=False,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                    ),
                ),
                DeviceGroupConfig(
                    device_group_name="DEVICE_GROUP_IPV4_IBGP",
                    device_group_index=1,
                    multiplier=ibgp_peer_count_v4,
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
                        local_as_4_bytes=ibgp_remote_as,
                        enable_4_byte_local_as=True,
                        enable_graceful_restart=False,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                        bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                    ),
                ),
            ],
        ),
    ]
    return basic_configs
