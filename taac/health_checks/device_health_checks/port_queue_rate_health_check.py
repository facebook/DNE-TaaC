# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.utils.common import async_everpaste_str
from taac.health_check.health_check import types as hc_types


class PortQueueRateHealthCheck(
    AbstractDeviceHealthCheck[hc_types.PortQueueRateHealthCheckIn]
):
    CHECK_NAME: hc_types.CheckName = hc_types.CheckName.PORT_QUEUE_RATE_CHECK
    OPERATING_SYSTEMS = ["EOS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.PortQueueRateHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        for threshold in input.thresholds:
            for endpoint in threshold.interfaces:
                device, interface = endpoint.split(":")
                try:
                    all_tc_percent = await self._get_all_tc_rate_percent(interface)
                except Exception as e:
                    return hc_types.HealthCheckResult(
                        status=hc_types.HealthCheckStatus.FAIL,
                        message=f"Failed to fetch queue rates for {interface} on device {device}: {str(e)}",
                    )
                for prio_threshold in threshold.priority_rate_thresholds:
                    tc_key = f"TC{int(prio_threshold.priority)}"
                    observed_tc_rate_percent = all_tc_percent.get(tc_key, 0)
                    self.logger.info(
                        f"Observed queue rate at {interface} {tc_key}: {observed_tc_rate_percent}%"
                    )
                    if not await self._compare_counters(
                        prio_threshold.comparison,
                        observed_tc_rate_percent,
                        prio_threshold.rate_percent,
                    ):
                        return await self.create_failure_result(
                            interface,
                            tc_key,
                            observed_tc_rate_percent,
                            prio_threshold.rate_percent,
                        )

        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
        )

    async def _get_all_tc_rate_percent(
        self,
        interface: str,
    ) -> t.Dict[str, int]:
        """
        Fetches the queue counters for all unicast traffic classes (TCs) on the given interface,
        calculates each TC's enqueued bits rate as a percentage of the total,
        and returns a dictionary mapping TC names (e.g., "TC0") to integer percentages.
        Returns:
            Dict[str, int]: Mapping from TC name to rate percentage.
        """
        cmd = f"show interfaces {interface} counters queue rates | json"
        # pyrefly: ignore [missing-attribute]
        response = await self.driver.async_execute_show_json_on_shell(cmd)
        tc_enqueued_bits_rates = {}
        interface_data = response["egressQueueCounters"]["interfaces"][interface]
        ucast_tcs = interface_data.get("ucastQueues").get("trafficClasses")
        for tc, tc_data in ucast_tcs.items():
            counts = tc_data["dropPrecedences"]["DP0"]
            tc_enqueued_bits_rates[tc] = counts["enqueuedBitsRate"]
        total_enqueued_bits_rate = sum(tc_enqueued_bits_rates.values())
        # Avoid division by zero
        if total_enqueued_bits_rate == 0:
            return {tc: 0 for tc in tc_enqueued_bits_rates}
        # Calculate and return percentage per TC
        return {
            tc: int(round((enqueued_bits_rate / total_enqueued_bits_rate) * 100))
            for tc, enqueued_bits_rate in tc_enqueued_bits_rates.items()
        }

    async def create_failure_result(
        self,
        interface: str,
        tc: str,
        observed_value: int,
        threshold_value: int,
    ):
        # Use the Everpaste URL directly; it is already a clickable internalfb.com
        # link, so the throttled fburl tier (createFBUrl) is unnecessary here.
        everpaste_url = await async_everpaste_str(
            f"Rate Percent: {observed_value}% on {interface} {tc}"
        )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.FAIL,
            message=f"Traffic on {interface} {tc} did not meet the threshold of {threshold_value}%. "
            f"Observed: {interface} {tc}: {observed_value}%. Failure report: {everpaste_url}",
        )

    async def _compare_counters(
        self,
        comparison: hc_types.ComparisonType,
        observed_value: int,
        threshold_value: int = 0,
    ) -> bool:
        """
        Helper function to compare the observed queue rate percentage with the threshold
        based on the specified comparison type.
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
