# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import asyncio
import re
import typing as t

from neteng.qosdb.Cos import types as qos_types
from taac.constants import TestTopology
from taac.health_checks.abstract_snapshot_health_check import (
    AbstractTopologySnapshotHealthCheck,
)
from taac.health_checks.constants import Snapshot
from taac.utils.health_check_utils import get_fb303_client
from taac.health_check.health_check import types as hc_types


# Mapping from ClassOfService to the queue label used in
# buffer_watermark_ucast fb303 counter names.
# Counter format: buffer_watermark_ucast.<port>.queue<N>.<name>.p100.60
COS_QUEUE_BUFFER_WM_LABEL: t.Dict[qos_types.ClassOfService, str] = {
    qos_types.ClassOfService.BRONZE: "queue1.bronze",
    qos_types.ClassOfService.SILVER: "queue2.silver",
    qos_types.ClassOfService.GOLD: "queue3.gold",
    qos_types.ClassOfService.ICP: "queue6.icp",
    qos_types.ClassOfService.NC: "queue7.nc",
}

# Regex to extract per-port per-queue unicast watermark counters.
RE_UCAST = re.compile(r"^buffer_watermark_ucast\.(.+?)\.queue(\d+)\.(.+?)\.p100\.60$")


def _bytes_to_mb(val: int) -> float:
    return val / (1024 * 1024)


class BufferUtilizationHealthCheck(
    AbstractTopologySnapshotHealthCheck[
        hc_types.BufferUtilizationHealthCheckIn
    ]  # pyre-ignore[11]
):
    CHECK_NAME: hc_types.CheckName = (
        hc_types.CheckName.BUFFER_UTILIZATION_CHECK
    )  # pyre-ignore[16]

    async def _collect_fb303_counters(
        self, input: hc_types.BufferUtilizationHealthCheckIn
    ) -> t.Dict[str, t.Dict[str, int]]:
        hosts = list({threshold.hostname for threshold in input.thresholds})
        counters = await asyncio.gather(
            *[self._get_buffer_wm_counters(hostname) for hostname in hosts]
        )
        return dict(zip(hosts, counters))

    async def _get_buffer_wm_counters(self, hostname: str) -> t.Dict[str, int]:
        async with await get_fb303_client(hostname) as client:
            all_counters = await client.getCounters()
            return {
                k: v
                for k, v in all_counters.items()
                if k.startswith("buffer_watermark_ucast") and ".p100.60" in k
            }

    async def capture_pre_snapshot(
        self,
        obj: TestTopology,
        input: hc_types.BufferUtilizationHealthCheckIn,
        check_params: t.Dict[str, t.Any],
        timestamp: int,
    ) -> Snapshot:
        return Snapshot(timestamp=timestamp)

    async def capture_post_snapshot(
        self,
        obj: TestTopology,
        input: hc_types.BufferUtilizationHealthCheckIn,
        check_params: t.Dict[str, t.Any],
        timestamp: int,
    ) -> Snapshot:
        host_to_counters = await self._collect_fb303_counters(input)
        return Snapshot(
            data=host_to_counters,
            timestamp=timestamp,
        )

    def _get_queue_watermarks_for_interface(
        self,
        counters: t.Dict[str, int],
        interface: str,
    ) -> t.Dict[str, int]:
        """Extract per-queue watermark values for a given interface.

        Returns a dict mapping queue label (e.g. "queue1.bronze") to
        the watermark value in bytes.
        """
        result = {}
        for counter_name, value in counters.items():
            m = RE_UCAST.match(counter_name)
            if m:
                port = m.group(1)
                queue_id = m.group(2)
                queue_name = m.group(3)
                if port == interface:
                    label = f"queue{queue_id}.{queue_name}"
                    result[label] = value
        return result

    async def compare_snapshots(
        self,
        obj: TestTopology,
        input: hc_types.BufferUtilizationHealthCheckIn,
        check_params: t.Dict[str, t.Any],
        pre_snapshot: Snapshot,
        post_snapshot: Snapshot,
    ) -> hc_types.HealthCheckResult:
        post_counters = post_snapshot.data
        failure_reasons = []

        for threshold in input.thresholds:
            hostname = threshold.hostname
            host_counters = post_counters.get(hostname, {})

            active_queue_labels = {
                COS_QUEUE_BUFFER_WM_LABEL[cos] for cos in threshold.active_cos_list
            }
            all_queue_labels = set(COS_QUEUE_BUFFER_WM_LABEL.values())
            other_queue_labels = all_queue_labels - active_queue_labels

            for interface in threshold.interfaces:
                queue_wms = self._get_queue_watermarks_for_interface(
                    host_counters, interface
                )

                # Check active queues against active_queue_max_bytes
                for label in active_queue_labels:
                    wm_bytes = queue_wms.get(label, 0)
                    if wm_bytes > threshold.active_queue_max_bytes:
                        failure_reasons.append(
                            f"Active queue buffer exceeded threshold on "
                            f"{hostname}:{interface} ({label})\n"
                            f"  Watermark: {_bytes_to_mb(wm_bytes):.2f} MB "
                            f"({wm_bytes} bytes)\n"
                            f"  Threshold: {_bytes_to_mb(threshold.active_queue_max_bytes):.2f} MB "
                            f"({threshold.active_queue_max_bytes} bytes)"
                        )

                # Check other queues against other_queue_max_bytes
                for label in other_queue_labels:
                    wm_bytes = queue_wms.get(label, 0)
                    if wm_bytes > threshold.other_queue_max_bytes:
                        failure_reasons.append(
                            f"Inactive queue buffer exceeded threshold on "
                            f"{hostname}:{interface} ({label})\n"
                            f"  Watermark: {_bytes_to_mb(wm_bytes):.2f} MB "
                            f"({wm_bytes} bytes)\n"
                            f"  Threshold: {_bytes_to_mb(threshold.other_queue_max_bytes):.2f} MB "
                            f"({threshold.other_queue_max_bytes} bytes)"
                        )

        if failure_reasons:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message="\n".join(failure_reasons),
            )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
        )
