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
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from neteng.netcastle.logger import get_root_logger
from taac.internal.driver.fboss_switch_internal import (
    FbossSwitchInternal,
)

# ``BaseCollector`` + the timestamp helpers were extracted to
# ``taac.libs.collectors.base_collector`` so the domain-agnostic pieces
# (poll loop, thread lifecycle, atexit cleanup, per-poll timeout, NULL-data
# recording, timestamped-row storage) live in a module with no Meta-internal
# imports and can be used by OSS test configs. Re-imported here for
# backward compatibility with existing FPF call sites.
from taac.libs.collectors.base_collector import (  # noqa: F401
    _now_str,
    _parse_ts,
    BaseCollector,
)
from taac.libs.fpf.fpf_bgp_rib import (  # oss-rewrite-touch
    _count_matching,
    get_bgp_rib,
    get_bgp_rib_subprefixes,
)
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


def _single_host(hosts: List[str]) -> str:
    """Best-effort single-host label for a result built without a host filter
    (multi-host collectors carry ``hosts``): the sole host, else a joined label."""
    if len(hosts) == 1:
        return hosts[0]
    return ",".join(hosts) if hosts else "?"


# ---------------------------------------------------------------------------
# Shared per-sample "blip handling" contract
# ---------------------------------------------------------------------------

# Two-mode blip-handling contract shared by the FPF HRT/data-plane convergence
# collector checks. ``samples`` is a chronologically-ordered list where each
# element is the in-window value of a metric, or ``None`` for a null/missing
# sample (a collection blip — e.g. a poll timeout or absent data). Values are
# compared to ``expected`` with ``==`` (so the helper is generic over ints,
# lists, sets, ...).
#
#   "strict"            — every non-null sample must equal ``expected`` (current
#                         default; null samples are NOT tolerated and count as a
#                         failure, matching the legacy "no drops" behaviour).
#   "last_sample"       — MODE A (disruptive triggers: kill / agent coldboot /
#                         reboot / GR-beyond): ignore all mid-window samples; only
#                         the LAST non-null sample must equal ``expected``.
#   "skip_null_strict"  — MODE B (graceful within-window triggers: GR / GR-in for
#                         fsdb/bgp/wedge_agent): TOLERATE null/missing samples, but
#                         every NON-NULL sample must equal ``expected`` and the
#                         last non-null sample must equal ``expected``.
BLIP_MODE_STRICT: str = "strict"
BLIP_MODE_LAST_SAMPLE: str = "last_sample"
BLIP_MODE_SKIP_NULL_STRICT: str = "skip_null_strict"
BLIP_MODE_LAST_N: str = "last_n"


def evaluate_blip_series(
    samples: List[Any],
    expected: Any,
    mode: str = BLIP_MODE_STRICT,
    last_n: int = 10,
) -> Tuple[bool, str]:
    """Evaluate a value-or-null sample series against ``expected`` under ``mode``.

    Returns ``(passed, detail)``. See the BLIP_MODE_* docstring above for the
    per-mode contract. ``None`` elements of ``samples`` are null/missing samples
    (collection blips). A series with no samples at all (or, for the modes that
    require a non-null tail, no non-null samples) fails.
    """
    total = len(samples)
    non_null = [v for v in samples if v is not None]
    null_count = total - len(non_null)

    if total == 0:
        return (False, "no samples in window")

    if mode == BLIP_MODE_LAST_SAMPLE:
        if not non_null:
            return (
                False,
                f"no non-null samples in window ({null_count} null)",
            )
        last = non_null[-1]
        passed = last == expected
        if passed:
            return (
                True,
                f"last sample == {expected} "
                f"({len(non_null)}/{total} non-null; mid-window samples ignored)",
            )
        return (
            False,
            f"last sample {last} != expected {expected} "
            f"({len(non_null)}/{total} non-null)",
        )

    if mode == BLIP_MODE_SKIP_NULL_STRICT:
        if not non_null:
            return (
                False,
                f"no non-null samples in window ({null_count} null)",
            )
        bad = [v for v in non_null if v != expected]
        if bad:
            return (
                False,
                f"{len(bad)}/{len(non_null)} non-null sample(s) != expected "
                f"{expected} (e.g. {bad[0]}); {null_count} null tolerated",
            )
        if non_null[-1] != expected:
            return (
                False,
                f"last non-null sample {non_null[-1]} != expected {expected}",
            )
        return (
            True,
            f"all {len(non_null)} non-null sample(s) == {expected} "
            f"({null_count} null tolerated)",
        )

    if mode == BLIP_MODE_LAST_N:
        if not non_null:
            return (
                False,
                f"no non-null samples in window ({null_count} null)",
            )
        tail = non_null[-last_n:] if len(non_null) >= last_n else non_null
        bad = [v for v in tail if v != expected]
        if bad:
            return (
                False,
                f"last {len(tail)} non-null: {len(bad)}/{len(tail)} != expected "
                f"{expected} (e.g. {bad[0]})",
            )
        return (
            True,
            f"last {len(tail)} non-null samples == {expected} (recovered; "
            f"{len(non_null)}/{total} non-null total)",
        )

    # BLIP_MODE_STRICT (default): every sample must be non-null and == expected.
    bad = [v for v in samples if v != expected]
    if bad:
        return (
            False,
            f"{len(bad)}/{total} sample(s) != expected {expected} "
            f"(e.g. {bad[0]}; {null_count} null)",
        )
    return (True, f"all {total} sample(s) == {expected}")


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
    valid: bool = True
    notes: str = ""
    plane_ids: List[int] = field(default_factory=lambda: list(range(NUM_LANES)))


@dataclass
class HrtRemoteFailureRow:
    timestamp: str
    host: str
    device_id: int
    lane_counts: List[int] = field(default_factory=lambda: [0] * NUM_LANES)
    unique: int = 0
    valid: bool = True
    notes: str = ""
    plane_ids: List[int] = field(default_factory=lambda: list(range(NUM_LANES)))


@dataclass
class BgpRibRow:
    timestamp: str
    gtsw: str
    matched: int
    total: int
    notes: str = ""
    request_start_epoch: float = 0.0
    request_end_epoch: float = 0.0
    duration_sec: float = 0.0


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
    host: Optional[str] = None
    device_id: Optional[int] = None
    error_count: int = 0


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
        fsdb_mode: str = "canonical",
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
            per_gtsw_timeout = max(0.1, self.POLL_TIMEOUT_SEC - 1.0)
            try:
                driver = FbossSwitchInternal(gtsw, logger)
                rib_map = await asyncio.wait_for(
                    get_fsdb_rib_map(driver, mode=self.fsdb_mode),
                    timeout=per_gtsw_timeout,
                )
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
            except asyncio.TimeoutError:
                self._record_host_timeout(gtsw, per_gtsw_timeout)
                notes = f"error: poll timeout ({per_gtsw_timeout:.0f}s)"
                matched = 0
                total = 0
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

        tasks = [asyncio.create_task(_one_gtsw(g)) for g in self.gtsws]
        try:
            for completed in asyncio.as_completed(tasks):
                row = await completed
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
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

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


def _normalize_local_plane_ids(plane_ids: Optional[List[int]]) -> List[int]:
    selected = list(range(NUM_LANES)) if plane_ids is None else list(plane_ids)
    if selected != list(range(len(selected))):
        raise ValueError(
            f"HRT plane_ids must be contiguous local IDs starting at 0; got {selected}"
        )
    return selected


class HrtBulkCollector(BaseCollector):
    """Polls HRT getPrefixTable per-lane counts for a supernet filter."""

    def __init__(
        self,
        hosts: List[str],
        device_ids: Optional[List[int]] = None,
        supernet: str = "5000:dd::/32",
        tmp_path: str = "/tmp/fpf_stress_hrt_bulk.log",
        interval_sec: float = 2.0,
        plane_ids: Optional[List[int]] = None,
    ) -> None:
        super().__init__(tmp_path, interval_sec)
        self.hosts = hosts
        self.device_ids = device_ids or [0]
        self.plane_ids = _normalize_local_plane_ids(plane_ids)
        self.supernet = ipaddress.IPv6Network(supernet, strict=False)
        self.rows: List[HrtBulkRow] = []

    def _write_header(self, f) -> None:
        lane_hdr = "  ".join(f"L{i}" for i in self.plane_ids)
        f.write(
            f"{'timestamp':<28}  {'host':<24}  {'dev':>3}  {lane_hdr}    [unique]\n"
        )

    async def _poll_once(self) -> None:
        async def _one_host(host: str) -> List[HrtBulkRow]:
            timestamp = _now_str()
            try:
                client_ctx = await get_hrt_client(host)
                async with client_ctx as client:
                    prefix_table = await client.getPrefixTable()
                return [
                    HrtBulkRow(
                        timestamp=timestamp,
                        host=host,
                        device_id=dev_id,
                        lane_counts=counts,
                        unique=total_unique,
                        plane_ids=self.plane_ids,
                    )
                    for dev_id in self.device_ids
                    for counts, total_unique in [
                        count_per_lane(
                            prefix_table, dev_id, self.supernet, self.plane_ids
                        )
                    ]
                ]
            except Exception as e:
                notes = f"error: {e}"
                logger.error(f"[HrtBulkCollector] {host}: {e}")
                return [
                    HrtBulkRow(
                        timestamp=timestamp,
                        host=host,
                        device_id=dev_id,
                        lane_counts=[],
                        unique=0,
                        valid=False,
                        notes=notes,
                        plane_ids=self.plane_ids,
                    )
                    for dev_id in self.device_ids
                ]

        host_rows = await asyncio.gather(*[_one_host(host) for host in self.hosts])
        for rows in host_rows:
            for row in rows:
                counts = row.lane_counts
                self.rows.append(row)
                lane_str = (
                    "  ".join(f"{c:>5}" for c in counts)
                    if row.valid
                    else "  ".join(f"{'NULL':>5}" for _ in self.plane_ids)
                )
                line = (
                    f"{row.timestamp:<28}  {row.host:<24}  {row.device_id:>3}  "
                    f"{lane_str}    [unique={row.unique}] {row.notes}\n"
                )
                self._file.write(line)
                self._write_json_row(
                    {
                        "collector": "hrt_bulk",
                        "timestamp": row.timestamp,
                        "host": row.host,
                        "device_id": row.device_id,
                        "lane_counts": row.lane_counts,
                        "plane_ids": row.plane_ids,
                        "unique": row.unique,
                        "valid": row.valid,
                        "notes": row.notes,
                    }
                )
        self._file.flush()

    def evaluate_per_lane(
        self,
        trigger_time: datetime,
        lanes: List[int],
        deadline_sec: int = 300,
        expected_per_lane: Optional[Dict[int, int]] = None,
        device_ids: Optional[List[int]] = None,
        only_hosts: Optional[List[str]] = None,
    ) -> List[PerLaneResult]:
        """Evaluate every selected (host, device_id, local-plane) tuple."""
        if expected_per_lane is None:
            expected_per_lane = {lane: int(20000) for lane in lanes}
        trigger_ts = trigger_time.timestamp()
        results = []
        selected_hosts = (
            only_hosts or self.hosts or sorted({row.host for row in self.rows})
        )
        selected_devices = device_ids or self.device_ids
        for host in sorted(selected_hosts):
            for device_id in sorted(selected_devices):
                tuple_rows = [
                    row
                    for row in self.rows
                    if row.host == host and row.device_id == device_id
                ]
                for lane_id in sorted(lanes):
                    expected = expected_per_lane.get(lane_id, 0)
                    convergence_sec = None
                    last_actual = 0
                    valid_samples = 0
                    error_count = 0
                    for row in tuple_rows:
                        if not row.valid or row.notes.startswith("error:"):
                            error_count += 1
                            continue
                        if lane_id >= len(row.lane_counts):
                            continue
                        valid_samples += 1
                        try:
                            row_ts = _parse_ts(row.timestamp).timestamp()
                        except ValueError:
                            continue
                        count = row.lane_counts[lane_id]
                        last_actual = count
                        if count >= expected and convergence_sec is None:
                            convergence_sec = round(row_ts - trigger_ts, 1)

                    passed = (
                        valid_samples > 0
                        and convergence_sec is not None
                        and error_count == 0
                    )
                    identity = f"{host}/dev{device_id}/L{lane_id}"
                    if not valid_samples:
                        detail = f"no valid samples ({error_count} error/null)"
                    elif passed:
                        detail = f"reached {expected} in {convergence_sec}s"
                    elif error_count:
                        detail = (
                            f"reached {last_actual}/{expected}, but saw "
                            f"{error_count} error/null sample(s)"
                        )
                    else:
                        detail = f"only reached {last_actual}/{expected}"
                    results.append(
                        PerLaneResult(
                            lane=lane_id,
                            device=identity,
                            check_type="HRT bulk",
                            passed=passed,
                            expected=expected,
                            actual=last_actual,
                            convergence_sec=convergence_sec,
                            detail=detail,
                            host=host,
                            device_id=device_id,
                            error_count=error_count,
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
        device_ids: Optional[List[int]] = None,
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
                only_hosts=only_hosts,
                device_ids=device_ids,
            )
        finally:
            self.rows = saved_rows


# ---------------------------------------------------------------------------
# BGP RIB Collector
# ---------------------------------------------------------------------------


class BgpRibCollector(BaseCollector):
    """Poll BGP subnet counts with per-GTSW request-boundary telemetry.

    Every row records request start, completion, and duration so health checks
    can attribute a timeout to the playbook in which the request began instead
    of whichever playbook happened to receive the completed timeout row.
    """

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
        # One independently scheduled request per GTSW. The health check reads
        # this map after the SLA deadline so an already-started boundary request
        # can finish and be classified without allowing overlapping requests.
        self.inflight_request_starts: Dict[str, float] = {}

    def _write_header(self, f) -> None:
        f.write(
            f"{'timestamp':<34}  {'gtsw':<34}  {'matched':>8}  {'total':>8}  "
            f"{'req_start':>14}  {'req_end':>14}  {'duration_s':>10}  notes\n"
        )

    def has_inflight_request_started_by(
        self, target_devices: Sequence[str], deadline: float
    ) -> bool:
        """Whether a target still has a request that began by ``deadline``."""
        return any(
            0 < self.inflight_request_starts.get(gtsw, 0.0) <= deadline
            for gtsw in target_devices
        )

    @property
    def per_gtsw_timeout_sec(self) -> float:
        return min(30.0, max(0.1, self.POLL_TIMEOUT_SEC - 1.0))

    def _append_row(self, row: BgpRibRow) -> None:
        self.rows.append(row)
        line = (
            f"{row.timestamp:<34}  {row.gtsw:<34}  {row.matched:>8}  "
            f"{row.total:>8}  {row.request_start_epoch:>14.3f}  "
            f"{row.request_end_epoch:>14.3f}  {row.duration_sec:>10.3f}  "
            f"{row.notes}\n"
        )
        self._file.write(line)
        self._write_json_row(
            {
                "collector": "bgp_rib",
                "timestamp": row.timestamp,
                "gtsw": row.gtsw,
                "matched": row.matched,
                "total": row.total,
                "request_start_epoch": row.request_start_epoch,
                "request_end_epoch": row.request_end_epoch,
                "duration_sec": row.duration_sec,
                "notes": row.notes,
            }
        )
        self._file.flush()

    async def _poll_gtsw_once(self, gtsw: str) -> None:
        notes = ""
        per_gtsw_timeout = self.per_gtsw_timeout_sec
        request_start_epoch = time.time()
        self.inflight_request_starts[gtsw] = request_start_epoch
        try:
            try:
                rib_entries = await asyncio.wait_for(
                    get_bgp_rib_subprefixes(gtsw, self.subnet),
                    timeout=per_gtsw_timeout,
                )
                total = len(rib_entries)
                matched = _count_matching(rib_entries, self.subnet, None)
            except asyncio.TimeoutError:
                self._record_host_timeout(gtsw, per_gtsw_timeout)
                notes = f"error: poll timeout ({per_gtsw_timeout:.0f}s)"
                matched = 0
                total = 0
            except Exception as e:
                notes = f"error: {e}"
                matched = 0
                total = 0
            request_end_epoch = time.time()
            self._append_row(
                BgpRibRow(
                    timestamp=_now_str(),
                    gtsw=gtsw,
                    matched=matched,
                    total=total,
                    notes=notes,
                    request_start_epoch=request_start_epoch,
                    request_end_epoch=request_end_epoch,
                    duration_sec=round(request_end_epoch - request_start_epoch, 3),
                )
            )
        finally:
            self.inflight_request_starts.pop(gtsw, None)

    async def _poll_once(self) -> None:
        await asyncio.gather(*(self._poll_gtsw_once(gtsw) for gtsw in self.gtsws))

    async def _poll_gtsw_loop(self, gtsw: str) -> None:
        """Poll one GTSW serially, independently of every sibling GTSW."""
        while not self._stop_flag.is_set():
            try:
                await self._poll_gtsw_once(gtsw)
            except asyncio.CancelledError:
                break
            except Exception as error:
                logger.error(f"[BgpRibCollector] {gtsw} poll error: {error}")
            try:
                await asyncio.sleep(self.interval_sec)
            except asyncio.CancelledError:
                break

    async def _run_loop(self) -> None:
        """Run one non-overlapping poll loop per GTSW.

        A slow observer therefore cannot delay the next DUT request. All workers
        share this collector's event loop and output file, and shutdown cancels
        every in-flight request through BaseCollector._cancel_thread_tasks().
        """
        mode = "a" if self._append_mode else "w"
        with open(self.tmp_path, mode) as f:
            self._file = f
            if not self._append_mode or f.tell() == 0:
                f.write("=" * 100 + "\n")
                self._write_header(f)
                f.write("-" * 100 + "\n")
                f.flush()
            workers = [
                asyncio.create_task(self._poll_gtsw_loop(gtsw)) for gtsw in self.gtsws
            ]
            try:
                await asyncio.gather(*workers)
            except asyncio.CancelledError:
                pass
            finally:
                for worker in workers:
                    if not worker.done():
                        worker.cancel()
                await asyncio.gather(*workers, return_exceptions=True)

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
        plane_ids: Optional[List[int]] = None,
    ) -> None:
        super().__init__(tmp_path, interval_sec)
        self.hosts = hosts
        self.device_ids = device_ids or [0]
        self.plane_ids = _normalize_local_plane_ids(plane_ids)
        self.supernet = ipaddress.IPv6Network(supernet, strict=False)
        self.rows: List[HrtRemoteFailureRow] = []

    def _write_header(self, f) -> None:
        lane_hdr = "  ".join(f"L{i}" for i in self.plane_ids)
        f.write(
            f"{'timestamp':<28}  {'host':<24}  {'dev':>3}  {lane_hdr}    [unique]\n"
        )

    async def _poll_once(self) -> None:
        async def _one_host(host: str) -> List[HrtRemoteFailureRow]:
            timestamp = _now_str()
            try:
                client_ctx = await get_hrt_client(host)
                async with client_ctx as client:
                    remote_failures = await client.getRemoteFailures()
                return [
                    HrtRemoteFailureRow(
                        timestamp=timestamp,
                        host=host,
                        device_id=dev_id,
                        lane_counts=counts,
                        unique=total_unique,
                        plane_ids=self.plane_ids,
                    )
                    for dev_id in self.device_ids
                    for counts, total_unique in [
                        count_failed_per_lane(
                            remote_failures, dev_id, self.supernet, self.plane_ids
                        )
                    ]
                ]
            except Exception as e:
                notes = f"error: {e}"
                logger.error(f"[HrtRemoteFailureCollector] {host}: {e}")
                return [
                    HrtRemoteFailureRow(
                        timestamp=timestamp,
                        host=host,
                        device_id=dev_id,
                        lane_counts=[],
                        unique=0,
                        valid=False,
                        notes=notes,
                        plane_ids=self.plane_ids,
                    )
                    for dev_id in self.device_ids
                ]

        host_rows = await asyncio.gather(*[_one_host(host) for host in self.hosts])
        for rows in host_rows:
            for row in rows:
                counts = row.lane_counts
                self.rows.append(row)
                lane_str = (
                    "  ".join(f"{c:>5}" for c in counts)
                    if row.valid
                    else "  ".join(f"{'NULL':>5}" for _ in self.plane_ids)
                )
                line = (
                    f"{row.timestamp:<28}  {row.host:<24}  {row.device_id:>3}  "
                    f"{lane_str}    [unique={row.unique}] {row.notes}\n"
                )
                self._file.write(line)
                self._write_json_row(
                    {
                        "collector": "hrt_remote_failure",
                        "timestamp": row.timestamp,
                        "host": row.host,
                        "device_id": row.device_id,
                        "lane_counts": row.lane_counts,
                        "plane_ids": row.plane_ids,
                        "unique": row.unique,
                        "valid": row.valid,
                        "notes": row.notes,
                    }
                )
        self._file.flush()

    def evaluate_per_lane_drain(
        self,
        trigger_time: datetime,
        lanes: List[int],
        expected_per_lane: Optional[Dict[int, int]] = None,
        max_convergence_sec: int = 120,
        device_ids: Optional[List[int]] = None,
        only_hosts: Optional[List[str]] = None,
        _single_tuple: bool = False,
    ) -> List[PerLaneResult]:
        """Drain direction: find 0->N transition per lane."""
        if not _single_tuple:
            results: List[PerLaneResult] = []
            selected_hosts = (
                only_hosts or self.hosts or sorted({row.host for row in self.rows})
            )
            selected_devices = device_ids or self.device_ids
            saved_rows = self.rows
            try:
                for host in sorted(selected_hosts):
                    for device_id in sorted(selected_devices):
                        self.rows = [
                            row
                            for row in saved_rows
                            if row.host == host and row.device_id == device_id
                        ]
                        tuple_results = self.evaluate_per_lane_drain(
                            trigger_time=trigger_time,
                            lanes=lanes,
                            expected_per_lane=expected_per_lane,
                            max_convergence_sec=max_convergence_sec,
                            _single_tuple=True,
                        )
                        for result in tuple_results:
                            result.host = host
                            result.device_id = device_id
                            result.device = f"{host}/dev{device_id}/L{result.lane}"
                        results.extend(tuple_results)
                return results
            finally:
                self.rows = saved_rows
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
        device_ids: Optional[List[int]] = None,
        only_hosts: Optional[List[str]] = None,
        _single_tuple: bool = False,
    ) -> List[PerLaneResult]:
        """Recovery direction: find N->0 transition per lane."""
        if not _single_tuple:
            results: List[PerLaneResult] = []
            selected_hosts = (
                only_hosts or self.hosts or sorted({row.host for row in self.rows})
            )
            selected_devices = device_ids or self.device_ids
            saved_rows = self.rows
            try:
                for host in sorted(selected_hosts):
                    for device_id in sorted(selected_devices):
                        self.rows = [
                            row
                            for row in saved_rows
                            if row.host == host and row.device_id == device_id
                        ]
                        tuple_results = self.evaluate_per_lane_recovery(
                            trigger_time=trigger_time,
                            lanes=lanes,
                            expected_per_lane=expected_per_lane,
                            max_convergence_sec=max_convergence_sec,
                            _single_tuple=True,
                        )
                        for result in tuple_results:
                            result.host = host
                            result.device_id = device_id
                            result.device = f"{host}/dev{device_id}/L{result.lane}"
                        results.extend(tuple_results)
                return results
            finally:
                self.rows = saved_rows
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
        expected_per_lane: Optional[Dict[int, int]] = None,
        last_sample_only: bool = False,
        skip_null_strict: bool = False,
        last_n: int | None = None,
        device_ids: Optional[List[int]] = None,
        only_hosts: Optional[List[str]] = None,
        _single_tuple: bool = False,
    ) -> List[PerLaneResult]:
        """Stable-state: assert each lane stays at its expected count.

        With ``last_sample_only=True`` (MODE A), assert only that the LAST sample
        before the window end equals the expected value — i.e. the metric fully
        reconverged by test-case end, tolerating a bounded transient. Use
        for DISRUPTIVE process-disruption configs where the HRT layer legitimately
        shows a recovery transient (e.g. GR-beyond / coldboot negative-route
        clearing in ~36-57s) that fully clears by the end (last=0).

        With ``skip_null_strict=True`` (MODE B), TOLERATE null/missing samples
        (collection blips) but require every NON-NULL sample, including the last,
        to equal the expected value. Use for GRACEFUL within-window triggers.
        """
        if not _single_tuple:
            results: List[PerLaneResult] = []
            selected_hosts = (
                only_hosts or self.hosts or sorted({row.host for row in self.rows})
            )
            selected_devices = device_ids or self.device_ids
            saved_rows = self.rows
            try:
                for host in sorted(selected_hosts):
                    for device_id in sorted(selected_devices):
                        self.rows = [
                            row
                            for row in saved_rows
                            if row.host == host and row.device_id == device_id
                        ]
                        tuple_results = self.evaluate_per_lane_stable(
                            lanes=lanes,
                            expected_per_lane=expected_per_lane,
                            last_sample_only=last_sample_only,
                            skip_null_strict=skip_null_strict,
                            last_n=last_n,
                            _single_tuple=True,
                        )
                        for result in tuple_results:
                            result.host = host
                            result.device_id = device_id
                            result.device = f"{host}/dev{device_id}/L{result.lane}"
                        results.extend(tuple_results)
                return results
            finally:
                self.rows = saved_rows
        expected_per_lane = expected_per_lane or {}
        results = []
        for lane_id in sorted(lanes):
            expected = expected_per_lane.get(lane_id, 0)
            max_seen = 0
            mismatch_count = 0
            error_count = 0
            total_rows = 0
            last_count = expected
            samples: List[Any] = []
            for row in self.rows:
                if not row.valid or row.notes.startswith("error:"):
                    error_count += 1
                    samples.append(None)
                    continue
                if lane_id >= len(row.lane_counts):
                    # Missing lane data — a null/blip sample for this lane.
                    samples.append(None)
                    continue
                total_rows += 1
                count = row.lane_counts[lane_id]
                samples.append(count)
                if count > max_seen:
                    max_seen = count
                if count != expected:
                    mismatch_count += 1
                last_count = count

            # Strict: every in-window sample must equal the expected value. The
            # default expected value is 0. The window MUST start at
            # the recorded disruption time (callers scope via
            # ``evaluate_per_lane_window(window_start=disruption_time, ...)``) so
            # the pre-disruption injection ramp is excluded — the negative-route
            # count legitimately blips during prefix injection (e.g. L0=100 for a
            # single ~3s sample) ~minutes BEFORE the drain, and that artifact must
            # not be counted against drain stability. Within the post-disruption
            # window a device/link drain produces NO negative-route blip on the
            # impacted lane, so any nonzero is a real regression.
            if last_n is not None:
                # LAST_N mode — the last N non-null samples must all hold the
                # expected recovered state; earlier transients are tolerated.
                passed, detail = evaluate_blip_series(
                    samples, expected, BLIP_MODE_LAST_N, last_n=last_n
                )
            elif last_sample_only:
                # MODE A — reconverged-by-end: only the last in-window sample must
                # equal expected; a bounded transient during the disruption is
                # tolerated.
                _passed, _ = evaluate_blip_series(
                    samples, expected, BLIP_MODE_LAST_SAMPLE
                )
                passed = _passed
                if passed:
                    detail = (
                        f"reconverged by window end (last={expected}; mismatched in "
                        f"{mismatch_count}/{total_rows} samples, max={max_seen})"
                    )
                else:
                    detail = (
                        f"NOT reconverged by window end (last={last_count} != "
                        f"{expected}; mismatched in {mismatch_count}/{total_rows} "
                        f"samples, max={max_seen})"
                    )
            elif skip_null_strict:
                # MODE B — graceful within-window: every non-null sample must
                # equal expected (including the last non-null), while null or
                # missing samples are tolerated.
                passed, detail = evaluate_blip_series(
                    samples, expected, BLIP_MODE_SKIP_NULL_STRICT
                )
            else:
                passed = total_rows > 0 and mismatch_count == 0 and error_count == 0
                if passed:
                    detail = f"stable at {expected} across {total_rows} samples"
                else:
                    detail = (
                        f"mismatched expected {expected} in "
                        f"{mismatch_count}/{total_rows} samples "
                        f"(max={max_seen}, last={last_count}, "
                        f"error/null={error_count})"
                    )
            results.append(
                PerLaneResult(
                    lane=lane_id,
                    device=f"HRT neg L{lane_id}",
                    check_type="HRT remote_failure stable",
                    passed=passed,
                    expected=expected,
                    actual=max_seen,
                    convergence_sec=None,
                    detail=detail,
                    error_count=error_count,
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
        device_ids: Optional[List[int]] = None,
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
                return self.evaluate_per_lane_stable(
                    lanes=lanes,
                    expected_per_lane=expected_per_lane,
                    device_ids=device_ids,
                    only_hosts=only_hosts,
                )
            if direction == "stable_last_sample":
                return self.evaluate_per_lane_stable(
                    lanes=lanes,
                    expected_per_lane=expected_per_lane,
                    last_sample_only=True,
                    device_ids=device_ids,
                    only_hosts=only_hosts,
                )
            if direction == "stable_skip_null_strict":
                return self.evaluate_per_lane_stable(
                    lanes=lanes,
                    expected_per_lane=expected_per_lane,
                    skip_null_strict=True,
                    device_ids=device_ids,
                    only_hosts=only_hosts,
                )
            if direction == "stable_last_n":
                return self.evaluate_per_lane_stable(
                    lanes=lanes,
                    expected_per_lane=expected_per_lane,
                    last_n=10,
                    device_ids=device_ids,
                    only_hosts=only_hosts,
                )
            if direction == "recovery":
                return self.evaluate_per_lane_recovery(
                    trigger_time=trigger_time,
                    lanes=lanes,
                    expected_per_lane=expected_per_lane,
                    max_convergence_sec=max_convergence_sec,
                    device_ids=device_ids,
                    only_hosts=only_hosts,
                )
            return self.evaluate_per_lane_drain(
                trigger_time=trigger_time,
                lanes=lanes,
                expected_per_lane=expected_per_lane,
                max_convergence_sec=max_convergence_sec,
                device_ids=device_ids,
                only_hosts=only_hosts,
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

    ONE collector instance holds ALL monitored hosts (``hosts``); each host
    monitors its OWN prefixes via ``prefixes_by_host`` ({host: [prefixes]}). Each
    poll loops the hosts and queries each with ITS prefixes; every row carries
    its ``host``; a single file with a host column.
    """

    def __init__(
        self,
        hosts: List[str],
        device_id: int,
        prefixes_by_host: Dict[str, List[str]],
        tmp_path: str = "/tmp/fpf_prod_hrt_prefix.log",
        interval_sec: float = 3.0,
    ) -> None:
        super().__init__(tmp_path, interval_sec)
        self.hosts = hosts
        self.device_id = device_id
        # host -> normalized target-prefix set (None = monitor all prefixes).
        self.target_prefixes_by_host: Dict[str, Optional[set]] = {
            h: ({normalize_prefix(p) for p in prefixes_by_host.get(h, [])} or None)
            for h in hosts
        }
        self.rows: List[ProdHrtPrefixRow] = []

    def _write_header(self, f) -> None:
        f.write(
            f"{'timestamp':<30}  {'host':<22}  {'prefix':<40}  "
            f"{'reachable':<16}  {'drained':<12}  {'unreachable':<14}  "
            f"{'plane_up':<16}  plane_down\n"
        )

    async def _poll_once(self) -> None:
        # Poll all hosts concurrently so a slow/hung host never serializes behind
        # (or stalls) its siblings. Each host is capped by its OWN timeout: a
        # single hung host records only its own per-host NULL (via
        # _record_host_timeout) instead of tripping the base _run_loop's
        # whole-cycle wait_for and marking every host FAIL. The per-host budget
        # is kept just under POLL_TIMEOUT_SEC so the outer backstop fires only
        # when the entire cycle genuinely stalls.
        host_timeout = max(1.0, self.POLL_TIMEOUT_SEC - 10.0)

        async def _poll_guarded(host: str) -> None:
            try:
                await asyncio.wait_for(self._poll_host(host), timeout=host_timeout)
            except asyncio.TimeoutError:
                self._record_host_timeout(host, host_timeout)

        results = await asyncio.gather(
            *(_poll_guarded(host) for host in self.hosts),
            return_exceptions=True,
        )
        # _poll_guarded swallows per-host errors, so a returned exception means
        # one escaped it (e.g. during row-writing); surface it per host rather
        # than letting return_exceptions discard it silently.
        for host, result in zip(self.hosts, results):
            if isinstance(result, BaseException):
                logger.error(
                    f"[{self.__class__.__name__}] {host} poll raised: {result}"
                )

    async def _poll_host(self, host: str) -> None:
        target_prefixes = self.target_prefixes_by_host.get(host)
        try:
            client_ctx = await get_hrt_client(host)
            async with client_ctx as client:
                prefixes = await client.getPrefixTable()
                neg_routes = await client.getRemoteFailures()
                plane_status_entries = await client.getPlaneStatus()
            prefix_map = build_prefix_map(
                prefixes,
                neg_routes,
                plane_status_entries,
                target_prefixes,
                {self.device_id},
            )
        except Exception as e:
            logger.error(f"[ProdHrtPrefixCollector] {host} dev{self.device_id}: {e}")
            prefix_map = {}

        ts = _now_str()
        self.rows.append(ProdHrtPrefixRow(timestamp=ts, host=host, prefixes=prefix_map))

        def _fmt(planes: List[int]) -> str:
            return ",".join(str(p) for p in planes) if planes else "-"

        for pfx in sorted(prefix_map):
            rb = prefix_map[pfx]
            self._file.write(
                f"{ts:<30}  {host:<22}  {pfx:<40}  "
                f"{_fmt(rb.reachable_planes):<16}  {_fmt(rb.drained_planes):<12}  "
                f"{_fmt(rb.unreachable_planes):<14}  {_fmt(rb.plane_up):<16}  "
                f"{_fmt(rb.plane_down)}\n"
            )
            self._write_json_row(
                {
                    "collector": "prod_hrt_prefix",
                    "timestamp": ts,
                    "host": host,
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

    def hosts_in_window(self, window_start: float, window_end: float) -> List[str]:
        """Distinct hosts present in the in-window rows (stable-sorted)."""
        seen: List[str] = []
        for r in self.get_rows_in_window(window_start, window_end):
            if r.host not in seen:
                seen.append(r.host)
        return sorted(seen)

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
                (self._row_ts(row), row.host, row.prefixes[pfx])
                for row in windowed
                if pfx in row.prefixes
            ]
            samples = [(ts, h, rb) for ts, h, rb in samples if ts is not None]
            samples.sort(key=lambda x: x[0])
            if not samples:
                continue
            pfx_host = samples[0][1]
            baseline = set(samples[0][2].reachable_planes)
            regression = None
            for ts, _h, rb in samples:
                missing = baseline - set(rb.reachable_planes)
                if missing:
                    regression = (ts, sorted(missing), rb)
                    break
            if regression is None:
                results.append(
                    ProdPrefixStabilityResult(
                        prefix=pfx,
                        host=pfx_host,
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
                        host=pfx_host,
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

# Legacy RTP plane count. New paired-device hosts pass ``num_planes=4``.
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
    valid: bool = True
    notes: str = ""


@dataclass
class PlaneStatusResult:
    """Per-plane verdict over an evaluation window."""

    plane: int
    passed: bool
    expected_state: str
    observed_state: str
    samples: int
    detail: str = ""
    host: str = ""
    device_id: int = 0


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
        hosts: List[str],
        device_id: Optional[int] = None,
        device_ids: Optional[List[int]] = None,
        tmp_path: str = "/tmp/fpf_stress_hrt_plane_status.log",
        interval_sec: float = 3.0,
        num_planes: int = NUM_PLANES,
    ) -> None:
        super().__init__(tmp_path, interval_sec)
        self.hosts = hosts
        self.device_ids = sorted(set(device_ids or [device_id or 0]))
        self.device_id = self.device_ids[0]
        self.num_planes = num_planes
        self.rows: List[HrtPlaneStatusRow] = []

    def _write_header(self, f) -> None:
        f.write(
            f"{'timestamp':<30}  {'host':<22}  {'device':<7}  "
            f"plane_states (plane=STATE ...)\n"
        )

    async def _poll_once(self) -> None:
        # Poll all hosts concurrently so a slow/hung host never serializes behind
        # (or stalls) its siblings. Each host is capped by its OWN timeout: a
        # single hung host records only its own per-host NULL (via
        # _record_host_timeout) instead of tripping the base _run_loop's
        # whole-cycle wait_for and marking every host FAIL. The per-host budget
        # is kept just under POLL_TIMEOUT_SEC so the outer backstop fires only
        # when the entire cycle genuinely stalls.
        host_timeout = max(1.0, self.POLL_TIMEOUT_SEC - 10.0)

        async def _poll_guarded(host: str) -> None:
            try:
                await asyncio.wait_for(self._poll_host(host), timeout=host_timeout)
            except asyncio.TimeoutError:
                self._record_host_timeout(host, host_timeout)

        results = await asyncio.gather(
            *(_poll_guarded(host) for host in self.hosts),
            return_exceptions=True,
        )
        # _poll_guarded swallows per-host errors, so a returned exception means
        # one escaped it (e.g. during row-writing); surface it per host rather
        # than letting return_exceptions discard it silently.
        for host, result in zip(self.hosts, results):
            if isinstance(result, BaseException):
                logger.error(
                    f"[{self.__class__.__name__}] {host} poll raised: {result}"
                )

    async def _poll_host(self, host: str) -> None:
        error = ""
        by_dev: Dict[int, Dict[int, str]] = {}
        try:
            client_ctx = await get_hrt_client(host)
            async with client_ctx as client:
                plane_status_entries = await client.getPlaneStatus()
            by_dev = build_plane_status_map(plane_status_entries, set(self.device_ids))
        except Exception as e:
            logger.error(f"[HrtPlaneStatusCollector] {host}: {e}")
            error = f"error: {e}"

        ts = _now_str()
        for device_id in self.device_ids:
            states = {
                int(plane): str(state)
                for plane, state in by_dev.get(device_id, {}).items()
            }
            row = HrtPlaneStatusRow(
                timestamp=ts,
                host=host,
                device_id=device_id,
                plane_states=states,
                valid=not error,
                notes=error,
            )
            self.rows.append(row)
            rendered = " ".join(f"{p}={states[p]}" for p in sorted(states)) or "-"
            if self._file is not None:
                self._file.write(
                    f"{ts:<30}  {host:<22}  {device_id:<7}  {rendered} {error}\n"
                )
                self._file.flush()
            self._write_json_row(
                {
                    "collector": "hrt_plane_status",
                    "timestamp": ts,
                    "host": host,
                    "device_id": device_id,
                    "plane_states": {str(p): s for p, s in states.items()},
                    "valid": not error,
                    "notes": error,
                }
            )

    def hosts_in_window(self, window_start: float, window_end: float) -> List[str]:
        """Distinct hosts present in the in-window rows (stable-sorted)."""
        seen: List[str] = []
        for r in self.get_rows_in_window(window_start, window_end):
            if r.host not in seen:
                seen.append(r.host)
        return sorted(seen)

    def _planes(self, expected_planes: Optional[List[int]]) -> List[int]:
        if expected_planes is not None:
            return sorted(expected_planes)
        return list(range(self.num_planes))

    def evaluate_all_up_window(
        self,
        window_start: float,
        window_end: float,
        expected_planes: Optional[List[int]] = None,
        last_sample_only: bool = False,
        skip_null_strict: bool = False,
        host: Optional[str] = None,
        device_ids: Optional[List[int]] = None,
        _single_tuple: bool = False,
    ) -> List[PlaneStatusResult]:
        """Every plane must be UP across the in-window samples.

        Strict (default): every in-window sample must be UP (latches the first
        non-UP state; byte-identical legacy behaviour).

        With ``last_sample_only=True`` (MODE A — disruptive coldboot/kill/reboot),
        only the LAST in-window sample must be UP; a bounded transient (e.g. an
        UNKNOWN latched mid-coldboot while HRT re-subscribes, then recovered) is
        tolerated. With ``skip_null_strict=True`` (MODE B — graceful), TOLERATE
        null/missing plane samples but require every NON-NULL sample (and the
        last non-null) to be UP. ``"UP"`` is the golden value; any other state
        (UNKNOWN/DOWN/...) is a failure; a missing plane state is a null sample.
        ``host`` (when given) restricts evaluation to that host's rows.
        """
        if not _single_tuple:
            results: List[PlaneStatusResult] = []
            selected_hosts = [host] if host is not None else self.hosts
            selected_devices = device_ids or self.device_ids
            saved_rows = self.rows
            try:
                for selected_host in sorted(selected_hosts):
                    for device_id in sorted(selected_devices):
                        self.rows = [
                            row
                            for row in saved_rows
                            if row.host == selected_host and row.device_id == device_id
                        ]
                        tuple_results = self.evaluate_all_up_window(
                            window_start=window_start,
                            window_end=window_end,
                            expected_planes=expected_planes,
                            last_sample_only=last_sample_only,
                            skip_null_strict=skip_null_strict,
                            host=selected_host,
                            _single_tuple=True,
                        )
                        for result in tuple_results:
                            result.host = selected_host
                            result.device_id = device_id
                        results.extend(tuple_results)
                return results
            finally:
                self.rows = saved_rows

        windowed = self.get_rows_in_window(window_start, window_end)
        if host is not None:
            windowed = [r for r in windowed if r.host == host]
        result_host = host if host is not None else _single_host(self.hosts)
        results: List[PlaneStatusResult] = []
        for plane in self._planes(expected_planes):
            samples = 0
            bad_state: Optional[str] = None
            bad_ts: Optional[str] = None
            last_state = "MISSING"
            series: List[Optional[str]] = []
            non_up_count = 0
            for r in windowed:
                samples += 1
                st = r.plane_states.get(plane)
                last_state = st if st is not None else "MISSING"
                series.append(st)
                if st != "UP":
                    non_up_count += 1
                if st != "UP" and bad_state is None:
                    bad_state = last_state
                    bad_ts = r.timestamp

            if last_sample_only or skip_null_strict:
                mode = (
                    BLIP_MODE_LAST_SAMPLE
                    if last_sample_only
                    else BLIP_MODE_SKIP_NULL_STRICT
                )
                passed, blip_detail = evaluate_blip_series(series, "UP", mode)
                if samples == 0:
                    detail = "no in-window samples"
                elif passed:
                    detail = (
                        f"[{mode}] {blip_detail} (tolerated transient non-UP in "
                        f"{non_up_count}/{samples} samples, last={last_state})"
                    )
                else:
                    detail = f"[{mode}] {blip_detail} (last={last_state})"
            else:
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
                    host=result_host,
                    device_id=self.rows[0].device_id if self.rows else 0,
                )
            )
        return results

    def evaluate_drain_window(
        self,
        window_start: float,
        window_end: float,
        impacted_planes: List[int],
        expected_planes: Optional[List[int]] = None,
        host: Optional[str] = None,
        device_ids: Optional[List[int]] = None,
        impacted_tuples_by_device: Optional[Dict[str, List[int]]] = None,
        _single_tuple: bool = False,
    ) -> List[PlaneStatusResult]:
        """Impacted plane(s) DRAINED by window end; all other planes stay UP.

        The window MUST start at the recorded disruption time so the impacted
        plane's pre-drain UP samples are excluded (a drain takes a few seconds to
        reflect). An impacted plane PASSES iff its last in-window sample is
        DRAINED; a non-impacted plane PASSES iff it is UP in every sample.
        ``host`` (when given) restricts evaluation to that host's rows.
        """
        if not _single_tuple:
            results: List[PlaneStatusResult] = []
            selected_hosts = [host] if host is not None else self.hosts
            selected_devices = device_ids or self.device_ids
            saved_rows = self.rows
            try:
                for selected_host in sorted(selected_hosts):
                    for device_id in sorted(selected_devices):
                        local_impacted = (
                            impacted_tuples_by_device.get(str(device_id), [])
                            if impacted_tuples_by_device is not None
                            else impacted_planes
                        )
                        self.rows = [
                            row
                            for row in saved_rows
                            if row.host == selected_host and row.device_id == device_id
                        ]
                        tuple_results = self.evaluate_drain_window(
                            window_start=window_start,
                            window_end=window_end,
                            impacted_planes=local_impacted,
                            expected_planes=expected_planes,
                            host=selected_host,
                            _single_tuple=True,
                        )
                        for result in tuple_results:
                            result.host = selected_host
                            result.device_id = device_id
                        results.extend(tuple_results)
                return results
            finally:
                self.rows = saved_rows

        impacted = {int(p) for p in impacted_planes}
        windowed = self.get_rows_in_window(window_start, window_end)
        if host is not None:
            windowed = [r for r in windowed if r.host == host]
        result_host = host if host is not None else _single_host(self.hosts)
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
                        host=result_host,
                        device_id=self.rows[0].device_id if self.rows else 0,
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
                        host=result_host,
                        device_id=self.rows[0].device_id if self.rows else 0,
                    )
                )
        return results


# ---------------------------------------------------------------------------
# HRT FSDB-Session-Count Collector (per-host CONNECTED session census)
# ---------------------------------------------------------------------------


def _session_is_connected(session: Any) -> bool:
    return str(getattr(session, "state", None)) == "CONNECTED"


def _session_tuple_key(device_id: int, local_plane: int) -> str:
    return f"dev{device_id}/L{local_plane}"


@dataclass
class HrtFsdbSessionRow:
    """One poll of ``getFsdbSessions()`` on a single GPU host.

    Each HRT FSDB session is keyed by (device_id, local plane_id). A
    session is CONNECTED or not. ``connected`` is the total CONNECTED count
    across all (gpu, lane); ``expected`` is the full census size (default
    32). ``tuple_connected`` / ``tuple_total`` retain exact identity. The
    legacy ``lane_connected`` / ``lane_total`` aggregation remains for RTP
    callers that still use the four-device/eight-plane model. ``error``
    (non-empty) marks a poll where the HRT query failed — treated as null data
    by the evaluator (not counted as a real 0).
    """

    timestamp: str
    host: str
    connected: int
    expected: int
    lane_connected: Dict[int, int] = field(default_factory=dict)
    lane_total: Dict[int, int] = field(default_factory=dict)
    tuple_connected: Dict[str, int] = field(default_factory=dict)
    tuple_total: Dict[str, int] = field(default_factory=dict)
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
    per_tuple_min: Dict[str, int] = field(default_factory=dict)
    impacted_tuple_churn: Dict[str, bool] = field(default_factory=dict)
    detail: str = ""


class HrtFsdbSessionCollector(BaseCollector):
    """Polls HRT ``getFsdbSessions()`` for one GPU host, recording the CONNECTED
    session census per poll.

    Programmatic equivalent of counting CONNECTED HRT FSDB sessions: each poll
    captures the total CONNECTED count, the expected census size (default 32 =
    32), and exact device/local-plane counts. A drain/kill of global lane 0 on
    all 4 GPUs in the paired-device model affects dev0/dev2/dev4/dev6 local L0
    and drops the overall count to 28. The ``evaluate_window``
    helper returns a structured verdict the FpfHrtSessionStatHealthCheck
    interprets for both the disruption (drop-then-recover) and stable (no churn)
    contracts.

    ONE collector instance holds ALL monitored hosts (``hosts``): each poll
    loops the hosts and each row carries its ``host``; a single file with a host
    column. A poll whose HRT query fails on a host records an error row (null
    data) for that host rather than a misleading all-zero census.
    """

    def __init__(
        self,
        hosts: List[str],
        expected_connected: int = 32,
        tmp_path: str = "/tmp/fpf_stress_hrt_fsdb_session.log",
        interval_sec: float = 3.0,
    ) -> None:
        super().__init__(tmp_path, interval_sec)
        self.hosts = hosts
        self.expected_connected = expected_connected
        self.rows: List[HrtFsdbSessionRow] = []

    def _write_header(self, f) -> None:
        f.write(
            f"{'timestamp':<30}  {'host':<22}  {'connected':>9}  {'expected':>8}  "
            f"per_lane (lane=conn/total ...)\n"
        )

    async def _poll_once(self) -> None:
        # Poll all hosts concurrently so a slow/hung host never serializes behind
        # (or stalls) its siblings. Each host is capped by its OWN timeout: a
        # single hung host records only its own per-host NULL (via
        # _record_host_timeout) instead of tripping the base _run_loop's
        # whole-cycle wait_for and marking every host FAIL. The per-host budget
        # is kept just under POLL_TIMEOUT_SEC so the outer backstop fires only
        # when the entire cycle genuinely stalls.
        host_timeout = max(1.0, self.POLL_TIMEOUT_SEC - 10.0)

        async def _poll_guarded(host: str) -> None:
            try:
                await asyncio.wait_for(self._poll_host(host), timeout=host_timeout)
            except asyncio.TimeoutError:
                self._record_host_timeout(host, host_timeout)

        results = await asyncio.gather(
            *(_poll_guarded(host) for host in self.hosts),
            return_exceptions=True,
        )
        # _poll_guarded swallows per-host errors, so a returned exception means
        # one escaped it (e.g. during row-writing); surface it per host rather
        # than letting return_exceptions discard it silently.
        for host, result in zip(self.hosts, results):
            if isinstance(result, BaseException):
                logger.error(
                    f"[{self.__class__.__name__}] {host} poll raised: {result}"
                )

    async def _poll_host(self, host: str) -> None:
        error = ""
        # `client.getFsdbSessions()` returns a Sequence (from generated thrift),
        # so we annotate as Sequence rather than List to avoid invariance issues.
        sessions: Sequence[Any] = []
        try:
            client_ctx = await get_hrt_client(host)
            async with client_ctx as client:
                sessions = await client.getFsdbSessions()
        except Exception as e:
            logger.error(f"[HrtFsdbSessionCollector] {host}: {e}")
            error = f"error: {e}"

        lane_connected: Dict[int, int] = {}
        lane_total: Dict[int, int] = {}
        tuple_connected: Dict[str, int] = {}
        tuple_total: Dict[str, int] = {}
        connected = 0
        if not error:
            for s in sessions:
                device_id = getattr(s, "device_id", None)
                lane = getattr(s, "plane_id", None)
                if not isinstance(device_id, int) or not isinstance(lane, int):
                    continue
                key = _session_tuple_key(device_id, lane)
                lane_total[lane] = lane_total.get(lane, 0) + 1
                tuple_total[key] = tuple_total.get(key, 0) + 1
                if _session_is_connected(s):
                    connected += 1
                    lane_connected[lane] = lane_connected.get(lane, 0) + 1
                    tuple_connected[key] = tuple_connected.get(key, 0) + 1
                else:
                    lane_connected.setdefault(lane, 0)
                    tuple_connected.setdefault(key, 0)

        ts = _now_str()
        row = HrtFsdbSessionRow(
            timestamp=ts,
            host=host,
            connected=connected,
            expected=self.expected_connected,
            lane_connected=lane_connected,
            lane_total=lane_total,
            tuple_connected=tuple_connected,
            tuple_total=tuple_total,
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
                f"{ts:<30}  {host:<22}  {connected:>9}  "
                f"{self.expected_connected:>8}  {rendered}\n"
            )
            self._file.flush()
        self._write_json_row(
            {
                "collector": "hrt_fsdb_session",
                "timestamp": ts,
                "host": host,
                "connected": connected,
                "expected": self.expected_connected,
                "lane_connected": {str(k): v for k, v in lane_connected.items()},
                "lane_total": {str(k): v for k, v in lane_total.items()},
                "tuple_connected": tuple_connected,
                "tuple_total": tuple_total,
                "error": error,
            }
        )

    def hosts_in_window(self, window_start: float, window_end: float) -> List[str]:
        """Distinct hosts present in the in-window rows (stable-sorted)."""
        seen: List[str] = []
        for r in self.get_rows_in_window(window_start, window_end):
            if r.host not in seen:
                seen.append(r.host)
        return sorted(seen)

    def evaluate_window(
        self,
        window_start: float,
        window_end: float,
        expected_connected: Optional[int] = None,
        impacted_lanes: Optional[List[int]] = None,
        impacted_tuples_by_device: Optional[Dict[str, List[int]]] = None,
        host: Optional[str] = None,
    ) -> FsdbSessionWindowResult:
        """Summarize the CONNECTED census over [window_start, window_end].

        ``expected_connected`` defaults to the collector's configured census
        size. ``impacted_lanes`` (when given) are the lanes a disruption is
        expected to churn; the result records, per impacted lane, whether its
        connected count was observed to drop below its total. Errored/null polls
        are excluded from the count statistics but counted in ``error_samples``.
        ``host`` (when given) restricts evaluation to that host's rows — the
        collector holds all hosts, so a caller iterates hosts and filters here.
        """
        expected = (
            expected_connected
            if expected_connected is not None
            else self.expected_connected
        )
        impacted = [int(x) for x in (impacted_lanes or [])]
        impacted_tuples = {
            _session_tuple_key(int(device_id), int(local_plane))
            for device_id, local_planes in (impacted_tuples_by_device or {}).items()
            for local_plane in local_planes
        }
        windowed = self.get_rows_in_window(window_start, window_end)
        if host is not None:
            windowed = [r for r in windowed if r.host == host]
        result_host = host if host is not None else _single_host(self.hosts)

        good = [r for r in windowed if not r.error]
        error_samples = sum(1 for r in windowed if r.error)

        if not good:
            return FsdbSessionWindowResult(
                host=result_host,
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
        per_tuple_min: Dict[str, int] = {}
        for r in good:
            for lane, conn in r.lane_connected.items():
                if lane not in per_lane_min or conn < per_lane_min[lane]:
                    per_lane_min[lane] = conn
            for key, conn in r.tuple_connected.items():
                if key not in per_tuple_min or conn < per_tuple_min[key]:
                    per_tuple_min[key] = conn

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

        impacted_tuple_churn: Dict[str, bool] = {}
        for key in sorted(impacted_tuples):
            impacted_tuple_churn[key] = any(
                r.tuple_connected.get(key) is not None
                and r.tuple_total.get(key) is not None
                and r.tuple_connected[key] < r.tuple_total[key]
                for r in good
            )

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
        if impacted_tuples:
            detail += " | impacted-tuple churn: " + ", ".join(
                f"{key}={'yes' if impacted_tuple_churn[key] else 'no'}"
                for key in sorted(impacted_tuples)
            )

        return FsdbSessionWindowResult(
            host=result_host,
            samples=len(good),
            error_samples=error_samples,
            min_connected=min_connected,
            max_connected=max_connected,
            last_connected=last_connected,
            reached_expected=reached_expected,
            per_lane_min=per_lane_min,
            impacted_lane_churn=impacted_lane_churn,
            per_tuple_min=per_tuple_min,
            impacted_tuple_churn=impacted_tuple_churn,
            detail=detail,
        )

    def evaluate_recovery_hold(
        self,
        window_start: float,
        window_end: float,
        expected_connected: Optional[int] = None,
        recovery_min_sec: float = 60.0,
        host: Optional[str] = None,
    ) -> Tuple[bool, Optional[float], str]:
        """Did the CONNECTED census recover to ``expected_connected`` and hold
        there for >= ``recovery_min_sec`` continuously up to window end?

        Walks the non-null in-window samples; finds the last contiguous tail run
        of samples at ``expected``. Returns (passed, held_sec, detail). ``passed``
        is True iff the tail run reaches window end and spans >= recovery_min_sec
        (a tail that is at expected but shorter than the floor fails; a census
        that drops below expected after recovering also fails). With < 2 samples
        the duration cannot be measured -> not passed. ``host`` (when given)
        restricts evaluation to that host's rows.
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
            if host is None or r.host == host
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
