# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.utils.hardware_capacity_utils import (
    check_hardware_capacity,
    HardwareCapacityThresholds,
)
from taac.health_check.health_check import types as hc_types


class HardwareCapacityHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    CHECK_NAME = hc_types.CheckName.HARDWARE_CAPACITY_CHECK
    OPERATING_SYSTEMS = [
        "EOS",
    ]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        """
        Run hardware capacity health check for network devices.

        Args:
            obj: Test device
            input: Base health check input
            check_params: Dictionary containing:
                - fec_threshold: Maximum allowed FEC entries (default: 10000 for pre-check, 20000 for post-check)
                - ecmp_threshold: Maximum allowed ECMP entries (default: 1000)
                - max_ecmp_level1: Maximum allowed EcmpLevel1 objects (default: 5)
                - max_ecmp_level2: Maximum allowed EcmpLevel2 objects (default: 500)
                - max_ecmp_level3: Maximum allowed EcmpLevel3 objects (default: 0)
                - watermark_delta_threshold: Maximum allowed delta between current count and high watermark (default: 100)
                - check_watermarks: Whether to check high watermarks delta (default: True)

        Returns:
            HealthCheckResult: Result of the health check
        """
        self.logger.debug(f"Executing hardware capacity check on {obj.name}.")

        try:
            # Create threshold configuration from parameters
            thresholds = HardwareCapacityThresholds.from_dict(check_params)

            # Run the hardware capacity check using utility functions
            result = await check_hardware_capacity(self.driver, thresholds)

            # Convert the result to HealthCheckResult format
            if result.passed:
                self.logger.info(result.get_message())
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.PASS,
                    message=result.get_message(),
                )
            else:
                self.logger.error(result.get_message())
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=result.get_message(),
                )

        except Exception as e:
            error_message = f"Error during hardware capacity check: {str(e)}"
            self.logger.error(error_message)
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=error_message,
            )
