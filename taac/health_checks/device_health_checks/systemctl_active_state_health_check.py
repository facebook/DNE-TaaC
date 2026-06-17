# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import asyncio
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_check.health_check import types as hc_types

DEFAULT_SERVICE_NAMES: t.List[str] = list(hc_types.SERVICE_NAME_MAP.values())


class SystemctlActiveStateHealthCheck(
    AbstractDeviceHealthCheck[hc_types.SystemctlActiveStateHealthCheckIn]
):
    CHECK_NAME = hc_types.CheckName.SYSTEMCTL_ACTIVE_STATE_CHECK
    OPERATING_SYSTEMS = ["FBOSS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.SystemctlActiveStateHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        if input.services:
            service_names = [
                hc_types.SERVICE_NAME_MAP[service] for service in input.services
            ]
        else:
            service_names = DEFAULT_SERVICE_NAMES

        results = await asyncio.gather(
            *[
                self.async_is_systemctl_service_active(obj.name, service)
                for service in service_names
            ]
        )
        inactive_services = [
            service for service, result in zip(service_names, results) if not result
        ]
        if inactive_services:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"Systemctl service(s) {inactive_services} are not active on {obj.name}",
            )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
        )

    async def async_is_systemctl_service_active(
        self, hostname: str, service: str
    ) -> bool:
        cmd = f"systemctl show {service} --no-page"
        # pyrefly: ignore [missing-attribute]
        output = await self.driver.async_run_cmd_on_shell(cmd)
        systemctl_unit_data = {}
        for line in output.split("\n"):
            splitted_line = line.split("=")
            if len(splitted_line) == 2:
                systemctl_unit_data[splitted_line[0]] = splitted_line[1]
        if systemctl_unit_data.get("UnitFileState") == "disabled":
            self.logger.debug(
                "Systemctl service is disabled on the device. Skipping..."
            )
            return True
        if systemctl_unit_data["LoadState"] != "loaded":
            self.logger.debug(
                f"Systemctl service {service} is not loaded on {hostname}... Skipping"
            )
            return True

        self.logger.debug(
            f"The active state of the systemctl service {service} is: {systemctl_unit_data['ActiveState']}"
        )
        return systemctl_unit_data["ActiveState"] == "active"
