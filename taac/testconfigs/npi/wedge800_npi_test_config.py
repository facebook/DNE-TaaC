# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Wedge800 (w800) NPI test configs.

Single home for all w800 New Product Introduction (NPI) TestConfigs, built by
instantiating the existing shared TAAC helper factories for each class of test.
Every device-specific value comes from `w800_constants.py` (the one file to edit
when the real hardware arrives).

Classes of tests planned for w800 (per the w800 test plan):
    - CPU queue tests: Generic (FE + BE)   <-- implemented below
    - BGP Hardening tests                  <-- implemented below
    - Longevity tests                      <-- implemented below
    - Thrift hardening tests               <-- implemented below
    - Snake tests                          <-- implemented below
    - L2/NDP/ARP hardening tests           <-- implemented below
    - Platform hardening tests             <-- implemented below
    - Critical services tests              <-- implemented below
    - System reboot tests                  <-- implemented below
    - FE QoS scheduling and buffering      <-- implemented below
    - Prefix profiling & overload tests    <-- implemented below
    - Interface flaps                      <-- implemented below
    - PTP tests                            (TODO -- deferred)
    - Speed flip tests                     (TODO -- mostly not feasible in
      OSS; feasible subset reuses existing speed_flip_test_configs.py)

As each additional class is added, instantiate its existing helper here and
register the resulting TestConfig constant (see cpu_queue section for the
registration pattern).
"""

from ixia.ixia import types as ixia_types
from taac.playbooks.playbook_definitions import (
    get_critical_services_single_box_playbooks,
)
from taac.testconfigs.ai_bb.mp3n_prefix_profiling_ixia_config import (
    build_prefix_profiling_profile,
    create_device_test_configs,
)
from taac.testconfigs.fboss_solution_tests.fboss_bgp_and_platform_hardening_conveyor import (
    test_config_for_bgp_and_fboss_platform_hardening_in_conveyor,
)
from taac.testconfigs.fboss_solution_tests.qos_scheduling_test_config import (
    test_config_qos_scheduling,
)
from taac.testconfigs.fboss_solution_tests.speed_flip_test_configs import (
    build_subsume_churn_test_config,
    Circuit,
)
from taac.testconfigs.fboss_solution_tests.test_config_for_2_ixia_bgp_and_fboss_platform_hardening_in_conveyor import (
    test_config_for_2_ixia_bgp_and_fboss_platform_hardening_in_conveyor,
)
from taac.testconfigs.npi import (  # oss-rewrite-touch
    w800_constants as w800,
)
from taac.testconfigs.npi.cpu_queue_test_config import (
    create_npi_cpu_queue_test_config,
)
from taac.testconfigs.npi.thrift_hardening_test_config import (
    create_npi_thrift_hardening_test_config,
)
from taac.testconfigs.npi.w800_scale_topology import (
    apply_w800_scale_topology,
)
from taac.testconfigs.routing.factories.bgp_dc_chronos_node import (
    build_bgp_dc_test_config,
)
from taac.testconfigs.snake.test_test_config import (
    gen_snake_test_config,
)
from taac.test_as_a_config import types as taac_types


# ===========================================================================
# CPU queue tests: Generic (FE + BE)
# ===========================================================================
# One combined FE+BE TestConfig. Cloned from the IcePack GTSW CPU-queue
# reference (NPI_DVT_ICEPACK_GTSW__CPU_QUEUE_TEST_CONFIG). The factory builds the
# full set of npi_cpu_* playbooks (LLDP / BGP-CP / DHCP / ICMP / NDP / ARP /
# LACP / hop-limit / TTL / unresolved-NH / data-plane-DSCP ...) via
# create_cpu_queue_playbooks() and injects the correct prechecks/postchecks/
# snapshot checks via add_common_checks_to_cpu_queue_playbooks() -- i.e. the
# "Playbook + healthchecks" usage from the w800 test plan.
#
# CPU queue indices are passed explicitly (from w800_constants) so the factory
# skips its live netwhoami lookup, which would otherwise fail for a device that
# is not yet in inventory.
W800_CPU_QUEUE_TEST_CONFIG = create_npi_cpu_queue_test_config(
    test_config_name="W800_CPU_QUEUE_TEST_CONFIG",
    device_name=w800.W800_RSW_DUT_DEVICE_NAME,
    local_mac_address=w800.W800_LOCAL_MAC_ADDRESS,
    ixia_downlink_interface=w800.W800_IXIA_DOWNLINK_INTERFACE,
    ixia_uplink_interface=w800.W800_IXIA_UPLINK_INTERFACE,
    ixia_rogue_interface=w800.W800_IXIA_ROGUE_INTERFACE,
    peergroup_uplink_mimic_v6=w800.W800_PEERGROUP_UPLINK_MIMIC_V6,
    peergroup_uplink_mimic_v4=w800.W800_PEERGROUP_UPLINK_MIMIC_V4,
    peergroup_downlink_mimic_v6=w800.W800_PEERGROUP_DOWNLINK_MIMIC_V6,
    peergroup_downlink_mimic_v4=w800.W800_PEERGROUP_DOWNLINK_MIMIC_V4,
    peergroup_rogue_mimic_v6=w800.W800_PEERGROUP_ROGUE_MIMIC_V6,
    peergroup_rogue_mimic_v4=w800.W800_PEERGROUP_ROGUE_MIMIC_V4,
    route_map_uplink_ingress=w800.W800_ROUTE_MAP_UPLINK_INGRESS,
    route_map_uplink_egress=w800.W800_ROUTE_MAP_UPLINK_EGRESS,
    route_map_downlink_ingress=w800.W800_ROUTE_MAP_DOWNLINK_INGRESS,
    route_map_downlink_egress=w800.W800_ROUTE_MAP_DOWNLINK_EGRESS,
    route_map_rogue_ingress=w800.W800_ROUTE_MAP_ROGUE_INGRESS,
    route_map_rogue_egress=w800.W800_ROUTE_MAP_ROGUE_EGRESS,
    ixia_downlink_ic_parent_network_v6=w800.W800_IXIA_DOWNLINK_IC_PARENT_NETWORK_V6,
    ixia_uplink_ic_parent_network_v6=w800.W800_IXIA_UPLINK_IC_PARENT_NETWORK_V6,
    ixia_rogue_ic_parent_network_v6=w800.W800_IXIA_ROGUE_IC_PARENT_NETWORK_V6,
    ixia_downlink_ic_parent_network_v4=w800.W800_IXIA_DOWNLINK_IC_PARENT_NETWORK_V4,
    ixia_uplink_ic_parent_network_v4=w800.W800_IXIA_UPLINK_IC_PARENT_NETWORK_V4,
    ixia_rogue_ic_parent_network_v4=w800.W800_IXIA_ROGUE_IC_PARENT_NETWORK_V4,
    unique_prefix_limit=w800.W800_UNIQUE_PREFIX_LIMIT,
    per_peer_max_route_limit=w800.W800_PER_PEER_MAX_ROUTE_LIMIT,
    downlink_peer_count=w800.W800_DOWNLINK_PEER_COUNT,
    uplink_peer_count=w800.W800_UPLINK_PEER_COUNT,
    rogue_peer_count=w800.W800_ROGUE_PEER_COUNT,
    remote_uplink_as_4byte=w800.W800_REMOTE_UPLINK_AS_4BYTE,
    remote_downlink_as_4byte=w800.W800_REMOTE_DOWNLINK_AS_4BYTE,
    remote_as_4_byte_step=w800.W800_REMOTE_AS_4_BYTE_STEP,
    remote_rogue_as_4byte=w800.W800_REMOTE_ROGUE_AS_4BYTE,
    is_uplink_peer_confed=w800.W800_IS_UPLINK_PEER_CONFED,
    is_downlink_peer_confed=w800.W800_IS_DOWNLINK_PEER_CONFED,
    is_rogue_peer_confed=w800.W800_IS_ROGUE_PEER_CONFED,
    ixia_downlink_prefix_count_v6=w800.W800_IXIA_DOWNLINK_PREFIX_COUNT_V6,
    ixia_uplink_prefix_count_v6=w800.W800_IXIA_UPLINK_PREFIX_COUNT_V6,
    ixia_rogue_prefix_count_v6=w800.W800_IXIA_ROGUE_PREFIX_COUNT_V6,
    ixia_downlink_prefix_count_v4=w800.W800_IXIA_DOWNLINK_PREFIX_COUNT_V4,
    ixia_uplink_prefix_count_v4=w800.W800_IXIA_UPLINK_PREFIX_COUNT_V4,
    ixia_rogue_prefix_count_v4=w800.W800_IXIA_ROGUE_PREFIX_COUNT_V4,
    ixia_downlink_communities=w800.W800_IXIA_DOWNLINK_COMMUNITIES,
    ixia_uplink_communities=w800.W800_IXIA_UPLINK_COMMUNITIES,
    uplink_peer_tag=w800.W800_UPLINK_PEER_TAG,
    downlink_peer_tag=w800.W800_DOWNLINK_PEER_TAG,
    # NOTE: the factory param names preserve a historical typo ("interations").
    bgpd_restart_no_of_interations=w800.W800_BGPD_RESTART_NO_OF_ITERATIONS,
    wedge_agent_restart_no_of_interations=w800.W800_WEDGE_AGENT_RESTART_NO_OF_ITERATIONS,
    basset_pool=w800.W800_BASSET_POOL,
    service_restart_services=w800.W800_SERVICE_RESTART_SERVICES,
    # Explicit CPU-queue indices -> skip the netwhoami lookup for the stubbed DUT.
    low_queue=w800.W800_CPU_LOW_QUEUE,
    mid_queue=w800.W800_CPU_MID_QUEUE,
    high_queue=w800.W800_CPU_HIGH_QUEUE,
)
W800_CPU_QUEUE_TEST_CONFIG = apply_w800_scale_topology(
    W800_CPU_QUEUE_TEST_CONFIG,
    start_directional_traffic=False,
)


# ===========================================================================
# Shared hardening device scaffolding
# ===========================================================================
# The two hardening factories used below -- build_bgp_dc_test_config and
# test_config_for_bgp_and_fboss_platform_hardening_in_conveyor -- share 59
# required parameters; the ONLY one the conveyor does not accept is
# `ixia_rogue_interface`, which the BGP-DC call passes separately. So the whole
# device scaffolding lives here once and both factories splat it, which keeps a
# device value from drifting between classes and makes a new class a playbook
# selection rather than another ~58-line copy.
# `ecmp_member_limit` is deliberately NOT in here: test_config_qos_scheduling
# does not accept it, so it is passed at the call sites that do.
_W800_HARDENING_PARAMS = {
    "device_name": w800.W800_RSW_DUT_DEVICE_NAME,
    "local_mac_address": w800.W800_LOCAL_MAC_ADDRESS,
    "ixia_downlink_interface": w800.W800_IXIA_DOWNLINK_INTERFACE,
    "ixia_uplink_interface": w800.W800_IXIA_UPLINK_INTERFACE,
    "peergroup_uplink_mimic_v6": w800.W800_PEERGROUP_UPLINK_MIMIC_V6,
    "peergroup_uplink_mimic_v4": w800.W800_PEERGROUP_UPLINK_MIMIC_V4,
    "peergroup_downlink_mimic_v6": w800.W800_PEERGROUP_DOWNLINK_MIMIC_V6,
    "peergroup_downlink_mimic_v4": w800.W800_PEERGROUP_DOWNLINK_MIMIC_V4,
    "peergroup_rogue_mimic_v6": w800.W800_PEERGROUP_ROGUE_MIMIC_V6,
    "peergroup_rogue_mimic_v4": w800.W800_PEERGROUP_ROGUE_MIMIC_V4,
    "route_map_uplink_ingress": w800.W800_ROUTE_MAP_UPLINK_INGRESS,
    "route_map_uplink_egress": w800.W800_ROUTE_MAP_UPLINK_EGRESS,
    "route_map_downlink_ingress": w800.W800_ROUTE_MAP_DOWNLINK_INGRESS,
    "route_map_downlink_egress": w800.W800_ROUTE_MAP_DOWNLINK_EGRESS,
    "route_map_rogue_ingress": w800.W800_ROUTE_MAP_ROGUE_INGRESS,
    "route_map_rogue_egress": w800.W800_ROUTE_MAP_ROGUE_EGRESS,
    "ixia_downlink_ic_parent_network_v6": w800.W800_IXIA_DOWNLINK_IC_PARENT_NETWORK_V6,
    "ixia_uplink_ic_parent_network_v6": w800.W800_IXIA_UPLINK_IC_PARENT_NETWORK_V6,
    "ixia_rogue_ic_parent_network_v6": w800.W800_IXIA_ROGUE_IC_PARENT_NETWORK_V6,
    "ixia_downlink_ic_parent_network_v4": w800.W800_IXIA_DOWNLINK_IC_PARENT_NETWORK_V4,
    "ixia_uplink_ic_parent_network_v4": w800.W800_IXIA_UPLINK_IC_PARENT_NETWORK_V4,
    "ixia_rogue_ic_parent_network_v4": w800.W800_IXIA_ROGUE_IC_PARENT_NETWORK_V4,
    "good_ndp_entry_network_v6": w800.W800_GOOD_NDP_ENTRY_NETWORK_V6,
    "rogue_ndp_entry_network_v6": w800.W800_ROGUE_NDP_ENTRY_NETWORK_V6,
    "good_arp_entry_network_v4": w800.W800_GOOD_ARP_ENTRY_NETWORK_V4,
    "rogue_arp_entry_network_v4": w800.W800_ROGUE_ARP_ENTRY_NETWORK_V4,
    "prefix_limit": w800.W800_BGP_PREFIX_LIMIT,
    "per_peer_max_route_limit": w800.W800_PER_PEER_MAX_ROUTE_LIMIT,
    "downlink_peer_count": w800.W800_DOWNLINK_PEER_COUNT,
    "uplink_peer_count": w800.W800_UPLINK_PEER_COUNT,
    "rogue_peer_count": w800.W800_ROGUE_PEER_COUNT,
    "remote_downlink_as_4byte": w800.W800_REMOTE_DOWNLINK_AS_4BYTE,
    "remote_uplink_as_4byte": w800.W800_REMOTE_UPLINK_AS_4BYTE,
    "remote_rogue_as_4byte": w800.W800_REMOTE_ROGUE_AS_4BYTE,
    "is_uplink_peer_confed": w800.W800_IS_UPLINK_PEER_CONFED,
    "is_downlink_peer_confed": w800.W800_IS_DOWNLINK_PEER_CONFED,
    "is_rogue_peer_confed": w800.W800_IS_ROGUE_PEER_CONFED,
    "ixia_downlink_prefix_count_v6": w800.W800_IXIA_DOWNLINK_PREFIX_COUNT_V6,
    "ixia_uplink_prefix_count_v6": w800.W800_IXIA_UPLINK_PREFIX_COUNT_V6,
    "ixia_rogue_prefix_count_v6": w800.W800_IXIA_ROGUE_PREFIX_COUNT_V6,
    "ixia_downlink_prefix_count_v4": w800.W800_IXIA_DOWNLINK_PREFIX_COUNT_V4,
    "ixia_uplink_prefix_count_v4": w800.W800_IXIA_UPLINK_PREFIX_COUNT_V4,
    "ixia_rogue_prefix_count_v4": w800.W800_IXIA_ROGUE_PREFIX_COUNT_V4,
    "ixia_downlink_communities": w800.W800_IXIA_DOWNLINK_COMMUNITIES,
    "ixia_uplink_communities": w800.W800_IXIA_UPLINK_COMMUNITIES,
    "uplink_peer_tag": w800.W800_UPLINK_PEER_TAG,
    "downlink_peer_tag": w800.W800_DOWNLINK_PEER_TAG,
    "ecmp_group_limit": w800.W800_ECMP_GROUP_LIMIT,
    "good_ndp_entries_uplink": w800.W800_GOOD_NDP_ENTRIES_UPLINK,
    "good_ndp_entries_downlink": w800.W800_GOOD_NDP_ENTRIES_DOWNLINK,
    "rogue_ndp_entries": w800.W800_ROGUE_NDP_ENTRIES,
    "good_arp_entries": w800.W800_GOOD_ARP_ENTRIES,
    "rogue_arp_entries": w800.W800_ROGUE_ARP_ENTRIES,
    "good_mac_entry_count": w800.W800_GOOD_MAC_ENTRY_COUNT,
    "rogue_mac_entry_count": w800.W800_ROGUE_MAC_ENTRY_COUNT,
    "bgp_induced_ecmp_group_count": w800.W800_BGP_INDUCED_ECMP_GROUP_COUNT,
    "ixia_uplink_good_ndp_network": w800.W800_IXIA_UPLINK_GOOD_NDP_NETWORK,
    "ixia_downlink_good_ndp_network": w800.W800_IXIA_DOWNLINK_GOOD_NDP_NETWORK,
    "basset_pool": w800.W800_BASSET_POOL,
}


# ===========================================================================
# BGP Hardening tests
# ===========================================================================
# Built from the centralized BGP-DC chronos factory (build_bgp_dc_test_config),
# selecting exactly the BGP_DC longevity playbooks the w800 test plan calls out
# for BGP Hardening ("Playbook + healthchecks" column, fburl mwvz3iv3). The
# factory wraps each selected playbook with the BGP-DC TC-level prechecks/
# postchecks/snapshot checks (the "playbook + healthchecks" flow). Cloned from
# the Kodiak-3 RBB reference (FBOSS_BGP_FULL_SCALE_KODIAK_3_RBB_TEST_CONFIG_QXS1);
# device-specific values come from w800_constants. build_bgp_dc_test_config
# does NOT hit netwhoami at build time, so no stub bypass is needed.
W800_BGP_HARDENING_TEST_CONFIG = build_bgp_dc_test_config(
    test_config_name="W800_BGP_HARDENING_TEST_CONFIG",
    **_W800_HARDENING_PARAMS,
    ecmp_member_limit=w800.W800_ECMP_MEMBER_LIMIT,
    # The one BGP-DC parameter the conveyor factory does not accept, so it
    # stays out of the shared dict.
    ixia_rogue_interface=w800.W800_IXIA_ROGUE_INTERFACE,
    # Exactly the BGP_DC longevity playbooks the w800 test plan lists for BGP
    # Hardening (the sheet's "todo" rows without a playbook are omitted).
    playbooks_selected=[
        "test_longevity_prefix_flap_all_prefixes",
        "test_longevity_activate_deactivate_all_prefixes",
        "test_longevity_session_flap_all_prefixes",
        "test_longevity_prefix_flap_all_prefixes_plus_bgp_restart",
        "test_longevity_session_flap_all_prefixes_plus_bgp_restart",
        "test_longevity_rogue_prefix_session_enable",
        "test_longevity_no_prefix_no_session_flap",
        "test_longevity_continuous_toggle_device_group",
        "test_longevity_frequent_best_path_computation",
        "test_longevity_cold_start_with_prefix_and_session_oscillations",
    ],
)
W800_BGP_HARDENING_TEST_CONFIG = apply_w800_scale_topology(
    W800_BGP_HARDENING_TEST_CONFIG,
    start_directional_traffic=True,
)


# ===========================================================================
# L2 / NDP / ARP hardening tests
# ===========================================================================
# The neighbour-table overload trio: each floods the DUT with rogue NDP / ARP /
# MAC entries on top of a good-entry baseline and asserts the soft limit holds,
# good entries survive, and traffic keeps forwarding.
#
# Built from the platform-hardening conveyor factory, NOT from
# build_bgp_dc_test_config: the BGP-DC builder sets basic_traffic_item_configs=[]
# ("runs setup + playbooks only, with no IXIA traffic generation"), and
# test_hardening_of_mac_overload_entries drives
# configure_traffic_item_src_mac_entry_count against a traffic-item regex, so it
# has nothing to act on there. Every other BGP-DC caller excludes these three
# playbooks for that reason. The conveyor factory owns its own copies of them
# and builds the traffic items they need.
#
# NOT wrapped in apply_w800_scale_topology, unlike the CPU-queue and
# BGP-hardening configs above: this factory brings its own traffic items and its
# own traffic_items_to_start regex, which the wrapper would overwrite with just
# the two cross-RSW directional items -- disabling exactly the traffic these
# playbooks measure.
W800_L2_NDP_ARP_HARDENING_TEST_CONFIG = (
    test_config_for_bgp_and_fboss_platform_hardening_in_conveyor(
        test_config_name="W800_L2_NDP_ARP_HARDENING_TEST_CONFIG",
        **_W800_HARDENING_PARAMS,
        ecmp_member_limit=w800.W800_ECMP_MEMBER_LIMIT,
        playbooks_selected=[
            # The base overload trio ...
            "test_hardening_of_ndp_overload_entries",
            "test_hardening_of_arp_overload_entries",
            "test_hardening_of_mac_overload_entries",
            # ... and the same three extended with the wedge_agent-churn and
            # table-clear disruption tails (UTP L2M_002 / L2M_003 / L2M_005 /
            # L2M_006 / L2M_009). L2M_008 (clear MAC table) is not implemented
            # upstream: FBOSS exposes no MAC-flush CLI or thrift API.
            "test_hardening_of_ndp_overload_with_agent_churn",
            "test_hardening_of_ndp_overload_10x_with_table_clear",
            "test_hardening_of_arp_overload_with_agent_churn",
            "test_hardening_of_arp_overload_10x_with_table_clear",
            "test_hardening_of_mac_overload_with_agent_churn",
        ],
    )
)


# ===========================================================================
# Platform hardening tests
# ===========================================================================
# The process/service-lifecycle robustness slice of the platform-hardening
# conveyor factory: every FBOSS service restarted, crashed, warmbooted and
# coldbooted -- individually, in pairs, and in the QSFP-warmboot combinations --
# plus the cgroup system-slice OOM-kill policy check. Each playbook carries the
# factory's TC-level prechecks/postchecks, so the assertion is that the DUT
# converges and traffic recovers after every disruption.
#
# Deliberately EXCLUDED from this class, though the same factory emits them:
#   test_hardening_of_{ndp,arp,mac}_overload* -> the L2/NDP/ARP class (parent diff)
#   test_ecmp_{group,member}_overload_limit   -> the DLB and ECMP hardening class
#   test_cpu_high_priority_queue_overload     -> the CPU queue class
#   test_bgp_malformed_packet_test            -> the BGP hardening class
W800_PLATFORM_HARDENING_TEST_CONFIG = (
    test_config_for_bgp_and_fboss_platform_hardening_in_conveyor(
        test_config_name="W800_PLATFORM_HARDENING_TEST_CONFIG",
        **_W800_HARDENING_PARAMS,
        ecmp_member_limit=w800.W800_ECMP_MEMBER_LIMIT,
        playbooks_selected=[
            # cgroup / OOM policy
            "test_cgroup_system_slice_oom_kill_policy",
            # Single-service restart
            "test_agent_warmboot",
            "test_bgpd_restart",
            "test_qsfp_service_restart",
            "test_fsdb_restart",
            "test_openr_restart",
            "test_fboss_hw_agent_0_restart",
            "test_fboss_sw_agent_warmboot",
            # Single-service crash
            "test_agent_crash",
            "test_bgpd_crash",
            "test_openr_crash",
            "test_qsfp_service_crash",
            "test_fsdb_crash",
            "test_fboss_sw_agent_crash",
            "test_fboss_hw_agent_0_crash",
            # Cold boot
            "test_agent_coldboot",
            "test_fboss_hw_agent_0_coldboot",
            # Concurrent / paired service churn
            "test_fboss_sw_agent_and_hw_agent_0_restart",
            "test_fboss_sw_agent_and_hw_agent_0_crash",
            "test_bgpd_and_fsdb_restart",
            "test_agent_and_bgpd_restart",
            "test_agent_and_fsdb_restart",
            "test_agent_and_qsfp_service_restart",
            "test_fsdb_and_qsfp_service_restart",
            "test_sw_agent_and_wedge_agent_restart",
            "test_agent_warmboot_wedge_and_sw_agent",
            # QSFP warmboot combinations
            "test_qsfp_service_warmboot_and_reset",
            "test_qsfp_service_warmboot_and_agent_coldboot",
            "test_qsfp_service_warmboot_and_tx_flap",
        ],
    )
)


# ===========================================================================
# Critical services tests
# ===========================================================================
# The 23 single-box critical-services cases run on the RSW DUT with five
# disruption cycles per case. The shared builder keeps this package aligned
# with the FSW qualification config while the hardening factory supplies the
# existing W800 topology, traffic, setup, and health checks.
W800_CRITICAL_SERVICES_TEST_CONFIG = (
    test_config_for_bgp_and_fboss_platform_hardening_in_conveyor(
        test_config_name="W800_CRITICAL_SERVICES_TEST_CONFIG",
        **_W800_HARDENING_PARAMS,
        ecmp_member_limit=w800.W800_ECMP_MEMBER_LIMIT,
        playbooks=get_critical_services_single_box_playbooks(
            iteration=5,
            ixia_rogue_ic_parent_network_v6=w800.W800_IXIA_ROGUE_IC_PARENT_NETWORK_V6,
            ixia_rogue_ic_parent_network_v4=w800.W800_IXIA_ROGUE_IC_PARENT_NETWORK_V4,
        ),
    )
)


# ===========================================================================
# Interface flap tests (INTF_001..006)
# ===========================================================================
W800_INTERFACE_FLAP_TEST_CONFIG = (
    test_config_for_2_ixia_bgp_and_fboss_platform_hardening_in_conveyor(
        test_config_name="W800_INTERFACE_FLAP_TEST_CONFIG",
        **{
            key: value
            for key, value in _W800_HARDENING_PARAMS.items()
            if key != "peergroup_rogue_mimic_v4"
        },
        ecmp_member_limit=w800.W800_ECMP_MEMBER_LIMIT,
        uplink_interfaces_to_flap=w800.W800_STSW_FLAP_PORTS,
        nbr_device_name=w800.W800_INTERFACE_FLAP_NBR_DEVICE_NAME,
        nbr_interfaces_to_flap=w800.W800_INTERFACE_FLAP_NBR_PORTS,
        uplink_flap_iterations=50,
        uplink_flap_interval_s=8,
        playbooks_selected=[
            "test_flap_1_uplink_port",
            "test_flap_half_uplink_ports",
            "test_flap_n_minus_1_uplink_ports",
            "test_flap_half_uplinks_dut_and_half_nbr",
            "test_flap_n_minus_1_uplink_ports_qsfp_low_power",
            "test_flap_n_minus_1_uplink_ports_qsfp_tx_disable",
        ],
    )
)


# ===========================================================================
# FE QoS scheduling and buffering
# ===========================================================================
# The full frontend QoS matrix from the centralized test_config_qos_scheduling
# factory: 6 per-ClassOfService scheduling playbooks (NC / ICP / GOLD / SILVER
# / BRONZE / NCNF) plus 26 buffering playbooks -- per-queue congestion, single
# -queue congestion, every priority-vs-congested queue pair, and the
# multi-queue combinations. 32 playbooks in total.
#
# "FE" (frontend, 6 ClassOfService queues) rather than the BE variant
# (be_test_config_qos_scheduling, 4 DSF traffic classes): both w800 and ac100t
# are frontend platforms.
#
# The congestion half is what makes this "and buffering" -- without the
# congestion_* arguments the factory emits only the 6 scheduling playbooks.
# Following the SSW-Elbert reference, congestion reuses the rogue IXIA port,
# parent network and remote AS rather than requiring a fourth IXIA port.
#
# Shares the same 59 device parameters as the hardening factories, so it splats
# the same scaffolding dict; it additionally takes `ixia_rogue_interface`,
# which the conveyor factory does not accept and so is passed separately.
W800_FE_QOS_TEST_CONFIG = test_config_qos_scheduling(
    test_config_name="W800_FE_QOS_TEST_CONFIG",
    **_W800_HARDENING_PARAMS,
    ixia_rogue_interface=w800.W800_IXIA_ROGUE_INTERFACE,
    # Congestion traffic rides the otherwise-idle rogue port.
    ixia_congestion_interface=w800.W800_IXIA_ROGUE_INTERFACE,
    ixia_congestion_ic_parent_network_v6=w800.W800_IXIA_ROGUE_IC_PARENT_NETWORK_V6,
    congestion_peer_as_4byte=w800.W800_REMOTE_ROGUE_AS_4BYTE,
    congestion_prefix_count_v6=w800.W800_CONGESTION_PREFIX_COUNT_V6,
    congestion_prefix_start_v6=w800.W800_CONGESTION_PREFIX_START_V6,
    is_congestion_peer_confed=w800.W800_IS_ROGUE_PEER_CONFED,
)


# ===========================================================================
# System reboot tests (REBT_001..003)
# ===========================================================================
# Reuse the 800G single-DUT snake topology because the reboot behavior is
# independent of port speed. This dedicated package runs the three system,
# BMC, and microserver reboot cases five times as required by the test plan.
W800_SYSTEM_REBOOT_TEST_CONFIG = gen_snake_test_config(
    name="W800_SYSTEM_REBOOT_TEST_CONFIG",
    hostname=w800.W800_DEVICE_NAME,
    basset_pool=w800.W800_STANDALONE_BASSET_POOL,
    snake_configs=[
        taac_types.SnakeConfig(
            source=f"{w800.W800_DEVICE_NAME}:{source_interface}",
            destination=f"{w800.W800_DEVICE_NAME}:{destination_interface}",
            source_ip=source_ip,
            destination_ip=destination_ip,
        )
        for (
            source_interface,
            destination_interface,
            source_ip,
            destination_ip,
        ) in w800.W800_SNAKE_800G_LOOPS
    ],
    line_rate=w800.W800_SNAKE_LINE_RATE,
    traffic_item_name="W800_SYSTEM_REBOOT_800G_IMIX",
    frame_size_settings=ixia_types.FrameSize(
        type=ixia_types.FrameSizeType.CUSTOM_IMIX,
        imix_weight=w800.W800_SNAKE_IMIX_WEIGHT,
    ),
    iteration=5,
    playbooks_to_include=[
        "test_snake_system_reboot_bmc_full",
        "test_snake_system_reboot_bmc_microserver",
        "test_snake_system_reboot_microserver",
    ],
)


# ===========================================================================
# Prefix profiling & overload tests
# ===========================================================================
# Three TestConfigs -- one per route distribution (contiguous / hybrid /
# non-contiguous) -- from create_device_test_configs(). Each drives its
# distribution into the DUT's FIB at /48, /64, /80 and /128, then warmboots,
# restarts bgpd and coldboots under that load and measures reconvergence: 12
# playbooks per config.
#
# The route scale is supplied as a per-hardware PrefixProfilingProfile rather
# than read from the module's MP3N globals, so retuning W800 is an edit to
# w800_constants.py alone and cannot perturb the RTSW/GTSW configs that share
# the factory. Only the counts and multipliers are hardware-specific; the
# fixed-prefix / random-mask / prefix-step patterns that DEFINE each
# distribution are inherited from the MP3N baseline.
#
# This class needs FOUR IXIA ports -- one per distribution plus a traffic
# downlink -- rather than the uplink/downlink/rogue trio the hardening classes
# share, so it does not reuse _W800_HARDENING_PARAMS.
(
    W800_PREFIX_PROFILING_CONTIGUOUS_TEST_CONFIG,
    W800_PREFIX_PROFILING_HYBRID_TEST_CONFIG,
    W800_PREFIX_PROFILING_NON_CONTIGUOUS_TEST_CONFIG,
) = create_device_test_configs(
    device_name=w800.W800_RSW_DUT_DEVICE_NAME,
    remote_as=w800.W800_REMOTE_UPLINK_AS_4BYTE,
    peer_group=w800.W800_PEERGROUP_UPLINK_MIMIC_V6,
    contiguous=w800.W800_PREFIX_PROFILING_CONTIGUOUS_SPEC,
    hybrid=w800.W800_PREFIX_PROFILING_HYBRID_SPEC,
    non_contiguous=w800.W800_PREFIX_PROFILING_NON_CONTIGUOUS_SPEC,
    downlink=w800.W800_PREFIX_PROFILING_DOWNLINK_SPEC,
    mac_address=w800.W800_LOCAL_MAC_ADDRESS,
    ingress_policy=w800.W800_PREFIX_PROFILING_INGRESS_POLICY,
    egress_policy=w800.W800_PREFIX_PROFILING_EGRESS_POLICY,
    patcher_suffix=w800.W800_PREFIX_PROFILING_PATCHER_SUFFIX,
    config_name_prefix="W800_PREFIX_PROFILING",
    basset_pool=w800.W800_BASSET_POOL,
    profile=build_prefix_profiling_profile(
        contiguous_scale=w800.W800_PREFIX_PROFILING_CONTIGUOUS_SCALE,
        hybrid_scale=w800.W800_PREFIX_PROFILING_HYBRID_SCALE,
        non_contiguous_scale=w800.W800_PREFIX_PROFILING_NON_CONTIGUOUS_SCALE,
        prefix_limits=w800.W800_PREFIX_PROFILING_LIMITS,
    ),
)


# ===========================================================================
# Longevity tests
# ===========================================================================
# The 72-hour traffic bake runs on one 800G loopback pair. The focused
# allowlist keeps shorter soaks and disruptive snake cases out of this package.
W800_LONGEVITY_TEST_CONFIG = gen_snake_test_config(
    name="W800_LONGEVITY_TEST_CONFIG",
    hostname=w800.W800_DEVICE_NAME,
    basset_pool=w800.W800_STANDALONE_BASSET_POOL,
    snake_configs=[
        taac_types.SnakeConfig(
            source=f"{w800.W800_DEVICE_NAME}:{w800.W800_SNAKE_SOURCE_INTERFACE}",
            destination=f"{w800.W800_DEVICE_NAME}:{w800.W800_SNAKE_DEST_INTERFACE}",
            source_ip=w800.W800_SNAKE_SOURCE_IP,
            destination_ip=w800.W800_SNAKE_DEST_IP,
        ),
    ],
    line_rate=w800.W800_SNAKE_LINE_RATE,
    traffic_item_name="W800_72HR_LONGEVITY_800G_IMIX",
    frame_size_settings=ixia_types.FrameSize(
        type=ixia_types.FrameSizeType.CUSTOM_IMIX,
        imix_weight=w800.W800_SNAKE_IMIX_WEIGHT,
    ),
    playbooks_to_include=["test_72hr_longevity"],
)


# ===========================================================================
# Snake tests
# ===========================================================================
# Same builder as the longevity config above, but one TestConfig per speed
# grade -- the shape the reference MINIPACK3_STANDALONE_TEST_CONFIG_{400G,800G}
# configs use, so a failure names the speed it happened at. Each config runs
# the full gen_snake_playbooks suite (thrift/qsfp_util interface toggles, qsfp
# reset, agent warmboot/coldboot/crash, qsfp_service and fsdb restart/crash,
# BMC and microserver reboots) over the jumpered loops for that speed.
#
# Longevity playbooks are left in the suite rather than skipped: the snake
# builder emits them unconditionally and they are cheap relative to the
# disruptive cases. The 72hr soak is owned by W800_LONGEVITY_TEST_CONFIG.
W800_SNAKE_800G_TEST_CONFIG = gen_snake_test_config(
    name="W800_SNAKE_800G_TEST_CONFIG",
    hostname=w800.W800_DEVICE_NAME,
    basset_pool=w800.W800_STANDALONE_BASSET_POOL,
    snake_configs=[
        taac_types.SnakeConfig(
            source=f"{w800.W800_DEVICE_NAME}:{source_interface}",
            destination=f"{w800.W800_DEVICE_NAME}:{destination_interface}",
            source_ip=source_ip,
            destination_ip=destination_ip,
        )
        for (
            source_interface,
            destination_interface,
            source_ip,
            destination_ip,
        ) in w800.W800_SNAKE_800G_LOOPS
    ],
    line_rate=w800.W800_SNAKE_LINE_RATE,
    traffic_item_name="W800_800G_IMIX",
    frame_size_settings=ixia_types.FrameSize(
        type=ixia_types.FrameSizeType.CUSTOM_IMIX,
        imix_weight=w800.W800_SNAKE_IMIX_WEIGHT,
    ),
    iteration=w800.W800_SNAKE_ITERATION,
)


W800_SNAKE_400G_TEST_CONFIG = gen_snake_test_config(
    name="W800_SNAKE_400G_TEST_CONFIG",
    hostname=w800.W800_DEVICE_NAME,
    basset_pool=w800.W800_STANDALONE_BASSET_POOL,
    snake_configs=[
        taac_types.SnakeConfig(
            source=f"{w800.W800_DEVICE_NAME}:{source_interface}",
            destination=f"{w800.W800_DEVICE_NAME}:{destination_interface}",
            source_ip=source_ip,
            destination_ip=destination_ip,
        )
        for (
            source_interface,
            destination_interface,
            source_ip,
            destination_ip,
        ) in w800.W800_SNAKE_400G_LOOPS
    ],
    line_rate=w800.W800_SNAKE_LINE_RATE,
    traffic_item_name="W800_400G_IMIX",
    frame_size_settings=ixia_types.FrameSize(
        type=ixia_types.FrameSizeType.CUSTOM_IMIX,
        imix_weight=w800.W800_SNAKE_IMIX_WEIGHT,
    ),
    iteration=w800.W800_SNAKE_ITERATION,
)


# ===========================================================================
# Thrift hardening tests (THFT_001..005)
# ===========================================================================
# Built from the centralized create_npi_thrift_hardening_test_config factory
# (the THFT_001..005 playbooks: thrift-stress + qsfp-flap background, with
# per-service restart variants). Mirrors the CPU-queue BGP scaffolding (minus
# the rogue interface). skip_platform_assert=True bypasses the factory's live
# netwhoami FBOSS-platform check for the not-yet-in-inventory w800 stub.
W800_THRIFT_HARDENING_TEST_CONFIG = create_npi_thrift_hardening_test_config(
    test_config_name="W800_THRIFT_HARDENING_TEST_CONFIG",
    device_name=w800.W800_DEVICE_NAME,
    local_mac_address=w800.W800_LOCAL_MAC_ADDRESS,
    ixia_downlink_interface=w800.W800_IXIA_DOWNLINK_INTERFACE,
    ixia_uplink_interface=w800.W800_IXIA_UPLINK_INTERFACE,
    peergroup_uplink_mimic_v6=w800.W800_PEERGROUP_UPLINK_MIMIC_V6,
    peergroup_uplink_mimic_v4=w800.W800_PEERGROUP_UPLINK_MIMIC_V4,
    peergroup_downlink_mimic_v6=w800.W800_PEERGROUP_DOWNLINK_MIMIC_V6,
    peergroup_downlink_mimic_v4=w800.W800_PEERGROUP_DOWNLINK_MIMIC_V4,
    route_map_uplink_ingress=w800.W800_ROUTE_MAP_UPLINK_INGRESS,
    route_map_uplink_egress=w800.W800_ROUTE_MAP_UPLINK_EGRESS,
    route_map_downlink_ingress=w800.W800_ROUTE_MAP_DOWNLINK_INGRESS,
    route_map_downlink_egress=w800.W800_ROUTE_MAP_DOWNLINK_EGRESS,
    ixia_downlink_ic_parent_network_v6=w800.W800_IXIA_DOWNLINK_IC_PARENT_NETWORK_V6,
    ixia_uplink_ic_parent_network_v6=w800.W800_IXIA_UPLINK_IC_PARENT_NETWORK_V6,
    ixia_downlink_ic_parent_network_v4=w800.W800_IXIA_DOWNLINK_IC_PARENT_NETWORK_V4,
    ixia_uplink_ic_parent_network_v4=w800.W800_IXIA_UPLINK_IC_PARENT_NETWORK_V4,
    unique_prefix_limit=w800.W800_UNIQUE_PREFIX_LIMIT,
    per_peer_max_route_limit=w800.W800_PER_PEER_MAX_ROUTE_LIMIT,
    downlink_peer_count=w800.W800_DOWNLINK_PEER_COUNT,
    uplink_peer_count=w800.W800_UPLINK_PEER_COUNT,
    remote_uplink_as_4byte=w800.W800_REMOTE_UPLINK_AS_4BYTE,
    remote_downlink_as_4byte=w800.W800_REMOTE_DOWNLINK_AS_4BYTE,
    remote_as_4_byte_step=w800.W800_REMOTE_AS_4_BYTE_STEP,
    is_uplink_peer_confed=w800.W800_IS_UPLINK_PEER_CONFED,
    is_downlink_peer_confed=w800.W800_IS_DOWNLINK_PEER_CONFED,
    ixia_downlink_prefix_count_v6=w800.W800_IXIA_DOWNLINK_PREFIX_COUNT_V6,
    ixia_uplink_prefix_count_v6=w800.W800_IXIA_UPLINK_PREFIX_COUNT_V6,
    ixia_downlink_prefix_count_v4=w800.W800_IXIA_DOWNLINK_PREFIX_COUNT_V4,
    ixia_uplink_prefix_count_v4=w800.W800_IXIA_UPLINK_PREFIX_COUNT_V4,
    ixia_downlink_communities=w800.W800_IXIA_DOWNLINK_COMMUNITIES,
    ixia_uplink_communities=w800.W800_IXIA_UPLINK_COMMUNITIES,
    uplink_peer_tag=w800.W800_UPLINK_PEER_TAG,
    downlink_peer_tag=w800.W800_DOWNLINK_PEER_TAG,
    stsw_flap_ports=w800.W800_STSW_FLAP_PORTS,
    basset_pool=w800.W800_BASSET_POOL,
    service_restart_services=w800.W800_SERVICE_RESTART_SERVICES,
    # w800 is not yet in netwhoami inventory -> skip the live platform assert.
    skip_platform_assert=True,
)


# ===========================================================================
# Speed flip tests (subsume-churn / SPD_041)
# ===========================================================================
# Built from build_subsume_churn_test_config (the SPD_041 factory in
# speed_flip_test_configs.py, landed in D113718643) -- the one w800 speed-flip
# scenario with a real device-parameterized factory. Requires EXACTLY 6
# circuits = 3 dual cages x 2 subports (/1 + /5); values come from
# w800_constants. No build-time netwhoami lookup, so no stub bypass is needed.
#
# The OTHER w800 speed-flip rows are intentionally NOT wired here: most are
# "not feasible in OSS" (GSC-native circuit-DB / config-generate / reprovision
# paths), and the feasible reboot/coldboot/400G-200G->800G rows reuse HARDCODED
# dataclass literals in speed_flip_test_configs.py (no device-parameterized
# factory) that need real w800 port maps -- deferred until the DUT is racked.
W800_SPEED_FLIP_SUBSUME_CHURN_TEST_CONFIG = build_subsume_churn_test_config(
    test_config_name="W800_SPEED_FLIP_SUBSUME_CHURN_TEST_CONFIG",
    playbook_name="W800_SPEED_FLIP_SUBSUME_CHURN_PLAYBOOK",
    circuit_info=[
        Circuit(
            a_end_device_name=w800.W800_DEVICE_NAME,
            a_end_interface_name=f"{cage}/{subport}",
            z_end_device_name=w800.W800_SPEED_FLIP_PEER_DEVICE_NAME,
            z_end_interface_name=f"{peer}/{subport}",
        )
        for (cage, peer) in w800.W800_SPEED_FLIP_CHURN_CAGES
        for subport in ("1", "5")
    ],
    churn_iterations=w800.W800_SPEED_FLIP_CHURN_ITERATIONS,
)


# ===========================================================================
# Registry
# ===========================================================================
# The ONE symbol the central registry (testconfigs/internal/__init__.py and
# internal/all.py, which spreads it into INTERNAL_TEST_CONFIGS) imports from
# this module. Append new w800 TestConfigs here as each test class is bound,
# so adding a config never requires touching the registry files again.
W800_TEST_CONFIGS = [
    W800_CPU_QUEUE_TEST_CONFIG,
    W800_CRITICAL_SERVICES_TEST_CONFIG,
    W800_INTERFACE_FLAP_TEST_CONFIG,
    W800_BGP_HARDENING_TEST_CONFIG,
    W800_L2_NDP_ARP_HARDENING_TEST_CONFIG,
    W800_FE_QOS_TEST_CONFIG,
    W800_PREFIX_PROFILING_CONTIGUOUS_TEST_CONFIG,
    W800_PREFIX_PROFILING_HYBRID_TEST_CONFIG,
    W800_PREFIX_PROFILING_NON_CONTIGUOUS_TEST_CONFIG,
    W800_PLATFORM_HARDENING_TEST_CONFIG,
    W800_SYSTEM_REBOOT_TEST_CONFIG,
    W800_LONGEVITY_TEST_CONFIG,
    W800_SNAKE_800G_TEST_CONFIG,
    W800_SNAKE_400G_TEST_CONFIG,
    W800_THRIFT_HARDENING_TEST_CONFIG,
    W800_SPEED_FLIP_SUBSUME_CHURN_TEST_CONFIG,
]


# ===========================================================================
# Deferred classes (TODO -- see w800 test plan)
# ===========================================================================
# PTP Test         -> W800_PTP_TEST_CONFIG              (TODO: sheet rows are
#                     all 'todo' -- no playbook defined yet)
# Speed flip       -> reboot / coldboot / 400G-200G->800G variants (TODO:
#                     hardcoded dataclass literals in speed_flip_test_configs.py
#                     with no device factory; need real w800 port maps). The
#                     remaining plan rows are not feasible in OSS.
