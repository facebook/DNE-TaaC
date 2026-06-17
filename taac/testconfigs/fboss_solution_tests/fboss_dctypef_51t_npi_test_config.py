# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
FBOSS DCTypeF 51T NPI Test Configuration

This module provides configuration for testing FBOSS DCTypeF 51T platforms.
It sets up BGP peering, traffic generation, and health checks for network testing.
"""

import asyncio
import json
import typing as t

from ixia.ixia import types as ixia_types
from taac.constants import Gigabyte
from taac.health_checks.constants import (
    SERVICES_TO_MONITOR_DURING_AGENT_RESTART,
)
from taac.health_checks.healthcheck_definitions import (
    create_bgp_peer_route_snapshot_check,
    create_bgp_session_establish_check,
    create_core_dumps_snapshot_check,
    create_cpu_queue_snapshot_check,
    create_cpu_utilization_check,
    create_drain_state_check,
    create_ixia_packet_loss_check,
    create_memory_utilization_check,
    create_prefix_limit_check,
    create_service_restart_check,
    create_systemctl_active_state_check,
    create_unclean_exit_check,
)
from taac.packet_headers import (
    ARP_REQUEST_TRAFFIC_PACKET_HEADERS,
    ARP_RESPONSE_TRAFFIC_PACKET_HEADERS,
    BGP_CP_TRAFFIC_PACKET_HEADERS,
    DHCP_V4_DISCOVER_TO_SERVER_TRAFFIC_PACKET_HEADERS,
    DHCP_V4_DISCOVER_TRAFFIC_PACKET_HEADERS,
    DHCP_V6_TRAFFIC_PACKET_HEADERS,
    HOP_LIMIT_0_IPV6_TRAFFIC_PACKET_HEADERS,
    HOP_LIMIT_1_IPV6_TRAFFIC_PACKET_HEADERS,
    ICMP_V4_DEST_UNREACHABLE_TRAFFIC_PACKET_HEADERS,
    ICMP_V4_ECHO_REPLY_TRAFFIC_PACKET_HEADERS,
    ICMP_V4_ECHO_REQUEST_TRAFFIC_PACKET_HEADERS,
    ICMP_V4_TIME_EXCEEDED_TRAFFIC_PACKET_HEADERS,
    ICMP_V6_DEST_UNREACHABLE_GLOBAL_DSCP48_TRAFFIC_PACKET_HEADERS,
    ICMP_V6_DEST_UNREACHABLE_LINK_LOCAL_TRAFFIC_PACKET_HEADERS,
    ICMP_V6_ECHO_REPLY_GLOBAL_DSCP48_TRAFFIC_PACKET_HEADERS,
    ICMP_V6_ECHO_REPLY_LINK_LOCAL_TRAFFIC_PACKET_HEADERS,
    ICMP_V6_ECHO_REQUEST_GLOBAL_DSCP48_TRAFFIC_PACKET_HEADERS,
    ICMP_V6_ECHO_REQUEST_LINK_LOCAL_TRAFFIC_PACKET_HEADERS,
    ICMP_V6_PACKET_TOO_BIG_GLOBAL_DSCP48_TRAFFIC_PACKET_HEADERS,
    ICMP_V6_PACKET_TOO_BIG_LINK_LOCAL_TRAFFIC_PACKET_HEADERS,
    ICMP_V6_REQUEST_TRAFFIC_PACKET_HEADERS,
    ICMP_V6_TIME_EXCEEDED_GLOBAL_DSCP48_TRAFFIC_PACKET_HEADERS,
    ICMP_V6_TIME_EXCEEDED_LINK_LOCAL_TRAFFIC_PACKET_HEADERS,
    LACP_SLOW_TIMER_TRAFFIC_PACKET_HEADERS,
    LLDP_TRAFFIC_PACKET_HEADERS,
    NDP_NA_MULTICAST_TRAFFIC_PACKET_HEADERS,
    NDP_NS_MULTICAST_TRAFFIC_PACKET_HEADERS,
    NDP_RA_MULTICAST_TRAFFIC_PACKET_HEADERS,
    NDP_RS_MULTICAST_TRAFFIC_PACKET_HEADERS,
    TTL_0_IPV4_TRAFFIC_PACKET_HEADERS,
    TTL_1_IPV4_TRAFFIC_PACKET_HEADERS,
)
from taac.playbooks.playbook_definitions import (
    build_dctypef_npi_playbook,
    TEST_51T_NPI_DCTYPEF_PLAYBOOKS,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_custom_step,
    create_interface_flap_step,
    create_longevity_step,
    create_service_convergence_step,
    create_service_interruption_step,
    create_unregister_patcher_step,
)
from taac.task_definitions import (
    create_configure_parallel_bgp_peers_task,
    create_coop_apply_patchers_task,
    create_coop_register_patcher_task,
    create_coop_unregister_patchers_task,
    create_wait_for_agent_convergence_task,
)
from taac.utils.netwhoami_utils import fetch_whoami
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import Playbook, Service, TestConfig


def _add_common_checks_to_npi_playbooks(
    playbooks: t.List[Playbook],
    unique_prefix_limit: str,
) -> t.List[Playbook]:
    """Add former TestConfig-level checks to each playbook.

    Merges prechecks, postchecks, and snapshot_checks into each playbook,
    appending to any existing checks the playbook already has.
    """
    common_prechecks = [
        create_drain_state_check(),
        create_bgp_session_establish_check(),
        create_systemctl_active_state_check(),
        create_prefix_limit_check(prefix_limit=unique_prefix_limit),
        create_memory_utilization_check(
            threshold=Gigabyte.GIG_5.value,
            start_time_jq_var="test_case_start_time",
        ),
        create_ixia_packet_loss_check(
            thresholds=[hc_types.PacketLossThreshold(str_value="0.1")],
        ),
    ]
    common_postchecks = [
        create_service_restart_check(start_time_jq_var="test_case_start_time"),
        create_prefix_limit_check(prefix_limit=unique_prefix_limit),
        create_unclean_exit_check(start_time_jq_var="test_case_start_time"),
        create_ixia_packet_loss_check(
            thresholds=[hc_types.PacketLossThreshold(str_value="0.1")],
        ),
        create_cpu_utilization_check(
            threshold=400.0,
            start_time_jq_var="test_case_start_time",
        ),
    ]
    common_snapshot_checks = [
        create_core_dumps_snapshot_check(),
        create_bgp_peer_route_snapshot_check(),
    ]
    result = []
    for pb in playbooks:
        result.append(
            build_dctypef_npi_playbook(
                name=pb.name,
                stages=pb.stages,
                description=pb.description,
                iteration=pb.iteration,
                traffic_items_to_start=pb.traffic_items_to_start,
                enabled=pb.enabled,
                backup_and_restore_ixia_config=pb.backup_and_restore_ixia_config,
                prechecks=list(pb.prechecks or []) + common_prechecks,
                postchecks=list(pb.postchecks or []) + common_postchecks,
                snapshot_checks=list(pb.snapshot_checks or []) + common_snapshot_checks,
                skip_test_config_prechecks=pb.skip_test_config_prechecks,
                skip_test_config_postchecks=pb.skip_test_config_postchecks,
                skip_test_config_snapshot_checks=pb.skip_test_config_snapshot_checks,
                override_duplicate_checks=pb.override_duplicate_checks,
                prechecks_to_skip=pb.prechecks_to_skip,
                postchecks_to_skip=pb.postchecks_to_skip,
                snapshot_checks_to_skip=pb.snapshot_checks_to_skip,
                check_ids_to_skip=pb.check_ids_to_skip,
                cleanup_steps=pb.cleanup_steps,
                setup_steps=pb.setup_steps,
                device_regexes=pb.device_regexes,
                periodic_tasks=pb.periodic_tasks,
                attribute_filters=pb.attribute_filters,
                traffic_items_to_configure=pb.traffic_items_to_configure,
                scuba_table=pb.scuba_table,
            )
        )
    return result


def get_cpu_queue_constants(hostname: str):
    """
    Determine CPU queue constants based on hardware type using netwhoami.

    Args:
        hostname: Device hostname to query hardware information

    Returns:
        tuple: (low_queue, mid_queue, high_queue) values based on hardware

    Raises:
        ValueError: If hardware type is unknown or unsupported
        Exception: If netwhoami fetch fails
    """
    try:
        # Use asyncio.run to call the async fetch_whoami function synchronously
        netwhoami = asyncio.run(fetch_whoami(hostname))
        # Normalize hardware to its symbolic name so this works identically for
        # the Meta NetWhoAmI thrift (enum .name) and the OSS stand-in (string name).
        hardware = netwhoami.hw.name if netwhoami.hw else ""

        # Check against specific Hardware names from the thrift Hardware enum.
        if hardware in (
            "MONTBLANC",  # MONTBLANC = 40 (for minipack3)
            "MINIPACK3BA",  # MINIPACK3BA = 72
        ):
            return (0, 2, 9)
        elif hardware == "MORGAN800CC":  # MORGAN800CC = 46 (Kodiak3)
            return (0, 2, 7)
        else:
            raise ValueError(
                f"Unknown or unsupported hardware type '{hardware}' for {hostname}. "
                f"Please add CPU queue constants for this hardware type."
            )
    except Exception as e:
        if isinstance(e, ValueError):
            # Re-raise ValueError (unknown hardware type)
            raise
        # For all other exceptions (netwhoami fetch failures), raise with context
        raise Exception(f"Failed to fetch netwhoami for {hostname}: {e}") from e


def create_dctypef_npi_test_config(
    test_config_name,
    device_name,
    local_mac_address,
    ixia_downlink_interface,
    ixia_uplink_interface,
    ixia_rogue_interface,
    peergroup_uplink_mimic_v6,
    peergroup_uplink_mimic_v4,
    peergroup_downlink_mimic_v6,
    peergroup_downlink_mimic_v4,
    peergroup_rogue_mimic_v6,
    peergroup_rogue_mimic_v4,
    route_map_uplink_ingress,
    route_map_uplink_egress,
    route_map_downlink_ingress,
    route_map_downlink_egress,
    route_map_rogue_ingress,
    route_map_rogue_egress,
    ixia_downlink_ic_parent_network_v6,
    ixia_uplink_ic_parent_network_v6,
    ixia_rogue_ic_parent_network_v6,
    ixia_downlink_ic_parent_network_v4,
    ixia_uplink_ic_parent_network_v4,
    ixia_rogue_ic_parent_network_v4,
    unique_prefix_limit,
    per_peer_max_route_limit,
    downlink_peer_count,
    uplink_peer_count,
    rogue_peer_count,
    remote_uplink_as_4byte,
    remote_downlink_as_4byte,
    remote_as_4_byte_step,
    remote_rogue_as_4byte,
    is_uplink_peer_confed,
    is_downlink_peer_confed,
    is_rogue_peer_confed,
    ixia_downlink_prefix_count_v6,
    ixia_uplink_prefix_count_v6,
    ixia_rogue_prefix_count_v6,
    ixia_downlink_prefix_count_v4,
    ixia_uplink_prefix_count_v4,
    ixia_rogue_prefix_count_v4,
    ixia_downlink_communities,
    ixia_uplink_communities,
    uplink_peer_tag,
    downlink_peer_tag,
    bgpd_rss_limit=5,
    bgpd_cache_size_limit=4000,
    bgpd_restart_no_of_interations=1,
    wedge_agent_restart_no_of_interations=1,
    direct_ixia_connections=None,
    basset_pool=None,
):
    """Build the DC-TypeF 51T NPI base TestConfig.

    Constructs a single-DUT TestConfig for the DC-TypeF 51T New Product Introduction
    (NPI) flow that exercises BGP, ECMP, and platform hardening on a TH4 / TH5-class
    platform. Resolves hardware-specific CPU queue constants (low/mid/high) from
    ``get_cpu_queue_constants(device_name)`` so the per-device CPU queue priorities
    match the silicon under test.

    See ``create_dctypef_npi_cpu_queue_test_config`` for the CPU-queue-specialized
    variant; this one focuses on data-plane BGP/ECMP rather than CPU prioritization.

    Args:
        test_config_name: Name to register in the TestConfig (CLI-callable).
        device_name: DUT hostname; also used to resolve CPU queue constants.
        local_mac_address: Local MAC address for the DUT side of IXIA peering.
        ixia_downlink_interface / ixia_uplink_interface / ixia_rogue_interface:
            DUT-facing IXIA ports for each peer group.
        peergroup_*_mimic_v6 / _v4: BGP peer-group names per direction and AFI.
        route_map_*_ingress / _egress: Inbound/outbound policy per direction.
        ixia_*_ic_parent_network_v6 / _v4: IXIA-side parent IP per interface.
        unique_prefix_limit: Per-peer unique-prefix cap programmed on the DUT.
        per_peer_max_route_limit: Per-peer max-route guard.
        downlink_peer_count / uplink_peer_count / rogue_peer_count: Mimic peer counts.
        remote_uplink_as_4byte / remote_downlink_as_4byte: Remote AS numbers (4-byte).
        remote_as_4_byte_step: Remote-AS increment between peers.
        bgpd_rss_limit / bgpd_cache_size_limit: BGPd resource limits.
        bgpd_restart_no_of_interations / wedge_agent_restart_no_of_interations:
            Restart iteration counts (sic — preserves historical typo).
        direct_ixia_connections: Optional explicit direct-IXIA connection mapping.
        basset_pool: Override basset pool selection.

    Returns:
        TestConfig: The DC-TypeF NPI base TestConfig.
    """
    # Get hardware-specific CPU queue constants
    low_queue, mid_queue, high_queue = get_cpu_queue_constants(device_name)
    # Create and return the complete test configuration
    return TestConfig(
        name=test_config_name,
        ixia_protocol_verification_timeout=600,
        basset_pool="dne.test",
        # Mirrors the NPI CPU queue testconfig opt-out — same shared
        # `create_custom_step(register_cpu_queue_static_route_patcher)`
        # invocation in the UNH playbooks reads `ixia.vport_indices`,
        # which is empty on Tier 1/Tier 2 cache HIT. See
        # `Ixia.assign_ports` / `Ixia.vport_indices` docstrings and
        # `testconfigs/npi/cpu_queue_test_config.py:219` for the
        # canonical rationale. Caught by
        # `tests/test_ixia_cache_opt_out_gate.py`.
        ixia_config_cache=taac_types.IxiaConfigCache(enabled=False),
        endpoints=[
            taac_types.Endpoint(
                name=device_name,
                ixia_ports=[
                    ixia_downlink_interface,
                    ixia_uplink_interface,
                ],
                dut=True,
                mac_address=local_mac_address,
                direct_ixia_connections=direct_ixia_connections or [],
            ),
        ],
        # Setup tasks to configure the device before testing
        setup_tasks=[
            create_coop_unregister_patchers_task(device_name),
            # Remove all the bgp peers present in the device first
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="a_remove_bgp_peers",
                task_name="coop_register_patcher",
                patcher_args={"delete_all": "True"},
                py_func_name="remove_bgp_peers",
            ),
            # Configure BGP switch prefix limit
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="configure_bgp_switch_limit",
                task_name="coop_register_patcher",
                patcher_args={
                    "prefix_limit": unique_prefix_limit,
                },
                py_func_name="configure_bgp_switch_limit",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"update_peer_group_patcher_{peergroup_downlink_mimic_v6}",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": peergroup_downlink_mimic_v6,
                    "attributes_to_update_json": json.dumps(
                        {
                            "disable_ipv4_afi": "True",
                            "v4_over_v6_nexthop": "False",
                            "is_passive": "False",
                            "max_routes": per_peer_max_route_limit,
                            "is_confed_peer": is_downlink_peer_confed,
                        }
                    ),
                },
                py_func_name="configure_bgp_peer_group",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"update_peer_group_patcher_{peergroup_uplink_mimic_v6}",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": peergroup_uplink_mimic_v6,
                    "attributes_to_update_json": json.dumps(
                        {
                            "disable_ipv4_afi": "True",
                            "v4_over_v6_nexthop": "False",
                            "is_passive": "False",
                            "max_routes": per_peer_max_route_limit,
                            "is_confed_peer": is_uplink_peer_confed,
                        }
                    ),
                },
                py_func_name="configure_bgp_peer_group",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"add_peer_group_patcher_{peergroup_downlink_mimic_v4}",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": peergroup_downlink_mimic_v4,
                    "description": "BGP peering from SSW to FSW, IPv4 sessions",
                    "next_hop_self": "True",
                    "disable_ipv4_afi": "False",
                    "disable_ipv6_afi": "True",
                    "is_confed_peer": is_downlink_peer_confed,
                    "ingress_policy_name": route_map_downlink_ingress,
                    "egress_policy_name": route_map_downlink_egress,
                    "bgp_peer_timers_hold_time_seconds": "30",
                    "bgp_peer_timers_keep_alive_seconds": "10",
                    "bgp_peer_timers_out_delay_seconds": "7",
                    "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                    "peer_tag": downlink_peer_tag,
                    "max_routes": per_peer_max_route_limit,
                    "warning_only": "True",
                    "warning_limit": "0",
                    "link_bandwidth_bps": "auto",
                    "v4_over_v6_nexthop": "False",
                    "is_passive": "False",
                },
                py_func_name="add_peer_group_patcher",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"add_peer_group_patcher_{peergroup_uplink_mimic_v4}",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": peergroup_uplink_mimic_v4,
                    "description": "BGP peering from FAUU to EB, IPV6 sessions",
                    "next_hop_self": "True",
                    "disable_ipv4_afi": "False",
                    "disable_ipv6_afi": "False",
                    "is_confed_peer": is_uplink_peer_confed,
                    "ingress_policy_name": route_map_uplink_ingress,
                    "egress_policy_name": route_map_uplink_egress,
                    "bgp_peer_timers_hold_time_seconds": "30",
                    "bgp_peer_timers_keep_alive_seconds": "10",
                    "bgp_peer_timers_out_delay_seconds": "7",
                    "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                    "peer_tag": uplink_peer_tag,
                    "warning_only": "True",
                    "max_routes": per_peer_max_route_limit,
                    "warning_limit": "0",
                    "link_bandwidth_bps": "auto",
                    "v4_over_v6_nexthop": "true",
                    "is_passive": "False",
                    "receive_link_bandwidth": "1",
                },
                py_func_name="add_peer_group_patcher",
            ),
            create_coop_apply_patchers_task(
                hostnames=[device_name],
                config_name="bgpcpp",
            ),
            create_configure_parallel_bgp_peers_task(
                hostname=device_name,
                peer_configs=[
                    {
                        "configure_vlans_patcher_name": "configure_vlans_patcher_name_downlink",
                        "add_bgp_peers_patcher_name": "add_bgp_peers_patcher_name_downlink",
                        "config_json": json.dumps(
                            {
                                ixia_downlink_interface: [
                                    {
                                        "starting_ip": f"{ixia_downlink_ic_parent_network_v6}::10",
                                        "increment_ip": "0:0:0:0::2",
                                        "prefix_length": 127,
                                        "description": "Downlink IPv6 Peers",
                                        "peer_group_name": peergroup_downlink_mimic_v6,
                                        "num_sessions": downlink_peer_count,
                                        "remote_as_4_byte": remote_downlink_as_4byte,
                                        "remote_as_4_byte_step": remote_as_4_byte_step,
                                        "gateway_starting_ip": f"{ixia_downlink_ic_parent_network_v6}::11",
                                        "gateway_increment_ip": "0:0:0:0::2",
                                    },
                                    {
                                        "starting_ip": f"{ixia_downlink_ic_parent_network_v4}.0",
                                        "increment_ip": "0.0.0.2",
                                        "prefix_length": 31,
                                        "description": "Downlink IPv4 Peers",
                                        "peer_group_name": peergroup_downlink_mimic_v4,
                                        "num_sessions": downlink_peer_count,
                                        "remote_as_4_byte": remote_downlink_as_4byte,
                                        "remote_as_4_byte_step": remote_as_4_byte_step,
                                        "gateway_starting_ip": f"{ixia_downlink_ic_parent_network_v4}.1",
                                        "gateway_increment_ip": "0.0.0.2",
                                    },
                                ]
                            }
                        ),
                    }
                ],
            ),
            create_wait_for_agent_convergence_task(
                hostnames=[device_name],
            ),
            create_configure_parallel_bgp_peers_task(
                hostname=device_name,
                peer_configs=[
                    {
                        "configure_vlans_patcher_name": "configure_vlans_patcher_name_uplink",
                        "add_bgp_peers_patcher_name": "add_bgp_peers_patcher_name_uplink",
                        "config_json": json.dumps(
                            {
                                ixia_uplink_interface: [
                                    {
                                        "starting_ip": f"{ixia_uplink_ic_parent_network_v6}::10",
                                        "increment_ip": "0:0:0:0::2",
                                        "prefix_length": 127,
                                        "description": "Uplink IPv6 Peers",
                                        "peer_group_name": peergroup_uplink_mimic_v6,
                                        "num_sessions": uplink_peer_count,
                                        "remote_as_4_byte": remote_uplink_as_4byte,
                                        "remote_as_4_byte_step": remote_as_4_byte_step,
                                        "gateway_starting_ip": f"{ixia_uplink_ic_parent_network_v6}::11",
                                        "gateway_increment_ip": "0:0:0:0::2",
                                    },
                                    {
                                        "starting_ip": f"{ixia_uplink_ic_parent_network_v4}.0",
                                        "increment_ip": "0.0.0.2",
                                        "prefix_length": 31,
                                        "description": "Uplink IPv4 Peers",
                                        "peer_group_name": peergroup_uplink_mimic_v4,
                                        "num_sessions": uplink_peer_count,
                                        "remote_as_4_byte": remote_uplink_as_4byte,
                                        "remote_as_4_byte_step": remote_as_4_byte_step,
                                        "gateway_starting_ip": f"{ixia_uplink_ic_parent_network_v4}.1",
                                        "gateway_increment_ip": "0.0.0.2",
                                    },
                                ]
                            }
                        ),
                    }
                ],
            ),
            create_coop_apply_patchers_task(
                hostnames=[device_name],
            ),
        ],
        # Tasks to clean up after testing is complete
        teardown_tasks=[
            create_coop_unregister_patchers_task(device_name),
        ],
        # Configure IXIA ports for traffic generation
        basic_port_configs=[
            taac_types.BasicPortConfig(
                endpoint=f"{device_name}:{ixia_downlink_interface}",
                device_group_configs=[
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        multiplier=downlink_peer_count,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_downlink_ic_parent_network_v6}::11",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_downlink_ic_parent_network_v6}::10",
                            gateway_increment_ip="0:0:0:0::2",
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_downlink_as_4byte,
                            local_as_increment=1,
                            enable_4_byte_local_as=True,
                            is_confed=is_downlink_peer_confed == "True",
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=ixia_downlink_prefix_count_v6,
                                        prefix_length=64,
                                        starting_prefixes="9000:1::",
                                        prefix_step="0:0:0:0::0",
                                        bgp_communities=ixia_downlink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    ),
                                ),
                            ],
                        ),
                    ),
                    taac_types.DeviceGroupConfig(
                        device_group_index=1,
                        multiplier=downlink_peer_count,
                        v4_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_downlink_ic_parent_network_v4}.1",
                            increment_ip="0.0.0.2",
                            gateway_starting_ip=f"{ixia_downlink_ic_parent_network_v4}.0",
                            gateway_increment_ip="0.0.0.2",
                            mask=31,
                        ),
                        v4_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_downlink_as_4byte,
                            local_as_increment=1,
                            enable_4_byte_local_as=True,
                            is_confed=is_downlink_peer_confed == "True",
                            bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v4_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=ixia_downlink_prefix_count_v4,
                                        prefix_length=24,
                                        starting_prefixes="101.1.0.0",
                                        prefix_step="0.0.0.0",
                                        bgp_communities=ixia_downlink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                    ),
                                ),
                            ],
                        ),
                    ),
                ],
            ),
            taac_types.BasicPortConfig(
                endpoint=f"{device_name}:{ixia_uplink_interface}",
                device_group_configs=[
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        multiplier=uplink_peer_count,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_uplink_ic_parent_network_v6}::11",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_uplink_ic_parent_network_v6}::10",
                            gateway_increment_ip="0:0:0:0::2",
                            mask=127,
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_uplink_as_4byte,
                            local_as_increment=1,
                            enable_4_byte_local_as=True,
                            is_confed=is_uplink_peer_confed == "True",
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=ixia_uplink_prefix_count_v6,
                                        prefix_length=64,
                                        starting_prefixes="8000:1::",
                                        prefix_step="0:0:0:0::0",
                                        bgp_communities=ixia_uplink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    ),
                                ),
                            ],
                        ),
                    ),
                    taac_types.DeviceGroupConfig(
                        device_group_index=1,
                        multiplier=uplink_peer_count,
                        v4_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_uplink_ic_parent_network_v4}.1",
                            increment_ip="0.0.0.2",
                            gateway_starting_ip=f"{ixia_uplink_ic_parent_network_v4}.0",
                            gateway_increment_ip="0.0.0.2",
                            mask=31,
                        ),
                        v4_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_uplink_as_4byte,
                            local_as_increment=1,
                            enable_4_byte_local_as=True,
                            is_confed=is_uplink_peer_confed == "True",
                            bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v4_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=ixia_uplink_prefix_count_v4,
                                        prefix_length=24,
                                        starting_prefixes="201.1.0.0",
                                        prefix_step="0.0.0.0",
                                        bgp_communities=ixia_uplink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                    ),
                                ),
                            ],
                        ),
                    ),
                ],
            ),
        ],
        # Define traffic patterns between endpoints
        basic_traffic_item_configs=[
            taac_types.BasicTrafficItemConfig(
                name="V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
                bidirectional=True,
                merge_destinations=True,
                line_rate=10,
                src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        network_group_index=0,
                        device_group_index=0,
                    )
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        network_group_index=0,
                        device_group_index=0,
                    )
                ],
                traffic_type=ixia_types.TrafficType.IPV6,
                tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
            ),
            taac_types.BasicTrafficItemConfig(
                name="V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
                bidirectional=True,
                merge_destinations=True,
                line_rate=10,
                src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        network_group_index=0,
                        device_group_index=1,
                    )
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        network_group_index=0,
                        device_group_index=1,
                    )
                ],
                traffic_type=ixia_types.TrafficType.IPV4,
                tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
            ),
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        network_group_index=0,
                        device_group_index=0,
                    )
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        network_group_index=0,
                        device_group_index=0,
                    )
                ],
                name="TEST_RAW_BGP_CP_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=BGP_CP_TRAFFIC_PACKET_HEADERS,
            ),
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        network_group_index=0,
                        device_group_index=0,
                    )
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        network_group_index=0,
                        device_group_index=0,
                    )
                ],
                name="TEST_RAW_LLDP_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=LLDP_TRAFFIC_PACKET_HEADERS,
            ),
            taac_types.BasicTrafficItemConfig(
                name="BGP_PREFIX_TRAFFIC",
                bidirectional=False,
                merge_destinations=True,
                line_rate=10,
                src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        network_group_index=0,
                        device_group_index=0,
                    )
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        network_group_index=0,
                        device_group_index=0,
                    )
                ],
                traffic_type=ixia_types.TrafficType.IPV6,
                frame_size_settings=ixia_types.FrameSize(
                    type=ixia_types.FrameSizeType.CUSTOM_IMIX
                ),
            ),
            taac_types.BasicTrafficItemConfig(
                name="IPV6_TRAFFIC",
                bidirectional=False,
                merge_destinations=True,
                line_rate=10,
                src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        network_group_index=0,
                        device_group_index=0,
                    )
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        network_group_index=0,
                        device_group_index=0,
                    )
                ],
                traffic_type=ixia_types.TrafficType.IPV6,
                frame_size_settings=ixia_types.FrameSize(
                    type=ixia_types.FrameSizeType.CUSTOM_IMIX
                ),
            ),
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=0,
                    ),
                ],
                name="TEST_RAW_DHCP_V6_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=DHCP_V6_TRAFFIC_PACKET_HEADERS,
            ),
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=1,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=1,
                    ),
                ],
                name="TEST_RAW_DHCP_V4_DISCOVER_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=DHCP_V4_DISCOVER_TRAFFIC_PACKET_HEADERS,
            ),
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=1,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=1,
                    ),
                ],
                name="TEST_RAW_DHCP_V4_DISCOVER_TO_SERVER_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=DHCP_V4_DISCOVER_TO_SERVER_TRAFFIC_PACKET_HEADERS,
            ),
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=0,
                    ),
                ],
                name="TEST_RAW_ARP_REQUEST_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=ARP_REQUEST_TRAFFIC_PACKET_HEADERS,
            ),
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=0,
                    ),
                ],
                name="TEST_RAW_ARP_RESPONSE_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=ARP_RESPONSE_TRAFFIC_PACKET_HEADERS,
            ),
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=0,
                    ),
                ],
                name="TEST_RAW_ICMP_V6_REQUEST_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=ICMP_V6_REQUEST_TRAFFIC_PACKET_HEADERS,
            ),
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=0,
                    ),
                ],
                name="TEST_RAW_ICMP_V4_ECHO_REQUEST_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=ICMP_V4_ECHO_REQUEST_TRAFFIC_PACKET_HEADERS,
            ),
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=0,
                    ),
                ],
                name="TEST_RAW_ICMP_V4_ECHO_REPLY_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=ICMP_V4_ECHO_REPLY_TRAFFIC_PACKET_HEADERS,
            ),
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=0,
                    ),
                ],
                name="TEST_RAW_ICMP_V4_DEST_UNREACHABLE_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=ICMP_V4_DEST_UNREACHABLE_TRAFFIC_PACKET_HEADERS,
            ),
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=0,
                    ),
                ],
                name="TEST_RAW_ICMP_V4_TIME_EXCEEDED_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=ICMP_V4_TIME_EXCEEDED_TRAFFIC_PACKET_HEADERS,
            ),
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=0,
                    ),
                ],
                name="TEST_NEXTHOP_LIMIT_1_IPV6_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=HOP_LIMIT_1_IPV6_TRAFFIC_PACKET_HEADERS,
            ),
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=0,
                    ),
                ],
                name="TEST_NEXTHOP_LIMIT_0_IPV6_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=HOP_LIMIT_0_IPV6_TRAFFIC_PACKET_HEADERS,
            ),
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=1,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=1,
                    ),
                ],
                name="TEST_TTL_1_IPV4_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=TTL_1_IPV4_TRAFFIC_PACKET_HEADERS,
            ),
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=1,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=1,
                    ),
                ],
                name="TEST_TTL_0_IPV4_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=TTL_0_IPV4_TRAFFIC_PACKET_HEADERS,
            ),
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=0,
                    ),
                ],
                name="TEST_LACP_SLOW_TIMER_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=LACP_SLOW_TIMER_TRAFFIC_PACKET_HEADERS,
            ),
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=0,
                    ),
                ],
                name="TEST_NDP_NS_MULTICAST_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=NDP_NS_MULTICAST_TRAFFIC_PACKET_HEADERS,
            ),
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=0,
                    ),
                ],
                name="TEST_NDP_NA_MULTICAST_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=NDP_NA_MULTICAST_TRAFFIC_PACKET_HEADERS,
            ),
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=0,
                    ),
                ],
                name="TEST_NDP_RS_MULTICAST_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=NDP_RS_MULTICAST_TRAFFIC_PACKET_HEADERS,
            ),
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=0,
                    ),
                ],
                name="TEST_NDP_RA_MULTICAST_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=NDP_RA_MULTICAST_TRAFFIC_PACKET_HEADERS,
            ),
            # ICMPv6 Non-NDP with Link-Local Addresses
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=0,
                    ),
                ],
                name="TEST_ICMPV6_ECHO_REQUEST_LINK_LOCAL_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=ICMP_V6_ECHO_REQUEST_LINK_LOCAL_TRAFFIC_PACKET_HEADERS,
            ),
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=0,
                    ),
                ],
                name="TEST_ICMPV6_ECHO_REPLY_LINK_LOCAL_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=ICMP_V6_ECHO_REPLY_LINK_LOCAL_TRAFFIC_PACKET_HEADERS,
            ),
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=0,
                    ),
                ],
                name="TEST_ICMPV6_DEST_UNREACHABLE_LINK_LOCAL_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=ICMP_V6_DEST_UNREACHABLE_LINK_LOCAL_TRAFFIC_PACKET_HEADERS,
            ),
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=0,
                    ),
                ],
                name="TEST_ICMPV6_PACKET_TOO_BIG_LINK_LOCAL_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=ICMP_V6_PACKET_TOO_BIG_LINK_LOCAL_TRAFFIC_PACKET_HEADERS,
            ),
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=0,
                    ),
                ],
                name="TEST_ICMPV6_TIME_EXCEEDED_LINK_LOCAL_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=ICMP_V6_TIME_EXCEEDED_LINK_LOCAL_TRAFFIC_PACKET_HEADERS,
            ),
            # ICMPv6 Non-NDP with Global Addresses and DSCP 48
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=0,
                    ),
                ],
                name="TEST_ICMPV6_ECHO_REQUEST_GLOBAL_DSCP48_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=ICMP_V6_ECHO_REQUEST_GLOBAL_DSCP48_TRAFFIC_PACKET_HEADERS,
            ),
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=0,
                    ),
                ],
                name="TEST_ICMPV6_ECHO_REPLY_GLOBAL_DSCP48_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=ICMP_V6_ECHO_REPLY_GLOBAL_DSCP48_TRAFFIC_PACKET_HEADERS,
            ),
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=0,
                    ),
                ],
                name="TEST_ICMPV6_DEST_UNREACHABLE_GLOBAL_DSCP48_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=ICMP_V6_DEST_UNREACHABLE_GLOBAL_DSCP48_TRAFFIC_PACKET_HEADERS,
            ),
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=0,
                    ),
                ],
                name="TEST_ICMPV6_PACKET_TOO_BIG_GLOBAL_DSCP48_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=ICMP_V6_PACKET_TOO_BIG_GLOBAL_DSCP48_TRAFFIC_PACKET_HEADERS,
            ),
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=0,
                    ),
                ],
                name="TEST_ICMPV6_TIME_EXCEEDED_GLOBAL_DSCP48_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=ICMP_V6_TIME_EXCEEDED_GLOBAL_DSCP48_TRAFFIC_PACKET_HEADERS,
            ),
            # Burst traffic item for queue prioritization testing
            # High rate traffic to LOW queue (TTL=1 IPv4) to create drops
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=1,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=1,
                    ),
                ],
                name="BURST_LOW_QUEUE_TTL1_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=100000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=TTL_1_IPV4_TRAFFIC_PACKET_HEADERS,
            ),
            # High rate traffic to MID queue (DHCPv6) to create drops
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=0,
                    ),
                ],
                name="BURST_MID_QUEUE_DHCPV6_TRAFFIC",
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=100000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                packet_headers=DHCP_V6_TRAFFIC_PACKET_HEADERS,
            ),
        ],
        # Test execution playbooks defining test stages
        playbooks=_add_common_checks_to_npi_playbooks(
            [
                build_dctypef_npi_playbook(
                    name="1_test_longevity",
                    stages=[
                        create_steps_stage(
                            steps=[create_longevity_step(duration=240)],
                        )
                    ],
                ),
                build_dctypef_npi_playbook(
                    name="test_cpu_mid_queue_traffic",
                    traffic_items_to_start=[
                        "TEST_RAW_LLDP_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            steps=[create_longevity_step(duration=60)],
                        )
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[mid_queue],
                            no_discard_queues=[high_queue],
                            active_min_out_pps_per_queue={low_queue: 10},
                        )
                    ],
                ),
                build_dctypef_npi_playbook(
                    name="test_cpu_high_queue_traffic",
                    traffic_items_to_start=[
                        "TEST_RAW_BGP_CP_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            steps=[create_longevity_step(duration=60)],
                        )
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[high_queue],
                            no_discard_queues=[high_queue],
                            active_min_out_pps_per_queue={low_queue: 10},
                        )
                    ],
                ),
                # Queue Prioritization Test: Send burst traffic to LOW and MID queues
                # to create drops, while verifying no drops on HIGH queue (BGP_CP)
                # LOW queue: TTL=1 IPv4 traffic (punted for ICMP TTL exceeded)
                # MID queue: DHCPv6 traffic
                # HIGH queue: BGP CP traffic
                build_dctypef_npi_playbook(
                    name="test_queue_prioritization_high_queue_no_drops",
                    traffic_items_to_start=[
                        "BURST_LOW_QUEUE_TTL1_TRAFFIC",
                        "BURST_MID_QUEUE_DHCPV6_TRAFFIC",
                        "TEST_RAW_BGP_CP_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            steps=[create_longevity_step(duration=60)],
                        )
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[low_queue, mid_queue, high_queue],
                            no_discard_queues=[high_queue],
                        )
                    ],
                ),
                build_dctypef_npi_playbook(
                    name="test_cpu_mid_queue_warmboot",
                    traffic_items_to_start=[
                        "TEST_RAW_LLDP_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    postchecks=[
                        create_service_restart_check(
                            services=SERVICES_TO_MONITOR_DURING_AGENT_RESTART
                        ),
                    ],
                    stages=[
                        create_steps_stage(
                            stage_id="test_cpu_mid_queue_warmboot",
                            steps=[
                                create_longevity_step(duration=60),
                                create_service_interruption_step(
                                    service=Service.AGENT,
                                    step_id="do_warmboot",
                                ),
                                create_service_convergence_step(
                                    step_id="wait_for_agent_configured_state",
                                ),
                                create_longevity_step(duration=60),
                            ],
                        ),
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[mid_queue],
                            no_discard_queues=[high_queue],
                            post_snapshot_checkpoint_id="stage.test_cpu_mid_queue_warmboot.step.do_warmboot.start",
                        ),
                        create_cpu_queue_snapshot_check(
                            active_queues=[mid_queue],
                            no_discard_queues=[high_queue],
                            pre_snapshot_checkpoint_id="stage.test_cpu_mid_queue_warmboot.step.wait_for_agent_configured_state.end",
                        ),
                    ],
                ),
                build_dctypef_npi_playbook(
                    name="test_cpu_high_queue_warmboot",
                    traffic_items_to_start=[
                        "TEST_RAW_BGP_CP_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    postchecks=[
                        create_service_restart_check(
                            services=SERVICES_TO_MONITOR_DURING_AGENT_RESTART
                        ),
                    ],
                    stages=[
                        create_steps_stage(
                            stage_id="test_cpu_high_queue_warmboot",
                            steps=[
                                create_longevity_step(duration=60),
                                create_service_interruption_step(
                                    service=Service.AGENT,
                                    step_id="do_warmboot",
                                ),
                                create_service_convergence_step(
                                    step_id="wait_for_agent_configured_state",
                                ),
                                create_longevity_step(duration=60),
                            ],
                        ),
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[high_queue],
                            no_discard_queues=[high_queue],
                            post_snapshot_checkpoint_id="stage.test_cpu_high_queue_warmboot.step.do_warmboot.start",
                        ),
                        create_cpu_queue_snapshot_check(
                            active_queues=[high_queue],
                            no_discard_queues=[high_queue],
                            pre_snapshot_checkpoint_id="stage.test_cpu_high_queue_warmboot.step.wait_for_agent_configured_state.end",
                        ),
                    ],
                ),
                build_dctypef_npi_playbook(
                    name="test_icmp_v6_request_traffic_punted_to_cpu_mid_queue",
                    traffic_items_to_start=[
                        "TEST_RAW_ICMP_V6_REQUEST_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            steps=[create_longevity_step(duration=60)],
                        )
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[mid_queue],
                            no_discard_queues=[high_queue],
                            active_min_out_pps_per_queue={low_queue: 10},
                        )
                    ],
                ),
                build_dctypef_npi_playbook(
                    name="test_icmp_v4_echo_request_traffic_punted_to_cpu_mid_queue",
                    traffic_items_to_start=[
                        "TEST_RAW_ICMP_V4_ECHO_REQUEST_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            steps=[create_longevity_step(duration=60)],
                        )
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[mid_queue],
                            no_discard_queues=[high_queue],
                            active_min_out_pps_per_queue={low_queue: 10},
                        )
                    ],
                ),
                build_dctypef_npi_playbook(
                    name="test_icmp_v4_echo_reply_traffic_punted_to_cpu_mid_queue",
                    traffic_items_to_start=[
                        "TEST_RAW_ICMP_V4_ECHO_REPLY_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            steps=[create_longevity_step(duration=60)],
                        )
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[mid_queue],
                            no_discard_queues=[high_queue],
                            active_min_out_pps_per_queue={low_queue: 10},
                        )
                    ],
                ),
                build_dctypef_npi_playbook(
                    name="test_icmp_v4_dest_unreachable_traffic_punted_to_cpu_mid_queue",
                    traffic_items_to_start=[
                        "TEST_RAW_ICMP_V4_DEST_UNREACHABLE_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            steps=[create_longevity_step(duration=60)],
                        )
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[mid_queue],
                            no_discard_queues=[high_queue],
                            active_min_out_pps_per_queue={low_queue: 10},
                        )
                    ],
                ),
                build_dctypef_npi_playbook(
                    name="test_icmp_v4_time_exceeded_traffic_punted_to_cpu_mid_queue",
                    traffic_items_to_start=[
                        "TEST_RAW_ICMP_V4_TIME_EXCEEDED_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            steps=[create_longevity_step(duration=60)],
                        )
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[mid_queue],
                            no_discard_queues=[high_queue],
                            active_min_out_pps_per_queue={low_queue: 10},
                        )
                    ],
                ),
                build_dctypef_npi_playbook(
                    name="test_dhcp_v6_traffic_punted_to_cpu_mid_queue",
                    traffic_items_to_start=[
                        "TEST_RAW_DHCP_V6_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            steps=[create_longevity_step(duration=60)],
                        )
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[mid_queue],
                            no_discard_queues=[high_queue],
                            active_min_out_pps_per_queue={low_queue: 10},
                        )
                    ],
                ),
                build_dctypef_npi_playbook(
                    name="test_dhcp_v4_discover_traffic_punted_to_cpu_mid_queue",
                    traffic_items_to_start=[
                        "TEST_RAW_DHCP_V4_DISCOVER_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            steps=[create_longevity_step(duration=60)],
                        )
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[mid_queue],
                            no_discard_queues=[high_queue],
                            active_min_out_pps_per_queue={low_queue: 10},
                        )
                    ],
                ),
                build_dctypef_npi_playbook(
                    name="test_dhcp_v4_discover_to_server_traffic_punted_to_cpu_mid_queue",
                    traffic_items_to_start=[
                        "TEST_RAW_DHCP_V4_DISCOVER_TO_SERVER_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            steps=[create_longevity_step(duration=60)],
                        )
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[mid_queue],
                            no_discard_queues=[high_queue],
                            active_min_out_pps_per_queue={low_queue: 10},
                        )
                    ],
                ),
                build_dctypef_npi_playbook(
                    name="test_lldp_traffic_punted_to_cpu_mid_queue",
                    traffic_items_to_start=[
                        "TEST_RAW_LLDP_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            steps=[create_longevity_step(duration=60)],
                        )
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[mid_queue],
                            no_discard_queues=[high_queue],
                            active_min_out_pps_per_queue={low_queue: 10},
                        )
                    ],
                ),
                build_dctypef_npi_playbook(
                    name="test_bgp_cp_traffic_punted_to_cpu_high_queue",
                    traffic_items_to_start=[
                        "TEST_RAW_BGP_CP_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            steps=[create_longevity_step(duration=60)],
                        )
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[high_queue],
                            no_discard_queues=[high_queue],
                            active_min_out_pps_per_queue={low_queue: 10},
                        )
                    ],
                ),
                build_dctypef_npi_playbook(
                    name="test_lacp_traffic_punted_to_cpu_high_queue",
                    traffic_items_to_start=[
                        "TEST_LACP_SLOW_TIMER_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            steps=[create_longevity_step(duration=60)],
                        )
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[high_queue],
                            no_discard_queues=[high_queue],
                            active_min_out_pps_per_queue={low_queue: 10},
                        )
                    ],
                ),
                build_dctypef_npi_playbook(
                    name="test_nexthop_limit_1_punted_to_cpu_low_queue",
                    traffic_items_to_start=[
                        "TEST_NEXTHOP_LIMIT_1_IPV6_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            steps=[create_longevity_step(duration=60)],
                        )
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[low_queue],
                            no_discard_queues=[mid_queue, high_queue],
                            active_min_out_pps_per_queue={low_queue: 10},
                        )
                    ],
                ),
                build_dctypef_npi_playbook(
                    name="test_nexthop_limit_0_not_punted_to_cpu",
                    traffic_items_to_start=[
                        "TEST_NEXTHOP_LIMIT_0_IPV6_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            steps=[create_longevity_step(duration=60)],
                        )
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[],
                            no_discard_queues=[low_queue, mid_queue, high_queue],
                            active_min_out_pps_per_queue={low_queue: 10},
                        )
                    ],
                ),
                build_dctypef_npi_playbook(
                    name="test_ttl_1_ipv4_traffic_punted_to_cpu_low_queue",
                    traffic_items_to_start=[
                        "TEST_TTL_1_IPV4_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            steps=[create_longevity_step(duration=30)],
                        )
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[low_queue],
                            no_discard_queues=[mid_queue, high_queue],
                            active_min_out_pps_per_queue={low_queue: 10},
                        )
                    ],
                ),
                build_dctypef_npi_playbook(
                    name="test_ttl_0_ipv4_traffic_not_punted_to_cpu",
                    traffic_items_to_start=[
                        "TEST_TTL_0_IPV4_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            steps=[create_longevity_step(duration=30)],
                        )
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[],
                            no_discard_queues=[low_queue, mid_queue, high_queue],
                            active_min_out_pps_per_queue={low_queue: 10},
                        )
                    ],
                ),
                build_dctypef_npi_playbook(
                    name="test_arp_traffic_punted_to_cpu_high_queue",
                    traffic_items_to_start=[
                        "TEST_RAW_ARP_REQUEST_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            stage_id="test_arp_traffic_punted_to_cpu_high_queue",
                            steps=[
                                create_longevity_step(duration=60),
                            ],
                        ),
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[high_queue],
                            no_discard_queues=[high_queue],
                            active_min_out_pps_per_queue={high_queue: 10},
                        ),
                    ],
                ),
                build_dctypef_npi_playbook(
                    name="test_arp_response_traffic_punted_to_cpu_high_queue",
                    traffic_items_to_start=[
                        "TEST_RAW_ARP_RESPONSE_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            stage_id="test_arp_response_traffic_punted_to_cpu_high_queue",
                            steps=[
                                create_longevity_step(duration=60),
                            ],
                        ),
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[high_queue],
                            no_discard_queues=[high_queue],
                            active_min_out_pps_per_queue={high_queue: 10},
                        ),
                    ],
                ),
                build_dctypef_npi_playbook(
                    name="test_ndp_ns_multicast_traffic_punted_to_cpu_high_queue",
                    traffic_items_to_start=[
                        "TEST_NDP_NS_MULTICAST_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            stage_id="test_ndp_ns_multicast_traffic_punted_to_cpu_high_queue",
                            steps=[
                                create_longevity_step(duration=60),
                            ],
                        ),
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[high_queue],
                            no_discard_queues=[high_queue],
                            active_min_out_pps_per_queue={high_queue: 10},
                        ),
                    ],
                ),
                build_dctypef_npi_playbook(
                    name="test_ndp_na_multicast_traffic_punted_to_cpu_high_queue",
                    traffic_items_to_start=[
                        "TEST_NDP_NA_MULTICAST_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            stage_id="test_ndp_na_multicast_traffic_punted_to_cpu_high_queue",
                            steps=[
                                create_longevity_step(duration=60),
                            ],
                        ),
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[high_queue],
                            no_discard_queues=[high_queue],
                            active_min_out_pps_per_queue={high_queue: 10},
                        ),
                    ],
                ),
                build_dctypef_npi_playbook(
                    name="test_ndp_rs_multicast_traffic_punted_to_cpu_high_queue",
                    traffic_items_to_start=[
                        "TEST_NDP_RS_MULTICAST_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            stage_id="test_ndp_rs_multicast_traffic_punted_to_cpu_high_queue",
                            steps=[
                                create_longevity_step(duration=60),
                            ],
                        ),
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[high_queue],
                            no_discard_queues=[high_queue],
                            active_min_out_pps_per_queue={high_queue: 10},
                        ),
                    ],
                ),
                build_dctypef_npi_playbook(
                    name="test_ndp_ra_multicast_traffic_punted_to_cpu_high_queue",
                    traffic_items_to_start=[
                        "TEST_NDP_RA_MULTICAST_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            stage_id="test_ndp_ra_multicast_traffic_punted_to_cpu_high_queue",
                            steps=[
                                create_longevity_step(duration=60),
                            ],
                        ),
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[high_queue],
                            no_discard_queues=[high_queue],
                            active_min_out_pps_per_queue={high_queue: 10},
                        ),
                    ],
                ),
                # ICMPv6 Non-NDP with Link-Local Addresses - Punted to MID queue
                build_dctypef_npi_playbook(
                    name="test_icmpv6_echo_request_link_local_traffic_punted_to_cpu_mid_queue",
                    traffic_items_to_start=[
                        "TEST_ICMPV6_ECHO_REQUEST_LINK_LOCAL_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            stage_id="test_icmpv6_echo_request_link_local_traffic_punted_to_cpu_mid_queue",
                            steps=[
                                create_longevity_step(duration=60),
                            ],
                        ),
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[mid_queue],
                            no_discard_queues=[high_queue],
                            active_min_out_pps_per_queue={low_queue: 10},
                        ),
                    ],
                ),
                build_dctypef_npi_playbook(
                    name="test_icmpv6_echo_reply_link_local_traffic_punted_to_cpu_mid_queue",
                    traffic_items_to_start=[
                        "TEST_ICMPV6_ECHO_REPLY_LINK_LOCAL_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            stage_id="test_icmpv6_echo_reply_link_local_traffic_punted_to_cpu_mid_queue",
                            steps=[
                                create_longevity_step(duration=60),
                            ],
                        ),
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[mid_queue],
                            no_discard_queues=[high_queue],
                            active_min_out_pps_per_queue={low_queue: 10},
                        ),
                    ],
                ),
                build_dctypef_npi_playbook(
                    name="test_icmpv6_dest_unreachable_link_local_traffic_punted_to_cpu_mid_queue",
                    traffic_items_to_start=[
                        "TEST_ICMPV6_DEST_UNREACHABLE_LINK_LOCAL_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            stage_id="test_icmpv6_dest_unreachable_link_local_traffic_punted_to_cpu_mid_queue",
                            steps=[
                                create_longevity_step(duration=60),
                            ],
                        ),
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[mid_queue],
                            no_discard_queues=[high_queue],
                            active_min_out_pps_per_queue={low_queue: 10},
                        ),
                    ],
                ),
                build_dctypef_npi_playbook(
                    name="test_icmpv6_packet_too_big_link_local_traffic_punted_to_cpu_mid_queue",
                    traffic_items_to_start=[
                        "TEST_ICMPV6_PACKET_TOO_BIG_LINK_LOCAL_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            stage_id="test_icmpv6_packet_too_big_link_local_traffic_punted_to_cpu_mid_queue",
                            steps=[
                                create_longevity_step(duration=60),
                            ],
                        ),
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[mid_queue],
                            no_discard_queues=[high_queue],
                            active_min_out_pps_per_queue={low_queue: 10},
                        ),
                    ],
                ),
                build_dctypef_npi_playbook(
                    name="test_icmpv6_time_exceeded_link_local_traffic_punted_to_cpu_mid_queue",
                    traffic_items_to_start=[
                        "TEST_ICMPV6_TIME_EXCEEDED_LINK_LOCAL_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            stage_id="test_icmpv6_time_exceeded_link_local_traffic_punted_to_cpu_mid_queue",
                            steps=[
                                create_longevity_step(duration=60),
                            ],
                        ),
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[mid_queue],
                            no_discard_queues=[high_queue],
                            active_min_out_pps_per_queue={low_queue: 10},
                        ),
                    ],
                ),
                # ICMPv6 Non-NDP with Global Addresses and DSCP 48 - Punted to MID queue
                build_dctypef_npi_playbook(
                    name="test_icmpv6_echo_request_global_dscp48_traffic_punted_to_cpu_mid_queue",
                    traffic_items_to_start=[
                        "TEST_ICMPV6_ECHO_REQUEST_GLOBAL_DSCP48_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            stage_id="test_icmpv6_echo_request_global_dscp48_traffic_punted_to_cpu_mid_queue",
                            steps=[
                                create_longevity_step(duration=60),
                            ],
                        ),
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[mid_queue],
                            no_discard_queues=[high_queue],
                            active_min_out_pps_per_queue={low_queue: 10},
                        ),
                    ],
                ),
                build_dctypef_npi_playbook(
                    name="test_icmpv6_echo_reply_global_dscp48_traffic_punted_to_cpu_mid_queue",
                    traffic_items_to_start=[
                        "TEST_ICMPV6_ECHO_REPLY_GLOBAL_DSCP48_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            stage_id="test_icmpv6_echo_reply_global_dscp48_traffic_punted_to_cpu_mid_queue",
                            steps=[
                                create_longevity_step(duration=60),
                            ],
                        ),
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[mid_queue],
                            no_discard_queues=[high_queue],
                            active_min_out_pps_per_queue={low_queue: 10},
                        ),
                    ],
                ),
                build_dctypef_npi_playbook(
                    name="test_icmpv6_dest_unreachable_global_dscp48_traffic_punted_to_cpu_mid_queue",
                    traffic_items_to_start=[
                        "TEST_ICMPV6_DEST_UNREACHABLE_GLOBAL_DSCP48_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            stage_id="test_icmpv6_dest_unreachable_global_dscp48_traffic_punted_to_cpu_mid_queue",
                            steps=[
                                create_longevity_step(duration=60),
                            ],
                        ),
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[mid_queue],
                            no_discard_queues=[high_queue],
                            active_min_out_pps_per_queue={low_queue: 10},
                        ),
                    ],
                ),
                build_dctypef_npi_playbook(
                    name="test_icmpv6_packet_too_big_global_dscp48_traffic_punted_to_cpu_mid_queue",
                    traffic_items_to_start=[
                        "TEST_ICMPV6_PACKET_TOO_BIG_GLOBAL_DSCP48_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            stage_id="test_icmpv6_packet_too_big_global_dscp48_traffic_punted_to_cpu_mid_queue",
                            steps=[
                                create_longevity_step(duration=60),
                            ],
                        ),
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[mid_queue],
                            no_discard_queues=[high_queue],
                            active_min_out_pps_per_queue={low_queue: 10},
                        ),
                    ],
                ),
                build_dctypef_npi_playbook(
                    name="test_icmpv6_time_exceeded_global_dscp48_traffic_punted_to_cpu_mid_queue",
                    traffic_items_to_start=[
                        "TEST_ICMPV6_TIME_EXCEEDED_GLOBAL_DSCP48_TRAFFIC",
                        "BGP_PREFIX_TRAFFIC",
                    ],
                    stages=[
                        create_steps_stage(
                            stage_id="test_icmpv6_time_exceeded_global_dscp48_traffic_punted_to_cpu_mid_queue",
                            steps=[
                                create_longevity_step(duration=60),
                            ],
                        ),
                    ],
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[mid_queue],
                            no_discard_queues=[high_queue],
                            active_min_out_pps_per_queue={low_queue: 10},
                        ),
                    ],
                ),
                build_dctypef_npi_playbook(
                    postchecks=[
                        create_ixia_packet_loss_check(clear_traffic_stats=True),
                        create_service_restart_check(
                            services=SERVICES_TO_MONITOR_DURING_AGENT_RESTART
                        ),
                    ],
                    traffic_items_to_start=["BGP_PREFIX_TRAFFIC"],
                    name="test_fboss_cpu_remote_subnet_unh",
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[low_queue],
                            no_discard_queues=[mid_queue, high_queue],
                            pre_snapshot_checkpoint_id="stage.test_fboss_cpu_remote_subnet_unh.step.disable_next_hop_egress_port.end",
                            post_snapshot_checkpoint_id="stage.test_fboss_cpu_remote_subnet_unh.step.enable_next_hop_egress_port.start",
                        ),
                        create_cpu_queue_snapshot_check(
                            active_queues=[],
                            no_discard_queues=[high_queue],
                            pre_snapshot_checkpoint_id="stage.test_fboss_cpu_remote_subnet_unh.step.enable_next_hop_egress_port.end",
                        ),
                    ],
                    stages=[
                        create_steps_stage(
                            stage_id="test_fboss_cpu_remote_subnet_unh",
                            steps=[
                                create_custom_step(
                                    params_dict={
                                        "custom_step_name": "register_cpu_queue_static_route_patcher",
                                        "static_route_mask": 64,
                                        "next_hop_egress_port": ixia_downlink_interface,
                                        "patcher_name": "cpu_queue_static_route_patcher",
                                    },
                                ),
                                create_service_interruption_step(service=Service.AGENT),
                                create_service_convergence_step(),
                                create_interface_flap_step(
                                    enable=False,
                                    interfaces=[ixia_downlink_interface],
                                    interface_flap_method=4,  # SSH_PORT_STATE_CHANGE
                                    step_id="disable_next_hop_egress_port",
                                ),
                                create_longevity_step(duration=60),
                                create_interface_flap_step(
                                    enable=True,
                                    interfaces=[ixia_downlink_interface],
                                    interface_flap_method=4,  # SSH_PORT_STATE_CHANGE
                                    step_id="enable_next_hop_egress_port",
                                ),
                                create_longevity_step(duration=60),
                                create_unregister_patcher_step(
                                    patcher_name="cpu_queue_static_route_patcher",
                                ),
                                create_service_interruption_step(service=Service.AGENT),
                                create_service_convergence_step(),
                            ],
                        )
                    ],
                ),
                build_dctypef_npi_playbook(
                    postchecks=[
                        create_ixia_packet_loss_check(clear_traffic_stats=True),
                        create_service_restart_check(
                            services=SERVICES_TO_MONITOR_DURING_AGENT_RESTART
                        ),
                    ],
                    traffic_items_to_start=["BGP_PREFIX_TRAFFIC"],
                    name="test_fboss_cpu_remote_subnet_128_unh",
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[low_queue],
                            no_discard_queues=[mid_queue, high_queue],
                            pre_snapshot_checkpoint_id="stage.test_fboss_cpu_remote_subnet_128_unh.step.disable_next_hop_egress_port.end",
                            post_snapshot_checkpoint_id="stage.test_fboss_cpu_remote_subnet_128_unh.step.enable_next_hop_egress_port.start",
                        ),
                        create_cpu_queue_snapshot_check(
                            active_queues=[],
                            no_discard_queues=[high_queue],
                            pre_snapshot_checkpoint_id="stage.test_fboss_cpu_remote_subnet_128_unh.step.enable_next_hop_egress_port.end",
                        ),
                    ],
                    stages=[
                        create_steps_stage(
                            stage_id="test_fboss_cpu_remote_subnet_128_unh",
                            steps=[
                                create_custom_step(
                                    params_dict={
                                        "custom_step_name": "register_cpu_queue_static_route_patcher",
                                        "static_route_mask": 128,
                                        "next_hop_egress_port": ixia_downlink_interface,
                                        "patcher_name": "cpu_queue_static_route_patcher",
                                    },
                                ),
                                create_service_interruption_step(service=Service.AGENT),
                                create_service_convergence_step(),
                                create_interface_flap_step(
                                    enable=False,
                                    interfaces=[ixia_downlink_interface],
                                    interface_flap_method=4,  # SSH_PORT_STATE_CHANGE
                                    step_id="disable_next_hop_egress_port",
                                ),
                                create_longevity_step(duration=60),
                                create_interface_flap_step(
                                    enable=True,
                                    interfaces=[ixia_downlink_interface],
                                    interface_flap_method=4,  # SSH_PORT_STATE_CHANGE
                                    step_id="enable_next_hop_egress_port",
                                ),
                                create_longevity_step(duration=60),
                                create_unregister_patcher_step(
                                    patcher_name="cpu_queue_static_route_patcher",
                                ),
                                create_service_interruption_step(service=Service.AGENT),
                                create_service_convergence_step(),
                            ],
                        )
                    ],
                ),
                build_dctypef_npi_playbook(
                    postchecks=[
                        create_ixia_packet_loss_check(clear_traffic_stats=True),
                        create_service_restart_check(
                            services=SERVICES_TO_MONITOR_DURING_AGENT_RESTART
                        ),
                    ],
                    traffic_items_to_start=["IPV6_TRAFFIC"],
                    name="test_fboss_cpu_dir_conn_host_unh",
                    snapshot_checks=[
                        create_cpu_queue_snapshot_check(
                            active_queues=[low_queue],
                            no_discard_queues=[mid_queue, high_queue],
                            pre_snapshot_checkpoint_id="stage.test_fboss_cpu_dir_conn_host_unh.step.disable_next_hop_egress_port.end",
                            post_snapshot_checkpoint_id="stage.test_fboss_cpu_dir_conn_host_unh.step.enable_next_hop_egress_port.start",
                        ),
                        create_cpu_queue_snapshot_check(
                            active_queues=[],
                            no_discard_queues=[high_queue],
                            pre_snapshot_checkpoint_id="stage.test_fboss_cpu_dir_conn_host_unh.step.enable_next_hop_egress_port.end",
                        ),
                    ],
                    stages=[
                        create_steps_stage(
                            stage_id="test_fboss_cpu_dir_conn_host_unh",
                            steps=[
                                create_custom_step(
                                    params_dict={
                                        "custom_step_name": "register_cpu_queue_static_route_patcher",
                                        "static_route_mask": 64,
                                        "next_hop_egress_port": ixia_downlink_interface,
                                        "patcher_name": "cpu_queue_static_route_patcher",
                                    },
                                ),
                                create_service_interruption_step(service=Service.AGENT),
                                create_service_convergence_step(),
                                create_interface_flap_step(
                                    enable=False,
                                    interfaces=[ixia_downlink_interface],
                                    interface_flap_method=4,  # SSH_PORT_STATE_CHANGE
                                    step_id="disable_next_hop_egress_port",
                                ),
                                create_longevity_step(duration=60),
                                create_interface_flap_step(
                                    enable=True,
                                    interfaces=[ixia_downlink_interface],
                                    interface_flap_method=4,  # SSH_PORT_STATE_CHANGE
                                    step_id="enable_next_hop_egress_port",
                                ),
                                create_longevity_step(duration=60),
                                create_unregister_patcher_step(
                                    patcher_name="cpu_queue_static_route_patcher",
                                ),
                                create_service_interruption_step(service=Service.AGENT),
                                create_service_convergence_step(),
                            ],
                        )
                    ],
                ),
                *TEST_51T_NPI_DCTYPEF_PLAYBOOKS,
            ],
            unique_prefix_limit=unique_prefix_limit,
        ),
    )
