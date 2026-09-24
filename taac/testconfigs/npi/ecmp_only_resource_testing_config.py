# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe

"""
ECMP-ONLY Resource Testing Configuration (platform-generic).

One factory, one instance per platform under test. Currently:
  - KO3_ECMP_ONLY_RESOURCE_TESTING     Kodiak-3 / G200      rb002-02.qxt1
  - FUJI_SSW_ECMP_ONLY_RESOURCE_TESTING Fuji / Tomahawk4     ssw002.s002.f01.qzd1

================================ IMPORTANT ================================
THIS TESTCONFIG TESTS ECMP RESOURCES ONLY — it never exercises DLB.

For KO3 that is forced: the silicon has no DLB. For Tomahawk4 it is a CHOICE —
TH4 does advertise `Feature::ARS` (see `Tomahawk4Asic.cpp`), so DLB coverage on
Fuji has to come from the 3-port Wedge400/IcePack-shaped configs instead. This
config deliberately omits ALL DLB-specific machinery either way:

  - NO RDMA-IB packet headers. DLB engagement on TH-class silicon required
    `DSF_RDMA_IB_PACKET_HEADERS` (AR=1, RoCEv2/UDP 4791, TC2/DSCP 56) so flows
    were DLB-eligible. Here traffic items use the DEFAULT stack (plain
    TCP/IPv6) with NO explicit `packet_headers`.
  - NO `dlb_resource_stickiness_check` `expected_totals={"dlb": ...}` assertion.
    ECMP groups carry no switching-mode override, so the resource analysis
    reports them under its "Default (DLB)" (= default switching mode) column. We
    assert ONLY `total` (group count) and `max_next_hops` (group width) — the
    platform-agnostic ECMP metrics — never the dlb/other-modes split.
  - NO DLB spillover playbook.

Sizing law (validated on Wedge400/TH3, sum-of-widths member accounting):
    members consumed (per network group) = network_group_multiplier
    groups programmed                    = network_group_multiplier / ecmp_width

So the two utilization profiles are driven purely by `ecmp_width` (the member /
group playbooks toggle width at runtime via `modify_network_group_ecmp_width`):
  - GROUP utilization:  narrow groups -> fill the GROUP table
  - MEMBER utilization: wide groups   -> fill the MEMBER table

The "Rouge" overflow class advertises EXTRA prefixes whose groups/members exceed
the platform limits; in the overcommit playbooks they must NOT program
(ResourceAccountant rejects them) -> 100% packet loss on Rouge traffic while
Main stays at 0%.

Every per-platform number (group/member ceilings, widths, Rouge multiplier, NDP
pool) lives in `ECMP_RESOURCE_PROFILES[asic]` in `dlb_ecmp_platform_constants.py`,
and all addressing lives in the `EcmpNhPool` passed as `pool`. Nothing platform-
specific is hardcoded below — add a platform by adding a profile + a pool + an
instance, not by editing the factory.
==========================================================================

Mirrors `testconfigs/ai_bb/wedge400_ecmp_resource_testing_config.py` shape, but
collapsed to a 2-port topology (no DLB-vs-non-DLB split needed):
  - Source port: pure L3 traffic source, no BGP.
  - Rogue port:  hosts the Main (in-budget ECMP) + Rouge (overflow) BGP sessions
                 and the NDP-supporting next-hop device group.
"""

import json
import os

from ixia.ixia import types as ixia_types
from taac.health_checks.healthcheck_definitions import (
    create_core_dumps_snapshot_check,
    create_prefix_limit_check,
    create_systemctl_active_state_check,
)
from taac.playbooks.dlb_ecmp_platform_constants import (
    ECMP_RESOURCE_PROFILES,
    EcmpAsic,
)
from taac.playbooks.playbook_definitions import (
    create_ecmp_only_groups_playbooks,
    create_ecmp_only_longevity_playbooks,
    create_ecmp_only_members_playbooks,
)
from taac.task_definitions import (
    create_configure_parallel_bgp_peers_task,
    create_coop_apply_patchers_task,
    create_coop_register_patcher_task,
    create_coop_unregister_patchers_task,
)
from taac.testconfigs.npi.ecmp_csvs import gen_ecmp_csv
from taac.testconfigs.npi.ecmp_csvs.ecmp_nh_pools import (
    FUJI_SSW_MAIN_ECMP_POOL,
    KO3_MAIN_ECMP_POOL,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import Playbook, TestConfig


# Main (in-budget) ECMP class address layout. The Member-util playbook changes
# only width/multiplier in place at runtime (the address layout is preserved),
# so these are needed only here for the Main CustomNetworkGroupConfig. The Main
# prefix itself is NOT here — it comes from `pool.prefix_base`, so the CSV the
# generator writes and the baseline NetworkGroup can never drift apart.
MAIN_PREFIX_LENGTH = 64
MAIN_NEXTHOP_INCREMENTS = "::1"

# Rouge (overflow) class. Platform-independent: the Rouge prefixes only have to
# be distinct from the Main pool's, and its SIZE (how far over the limit it
# pushes) comes from the per-ASIC profile, not from here.
ROUGE_NETWORK_GROUP_NAME = "ROUGE_ECMP_PREFIXES"
ROUGE_PREFIX_START_VALUE = "5000:ff::"
ROUGE_PREFIX_LENGTH = 64
ROUGE_NEXTHOP_INCREMENTS = "::1"

# BGP config namespaces the IXIA peer group + its policies must be written into.
#
# MUST match what `ConfigureParallelBgpPeersTask` uses for the PEERS themselves
# (tasks/all.py: `configs = ["bgpcpp", "bgpcpp_softdrain"]`). Registering the
# peer group on "bgpcpp" alone leaves bgpcpp_softdrain holding a peer that
# references a peer group defined nowhere in that variant, and bgpd treats it as
# fatal the moment it loads it:
#     terminate called after throwing an instance of 'facebook::bgp::BgpError'
#       what(): Unsupported config: peer_group '<name>' does not exist for peer <ip>
# -> SIGABRT -> systemd restart -> same bad config -> crash loop (observed at
# NRestarts=114 on ssw002.s002.f01.qzd1).
BGP_PEER_CONFIG_NAMES: list[str] = ["bgpcpp", "bgpcpp_drain", "bgpcpp_softdrain"]


# =============================================================================
# ECMP add-path CSV generation.
#
# Two CSVs per platform (GROUP-table-maximizing and WIDTH-maximizing), sized
# from `ECMP_RESOURCE_PROFILES[asic]` -- groups / members / width / unique-NH
# cap are NEVER hardcoded here -- and addressed from the `EcmpNhPool`. The
# anchor-pair construction keeps the union of unique next-hops within the
# platform cap (`max_unique_next_hops`). `generate_ecmp_csvs` writes the
# committed reference copies under `ecmp_csvs/csvs/`; run this module as
# __main__ to (re)generate them for every platform.
#
# The filename stem comes from `pool.csv_prefix`, NOT from `pool.name`: the
# generated path is passed to `apply_pool_mutations` as a step argument and is
# therefore part of the TestConfig golden hash, so each pool pins its own stem.
# =============================================================================
ECMP_CSV_DIR: str = os.path.join(
    os.path.dirname(os.path.abspath(gen_ecmp_csv.__file__)), "csvs"
)


def ecmp_csv_filenames(pool) -> dict:
    """``{key: filename}`` for the two CSVs a pool generates."""
    return {
        "max_groups": f"{pool.csv_prefix}_ecmp_max_groups.csv",
        "max_width": f"{pool.csv_prefix}_ecmp_max_width.csv",
    }


def generate_ecmp_csvs(
    asic: EcmpAsic,
    pool,
    out_dir: str = ECMP_CSV_DIR,
) -> dict:
    """Generate a platform's ECMP CSVs from its ASIC profile + NH pool.

    Sizing comes from `ECMP_RESOURCE_PROFILES[asic]` (not hardcoded); addressing
    and filenames from `pool`. Returns ``{key: csv_path}`` for keys
    ``max_groups`` / ``max_width``.
    """
    profile = ECMP_RESOURCE_PROFILES[asic]
    filenames = ecmp_csv_filenames(pool)
    os.makedirs(out_dir, exist_ok=True)
    paths = {}
    for key, rows in gen_ecmp_csv.gen_for_profile_pool(profile, pool).items():
        path = os.path.join(out_dir, filenames[key])
        gen_ecmp_csv.write_csv(path, rows)
        paths[key] = path
    return paths


# Policy term that unconditionally accepts all routes (ALWAYS match, no actions
# → bgpd defaults to PERMIT).
_PERMIT_ALL_POLICY_TERM = {
    "name": "RULE_ACCEPT_ALL",
    "description": "Unconditionally accept all prefixes",
    "policy_match_entries": {
        "name": "",
        "description": "",
        "match_logic_type": 1,
        "match_entries": [
            {
                "type": 20,  # ALWAYS
                "match_logic_type": 0,
            }
        ],
    },
}


# =============================================================================
# SECTION 4.2: IXIA PEER-GROUP HELPER
# Dedicated eBGP peer group (AddPath BOTH) for multi-path advertisement of the
# Main + Rouge ECMP prefixes.
# =============================================================================
def get_ixia_peer_group_tasks(
    device_name,
    peergroup_uplink_mimic_v6,
    peer_group_description,
):
    """Return COOP patcher tasks configuring the eBGP peer group toward IXIA.

    `peer_group_description` is passed in rather than derived: it is a patcher
    argument and therefore part of the TestConfig golden hash, so an existing
    instance's wording has to stay pinned.

    ORDER MATTERS. The two policy statements are registered BEFORE the peer
    group that references them. COOP regenerates the daemon config after EVERY
    registration, so registering the peer group first leaves a window in which
    the config names an ingress/egress policy that does not exist yet; if bgpd
    reloads during that window it aborts:
        terminate called after throwing an instance of 'facebook::bgp::BgpError'
          what(): Missing ingress policy (...) needed for peer group (...)
    -> SIGABRT -> restart -> same window -> crash loop. The `a_` name prefix
    only orders patchers WITHIN a single apply, so it cannot close this gap.

    TODO: replace `ingress_policy_name`/`egress_policy_name` with the device's
    real community-gated policy chain (see IcePack note: a fresh empty policy
    leaves FIB at 0).
    """
    return [
        create_coop_register_patcher_task(
            hostname=device_name,
            config_names=BGP_PEER_CONFIG_NAMES,
            patcher_name=f"a_add_bgp_policy_statement_PROPAGATE_EVERYTHING_{peergroup_uplink_mimic_v6}_IN",
            task_name="coop_register_patcher",
            patcher_args={
                "name": f"PROPAGATE_EVERYTHING_{peergroup_uplink_mimic_v6}_IN",
                "description": "Policy for IXIA IN",
                "policy_entries": json.dumps([_PERMIT_ALL_POLICY_TERM]),
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_names=BGP_PEER_CONFIG_NAMES,
            patcher_name=f"a_add_bgp_policy_statement_PROPAGATE_EVERYTHING_{peergroup_uplink_mimic_v6}_OUT",
            task_name="coop_register_patcher",
            patcher_args={
                "name": f"PROPAGATE_EVERYTHING_{peergroup_uplink_mimic_v6}_OUT",
                "description": "Policy for IXIA OUT",
                "policy_entries": json.dumps([_PERMIT_ALL_POLICY_TERM]),
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_names=BGP_PEER_CONFIG_NAMES,
            patcher_name=f"add_peer_group_patcher_{peergroup_uplink_mimic_v6}",
            task_name="add_peer_group_patcher",
            patcher_args={
                "name": peergroup_uplink_mimic_v6,
                "description": peer_group_description,
                "disable_ipv4_afi": "True",
                "disable_ipv6_afi": "False",
                "ingress_policy_name": f"PROPAGATE_EVERYTHING_{peergroup_uplink_mimic_v6}_IN",
                "egress_policy_name": f"PROPAGATE_EVERYTHING_{peergroup_uplink_mimic_v6}_OUT",
                "bgp_peer_timers_hold_time_seconds": "30",
                "bgp_peer_timers_keep_alive_seconds": "10",
                "bgp_peer_timers_out_delay_seconds": "0",
                "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                "peer_tag": "IXIA",
                "max_routes": "900000",
                "warning_only": "True",
                "warning_limit": "0",
                "next_hop_self": "False",
                "add_path": "BOTH",
                "is_confed_peer": "False",
                "is_passive": "False",
                "v4_over_v6_nexthop": "False",
                "link_bandwidth_bps": "auto",
            },
            py_func_name="add_peer_group_patcher",
        ),
    ]


# =============================================================================
# SECTION 6: TEST CONFIG FACTORY FUNCTION
# =============================================================================
def test_config_for_ecmp_only_resource_testing(
    test_config_name,
    device_name,
    ixia_source_interface,
    ixia_rogue_interface,
    peergroup_uplink_mimic_v6,
    peer_group_description,
    ixia_source_ic_parent_network_v6,
    ixia_rogue_ic_parent_network_v6,
    ixia_nexthop_supporting_ndp_network,
    ixia_nexthop_supporting_ndp_gateway,
    remote_uplink_as_4byte,
    is_uplink_peer_confed,
    prefix_limit,
    asic,
    pool,
    configure_vlans_patcher_name,
    add_bgp_peers_patcher_name="add_bgp_peers_dut",
    interconnect_prefix_length=64,
    baseline_network_group_multiplier=100,
    baseline_ecmp_width=None,
    enable_ixia_ports=False,
    # Playbook scale knobs. Defaults equal the playbook factories' own defaults,
    # so an instance that omits them serializes exactly as before. Lower them
    # for a smoke run that exercises all 18 playbooks quickly.
    disruptive_iterations=5,
    disruptive_settle_seconds=300,
    ndp_flap_iterations=60,
    cold_start_iterations=13,
    longevity_stabilization_seconds=300,
    playbooks=None,
    direct_ixia_connections=None,
    basset_pool=None,
):
    """ECMP-ONLY Resource Testing configuration (2-port, no DLB exercised).

    - Source port: pure L3 traffic source (no BGP).
    - Rogue port:  Main (in-budget ECMP) + Rouge (overflow) eBGP sessions and
      the NDP-supporting next-hop device group.

    Platform-specific inputs, neither of them hardcoded in this module:
      `asic` -> ECMP table sizing (Main/Rouge multipliers + widths, NDP pool,
                expected group/width counts) via `ECMP_RESOURCE_PROFILES` in
                dlb_ecmp_platform_constants.py. Adjust limits there, not here.
      `pool` -> an `EcmpNhPool`: Main prefix base, next-hop /64 and host start,
                unique-NH budget, IxNetwork NetworkGroup name, CSV filename stem.

    `peer_group_description` and `configure_vlans_patcher_name` /
    `add_bgp_peers_patcher_name` are explicit parameters rather than derived
    strings because they are COOP patcher arguments and therefore part of the
    TestConfig golden hash — an existing instance must keep passing its original
    literal or its manifest entry changes.
    """
    if pool.size != ECMP_RESOURCE_PROFILES[asic].max_unique_next_hops:
        raise ValueError(
            f"{test_config_name}: pool.size={pool.size} != max_unique_next_hops="
            f"{ECMP_RESOURCE_PROFILES[asic].max_unique_next_hops} for {asic}"
        )

    # Opt-in so the test owns the ports' admin state instead of inheriting
    # whatever the device's production config or a DC-wide override happens to
    # leave them at. Off by default: turning it on adds a setup task, which
    # changes an existing instance's golden hash.
    #
    # `a_` prefix because patcher_name is the execution order (alphabetical) and
    # the ports must come up before `configure_vlans` assigns their RIF IPs.
    # patcher_args is a flat {interface: "enable"|"disable"} map — that is what
    # PythonPatchApplier.change_port_admin_state actually reads (patchers.py),
    # NOT a port_ids/admin_state pair.
    enable_ixia_ports_tasks = (
        [
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="agent",
                patcher_name="a_enable_ixia_ports",
                task_name="coop_register_patcher",
                patcher_args={
                    ixia_source_interface: "enable",
                    ixia_rogue_interface: "enable",
                },
                py_func_name="change_port_admin_state",
            )
        ]
        if enable_ixia_ports
        else []
    )
    profile = ECMP_RESOURCE_PROFILES[asic]
    # Baseline shape of the Main NetworkGroup at IXIA-setup time, BEFORE any
    # playbook injects its CSV via `apply_pool_mutations`.
    #
    # The historical values (multiplier=100, width=group_util_width) contradict
    # the "minimal shell" comment on the CustomNetworkGroupConfig below, and on
    # Elbert they make IxNetwork reject the route property at commit:
    #   POST .../ipv6PrefixPools/1/bgpV6IPRouteProperty -> 400
    #   code 5500  Unable to add ...
    #   code 10000 Commit operation failed
    # The NetworkAddress multivalue is built as start + one increment of
    # `count=ecmp_width`, i.e. 1+27=28 values, while the NetworkGroup declares
    # Multiplier=100 rows. Keep these overridable so an instance can boot the
    # genuinely minimal 1/1 shell the comment describes.
    main_network_group_multiplier = baseline_network_group_multiplier
    main_ecmp_width = (
        profile.group_util_width if baseline_ecmp_width is None else baseline_ecmp_width
    )
    rouge_network_group_multiplier = profile.rouge_network_group_multiplier
    rouge_ecmp_width = profile.rouge_ecmp_width
    ndp_pool_multiplier = profile.ndp_pool_multiplier

    # Runtime CSV generation (ephemeral, NOT in fbcode). Sized from the profile,
    # addressed from KO3_MAIN_ECMP_POOL; the per-playbook apply_pool_mutations
    # setup steps feed these /tmp paths. The GROUP CSV goes to the Group
    # playbooks and the WIDTH/MEMBER CSV to the Member playbooks. Committed
    # reference copies live in ecmp_csvs/csvs/ (regenerate via this module's
    # __main__). The Main NetworkGroup boots as a MINIMAL shell (1 prefix /
    # width 1) that these CSVs overwrite -- a minimal baseline keeps IXIA setup
    # from advertising a shape that exceeds the platform unique-NH cap before the
    # CSV lands.
    csv_paths = generate_ecmp_csvs(
        asic=asic,
        pool=pool,
        out_dir=os.path.join("/tmp/ecmp_csvs", asic.value, pool.name),
    )

    tc_prechecks = [
        create_systemctl_active_state_check(
            services=[
                hc_types.Service.WEDGE_AGENT,
                hc_types.Service.BGPD,
                hc_types.Service.QSFP_SERVICE,
                hc_types.Service.FSDB,
                hc_types.Service.FBOSS_SW_AGENT,
                hc_types.Service.FBOSS_HW_AGENT_0,
            ],
        ),
    ]

    tc_postchecks = [
        create_systemctl_active_state_check(
            services=[
                hc_types.Service.WEDGE_AGENT,
                hc_types.Service.BGPD,
                hc_types.Service.QSFP_SERVICE,
                hc_types.Service.FSDB,
                hc_types.Service.FBOSS_SW_AGENT,
                hc_types.Service.FBOSS_HW_AGENT_0,
            ],
        ),
        create_prefix_limit_check(prefix_limit=prefix_limit),
    ]

    tc_snapshot_checks = [
        create_core_dumps_snapshot_check(),
    ]

    def _add_tc_checks_to_playbook(pb: Playbook) -> Playbook:
        new_prechecks = tc_prechecks + list(pb.prechecks or [])
        new_postchecks = list(pb.postchecks or []) + tc_postchecks

        if pb.skip_test_config_snapshot_checks:
            new_snapshot_checks = list(pb.snapshot_checks or [])
        else:
            new_snapshot_checks = list(pb.snapshot_checks or []) + tc_snapshot_checks

        return pb(
            prechecks=new_prechecks,
            postchecks=new_postchecks,
            snapshot_checks=new_snapshot_checks,
            skip_test_config_snapshot_checks=False,
        )

    def _add_tc_checks_to_playbooks(playbooks: list[Playbook]) -> list[Playbook]:
        return [_add_tc_checks_to_playbook(pb) for pb in playbooks]

    endpoints = [
        taac_types.Endpoint(
            name=device_name,
            ixia_ports=[
                ixia_source_interface,
                ixia_rogue_interface,
            ],
            dut=True,
            direct_ixia_connections=(
                direct_ixia_connections if direct_ixia_connections else []
            ),
        ),
    ]

    return TestConfig(
        name=test_config_name,
        ixia_protocol_verification_timeout=10,
        skip_ixia_protocol_verification=True,
        basset_pool=basset_pool,
        endpoints=endpoints,
        setup_tasks=[
            create_coop_unregister_patchers_task(device_name),
        ]
        + enable_ixia_ports_tasks
        + get_ixia_peer_group_tasks(
            device_name, peergroup_uplink_mimic_v6, peer_group_description
        )
        + [
            # Assign the DUT-side interconnect RIF IPs AND configure the eBGP
            # sessions in one step (mirrors wedge400). Without an agent-side RIF
            # IP the DUT has no L3 address to source BGP from or to answer the
            # IXIA's NDP, so traffic never resolves. The source interface gets
            # only its gateway IP (no BGP); the rogue interface gets its gateway
            # IP plus the Main (peer ::b) and Rouge (peer ::c) eBGP sessions.
            create_configure_parallel_bgp_peers_task(
                hostname=device_name,
                configure_vlans_patcher_name=configure_vlans_patcher_name,
                add_bgp_peers_patcher_name=add_bgp_peers_patcher_name,
                config_json=json.dumps(
                    {
                        ixia_source_interface: [
                            {
                                "starting_ip": f"{ixia_source_ic_parent_network_v6}::a",
                                "increment_ip": "0:0:0:0::0",
                                "prefix_length": interconnect_prefix_length,
                                "num_sessions": 1,
                                "gateway_starting_ip": f"{ixia_source_ic_parent_network_v6}::b",
                                "gateway_increment_ip": "0:0:0:0::0",
                                "peer_group_name": peergroup_uplink_mimic_v6,
                                "remote_as_4_byte": remote_uplink_as_4byte,
                                "description": "Source L3 RIF IP (interface only, no BGP)",
                                "config_only_interface_ip": True,
                            },
                        ],
                        ixia_rogue_interface: [
                            {
                                "starting_ip": f"{ixia_rogue_ic_parent_network_v6}::a",
                                "increment_ip": "0:0:0:0::0",
                                "prefix_length": interconnect_prefix_length,
                                "num_sessions": 2,
                                "gateway_starting_ip": f"{ixia_rogue_ic_parent_network_v6}::b",
                                "gateway_increment_ip": "0:0:0:0::1",
                                "peer_group_name": peergroup_uplink_mimic_v6,
                                "remote_as_4_byte": remote_uplink_as_4byte,
                                "description": "Main + Rouge eBGP sessions",
                            },
                        ],
                    }
                ),
            ),
            create_coop_apply_patchers_task(
                hostnames=[device_name],
                do_warmboot=True,
            ),
        ],
        teardown_tasks=[
            create_coop_unregister_patchers_task(device_name),
        ],
        basic_traffic_item_configs=[
            # Main ECMP traffic: source -> Main network group (in-budget).
            # Expect 0% loss. NO packet_headers -> default TCP/IPv6 stack.
            taac_types.BasicTrafficItemConfig(
                name=f"{ixia_source_interface.upper().replace('/', '_')}_TO_MAIN_ECMP_TRAFFIC",
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_source_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_rogue_interface}",
                        device_group_index=0,
                        network_group_index=0,
                    ),
                ],
                bidirectional=False,
                merge_destinations=True,
                line_rate=10,
                frame_size_settings=ixia_types.FrameSize(
                    type=ixia_types.FrameSizeType.FIXED,
                    fixed_size=1024,
                ),
                src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
                traffic_type=ixia_types.TrafficType.IPV6,
                tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
            ),
            # Rouge overflow traffic: source -> Rouge network group (over-budget).
            # In overcommit playbooks these routes do NOT program -> expect 100% loss.
            taac_types.BasicTrafficItemConfig(
                name=f"{ixia_source_interface.upper().replace('/', '_')}_TO_ROUGE_TRAFFIC",
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_source_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_rogue_interface}",
                        device_group_index=1,
                        network_group_index=0,
                    ),
                ],
                bidirectional=False,
                merge_destinations=True,
                line_rate=10,
                frame_size_settings=ixia_types.FrameSize(
                    type=ixia_types.FrameSizeType.FIXED,
                    fixed_size=1024,
                ),
                src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
                traffic_type=ixia_types.TrafficType.IPV6,
                tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
            ),
        ],
        basic_port_configs=[
            # Source port (no BGP, pure L3 traffic source).
            taac_types.BasicPortConfig(
                endpoint=f"{device_name}:{ixia_source_interface}",
                device_group_configs=[
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        tag_name="SOURCE_L3_TRAFFIC",
                        multiplier=1,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_source_ic_parent_network_v6}::b",
                            increment_ip="::",
                            gateway_starting_ip=f"{ixia_source_ic_parent_network_v6}::a",
                            gateway_increment_ip="::",
                            mask=interconnect_prefix_length,
                        ),
                    ),
                ],
            ),
            # Rogue port: Main + Rouge ECMP BGP sessions + NDP-supporting NH pool.
            taac_types.BasicPortConfig(
                endpoint=f"{device_name}:{ixia_rogue_interface}",
                device_group_configs=[
                    # DG 0: Main in-budget ECMP class. Width is the GROUP-util
                    # default; the MEMBER-util playbooks widen it at runtime.
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        tag_name="MAIN_ECMP_RESOURCE",
                        enable=True,
                        multiplier=1,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_rogue_ic_parent_network_v6}::b",
                            increment_ip="::",
                            gateway_starting_ip=f"{ixia_rogue_ic_parent_network_v6}::a",
                            gateway_increment_ip="::",
                            mask=interconnect_prefix_length,
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_uplink_as_4byte,
                            local_as_increment=0,
                            enable_4_byte_local_as=True,
                            bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                            is_confed=is_uplink_peer_confed == "True",
                            bgp_capabilities=[
                                ixia_types.BgpCapability.IpV6Unicast,
                                ixia_types.BgpCapability.Ipv6UnicastAddPath,
                            ],
                            custom_network_group_configs=[
                                # Minimal shell -- overwritten per-playbook by the
                                # CSV apply_pool_mutations setup step. multiplier=1
                                # / ecmp_width=1 so IXIA setup advertises a single
                                # route (well under the unique-NH cap) until the
                                # CSV lands.
                                ixia_types.CustomNetworkGroupConfig(
                                    device_group_name="MAIN_ECMP_RESOURCE",
                                    network_group_name=pool.pool_name,
                                    network_group_multiplier=main_network_group_multiplier,
                                    prefix_start_value=pool.prefix_base,
                                    prefix_length=MAIN_PREFIX_LENGTH,
                                    nexthop_start_value=ixia_nexthop_supporting_ndp_network,
                                    nexthop_increments=MAIN_NEXTHOP_INCREMENTS,
                                    ecmp_width=main_ecmp_width,
                                    network_group_index=0,
                                ),
                            ],
                        ),
                    ),
                    # DG 1: Rouge overflow class. Sized to exceed KO3 limits in
                    # the overcommit playbooks -> routes rejected -> 100% loss.
                    taac_types.DeviceGroupConfig(
                        device_group_index=1,
                        tag_name="ROUGE_OVERFLOW_RESOURCE",
                        enable=True,
                        multiplier=1,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_rogue_ic_parent_network_v6}::c",
                            increment_ip="::",
                            gateway_starting_ip=f"{ixia_rogue_ic_parent_network_v6}::a",
                            gateway_increment_ip="::",
                            mask=interconnect_prefix_length,
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_uplink_as_4byte,
                            local_as_increment=0,
                            enable_4_byte_local_as=True,
                            bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                            is_confed=is_uplink_peer_confed == "True",
                            bgp_capabilities=[
                                ixia_types.BgpCapability.IpV6Unicast,
                                ixia_types.BgpCapability.Ipv6UnicastAddPath,
                            ],
                            custom_network_group_configs=[
                                ixia_types.CustomNetworkGroupConfig(
                                    device_group_name="ROUGE_OVERFLOW_RESOURCE",
                                    network_group_name=ROUGE_NETWORK_GROUP_NAME,
                                    network_group_multiplier=rouge_network_group_multiplier,
                                    prefix_start_value=ROUGE_PREFIX_START_VALUE,
                                    prefix_length=ROUGE_PREFIX_LENGTH,
                                    nexthop_start_value=ixia_nexthop_supporting_ndp_network,
                                    nexthop_increments=ROUGE_NEXTHOP_INCREMENTS,
                                    ecmp_width=rouge_ecmp_width,
                                    network_group_index=0,
                                ),
                            ],
                        ),
                    ),
                    # DG 2: NDP-supporting nexthops (no BGP). Must be large enough
                    # that the sliding next-hop window never wraps before the
                    # target group count: >= max(ecmp_width) + (max groups).
                    taac_types.DeviceGroupConfig(
                        device_group_index=2,
                        tag_name="NDP_SUPPORTING_NEXTHOP",
                        multiplier=ndp_pool_multiplier,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=ixia_nexthop_supporting_ndp_network,
                            increment_ip="::1",
                            gateway_starting_ip=ixia_nexthop_supporting_ndp_gateway,
                            mask=interconnect_prefix_length,
                        ),
                    ),
                ],
            ),
        ],
        playbooks=_add_tc_checks_to_playbooks(
            create_ecmp_only_groups_playbooks(
                ixia_source_interface,
                asic,
                main_csv_path=csv_paths["max_groups"],
                main_pool_name=pool.pool_name,
                disruptive_iterations=disruptive_iterations,
                disruptive_settle_seconds=disruptive_settle_seconds,
            )
            + create_ecmp_only_members_playbooks(
                ixia_source_interface,
                asic,
                main_csv_path=csv_paths["max_width"],
                main_pool_name=pool.pool_name,
                disruptive_iterations=disruptive_iterations,
                disruptive_settle_seconds=disruptive_settle_seconds,
            )
            # NDP-flap and cold-start longevity both run against the GROUP CSV
            # with Rouge disabled: a full in-budget ECMP group table, which is
            # the "first set of ECMP group resources" the source (DLB) cases
            # refer to.
            + create_ecmp_only_longevity_playbooks(
                ixia_source_interface,
                asic,
                main_csv_path=csv_paths["max_groups"],
                main_pool_name=pool.pool_name,
                ndp_flap_iterations=ndp_flap_iterations,
                cold_start_iterations=cold_start_iterations,
                stabilization_seconds=longevity_stabilization_seconds,
            )
        ),
    )


# =============================================================================
# SECTION 7: TEST CONFIG INSTANCE
# =============================================================================

KO3_ECMP_ONLY_RESOURCE_TESTING: TestConfig = test_config_for_ecmp_only_resource_testing(
    test_config_name="KO3_ECMP_ONLY_RESOURCE_TESTING",
    device_name="rb002-02.qxt1",
    ixia_source_interface="eth1/64/1",
    ixia_rogue_interface="eth1/64/5",
    peergroup_uplink_mimic_v6="PEERGROUP_RB_IXIA_V6",
    # The next three are COOP patcher arguments and so are part of this
    # config's golden hash. They read oddly generic-unfriendly on purpose:
    # they are the pre-genericization literals, pinned so that
    # parameterizing the factory left KO3_ECMP_ONLY_RESOURCE_TESTING
    # byte-identical. Do not "tidy" them.
    peer_group_description="eBGP peering from KO3 to IXIA, IPv6 sessions",
    configure_vlans_patcher_name="configure_ko3_ixia_rif_ips",
    ixia_source_ic_parent_network_v6="2401:db00:206a:0",
    ixia_rogue_ic_parent_network_v6="2401:db00:206a:1",
    ixia_nexthop_supporting_ndp_network="2401:db00:206a:1::a001",
    ixia_nexthop_supporting_ndp_gateway="2401:db00:206a:1::a",
    remote_uplink_as_4byte=4200000005,
    is_uplink_peer_confed="False",
    prefix_limit="75000",
    # All ECMP table sizing (Main/Rouge multipliers + widths, NDP pool) and
    # the expected group/width counts come from EcmpAsic.G200 in
    # dlb_ecmp_platform_constants.py — re-tune there after the first hardware run.
    asic=EcmpAsic.G200,
    pool=KO3_MAIN_ECMP_POOL,
    # direct_ixia_connections=[
    #     taac_types.DirectIxiaConnection(
    #         interface="eth1/64/1",
    #         ixia_chassis_ip="2401:db00:2076:3089::3003",
    #         ixia_port="1/13",
    #     ),
    #     taac_types.DirectIxiaConnection(
    #         interface="eth1/64/5",
    #         ixia_chassis_ip="2401:db00:2076:3089::3003",
    #         ixia_port="1/14",
    #     ),
    # ],
)


# Fuji (Tomahawk4) SSW on the qzd1 fabric. Ports eth8/16/1 (IXIA slot 7 port 4)
# and eth9/16/1 (IXIA slot 8 port 7) are LLDP-confirmed against
# ixia01.netcastle.snc1 and carry no production BGP peer. Fuji and Elbert both
# instantiate Tomahawk4Asic, so EcmpAsic.TOMAHAWK4 applies unchanged.
#
# NOTE: configerator `neteng/netcastle/lab/dne_lab_ixia` has an entry for this
# hostname driving the DC-wide `configure_dne_ixia_interface` /
# `configure_dne_ixia_bgp_peer` patchers over these same two ports (vlan2112 /
# vlan2128, 2401:db00:e50d:111:8|9::1/80, remote AS 65403 in
# PEERGROUP_SSW_FSW_V6, pinned to 100G / PROFILE_100G_4_NRZ_RS528_OPTICAL).
# This config reuses those RIFs deliberately and creates its own dedicated
# AddPath peer group alongside them.
FUJI_SSW_ECMP_ONLY_RESOURCE_TESTING: TestConfig = (
    test_config_for_ecmp_only_resource_testing(
        test_config_name="FUJI_SSW_ECMP_ONLY_RESOURCE_TESTING",
        device_name="ssw002.s002.f01.qzd1",
        ixia_source_interface="eth8/16/1",
        ixia_rogue_interface="eth9/16/1",
        # New dedicated group -- must NOT collide with this SSW's production
        # PEERGROUP_SSW_FSW_V6 (48 downlinks) or PEERGROUP_SSW_FADU_V6 (16
        # uplinks), because the factory CREATES this peer group.
        peergroup_uplink_mimic_v6="PEERGROUP_SSW_IXIA_V6",
        peer_group_description="eBGP peering from Fuji SSW to IXIA, IPv6 sessions",
        configure_vlans_patcher_name="configure_fuji_ssw_ixia_rif_ips",
        # The /80s the dne_lab_ixia CoopOverride already puts on these ports --
        # permanent, so matching them removes the conflict rather than fighting
        # it. The override owns ::1; we take ::a/::b/::c.
        ixia_source_ic_parent_network_v6="2401:db00:e50d:111:8",
        ixia_rogue_ic_parent_network_v6="2401:db00:e50d:111:9",
        ixia_nexthop_supporting_ndp_network="2401:db00:e50d:111:9::a001",
        ixia_nexthop_supporting_ndp_gateway="2401:db00:e50d:111:9::a",
        # Private 4-byte ASN. The device's own ixia_ebgp_as is 65403, which is
        # also what the dne_lab_ixia override peers with on these ports -- using
        # a distinct private AS keeps our dedicated AddPath peer unambiguous
        # against the override's peer on the same /80.
        remote_uplink_as_4byte=4200000005,
        # This SSW is not in a confederation (confed_asn=0).
        is_uplink_peer_confed="False",
        # Must clear the 66,300 routes IXIA advertises at full overcommit
        # (42,000 Main + 24,300 Rouge) plus this SSW's production routes from
        # its 64 BGP neighbours. KO3's 75000 only had to cover 21,789.
        prefix_limit="150000",
        # Sizing from EcmpAsic.TOMAHAWK4 in dlb_ecmp_platform_constants.py: 1536
        # groups / 42,000 members (TH4 raw 2048 / 56,000 derated by the 75%
        # ecmp_resource_percentage) -- re-tune there after the first run.
        asic=EcmpAsic.TOMAHAWK4,
        pool=FUJI_SSW_MAIN_ECMP_POOL,
        basset_pool="dne.test",
        # Matches the /80 the dne_lab_ixia override writes on these RIFs. Sets
        # the DUT RIF prefix_length and the IXIA device-group mask only -- the
        # ADVERTISED prefix length is MAIN_PREFIX_LENGTH (64) and is unaffected.
        interconnect_prefix_length=80,
        # Own the ports' admin state so the test does not silently depend on
        # whatever the base config or a DC-wide override leaves them at.
        enable_ixia_ports=True,
        # Boot the Main NetworkGroup as the genuinely minimal shell its own
        # comment describes. Every playbook overwrites it via
        # `apply_pool_mutations` before traffic, so the baseline only has to be
        # valid, not representative.
        baseline_network_group_multiplier=1,
        baseline_ecmp_width=1,
        # SMOKE-RUN SCALE -- raise to the factory defaults (5 / 300 / 60 / 13 /
        # 300) once the first full pass is green. Keeps all 18 playbooks in the
        # run but cuts repeat counts and settle windows.
        disruptive_iterations=2,
        disruptive_settle_seconds=60,
        ndp_flap_iterations=2,
        cold_start_iterations=2,
        longevity_stabilization_seconds=60,
    )
)


if __name__ == "__main__":
    for _asic, _pool in (
        (EcmpAsic.G200, KO3_MAIN_ECMP_POOL),
        (EcmpAsic.TOMAHAWK4, FUJI_SSW_MAIN_ECMP_POOL),
    ):
        for _key, _path in generate_ecmp_csvs(_asic, _pool).items():
            print(f"{_asic.value:10s} {_key:11s} {_path}")
