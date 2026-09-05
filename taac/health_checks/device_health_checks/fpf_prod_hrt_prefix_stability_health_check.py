# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import logging
import time
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.libs.fpf.fpf_collector_registry import (
    disruption_inconclusive_skip,
    everpaste_details_suffix,
    get_collector,
    get_disruption_time,
    get_recovery_completion_time,
    get_recovery_start_time,
    get_restart_completion_time,
    get_restart_time,
    get_test_case_start_time,
)
from taac.libs.fpf.fpf_prod_hrt_prefix import normalize_prefix
from taac.libs.fpf.fpf_stress_checks import (
    BLIP_MODE_LAST_SAMPLE,
    BLIP_MODE_SKIP_NULL_STRICT,
    evaluate_blip_series,
)
from taac.health_check.health_check import types as hc_types

# Fallback expected steady-state reachability (validated MWG2 FPF lab: VF1
# reachable planes 0-3, VF2 unreachable 4-7, no drains, all 8 planes UP). Only
# used when baseline_mode != "per_prefix" AND no explicit expected_* override is
# supplied. The DEFAULT behaviour is per-prefix baselines (see _run).
DEFAULT_EXPECTED_REACHABLE: t.List[int] = [0, 1, 2, 3]
DEFAULT_EXPECTED_DRAINED: t.List[int] = []
DEFAULT_EXPECTED_UNREACHABLE: t.List[int] = [4, 5, 6, 7]
DEFAULT_EXPECTED_PLANE_UP: t.List[int] = [0, 1, 2, 3, 4, 5, 6, 7]

logger: logging.Logger = logging.getLogger(__name__)

# Registry name of the single production-prefix collector (holds ALL hosts).
_COLLECTOR_NAME = "prod_hrt_prefix"

# Plane-list fields that must always be present as integer lists (never null).
_LIST_FIELDS = (
    "reachable_planes",
    "drained_planes",
    "unreachable_planes",
    "plane_up",
)


def _row_ts(row: t.Any) -> t.Optional[float]:
    from taac.libs.fpf.fpf_stress_checks import _parse_ts

    try:
        return _parse_ts(row.timestamp).timestamp()
    except (ValueError, AttributeError):
        return None


def _fmt(planes: t.Optional[t.List[int]]) -> str:
    if not planes:
        return "[]"
    return "[" + ",".join(str(p) for p in planes) + "]"


def discover_prod_collectors(
    check_params: t.Dict[str, t.Any],
) -> t.List[t.Tuple[str, t.Any]]:
    """Return [(host, collector)] for the single prod-prefix collector.

    The single collector holds ALL hosts; this returns one (host, collector)
    pair per host present in its rows so the check can iterate hosts internally
    (each _evaluate_* filters the collector's rows to the given host). Kept as a
    seam so tests can patch it to inject a synthetic collector.
    """
    if "collector_names" in check_params:
        # The pre-multi-host API accepted a plural list override; the single
        # multi-host collector makes it meaningless. Surface misconfigured
        # callers instead of silently falling back to the default name.
        logger.warning(
            "discover_prod_collectors: 'collector_names' is deprecated and "
            "ignored in the multi-host model; use singular 'collector_name'. "
            "Falling back to %r.",
            check_params.get("collector_name", _COLLECTOR_NAME),
        )
    name = check_params.get("collector_name", _COLLECTOR_NAME)
    c = get_collector(name)
    if c is None:
        return []
    hosts: t.List[str] = []
    hiw = getattr(c, "hosts_in_window", None)
    if callable(hiw):
        window_end = check_params.get("window_end", time.time())
        tc_start = get_test_case_start_time()
        lookback_sec = check_params.get("lookback_sec", 900)
        window_start = check_params.get(
            "window_start", tc_start if tc_start else window_end - lookback_sec
        )
        hosts = t.cast(t.List[str], hiw(window_start, window_end) or [])
    if not hosts:
        hosts = list(getattr(c, "hosts", []) or [])
    return [(h, c) for h in hosts]


def _prefix_samples(
    rows: t.List[t.Any],
    target_norms: t.Optional[t.Set[str]],
    host: t.Optional[str] = None,
) -> t.Dict[str, t.Dict[str, t.Any]]:
    """norm -> {display, samples: [(ts_float, ts_str, rb)] sorted}.

    ``host`` (when given) restricts to rows from that host — the single collector
    holds all hosts, so each per-host evaluation filters here.
    """
    out: t.Dict[str, t.Dict[str, t.Any]] = {}
    for row in rows:
        if host is not None and getattr(row, "host", None) != host:
            continue
        ts = _row_ts(row)
        if ts is None:
            continue
        for raw, rb in row.prefixes.items():
            norm = normalize_prefix(raw)
            if target_norms is not None and norm not in target_norms:
                continue
            entry = out.setdefault(norm, {"display": raw, "samples": []})
            entry["samples"].append((ts, row.timestamp, rb))
    for entry in out.values():
        entry["samples"].sort(key=lambda x: x[0])
    return out


def _baseline_of(rb: t.Any) -> t.Dict[str, t.List[int]]:
    return {
        "reachable_planes": sorted(rb.reachable_planes),
        "drained_planes": sorted(rb.drained_planes),
        "unreachable_planes": sorted(rb.unreachable_planes),
        "plane_up": sorted(rb.plane_up),
    }


class _HostResult:
    """Per-host evaluation outcome."""

    def __init__(self, host: str) -> None:
        self.host = host
        self.status = "SKIP"  # PASS / FAIL / SKIP
        self.n_prefixes = 0
        self.n_samples = 0
        self.s1_ok = True  # compliance
        self.s2_ok = True  # data integrity
        self.compliance_issues: t.List[str] = []
        self.null_issues: t.List[str] = []
        self.notes: t.List[str] = []
        # impacted prefix -> dict(ts_str, lost, gained, baseline, post_rb)
        self.impacts: t.List[t.Dict[str, t.Any]] = []


def _sample_null_fields(rb: t.Any) -> t.List[str]:
    """Plane fields on ``rb`` that are null/non-list (a collection blip)."""
    bad: t.List[str] = []
    for fld in _LIST_FIELDS:
        val = getattr(rb, fld, None)
        if val is None or not isinstance(val, list):
            bad.append(fld)
    return bad


def _sample_matches_baseline(rb: t.Any, baseline: t.Dict[str, t.List[int]]) -> bool:
    """Every plane-set field of ``rb`` equals the golden baseline set."""
    for fld in _LIST_FIELDS:
        if sorted(getattr(rb, fld)) != baseline[fld]:
            return False
    return True


def _rb_tuple(rb: t.Any) -> t.Tuple[t.Tuple[int, ...], ...]:
    """Comparable plane-set tuple for one (non-null) sample."""
    return tuple(tuple(sorted(getattr(rb, fld))) for fld in _LIST_FIELDS)


def _baseline_tuple(
    baseline: t.Dict[str, t.List[int]],
) -> t.Tuple[t.Tuple[int, ...], ...]:
    """Comparable plane-set tuple for the golden baseline."""
    return tuple(tuple(baseline[fld]) for fld in _LIST_FIELDS)


def _first_regressing_impact(
    display: str,
    samples: t.List[t.Any],
    baseline: t.Dict[str, t.List[int]],
    stability_mode: str,
) -> t.Optional[t.Dict[str, t.Any]]:
    """Locate the regressing non-null sample to report as the per-prefix impact.

    For MODE A (last_sample) the regressing sample is the last non-null one (only
    it is asserted); for MODE B (skip_null_strict) it is the first non-null
    sample that fails to match the baseline.
    """
    non_null = [
        (ts_str, rb) for _ts, ts_str, rb in samples if not _sample_null_fields(rb)
    ]
    if not non_null:
        return None
    if stability_mode == BLIP_MODE_LAST_SAMPLE:
        ts_str, rb = non_null[-1]
        if _sample_matches_baseline(rb, baseline):
            return None
        return _make_impact(display, ts_str, rb, baseline)
    for ts_str, rb in non_null:
        if not _sample_matches_baseline(rb, baseline):
            return _make_impact(display, ts_str, rb, baseline)
    return None


def _evaluate_host(
    host: str,
    collector: t.Any,
    window_start: float,
    window_end: float,
    target_norms: t.Optional[t.Set[str]],
    fixed_expected: t.Optional[t.Dict[str, t.List[int]]],
    stability_mode: str = "strict",
    recovery_last_n: t.Optional[int] = None,
) -> _HostResult:
    """Per-prefix, baseline-relative compliance + integrity for one host.

    ``stability_mode`` selects the per-sample blip contract on each prefix's
    plane-set series (reachable/drained/unreachable/plane_up):
      "strict" (default) — every non-null sample must match the baseline and no
        sample may have a null plane field (byte-identical legacy behaviour).
      "last_sample" (MODE A) — mid-window mismatches are ignored; only the LAST
        non-null sample's plane-sets must equal the baseline.
      "skip_null_strict" (MODE B) — null/missing samples are TOLERATED (not an
        integrity failure); every NON-NULL sample's plane-sets must equal the
        baseline, and the last non-null must too.

    ``recovery_last_n`` (when set) enables recovery mode: S1 compliance passes if
    the LAST N samples are all compliant (prefix reachable on its expected planes),
    ignoring earlier non-compliance. S2 (integrity) is unchanged.
    """
    res = _HostResult(host)
    rows = collector.get_rows_in_window(window_start, window_end)
    timeline = _prefix_samples(rows, target_norms, host=host)
    if not timeline:
        res.status = "SKIP"
        return res

    # Signal 2 (integrity): poll timeouts → null data points. Under MODE B
    # (skip_null_strict) collection blips are tolerated, so a poll timeout is not
    # counted as an integrity failure.
    timeout_count = collector.timeout_count_in_window(window_start, window_end)
    if timeout_count > 0 and stability_mode != "skip_null_strict":
        res.null_issues.append(
            f"{timeout_count} poll timeout(s) recorded null data (>2min)"
        )

    res.n_prefixes = len(timeline)
    for norm in sorted(timeline):
        info = timeline[norm]
        display = info["display"]
        samples = info["samples"]
        # Each prefix uses its OWN baseline (first in-window sample) unless a
        # fixed expected set was supplied via check_params.
        baseline = fixed_expected or _baseline_of(samples[0][2])
        first_impact = _evaluate_prefix_series(
            res, display, samples, baseline, stability_mode, recovery_last_n
        )
        if first_impact is not None:
            first_impact["display"] = display
            first_impact["device_ids"] = sorted(samples[0][2].device_ids)
            res.impacts.append(first_impact)

    res.s2_ok = not res.null_issues
    res.s1_ok = not res.compliance_issues
    if not res.s2_ok or not res.s1_ok:
        res.status = "FAIL"
    else:
        res.status = "PASS"
    return res


def _restart_rows_for_host(
    host: str,
    collector: t.Any,
    window_start: float,
    window_end: float,
) -> t.List[t.Tuple[float, t.Any]]:
    rows = [
        (ts, row)
        for row in collector.get_rows_in_window(window_start, window_end)
        if getattr(row, "host", None) == host
        if (ts := _row_ts(row)) is not None
    ]
    return sorted(rows, key=lambda item: item[0])


def _restart_monitored_prefixes(
    rows: t.List[t.Tuple[float, t.Any]], target_norms: t.Optional[t.Set[str]]
) -> t.Set[str]:
    if target_norms:
        return set(target_norms)
    return {
        normalize_prefix(pfx)
        for _ts, row in rows
        for pfx in getattr(row, "prefixes", {})
    }


def _restart_baselines(
    rows: t.List[t.Tuple[float, t.Any]],
    monitored: t.Set[str],
    restart_ts: float,
) -> t.Tuple[t.Dict[str, t.Dict[str, t.List[int]]], t.Dict[str, str]]:
    baselines: t.Dict[str, t.Dict[str, t.List[int]]] = {}
    displays: t.Dict[str, str] = {}
    for ts, row in rows:
        if ts > restart_ts:
            break
        for raw, rb in row.prefixes.items():
            norm = normalize_prefix(raw)
            if norm in monitored and not _sample_null_fields(rb):
                baselines[norm] = _baseline_of(rb)
                displays[norm] = raw
    return baselines, displays


def _complete_post_restart_rows(
    rows: t.List[t.Tuple[float, t.Any]],
    monitored: t.Set[str],
    restart_ts: float,
) -> t.Tuple[t.List[t.Tuple[float, t.Dict[str, t.Any]]], int, t.Optional[float]]:
    valid: t.List[t.Tuple[float, t.Dict[str, t.Any]]] = []
    ignored = 0
    last_incomplete_ts: t.Optional[float] = None
    for ts, row in rows:
        if ts <= restart_ts:
            continue
        by_norm = {normalize_prefix(raw): rb for raw, rb in row.prefixes.items()}
        if any(
            norm not in by_norm or _sample_null_fields(by_norm[norm])
            for norm in monitored
        ):
            ignored += 1
            last_incomplete_ts = ts
        else:
            valid.append((ts, by_norm))
    return valid, ignored, last_incomplete_ts


def _evaluate_host_restart_recovery(
    host: str,
    collector: t.Any,
    window_start: float,
    window_end: float,
    target_norms: t.Optional[t.Set[str]],
    restart_ts: float,
    max_recovery_sec: float,
    restart_completion_ts: t.Optional[float] = None,
) -> _HostResult:
    """Validate full production-prefix recovery after an HRT restart.

    Each prefix's baseline is its last complete sample at or before restart.
    Empty, partial, or invalid rows after restart are treated as expected outage
    observations. Recovery eligibility begins after the restart command
    completes or the last observed outage row, whichever is later. Recovery
    latency begins at the first complete eligible row and ends at the first row
    where every monitored prefix matches its baseline. The final complete row
    must also remain healthy.
    """
    res = _HostResult(host)
    rows = _restart_rows_for_host(host, collector, window_start, window_end)
    monitored = _restart_monitored_prefixes(rows, target_norms)
    res.n_prefixes = len(monitored)
    if not monitored:
        res.status = "FAIL"
        res.s1_ok = False
        res.s2_ok = False
        res.compliance_issues.append("no monitored prefix data")
        return res

    baselines, displays = _restart_baselines(rows, monitored, restart_ts)
    missing_baselines = sorted(monitored - set(baselines))
    if missing_baselines:
        res.status = "FAIL"
        res.s1_ok = False
        res.s2_ok = False
        res.compliance_issues.append(
            "no complete pre-restart baseline for " + ", ".join(missing_baselines)
        )
        return res

    valid_post, ignored_rows, last_incomplete_ts = _complete_post_restart_rows(
        rows, monitored, restart_ts
    )
    if ignored_rows:
        res.notes.append(
            f"ignored {ignored_rows} empty/incomplete outage row(s) after restart"
        )
    eligibility_ts = max(
        restart_ts,
        restart_completion_ts or restart_ts,
        last_incomplete_ts or restart_ts,
    )
    valid_post = [(ts, by_norm) for ts, by_norm in valid_post if ts > eligibility_ts]
    res.notes.append(f"post-outage recovery eligibility starts at {eligibility_ts:.3f}")
    res.n_samples = len(valid_post) * len(monitored)
    if not valid_post:
        res.status = "FAIL"
        res.s1_ok = False
        res.s2_ok = False
        res.compliance_issues.append("no complete valid post-restart sample")
        return res

    first_valid_ts = valid_post[0][0]
    full_recovery_ts: t.Optional[float] = None
    for ts, by_norm in valid_post:
        if all(
            _sample_matches_baseline(by_norm[norm], baselines[norm])
            for norm in monitored
        ):
            full_recovery_ts = ts
            break

    if full_recovery_ts is None:
        res.s1_ok = False
        res.compliance_issues.append(
            "no complete post-restart sample recovered all monitored prefixes"
        )
    else:
        recovery_sec = round(full_recovery_ts - first_valid_ts, 3)
        if recovery_sec > max_recovery_sec:
            res.s1_ok = False
            res.compliance_issues.append(
                f"full prefix recovery took {recovery_sec:.3f}s > "
                f"{max_recovery_sec:.1f}s SLA"
            )
        else:
            res.notes.append(
                f"all {len(monitored)} prefix(es) recovered in "
                f"{recovery_sec:.3f}s from first valid post-restart sample"
            )

    final_by_norm = valid_post[-1][1]
    final_regressions = sorted(
        displays.get(norm, norm)
        for norm in monitored
        if not _sample_matches_baseline(final_by_norm[norm], baselines[norm])
    )
    if final_regressions:
        res.s1_ok = False
        res.compliance_issues.append(
            "final valid sample regressed for " + ", ".join(final_regressions)
        )

    res.s2_ok = True
    res.status = "PASS" if res.s1_ok else "FAIL"
    return res


def _evaluate_prefix_series(
    res: _HostResult,
    display: str,
    samples: t.List[t.Any],
    baseline: t.Dict[str, t.List[int]],
    stability_mode: str,
    recovery_last_n: t.Optional[int] = None,
) -> t.Optional[t.Dict[str, t.Any]]:
    """Evaluate one prefix's plane-set series under ``stability_mode``.

    Appends to ``res.null_issues`` / ``res.compliance_issues`` as needed and
    returns the first impact dict (or None) for the per-host report.

    ``recovery_last_n`` (when set) enables recovery mode: compliance passes if the
    LAST N samples are all compliant, ignoring earlier non-compliance.
    """
    if recovery_last_n is not None:
        # Recovery mode: evaluate only the last N samples for compliance.
        # The expected (compliant) baseline for each prefix is its plane set
        # at the end of the window (the "recovered" state).
        tail = (
            samples[-recovery_last_n:] if len(samples) >= recovery_last_n else samples
        )
        expected_tuple = _baseline_tuple(baseline)
        all_compliant = all(
            not _sample_null_fields(rb) and _rb_tuple(rb) == expected_tuple
            for _ts, _ts_str, rb in tail
        )
        if all_compliant:
            return None  # PASS
        # FAIL: at least one of the last N samples is non-compliant.
        bad_samples = [
            (ts_str, rb)
            for ts, ts_str, rb in tail
            if _sample_null_fields(rb) or _rb_tuple(rb) != expected_tuple
        ]
        first_bad = bad_samples[0] if bad_samples else (None, None)
        res.compliance_issues.append(
            f"{display}: last {len(tail)} samples: {len(bad_samples)} not compliant "
            f"(recovery_last_n={recovery_last_n})"
        )
        if first_bad[1]:
            return {
                "timestamp": first_bad[0],
                "reachable": first_bad[1].reachable_planes,
                "drained": first_bad[1].drained_planes,
                "unreachable": first_bad[1].unreachable_planes,
                "plane_up": first_bad[1].plane_up,
            }
        return None
    if stability_mode in (BLIP_MODE_LAST_SAMPLE, BLIP_MODE_SKIP_NULL_STRICT):
        # Drive the pass/fail verdict through the shared blip-handling helper:
        # each sample becomes a comparable plane-set tuple (or None for a null
        # collection blip) and ``expected`` is the golden baseline tuple. The
        # per-prefix impact reporting (first regressing non-null sample) is kept
        # for the human-readable per-host report.
        expected_tuple = _baseline_tuple(baseline)
        value_series = [
            None if _sample_null_fields(rb) else _rb_tuple(rb)
            for _ts, _ts_str, rb in samples
        ]
        res.n_samples += sum(1 for v in value_series if v is not None)
        passed, detail = evaluate_blip_series(
            value_series, expected_tuple, stability_mode
        )
        if passed:
            return None
        impact = _first_regressing_impact(display, samples, baseline, stability_mode)
        if impact is not None:
            res.compliance_issues.append(
                f"{display} regressed at {impact['ts_str']}: reachable "
                f"{_fmt(baseline['reachable_planes'])}->"
                f"{_fmt(sorted(impact['rb'].reachable_planes))} "
                f"([{stability_mode}] {detail})"
            )
        else:
            res.compliance_issues.append(f"{display}: [{stability_mode}] {detail}")
        return impact

    # strict (default): null plane field → integrity failure; first mismatch →
    # compliance failure.
    first_impact: t.Optional[t.Dict[str, t.Any]] = None
    for _ts, ts_str, rb in samples:
        null_fields = _sample_null_fields(rb)
        if null_fields:
            for fld in null_fields:
                res.null_issues.append(f"{display}.{fld} null at {ts_str}")
            continue
        res.n_samples += 1
        if not _sample_matches_baseline(rb, baseline) and first_impact is None:
            first_impact = _make_impact(display, ts_str, rb, baseline)
            res.compliance_issues.append(
                f"{display} regressed at {ts_str}: reachable "
                f"{_fmt(baseline['reachable_planes'])}->"
                f"{_fmt(sorted(rb.reachable_planes))}"
            )
    return first_impact


def _make_impact(
    display: str,
    ts_str: str,
    rb: t.Any,
    baseline: t.Dict[str, t.List[int]],
) -> t.Dict[str, t.Any]:
    base_r = set(baseline["reachable_planes"])
    cur_r = set(rb.reachable_planes)
    return {
        "ts_str": ts_str,
        "lost": sorted(base_r - cur_r),
        "gained": sorted(cur_r - base_r),
        "baseline": baseline,
        "rb": rb,
    }


def _evaluate_host_transition(
    host: str,
    collector: t.Any,
    window_start: float,
    window_end: float,
    target_norms: t.Optional[t.Set[str]],
    impacted_planes: t.Set[int],
    max_transition_sec: float,
    disruption_ts: t.Optional[float],
) -> _HostResult:
    """Link-event transition contract for one host.

    For every monitored prefix, each impacted plane that was reachable at the
    window baseline MUST leave the reachable set (go drained/unreachable) and do
    so within ``max_transition_sec``. The transition latency is measured from
    ``disruption_ts`` when supplied, else from the plane's last still-reachable
    sample before the drop (disruption-relative latency). A plane that never
    drops, or drops too slowly, fails. By the final in-window sample the
    impacted planes must not be reachable.
    """
    res = _HostResult(host)
    rows = collector.get_rows_in_window(window_start, window_end)
    timeline = _prefix_samples(rows, target_norms, host=host)
    if not timeline:
        res.status = "SKIP"
        return res

    timeout_count = collector.timeout_count_in_window(window_start, window_end)
    if timeout_count > 0:
        res.null_issues.append(
            f"{timeout_count} poll timeout(s) recorded null data (>2min)"
        )

    res.n_prefixes = len(timeline)
    any_relevant = False
    for norm in sorted(timeline):
        info = timeline[norm]
        display = info["display"]
        samples = info["samples"]
        baseline_reachable = set(samples[0][2].reachable_planes)
        relevant = sorted(impacted_planes & baseline_reachable)
        if not relevant:
            # This prefix is not carried on any impacted plane (e.g. a remote
            # VF2 prefix when a VF1 lane was disabled) — skip from transition.
            continue
        any_relevant = True
        res.n_samples += len(samples)
        final_reachable = set(samples[-1][2].reachable_planes)
        for plane in relevant:
            last_reachable_ts: t.Optional[float] = None
            drop_ts: t.Optional[float] = None
            drop_str = ""
            for ts, ts_str, rb in samples:
                if plane in set(rb.reachable_planes):
                    if drop_ts is None:
                        last_reachable_ts = ts
                else:
                    if drop_ts is None:
                        drop_ts = ts
                        drop_str = ts_str
            if drop_ts is None:
                res.compliance_issues.append(
                    f"{display} plane {plane} never left reachable "
                    f"(link-disable did not take)"
                )
                continue
            ref = disruption_ts if disruption_ts is not None else last_reachable_ts
            if ref is None:
                # Plane was already non-reachable from the very first sample;
                # treat as an immediate (0s) transition.
                ref = drop_ts
            transition_sec = round(drop_ts - ref, 1)
            if transition_sec > max_transition_sec:
                res.compliance_issues.append(
                    f"{display} plane {plane} went unreachable in "
                    f"{transition_sec}s > {max_transition_sec:.0f}s SLA @ {drop_str}"
                )
            elif plane in final_reachable:
                res.compliance_issues.append(
                    f"{display} plane {plane} flapped back to reachable by "
                    f"window end (not durably down)"
                )
            else:
                res.impacts.append(
                    {
                        "display": display,
                        "device_ids": sorted(samples[0][2].device_ids),
                        "ts_str": drop_str,
                        "lost": [plane],
                        "gained": [],
                        "baseline": {"reachable_planes": sorted(baseline_reachable)},
                        "rb": samples[-1][2],
                        "transition_sec": transition_sec,
                    }
                )

    res.s2_ok = not res.null_issues
    res.s1_ok = not res.compliance_issues
    if not any_relevant and res.s2_ok:
        # No monitored prefix sits on an impacted plane on this host.
        res.status = "SKIP"
    elif not res.s1_ok or not res.s2_ok:
        res.status = "FAIL"
    else:
        res.status = "PASS"
    return res


def _evaluate_host_local_drain(
    host: str,
    collector: t.Any,
    window_start: float,
    window_end: float,
    local_norms: t.Set[str],
    impacted_planes: t.Set[int],
    max_drain_sec: float,
    action_ts: t.Optional[float],
    recovery_completion_ts: t.Optional[float],
    to_drained: bool,
) -> _HostResult:
    """Local-vs-remote drain/undrain contract for one host.

    Splits monitored prefixes into LOCAL (this host's own, ``local_norms``) and
    REMOTE (everything else). Three signals on the LOCAL prefixes' impacted
    plane(s); a no-churn assertion on the REMOTE prefixes:

      ``to_drained=True`` (DRAIN): each impacted plane that was reachable at the
        baseline must move into ``drained_planes`` (Signal 1), must NOT land in
        ``unreachable_planes`` — drained, not unavailable (Signal 2), and must do
        so within ``max_drain_sec`` of the recorded drain start (Signal 3).
      ``to_drained=False`` (UNDRAIN): each impacted plane must LEAVE
        ``drained_planes`` and return to ``reachable_planes`` within
        ``max_drain_sec`` of the separately recorded recovery start
        (Signals 1+3); it must not be left unreachable (Signal 2), and at
        least one sample must follow recovery completion.

    REMOTE prefixes must show NO churn: their reachable plane set is unchanged
    across the whole window (a drain of THIS host's local advert must not move a
    remote destination's reachability).
    """
    res = _HostResult(host)
    rows = collector.get_rows_in_window(window_start, window_end)
    timeline = _prefix_samples(rows, None, host=host)
    if not timeline:
        res.status = "SKIP"
        return res

    timeout_count = collector.timeout_count_in_window(window_start, window_end)
    if timeout_count > 0:
        res.null_issues.append(
            f"{timeout_count} poll timeout(s) recorded null data (>2min)"
        )

    res.n_prefixes = len(timeline)
    any_relevant = False

    def _split(
        samples: t.List[t.Any],
    ) -> t.Tuple[t.Any, t.List[t.Any]]:
        """Return the pre-action baseline and post-action samples.

        Anchoring the baseline at the sample JUST BEFORE the recorded disruption
        time makes the check robust to a dirty starting state (e.g. a plane left
        drained by a prior aborted run): we judge the transition the action
        actually caused, measured from its recorded start, not from whatever the
        window happened to open on.
        """
        if action_ts is None:
            return samples[0][2], samples
        pre = [s for s in samples if s[0] <= action_ts]
        post = [s for s in samples if s[0] > action_ts]
        base = pre[-1][2] if pre else samples[0][2]
        return base, (post if post else samples)

    for norm in sorted(timeline):
        info = timeline[norm]
        display = info["display"]
        samples = info["samples"]
        res.n_samples += len(samples)
        is_local = norm in local_norms
        base_rb, post_samples = _split(samples)

        if (
            not to_drained
            and recovery_completion_ts is not None
            and not any(ts >= recovery_completion_ts for ts, _ts_str, _rb in samples)
        ):
            res.compliance_issues.append(
                f"{display} has no collector sample after recovery completed at "
                f"{recovery_completion_ts:.3f}"
            )
            continue

        if not is_local:
            # REMOTE prefix: reachable set must not change through the disruption.
            baseline_reachable = set(base_rb.reachable_planes)
            for _ts, ts_str, rb in post_samples:
                if set(rb.reachable_planes) != baseline_reachable:
                    res.compliance_issues.append(
                        f"REMOTE {display} churned at {ts_str}: reachable "
                        f"{_fmt(sorted(baseline_reachable))}->"
                        f"{_fmt(sorted(rb.reachable_planes))} "
                        f"(expected no change on a local-host drain)"
                    )
                    break
            continue

        # LOCAL prefix: assert the drain/undrain transition on impacted planes.
        baseline_reachable = set(base_rb.reachable_planes)
        baseline_drained = set(base_rb.drained_planes)
        # On DRAIN the relevant planes are those reachable just before the drain;
        # on UNDRAIN they are the impacted planes drained just before the undrain.
        if to_drained:
            relevant = sorted(impacted_planes & baseline_reachable)
        else:
            relevant = sorted(impacted_planes & baseline_drained)
            if not relevant:
                relevant = sorted(impacted_planes)
        if not relevant:
            continue
        any_relevant = True
        final_rb = samples[-1][2]
        baseline_unreach = set(base_rb.unreachable_planes)
        for plane in relevant:
            transition_ts: t.Optional[float] = None
            for ts, _ts_str, rb in post_samples:
                in_drained = plane in set(rb.drained_planes)
                in_reach = plane in set(rb.reachable_planes)
                if to_drained and in_drained and transition_ts is None:
                    transition_ts = ts
                if (
                    not to_drained
                    and in_reach
                    and not in_drained
                    and transition_ts is None
                ):
                    transition_ts = ts

            want = "drained" if to_drained else "reachable"
            # Signal 1: the impacted plane reached the expected state.
            if transition_ts is None:
                res.compliance_issues.append(
                    f"LOCAL {display} plane {plane} never became {want} "
                    f"({'drain' if to_drained else 'undrain'} did not take)"
                )
                continue
            # Signal 2: a DRAINED prefix-plane is inherently also a negative route
            # (it shows up in unreachable) — that is the EXPECTED consequence of an
            # intentional drain, not a fault. So "not unavailable" means: no plane
            # went unreachable WITHOUT being drained, and (undrain) the plane is
            # not left unreachable. Checked per-prefix below for drain; per-plane
            # here for undrain.
            if not to_drained and plane in set(final_rb.unreachable_planes):
                res.compliance_issues.append(
                    f"LOCAL {display} plane {plane} left UNREACHABLE after undrain "
                    f"(expected reachable)"
                )
            # Signal 3: within SLA, measured from the drain/recovery action.
            ref = action_ts if action_ts is not None else post_samples[0][0]
            latency = round(transition_ts - ref, 1)
            if latency > max_drain_sec:
                res.compliance_issues.append(
                    f"LOCAL {display} plane {plane} became {want} in {latency}s "
                    f"> {max_drain_sec:.0f}s SLA"
                )
            else:
                res.impacts.append(
                    {
                        "display": display,
                        "device_ids": sorted(base_rb.device_ids),
                        "ts_str": "",
                        "lost": [plane] if to_drained else [],
                        "gained": [] if to_drained else [plane],
                        "baseline": {"reachable_planes": sorted(baseline_reachable)},
                        "rb": final_rb,
                        "transition_sec": latency,
                    }
                )

        # Signal 2 (drain): "no unavailable planes". A drained plane is expected
        # to also show as a negative route (unreachable) — that is fine. But any
        # plane that became unreachable WITHOUT being drained (beyond the steady
        # baseline) is a genuine outage, not a drain.
        if to_drained:
            new_unreach = set(final_rb.unreachable_planes) - baseline_unreach
            unexplained = new_unreach - set(final_rb.drained_planes)
            if unexplained:
                res.compliance_issues.append(
                    f"LOCAL {display} plane(s) {sorted(unexplained)} went "
                    f"UNAVAILABLE (unreachable without being drained)"
                )

    res.s2_ok = not res.null_issues
    res.s1_ok = not res.compliance_issues
    if not any_relevant and res.s2_ok and not res.compliance_issues:
        res.status = "SKIP"
    elif not res.s1_ok or not res.s2_ok:
        res.status = "FAIL"
    else:
        res.status = "PASS"
    return res


def _format_report(host_results: t.List[_HostResult], agg: str) -> str:
    """Human-readable multi-host report (this is the everpaste'd message)."""
    lines: t.List[str] = []
    lines.append(f"Prod HRT prefix stability — {len(host_results)} host(s)")
    for r in host_results:
        lines.append(
            f"[{r.host}] VERDICT {r.status} | "
            f"S1 compliance {'PASS' if r.s1_ok else 'FAIL'} | "
            f"S2 data-integrity {'PASS' if r.s2_ok else 'FAIL'} | "
            f"{r.n_prefixes} prefix(es), {r.n_samples} sample(s)"
        )
        for imp in sorted(r.impacts, key=lambda x: x["ts_str"]):
            rb = imp["rb"]
            lines.append(
                f"    IMPACTED {imp['display']} (dev "
                f"{','.join(map(str, imp['device_ids']))}) @ {imp['ts_str']}: "
                f"lost {_fmt(imp['lost'])}"
                + (f" gained {_fmt(imp['gained'])}" if imp["gained"] else "")
                + f"; reachable {_fmt(imp['baseline']['reachable_planes'])}->"
                f"{_fmt(sorted(rb.reachable_planes))}, "
                f"drained={_fmt(sorted(rb.drained_planes))}, "
                f"unreachable={_fmt(sorted(rb.unreachable_planes))}"
            )
        if r.null_issues and not r.impacts:
            lines.append(f"    NULL: {'; '.join(r.null_issues[:5])}")
        if r.compliance_issues and not r.impacts:
            lines.append(f"    ISSUE: {'; '.join(r.compliance_issues[:5])}")
        for note in r.notes:
            lines.append(f"    NOTE: {note}")
    lines.append(f"AGGREGATE: {agg}")
    return "\n".join(lines)


class FpfProdHrtPrefixStabilityHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    """Postcheck: production HRT prefix reachability stability, per host.

    Consumes the single live ``prod_hrt_prefix`` collector registered in the FPF
    collector registry. That ONE collector holds ALL monitored hosts (each row
    carries its ``host``, and each host monitors its own prefixes); this check
    iterates the hosts present in its rows and evaluates each host independently.
    For every monitored prefix on a host, over the test window:

      Signal 1 — Compliance: every in-window sample matches the prefix's
        baseline plane sets (reachable / drained / unreachable / plane_up).
        By default the baseline is the prefix's OWN first in-window sample
        (``baseline_mode="per_prefix"``), so local (VF1, planes 0-3) and
        remote (VF2, planes 4-7) prefixes are each validated against their own
        steady state. A fixed expected set can be pinned via the
        ``expected_*`` check_params (applied to all prefixes).
      Signal 2 — Data integrity: no null data points (poll timeout >2min,
        missing prefix, or a non-list plane field).

    ``mode="restart_recovery"`` is the HRT-restart exception to that strict
    stability rule. It reports but ignores empty/incomplete outage rows, uses
    each prefix's last complete pre-restart sample as baseline, and bounds full
    post-restart recovery from the first complete sample after restart completion
    or the final outage row. This prevents a healthy pre-outage race sample from
    anchoring recovery at zero seconds.

    The result message is a per-host report that names every IMPACTED prefix
    with the timestamp it regressed and the planes lost (before->after). When
    run through the health-check framework (TAAC) the message is uploaded to
    Everpaste automatically, so the impacted-prefix detail is shareable without
    any binary involvement.

    The overall status is FAIL if any host fails Signal 1 or Signal 2, SKIP if
    no host produced in-window data, else PASS.
    """

    CHECK_NAME = hc_types.CheckName.FPF_PROD_HRT_PREFIX_STABILITY_CHECK
    CHECK_SCOPE = hc_types.Scope.DEFAULT
    OPERATING_SYSTEMS = ["FBOSS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        collectors = discover_prod_collectors(check_params)
        if not collectors:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message="No prod_hrt_prefix collector(s) in registry",
            )

        window_end = check_params.get("window_end", time.time())
        tc_start = get_test_case_start_time()
        lookback_sec = check_params.get("lookback_sec", 900)
        window_start = check_params.get(
            "window_start", tc_start if tc_start else window_end - lookback_sec
        )

        mode = check_params.get("mode", "stability")
        # Blip-handling contract for the stability assertion (mode="stability"):
        # "strict" (default), "last_sample" (MODE A — disruptive), or
        # "skip_null_strict" (MODE B — graceful within-window). Ignored by the
        # transition / local_drain / local_undrain modes.
        stability_mode = check_params.get("stability_mode", "strict")
        # recovery_last_n: when set (mode="stability"), S1 compliance passes if the
        # LAST N samples are all compliant (prefix reachable on its expected planes),
        # ignoring earlier non-compliance. Recovery mode for fsdb kill.
        recovery_last_n: t.Optional[int] = check_params.get("recovery_last_n")
        # settle_sec: skip the first settle_sec of the window before evaluating
        # stability. Used by the restore/recovery phase: the per-prefix baseline
        # is the first IN-WINDOW sample, so without this the baseline captures the
        # still-degraded state at window start (the re-enable hasn't recovered the
        # plane yet) and the subsequent recovery (plane comes back) is flagged as
        # a regression. Advancing the window start past the recovery makes the
        # baseline the healthy steady state and the tail validates it stays
        # stable. Not applied to transition mode (which needs the full window).
        settle_sec = float(check_params.get("settle_sec", 0))
        if settle_sec > 0 and mode == "stability":
            window_start = min(window_start + settle_sec, window_end)

        prefix_filter = check_params.get("prefixes")
        target_norms = (
            {normalize_prefix(p) for p in prefix_filter} if prefix_filter else None
        )

        fixed_expected = self._build_fixed_expected(check_params)

        # mode="transition" (link-event): impacted planes must go reachable->
        # unreachable within max_transition_sec. mode="local_drain"/"local_undrain"
        # (see _evaluate_host_local_drain): LOCAL prefix impacted plane transitions
        # to/from drained within max_drain_sec while REMOTE prefixes don't churn.
        # Default "stability" (read above). The drain-direction modes SKIP when the
        # disruption was verified ineffective.
        if mode in ("transition", "local_drain"):
            _skip = disruption_inconclusive_skip()
            if _skip:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.SKIP, message=_skip
                )
        impacted_by_host: t.Dict[str, t.List[int]] = (
            check_params.get("impacted_planes_by_host", {}) or {}
        )
        max_transition_sec = float(check_params.get("max_transition_sec", 30.0))
        # LOCAL prefix set (this host's own advertised prefixes). Everything else
        # monitored is treated as REMOTE for the local_drain/local_undrain modes.
        local_norms: t.Set[str] = {
            normalize_prefix(p) for p in (check_params.get("local_prefixes") or [])
        }
        max_drain_sec = float(check_params.get("max_drain_sec", 30.0))
        # Reference for the transition SLA: explicit check_param wins; else the
        # disruption time recorded at runtime by the record_fpf_disruption_time
        # step (the actual interface-flap / drain moment); else None, which makes
        # _evaluate_host_transition fall back to the last-reachable-sample
        # heuristic.
        disruption_ts = check_params.get("disruption_ts")
        if disruption_ts is None:
            recorded = get_disruption_time()
            disruption_ts = recorded if recorded > 0 else None

        recovery_ts: t.Optional[float] = None
        recovery_completion_ts: t.Optional[float] = None
        if mode == "local_undrain":
            recovery_ts = check_params.get("recovery_ts")
            if recovery_ts is None:
                recorded_recovery = get_recovery_start_time()
                recovery_ts = recorded_recovery if recorded_recovery > 0 else None
            recovery_completion_ts = check_params.get("recovery_completion_ts")
            if recovery_completion_ts is None:
                recorded_completion = get_recovery_completion_time()
                recovery_completion_ts = (
                    recorded_completion if recorded_completion > 0 else None
                )
            if recovery_ts is None or recovery_completion_ts is None:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=(
                        "No complete recorded recovery boundary for local_undrain "
                        f"(start={recovery_ts}, completion={recovery_completion_ts})"
                    ),
                )
            # Cleanup of the disrupt playbook may perform the undrain before the
            # restore playbook starts. Retain those cross-playbook samples.
            if "window_start" not in check_params:
                window_start = min(window_start, recovery_ts)

        restart_ts: t.Optional[float] = None
        restart_completion_ts: t.Optional[float] = None
        max_recovery_sec = float(check_params.get("max_recovery_sec", 30.0))
        if mode == "restart_recovery":
            restart_ts = check_params.get("restart_ts")
            if restart_ts is None:
                recorded = get_restart_time()
                restart_ts = recorded if recorded > 0 else None
            if restart_ts is None:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message="No recorded HRT restart timestamp",
                )
            restart_completion_ts = check_params.get("restart_completion_ts")
            if restart_completion_ts is None:
                recorded_completion = get_restart_completion_time()
                restart_completion_ts = (
                    recorded_completion if recorded_completion > 0 else None
                )

        host_results = self._evaluate_hosts(
            collectors,
            mode=mode,
            window_start=window_start,
            window_end=window_end,
            target_norms=target_norms,
            fixed_expected=fixed_expected,
            stability_mode=stability_mode,
            recovery_last_n=recovery_last_n,
            local_norms=local_norms,
            impacted_by_host=impacted_by_host,
            max_drain_sec=max_drain_sec,
            max_transition_sec=max_transition_sec,
            disruption_ts=disruption_ts,
            recovery_ts=recovery_ts,
            recovery_completion_ts=recovery_completion_ts,
            restart_ts=restart_ts,
            restart_completion_ts=restart_completion_ts,
            max_recovery_sec=max_recovery_sec,
        )
        return await self._aggregate_and_report(
            host_results, collectors, window_start, window_end
        )

    @staticmethod
    def _build_fixed_expected(
        check_params: t.Dict[str, t.Any],
    ) -> t.Optional[t.Dict[str, t.List[int]]]:
        """Per-prefix baselines by default; return a fixed expected-plane set only
        if any ``expected_*`` is supplied or ``baseline_mode`` is explicitly not
        ``per_prefix`` (else None)."""
        baseline_mode = check_params.get("baseline_mode", "per_prefix")
        has_expected = any(
            check_params.get(k) is not None
            for k in (
                "expected_reachable",
                "expected_drained",
                "expected_unreachable",
                "expected_plane_up",
            )
        )
        if baseline_mode == "per_prefix" and not has_expected:
            return None
        return {
            "reachable_planes": sorted(
                check_params.get("expected_reachable", DEFAULT_EXPECTED_REACHABLE)
            ),
            "drained_planes": sorted(
                check_params.get("expected_drained", DEFAULT_EXPECTED_DRAINED)
            ),
            "unreachable_planes": sorted(
                check_params.get("expected_unreachable", DEFAULT_EXPECTED_UNREACHABLE)
            ),
            "plane_up": sorted(
                check_params.get("expected_plane_up", DEFAULT_EXPECTED_PLANE_UP)
            ),
        }

    def _evaluate_hosts(
        self,
        collectors: t.List[t.Tuple[str, t.Any]],
        *,
        mode: str,
        window_start: float,
        window_end: float,
        target_norms: t.Optional[t.Set[str]],
        fixed_expected: t.Optional[t.Dict[str, t.List[int]]],
        stability_mode: str,
        recovery_last_n: t.Optional[int],
        local_norms: t.Set[str],
        impacted_by_host: t.Dict[str, t.List[int]],
        max_drain_sec: float,
        max_transition_sec: float,
        disruption_ts: t.Optional[float],
        recovery_ts: t.Optional[float],
        recovery_completion_ts: t.Optional[float],
        restart_ts: t.Optional[float],
        restart_completion_ts: t.Optional[float],
        max_recovery_sec: float,
    ) -> t.List[_HostResult]:
        """Dispatch each (host, collector) to the evaluator for ``mode`` and log a
        one-line verdict per host."""
        dts = float(disruption_ts) if disruption_ts is not None else None
        rts = float(recovery_ts) if recovery_ts is not None else None
        host_results: t.List[_HostResult] = []
        for host, collector in collectors:
            impacted = {int(p) for p in impacted_by_host.get(host, [])}
            if mode == "restart_recovery":
                if restart_ts is None:
                    raise ValueError("restart_recovery requires restart_ts")
                res = _evaluate_host_restart_recovery(
                    host,
                    collector,
                    window_start,
                    window_end,
                    target_norms,
                    restart_ts,
                    max_recovery_sec,
                    restart_completion_ts,
                )
            elif mode in ("local_drain", "local_undrain"):
                res = _evaluate_host_local_drain(
                    host,
                    collector,
                    window_start,
                    window_end,
                    local_norms,
                    impacted,
                    max_drain_sec,
                    dts if mode == "local_drain" else rts,
                    recovery_completion_ts,
                    to_drained=(mode == "local_drain"),
                )
            elif mode == "transition":
                res = _evaluate_host_transition(
                    host,
                    collector,
                    window_start,
                    window_end,
                    target_norms,
                    impacted,
                    max_transition_sec,
                    dts,
                )
            else:
                res = _evaluate_host(
                    host,
                    collector,
                    window_start,
                    window_end,
                    target_norms,
                    fixed_expected,
                    stability_mode=stability_mode,
                    recovery_last_n=recovery_last_n,
                )
            host_results.append(res)
            self.logger.info(
                f"  [prod HRT prefix][{host}] mode={mode} VERDICT {res.status} — "
                f"S1 {'PASS' if res.s1_ok else 'FAIL'}, "
                f"S2 {'PASS' if res.s2_ok else 'FAIL'}, "
                f"{len(res.impacts)} impacted prefix(es)"
            )
        return host_results

    async def _aggregate_and_report(
        self,
        host_results: t.List[_HostResult],
        collectors: t.List[t.Tuple[str, t.Any]],
        window_start: float,
        window_end: float,
    ) -> hc_types.HealthCheckResult:
        """Aggregate per-host verdicts (SKIP if all skipped, FAIL if any failed,
        else PASS) and attach the full per-host report + Everpaste details."""
        if all(r.status == "SKIP" for r in host_results):
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=(
                    "No in-window prod_hrt_prefix samples on any host "
                    f"[{window_start:.0f}, {window_end:.0f}]"
                ),
            )

        agg = "FAIL" if any(r.status == "FAIL" for r in host_results) else "PASS"
        status = (
            hc_types.HealthCheckStatus.FAIL
            if agg == "FAIL"
            else hc_types.HealthCheckStatus.PASS
        )

        report = _format_report(host_results, agg)
        # discover_prod_collectors repeats the single collector once per host;
        # dedupe by identity so the poll table is attached only once.
        unique_collectors: t.List[t.Any] = []
        for _host, c in collectors:
            if all(c is not seen for seen in unique_collectors):
                unique_collectors.append(c)
        details = await everpaste_details_suffix(
            "Prod HRT prefix stability — full per-host report",
            report.splitlines(),
            collectors=unique_collectors,
            window_start=window_start,
            window_end=window_end,
            result_status=("FAIL" if agg == "FAIL" else "PASS"),
            result_reason=(
                report.splitlines()[1] if len(report.splitlines()) > 1 else ""
            )[:300],
        )
        return hc_types.HealthCheckResult(
            status=status,
            message=report + details,
        )
