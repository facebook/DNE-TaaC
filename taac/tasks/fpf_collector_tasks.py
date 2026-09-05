# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Setup/teardown tasks for long-lived FPF hardening collectors.

FpfStartCollectorsTask: Starts the FSDB ribMap, HRT, and BGP RIB collectors,
    waits 2 min for baseline data collection, then registers them in the
    module-level registry. FSDB expands to all local plane GTSWs while BGP polls
    only the explicitly supplied observer GTSWs.

FpfStopCollectorsTask: Stops all collectors, withdraws prefixes, and clears
    the registry.

Prefix injection is NOT part of the setup task — it is done as a stage step
in the playbook so that the test case start time coincides with injection.

Usage in TestConfig:
    setup_tasks=[create_fpf_start_collectors_task(...)],
    teardown_tasks=[create_fpf_stop_collectors_task(...)],
"""

import asyncio
import typing as t

from taac.internal.driver.fboss_switch_internal import (
    FbossSwitchInternal,
)
from taac.libs.fpf.fpf_collector_registry import (
    clear_all,
    get_all_collectors,
    get_artifacts,
    get_check_results,
    register_collector,
)
from taac.libs.fpf.fpf_hrt_bulk_tracker import NUM_LANES
from taac.libs.fpf.fpf_stress_checks import (
    BgpRibCollector,
    FsdbRibmapCollector,
    HrtBulkCollector,
    HrtFsdbSessionCollector,
    HrtPlaneStatusCollector,
    HrtRemoteFailureCollector,
    ProdHrtPrefixCollector,
)
from taac.libs.fpf.inject_bgp_prefixes import (
    build_tip_prefix,
    expand_prefix_range,
    withdraw_prefixes,
)
from taac.tasks.base_task import BaseTask
from taac.utils.oss_taac_lib_utils import get_root_logger

logger = get_root_logger()

BASELINE_COLLECTION_SEC = 120


def _all_plane_gtsws(gtsws: t.List[str]) -> t.List[str]:
    """Expand the observer GTSW list to ALL plane GTSWs (gtsw001..gtsw{NUM_LANES})
    so the FSDB-ribMap collector observes every plane's switch, not just the
    observer subset (gtsw001/002). The naming suffix (e.g.
    ``.l1002.c087.mwg2``) is taken from the first GTSW; returns the input
    unchanged if it can't be parsed.
    """
    if not gtsws or not gtsws[0].startswith("gtsw") or "." not in gtsws[0]:
        return gtsws
    suffix = gtsws[0][gtsws[0].index(".") :]
    return [f"gtsw{i:03d}{suffix}" for i in range(1, NUM_LANES + 1)]


def _collector_gtsw_scopes(
    gtsws: t.List[str],
) -> t.Tuple[t.List[str], t.List[str]]:
    """Return ``(fsdb_gtsws, bgp_gtsws)`` for the collector task.

    FSDB ribMap needs all local plane switches plus any explicit remote-pod
    observer. BGP health checks consume only the explicitly supplied observer
    GTSWs, so polling the expanded plane list adds latency and timeout noise
    without adding coverage.
    """
    fsdb_gtsws = _all_plane_gtsws(gtsws)
    for gtsw in gtsws:
        if gtsw not in fsdb_gtsws:
            fsdb_gtsws.append(gtsw)
    return fsdb_gtsws, list(dict.fromkeys(gtsws))


class FpfStartCollectorsTask(BaseTask):
    NAME = "fpf_start_collectors"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        gtsws: t.List[str] = params["gtsws"]
        hosts: t.List[str] = params["hosts"]
        subnet_prefix: str = params.get("subnet_prefix", "5000:dd::/32")
        poll_interval_sec: float = params.get("poll_interval_sec", 5.0)
        hrt_device_ids: t.List[int] = params.get("hrt_device_ids", [0])
        hrt_plane_ids: t.List[int] = params.get("hrt_plane_ids", list(range(NUM_LANES)))
        baseline_collection_sec: int = params.get(
            "baseline_collection_sec", BASELINE_COLLECTION_SEC
        )
        # FSDB ribMap read path: "ribmap" -> bgp/ribMap (valid on current GTSWs),
        # "canonical" -> bgp/canonicalRib (newer schema; INVALID_PATH on GTSWs
        # that don't expose it yet). Default "ribmap".
        fsdb_mode: str = params.get("fsdb_mode", "ribmap")
        # When True, postcheck lane assertions exclude lanes already impaired at
        # precheck (baseline) — a failure on a known-degraded lab lane is
        # PRE-EXISTING, not a test regression, so the test can pass on the
        # healthy + test-impacted lanes. Set in the registry for the checks.
        from taac.libs.fpf.fpf_collector_registry import (
            set_allow_baseline_failures,
        )

        set_allow_baseline_failures(bool(params.get("allow_baseline_failures", False)))

        # FSDB-ribMap observes ALL plane GTSWs (not just the observer subset
        # gtsw001/002) so every plane's switch is tracked.
        # _all_plane_gtsws() expands only gtsws[0]'s pod suffix (e.g. .l1002),
        # so any explicitly-listed observer in a DIFFERENT pod (e.g. the
        # remote-pod observer gtsw001.l1001) must be unioned back in — otherwise
        # the collector never polls it and its FSDB/BGP-RIB convergence check
        # reads "no data collected" (FAIL) even though the switch is healthy.
        # BGP is intentionally narrower: its HCs consume only the supplied
        # observer GTSWs. Polling all plane switches serialized unnecessary
        # 30-second RPC deadlines into an otherwise healthy TC41 window.
        fsdb_gtsws, bgp_gtsws = _collector_gtsw_scopes(gtsws)
        logger.info(
            f"[FpfStartCollectors] Starting collectors: FSDB over "
            f"{len(fsdb_gtsws)} plane/observer GTSWs, BGP over "
            f"{len(bgp_gtsws)} supplied observer GTSWs, "
            f"HRT over {len(hosts)} hosts"
        )

        fsdb_collector = FsdbRibmapCollector(
            gtsws=fsdb_gtsws,
            subnet_prefix=subnet_prefix,
            interval_sec=poll_interval_sec,
            fsdb_mode=fsdb_mode,
        )
        fsdb_collector.set_append_mode(True)

        hrt_collector = HrtBulkCollector(
            hosts=hosts,
            device_ids=hrt_device_ids,
            plane_ids=hrt_plane_ids,
            supernet=subnet_prefix,
            interval_sec=poll_interval_sec,
        )
        hrt_collector.set_append_mode(True)

        bgp_collector = BgpRibCollector(
            gtsws=bgp_gtsws,
            subnet_prefix=subnet_prefix,
            interval_sec=poll_interval_sec,
        )
        bgp_collector.set_append_mode(True)

        fsdb_collector.start()
        hrt_collector.start()
        hrt_remote_failure_collector = HrtRemoteFailureCollector(
            hosts=hosts,
            device_ids=hrt_device_ids,
            plane_ids=hrt_plane_ids,
            supernet=subnet_prefix,
            interval_sec=poll_interval_sec,
        )
        hrt_remote_failure_collector.set_append_mode(True)

        bgp_collector.start()
        hrt_remote_failure_collector.start()

        register_collector("fsdb", fsdb_collector)
        register_collector("hrt", hrt_collector)
        register_collector("bgp", bgp_collector)
        register_collector("hrt_remote_failure", hrt_remote_failure_collector)

        # Per-VF-group remote-failure collectors (8-STSW split-per-VF injection).
        # Each VF group's prefixes are reachable only on its own planes, so on the
        # OTHER group's planes they show as (expected) remote-failures. To assert
        # each group has zero remote-failure on its OWN lanes, start a per-group
        # collector with the group's NARROW subnet (e.g. 5000:dd::/32 for VF1),
        # registered as "hrt_remote_failure_<suffix>". The per-group remote-failure
        # checks (scoped to the group's lanes) target these by collector name.
        rf_vf_groups: t.List[t.Dict[str, t.Any]] = params.get("rf_vf_groups", []) or []
        for group in rf_vf_groups:
            suffix = group["suffix"]
            group_subnet = group["subnet"]
            group_rf_collector = HrtRemoteFailureCollector(
                hosts=hosts,
                device_ids=group.get("device_ids", [0]),
                plane_ids=hrt_plane_ids,
                supernet=group_subnet,
                interval_sec=poll_interval_sec,
            )
            group_rf_collector.set_append_mode(True)
            group_rf_collector.start()
            register_collector(f"hrt_remote_failure_{suffix}", group_rf_collector)
            logger.info(
                f"[FpfStartCollectors] Per-VF-group remote-failure collector "
                f"'hrt_remote_failure_{suffix}' started (subnet {group_subnet}, "
                f"devices {group.get('device_ids', [0])})"
            )

        # HRT FSDB-session-count collector (getFsdbSessions CONNECTED census):
        # tracks the per-host CONNECTED session count + per-lane breakdown for
        # the FpfHrtSessionStatHealthCheck (disruption / stable contracts). HRT
        # runs only on rtptest GPU hosts. Enabled by default when GPU hosts are
        # present; mirrors how prod_hrt_prefix is conditionally started. Polls
        # every 3s (independent of poll_interval_sec) so a sub-minute drop +
        # recovery is captured. One collector keyed off the monitored GPU host.
        enable_fsdb_session = bool(params.get("enable_fsdb_session_collector", True))
        gpu_hosts = [
            h
            for h in hosts
            if str(h).startswith("rtptest") or str(h).startswith("twshared")
        ]
        if enable_fsdb_session and gpu_hosts:
            session_poll_sec: float = float(
                params.get("fsdb_session_poll_interval_sec", 3.0)
            )
            session_expected: int = int(params.get("fsdb_session_expected", 32))
            # ONE collector holds ALL monitored GPU hosts (each row carries its
            # host, one file with a host column). ``fsdb_session_hosts`` (opt-in)
            # selects which hosts to monitor; default is all GPU hosts.
            # FpfHrtSessionStatHealthCheck reads this single collector and
            # iterates its hosts internally, asserting each meets the census.
            session_hosts: t.List[str] = params.get("fsdb_session_hosts") or gpu_hosts
            fsdb_session_collector = HrtFsdbSessionCollector(
                hosts=session_hosts,
                expected_connected=session_expected,
                interval_sec=session_poll_sec,
            )
            fsdb_session_collector.set_append_mode(True)
            fsdb_session_collector.start()
            register_collector("hrt_fsdb_session", fsdb_session_collector)
            logger.info(
                f"[FpfStartCollectors] HRT FSDB-session collector started on "
                f"{session_hosts} (expected {session_expected} CONNECTED, "
                f"poll {session_poll_sec:.0f}s)"
            )

        # Production-prefix reachability collector. This remains an explicitly
        # selected single-device canary, not whole-host device coverage. Each
        # host monitors its configured query prefixes via ``prefixes_by_host``;
        # multiple hosts may observe the same route. Wiring inputs:
        #
        #   ``prod_prefixes_by_host`` ({host: [prefixes]}): the per-host query
        #     map, preferred. Every host in the map is monitored.
        #   Legacy (``prod_prefixes`` + ``prod_prefix_host``): a single host's
        #     prefixes, folded into a one-entry prefixes_by_host map.
        #
        # FpfProdHrtPrefixStabilityHealthCheck reads the single collector and
        # iterates its hosts internally.
        prod_device_id: int = params.get("prod_prefix_device_id", 0)
        prod_by_host: t.Dict[str, t.List[str]] = (
            params.get("prod_prefixes_by_host") or {}
        )
        if not prod_by_host:
            prod_prefixes: t.List[str] = params.get("prod_prefixes", [])
            if prod_prefixes:
                prod_host: str = params.get(
                    "prod_prefix_host", hosts[0] if hosts else ""
                )
                prod_by_host = {prod_host: prod_prefixes}
        # Drop hosts with no prefixes, and guard against an empty host key: the
        # legacy fallback yields "" when no hosts were supplied, which would
        # otherwise build ProdHrtPrefixCollector(hosts=[""]) / get_hrt_client("").
        dropped = [h for h, p in prod_by_host.items() if p and not h]
        if dropped:
            logger.warning(
                "[FpfStartCollectors] dropping prod-prefix entry with empty host "
                "key (no hosts supplied and no prod_prefix_host given)"
            )
        prod_by_host = {h: p for h, p in prod_by_host.items() if p and h}
        if prod_by_host:
            prod_hosts = list(prod_by_host.keys())
            prod_collector = ProdHrtPrefixCollector(
                hosts=prod_hosts,
                device_id=prod_device_id,
                prefixes_by_host=prod_by_host,
                interval_sec=poll_interval_sec,
            )
            prod_collector.set_append_mode(True)
            prod_collector.start()
            register_collector("prod_hrt_prefix", prod_collector)

            logger.info(
                f"[FpfStartCollectors] Production-prefix dev{prod_device_id} canary "
                f"started on {prod_hosts} dev{prod_device_id} "
                f"({sum(len(p) for p in prod_by_host.values())} prefix(es) total)"
            )

        # Plane-status is whole-host topology coverage, independent of the
        # production-prefix dev0 canary. New paired-device MWG2 uses dev0..7,
        # each with local planes 0..3; the legacy default remains dev0/planes0..7.
        if gpu_hosts:
            plane_status_collector = HrtPlaneStatusCollector(
                hosts=gpu_hosts,
                device_ids=hrt_device_ids,
                interval_sec=poll_interval_sec,
                num_planes=len(hrt_plane_ids),
            )
            plane_status_collector.set_append_mode(True)
            plane_status_collector.start()
            register_collector("hrt_plane_status", plane_status_collector)
            logger.info(
                f"[FpfStartCollectors] HRT plane-status collector started on "
                f"{gpu_hosts}, devices={hrt_device_ids}"
            )

        logger.info(
            f"[FpfStartCollectors] Collectors started. Waiting "
            f"{baseline_collection_sec}s for baseline data collection"
        )
        await asyncio.sleep(baseline_collection_sec)
        logger.info(
            "[FpfStartCollectors] Baseline collection complete, ready for test cases"
        )


class FpfStopCollectorsTask(BaseTask):
    NAME = "fpf_stop_collectors"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        trigger_stsws: t.List[str] = params["trigger_stsws"]
        prefix_count: int = params.get("prefix_count", 70000)
        prefix_base: str = params.get("prefix_base", "5000:dd::/64")
        increment_step: str = params.get("increment_step", "0:0:1::")
        # When False, only stop the collectors — prefixes are cleared elsewhere
        # (e.g. an 8-STSW config that restarts bgpd at teardown).
        withdraw: bool = params.get("withdraw", True)
        # community_list is currently unused — withdraw_prefixes() doesn't
        # take it. Keep params.get() so callers can still pass it without
        # KeyError, but discard the value.
        _ = params.get("community_list", "stsw")

        collectors = get_all_collectors()

        try:
            for name, collector in collectors.items():
                logger.info(f"[FpfStopCollectors] Stopping {name} collector")
                try:
                    await asyncio.wait_for(collector.stop(), timeout=15)
                except asyncio.TimeoutError:
                    logger.error(
                        f"[FpfStopCollectors] {name}.stop() exceeded 15s — "
                        f"moving on; daemon thread will die with parent process"
                    )

            if withdraw and prefix_count > 0:
                prefix_strs = expand_prefix_range(
                    prefix_base, prefix_count, increment_step
                )
                tip_prefixes = [build_tip_prefix(p) for p in prefix_strs]

                logger.info(
                    f"[FpfStopCollectors] Withdrawing {prefix_count} prefixes "
                    f"from {len(trigger_stsws)} STSW devices"
                )

                async def _withdraw_on_device(device: str) -> None:
                    driver = FbossSwitchInternal(hostname=device, logger=self.logger)
                    await withdraw_prefixes(driver, tip_prefixes)

                await asyncio.gather(*[_withdraw_on_device(d) for d in trigger_stsws])
            else:
                logger.info(
                    "[FpfStopCollectors] withdraw=False — collectors stopped only; "
                    "prefixes cleared elsewhere (e.g. bgpd restart at teardown)"
                )
        finally:
            await self._emit_artifacts_summary()
            clear_all()
        logger.info("[FpfStopCollectors] All collectors stopped, prefixes withdrawn")

    async def _emit_artifacts_summary(self) -> None:
        """Emit the single consolidated FPF test-case summary at teardown.

        ONE Everpaste (and one log block) containing BOTH:
          1. the FAILURE TRIAGE table (every check's verdict / class / reason), and
          2. the DEBUG ARTIFACTS table (every collector per-poll Everpaste link and
             every ODS query link generated during the test case).

        This is the "single place" to start any FPF failure investigation — no
        scrolling the per-check log lines. Best-effort; never raises."""
        try:
            triage_table = self._build_triage_table()  # may be ""
            artifacts = get_artifacts()
            artifacts_table = self._build_artifacts_table(artifacts)  # may be ""

            blocks = [b for b in (triage_table, artifacts_table) if b]
            if not blocks:
                return
            body = "\n\n".join(blocks)
            # Log both tables inline so they're visible without opening a link.
            logger.info("\n" + body)

            from taac.utils.common import (
                async_everpaste_str,
                async_get_fburl,
            )

            try:
                summary_url = await async_get_fburl(
                    await async_everpaste_str(body, color=0)
                )
                logger.warning(
                    f"[FpfStopCollectors] ⭐ FPF TEST-CASE SUMMARY "
                    f"({len(artifacts)} artifact link(s)) — triage + all "
                    f"collector/ODS links in one place: {summary_url}"
                )
            except Exception as e:
                logger.warning(f"[FpfStopCollectors] summary everpaste failed: {e}")
        except Exception as e:
            logger.warning(f"[FpfStopCollectors] test-case summary skipped: {e}")

    def _build_triage_table(self) -> str:
        """Build the FAILURE TRIAGE table (every link-event health check's
        verdict, reason, and classification: OK / NEW regression / PRE-EXISTING
        baseline / INCONCLUSIVE disruption / SKIP). Returns "" if no results."""
        results = get_check_results()
        if not results:
            return ""
        # Sort so failures/regressions float to the top, OK sinks to the bottom.
        order = {
            "NEW": 0,
            "INCONCLUSIVE": 1,
            "PRE-EXISTING": 2,
            "SKIP": 3,
            "OK": 4,
        }
        results = sorted(results, key=lambda r: order.get(r[3], 9))
        lines = [
            "FPF FAILURE TRIAGE",
            "=" * 100,
            f"{'CHECK':<40}  {'VERDICT':<8}  {'CLASS':<13}  REASON",
            "-" * 100,
        ]
        for name, status, reason, classification in results:
            reason_short = (reason or "")[:60]
            lines.append(
                f"{name[:40]:<40}  {status:<8}  {classification:<13}  {reason_short}"
            )
        n_new = sum(1 for r in results if r[3] == "NEW")
        n_pre = sum(1 for r in results if r[3] == "PRE-EXISTING")
        n_inc = sum(1 for r in results if r[3] == "INCONCLUSIVE")
        lines.append("-" * 100)
        lines.append(
            f"Totals: {len(results)} checks — {n_new} NEW (regression), "
            f"{n_pre} PRE-EXISTING (baseline), {n_inc} INCONCLUSIVE (disruption)"
        )
        if n_new:
            logger.warning(
                f"[FpfStopCollectors] FPF TRIAGE: {n_new} NEW regression(s) — "
                f"see FPF TEST-CASE SUMMARY"
            )
        return "\n".join(lines)

    def _build_artifacts_table(self, artifacts: t.List[t.Tuple[str, str, str]]) -> str:
        """Build the DEBUG ARTIFACTS table — every collector per-poll Everpaste
        link and every ODS query link generated during the test case. Returns ""
        if nothing was registered."""
        if not artifacts:
            return ""
        lines = [
            "FPF TEST-CASE DEBUG ARTIFACTS (collector Everpaste + ODS query links)",
            "=" * 80,
            f"{'CATEGORY':<12}  {'LABEL':<48}  URL",
            "-" * 80,
        ]
        for category, label, url in artifacts:
            lines.append(f"{category:<12}  {label:<48}  {url}")
        return "\n".join(lines)


class FpfWithdrawStalePrefixesTask(BaseTask):
    """Setup task: withdraw any leftover synthetic test prefixes before injection.

    Runs ONCE at the head of ``setup_tasks`` (before collectors and before the
    playbooks' injection steps) to guarantee a clean ``5000:dd`` baseline. The
    pollution it clears comes from a PRIOR run whose teardown never executed —
    most commonly a run killed mid-flight — leaving its injected prefixes in the
    STSW BGP RIB. Those leftovers fail ``FPF_STALE_PREFIX_CHECK`` and skew the
    exact-count convergence checks (notably the scale tests).

    Withdraws a SUPERSET (``prefix_count`` defaults to 70000 — ≥ the max any FPF
    config injects, incl. the 70000-prefix v1 hardening configs; same scale the
    teardown ``fpf_stop_collectors`` already withdraws) of ``prefix_base`` on
    every trigger STSW, so it clears residue from prior scale/hardening runs too.
    Idempotent: withdrawing prefixes that are not present is a no-op
    (``delNetworks`` on absent prefixes).
    """

    NAME = "fpf_withdraw_stale_prefixes"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        trigger_stsws: t.List[str] = params["trigger_stsws"]
        prefix_count: int = params.get("prefix_count", 70000)
        prefix_base: str = params.get("prefix_base", "5000:dd::/64")
        increment_step: str = params.get("increment_step", "0:0:1::")

        prefix_strs = expand_prefix_range(prefix_base, prefix_count, increment_step)
        tip_prefixes = [build_tip_prefix(p) for p in prefix_strs]

        logger.info(
            f"[FpfWithdrawStalePrefixes] clean-slate: withdrawing up to "
            f"{prefix_count} {prefix_base} prefixes from {len(trigger_stsws)} "
            f"STSW device(s) before injection"
        )

        async def _withdraw_on_device(device: str) -> None:
            driver = FbossSwitchInternal(hostname=device, logger=self.logger)
            await withdraw_prefixes(driver, tip_prefixes)

        await asyncio.gather(*[_withdraw_on_device(d) for d in trigger_stsws])
        logger.info(
            "[FpfWithdrawStalePrefixes] clean-slate withdraw complete on "
            f"{trigger_stsws}"
        )
