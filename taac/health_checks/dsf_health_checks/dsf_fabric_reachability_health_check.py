# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_check.health_check import types as hc_types


class DsfFabricReachabilityHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    CHECK_NAME = hc_types.CheckName.DSF_FABRIC_REACHABILITY_CHECK
    OPERATING_SYSTEMS = ["FBOSS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        # pyrefly: ignore [missing-attribute]
        fabric_connectivity = await self.driver.async_get_fabric_connectivity()
        inconsistent_fabric_endpoints = []
        for fabric_endpoint in fabric_connectivity.values():
            if fabric_endpoint.expectedSwitchId and fabric_endpoint.expectedPortId:
                if (
                    fabric_endpoint.expectedSwitchId != fabric_endpoint.switchId
                    or fabric_endpoint.expectedPortId != fabric_endpoint.portId
                ):
                    self.logger.error(
                        f"Expected switch ID {fabric_endpoint.expectedSwitchId} and port ID {fabric_endpoint.expectedPortId}, but got switch ID {fabric_endpoint.switchId} and port ID {fabric_endpoint.portId}"
                    )
                    inconsistent_fabric_endpoints.append(fabric_endpoint)

        if inconsistent_fabric_endpoints:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"{obj.name} has inconsistent fabric endpoints. The following endpoints have mismatched switch IDs or port IDs: {inconsistent_fabric_endpoints}",
            )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
        )

    async def skip_check(self, obj: TestDevice) -> t.Tuple[bool, str | None]:
        supported_roles = ["RDSW", "EDSW"]
        if obj.attributes.role not in supported_roles:
            return True, f"{obj.name}'s device role is not in {supported_roles}"
        return False, None
