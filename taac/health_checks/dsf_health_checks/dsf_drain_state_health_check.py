# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import typing as t

from neteng.fboss.switch_config.thrift_types import SwitchDrainState
from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_check.health_check import types as hc_types


class DsfDrainStateHealthCheck(
    AbstractDeviceHealthCheck[hc_types.DsfDrainStateCheckIn]
):
    CHECK_NAME = hc_types.CheckName.DSF_DRAIN_STATE_CHECK
    OPERATING_SYSTEMS = ["FBOSS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.DsfDrainStateCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        # pyrefly: ignore [missing-attribute]
        is_switch_drained = await self.driver.async_is_switch_drained()
        actual_switch_drain_state = (
            # pyrefly: ignore [missing-attribute]
            await self.driver.async_get_actual_switch_drain_state()
        )

        is_drained = is_switch_drained or any(
            drain_state != SwitchDrainState.UNDRAINED
            for drain_state in actual_switch_drain_state.values()
        )

        if is_drained and not input.is_drained:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"{obj.name} is in a drained state: isSwitchDrained={is_switch_drained}, actualSwitchDrainState={actual_switch_drain_state}",
            )
        elif not is_drained and input.is_drained:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"{obj.name} is not in a drained state but expected to be: isSwitchDrained={is_switch_drained}, actualSwitchDrainState={actual_switch_drain_state}",
            )
        else:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.PASS,
            )

    async def skip_check(self, obj: TestDevice) -> t.Tuple[bool, str | None]:
        supported_roles = ["RDSW", "FDSW", "EDSW"]
        if obj.attributes.role not in supported_roles:
            return True, f"{obj.name}'s device role is not in {supported_roles}"
        return False, None
