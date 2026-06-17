# pyre-unsafe
"""
BGP++ Update Group Test Configuration for eb03.lab.ash6.

This is used to mirror the bag test_configs run in conveyor, but mostly used for local testing and debugging.

Device: eb03.lab.ash6
IXIA Chassis: ares1-my24520014
IXIA Ports (per LLDP to ixia11.netcastle.ash6):
- Et3/1/3  -> 6/5 (eBGP)
- Et3/1/5  -> 6/6 (iBGP)
- Et3/36/1 -> 2/8 (BGP MON)
NOTE: eb03's BGP-MON uses Et3/36/1, not Et3/1/1 (the eb03 full-scale config's
Et3/1/1 is not cabled to IXIA on this device).
"""

import json
import os

from taac.constants import (
    BgpPlusPlusProfile,
    DEFAULT_LOCAL_LINK,
    DEFAULT_OPENR_START_IPV4S,
    DEFAULT_OPENR_START_IPV6S,
    DEFAULT_OTHER_LINK,
    OpenRRouteAction,
)
from taac.playbooks.playbook_definitions import (
    build_arista_ebb_scale_playbook,
)
from taac.routing.ebb.ebb_bgp_plus_plus_test_config.ebb_bgp_plus_plus_conveyor.conveyor_common_tasks import (
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
)
from taac.routing.ebb.ebb_bgp_plus_plus_test_config.ixia_config_for_ebb_scale import (
    create_ebb_scale_basic_port_configs,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import create_longevity_step
from taac.task_definitions import create_openr_route_action_task
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import DirectIxiaConnection, Endpoint, TestConfig


# =============================================================================
# Device-specific configuration for eb03.lab.ash6
# =============================================================================
DEVICE_NAME = "eb03.lab.ash6"
IXIA_CHASSIS_IP = "2401:db00:2066:303b::3001"
EB03_EOS_BGP_AS = 64981
SPEED = "100g-2"
BGPCPP_CONFIGERATOR_PATH = "taac/ebb_ci_cd_configs/ebb_full_scale_bgpcpp_config"

# Lab device credential (internal-only TAAC test environment). eb03.lab.ash6 is
# a lab device that authenticates as ``admin``; the netcastle service account
# (svc-netcastle_bot) is not authorized on it. Pass these via host_driver_args
# so device tasks log in as admin. Same shared lab account as the eb03
# full-scale config; not a real production secret. Override via env var if
# rotated. pragma: allowlist secret
_LAB_DEVICE_PASSWORD = os.environ.get("TAAC_EBB_LAB_DEVICE_PASSWORD", "dnepit")

# IXIA interface mappings for eb03.lab.ash6 (per LLDP to ixia11.netcastle.ash6).
# NOTE: Ethernet3/1/1 (the eb03 full-scale config's BGP-MON port) is NOT cabled
# to IXIA on eb03, so BGP-MON uses Ethernet3/36/1 (ixia port 2/8) instead.
IXIA_INTERFACE_MIMIC_EBGP = "Ethernet3/1/3"
IXIA_INTERFACE_MIMIC_IBGP = "Ethernet3/1/5"
IXIA_INTERFACE_MIMIC_BGP_MON = "Ethernet3/36/1"

# IXIA port mappings (chassis slot/port)
IXIA_PORT_EBGP = "6/5"
IXIA_PORT_IBGP = "6/6"
IXIA_PORT_BGP_MON = "2/8"

# OpenR: eb03 uses route-injection only (shared DEFAULT_LOCAL_LINK /
# DEFAULT_OTHER_LINK / DEFAULT_OPENR_START_* constants), matching its existing
# full-scale config. No Port-Channel and no per-device OpenR configerator
# config -- see module docstring.


def create_eb03_update_group_test_config(
    profile: BgpPlusPlusProfile = DEFAULT_PROFILE,
) -> TestConfig:
    """
    Create the Update Group test configuration for eb03.lab.ash6.

    Args:
        profile: BGP++ profile to use. Determines whether OpenR route injection
                 is included in setup tasks.

    Returns:
        TestConfig object configured for eb03.lab.ash6 with Update Group enabled.
    """
    # Pass WITHOUT_OPEN_R to the conveyor setup so it does NOT configure a
    # bag-style OpenR nexthop Port-Channel (eb03 is not cabled for one). eb03's
    # OpenR is route-injection only, appended below. The config-level ``profile``
    # (default WITH_OPEN_R) is still used for basic_port_configs route-file
    # selection, matching eb03's full-scale config.
    setup_tasks = get_common_setup_tasks(
        device_name=DEVICE_NAME,
        bgp_asn=EB03_EOS_BGP_AS,
        ixia_interface_mimic_ebgp=IXIA_INTERFACE_MIMIC_EBGP,
        ixia_interface_mimic_ibgp=IXIA_INTERFACE_MIMIC_IBGP,
        ixia_interface_mimic_bgp_mon=IXIA_INTERFACE_MIMIC_BGP_MON,
        bgpcpp_configerator_path=BGPCPP_CONFIGERATOR_PATH,
        profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
        # Update Group is the whole point of this config: enable it at setup
        # time so all playbooks run with the feature on.
        enable_update_group=True,
    )

    # eb03-style Open/R: inject routes only (no Port-Channel), exactly as eb03's
    # existing full-scale config does, using the shared DEFAULT_* link constants.
    if profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R:
        setup_tasks.append(
            create_openr_route_action_task(
                device_name=DEVICE_NAME,
                action=OpenRRouteAction.INJECT.value,
                start_ipv4s=DEFAULT_OPENR_START_IPV4S,
                start_ipv6s=DEFAULT_OPENR_START_IPV6S,
                local_link=DEFAULT_LOCAL_LINK,
                other_link=DEFAULT_OTHER_LINK,
                count=63,
                step=2,
                ixia_needed=True,
                set_outer_hostname=True,
                description="Inject Open/R routes during test setup",
            )
        )

    teardown_tasks = get_teardown_tasks(
        ixia_interface_mimic_ebgp=IXIA_INTERFACE_MIMIC_EBGP,
        ixia_interface_mimic_ibgp=IXIA_INTERFACE_MIMIC_IBGP,
        ixia_interface_mimic_bgp_mon=IXIA_INTERFACE_MIMIC_BGP_MON,
    )

    test_config = TestConfig(
        name="EB03_LAB_ASH6_BGP_TEST_UPDATE_GROUP_CONFIG",
        skip_ixia_protocol_verification=True,
        log_collection_timeout=600,
        basset_pool="dne.test",
        # eb03 is a lab device that authenticates as admin (svc-netcastle_bot is
        # not authorized on it) -- mirror the eb03 full-scale config's creds.
        host_driver_args={
            DEVICE_NAME: json.dumps(
                {"username": "admin", "password": _LAB_DEVICE_PASSWORD}
            ),
        },
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
        # eb03 is a lab device netwhoami does not resolve (role/hardware show as
        # #INVALID#), so its operating_system never becomes "EOS" and every
        # OS-gated device health check SKIPs. Override the device metadata so
        # operating_system="EOS" -- mirrors the eb03 full-scale config.
        oss_mock_device_data={
            DEVICE_NAME: taac_types.MockDeviceInfo(
                name=DEVICE_NAME,
                hardware="ARISTA_7516",
                role="EB",
                operating_system="EOS",
                dc="ash6",
                region="ash",
                asset_id=12345,
                asic="JERICHO",
                routing_protocol="BGP",
                dc_type="ONE",
                network_area="BACKBONE",
                network_area_type="BACKBONE",
                network_type="EBB",
            ),
        },
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
        playbooks=[
            # Simple playbook: a single longevity (soak) step to validate the
            # config stands up end-to-end with Update Group enabled.
            build_arista_ebb_scale_playbook(
                name="eb03_longevity_debugging",
                stages=[
                    create_steps_stage(
                        steps=[create_longevity_step(duration=20)],
                    ),
                ],
            ),
        ],
    )

    return test_config


# Export the test config (Update Group enabled at setup; skeleton playbooks)
EB03_LAB_ASH6_BGP_TEST_UPDATE_GROUP_CONFIG = create_eb03_update_group_test_config()
