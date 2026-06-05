# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

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
        port_channel_name = check_params["port_channel_name"]
        expected_up = check_params.get("expected_up", True)

        if obj.attributes.operating_system == "EOS":
            is_up = await self._get_eos_port_channel_up(port_channel_name)
        else:
            is_up = await self._get_fboss_port_channel_up(port_channel_name)

        if is_up is None:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"Port-channel {port_channel_name} not found on {obj.name}",
            )

        if expected_up and not is_up:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"Port-channel {port_channel_name} expected UP but is DOWN on {obj.name}",
            )
        if not expected_up and is_up:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"Port-channel {port_channel_name} expected DOWN but is UP on {obj.name}",
            )

        expected_state = "UP" if expected_up else "DOWN"
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=f"Port-channel {port_channel_name} is {expected_state} as expected on {obj.name}",
        )

    async def _get_fboss_port_channel_up(
        self, port_channel_name: str
    ) -> t.Optional[bool]:
        agg_ports = await self.driver.async_get_all_aggregated_port_info()
        pc_info = next((p for p in agg_ports if p.name == port_channel_name), None)
        if pc_info is None:
            return None
        return pc_info.isUp

    async def _get_eos_port_channel_up(
        self, port_channel_name: str
    ) -> t.Optional[bool]:
        # pyre-fixme[16]: `AbstractSwitch` has no attribute
        #  `async_get_port_channel_detailed_info`.
        output = await self.driver.async_get_port_channel_detailed_info()
        port_channels = output.get("portChannels", {})
        pc_data = port_channels.get(port_channel_name)
        if pc_data is None:
            return None
        active_ports = pc_data.get("activePorts", {})
        inactive_lag = pc_data.get("inactiveLag", False)
        return bool(active_ports) and not inactive_lag
