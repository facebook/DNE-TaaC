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

from taac.testconfigs.npi import (  # oss-rewrite-touch
    ac100t_constants as ac100t,
)
from taac.testconfigs.npi.cpu_queue_test_config import (
    create_npi_cpu_queue_test_config,
)

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
# Registry
# ===========================================================================
# The ONE symbol the central registry (testconfigs/internal/__init__.py and
# internal/all.py, which spreads it into INTERNAL_TEST_CONFIGS) imports from
# this module. Append new ac100t TestConfigs here as each test class is bound,
# so adding a config never requires touching the registry files again.
AC100T_TEST_CONFIGS = [
    AC100T_CPU_QUEUE_TEST_CONFIG,
]
