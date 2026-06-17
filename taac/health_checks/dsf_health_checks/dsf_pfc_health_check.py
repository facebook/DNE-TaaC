# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.utils.common import async_everpaste_str
from taac.utils.health_check_utils import get_fb303_client
from taac.health_check.health_check import types as hc_types


class DsfPfcHealthCheck(AbstractDeviceHealthCheck[hc_types.DsfPfcHealthCheckIn]):
    CHECK_NAME: hc_types.CheckName = hc_types.CheckName.DSF_PFC_CHECK

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.DsfPfcHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        operating_system = obj.attributes.operating_system
        match operating_system:
            case "FBOSS":
                return await self._run_fboss_pfc_health_check(obj, input, check_params)
            case "EOS":
                return await self._run_eos_pfc_health_check(obj, input, check_params)
            case _:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=f"Unsupported operating system: {operating_system}",
                )

    async def _run_fboss_pfc_health_check(
        self,
        obj: TestDevice,
        input: hc_types.DsfPfcHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        for threshold in input.thresholds:
            for endpoint in threshold.interfaces:
                device, interface = endpoint.split(":")

                priority = int(threshold.priority)

                # Fetch counters for the interface from the selected device
                try:
                    async with await get_fb303_client(device) as client:
                        counter = await client.getSelectedCounters(
                            [
                                f"{interface}.out_pfc_frames.priority{priority}.sum.60",
                                f"{interface}.in_pfc_frames.priority{priority}.sum.60",
                            ]
                        )
                    out_pfc = counter.get(
                        f"{interface}.out_pfc_frames.priority{priority}.sum.60", 0
                    )
                    in_pfc = counter.get(
                        f"{interface}.in_pfc_frames.priority{priority}.sum.60", 0
                    )
                    self.logger.info(
                        f"At {endpoint} priority{priority} observed - in_pfc: {in_pfc}, out_pfc: {out_pfc}"
                    )

                except Exception as e:
                    return hc_types.HealthCheckResult(
                        status=hc_types.HealthCheckStatus.FAIL,
                        message=f"Failed to fetch priority{priority} counters for {device} {interface}: {str(e)}",
                    )

                # Check out_pfc if threshold is provided
                if threshold.out_pfc is not None:
                    if await self._compare_pfc(
                        threshold.comparison, out_pfc, threshold.out_pfc
                    ):
                        return await self.create_failure_result(
                            device,
                            interface,
                            "out_pfc",
                            out_pfc,
                            threshold.out_pfc,
                            threshold.comparison,
                            priority,
                        )

                # Check in_pfc if threshold is provided
                if threshold.in_pfc is not None:
                    if await self._compare_pfc(
                        threshold.comparison, in_pfc, threshold.in_pfc
                    ):
                        return await self.create_failure_result(
                            device,
                            interface,
                            "in_pfc",
                            in_pfc,
                            threshold.in_pfc,
                            threshold.comparison,
                            priority,
                        )

        # Return PASS if no failures
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
        )

    async def _run_eos_pfc_health_check(
        self,
        obj: TestDevice,
        input: hc_types.DsfPfcHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        for threshold in input.thresholds:
            for endpoint in threshold.interfaces:
                device, interface = endpoint.split(":")
                priority = int(threshold.priority)
                try:
                    counters = await self._get_eos_pfc_counters(interface, priority)
                    out_pfc = counters["txFrames"]
                    in_pfc = counters["rxFrames"]
                    self.logger.info(
                        f"At {endpoint} priority{priority} observed - in_pfc: {in_pfc}, out_pfc: {out_pfc}"
                    )
                except Exception as e:
                    return hc_types.HealthCheckResult(
                        status=hc_types.HealthCheckStatus.FAIL,
                        message=f"Failed to fetch priority{priority} counters for {device} {interface}: {str(e)}",
                    )

                # Check out_pfc if threshold is provided
                if threshold.out_pfc is not None:
                    if await self._compare_pfc(
                        threshold.comparison, out_pfc, threshold.out_pfc
                    ):
                        return await self.create_failure_result(
                            device,
                            interface,
                            "out_pfc",
                            out_pfc,
                            threshold.out_pfc,
                            threshold.comparison,
                            priority,
                        )

                # Check in_pfc if threshold is provided
                if threshold.in_pfc is not None:
                    if await self._compare_pfc(
                        threshold.comparison, in_pfc, threshold.in_pfc
                    ):
                        return await self.create_failure_result(
                            device,
                            interface,
                            "in_pfc",
                            in_pfc,
                            threshold.in_pfc,
                            threshold.comparison,
                            priority,
                        )

        # Return PASS if no failures
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
        )

    async def _get_eos_pfc_counters(
        self,
        interface: str,
        priority: int,
    ) -> t.Dict[str, int]:
        cmd = f"show interface {interface} priority-flow-control counters detail | json"
        # pyrefly: ignore [missing-attribute]
        response = await self.driver.async_execute_show_json_on_shell(cmd)
        return response["interfaces"][interface]["priorities"][str(priority)]

    async def create_failure_result(
        self,
        device: str,
        interface: str,
        pfc_type,
        observed_pfc,
        threshold_value,
        threshold_comparison,
        priority: int,
    ):
        # Use the Everpaste URL directly; it is already a clickable internalfb.com
        # link, so the throttled fburl tier (createFBUrl) is unnecessary here.
        everpaste_url = await async_everpaste_str(f"{pfc_type}: {observed_pfc}")
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.FAIL,
            message=f"Traffic on {device} {interface} for {pfc_type} (priority {priority}) exceeds the threshold of {threshold_value}. "
            f"Observed {pfc_type}: {observed_pfc}. Failure report: {everpaste_url}",
        )

    async def _compare_pfc(
        self,
        comparison: hc_types.ComparisonType,
        observed_pfc: int,
        threshold_value: int = 0,
    ) -> bool:
        """
        Helper function to compare the observed PFC value with the threshold based on the comparison type.
        """
        if comparison == hc_types.ComparisonType.LESS_THAN:
            return observed_pfc >= threshold_value
        elif comparison == hc_types.ComparisonType.GREATER_THAN:
            return observed_pfc <= threshold_value
        elif comparison == hc_types.ComparisonType.EQUAL_TO:
            return observed_pfc != threshold_value
        return False

    async def skip_check(self, obj: TestDevice) -> t.Tuple[bool, str | None]:
        supported_roles = ["RDSW", "FDSW", "EDSW", "DTSW", "RTSW", "SUSW", "BAG"]
        if obj.attributes.role not in supported_roles:
            return True, f"{obj.name}'s device role is not in {supported_roles}"
        return False, None
