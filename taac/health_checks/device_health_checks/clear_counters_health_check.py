# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import asyncio
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_check.health_check import types as hc_types


class ClearCountersHealthCheck(AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]):
    CHECK_NAME: hc_types.CheckName = hc_types.CheckName.CLEAR_COUNTERS_CHECK
    OPERATING_SYSTEMS = ["EOS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        if self.ixia is None:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message="ixia is None, failed to stop traffics and clear counters",
            )
        ixia = self.ixia
        try:
            self.logger.info("Stopping traffic to clear counters")
            ixia.stop_traffic()
            await asyncio.sleep(3)
            cmd = "\n".join(
                [
                    "clear counter",
                    "clear plat fap counter",
                    "clear hardware counter drop",
                    "clear mac access-list counter",
                    "clear ip access-list counter",
                    "clear ipv6 access-list counter",
                    "clear priority-flow-control buffer counters",
                    "clear sflow counter",
                    "clear priority-flow-control counter history",
                    "clear priority-flow-control counter watchdog",
                ]
            )
            # pyrefly: ignore [missing-attribute]
            await self.driver.async_execute_show_or_configure_cmd_on_shell(cmd=cmd)
            self.logger.info("Starting traffic")
            ixia.start_traffic()
            await asyncio.sleep(3)
        except Exception as e:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"Failed to clear counters on {obj.name}: {e}",
            )
        # Return PASS if no failures
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
        )

    async def skip_check(self, obj: TestDevice) -> t.Tuple[bool, str | None]:
        supported_roles = ["BAG"]
        if obj.attributes.role not in supported_roles:
            return True, f"{obj.name}'s device role is not in {supported_roles}"
        return False, None
