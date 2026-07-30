# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Wrapper factory for the ``ARISTA_MIMIC`` EBB full-scale TestConfig family.

Thin ``(physical_inventory, *, name, ...) -> TestConfig`` shim around the legacy
``test_config_for_bgp_plus_plus_on_ebb_arista_with_bgp_mon`` factory in
``ebb/arista_ebb_scale_test_config.py``. Wave 5E.2 migrates the 4
wrappers previously living at
``testconfigs/routing/ebb/*arista_mimic_ebb_test_full_scale*`` into the
Wave-5 lifecycle framework.

The wrapper hardcodes every "shared EBB scale" default (peer-group
names, ASNs, IXIA parent networks, communities, policy names,
``ibgp_peer_scale_per_plane``, ``local_as_4_byte``, ``bgp_router_id``)
to their legacy values, matching all 4 legacy wrappers verbatim. The
sibling ``util/bgp_ebb_constants.py`` module has drifted defaults
(``IBGP_PEER_SCALE_PER_PLANE=62`` vs the legacy ``63``;
``BGP_MON_PEER_COUNT=2`` while two of the legacy wrappers use ``0``),
so reusing those constants would break the golden manifest hash.
"""

from taac.abstractions.physical_inventory import PhysicalInventory
from taac.constants import BgpPlusPlusProfile
from taac.testconfigs.routing.ebb.arista_ebb_scale_test_config import (
    test_config_for_bgp_plus_plus_on_ebb_arista_with_bgp_mon,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import DirectIxiaConnection, TestConfig


# ─── Legacy constants preserved verbatim for byte-identity ────────────────
_PEERGROUP_IBGP_V6 = "EB-EB-V6"
_PEERGROUP_EBGP_V6 = "EB-FA-V6"
_PEERGROUP_IBGP_V4 = "EB-EB-V4"
_PEERGROUP_EBGP_V4 = "EB-FA-V4"
_PEERGROUP_BGP_MON = "BGP-MON"

_IBGP_REMOTE_AS = 64981
_EBGP_REMOTE_AS = 65334
_BGP_MON_REMOTE_AS = 64001

_EBGP_PEER_COUNT_V4 = 140
_EBGP_PEER_COUNT_V6 = 140

_UNQUE_PREFIX_LIMIT = 130000
_TOTAL_PATH_LIMIT = 20000000

_IXIA_EBGP_IC_PARENT_NETWORK_V6 = "2401:db00:e50d:11:8"
_IXIA_EBGP_IC_PARENT_NETWORK_V4 = "10.163.28"
_IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1 = "2401:db00:e50d:11:9"
_IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE2 = "2401:db00:e50d:11:10"
_IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE3 = "2401:db00:e50d:11:11"
_IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE4 = "2401:db00:e50d:11:12"
_IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE1 = "2401:db00:e50d:11:13"
_IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE2 = "2401:db00:e50d:11:14"
_IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE3 = "2401:db00:e50d:11:15"
_IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE4 = "2401:db00:e50d:11:16"
_IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1 = "10.164.28"
_IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE2 = "10.165.28"
_IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE3 = "10.166.28"
_IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE4 = "10.167.28"
_IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE1 = "10.168.28"
_IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE2 = "10.169.28"
_IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE3 = "10.170.28"
_IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE4 = "10.171.28"
_IXIA_BGP_MON_IC_PARENT_NETWORK = "2401:db00:e50d:22:a"

_IXIA_EBGP_COMMUNITIES = [
    "65529:39744",
    "65530:50700",
    "65527:36706",
    "65520:523",
    "65140:65527",
    "65060:10012",
]
_IXIA_IBGP_COMMUNITIES = [
    "65060:10012",
    "65140:65529",
    "65520:503",
    "65529:11610",
    "65529:39744",
    "65530:50300",
    "65530:50320",
    "65530:50800",
]

_EBGP_INGRESS_POLICY_NAME = "EB-FA-IN"
_EBGP_EGRESS_POLICY_NAME = "EB-FA-OUT"
_IBGP_INGRESS_POLICY_NAME = "EB-EB-IN"
_IBGP_EGRESS_POLICY_NAME = "EB-EB-OUT"
_BGP_MON_INGRESS_POLICY_NAME = "PROPAGATE_NOTHING_IN"
_BGP_MON_EGRESS_POLICY_NAME = "PROPAGATE_EVERYTHING_OUT"

_IBGP_PEER_SCALE_PER_PLANE = 63
_LOCAL_AS_4_BYTE = 64981
_BGP_ROUTER_ID = "129.134.63.224"


def create_bgp_ebb_full_scale_mimic_test_config(
    physical_inventory: PhysicalInventory,
    *,
    name: str,
    ixia_interface_mimic_ebgp: str,
    ixia_interface_mimic_ibgp: str,
    ixia_interface_mimic_bgp_mon: str,
    bgp_mon_peer_count: int = 2,
    profile: BgpPlusPlusProfile | None = None,
    direct_ixia_connections: list[DirectIxiaConnection] | None = None,
) -> TestConfig:
    """Full-scale Arista EBB mimic TestConfig (with BGP MON peers).

    Byte-identical to the legacy
    ``arista_mimic_ebb_test_full_scale_test_config.py`` and its three
    ``eb0{1,3,4}_arista_mimic_ebb_test_full_scale_*_test_config.py``
    siblings, depending on which ``physical_inventory`` + kwargs are passed.

    ``physical_inventory.host_driver_args`` / ``physical_inventory.oss_mock_device_data`` are
    forwarded verbatim when populated (lab-box physical inventories); production
    physical inventories leave both ``None`` (matching the legacy shared wrapper
    which relied on the underlying factory's default omission).

    ``profile=None`` (the default) preserves the legacy shared-wrapper
    behavior of falling through to the underlying factory's default
    (``BGP_PLUS_PLUS_WITHOUT_OPEN_R``); the eb0x wrappers all pass
    ``BGP_PLUS_PLUS_WITH_OPEN_R`` explicitly.
    """
    device_name = physical_inventory.device_name
    host_os_type_map = (
        {device_name: taac_types.DeviceOsType.ARISTA_FBOSS}
        if physical_inventory.oss_mock_device_data is not None
        else None
    )

    kwargs: dict = {
        "test_config_name": name,
        "device_name": device_name,
        "peergroup_ibgp_v6": _PEERGROUP_IBGP_V6,
        "peergroup_ebgp_v6": _PEERGROUP_EBGP_V6,
        "peergroup_ibgp_v4": _PEERGROUP_IBGP_V4,
        "peergroup_ebgp_v4": _PEERGROUP_EBGP_V4,
        "peergroup_bgp_mon": _PEERGROUP_BGP_MON,
        "ixia_interface_mimic_ebgp": ixia_interface_mimic_ebgp,
        "ixia_interface_mimic_ibgp": ixia_interface_mimic_ibgp,
        "ixia_interface_mimic_bgp_mon": ixia_interface_mimic_bgp_mon,
        "ibgp_remote_as": _IBGP_REMOTE_AS,
        "ebgp_remote_as": _EBGP_REMOTE_AS,
        "bgp_mon_remote_as": _BGP_MON_REMOTE_AS,
        "ebgp_peer_count_v4": _EBGP_PEER_COUNT_V4,
        "ebgp_peer_count_v6": _EBGP_PEER_COUNT_V6,
        "bgp_mon_peer_count": bgp_mon_peer_count,
        "unqiue_prefix_limit": _UNQUE_PREFIX_LIMIT,
        "total_path_limit": _TOTAL_PATH_LIMIT,
        "ixia_ebgp_ic_parent_network_v6": _IXIA_EBGP_IC_PARENT_NETWORK_V6,
        "ixia_ebgp_ic_parent_network_v4": _IXIA_EBGP_IC_PARENT_NETWORK_V4,
        "ixia_ibgp_ic_parent_network_v6_dc_plane1": _IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
        "ixia_ibgp_ic_parent_network_v6_dc_plane2": _IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE2,
        "ixia_ibgp_ic_parent_network_v6_dc_plane3": _IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE3,
        "ixia_ibgp_ic_parent_network_v6_dc_plane4": _IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE4,
        "ixia_ibgp_ic_parent_network_v6_mp_plane1": _IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE1,
        "ixia_ibgp_ic_parent_network_v6_mp_plane2": _IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE2,
        "ixia_ibgp_ic_parent_network_v6_mp_plane3": _IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE3,
        "ixia_ibgp_ic_parent_network_v6_mp_plane4": _IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE4,
        "ixia_ibgp_ic_parent_network_v4_dc_plane1": _IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
        "ixia_ibgp_ic_parent_network_v4_dc_plane2": _IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE2,
        "ixia_ibgp_ic_parent_network_v4_dc_plane3": _IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE3,
        "ixia_ibgp_ic_parent_network_v4_dc_plane4": _IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE4,
        "ixia_ibgp_ic_parent_network_v4_mp_plane1": _IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE1,
        "ixia_ibgp_ic_parent_network_v4_mp_plane2": _IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE2,
        "ixia_ibgp_ic_parent_network_v4_mp_plane3": _IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE3,
        "ixia_ibgp_ic_parent_network_v4_mp_plane4": _IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE4,
        "ixia_bgp_mon_ic_parent_network": _IXIA_BGP_MON_IC_PARENT_NETWORK,
        "ixia_ebgp_communities": _IXIA_EBGP_COMMUNITIES,
        "ixia_ibgp_communities": _IXIA_IBGP_COMMUNITIES,
        "ebgp_ingress_policy_name": _EBGP_INGRESS_POLICY_NAME,
        "ebgp_egress_policy_name": _EBGP_EGRESS_POLICY_NAME,
        "ibgp_ingress_policy_name": _IBGP_INGRESS_POLICY_NAME,
        "ibgp_egress_policy_name": _IBGP_EGRESS_POLICY_NAME,
        "bgp_mon_ingress_policy_name": _BGP_MON_INGRESS_POLICY_NAME,
        "bgp_mon_egress_policy_name": _BGP_MON_EGRESS_POLICY_NAME,
        "ibgp_peer_scale_per_plane": _IBGP_PEER_SCALE_PER_PLANE,
        "local_as_4_byte": _LOCAL_AS_4_BYTE,
        "bgp_router_id": _BGP_ROUTER_ID,
        "oss_mock_device_data": physical_inventory.oss_mock_device_data,
        "host_os_type_map": host_os_type_map,
        "host_driver_args": physical_inventory.host_driver_args,
        "direct_ixia_connections": direct_ixia_connections,
    }
    if profile is not None:
        kwargs["profile"] = profile

    return test_config_for_bgp_plus_plus_on_ebb_arista_with_bgp_mon(**kwargs)
