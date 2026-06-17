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
from taac.utils.oss_taac_lib_utils import (
    async_retryable,
    to_fb_fqdn,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types


def is_fabric_interface(name: str) -> bool:
    return "fab" in name


class LldpHealthCheck(AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]):
    CHECK_NAME = hc_types.CheckName.LLDP_CHECK
    OPERATING_SYSTEMS = [
        "FBOSS",
        "EOS",
    ]

    def _get_enabled_and_disabled_interfaces(
        self,
        obj: TestDevice,
        check_params: t.Dict[str, t.Any],
    ) -> t.Tuple[t.List[taac_types.TestInterface], t.List[taac_types.TestInterface]]:
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
        enabled_interfaces = []
        for interface in obj.interfaces:
            if (
                interface.interface_name not in disabled_interface_names
                and not is_fabric_interface(interface.interface_name)
            ):
                enabled_interfaces.append(interface)
        return enabled_interfaces, disabled_interfaces

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        enabled_interfaces, disabled_interfaces = (
            self._get_enabled_and_disabled_interfaces(obj, check_params)
        )
        await self.async_validate_lldp_neighbors(
            enabled_interfaces, disabled_interfaces
        )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
        )

    async def _run_arista(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        enabled_interfaces, disabled_interfaces = (
            self._get_enabled_and_disabled_interfaces(obj, check_params)
        )
        await self.async_validate_lldp_neighbors(
            enabled_interfaces, disabled_interfaces
        )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
        )

    @async_retryable(retries=3, sleep_time=2, exceptions=(Exception,))
    async def async_validate_lldp_neighbors(
        self,
        enabled_interfaces: t.List[taac_types.TestInterface],
        disabled_interfaces: t.List[taac_types.TestInterface],
    ) -> None:
        # pyrefly: ignore [missing-attribute]
        lldp_neighbors = await self.driver.async_get_lldp_neighbors()

        failure_reasons = []
        # down interfaces should not have LLDP neighbors
        for interface in disabled_interfaces:
            if interface.interface_name in lldp_neighbors:
                failure_reasons.append(
                    f"Interface {interface.interface_name} is expected to be DOWN, but an unexpected LLDP entry was found."
                )
        for interface in enabled_interfaces:
            lldp_neighbor = lldp_neighbors.get(interface.interface_name)
            if lldp_neighbor:
                expected_lldp_neighbors = interface.neighbor_display_name
                actual_lldp_neighbors = f"{to_fb_fqdn(lldp_neighbor.remote_device_name)}:{lldp_neighbor.remote_intf_name}"
                if expected_lldp_neighbors != actual_lldp_neighbors:
                    failure_reasons.append(
                        f"Interface {interface.interface_name} expects LLDP neighbor {expected_lldp_neighbors}, but found {actual_lldp_neighbors} instead."
                    )
            else:
                failure_reasons.append(
                    f"Interface {interface.interface_name} is expected to be UP, but no LLDP entry was found."
                )
        if failure_reasons:
            # Use the Everpaste URL directly; it is already a clickable internalfb.com
            # link, so the throttled fburl tier (createFBUrl) is unnecessary here.
            everpaste_url = await async_everpaste_str("\n".join(failure_reasons))
            inline_summary = failure_reasons[:5]
            suffix = (
                f" (+{len(failure_reasons) - 5} more)"
                if len(failure_reasons) > 5
                else ""
            )
            raise Exception(
                f"LLDP validation failed with {len(failure_reasons)} issue(s): "
                f"{inline_summary}{suffix}. Full details: {everpaste_url}"
            )
