# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.utils.common import async_everpaste_str
from taac.health_check.health_check import types as hc_types


class PortCountersHealthCheck(
    AbstractDeviceHealthCheck[hc_types.PortCountersHealthCheckIn]
):
    CHECK_NAME: hc_types.CheckName = hc_types.CheckName.PORT_COUNTERS_CHECK
    OPERATING_SYSTEMS = ["EOS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.PortCountersHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        try:
            for threshold in input.thresholds:
                interfaces = [
                    endpoint.split(":")[1] for endpoint in threshold.interfaces
                ]
                # pyrefly: ignore [missing-attribute]
                port_counters = await self.driver.async_get_multiple_port_stats(
                    interfaces
                )
                result = await self._evaluate_port_counters(port_counters, threshold)
                if result is not None:
                    return result
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.PASS,
            )
        except Exception as e:
            self.logger.info(f"Error during port counters health check: {e}")
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=str(e),
            )

    async def _evaluate_port_counters(
        self,
        port_counters,
        threshold,
    ) -> t.Optional[hc_types.HealthCheckResult]:
        for port_counter in port_counters:
            for counter_type in [
                "in_discards",
                "out_discards",
                "in_error",
                "out_error",
            ]:
                observed_value = getattr(port_counter, counter_type, None)
                threshold_value = getattr(threshold, counter_type, None)
                if threshold_value is not None:
                    self.logger.info(
                        f"Observed {counter_type} on {port_counter.interface_name}: {observed_value}"
                    )
                    if not await self._compare_port_counters(
                        threshold.comparison,
                        # pyrefly: ignore [bad-argument-type]
                        observed_value,
                        threshold_value,
                    ):
                        return await self.create_failure_result(
                            interface=port_counter.interface_name,
                            port_counters_type=counter_type,
                            observed_value=observed_value,
                            threshold_value=threshold_value,
                        )
        return None

    async def create_failure_result(
        self,
        interface: str,
        port_counters_type: str,
        observed_value,
        threshold_value,
    ):
        # Use the Everpaste URL directly; it is already a clickable internalfb.com
        # link, so the throttled fburl tier (createFBUrl) is unnecessary here.
        everpaste_url = await async_everpaste_str(
            f"{port_counters_type}: {observed_value}"
        )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.FAIL,
            message=f"Traffic on {interface} for {port_counters_type} did not meet the threshold of {threshold_value}. "
            f"Observed {port_counters_type}: {observed_value}. Failure report: {everpaste_url}",
        )

    async def _compare_port_counters(
        self,
        comparison: hc_types.ComparisonType,
        observed_value: int,
        threshold_value: int = 0,
    ) -> bool:
        """
        Helper function to compare the observed port counters with the threshold based on the comparison type.
        """
        if comparison == hc_types.ComparisonType.LESS_THAN:
            return observed_value < threshold_value
        elif comparison == hc_types.ComparisonType.GREATER_THAN:
            return observed_value > threshold_value
        elif comparison == hc_types.ComparisonType.EQUAL_TO:
            return observed_value == threshold_value
        else:
            raise ValueError(f"Unsupported comparison type: {comparison}")

    async def skip_check(self, obj: TestDevice) -> t.Tuple[bool, t.Optional[str]]:
        supported_roles = ["BAG"]
        if obj.attributes.role not in supported_roles:
            return True, f"{obj.name}'s device role is not in {supported_roles}"
        return False, None
