# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""BGP++ constant attribute storage verification TestConfig.

Verifies that BGP++ memory usage depends ONLY on the number of unique
route attributes (AS path, communities, ext-communities), NOT on how the
same routes are distributed across peers. Maintains a constant total path
count (default 400K) while sweeping EBGP peer counts (e.g. 8, 16, 32, 64,
128) — memory must stay flat across iterations.

Full test design (constant-total-paths approach, expected memory profile)
is in the in-module string literal below.
"""

from typing import List

from ixia.ixia import types as ixia_types
from taac.playbooks.playbook_definitions import (
    create_test_constant_attribute_storage_playbook,
)
from taac.task_definitions import (
    create_coop_apply_patchers_task,
    create_coop_register_patcher_task,
    create_coop_unregister_patchers_task,
    create_run_commands_on_shell_task,
    create_scp_file_template_task,
    create_wait_for_agent_convergence_task,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import Endpoint, TestConfig


"""
Test Case: Constant Total Paths Test

Objective:
Verify that BGP++ memory usage depends ONLY on unique attributes,
NOT on how routes are distributed across peers.

Test Design - Constant Total Paths:
    Maintains a CONSTANT total number of ingress paths (default: 400K) across
    all test iterations by adjusting prefix count per peer:

    Example with constant_total_paths=400K:
        8 peers   x 50,000 prefixes = 400K paths
        16 peers  x 25,000 prefixes = 400K paths
        32 peers  x 12,500 prefixes = 400K paths
        64 peers  x 6,250 prefixes  = 400K paths
        128 peers x  3,125 prefixes  = 400K paths

    All 400K paths use attributes from the SAME limited pools:
        - 100 unique AS paths
        - 100 unique communities
        - 100 unique extended communities

    Expected Result:
        Memory should remain CONSTANT across all iterations since:
        - Total paths are constant (400K)
        - Unique attribute pools are constant
        - Only the distribution across peers changes

    This proves BGP++ memory depends on unique attributes, not peer count!

Execution:
1. EBGP Peer Configuration:
   - Configure varying numbers of EBGP peers (e.g., 8, 16, 32, 64, 128)
   - Calculate prefix count per peer = constant_total_paths / peer_count
   - This keeps total ingress paths constant across all iterations

2. Route Advertisement:
   - Each EBGP peer advertises its calculated number of prefixes
   - All routes use attributes from the same constant pools
   - Wait for BGP convergence and stabilization

3. Metrics Collection:
   - Collect peak CPU and memory usage
   - Collect BGP attribute statistics
   - Verify memory remains constant across iterations

4. Repeat for Each Peer Count:
   - Test with different numbers of EBGP peers: [8, 16, 32, 64, 128]
   - Each iteration maintains the same total paths (400K)
   - Memory should be constant since unique attributes are constant
"""


def test_config_to_verify_constant_attribute_storage(
    test_config_name,
    device_name,
    peergroup_ibgp_v6,
    peergroup_ebgp_v6,
    peergroup_ibgp_v4,
    peergroup_ebgp_v4,
    ixia_interface_mimic_ebgp,
    ixia_interface_mimic_ibgp,
    ibgp_remote_as,
    ebgp_remote_as,
    ebgp_peer_counts: List[int],  # [1, 4, 16, 64, 128]
    unqiue_prefix_limit,
    total_path_limit,
    ixia_ebgp_ic_parent_network_v6,
    ixia_ibgp_ic_parent_network_v6,
    ixia_ebgp_ic_parent_network_v4,
    ixia_ibgp_ic_parent_network_v4,
    ixia_ebgp_communities,
    ixia_ibgp_communities,
    ebgp_ingress_policy_name,
    ebgp_egress_policy_name,
    ibgp_ingress_policy_name,
    ibgp_egress_policy_name,
    prefix_counts: List[int],  # [10000, 20000, 30000, 40000, 50000]
    ibgp_peer_count: int = 1000,  # Constant IBGP peer count for all test configurations
):
    """Build the BGP++ constant-attribute-storage verification TestConfig.

    Wires up COOP patcher tasks (unregister/register/apply, scp systemd
    bgpd service template, restart bgpd, agent convergence wait), then
    runs `create_test_constant_attribute_storage_playbook` which sweeps
    `ebgp_peer_counts` while adjusting prefix-per-peer to keep total paths
    constant. Memory should remain CONSTANT across iterations because the
    unique-attribute pool (100 AS paths × 100 communities × 100 ext-comms)
    is fixed — proving BGP++ memory depends on attribute uniqueness, not
    peer distribution.

    Args:
        test_config_name: Final name of the produced TestConfig.
        device_name: DUT hostname (FBOSS EBB).
        peergroup_* / ixia_interface_mimic_* / *_remote_as / ixia_*_communities:
            BGP peer-group and IXIA peer wiring (v4 + v6 for IBGP and EBGP).
        ebgp_peer_counts: List of EBGP peer counts to sweep (e.g. 1, 4, 16,
            64, 128). The playbook holds total ingress paths constant by
            adjusting per-peer prefix count.
        unqiue_prefix_limit / total_path_limit: Route scale knobs (historical
            typo in `unqiue_*` preserved).
        ixia_*_ic_parent_network_v6/v4: Parent networks for IXIA-side prefix
            generation.
        *_ingress_policy_name / *_egress_policy_name: COOP BGP policy names.
        prefix_counts: List of base prefix counts (informational; actual
            per-peer count is derived from constant-total-paths invariant).
        ibgp_peer_count: Constant IBGP peer count for all test iterations.

    Returns:
        TestConfig: The constant-attribute-storage TestConfig, registered
        via `BGP_PLUS_PLUS_VERIFY_CONSTANT_ATTRIBUTE_STORAGE_TEST_CONFIG` and
        re-exported through `testconfigs.routing.ebb`.
    """
    return TestConfig(
        name=test_config_name,
        basset_pool="dne.test",
        skip_ixia_protocol_verification=True,
        endpoints=[
            Endpoint(
                name=device_name,
                dut=True,
                ixia_ports=[
                    ixia_interface_mimic_ebgp,
                    ixia_interface_mimic_ibgp,
                ],
            ),
        ],
        setup_tasks=[
            create_coop_unregister_patchers_task(device_name),
            create_scp_file_template_task(
                hostname=device_name,
                remote_path="/etc/packages/neteng-fboss-bgpd/current/bgpd.service",
                file_template="systemd_bgp_service",
                template_params={
                    "max_rss_size": "10",
                    "bgp_policy_cache_size": "200000",
                    "platform": "dev",
                },
            ),
            create_run_commands_on_shell_task(
                hostname=device_name,
                cmds=[
                    "systemctl restart bgpd",
                    "systemctl daemon-reload",
                ],
            ),
            # Remove all the bgp peers present in the device first
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="a_remove_bgp_peers",
                task_name="remove_bgp_peers",
                patcher_args={"delete_all": "True"},
                py_func_name="remove_bgp_peers",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="configure_bgp_switch_limit",
                task_name="configure_bgp_switch_limit",
                patcher_args={
                    "prefix_limit": str(unqiue_prefix_limit),
                    "total_path_limit": str(total_path_limit),
                },
                py_func_name="configure_bgp_switch_limit",
            ),
            create_coop_apply_patchers_task(
                hostnames=[device_name],
                config_name="bgpcpp",
            ),
            create_wait_for_agent_convergence_task([device_name]),
            create_coop_apply_patchers_task(
                hostnames=[device_name],
                config_name="bgpcpp",
            ),
            create_wait_for_agent_convergence_task([device_name]),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"add_peer_group_patcher_{peergroup_ebgp_v6}",
                task_name="add_peer_group_patcher",
                patcher_args={
                    "name": peergroup_ebgp_v6,
                    "description": "BGP V6 peering for EBGP",
                    "next_hop_self": "True",
                    "disable_ipv4_afi": "True",
                    "disable_ipv6_afi": "False",
                    "is_confed_peer": "False",
                    "ingress_policy_name": ebgp_ingress_policy_name,
                    "egress_policy_name": ebgp_egress_policy_name,
                    "bgp_peer_timers_hold_time_seconds": "15",
                    "bgp_peer_timers_keep_alive_seconds": "5",
                    "bgp_peer_timers_out_delay_seconds": "7",
                    "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                    "peer_tag": "EBGP",
                    "max_routes": "50000",
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
                patcher_name=f"add_peer_group_patcher_{peergroup_ibgp_v6}",
                task_name="add_peer_group_patcher",
                patcher_args={
                    "name": peergroup_ibgp_v6,
                    "description": "BGP V6 peering for IBGP",
                    "next_hop_self": "True",
                    "disable_ipv4_afi": "True",
                    "disable_ipv6_afi": "False",
                    "is_confed_peer": "False",
                    "ingress_policy_name": ibgp_ingress_policy_name,
                    "egress_policy_name": ibgp_egress_policy_name,
                    "bgp_peer_timers_hold_time_seconds": "15",
                    "bgp_peer_timers_keep_alive_seconds": "5",
                    "bgp_peer_timers_out_delay_seconds": "7",
                    "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                    "peer_tag": "IBGP",
                    "max_routes": "50000",
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
                patcher_name=f"add_peer_group_patcher_{peergroup_ebgp_v4}",
                task_name="add_peer_group_patcher",
                patcher_args={
                    "name": peergroup_ebgp_v4,
                    "description": "BGP V4 peering for EBGP",
                    "next_hop_self": "True",
                    "disable_ipv4_afi": "False",
                    "disable_ipv6_afi": "True",
                    "is_confed_peer": "False",
                    "ingress_policy_name": ebgp_ingress_policy_name,
                    "egress_policy_name": ebgp_egress_policy_name,
                    "bgp_peer_timers_hold_time_seconds": "15",
                    "bgp_peer_timers_keep_alive_seconds": "5",
                    "bgp_peer_timers_out_delay_seconds": "7",
                    "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                    "peer_tag": "EBGP",
                    "max_routes": "50000",
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
                patcher_name=f"add_peer_group_patcher_{peergroup_ibgp_v4}",
                task_name="add_peer_group_patcher",
                patcher_args={
                    "name": peergroup_ibgp_v4,
                    "description": "BGP V4 peering for IBGP",
                    "next_hop_self": "True",
                    "disable_ipv4_afi": "False",
                    "disable_ipv6_afi": "True",
                    "is_confed_peer": "False",
                    "ingress_policy_name": ibgp_ingress_policy_name,
                    "egress_policy_name": ibgp_egress_policy_name,
                    "bgp_peer_timers_hold_time_seconds": "15",
                    "bgp_peer_timers_keep_alive_seconds": "5",
                    "bgp_peer_timers_out_delay_seconds": "7",
                    "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                    "peer_tag": "IBGP",
                    "max_routes": "50000",
                    "warning_only": "True",
                    "warning_limit": "0",
                    "link_bandwidth_bps": "auto",
                    "v4_over_v6_nexthop": "False",
                    "is_passive": "False",
                },
                py_func_name="add_peer_group_patcher",
            ),
            create_coop_apply_patchers_task(
                hostnames=[device_name],
                config_name="bgpcpp",
            ),
            create_wait_for_agent_convergence_task([device_name]),
        ],
        teardown_tasks=[
            create_coop_unregister_patchers_task(device_name),
        ],
        basic_port_configs=[
            taac_types.BasicPortConfig(
                endpoint=f"{device_name}:{ixia_interface_mimic_ebgp}",
                device_group_configs=[
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        multiplier=1,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_ebgp_ic_parent_network_v6}::11",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_ebgp_ic_parent_network_v6}::10",
                            gateway_increment_ip="0:0:0:0::2",
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=ebgp_remote_as,
                            enable_4_byte_local_as=True,
                            is_confed=False,
                            bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=1,
                                        prefix_length=64,
                                        starting_prefixes="2001:db8::",
                                        prefix_step="0:0:0:1::",
                                        bgp_communities=ixia_ebgp_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    ),
                                ),
                            ],
                        ),
                    ),
                    taac_types.DeviceGroupConfig(
                        device_group_index=1,
                        multiplier=1,
                        v4_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_ebgp_ic_parent_network_v4}.11",
                            increment_ip="0.0.0.2",
                            gateway_starting_ip=f"{ixia_ebgp_ic_parent_network_v4}.10",
                            gateway_increment_ip="0.0.0.2",
                            mask=31,
                        ),
                        v4_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=ebgp_remote_as,
                            enable_4_byte_local_as=True,
                            is_confed=False,
                            bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v4_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=1,
                                        prefix_length=24,
                                        starting_prefixes="100.0.0.0",
                                        prefix_step="0.0.1.0",
                                        bgp_communities=ixia_ebgp_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                    ),
                                ),
                            ],
                        ),
                    ),
                ],
            ),
            taac_types.BasicPortConfig(
                endpoint=f"{device_name}:{ixia_interface_mimic_ibgp}",
                device_group_configs=[
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        multiplier=1,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_ibgp_ic_parent_network_v6}::11",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v6}::10",
                            gateway_increment_ip="0:0:0:0::2",
                            mask=127,
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=ibgp_remote_as,
                            enable_4_byte_local_as=True,
                            is_confed=False,
                            bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        ),
                    ),
                    taac_types.DeviceGroupConfig(
                        device_group_index=1,
                        multiplier=1,
                        v4_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_ibgp_ic_parent_network_v4}.11",
                            increment_ip="0.0.0.2",
                            gateway_starting_ip=f"{ixia_ibgp_ic_parent_network_v4}.10",
                            gateway_increment_ip="0.0.0.2",
                            mask=31,
                        ),
                        v4_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=ibgp_remote_as,
                            enable_4_byte_local_as=True,
                            is_confed=False,
                            bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                        ),
                    ),
                ],
            ),
        ],
        playbooks=[
            create_test_constant_attribute_storage_playbook(
                device_name=device_name,
                peergroup_ibgp_v6=peergroup_ibgp_v6,
                peergroup_ebgp_v6=peergroup_ebgp_v6,
                peergroup_ibgp_v4=peergroup_ibgp_v4,
                peergroup_ebgp_v4=peergroup_ebgp_v4,
                ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
                ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
                ibgp_remote_as=ibgp_remote_as,
                ebgp_remote_as=ebgp_remote_as,
                ebgp_peer_counts=ebgp_peer_counts,
                unqiue_prefix_limit=unqiue_prefix_limit,
                total_path_limit=total_path_limit,
                ixia_ebgp_ic_parent_network_v6=ixia_ebgp_ic_parent_network_v6,
                ixia_ibgp_ic_parent_network_v6=ixia_ibgp_ic_parent_network_v6,
                ixia_ebgp_ic_parent_network_v4=ixia_ebgp_ic_parent_network_v4,
                ixia_ibgp_ic_parent_network_v4=ixia_ibgp_ic_parent_network_v4,
                ixia_ebgp_communities=ixia_ebgp_communities,
                ixia_ibgp_communities=ixia_ibgp_communities,
                ebgp_ingress_policy_name=ebgp_ingress_policy_name,
                ebgp_egress_policy_name=ebgp_egress_policy_name,
                ibgp_ingress_policy_name=ibgp_ingress_policy_name,
                ibgp_egress_policy_name=ibgp_egress_policy_name,
                ibgp_peer_count=ibgp_peer_count,
                prefix_counts=prefix_counts,
            ),
        ],
    )
