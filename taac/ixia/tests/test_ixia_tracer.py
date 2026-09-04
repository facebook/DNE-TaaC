# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Unit tests for the IxNetwork REST API tracer.

The transport-extraction tests pin the two calling conventions
`ixnetwork_restpy` uses against `requests.Session.request`: keyword-only via
`Connection._request`, and positional `("GET", url, ...)` from the
file-transfer, 409-retry and async-poll helpers. Getting either wrong drops
whole classes of calls out of the trace silently.
"""

import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from taac.ixia.ixia_tracer import (
    BodyCapture,
    build_trace_path,
    clip_body,
    extract_request_body,
    extract_request_method_and_url,
    IxiaTracer,
    redact_credentials,
    REDACTED_MARKER,
)

_AUTH_URL: str = "https://chassis/api/v1/auth/session"
_TOPOLOGY_URL: str = "https://chassis/api/v1/sessions/1/ixnetwork/topology"


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


class IxiaTracerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(prefix="ixia_tracer_test_")
        self.addCleanup(self._tmpdir.cleanup)
        self.trace_path = Path(self._tmpdir.name) / "trace.jsonl"

    def _records(self) -> list[dict[str, object]]:
        return [
            json.loads(line)
            for line in self.trace_path.read_text(encoding="utf-8").splitlines()
            if line
        ]

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
        summary = tracer.close()

        self.assertEqual(summary.record_count, 1)
        self.assertEqual(summary.dropped_count, 0)
        (record,) = self._records()
        self.assertEqual(record["method"], "POST")
        self.assertEqual(record["status"], 201)
        self.assertEqual(record["request_body"], '{"name": "Topology 1"}')
        self.assertIsNone(record["response_body"])
        self.assertIsNone(record["error"])
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
        tracer.close()

        (record,) = self._records()
        self.assertEqual(record["status"], 502)
        self.assertEqual(record["response_body"], "<html>Bad Gateway</html>")

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
        summary = tracer.close()

        records = self._records()
        self.assertEqual(summary.record_count, 2 * calls_per_thread)
        self.assertEqual(len(records), 2 * calls_per_thread)
        self.assertEqual(
            len({record["seq"] for record in records}), 2 * calls_per_thread
        )
        self.assertEqual(len({record["thread_id"] for record in records}), 2)

    def test_writes_after_close_are_counted_not_raised(self) -> None:
        tracer = IxiaTracer(path=self.trace_path)
        tracer.finish(
            tracer.begin(method="GET", url="https://chassis/a"), _response(200)
        )
        tracer.close()
        tracer.finish(
            tracer.begin(method="GET", url="https://chassis/b"), _response(200)
        )

        self.assertEqual(len(self._records()), 1)
        self.assertEqual(tracer.close().dropped_count, 1)

    def test_unwritable_path_does_not_raise(self) -> None:
        tracer = IxiaTracer(path=Path(self._tmpdir.name) / "missing_dir" / "t.jsonl")
        tracer.finish(
            tracer.begin(method="GET", url="https://chassis/a"), _response(200)
        )
        summary = tracer.close()

        self.assertEqual(summary.record_count, 0)
        self.assertEqual(summary.dropped_count, 1)

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

        raw = self.trace_path.read_text(encoding="utf-8")
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
