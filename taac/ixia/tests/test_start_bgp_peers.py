# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe

import contextlib
import re
import typing as t
import unittest
from unittest.mock import MagicMock, patch

from taac.constants import TestCaseFailure
from taac.ixia.ixia import Ixia


def _ixia() -> Ixia:
    with patch.object(Ixia, "__init__", lambda self: None):
        instance = Ixia()
    instance.logger = MagicMock()
    return instance


class _ActiveVector:
    def __init__(
        self,
        values: list[object],
        *,
        count: int,
        events: list[str] | None = None,
        label: str = "",
    ) -> None:
        self.Count = count
        self.Values = list(values)
        self._events = events
        self._label = label
        self._properties: dict[str, object] = {}
        self._set_pattern("singleValue" if len(values) == 1 else "valueList")

    @property
    def Pattern(self) -> str:
        return str(self._properties["pattern"])

    def Single(self, value: object) -> None:
        self.Values = [value]
        self._set_pattern("singleValue")
        if self._events is not None:
            self._events.append(f"active:{self._label}")

    def ValueList(self, values: list[object]) -> None:
        self.Values = list(values)
        self._set_pattern("valueList")
        if self._events is not None:
            self._events.append(f"active:{self._label}")

    def _set_pattern(self, pattern: str) -> None:
        self._properties = {"pattern": pattern}
        if pattern == "singleValue":
            self._properties[pattern] = {"value": self.Values[0]}
        else:
            self._properties[pattern] = {"values": list(self.Values)}


def _peer(
    name: str,
    count: int,
    active_values: list[object] | None = None,
    events: list[str] | None = None,
) -> MagicMock:
    peer = MagicMock()
    peer.Name = name
    peer.Count = count
    peer.Active = _ActiveVector(
        active_values or ["true"], count=count, events=events, label=name
    )
    if events is not None:
        peer.Start.side_effect = lambda **_kwargs: events.append(f"start:{name}")
    return peer


class StartBgpPeersTest(unittest.TestCase):
    def setUp(self) -> None:
        self.ixia = _ixia()
        self.peer = _peer("IPV4_EBGP", 140)
        self.find_bgp_peers = MagicMock(return_value=[self.peer])
        self.ixia.find_bgp_peers = self.find_bgp_peers

    def _configure_restore_peers(self, peers: list[MagicMock]) -> None:
        def find(regex: str, _ignore_case: bool = False) -> list[MagicMock]:
            return [peer for peer in peers if re.search(regex, str(peer.Name))]

        self.ixia.find_bgp_peers = MagicMock(side_effect=find)
        self.ixia.mutation_transaction = MagicMock(side_effect=contextlib.nullcontext)
        self.apply_changes_bounded = MagicMock()
        self.ixia.apply_changes_bounded = self.apply_changes_bounded

    @staticmethod
    def _restore_targets(end: int = 4) -> tuple[dict[str, object], ...]:
        return (
            {
                "label": "IPv4",
                "regex": "IPV4_EBGP",
                "session_start_idx": 1,
                "session_end_idx": end,
                "expected_peer_count": 1,
            },
            {
                "label": "IPv6",
                "regex": "IPV6_EBGP",
                "session_start_idx": 1,
                "session_end_idx": end,
                "expected_peer_count": 1,
            },
        )

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
        events: list[str] = []
        ipv4 = _peer("IPV4_EBGP", 4, ["false"] * 4, events)
        ipv6 = _peer("IPV6_EBGP", 4, ["false"] * 4, events)
        ipv4.Start.side_effect = RuntimeError("IPv4 restore failed")
        self._configure_restore_peers([ipv4, ipv6])

        with self.assertRaisesRegex(
            RuntimeError, "IPv4 restore failed"
        ) as raised_error:
            self.ixia.restore_bgp_peer_ranges(self._restore_targets())

        self.assertIn("succeeded=['IPv6']", str(raised_error.exception))
        self.assertIn(
            "failed=IPv4/IPV4_EBGP: RuntimeError", str(raised_error.exception)
        )
        ipv4.Start.assert_called_once_with(SessionIndices="1-4")
        ipv6.Start.assert_called_once_with(SessionIndices="1-4")
        self.assertEqual(["true"], ipv4.Active.Values)
        self.assertEqual(["true"], ipv6.Active.Values)

    def test_restore_peer_ranges_applies_and_verifies_active_before_start(
        self,
    ) -> None:
        ipv4 = _peer("IPV4_EBGP", 4, ["false", "true", "false", "true"])
        ipv6 = _peer("IPV6_EBGP", 4, [False, True, False, True])
        self._configure_restore_peers([ipv4, ipv6])
        apply_completed = False
        verification_completed = False
        started: set[str] = set()

        def apply_changes(*_args: object, **_kwargs: object) -> None:
            nonlocal apply_completed
            self.assertEqual(["true"], ipv4.Active.Values)
            self.assertEqual([True], ipv6.Active.Values)
            apply_completed = True

        real_verify = self.ixia._verify_bgp_peer_active_baseline

        def verify_active(plans: t.Any) -> None:
            nonlocal verification_completed
            self.assertTrue(apply_completed)
            real_verify(plans)
            verification_completed = True

        def start(name: str) -> t.Callable[..., None]:
            def guarded_start(**_kwargs: object) -> None:
                self.assertTrue(
                    apply_completed,
                    "sessions must not start before Active changes are applied",
                )
                self.assertTrue(
                    verification_completed,
                    "sessions must not start before Active readback is verified",
                )
                self.assertEqual(["true"], ipv4.Active.Values)
                self.assertEqual([True], ipv6.Active.Values)
                started.add(name)

            return guarded_start

        self.apply_changes_bounded.side_effect = apply_changes
        ipv4.Start.side_effect = start("IPV4_EBGP")
        ipv6.Start.side_effect = start("IPV6_EBGP")

        with patch.object(
            self.ixia,
            "_verify_bgp_peer_active_baseline",
            side_effect=verify_active,
        ) as verify_active_mock:
            self.ixia.restore_bgp_peer_ranges(self._restore_targets())

        self.assertTrue(apply_completed)
        self.assertTrue(verification_completed)
        self.assertEqual({"IPV4_EBGP", "IPV6_EBGP"}, started)
        self.assertEqual(["true"], ipv4.Active.Values)
        self.assertEqual([True], ipv6.Active.Values)
        self.apply_changes_bounded.assert_called_once_with(
            60.0, abort_timeout_seconds=10.0
        )
        verify_active_mock.assert_called_once()

    def test_restore_peer_ranges_is_idempotent(self) -> None:
        ipv4 = _peer("IPV4_EBGP", 4, ["true"])
        ipv6 = _peer("IPV6_EBGP", 4, [True])
        self._configure_restore_peers([ipv4, ipv6])

        self.ixia.restore_bgp_peer_ranges(self._restore_targets())
        self.ixia.restore_bgp_peer_ranges(self._restore_targets())

        self.assertEqual(["true"], ipv4.Active.Values)
        self.assertEqual([True], ipv6.Active.Values)
        self.assertEqual(2, ipv4.Start.call_count)
        self.assertEqual(2, ipv6.Start.call_count)
        self.assertEqual(2, self.apply_changes_bounded.call_count)

    def test_restore_peer_ranges_validates_all_targets_before_writing(self) -> None:
        ipv4 = _peer("IPV4_EBGP", 4, ["false"] * 4)
        ipv6 = _peer("IPV6_EBGP", 3, ["false"] * 3)
        self._configure_restore_peers([ipv4, ipv6])

        with self.assertRaisesRegex(ValueError, "1-4"):
            self.ixia.restore_bgp_peer_ranges(self._restore_targets())

        self.assertEqual(["false"] * 4, ipv4.Active.Values)
        self.apply_changes_bounded.assert_not_called()
        ipv4.Start.assert_not_called()
        ipv6.Start.assert_not_called()

    def test_restore_peer_ranges_rejects_partial_activation(self) -> None:
        ipv4 = _peer("IPV4_EBGP", 4, ["false", "true", "false", "true"])
        ipv6 = _peer("IPV6_EBGP", 4, [False, True, False, True])
        self._configure_restore_peers([ipv4, ipv6])

        with self.assertRaisesRegex(ValueError, "complete session range 1-4"):
            self.ixia.restore_bgp_peer_ranges(self._restore_targets(end=3))

        self.assertEqual(["false", "true", "false", "true"], ipv4.Active.Values)
        self.assertEqual([False, True, False, True], ipv6.Active.Values)
        self.apply_changes_bounded.assert_not_called()
        ipv4.Start.assert_not_called()
        ipv6.Start.assert_not_called()

    def test_restore_peer_ranges_rolls_back_failed_readback(self) -> None:
        ipv4 = _peer("IPV4_EBGP", 4, ["false", "true", "false", "true"])
        ipv6 = _peer("IPV6_EBGP", 4, ["false", "true", "false", "true"])
        self._configure_restore_peers([ipv4, ipv6])
        apply_calls = 0

        def corrupt_first_apply(*_args: object, **_kwargs: object) -> None:
            nonlocal apply_calls
            apply_calls += 1
            if apply_calls == 1:
                ipv4.Active.ValueList(["false"] * 4)

        self.apply_changes_bounded.side_effect = corrupt_first_apply

        with self.assertRaisesRegex(TestCaseFailure, "readback"):
            self.ixia.restore_bgp_peer_ranges(self._restore_targets())

        self.assertEqual(["false", "true", "false", "true"], ipv4.Active.Values)
        self.assertEqual(["false", "true", "false", "true"], ipv6.Active.Values)
        self.assertEqual(2, apply_calls)
        ipv4.Start.assert_not_called()
        ipv6.Start.assert_not_called()
