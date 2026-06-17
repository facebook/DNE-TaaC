# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Arista BGP++ performance scaling test case 4: transient memory peer scale.

Builds a TestConfig that exercises Arista BGP++ transient memory behavior
under increasing peer counts at a fixed prefix count. Sweeps a list of
(ibgp_peer_count, ebgp_peer_count) combinations to plot DUT memory vs.
peer count, complementing case 3 which sweeps prefixes at fixed peers.
"""

from taac.playbooks.playbook_definitions import (
    create_bgp_plus_plus_transient_memory_peer_scale_playbook,
)
from taac.routing.ebb.arista_bgp_plus_plus_performance_scaling_tests.ixia_configs_for_tests import (
    create_ebb_transient_memory_route_peer_scale_basic_port_configs,
)
from taac.task_definitions import (
    create_configure_bgpcpp_startup_task,
    create_invoke_ixia_api_task,
)
from taac.test_as_a_config.types import Endpoint, TestConfig


def test_config_for_bgp_plus_plus_on_ebb_arista_transient_memory_peer_scale(
    test_config_name: str,
    device_name: str,
    ixia_interface_mimic_ebgp: str,
    ixia_interface_mimic_ibgp: str,
    ebgp_remote_as: int,
    ibgp_remote_as: int,
    ixia_ebgp_ic_parent_network_v6: str,
    ixia_ebgp_ic_parent_network_v4: str,
    ixia_ibgp_ic_parent_network_v6: str,
    ixia_ibgp_ic_parent_network_v4: str,
    direct_ixia_connections: list,
    prefixes: int,
    peers_combination: list[tuple[int, int]],
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
    """Build the case-4 (transient memory, peer scale) BGP++ TestConfig.

    Configures one DUT, starts with a single peer per group, then runs
    `create_bgp_plus_plus_transient_memory_peer_scale_playbook` which
    iteratively reconfigures the EBGP/IBGP peer counts via the supplied
    `peers_combination` list while holding the prefix count steady.

    Args:
        test_config_name: Final name of the produced TestConfig.
        device_name: DUT hostname (Arista EBB).
        ixia_interface_mimic_ebgp / ixia_interface_mimic_ibgp: IXIA port
            names used as EBGP/IBGP peer endpoints.
        ebgp_remote_as / ibgp_remote_as: Remote ASNs.
        ixia_*_ic_parent_network_v6/v4: Parent networks for IXIA-side
            prefix and peer generation.
        direct_ixia_connections: Optional direct IXIA-port connection list.
        prefixes: Total prefix count to advertise per peer (held constant).
        peers_combination: List of (ibgp_count, ebgp_count) tuples to sweep.
        constant_acceptance_communities: Optional list of communities the
            DUT should always accept (passed through to the playbook).
        log_collection_timeout / oss_mock_device_data / host_os_type_map /
        host_driver_args: Optional overrides for OSS harness wiring.
        ssh_user / ssh_password: Credentials for dynamic bgpcpp peer
            configuration.
        peergroup_ebgp_v6 / peergroup_ebgp_v4 / peergroup_ibgp_v6 /
        peergroup_ibgp_v4: Peer-group names (defaults match EB-FA/EB-EB).

    Returns:
        TestConfig: The case-4 transient-memory peer-scale TestConfig
        (consumed via `testconfigs.routing.ebb`).
    """
    initial_peer_count = 1

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
        ],
        teardown_tasks=[
            create_invoke_ixia_api_task(
                api_name="start_bgp_peers",
                args_dict={
                    "start": False,
                    "regex": "BGP_PEER_IPV6_IBGP",
                    "session_start_idx": 1,
                },
            ),
            create_invoke_ixia_api_task(
                api_name="start_bgp_peers",
                args_dict={
                    "start": False,
                    "regex": "BGP_PEER_IPV4_IBGP",
                    "session_start_idx": 1,
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
            ebgp_peer_count_v6=initial_peer_count,
            ebgp_peer_count_v4=initial_peer_count,
            ibgp_peer_count_v6=initial_peer_count,
            ibgp_peer_count_v4=initial_peer_count,
            ebgp_remote_as=ebgp_remote_as,
            ibgp_remote_as=ibgp_remote_as,
            initial_prefix_count=prefixes // 2,
            ixia_ebgp_ic_parent_network_v6=ixia_ebgp_ic_parent_network_v6,
            ixia_ebgp_ic_parent_network_v4=ixia_ebgp_ic_parent_network_v4,
            ixia_ibgp_ic_parent_network_v6=ixia_ibgp_ic_parent_network_v6,
            ixia_ibgp_ic_parent_network_v4=ixia_ibgp_ic_parent_network_v4,
        ),
        playbooks=[
            create_bgp_plus_plus_transient_memory_peer_scale_playbook(
                device_name=device_name,
                ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
                ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
                prefixes=prefixes,
                constant_acceptance_communities=constant_acceptance_communities,
                peers_combination=peers_combination,
                ebgp_remote_as=ebgp_remote_as,
                ibgp_remote_as=ibgp_remote_as,
                ixia_ebgp_ic_parent_network_v6=ixia_ebgp_ic_parent_network_v6,
                ixia_ebgp_ic_parent_network_v4=ixia_ebgp_ic_parent_network_v4,
                ixia_ibgp_ic_parent_network_v6=ixia_ibgp_ic_parent_network_v6,
                ixia_ibgp_ic_parent_network_v4=ixia_ibgp_ic_parent_network_v4,
                peergroup_ebgp_v6=peergroup_ebgp_v6,
                peergroup_ebgp_v4=peergroup_ebgp_v4,
                peergroup_ibgp_v6=peergroup_ibgp_v6,
                peergroup_ibgp_v4=peergroup_ibgp_v4,
                ssh_user=ssh_user,
                ssh_password=ssh_password,
            ),
        ],
    )
