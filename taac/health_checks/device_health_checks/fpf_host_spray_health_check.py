# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""FPF host-spray ODS health check (per-lane RDMA egress fairness).

For each traffic host, queries the per-lane NIC tx rate (beth0-3) over the test
window and asserts two signals:

  Signal 1 (egress floor): every lane's average egress exceeds a minimum
    (default from fpf_thresholds.ACTIVE.host_spray_min_egress_gbps — 75 Gbps
    temporary / 90 Gbps expected). Confirms the host is actually pushing traffic
    on all lanes.

  Signal 2 (spray fairness): within a host, the spread between the busiest and
    quietest lane (max - min across beth0-3) stays within a bound (default
    fpf_thresholds.ACTIVE.host_spray_max_spread_gbps — 2 Gbps). This is the
    spraying-fairness signal: a host spraying evenly keeps all lanes close.

Metric (ODS), per host, FOUR time series (one per lane):
    key:       regex(system.beth[0123].tx-bytes-phy.rate)   (bytes/s per lane)
    transform: formula(/ $1 125000000),avg(1m),latest      (bytes/s -> Gbps, latest 1m avg)
    (no reduce — we want each lane separately, not a per-host sum)

Window: test-case start time -> now (overridable). The check builds a
host -> {lane -> avg Gbps} map, logs every value and the ODS URL, and FAILs if
either signal is violated on any host.
"""

import re
import time
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.internal.ods_utils import (
    async_generate_ods_url,
    async_query_ods,
)
from taac.libs.fpf.fpf_collector_registry import (
    baseline_impaired_lane_union,
    disruption_inconclusive_skip,
    get_allow_baseline_failures,
    get_test_case_start_time,
    register_artifact,
)
from taac.libs.fpf.fpf_thresholds import ACTIVE
from taac.utils.common import async_get_fburl
from taac.health_check.health_check import types as hc_types

DEFAULT_KEY_DESC = "regex(system.beth[0123].tx-bytes-phy.rate)"
DEFAULT_TRANSFORM_DESC = "formula(/ $1 125000000),avg(1m),latest"
DEFAULT_LOOKBACK_SEC = 900

_LANE_RE = re.compile(r"(beth\d+)")


def _lane_label(key_name: str) -> str:
    """Extract the lane label (e.g. beth0) from an ODS key, else the key."""
    m = _LANE_RE.search(key_name)
    return m.group(1) if m else key_name


class FpfHostSprayHealthCheck(AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]):
    """Postcheck: per-lane RDMA egress floor + spray fairness across beth0-3.

    check_params:
        hosts (List[str]) | entity_desc (str): traffic hosts to query.
        key_desc / transform_desc: ODS query overrides.
        min_egress_gbps (float): Signal 1 floor. Default ACTIVE threshold.
        max_spread_gbps (float): Signal 2 max per-host lane spread. Default
            ACTIVE threshold.
        lookback_sec / window_start / window_end: window overrides.
    """

    CHECK_NAME = hc_types.CheckName.FPF_HOST_SPRAY_CHECK
    CHECK_SCOPE = hc_types.Scope.DEFAULT
    OPERATING_SYSTEMS = ["FBOSS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        hosts = check_params.get("hosts")
        entity_desc = check_params.get("entity_desc")
        if entity_desc is None:
            if hosts:
                entity_desc = ",".join(hosts)
            elif obj is not None:
                entity_desc = obj.name
            else:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.SKIP,
                    message="No hosts/entity_desc provided for host-spray check",
                )

        key_desc = check_params.get("key_desc", DEFAULT_KEY_DESC)
        transform_desc = check_params.get("transform_desc", DEFAULT_TRANSFORM_DESC)
        reduce_desc = check_params.get("reduce_desc", "")
        min_egress_gbps = float(
            check_params.get("min_egress_gbps", ACTIVE.host_spray_min_egress_gbps)
        )
        max_spread_gbps = float(
            check_params.get("max_spread_gbps", ACTIVE.host_spray_max_spread_gbps)
        )
        # Link-event: impacted lanes (beth labels) per host whose egress must be
        # BELOW impacted_max_gbps (their link is disabled/drained, so traffic
        # has moved off them). Signal 1 (floor) + Signal 2 (spread) are then
        # evaluated over the UNIMPACTED lanes only. Empty => stable-state.
        impacted_by_host: t.Dict[str, t.List[str]] = (
            check_params.get("impacted_lanes_by_host", {}) or {}
        )
        impacted_max_gbps = float(check_params.get("impacted_max_gbps", 10.0))
        if impacted_by_host:
            _skip = disruption_inconclusive_skip()
            if _skip:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.SKIP, message=_skip
                )

        window_end = float(check_params.get("window_end", time.time()))
        tc_start = get_test_case_start_time()
        lookback_sec = check_params.get("lookback_sec", DEFAULT_LOOKBACK_SEC)
        window_start = float(
            check_params.get(
                "window_start", tc_start if tc_start else window_end - lookback_sec
            )
        )
        start_time = int(window_start)
        end_time = int(window_end)

        self.logger.info(
            f"  [host spray] Querying ODS for {entity_desc} key={key_desc} "
            f"transform={transform_desc} window {start_time} to {end_time} "
            f"({end_time - start_time}s); floor>{min_egress_gbps:.1f} Gbps, "
            f"spread<={max_spread_gbps:.1f} Gbps"
        )

        ods_data = await async_query_ods(
            entity_desc=entity_desc,
            key_desc=key_desc,
            reduce_desc=reduce_desc,
            transform_desc=transform_desc,
            start_time=start_time,
            end_time=end_time,
        )
        raw_url = await async_generate_ods_url(
            entity_desc=entity_desc,
            key_desc=key_desc,
            reduce_desc=reduce_desc,
            transform_desc=transform_desc,
            start_time=start_time,
            end_time=end_time,
        )
        ods_url = await async_get_fburl(raw_url)
        register_artifact("ods", "host spray (beth tx egress)", ods_url)

        if not ods_data:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=f"No ODS data for host-spray check. URL: {ods_url}",
            )

        # Build host -> {lane -> avg Gbps}, taking each lane's latest sample.
        host_lanes: t.Dict[str, t.Dict[str, float]] = {}
        for entity, key_data in sorted(ods_data.items()):
            lanes: t.Dict[str, float] = {}
            for key_name, ts_data in key_data.items():
                if not ts_data:
                    continue
                latest_ts = max(ts_data.keys())
                lanes[_lane_label(key_name)] = ts_data[latest_ts]
            if lanes:
                host_lanes[entity] = lanes

        if not host_lanes:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=f"No host-spray lane samples in window. URL: {ods_url}",
            )

        # Log the full host -> lane -> egress map.
        for host in sorted(host_lanes):
            lanes = host_lanes[host]
            lane_str = ", ".join(f"{lane}={lanes[lane]:.2f}" for lane in sorted(lanes))
            vmax, vmin = max(lanes.values()), min(lanes.values())
            self.logger.info(
                f"  [host spray] {host}: {lane_str} Gbps "
                f"(min={vmin:.2f}, max={vmax:.2f}, spread={vmax - vmin:.2f})"
            )

        # Signal 1 (floor) + Signal 2 (spread) over UNIMPACTED lanes; impacted
        # lanes must instead be BELOW impacted_max_gbps.
        s1_violations: t.List[str] = []
        s2_violations: t.List[str] = []
        impacted_violations: t.List[str] = []
        impacted_ok_notes: t.List[str] = []
        # Baseline exclusion: drop beths for lanes already impaired at precheck
        # when the config opted in (a dead lab lane is PRE-EXISTING, not a
        # spray regression) — excluded from floor, spread, and impacted checks.
        baseline_beths: t.Set[str] = set()
        if get_allow_baseline_failures():
            baseline_beths = {f"beth{lane}" for lane in baseline_impaired_lane_union()}
            if baseline_beths:
                self.logger.info(
                    f"  [host spray] excluding baseline-impaired beths "
                    f"{sorted(baseline_beths)}"
                )
        for host in sorted(host_lanes):
            host_impacted = set(impacted_by_host.get(host, []))
            unimpacted_vals: t.List[float] = []
            for lane in sorted(host_lanes[host]):
                if lane in baseline_beths:
                    continue
                val = host_lanes[host][lane]
                if lane in host_impacted:
                    if val >= impacted_max_gbps:
                        impacted_violations.append(
                            f"{host}/{lane}={val:.2f} >= {impacted_max_gbps:.1f} "
                            f"(expected drained)"
                        )
                    else:
                        impacted_ok_notes.append(
                            f"{host}/{lane}={val:.2f} < {impacted_max_gbps:.1f}"
                        )
                    continue
                unimpacted_vals.append(val)
                if val <= min_egress_gbps:
                    s1_violations.append(
                        f"{host}/{lane}={val:.2f} <= {min_egress_gbps:.1f}"
                    )
            # Impacted lanes that produced no egress series at all are also fine
            # (a down link emits nothing) — note them for visibility.
            for lane in sorted(host_impacted - set(host_lanes[host])):
                impacted_ok_notes.append(f"{host}/{lane}=absent (no egress)")
            if len(unimpacted_vals) >= 2:
                spread = max(unimpacted_vals) - min(unimpacted_vals)
                if spread > max_spread_gbps:
                    s2_violations.append(
                        f"{host} spread={spread:.2f} > {max_spread_gbps:.1f} "
                        f"(unimpacted lanes)"
                    )

        s1_ok = not s1_violations
        s2_ok = not s2_violations
        s3_ok = not impacted_violations
        self.logger.info(
            f"  [host spray] Signal 1 (egress floor >{min_egress_gbps:.1f} Gbps, "
            f"unimpacted): [{'PASS' if s1_ok else 'FAIL'}]"
            + ("" if s1_ok else "; " + "; ".join(s1_violations))
        )
        self.logger.info(
            f"  [host spray] Signal 2 (lane spread <={max_spread_gbps:.1f} Gbps, "
            f"unimpacted): [{'PASS' if s2_ok else 'FAIL'}]"
            + ("" if s2_ok else "; " + "; ".join(s2_violations))
        )
        if impacted_by_host:
            self.logger.info(
                f"  [host spray] Signal 3 (impacted lanes <{impacted_max_gbps:.1f} "
                f"Gbps): [{'PASS' if s3_ok else 'FAIL'}] "
                + (
                    "; ".join(impacted_ok_notes)
                    if s3_ok
                    else "; ".join(impacted_violations)
                )
            )

        if s1_ok and s2_ok and s3_ok:
            extra = (
                f", {len(impacted_ok_notes)} impacted lane(s) <{impacted_max_gbps:.1f} Gbps"
                if impacted_by_host
                else ""
            )
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.PASS,
                message=(
                    f"Host spray OK for {len(host_lanes)} host(s): unimpacted lanes "
                    f">{min_egress_gbps:.1f} Gbps, spread <={max_spread_gbps:.1f} "
                    f"Gbps{extra} | ODS: {ods_url}"
                ),
            )
        parts: t.List[str] = []
        if not s1_ok:
            parts.append("Signal 1 (egress floor) FAILED — " + "; ".join(s1_violations))
        if not s2_ok:
            parts.append(
                "Signal 2 (spray fairness) FAILED — " + "; ".join(s2_violations)
            )
        if not s3_ok:
            parts.append(
                "Signal 3 (impacted-lane drain) FAILED — "
                + "; ".join(impacted_violations)
            )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.FAIL,
            message=" | ".join(parts) + f" | ODS: {ods_url}",
        )
