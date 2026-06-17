# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""DNE_KODIAK3_CRITICAL_SERVICES_CICD_NODE — CICD_TC TestConfig.

CICD_TC conveyor node binding (per `scripts/triage/dne_taac_checker.py`).
Built from the centralized `test_config_for_bgp_and_fboss_platform_hardening_in_conveyor` factory.
"""

from ixia.ixia import types as ixia_types
from taac.task_definitions import (
    create_coop_register_patcher_task,
)
from taac.testconfigs.fboss_solution_tests.fboss_bgp_and_platform_hardening_conveyor import (
    test_config_for_bgp_and_fboss_platform_hardening_in_conveyor,
)

# Kodiak3 rb002-01.qxq1 - Critical Services CI/CD Node
DNE_KODIAK3_CRITICAL_SERVICES_CICD_NODE_TEST_CONFIG = (
    test_config_for_bgp_and_fboss_platform_hardening_in_conveyor(
        test_config_name="DNE_KODIAK3_CRITICAL_SERVICES_CICD_NODE",
        device_name="rb002-01.qxq1",
        local_mac_address="9e:a9:b8:49:df:fe",
        ixia_downlink_interface="eth1/64/1",
        ixia_uplink_interface="eth1/64/5",
        peergroup_uplink_mimic_v6="PEERGROUP_RB_RB_V6",
        peergroup_uplink_mimic_v4="PEERGROUP_RB_RB_V4",
        peergroup_downlink_mimic_v6="PEERGROUP_RB_XSW_V6",
        peergroup_downlink_mimic_v4="PEERGROUP_RB_XSW_V4",
        peergroup_rogue_mimic_v6="PEERGROUP_RB_RB_V6",  # Same as uplink
        peergroup_rogue_mimic_v4="PEERGROUP_RB_RB_V4",  # Same as uplink
        route_map_uplink_ingress="PROPAGATE_RB_RB_IN",
        route_map_uplink_egress="PROPAGATE_RB_RB_OUT",
        route_map_downlink_ingress="PROPAGATE_RB_XSW_IN",
        route_map_downlink_egress="PROPAGATE_RB_XSW_OUT",
        route_map_rogue_ingress="PROPAGATE_RB_RB_IN",  # Same as uplink
        route_map_rogue_egress="PROPAGATE_RB_XSW_OUT",  # Same as downlink
        ixia_downlink_ic_parent_network_v6="2401:db00:e50d:11:8",
        ixia_uplink_ic_parent_network_v6="2401:db00:e50d:11:9",
        ixia_rogue_ic_parent_network_v6="2401:db00:e50d:11:10",
        ixia_downlink_ic_parent_network_v4="10.163.28",
        ixia_uplink_ic_parent_network_v4="10.164.28",
        ixia_rogue_ic_parent_network_v4="10.165.28",
        good_ndp_entry_network_v6="2401:db00:e50d:1102:9",
        rogue_ndp_entry_network_v6="2401:db00:e50d:1102:8",
        good_arp_entry_network_v4="192.168",
        rogue_arp_entry_network_v4="193.168",
        prefix_limit="75000",
        per_peer_max_route_limit="20000",
        downlink_peer_count=15,
        uplink_peer_count=8,
        rogue_peer_count=8,
        remote_downlink_as_4byte=7001,
        remote_uplink_as_4byte=4260310998,
        remote_rogue_as_4byte=2500,
        is_uplink_peer_confed="False",
        is_downlink_peer_confed="False",
        is_rogue_peer_confed="False",  # Same as uplink
        ixia_downlink_prefix_count_v6=10000,
        ixia_uplink_prefix_count_v6=20000,
        ixia_rogue_prefix_count_v6=7500,
        ixia_downlink_prefix_count_v4=7000,
        ixia_uplink_prefix_count_v4=15000,
        ixia_rogue_prefix_count_v4=7500,
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
        downlink_peer_tag="XSW",
        uplink_peer_tag="RB",
        ecmp_group_limit=750,
        good_ndp_entries_uplink=110,
        good_ndp_entries_downlink=10,
        rogue_ndp_entries=5,
        good_arp_entries=100,
        rogue_arp_entries=1500,
        good_mac_entry_count=100,
        rogue_mac_entry_count=200,
        bgp_induced_ecmp_group_count=50,
        bgpd_restart_no_of_interations=5,
        wedge_agent_restart_no_of_interations=5,
        basset_pool="dne.test",
        allow_all_v4_policies=True,
        skip_playbooks=[
            "test_cgroup_system_slice_oom_kill_policy",
            "test_hardening_of_ndp_overload_entries",
            "test_hardening_of_arp_overload_entries",
            "test_hardening_of_mac_overload_entries",
            "test_bgp_malformed_packet_test",
            "test_ecmp_member_overload_limit",
            "test_ecmp_group_overload_limit",
            "test_cpu_high_priority_queue_overload",
        ],
        uplink_bgp_peer_type=ixia_types.BgpPeerType.IBGP,
        additional_setup_tasks=[
            # Set BGP router ID
            create_coop_register_patcher_task(
                hostname="rb002-01.qxq1",
                config_name="bgpcpp",
                patcher_name="set_bgp_router_id",
                task_name="bgp_feature_canary",
                patcher_args={
                    "router-id": "180.1.1.1",
                },
                py_func_name="bgp_feature_canary",
            ),
            # Enable the 3 non-ixia ports (ixia ports already enabled by conveyor)
            create_coop_register_patcher_task(
                hostname="rb002-01.qxq1",
                config_name="agent",
                patcher_name="enable_extra_ports",
                task_name="coop_register_patcher",
                patcher_args={
                    "eth1/62/1": "enable",
                    "eth1/64/1": "enable",
                    "eth1/64/5": "enable",
                },
                py_func_name="change_port_admin_state",
            ),
        ]
        + [
            # Set all 5 ports to 400G (Kodiak3/Morgan800CC profile)
            create_coop_register_patcher_task(
                hostname="rb002-01.qxq1",
                config_name="agent",
                patcher_name=f"change_speed_{port}_400G",
                task_name="coop_register_patcher",
                patcher_args={
                    "intfs": port,
                    "speed": "FOURHUNDREDG",
                    "profile_id": "PROFILE_400G_4_PAM4_RS544X2N_OPTICAL",
                },
                py_func_name="change_speed",
            )
            for port in [
                "eth1/62/1",
                "eth1/63/1",
                "eth1/63/5",
                "eth1/64/1",
                "eth1/64/5",
            ]
        ],
    )
)
