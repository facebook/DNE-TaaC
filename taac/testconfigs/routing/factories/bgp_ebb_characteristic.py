# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""BGPCPP-on-EBB characteristic/measurement workflow factories.

EBB-topology measurement tests (update-packing, constant-attribute storage,
queue/memory monitoring, performance scaling, bounded ECMP). Naming:
``create_ebb_<workflow>_test_config(physical_inventory: PhysicalInventory, ...) -> TestConfig``.

Wave 5D.1 absorbs the ``test_config_constant_attribute_storage_on_eos``,
``test_config_constant_attribute_storage_varying_combinations_on_eos`` and
``test_config_bgp_queue_memory_monitoring_with_route_scale`` helpers
(historically in ``testconfigs/routing/ebb/test_config_performance_scaling_case2.py``
and ``test_config_queue_memory_monitor.py``) into this module so that the
Wave 5D catalog (``qual_bgp_ebb_characteristic.py``) can call them via the
new ``create_bgp_ebb_characteristic_*`` factories. The playbook factories
(``build_case2_playbook``, ``create_bgp_queue_memory_monitoring_playbook``)
stay in ``playbook_definitions.py`` verbatim so the playbook snapshot
manifest ``__module__`` filter still picks them up.

Wave 5D.2 absorbs 4 more helpers verbatim so their thin wrappers can be
retired: ``test_config_for_bgp_plus_plus_on_ebb_arista_separable_policy``
(case 8), ``test_config_bgp_update_packing_validation`` (update-packing),
``test_config_to_verify_computational_load_of_bgp_plus_plus`` and
``test_config_to_verify_constant_attribute_storage`` (verify pair). The
new physical-inventory-driven factories (``create_bgp_ebb_characteristic_*``) call
these helpers by name. Playbook factories (``build_case8_playbook``,
``create_bgp_update_packing_validation_playbook``,
``create_test_computational_load_for_bgp_plus_plus_playbook``,
``create_test_constant_attribute_storage_playbook``) stay in
``playbook_definitions.py``.

See ../README.md §3.
"""

import os

from ixia.ixia import types as ixia_types
from taac.abstractions.topologies.ipv6_update_packing import (
    IPV6_UPDATE_PACKING,
    IPV6_UPDATE_PACKING_AS_NUMBERS,
    IPV6_UPDATE_PACKING_PARENT_NETWORKS,
    IPV6_UPDATE_PACKING_PEER_GROUPS,
    IPV6_UPDATE_PACKING_PORT_MAP,
)
from taac.abstractions.topology import RoutingDeviceConfig
from neteng.test_infra.dne.taac.constants import BgpPlusPlusProfile, Gigabyte
from taac.health_checks.healthcheck_definitions import (
    create_bgp_session_establish_check,
    create_bgp_session_snapshot_check,
    create_core_dumps_snapshot_check,
)
from taac.playbooks.playbook_definitions import (
    build_case2_playbook,
    build_case8_playbook,
    create_bgp_queue_memory_monitoring_playbook,
    create_bgp_update_packing_validation_playbook,
    create_test_computational_load_for_bgp_plus_plus_playbook,
    create_test_constant_attribute_storage_playbook,
)
from taac.routing.ebb.arista_bgp_plus_plus_performance_scaling_tests.attribute_pool_generator import (
    generate_as_path_pool,
    generate_community_pool,
    generate_extended_community_pool,
)
from taac.routing.ebb.arista_bgp_plus_plus_performance_scaling_tests.ixia_configs_for_tests import (
    create_ebb_performance_scale_basic_port_configs,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_custom_step,
    create_sc_8_setup_steps,
    create_sc_8_steps,
)
from taac.task_definitions import (
    create_bgp_clear_route_filter_task,
    create_configure_bgpcpp_startup_task,
    create_coop_apply_patchers_task,
    create_coop_register_patcher_task,
    create_coop_unregister_patchers_task,
    create_interface_ip_configuration_task,
    create_replace_bgp_peers_task,
    create_run_commands_on_shell_task,
    create_scp_file_template_task,
    create_wait_for_agent_convergence_task,
)
from taac.testconfigs.routing.factories.bgp_ebb_scaling import (
    create_bgp_ebb_scaling_bounded_ecmp_sets_test_config,
    create_bgp_ebb_scaling_performance_test_config,
)
from taac.testconfigs.routing.physical_inventory import (
    PhysicalInventory,
)
from taac.testconfigs.routing.util.bgp_ebb_constants import (
    _derive_test_config_name,
    EBGP_PEER_COUNT_V6,
    EBGP_REMOTE_AS,
    IBGP_PEER_SCALE_PER_PLANE,
    IBGP_REMOTE_AS,
    IXIA_EBGP_IC_PARENT_NETWORK_V4,
    IXIA_EBGP_IC_PARENT_NETWORK_V6,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
    IXIA_IPV4_START_OFFSET,
    IXIA_IPV6_START_OFFSET,
    PEERGROUP_EBGP_V4,
    PEERGROUP_EBGP_V6,
    PEERGROUP_IBGP_V4,
    PEERGROUP_IBGP_V6,
)
from taac.testconfigs.routing.util.bgp_ebb_periodic_tasks import (
    create_standard_periodic_tasks,
)
from taac.testconfigs.routing.util.bgp_ebb_setup_tasks import (
    build_per_iteration_factory_v4_capable,
    get_update_packing_setup_tasks,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import (
    BasicPortConfig,
    BgpConfig,
    DeviceGroupConfig,
    DirectIxiaConnection,
    Endpoint,
    IpAddressesConfig,
    IxiaConfigCache,
    RouteScale,
    RouteScaleSpec,
    Task,
    TestConfig,
)


# =============================================================================
# Absorbed helpers (Wave 5D.1) -- historically lived at
# ``testconfigs/routing/ebb/test_config_performance_scaling_case2.py`` and
# ``testconfigs/routing/ebb/test_config_queue_memory_monitor.py``. Bodies
# copied verbatim so serialized TestConfig output is byte-wise identical.
# The new ``create_bgp_ebb_characteristic_*`` factories below (and the
# existing bag012 conveyor factories) call these helpers by name.
# =============================================================================


def test_config_constant_attribute_storage_on_eos(
    test_config_name: str,
    device_name: str,
    ixia_interface_mimic_ebgp: str,
    ebgp_remote_as: int,
    ixia_ebgp_ic_parent_network_v6: str,
    ixia_ebgp_ic_parent_network_v4: str,
    ebgp_peer_counts: list[int],
    constant_total_paths: int = 400000,
    as_path_pool_size: int = 100,
    community_pool_size: int = 50,
    extended_community_pool_size: int = 50,
    as_path_length: int = 4,
    constant_acceptance_communities: list[str] | None = None,
    max_communities_per_route_from_pool: int | None = None,
    randomize_attributes: bool = False,
    random_seed: int = 42,
    test_route_withdrawal: bool = False,
    withdrawal_wait_minutes: int = 3,
    dump_attribute_assignments: bool = True,
    soak_time_minutes: int = 10,
    direct_ixia_connections: list | None = None,
    log_collection_timeout: int | None = None,
    oss_mock_device_data=None,
    host_os_type_map=None,
    host_driver_args=None,
) -> taac_types.TestConfig:
    """BGP++ constant total-paths test on Arista EOS.

    Byte-identical to the legacy
    ``testconfigs/routing/ebb/test_config_performance_scaling_case2``
    ``test_config_constant_attribute_storage_on_eos``. See that file's
    header (pre-deletion) for the full test design notes.
    """
    initial_ebgp_peer_count = 1

    as_path_pool = generate_as_path_pool(
        count=as_path_pool_size,
        base_as=65000,
        as_path_length=as_path_length,
    )

    community_pool = generate_community_pool(
        count=community_pool_size,
        base_community=65000,
    )

    extended_community_pool = generate_extended_community_pool(
        count=extended_community_pool_size,
        base_rt=65000,
    )

    ixia_ports = [ixia_interface_mimic_ebgp]

    return TestConfig(
        name=test_config_name,
        skip_ixia_protocol_verification=True,
        log_collection_timeout=log_collection_timeout,
        basset_pool="dne.test",
        endpoints=[
            Endpoint(
                name=device_name,
                dut=True,
                ixia_ports=ixia_ports,
                direct_ixia_connections=direct_ixia_connections
                if direct_ixia_connections
                else [],
            ),
        ],
        host_driver_args=host_driver_args,
        oss_mock_device_data=oss_mock_device_data,
        host_os_type_map=host_os_type_map,
        startup_checks=[],
        setup_tasks=[],
        teardown_tasks=[],
        basic_port_configs=[
            BasicPortConfig(
                endpoint=f"{device_name}:{ixia_interface_mimic_ebgp}",
                device_group_configs=[
                    DeviceGroupConfig(
                        device_group_name="DEVICE_GROUP_IPV6_EBGP",
                        device_group_index=0,
                        multiplier=initial_ebgp_peer_count,
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
                            bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                            route_scales=[
                                RouteScaleSpec(
                                    v6_route_scale=RouteScale(
                                        prefix_name="PREFIX_POOL_IPV6_EBGP",
                                        starting_prefixes="2001:db8:1000::",
                                        prefix_step="0:0:1::",
                                        prefix_length=64,
                                        multiplier=1,
                                        prefix_count=1,
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
                        multiplier=initial_ebgp_peer_count,
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
                            bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                            route_scales=[
                                RouteScaleSpec(
                                    v4_route_scale=RouteScale(
                                        prefix_name="PREFIX_POOL_IPV4_EBGP",
                                        starting_prefixes="10.100.0.0",
                                        prefix_step="0.0.1.0",
                                        prefix_length=24,
                                        multiplier=1,
                                        prefix_count=1,
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
        ],
        playbooks=[
            build_case2_playbook(
                name="bgp_plus_plus_constant_attribute_storage_test",
                description="Test BGP++ constant attribute storage with varying EBGP peers and prefix counts",
                stages=[
                    create_steps_stage(
                        steps=[
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "test_constant_attribute_storage_eos_bgp_plus_plus",
                                    "hostname": device_name,
                                    "ixia_interface_mimic_ebgp": ixia_interface_mimic_ebgp,
                                    "ebgp_peer_counts": ebgp_peer_counts,
                                    "constant_total_paths": constant_total_paths,
                                    "soak_time_minutes": soak_time_minutes,
                                    "attribute_pool_as_paths": as_path_pool,
                                    "attribute_pool_communities": community_pool,
                                    "attribute_pool_extended_communities": extended_community_pool,
                                    "attach_communities_for_ebgp_prefixes": constant_acceptance_communities,
                                    "max_communities_per_route_from_pool": max_communities_per_route_from_pool,
                                    "randomize_attributes": randomize_attributes,
                                    "random_seed": random_seed,
                                    "test_route_withdrawal": test_route_withdrawal,
                                    "withdrawal_wait_minutes": withdrawal_wait_minutes,
                                    "dump_attribute_assignments": dump_attribute_assignments,
                                }
                            ),
                        ],
                    )
                ],
            ),
        ],
    )


def test_config_constant_attribute_storage_varying_combinations_on_eos(
    test_config_name: str,
    device_name: str,
    ixia_interface_mimic_ebgp: str,
    ebgp_remote_as: int,
    ixia_ebgp_ic_parent_network_v6: str,
    ixia_ebgp_ic_parent_network_v4: str,
    unique_combination_counts: list[int],
    ixia_interface_mimic_ibgp: str | None = None,
    ibgp_local_as: int | None = None,
    ixia_ibgp_ic_parent_network_v6: str | None = None,
    ixia_ibgp_ic_parent_network_v4: str | None = None,
    constant_ebgp_peer_count: int = 8,
    constant_ibgp_peer_count: int = 2,
    constant_total_paths: int = 800_000,
    test_address_families: list[str] | None = None,
    base_as_path_pool_size: int = 100,
    base_community_pool_size: int = 100,
    base_extended_community_pool_size: int = 100,
    constant_acceptance_communities: list[str] | None = None,
    max_communities_per_route_from_pool: int | None = None,
    random_seed: int = 42,
    test_route_withdrawal: bool = False,
    withdrawal_wait_minutes: int = 3,
    dump_attribute_assignments: bool = False,
    soak_time_minutes: int = 10,
    direct_ixia_connections: list | None = None,
    log_collection_timeout: int | None = None,
    peergroup_ebgp_v6: str | None = None,
    peergroup_ebgp_v4: str | None = None,
    peergroup_ibgp_v6: str | None = None,
    peergroup_ibgp_v4: str | None = None,
    ssh_password: str = "",
    setup_tasks: list[Task] | None = None,
    oss_mock_device_data=None,
    host_os_type_map=None,
    host_driver_args=None,
) -> taac_types.TestConfig:
    """Constant Attribute Storage varying-combinations test on Arista EOS.

    Byte-identical to the legacy
    ``testconfigs/routing/ebb/test_config_performance_scaling_case2``
    ``test_config_constant_attribute_storage_varying_combinations_on_eos``.
    """
    if test_address_families is None:
        test_address_families = ["ipv4", "ipv6"]

    num_afs = len(test_address_families)
    if num_afs == 2:
        initial_ebgp_peer_count = constant_ebgp_peer_count // 2
        initial_ibgp_peer_count = constant_ibgp_peer_count // 2
    elif "ipv4" in test_address_families:
        initial_ebgp_peer_count = constant_ebgp_peer_count
        initial_ibgp_peer_count = constant_ibgp_peer_count
    else:
        initial_ebgp_peer_count = constant_ebgp_peer_count
        initial_ibgp_peer_count = constant_ibgp_peer_count

    ixia_ports = [ixia_interface_mimic_ebgp]
    if ixia_interface_mimic_ibgp:
        ixia_ports.append(ixia_interface_mimic_ibgp)

    ebgp_device_groups = []
    if "ipv6" in test_address_families:
        ebgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV6_EBGP",
                device_group_index=len(ebgp_device_groups),
                multiplier=initial_ebgp_peer_count,
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
                    bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                    route_scales=[
                        RouteScaleSpec(
                            v6_route_scale=RouteScale(
                                prefix_name="PREFIX_POOL_IPV6_EBGP",
                                starting_prefixes="2001:db8:1000::",
                                prefix_step="0:0:1::",
                                prefix_length=64,
                                multiplier=1,
                                prefix_count=constant_total_paths
                                // constant_ebgp_peer_count,
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                bgp_communities=[],
                            ),
                            multiplier=1,
                            network_group_index=0,
                        )
                    ],
                ),
            )
        )

    if "ipv4" in test_address_families:
        ebgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV4_EBGP",
                device_group_index=len(ebgp_device_groups),
                multiplier=initial_ebgp_peer_count,
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
                    bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                    route_scales=[
                        RouteScaleSpec(
                            v4_route_scale=RouteScale(
                                prefix_name="PREFIX_POOL_IPV4_EBGP",
                                starting_prefixes="50.100.0.0",
                                prefix_step="0.0.1.0",
                                prefix_length=24,
                                multiplier=1,
                                prefix_count=constant_total_paths
                                // constant_ebgp_peer_count,
                                ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                bgp_communities=[],
                            ),
                            multiplier=1,
                            network_group_index=0,
                        )
                    ],
                ),
            )
        )

    ibgp_device_groups = []
    if (
        ixia_interface_mimic_ibgp
        and ibgp_local_as
        and ixia_ibgp_ic_parent_network_v6
        and ixia_ibgp_ic_parent_network_v4
    ):
        if "ipv6" in test_address_families:
            ibgp_device_groups.append(
                DeviceGroupConfig(
                    device_group_name="DEVICE_GROUP_IPV6_IBGP",
                    device_group_index=len(ibgp_device_groups),
                    multiplier=initial_ibgp_peer_count,
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
                        bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                    ),
                )
            )

        if "ipv4" in test_address_families:
            ibgp_device_groups.append(
                DeviceGroupConfig(
                    device_group_name="DEVICE_GROUP_IPV4_IBGP",
                    device_group_index=len(ibgp_device_groups),
                    multiplier=initial_ibgp_peer_count,
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
                        bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                    ),
                )
            )

    return TestConfig(
        name=test_config_name,
        skip_ixia_protocol_verification=True,
        log_collection_timeout=log_collection_timeout,
        basset_pool="dne.test",
        endpoints=[
            Endpoint(
                name=device_name,
                dut=True,
                ixia_ports=ixia_ports,
                direct_ixia_connections=direct_ixia_connections
                if direct_ixia_connections
                else [],
            ),
        ],
        host_driver_args=host_driver_args,
        oss_mock_device_data=oss_mock_device_data,
        host_os_type_map=host_os_type_map,
        startup_checks=[],
        setup_tasks=setup_tasks if setup_tasks else [],
        teardown_tasks=[],
        basic_port_configs=[
            BasicPortConfig(
                endpoint=f"{device_name}:{ixia_interface_mimic_ebgp}",
                device_group_configs=ebgp_device_groups,
            ),
            *(
                [
                    BasicPortConfig(
                        endpoint=f"{device_name}:{ixia_interface_mimic_ibgp}",
                        device_group_configs=ibgp_device_groups,
                    ),
                ]
                if ibgp_device_groups
                else []
            ),
        ],
        playbooks=[
            build_case2_playbook(
                name="bgp_plus_plus_constant_attribute_storage_varying_combinations_test",
                description="Test BGP++ constant attribute storage with varying unique combination counts",
                stages=[
                    create_steps_stage(
                        steps=[
                            create_custom_step(
                                params_dict={
                                    "custom_step_name": "test_constant_attribute_storage_varying_combinations_eos_bgp_plus_plus",
                                    "hostname": device_name,
                                    "ixia_interface_mimic_ebgp": ixia_interface_mimic_ebgp,
                                    "constant_ebgp_peer_count": constant_ebgp_peer_count,
                                    "constant_ibgp_peer_count": constant_ibgp_peer_count,
                                    "ixia_interface_mimic_ibgp": ixia_interface_mimic_ibgp,
                                    "constant_total_paths": constant_total_paths,
                                    "unique_combination_counts": unique_combination_counts,
                                    "test_address_families": test_address_families,
                                    "soak_time_minutes": soak_time_minutes,
                                    "base_as_path_pool_size": base_as_path_pool_size,
                                    "base_community_pool_size": base_community_pool_size,
                                    "base_extended_community_pool_size": base_extended_community_pool_size,
                                    "as_path_length": 5,
                                    "communities_per_route": 5,
                                    "extended_communities_per_route": 1,
                                    "attach_communities_for_ebgp_prefixes": constant_acceptance_communities,
                                    "max_communities_per_route_from_pool": max_communities_per_route_from_pool,
                                    "random_seed": random_seed,
                                    "test_route_withdrawal": test_route_withdrawal,
                                    "withdrawal_wait_minutes": withdrawal_wait_minutes,
                                    "dump_attribute_assignments": dump_attribute_assignments,
                                    **(
                                        {
                                            "ebgp_remote_as": ebgp_remote_as,
                                            "ibgp_remote_as": ibgp_local_as,
                                            "ixia_ebgp_ic_parent_network_v6": ixia_ebgp_ic_parent_network_v6,
                                            "ixia_ebgp_ic_parent_network_v4": ixia_ebgp_ic_parent_network_v4,
                                            "ixia_ibgp_ic_parent_network_v6": ixia_ibgp_ic_parent_network_v6,
                                            "ixia_ibgp_ic_parent_network_v4": ixia_ibgp_ic_parent_network_v4,
                                            "peergroup_ebgp_v6": peergroup_ebgp_v6,
                                            "peergroup_ebgp_v4": peergroup_ebgp_v4,
                                            "peergroup_ibgp_v6": peergroup_ibgp_v6,
                                            "peergroup_ibgp_v4": peergroup_ibgp_v4,
                                            "ssh_password": ssh_password,
                                        }
                                        if setup_tasks is None
                                        else {}
                                    ),
                                }
                            ),
                        ],
                    )
                ],
            ),
        ],
    )


def test_config_bgp_queue_memory_monitoring_with_route_scale(
    test_config_name: str,
    device_name: str,
    ixia_interface_mimic_ibgp: str,
    ibgp_local_as: int,
    ixia_ibgp_ic_parent_network_v6: str,
    ixia_ibgp_ic_parent_network_v4: str,
    ixia_interface_mimic_ebgp: str,
    ebgp_remote_as: int,
    ixia_ebgp_ic_parent_network_v6: str,
    ixia_ebgp_ic_parent_network_v4: str,
    ibgp_peer_count: int = 25,
    ebgp_peer_count: int = 50,
    prefixes_per_ebgp_peer: int = 10000,
    ip_version: str = "ipv6",
    ebgp_route_acceptance_communities: list[str] | None = None,
    monitoring_duration_minutes: int = 60,
    monitoring_interval_seconds: int = 120,
    flap_uptime_seconds: int = 15,
    flap_downtime_seconds: int = 15,
    direct_ixia_connections: list | None = None,
    log_collection_timeout: int | None = None,
    oss_mock_device_data=None,
    host_os_type_map=None,
    host_driver_args=None,
    setup_tasks: list | None = None,
    teardown_tasks: list | None = None,
    monitor_cpu_stress: bool = False,
    ssh_user: str | None = None,
    ssh_password: str | None = None,
    peergroup_ebgp_v6: str = "EB-FA-V6",
    peergroup_ebgp_v4: str = "EB-FA-V4",
    peergroup_ibgp_v6: str = "EB-EB-V6",
    peergroup_ibgp_v4: str = "EB-EB-V4",
) -> taac_types.TestConfig:
    """BGP++ queue and memory monitoring under route churn.

    Byte-identical to the legacy
    ``testconfigs/routing/ebb/test_config_queue_memory_monitor``
    ``test_config_bgp_queue_memory_monitoring_with_route_scale``.
    """
    ebgp_as_paths = generate_as_path_pool(
        count=ebgp_peer_count,
        base_as=64512,
        as_path_length=100,
    )

    ibgp_device_groups = []
    if ip_version in ["ipv6", "both"]:
        ibgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV6_IBGP",
                device_group_index=0,
                multiplier=ibgp_peer_count,
                enable=False,
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

    if ip_version in ["ipv4", "both"]:
        ibgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV4_IBGP",
                device_group_index=1 if ip_version == "both" else 0,
                multiplier=ibgp_peer_count,
                enable=False,
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

    ebgp_device_groups = []
    if ip_version in ["ipv6", "both"]:
        ebgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV6_EBGP",
                device_group_index=0,
                multiplier=ebgp_peer_count,
                enable=False,
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
                                prefix_step="0:0:0:0:0:0:0:0",
                                prefix_length=64,
                                multiplier=1,
                                prefix_count=prefixes_per_ebgp_peer,
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                bgp_communities=ebgp_route_acceptance_communities
                                if ebgp_route_acceptance_communities
                                else [],
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

    if ip_version in ["ipv4", "both"]:
        ebgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV4_EBGP",
                device_group_index=1 if ip_version == "both" else 0,
                multiplier=ebgp_peer_count,
                enable=False,
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
                                prefix_step="0.0.0.0",
                                prefix_length=24,
                                multiplier=1,
                                prefix_count=prefixes_per_ebgp_peer,
                                ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                bgp_communities=ebgp_route_acceptance_communities
                                if ebgp_route_acceptance_communities
                                else [],
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
        basic_port_configs=[
            BasicPortConfig(
                endpoint=f"{device_name}:{ixia_interface_mimic_ibgp}",
                device_group_configs=ibgp_device_groups,
            ),
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


# =============================================================================
# Wave 5D.1 -- new physical-inventory-driven factories for the routing catalog.
# =============================================================================


def create_bgp_ebb_characteristic_constant_attribute_storage_test_config(
    physical_inventory: PhysicalInventory,
    *,
    name: str,
    ebgp_remote_as: int = 65334,
    ixia_ebgp_ic_parent_network_v6: str = "2401:db00:e50d:11:8",
    ixia_ebgp_ic_parent_network_v4: str = "10.163.28",
    ebgp_peer_counts: list[int] | None = None,
    constant_total_paths: int = 800000,
    as_path_pool_size: int = 800000,
    community_pool_size: int = 50,
    extended_community_pool_size: int = 0,
    as_path_length: int = 4,
    constant_acceptance_communities: list[str] | None = None,
    max_communities_per_route_from_pool: int | None = 5,
    randomize_attributes: bool = False,
    random_seed: int = 42,
    dump_attribute_assignments: bool = True,
    soak_time_minutes: int = 10,
    log_collection_timeout: int | None = None,
    direct_ixia_connections: list[DirectIxiaConnection] | None = None,
) -> taac_types.TestConfig:
    """Constant Attribute Storage / High-Diversity TestConfig (legacy case2 factory 1).

    Byte-identical to the legacy
    ``eb03_arista_high_diversity_test_config.py`` wrapper when invoked with
    ``EB03_LAB_ASH6`` and its wrapper defaults; DUT identity + IXIA port map
    + host_driver_args + oss_mock_device_data are derived from ``physical_inventory``
    directly (populated on the lab PhysicalInventory instances as first-class fields).
    """
    if ebgp_peer_counts is None:
        ebgp_peer_counts = [8, 16, 32, 64, 128]
    if constant_acceptance_communities is None:
        constant_acceptance_communities = ["65529:39744"]

    device_name = physical_inventory.device_name
    ebgp_iface, ebgp_port = physical_inventory.ixia_ports[0]

    host_driver_args = physical_inventory.host_driver_args
    oss_mock_device_data = physical_inventory.oss_mock_device_data
    host_os_type_map = {device_name: taac_types.DeviceOsType.ARISTA_FBOSS}
    resolved_direct_ixia_connections = (
        direct_ixia_connections
        if direct_ixia_connections is not None
        else [
            DirectIxiaConnection(
                interface=ebgp_iface,
                ixia_chassis_ip=physical_inventory.ixia_chassis_ip,
                ixia_port=ebgp_port,
            ),
        ]
    )

    return test_config_constant_attribute_storage_on_eos(
        test_config_name=name,
        device_name=device_name,
        ixia_interface_mimic_ebgp=ebgp_iface,
        ebgp_remote_as=ebgp_remote_as,
        ixia_ebgp_ic_parent_network_v6=ixia_ebgp_ic_parent_network_v6,
        ixia_ebgp_ic_parent_network_v4=ixia_ebgp_ic_parent_network_v4,
        ebgp_peer_counts=ebgp_peer_counts,
        constant_total_paths=constant_total_paths,
        as_path_pool_size=as_path_pool_size,
        community_pool_size=community_pool_size,
        extended_community_pool_size=extended_community_pool_size,
        as_path_length=as_path_length,
        soak_time_minutes=soak_time_minutes,
        host_driver_args=host_driver_args,
        oss_mock_device_data=oss_mock_device_data,
        host_os_type_map=host_os_type_map,
        direct_ixia_connections=resolved_direct_ixia_connections,
        constant_acceptance_communities=constant_acceptance_communities,
        max_communities_per_route_from_pool=max_communities_per_route_from_pool,
        randomize_attributes=randomize_attributes,
        random_seed=random_seed,
        dump_attribute_assignments=dump_attribute_assignments,
        log_collection_timeout=log_collection_timeout,
    )


def create_bgp_ebb_characteristic_constant_attribute_storage_varying_combinations_test_config(
    physical_inventory: PhysicalInventory,
    *,
    name: str,
    ebgp_remote_as: int = 65334,
    ixia_ebgp_ic_parent_network_v6: str = "2401:db00:e50d:11:8",
    ixia_ebgp_ic_parent_network_v4: str = "10.163.28",
    ibgp_local_as: int = 64981,
    ixia_ibgp_ic_parent_network_v6: str = "2401:db00:e50d:11:9",
    ixia_ibgp_ic_parent_network_v4: str = "10.164.28",
    constant_ebgp_peer_count: int = 8,
    constant_ibgp_peer_count: int = 2,
    constant_total_paths: int = 800_000,
    unique_combination_counts: list[int] | None = None,
    soak_time_minutes: int = 2,
    dump_attribute_assignments: bool = True,
    test_address_families: list[str] | None = None,
    constant_acceptance_communities: list[str] | None = None,
    max_communities_per_route_from_pool: int | None = 5,
    random_seed: int = 42,
    peergroup_ebgp_v6: str = "EB-FA-V6",
    peergroup_ebgp_v4: str = "EB-FA-V4",
    peergroup_ibgp_v6: str = "EB-EB-V6",
    peergroup_ibgp_v4: str = "EB-EB-V4",
    log_collection_timeout: int | None = None,
    direct_ixia_connections: list[DirectIxiaConnection] | None = None,
) -> taac_types.TestConfig:
    """Constant Attribute Storage varying-combinations TestConfig (legacy case2 factory 2).

    Byte-identical to the legacy
    ``eb02_arista_constant_attribute_storage_varying_combinations_test_config.py``
    wrapper when invoked with ``EB02_LAB_ASH6`` and its wrapper defaults.
    """
    if unique_combination_counts is None:
        unique_combination_counts = [
            100_000,
            200_000,
            400_000,
            600_000,
            800_000,
        ]
    if test_address_families is None:
        test_address_families = ["ipv6"]
    if constant_acceptance_communities is None:
        constant_acceptance_communities = ["65529:39744"]

    device_name = physical_inventory.device_name
    ebgp_iface, ebgp_port = physical_inventory.ixia_ports[0]
    ibgp_iface, ibgp_port = physical_inventory.ixia_ports[1]

    host_driver_args = physical_inventory.host_driver_args
    oss_mock_device_data = physical_inventory.oss_mock_device_data
    host_os_type_map = {device_name: taac_types.DeviceOsType.ARISTA_FBOSS}
    resolved_direct_ixia_connections = (
        direct_ixia_connections
        if direct_ixia_connections is not None
        else [
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
    )

    lab_password_env = (
        physical_inventory.lab_device_password_env_var or "TAAC_EBB_LAB_DEVICE_PASSWORD"
    )
    lab_admin_password_default = physical_inventory.extras.get(
        "lab_admin_password_default",
        "dnepit",  # pragma: allowlist secret
    )
    ssh_password = os.environ.get(lab_password_env, lab_admin_password_default)

    return test_config_constant_attribute_storage_varying_combinations_on_eos(
        test_config_name=name,
        device_name=device_name,
        ixia_interface_mimic_ebgp=ebgp_iface,
        ebgp_remote_as=ebgp_remote_as,
        ixia_ebgp_ic_parent_network_v6=ixia_ebgp_ic_parent_network_v6,
        ixia_ebgp_ic_parent_network_v4=ixia_ebgp_ic_parent_network_v4,
        ixia_interface_mimic_ibgp=ibgp_iface,
        ibgp_local_as=ibgp_local_as,
        ixia_ibgp_ic_parent_network_v6=ixia_ibgp_ic_parent_network_v6,
        ixia_ibgp_ic_parent_network_v4=ixia_ibgp_ic_parent_network_v4,
        constant_ebgp_peer_count=constant_ebgp_peer_count,
        constant_ibgp_peer_count=constant_ibgp_peer_count,
        constant_total_paths=constant_total_paths,
        unique_combination_counts=unique_combination_counts,
        soak_time_minutes=soak_time_minutes,
        dump_attribute_assignments=dump_attribute_assignments,
        test_address_families=test_address_families,
        host_driver_args=host_driver_args,
        oss_mock_device_data=oss_mock_device_data,
        host_os_type_map=host_os_type_map,
        direct_ixia_connections=resolved_direct_ixia_connections,
        constant_acceptance_communities=constant_acceptance_communities,
        max_communities_per_route_from_pool=max_communities_per_route_from_pool,
        random_seed=random_seed,
        peergroup_ebgp_v6=peergroup_ebgp_v6,
        peergroup_ebgp_v4=peergroup_ebgp_v4,
        peergroup_ibgp_v6=peergroup_ibgp_v6,
        peergroup_ibgp_v4=peergroup_ibgp_v4,
        ssh_password=ssh_password,
        log_collection_timeout=log_collection_timeout,
    )


def create_bgp_ebb_characteristic_queue_memory_monitor_test_config(
    physical_inventory: PhysicalInventory,
    *,
    name: str,
    ibgp_local_as: int = 64981,
    ixia_ibgp_ic_parent_network_v6: str = "2401:db00:e50d:11:9",
    ixia_ibgp_ic_parent_network_v4: str = "10.164.28",
    ebgp_remote_as: int = 65334,
    ixia_ebgp_ic_parent_network_v6: str = "2401:db00:e50d:11:8",
    ixia_ebgp_ic_parent_network_v4: str = "10.163.28",
    ibgp_peer_count: int = 50,
    ebgp_peer_count: int = 50,
    prefixes_per_ebgp_peer: int = 15000,
    ip_version: str = "both",
    ebgp_route_acceptance_communities: list[str] | None = None,
    monitoring_duration_minutes: int = 30,
    monitoring_interval_seconds: int = 60,
    flap_uptime_seconds: int = 15,
    flap_downtime_seconds: int = 15,
    ssh_user: str | None = None,
    log_collection_timeout: int | None = None,
    direct_ixia_connections: list[DirectIxiaConnection] | None = None,
) -> taac_types.TestConfig:
    """BGP++ queue-memory-monitor TestConfig (legacy queue_memory_monitor factory).

    Byte-identical to the legacy
    ``eb02_arista_bgp_queue_memory_monitor_ipv6_50ebgp_25ibgp_with_flapping_test_config.py``
    /  ``eb04_.../..._test_config.py`` / ``eb_test_device_.../..._test_config.py``
    wrappers when invoked with the respective physical_inventory + wrapper defaults.

    Note: legacy wrappers use different ``direct_ixia_connections`` orderings
    (EB02 + EB_TEST_DEVICE: EBGP-first; EB04: IBGP-first). Callers pass the
    exact list to preserve golden-manifest byte identity.
    """
    if ebgp_route_acceptance_communities is None:
        ebgp_route_acceptance_communities = ["65529:39744"]

    device_name = physical_inventory.device_name
    ebgp_iface, _ebgp_port = physical_inventory.ixia_ports[0]
    ibgp_iface, _ibgp_port = physical_inventory.ixia_ports[1]

    host_driver_args = physical_inventory.host_driver_args
    oss_mock_device_data = physical_inventory.oss_mock_device_data
    host_os_type_map = {device_name: taac_types.DeviceOsType.ARISTA_FBOSS}

    ssh_password: str | None = None
    if ssh_user is not None:
        lab_password_env = (
            physical_inventory.lab_device_password_env_var
            or "TAAC_EBB_LAB_DEVICE_PASSWORD"
        )
        lab_admin_password_default = physical_inventory.extras.get(
            "lab_admin_password_default",
            "dnepit",  # pragma: allowlist secret
        )
        ssh_password = os.environ.get(lab_password_env, lab_admin_password_default)

    return test_config_bgp_queue_memory_monitoring_with_route_scale(
        test_config_name=name,
        device_name=device_name,
        ixia_interface_mimic_ibgp=ibgp_iface,
        ibgp_local_as=ibgp_local_as,
        ixia_ibgp_ic_parent_network_v6=ixia_ibgp_ic_parent_network_v6,
        ixia_ibgp_ic_parent_network_v4=ixia_ibgp_ic_parent_network_v4,
        ixia_interface_mimic_ebgp=ebgp_iface,
        ebgp_remote_as=ebgp_remote_as,
        ixia_ebgp_ic_parent_network_v6=ixia_ebgp_ic_parent_network_v6,
        ixia_ebgp_ic_parent_network_v4=ixia_ebgp_ic_parent_network_v4,
        ibgp_peer_count=ibgp_peer_count,
        ebgp_peer_count=ebgp_peer_count,
        prefixes_per_ebgp_peer=prefixes_per_ebgp_peer,
        ip_version=ip_version,
        ebgp_route_acceptance_communities=ebgp_route_acceptance_communities,
        monitoring_duration_minutes=monitoring_duration_minutes,
        monitoring_interval_seconds=monitoring_interval_seconds,
        flap_uptime_seconds=flap_uptime_seconds,
        flap_downtime_seconds=flap_downtime_seconds,
        ssh_user=ssh_user,
        ssh_password=ssh_password,
        host_driver_args=host_driver_args,
        oss_mock_device_data=oss_mock_device_data,
        host_os_type_map=host_os_type_map,
        direct_ixia_connections=direct_ixia_connections,
        log_collection_timeout=log_collection_timeout,
    )


# =============================================================================
# BAG012_ASH6 conveyor family — Update Packing / Constant Attribute Storage /
# Queue Memory Monitor / Performance Scaling / Bounded ECMP.
# =============================================================================
# Defaults for the performance-scaling egress IBGP peer sweep match the
# simplified rewrite of D104072489: per stage n peers per AF, total = 2n + 2
# EBGP. Each Stage rewrites /mnt/flash/bgpcpp_config to the matching number of
# peer entries so BGP++ EOR completes from 100% of configured peers.
_PERFORMANCE_SCALING_EGRESS_PEER_COUNTS: list = [100, 200, 300, 400, 500]
_PERFORMANCE_SCALING_PREFIX_COUNT: int = 50000

# Interface-state nexthop-resolution gflag. This test runs WITHOUT_OPEN_R, so
# recursive/loopback nexthops never resolve via the (dead) Open/R FIB stream;
# the eBGP nexthop is directly connected and must resolve through NetlinkWrapper
# instead. NetlinkWrapper only populates the nexthopCache from interface
# link-state + prefix match when bgp_resolve_nexthops_from_interface_state is
# set; with the default (legacy, ARP/ND-based) path the connected nexthop stayed
# unresolved, so no path was ever selected and convergence completed vacuously.
# Enabling the gflag in run_bgpcpp.sh makes egress routes actually resolve and
# get selected.
_NEXTHOP_IFACE_STATE_FLAG: str = "bgp_resolve_nexthops_from_interface_state"

# bag012.ash6 nexthop group threshold parameters for bounded ECMP.
_BAG012_BOUNDED_ECMP_PEER_COUNT: int = 128
_BAG012_BOUNDED_ECMP_PREFIX_COUNT: int = 5000


def _two_port_direct_ixia_connections(
    physical_inventory: PhysicalInventory,
) -> list[DirectIxiaConnection]:
    """Two DirectIxiaConnection entries from ``physical_inventory.ixia_ports[0]`` (eBGP)
    and ``[1]`` (iBGP).

    For the 2-port EBB characteristic tests (no BGP-MON connection). PhysicalInventory instances
    that also wire a third BGP-MON port (bag010/bag011/bag013) leave it unused
    here.
    """
    ebgp_iface, ebgp_port = physical_inventory.ixia_ports[0]
    ibgp_iface, ibgp_port = physical_inventory.ixia_ports[1]
    return [
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


def create_bgp_ebb_update_packing_test_config(
    physical_inventory: PhysicalInventory,
    enable_update_group: bool = False,
    name_override: str | None = None,
) -> taac_types.TestConfig:
    """BGP Update Packing conveyor test config for bag012.ash6.

    Renamed from ``create_bgp_ebb_conveyor_test_config`` — the "conveyor"
    label was ambiguous (all configs in this file are conveyor-scheduled);
    the actual test is BGP update-packing validation.

    Extracted verbatim from the legacy
    ``bag012_ash6_test_config.create_bag012_ash6_conveyor_test_config``
    factory. Reuses ``test_config_bgp_update_packing_validation()`` with
    bag012-specific setup_tasks + direct_ixia_connections.

    Test direction matches EB02_ARISTA_BGP_UPDATE_PACKING_VALIDATION:
    - EBGP → IBGP: 10 EBGP peers inject routes, 1 IBGP peer captures UPDATEs.
    - ``ebgp_route_acceptance_communities=["65529:39744"]``.
    """
    assert physical_inventory.ixia_ports, (
        "factory requires IXIA port map on physical_inventory"
    )
    assert physical_inventory.bgpcpp_configerator_path, (
        "factory requires bgpcpp_configerator_path on physical_inventory"
    )
    assert physical_inventory.dut_bgp_as is not None, (
        "factory requires dut_bgp_as on physical_inventory"
    )
    assert physical_inventory.router_id, (
        "factory requires router_id on physical_inventory"
    )

    device_name = physical_inventory.device_name
    ixia_interface_mimic_ebgp = physical_inventory.ixia_ports[0][0]
    ixia_interface_mimic_ibgp = physical_inventory.ixia_ports[1][0]

    name = name_override or _derive_test_config_name(
        physical_inventory, "UPDATE_PACKING", enable_update_group
    )

    bound = IPV6_UPDATE_PACKING.bind_to_inventory(
        physical_inventory=physical_inventory,
        port_map=IPV6_UPDATE_PACKING_PORT_MAP,
        parent_networks=IPV6_UPDATE_PACKING_PARENT_NETWORKS,
        peer_groups=IPV6_UPDATE_PACKING_PEER_GROUPS,
        as_numbers=IPV6_UPDATE_PACKING_AS_NUMBERS,
        device_config_override=RoutingDeviceConfig(
            update_group_enable=enable_update_group,
        ),
    )
    compiled = bound.compile()

    return test_config_bgp_update_packing_validation(
        test_config_name=name,
        device_name=device_name,
        # EBGP configuration (ingress - routes sent here from Fabric Aggregators)
        ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
        ebgp_remote_as=EBGP_REMOTE_AS,
        ixia_ebgp_ic_parent_network_v6=IXIA_EBGP_IC_PARENT_NETWORK_V6,
        ixia_ebgp_ic_parent_network_v4="",
        # IBGP configuration (egress - capture UPDATEs here)
        ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
        ibgp_local_as=IBGP_REMOTE_AS,
        ixia_ibgp_ic_parent_network_v6=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
        ixia_ibgp_ic_parent_network_v4="",
        # Test parameters (matching EB02)
        ebgp_peer_count=10,
        prefixes_per_peer=10000,
        ibgp_peer_count=1,
        test_address_families=["ipv6"],
        as_path_pool_size=10,
        community_pool_size=20,
        as_path_length=3,
        communities_per_route=2,
        ebgp_route_acceptance_communities=["65529:39744"],
        capture_duration_seconds=300,
        min_packed_size=4000,
        restart_bgp_for_complete_view=True,
        # Conveyor-specific configuration
        setup_tasks=compiled.setup_tasks,
        teardown_tasks=compiled.teardown_tasks,
        host_os_type_map=compiled.host_os_type_map,
        endpoints=compiled.endpoints,
        basic_port_configs=compiled.basic_port_configs,
        log_collection_timeout=600,
    )


def create_bgp_ebb_constant_attribute_storage_test_config(
    physical_inventory: PhysicalInventory,
    enable_update_group: bool = False,
    name_override: str | None = None,
) -> taac_types.TestConfig:
    """Constant Attribute Storage varying-combinations test config for bag012.ash6.

    Extracted verbatim from the legacy
    ``bag012_ash6_test_config.create_bag012_ash6_constant_attribute_storage_test_config``
    factory. Validates that the amount of memory for storing pool of
    attributes remains constant regardless of the number of unique
    attribute-set combinations.
    """
    assert physical_inventory.ixia_ports, (
        "factory requires IXIA port map on physical_inventory"
    )
    assert physical_inventory.bgpcpp_configerator_path, (
        "factory requires bgpcpp_configerator_path on physical_inventory"
    )
    assert physical_inventory.dut_bgp_as is not None, (
        "factory requires dut_bgp_as on physical_inventory"
    )
    assert physical_inventory.router_id, (
        "factory requires router_id on physical_inventory"
    )

    device_name = physical_inventory.device_name
    ixia_interface_mimic_ebgp = physical_inventory.ixia_ports[0][0]
    ixia_interface_mimic_ibgp = physical_inventory.ixia_ports[1][0]

    name = name_override or _derive_test_config_name(
        physical_inventory, "CONSTANT_ATTRIBUTE_STORAGE", enable_update_group
    )

    setup_tasks = get_update_packing_setup_tasks(
        device_name=device_name,
        bgp_asn=physical_inventory.dut_bgp_as,
        ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
        ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
        ebgp_peer_count=8,
        ibgp_peer_count=2,
        ebgp_remote_as=EBGP_REMOTE_AS,
        ibgp_remote_as=IBGP_REMOTE_AS,
        ixia_ebgp_ic_parent_network_v6=IXIA_EBGP_IC_PARENT_NETWORK_V6,
        ixia_ibgp_ic_parent_network_v6=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
        router_id=physical_inventory.router_id,
        bgpcpp_configerator_path=physical_inventory.bgpcpp_configerator_path,
        profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
        enable_update_group=enable_update_group,
    )

    return test_config_constant_attribute_storage_varying_combinations_on_eos(
        test_config_name=name,
        device_name=device_name,
        # EBGP configuration
        ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
        ebgp_remote_as=EBGP_REMOTE_AS,
        ixia_ebgp_ic_parent_network_v6=IXIA_EBGP_IC_PARENT_NETWORK_V6,
        ixia_ebgp_ic_parent_network_v4=IXIA_EBGP_IC_PARENT_NETWORK_V4,
        # IBGP configuration
        ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
        ibgp_local_as=IBGP_REMOTE_AS,
        ixia_ibgp_ic_parent_network_v6=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
        ixia_ibgp_ic_parent_network_v4=IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
        # Fixed: 8 EBGP peers + 2 IBGP peers (smaller scale)
        constant_ebgp_peer_count=8,
        constant_ibgp_peer_count=2,
        # Fixed: 800K total paths
        constant_total_paths=800_000,
        # Variable: unique combination counts
        unique_combination_counts=[
            100_000,
            200_000,
            400_000,
            600_000,
            800_000,
        ],
        soak_time_minutes=2,
        dump_attribute_assignments=True,
        test_address_families=["ipv6"],
        # Custom setup tasks (no openR)
        setup_tasks=setup_tasks,
        host_os_type_map={device_name: taac_types.DeviceOsType.ARISTA_FBOSS},
        direct_ixia_connections=_two_port_direct_ixia_connections(physical_inventory),
        # Constant acceptance community (required by device BGP policy)
        constant_acceptance_communities=["65529:39744"],
        max_communities_per_route_from_pool=5,
        random_seed=42,
        # Device-level BGP peer group names
        peergroup_ebgp_v6=PEERGROUP_EBGP_V6,
        peergroup_ebgp_v4=PEERGROUP_EBGP_V4,
        peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
        peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
        log_collection_timeout=600,
    )


def create_bgp_ebb_queue_memory_monitor_test_config(
    physical_inventory: PhysicalInventory,
    enable_update_group: bool = False,
    name_override: str | None = None,
) -> taac_types.TestConfig:
    """Queue-memory-monitor conveyor test config for bag012.ash6.

    Extracted verbatim from the legacy
    ``bag012_ash6_test_config.create_bag012_ash6_queue_memory_monitor_test_config``
    factory. Monitors BGP++ fiber queue statistics and memory usage under
    route churn (140 EBGP peers flapping 15s up / 15s down; 63 IBGP peers).
    """
    assert physical_inventory.ixia_ports, (
        "factory requires IXIA port map on physical_inventory"
    )
    assert physical_inventory.bgpcpp_configerator_path, (
        "factory requires bgpcpp_configerator_path on physical_inventory"
    )
    assert physical_inventory.dut_bgp_as is not None, (
        "factory requires dut_bgp_as on physical_inventory"
    )
    assert physical_inventory.router_id, (
        "factory requires router_id on physical_inventory"
    )

    device_name = physical_inventory.device_name
    ixia_interface_mimic_ebgp = physical_inventory.ixia_ports[0][0]
    ixia_interface_mimic_ibgp = physical_inventory.ixia_ports[1][0]

    name = name_override or _derive_test_config_name(
        physical_inventory, "QUEUE_MEMORY_MONITOR", enable_update_group
    )

    setup_tasks = get_update_packing_setup_tasks(
        device_name=device_name,
        bgp_asn=physical_inventory.dut_bgp_as,
        ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
        ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
        ebgp_peer_count=EBGP_PEER_COUNT_V6,
        ibgp_peer_count=IBGP_PEER_SCALE_PER_PLANE,
        ebgp_remote_as=EBGP_REMOTE_AS,
        ibgp_remote_as=IBGP_REMOTE_AS,
        ixia_ebgp_ic_parent_network_v6=IXIA_EBGP_IC_PARENT_NETWORK_V6,
        ixia_ibgp_ic_parent_network_v6=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
        router_id=physical_inventory.router_id,
        bgpcpp_configerator_path=physical_inventory.bgpcpp_configerator_path,
        profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
        enable_update_group=enable_update_group,
    )

    # CPU stress is deployed directly by the custom step (_deploy_cpu_stress)
    # when monitor_cpu_stress=True -- no need for setup_tasks deployment.

    return test_config_bgp_queue_memory_monitoring_with_route_scale(
        test_config_name=name,
        device_name=device_name,
        # IBGP configuration
        ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
        ibgp_local_as=IBGP_REMOTE_AS,
        ixia_ibgp_ic_parent_network_v6=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
        ixia_ibgp_ic_parent_network_v4=IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
        # EBGP configuration
        ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
        ebgp_remote_as=EBGP_REMOTE_AS,
        ixia_ebgp_ic_parent_network_v6=IXIA_EBGP_IC_PARENT_NETWORK_V6,
        ixia_ebgp_ic_parent_network_v4=IXIA_EBGP_IC_PARENT_NETWORK_V4,
        # Test parameters
        ibgp_peer_count=IBGP_PEER_SCALE_PER_PLANE,
        ebgp_peer_count=EBGP_PEER_COUNT_V6,
        prefixes_per_ebgp_peer=10000,
        ip_version="ipv6",
        # Route acceptance communities
        ebgp_route_acceptance_communities=["65529:39744"],
        # Monitoring parameters
        monitoring_duration_minutes=60,
        monitoring_interval_seconds=120,
        # Route flapping parameters
        flap_uptime_seconds=15,
        flap_downtime_seconds=15,
        # Conveyor-specific configuration
        setup_tasks=setup_tasks,
        monitor_cpu_stress=True,
        host_os_type_map={device_name: taac_types.DeviceOsType.ARISTA_FBOSS},
        direct_ixia_connections=_two_port_direct_ixia_connections(physical_inventory),
        log_collection_timeout=600,
    )


def create_bgp_ebb_characteristic_performance_scaling_test_config(
    physical_inventory: PhysicalInventory,
    enable_update_group: bool = False,
) -> taac_types.TestConfig:
    """Performance-scaling egress IBGP peer-sweep test config (physical-inventory-driven).

    Extracted verbatim from the legacy
    ``bag012_ash6_test_config.create_bag012_ash6_performance_scaling_test_config``
    factory. Per Stage n in ``egress_peer_counts``, the device is configured
    with n v6 + n v4 IBGP peers via in-shell ``bgpcpp_config`` rewrite, then
    50K v6 + 50K v4 EBGP prefixes are advertised and initial convergence is
    measured. A final aggregator Stage produces one consolidated everpaste
    plot.

    The internal ``TestConfig.name`` is derived from ``physical_inventory.device_name`` as
    ``{DEVICE}_BGP_PERFORMANCE_SCALING_CONVEYOR_TEST`` (+ ``_UPDATE_GROUP``); for
    bag012 this reproduces the grandfathered name byte-for-byte, so its golden
    manifest hash is unchanged.
    """
    assert physical_inventory.ixia_ports, (
        "factory requires IXIA port map on physical_inventory"
    )
    assert physical_inventory.bgpcpp_configerator_path, (
        "factory requires bgpcpp_configerator_path on physical_inventory"
    )
    assert physical_inventory.dut_bgp_as is not None, (
        "factory requires dut_bgp_as on physical_inventory"
    )
    # router_id is optional: bag012 pins one explicitly; bag010/bag011/bag013
    # rely on the device-default router-id, which the setup helpers preserve
    # when router_id is None.

    device_name = physical_inventory.device_name
    ixia_interface_mimic_ebgp = physical_inventory.ixia_ports[0][0]
    ixia_interface_mimic_ibgp = physical_inventory.ixia_ports[1][0]

    # Derived from the physical_inventory device name. SC1 = the first "scale &
    # characteristics" test (egress peer-scale). The legacy
    # `_BGP_PERFORMANCE_SCALING_CONVEYOR_TEST` suffix was dropped: CONVEYOR
    # overclaimed (this is an ad-hoc test, not conveyor-scheduled).
    name = f"{physical_inventory.device_name.upper().replace('.', '_')}_SC1_EGRESS_PEER_SCALE_TEST"
    if enable_update_group:
        name += "_UPDATE_GROUP"

    setup_tasks = get_update_packing_setup_tasks(
        device_name=device_name,
        bgp_asn=physical_inventory.dut_bgp_as,
        ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
        ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
        ebgp_peer_count=1,
        ibgp_peer_count=_PERFORMANCE_SCALING_EGRESS_PEER_COUNTS[0],
        ebgp_remote_as=EBGP_REMOTE_AS,
        ibgp_remote_as=IBGP_REMOTE_AS,
        ixia_ebgp_ic_parent_network_v6=IXIA_EBGP_IC_PARENT_NETWORK_V6,
        ixia_ibgp_ic_parent_network_v6=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
        # v4 enables dual-stack IBGP/EBGP at startup so the initial
        # /mnt/flash/bgpcpp_config matches the v6+v4 layout that each
        # per-iteration factory call produces.
        ixia_ebgp_ic_parent_network_v4=IXIA_EBGP_IC_PARENT_NETWORK_V4,
        ixia_ibgp_ic_parent_network_v4=IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
        router_id=physical_inventory.router_id,
        bgpcpp_configerator_path=physical_inventory.bgpcpp_configerator_path,
        profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
        enable_update_group=enable_update_group,
        # Align v4 peer local addresses to the device's v4 secondary-interface-IP
        # offset (IXIA_IPV4_START_OFFSET=10). Without this the v4 peers default to
        # offset 16 while the interface IPs sit at 10, so the eBGP v4 peer and the
        # tail iBGP v4 peers have no local source IP and stay IDLE. (v6 already
        # aligns: both interface IPs and peers use offset 16.)
        v4_peer_start_offset=IXIA_IPV4_START_OFFSET,
    )
    # The per-iteration rescale rewrites only the bgpcpp peer list, never the
    # interface secondary IPs. get_update_packing_setup_tasks lays the iBGP
    # interface's source IPs for just the first sweep stage
    # (_PERFORMANCE_SCALING_EGRESS_PEER_COUNTS[0]), so every peer beyond that
    # stage has no local source address and stays IDLE (bag010 came up
    # established=202 at every stage, IDLE=total-202; P2415335739). Re-lay the
    # iBGP interface once at the full sweep max (clear_existing supersedes the
    # helper's smaller set); each stage then sources from the first n of these.
    # eBGP is constant at 1 peer/AFI, so its interface is already covered.
    setup_tasks.append(
        create_interface_ip_configuration_task(
            interface=ixia_interface_mimic_ibgp,
            peer_count=max(_PERFORMANCE_SCALING_EGRESS_PEER_COUNTS),
            ipv4_base_network=IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
            ipv6_base_network=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
            address_families=["ipv6", "ipv4"],
            clear_existing=True,
            ipv4_start_offset=IXIA_IPV4_START_OFFSET,
            ipv6_start_offset=IXIA_IPV6_START_OFFSET,
            hostname=device_name,
            ixia_needed=True,
        )
    )
    # Enable the interface-state nexthop-resolution gflag in run_bgpcpp.sh so
    # directly-connected egress nexthops resolve via NetlinkWrapper under
    # WITHOUT_OPEN_R (see _NEXTHOP_IFACE_STATE_FLAG above). use_managed_shell
    # routes the standardized startup task over the managed device driver the
    # perf-scaling sweep runs under (it passes no SSH credentials); the
    # per-stage Bgp restart then picks up the new flag.
    setup_tasks.append(
        create_configure_bgpcpp_startup_task(
            hostname=device_name,
            flags={_NEXTHOP_IFACE_STATE_FLAG: "true"},
            use_managed_shell=True,
            set_outer_hostname=True,
            ixia_needed=True,
        )
    )
    # This test injects arbitrary scale prefixes that are not in the device's
    # baked-in route registry, so the Centralized Route Filter (CRF) denies all
    # but the ~registered handful ("Denied by Route Filter Policy"). Clear the
    # route filter so no inbound prefix is blocked; the clear deletes the
    # persisted rp_state_file, so the daemon stays CRF-free across the per-stage
    # Bgp restarts.
    setup_tasks.append(
        create_bgp_clear_route_filter_task(
            hostname=device_name,
            set_outer_hostname=True,
            ixia_needed=True,
        )
    )
    factory = build_per_iteration_factory_v4_capable(
        device_name=device_name,
        router_id=physical_inventory.router_id,
        ebgp_remote_as=EBGP_REMOTE_AS,
        ibgp_remote_as=IBGP_REMOTE_AS,
        ebgp_v6_base=IXIA_EBGP_IC_PARENT_NETWORK_V6,
        ebgp_v4_base=IXIA_EBGP_IC_PARENT_NETWORK_V4,
        ibgp_v6_base=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
        ibgp_v4_base=IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
        peergroup_ebgp_v6=PEERGROUP_EBGP_V6,
        peergroup_ebgp_v4=PEERGROUP_EBGP_V4,
        peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
        peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
        ebgp_peer_count=1,
        # Same v4 offset alignment for the per-stage peer rewrites — the
        # load-bearing path at convergence time.
        v4_peer_start_offset=IXIA_IPV4_START_OFFSET,
    )
    return create_bgp_ebb_scaling_performance_test_config(
        physical_inventory,
        name=name,
        host_driver_args=None,
        oss_mock_device_data=None,
        host_os_type_map={device_name: taac_types.DeviceOsType.ARISTA_FBOSS},
        direct_ixia_connections=_two_port_direct_ixia_connections(physical_inventory),
        egress_peer_counts=_PERFORMANCE_SCALING_EGRESS_PEER_COUNTS,
        prefix_count=_PERFORMANCE_SCALING_PREFIX_COUNT,
        ebgp_peer_count=1,
        ebgp_remote_as=EBGP_REMOTE_AS,
        ibgp_remote_as=IBGP_REMOTE_AS,
        ixia_ebgp_ic_parent_network_v6=IXIA_EBGP_IC_PARENT_NETWORK_V6,
        ixia_ebgp_ic_parent_network_v4=IXIA_EBGP_IC_PARENT_NETWORK_V4,
        ixia_ibgp_ic_parent_network_v6=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
        ixia_ibgp_ic_parent_network_v4=IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
        log_collection_timeout=600,
        setup_tasks=setup_tasks,
        per_iteration_setup_steps_factory=factory,
    )


def create_bgp_ebb_characteristic_bounded_ecmp_sets_test_config(
    physical_inventory: PhysicalInventory,
    name_override: str | None = None,
) -> taac_types.TestConfig:
    """Bounded-ECMP-sets conveyor test config for bag012.ash6.

    Extracted verbatim from the legacy
    ``bag012_ash6_test_config.create_bag012_ash6_bounded_ecmp_sets_test_config``
    factory. Verifies BGP++ ECMP-set bounding at production peer scale (128
    EBGP + 128 IBGP per AFI) with update_group enabled. The DUT setup uses
    the standard ``get_update_packing_setup_tasks`` helper (same path as the
    other bag012 characteristic tests) so the configerator ``bgpcpp_config``
    is deployed cleanly instead of patching the image's leftover config in
    place. Bounded ECMP brings up IPv4 sessions too, so
    ``v4_peer_start_offset=IXIA_IPV4_START_OFFSET`` aligns the generated v4
    peers with the device's v4 secondary IPs.
    """
    assert physical_inventory.ixia_ports, (
        "factory requires IXIA port map on physical_inventory"
    )
    assert physical_inventory.bgpcpp_configerator_path, (
        "factory requires bgpcpp_configerator_path on physical_inventory"
    )
    assert physical_inventory.dut_bgp_as is not None, (
        "factory requires dut_bgp_as on physical_inventory"
    )
    assert physical_inventory.router_id, (
        "factory requires router_id on physical_inventory"
    )

    device_name = physical_inventory.device_name
    ixia_interface_mimic_ebgp = physical_inventory.ixia_ports[0][0]
    ixia_interface_mimic_ibgp = physical_inventory.ixia_ports[1][0]

    setup_tasks = get_update_packing_setup_tasks(
        device_name=device_name,
        bgp_asn=physical_inventory.dut_bgp_as,
        ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
        ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
        ebgp_peer_count=_BAG012_BOUNDED_ECMP_PEER_COUNT,
        ibgp_peer_count=_BAG012_BOUNDED_ECMP_PEER_COUNT,
        ebgp_remote_as=EBGP_REMOTE_AS,
        ibgp_remote_as=IBGP_REMOTE_AS,
        ixia_ebgp_ic_parent_network_v6=IXIA_EBGP_IC_PARENT_NETWORK_V6,
        ixia_ibgp_ic_parent_network_v6=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
        # Dual-stack: bounded ECMP runs v4 + v6 peers on both interfaces.
        ixia_ebgp_ic_parent_network_v4=IXIA_EBGP_IC_PARENT_NETWORK_V4,
        ixia_ibgp_ic_parent_network_v4=IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
        router_id=physical_inventory.router_id,
        bgpcpp_configerator_path=physical_inventory.bgpcpp_configerator_path,
        profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
        # Align v4 peers with the device v4 secondary IPs + IXIA .10 layout.
        v4_peer_start_offset=IXIA_IPV4_START_OFFSET,
        # DUT runs with BGP++ update_group enabled.
        enable_update_group=True,
    )

    return create_bgp_ebb_scaling_bounded_ecmp_sets_test_config(
        physical_inventory,
        name=name_override
        or _derive_test_config_name(
            physical_inventory, "BOUNDED_ECMP_SETS", enable_update_group=True
        ),
        ebgp_peer_count_v6=_BAG012_BOUNDED_ECMP_PEER_COUNT,
        ibgp_peer_count_v6=_BAG012_BOUNDED_ECMP_PEER_COUNT,
        ebgp_peer_count_v4=_BAG012_BOUNDED_ECMP_PEER_COUNT,
        ibgp_peer_count_v4=_BAG012_BOUNDED_ECMP_PEER_COUNT,
        ebgp_remote_as=EBGP_REMOTE_AS,
        ibgp_remote_as=IBGP_REMOTE_AS,
        ixia_ebgp_ic_parent_network_v6=IXIA_EBGP_IC_PARENT_NETWORK_V6,
        ixia_ebgp_ic_parent_network_v4=IXIA_EBGP_IC_PARENT_NETWORK_V4,
        ixia_ibgp_ic_parent_network_v6=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
        ixia_ibgp_ic_parent_network_v4=IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
        prefix_count=_BAG012_BOUNDED_ECMP_PREFIX_COUNT,
        direct_ixia_connections=_two_port_direct_ixia_connections(physical_inventory),
        host_os_type_map={device_name: taac_types.DeviceOsType.ARISTA_FBOSS},
        # Standard device setup (configerator deploy + control plane + validator
        # + interface IPs + update_group), shared with the other bag012 conveyor
        # nodes. Passing setup_tasks skips case9's in-shell fallback.
        setup_tasks=setup_tasks,
        log_collection_timeout=600,
    )


# =============================================================================
# Absorbed helpers (Wave 5D.2) -- historically lived at
# ``testconfigs/routing/ebb/test_config_performance_scaling_case8.py``,
# ``testconfigs/routing/ebb/test_config_update_packing.py``,
# ``testconfigs/routing/ebb/test_config_to_verify_computational_load_of_bgp_plus_plus.py``
# and
# ``testconfigs/routing/ebb/test_config_to_verify_constant_attribute_storage.py``.
# Bodies copied verbatim so serialized TestConfig output is byte-wise identical.
# The new ``create_bgp_ebb_characteristic_*`` factories below call these
# helpers by name.
# =============================================================================


def test_config_for_bgp_plus_plus_on_ebb_arista_separable_policy(
    test_config_name: str,
    device_name: str,
    ixia_interface_mimic_ebgp: str,
    ebgp_peer_count_v6: int,
    ebgp_peer_count_v4: int,
    ebgp_remote_as: int,
    ixia_ebgp_ic_parent_network_v6: str,
    ixia_ebgp_ic_parent_network_v4: str,
    prefix_count: int,
    direct_ixia_connections: list,
    log_collection_timeout=None,
    oss_mock_device_data=None,
    host_os_type_map=None,
    host_driver_args=None,
    # Dynamic peer configuration (optional)
    ssh_user: str | None = None,
    ssh_password: str | None = None,
    peergroup_ebgp_v6: str = "EB-FA-V6",
    peergroup_ebgp_v4: str = "EB-FA-V4",
):
    """Build the case-8 (separable policy) BGP++ TestConfig.

    Byte-identical to the legacy
    ``testconfigs/routing/ebb/test_config_performance_scaling_case8``
    ``test_config_for_bgp_plus_plus_on_ebb_arista_separable_policy``.
    """
    # Build setup_tasks based on whether dynamic peer config is provided
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
                        "peer_count": ebgp_peer_count_v6,
                        "start_offset": 16,
                    },
                    {
                        "peer_group_name": peergroup_ebgp_v4,
                        "remote_as": ebgp_remote_as,
                        "base_network": ixia_ebgp_ic_parent_network_v4,
                        "is_v6": False,
                        "peer_count": ebgp_peer_count_v4,
                        "start_offset": 16,
                    },
                ],
            ),
        ]
    else:
        setup_tasks = []

    return TestConfig(
        name=test_config_name,
        skip_ixia_protocol_verification=True,
        log_collection_timeout=log_collection_timeout,
        basset_pool="dne.test",
        endpoints=[
            Endpoint(
                name=device_name,
                dut=True,
                ixia_ports=[ixia_interface_mimic_ebgp],
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
        teardown_tasks=[],
        basic_port_configs=create_ebb_performance_scale_basic_port_configs(
            device_name=device_name,
            ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
            ixia_interface_mimic_ibgp="",
            ebgp_peer_count_v6=ebgp_peer_count_v6,
            ebgp_peer_count_v4=ebgp_peer_count_v4,
            ibgp_peer_count_v6=0,
            ibgp_peer_count_v4=0,
            ebgp_remote_as=ebgp_remote_as,
            ibgp_remote_as=0,
            ixia_ebgp_ic_parent_network_v6=ixia_ebgp_ic_parent_network_v6,
            ixia_ebgp_ic_parent_network_v4=ixia_ebgp_ic_parent_network_v4,
            ixia_ibgp_ic_parent_network_v6="",
            ixia_ibgp_ic_parent_network_v4="",
            same_community=True,
        ),
        playbooks=[
            build_case8_playbook(
                name="bgp_plus_plus_arista_separable_policy_eb_fa_in_test",
                description="Test BGP++ performance with separable policy",
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
                postchecks=[
                    create_bgp_session_establish_check(),
                ],
                setup_steps=create_sc_8_setup_steps(
                    device_name=device_name,
                    configerator_path="taac/arista_performance_scaling_test_bgpcpp_configs/bgpcpp_config_test_case8_eb_fa_in_no_prefix",
                ),
                stages=[
                    create_steps_stage(
                        steps=create_sc_8_steps(
                            device_name=device_name,
                            prefix_count=10000,
                            plot_policy_stats=False,
                        )
                        + create_sc_8_steps(
                            device_name=device_name,
                            prefix_count=20000,
                            plot_policy_stats=False,
                        )
                        + create_sc_8_steps(
                            device_name=device_name,
                            prefix_count=30000,
                            plot_policy_stats=False,
                        )
                        + create_sc_8_steps(
                            device_name=device_name,
                            prefix_count=40000,
                            plot_policy_stats=False,
                        )
                        + create_sc_8_steps(
                            device_name=device_name,
                            prefix_count=50000,
                            plot_policy_stats=True,
                        )
                    )
                ],
            ),
            build_case8_playbook(
                name="bgp_plus_plus_arista_default_policy_test",
                description="Test BGP++ performance with default policy",
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
                postchecks=[
                    create_bgp_session_establish_check(),
                ],
                setup_steps=create_sc_8_setup_steps(
                    device_name=device_name,
                    configerator_path="taac/arista_performance_scaling_test_bgpcpp_configs/bgpcpp_config_test_case8_accept_all",
                ),
                stages=[
                    create_steps_stage(
                        steps=create_sc_8_steps(
                            device_name=device_name,
                            prefix_count=10000,
                            policy_name="ACCEPT_ALL",
                            plot_policy_stats=False,
                        )
                        + create_sc_8_steps(
                            device_name=device_name,
                            prefix_count=20000,
                            policy_name="ACCEPT_ALL",
                            plot_policy_stats=False,
                        )
                        + create_sc_8_steps(
                            device_name=device_name,
                            prefix_count=30000,
                            policy_name="ACCEPT_ALL",
                            plot_policy_stats=False,
                        )
                        + create_sc_8_steps(
                            device_name=device_name,
                            prefix_count=40000,
                            policy_name="ACCEPT_ALL",
                            plot_policy_stats=False,
                        )
                        + create_sc_8_steps(
                            device_name=device_name,
                            prefix_count=50000,
                            policy_name="ACCEPT_ALL",
                            plot_policy_stats=True,
                        )
                    )
                ],
            ),
        ],
    )


def test_config_bgp_update_packing_validation(
    test_config_name: str,
    device_name: str,
    # IBGP configuration (ingress)
    ixia_interface_mimic_ibgp: str,
    ibgp_local_as: int,
    ixia_ibgp_ic_parent_network_v6: str,
    ixia_ibgp_ic_parent_network_v4: str,
    # EBGP configuration (egress - for capture)
    ixia_interface_mimic_ebgp: str,
    ebgp_remote_as: int,
    ixia_ebgp_ic_parent_network_v6: str,
    ixia_ebgp_ic_parent_network_v4: str,
    # Test parameters
    ibgp_peer_count: int = 10,
    prefixes_per_peer: int = 10000,
    ebgp_peer_count: int = 1,
    # Address family selection
    test_address_families: list[str] | None = None,
    # Attribute pool configuration
    as_path_pool_size: int = 10,
    community_pool_size: int = 20,
    as_path_length: int = 3,
    communities_per_route: int = 2,
    # Route acceptance communities (required for Edge Border acceptance policy)
    ibgp_route_acceptance_communities: list[str] | None = None,
    ebgp_route_acceptance_communities: list[str] | None = None,
    # Test control
    capture_duration_seconds: int = 600,
    min_packed_size: int = 4000,
    restart_bgp_for_complete_view: bool = True,
    direct_ixia_connections: list | None = None,
    endpoints: list[Endpoint] | None = None,
    basic_port_configs: list[BasicPortConfig] | None = None,
    log_collection_timeout: int | None = None,
    oss_mock_device_data=None,
    host_os_type_map=None,
    host_driver_args=None,
    setup_tasks: list | None = None,
    teardown_tasks: list | None = None,
    ixia_config_cache: IxiaConfigCache | None = None,
):
    """BGP++ UPDATE Message Packing Validation TestConfig.

    Byte-identical to the legacy
    ``testconfigs/routing/ebb/test_config_update_packing``
    ``test_config_bgp_update_packing_validation``.
    """
    # Set default address families if not specified
    if test_address_families is None:
        test_address_families = ["ipv4", "ipv6"]

    # Calculate initial peer counts based on address families
    num_afs = len(test_address_families)
    if num_afs == 2:
        initial_ibgp_peer_count = ibgp_peer_count // 2
        initial_ebgp_peer_count = ebgp_peer_count // 2
    elif "ipv4" in test_address_families:
        initial_ibgp_peer_count = ibgp_peer_count
        initial_ebgp_peer_count = ebgp_peer_count
    else:
        initial_ibgp_peer_count = ibgp_peer_count
        initial_ebgp_peer_count = ebgp_peer_count

    as_path_pool = generate_as_path_pool(
        count=as_path_pool_size,
        base_as=45000,
        as_path_length=as_path_length,
    )

    community_pool = generate_community_pool(
        count=community_pool_size,
        base_community=45100,
    )

    if ebgp_route_acceptance_communities:
        test_direction = "EBGP → IBGP"
    elif ibgp_route_acceptance_communities:
        test_direction = "IBGP → EBGP"
    else:
        raise ValueError(
            "Must specify either ibgp_route_acceptance_communities or "
            "ebgp_route_acceptance_communities to determine test direction"
        )

    ibgp_device_groups = []
    ibgp_advertises_routes = test_direction == "IBGP → EBGP"

    if "ipv6" in test_address_families:
        ibgp_v6_route_scales = None
        if ibgp_advertises_routes:
            ibgp_v6_route_scales = [
                RouteScaleSpec(
                    v6_route_scale=RouteScale(
                        prefix_name="PREFIX_POOL_IPV6_IBGP",
                        starting_prefixes="5001:db8:1000::",
                        prefix_step="0:0:1::",
                        prefix_length=64,
                        multiplier=1,
                        prefix_count=prefixes_per_peer,
                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                        bgp_communities=[],
                    ),
                    multiplier=1,
                    network_group_index=0,
                )
            ]

        ibgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV6_IBGP",
                device_group_index=len(ibgp_device_groups),
                multiplier=initial_ibgp_peer_count,
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
                    bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                    route_scales=ibgp_v6_route_scales,
                ),
            )
        )

    if "ipv4" in test_address_families:
        ibgp_v4_route_scales = None
        if ibgp_advertises_routes:
            ibgp_v4_route_scales = [
                RouteScaleSpec(
                    v4_route_scale=RouteScale(
                        prefix_name="PREFIX_POOL_IPV4_IBGP",
                        starting_prefixes="50.100.0.0",
                        prefix_step="0.0.1.0",
                        prefix_length=24,
                        multiplier=1,
                        prefix_count=prefixes_per_peer,
                        ip_address_family=ixia_types.IpAddressFamily.IPV4,
                        bgp_communities=[],
                    ),
                    multiplier=1,
                    network_group_index=0,
                )
            ]

        ibgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV4_IBGP",
                device_group_index=len(ibgp_device_groups),
                multiplier=initial_ibgp_peer_count,
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
                    bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                    route_scales=ibgp_v4_route_scales,
                ),
            )
        )

    ebgp_device_groups = []
    ebgp_advertises_routes = test_direction == "EBGP → IBGP"

    if "ipv6" in test_address_families:
        ebgp_v6_route_scales = None
        if ebgp_advertises_routes:
            ebgp_v6_route_scales = [
                RouteScaleSpec(
                    v6_route_scale=RouteScale(
                        prefix_name="PREFIX_POOL_IPV6_EBGP",
                        starting_prefixes="5001:db8:1000::",
                        prefix_step="0:0:1::",
                        prefix_length=64,
                        multiplier=1,
                        prefix_count=prefixes_per_peer,
                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                        bgp_communities=[],
                    ),
                    multiplier=1,
                    network_group_index=0,
                )
            ]

        ebgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV6_EBGP",
                device_group_index=len(ebgp_device_groups),
                multiplier=initial_ebgp_peer_count,
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
                    bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                    route_scales=ebgp_v6_route_scales,
                ),
            )
        )

    if "ipv4" in test_address_families:
        ebgp_v4_route_scales = None
        if ebgp_advertises_routes:
            ebgp_v4_route_scales = [
                RouteScaleSpec(
                    v4_route_scale=RouteScale(
                        prefix_name="PREFIX_POOL_IPV4_EBGP",
                        starting_prefixes="50.100.0.0",
                        prefix_step="0.0.1.0",
                        prefix_length=24,
                        multiplier=1,
                        prefix_count=prefixes_per_peer,
                        ip_address_family=ixia_types.IpAddressFamily.IPV4,
                        bgp_communities=[],
                    ),
                    multiplier=1,
                    network_group_index=0,
                )
            ]

        ebgp_device_groups.append(
            DeviceGroupConfig(
                device_group_name="DEVICE_GROUP_IPV4_EBGP",
                device_group_index=len(ebgp_device_groups),
                multiplier=initial_ebgp_peer_count,
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
                    bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                    route_scales=ebgp_v4_route_scales,
                ),
            )
        )

    return TestConfig(
        name=test_config_name,
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
                        ixia_interface_mimic_ibgp,
                        ixia_interface_mimic_ebgp,
                    ],
                    direct_ixia_connections=direct_ixia_connections
                    if direct_ixia_connections
                    else [],
                ),
            ]
        ),
        host_driver_args=host_driver_args,
        oss_mock_device_data=oss_mock_device_data,
        host_os_type_map=host_os_type_map,
        startup_checks=[],
        setup_tasks=setup_tasks if setup_tasks else [],
        teardown_tasks=teardown_tasks if teardown_tasks else [],
        basic_port_configs=(
            basic_port_configs
            if basic_port_configs is not None
            else [
                BasicPortConfig(
                    endpoint=f"{device_name}:{ixia_interface_mimic_ibgp}",
                    device_group_configs=ibgp_device_groups,
                ),
                BasicPortConfig(
                    endpoint=f"{device_name}:{ixia_interface_mimic_ebgp}",
                    device_group_configs=ebgp_device_groups,
                ),
            ]
        ),
        playbooks=[
            create_bgp_update_packing_validation_playbook(
                device_name=device_name,
                ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
                ibgp_peer_count=ibgp_peer_count,
                prefixes_per_peer=prefixes_per_peer,
                ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
                ebgp_peer_count=ebgp_peer_count,
                test_address_families=test_address_families,
                as_path_pool=as_path_pool,
                community_pool=community_pool,
                communities_per_route=communities_per_route,
                ibgp_route_acceptance_communities=ibgp_route_acceptance_communities,
                ebgp_route_acceptance_communities=ebgp_route_acceptance_communities,
                capture_duration_seconds=capture_duration_seconds,
                min_packed_size=min_packed_size,
                restart_bgp_for_complete_view=restart_bgp_for_complete_view,
            ),
        ],
        ixia_config_cache=ixia_config_cache,
    )


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
    ibgp_peer_counts: list[int],
    prefix_counts: list[int],
):
    """BGP++ computational-load verification TestConfig.

    Byte-identical to the legacy
    ``testconfigs/routing/ebb/test_config_to_verify_computational_load_of_bgp_plus_plus``
    ``test_config_to_verify_computational_load_of_bgp_plus_plus``.
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
    ebgp_peer_counts: list[int],
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
    prefix_counts: list[int],
    ibgp_peer_count: int = 1000,
):
    """BGP++ constant-attribute-storage verification TestConfig.

    Byte-identical to the legacy
    ``testconfigs/routing/ebb/test_config_to_verify_constant_attribute_storage``
    ``test_config_to_verify_constant_attribute_storage``.
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


# =============================================================================
# Wave 5D.2 -- new physical-inventory-driven factories for the routing catalog.
# =============================================================================


def create_bgp_ebb_characteristic_separable_policy_test_config(
    physical_inventory: PhysicalInventory,
    *,
    name: str,
    ebgp_remote_as: int = 65334,
    ixia_ebgp_ic_parent_network_v6: str = "2401:db00:e50d:11:8",
    ixia_ebgp_ic_parent_network_v4: str = "10.163.28",
    ebgp_peer_count_v6: int = 1,
    ebgp_peer_count_v4: int = 1,
    prefix_count: int = 50000,
    ssh_user: str | None = None,
    log_collection_timeout: int | None = None,
    direct_ixia_connections: list[DirectIxiaConnection] | None = None,
) -> taac_types.TestConfig:
    """Case-8 separable-policy TestConfig (legacy case8 factory).

    Byte-identical to the legacy
    ``eb02_arista_bgp_plus_plus_separable_policy_1_peer_test_config.py``
    wrapper when invoked with ``EB02_LAB_ASH6`` + ``ssh_user="admin"``.
    """
    device_name = physical_inventory.device_name
    ebgp_iface, ebgp_port = physical_inventory.ixia_ports[0]

    host_driver_args = physical_inventory.host_driver_args
    oss_mock_device_data = physical_inventory.oss_mock_device_data
    host_os_type_map = {device_name: taac_types.DeviceOsType.ARISTA_FBOSS}
    resolved_direct_ixia_connections = (
        direct_ixia_connections
        if direct_ixia_connections is not None
        else [
            DirectIxiaConnection(
                interface=ebgp_iface,
                ixia_chassis_ip=physical_inventory.ixia_chassis_ip,
                ixia_port=ebgp_port,
            ),
        ]
    )

    ssh_password: str | None = None
    if ssh_user is not None:
        lab_password_env = (
            physical_inventory.lab_device_password_env_var
            or "TAAC_EBB_LAB_DEVICE_PASSWORD"
        )
        lab_admin_password_default = physical_inventory.extras.get(
            "lab_admin_password_default",
            "dnepit",  # pragma: allowlist secret
        )
        ssh_password = os.environ.get(lab_password_env, lab_admin_password_default)

    return test_config_for_bgp_plus_plus_on_ebb_arista_separable_policy(
        test_config_name=name,
        device_name=device_name,
        ixia_interface_mimic_ebgp=ebgp_iface,
        ebgp_remote_as=ebgp_remote_as,
        ebgp_peer_count_v6=ebgp_peer_count_v6,
        ebgp_peer_count_v4=ebgp_peer_count_v4,
        ixia_ebgp_ic_parent_network_v6=ixia_ebgp_ic_parent_network_v6,
        ixia_ebgp_ic_parent_network_v4=ixia_ebgp_ic_parent_network_v4,
        direct_ixia_connections=resolved_direct_ixia_connections,
        prefix_count=prefix_count,
        host_driver_args=host_driver_args,
        oss_mock_device_data=oss_mock_device_data,
        host_os_type_map=host_os_type_map,
        ssh_user=ssh_user,
        ssh_password=ssh_password,
        log_collection_timeout=log_collection_timeout,
    )


def create_bgp_ebb_characteristic_update_packing_test_config(
    physical_inventory: PhysicalInventory,
    *,
    name: str,
    ebgp_remote_as: int = 65334,
    ixia_ebgp_ic_parent_network_v6: str = "2401:db00:e50d:11:8",
    ixia_ebgp_ic_parent_network_v4: str = "10.163.28",
    ibgp_local_as: int = 64981,
    ixia_ibgp_ic_parent_network_v6: str = "2401:db00:e50d:11:9",
    ixia_ibgp_ic_parent_network_v4: str = "10.164.28",
    ebgp_peer_count: int = 10,
    prefixes_per_peer: int = 10000,
    ibgp_peer_count: int = 1,
    test_address_families: list[str] | None = None,
    as_path_pool_size: int = 10,
    community_pool_size: int = 20,
    as_path_length: int = 3,
    communities_per_route: int = 2,
    ebgp_route_acceptance_communities: list[str] | None = None,
    capture_duration_seconds: int = 300,
    min_packed_size: int = 3500,
    restart_bgp_for_complete_view: bool = True,
    log_collection_timeout: int | None = None,
    direct_ixia_connections: list[DirectIxiaConnection] | None = None,
) -> taac_types.TestConfig:
    """BGP++ UPDATE-packing-validation TestConfig (legacy update_packing factory).

    Byte-identical to the legacy
    ``eb02_arista_bgp_update_packing_validation_test_config.py``
    wrapper when invoked with ``EB02_LAB_ASH6`` and its wrapper defaults.
    """
    if test_address_families is None:
        test_address_families = ["ipv6"]
    if ebgp_route_acceptance_communities is None:
        ebgp_route_acceptance_communities = ["65529:39744"]

    device_name = physical_inventory.device_name
    ebgp_iface, ebgp_port = physical_inventory.ixia_ports[0]
    ibgp_iface, ibgp_port = physical_inventory.ixia_ports[1]

    host_driver_args = physical_inventory.host_driver_args
    oss_mock_device_data = physical_inventory.oss_mock_device_data
    host_os_type_map = {device_name: taac_types.DeviceOsType.ARISTA_FBOSS}
    resolved_direct_ixia_connections = (
        direct_ixia_connections
        if direct_ixia_connections is not None
        else [
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
    )

    return test_config_bgp_update_packing_validation(
        test_config_name=name,
        device_name=device_name,
        ixia_interface_mimic_ebgp=ebgp_iface,
        ebgp_remote_as=ebgp_remote_as,
        ixia_ebgp_ic_parent_network_v6=ixia_ebgp_ic_parent_network_v6,
        ixia_ebgp_ic_parent_network_v4=ixia_ebgp_ic_parent_network_v4,
        ixia_interface_mimic_ibgp=ibgp_iface,
        ibgp_local_as=ibgp_local_as,
        ixia_ibgp_ic_parent_network_v6=ixia_ibgp_ic_parent_network_v6,
        ixia_ibgp_ic_parent_network_v4=ixia_ibgp_ic_parent_network_v4,
        ebgp_peer_count=ebgp_peer_count,
        prefixes_per_peer=prefixes_per_peer,
        ibgp_peer_count=ibgp_peer_count,
        test_address_families=test_address_families,
        as_path_pool_size=as_path_pool_size,
        community_pool_size=community_pool_size,
        as_path_length=as_path_length,
        communities_per_route=communities_per_route,
        ebgp_route_acceptance_communities=ebgp_route_acceptance_communities,
        capture_duration_seconds=capture_duration_seconds,
        min_packed_size=min_packed_size,
        restart_bgp_for_complete_view=restart_bgp_for_complete_view,
        host_driver_args=host_driver_args,
        oss_mock_device_data=oss_mock_device_data,
        host_os_type_map=host_os_type_map,
        direct_ixia_connections=resolved_direct_ixia_connections,
        log_collection_timeout=log_collection_timeout,
    )


def create_bgp_ebb_characteristic_verify_computational_load_test_config(
    physical_inventory: PhysicalInventory,
    *,
    name: str,
    peergroup_ibgp_v6: str = "PEERGROUP_FAUU_FADU_V6_NEW",
    peergroup_ebgp_v6: str = "PEERGROUP_FAUU_EB_V6_NEW",
    peergroup_ibgp_v4: str = "PEERGROUP_FAUU_FADU_V4_NEW",
    peergroup_ebgp_v4: str = "PEERGROUP_FAUU_EB_V4_NEW",
    ebgp_remote_as: int = 64734,
    ebgp_peer_scale: int = 1,
    unqiue_prefix_limit: int = 75000,
    total_path_limit: int = 30000000,
    ixia_ebgp_ic_parent_network_v6: str = "2401:db00:e50d:11:8",
    ixia_ibgp_ic_parent_network_v6: str = "2401:db00:e50d:11:9",
    ixia_ebgp_ic_parent_network_v4: str = "10.163.28",
    ixia_ibgp_ic_parent_network_v4: str = "10.164.28",
    ixia_ebgp_communities: list[str] | None = None,
    ixia_ibgp_communities: list[str] | None = None,
    ebgp_ingress_policy_name: str = "PROPAGATE_FAUU_EB_IN",
    ebgp_egress_policy_name: str = "PROPAGATE_FAUU_EB_OUT",
    ibgp_ingress_policy_name: str = "PROPAGATE_FAUU_FADU_IN",
    ibgp_egress_policy_name: str = "PROPAGATE_FAUU_FADU_OUT",
    ibgp_peer_counts: list[int] | None = None,
    prefix_counts: list[int] | None = None,
) -> taac_types.TestConfig:
    """BGP++ computational-load-verification TestConfig.

    Byte-identical to the legacy
    ``bgp_plus_plus_verify_computational_load_test_config.py`` wrapper when
    invoked with ``FA001_UU001_QZD1`` and its wrapper defaults. DUT identity
    + IXIA interface map come from ``physical_inventory`` (interfaces come from
    ``physical_inventory.extras['dut_iface_*']`` since this FA physical_inventory does not declare
    ``ixia_ports``). iBGP remote AS is derived from ``physical_inventory.dut_bgp_as``
    (iBGP is same-AS on FA-UU).
    """
    if ixia_ebgp_communities is None:
        ixia_ebgp_communities = ["65526:35724"]
    if ixia_ibgp_communities is None:
        ixia_ibgp_communities = ["65441:133"]
    if ibgp_peer_counts is None:
        ibgp_peer_counts = [200]
    if prefix_counts is None:
        prefix_counts = [2000]

    assert physical_inventory.dut_bgp_as is not None, (
        "factory requires dut_bgp_as on physical_inventory"
    )
    device_name = physical_inventory.device_name
    ixia_interface_mimic_ebgp = physical_inventory.extras["dut_iface_ebgp"]
    ixia_interface_mimic_ibgp = physical_inventory.extras["dut_iface_ibgp"]

    return test_config_to_verify_computational_load_of_bgp_plus_plus(
        test_config_name=name,
        device_name=device_name,
        peergroup_ibgp_v6=peergroup_ibgp_v6,
        peergroup_ebgp_v6=peergroup_ebgp_v6,
        peergroup_ibgp_v4=peergroup_ibgp_v4,
        peergroup_ebgp_v4=peergroup_ebgp_v4,
        ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
        ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
        ibgp_remote_as=physical_inventory.dut_bgp_as,
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
    )


def create_bgp_ebb_characteristic_verify_constant_attribute_storage_test_config(
    physical_inventory: PhysicalInventory,
    *,
    name: str,
    peergroup_ibgp_v6: str = "PEERGROUP_FAUU_FADU_V6_NEW",
    peergroup_ebgp_v6: str = "PEERGROUP_FAUU_EB_V6_NEW",
    peergroup_ibgp_v4: str = "PEERGROUP_FAUU_FADU_V4_NEW",
    peergroup_ebgp_v4: str = "PEERGROUP_FAUU_EB_V4_NEW",
    ebgp_remote_as: int = 64734,
    ebgp_peer_counts: list[int] | None = None,
    unqiue_prefix_limit: int = 75000,
    total_path_limit: int = 30000000,
    ixia_ebgp_ic_parent_network_v6: str = "2401:db00:e50d:11:8",
    ixia_ibgp_ic_parent_network_v6: str = "2401:db00:e50d:11:9",
    ixia_ebgp_ic_parent_network_v4: str = "10.163.28",
    ixia_ibgp_ic_parent_network_v4: str = "10.164.28",
    ixia_ebgp_communities: list[str] | None = None,
    ixia_ibgp_communities: list[str] | None = None,
    ebgp_ingress_policy_name: str = "PROPAGATE_FAUU_EB_IN",
    ebgp_egress_policy_name: str = "PROPAGATE_FAUU_EB_OUT",
    ibgp_ingress_policy_name: str = "PROPAGATE_FAUU_FADU_IN",
    ibgp_egress_policy_name: str = "PROPAGATE_FAUU_FADU_OUT",
    prefix_counts: list[int] | None = None,
    ibgp_peer_count: int = 1000,
) -> taac_types.TestConfig:
    """BGP++ constant-attribute-storage-verification TestConfig.

    Byte-identical to the legacy
    ``bgp_plus_plus_verify_constant_attribute_storage_test_config.py``
    wrapper when invoked with ``FA001_UU001_QZD1`` and its wrapper defaults.
    """
    if ebgp_peer_counts is None:
        ebgp_peer_counts = [1, 4, 16, 64, 128]
    if ixia_ebgp_communities is None:
        ixia_ebgp_communities = ["65526:35724"]
    if ixia_ibgp_communities is None:
        ixia_ibgp_communities = ["65441:133"]
    if prefix_counts is None:
        prefix_counts = [10000]

    assert physical_inventory.dut_bgp_as is not None, (
        "factory requires dut_bgp_as on physical_inventory"
    )
    device_name = physical_inventory.device_name
    ixia_interface_mimic_ebgp = physical_inventory.extras["dut_iface_ebgp"]
    ixia_interface_mimic_ibgp = physical_inventory.extras["dut_iface_ibgp"]

    return test_config_to_verify_constant_attribute_storage(
        test_config_name=name,
        device_name=device_name,
        peergroup_ibgp_v6=peergroup_ibgp_v6,
        peergroup_ebgp_v6=peergroup_ebgp_v6,
        peergroup_ibgp_v4=peergroup_ibgp_v4,
        peergroup_ebgp_v4=peergroup_ebgp_v4,
        ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
        ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
        ibgp_remote_as=physical_inventory.dut_bgp_as,
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
        prefix_counts=prefix_counts,
        ibgp_peer_count=ibgp_peer_count,
    )
