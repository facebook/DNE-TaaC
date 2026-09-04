# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Unit tests for the tracer wiring inside `Ixia`.

These exercise the seam that the tracer depends on: the transport wrapper
installed by `_install_request_deadline_wrapper_locked`, and the `op` label
`@external_api` publishes for it. The case that matters most is a call issued
OUTSIDE a `request_deadline()` scope, which takes the wrapper's no-deadline
early return and would go unrecorded if tracing lived inside the deadline
branch.

The rest hold the line that tracing is an observer: a credential must not
reach the trace file, and no tracer fault may change the REST result the
caller is waiting on.
"""

import json
import logging
import tempfile
import threading
import typing as t
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from neteng.test_infra.dne.taac.ixia.ixia import external_api, Ixia
from taac.ixia.ixia_tracer import IxiaTracer


def _response(status_code: int = 200, content: bytes = b"{}") -> SimpleNamespace:
    return SimpleNamespace(status_code=status_code, content=content)


class IxiaApiTracingTest(unittest.TestCase):
    def setUp(self) -> None:
        tmpdir = tempfile.TemporaryDirectory(prefix="ixia_api_tracing_test_")
        self.addCleanup(tmpdir.cleanup)
        self.trace_path = Path(tmpdir.name) / "trace.jsonl"

        with patch.object(Ixia, "__init__", lambda self: None):
            self.ixia = Ixia()
        self.ixia.logger = logging.getLogger(__name__)
        self.ixia._request_deadline_state = threading.local()
        self.ixia._request_deadline_wrapper_lock = threading.Lock()
        self.ixia._current_playbook_name = "bag011_cold_start"
        self.ixia._current_testconfig_name = "BGP_PLUS_PLUS_BAG011"
        self.tracer = IxiaTracer(path=self.trace_path, logger=self.ixia.logger)
        self.ixia._tracer = self.tracer
        self.request = MagicMock(return_value=_response())
        self.transport = SimpleNamespace(request=self.request)
        self.ixia.session = t.cast(
            t.Any,
            SimpleNamespace(
                TestPlatform=SimpleNamespace(
                    _connection=SimpleNamespace(_session=self.transport)
                )
            ),
        )
        self.ixia._install_request_deadline_wrapper()

    def _trace_text(self) -> str:
        self.tracer.close()
        if not self.trace_path.exists():
            return ""
        return self.trace_path.read_text(encoding="utf-8")

    def _records(self) -> list:
        return [json.loads(line) for line in self._trace_text().splitlines() if line]

    def test_call_outside_a_deadline_scope_is_traced(self) -> None:
        self.transport.request(
            method="GET",
            url="https://chassis/api/v1/sessions/1/ixnetwork/vport",
            data=None,
        )

        (record,) = self._records()
        self.assertEqual(record["method"], "GET")
        self.assertEqual(
            record["url"], "https://chassis/api/v1/sessions/1/ixnetwork/vport"
        )
        self.assertEqual(record["status"], 200)
        self.assertIsNone(record["phase"])
        self.assertEqual(record["playbook"], "bag011_cold_start")
        self.assertEqual(record["testconfig"], "BGP_PLUS_PLUS_BAG011")

    def test_positional_call_is_traced(self) -> None:
        self.transport.request(
            "GET",
            "https://chassis/api/v1/sessions/1/files?filename=cfg.ixncfg",
            headers={},
            verify=False,
        )

        (record,) = self._records()
        self.assertEqual(record["method"], "GET")
        self.assertEqual(
            record["url"],
            "https://chassis/api/v1/sessions/1/files?filename=cfg.ixncfg",
        )

    def test_request_body_and_phase_are_recorded_inside_a_deadline(self) -> None:
        with self.ixia.request_deadline(30.0, "IXIA protocol start"):
            self.transport.request(
                method="POST",
                url="https://chassis/api/v1/sessions/1/ixnetwork/operations/start",
                data='{"arg1": "/topology/1"}',
            )

        (record,) = self._records()
        self.assertEqual(record["phase"], "IXIA protocol start")
        self.assertEqual(record["request_body"], '{"arg1": "/topology/1"}')
        # The deadline still caps the transport timeout.
        capped_timeout = self.request.call_args.kwargs["timeout"]
        self.assertGreater(capped_timeout, 0)
        self.assertLessEqual(capped_timeout, 30.0)

    def test_transport_exception_is_traced_and_reraised(self) -> None:
        self.request.side_effect = ConnectionError("connection reset by peer")

        with self.assertRaises(ConnectionError):
            self.transport.request(method="GET", url="https://chassis/api/v1")

        (record,) = self._records()
        self.assertIsNone(record["status"])
        self.assertEqual(record["error"], "ConnectionError: connection reset by peer")

    def test_external_api_labels_the_call_and_restores_the_previous_label(
        self,
    ) -> None:
        transport = self.transport

        def inner(self) -> None:
            transport.request(method="GET", url="https://chassis/inner")

        def outer(self) -> None:
            transport.request(method="GET", url="https://chassis/outer-before")
            external_api(inner)(self)
            transport.request(method="GET", url="https://chassis/outer-after")

        external_api(outer)(self.ixia)
        self.transport.request(method="GET", url="https://chassis/unlabelled")

        labels = {record["url"]: record["op"] for record in self._records()}
        self.assertEqual(labels["https://chassis/outer-before"], "outer")
        self.assertEqual(labels["https://chassis/inner"], "inner")
        self.assertEqual(labels["https://chassis/outer-after"], "outer")
        self.assertIsNone(labels["https://chassis/unlabelled"])

    def test_reinstalling_after_a_reconnect_keeps_tracing(self) -> None:
        replacement_request = MagicMock(return_value=_response(201))
        replacement_transport = SimpleNamespace(request=replacement_request)
        replacement_session = SimpleNamespace(
            TestPlatform=SimpleNamespace(
                _connection=SimpleNamespace(_session=replacement_transport)
            )
        )

        self.ixia._install_request_deadline_wrapper_locked(replacement_session)
        replacement_transport.request(method="POST", url="https://chassis/after")

        (record,) = self._records()
        self.assertEqual(record["url"], "https://chassis/after")
        self.assertEqual(record["status"], 201)

    def test_reinstalling_the_same_transport_is_a_no_op(self) -> None:
        already_installed = self.transport.request

        self.ixia._install_request_deadline_wrapper()

        self.assertIs(self.transport.request, already_installed)

    def test_reinstalling_over_an_earlier_transport_does_not_nest(self) -> None:
        first_wrapper = self.transport.request
        replacement_transport = SimpleNamespace(
            request=MagicMock(return_value=_response())
        )
        replacement_session = SimpleNamespace(
            TestPlatform=SimpleNamespace(
                _connection=SimpleNamespace(_session=replacement_transport)
            )
        )

        self.ixia._install_request_deadline_wrapper_locked(replacement_session)
        # Back to the transport wrapped first, which the single-slot
        # bookkeeping no longer names.
        self.ixia._install_request_deadline_wrapper()
        self.transport.request(method="GET", url="https://chassis/api/v1")

        self.assertIs(first_wrapper, self.transport.request)
        self.assertEqual(1, len(self._records()))

    def test_untraced_ixia_still_enforces_the_deadline(self) -> None:
        self.ixia._tracer = None
        self.transport.request = self.request
        self.ixia._deadline_wrapped_transport = None
        self.ixia._deadline_request_wrapper = None
        self.ixia._install_request_deadline_wrapper()

        with self.ixia.request_deadline(30.0, "IXIA operation"):
            self.transport.request(method="GET", url="https://chassis/api/v1")

        self.assertLessEqual(self.request.call_args.kwargs["timeout"], 30.0)
        self.assertFalse(self.trace_path.exists())

    def test_auth_password_never_reaches_the_trace_file(self) -> None:
        self.transport.request(
            method="POST",
            url="https://chassis/api/v1/auth/session",
            data=json.dumps(
                {"username": "ixia_admin", "password": "hunter2", "ignorePolicy": True}
            ),
        )

        trace_text = self._trace_text()
        self.assertNotIn("hunter2", trace_text)
        self.assertNotIn("ixia_admin", trace_text)
        (record,) = [json.loads(line) for line in trace_text.splitlines() if line]
        body = json.loads(record["request_body"])
        self.assertEqual("[REDACTED]", body["password"])
        self.assertEqual("[REDACTED]", body["username"])
        # The call itself is still visible, which is the point of replacing
        # the values rather than dropping the record.
        self.assertEqual("https://chassis/api/v1/auth/session", record["url"])
        self.assertTrue(body["ignorePolicy"])

    def test_auth_response_api_key_never_reaches_the_trace_file(self) -> None:
        self.request.return_value = _response(
            status_code=401,
            content=json.dumps(
                {"apiKey": "5f4dcc3b5aa765d6", "username": "ixia_admin"}
            ).encode("utf-8"),
        )

        self.transport.request(
            method="POST", url="https://chassis/api/v1/auth/session", data="{}"
        )

        self.assertNotIn("5f4dcc3b5aa765d6", self._trace_text())

    def test_credential_key_is_redacted_off_the_auth_path(self) -> None:
        self.transport.request(
            method="POST",
            url="https://chassis/api/v1/sessions/1/ixnetwork/topology/deviceGroup",
            data=json.dumps({"name": "dg1", "password": "hunter2"}),
        )

        (record,) = self._records()
        body = json.loads(record["request_body"])
        self.assertEqual("[REDACTED]", body["password"])
        # Everything that is not a credential survives, or the trace stops
        # being useful to Keysight.
        self.assertEqual("dg1", body["name"])

    def test_span_setup_failure_still_completes_the_request(self) -> None:
        with (
            patch(
                "neteng.test_infra.dne.taac.ixia.ixia.extract_request_method_and_url",
                side_effect=RuntimeError("unrecognised call shape"),
            ),
            self.assertLogs(self.ixia.logger, level="ERROR"),
        ):
            response = self.transport.request(
                method="GET", url="https://chassis/api/v1"
            )

        self.assertEqual(200, response.status_code)
        self.request.assert_called_once()
        self.assertEqual([], self._records())

    def test_trace_write_failure_does_not_mask_a_successful_response(self) -> None:
        with (
            patch.object(self.tracer, "finish", side_effect=RuntimeError("disk full")),
            self.assertLogs(self.ixia.logger, level="ERROR"),
        ):
            response = self.transport.request(
                method="GET", url="https://chassis/api/v1"
            )

        self.assertEqual(200, response.status_code)

    def test_trace_write_failure_does_not_mask_the_transport_exception(self) -> None:
        self.request.side_effect = ConnectionError("connection reset by peer")

        with (
            patch.object(self.tracer, "fail", side_effect=RuntimeError("disk full")),
            self.assertLogs(self.ixia.logger, level="ERROR"),
            self.assertRaises(ConnectionError),
        ):
            self.transport.request(method="GET", url="https://chassis/api/v1")


class IxiaTracerConstructionTest(unittest.TestCase):
    """The `trace_api_calls` branch of the real `__init__`.

    Every other case in this module patches `__init__` out and injects a
    tracer by hand, so without this the branch that builds the tracer and the
    `api_tracer` property that exposes it never execute: tracing could be off
    in production with the whole suite green.
    """

    def _build_ixia(self, **kwargs: t.Any) -> Ixia:
        with patch("neteng.test_infra.dne.taac.ixia.ixia.ConfigeratorClient"):
            return Ixia(
                session_id=1,
                chassis_ip="::1",
                logger=logging.getLogger(__name__),
                **kwargs,
            )

    def test_trace_api_calls_builds_a_tracer(self) -> None:
        tracer = self._build_ixia(trace_api_calls=True).api_tracer

        self.assertIsInstance(tracer, IxiaTracer)
        self.assertEqual(".jsonl", tracer.path.suffix)
        # Construction only names the file; the first record creates it.
        self.assertFalse(tracer.path.exists())

    def test_tracing_is_off_by_default(self) -> None:
        self.assertIsNone(self._build_ixia().api_tracer)
