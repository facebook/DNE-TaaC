# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""
FPF Continuous Collector Step for TAAC.

Runs three continuous-polling collectors (FSDB ribMap, HRT bulk,
BGP RIB) as background asyncio tasks for a configurable duration,
then evaluates convergence results per-device and per-lane.
"""

import asyncio
import os
import time
import typing as t
from datetime import datetime, timezone

from taac.libs.fpf.fpf_stress_checks import (
    BgpRibCollector,
    FsdbRibmapCollector,
    HrtBulkCollector,
    lanes_to_gtsws,
    PerLaneResult,
)
from taac.steps.step import Step
from taac.test_as_a_config import types as taac_types


class FpfContinuousCollectorStep(Step[taac_types.BaseInput]):
    STEP_NAME = taac_types.StepName.FPF_CONTINUOUS_COLLECTOR_STEP

    def __init__(self, *args: t.Any, **kwargs: t.Any) -> None:
        super().__init__(*args, **kwargs)
        self.gtsws: t.List[str] = []
        self.hosts: t.List[str] = []
        self.subnet_prefix: str = ""
        self.poll_interval_sec: float = 2.0
        self.collection_duration_sec: int = 0
        self.lanes: t.List[int] = []
        self.fsdb_expected: int = 20000
        self.bgp_expected: int = 20000
        self.hrt_thresholds: t.Dict[int, int] = {}
        self.trigger_delay_sec: float = 0.0

    async def setUp(
        self,
        input: taac_types.BaseInput,
        params: t.Dict[str, t.Any],
    ) -> None:
        # Parse params from step_params dict
        self.gtsws = params["gtsws"]
        self.hosts = params["hosts"]
        self.subnet_prefix = params["subnet_prefix"]
        self.poll_interval_sec = params.get("poll_interval_sec", 2.0)
        self.collection_duration_sec = params["collection_duration_sec"]
        self.lanes = params["lanes"]
        self.fsdb_expected = params.get("fsdb_expected", 20000)
        self.bgp_expected = params.get("bgp_expected", 20000)
        self.hrt_thresholds = {
            int(k): v for k, v in params.get("hrt_thresholds", {}).items()
        }
        self.trigger_delay_sec = params.get("trigger_delay_sec", 0.0)

    async def run(
        self,
        input: taac_types.BaseInput,
        params: t.Dict[str, t.Any],
    ) -> None:
        step_start_time = time.time()

        # Clear stale collector files from previous runs
        for path in [
            "/tmp/fpf_stress_fsdb_ribmap.log",
            "/tmp/fpf_stress_fsdb_ribmap.jsonl",
            "/tmp/fpf_stress_hrt_bulk.log",
            "/tmp/fpf_stress_hrt_bulk.jsonl",
            "/tmp/fpf_stress_bgp_rib.log",
            "/tmp/fpf_stress_bgp_rib.jsonl",
        ]:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass

        # Instantiate collectors
        fsdb_collector = FsdbRibmapCollector(
            gtsws=self.gtsws,
            subnet_prefix=self.subnet_prefix,
            interval_sec=self.poll_interval_sec,
        )
        hrt_collector = HrtBulkCollector(
            hosts=self.hosts,
            supernet=self.subnet_prefix,
            interval_sec=self.poll_interval_sec,
        )
        bgp_collector = BgpRibCollector(
            gtsws=self.gtsws,
            subnet_prefix=self.subnet_prefix,
            interval_sec=self.poll_interval_sec,
        )

        # Start all collectors (they run as asyncio background tasks)
        self.logger.info(
            f"Starting 3 continuous collectors for {self.collection_duration_sec}s "
            f"(poll interval {self.poll_interval_sec}s)"
        )
        fsdb_collector.start()
        hrt_collector.start()
        bgp_collector.start()

        # Sleep for the collection duration, logging progress every 60s
        total = self.collection_duration_sec
        total_min = total // 60
        self.logger.info(
            f"Collecting for {total_min}m ({total}s) — progress logged every 60s"
        )
        elapsed = 0
        while elapsed < total:
            chunk = min(60, total - elapsed)
            await asyncio.sleep(chunk)
            elapsed += chunk
            remaining = max(0, total - elapsed)
            self.logger.info(
                f"[Collector] {elapsed // 60}m/{total_min}m elapsed, "
                f"{remaining // 60}m {remaining % 60}s remaining"
            )

        # Stop all collectors
        self.logger.info("Stopping collectors...")
        await fsdb_collector.stop()
        await hrt_collector.stop()
        await bgp_collector.stop()
        self.logger.info("All collectors stopped")

        # Compute trigger_time = step_start_time + trigger_delay_sec
        trigger_time = datetime.fromtimestamp(
            step_start_time + self.trigger_delay_sec,
            tz=timezone.utc,
        )
        self.logger.info(
            f"Trigger time: {trigger_time.isoformat()} "
            f"(start + {self.trigger_delay_sec}s delay)"
        )

        # Build lane -> gtsw mapping
        gtsw_list = lanes_to_gtsws(self.lanes)
        lane_to_gtsw: t.Dict[int, str] = dict(zip(self.lanes, gtsw_list))
        self.logger.info(f"Lane-to-GTSW mapping: {lane_to_gtsw}")

        # Evaluate results
        fsdb_results = fsdb_collector.evaluate_per_device(
            trigger_time=trigger_time,
            lane_map=lane_to_gtsw,
            expected_matched=self.fsdb_expected,
        )
        bgp_results = bgp_collector.evaluate_per_device(
            trigger_time=trigger_time,
            lane_map=lane_to_gtsw,
            expected_matched=self.bgp_expected,
        )
        hrt_results = hrt_collector.evaluate_per_lane(
            trigger_time=trigger_time,
            lanes=self.lanes,
            expected_per_lane=self.hrt_thresholds if self.hrt_thresholds else None,
        )

        # Log results
        all_results: t.List[PerLaneResult] = fsdb_results + bgp_results + hrt_results
        failures: t.List[PerLaneResult] = []

        self.logger.info("=" * 80)
        self.logger.info("FPF CONTINUOUS COLLECTOR RESULTS")
        self.logger.info("=" * 80)

        for r in all_results:
            status = "PASS" if r.passed else "FAIL"
            convergence_str = (
                f" convergence={r.convergence_sec}s"
                if r.convergence_sec is not None
                else ""
            )
            self.logger.info(
                f"  [{status}] Lane {r.lane} | {r.check_type} | "
                f"{r.device} | expected={r.expected} actual={r.actual}"
                f"{convergence_str} | {r.detail}"
            )
            if not r.passed:
                failures.append(r)

        self.logger.info("=" * 80)

        if failures:
            failure_lines = []
            for f in failures:
                failure_lines.append(
                    f"Lane {f.lane} {f.check_type} on {f.device}: {f.detail}"
                )
            self.logger.warning(
                f"{len(failures)} collector check(s) failed — "
                f"details will appear in postcheck results table:\n"
                + "\n".join(failure_lines)
            )
        else:
            self.logger.info(f"All {len(all_results)} collector checks passed")

    async def cleanUp(
        self,
        input: taac_types.BaseInput,
        params: t.Dict[str, t.Any],
    ) -> None:
        pass
