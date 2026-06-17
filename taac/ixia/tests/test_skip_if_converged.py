# pyre-unsafe
# Copyright (c) Meta Platforms, Inc. and affiliates.
"""Unit tests for skip-if-already-converged helpers + `configure_bgp_peers_flap` integration.

Pain #1 Lever E. Validates:
  * `_ixia_value_equals` type-coerces correctly (bool, int, float, string)
  * `_set_multivalue_if_changed` skips on match, writes on mismatch
  * fallthrough-to-write on Values read failure
  * `configure_bgp_peers_flap` reports skipped/total counter accurately
"""

import unittest
from unittest.mock import MagicMock, patch

from taac.ixia.ixia import (
    _ixia_value_equals,
    _set_multivalue_if_changed,
    Ixia,
)


class IxiaValueEqualsTest(unittest.TestCase):
    """Type-coerce-safe comparison of IxNetwork-returned strings vs Python values."""

    # ---- bool ----
    def test_bool_true_matches_string_true(self):
        self.assertTrue(_ixia_value_equals("true", True))

    def test_bool_true_matches_capital_TRUE(self):
        self.assertTrue(_ixia_value_equals("TRUE", True))

    def test_bool_false_matches_string_false(self):
        self.assertTrue(_ixia_value_equals("false", False))

    def test_bool_true_does_not_match_string_false(self):
        self.assertFalse(_ixia_value_equals("false", True))

    # ---- int ----
    def test_int_matches_string(self):
        self.assertTrue(_ixia_value_equals("60", 60))

    def test_int_does_not_match_different_string(self):
        self.assertFalse(_ixia_value_equals("60", 30))

    def test_int_handles_non_numeric_string_safely(self):
        # Non-numeric current value should NOT crash and should return False
        # so the caller falls through to a write.
        self.assertFalse(_ixia_value_equals("not-a-number", 60))

    def test_int_handles_none_current_safely(self):
        self.assertFalse(_ixia_value_equals(None, 60))

    # ---- float ----
    def test_float_matches_string(self):
        self.assertTrue(_ixia_value_equals("1.5", 1.5))

    def test_float_handles_garbage(self):
        self.assertFalse(_ixia_value_equals("garbage", 1.5))

    # ---- string ----
    def test_string_exact_match(self):
        self.assertTrue(_ixia_value_equals("foo", "foo"))

    def test_string_mismatch(self):
        self.assertFalse(_ixia_value_equals("foo", "bar"))


class SetMultivalueIfChangedTest(unittest.TestCase):
    """Skip-if-converged behavior on Multivalue-like objects."""

    def _mv(self, current_values):
        mv = MagicMock()
        mv.Values = current_values
        return mv

    def test_skips_when_already_equal_bool(self):
        mv = self._mv(["true"])
        wrote = _set_multivalue_if_changed(mv, True)
        self.assertFalse(wrote)
        mv.Single.assert_not_called()

    def test_writes_when_differ_bool(self):
        mv = self._mv(["false"])
        wrote = _set_multivalue_if_changed(mv, True)
        self.assertTrue(wrote)
        mv.Single.assert_called_once_with(value=True)

    def test_skips_when_already_equal_int(self):
        mv = self._mv(["60"])
        wrote = _set_multivalue_if_changed(mv, 60)
        self.assertFalse(wrote)
        mv.Single.assert_not_called()

    def test_writes_when_differ_int(self):
        mv = self._mv(["30"])
        wrote = _set_multivalue_if_changed(mv, 60)
        self.assertTrue(wrote)
        mv.Single.assert_called_once_with(value=60)

    def test_falls_through_to_write_when_values_read_raises(self):
        """Conservative: any Values read failure → write anyway (safe)."""
        mv = MagicMock()
        # Configure Values property to raise on access
        type(mv).Values = MagicMock(side_effect=RuntimeError("REST blip"))
        wrote = _set_multivalue_if_changed(mv, 60)
        self.assertTrue(wrote)
        mv.Single.assert_called_once_with(value=60)

    def test_falls_through_to_write_when_values_empty(self):
        mv = self._mv([])  # empty Values
        wrote = _set_multivalue_if_changed(mv, 60)
        self.assertTrue(wrote)
        mv.Single.assert_called_once_with(value=60)


class ConfigureBgpPeersFlapSkipCounterTest(unittest.TestCase):
    """Integration: `configure_bgp_peers_flap` should track skipped writes."""

    def _make_peer(
        self, name, current_uptime=None, current_downtime=None, current_flap=None
    ):
        peer = MagicMock()
        peer.Name = name
        # Pre-populate Multivalue Values so skip-if-converged can read them
        peer.UptimeInSec = MagicMock()
        peer.UptimeInSec.Values = (
            [str(current_uptime)] if current_uptime is not None else []
        )
        peer.DowntimeInSec = MagicMock()
        peer.DowntimeInSec.Values = (
            [str(current_downtime)] if current_downtime is not None else []
        )
        peer.Flap = MagicMock()
        peer.Flap.Values = (
            [str(current_flap).lower()] if current_flap is not None else []
        )
        return peer

    def _make_ixia(self, peers, fail_peer_names=()):
        with patch.object(Ixia, "__init__", lambda self: None):
            ixia = Ixia()
        ixia.logger = MagicMock()
        ixia.apply_changes = MagicMock()
        ixia.find_bgp_peers = MagicMock(return_value=peers)
        return ixia

    def test_all_peers_already_converged_zero_writes(self):
        """3 peers, all at desired uptime=60/downtime=30/flap=True → 0/9 writes."""
        peers = [
            self._make_peer(
                f"P{i}", current_uptime=60, current_downtime=30, current_flap=True
            )
            for i in range(3)
        ]
        ixia = self._make_ixia(peers)
        ixia.configure_bgp_peers_flap(
            regex=".*", enable=True, uptime_in_sec=60, downtime_in_sec=30
        )
        # No peer should have had its Multivalue.Single called
        for peer in peers:
            peer.UptimeInSec.Single.assert_not_called()
            peer.DowntimeInSec.Single.assert_not_called()
            peer.Flap.Single.assert_not_called()
        # apply_changes IS still called (even when nothing changed — safe default)
        ixia.apply_changes.assert_called_once()
        # Summary log fired with 9/9 skipped
        summary_logged = any(
            "9/9 writes skipped" in str(call)
            for call in ixia.logger.info.call_args_list
        )
        self.assertTrue(summary_logged, "expected 9/9 skipped summary in logger.info")

    def test_partial_convergence(self):
        """Some peers converged, some not."""
        peers = [
            self._make_peer(
                "P0", current_uptime=60, current_downtime=30, current_flap=True
            ),  # all match
            self._make_peer(
                "P1", current_uptime=99, current_downtime=99, current_flap=False
            ),  # all differ
        ]
        ixia = self._make_ixia(peers)
        ixia.configure_bgp_peers_flap(
            regex=".*", enable=True, uptime_in_sec=60, downtime_in_sec=30
        )
        # P0: all 3 should be skipped (no writes)
        peers[0].UptimeInSec.Single.assert_not_called()
        peers[0].DowntimeInSec.Single.assert_not_called()
        peers[0].Flap.Single.assert_not_called()
        # P1: all 3 should be written
        peers[1].UptimeInSec.Single.assert_called_once_with(value=60)
        peers[1].DowntimeInSec.Single.assert_called_once_with(value=30)
        peers[1].Flap.Single.assert_called_once_with(value=True)
        summary_logged = any(
            "3/6 writes skipped" in str(call)
            for call in ixia.logger.info.call_args_list
        )
        self.assertTrue(summary_logged, "expected 3/6 skipped summary")

    def test_only_supplied_kwargs_are_counted(self):
        """When only `enable` is passed, only Flap is touched — count is N/N for N peers."""
        peers = [self._make_peer(f"P{i}", current_flap=True) for i in range(3)]
        ixia = self._make_ixia(peers)
        # Pass ONLY enable — uptime/downtime should not be touched at all
        ixia.configure_bgp_peers_flap(regex=".*", enable=True)
        for peer in peers:
            peer.UptimeInSec.Single.assert_not_called()
            peer.DowntimeInSec.Single.assert_not_called()
            peer.Flap.Single.assert_not_called()  # already True, skip
        # Counter should be 3/3 (3 Flap writes considered, all skipped)
        summary_logged = any(
            "3/3 writes skipped" in str(call)
            for call in ixia.logger.info.call_args_list
        )
        self.assertTrue(summary_logged)
