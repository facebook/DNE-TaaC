# Copyright (c) Meta Platforms, Inc. and affiliates.

"""IXIA ``SessionIndices`` are 1-based: index 0 is not a valid session.

Sending a range that starts at 0 does not error at the API. It leaves an
IxNetwork-internal lock unreleased, wedging the session so the NEXT substantial
operation stalls to the 600s Jetty ceiling and returns 504 Gateway Timeout --
observed ~10 minutes and several unrelated calls after the offending stop, which
is why it was expensive to attribute.

These tests pin both halves of that contract:
  - the payload actually put on the wire for a given index range, and
  - the guards that reject an out-of-contract range before it reaches the
    chassis.
"""

from unittest.mock import MagicMock, patch

import later.unittest
from taac.ixia.ixia import Ixia


class _BgpPeer:
    """Minimal stand-in for a restpy bgpIpvXPeer object."""

    def __init__(self, name: str = "BGP_PEER_IPV6_EBGP", count: int = 140) -> None:
        self.Name = name
        self.Count = count
        self.start_calls: list[str] = []
        self.stop_calls: list[str] = []

    def Start(self, SessionIndices: str) -> None:  # noqa: N803 - restpy casing
        self.start_calls.append(SessionIndices)

    def Stop(self, SessionIndices: str) -> None:  # noqa: N803 - restpy casing
        self.stop_calls.append(SessionIndices)


class _RouteProperty:
    """Minimal stand-in for a restpy BgpIPRouteProperty object."""

    def __init__(self, count: int) -> None:
        self.Count = count
        self.start_calls: list[str] = []
        self.stop_calls: list[str] = []

    def Start(self, SessionIndices: str) -> None:  # noqa: N803 - restpy casing
        self.start_calls.append(SessionIndices)

    def Stop(self, SessionIndices: str) -> None:  # noqa: N803 - restpy casing
        self.stop_calls.append(SessionIndices)


class _PrefixPool:
    """Minimal stand-in for an Ipv6PrefixPools object.

    Not an ``Ipv4PrefixPools``, so ``configure_bgp_prefixes`` takes the v6
    branch and reads ``BgpV6IPRouteProperty``.
    """

    def __init__(self, count: int) -> None:
        self.Name = "PREFIX_POOL"
        self.route_property = _RouteProperty(count)
        self.BgpV6IPRouteProperty = MagicMock()
        self.BgpV6IPRouteProperty.find.return_value = [self.route_property]


def _ixia_with_pools(pools: list[_PrefixPool]) -> tuple[Ixia, MagicMock]:
    with patch.object(Ixia, "__init__", lambda self: None):
        ixia = Ixia()
    ixia.logger = MagicMock()
    get_pools = MagicMock(return_value=pools)
    ixia.get_prefix_pools_by_regexes = get_pools
    ixia.apply_changes = MagicMock()
    return ixia, get_pools


def _ixia(peers: list[_BgpPeer]) -> Ixia:
    with patch.object(Ixia, "__init__", lambda self: None):
        ixia = Ixia()
    ixia.logger = MagicMock()
    ixia.find_bgp_peers = MagicMock(return_value=peers)
    return ixia


class BgpSessionIndicesTest(later.unittest.TestCase):
    def test_stop_sends_one_based_range(self) -> None:
        """UG 2.2.1 stops 64 sessions; the wire payload must read "1-64"."""
        peer = _BgpPeer()
        ixia = _ixia([peer])

        ixia.start_bgp_peers(
            start=False, regex=".*", session_start_idx=1, session_end_idx=64
        )

        self.assertEqual(["1-64"], peer.stop_calls)
        self.assertEqual([], peer.start_calls)

    def test_start_sends_one_based_range(self) -> None:
        peer = _BgpPeer()
        ixia = _ixia([peer])

        ixia.start_bgp_peers(
            start=True, regex=".*", session_start_idx=1, session_end_idx=32
        )

        self.assertEqual(["1-32"], peer.start_calls)
        self.assertEqual([], peer.stop_calls)

    def test_zero_start_index_is_rejected_before_the_chassis(self) -> None:
        """The 0-based form that wedged the session must never be sent."""
        peer = _BgpPeer()
        ixia = _ixia([peer])

        with self.assertRaises(ValueError) as ctx:
            ixia.start_bgp_peers(
                start=False, regex=".*", session_start_idx=0, session_end_idx=1
            )

        self.assertIn("1-based", str(ctx.exception))
        # The guard must fire BEFORE any call reaches the peer object.
        self.assertEqual([], peer.stop_calls)
        self.assertEqual([], peer.start_calls)

    def test_inverted_range_is_rejected(self) -> None:
        peer = _BgpPeer()
        ixia = _ixia([peer])

        with self.assertRaises(ValueError):
            ixia.start_bgp_peers(
                start=False, regex=".*", session_start_idx=10, session_end_idx=4
            )

        self.assertEqual([], peer.stop_calls)

    def test_end_index_defaults_per_peer_not_locked_to_the_first(self) -> None:
        """With session_end_idx=None each peer uses its OWN Count.

        Reassigning the caller's session_end_idx inside the loop would pin every
        subsequent peer to the first peer's Count, silently applying the wrong
        range across a multi-peer regex match (e.g. ".*" spanning v4 and v6
        peers with differing session counts).
        """
        v6 = _BgpPeer(name="BGP_PEER_IPV6_EBGP", count=140)
        v4 = _BgpPeer(name="BGP_PEER_IPV4_EBGP", count=70)
        ixia = _ixia([v6, v4])

        ixia.start_bgp_peers(start=False, regex=".*", session_start_idx=1)

        self.assertEqual(["1-140"], v6.stop_calls)
        self.assertEqual(["1-70"], v4.stop_calls)

    def test_configure_bgp_prefixes_rejects_zero_start_index(self) -> None:
        """The other SessionIndices producer carries the same guard."""
        ixia, get_pools = _ixia_with_pools([])

        with self.assertRaises(ValueError) as ctx:
            ixia.configure_bgp_prefixes(
                prefix_pool_regex=".*", enable=False, session_start_idx=0
            )

        self.assertIn("1-based", str(ctx.exception))
        # Rejected before any pool lookup or mutation is attempted.
        get_pools.assert_not_called()

    def test_configure_bgp_prefixes_rejects_inverted_range(self) -> None:
        """Both SessionIndices producers reject an inverted range.

        Guarding only start_bgp_peers would leave this entry point formatting
        the inverted range straight into SessionIndices and sending it.
        """
        ixia, get_pools = _ixia_with_pools([])

        with self.assertRaises(ValueError) as ctx:
            ixia.configure_bgp_prefixes(
                prefix_pool_regex=".*",
                enable=False,
                session_start_idx=10,
                session_end_idx=4,
            )

        self.assertIn("session_end_idx must be >=", str(ctx.exception))
        get_pools.assert_not_called()

    def test_configure_bgp_prefixes_end_index_defaults_per_pool(self) -> None:
        """With session_end_idx=None each pool uses its OWN Count.

        Assigning the resolved value back to session_end_idx would pin every
        later pool to the first pool's Count, so a multi-pool regex would send
        the wrong range to all but the first.
        """
        v6 = _PrefixPool(count=140)
        v4 = _PrefixPool(count=70)
        ixia, _ = _ixia_with_pools([v6, v4])

        ixia.configure_bgp_prefixes(prefix_pool_regex=".*", enable=False)

        self.assertEqual(["1-140"], v6.route_property.stop_calls)
        self.assertEqual(["1-70"], v4.route_property.stop_calls)
