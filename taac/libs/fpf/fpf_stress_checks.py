#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""
Continuous-polling health check collectors for FPF stress tests.

Three collector classes that run as background asyncio tasks, writing
timestamped rows to both an in-memory list (for post-processing) and
a tmp file (for human readability). After the trigger + wait period,
each collector's evaluate() method assesses pass/fail against thresholds.

Collectors:
  FsdbRibmapCollector  — polls FSDB ribMap prefix counts per GTSW
  HrtBulkCollector     — polls HRT getPrefixTable per-lane counts per host
  BgpRibCollector      — polls BGP RIB prefix counts per GTSW
"""

import asyncio
import atexit
import ipaddress
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from neteng.netcastle.logger import get_root_logger
from taac.internal.driver.fboss_switch_internal import (
    FbossSwitchInternal,
)
from neteng.test_infra.dne.taac.libs.fpf.fpf_bgp_rib import _count_matching, get_bgp_rib
from taac.libs.fpf.fpf_fsdb_ribmap import get_fsdb_rib_map
from taac.libs.fpf.fpf_hrt_bulk_tracker import (
    count_failed_per_lane,
    count_per_lane,
    NUM_LANES,
)
from taac.libs.fpf.fpf_hrt_polling import get_hrt_client
from taac.libs.fpf.fpf_prod_hrt_prefix import (
    build_plane_status_map,
    build_prefix_map,
    normalize_prefix,
    PrefixReachability,
)


logger = get_root_logger()


def _now_str() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S.%f")[
        :-3
    ] + datetime.now(timezone.utc).astimezone().strftime("%z")


def _parse_ts(ts_str: str) -> datetime:
    """Parse a timestamp string like '2026-05-19 22:36:32.560-0700'."""
    for fmt in ["%Y-%m-%d %H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S%z"]:
        try:
            return datetime.strptime(ts_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse timestamp: {ts_str}")


# ---------------------------------------------------------------------------
# Lane mapping: lane N → STSW stsw001.s00{N+1}, GTSW gtsw00{N+1}.l1002
# ---------------------------------------------------------------------------

STSW_TEMPLATE = "stsw001.s{plane:03d}.l202.mwg2"
GTSW_TEMPLATE = "gtsw{plane:03d}.l1002.c087.mwg2"


def lanes_to_stsws(lanes: List[int]) -> List[str]:
    return [STSW_TEMPLATE.format(plane=lane + 1) for lane in lanes]


def lanes_to_gtsws(lanes: List[int]) -> List[str]:
    return [GTSW_TEMPLATE.format(plane=lane + 1) for lane in lanes]


# ---------------------------------------------------------------------------
# Precheck: verify no test prefixes already exist
# ---------------------------------------------------------------------------


@dataclass
class PrecheckResult:
    device: str
    source: str
    matched: int
    total: int
    passed: bool
    error: str = ""


async def run_stress_precheck(
    trigger_devices: List[str],
    observer_gtsws: List[str],
    subnet_prefix: str,
) -> Tuple[bool, List[PrecheckResult]]:
    """Verify that no prefixes matching the test subnet already exist
    on the trigger (STSW) or observer (GTSW) devices. Returns (all_passed, results).

    Checks BGP RIB on trigger devices and FSDB ribMap on observer GTSWs.
    Any matched > 0 means stale test prefixes from a prior run — fail the precheck.
    Connection errors are treated as warnings (passed=True) since they indicate
    the service is down, not that stale prefixes exist.
    """
    subnet = ipaddress.IPv6Network(subnet_prefix, strict=False)

    async def _check_bgp_rib(device: str) -> PrecheckResult:
        try:
            rib_entries = await get_bgp_rib(device)
            total = len(rib_entries)
            matched = _count_matching(rib_entries, subnet, None)
            return PrecheckResult(
                device=device,
                source="BGP RIB",
                matched=matched,
                total=total,
                passed=matched == 0,
            )
        except Exception as e:
            return PrecheckResult(
                device=device,
                source="BGP RIB",
                matched=0,
                total=0,
                passed=True,
                error=str(e),
            )

    async def _check_fsdb_ribmap(gtsw: str) -> PrecheckResult:
        try:
            driver = FbossSwitchInternal(gtsw, logger)
            rib_map = await get_fsdb_rib_map(driver)
            total = len(rib_map) if isinstance(rib_map, dict) else 0
            matched = 0
            if isinstance(rib_map, dict):
                for prefix_str in rib_map:
                    try:
                        net = ipaddress.ip_network(prefix_str, strict=False)
                        if isinstance(net, ipaddress.IPv6Network) and net.subnet_of(
                            subnet
                        ):
                            matched += 1
                    except (ValueError, TypeError):
                        continue
            return PrecheckResult(
                device=gtsw,
                source="FSDB ribMap",
                matched=matched,
                total=total,
                passed=matched == 0,
            )
        except Exception as e:
            return PrecheckResult(
                device=gtsw,
                source="FSDB ribMap",
                matched=0,
                total=0,
                passed=True,
                error=str(e),
            )

    tasks = []
    for dev in trigger_devices:
        tasks.append(_check_bgp_rib(dev))
    for gtsw in observer_gtsws:
        tasks.append(_check_fsdb_ribmap(gtsw))
        tasks.append(_check_bgp_rib(gtsw))

    results = await asyncio.gather(*tasks)
    all_passed = all(r.passed for r in results)
    return all_passed, list(results)


# ---------------------------------------------------------------------------
# Data rows stored per collector
# ---------------------------------------------------------------------------


@dataclass
class RibmapRow:
    timestamp: str
    gtsw: str
    matched: int
    total: int
    notes: str = ""


@dataclass
class HrtBulkRow:
    timestamp: str
    host: str
    device_id: int
    lane_counts: List[int] = field(default_factory=lambda: [0] * NUM_LANES)
    unique: int = 0


@dataclass
class HrtRemoteFailureRow:
    timestamp: str
    host: str
    device_id: int
    lane_counts: List[int] = field(default_factory=lambda: [0] * NUM_LANES)
    unique: int = 0


@dataclass
class BgpRibRow:
    timestamp: str
    gtsw: str
    matched: int
    total: int
    notes: str = ""


@dataclass
class ProdHrtPrefixRow:
    """One poll of production-prefix reachability on a host (per-prefix snapshot)."""

    timestamp: str
    host: str
    # prefix -> PrefixReachability (reachable/drained/unreachable/up/down planes).
    prefixes: Dict[str, PrefixReachability] = field(default_factory=dict)


@dataclass
class ProdPrefixStabilityResult:
    """Per-prefix reachability-stability verdict over an evaluation window."""

    prefix: str
    host: str
    passed: bool
    baseline_reachable: List[int]
    samples: int
    detail: str = ""


@dataclass
class PerLaneResult:
    """Result of a per-lane/per-device evaluation.

    The base fields (lane, device, passed, expected, actual, convergence_sec,
    detail) capture the simple "did the threshold get reached" outcome.

    The ``signal*`` fields below capture the three-signal evaluation performed
    by ``evaluate_three_signals()`` in ``fpf_collector_registry``. Each signal
    is independent; the overall ``passed`` requires all three to pass.
    """

    lane: int
    device: str
    check_type: str
    passed: bool
    expected: int
    actual: int
    convergence_sec: Optional[float] = None
    detail: str = ""
    # Legacy fields (unused by current logic; kept for forward compat).
    sla_ok: Optional[bool] = None
    stability_ok: Optional[bool] = None
    stability_detail: str = ""
    # --- Three-signal evaluation outputs -----------------------------------
    # Signal 1: end-to-end convergence (window_start → first row at threshold)
    signal1_e2e_ok: Optional[bool] = None
    signal1_e2e_sec: Optional[float] = None
    signal1_e2e_threshold_sec: Optional[float] = None
    signal1_e2e_detail: str = ""
    # Signal 2: local propagation (T1 first-nonzero → T2 first-at-threshold)
    signal2_local_ok: Optional[bool] = None
    signal2_local_sec: Optional[float] = None
    signal2_local_threshold_sec: Optional[float] = None
    signal2_t1_sec_from_start: Optional[float] = None
    signal2_t2_sec_from_start: Optional[float] = None
    signal2_local_detail: str = ""
    # Signal 3: post-convergence stability (≥ threshold for stability_duration)
    signal3_stability_ok: Optional[bool] = None
    signal3_stability_duration_sec: Optional[float] = None
    signal3_stability_detail: str = ""


# ---------------------------------------------------------------------------
# Base collector
# ---------------------------------------------------------------------------


class BaseCollector:
    """Base for continuous-polling collectors.

    Subclasses implement _poll_once() to do one data collection cycle.
    The collector runs in a background daemon thread with its own event
    loop, so it survives across asyncio.run() boundaries (e.g. between
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
        self.timeout_timestamps: List[float] = []
        self._file: Any = None
        self._json_file: Any = None
        self._append_mode: bool = False

    def set_append_mode(self, enabled: bool = True) -> None:
        self._append_mode = enabled

    def _write_header(self, f) -> None:
        pass

    def _write_json_row(self, row_dict: Dict) -> None:
        self._json_file.write(json.dumps(row_dict) + "\n")
        self._json_file.flush()

    async def _poll_once(self) -> None:
        raise NotImplementedError

    async def _run_loop(self) -> None:
        mode = "a" if self._append_mode else "w"
        poll_timeout = self.POLL_TIMEOUT_SEC
        with open(self.tmp_path, mode) as f, open(self.json_path, mode) as jf:
            self._file = f
            self._json_file = jf
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
                    f"{ts_str:<34}  *** NULL DATA — poll timeout "
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

    def had_timeout_in_window(self, window_start: float, window_end: float) -> bool:
        return any(window_start <= ts <= window_end for ts in self.timeout_timestamps)

    def timeout_count_in_window(self, window_start: float, window_end: float) -> int:
        return sum(
            1 for ts in self.timeout_timestamps if window_start <= ts <= window_end
        )

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
        atexit.register(self._atexit_stop)
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
            try:
                row_ts = _parse_ts(row.timestamp).timestamp()
            except (ValueError, AttributeError):
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


# ---------------------------------------------------------------------------
# FSDB RibMap Collector
# ---------------------------------------------------------------------------


class FsdbRibmapCollector(BaseCollector):
    """Polls FSDB ribMap prefix counts matching a subnet filter per GTSW."""

    def __init__(
        self,
        gtsws: List[str],
        subnet_prefix: str,
        tmp_path: str = "/tmp/fpf_stress_fsdb_ribmap.log",
        interval_sec: float = 2.0,
        fsdb_mode: str = "ribmap",
    ) -> None:
        super().__init__(tmp_path, interval_sec)
        self.gtsws = gtsws
        self.subnet = ipaddress.IPv6Network(subnet_prefix, strict=False)
        self.fsdb_mode = fsdb_mode
        self.rows: List[RibmapRow] = []

    def _write_header(self, f) -> None:
        f.write(
            f"{'timestamp':<34}  {'gtsw':<34}  {'matched':>8}  {'total':>8}  notes\n"
        )

    async def _poll_once(self) -> None:
        async def _one_gtsw(gtsw: str) -> RibmapRow:
            notes = ""
            try:
                driver = FbossSwitchInternal(gtsw, logger)
                rib_map = await get_fsdb_rib_map(driver, mode=self.fsdb_mode)
                total = len(rib_map) if isinstance(rib_map, dict) else 0
                matched = 0
                if isinstance(rib_map, dict):
                    for prefix_str in rib_map:
                        try:
                            net = ipaddress.ip_network(prefix_str, strict=False)
                            if isinstance(net, ipaddress.IPv6Network) and net.subnet_of(
                                self.subnet
                            ):
                                matched += 1
                        except (ValueError, TypeError):
                            continue
            except Exception as e:
                notes = f"error: {e}"
                matched = 0
                total = 0
            return RibmapRow(
                timestamp=_now_str(),
                gtsw=gtsw,
                matched=matched,
                total=total,
                notes=notes,
            )

        results = await asyncio.gather(*[_one_gtsw(g) for g in self.gtsws])
        for row in results:
            self.rows.append(row)
            line = f"{row.timestamp:<34}  {row.gtsw:<34}  {row.matched:>8}  {row.total:>8}  {row.notes}\n"
            self._file.write(line)
            self._write_json_row(
                {
                    "collector": "fsdb_ribmap",
                    "timestamp": row.timestamp,
                    "gtsw": row.gtsw,
                    "matched": row.matched,
                    "total": row.total,
                    "notes": row.notes,
                }
            )
        self._file.flush()

    def evaluate_per_device(
        self,
        trigger_time: datetime,
        lane_map: Dict[int, str],
        deadline_sec: int = 300,
        expected_matched: int = 20000,
    ) -> List[PerLaneResult]:
        """Per-GTSW evaluation. lane_map maps lane_id -> gtsw hostname.
        Connection errors (all rows for a GTSW have notes containing 'error')
        are treated as FAIL since the service is unresponsive.
        """
        trigger_ts = trigger_time.timestamp()
        results = []
        for lane_id, gtsw in sorted(lane_map.items()):
            device_rows = [r for r in self.rows if r.gtsw == gtsw]
            if not device_rows:
                results.append(
                    PerLaneResult(
                        lane=lane_id,
                        device=gtsw,
                        check_type="FSDB ribMap",
                        passed=False,
                        expected=expected_matched,
                        actual=0,
                        detail="no data collected",
                    )
                )
                continue

            all_errors = all(r.notes.startswith("error:") for r in device_rows)
            if all_errors:
                results.append(
                    PerLaneResult(
                        lane=lane_id,
                        device=gtsw,
                        check_type="FSDB ribMap",
                        passed=False,
                        expected=expected_matched,
                        actual=0,
                        detail=f"FSDB unresponsive (all {len(device_rows)} polls failed)",
                    )
                )
                continue

            convergence_sec = None
            first_met_ts = None
            last_matched = 0
            for row in device_rows:
                try:
                    row_ts = _parse_ts(row.timestamp).timestamp()
                except ValueError:
                    continue
                if (
                    not row.notes
                    and row.matched >= expected_matched
                    and first_met_ts is None
                ):
                    first_met_ts = row_ts
                    convergence_sec = round(row_ts - trigger_ts, 1)
                last_matched = row.matched

            passed = first_met_ts is not None
            results.append(
                PerLaneResult(
                    lane=lane_id,
                    device=gtsw,
                    check_type="FSDB ribMap",
                    passed=passed,
                    expected=expected_matched,
                    actual=last_matched,
                    convergence_sec=convergence_sec,
                    detail=(
                        f"reached {last_matched} in {convergence_sec}s"
                        if passed
                        else f"only reached {last_matched}/{expected_matched}"
                    ),
                )
            )
        return results

    def evaluate_per_device_window(
        self,
        window_start: float,
        window_end: float,
        lane_map: Dict[int, str],
        expected_matched: int = 70000,
    ) -> List[PerLaneResult]:
        """Time-windowed variant of evaluate_per_device.

        Filters rows to [window_start, window_end] then evaluates convergence
        using window_start as the trigger reference. Used by long-lived
        collectors where each test case queries its own time window.
        """
        trigger_time = datetime.fromtimestamp(window_start, tz=timezone.utc)
        windowed = self.get_rows_in_window(window_start, window_end)
        saved_rows = self.rows
        try:
            self.rows = windowed
            return self.evaluate_per_device(
                trigger_time=trigger_time,
                lane_map=lane_map,
                expected_matched=expected_matched,
            )
        finally:
            self.rows = saved_rows


# ---------------------------------------------------------------------------
# HRT Bulk Prefix Collector
# ---------------------------------------------------------------------------


class HrtBulkCollector(BaseCollector):
    """Polls HRT getPrefixTable per-lane counts for a supernet filter."""

    def __init__(
        self,
        hosts: List[str],
        device_ids: Optional[List[int]] = None,
        supernet: str = "5000:dd::/32",
        tmp_path: str = "/tmp/fpf_stress_hrt_bulk.log",
        interval_sec: float = 2.0,
    ) -> None:
        super().__init__(tmp_path, interval_sec)
        self.hosts = hosts
        self.device_ids = device_ids or [0]
        self.supernet = ipaddress.IPv6Network(supernet, strict=False)
        self.rows: List[HrtBulkRow] = []

    def _write_header(self, f) -> None:
        lane_hdr = "  ".join(f"L{i}" for i in range(NUM_LANES))
        f.write(
            f"{'timestamp':<28}  {'host':<24}  {'dev':>3}  {lane_hdr}    [unique]\n"
        )

    async def _poll_once(self) -> None:
        for host in self.hosts:
            for dev_id in self.device_ids:
                try:
                    client_ctx = await get_hrt_client(host)
                    async with client_ctx as client:
                        prefix_table = await client.getPrefixTable()
                    counts, total_unique = count_per_lane(
                        prefix_table, dev_id, self.supernet
                    )
                except Exception as e:
                    logger.error(f"[HrtBulkCollector] {host} dev{dev_id}: {e}")
                    counts = [0] * NUM_LANES
                    total_unique = 0

                row = HrtBulkRow(
                    timestamp=_now_str(),
                    host=host,
                    device_id=dev_id,
                    lane_counts=counts,
                    unique=total_unique,
                )
                self.rows.append(row)
                lane_str = "  ".join(f"{c:>5}" for c in counts)
                line = (
                    f"{row.timestamp:<28}  {row.host:<24}  {row.device_id:>3}  "
                    f"{lane_str}    [unique={row.unique}]\n"
                )
                self._file.write(line)
                self._write_json_row(
                    {
                        "collector": "hrt_bulk",
                        "timestamp": row.timestamp,
                        "host": row.host,
                        "device_id": row.device_id,
                        "lane_counts": row.lane_counts,
                        "unique": row.unique,
                    }
                )
        self._file.flush()

    def evaluate_per_lane(
        self,
        trigger_time: datetime,
        lanes: List[int],
        deadline_sec: int = 300,
        expected_per_lane: Optional[Dict[int, int]] = None,
    ) -> List[PerLaneResult]:
        """Per-lane evaluation with convergence timing."""
        if expected_per_lane is None:
            expected_per_lane = {lane: int(20000) for lane in lanes}
        trigger_ts = trigger_time.timestamp()
        results = []
        for lane_id in sorted(lanes):
            expected = expected_per_lane.get(lane_id, 0)
            if expected == 0:
                results.append(
                    PerLaneResult(
                        lane=lane_id,
                        device=f"HRT L{lane_id}",
                        check_type="HRT bulk",
                        passed=True,
                        expected=0,
                        actual=0,
                        detail="no threshold set",
                    )
                )
                continue

            convergence_sec = None
            last_actual = 0
            for row in self.rows:
                if lane_id >= len(row.lane_counts):
                    continue
                try:
                    row_ts = _parse_ts(row.timestamp).timestamp()
                except ValueError:
                    continue
                count = row.lane_counts[lane_id]
                last_actual = count
                if count >= expected and convergence_sec is None:
                    convergence_sec = round(row_ts - trigger_ts, 1)

            passed = convergence_sec is not None
            results.append(
                PerLaneResult(
                    lane=lane_id,
                    device=f"HRT L{lane_id}",
                    check_type="HRT bulk",
                    passed=passed,
                    expected=expected,
                    actual=last_actual,
                    convergence_sec=convergence_sec,
                    detail=(
                        f"reached {expected} in {convergence_sec}s"
                        if passed
                        else f"only reached {last_actual}/{expected}"
                    ),
                )
            )
        return results

    def evaluate_per_lane_window(
        self,
        window_start: float,
        window_end: float,
        lanes: List[int],
        expected_per_lane: Optional[Dict[int, int]] = None,
        only_hosts: Optional[List[str]] = None,
    ) -> List[PerLaneResult]:
        """Time-windowed variant of evaluate_per_lane.

        ``only_hosts`` (when given) restricts evaluation to rows from those hosts
        — used by link-event checks that should assert only on the host whose
        lane was actually impacted, ignoring the unimpacted remote host(s).
        """
        trigger_time = datetime.fromtimestamp(window_start, tz=timezone.utc)
        windowed = self.get_rows_in_window(window_start, window_end)
        if only_hosts:
            allow = set(only_hosts)
            windowed = [r for r in windowed if getattr(r, "host", None) in allow]
        saved_rows = self.rows
        try:
            self.rows = windowed
            return self.evaluate_per_lane(
                trigger_time=trigger_time,
                lanes=lanes,
                expected_per_lane=expected_per_lane,
            )
        finally:
            self.rows = saved_rows


# ---------------------------------------------------------------------------
# BGP RIB Collector
# ---------------------------------------------------------------------------


class BgpRibCollector(BaseCollector):
    """Polls BGP RIB prefix counts matching a subnet filter per GTSW."""

    def __init__(
        self,
        gtsws: List[str],
        subnet_prefix: str,
        tmp_path: str = "/tmp/fpf_stress_bgp_rib.log",
        interval_sec: float = 2.0,
    ) -> None:
        super().__init__(tmp_path, interval_sec)
        self.gtsws = gtsws
        self.subnet = ipaddress.IPv6Network(subnet_prefix, strict=False)
        self.rows: List[BgpRibRow] = []

    def _write_header(self, f) -> None:
        f.write(
            f"{'timestamp':<34}  {'gtsw':<34}  {'matched':>8}  {'total':>8}  notes\n"
        )

    async def _poll_once(self) -> None:
        async def _one_gtsw(gtsw: str) -> BgpRibRow:
            notes = ""
            try:
                rib_entries = await get_bgp_rib(gtsw)
                total = len(rib_entries)
                matched = _count_matching(rib_entries, self.subnet, None)
            except Exception as e:
                notes = f"error: {e}"
                matched = 0
                total = 0
            return BgpRibRow(
                timestamp=_now_str(),
                gtsw=gtsw,
                matched=matched,
                total=total,
                notes=notes,
            )

        results = await asyncio.gather(*[_one_gtsw(g) for g in self.gtsws])
        for row in results:
            self.rows.append(row)
            line = f"{row.timestamp:<34}  {row.gtsw:<34}  {row.matched:>8}  {row.total:>8}  {row.notes}\n"
            self._file.write(line)
            self._write_json_row(
                {
                    "collector": "bgp_rib",
                    "timestamp": row.timestamp,
                    "gtsw": row.gtsw,
                    "matched": row.matched,
                    "total": row.total,
                    "notes": row.notes,
                }
            )
        self._file.flush()

    def evaluate_per_device(
        self,
        trigger_time: datetime,
        lane_map: Dict[int, str],
        deadline_sec: int = 300,
        expected_matched: int = 20000,
    ) -> List[PerLaneResult]:
        """Per-GTSW evaluation with convergence timing. Same pattern as
        FsdbRibmapCollector but queries BGP RIB (upstream of FSDB)."""
        trigger_ts = trigger_time.timestamp()
        results = []
        for lane_id, gtsw in sorted(lane_map.items()):
            device_rows = [r for r in self.rows if r.gtsw == gtsw]
            if not device_rows:
                results.append(
                    PerLaneResult(
                        lane=lane_id,
                        device=gtsw,
                        check_type="BGP RIB",
                        passed=False,
                        expected=expected_matched,
                        actual=0,
                        detail="no data collected",
                    )
                )
                continue

            all_errors = all(r.notes.startswith("error:") for r in device_rows)
            if all_errors:
                results.append(
                    PerLaneResult(
                        lane=lane_id,
                        device=gtsw,
                        check_type="BGP RIB",
                        passed=False,
                        expected=expected_matched,
                        actual=0,
                        detail=f"BGP unresponsive (all {len(device_rows)} polls failed)",
                    )
                )
                continue

            convergence_sec = None
            last_matched = 0
            for row in device_rows:
                try:
                    row_ts = _parse_ts(row.timestamp).timestamp()
                except ValueError:
                    continue
                if (
                    not row.notes
                    and row.matched >= expected_matched
                    and convergence_sec is None
                ):
                    convergence_sec = round(row_ts - trigger_ts, 1)
                last_matched = row.matched

            passed = convergence_sec is not None
            results.append(
                PerLaneResult(
                    lane=lane_id,
                    device=gtsw,
                    check_type="BGP RIB",
                    passed=passed,
                    expected=expected_matched,
                    actual=last_matched,
                    convergence_sec=convergence_sec,
                    detail=(
                        f"reached {last_matched} in {convergence_sec}s"
                        if passed
                        else f"only reached {last_matched}/{expected_matched}"
                    ),
                )
            )
        return results

    def evaluate_per_device_window(
        self,
        window_start: float,
        window_end: float,
        lane_map: Dict[int, str],
        expected_matched: int = 70000,
    ) -> List[PerLaneResult]:
        """Time-windowed variant of evaluate_per_device."""
        trigger_time = datetime.fromtimestamp(window_start, tz=timezone.utc)
        windowed = self.get_rows_in_window(window_start, window_end)
        saved_rows = self.rows
        try:
            self.rows = windowed
            return self.evaluate_per_device(
                trigger_time=trigger_time,
                lane_map=lane_map,
                expected_matched=expected_matched,
            )
        finally:
            self.rows = saved_rows


# ---------------------------------------------------------------------------
# HRT Remote Failure Collector
# ---------------------------------------------------------------------------


class HrtRemoteFailureCollector(BaseCollector):
    """Polls HRT getRemoteFailures() per-lane counts for a supernet filter.

    Measures negative-route (remote-failure) prefix counts per lane.
    In stable state all lanes read 0. After a drain, the drained lane's
    count rises to the injected prefix count.
    """

    def __init__(
        self,
        hosts: List[str],
        device_ids: Optional[List[int]] = None,
        supernet: str = "5000:dd::/32",
        tmp_path: str = "/tmp/fpf_stress_hrt_remote_failure.log",
        interval_sec: float = 2.0,
    ) -> None:
        super().__init__(tmp_path, interval_sec)
        self.hosts = hosts
        self.device_ids = device_ids or [0]
        self.supernet = ipaddress.IPv6Network(supernet, strict=False)
        self.rows: List[HrtRemoteFailureRow] = []

    def _write_header(self, f) -> None:
        lane_hdr = "  ".join(f"L{i}" for i in range(NUM_LANES))
        f.write(
            f"{'timestamp':<28}  {'host':<24}  {'dev':>3}  {lane_hdr}    [unique]\n"
        )

    async def _poll_once(self) -> None:
        for host in self.hosts:
            for dev_id in self.device_ids:
                try:
                    client_ctx = await get_hrt_client(host)
                    async with client_ctx as client:
                        remote_failures = await client.getRemoteFailures()
                    counts, total_unique = count_failed_per_lane(
                        remote_failures, dev_id, self.supernet
                    )
                except Exception as e:
                    logger.error(f"[HrtRemoteFailureCollector] {host} dev{dev_id}: {e}")
                    counts = [0] * NUM_LANES
                    total_unique = 0

                row = HrtRemoteFailureRow(
                    timestamp=_now_str(),
                    host=host,
                    device_id=dev_id,
                    lane_counts=counts,
                    unique=total_unique,
                )
                self.rows.append(row)
                lane_str = "  ".join(f"{c:>5}" for c in counts)
                line = (
                    f"{row.timestamp:<28}  {row.host:<24}  {row.device_id:>3}  "
                    f"{lane_str}    [unique={row.unique}]\n"
                )
                self._file.write(line)
                self._write_json_row(
                    {
                        "collector": "hrt_remote_failure",
                        "timestamp": row.timestamp,
                        "host": row.host,
                        "device_id": row.device_id,
                        "lane_counts": row.lane_counts,
                        "unique": row.unique,
                    }
                )
        self._file.flush()

    def evaluate_per_lane_drain(
        self,
        trigger_time: datetime,
        lanes: List[int],
        expected_per_lane: Optional[Dict[int, int]] = None,
        max_convergence_sec: int = 120,
    ) -> List[PerLaneResult]:
        """Drain direction: find 0->N transition per lane."""
        if expected_per_lane is None:
            expected_per_lane = {}
        results = []
        for lane_id in sorted(lanes):
            expected = expected_per_lane.get(lane_id, 0)
            if expected == 0:
                results.append(
                    PerLaneResult(
                        lane=lane_id,
                        device=f"HRT neg L{lane_id}",
                        check_type="HRT remote_failure drain",
                        passed=True,
                        expected=0,
                        actual=0,
                        detail="no threshold set",
                    )
                )
                continue

            t_last_zero: Optional[float] = None
            t_converge: Optional[float] = None
            last_actual = 0
            for row in self.rows:
                if lane_id >= len(row.lane_counts):
                    continue
                try:
                    row_ts = _parse_ts(row.timestamp).timestamp()
                except ValueError:
                    continue
                count = row.lane_counts[lane_id]
                last_actual = count
                # Only update t_last_zero before convergence — otherwise a later
                # recovery (count back to 0) would push t_last_zero past
                # t_converge and yield a negative convergence_sec.
                if count == 0 and t_converge is None:
                    t_last_zero = row_ts
                if count >= expected and t_converge is None and t_last_zero is not None:
                    t_converge = row_ts

            if t_converge is not None and t_last_zero is not None:
                convergence_sec = round(t_converge - t_last_zero, 1)
                passed = convergence_sec <= max_convergence_sec
                results.append(
                    PerLaneResult(
                        lane=lane_id,
                        device=f"HRT neg L{lane_id}",
                        check_type="HRT remote_failure drain",
                        passed=passed,
                        expected=expected,
                        actual=last_actual,
                        convergence_sec=convergence_sec,
                        detail=(
                            f"0->{expected} in {convergence_sec}s "
                            f"(SLA {max_convergence_sec}s)"
                        ),
                    )
                )
            else:
                results.append(
                    PerLaneResult(
                        lane=lane_id,
                        device=f"HRT neg L{lane_id}",
                        check_type="HRT remote_failure drain",
                        passed=False,
                        expected=expected,
                        actual=last_actual,
                        detail=f"never reached {expected} (last={last_actual})",
                    )
                )
        return results

    def evaluate_per_lane_recovery(
        self,
        trigger_time: datetime,
        lanes: List[int],
        expected_per_lane: Optional[Dict[int, int]] = None,
        max_convergence_sec: int = 120,
    ) -> List[PerLaneResult]:
        """Recovery direction: find N->0 transition per lane."""
        if expected_per_lane is None:
            expected_per_lane = {}
        results = []
        for lane_id in sorted(lanes):
            peak_expected = expected_per_lane.get(lane_id, 0)
            if peak_expected == 0:
                results.append(
                    PerLaneResult(
                        lane=lane_id,
                        device=f"HRT neg L{lane_id}",
                        check_type="HRT remote_failure recovery",
                        passed=True,
                        expected=0,
                        actual=0,
                        detail="no threshold set",
                    )
                )
                continue

            t_peak: Optional[float] = None
            t_recovered: Optional[float] = None
            last_actual = 0
            for row in self.rows:
                if lane_id >= len(row.lane_counts):
                    continue
                try:
                    row_ts = _parse_ts(row.timestamp).timestamp()
                except ValueError:
                    continue
                count = row.lane_counts[lane_id]
                last_actual = count
                if count >= peak_expected:
                    t_peak = row_ts
                    t_recovered = None
                if count == 0 and t_peak is not None and t_recovered is None:
                    t_recovered = row_ts

            if t_recovered is not None and t_peak is not None:
                convergence_sec = round(t_recovered - t_peak, 1)
                passed = convergence_sec <= max_convergence_sec
                results.append(
                    PerLaneResult(
                        lane=lane_id,
                        device=f"HRT neg L{lane_id}",
                        check_type="HRT remote_failure recovery",
                        passed=passed,
                        expected=0,
                        actual=last_actual,
                        convergence_sec=convergence_sec,
                        detail=(
                            f"{peak_expected}->0 in {convergence_sec}s "
                            f"(SLA {max_convergence_sec}s)"
                        ),
                    )
                )
            else:
                results.append(
                    PerLaneResult(
                        lane=lane_id,
                        device=f"HRT neg L{lane_id}",
                        check_type="HRT remote_failure recovery",
                        passed=False,
                        expected=0,
                        actual=last_actual,
                        detail=f"never recovered to 0 (last={last_actual})",
                    )
                )
        return results

    def evaluate_per_lane_stable(
        self,
        lanes: List[int],
    ) -> List[PerLaneResult]:
        """Stable-state: assert count stays 0 for every row in the window."""
        results = []
        for lane_id in sorted(lanes):
            max_seen = 0
            nonzero_count = 0
            total_rows = 0
            last_count = 0
            for row in self.rows:
                if lane_id >= len(row.lane_counts):
                    continue
                total_rows += 1
                count = row.lane_counts[lane_id]
                if count > max_seen:
                    max_seen = count
                if count != 0:
                    nonzero_count += 1
                last_count = count

            # Strict: every in-window sample must be 0. The window MUST start at
            # the recorded disruption time (callers scope via
            # ``evaluate_per_lane_window(window_start=disruption_time, ...)``) so
            # the pre-disruption injection ramp is excluded — the negative-route
            # count legitimately blips during prefix injection (e.g. L0=100 for a
            # single ~3s sample) ~minutes BEFORE the drain, and that artifact must
            # not be counted against drain stability. Within the post-disruption
            # window a device/link drain produces NO negative-route blip on the
            # impacted lane, so any nonzero is a real regression.
            passed = nonzero_count == 0
            if passed:
                detail = f"stable at 0 across {total_rows} samples"
            else:
                detail = (
                    f"saw nonzero in {nonzero_count}/{total_rows} "
                    f"samples (max={max_seen}, last={last_count})"
                )
            results.append(
                PerLaneResult(
                    lane=lane_id,
                    device=f"HRT neg L{lane_id}",
                    check_type="HRT remote_failure stable",
                    passed=passed,
                    expected=0,
                    actual=max_seen,
                    convergence_sec=None,
                    detail=detail,
                )
            )
        return results

    def evaluate_per_lane_window(
        self,
        window_start: float,
        window_end: float,
        lanes: List[int],
        expected_per_lane: Optional[Dict[int, int]] = None,
        direction: str = "drain",
        max_convergence_sec: int = 120,
        only_hosts: Optional[List[str]] = None,
    ) -> List[PerLaneResult]:
        """Time-windowed variant for use by health checks.

        ``only_hosts`` (when given) restricts evaluation to rows from those hosts
        — link-event checks assert only on the impacted host's lane, ignoring the
        unimpacted remote host(s).
        """
        trigger_time = datetime.fromtimestamp(window_start, tz=timezone.utc)
        windowed = self.get_rows_in_window(window_start, window_end)
        if only_hosts:
            allow = set(only_hosts)
            windowed = [r for r in windowed if getattr(r, "host", None) in allow]
        saved_rows = self.rows
        try:
            self.rows = windowed
            if direction == "stable":
                return self.evaluate_per_lane_stable(lanes=lanes)
            if direction == "recovery":
                return self.evaluate_per_lane_recovery(
                    trigger_time=trigger_time,
                    lanes=lanes,
                    expected_per_lane=expected_per_lane,
                    max_convergence_sec=max_convergence_sec,
                )
            return self.evaluate_per_lane_drain(
                trigger_time=trigger_time,
                lanes=lanes,
                expected_per_lane=expected_per_lane,
                max_convergence_sec=max_convergence_sec,
            )
        finally:
            self.rows = saved_rows


# ---------------------------------------------------------------------------
# Production HRT Prefix Collector (per-prefix reachability stability)
# ---------------------------------------------------------------------------


class ProdHrtPrefixCollector(BaseCollector):
    """Polls per-prefix reachability for a set of production prefixes on a GPU host.

    Each poll queries HRT getPrefixTable / getRemoteFailures / getPlaneStatus
    and records, per monitored prefix, the reachable / drained / unreachable
    planes plus plane_up / plane_down (see ``fpf_prod_hrt_prefix``). Unlike the
    convergence collectors (which track a count reaching a threshold), this
    collector supports a *reachability-stability* postcheck: over the
    evaluation window each prefix must retain its baseline reachable planes
    with no plane regressing to down/unreachable/drained.

    A single GPU ``device_id`` is required — the collector never assumes all
    GPUs (matching the standalone binary's contract).
    """

    def __init__(
        self,
        host: str,
        device_id: int,
        prefixes: List[str],
        tmp_path: str = "/tmp/fpf_prod_hrt_prefix.log",
        interval_sec: float = 3.0,
    ) -> None:
        super().__init__(tmp_path, interval_sec)
        self.host = host
        self.device_id = device_id
        self.target_prefixes = (
            {normalize_prefix(p) for p in prefixes} if prefixes else None
        )
        self.rows: List[ProdHrtPrefixRow] = []

    def _write_header(self, f) -> None:
        f.write(
            f"{'timestamp':<30}  {'host':<22}  {'prefix':<40}  "
            f"{'reachable':<16}  {'drained':<12}  {'unreachable':<14}  "
            f"{'plane_up':<16}  plane_down\n"
        )

    async def _poll_once(self) -> None:
        try:
            client_ctx = await get_hrt_client(self.host)
            async with client_ctx as client:
                prefixes = await client.getPrefixTable()
                neg_routes = await client.getRemoteFailures()
                plane_status_entries = await client.getPlaneStatus()
            prefix_map = build_prefix_map(
                prefixes,
                neg_routes,
                plane_status_entries,
                self.target_prefixes,
                {self.device_id},
            )
        except Exception as e:
            logger.error(
                f"[ProdHrtPrefixCollector] {self.host} dev{self.device_id}: {e}"
            )
            prefix_map = {}

        ts = _now_str()
        self.rows.append(
            ProdHrtPrefixRow(timestamp=ts, host=self.host, prefixes=prefix_map)
        )

        def _fmt(planes: List[int]) -> str:
            return ",".join(str(p) for p in planes) if planes else "-"

        for pfx in sorted(prefix_map):
            rb = prefix_map[pfx]
            self._file.write(
                f"{ts:<30}  {self.host:<22}  {pfx:<40}  "
                f"{_fmt(rb.reachable_planes):<16}  {_fmt(rb.drained_planes):<12}  "
                f"{_fmt(rb.unreachable_planes):<14}  {_fmt(rb.plane_up):<16}  "
                f"{_fmt(rb.plane_down)}\n"
            )
            self._write_json_row(
                {
                    "collector": "prod_hrt_prefix",
                    "timestamp": ts,
                    "host": self.host,
                    "device_id": self.device_id,
                    "prefix": pfx,
                    "reachable_planes": rb.reachable_planes,
                    "drained_planes": rb.drained_planes,
                    "unreachable_planes": rb.unreachable_planes,
                    "plane_up": rb.plane_up,
                    "plane_down": rb.plane_down,
                    "device_ids": rb.device_ids,
                }
            )
        self._file.flush()

    def evaluate_prefix_stability_window(
        self,
        window_start: float,
        window_end: float,
    ) -> List[ProdPrefixStabilityResult]:
        """Reachability-stability verdict per prefix over [window_start, window_end].

        For each monitored prefix the baseline is the reachable plane set from
        the first in-window sample. The prefix PASSES iff every later sample's
        reachable set is a superset of that baseline (no plane regressed to
        down / unreachable / drained). The first regressing sample is reported.
        """
        windowed = [
            row
            for row in self.rows
            if self._row_in_window(row, window_start, window_end)
        ]
        # Collect the set of prefixes seen across the window.
        all_prefixes: set[str] = set()
        for row in windowed:
            all_prefixes.update(row.prefixes.keys())

        results: List[ProdPrefixStabilityResult] = []
        for pfx in sorted(all_prefixes):
            samples = [
                (self._row_ts(row), row.prefixes[pfx])
                for row in windowed
                if pfx in row.prefixes
            ]
            samples = [(ts, rb) for ts, rb in samples if ts is not None]
            samples.sort(key=lambda x: x[0])
            if not samples:
                continue
            baseline = set(samples[0][1].reachable_planes)
            regression = None
            for ts, rb in samples:
                missing = baseline - set(rb.reachable_planes)
                if missing:
                    regression = (ts, sorted(missing), rb)
                    break
            if regression is None:
                results.append(
                    ProdPrefixStabilityResult(
                        prefix=pfx,
                        host=self.host,
                        passed=True,
                        baseline_reachable=sorted(baseline),
                        samples=len(samples),
                        detail=(
                            f"stable: reachable held at {sorted(baseline)} "
                            f"across {len(samples)} samples"
                        ),
                    )
                )
            else:
                reg_ts, missing_planes, rb = regression
                from datetime import datetime as _dt

                when = _dt.fromtimestamp(reg_ts).strftime("%H:%M:%S")
                results.append(
                    ProdPrefixStabilityResult(
                        prefix=pfx,
                        host=self.host,
                        passed=False,
                        baseline_reachable=sorted(baseline),
                        samples=len(samples),
                        detail=(
                            f"FAIL — plane(s) {missing_planes} left reachable at "
                            f"{when} (now reachable={rb.reachable_planes}, "
                            f"drained={rb.drained_planes}, "
                            f"unreachable={rb.unreachable_planes})"
                        ),
                    )
                )
        return results

    def _row_in_window(self, row, window_start: float, window_end: float) -> bool:
        ts = self._row_ts(row)
        return ts is not None and window_start <= ts <= window_end

    @staticmethod
    def _row_ts(row) -> Optional[float]:
        try:
            return _parse_ts(row.timestamp).timestamp()
        except (ValueError, AttributeError):
            return None


# ---------------------------------------------------------------------------
# HRT Plane-Status Collector (per-device plane Up/Drained state)
# ---------------------------------------------------------------------------

# Canonical plane (lane) count per GPU device — beth0..beth7.
NUM_PLANES: int = NUM_LANES


@dataclass
class HrtPlaneStatusRow:
    """One poll of ``hrtctl show plane-status --device N`` for a single device.

    ``plane_states`` maps plane_id -> PlaneState name (e.g. ``"UP"``,
    ``"DRAINED"``, ``"DOWN"``, ``"UNKNOWN"``). Empty when the poll returned no
    entries for the device (treated as missing/null data downstream).
    """

    timestamp: str
    host: str
    device_id: int
    plane_states: Dict[int, str] = field(default_factory=dict)


@dataclass
class PlaneStatusResult:
    """Per-plane verdict over an evaluation window."""

    plane: int
    passed: bool
    expected_state: str
    observed_state: str
    samples: int
    detail: str = ""


class HrtPlaneStatusCollector(BaseCollector):
    """Polls HRT ``getPlaneStatus()`` for one GPU device, per-plane State.

    Programmatic equivalent of ``hrtctl show plane-status --device N``: each poll
    captures the State of every plane (beth0..beth7) on the device. Two postcheck
    contracts are supported via the evaluate_* helpers:

      - all_up: every plane is UP across the whole window (non-drained
        scenarios — baseline, interface enable, link/device undrain).
      - drain : the impacted plane(s) reach DRAINED and remain so by window end,
        while every other plane stays UP (link OR device drain — from the GPU's
        plane-status view a device drain of the GTSW serving a plane looks the
        same as a link drain of that plane).
    """

    def __init__(
        self,
        host: str,
        device_id: int,
        tmp_path: str = "/tmp/fpf_stress_hrt_plane_status.log",
        interval_sec: float = 3.0,
        num_planes: int = NUM_PLANES,
    ) -> None:
        super().__init__(tmp_path, interval_sec)
        self.host = host
        self.device_id = device_id
        self.num_planes = num_planes
        self.rows: List[HrtPlaneStatusRow] = []

    def _write_header(self, f) -> None:
        f.write(
            f"{'timestamp':<30}  {'host':<22}  {'device':<7}  "
            f"plane_states (plane=STATE ...)\n"
        )

    async def _poll_once(self) -> None:
        states: Dict[int, str] = {}
        try:
            client_ctx = await get_hrt_client(self.host)
            async with client_ctx as client:
                plane_status_entries = await client.getPlaneStatus()
            by_dev = build_plane_status_map(plane_status_entries, {self.device_id})
            states = {int(p): str(s) for p, s in by_dev.get(self.device_id, {}).items()}
        except Exception as e:
            logger.error(
                f"[HrtPlaneStatusCollector] {self.host} dev{self.device_id}: {e}"
            )
            states = {}

        ts = _now_str()
        self.rows.append(
            HrtPlaneStatusRow(
                timestamp=ts,
                host=self.host,
                device_id=self.device_id,
                plane_states=states,
            )
        )
        rendered = " ".join(f"{p}={states[p]}" for p in sorted(states)) or "-"
        if self._file is not None:
            self._file.write(
                f"{ts:<30}  {self.host:<22}  {self.device_id:<7}  {rendered}\n"
            )
            self._file.flush()
        self._write_json_row(
            {
                "collector": "hrt_plane_status",
                "timestamp": ts,
                "host": self.host,
                "device_id": self.device_id,
                "plane_states": {str(p): s for p, s in states.items()},
            }
        )

    def _planes(self, expected_planes: Optional[List[int]]) -> List[int]:
        if expected_planes is not None:
            return sorted(expected_planes)
        return list(range(self.num_planes))

    def evaluate_all_up_window(
        self,
        window_start: float,
        window_end: float,
        expected_planes: Optional[List[int]] = None,
    ) -> List[PlaneStatusResult]:
        """Every plane must be UP in every in-window sample."""
        windowed = self.get_rows_in_window(window_start, window_end)
        results: List[PlaneStatusResult] = []
        for plane in self._planes(expected_planes):
            samples = 0
            bad_state: Optional[str] = None
            bad_ts: Optional[str] = None
            last_state = "MISSING"
            for r in windowed:
                samples += 1
                st = r.plane_states.get(plane)
                last_state = st if st is not None else "MISSING"
                if st != "UP" and bad_state is None:
                    bad_state = last_state
                    bad_ts = r.timestamp
            passed = bad_state is None and samples > 0
            if samples == 0:
                detail = "no in-window samples"
            elif passed:
                detail = f"UP across {samples} samples"
            else:
                detail = f"not UP — saw {bad_state} at {bad_ts} (last={last_state})"
            results.append(
                PlaneStatusResult(
                    plane=plane,
                    passed=passed,
                    expected_state="UP",
                    observed_state=last_state,
                    samples=samples,
                    detail=detail,
                )
            )
        return results

    def evaluate_drain_window(
        self,
        window_start: float,
        window_end: float,
        impacted_planes: List[int],
        expected_planes: Optional[List[int]] = None,
    ) -> List[PlaneStatusResult]:
        """Impacted plane(s) DRAINED by window end; all other planes stay UP.

        The window MUST start at the recorded disruption time so the impacted
        plane's pre-drain UP samples are excluded (a drain takes a few seconds to
        reflect). An impacted plane PASSES iff its last in-window sample is
        DRAINED; a non-impacted plane PASSES iff it is UP in every sample.
        """
        impacted = {int(p) for p in impacted_planes}
        windowed = self.get_rows_in_window(window_start, window_end)
        results: List[PlaneStatusResult] = []
        for plane in self._planes(expected_planes):
            states = [(r.timestamp, r.plane_states.get(plane)) for r in windowed]
            samples = len(states)
            last_state = states[-1][1] if states else None
            last_disp = last_state if last_state is not None else "MISSING"
            if plane in impacted:
                reached = any(st == "DRAINED" for _ts, st in states)
                passed = samples > 0 and last_state == "DRAINED"
                if samples == 0:
                    detail = "no in-window samples"
                elif passed:
                    detail = f"DRAINED by window end across {samples} samples"
                elif reached:
                    detail = f"reached DRAINED but left it (last={last_disp})"
                else:
                    detail = (
                        f"never DRAINED (last={last_disp}) — drain not reflected "
                        f"on impacted plane"
                    )
                results.append(
                    PlaneStatusResult(
                        plane=plane,
                        passed=passed,
                        expected_state="DRAINED",
                        observed_state=last_disp,
                        samples=samples,
                        detail=detail,
                    )
                )
            else:
                bad_state: Optional[str] = None
                bad_ts: Optional[str] = None
                for ts, st in states:
                    if st != "UP" and bad_state is None:
                        bad_state = st if st is not None else "MISSING"
                        bad_ts = ts
                passed = bad_state is None and samples > 0
                if samples == 0:
                    detail = "no in-window samples"
                elif passed:
                    detail = f"UP across {samples} samples"
                else:
                    detail = f"unexpectedly not UP — {bad_state} at {bad_ts}"
                results.append(
                    PlaneStatusResult(
                        plane=plane,
                        passed=passed,
                        expected_state="UP",
                        observed_state=last_disp,
                        samples=samples,
                        detail=detail,
                    )
                )
        return results


# ---------------------------------------------------------------------------
# HRT FSDB-Session-Count Collector (per-host CONNECTED session census)
# ---------------------------------------------------------------------------


def _session_is_connected(session: Any) -> bool:
    return str(getattr(session, "state", None)) == "CONNECTED"


@dataclass
class HrtFsdbSessionRow:
    """One poll of ``getFsdbSessions()`` on a single GPU host.

    Each HRT FSDB session is keyed by (device_id = GPU, plane_id = lane). A
    session is CONNECTED or not. ``connected`` is the total CONNECTED count
    across all (gpu, lane); ``expected`` is the full census size (default
    32 = 4 GPUs x 8 GTSWs). ``lane_connected`` / ``lane_total`` give the
    per-lane breakdown (lane -> #CONNECTED / #sessions) so a check can assert
    "lane 0 connected dropped to 0 while overall dropped to 28". ``error``
    (non-empty) marks a poll where the HRT query failed — treated as null data
    by the evaluator (not counted as a real 0).
    """

    timestamp: str
    host: str
    connected: int
    expected: int
    lane_connected: Dict[int, int] = field(default_factory=dict)
    lane_total: Dict[int, int] = field(default_factory=dict)
    error: str = ""


@dataclass
class FsdbSessionWindowResult:
    """Structured verdict for an HRT FSDB-session-count evaluation window.

    ``min_connected`` / ``max_connected`` bound the observed CONNECTED count
    over the window (errored/null polls excluded). ``reached_expected`` is True
    iff some in-window sample equalled ``expected_connected``. ``samples`` is the
    number of non-null in-window samples; ``error_samples`` the null ones.
    ``last_connected`` is the final non-null count. ``per_lane_min`` maps lane ->
    min CONNECTED seen for that lane over the window (so churn on a specific lane
    is observable). ``impacted_lane_churn`` maps each requested impacted lane to
    whether its connected count was observed to drop below its lane_total.
    """

    host: str
    samples: int
    error_samples: int
    min_connected: Optional[int]
    max_connected: Optional[int]
    last_connected: Optional[int]
    reached_expected: bool
    per_lane_min: Dict[int, int] = field(default_factory=dict)
    impacted_lane_churn: Dict[int, bool] = field(default_factory=dict)
    detail: str = ""


class HrtFsdbSessionCollector(BaseCollector):
    """Polls HRT ``getFsdbSessions()`` for one GPU host, recording the CONNECTED
    session census per poll.

    Programmatic equivalent of counting CONNECTED HRT FSDB sessions: each poll
    captures the total CONNECTED count, the expected census size (default 32 =
    4 GPUs x 8 GTSWs), and a per-lane breakdown (lane -> #CONNECTED / #total
    across the 4 GPUs). A drain/kill of lane 0 on all 4 GPUs drops the overall
    count to 28 and lane 0's connected count to 0. The ``evaluate_window``
    helper returns a structured verdict the FpfHrtSessionStatHealthCheck
    interprets for both the disruption (drop-then-recover) and stable (no churn)
    contracts.

    One collector instance per host (mirroring the per-host session health
    check). A poll whose HRT query fails records an error row (null data) rather
    than a misleading all-zero census.
    """

    def __init__(
        self,
        host: str,
        expected_connected: int = 32,
        tmp_path: str = "/tmp/fpf_stress_hrt_fsdb_session.log",
        interval_sec: float = 3.0,
    ) -> None:
        super().__init__(tmp_path, interval_sec)
        self.host = host
        self.expected_connected = expected_connected
        self.rows: List[HrtFsdbSessionRow] = []

    def _write_header(self, f) -> None:
        f.write(
            f"{'timestamp':<30}  {'host':<22}  {'connected':>9}  {'expected':>8}  "
            f"per_lane (lane=conn/total ...)\n"
        )

    async def _poll_once(self) -> None:
        error = ""
        # `client.getFsdbSessions()` returns a Sequence (from generated thrift),
        # so we annotate as Sequence rather than List to avoid invariance issues.
        sessions: Sequence[Any] = []
        try:
            client_ctx = await get_hrt_client(self.host)
            async with client_ctx as client:
                sessions = await client.getFsdbSessions()
        except Exception as e:
            logger.error(f"[HrtFsdbSessionCollector] {self.host}: {e}")
            error = f"error: {e}"

        lane_connected: Dict[int, int] = {}
        lane_total: Dict[int, int] = {}
        connected = 0
        if not error:
            for s in sessions:
                lane = getattr(s, "plane_id", None)
                if lane is None:
                    continue
                lane = int(lane)
                lane_total[lane] = lane_total.get(lane, 0) + 1
                if _session_is_connected(s):
                    connected += 1
                    lane_connected[lane] = lane_connected.get(lane, 0) + 1
                else:
                    lane_connected.setdefault(lane, 0)

        ts = _now_str()
        row = HrtFsdbSessionRow(
            timestamp=ts,
            host=self.host,
            connected=connected,
            expected=self.expected_connected,
            lane_connected=lane_connected,
            lane_total=lane_total,
            error=error,
        )
        self.rows.append(row)

        if error:
            rendered = error
        else:
            rendered = (
                " ".join(
                    f"{lane}={lane_connected.get(lane, 0)}/{lane_total[lane]}"
                    for lane in sorted(lane_total)
                )
                or "-"
            )
        if self._file is not None:
            self._file.write(
                f"{ts:<30}  {self.host:<22}  {connected:>9}  "
                f"{self.expected_connected:>8}  {rendered}\n"
            )
            self._file.flush()
        self._write_json_row(
            {
                "collector": "hrt_fsdb_session",
                "timestamp": ts,
                "host": self.host,
                "connected": connected,
                "expected": self.expected_connected,
                "lane_connected": {str(k): v for k, v in lane_connected.items()},
                "lane_total": {str(k): v for k, v in lane_total.items()},
                "error": error,
            }
        )

    def evaluate_window(
        self,
        window_start: float,
        window_end: float,
        expected_connected: Optional[int] = None,
        impacted_lanes: Optional[List[int]] = None,
    ) -> FsdbSessionWindowResult:
        """Summarize the CONNECTED census over [window_start, window_end].

        ``expected_connected`` defaults to the collector's configured census
        size. ``impacted_lanes`` (when given) are the lanes a disruption is
        expected to churn; the result records, per impacted lane, whether its
        connected count was observed to drop below its total. Errored/null polls
        are excluded from the count statistics but counted in ``error_samples``.
        """
        expected = (
            expected_connected
            if expected_connected is not None
            else self.expected_connected
        )
        impacted = [int(x) for x in (impacted_lanes or [])]
        windowed = self.get_rows_in_window(window_start, window_end)

        good = [r for r in windowed if not r.error]
        error_samples = sum(1 for r in windowed if r.error)

        if not good:
            return FsdbSessionWindowResult(
                host=self.host,
                samples=0,
                error_samples=error_samples,
                min_connected=None,
                max_connected=None,
                last_connected=None,
                reached_expected=False,
                detail=(
                    "no non-null in-window samples"
                    + (f" ({error_samples} null)" if error_samples else "")
                ),
            )

        counts = [r.connected for r in good]
        min_connected = min(counts)
        max_connected = max(counts)
        last_connected = good[-1].connected
        reached_expected = any(c == expected for c in counts)

        # Per-lane minimum connected over the window.
        per_lane_min: Dict[int, int] = {}
        for r in good:
            for lane, conn in r.lane_connected.items():
                if lane not in per_lane_min or conn < per_lane_min[lane]:
                    per_lane_min[lane] = conn

        # Did each requested impacted lane churn (drop below its total)?
        impacted_lane_churn: Dict[int, bool] = {}
        for lane in impacted:
            churned = False
            for r in good:
                total = r.lane_total.get(lane)
                conn = r.lane_connected.get(lane)
                if total is None or conn is None:
                    continue
                if conn < total:
                    churned = True
                    break
            impacted_lane_churn[lane] = churned

        detail = (
            f"connected min={min_connected} max={max_connected} "
            f"last={last_connected} (expected {expected}); "
            f"{len(good)} samples"
            + (f", {error_samples} null" if error_samples else "")
        )
        if impacted:
            detail += " | impacted-lane churn: " + ", ".join(
                f"L{lane}={'yes' if impacted_lane_churn[lane] else 'no'}"
                for lane in impacted
            )

        return FsdbSessionWindowResult(
            host=self.host,
            samples=len(good),
            error_samples=error_samples,
            min_connected=min_connected,
            max_connected=max_connected,
            last_connected=last_connected,
            reached_expected=reached_expected,
            per_lane_min=per_lane_min,
            impacted_lane_churn=impacted_lane_churn,
            detail=detail,
        )

    def evaluate_recovery_hold(
        self,
        window_start: float,
        window_end: float,
        expected_connected: Optional[int] = None,
        recovery_min_sec: float = 60.0,
    ) -> Tuple[bool, Optional[float], str]:
        """Did the CONNECTED census recover to ``expected_connected`` and hold
        there for >= ``recovery_min_sec`` continuously up to window end?

        Walks the non-null in-window samples; finds the last contiguous tail run
        of samples at ``expected``. Returns (passed, held_sec, detail). ``passed``
        is True iff the tail run reaches window end and spans >= recovery_min_sec
        (a tail that is at expected but shorter than the floor fails; a census
        that drops below expected after recovering also fails). With < 2 samples
        the duration cannot be measured -> not passed.
        """
        expected = (
            expected_connected
            if expected_connected is not None
            else self.expected_connected
        )
        good = [
            (ts, r)
            for r in self.get_rows_in_window(window_start, window_end)
            if not r.error
            for ts in [self._row_ts(r)]
            if ts is not None
        ]
        good.sort(key=lambda x: x[0])
        if not good:
            return (False, None, "no non-null in-window samples for recovery")

        # Find the start of the final contiguous tail run at expected.
        last = good[-1][1]
        if last.connected != expected:
            return (
                False,
                None,
                f"did not recover by window end (last={last.connected}, "
                f"expected {expected})",
            )
        tail_start_ts = good[-1][0]
        for ts, r in reversed(good):
            if r.connected == expected:
                tail_start_ts = ts
            else:
                break
        held_sec = round(good[-1][0] - tail_start_ts, 1)
        passed = held_sec >= recovery_min_sec
        if passed:
            detail = (
                f"recovered to {expected} and held for {held_sec}s "
                f"(>= {recovery_min_sec:.0f}s floor)"
            )
        else:
            detail = (
                f"recovered to {expected} but held only {held_sec}s "
                f"(< {recovery_min_sec:.0f}s floor)"
            )
        return (passed, held_sec, detail)

    @staticmethod
    def _row_ts(row) -> Optional[float]:
        try:
            return _parse_ts(row.timestamp).timestamp()
        except (ValueError, AttributeError):
            return None
