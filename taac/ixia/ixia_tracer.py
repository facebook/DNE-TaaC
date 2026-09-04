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

Two things make an HTTP-status-only trace blind to real IxNetwork failures,
and both are handled here.

1. IxNetwork signals async failure INSIDE a 2xx. `Traffic.Apply` POSTs and
   gets HTTP 202 carrying `{"state": "EXCEPTION", "result": " Error in
   L2/L3 Traffic Apply\\n"}`. Only later, in `_process_response_status_code`
   (`connection.py:445-447`), does restpy mutate `response.status_code` to
   400 -- long after the transport call this module wraps has returned. So
   `outcome` is derived from the response BODY, not the status.

2. restpy's own `/globals/appErrors/error` enrichment is dead on the async
   path: it derives the URL from `url` (`connection.py:462`), which on that
   path is `self._async_operation.request` and is `None` unless the caller
   opted into `async_operation: True`. The resulting `AttributeError` is
   swallowed by a bare `except` at `:489-490`. This module therefore fetches
   appErrors itself on a failure outcome.

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
import re
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


class TraceOutcome(enum.Enum):
    SUCCESS = "success"
    FAILURE = "failure"


RECORD_TYPE_REST_CALL: str = "rest_call"
RECORD_TYPE_SESSION_PREAMBLE: str = "session_preamble"

SETUP_PHASE: str = "setup"
TEARDOWN_PHASE: str = "teardown"

APP_ERRORS_PATH_SUFFIX: str = "/globals/appErrors/error"

DEFAULT_REQUEST_BODY_LIMIT_BYTES: int = 4096
DEFAULT_RESPONSE_BODY_LIMIT_BYTES: int = 8192
# appErrors replies are the payload the trace exists for, so they get their
# own, larger cap than an incidental error body.
DEFAULT_APP_ERRORS_BODY_LIMIT_BYTES: int = 32768

# A stat-view GET response is megabytes, so responses are captured only when
# the call went wrong. Requests are small enough to keep unconditionally.
DEFAULT_REQUEST_BODY_CAPTURE: BodyCapture = BodyCapture.ALWAYS
DEFAULT_RESPONSE_BODY_CAPTURE: BodyCapture = BodyCapture.ON_ERROR

# The 15 `start_traffic` failures of the run that motivated appErrors capture
# arrived over 98 seconds. One fetch per distinct (op, error) per cooldown
# turns that into 2 extra REST calls instead of 15.
DEFAULT_APP_ERRORS_COOLDOWN_SECONDS: float = 60.0
DEFAULT_MAX_APP_ERRORS_FETCHES: int = 20

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


# `_poll` treats these as "not a failure": IN_PROGRESS keeps polling, SUCCESS
# returns the result, and ACTIVE/STOPPED/STARTING are terminal successes on
# the connection_manager platform (`connection.py:636-657`). Every other
# state falls through to `_process_response_status_code(async_status=True)`,
# which raises.
_ASYNC_SUCCESS_STATES: frozenset[str] = frozenset(
    {"IN_PROGRESS", "SUCCESS", "ACTIVE", "STOPPED", "STARTING"}
)

# An async status reply is a handful of short fields. Anything larger is a
# stat view or a config export, and running `json.loads` over megabytes on
# every call would cost more than the trace is worth.
_ASYNC_STATUS_MAX_BYTES: int = 65536
_STATE_KEY_MARKER: bytes = b'"state"'

_MAX_PHASE_SLUG_LENGTH: int = 48
_MAX_ERROR_LENGTH: int = 1024
_UNSAFE_PHASE_CHARS: t.Pattern[str] = re.compile(r"[^0-9A-Za-z._-]+")

AppErrorsFetch = t.Callable[[str], object]


@dataclass(frozen=True)
class IxiaTracePortMapping:
    """One physical Ixia port, its vport and the DUT interface behind it."""

    dut_interface: str
    chassis_ip: str
    slot: int
    port: int
    vport_name: str


@dataclass(frozen=True)
class IxiaTraceSessionPreamble:
    """Everything Keysight needs to place a trace against a live chassis.

    Written as the first line of every slice file (and again whenever the
    session identity changes, e.g. after a reconnect), so any single slice
    handed to Keysight is self-contained.
    """

    record_type: str
    seq: int
    recorded_at: float
    chassis_ip: str | None
    session_id: int | None
    session_name: str | None
    restpy_version: str | None
    is_uhd_chassis: bool | None
    force_take_port_ownership: bool | None
    ports: tuple[IxiaTracePortMapping, ...]
    traffic_items: tuple[str, ...]


@dataclass(frozen=True)
class IxiaTraceRecord:
    """One completed REST call, serialized as one JSONL line."""

    record_type: str
    seq: int
    thread_id: int
    started_at: float
    duration_ms: float
    method: str
    url: str
    request_body: str | None
    status: int | None
    outcome: str
    response_body: str | None
    error: str | None
    op: str | None
    phase: str | None
    playbook: str | None
    testconfig: str | None
    caused_by_seq: int | None


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
class IxiaTraceSlice:
    """One completed phase slice: setup, a single test case, or teardown."""

    index: int
    phase: str
    path: Path
    record_count: int
    failure_count: int
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


def slugify_phase(phase: str) -> str:
    slug = _UNSAFE_PHASE_CHARS.sub("_", phase).strip("_")
    return slug[:_MAX_PHASE_SLUG_LENGTH] or "phase"


def build_slice_path(base: Path, index: int, phase: str) -> Path:
    return base.with_name(
        f"{base.stem}_{index:02d}_{slugify_phase(phase)}{base.suffix}"
    )


def is_app_errors_url(url: str) -> bool:
    return url.split("?", 1)[0].endswith(APP_ERRORS_PATH_SUFFIX)


def app_errors_url_for(url: str) -> str | None:
    """The session's appErrors collection, derived from any URL in it.

    Same derivation as `connection.py:462-465`, minus the bug: restpy indexes
    into the URL without checking that `/sessions/` is present, which raises
    (and is swallowed) whenever it is not.
    """
    marker = "/sessions/"
    session_at = url.find(marker)
    if session_at < 0:
        return None
    end = url.find("/", session_at + len(marker))
    if end < 0:
        return None
    return f"{url[:end]}/ixnetwork{APP_ERRORS_PATH_SUFFIX}"


def clip_body(body: object, limit_bytes: int) -> str | None:
    """Render a request or response body as text, capped at `limit_bytes`.

    A truncated value carries an explicit marker naming the original size so a
    reader never mistakes a clipped payload for the real one.
    """
    if body is None:
        return None
    raw = _as_bytes(body)
    if len(raw) <= limit_bytes:
        return raw.decode("utf-8", errors="replace")
    kept = raw[:limit_bytes].decode("utf-8", errors="replace")
    return f"{kept}...[truncated: kept {limit_bytes} of {len(raw)} bytes]"


def async_failure_message(payload: object) -> str | None:
    """The failure text of an IxNetwork async reply, or None if it is not one.

    IxNetwork reports an async operation's outcome in the body while the HTTP
    status stays 2xx, so this -- not `status` -- is what says whether a call
    such as `Traffic.Apply` worked. The message concatenates `message` and
    `result` the way `connection.py:449-452` does before raising.
    """
    status = _parse_async_status(payload)
    if status is None:
        return None
    state = status.get("state")
    if not isinstance(state, str) or state in _ASYNC_SUCCESS_STATES:
        return None
    parts = [
        str(status[key]).strip()
        for key in ("message", "result")
        if status.get(key) is not None and str(status[key]).strip()
    ]
    return " ".join(parts)[:_MAX_ERROR_LENGTH] or f"async operation state {state}"


def _parse_async_status(payload: object) -> dict[str, object] | None:
    if payload is None:
        return None
    raw = _as_bytes(payload)
    if len(raw) > _ASYNC_STATUS_MAX_BYTES or _STATE_KEY_MARKER not in raw:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        # Covers `json.JSONDecodeError` and the `UnicodeDecodeError` a
        # non-UTF-8 body raises; both subclass `ValueError`.
        return None
    return parsed if isinstance(parsed, dict) else None


def _as_bytes(body: object) -> bytes:
    if isinstance(body, (bytes, bytearray)):
        return bytes(body)
    return str(body).encode("utf-8", errors="replace")


def _response_payload(response: object) -> object:
    if response is None:
        return None
    content = getattr(response, "content", None)
    return content if content is not None else getattr(response, "text", None)


class IxiaTracer:
    """Appends one JSON object per IxNetwork REST call to a JSONL file.

    The trace is cut into phase slices -- `setup`, one per test case, then
    `teardown` -- so each slice can be uploaded and linked the moment the
    phase it covers ends, instead of a single run-level artifact that only
    exists once the run is over.

    Thread-safe by necessity, not by caution: `TaacIxia` samples chassis
    statistics from a background thread (2s by default) concurrently with
    main-thread operations, so the sequence counter, the file handle and the
    slice bookkeeping are all lock-guarded.

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
        app_errors_body_limit_bytes: int = DEFAULT_APP_ERRORS_BODY_LIMIT_BYTES,
        app_errors_cooldown_seconds: float = DEFAULT_APP_ERRORS_COOLDOWN_SECONDS,
        max_app_errors_fetches: int = DEFAULT_MAX_APP_ERRORS_FETCHES,
        initial_phase: str = SETUP_PHASE,
    ) -> None:
        self.path = path
        self._logger: logging.Logger = logger or logging.getLogger(__name__)
        self._request_body_capture = request_body_capture
        self._response_body_capture = response_body_capture
        self._request_body_limit_bytes = request_body_limit_bytes
        self._response_body_limit_bytes = response_body_limit_bytes
        self._app_errors_body_limit_bytes = app_errors_body_limit_bytes
        self._app_errors_cooldown_seconds = app_errors_cooldown_seconds
        self._max_app_errors_fetches = max_app_errors_fetches
        self._lock = threading.Lock()
        # Guards against the appErrors fetch re-entering `finish`/`fail` and
        # triggering a fetch of its own.
        self._reentrancy = threading.local()
        self._handle: t.IO[str] | None = None
        self._closed = False
        self._seq = 0
        self._write_failure_logged = False
        self._app_errors_fetch: AppErrorsFetch | None = None
        self._app_errors_fetch_times: dict[tuple[str | None, str | None], float] = {}
        self._app_errors_fetch_count = 0
        self._preamble: IxiaTraceSessionPreamble | None = None
        self._slices: list[IxiaTraceSlice] = []
        self._slice_index = 0
        self._slice_phase = initial_phase
        self._slice_path: Path = build_slice_path(path, 0, initial_phase)
        self._slice_records = 0
        self._slice_failures = 0
        self._slice_dropped = 0

    @property
    def slices(self) -> tuple[IxiaTraceSlice, ...]:
        """Every slice closed so far, oldest first."""
        with self._lock:
            return tuple(self._slices)

    @property
    def current_phase(self) -> str:
        with self._lock:
            return self._slice_phase

    def set_app_errors_fetch(self, fetch: AppErrorsFetch | None) -> None:
        """Install the callable used to pull `/globals/appErrors/error`.

        `Ixia` passes the raw, un-wrapped transport here so the fetch cannot
        re-enter the tracing wrapper it is issued from.
        """
        self._app_errors_fetch = fetch

    def set_session_preamble(self, preamble: IxiaTraceSessionPreamble) -> None:
        """Record the session context and reuse it to head every later slice."""
        try:
            line = _encode(preamble)
        except Exception as exc:
            self._log_first_failure(f"ixia api trace: preamble build failed: {exc!r}")
            return
        with self._lock:
            self._preamble = preamble
            self._write_line_locked(line, is_record=False, is_failure=False)

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
            span,
            response=None,
            error=f"{type(error).__name__}: {error!s}"[:_MAX_ERROR_LENGTH],
        )

    def rotate(self, phase: str) -> IxiaTraceSlice | None:
        """Close the current slice and start recording into `phase`."""
        with self._lock:
            if self._closed:
                return None
            completed = self._close_slice_locked()
            self._open_slice_locked(phase)
        return completed

    def close(self) -> IxiaTraceSlice | None:
        """Close the final slice; further calls are counted as dropped."""
        with self._lock:
            if self._closed:
                return None
            self._closed = True
            return self._close_slice_locked()

    def _record(
        self,
        span: IxiaTraceSpan,
        response: object,
        error: str | None,
        caused_by_seq: int | None = None,
    ) -> None:
        try:
            record = self._build_record(span, response, error, caused_by_seq)
            line = _encode(record)
        except Exception as exc:
            self._count_drop()
            self._log_first_failure(f"ixia api trace: record build failed: {exc!r}")
            return
        is_failure = record.outcome == TraceOutcome.FAILURE.value
        with self._lock:
            self._write_line_locked(line, is_record=True, is_failure=is_failure)
        if is_failure:
            self._fetch_app_errors_for(record)

    def _build_record(
        self,
        span: IxiaTraceSpan,
        response: object,
        error: str | None,
        caused_by_seq: int | None,
    ) -> IxiaTraceRecord:
        status = getattr(response, "status_code", None)
        status = int(status) if isinstance(status, int) else None
        payload = _response_payload(response)
        outcome, outcome_error = self._derive_outcome(status, payload, error)
        is_failure = outcome is TraceOutcome.FAILURE
        return IxiaTraceRecord(
            record_type=RECORD_TYPE_REST_CALL,
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
                is_failure,
                span.url,
            ),
            status=status,
            outcome=outcome.value,
            response_body=self._render_response_body(span.url, payload, is_failure),
            error=outcome_error,
            op=span.op,
            phase=span.phase,
            playbook=span.playbook,
            testconfig=span.testconfig,
            caused_by_seq=caused_by_seq,
        )

    def _derive_outcome(
        self,
        status: int | None,
        payload: object,
        transport_error: str | None,
    ) -> tuple[TraceOutcome, str | None]:
        if transport_error is not None:
            return (TraceOutcome.FAILURE, transport_error)
        async_error = async_failure_message(payload)
        if async_error is not None:
            return (TraceOutcome.FAILURE, async_error)
        if status is None or status not in _SUCCESS_STATUS_RANGE:
            return (TraceOutcome.FAILURE, None)
        return (TraceOutcome.SUCCESS, None)

    def _render_response_body(
        self,
        url: str,
        payload: object,
        is_failure: bool,
    ) -> str | None:
        if is_app_errors_url(url):
            # Free: the reply is already in memory, and it is the one payload
            # that names the server-side cause of everything around it.
            return clip_body(
                redact_credentials(payload, url), self._app_errors_body_limit_bytes
            )
        return self._render_body(
            payload,
            self._response_body_capture,
            self._response_body_limit_bytes,
            is_failure,
            url,
        )

    def _render_body(
        self,
        body: object,
        capture: BodyCapture,
        limit_bytes: int,
        is_failure: bool,
        url: str,
    ) -> str | None:
        if capture is BodyCapture.NEVER:
            return None
        if capture is BodyCapture.ON_ERROR and not is_failure:
            return None
        return clip_body(redact_credentials(body, url), limit_bytes)

    def _fetch_app_errors_for(self, record: IxiaTraceRecord) -> None:
        fetch = self._app_errors_fetch
        if fetch is None or getattr(self._reentrancy, "in_app_errors_fetch", False):
            return
        url = app_errors_url_for(record.url)
        if url is None or not self._claim_app_errors_fetch(record.op, record.error):
            return
        self._reentrancy.in_app_errors_fetch = True
        try:
            span = self.begin(
                method="GET",
                url=url,
                op=record.op,
                phase=record.phase,
                playbook=record.playbook,
                testconfig=record.testconfig,
            )
            try:
                response = fetch(url)
            except Exception as exc:
                self._record(
                    span,
                    response=None,
                    error=f"appErrors fetch failed: {type(exc).__name__}: {exc!s}"[
                        :_MAX_ERROR_LENGTH
                    ],
                    caused_by_seq=record.seq,
                )
                return
            self._record(span, response=response, error=None, caused_by_seq=record.seq)
        finally:
            self._reentrancy.in_app_errors_fetch = False

    def _claim_app_errors_fetch(self, op: str | None, error: str | None) -> bool:
        """Rate-limit to one fetch per distinct failure per cooldown."""
        with self._lock:
            if self._closed or self._app_errors_fetch_count >= (
                self._max_app_errors_fetches
            ):
                return False
            now = time.monotonic()
            key = (op, error)
            last = self._app_errors_fetch_times.get(key)
            if last is not None and now - last < self._app_errors_cooldown_seconds:
                return False
            self._app_errors_fetch_times[key] = now
            self._app_errors_fetch_count += 1
            return True

    def _open_slice_locked(self, phase: str) -> None:
        self._slice_index += 1
        self._slice_phase = phase
        self._slice_path = build_slice_path(self.path, self._slice_index, phase)
        self._slice_records = 0
        self._slice_failures = 0
        self._slice_dropped = 0
        preamble = self._preamble
        if preamble is not None:
            try:
                line = _encode(preamble)
            except Exception as exc:
                self._log_first_failure(
                    f"ixia api trace: preamble build failed: {exc!r}"
                )
                return
            self._write_line_locked(line, is_record=False, is_failure=False)

    def _close_slice_locked(self) -> IxiaTraceSlice:
        handle, self._handle = self._handle, None
        if handle is not None:
            try:
                handle.close()
            except OSError as exc:
                self._logger.warning(
                    f"ixia api trace: close failed on {self._slice_path}: {exc!r}"
                )
        completed = IxiaTraceSlice(
            index=self._slice_index,
            phase=self._slice_phase,
            path=self._slice_path,
            record_count=self._slice_records,
            failure_count=self._slice_failures,
            dropped_count=self._slice_dropped,
        )
        self._slices.append(completed)
        return completed

    def _write_line_locked(
        self, line: str, *, is_record: bool, is_failure: bool
    ) -> None:
        if self._closed:
            self._slice_dropped += 1
            self._log_first_failure("ixia api trace: write after close, record dropped")
            return
        try:
            handle = self._open_handle_locked()
            handle.write(f"{line}\n")
            # Flushed per line so a hard kill mid-run still leaves every
            # completed call on disk, which is the run the trace is for.
            handle.flush()
        except OSError as exc:
            self._slice_dropped += 1
            self._log_first_failure(
                f"ixia api trace: write failed on {self._slice_path}: {exc!r}"
            )
            return
        if is_record:
            self._slice_records += 1
            if is_failure:
                self._slice_failures += 1

    def _open_handle_locked(self) -> t.IO[str]:
        handle = self._handle
        if handle is None:
            handle = self._slice_path.open("a", encoding="utf-8")
            self._handle = handle
        return handle

    def _count_drop(self) -> None:
        with self._lock:
            self._slice_dropped += 1

    def _log_first_failure(self, message: str) -> None:
        if self._write_failure_logged:
            return
        self._write_failure_logged = True
        self._logger.warning(f"{message} (further tracer failures are silent)")


def _encode(record: object) -> str:
    return json.dumps(asdict(t.cast(t.Any, record)), separators=(",", ":"), default=str)
