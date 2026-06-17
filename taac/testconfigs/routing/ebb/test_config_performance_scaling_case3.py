# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Arista BGP++ performance scaling test case 3: transient memory route scale.

Builds a TestConfig that exercises Arista BGP++ transient memory behavior
under increasing prefix counts. Holds IBGP/EBGP peer counts steady at a high
value (default 500 IBGP) and iterates through a list of prefix counts to
observe DUT memory growth and recovery as routes are advertised/withdrawn.
"""

from taac.playbooks.playbook_definitions import (
    create_bgp_plus_plus_transient_memory_route_scale_playbook,
)
from taac.routing.ebb.arista_bgp_plus_plus_performance_scaling_tests.ixia_configs_for_tests import (
    create_ebb_transient_memory_route_peer_scale_basic_port_configs,
)
from taac.task_definitions import (
    create_configure_bgpcpp_startup_task,
    create_invoke_ixia_api_task,
    create_replace_bgp_peers_task,
)
from taac.test_as_a_config.types import Endpoint, TestConfig

TOTAL_IBGP_PEERS = 500


def test_config_for_bgp_plus_plus_on_ebb_arista_transient_memory_route_scale(
    test_config_name: str,
    device_name: str,
    ixia_interface_mimic_ebgp: str,
    ixia_interface_mimic_ibgp: str,
    ibgp_peer_count_v6: int,
    ibgp_peer_count_v4: int,
    ebgp_peer_count_v6: int,
    ebgp_peer_count_v4: int,
    ebgp_remote_as: int,
    ibgp_remote_as: int,
    ixia_ebgp_ic_parent_network_v6: str,
    ixia_ebgp_ic_parent_network_v4: str,
    ixia_ibgp_ic_parent_network_v6: str,
    ixia_ibgp_ic_parent_network_v4: str,
    direct_ixia_connections: list,
    prefixes: list[int],
    initial_prefix_count: int,
    constant_acceptance_communities: list[str] | None = None,
    log_collection_timeout=None,
    oss_mock_device_data=None,
    host_os_type_map=None,
    host_driver_args=None,
    ssh_user: str = "admin",
    ssh_password: str = "",
    peergroup_ebgp_v6: str = "EB-FA-V6",
    peergroup_ebgp_v4: str = "EB-FA-V4",
    peergroup_ibgp_v6: str = "EB-EB-V6",
    peergroup_ibgp_v4: str = "EB-EB-V4",
):
    """Build the case-3 (transient memory, route scale) BGP++ TestConfig.

    Configures one DUT with EBGP and IBGP peer groups via bgpcpp dynamic
    peer replacement, then sweeps prefix advertisement counts via the
    `create_bgp_plus_plus_transient_memory_route_scale_playbook`. Used to
    plot Arista BGP++ memory vs. prefix count at a fixed peer count.

    Args:
        test_config_name: Final name of the produced TestConfig.
        device_name: DUT hostname (Arista EBB).
        ixia_interface_mimic_ebgp / ixia_interface_mimic_ibgp: IXIA port
            names used as EBGP/IBGP peer endpoints.
        ibgp_peer_count_v6 / ibgp_peer_count_v4 / ebgp_peer_count_v6 /
        ebgp_peer_count_v4: Per-AFI peer counts.
        ebgp_remote_as / ibgp_remote_as: Remote ASNs.
        ixia_ebgp_ic_parent_network_v6/v4, ixia_ibgp_ic_parent_network_v6/v4:
            Parent networks for IXIA-side prefix generation.
        direct_ixia_connections: Optional direct IXIA-port connection list.
        prefixes: List of prefix counts to sweep in the playbook.
        initial_prefix_count: Number of prefixes preloaded into the IXIA
            basic port config before the playbook starts.
        constant_acceptance_communities: Optional list of communities the
            DUT should always accept (passed through to the playbook).
        log_collection_timeout / oss_mock_device_data / host_os_type_map /
        host_driver_args: Optional overrides for OSS harness wiring.
        ssh_user / ssh_password: Credentials for dynamic bgpcpp peer
            configuration.
        peergroup_ebgp_v6 / peergroup_ebgp_v4 / peergroup_ibgp_v6 /
        peergroup_ibgp_v4: Peer-group names (defaults match EB-FA/EB-EB).

    Returns:
        TestConfig: The case-3 transient-memory route-scale TestConfig
        (consumed via `testconfigs.routing.ebb`).
    """
    initial_ebgp_peer_count = 1

    return TestConfig(
        name=test_config_name,
        skip_ixia_protocol_verification=True,
        log_collection_timeout=log_collection_timeout,
        basset_pool="dne.test",
        endpoints=[
            Endpoint(
                name=device_name,
                dut=True,
                ixia_ports=[ixia_interface_mimic_ebgp, ixia_interface_mimic_ibgp],
                direct_ixia_connections=direct_ixia_connections
                if direct_ixia_connections
                else [],
            ),
        ],
        host_driver_args=host_driver_args,
        oss_mock_device_data=oss_mock_device_data,
        host_os_type_map=host_os_type_map,
        startup_checks=[],
        setup_tasks=[
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
                        "peer_count": ebgp_peer_count_v6,
                        "start_offset": 16,
                    },
                    {
                        "peer_group_name": peergroup_ebgp_v4,
                        "remote_as": ebgp_remote_as,
                        "base_network": ixia_ebgp_ic_parent_network_v4,
                        "is_v6": False,
                        "peer_count": ebgp_peer_count_v4,
                        "start_offset": 10,
                    },
                    {
                        "peer_group_name": peergroup_ibgp_v6,
                        "remote_as": ibgp_remote_as,
                        "base_network": ixia_ibgp_ic_parent_network_v6,
                        "is_v6": True,
                        "peer_count": ibgp_peer_count_v6,
                        "start_offset": 16,
                    },
                    {
                        "peer_group_name": peergroup_ibgp_v4,
                        "remote_as": ibgp_remote_as,
                        "base_network": ixia_ibgp_ic_parent_network_v4,
                        "is_v6": False,
                        "peer_count": ibgp_peer_count_v4,
                        "start_offset": 10,
                    },
                ],
            ),
        ],
        teardown_tasks=[
            create_invoke_ixia_api_task(
                api_name="start_bgp_peers",
                args_dict={
                    "start": False,
                    "regex": "BGP_PEER_IPV6_IBGP",
                    "session_start_idx": 1,
                    "session_end_idx": ibgp_peer_count_v6,
                },
            ),
            create_invoke_ixia_api_task(
                api_name="start_bgp_peers",
                args_dict={
                    "start": False,
                    "regex": "BGP_PEER_IPV4_IBGP",
                    "session_start_idx": 1,
                    "session_end_idx": ibgp_peer_count_v4,
                },
            ),
        ],
        # Deprecated - define at playbook level
        # prechecks=[],
        # postchecks=[],
        # snapshot_checks=[],
        basic_port_configs=create_ebb_transient_memory_route_peer_scale_basic_port_configs(
            device_name=device_name,
            ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
            ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
            ebgp_peer_count_v6=initial_ebgp_peer_count,
            ebgp_peer_count_v4=initial_ebgp_peer_count,
            ibgp_peer_count_v6=ibgp_peer_count_v6,
            ibgp_peer_count_v4=ibgp_peer_count_v4,
            ebgp_remote_as=ebgp_remote_as,
            ibgp_remote_as=ibgp_remote_as,
            initial_prefix_count=initial_prefix_count,
            ixia_ebgp_ic_parent_network_v6=ixia_ebgp_ic_parent_network_v6,
            ixia_ebgp_ic_parent_network_v4=ixia_ebgp_ic_parent_network_v4,
            ixia_ibgp_ic_parent_network_v6=ixia_ibgp_ic_parent_network_v6,
            ixia_ibgp_ic_parent_network_v4=ixia_ibgp_ic_parent_network_v4,
        ),
        playbooks=[
            create_bgp_plus_plus_transient_memory_route_scale_playbook(
                device_name=device_name,
                ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
                ebgp_peer_count_v6=ebgp_peer_count_v6,
                ebgp_peer_count_v4=ebgp_peer_count_v4,
                ibgp_peer_count_v6=ibgp_peer_count_v6,
                ibgp_peer_count_v4=ibgp_peer_count_v4,
                prefixes=prefixes,
                constant_acceptance_communities=constant_acceptance_communities,
            ),
        ],
    )
