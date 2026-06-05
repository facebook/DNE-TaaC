# pyre-unsafe
import asyncio
import typing as t

from taac.steps.step import Step
from taac.utils.driver_factory import async_get_device_driver
from taac.utils.json_thrift_utils import (
    try_json_loads,
    try_json_to_thrift,
)
from taac.test_as_a_config import types as taac_types


class InterfaceFlapStep(Step[taac_types.BaseInput]):
    STEP_NAME = taac_types.StepName.INTERFACE_FLAP_STEP

    async def run(
        self,
        input: taac_types.BaseInput,
        params: t.Dict[str, t.Any],
    ) -> None:
        interfaces = params["interfaces"]
        device_name = params.get("device_name", self.device.name)
        self.driver = await async_get_device_driver(device_name)
        print("Inside InterfaceFlapStep")
        print(interfaces)
        test_interfaces: t.List[taac_types.TestInterface] = [
            t.cast(
                taac_types.TestInterface,
                try_json_to_thrift(interface, taac_types.TestInterface),
            )
            for interface in try_json_loads(interfaces)
        ]
        interfaces = [iface.interface_name for iface in test_interfaces]
        delay = params.get("delay", 5)
        enable = params["enable"]
        sequential = params.get("sequential", False)
        interface_flap_method = taac_types.InterfaceFlapMethod(
            params["interface_flap_method"]
        )
        await self.async_flap_interfaces(
            device_name,
            interfaces,
            interface_flap_method,
            enable,
            sequential,
        )
        if delay:
            self.logger.info(f"Sleeping for {delay} seconds...")
            await asyncio.sleep(delay)

    async def async_flap_interfaces(
        self,
        hostname: str,
        interface_names: t.List[str],
        interface_flap_method: taac_types.InterfaceFlapMethod,
        enable: bool,
        sequential: bool,
    ) -> None:
        # Lazy import of internal driver class.
        from taac.internal.driver.arista_switch import (
            AristaSwitch,
        )

        if (
            isinstance(self.driver, AristaSwitch)
            and interface_flap_method
            != taac_types.InterfaceFlapMethod.SSH_PORT_STATE_CHANGE
        ):
            raise NotImplementedError(
                f"Interface flap method {interface_flap_method} not supported for EOS devices. "
                "Only SSH_PORT_STATE_CHANGE is supported for EOS devices"
            )
        if (
            interface_flap_method
            == taac_types.InterfaceFlapMethod.THRIFT_PORT_STATE_CHANGE
        ):
            success: bool = await self.flap_with_thrift(
                interface_names, enable, sequential
            )
            if not success:
                await self.flap_with_ssh(interface_names, enable, sequential)
        elif (
            interface_flap_method
            == taac_types.InterfaceFlapMethod.FBOSS_WEDGE_QSFP_UTIL_TX
        ):
            subcmd: str = "--tx_enable" if enable else "--tx_disable"
            await self.flap_with_shell_cmd(interface_names, subcmd, sequential)
        elif (
            interface_flap_method
            == taac_types.InterfaceFlapMethod.FBOSS_WEDGE_QSFP_UTIL_POWER
        ):
            subcmd: str = "--clear_low_power" if enable else "--set_low_power"
            await self.flap_with_shell_cmd(interface_names, subcmd, sequential)

        elif (
            interface_flap_method
            == taac_types.InterfaceFlapMethod.SSH_PORT_STATE_CHANGE
        ):
            await self.flap_with_ssh(interface_names, enable, sequential)
        else:
            raise NotImplementedError(
                f"Interface flap method {interface_flap_method} not supported"
            )
        action: str = "enabled" if enable else "disabled"
        self.logger.info(
            f"Successfully {action} interfaces {interface_names} via {interface_flap_method.name}"
        )

    async def run_coroutines(
        self,
        coros: t.List[t.Coroutine],
        sequential: bool,
    ) -> None:
        if sequential:
            for coro in coros:
                try:
                    await coro
                except Exception as e:
                    self.logger.debug(f"Error during interface flap: {e}")
                    raise
        else:
            results = await asyncio.gather(*coros, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    self.logger.debug(f"Error during interface flap: {result}")
                    raise result

    async def flap_with_thrift(
        self,
        interface_names: t.List[str],
        enable: bool,
        sequential: bool,
    ) -> bool:
        try:
            interfaces_info = (
                # pyre-ignore
                await self.driver.async_get_all_interfaces_info()
            )
            coros = [
                # pyre-ignore
                self.driver.async_set_port_state(interfaces_info[iface].port_id, enable)
                for iface in interface_names
            ]
            await self.run_coroutines(coros, sequential)
            return True
        except Exception as e:
            self.logger.debug(
                f"THRIFT_PORT_STATE_CHANGE failed: {e}. Falling back to SSH_PORT_STATE_CHANGE."
            )
            return False

    async def flap_with_ssh(
        self,
        interface_names: t.List[str],
        enable: bool,
        sequential: bool,
    ) -> None:
        coros = [
            self.driver.async_enable_ports_via_ssh([iface], enable)
            for iface in interface_names
        ]
        await self.run_coroutines(coros, sequential)

    async def flap_with_shell_cmd(
        self,
        interface_names: t.List[str],
        subcmd: str,
        sequential: bool,
    ) -> None:
        coros = []
        if not sequential:
            ifaces = " ".join(interface_names)
            coros = [
                self.driver.async_run_cmd_on_shell(f"wedge_qsfp_util {subcmd} {ifaces}")
            ]
        else:
            coros = [
                self.driver.async_run_cmd_on_shell(f"wedge_qsfp_util {subcmd} {iface}")
                for iface in interface_names
            ]
        await self.run_coroutines(coros, sequential)
