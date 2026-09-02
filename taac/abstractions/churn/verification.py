# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""Pure comparison helpers for churn transition and restoration evidence."""

from __future__ import annotations

import typing as t

from .observations import Block, Counters, RouteState


def counter_snapshot(counters: Counters) -> t.Mapping[str, object]:
    return {
        "state": counters.state,
        "uptime": counters.uptime,
        "resets": counters.resets,
        "flaps": counters.flaps,
        "recv4": counters.recv4,
        "recv6": counters.recv6,
        "recv_update_msgs": counters.recv_update_msgs,
        "recv_withdrawals": counters.recv_withdrawals,
        "sent4": counters.sent4,
        "sent6": counters.sent6,
        "sent_withdrawals": counters.sent_withdrawals,
    }


def counter_delta(before: Counters, after: Counters) -> t.Mapping[str, object]:
    return {
        "state": after.state,
        "uptime": after.uptime - before.uptime,
        "resets": after.resets - before.resets,
        "flaps": after.flaps - before.flaps,
        "recv4": after.recv4 - before.recv4,
        "recv6": after.recv6 - before.recv6,
        "recv_update_msgs": after.recv_update_msgs - before.recv_update_msgs,
        "recv_withdrawals": after.recv_withdrawals - before.recv_withdrawals,
        "sent4": after.sent4 - before.sent4,
        "sent6": after.sent6 - before.sent6,
        "sent_withdrawals": after.sent_withdrawals - before.sent_withdrawals,
    }


def routes_match_baseline(
    baseline: t.Mapping[str, RouteState], current: t.Mapping[str, RouteState]
) -> bool:
    for prefix, before in baseline.items():
        after = current.get(prefix)
        if after is None:
            return False
        if after.path_selection_pending or after.best_peers != before.best_peers:
            return False
        if after.peer_attributes != before.peer_attributes:
            return False
    return True


def missing_session_peers(
    expected: t.AbstractSet[str], sessions: t.Mapping[str, Counters]
) -> tuple[str, ...]:
    return tuple(sorted(expected - sessions.keys()))


def session_baseline_violation(
    old: t.Mapping[str, Counters], new: t.Mapping[str, Counters]
) -> str | None:
    for peer, before in old.items():
        after = new[peer]
        if (
            after.resets != before.resets
            or after.flaps != before.flaps
            or after.uptime < before.uptime
            or after.recv_withdrawals != before.recv_withdrawals
            or after.sent_withdrawals != before.sent_withdrawals
        ):
            return peer
    return None


def quiet_update_violation(
    old: t.Mapping[str, Counters], new: t.Mapping[str, Counters]
) -> str | None:
    for peer, before in old.items():
        after = new[peer]
        old_updates = (before.recv4, before.recv6, before.sent4, before.sent6)
        new_updates = (after.recv4, after.recv6, after.sent4, after.sent6)
        if (
            new_updates != old_updates
            or after.recv_update_msgs != before.recv_update_msgs
        ):
            return peer
    return None


def transition_best_peer(
    *,
    prefix: str,
    before: RouteState,
    after: RouteState,
    expected_peers: t.AbstractSet[str],
    should_advance: bool,
) -> str:
    if after.path_selection_pending:
        raise ValueError(f"{prefix}: path selection is pending")
    if should_advance and after.rib_version <= before.rib_version:
        raise ValueError(f"{prefix}: per-prefix RIB version did not advance")
    if not after.best_peers:
        raise ValueError(f"{prefix}: no best path selected")
    unexpected_best = set(after.best_peers) - expected_peers
    if unexpected_best:
        raise ValueError(
            f"{prefix}: unexpected best-path peers {sorted(unexpected_best)}"
        )
    if len(after.best_peers) != 1:
        raise ValueError(
            f"{prefix}: expected exactly one deterministic best path, "
            f"got {list(after.best_peers)}"
        )
    return after.best_peers[0]


def verify_preferred_path(
    *,
    prefix: str,
    best_peer: str,
    plane1_peer: str,
    reference_peers: t.AbstractSet[str],
    family: str,
    preferred: bool | None,
) -> None:
    if preferred is True and best_peer != plane1_peer:
        raise ValueError(f"{prefix}: plane 1 did not become best for {family}")
    if preferred is False and best_peer == plane1_peer:
        raise ValueError(f"{prefix}: plane 1 remained best for {family}")
    if preferred is False and best_peer not in reference_peers:
        raise ValueError(f"{prefix}: no reference plane became best")


def verify_route_attributes(
    *,
    blocks: t.Sequence[Block],
    routes: t.Mapping[str, RouteState],
    family: str,
    expected: object,
    planes: t.AbstractSet[int],
) -> None:
    for block in blocks:
        if block.plane not in planes:
            continue
        for prefix in block.prefixes:
            state = routes[prefix]
            if state.path_selection_pending:
                raise ValueError(f"{prefix}: path selection is pending")
            actual = state.peer_attributes[block.rib_peer][family]
            if actual != expected:
                raise ValueError(
                    f"{prefix}: {block.rib_peer} {family}={actual!r}, "
                    f"expected {expected!r}"
                )
