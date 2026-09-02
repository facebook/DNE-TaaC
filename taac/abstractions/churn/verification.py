# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""Pure comparison helpers for churn transition and restoration evidence."""

from __future__ import annotations

import typing as t

from .observations import Counters, RouteState


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
