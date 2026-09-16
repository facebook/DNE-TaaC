# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Steller Eagle / 100T air-cooled (ac100t) NPI test configs.

Single home for all ac100t New Product Introduction (NPI) TestConfigs, built by
instantiating the existing shared TAAC helper factories for each class of test.
Every device-specific value comes from `ac100t_constants.py` (the one file to
edit when the real hardware arrives), which encodes the M4062NHP 4-DUT + IXIA
fanout topology: DUT1-DUT3 are Steller Eagle 100T units and DUT4 is a Wedge800
acting as the CE.

Classes of tests planned for ac100t (per the ac100t test plan):
    - CPU queue tests: Generic (FE + BE)   <-- implemented below
    - BGP Hardening tests                  (TODO -- constants already staged in
      ac100t_constants.py; bind build_bgp_dc_test_config next)
    - Snake tests                          <-- implemented below
    - L2/NDP/ARP hardening tests           <-- implemented below
    - Platform hardening tests             <-- implemented below
    - Critical services tests              <-- implemented below
    - FE QoS scheduling and buffering      <-- implemented below
    - Longevity tests                      (TODO -- constants staged;
      gen_snake_test_config)
    - Thrift hardening tests               (TODO -- constants staged;
      create_npi_thrift_hardening_test_config)
    - Interface flaps                      (TODO -- deferred)
    - PTP tests                            (TODO -- deferred)
    - Speed flip tests                     (TODO -- mostly not feasible in
      OSS; feasible subset reuses existing speed_flip_test_configs.py)
    - Multi-DUT classes from the topology doc (TODO -- constants staged):
      the B->D / A->C / C->A traffic items, the DUT3 drain converging on DUT1,
      and the QoS case (B + D routes -> A routes, 2x800G -> 1x800G). These need
      a multi-device factory; the single-DUT factories below cannot express them.

As each additional class is added, instantiate its existing helper here and
register the resulting TestConfig constant (see cpu_queue section for the
registration pattern).
"""

from ixia.ixia import types as ixia_types
from taac.playbooks.playbook_definitions import (
    get_critical_services_single_box_playbooks,
)
from taac.testconfigs.fboss_solution_tests.fboss_bgp_and_platform_hardening_conveyor import (
    test_config_for_bgp_and_fboss_platform_hardening_in_conveyor,
)
from taac.testconfigs.fboss_solution_tests.qos_scheduling_test_config import (
    test_config_qos_scheduling,
)
from taac.testconfigs.npi import (  # oss-rewrite-touch
    ac100t_constants as ac100t,
)
from taac.testconfigs.npi.cpu_queue_test_config import (
    create_npi_cpu_queue_test_config,
)
from taac.testconfigs.snake.test_test_config import (
    gen_snake_test_config,
)
from taac.test_as_a_config import types as taac_types

# ===========================================================================
# CPU queue tests: Generic (FE + BE)
# ===========================================================================
# One combined FE+BE TestConfig. Cloned from the IcePack GTSW CPU-queue
# reference (NPI_DVT_ICEPACK_GTSW__CPU_QUEUE_TEST_CONFIG). The factory builds
# the full set of npi_cpu_* playbooks (LLDP / BGP-CP / DHCP / ICMP / NDP / ARP /
# LACP / hop-limit / TTL / unresolved-NH / data-plane-DSCP ...) via
# create_cpu_queue_playbooks() and injects the correct prechecks/postchecks/
# snapshot checks via add_common_checks_to_cpu_queue_playbooks() -- i.e. the
# "Playbook + healthchecks" usage from the ac100t test plan.
#
# This factory is SINGLE-DUT, so the CPU-queue class runs on one Steller Eagle
# unit (DUT2) rather than the full 4-DUT topology -- DUT2 is the device the
# topology doc frames its traffic items around. CPU queue indices are passed
# explicitly (from ac100t_constants) so the factory skips its live netwhoami
# lookup, which would otherwise raise: Steller Eagle has no netwhoami Hardware
# enum value and no entry in get_cpu_queue_constants().
AC100T_CPU_QUEUE_TEST_CONFIG = create_npi_cpu_queue_test_config(
    test_config_name="AC100T_CPU_QUEUE_TEST_CONFIG",
    device_name=ac100t.AC100T_CPU_QUEUE_DUT,
    local_mac_address=ac100t.AC100T_CPU_QUEUE_LOCAL_MAC_ADDRESS,
    ixia_downlink_interface=ac100t.AC100T_CPU_QUEUE_IXIA_DOWNLINK_INTERFACE,
    ixia_uplink_interface=ac100t.AC100T_CPU_QUEUE_IXIA_UPLINK_INTERFACE,
    ixia_rogue_interface=ac100t.AC100T_CPU_QUEUE_IXIA_ROGUE_INTERFACE,
    peergroup_uplink_mimic_v6=ac100t.AC100T_PEERGROUP_UPLINK_MIMIC_V6,
    peergroup_uplink_mimic_v4=ac100t.AC100T_PEERGROUP_UPLINK_MIMIC_V4,
    peergroup_downlink_mimic_v6=ac100t.AC100T_PEERGROUP_DOWNLINK_MIMIC_V6,
    peergroup_downlink_mimic_v4=ac100t.AC100T_PEERGROUP_DOWNLINK_MIMIC_V4,
    peergroup_rogue_mimic_v6=ac100t.AC100T_PEERGROUP_ROGUE_MIMIC_V6,
    peergroup_rogue_mimic_v4=ac100t.AC100T_PEERGROUP_ROGUE_MIMIC_V4,
    route_map_uplink_ingress=ac100t.AC100T_ROUTE_MAP_UPLINK_INGRESS,
    route_map_uplink_egress=ac100t.AC100T_ROUTE_MAP_UPLINK_EGRESS,
    route_map_downlink_ingress=ac100t.AC100T_ROUTE_MAP_DOWNLINK_INGRESS,
    route_map_downlink_egress=ac100t.AC100T_ROUTE_MAP_DOWNLINK_EGRESS,
    route_map_rogue_ingress=ac100t.AC100T_ROUTE_MAP_ROGUE_INGRESS,
    route_map_rogue_egress=ac100t.AC100T_ROUTE_MAP_ROGUE_EGRESS,
    ixia_downlink_ic_parent_network_v6=ac100t.AC100T_IXIA_DOWNLINK_IC_PARENT_NETWORK_V6,
    ixia_uplink_ic_parent_network_v6=ac100t.AC100T_IXIA_UPLINK_IC_PARENT_NETWORK_V6,
    ixia_rogue_ic_parent_network_v6=ac100t.AC100T_IXIA_ROGUE_IC_PARENT_NETWORK_V6,
    ixia_downlink_ic_parent_network_v4=ac100t.AC100T_IXIA_DOWNLINK_IC_PARENT_NETWORK_V4,
    ixia_uplink_ic_parent_network_v4=ac100t.AC100T_IXIA_UPLINK_IC_PARENT_NETWORK_V4,
    ixia_rogue_ic_parent_network_v4=ac100t.AC100T_IXIA_ROGUE_IC_PARENT_NETWORK_V4,
    unique_prefix_limit=ac100t.AC100T_UNIQUE_PREFIX_LIMIT,
    per_peer_max_route_limit=ac100t.AC100T_PER_PEER_MAX_ROUTE_LIMIT,
    downlink_peer_count=ac100t.AC100T_DOWNLINK_PEER_COUNT,
    uplink_peer_count=ac100t.AC100T_UPLINK_PEER_COUNT,
    rogue_peer_count=ac100t.AC100T_ROGUE_PEER_COUNT,
    remote_uplink_as_4byte=ac100t.AC100T_REMOTE_UPLINK_AS_4BYTE,
    remote_downlink_as_4byte=ac100t.AC100T_REMOTE_DOWNLINK_AS_4BYTE,
    remote_as_4_byte_step=ac100t.AC100T_REMOTE_AS_4_BYTE_STEP,
    remote_rogue_as_4byte=ac100t.AC100T_REMOTE_ROGUE_AS_4BYTE,
    is_uplink_peer_confed=ac100t.AC100T_IS_UPLINK_PEER_CONFED,
    is_downlink_peer_confed=ac100t.AC100T_IS_DOWNLINK_PEER_CONFED,
    is_rogue_peer_confed=ac100t.AC100T_IS_ROGUE_PEER_CONFED,
    ixia_downlink_prefix_count_v6=ac100t.AC100T_IXIA_DOWNLINK_PREFIX_COUNT_V6,
    ixia_uplink_prefix_count_v6=ac100t.AC100T_IXIA_UPLINK_PREFIX_COUNT_V6,
    ixia_rogue_prefix_count_v6=ac100t.AC100T_IXIA_ROGUE_PREFIX_COUNT_V6,
    ixia_downlink_prefix_count_v4=ac100t.AC100T_IXIA_DOWNLINK_PREFIX_COUNT_V4,
    ixia_uplink_prefix_count_v4=ac100t.AC100T_IXIA_UPLINK_PREFIX_COUNT_V4,
    ixia_rogue_prefix_count_v4=ac100t.AC100T_IXIA_ROGUE_PREFIX_COUNT_V4,
    ixia_downlink_communities=ac100t.AC100T_IXIA_DOWNLINK_COMMUNITIES,
    ixia_uplink_communities=ac100t.AC100T_IXIA_UPLINK_COMMUNITIES,
    uplink_peer_tag=ac100t.AC100T_UPLINK_PEER_TAG,
    downlink_peer_tag=ac100t.AC100T_DOWNLINK_PEER_TAG,
    # NOTE: the factory param names preserve a historical typo ("interations").
    bgpd_restart_no_of_interations=ac100t.AC100T_BGPD_RESTART_NO_OF_ITERATIONS,
    wedge_agent_restart_no_of_interations=ac100t.AC100T_WEDGE_AGENT_RESTART_NO_OF_ITERATIONS,
    basset_pool=ac100t.AC100T_BASSET_POOL,
    service_restart_services=ac100t.AC100T_SERVICE_RESTART_SERVICES,
    # Explicit CPU-queue indices -> skip the netwhoami lookup for the stubbed DUT.
    low_queue=ac100t.AC100T_CPU_LOW_QUEUE,
    mid_queue=ac100t.AC100T_CPU_MID_QUEUE,
    high_queue=ac100t.AC100T_CPU_HIGH_QUEUE,
)


# ===========================================================================
# Shared hardening device scaffolding
# ===========================================================================
# The hardening factories share 59 required parameters; the ONLY one
# test_config_for_bgp_and_fboss_platform_hardening_in_conveyor does not accept
# is `ixia_rogue_interface`, which a build_bgp_dc_test_config call would pass
# separately. Keeping the scaffolding here once means a new class is a playbook
# selection rather than another ~58-line copy, and stops a device value
# drifting between classes. AC100T_BGP_HARDENING_TEST_CONFIG should reuse this
# dict when it is bound.
#
# These factories are SINGLE-DUT, so they run on the same Steller Eagle unit
# the CPU-queue class uses (DUT2) rather than the full 4-DUT topology.
# `ecmp_member_limit` is deliberately NOT in here: test_config_qos_scheduling
# does not accept it, so it is passed at the call sites that do.
_AC100T_HARDENING_PARAMS = {
    "device_name": ac100t.AC100T_CPU_QUEUE_DUT,
    "local_mac_address": ac100t.AC100T_CPU_QUEUE_LOCAL_MAC_ADDRESS,
    "ixia_downlink_interface": ac100t.AC100T_CPU_QUEUE_IXIA_DOWNLINK_INTERFACE,
    "ixia_uplink_interface": ac100t.AC100T_CPU_QUEUE_IXIA_UPLINK_INTERFACE,
    "peergroup_uplink_mimic_v6": ac100t.AC100T_PEERGROUP_UPLINK_MIMIC_V6,
    "peergroup_uplink_mimic_v4": ac100t.AC100T_PEERGROUP_UPLINK_MIMIC_V4,
    "peergroup_downlink_mimic_v6": ac100t.AC100T_PEERGROUP_DOWNLINK_MIMIC_V6,
    "peergroup_downlink_mimic_v4": ac100t.AC100T_PEERGROUP_DOWNLINK_MIMIC_V4,
    "peergroup_rogue_mimic_v6": ac100t.AC100T_PEERGROUP_ROGUE_MIMIC_V6,
    "peergroup_rogue_mimic_v4": ac100t.AC100T_PEERGROUP_ROGUE_MIMIC_V4,
    "route_map_uplink_ingress": ac100t.AC100T_ROUTE_MAP_UPLINK_INGRESS,
    "route_map_uplink_egress": ac100t.AC100T_ROUTE_MAP_UPLINK_EGRESS,
    "route_map_downlink_ingress": ac100t.AC100T_ROUTE_MAP_DOWNLINK_INGRESS,
    "route_map_downlink_egress": ac100t.AC100T_ROUTE_MAP_DOWNLINK_EGRESS,
    "route_map_rogue_ingress": ac100t.AC100T_ROUTE_MAP_ROGUE_INGRESS,
    "route_map_rogue_egress": ac100t.AC100T_ROUTE_MAP_ROGUE_EGRESS,
    "ixia_downlink_ic_parent_network_v6": ac100t.AC100T_IXIA_DOWNLINK_IC_PARENT_NETWORK_V6,
    "ixia_uplink_ic_parent_network_v6": ac100t.AC100T_IXIA_UPLINK_IC_PARENT_NETWORK_V6,
    "ixia_rogue_ic_parent_network_v6": ac100t.AC100T_IXIA_ROGUE_IC_PARENT_NETWORK_V6,
    "ixia_downlink_ic_parent_network_v4": ac100t.AC100T_IXIA_DOWNLINK_IC_PARENT_NETWORK_V4,
    "ixia_uplink_ic_parent_network_v4": ac100t.AC100T_IXIA_UPLINK_IC_PARENT_NETWORK_V4,
    "ixia_rogue_ic_parent_network_v4": ac100t.AC100T_IXIA_ROGUE_IC_PARENT_NETWORK_V4,
    "good_ndp_entry_network_v6": ac100t.AC100T_GOOD_NDP_ENTRY_NETWORK_V6,
    "rogue_ndp_entry_network_v6": ac100t.AC100T_ROGUE_NDP_ENTRY_NETWORK_V6,
    "good_arp_entry_network_v4": ac100t.AC100T_GOOD_ARP_ENTRY_NETWORK_V4,
    "rogue_arp_entry_network_v4": ac100t.AC100T_ROGUE_ARP_ENTRY_NETWORK_V4,
    "prefix_limit": ac100t.AC100T_BGP_PREFIX_LIMIT,
    "per_peer_max_route_limit": ac100t.AC100T_PER_PEER_MAX_ROUTE_LIMIT,
    "downlink_peer_count": ac100t.AC100T_DOWNLINK_PEER_COUNT,
    "uplink_peer_count": ac100t.AC100T_UPLINK_PEER_COUNT,
    "rogue_peer_count": ac100t.AC100T_ROGUE_PEER_COUNT,
    "remote_downlink_as_4byte": ac100t.AC100T_REMOTE_DOWNLINK_AS_4BYTE,
    "remote_uplink_as_4byte": ac100t.AC100T_REMOTE_UPLINK_AS_4BYTE,
    "remote_rogue_as_4byte": ac100t.AC100T_REMOTE_ROGUE_AS_4BYTE,
    "is_uplink_peer_confed": ac100t.AC100T_IS_UPLINK_PEER_CONFED,
    "is_downlink_peer_confed": ac100t.AC100T_IS_DOWNLINK_PEER_CONFED,
    "is_rogue_peer_confed": ac100t.AC100T_IS_ROGUE_PEER_CONFED,
    "ixia_downlink_prefix_count_v6": ac100t.AC100T_IXIA_DOWNLINK_PREFIX_COUNT_V6,
    "ixia_uplink_prefix_count_v6": ac100t.AC100T_IXIA_UPLINK_PREFIX_COUNT_V6,
    "ixia_rogue_prefix_count_v6": ac100t.AC100T_IXIA_ROGUE_PREFIX_COUNT_V6,
    "ixia_downlink_prefix_count_v4": ac100t.AC100T_IXIA_DOWNLINK_PREFIX_COUNT_V4,
    "ixia_uplink_prefix_count_v4": ac100t.AC100T_IXIA_UPLINK_PREFIX_COUNT_V4,
    "ixia_rogue_prefix_count_v4": ac100t.AC100T_IXIA_ROGUE_PREFIX_COUNT_V4,
    "ixia_downlink_communities": ac100t.AC100T_IXIA_DOWNLINK_COMMUNITIES,
    "ixia_uplink_communities": ac100t.AC100T_IXIA_UPLINK_COMMUNITIES,
    "uplink_peer_tag": ac100t.AC100T_UPLINK_PEER_TAG,
    "downlink_peer_tag": ac100t.AC100T_DOWNLINK_PEER_TAG,
    "ecmp_group_limit": ac100t.AC100T_ECMP_GROUP_LIMIT,
    "good_ndp_entries_uplink": ac100t.AC100T_GOOD_NDP_ENTRIES_UPLINK,
    "good_ndp_entries_downlink": ac100t.AC100T_GOOD_NDP_ENTRIES_DOWNLINK,
    "rogue_ndp_entries": ac100t.AC100T_ROGUE_NDP_ENTRIES,
    "good_arp_entries": ac100t.AC100T_GOOD_ARP_ENTRIES,
    "rogue_arp_entries": ac100t.AC100T_ROGUE_ARP_ENTRIES,
    "good_mac_entry_count": ac100t.AC100T_GOOD_MAC_ENTRY_COUNT,
    "rogue_mac_entry_count": ac100t.AC100T_ROGUE_MAC_ENTRY_COUNT,
    "bgp_induced_ecmp_group_count": ac100t.AC100T_BGP_INDUCED_ECMP_GROUP_COUNT,
    "ixia_uplink_good_ndp_network": ac100t.AC100T_IXIA_UPLINK_GOOD_NDP_NETWORK,
    "ixia_downlink_good_ndp_network": ac100t.AC100T_IXIA_DOWNLINK_GOOD_NDP_NETWORK,
    "basset_pool": ac100t.AC100T_BASSET_POOL,
}


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
AC100T_L2_NDP_ARP_HARDENING_TEST_CONFIG = (
    test_config_for_bgp_and_fboss_platform_hardening_in_conveyor(
        test_config_name="AC100T_L2_NDP_ARP_HARDENING_TEST_CONFIG",
        **_AC100T_HARDENING_PARAMS,
        ecmp_member_limit=ac100t.AC100T_ECMP_MEMBER_LIMIT,
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
AC100T_PLATFORM_HARDENING_TEST_CONFIG = (
    test_config_for_bgp_and_fboss_platform_hardening_in_conveyor(
        test_config_name="AC100T_PLATFORM_HARDENING_TEST_CONFIG",
        **_AC100T_HARDENING_PARAMS,
        ecmp_member_limit=ac100t.AC100T_ECMP_MEMBER_LIMIT,
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
# The 23 single-box critical-services cases run on DUT2 with five disruption
# cycles per case. The shared builder keeps this package aligned with the FSW
# qualification config while the hardening factory supplies the existing
# AC100T topology, traffic, setup, and health checks.
AC100T_CRITICAL_SERVICES_TEST_CONFIG = test_config_for_bgp_and_fboss_platform_hardening_in_conveyor(
    test_config_name="AC100T_CRITICAL_SERVICES_TEST_CONFIG",
    **_AC100T_HARDENING_PARAMS,
    ecmp_member_limit=ac100t.AC100T_ECMP_MEMBER_LIMIT,
    playbooks=get_critical_services_single_box_playbooks(
        iteration=5,
        ixia_rogue_ic_parent_network_v6=ac100t.AC100T_IXIA_ROGUE_IC_PARENT_NETWORK_V6,
        ixia_rogue_ic_parent_network_v4=ac100t.AC100T_IXIA_ROGUE_IC_PARENT_NETWORK_V4,
    ),
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
AC100T_FE_QOS_TEST_CONFIG = test_config_qos_scheduling(
    test_config_name="AC100T_FE_QOS_TEST_CONFIG",
    **_AC100T_HARDENING_PARAMS,
    ixia_rogue_interface=ac100t.AC100T_CPU_QUEUE_IXIA_ROGUE_INTERFACE,
    # Congestion traffic rides the otherwise-idle rogue port.
    ixia_congestion_interface=ac100t.AC100T_CPU_QUEUE_IXIA_ROGUE_INTERFACE,
    ixia_congestion_ic_parent_network_v6=ac100t.AC100T_IXIA_ROGUE_IC_PARENT_NETWORK_V6,
    congestion_peer_as_4byte=ac100t.AC100T_REMOTE_ROGUE_AS_4BYTE,
    congestion_prefix_count_v6=ac100t.AC100T_CONGESTION_PREFIX_COUNT_V6,
    congestion_prefix_start_v6=ac100t.AC100T_CONGESTION_PREFIX_START_V6,
    is_congestion_peer_confed=ac100t.AC100T_IS_ROGUE_PEER_CONFED,
)


# ===========================================================================
# Snake tests
# ===========================================================================
# Built from the snake/loopback standalone builder (gen_snake_test_config),
# one TestConfig per speed grade in AC100T_SNAKE_PORT_SPEEDS_GBPS -- the shape
# the reference MINIPACK3_STANDALONE_TEST_CONFIG_{400G,800G} configs use, so a
# failure names the speed it happened at. Each config runs the full
# gen_snake_playbooks suite (thrift/qsfp_util interface toggles, qsfp reset,
# agent warmboot/coldboot/crash, qsfp_service and fsdb restart/crash, BMC and
# microserver reboots) over the jumpered loops for that speed.
#
# Snake is single-DUT loopback, so this runs on one Steller Eagle unit rather
# than the full 4-DUT topology. Snake builds the TestConfig without a
# build-time netwhoami lookup (topology discovery is deferred to runtime), so
# no stub bypass is needed.
AC100T_SNAKE_800G_TEST_CONFIG = gen_snake_test_config(
    name="AC100T_SNAKE_800G_TEST_CONFIG",
    hostname=ac100t.AC100T_SNAKE_DEVICE_NAME,
    basset_pool=ac100t.AC100T_STANDALONE_BASSET_POOL,
    snake_configs=[
        taac_types.SnakeConfig(
            source=f"{ac100t.AC100T_SNAKE_DEVICE_NAME}:{source_interface}",
            destination=f"{ac100t.AC100T_SNAKE_DEVICE_NAME}:{destination_interface}",
            source_ip=source_ip,
            destination_ip=destination_ip,
        )
        for (
            source_interface,
            destination_interface,
            source_ip,
            destination_ip,
        ) in ac100t.AC100T_SNAKE_800G_LOOPS
    ],
    line_rate=ac100t.AC100T_SNAKE_LINE_RATE,
    traffic_item_name="AC100T_800G_IMIX",
    frame_size_settings=ixia_types.FrameSize(
        type=ixia_types.FrameSizeType.CUSTOM_IMIX,
        imix_weight=ac100t.AC100T_SNAKE_IMIX_WEIGHT,
    ),
    iteration=ac100t.AC100T_SNAKE_ITERATION,
)


AC100T_SNAKE_400G_TEST_CONFIG = gen_snake_test_config(
    name="AC100T_SNAKE_400G_TEST_CONFIG",
    hostname=ac100t.AC100T_SNAKE_DEVICE_NAME,
    basset_pool=ac100t.AC100T_STANDALONE_BASSET_POOL,
    snake_configs=[
        taac_types.SnakeConfig(
            source=f"{ac100t.AC100T_SNAKE_DEVICE_NAME}:{source_interface}",
            destination=f"{ac100t.AC100T_SNAKE_DEVICE_NAME}:{destination_interface}",
            source_ip=source_ip,
            destination_ip=destination_ip,
        )
        for (
            source_interface,
            destination_interface,
            source_ip,
            destination_ip,
        ) in ac100t.AC100T_SNAKE_400G_LOOPS
    ],
    line_rate=ac100t.AC100T_SNAKE_LINE_RATE,
    traffic_item_name="AC100T_400G_IMIX",
    frame_size_settings=ixia_types.FrameSize(
        type=ixia_types.FrameSizeType.CUSTOM_IMIX,
        imix_weight=ac100t.AC100T_SNAKE_IMIX_WEIGHT,
    ),
    iteration=ac100t.AC100T_SNAKE_ITERATION,
)


# ===========================================================================
# Registry
# ===========================================================================
# The ONE symbol the central registry (testconfigs/internal/__init__.py and
# internal/all.py, which spreads it into INTERNAL_TEST_CONFIGS) imports from
# this module. Append new ac100t TestConfigs here as each test class is bound,
# so adding a config never requires touching the registry files again.
AC100T_TEST_CONFIGS = [
    AC100T_CPU_QUEUE_TEST_CONFIG,
    AC100T_CRITICAL_SERVICES_TEST_CONFIG,
    AC100T_L2_NDP_ARP_HARDENING_TEST_CONFIG,
    AC100T_FE_QOS_TEST_CONFIG,
    AC100T_PLATFORM_HARDENING_TEST_CONFIG,
    AC100T_SNAKE_800G_TEST_CONFIG,
    AC100T_SNAKE_400G_TEST_CONFIG,
]
