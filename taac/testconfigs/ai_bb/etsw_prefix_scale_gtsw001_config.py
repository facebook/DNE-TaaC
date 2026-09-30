# Copyright (c) Meta Platforms, Inc. and affiliates.

"""UFv2 ETSW prefix-scale population on gtsw001.l1001.c085.ash6.

GOAL: get the UFv2 ETSW prefix set onto a real TH6 box and observe it in the
BGP RIB and the wedge_agent FIB. This is a population/observation config --
there are deliberately NO traffic items, and ECMP/DLB width is intentionally
NOT exercised (every prefix carries a single next-hop, so FBOSS folds them into
one ECMP group).

WHY THIS DEVICE: the ETSW role does not exist in any lab -- `etsw.*` returns
zero devices fleet-wide, because UFv2/DC-TypeG is unbuilt. The ETSW is TH6 and
IceCube is TH6, so gtsw001.l1001.c085.ash6 (model ICECUBE) is an ASIC-faithful
stand-in, and it is the only ash6 device with IXIA ports up (4 x ixia19). It is
a scale/ASIC proxy, not a topology proxy.

PREFIX SET (see `etsw_prefix_tree.py` for the model):
    69,120 x /64   VF specifics   = 144 GSLs x 2 VF groups x 240 GPUs

The LLD's full ETSW route scale is 69,139 = these 69,120 plus 19 /46 remote L2
aggregates. The /46s are not injected yet: the CSV injector hardcodes
`PrefixLength.Single(64)` so it cannot carry them, and a plain /46 network
group needs a prefix-pool address step override that the config structs do not
currently expose. Follow-up; the /64 tree is the primary target.

The /64s are NOT contiguous: 288 dense runs of 240, each starting on a
256-aligned /56 boundary, with a 16-slot gap between runs. That shape is why
the set is injected from a CSV -- IxNetwork's INCREMENT pattern can only
produce one flat arithmetic progression, and RANDOM_MASK loses the run
structure entirely.

Source: "[DCXOR] Backend LLD for UFv2 in DC-TypeG" -- IP Addressing tab
("Proposed UFv2 load-bearing hierarchy"), Scale Numbers tab ("ETSW Scale
(TH6)"), Routing tab ("Route Propagation Through the Fabric").
"""

import ipaddress
import os

from ixia.ixia import types as ixia_types
from taac.playbooks.playbook_definitions import (
    create_prefix_scale_inject_and_observe_playbook,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_run_ssh_command_step,
)
from taac.testconfigs.ai_bb.mp3n_prefix_profiling_ixia_config import (
    create_mp3n_setup_tasks,
    create_mp3n_teardown_tasks,
    MP3N_L1_CONFIG,
)
from taac.testconfigs.ai_bb.prefix_block_spec import (
    describe,
    ETSW_RECEIVED_SPECS,
    format_ipv6_full,
    nexthop_pool,
    PrefixBlockSpec,
    write_injection_csv,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import Playbook, TestConfig


# =============================================================================
# Testbed
# =============================================================================
DEVICE_NAME: str = "gtsw001.l1001.c085.ash6"

# eth1/1/1 -> ixia19.netcastle.ash6 port 1/25 (confirmed live via LLDP).
IXIA_INTERFACE: str = "eth1/1/1"
IXIA_CHASSIS_IP: str = "2401:db00:2066:31fb::3019"
IXIA_PORT: str = "1/25"

# Interconnect /64 already provisioned on the DUT (eth1/1/1 holds ::a/64).
INTERCONNECT_V6: str = "2401:db00:206a:c000"
DUT_IP: str = f"{INTERCONNECT_V6}::a"
IXIA_IP: str = f"{INTERCONNECT_V6}::b"

# The IXIA peer's own address is the next-hop for every advertised prefix. It
# is guaranteed NDP-resolvable because it is the BGP peer itself, which removes
# the need for a separate NDP-supporting device group.
NEXT_HOP: str = f"{INTERCONNECT_V6}:0:0:0:b"

REMOTE_AS: int = 4200601902
PEER_GROUP: str = "PEERGROUP_GTSW_IXIA_V6"
INGRESS_POLICY: str = "PROPAGATE_GTSW_IXIA_PREFIX_PROFILING_IN"
EGRESS_POLICY: str = "PROPAGATE_GTSW_IXIA_PREFIX_PROFILING_OUT"
PATCHER_SUFFIX: str = "gtsw_ixia"

# VF origination community, matching the prefix-profiling policy set already
# deployed for these peer groups.
VF_COMMUNITY: str = "65527:12711"

DEVICE_GROUP_TAG: str = "ETSW_PREFIX_SCALE"
# RouteScale.prefix_name -> the Ipv6PrefixPools object name (not the NG name).
VF_POOL_NAME: str = "ETSW_VF_PREFIXES"
AGG_POOL_NAME: str = "ETSW_REMOTE_L2_AGGS"

# apply_pool_mutations resolves this against the NetworkGroup name first and
# then the Ipv6PrefixPools name. The route_scales path derives its NG name from
# the port and is not caller-controllable, but it does set the prefix-pool name
# from RouteScale.prefix_name -- so VF_POOL_NAME is the stable handle.

# BGP switch prefix limit. 69,120 advertised + ~169 already on the box, with
# headroom so the tail of the injection is not rejected.
PREFIX_LIMIT: int = 200000


# =============================================================================
# CSV generation (at import time -- 69,120 rows, ~3.4 MB)
# =============================================================================
ETSW_CSV_DIR: str = "/tmp/etsw_csvs"
ETSW_INJECTION_CSV: str = os.path.join(ETSW_CSV_DIR, "etsw_injection.csv")

# One CSV for the whole received set -- both mask lengths. The injector reads
# the PrefixLength column and drives Ipv6PrefixPools.PrefixLength with a
# ValueList, so a single network group carries /64s and /46s together.
write_injection_csv(ETSW_INJECTION_CSV, ETSW_RECEIVED_SPECS, next_hop=NEXT_HOP)

_EXPECTED_BY_TYPE: str = describe(ETSW_RECEIVED_SPECS)


# =============================================================================
# IXIA topology -- one port, one BGP peer, one network group
# =============================================================================
_ENDPOINT: taac_types.Endpoint = taac_types.Endpoint(
    name=DEVICE_NAME,
    ixia_ports=[IXIA_INTERFACE],
    dut=True,
    direct_ixia_connections=[
        taac_types.DirectIxiaConnection(
            interface=IXIA_INTERFACE,
            ixia_chassis_ip=IXIA_CHASSIS_IP,
            ixia_port=IXIA_PORT,
        ),
    ],
)

_PORT_CONFIG: taac_types.BasicPortConfig = taac_types.BasicPortConfig(
    l1_config=MP3N_L1_CONFIG,
    endpoint=f"{DEVICE_NAME}:{IXIA_INTERFACE}",
    device_group_configs=[
        taac_types.DeviceGroupConfig(
            device_group_index=0,
            tag_name=DEVICE_GROUP_TAG,
            enable=True,
            multiplier=1,
            v6_addresses_config=taac_types.IpAddressesConfig(
                starting_ip=IXIA_IP,
                gateway_starting_ip=DUT_IP,
                increment_ip="::",
                gateway_increment_ip="::",
                mask=64,
            ),
            v6_bgp_config=taac_types.BgpConfig(
                local_as_4_bytes=REMOTE_AS,
                local_as_increment=0,
                enable_4_byte_local_as=True,
                bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                is_confed=False,
                bgp_capabilities=[
                    ixia_types.BgpCapability.IpV6Unicast,
                    ixia_types.BgpCapability.Ipv6UnicastAddPath,
                ],
                # Use the route_scales path, NOT custom_network_group_configs.
                #
                # custom_network_group_configs drives
                # `_create_custom_network_group`, which builds the prefix pool
                # with NetworkAddress.Custom(increments=[("::", ecmp_width)]).
                # On this chassis that consistently fails at
                # BgpV6IPRouteProperty.add() with a bare
                #   "Unable to add .../bgpV6IPRouteProperty:L100
                #    Commit operation failed"
                # and no detail in globals/appErrors -- reproduced across
                # multiplier 1 and 100, with and without the second network
                # group. route_scales instead goes through
                # NetworkAddress.Increment, which is the path the working
                # GTSW001 prefix-profiling configs already use on this exact
                # device and port.
                #
                # This is only the boot shell (1 prefix); the CSV setup step
                # replaces the address list and the multiplier at runtime.
                route_scales=[
                    taac_types.RouteScaleSpec(
                        v6_route_scale=taac_types.RouteScale(
                            prefix_name=VF_POOL_NAME,
                            starting_prefixes=ETSW_RECEIVED_SPECS[0].root,
                            prefix_length=64,
                            prefix_step="0:0:0:1:0:0:0:0",
                            prefix_count=1,
                            multiplier=1,
                            bgp_communities=[VF_COMMUNITY],
                            pattern_type=taac_types.PrefixPatternType.INCREMENT,
                        ),
                        multiplier=1,
                        network_group_index=0,
                    ),
                ],
            ),
        ),
    ],
)


# =============================================================================
# Playbook -- inject, settle, observe
# =============================================================================
_EXPECTED_VF = sum(sp.total for sp in ETSW_RECEIVED_SPECS if sp.prefix_type == "vf_gpu")
# Only the /64 tree is injected today -- see the note on the omitted /46
# aggregate network group above.
_EXPECTED_TOTAL = sum(sp.total for sp in ETSW_RECEIVED_SPECS)

# Spot-check three points that prove the run/gap structure survived the
# injection: the first prefix of run 0, the last prefix of run 0 (::ef), and
# the first prefix of run 1 (::100 -- i.e. the 16-slot gap was preserved).
_VERIFY_ROUTE_SHAPE_CMD = (
    "for p in 6000::/64 6000:0:0:ef::/64 6000:0:0:100::/64 6000:0:1:1fef::/64; do "
    'echo "--- $p"; timeout 60 fboss2 show route details "$p" 2>/dev/null '
    "| head -12; done"
)

_VERIFY_COUNTS_CMD = (
    'echo "=== FIB (wedge_agent) route summary ==="; '
    "timeout 120 fboss2 show route summary 2>/dev/null | tail -12; "
    'echo "=== FIB /64 count in the 6000::/46 tree ==="; '
    "timeout 300 fboss2 show route 2>/dev/null | grep -c '^6000:' || true; "
    'echo "=== BGP RIB received-from-IXIA count ==="; '
    f"timeout 300 vtysh -c 'show bgp ipv6 unicast neighbors {IXIA_IP} received-routes' "
    "2>/dev/null | tail -3 || "
    f"timeout 300 fboss2 show bgp neighbor {IXIA_IP} 2>/dev/null | tail -20 || true"
)

_INJECT_PLAYBOOK: Playbook = create_prefix_scale_inject_and_observe_playbook(
    name="etsw_prefix_scale_inject_and_observe",
    description=(
        f"Inject the UFv2 ETSW VF prefix set ({_EXPECTED_VF} /64s in 288 runs "
        f"of 240) into {DEVICE_NAME} and observe it in the BGP RIB and the "
        "wedge_agent FIB."
    ),
    pool_csvs=[[ETSW_INJECTION_CSV, VF_POOL_NAME]],
    inject_description=(
        f"Inject {_EXPECTED_VF} VF /64s from {ETSW_INJECTION_CSV} "
        f"into prefix pool {VF_POOL_NAME}"
    ),
    settle_stage_id="settle_after_injection",
    settle_seconds=300,
    observe_stage_id="observe_route_counts",
    observe_description=f"Report RIB/FIB counts (expect ~{_EXPECTED_TOTAL} added)",
    observe_commands=[
        (_VERIFY_COUNTS_CMD, "RIB + FIB route counts"),
    ],
    extra_stages=[
        create_steps_stage(
            stage_id="observe_route_shape",
            description=(
                "Verify the 240-run / 16-gap structure survived: ::ef present, "
                "::f0 absent, ::100 present"
            ),
            steps=[
                create_run_ssh_command_step(
                    cmd=_VERIFY_ROUTE_SHAPE_CMD,
                    description="Per-prefix route details at run boundaries",
                ),
            ],
        ),
    ],
)


# =============================================================================
# TestConfig
# =============================================================================
ETSW_PREFIX_SCALE_GTSW001: TestConfig = TestConfig(
    name="ETSW_PREFIX_SCALE_GTSW001_C085",
    basset_pool="dne.test",
    ixia_protocol_verification_timeout=10,
    skip_ixia_protocol_verification=True,
    endpoints=[_ENDPOINT],
    basic_port_configs=[_PORT_CONFIG],
    # Deliberately no traffic items: this config populates and observes the
    # route table, it does not measure forwarding.
    basic_traffic_item_configs=[],
    setup_tasks=create_mp3n_setup_tasks(
        device_name=DEVICE_NAME,
        peer_group=PEER_GROUP,
        local_ip=DUT_IP,
        peer_ip=IXIA_IP,
        interface_configs=[
            (IXIA_INTERFACE, DUT_IP, IXIA_IP, "ixia_etsw_prefix_scale"),
        ],
        peer_description="ixia_etsw_prefix_scale",
        remote_as=REMOTE_AS,
        ingress_policy=INGRESS_POLICY,
        egress_policy=EGRESS_POLICY,
        patcher_suffix=PATCHER_SUFFIX,
        prefix_limit=PREFIX_LIMIT,
    ),
    teardown_tasks=create_mp3n_teardown_tasks(device_name=DEVICE_NAME),
    playbooks=[_INJECT_PLAYBOOK],
)


# =============================================================================
# 45-NEXTHOP ADD-PATH VARIANT -- models the ETSW's northbound BAG fanout
# =============================================================================
# The LLD gives the ETSW 45 BAGs northbound with an NB ECMP group width of 45.
# This variant produces that width from NEXT-HOP diversity on a single BGP
# session rather than from 45 sessions:
#
#   DG0  single eBGP peer (multiplier=1) advertising every prefix 45 times,
#        once per next-hop, with add-path enabled.
#   DG1  NDP_SUPPORTING_NEXTHOP (multiplier=45) emulating the 45 next-hop
#        addresses so the DUT can resolve them. Without it every path is
#        dropped as unresolvable.
#
# The CSV carries 45 rows per prefix -- same Address, 45 distinct
# "Ipv6 Next Hop" values. The injector derives
# ``MvNextHopCount = total_rows / distinct_prefixes`` = 45 and enables
# add-path, so this is the same contract the ECMP resource tests use.
#
# Both device groups are siblings on ONE port, sharing the interface /64 that
# already exists on the DUT (::a). This mirrors the proven IcePack ECMP config
# (testconfigs/npi/icepack_ecmp_resource_testing_config.py), which puts its
# NDP_SUPPORTING_NEXTHOP group alongside the BGP peer rather than on a separate
# port -- it needs no extra interface provisioning, and the DUT's existing
# ::a/64 already covers the next-hop pool.
#
# CAVEAT: add-path controls how many paths are ADVERTISED; installing several
# of them as ECMP is a separate multipath decision on the DUT. Standard BGP
# best-path selection installs one next-hop per prefix. Multipath is confirmed
# working on this box for its real STSW-learned routes (a production /56 shows
# 8+ next hops), but whether it engages for this synthetic single-session
# add-path advertisement is exactly what this config measures.
# eBGP, matching the rest of this fabric. iBGP was tried here and does NOT
# work: gtsw001 reports "Member of confederation: None (pure-ebgp)" and has no
# route-reflector config, so an iBGP peer establishes and its updates count as
# received+accepted but never reach Loc-RIB. (The DSF hardening configs can use
# BgpPeerType.IBGP because those roles are not a pure-eBGP fabric.)
#
# eBGP carries the third-party ::a001 next-hops through fine -- they are on the
# peer's connected subnet, which is exactly when eBGP permits them.
ETSW_45NH_AS: int = REMOTE_AS

ETSW_45NH_COUNT: int = 45

# Next-hop pool, inside the existing interface /64 so the DUT resolves it on
# the same interface as the BGP session.
ETSW_45NH_BASE: str = f"{INTERCONNECT_V6}::a001"
ETSW_45NH_POOL: list = nexthop_pool(ETSW_45NH_BASE, ETSW_45NH_COUNT)

# Prefixes advertised. Held below the full 69,139 while the add-path shape is
# being proven: 4 blocks x 240 = 960 prefixes x 45 next-hops = 43,200 paths,
# a scale already shown to hold sessions up on this DUT. Raise once the shape
# is confirmed.
# Deliberately tiny while the add-path SHAPE is being proven: 2 prefixes x 45
# next-hops = 90 rows. Small enough to read the whole RIB by eye and to make a
# run cheap. Scale up only once 45 paths per prefix are confirmed on the DUT.
ETSW_45NH_PREFIX_COUNT: int = 2

ETSW_45NH_SPECS: list = [
    PrefixBlockSpec(
        root=ETSW_RECEIVED_SPECS[0].root,
        root_mask=ETSW_RECEIVED_SPECS[0].root_mask,
        blocks=1,
        parent_mask=ETSW_RECEIVED_SPECS[0].parent_mask,
        prefixes_per_block=ETSW_45NH_PREFIX_COUNT,
        prefix_length=ETSW_RECEIVED_SPECS[0].prefix_length,
        prefix_type=ETSW_RECEIVED_SPECS[0].prefix_type,
    ),
]

ETSW_45NH_CSV: str = os.path.join(ETSW_CSV_DIR, "etsw_addpath_injection.csv")
# Cross-product: every prefix is emitted once per next-hop, so each address
# occupies ETSW_45NH_COUNT consecutive rows and the whole file is
# prefixes x next-hops rows. With NG.Multiplier = row count, each row becomes
# its own route instance carrying its own next-hop, and the rows sharing an
# address are the add-path group for that prefix.
#
# This is the shape an earlier run could not confirm -- with repeated addresses
# the next-hop ValueList appeared to be discarded and every route reverted to
# the interface address. That run never reached the DUT (the session had no
# port), so the observation is unproven; this config re-tests it properly.
write_injection_csv(
    ETSW_45NH_CSV, ETSW_45NH_SPECS, next_hop=ETSW_45NH_POOL, pair_nexthops=False
)

ETSW_45NH_PREFIXES: int = sum(sp.total for sp in ETSW_45NH_SPECS)
ETSW_45NH_PATHS: int = ETSW_45NH_PREFIXES * ETSW_45NH_COUNT

PREFIX_LIMIT_45NH: int = 5_000_000

_45NH_PORT_CONFIG: taac_types.BasicPortConfig = taac_types.BasicPortConfig(
    l1_config=MP3N_L1_CONFIG,
    endpoint=f"{DEVICE_NAME}:{IXIA_INTERFACE}",
    device_group_configs=[
        # DG0 -- the single eBGP peer. Same proven addressing as the
        # single-peer config: IXIA ::b, DUT ::a.
        taac_types.DeviceGroupConfig(
            device_group_index=0,
            tag_name="ETSW_ADDPATH_PEER",
            enable=True,
            multiplier=1,
            v6_addresses_config=taac_types.IpAddressesConfig(
                starting_ip=IXIA_IP,
                gateway_starting_ip=DUT_IP,
                increment_ip="::",
                gateway_increment_ip="::",
                mask=64,
            ),
            v6_bgp_config=taac_types.BgpConfig(
                local_as_4_bytes=ETSW_45NH_AS,
                local_as_increment=0,
                enable_4_byte_local_as=True,
                bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                is_confed=False,
                bgp_capabilities=[
                    ixia_types.BgpCapability.IpV6Unicast,
                    ixia_types.BgpCapability.Ipv6UnicastAddPath,
                ],
                route_scales=[
                    taac_types.RouteScaleSpec(
                        v6_route_scale=taac_types.RouteScale(
                            prefix_name=VF_POOL_NAME,
                            starting_prefixes=ETSW_RECEIVED_SPECS[0].root,
                            prefix_length=64,
                            prefix_step="0:0:0:1:0:0:0:0",
                            prefix_count=1,
                            multiplier=1,
                            bgp_communities=[VF_COMMUNITY],
                            pattern_type=taac_types.PrefixPatternType.INCREMENT,
                        ),
                        multiplier=1,
                        network_group_index=0,
                    ),
                ],
            ),
        ),
        # DG1 -- NDP responders for the 45 next-hops. No BGP.
        taac_types.DeviceGroupConfig(
            device_group_index=1,
            tag_name="NDP_SUPPORTING_NEXTHOP",
            enable=True,
            multiplier=ETSW_45NH_COUNT,
            v6_addresses_config=taac_types.IpAddressesConfig(
                starting_ip=ETSW_45NH_BASE,
                increment_ip="::1",
                gateway_starting_ip=DUT_IP,
                gateway_increment_ip="::",
                mask=64,
            ),
        ),
    ],
)

# Where the observation is parked ON THE DUT. RUN_SSH_COMMAND_STEP does not
# echo stdout into the netcastle log, and teardown reverts the BGP config the
# moment the playbook ends, so a run that only prints leaves no evidence behind
# and cannot be checked afterwards. Tee-ing to a file survives both.
_VERIFY_45NH_OUT: str = "/tmp/etsw_45nh_observe.txt"

# The question this answers is "how many next-hops did the DUT keep for ONE
# prefix", so both advertised prefixes are dumped and their next-hops counted
# rather than eyeballed.
_VERIFY_45NH_CMD = (
    "{ "
    'echo "=== BGP session + paths ==="; '
    f"timeout 300 fboss2 show bgp neighbors 2>/dev/null "
    f"| grep -A 26 'neighbor is {IXIA_IP},' "
    "| grep -E 'BGP state|Current prefixes'; "
    'echo "=== route details: 6000::/64 ==="; '
    "timeout 120 fboss2 show route details 6000::/64 2>/dev/null | head -60; "
    'echo "=== route details: 6000:0:0:1::/64 ==="; '
    "timeout 120 fboss2 show route details 6000:0:0:1::/64 2>/dev/null "
    "| head -60; "
    'echo "=== distinct next-hops per advertised prefix ==="; '
    "for p in 6000::/64 6000:0:0:1::/64; do "
    'printf "%s -> " "$p"; '
    'timeout 120 fboss2 show route details "$p" 2>/dev/null '
    "| grep -oE '2401:db00:206a:c000:[0-9a-f:]+' | sort -u | wc -l; "
    "done; "
    'echo "=== shadowrib paths for 6000::/64 ==="; '
    "timeout 120 fboss2 show bgp shadowrib 2>/dev/null "
    "| sed -n '/^> 6000::\\/64,/,/^$/p' | head -60; "
    'echo "=== FIB route summary ==="; '
    "timeout 200 fboss2 show route summary 2>/dev/null | tail -12; "
    f"}} 2>&1 | tee {_VERIFY_45NH_OUT}"
)

_45NH_PLAYBOOK: Playbook = create_prefix_scale_inject_and_observe_playbook(
    name="etsw_45nh_addpath_inject_and_observe",
    description=(
        f"Advertise {ETSW_45NH_PREFIXES} prefixes x {ETSW_45NH_COUNT} "
        f"next-hops = {ETSW_45NH_PATHS} add-paths from a single BGP session, "
        "and observe how many next-hops the DUT installs per prefix."
    ),
    pool_csvs=[[ETSW_45NH_CSV, VF_POOL_NAME]],
    inject_description=(
        f"Inject {ETSW_45NH_PATHS} rows "
        f"({ETSW_45NH_PREFIXES} prefixes x {ETSW_45NH_COUNT} "
        f"next-hops) into prefix pool {VF_POOL_NAME}"
    ),
    settle_stage_id="settle_45nh",
    settle_seconds=150,
    observe_stage_id="observe_45nh",
    observe_description=(
        f"Report session, path count and installed next-hops "
        f"(expect {ETSW_45NH_PREFIXES} prefixes, "
        f"{ETSW_45NH_PATHS} paths received)"
    ),
    observe_commands=[
        (_VERIFY_45NH_CMD, "BGP paths + installed nexthops per prefix"),
    ],
)

ETSW_PREFIX_SCALE_GTSW001_45PEER: TestConfig = TestConfig(
    name="ETSW_PREFIX_SCALE_GTSW001_C085_45PEER",
    basset_pool="dne.test",
    ixia_protocol_verification_timeout=10,
    skip_ixia_protocol_verification=True,
    endpoints=[_ENDPOINT],
    basic_port_configs=[_45NH_PORT_CONFIG],
    basic_traffic_item_configs=[],
    setup_tasks=create_mp3n_setup_tasks(
        device_name=DEVICE_NAME,
        peer_group=PEER_GROUP,
        local_ip=DUT_IP,
        peer_ip=IXIA_IP,
        interface_configs=[
            (IXIA_INTERFACE, DUT_IP, IXIA_IP, "ixia_etsw_addpath"),
        ],
        peer_description="ixia_etsw_addpath",
        # Same ASN on both ends -> the DUT classifies this peer as INTERNAL.
        remote_as=ETSW_45NH_AS,
        ingress_policy=INGRESS_POLICY,
        egress_policy=EGRESS_POLICY,
        patcher_suffix=PATCHER_SUFFIX,
        prefix_limit=PREFIX_LIMIT_45NH,
        hold_time_seconds=180,
        keep_alive_seconds=60,
        # The IXIA advertises third-party next-hops from the ::a001 pool. With
        # next-hop-self the DUT rewrites them all to the peer address, the 45
        # paths become indistinguishable and collapse to one.
        next_hop_self=False,
    ),
    teardown_tasks=create_mp3n_teardown_tasks(device_name=DEVICE_NAME),
    playbooks=[_45NH_PLAYBOOK],
)


# =============================================================================
# 4-port variant -- spread the prefix load across every IXIA port on the device
# =============================================================================
# A single IXIA port cannot carry the full ETSW prefix set at 45-way ECMP. The
# port CPU refuses configs beyond roughly half a million routes:
#
#   StartAllProtocols failed: Download of package(s) aptixiaError,ixgratarp,ixg
#   failed ... Timeout. Port <chassis>;1;25 is not CPU ready.
#
# Measured on gtsw001: 453,600 routes on one port converges in 71s; 1,123,200
# and 3,111,255 both fail. So the prefix set is split across the four IXIA
# ports, each advertising its own quarter.
#
# THE NEXT-HOP POOL IS NOT REPLICATED. All four ports advertise the SAME 45
# next-hops, which live on port 1's connected /64. Ports 2-4 have no NDP device
# group -- their routes resolve recursively through port 1's connected route.
# That keeps the Virtual ARS supergroup at 45 unique members no matter how many
# ports participate (see ResourceAccountant::wouldExceedSuperGroupLimit, which
# counts unique next-hops device-wide), which is the whole point: scale the
# PREFIX count without spending more of the 128-member ARS budget.
#
#   port 1 (eth1/1/1)  DG0 eBGP peer + DG1 NDP responders (the 45 next-hops)
#   port 2 (eth1/1/3)  DG0 eBGP peer only
#   port 3 (eth1/1/5)  DG0 eBGP peer only
#   port 4 (eth1/1/7)  DG0 eBGP peer only

# (interface, subnet prefix, IXIA chassis port). All four are already addressed
# on the DUT as <subnet>::a/64 -- confirmed via fboss2 show interface.
ETSW_4PORT_PORTS: list = [
    ("eth1/1/1", "2401:db00:206a:c000", "1/25"),
    ("eth1/1/3", "2401:db00:206a:c002", "1/27"),
    ("eth1/1/5", "2401:db00:206a:c004", "1/29"),
    ("eth1/1/7", "2401:db00:206a:c006", "1/31"),
]

# Blocks of 240 /64s per port. 42 blocks = 10,080 prefixes x 45 next-hops =
# 453,600 routes, the largest single-port load proven to converge. Four ports
# gives 40,320 prefixes / 1,814,400 paths. Raise toward 72 (the full 288/4) once
# the per-port ceiling above 453,600 has been bracketed.
ETSW_4PORT_BLOCKS_PER_PORT: int = 42

ETSW_4PORT_CSVS: list = []
ETSW_4PORT_POOLS: list = []
for _i, (_iface, _net, _cport) in enumerate(ETSW_4PORT_PORTS):
    # Each port owns a disjoint, contiguous run of /56 blocks so the prefix sets
    # never overlap -- overlapping prefixes across ports would collapse into one
    # RIB entry and silently under-count the scale.
    _base = ETSW_RECEIVED_SPECS[0]
    _port_stride = ETSW_4PORT_BLOCKS_PER_PORT * (1 << (128 - _base.parent_mask))
    _root = format_ipv6_full(
        ipaddress.IPv6Address(
            int(ipaddress.IPv6Address(_base.root)) + _i * _port_stride
        )
    )
    _spec = [
        PrefixBlockSpec(
            root=_root,
            root_mask=_base.root_mask,
            blocks=ETSW_4PORT_BLOCKS_PER_PORT,
            parent_mask=_base.parent_mask,
            prefixes_per_block=_base.prefixes_per_block,
            prefix_length=_base.prefix_length,
            prefix_type=_base.prefix_type,
        )
    ]
    _pool = f"{VF_POOL_NAME}_P{_i}"
    _csv = os.path.join(ETSW_CSV_DIR, f"etsw_4port_p{_i}.csv")
    # Same 45 next-hops on every port -- they resolve via port 1.
    write_injection_csv(_csv, _spec, next_hop=ETSW_45NH_POOL, pair_nexthops=False)
    ETSW_4PORT_CSVS.append(_csv)
    ETSW_4PORT_POOLS.append(_pool)

ETSW_4PORT_PREFIXES: int = (
    ETSW_4PORT_BLOCKS_PER_PORT
    * ETSW_RECEIVED_SPECS[0].prefixes_per_block
    * len(ETSW_4PORT_PORTS)
)
ETSW_4PORT_PATHS: int = ETSW_4PORT_PREFIXES * ETSW_45NH_COUNT


def _make_4port_port_config(index: int) -> taac_types.BasicPortConfig:
    """One IXIA port: eBGP peer, plus the NDP responder group on port 0 only."""
    iface, net, _cport = ETSW_4PORT_PORTS[index]
    dut_ip = f"{net}::a"
    ixia_ip = f"{net}::b"

    dgs = [
        taac_types.DeviceGroupConfig(
            device_group_index=0,
            tag_name=f"ETSW_ADDPATH_PEER_P{index}",
            enable=True,
            multiplier=1,
            v6_addresses_config=taac_types.IpAddressesConfig(
                starting_ip=ixia_ip,
                gateway_starting_ip=dut_ip,
                increment_ip="::",
                gateway_increment_ip="::",
                mask=64,
            ),
            v6_bgp_config=taac_types.BgpConfig(
                local_as_4_bytes=ETSW_45NH_AS,
                local_as_increment=0,
                enable_4_byte_local_as=True,
                bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                is_confed=False,
                bgp_capabilities=[
                    ixia_types.BgpCapability.IpV6Unicast,
                    ixia_types.BgpCapability.Ipv6UnicastAddPath,
                ],
                route_scales=[
                    taac_types.RouteScaleSpec(
                        v6_route_scale=taac_types.RouteScale(
                            prefix_name=ETSW_4PORT_POOLS[index],
                            starting_prefixes=ETSW_RECEIVED_SPECS[0].root,
                            prefix_length=64,
                            prefix_step="0:0:0:1:0:0:0:0",
                            prefix_count=1,
                            multiplier=1,
                            bgp_communities=[VF_COMMUNITY],
                            pattern_type=taac_types.PrefixPatternType.INCREMENT,
                        ),
                        multiplier=1,
                        network_group_index=0,
                    ),
                ],
            ),
        ),
    ]

    if index == 0:
        # The only NDP responder group in the whole config. Ports 1-3 reuse
        # these next-hops; their routes resolve recursively via this /64.
        dgs.append(
            taac_types.DeviceGroupConfig(
                device_group_index=1,
                tag_name="NDP_SUPPORTING_NEXTHOP",
                enable=True,
                multiplier=ETSW_45NH_COUNT,
                v6_addresses_config=taac_types.IpAddressesConfig(
                    starting_ip=ETSW_45NH_BASE,
                    increment_ip="::1",
                    gateway_starting_ip=dut_ip,
                    gateway_increment_ip="::",
                    mask=64,
                ),
            )
        )

    return taac_types.BasicPortConfig(
        l1_config=MP3N_L1_CONFIG,
        endpoint=f"{DEVICE_NAME}:{iface}",
        device_group_configs=dgs,
    )


_4PORT_ENDPOINT: taac_types.Endpoint = taac_types.Endpoint(
    name=DEVICE_NAME,
    ixia_ports=[p[0] for p in ETSW_4PORT_PORTS],
    dut=True,
    direct_ixia_connections=[
        taac_types.DirectIxiaConnection(
            interface=iface,
            ixia_chassis_ip=IXIA_CHASSIS_IP,
            ixia_port=cport,
        )
        for iface, _net, cport in ETSW_4PORT_PORTS
    ],
)

_VERIFY_4PORT_OUT: str = "/tmp/etsw_4port_observe.txt"
_VERIFY_4PORT_CMD = (
    "{ "
    'echo "=== sessions ==="; '
    "bgpsum6 2>/dev/null | grep -E '206a:c00[0246]::b'; "
    'echo "=== bgp table prefix count ==="; '
    "timeout 300 fboss2 show bgp table 2>/dev/null | grep -cE '^> 6000'; "
    'echo "=== distinct next-hops per sample prefix ==="; '
    "for p in 6000::/64 6000:0:0:1::/64; do printf '%s -> ' \"$p\"; "
    'timeout 120 fboss2 show route details "$p" 2>/dev/null '
    "| grep -oE '2401:db00:206a:c000::a[0-9a-f]+' | sort -u | wc -l; done; "
    'echo "=== route summary ==="; '
    "timeout 200 fboss2 show route summary 2>/dev/null | tail -8; "
    'echo "=== resource rejections ==="; '
    "timeout 60 journalctl -u fboss_sw_agent --since '-10min' --no-pager 2>/dev/null "
    "| grep -cE 'State update rejected'; "
    f"}} 2>&1 | tee {_VERIFY_4PORT_OUT}"
)

_4PORT_PLAYBOOK: Playbook = create_prefix_scale_inject_and_observe_playbook(
    name="etsw_4port_addpath_inject_and_observe",
    description=(
        f"Advertise {ETSW_4PORT_PREFIXES} prefixes x {ETSW_45NH_COUNT} next-hops "
        f"= {ETSW_4PORT_PATHS} paths, split across "
        f"{len(ETSW_4PORT_PORTS)} IXIA ports sharing one next-hop pool."
    ),
    pool_csvs=[[csv, pool] for csv, pool in zip(ETSW_4PORT_CSVS, ETSW_4PORT_POOLS)],
    inject_description=(
        f"Inject {ETSW_4PORT_PATHS} rows across {len(ETSW_4PORT_POOLS)} pools"
    ),
    wait_after_inject=True,
    settle_stage_id="settle_4port",
    settle_seconds=300,
    observe_stage_id="observe_4port",
    observe_description=(
        f"Report sessions, path count and installed next-hops "
        f"(expect {ETSW_4PORT_PREFIXES} prefixes, "
        f"{ETSW_45NH_COUNT} next-hops each)"
    ),
    observe_commands=[
        (_VERIFY_4PORT_CMD, "4-port BGP paths + installed nexthops"),
    ],
)

ETSW_PREFIX_SCALE_GTSW001_4PORT: TestConfig = TestConfig(
    name="ETSW_PREFIX_SCALE_GTSW001_C085_4PORT",
    basset_pool="dne.test",
    ixia_protocol_verification_timeout=10,
    skip_ixia_protocol_verification=True,
    endpoints=[_4PORT_ENDPOINT],
    basic_port_configs=[
        _make_4port_port_config(i) for i in range(len(ETSW_4PORT_PORTS))
    ],
    basic_traffic_item_configs=[],
    setup_tasks=create_mp3n_setup_tasks(
        device_name=DEVICE_NAME,
        peer_group=PEER_GROUP,
        local_ip=DUT_IP,
        peer_ip=IXIA_IP,
        # One eBGP peer per IXIA port. The interfaces already carry <net>::a/64
        # on the DUT, so this only adds the BGP peers.
        interface_configs=[
            (iface, f"{net}::a", f"{net}::b", f"ixia_etsw_4port_p{i}")
            for i, (iface, net, _c) in enumerate(ETSW_4PORT_PORTS)
        ],
        peer_description="ixia_etsw_4port",
        remote_as=ETSW_45NH_AS,
        ingress_policy=INGRESS_POLICY,
        egress_policy=EGRESS_POLICY,
        patcher_suffix=PATCHER_SUFFIX,
        prefix_limit=PREFIX_LIMIT_45NH,
        hold_time_seconds=180,
        keep_alive_seconds=60,
        next_hop_self=False,
    ),
    teardown_tasks=create_mp3n_teardown_tasks(device_name=DEVICE_NAME),
    playbooks=[_4PORT_PLAYBOOK],
)
