# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""IXIA-owned operations used by reusable BGP session churn."""

from __future__ import annotations

import typing as t
from contextlib import nullcontext


class IxiaSessionChurnOperations:
    def __init__(self, ixia: t.Any) -> None:
        self._ixia = ixia

    def matching_bgp_peers(self, regex: str) -> list[t.Any]:
        return list(self._ixia.find_bgp_peers(regex))

    def set_peer_range(
        self,
        *,
        start: bool,
        regex: str,
        first: int,
        last: int,
    ) -> None:
        self._ixia.start_bgp_peers(
            start=start,
            regex=regex,
            session_start_idx=first,
            session_end_idx=last,
        )

    def request_deadline(
        self,
        timeout_seconds: float,
        phase: str,
    ) -> t.ContextManager[None]:
        deadline = getattr(type(self._ixia), "request_deadline", None)
        if deadline is None:
            return nullcontext()
        return deadline(self._ixia, timeout_seconds, phase)

    @property
    def supports_request_deadline(self) -> bool:
        return getattr(type(self._ixia), "request_deadline", None) is not None
