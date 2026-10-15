# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.utils.json_thrift_utils import try_json_loads
from taac.health_check.health_check import types as hc_types


class PortTransceiverHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    CHECK_NAME = hc_types.CheckName.PORT_TRANSCEIVER_CHECK
    # async_get_all_interface_to_qsfp_info_mapping only exists on FbossSwitch.
    OPERATING_SYSTEMS = ["FBOSS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        explicit_interfaces = check_params.get("interfaces", [])
        if isinstance(explicit_interfaces, str):
            explicit_interfaces = try_json_loads(explicit_interfaces, [])
        if not isinstance(explicit_interfaces, list):
            # A malformed `interfaces` falls back to the (broader) topology
            # set below, which is the opposite of what a narrowing param
            # failing to parse should do -- make that loud.
            self.logger.warning(
                f"{self.__class__.CHECK_NAME}: `interfaces` param on "
                f"{obj.name} did not decode to a list ({explicit_interfaces!r}); "
                "falling back to the device's topology interfaces."
            )
            explicit_interfaces = []
        expected_present = check_params.get("expected_present")
        if expected_present is None:
            expected_present = True
        elif isinstance(expected_present, str):
            expected_present = expected_present.strip().lower() not in (
                "",
                "0",
                "false",
                "no",
            )

        # Explicit `interfaces` narrows the assertion rather than widening
        # it (same idea as `disabled_interfaces` on PortStateHealthCheck):
        # `expected_present` applies to the whole set, so a caller pulling
        # one transceiver on a device with several topology interfaces
        # (e.g. a snake circuit, where both circuit ends share a hostname)
        # must be able to name just that one interface.
        if explicit_interfaces:
            interface_names = sorted(set(explicit_interfaces))
        else:
            interface_names = sorted(
                {interface.interface_name for interface in obj.interfaces}
            )

        # Same SKIP-not-PASS guard as PortStateHealthCheck: with no topology
        # interfaces and no explicit `interfaces` param, there is nothing to
        # assert, so a single-endpoint TestConfig would otherwise report a
        # silent PASS.
        if not interface_names:
            message = (
                f"No in-topology interfaces to validate on {obj.name}, so this "
                "check asserted nothing. Declare the neighbor device(s) as "
                "`Endpoint(dut=False)`, or pass `interfaces`, to make it "
                "meaningful."
            )
            self.logger.warning(f"{self.__class__.CHECK_NAME}: {message}")
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=message,
            )

        intf_to_transceiver = (
            # pyrefly: ignore [missing-attribute]
            await self.driver.async_get_all_interface_to_qsfp_info_mapping()
        )
        failure_reasons = []
        for interface_name in interface_names:
            transceiver = intf_to_transceiver.get(interface_name)
            if transceiver is None:
                present = False
                detail = "was not reported by qsfp_service"
            else:
                present = bool(
                    transceiver.tcvrState and transceiver.tcvrState.present
                )
                detail = (
                    "has a transceiver present"
                    if present
                    else "has no transceiver present"
                )
            if present != expected_present:
                failure_reasons.append(
                    f"Interface {obj.name}:{interface_name} {detail}, expected "
                    f"{'present' if expected_present else 'absent'}"
                )

        if failure_reasons:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"Found {len(failure_reasons)} transceiver presence "
                f"mismatch(es) on {obj.name}: {failure_reasons[:5]}"
                + (
                    f" (+{len(failure_reasons) - 5} more)"
                    if len(failure_reasons) > 5
                    else ""
                ),
            )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
        )
