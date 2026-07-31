# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
import unittest
from types import SimpleNamespace

from taac.tasks.ixia_tasks import _resolve_prefix_slots

_PREFIX_COUNT = 50000
_PEERS = 2


def _pool(number_of_addresses: int) -> SimpleNamespace:
    """Minimal stand-in for an IxNetwork prefix-pool node (only NumberOfAddresses
    is read by the helper)."""
    return SimpleNamespace(NumberOfAddresses=number_of_addresses)


class ResolvePrefixSlotsTest(unittest.TestCase):
    """The enable/disable + attribute tasks select route-range slots by index. The
    per-route-range multivalue spans ``peers * prefixes_per_peer``, where
    ``prefixes_per_peer = NetworkGroup.Multiplier * pool.NumberOfAddresses`` equals
    the configured prefix count in BOTH IxNetwork geometries. Regression guard:
    compact geometry previously collapsed the window to "range 0 - 1" and
    advertised ~0 routes (P2441146392)."""

    def test_compact_full_range_enables_all(self) -> None:
        # compact: NetworkGroup.Multiplier=1, NumberOfAddresses=prefix_count
        total = _PEERS * _PREFIX_COUNT
        slots, end_idx = _resolve_prefix_slots(
            _pool(_PREFIX_COUNT), 1, total, 0, _PREFIX_COUNT
        )
        self.assertEqual(end_idx, _PREFIX_COUNT)  # NOT 1 (the pre-fix collapse)
        self.assertEqual(len(slots), total)  # every route range on every peer
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
        total = _PEERS * _PREFIX_COUNT
        slots, end_idx = _resolve_prefix_slots(_pool(_PREFIX_COUNT), 1, total, 0, None)
        self.assertEqual(end_idx, _PREFIX_COUNT)
        self.assertEqual(len(slots), total)

    def test_sub_range_applies_per_peer(self) -> None:
        # Enable only the first 100 prefixes of EACH peer.
        total = _PEERS * _PREFIX_COUNT
        slots, end_idx = _resolve_prefix_slots(_pool(_PREFIX_COUNT), 1, total, 0, 100)
        self.assertEqual(end_idx, 100)
        self.assertEqual(len(slots), _PEERS * 100)
        self.assertTrue(all(mod < 100 for _, mod in slots))
        selected = {i for i, _ in slots}
        self.assertIn(0, selected)
        self.assertIn(99, selected)
        self.assertIn(_PREFIX_COUNT, selected)  # peer 2's first prefix
        self.assertIn(_PREFIX_COUNT + 99, selected)
        self.assertNotIn(100, selected)

    def test_end_index_clamped_to_prefixes_per_peer(self) -> None:
        total = _PEERS * _PREFIX_COUNT
        _, end_idx = _resolve_prefix_slots(
            _pool(_PREFIX_COUNT), 1, total, 0, 10 * _PREFIX_COUNT
        )
        self.assertEqual(end_idx, _PREFIX_COUNT)

    def test_within_peer_index_exposed_for_cycling(self) -> None:
        # Origin cycling relies on the within-peer index, not the global index.
        total = _PEERS * _PREFIX_COUNT
        slots, _ = _resolve_prefix_slots(
            _pool(_PREFIX_COUNT), 1, total, 0, _PREFIX_COUNT
        )
        by_index = dict(slots)
        self.assertEqual(by_index[0], 0)
        self.assertEqual(by_index[_PREFIX_COUNT], 0)  # peer 2 restarts at 0
        self.assertEqual(by_index[_PREFIX_COUNT + 5], 5)
