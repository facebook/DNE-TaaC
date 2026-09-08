# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Minimal, in-place BGP helpers for the reversible RBB IXIA edge."""

from __future__ import annotations

import ipaddress
import typing as t

_DEFAULT_TIMERS: t.Dict[str, int] = {
    "hold_time_seconds": 30,
    "keep_alive_seconds": 10,
    "out_delay_seconds": 3,
}


def _strip_len(addr: str) -> str:
    """``192.0.2.1/32`` -> ``192.0.2.1``; preserve a bare address."""
    return addr.split("/", 1)[0]


# In-place edge-eBGP mutation (bgp.json-compatible; no bgpcpp/COOP).
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
    ibgp_peer_addr: t.Optional[str] = None,
) -> t.Dict[str, t.Any]:
    """Turn on v6 AFI for a safely selected iBGP group and set its v6 next-hop.

    An iBGP peer group is one whose ``remote_as_4_byte`` equals the box's
    ``local_as_4_byte``. Supplying ``ibgp_peer_addr`` restricts the mutation to
    that exact peer and its group; the helper fails closed if the group is
    shared, the peer is missing/duplicated, or the existing next hop is unusable.
    When no peer selector is supplied, all iBGP groups are selected for backward
    compatibility. Passing the tail SRv6 **decap SID** as
    ``ibgp_next_hop6`` (with ``next_hop_self`` already true) makes the receiver
    install the edge pool with an underlay-resolvable SID next hop. The explicit
    segment list on the head's TE_AGENT route triggers SRv6 encapsulation.
    """
    local_as = config.get("local_as_4_byte")
    if local_as is None:
        raise ValueError("BGP config has no local_as_4_byte")
    nh6 = _strip_len(ibgp_next_hop6) if ibgp_next_hop6 else None
    if nh6:
        try:
            parsed_nh6 = ipaddress.ip_address(nh6)
        except ValueError as exc:
            raise ValueError(f"invalid iBGP IPv6 next-hop {nh6!r}") from exc
        if parsed_nh6.version != 6 or parsed_nh6.is_unspecified:
            raise ValueError(
                f"iBGP next-hop {nh6!r} must be a usable IPv6 address"
            )
    all_ibgp_groups = [
        pg
        for pg in config.get("peer_groups", [])
        if pg.get("remote_as_4_byte") == local_as and pg.get("name")
    ]
    all_ibgp_group_names = {pg.get("name") for pg in all_ibgp_groups}
    if not all_ibgp_group_names:
        raise ValueError("BGP config has no iBGP peer group to enable for IPv6")
    all_ibgp_peers = [
        peer
        for peer in config.get("peers", [])
        if peer.get("peer_group_name") in all_ibgp_group_names
    ]
    if ibgp_peer_addr:
        try:
            requested_peer = str(
                ipaddress.ip_address(_strip_len(ibgp_peer_addr))
            )
        except ValueError as exc:
            raise ValueError(
                f"invalid requested iBGP peer {ibgp_peer_addr!r}"
            ) from exc
        matching_peers: t.List[t.Dict[str, t.Any]] = []
        for peer in all_ibgp_peers:
            try:
                candidate = str(
                    ipaddress.ip_address(
                        _strip_len(str(peer.get("peer_addr") or ""))
                    )
                )
            except ValueError:
                continue
            if candidate == requested_peer:
                matching_peers.append(peer)
        if len(matching_peers) != 1:
            raise ValueError(
                f"expected exactly one iBGP peer {requested_peer!r}, found "
                f"{len(matching_peers)}"
            )
        selected_group = matching_peers[0].get("peer_group_name")
        group_peers = [
            peer
            for peer in all_ibgp_peers
            if peer.get("peer_group_name") == selected_group
        ]
        if len(group_peers) != 1:
            raise ValueError(
                f"iBGP peer {requested_peer!r} shares peer group "
                f"{selected_group!r}; refusing to enable IPv6 for unrelated peers"
            )
        ibgp_groups = [
            group for group in all_ibgp_groups if group.get("name") == selected_group
        ]
        ibgp_peers = matching_peers
    else:
        ibgp_groups = all_ibgp_groups
        ibgp_peers = all_ibgp_peers
    if not ibgp_peers:
        raise ValueError("BGP config has no iBGP peer to enable for IPv6")
    if nh6 is None:
        unusable_peers: t.List[str] = []
        for peer in ibgp_peers:
            current = _strip_len(str(peer.get("next_hop6") or ""))
            try:
                parsed = ipaddress.ip_address(current)
            except ValueError:
                parsed = None
            if (
                parsed is None
                or parsed.version != 6
                or parsed.is_unspecified
            ):
                unusable_peers.append(str(peer.get("peer_addr") or "<unknown>"))
        if unusable_peers:
            raise ValueError(
                "BGP iBGP peer(s) have no usable IPv6 next_hop6: "
                f"{sorted(unusable_peers)}; supply ibgp_next_hop6"
            )

    # Validate the complete target set before mutating the caller's document.
    for group in ibgp_groups:
        group["disable_ipv6_afi"] = False
    if nh6:
        for peer in ibgp_peers:
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

    Idempotent: a peer group/peer already owned by this RBB group is converged
    to the requested values. A peer-address collision with another group fails
    closed instead of silently reporting that the edge is configured. The peer
    advertises the box's own v6 next-hop to the edge (``next_hop6`` = the DUT
    edge address) and relies on the peer group's ``next_hop_self`` for what it
    re-advertises into iBGP.
    """
    peer4or6 = _strip_len(peer_addr)
    local = _strip_len(local_addr)
    is_v6 = ":" in peer4or6
    # bgpd parses ``next_hop4`` as an IPv4 unconditionally and aborts on an empty
    # string (``folly::IPAddressFormatException: Invalid IPv4 address ''``), even
    # when the peer group has ``disable_ipv4_afi=True``. For a v6 edge peer fall
    # back to the box's own router-id so the field parses; it is never
    # advertised because the v4 AFI is disabled on this group. Fail closed if
    # the existing config has no usable router-id instead of writing an
    # unspecified address that can crash or be rejected by bgpd.
    nh4 = local
    if is_v6:
        try:
            router_id = ipaddress.ip_address(str(config.get("router_id") or ""))
        except ValueError as exc:
            raise ValueError(
                "BGP config needs a valid IPv4 router_id for an IPv6 edge peer"
            ) from exc
        if router_id.version != 4 or router_id.is_unspecified:
            raise ValueError(
                "BGP config needs a usable IPv4 router_id for an IPv6 edge peer"
            )
        nh4 = str(router_id)

    timers = dict(_DEFAULT_TIMERS)
    timers["hold_time_seconds"] = hold_time
    desired_group = {
        "bgp_peer_timers": timers,
        "disable_ipv4_afi": is_v6,
        "disable_ipv6_afi": not is_v6,
        "name": peer_group_name,
        "next_hop_self": True,
        "remote_as_4_byte": remote_as,
        "v4_over_v6_nexthop": False,
    }
    pgs = config.setdefault("peer_groups", [])
    matching_groups = [pg for pg in pgs if pg.get("name") == peer_group_name]
    if len(matching_groups) > 1:
        raise ValueError(f"duplicate BGP peer group {peer_group_name!r}")
    peers = config.setdefault("peers", [])
    other_owned_peers = [
        p.get("peer_addr")
        for p in peers
        if p.get("peer_group_name") == peer_group_name
        and p.get("peer_addr") != peer4or6
    ]
    if other_owned_peers:
        raise ValueError(
            f"BGP peer group {peer_group_name!r} already serves other peer(s) "
            f"{sorted(str(peer) for peer in other_owned_peers)}"
        )
    matching_peers = [p for p in peers if p.get("peer_addr") == peer4or6]
    if len(matching_peers) > 1:
        raise ValueError(f"duplicate BGP peer address {peer4or6!r}")
    if matching_peers and matching_peers[0].get("peer_group_name") not in (
        None,
        peer_group_name,
    ):
        raise ValueError(
            f"BGP peer {peer4or6} already belongs to peer group "
            f"{matching_peers[0].get('peer_group_name')!r}"
        )

    # All collision checks complete before the first in-place mutation. This
    # keeps callers' parsed config unchanged when the helper fails closed.
    if matching_groups:
        matching_groups[0].update(desired_group)
    else:
        pgs.append(desired_group)
    desired_peer = {
        "description": description,
        "local_addr": local,
        "next_hop4": nh4,
        "next_hop6": local if is_v6 else "::",
        "peer_addr": peer4or6,
        "peer_group_name": peer_group_name,
        "peer_id": f"ixia-edge-{peer4or6}",
        "remote_as_4_byte": remote_as,
    }
    if matching_peers:
        matching_peers[0].update(desired_peer)
    else:
        peers.append(desired_peer)
    return config
