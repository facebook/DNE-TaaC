# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""Unit tests for the carved drain-pool peer count.

Locks the derived constant against accidental drift (changing
`EBGP_PEER_TO_DRAIN`, `IBGP_PEER_TO_DRAIN_PER_PLANE`, or
`IBGP_DC_PLANE_COUNT` would silently change `DRAIN_POOL_PEER_COUNT` and
re-break the `BGP_SESSION_ESTABLISH_CHECK` precheck on drain
testconfigs). See paste P2391197932 for the original investigation.
"""

import unittest

from taac.routing.ebb.ebb_bgp_plus_plus_test_config.ebb_bgp_plus_plus_conveyor.conveyor_constants import (
    DRAIN_POOL_PEER_COUNT,
    EBGP_PEER_TO_DRAIN,
    IBGP_DC_PLANE_COUNT,
    IBGP_PEER_TO_DRAIN_PER_PLANE,
)


class DrainPoolPeerCountTest(unittest.TestCase):
    def test_drain_pool_peer_count_is_24(self):
        """Locks the value reported by the live BAG010 Drain precheck
        failure (`24/1272 IDLE`) — see paste P2391197932 §2.1."""
        self.assertEqual(DRAIN_POOL_PEER_COUNT, 24)

    def test_drain_pool_peer_count_formula_matches_inputs(self):
        """Locks the formula. If any of the three inputs change, this
        test forces the reviewer to (a) verify the topology builder in
        ``ixia_config_for_ebb_scale.py`` still matches and (b) update
        any testconfig that hard-codes the drain-aware expected count."""
        expected = (
            EBGP_PEER_TO_DRAIN * 2  # V4 + V6 eBGP DRAIN DGs
            + IBGP_PEER_TO_DRAIN_PER_PLANE * IBGP_DC_PLANE_COUNT * 2
        )
        self.assertEqual(DRAIN_POOL_PEER_COUNT, expected)

    def test_input_constants_match_topology_assumptions(self):
        """Regression-guards the three input constants individually.

        These match the ``drain=True`` branches of
        ``ixia_config_for_ebb_scale.py`` (lines 115-160 V6 iBGP DC DRAIN,
        245-290 V4 iBGP DC DRAIN, 558-590 V6 eBGP DRAIN,
        656-690 V4 eBGP DRAIN — only DC planes have DRAIN variants, MP
        planes don't)."""
        self.assertEqual(EBGP_PEER_TO_DRAIN, 4)
        self.assertEqual(IBGP_PEER_TO_DRAIN_PER_PLANE, 2)
        self.assertEqual(IBGP_DC_PLANE_COUNT, 4)
