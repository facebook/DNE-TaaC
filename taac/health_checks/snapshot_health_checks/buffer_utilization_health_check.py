# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import asyncio
import re
import typing as t

from taac.constants import TestTopology
from taac.health_checks.abstract_snapshot_health_check import (
    AbstractTopologySnapshotHealthCheck,
)
from taac.health_checks.constants import Snapshot
from taac.utils.health_check_utils import get_fb303_client
from taac.utils.qos_constants import ClassOfService
from taac.health_check.health_check import types as hc_types


# Mapping from ClassOfService to the queue label used in
# buffer_watermark_ucast fb303 counter names.
# Counter format: buffer_watermark_ucast.<port>.queue<N>.<name>.p100.60
COS_QUEUE_BUFFER_WM_LABEL: t.Dict[ClassOfService, str] = {
    ClassOfService.BRONZE: "queue1.bronze",
    ClassOfService.SILVER: "queue2.silver",
    ClassOfService.GOLD: "queue3.gold",
    ClassOfService.ICP: "queue6.icp",
    ClassOfService.NC: "queue7.nc",
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

    def _resolve_active_labels(
        self,
        threshold: "hc_types.BufferUtilizationThreshold",
        failure_reasons: t.List[str],
    ) -> t.Optional[t.Tuple[t.Set[str], t.Optional[t.Set[str]]]]:
        """Resolve (active labels, fixed "other" labels) for a threshold.

        Backend (DSF/RTSW) queues -- queue2.rdma, queue6.monitoring, queue0.be
        -- have no ClassOfService equivalent, so they are named by string
        descriptor instead, and the fb303 watermark counters are already keyed
        by that same "queue<N>.<name>" label. When descriptors are supplied the
        "other" set has to come from the queues the interface actually reports,
        because the FE ClassOfService label set does not cover the BE queues;
        that case returns None for the fixed set.

        Returns None when the threshold names nothing usable, having recorded
        why in ``failure_reasons``.
        """
        hostname = threshold.hostname
        queue_descs = threshold.active_queue_desc_list
        if queue_descs:
            active_queue_labels = set(queue_descs)
            fixed_other_labels = None
        else:
            try:
                active_queue_labels = {
                    COS_QUEUE_BUFFER_WM_LABEL[ClassOfService(cos)]
                    for cos in threshold.active_cos_list
                }
            except (KeyError, ValueError):
                failure_reasons.append(
                    f"Threshold for {hostname} requests classes of service "
                    f"{list(threshold.active_cos_list)}, which do not all map "
                    f"to a buffer watermark queue label."
                )
                return None
            fixed_other_labels = (
                set(COS_QUEUE_BUFFER_WM_LABEL.values()) - active_queue_labels
            )

        if not active_queue_labels:
            failure_reasons.append(
                f"Threshold for {hostname} names no active queue; buffer "
                "utilization could not be verified."
            )
            return None
        return active_queue_labels, fixed_other_labels

    def _check_interface(
        self,
        threshold: "hc_types.BufferUtilizationThreshold",
        interface: str,
        host_counters: t.Dict[str, int],
        active_queue_labels: t.Set[str],
        fixed_other_labels: t.Optional[t.Set[str]],
        failure_reasons: t.List[str],
    ) -> None:
        """Compare one interface's queue watermarks against the threshold.

        An unreported watermark is a failure, not a zero: defaulting it would
        let the threshold pass without observing the queue at all.
        """
        hostname = threshold.hostname
        queue_wms = self._get_queue_watermarks_for_interface(host_counters, interface)
        if not queue_wms:
            failure_reasons.append(
                f"{hostname}:{interface} exported no per-queue "
                "buffer_watermark_ucast counters; buffer utilization "
                "could not be verified."
            )
            return

        unobserved = sorted(active_queue_labels - set(queue_wms))
        if unobserved:
            failure_reasons.append(
                f"{hostname}:{interface} did not report a watermark for "
                f"requested queue(s) {', '.join(unobserved)}; buffer "
                "utilization could not be verified."
            )
            return

        other_queue_labels = (
            set(queue_wms) - active_queue_labels
            if fixed_other_labels is None
            else fixed_other_labels & set(queue_wms)
        )
        # Both label sets are known present in queue_wms by this point.
        self._check_labels(
            hostname,
            interface,
            "Active",
            sorted(active_queue_labels),
            queue_wms,
            threshold.active_queue_max_bytes,
            failure_reasons,
        )
        self._check_labels(
            hostname,
            interface,
            "Inactive",
            sorted(other_queue_labels),
            queue_wms,
            threshold.other_queue_max_bytes,
            failure_reasons,
        )

    def _check_labels(
        self,
        hostname: str,
        interface: str,
        kind: str,
        labels: t.List[str],
        queue_wms: t.Dict[str, int],
        max_bytes: int,
        failure_reasons: t.List[str],
    ) -> None:
        for label in labels:
            wm_bytes = queue_wms[label]
            if wm_bytes > max_bytes:
                failure_reasons.append(
                    f"{kind} queue buffer exceeded threshold on "
                    f"{hostname}:{interface} ({label})\n"
                    f"  Watermark: {_bytes_to_mb(wm_bytes):.2f} MB "
                    f"({wm_bytes} bytes)\n"
                    f"  Threshold: {_bytes_to_mb(max_bytes):.2f} MB "
                    f"({max_bytes} bytes)"
                )

    async def compare_snapshots(
        self,
        obj: TestTopology,
        input: hc_types.BufferUtilizationHealthCheckIn,
        check_params: t.Dict[str, t.Any],
        pre_snapshot: Snapshot,
        post_snapshot: Snapshot,
    ) -> hc_types.HealthCheckResult:
        post_counters = post_snapshot.data or {}
        failure_reasons: t.List[str] = []

        # A watermark that was never exported reads as absent, and treating
        # absent as 0 would let every threshold below pass without observing a
        # single queue. Every level of the lookup -- thresholds, host,
        # interface, requested queue label -- therefore fails explicitly when
        # it produces nothing.
        if not input.thresholds:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    "BUFFER_UTILIZATION_CHECK ran with no thresholds; no queue "
                    "was observed."
                ),
            )

        for threshold in input.thresholds:
            hostname = threshold.hostname
            host_counters = post_counters.get(hostname)
            if not host_counters:
                failure_reasons.append(
                    f"No buffer_watermark_ucast counters were collected for "
                    f"{hostname}; buffer utilization could not be verified."
                )
                continue

            if not threshold.interfaces:
                failure_reasons.append(
                    f"Threshold for {hostname} lists no interfaces; buffer "
                    "utilization could not be verified."
                )
                continue

            resolved = self._resolve_active_labels(threshold, failure_reasons)
            if resolved is None:
                continue
            active_queue_labels, fixed_other_labels = resolved

            for interface in threshold.interfaces:
                self._check_interface(
                    threshold,
                    interface,
                    host_counters,
                    active_queue_labels,
                    fixed_other_labels,
                    failure_reasons,
                )

        if failure_reasons:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message="\n".join(failure_reasons),
            )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
        )
