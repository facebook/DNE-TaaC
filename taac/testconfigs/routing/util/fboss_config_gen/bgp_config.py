# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Build ``/opt/bgpd/bgp.json`` (+ ``policy.json``) from scratch.

Emits the FBOSS bgpd JSON config for the RBB iBGP loopback session: a single
``C8501-IBGP-LOOPBACK-V4V6`` next-hop-self peer group, one loopback peer to the
far DUT, and the locally originated loopback / tail networks. Shape mirrors the
reference deployment 1:1 so the shipped bgpd accepts it; all *values* come from
the address plan (loopbacks / ASN / originated prefixes), never hard-coded.
"""

from __future__ import annotations

import os
import typing as t

# Peer-group name is a platform-generic FBOSS convention (Cisco 8501 iBGP
# loopback peer group), not a lab identifier.
IBGP_PEER_GROUP: str = "C8501-IBGP-LOOPBACK-V4V6"

# bgpd's net_service static-file ACL path. This is the reference-deployment
# absolute path the shipped bgpd expects, kept as the default so the generated
# config is accepted unchanged; override for other deployment layouts.
NET_STATIC_FILE_ACL: str = os.environ.get(
    "TAAC_RBB_BGP_STATIC_ACL_PATH", "/usr/facebook/thrift_acls/dummy_acl.json"
)

_DEFAULT_TIMERS: t.Dict[str, int] = {
    "hold_time_seconds": 30,
    "keep_alive_seconds": 10,
    "out_delay_seconds": 3,
}


def _strip_len(addr: str) -> str:
    """``9.9.9.9/32`` -> ``9.9.9.9`` ; leave a bare address untouched."""
    return addr.split("/", 1)[0]


def build_bgp_config(
    *,
    local_as: int,
    router_id: str,
    loopback_v4: str,
    loopback_v6: str,
    peer_loopback_v4: str,
    remote_as: t.Optional[int] = None,
    networks4: t.Optional[t.Sequence[str]] = None,
    networks6: t.Optional[t.Sequence[str]] = None,
    peer_group_name: str = IBGP_PEER_GROUP,
    peer_description: str = "iBGP loopback peer",
    hold_time: int = 30,
) -> t.Dict[str, t.Any]:
    """Build the bgpd config dict for one DUT.

    Args:
        local_as: this DUT's BGP AS (iBGP => remote_as defaults to it).
        router_id / loopback_v4 / loopback_v6: this DUT's loopback identity.
        peer_loopback_v4: the far DUT's loopback (the iBGP peer address).
        networks4 / networks6: locally originated prefixes (CIDR strings).
        remote_as: peer AS; defaults to ``local_as`` (iBGP).
    """
    remote_as = local_as if remote_as is None else remote_as
    rid = _strip_len(router_id)
    lo4 = _strip_len(loopback_v4)
    lo6 = _strip_len(loopback_v6)
    peer4 = _strip_len(peer_loopback_v4)

    nets4 = list(networks4) if networks4 else [f"{lo4}/32"]
    nets6 = list(networks6) if networks6 else [f"{lo6}/128"]

    return {
        "bgp_setting_config": {
            "enable_dynamic_policy_evaluation": True,
            "enable_next_hop_tracking": False,
            "enable_update_group": False,
            "include_interface_regexes": [".*"],
        },
        "hold_time": hold_time,
        "listen_addr": "::",
        "listen_port": 179,
        "local_as_4_byte": local_as,
        "net_service_config": {
            "net_auth_checker_kill_switch_file": "",
            "net_service_identity": "BgpdService",
            "net_static_file_acl": NET_STATIC_FILE_ACL,
            "thrift_num_cpu_worker_threads": 1,
            "thrift_num_io_worker_threads": 1,
        },
        "networks4": [{"prefix": p} for p in nets4],
        "networks6": [{"prefix": p} for p in nets6],
        "peer_groups": [
            {
                "bgp_peer_timers": dict(_DEFAULT_TIMERS),
                "disable_ipv4_afi": False,
                "disable_ipv6_afi": False,
                "name": peer_group_name,
                "next_hop_self": True,
                "remote_as_4_byte": remote_as,
                "v4_over_v6_nexthop": False,
            }
        ],
        "peers": [
            {
                "description": peer_description,
                "local_addr": lo4,
                "next_hop4": lo4,
                "next_hop6": lo6,
                "peer_addr": peer4,
                "peer_group_name": peer_group_name,
                "peer_id": "loopback-ibgp-peer",
                "remote_as_4_byte": remote_as,
            }
        ],
        "router_id": rid,
    }


def build_policy_config() -> t.Dict[str, t.Any]:
    """Empty bgpd policy doc (the reference deployment ships no policy rules)."""
    return {}


# ─── In-place edge-eBGP mutation (bgp.json-compatible; no bgpcpp/COOP) ─────────
# These pure helpers edit an already-parsed ``/opt/bgpd/bgp.json`` dict in place
# so the DUT's existing config (loopbacks, iBGP session, originated networks) is
# preserved verbatim — only the IXIA-facing eBGP edge is added and, on an
# iBGP-only tail that ships ``disable_ipv6_afi``, the v6 AFI is switched on so the
# eBGP-learned v6 pool can propagate over the core iBGP. This is the OSS-safe
# replacement for the shipped ``configure_ixia_interfaces`` (which patches the
# COOP ``bgpcpp`` config and is incompatible with a ``/opt/bgpd/bgp.json`` box).

EDGE_EBGP_PEER_GROUP: str = "RBB-IXIA-EDGE-EBGP"


def enable_ipv6_afi_on_ibgp(
    config: t.Dict[str, t.Any],
    *,
    ibgp_next_hop6: t.Optional[str] = None,
) -> t.Dict[str, t.Any]:
    """Turn on the v6 AFI for the iBGP peer group(s) and set the advertised v6
    next-hop.

    An iBGP peer group is one whose ``remote_as_4_byte`` equals the box's
    ``local_as_4_byte``. For each, clear ``disable_ipv6_afi`` so v6 routes are
    exchanged, and — when ``ibgp_next_hop6`` is given — set every iBGP peer's
    ``next_hop6`` to it. Passing the tail SRv6 **decap SID** as
    ``ibgp_next_hop6`` (with ``next_hop_self`` already true) makes the receiver
    install the edge pool with a SID next-hop, i.e. SRv6-encapsulate toward the
    tail — which is exactly the head→tail steering the proposal wants.
    """
    local_as = config.get("local_as_4_byte")
    nh6 = _strip_len(ibgp_next_hop6) if ibgp_next_hop6 else None
    ibgp_group_names: t.Set[str] = set()
    for pg in config.get("peer_groups", []):
        if pg.get("remote_as_4_byte") == local_as:
            pg["disable_ipv6_afi"] = False
            ibgp_group_names.add(pg.get("name"))
    if nh6:
        for peer in config.get("peers", []):
            if peer.get("peer_group_name") in ibgp_group_names:
                peer["next_hop6"] = nh6
    return config


def add_edge_ebgp_peer(
    config: t.Dict[str, t.Any],
    *,
    peer_addr: str,
    remote_as: int,
    local_addr: str,
    peer_group_name: str = EDGE_EBGP_PEER_GROUP,
    description: str = "IXIA edge eBGP peer",
    hold_time: int = 30,
) -> t.Dict[str, t.Any]:
    """Add an eBGP peer group + peer toward one IXIA emulated router, in place.

    Idempotent: a peer group/peer with the same name/``peer_addr`` is left
    untouched (re-apply is a no-op). The peer advertises the box's own v6
    next-hop to the edge (``next_hop6`` = the DUT edge address) and relies on the
    peer group's ``next_hop_self`` for what it re-advertises into iBGP.
    """
    peer4or6 = _strip_len(peer_addr)
    local = _strip_len(local_addr)
    is_v6 = ":" in peer4or6
    # bgpd parses ``next_hop4`` as an IPv4 unconditionally and aborts on an empty
    # string (``folly::IPAddressFormatException: Invalid IPv4 address ''``), even
    # when the peer group has ``disable_ipv4_afi=True``. For a v6 edge peer fall
    # back to the box's own router-id (always a valid IPv4) so the field parses;
    # it is never advertised because the v4 AFI is disabled on this group.
    nh4 = local if not is_v6 else (config.get("router_id") or "0.0.0.0")

    pgs = config.setdefault("peer_groups", [])
    if not any(pg.get("name") == peer_group_name for pg in pgs):
        pgs.append(
            {
                "bgp_peer_timers": dict(_DEFAULT_TIMERS),
                "disable_ipv4_afi": is_v6,
                "disable_ipv6_afi": not is_v6,
                "name": peer_group_name,
                "next_hop_self": True,
                "remote_as_4_byte": remote_as,
                "v4_over_v6_nexthop": False,
            }
        )

    peers = config.setdefault("peers", [])
    if not any(p.get("peer_addr") == peer4or6 for p in peers):
        peers.append(
            {
                "description": description,
                "local_addr": local,
                "next_hop4": nh4,
                "next_hop6": local if is_v6 else "::",
                "peer_addr": peer4or6,
                "peer_group_name": peer_group_name,
                "peer_id": f"ixia-edge-{peer4or6}",
                "remote_as_4_byte": remote_as,
            }
        )
    return config
