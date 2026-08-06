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
    - Interface flaps                      (TODO -- deferred)
    - PTP tests                            (TODO -- deferred)
    - Speed flip tests                     (TODO -- mostly not feasible in
      OSS; feasible subset reuses existing speed_flip_test_configs.py)

As each additional class is added, instantiate its existing helper here and
register the resulting TestConfig constant (see cpu_queue section for the
registration pattern).
"""

from taac.testconfigs.fboss_solution_tests.speed_flip_test_configs import (
    build_subsume_churn_test_config,
    Circuit,
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
    device_name=w800.W800_DEVICE_NAME,
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
    device_name=w800.W800_DEVICE_NAME,
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
    good_ndp_entry_network_v6=w800.W800_GOOD_NDP_ENTRY_NETWORK_V6,
    rogue_ndp_entry_network_v6=w800.W800_ROGUE_NDP_ENTRY_NETWORK_V6,
    good_arp_entry_network_v4=w800.W800_GOOD_ARP_ENTRY_NETWORK_V4,
    rogue_arp_entry_network_v4=w800.W800_ROGUE_ARP_ENTRY_NETWORK_V4,
    prefix_limit=w800.W800_BGP_PREFIX_LIMIT,
    per_peer_max_route_limit=w800.W800_PER_PEER_MAX_ROUTE_LIMIT,
    downlink_peer_count=w800.W800_DOWNLINK_PEER_COUNT,
    uplink_peer_count=w800.W800_UPLINK_PEER_COUNT,
    rogue_peer_count=w800.W800_ROGUE_PEER_COUNT,
    remote_downlink_as_4byte=w800.W800_REMOTE_DOWNLINK_AS_4BYTE,
    remote_uplink_as_4byte=w800.W800_REMOTE_UPLINK_AS_4BYTE,
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
    ecmp_group_limit=w800.W800_ECMP_GROUP_LIMIT,
    good_ndp_entries_uplink=w800.W800_GOOD_NDP_ENTRIES_UPLINK,
    good_ndp_entries_downlink=w800.W800_GOOD_NDP_ENTRIES_DOWNLINK,
    rogue_ndp_entries=w800.W800_ROGUE_NDP_ENTRIES,
    good_arp_entries=w800.W800_GOOD_ARP_ENTRIES,
    rogue_arp_entries=w800.W800_ROGUE_ARP_ENTRIES,
    good_mac_entry_count=w800.W800_GOOD_MAC_ENTRY_COUNT,
    rogue_mac_entry_count=w800.W800_ROGUE_MAC_ENTRY_COUNT,
    bgp_induced_ecmp_group_count=w800.W800_BGP_INDUCED_ECMP_GROUP_COUNT,
    ixia_uplink_good_ndp_network=w800.W800_IXIA_UPLINK_GOOD_NDP_NETWORK,
    ixia_downlink_good_ndp_network=w800.W800_IXIA_DOWNLINK_GOOD_NDP_NETWORK,
    basset_pool=w800.W800_BASSET_POOL,
    ecmp_member_limit=w800.W800_ECMP_MEMBER_LIMIT,
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


# ===========================================================================
# Longevity tests
# ===========================================================================
# Built from the snake/loopback standalone builder (gen_snake_test_config) --
# the ONLY factory that emits the w800 test plan's test_72hr_longevity playbook
# (via gen_snake_longevity_playbook). Cloned from MINIPACK3_STANDALONE_TEST_CONFIG.
# The snake suite also includes shorter-duration longevity + link/service toggle
# playbooks; prune via playbooks_to_skip when tuning for w800. Snake builds the
# TestConfig object without a build-time netwhoami lookup (topology discovery is
# deferred to runtime), so no stub bypass is needed.
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
# Deferred classes (TODO -- see w800 test plan)
# ===========================================================================
# Interface flaps  -> W800_INTERFACE_FLAP_TEST_CONFIG   (TODO: bind next)
# PTP Test         -> W800_PTP_TEST_CONFIG              (TODO: sheet rows are
#                     all 'todo' -- no playbook defined yet)
# Speed flip       -> reboot / coldboot / 400G-200G->800G variants (TODO:
#                     hardcoded dataclass literals in speed_flip_test_configs.py
#                     with no device factory; need real w800 port maps). The
#                     remaining plan rows are not feasible in OSS.
