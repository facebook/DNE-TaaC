# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import asyncio
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.utils.common import async_everpaste_str
from taac.utils.health_check_utils import get_fb303_client
from taac.health_check.health_check import types as hc_types


class PfcWdHealthCheck(AbstractDeviceHealthCheck[hc_types.PfcWdHealthCheckIn]):
    CHECK_NAME: hc_types.CheckName = hc_types.CheckName.PFC_WD_CHCEK

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.PfcWdHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        operating_system = obj.attributes.operating_system
        match operating_system:
            case "FBOSS":
                return await self._run_fboss_pfc_wd_health_check(
                    obj, input, check_params
                )
            case "EOS":
                return await self._run_eos_pfc_wd_health_check(obj, input, check_params)
            case _:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=f"Unsupported operating system: {operating_system}",
                )

    async def _run_fboss_pfc_wd_health_check(
        self,
        obj: TestDevice,
        input: hc_types.PfcWdHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        for threshold in input.thresholds:
            for endpoint in threshold.interfaces:
                device, interface = endpoint.split(":")
                # Fetch counters for the interface from the selected device
                try:
                    async with await get_fb303_client(device) as client:
                        counter = await client.getSelectedCounters(
                            [
                                f"{interface}.pfc_deadlock_detection.sum.60",
                                f"{interface}.pfc_deadlock_recovery.sum.60",
                            ]
                        )
                    deadlock = counter.get(
                        f"{interface}.pfc_deadlock_detection.sum.60", 0
                    )
                    recovery = counter.get(
                        f"{interface}.pfc_deadlock_recovery.sum.60", 0
                    )
                    self.logger.info(
                        f"At {endpoint} observed - pfc_deadlock_detection: {deadlock}, "
                        f"pfc_deadlock_recovery: {recovery}"
                    )

                    # Check for deadlock but no recovery
                    if deadlock > 0 and recovery == 0:
                        return hc_types.HealthCheckResult(
                            status=hc_types.HealthCheckStatus.FAIL,
                            message=f"Deadlock detected on {device} {interface} but no recovery happened",
                        )

                    (
                        is_violated,
                        message,
                    ) = await self._check_threshold_condition_violated(
                        threshold.comparison,
                        deadlock,
                        recovery,
                        threshold.deadlock_threshold,
                        threshold.recovery_threshold,
                    )
                    if is_violated:
                        return await self.create_failure_result(
                            device, interface, deadlock, recovery, message
                        )
                except Exception as e:
                    return hc_types.HealthCheckResult(
                        status=hc_types.HealthCheckStatus.FAIL,
                        message=f"Failed to fetch counters for {device} {interface}: {str(e)}",
                    )

        # Return PASS if no issues were found
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
        )

    # For Arista EOS devices, the PFC watchdog health check must follow this specific sequence:
    # 1. Clear the watchdog counters
    # 2. Start traffic
    # 3. Stop traffic
    # 4. Fetch the watchdog counters
    #
    # This order is critical because:
    # - The "Stuck" counter updates at the start of traffic.
    # - The "Recovery" counter updates at the end of traffic.
    async def _run_eos_pfc_wd_health_check(
        self,
        obj: TestDevice,
        input: hc_types.PfcWdHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        if self.ixia is None:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message="ixia is None, failed to stop traffics and fetch PFC watchdog counters",
            )
        ixia = self.ixia
        # Check the counters for each interface
        for threshold in input.thresholds:
            for endpoint in threshold.interfaces:
                device, interface = endpoint.split(":")
                try:
                    self.logger.info("Stopping traffic to fetch PFC watchdog counters")
                    ixia.stop_traffic()
                    await asyncio.sleep(3)
                    counters = await self._get_eos_pfc_wd_counters(interface)
                    stuck_count = counters.get("stuckCount", 0)
                    recovery_count = counters.get("recoveryCount", 0)
                    self.logger.info(
                        f"At {endpoint} observed - PFC watchdog stuck count: {stuck_count}, "
                        f"recovery count: {recovery_count}"
                    )

                    # Check for watchdog stuck but no recovery
                    if stuck_count > 0 and recovery_count == 0:
                        return hc_types.HealthCheckResult(
                            status=hc_types.HealthCheckStatus.FAIL,
                            message=f"Stuck detected on {device} {interface} but no recovery happened",
                        )

                    (
                        is_violated,
                        message,
                    ) = await self._check_threshold_condition_violated(
                        threshold.comparison,
                        stuck_count,
                        recovery_count,
                        threshold.deadlock_threshold,
                        threshold.recovery_threshold,
                    )
                    if is_violated:
                        return await self.create_failure_result(
                            device, interface, stuck_count, recovery_count, message
                        )
                except Exception as e:
                    return hc_types.HealthCheckResult(
                        status=hc_types.HealthCheckStatus.FAIL,
                        message=f"Failed to fetch counters for {device} {interface}: {str(e)}",
                    )

        # Return PASS if no failures
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
        )

    async def _get_eos_pfc_wd_counters(self, interface: str) -> t.Dict[str, int]:
        cmd = "show priority-flow-control counters watchdog | json"
        # pyrefly: ignore [missing-attribute]
        response = await self.driver.async_execute_show_json_on_shell(cmd)
        # Arista returns {"interfaces": {}} when no WD event has fired on any
        # interface, and omits an interface key entirely until that interface
        # has had its first event. Both states are functionally equivalent to
        # stuckCount=0, recoveryCount=0 — treat missing keys as zero.
        tx_queue_data = (
            response.get("interfaces", {})
            .get(interface, {})
            .get("txQueues", {})
            .get("2", {})
        )
        return {
            "stuckCount": tx_queue_data.get("stuckCount", 0),
            "recoveryCount": tx_queue_data.get("recoveryCount", 0),
        }

    async def _check_threshold_condition_violated(
        self,
        comparison: hc_types.ComparisonType,
        deadlock: int,
        recovery: int,
        deadlock_threshold: int = 0,
        recovery_threshold: int = 0,
    ) -> t.Tuple[bool, str]:
        if comparison == hc_types.ComparisonType.LESS_THAN:
            if deadlock >= deadlock_threshold or recovery >= recovery_threshold:
                return True, "Deadlock or Recovery threshold exceeded"
        elif comparison == hc_types.ComparisonType.GREATER_THAN:
            if deadlock <= deadlock_threshold or recovery <= recovery_threshold:
                return True, "Deadlock or Recovery value less than expected threshold"
        elif comparison == hc_types.ComparisonType.EQUAL_TO:
            if deadlock != deadlock_threshold or recovery != recovery_threshold:
                return (
                    True,
                    "Deadlock or Recovery value does not match the expected threshold",
                )
        return False, ""

    async def create_failure_result(
        self,
        device: str,
        interface: str,
        deadlock: int,
        recovery: int,
        failure_message: str,
    ) -> hc_types.HealthCheckResult:
        # Use the Everpaste URL directly; it is already a clickable internalfb.com
        # link, so the throttled fburl tier (createFBUrl) is unnecessary here.
        everpaste_url = await async_everpaste_str(
            f"Deadlock: {deadlock}, Recovery: {recovery}"
        )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.FAIL,
            message=f"{failure_message} on {device} {interface}. "
            f"Observed Deadlock: {deadlock}, Recovery: {recovery}. Failure report: {everpaste_url}",
        )

    async def skip_check(self, obj: TestDevice) -> t.Tuple[bool, str | None]:
        supported_roles = ["RDSW", "FDSW", "EDSW", "DTSW", "RTSW", "SUSW", "BAG"]
        if obj.attributes.role not in supported_roles:
            return True, f"{obj.name}'s device role is not in {supported_roles}"
        return False, None
