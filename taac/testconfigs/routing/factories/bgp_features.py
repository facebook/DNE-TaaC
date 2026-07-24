# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""BGP feature testconfig factories (fast-reset / weight / well-known-communities / enforce-first-as / MED).

Wave 5B.1 — moved from
``testconfigs/routing/ebb/test_config_bgp_fast_reset_feature.py``,
``testconfigs/routing/ebb/test_config_bgp_weight_feature.py`` and
``testconfigs/routing/ebb/test_config_well_known_communities.py``. Wave 5B.2
extends with ``create_bgp_feature_enforce_first_as_test_config`` (from
``test_config_bgp_enforce_first_as_feature.py``) and
``create_bgp_feature_med_test_config`` (from
``test_config_bgp_med_feature.py``). Each factory takes
``(physical_inventory: PhysicalInventory, *, name: str, ...)`` and returns a ``TestConfig`` whose
serialized form is byte-wise identical to the legacy factory outputs
(golden manifest hashes preserved verbatim). DUT identity
(``device_name``, IXIA port map, direct_ixia_connections, lab
host_driver_args, oss_mock_device_data, host_os_type_map) is derived from
``physical_inventory``; the remaining workload knobs stay as kwargs with defaults
matching the legacy eb03.lab.ash6 wrappers.

Playbook factories (``build_fast_reset_playbook``,
``build_bgp_weight_playbook``, ``build_bgp_well_known_community_playbook``,
``build_enforce_first_as_playbook``, ``build_bgp_med_playbook``) are
imported from ``playbook_definitions`` verbatim so the playbook snapshot
manifest ``__module__`` filter still picks them up.

See ../README.md §3.
"""

import os

from taac.health_checks.healthcheck_definitions import (
    create_bgp_rib_fib_consistency_check,
    create_bgp_session_establish_check,
    create_bgp_session_snapshot_check,
    create_core_dumps_snapshot_check,
    create_next_hop_count_check,
)
from taac.playbooks.playbook_definitions import (
    build_bgp_med_playbook,
    build_bgp_weight_playbook,
    build_bgp_well_known_community_playbook,
    build_enforce_first_as_playbook,
    build_fast_reset_playbook,
)
from taac.routing.ebb.arista_feature_testing.ixia_configs_for_enforce_first_as_test import (
    create_enforce_first_as_test_basic_port_configs,
)
from taac.routing.ebb.arista_feature_testing.ixia_configs_for_fast_reset_test import (
    create_fast_reset_test_basic_port_configs,
)
from taac.routing.ebb.arista_feature_testing.ixia_configs_for_med_test import (
    create_med_test_basic_port_configs,
)
from taac.routing.ebb.arista_feature_testing.ixia_configs_for_weight_test import (
    create_weight_test_basic_port_configs,
)
from taac.routing.ebb.arista_feature_testing.ixia_configs_for_well_known_community_test import (
    create_well_known_community_test_basic_port_configs,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_advertise_withdraw_prefixes_step,
    create_bgp_prefixes_med_value_step,
    create_custom_step,
    create_ixia_device_group_toggle_step,
    create_ixia_packet_capture_step,
    create_longevity_step,
    create_run_task_step,
)
from taac.task_definitions import (
    create_add_bgp_weight_policy_task,
    create_disable_med_comparison_task,
    create_invoke_ixia_api_task,
    create_ixia_enable_disable_bgp_prefixes_task,
    create_replace_bgp_peers_task,
    create_restore_bgp_peers_task,
    create_run_commands_on_shell_task,
    create_set_peer_group_enforce_first_as_task,
)
from taac.testconfigs.routing.physical_inventory import (
    PhysicalInventory,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import DirectIxiaConnection, Endpoint, TestConfig


__all__ = [
    "create_bgp_feature_enforce_first_as_test_config",
    "create_bgp_feature_fast_reset_test_config",
    "create_bgp_feature_med_test_config",
    "create_bgp_feature_weight_test_config",
    "create_bgp_feature_well_known_communities_test_config",
]


def _feature_ssh_password(physical_inventory: PhysicalInventory) -> str:
    """Return the lab SSH password for ``physical_inventory``.

    Uses the physical_inventory's declared password env-var (matches the
    ``physical_inventory.host_driver_args`` payload built at PhysicalInventory construction);
    falls back to ``"dnepit"`` when the env var is unset -- byte-identical
    with the legacy wrappers whose ``_LAB_DEVICE_PASSWORD`` also fell back
    to ``"dnepit"``.
    """
    env_var = (
        physical_inventory.lab_device_password_env_var or "TAAC_EBB_LAB_DEVICE_PASSWORD"
    )
    return os.environ.get(env_var, "dnepit")  # pragma: allowlist secret


# =============================================================================
# BGP fast reset (legacy test_config_bgp_fast_reset_feature)
# =============================================================================


def create_bgp_feature_fast_reset_test_config(
    physical_inventory: PhysicalInventory,
    *,
    name: str,
    ebgp_remote_as: int = 65334,
    ixia_ebgp_ic_parent_networks_v6: list[str] | None = None,
    ixia_ebgp_ic_parent_networks_v4: list[str] | None = None,
    peer_groups: list[str] | None = None,
    ssh_user: str = "admin",
    ebgp_peer_count_per_interface: int = 10,
    prefix_count: int = 100,
    ebgp_route_acceptance_communities: list[str] | None = None,
    test_address_families: list[str] | None = None,
    max_teardown_time_seconds: int = 20,
    hold_timer_seconds: int = 90,  # noqa: ARG001 -- kept for API compat with legacy wrapper
    convergence_wait_seconds: int = 60,
    link_down_duration_seconds: int = 30,
    log_collection_timeout: int | None = None,
) -> TestConfig:
    """BGP fast neighbor tear-down TestConfig -- Arista BGP++ feature test.

    Byte-wise identical to the legacy
    ``test_config_bgp_fast_reset_feature.test_config_for_bgp_fast_reset_feature``
    factory invoked from the ``ARISTA_BGP_FAST_RESET_FEATURE_TEST`` wrapper on
    ``eb03.lab.ash6``. DUT identity + IXIA port map + lab host wiring are
    derived from ``physical_inventory``; the remaining workload knobs keep the wrapper's
    default values.
    """
    if ixia_ebgp_ic_parent_networks_v6 is None:
        ixia_ebgp_ic_parent_networks_v6 = ["2401:db00:e50d:11:8"]
    if ixia_ebgp_ic_parent_networks_v4 is None:
        ixia_ebgp_ic_parent_networks_v4 = ["10.163.28"]
    if ebgp_route_acceptance_communities is None:
        ebgp_route_acceptance_communities = ["65529:39744"]
    if test_address_families is None:
        test_address_families = ["ipv6"]
    if peer_groups is None:
        peer_groups = ["EB-FA-V6"]

    device_name = physical_inventory.device_name
    # Legacy wrapper drives only one eBGP port (the eBGP slot on eb03).
    ebgp_iface, ebgp_port = physical_inventory.ixia_ports[0]
    ixia_interfaces_ebgp = [ebgp_iface]
    ssh_password = _feature_ssh_password(physical_inventory)

    host_driver_args = physical_inventory.host_driver_args
    oss_mock_device_data = physical_inventory.oss_mock_device_data
    host_os_type_map = {device_name: taac_types.DeviceOsType.ARISTA_FBOSS}
    direct_ixia_connections = [
        DirectIxiaConnection(
            interface=ebgp_iface,
            ixia_chassis_ip=physical_inventory.ixia_chassis_ip,
            ixia_port=ebgp_port,
        ),
    ]

    ixia_interface_ibgp = None
    ibgp_local_as = 0
    ibgp_peer_count = 10
    ixia_ibgp_ic_parent_network_v6 = ""
    ixia_ibgp_ic_parent_network_v4 = ""

    # Calculate total peer counts (matches legacy factory arithmetic).
    num_afs = len(test_address_families)
    num_ebgp_interfaces = len(ixia_interfaces_ebgp)
    total_ebgp_peers = ebgp_peer_count_per_interface * num_ebgp_interfaces * num_afs
    total_ibgp_peers = ibgp_peer_count * num_afs if ixia_interface_ibgp else 0
    total_peers = total_ebgp_peers + total_ibgp_peers

    all_ixia_ports = list(ixia_interfaces_ebgp)
    if ixia_interface_ibgp:
        all_ixia_ports.append(ixia_interface_ibgp)

    replace_peer_groups = []
    for idx, iface in enumerate(ixia_interfaces_ebgp):
        if "ipv6" in test_address_families and idx < len(
            ixia_ebgp_ic_parent_networks_v6
        ):
            replace_peer_groups.append(
                {
                    "peer_group_name": "EB-FA-V6",
                    "remote_as": ebgp_remote_as,
                    "base_network": ixia_ebgp_ic_parent_networks_v6[idx],
                    "is_v6": True,
                    "peer_count": ebgp_peer_count_per_interface,
                    "description_prefix": f"Test eBGP V6 Peer {iface}",
                }
            )
        if "ipv4" in test_address_families and idx < len(
            ixia_ebgp_ic_parent_networks_v4
        ):
            replace_peer_groups.append(
                {
                    "peer_group_name": "EB-FA-V4",
                    "remote_as": ebgp_remote_as,
                    "base_network": ixia_ebgp_ic_parent_networks_v4[idx],
                    "is_v6": False,
                    "peer_count": ebgp_peer_count_per_interface,
                    "description_prefix": f"Test eBGP V4 Peer {iface}",
                }
            )

    if ixia_interface_ibgp and ibgp_local_as:
        if "ipv6" in test_address_families and ixia_ibgp_ic_parent_network_v6:
            replace_peer_groups.append(
                {
                    "peer_group_name": "EB-EB-V6",
                    "remote_as": ibgp_local_as,
                    "base_network": ixia_ibgp_ic_parent_network_v6,
                    "is_v6": True,
                    "peer_count": ibgp_peer_count,
                    "description_prefix": "Test iBGP V6 Listener",
                }
            )
        if "ipv4" in test_address_families and ixia_ibgp_ic_parent_network_v4:
            replace_peer_groups.append(
                {
                    "peer_group_name": "EB-EB-V4",
                    "remote_as": ibgp_local_as,
                    "base_network": ixia_ibgp_ic_parent_network_v4,
                    "is_v6": False,
                    "peer_count": ibgp_peer_count,
                    "description_prefix": "Test iBGP V4 Listener",
                }
            )

    return TestConfig(
        name=name,
        skip_ixia_protocol_verification=True,
        log_collection_timeout=log_collection_timeout,
        basset_pool="dne.test",
        endpoints=[
            Endpoint(
                name=device_name,
                dut=True,
                ixia_ports=all_ixia_ports,
                direct_ixia_connections=direct_ixia_connections,
            ),
        ],
        host_driver_args=host_driver_args,
        oss_mock_device_data=oss_mock_device_data,
        host_os_type_map=host_os_type_map,
        startup_checks=[],
        setup_tasks=[
            create_replace_bgp_peers_task(
                hostname=device_name,
                peer_configs=replace_peer_groups,
            ),
            create_run_commands_on_shell_task(
                hostname=device_name,
                cmds=[
                    "configure\n"
                    + "\n".join(
                        f"interface {iface}\nno shutdown"
                        for iface in ixia_interfaces_ebgp
                    )
                    + "\nend",
                ],
            ),
        ],
        teardown_tasks=[
            create_run_commands_on_shell_task(
                hostname=device_name,
                cmds=[
                    "configure\n"
                    + "\n".join(
                        f"interface {iface}\nno shutdown"
                        for iface in ixia_interfaces_ebgp
                    )
                    + "\nend",
                ],
            ),
            create_invoke_ixia_api_task(
                api_name="toggle_device_groups",
                args_dict={
                    "enable": False,
                    "device_group_name_regex": ".*",
                },
            ),
            create_restore_bgp_peers_task(
                hostname=device_name,
            ),
        ],
        basic_port_configs=create_fast_reset_test_basic_port_configs(
            device_name=device_name,
            ixia_interfaces_ebgp=ixia_interfaces_ebgp,
            ebgp_peer_count_per_interface=ebgp_peer_count_per_interface,
            ebgp_remote_as=ebgp_remote_as,
            ixia_ebgp_ic_parent_networks_v6=ixia_ebgp_ic_parent_networks_v6,
            ixia_ebgp_ic_parent_networks_v4=ixia_ebgp_ic_parent_networks_v4,
            ixia_interface_ibgp=ixia_interface_ibgp,
            ibgp_peer_count=ibgp_peer_count,
            ibgp_local_as=ibgp_local_as,
            ixia_ibgp_ic_parent_network_v6=ixia_ibgp_ic_parent_network_v6,
            ixia_ibgp_ic_parent_network_v4=ixia_ibgp_ic_parent_network_v4,
            prefix_count=prefix_count,
            ebgp_route_acceptance_communities=ebgp_route_acceptance_communities,
            test_address_families=test_address_families,
        ),
        playbooks=[
            build_fast_reset_playbook(
                name="BGP_Fast_Reset_Test_Phase0_Single_Link_Failure",
                setup_steps=[
                    create_ixia_device_group_toggle_step(
                        enable=True,
                        device_group_name_regex=".*",
                        description="Enable all BGP peer device groups",
                    ),
                ],
                periodic_tasks=[],
                prechecks=[
                    create_bgp_session_establish_check(
                        expected_established_sessions_static=total_peers,
                        check_id="verify_all_bgp_sessions_established_phase0",
                    ),
                ],
                snapshot_checks=[
                    create_bgp_session_snapshot_check(
                        skip_flap_check=True, skip_uptime_check=True
                    ),
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "simulate_multiple_link_failures",
                                    "hostname": device_name,
                                    "interfaces": list(ixia_interfaces_ebgp),
                                    "action": "enable",
                                    "ssh_user": ssh_user,
                                    "ssh_password": ssh_password,
                                },
                                description="Restore all eBGP interfaces (cleanup from previous run)",
                            ),
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for BGP convergence ({convergence_wait_seconds}s)",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "record_bgp_session_baseline",
                                    "hostname": device_name,
                                },
                                description="Record baseline BGP session state",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "simulate_link_failure",
                                    "hostname": device_name,
                                    "interface": ixia_interfaces_ebgp[0],
                                    "action": "disable",
                                    "ssh_user": ssh_user,
                                    "ssh_password": ssh_password,
                                },
                                description="Simulate single link failure (shutdown first eBGP interface)",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_fast_route_withdrawal",
                                    "hostname": device_name,
                                    "max_withdrawal_time_seconds": max_teardown_time_seconds,
                                    "expected_withdrawn_routes": 0,
                                },
                                description=f"Verify fast route withdrawal (within {max_teardown_time_seconds}s)",
                            ),
                            create_longevity_step(
                                duration=link_down_duration_seconds,
                                description=f"Keep link down ({link_down_duration_seconds}s)",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "simulate_link_failure",
                                    "hostname": device_name,
                                    "interface": ixia_interfaces_ebgp[0],
                                    "action": "enable",
                                    "ssh_user": ssh_user,
                                    "ssh_password": ssh_password,
                                },
                                description="Restore link (no shutdown first eBGP interface)",
                            ),
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for session recovery ({convergence_wait_seconds}s)",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_sessions_established",
                                    "hostname": device_name,
                                    "expected_session_count": total_peers,
                                },
                                description="Verify all sessions recovered",
                            ),
                        ],
                    ),
                ],
            ),
            build_fast_reset_playbook(
                name="BGP_Fast_Reset_Test_Phase1_Multiple_Simultaneous_Failures",
                setup_steps=[
                    create_ixia_device_group_toggle_step(
                        enable=True,
                        device_group_name_regex=".*",
                        description="Enable all BGP peer device groups",
                    ),
                ],
                periodic_tasks=[],
                prechecks=[],
                snapshot_checks=[
                    create_bgp_session_snapshot_check(
                        skip_flap_check=True, skip_uptime_check=True
                    ),
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[
                    create_bgp_rib_fib_consistency_check(),
                ],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "simulate_multiple_link_failures",
                                    "hostname": device_name,
                                    "interfaces": list(ixia_interfaces_ebgp),
                                    "action": "enable",
                                    "ssh_user": ssh_user,
                                    "ssh_password": ssh_password,
                                },
                                description="Restore all eBGP interfaces (cleanup from previous phase)",
                            ),
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for BGP convergence ({convergence_wait_seconds}s)",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_sessions_established",
                                    "hostname": device_name,
                                    "expected_session_count": total_peers,
                                },
                                description="Verify all sessions established before test",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "record_bgp_session_baseline",
                                    "hostname": device_name,
                                },
                                description="Record baseline BGP session state",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "simulate_multiple_link_failures",
                                    "hostname": device_name,
                                    "interfaces": list(ixia_interfaces_ebgp),
                                    "action": "disable",
                                    "ssh_user": ssh_user,
                                    "ssh_password": ssh_password,
                                },
                                description="Simulate multiple simultaneous link failures",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_fast_route_withdrawal",
                                    "hostname": device_name,
                                    "max_withdrawal_time_seconds": max_teardown_time_seconds,
                                    "expected_withdrawn_routes": 0,
                                },
                                description=f"Verify fast route withdrawal for all eBGP routes (within {max_teardown_time_seconds}s)",
                            ),
                            create_longevity_step(
                                duration=link_down_duration_seconds,
                                description=f"Keep links down ({link_down_duration_seconds}s)",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "simulate_multiple_link_failures",
                                    "hostname": device_name,
                                    "interfaces": list(ixia_interfaces_ebgp),
                                    "action": "enable",
                                    "ssh_user": ssh_user,
                                    "ssh_password": ssh_password,
                                },
                                description="Restore all links simultaneously",
                            ),
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for session recovery ({convergence_wait_seconds}s)",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_sessions_established",
                                    "hostname": device_name,
                                    "expected_session_count": total_peers,
                                },
                                description="Verify all sessions recovered after simultaneous recovery",
                            ),
                        ],
                    ),
                ],
            ),
            build_fast_reset_playbook(
                name="BGP_Fast_Reset_Test_Phase2_Link_Flap",
                setup_steps=[
                    create_ixia_device_group_toggle_step(
                        enable=True,
                        device_group_name_regex=".*",
                        description="Enable all BGP peer device groups",
                    ),
                ],
                periodic_tasks=[],
                prechecks=[],
                snapshot_checks=[
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "simulate_multiple_link_failures",
                                    "hostname": device_name,
                                    "interfaces": list(ixia_interfaces_ebgp),
                                    "action": "enable",
                                    "ssh_user": ssh_user,
                                    "ssh_password": ssh_password,
                                },
                                description="Restore all eBGP interfaces (cleanup from previous test)",
                            ),
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for BGP convergence ({convergence_wait_seconds}s)",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_sessions_established",
                                    "hostname": device_name,
                                    "expected_session_count": total_peers,
                                },
                                description="Verify all sessions established before link flap",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "perform_link_flap",
                                    "hostname": device_name,
                                    "interface": ixia_interfaces_ebgp[0],
                                    "flap_count": 3,
                                    "down_duration_seconds": 5,
                                    "up_duration_seconds": 10,
                                    "ssh_user": ssh_user,
                                    "ssh_password": ssh_password,
                                },
                                description="Perform rapid link flap (down-up cycle)",
                            ),
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for session stabilization ({convergence_wait_seconds}s)",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_sessions_established",
                                    "hostname": device_name,
                                    "expected_session_count": total_peers,
                                },
                                description="Verify all sessions recovered after link flap",
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )


# =============================================================================
# BGP weight feature (legacy test_config_bgp_weight_feature)
# =============================================================================


def create_bgp_feature_weight_test_config(
    physical_inventory: PhysicalInventory,
    *,
    name: str,
    ebgp_remote_as: int = 65334,
    ixia_ebgp_ic_parent_network_v6: str = "2401:db00:e50d:11:8",
    ixia_ebgp_ic_parent_network_v4: str = "10.163.28",
    ibgp_local_as: int = 64981,
    ixia_ibgp_ic_parent_network_v6: str = "2401:db00:e50d:11:9",
    ixia_ibgp_ic_parent_network_v4: str = "10.164.28",
    target_policy: str = "EB-FA-IN",
    ssh_user: str = "admin",
    ebgp_peer_count_group1: int = 50,
    ebgp_peer_count_group2: int = 50,
    ibgp_peer_count: int = 50,
    prefix_count: int = 100,
    weight_low: int = 10,
    weight_high: int = 20,
    weight_low_community: str = "65001:10",
    weight_high_community: str = "65001:20",
    ebgp_route_acceptance_communities: list[str] | None = None,
    test_address_families: list[str] | None = None,
    convergence_wait_seconds: int = 120,
    log_collection_timeout: int | None = None,
) -> TestConfig:
    """BGP weight-attribute TestConfig -- Arista BGP++ feature test.

    Byte-wise identical to the legacy
    ``test_config_bgp_weight_feature.test_config_for_bgp_weight_feature``
    factory invoked from the ``ARISTA_BGP_WEIGHT_FEATURE_TEST`` wrapper on
    ``eb03.lab.ash6``.
    """
    if ebgp_route_acceptance_communities is None:
        ebgp_route_acceptance_communities = ["65529:39744"]
    if test_address_families is None:
        test_address_families = ["ipv6", "ipv4"]

    device_name = physical_inventory.device_name
    ebgp_iface, ebgp_port = physical_inventory.ixia_ports[0]
    ibgp_iface, ibgp_port = physical_inventory.ixia_ports[1]
    ixia_interface_ebgp = ebgp_iface
    ixia_interface_ibgp = ibgp_iface
    ssh_password = _feature_ssh_password(physical_inventory)

    host_driver_args = physical_inventory.host_driver_args
    oss_mock_device_data = physical_inventory.oss_mock_device_data
    host_os_type_map = {device_name: taac_types.DeviceOsType.ARISTA_FBOSS}
    direct_ixia_connections = [
        DirectIxiaConnection(
            interface=ebgp_iface,
            ixia_chassis_ip=physical_inventory.ixia_chassis_ip,
            ixia_port=ebgp_port,
        ),
        DirectIxiaConnection(
            interface=ibgp_iface,
            ixia_chassis_ip=physical_inventory.ixia_chassis_ip,
            ixia_port=ibgp_port,
        ),
    ]

    num_afs = len(test_address_families)
    total_ebgp_peers = (ebgp_peer_count_group1 + ebgp_peer_count_group2) * num_afs
    total_ibgp_peers = ibgp_peer_count * num_afs
    total_peers = total_ebgp_peers + total_ibgp_peers
    total_ebgp_per_af = ebgp_peer_count_group1 + ebgp_peer_count_group2

    peer_groups = []
    if "ipv6" in test_address_families:
        peer_groups.append(
            {
                "peer_group_name": "EB-FA-V6",
                "remote_as": ebgp_remote_as,
                "base_network": ixia_ebgp_ic_parent_network_v6,
                "is_v6": True,
                "peer_count": total_ebgp_per_af,
                "description_prefix": "eBGP V6 Peer",
            }
        )
        peer_groups.append(
            {
                "peer_group_name": "EB-EB-V6",
                "remote_as": ibgp_local_as,
                "base_network": ixia_ibgp_ic_parent_network_v6,
                "is_v6": True,
                "peer_count": ibgp_peer_count,
                "description_prefix": "iBGP V6 Listener",
            }
        )
    if "ipv4" in test_address_families:
        peer_groups.append(
            {
                "peer_group_name": "EB-FA-V4",
                "remote_as": ebgp_remote_as,
                "base_network": ixia_ebgp_ic_parent_network_v4,
                "is_v6": False,
                "peer_count": total_ebgp_per_af,
                "description_prefix": "eBGP V4 Peer",
            }
        )
        peer_groups.append(
            {
                "peer_group_name": "EB-EB-V4",
                "remote_as": ibgp_local_as,
                "base_network": ixia_ibgp_ic_parent_network_v4,
                "is_v6": False,
                "peer_count": ibgp_peer_count,
                "description_prefix": "iBGP V4 Listener",
            }
        )

    community_weight_map = {
        weight_low_community: weight_low,
        weight_high_community: weight_high,
    }

    setup_tasks = [
        create_replace_bgp_peers_task(
            hostname=device_name,
            peer_configs=peer_groups,
        ),
        create_add_bgp_weight_policy_task(
            hostname=device_name,
            target_policy=target_policy,
            community_weight_map=community_weight_map,
            ssh_user=ssh_user,
            ssh_password=ssh_password,
        ),
        create_ixia_enable_disable_bgp_prefixes_task(
            enable=False,
            prefix_pool_regex="PREFIX_POOL_.*",
            prefix_start_index=0,
        ),
    ]

    return TestConfig(
        name=name,
        skip_ixia_protocol_verification=True,
        log_collection_timeout=log_collection_timeout,
        basset_pool="dne.test",
        endpoints=[
            Endpoint(
                name=device_name,
                dut=True,
                ixia_ports=[ixia_interface_ebgp, ixia_interface_ibgp],
                direct_ixia_connections=direct_ixia_connections,
            ),
        ],
        host_driver_args=host_driver_args,
        oss_mock_device_data=oss_mock_device_data,
        host_os_type_map=host_os_type_map,
        startup_checks=[],
        setup_tasks=setup_tasks,
        teardown_tasks=[
            create_invoke_ixia_api_task(
                api_name="toggle_device_groups",
                args_dict={
                    "enable": False,
                    "device_group_name_regex": ".*",
                },
            ),
            create_restore_bgp_peers_task(
                hostname=device_name,
            ),
        ],
        basic_port_configs=create_weight_test_basic_port_configs(
            device_name=device_name,
            ixia_interface_ebgp=ixia_interface_ebgp,
            ebgp_peer_count_group1=ebgp_peer_count_group1,
            ebgp_peer_count_group2=ebgp_peer_count_group2,
            ebgp_remote_as=ebgp_remote_as,
            ixia_ebgp_ic_parent_network_v6=ixia_ebgp_ic_parent_network_v6,
            ixia_ebgp_ic_parent_network_v4=ixia_ebgp_ic_parent_network_v4,
            ixia_interface_ibgp=ixia_interface_ibgp,
            ibgp_peer_count=ibgp_peer_count,
            ibgp_local_as=ibgp_local_as,
            ixia_ibgp_ic_parent_network_v6=ixia_ibgp_ic_parent_network_v6,
            ixia_ibgp_ic_parent_network_v4=ixia_ibgp_ic_parent_network_v4,
            prefix_count=prefix_count,
            weight_10_community=weight_low_community,
            weight_20_community=weight_high_community,
            ebgp_route_acceptance_communities=ebgp_route_acceptance_communities,
            test_address_families=test_address_families,
        ),
        playbooks=[
            build_bgp_weight_playbook(
                name="BGP_Weight_Test_Phase1_Both_Groups_Active",
                setup_steps=[
                    create_ixia_device_group_toggle_step(
                        enable=True,
                        device_group_name_regex=".*",
                        description="Enable all BGP peer device groups",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_WEIGHT_10",
                        prefix_start_index=0,
                        description=f"Advertise routes from eBGP Group 1 (weight {weight_low})",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_WEIGHT_20",
                        prefix_start_index=0,
                        description=f"Advertise routes from eBGP Group 2 (weight {weight_high})",
                    ),
                ],
                periodic_tasks=[],
                prechecks=[
                    create_bgp_session_establish_check(
                        expected_established_sessions_static=total_peers,
                        check_id="verify_all_bgp_sessions_established",
                    ),
                ],
                snapshot_checks=[
                    create_bgp_session_snapshot_check(
                        skip_flap_check=True, skip_uptime_check=True
                    ),
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[
                    create_bgp_session_establish_check(
                        expected_established_sessions_static=total_peers,
                        check_id="verify_bgp_sessions_after_advertisement",
                    ),
                ],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for BGP convergence ({convergence_wait_seconds}s)",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_weight_best_path",
                                    "hostname": device_name,
                                    "expected_weight": weight_high,
                                    "expected_community": weight_high_community,
                                },
                                description=f"Verify routes with weight {weight_high} are selected as best",
                            ),
                        ],
                    ),
                ],
            ),
            build_bgp_weight_playbook(
                name="BGP_Weight_Test_Phase2_Group2_Withdrawn",
                setup_steps=[
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_WEIGHT_20",
                        prefix_start_index=0,
                        description=f"Withdraw routes from eBGP Group 2 (weight {weight_high})",
                    ),
                ],
                periodic_tasks=[],
                prechecks=[],
                snapshot_checks=[
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[
                    create_bgp_rib_fib_consistency_check(),
                ],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for withdrawal convergence ({convergence_wait_seconds}s)",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_weight_best_path",
                                    "hostname": device_name,
                                    "expected_weight": weight_low,
                                    "expected_community": weight_low_community,
                                },
                                description=f"Verify routes with weight {weight_low} are now best",
                            ),
                        ],
                    ),
                ],
            ),
            build_bgp_weight_playbook(
                name="BGP_Weight_Test_Phase3_Group2_Readvertised",
                setup_steps=[
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_WEIGHT_20",
                        prefix_start_index=0,
                        description=f"Re-advertise routes from eBGP Group 2 (weight {weight_high})",
                    ),
                ],
                periodic_tasks=[],
                prechecks=[],
                snapshot_checks=[
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[
                    create_bgp_rib_fib_consistency_check(),
                ],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for re-advertisement convergence ({convergence_wait_seconds}s)",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_weight_best_path",
                                    "hostname": device_name,
                                    "expected_weight": weight_high,
                                    "expected_community": weight_high_community,
                                },
                                description=f"Verify routes with weight {weight_high} are best again",
                            ),
                        ],
                    ),
                ],
            ),
            build_bgp_weight_playbook(
                name="BGP_Weight_Test_Phase4_Weight_Vs_NoWeight",
                setup_steps=[
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_WEIGHT_10",
                        prefix_start_index=0,
                        description="Withdraw weight 10 routes",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_WEIGHT_20$",
                        prefix_start_index=0,
                        description="Withdraw weight 20 routes",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_NO_WEIGHT$",
                        prefix_start_index=0,
                        description="Advertise routes with no weight (default weight 0)",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_WEIGHT_20_VS_NOWEIGHT",
                        prefix_start_index=0,
                        description=f"Advertise same routes with weight {weight_high}",
                    ),
                ],
                periodic_tasks=[],
                prechecks=[],
                snapshot_checks=[
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[
                    create_bgp_rib_fib_consistency_check(),
                ],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for convergence ({convergence_wait_seconds}s)",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_weight_best_path",
                                    "hostname": device_name,
                                    "expected_weight": weight_high,
                                    "expected_community": weight_high_community,
                                    "prefix_filter": "2001:db8:2000::",
                                },
                                description=f"Verify routes with weight {weight_high} are selected over default weight (0)",
                            ),
                        ],
                    ),
                ],
            ),
            build_bgp_weight_playbook(
                name="BGP_Weight_Test_Phase5_ECMP_Equal_Weight",
                setup_steps=[
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_WEIGHT_10",
                        prefix_start_index=0,
                        description="Withdraw weight 10 routes",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_WEIGHT_20$",
                        prefix_start_index=0,
                        description="Withdraw weight 20 routes",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_WEIGHT_20_VS_NOWEIGHT",
                        prefix_start_index=0,
                        description="Withdraw weight 20 vs no-weight routes",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_NO_WEIGHT$",
                        prefix_start_index=0,
                        description="Advertise routes from Group 1 with no weight (default 0)",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_NO_WEIGHT_G2",
                        prefix_start_index=0,
                        description="Advertise same routes from Group 2 with no weight (default 0)",
                    ),
                ],
                periodic_tasks=[],
                prechecks=[],
                snapshot_checks=[
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[
                    create_bgp_rib_fib_consistency_check(),
                    create_next_hop_count_check(
                        min_nexthop_count=2,
                        prefix_subnets=[
                            "2001:db8:2000::/48",
                            "10.200.0.0/16",
                        ],
                        check_id="verify_ecmp_equal_weight",
                    ),
                ],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for convergence ({convergence_wait_seconds}s)",
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )


# =============================================================================
# RFC 1997 well-known community filtering (legacy test_config_well_known_communities)
# =============================================================================


def create_bgp_feature_well_known_communities_test_config(
    physical_inventory: PhysicalInventory,
    *,
    name: str,
    ebgp_remote_as: int = 65334,
    ixia_ebgp_ic_parent_network_v6: str = "2401:db00:e50d:11:8",
    ixia_ebgp_ic_parent_network_v4: str = "10.163.28",
    ibgp_local_as: int = 64981,
    ixia_ibgp_ic_parent_network_v6: str = "2401:db00:e50d:11:9",
    ixia_ibgp_ic_parent_network_v4: str = "10.164.28",
    ssh_user: str = "admin",
    ebgp_peer_count: int = 5,
    ibgp_peer_count: int = 5,
    prefix_count: int = 100,
    ebgp_route_acceptance_communities: list[str] | None = None,
    test_address_families: list[str] | None = None,
    convergence_wait_seconds: int = 60,
    log_collection_timeout: int | None = 600,
) -> TestConfig:
    """RFC 1997 well-known community egress filtering TestConfig.

    Byte-wise identical to the legacy
    ``test_config_well_known_communities.test_config_for_well_known_communities``
    factory invoked from the
    ``EB03_ARISTA_WELL_KNOWN_COMMUNITY_TEST_CONFIG`` wrapper on
    ``eb03.lab.ash6``.
    """
    if ebgp_route_acceptance_communities is None:
        ebgp_route_acceptance_communities = ["65529:39744"]
    if test_address_families is None:
        test_address_families = ["ipv6"]

    device_name = physical_inventory.device_name
    ebgp_iface, ebgp_port = physical_inventory.ixia_ports[0]
    ibgp_iface, ibgp_port = physical_inventory.ixia_ports[1]
    ixia_interface_ebgp = ebgp_iface
    ixia_interface_ibgp = ibgp_iface
    ssh_password = _feature_ssh_password(physical_inventory)

    host_driver_args = physical_inventory.host_driver_args
    oss_mock_device_data = physical_inventory.oss_mock_device_data
    host_os_type_map = {device_name: taac_types.DeviceOsType.ARISTA_FBOSS}
    direct_ixia_connections = [
        DirectIxiaConnection(
            interface=ebgp_iface,
            ixia_chassis_ip=physical_inventory.ixia_chassis_ip,
            ixia_port=ebgp_port,
        ),
        DirectIxiaConnection(
            interface=ibgp_iface,
            ixia_chassis_ip=physical_inventory.ixia_chassis_ip,
            ixia_port=ibgp_port,
        ),
    ]

    peer_groups = []
    if "ipv6" in test_address_families:
        peer_groups.extend(
            [
                {
                    "peer_group_name": "EB-FA-V6",
                    "remote_as": ebgp_remote_as,
                    "base_network": ixia_ebgp_ic_parent_network_v6,
                    "is_v6": True,
                    "peer_count": ebgp_peer_count,
                    "description_prefix": "eBGP V6 Peer",
                },
                {
                    "peer_group_name": "EB-EB-V6",
                    "remote_as": ibgp_local_as,
                    "base_network": ixia_ibgp_ic_parent_network_v6,
                    "is_v6": True,
                    "peer_count": ibgp_peer_count,
                    "description_prefix": "iBGP V6 Peer",
                },
            ]
        )
    if "ipv4" in test_address_families:
        peer_groups.extend(
            [
                {
                    "peer_group_name": "EB-FA-V4",
                    "remote_as": ebgp_remote_as,
                    "base_network": ixia_ebgp_ic_parent_network_v4,
                    "is_v6": False,
                    "peer_count": ebgp_peer_count,
                    "description_prefix": "eBGP V4 Peer",
                },
                {
                    "peer_group_name": "EB-EB-V4",
                    "remote_as": ibgp_local_as,
                    "base_network": ixia_ibgp_ic_parent_network_v4,
                    "is_v6": False,
                    "peer_count": ibgp_peer_count,
                    "description_prefix": "iBGP V4 Peer",
                },
            ]
        )

    all_setup_tasks = [
        create_replace_bgp_peers_task(
            hostname=device_name,
            peer_configs=peer_groups,
            ssh_user=ssh_user,
            ssh_password=ssh_password,
        ),
        create_ixia_enable_disable_bgp_prefixes_task(
            enable=False,
            prefix_pool_regex="PREFIX_POOL_.*",
            prefix_start_index=0,
        ),
    ]

    community_checks = [
        (
            "NO_EXPORT",
            "PREFIX_POOL_.*EBGP_NO_EXPORT$",
            "PREFIX_POOL_.*IBGP_NO_EXPORT$",
            True,
            False,
        ),
        (
            "NO_ADVERTISE",
            "PREFIX_POOL_.*EBGP_NO_ADVERTISE$",
            "PREFIX_POOL_.*IBGP_NO_ADVERTISE$",
            True,
            True,
        ),
        (
            "NO_EXPORT_SUBCONFED",
            "PREFIX_POOL_.*EBGP_NO_EXPORT_SUBCONFED$",
            "PREFIX_POOL_.*IBGP_NO_EXPORT_SUBCONFED$",
            True,
            False,
        ),
        (
            "BASELINE",
            "PREFIX_POOL_.*EBGP_BASELINE$",
            "PREFIX_POOL_.*IBGP_BASELINE$",
            False,
            False,
        ),
    ]

    verification_stages = []
    for stage_idx, (
        community_name,
        ebgp_regex,
        ibgp_regex,
        suppress_ebgp,
        suppress_ibgp,
    ) in enumerate(community_checks, start=1):
        verification_stages.append(
            create_steps_stage(
                iteration=stage_idx,
                steps=[
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex=ebgp_regex,
                        prefix_start_index=0,
                        description=f"Enable eBGP {community_name} prefixes",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex=ibgp_regex,
                        prefix_start_index=0,
                        description=f"Enable iBGP {community_name} prefixes",
                    ),
                    create_longevity_step(
                        duration=convergence_wait_seconds,
                        description=f"Wait {convergence_wait_seconds}s for {community_name} convergence",
                    ),
                    create_custom_step(
                        params_dict={
                            "custom_step_name": "verify_well_known_community_filtering",
                            "hostname": device_name,
                            "community_name": community_name,
                            "expect_suppressed_to_ebgp": suppress_ebgp,
                            "expect_suppressed_to_ibgp": suppress_ibgp,
                        },
                        description=f"Verify {community_name} filtering",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex=ebgp_regex,
                        prefix_start_index=0,
                        description=f"Disable eBGP {community_name} prefixes",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex=ibgp_regex,
                        prefix_start_index=0,
                        description=f"Disable iBGP {community_name} prefixes",
                    ),
                ],
            ),
        )

    playbook_community_filter = build_bgp_well_known_community_playbook(
        name="EB03_RFC1997_WELL_KNOWN_COMMUNITY_FILTER",
        setup_steps=[
            create_ixia_device_group_toggle_step(
                enable=True,
                device_group_name_regex=".*",
                description="Enable all device groups",
            ),
            create_longevity_step(
                duration=30,
                description="Wait for BGP sessions to establish",
            ),
        ],
        periodic_tasks=[],
        prechecks=[],
        snapshot_checks=[
            create_core_dumps_snapshot_check(),
        ],
        postchecks=[
            create_bgp_rib_fib_consistency_check(),
        ],
        stages=verification_stages,
    )

    # Flag-off regression playbook -- constructed but not registered on the
    # TestConfig (matches the legacy factory which prefixes the local variable
    # with ``_`` and never appends it to ``playbooks``). Kept here verbatim so
    # future work can flip it on without hunting for the definition.
    _playbook_flag_off_regression = build_bgp_well_known_community_playbook(  # noqa: F841
        name="EB03_RFC1997_FLAG_OFF_REGRESSION",
        setup_steps=[
            create_run_task_step(
                task_name="set_bgp_setting_config",
                params_dict={
                    "hostname": device_name,
                    "settings": {"enable_well_known_community_filter": False},
                    "ssh_user": ssh_user,
                    "ssh_password": ssh_password,
                    "reload_bgp": True,
                },
                description="Disable well-known community filter (flag off)",
            ),
            create_longevity_step(duration=30, description="Wait for BGP restart"),
            create_ixia_device_group_toggle_step(
                enable=True,
                device_group_name_regex=".*",
                description="Enable all device groups",
            ),
            create_advertise_withdraw_prefixes_step(
                device_name=device_name,
                advertise=True,
                prefix_pool_regex="PREFIX_POOL_.*NO_ADVERTISE$",
                prefix_start_index=0,
                description="Enable NO_ADVERTISE prefixes (filter disabled)",
            ),
        ],
        periodic_tasks=[],
        prechecks=[],
        snapshot_checks=[create_core_dumps_snapshot_check()],
        postchecks=[create_bgp_rib_fib_consistency_check()],
        stages=[
            create_steps_stage(
                iteration=1,
                steps=[
                    create_longevity_step(
                        duration=convergence_wait_seconds,
                        description=f"Wait {convergence_wait_seconds}s for convergence",
                    ),
                    create_custom_step(
                        params_dict={
                            "custom_step_name": "verify_well_known_community_filtering",
                            "hostname": device_name,
                            "community_name": "NO_ADVERTISE",
                            "expect_suppressed_to_ebgp": False,
                            "expect_suppressed_to_ibgp": False,
                        },
                        description="Verify NO_ADVERTISE NOT suppressed (flag off)",
                    ),
                    create_run_task_step(
                        task_name="set_bgp_setting_config",
                        params_dict={
                            "hostname": device_name,
                            "settings": {"enable_well_known_community_filter": True},
                            "ssh_user": ssh_user,
                            "ssh_password": ssh_password,
                            "reload_bgp": True,
                        },
                        description="Re-enable well-known community filter",
                    ),
                ],
            ),
        ],
    )

    return TestConfig(
        name=name,
        skip_ixia_protocol_verification=True,
        log_collection_timeout=log_collection_timeout,
        basset_pool="dne.test",
        endpoints=[
            Endpoint(
                name=device_name,
                dut=True,
                ixia_ports=[ixia_interface_ebgp, ixia_interface_ibgp],
                direct_ixia_connections=direct_ixia_connections,
            ),
        ],
        host_driver_args=host_driver_args,
        oss_mock_device_data=oss_mock_device_data,
        host_os_type_map=host_os_type_map,
        startup_checks=[],
        setup_tasks=all_setup_tasks,
        teardown_tasks=[
            create_invoke_ixia_api_task(
                api_name="toggle_device_groups",
                args_dict={"enable": False, "device_group_name_regex": ".*"},
            ),
            create_restore_bgp_peers_task(
                hostname=device_name,
                ssh_user=ssh_user,
                ssh_password=ssh_password,
            ),
        ],
        basic_port_configs=create_well_known_community_test_basic_port_configs(
            device_name=device_name,
            ixia_interface_ebgp=ixia_interface_ebgp,
            ebgp_peer_count=ebgp_peer_count,
            ebgp_remote_as=ebgp_remote_as,
            ixia_ebgp_ic_parent_network_v6=ixia_ebgp_ic_parent_network_v6,
            ixia_ebgp_ic_parent_network_v4=ixia_ebgp_ic_parent_network_v4,
            ixia_interface_ibgp=ixia_interface_ibgp,
            ibgp_peer_count=ibgp_peer_count,
            ibgp_local_as=ibgp_local_as,
            ixia_ibgp_ic_parent_network_v6=ixia_ibgp_ic_parent_network_v6,
            ixia_ibgp_ic_parent_network_v4=ixia_ibgp_ic_parent_network_v4,
            prefix_count=prefix_count,
            ebgp_route_acceptance_communities=ebgp_route_acceptance_communities,
            test_address_families=test_address_families,
        ),
        playbooks=[
            playbook_community_filter,
        ],
    )


# =============================================================================
# BGP enforce_first_as (legacy test_config_bgp_enforce_first_as_feature)
# =============================================================================


def create_bgp_feature_enforce_first_as_test_config(
    physical_inventory: PhysicalInventory,
    *,
    name: str,
    ebgp_remote_as: int = 65334,
    wrong_first_as: int = 65000,
    ixia_ebgp_ic_parent_network_v6: str = "2401:db00:e50d:11:8",
    ixia_ebgp_ic_parent_network_v4: str = "10.163.28",
    ibgp_local_as: int = 64981,
    ixia_ibgp_ic_parent_network_v6: str = "2401:db00:e50d:11:9",
    ixia_ibgp_ic_parent_network_v4: str = "10.164.28",
    peer_groups: list[str] | None = None,
    ssh_user: str = "admin",
    ebgp_peer_count_valid: int = 10,
    ebgp_peer_count_invalid: int = 10,
    ibgp_peer_count: int = 10,
    prefix_count: int = 500,
    ebgp_route_acceptance_communities: list[str] | None = None,
    test_address_families: list[str] | None = None,
    convergence_wait_seconds: int = 120,
    log_collection_timeout: int | None = None,
) -> TestConfig:
    """BGP enforce_first_as TestConfig -- Arista BGP++ security feature test.

    Byte-wise identical to the legacy
    ``test_config_bgp_enforce_first_as_feature.test_config_for_bgp_enforce_first_as_feature``
    factory invoked from the ``ARISTA_BGP_ENFORCE_FIRST_AS_FEATURE_TEST``
    wrapper on ``eb03.lab.ash6``. DUT identity + IXIA port map + lab host
    wiring are derived from ``physical_inventory``; the remaining workload knobs keep
    the wrapper's default values.
    """
    if ebgp_route_acceptance_communities is None:
        ebgp_route_acceptance_communities = ["65529:39744"]
    if test_address_families is None:
        test_address_families = ["ipv6"]
    if peer_groups is None:
        peer_groups = ["EB-FA-V6"]

    device_name = physical_inventory.device_name
    ebgp_iface, ebgp_port = physical_inventory.ixia_ports[0]
    ibgp_iface, ibgp_port = physical_inventory.ixia_ports[1]
    ixia_interface_ebgp = ebgp_iface
    ixia_interface_ibgp = ibgp_iface
    ssh_password = _feature_ssh_password(physical_inventory)

    host_driver_args = physical_inventory.host_driver_args
    oss_mock_device_data = physical_inventory.oss_mock_device_data
    host_os_type_map = {device_name: taac_types.DeviceOsType.ARISTA_FBOSS}
    direct_ixia_connections = [
        DirectIxiaConnection(
            interface=ebgp_iface,
            ixia_chassis_ip=physical_inventory.ixia_chassis_ip,
            ixia_port=ebgp_port,
        ),
        DirectIxiaConnection(
            interface=ibgp_iface,
            ixia_chassis_ip=physical_inventory.ixia_chassis_ip,
            ixia_port=ibgp_port,
        ),
    ]

    num_afs = len(test_address_families)
    total_ebgp_peers = (ebgp_peer_count_valid + ebgp_peer_count_invalid) * num_afs
    total_ibgp_peers = ibgp_peer_count * num_afs
    total_peers = total_ebgp_peers + total_ibgp_peers
    total_ebgp_per_af = ebgp_peer_count_valid + ebgp_peer_count_invalid

    expected_valid_routes = prefix_count * ebgp_peer_count_valid * num_afs
    expected_invalid_routes = prefix_count * ebgp_peer_count_invalid * num_afs

    valid_prefix_filters: list[str] = []
    invalid_prefix_filters: list[str] = []
    if "ipv6" in test_address_families:
        valid_prefix_filters.append("2001:db8:10")
        invalid_prefix_filters.append("2001:db8:20")
    if "ipv4" in test_address_families:
        valid_prefix_filters.append("10.1")
        invalid_prefix_filters.append("10.2")

    peer_group_configs = []
    if "ipv6" in test_address_families:
        peer_group_configs.append(
            {
                "peer_group_name": "EB-FA-V6",
                "remote_as": ebgp_remote_as,
                "base_network": ixia_ebgp_ic_parent_network_v6,
                "is_v6": True,
                "peer_count": total_ebgp_per_af,
                "description_prefix": "eBGP V6 Peer",
            }
        )
        peer_group_configs.append(
            {
                "peer_group_name": "EB-EB-V6",
                "remote_as": ibgp_local_as,
                "base_network": ixia_ibgp_ic_parent_network_v6,
                "is_v6": True,
                "peer_count": ibgp_peer_count,
                "description_prefix": "iBGP V6 Listener",
            }
        )
    if "ipv4" in test_address_families:
        peer_group_configs.append(
            {
                "peer_group_name": "EB-FA-V4",
                "remote_as": ebgp_remote_as,
                "base_network": ixia_ebgp_ic_parent_network_v4,
                "is_v6": False,
                "peer_count": total_ebgp_per_af,
                "description_prefix": "eBGP V4 Peer",
            }
        )
        peer_group_configs.append(
            {
                "peer_group_name": "EB-EB-V4",
                "remote_as": ibgp_local_as,
                "base_network": ixia_ibgp_ic_parent_network_v4,
                "is_v6": False,
                "peer_count": ibgp_peer_count,
                "description_prefix": "iBGP V4 Listener",
            }
        )

    setup_tasks = [
        create_replace_bgp_peers_task(
            hostname=device_name,
            peer_configs=peer_group_configs,
        ),
        create_ixia_enable_disable_bgp_prefixes_task(
            enable=False,
            prefix_pool_regex="PREFIX_POOL_.*",
            prefix_start_index=0,
        ),
    ]

    def _mk_set_enforce_first_as_step(
        enable: bool,
        description: str | None = None,
    ):
        action = "Enable" if enable else "Disable"
        if description is None:
            description = f"{action} enforce_first_as on peer groups: {peer_groups}"
        return create_run_task_step(
            task_name="set_peer_group_enforce_first_as",
            params_dict={
                "hostname": device_name,
                "peer_groups": peer_groups,
                "enforce_first_as": enable,
                "ssh_user": ssh_user,
                "ssh_password": ssh_password,
                "reload_bgp": True,
            },
            description=description,
        )

    return TestConfig(
        name=name,
        skip_ixia_protocol_verification=True,
        log_collection_timeout=log_collection_timeout,
        basset_pool="dne.test",
        endpoints=[
            Endpoint(
                name=device_name,
                dut=True,
                ixia_ports=[ixia_interface_ebgp, ixia_interface_ibgp],
                direct_ixia_connections=direct_ixia_connections,
            ),
        ],
        host_driver_args=host_driver_args,
        oss_mock_device_data=oss_mock_device_data,
        host_os_type_map=host_os_type_map,
        startup_checks=[],
        setup_tasks=setup_tasks,
        teardown_tasks=[
            create_invoke_ixia_api_task(
                api_name="toggle_device_groups",
                args_dict={
                    "enable": False,
                    "device_group_name_regex": ".*",
                },
            ),
            create_restore_bgp_peers_task(
                hostname=device_name,
            ),
            create_set_peer_group_enforce_first_as_task(
                hostname=device_name,
                peer_groups=peer_groups,
                enforce_first_as=False,
                ssh_user=ssh_user,
                ssh_password=ssh_password,
            ),
        ],
        basic_port_configs=create_enforce_first_as_test_basic_port_configs(
            device_name=device_name,
            ixia_interface_ebgp=ixia_interface_ebgp,
            ebgp_peer_count_valid=ebgp_peer_count_valid,
            ebgp_peer_count_invalid=ebgp_peer_count_invalid,
            ebgp_remote_as=ebgp_remote_as,
            wrong_first_as=wrong_first_as,
            ixia_ebgp_ic_parent_network_v6=ixia_ebgp_ic_parent_network_v6,
            ixia_ebgp_ic_parent_network_v4=ixia_ebgp_ic_parent_network_v4,
            ixia_interface_ibgp=ixia_interface_ibgp,
            ibgp_peer_count=ibgp_peer_count,
            ibgp_local_as=ibgp_local_as,
            ixia_ibgp_ic_parent_network_v6=ixia_ibgp_ic_parent_network_v6,
            ixia_ibgp_ic_parent_network_v4=ixia_ibgp_ic_parent_network_v4,
            prefix_count=prefix_count,
            ebgp_route_acceptance_communities=ebgp_route_acceptance_communities,
            test_address_families=test_address_families,
        ),
        playbooks=[
            build_enforce_first_as_playbook(
                name="BGP_Enforce_First_AS_Test_Phase0_Feature_Disabled",
                setup_steps=[
                    _mk_set_enforce_first_as_step(
                        enable=False,
                        description="Disable enforce_first_as for Phase 0 test",
                    ),
                    create_ixia_device_group_toggle_step(
                        enable=True,
                        device_group_name_regex=".*",
                        description="Enable all BGP peer device groups",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_EBGP_VALID_AS$",
                        prefix_start_index=0,
                        description="Advertise routes from VALID AS group",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_EBGP_INVALID_AS$",
                        prefix_start_index=0,
                        description="Advertise routes from INVALID AS group",
                    ),
                ],
                periodic_tasks=[],
                prechecks=[
                    create_bgp_session_establish_check(
                        expected_established_sessions_static=total_peers,
                        check_id="verify_all_bgp_sessions_established_phase0",
                    ),
                ],
                snapshot_checks=[
                    create_bgp_session_snapshot_check(
                        skip_flap_check=True, skip_uptime_check=True
                    ),
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for BGP convergence ({convergence_wait_seconds}s)",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_enforce_first_as_routes",
                                    "hostname": device_name,
                                    "enforce_first_as_enabled": False,
                                    "valid_prefix_filters": valid_prefix_filters,
                                    "invalid_prefix_filters": invalid_prefix_filters,
                                    "expected_valid_route_count": expected_valid_routes,
                                    "expected_invalid_route_count": expected_invalid_routes,
                                },
                                description="Verify ALL routes accepted (enforce_first_as disabled)",
                            ),
                        ],
                    ),
                ],
            ),
            build_enforce_first_as_playbook(
                name="BGP_Enforce_First_AS_Test_Phase1_Feature_Enabled",
                setup_steps=[
                    create_ixia_device_group_toggle_step(
                        enable=True,
                        device_group_name_regex=".*",
                        description="Enable all BGP peer device groups",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_EBGP_VALID_AS$",
                        prefix_start_index=0,
                        description="Advertise routes from VALID AS group",
                    ),
                    create_custom_step(
                        params_dict={
                            "custom_step_name": "get_enforce_first_as_rejects_baseline",
                            "hostname": device_name,
                        },
                        description="Get baseline enforce_first_as reject count",
                    ),
                    _mk_set_enforce_first_as_step(
                        enable=True,
                        description="Enable enforce_first_as for Phase 1 test",
                    ),
                ],
                periodic_tasks=[],
                prechecks=[
                    create_bgp_session_establish_check(
                        expected_established_sessions_static=total_peers,
                        check_id="verify_all_bgp_sessions_established_phase1",
                    ),
                ],
                snapshot_checks=[
                    create_bgp_session_snapshot_check(
                        skip_flap_check=True, skip_uptime_check=True
                    ),
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[
                    create_bgp_rib_fib_consistency_check(),
                ],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            create_advertise_withdraw_prefixes_step(
                                device_name=device_name,
                                advertise=False,
                                prefix_pool_regex="PREFIX_POOL_.*_EBGP_INVALID_AS$",
                                prefix_start_index=0,
                                description="Withdraw INVALID AS routes",
                            ),
                            create_longevity_step(
                                duration=30,
                                description="Wait for withdrawal (30s)",
                            ),
                            create_advertise_withdraw_prefixes_step(
                                device_name=device_name,
                                advertise=True,
                                prefix_pool_regex="PREFIX_POOL_.*_EBGP_INVALID_AS$",
                                prefix_start_index=0,
                                description="Re-advertise INVALID AS routes",
                            ),
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for BGP convergence ({convergence_wait_seconds}s)",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_enforce_first_as_routes",
                                    "hostname": device_name,
                                    "enforce_first_as_enabled": True,
                                    "valid_prefix_filters": valid_prefix_filters,
                                    "invalid_prefix_filters": invalid_prefix_filters,
                                    "expected_valid_route_count": expected_valid_routes,
                                    "expected_invalid_route_count": 0,
                                },
                                description="Verify only VALID routes accepted (enforce_first_as enabled)",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_enforce_first_as_rejects_increased",
                                    "hostname": device_name,
                                    "min_rejects": 1,
                                },
                                description="Verify enforce_first_as reject counter increased",
                            ),
                        ],
                    ),
                ],
            ),
            build_enforce_first_as_playbook(
                name="BGP_Enforce_First_AS_Test_Phase2_Readvertise_Invalid",
                setup_steps=[
                    create_ixia_device_group_toggle_step(
                        enable=True,
                        device_group_name_regex=".*",
                        description="Enable all BGP peer device groups",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_EBGP_VALID_AS$",
                        prefix_start_index=0,
                        description="Advertise routes from VALID AS group",
                    ),
                    _mk_set_enforce_first_as_step(
                        enable=True,
                        description="Enable enforce_first_as for Phase 2 test",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_EBGP_INVALID_AS$",
                        prefix_start_index=0,
                        description="Withdraw INVALID AS routes",
                    ),
                ],
                periodic_tasks=[],
                prechecks=[],
                snapshot_checks=[
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            create_longevity_step(
                                duration=30,
                                description="Wait for withdrawal (30s)",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "get_enforce_first_as_rejects_baseline",
                                    "hostname": device_name,
                                },
                                description="Get current enforce_first_as reject count",
                            ),
                            create_advertise_withdraw_prefixes_step(
                                device_name=device_name,
                                advertise=True,
                                prefix_pool_regex="PREFIX_POOL_.*_EBGP_INVALID_AS$",
                                prefix_start_index=0,
                                description="Re-advertise INVALID AS routes",
                            ),
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for re-advertisement ({convergence_wait_seconds}s)",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_enforce_first_as_routes",
                                    "hostname": device_name,
                                    "enforce_first_as_enabled": True,
                                    "valid_prefix_filters": valid_prefix_filters,
                                    "invalid_prefix_filters": invalid_prefix_filters,
                                    "expected_valid_route_count": expected_valid_routes,
                                    "expected_invalid_route_count": 0,
                                },
                                description="Verify INVALID routes still rejected after re-advertise",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_enforce_first_as_rejects_increased",
                                    "hostname": device_name,
                                    "min_rejects": 1,
                                },
                                description="Verify reject counter increased again",
                            ),
                        ],
                    ),
                ],
            ),
            build_enforce_first_as_playbook(
                name="BGP_Enforce_First_AS_Test_Phase3_Feature_Disabled_Again",
                setup_steps=[
                    create_ixia_device_group_toggle_step(
                        enable=True,
                        device_group_name_regex=".*",
                        description="Enable all BGP peer device groups",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_EBGP_VALID_AS$",
                        prefix_start_index=0,
                        description="Advertise routes from VALID AS group",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_EBGP_INVALID_AS$",
                        prefix_start_index=0,
                        description="Advertise routes from INVALID AS group",
                    ),
                    _mk_set_enforce_first_as_step(
                        enable=False,
                        description="Disable enforce_first_as for Phase 3 test",
                    ),
                ],
                periodic_tasks=[],
                prechecks=[],
                snapshot_checks=[
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[
                    create_bgp_rib_fib_consistency_check(),
                ],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for BGP convergence ({convergence_wait_seconds}s)",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_enforce_first_as_routes",
                                    "hostname": device_name,
                                    "enforce_first_as_enabled": False,
                                    "valid_prefix_filters": valid_prefix_filters,
                                    "invalid_prefix_filters": invalid_prefix_filters,
                                    "expected_valid_route_count": expected_valid_routes,
                                    "expected_invalid_route_count": expected_invalid_routes,
                                },
                                description="Verify ALL routes accepted again (enforce_first_as disabled)",
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )


# =============================================================================
# BGP MED (legacy test_config_bgp_med_feature)
# =============================================================================


def create_bgp_feature_med_test_config(
    physical_inventory: PhysicalInventory,
    *,
    name: str,
    ebgp_remote_as: int = 65334,
    ixia_ebgp_ic_parent_network_v6: str = "2401:db00:e50d:11:8",
    ixia_ebgp_ic_parent_network_v4: str = "10.163.28",
    ibgp_local_as: int = 64981,
    ixia_ibgp_ic_parent_network_v6: str = "2401:db00:e50d:11:9",
    ixia_ibgp_ic_parent_network_v4: str = "10.164.28",
    ssh_user: str = "admin",
    ebgp_peer_count_group1: int = 50,
    ebgp_peer_count_group2: int = 50,
    ibgp_peer_count: int = 50,
    prefix_count: int = 100,
    med_low: int = 10,
    med_high: int = 100,
    ebgp_route_acceptance_communities: list[str] | None = None,
    test_address_families: list[str] | None = None,
    convergence_wait_seconds: int = 120,
    log_collection_timeout: int | None = None,
) -> TestConfig:
    """BGP MED (Multi-Exit Discriminator) TestConfig -- Arista BGP++ feature test.

    Byte-wise identical to the legacy
    ``test_config_bgp_med_feature.test_config_for_bgp_med_feature`` factory
    invoked from the ``ARISTA_BGP_MED_FEATURE_TEST`` wrapper on
    ``eb03.lab.ash6``. DUT identity + IXIA port map + lab host wiring are
    derived from ``physical_inventory``; the remaining workload knobs keep the
    wrapper's default values (test_address_families = ["ipv6", "ipv4"]).
    """
    if ebgp_route_acceptance_communities is None:
        ebgp_route_acceptance_communities = ["65529:39744"]
    if test_address_families is None:
        test_address_families = ["ipv6", "ipv4"]

    device_name = physical_inventory.device_name
    ebgp_iface, ebgp_port = physical_inventory.ixia_ports[0]
    ibgp_iface, ibgp_port = physical_inventory.ixia_ports[1]
    ixia_interface_ebgp = ebgp_iface
    ixia_interface_ibgp = ibgp_iface
    ssh_password = _feature_ssh_password(physical_inventory)

    host_driver_args = physical_inventory.host_driver_args
    oss_mock_device_data = physical_inventory.oss_mock_device_data
    host_os_type_map = {device_name: taac_types.DeviceOsType.ARISTA_FBOSS}
    direct_ixia_connections = [
        DirectIxiaConnection(
            interface=ebgp_iface,
            ixia_chassis_ip=physical_inventory.ixia_chassis_ip,
            ixia_port=ebgp_port,
        ),
        DirectIxiaConnection(
            interface=ibgp_iface,
            ixia_chassis_ip=physical_inventory.ixia_chassis_ip,
            ixia_port=ibgp_port,
        ),
    ]

    num_afs = len(test_address_families)
    total_ebgp_peers = (ebgp_peer_count_group1 + ebgp_peer_count_group2) * num_afs
    total_ibgp_peers = ibgp_peer_count * num_afs
    total_peers = total_ebgp_peers + total_ibgp_peers
    total_ebgp_per_af = ebgp_peer_count_group1 + ebgp_peer_count_group2

    peer_groups = []
    if "ipv6" in test_address_families:
        peer_groups.append(
            {
                "peer_group_name": "EB-FA-V6",
                "remote_as": ebgp_remote_as,
                "base_network": ixia_ebgp_ic_parent_network_v6,
                "is_v6": True,
                "peer_count": total_ebgp_per_af,
                "description_prefix": "eBGP V6 Peer",
            }
        )
        peer_groups.append(
            {
                "peer_group_name": "EB-EB-V6",
                "remote_as": ibgp_local_as,
                "base_network": ixia_ibgp_ic_parent_network_v6,
                "is_v6": True,
                "peer_count": ibgp_peer_count,
                "description_prefix": "iBGP V6 Listener",
            }
        )
    if "ipv4" in test_address_families:
        peer_groups.append(
            {
                "peer_group_name": "EB-FA-V4",
                "remote_as": ebgp_remote_as,
                "base_network": ixia_ebgp_ic_parent_network_v4,
                "is_v6": False,
                "peer_count": total_ebgp_per_af,
                "description_prefix": "eBGP V4 Peer",
            }
        )
        peer_groups.append(
            {
                "peer_group_name": "EB-EB-V4",
                "remote_as": ibgp_local_as,
                "base_network": ixia_ibgp_ic_parent_network_v4,
                "is_v6": False,
                "peer_count": ibgp_peer_count,
                "description_prefix": "iBGP V4 Listener",
            }
        )

    setup_tasks = [
        create_replace_bgp_peers_task(
            hostname=device_name,
            peer_configs=peer_groups,
        ),
        create_ixia_enable_disable_bgp_prefixes_task(
            enable=False,
            prefix_pool_regex="PREFIX_POOL_.*",
            prefix_start_index=0,
        ),
    ]

    def _mk_enable_med_comparison_step(
        description: str = "Enable MED comparison in BGP++ settings",
    ):
        return create_run_task_step(
            task_name="enable_med_comparison",
            params_dict={
                "hostname": device_name,
                "enable_med_missing_as_worst": False,
                "ssh_user": ssh_user,
                "ssh_password": ssh_password,
                "reload_bgp": True,
            },
            description=description,
        )

    def _mk_disable_med_comparison_step(
        description: str = "Disable MED comparison in BGP++ settings",
    ):
        return create_run_task_step(
            task_name="disable_med_comparison",
            params_dict={
                "hostname": device_name,
                "ssh_user": ssh_user,
                "ssh_password": ssh_password,
                "reload_bgp": True,
            },
            description=description,
        )

    def _mk_enable_med_missing_as_worst_step(
        description: str = "Enable 'treat missing MED as worst' in BGP++ settings",
    ):
        return create_run_task_step(
            task_name="enable_med_comparison",
            params_dict={
                "hostname": device_name,
                "enable_med_missing_as_worst": True,
                "ssh_user": ssh_user,
                "ssh_password": ssh_password,
                "reload_bgp": True,
            },
            description=description,
        )

    def _mk_disable_med_missing_as_worst_step(
        description: str = "Disable 'treat missing MED as worst' in BGP++ settings",
    ):
        return create_run_task_step(
            task_name="enable_med_comparison",
            params_dict={
                "hostname": device_name,
                "enable_med_missing_as_worst": False,
                "ssh_user": ssh_user,
                "ssh_password": ssh_password,
                "reload_bgp": True,
            },
            description=description,
        )

    return TestConfig(
        name=name,
        skip_ixia_protocol_verification=True,
        log_collection_timeout=log_collection_timeout,
        basset_pool="dne.test",
        endpoints=[
            Endpoint(
                name=device_name,
                dut=True,
                ixia_ports=[ixia_interface_ebgp, ixia_interface_ibgp],
                direct_ixia_connections=direct_ixia_connections,
            ),
        ],
        host_driver_args=host_driver_args,
        oss_mock_device_data=oss_mock_device_data,
        host_os_type_map=host_os_type_map,
        startup_checks=[],
        setup_tasks=setup_tasks,
        teardown_tasks=[
            create_invoke_ixia_api_task(
                api_name="toggle_device_groups",
                args_dict={
                    "enable": False,
                    "device_group_name_regex": ".*",
                },
            ),
            create_restore_bgp_peers_task(
                hostname=device_name,
            ),
            create_disable_med_comparison_task(
                hostname=device_name,
                ssh_user=ssh_user,
                ssh_password=ssh_password,
            ),
        ],
        basic_port_configs=create_med_test_basic_port_configs(
            device_name=device_name,
            ixia_interface_ebgp=ixia_interface_ebgp,
            ebgp_peer_count_group1=ebgp_peer_count_group1,
            ebgp_peer_count_group2=ebgp_peer_count_group2,
            ebgp_remote_as=ebgp_remote_as,
            ixia_ebgp_ic_parent_network_v6=ixia_ebgp_ic_parent_network_v6,
            ixia_ebgp_ic_parent_network_v4=ixia_ebgp_ic_parent_network_v4,
            ixia_interface_ibgp=ixia_interface_ibgp,
            ibgp_peer_count=ibgp_peer_count,
            ibgp_local_as=ibgp_local_as,
            ixia_ibgp_ic_parent_network_v6=ixia_ibgp_ic_parent_network_v6,
            ixia_ibgp_ic_parent_network_v4=ixia_ibgp_ic_parent_network_v4,
            prefix_count=prefix_count,
            ebgp_route_acceptance_communities=ebgp_route_acceptance_communities,
            test_address_families=test_address_families,
        ),
        playbooks=[
            build_bgp_med_playbook(
                name="BGP_MED_Test_Phase0_MED_Comparison_Disabled",
                setup_steps=[
                    _mk_disable_med_comparison_step(
                        description="Disable MED comparison for Phase 0 ECMP test"
                    ),
                    create_ixia_device_group_toggle_step(
                        enable=True,
                        device_group_name_regex=".*",
                        description="Enable all BGP peer device groups",
                    ),
                    create_bgp_prefixes_med_value_step(
                        prefix_pool_regex="PREFIX_POOL_.*_MED_HIGH$",
                        prefix_start_index=0,
                        med_value=med_high,
                        description=f"Set MED {med_high} on HIGH MED prefix pools",
                    ),
                    create_bgp_prefixes_med_value_step(
                        prefix_pool_regex="PREFIX_POOL_.*_MED_LOW$",
                        prefix_start_index=0,
                        med_value=med_low,
                        description=f"Set MED {med_low} on LOW MED prefix pools",
                    ),
                    create_bgp_prefixes_med_value_step(
                        prefix_pool_regex="PREFIX_POOL_.*_MED_LOW_VS_NOMED$",
                        prefix_start_index=0,
                        med_value=med_low,
                        description=f"Set MED {med_low} on LOW MED vs NOMED prefix pools",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_HIGH$",
                        prefix_start_index=0,
                        description=f"Advertise routes from eBGP Group 1 (MED {med_high})",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_LOW$",
                        prefix_start_index=0,
                        description=f"Advertise routes from eBGP Group 2 (MED {med_low})",
                    ),
                ],
                periodic_tasks=[],
                prechecks=[
                    create_bgp_session_establish_check(
                        expected_established_sessions_static=total_peers,
                        check_id="verify_all_bgp_sessions_established_phase0",
                    ),
                ],
                snapshot_checks=[
                    create_bgp_session_snapshot_check(
                        skip_flap_check=True, skip_uptime_check=True
                    ),
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[
                    create_next_hop_count_check(
                        min_nexthop_count=2,
                        prefix_subnets=["2001:db8:3000::/48", "10.200.0.0/16"],
                        check_id="verify_ecmp_med_ignored",
                    ),
                ],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for BGP convergence ({convergence_wait_seconds}s)",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_med_ignored",
                                    "hostname": device_name,
                                    "prefix_filter": "2001:db8:3000::",
                                    "expected_med_low": med_low,
                                    "expected_med_high": med_high,
                                },
                                description="Verify MED is IGNORED - both MED values should be in RIB (ECMP)",
                            ),
                        ],
                    ),
                ],
            ),
            build_bgp_med_playbook(
                name="BGP_MED_Test_Phase1_Both_Groups_Active",
                setup_steps=[
                    _mk_enable_med_comparison_step(
                        description="Enable MED comparison for best path selection"
                    ),
                ],
                periodic_tasks=[],
                prechecks=[
                    create_bgp_session_establish_check(
                        expected_established_sessions_static=total_peers,
                        check_id="verify_all_bgp_sessions_established",
                    ),
                ],
                snapshot_checks=[
                    create_bgp_session_snapshot_check(
                        skip_flap_check=True, skip_uptime_check=True
                    ),
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[
                    create_bgp_session_establish_check(
                        expected_established_sessions_static=total_peers,
                        check_id="verify_bgp_sessions_after_advertisement",
                    ),
                ],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for BGP convergence ({convergence_wait_seconds}s)",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_med_best_path",
                                    "hostname": device_name,
                                    "expected_med": med_low,
                                    "prefix_filter": "2001:db8:3000::",
                                },
                                description=f"Verify routes with MED {med_low} are selected as best",
                            ),
                        ],
                    ),
                ],
            ),
            build_bgp_med_playbook(
                name="BGP_MED_Test_Phase2_LowMED_Withdrawn",
                setup_steps=[
                    create_ixia_packet_capture_step(
                        device_name=device_name,
                        interface=ixia_interface_ibgp,
                        mode="start",
                        capture_filter="tcp port 179",
                        capture_id="phase2_med_capture",
                        description="Start capture on iBGP interface for Phase 2",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_LOW$",
                        prefix_start_index=0,
                        description=f"Withdraw routes from eBGP Group 2 (MED {med_low})",
                    ),
                ],
                periodic_tasks=[],
                prechecks=[],
                snapshot_checks=[
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[
                    create_bgp_rib_fib_consistency_check(),
                ],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for withdrawal convergence ({convergence_wait_seconds}s)",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_ibgp,
                                mode="stop",
                                capture_id="phase2_med_capture",
                                description="Stop capture on iBGP interface",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_ibgp,
                                mode="save",
                                capture_id="phase2_med_capture",
                                pcap_filename="bgp_med_phase2.pcap",
                                description="Save Phase 2 packet capture",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_med_best_path",
                                    "hostname": device_name,
                                    "expected_med": med_high,
                                    "prefix_filter": "2001:db8:3000::",
                                },
                                description=f"Verify routes with MED {med_high} are now best",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_med_in_pcap",
                                    "pcap_filename": "bgp_med_phase2.pcap",
                                    "expected_med": med_high,
                                    "min_updates_with_med": 1,
                                },
                                description=f"Verify MED {med_high} in PCAP sent to iBGP",
                            ),
                        ],
                    ),
                ],
            ),
            build_bgp_med_playbook(
                name="BGP_MED_Test_Phase3_LowMED_Readvertised",
                setup_steps=[
                    create_ixia_packet_capture_step(
                        device_name=device_name,
                        interface=ixia_interface_ibgp,
                        mode="start",
                        capture_filter="tcp port 179",
                        capture_id="phase3_med_capture",
                        description="Start capture on iBGP interface for Phase 3",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_LOW$",
                        prefix_start_index=0,
                        description=f"Re-advertise routes from eBGP Group 2 (MED {med_low})",
                    ),
                ],
                periodic_tasks=[],
                prechecks=[],
                snapshot_checks=[
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[
                    create_bgp_rib_fib_consistency_check(),
                ],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for re-advertisement convergence ({convergence_wait_seconds}s)",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_ibgp,
                                mode="stop",
                                capture_id="phase3_med_capture",
                                description="Stop capture on iBGP interface",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_ibgp,
                                mode="save",
                                capture_id="phase3_med_capture",
                                pcap_filename="bgp_med_phase3.pcap",
                                description="Save Phase 3 packet capture",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_med_best_path",
                                    "hostname": device_name,
                                    "expected_med": med_low,
                                    "prefix_filter": "2001:db8:3000::",
                                },
                                description=f"Verify routes with MED {med_low} are best again",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_med_in_pcap",
                                    "pcap_filename": "bgp_med_phase3.pcap",
                                    "expected_med": med_low,
                                    "min_updates_with_med": 1,
                                },
                                description=f"Verify MED {med_low} in PCAP sent to iBGP",
                            ),
                        ],
                    ),
                ],
            ),
            build_bgp_med_playbook(
                name="BGP_MED_Test_Phase4_MED_Vs_NoMED",
                setup_steps=[
                    _mk_enable_med_missing_as_worst_step(
                        description="Enable 'missing MED as worst' for MED vs No-MED test"
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_HIGH$",
                        prefix_start_index=0,
                        description="Withdraw high MED routes",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_LOW$",
                        prefix_start_index=0,
                        description="Withdraw low MED routes",
                    ),
                    create_ixia_packet_capture_step(
                        device_name=device_name,
                        interface=ixia_interface_ibgp,
                        mode="start",
                        capture_filter="tcp port 179",
                        capture_id="phase4_med_capture",
                        description="Start capture on iBGP interface for Phase 4",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_NO_MED$",
                        prefix_start_index=0,
                        description="Advertise routes with no MED (default)",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_LOW_VS_NOMED",
                        prefix_start_index=0,
                        description=f"Advertise same routes with MED {med_low}",
                    ),
                ],
                periodic_tasks=[],
                prechecks=[],
                snapshot_checks=[
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[
                    create_bgp_rib_fib_consistency_check(),
                ],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for convergence ({convergence_wait_seconds}s)",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_ibgp,
                                mode="stop",
                                capture_id="phase4_med_capture",
                                description="Stop capture on iBGP interface",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_ibgp,
                                mode="save",
                                capture_id="phase4_med_capture",
                                pcap_filename="bgp_med_phase4.pcap",
                                description="Save Phase 4 packet capture",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_med_best_path",
                                    "hostname": device_name,
                                    "expected_med": med_low,
                                    "prefix_filter": "2001:db8:4000::",
                                },
                                description=f"Verify routes with explicit MED {med_low} vs no MED",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_med_in_pcap",
                                    "pcap_filename": "bgp_med_phase4.pcap",
                                    "expected_med": med_low,
                                    "min_updates_with_med": 1,
                                },
                                description=f"Verify MED {med_low} in PCAP sent to iBGP",
                            ),
                        ],
                    ),
                ],
            ),
            build_bgp_med_playbook(
                name="BGP_MED_Test_Phase4a_NoMED_As_Zero",
                setup_steps=[
                    create_ixia_packet_capture_step(
                        device_name=device_name,
                        interface=ixia_interface_ibgp,
                        mode="start",
                        capture_filter="tcp port 179",
                        capture_id="phase4a_med_capture",
                        description="Start capture on iBGP interface for Phase 4a",
                    ),
                    _mk_disable_med_missing_as_worst_step(
                        description="Reset 'missing MED as worst' to false - no-MED treated as 0"
                    ),
                ],
                periodic_tasks=[],
                prechecks=[],
                snapshot_checks=[
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[
                    create_bgp_rib_fib_consistency_check(),
                ],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for convergence after config change ({convergence_wait_seconds}s)",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_ibgp,
                                mode="stop",
                                capture_id="phase4a_med_capture",
                                description="Stop capture on iBGP interface",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_ibgp,
                                mode="save",
                                capture_id="phase4a_med_capture",
                                pcap_filename="bgp_med_phase4a.pcap",
                                description="Save Phase 4a packet capture",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_med_best_path",
                                    "hostname": device_name,
                                    "expected_med": 0,
                                    "prefix_filter": "2001:db8:4000::",
                                },
                                description="Verify no-MED (treated as 0) beats explicit MED > 0",
                            ),
                        ],
                    ),
                ],
            ),
            build_bgp_med_playbook(
                name="BGP_MED_Test_Phase4b_MED_Zero_Best",
                setup_steps=[
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_NO_MED$",
                        prefix_start_index=0,
                        description="Withdraw no-MED routes",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_LOW_VS_NOMED",
                        prefix_start_index=0,
                        description="Withdraw MED low vs no-MED routes",
                    ),
                    create_bgp_prefixes_med_value_step(
                        prefix_pool_regex="PREFIX_POOL_.*_MED_LOW$",
                        prefix_start_index=0,
                        med_value=0,
                        description="Set explicit MED=0 on LOW MED prefix pools",
                    ),
                    create_ixia_packet_capture_step(
                        device_name=device_name,
                        interface=ixia_interface_ibgp,
                        mode="start",
                        capture_filter="tcp port 179",
                        capture_id="phase4b_med_capture",
                        description="Start capture on iBGP interface for Phase 4b",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_HIGH$",
                        prefix_start_index=0,
                        description=f"Advertise routes with MED {med_high}",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_LOW$",
                        prefix_start_index=0,
                        description="Advertise routes with explicit MED=0",
                    ),
                ],
                periodic_tasks=[],
                prechecks=[],
                snapshot_checks=[
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[
                    create_bgp_rib_fib_consistency_check(),
                ],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for convergence ({convergence_wait_seconds}s)",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_ibgp,
                                mode="stop",
                                capture_id="phase4b_med_capture",
                                description="Stop capture on iBGP interface",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_ibgp,
                                mode="save",
                                capture_id="phase4b_med_capture",
                                pcap_filename="bgp_med_phase4b.pcap",
                                description="Save Phase 4b packet capture",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_med_best_path",
                                    "hostname": device_name,
                                    "expected_med": 0,
                                    "prefix_filter": "2001:db8:3000::",
                                },
                                description="Verify explicit MED=0 beats higher MED values",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_med_in_pcap",
                                    "pcap_filename": "bgp_med_phase4b.pcap",
                                    "expected_med": 0,
                                    "min_updates_with_med": 1,
                                },
                                description="Verify MED=0 in PCAP sent to iBGP",
                            ),
                        ],
                    ),
                ],
            ),
            build_bgp_med_playbook(
                name="BGP_MED_Test_Phase4c_MED_Ordering",
                setup_steps=[
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_LOW$",
                        prefix_start_index=0,
                        description="Withdraw MED=0 routes",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_HIGH$",
                        prefix_start_index=0,
                        description="Withdraw MED high routes",
                    ),
                    create_bgp_prefixes_med_value_step(
                        prefix_pool_regex="PREFIX_POOL_.*_MED_LOW$",
                        prefix_start_index=0,
                        med_value=med_low,
                        description=f"Reset MED to {med_low} on LOW MED prefix pools",
                    ),
                    create_bgp_prefixes_med_value_step(
                        prefix_pool_regex="PREFIX_POOL_.*_MED_HIGH$",
                        prefix_start_index=0,
                        med_value=50,
                        description="Set MED=50 on HIGH MED prefix pools",
                    ),
                    create_ixia_packet_capture_step(
                        device_name=device_name,
                        interface=ixia_interface_ibgp,
                        mode="start",
                        capture_filter="tcp port 179",
                        capture_id="phase4c_med_capture",
                        description="Start capture on iBGP interface for Phase 4c",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_HIGH$",
                        prefix_start_index=0,
                        description="Advertise routes with MED=50",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_LOW$",
                        prefix_start_index=0,
                        description=f"Advertise routes with MED={med_low}",
                    ),
                ],
                periodic_tasks=[],
                prechecks=[],
                snapshot_checks=[
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[
                    create_bgp_rib_fib_consistency_check(),
                ],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for convergence ({convergence_wait_seconds}s)",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_ibgp,
                                mode="stop",
                                capture_id="phase4c_med_capture",
                                description="Stop capture on iBGP interface",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_ibgp,
                                mode="save",
                                capture_id="phase4c_med_capture",
                                pcap_filename="bgp_med_phase4c.pcap",
                                description="Save Phase 4c packet capture",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_med_best_path",
                                    "hostname": device_name,
                                    "expected_med": med_low,
                                    "prefix_filter": "2001:db8:3000::",
                                },
                                description=f"Verify MED={med_low} beats MED=50",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_med_in_pcap",
                                    "pcap_filename": "bgp_med_phase4c.pcap",
                                    "expected_med": med_low,
                                    "min_updates_with_med": 1,
                                },
                                description=f"Verify MED {med_low} in PCAP sent to iBGP",
                            ),
                        ],
                    ),
                ],
            ),
            build_bgp_med_playbook(
                name="BGP_MED_Test_Phase4d_Restore_MED_Values",
                setup_steps=[
                    create_bgp_prefixes_med_value_step(
                        prefix_pool_regex="PREFIX_POOL_.*_MED_HIGH$",
                        prefix_start_index=0,
                        med_value=med_high,
                        description=f"Reset MED to {med_high} on HIGH MED prefix pools",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_LOW$",
                        prefix_start_index=0,
                        description="Withdraw MED low routes",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_HIGH$",
                        prefix_start_index=0,
                        description="Withdraw MED high routes",
                    ),
                ],
                periodic_tasks=[],
                prechecks=[],
                snapshot_checks=[
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            create_longevity_step(
                                duration=30,
                                description="Wait for cleanup (30s)",
                            ),
                        ],
                    ),
                ],
            ),
            build_bgp_med_playbook(
                name="BGP_MED_Test_Phase5_ECMP_Equal_MED",
                setup_steps=[
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*_MED_LOW_VS_NOMED",
                        prefix_start_index=0,
                        description="Withdraw MED low vs no-MED routes",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_NO_MED$",
                        prefix_start_index=0,
                        description="Advertise routes from Group 1 with no MED",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex="PREFIX_POOL_.*_NO_MED_G2",
                        prefix_start_index=0,
                        description="Advertise same routes from Group 2 with no MED",
                    ),
                ],
                periodic_tasks=[],
                prechecks=[],
                snapshot_checks=[
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[
                    create_bgp_rib_fib_consistency_check(),
                    create_next_hop_count_check(
                        min_nexthop_count=2,
                        prefix_subnets=["2001:db8:4000::/48", "10.250.0.0/16"],
                        check_id="verify_ecmp_equal_med",
                    ),
                ],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for convergence ({convergence_wait_seconds}s)",
                            ),
                        ],
                    ),
                ],
            ),
            build_bgp_med_playbook(
                name="BGP_MED_Test_Phase6_Verify_MED_Sent_To_IBGP",
                setup_steps=[
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex="PREFIX_POOL_.*",
                        prefix_start_index=0,
                        description="Withdraw all routes to reset state",
                    ),
                ],
                periodic_tasks=[],
                prechecks=[
                    create_bgp_session_establish_check(
                        expected_established_sessions_static=total_peers,
                        check_id="verify_bgp_sessions_before_capture",
                    ),
                ],
                snapshot_checks=[
                    create_core_dumps_snapshot_check(),
                ],
                postchecks=[],
                stages=[
                    create_steps_stage(
                        iteration=1,
                        steps=[
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_ibgp,
                                mode="start",
                                capture_filter="tcp port 179",
                                capture_id="med_ibgp_capture",
                                description="Start capture on iBGP interface for MED verification",
                            ),
                            create_longevity_step(
                                duration=5,
                                description="Wait for capture to initialize (5s)",
                            ),
                            create_advertise_withdraw_prefixes_step(
                                device_name=device_name,
                                advertise=True,
                                prefix_pool_regex="PREFIX_POOL_.*_MED_LOW$",
                                prefix_start_index=0,
                                description=f"Advertise routes with MED {med_low}",
                            ),
                            create_longevity_step(
                                duration=convergence_wait_seconds,
                                description=f"Wait for routes to propagate to iBGP ({convergence_wait_seconds}s)",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_ibgp,
                                mode="stop",
                                capture_id="med_ibgp_capture",
                                description="Stop capture on iBGP interface",
                            ),
                            create_ixia_packet_capture_step(
                                device_name=device_name,
                                interface=ixia_interface_ibgp,
                                mode="save",
                                capture_id="med_ibgp_capture",
                                pcap_filename="bgp_med_ibgp.pcap",
                                description="Save iBGP packet capture",
                            ),
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "verify_bgp_med_in_pcap",
                                    "pcap_filename": "bgp_med_ibgp.pcap",
                                    "expected_med": med_low,
                                    "min_updates_with_med": 1,
                                },
                                description="Verify MED attribute is present in BGP updates to iBGP",
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )
