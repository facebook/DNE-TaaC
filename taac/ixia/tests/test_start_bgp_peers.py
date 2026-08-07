# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe

import unittest
from unittest.mock import MagicMock, patch

from taac.ixia.ixia import Ixia


def _ixia() -> Ixia:
    with patch.object(Ixia, "__init__", lambda self: None):
        instance = Ixia()
    instance.logger = MagicMock()
    return instance


def _peer(name: str, count: int) -> MagicMock:
    peer = MagicMock()
    peer.Name = name
    peer.Count = count
    return peer


class StartBgpPeersTest(unittest.TestCase):
    def setUp(self) -> None:
        self.ixia = _ixia()
        self.peer = _peer("IPV4_EBGP", 140)
        self.find_bgp_peers = MagicMock(return_value=[self.peer])
        self.ixia.find_bgp_peers = self.find_bgp_peers

    def test_strict_target_and_range_stops_selected_sessions(self) -> None:
        self.ixia.start_bgp_peers(
            start=False,
            regex="IPV4_EBGP",
            session_start_idx=1,
            session_end_idx=11,
            expected_peer_count=1,
            validate_session_range=True,
        )

        self.peer.Stop.assert_called_once_with(SessionIndices="1-11")

    def test_expected_peer_count_rejects_empty_match(self) -> None:
        self.find_bgp_peers.return_value = []

        with self.assertRaisesRegex(ValueError, "expected 1 peer object"):
            self.ixia.start_bgp_peers(
                start=False,
                regex="IPV4_EBGP",
                expected_peer_count=1,
            )

        self.peer.Stop.assert_not_called()

    def test_range_validation_rejects_out_of_bounds_end(self) -> None:
        with self.assertRaisesRegex(ValueError, "1-141"):
            self.ixia.start_bgp_peers(
                start=False,
                regex="IPV4_EBGP",
                session_start_idx=1,
                session_end_idx=141,
                expected_peer_count=1,
                validate_session_range=True,
            )

        self.peer.Stop.assert_not_called()

    def test_restore_peer_ranges_attempts_every_target_before_raising(self) -> None:
        logger = MagicMock()
        self.ixia.logger = logger
        self.ixia.start_bgp_peers = MagicMock(
            side_effect=(RuntimeError("IPv4 restore failed"), None)
        )
        targets = (
            {
                "label": "IPv4",
                "regex": "IPV4_EBGP",
                "session_start_idx": 1,
                "session_end_idx": 11,
                "expected_peer_count": 1,
            },
            {
                "label": "IPv6",
                "regex": "IPV6_EBGP",
                "session_start_idx": 1,
                "session_end_idx": 11,
                "expected_peer_count": 1,
            },
        )

        with self.assertRaisesRegex(
            RuntimeError, "IPv4 restore failed"
        ) as raised_error:
            self.ixia.restore_bgp_peer_ranges(targets)

        self.assertIn("succeeded=['IPv6']", str(raised_error.exception))
        self.assertIn("failed=IPv4: RuntimeError", str(raised_error.exception))
        self.assertEqual(2, self.ixia.start_bgp_peers.call_count)
        second_call = self.ixia.start_bgp_peers.call_args_list[1]
        self.assertEqual("IPV6_EBGP", second_call.kwargs["regex"])
        logger.exception.assert_called_once_with(
            "Failed to restore BGP peer range IPv4"
        )

    def test_restore_peer_ranges_starts_every_target(self) -> None:
        self.ixia.start_bgp_peers = MagicMock()

        self.ixia.restore_bgp_peer_ranges(
            (
                {
                    "label": "IPv4",
                    "regex": "IPV4_EBGP",
                    "session_start_idx": 1,
                    "session_end_idx": 11,
                    "expected_peer_count": 1,
                },
                {
                    "label": "IPv6",
                    "regex": "IPV6_EBGP",
                    "session_start_idx": 1,
                    "session_end_idx": 11,
                    "expected_peer_count": 1,
                },
            )
        )

        self.assertEqual(2, self.ixia.start_bgp_peers.call_count)
