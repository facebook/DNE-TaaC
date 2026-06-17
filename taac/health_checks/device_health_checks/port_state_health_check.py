# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.utils.common import async_everpaste_str
from taac.utils.json_thrift_utils import (
    try_json_loads,
    try_json_to_thrift,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types


class PortStateHealthCheck(AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]):
    CHECK_NAME = hc_types.CheckName.PORT_STATE_CHECK

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        disabled_interfaces = check_params.get("disabled_interfaces", [])
        if isinstance(disabled_interfaces, str):
            disabled_interfaces = try_json_loads(disabled_interfaces, [])
        if disabled_interfaces:
            disabled_interfaces = [
                try_json_to_thrift(interface, taac_types.TestInterface)
                for interface in disabled_interfaces
            ]
        disabled_interface_names = set()
        for disabled_interface in disabled_interfaces:
            if disabled_interface.switch_name == obj.name:
                disabled_interface_names.add(disabled_interface.interface_name)
            if disabled_interface.neighbor_switch_name == obj.name:
                disabled_interface_names.add(disabled_interface.neighbor_interface_name)
        enabled_interface_names = [
            interface.interface_name
            for interface in obj.interfaces
            if interface.interface_name not in disabled_interface_names
        ]
        interfaces_oper_state = (
            # pyrefly: ignore [missing-attribute]
            await self.driver.async_get_all_interfaces_operational_status()
        )
        failure_reasons = []
        for interface in enabled_interface_names:
            if not interfaces_oper_state.get(interface):
                failure_reasons.append(
                    f"Interface {obj.name}:{interface} is expected to be UP but is DOWN"
                )
        for interface in disabled_interface_names:
            if interfaces_oper_state.get(interface):
                failure_reasons.append(
                    f"Interface {obj.name}:{interface} is expected to be DOWN but is UP"
                )

        # Check additional (non-topology) interfaces for AdminState/LinkState consistency
        additional_interfaces = check_params.get("additional_interfaces", [])
        if additional_interfaces:
            additional_interface_names = [
                entry["interface_name"]
                for entry in additional_interfaces
                if entry.get("switch_name") == obj.name
            ]
            if additional_interface_names:
                interfaces_admin_state = (
                    # pyrefly: ignore [missing-attribute]
                    await self.driver.async_get_all_interfaces_admin_status()
                )
                for interface in additional_interface_names:
                    admin_enabled = interfaces_admin_state.get(interface, False)
                    oper_up = interfaces_oper_state.get(interface, False)
                    if admin_enabled and not oper_up:
                        failure_reasons.append(
                            f"Interface {obj.name}:{interface} AdminState is Enabled but LinkState is Down"
                        )
                    elif not admin_enabled and oper_up:
                        failure_reasons.append(
                            f"Interface {obj.name}:{interface} AdminState is Disabled but LinkState is Up"
                        )

        if failure_reasons:
            # Use the Everpaste URL directly; it is already a clickable internalfb.com
            # link, so the throttled fburl tier (createFBUrl) is unnecessary here.
            everpaste_url = await async_everpaste_str("\n".join(failure_reasons))
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"Found {len(failure_reasons)} interface operational state mismatch(es) on {obj.name}: "
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
        )
