# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Module-level registry for long-lived FPF collectors and shared
3-signal convergence evaluation.

Two responsibilities:

1. **Registry** — stores collector instances + test case start time so health
   checks can query time-windowed convergence data without needing access to
   shared_task_data or the TaacRunner. Populated by
   FpfStartCollectorsTask and cleared by FpfStopCollectorsTask.

2. **3-signal evaluation** — ``evaluate_three_signals()`` is a shared function
   used by the FSDB-ribMap, BGP-RIB, and HRT-bulk convergence health checks.
   It decorates a basic ``PerLaneResult`` with three independent signal
   evaluations, and only marks the result as passed when all three pass.

   Signal 1 — End-to-end convergence (default ≤ 180s):
       window_start (≈ test case start) → first sample reaching ``expected``.
       Bounds the total user-visible time for "trigger fires → system done".

   Signal 2 — Local / GTSW-GPU propagation (default ≤ 120s):
       T1 (first non-zero sample) → T2 (first sample reaching ``expected``).
       Excludes the stimulus push duration (e.g., addNetworks() time) so it
       reports how fast the data plane actually catches up once it has work
       to do.

   Signal 3 — Post-convergence stability (default 60s, no drops):
       Beginning at T2, every subsequent sample within
       ``stability_duration_sec`` must show ``>= expected``. Catches churn,
       flap, or premature withdrawal.

   Health check defaults can be overridden per call via ``check_params``.
"""

import asyncio
import time
import typing as t

# The registry state + register/get/clear/test_case_start_time helpers were
# extracted to ``taac.libs.collectors.registry`` so OSS test configs can
# consume them without importing this file's FPF-specific dependencies.
# Re-exported here for backward compatibility (including ``_collectors``,
# which was this module's own global before the extraction and is safe to
# re-export by identity since ``clear()`` mutates in place); ``clear_all()``
# below still owns clearing FPF-specific state (artifacts, disruption gate,
# baseline lanes) in addition to delegating to ``clear_collectors()``.
from taac.libs.collectors.registry import (  # noqa: F401
    _collectors,
    clear_collectors as _clear_collectors,
    get_all_collectors,
    get_collector,
    get_test_case_start_time,
    register_collector,
    set_test_case_start_time,
)
from taac.libs.fpf.fpf_stress_checks import (
    _parse_ts,
    BLIP_MODE_LAST_SAMPLE,
    BLIP_MODE_SKIP_NULL_STRICT,
    BLIP_MODE_STRICT,
    evaluate_blip_series,
    PerLaneResult,
)

# Debug artifacts (category, label, url) generated during a test case — collector
# detail Everpastes and ODS query links — accumulated so a consolidated summary
# table can be emitted at teardown for easy access. Cleared by clear_all().
_artifacts: t.List[t.Tuple[str, str, str]] = []

# --- Disruption-effectiveness gate (#1) -----------------------------------
# Set by the fpf_verify_disruption custom step after the disable/drain: whether
# the targeted interface(s) actually changed state (admin DISABLED / oper DOWN).
# None = not verified; True/False = verified effective/ineffective. Downstream
# lane checks consult this and SKIP (inconclusive) rather than FAIL when the
# disruption never took effect, so one clear signal replaces N confusing ones.
_disruption_effective: t.Optional[bool] = None
_disruption_effective_detail: str = ""

# --- Baseline-impaired lanes (#2) -----------------------------------------
# host -> set(lane) that were ALREADY impaired at precheck (e.g. a degraded lab
# lane like gtsw003/plane2). Recorded by the FSDB-session precheck. When a test
# config sets allow_baseline_failures, postcheck lane assertions exclude these
# lanes (a failure there is PRE-EXISTING, not a test regression).
_baseline_impaired_lanes: t.Dict[str, t.Set[int]] = {}
_baseline_impaired_tuples: t.Dict[str, t.Set[t.Tuple[int, int]]] = {}
_allow_baseline_failures: bool = False

# Drain cleanup ownership. A token is armed only immediately before this test
# invokes the local drainer, after its read-only clean-state precondition has
# passed. Cleanup must present the same token, target device, and interface
# scope so it cannot clear unrelated ambient drain state.
_drain_mutations: t.Dict[str, t.Tuple[str, t.Tuple[str, ...]]] = {}


def set_disruption_effective(effective: bool, detail: str = "") -> None:
    global _disruption_effective, _disruption_effective_detail
    _disruption_effective = effective
    _disruption_effective_detail = detail


def get_disruption_effective() -> t.Tuple[t.Optional[bool], str]:
    return _disruption_effective, _disruption_effective_detail


def disruption_inconclusive_skip() -> t.Optional[str]:
    """If a disruption was explicitly verified INEFFECTIVE this playbook, return a
    human-readable skip reason for disrupt-asserting checks to surface as SKIP
    (inconclusive) instead of FAIL. None when effective or not verified."""
    if _disruption_effective is False:
        return (
            f"INCONCLUSIVE — disruption did not take effect "
            f"({_disruption_effective_detail}); the targeted link never went down, "
            f"so this disrupted-state assertion cannot be evaluated"
        )
    return None


def set_baseline_impaired_lanes(host_to_lanes: t.Dict[str, t.Set[int]]) -> None:
    global _baseline_impaired_lanes
    _baseline_impaired_lanes = {h: set(v) for h, v in host_to_lanes.items()}


def get_baseline_impaired_lanes() -> t.Dict[str, t.Set[int]]:
    return {h: set(v) for h, v in _baseline_impaired_lanes.items()}


def set_baseline_impaired_tuples(
    host_to_tuples: t.Dict[str, t.Set[t.Tuple[int, int]]],
) -> None:
    """Record exact ``(device_id, local_plane)`` baseline impairments."""
    global _baseline_impaired_tuples
    _baseline_impaired_tuples = {h: set(v) for h, v in host_to_tuples.items()}


def get_baseline_impaired_tuples() -> t.Dict[str, t.Set[t.Tuple[int, int]]]:
    return {h: set(v) for h, v in _baseline_impaired_tuples.items()}


def baseline_impaired_lane_union() -> t.Set[int]:
    """All lanes impaired at baseline on any host (host-agnostic view)."""
    out: t.Set[int] = set()
    for lanes in _baseline_impaired_lanes.values():
        out |= lanes
    return out


def set_allow_baseline_failures(allow: bool) -> None:
    global _allow_baseline_failures
    _allow_baseline_failures = allow


def get_allow_baseline_failures() -> bool:
    return _allow_baseline_failures


def mark_drain_mutation(
    token: str,
    device: str,
    interfaces: t.Iterable[str],
) -> None:
    _drain_mutations[token] = (device, tuple(sorted(interfaces)))


def get_drain_mutation(
    token: str,
) -> t.Optional[t.Tuple[str, t.Tuple[str, ...]]]:
    return _drain_mutations.get(token)


def clear_drain_mutation(token: str) -> None:
    _drain_mutations.pop(token, None)


def clear_drain_mutations() -> None:
    _drain_mutations.clear()


def register_artifact(category: str, label: str, url: str) -> None:
    """Record a debug artifact link (category e.g. 'collector'/'ods', a label,
    and the URL) for the consolidated end-of-test artifacts summary."""
    if url:
        _artifacts.append((category, label, url))


def get_artifacts() -> t.List[t.Tuple[str, str, str]]:
    return list(_artifacts)


# Per-check results (name, status, reason, classification) recorded by the FPF
# checks for the consolidated FAILURE TRIAGE table at teardown. classification:
# OK / NEW (regression) / PRE-EXISTING (baseline) / INCONCLUSIVE (disruption
# didn't take). Cleared by clear_all().
_check_results: t.List[t.Tuple[str, str, str, str]] = []


def register_check_result(
    name: str, status: str, reason: str = "", classification: str = ""
) -> None:
    """Record a check's verdict for the teardown FAILURE TRIAGE table. If
    classification is omitted it is inferred from status/reason."""
    if not classification:
        r = reason.lower()
        if status == "PASS":
            classification = "OK"
        elif "inconclusive" in r:
            classification = "INCONCLUSIVE"
        elif "pre-existing" in r or "baseline" in r:
            classification = "PRE-EXISTING"
        elif status == "SKIP":
            classification = "SKIP"
        else:
            classification = "NEW"
    _check_results.append((name, status, reason, classification))


def get_check_results() -> t.List[t.Tuple[str, str, str, str]]:
    return list(_check_results)


# Wall-clock epoch of the disruptive action (interface flap / link drain),
# recorded at runtime by the record_fpf_disruption_time custom step. 0.0 means
# "not recorded"; link-event transition checks then fall back to a
# disruption-relative heuristic. Distinct from test_case_start_time, which is
# set at the START of the playbook (before inject + stabilization).
_disruption_time: float = 0.0

# Wall-clock epoch of a recovery/restart action. This is intentionally separate
# from ``_disruption_time``: GR-beyond tests use the latter to retain the full
# service-down observation window while affected-rib recovery SLAs start here.
_restart_time: float = 0.0

# Wall-clock epoch immediately after a restart command completes. HRT restart
# recovery uses this to exclude a healthy collector sample that races between
# the pre-command marker and the actual service outage.
_restart_completion_time: float = 0.0

# Wall-clock epochs bracketing a link/device recovery action. These are kept
# separate from ``_disruption_time`` because a disrupt playbook's finally
# cleanup may perform the real undrain before the following restore playbook
# starts. The restore health check must measure from that cleanup action rather
# than from the earlier drain.
_recovery_start_time: float = 0.0
_recovery_completion_time: float = 0.0

# Signal 1: end-to-end convergence ceiling. Includes any stimulus push
# duration. 180s allows ~110s for 10k-prefix injection + ~70s propagation.
DEFAULT_SIGNAL1_E2E_MAX_SEC: float = 180.0

# Signal 2: local propagation ceiling. Measures pure data-plane catch-up.
DEFAULT_SIGNAL2_LOCAL_MAX_SEC: float = 120.0

# Signal 3: required post-convergence stability duration. The signal must
# remain >= expected continuously across this window after first reaching it.
DEFAULT_SIGNAL3_STABILITY_DURATION_SEC: float = 60.0

# Fraction of stability_duration that is acceptable when the window ends
# before the full duration elapses (gives partial credit so tests don't fail
# purely because their soak window is short relative to the stability check).
DEFAULT_STABILITY_PARTIAL_CREDIT_FRACTION: float = 0.8


async def everpaste_details_suffix(
    title: str,
    lines: t.List[str],
    collectors: t.Optional[t.List[t.Any]] = None,
    window_start: t.Optional[float] = None,
    window_end: t.Optional[float] = None,
    result_status: t.Optional[str] = None,
    result_reason: str = "",
) -> str:
    """Upload ``lines`` (plus, when ``collectors`` + window are given, each
    collector's human-readable poll table for [window_start, window_end]) to
    Everpaste and return a ``"  |  Details: <url>"`` suffix to append to a
    collector-based health-check message.

    The per-poll table is the key debugging aid: it shows the actual counts the
    collector observed over the test-case window, so a failure is explainable
    from the link alone (no log spelunking). Returns "" on empty input or on any
    everpaste/fburl failure — a cosmetic link must never turn a check into an
    error.
    """
    if not lines and not collectors:
        return ""
    from taac.utils.common import (
        async_everpaste_str,
        async_get_fburl_retry,
    )

    body_lines = list(lines)
    if collectors and window_start is not None and window_end is not None:
        for c in collectors:
            if c is None or not hasattr(c, "format_window_table"):
                continue
            label = getattr(c, "host", None) or type(c).__name__
            body_lines += [
                "",
                f"=== collector poll table [{label}] (test-case window) ===",
                c.format_window_table(window_start, window_end),
            ]
    body = title + "\n" + "\n".join(body_lines)
    try:
        url = await async_everpaste_str(body, color=1)
        url = await async_get_fburl_retry(url)
        register_artifact("collector", title, url)
        if result_status is not None:
            register_check_result(title, result_status, result_reason)
        return f"  |  Details: {url}"
    except Exception:
        return ""


def set_disruption_time(ts: float) -> None:
    global _disruption_time
    _disruption_time = ts


def get_disruption_time() -> float:
    return _disruption_time


def set_restart_time(ts: float) -> None:
    global _restart_time
    _restart_time = ts


def get_restart_time() -> float:
    return _restart_time


def set_restart_completion_time(ts: float) -> None:
    global _restart_completion_time
    _restart_completion_time = ts


def get_restart_completion_time() -> float:
    return _restart_completion_time


def set_recovery_start_time(ts: float) -> None:
    global _recovery_start_time, _recovery_completion_time
    _recovery_start_time = ts
    # A new recovery attempt invalidates completion from any earlier attempt.
    _recovery_completion_time = 0.0


def get_recovery_start_time() -> float:
    return _recovery_start_time


def set_recovery_completion_time(ts: float) -> None:
    global _recovery_completion_time
    _recovery_completion_time = ts


def get_recovery_completion_time() -> float:
    return _recovery_completion_time


def validate_restart_tolerant_tuple(
    rows: t.Iterable[t.Any],
    host: str,
    device_id: int,
    lane: int,
    expected: int,
    restart_ts: float,
    restart_completion_ts: t.Optional[float] = None,
) -> t.Tuple[bool, str]:
    """Validate one HRT tuple after an intentional host restart.

    Error/null rows are tolerated for the restarted host, but every valid row
    must retain the exact expected count. At least one valid row must also be
    published after the restart command completes or, if later, after the last
    observed outage row. This prevents a healthy sample racing just after the
    pre-command marker from being mistaken for recovery.
    """
    valid: t.List[t.Tuple[float, int]] = []
    last_outage_ts: t.Optional[float] = None
    for row in rows:
        if getattr(row, "host", None) != host:
            continue
        if int(getattr(row, "device_id", 0)) != device_id:
            continue
        try:
            row_ts = _parse_ts(row.timestamp).timestamp()
        except (ValueError, AttributeError):
            continue
        if row_ts <= restart_ts:
            continue
        counts = getattr(row, "lane_counts", [])
        is_error = (
            not getattr(row, "valid", True)
            or str(getattr(row, "notes", "") or "").startswith("error:")
            or lane >= len(counts)
        )
        if is_error:
            last_outage_ts = row_ts
            continue
        valid.append((row_ts, int(counts[lane])))

    dirty = [(ts, count) for ts, count in valid if count != expected]
    if dirty:
        ts, count = dirty[0]
        return (
            False,
            f"valid sample {count} != {expected} at {ts:.3f} after restart",
        )

    eligibility_ts = max(
        restart_ts,
        restart_completion_ts or restart_ts,
        last_outage_ts or restart_ts,
    )
    eligible_valid = [(ts, count) for ts, count in valid if ts > eligibility_ts]
    if not eligible_valid:
        return (
            False,
            "no valid recovery sample after restart/outage eligibility "
            f"{eligibility_ts:.3f}",
        )
    return (
        True,
        f"recovered at {eligible_valid[0][0]:.3f} after eligibility "
        f"{eligibility_ts:.3f}; final={eligible_valid[-1][1]}",
    )


def clear_all() -> None:
    global _disruption_time, _restart_time, _restart_completion_time
    global _recovery_start_time, _recovery_completion_time
    global _disruption_effective, _disruption_effective_detail
    global _baseline_impaired_lanes, _baseline_impaired_tuples
    global _allow_baseline_failures
    # Shared registry state (collectors dict + test-case start time) lives in
    # taac.libs.collectors.registry — delegate its reset there.
    _clear_collectors()
    _artifacts.clear()
    _check_results.clear()
    _disruption_time = 0.0
    _restart_time = 0.0
    _restart_completion_time = 0.0
    _recovery_start_time = 0.0
    _recovery_completion_time = 0.0
    _disruption_effective = None
    _disruption_effective_detail = ""
    _baseline_impaired_lanes = {}
    _baseline_impaired_tuples = {}
    _allow_baseline_failures = False
    clear_drain_mutations()


def _row_matches_device(row: t.Any, device: str) -> bool:
    # Per-lane HRT rows (HrtBulkRow / HrtRemoteFailureRow) carry `lane_counts`
    # and are discriminated by lane via `_row_value(lane_id=...)`, not by the
    # caller's `device` string (which for these checks is the pseudo-label
    # "HRT L{lane}", never a hostname). Match them unconditionally so the
    # 3-signal evaluation sees the same per-lane samples as evaluate_per_lane.
    if hasattr(row, "lane_counts"):
        return True
    # FSDB/BGP rows: match by `gtsw` (their device IS the GTSW hostname).
    if hasattr(row, "gtsw"):
        return row.gtsw == device
    if hasattr(row, "host"):
        return row.host == device
    return True


def _row_value(
    row: t.Any, lane_id: t.Optional[int], match_field: str
) -> t.Optional[int]:
    if not getattr(row, "valid", True) or str(getattr(row, "notes", "")).startswith(
        "error:"
    ):
        return None
    if lane_id is not None and hasattr(row, "lane_counts"):
        lc = row.lane_counts
        return lc[lane_id] if lane_id < len(lc) else None
    if hasattr(row, "lane_counts") and lane_id is None:
        return None
    return getattr(row, match_field, None)


def _collect_sorted_samples(
    rows: t.Iterable[t.Any],
    device: str,
    lane_id: t.Optional[int],
    match_field: str,
    host: t.Optional[str] = None,
    device_id: t.Optional[int] = None,
) -> t.List[t.Tuple[float, int]]:
    """Filter rows for device, parse timestamps, sort chronologically."""
    samples: t.List[t.Tuple[float, int]] = []
    for row in rows:
        if host is not None and getattr(row, "host", None) != host:
            continue
        if device_id is not None and getattr(row, "device_id", None) != device_id:
            continue
        if not _row_matches_device(row, device):
            continue
        val = _row_value(row, lane_id, match_field)
        if val is None:
            continue
        try:
            row_ts = _parse_ts(row.timestamp).timestamp()
        except (ValueError, AttributeError):
            continue
        samples.append((row_ts, val))
    samples.sort(key=lambda x: x[0])
    return samples


def _find_t1_t2(
    samples: t.List[t.Tuple[float, int]], expected: int
) -> t.Tuple[t.Optional[float], t.Optional[float]]:
    """T1 = first sample > 0. T2 = first sample >= expected."""
    t1: t.Optional[float] = None
    t2: t.Optional[float] = None
    for ts, val in samples:
        if t1 is None and val > 0:
            t1 = ts
        if t2 is None and val >= expected:
            t2 = ts
        if t1 is not None and t2 is not None:
            break
    return t1, t2


def _eval_signal1_e2e(
    result: PerLaneResult,
    t2: t.Optional[float],
    window_start: float,
    expected: int,
    max_sec: float,
) -> None:
    result.signal1_e2e_threshold_sec = max_sec
    if t2 is None:
        result.signal1_e2e_ok = False
        result.signal1_e2e_sec = None
        result.signal1_e2e_detail = (
            f"FAIL — never reached {expected} (last seen: {result.actual})"
        )
        return
    sec = round(t2 - window_start, 1)
    result.signal1_e2e_sec = sec
    result.signal1_e2e_ok = sec <= max_sec
    verb = "reached" if result.signal1_e2e_ok else "took"
    result.signal1_e2e_detail = f"{verb} {expected} in {sec}s (limit: ≤{max_sec:.0f}s)"


def _eval_signal2_local(
    result: PerLaneResult,
    t1: t.Optional[float],
    t2: t.Optional[float],
    window_start: float,
    expected: int,
    max_sec: float,
) -> None:
    result.signal2_local_threshold_sec = max_sec
    if t1 is None:
        result.signal2_local_ok = False
        result.signal2_local_sec = None
        result.signal2_local_detail = (
            "FAIL — no T1 transition observed (signal stayed at 0 throughout window)"
        )
        return
    if t2 is None:
        result.signal2_local_ok = False
        result.signal2_local_sec = None
        result.signal2_t1_sec_from_start = round(t1 - window_start, 1)
        result.signal2_local_detail = (
            f"FAIL — T1 observed at +{result.signal2_t1_sec_from_start}s "
            f"but T2 (>= {expected}) never reached"
        )
        return
    sec = round(t2 - t1, 1)
    result.signal2_local_sec = sec
    result.signal2_t1_sec_from_start = round(t1 - window_start, 1)
    result.signal2_t2_sec_from_start = round(t2 - window_start, 1)
    result.signal2_local_ok = sec <= max_sec
    result.signal2_local_detail = (
        f"T2-T1 = {sec}s "
        f"(T1=+{result.signal2_t1_sec_from_start}s, "
        f"T2=+{result.signal2_t2_sec_from_start}s) "
        f"(limit: ≤{max_sec:.0f}s)"
    )


def _eval_signal3_stability(
    result: PerLaneResult,
    t2: t.Optional[float],
    samples: t.List[t.Tuple[float, int]],
    window_end: float,
    expected: int,
    duration_sec: float,
    stability_mode: str = BLIP_MODE_STRICT,
) -> None:
    result.signal3_stability_duration_sec = duration_sec
    if t2 is None:
        result.signal3_stability_ok = False
        result.signal3_stability_detail = (
            "SKIP — threshold never reached, stability not assessed"
        )
        return
    # MODE A ("last_sample") / MODE B ("skip_null_strict"): the post-convergence
    # count legitimately blips during a disruptive (kill/coldboot/reboot/GR-beyond)
    # or graceful within-window (GR / GR-in) trigger. Delegate to the shared
    # blip-handling helper on the post-T2 value series rather than the strict
    # "no drops" rule. Null/missing samples are already excluded from ``samples``
    # by ``_collect_sorted_samples`` (so tolerated for skip_null_strict).
    if stability_mode in (BLIP_MODE_LAST_SAMPLE, BLIP_MODE_SKIP_NULL_STRICT):
        stability_end = t2 + duration_sec
        post_t2 = [v for ts, v in samples if t2 <= ts <= stability_end]
        passed, detail = evaluate_blip_series(post_t2, expected, stability_mode)
        result.signal3_stability_ok = passed
        result.signal3_stability_detail = (
            f"[{stability_mode}] {detail}"
            if passed
            else f"FAIL — [{stability_mode}] {detail}"
        )
        return
    stability_end = t2 + duration_sec
    post_t2 = [(ts, v) for ts, v in samples if t2 <= ts <= stability_end]
    drops = [(ts, v) for ts, v in post_t2 if v < expected]
    available = min(window_end, stability_end) - t2
    partial_min = duration_sec * DEFAULT_STABILITY_PARTIAL_CREDIT_FRACTION
    if drops:
        first_drop_offset = round(drops[0][0] - t2, 1)
        result.signal3_stability_ok = False
        result.signal3_stability_detail = (
            f"FAIL — {len(drops)} drop(s) below {expected} within "
            f"{duration_sec:.0f}s of T2 "
            f"(first drop: {drops[0][1]} at T2+{first_drop_offset}s)"
        )
        return
    if available >= duration_sec:
        result.signal3_stability_ok = True
        result.signal3_stability_detail = (
            f"held at >= {expected} for {duration_sec:.0f}s "
            f"after T2 (no drops, {len(post_t2)} samples)"
        )
        return
    if available >= partial_min:
        result.signal3_stability_ok = True
        result.signal3_stability_detail = (
            f"held at >= {expected} for {available:.1f}s after T2 "
            f"(partial credit: window ended before full "
            f"{duration_sec:.0f}s, {len(post_t2)} samples)"
        )
        return
    result.signal3_stability_ok = False
    result.signal3_stability_detail = (
        f"FAIL — only {available:.1f}s of post-T2 data "
        f"(need >= {partial_min:.1f}s; "
        f"required {duration_sec:.0f}s with "
        f"{DEFAULT_STABILITY_PARTIAL_CREDIT_FRACTION:.0%} partial credit)"
    )


def evaluate_three_signals(
    result: PerLaneResult,
    collector: t.Any,
    window_start: float,
    window_end: float,
    expected: int,
    signal1_e2e_max_sec: float = DEFAULT_SIGNAL1_E2E_MAX_SEC,
    signal2_local_max_sec: float = DEFAULT_SIGNAL2_LOCAL_MAX_SEC,
    signal3_stability_duration_sec: float = DEFAULT_SIGNAL3_STABILITY_DURATION_SEC,
    match_field: str = "matched",
    lane_id: t.Optional[int] = None,
    stability_mode: str = BLIP_MODE_STRICT,
    host: t.Optional[str] = None,
    device_id: t.Optional[int] = None,
) -> PerLaneResult:
    """Decorate ``result`` with three independent signal evaluations.

    Signal 1 — End-to-end convergence (window_start → T2):
        T2 - window_start must be <= ``signal1_e2e_max_sec``.

    Signal 2 — Local propagation (T1 → T2):
        T2 - T1 must be <= ``signal2_local_max_sec``.
        T1 = first sample where value > 0.
        T2 = first sample where value >= ``expected``.

    Signal 3 — Post-convergence stability (T2 → T2 + duration):
        ``stability_mode="strict"`` (default): every sample in that window must
        show value >= ``expected``. If the data window ends before the full
        duration elapses, accept if at least
        ``DEFAULT_STABILITY_PARTIAL_CREDIT_FRACTION`` of the required duration
        was observed without drops.
        ``stability_mode="last_sample"`` (MODE A, disruptive triggers): ignore
        mid-window drops; only the LAST post-T2 sample must == ``expected``.
        ``stability_mode="skip_null_strict"`` (MODE B, graceful within-window
        triggers): tolerate null/missing samples, but every non-null post-T2
        sample (and the last) must == ``expected``.

    Mutates and returns ``result`` with its ``signal*`` fields populated,
    ``passed`` set to (signal1_ok AND signal2_ok AND signal3_ok), and
    ``detail`` rewritten as a human-readable 3-line summary.
    """
    rows = collector.get_rows_in_window(window_start, window_end)
    samples = _collect_sorted_samples(
        rows,
        result.device,
        lane_id,
        match_field,
        host=host,
        device_id=device_id,
    )
    t1, t2 = _find_t1_t2(samples, expected)
    _eval_signal1_e2e(result, t2, window_start, expected, signal1_e2e_max_sec)
    _eval_signal2_local(result, t1, t2, window_start, expected, signal2_local_max_sec)
    _eval_signal3_stability(
        result,
        t2,
        samples,
        window_end,
        expected,
        signal3_stability_duration_sec,
        stability_mode=stability_mode,
    )
    all_ok = (
        result.signal1_e2e_ok is True
        and result.signal2_local_ok is True
        and result.signal3_stability_ok is True
    )
    result.passed = all_ok
    result.detail = (
        f"Signal 1 (E2E ≤{signal1_e2e_max_sec:.0f}s): "
        f"{'PASS' if result.signal1_e2e_ok else 'FAIL'} — {result.signal1_e2e_detail} | "
        f"Signal 2 (GTSW ≤{signal2_local_max_sec:.0f}s): "
        f"{'PASS' if result.signal2_local_ok else 'FAIL'} — {result.signal2_local_detail} | "
        f"Signal 3 (Stable {signal3_stability_duration_sec:.0f}s): "
        f"{'PASS' if result.signal3_stability_ok else 'FAIL'} — {result.signal3_stability_detail}"
    )
    return result


_RestartObservation = t.Tuple[float, float, int, bool]


def _collect_restart_observations(
    rows: t.Iterable[t.Any], match_field: str, disruption_ts: float
) -> t.Tuple[t.List[_RestartObservation], int, int]:
    observations: t.List[_RestartObservation] = []
    null_count = 0
    legacy_count = 0
    for row in rows:
        try:
            completion_ts = _parse_ts(row.timestamp).timestamp()
        except (ValueError, AttributeError):
            continue
        request_start = float(getattr(row, "request_start_epoch", 0.0) or 0.0)
        request_end = float(getattr(row, "request_end_epoch", 0.0) or 0.0)
        legacy = request_start <= 0 or request_end < request_start
        if legacy:
            request_start = completion_ts
            request_end = completion_ts
            legacy_count += 1
        if request_start < disruption_ts:
            continue
        notes = getattr(row, "notes", "") or ""
        matched = getattr(row, match_field, None)
        if notes.startswith("error:") or matched is None:
            null_count += 1
            continue
        observations.append((request_start, request_end, int(matched), legacy))
    observations.sort(key=lambda observation: observation[1])
    return observations, null_count, legacy_count


def _evaluate_restart_observations(
    observations: t.List[_RestartObservation],
    expected: int,
    disruption_ts: float,
    reconverge_sla_sec: float,
    null_count: int,
    legacy_count: int,
) -> t.Tuple[bool, t.Optional[float], str]:
    if not observations:
        return (
            False,
            None,
            "INSUFFICIENT MEASUREMENT — no non-null samples after "
            f"restart ({null_count} null tolerated)",
        )

    recovery = next(
        (observation for observation in observations if observation[2] >= expected),
        None,
    )
    last = observations[-1][2]
    legacy_note = (
        f"; {legacy_count} legacy row(s) used completion-time fallback"
        if legacy_count
        else ""
    )
    if recovery is None:
        return (
            False,
            None,
            f"never reached {expected} after restart "
            f"(last={last}, {null_count} null tolerated{legacy_note})",
        )

    request_start, request_end, _matched, legacy = recovery
    reconverge_sec = round(request_end - disruption_ts, 1)
    deadline = disruption_ts + reconverge_sla_sec
    if request_end <= deadline:
        timing_ok = True
        timing_detail = f"completed by SLA at +{request_end - disruption_ts:.1f}s"
    elif request_start > deadline:
        timing_ok = False
        timing_detail = (
            f"request started after SLA at +{request_start - disruption_ts:.1f}s"
        )
    else:
        timing_ok = False
        timing_detail = (
            "MEASUREMENT INCONCLUSIVE — qualifying request crossed SLA "
            f"boundary (+{request_start - disruption_ts:.1f}s to "
            f"+{request_end - disruption_ts:.1f}s)"
        )

    fallback = " using legacy completion-time fallback" if legacy else ""
    if not timing_ok:
        detail = (
            f"reached {expected}, but {timing_detail}{fallback} "
            f"(last={last}, {null_count} null tolerated{legacy_note})"
        )
    elif last < expected:
        detail = (
            f"reconverged to {expected} in {reconverge_sec}s but final "
            f"sample regressed to {last}{legacy_note}"
        )
    else:
        detail = (
            f"reconverged to {expected} in {reconverge_sec}s "
            f"(SLA {reconverge_sla_sec:.0f}s; {timing_detail}{fallback}); "
            f"{null_count} null sample(s) tolerated{legacy_note}"
        )
    return timing_ok and last >= expected, reconverge_sec, detail


def evaluate_restart_reconverge(
    collector: t.Any,
    lane_map: t.Dict[int, str],
    expected: int,
    disruption_ts: float,
    window_end: float,
    reconverge_sla_sec: float,
    match_field: str = "matched",
) -> t.List[t.Tuple[int, str, bool, t.Optional[float], int, str]]:
    """Per-device RIB reconverge contract for a SERVICE RESTART.

    During a restart the restarted device's thrift queries go
    null/unresponsive for a few polls — those samples are TOLERATED (not a
    failure). Each device's RIB must return to (or hold at) ``expected`` within
    ``reconverge_sla_sec`` of ``disruption_ts`` (the recorded restart moment). A
    device whose count never dropped (only nulls) passes with reconverge ~0s.

    Request-boundary telemetry makes the SLA verdict unambiguous: a qualifying
    request must both start after the disruption and complete by the deadline.
    A qualifying request spanning the deadline is a strict measurement failure,
    while one starting after the deadline is a definite late recovery. Rows that
    predate request telemetry retain the legacy completion-timestamp behavior.

    A poll is treated as null/unresponsive when its ``notes`` starts with
    "error:" or the match field is None. Returns a list of
    (lane, device, passed, reconverge_sec, null_count, detail).
    """
    rows = collector.get_rows_in_window(disruption_ts, window_end)
    results: t.List[t.Tuple[int, str, bool, t.Optional[float], int, str]] = []
    for lane_id, device in sorted(lane_map.items()):
        drows = [r for r in rows if getattr(r, "gtsw", None) == device]
        observations, null_count, legacy_count = _collect_restart_observations(
            drows, match_field, disruption_ts
        )
        passed, reconverge_sec, detail = _evaluate_restart_observations(
            observations=observations,
            expected=expected,
            disruption_ts=disruption_ts,
            reconverge_sla_sec=reconverge_sla_sec,
            null_count=null_count,
            legacy_count=legacy_count,
        )
        results.append((lane_id, device, passed, reconverge_sec, null_count, detail))
    return results


async def wait_for_restart_reconverge(
    collector: t.Any,
    lane_map: t.Dict[int, str],
    expected: int,
    disruption_ts: float,
    reconverge_sla_sec: float,
    match_field: str = "matched",
    window_end: t.Optional[float] = None,
    poll_interval_sec: float = 1.0,
) -> t.Tuple[t.List[t.Tuple[int, str, bool, t.Optional[float], int, str]], float]:
    """Re-read live restart samples until the recovery SLA has elapsed.

    A caller-supplied ``window_end`` is an explicit historical/test boundary and
    is evaluated immediately. Live callers omit it: the health check remains
    bounded by ``disruption_ts + reconverge_sla_sec`` and re-evaluates while the
    background collector publishes new rows. Waiting through the deadline also
    makes the final valid sample part of the verdict, so an early recovery that
    regresses before the SLA expires still fails.
    """
    deadline = disruption_ts + reconverge_sla_sec
    if window_end is not None:
        final_window_end = float(window_end)
        return (
            evaluate_restart_reconverge(
                collector=collector,
                lane_map=lane_map,
                expected=expected,
                disruption_ts=disruption_ts,
                window_end=final_window_end,
                reconverge_sla_sec=reconverge_sla_sec,
                match_field=match_field,
            ),
            final_window_end,
        )

    targets = list(lane_map.values())
    boundary_wait_deadline = (
        deadline
        + float(getattr(collector, "per_gtsw_timeout_sec", 0.0))
        + poll_interval_sec
    )
    while True:
        current_time = time.time()
        results = evaluate_restart_reconverge(
            collector=collector,
            lane_map=lane_map,
            expected=expected,
            disruption_ts=disruption_ts,
            window_end=current_time,
            reconverge_sla_sec=reconverge_sla_sec,
            match_field=match_field,
        )
        remaining = deadline - current_time
        if remaining <= 0:
            has_boundary_request = getattr(
                collector, "has_inflight_request_started_by", None
            )
            if (
                callable(has_boundary_request)
                and has_boundary_request(targets, deadline)
                and current_time < boundary_wait_deadline
            ):
                await asyncio.sleep(
                    min(poll_interval_sec, boundary_wait_deadline - current_time)
                )
                continue
            return results, current_time
        await asyncio.sleep(min(poll_interval_sec, remaining))


async def wait_for_target_rib_rows(
    collector: t.Any,
    target_devices: t.Iterable[str],
    window_start: float,
    deadline: float,
    match_field: str = "matched",
    poll_interval_sec: float = 1.0,
) -> float:
    """Wait until every target device has a valid RIB row, or the deadline.

    Null/error rows and rows for non-target devices do not satisfy the wait.
    The returned timestamp is the evaluation window end. This helper only
    delays the read; the caller's normal convergence/stability policy remains
    responsible for exact counts, latency, and final-state validation.
    """
    targets = set(target_devices)
    while True:
        current_time = time.time()
        rows = collector.get_rows_in_window(window_start, current_time)
        observed = {
            str(getattr(row, "gtsw", ""))
            for row in rows
            if getattr(row, match_field, None) is not None
            and not str(getattr(row, "notes", "") or "").startswith("error:")
        }
        if targets.issubset(observed) or current_time >= deadline:
            return current_time
        await asyncio.sleep(min(poll_interval_sec, deadline - current_time))
