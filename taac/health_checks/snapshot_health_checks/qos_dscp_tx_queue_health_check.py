# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import asyncio
import re
import typing as t

from taac.constants import TestTopology
from taac.health_checks.abstract_snapshot_health_check import (
    AbstractTopologySnapshotHealthCheck,
)
from taac.health_checks.common_utils import evaluate_comparison
from taac.health_checks.constants import Snapshot
from taac.utils.driver_factory import async_get_device_driver
from taac.utils.health_check_utils import get_fb303_client
from taac.utils.qos_constants import ClassOfService
from taac.health_check.health_check import types as hc_types


COS_QUEUE_FB303_COUNTER_DESC = {
    ClassOfService.BRONZE: "queue1.bronze",
    ClassOfService.SILVER: "queue2.silver",
    ClassOfService.GOLD: "queue3.gold",
    ClassOfService.ICP: "queue6.icp",
    ClassOfService.NC: "queue7.nc",
}

# NC queue always carries background control plane traffic (BGP keepalives,
# etc.), so its byte counter will show some increment even when NC is not
# the target queue under test.  Subtract this offset from the NC diff to
# avoid false positives in the exclusivity check.
NC_QUEUE_OFFSET_BYTES = 10 * 1024 * 1024  # 10 MB
DEFAULT_QUEUE_OFFSET_BYTES = 1 * 1024 * 1024  # 1 MB

NC_QUEUE_DESC = "queue7.nc"

# Leading queue id of a descriptor like "queue2.silver" / "queue0.be".
RE_QUEUE_INDEX = re.compile(r"^queue(\d+)\.")


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
                self._get_all_fb303_counters(hostname, input)
                for hostname in hosts_to_collect_counters
            ]
        )
        return dict(zip(hosts_to_collect_counters, counters))

    async def _get_all_fb303_counters(
        self,
        hostname: str,
        input: t.Optional[hc_types.QoSDscpTxQueueHealthCheckIn] = None,
    ) -> dict:
        async with await get_fb303_client(hostname) as client:
            counters = dict(await client.getCounters())
        if input is not None:
            counters.update(await self._queue_byte_counters(hostname, input))
        return counters

    async def _queue_byte_counters(
        self, hostname: str, input: hc_types.QoSDscpTxQueueHealthCheckIn
    ) -> t.Dict[str, int]:
        """Supply the per-queue byte counters fb303 does not export.

        FBOSS exports per-queue buffer watermarks but no per-queue out_bytes,
        while getHwPortStats() carries queueOutBytes_ keyed by queue id. Emit
        the same keys the filters look up so they need not know the source.
        Absent stats yield nothing, keeping "unexported" distinct from zero.
        """
        infos = [i for i in input.tx_queue_info_list if i.hostname == hostname]
        if not infos:
            return {}
        descs = set(COS_QUEUE_FB303_COUNTER_DESC.values())
        for info in infos:
            descs.update(info.queue_desc_list or [])
        try:
            driver = await async_get_device_driver(hostname)
            async with driver.async_agent_client as client:
                port_stats = await client.getHwPortStats()
        except Exception as e:
            self.logger.warning(
                f"{hostname}: per-queue byte stats unavailable ({e}); "
                "falling back to fb303 counters only"
            )
            return {}

        synthesized: t.Dict[str, int] = {}
        for info in infos:
            stats = port_stats.get(info.interface)
            queue_bytes = getattr(stats, "queueOutBytes_", None) if stats else None
            if not queue_bytes:
                continue
            for desc in descs:
                m = RE_QUEUE_INDEX.match(desc)
                if m is None:
                    continue
                value = queue_bytes.get(int(m.group(1)))
                if value is None:
                    continue
                synthesized[f"{info.interface}.{desc}.{info.key_desc}"] = value
        return synthesized

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
        # An unexported counter is reported as None, not raised as a KeyError
        # and not defaulted to 0: crashing aborts the whole check as an infra
        # error, and defaulting lets the comparison pass without observing the
        # queue. The callers turn None into an explicit failure.
        cos_to_counter = {}
        for cos, key in counter_keys.items():
            cos_to_counter[cos] = fb303_counters.get(key)
        return cos_to_counter

    def filter_queue_desc_counters(
        self, fb303_counters: dict, tx_queue_info: hc_types.TxQueueInfo
    ) -> t.Dict[str, t.Optional[int]]:
        """Filter fb303 counters using string-based queue descriptions.

        Used for backend TCs (queue2.rdma, queue6.monitoring, queue0.be)
        that don't map to the FE ClassOfService enum.

        A descriptor the device never exported maps to None so the caller can
        fail explicitly on it.
        """
        # None rather than 0 for an unexported counter -- see
        # filter_cos_counters.
        desc_to_counter = {}
        for desc in tx_queue_info.queue_desc_list:
            key = f"{tx_queue_info.interface}.{desc}.{tx_queue_info.key_desc}"
            desc_to_counter[desc] = fb303_counters.get(key)
        return desc_to_counter

    def _exclusivity_counters(
        self,
        pre_value: t.Optional[int],
        post_value: t.Optional[int],
        tx_queue_info: hc_types.TxQueueInfo,
        label: str,
        failure_reasons: t.List[str],
    ) -> t.Optional[t.Tuple[int, int]]:
        """Resolve the pre/post pair for a queue that should have stayed idle.

        Absent from BOTH snapshots means the device never exported the counter,
        so the queue cannot have leaked and there is nothing to compare.
        Absent from only one is not a clean zero: coercing the missing side
        invents a positive delta on a post-only counter (a false leak) or a
        negative one on a pre-only counter (a real leak masked). Report it
        instead.
        """
        if pre_value is None and post_value is None:
            return None
        if pre_value is None or post_value is None:
            failure_reasons.append(
                f"{tx_queue_info.hostname}:{tx_queue_info.interface} exported a "
                f"{tx_queue_info.key_desc} counter for {label} in only one "
                "snapshot; exclusivity could not be verified."
            )
            return None
        return pre_value, post_value

    def _compare_cos(
        self,
        tx_queue_info: hc_types.TxQueueInfo,
        pre_fb303: dict,
        post_fb303: dict,
        failure_reasons: t.List[str],
    ) -> None:
        pre_cos_counters = self.filter_cos_counters(pre_fb303, tx_queue_info)
        post_cos_counters = self.filter_cos_counters(post_fb303, tx_queue_info)

        for cos in tx_queue_info.cos_list:
            pre_counter = pre_cos_counters.get(cos)
            post_counter = post_cos_counters.get(cos)
            if pre_counter is None or post_counter is None:
                failure_reasons.append(
                    f"{tx_queue_info.hostname}:{tx_queue_info.interface} did not "
                    f"export a {tx_queue_info.key_desc} counter for {cos}; the "
                    "queue could not be verified."
                )
                continue
            diff = post_counter - pre_counter
            offset = (
                NC_QUEUE_OFFSET_BYTES
                if cos == ClassOfService.NC
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
                set(COS_QUEUE_FB303_COUNTER_DESC.keys()) - set(tx_queue_info.cos_list)
            )
            for cos in other_cos_list:
                pair = self._exclusivity_counters(
                    pre_cos_counters.get(cos),
                    post_cos_counters.get(cos),
                    tx_queue_info,
                    str(cos),
                    failure_reasons,
                )
                if pair is None:
                    continue
                pre_counter, post_counter = pair
                diff = post_counter - pre_counter
                offset = (
                    NC_QUEUE_OFFSET_BYTES
                    if cos == ClassOfService.NC
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

    def _compare_queue_desc(
        self,
        tx_queue_info: hc_types.TxQueueInfo,
        pre_fb303: dict,
        post_fb303: dict,
        failure_reasons: t.List[str],
    ) -> None:
        """Compare fb303 counters using string-based queue descriptions (backend)."""
        pre_counters = self.filter_queue_desc_counters(pre_fb303, tx_queue_info)
        post_counters = self.filter_queue_desc_counters(post_fb303, tx_queue_info)

        for desc in tx_queue_info.queue_desc_list:
            pre_counter = pre_counters.get(desc)
            post_counter = post_counters.get(desc)
            if pre_counter is None or post_counter is None:
                failure_reasons.append(
                    f"{tx_queue_info.hostname}:{tx_queue_info.interface} did not "
                    f"export a {tx_queue_info.key_desc} counter for {desc}; the "
                    "queue could not be verified."
                )
                continue
            diff = post_counter - pre_counter
            offset = (
                NC_QUEUE_OFFSET_BYTES
                if desc == NC_QUEUE_DESC
                else DEFAULT_QUEUE_OFFSET_BYTES
            )
            diff = max(0, diff - offset)
            if not evaluate_comparison(
                diff, tx_queue_info.comparison, tx_queue_info.val
            ):
                failure_reasons.append(
                    f"Insufficient counter difference for {tx_queue_info.hostname}:{tx_queue_info.interface} ({desc})\n"
                    f"  Expected difference: {tx_queue_info.comparison.name} {tx_queue_info.val}\n"
                    f"  Actual difference:   {post_counter - pre_counter}\n"
                    f"  Before: {pre_counter}\n"
                    f"  After:  {post_counter}"
                )
        if tx_queue_info.enforce_exclusivity:
            all_be_queue_descs = [
                "queue7.nc",
                "queue2.rdma",
                "queue6.monitoring",
                "queue0.be",
            ]
            other_descs = [
                d for d in all_be_queue_descs if d not in tx_queue_info.queue_desc_list
            ]
            for desc in other_descs:
                key = f"{tx_queue_info.interface}.{desc}.{tx_queue_info.key_desc}"
                pair = self._exclusivity_counters(
                    pre_fb303.get(key),
                    post_fb303.get(key),
                    tx_queue_info,
                    desc,
                    failure_reasons,
                )
                if pair is None:
                    continue
                pre_counter, post_counter = pair
                diff = post_counter - pre_counter
                offset = (
                    NC_QUEUE_OFFSET_BYTES
                    if desc == NC_QUEUE_DESC
                    else DEFAULT_QUEUE_OFFSET_BYTES
                )
                diff = max(0, diff - offset)
                if evaluate_comparison(
                    diff, tx_queue_info.comparison, tx_queue_info.val
                ):
                    failure_reasons.append(
                        f"Unexpected counter difference for {tx_queue_info.hostname}:{tx_queue_info.interface} ({desc})\n"
                        f"  Expected difference: NOT {tx_queue_info.comparison.name} {tx_queue_info.val}\n"
                        f"  Actual difference:   {post_counter - pre_counter}\n"
                        f"  Before: {pre_counter}\n"
                        f"  After:  {post_counter}"
                    )

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
            if tx_queue_info.queue_desc_list:
                self._compare_queue_desc(
                    tx_queue_info,
                    pre_fb303_counters[tx_queue_info.hostname],
                    post_fb303_counters[tx_queue_info.hostname],
                    failure_reasons,
                )
            else:
                self._compare_cos(
                    tx_queue_info,
                    pre_fb303_counters[tx_queue_info.hostname],
                    post_fb303_counters[tx_queue_info.hostname],
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
