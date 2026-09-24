# Copyright (c) Meta Platforms, Inc. and affiliates.

"""NETOS warmboot TestConfig for fsw002.p006.f01.qzd1."""

from taac.playbooks.playbook_definitions import (
    get_critical_services_single_box_playbooks,
)
from taac.testconfigs.fboss_solution_tests.fboss_bgp_and_platform_hardening_conveyor import (
    test_config_for_bgp_and_fboss_platform_hardening_in_conveyor,
)
from taac.test_as_a_config import types as taac_types


_PLAYBOOK_NAMES: frozenset[str] = frozenset(
    {
        "test_agent_warmboot",
        "test_fboss_sw_agent_crash",
        "test_fboss_hw_agent_0_crash",
        "test_bgpd_crash",
        "test_qsfp_service_crash",
        "test_fsdb_crash",
        "test_openr_crash",
        "test_qsfp_service_warmboot_and_agent_coldboot",
        "test_qsfp_service_and_agent_warmboot",
        "test_qsfp_service_warmboot_and_tx_flap",
        "test_qsfp_service_warmboot_and_reset",
        "test_bgpd_and_fsdb_restart",
        "test_agent_and_fsdb_restart",
        "test_agent_and_qsfp_service_restart",
    }
)


CHRONOS_NODE_FSW_FUJI_NETOS_TEST_CONFIG = (
    test_config_for_bgp_and_fboss_platform_hardening_in_conveyor(
        test_config_name="CHRONOS_NODE_FSW_FUJI_NETOS",
        device_name="fsw002.p006.f01.qzd1",
        local_mac_address="c2:18:50:9c:13:f8",
        ixia_downlink_interface="eth8/16/1",
        ixia_uplink_interface="eth9/16/1",
        peergroup_uplink_mimic_v6="PEERGROUP_FSW_SSW_V6",
        peergroup_uplink_mimic_v4="PEERGROUP_FSW_SSW_V4",
        peergroup_downlink_mimic_v6="PEERGROUP_FSW_RSW_V6",
        peergroup_downlink_mimic_v4="PEERGROUP_FSW_RSW_V4",
        peergroup_rogue_mimic_v6="PEERGROUP_FSW_SSW_V6",
        peergroup_rogue_mimic_v4="PEERGROUP_FSW_SSW_V4",
        route_map_uplink_ingress="PROPAGATE_FSW_SSW_IN",
        route_map_uplink_egress="PROPAGATE_FSW_SSW_OUT",
        route_map_downlink_ingress="PROPAGATE_FSW_RSW_IN",
        route_map_downlink_egress="PROPAGATE_FSW_RSW_OUT",
        route_map_rogue_ingress="PROPAGATE_FSW_SSW_IN",
        route_map_rogue_egress="PROPAGATE_FSW_RSW_OUT",
        ixia_downlink_ic_parent_network_v6="2401:db00:e50d:11:8",
        ixia_uplink_ic_parent_network_v6="2401:db00:e50d:11:9",
        ixia_rogue_ic_parent_network_v6="2401:db00:e50d:11:10",
        ixia_downlink_ic_parent_network_v4="10.163.28",
        ixia_uplink_ic_parent_network_v4="10.164.28",
        ixia_rogue_ic_parent_network_v4="10.165.28",
        good_ndp_entry_network_v6="2401:db00:e50d:11:9",
        rogue_ndp_entry_network_v6="2401:db00:e50d:11:8",
        good_arp_entry_network_v4="192.168",
        rogue_arp_entry_network_v4="193.168",
        prefix_limit="75000",
        per_peer_max_route_limit="25000",
        downlink_peer_count=20,
        uplink_peer_count=20,
        rogue_peer_count=20,
        remote_downlink_as_4byte=2000,
        remote_uplink_as_4byte=65000,
        remote_rogue_as_4byte=2500,
        is_uplink_peer_confed="False",
        is_downlink_peer_confed="True",
        is_rogue_peer_confed="False",
        ixia_downlink_prefix_count_v6=10000,
        ixia_uplink_prefix_count_v6=10000,
        ixia_rogue_prefix_count_v6=17500,
        ixia_downlink_prefix_count_v4=7500,
        ixia_uplink_prefix_count_v4=7500,
        ixia_rogue_prefix_count_v4=17500,
        ixia_uplink_good_ndp_network="2401:db00:e50d:1101:9",
        ixia_downlink_good_ndp_network="2401:db00:e50d:1101:8",
        ixia_downlink_communities=[
            "65441:194",
            "65441:9001",
            "65441:9002",
            "65441:9003",
            "65441:9004",
            "65441:9005",
        ],
        ixia_uplink_communities=[
            "65441:196",
            "65441:9001",
            "65441:9002",
            "65441:9003",
            "65441:9004",
            "65441:9005",
        ],
        downlink_peer_tag="RSW",
        uplink_peer_tag="SSW",
        ecmp_group_limit=1520,
        good_ndp_entries_uplink=250,
        good_ndp_entries_downlink=200,
        rogue_ndp_entries=10000,
        good_arp_entries=500,
        rogue_arp_entries=1500,
        good_mac_entry_count=100,
        rogue_mac_entry_count=200,
        bgp_induced_ecmp_group_count=50,
        basset_pool="dne.regression",
        include_bgp_peer_route_snapshot_check=True,
        include_cgroup_memory_setup=False,
        playbooks=[
            playbook
            for playbook in get_critical_services_single_box_playbooks(
                iteration=1,
                ixia_rogue_ic_parent_network_v6="2401:db00:e50d:11:10",
                ixia_rogue_ic_parent_network_v4="10.165.28",
            )
            if playbook.name in _PLAYBOOK_NAMES
        ],
    )(
        # This config's precheck depends on the high-scale NDP traffic item.
        # A cached ixncfg can retain unresolved destination MAC state and load
        # the item with no valid packets, so rebuild the IXIA session each run.
        ixia_config_cache=taac_types.IxiaConfigCache(enabled=False),
        # TAAC does not renew reservations, the 14 playbooks take more than the
        # 4 hour default, and Lab Doctor strips TAAC's COOP patchers from any
        # device whose reservation has lapsed.
        basset_reservation_time_hr=6,
    )
)
