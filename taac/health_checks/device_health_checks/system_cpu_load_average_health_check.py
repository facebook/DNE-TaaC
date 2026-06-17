# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_check.health_check import types as hc_types


class SystemCpuLoadAverageHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    CHECK_NAME = hc_types.CheckName.SYSTEM_CPU_LOAD_AVERAGE_CHECK
    OPERATING_SYSTEMS = ["EOS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        """
        Run a health check to verify System CPU utilization is below baseline.

        Args:
            obj: Test device
            input: Base health check input
            check_params: Dictionary containing:
                - baseline: Optional float to set the baseline value for the check, if unset, we assume baseline is not being checked

        Returns:
            HealthCheckResult: Result of the health check
        """
        hostname = obj.name
        self.logger.info(f"Starting System CPU health check for {hostname}")
        baseline = check_params.get("baseline", -1.0)
        # pyrefly: ignore [missing-attribute]
        output = await self.driver.async_get_system_cpu_load_average()

        load_info = f"CPU load average: 1 min: {output[0]}, 5 min: {output[1]}, 15 min: {output[2]}"
        self.logger.info(f"{hostname} {load_info}")

        if baseline > 0:
            if any(load_avg > baseline for load_avg in output):
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=f"System CPU load average is above baseline: {baseline}. {load_info}",
                )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=f"System CPU load average is within baseline: {baseline}. {load_info}",
        )
