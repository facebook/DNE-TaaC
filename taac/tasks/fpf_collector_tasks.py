# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Setup/teardown tasks for long-lived FPF hardening collectors.

FpfStartCollectorsTask: Starts 3 collectors (FSDB ribMap, HRT bulk, BGP RIB),
    waits 2 min for baseline data collection, then registers collectors in the
    module-level registry so health checks can query them.

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


class FpfStartCollectorsTask(BaseTask):
    NAME = "fpf_start_collectors"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        gtsws: t.List[str] = params["gtsws"]
        hosts: t.List[str] = params["hosts"]
        subnet_prefix: str = params.get("subnet_prefix", "5000:dd::/32")
        poll_interval_sec: float = params.get("poll_interval_sec", 5.0)
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

        logger.info(
            f"[FpfStartCollectors] Starting collectors for {len(gtsws)} GTSWs, "
            f"{len(hosts)} hosts"
        )

        fsdb_collector = FsdbRibmapCollector(
            gtsws=gtsws,
            subnet_prefix=subnet_prefix,
            interval_sec=poll_interval_sec,
            fsdb_mode=fsdb_mode,
        )
        fsdb_collector.set_append_mode(True)

        hrt_collector = HrtBulkCollector(
            hosts=hosts,
            supernet=subnet_prefix,
            interval_sec=poll_interval_sec,
        )
        hrt_collector.set_append_mode(True)

        bgp_collector = BgpRibCollector(
            gtsws=gtsws,
            subnet_prefix=subnet_prefix,
            interval_sec=poll_interval_sec,
        )
        bgp_collector.set_append_mode(True)

        fsdb_collector.start()
        hrt_collector.start()
        hrt_remote_failure_collector = HrtRemoteFailureCollector(
            hosts=hosts,
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

        # HRT FSDB-session-count collector (getFsdbSessions CONNECTED census):
        # tracks the per-host CONNECTED session count + per-lane breakdown for
        # the FpfHrtSessionStatHealthCheck (disruption / stable contracts). HRT
        # runs only on rtptest GPU hosts. Enabled by default when GPU hosts are
        # present; mirrors how prod_hrt_prefix is conditionally started. Polls
        # every 3s (independent of poll_interval_sec) so a sub-minute drop +
        # recovery is captured. One collector keyed off the monitored GPU host.
        enable_fsdb_session = bool(params.get("enable_fsdb_session_collector", True))
        gpu_hosts = [h for h in hosts if str(h).startswith("rtptest")]
        if enable_fsdb_session and gpu_hosts:
            session_host: str = params.get("fsdb_session_host", gpu_hosts[0])
            session_poll_sec: float = float(
                params.get("fsdb_session_poll_interval_sec", 3.0)
            )
            session_expected: int = int(params.get("fsdb_session_expected", 32))
            fsdb_session_collector = HrtFsdbSessionCollector(
                host=session_host,
                expected_connected=session_expected,
                interval_sec=session_poll_sec,
            )
            fsdb_session_collector.set_append_mode(True)
            fsdb_session_collector.start()
            register_collector("hrt_fsdb_session", fsdb_session_collector)
            logger.info(
                f"[FpfStartCollectors] HRT FSDB-session collector started on "
                f"{session_host} (expected {session_expected} CONNECTED, "
                f"poll {session_poll_sec:.0f}s)"
            )

        # Optional: production-prefix reachability collector. Only started when
        # the caller supplies prod_prefixes (list) + the host + GPU device_id —
        # the collector never assumes all GPUs. Monitors steady-state per-prefix
        # reachability for the reachability-stability postcheck.
        prod_prefixes: t.List[str] = params.get("prod_prefixes", [])
        if prod_prefixes:
            prod_host: str = params.get("prod_prefix_host", hosts[0] if hosts else "")
            prod_device_id: int = params.get("prod_prefix_device_id", 0)
            prod_collector = ProdHrtPrefixCollector(
                host=prod_host,
                device_id=prod_device_id,
                prefixes=prod_prefixes,
                interval_sec=poll_interval_sec,
            )
            prod_collector.set_append_mode(True)
            prod_collector.start()
            register_collector("prod_hrt_prefix", prod_collector)
            logger.info(
                f"[FpfStartCollectors] Production-prefix collector started on "
                f"{prod_host} dev{prod_device_id} for {len(prod_prefixes)} prefix(es)"
            )

            # Device-level HRT plane-status collector (hrtctl show plane-status):
            # tracks per-plane Up/Drained state on the same monitored GPU device.
            # Consumed by FpfHrtPlaneStatusHealthCheck (all_up / drain contracts).
            plane_status_collector = HrtPlaneStatusCollector(
                host=prod_host,
                device_id=prod_device_id,
                interval_sec=poll_interval_sec,
            )
            plane_status_collector.set_append_mode(True)
            plane_status_collector.start()
            register_collector("hrt_plane_status", plane_status_collector)
            logger.info(
                f"[FpfStartCollectors] HRT plane-status collector started on "
                f"{prod_host} dev{prod_device_id}"
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

            prefix_strs = expand_prefix_range(prefix_base, prefix_count, increment_step)
            tip_prefixes = [build_tip_prefix(p) for p in prefix_strs]

            logger.info(
                f"[FpfStopCollectors] Withdrawing {prefix_count} prefixes "
                f"from {len(trigger_stsws)} STSW devices"
            )

            async def _withdraw_on_device(device: str) -> None:
                driver = FbossSwitchInternal(hostname=device, logger=self.logger)
                await withdraw_prefixes(driver, tip_prefixes)

            await asyncio.gather(*[_withdraw_on_device(d) for d in trigger_stsws])
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
