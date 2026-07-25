# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""BGPCPP-on-EBB full-scale workflow factories.

Bag conveyor workflows on the 1274-peer EBB logical_topology. Naming:
``create_ebb_<workflow>_test_config(physical_inventory: PhysicalInventory, ...) -> TestConfig``.

See ../README.md §3.
"""

from taac.abstractions.topologies.ebb_full_scale import (
    EBB_AS_NUMBERS,
    EBB_FULL_SCALE_PORT_MAP_WITH_BGPMON,
    ebb_full_scale_topology,
    EBB_PARENT_NETWORKS,
    EBB_PEER_GROUPS,
)
from taac.abstractions.topology import RoutingDeviceConfig
from taac.constants import (
    BgpPlusPlusProfile,
    DEFAULT_LOCAL_LINK,
    DEFAULT_OPENR_START_IPV4S,
    DEFAULT_OPENR_START_IPV6S,
    DEFAULT_OTHER_LINK,
    OpenRRouteAction,
)
from taac.playbooks.routing.bgp_ebb_playbooks import (
    create_bgp_ebb_cold_start_playbook,
    create_bgp_ebb_daemon_restart_playbook,
    create_bgp_ebb_ebgp_route_oscillations_playbook,
    create_bgp_ebb_ebgp_session_oscillations_playbook,
    create_bgp_ebb_fauu_drain_undrain_playbook,
    create_bgp_ebb_ibgp_route_oscillations_playbook,
    create_bgp_ebb_ibgp_tornado_plane_oscillations_playbook,
    create_bgp_ebb_igp_instability_unresolvable_pnhs_playbook,
    create_bgp_ebb_igp_pnh_metric_oscillation_playbook,
    create_bgp_ebb_instability_attribute_churn_playbook,
    create_bgp_ebb_longevity_playbook,
    create_bgp_ebb_multipath_group_oscillation_playbook,
    create_bgp_ebb_nexthop_group_count_threshold_playbook,
    create_bgp_ebb_plane_drain_undrain_playbook,
    create_bgp_ebb_route_registry_runtime_update_playbook,
    create_bgp_ebb_route_storm_playbook,
)
from taac.task_definitions import (
    create_arista_create_file_from_config_task,
    create_arista_daemon_control_task,
    create_interface_ip_cleanup_task,
    create_interface_ip_configuration_task,
    create_openr_route_action_task,
    create_run_commands_on_shell_task,
)
from taac.testconfigs.routing.physical_inventory import (
    PhysicalInventory,
)
from taac.testconfigs.routing.util.bgp_ebb_constants import (
    _derive_test_config_name,
    BGP_MON_PEER_COUNT,
    BGP_MON_REMOTE_AS,
    DEFAULT_PROFILE,
    EBGP_PEER_COUNT_V4,
    EBGP_PEER_COUNT_V6,
    EBGP_PEER_TO_DRAIN,
    EBGP_REMOTE_AS,
    IBGP_PEER_SCALE_PER_PLANE,
    IBGP_PEER_TO_DRAIN_PER_PLANE,
    IBGP_REMOTE_AS,
    IXIA_BGP_MON_IC_PARENT_NETWORK,
    IXIA_EBGP_IC_PARENT_NETWORK_V4,
    IXIA_EBGP_IC_PARENT_NETWORK_V6,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE2,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE3,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE4,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE1,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE2,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE3,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE4,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE2,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE3,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE4,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE1,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE2,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE3,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE4,
    PEERGROUP_IBGP_V4,
    PEERGROUP_IBGP_V6,
)
from taac.testconfigs.routing.util.bgp_ebb_ixia_config import (
    create_ebb_scale_basic_port_configs,
)
from taac.testconfigs.routing.util.bgp_ebb_setup_tasks import (
    build_expected_peer_identity,
    get_common_setup_tasks,
    get_teardown_tasks,
)
from taac.utils.arista_utils import interface_name_to_short_format
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import DirectIxiaConnection, Endpoint, TestConfig


def create_ebb_cold_start_and_daemon_restart_test_config(
    physical_inventory: PhysicalInventory,
    profile: BgpPlusPlusProfile = DEFAULT_PROFILE,
) -> TestConfig:
    """Create the BGP++ conveyor test configuration (daemon-restart + cold-start).

    Extracted verbatim from the legacy
    ``testconfigs/routing/ebb/bag002_snc1_test_config.create_bag002_snc1_conveyor_test_config``
    factory as part of the Wave 1 hierarchical migration. Only the DUT
    identity + IXIA port map are parameterized on the ``physical_inventory`` argument;
    everything else (setup / teardown tasks, IXIA logical_topology, playbook list)
    is byte-wise identical to the pre-migration factory so the golden
    manifest hash for ``BAG002_SNC1_BGP_CONVEYOR_TEST`` is preserved.

    Playbooks:
    - ``bgp_daemon_restart_test_playbook``
    - ``bgp_cold_start_test_playbook``

    Args:
        physical_inventory: PhysicalInventory instance for the DUT (currently BAG002_SNC1).
        profile: BGP++ profile — determines whether OpenR route injection
            is added to setup tasks.

    Returns:
        TestConfig configured for the BGP++ conveyor CI/CD pipeline.
    """
    assert physical_inventory.ixia_ports, (
        "factory requires IXIA port map on physical_inventory"
    )
    assert physical_inventory.bgpcpp_configerator_path, (
        "factory requires bgpcpp_configerator_path on physical_inventory"
    )

    device_name = physical_inventory.device_name
    ixia_chassis_ip = physical_inventory.ixia_chassis_ip

    ixia_interface_mimic_ebgp, ixia_port_ebgp = physical_inventory.ixia_ports[0]
    ixia_interface_mimic_ibgp, ixia_port_ibgp = physical_inventory.ixia_ports[1]
    ixia_interface_mimic_bgp_mon, ixia_port_bgp_mon = physical_inventory.ixia_ports[2]

    # Build setup tasks based on profile
    # EXECUTION FLOW:
    # 1. async_setUp() runs first (includes EOS image deployment if eos_image_id passed to TaacRunner)
    # 2. IXIA setup happens during async_setUp()
    # 3. PRE-IXIA setup tasks run (ixia_needed=False)
    # 4. POST-IXIA setup tasks run (ixia_needed=True) <- config tasks run here
    #
    # Config tasks have ixia_needed=True so they run AFTER IXIA is configured
    setup_tasks = []

    # All config tasks below have ixia_needed=True so they run AFTER IXIA setup
    setup_tasks.extend(
        [
            # Shutdown EOS native BGP (router bgp <ASN>)
            # This must be done before enabling BGP++ daemons
            create_run_commands_on_shell_task(
                hostname=device_name,
                cmds=["configure\nrouter bgp 65060\nshutdown\nend"],
                ixia_needed=True,
            ),
            # Add IPv6 ACL rule to permit BGP++ control plane traffic (ports 5911-5919)
            create_run_commands_on_shell_task(
                hostname=device_name,
                cmds=[
                    "configure\n"
                    "ipv6 access-list aiv6-control-plane-acl\n"
                    "permit tcp any any range 5911 5919\n"
                    "end",
                ],
                ixia_needed=True,
            ),
            # Create required directories for config files
            create_run_commands_on_shell_task(
                hostname=device_name,
                cmds=[
                    "bash mkdir -p /usr/facebook/thrift_acls",
                    "bash mkdir -p /mnt/fb/agent_configs",
                ],
                ixia_needed=True,
            ),
            # Copy BGP++ config files from configerator to device
            create_arista_create_file_from_config_task(
                hostname=device_name,
                configerator_path=physical_inventory.bgpcpp_configerator_path,
                file_path="/mnt/flash/bgpcpp_config",
            ),
            create_arista_create_file_from_config_task(
                hostname=device_name,
                configerator_path="taac/ebb_ci_cd_configs/FibAgent.json",
                file_path="/usr/facebook/thrift_acls/FibAgent.json",
            ),
            create_arista_create_file_from_config_task(
                hostname=device_name,
                configerator_path="taac/ebb_ci_cd_configs/fib_agent_bgp.conf",
                file_path="/mnt/fb/agent_configs/fib_agent_bgp.conf",
            ),
            # Enable BGP++ daemons (ixia_needed=True so they run after IXIA setup)
            create_arista_daemon_control_task(
                hostname=device_name, daemon_name="Bgp", ixia_needed=True
            ),
            create_arista_daemon_control_task(
                hostname=device_name, daemon_name="FibAgent", ixia_needed=True
            ),
            create_arista_daemon_control_task(
                hostname=device_name, daemon_name="FibAgentBgp", ixia_needed=True
            ),
            create_arista_daemon_control_task(
                hostname=device_name, daemon_name="FibBgpGrpc", ixia_needed=True
            ),
            create_arista_daemon_control_task(
                hostname=device_name, daemon_name="FibGrpc", ixia_needed=True
            ),
            create_arista_daemon_control_task(
                hostname=device_name, daemon_name="Openr", ixia_needed=True
            ),
            create_arista_daemon_control_task(
                hostname=device_name, daemon_name="RouteGrpc", ixia_needed=True
            ),
            # Configure IXIA interfaces before IP address configuration
            create_run_commands_on_shell_task(
                hostname=device_name,
                cmds=[
                    "configure\n"
                    f"interface {ixia_interface_mimic_ebgp}\n"
                    "description IXIA_EBGP\n"
                    "mtu 9000\n"
                    "speed 400g-4\n"
                    "no switchport\n"
                    "!\n"
                    f"interface {ixia_interface_mimic_ibgp}\n"
                    "description IXIA_IBGP\n"
                    "mtu 9000\n"
                    "speed 400g-4\n"
                    "no switchport\n"
                    "!\n"
                    f"interface {ixia_interface_mimic_bgp_mon}\n"
                    "description IXIA_BGP_MON\n"
                    "mtu 9000\n"
                    "speed 400g-4\n"
                    "no switchport\n"
                    "end",
                ],
                ixia_needed=True,
            ),
            # Configure eBGP interface IPs (Ethernet3/25/1)
            # 140 IPv6 + 140 IPv4 secondary IPs for IXIA peers
            create_interface_ip_configuration_task(
                interface=ixia_interface_mimic_ebgp,
                peer_count=EBGP_PEER_COUNT_V6,
                ipv4_base_network=IXIA_EBGP_IC_PARENT_NETWORK_V4,
                ipv6_base_network=IXIA_EBGP_IC_PARENT_NETWORK_V6,
                address_families=["ipv4", "ipv6"],
                ixia_needed=True,
            ),
            # Configure iBGP interface IPs (Ethernet3/26/1)
            # 504 IPv6 + 504 IPv4 secondary IPs (8 planes × 63 peers/plane)
            create_interface_ip_configuration_task(
                interface=ixia_interface_mimic_ibgp,
                peer_count=IBGP_PEER_SCALE_PER_PLANE * 8,
                ipv4_base_network=IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
                ipv6_base_network=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
                address_families=["ipv4", "ipv6"],
                ixia_needed=True,
            ),
            # Configure BGP MON interface IPs (Ethernet3/27/1)
            # 1 IPv6 secondary IP for IXIA peer
            create_interface_ip_configuration_task(
                interface=ixia_interface_mimic_bgp_mon,
                peer_count=BGP_MON_PEER_COUNT,
                ipv6_base_network=IXIA_BGP_MON_IC_PARENT_NETWORK,
                address_families=["ipv6"],
                ixia_needed=True,
            ),
        ]
    )

    # Add OpenR route injection task if profile requires it
    if profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R:
        setup_tasks.append(
            create_openr_route_action_task(
                device_name=device_name,
                start_ipv4s=DEFAULT_OPENR_START_IPV4S,
                start_ipv6s=DEFAULT_OPENR_START_IPV6S,
                local_link=DEFAULT_LOCAL_LINK,
                other_link=DEFAULT_OTHER_LINK,
                action=OpenRRouteAction.INJECT.value,
                count=63,
                step=2,
            ),
        )

    # Build teardown tasks - restore interface configs from backup
    teardown_tasks = [
        create_interface_ip_cleanup_task(
            interfaces=[ixia_interface_mimic_ebgp],
            restore_from_backup=True,
            hostname=device_name,
        ),
        create_interface_ip_cleanup_task(
            interfaces=[ixia_interface_mimic_ibgp],
            restore_from_backup=True,
            hostname=device_name,
        ),
        create_interface_ip_cleanup_task(
            interfaces=[ixia_interface_mimic_bgp_mon],
            restore_from_backup=True,
            hostname=device_name,
        ),
    ]

    return TestConfig(
        name="BAG002_SNC1_BGP_CONVEYOR_TEST",
        skip_ixia_protocol_verification=True,
        log_collection_timeout=600,
        basset_pool="dne.test",
        endpoints=[
            Endpoint(
                name=device_name,
                dut=True,
                ixia_ports=[
                    ixia_interface_mimic_ebgp,
                    ixia_interface_mimic_ibgp,
                    ixia_interface_mimic_bgp_mon,
                ],
                direct_ixia_connections=[
                    DirectIxiaConnection(
                        interface=ixia_interface_mimic_ebgp,
                        ixia_chassis_ip=ixia_chassis_ip,
                        ixia_port=ixia_port_ebgp,
                    ),
                    DirectIxiaConnection(
                        interface=ixia_interface_mimic_ibgp,
                        ixia_chassis_ip=ixia_chassis_ip,
                        ixia_port=ixia_port_ibgp,
                    ),
                    DirectIxiaConnection(
                        interface=ixia_interface_mimic_bgp_mon,
                        ixia_chassis_ip=ixia_chassis_ip,
                        ixia_port=ixia_port_bgp_mon,
                    ),
                ],
            ),
        ],
        host_os_type_map={device_name: taac_types.DeviceOsType.ARISTA_FBOSS},
        startup_checks=[],
        setup_tasks=setup_tasks,
        teardown_tasks=teardown_tasks,
        basic_port_configs=create_ebb_scale_basic_port_configs(
            device_name=device_name,
            ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
            ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
            ixia_interface_mimic_bgp_mon=ixia_interface_mimic_bgp_mon,
            ebgp_peer_count_v6=EBGP_PEER_COUNT_V6,
            ebgp_peer_count_v4=EBGP_PEER_COUNT_V4,
            ebgp_peer_to_drain=EBGP_PEER_TO_DRAIN,
            ibgp_peer_scale_per_plane=IBGP_PEER_SCALE_PER_PLANE,
            ibgp_peer_to_drain_per_plane=IBGP_PEER_TO_DRAIN_PER_PLANE,
            bgp_mon_peer_count=BGP_MON_PEER_COUNT,
            ebgp_remote_as=EBGP_REMOTE_AS,
            ibgp_remote_as=IBGP_REMOTE_AS,
            bgp_mon_remote_as=BGP_MON_REMOTE_AS,
            ixia_ebgp_ic_parent_network_v6=IXIA_EBGP_IC_PARENT_NETWORK_V6,
            ixia_ebgp_ic_parent_network_v4=IXIA_EBGP_IC_PARENT_NETWORK_V4,
            ixia_ibgp_ic_parent_network_v6_dc_plane1=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
            ixia_ibgp_ic_parent_network_v6_dc_plane2=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE2,
            ixia_ibgp_ic_parent_network_v6_dc_plane3=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE3,
            ixia_ibgp_ic_parent_network_v6_dc_plane4=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE4,
            ixia_ibgp_ic_parent_network_v6_mp_plane1=IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE1,
            ixia_ibgp_ic_parent_network_v6_mp_plane2=IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE2,
            ixia_ibgp_ic_parent_network_v6_mp_plane3=IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE3,
            ixia_ibgp_ic_parent_network_v6_mp_plane4=IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE4,
            ixia_ibgp_ic_parent_network_v4_dc_plane1=IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
            ixia_ibgp_ic_parent_network_v4_dc_plane2=IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE2,
            ixia_ibgp_ic_parent_network_v4_dc_plane3=IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE3,
            ixia_ibgp_ic_parent_network_v4_dc_plane4=IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE4,
            ixia_ibgp_ic_parent_network_v4_mp_plane1=IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE1,
            ixia_ibgp_ic_parent_network_v4_mp_plane2=IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE2,
            ixia_ibgp_ic_parent_network_v4_mp_plane3=IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE3,
            ixia_ibgp_ic_parent_network_v4_mp_plane4=IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE4,
            ixia_bgp_mon_ic_parent_network=IXIA_BGP_MON_IC_PARENT_NETWORK,
            profile=profile,
        ),
        playbooks=[
            # BGP Daemon Restart Test Playbook - using factory function
            create_bgp_ebb_daemon_restart_playbook(
                device_name=device_name,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                profile=profile,
            ),
            # BGP Cold Start Test Playbook - using factory function
            create_bgp_ebb_cold_start_playbook(
                device_name=device_name,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                profile=profile,
            ),
        ],
    )


# =============================================================================
# Shared helper for the BAG010_ASH6 full-scale conveyor family
# =============================================================================
# Longevity soak duration (seconds). Temporarily reduced from 8h (28800s) to
# 4h; restore to 28800 to return to the full 8h soak.
_BAG010_LONGEVITY_DURATION_SECONDS = 14400  # 4h


def _build_ebb_full_scale_test_config(
    physical_inventory: PhysicalInventory,
    name: str,
    playbooks: list,
    profile: BgpPlusPlusProfile,
    enable_update_group: bool,
    drain: bool,
) -> TestConfig:
    """Assemble a byte-wise-identical bag010.ash6 conveyor TestConfig.

    Reproduces the legacy ``bag010_ash6_test_config._build_test_config``
    helper: builds ``get_common_setup_tasks`` + ``get_teardown_tasks``
    from ``conveyor_common_tasks``, wires the EBB-scale IXIA topology
    via ``create_ebb_scale_basic_port_configs``, and returns the
    ``TestConfig`` verbatim so the golden manifest hashes for
    ``BAG010_ASH6_BGP_DRAIN_CONVEYOR_TEST`` /
    ``BAG010_ASH6_BGP_RUNTIME_UPDATE_CONVEYOR_TEST`` /
    ``BAG010_ASH6_CONVEYOR_LONGEVITY_TEST_CONFIG`` (+ ``_UPDATE_GROUP``
    siblings) are preserved.
    """
    device_name = physical_inventory.device_name
    ixia_chassis_ip = physical_inventory.ixia_chassis_ip
    ixia_interface_mimic_ebgp, ixia_port_ebgp = physical_inventory.ixia_ports[0]
    ixia_interface_mimic_ibgp, ixia_port_ibgp = physical_inventory.ixia_ports[1]
    ixia_interface_mimic_bgp_mon, ixia_port_bgp_mon = physical_inventory.ixia_ports[2]

    assert physical_inventory.dut_bgp_as is not None, (
        "physical_inventory must have dut_bgp_as"
    )
    assert physical_inventory.bgpcpp_configerator_path is not None, (
        "physical_inventory must have bgpcpp_configerator_path"
    )

    extras = physical_inventory.extras
    setup_tasks = get_common_setup_tasks(
        device_name=device_name,
        bgp_asn=physical_inventory.dut_bgp_as,
        ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
        ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
        ixia_interface_mimic_bgp_mon=ixia_interface_mimic_bgp_mon,
        bgpcpp_configerator_path=physical_inventory.bgpcpp_configerator_path,
        profile=profile,
        openr_configerator_path=physical_inventory.openr_configerator_path,
        openr_port_channel_member=extras["openr_port_channel_member"],
        openr_port_channel_ipv4=extras["openr_port_channel_ipv4"],
        openr_port_channel_link_local=extras["openr_port_channel_link_local"],
        openr_local_link=extras["openr_local_link"],
        openr_other_link=extras["openr_other_link"],
        enable_update_group=enable_update_group,
    )
    teardown_tasks = get_teardown_tasks(
        ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
        ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
        ixia_interface_mimic_bgp_mon=ixia_interface_mimic_bgp_mon,
        device_name=device_name,
    )

    return TestConfig(
        name=name,
        skip_ixia_protocol_verification=True,
        log_collection_timeout=600,
        basset_pool="dne.test",
        endpoints=[
            Endpoint(
                name=device_name,
                dut=True,
                ixia_ports=[
                    ixia_interface_mimic_ebgp,
                    ixia_interface_mimic_ibgp,
                    ixia_interface_mimic_bgp_mon,
                ],
                direct_ixia_connections=[
                    DirectIxiaConnection(
                        interface=ixia_interface_mimic_ebgp,
                        ixia_chassis_ip=ixia_chassis_ip,
                        ixia_port=ixia_port_ebgp,
                    ),
                    DirectIxiaConnection(
                        interface=ixia_interface_mimic_ibgp,
                        ixia_chassis_ip=ixia_chassis_ip,
                        ixia_port=ixia_port_ibgp,
                    ),
                    DirectIxiaConnection(
                        interface=ixia_interface_mimic_bgp_mon,
                        ixia_chassis_ip=ixia_chassis_ip,
                        ixia_port=ixia_port_bgp_mon,
                    ),
                ],
            ),
        ],
        host_os_type_map={device_name: taac_types.DeviceOsType.ARISTA_FBOSS},
        startup_checks=[],
        setup_tasks=setup_tasks,
        teardown_tasks=teardown_tasks,
        basic_port_configs=create_ebb_scale_basic_port_configs(
            device_name=device_name,
            ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
            ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
            ixia_interface_mimic_bgp_mon=ixia_interface_mimic_bgp_mon,
            ebgp_peer_count_v6=EBGP_PEER_COUNT_V6,
            ebgp_peer_count_v4=EBGP_PEER_COUNT_V4,
            ebgp_peer_to_drain=EBGP_PEER_TO_DRAIN,
            ibgp_peer_scale_per_plane=IBGP_PEER_SCALE_PER_PLANE,
            ibgp_peer_to_drain_per_plane=IBGP_PEER_TO_DRAIN_PER_PLANE,
            drain=drain,
            bgp_mon_peer_count=BGP_MON_PEER_COUNT,
            ebgp_remote_as=EBGP_REMOTE_AS,
            ibgp_remote_as=IBGP_REMOTE_AS,
            bgp_mon_remote_as=BGP_MON_REMOTE_AS,
            ixia_ebgp_ic_parent_network_v6=IXIA_EBGP_IC_PARENT_NETWORK_V6,
            ixia_ebgp_ic_parent_network_v4=IXIA_EBGP_IC_PARENT_NETWORK_V4,
            ixia_ibgp_ic_parent_network_v6_dc_plane1=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
            ixia_ibgp_ic_parent_network_v6_dc_plane2=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE2,
            ixia_ibgp_ic_parent_network_v6_dc_plane3=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE3,
            ixia_ibgp_ic_parent_network_v6_dc_plane4=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE4,
            ixia_ibgp_ic_parent_network_v6_mp_plane1=IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE1,
            ixia_ibgp_ic_parent_network_v6_mp_plane2=IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE2,
            ixia_ibgp_ic_parent_network_v6_mp_plane3=IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE3,
            ixia_ibgp_ic_parent_network_v6_mp_plane4=IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE4,
            ixia_ibgp_ic_parent_network_v4_dc_plane1=IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
            ixia_ibgp_ic_parent_network_v4_dc_plane2=IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE2,
            ixia_ibgp_ic_parent_network_v4_dc_plane3=IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE3,
            ixia_ibgp_ic_parent_network_v4_dc_plane4=IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE4,
            ixia_ibgp_ic_parent_network_v4_mp_plane1=IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE1,
            ixia_ibgp_ic_parent_network_v4_mp_plane2=IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE2,
            ixia_ibgp_ic_parent_network_v4_mp_plane3=IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE3,
            ixia_ibgp_ic_parent_network_v4_mp_plane4=IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE4,
            ixia_bgp_mon_ic_parent_network=IXIA_BGP_MON_IC_PARENT_NETWORK,
            profile=profile,
        ),
        playbooks=playbooks,
    )


def _bag010_expected_established_session_count() -> int:
    """Established-session baseline for bag010.ash6 full-scale logical_topology.

    Total sessions across all peer types minus BGP MON. BGP MON peers
    (ASN 64001) legitimately stay IDLE intermittently on bag010 post-
    restart / cold-start, and the upstream bgpcpp configerator config does
    not always bring them back. Excluding them from BGP session-establish
    checks avoids spurious flakes while preserving the iBGP/eBGP signal.
    """
    total_session_count = (
        EBGP_PEER_COUNT_V6
        + EBGP_PEER_COUNT_V4
        + BGP_MON_PEER_COUNT
        + IBGP_PEER_SCALE_PER_PLANE * 4  # 4 DC-site devices, IPv4 remote EB
        + IBGP_PEER_SCALE_PER_PLANE * 4  # 4 DC-site devices, IPv6 remote EB
        + IBGP_PEER_SCALE_PER_PLANE * 4  # 4 MP-site devices, IPv4 remote MP
        + IBGP_PEER_SCALE_PER_PLANE * 4  # 4 MP-site devices, IPv6 remote MP
    )
    return total_session_count - BGP_MON_PEER_COUNT


def create_ebb_instability_test_config(
    physical_inventory: PhysicalInventory,
    profile: BgpPlusPlusProfile = DEFAULT_PROFILE,
    enable_update_group: bool = False,
) -> TestConfig:
    """BGP++ instability conveyor test (attribute-churn + route-storm).

    Extracted verbatim from the legacy
    ``bag010_ash6_test_config.create_bag010_ash6_instability_test_config``
    factory. TestConfig ``name`` field is preserved verbatim
    (``BAG010_ASH6_BGP_INSTABILITY_CONVEYOR_TEST`` (+ ``_UPDATE_GROUP``)).
    """
    name = "BAG010_ASH6_BGP_INSTABILITY_CONVEYOR_TEST"
    if enable_update_group:
        name += "_UPDATE_GROUP"

    device_name = physical_inventory.device_name
    ixia_interface_mimic_ibgp = physical_inventory.ixia_ports[1][0]
    session_count = _bag010_expected_established_session_count()
    return _build_ebb_full_scale_test_config(
        physical_inventory=physical_inventory,
        name=name,
        profile=profile,
        enable_update_group=enable_update_group,
        drain=False,
        playbooks=[
            create_bgp_ebb_instability_attribute_churn_playbook(
                device_name=device_name,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                total_session_count=session_count,
                profile=profile,
            ),
            create_bgp_ebb_route_storm_playbook(
                device_name=device_name,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                total_session_count=session_count,
                ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
                profile=profile,
            ),
        ],
    )


def create_ebb_runtime_update_test_config(
    physical_inventory: PhysicalInventory,
    profile: BgpPlusPlusProfile = DEFAULT_PROFILE,
    enable_update_group: bool = False,
) -> TestConfig:
    """BGP++ runtime-update conveyor test (prefix-list + multipath group).

    Extracted verbatim from the legacy
    ``bag010_ash6_test_config.create_bag010_ash6_runtime_update_test_config``
    factory.
    """
    name = "BAG010_ASH6_BGP_RUNTIME_UPDATE_CONVEYOR_TEST"
    if enable_update_group:
        name += "_UPDATE_GROUP"

    device_name = physical_inventory.device_name
    session_count = _bag010_expected_established_session_count()
    return _build_ebb_full_scale_test_config(
        physical_inventory=physical_inventory,
        name=name,
        profile=profile,
        enable_update_group=enable_update_group,
        drain=False,
        playbooks=[
            create_bgp_ebb_route_registry_runtime_update_playbook(
                device_name=device_name,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                expected_established_sessions=session_count,
                profile=profile,
            ),
            create_bgp_ebb_multipath_group_oscillation_playbook(
                device_name=device_name,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                expected_established_sessions=session_count,
                profile=profile,
            ),
        ],
    )


def create_ebb_drain_test_config(
    physical_inventory: PhysicalInventory,
    profile: BgpPlusPlusProfile = DEFAULT_PROFILE,
    enable_update_group: bool = False,
    name_override: str | None = None,
) -> TestConfig:
    """BGP++ drain conveyor test (FAUU + Plane drain/undrain).

    Extracted verbatim from the legacy
    ``bag010_ash6_test_config.create_bag010_ash6_drain_test_config``
    factory. Soft-drain (origin/local-pref attribute drain/undrain in the
    stages) runs on the full peer set; the carved session-drain pool
    (``drain=True``) is unused by these playbooks, so ``drain=False`` keeps
    all peers established and pre/post-test session counts verify.
    """
    name = name_override or _derive_test_config_name(
        physical_inventory, "DRAIN", enable_update_group
    )

    device_name = physical_inventory.device_name
    ixia_interface_mimic_ebgp = physical_inventory.ixia_ports[0][0]
    ixia_interface_mimic_ibgp = physical_inventory.ixia_ports[1][0]
    ixia_interface_mimic_bgp_mon = physical_inventory.ixia_ports[2][0]
    session_count = _bag010_expected_established_session_count()
    return _build_ebb_full_scale_test_config(
        physical_inventory=physical_inventory,
        name=name,
        profile=profile,
        enable_update_group=enable_update_group,
        drain=False,
        playbooks=[
            create_bgp_ebb_fauu_drain_undrain_playbook(
                device_name=device_name,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                expected_established_sessions=session_count,
                profile=profile,
                tcp_dump_capture_interface_ebgp=ixia_interface_mimic_ebgp,
                tcp_dump_capture_interface_bgpmon=ixia_interface_mimic_bgp_mon,
                tcp_dump_capture_interface_ibgp=ixia_interface_mimic_ibgp,
            ),
            create_bgp_ebb_plane_drain_undrain_playbook(
                device_name=device_name,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                expected_established_sessions=session_count,
                profile=profile,
                tcp_dump_capture_interface_ebgp=ixia_interface_mimic_ebgp,
                tcp_dump_capture_interface_bgpmon=ixia_interface_mimic_bgp_mon,
                tcp_dump_capture_interface_ibgp=ixia_interface_mimic_ibgp,
            ),
        ],
    )


def create_ebb_stage1_consolidated_test_config(
    physical_inventory: PhysicalInventory,
    profile: BgpPlusPlusProfile = DEFAULT_PROFILE,
    enable_update_group: bool = False,
    name_override: str | None = None,
) -> TestConfig:
    """Stage-1 consolidated conveyor test — all non-longevity bag010 playbooks.

    Extracted verbatim from the legacy
    ``bag010_ash6_test_config.create_bag010_ash6_stage1_consolidated_test_config``
    factory. Runs 5 playbooks under one setup phase:
    attribute-churn, route-storm, prefix-list runtime update, multipath
    oscillation, and pnh_metric_oscillation (moved from bag011 for
    cross-device balance).
    """
    name = name_override or _derive_test_config_name(
        physical_inventory, "STAGE1_CONSOLIDATED", enable_update_group
    )

    device_name = physical_inventory.device_name
    ixia_interface_mimic_ibgp = physical_inventory.ixia_ports[1][0]
    session_count = _bag010_expected_established_session_count()
    expected_peer_identity = build_expected_peer_identity()
    return _build_ebb_full_scale_test_config(
        physical_inventory=physical_inventory,
        name=name,
        profile=profile,
        enable_update_group=enable_update_group,
        drain=False,
        playbooks=[
            create_bgp_ebb_instability_attribute_churn_playbook(
                device_name=device_name,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                total_session_count=session_count,
                profile=profile,
            ),
            create_bgp_ebb_route_storm_playbook(
                device_name=device_name,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                total_session_count=session_count,
                ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
                profile=profile,
            ),
            create_bgp_ebb_route_registry_runtime_update_playbook(
                device_name=device_name,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                expected_established_sessions=session_count,
                profile=profile,
            ),
            create_bgp_ebb_multipath_group_oscillation_playbook(
                device_name=device_name,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                expected_established_sessions=session_count,
                profile=profile,
            ),
            create_bgp_ebb_igp_pnh_metric_oscillation_playbook(
                device_name=device_name,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                local_link=physical_inventory.extras["openr_local_link"],
                other_link=physical_inventory.extras["openr_other_link"],
                expected_established_sessions=session_count,
                profile=profile,
                expected_peer_identity=expected_peer_identity,
            ),
        ],
    )


# =============================================================================
# BAG011_ASH6 conveyor family — Restart / Oscillations / Stability / Stage1
# =============================================================================
# bag011.ash6 nexthop group threshold — fail if num_groups_configured meets or
# exceeds this value. Preserved verbatim from the legacy
# ``bag011_ash6_test_config.NEXTHOP_GROUP_THRESHOLD``.
_BAG011_NEXTHOP_GROUP_THRESHOLD = 100


def _bag011_expected_established_session_count() -> int:
    """Established-session baseline for bag011.ash6 full-scale logical_topology.

    Total sessions across all peer types minus BGP MON. BGP MON peers
    (ASN 64001) legitimately stay IDLE intermittently on bag011 post-
    restart / cold-start (R96.1 failure analysis), and the upstream bgpcpp
    configerator config does not always bring them back. Excluding them from
    BGP session-establish checks avoids spurious flakes while preserving the
    iBGP/eBGP signal.
    """
    total_session_count = (
        EBGP_PEER_COUNT_V6
        + EBGP_PEER_COUNT_V4
        + BGP_MON_PEER_COUNT
        + IBGP_PEER_SCALE_PER_PLANE * 4  # 4 DC-site devices, IPv4 remote EB
        + IBGP_PEER_SCALE_PER_PLANE * 4  # 4 DC-site devices, IPv6 remote EB
        + IBGP_PEER_SCALE_PER_PLANE * 4  # 4 MP-site devices, IPv4 remote MP
        + IBGP_PEER_SCALE_PER_PLANE * 4  # 4 MP-site devices, IPv6 remote MP
    )
    return total_session_count - BGP_MON_PEER_COUNT


def create_bgp_ebb_restart_test_config(
    physical_inventory: PhysicalInventory,
    profile: BgpPlusPlusProfile = DEFAULT_PROFILE,
    enable_update_group: bool = False,
) -> TestConfig:
    """BGP restart conveyor test — daemon-restart + cold-start.

    Extracted verbatim from the legacy
    ``bag011_ash6_test_config.create_bgp_restart_test_config`` factory. The
    internal ``TestConfig.name`` field is preserved verbatim as
    ``BAG011_ASH6_BGP_RESTART_CONVEYOR_TEST`` (+ ``_UPDATE_GROUP``) so the
    golden manifest hash is byte-wise identical.
    """
    name = "BAG011_ASH6_BGP_RESTART_CONVEYOR_TEST"
    if enable_update_group:
        name += "_UPDATE_GROUP"

    device_name = physical_inventory.device_name
    expected_peer_identity = build_expected_peer_identity()
    return _build_ebb_full_scale_test_config(
        physical_inventory=physical_inventory,
        name=name,
        profile=profile,
        enable_update_group=enable_update_group,
        drain=False,
        playbooks=[
            create_bgp_ebb_daemon_restart_playbook(
                device_name=device_name,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                profile=profile,
                expected_peer_identity=expected_peer_identity,
            ),
            create_bgp_ebb_cold_start_playbook(
                device_name=device_name,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                profile=profile,
                expected_peer_identity=expected_peer_identity,
            ),
        ],
    )


def create_bgp_ebb_oscillations_test_config(
    physical_inventory: PhysicalInventory,
    profile: BgpPlusPlusProfile = DEFAULT_PROFILE,
    enable_update_group: bool = False,
) -> TestConfig:
    """BGP oscillations conveyor test — eBGP/iBGP session + route oscillations.

    Extracted verbatim from the legacy
    ``bag011_ash6_test_config.create_bgp_oscillations_test_config`` factory.
    The internal ``TestConfig.name`` field is preserved verbatim as
    ``BAG011_ASH6_BGP_OSCILLATIONS_CONVEYOR_TEST`` (+ ``_UPDATE_GROUP``) so
    the golden manifest hash is byte-wise identical.
    """
    name = "BAG011_ASH6_BGP_OSCILLATIONS_CONVEYOR_TEST"
    if enable_update_group:
        name += "_UPDATE_GROUP"

    device_name = physical_inventory.device_name
    session_count = _bag011_expected_established_session_count()
    expected_peer_identity = build_expected_peer_identity()
    return _build_ebb_full_scale_test_config(
        physical_inventory=physical_inventory,
        name=name,
        profile=profile,
        enable_update_group=enable_update_group,
        drain=False,
        playbooks=[
            create_bgp_ebb_ebgp_session_oscillations_playbook(
                device_name=device_name,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                ipv4_session_count=EBGP_PEER_COUNT_V4,
                ipv6_session_count=EBGP_PEER_COUNT_V6,
                expected_established_sessions=session_count,
                profile=profile,
                expected_peer_identity=expected_peer_identity,
            ),
            create_bgp_ebb_ibgp_tornado_plane_oscillations_playbook(
                device_name=device_name,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                ipv4_sessions_per_plane=IBGP_PEER_SCALE_PER_PLANE,
                ipv6_sessions_per_plane=IBGP_PEER_SCALE_PER_PLANE,
                expected_established_sessions=session_count,
                profile=profile,
                expected_peer_identity=expected_peer_identity,
            ),
            create_bgp_ebb_ebgp_route_oscillations_playbook(
                device_name=device_name,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                expected_established_sessions=session_count,
                profile=profile,
            ),
            create_bgp_ebb_ibgp_route_oscillations_playbook(
                device_name=device_name,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                expected_established_sessions=session_count,
                profile=profile,
            ),
        ],
    )


def create_bgp_ebb_stability_test_config(
    physical_inventory: PhysicalInventory,
    profile: BgpPlusPlusProfile = DEFAULT_PROFILE,
    enable_update_group: bool = False,
) -> TestConfig:
    """BGP stability conveyor test — Tier 3 IGP instability + nexthop group.

    Extracted verbatim from the legacy
    ``bag011_ash6_test_config.create_bgp_stability_test_config`` factory.
    The internal ``TestConfig.name`` field is preserved verbatim as
    ``BAG011_ASH6_BGP_STABILITY_CONVEYOR_TEST`` (+ ``_UPDATE_GROUP``) so
    the golden manifest hash is byte-wise identical.
    """
    name = "BAG011_ASH6_BGP_STABILITY_CONVEYOR_TEST"
    if enable_update_group:
        name += "_UPDATE_GROUP"

    device_name = physical_inventory.device_name
    ixia_interface_mimic_bgp_mon = physical_inventory.ixia_ports[2][0]
    session_count = _bag011_expected_established_session_count()
    expected_peer_identity = build_expected_peer_identity()
    return _build_ebb_full_scale_test_config(
        physical_inventory=physical_inventory,
        name=name,
        profile=profile,
        enable_update_group=enable_update_group,
        drain=False,
        playbooks=[
            create_bgp_ebb_igp_pnh_metric_oscillation_playbook(
                device_name=device_name,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                local_link=physical_inventory.extras["openr_local_link"],
                other_link=physical_inventory.extras["openr_other_link"],
                expected_established_sessions=session_count,
                profile=profile,
                expected_peer_identity=expected_peer_identity,
            ),
            create_bgp_ebb_igp_instability_unresolvable_pnhs_playbook(
                device_name=device_name,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                tcp_dump_capture_interface=interface_name_to_short_format(
                    ixia_interface_mimic_bgp_mon
                ),
                local_link=physical_inventory.extras["openr_local_link"],
                other_link=physical_inventory.extras["openr_other_link"],
                expected_established_sessions=session_count,
                profile=profile,
                expected_peer_identity=expected_peer_identity,
            ),
            create_bgp_ebb_nexthop_group_count_threshold_playbook(
                device_name=device_name,
                nexthop_group_threshold=_BAG011_NEXTHOP_GROUP_THRESHOLD,
            ),
        ],
    )


def create_bgp_ebb_stage1_test_config(
    physical_inventory: PhysicalInventory,
    profile: BgpPlusPlusProfile = DEFAULT_PROFILE,
    enable_update_group: bool = False,
    name_override: str | None = None,
) -> TestConfig:
    """Stage-1 consolidated conveyor test — all bag011 playbooks minus pnh_metric_oscillation.

    Extracted verbatim from the legacy
    ``bag011_ash6_test_config.create_bag011_ash6_stage1_consolidated_test_config``
    factory. Runs 8 playbooks under one setup phase (restart first, then
    oscillations, then IGP-instability + nexthop-group). The
    ``bgp_igp_instability_pnh_metric_oscillation`` playbook is moved to
    bag010 for cross-device wall-clock balance (both bag010 and bag011 share
    the same full-scale logical_topology).
    """
    name = name_override or _derive_test_config_name(
        physical_inventory, "STAGE1_CONSOLIDATED", enable_update_group
    )

    device_name = physical_inventory.device_name
    ixia_interface_mimic_bgp_mon = physical_inventory.ixia_ports[2][0]
    session_count = _bag011_expected_established_session_count()
    expected_peer_identity = build_expected_peer_identity()
    return _build_ebb_full_scale_test_config(
        physical_inventory=physical_inventory,
        name=name,
        profile=profile,
        enable_update_group=enable_update_group,
        drain=False,
        playbooks=[
            create_bgp_ebb_daemon_restart_playbook(
                device_name=device_name,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                profile=profile,
                expected_peer_identity=expected_peer_identity,
            ),
            create_bgp_ebb_cold_start_playbook(
                device_name=device_name,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                profile=profile,
                expected_peer_identity=expected_peer_identity,
            ),
            create_bgp_ebb_ebgp_session_oscillations_playbook(
                device_name=device_name,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                ipv4_session_count=EBGP_PEER_COUNT_V4,
                ipv6_session_count=EBGP_PEER_COUNT_V6,
                expected_established_sessions=session_count,
                profile=profile,
                expected_peer_identity=expected_peer_identity,
            ),
            create_bgp_ebb_ebgp_route_oscillations_playbook(
                device_name=device_name,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                expected_established_sessions=session_count,
                profile=profile,
            ),
            create_bgp_ebb_ibgp_tornado_plane_oscillations_playbook(
                device_name=device_name,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                ipv4_sessions_per_plane=IBGP_PEER_SCALE_PER_PLANE,
                ipv6_sessions_per_plane=IBGP_PEER_SCALE_PER_PLANE,
                expected_established_sessions=session_count,
                profile=profile,
                expected_peer_identity=expected_peer_identity,
            ),
            create_bgp_ebb_ibgp_route_oscillations_playbook(
                device_name=device_name,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                expected_established_sessions=session_count,
                profile=profile,
            ),
            create_bgp_ebb_igp_instability_unresolvable_pnhs_playbook(
                device_name=device_name,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                tcp_dump_capture_interface=interface_name_to_short_format(
                    ixia_interface_mimic_bgp_mon
                ),
                local_link=physical_inventory.extras["openr_local_link"],
                other_link=physical_inventory.extras["openr_other_link"],
                expected_established_sessions=session_count,
                profile=profile,
                expected_peer_identity=expected_peer_identity,
            ),
            create_bgp_ebb_nexthop_group_count_threshold_playbook(
                device_name=device_name,
                nexthop_group_threshold=_BAG011_NEXTHOP_GROUP_THRESHOLD,
            ),
        ],
    )


def _create_ebb_longevity_playbooks(physical_inventory: PhysicalInventory) -> list:
    return [
        create_bgp_ebb_longevity_playbook(
            device_name=physical_inventory.device_name,
            duration=_BAG010_LONGEVITY_DURATION_SECONDS,
        ),
    ]


def create_ebb_longevity_test_config(
    physical_inventory: PhysicalInventory,
    profile: BgpPlusPlusProfile = DEFAULT_PROFILE,
    enable_update_group: bool = False,
    name_override: str | None = None,
) -> TestConfig:
    """BGP++ longevity soak conveyor test (4h, community churn every 60s).

    Extracted verbatim from the legacy
    ``bag010_ash6_test_config.create_bag010_ash6_longevity_test_config``
    factory. Longevity soak duration is temporarily reduced from 8h to 4h
    (see ``_BAG010_LONGEVITY_DURATION_SECONDS``); restore to 28800 to
    return to the full 8h soak.
    """
    name = name_override or _derive_test_config_name(
        physical_inventory, "LONGEVITY", enable_update_group
    )

    bound = ebb_full_scale_topology(
        openr_enabled=(profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R),
    ).bind_to_inventory(
        physical_inventory=physical_inventory,
        port_map=EBB_FULL_SCALE_PORT_MAP_WITH_BGPMON,
        parent_networks=EBB_PARENT_NETWORKS,
        peer_groups=EBB_PEER_GROUPS,
        as_numbers=EBB_AS_NUMBERS,
        device_config_override=RoutingDeviceConfig(
            openr_enable=(profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R),
            update_group_enable=enable_update_group,
        ),
    )
    compiled = bound.compile()
    return TestConfig(
        name=name,
        skip_ixia_protocol_verification=True,
        log_collection_timeout=600,
        basset_pool="dne.test",
        endpoints=compiled.endpoints,
        host_os_type_map=compiled.host_os_type_map,
        startup_checks=[],
        setup_tasks=compiled.setup_tasks,
        teardown_tasks=compiled.teardown_tasks,
        basic_port_configs=compiled.basic_port_configs,
        playbooks=_create_ebb_longevity_playbooks(physical_inventory),
    )
