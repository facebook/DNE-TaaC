# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_check.health_check import types as hc_types


class OpenrOverloadStateHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    """
    Validates the Open/R overload state on the device.

    check_params:
        expected_overloaded (bool): whether the node is expected to be
            overloaded (True) or not (False). Defaults to False.
    """

    # TODO: Update to the real CheckName once added to health_check.thrift
    CHECK_NAME = hc_types.CheckName.OPENR_OVERLOAD_STATE_CHECK
    OPERATING_SYSTEMS = ["FBOSS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        expected_overloaded = check_params.get("expected_overloaded", False)

        # pyrefly: ignore [missing-attribute]
        lm_links = await self.driver.async_get_openr_lm_links()
        is_overloaded = bool(lm_links.isOverloaded)

        if is_overloaded != expected_overloaded:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"{obj.name}: expected overload="
                f"{expected_overloaded}, actual={is_overloaded}",
            )

        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=f"{obj.name}: overload state is "
            f"{'overloaded' if is_overloaded else 'not overloaded'} "
            f"(as expected)",
        )
