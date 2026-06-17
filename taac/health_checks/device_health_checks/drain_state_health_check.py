# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import typing as t

from taac.constants import TestDevice
from taac.driver.driver_constants import DeviceDrainState
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_check.health_check import types as hc_types


class DrainStateHealthCheck(AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]):
    CHECK_NAME = hc_types.CheckName.DRAIN_STATE_CHECK
    OPERATING_SYSTEMS = ["FBOSS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        hostname = obj.name
        self.logger.info(f"Starting drain state check for {hostname}")

        try:
            # Use the _async_is_onbox_drained_helper API to get the actual drain state
            # pyrefly: ignore [missing-attribute]
            actual_drain_state = await self.driver._async_is_onbox_drained_helper()
            self.logger.info(f"Drain state for {hostname}: {actual_drain_state.name}")

            # Check if device is drained
            if actual_drain_state == DeviceDrainState.DRAINED:
                # Device is drained - return failure
                error_msg = (
                    f"Device {hostname} is drained (state: {actual_drain_state.name})"
                )
                self.logger.error(error_msg)
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=error_msg,
                )
            elif actual_drain_state == DeviceDrainState.UNDRAINED:
                # Device is explicitly undrained - return pass
                self.logger.info(
                    f"Device {hostname} is undrained (state: {actual_drain_state.name})"
                )
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.PASS,
                    message=f"Device {hostname} is undrained",
                )
            else:
                # Unknown or unexpected drain state - return failure
                error_msg = f"Device {hostname} has unexpected drain state: {actual_drain_state.name}"
                self.logger.error(error_msg)
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=error_msg,
                )

        except Exception as e:
            error_msg = f"Error checking drain state for {hostname}: {e}"
            self.logger.error(error_msg)
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=error_msg,
            )
