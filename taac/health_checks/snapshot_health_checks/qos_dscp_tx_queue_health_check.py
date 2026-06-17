# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import asyncio
import typing as t

from neteng.qosdb.Cos import types as qos_types
from taac.constants import TestTopology
from taac.health_checks.abstract_snapshot_health_check import (
    AbstractTopologySnapshotHealthCheck,
)
from taac.health_checks.common_utils import evaluate_comparison
from taac.health_checks.constants import Snapshot
from taac.utils.health_check_utils import get_fb303_client
from taac.health_check.health_check import types as hc_types


COS_QUEUE_FB303_COUNTER_DESC = {
    qos_types.ClassOfService.BRONZE: "queue1.bronze",
    qos_types.ClassOfService.SILVER: "queue2.silver",
    qos_types.ClassOfService.GOLD: "queue3.gold",
    qos_types.ClassOfService.ICP: "queue6.icp",
    qos_types.ClassOfService.NC: "queue7.nc",
}

# NC queue always carries background control plane traffic (BGP keepalives,
# etc.), so its byte counter will show some increment even when NC is not
# the target queue under test.  Subtract this offset from the NC diff to
# avoid false positives in the exclusivity check.
NC_QUEUE_OFFSET_BYTES = 10 * 1024 * 1024  # 10 MB
DEFAULT_QUEUE_OFFSET_BYTES = 1 * 1024 * 1024  # 1 MB


class QoSDscpTxQueueHealthCheck(
    AbstractTopologySnapshotHealthCheck[hc_types.QoSDscpTxQueueHealthCheckIn]
):
    CHECK_NAME: hc_types.CheckName = hc_types.CheckName.QOS_DSCP_TX_QUEUE_CHECK

    async def _collect_fb303_counters(
        self, input: hc_types.QoSDscpTxQueueHealthCheckIn
    ) -> dict:
        hosts_to_collect_counters = list(
            {tx_queue_info.hostname for tx_queue_info in input.tx_queue_info_list}
        )
        counters = await asyncio.gather(
            *[
                self._get_all_fb303_counters(hostname)
                for hostname in hosts_to_collect_counters
            ]
        )
        return dict(zip(hosts_to_collect_counters, counters))

    async def _get_all_fb303_counters(self, hostname: str) -> dict:
        async with await get_fb303_client(hostname) as client:
            # pyrefly: ignore [bad-return]
            return await client.getCounters()

    async def capture_pre_snapshot(
        self,
        obj: TestTopology,
        input: hc_types.QoSDscpTxQueueHealthCheckIn,
        check_params: t.Dict[str, t.Any],
        timestamp: int,
    ) -> Snapshot:
        host_to_fb303_counters = await self._collect_fb303_counters(input)
        return Snapshot(
            data=host_to_fb303_counters,
            timestamp=timestamp,
        )

    async def capture_post_snapshot(
        self,
        obj: TestTopology,
        input: hc_types.QoSDscpTxQueueHealthCheckIn,
        check_params: t.Dict[str, t.Any],
        timestamp: int,
    ) -> Snapshot:
        host_to_fb303_counters = await self._collect_fb303_counters(input)
        return Snapshot(
            data=host_to_fb303_counters,
            timestamp=timestamp,
        )

    def filter_cos_counters(
        self, fb303_counters: dict, tx_queue_info: hc_types.TxQueueInfo
    ) -> dict:
        counter_keys = {
            cos: f"{tx_queue_info.interface}.{desc}.{tx_queue_info.key_desc}"
            for cos, desc in COS_QUEUE_FB303_COUNTER_DESC.items()
        }
        cos_to_counter = {}
        for cos, key in counter_keys.items():
            cos_to_counter[cos] = fb303_counters[key]
        return cos_to_counter

    async def compare_snapshots(
        self,
        obj: TestTopology,
        input: hc_types.QoSDscpTxQueueHealthCheckIn,
        check_params: t.Dict[str, t.Any],
        pre_snapshot: Snapshot,
        post_snapshot: Snapshot,
    ) -> hc_types.HealthCheckResult:
        pre_fb303_counters = pre_snapshot.data
        post_fb303_counters = post_snapshot.data
        failure_reasons = []
        for tx_queue_info in input.tx_queue_info_list:
            pre_cos_counters = self.filter_cos_counters(
                pre_fb303_counters[tx_queue_info.hostname], tx_queue_info
            )
            post_cos_counters = self.filter_cos_counters(
                post_fb303_counters[tx_queue_info.hostname], tx_queue_info
            )

            for cos in tx_queue_info.cos_list:
                pre_counter = pre_cos_counters[cos]
                post_counter = post_cos_counters[cos]
                diff = post_counter - pre_counter
                offset = (
                    NC_QUEUE_OFFSET_BYTES
                    if cos == qos_types.ClassOfService.NC
                    else DEFAULT_QUEUE_OFFSET_BYTES
                )
                diff = max(0, diff - offset)
                if not evaluate_comparison(
                    diff, tx_queue_info.comparison, tx_queue_info.val
                ):
                    failure_reasons.append(
                        f"Insufficient counter difference for {tx_queue_info.hostname}:{tx_queue_info.interface} ({cos})\n"
                        f"  Expected difference: {tx_queue_info.comparison.name} {tx_queue_info.val}\n"
                        f"  Actual difference:   {post_counter - pre_counter}\n"
                        f"  Before: {pre_counter}\n"
                        f"  After:  {post_counter}"
                    )
            if tx_queue_info.enforce_exclusivity:
                other_cos_list = list(
                    set(COS_QUEUE_FB303_COUNTER_DESC.keys())
                    - set(tx_queue_info.cos_list)
                )
                for cos in other_cos_list:
                    pre_counter = pre_cos_counters[cos]
                    post_counter = post_cos_counters[cos]
                    diff = post_counter - pre_counter
                    offset = (
                        NC_QUEUE_OFFSET_BYTES
                        if cos == qos_types.ClassOfService.NC
                        else DEFAULT_QUEUE_OFFSET_BYTES
                    )
                    diff = max(0, diff - offset)
                    if evaluate_comparison(
                        diff, tx_queue_info.comparison, tx_queue_info.val
                    ):
                        failure_reasons.append(
                            f"Unexpected counter difference for {tx_queue_info.hostname}:{tx_queue_info.interface} ({cos})\n"
                            f"  Expected difference: NOT {tx_queue_info.comparison.name} {tx_queue_info.val}\n"
                            f"  Actual difference:   {post_counter - pre_counter}\n"
                            f"  Before: {pre_counter}\n"
                            f"  After:  {post_counter}"
                        )
        if failure_reasons:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message="\n".join(failure_reasons),
            )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
        )
