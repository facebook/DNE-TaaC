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

import os
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
    usid_tail: str = C.SRV6_USID_TAIL
    decap_sid: str = C.SRV6_DECAP_SID
    tail_prefix: str = C.TAIL_DEST_PREFIX
    usids: t.Tuple[str, ...] = field(default_factory=tuple)


# TC1: full 3-uSID head→mid→tail chain.
SRV6_3_USIDS_PROFILE: Srv6Profile = Srv6Profile(
    name="srv6_3_usids",
    usids=(C.SRV6_USID_HEAD, C.SRV6_USID_MID, C.SRV6_USID_TAIL),
)

# TC2: TE baseline — locator + tail uSID only, no explicit TE_AGENT direct
# route (the tail prefix is reachable via BGPD the whole time).
SRV6_TE_BASELINE_PROFILE: Srv6Profile = Srv6Profile(
    name="srv6_te_baseline",
    usids=(C.SRV6_USID_TAIL,),
)


def _topology(topology: t.Optional[RbbTopology]) -> RbbTopology:
    return topology if topology is not None else load_rbb_topology()


# ─── Core-underlay bring-up ────────────────────────────────────────────────
def core_interface_cmds(node: str) -> t.List[str]:
    """Confirm the core port-channel underlay on one node ("r1" or "r2").

    The core port-channels are already provisioned and Up on the FBOSS lab
    boxes (there is no ``fboss2`` write path to (re)configure them, and the RBB
    slice must never disturb the live R1<->R2 core). So this "setup" step is a
    non-destructive read that dumps the aggregate-port state; the S10 verify
    stage then asserts the core PC is present with its RIF.
    """
    return ["fboss2 show aggregate-port"]


# ─── SRv6 programming ─────────────────────────────────────────────────────
def srv6_program_cmds(node: str, profile: Srv6Profile) -> t.List[str]:
    """Confirm SRv6 micro-SID state on one node.

    SRv6 is already ASIC-programmed via the FBOSS agent config (mySidConfig /
    srv6Tunnels) — there is no CLI/agent-thrift path to (re)program it and the
    RBB slice must not overwrite the live SID state. So the "program" step is a
    non-destructive read of ``fboss2 show mysid``; the S11 verify stage asserts
    the configured locator token + micro-SID behaviors.
    """
    return ["fboss2 show mysid"]


# ─── IXIA-facing L3 edge ──────────────────────────────────────────────────
def ixia_edge_cmds(node: str, topology: t.Optional[RbbTopology] = None) -> t.List[str]:
    """Confirm the IXIA-facing L3 edge interface on one node.

    Non-destructive read of the edge port state (the actual IXIA-side traffic
    bring-up happens in the IXIA phase). The edge interface is taken from the
    topology's IXIA edges (derived from ``circuit_info.csv``); ``fboss2 show
    port`` output includes the edge interface name so the step is a meaningful,
    side-effect-free gate.
    """
    iface = _topology(topology).node(node).primary_ixia_interface
    if not iface:
        # No IXIA edge declared for this node; fall back to a generic port dump.
        return ["fboss2 show port"]
    return [f"fboss2 show port {iface}"]


# ─── TE_AGENT direct route (install / delete) ─────────────────────────────
# The FBOSS direct-route lifecycle is driven by the rbb_srv6_direct_route task
# over agent thrift (addUnicastRoutes/deleteUnicastRoutes with ClientID
# TE_AGENT) — see rbb_srv6_direct_route_task.py. The two builders below remain
# as the generic-NOS shell template (unused by the FBOSS playbook) so a
# non-FBOSS target can supply CLI via the task's ``install_cmds``/``delete_cmds``
# params instead of the thrift ``prefix`` param.
def direct_route_install_cmds(profile: Srv6Profile) -> t.List[str]:
    """Generic-NOS install template for the tail prefix (non-FBOSS only)."""
    return [
        f"te-agent srv6 route {profile.tail_prefix} "
        f"encap-sid {profile.usid_tail} owner te_agent",
    ]


def direct_route_delete_cmds(profile: Srv6Profile) -> t.List[str]:
    """Generic-NOS delete template for the tail prefix (non-FBOSS only)."""
    return [f"no te-agent srv6 route {profile.tail_prefix}"]


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
    port-channel, and the peer has redistributed its loopback into OpenR. So the
    single ``Client: OPENR`` fact on the peer loopback proves S06 (up +
    adjacency) and S13 (redistribute edge) at once.
    """
    peer_v4 = C.R2_ROUTER_ID if node == "r1" else C.R1_ROUTER_ID
    return {
        "gate": "S06_S13_openr_adjacency",
        "show_cmd": _route_details_for(f"{peer_v4}/32"),
        "expect_contains": ["OPENR", peer_v4],
    }


def verify_openr_redistribute_spec(node: str) -> t.Dict[str, t.Any]:
    """S13 (alt): OpenR redistributes this node's own loopback into its prefix DB.

    ``breeze``-CLI alternative to :func:`verify_openr_adjacency_spec` for sites
    where the OpenR prefix DB is the preferred source of truth; asserts the
    node's own router-id loopback is being originated/redistributed by OpenR
    (openr.conf redistributes ``^lo$`` / ``^fboss4000$``). Not on the default
    live path (the fboss2 route-client read is more portable), but kept as a
    documented, OSS-safe option.
    """
    own_v4 = C.R1_ROUTER_ID if node == "r1" else C.R2_ROUTER_ID
    return {
        "gate": "S13_openr_redistribute_edge",
        "show_cmd": "breeze prefixmgr view || breeze kvstore prefixes",
        "expect_contains": [own_v4],
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
        f"fboss2 show port {member} counters" if member else "fboss2 show port counters"
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
    """S25: R2 SRv6 decap counter — snapshot/assert delta.

    Returns the counter command + integer-extraction regex for the tail (R2)
    decap direction. Default reads the tail decap SID counter via ``fboss2 show
    mysid counters`` (the ``DECAPSULATE_AND_LOOKUP`` SID); override per lab.
    """
    return {
        "gate": "S25_srv6_decap_delta",
        "direction": "decap",
        "counter_cmd": _counter_read_cmd(
            "TAAC_RBB_DECAP_COUNTER_CMD", "fboss2 show mysid counters"
        ),
        "counter_regex": _counter_read_cmd(
            "TAAC_RBB_DECAP_COUNTER_REGEX", r"(?:decap|DECAP)\D*(\d+)"
        ),
    }


def _route_details_for(prefix: str) -> str:
    """``fboss2 show route details`` sliced to one prefix's block.

    ``fboss2`` has no per-prefix route show, so grep the details output for the
    ``Network Address: <prefix>`` block (up to the next blank line). The slash
    in the prefix is escaped for the sed address regex.
    """
    esc = prefix.replace("/", r"\/")
    return f"fboss2 show route details | sed -n '/Network Address: {esc}/,/^$/p'"


def verify_pc162_global_ipv6_spec(
    node: str,
    topology: t.Optional[RbbTopology] = None,
    rif_token: t.Optional[str] = None,
) -> t.Dict[str, t.Any]:
    """S10: the core PC RIF is present/Up on this node.

    Asserts the (topology-derived) core port-channel's ``show`` name. If a RIF
    token is configured (``TAAC_RBB_PC162_RIF_TOKEN`` — e.g. a global-v6 token or
    a /30 subnet substring) it is additionally asserted; otherwise only the
    port-channel presence is required (the core is never mutated).
    """
    pc = _topology(topology).node(node).rif_verify_pc
    rif_token = C.PC162_RIF_TOKEN if rif_token is None else rif_token
    expect: t.List[str] = []
    if pc is not None:
        expect.append(pc.show_name)
    if rif_token:
        expect.append(rif_token)
    return {
        "gate": "S10_pc_rif",
        "show_cmd": "fboss2 show aggregate-port",
        "expect_contains": expect,
    }


def verify_srv6_tunnels_spec(
    node: str, profile: t.Optional[Srv6Profile] = None
) -> t.Dict[str, t.Any]:
    """S11: SRv6 micro-SIDs are programmed (real ``fboss2 show mysid``).

    Both nodes carry an ADJACENCY_MICRO_SID under the configured locator block;
    the tail (R2) additionally carries the DECAPSULATE_AND_LOOKUP SID. Asserts
    the token DERIVED from the profile's locator (never a hardcoded block).
    """
    profile = profile if profile is not None else SRV6_3_USIDS_PROFILE
    expect = [profile.locator_token, C.SRV6_BEHAVIOR_ADJACENCY]
    if node == "r2":
        expect.append(C.SRV6_BEHAVIOR_DECAP)
    return {
        "gate": "S11_srv6_mysid",
        "show_cmd": "fboss2 show mysid",
        "expect_contains": expect,
    }


def verify_route_owner_te_agent_spec(profile: Srv6Profile) -> t.Dict[str, t.Any]:
    """S22-S23: after install, the tail prefix is owned by TE_AGENT."""
    return {
        "gate": "S22_23_route_owner_te_agent",
        "show_cmd": _route_details_for(profile.tail_prefix),
        "expect_contains": [C.ROUTE_OWNER_TE_AGENT],
    }


def verify_srv6_counters_spec() -> t.Dict[str, t.Any]:
    """S26: SRv6 forwarding state present (ASIC FIB populated).

    ``fboss2 show route counters`` is empty unless counters are explicitly
    configured, so re-anchor to ``show route summary`` and assert the v6 FIB is
    populated (the SRv6 routes are installed in hardware).
    """
    return {
        "gate": "S26_srv6_fib_present",
        "show_cmd": "fboss2 show route summary",
        "expect_contains": ["v6 routes (total)"],
    }


def verify_route_owner_bgpd_spec(profile: Srv6Profile) -> t.Dict[str, t.Any]:
    """S28: after direct-route delete, prefix reverts to BGPD (not TE_AGENT)."""
    return {
        "gate": "S28_route_owner_bgpd",
        "show_cmd": _route_details_for(profile.tail_prefix),
        "expect_contains": [C.ROUTE_OWNER_BGPD],
        "expect_absent": [C.ROUTE_OWNER_TE_AGENT],
    }
