#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""
FPF HRT Capture — JSONL writer/reader for the prefix-tracker capture file.

Phase 1 of the two-phase HRT prefix-tracker assertion framework. This module is
deliberately tiny and dependency-free: no thrift, no asyncio. It is consumed by
both the live capture path (``track_prefix()`` in ``fpf_hrt_client.py``) and the
offline evaluator (``fpf_hrt_assertions.py``).

File format (JSONL, one JSON object per line)::

    {"_kind":"meta_header","host":"rtptest1544.mwg2","prefix":"2401:db00:292a:a27c::/64",
     "device_id":0,"interval_sec":2.0,"run_start":"2026-04-30T10:00:00-07:00",
     "schema_version":1,"poll_index_zero_based":true}
    {"_kind":"row","timestamp":"2026-04-30T10:00:00-07:00","poll_index":0,
     "reachable_planes":[0,1,2,3],"failed_planes":[4,5,6,7]}
    ...
    {"_kind":"meta_trailer","run_end":"2026-04-30T10:05:00-07:00",
     "total_rows":150,"clean_exit":true}

Why JSONL (not one big JSON):
  - Append-only: each row is one ``f.write(json.dumps(row) + "\\n"); f.flush()``.
    Ctrl-C / OOM / SSH drop loses at most the in-flight poll.
  - Streaming-friendly: ``tail -f`` works during the live run, ``wc -l`` gives
    sample count instantly.
  - Header is line 1, trailer (best-effort) is the last line. If trailer is
    missing, evaluators infer ``run_end = max(row.timestamp)`` and report
    ``clean_exit=False``.

Single-device invariant: the capture file represents one device per file. The
header carries the ``device_id``; rows omit it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import IO, List, Optional


SCHEMA_VERSION: int = 1


def format_readable_ts(dt: datetime) -> str:
    """Format a datetime as a human-readable timestamp with offset.

    Drops microseconds, uses a space separator instead of ``T``. The result
    is still parseable by ``datetime.fromisoformat()`` on Python 3.11+, so
    scenario JSON files can use either this readable form or the canonical
    ``T``-separated ISO-8601 form interchangeably.

    Example: ``"2026-05-03 21:06:14-07:00"``.
    """
    return dt.replace(microsecond=0).isoformat(sep=" ")


@dataclass
class CaptureMetaHeader:
    """First line of a capture file. Identifies the run."""

    host: str
    prefix: str
    device_id: int
    interval_sec: float
    run_start: str  # ISO-8601 with offset
    schema_version: int = SCHEMA_VERSION
    poll_index_zero_based: bool = True


@dataclass
class CaptureRow:
    """Single poll sample. One row per poll iteration in single-device mode."""

    timestamp: str  # ISO-8601 with offset
    poll_index: int
    reachable_planes: List[int]
    failed_planes: List[int]


@dataclass
class CaptureMetaTrailer:
    """Best-effort trailer written on clean shutdown."""

    run_end: str  # ISO-8601 with offset
    total_rows: int
    clean_exit: bool = True


@dataclass
class LoadedCapture:
    """Result of ``load_capture()`` — header + rows + optional trailer."""

    header: CaptureMetaHeader
    rows: List[CaptureRow] = field(default_factory=list)
    trailer: Optional[CaptureMetaTrailer] = None
    # Inferred when trailer is missing (Ctrl-C / kill).
    run_end: str = ""
    clean_exit: bool = True


class CaptureWriter:
    """Line-buffered JSONL writer.

    Usage::

        writer = CaptureWriter(
            path="/tmp/hrt_capture_rtptest1544_dev0_run42.jsonl",
            header=CaptureMetaHeader(
                host="rtptest1544.mwg2",
                prefix="2401:db00:292a:a27c::/64",
                device_id=0,
                interval_sec=2.0,
                run_start="2026-04-30T10:00:00-07:00",
            ),
        )
        try:
            for poll_index, sample in enumerate(samples):
                writer.write_row(
                    timestamp=sample.iso_ts,
                    poll_index=poll_index,
                    reachable_planes=sample.reachable,
                    failed_planes=sample.failed,
                )
        finally:
            writer.close(run_end=last_ts, clean_exit=True)

    The header is written immediately on construction. Each ``write_row`` flushes
    the underlying file so that a SIGKILL / Ctrl-C loses at most one poll.
    """

    def __init__(self, path: str, header: CaptureMetaHeader) -> None:
        self.path: str = path
        self.header: CaptureMetaHeader = header
        self._fh: Optional[IO[str]] = open(path, "w")  # noqa: SIM115
        self._row_count: int = 0
        self._closed: bool = False
        self._write_header()

    def _write_header(self) -> None:
        rec = {
            "_kind": "meta_header",
            "host": self.header.host,
            "prefix": self.header.prefix,
            "device_id": self.header.device_id,
            "interval_sec": self.header.interval_sec,
            "run_start": self.header.run_start,
            "schema_version": self.header.schema_version,
            "poll_index_zero_based": self.header.poll_index_zero_based,
        }
        self._write_line(rec)

    def write_row(
        self,
        timestamp: str,
        poll_index: int,
        reachable_planes: List[int],
        failed_planes: List[int],
        drained_reachable_planes: Optional[List[int]] = None,
        drained_failed_planes: Optional[List[int]] = None,
    ) -> None:
        """Append one row; flushes immediately for durability.

        ``drained_reachable_planes`` and ``drained_failed_planes`` are optional
        and default to empty lists. Older capture readers ignore unknown keys,
        so this is backward-compatible.
        """
        if self._closed or self._fh is None:
            return
        rec = {
            "_kind": "row",
            "timestamp": timestamp,
            "poll_index": poll_index,
            "reachable_planes": list(reachable_planes),
            "failed_planes": list(failed_planes),
            "drained_reachable_planes": list(drained_reachable_planes or []),
            "drained_failed_planes": list(drained_failed_planes or []),
        }
        self._write_line(rec)
        self._row_count += 1

    def close(self, run_end: str, clean_exit: bool = True) -> None:
        """Write the trailer and close the file. Idempotent."""
        fh = self._fh
        if self._closed or fh is None:
            return
        rec = {
            "_kind": "meta_trailer",
            "run_end": run_end,
            "total_rows": self._row_count,
            "clean_exit": clean_exit,
        }
        try:
            self._write_line(rec)
        finally:
            try:
                fh.close()
            except Exception:
                pass
            self._fh = None
            self._closed = True

    def _write_line(self, rec: dict) -> None:
        fh = self._fh
        if fh is None:
            return
        fh.write(json.dumps(rec) + "\n")
        fh.flush()

    @property
    def row_count(self) -> int:
        return self._row_count


def load_capture(path: str) -> LoadedCapture:
    """Parse a JSONL capture file produced by :class:`CaptureWriter`.

    Returns a :class:`LoadedCapture` with header, rows, and optional trailer. If
    the trailer is missing (e.g. SIGKILL / Ctrl-C between rows), the loader
    infers ``run_end`` from the maximum row timestamp and sets
    ``clean_exit=False``.

    Raises:
        FileNotFoundError: capture file does not exist.
        ValueError: header is missing/malformed, or no rows could be parsed,
            or a row has an unrecognized ``_kind``.
    """
    header: Optional[CaptureMetaHeader] = None
    rows: List[CaptureRow] = []
    trailer: Optional[CaptureMetaTrailer] = None

    with open(path, "r") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"capture file {path!r} line {lineno}: invalid JSON ({e})"
                ) from e

            kind = obj.get("_kind")
            if kind == "meta_header":
                if header is not None:
                    raise ValueError(
                        f"capture file {path!r} line {lineno}: duplicate meta_header"
                    )
                header = _parse_header(obj, path, lineno)
            elif kind == "row":
                if header is None:
                    raise ValueError(
                        f"capture file {path!r} line {lineno}: row before meta_header"
                    )
                rows.append(_parse_row(obj, path, lineno))
            elif kind == "meta_trailer":
                trailer = _parse_trailer(obj, path, lineno)
            else:
                raise ValueError(
                    f"capture file {path!r} line {lineno}: unknown _kind={kind!r}"
                )

    if header is None:
        raise ValueError(f"capture file {path!r}: missing meta_header")
    if not rows:
        raise ValueError(f"capture file {path!r}: zero rows captured")

    if trailer is not None:
        run_end = trailer.run_end
        clean_exit = trailer.clean_exit
    else:
        # Infer from the last row, mark unclean.
        run_end = rows[-1].timestamp
        clean_exit = False

    return LoadedCapture(
        header=header,
        rows=rows,
        trailer=trailer,
        run_end=run_end,
        clean_exit=clean_exit,
    )


def _parse_header(obj: dict, path: str, lineno: int) -> CaptureMetaHeader:
    required = ("host", "prefix", "device_id", "interval_sec", "run_start")
    missing = [k for k in required if k not in obj]
    if missing:
        raise ValueError(
            f"capture file {path!r} line {lineno}: meta_header missing keys {missing}"
        )
    return CaptureMetaHeader(
        host=str(obj["host"]),
        prefix=str(obj["prefix"]),
        device_id=int(obj["device_id"]),
        interval_sec=float(obj["interval_sec"]),
        run_start=str(obj["run_start"]),
        schema_version=int(obj.get("schema_version", SCHEMA_VERSION)),
        poll_index_zero_based=bool(obj.get("poll_index_zero_based", True)),
    )


def _parse_row(obj: dict, path: str, lineno: int) -> CaptureRow:
    required = ("timestamp", "poll_index", "reachable_planes", "failed_planes")
    missing = [k for k in required if k not in obj]
    if missing:
        raise ValueError(
            f"capture file {path!r} line {lineno}: row missing keys {missing}"
        )
    reachable = obj["reachable_planes"]
    failed = obj["failed_planes"]
    if not isinstance(reachable, list) or not isinstance(failed, list):
        raise ValueError(
            f"capture file {path!r} line {lineno}: reachable/failed_planes "
            "must be lists"
        )
    return CaptureRow(
        timestamp=str(obj["timestamp"]),
        poll_index=int(obj["poll_index"]),
        reachable_planes=[int(p) for p in reachable],
        failed_planes=[int(p) for p in failed],
    )


def _parse_trailer(obj: dict, path: str, lineno: int) -> CaptureMetaTrailer:
    required = ("run_end", "total_rows")
    missing = [k for k in required if k not in obj]
    if missing:
        raise ValueError(
            f"capture file {path!r} line {lineno}: meta_trailer missing keys {missing}"
        )
    return CaptureMetaTrailer(
        run_end=str(obj["run_end"]),
        total_rows=int(obj["total_rows"]),
        clean_exit=bool(obj.get("clean_exit", True)),
    )
