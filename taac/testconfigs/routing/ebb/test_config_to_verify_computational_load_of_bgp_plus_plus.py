# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""BGP++ computational load verification TestConfig.

Verifies that the computational load to advertise a given set of routes does
NOT increase significantly with the number of related IBGP peers. Sweeps
IBGP peer counts (200, 400, 600, 800, 1000) and prefix counts (10K-50K),
restarts bgpd at each combination, and plots CPU utilization to characterize
EOR-to-EOR latency and per-peer policy evaluation overhead.

Full test description (objective, execution steps, plot specification) is
in the in-module string literal below.
"""

from typing import List

from ixia.ixia import types as ixia_types
from taac.playbooks.playbook_definitions import (
    create_test_computational_load_for_bgp_plus_plus_playbook,
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
Test case: https://docs.google.com/document/d/1Jz4DMEBLUt90Di-0bx0c6G8m39sIR0QHTqWveE0fg5I/edit?tab=t.zhl42spd290x#heading=h.jey8tkk0dlky

Objective
Verify that the computational load to advertise a given set of routes does not increase significantly with the number of related IBGP peers.


Step-by-Step Test Case Execution

EBGP Peer Configuration:

Configure the EBGP peer to initially send 10,000 prefixes to the Device Under Test (DUT). 

IBGP Peers Configuration:

Set up 200 related IBGP peers with a non-trivial outbound policy, ensuring none of them sends any routes. 

Execution

Restart BGP Process:
Restart the BGP process on the DUT to ensure a clean start.
Capture CPU utilization over time.

Data Collection:
Record the time from when the EBGP peer sends the End-of-RIB (EOR) marker to when the last EOR is sent to the IBGP peers.
Wait for 10mins to soak to make sure we capture any instabilities such as peer flaps, route churns etc.
Note the CPU utilization during this period.

Repeat for Different N:
Incrementally increase the number of IBGP peers to 400, 600, 800, and 1,000.

For each increment:
Reconfigure the IBGP peers.

Restart the BGP process.
Collect data as described in steps 3 and 4.

Increase Prefixes:
Reconfigure the EBGP peer to send 20,000 prefixes.
Repeat steps 3 to 5 for each configuration of IBGP peers (N=200, 400, 600, 800, 1,000).
Reconfigure the EBGP peer to send 30,000 prefixes.
Repeat steps 3 to 5 for each configuration of IBGP peers (N=200, 400, 600, 800).
Reconfigure the EBGP peer to send 40,000 prefixes.
Repeat steps 3 to 5 for each configuration of IBGP peers (N=200, 400, 600).
Reconfigure the EBGP peer to send 50,000 prefixes.
Repeat steps 3 to 5 for each configuration of IBGP peers (N=200, 400).


Plot CPU Utilization:
For each configuration (10K and 20K prefixes with varying N), plot CPU utilization against the number of IBGP peers (CPU(N)).
Use a line graph to visualize the relationship between the number of peers, prefixes, and CPU load.
"""


def test_config_to_verify_computational_load_of_bgp_plus_plus(
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
    ebgp_peer_scale,
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
    ibgp_peer_counts: List[int],
    prefix_counts: List[int],
):
    """Build the BGP++ computational-load verification TestConfig.

    Wires up COOP patcher tasks (unregister/register/apply, scp systemd
    bgpd service template, restart bgpd, agent convergence wait), then
    runs `create_test_computational_load_for_bgp_plus_plus_playbook` which
    sweeps the cartesian product of `ibgp_peer_counts` and `prefix_counts`,
    restarting bgpd at each iteration and capturing CPU + EOR timing.

    Args:
        test_config_name: Final name of the produced TestConfig.
        device_name: DUT hostname (FBOSS EBB).
        peergroup_* / ixia_interface_mimic_* / *_remote_as / ixia_*_communities:
            BGP peer-group and IXIA peer wiring (v4 + v6 for IBGP and EBGP).
        ebgp_peer_scale: Number of EBGP peers configured up front.
        unqiue_prefix_limit / total_path_limit: Route scale knobs (historical
            typo in `unqiue_*` preserved).
        ixia_*_ic_parent_network_v6/v4: Parent networks for IXIA-side prefix
            generation.
        *_ingress_policy_name / *_egress_policy_name: COOP BGP policy names
            (non-trivial outbound policy is the load source under test).
        ibgp_peer_counts: List of IBGP peer counts to sweep (e.g. 200, 400,
            600, 800, 1000).
        prefix_counts: List of prefix advertisement counts to sweep at each
            IBGP peer count (e.g. 10000, 20000, 30000, 40000, 50000).

    Returns:
        TestConfig: The computational-load TestConfig, registered via
        `BGP_PLUS_PLUS_VERIFY_COMPUTATIONAL_LOAD_TEST_CONFIG` and re-exported
        through `testconfigs.routing.ebb`.
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
            # Remove all the bgp peers present in the device first
            # Task(
            #     task_name="coop_register_patcher",
            #     params=Params(
            #         json_params=json.dumps(
            #             {
            #                 "hostname": device_name,
            #                 "config_name": "bgpcpp",
            #                 "patcher_name": "delete_bgp_peer_groups",
            #                 "py_func_name": "delete_bgp_peer_groups",
            #                 "patcher_args": json.dumps({"delete_all": "True"}),
            #             }
            #         ),
            #     ),
            # ),
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
            # Task(
            #     task_name="bgp_policy_installer",
            #     params=Params(
            #         json_params=json.dumps(
            #             {
            #                 "hostname": device_name,
            #                 "file_path": "/data/users/rpurushoth/configerator/raw_configs/taac/test_bgp_policies/ebb_policy_in_fboss_format.json",
            #                 "config_name": "bgpcpp",
            #                 "filter_policy_names": [
            #                     ebgp_ingress_policy_name,
            #                     ebgp_egress_policy_name,
            #                     ibgp_ingress_policy_name,
            #                     ibgp_egress_policy_name,
            #                 ],
            #             }
            #         )
            #     ),
            # ),
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
            create_test_computational_load_for_bgp_plus_plus_playbook(
                device_name=device_name,
                peergroup_ibgp_v6=peergroup_ibgp_v6,
                peergroup_ebgp_v6=peergroup_ebgp_v6,
                peergroup_ibgp_v4=peergroup_ibgp_v4,
                peergroup_ebgp_v4=peergroup_ebgp_v4,
                ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
                ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
                ibgp_remote_as=ibgp_remote_as,
                ebgp_remote_as=ebgp_remote_as,
                ebgp_peer_scale=ebgp_peer_scale,
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
                ibgp_peer_counts=ibgp_peer_counts,
                prefix_counts=prefix_counts,
            ),
        ],
    )
