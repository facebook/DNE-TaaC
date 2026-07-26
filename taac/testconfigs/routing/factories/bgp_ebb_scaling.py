# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""BGP++ EBB scaling-workload testconfig factories.

Workload family covers the Arista BGP++ perf-scaling / transient-memory /
route-churn / bounded-ECMP-set experiments historically wired through the
``test_config_performance_scaling_case{1,3,4,6,9}.py`` factories. Each
new factory takes ``(physical_inventory: PhysicalInventory, *, name: str, ...)`` and returns a
``TestConfig`` whose serialized form is byte-wise identical to the legacy
factory outputs (golden manifest hashes preserved verbatim).

The factory bodies stay as close as possible to the legacy factory bodies;
DUT identity fields (``device_name``, IXIA port names / chassis map, lab
device host_driver_args, oss_mock_device_data) are derived from
``physical_inventory`` (via ``extras`` on the lab physical inventories); the remaining workload
knobs (peer counts, prefix counts, community lists, etc.) stay as
kwargs with defaults matching the legacy eb02.lab.ash6 wrappers.

See ../README.md §3.
"""

import os
import typing as t
from dataclasses import replace

from taac.abstractions.physical_inventory import PhysicalInventory
from taac.abstractions.topologies.bounded_ecmp import (
    BOUNDED_ECMP,
    BOUNDED_ECMP_PEER_GROUPS,
    BOUNDED_ECMP_PORT_MAP,
)
from taac.abstractions.topology import (
    OpenRMode,
    RoutingDeviceConfig,
)
from taac.constants import Gigabyte
from taac.health_checks.healthcheck_definitions import (
    create_bgp_convergence_check,
    create_bgp_rib_fib_consistency_check,
    create_bgp_session_establish_check,
    create_bgp_session_snapshot_check,
    create_core_dumps_snapshot_check,
)
from taac.playbooks.playbook_definitions import (
    build_case6_playbook,
    create_bgp_plus_plus_arista_bounded_ecmp_sets_playbook,
    create_bgp_plus_plus_transient_memory_peer_scale_playbook,
    create_bgp_plus_plus_transient_memory_route_scale_playbook,
    create_performance_scaling_egress_peer_sweep_playbook,
    PerIterationSetupStepsFactory,
)
from taac.routing.ebb.arista_bgp_plus_plus_performance_scaling_tests.ixia_configs_for_tests import (
    create_ebb_performance_scale_basic_port_configs,
    create_ebb_route_churn_test_basic_port_configs,
    create_ebb_transient_memory_route_peer_scale_basic_port_configs,
)
from taac.stages.stage_definitions import (
    create_bgp_restart_test_stage,
    create_steps_stage,
)
from taac.steps.step_definitions import (
    create_custom_step,
    create_ixia_api_step,
    create_ixia_packet_capture_step,
    create_longevity_step,
)
from taac.task_definitions import (
    create_arista_daemon_control_task,
    create_configure_bgpcpp_startup_task,
    create_interface_ip_configuration_task,
    create_invoke_ixia_api_task,
    create_replace_bgp_peers_task,
    create_run_commands_on_shell_task,
    create_validate_bgpcpp_config_on_device_task,
)
from taac.testconfigs.routing.util.bgp_ebb_constants import (
    UPDATE_GROUP_CONFIG,
)
from taac.testconfigs.routing.util.bgp_ebb_lab_wiring import (
    _direct_ixia_conns_two_port,
)
from taac.testconfigs.routing.util.bgp_ebb_periodic_tasks import (
    create_standard_periodic_tasks,
)
from taac.testconfigs.routing.util.bgp_ebb_setup_tasks import (
    _generate_ixia_v4_peer_entries_for_bgpcpp,
    _generate_ixia_v6_peer_entries_for_bgpcpp,
)
from taac.testconfigs.routing.util.bgpcpp_peers_modification import (
    _generate_bgpcpp_peers_modification_tasks,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import (
    BasicPortConfig,
    DirectIxiaConnection,
    Endpoint,
    TestConfig,
)


# bgpcpp on-device paths (Arista EOS) -- kept in lock-step with the legacy
# ``test_config_performance_scaling_case9.py`` constants so the ECMP-sets
# factory produces byte-identical setup task strings.
_RUN_BGPCPP_SCRIPT_PATH = "/usr/sbin/run_bgpcpp.sh"
_BGPCPP_CONFIG_PATH = "/mnt/flash/bgpcpp_config"

# The community on the DUT's inbound eBGP allowlist policy (EB-FA-IN): routes
# carrying it are accepted, everything else is denied by the catch-all term. The
# perf-scaling eBGP routes are tagged with only this one community so they (a)
# pass EB-FA-IN and (b) render cleanly (no diverse-CSV named-community noise).
_EB_FA_TRANSITED_COMMUNITY = "65529:39744"


# ─── physical_inventory → DUT-wiring helpers hoisted to util/bgp_ebb_lab_wiring.py ───
# to break a circular import with bgp_ebb_characteristic.py (see that file's
# imports and util/bgp_ebb_lab_wiring.py docstring).


# =============================================================================
# BGP++ perf-scaling egress IBGP peer sweep (legacy case1)
# =============================================================================


def create_bgp_ebb_scaling_performance_test_config(
    physical_inventory: PhysicalInventory,
    *,
    name: str,
    egress_peer_counts: list[int],
    prefix_count: int = 50000,
    ebgp_peer_count: int = 1,
    ebgp_remote_as: int = 65334,
    ibgp_remote_as: int = 64981,
    ixia_ebgp_ic_parent_network_v6: str = "2401:db00:e50d:11:8",
    ixia_ebgp_ic_parent_network_v4: str = "10.163.28",
    ixia_ibgp_ic_parent_network_v6: str = "2401:db00:e50d:11:9",
    ixia_ibgp_ic_parent_network_v4: str = "10.164.28",
    log_collection_timeout: int | None = None,
    setup_tasks: list | None = None,
    teardown_tasks: list | None = None,
    per_iteration_setup_steps_factory: PerIterationSetupStepsFactory | None = None,
    direct_ixia_connections: list[DirectIxiaConnection] | None = None,
    host_driver_args: dict[str, str] | None = None,
    oss_mock_device_data: dict[str, taac_types.MockDeviceInfo] | None = None,
    host_os_type_map: dict[str, taac_types.DeviceOsType] | None = None,
    endpoints: list[Endpoint] | None = None,
    basic_port_configs: list[BasicPortConfig] | None = None,
) -> TestConfig:
    """BGP++ egress-peer sweep TestConfig -- Arista perf-scaling case 1.

    DUT identity and default IXIA artifacts come from ``physical_inventory``.
    Migrated callers may supply topology-compiled endpoints and port configs;
    ``None`` selects inventory-derived defaults, while explicit empty lists are
    preserved. This factory retains ownership of the peer-sweep playbook.

    See ../ebb/test_config_performance_scaling_case1.py header for the full
    playbook contract.
    """
    device_name = physical_inventory.device_name
    ixia_interface_mimic_ebgp = physical_inventory.ixia_ports[0][0]
    ixia_interface_mimic_ibgp = physical_inventory.ixia_ports[1][0]
    max_n = max(egress_peer_counts)

    resolved_host_driver_args = (
        host_driver_args
        if host_driver_args is not None
        else physical_inventory.host_driver_args
    )
    resolved_oss_mock_device_data = (
        oss_mock_device_data
        if oss_mock_device_data is not None
        else physical_inventory.oss_mock_device_data
    )
    resolved_host_os_type_map = (
        host_os_type_map
        if host_os_type_map is not None
        else {device_name: taac_types.DeviceOsType.ARISTA_FBOSS}
    )
    resolved_direct_ixia_connections = (
        direct_ixia_connections
        if direct_ixia_connections is not None
        else _direct_ixia_conns_two_port(physical_inventory)
    )

    return TestConfig(
        name=name,
        skip_ixia_protocol_verification=True,
        log_collection_timeout=log_collection_timeout,
        basset_pool="dne.test",
        endpoints=(
            endpoints
            if endpoints is not None
            else [
                Endpoint(
                    name=device_name,
                    dut=True,
                    ixia_ports=[
                        ixia_interface_mimic_ebgp,
                        ixia_interface_mimic_ibgp,
                    ],
                    direct_ixia_connections=resolved_direct_ixia_connections,
                ),
            ]
        ),
        host_driver_args=resolved_host_driver_args,
        oss_mock_device_data=resolved_oss_mock_device_data,
        host_os_type_map=resolved_host_os_type_map,
        startup_checks=[],
        setup_tasks=setup_tasks if setup_tasks is not None else [],
        teardown_tasks=teardown_tasks if teardown_tasks is not None else [],
        basic_port_configs=basic_port_configs
        if basic_port_configs is not None
        else create_ebb_performance_scale_basic_port_configs(
            device_name=device_name,
            ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
            ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
            ebgp_peer_count_v6=ebgp_peer_count,
            ebgp_peer_count_v4=ebgp_peer_count,
            ibgp_peer_count_v6=max_n,
            ibgp_peer_count_v4=max_n,
            ebgp_remote_as=ebgp_remote_as,
            ibgp_remote_as=ibgp_remote_as,
            ixia_ebgp_ic_parent_network_v6=ixia_ebgp_ic_parent_network_v6,
            ixia_ebgp_ic_parent_network_v4=ixia_ebgp_ic_parent_network_v4,
            ixia_ibgp_ic_parent_network_v6=ixia_ibgp_ic_parent_network_v6,
            ixia_ibgp_ic_parent_network_v4=ixia_ibgp_ic_parent_network_v4,
            # next-hop-self so the eBGP routes carry the connected IXIA peer
            # address and the DUT resolves them without Open/R/IGP (perf-scaling
            # only; other callers keep the default PRESERVE_FROM_FILE).
            ebgp_next_hop_self=True,
            ebgp_fixed_communities=[_EB_FA_TRANSITED_COMMUNITY],
        ),
        playbooks=[
            create_performance_scaling_egress_peer_sweep_playbook(
                device_name=device_name,
                egress_peer_counts=egress_peer_counts,
                prefix_count=prefix_count,
                ebgp_peer_count=ebgp_peer_count,
                per_iteration_setup_steps_factory=per_iteration_setup_steps_factory,
            ),
        ],
    )


# =============================================================================
# BGP++ transient-memory route scale (legacy case3)
# =============================================================================


def create_bgp_ebb_scaling_transient_memory_route_scale_test_config(
    physical_inventory: PhysicalInventory,
    *,
    name: str,
    ebgp_peer_count_v4: int = 140,
    ebgp_peer_count_v6: int = 140,
    ibgp_peer_count_v6: int = 200,
    ibgp_peer_count_v4: int = 200,
    ebgp_remote_as: int = 65334,
    ibgp_remote_as: int = 64981,
    ixia_ebgp_ic_parent_network_v6: str = "2401:db00:e50d:11:8",
    ixia_ebgp_ic_parent_network_v4: str = "10.163.28",
    ixia_ibgp_ic_parent_network_v6: str = "2401:db00:e50d:11:9",
    ixia_ibgp_ic_parent_network_v4: str = "10.164.28",
    prefixes: list[int] | None = None,
    initial_prefix_count: int = 1,
    constant_acceptance_communities: list[str] | None = None,
    ssh_user: str = "admin",
    ssh_password: str | None = None,
    peergroup_ebgp_v6: str = "EB-FA-V6",
    peergroup_ebgp_v4: str = "EB-FA-V4",
    peergroup_ibgp_v6: str = "EB-EB-V6",
    peergroup_ibgp_v4: str = "EB-EB-V4",
) -> TestConfig:
    """BGP++ transient-memory route-scale TestConfig -- Arista perf-scaling case 3.

    Byte-wise identical to the legacy
    ``test_config_performance_scaling_case3.test_config_for_bgp_plus_plus_on_ebb_arista_transient_memory_route_scale``.
    """
    if prefixes is None:
        prefixes = [10000, 20000, 30000, 40000, 50000]
    if ssh_password is None:
        ssh_password = os.environ.get("TAAC_EBB_LAB_DEVICE_PASSWORD", "dnepit")
    if constant_acceptance_communities is None:
        constant_acceptance_communities = ["65529:39744"]

    device_name = physical_inventory.device_name
    ixia_interface_mimic_ebgp = physical_inventory.ixia_ports[0][0]
    ixia_interface_mimic_ibgp = physical_inventory.ixia_ports[1][0]
    host_driver_args = physical_inventory.host_driver_args
    oss_mock_device_data = physical_inventory.oss_mock_device_data
    host_os_type_map = {device_name: taac_types.DeviceOsType.ARISTA_FBOSS}
    direct_ixia_connections = _direct_ixia_conns_two_port(physical_inventory)

    initial_ebgp_peer_count = 1

    return TestConfig(
        name=name,
        skip_ixia_protocol_verification=True,
        log_collection_timeout=None,
        basset_pool="dne.test",
        endpoints=[
            Endpoint(
                name=device_name,
                dut=True,
                ixia_ports=[ixia_interface_mimic_ebgp, ixia_interface_mimic_ibgp],
                direct_ixia_connections=direct_ixia_connections,
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


# =============================================================================
# BGP++ transient-memory peer scale (legacy case4)
# =============================================================================


def create_bgp_ebb_scaling_transient_memory_peer_scale_test_config(
    physical_inventory: PhysicalInventory,
    *,
    name: str,
    ebgp_remote_as: int = 65334,
    ibgp_remote_as: int = 64981,
    ixia_ebgp_ic_parent_network_v6: str = "2401:db00:e50d:11:8",
    ixia_ebgp_ic_parent_network_v4: str = "10.163.28",
    ixia_ibgp_ic_parent_network_v6: str = "2401:db00:e50d:11:9",
    ixia_ibgp_ic_parent_network_v4: str = "10.164.28",
    prefixes: int = 50000,
    peers_combination: list[tuple[int, int]] | None = None,
    constant_acceptance_communities: list[str] | None = None,
    ssh_user: str = "admin",
    ssh_password: str | None = None,
    peergroup_ebgp_v6: str = "EB-FA-V6",
    peergroup_ebgp_v4: str = "EB-FA-V4",
    peergroup_ibgp_v6: str = "EB-EB-V6",
    peergroup_ibgp_v4: str = "EB-EB-V4",
) -> TestConfig:
    """BGP++ transient-memory peer-scale TestConfig -- Arista perf-scaling case 4.

    Byte-wise identical to the legacy
    ``test_config_performance_scaling_case4.test_config_for_bgp_plus_plus_on_ebb_arista_transient_memory_peer_scale``.
    """
    if peers_combination is None:
        peers_combination = [(40, 100), (120, 200), (200, 300), (280, 400)]
    if ssh_password is None:
        ssh_password = os.environ.get("TAAC_EBB_LAB_DEVICE_PASSWORD", "dnepit")
    if constant_acceptance_communities is None:
        constant_acceptance_communities = ["65529:39744"]

    device_name = physical_inventory.device_name
    ixia_interface_mimic_ebgp = physical_inventory.ixia_ports[0][0]
    ixia_interface_mimic_ibgp = physical_inventory.ixia_ports[1][0]
    host_driver_args = physical_inventory.host_driver_args
    oss_mock_device_data = physical_inventory.oss_mock_device_data
    host_os_type_map = {device_name: taac_types.DeviceOsType.ARISTA_FBOSS}
    direct_ixia_connections = _direct_ixia_conns_two_port(physical_inventory)

    initial_peer_count = 1

    return TestConfig(
        name=name,
        skip_ixia_protocol_verification=True,
        log_collection_timeout=None,
        basset_pool="dne.test",
        endpoints=[
            Endpoint(
                name=device_name,
                dut=True,
                ixia_ports=[ixia_interface_mimic_ebgp, ixia_interface_mimic_ibgp],
                direct_ixia_connections=direct_ixia_connections,
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


# =============================================================================
# BGP++ route churn (legacy case6, 2 variants)
# =============================================================================


def create_bgp_ebb_scaling_route_churn_test_config(
    physical_inventory: PhysicalInventory,
    *,
    name: str,
    ebgp_peer_count: int,
    ibgp_peer_count: int,
    ebgp_remote_as: int = 65334,
    ibgp_remote_as: int = 64981,
    ixia_ebgp_ic_parent_network_v6: str = "2401:db00:e50d:11:8",
    ixia_ibgp_ic_parent_network_v6: str = "2401:db00:e50d:11:9",
    prefixes: int = 5000,
    churn_count: int = 100,
    initial_convergence_time_seconds: int = 600,
    ssh_user: str | None = None,
    ssh_password: str | None = None,
    peergroup_ebgp_v6: str = "EB-FA-V6",
    peergroup_ibgp_v6: str = "EB-EB-V6",
) -> TestConfig:
    """BGP++ route-churn TestConfig -- Arista perf-scaling case 6 (fixed-peer).

    Byte-wise identical to the legacy
    ``test_config_performance_scaling_case6.test_config_for_bgp_plus_plus_on_ebb_arista_route_churn``.
    """
    device_name = physical_inventory.device_name
    ixia_interface_mimic_ebgp = physical_inventory.ixia_ports[0][0]
    ixia_interface_mimic_ibgp = physical_inventory.ixia_ports[1][0]
    host_driver_args = physical_inventory.host_driver_args
    oss_mock_device_data = physical_inventory.oss_mock_device_data
    host_os_type_map = {device_name: taac_types.DeviceOsType.ARISTA_FBOSS}
    direct_ixia_connections = _direct_ixia_conns_two_port(physical_inventory)

    total_bgp_peers = ibgp_peer_count + ebgp_peer_count

    if ssh_user is not None and ssh_password is not None:
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
                        "peer_group_name": peergroup_ibgp_v6,
                        "remote_as": ibgp_remote_as,
                        "base_network": ixia_ibgp_ic_parent_network_v6,
                        "is_v6": True,
                        "peer_count": ibgp_peer_count,
                        "start_offset": 16,
                    },
                ],
            ),
        ]
    else:
        setup_tasks = [
            create_run_commands_on_shell_task(
                hostname=device_name,
                cmds=[
                    f"bash sudo cp /mnt/flash/bgpcpp_config_test_case6_{total_bgp_peers}_total_bgp_peers /mnt/flash/bgpcpp_config"
                ],
            ),
        ]

    return TestConfig(
        name=name,
        skip_ixia_protocol_verification=True,
        log_collection_timeout=None,
        basset_pool="dne.test",
        endpoints=[
            Endpoint(
                name=device_name,
                dut=True,
                ixia_ports=[ixia_interface_mimic_ebgp, ixia_interface_mimic_ibgp],
                direct_ixia_connections=direct_ixia_connections,
            ),
        ],
        host_driver_args=host_driver_args,
        oss_mock_device_data=oss_mock_device_data,
        host_os_type_map=host_os_type_map,
        startup_checks=[],
        setup_tasks=setup_tasks,
        teardown_tasks=[],
        basic_port_configs=create_ebb_route_churn_test_basic_port_configs(
            device_name=device_name,
            ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
            ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
            ebgp_peer_count_v6=ebgp_peer_count,
            ibgp_peer_count_v6=ibgp_peer_count,
            ebgp_remote_as=ebgp_remote_as,
            ibgp_remote_as=ibgp_remote_as,
            initial_prefix_count=prefixes,
            churn_count=churn_count,
            ixia_ebgp_ic_parent_network_v6=ixia_ebgp_ic_parent_network_v6,
            ixia_ibgp_ic_parent_network_v6=ixia_ibgp_ic_parent_network_v6,
        ),
        playbooks=[
            build_case6_playbook(
                name="bgp_plus_plus_arista_route_churn_test",
                description="Test BGP++ Convergence time with route churn",
                snapshot_checks=[
                    create_core_dumps_snapshot_check(),
                    create_bgp_session_snapshot_check(
                        skip_flap_check=True, skip_uptime_check=True
                    ),
                ],
                periodic_tasks=create_standard_periodic_tasks(
                    device_name=device_name,
                    memory_threshold=Gigabyte.GIG_5.value,
                    cpu_util_terminate_on_error=False,
                    memory_terminate_on_error=False,
                ),
                prechecks=[],
                postchecks=[
                    create_bgp_session_establish_check(
                        expected_established_sessions_static=ibgp_peer_count
                        + ebgp_peer_count,
                        check_id="startup_bgp_session_verification",
                    ),
                    create_bgp_rib_fib_consistency_check(),
                    create_bgp_convergence_check(
                        convergence_threshold=700,
                        check_id="postcheck_bgp_convergence_time",
                    ),
                ],
                stages=[
                    create_steps_stage(
                        steps=[
                            create_ixia_api_step(
                                api_name="set_bgp_local_preference",
                                args_dict={
                                    "local_preference": 100,
                                    "prefix_pool_regex": ".*IPV6_IBGP.*",
                                },
                            ),
                        ]
                    ),
                    create_bgp_restart_test_stage(
                        device_name=device_name,
                        convergence_wait_seconds=initial_convergence_time_seconds,
                    ),
                    create_steps_stage(
                        steps=[
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_mimic_ebgp,
                                mode="start",
                                capture_id="arista_route_churn_ebgp",
                                description="Start IXIA packet capture for route churn - eBGP",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_mimic_ibgp,
                                mode="start",
                                capture_id="arista_route_churn_ibgp",
                                description="Start IXIA packet capture for route churn - iBGP",
                            ),
                            create_longevity_step(
                                duration=5,
                                description="Brief pause to ensure IXIA capture is ready - 5 seconds",
                            ),
                            create_ixia_api_step(
                                api_name="set_bgp_local_preference",
                                args_dict={
                                    "local_preference": 50,
                                    "prefix_pool_regex": ".*PEER_1_FIRST_100.*",
                                },
                            ),
                            create_longevity_step(
                                duration=600,
                                description="Soak after churn for 600 seconds",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_mimic_ebgp,
                                mode="stop",
                                capture_id="arista_route_churn_ebgp",
                                description="Stop IXIA packet capture for route churn - eBGP",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_mimic_ibgp,
                                mode="stop",
                                capture_id="arista_route_churn_ibgp",
                                description="Stop IXIA packet capture for route churn - iBGP",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_mimic_ebgp,
                                mode="save",
                                pcap_filename="bgp_arista_churn_ebgp.pcap",
                                capture_id="arista_route_churn_ebgp",
                                description="Save IXIA packet capture for route churn - eBGP",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_mimic_ibgp,
                                mode="save",
                                pcap_filename="bgp_arista_churn_ibgp.pcap",
                                capture_id="arista_route_churn_ibgp",
                                description="Save IXIA packet capture for route churn - iBGP",
                            ),
                            create_custom_step(
                                description="Analyze route churn convergence time - eBGP",
                                params_dict={
                                    "custom_step_name": "check_route_churn_convergence",
                                    "pcap_filename": "bgp_arista_churn_ebgp.pcap",
                                    "phase": "route_churn_ebgp",
                                    "max_convergence_time_seconds": 300,
                                },
                            ),
                            create_custom_step(
                                description="Analyze route churn convergence time - iBGP",
                                params_dict={
                                    "custom_step_name": "check_route_churn_convergence",
                                    "pcap_filename": "bgp_arista_churn_ibgp.pcap",
                                    "phase": "route_churn_ibgp",
                                    "max_convergence_time_seconds": 300,
                                },
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_mimic_ebgp,
                                mode="start",
                                capture_id="arista_route_churn_revert_ebgp",
                                description="Start IXIA packet capture for route churn revert - eBGP",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_mimic_ibgp,
                                mode="start",
                                capture_id="arista_route_churn_revert_ibgp",
                                description="Start IXIA packet capture for route churn revert - iBGP",
                            ),
                            create_longevity_step(
                                duration=5,
                                description="Brief pause to ensure IXIA capture is ready - 5 seconds",
                            ),
                            create_ixia_api_step(
                                api_name="set_bgp_local_preference",
                                args_dict={
                                    "local_preference": 100,
                                    "prefix_pool_regex": ".*PEER_1_FIRST_100.*",
                                },
                            ),
                            create_longevity_step(
                                duration=600,
                                description="Soak after churn revert for 600 seconds",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_mimic_ebgp,
                                mode="stop",
                                capture_id="arista_route_churn_revert_ebgp",
                                description="Stop IXIA packet capture for route churn revert - eBGP",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_mimic_ibgp,
                                mode="stop",
                                capture_id="arista_route_churn_revert_ibgp",
                                description="Stop IXIA packet capture for route churn revert - iBGP",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_mimic_ebgp,
                                mode="save",
                                pcap_filename="bgp_arista_churn_revert_ebgp.pcap",
                                capture_id="arista_route_churn_revert_ebgp",
                                description="Save IXIA packet capture for route churn revert - eBGP",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_mimic_ibgp,
                                mode="save",
                                pcap_filename="bgp_arista_churn_revert_ibgp.pcap",
                                capture_id="arista_route_churn_revert_ibgp",
                                description="Save IXIA packet capture for route churn revert - iBGP",
                            ),
                            create_custom_step(
                                description="Analyze route churn revert convergence time - eBGP",
                                params_dict={
                                    "custom_step_name": "check_route_churn_convergence",
                                    "pcap_filename": "bgp_arista_churn_revert_ebgp.pcap",
                                    "phase": "route_churn_revert_ebgp",
                                    "max_convergence_time_seconds": 300,
                                },
                            ),
                            create_custom_step(
                                description="Analyze route churn revert convergence time - iBGP",
                                params_dict={
                                    "custom_step_name": "check_route_churn_convergence",
                                    "pcap_filename": "bgp_arista_churn_revert_ibgp.pcap",
                                    "phase": "route_churn_revert_ibgp",
                                    "max_convergence_time_seconds": 300,
                                },
                            ),
                            create_longevity_step(
                                duration=100,
                                description="Sleep for 100 seconds for FIB Sync",
                            ),
                        ]
                    ),
                ],
            ),
        ],
    )


def create_bgp_ebb_scaling_route_churn_prefix_test_config(
    physical_inventory: PhysicalInventory,
    *,
    name: str,
    ebgp_peer_count: int = 100,
    ibgp_peer_count: int = 100,
    ebgp_remote_as: int = 65334,
    ibgp_remote_as: int = 64981,
    ixia_ebgp_ic_parent_network_v6: str = "2401:db00:e50d:11:8",
    ixia_ibgp_ic_parent_network_v6: str = "2401:db00:e50d:11:9",
    prefix_configs: list[tuple[int, int]] | None = None,
    churn_count: int = 100,
    soak_duration_seconds: int = 600,
    max_convergence_time_seconds: int = 300,
    ssh_user: str = "admin",
    ssh_password: str | None = None,
    peergroup_ebgp_v6: str = "EB-FA-V6",
    peergroup_ibgp_v6: str = "EB-EB-V6",
) -> TestConfig:
    """BGP++ route-churn prefix-scaling TestConfig -- perf-scaling case 6 (prefix scaling).

    Byte-wise identical to the legacy
    ``test_config_performance_scaling_case6.test_config_for_route_churn_prefix_scaling``.
    """
    if prefix_configs is None:
        prefix_configs = [(5000, 600)]
    if ssh_password is None:
        ssh_password = os.environ.get("TAAC_EBB_LAB_DEVICE_PASSWORD", "dnepit")

    device_name = physical_inventory.device_name
    ixia_interface_mimic_ebgp = physical_inventory.ixia_ports[0][0]
    ixia_interface_mimic_ibgp = physical_inventory.ixia_ports[1][0]
    host_driver_args = physical_inventory.host_driver_args
    oss_mock_device_data = physical_inventory.oss_mock_device_data
    host_os_type_map = {device_name: taac_types.DeviceOsType.ARISTA_FBOSS}
    direct_ixia_connections = _direct_ixia_conns_two_port(physical_inventory)

    max_prefix_count = max(pc for pc, _ in prefix_configs)

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
                    "peer_group_name": peergroup_ibgp_v6,
                    "remote_as": ibgp_remote_as,
                    "base_network": ixia_ibgp_ic_parent_network_v6,
                    "is_v6": True,
                    "peer_count": ibgp_peer_count,
                    "start_offset": 16,
                },
            ],
        ),
    ]

    return TestConfig(
        name=name,
        skip_ixia_protocol_verification=True,
        log_collection_timeout=None,
        basset_pool="dne.test",
        endpoints=[
            Endpoint(
                name=device_name,
                dut=True,
                ixia_ports=[ixia_interface_mimic_ebgp, ixia_interface_mimic_ibgp],
                direct_ixia_connections=direct_ixia_connections,
            ),
        ],
        host_driver_args=host_driver_args,
        oss_mock_device_data=oss_mock_device_data,
        host_os_type_map=host_os_type_map,
        startup_checks=[],
        setup_tasks=setup_tasks,
        teardown_tasks=[],
        basic_port_configs=create_ebb_route_churn_test_basic_port_configs(
            device_name=device_name,
            ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
            ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
            ebgp_peer_count_v6=ebgp_peer_count,
            ibgp_peer_count_v6=ibgp_peer_count,
            ebgp_remote_as=ebgp_remote_as,
            ibgp_remote_as=ibgp_remote_as,
            initial_prefix_count=max_prefix_count,
            churn_count=churn_count,
            ixia_ebgp_ic_parent_network_v6=ixia_ebgp_ic_parent_network_v6,
            ixia_ibgp_ic_parent_network_v6=ixia_ibgp_ic_parent_network_v6,
        ),
        playbooks=[
            build_case6_playbook(
                name="bgp_plus_plus_route_churn_prefix_scaling_test",
                description="Test BGP++ route churn convergence across multiple prefix scales",
                snapshot_checks=[
                    create_core_dumps_snapshot_check(),
                    create_bgp_session_snapshot_check(
                        skip_flap_check=True, skip_uptime_check=True
                    ),
                ],
                periodic_tasks=create_standard_periodic_tasks(
                    device_name=device_name,
                    memory_threshold=Gigabyte.GIG_5.value,
                    cpu_util_terminate_on_error=False,
                    memory_terminate_on_error=False,
                ),
                prechecks=[],
                postchecks=[
                    create_bgp_session_establish_check(
                        expected_established_sessions_static=ibgp_peer_count
                        + ebgp_peer_count,
                        check_id="startup_bgp_session_verification",
                    ),
                    create_bgp_rib_fib_consistency_check(),
                    create_bgp_convergence_check(
                        convergence_threshold=700,
                        check_id="postcheck_bgp_convergence_time",
                    ),
                ],
                stages=[
                    create_steps_stage(
                        steps=[
                            create_custom_step(
                                description="Route churn scaling test across multiple prefix counts",
                                params_dict={
                                    "custom_step_name": "test_bgp_route_churn_scaling_eos_bgp_plus_plus",
                                    "prefix_configs": [
                                        list(pc) for pc in prefix_configs
                                    ],
                                    "churn_count": churn_count,
                                    "soak_duration_seconds": soak_duration_seconds,
                                    "max_convergence_time_seconds": max_convergence_time_seconds,
                                    "hostname": device_name,
                                    "ixia_interface_ebgp": ixia_interface_mimic_ebgp,
                                    "ixia_interface_ibgp": ixia_interface_mimic_ibgp,
                                },
                            ),
                        ]
                    ),
                ],
            ),
        ],
    )


# =============================================================================
# BGP++ bounded ECMP sets (legacy case9)
# =============================================================================


def create_bgp_ebb_scaling_bounded_ecmp_sets_test_config(
    physical_inventory: PhysicalInventory,
    *,
    name: str,
    ebgp_peer_count_v6: int = 128,
    ibgp_peer_count_v6: int = 128,
    ebgp_peer_count_v4: int = 128,
    ibgp_peer_count_v4: int = 128,
    ebgp_remote_as: int = 65334,
    ibgp_remote_as: int = 64981,
    ixia_ebgp_ic_parent_network_v6: str = "2401:db00:e50d:11:8",
    ixia_ibgp_ic_parent_network_v6: str = "2401:db00:e50d:11:9",
    ixia_ebgp_ic_parent_network_v4: str = "10.163.28",
    ixia_ibgp_ic_parent_network_v4: str = "10.164.28",
    prefix_count: int = 5000,
    ssh_user: str = "admin",
    ssh_password: str | None = None,
    peergroup_ebgp_v6: str = "EB-FA-V6",
    peergroup_ebgp_v4: str = "EB-FA-V4",
    peergroup_ibgp_v6: str = "EB-EB-V6",
    peergroup_ibgp_v4: str = "EB-EB-V4",
    enable_update_group: bool = False,
    update_group_config: t.Optional[t.Dict[str, t.Any]] = None,
    setup_tasks: list | None = None,
    log_collection_timeout: int | None = None,
    host_os_type_map: dict[str, taac_types.DeviceOsType] | None = None,
) -> TestConfig:
    """BGP++ bounded-ECMP-sets TestConfig -- Arista perf-scaling case 9.

    Byte-wise identical to the legacy
    ``test_config_performance_scaling_case9.test_config_for_bgp_plus_plus_on_ebb_arista_bounded_ecmp_sets``
    factory. Callers (bag012 conveyor) that supply ``setup_tasks`` verbatim
    (from ``get_update_packing_setup_tasks``) skip the in-shell managed
    fallback below, matching the legacy ``setup_tasks is None`` gate.
    """
    if ssh_password is None:
        ssh_password = os.environ.get("TAAC_EBB_LAB_DEVICE_PASSWORD", "dnepit")

    device_name = physical_inventory.device_name
    ixia_interface_mimic_ebgp = physical_inventory.ixia_ports[0][0]
    ixia_interface_mimic_ibgp = physical_inventory.ixia_ports[1][0]
    host_driver_args = physical_inventory.host_driver_args
    oss_mock_device_data = physical_inventory.oss_mock_device_data
    resolved_host_os_type_map = (
        host_os_type_map
        if host_os_type_map is not None
        else {device_name: taac_types.DeviceOsType.ARISTA_FBOSS}
    )
    if setup_tasks is None:
        setup_tasks = [
            create_interface_ip_configuration_task(
                interface=ixia_interface_mimic_ebgp,
                peer_count=ebgp_peer_count_v6,
                ipv4_base_network=ixia_ebgp_ic_parent_network_v4,
                ipv6_base_network=ixia_ebgp_ic_parent_network_v6,
                address_families=["ipv6", "ipv4"],
                clear_existing=True,
                hostname=device_name,
                ixia_needed=True,
            ),
            create_interface_ip_configuration_task(
                interface=ixia_interface_mimic_ibgp,
                peer_count=ibgp_peer_count_v6,
                ipv4_base_network=ixia_ibgp_ic_parent_network_v4,
                ipv6_base_network=ixia_ibgp_ic_parent_network_v6,
                address_families=["ipv6", "ipv4"],
                clear_existing=True,
                hostname=device_name,
                ixia_needed=True,
            ),
        ]

        startup_flags = {"agent_thrift_recv_timeout_ms": "160000"}
        startup_flag_cmds = []
        for flag_name, flag_value in startup_flags.items():
            startup_flag_cmds += [
                f"bash sudo sed -i '/{flag_name}/d' {_RUN_BGPCPP_SCRIPT_PATH}",
                f"bash sudo sed -i '/--max_rss_size/s/[^\\\\]$/& \\\\/' "
                f"{_RUN_BGPCPP_SCRIPT_PATH}",
                f"bash sudo sed -i '/--max_rss_size/a\\      "
                f"--{flag_name}={flag_value}' {_RUN_BGPCPP_SCRIPT_PATH}",
            ]
        setup_tasks.append(
            create_run_commands_on_shell_task(
                hostname=device_name,
                cmds=startup_flag_cmds,
                set_outer_hostname=True,
                ixia_needed=True,
            )
        )

        peers = (
            _generate_ixia_v6_peer_entries_for_bgpcpp(
                remote_as=ebgp_remote_as,
                ixia_ipv6_base=ixia_ebgp_ic_parent_network_v6,
                peer_count=ebgp_peer_count_v6,
                peer_group_v6=peergroup_ebgp_v6,
                start_offset=16,
            )
            + _generate_ixia_v4_peer_entries_for_bgpcpp(
                remote_as=ebgp_remote_as,
                ixia_ipv4_base=ixia_ebgp_ic_parent_network_v4,
                peer_count=ebgp_peer_count_v4,
                peer_group_v4=peergroup_ebgp_v4,
                start_offset=10,
            )
            + _generate_ixia_v6_peer_entries_for_bgpcpp(
                remote_as=ibgp_remote_as,
                ixia_ipv6_base=ixia_ibgp_ic_parent_network_v6,
                peer_count=ibgp_peer_count_v6,
                peer_group_v6=peergroup_ibgp_v6,
                start_offset=16,
            )
            + _generate_ixia_v4_peer_entries_for_bgpcpp(
                remote_as=ibgp_remote_as,
                ixia_ipv4_base=ixia_ibgp_ic_parent_network_v4,
                peer_count=ibgp_peer_count_v4,
                peer_group_v4=peergroup_ibgp_v4,
                start_offset=10,
            )
        )
        setup_tasks.extend(
            _generate_bgpcpp_peers_modification_tasks(
                bgpcpp_device=device_name,
                router_id=None,
                peers=peers,
            )
        )

        if enable_update_group:
            ug_config = (
                update_group_config
                if update_group_config is not None
                else UPDATE_GROUP_CONFIG
            )
            setup_tasks.append(
                create_run_commands_on_shell_task(
                    hostname=device_name,
                    cmds=[
                        'bash python3 -c "'
                        "import json; "
                        f"f=open('{_BGPCPP_CONFIG_PATH}'); c=json.load(f); f.close(); "
                        "s=c.setdefault('bgp_setting_config',{}); "
                        "s['enable_update_group']=True; "
                        f"s['update_group_config']={ug_config!r}; "
                        f"f=open('{_BGPCPP_CONFIG_PATH}','w'); "
                        "json.dump(c,f,indent=2); f.close(); "
                        "print('Patched bgp_setting_config update_group')"
                        '"',
                    ],
                    set_outer_hostname=True,
                    ixia_needed=True,
                )
            )

        setup_tasks.append(
            create_validate_bgpcpp_config_on_device_task(
                hostname=device_name,
                config_path=_BGPCPP_CONFIG_PATH,
                ixia_needed=True,
            )
        )

        setup_tasks.append(
            create_arista_daemon_control_task(
                hostname=device_name,
                daemon_name="Bgp",
                action="disable",
                ixia_needed=True,
            )
        )
        setup_tasks.append(
            create_arista_daemon_control_task(
                hostname=device_name,
                daemon_name="Bgp",
                action="enable",
                ixia_needed=True,
            )
        )

    if (
        ebgp_peer_count_v6,
        ibgp_peer_count_v6,
        ebgp_peer_count_v4,
        ibgp_peer_count_v4,
        prefix_count,
    ) != (128, 128, 128, 128, 5_000):
        raise ValueError(
            "DICE bounded-ECMP qualification uses its checked 128/5000 shape"
        )
    topology = replace(
        BOUNDED_ECMP,
        endpoints=tuple(
            replace(endpoint, setup_mode="skip") if endpoint.role == "dut" else endpoint
            for endpoint in BOUNDED_ECMP.endpoints
        ),
    )
    compiled = topology.bind_to_inventory(
        physical_inventory=physical_inventory,
        port_map=BOUNDED_ECMP_PORT_MAP,
        parent_networks={
            "ebgp_v6": ixia_ebgp_ic_parent_network_v6,
            "ebgp_v4": ixia_ebgp_ic_parent_network_v4,
            "ibgp_v6": ixia_ibgp_ic_parent_network_v6,
            "ibgp_v4": ixia_ibgp_ic_parent_network_v4,
        },
        peer_groups=BOUNDED_ECMP_PEER_GROUPS,
        as_numbers={"ebgp": ebgp_remote_as, "ibgp": ibgp_remote_as},
        device_config_override=RoutingDeviceConfig(
            openr_mode=OpenRMode.NONE,
            update_group_enable=enable_update_group,
            update_group_config=(
                tuple((update_group_config or UPDATE_GROUP_CONFIG).items())
                if enable_update_group
                else ()
            ),
        ),
    ).compile()
    return TestConfig(
        name=name,
        skip_ixia_protocol_verification=True,
        log_collection_timeout=log_collection_timeout,
        basset_pool="dne.test",
        endpoints=compiled.endpoints,
        host_driver_args=host_driver_args,
        oss_mock_device_data=oss_mock_device_data,
        host_os_type_map=resolved_host_os_type_map,
        startup_checks=[],
        setup_tasks=setup_tasks,
        teardown_tasks=[],
        basic_port_configs=compiled.basic_port_configs,
        playbooks=[
            create_bgp_plus_plus_arista_bounded_ecmp_sets_playbook(
                device_name=device_name,
            ),
        ],
    )
