# pyre-unsafe
# Copyright (c) Meta Platforms, Inc. and affiliates.
import threading
import unittest
from unittest.mock import MagicMock, patch

from taac.ixia.ixia import Ixia


def _make_peer(name: str):
    """Create a mock BGP peer container with the three Multivalue properties."""
    peer = MagicMock()
    peer.Name = name
    peer.UptimeInSec = MagicMock()
    peer.DowntimeInSec = MagicMock()
    peer.Flap = MagicMock()
    return peer


def _create_ixia_instance():
    """Create an Ixia instance with mocked session, logger, and apply_changes."""
    with patch.object(Ixia, "__init__", lambda self: None):
        ixia = Ixia()
    ixia.logger = MagicMock()
    ixia.session = MagicMock()
    ixia.apply_changes = MagicMock()
    return ixia


class ConfigureBgpPeersFlapTest(unittest.TestCase):
    """Tests for Ixia.configure_bgp_peers_flap concurrent batching."""

    def setUp(self):
        self.ixia = _create_ixia_instance()
        self.peers = [_make_peer(f"BGP_PEER_{i}") for i in range(5)]
        self.ixia.find_bgp_peers = MagicMock(return_value=self.peers)

    def test_no_matching_peers_short_circuits(self):
        """Empty match list logs and returns without calling apply_changes."""
        self.ixia.find_bgp_peers.return_value = []
        self.ixia.configure_bgp_peers_flap(
            regex="NOMATCH.*", enable=True, uptime_in_sec=30, downtime_in_sec=30
        )
        self.ixia.apply_changes.assert_not_called()

    def test_all_three_props_applied_to_every_peer(self):
        """When all three params given, every peer gets all three .Single() calls."""
        self.ixia.configure_bgp_peers_flap(
            regex=".*", enable=True, uptime_in_sec=30, downtime_in_sec=45
        )
        for peer in self.peers:
            peer.UptimeInSec.Single.assert_called_once_with(value=30)
            peer.DowntimeInSec.Single.assert_called_once_with(value=45)
            peer.Flap.Single.assert_called_once_with(value=True)
        self.ixia.apply_changes.assert_called_once()

    def test_only_enable_param_skips_others(self):
        """Omitted uptime/downtime params skip the corresponding Single() calls."""
        self.ixia.configure_bgp_peers_flap(regex=".*", enable=False)
        for peer in self.peers:
            peer.UptimeInSec.Single.assert_not_called()
            peer.DowntimeInSec.Single.assert_not_called()
            peer.Flap.Single.assert_called_once_with(value=False)
        self.ixia.apply_changes.assert_called_once()

    def test_only_uptime_param(self):
        """Only uptime sets UptimeInSec, not the others."""
        self.ixia.configure_bgp_peers_flap(regex=".*", uptime_in_sec=120)
        for peer in self.peers:
            peer.UptimeInSec.Single.assert_called_once_with(value=120)
            peer.DowntimeInSec.Single.assert_not_called()
            peer.Flap.Single.assert_not_called()
        self.ixia.apply_changes.assert_called_once()

    def test_uptime_set_before_flap_per_peer(self):
        """Per the docstring: uptime/downtime MUST be set before enabling flap.

        Verified per-peer because concurrent execution makes cross-peer ordering
        non-deterministic, but within one peer the order is fixed by the worker
        function.
        """
        order_log = []

        def _logged_single(name, value):
            order_log.append((name, value))

        for peer in self.peers:
            peer.UptimeInSec.Single.side_effect = (
                lambda value, p=peer: order_log.append((p.Name, "Uptime"))
            )
            peer.DowntimeInSec.Single.side_effect = (
                lambda value, p=peer: order_log.append((p.Name, "Downtime"))
            )
            peer.Flap.Single.side_effect = lambda value, p=peer: order_log.append(
                (p.Name, "Flap")
            )

        self.ixia.configure_bgp_peers_flap(
            regex=".*", enable=True, uptime_in_sec=30, downtime_in_sec=30
        )

        # Verify per-peer property ordering: for every peer, Uptime/Downtime
        # appear before Flap.
        for peer in self.peers:
            calls_for_peer = [prop for (name, prop) in order_log if name == peer.Name]
            self.assertEqual(calls_for_peer, ["Uptime", "Downtime", "Flap"])

    def test_concurrent_failure_retried_sequentially_and_succeeds(self):
        """A peer that fails the first concurrent attempt is retried serially."""
        attempt_counts = {peer.Name: 0 for peer in self.peers}
        lock = threading.Lock()

        def _flap_side_effect(peer_name):
            def _impl(value):
                with lock:
                    attempt_counts[peer_name] += 1
                    if peer_name == "BGP_PEER_2" and attempt_counts[peer_name] == 1:
                        raise RuntimeError("simulated transient REST error")

            return _impl

        for peer in self.peers:
            peer.Flap.Single.side_effect = _flap_side_effect(peer.Name)

        self.ixia.configure_bgp_peers_flap(regex=".*", enable=True)

        # PEER_2 attempted twice (concurrent fail + sequential retry succeeded),
        # all others attempted exactly once.
        self.assertEqual(attempt_counts["BGP_PEER_2"], 2)
        for peer in self.peers:
            if peer.Name != "BGP_PEER_2":
                self.assertEqual(attempt_counts[peer.Name], 1)
        self.ixia.apply_changes.assert_called_once()

    def test_concurrent_failure_persisting_after_retry_raises(self):
        """A peer that fails BOTH the concurrent and retry attempts raises."""

        def _persistent_failure(value):
            raise RuntimeError("permanent REST failure")

        # Peer 3 fails always
        self.peers[3].Flap.Single.side_effect = _persistent_failure

        with self.assertRaises(RuntimeError) as cm:
            self.ixia.configure_bgp_peers_flap(regex=".*", enable=True)
        self.assertIn("1 peer(s) failed even after sequential retry", str(cm.exception))
        # apply_changes is NOT called on hard failure
        self.ixia.apply_changes.assert_not_called()

    def test_concurrent_calls_across_peers(self):
        """All peers' Flap.Single is called exactly once across N workers."""
        self.ixia.configure_bgp_peers_flap(regex=".*", enable=True)
        for peer in self.peers:
            self.assertEqual(peer.Flap.Single.call_count, 1)
        # apply_changes called exactly once after all peer property sets
        self.assertEqual(self.ixia.apply_changes.call_count, 1)

    def test_duplicate_peer_names_retried_independently(self):
        """Two distinct peer containers that share a Name must each be retried.

        IxNetwork allows separate BgpIpv4/v6Peer containers under different
        DeviceGroups to share a Name; a name-keyed retry map would collapse
        them. Ensure the retry path operates on the peer OBJECT, so both
        share-named peers are independently retried.
        """
        # Build 4 peers, two of which share Name "DUP".
        dup_a = _make_peer("DUP")
        dup_b = _make_peer("DUP")
        unique_c = _make_peer("UNIQUE_C")
        unique_d = _make_peer("UNIQUE_D")
        peers = [dup_a, dup_b, unique_c, unique_d]
        self.ixia.find_bgp_peers = MagicMock(return_value=peers)

        # Both DUP peers fail on the first concurrent attempt; on retry both succeed.
        attempt_counts = {id(p): 0 for p in peers}
        lock = threading.Lock()

        def _make_side_effect(peer):
            def _impl(value):
                with lock:
                    attempt_counts[id(peer)] += 1
                    if peer in (dup_a, dup_b) and attempt_counts[id(peer)] == 1:
                        raise RuntimeError("simulated transient REST error")

            return _impl

        for peer in peers:
            peer.Flap.Single.side_effect = _make_side_effect(peer)

        self.ixia.configure_bgp_peers_flap(regex=".*", enable=True)

        # Both DUP peers attempted twice (concurrent fail + sequential retry),
        # unique peers attempted exactly once. If retry-by-name had collapsed
        # the DUP entries, one of dup_a/dup_b would still be at 1.
        self.assertEqual(attempt_counts[id(dup_a)], 2)
        self.assertEqual(attempt_counts[id(dup_b)], 2)
        self.assertEqual(attempt_counts[id(unique_c)], 1)
        self.assertEqual(attempt_counts[id(unique_d)], 1)
        self.ixia.apply_changes.assert_called_once()

    def test_find_bgp_peers_called_with_regex(self):
        """The regex argument is forwarded to find_bgp_peers."""
        self.ixia.configure_bgp_peers_flap(regex=".*IPV4.*EB.*", enable=True)
        self.ixia.find_bgp_peers.assert_called_once_with(".*IPV4.*EB.*")
