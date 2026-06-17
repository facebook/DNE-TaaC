# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.utils.common import async_everpaste_str
from taac.utils.health_check_utils import get_fb303_client
from taac.health_check.health_check import types as hc_types

# minimum output mbps to avoid false positives caused by control plane traffic
MIN_OUTMBPS: int = 200


class DsfTrafficRebalanceHealthCheck(
    AbstractDeviceHealthCheck[hc_types.DsfTrafficRebalanceHealthCheckIn]
):
    CHECK_NAME: hc_types.CheckName = hc_types.CheckName.DSF_TRAFFIC_REBALANCE_CHECK
    OPERATING_SYSTEMS = ["FBOSS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.DsfTrafficRebalanceHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        async with await get_fb303_client(obj.name) as client:
            counters = await client.getCounters()
        # pyrefly: ignore [missing-attribute]
        ports = (await self.driver.async_get_all_port_info()).values()
        max_out_mbps = float("-inf")
        min_out_mbps = float("inf")

        out_mbps_counters = {}

        for port in ports:
            if "fab" not in port.name:
                continue
            out_bps = counters[f"{port.name}.out_bytes.rate.60"]
            out_mbps = out_bps / 1_000_000
            out_mbps_counters[port.name] = out_mbps
            if out_mbps < MIN_OUTMBPS:
                continue
            max_out_mbps = max(max_out_mbps, out_mbps)
            min_out_mbps = min(min_out_mbps, out_mbps)

        deviation = (max_out_mbps - min_out_mbps) * 100 / (max_out_mbps + min_out_mbps)

        if deviation > input.deviation_threshold_pct:
            # Use the Everpaste URL directly; it is already a clickable internalfb.com
            # link, so the throttled fburl tier (createFBUrl) is unnecessary here.
            everpaste_url = await async_everpaste_str(str(out_mbps_counters))
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"Traffic is unevenly distributed on {obj.name}. Observed deviation is {deviation} which is greater than {input.deviation_threshold_pct}: {everpaste_url}",
            )

        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
        )

    async def skip_check(self, obj: TestDevice) -> t.Tuple[bool, str | None]:
        supported_roles = ["RDSW", "FDSW", "EDSW"]
        if obj.attributes.role not in supported_roles:
            return True, f"{obj.name}'s device role is not in {supported_roles}"
        return False, None
