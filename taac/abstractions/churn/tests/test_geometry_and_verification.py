# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""Behavioral contracts for device-independent churn calculations."""

from __future__ import annotations

import unittest

from taac.abstractions.churn.geometry import (
    comparison_peers,
    sample_prefix_range,
    select_uniform_rows,
    topology_prefix_at,
)
from taac.abstractions.churn.observations import (
    BaselineObservation,
    Block,
    Counters,
    RouteState,
)
from taac.abstractions.churn.verification import (
    counter_delta,
    quiet_update_violation,
    routes_match_baseline,
    session_baseline_violation,
    transition_best_peer,
    verify_preferred_path,
    verify_route_attributes,
)


def _counters(*, uptime: int = 10, recv4: int = 1) -> Counters:
    return Counters(
        state="established",
        reset_time=None,
        uptime=uptime,
        resets=0,
        flaps=0,
        recv4=recv4,
        recv6=2,
        recv_withdrawals=0,
        sent4=3,
        sent6=4,
        sent_withdrawals=0,
        recv_update_msgs=5,
    )


class ChurnGeometryAndVerificationTest(unittest.TestCase):
    def test_uniform_rows_include_both_boundaries(self) -> None:
        self.assertEqual((0, 10, 20, 30, 40, 50, 61), select_uniform_rows(62, 7))

    def test_prefix_sampling_uses_concrete_endpoints(self) -> None:
        self.assertEqual(
            ("10.0.0.0/24", "10.2.237.0/24"),
            sample_prefix_range(
                "10.0.0.0",
                24,
                route_count=750,
                sample_count=2,
            ),
        )

    def test_topology_prefix_skips_excluded_candidates(self) -> None:
        self.assertEqual(
            "10.0.3.0",
            topology_prefix_at(
                start_prefix="10.0.0.0",
                prefix_step=256,
                count=4,
                excluded_indices=(1, 2),
                row=1,
            ),
        )

    def test_comparison_peers_requires_four_distinct_planes(self) -> None:
        blocks = tuple(
            Block("ipv4", plane, 0, f"pool{plane}", f"peer{plane}", ("10/8",))
            for plane in range(1, 5)
        )
        self.assertEqual(
            ("peer1", frozenset({"peer2", "peer3", "peer4"})),
            comparison_peers(blocks)["10/8"],
        )

    def test_route_and_counter_comparisons_are_pure(self) -> None:
        before = _counters()
        after = _counters(uptime=11, recv4=2)
        self.assertEqual(1, counter_delta(before, after)["recv4"])
        self.assertIsNone(session_baseline_violation({"peer": before}, {"peer": after}))
        self.assertEqual(
            "peer", quiet_update_violation({"peer": before}, {"peer": after})
        )

        route = RouteState(1, False, ("peer",), {"peer": {"med": 100}})
        self.assertTrue(routes_match_baseline({"10/8": route}, {"10/8": route}))
        self.assertFalse(routes_match_baseline({"10/8": route}, {}))

    def test_baseline_observation_contains_only_device_independent_state(self) -> None:
        route = RouteState(1, False, ("peer",), {"peer": {"med": 100}})
        baseline = BaselineObservation(
            blocks=(Block("ipv4", 1, 0, "pool", "peer", ("10/8",)),),
            sessions={"peer": _counters()},
            rib_version=1,
            routes={"10/8": route},
            established_session_peers=frozenset({"peer"}),
        )

        self.assertEqual(("10/8",), baseline.blocks[0].prefixes)
        self.assertEqual(frozenset({"peer"}), baseline.established_session_peers)

    def test_transition_helpers_validate_best_path_and_attributes(self) -> None:
        before = RouteState(1, False, ("peer2",), {"peer1": {"med": 200}})
        after = RouteState(2, False, ("peer1",), {"peer1": {"med": 100}})
        block = Block("ipv4", 1, 0, "pool", "peer1", ("10/8",))

        best_peer = transition_best_peer(
            prefix="10/8",
            before=before,
            after=after,
            expected_peers={"peer1", "peer2"},
            should_advance=True,
        )
        verify_preferred_path(
            prefix="10/8",
            best_peer=best_peer,
            plane1_peer="peer1",
            reference_peers={"peer2"},
            family="med",
            preferred=True,
        )
        verify_route_attributes(
            blocks=(block,),
            routes={"10/8": after},
            family="med",
            expected=100,
            planes={1},
        )

    def test_transition_helpers_reject_stale_or_unexpected_paths(self) -> None:
        before = RouteState(2, False, ("peer2",), {})
        stale = RouteState(2, False, ("peer3",), {})

        with self.assertRaisesRegex(ValueError, "RIB version did not advance"):
            transition_best_peer(
                prefix="10/8",
                before=before,
                after=stale,
                expected_peers={"peer3"},
                should_advance=True,
            )

        with self.assertRaisesRegex(ValueError, "plane 1 remained best"):
            verify_preferred_path(
                prefix="10/8",
                best_peer="peer1",
                plane1_peer="peer1",
                reference_peers={"peer2"},
                family="med",
                preferred=False,
            )
