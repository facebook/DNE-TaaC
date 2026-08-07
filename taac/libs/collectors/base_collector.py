#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Continuous-polling collector framework — OSS-safe base class + helpers.

Extracted from ``taac/libs/fpf/fpf_stress_checks.py`` so the domain-agnostic
pieces (poll loop, thread lifecycle, atexit cleanup, per-poll timeout, NULL-
data recording, timestamped-row storage) live in a module with no Meta-
internal imports. Meta's FPF-specific collectors (FSDB ribMap, HRT bulk, BGP
RIB) continue to live in ``fpf_stress_checks.py`` and re-import ``BaseCollector``
+ the two timestamp helpers from here.

Subclass ``BaseCollector`` and implement ``_poll_once()`` — one data-collection
cycle. The base class runs it in a background daemon thread with its own
asyncio event loop, so the collector survives across ``asyncio.run()``
boundaries (e.g. between setup tasks and playbook execution in the TAAC
framework).
"""

import asyncio
import atexit
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


def _now_str() -> str:
    """Timestamp string in ``BaseCollector`` row-log format.

    Human-readable + timezone-explicit. Matches ``_parse_ts``'s accepted formats.
    """
    now = datetime.now(timezone.utc).astimezone()
    return now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + now.strftime("%z")


def _parse_ts(ts_str: str) -> datetime:
    """Parse a timestamp string like ``'2026-05-19 22:36:32.560-0700'``.

    Accepts both fractional-second and integer-second forms; raises
    ``ValueError`` otherwise.
    """
    for fmt in ["%Y-%m-%d %H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S%z"]:
        try:
            return datetime.strptime(ts_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse timestamp: {ts_str}")


class BaseCollector:
    """Base for continuous-polling collectors.

    Subclasses implement ``_poll_once()`` to do one data collection cycle.
    The collector runs in a background daemon thread with its own event
    loop, so it survives across ``asyncio.run()`` boundaries (e.g. between
    setup tasks and playbook execution in the TAAC framework).
    """

    POLL_TIMEOUT_SEC: float = 120.0

    def __init__(self, tmp_path: str, interval_sec: float = 2.0) -> None:
        self.tmp_path = tmp_path
        self.json_path = tmp_path.replace(".log", ".jsonl")
        self.interval_sec = interval_sec
        self._task: Optional[asyncio.Task] = None
        self._stop_flag = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._thread_loop: Optional[asyncio.AbstractEventLoop] = None
        self.rows: List = []
        # Whole-cycle timeouts (outer _run_loop wait_for) — affect every host.
        self.timeout_timestamps: List[float] = []
        # Per-host timeouts (a single hung host in a concurrent multi-host cycle)
        # — attributed only to that host. host -> [epoch, ...].
        self.host_timeout_timestamps: Dict[str, List[float]] = {}
        self._file: Any = None
        self._json_file: Any = None
        self._append_mode: bool = False
        # atexit has no deregister-by-default; guard so a restart doesn't
        # stack duplicate shutdown hooks.
        self._atexit_registered: bool = False

    def set_append_mode(self, enabled: bool = True) -> None:
        self._append_mode = enabled

    def _write_header(self, f) -> None:
        pass

    def _write_json_row(self, row_dict: Dict) -> None:
        # JSON output disabled by request — human-readable .log files are the
        # only artifact. Kept as a guarded no-op so the per-collector call sites
        # need no changes; re-enable by opening self._json_file in _run_loop.
        if self._json_file is None:
            return
        self._json_file.write(json.dumps(row_dict) + "\n")
        self._json_file.flush()

    async def _poll_once(self) -> None:
        raise NotImplementedError

    async def _run_loop(self) -> None:
        mode = "a" if self._append_mode else "w"
        poll_timeout = self.POLL_TIMEOUT_SEC
        # JSON (.jsonl) output disabled by request — only the human-readable
        # .log file is written. self._json_file stays None so _write_json_row
        # is a no-op.
        with open(self.tmp_path, mode) as f:
            self._file = f
            if not self._append_mode or f.tell() == 0:
                f.write("=" * 100 + "\n")
                self._write_header(f)
                f.write("-" * 100 + "\n")
                f.flush()
            try:
                while not self._stop_flag.is_set():
                    try:
                        await asyncio.wait_for(self._poll_once(), timeout=poll_timeout)
                    except asyncio.TimeoutError:
                        self._record_null_poll(poll_timeout)
                    except asyncio.CancelledError:
                        break
                    except Exception as e:
                        logger.error(f"[{self.__class__.__name__}] poll error: {e}")
                    try:
                        await asyncio.sleep(self.interval_sec)
                    except asyncio.CancelledError:
                        break
            except asyncio.CancelledError:
                pass

    def _record_null_poll(self, poll_timeout: float) -> None:
        ts_str = _now_str()
        epoch = datetime.now(timezone.utc).timestamp()
        self.timeout_timestamps.append(epoch)
        logger.warning(
            f"[{self.__class__.__name__}] poll exceeded {poll_timeout:.0f}s — "
            f"recording NULL data point (input=null, output=null)"
        )
        if self._file is not None:
            try:
                self._file.write(
                    f"{ts_str}  *** NULL DATA — poll timeout "
                    f"({poll_timeout:.0f}s) ***\n"
                )
                self._file.flush()
            except Exception:
                pass
        if self._json_file is not None:
            try:
                self._write_json_row(
                    {
                        "collector": self.__class__.__name__,
                        "timestamp": ts_str,
                        "input": None,
                        "output": None,
                        "notes": f"error: poll timeout ({poll_timeout:.0f}s) — null data",
                    }
                )
            except Exception:
                pass

    def _record_host_timeout(self, host: str, poll_timeout: float) -> None:
        epoch = datetime.now(timezone.utc).timestamp()
        self.host_timeout_timestamps.setdefault(host, []).append(epoch)
        logger.warning(
            f"[{self.__class__.__name__}] {host} poll exceeded {poll_timeout:.0f}s — "
            f"recording per-host NULL data point"
        )
        if self._file is not None:
            try:
                self._file.write(
                    f"{_now_str()}  *** NULL DATA — {host} poll timeout "
                    f"({poll_timeout:.0f}s) ***\n"
                )
                self._file.flush()
            except Exception:
                pass

    def had_timeout_in_window(
        self, window_start: float, window_end: float, host: Optional[str] = None
    ) -> bool:
        return self.timeout_count_in_window(window_start, window_end, host) > 0

    def timeout_count_in_window(
        self, window_start: float, window_end: float, host: Optional[str] = None
    ) -> int:
        # Whole-cycle timeouts affect every host, so they count for any host.
        # When a host is given, add that host's own per-host timeouts on top.
        count = sum(
            1 for ts in self.timeout_timestamps if window_start <= ts <= window_end
        )
        if host is not None:
            count += sum(
                1
                for ts in self.host_timeout_timestamps.get(host, [])
                if window_start <= ts <= window_end
            )
        return count

    def _thread_target(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._thread_loop = loop
        try:
            loop.run_until_complete(self._run_loop())
        finally:
            loop.close()

    def start(self) -> None:
        self._stop_flag.clear()
        self._thread = threading.Thread(
            target=self._thread_target,
            daemon=True,
            name=f"{self.__class__.__name__}-collector",
        )
        self._thread.start()
        if not self._atexit_registered:
            atexit.register(self._atexit_stop)
            self._atexit_registered = True
        logger.info(f"[{self.__class__.__name__}] started, writing to {self.tmp_path}")

    def _cancel_thread_tasks(self) -> None:
        loop = self._thread_loop
        if loop is None or loop.is_closed():
            return

        def _cancel_all() -> None:
            for task in asyncio.all_tasks(loop):
                task.cancel()

        try:
            loop.call_soon_threadsafe(_cancel_all)
        except RuntimeError:
            pass

    def _atexit_stop(self) -> None:
        if self._stop_flag.is_set() and not (self._thread and self._thread.is_alive()):
            return
        self._stop_flag.set()
        self._cancel_thread_tasks()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    async def stop(self) -> None:
        self._stop_flag.set()
        self._cancel_thread_tasks()
        # Cache to a local so Pyre narrows the Optional[Thread] across
        # the join + post-join is_alive re-check.
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=10)
            if thread.is_alive():
                logger.error(
                    f"[{self.__class__.__name__}] FAILED to stop within 10s — "
                    f"thread still alive (likely blocked in a network call). "
                    f"Daemon thread will die when the parent process exits."
                )
                return
        logger.info(f"[{self.__class__.__name__}] stopped")

    def get_rows_in_window(self, window_start: float, window_end: float) -> List:
        windowed = []
        for row in self.rows:
            # Prefer the row's exact epoch; the formatted timestamp string is
            # only a fallback for row types that predate it. Silently dropping
            # a row on a parse failure would make a windowed query look empty
            # rather than broken.
            row_ts = getattr(row, "epoch", None)
            if row_ts is None:
                try:
                    row_ts = _parse_ts(row.timestamp).timestamp()
                except (ValueError, AttributeError):
                    logger.warning(
                        f"[{self.__class__.__name__}] dropping row with "
                        f"unparseable timestamp: {getattr(row, 'timestamp', row)!r}"
                    )
                    continue
            if window_start <= row_ts <= window_end:
                windowed.append(row)
        return windowed

    def format_window_table(
        self, window_start: float, window_end: float, max_rows: int = 4000
    ) -> str:
        """Human-readable table of this collector's polled rows within the test-
        case window — the same per-poll data written to the .log file, sliced to
        [window_start, window_end]. Used to attach a debuggable poll table to the
        collector-based health-check Everpaste detail. Generic over the row
        dataclass (header = field names, one line per poll); capped at max_rows.
        """
        import dataclasses

        rows = self.get_rows_in_window(window_start, window_end)
        if not rows:
            return "(no collector rows in test-case window)"
        try:
            field_names = [f.name for f in dataclasses.fields(rows[0])]
        except TypeError:
            return "\n".join(str(r) for r in rows[:max_rows])
        lines = ["  ".join(field_names)]
        for r in rows[:max_rows]:
            lines.append("  ".join(str(getattr(r, fn, "")) for fn in field_names))
        if len(rows) > max_rows:
            lines.append(f"... ({len(rows) - max_rows} more rows truncated)")
        return "\n".join(lines)
