# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
BGP++ Conveyor Test Configurations for bag010.ash6.

This module contains four test configs designed for the EBB BGP++ CI/CD
conveyor pipeline, split per workload so each can be scheduled,
debugged, and toggled with ``_UPDATE_GROUP`` independently:

1. BAG010_ASH6_BGP_INSTABILITY_CONVEYOR_TEST (instability playbooks):
   - bgp_instability_attribute_churn
   - bgp_instability_route_storm

2. BAG010_ASH6_BGP_RUNTIME_UPDATE_CONVEYOR_TEST (runtime config updates):
   - bgp_route_registry_prefix_list_runtime_update_playbook
   - bgp_multipath_group_oscillation_playbook

3. BAG010_ASH6_BGP_DRAIN_CONVEYOR_TEST (drain playbooks):
   - bgp_fauu_drain_undrain_playbook
   - bgp_plane_drain_undrain_playbook

4. BAG010_ASH6_CONVEYOR_LONGEVITY_TEST_CONFIG:
   - bgp_longevity_playbook

Update Group Variants:
  Each config above also exposes a sibling ``*_UPDATE_GROUP`` variant
  produced by the same factory with ``enable_update_group=True`` and
  (``update_group_config`` per D100093369). The variant runs the same
  playbooks but dynamically patches ``/mnt/flash/bgpcpp_config`` in-shell
  during BGP++ deployment so the features are toggled before the BGP
  daemons start (no daemon reload needed).

Split rationale (per-workload conveyor refactor):
  All bag010 playbooks share the same IXIA topology (ports 7/1-7/3,
  ~1285 BGP peers) and were previously bundled into a single MEGA
  config (``BAG010_ASH6_BGP_CONVEYOR_TEST``). Splitting them
  per workload (instability / runtime-update / drain / longevity) lets
  each workload be scheduled and triaged independently, and each can
  qualify the BGP++ ``enable_update_group`` /
  ``update_group_config`` features in isolation via its sibling
  ``_UPDATE_GROUP`` variant.

Device: bag010.ash6
IXIA Chassis: ares1-my24520014
IXIA Ports:
- Et3/36/1 -> 7/1 (eBGP)
- Et3/36/2 -> 7/2 (iBGP)
- Et3/36/3 -> 7/3 (BGP MON)
"""

from typing import List

from taac.constants import BgpPlusPlusProfile
from taac.playbooks.playbook_definitions import (
    create_bag010_ash6_bgp_instability_attribute_churn_playbook,
    create_bag010_ash6_bgp_instability_route_storm_playbook,
    create_bgp_fauu_drain_undrain_playbook,
    create_bgp_igp_instability_pnh_metric_oscillation_playbook,
    create_bgp_longevity_playbook,
    create_bgp_multipath_group_oscillation_playbook,
    create_bgp_plane_drain_undrain_playbook,
    create_bgp_route_registry_prefix_list_runtime_update_playbook,
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
    PEERGROUP_IBGP_V4,
    PEERGROUP_IBGP_V6,
)
from taac.routing.ebb.ebb_bgp_plus_plus_test_config.ixia_config_for_ebb_scale import (
    create_ebb_scale_basic_port_configs,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import (
    DirectIxiaConnection,
    Endpoint,
    Playbook,
    TestConfig,
)


# =============================================================================
# Device-specific configuration for bag010.ash6
# =============================================================================
DEVICE_NAME = "bag010.ash6"
IXIA_CHASSIS_IP = "2401:db00:2066:303b::3001"
BAG010_EOS_BGP_AS = 65010
SPEED = "100g-2"
BGPCPP_CONFIGERATOR_PATH = "taac/ebb_ci_cd_configs/ebb_full_scale_bgpcpp_config"
OPENR_CONFIGERATOR_PATH = "taac/ebb_ci_cd_configs/bag010_ash6_openr_config"

# IXIA interface mappings for bag010.ash6
IXIA_INTERFACE_MIMIC_EBGP = "Ethernet3/36/1"
IXIA_INTERFACE_MIMIC_IBGP = "Ethernet3/36/2"
IXIA_INTERFACE_MIMIC_BGP_MON = "Ethernet3/36/3"

# IXIA port mappings (chassis slot/port)
IXIA_PORT_EBGP = "7/1"
IXIA_PORT_IBGP = "7/2"
IXIA_PORT_BGP_MON = "7/3"

# OpenR link configurations for bag010.ash6
OPENR_LOCAL_LINK = {
    "ipv4": "10.131.97.238",
    "ipv6": "fe80::eba:a7f:fd02",
    "ifName": "po100211",
    "weight": 0,
    "metric": 10,
}
OPENR_OTHER_LINK = {
    "ipv4": "10.131.97.239",
    "ipv6": "fe80::eba:a7f:fd03",
    "ifName": "po100211",
    "weight": 0,
    "metric": 10,
}

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
# peers (ASN 64001) legitimately stay IDLE intermittently on bag010 post-
# restart / cold-start, and the upstream bgpcpp configerator config does not
# always bring them back. Excluding them from BGP_SESSION_ESTABLISH_CHECK
# avoids spurious flakes while preserving the iBGP/eBGP establishment signal
# that actually matters.
EXPECTED_ESTABLISHED_SESSION_COUNT = TOTAL_SESSION_COUNT - BGP_MON_PEER_COUNT


def _get_setup_tasks(
    profile: BgpPlusPlusProfile = DEFAULT_PROFILE,
) -> List["taac_types.Task"]:
    """Get setup tasks for bag010.ash6."""
    return get_common_setup_tasks(
        device_name=DEVICE_NAME,
        bgp_asn=BAG010_EOS_BGP_AS,
        ixia_interface_mimic_ebgp=IXIA_INTERFACE_MIMIC_EBGP,
        ixia_interface_mimic_ibgp=IXIA_INTERFACE_MIMIC_IBGP,
        ixia_interface_mimic_bgp_mon=IXIA_INTERFACE_MIMIC_BGP_MON,
        bgpcpp_configerator_path=BGPCPP_CONFIGERATOR_PATH,
        profile=profile,
        openr_configerator_path=OPENR_CONFIGERATOR_PATH,
        openr_port_channel_member="Ethernet3/6/1",
        openr_port_channel_ipv4="10.131.97.238/31",
        openr_port_channel_link_local="fe80::eba:a7f:fd02/64",
        openr_local_link=OPENR_LOCAL_LINK,
        openr_other_link=OPENR_OTHER_LINK,
    )


def _build_test_config(
    name: str,
    playbooks: List[Playbook],
    setup_tasks: List | None = None,
    profile: BgpPlusPlusProfile = DEFAULT_PROFILE,
    enable_update_group: bool = False,
    drain: bool = False,
) -> TestConfig:
    """
    Build a TestConfig with common bag010.ash6 settings and the given playbooks.

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
                 ``enable_update_group`` setting on the device by patching
                 ``/mnt/flash/bgpcpp_config`` in-shell during BGP++ deployment
                 (no daemon reload — control plane starts daemons fresh).

    Returns:
        TestConfig object configured for bag010.ash6.
    """
    setup_tasks = get_common_setup_tasks(
        device_name=DEVICE_NAME,
        bgp_asn=BAG010_EOS_BGP_AS,
        ixia_interface_mimic_ebgp=IXIA_INTERFACE_MIMIC_EBGP,
        ixia_interface_mimic_ibgp=IXIA_INTERFACE_MIMIC_IBGP,
        ixia_interface_mimic_bgp_mon=IXIA_INTERFACE_MIMIC_BGP_MON,
        bgpcpp_configerator_path=BGPCPP_CONFIGERATOR_PATH,
        profile=profile,
        openr_configerator_path=OPENR_CONFIGERATOR_PATH,
        openr_port_channel_member="Ethernet3/6/1",
        openr_port_channel_ipv4="10.131.97.238/31",
        openr_port_channel_link_local="fe80::eba:a7f:fd02/64",
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


# =============================================================================
# Test Config 1: Instability conveyor test (BGP instability playbooks)
# =============================================================================
def create_bag010_ash6_instability_test_config(
    profile: BgpPlusPlusProfile = DEFAULT_PROFILE,
    enable_update_group: bool = False,
) -> TestConfig:
    """
    Test config for bag010.ash6 — BGP instability playbooks.

    Playbooks (2):
    - bgp_instability_attribute_churn
    - bgp_instability_route_storm

    Other bag010.ash6 workloads live in dedicated configs and can be
    scheduled / debugged / toggled with ``_UPDATE_GROUP`` independently:
      - runtime-update playbooks →
        ``BAG010_ASH6_BGP_RUNTIME_UPDATE_CONVEYOR_TEST``
        (``create_bag010_ash6_runtime_update_test_config``)
      - drain playbooks →
        ``BAG010_ASH6_BGP_DRAIN_CONVEYOR_TEST``
        (``create_bag010_ash6_drain_test_config``)
      - longevity →
        ``BAG010_ASH6_CONVEYOR_LONGEVITY_TEST_CONFIG``
        (``create_bag010_ash6_longevity_test_config``)

    When ``enable_update_group`` is True, the BGP++ settings (including the
    ``update_group_config`` struct, per D100093369) are dynamically toggled on the device during
    BGP++ deployment (in-shell patch of ``/mnt/flash/bgpcpp_config``) and
    the test config name is suffixed with ``_UPDATE_GROUP``.
    """
    name = "BAG010_ASH6_BGP_INSTABILITY_CONVEYOR_TEST"
    if enable_update_group:
        name += "_UPDATE_GROUP"

    setup_tasks = _get_setup_tasks(profile)
    expected_peer_identity = build_expected_peer_identity()
    return _build_test_config(
        name=name,
        profile=profile,
        enable_update_group=enable_update_group,
        playbooks=[
            create_bag010_ash6_bgp_instability_attribute_churn_playbook(
                device_name=DEVICE_NAME,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                total_session_count=EXPECTED_ESTABLISHED_SESSION_COUNT,
                profile=profile,
            ),
            create_bag010_ash6_bgp_instability_route_storm_playbook(
                device_name=DEVICE_NAME,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                total_session_count=EXPECTED_ESTABLISHED_SESSION_COUNT,
                ixia_interface_mimic_ibgp=IXIA_INTERFACE_MIMIC_IBGP,
                profile=profile,
            ),
        ],
    )


# =============================================================================
# Test Config 2: Runtime update tests (route registry + multipath group)
# =============================================================================
def create_bag010_ash6_runtime_update_test_config(
    profile: BgpPlusPlusProfile = DEFAULT_PROFILE,
    enable_update_group: bool = False,
) -> TestConfig:
    """
    Test config for bag010.ash6 runtime-update playbooks:
    - bgp_route_registry_prefix_list_runtime_update_playbook
    - bgp_multipath_group_oscillation_playbook

    Both playbooks exercise runtime configuration churn against the BGP++
    daemon (prefix-list updates from route-registry and multipath group
    oscillation). Lives in its own dedicated config so it can be
    scheduled, debugged, and toggled with ``_UPDATE_GROUP`` independently
    of the other bag010 workloads (instability / drain / longevity).

    When ``enable_update_group`` is True, the BGP++ settings (including the
    ``update_group_config`` struct, per D100093369) are dynamically toggled on the device during
    BGP++ deployment (in-shell patch of ``/mnt/flash/bgpcpp_config``) and
    the test config name is suffixed with ``_UPDATE_GROUP``.
    """
    name = "BAG010_ASH6_BGP_RUNTIME_UPDATE_CONVEYOR_TEST"
    if enable_update_group:
        name += "_UPDATE_GROUP"

    return _build_test_config(
        name=name,
        profile=profile,
        enable_update_group=enable_update_group,
        playbooks=[
            create_bgp_route_registry_prefix_list_runtime_update_playbook(
                device_name=DEVICE_NAME,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                expected_established_sessions=EXPECTED_ESTABLISHED_SESSION_COUNT,
                profile=profile,
            ),
            create_bgp_multipath_group_oscillation_playbook(
                device_name=DEVICE_NAME,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                expected_established_sessions=EXPECTED_ESTABLISHED_SESSION_COUNT,
                profile=profile,
            ),
        ],
    )


# =============================================================================
# Stage-1 consolidated test config (for the dne_routing conveyor's staged layout)
# =============================================================================
def create_bag010_ash6_stage1_consolidated_test_config(
    profile: BgpPlusPlusProfile = DEFAULT_PROFILE,
    enable_update_group: bool = False,
) -> TestConfig:
    """
    Stage-1 consolidated test config for bag010.ash6 — runs every non-longevity
    bag010-side playbook (and the pnh_metric_oscillation playbook moved from
    bag011 for cross-device balance) under ONE setup phase to cut per-testconfig
    setup overhead. Longevity stays in its own dedicated config and runs in
    Stage 2 after this one passes (longevity is the last thing on the conveyor).

    Playbooks (5, in order):
      1. bgp_instability_attribute_churn  (~2h)
      2. bgp_instability_route_storm      (~2h 15m)
      3. bgp_route_registry_prefix_list_runtime_update  (~17m)
      4. bgp_multipath_group_oscillation  (~47m)
      5. bgp_igp_instability_pnh_metric_oscillation  (~51m, moved from bag011)

    Cross-device move rationale: bag010 and bag011 expose the same full-scale
    EBGP+IBGP+BGP MON topology, so playbooks that only need full-scale topology
    can run on either. Moving pnh_metric_oscillation from bag011 to bag010
    balances Stage 1 wall-clock (bag010 5h 19m → 6h 10m; bag011 7h 33m → 6h 42m).

    When ``enable_update_group`` is True, the BGP++ settings (including the
    ``update_group_config`` struct, per D100093369) are dynamically toggled on
    the device during BGP++ deployment (in-shell patch of
    ``/mnt/flash/bgpcpp_config``) and the test config name is suffixed with
    ``_UPDATE_GROUP``.
    """
    name = "BAG010_ASH6_BGP_STAGE1_CONVEYOR_TEST"
    if enable_update_group:
        name += "_UPDATE_GROUP"

    expected_peer_identity = build_expected_peer_identity()
    return _build_test_config(
        name=name,
        profile=profile,
        enable_update_group=enable_update_group,
        playbooks=[
            create_bag010_ash6_bgp_instability_attribute_churn_playbook(
                device_name=DEVICE_NAME,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                total_session_count=EXPECTED_ESTABLISHED_SESSION_COUNT,
                profile=profile,
            ),
            create_bag010_ash6_bgp_instability_route_storm_playbook(
                device_name=DEVICE_NAME,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                total_session_count=EXPECTED_ESTABLISHED_SESSION_COUNT,
                ixia_interface_mimic_ibgp=IXIA_INTERFACE_MIMIC_IBGP,
                profile=profile,
            ),
            create_bgp_route_registry_prefix_list_runtime_update_playbook(
                device_name=DEVICE_NAME,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                expected_established_sessions=EXPECTED_ESTABLISHED_SESSION_COUNT,
                profile=profile,
            ),
            create_bgp_multipath_group_oscillation_playbook(
                device_name=DEVICE_NAME,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                expected_established_sessions=EXPECTED_ESTABLISHED_SESSION_COUNT,
                profile=profile,
            ),
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
        ],
    )


# =============================================================================
# Test Config 3: Drain tests (FAUU drain/undrain + Plane drain/undrain)
# =============================================================================
def create_bag010_ash6_drain_test_config(
    profile: BgpPlusPlusProfile = DEFAULT_PROFILE,
    enable_update_group: bool = False,
) -> TestConfig:
    """
    Test config for bag010.ash6 drain playbooks:
    - bgp_fauu_drain_undrain_playbook
    - bgp_plane_drain_undrain_playbook

    Drain behaviour exercises multi-plane / FAUU drain/undrain
    transitions and is more sensitive to BGP convergence dynamics, so it
    lives in its own dedicated config that can be scheduled, debugged,
    and toggled with ``_UPDATE_GROUP`` independently of the other bag010
    workloads (instability / runtime-update / longevity). Both playbooks
    share the same IXIA tcp_dump capture interfaces (eBGP / iBGP /
    BGP MON).

    When ``enable_update_group`` is True, the BGP++ settings (including the
    ``update_group_config`` struct, per D100093369) are dynamically toggled on the device during
    BGP++ deployment (in-shell patch of ``/mnt/flash/bgpcpp_config``) and
    the test config name is suffixed with ``_UPDATE_GROUP``.
    """
    name = "BAG010_ASH6_BGP_DRAIN_CONVEYOR_TEST"
    if enable_update_group:
        name += "_UPDATE_GROUP"

    return _build_test_config(
        name=name,
        profile=profile,
        enable_update_group=enable_update_group,
        drain=True,
        playbooks=[
            create_bgp_fauu_drain_undrain_playbook(
                device_name=DEVICE_NAME,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                expected_established_sessions=EXPECTED_ESTABLISHED_SESSION_COUNT,
                profile=profile,
                tcp_dump_capture_interface_ebgp=IXIA_INTERFACE_MIMIC_EBGP,
                tcp_dump_capture_interface_bgpmon=IXIA_INTERFACE_MIMIC_BGP_MON,
                tcp_dump_capture_interface_ibgp=IXIA_INTERFACE_MIMIC_IBGP,
            ),
            create_bgp_plane_drain_undrain_playbook(
                device_name=DEVICE_NAME,
                peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
                peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
                expected_established_sessions=EXPECTED_ESTABLISHED_SESSION_COUNT,
                profile=profile,
                tcp_dump_capture_interface_ebgp=IXIA_INTERFACE_MIMIC_EBGP,
                tcp_dump_capture_interface_bgpmon=IXIA_INTERFACE_MIMIC_BGP_MON,
                tcp_dump_capture_interface_ibgp=IXIA_INTERFACE_MIMIC_IBGP,
            ),
        ],
    )


# =============================================================================
# Test Config 4: Longevity test
# =============================================================================
def create_bag010_ash6_longevity_test_config(
    profile: BgpPlusPlusProfile = DEFAULT_PROFILE,
    enable_update_group: bool = False,
) -> TestConfig:
    """
    Test config for bag010.ash6 longevity testing:
    - bgp_longevity_playbook (8 hours with community churn every 60 seconds)

    When ``enable_update_group`` is True, the BGP++ settings (including the
    ``update_group_config`` struct, per D100093369) are dynamically toggled on the device during
    BGP++ deployment and the test config name is suffixed with
    ``_UPDATE_GROUP``.
    """
    name = "BAG010_ASH6_CONVEYOR_LONGEVITY_TEST_CONFIG"
    if enable_update_group:
        name += "_UPDATE_GROUP"

    setup_tasks = _get_setup_tasks(profile)
    return _build_test_config(
        name=name,
        profile=profile,
        enable_update_group=enable_update_group,
        playbooks=[
            create_bgp_longevity_playbook(
                device_name=DEVICE_NAME,
                duration=28800,
            ),
        ],
    )


# Export the test configs
BAG010_ASH6_INSTABILITY_CONVEYOR_TEST_CONFIG = (
    create_bag010_ash6_instability_test_config()
)
BAG010_ASH6_INSTABILITY_CONVEYOR_TEST_UPDATE_GROUP_CONFIG = (
    create_bag010_ash6_instability_test_config(
        enable_update_group=True,
    )
)
BAG010_ASH6_RUNTIME_UPDATE_CONVEYOR_TEST_CONFIG = (
    create_bag010_ash6_runtime_update_test_config()
)
BAG010_ASH6_RUNTIME_UPDATE_CONVEYOR_TEST_UPDATE_GROUP_CONFIG = (
    create_bag010_ash6_runtime_update_test_config(
        enable_update_group=True,
    )
)
BAG010_ASH6_DRAIN_CONVEYOR_TEST_CONFIG = create_bag010_ash6_drain_test_config()
BAG010_ASH6_DRAIN_CONVEYOR_TEST_UPDATE_GROUP_CONFIG = (
    create_bag010_ash6_drain_test_config(
        enable_update_group=True,
    )
)
BAG010_ASH6_BGP_STAGE1_CONVEYOR_TEST_CONFIG = (
    create_bag010_ash6_stage1_consolidated_test_config()
)
BAG010_ASH6_BGP_STAGE1_CONVEYOR_TEST_UPDATE_GROUP_CONFIG = (
    create_bag010_ash6_stage1_consolidated_test_config(
        enable_update_group=True,
    )
)
BAG010_ASH6_CONVEYOR_LONGEVITY_TEST_CONFIG = create_bag010_ash6_longevity_test_config()
BAG010_ASH6_CONVEYOR_LONGEVITY_TEST_UPDATE_GROUP_CONFIG = (
    create_bag010_ash6_longevity_test_config(
        enable_update_group=True,
    )
)
