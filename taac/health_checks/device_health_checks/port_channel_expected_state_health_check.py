# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_check.health_check import types as hc_types


class PortChannelExpectedStateHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn],
):
    CHECK_NAME = hc_types.CheckName.PORT_CHANNEL_EXPECTED_STATE_CHECK
    OPERATING_SYSTEMS = ["FBOSS", "EOS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        port_channel_names_map = check_params["port_channel_names"]
        expected_up = check_params.get("expected_up", True)

        device_port_channels = port_channel_names_map.get(obj.name, None)

        if device_port_channels is None:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"Port-channel not found for {obj.name}",
            )

        if isinstance(device_port_channels, str):
            device_port_channels = [device_port_channels]

        if obj.attributes.operating_system == "EOS":
            pc_status_map = await self._get_eos_port_channel_status_map()
        else:
            pc_status_map = await self._get_fboss_port_channel_status_map()

        failures = []
        for port_channel_name in device_port_channels:
            is_up = pc_status_map.get(port_channel_name)

            if is_up is None:
                failures.append(
                    f"Port-channel {port_channel_name} not found on {obj.name}"
                )
            elif expected_up and not is_up:
                failures.append(
                    f"Port-channel {port_channel_name} expected UP but is DOWN on {obj.name}"
                )
            elif not expected_up and is_up:
                failures.append(
                    f"Port-channel {port_channel_name} expected DOWN but is UP on {obj.name}"
                )

        if failures:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message="; ".join(failures),
            )

        expected_state = "UP" if expected_up else "DOWN"
        checked = ", ".join(device_port_channels)
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=f"Port-channel(s) {checked} are {expected_state} as expected on {obj.name}",
        )

    async def _get_fboss_port_channel_status_map(self) -> t.Dict[str, bool]:
        # pyrefly: ignore [missing-attribute]
        agg_ports = await self.driver.async_get_all_aggregated_port_info()
        return {p.name: p.isUp for p in agg_ports}

    async def _get_eos_port_channel_status_map(self) -> t.Dict[str, bool]:
        # pyre-fixme[16]: `AbstractSwitch` has no attribute
        #  `async_get_port_channel_detailed_info`.
        output = await self.driver.async_get_port_channel_detailed_info()
        port_channels = output.get("portChannels", {})
        return {
            name: bool(data.get("activePorts", {}))
            and not data.get("inactiveLag", False)
            for name, data in port_channels.items()
        }
