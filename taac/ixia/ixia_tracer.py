# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""JSONL trace of every IxNetwork REST call TAAC issues.

Every IxNetwork operation `ixnetwork_restpy` performs funnels through
`requests.Session.request` on `session.TestPlatform._connection._session`:
`connection.py` routes `_read`/`_create`/`_update`/`_delete`/`_execute`/
`_options` into `_send_recv`, and the file-transfer and async-poll helpers
call the transport directly. `Ixia._install_request_deadline_wrapper_locked`
already replaces that one callable, so wrapping it there records 100% of the
REST traffic without instrumenting a single call site.

`started_at` is wall clock rather than a monotonic reading because that is
what Keysight correlates a trace against in their own server-side logs.

Every body is passed through `redact_credentials` on its way to the file.
The trace is uploaded to Manifold, attached to the test report and handed to
Keysight, so a credential written here is a disclosure to an external vendor.
"""

from __future__ import annotations

import enum
import json
import logging
import os
import tempfile
import threading
import time
import typing as t
from dataclasses import asdict, dataclass
from pathlib import Path


class BodyCapture(enum.Enum):
    NEVER = "never"
    ON_ERROR = "on_error"
    ALWAYS = "always"


DEFAULT_REQUEST_BODY_LIMIT_BYTES: int = 4096
DEFAULT_RESPONSE_BODY_LIMIT_BYTES: int = 8192

# A stat-view GET response is megabytes, so responses are captured only when
# the call went wrong. Requests are small enough to keep unconditionally.
DEFAULT_REQUEST_BODY_CAPTURE: BodyCapture = BodyCapture.ALWAYS
DEFAULT_RESPONSE_BODY_CAPTURE: BodyCapture = BodyCapture.ON_ERROR

_SUCCESS_STATUS_RANGE: range = range(200, 300)

REDACTED_MARKER: str = "[REDACTED]"

# `TestPlatform.Authenticate` POSTs `{"username", "password", "ignorePolicy"}`
# here and reads `apiKey` back out of the reply
# (`ixnetwork_restpy/testplatform/testplatform.py:125-130`);
# `Connection._determine_test_platform` probes the same path with an
# empty-credential body of the same shape (`connection.py:188-210`). Both go
# through the transport callable this module traces.
AUTH_URL_PATH: str = "/auth/session"

# Normalized (`_` and `-` stripped, lowercased) JSON keys whose value is a
# credential. `apikey` is what the auth reply carries; the rest are the
# spellings restpy and the IxNetwork schema use for a secret elsewhere.
_CREDENTIAL_KEYS: frozenset[str] = frozenset(
    {"password", "passwd", "pwd", "apikey", "xapikey", "secret"}
)

# The auth exchange is a few hundred bytes and a config POST is kilobytes, so
# this covers everything that can carry the API credential with room to
# spare. A stat view is megabytes and parsing one on every failed call would
# cost more than the trace is worth, so above this bound only the URL rule
# applies.
_MAX_CREDENTIAL_SCAN_BYTES: int = 262144


def is_auth_url(url: str) -> bool:
    return AUTH_URL_PATH in url.lower()


def redact_credentials(body: object, url: str) -> object:
    """Strip credentials out of a body before it can reach the trace file.

    Two rules apply, because either one alone leaves a hole:

    - By key, anywhere in the payload, so a credential on a path this module
      does not know about is still caught.
    - By URL, blanking every string on the auth path, so a payload restpy
      reshapes later, or one too large or too malformed to parse, stays
      covered without this module tracking the schema.

    Values are replaced with `REDACTED_MARKER` rather than dropped, so the
    trace still shows that an auth call happened and which fields it carried.
    """
    if body is None:
        return None
    on_auth_path = is_auth_url(url)
    parsed = _parse_json_body(body)
    if parsed is None:
        return REDACTED_MARKER if on_auth_path else body
    redacted, changed = _redact_values(parsed, redact_every_string=on_auth_path)
    if not changed:
        return body
    return json.dumps(redacted, separators=(",", ":"), default=str)


def _parse_json_body(body: object) -> object | None:
    if not isinstance(body, (bytes, bytearray, str)):
        return None
    if len(body) > _MAX_CREDENTIAL_SCAN_BYTES:
        return None
    try:
        parsed = json.loads(body)
    except ValueError:
        # Covers `json.JSONDecodeError` and the `UnicodeDecodeError` a
        # non-UTF-8 body raises; both subclass `ValueError`.
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


def _redact_values(value: object, redact_every_string: bool) -> tuple[object, bool]:
    if isinstance(value, dict):
        redacted_items: dict[object, object] = {}
        changed = False
        for key, item in value.items():
            if _is_credential_key(key) or (
                redact_every_string and isinstance(item, str)
            ):
                redacted_items[key] = REDACTED_MARKER
                changed = True
                continue
            redacted_items[key], item_changed = _redact_values(
                item, redact_every_string
            )
            changed = changed or item_changed
        return (redacted_items, changed)
    if isinstance(value, list):
        results = [_redact_values(item, redact_every_string) for item in value]
        return ([item for item, _ in results], any(changed for _, changed in results))
    return (value, False)


def _is_credential_key(key: object) -> bool:
    return (
        isinstance(key, str)
        and key.replace("_", "").replace("-", "").lower() in _CREDENTIAL_KEYS
    )


@dataclass(frozen=True)
class IxiaTraceRecord:
    """One completed REST call, serialized as one JSONL line."""

    seq: int
    thread_id: int
    started_at: float
    duration_ms: float
    method: str
    url: str
    request_body: str | None
    status: int | None
    response_body: str | None
    error: str | None
    op: str | None
    phase: str | None
    playbook: str | None
    testconfig: str | None


@dataclass(frozen=True)
class IxiaTraceSpan:
    """An in-flight REST call, handed back to `finish` or `fail`.

    `request_body` holds the caller's raw `data` argument rather than a
    rendered string so that a `BodyCapture.ON_ERROR` request policy can decide
    after the response arrives. The caller keeps the same object alive for the
    duration of the call, so holding the reference costs nothing.
    """

    seq: int
    thread_id: int
    started_at: float
    started_monotonic: float
    method: str
    url: str
    request_body: object
    op: str | None
    phase: str | None
    playbook: str | None
    testconfig: str | None


@dataclass(frozen=True)
class IxiaTraceSummary:
    path: Path
    record_count: int
    dropped_count: int


def extract_request_method_and_url(
    args: t.Sequence[object],
    kwargs: t.Mapping[str, object],
) -> tuple[str, str]:
    """Pull method and URL out of a `requests.Session.request` call.

    `ixnetwork_restpy` uses both calling conventions: `Connection._request`
    forwards everything as keywords, while the file-transfer, 409-retry and
    async-poll helpers pass `("GET", url, ...)` positionally.
    """
    method = kwargs.get("method")
    if method is None and args:
        method = args[0]
    url = kwargs.get("url")
    if url is None and len(args) > 1:
        url = args[1]
    return ("" if method is None else str(method), "" if url is None else str(url))


def extract_request_body(kwargs: t.Mapping[str, object]) -> object:
    """The request payload, which restpy always passes as the `data` keyword."""
    return kwargs.get("data")


def build_trace_path(directory: Path | None = None) -> Path:
    base = directory if directory is not None else Path(tempfile.gettempdir())
    return base / f"ixia_api_trace_{os.getpid()}_{int(time.time())}.jsonl"


def clip_body(body: object, limit_bytes: int) -> str | None:
    """Render a request or response body as text, capped at `limit_bytes`.

    A truncated value carries an explicit marker naming the original size so a
    reader never mistakes a clipped payload for the real one.
    """
    if body is None:
        return None
    raw = (
        bytes(body)
        if isinstance(body, (bytes, bytearray))
        else str(body).encode("utf-8", errors="replace")
    )
    if len(raw) <= limit_bytes:
        return raw.decode("utf-8", errors="replace")
    kept = raw[:limit_bytes].decode("utf-8", errors="replace")
    return f"{kept}...[truncated: kept {limit_bytes} of {len(raw)} bytes]"


def _is_error_outcome(status: int | None, error: str | None) -> bool:
    return error is not None or status is None or status not in _SUCCESS_STATUS_RANGE


class IxiaTracer:
    """Appends one JSON object per IxNetwork REST call to a JSONL file.

    Thread-safe by necessity, not by caution: `TaacIxia` samples chassis
    statistics from a background thread (2s by default) concurrently with
    main-thread operations, so both the sequence counter and the file handle
    are lock-guarded.

    No method raises. A tracer defect must never turn a green test red, which
    is the same discipline `Ixia._emit_inband_502` applies to its Scuba write.
    """

    def __init__(
        self,
        path: Path,
        logger: logging.Logger | None = None,
        request_body_capture: BodyCapture = DEFAULT_REQUEST_BODY_CAPTURE,
        response_body_capture: BodyCapture = DEFAULT_RESPONSE_BODY_CAPTURE,
        request_body_limit_bytes: int = DEFAULT_REQUEST_BODY_LIMIT_BYTES,
        response_body_limit_bytes: int = DEFAULT_RESPONSE_BODY_LIMIT_BYTES,
    ) -> None:
        self.path = path
        self._logger: logging.Logger = logger or logging.getLogger(__name__)
        self._request_body_capture = request_body_capture
        self._response_body_capture = response_body_capture
        self._request_body_limit_bytes = request_body_limit_bytes
        self._response_body_limit_bytes = response_body_limit_bytes
        self._lock = threading.Lock()
        self._handle: t.IO[str] | None = None
        self._closed = False
        self._seq = 0
        self._written = 0
        self._dropped = 0
        self._write_failure_logged = False

    def begin(
        self,
        method: str,
        url: str,
        request_body: object = None,
        op: str | None = None,
        phase: str | None = None,
        playbook: str | None = None,
        testconfig: str | None = None,
    ) -> IxiaTraceSpan:
        with self._lock:
            self._seq += 1
            seq = self._seq
        return IxiaTraceSpan(
            seq=seq,
            thread_id=threading.get_ident(),
            started_at=time.time(),
            started_monotonic=time.monotonic(),
            method=method,
            url=url,
            request_body=request_body,
            op=op,
            phase=phase,
            playbook=playbook,
            testconfig=testconfig,
        )

    def finish(self, span: IxiaTraceSpan, response: object) -> None:
        self._record(span, response=response, error=None)

    def fail(self, span: IxiaTraceSpan, error: BaseException) -> None:
        self._record(
            span, response=None, error=f"{type(error).__name__}: {error!s}"[:1024]
        )

    def close(self) -> IxiaTraceSummary:
        """Flush and release the file; further calls are counted as dropped."""
        with self._lock:
            self._closed = True
            handle, self._handle = self._handle, None
            summary = IxiaTraceSummary(
                path=self.path,
                record_count=self._written,
                dropped_count=self._dropped,
            )
        if handle is not None:
            try:
                handle.close()
            except OSError as exc:
                self._logger.warning(
                    f"ixia api trace: close failed on {self.path}: {exc!r}"
                )
        return summary

    def _record(
        self,
        span: IxiaTraceSpan,
        response: object,
        error: str | None,
    ) -> None:
        try:
            line = json.dumps(
                asdict(self._build_record(span, response, error)),
                separators=(",", ":"),
                default=str,
            )
        except Exception as exc:
            self._count_drop()
            self._log_first_failure(f"ixia api trace: record build failed: {exc!r}")
            return
        self._write(line)

    def _build_record(
        self,
        span: IxiaTraceSpan,
        response: object,
        error: str | None,
    ) -> IxiaTraceRecord:
        status = getattr(response, "status_code", None)
        status = int(status) if isinstance(status, int) else None
        is_error = _is_error_outcome(status, error)
        return IxiaTraceRecord(
            seq=span.seq,
            thread_id=span.thread_id,
            started_at=span.started_at,
            duration_ms=round((time.monotonic() - span.started_monotonic) * 1000, 3),
            method=span.method,
            url=span.url,
            request_body=self._render_body(
                span.request_body,
                self._request_body_capture,
                self._request_body_limit_bytes,
                is_error,
                span.url,
            ),
            status=status,
            response_body=self._render_body(
                _response_payload(response),
                self._response_body_capture,
                self._response_body_limit_bytes,
                is_error,
                span.url,
            ),
            error=error,
            op=span.op,
            phase=span.phase,
            playbook=span.playbook,
            testconfig=span.testconfig,
        )

    def _render_body(
        self,
        body: object,
        capture: BodyCapture,
        limit_bytes: int,
        is_error: bool,
        url: str,
    ) -> str | None:
        if capture is BodyCapture.NEVER:
            return None
        if capture is BodyCapture.ON_ERROR and not is_error:
            return None
        return clip_body(redact_credentials(body, url), limit_bytes)

    def _write(self, line: str) -> None:
        with self._lock:
            if self._closed:
                self._dropped += 1
                return
            try:
                handle = self._open_handle_locked()
                handle.write(f"{line}\n")
                # Flushed per line so a hard kill mid-run still leaves every
                # completed call on disk, which is the run the trace is for.
                handle.flush()
            except OSError as exc:
                self._dropped += 1
                self._log_first_failure(
                    f"ixia api trace: write failed on {self.path}: {exc!r}"
                )
                return
            self._written += 1

    def _open_handle_locked(self) -> t.IO[str]:
        handle = self._handle
        if handle is None:
            handle = self.path.open("a", encoding="utf-8")
            self._handle = handle
        return handle

    def _count_drop(self) -> None:
        with self._lock:
            self._dropped += 1

    def _log_first_failure(self, message: str) -> None:
        if self._write_failure_logged:
            return
        self._write_failure_logged = True
        self._logger.warning(f"{message} (further tracer failures are silent)")


def _response_payload(response: object) -> object:
    if response is None:
        return None
    content = getattr(response, "content", None)
    return content if content is not None else getattr(response, "text", None)
