# pyre-unsafe
"""Shared builders for the OTG hardening conveyor profiles.

This module is a LIBRARY, not a runnable test config — it defines no
`test_config()`.  The runnable configs are:

  taac/otg/otg_hardening_restarts_test_config.py    4 interfaces / 4 sessions
  taac/otg/otg_hardening_ecmp_test_config.py        4 / 2
  taac/otg/otg_hardening_malformed_test_config.py   3 / 2

Between them they cover all eight ported playbooks.  They exist as separate
configs because ixia-c community edition caps control-plane interfaces and
sessions at 4 each, and the full set needs far more — see
`taac/otg/HARDENING_SETUP.md`.

There is deliberately no all-eight-in-one-run config.  One existed and rotted: it
could not run on community edition, so nothing exercised it, and it silently kept
a `parent_prefixes_to_ignore` bug already fixed in the malformed profile.  Run the
three back to back instead — that also isolates failures.  If a single-invocation
config is wanted, `build_hardening_test_config` makes it ~15 lines; add it when
someone can actually run it.

See `taac/otg/README.md` for the fidelity analysis of which upstream playbooks
port and which do not.
"""
import json
import logging
import typing as t

from ixia.ixia import types as ixia_types
from taac.oss_topology_info.device_info_loader import get_mac_from_hostname_oss
from taac.otg.otg_bgp_malformed_updates import rfc7606_malformation_suite
from taac.otg.otg_hardening_playbooks import (
    device_group_name,
    ECMP_1_DEVICE_GROUP_PREFIX,
    ECMP_2_DEVICE_GROUP_PREFIX,
    HIGH_QUEUE_BGP_CP_TRAFFIC,
    MALFORMED_BGP_DEVICE_GROUP_PREFIX,
    MEASURED_DEVICE_GROUP_PREFIX,
)
from taac.runner.testbed_topology import (
    ConfigTopology,
    LinkType,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import (
    BasicPortConfig,
    BasicTrafficItemConfig,
    BgpConfig,
    DeviceGroupConfig,
    DirectIxiaConnection,
    Endpoint,
    Field,
    IpAddressesConfig,
    PacketHeader,
    Reference,
    RouteScale,
    RouteScaleSpec,
    TestConfig,
    TrafficEndpoint,
)

# -- AS / timers --------------------------------------------------------------

DUT_AS = 65000
OTG_LOCAL_AS = 65001

BGP_HOLD_TIMER = 90
BGP_KEEPALIVE_TIMER = 30

# -- Scale --------------------------------------------------------------------
# Tuned so ECMP_2 crosses typical platform MEMBER limits while group count
# stays well under group limits.  That separation is what keeps the member
# test distinct from the group test.  Starting values; retune per platform.

BASELINE_PREFIX_COUNT = 100
BASELINE_V4_PREFIX_LENGTH = 24
BASELINE_V6_PREFIX_LENGTH = 64

ECMP_PREFIX_COUNT = 500
ECMP_PREFIX_LENGTH = 64

# Host offset where an ECMP group's simulated devices start.
#
# Must clear the DUT's gateway.  With devices starting at ::1 and the gateway at
# ::2, the SECOND simulated device would land on ::2 — the DUT's own address.
# Starting at ::10 leaves room for the gateway and for a reasonable multiplier.
ECMP_DEVICE_HOST_OFFSET = 0x10

# Members are prefix_count x total next-hops, and next-hops come from the ECMP
# groups' multipliers — which the ECMP profile owns, since only it knows what its
# interface budget allows.

# -- Traffic ------------------------------------------------------------------

# Absolute pps, like the CP flood.  A live ixia-c run at 10% line rate showed
# ~34% STEADY loss on every measured flow (per-second tx ~122k vs rx ~84k): the
# engine transmits faster than it can receive and count, so the 0.1% threshold
# was unsatisfiable regardless of DUT health.  1000 pps per flow is well inside
# a software engine while still resolving a restart outage.
MEASURED_FLOW_PPS = 1000

# Absolute pps, not a line-rate percentage: what this overloads is the CPU punt
# path, where CoPP policers sit in the 10^2-10^3 pps range (FBOSS's own constants
# are 100 and 200), so thousands of pps suffice.  A percentage is also not
# backend-portable — upstream's 70% is ~10^8 pps on a 400G port, far enough past
# any CoPP limit that no queue config keeps BGP alive, while on a software engine
# it is unachievable and resolves to whatever the container CPU allows.  10000 is
# ~10x a typical queue policer and well within a software engine.
CP_FLOW_PPS = 10000

BGP_PORT = 179
BGP_CP_DSCP = 48

# Spacing between replayed malformed UPDATEs.  Deliberately non-zero so each is
# processed as a distinct message rather than arriving coalesced in one read,
# which would blur which malformation provoked any reaction.
MALFORMED_UPDATE_GAP_MS = 500

# Frames the DUT will punt to its CPU high-priority queue.
#
# IPv4, deliberately, where upstream's BGP_CP_TRAFFIC_PACKET_HEADERS is IPv6.
# The DUT punts TCP/179 to the high-priority queue via rx-reason regardless of
# address family, and this test asserts BGP session survival rather than
# anything address-family specific — so parity buys nothing observable here,
# while v4+TCP is the lower-risk composition on a software traffic engine.
CP_SRC_MAC = "00:00:00:11:22:33"

# -- Device group names ------------------------------------------------------
# Prefixes come from otg_hardening_playbooks, which also defines the regexes
# the playbooks match them with.  Do not restate the strings here.

MEASURED_DG_PREFIX = MEASURED_DEVICE_GROUP_PREFIX
ECMP_1_DG_PREFIX = ECMP_1_DEVICE_GROUP_PREFIX
ECMP_2_DG_PREFIX = ECMP_2_DEVICE_GROUP_PREFIX
MALFORMED_BGP_DG_PREFIX = MALFORMED_BGP_DEVICE_GROUP_PREFIX

MEASURED_DG_INDEX = 0
ECMP_1_DG_INDEX = 1
ECMP_2_DG_INDEX = 2
MALFORMED_BGP_DG_INDEX = 3


def _v4_net(index: int) -> str:
    return f"10.0.{index + 1}"


def _v6_net(index: int) -> str:
    return f"2001:db8:{index + 1}"


def _baseline_v4_prefix(index: int) -> str:
    return f"100.{index + 1}.0.0"


def _baseline_v6_prefix(index: int) -> str:
    return f"2001:db8:1{index + 1}00::"


# Both ECMP device groups on both ports advertise this SAME aggregate, so each
# prefix accumulates next-hops from every group that is up.  That is what
# creates ECMP members on the DUT.
# NOTE: every group of an IPv6 literal must be hex.  An earlier value here was
# "2001:db8:ecmp::", which reads nicely but is not a valid address — 'm' and 'p'
# are not hex digits — and snappi rejected it at set_config with
# "Invalid 2001:db8:ecmp:: format, expected ipv6".  "ec00" keeps the mnemonic
# while staying valid, and matches the ec1/ec2 labels used for the peer subnets.
ECMP_AGGREGATE_PREFIX = "2001:db8:ec00::"


def _bgp_capabilities() -> t.List[int]:
    return [
        ixia_types.BgpCapability.IpV4Unicast,
        ixia_types.BgpCapability.IpV6Unicast,
    ]


def _v6_bgp_config(
    starting_prefix: str,
    prefix_count: int,
    prefix_length: int,
    network_group_index: int = 0,
) -> BgpConfig:
    return BgpConfig(
        local_as_4_bytes=OTG_LOCAL_AS,
        enable_4_byte_local_as=True,
        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
        bgp_capabilities=_bgp_capabilities(),
        hold_timer=BGP_HOLD_TIMER,
        keepalive_timer=BGP_KEEPALIVE_TIMER,
        route_scales=[
            RouteScaleSpec(
                network_group_index=network_group_index,
                v6_route_scale=RouteScale(
                    multiplier=1,
                    prefix_count=prefix_count,
                    prefix_length=prefix_length,
                    starting_prefixes=starting_prefix,
                    prefix_step="0:0:0:1::",
                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                ),
            ),
        ],
    )


def _measured_device_group(
    index: int,
    afs: t.Sequence[str] = ("v4", "v6"),
    bgp_afs: t.Sequence[str] = ("v4", "v6"),
) -> DeviceGroupConfig:
    """Dual-stack group carrying the traffic whose loss is asserted.

    `afs` picks which families get ADDRESSES, and so which measured flows are
    possible; each costs an interface.  `bgp_afs` picks which of those also get a
    peer — the measured traffic needs only addresses, since the DUT forwards
    between the connected subnets without BGP, so peers exist only to give the
    convergence and session-snapshot checks something to observe.
    """
    v4 = _v4_net(index)
    v6 = _v6_net(index)
    return DeviceGroupConfig(
        device_group_index=MEASURED_DG_INDEX,
        device_group_name=device_group_name(MEASURED_DG_PREFIX, index),
        multiplier=1,
        enable=True,
        v4_addresses_config=(
            IpAddressesConfig(
                starting_ip=f"{v4}.1",
                gateway_starting_ip=f"{v4}.2",
                mask=24,
            )
            if "v4" in afs
            else None
        ),
        v6_addresses_config=(
            IpAddressesConfig(
                starting_ip=f"{v6}::1",
                gateway_starting_ip=f"{v6}::2",
                mask=64,
            )
            if "v6" in afs
            else None
        ),
        v4_bgp_config=(
            BgpConfig(
                local_as_4_bytes=OTG_LOCAL_AS,
                enable_4_byte_local_as=True,
                bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                bgp_capabilities=_bgp_capabilities(),
                hold_timer=BGP_HOLD_TIMER,
                keepalive_timer=BGP_KEEPALIVE_TIMER,
                route_scales=[
                    RouteScaleSpec(
                        network_group_index=0,
                        v4_route_scale=RouteScale(
                            multiplier=1,
                            prefix_count=BASELINE_PREFIX_COUNT,
                            prefix_length=BASELINE_V4_PREFIX_LENGTH,
                            starting_prefixes=_baseline_v4_prefix(index),
                            prefix_step="0.0.1.0",
                            ip_address_family=ixia_types.IpAddressFamily.IPV4,
                        ),
                    ),
                ],
            )
            if "v4" in bgp_afs and "v4" in afs
            else None
        ),
        v6_bgp_config=(
            _v6_bgp_config(
                starting_prefix=_baseline_v6_prefix(index),
                prefix_count=BASELINE_PREFIX_COUNT,
                prefix_length=BASELINE_V6_PREFIX_LENGTH,
            )
            if "v6" in bgp_afs and "v6" in afs
            else None
        ),
    )


def _ecmp_device_group(
    index: int,
    dg_index: int,
    name_prefix: str,
    subnet_tag: str,
    multiplier: int,
    enable: bool,
) -> DeviceGroupConfig:
    """v6 group advertising the shared ECMP aggregate.

    `multiplier` is the number of simulated devices, hence the number of distinct
    next-hops this group contributes to every aggregate prefix.  Each device
    costs an interface and a session.
    """
    v6 = f"{_v6_net(index)}:{subnet_tag}"
    return DeviceGroupConfig(
        device_group_index=dg_index,
        device_group_name=device_group_name(name_prefix, index),
        multiplier=multiplier,
        enable=enable,
        v6_addresses_config=IpAddressesConfig(
            # Devices occupy ::10, ::11, ... so they never collide with the DUT
            # gateway at ::2 — see ECMP_DEVICE_HOST_OFFSET.
            starting_ip=f"{v6}::{ECMP_DEVICE_HOST_OFFSET:x}",
            gateway_starting_ip=f"{v6}::2",
            mask=64,
        ),
        v6_bgp_config=_v6_bgp_config(
            starting_prefix=ECMP_AGGREGATE_PREFIX,
            prefix_count=ECMP_PREFIX_COUNT,
            prefix_length=ECMP_PREFIX_LENGTH,
        ),
    )


# Host part of the malformed speaker's address within its port's v4 subnet.
# Distinct from the measured group's .1 so both can coexist on one port.
MALFORMED_PEER_HOST = 10


def malformed_peer_address(index: int) -> str:
    """The malformed speaker's own address on `index` (0-based port)."""
    return f"{_v4_net(index)}.{MALFORMED_PEER_HOST}"


def malformed_peer_prefix(index: int) -> str:
    """The malformed speaker's address as a host prefix.

    BGP_SESSION_CHECK takes `parent_prefixes_to_ignore` and filters peers whose
    address is a subnet of one, so a /32 excludes exactly this peer.
    """
    return f"{malformed_peer_address(index)}/32"


def _malformed_bgp_device_group(index: int) -> DeviceGroupConfig:
    """v4 group whose peer replays deliberately non-conformant BGP UPDATEs.

    Separate from the measured path because OTG replays a peer's sequence on each
    establishment, so toggling this group up is the trigger — and flapping the
    measured peer would invalidate its own packet-loss postcheck.

    `enable=False` holds this peer down through setup, so the playbook's own
    toggle drives establishment and the replay fires in-window.  Not absolutely:
    protocol start is all-or-nothing, so the peer can establish for a moment
    before the hold-down lands and fire one early replay outside any snapshot
    window.  Expect that in DUT logs rather than chasing it — see "A disabled
    peer establishes briefly before being held down" in HARDENING_SETUP.md.
    """
    # `BgpUpdateSequence` is a local addition to taac/thrift/ixia/ixia.thrift, and
    # the generated module is a mechanical copy of a configerator source — so an
    # upstream sync reverts it, and a checkout without regenerated thrift never
    # had it.  Fail loudly: this speaker has no route_scales by design, so
    # without the sequence it establishes, advertises nothing, and the profile
    # passes having replayed no malformation at all.
    if getattr(ixia_types, "BgpUpdateSequence", None) is None:
        raise RuntimeError(
            "ixia.BgpUpdateSequence is absent from the generated thrift module, "
            "so the malformed BGP speaker cannot be built. Regenerate with "
            "./scripts/run_tests.sh --regen-thrift, or land the struct in "
            "configerator for a durable fix. See the known gaps in "
            "taac/otg/HARDENING_SETUP.md."
        )

    v4 = f"{_v4_net(index)}"
    return DeviceGroupConfig(
        device_group_index=MALFORMED_BGP_DG_INDEX,
        device_group_name=device_group_name(MALFORMED_BGP_DG_PREFIX, index),
        multiplier=1,
        enable=False,
        v4_addresses_config=IpAddressesConfig(
            starting_ip=malformed_peer_address(index),
            gateway_starting_ip=f"{v4}.2",
            mask=24,
        ),
        v4_bgp_config=BgpConfig(
            local_as_4_bytes=OTG_LOCAL_AS,
            enable_4_byte_local_as=True,
            bgp_peer_type=ixia_types.BgpPeerType.EBGP,
            # The same capability set as every other peer, deliberately.  A
            # bespoke list here -- v4-only, or v4 plus RouteRefresh as an earlier
            # revision had -- makes this speaker negotiate differently from the
            # measured peers, which changes the bgpd code paths its session can
            # reach.  A reaction could then be attributed to a malformation when
            # it came from the capability difference.  The replayed bytes are
            # supposed to be the only variable, so the capabilities must not be.
            bgp_capabilities=_bgp_capabilities(),
            hold_timer=BGP_HOLD_TIMER,
            keepalive_timer=BGP_KEEPALIVE_TIMER,
            # No route_scales: this peer advertises nothing declaratively.
            # Everything it sends comes from the explicit UPDATE sequence.
            update_sequence=ixia_types.BgpUpdateSequence(
                updates=[
                    ixia_types.BgpUpdateSequenceEntry(
                        update_bytes=update_hex,
                        time_gap_ms=MALFORMED_UPDATE_GAP_MS,
                    )
                    for update_hex in rfc7606_malformation_suite(
                        next_hop=malformed_peer_address(index)
                    )
                ],
            ),
        ),
    )


def _bgp_cp_packet_headers() -> t.List[PacketHeader]:
    """Frames shaped like BGP control-plane traffic, aimed at the DUT CPU.

    Deliberately narrow: only the stacks/fields that
    OtgTrafficGen._PACKET_HEADER_FIELD_MAP understands.  The upstream
    BGP_CP_TRAFFIC_PACKET_HEADERS constant carries restpy-only constructs, so
    this is a purpose-built equivalent rather than a reuse.

    Destination MAC and IP come from References the TrafficGenerator pipeline
    resolves before OtgTrafficGen sees them: DST_MAC_ADDRESS is the DUT's own
    MAC and SRC_GATEWAY_IPV4_ADDRESS is the DUT's interface address — together
    that is exactly a frame the DUT must punt rather than forward.
    """
    return [
        PacketHeader(
            query=ixia_types.Query(
                regex="^ethernet$",
                query_type=ixia_types.QueryType.STACK_TYPE_ID,
            ),
            fields=[
                Field(
                    query=ixia_types.Query(regex="Destination MAC Address"),
                    attrs_json=json.dumps({"ValueType": "increment",
                                           "StepValue": "00:00:00:00:00:00",
                                           "CountValue": 1}),
                    references={
                        "StartValue": Reference(
                            type=taac_types.ReferenceType.DST_MAC_ADDRESS
                        ),
                    },
                ),
                Field(
                    query=ixia_types.Query(regex="Source MAC Address"),
                    attrs_json=json.dumps({"SingleValue": CP_SRC_MAC}),
                ),
            ],
        ),
        PacketHeader(
            query=ixia_types.Query(
                regex="^ipv4$",
                query_type=ixia_types.QueryType.STACK_TYPE_ID,
            ),
            fields=[
                Field(
                    query=ixia_types.Query(regex="Source Address"),
                    attrs_json=json.dumps({"ValueType": "increment",
                                           "StepValue": "0.0.0.0",
                                           "CountValue": 1}),
                    references={
                        "StartValue": Reference(
                            type=taac_types.ReferenceType.SRC_IPV4_ADDRESS
                        ),
                    },
                ),
                Field(
                    query=ixia_types.Query(regex="Destination Address"),
                    attrs_json=json.dumps({"ValueType": "increment",
                                           "StepValue": "0.0.0.0",
                                           "CountValue": 1}),
                    references={
                        "StartValue": Reference(
                            type=taac_types.ReferenceType.SRC_GATEWAY_IPV4_ADDRESS
                        ),
                    },
                ),
            ],
        ),
        PacketHeader(
            query=ixia_types.Query(
                regex="^tcp$",
                query_type=ixia_types.QueryType.STACK_TYPE_ID,
            ),
            fields=[
                Field(
                    query=ixia_types.Query(regex="TCP-Source-Port"),
                    attrs_json=json.dumps({"SingleValue": BGP_PORT}),
                ),
                Field(
                    query=ixia_types.Query(regex="TCP-Dest-Port"),
                    attrs_json=json.dumps({"SingleValue": BGP_PORT}),
                ),
            ],
        ),
    ]


def _tgen_links(
    topology: ConfigTopology,
) -> t.List[t.Tuple[str, str, str, str]]:
    """Extract TGEN links as (dut_host, dut_port, tgen_host, tgen_port)."""
    return [
        (link.local_host, link.local_port, link.remote_host, link.remote_port)
        for link in topology.links
        if link.link_type == LinkType.TGEN
    ]


# ixia-c community edition caps two DIFFERENT counts at 4 each: "control plane
# connected interfaces" is configured IP addresses, "control plane sessions" is
# BGP peers — both per SIMULATED DEVICE per AF, so a group's `multiplier`
# multiplies them.  Interfaces usually binds first, since a device can carry an
# address without a peer but never the reverse; and a group counts even when it
# ships `enable=False`, because ixia-c counts the pushed config rather than what
# is up.  Exceeding either fails at set_config with an opaque HTTP 500, so
# profiles declare a budget and this checks both at build time.
COMMUNITY_EDITION_MAX_CP_INTERFACES = 4
COMMUNITY_EDITION_MAX_BGP_SESSIONS = 4


def _device_group_multiplier(dg) -> int:
    """Simulated devices in a group — each is a real interface and session.

    Counting groups instead of devices under-reports the licence cost by this
    factor, which once made a 67-device config look like 9 interfaces.
    """
    return max(1, int(getattr(dg, "multiplier", 1) or 1))


def _count_cp_interfaces(basic_port_configs) -> int:
    """Configured IP addresses — ixia-c's 'control plane connected interfaces'."""
    return sum(
        _device_group_multiplier(dg)
        for pc in basic_port_configs
        for dg in pc.device_group_configs
        for addrs in (dg.v4_addresses_config, dg.v6_addresses_config)
        if addrs is not None
    )


def _count_bgp_sessions(basic_port_configs) -> int:
    return sum(
        _device_group_multiplier(dg)
        for pc in basic_port_configs
        for dg in pc.device_group_configs
        for bgp in (dg.v4_bgp_config, dg.v6_bgp_config)
        if bgp is not None
    )


def build_hardening_test_config(
    topology: ConfigTopology,
    *,
    name: str,
    playbooks: t.List,
    measured_afs_per_port: t.Sequence[t.Sequence[str]] = (("v4", "v6"), ("v4", "v6")),
    measured_bgp_afs_per_port: t.Sequence[t.Sequence[str]] = (("v4", "v6"), ("v4", "v6")),
    ecmp_ports: t.Sequence[int] = (),
    ecmp_multipliers: t.Tuple[int, int] = (1, 1),
    malformed_ports: t.Sequence[int] = (),
    include_cp_flow: bool = False,
    prefix_targeted_flows: t.Sequence[t.Tuple[str, str, int, int, int, int]] = (),
    max_cp_interfaces: t.Optional[int] = None,
    max_bgp_sessions: t.Optional[int] = None,
) -> TestConfig:
    """Assemble a hardening TestConfig from a chosen set of device groups.

    Both ports always get the measured group's addressing, since the measured
    flows need it; everything else is opt-in so a profile can stay inside its
    control-plane budget.

    Args:
        name: TestConfig name.
        playbooks: Playbooks to attach.
        measured_afs_per_port: Families the measured group gets ADDRESSES for,
            per port.  Each costs an interface; a measured flow is emitted only
            for families present on BOTH ports.
        measured_bgp_afs_per_port: Which of those also get a peer.  Use () for
            addresses without a peer — saves a session, NOT an interface.
        ecmp_ports: Port indices that get ECMP_1 + ECMP_2.
        ecmp_multipliers: Simulated devices in (ECMP_1, ECMP_2).  Each device is
            one interface and one session, so community edition needs (1, 1).
        malformed_ports: Port indices that get the malformed-UPDATE speaker.
        include_cp_flow: Add HIGH_QUEUE_BGP_CP_TRAFFIC.
        prefix_targeted_flows: Flows addressed INTO a BGP-advertised prefix
            instead of a device group's interface, as
            (name, af, src_port, dst_port, dst_dg_index, dst_network_group) —
            this is what makes traffic traverse BGP routes.  The source is always
            the measured group, so the DUT has a connected route back.
        max_cp_interfaces: Raise if addresses exceed this — usually the binding
            constraint.  Pass COMMUNITY_EDITION_MAX_CP_INTERFACES for ixia-c.
        max_bgp_sessions: Raise if peers exceed this.
    """
    tgen_links = _tgen_links(topology)
    if len(tgen_links) < 2:
        raise RuntimeError(
            f"{name} requires at least 2 TGEN links in the circuit CSV, "
            f"found {len(tgen_links)}: {tgen_links}"
        )

    tgen_links = tgen_links[:2]
    device_name = tgen_links[0][0]

    dut_mac = get_mac_from_hostname_oss(device_name)
    if include_cp_flow and not dut_mac:
        # The CP flow's destination MAC is a DST_MAC_ADDRESS Reference the
        # TrafficGenerator pipeline resolves from Endpoint.mac_address.  Without
        # it the flood is addressed to nothing and the DUT never punts it, so
        # fail here rather than silently sending dead traffic.
        raise RuntimeError(
            f"No MAC address for {device_name} in the device-info CSV. "
            f"{HIGH_QUEUE_BGP_CP_TRAFFIC} needs it to target the DUT CPU."
        )

    direct_ixia_connections = []
    basic_port_configs = []

    for i, (_, _, _, tgen_port) in enumerate(tgen_links):
        direct_ixia_connections.append(
            DirectIxiaConnection(
                interface=tgen_port,
                ixia_port=f"1/{i + 1}",
                is_logical_port=True,
                port_location=tgen_port,
            )
        )

        addr_afs = (
            measured_afs_per_port[i] if i < len(measured_afs_per_port) else ()
        )
        bgp_afs = (
            measured_bgp_afs_per_port[i]
            if i < len(measured_bgp_afs_per_port)
            else ()
        )
        device_groups = [
            _measured_device_group(i, afs=addr_afs, bgp_afs=bgp_afs)
        ]

        if i in ecmp_ports:
            device_groups += [
                _ecmp_device_group(
                    index=i,
                    dg_index=ECMP_1_DG_INDEX,
                    name_prefix=ECMP_1_DG_PREFIX,
                    subnet_tag="ec1",
                    multiplier=ecmp_multipliers[0],
                    enable=True,
                ),
                _ecmp_device_group(
                    index=i,
                    dg_index=ECMP_2_DG_INDEX,
                    name_prefix=ECMP_2_DG_PREFIX,
                    subnet_tag="ec2",
                    multiplier=ecmp_multipliers[1],
                    # Built in full but held down at setup, so each playbook's
                    # toggle-up is a real transition: this group's next-hops join
                    # the shared aggregate while the test is watching.  How much
                    # pressure that applies is still bounded by ecmp_multipliers,
                    # which the licence pins low — see HARDENING_SETUP.md.
                    enable=False,
                ),
            ]

        if i in malformed_ports:
            device_groups.append(_malformed_bgp_device_group(i))

        basic_port_configs.append(
            BasicPortConfig(
                endpoint=f"{device_name}:{tgen_port}",
                device_group_configs=device_groups,
            )
        )

    interfaces = _count_cp_interfaces(basic_port_configs)
    sessions = _count_bgp_sessions(basic_port_configs)
    # Logged unconditionally: an over-budget config otherwise only shows up as an
    # opaque HTTP 500 from the controller, and a silently-changed count (say from
    # editing an address family) shows up nowhere at all.
    logging.getLogger(__name__).info(
        "%s: %d control-plane interface(s), %d BGP session(s)",
        name,
        interfaces,
        sessions,
    )
    for actual, budget, what, knobs in (
        (
            interfaces,
            max_cp_interfaces,
            "control-plane connected interfaces (configured IP addresses)",
            "measured_afs_per_port, ecmp_ports, or malformed_ports",
        ),
        (
            sessions,
            max_bgp_sessions,
            "BGP control-plane sessions (peers)",
            "measured_bgp_afs_per_port, ecmp_ports, or malformed_ports",
        ),
    ):
        if budget is not None and actual > budget:
            raise RuntimeError(
                f"{name} builds {actual} {what} but the budget is {budget}. "
                f"ixia-c community edition rejects this at set_config with an "
                f"opaque HTTP 500. Reduce {knobs} — note that a device group "
                f"counts even when it ships enable=False, and that dropping a "
                f"BGP peer while keeping its IP address saves a session but not "
                f"an interface. See taac/otg/HARDENING_SETUP.md."
            )

    src_endpoint = f"{device_name}:{tgen_links[0][3]}"
    dst_endpoint = f"{device_name}:{tgen_links[1][3]}"

    def _measured_pair():
        return (
            [TrafficEndpoint(name=src_endpoint, device_group_index=MEASURED_DG_INDEX)],
            [TrafficEndpoint(name=dst_endpoint, device_group_index=MEASURED_DG_INDEX)],
        )

    # A measured flow needs the address family on BOTH ports.
    common_afs = set(
        measured_afs_per_port[0] if len(measured_afs_per_port) > 0 else ()
    ) & set(measured_afs_per_port[1] if len(measured_afs_per_port) > 1 else ())

    flows = []
    for af, flow_name, traffic_type in (
        ("v4", f"{MEASURED_DG_PREFIX}_V4", ixia_types.TrafficType.IPV4),
        ("v6", f"{MEASURED_DG_PREFIX}_V6", ixia_types.TrafficType.IPV6),
    ):
        if af not in common_afs:
            continue
        msrc, mdst = _measured_pair()
        flows.append(
            BasicTrafficItemConfig(
                name=flow_name,
                traffic_type=traffic_type,
                src_endpoints=msrc,
                dest_endpoints=mdst,
                line_rate=MEASURED_FLOW_PPS,
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                bidirectional=True,
            )
        )

    for (
        flow_name,
        af,
        src_port,
        dst_port,
        dst_dg,
        dst_ng,
    ) in prefix_targeted_flows:
        traffic_type = (
            ixia_types.TrafficType.IPV6
            if af == "v6"
            else ixia_types.TrafficType.IPV4
        )
        flows.append(
            BasicTrafficItemConfig(
                name=flow_name,
                traffic_type=traffic_type,
                src_endpoints=[
                    TrafficEndpoint(
                        name=f"{device_name}:{tgen_links[src_port][3]}",
                        device_group_index=MEASURED_DG_INDEX,
                    )
                ],
                dest_endpoints=[
                    TrafficEndpoint(
                        name=f"{device_name}:{tgen_links[dst_port][3]}",
                        device_group_index=dst_dg,
                        # This is the whole point: resolve the destination into
                        # the advertised prefix, so the DUT must use its BGP
                        # route rather than a connected one.
                        network_group_index=dst_ng,
                    )
                ],
                line_rate=MEASURED_FLOW_PPS,
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                # Unidirectional: the assertion is about forwarding INTO the
                # BGP-routed prefixes.  The reverse direction would just be
                # connected-route forwarding back to the measured interface.
                bidirectional=False,
            )
        )

    if include_cp_flow:
        cp_src, cp_dst = _measured_pair()
        flows.append(
            BasicTrafficItemConfig(
                name=HIGH_QUEUE_BGP_CP_TRAFFIC,
                traffic_type=ixia_types.TrafficType.IPV4,
                src_endpoints=cp_src,
                dest_endpoints=cp_dst,
                line_rate=CP_FLOW_PPS,
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                bidirectional=False,
                # Ships disabled; the CPU-queue playbook enables it on demand.
                enabled=False,
                packet_headers=_bgp_cp_packet_headers(),
                # DSCP 48 is CS6, hence CLASSSELECTOR.  The OTG backend reads
                # dscp_value directly; phb_type is what the restpy path needs.
                qos_config=ixia_types.QoSConfig(
                    phb_type=ixia_types.PHBTypes.CLASSSELECTOR,
                    dscp_value=BGP_CP_DSCP,
                ),
            )
        )

    return TestConfig(
        name=name,
        basset_pool="",
        traffic_generator_backend=taac_types.TrafficGeneratorBackend.OTG,
        skip_ixia_protocol_verification=False,
        ixia_protocol_verification_timeout=300,
        endpoints=[
            Endpoint(
                name=device_name,
                dut=True,
                mac_address=dut_mac or "",
                direct_ixia_connections=direct_ixia_connections,
            ),
        ],
        basic_port_configs=basic_port_configs,
        basic_traffic_item_configs=flows,
        # Start ONLY the measured flows.  Without this,
        # begin_test_case(traffic_regexes=None) CLEARS _disabled_flows, wiping the
        # CP flood's `enabled=False` — a live run had it transmitting through all
        # four restart playbooks at 100% loss (it is punted to the CPU, never
        # forwarded), failing the packet-loss check too.
        #
        # Upstream's idiom is a negative lookahead. Do NOT copy it: restpy uses
        # re.match while _enable_traffic uses re.search, under which a negative
        # lookahead matches every string including the one it excludes, so it is
        # silently inert.
        traffic_items_to_start=[MEASURED_DG_PREFIX],
        playbooks=playbooks,
        startup_checks=[],
    )
