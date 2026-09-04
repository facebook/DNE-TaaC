# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Unit tests for the IxNetwork REST API tracer.

The transport-extraction tests pin the two calling conventions
`ixnetwork_restpy` uses against `requests.Session.request`: keyword-only via
`Connection._request`, and positional `("GET", url, ...)` from the
file-transfer, 409-retry and async-poll helpers. Getting either wrong drops
whole classes of calls out of the trace silently.

`AsyncOutcomeTest` and `RealRunReplayTest` cover the reason this module was
revised: a run in which `start_traffic` failed 15 times produced 2621 records
with zero non-null `error` fields, because IxNetwork reports the failure in
the body of an HTTP 202 and restpy only rewrites the status code afterwards.
"""

import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from taac.ixia.ixia_tracer import (
    app_errors_url_for,
    async_failure_message,
    BodyCapture,
    build_slice_path,
    build_trace_path,
    clip_body,
    extract_request_body,
    extract_request_method_and_url,
    IxiaTracePortMapping,
    IxiaTracer,
    IxiaTraceSessionPreamble,
    RECORD_TYPE_REST_CALL,
    RECORD_TYPE_SESSION_PREAMBLE,
    redact_credentials,
    REDACTED_MARKER,
    slugify_phase,
    TEARDOWN_PHASE,
)

_SESSION = "https://[2401:db00::3023]:443/api/v1/sessions/17"
_APPLY_URL = f"{_SESSION}/ixnetwork/traffic/operations/apply"
_APPLY_BODY = '{"Arg1": "/api/v1/sessions/17/ixnetwork/traffic"}'
_APP_ERRORS_URL = f"{_SESSION}/ixnetwork/globals/appErrors/error"

# The body IxNetwork returns inside the HTTP 202 when Traffic.Apply fails.
_APPLY_EXCEPTION_BODY = (
    b'{"state":"EXCEPTION","result":" Error in L2/L3 Traffic Apply\\n","message":null}'
)
_APPLY_IN_PROGRESS_BODY = (
    b'{"state":"IN_PROGRESS","url":"/api/v1/sessions/17/operations/apply/1"}'
)
_APP_ERRORS_BODY = (
    b'[{"errorLevel":"kError","name":"Port ownership","lastModified":'
    b'"18:03:52","description":"Port taken by another user"}]'
)

_AUTH_URL = "https://chassis/api/v1/auth/session"
_TOPOLOGY_URL = "https://chassis/api/v1/sessions/1/ixnetwork/topology"


def _response(status_code: int, content: bytes = b"") -> SimpleNamespace:
    return SimpleNamespace(status_code=status_code, content=content)


def _text(value: object) -> str:
    assert isinstance(value, str), f"expected a string, got {value!r}"
    return value


def _number(value: object) -> float:
    assert isinstance(value, (int, float)), f"expected a number, got {value!r}"
    return value


class ExtractRequestTargetTest(unittest.TestCase):
    def test_keyword_convention(self) -> None:
        method, url = extract_request_method_and_url(
            (),
            {
                "method": "POST",
                "url": "https://chassis/api/v1/sessions/1/ixnetwork/operations/apply",
                "data": '{"arg1": "x"}',
            },
        )
        self.assertEqual(method, "POST")
        self.assertEqual(
            url, "https://chassis/api/v1/sessions/1/ixnetwork/operations/apply"
        )

    def test_positional_convention(self) -> None:
        method, url = extract_request_method_and_url(
            ("GET", "https://chassis/api/v1/sessions/1/files?filename=cfg"),
            {"headers": {}, "verify": False},
        )
        self.assertEqual(method, "GET")
        self.assertEqual(url, "https://chassis/api/v1/sessions/1/files?filename=cfg")

    def test_mixed_convention_prefers_keyword(self) -> None:
        method, url = extract_request_method_and_url(
            ("GET",), {"url": "https://chassis/api/v1/sessions"}
        )
        self.assertEqual(method, "GET")
        self.assertEqual(url, "https://chassis/api/v1/sessions")

    def test_missing_target_is_empty_not_an_error(self) -> None:
        self.assertEqual(extract_request_method_and_url((), {}), ("", ""))

    def test_body_is_the_data_keyword_in_both_conventions(self) -> None:
        self.assertEqual(extract_request_body({"data": b"payload"}), b"payload")
        self.assertIsNone(extract_request_body({"headers": {}}))


class ClipBodyTest(unittest.TestCase):
    def test_short_body_is_kept_verbatim(self) -> None:
        self.assertEqual(clip_body('{"a": 1}', 4096), '{"a": 1}')

    def test_none_body_stays_none(self) -> None:
        self.assertIsNone(clip_body(None, 4096))

    def test_oversized_body_is_marked_with_original_size(self) -> None:
        clipped = _text(clip_body("x" * 5000, 100))
        self.assertTrue(clipped.startswith("x" * 100))
        self.assertIn("truncated: kept 100 of 5000 bytes", clipped)

    def test_bytes_body_is_decoded_leniently(self) -> None:
        self.assertEqual(clip_body(b"\xff\xfeabc", 4096), "\ufffd\ufffdabc")


class RedactCredentialsTest(unittest.TestCase):
    def test_auth_payload_keeps_its_shape_without_its_secrets(self) -> None:
        redacted = json.loads(
            _text(
                redact_credentials(
                    json.dumps(
                        {
                            "username": "ixia_admin",
                            "password": "hunter2",
                            "ignorePolicy": True,
                        }
                    ),
                    _AUTH_URL,
                )
            )
        )
        self.assertEqual(
            {
                "username": REDACTED_MARKER,
                "password": REDACTED_MARKER,
                "ignorePolicy": True,
            },
            redacted,
        )

    def test_auth_reply_api_key_is_redacted(self) -> None:
        redacted = json.loads(
            _text(redact_credentials(b'{"apiKey": "5f4dcc3b"}', _AUTH_URL))
        )
        self.assertEqual({"apiKey": REDACTED_MARKER}, redacted)

    def test_unparseable_auth_body_is_dropped_whole(self) -> None:
        self.assertEqual(
            REDACTED_MARKER, redact_credentials(b"\x00binary blob", _AUTH_URL)
        )

    def test_credential_keys_are_redacted_off_the_auth_path(self) -> None:
        redacted = json.loads(
            _text(
                redact_credentials(
                    json.dumps(
                        {
                            "name": "dg1",
                            "password": "hunter2",
                            "api_key": "5f4dcc3b",
                            "nested": [{"apiKey": "5f4dcc3b"}],
                        }
                    ),
                    _TOPOLOGY_URL,
                )
            )
        )
        self.assertEqual(
            {
                "name": "dg1",
                "password": REDACTED_MARKER,
                "api_key": REDACTED_MARKER,
                "nested": [{"apiKey": REDACTED_MARKER}],
            },
            redacted,
        )

    def test_body_without_a_credential_is_returned_untouched(self) -> None:
        body = '{"name": "Topology 1", "count": 4}'
        self.assertIs(body, redact_credentials(body, _TOPOLOGY_URL))

    def test_non_json_body_off_the_auth_path_is_returned_untouched(self) -> None:
        self.assertEqual(
            b"\x00ixncfg", redact_credentials(b"\x00ixncfg", _TOPOLOGY_URL)
        )

    def test_none_body_stays_none(self) -> None:
        self.assertIsNone(redact_credentials(None, _AUTH_URL))


class AsyncFailureMessageTest(unittest.TestCase):
    def test_exception_state_yields_message_and_result(self) -> None:
        self.assertEqual(
            async_failure_message(
                b'{"state":"EXCEPTION","message":"API CONTENTION",'
                b'"result":" Error in L2/L3 Traffic Apply"}'
            ),
            "API CONTENTION Error in L2/L3 Traffic Apply",
        )

    def test_null_message_leaves_only_the_result(self) -> None:
        self.assertEqual(
            async_failure_message(_APPLY_EXCEPTION_BODY),
            "Error in L2/L3 Traffic Apply",
        )

    def test_state_with_neither_field_still_names_the_state(self) -> None:
        self.assertEqual(
            async_failure_message(b'{"state":"ERROR"}'), "async operation state ERROR"
        )

    def test_in_progress_and_success_are_not_failures(self) -> None:
        self.assertIsNone(async_failure_message(_APPLY_IN_PROGRESS_BODY))
        self.assertIsNone(async_failure_message(b'{"state":"SUCCESS"}'))

    def test_connection_manager_states_are_not_failures(self) -> None:
        for state in ("ACTIVE", "STOPPED", "STARTING"):
            self.assertIsNone(async_failure_message(f'{{"state":"{state}"}}'))

    def test_non_async_bodies_are_ignored(self) -> None:
        self.assertIsNone(async_failure_message(None))
        self.assertIsNone(async_failure_message(b'{"links":[]}'))
        self.assertIsNone(async_failure_message(b"<html>Bad Gateway</html>"))

    def test_oversized_bodies_are_not_parsed(self) -> None:
        # A stat view is megabytes; parsing every one of them would cost more
        # than the trace is worth, so the size cap short-circuits first.
        stat_view = b'{"state":"EXCEPTION","rows":"' + b"x" * 70000 + b'"}'
        self.assertIsNone(async_failure_message(stat_view))


class AppErrorsUrlTest(unittest.TestCase):
    def test_url_is_derived_from_the_session_prefix(self) -> None:
        self.assertEqual(app_errors_url_for(_APPLY_URL), _APP_ERRORS_URL)

    def test_url_without_a_session_segment_yields_none(self) -> None:
        # restpy indexes blindly here and raises an exception it then
        # swallows; returning None is the same decision, made explicitly.
        self.assertIsNone(app_errors_url_for("https://chassis/api/v1/sessions"))
        self.assertIsNone(app_errors_url_for("https://chassis/ixnetworkweb"))


class SlicePathTest(unittest.TestCase):
    def test_phase_is_slugified_into_the_file_name(self) -> None:
        path = build_slice_path(Path("/tmp/ixia_api_trace_1_2.jsonl"), 3, "pb/one two")
        self.assertEqual(path.name, "ixia_api_trace_1_2_03_pb_one_two.jsonl")

    def test_empty_phase_still_produces_a_name(self) -> None:
        self.assertEqual(slugify_phase("///"), "phase")


class TracerTestBase(unittest.TestCase):
    """Temp-directory plumbing shared by the tracer suites below.

    Split out from the cases so that inheriting the helpers does not also
    re-run every base case in each subclass.
    """

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(prefix="ixia_tracer_test_")
        self.addCleanup(self._tmpdir.cleanup)
        self.trace_path = Path(self._tmpdir.name) / "trace.jsonl"

    def _lines(self, index: int = 0, phase: str = "setup") -> list[dict[str, object]]:
        path = build_slice_path(self.trace_path, index, phase)
        if not path.exists():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line
        ]

    def _records(self, index: int = 0, phase: str = "setup") -> list[dict[str, object]]:
        return [
            line
            for line in self._lines(index, phase)
            if line["record_type"] == RECORD_TYPE_REST_CALL
        ]


class IxiaTracerTest(TracerTestBase):
    def test_successful_call_is_recorded_without_response_body(self) -> None:
        tracer = IxiaTracer(path=self.trace_path)
        span = tracer.begin(
            method="POST",
            url="https://chassis/api/v1/sessions/1/ixnetwork/topology",
            request_body='{"name": "Topology 1"}',
            op="create_topologies",
            phase="IXIA setup",
            playbook="pb1",
            testconfig="tc1",
        )
        tracer.finish(span, _response(201, b'{"links": []}'))
        closed = tracer.close()

        assert closed is not None
        self.assertEqual(closed.phase, "setup")
        self.assertEqual(closed.record_count, 1)
        self.assertEqual(closed.failure_count, 0)
        self.assertEqual(closed.dropped_count, 0)
        (record,) = self._records()
        self.assertEqual(record["record_type"], RECORD_TYPE_REST_CALL)
        self.assertEqual(record["method"], "POST")
        self.assertEqual(record["status"], 201)
        self.assertEqual(record["outcome"], "success")
        self.assertEqual(record["request_body"], '{"name": "Topology 1"}')
        self.assertIsNone(record["response_body"])
        self.assertIsNone(record["error"])
        self.assertIsNone(record["caused_by_seq"])
        self.assertEqual(record["op"], "create_topologies")
        self.assertEqual(record["phase"], "IXIA setup")
        self.assertEqual(record["playbook"], "pb1")
        self.assertEqual(record["testconfig"], "tc1")
        self.assertGreater(_number(record["started_at"]), 0)
        self.assertGreaterEqual(_number(record["duration_ms"]), 0)

    def test_non_2xx_response_body_is_captured(self) -> None:
        tracer = IxiaTracer(path=self.trace_path)
        span = tracer.begin(method="GET", url="https://chassis/api/v1/sessions")
        tracer.finish(span, _response(502, b"<html>Bad Gateway</html>"))
        closed = tracer.close()

        (record,) = self._records()
        self.assertEqual(record["status"], 502)
        self.assertEqual(record["outcome"], "failure")
        self.assertEqual(record["response_body"], "<html>Bad Gateway</html>")
        assert closed is not None
        self.assertEqual(closed.failure_count, 1)

    def test_response_body_capture_is_configurable(self) -> None:
        tracer = IxiaTracer(
            path=self.trace_path, response_body_capture=BodyCapture.ALWAYS
        )
        tracer.finish(
            tracer.begin(method="GET", url="https://chassis/api/v1/stats"),
            _response(200, b'{"rows": []}'),
        )
        tracer.close()

        (record,) = self._records()
        self.assertEqual(record["response_body"], '{"rows": []}')

    def test_bodies_are_truncated_at_the_configured_cap(self) -> None:
        tracer = IxiaTracer(
            path=self.trace_path,
            request_body_limit_bytes=64,
            response_body_limit_bytes=32,
        )
        tracer.finish(
            tracer.begin(
                method="POST",
                url="https://chassis/api/v1/sessions/1/ixnetwork/traffic",
                request_body="a" * 900,
            ),
            _response(500, b"b" * 900),
        )
        tracer.close()

        (record,) = self._records()
        request_body = _text(record["request_body"])
        response_body = _text(record["response_body"])
        self.assertTrue(request_body.startswith("a" * 64))
        self.assertIn("truncated: kept 64 of 900 bytes", request_body)
        self.assertTrue(response_body.startswith("b" * 32))
        self.assertIn("truncated: kept 32 of 900 bytes", response_body)

    def test_request_body_capture_can_be_disabled(self) -> None:
        tracer = IxiaTracer(
            path=self.trace_path, request_body_capture=BodyCapture.NEVER
        )
        tracer.finish(
            tracer.begin(
                method="POST",
                url="https://chassis/api/v1/sessions",
                request_body="secret payload",
            ),
            _response(200),
        )
        tracer.close()

        (record,) = self._records()
        self.assertIsNone(record["request_body"])

    def test_transport_exception_is_recorded_with_no_status(self) -> None:
        tracer = IxiaTracer(path=self.trace_path)
        span = tracer.begin(
            method="GET",
            url="https://chassis/api/v1/sessions/1/ixnetwork",
            request_body="payload",
        )
        tracer.fail(span, TimeoutError("read timed out"))
        tracer.close()

        (record,) = self._records()
        self.assertIsNone(record["status"])
        self.assertEqual(record["outcome"], "failure")
        self.assertEqual(record["error"], "TimeoutError: read timed out")
        # An exception is an error outcome, so an ON_ERROR request policy
        # still keeps the payload that triggered it.
        self.assertEqual(record["request_body"], "payload")

    def test_concurrent_writers_produce_one_line_per_call(self) -> None:
        tracer = IxiaTracer(path=self.trace_path)
        calls_per_thread = 200
        barrier = threading.Barrier(2)

        def drive(label: str) -> None:
            barrier.wait()
            for index in range(calls_per_thread):
                span = tracer.begin(
                    method="GET", url=f"https://chassis/{label}/{index}"
                )
                tracer.finish(span, _response(200))

        threads = [
            threading.Thread(target=drive, args=("sampler",)),
            threading.Thread(target=drive, args=("main",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        closed = tracer.close()

        records = self._records()
        assert closed is not None
        self.assertEqual(closed.record_count, 2 * calls_per_thread)
        self.assertEqual(len(records), 2 * calls_per_thread)
        self.assertEqual(
            len({record["seq"] for record in records}), 2 * calls_per_thread
        )
        self.assertEqual(len({record["thread_id"] for record in records}), 2)

    def test_writes_after_close_are_dropped_not_raised(self) -> None:
        tracer = IxiaTracer(path=self.trace_path)
        tracer.finish(
            tracer.begin(method="GET", url="https://chassis/a"), _response(200)
        )
        tracer.close()
        tracer.finish(
            tracer.begin(method="GET", url="https://chassis/b"), _response(200)
        )

        self.assertEqual(len(self._records()), 1)
        self.assertIsNone(tracer.close())
        self.assertIsNone(tracer.rotate("pb1"))

    def test_unwritable_path_does_not_raise(self) -> None:
        tracer = IxiaTracer(path=Path(self._tmpdir.name) / "missing_dir" / "t.jsonl")
        tracer.finish(
            tracer.begin(method="GET", url="https://chassis/a"), _response(200)
        )
        closed = tracer.close()

        assert closed is not None
        self.assertEqual(closed.record_count, 0)
        self.assertEqual(closed.dropped_count, 1)

    def test_auth_credentials_never_reach_the_file(self) -> None:
        tracer = IxiaTracer(
            path=self.trace_path, response_body_capture=BodyCapture.ALWAYS
        )
        tracer.finish(
            tracer.begin(
                method="POST",
                url="https://chassis/api/v1/auth/session",
                request_body='{"username": "ixia_admin", "password": "hunter2"}',
            ),
            _response(200, b'{"apiKey": "5f4dcc3b"}'),
        )
        tracer.close()

        raw = build_slice_path(self.trace_path, 0, "setup").read_text(encoding="utf-8")
        self.assertNotIn("hunter2", raw)
        self.assertNotIn("ixia_admin", raw)
        self.assertNotIn("5f4dcc3b", raw)
        (record,) = self._records()
        self.assertEqual(
            {"username": REDACTED_MARKER, "password": REDACTED_MARKER},
            json.loads(_text(record["request_body"])),
        )
        self.assertEqual(
            {"apiKey": REDACTED_MARKER},
            json.loads(_text(record["response_body"])),
        )

    def test_build_trace_path_is_unique_per_directory(self) -> None:
        path = build_trace_path(Path(self._tmpdir.name))
        self.assertEqual(path.parent, Path(self._tmpdir.name))
        self.assertTrue(path.name.startswith("ixia_api_trace_"))
        self.assertTrue(path.name.endswith(".jsonl"))


class AsyncOutcomeTest(TracerTestBase):
    def test_exception_inside_http_202_is_a_failure(self) -> None:
        tracer = IxiaTracer(path=self.trace_path)
        tracer.finish(
            tracer.begin(
                method="POST",
                url=_APPLY_URL,
                request_body=_APPLY_BODY,
                op="start_traffic",
            ),
            _response(202, _APPLY_EXCEPTION_BODY),
        )
        closed = tracer.close()

        (record,) = self._records()
        self.assertEqual(record["status"], 202)
        self.assertEqual(record["outcome"], "failure")
        self.assertEqual(record["error"], "Error in L2/L3 Traffic Apply")
        # The body is what Keysight needs and an HTTP-status rule drops it.
        self.assertEqual(record["response_body"], _APPLY_EXCEPTION_BODY.decode("utf-8"))
        assert closed is not None
        self.assertEqual(closed.failure_count, 1)

    def test_in_progress_inside_http_202_is_a_success(self) -> None:
        tracer = IxiaTracer(path=self.trace_path)
        tracer.finish(
            tracer.begin(method="POST", url=_APPLY_URL, request_body=_APPLY_BODY),
            _response(202, _APPLY_IN_PROGRESS_BODY),
        )
        closed = tracer.close()

        (record,) = self._records()
        self.assertEqual(record["outcome"], "success")
        self.assertIsNone(record["response_body"])
        assert closed is not None
        self.assertEqual(closed.failure_count, 0)

    def test_exception_on_a_poll_get_is_a_failure(self) -> None:
        # `_poll` walks IN_PROGRESS to a terminal state on a 200 GET, so the
        # failure can arrive on the poll rather than on the original POST.
        tracer = IxiaTracer(path=self.trace_path)
        tracer.finish(
            tracer.begin(method="GET", url=f"{_SESSION}/operations/apply/1"),
            _response(200, _APPLY_EXCEPTION_BODY),
        )
        tracer.close()

        (record,) = self._records()
        self.assertEqual(record["status"], 200)
        self.assertEqual(record["outcome"], "failure")
        self.assertEqual(record["error"], "Error in L2/L3 Traffic Apply")


class AppErrorsCaptureTest(TracerTestBase):
    def _tracer(
        self,
        cooldown_seconds: float = 60.0,
        max_fetches: int = 20,
    ) -> tuple[IxiaTracer, list[str]]:
        fetched: list[str] = []

        def fetch(url: str) -> object:
            fetched.append(url)
            return _response(200, _APP_ERRORS_BODY)

        tracer = IxiaTracer(
            path=self.trace_path,
            app_errors_cooldown_seconds=cooldown_seconds,
            max_app_errors_fetches=max_fetches,
        )
        tracer.set_app_errors_fetch(fetch)
        return (tracer, fetched)

    def _fail_apply(self, tracer: IxiaTracer, op: str = "start_traffic") -> None:
        tracer.finish(
            tracer.begin(
                method="POST", url=_APPLY_URL, request_body=_APPLY_BODY, op=op
            ),
            _response(202, _APPLY_EXCEPTION_BODY),
        )

    def test_app_errors_body_is_kept_even_on_a_success(self) -> None:
        tracer = IxiaTracer(path=self.trace_path)
        tracer.finish(
            tracer.begin(method="GET", url=_APP_ERRORS_URL),
            _response(200, _APP_ERRORS_BODY),
        )
        tracer.close()

        (record,) = self._records()
        self.assertEqual(record["outcome"], "success")
        self.assertEqual(record["response_body"], _APP_ERRORS_BODY.decode("utf-8"))

    def test_failure_triggers_an_app_errors_fetch_linked_to_its_cause(self) -> None:
        tracer, fetched = self._tracer()
        self._fail_apply(tracer)
        tracer.close()

        self.assertEqual(fetched, [_APP_ERRORS_URL])
        failure, app_errors = self._records()
        self.assertEqual(failure["outcome"], "failure")
        self.assertEqual(app_errors["url"], _APP_ERRORS_URL)
        self.assertEqual(app_errors["caused_by_seq"], failure["seq"])
        self.assertEqual(app_errors["op"], "start_traffic")
        self.assertEqual(app_errors["response_body"], _APP_ERRORS_BODY.decode("utf-8"))

    def test_repeated_identical_failures_fetch_once_per_cooldown(self) -> None:
        # The real run failed `start_traffic` 15 times in 98 seconds. Without
        # this, that is 15 extra REST calls into an already-sick chassis.
        tracer, fetched = self._tracer(cooldown_seconds=600.0)
        for _ in range(15):
            self._fail_apply(tracer)
        tracer.close()

        self.assertEqual(len(fetched), 1)
        self.assertEqual(len(self._records()), 16)

    def test_a_different_failure_gets_its_own_fetch(self) -> None:
        tracer, fetched = self._tracer(cooldown_seconds=600.0)
        self._fail_apply(tracer, op="start_traffic")
        self._fail_apply(tracer, op="stop_traffic")
        tracer.close()

        self.assertEqual(len(fetched), 2)

    def test_total_fetches_are_capped(self) -> None:
        tracer, fetched = self._tracer(cooldown_seconds=0.0, max_fetches=3)
        for index in range(10):
            self._fail_apply(tracer, op=f"op_{index}")
        tracer.close()

        self.assertEqual(len(fetched), 3)

    def test_a_failing_fetch_is_recorded_and_does_not_recurse(self) -> None:
        attempts: list[str] = []

        def fetch(url: str) -> object:
            attempts.append(url)
            raise ConnectionError("chassis is gone")

        tracer = IxiaTracer(path=self.trace_path)
        tracer.set_app_errors_fetch(fetch)
        self._fail_apply(tracer)
        tracer.close()

        self.assertEqual(len(attempts), 1)
        _failure, app_errors = self._records()
        self.assertEqual(app_errors["outcome"], "failure")
        self.assertIn("appErrors fetch failed", _text(app_errors["error"]))

    def test_a_fetch_that_re_enters_the_tracer_does_not_loop(self) -> None:
        """The fetch is issued from inside the transport wrapper it traces.

        `Ixia` hands the tracer the un-wrapped transport so this cannot
        happen, but a future caller could wire the wrapped one. The
        reentrancy flag has to hold on its own.
        """
        attempts: list[str] = []

        def reentrant_fetch(url: str) -> object:
            attempts.append(url)
            # Exactly what the traced transport does on the way back.
            tracer.finish(
                tracer.begin(method="GET", url=url, op="start_traffic"),
                _response(202, _APPLY_EXCEPTION_BODY),
            )
            return _response(200, _APP_ERRORS_BODY)

        tracer = IxiaTracer(path=self.trace_path)
        tracer.set_app_errors_fetch(reentrant_fetch)
        self._fail_apply(tracer)
        tracer.close()

        self.assertEqual(len(attempts), 1)

    def test_no_fetch_is_configured_means_no_extra_call(self) -> None:
        tracer = IxiaTracer(path=self.trace_path)
        self._fail_apply(tracer)
        tracer.close()

        self.assertEqual(len(self._records()), 1)


class PhaseSliceTest(TracerTestBase):
    def _call(self, tracer: IxiaTracer, url: str) -> None:
        tracer.finish(tracer.begin(method="GET", url=url), _response(200))

    def test_each_phase_lands_in_its_own_file(self) -> None:
        tracer = IxiaTracer(path=self.trace_path)
        self._call(tracer, "https://chassis/setup")
        setup = tracer.rotate("pb1")
        self._call(tracer, "https://chassis/pb1/a")
        self._call(tracer, "https://chassis/pb1/b")
        pb1 = tracer.rotate(TEARDOWN_PHASE)
        self._call(tracer, "https://chassis/teardown")
        teardown = tracer.close()

        assert setup is not None and pb1 is not None and teardown is not None
        self.assertEqual(
            [(s.index, s.phase, s.record_count) for s in tracer.slices],
            [(0, "setup", 1), (1, "pb1", 2), (2, "teardown", 1)],
        )
        self.assertEqual(len(self._records(0, "setup")), 1)
        self.assertEqual(len(self._records(1, "pb1")), 2)
        self.assertEqual(len(self._records(2, "teardown")), 1)
        self.assertEqual(setup.path, build_slice_path(self.trace_path, 0, "setup"))

    def test_failures_are_counted_per_slice(self) -> None:
        tracer = IxiaTracer(path=self.trace_path)
        tracer.rotate("pb1")
        tracer.finish(
            tracer.begin(method="POST", url=_APPLY_URL),
            _response(202, _APPLY_EXCEPTION_BODY),
        )
        self._call(tracer, "https://chassis/pb1/ok")
        pb1 = tracer.close()

        assert pb1 is not None
        self.assertEqual((pb1.record_count, pb1.failure_count), (2, 1))
        self.assertEqual(tracer.slices[0].record_count, 0)

    def test_a_setup_only_run_still_closes_its_slice(self) -> None:
        # Ixia setup that dies before the first playbook: no rotation ever
        # happens, and the setup slice is the only evidence there is.
        tracer = IxiaTracer(path=self.trace_path)
        self._call(tracer, "https://chassis/setup")
        closed = tracer.close()

        assert closed is not None
        self.assertEqual(closed.phase, "setup")
        self.assertEqual(closed.record_count, 1)
        self.assertEqual([s.phase for s in tracer.slices], ["setup"])
        self.assertTrue(closed.path.exists())

    def test_the_sequence_counter_is_continuous_across_slices(self) -> None:
        tracer = IxiaTracer(path=self.trace_path)
        self._call(tracer, "https://chassis/setup")
        tracer.rotate("pb1")
        self._call(tracer, "https://chassis/pb1")
        tracer.close()

        self.assertEqual(self._records(0, "setup")[0]["seq"], 1)
        self.assertEqual(self._records(1, "pb1")[0]["seq"], 2)


class SessionPreambleTest(TracerTestBase):
    def _preamble(self) -> IxiaTraceSessionPreamble:
        return IxiaTraceSessionPreamble(
            record_type=RECORD_TYPE_SESSION_PREAMBLE,
            seq=0,
            recorded_at=1787705237.0,
            chassis_ip="2401:db00::3023",
            session_id=17,
            session_name="taac_run",
            restpy_version="1.9.0",
            is_uhd_chassis=False,
            force_take_port_ownership=True,
            ports=(
                IxiaTracePortMapping(
                    dut_interface="gtsw007:eth1/1/1",
                    chassis_ip="2401:db00::3023",
                    slot=2,
                    port=5,
                    vport_name="VPORT_GTSW007_ETH1_1_1",
                ),
            ),
            traffic_items=("TI_A_TO_B_IPV6",),
        )

    def test_preamble_is_written_with_seq_zero(self) -> None:
        tracer = IxiaTracer(path=self.trace_path)
        tracer.set_session_preamble(self._preamble())
        tracer.close()

        (line,) = self._lines()
        self.assertEqual(line["record_type"], RECORD_TYPE_SESSION_PREAMBLE)
        self.assertEqual(line["seq"], 0)
        self.assertEqual(line["session_id"], 17)
        self.assertEqual(line["restpy_version"], "1.9.0")
        self.assertTrue(line["force_take_port_ownership"])
        self.assertEqual(line["traffic_items"], ["TI_A_TO_B_IPV6"])
        self.assertEqual(
            line["ports"],
            [
                {
                    "dut_interface": "gtsw007:eth1/1/1",
                    "chassis_ip": "2401:db00::3023",
                    "slot": 2,
                    "port": 5,
                    "vport_name": "VPORT_GTSW007_ETH1_1_1",
                }
            ],
        )

    def test_every_later_slice_starts_with_the_preamble(self) -> None:
        tracer = IxiaTracer(path=self.trace_path)
        tracer.set_session_preamble(self._preamble())
        tracer.rotate("pb1")
        tracer.finish(
            tracer.begin(method="GET", url="https://chassis/pb1"), _response(200)
        )
        tracer.close()

        pb1_lines = self._lines(1, "pb1")
        self.assertEqual(pb1_lines[0]["record_type"], RECORD_TYPE_SESSION_PREAMBLE)
        self.assertEqual(pb1_lines[1]["record_type"], RECORD_TYPE_REST_CALL)
        # A preamble is context, not a REST call, so it does not inflate the
        # per-phase call count in the report.
        self.assertEqual(tracer.slices[1].record_count, 1)

    def test_a_slice_opened_before_the_preamble_is_known_is_not_headed(self) -> None:
        tracer = IxiaTracer(path=self.trace_path)
        tracer.finish(
            tracer.begin(method="GET", url="https://chassis/setup"), _response(200)
        )
        tracer.set_session_preamble(self._preamble())
        tracer.close()

        kinds = [line["record_type"] for line in self._lines()]
        self.assertEqual(kinds, [RECORD_TYPE_REST_CALL, RECORD_TYPE_SESSION_PREAMBLE])


class RealRunReplayTest(TracerTestBase):
    """Replay of the run that motivated this change.

    Fixtures are shaped after `/tmp/ixia_api_trace_1052956_1787705237.jsonl`
    (2621 records, `start_traffic` failing 15 times between 18:03:52 and
    18:05:30) rather than read from it, so the test does not depend on a file
    that only exists on one host.
    """

    def _replay(self, tracer: IxiaTracer) -> None:
        tracer.finish(
            tracer.begin(
                method="POST",
                url=f"{_SESSION}/ixnetwork/operations/select?xpath=false",
                request_body='{"selects": [{"from": "/api/v1/sessions/17/ixnetwork"}]}',
                op="start_traffic",
                playbook="test_icepack_gtsw007_warmboot_troubleshooting",
                testconfig="NPI_ICEPACK_GTSW007_WARMBOOT_TROUBLESHOOTING_TEST_CONFIG",
            ),
            _response(202, b'{"state":"SUCCESS","result":[]}'),
        )
        for _ in range(15):
            tracer.finish(
                tracer.begin(
                    method="POST",
                    url=_APPLY_URL,
                    request_body=_APPLY_BODY,
                    op="start_traffic",
                    playbook="test_icepack_gtsw007_warmboot_troubleshooting",
                    testconfig=(
                        "NPI_ICEPACK_GTSW007_WARMBOOT_TROUBLESHOOTING_TEST_CONFIG"
                    ),
                ),
                _response(202, _APPLY_EXCEPTION_BODY),
            )
        tracer.finish(
            tracer.begin(
                method="DELETE",
                url=(
                    "https://[2401:db00::3023]/ixnetworkweb/api/v1/sessions/17"
                    "/ixnetwork/files?filename=taac_session_diagnostics_d0f72f"
                ),
            ),
            _response(
                404,
                b'{"method":"DELETE","errors":[{"code":404,"detail":'
                b'"File ... does not exist on the system"}]}',
            ),
        )

    def test_every_failed_apply_is_visible_after_the_fix(self) -> None:
        fetched: list[str] = []

        def fetch(url: str) -> object:
            fetched.append(url)
            return _response(200, _APP_ERRORS_BODY)

        tracer = IxiaTracer(path=self.trace_path, app_errors_cooldown_seconds=600.0)
        tracer.set_app_errors_fetch(fetch)
        self._replay(tracer)
        closed = tracer.close()

        records = self._records()
        applies = [r for r in records if r["url"] == _APPLY_URL]
        self.assertEqual(len(applies), 15)
        self.assertTrue(all(r["status"] == 202 for r in applies))
        self.assertTrue(all(r["outcome"] == "failure" for r in applies))
        self.assertTrue(
            all(r["error"] == "Error in L2/L3 Traffic Apply" for r in applies)
        )
        self.assertTrue(
            all(
                r["response_body"] == _APPLY_EXCEPTION_BODY.decode("utf-8")
                for r in applies
            )
        )
        # One appErrors fetch for the repeated apply failure, one for the
        # unrelated 404 on diagnostics cleanup.
        self.assertEqual(len(fetched), 2)
        app_errors = [r for r in records if r["url"] == _APP_ERRORS_URL]
        self.assertEqual(len(app_errors), 1)
        self.assertEqual(app_errors[0]["caused_by_seq"], applies[0]["seq"])
        assert closed is not None
        # 15 applies + 1 404 + 2 fetch replies, of which the 404 and the
        # applies failed. The original trace reported zero of them.
        self.assertEqual(closed.record_count, 19)
        self.assertEqual(closed.failure_count, 16)
