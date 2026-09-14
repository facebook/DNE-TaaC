# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_snapshot_health_check import (
    AbstractDeviceSnapshotHealthCheck,
)
from taac.health_checks.constants import Snapshot
from taac.utils.common import async_everpaste_str
from taac.health_check.health_check import types as hc_types


class CpuQueueHealthCheck(
    AbstractDeviceSnapshotHealthCheck[hc_types.CpuQueueHealthCheckIn],
):
    CHECK_NAME = hc_types.CheckName.CPU_QUEUE_CHECK
    OPERATING_SYSTEMS = ["FBOSS"]

    async def capture_pre_snapshot(
        self,
        obj: TestDevice,
        input: hc_types.CpuQueueHealthCheckIn,
        check_params: t.Dict[str, t.Any],
        timestamp: int,
    ) -> Snapshot:
        # pyrefly: ignore [missing-attribute]
        cpu_port_stats = await self.driver.async_get_cpu_port_stats()
        return Snapshot(
            data=cpu_port_stats,
            timestamp=timestamp,
        )

    async def capture_post_snapshot(
        self,
        obj: TestDevice,
        input: hc_types.CpuQueueHealthCheckIn,
        check_params: t.Dict[str, t.Any],
        timestamp: int,
    ) -> Snapshot:
        # pyrefly: ignore [missing-attribute]
        cpu_port_stats = await self.driver.async_get_cpu_port_stats()
        return Snapshot(
            data=cpu_port_stats,
            timestamp=timestamp,
        )

    async def compare_snapshots(
        self,
        obj: TestDevice,
        input: hc_types.CpuQueueHealthCheckIn,
        check_params: t.Dict[str, t.Any],
        pre_snapshot: Snapshot,
        post_snapshot: Snapshot,
    ) -> hc_types.HealthCheckResult:
        failure_reasons = []
        elapsed_secs = post_snapshot.timestamp - pre_snapshot.timestamp
        if elapsed_secs < 0:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    "CPU queue snapshots must not move backwards in time; "
                    f"pre={pre_snapshot.timestamp}, post={post_snapshot.timestamp}"
                ),
            )
        # Snapshot timestamps have one-second precision. A fast pre/post pair
        # can legitimately share a timestamp; evaluate it as a one-second
        # window rather than rejecting otherwise valid counter deltas.
        elapsed_secs = max(1, elapsed_secs)

        all_queues = set(
            # pyre-ignore
            input.active_queues
            + (input.inactive_queues or [])
            + (input.no_discard_queues or [])
            + (input.active_discard_queues or [])
        )

        pre_snapshot_out_packets: dict[int, int | None] = {}
        post_snapshot_out_packets: dict[int, int | None] = {}
        pre_snapshot_discard_packets: dict[int, int | None] = {}
        post_snapshot_discard_packets: dict[int, int | None] = {}
        out_packets_increase = {}
        out_pps = {}
        min_out_pps_threshold = {}
        for queue in all_queues:
            pre_snapshot_out_packets[queue] = (
                pre_snapshot.data.portStats_.queueOutPackets_.get(queue)
            )
            post_snapshot_out_packets[queue] = (
                post_snapshot.data.portStats_.queueOutPackets_.get(queue)
            )
            min_out_pps_threshold[queue] = (
                input.active_min_out_pps_per_queue.get(queue, input.active_min_out_pps)
                if input.active_min_out_pps_per_queue
                else input.active_min_out_pps
            )

            pre_snapshot_discard_packets[queue] = (
                pre_snapshot.data.portStats_.queueOutDiscardPackets_.get(queue)
            )
            post_snapshot_discard_packets[queue] = (
                post_snapshot.data.portStats_.queueOutDiscardPackets_.get(queue)
            )

            pre_out_packets = pre_snapshot_out_packets[queue]
            post_out_packets = post_snapshot_out_packets[queue]
            if pre_out_packets is None or post_out_packets is None:
                continue

            out_packets_increase[queue] = post_out_packets - pre_out_packets
            out_pps[queue] = out_packets_increase[queue] / elapsed_secs

        for queue in input.active_queues:
            pre_out_packets = pre_snapshot_out_packets[queue]
            post_out_packets = post_snapshot_out_packets[queue]
            if post_out_packets is None:
                failure_reasons.append(
                    f"No out_packets counters found for queue {queue}"
                )
                continue

            packets_increase = (
                post_out_packets
                if pre_out_packets is None
                else out_packets_increase[queue]
            )
            packets_per_second = packets_increase / elapsed_secs

            if packets_increase <= 0:
                failure_reasons.append(
                    f"No output packet increase detected on queue {queue}"
                )
            elif packets_per_second < min_out_pps_threshold[queue]:
                failure_reasons.append(
                    f"Output packet per second on queue {queue} "
                    f"({packets_per_second}) is below threshold "
                    f"({min_out_pps_threshold[queue]})"
                )
            else:
                self.logger.debug(
                    f"Successfully validated that that the output packet per second of {packets_per_second} "
                    f"on queue {queue} is above the defined minimum threshold {min_out_pps_threshold[queue]}."
                )

        for queue in input.inactive_queues or []:
            pre_out_packets = pre_snapshot_out_packets[queue]
            post_out_packets = post_snapshot_out_packets[queue]
            # FBOSS omits queues with no packets from the sparse counter map.
            if pre_out_packets is None and post_out_packets is None:
                continue
            if pre_out_packets is None and post_out_packets is not None:
                observed_pps = post_out_packets / elapsed_secs
                if observed_pps > min_out_pps_threshold[queue]:
                    failure_reasons.append(
                        f"Output packet increase ({observed_pps} pps) "
                        f"detected on inactive queue {queue}"
                    )
                continue
            if post_out_packets is None:
                failure_reasons.append(
                    f"Incomplete out_packets counters for queue {queue}"
                )
                continue

            if out_pps[queue] > min_out_pps_threshold[queue]:
                failure_reasons.append(
                    f"Output bytes increase ({out_pps[queue]}) detected on queue {queue}"
                )

        for queue in input.no_discard_queues or []:
            pre_discards = pre_snapshot_discard_packets[queue]
            post_discards = post_snapshot_discard_packets[queue]
            if pre_discards is None and post_discards is None:
                # Queue counters are sparse. Absence in both snapshots means
                # zero discards throughout the observation window.
                continue
            if pre_discards is None and post_discards is not None:
                if post_discards > 0:
                    failure_reasons.append(
                        f"Detected {post_discards} packet discard(s) on queue "
                        f"{queue} from a sparse zero baseline"
                    )
                continue
            if post_discards is None:
                failure_reasons.append(
                    f"Incomplete packet discard counters for queue {queue}"
                )
                continue
            assert pre_discards is not None
            if post_discards > pre_discards:
                failure_reasons.append(
                    f"Detected packet discards on queue {queue}. The number of out byte discards "
                    f"increased from {pre_discards} at {pre_snapshot.timestamp} to "
                    f"{post_discards} at {post_snapshot.timestamp}"
                )

        for queue in input.active_discard_queues or []:
            pre_discards = pre_snapshot_discard_packets[queue]
            post_discards = post_snapshot_discard_packets[queue]
            if post_discards is None:
                failure_reasons.append(
                    f"No packet discard counters found for queue {queue}"
                )
                continue
            baseline_discards = 0 if pre_discards is None else pre_discards
            if post_discards <= baseline_discards:
                failure_reasons.append(
                    f"No packet discard increase detected on queue {queue}: "
                    f"pre={pre_discards!r}, post={post_discards}"
                )

        if failure_reasons:
            # Use the Everpaste URL directly; it is already a clickable internalfb.com
            # link, so the throttled fburl tier (createFBUrl) is unnecessary here.
            everpaste_url = await async_everpaste_str("\n".join(failure_reasons))
            inline_summary = failure_reasons[:5]
            suffix = (
                f" (+{len(failure_reasons) - 5} more)"
                if len(failure_reasons) > 5
                else ""
            )
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"CPU queue check failed with {len(failure_reasons)} issue(s): "
                f"{inline_summary}{suffix}. Full details: {everpaste_url}",
            )

        return hc_types.HealthCheckResult(status=hc_types.HealthCheckStatus.PASS)
