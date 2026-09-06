# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-strict

import logging
import threading
import time
import typing as t
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from taac.ixia.ixia import (
    Ixia,
    IxiaOperationStateError,
    IxiaOperationTimeoutError,
    IxiaScenarioQuarantineRecord,
    IxiaSessionQuarantinedError,
    IxnIxNetworkError,
    UhdIxNetworkError,
)
from requests.exceptions import ConnectionError as RequestsConnectionError, ReadTimeout


class _CountingTransport:
    def __init__(self, request: t.Callable[..., object]) -> None:
        self._request = request
        self._counter_lock = threading.Lock()
        self.request_reads = 0
        self.request_writes = 0

    @property
    def request(self) -> t.Callable[..., object]:
        with self._counter_lock:
            self.request_reads += 1
        time.sleep(0.01)
        return self._request

    @request.setter
    def request(self, request: t.Callable[..., object]) -> None:
        with self._counter_lock:
            self.request_writes += 1
            self._request = request


class ApplyChangesTimeoutTest(unittest.TestCase):
    def setUp(self) -> None:
        with patch.object(Ixia, "__init__", lambda self: None):
            self.ixia = Ixia()
        self.ixia.logger = logging.getLogger(__name__)
        self.ixia._request_deadline_state = threading.local()
        self.ixia._request_deadline_wrapper_lock = threading.Lock()
        self.ixia._bounded_apply_lock = threading.RLock()
        self.ixia._session_quarantine_reason = None
        self.ixia._quarantined_session_identity = None
        self.ixia._scenario_quarantine_generation = 0
        self.ixia._scenario_quarantine_record = None
        self.ixia.primary_chassis_ip = "::1"
        self.request = MagicMock(return_value=object())
        self.transport = SimpleNamespace(request=self.request)
        connection = SimpleNamespace(_session=self.transport)
        test_platform = SimpleNamespace(_connection=connection)
        self.ixia.session = t.cast(
            t.Any,
            SimpleNamespace(
                Session=SimpleNamespace(Id=17, Name="old-session"),
                TestPlatform=test_platform,
            ),
        )
        self.topology = MagicMock()
        self.ixia.ixnetwork = t.cast(
            t.Any,
            SimpleNamespace(Globals=SimpleNamespace(Topology=self.topology)),
        )

        def apply() -> None:
            self.transport.request("POST", "https://ixia/apply")

        def abort() -> None:
            self.transport.request("POST", "https://ixia/abort")

        self.topology.ApplyOnTheFly.side_effect = apply
        self.topology.AbortApplyOnTheFly.side_effect = abort

    def _timeout_request(self, *_args: object, **kwargs: object) -> object:
        timeout = t.cast(float, kwargs["timeout"])
        time.sleep(timeout)
        raise TimeoutError("server did not reply")

    def test_success_applies_remaining_request_timeout(self) -> None:
        self.ixia.apply_changes_bounded(1.0)

        timeout = self.request.call_args.kwargs["timeout"]
        self.assertGreater(timeout, 0)
        self.assertLessEqual(timeout, 1.0)
        self.topology.ApplyOnTheFly.assert_called_once_with()
        self.topology.AbortApplyOnTheFly.assert_not_called()
        self.assertFalse(self.ixia.session_quarantined)

    def test_scenario_quarantine_owns_recovery_state_and_blocks_mutation(self) -> None:
        baseline = object()
        journal = (("med", "started"),)

        record = self.ixia.quarantine_scenario(
            "restore could not be verified",
            baseline,
            journal,
            time.monotonic() + 60.0,
        )

        self.assertIsInstance(record, IxiaScenarioQuarantineRecord)
        self.assertIs(baseline, record.baseline)
        self.assertIs(journal, record.mutation_journal)
        self.assertIs(record, self.ixia.scenario_quarantine_record)
        with self.assertRaisesRegex(IxiaSessionQuarantinedError, "unverified churn"):
            self.ixia.apply_changes_bounded(1.0)
        with self.assertRaisesRegex(IxiaSessionQuarantinedError, "unverified churn"):
            self.ixia.apply_changes()
        self.topology.ApplyOnTheFly.assert_not_called()

    def test_expired_scenario_quarantine_remains_fail_closed(self) -> None:
        now = 10.0
        with patch(
            "neteng.test_infra.dne.taac.ixia.ixia.time.monotonic",
            side_effect=lambda: now,
        ):
            self.ixia.quarantine_scenario("unverified", object(), (), 15.0)
            now = 20.0
            with self.assertRaisesRegex(
                IxiaSessionQuarantinedError, "expired; explicit recovery"
            ):
                self.ixia.assert_session_not_quarantined()

    def test_verified_same_session_recovery_clears_quarantine(self) -> None:
        record = self.ixia.quarantine_scenario(
            "unverified", object(), (), time.monotonic() + 60.0
        )

        self.ixia.reset_scenario_quarantine(
            record.generation, restoration_verified=True
        )

        self.assertFalse(self.ixia.session_quarantined)
        self.assertIsNone(self.ixia.scenario_quarantine_record)

    def test_scenario_reset_preserves_existing_session_quarantine(self) -> None:
        self.ixia._quarantine_session("ambiguous apply")
        record = self.ixia.quarantine_scenario(
            "unverified", object(), (), time.monotonic() + 60.0
        )

        self.ixia.reset_scenario_quarantine(
            record.generation, restoration_verified=True
        )

        self.assertIsNone(self.ixia.scenario_quarantine_record)
        with self.assertRaisesRegex(IxiaSessionQuarantinedError, "ambiguous apply"):
            self.ixia.assert_session_not_quarantined()

    def test_unknown_session_identity_cannot_verify_recovery(self) -> None:
        self.ixia.session.Session.Id = None
        record = self.ixia.quarantine_scenario(
            "unverified", object(), (), time.monotonic() + 60.0
        )

        with self.assertRaisesRegex(
            IxiaSessionQuarantinedError, "requires verified restoration"
        ):
            self.ixia.reset_scenario_quarantine(
                record.generation, restoration_verified=True
            )

    def test_legacy_apply_does_not_retry_quarantine_precondition(self) -> None:
        self.ixia._quarantine_session("ambiguous apply")

        with (
            patch(
                "neteng.test_infra.dne.taac.utils.oss_taac_lib_utils.time.sleep"
            ) as retry_sleep,
            self.assertRaisesRegex(IxiaSessionQuarantinedError, "ambiguous apply"),
        ):
            self.ixia.apply_changes()

        retry_sleep.assert_not_called()
        self.topology.ApplyOnTheFly.assert_not_called()

    def test_legacy_apply_releases_mutation_lock_during_retry_delay(self) -> None:
        lock_acquired_during_backoff = threading.Event()

        def acquire_mutation_lock() -> None:
            with self.ixia.mutation_transaction():
                lock_acquired_during_backoff.set()

        def verify_lock_is_released(delay_seconds: float) -> None:
            if delay_seconds == 0:
                return
            contender = threading.Thread(target=acquire_mutation_lock)
            contender.start()
            self.assertTrue(lock_acquired_during_backoff.wait(timeout=1.0))
            contender.join(timeout=1.0)
            self.assertFalse(contender.is_alive())

        self.topology.ApplyOnTheFly.side_effect = [RuntimeError("transient"), None]
        with patch(
            "neteng.test_infra.dne.taac.ixia.ixia.time.sleep",
            side_effect=verify_lock_is_released,
        ):
            self.ixia.apply_changes()

        self.assertEqual(2, self.topology.ApplyOnTheFly.call_count)

    def test_new_session_requires_explicit_reset_before_mutation(self) -> None:
        record = self.ixia.quarantine_scenario(
            "unverified", object(), (), time.monotonic() + 60.0
        )
        self.ixia.session.Session.Id = 18

        with self.assertRaises(IxiaSessionQuarantinedError):
            self.ixia.assert_session_not_quarantined()
        self.ixia.reset_scenario_quarantine(record.generation, session_reset=True)

        self.ixia.assert_session_not_quarantined()

    def test_quarantine_generation_fences_stale_recovery(self) -> None:
        first = self.ixia.quarantine_scenario(
            "first", object(), (), time.monotonic() + 60.0
        )
        second = self.ixia.quarantine_scenario(
            "second", object(), (), time.monotonic() + 60.0
        )

        with self.assertRaisesRegex(IxiaSessionQuarantinedError, "generation changed"):
            self.ixia.reset_scenario_quarantine(
                first.generation, restoration_verified=True
            )
        self.assertEqual(second, self.ixia.scenario_quarantine_record)

    def test_timeout_aborts_once_without_retrying_apply(self) -> None:
        def timeout_then_succeed(*args: object, **kwargs: object) -> object:
            if self.request.call_count == 1:
                return self._timeout_request(*args, **kwargs)
            return object()

        self.request.side_effect = timeout_then_succeed

        with self.assertRaises(IxiaOperationTimeoutError) as context:
            self.ixia.apply_changes_bounded(0.01, abort_timeout_seconds=0.1)

        self.topology.ApplyOnTheFly.assert_called_once_with()
        self.topology.AbortApplyOnTheFly.assert_called_once_with()
        self.assertFalse(self.ixia.session_quarantined)
        self.assertIn(
            "AbortApplyOnTheFly acknowledged",
            " ".join(getattr(context.exception, "__notes__", ())),
        )
        self.assertTrue(context.exception.deadline_expired)

    def test_early_transport_timeout_uses_abort_path(self) -> None:
        self.request.side_effect = [ReadTimeout("early read timeout"), object()]

        with self.assertRaises(IxiaOperationTimeoutError) as context:
            self.ixia.apply_changes_bounded(1.0, abort_timeout_seconds=0.1)

        self.topology.ApplyOnTheFly.assert_called_once_with()
        self.topology.AbortApplyOnTheFly.assert_called_once_with()
        self.assertFalse(self.ixia.session_quarantined)
        self.assertIsInstance(context.exception.__cause__, ReadTimeout)
        self.assertFalse(context.exception.deadline_expired)

    def test_early_timeout_provenance_survives_slow_abort(self) -> None:
        now = 0.0

        def early_then_slow_abort(*_args: object, **_kwargs: object) -> object:
            nonlocal now
            if self.request.call_count == 1:
                raise ReadTimeout("early read timeout")
            now = 20.0
            return object()

        self.request.side_effect = early_then_slow_abort

        with (
            patch(
                "neteng.test_infra.dne.taac.ixia.ixia.time.monotonic",
                side_effect=lambda: now,
            ),
            self.assertRaises(IxiaOperationTimeoutError) as context,
        ):
            self.ixia.apply_changes_bounded(10.0, abort_timeout_seconds=100.0)

        self.topology.ApplyOnTheFly.assert_called_once_with()
        self.topology.AbortApplyOnTheFly.assert_called_once_with()
        self.assertFalse(context.exception.deadline_expired)

    def test_reinstalled_wrapper_preserves_inner_timeout_provenance(self) -> None:
        now = 0.0
        self.request.side_effect = [ReadTimeout("early read timeout"), object()]
        self.ixia._install_request_deadline_wrapper()
        inner_request = self.transport.request

        def middleware(*args: object, **kwargs: object) -> object:
            nonlocal now
            try:
                return inner_request(*args, **kwargs)
            except IxiaOperationTimeoutError:
                now = 20.0
                raise

        self.transport.request = middleware

        with (
            patch(
                "neteng.test_infra.dne.taac.ixia.ixia.time.monotonic",
                side_effect=lambda: now,
            ),
            self.assertRaises(IxiaOperationTimeoutError) as context,
        ):
            self.ixia.apply_changes_bounded(10.0, abort_timeout_seconds=100.0)

        self.topology.ApplyOnTheFly.assert_called_once_with()
        self.topology.AbortApplyOnTheFly.assert_called_once_with()
        self.assertFalse(context.exception.deadline_expired)

    def test_nested_deadline_cannot_extend_outer_budget(self) -> None:
        with self.ixia.request_deadline(0.1, "outer"):
            outer_deadline = self.ixia._request_deadline_state.deadline
            with self.ixia.request_deadline(10.0, "inner"):
                self.assertEqual(
                    outer_deadline, self.ixia._request_deadline_state.deadline
                )
                self.assertEqual("outer", self.ixia._request_deadline_state.phase)

    def test_mutation_transaction_allows_nested_bounded_apply(self) -> None:
        with self.ixia.mutation_transaction():
            self.ixia.apply_changes_bounded(1.0)

        self.topology.ApplyOnTheFly.assert_called_once_with()

    def test_mutation_transaction_serializes_same_session_writers(self) -> None:
        first_entered = threading.Event()
        release_first = threading.Event()
        second_entered = threading.Event()

        def first_writer() -> None:
            with self.ixia.mutation_transaction():
                first_entered.set()
                release_first.wait(timeout=1.0)

        def second_writer() -> None:
            with self.ixia.mutation_transaction():
                second_entered.set()

        first = threading.Thread(target=first_writer)
        second = threading.Thread(target=second_writer)
        first.start()
        self.assertTrue(first_entered.wait(timeout=1.0))
        second.start()
        self.assertFalse(second_entered.wait(timeout=0.05))
        release_first.set()
        first.join()
        second.join()

        self.assertTrue(second_entered.is_set())

    def test_deadline_cleanup_does_not_mask_body_error_after_state_loss(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "operation body failed"):
            with self.ixia.request_deadline(1.0, "body"):
                del self.ixia._request_deadline_state.deadline
                del self.ixia._request_deadline_state.phase
                raise RuntimeError("operation body failed")

    def test_existing_request_timeout_is_never_extended(self) -> None:
        with self.ixia.request_deadline(1.0, "bounded"):
            self.transport.request("GET", "https://ixia/numeric", timeout=0.25)
            numeric_timeout = self.request.call_args.kwargs["timeout"]
            self.transport.request("GET", "https://ixia/tuple", timeout=(0.25, 2.0))
            tuple_timeout = self.request.call_args.kwargs["timeout"]

        self.assertEqual(0.25, numeric_timeout)
        self.assertEqual(0.25, tuple_timeout[0])
        self.assertGreater(tuple_timeout[1], 0)
        self.assertLessEqual(tuple_timeout[1], 1.0)

    def test_wrapper_installation_is_atomic(self) -> None:
        transport = _CountingTransport(self.request)
        self.ixia.session.TestPlatform._connection._session = transport
        barrier = threading.Barrier(8)
        errors: list[Exception] = []

        def install() -> None:
            try:
                barrier.wait()
                self.ixia._install_request_deadline_wrapper()
            except Exception as error:
                errors.append(error)

        threads = [threading.Thread(target=install) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual([], errors)
        self.assertEqual(8, transport.request_reads)
        self.assertEqual(1, transport.request_writes)

    def test_reinstalls_wrapper_after_transport_request_replacement(self) -> None:
        self.ixia._install_request_deadline_wrapper()
        replacement = MagicMock(return_value=object())
        self.transport.request = replacement

        with self.ixia.request_deadline(1.0, "replacement"):
            self.transport.request("GET", "https://ixia/replacement")

        replacement.assert_called_once()
        timeout = replacement.call_args.kwargs["timeout"]
        self.assertGreater(timeout, 0)
        self.assertLessEqual(timeout, 1.0)

    def test_abort_has_independent_budget_after_outer_deadline_expires(self) -> None:
        now = 0.0

        def request(*_args: object, **_kwargs: object) -> object:
            nonlocal now
            if self.request.call_count == 1:
                now = 1.1
                raise ReadTimeout("apply consumed the outer deadline")
            return object()

        self.request.side_effect = request
        with (
            patch(
                "neteng.test_infra.dne.taac.ixia.ixia.time.monotonic",
                side_effect=lambda: now,
            ),
            self.ixia.request_deadline(1.0, "outer"),
            self.assertRaises(IxiaOperationTimeoutError) as context,
        ):
            self.ixia.apply_changes_bounded(1.0, abort_timeout_seconds=0.1)

        self.topology.AbortApplyOnTheFly.assert_called_once_with()
        self.assertFalse(self.ixia.session_quarantined)
        self.assertAlmostEqual(0.1, self.request.call_args.kwargs["timeout"])
        self.assertIn(
            "AbortApplyOnTheFly acknowledged",
            " ".join(getattr(context.exception, "__notes__", ())),
        )

    def test_failed_abort_quarantines_session_and_blocks_mutation(self) -> None:
        self.request.side_effect = self._timeout_request

        with self.assertRaises(IxiaOperationTimeoutError):
            self.ixia.apply_changes_bounded(0.01, abort_timeout_seconds=0.01)

        self.assertTrue(self.ixia.session_quarantined)
        self.assertEqual(1, self.topology.ApplyOnTheFly.call_count)
        self.assertEqual(1, self.topology.AbortApplyOnTheFly.call_count)
        with self.assertRaises(IxiaSessionQuarantinedError):
            self.ixia.apply_changes_bounded(1.0)
        self.assertEqual(1, self.topology.ApplyOnTheFly.call_count)

    def _replacement_assistant(
        self, *, session_id: int, session_name: str
    ) -> tuple[t.Any, MagicMock, MagicMock]:
        replacement_request = MagicMock(return_value=object())
        replacement_transport = SimpleNamespace(request=replacement_request)
        replacement_connection = SimpleNamespace(_session=replacement_transport)
        replacement_session = SimpleNamespace(
            Id=session_id,
            Name=session_name,
        )
        replacement_topology = MagicMock()

        def apply() -> None:
            replacement_transport.request("POST", "https://ixia/apply")

        replacement_topology.ApplyOnTheFly.side_effect = apply
        assistant = SimpleNamespace(
            Session=replacement_session,
            TestPlatform=SimpleNamespace(_connection=replacement_connection),
            Ixnetwork=SimpleNamespace(
                Globals=SimpleNamespace(Topology=replacement_topology)
            ),
        )
        return assistant, replacement_request, replacement_topology

    def _configure_connect(
        self, *, session_id: int | None, session_name: str | None
    ) -> None:
        self.ixia.session_id = session_id
        self.ixia.session_name = session_name
        self.ixia.cleanup_config = False
        self.ixia.is_existing_session = session_id is not None
        self.ixia.is_uhd_chassis = False
        self.ixia.username = "admin"
        self.ixia.password = "password"
        self.ixia.ApiKey = None

    def test_new_remote_session_clears_quarantine_after_wrapper_install(self) -> None:
        assistant, replacement_request, replacement_topology = (
            self._replacement_assistant(session_id=18, session_name="rebuilt-session")
        )
        self.ixia._session_quarantine_reason = "old ambiguous apply"
        self.ixia._quarantined_session_identity = ("::1", 17)
        self._configure_connect(session_id=None, session_name=None)

        with patch(
            "neteng.test_infra.dne.taac.ixia.ixia.IxnSessionAssistant",
            return_value=assistant,
        ):
            self.ixia.connect()

        self.assertFalse(self.ixia.session_quarantined)
        self.assertIs(
            assistant.TestPlatform._connection._session.request,
            self.ixia._deadline_request_wrapper,
        )
        self.ixia.apply_changes_bounded(1.0)
        replacement_topology.ApplyOnTheFly.assert_called_once_with()
        self.assertGreater(replacement_request.call_args.kwargs["timeout"], 0)

    def test_reconnect_inside_deadline_wraps_replacement_transport(self) -> None:
        assistant, replacement_request, _replacement_topology = (
            self._replacement_assistant(session_id=18, session_name="new-session")
        )
        self._configure_connect(session_id=None, session_name=None)

        with (
            patch(
                "neteng.test_infra.dne.taac.ixia.ixia.IxnSessionAssistant",
                return_value=assistant,
            ),
            self.ixia.request_deadline(1.0, "outer operation"),
        ):
            self.ixia.connect()
            assistant.TestPlatform._connection._session.request(
                "GET", "https://ixia/replacement"
            )

        replacement_request.assert_called_once()
        timeout = replacement_request.call_args.kwargs["timeout"]
        self.assertGreater(timeout, 0)
        self.assertLessEqual(timeout, 1.0)

    def test_reconnect_to_same_remote_session_preserves_quarantine(self) -> None:
        assistant, _replacement_request, replacement_topology = (
            self._replacement_assistant(session_id=18, session_name="existing-session")
        )
        self.ixia._session_quarantine_reason = "ambiguous apply"
        self.ixia._quarantined_session_identity = ("::1", 18)
        self._configure_connect(session_id=18, session_name="existing-session")

        with patch(
            "neteng.test_infra.dne.taac.ixia.ixia.IxnSessionAssistant",
            return_value=assistant,
        ):
            self.ixia.connect()

        self.assertTrue(self.ixia.session_quarantined)
        with self.assertRaises(IxiaSessionQuarantinedError):
            self.ixia.apply_changes_bounded(1.0)
        replacement_topology.ApplyOnTheFly.assert_not_called()

    def test_same_remote_session_id_with_new_name_preserves_quarantine(self) -> None:
        assistant, _replacement_request, replacement_topology = (
            self._replacement_assistant(session_id=18, session_name="renamed-session")
        )
        self.ixia._session_quarantine_reason = "ambiguous apply"
        self.ixia._quarantined_session_identity = ("::1", 18)
        self._configure_connect(session_id=18, session_name="original-session")

        with patch(
            "neteng.test_infra.dne.taac.ixia.ixia.IxnSessionAssistant",
            return_value=assistant,
        ):
            self.ixia.connect()

        self.assertTrue(self.ixia.session_quarantined)
        with self.assertRaises(IxiaSessionQuarantinedError):
            self.ixia.apply_changes_bounded(1.0)
        replacement_topology.ApplyOnTheFly.assert_not_called()

    def test_reconnect_waits_for_timed_out_apply_abort(self) -> None:
        apply_started = threading.Event()
        release_apply = threading.Event()
        old_session = self.ixia.session
        apply_errors: list[Exception] = []
        connect_errors: list[Exception] = []

        def timeout_then_abort(*_args: object, **_kwargs: object) -> object:
            if self.request.call_count == 1:
                apply_started.set()
                if not release_apply.wait(timeout=1.0):
                    raise AssertionError("apply release was not signaled")
                raise ReadTimeout("apply timed out")
            return object()

        assistant, _replacement_request, replacement_topology = (
            self._replacement_assistant(session_id=19, session_name="new-session")
        )
        self._configure_connect(session_id=None, session_name=None)
        self.request.side_effect = timeout_then_abort

        def apply() -> None:
            try:
                self.ixia.apply_changes_bounded(1.0, abort_timeout_seconds=0.1)
            except Exception as error:
                apply_errors.append(error)

        def connect() -> None:
            try:
                self.ixia.connect()
            except Exception as error:
                connect_errors.append(error)

        with patch(
            "neteng.test_infra.dne.taac.ixia.ixia.IxnSessionAssistant",
            return_value=assistant,
        ):
            apply_thread = threading.Thread(target=apply)
            connect_thread = threading.Thread(target=connect)
            apply_thread.start()
            self.assertTrue(apply_started.wait(timeout=1.0))
            connect_thread.start()
            time.sleep(0.05)
            self.assertTrue(connect_thread.is_alive())
            self.assertIs(old_session, self.ixia.session)
            release_apply.set()
            apply_thread.join()
            connect_thread.join()

        self.assertEqual([], connect_errors)
        self.assertEqual(1, len(apply_errors))
        self.assertIsInstance(apply_errors[0], IxiaOperationTimeoutError)
        self.topology.AbortApplyOnTheFly.assert_called_once_with()
        replacement_topology.AbortApplyOnTheFly.assert_not_called()
        self.assertIs(assistant, self.ixia.session)

    def test_failed_abort_identity_is_cleared_by_different_remote_session(
        self,
    ) -> None:
        self.request.side_effect = self._timeout_request

        with self.assertRaises(IxiaOperationTimeoutError):
            self.ixia.apply_changes_bounded(0.01, abort_timeout_seconds=0.01)

        self.assertEqual(("::1", 17), self.ixia._quarantined_session_identity)
        assistant, _replacement_request, _replacement_topology = (
            self._replacement_assistant(session_id=18, session_name="new-session")
        )
        self._configure_connect(session_id=None, session_name=None)

        with patch(
            "neteng.test_infra.dne.taac.ixia.ixia.IxnSessionAssistant",
            return_value=assistant,
        ):
            self.ixia.connect()

        self.assertFalse(self.ixia.session_quarantined)
        self.assertIsNone(self.ixia._quarantined_session_identity)

    def _assert_operational_abort_failure(self, error: Exception) -> None:
        apply_error = ReadTimeout("apply timed out")
        self.request.side_effect = apply_error
        self.topology.AbortApplyOnTheFly.side_effect = error

        with self.assertRaises(IxiaOperationTimeoutError) as context:
            self.ixia.apply_changes_bounded(1.0, abort_timeout_seconds=0.1)

        self.topology.ApplyOnTheFly.assert_called_once_with()
        self.topology.AbortApplyOnTheFly.assert_called_once_with()
        self.assertTrue(self.ixia.session_quarantined)
        self.assertIn(
            type(error).__name__,
            " ".join(getattr(context.exception, "__notes__", ())),
        )
        self.assertIs(apply_error, context.exception.__cause__)

    def test_ixnetwork_abort_failure_quarantines_session(self) -> None:
        self._assert_operational_abort_failure(IxnIxNetworkError("server failed"))

    def test_uhd_abort_failure_quarantines_session(self) -> None:
        self._assert_operational_abort_failure(UhdIxNetworkError("server failed"))

    def test_requests_abort_failure_quarantines_session(self) -> None:
        self._assert_operational_abort_failure(
            RequestsConnectionError("connection failed")
        )

    def test_abort_memory_error_propagates_and_quarantines(self) -> None:
        self.request.side_effect = ReadTimeout("apply timed out")
        self.topology.AbortApplyOnTheFly.side_effect = MemoryError("out of memory")

        with self.assertRaisesRegex(MemoryError, "out of memory"):
            self.ixia.apply_changes_bounded(1.0, abort_timeout_seconds=0.1)

        self.topology.ApplyOnTheFly.assert_called_once_with()
        self.topology.AbortApplyOnTheFly.assert_called_once_with()
        self.assertTrue(self.ixia.session_quarantined)
        with self.assertRaises(IxiaSessionQuarantinedError):
            self.ixia.apply_changes_bounded(1.0)
        self.topology.ApplyOnTheFly.assert_called_once_with()

    def test_abort_recursion_error_propagates_and_quarantines(self) -> None:
        self.request.side_effect = ReadTimeout("apply timed out")
        self.topology.AbortApplyOnTheFly.side_effect = RecursionError(
            "maximum recursion depth exceeded"
        )

        with self.assertRaisesRegex(RecursionError, "maximum recursion depth exceeded"):
            self.ixia.apply_changes_bounded(1.0, abort_timeout_seconds=0.1)

        self.topology.ApplyOnTheFly.assert_called_once_with()
        self.topology.AbortApplyOnTheFly.assert_called_once_with()
        self.assertTrue(self.ixia.session_quarantined)
        with self.assertRaises(IxiaSessionQuarantinedError):
            self.ixia.apply_changes_bounded(1.0)
        self.topology.ApplyOnTheFly.assert_called_once_with()

    def test_unexpected_abort_error_propagates_and_quarantines(self) -> None:
        self.request.side_effect = ReadTimeout("apply timed out")
        self.topology.AbortApplyOnTheFly.side_effect = TypeError("bad SDK call")

        with self.assertRaisesRegex(TypeError, "bad SDK call"):
            self.ixia.apply_changes_bounded(1.0, abort_timeout_seconds=0.1)

        self.topology.ApplyOnTheFly.assert_called_once_with()
        self.topology.AbortApplyOnTheFly.assert_called_once_with()
        self.assertTrue(self.ixia.session_quarantined)
        with self.assertRaises(IxiaSessionQuarantinedError):
            self.ixia.apply_changes_bounded(1.0)
        self.topology.ApplyOnTheFly.assert_called_once_with()

    def test_non_timeout_error_is_not_aborted_or_retried(self) -> None:
        self.request.side_effect = RuntimeError("HTTP 400")

        with self.assertRaisesRegex(RuntimeError, "HTTP 400"):
            self.ixia.apply_changes_bounded(1.0)

        self.topology.ApplyOnTheFly.assert_called_once_with()
        self.topology.AbortApplyOnTheFly.assert_not_called()
        self.assertFalse(self.ixia.session_quarantined)

    def test_late_non_timeout_error_remains_definitive(self) -> None:
        now = 0.0

        def late_error(*_args: object, **_kwargs: object) -> object:
            nonlocal now
            now = 2.0
            raise RuntimeError("HTTP 400")

        self.request.side_effect = late_error
        with (
            patch(
                "neteng.test_infra.dne.taac.ixia.ixia.time.monotonic",
                side_effect=lambda: now,
            ),
            self.assertRaisesRegex(RuntimeError, "HTTP 400"),
        ):
            self.ixia.apply_changes_bounded(1.0)

        self.topology.AbortApplyOnTheFly.assert_not_called()
        self.assertFalse(self.ixia.session_quarantined)

    def test_post_apply_sleep_timeout_does_not_abort(self) -> None:
        with (
            patch(
                "neteng.test_infra.dne.taac.ixia.ixia.time.monotonic",
                side_effect=[0.0, 0.0, 2.0],
            ),
            self.assertRaises(IxiaOperationTimeoutError),
        ):
            self.ixia.apply_changes_bounded(1.0, sleep_timer=1)

        self.topology.ApplyOnTheFly.assert_called_once_with()
        self.topology.AbortApplyOnTheFly.assert_not_called()
        self.assertFalse(self.ixia.session_quarantined)

    def test_missing_post_apply_deadline_is_internal_state_error(self) -> None:
        def apply_and_remove_deadline() -> None:
            self.transport.request("POST", "https://ixia/apply")
            del self.ixia._request_deadline_state.deadline

        self.topology.ApplyOnTheFly.side_effect = apply_and_remove_deadline

        with self.assertRaisesRegex(
            IxiaOperationStateError, "operation deadline state is missing"
        ):
            self.ixia.apply_changes_bounded(1.0, sleep_timer=1)

        self.topology.ApplyOnTheFly.assert_called_once_with()
        self.topology.AbortApplyOnTheFly.assert_not_called()
        self.assertFalse(self.ixia.session_quarantined)

    def test_post_apply_sleep_allows_exact_deadline_margin(self) -> None:
        with (
            patch(
                "neteng.test_infra.dne.taac.ixia.ixia.time.monotonic",
                side_effect=[0.0, 0.0, 0.0],
            ),
            patch("neteng.test_infra.dne.taac.ixia.ixia.time.sleep") as sleep,
        ):
            self.ixia.apply_changes_bounded(11.0, sleep_timer=10)

        sleep.assert_called_once_with(10)
        self.topology.ApplyOnTheFly.assert_called_once_with()
        self.topology.AbortApplyOnTheFly.assert_not_called()
        self.assertFalse(self.ixia.session_quarantined)

    def test_post_apply_sleep_rejects_subsecond_deadline_margin(self) -> None:
        with (
            patch(
                "neteng.test_infra.dne.taac.ixia.ixia.time.monotonic",
                side_effect=[0.0, 0.0, 0.0],
            ),
            patch("neteng.test_infra.dne.taac.ixia.ixia.time.sleep") as sleep,
            self.assertRaisesRegex(
                IxiaOperationTimeoutError, "insufficient operation deadline margin"
            ),
        ):
            self.ixia.apply_changes_bounded(10.5, sleep_timer=10)

        sleep.assert_not_called()
        self.topology.ApplyOnTheFly.assert_called_once_with()
        self.topology.AbortApplyOnTheFly.assert_not_called()
        self.assertFalse(self.ixia.session_quarantined)

    def test_failed_abort_quarantines_waiting_apply(self) -> None:
        abort_started = threading.Event()
        release_abort = threading.Event()
        second_started = threading.Event()
        first_errors: list[Exception] = []
        second_errors: list[Exception] = []

        def fail_apply_and_abort(*_args: object, **_kwargs: object) -> object:
            if self.request.call_count == 1:
                raise ReadTimeout("apply timed out")
            abort_started.set()
            if not release_abort.wait(timeout=1.0):
                raise AssertionError("abort release was not signaled")
            raise ReadTimeout("abort timed out")

        def first_apply() -> None:
            try:
                self.ixia.apply_changes_bounded(1.0, abort_timeout_seconds=1.0)
            except Exception as error:
                first_errors.append(error)

        def second_apply() -> None:
            second_started.set()
            try:
                self.ixia.apply_changes_bounded(1.0)
            except Exception as error:
                second_errors.append(error)

        self.request.side_effect = fail_apply_and_abort
        first = threading.Thread(target=first_apply)
        second = threading.Thread(target=second_apply)
        first.start()
        self.assertTrue(abort_started.wait(timeout=1.0))
        second.start()
        self.assertTrue(second_started.wait(timeout=1.0))
        self.assertEqual(1, self.topology.ApplyOnTheFly.call_count)
        release_abort.set()
        first.join()
        second.join()

        self.assertEqual(1, len(first_errors))
        self.assertIsInstance(first_errors[0], IxiaOperationTimeoutError)
        self.assertEqual(1, len(second_errors))
        self.assertIsInstance(second_errors[0], IxiaSessionQuarantinedError)
        self.assertEqual(1, self.topology.ApplyOnTheFly.call_count)
        self.assertEqual(1, self.topology.AbortApplyOnTheFly.call_count)

    def test_rejects_nonpositive_deadlines(self) -> None:
        with self.assertRaisesRegex(ValueError, "timeout_seconds"):
            self.ixia.apply_changes_bounded(0)
        with self.assertRaisesRegex(ValueError, "abort_timeout_seconds"):
            self.ixia.apply_changes_bounded(1.0, abort_timeout_seconds=0)
