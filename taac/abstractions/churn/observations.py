# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""Immutable observations shared without exposing TAAC runtime objects."""

from __future__ import annotations

import dataclasses
import typing as t


@dataclasses.dataclass(frozen=True)
class Block:
    afi: str
    plane: int
    row: int
    pool_name: str
    peer: str
    prefixes: tuple[str, ...]
    route_peer: str | None = None

    @property
    def rib_peer(self) -> str:
        return self.route_peer or self.peer


@dataclasses.dataclass(frozen=True)
class Counters:
    state: str
    reset_time: object
    uptime: int
    resets: int
    flaps: int
    recv4: int
    recv6: int
    recv_withdrawals: int
    sent4: int
    sent6: int
    sent_withdrawals: int
    peer_asn: int = 0
    recv_update_msgs: int = 0


@dataclasses.dataclass(frozen=True)
class RouteState:
    rib_version: int
    path_selection_pending: bool
    best_peers: tuple[str, ...]
    peer_attributes: t.Mapping[str, t.Mapping[str, object]]


ConvergenceState = tuple[t.Mapping[str, Counters], int, t.Mapping[str, RouteState]]
