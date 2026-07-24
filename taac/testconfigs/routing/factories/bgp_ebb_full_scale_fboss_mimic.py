# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Wrapper factories for the FBOSS EBB single-node full-scale TestConfig family.

Thin ``(physical_inventory, *, name, ...) -> TestConfig`` shims around the legacy
``test_config_for_bgp_plus_plus_ebb`` and
``test_config_for_bgp_plus_plus_ebb_with_bgp_mon`` factories in
``ebb/fboss_ebb_scale_test_config.py``. Wave 5E.4 migrates the 4
``*single_node_topology_mimic_ebb_test_full_scale*`` wrappers previously
living under ``testconfigs/routing/ebb/`` into the Wave-5 catalog framework.

Two entry points:

* ``create_bgp_ebb_full_scale_fboss_test_config`` — no BGP MON peer group
  (matches ``FSW_QZB_...`` and ``QZD_...`` non-MON legacy wrappers).
* ``create_bgp_ebb_full_scale_fboss_test_config_with_bgp_mon`` — includes the
  BGP MON peer group (matches ``FSW001_QZB_..._MON`` and ``QZD_..._FSW002``).

All "shared FBOSS EBB scale" defaults (peer-group names, ASNs, IXIA parent
networks, communities, ``ibgp_peer_scale_per_plane``, ``local_as_4_byte``,
``bgp_router_id``, and the BGP-MON defaults) are hardcoded verbatim from
the legacy wrappers so the golden manifest hash stays byte-identical. Only
the 4 policy names + the mimic interface names + optional
``direct_ixia_connections`` differ across sites, so those are the sole
overridable knobs.
"""

from taac.testconfigs.routing.ebb.fboss_ebb_scale_test_config import (
    test_config_for_bgp_plus_plus_ebb,
    test_config_for_bgp_plus_plus_ebb_with_bgp_mon,
)
from taac.testconfigs.routing.physical_inventory import (
    PhysicalInventory,
)
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
_BGP_MON_PEER_COUNT = 2

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

_BGP_MON_INGRESS_POLICY_NAME = "PROPAGATE_NOTHING_IN"
_BGP_MON_EGRESS_POLICY_NAME = "PROPAGATE_EVERYTHING_OUT"

_IBGP_PEER_SCALE_PER_PLANE = 63
_LOCAL_AS_4_BYTE = 64981
_BGP_ROUTER_ID = "129.134.63.224"


def create_bgp_ebb_full_scale_fboss_test_config(
    physical_inventory: PhysicalInventory,
    *,
    name: str,
    ixia_interface_mimic_ebgp: str,
    ixia_interface_mimic_ibgp: str,
    ebgp_ingress_policy_name: str = "EB-FA-IN",
    ebgp_egress_policy_name: str = "EB-FA-OUT",
    ibgp_ingress_policy_name: str = "EB-EB-IN",
    ibgp_egress_policy_name: str = "EB-EB-OUT",
) -> TestConfig:
    """FBOSS EBB single-node full-scale TestConfig (no BGP MON peers).

    Byte-identical to the legacy
    ``fsw_qzb_single_node_topology_mimic_ebb_test_full_scale_test_config.py``
    and ``qzd_single_node_topology_mimic_ebb_test_full_scale_test_config.py``
    depending on which ``physical_inventory`` + policy names are passed. The QZD-lab
    variant overrides the 4 policy-name kwargs to ``PROPAGATE_FSW_{SSW,RSW}_*``.
    """
    return test_config_for_bgp_plus_plus_ebb(
        test_config_name=name,
        device_name=physical_inventory.device_name,
        peergroup_ibgp_v6=_PEERGROUP_IBGP_V6,
        peergroup_ebgp_v6=_PEERGROUP_EBGP_V6,
        peergroup_ibgp_v4=_PEERGROUP_IBGP_V4,
        peergroup_ebgp_v4=_PEERGROUP_EBGP_V4,
        ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
        ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
        ibgp_remote_as=_IBGP_REMOTE_AS,
        ebgp_remote_as=_EBGP_REMOTE_AS,
        ebgp_peer_count_v4=_EBGP_PEER_COUNT_V4,
        ebgp_peer_count_v6=_EBGP_PEER_COUNT_V6,
        unqiue_prefix_limit=_UNQUE_PREFIX_LIMIT,
        total_path_limit=_TOTAL_PATH_LIMIT,
        ixia_ebgp_ic_parent_network_v6=_IXIA_EBGP_IC_PARENT_NETWORK_V6,
        ixia_ebgp_ic_parent_network_v4=_IXIA_EBGP_IC_PARENT_NETWORK_V4,
        ixia_ibgp_ic_parent_network_v6_dc_plane1=_IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
        ixia_ibgp_ic_parent_network_v6_dc_plane2=_IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE2,
        ixia_ibgp_ic_parent_network_v6_dc_plane3=_IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE3,
        ixia_ibgp_ic_parent_network_v6_dc_plane4=_IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE4,
        ixia_ibgp_ic_parent_network_v6_mp_plane1=_IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE1,
        ixia_ibgp_ic_parent_network_v6_mp_plane2=_IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE2,
        ixia_ibgp_ic_parent_network_v6_mp_plane3=_IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE3,
        ixia_ibgp_ic_parent_network_v6_mp_plane4=_IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE4,
        ixia_ibgp_ic_parent_network_v4_dc_plane1=_IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
        ixia_ibgp_ic_parent_network_v4_dc_plane2=_IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE2,
        ixia_ibgp_ic_parent_network_v4_dc_plane3=_IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE3,
        ixia_ibgp_ic_parent_network_v4_dc_plane4=_IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE4,
        ixia_ibgp_ic_parent_network_v4_mp_plane1=_IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE1,
        ixia_ibgp_ic_parent_network_v4_mp_plane2=_IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE2,
        ixia_ibgp_ic_parent_network_v4_mp_plane3=_IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE3,
        ixia_ibgp_ic_parent_network_v4_mp_plane4=_IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE4,
        ixia_ebgp_communities=_IXIA_EBGP_COMMUNITIES,
        ixia_ibgp_communities=_IXIA_IBGP_COMMUNITIES,
        ebgp_ingress_policy_name=ebgp_ingress_policy_name,
        ebgp_egress_policy_name=ebgp_egress_policy_name,
        ibgp_ingress_policy_name=ibgp_ingress_policy_name,
        ibgp_egress_policy_name=ibgp_egress_policy_name,
        ibgp_peer_scale_per_plane=_IBGP_PEER_SCALE_PER_PLANE,
        local_as_4_byte=_LOCAL_AS_4_BYTE,
        bgp_router_id=_BGP_ROUTER_ID,
    )


def create_bgp_ebb_full_scale_fboss_test_config_with_bgp_mon(
    physical_inventory: PhysicalInventory,
    *,
    name: str,
    ixia_interface_mimic_ebgp: str,
    ixia_interface_mimic_ibgp: str,
    ixia_interface_mimic_bgp_mon: str,
    direct_ixia_connections: list[DirectIxiaConnection] | None = None,
) -> TestConfig:
    """FBOSS EBB single-node full-scale TestConfig (with BGP MON peers).

    Byte-identical to the legacy
    ``fsw001_qzb_single_node_topology_mimic_ebb_test_full_scale_mon_test_config.py``
    and ``qzd_single_node_topology_mimic_ebb_test_full_scale_fsw002_test_config.py``
    depending on which ``physical_inventory`` + kwargs are passed.
    """
    return test_config_for_bgp_plus_plus_ebb_with_bgp_mon(
        test_config_name=name,
        device_name=physical_inventory.device_name,
        peergroup_ibgp_v6=_PEERGROUP_IBGP_V6,
        peergroup_ebgp_v6=_PEERGROUP_EBGP_V6,
        peergroup_ibgp_v4=_PEERGROUP_IBGP_V4,
        peergroup_ebgp_v4=_PEERGROUP_EBGP_V4,
        peergroup_bgp_mon=_PEERGROUP_BGP_MON,
        ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
        ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
        ixia_interface_mimic_bgp_mon=ixia_interface_mimic_bgp_mon,
        ibgp_remote_as=_IBGP_REMOTE_AS,
        ebgp_remote_as=_EBGP_REMOTE_AS,
        bgp_mon_remote_as=_BGP_MON_REMOTE_AS,
        ebgp_peer_count_v4=_EBGP_PEER_COUNT_V4,
        ebgp_peer_count_v6=_EBGP_PEER_COUNT_V6,
        bgp_mon_peer_count=_BGP_MON_PEER_COUNT,
        unqiue_prefix_limit=_UNQUE_PREFIX_LIMIT,
        total_path_limit=_TOTAL_PATH_LIMIT,
        ixia_ebgp_ic_parent_network_v6=_IXIA_EBGP_IC_PARENT_NETWORK_V6,
        ixia_ebgp_ic_parent_network_v4=_IXIA_EBGP_IC_PARENT_NETWORK_V4,
        ixia_ibgp_ic_parent_network_v6_dc_plane1=_IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
        ixia_ibgp_ic_parent_network_v6_dc_plane2=_IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE2,
        ixia_ibgp_ic_parent_network_v6_dc_plane3=_IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE3,
        ixia_ibgp_ic_parent_network_v6_dc_plane4=_IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE4,
        ixia_ibgp_ic_parent_network_v6_mp_plane1=_IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE1,
        ixia_ibgp_ic_parent_network_v6_mp_plane2=_IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE2,
        ixia_ibgp_ic_parent_network_v6_mp_plane3=_IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE3,
        ixia_ibgp_ic_parent_network_v6_mp_plane4=_IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE4,
        ixia_ibgp_ic_parent_network_v4_dc_plane1=_IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
        ixia_ibgp_ic_parent_network_v4_dc_plane2=_IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE2,
        ixia_ibgp_ic_parent_network_v4_dc_plane3=_IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE3,
        ixia_ibgp_ic_parent_network_v4_dc_plane4=_IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE4,
        ixia_ibgp_ic_parent_network_v4_mp_plane1=_IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE1,
        ixia_ibgp_ic_parent_network_v4_mp_plane2=_IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE2,
        ixia_ibgp_ic_parent_network_v4_mp_plane3=_IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE3,
        ixia_ibgp_ic_parent_network_v4_mp_plane4=_IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE4,
        ixia_bgp_mon_ic_parent_network=_IXIA_BGP_MON_IC_PARENT_NETWORK,
        ixia_ebgp_communities=_IXIA_EBGP_COMMUNITIES,
        ixia_ibgp_communities=_IXIA_IBGP_COMMUNITIES,
        ebgp_ingress_policy_name="EB-FA-IN",
        ebgp_egress_policy_name="EB-FA-OUT",
        ibgp_ingress_policy_name="EB-EB-IN",
        ibgp_egress_policy_name="EB-EB-OUT",
        bgp_mon_ingress_policy_name=_BGP_MON_INGRESS_POLICY_NAME,
        bgp_mon_egress_policy_name=_BGP_MON_EGRESS_POLICY_NAME,
        ibgp_peer_scale_per_plane=_IBGP_PEER_SCALE_PER_PLANE,
        local_as_4_byte=_LOCAL_AS_4_BYTE,
        bgp_router_id=_BGP_ROUTER_ID,
        direct_ixia_connections=direct_ixia_connections,
    )
