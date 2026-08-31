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
        target_device = check_params.get("device_name")
        if target_device is not None and self._normalize_hostname(
            hostname
        ) != self._normalize_hostname(str(target_device)):
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=(
                    f"Drain-state expectation is scoped to {target_device}; "
                    f"skipping {hostname}"
                ),
            )

        expected_drained = bool(check_params.get("expected_drained", False))
        self.logger.info(f"Starting drain state check for {hostname}")

        try:
            # Use the _async_is_onbox_drained_helper API to get the actual drain state
            # pyrefly: ignore [missing-attribute]
            actual_drain_state = await self.driver._async_is_onbox_drained_helper()
            self.logger.info(f"Drain state for {hostname}: {actual_drain_state.name}")

            if actual_drain_state not in (
                DeviceDrainState.DRAINED,
                DeviceDrainState.UNDRAINED,
            ):
                # Unknown or unexpected drain state - return failure
                error_msg = f"Device {hostname} has unexpected drain state: {actual_drain_state.name}"
                self.logger.error(error_msg)
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=error_msg,
                )

            actual_drained = actual_drain_state == DeviceDrainState.DRAINED
            actual_label = "drained" if actual_drained else "undrained"
            expected_label = "drained" if expected_drained else "undrained"
            message = f"Device {hostname} is {actual_label}"
            if actual_drained == expected_drained:
                self.logger.info(f"{message}, as expected")
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.PASS,
                    message=message,
                )

            error_msg = f"{message}; expected {expected_label}"
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

    @staticmethod
    def _normalize_hostname(hostname: str) -> str:
        return (
            hostname.rstrip(".")
            .casefold()
            .removesuffix(".tfbnw.net")
            .removesuffix(".facebook.com")
        )
