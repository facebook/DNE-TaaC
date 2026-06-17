# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import time
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.libs.fpf.fpf_collector_registry import (
    disruption_inconclusive_skip,
    everpaste_details_suffix,
    get_all_collectors,
    get_collector,
    get_disruption_time,
    get_test_case_start_time,
)
from taac.libs.fpf.fpf_prod_hrt_prefix import normalize_prefix
from taac.health_check.health_check import types as hc_types

# Fallback expected steady-state reachability (validated MWG2 FPF lab: VF1
# reachable planes 0-3, VF2 unreachable 4-7, no drains, all 8 planes UP). Only
# used when baseline_mode != "per_prefix" AND no explicit expected_* override is
# supplied. The DEFAULT behaviour is per-prefix baselines (see _run).
DEFAULT_EXPECTED_REACHABLE: t.List[int] = [0, 1, 2, 3]
DEFAULT_EXPECTED_DRAINED: t.List[int] = []
DEFAULT_EXPECTED_UNREACHABLE: t.List[int] = [4, 5, 6, 7]
DEFAULT_EXPECTED_PLANE_UP: t.List[int] = [0, 1, 2, 3, 4, 5, 6, 7]

# Registry-name prefix used to discover production-prefix collectors. The single
# legacy registration ("prod_hrt_prefix") and multi-host registrations
# ("prod_hrt_prefix:<host>") both match.
_COLLECTOR_NAME_PREFIX = "prod_hrt_prefix"

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
    """Return [(host, collector)] for every registered prod-prefix collector.

    Honors an explicit ``collector_names`` check_param; otherwise discovers all
    registry entries whose name starts with ``prod_hrt_prefix`` (covers both the
    legacy single registration and per-host ``prod_hrt_prefix:<host>`` ones).
    """
    names = check_params.get("collector_names")
    out: t.List[t.Tuple[str, t.Any]] = []
    if names:
        for n in names:
            c = get_collector(n)
            if c is not None:
                out.append((str(getattr(c, "host", n)), c))
        return out
    for name, c in get_all_collectors().items():
        if name.startswith(_COLLECTOR_NAME_PREFIX) and hasattr(c, "get_rows_in_window"):
            out.append((getattr(c, "host", name), c))
    # Stable order by host for deterministic reporting.
    out.sort(key=lambda hc: hc[0])
    return out


def _prefix_samples(
    rows: t.List[t.Any], target_norms: t.Optional[t.Set[str]]
) -> t.Dict[str, t.Dict[str, t.Any]]:
    """norm -> {display, samples: [(ts_float, ts_str, rb)] sorted}."""
    out: t.Dict[str, t.Dict[str, t.Any]] = {}
    for row in rows:
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
        # impacted prefix -> dict(ts_str, lost, gained, baseline, post_rb)
        self.impacts: t.List[t.Dict[str, t.Any]] = []


def _evaluate_host(
    host: str,
    collector: t.Any,
    window_start: float,
    window_end: float,
    target_norms: t.Optional[t.Set[str]],
    fixed_expected: t.Optional[t.Dict[str, t.List[int]]],
) -> _HostResult:
    """Per-prefix, baseline-relative compliance + integrity for one host."""
    res = _HostResult(host)
    rows = collector.get_rows_in_window(window_start, window_end)
    timeline = _prefix_samples(rows, target_norms)
    if not timeline:
        res.status = "SKIP"
        return res

    # Signal 2 (integrity): poll timeouts → null data points.
    timeout_count = collector.timeout_count_in_window(window_start, window_end)
    if timeout_count > 0:
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
        first_impact: t.Optional[t.Dict[str, t.Any]] = None
        for _ts, ts_str, rb in samples:
            # Integrity: every plane field must be a real integer list.
            null_field = False
            for fld in _LIST_FIELDS:
                val = getattr(rb, fld, None)
                if val is None or not isinstance(val, list):
                    res.null_issues.append(f"{display}.{fld} null at {ts_str}")
                    null_field = True
            if null_field:
                continue
            res.n_samples += 1
            # Compliance: every field must match the baseline set.
            mismatch = False
            for fld in _LIST_FIELDS:
                if sorted(getattr(rb, fld)) != baseline[fld]:
                    mismatch = True
            if mismatch and first_impact is None:
                base_r = set(baseline["reachable_planes"])
                cur_r = set(rb.reachable_planes)
                first_impact = {
                    "ts_str": ts_str,
                    "lost": sorted(base_r - cur_r),
                    "gained": sorted(cur_r - base_r),
                    "baseline": baseline,
                    "rb": rb,
                }
                res.compliance_issues.append(
                    f"{display} regressed at {ts_str}: reachable "
                    f"{_fmt(baseline['reachable_planes'])}->"
                    f"{_fmt(sorted(rb.reachable_planes))}"
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
    timeline = _prefix_samples(rows, target_norms)
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
    disruption_ts: t.Optional[float],
    to_drained: bool,
) -> _HostResult:
    """Local-vs-remote drain/undrain contract for one host.

    Splits monitored prefixes into LOCAL (this host's own, ``local_norms``) and
    REMOTE (everything else). Three signals on the LOCAL prefixes' impacted
    plane(s); a no-churn assertion on the REMOTE prefixes:

      ``to_drained=True`` (DRAIN): each impacted plane that was reachable at the
        baseline must move into ``drained_planes`` (Signal 1), must NOT land in
        ``unreachable_planes`` — drained, not unavailable (Signal 2), and must do
        so within ``max_drain_sec`` of ``disruption_ts`` (Signal 3).
      ``to_drained=False`` (UNDRAIN): each impacted plane must LEAVE
        ``drained_planes`` and return to ``reachable_planes`` within
        ``max_drain_sec`` (Signals 1+3); it must not be left unreachable
        (Signal 2).

    REMOTE prefixes must show NO churn: their reachable plane set is unchanged
    across the whole window (a drain of THIS host's local advert must not move a
    remote destination's reachability).
    """
    res = _HostResult(host)
    rows = collector.get_rows_in_window(window_start, window_end)
    timeline = _prefix_samples(rows, None)
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
        """(pre-disruption baseline sample, post-disruption samples).

        Anchoring the baseline at the sample JUST BEFORE the recorded disruption
        time makes the check robust to a dirty starting state (e.g. a plane left
        drained by a prior aborted run): we judge the transition the disruption
        actually caused, measured from the disruption moment, not from whatever
        the window happened to open on.
        """
        if disruption_ts is None:
            return samples[0][2], samples
        pre = [s for s in samples if s[0] <= disruption_ts]
        post = [s for s in samples if s[0] > disruption_ts]
        base = pre[-1][2] if pre else samples[0][2]
        return base, (post if post else samples)

    for norm in sorted(timeline):
        info = timeline[norm]
        display = info["display"]
        samples = info["samples"]
        res.n_samples += len(samples)
        is_local = norm in local_norms
        base_rb, post_samples = _split(samples)

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
            # Signal 3: within SLA, measured from the disruption moment.
            ref = disruption_ts if disruption_ts is not None else post_samples[0][0]
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
    lines.append(f"AGGREGATE: {agg}")
    return "\n".join(lines)


class FpfProdHrtPrefixStabilityHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    """Postcheck: production HRT prefix reachability stability, per host.

    Consumes the live ``prod_hrt_prefix`` collector(s) registered in the FPF
    collector registry. Discovers ALL such collectors (one per host) and
    evaluates each host independently. For every monitored prefix on a host,
    over the test window:

      Signal 1 — Compliance: every in-window sample matches the prefix's
        baseline plane sets (reachable / drained / unreachable / plane_up).
        By default the baseline is the prefix's OWN first in-window sample
        (``baseline_mode="per_prefix"``), so local (VF1, planes 0-3) and
        remote (VF2, planes 4-7) prefixes are each validated against their own
        steady state. A fixed expected set can be pinned via the
        ``expected_*`` check_params (applied to all prefixes).
      Signal 2 — Data integrity: no null data points (poll timeout >2min,
        missing prefix, or a non-list plane field).

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

        # Per-prefix baselines by default; a fixed expected set is used only if
        # any expected_* is supplied or baseline_mode is explicitly "fixed".
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
        fixed_expected: t.Optional[t.Dict[str, t.List[int]]] = None
        if baseline_mode != "per_prefix" or has_expected:
            fixed_expected = {
                "reachable_planes": sorted(
                    check_params.get("expected_reachable", DEFAULT_EXPECTED_REACHABLE)
                ),
                "drained_planes": sorted(
                    check_params.get("expected_drained", DEFAULT_EXPECTED_DRAINED)
                ),
                "unreachable_planes": sorted(
                    check_params.get(
                        "expected_unreachable", DEFAULT_EXPECTED_UNREACHABLE
                    )
                ),
                "plane_up": sorted(
                    check_params.get("expected_plane_up", DEFAULT_EXPECTED_PLANE_UP)
                ),
            }

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

        host_results: t.List[_HostResult] = []
        for host, collector in collectors:
            if mode in ("local_drain", "local_undrain"):
                res = _evaluate_host_local_drain(
                    host,
                    collector,
                    window_start,
                    window_end,
                    local_norms,
                    {int(p) for p in impacted_by_host.get(host, [])},
                    max_drain_sec,
                    float(disruption_ts) if disruption_ts is not None else None,
                    to_drained=(mode == "local_drain"),
                )
            elif mode == "transition":
                res = _evaluate_host_transition(
                    host,
                    collector,
                    window_start,
                    window_end,
                    target_norms,
                    {int(p) for p in impacted_by_host.get(host, [])},
                    max_transition_sec,
                    float(disruption_ts) if disruption_ts is not None else None,
                )
            else:
                res = _evaluate_host(
                    host,
                    collector,
                    window_start,
                    window_end,
                    target_norms,
                    fixed_expected,
                )
            host_results.append(res)
            self.logger.info(
                f"  [prod HRT prefix][{host}] mode={mode} VERDICT {res.status} — "
                f"S1 {'PASS' if res.s1_ok else 'FAIL'}, "
                f"S2 {'PASS' if res.s2_ok else 'FAIL'}, "
                f"{len(res.impacts)} impacted prefix(es)"
            )

        if all(r.status == "SKIP" for r in host_results):
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=(
                    "No in-window prod_hrt_prefix samples on any host "
                    f"[{window_start:.0f}, {window_end:.0f}]"
                ),
            )

        if any(r.status == "FAIL" for r in host_results):
            agg = "FAIL"
            status = hc_types.HealthCheckStatus.FAIL
        else:
            agg = "PASS"
            status = hc_types.HealthCheckStatus.PASS

        report = _format_report(host_results, agg)
        details = await everpaste_details_suffix(
            "Prod HRT prefix stability — full per-host report",
            report.splitlines(),
            collectors=[c for _host, c in collectors],
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
