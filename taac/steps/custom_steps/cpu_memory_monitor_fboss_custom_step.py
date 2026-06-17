# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""
FBOSS-compatible custom step for periodic BGP queue depth monitoring.

Polls BGP fiber queue depths at regular intervals, logs each sample,
reports peak values, and fails if any queue exceeds the per-peer threshold.
"""

import asyncio
import time
import typing as t

from taac.constants import TestCaseFailure
from taac.internal.utils.bgp_client_helper import BgpClientHelper


# Queue name mapping (BGP++ internal names to friendly names)
QUEUE_NAME_MAPPING = {
    "ingress_adjrib_in": "AdjRibIn",
    "egress_rib_out": "RibOut",
    "ingress_rib_in": "RibIn",
}


class CpuMemoryMonitorFbossCustomStep:
    """
    Periodic BGP queue depth monitor for FBOSS devices.

    Collects BGP queue depths via thrift, logs each sample,
    and validates that aggregate queue depths stay within
    the per-peer threshold.
    """

    def __init__(self, step: t.Any) -> None:
        self.step: t.Any = step
        self.logger: t.Any = step.logger

    async def _collect_queue_stats(self, bgp_helper, focused_queues):
        """Collect aggregate BGP queue depths."""
        try:
            queue_stats = await bgp_helper.async_get_fiber_queue_stats()
            queue_details = queue_stats.get("queue_details", {})
            aggregate = dict.fromkeys(focused_queues, 0)
            for queue_name, depth in queue_details.items():
                if "peer_manager.session_manager." in queue_name:
                    parts = queue_name.split(".")
                    if len(parts) >= 4:
                        friendly = QUEUE_NAME_MAPPING.get(parts[-1])
                        if friendly and friendly in aggregate:
                            aggregate[friendly] += depth
                elif queue_name.startswith("rib."):
                    bgp_type = (
                        queue_name.split(".", 1)[1] if "." in queue_name else None
                    )
                    if bgp_type:
                        friendly = QUEUE_NAME_MAPPING.get(bgp_type)
                        if friendly and friendly in aggregate:
                            aggregate[friendly] += depth
            return aggregate
        except Exception as e:
            self.logger.warning(f"Failed to collect queue stats: {e}")
            return {q: -1 for q in focused_queues}

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        """
        Monitor BGP queue depths and validate against per-peer threshold.

        Args:
            params: Dictionary containing:
                - hostname: Device hostname
                - duration_minutes: Monitoring duration in minutes (default: 60)
                - interval_seconds: Sampling interval in seconds (default: 10)
                - focused_queues: Queue names to track
                  (default: AdjRibIn, RibOut, RibIn)
                - max_queue_per_peer: Max allowed queue depth per peer
                  (default: 10)
                - total_peers: Total number of BGP peers (default: 140)
        """
        hostname = params["hostname"]
        duration_minutes = params.get("duration_minutes", 60)
        interval_seconds = params.get("interval_seconds", 10)
        focused_queues = params.get("focused_queues", ["AdjRibIn", "RibOut", "RibIn"])
        max_queue_per_peer = params.get("max_queue_per_peer", 10)
        total_peers = params.get("total_peers", 140)

        max_aggregate_queue = max_queue_per_peer * total_peers
        duration_seconds = duration_minutes * 60

        self.logger.info("=" * 60)
        self.logger.info("BGP QUEUE MONITOR (FBOSS)")
        self.logger.info(f"Device: {hostname}")
        self.logger.info(f"Duration: {duration_minutes} minutes")
        self.logger.info(f"Interval: {interval_seconds} seconds")
        self.logger.info(f"Queues: {', '.join(focused_queues)}")
        self.logger.info(
            f"Threshold: {max_queue_per_peer} per peer x "
            f"{total_peers} peers = {max_aggregate_queue}"
        )
        self.logger.info("=" * 60)

        bgp_helper = BgpClientHelper(host=hostname)

        max_queues = dict.fromkeys(focused_queues, 0)
        sample_count = 0
        violations = []
        start_time = time.time()

        while (time.time() - start_time) < duration_seconds:
            sample_count += 1

            queue_agg = await self._collect_queue_stats(bgp_helper, focused_queues)

            for q in focused_queues:
                depth = queue_agg.get(q, 0)
                max_queues[q] = max(max_queues[q], depth)
                if depth > max_aggregate_queue:
                    violations.append(
                        f"Sample {sample_count}: {q}={depth} "
                        f"exceeded threshold {max_aggregate_queue}"
                    )

            queue_str = ", ".join(f"{q}={queue_agg.get(q, 0)}" for q in focused_queues)
            self.logger.info(f"Sample {sample_count}: {queue_str}")

            elapsed = time.time() - start_time
            if elapsed < duration_seconds:
                sleep_time = min(interval_seconds, duration_seconds - elapsed)
                await asyncio.sleep(sleep_time)

        self.logger.info("=" * 60)
        self.logger.info("BGP QUEUE MONITOR RESULTS")
        self.logger.info(f"Samples collected: {sample_count}")
        for q in focused_queues:
            self.logger.info(f"Peak {q}: {max_queues[q]}")
        self.logger.info(
            f"Threshold: {max_aggregate_queue} "
            f"({max_queue_per_peer}/peer x {total_peers} peers)"
        )
        if violations:
            self.logger.info(f"Violations: {len(violations)}")
            for v in violations:
                self.logger.info(f"  {v}")
        else:
            self.logger.info("Violations: 0 (all samples within threshold)")
        self.logger.info("=" * 60)

        if violations:
            raise TestCaseFailure(
                f"BGP queue depth exceeded threshold in {len(violations)} sample(s). "
                f"Max allowed: {max_aggregate_queue} "
                f"({max_queue_per_peer}/peer x {total_peers} peers). "
                f"First violation: {violations[0]}",
                is_postcheck_failure=True,
            )
