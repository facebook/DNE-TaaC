# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
BGP++ Conveyor Test Configurations for bag011.ash6.

This module contains three test configs designed for the EBB BGP++ CI/CD
conveyor pipeline, grouped by reliability tier:

1. BAG011_ASH6_BGP_RESTART_CONVEYOR_TEST (Tier 1 — 73-80% pass rate):
   - bgp_daemon_restart_test_playbook
   - bgp_cold_start_test_playbook

2. BAG011_ASH6_BGP_OSCILLATIONS_CONVEYOR_TEST (Tier 1-2 — 71-83% pass rate):
   - bgp_ebgp_session_oscillations_test_playbook
   - bgp_ibgp_tornado_plane_oscillations_test_playbook
   - bgp_ebgp_route_oscillations
   - bgp_ibgp_route_oscillations

2b. BAG011_ASH6_BGP_OSCILLATIONS_CONVEYOR_TEST_UPDATE_GROUP:
   - Same playbooks as #2, but dynamically toggles
     ``enable_update_group=True`` (which now also writes the
     ``update_group_config`` struct, per D100093369)
     via the ``set_bgp_setting_config`` setup task before running.

3. BAG011_ASH6_BGP_STABILITY_CONVEYOR_TEST (Tier 3 — <25% pass rate):
   - bgp_igp_instability_pnh_metric_oscillation_playbook
   - bgp_igp_instability_unresolvable_pnhs_playbook
   - nexthop_group_count_threshold_playbook

Update Group Variants:
  Each of the three configs above has a sibling ``*_UPDATE_GROUP`` variant
  produced by the same factory with ``enable_update_group=True`` and
  (``update_group_config`` per D100093369). The variant runs the same playbooks
  but appends a ``set_bgp_setting_config`` task to setup_tasks so the
  features are toggled on-device before any playbook runs.
   - bgp_igp_instability_pnh_metric_oscillation_playbook
   - bgp_igp_instability_unresolvable_pnhs_playbook
   - nexthop_group_count_threshold_playbook

Reliability-based grouping rationale:
  Configs are ordered by historical pass rate (excluding IXIA/infra errors,
  60-day Scuba data). Stage 1 runs the most reliable config first to
  guarantee results even if later stages fail. Tier 3 playbooks are
  isolated so their expected failures don't mask Tier 1-2 results.

  Consolidation from 5 → 3 configs saves 2 IXIA setups (~144 min).

Device: bag011.ash6
IXIA Chassis: ares1-my24520014
IXIA Ports:
- Et3/36/1 -> 7/4 (eBGP)
- Et3/36/2 -> 7/5 (iBGP)
- Et3/36/3 -> 7/6 (BGP MON)
"""

from typing import List

from taac.constants import BgpPlusPlusProfile
from taac.playbooks.playbook_definitions import (
    create_bgp_cold_start_playbook,
    create_bgp_daemon_restart_playbook,
    create_bgp_ebgp_route_oscillations_playbook,
    create_bgp_ebgp_session_oscillations_playbook,
    create_bgp_ibgp_route_oscillations_playbook,
    create_bgp_ibgp_tornado_plane_oscillations_playbook,
    create_bgp_igp_instability_pnh_metric_oscillation_playbook,
    create_bgp_igp_instability_unresolvable_pnhs_playbook,
    create_nexthop_group_count_threshold_playbook,
)
from taac.routing.ebb.ebb_bgp_plus_plus_test_config.ebb_bgp_plus_plus_conveyor.conveyor_common_tasks import (
    build_expected_peer_identity,
    get_common_setup_tasks,
    get_teardown_tasks,
)
from taac.routing.ebb.ebb_bgp_plus_plus_test_config.ebb_bgp_plus_plus_conveyor.conveyor_constants import (
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
    OPENR_LOCAL_LINK,
    OPENR_OTHER_LINK,
    PEERGROUP_IBGP_V4,
    PEERGROUP_IBGP_V6,
)
from taac.routing.ebb.ebb_bgp_plus_plus_test_config.ixia_config_for_ebb_scale import (
    create_ebb_scale_basic_port_configs,
)
from taac.utils.arista_utils import interface_name_to_short_format
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import (
    DirectIxiaConnection,
    Endpoint,
    Playbook,
    TestConfig,
)


# =============================================================================
# Device-specific configuration for bag011.ash6
# =============================================================================
DEVICE_NAME = "bag011.ash6"
IXIA_CHASSIS_IP = "2401:db00:2066:303b::3001"
BAG012_EOS_BGP_AS = 65011
SPEED = "100g-2"
BGPCPP_CONFIGERATOR_PATH = "taac/ebb_ci_cd_configs/ebb_full_scale_bgpcpp_config"
OPENR_CONFIGERATOR_PATH = "taac/ebb_ci_cd_configs/bag011_ash6_openr_config"

# IXIA interface mappings for bag011.ash6
IXIA_INTERFACE_MIMIC_EBGP = "Ethernet3/36/1"
IXIA_INTERFACE_MIMIC_IBGP = "Ethernet3/36/2"
IXIA_INTERFACE_MIMIC_BGP_MON = "Ethernet3/36/3"

# IXIA port mappings (chassis slot/port)
IXIA_PORT_EBGP = "7/4"
IXIA_PORT_IBGP = "7/5"
IXIA_PORT_BGP_MON = "7/6"

# Nexthop group threshold - fail if num_groups_configured meets or exceeds this
NEXTHOP_GROUP_THRESHOLD = 100

# Total BGP session count across all peer types
TOTAL_SESSION_COUNT = (
    EBGP_PEER_COUNT_V6
    + EBGP_PEER_COUNT_V4
    + BGP_MON_PEER_COUNT
    + IBGP_PEER_SCALE_PER_PLANE * 4  # 4 DC-site devices, IPv4 remote EB
    + IBGP_PEER_SCALE_PER_PLANE * 4  # 4 DC-site devices, IPv6 remote EB
    + IBGP_PEER_SCALE_PER_PLANE * 4  # 4 MP-site devices, IPv4 remote Mid Point
    + IBGP_PEER_SCALE_PER_PLANE * 4  # 4 MP-site devices, IPv6 remote Mid Point
)

# Sessions actually expected to ESTABLISH (excludes BGP MON peers). BGP MON
# peers (ASN 64001) legitimately stay IDLE intermittently on bag011 post-
# restart / cold-start (see R96.1 failure analysis), and the upstream bgpcpp
# configerator config does not always bring them back. Excluding them from
# BGP_SESSION_ESTABLISH_CHECK avoids spurious flakes while preserving the
# iBGP/eBGP establishment signal that actually matters.
EXPECTED_ESTABLISHED_SESSION_COUNT = TOTAL_SESSION_COUNT - BGP_MON_PEER_COUNT


def _get_setup_tasks(
    profile: BgpPlusPlusProfile = DEFAULT_PROFILE,
) -> List["taac_types.Task"]:
    """Get setup tasks for bag011.ash6."""
    return get_common_setup_tasks(
        device_name=DEVICE_NAME,
        bgp_asn=BAG012_EOS_BGP_AS,
        ixia_interface_mimic_ebgp=IXIA_INTERFACE_MIMIC_EBGP,
        ixia_interface_mimic_ibgp=IXIA_INTERFACE_MIMIC_IBGP,
        ixia_interface_mimic_bgp_mon=IXIA_INTERFACE_MIMIC_BGP_MON,
        bgpcpp_configerator_path=BGPCPP_CONFIGERATOR_PATH,
        profile=profile,
        openr_configerator_path=OPENR_CONFIGERATOR_PATH,
        openr_port_channel_member="Ethernet3/9/1",
        openr_port_channel_ipv4="10.131.97.236/31",
        openr_port_channel_link_local="fe80::eba:a7f:fd00/64",
        openr_local_link=OPENR_LOCAL_LINK,
        openr_other_link=OPENR_OTHER_LINK,
    )


def _build_test_config(
    name: str,
    playbooks: List[Playbook],
    setup_tasks: List,
    profile: BgpPlusPlusProfile = DEFAULT_PROFILE,
    enable_update_group: bool = False,
) -> TestConfig:
    """
    Build a TestConfig with common bag011.ash6 settings and the given playbooks.

    EOS Image Deployment:
        EOS image deployment is handled dynamically by TaacRunner when
        eos_image_id is passed at runtime. CI/CD conveyor passes the
        eos_image_id to TaacRunner, which deploys the image via fbpkg
        directly on the device before running setup tasks.

    Args:
        name: Test config name.
        playbooks: List of playbooks to include.
        setup_tasks: Setup tasks from _get_setup_tasks.
        profile: BGP++ profile to use. Determines whether OpenR route injection
                 is included in setup tasks.
        enable_update_group: When True, dynamically toggles the BGP++
                 ``enable_update_group`` setting on the device after the common
                 setup tasks (patches ``/mnt/flash/bgpcpp_config`` and reloads
                 the BGP daemon via the ``set_bgp_setting_config`` task).

    Returns:
        TestConfig object configured for bag011.ash6.
    """
    setup_tasks = get_common_setup_tasks(
        device_name=DEVICE_NAME,
        bgp_asn=BAG012_EOS_BGP_AS,
        ixia_interface_mimic_ebgp=IXIA_INTERFACE_MIMIC_EBGP,
        ixia_interface_mimic_ibgp=IXIA_INTERFACE_MIMIC_IBGP,
        ixia_interface_mimic_bgp_mon=IXIA_INTERFACE_MIMIC_BGP_MON,
        bgpcpp_configerator_path=BGPCPP_CONFIGERATOR_PATH,
        profile=profile,
        openr_configerator_path=OPENR_CONFIGERATOR_PATH,
        openr_port_channel_member="Ethernet3/9/1",
        openr_port_channel_ipv4="10.131.97.236/31",
        openr_port_channel_link_local="fe80::eba:a7f:fd00/64",
        openr_local_link=OPENR_LOCAL_LINK,
        openr_other_link=OPENR_OTHER_LINK,
        enable_update_group=enable_update_group,
    )
    teardown_tasks = get_teardown_tasks(
        ixia_interface_mimic_ebgp=IXIA_INTERFACE_MIMIC_EBGP,
        ixia_interface_mimic_ibgp=IXIA_INTERFACE_MIMIC_IBGP,
        ixia_interface_mimic_bgp_mon=IXIA_INTERFACE_MIMIC_BGP_MON,
        device_name=DEVICE_NAME,
    )

    return TestConfig(
        name=name,
        skip_ixia_protocol_verification=True,
        log_collection_timeout=600,
        basset_pool="dne.test",
        endpoints=[
            Endpoint(
                name=DEVICE_NAME,
                dut=True,
                ixia_ports=[
                    IXIA_INTERFACE_MIMIC_EBGP,
                    IXIA_INTERFACE_MIMIC_IBGP,
                    IXIA_INTERFACE_MIMIC_BGP_MON,
                ],
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
                    DirectIxiaConnection(
                        interface=IXIA_INTERFACE_MIMIC_BGP_MON,
                        ixia_chassis_ip=IXIA_CHASSIS_IP,
                        ixia_port=IXIA_PORT_BGP_MON,
                    ),
                ],
            ),
        ],
        host_os_type_map={DEVICE_NAME: taac_types.DeviceOsType.ARISTA_FBOSS},
        startup_checks=[],
        setup_tasks=setup_tasks,
        teardown_tasks=teardown_tasks,
        # Deprecated - define at playbook level
        # prechecks=[],
        # postchecks=[],
        # snapshot_checks=[],
        basic_port_configs=create_ebb_scale_basic_port_configs(
            device_name=DEVICE_NAME,
            ixia_interface_mimic_ebgp=IXIA_INTERFACE_MIMIC_EBGP,
            ixia_interface_mimic_ibgp=IXIA_INTERFACE_MIMIC_IBGP,
            ixia_interface_mimic_bgp_mon=IXIA_INTERFACE_MIMIC_BGP_MON,
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
        playbooks=playbooks,
    )


# =============================================================================
# Test Config 1: BGP Restart (daemon restart + cold start)
# =============================================================================
def create_bgp_restart_test_config(
    profile: BgpPlusPlusProfile = DEFAULT_PROFILE,
    enable_update_group: bool = False,
) -> TestConfig:
    """
    Test config for BGP restart playbooks:
    - bgp_daemon_restart_test_playbook
    - bgp_cold_start_test_playbook

    When ``enable_update_group`` is True, the BGP++ settings (including the
    ``update_group_config`` struct, per D100093369) are dynamically toggled on the device after
    common setup (via the ``set_bgp_setting_config`` task) and the test
    config name is suffixed with ``_UPDATE_GROUP``.
    """
    name = "BAG011_ASH6_BGP_RESTART_CONVEYOR_TEST"
    if enable_update_group:
        name += "_UPDATE_GROUP"

    setup_tasks = _get_setup_tasks(profile)
    expected_peer_identity = build_expected_peer_identity()
    return _build_test_config(
        name=name,
        profile=profile,
        enable_update_group=enable_update_group,
        setup_tasks=setup_tasks,
        playbooks=[
            create_bgp_daemon_restart_playbook(
                device_name=DEVICE_NAME,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                profile=profile,
                expected_peer_identity=expected_peer_identity,
            ),
            create_bgp_cold_start_playbook(
                device_name=DEVICE_NAME,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                profile=profile,
                expected_peer_identity=expected_peer_identity,
            ),
        ],
    )


# =============================================================================
# Test Config 2: BGP Oscillations (all session + route oscillation playbooks)
# =============================================================================
def create_bgp_oscillations_test_config(
    profile: BgpPlusPlusProfile = DEFAULT_PROFILE,
    enable_update_group: bool = False,
) -> TestConfig:
    """
    Test config for all Tier 1-2 oscillation playbooks:
    - bgp_ebgp_session_oscillations_test_playbook (79% pass rate)
    - bgp_ibgp_tornado_plane_oscillations_test_playbook (83% pass rate)
    - bgp_ebgp_route_oscillations (80% pass rate)
    - bgp_ibgp_route_oscillations (71% pass rate)

    Consolidates the former Session Oscillations and Route Oscillations
    configs. All four playbooks are historically reliable (71-83% pass
    rate excluding IXIA errors).

    When ``enable_update_group`` is True, the BGP++ settings (including the
    ``update_group_config`` struct, per D100093369) are dynamically toggled on the device after
    common setup (via the ``set_bgp_setting_config`` task) and the test
    config name is suffixed with ``_UPDATE_GROUP`` so the variant is
    distinguishable in conveyor results.
    """
    name = "BAG011_ASH6_BGP_OSCILLATIONS_CONVEYOR_TEST"
    if enable_update_group:
        name += "_UPDATE_GROUP"

    setup_tasks = _get_setup_tasks(profile)
    expected_peer_identity = build_expected_peer_identity()
    return _build_test_config(
        name=name,
        profile=profile,
        enable_update_group=enable_update_group,
        setup_tasks=setup_tasks,
        playbooks=[
            create_bgp_ebgp_session_oscillations_playbook(
                device_name=DEVICE_NAME,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                ipv4_session_count=EBGP_PEER_COUNT_V4,
                ipv6_session_count=EBGP_PEER_COUNT_V6,
                expected_established_sessions=EXPECTED_ESTABLISHED_SESSION_COUNT,
                profile=profile,
                expected_peer_identity=expected_peer_identity,
            ),
            create_bgp_ibgp_tornado_plane_oscillations_playbook(
                device_name=DEVICE_NAME,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                ipv4_sessions_per_plane=IBGP_PEER_SCALE_PER_PLANE,
                ipv6_sessions_per_plane=IBGP_PEER_SCALE_PER_PLANE,
                expected_established_sessions=EXPECTED_ESTABLISHED_SESSION_COUNT,
                profile=profile,
                expected_peer_identity=expected_peer_identity,
            ),
            create_bgp_ebgp_route_oscillations_playbook(
                device_name=DEVICE_NAME,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                expected_established_sessions=EXPECTED_ESTABLISHED_SESSION_COUNT,
                profile=profile,
            ),
            create_bgp_ibgp_route_oscillations_playbook(
                device_name=DEVICE_NAME,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                expected_established_sessions=EXPECTED_ESTABLISHED_SESSION_COUNT,
                profile=profile,
            ),
        ],
    )


# =============================================================================
# Test Config 3: BGP Stability (low-reliability IGP instability + nexthop group)
# =============================================================================
def create_bgp_stability_test_config(
    profile: BgpPlusPlusProfile = DEFAULT_PROFILE,
    enable_update_group: bool = False,
) -> TestConfig:
    """
    Test config for Tier 3 stability playbooks:
    - bgp_igp_instability_pnh_metric_oscillation_playbook (25% pass rate)
    - bgp_igp_instability_unresolvable_pnhs_playbook (insufficient data)
    - nexthop_group_count_threshold_playbook (insufficient data)

    Consolidates the former IGP Instability and Nexthop Group configs.
    These playbooks have the lowest historical pass rates and are isolated
    to prevent their expected failures from blocking higher-reliability
    playbooks in earlier conveyor stages.

    When ``enable_update_group`` is True, the BGP++ settings (including the
    ``update_group_config`` struct, per D100093369) are dynamically toggled on the device after
    common setup (via the ``set_bgp_setting_config`` task) and the test
    config name is suffixed with ``_UPDATE_GROUP``.
    """
    name = "BAG011_ASH6_BGP_STABILITY_CONVEYOR_TEST"
    if enable_update_group:
        name += "_UPDATE_GROUP"

    setup_tasks = _get_setup_tasks(profile)
    expected_peer_identity = build_expected_peer_identity()
    return _build_test_config(
        name=name,
        profile=profile,
        enable_update_group=enable_update_group,
        setup_tasks=setup_tasks,
        playbooks=[
            create_bgp_igp_instability_pnh_metric_oscillation_playbook(
                device_name=DEVICE_NAME,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                local_link=OPENR_LOCAL_LINK,
                other_link=OPENR_OTHER_LINK,
                expected_established_sessions=EXPECTED_ESTABLISHED_SESSION_COUNT,
                profile=profile,
                expected_peer_identity=expected_peer_identity,
            ),
            create_bgp_igp_instability_unresolvable_pnhs_playbook(
                device_name=DEVICE_NAME,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                tcp_dump_capture_interface=interface_name_to_short_format(
                    IXIA_INTERFACE_MIMIC_BGP_MON
                ),
                local_link=OPENR_LOCAL_LINK,
                other_link=OPENR_OTHER_LINK,
                expected_established_sessions=EXPECTED_ESTABLISHED_SESSION_COUNT,
                profile=profile,
                expected_peer_identity=expected_peer_identity,
            ),
            create_nexthop_group_count_threshold_playbook(
                device_name=DEVICE_NAME,
                nexthop_group_threshold=NEXTHOP_GROUP_THRESHOLD,
            ),
        ],
    )


# =============================================================================
# Stage-1 consolidated test config (for the dne_routing conveyor's staged layout)
# =============================================================================
def create_bag011_ash6_stage1_consolidated_test_config(
    profile: BgpPlusPlusProfile = DEFAULT_PROFILE,
    enable_update_group: bool = False,
) -> TestConfig:
    """
    Stage-1 consolidated test config for bag011.ash6 — runs every bag011-side
    playbook under ONE setup phase, except
    ``bgp_igp_instability_pnh_metric_oscillation`` which is moved to bag010 for
    cross-device wall-clock balance (bag010 and bag011 share the same full-scale
    topology, so the move is safe).

    Playbooks (8, in order — restart first to preserve clean-device-state
    precondition, then oscillations, then IGP-instability):
      1. bgp_daemon_restart                       (~30m)
      2. bgp_cold_start                           (~30m)
      3. bgp_ebgp_session_oscillations            (~1h 14m)
      4. bgp_ebgp_route_oscillations              (~1h)
      5. bgp_ibgp_tornado_plane_oscillations      (~1h)
      6. bgp_ibgp_route_oscillations              (~1h)
      7. bgp_igp_instability_unresolvable_pnhs    (~40m)
      8. nexthop_group_count_threshold            (~48m)

    NOTE: ``bgp_igp_instability_pnh_metric_oscillation`` lives on bag010 in the
    new layout — see ``bag010_ash6_test_config.create_bag010_ash6_stage1_consolidated_test_config``.

    When ``enable_update_group`` is True, the BGP++ settings (including the
    ``update_group_config`` struct, per D100093369) are dynamically toggled on
    the device after common setup (via the ``set_bgp_setting_config`` task) and
    the test config name is suffixed with ``_UPDATE_GROUP``.
    """
    name = "BAG011_ASH6_BGP_STAGE1_CONVEYOR_TEST"
    if enable_update_group:
        name += "_UPDATE_GROUP"

    setup_tasks = _get_setup_tasks(profile)
    expected_peer_identity = build_expected_peer_identity()
    return _build_test_config(
        name=name,
        profile=profile,
        enable_update_group=enable_update_group,
        setup_tasks=setup_tasks,
        playbooks=[
            create_bgp_daemon_restart_playbook(
                device_name=DEVICE_NAME,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                profile=profile,
                expected_peer_identity=expected_peer_identity,
            ),
            create_bgp_cold_start_playbook(
                device_name=DEVICE_NAME,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                profile=profile,
                expected_peer_identity=expected_peer_identity,
            ),
            create_bgp_ebgp_session_oscillations_playbook(
                device_name=DEVICE_NAME,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                ipv4_session_count=EBGP_PEER_COUNT_V4,
                ipv6_session_count=EBGP_PEER_COUNT_V6,
                expected_established_sessions=EXPECTED_ESTABLISHED_SESSION_COUNT,
                profile=profile,
                expected_peer_identity=expected_peer_identity,
            ),
            create_bgp_ebgp_route_oscillations_playbook(
                device_name=DEVICE_NAME,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                expected_established_sessions=EXPECTED_ESTABLISHED_SESSION_COUNT,
                profile=profile,
            ),
            create_bgp_ibgp_tornado_plane_oscillations_playbook(
                device_name=DEVICE_NAME,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                ipv4_sessions_per_plane=IBGP_PEER_SCALE_PER_PLANE,
                ipv6_sessions_per_plane=IBGP_PEER_SCALE_PER_PLANE,
                expected_established_sessions=EXPECTED_ESTABLISHED_SESSION_COUNT,
                profile=profile,
                expected_peer_identity=expected_peer_identity,
            ),
            create_bgp_ibgp_route_oscillations_playbook(
                device_name=DEVICE_NAME,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                expected_established_sessions=EXPECTED_ESTABLISHED_SESSION_COUNT,
                profile=profile,
            ),
            create_bgp_igp_instability_unresolvable_pnhs_playbook(
                device_name=DEVICE_NAME,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                tcp_dump_capture_interface=interface_name_to_short_format(
                    IXIA_INTERFACE_MIMIC_BGP_MON
                ),
                local_link=OPENR_LOCAL_LINK,
                other_link=OPENR_OTHER_LINK,
                expected_established_sessions=EXPECTED_ESTABLISHED_SESSION_COUNT,
                profile=profile,
                expected_peer_identity=expected_peer_identity,
            ),
            create_nexthop_group_count_threshold_playbook(
                device_name=DEVICE_NAME,
                nexthop_group_threshold=NEXTHOP_GROUP_THRESHOLD,
            ),
        ],
    )


# Export all test configs
BAG011_ASH6_BGP_RESTART_CONVEYOR_TEST_CONFIG = create_bgp_restart_test_config()
BAG011_ASH6_BGP_STAGE1_CONVEYOR_TEST_CONFIG = (
    create_bag011_ash6_stage1_consolidated_test_config()
)
BAG011_ASH6_BGP_STAGE1_CONVEYOR_TEST_UPDATE_GROUP_CONFIG = (
    create_bag011_ash6_stage1_consolidated_test_config(
        enable_update_group=True,
    )
)
BAG011_ASH6_BGP_RESTART_CONVEYOR_TEST_UPDATE_GROUP_CONFIG = (
    create_bgp_restart_test_config(
        enable_update_group=True,
    )
)
BAG011_ASH6_BGP_OSCILLATIONS_CONVEYOR_TEST_CONFIG = (
    create_bgp_oscillations_test_config()
)
BAG011_ASH6_BGP_OSCILLATIONS_CONVEYOR_TEST_UPDATE_GROUP_CONFIG = (
    create_bgp_oscillations_test_config(
        enable_update_group=True,
    )
)
BAG011_ASH6_BGP_STABILITY_CONVEYOR_TEST_CONFIG = create_bgp_stability_test_config()
BAG011_ASH6_BGP_STABILITY_CONVEYOR_TEST_UPDATE_GROUP_CONFIG = (
    create_bgp_stability_test_config(
        enable_update_group=True,
    )
)
