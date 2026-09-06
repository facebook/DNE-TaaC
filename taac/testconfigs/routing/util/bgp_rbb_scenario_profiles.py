# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""RBB SRv6 qualification — scenario profiles and command builders.

Centralizes every device-side command bundle and verification spec the RBB
SRv6 tasks consume, so the *exact* CLI lives with the scenario (not hard-coded
inside the ``BaseTask`` classes — §5.4 of the OSS onboarding guide).

Physical wiring (which port-channel / IXIA edge interface a given node uses) is
NOT hardcoded here: the interface-bearing builders take an ``RbbTopology``
(derived from the run's ``circuit_info.csv``; see ``bgp_rbb_topology``) and the
SRv6 assert token comes from the ``Srv6Profile`` (derived from the
``TAAC_RBB_SRV6_*`` env plan). Both default to generic, documentation-only
values so the public entrypoints keep working with no external inputs.

A ``Srv6Profile`` bundles the locator (+ its ``show mysid`` token), the
head/mid/tail uSIDs, the decap SID, and the steered tail prefix for one test
case (TC1 uses the full 3-uSID chain).
"""

from __future__ import annotations

import ipaddress
import os
import shlex
import typing as t
from dataclasses import dataclass, field

from taac.testconfigs.routing.util import bgp_rbb_constants as C
from taac.testconfigs.routing.util.bgp_rbb_topology import (
    load_rbb_topology,
    RbbTopology,
)


@dataclass(frozen=True)
class Srv6Profile:
    """One SRv6 scenario: locator (+token) + uSID chain + decap SID + prefix."""

    name: str
    locator: str = C.SRV6_LOCATOR
    locator_token: str = C.SRV6_LOCATOR_TOKEN
    usid_head: str = C.SRV6_USID_HEAD
    usid_mid: str = C.SRV6_USID_MID
    # The final container function must be the MySID entry configured for
    # decapsulation. ``TAAC_RBB_SRV6_DECAP_SID`` may intentionally override the
    # representative tail default, so use the effective decap SID here.
    usid_tail: str = C.SRV6_DECAP_SID
    decap_sid: str = C.SRV6_DECAP_SID
    tail_prefix: str = C.TAIL_DEST_PREFIX
    usids: t.Tuple[str, ...] = field(default_factory=tuple)

    @property
    def encap_usids(self) -> t.Tuple[str, ...]:
        """uSIDs placed on the wire by the local SRv6 headend.

        ``usids`` describes the complete logical head→mid→tail chain.  The
        direct route is installed on the head itself, so its own MySID must not
        be the first active function in the encapsulated packet.  The wire
        container therefore starts with the next endpoint (mid) and ends with
        the decap function.
        """
        if len(self.usids) < 2:
            raise ValueError(
                "an SRv6 headend route requires at least a head and a remote uSID"
            )
        return self.usids[1:]


# TC1: full 3-uSID head→mid→tail chain.
SRV6_3_USIDS_PROFILE: Srv6Profile = Srv6Profile(
    name="srv6_3_usids",
    usids=(C.SRV6_USID_HEAD, C.SRV6_USID_MID, C.SRV6_DECAP_SID),
)


def _topology(topology: t.Optional[RbbTopology]) -> RbbTopology:
    return topology if topology is not None else load_rbb_topology()


# ─── Verification specs (consumed by rbb_srv6_verify task) ────────────────
def verify_core_links_up_spec(
    node: str, topology: t.Optional[RbbTopology] = None
) -> t.Dict[str, t.Any]:
    """S02-S05: the core port-channel members are Up on this node.

    A REAL link-up assertion (not a passive dump): asserts each core
    port-channel's ``show`` name AND every member interface is present in
    ``fboss2 show aggregate-port`` output (members drop out of the table when a
    link is down / removed from the bundle). If ``TAAC_RBB_CORE_UP_TOKEN`` is
    set, that liveness substring (e.g. the FBOSS forwarding token) is asserted
    too. All expected tokens are topology-derived — nothing lab-specific is
    committed.
    """
    top = _topology(topology).node(node)
    expect: t.List[str] = []
    for pc in top.core_pcs:
        expect.append(pc.show_name)
        expect.extend(pc.members)
    if C.CORE_MEMBER_UP_TOKEN:
        expect.append(C.CORE_MEMBER_UP_TOKEN)
    return {
        "gate": "S02_05_core_links_up",
        "show_cmd": "fboss2 show aggregate-port",
        "expect_contains": expect,
        "interfaces_up": [
            member for pc in top.core_pcs for member in pc.members
        ],
    }


def verify_peer_loopback_learned_spec(node: str) -> t.Dict[str, t.Any]:
    """S07: the PEER node's loopback is present in this node's RIB.

    Confirms core iBGP/OpenR actually delivered reachability: R1 must have R2's
    loopback (and vice versa). The loopback values are the (env-overridable,
    doc-range) ``R{1,2}_ROUTER_ID`` constants — real values arrive via the
    uncommitted lab profile, never committed.
    """
    peer_v4 = C.R2_ROUTER_ID if node == "r1" else C.R1_ROUTER_ID
    return {
        "gate": "S07_peer_loopback_learned",
        "show_cmd": _route_details_for(f"{peer_v4}/32"),
        "expect_contains": [peer_v4],
    }


def verify_openr_adjacency_spec(
    node: str, topology: t.Optional[RbbTopology] = None
) -> t.Dict[str, t.Any]:
    """S06/S13: OpenR is up, adjacent over the core, and redistributing loopbacks.

    Pure-OSS, non-destructive fboss2 read (the shipped ``Openr*HealthCheck``
    checks raise ``NotImplementedError`` in OSS — they need Meta-internal OpenR
    thrift). The PEER node's loopback must appear in this node's route table
    with an ``OPENR`` client: FBOSS only installs an OPENR-owned route for that
    loopback once OpenR has initialized, formed a Spark adjacency over the core
    port-channel, and the peer has redistributed its loopback into OpenR. The
    single ``Client: OPENR`` fact therefore proves the IGP adjacency and
    loopback-redistribution prerequisite for the later edge-routing stages.
    """
    peer_v4 = C.R2_ROUTER_ID if node == "r1" else C.R1_ROUTER_ID
    return {
        "gate": "S06_S13_openr_adjacency",
        "show_cmd": _route_details_for(f"{peer_v4}/32"),
        "expect_contains": ["OPENR", peer_v4],
    }


def _counter_read_cmd(cmd_env: str, default: str) -> str:
    return os.environ.get(cmd_env, default)


def srv6_encap_counter_spec(
    node: str, topology: t.Optional[RbbTopology] = None
) -> t.Dict[str, t.Any]:
    """S25: R1 SRv6 encap counter (core PC egress) — snapshot/assert delta.

    Returns the counter command + integer-extraction regex for the head (R1)
    encap direction: packets routed onto the core toward the tail. Default reads
    the first core PC member's tx packets via ``fboss2 show port <member>
    counters``; override the exact CLI/regex per lab via env.
    """
    top = _topology(topology).node(node)
    member = ""
    if top.core_pcs and top.core_pcs[0].members:
        member = top.core_pcs[0].members[0]
    default_cmd = (
        f"fboss2 show port {shlex.quote(member)} counters"
        if member
        else "fboss2 show port counters"
    )
    return {
        "gate": "S25_srv6_encap_delta",
        "direction": "encap",
        "counter_cmd": _counter_read_cmd("TAAC_RBB_ENCAP_COUNTER_CMD", default_cmd),
        "counter_regex": _counter_read_cmd(
            "TAAC_RBB_ENCAP_COUNTER_REGEX", r"[Oo]ut(?:put)?\D*(\d+)"
        ),
    }


def srv6_decap_counter_spec(
    node: str, topology: t.Optional[RbbTopology] = None
) -> t.Dict[str, t.Any]:
    """S25: R2 tail-path counter — snapshot/assert delta.

    The public FBOSS CLI has no portable per-MySID counter command. The default
    therefore reads the selected R2 edge's egress packets, which proves delivery
    after decapsulation but is not itself SRv6-specific. Override the command and
    regex with a platform's actual decap-object counter for strict S25 evidence.
    """
    top = _topology(topology).node(node)
    edge = top.primary_ixia_interface or ""
    default_cmd = (
        f"fboss2 show port {shlex.quote(edge)} counters"
        if edge
        else "fboss2 show port counters"
    )
    return {
        "gate": "S25_srv6_decap_delta",
        "direction": "decap",
        "counter_cmd": _counter_read_cmd(
            "TAAC_RBB_DECAP_COUNTER_CMD", default_cmd
        ),
        "counter_regex": _counter_read_cmd(
            "TAAC_RBB_DECAP_COUNTER_REGEX", r"[Oo]ut(?:put)?\D*(\d+)"
        ),
    }


def _route_details_for(prefix: str) -> str:
    """``fboss2 show route details`` sliced to one prefix's block.

    ``fboss2`` has no per-prefix route show, so grep the details output for the
    ``Network Address: <prefix>`` block (up to the next blank line). The slash
    in the prefix is escaped for the sed address regex.
    """
    # Canonicalization both avoids ambiguous host bits and restricts the shell
    # interpolation below to valid address characters.
    canonical = str(ipaddress.ip_network(prefix, strict=True))
    esc = canonical.replace(".", r"\.").replace("/", r"\/")
    return f"fboss2 show route details | sed -n '/Network Address: {esc}/,/^$/p'"


def verify_pc162_global_ipv6_spec(
    node: str,
    topology: t.Optional[RbbTopology] = None,
    rif_token: t.Optional[str] = None,
) -> t.Dict[str, t.Any]:
    """S10: the topology-selected core interface has its expected IPv6 RIF.

    S02-S05 already proves the selected port-channel and member are Up. This
    gate reads that member's interface details and requires the configured
    CORE<n> IPv6 address. ``TAAC_RBB_PC162_RIF_TOKEN`` remains an optional
    platform-specific display-token override.
    """
    node_topology = _topology(topology).node(node)
    pc = node_topology.rif_verify_pc
    if pc is None or not pc.members:
        raise ValueError(f"{node}: no core interface is available for S10 RIF verify")
    pc_index = node_topology.core_pcs.index(pc)
    rif_token = C.PC162_RIF_TOKEN if rif_token is None else rif_token
    expected_address = rif_token or str(
        ipaddress.ip_interface(C.core_rif_cidr(node, pc_index, 6)).ip
    )
    return {
        "gate": "S10_pc_rif",
        "show_cmd": f"fboss2 show interface {shlex.quote(pc.members[0])}",
        "expect_contains": [expected_address],
    }


def verify_srv6_tunnels_spec(
    node: str, profile: t.Optional[Srv6Profile] = None
) -> t.Dict[str, t.Any]:
    """S11: SRv6 micro-SIDs are programmed (real ``fboss2 show mysid``).

    Both nodes carry an ADJACENCY_MICRO_SID under the configured locator block;
    the tail (R2) additionally carries the DECAPSULATE_AND_LOOKUP SID. Assert the
    full, configured SID tokens rendered by the CLI. The agent config's decimal
    map key (for example ``10188`` for function 0x27cc) is intentionally not
    checked because ``fboss2 show mysid`` does not render that internal key.
    """
    profile = profile if profile is not None else SRV6_3_USIDS_PROFILE
    adjacency_sid = profile.usid_head if node == "r1" else profile.usid_mid
    adjacency_token = str(
        ipaddress.ip_address(str(adjacency_sid).split("/", 1)[0])
    )
    expect = [profile.locator_token, adjacency_token, C.SRV6_BEHAVIOR_ADJACENCY]
    if node == "r2":
        decap_token = str(
            ipaddress.ip_address(str(profile.decap_sid).split("/", 1)[0])
        )
        expect.extend([decap_token, C.SRV6_BEHAVIOR_DECAP])
    return {
        "gate": "S11_srv6_mysid",
        "show_cmd": "fboss2 show mysid",
        "expect_contains": expect,
    }


def verify_route_owner_te_agent_spec(profile: Srv6Profile) -> t.Dict[str, t.Any]:
    """S22-S23: after install, the tail prefix is owned by TE_AGENT."""
    packed_segment = C.pack_usid_container(profile.locator, profile.encap_usids)
    return {
        "gate": "S22_23_route_owner_te_agent",
        "show_cmd": _route_details_for(profile.tail_prefix),
        "expect_contains": [
            profile.tail_prefix,
            C.ROUTE_OWNER_TE_AGENT,
            profile.decap_sid,
            packed_segment,
        ],
    }


def verify_srv6_counters_spec(profile: Srv6Profile) -> t.Dict[str, t.Any]:
    """S26: SRv6 forwarding state present (ASIC FIB populated).

    Counter deltas are asserted separately when traffic is enabled.  This gate
    anchors the FIB assertion to the exact steered prefix, resolved decap next
    hop, and rendered SRv6 segment container instead of accepting any non-empty
    IPv6 route table.
    """
    packed_segment = C.pack_usid_container(profile.locator, profile.encap_usids)
    return {
        "gate": "S26_srv6_fib_present",
        "show_cmd": _route_details_for(profile.tail_prefix),
        "fib_prefixes": [profile.tail_prefix],
        "expect_contains": [
            profile.tail_prefix,
            profile.decap_sid,
            packed_segment,
        ],
    }


def verify_route_owner_bgpd_spec(
    profile: Srv6Profile, gate: str = "S28_route_owner_bgpd"
) -> t.Dict[str, t.Any]:
    """Assert the exact prefix is BGPD-owned and not owned by TE_AGENT."""
    return {
        "gate": gate,
        "show_cmd": _route_details_for(profile.tail_prefix),
        "expect_contains": [profile.tail_prefix, C.ROUTE_OWNER_BGPD],
        "expect_absent": [C.ROUTE_OWNER_TE_AGENT],
    }


def verify_remote_ixia_prefix_spec() -> t.Dict[str, t.Any]:
    """S17-S18: the exact tail IXIA prefix is BGPD-owned on the head."""
    prefix = (
        f"{C.IXIA_TAIL_ADVERTISED_PREFIX}/"
        f"{C.IXIA_TAIL_ADVERTISED_PREFIX_LEN}"
    )
    return {
        "gate": "S17_18_exact_remote_ixia_prefix",
        "show_cmd": _route_details_for(prefix),
        "fib_prefixes": [prefix],
        "expect_contains": [prefix, C.ROUTE_OWNER_BGPD, C.SRV6_DECAP_SID],
    }
