# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Unit tests for the tracer wiring inside `Ixia`.

These exercise the seams the tracer depends on: the transport wrapper
installed by `_install_request_deadline_wrapper_locked`, the `op` label
`@external_api` publishes for it, the appErrors fetch the wrapper hands the
tracer, and the session preamble `connect()` emits.

Two cases matter most. A call issued OUTSIDE a `request_deadline()` scope
takes the wrapper's no-deadline early return and would go unrecorded if
tracing lived inside the deadline branch. And an `@external_api` method that
also carries `@require_traffic_item` used to be labelled `wrapper`, which is
how a whole run of `start_traffic` failures went unattributed.

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

from taac.ixia.ixia import (
    external_api,
    Ixia,
    require_traffic_item,
    resolve_decorated_name,
)
from taac.ixia.ixia_tracer import (
    build_slice_path,
    IxiaTracer,
    RECORD_TYPE_REST_CALL,
    RECORD_TYPE_SESSION_PREAMBLE,
)
from taac.utils.oss_taac_lib_utils import retryable

_SESSION = "https://chassis/api/v1/sessions/17"
_APPLY_URL = f"{_SESSION}/ixnetwork/traffic/operations/apply"
_APPLY_BODY = '{"Arg1": "/api/v1/sessions/17/ixnetwork/traffic"}'
_APP_ERRORS_URL = f"{_SESSION}/ixnetwork/globals/appErrors/error"
_APPLY_EXCEPTION_BODY = (
    b'{"state":"EXCEPTION","result":" Error in L2/L3 Traffic Apply\\n","message":null}'
)
_APP_ERRORS_BODY = b'[{"errorLevel":"kError","name":"Port ownership"}]'


def _response(status_code: int = 200, content: bytes = b"{}") -> SimpleNamespace:
    return SimpleNamespace(status_code=status_code, content=content)


def _port_config(port_name: str, slot: int, port: int) -> SimpleNamespace:
    return SimpleNamespace(
        port_name=port_name,
        phy_port_config=SimpleNamespace(
            chassis_ip="2401:db00::3023", slot_number=slot, port_number=port
        ),
    )


class TracingTestBase(unittest.TestCase):
    """An `Ixia` whose transport is a mock, shared by the suites below.

    Split from the cases so that inheriting the fixture does not also re-run
    every base case in each subclass.
    """

    def setUp(self) -> None:
        tmpdir = tempfile.TemporaryDirectory(prefix="ixia_api_tracing_test_")
        self.addCleanup(tmpdir.cleanup)
        self.trace_path = Path(tmpdir.name) / "trace.jsonl"
        self.setup_slice_path = build_slice_path(self.trace_path, 0, "setup")

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
        self.connection = SimpleNamespace(
            _session=self.transport,
            _headers={"X-Api-Key": "k"},
            _verify_cert=False,
        )
        self.ixia.session = t.cast(
            t.Any,
            SimpleNamespace(TestPlatform=SimpleNamespace(_connection=self.connection)),
        )
        self.ixia._install_request_deadline_wrapper()

    def _trace_text(self, path: t.Optional[Path] = None) -> str:
        self.tracer.close()
        target = path if path is not None else self.setup_slice_path
        return target.read_text(encoding="utf-8") if target.exists() else ""

    def _lines(self, path: t.Optional[Path] = None) -> list:
        return [
            json.loads(line) for line in self._trace_text(path).splitlines() if line
        ]

    def _records(self, path: t.Optional[Path] = None) -> list:
        return [
            line
            for line in self._lines(path)
            if line["record_type"] == RECORD_TYPE_REST_CALL
        ]


class IxiaApiTracingTest(TracingTestBase):
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
        self.assertEqual(record["outcome"], "success")
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
        self.assertEqual(record["outcome"], "failure")
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
        self.assertFalse(self.setup_slice_path.exists())

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
        (record,) = self._records()
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


class OperationLabelTest(TracingTestBase):
    def test_the_shipped_ixia_methods_carry_their_own_names(self) -> None:
        """Pins the four `@external_api` methods that sit above a decorator.

        `start_traffic`, `stop_traffic` and `enable_traffic` all resolved to
        `wrapper` before `require_traffic_item` learned `functools.wraps`.
        """
        for name in (
            "start_traffic",
            "stop_traffic",
            "enable_traffic",
            "apply_changes",
        ):
            method = getattr(Ixia, name)
            self.assertEqual(resolve_decorated_name(method), name)
            self.assertEqual(method.__name__, name)

    def test_resolve_decorated_name_sees_through_the_decorator_stack(self) -> None:
        def start_traffic(self) -> None:
            return None

        wrapped = require_traffic_item(
            retryable(num_tries=15, sleep_time=5, debug=True)(start_traffic)
        )

        self.assertEqual(resolve_decorated_name(wrapped), "start_traffic")

    def test_the_real_decorator_stack_labels_calls_start_traffic(self) -> None:
        """The exact `ixia.py:5783` stack, which used to publish `wrapper`.

        In the run this fixture is modelled on, all 19
        `traffic/operations/apply` records carried `op: "wrapper"`, so no
        query could tie the 15 failures to `start_traffic`.
        """
        transport = self.transport

        @external_api
        @require_traffic_item
        @retryable(num_tries=15, sleep_time=5, debug=True)
        def start_traffic(self) -> None:
            transport.request(method="POST", url=_APPLY_URL, data=_APPLY_BODY)

        self.ixia.has_traffic_items = lambda: True
        start_traffic(self.ixia)

        (record,) = self._records()
        self.assertEqual(record["op"], "start_traffic")
        self.assertNotEqual(record["op"], "wrapper")

    def test_a_skipped_require_traffic_item_call_issues_no_rest_call(self) -> None:
        transport = self.transport

        @external_api
        @require_traffic_item
        def start_traffic(self) -> None:
            transport.request(method="POST", url=_APPLY_URL, data=_APPLY_BODY)

        self.ixia.has_traffic_items = lambda: False
        start_traffic(self.ixia)

        self.assertEqual(self._records(), [])


class AppErrorsFetchWiringTest(TracingTestBase):
    def test_a_failure_fetches_app_errors_off_the_unwrapped_transport(self) -> None:
        self.request.side_effect = [
            _response(202, _APPLY_EXCEPTION_BODY),
            _response(200, _APP_ERRORS_BODY),
        ]

        self.transport.request(method="POST", url=_APPLY_URL, data=_APPLY_BODY)

        apply_record, app_errors = self._records()
        self.assertEqual(apply_record["status"], 202)
        self.assertEqual(apply_record["outcome"], "failure")
        self.assertEqual(apply_record["error"], "Error in L2/L3 Traffic Apply")
        self.assertEqual(app_errors["url"], _APP_ERRORS_URL)
        self.assertEqual(app_errors["caused_by_seq"], apply_record["seq"])
        self.assertEqual(app_errors["response_body"], _APP_ERRORS_BODY.decode("utf-8"))
        # Two transport calls, two records: the fetch went through the
        # pre-wrap callable, so it was not traced twice.
        self.assertEqual(self.request.call_count, 2)
        fetch_call = self.request.call_args_list[1]
        self.assertEqual(fetch_call.args, ("GET", _APP_ERRORS_URL))
        self.assertEqual(fetch_call.kwargs["headers"], {"X-Api-Key": "k"})
        self.assertGreater(fetch_call.kwargs["timeout"], 0)

    def test_the_fetch_ignores_an_expired_request_deadline(self) -> None:
        """The deadline the failing call exhausted must not eat the evidence."""
        self.request.side_effect = [
            _response(202, _APPLY_EXCEPTION_BODY),
            _response(200, _APP_ERRORS_BODY),
        ]

        with self.ixia.request_deadline(30.0, "IXIA traffic apply"):
            self.transport.request(method="POST", url=_APPLY_URL, data=_APPLY_BODY)

        self.assertEqual(self.request.call_count, 2)
        _apply_record, app_errors = self._records()
        self.assertEqual(app_errors["url"], _APP_ERRORS_URL)


class SessionPreambleWiringTest(TracingTestBase):
    def _configure_session(self) -> None:
        self.ixia.primary_chassis_ip = "2401:db00::3023"
        self.ixia.session_id = 17
        self.ixia.session_name = "taac_run"
        self.ixia.is_uhd_chassis = False
        self.ixia.force_take_port_ownership = True
        self.ixia.ixia_config = t.cast(
            t.Any,
            SimpleNamespace(
                port_configs=[_port_config("gtsw007.f01.snc1:eth1/1/1", 2, 5)],
                traffic_items=[SimpleNamespace(name="TI_A_TO_B")],
            ),
        )

    def test_preamble_names_the_session_and_the_port_map(self) -> None:
        self._configure_session()

        self.ixia._publish_trace_session_preamble()

        (line,) = self._lines()
        self.assertEqual(line["record_type"], RECORD_TYPE_SESSION_PREAMBLE)
        self.assertEqual(line["seq"], 0)
        self.assertEqual(line["chassis_ip"], "2401:db00::3023")
        self.assertEqual(line["session_id"], 17)
        self.assertEqual(line["session_name"], "taac_run")
        self.assertFalse(line["is_uhd_chassis"])
        self.assertTrue(line["force_take_port_ownership"])
        self.assertEqual(line["traffic_items"], ["TI_A_TO_B"])
        self.assertEqual(
            line["ports"],
            [
                {
                    "dut_interface": "gtsw007.f01.snc1:eth1/1/1",
                    "chassis_ip": "2401:db00::3023",
                    "slot": 2,
                    "port": 5,
                    "vport_name": "VPORT_GTSW007.F01.SNC1:ETH1/1/1",
                }
            ],
        )

    def test_a_broken_config_does_not_raise(self) -> None:
        self.ixia.primary_chassis_ip = "2401:db00::3023"
        self.ixia.session_id = 17
        self.ixia.session_name = "taac_run"
        self.ixia.is_uhd_chassis = False
        self.ixia.force_take_port_ownership = False
        self.ixia.ixia_config = t.cast(t.Any, SimpleNamespace(port_configs=[object()]))

        self.ixia._publish_trace_session_preamble()

        self.assertEqual(self._lines(), [])


class PhaseRotationTest(TracingTestBase):
    def test_rotation_returns_the_closed_slice_and_starts_a_new_one(self) -> None:
        self.transport.request(method="GET", url="https://chassis/setup")

        setup = self.ixia.rotate_api_trace_phase("bag011_cold_start")
        self.transport.request(method="GET", url="https://chassis/pb")

        assert setup is not None
        self.assertEqual((setup.phase, setup.record_count), ("setup", 1))
        self.assertEqual(self.tracer.current_phase, "bag011_cold_start")
        playbook_slice = build_slice_path(self.trace_path, 1, "bag011_cold_start")
        (record,) = self._records(playbook_slice)
        self.assertEqual(record["url"], "https://chassis/pb")

    def test_rotation_without_a_tracer_is_a_no_op(self) -> None:
        self.ixia._tracer = None

        self.assertIsNone(self.ixia.rotate_api_trace_phase("bag011_cold_start"))


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
