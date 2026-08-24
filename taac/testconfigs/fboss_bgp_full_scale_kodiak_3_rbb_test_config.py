# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""FBOSS_BGP_FULL_SCALE_KODIAK_3_RBB_TEST_CONFIG_QXS1.

Conveyor node binding (per `scripts/triage/dne_taac_checker.py`).

Built from the centralized `build_bgp_dc_test_config` factory. Scale parameters
preserve the original `SCALE_REDUCED_BGP_PATHS` values from `internal_test_configs.py`
verbatim (inlined at extraction time).
"""

from taac.testconfigs.fboss_solution_tests.fboss_wide_ecmp_test_config import (
    test_config_wide_ecmp,
)
from taac.testconfigs.internal.fboss_bgp_back_pressure_test_config import (
    test_config_back_pressure,
)
from taac.testconfigs.npi.thrift_hardening_test_config import (
    create_npi_thrift_hardening_test_config,
)
from taac.testconfigs.routing.factories.bgp_dc_chronos_node import (
    build_bgp_dc_test_config,
)


FBOSS_BGP_FULL_SCALE_KODIAK_3_RBB_TEST_CONFIG_QXS1 = build_bgp_dc_test_config(
    test_config_name="FBOSS_BGP_FULL_SCALE_KODIAK_3_RBB_TEST_CONFIG_QXS1",
    device_name="rb002-04.qxs1",
    local_mac_address="c2:18:50:9c:1f:1d",
    ixia_downlink_interface="eth1/64/1",
    ixia_uplink_interface="eth1/64/5",
    ixia_rogue_interface="eth9/16/1",
    peergroup_uplink_mimic_v6="PEERGROUP_RB_FADU_V6",
    peergroup_uplink_mimic_v4="PEERGROUP_RB_FADU_V4",
    peergroup_downlink_mimic_v6="PEERGROUP_RB_RB_V6",
    peergroup_downlink_mimic_v4="PEERGROUP_RB_RB_V4",
    peergroup_rogue_mimic_v6="PEERGROUP_RB_RB_V6",  # Setting Same as uplink
    peergroup_rogue_mimic_v4="PEERGROUP_RB_RB_V4",  # Setting Same as uplink
    route_map_uplink_ingress="PROPAGATE_EVERYTHING_PEERGROUP_RB_FADU_V6_IN",
    route_map_uplink_egress="PROPAGATE_EVERYTHING_PEERGROUP_RB_FADU_V6_OUT",
    route_map_downlink_ingress="PROPAGATE_RB_RB_IN",
    route_map_downlink_egress="PROPAGATE_RB_RB_OUT",
    route_map_rogue_ingress="PROPAGATE_RB_RB_IN",  # Setting Same as uplink
    route_map_rogue_egress="PROPAGATE_RB_RB_OUT",  # Setting Same as uplink
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
    remote_downlink_as_4byte=65409,
    remote_uplink_as_4byte=65271,
    remote_rogue_as_4byte=2500,
    is_uplink_peer_confed="False",
    is_downlink_peer_confed="False",
    is_rogue_peer_confed="False",  # Setting Same as uplink
    ixia_downlink_prefix_count_v6=5000,  # 10000 original
    ixia_uplink_prefix_count_v6=5000,  # 10000 original
    ixia_rogue_prefix_count_v6=2500,  # 17500 original
    ixia_downlink_prefix_count_v4=5000,  # 7500 original
    ixia_uplink_prefix_count_v4=5000,  # 7500 original
    ixia_rogue_prefix_count_v4=2500,  # 17500 original
    ixia_uplink_good_ndp_network="2401:db00:e50d:1101:9",
    ixia_downlink_good_ndp_network="2401:db00:e50d:1101:8",
    ixia_downlink_communities=[
        "65441:66",
    ],
    ixia_uplink_communities=[
        "65441:201",
    ],
    downlink_peer_tag="RSW",
    uplink_peer_tag="SSW",
    ecmp_group_limit=200,
    good_ndp_entries_uplink=100,
    good_ndp_entries_downlink=100,
    rogue_ndp_entries=50,
    good_arp_entries=100,
    rogue_arp_entries=100,
    good_mac_entry_count=100,
    rogue_mac_entry_count=200,
    bgp_induced_ecmp_group_count=50,
    basset_pool="dne.test",
    ecmp_member_limit=5000,
    playbooks_selected=[
        "test_agent_restart",
        "test_bgp_restart",
        "test_bgpd_crash",
        "test_longevity_prefix_flap_all_prefixes",
        "test_longevity_activate_deactivate_all_prefixes",
        "test_longevity_session_flap_all_prefixes",
        "test_longevity_prefix_flap_all_prefixes_plus_bgp_restart",
        "test_longevity_session_flap_all_prefixes_plus_bgp_restart",
        "test_longevity_rogue_prefix_session_enable",
        "test_longevity_no_prefix_no_session_flap",
        "test_longevity_continuous_toggle_device_group",
        "test_longevity_cold_start_with_prefix_and_session_oscillations",
        "test_longevity_frequent_best_path_computation",
    ],
)

FBOSS_WIDE_ECMP_KODIAK_3_RBB_TEST_CONFIG_QXS1 = test_config_wide_ecmp(
    test_config_name="FBOSS_WIDE_ECMP_KODIAK_3_RBB_TEST_CONFIG_QXS1",
    device_name="rb002-03.qxs1",
    local_mac_address="c2:18:50:9c:1f:1d",
    ixia_uplink_interface="eth1/64/1",
    ixia_downlink_interface="eth1/64/5",
    # BGP peering
    peergroup_uplink_mimic_v6="PEERGROUP_RB_FADU_V6",
    peergroup_uplink_mimic_v4="PEERGROUP_RB_FADU_V4",
    peergroup_downlink_mimic_v6="PEERGROUP_RB_RB_V6",
    peergroup_downlink_mimic_v4="PEERGROUP_RB_RB_V4",
    route_map_uplink_ingress="PROPAGATE_EVERYTHING_PEERGROUP_RB_FADU_V6_IN",
    route_map_uplink_egress="PROPAGATE_EVERYTHING_PEERGROUP_RB_FADU_V6_OUT",
    route_map_downlink_ingress="PROPAGATE_RB_RB_IN",
    route_map_downlink_egress="PROPAGATE_RB_RB_OUT",
    uplink_peer_tag="SSW",
    downlink_peer_tag="RSW",
    # IP addressing
    ixia_uplink_ic_parent_network_v6="2401:db00:e50d:11:9",
    ixia_uplink_ic_parent_network_v4="10.164.28",
    ixia_downlink_ic_parent_network_v6="2401:db00:e50d:11:8",
    ixia_downlink_ic_parent_network_v4="10.163.28",
    # AS numbers
    remote_uplink_as_4byte=65271,
    remote_downlink_as_4byte=65409,
    is_uplink_peer_confed="False",
    is_downlink_peer_confed="False",
    # Communities, pool
    ixia_uplink_communities=[
        "65441:201",
    ],
    ixia_downlink_communities=[
        "65441:66",
    ],
    basset_pool="dne.test",
    # ECMP parameters
    max_ecmp_width_per_group=20,
    max_ecmp_member_count=10000,
    # Prefix address space
    v6_uplink_prefix="6000",
    v4_uplink_prefix="102",
    v6_downlink_prefix="3000",
    v4_downlink_prefix="101",
    # Peer route limits
    per_peer_max_route_limit="25000",
)


FBOSS_BGP_BACK_PRESSURE_KODIAK_3_RBB_TEST_CONFIG_QXS1 = test_config_back_pressure(
    test_config_name="FBOSS_BGP_BACK_PRESSURE_KODIAK_3_RBB_TEST_CONFIG_QXS1",
    device_name="rb002-03.qxs1",
    local_mac_address="c2:18:50:9c:1f:1d",
    ixia_uplink_interface="eth1/64/1",
    ixia_downlink_interface="eth1/64/5",
    # BGP peering
    peergroup_uplink_mimic_v6="PEERGROUP_RB_FADU_V6",
    peergroup_uplink_mimic_v4="PEERGROUP_RB_FADU_V4",
    peergroup_downlink_mimic_v6="PEERGROUP_RB_RB_V6",
    peergroup_downlink_mimic_v4="PEERGROUP_RB_RB_V4",
    route_map_uplink_ingress="PROPAGATE_EVERYTHING_PEERGROUP_RB_FADU_V6_IN",
    route_map_uplink_egress="PROPAGATE_EVERYTHING_PEERGROUP_RB_FADU_V6_OUT",
    route_map_downlink_ingress="PROPAGATE_RB_RB_IN",
    route_map_downlink_egress="PROPAGATE_RB_RB_OUT",
    uplink_peer_tag="SSW",
    downlink_peer_tag="RSW",
    # IP addressing
    ixia_uplink_ic_parent_network_v6="2401:db00:e50d:11:9",
    ixia_uplink_ic_parent_network_v4="10.164.28",
    ixia_downlink_ic_parent_network_v6="2401:db00:e50d:11:8",
    ixia_downlink_ic_parent_network_v4="10.163.28",
    # AS numbers
    remote_uplink_as_4byte=65271,
    remote_downlink_as_4byte=65409,
    is_uplink_peer_confed="False",
    is_downlink_peer_confed="False",
    # Communities, pool
    ixia_uplink_communities=[
        "65441:201",
    ],
    ixia_downlink_communities=[
        "65441:66",
    ],
    basset_pool="dne.test",
    # Prefix address space
    v6_uplink_prefix="6000",
    v4_uplink_prefix="102",
    v6_downlink_prefix="3000",
    v4_downlink_prefix="101",
    # Peer route limits
    per_peer_max_route_limit="50000",
    # Control/Experiment group sizing
    control_peer_count=5,
    experiment_peer_count=10,
    control_prefix_count_v6=500,
    control_prefix_count_v4=500,
    experiment_prefix_count_v6=1500,
    experiment_prefix_count_v4=500,
)


# ---------------------------------------------------------------------------
# Kodiak-3 RBB (`rb002-03.qxs1`) fabric-uplink flap port list.
#
# Discovered live via `fboss2 show interface` — the only non-IXIA ports in
# `up` state, each an 800G link to an `rb002-0X.qxt1` neighbour. The two IXIA
# ports (`eth1/64/1` / `eth1/64/5`) are deliberately EXCLUDED: flapping those
# would tear down the mimic BGP peers the THFT validation chain asserts on.
# ---------------------------------------------------------------------------
KODIAK3_RBB_QXS1_FABRIC_FLAP_PORTS = [
    "eth1/5/1",  # rb002-01.qxt1:eth1/9/1
    "eth1/8/1",  # rb002-02.qxt1:eth1/9/1
    "eth1/9/1",  # rb002-03.qxt1:eth1/9/1
    "eth1/12/1",  # rb002-04.qxt1:eth1/9/1
]


# FBOSS_THRIFT_HARDENING_KODIAK_3_RBB_TEST_CONFIG_QXS1 — the THFT_001..005
# thrift-stress + qsfp-flap suite on the Kodiak-3 RBB (`rb002-03.qxs1`;
# netwhoami `hw=MORGAN800CC`, `chmodel=CHMODEL_CISCO_KODIAK3`,
# `asic=GRAPHENE200`), built from the same centralized NPI factory that backs
# the IcePack GTSW and w800 THFT configs.
#
# BGP identity params (peer groups, route maps, IC parent networks, remote AS,
# communities, peer tags) are taken verbatim from the two sibling rb002-03
# configs above so all three programme the RBB peer groups consistently. The
# SCALE params instead mirror the validated GTSW THFT config (8 peers x 500
# prefixes per direction/AFI) rather than the RBB BGP-scale numbers: THFT has
# no user-traffic plane, so BGP here is only scaffolding for the
# BGP_SESSION_ESTABLISH precheck + BGP_PEER_ROUTE snapshot.
#
# `requests_per_burst=10000` (= 70K concurrent calls per burst across the 7
# read-only APIs) is safe here: `thriftApiToRateLimitInQps` is populated with
# 140 entries in `/etc/coop/agent/current` on this DUT, and the factory's
# `assert_thrift_rate_limit_enabled` setup task fails fast if that ever
# regresses.
#
# `service_restart_services` is left at the check's default (all 7 FBOSS
# daemons) — unlike the IcePack GTSW, this DUT does run openr.
FBOSS_THRIFT_HARDENING_KODIAK_3_RBB_TEST_CONFIG_QXS1 = (
    create_npi_thrift_hardening_test_config(
        test_config_name="FBOSS_THRIFT_HARDENING_KODIAK_3_RBB_TEST_CONFIG_QXS1",
        device_name="rb002-03.qxs1",
        # eth0 NIC MAC — what `async_get_serf_device_mac_address` resolves when
        # this field is left empty. NOT the `c2:18:50:9c:1f:1d` the sibling RBB
        # configs above carry; that is a placeholder shared by several
        # unrelated DUTs.
        local_mac_address="c8:78:f7:65:c3:fe",
        ixia_uplink_interface="eth1/64/1",
        ixia_downlink_interface="eth1/64/5",
        # BGP peering
        peergroup_uplink_mimic_v6="PEERGROUP_RB_FADU_V6",
        peergroup_uplink_mimic_v4="PEERGROUP_RB_FADU_V4",
        peergroup_downlink_mimic_v6="PEERGROUP_RB_RB_V6",
        peergroup_downlink_mimic_v4="PEERGROUP_RB_RB_V4",
        # Must name policy statements that ALREADY EXIST in the DUT's bgpcpp
        # config. This factory only references route maps — unlike the
        # BGP-hardening conveyor factory, it never creates policy statements.
        # So the `PROPAGATE_EVERYTHING_<peergroup>_IN/OUT` names the sibling
        # RBB configs above pass are NOT valid here: that factory generates
        # them at setup time. Referencing a missing policy makes bgpd throw
        # "Missing ingress policy ... needed for peer group" out of
        # `Config::verifyIfPoliciesExist` and crash-loop on every restart.
        # rb002-03 has exactly: ORIGINATE_RBB_DOMAIN_AGG, PROPAGATE_RB_FADU_IN
        # /OUT, PROPAGATE_RB_RB_IN/OUT.
        route_map_uplink_ingress="PROPAGATE_RB_FADU_IN",
        route_map_uplink_egress="PROPAGATE_RB_FADU_OUT",
        route_map_downlink_ingress="PROPAGATE_RB_RB_IN",
        route_map_downlink_egress="PROPAGATE_RB_RB_OUT",
        uplink_peer_tag="FADU",
        downlink_peer_tag="RB",
        # IP addressing
        ixia_uplink_ic_parent_network_v6="2401:db00:e50d:11:9",
        ixia_uplink_ic_parent_network_v4="10.164.28",
        ixia_downlink_ic_parent_network_v6="2401:db00:e50d:11:8",
        ixia_downlink_ic_parent_network_v4="10.163.28",
        # AS numbers
        remote_uplink_as_4byte=65271,
        remote_downlink_as_4byte=65409,
        remote_as_4_byte_step=1,
        is_uplink_peer_confed="False",
        is_downlink_peer_confed="False",
        # Scale — scaffolding only, mirrors the GTSW THFT reference
        unique_prefix_limit="5000",
        per_peer_max_route_limit="20000",
        uplink_peer_count=8,
        downlink_peer_count=8,
        ixia_uplink_prefix_count_v6=500,
        ixia_uplink_prefix_count_v4=500,
        ixia_downlink_prefix_count_v6=500,
        ixia_downlink_prefix_count_v4=500,
        # Communities must satisfy the DUT's real ingress policies (see the
        # route_map note above) — the sibling RBB configs' `65441:201` appears
        # nowhere in either policy and only worked there because that factory
        # binds a generated permit-all policy instead.
        #
        # Each direction must clear the INGRESS policy on its own peer group
        # AND the EGRESS policy on the far peer group, since the DUT transits
        # routes between them:
        #   uplink   IXIA -> PROPAGATE_RB_FADU_IN, then PROPAGATE_RB_RB_OUT
        #   downlink IXIA -> PROPAGATE_RB_RB_IN,   then PROPAGATE_RB_FADU_OUT
        #
        # `65529:11610` is in the accept list of BOTH PROPAGATE_RB_FADU_IN
        # (term RULE_IBN_EDGE_IN_RB_FADU_IN_340) and PROPAGATE_RB_FADU_OUT
        # (term RULE_IBN_EDGE_OUT_RB_FADU_OUT_930), so one aggregate serves
        # both directions. Both of those IBN blocks end in a term with
        # term_miss_action=DENY (_360 / _980), so an aggregate is mandatory.
        #
        # Adjacency-hop tag is mandatory too: A_HOP1 for the directly-adjacent
        # FADU, A_HOP2 for the 2-hop RB. `65441:65` clears
        # RULE_RB_FADU_IN_A_HOP2_730 (DENY) inbound, and drives
        # RULE_RB_RB_OUT_A_HOP1_980 outbound, which ADDs `65446:201` — required
        # by LOCAL_ACCEPT_RULE_990 (DENY) — while rewriting A_HOP1 -> A_HOP2.
        # `65441:66` clears RULE_RB_RB_IN_A_HOP2_860 (DENY) on the downlink.
        #
        # `65446:30` (live) is not a gate — it only hits RESET_LOCAL_PREF
        # (NEXT_TERM). Safe alongside `65441:65`: the three DENY terms
        # RULE_RB_DENY_A_HOP1_A_HOP2{,_LIVE,_DRAIN}_9[456]0 use
        # BooleanOperator.AND, and each additionally requires a
        # `6544[2-5]:65` tag we never send.
        ixia_uplink_communities=[
            "65529:11610",  # IBN aggregate, accepted by FADU_IN + FADU_OUT
            "65441:65",  # A_HOP1 (adjacent FADU)
            "65446:30",  # live
        ],
        ixia_downlink_communities=[
            "65529:11610",  # IBN aggregate, accepted by FADU_IN + FADU_OUT
            "65441:66",  # A_HOP2 (2-hop RB)
            "65446:30",  # live
        ],
        basset_pool="dne.test",
        # Disruption
        stsw_flap_ports=KODIAK3_RBB_QXS1_FABRIC_FLAP_PORTS,
        test_duration_s=14400,  # THFT_001 = 4 hr prod (override to 600 for smoke)
        restart_test_duration_s=3600,  # THFT_002..005 = 1 hr each -> 4 hr total
        requests_per_burst=10000,
        # Thrift storm and qsfp flap run as two SEPARATE periodic tasks, so
        # each gets a timeout matched to its own runtime. Both left at the
        # factory defaults: 60s for the rate-limited thrift burst, 900s for
        # the flap (~7.2s per flap measured on this DUT x 100 = ~720s).
    )
)
