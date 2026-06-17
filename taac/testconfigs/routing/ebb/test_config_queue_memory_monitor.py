# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
Test Config for BGP++ Queue and Memory Monitoring Under Route Churn

This test monitors BGP++ fiber queue statistics and memory usage over time
while subjecting the router to continuous route churn via flapping.

Test Design:
    - IXIA mimics 50 EBGP peers and 25 IBGP peers
    - Each EBGP peer advertises 10K prefixes (same prefixes across peers)
    - Each EBGP peer has a unique AS_PATH (100 AS numbers)
    - Route flapping: 15 seconds up, 15 seconds down (configurable)
    - Monitor for 60 minutes at 2-minute intervals (30 data points)

Monitored Metrics:
    - Fiber queue statistics: AdjRibIn, AdjRibOut, RibQueue
    - BGP++ memory usage: RSS and VMS

Expected Behavior:
    - Queues spike during flapping but drain between cycles
    - Memory remains stable (no continuous growth = no leaks)
    - After flapping stops, queues drain to near-zero
    - After session teardown, memory is released
"""

from typing import List

from ixia.ixia import types as ixia_types
from taac.playbooks.playbook_definitions import (
    create_bgp_queue_memory_monitoring_playbook,
)
from taac.routing.ebb.arista_bgp_plus_plus_performance_scaling_tests.attribute_pool_generator import (
    generate_as_path_pool,
)
from taac.task_definitions import (
    create_configure_bgpcpp_startup_task,
    create_replace_bgp_peers_task,
)
from taac.test_as_a_config.types import (
    BasicPortConfig,
    BgpConfig,
    DeviceGroupConfig,
    Endpoint,
    IpAddressesConfig,
    RouteScale,
    RouteScaleSpec,
    TestConfig,
)


def test_config_bgp_queue_memory_monitoring_with_route_scale(
    test_config_name: str,
    device_name: str,
    # IBGP configuration
    ixia_interface_mimic_ibgp: str,
    ibgp_local_as: int,
    ixia_ibgp_ic_parent_network_v6: str,
    ixia_ibgp_ic_parent_network_v4: str,
    # EBGP configuration
    ixia_interface_mimic_ebgp: str,
    ebgp_remote_as: int,
    ixia_ebgp_ic_parent_network_v6: str,
    ixia_ebgp_ic_parent_network_v4: str,
    # Test parameters
    ibgp_peer_count: int = 25,
    ebgp_peer_count: int = 50,
    prefixes_per_ebgp_peer: int = 10000,
    ip_version: str = "ipv6",  # "ipv4", "ipv6", or "both"
    # Route acceptance communities
    ebgp_route_acceptance_communities: List[str] | None = None,
    # Monitoring parameters
    monitoring_duration_minutes: int = 60,
    monitoring_interval_seconds: int = 120,
    # Route flapping parameters
    flap_uptime_seconds: int = 15,
    flap_downtime_seconds: int = 15,
    # Optional parameters
    direct_ixia_connections: List | None = None,
    log_collection_timeout: int | None = None,
    oss_mock_device_data=None,
    host_os_type_map=None,
    host_driver_args=None,
    # Setup/teardown tasks (optional - when provided, used directly)
    setup_tasks: List | None = None,
    teardown_tasks: List | None = None,
    # CPU stress monitoring (only enable when setup_tasks include CPU stress)
    monitor_cpu_stress: bool = False,
    # Dynamic peer configuration (optional - when provided and setup_tasks is None, setup_tasks are built)
    ssh_user: str | None = None,
    ssh_password: str | None = None,
    peergroup_ebgp_v6: str = "EB-FA-V6",
    peergroup_ebgp_v4: str = "EB-FA-V4",
    peergroup_ibgp_v6: str = "EB-EB-V6",
    peergroup_ibgp_v4: str = "EB-EB-V4",
):
    """
    Create test config for BGP++ queue and memory monitoring under route churn.

    Args:
        test_config_name: Name of the test configuration
        device_name: Device under test (DUT) hostname (e.g., "eb04.lab.ash6")
        ixia_interface_mimic_ibgp: IBGP interface (e.g., "Ethernet3/1/3")
        ibgp_local_as: IBGP local AS number
        ixia_ibgp_ic_parent_network_v6: IPv6 network for IBGP
        ixia_ibgp_ic_parent_network_v4: IPv4 network for IBGP
        ixia_interface_mimic_ebgp: EBGP interface (e.g., "Ethernet3/1/1")
        ebgp_remote_as: EBGP remote AS number
        ixia_ebgp_ic_parent_network_v6: IPv6 network for EBGP
        ixia_ebgp_ic_parent_network_v4: IPv4 network for EBGP
        ibgp_peer_count: Number of IBGP peers (default: 25)
        ebgp_peer_count: Number of EBGP peers (default: 50)
        prefixes_per_ebgp_peer: Prefixes per EBGP peer (default: 10000)
            → 50 peers x 10,000 prefixes = 500,000 total routes
        ip_version: IP version to test (default: "ipv6")
            - "ipv4": IPv4 only
            - "ipv6": IPv6 only
            - "both": Both IPv4 and IPv6
        monitoring_duration_minutes: Total monitoring duration (default: 60)
        monitoring_interval_seconds: Sampling interval (default: 120)
        flap_uptime_seconds: Route uptime in seconds (default: 15)
        flap_downtime_seconds: Route downtime in seconds (default: 15)
        direct_ixia_connections: Optional direct IXIA connections
        log_collection_timeout: Optional log collection timeout
        host_os_type_map: Optional host OS type mapping
        host_driver_args: Optional host driver arguments

    Returns:
        TestConfig for BGP++ queue and memory monitoring
    """
    # Generate unique AS_PATH for each EBGP peer (100 AS numbers per path)
    # Using the existing API from attribute_pool_generator
    ebgp_as_paths = generate_as_path_pool(
        count=ebgp_peer_count,
        base_as=64512,  # Start of private ASN range
        as_path_length=100,  # 100 AS numbers per peer
    )

    # Build IBGP device group configs
    ibgp_device_groups = []

    # Add IPv6 IBGP device group if testing IPv6
    if ip_version in ["ipv6", "both"]:
        ibgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV6_IBGP",
                device_group_index=0,
                multiplier=ibgp_peer_count,
                enable=False,  # Disabled initially - custom step will enable after baseline measurement
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
                ),
            )
        )

    # Add IPv4 IBGP device group if testing IPv4
    if ip_version in ["ipv4", "both"]:
        ibgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV4_IBGP",
                device_group_index=1 if ip_version == "both" else 0,
                multiplier=ibgp_peer_count,
                enable=False,  # Disabled initially - custom step will enable after baseline measurement
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
                    enable_graceful_restart=False,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                    bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                ),
            )
        )

    # Build EBGP device group configs
    ebgp_device_groups = []

    # Add IPv6 EBGP device group if testing IPv6
    if ip_version in ["ipv6", "both"]:
        ebgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV6_EBGP",
                device_group_index=0,
                multiplier=ebgp_peer_count,
                enable=False,  # Disabled initially - custom step will enable after baseline measurement
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
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                    bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                    route_scales=[
                        RouteScaleSpec(
                            v6_route_scale=RouteScale(
                                prefix_name="PREFIX_POOL_IPV6_EBGP",
                                starting_prefixes="3001:db8:1000::",
                                prefix_step="0:0:0:0:0:0:0:0",  # Same prefixes for all peers
                                prefix_length=64,
                                multiplier=1,
                                prefix_count=prefixes_per_ebgp_peer,
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                bgp_communities=ebgp_route_acceptance_communities
                                if ebgp_route_acceptance_communities
                                else [],
                                # Route flapping configuration
                                prefix_flap_config=ixia_types.BgpFlapConfig(
                                    uptime_in_sec=flap_uptime_seconds,
                                    downtime_in_sec=flap_downtime_seconds,
                                ),
                            ),
                            multiplier=1,
                            network_group_index=0,
                        )
                    ],
                ),
            )
        )

    # Add IPv4 EBGP device group if testing IPv4
    if ip_version in ["ipv4", "both"]:
        ebgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV4_EBGP",
                device_group_index=1 if ip_version == "both" else 0,
                multiplier=ebgp_peer_count,
                enable=False,  # Disabled initially - custom step will enable after baseline measurement
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
                    bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                    bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                    route_scales=[
                        RouteScaleSpec(
                            v4_route_scale=RouteScale(
                                prefix_name="PREFIX_POOL_IPV4_EBGP",
                                starting_prefixes="20.100.0.0",
                                prefix_step="0.0.0.0",  # Same prefixes for all peers
                                prefix_length=24,
                                multiplier=1,
                                prefix_count=prefixes_per_ebgp_peer,
                                ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                bgp_communities=ebgp_route_acceptance_communities
                                if ebgp_route_acceptance_communities
                                else [],
                                # Route flapping configuration
                                prefix_flap_config=ixia_types.BgpFlapConfig(
                                    uptime_in_sec=flap_uptime_seconds,
                                    downtime_in_sec=flap_downtime_seconds,
                                ),
                            ),
                            multiplier=1,
                            network_group_index=0,
                        )
                    ],
                ),
            )
        )

    # Build setup_tasks: use provided setup_tasks, or build from ssh params
    if setup_tasks is None:
        setup_tasks = []
    if not setup_tasks and ssh_user is not None and ssh_password is not None:
        setup_tasks = [
            create_configure_bgpcpp_startup_task(
                hostname=device_name,
                flags={
                    "agent_thrift_recv_timeout_ms": "160000",
                },
                ssh_user=ssh_user,
                ssh_password=ssh_password,
            ),
            create_replace_bgp_peers_task(
                hostname=device_name,
                peer_configs=[
                    {
                        "peer_group_name": peergroup_ebgp_v6,
                        "remote_as": ebgp_remote_as,
                        "base_network": ixia_ebgp_ic_parent_network_v6,
                        "is_v6": True,
                        "peer_count": ebgp_peer_count,
                        "start_offset": 16,
                    },
                    {
                        "peer_group_name": peergroup_ebgp_v4,
                        "remote_as": ebgp_remote_as,
                        "base_network": ixia_ebgp_ic_parent_network_v4,
                        "is_v6": False,
                        "peer_count": ebgp_peer_count,
                        "start_offset": 10,
                    },
                    {
                        "peer_group_name": peergroup_ibgp_v6,
                        "remote_as": ibgp_local_as,
                        "base_network": ixia_ibgp_ic_parent_network_v6,
                        "is_v6": True,
                        "peer_count": ibgp_peer_count,
                        "start_offset": 16,
                    },
                    {
                        "peer_group_name": peergroup_ibgp_v4,
                        "remote_as": ibgp_local_as,
                        "base_network": ixia_ibgp_ic_parent_network_v4,
                        "is_v6": False,
                        "peer_count": ibgp_peer_count,
                        "start_offset": 10,
                    },
                ],
            ),
        ]

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
                    ixia_interface_mimic_ibgp,
                    ixia_interface_mimic_ebgp,
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
        setup_tasks=setup_tasks,
        teardown_tasks=teardown_tasks if teardown_tasks else [],
        # Deprecated - define at playbook level
        # prechecks=[],
        # postchecks=[],
        # snapshot_checks - moved to playbook level
        basic_port_configs=[
            # IBGP configuration
            BasicPortConfig(
                endpoint=f"{device_name}:{ixia_interface_mimic_ibgp}",
                device_group_configs=ibgp_device_groups,
            ),
            # EBGP configuration (with route flapping)
            BasicPortConfig(
                endpoint=f"{device_name}:{ixia_interface_mimic_ebgp}",
                device_group_configs=ebgp_device_groups,
            ),
        ],
        playbooks=[
            create_bgp_queue_memory_monitoring_playbook(
                device_name=device_name,
                monitoring_duration_minutes=monitoring_duration_minutes,
                monitoring_interval_seconds=monitoring_interval_seconds,
                ebgp_as_paths=ebgp_as_paths,
                ebgp_peer_count=ebgp_peer_count,
                ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
                monitor_cpu_stress=monitor_cpu_stress,
            ),
        ],
    )
