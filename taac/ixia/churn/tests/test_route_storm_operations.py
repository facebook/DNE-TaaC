# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

import dataclasses
import typing as t
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from taac.constants import TestCaseFailure
from taac.ixia.churn.route_operations import (
    IxiaRouteStormOperations,
)


@dataclasses.dataclass(frozen=True)
class _Pool:
    name: str
    route: t.Any
    route_count: int
    selected_indices: tuple[int, ...]
    device_group: t.Any = None
    network_group: t.Any = None


class IxiaRouteStormOperationsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.ixia = MagicMock()
        self.operations = IxiaRouteStormOperations(self.ixia)

    def test_matching_prefix_pools_escapes_names(self) -> None:
        pools = (MagicMock(), MagicMock())
        self.ixia.get_prefix_pools_by_regexes.return_value = pools

        result = self.operations.matching_prefix_pools(("pool.v4", "pool[v6]"))

        self.assertEqual(pools, result)
        self.ixia.get_prefix_pools_by_regexes.assert_called_once_with(
            prefix_pool_regex=r"^(?:pool\.v4|pool\[v6\])$"
        )

    def test_mapped_structure_targets_require_both_targets(self) -> None:
        pool = MagicMock(Name="pool")
        self.ixia.map_prefix_pool_to_device_group.return_value = object()
        self.ixia.map_prefix_pool_to_network_group.return_value = None

        with self.assertRaisesRegex(TestCaseFailure, "network group"):
            self.operations.mapped_structure_targets(pool)

    def test_structure_start_arms_children_before_parent(self) -> None:
        calls: list[str] = []
        device_group = SimpleNamespace(
            href="device",
            Start=lambda: calls.append("device"),
            Stop=MagicMock(),
        )
        network_group = SimpleNamespace(
            href="network",
            Start=lambda: calls.append("network"),
            Stop=MagicMock(),
        )
        pool = _Pool(
            name="pool",
            route=MagicMock(),
            route_count=0,
            selected_indices=(),
            device_group=device_group,
            network_group=network_group,
        )

        self.operations.set_structure_targets_running((pool,), True)

        self.assertEqual(["network", "device"], calls)

    def test_route_row_failure_rolls_back_completed_pools(self) -> None:
        first_route = MagicMock()
        second_route = MagicMock()
        second_route.Stop.side_effect = RuntimeError("stop failed")
        pools = (
            _Pool(
                name="first",
                route=first_route,
                route_count=3,
                selected_indices=(0, 2),
            ),
            _Pool(
                name="second",
                route=second_route,
                route_count=2,
                selected_indices=(1,),
            ),
        )

        with self.assertRaisesRegex(RuntimeError, "stop failed"):
            self.operations.set_route_rows_running(
                pools,
                False,
                selected_only=True,
            )

        first_route.Stop.assert_called_once_with(SessionIndices=[1, 3])
        first_route.Start.assert_called_once_with(SessionIndices=[1, 3])
        self.ixia.apply_changes.assert_called_once_with()

    def test_bgp_statistics_requires_complete_scope(self) -> None:
        with self.assertRaisesRegex(ValueError, "provided together"):
            self.operations.bgp_update_statistics(hostname="dut")
