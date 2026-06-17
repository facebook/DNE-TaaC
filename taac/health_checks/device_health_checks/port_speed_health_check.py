# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-strict

import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.utils.common import async_everpaste_str
from taac.health_check.health_check import types as hc_types


class PortSpeedHealthCheck(AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]):
    CHECK_NAME: hc_types.CheckName = hc_types.CheckName.PORT_SPEED_CHECK

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        device_interfaces = check_params.get(obj.name, {}).get("interfaces", [])

        """
        Format of check_params:
        check_params = {
            "<device_name>": {
                "interfaces": [
                    {"interface_name": "eth1/1/1", "expected_speed": 100},
                ]
            }
        }
        """
        if not device_interfaces:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message="No interfaces provided for port speed check",
            )

        failure_reasons = []
        interface_name_to_expected_speed = {}
        for interface in device_interfaces:
            interface_name = interface.get("interface_name", None)
            expected_speed = interface.get("expected_speed", None)
            if not interface_name or not expected_speed:
                failure_reasons.append(
                    f"Interface name or expected speed not provided for {obj.name}"
                )
            else:
                interface_name_to_expected_speed[interface_name] = expected_speed

        # pyrefly: ignore [missing-attribute]
        interface_port_speed = await self.driver.async_get_interfaces_speed_in_Gbps(
            interface_names=list(interface_name_to_expected_speed.keys())
        )

        for iface, speed in interface_name_to_expected_speed.items():
            if iface not in interface_port_speed:
                failure_reasons.append(
                    f"Interface {obj.name}:{iface} not found in device"
                )
            elif speed != interface_port_speed.get(iface):
                failure_reasons.append(
                    f"Interface {obj.name}:{iface} is expected to be {speed} but is {interface_port_speed.get(iface)}"
                )

        if failure_reasons:
            # Use the Everpaste URL directly; it is already a clickable internalfb.com
            # link, so the throttled fburl tier (createFBUrl) is unnecessary here.
            everpaste_url = await async_everpaste_str("\n".join(failure_reasons))
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"Found {len(failure_reasons)} interface speed mismatch(es) on {obj.name}: "
                f"{failure_reasons[:5]}"
                + (
                    f" (+{len(failure_reasons) - 5} more)"
                    if len(failure_reasons) > 5
                    else ""
                )
                + f". Full details: {everpaste_url}",
            )

        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=f"All {len(device_interfaces)} interfaces on {obj.name} have expected speed",
        )
