# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import asyncio
import time
import typing as t

from taac.health_checks.abstract_health_check import (
    AbstractIxiaHealthCheck,
)
from neteng.test_infra.dne.taac.ixia.taac_ixia import TaacIxia as Ixia
from taac.health_check.health_check import types as hc_types

PTP_DEFAULT_OFFSET_NS_THRESHOLD: int = 50
PTP_CLIENT_ROLE: str = "Slave"
PTP_INVALID_LISTENING_STATE: str = "Listening"


class IxiaPTPHealthCheck(AbstractIxiaHealthCheck[hc_types.BaseHealthCheckIn]):
    CHECK_NAME = hc_types.CheckName.IXIA_PTP_CHECK

    async def _run(
        self,
        obj: Ixia,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        wait_before_check = check_params.get("wait_before_check", 0)
        if wait_before_check > 0:
            await asyncio.sleep(wait_before_check)
        start_time = check_params.get("start_time")
        min_time_to_monitor = check_params.get("min_time_to_monitor", 60)
        clear_ptp_stats = check_params.get("clear_ptp_stats", False)
        if clear_ptp_stats:
            start_time = time.time()
        ptp_offset_ns_threshold = check_params.get(
            "ptp_offset_ns_threshold", PTP_DEFAULT_OFFSET_NS_THRESHOLD
        )
        ptp_stats = obj.captured_ptp_drill_down_stats[obj.test_case_uuid]
        if not ptp_stats:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message="No PTP stats found in the ixia setup.",
            )
        while True:
            ptp_stats = obj.captured_ptp_drill_down_stats[obj.test_case_uuid]
            ptp_stats_without_latest = {
                timestamp: states for timestamp, states in ptp_stats.items()
            }
            sorted_timestamps = sorted(
                ptp_stats_without_latest.keys(), key=lambda x: int(x)
            )
            if sorted_timestamps[-1] - sorted_timestamps[0] >= min_time_to_monitor:
                break
            await asyncio.sleep(1)
        ptp_stats_in_time_range = []
        if start_time:
            for timestamp, states in ptp_stats.items():
                if timestamp >= start_time:
                    ptp_stats_in_time_range.append(states)
        else:
            ptp_stats_in_time_range = ptp_stats.values()
        failure_reasons = []
        for stats in ptp_stats_in_time_range:
            for ptp_id, ptp_stats in stats.items():
                if ptp_stats["clock_role"] == PTP_CLIENT_ROLE:
                    if abs(ptp_stats["offset_ns"]) > ptp_offset_ns_threshold:
                        failure_reasons.append(
                            f"PTP offset for {ptp_id} {ptp_stats['offset_ns']} is greater than threshold: {ptp_offset_ns_threshold}"
                        )
                    if ptp_stats["ptp_state"] == PTP_INVALID_LISTENING_STATE:
                        failure_reasons.append(
                            f"PTP state for {ptp_id} is stuck in invalid state: {ptp_stats['ptp_state']}."
                        )
        if failure_reasons:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message="\n".join(failure_reasons),
            )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
        )
