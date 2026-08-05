# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Physical inventories for routing FBOSS and DCN testbeds."""

from taac.abstractions.physical_inventory.physical_inventory import (
    PhysicalInventory,
)


_EBB_BGPCPP_PATH = "taac/ebb_ci_cd_configs/ebb_full_scale_bgpcpp_config"
IXIA11_ASH6 = "2401:db00:2066:303b::3001"


def _ebb_peer_groups() -> dict[str, str]:
    return {
        "ibgp_v6": "EB-EB-V6",
        "ebgp_v6": "EB-FA-V6",
        "ibgp_v4": "EB-EB-V4",
        "ebgp_v4": "EB-FA-V4",
    }


# ─── FA verify physical_inventory (FA001-UU001 in QZD1) ──────────────────────────────
# ``fa001-uu001.qzd1`` is a Fabric-Aggregator uplink used by the BGP++
# computational-load and constant-attribute-storage feature verify configs.
# It uses FAUU-style peer-group names (PEERGROUP_FAUU_*) rather than the
# EBB EB-EB/EB-FA scheme, so ``peer_groups`` is left empty here — a
# future ``fa_uu_peer_groups()`` helper will populate it when Wave 5B
# migrates the FA verify factory.
FA001_UU001_QZD1 = PhysicalInventory(
    usage=frozenset({"adhoc"}),
    device_name="fa001-uu001.qzd1",
    primary_ixia_chassis_ip="",
    # dut_bgp_as = ibgp_remote_as (iBGP is same-AS): AS 65271 (FAUU-FADU pool).
    dut_bgp_as=65271,
    extras={
        "dut_iface_ebgp": "eth6/13/1",
        "dut_iface_ibgp": "eth6/15/1",
    },
)


# ─── FBOSS EBB single-node physical inventories (FSW / QZD family) ────────────────────
# Four sibling physical inventories built from the same ``test_config_for_bgp_plus_plus_ebb``
# / ``..._with_bgp_mon`` factories, each pinning a different DUT. The QZD
# testconfigs uniformly route to the ASH6 IXIA chassis (verbatim from legacy
# ``direct_ixia_connections``); the non-MON siblings do not declare direct
# connections at all, so their ports are captured via ``extras`` for Wave 5B
# to consume.
FSW001_QZB = PhysicalInventory(
    usage=frozenset({"adhoc"}),
    device_name="fsw001.p003.f01.qzb1",
    primary_ixia_chassis_ip=IXIA11_ASH6,
    ixia_ports=[
        ("eth7/1/1", "1/7"),  # eBGP
        ("eth7/3/1", "1/8"),  # iBGP
        ("eth7/5/1", "4/3"),  # BGP-MON
    ],
    dut_bgp_as=64981,
    bgpcpp_configerator_path=_EBB_BGPCPP_PATH,
    peer_groups=_ebb_peer_groups(),
)

FSW_QZB = PhysicalInventory(
    usage=frozenset({"adhoc"}),
    device_name="fsw001.p003.f01.qzb1",
    # Legacy ``fsw_qzb_...`` testconfig declares no ``direct_ixia_connections``.
    # Same physical DUT as ``FSW001_QZB`` above; a separate PhysicalInventory instance
    # because it drives a different testconfig (no BGP-MON, different playbook
    # scope) and Wave 5B may layer distinct factory args on top.
    primary_ixia_chassis_ip="",
    dut_bgp_as=64981,
    bgpcpp_configerator_path=_EBB_BGPCPP_PATH,
    peer_groups=_ebb_peer_groups(),
    extras={
        "dut_iface_ebgp": "eth7/1/1",
        "dut_iface_ibgp": "eth7/3/1",
    },
)

QZD_FSW002 = PhysicalInventory(
    usage=frozenset({"adhoc"}),
    device_name="fsw002.p003.f01.qzb1",
    primary_ixia_chassis_ip="",
    dut_bgp_as=64981,
    bgpcpp_configerator_path=_EBB_BGPCPP_PATH,
    peer_groups=_ebb_peer_groups(),
    extras={
        "dut_iface_ebgp": "eth7/1/1",
        "dut_iface_ibgp": "eth7/3/1",
        "dut_iface_bgp_mon": "eth7/5/1",
    },
)

QZD_LAB = PhysicalInventory(
    usage=frozenset({"adhoc"}),
    # Same DUT name as ``CTE_UCMP_STAND_ALONE_PHYSICAL_INVENTORY`` — the CTE UCMP config
    # reserves this device for confed-peer stand-alone testing, while
    # ``QZD_LAB`` uses it as an EBB single-node full-scale DUT. Separate
    # logical inventory because peer-groups / route-maps differ (uses
    # PROPAGATE_FSW_SSW_* / PROPAGATE_FSW_RSW_* policy names in the legacy
    # source, distinct from EBB EB-FA-IN/OUT).
    device_name="fsw003.p003.f01.qzd1",
    primary_ixia_chassis_ip="",
    dut_bgp_as=64981,
    bgpcpp_configerator_path=_EBB_BGPCPP_PATH,
    peer_groups=_ebb_peer_groups(),
    extras={
        "dut_iface_ebgp": "eth8/16/1",
        "dut_iface_ibgp": "eth9/16/1",
    },
)


# ─── BGP-DC chronos_node physical inventories (Wave 3B) ───────────────────────────────
# Consumed by ``factories/bgp_dc_chronos_node.py`` — single-DUT BGP++ DC
# configs assembled through ``create_bgp_dc_chronos_node_test_config``. The
# BGP-DC factory ignores ``ixia_ports`` (physical chassis-port mapping is
# discovered at runtime rather than pinned in the testconfig), so the DUT
# interface names for downlink / uplink / rogue live in ``extras`` where the
# factory reads them. ``extras`` also carries the SSW-vs-FSW peer-group
# names, route-map identifiers, IXIA parent-network prefixes, ASNs, confed
# flags, and per-inventory IXIA BGP communities — every knob that varies by
# physical_inventory but not by binding.

# Shared IXIA parent networks / hardening baselines. Every BGP-DC chronos
# binding pins the same downlink/uplink/rogue IPv6+IPv4 parent prefixes and
# NDP-stressor networks (verified across all 4 pre-migration bindings). Kept
# as a module-level dict so each PhysicalInventory inherits the same values without
# repeating them.
_BGP_DC_CHRONOS_SHARED_EXTRAS = {
    "ixia_downlink_ic_parent_network_v6": "2401:db00:e50d:11:8",
    "ixia_uplink_ic_parent_network_v6": "2401:db00:e50d:11:9",
    "ixia_rogue_ic_parent_network_v6": "2401:db00:e50d:11:10",
    "ixia_downlink_ic_parent_network_v4": "10.163.28",
    "ixia_uplink_ic_parent_network_v4": "10.164.28",
    "ixia_rogue_ic_parent_network_v4": "10.165.28",
    "good_ndp_entry_network_v6": "2401:db00:e50d:11:9",
    "rogue_ndp_entry_network_v6": "2401:db00:e50d:11:8",
    "good_arp_entry_network_v4": "192.168",
    "rogue_arp_entry_network_v4": "193.168",
    "ixia_uplink_good_ndp_network": "2401:db00:e50d:1101:9",
    "ixia_downlink_good_ndp_network": "2401:db00:e50d:1101:8",
}

SSW_ELBERT_QZD1 = PhysicalInventory(
    usage=frozenset({"adhoc"}),
    device_name="ssw001.s002.f01.qzd1",
    primary_ixia_chassis_ip="",
    mac_address="c2:18:50:9c:1f:1d",
    extras={
        **_BGP_DC_CHRONOS_SHARED_EXTRAS,
        "ixia_downlink_interface": "eth7/16/1",
        "ixia_uplink_interface": "eth8/16/1",
        "ixia_rogue_interface": "eth9/16/1",
        "peergroup_uplink_mimic_v6": "PEERGROUP_SSW_FADU_V6",
        "peergroup_uplink_mimic_v4": "PEERGROUP_SSW_FADU_V4",
        "peergroup_downlink_mimic_v6": "PEERGROUP_SSW_FSW_V6",
        "peergroup_downlink_mimic_v4": "PEERGROUP_SSW_FSW_V4",
        # Rogue peer-group re-uses the uplink identifiers (per pre-migration source).
        "peergroup_rogue_mimic_v6": "PEERGROUP_SSW_FADU_V6",
        "peergroup_rogue_mimic_v4": "PEERGROUP_SSW_FADU_V4",
        "route_map_uplink_ingress": "PROPAGATE_SSW_FADU_IN",
        "route_map_uplink_egress": "PROPAGATE_SSW_FADU_OUT",
        "route_map_downlink_ingress": "PROPAGATE_SSW_FSW_IN",
        "route_map_downlink_egress": "PROPAGATE_SSW_FSW_OUT",
        # Rogue route-map re-uses the uplink ingress + downlink egress (per source).
        "route_map_rogue_ingress": "PROPAGATE_SSW_FADU_IN",
        "route_map_rogue_egress": "PROPAGATE_SSW_FSW_OUT",
        "remote_downlink_as_4byte": 65409,
        "remote_uplink_as_4byte": 65271,
        "remote_rogue_as_4byte": 2500,
        "is_uplink_peer_confed": "False",
        "is_downlink_peer_confed": "False",
        "is_rogue_peer_confed": "False",
        "ixia_downlink_communities": [
            "65529:34814",
            "65441:131",
        ],
        "ixia_uplink_communities": [
            "65441:261",
        ],
    },
)

FSW_FUJI_QZD1 = PhysicalInventory(
    usage=frozenset({"adhoc"}),
    device_name="fsw002.p006.f01.qzd1",
    primary_ixia_chassis_ip="",
    mac_address="c2:18:50:9c:13:f8",
    extras={
        **_BGP_DC_CHRONOS_SHARED_EXTRAS,
        "ixia_downlink_interface": "eth8/16/1",
        # Fuji uplink is on eth9/14/1 — the odd port-index (out of the /16/1
        # sibling pattern) is verbatim from the pre-migration source.
        "ixia_uplink_interface": "eth9/14/1",
        "ixia_rogue_interface": "eth9/16/1",
        "peergroup_uplink_mimic_v6": "PEERGROUP_FSW_SSW_V6",
        "peergroup_uplink_mimic_v4": "PEERGROUP_FSW_SSW_V4",
        "peergroup_downlink_mimic_v6": "PEERGROUP_FSW_RSW_V6",
        "peergroup_downlink_mimic_v4": "PEERGROUP_FSW_RSW_V4",
        "peergroup_rogue_mimic_v6": "PEERGROUP_FSW_SSW_V6",
        "peergroup_rogue_mimic_v4": "PEERGROUP_FSW_SSW_V4",
        "route_map_uplink_ingress": "PROPAGATE_FSW_SSW_IN",
        "route_map_uplink_egress": "PROPAGATE_FSW_SSW_OUT",
        "route_map_downlink_ingress": "PROPAGATE_FSW_RSW_IN",
        "route_map_downlink_egress": "PROPAGATE_FSW_RSW_OUT",
        "route_map_rogue_ingress": "PROPAGATE_FSW_SSW_IN",
        "route_map_rogue_egress": "PROPAGATE_FSW_RSW_OUT",
        # FSW uplink terminates on the ASH6 SSW plane (AS 65000); downlink is
        # a private RSW pool (AS 2000); rogue re-uses the rogue AS reservation.
        "remote_downlink_as_4byte": 2000,
        "remote_uplink_as_4byte": 65000,
        "remote_rogue_as_4byte": 2500,
        "is_uplink_peer_confed": "False",
        "is_downlink_peer_confed": "True",
        "is_rogue_peer_confed": "False",
        "ixia_downlink_communities": [
            "65441:194",
            "65441:9001",
            "65441:9002",
            "65441:9003",
            "65441:9004",
            "65441:9005",
        ],
        "ixia_uplink_communities": [
            "65441:196",
            "65441:9001",
            "65441:9002",
            "65441:9003",
            "65441:9004",
            "65441:9005",
        ],
    },
)

# ``FSW_P001_QZD1`` and ``FSW_P006_QZD1`` are declared for
# ``testconfigs/fboss_solution_tests/chronos_node_{fsw_p001_qzd1,
# full_scale_p006_qzd1}_test_config.py`` — configs built by
# ``test_config_for_bgp_and_fboss_platform_hardening_in_conveyor`` (a
# traffic-carrying sibling factory that lives outside this Wave's scope).
# No rogue-interface port and no rogue peer-group / route-map / community
# entries because that factory does not exercise the rogue path.
FSW_P001_QZD1 = PhysicalInventory(
    usage=frozenset({"adhoc"}),
    device_name="fsw001.p001.f01.qzd1",
    primary_ixia_chassis_ip="",
    mac_address="fe:59:c0:46:07:94",
    extras={
        "ixia_downlink_interface": "eth8/16/1",
        "ixia_uplink_interface": "eth9/16/1",
    },
)

FSW_P006_QZD1 = PhysicalInventory(
    usage=frozenset({"adhoc"}),
    device_name="fsw001.p006.f01.qzd1",
    primary_ixia_chassis_ip="",
    mac_address="c2:18:50:b7:0a:46",
    extras={
        "ixia_downlink_interface": "eth8/16/1",
        "ixia_uplink_interface": "eth9/16/1",
    },
)
