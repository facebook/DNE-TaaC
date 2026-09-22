# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""CI/CD-sized interface and L2 hardening coverage for the QZD FSW DUT."""

from taac.constants import (
    ARP_SOFT_LIMIT,
    MAC_SOFT_LIMIT,
    NDP_SOFT_LIMIT,
)
from taac.playbooks.playbook_definitions import (
    create_hardening_of_ndp_overload_entries_playbook,
    create_l2_hardening_playbooks,
    L2_HARDENING_TIMING_PROFILES,
)
from taac.testconfigs.fboss_solution_tests.fboss_bgp_and_platform_hardening_conveyor import (
    test_config_for_bgp_and_fboss_platform_hardening_in_conveyor,
)
from taac.testconfigs.fboss_solution_tests.test_config_for_2_ixia_bgp_and_fboss_platform_hardening_in_conveyor import (
    test_config_for_2_ixia_bgp_and_fboss_platform_hardening_in_conveyor,
)
from taac.testconfigs.npi.npi_cicd_constants import (
    is_npi_cicd_dut,
    NPI_CICD_INTERFACE_FLAP_ITERATIONS,
)
from taac.test_as_a_config import types as taac_types


FSW003_P003_QZD1_DUT = "fsw003.p003.f01.qzd1"

# Active production uplinks verified on this CI/CD DUT. Ports that are
# admin-enabled but operationally down at baseline are intentionally excluded:
# a flap test cannot require those links to recover to an UP state.
FSW003_P003_QZD1_UPLINK_INTERFACES = [
    "eth2/1/1",
    "eth2/3/1",
    "eth2/9/1",
    "eth2/11/1",
    "eth2/15/1",
    "eth3/1/1",
    "eth3/3/1",
    "eth3/7/1",
    "eth3/9/1",
    "eth3/11/1",
    "eth3/15/1",
    "eth8/1/1",
    "eth8/3/1",
    "eth8/7/1",
    "eth8/9/1",
    "eth8/11/1",
    "eth8/15/1",
    "eth9/1/1",
    "eth9/3/1",
    "eth9/7/1",
    "eth9/9/1",
    "eth9/11/1",
    "eth9/15/1",
]

# INTF_004 needs one controllable peer. These lists are the exact bidirectional
# LLDP pairs discovered on fsw003 and ssw004. Keeping them index-aligned lets
# the shared factory split the bundle and flap complementary halves concurrently.
FSW003_P003_QZD1_SSW004_DUT_INTERFACES = [
    "eth2/15/1",
    "eth3/7/1",
    "eth3/15/1",
    "eth8/7/1",
    "eth8/15/1",
    "eth9/7/1",
    "eth9/15/1",
]
FSW003_P003_QZD1_SSW004_INTERFACES = [
    "eth5/2/1",
    "eth5/3/1",
    "eth5/4/1",
    "eth5/5/1",
    "eth5/6/1",
    "eth5/7/1",
    "eth5/8/1",
]

_FSW003_COMMON_HARDENING_PARAMS = {
    "device_name": FSW003_P003_QZD1_DUT,
    "local_mac_address": "b6:a9:fc:34:2b:41",
    "ixia_downlink_interface": "eth8/16/1",
    "ixia_uplink_interface": "eth7/16/1",
    "peergroup_uplink_mimic_v6": "PEERGROUP_FSW_SSW_V6",
    "peergroup_uplink_mimic_v4": "PEERGROUP_FSW_SSW_V4",
    "peergroup_downlink_mimic_v6": "PEERGROUP_FSW_RSW_V6",
    "peergroup_downlink_mimic_v4": "PEERGROUP_FSW_RSW_V4",
    "peergroup_rogue_mimic_v6": "PEERGROUP_FSW_SSW_V6",
    "route_map_uplink_ingress": "PROPAGATE_FSW_SSW_IN",
    "route_map_uplink_egress": "PROPAGATE_FSW_SSW_OUT",
    "route_map_downlink_ingress": "PROPAGATE_FSW_RSW_IN",
    "route_map_downlink_egress": "PROPAGATE_FSW_RSW_OUT",
    "route_map_rogue_ingress": "PROPAGATE_FSW_SSW_IN",
    "route_map_rogue_egress": "PROPAGATE_FSW_RSW_OUT",
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
    "prefix_limit": "75000",
    "per_peer_max_route_limit": "25000",
    "downlink_peer_count": 20,
    "uplink_peer_count": 20,
    "rogue_peer_count": 20,
    "remote_downlink_as_4byte": 2000,
    "remote_uplink_as_4byte": 65000,
    "remote_rogue_as_4byte": 2500,
    "is_uplink_peer_confed": "False",
    "is_downlink_peer_confed": "True",
    "is_rogue_peer_confed": "False",
    "ixia_downlink_prefix_count_v6": 10000,
    "ixia_uplink_prefix_count_v6": 10000,
    "ixia_rogue_prefix_count_v6": 17500,
    "ixia_downlink_prefix_count_v4": 7500,
    "ixia_uplink_prefix_count_v4": 7500,
    "ixia_rogue_prefix_count_v4": 17500,
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
    "uplink_peer_tag": "SSW",
    "downlink_peer_tag": "RSW",
    "ecmp_group_limit": 1520,
    "good_ndp_entries_uplink": 250,
    "good_ndp_entries_downlink": 200,
    "rogue_ndp_entries": 10 * NDP_SOFT_LIMIT,
    "good_arp_entries": 500,
    "rogue_arp_entries": 10 * ARP_SOFT_LIMIT,
    "good_mac_entry_count": 100,
    "rogue_mac_entry_count": 10 * MAC_SOFT_LIMIT,
    "bgp_induced_ecmp_group_count": 50,
    "ixia_uplink_good_ndp_network": "2401:db00:e50d:1101:9",
    "ixia_downlink_good_ndp_network": "2401:db00:e50d:1101:8",
    "basset_pool": "dne.test",
    # skip_ixia_protocol_verification interprets this value as a settle sleep.
    # CI/CD uses immediate handoff; playbook prechecks remain authoritative.
    "ixia_protocol_verification_timeout": 0,
    "ecmp_member_limit": 11500,
    "direct_ixia_connections": [
        taac_types.DirectIxiaConnection(
            interface="eth8/16/1",
            ixia_chassis_ip="2401:db00:0116:3006:021a:c5ff:fe01:314c",
            ixia_port="2/3",
        ),
        taac_types.DirectIxiaConnection(
            interface="eth7/16/1",
            ixia_chassis_ip="2401:db00:0116:3006:021a:c5ff:fe01:314c",
            ixia_port="6/2",
        ),
    ],
}

_IS_CICD_DUT = is_npi_cicd_dut(FSW003_P003_QZD1_DUT)
_INTERFACE_FLAP_ITERATIONS = NPI_CICD_INTERFACE_FLAP_ITERATIONS if _IS_CICD_DUT else 50
_L2_TIMING_PROFILE = L2_HARDENING_TIMING_PROFILES["cicd" if _IS_CICD_DUT else "npi"]

# LNAR validates L2-table behavior, not BGP route scale. The common factory's
# L2-only mode uses IP-only IXIA stacks and RIF patchers, leaving production BGP
# untouched. These peer/route parameters are therefore unused in this config;
# the common factory's full BGP/ECMP path remains the default for NPI callers.
_FSW003_L2_HARDENING_PARAMS = {
    **_FSW003_COMMON_HARDENING_PARAMS,
    "downlink_peer_count": 1,
    "uplink_peer_count": 1,
    "ixia_downlink_prefix_count_v6": 1,
    "ixia_uplink_prefix_count_v6": 1,
    "ixia_rogue_prefix_count_v6": 1,
    "ixia_downlink_prefix_count_v4": 1,
    "ixia_uplink_prefix_count_v4": 1,
    "ixia_rogue_prefix_count_v4": 1,
}

_FSW003_L2_HARDENING_PLAYBOOKS = create_l2_hardening_playbooks(
    device_name=FSW003_P003_QZD1_DUT,
    downlink_iface="eth8/16/1",
    uplink_iface="eth7/16/1",
    good_ndp_entries_downlink=200,
    good_ndp_entries_uplink=250,
    rogue_ndp_entries=10 * NDP_SOFT_LIMIT,
    good_arp_entries=500,
    rogue_arp_entries=10 * ARP_SOFT_LIMIT,
    good_mac_entry_count=100,
    rogue_mac_entry_count=10 * MAC_SOFT_LIMIT,
    mac_traffic_item_regex=".*_L2_MAC_LEARNING_TRAFFIC$",
    include_ixia_stable_state_checks=False,
    reapply_agent_patchers_after_coldboot=True,
    timing_profile=_L2_TIMING_PROFILE,
)

# LNAR_009: plain NDP capacity coverage, without the churn or table-clear
# actions used by LNAR_003/004.  Keep the CI/CD settle/toggle profile local to
# this DUT; the reusable playbook retains its NPI defaults for all other callers.
_FSW003_L2_HARDENING_PLAYBOOKS.append(
    create_hardening_of_ndp_overload_entries_playbook(
        device_name=FSW003_P003_QZD1_DUT,
        downlink_iface="eth8/16/1",
        uplink_iface="eth7/16/1",
        good_ndp_entries_downlink=200,
        good_ndp_entries_uplink=250,
        rogue_ndp_entries=10 * NDP_SOFT_LIMIT,
        ndp_entry_limit=NDP_SOFT_LIMIT,
        toggle_all_ipv6_ipv4_only_protocol=_L2_TIMING_PROFILE[
            "ixia_toggle_all_ip_only_protocols"
        ],
        toggle_matching_device_group=_L2_TIMING_PROFILE[
            "ixia_toggle_matching_device_group"
        ],
        sleep_time_between_toggle_s=_L2_TIMING_PROFILE["ixia_toggle_sleep_s"],
        settle_duration_s=_L2_TIMING_PROFILE["base_overload_settle_s"],
        include_ixia_stable_state_check=False,
    )
)


FSW003_P003_QZD1_INTERFACE_FLAP_TEST_CONFIG = (
    test_config_for_2_ixia_bgp_and_fboss_platform_hardening_in_conveyor(
        test_config_name="FSW003_P003_QZD1_INTERFACE_FLAP_TEST_CONFIG",
        **_FSW003_COMMON_HARDENING_PARAMS,
        uplink_interfaces_to_flap=FSW003_P003_QZD1_UPLINK_INTERFACES,
        uplink_flap_iterations=_INTERFACE_FLAP_ITERATIONS,
        uplink_flap_interval_s=8,
        playbooks_selected=[
            "test_flap_1_uplink_port",
            "test_flap_half_uplink_ports",
            "test_flap_n_minus_1_uplink_ports",
            "test_flap_n_minus_1_uplink_ports_qsfp_low_power",
            "test_flap_n_minus_1_uplink_ports_qsfp_tx_disable",
        ],
    )
)

# Keep the cross-device case separate so an unavailable neighbor cannot block
# the five DUT-only flap cases during topology discovery.
FSW003_P003_QZD1_NEIGHBOR_INTERFACE_FLAP_TEST_CONFIG = (
    test_config_for_2_ixia_bgp_and_fboss_platform_hardening_in_conveyor(
        test_config_name="FSW003_P003_QZD1_NEIGHBOR_INTERFACE_FLAP_TEST_CONFIG",
        **_FSW003_COMMON_HARDENING_PARAMS,
        uplink_interfaces_to_flap=FSW003_P003_QZD1_UPLINK_INTERFACES,
        neighbor_dut_name="ssw004.s003.f01.qzd1",
        neighbor_dut_interfaces_to_flap=FSW003_P003_QZD1_SSW004_DUT_INTERFACES,
        neighbor_interfaces_to_flap=FSW003_P003_QZD1_SSW004_INTERFACES,
        uplink_flap_iterations=_INTERFACE_FLAP_ITERATIONS,
        uplink_flap_interval_s=8,
        playbooks_selected=["test_flap_half_uplinks_dut_and_half_nbr"],
    )
)

_FSW003_P003_QZD1_L2_HARDENING_BASE_CONFIG = (
    test_config_for_bgp_and_fboss_platform_hardening_in_conveyor(
        test_config_name="FSW003_P003_QZD1_L2_HARDENING_TEST_CONFIG",
        **_FSW003_L2_HARDENING_PARAMS,
        l2_overload_only=True,
        peergroup_rogue_mimic_v4="PEERGROUP_FSW_SSW_V4",
        playbooks=_FSW003_L2_HARDENING_PLAYBOOKS,
    )
)

# The generic platform-hardening factory also provisions memory pressure for
# its OOM coverage.  None of the L2 overload cases below exercise memory
# pressure, and requiring /opt/memory_pressure would make their setup depend on
# an unrelated host utility.  Keep the common routing/IXIA setup while omitting
# only that out-of-scope task.
_FSW003_P003_QZD1_L2_HARDENING_CONFIG_FIELDS = dict(
    _FSW003_P003_QZD1_L2_HARDENING_BASE_CONFIG
)
_FSW003_P003_QZD1_L2_HARDENING_CONFIG_FIELDS["setup_tasks"] = [
    task
    for task in _FSW003_P003_QZD1_L2_HARDENING_BASE_CONFIG.setup_tasks
    if task.task_name != "allocate_cgroup_slice_memory"
]
FSW003_P003_QZD1_L2_HARDENING_TEST_CONFIG = taac_types.TestConfig(
    **_FSW003_P003_QZD1_L2_HARDENING_CONFIG_FIELDS
)

FSW003_P003_QZD1_TEST_CONFIGS = [
    FSW003_P003_QZD1_INTERFACE_FLAP_TEST_CONFIG,
    FSW003_P003_QZD1_NEIGHBOR_INTERFACE_FLAP_TEST_CONFIG,
    FSW003_P003_QZD1_L2_HARDENING_TEST_CONFIG,
]
