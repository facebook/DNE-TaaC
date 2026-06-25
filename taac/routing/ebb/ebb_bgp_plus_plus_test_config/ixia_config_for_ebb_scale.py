# pyre-unsafe

from collections import defaultdict

from ixia.ixia import types as ixia_types
from taac.constants import BgpPlusPlusProfile
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import (
    BasicPortConfig,
    BgpConfig,
    DeviceGroupConfig,
    IpAddressesConfig,
)


def _create_ibgp_plane_device_groups(
    plane_num: int,
    ibgp_peer_scale_per_plane: int,
    ibgp_peer_to_drain_per_plane: int,
    ibgp_remote_as: int,
    ixia_ibgp_ic_parent_network_v6_dc: str,
    ixia_ibgp_ic_parent_network_v6_mp: str,
    ixia_ibgp_ic_parent_network_v4_dc: str,
    ixia_ibgp_ic_parent_network_v4_mp: str,
    profile: BgpPlusPlusProfile,
    multiplier: int,
    device_group_index_offset: int = 0,
    drain: bool = False,
) -> list[DeviceGroupConfig]:
    """
    Create device group configurations for a single iBGP plane.

    This helper function generates all the device groups needed for one plane:
    - IPv6 DC (Remote EB) + Drain
    - IPv6 MP (Remote MP)
    - IPv4 DC (Remote EB) + Drain
    - IPv4 MP (Remote MP)

    Args:
        plane_num: Plane number (1, 2, 3, or 4)
        ibgp_peer_scale_per_plane: Number of iBGP peers per plane
        ibgp_peer_to_drain_per_plane: Number of iBGP peers to drain per plane
        ibgp_remote_as: iBGP remote AS number
        ixia_ibgp_ic_parent_network_v6_dc: IPv6 network prefix for DC plane
        ixia_ibgp_ic_parent_network_v6_mp: IPv6 network prefix for MP plane
        ixia_ibgp_ic_parent_network_v4_dc: IPv4 network prefix for DC plane
        ixia_ibgp_ic_parent_network_v4_mp: IPv4 network prefix for MP plane
        profile: BGP++ profile for route file paths
        multiplier: Route multiplier
        device_group_index_offset: Starting index for device groups (default: 0)

    Returns:
        List of DeviceGroupConfig for this plane
    """
    # Map plane number to route file suffix (p0, p1, p2, p3)
    route_file_suffix = f"p{plane_num - 1}"

    device_groups = []
    idx = device_group_index_offset

    # IPv6 DC (Remote EB)
    ibgp_v6_dc_multiplier = (
        ibgp_peer_scale_per_plane - ibgp_peer_to_drain_per_plane
        if drain
        else ibgp_peer_scale_per_plane
    )
    ibgp_v6_dc_route_end_index = ibgp_v6_dc_multiplier
    device_groups.append(
        DeviceGroupConfig(
            device_group_name=f"DEVICE_GROUP_IPV6_IBGP_PLANE_{plane_num}_REMOTE_EB",
            device_group_index=idx,
            multiplier=ibgp_v6_dc_multiplier,
            v6_addresses_config=IpAddressesConfig(
                starting_ip=f"{ixia_ibgp_ic_parent_network_v6_dc}::11",
                increment_ip="0:0:0:0::2",
                gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v6_dc}::10",
                gateway_increment_ip="0:0:0:0::2",
                start_index=0,
            ),
            v6_bgp_config=BgpConfig(
                bgp_peer_name=f"BGP_PEER_IPV6_IBGP_PLANE_{plane_num}_REMOTE_EB",
                local_as_4_bytes=ibgp_remote_as,
                enable_4_byte_local_as=True,
                enable_graceful_restart=False,
                bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                import_bgp_routes_params_list=[
                    ixia_types.ImportBgpRoutesParams(
                        multiplier=multiplier,
                        bgp_route_import_file_path=get_bgp_route_file_path(
                            profile, f"ibgp_ipv6_{route_file_suffix}.csv"
                        ),
                        import_file_type=ixia_types.BgpRouteImportFileType.CSV,
                        network_group_index=0,
                        bgp_attribute_configs=[
                            ixia_types.BgpAttributeConfig(
                                attribute=ixia_types.BgpAttribute.COMMUNITIES,
                                file_path=get_bgp_route_file_path(
                                    profile, "ibgp_ipv6_communites.csv"
                                ),
                                distribution_type=ixia_types.DistribitionType.ROUND_ROBIN,
                            )
                        ],
                        bgp_next_hop_modification_type=ixia_types.BgpNextHopModificationType.PRESERVE_FROM_FILE,
                        prefix_pool_name=f"PREFIX_POOL_IBGP_IPV6_PLANE_{plane_num}_REMOTE_EB",
                        start_index=0,
                        end_index=ibgp_v6_dc_route_end_index,
                    )
                ],
            ),
        )
    )
    idx += 1

    # IPv6 DC (Remote EB) DRAIN (only when drain=True)
    if drain:
        device_groups.append(
            DeviceGroupConfig(
                device_group_name=f"DEVICE_GROUP_IPV6_IBGP_PLANE_{plane_num}_REMOTE_EB_DRAIN",
                device_group_index=idx,
                multiplier=ibgp_peer_to_drain_per_plane,
                v6_addresses_config=IpAddressesConfig(
                    starting_ip=f"{ixia_ibgp_ic_parent_network_v6_dc}::11",
                    increment_ip="0:0:0:0::2",
                    gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v6_dc}::10",
                    gateway_increment_ip="0:0:0:0::2",
                    start_index=ibgp_peer_scale_per_plane
                    - ibgp_peer_to_drain_per_plane,
                ),
                v6_bgp_config=BgpConfig(
                    bgp_peer_name=f"BGP_PEER_IPV6_IBGP_PLANE_{plane_num}_REMOTE_EB_DRAIN",
                    local_as_4_bytes=ibgp_remote_as,
                    enable_4_byte_local_as=True,
                    enable_graceful_restart=False,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                    bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                    import_bgp_routes_params_list=[
                        ixia_types.ImportBgpRoutesParams(
                            multiplier=multiplier,
                            bgp_route_import_file_path=get_bgp_route_file_path(
                                profile, f"ibgp_ipv6_{route_file_suffix}.csv"
                            ),
                            import_file_type=ixia_types.BgpRouteImportFileType.CSV,
                            network_group_index=0,
                            bgp_attribute_configs=[
                                ixia_types.BgpAttributeConfig(
                                    attribute=ixia_types.BgpAttribute.COMMUNITIES,
                                    file_path=get_bgp_route_file_path(
                                        profile, "ibgp_ipv6_communites.csv"
                                    ),
                                    distribution_type=ixia_types.DistribitionType.ROUND_ROBIN,
                                )
                            ],
                            bgp_next_hop_modification_type=ixia_types.BgpNextHopModificationType.PRESERVE_FROM_FILE,
                            prefix_pool_name=f"PREFIX_POOL_IBGP_IPV6_PLANE_{plane_num}_REMOTE_EB_DRAIN",
                            start_index=ibgp_peer_scale_per_plane
                            - ibgp_peer_to_drain_per_plane,
                            end_index=ibgp_peer_scale_per_plane,
                        )
                    ],
                ),
            )
        )
        idx += 1

    # IPv6 MP (Remote MP) - no drain variant
    device_groups.append(
        DeviceGroupConfig(
            device_group_index=idx,
            device_group_name=f"DEVICE_GROUP_IPV6_IBGP_PLANE_{plane_num}_REMOTE_MP",
            multiplier=ibgp_peer_scale_per_plane,
            v6_addresses_config=IpAddressesConfig(
                starting_ip=f"{ixia_ibgp_ic_parent_network_v6_mp}::11",
                increment_ip="0:0:0:0::2",
                gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v6_mp}::10",
                gateway_increment_ip="0:0:0:0::2",
            ),
            v6_bgp_config=BgpConfig(
                bgp_peer_name=f"BGP_PEER_IPV6_IBGP_PLANE_{plane_num}_REMOTE_MP",
                local_as_4_bytes=ibgp_remote_as,
                enable_4_byte_local_as=True,
                enable_graceful_restart=False,
                bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                bgp_peer_type=ixia_types.BgpPeerType.IBGP,
            ),
        )
    )
    idx += 1

    # IPv4 DC (Remote EB)
    ibgp_v4_dc_multiplier = (
        ibgp_peer_scale_per_plane - ibgp_peer_to_drain_per_plane
        if drain
        else ibgp_peer_scale_per_plane
    )
    ibgp_v4_dc_route_end_index = ibgp_v4_dc_multiplier
    device_groups.append(
        DeviceGroupConfig(
            device_group_index=idx,
            device_group_name=f"DEVICE_GROUP_IPV4_IBGP_PLANE_{plane_num}_REMOTE_EB",
            multiplier=ibgp_v4_dc_multiplier,
            v4_addresses_config=IpAddressesConfig(
                starting_ip=f"{ixia_ibgp_ic_parent_network_v4_dc}.11",
                increment_ip="0.0.0.2",
                gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v4_dc}.10",
                gateway_increment_ip="0.0.0.2",
                mask=31,
                start_index=0,
            ),
            v4_bgp_config=BgpConfig(
                bgp_peer_name=f"BGP_PEER_IPV4_IBGP_PLANE_{plane_num}_REMOTE_EB",
                local_as_4_bytes=ibgp_remote_as,
                enable_4_byte_local_as=True,
                enable_graceful_restart=False,
                bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                import_bgp_routes_params_list=[
                    ixia_types.ImportBgpRoutesParams(
                        multiplier=multiplier,
                        bgp_route_import_file_path=get_bgp_route_file_path(
                            profile, f"ibgp_ipv4_{route_file_suffix}.csv"
                        ),
                        import_file_type=ixia_types.BgpRouteImportFileType.CSV,
                        network_group_index=0,
                        bgp_attribute_configs=[
                            ixia_types.BgpAttributeConfig(
                                attribute=ixia_types.BgpAttribute.COMMUNITIES,
                                file_path=get_bgp_route_file_path(
                                    profile, "ibgp_ipv4_communites.csv"
                                ),
                                distribution_type=ixia_types.DistribitionType.ROUND_ROBIN,
                            )
                        ],
                        bgp_next_hop_modification_type=ixia_types.BgpNextHopModificationType.PRESERVE_FROM_FILE,
                        prefix_pool_name=f"PREFIX_POOL_IBGP_IPV4_PLANE_{plane_num}_REMOTE_EB",
                        start_index=0,
                        end_index=ibgp_v4_dc_route_end_index,
                    )
                ],
            ),
        )
    )
    idx += 1

    # IPv4 DC (Remote EB) DRAIN (only when drain=True)
    if drain:
        device_groups.append(
            DeviceGroupConfig(
                device_group_index=idx,
                device_group_name=f"DEVICE_GROUP_IPV4_IBGP_PLANE_{plane_num}_REMOTE_EB_DRAIN",
                multiplier=ibgp_peer_to_drain_per_plane,
                v4_addresses_config=IpAddressesConfig(
                    starting_ip=f"{ixia_ibgp_ic_parent_network_v4_dc}.11",
                    increment_ip="0.0.0.2",
                    gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v4_dc}.10",
                    gateway_increment_ip="0.0.0.2",
                    mask=31,
                    start_index=ibgp_peer_scale_per_plane
                    - ibgp_peer_to_drain_per_plane,
                ),
                v4_bgp_config=BgpConfig(
                    bgp_peer_name=f"BGP_PEER_IPV4_IBGP_PLANE_{plane_num}_REMOTE_EB_DRAIN",
                    local_as_4_bytes=ibgp_remote_as,
                    enable_4_byte_local_as=True,
                    enable_graceful_restart=False,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                    bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                    import_bgp_routes_params_list=[
                        ixia_types.ImportBgpRoutesParams(
                            multiplier=multiplier,
                            bgp_route_import_file_path=get_bgp_route_file_path(
                                profile, f"ibgp_ipv4_{route_file_suffix}.csv"
                            ),
                            import_file_type=ixia_types.BgpRouteImportFileType.CSV,
                            network_group_index=0,
                            bgp_attribute_configs=[
                                ixia_types.BgpAttributeConfig(
                                    attribute=ixia_types.BgpAttribute.COMMUNITIES,
                                    file_path=get_bgp_route_file_path(
                                        profile, "ibgp_ipv4_communites.csv"
                                    ),
                                    distribution_type=ixia_types.DistribitionType.ROUND_ROBIN,
                                )
                            ],
                            bgp_next_hop_modification_type=ixia_types.BgpNextHopModificationType.PRESERVE_FROM_FILE,
                            prefix_pool_name=f"PREFIX_POOL_IBGP_IPV4_PLANE_{plane_num}_REMOTE_EB_DRAIN",
                            start_index=ibgp_peer_scale_per_plane
                            - ibgp_peer_to_drain_per_plane,
                            end_index=ibgp_peer_scale_per_plane,
                        )
                    ],
                ),
            )
        )
        idx += 1

    # IPv4 MP (Remote MP) - no drain variant
    device_groups.append(
        DeviceGroupConfig(
            device_group_index=idx,
            device_group_name=f"DEVICE_GROUP_IPV4_IBGP_PLANE_{plane_num}_REMOTE_MP",
            multiplier=ibgp_peer_scale_per_plane,
            v4_addresses_config=IpAddressesConfig(
                starting_ip=f"{ixia_ibgp_ic_parent_network_v4_mp}.11",
                increment_ip="0.0.0.2",
                gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v4_mp}.10",
                gateway_increment_ip="0.0.0.2",
                mask=31,
            ),
            v4_bgp_config=BgpConfig(
                bgp_peer_name=f"BGP_PEER_IPV4_IBGP_PLANE_{plane_num}_REMOTE_MP",
                local_as_4_bytes=ibgp_remote_as,
                enable_4_byte_local_as=True,
                enable_graceful_restart=False,
                bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                bgp_peer_type=ixia_types.BgpPeerType.IBGP,
            ),
        )
    )

    return device_groups


def get_bgp_route_file_path(profile: BgpPlusPlusProfile, base_filename: str) -> str:
    """
    Helper function to get the correct BGP route file path based on the profile.

    Args:
        profile: BGP++ profile enum value
        base_filename: Base filename (e.g., "ebgp_ipv6.csv", "ibgp_ipv4_p0.csv")

    Returns:
        Complete file path for the route file based on profile
    """
    if profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R:
        return f"generated_routes/bgp_plus_plus_open_r_routes/{base_filename}"
    else:
        return f"generated_routes/{base_filename}"


def create_ebb_scale_basic_port_configs(
    device_name: str,
    ixia_interface_mimic_ebgp: str,
    ixia_interface_mimic_ibgp: str,
    ixia_interface_mimic_bgp_mon: str,
    ebgp_peer_count_v6: int,
    ebgp_peer_count_v4: int,
    ebgp_peer_to_drain: int,
    ibgp_peer_scale_per_plane: int,
    ibgp_peer_to_drain_per_plane: int,
    bgp_mon_peer_count: int,
    ebgp_remote_as: int,
    ibgp_remote_as: int,
    bgp_mon_remote_as: int,
    ixia_ebgp_ic_parent_network_v6: str,
    ixia_ebgp_ic_parent_network_v4: str,
    ixia_ibgp_ic_parent_network_v6_dc_plane1: str,
    ixia_ibgp_ic_parent_network_v6_dc_plane2: str,
    ixia_ibgp_ic_parent_network_v6_dc_plane3: str,
    ixia_ibgp_ic_parent_network_v6_dc_plane4: str,
    ixia_ibgp_ic_parent_network_v6_mp_plane1: str,
    ixia_ibgp_ic_parent_network_v6_mp_plane2: str,
    ixia_ibgp_ic_parent_network_v6_mp_plane3: str,
    ixia_ibgp_ic_parent_network_v6_mp_plane4: str,
    ixia_ibgp_ic_parent_network_v4_dc_plane1: str,
    ixia_ibgp_ic_parent_network_v4_dc_plane2: str,
    ixia_ibgp_ic_parent_network_v4_dc_plane3: str,
    ixia_ibgp_ic_parent_network_v4_dc_plane4: str,
    ixia_ibgp_ic_parent_network_v4_mp_plane1: str,
    ixia_ibgp_ic_parent_network_v4_mp_plane2: str,
    ixia_ibgp_ic_parent_network_v4_mp_plane3: str,
    ixia_ibgp_ic_parent_network_v4_mp_plane4: str,
    ixia_bgp_mon_ic_parent_network: str,
    profile: BgpPlusPlusProfile = BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
    multiplier: int = 750,
    multiport_ibgp_sessions: bool = False,
    ixia_interface_mimic_ibgp_plane1: str | None = None,
    ixia_interface_mimic_ibgp_plane2: str | None = None,
    ixia_interface_mimic_ibgp_plane3: str | None = None,
    ixia_interface_mimic_ibgp_plane4: str | None = None,
    drain: bool = False,
) -> list[BasicPortConfig]:
    """
    Create basic port configurations for EBB scale testing with eBGP, iBGP, and BGP monitoring.

    This function generates Ixia port configurations for BGP scale testing scenarios including:
    - eBGP peers (IPv4/IPv6) with drain capability
    - iBGP peers across multiple planes (DC and MP) with drain capability
    - BGP monitoring peers

    Args:
        device_name: Name of the device under test
        ixia_interface_mimic_ebgp: Ixia interface for eBGP simulation
        ixia_interface_mimic_ibgp: Ixia interface for iBGP simulation (used when multiport_ibgp_sessions=False)
        ixia_interface_mimic_bgp_mon: Ixia interface for BGP monitoring
        ebgp_peer_count_v6: Total number of eBGP IPv6 peers
        ebgp_peer_count_v4: Total number of eBGP IPv4 peers
        ebgp_peer_to_drain: Number of eBGP peers to configure for draining
        ibgp_peer_scale_per_plane: Number of iBGP peers per plane
        ibgp_peer_to_drain_per_plane: Number of iBGP peers to drain per plane
        bgp_mon_peer_count: Number of BGP monitoring peers
        ebgp_remote_as: eBGP remote AS number
        ibgp_remote_as: iBGP remote AS number
        bgp_mon_remote_as: BGP monitoring remote AS number
        ixia_ebgp_ic_parent_network_v6: IPv6 network prefix for eBGP
        ixia_ebgp_ic_parent_network_v4: IPv4 network prefix for eBGP
        ixia_ibgp_ic_parent_network_v6_dc_plane1-4: IPv6 network prefixes for iBGP DC planes
        ixia_ibgp_ic_parent_network_v6_mp_plane1-4: IPv6 network prefixes for iBGP MP planes
        ixia_ibgp_ic_parent_network_v4_dc_plane1-4: IPv4 network prefixes for iBGP DC planes
        ixia_ibgp_ic_parent_network_v4_mp_plane1-4: IPv4 network prefixes for iBGP MP planes
        ixia_bgp_mon_ic_parent_network: IPv6 network prefix for BGP monitoring
        multiplier: Multiplier for route generation (default: 750)
        multiport_ibgp_sessions: When True, each iBGP plane uses a separate port instead of
            sharing a single port. Requires ixia_interface_mimic_ibgp_plane1-4 to be set.
        ixia_interface_mimic_ibgp_plane1: Ixia interface for iBGP plane 1 (when multiport_ibgp_sessions=True)
        ixia_interface_mimic_ibgp_plane2: Ixia interface for iBGP plane 2 (when multiport_ibgp_sessions=True)
        ixia_interface_mimic_ibgp_plane3: Ixia interface for iBGP plane 3 (when multiport_ibgp_sessions=True)
        ixia_interface_mimic_ibgp_plane4: Ixia interface for iBGP plane 4 (when multiport_ibgp_sessions=True)

    Returns:
        List of BasicPortConfig objects for Ixia configuration

    Note:
        When multiport_ibgp_sessions=True:
        - Port 1: eBGP sessions (IPv4/IPv6)
        - Port 2: iBGP Plane 1 sessions (DC + MP, IPv4/IPv6)
        - Port 3: iBGP Plane 2 sessions (DC + MP, IPv4/IPv6)
        - Port 4: iBGP Plane 3 sessions (DC + MP, IPv4/IPv6)
        - Port 5: iBGP Plane 4 sessions (DC + MP, IPv4/IPv6)
        - Port 6: BGP monitoring sessions (if bgp_mon_peer_count > 0)

        When multiport_ibgp_sessions=False (default):
        - Port 1: eBGP sessions (IPv4/IPv6)
        - Port 2: All iBGP sessions (all 4 planes, DC + MP, IPv4/IPv6)
        - Port 3: BGP monitoring sessions (if bgp_mon_peer_count > 0)
    """
    # Validate multiport configuration and set up plane interfaces
    if multiport_ibgp_sessions:
        if not all(
            [
                ixia_interface_mimic_ibgp_plane1,
                ixia_interface_mimic_ibgp_plane2,
                ixia_interface_mimic_ibgp_plane3,
                ixia_interface_mimic_ibgp_plane4,
            ]
        ):
            raise ValueError(
                "When multiport_ibgp_sessions=True, all plane interfaces must be provided: "
                "ixia_interface_mimic_ibgp_plane1, ixia_interface_mimic_ibgp_plane2, "
                "ixia_interface_mimic_ibgp_plane3, ixia_interface_mimic_ibgp_plane4"
            )
        # Multiport mode: each plane gets its own interface
        plane_interfaces = [
            ixia_interface_mimic_ibgp_plane1,
            ixia_interface_mimic_ibgp_plane2,
            ixia_interface_mimic_ibgp_plane3,
            ixia_interface_mimic_ibgp_plane4,
        ]
    else:
        # Single-port mode: all planes share the same interface
        plane_interfaces = [
            ixia_interface_mimic_ibgp,
            ixia_interface_mimic_ibgp,
            ixia_interface_mimic_ibgp,
            ixia_interface_mimic_ibgp,
        ]

    # Plane network configurations - used for BOTH single-port and multi-port modes
    plane_network_configs = [
        {
            "plane_num": 1,
            "v6_dc": ixia_ibgp_ic_parent_network_v6_dc_plane1,
            "v6_mp": ixia_ibgp_ic_parent_network_v6_mp_plane1,
            "v4_dc": ixia_ibgp_ic_parent_network_v4_dc_plane1,
            "v4_mp": ixia_ibgp_ic_parent_network_v4_mp_plane1,
            "interface": plane_interfaces[0],
        },
        {
            "plane_num": 2,
            "v6_dc": ixia_ibgp_ic_parent_network_v6_dc_plane2,
            "v6_mp": ixia_ibgp_ic_parent_network_v6_mp_plane2,
            "v4_dc": ixia_ibgp_ic_parent_network_v4_dc_plane2,
            "v4_mp": ixia_ibgp_ic_parent_network_v4_mp_plane2,
            "interface": plane_interfaces[1],
        },
        {
            "plane_num": 3,
            "v6_dc": ixia_ibgp_ic_parent_network_v6_dc_plane3,
            "v6_mp": ixia_ibgp_ic_parent_network_v6_mp_plane3,
            "v4_dc": ixia_ibgp_ic_parent_network_v4_dc_plane3,
            "v4_mp": ixia_ibgp_ic_parent_network_v4_mp_plane3,
            "interface": plane_interfaces[2],
        },
        {
            "plane_num": 4,
            "v6_dc": ixia_ibgp_ic_parent_network_v6_dc_plane4,
            "v6_mp": ixia_ibgp_ic_parent_network_v6_mp_plane4,
            "v4_dc": ixia_ibgp_ic_parent_network_v4_dc_plane4,
            "v4_mp": ixia_ibgp_ic_parent_network_v4_mp_plane4,
            "interface": plane_interfaces[3],
        },
    ]

    # eBGP port configuration (always the first port)
    ebgp_device_groups: list[DeviceGroupConfig] = []

    # IPv6 eBGP main group
    ebgp_v6_multiplier = (
        ebgp_peer_count_v6 - ebgp_peer_to_drain if drain else ebgp_peer_count_v6
    )
    ebgp_v6_route_end_index = ebgp_v6_multiplier
    ebgp_device_groups.append(
        DeviceGroupConfig(
            device_group_name="DEVICE_GROUP_IPV6_EBGP",
            device_group_index=0,
            multiplier=ebgp_v6_multiplier,
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
                        multiplier=multiplier,
                        bgp_route_import_file_path=get_bgp_route_file_path(
                            profile, "ebgp_ipv6.csv"
                        ),
                        import_file_type=ixia_types.BgpRouteImportFileType.CSV,
                        network_group_index=0,
                        bgp_attribute_configs=[
                            ixia_types.BgpAttributeConfig(
                                attribute=ixia_types.BgpAttribute.COMMUNITIES,
                                file_path=get_bgp_route_file_path(
                                    profile,
                                    "ipv6_routes_ebgp_communities_enhanced.csv",
                                ),
                                distribution_type=ixia_types.DistribitionType.ROUND_ROBIN,
                            )
                        ],
                        bgp_next_hop_modification_type=ixia_types.BgpNextHopModificationType.PRESERVE_FROM_FILE,
                        start_index=0,
                        end_index=ebgp_v6_route_end_index,
                    )
                ],
            ),
        ),
    )

    # IPv6 eBGP drain group (only when drain=True)
    if drain:
        ebgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV6_EBGP_DRAIN",
                device_group_index=1,
                multiplier=ebgp_peer_to_drain,
                v6_addresses_config=taac_types.IpAddressesConfig(
                    starting_ip=f"{ixia_ebgp_ic_parent_network_v6}::11",
                    increment_ip="0:0:0:0::2",
                    gateway_starting_ip=f"{ixia_ebgp_ic_parent_network_v6}::10",
                    gateway_increment_ip="0:0:0:0::2",
                    start_index=ebgp_peer_count_v6 - ebgp_peer_to_drain,
                ),
                v6_bgp_config=BgpConfig(
                    bgp_peer_name="BGP_PEER_IPV6_EBGP_DRAIN",
                    local_as_4_bytes=ebgp_remote_as,
                    enable_4_byte_local_as=True,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                    bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                    import_bgp_routes_params_list=[
                        ixia_types.ImportBgpRoutesParams(
                            prefix_pool_name="PREFIX_POOL_IPV6_EBGP_DRAIN",
                            multiplier=multiplier,
                            bgp_route_import_file_path=get_bgp_route_file_path(
                                profile, "ebgp_ipv6.csv"
                            ),
                            import_file_type=ixia_types.BgpRouteImportFileType.CSV,
                            network_group_index=0,
                            bgp_attribute_configs=[
                                ixia_types.BgpAttributeConfig(
                                    attribute=ixia_types.BgpAttribute.COMMUNITIES,
                                    file_path=get_bgp_route_file_path(
                                        profile,
                                        "ipv6_routes_ebgp_communities_enhanced.csv",
                                    ),
                                    distribution_type=ixia_types.DistribitionType.ROUND_ROBIN,
                                )
                            ],
                            bgp_next_hop_modification_type=ixia_types.BgpNextHopModificationType.PRESERVE_FROM_FILE,
                            start_index=ebgp_peer_count_v6 - ebgp_peer_to_drain,
                            end_index=ebgp_peer_count_v6,  # non-inclusive
                        )
                    ],
                ),
            ),
        )

    # IPv4 eBGP main group
    ebgp_v4_dg_index = len(ebgp_device_groups)
    ebgp_v4_multiplier = (
        ebgp_peer_count_v4 - ebgp_peer_to_drain if drain else ebgp_peer_count_v4
    )
    ebgp_device_groups.append(
        DeviceGroupConfig(
            device_group_name="DEVICE_GROUP_IPV4_EBGP",
            device_group_index=ebgp_v4_dg_index,
            multiplier=ebgp_v4_multiplier,
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
                        multiplier=multiplier,
                        bgp_route_import_file_path=get_bgp_route_file_path(
                            profile, "ebgp_ipv4.csv"
                        ),
                        import_file_type=ixia_types.BgpRouteImportFileType.CSV,
                        network_group_index=0,
                        bgp_attribute_configs=[
                            ixia_types.BgpAttributeConfig(
                                attribute=ixia_types.BgpAttribute.COMMUNITIES,
                                file_path=get_bgp_route_file_path(
                                    profile,
                                    "ipv4_routes_ebgp_communities_enhanced.csv",
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

    # IPv4 eBGP drain group (only when drain=True)
    if drain:
        ebgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV4_EBGP_DRAIN",
                device_group_index=ebgp_v4_dg_index + 1,
                multiplier=ebgp_peer_to_drain,
                v4_addresses_config=taac_types.IpAddressesConfig(
                    starting_ip=f"{ixia_ebgp_ic_parent_network_v4}.11",
                    increment_ip="0.0.0.2",
                    gateway_starting_ip=f"{ixia_ebgp_ic_parent_network_v4}.10",
                    gateway_increment_ip="0.0.0.2",
                    mask=31,
                    start_index=ebgp_peer_count_v4 - ebgp_peer_to_drain,
                ),
                v4_bgp_config=BgpConfig(
                    bgp_peer_name="BGP_PEER_IPV4_EBGP_DRAIN",
                    local_as_4_bytes=ebgp_remote_as,
                    enable_4_byte_local_as=True,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                    bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                    import_bgp_routes_params_list=[
                        ixia_types.ImportBgpRoutesParams(
                            prefix_pool_name="PREFIX_POOL_IPV4_EBGP_DRAIN",
                            multiplier=multiplier,
                            bgp_route_import_file_path=get_bgp_route_file_path(
                                profile, "ebgp_ipv4.csv"
                            ),
                            import_file_type=ixia_types.BgpRouteImportFileType.CSV,
                            network_group_index=0,
                            bgp_attribute_configs=[
                                ixia_types.BgpAttributeConfig(
                                    attribute=ixia_types.BgpAttribute.COMMUNITIES,
                                    file_path=get_bgp_route_file_path(
                                        profile,
                                        "ipv4_routes_ebgp_communities_enhanced.csv",
                                    ),
                                    distribution_type=ixia_types.DistribitionType.ROUND_ROBIN,
                                )
                            ],
                            bgp_next_hop_modification_type=ixia_types.BgpNextHopModificationType.PRESERVE_FROM_FILE,
                            start_index=ebgp_peer_count_v4 - ebgp_peer_to_drain,
                            end_index=ebgp_peer_count_v4,  # non-inclusive
                        )
                    ],
                ),
            ),
        )

    basic_configs: list[BasicPortConfig] = [
        BasicPortConfig(
            endpoint=f"{device_name}:{ixia_interface_mimic_ebgp}",
            device_group_configs=ebgp_device_groups,
        ),
    ]

    # iBGP port configuration - group device groups by interface
    # In multi-port mode: 4 unique interfaces → 4 BasicPortConfigs
    # In single-port mode: 1 interface (same for all) → 1 BasicPortConfig with all device groups

    interface_device_groups: dict[str, list[DeviceGroupConfig]] = defaultdict(list)
    device_group_index_by_interface: dict[str, int] = {}

    for plane_config in plane_network_configs:
        interface = str(plane_config["interface"])
        current_offset = device_group_index_by_interface.get(interface, 0)

        plane_device_groups = _create_ibgp_plane_device_groups(
            plane_num=int(plane_config["plane_num"]),  # type: ignore[arg-type]
            ibgp_peer_scale_per_plane=ibgp_peer_scale_per_plane,
            ibgp_peer_to_drain_per_plane=ibgp_peer_to_drain_per_plane,
            ibgp_remote_as=ibgp_remote_as,
            ixia_ibgp_ic_parent_network_v6_dc=str(plane_config["v6_dc"]),
            ixia_ibgp_ic_parent_network_v6_mp=str(plane_config["v6_mp"]),
            ixia_ibgp_ic_parent_network_v4_dc=str(plane_config["v4_dc"]),
            ixia_ibgp_ic_parent_network_v4_mp=str(plane_config["v4_mp"]),
            profile=profile,
            multiplier=multiplier,
            device_group_index_offset=current_offset,
            drain=drain,
        )

        interface_device_groups[interface].extend(plane_device_groups)
        device_group_index_by_interface[interface] = current_offset + len(
            plane_device_groups
        )

    # Create BasicPortConfig for each unique interface
    for interface, device_groups in interface_device_groups.items():
        basic_configs.append(
            BasicPortConfig(
                endpoint=f"{device_name}:{interface}",
                device_group_configs=device_groups,
            )
        )

    # Only add BGP monitoring port config if bgp_mon_peer_count is greater than 0
    if bgp_mon_peer_count > 0:
        basic_configs.append(
            BasicPortConfig(
                endpoint=f"{device_name}:{ixia_interface_mimic_bgp_mon}",
                device_group_configs=[
                    DeviceGroupConfig(
                        device_group_name="DEVICE_GROUP_BGP_MON",
                        device_group_index=0,
                        multiplier=bgp_mon_peer_count,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_bgp_mon_ic_parent_network}::11",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_bgp_mon_ic_parent_network}::10",
                            gateway_increment_ip="0:0:0:0::2",
                            start_index=0,
                        ),
                        v6_bgp_config=BgpConfig(
                            bgp_peer_name="BGP_PEER_IPV6_BGP_MON",
                            local_as_4_bytes=bgp_mon_remote_as,
                            enable_4_byte_local_as=True,
                            enable_graceful_restart=False,
                            bgp_capabilities=[
                                ixia_types.BgpCapability.IpV6Unicast,
                                ixia_types.BgpCapability.IpV4Unicast,
                                ixia_types.BgpCapability.Ipv4UnicastAddPath,
                                ixia_types.BgpCapability.Ipv6UnicastAddPath,
                                ixia_types.BgpCapability.NHEncodingCapabilities,
                            ],
                            bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                        ),
                    ),
                ],
            )
        )

    return basic_configs
