# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
BGP++ Conveyor Test Configuration for bag012.ash6.

This test config is designed for the EBB BGP++ CI/CD conveyor pipeline.
It runs the following playbooks:
- bgp_update_packing_validation_playbook
- constant_attribute_storage_varying_combinations_test

Test direction matches EB02_ARISTA_BGP_UPDATE_PACKING_VALIDATION:
- EBGP → IBGP: 10 EBGP peers inject routes, 1 IBGP peer captures UPDATEs
- 2 IXIA ports only (no BGP MON)

Constant Attribute Storage Varying Combinations Test:
- Validates that memory for storing pool of attributes is constant
- 8 EBGP peers + 2 IBGP peers (smaller scale, no openR)
- Uses custom setup tasks

Device: bag012.ash6
IXIA Chassis: ares1-my24520014
IXIA Ports:
- Et3/36/1 -> 7/7 (eBGP)
- Et3/36/2 -> 7/8 (iBGP)
"""

from taac.constants import BgpPlusPlusProfile
from taac.routing.ebb.ebb_bgp_plus_plus_test_config.ebb_bgp_plus_plus_conveyor.conveyor_common_tasks import (
    build_per_iteration_factory_v4_capable,
    get_update_packing_setup_tasks,
)
from taac.routing.ebb.ebb_bgp_plus_plus_test_config.ebb_bgp_plus_plus_conveyor.conveyor_constants import (
    EBGP_PEER_COUNT_V6,
    EBGP_REMOTE_AS,
    IBGP_PEER_SCALE_PER_PLANE,
    IBGP_REMOTE_AS,
    IXIA_EBGP_IC_PARENT_NETWORK_V4,
    IXIA_EBGP_IC_PARENT_NETWORK_V6,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
    IXIA_IPV4_START_OFFSET,
    PEERGROUP_EBGP_V4,
    PEERGROUP_EBGP_V6,
    PEERGROUP_IBGP_V4,
    PEERGROUP_IBGP_V6,
)
from taac.testconfigs.routing.ebb.test_config_performance_scaling_case1 import (
    test_config_for_bgp_plus_plus_on_ebb_arista_performance_scaling,
)
from taac.testconfigs.routing.ebb.test_config_performance_scaling_case2 import (
    test_config_constant_attribute_storage_varying_combinations_on_eos,
)
from taac.testconfigs.routing.ebb.test_config_performance_scaling_case9 import (
    test_config_for_bgp_plus_plus_on_ebb_arista_bounded_ecmp_sets,
)
from taac.testconfigs.routing.ebb.test_config_queue_memory_monitor import (
    test_config_bgp_queue_memory_monitoring_with_route_scale,
)
from taac.testconfigs.routing.ebb.test_config_update_packing import (
    test_config_bgp_update_packing_validation,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import DirectIxiaConnection


# =============================================================================
# Device-specific configuration for bag012.ash6
# =============================================================================
DEVICE_NAME = "bag012.ash6"
IXIA_CHASSIS_IP = "2401:db00:2066:303b::3001"
BAG012_EOS_BGP_AS = 65012
BGPCPP_CONFIGERATOR_PATH = "taac/ebb_ci_cd_configs/ebb_full_scale_bgpcpp_config"
BAG012_ROUTER_ID = "10.163.28.11"

# IXIA interface mappings for bag012.ash6 (no BGP MON needed)
IXIA_INTERFACE_MIMIC_EBGP = "Ethernet3/36/1"
IXIA_INTERFACE_MIMIC_IBGP = "Ethernet3/36/2"

# IXIA port mappings (chassis slot/port)
IXIA_PORT_EBGP = "7/7"
IXIA_PORT_IBGP = "7/8"


def create_bag012_ash6_conveyor_test_config(
    enable_update_group: bool = False,
) -> taac_types.TestConfig:
    """
    Create the test configuration for bag012.ash6 conveyor testing.

    Reuses test_config_bgp_update_packing_validation() with bag012-specific
    setup_tasks and direct_ixia_connections.

    Test direction matches EB02_ARISTA_BGP_UPDATE_PACKING_VALIDATION:
    - EBGP → IBGP: 10 EBGP peers inject routes, 1 IBGP peer captures UPDATEs
    - ebgp_route_acceptance_communities=["65529:39744"]

    Args:
        enable_update_group: When True, dynamically toggles BGP++
            ``enable_update_group`` (and the ``update_group_config`` struct
            per D100093369) by patching ``/mnt/flash/bgpcpp_config`` in-shell
            during BGP++ deployment. The test config name is suffixed with
            ``_UPDATE_GROUP``.

    Returns:
        TestConfig object configured for bag012.ash6
    """
    name = "BAG012_ASH6_BGP_CONVEYOR_TEST"
    if enable_update_group:
        name += "_UPDATE_GROUP"
    setup_tasks = get_update_packing_setup_tasks(
        device_name=DEVICE_NAME,
        bgp_asn=BAG012_EOS_BGP_AS,
        ixia_interface_mimic_ebgp=IXIA_INTERFACE_MIMIC_EBGP,
        ixia_interface_mimic_ibgp=IXIA_INTERFACE_MIMIC_IBGP,
        ebgp_peer_count=10,
        ibgp_peer_count=1,
        ebgp_remote_as=EBGP_REMOTE_AS,
        ibgp_remote_as=IBGP_REMOTE_AS,
        ixia_ebgp_ic_parent_network_v6=IXIA_EBGP_IC_PARENT_NETWORK_V6,
        ixia_ibgp_ic_parent_network_v6=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
        router_id=BAG012_ROUTER_ID,
        bgpcpp_configerator_path=BGPCPP_CONFIGERATOR_PATH,
        profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
        enable_update_group=enable_update_group,
    )

    return test_config_bgp_update_packing_validation(
        test_config_name=name,
        device_name=DEVICE_NAME,
        # EBGP configuration (ingress - routes sent here from Fabric Aggregators)
        ixia_interface_mimic_ebgp=IXIA_INTERFACE_MIMIC_EBGP,
        ebgp_remote_as=EBGP_REMOTE_AS,
        ixia_ebgp_ic_parent_network_v6=IXIA_EBGP_IC_PARENT_NETWORK_V6,
        ixia_ebgp_ic_parent_network_v4="",
        # IBGP configuration (egress - capture UPDATEs here)
        ixia_interface_mimic_ibgp=IXIA_INTERFACE_MIMIC_IBGP,
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
        setup_tasks=setup_tasks,
        host_os_type_map={DEVICE_NAME: taac_types.DeviceOsType.ARISTA_FBOSS},
        direct_ixia_connections=[
            DirectIxiaConnection(
                interface=IXIA_INTERFACE_MIMIC_EBGP,
                ixia_chassis_ip=IXIA_CHASSIS_IP,
                ixia_port=IXIA_PORT_EBGP,
            ),
            DirectIxiaConnection(
                interface=IXIA_INTERFACE_MIMIC_IBGP,
                ixia_chassis_ip=IXIA_CHASSIS_IP,
                ixia_port=IXIA_PORT_IBGP,
            ),
        ],
        log_collection_timeout=600,
    )


def create_bag012_ash6_constant_attribute_storage_test_config(
    enable_update_group: bool = False,
) -> taac_types.TestConfig:
    """
    Create the constant attribute storage varying combinations test config
    for bag012.ash6.

    Validates that the amount of memory for storing pool of attributes
    remains constant regardless of the number of unique attribute-set
    combinations.

    Uses custom setup tasks (no openR) with smaller scale:
    - 8 EBGP peers + 2 IBGP peers

    Args:
        enable_update_group: When True, dynamically toggles BGP++
            ``enable_update_group`` on the device. Suffixes test name with
            ``_UPDATE_GROUP``.

    Returns:
        TestConfig object configured for bag012.ash6
    """
    name = "BAG012_ASH6_BGP_CONSTANT_ATTRIBUTE_STORAGE_CONVEYOR_TEST"
    if enable_update_group:
        name += "_UPDATE_GROUP"
    setup_tasks = get_update_packing_setup_tasks(
        device_name=DEVICE_NAME,
        bgp_asn=BAG012_EOS_BGP_AS,
        ixia_interface_mimic_ebgp=IXIA_INTERFACE_MIMIC_EBGP,
        ixia_interface_mimic_ibgp=IXIA_INTERFACE_MIMIC_IBGP,
        ebgp_peer_count=8,
        ibgp_peer_count=2,
        ebgp_remote_as=EBGP_REMOTE_AS,
        ibgp_remote_as=IBGP_REMOTE_AS,
        ixia_ebgp_ic_parent_network_v6=IXIA_EBGP_IC_PARENT_NETWORK_V6,
        ixia_ibgp_ic_parent_network_v6=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
        router_id=BAG012_ROUTER_ID,
        bgpcpp_configerator_path=BGPCPP_CONFIGERATOR_PATH,
        profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
        enable_update_group=enable_update_group,
    )

    return test_config_constant_attribute_storage_varying_combinations_on_eos(
        test_config_name=name,
        device_name=DEVICE_NAME,
        # EBGP configuration
        ixia_interface_mimic_ebgp=IXIA_INTERFACE_MIMIC_EBGP,
        ebgp_remote_as=EBGP_REMOTE_AS,
        ixia_ebgp_ic_parent_network_v6=IXIA_EBGP_IC_PARENT_NETWORK_V6,
        ixia_ebgp_ic_parent_network_v4=IXIA_EBGP_IC_PARENT_NETWORK_V4,
        # IBGP configuration
        ixia_interface_mimic_ibgp=IXIA_INTERFACE_MIMIC_IBGP,
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
        host_os_type_map={DEVICE_NAME: taac_types.DeviceOsType.ARISTA_FBOSS},
        direct_ixia_connections=[
            DirectIxiaConnection(
                interface=IXIA_INTERFACE_MIMIC_EBGP,
                ixia_chassis_ip=IXIA_CHASSIS_IP,
                ixia_port=IXIA_PORT_EBGP,
            ),
            DirectIxiaConnection(
                interface=IXIA_INTERFACE_MIMIC_IBGP,
                ixia_chassis_ip=IXIA_CHASSIS_IP,
                ixia_port=IXIA_PORT_IBGP,
            ),
        ],
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


def create_bag012_ash6_queue_memory_monitor_test_config(
    enable_update_group: bool = False,
) -> taac_types.TestConfig:
    """
    Create the queue memory monitor test config for bag012.ash6.

    Monitors BGP++ fiber queue statistics and memory usage under route churn.
    - 140 EBGP peers with route flapping (15s up / 15s down)
    - 63 IBGP peers (full EBB scale)
    - Monitor for 60 minutes at 2-minute intervals

    Args:
        enable_update_group: When True, dynamically toggles BGP++
            ``enable_update_group`` on the device. Suffixes test name with
            ``_UPDATE_GROUP``.

    Returns:
        TestConfig object configured for bag012.ash6
    """
    name = "BAG012_ASH6_BGP_QUEUE_MEMORY_MONITOR_CONVEYOR_TEST"
    if enable_update_group:
        name += "_UPDATE_GROUP"
    setup_tasks = get_update_packing_setup_tasks(
        device_name=DEVICE_NAME,
        bgp_asn=BAG012_EOS_BGP_AS,
        ixia_interface_mimic_ebgp=IXIA_INTERFACE_MIMIC_EBGP,
        ixia_interface_mimic_ibgp=IXIA_INTERFACE_MIMIC_IBGP,
        ebgp_peer_count=EBGP_PEER_COUNT_V6,
        ibgp_peer_count=IBGP_PEER_SCALE_PER_PLANE,
        ebgp_remote_as=EBGP_REMOTE_AS,
        ibgp_remote_as=IBGP_REMOTE_AS,
        ixia_ebgp_ic_parent_network_v6=IXIA_EBGP_IC_PARENT_NETWORK_V6,
        ixia_ibgp_ic_parent_network_v6=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
        router_id=BAG012_ROUTER_ID,
        bgpcpp_configerator_path=BGPCPP_CONFIGERATOR_PATH,
        profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
        enable_update_group=enable_update_group,
    )

    # CPU stress is deployed directly by the custom step (_deploy_cpu_stress)
    # when monitor_cpu_stress=True — no need for setup_tasks deployment.

    return test_config_bgp_queue_memory_monitoring_with_route_scale(
        test_config_name=name,
        device_name=DEVICE_NAME,
        # IBGP configuration
        ixia_interface_mimic_ibgp=IXIA_INTERFACE_MIMIC_IBGP,
        ibgp_local_as=IBGP_REMOTE_AS,
        ixia_ibgp_ic_parent_network_v6=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
        ixia_ibgp_ic_parent_network_v4=IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
        # EBGP configuration
        ixia_interface_mimic_ebgp=IXIA_INTERFACE_MIMIC_EBGP,
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
        host_os_type_map={DEVICE_NAME: taac_types.DeviceOsType.ARISTA_FBOSS},
        direct_ixia_connections=[
            DirectIxiaConnection(
                interface=IXIA_INTERFACE_MIMIC_EBGP,
                ixia_chassis_ip=IXIA_CHASSIS_IP,
                ixia_port=IXIA_PORT_EBGP,
            ),
            DirectIxiaConnection(
                interface=IXIA_INTERFACE_MIMIC_IBGP,
                ixia_chassis_ip=IXIA_CHASSIS_IP,
                ixia_port=IXIA_PORT_IBGP,
            ),
        ],
        log_collection_timeout=600,
    )


# Export the test configs
BAG012_ASH6_CONVEYOR_TEST_CONFIG = create_bag012_ash6_conveyor_test_config()
BAG012_ASH6_CONSTANT_ATTRIBUTE_STORAGE_TEST_CONFIG = (
    create_bag012_ash6_constant_attribute_storage_test_config()
)
BAG012_ASH6_QUEUE_MEMORY_MONITOR_TEST_CONFIG = (
    create_bag012_ash6_queue_memory_monitor_test_config()
)


# =============================================================================
# BGP++ Performance Scaling — egress IBGP peer sweep on bag012.ash6 conveyor.
# =============================================================================
# Defaults match the simplified rewrite of D104072489: per stage n peers per
# AF, total = 2n + 2 EBGP. Each Stage rewrites /mnt/flash/bgpcpp_config to
# have exactly the matching number of peer entries (so BGP++ EOR completes
# from 100% of configured peers and convergence isn't clamped at the 2-min
# EOR-expiry timer).
BAG012_ASH6_PERFORMANCE_SCALING_EGRESS_PEER_COUNTS: list = [100, 200, 300, 400, 500]
BAG012_ASH6_PERFORMANCE_SCALING_PREFIX_COUNT: int = 50000


def create_bag012_ash6_performance_scaling_test_config(
    enable_update_group: bool = False,
) -> taac_types.TestConfig:
    """Egress IBGP peer-sweep TestConfig for bag012.ash6 conveyor (v6 + v4).

    Per Stage n in egress_peer_counts, the device is configured with n v6 +
    n v4 IBGP peers via in-shell bgpcpp_config rewrite, then 50K v6 + 50K v4
    EBGP prefixes are advertised and initial convergence is measured. A
    final aggregator Stage produces one consolidated everpaste plot.

    Args:
        enable_update_group: When True, dynamically toggles BGP++
            ``enable_update_group`` on the device. Suffixes test name with
            ``_UPDATE_GROUP``. The per-iteration factory only rewrites
            ``peers`` + ``router_id``; ``bgp_setting_config`` (where
            ``enable_update_group`` lives) is preserved across iterations.
    """
    name = "BAG012_ASH6_BGP_PERFORMANCE_SCALING_CONVEYOR_TEST"
    if enable_update_group:
        name += "_UPDATE_GROUP"
    setup_tasks = get_update_packing_setup_tasks(
        device_name=DEVICE_NAME,
        bgp_asn=BAG012_EOS_BGP_AS,
        ixia_interface_mimic_ebgp=IXIA_INTERFACE_MIMIC_EBGP,
        ixia_interface_mimic_ibgp=IXIA_INTERFACE_MIMIC_IBGP,
        ebgp_peer_count=1,
        ibgp_peer_count=BAG012_ASH6_PERFORMANCE_SCALING_EGRESS_PEER_COUNTS[0],
        ebgp_remote_as=EBGP_REMOTE_AS,
        ibgp_remote_as=IBGP_REMOTE_AS,
        ixia_ebgp_ic_parent_network_v6=IXIA_EBGP_IC_PARENT_NETWORK_V6,
        ixia_ibgp_ic_parent_network_v6=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
        # v4 enables dual-stack IBGP/EBGP at startup so the initial
        # /mnt/flash/bgpcpp_config matches the v6+v4 layout that each
        # per-iteration factory call produces.
        ixia_ebgp_ic_parent_network_v4=IXIA_EBGP_IC_PARENT_NETWORK_V4,
        ixia_ibgp_ic_parent_network_v4=IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
        router_id=BAG012_ROUTER_ID,
        bgpcpp_configerator_path=BGPCPP_CONFIGERATOR_PATH,
        profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
        enable_update_group=enable_update_group,
    )
    factory = build_per_iteration_factory_v4_capable(
        device_name=DEVICE_NAME,
        router_id=BAG012_ROUTER_ID,
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
    )
    return test_config_for_bgp_plus_plus_on_ebb_arista_performance_scaling(
        test_config_name=name,
        device_name=DEVICE_NAME,
        host_driver_args=None,
        oss_mock_device_data=None,
        host_os_type_map={DEVICE_NAME: taac_types.DeviceOsType.ARISTA_FBOSS},
        ixia_interface_mimic_ebgp=IXIA_INTERFACE_MIMIC_EBGP,
        ixia_interface_mimic_ibgp=IXIA_INTERFACE_MIMIC_IBGP,
        direct_ixia_connections=[
            DirectIxiaConnection(
                interface=IXIA_INTERFACE_MIMIC_EBGP,
                ixia_chassis_ip=IXIA_CHASSIS_IP,
                ixia_port=IXIA_PORT_EBGP,
            ),
            DirectIxiaConnection(
                interface=IXIA_INTERFACE_MIMIC_IBGP,
                ixia_chassis_ip=IXIA_CHASSIS_IP,
                ixia_port=IXIA_PORT_IBGP,
            ),
        ],
        egress_peer_counts=BAG012_ASH6_PERFORMANCE_SCALING_EGRESS_PEER_COUNTS,
        prefix_count=BAG012_ASH6_PERFORMANCE_SCALING_PREFIX_COUNT,
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


BAG012_ASH6_PERFORMANCE_SCALING_TEST_CONFIG = (
    create_bag012_ash6_performance_scaling_test_config()
)

# =============================================================================
# _UPDATE_GROUP variants — same playbooks, but with BGP++ update_group +
# enableSerializeGroupPdu (per D100093369) patched into
# /mnt/flash/bgpcpp_config during BGP++ deployment so the conveyor qualifies
# the update-group BGP++ feature alongside the baseline.
# =============================================================================
BAG012_ASH6_CONVEYOR_TEST_UPDATE_GROUP_CONFIG = create_bag012_ash6_conveyor_test_config(
    enable_update_group=True,
)
BAG012_ASH6_CONSTANT_ATTRIBUTE_STORAGE_TEST_UPDATE_GROUP_CONFIG = (
    create_bag012_ash6_constant_attribute_storage_test_config(
        enable_update_group=True,
    )
)
BAG012_ASH6_QUEUE_MEMORY_MONITOR_TEST_UPDATE_GROUP_CONFIG = (
    create_bag012_ash6_queue_memory_monitor_test_config(
        enable_update_group=True,
    )
)
BAG012_ASH6_PERFORMANCE_SCALING_TEST_UPDATE_GROUP_CONFIG = (
    create_bag012_ash6_performance_scaling_test_config(
        enable_update_group=True,
    )
)


# =============================================================================
# BGP++ Bounded ECMP Sets on bag012.ash6 conveyor.
# Converted from EB02-ARISTA_PERFORMANCE_SCALING_TEST_9_BOUNDED_ECMP_SETS: the
# same upstream factory, retargeted to bag012.ash6 (IXIA ports 7/7 eBGP, 7/8
# iBGP). Device setup runs through netcastle's MANAGED shell (no raw SSH) — the
# factory patches /mnt/flash/bgpcpp_config + /usr/sbin/run_bgpcpp.sh and bounces
# the Bgp daemon via create_arista_daemon_control_task. The DUT runs with BGP++
# update_group enabled.
# =============================================================================
BAG012_ASH6_BOUNDED_ECMP_PEER_COUNT: int = 128
BAG012_ASH6_BOUNDED_ECMP_PREFIX_COUNT: int = 5000


def create_bag012_ash6_bounded_ecmp_sets_test_config() -> taac_types.TestConfig:
    """Bounded-ECMP-sets TestConfig for bag012.ash6 conveyor.

    Verifies BGP++ ECMP-set bounding at production peer scale (128 EBGP + 128
    IBGP per AFI) with update_group enabled. Targets bag012.ash6 (IXIA ports
    7/7 eBGP, 7/8 iBGP).

    Device setup uses the standard ``get_update_packing_setup_tasks`` helper --
    the same path Constant Attribute Storage / Queue Memory Monitor / Update
    Packing use -- so the configerator bgpcpp_config is deployed cleanly
    (BgpTcpdump disable, pre-IXIA interface config, control plane + ACLs,
    interface secondary IPs, config validator gate, OpenR profile handling,
    iptables flush) instead of patching the image's leftover config in place.

    Because bounded ECMP brings up IPv4 sessions too (most conveyor tests are
    validated IPv6-only), it passes ``v4_peer_start_offset=IXIA_IPV4_START_OFFSET``
    so the generated v4 peers align with the device's v4 secondary IPs and the
    bounded-ECMP IXIA-side addressing (v4 device gateways from ``.10``; v6 from
    ``::10`` which already matches the default offset 16).

    Returns:
        TestConfig object configured for bag012.ash6
    """
    setup_tasks = get_update_packing_setup_tasks(
        device_name=DEVICE_NAME,
        bgp_asn=BAG012_EOS_BGP_AS,
        ixia_interface_mimic_ebgp=IXIA_INTERFACE_MIMIC_EBGP,
        ixia_interface_mimic_ibgp=IXIA_INTERFACE_MIMIC_IBGP,
        ebgp_peer_count=BAG012_ASH6_BOUNDED_ECMP_PEER_COUNT,
        ibgp_peer_count=BAG012_ASH6_BOUNDED_ECMP_PEER_COUNT,
        ebgp_remote_as=EBGP_REMOTE_AS,
        ibgp_remote_as=IBGP_REMOTE_AS,
        ixia_ebgp_ic_parent_network_v6=IXIA_EBGP_IC_PARENT_NETWORK_V6,
        ixia_ibgp_ic_parent_network_v6=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
        # Dual-stack: bounded ECMP runs v4 + v6 peers on both interfaces.
        ixia_ebgp_ic_parent_network_v4=IXIA_EBGP_IC_PARENT_NETWORK_V4,
        ixia_ibgp_ic_parent_network_v4=IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
        router_id=BAG012_ROUTER_ID,
        bgpcpp_configerator_path=BGPCPP_CONFIGERATOR_PATH,
        profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
        # Align v4 peers with the device v4 secondary IPs + IXIA .10 layout.
        v4_peer_start_offset=IXIA_IPV4_START_OFFSET,
        # DUT runs with BGP++ update_group enabled.
        enable_update_group=True,
    )

    return test_config_for_bgp_plus_plus_on_ebb_arista_bounded_ecmp_sets(
        test_config_name="BAG012_ASH6_BGP_BOUNDED_ECMP_SETS_CONVEYOR_TEST_UPDATE_GROUP",
        device_name=DEVICE_NAME,
        ixia_interface_mimic_ebgp=IXIA_INTERFACE_MIMIC_EBGP,
        ixia_interface_mimic_ibgp=IXIA_INTERFACE_MIMIC_IBGP,
        ebgp_peer_count_v6=BAG012_ASH6_BOUNDED_ECMP_PEER_COUNT,
        ibgp_peer_count_v6=BAG012_ASH6_BOUNDED_ECMP_PEER_COUNT,
        ebgp_peer_count_v4=BAG012_ASH6_BOUNDED_ECMP_PEER_COUNT,
        ibgp_peer_count_v4=BAG012_ASH6_BOUNDED_ECMP_PEER_COUNT,
        ebgp_remote_as=EBGP_REMOTE_AS,
        ibgp_remote_as=IBGP_REMOTE_AS,
        ixia_ebgp_ic_parent_network_v6=IXIA_EBGP_IC_PARENT_NETWORK_V6,
        ixia_ebgp_ic_parent_network_v4=IXIA_EBGP_IC_PARENT_NETWORK_V4,
        ixia_ibgp_ic_parent_network_v6=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
        ixia_ibgp_ic_parent_network_v4=IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
        prefix_count=BAG012_ASH6_BOUNDED_ECMP_PREFIX_COUNT,
        direct_ixia_connections=[
            DirectIxiaConnection(
                interface=IXIA_INTERFACE_MIMIC_EBGP,
                ixia_chassis_ip=IXIA_CHASSIS_IP,
                ixia_port=IXIA_PORT_EBGP,
            ),
            DirectIxiaConnection(
                interface=IXIA_INTERFACE_MIMIC_IBGP,
                ixia_chassis_ip=IXIA_CHASSIS_IP,
                ixia_port=IXIA_PORT_IBGP,
            ),
        ],
        host_os_type_map={DEVICE_NAME: taac_types.DeviceOsType.ARISTA_FBOSS},
        # Standard device setup (configerator deploy + control plane + validator
        # + interface IPs + update_group), shared with the other bag012 conveyor
        # nodes. Passing setup_tasks skips case9's in-shell fallback.
        setup_tasks=setup_tasks,
        log_collection_timeout=600,
    )


BAG012_ASH6_BOUNDED_ECMP_SETS_TEST_UPDATE_GROUP_CONFIG = (
    create_bag012_ash6_bounded_ecmp_sets_test_config()
)
