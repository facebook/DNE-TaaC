# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""IXIA-owned operations used by reusable route churn."""

from __future__ import annotations

import typing as t


class IxiaRouteChurnOperations:
    def __init__(self, ixia: t.Any) -> None:
        self._ixia = ixia

    def matching_prefix_pools(self, regex: str) -> list[t.Any]:
        return list(self._ixia.get_prefix_pools_by_regexes(prefix_pool_regex=regex))

    def bgp_peer(self, prefix_pool: t.Any) -> t.Any:
        return self._ixia.map_prefix_pool_to_bgp_peer(prefix_pool)

    def network_group(self, prefix_pool: t.Any) -> t.Any:
        return self._ixia.map_prefix_pool_to_network_group(prefix_pool)

    def apply_changes(self) -> None:
        self._ixia.apply_changes()
