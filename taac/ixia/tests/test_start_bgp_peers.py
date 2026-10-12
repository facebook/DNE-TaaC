# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe

import contextlib
import itertools
import re
import typing as t
import unittest
from types import SimpleNamespace
from unittest.mock import call, MagicMock, patch

from taac.constants import TestCaseFailure
from taac.ixia.ixia import (
    _bgp_session_indices_spec,
    Ixia,
    IxiaOperationStateError,
)


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


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class StartBgpPeersVerifyStartedTest(unittest.TestCase):
    def setUp(self) -> None:
        self.ixia = _ixia()
        self.peer = _peer("BGP_PEER_IPV6_IBGP", 5)
        self.ixia.find_bgp_peers = MagicMock(return_value=[self.peer])
        self.clock = _FakeClock()
        patcher = patch(
            "neteng.test_infra.dne.taac.ixia.ixia.time",
            MagicMock(monotonic=self.clock.monotonic, sleep=self.clock.sleep),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _set_statuses(self, *reads: list[str]) -> None:
        # Like restpy, SessionStatus only changes when refresh() re-fetches it;
        # the cached value is the pre-Start snapshot.
        fresh = itertools.chain(reads, itertools.repeat(reads[-1]))
        self.peer.SessionStatus = ["notStarted"] * len(reads[0])

        def refresh() -> MagicMock:
            self.peer.SessionStatus = next(fresh)
            return self.peer

        self.peer.refresh.side_effect = refresh

    def _start(self, end: int = 5) -> None:
        self.ixia.start_bgp_peers(
            start=True,
            regex="BGP_PEER_IPV6_IBGP",
            session_start_idx=1,
            session_end_idx=end,
            verify_started=True,
        )

    def test_started_sessions_need_no_retry(self) -> None:
        self._set_statuses(["up", "down", "up", "down", "notStarted"])

        self._start(end=4)

        self.peer.Start.assert_called_once_with(SessionIndices="1-4")
        self.assertEqual([], self.clock.sleeps)

    def test_restarts_only_sessions_still_not_started(self) -> None:
        stuck = ["up", "notStarted", "notStarted", "up", "notStarted"]
        self._set_statuses(*([stuck] * 6), ["up"] * 5)

        self._start()

        self.assertEqual(
            [call(SessionIndices="1-5"), call(SessionIndices="2-3;5")],
            self.peer.Start.call_args_list,
        )

    def test_raises_with_diagnostics_when_sessions_never_start(self) -> None:
        self._set_statuses(["up", "notStarted", "up", "up", "up"])
        self.peer.SessionInfo = ["none", "ceaseErrorRx", "none", "none", "none"]
        self.peer.Active = _ActiveVector(
            ["true", "false", "true", "true", "true"], count=5
        )

        with self.assertRaises(IxiaOperationStateError) as raised:
            self._start()

        message = str(raised.exception)
        self.assertIn("BGP_PEER_IPV6_IBGP: 1 notStarted [2]", message)
        self.assertIn("Ixia server errors: [", message)
        self.assertIn("SessionInfo={'ceaseErrorRx': 1}", message)
        self.assertIn("inactive=[2]", message)
        self.assertEqual(3, self.peer.Start.call_count)

    def test_rejects_range_beyond_reported_sessions(self) -> None:
        self._set_statuses(["up"] * 3)

        with self.assertRaisesRegex(ValueError, "reports 3 session"):
            self._start(end=5)

    def test_stop_does_not_read_session_status(self) -> None:
        self.ixia.start_bgp_peers(
            start=False, regex="BGP_PEER_IPV6_IBGP", session_end_idx=5
        )

        self.peer.refresh.assert_not_called()

    def test_session_indices_spec_merges_contiguous_runs(self) -> None:
        self.assertEqual(
            "1-3;6-8;10", _bgp_session_indices_spec([7, 1, 2, 10, 3, 6, 8])
        )

    def _set_server_errors(self, *errors: SimpleNamespace) -> None:
        app_errors = MagicMock()
        app_errors.find.return_value.Error.find.return_value = list(errors)
        self.ixia.ixnetwork = MagicMock()
        self.ixia.ixnetwork.Globals.AppErrors = app_errors

    def test_failure_quotes_latest_server_errors_only(self) -> None:
        self._set_statuses(["notStarted"] * 5)
        self._set_server_errors(
            SimpleNamespace(
                LastModified="03:01:47",
                ErrorLevel="kError",
                Name="Download of package(s) failed",
                Description="Port 1;90 is not CPU ready.",
            ),
            SimpleNamespace(
                LastModified="03:01:12",
                ErrorLevel="kWarning",
                Name="PCPU errors on the chassis",
                Description="Port CPU errors detected.",
            ),
            SimpleNamespace(
                LastModified="03:02:00",
                ErrorLevel="kMessage",
                Name="informational",
                Description="ignored",
            ),
        )

        with self.assertRaises(IxiaOperationStateError) as raised:
            self._start()

        message = str(raised.exception)
        self.assertIn("Port 1;90 is not CPU ready.", message)
        self.assertNotIn("informational", message)
        self.assertLess(message.index("PCPU errors"), message.index("not CPU ready"))

    def test_failure_survives_unreadable_server_errors(self) -> None:
        self._set_statuses(["notStarted"] * 5)
        self.ixia.ixnetwork = MagicMock()
        self.ixia.ixnetwork.Globals.AppErrors.find.side_effect = RuntimeError(
            "gateway timeout"
        )

        with self.assertRaisesRegex(
            IxiaOperationStateError,
            r"Ixia server errors: \['unavailable \(RuntimeError: gateway timeout\)'\]",
        ):
            self._start()
