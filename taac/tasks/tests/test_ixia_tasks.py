# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe

import asyncio
import threading
import typing as t
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from ixnetwork_restpy.errors import BadRequestError
from later.unittest import TestCase
from taac.tasks.ixia_tasks import (
    _resolve_prefix_slots,
    _retry_ixia_busy_operation,
    IxiaEnableDisableBgpPrefixes,
)

_PREFIX_COUNT = 50000
_PEERS = 2


def _pool(number_of_addresses: int) -> SimpleNamespace:
    """Minimal stand-in for an IxNetwork prefix-pool node (only NumberOfAddresses
    is read by the helper)."""
    return SimpleNamespace(NumberOfAddresses=number_of_addresses)


class ResolvePrefixSlotsTest(unittest.TestCase):
    """The enable/disable + attribute tasks select physical route rows by index."""

    def test_compact_full_range_enables_all(self) -> None:
        total = _PEERS
        slots, end_idx = _resolve_prefix_slots(
            _pool(_PREFIX_COUNT), 1, total, 0, _PREFIX_COUNT
        )
        self.assertEqual(end_idx, _PREFIX_COUNT)
        self.assertEqual(len(slots), total)
        self.assertEqual([i for i, _ in slots], list(range(total)))

    def test_flat_full_range_matches_compact(self) -> None:
        # flat: NetworkGroup.Multiplier=prefix_count, NumberOfAddresses=1 -- must
        # behave identically to compact (no regression for existing flat callers).
        total = _PEERS * _PREFIX_COUNT
        slots, end_idx = _resolve_prefix_slots(
            _pool(1), _PREFIX_COUNT, total, 0, _PREFIX_COUNT
        )
        self.assertEqual(end_idx, _PREFIX_COUNT)
        self.assertEqual(len(slots), total)

    def test_none_end_index_defaults_to_full_per_peer(self) -> None:
        total = _PEERS
        slots, end_idx = _resolve_prefix_slots(_pool(_PREFIX_COUNT), 1, total, 0, None)
        self.assertEqual(end_idx, _PREFIX_COUNT)
        self.assertEqual(len(slots), total)

    def test_zero_end_index_is_not_treated_as_none(self) -> None:
        slots, end_idx = _resolve_prefix_slots(
            _pool(1), _PREFIX_COUNT, _PEERS * _PREFIX_COUNT, 0, 0
        )

        self.assertEqual(0, end_idx)
        self.assertEqual([], slots)

    def test_flat_sub_range_applies_per_peer(self) -> None:
        total = _PEERS * _PREFIX_COUNT
        slots, end_idx = _resolve_prefix_slots(_pool(1), _PREFIX_COUNT, total, 0, 100)
        self.assertEqual(end_idx, 100)
        self.assertEqual(len(slots), _PEERS * 100)
        self.assertTrue(all(mod < 100 for _, mod in slots))
        selected = {i for i, _ in slots}
        self.assertIn(0, selected)
        self.assertIn(99, selected)
        self.assertIn(_PREFIX_COUNT, selected)  # peer 2's first prefix
        self.assertIn(_PREFIX_COUNT + 99, selected)
        self.assertNotIn(100, selected)

    def test_compact_partial_range_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot select a partial"):
            _resolve_prefix_slots(_pool(_PREFIX_COUNT), 1, _PEERS, 0, 100)

    def test_flat_end_index_clamped_to_prefixes_per_peer(self) -> None:
        total = _PEERS * _PREFIX_COUNT
        _, end_idx = _resolve_prefix_slots(
            _pool(1), _PREFIX_COUNT, total, 0, 10 * _PREFIX_COUNT
        )
        self.assertEqual(end_idx, _PREFIX_COUNT)

    def test_within_peer_index_exposed_for_cycling(self) -> None:
        # Origin cycling relies on the within-peer index, not the global index.
        total = _PEERS * _PREFIX_COUNT
        slots, _ = _resolve_prefix_slots(
            _pool(1), _PREFIX_COUNT, total, 0, _PREFIX_COUNT
        )
        by_index = dict(slots)
        self.assertEqual(by_index[0], 0)
        self.assertEqual(by_index[_PREFIX_COUNT], 0)  # peer 2 restarts at 0
        self.assertEqual(by_index[_PREFIX_COUNT + 5], 5)

    def test_nonpositive_prefix_geometry_is_rejected(self) -> None:
        for number_of_addresses, multiplier in ((0, 1), (1, 0), (-1, 1)):
            with self.subTest(
                number_of_addresses=number_of_addresses,
                multiplier=multiplier,
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "prefixes_per_peer must be positive",
                ):
                    _resolve_prefix_slots(
                        _pool(number_of_addresses),
                        multiplier,
                        _PEERS,
                        0,
                        None,
                    )


class FakeIpv4PrefixPool:
    def __init__(
        self,
        name: str,
        count: int = 20,
        number_of_addresses: int = 1,
        *,
        compact_peer_count: int | None = None,
    ) -> None:
        self.Name = name
        self.Count = compact_peer_count or count
        self._number_of_addresses = number_of_addresses
        self._compact_peer_count = compact_peer_count
        self.refresh = MagicMock()
        active_value_count = compact_peer_count or count
        active = SimpleNamespace(Values=[False] * active_value_count)
        active.ValueList = MagicMock(
            side_effect=lambda values: setattr(active, "Values", list(values))
        )
        self.route_property = SimpleNamespace(
            Count=active_value_count,
            Active=active,
            refresh=MagicMock(),
            Start=MagicMock(),
            Stop=MagicMock(),
        )
        self.BgpIPRouteProperty = SimpleNamespace(
            find=MagicMock(return_value=[self.route_property])
        )
        self.BgpV6IPRouteProperty = SimpleNamespace(
            find=MagicMock(return_value=[self.route_property])
        )

    @property
    def NumberOfAddresses(self) -> int:
        return self._number_of_addresses

    @NumberOfAddresses.setter
    def NumberOfAddresses(self, value: int) -> None:
        self._number_of_addresses = value
        if self._compact_peer_count is not None and hasattr(self, "route_property"):
            self.route_property.Active.Values = [True] * self._compact_peer_count


class IxiaEnableDisableBgpPrefixesTest(TestCase):
    @staticmethod
    async def _wait_for(event: threading.Event) -> None:
        while not event.is_set():
            await asyncio.sleep(0)

    def _task(self, pools, *, network_group_multiplier: int = 20):
        ixia = SimpleNamespace(
            get_prefix_pools_by_regexes=MagicMock(return_value=pools),
            map_prefix_pool_to_network_group=MagicMock(
                return_value=SimpleNamespace(Multiplier=network_group_multiplier)
            ),
            apply_changes=MagicMock(),
            start_protocols=MagicMock(),
            stop_protocols=MagicMock(),
        )
        return IxiaEnableDisableBgpPrefixes(ixia=t.cast(t.Any, ixia)), ixia

    def test_exact_one_pool_toggles_only_first_twenty_prefixes(self) -> None:
        pool = FakeIpv4PrefixPool("RUNTIME_20")
        task, ixia = self._task([pool])

        with patch(
            "neteng.test_infra.dne.taac.tasks.ixia_tasks.Ipv4PrefixPools",
            FakeIpv4PrefixPool,
        ):
            task.configure_bgp_prefixes_active_state(
                True,
                "RUNTIME_20$",
                prefix_start_index=0,
                prefix_end_index=20,
                expected_prefix_pool_count=1,
            )

        pool.route_property.Active.ValueList.assert_called_once_with([True] * 20)
        self.assertEqual([True] * 20, pool.route_property.Active.Values)
        self.assertEqual(2, ixia.get_prefix_pools_by_regexes.call_count)
        ixia.apply_changes.assert_called_once_with()

    def test_active_values_readback_mismatch_fails_closed(self) -> None:
        cached_pool = FakeIpv4PrefixPool("RUNTIME_20")
        fresh_pool = FakeIpv4PrefixPool("RUNTIME_20")
        task, ixia = self._task([])
        lookup_count = 0

        def lookup(*, prefix_pool_regex):
            nonlocal lookup_count
            lookup_count += 1
            self.assertEqual("RUNTIME_20$", prefix_pool_regex)
            return [cached_pool] if lookup_count % 4 == 1 else [fresh_pool]

        ixia.get_prefix_pools_by_regexes.side_effect = lookup

        with (
            patch(
                "neteng.test_infra.dne.taac.tasks.ixia_tasks.Ipv4PrefixPools",
                FakeIpv4PrefixPool,
            ),
            self.assertRaisesRegex(ValueError, "Active.Values readback mismatch"),
        ):
            task.configure_bgp_prefixes_active_state(
                True,
                "RUNTIME_20$",
                prefix_start_index=0,
                prefix_end_index=20,
                expected_prefix_pool_count=1,
            )

        cached_pool.route_property.Active.ValueList.assert_called_once_with([True] * 20)
        self.assertEqual(
            [False] * 20,
            fresh_pool.route_property.Active.Values,
        )
        fresh_pool.route_property.Active.ValueList.assert_called_once_with([False] * 20)
        self.assertEqual(4, ixia.get_prefix_pools_by_regexes.call_count)
        self.assertEqual(2, ixia.apply_changes.call_count)

    def test_active_values_accepts_restpy_string_booleans(self) -> None:
        pool = FakeIpv4PrefixPool("RUNTIME_20")
        pool.route_property.Active.Values = [" FALSE "] * 20
        task, ixia = self._task([pool])

        with patch(
            "neteng.test_infra.dne.taac.tasks.ixia_tasks.Ipv4PrefixPools",
            FakeIpv4PrefixPool,
        ):
            task.configure_bgp_prefixes_active_state(
                True,
                "RUNTIME_20$",
                prefix_start_index=0,
                prefix_end_index=20,
                expected_prefix_pool_count=1,
            )

        self.assertEqual([True] * 20, pool.route_property.Active.Values)
        ixia.apply_changes.assert_called_once_with()

    def test_setter_error_forces_safe_withdrawal(self) -> None:
        pool = FakeIpv4PrefixPool("RUNTIME_20")
        task, ixia = self._task([pool])
        setter_calls = 0

        def setter(values) -> None:
            nonlocal setter_calls
            setter_calls += 1
            if setter_calls == 1:
                raise RuntimeError("setter failed")
            pool.route_property.Active.Values = list(values)

        pool.route_property.Active.ValueList.side_effect = setter

        with (
            patch(
                "neteng.test_infra.dne.taac.tasks.ixia_tasks.Ipv4PrefixPools",
                FakeIpv4PrefixPool,
            ),
            self.assertRaisesRegex(RuntimeError, "setter failed"),
        ):
            task.configure_bgp_prefixes_active_state(
                True,
                "RUNTIME_20$",
                prefix_start_index=0,
                prefix_end_index=20,
                expected_prefix_pool_count=1,
            )

        self.assertEqual(2, setter_calls)
        self.assertEqual([False] * 20, pool.route_property.Active.Values)
        ixia.apply_changes.assert_called_once_with()

    def test_apply_error_forces_safe_withdrawal(self) -> None:
        pool = FakeIpv4PrefixPool("RUNTIME_20")
        task, ixia = self._task([pool])
        ixia.apply_changes.side_effect = [
            RuntimeError("apply failed"),
            None,
        ]

        with (
            patch(
                "neteng.test_infra.dne.taac.tasks.ixia_tasks.Ipv4PrefixPools",
                FakeIpv4PrefixPool,
            ),
            self.assertRaisesRegex(RuntimeError, "apply failed"),
        ):
            task.configure_bgp_prefixes_active_state(
                True,
                "RUNTIME_20$",
                prefix_start_index=0,
                prefix_end_index=20,
                expected_prefix_pool_count=1,
            )

        self.assertEqual([False] * 20, pool.route_property.Active.Values)
        self.assertEqual(2, ixia.apply_changes.call_count)

    def test_busy_operation_retries_twice_then_succeeds(self) -> None:
        task, _ = self._task([])
        busy = BadRequestError(
            '"getValues" exec not allowed currently since an operation '
            "(Collecting Diagnostics) is in progress.",
            400,
        )
        task._build_prefix_mutation_plan = MagicMock(
            side_effect=[busy, busy, ([], {}, {}, {})]
        )
        task._apply_prefix_mutation_plan = MagicMock()

        with (
            patch(
                "neteng.test_infra.dne.taac.tasks.ixia_tasks.time.monotonic",
                return_value=0.0,
            ),
            patch("neteng.test_infra.dne.taac.tasks.ixia_tasks.time.sleep") as sleep,
        ):
            task.configure_bgp_prefixes_active_state(False, "runtime")

        self.assertEqual(3, task._build_prefix_mutation_plan.call_count)
        self.assertEqual([30.0, 30.0], [call.args[0] for call in sleep.call_args_list])
        task._apply_prefix_mutation_plan.assert_called_once()

    def test_non_busy_bad_request_is_not_retried(self) -> None:
        task, _ = self._task([])
        error = BadRequestError("invalid prefix configuration", 400)
        task._build_prefix_mutation_plan = MagicMock(side_effect=error)

        with (
            patch(
                "neteng.test_infra.dne.taac.tasks.ixia_tasks.time.monotonic",
                return_value=0.0,
            ),
            patch("neteng.test_infra.dne.taac.tasks.ixia_tasks.time.sleep") as sleep,
            self.assertRaises(BadRequestError),
        ):
            task.configure_bgp_prefixes_active_state(False, "runtime")

        task._build_prefix_mutation_plan.assert_called_once()
        sleep.assert_not_called()

    def test_busy_operation_retry_exhaustion_reraises(self) -> None:
        task, _ = self._task([])
        busy = BadRequestError(
            '"getValues" exec not allowed currently since an operation '
            "(Collecting Diagnostics) is in progress.",
            400,
        )
        task._build_prefix_mutation_plan = MagicMock(side_effect=busy)

        with (
            patch(
                "neteng.test_infra.dne.taac.tasks.ixia_tasks."
                "_IXIA_BUSY_OPERATION_RETRY_TIMEOUT_SECONDS",
                60.0,
            ),
            patch(
                "neteng.test_infra.dne.taac.tasks.ixia_tasks.time.monotonic",
                side_effect=[0.0, 0.0, 30.0, 60.0],
            ),
            patch("neteng.test_infra.dne.taac.tasks.ixia_tasks.time.sleep") as sleep,
            self.assertRaises(BadRequestError),
        ):
            task.configure_bgp_prefixes_active_state(False, "runtime")

        self.assertEqual(3, task._build_prefix_mutation_plan.call_count)
        self.assertEqual([30.0, 30.0], [call.args[0] for call in sleep.call_args_list])

    def test_nested_busy_operations_share_one_retry_deadline(self) -> None:
        busy = BadRequestError(
            '"getValues" exec not allowed currently since an operation '
            "(Collecting Diagnostics) is in progress.",
            400,
        )
        clock = 0.0

        def monotonic() -> float:
            return clock

        def advance(delay: float) -> None:
            nonlocal clock
            clock += delay

        class NestedOperations:
            def __init__(self) -> None:
                self.logger = MagicMock()
                self.first_attempts = 0

            @_retry_ixia_busy_operation
            def first(self) -> None:
                self.first_attempts += 1
                if self.first_attempts == 1:
                    raise busy

            @_retry_ixia_busy_operation
            def second(self) -> None:
                raise busy

            @_retry_ixia_busy_operation
            def run(self) -> None:
                self.first()
                self.second()

        operations = NestedOperations()
        with (
            patch(
                "neteng.test_infra.dne.taac.tasks.ixia_tasks."
                "_IXIA_BUSY_OPERATION_RETRY_TIMEOUT_SECONDS",
                60.0,
            ),
            patch(
                "neteng.test_infra.dne.taac.tasks.ixia_tasks.time.monotonic",
                side_effect=monotonic,
            ),
            patch(
                "neteng.test_infra.dne.taac.tasks.ixia_tasks.time.sleep",
                side_effect=advance,
            ) as sleep,
            self.assertRaises(BadRequestError),
        ):
            operations.run()

        self.assertEqual(60.0, clock)
        self.assertEqual([30.0, 30.0], [call.args[0] for call in sleep.call_args_list])
        self.assertFalse(hasattr(operations, "_ixia_busy_operation_retry_deadline"))

    def test_expected_count_zero_matches_fails_before_mutation(self) -> None:
        task, ixia = self._task([])

        with self.assertRaisesRegex(ValueError, "No IXIA prefix pools matched"):
            task.configure_bgp_prefixes_active_state(
                True,
                "missing",
                prefix_end_index=20,
                expected_prefix_pool_count=1,
            )

        ixia.apply_changes.assert_not_called()

    def test_legacy_zero_matches_preserves_noop_apply_behavior(self) -> None:
        task, ixia = self._task([])

        task.configure_bgp_prefixes_active_state(
            True,
            "optional",
            prefix_end_index=20,
        )

        ixia.apply_changes.assert_called_once_with()

    def test_multiple_matches_fail_before_mutation(self) -> None:
        pools = [SimpleNamespace(Name="one"), SimpleNamespace(Name="two")]
        task, ixia = self._task(pools)

        with self.assertRaisesRegex(ValueError, "matched 2 pools, expected 1"):
            task.configure_bgp_prefixes_active_state(
                True,
                "runtime",
                prefix_end_index=20,
                expected_prefix_pool_count=1,
            )

        ixia.apply_changes.assert_not_called()

    def test_expected_pool_name_drift_fails_before_mutation(self) -> None:
        pool = FakeIpv4PrefixPool("WRONG_POOL")
        task, ixia = self._task([pool])

        with self.assertRaisesRegex(ValueError, "prefix pool match mismatch"):
            task.configure_bgp_prefixes_active_state(
                True,
                "^PREFIX_POOL_IPV4_EBGP$",
                prefix_start_index=0,
                prefix_end_index=20,
                expected_prefix_pool_names=("PREFIX_POOL_IPV4_EBGP",),
                strict_range=True,
                verify_readback=True,
            )

        ixia.apply_changes.assert_not_called()

    def test_strict_flat_slice_returns_verified_evidence(self) -> None:
        pool = FakeIpv4PrefixPool("PREFIX_POOL_IPV4_EBGP", count=1700)
        task, ixia = self._task([pool], network_group_multiplier=850)

        with patch(
            "neteng.test_infra.dne.taac.tasks.ixia_tasks.Ipv4PrefixPools",
            FakeIpv4PrefixPool,
        ):
            evidence = task.configure_bgp_prefixes_active_state(
                True,
                "^PREFIX_POOL_IPV4_EBGP$",
                prefix_start_index=750,
                prefix_end_index=850,
                expected_prefix_pool_names=("PREFIX_POOL_IPV4_EBGP",),
                strict_range=True,
                verify_readback=True,
            )

        self.assertFalse(pool.route_property.Active.Values[749])
        self.assertTrue(all(pool.route_property.Active.Values[750:850]))
        self.assertTrue(all(pool.route_property.Active.Values[1600:1700]))
        self.assertEqual(200, evidence["pools"][0]["selected_row_count"])
        self.assertTrue(evidence["pools"][0]["readback_verified"])
        ixia.apply_changes.assert_called_once_with()

    def test_strict_flat_range_rejects_overrun_and_empty_selection(self) -> None:
        pool = FakeIpv4PrefixPool("PREFIX_POOL_IPV4_EBGP", count=20)
        task, ixia = self._task([pool], network_group_multiplier=20)

        with (
            patch(
                "neteng.test_infra.dne.taac.tasks.ixia_tasks.Ipv4PrefixPools",
                FakeIpv4PrefixPool,
            ),
            self.assertRaisesRegex(ValueError, "exceeds 20 prefixes per peer"),
        ):
            task.configure_bgp_prefixes_active_state(
                True,
                "^PREFIX_POOL_IPV4_EBGP$",
                20,
                21,
                expected_prefix_pool_names=("PREFIX_POOL_IPV4_EBGP",),
                strict_range=True,
                verify_readback=True,
            )
        with (
            patch(
                "neteng.test_infra.dne.taac.tasks.ixia_tasks.Ipv4PrefixPools",
                FakeIpv4PrefixPool,
            ),
            self.assertRaisesRegex(ValueError, "selected no IXIA rows"),
        ):
            task.configure_bgp_prefixes_active_state(
                True,
                "^PREFIX_POOL_IPV4_EBGP$",
                20,
                None,
                expected_prefix_pool_names=("PREFIX_POOL_IPV4_EBGP",),
                strict_range=True,
                verify_readback=True,
            )

        ixia.apply_changes.assert_not_called()

    def test_strict_compact_slice_resizes_between_logical_capacities(self) -> None:
        pool = FakeIpv4PrefixPool(
            "PREFIX_POOL_IPV4_EBGP",
            number_of_addresses=850,
            compact_peer_count=2,
        )
        pool.route_property.Active.Values = [True, True]
        task, _ = self._task([pool], network_group_multiplier=1)

        with patch(
            "neteng.test_infra.dne.taac.tasks.ixia_tasks.Ipv4PrefixPools",
            FakeIpv4PrefixPool,
        ):
            withdraw_evidence = task.configure_bgp_prefixes_active_state(
                False,
                "^PREFIX_POOL_IPV4_EBGP$",
                750,
                850,
                expected_prefix_pool_names=("PREFIX_POOL_IPV4_EBGP",),
                strict_range=True,
                verify_readback=True,
            )
            advertise_evidence = task.configure_bgp_prefixes_active_state(
                True,
                "^PREFIX_POOL_IPV4_EBGP$",
                750,
                850,
                expected_prefix_pool_names=("PREFIX_POOL_IPV4_EBGP",),
                strict_range=True,
                verify_readback=True,
            )

        self.assertEqual(850, pool.NumberOfAddresses)
        self.assertEqual([True, True], pool.route_property.Active.Values)
        self.assertEqual(750, withdraw_evidence["pools"][0]["prefixes_per_peer"])
        self.assertEqual(850, advertise_evidence["pools"][0]["prefixes_per_peer"])
        self.assertEqual(
            750,
            withdraw_evidence["pools"][0]["logical_prefix_capacity_after_operation"],
        )
        self.assertEqual(
            850,
            advertise_evidence["pools"][0]["logical_prefix_capacity_after_operation"],
        )
        self.assertTrue(withdraw_evidence["pools"][0]["readback_verified"])

    def test_strict_compact_slice_skips_steady_state_reapply(self) -> None:
        pool = FakeIpv4PrefixPool(
            "PREFIX_POOL_IPV4_EBGP",
            number_of_addresses=850,
            compact_peer_count=2,
        )
        pool.route_property.Active.Values = [True, True]
        task, ixia = self._task([pool], network_group_multiplier=1)

        with patch(
            "neteng.test_infra.dne.taac.tasks.ixia_tasks.Ipv4PrefixPools",
            FakeIpv4PrefixPool,
        ):
            evidence = task.configure_bgp_prefixes_active_state(
                True,
                "^PREFIX_POOL_IPV4_EBGP$",
                750,
                850,
                expected_prefix_pool_names=("PREFIX_POOL_IPV4_EBGP",),
                strict_range=True,
                verify_readback=True,
            )

        ixia.apply_changes.assert_not_called()
        self.assertEqual(850, evidence["pools"][0]["prefixes_per_peer"])
        self.assertTrue(evidence["pools"][0]["readback_verified"])

    def test_cleanup_failure_latches_terminal_error(self) -> None:
        pool = FakeIpv4PrefixPool("RUNTIME_20")
        task, ixia = self._task([pool])
        pool.route_property.Active.ValueList.side_effect = RuntimeError(
            "setter and cleanup failed"
        )

        with (
            patch(
                "neteng.test_infra.dne.taac.tasks.ixia_tasks.Ipv4PrefixPools",
                FakeIpv4PrefixPool,
            ),
            self.assertRaisesRegex(ValueError, "fail-closed withdrawal failed"),
        ):
            task.configure_bgp_prefixes_active_state(
                True,
                "^RUNTIME_20$",
                expected_prefix_pool_count=1,
            )
        write_count = pool.route_property.Active.ValueList.call_count
        lookup_count = ixia.get_prefix_pools_by_regexes.call_count

        with self.assertRaisesRegex(
            ValueError, "Create a new IxiaEnableDisableBgpPrefixes instance"
        ):
            task.configure_bgp_prefixes_active_state(
                True,
                "^RUNTIME_20$",
                expected_prefix_pool_count=1,
            )

        self.assertEqual(write_count, pool.route_property.Active.ValueList.call_count)
        self.assertEqual(lookup_count, ixia.get_prefix_pools_by_regexes.call_count)

        recovered_pool = FakeIpv4PrefixPool("RUNTIME_20")
        replacement, _ = self._task([recovered_pool])
        with patch(
            "neteng.test_infra.dne.taac.tasks.ixia_tasks.Ipv4PrefixPools",
            FakeIpv4PrefixPool,
        ):
            replacement.configure_bgp_prefixes_active_state(
                True,
                "^RUNTIME_20$",
                expected_prefix_pool_count=1,
            )
        self.assertEqual([True] * 20, recovered_pool.route_property.Active.Values)

    def test_invalid_expected_count_fails_before_lookup(self) -> None:
        for invalid_count in (0, -1, True, 1.0, "1"):
            with self.subTest(invalid_count=invalid_count):
                task, ixia = self._task([])

                with self.assertRaisesRegex(ValueError, "positive non-bool integer"):
                    task.configure_bgp_prefixes_active_state(
                        True,
                        "runtime",
                        prefix_end_index=20,
                        expected_prefix_pool_count=invalid_count,
                    )

                ixia.get_prefix_pools_by_regexes.assert_not_called()
                ixia.apply_changes.assert_not_called()

    def test_compact_pool_resize_is_inactive_verified_and_online(self) -> None:
        pool = FakeIpv4PrefixPool(
            "SHARED_RUNTIME",
            number_of_addresses=100,
            compact_peer_count=140,
        )
        pool.route_property.Active.Values = [True] * 140
        task, ixia = self._task([pool], network_group_multiplier=1)

        with patch(
            "neteng.test_infra.dne.taac.tasks.ixia_tasks.Ipv4PrefixPools",
            FakeIpv4PrefixPool,
        ):
            task.configure_bgp_prefixes_active_state(
                False,
                "^SHARED_RUNTIME$",
                prefix_start_index=0,
                expected_prefix_pool_count=1,
                target_number_of_addresses=20,
                allowed_current_number_of_addresses=(100,),
                safe_number_of_addresses=100,
                runtime_route_operation=True,
            )

        self.assertEqual(20, pool.NumberOfAddresses)
        self.assertEqual([False] * 140, pool.route_property.Active.Values)
        self.assertEqual(
            [[False] * 140, [False] * 140],
            [
                call.args[0]
                for call in pool.route_property.Active.ValueList.call_args_list
            ],
        )
        self.assertEqual(3, ixia.apply_changes.call_count)
        self.assertGreaterEqual(pool.refresh.call_count, 2)
        self.assertGreaterEqual(pool.route_property.refresh.call_count, 2)
        ixia.start_protocols.assert_not_called()
        ixia.stop_protocols.assert_not_called()
        pool.route_property.Stop.assert_called_once_with(
            SessionIndices=list(range(1, 141))
        )
        pool.route_property.Start.assert_not_called()

    def test_compact_pool_resize_preserves_physical_row_cardinality(self) -> None:
        for target_count in (50, 20, 1):
            with self.subTest(target_count=target_count):
                pool = FakeIpv4PrefixPool(
                    "SHARED_RUNTIME",
                    number_of_addresses=100,
                    compact_peer_count=140,
                )
                pool.route_property.Active.Values = [True] * 140
                task, _ = self._task([pool], network_group_multiplier=1)

                with patch(
                    "neteng.test_infra.dne.taac.tasks.ixia_tasks.Ipv4PrefixPools",
                    FakeIpv4PrefixPool,
                ):
                    task.configure_bgp_prefixes_active_state(
                        False,
                        "^SHARED_RUNTIME$",
                        expected_prefix_pool_count=1,
                        target_number_of_addresses=target_count,
                        allowed_current_number_of_addresses=(100,),
                        safe_number_of_addresses=100,
                    )

                self.assertEqual(target_count, pool.NumberOfAddresses)
                self.assertEqual(140, len(pool.route_property.Active.Values))
                self.assertFalse(any(pool.route_property.Active.Values))

    def test_compact_pool_rejects_partial_logical_prefix_selection(self) -> None:
        pool = FakeIpv4PrefixPool(
            "SHARED_RUNTIME",
            number_of_addresses=100,
            compact_peer_count=140,
        )
        task, ixia = self._task([pool], network_group_multiplier=1)

        with (
            patch(
                "neteng.test_infra.dne.taac.tasks.ixia_tasks.Ipv4PrefixPools",
                FakeIpv4PrefixPool,
            ),
            self.assertRaisesRegex(ValueError, "cannot select a partial"),
        ):
            task.configure_bgp_prefixes_active_state(
                True,
                "^SHARED_RUNTIME$",
                prefix_start_index=0,
                prefix_end_index=20,
                expected_prefix_pool_count=1,
                expected_number_of_addresses=100,
                runtime_route_operation=True,
            )

        pool.route_property.Start.assert_not_called()
        pool.route_property.Stop.assert_not_called()
        ixia.apply_changes.assert_not_called()

    def test_runtime_enable_orders_stop_mutate_verify_start(self) -> None:
        events: list[tuple[str, t.Any]] = []
        pool = FakeIpv4PrefixPool(
            "SHARED_RUNTIME",
            number_of_addresses=20,
            compact_peer_count=140,
        )
        task, ixia = self._task([pool], network_group_multiplier=1)

        def set_active(values) -> None:
            pool.route_property.Active.Values = list(values)
            events.append(("active", tuple(values)))

        pool.route_property.Active.ValueList.side_effect = set_active
        pool.route_property.Stop.side_effect = lambda *, SessionIndices: events.append(
            ("stop", tuple(SessionIndices))
        )
        pool.route_property.Start.side_effect = lambda *, SessionIndices: events.append(
            ("start", tuple(SessionIndices))
        )
        ixia.apply_changes.side_effect = lambda: events.append(("apply", None))

        with patch(
            "neteng.test_infra.dne.taac.tasks.ixia_tasks.Ipv4PrefixPools",
            FakeIpv4PrefixPool,
        ):
            task.configure_bgp_prefixes_active_state(
                True,
                "^SHARED_RUNTIME$",
                expected_prefix_pool_count=1,
                expected_number_of_addresses=20,
                runtime_route_operation=True,
            )

        self.assertEqual(
            ["stop", "active", "apply", "start", "apply"],
            [event for event, _ in events],
        )
        self.assertEqual(tuple(range(1, 141)), events[0][1])
        self.assertTrue(all(pool.route_property.Active.Values))

    def test_runtime_disable_stops_before_active_mutation(self) -> None:
        events: list[str] = []
        pool = FakeIpv4PrefixPool(
            "SHARED_RUNTIME",
            number_of_addresses=20,
            compact_peer_count=140,
        )
        pool.route_property.Active.Values = [True] * 140
        task, ixia = self._task([pool], network_group_multiplier=1)

        def set_active(values) -> None:
            pool.route_property.Active.Values = list(values)
            events.append("active")

        pool.route_property.Active.ValueList.side_effect = set_active
        pool.route_property.Stop.side_effect = lambda **_: events.append("stop")
        pool.route_property.Start.side_effect = lambda **_: events.append("start")
        ixia.apply_changes.side_effect = lambda: events.append("apply")

        with patch(
            "neteng.test_infra.dne.taac.tasks.ixia_tasks.Ipv4PrefixPools",
            FakeIpv4PrefixPool,
        ):
            task.configure_bgp_prefixes_active_state(
                False,
                "^SHARED_RUNTIME$",
                expected_prefix_pool_count=1,
                expected_number_of_addresses=20,
                runtime_route_operation=True,
            )

        self.assertEqual(["stop", "active", "apply"], events)
        self.assertFalse(any(pool.route_property.Active.Values))

    def test_runtime_start_failure_rolls_back_stopped_and_inactive(self) -> None:
        pool = FakeIpv4PrefixPool(
            "SHARED_RUNTIME",
            number_of_addresses=20,
            compact_peer_count=140,
        )
        task, ixia = self._task([pool], network_group_multiplier=1)
        pool.route_property.Start.side_effect = RuntimeError("start failed")

        with (
            patch(
                "neteng.test_infra.dne.taac.tasks.ixia_tasks.Ipv4PrefixPools",
                FakeIpv4PrefixPool,
            ),
            self.assertRaisesRegex(RuntimeError, "start failed"),
        ):
            task.configure_bgp_prefixes_active_state(
                True,
                "^SHARED_RUNTIME$",
                expected_prefix_pool_count=1,
                expected_number_of_addresses=20,
                runtime_route_operation=True,
            )

        self.assertEqual(2, pool.route_property.Stop.call_count)
        self.assertFalse(any(pool.route_property.Active.Values))
        self.assertEqual(3, ixia.apply_changes.call_count)

    def test_safe_active_restore_skips_verify_when_apply_fails(self) -> None:
        pool = FakeIpv4PrefixPool("SHARED_RUNTIME")
        task, ixia = self._task([pool])
        failure = RuntimeError("cleanup apply failed")
        ixia.apply_changes.side_effect = failure
        task._verify_fresh_active_values = MagicMock()
        failures: list[Exception] = []

        with patch(
            "neteng.test_infra.dne.taac.tasks.ixia_tasks.Ipv4PrefixPools",
            FakeIpv4PrefixPool,
        ):
            task._restore_safe_active_values(
                [pool],
                "^SHARED_RUNTIME$",
                1,
                {"SHARED_RUNTIME": [False]},
                failures,
            )

        self.assertEqual([failure], failures)
        task._verify_fresh_active_values.assert_not_called()

    def test_safe_compact_restore_attempts_final_withdraw_after_resize_failure(
        self,
    ) -> None:
        pool = FakeIpv4PrefixPool(
            "SHARED_RUNTIME",
            number_of_addresses=20,
            compact_peer_count=140,
        )
        task, _ = self._task([pool], network_group_multiplier=1)
        resize_failure = RuntimeError("cleanup resize failed")
        task._write_all_fresh_active_values_inactive = MagicMock()
        task._resize_prefix_pools = MagicMock(side_effect=resize_failure)
        task._verify_safe_compact_capacity = MagicMock()
        failures: list[Exception] = []

        with patch(
            "neteng.test_infra.dne.taac.tasks.ixia_tasks.Ipv4PrefixPools",
            FakeIpv4PrefixPool,
        ):
            task._restore_safe_compact_capacity(
                [pool],
                "^SHARED_RUNTIME$",
                1,
                {"SHARED_RUNTIME": [False] * 140},
                100,
                failures,
            )

        self.assertEqual([resize_failure], failures)
        self.assertEqual(2, task._write_all_fresh_active_values_inactive.call_count)
        task._verify_safe_compact_capacity.assert_called_once()

    def test_compact_pool_restore_expands_active_geometry_and_withdraws_all(
        self,
    ) -> None:
        pool = FakeIpv4PrefixPool(
            "SHARED_RUNTIME",
            number_of_addresses=20,
            compact_peer_count=140,
        )
        pool.route_property.Active.Values = [True] * 140
        task, ixia = self._task([pool], network_group_multiplier=1)

        with patch(
            "neteng.test_infra.dne.taac.tasks.ixia_tasks.Ipv4PrefixPools",
            FakeIpv4PrefixPool,
        ):
            task.configure_bgp_prefixes_active_state(
                False,
                "^SHARED_RUNTIME$",
                expected_prefix_pool_count=1,
                target_number_of_addresses=100,
                allowed_current_number_of_addresses=(20,),
                safe_number_of_addresses=100,
            )

        self.assertEqual(100, pool.NumberOfAddresses)
        self.assertEqual([False] * 140, pool.route_property.Active.Values)
        self.assertEqual(
            [[False] * 140, [False] * 140],
            [
                call.args[0]
                for call in pool.route_property.Active.ValueList.call_args_list
            ],
        )
        self.assertEqual(3, ixia.apply_changes.call_count)
        ixia.start_protocols.assert_not_called()
        ixia.stop_protocols.assert_not_called()

    def test_compact_pool_resize_rejects_noncompact_geometry(self) -> None:
        pool = FakeIpv4PrefixPool("SHARED_RUNTIME", number_of_addresses=100)
        task, ixia = self._task([pool], network_group_multiplier=100)

        with (
            patch(
                "neteng.test_infra.dne.taac.tasks.ixia_tasks.Ipv4PrefixPools",
                FakeIpv4PrefixPool,
            ),
            self.assertRaisesRegex(ValueError, "Multiplier=1"),
        ):
            task.configure_bgp_prefixes_active_state(
                False,
                "^SHARED_RUNTIME$",
                expected_prefix_pool_count=1,
                target_number_of_addresses=20,
                allowed_current_number_of_addresses=(100,),
                safe_number_of_addresses=100,
            )

        self.assertEqual(100, pool.NumberOfAddresses)
        self.assertEqual([False] * 20, pool.route_property.Active.Values)
        self.assertGreaterEqual(ixia.apply_changes.call_count, 3)

    def test_unexpected_compact_pool_count_fails_closed_to_inactive_capacity(
        self,
    ) -> None:
        pool = FakeIpv4PrefixPool(
            "SHARED_RUNTIME",
            number_of_addresses=7,
            compact_peer_count=140,
        )
        pool.route_property.Active.Values = [True] * 140
        task, ixia = self._task([pool], network_group_multiplier=1)

        with (
            patch(
                "neteng.test_infra.dne.taac.tasks.ixia_tasks.Ipv4PrefixPools",
                FakeIpv4PrefixPool,
            ),
            self.assertRaisesRegex(ValueError, "expected one of"),
        ):
            task.configure_bgp_prefixes_active_state(
                False,
                "^SHARED_RUNTIME$",
                expected_prefix_pool_count=1,
                target_number_of_addresses=100,
                allowed_current_number_of_addresses=(20,),
                safe_number_of_addresses=100,
            )

        self.assertEqual(100, pool.NumberOfAddresses)
        self.assertEqual([False] * 140, pool.route_property.Active.Values)
        self.assertGreaterEqual(ixia.apply_changes.call_count, 3)
        ixia.start_protocols.assert_not_called()
        ixia.stop_protocols.assert_not_called()

    def test_compact_pool_resize_readback_failure_restores_safe_capacity(self) -> None:
        pool = FakeIpv4PrefixPool(
            "SHARED_RUNTIME",
            number_of_addresses=100,
            compact_peer_count=140,
        )
        pool.route_property.Active.Values = [True] * 140
        task, ixia = self._task([pool], network_group_multiplier=1)
        original_verify = task._verify_fresh_inactive_values
        verification_count = 0

        def fail_target_readback(*args, **kwargs) -> None:
            nonlocal verification_count
            verification_count += 1
            if verification_count % 2:
                raise ValueError("stale resize readback")
            original_verify(*args, **kwargs)

        task._verify_fresh_inactive_values = MagicMock(side_effect=fail_target_readback)

        with (
            patch(
                "neteng.test_infra.dne.taac.tasks.ixia_tasks.Ipv4PrefixPools",
                FakeIpv4PrefixPool,
            ),
            self.assertRaisesRegex(ValueError, "stale resize readback"),
        ):
            task.configure_bgp_prefixes_active_state(
                False,
                "^SHARED_RUNTIME$",
                expected_prefix_pool_count=1,
                target_number_of_addresses=20,
                allowed_current_number_of_addresses=(100,),
                safe_number_of_addresses=100,
            )

        self.assertEqual(100, pool.NumberOfAddresses)
        self.assertEqual([False] * 140, pool.route_property.Active.Values)
        ixia.start_protocols.assert_not_called()
        ixia.stop_protocols.assert_not_called()

    async def test_expected_count_run_offloads_synchronous_restpy_work(self) -> None:
        task, _ = self._task([])
        task.configure_bgp_prefixes_active_state = MagicMock()

        await task.run(
            {
                "enable": True,
                "prefix_pool_regex": "runtime",
                "prefix_start_index": 0,
                "prefix_end_index": 20,
                "expected_prefix_pool_count": 1,
            }
        )

        task.configure_bgp_prefixes_active_state.assert_called_once_with(
            True, "runtime", 0, 20, 1
        )

    async def test_run_records_strict_toggle_evidence(self) -> None:
        task, _ = self._task([])
        evidence = {"pools": [{"name": "PREFIX_POOL_IPV4_EBGP"}]}
        task.configure_bgp_prefixes_active_state = MagicMock(return_value=evidence)

        await task.run(
            {
                "enable": True,
                "prefix_pool_regex": "^PREFIX_POOL_IPV4_EBGP$",
                "prefix_start_index": 750,
                "prefix_end_index": 850,
                "expected_prefix_pool_names": ["PREFIX_POOL_IPV4_EBGP"],
                "strict_range": True,
                "verify_readback": True,
            }
        )

        task.configure_bgp_prefixes_active_state.assert_called_once_with(
            True,
            "^PREFIX_POOL_IPV4_EBGP$",
            750,
            850,
            None,
            expected_prefix_pool_names=["PREFIX_POOL_IPV4_EBGP"],
            strict_range=True,
            verify_readback=True,
        )
        self.assertEqual(evidence, task._data["prefix_toggle"])

    async def test_run_retains_cross_instance_phase_evidence(self) -> None:
        shared_data: dict[str, t.Any] = {}
        first, ixia = self._task([])
        second = IxiaEnableDisableBgpPrefixes(
            ixia=t.cast(t.Any, ixia), shared_data=shared_data
        )
        first = IxiaEnableDisableBgpPrefixes(
            ixia=t.cast(t.Any, ixia), shared_data=shared_data
        )
        first.configure_bgp_prefixes_active_state = MagicMock(
            return_value={"pools": [{"name": "PREFIX_POOL_IPV4_EBGP"}]}
        )
        second.configure_bgp_prefixes_active_state = MagicMock(
            return_value={"pools": [{"name": "PREFIX_POOL_IPV6_EBGP"}]}
        )

        await first.run(
            {
                "enable": False,
                "prefix_pool_regex": "^PREFIX_POOL_IPV4_EBGP$",
                "evidence_label": "setup_withdraw:PREFIX_POOL_IPV4_EBGP",
            }
        )
        await second.run(
            {
                "enable": True,
                "prefix_pool_regex": "^PREFIX_POOL_IPV6_EBGP$",
                "evidence_label": "stage_advertise:PREFIX_POOL_IPV6_EBGP",
            }
        )

        history = second._data["prefix_toggle_history"]
        self.assertEqual(2, len(history))
        self.assertEqual(
            [
                "setup_withdraw:PREFIX_POOL_IPV4_EBGP",
                "stage_advertise:PREFIX_POOL_IPV6_EBGP",
            ],
            [record["label"] for record in history],
        )

    async def test_worker_path_serializes_restpy_across_task_instances(self) -> None:
        first_started = threading.Event()
        release_first = threading.Event()
        second_started = threading.Event()
        first_pool = FakeIpv4PrefixPool("runtime")
        second_pool = FakeIpv4PrefixPool("runtime")
        first, _ = self._task([first_pool])
        second, _ = self._task([second_pool])

        def first_lookup(*, prefix_pool_regex):
            first_started.set()
            release_first.wait()
            return [first_pool]

        def second_lookup(*, prefix_pool_regex):
            second_started.set()
            return [second_pool]

        first.ixia.get_prefix_pools_by_regexes = MagicMock(side_effect=first_lookup)
        second.ixia.get_prefix_pools_by_regexes = MagicMock(side_effect=second_lookup)
        params = {
            "enable": True,
            "prefix_pool_regex": "runtime",
            "prefix_start_index": 0,
            "prefix_end_index": 20,
            "expected_prefix_pool_count": 1,
        }

        with patch(
            "neteng.test_infra.dne.taac.tasks.ixia_tasks.Ipv4PrefixPools",
            FakeIpv4PrefixPool,
        ):
            first_run = asyncio.create_task(first.run(params))
            await self._wait_for(first_started)
            second_run = asyncio.create_task(second.run(params))
            await asyncio.sleep(0)
            self.assertFalse(second_started.is_set())
            release_first.set()
            await asyncio.gather(first_run, second_run)

        self.assertTrue(second_started.is_set())

    async def test_legacy_run_offloads_synchronous_restpy_work(self) -> None:
        task, _ = self._task([])
        task.configure_bgp_prefixes_active_state = MagicMock()
        target = "neteng.test_infra.dne.taac.tasks.ixia_tasks.asyncio.to_thread"

        with patch(target, new=AsyncMock()) as to_thread:
            to_thread.return_value = {"pools": []}
            await task.run(
                {
                    "enable": False,
                    "prefix_pool_regex": "optional",
                    "prefix_start_index": 0,
                    "prefix_end_index": 20,
                }
            )

        to_thread.assert_awaited_once_with(
            task.configure_bgp_prefixes_active_state,
            False,
            "optional",
            0,
            20,
            None,
        )
        task.configure_bgp_prefixes_active_state.assert_not_called()
