# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_check.health_check import types as hc_types


class OpenrInitializedHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    """
    Validates that Open/R has completed full initialization on the device.
    Checks that initialization events have fired (INITIALIZED).
    """

    # TODO: Update to the real CheckName once added to health_check.thrift
    CHECK_NAME = hc_types.CheckName.OPENR_INITIALIZED_CHECK
    OPERATING_SYSTEMS = ["FBOSS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        openr_data = await self.driver.async_validate_openr()
        init_events = openr_data.get("initialization_events", {})

        if not init_events:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"{obj.name}: OpenR has no initialization events — "
                f"not initialized",
            )

        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=f"{obj.name}: OpenR initialized with {len(init_events)} event(s)",
        )
