# pyre-unsafe
import typing as t

from taac.driver.driver_constants import FbossSystemctlServiceName
from taac.driver.fboss_switch import FbossSwitch
from taac.steps.step import Step
from taac.utils.driver_factory import async_get_device_driver
from taac.utils.oss_taac_lib_utils import none_throws
from taac.test_as_a_config import types as taac_types

PATCHER_NAME = "configure_port_channel_min_link_percentage"
PATCHER_DESCRIPTION = "Configuration of port channel minimum link capacity percentage for DNE Solution Test"
AGENT_CONFIG = "agent"


class RegisterPortChannelMinLinkPercentagePatchers(Step[taac_types.BaseInput]):
    """
    Step to register and apply patchers that configure the minimum link capacity percentage
    for port channels on both the local device and its neighbor device (if applicable).
    """

    STEP_NAME = taac_types.StepName.REGISTER_PORT_CHANNEL_MIN_LINK_PERCENTAGE_PATCHERS

    async def run(
        self,
        input: taac_types.BaseInput,
        params: t.Dict[str, t.Any],
    ) -> None:
        """
        Main entry point to run the step.

        Args:
            input (taac_types.BaseInput): The input data for the step.
            params (Dict[str, Any]): Parameters including:
                - port_channel_name (str): The name of the port channel to configure.
                - min_link_percentage (float): The minimum link capacity percentage to set.
                - min_link_up_percentage (optional) (float): The minimum link up percentage to set.

        This method registers and applies the patcher on the local device and,
        if applicable, on the neighbor device connected to the port channel.
        """
        port_channel_name = params["port_channel_name"]
        min_link_percentage = params.get("min_link_percentage")
        min_link_up_percentage = None
        if "min_link_up_percentage" in params:
            min_link_up_percentage = params["min_link_up_percentage"]
        patcher_name = params.get("patcher_name", PATCHER_NAME)
        register_patchers = params.get("register_patchers", True)
        neighbor_hostname, neighbor_interface = none_throws(
            await self.driver.async_get_interface_neighbor(port_channel_name)
        )
        await self._register_and_apply_port_channel_min_link_percentage_patcher(
            # pyre-ignore
            self.driver,
            register_patchers,
            patcher_name,
            port_channel_name,
            min_link_percentage,
            min_link_up_percentage,
        )
        # Register patcher for the neighbor device, if applicable
        if "eb" not in neighbor_hostname:
            neighbor_driver = await async_get_device_driver(neighbor_hostname)
            neighbor_aggregated_interfaces = (
                # pyre-fixme[16]: `AbstractSwitch` has no attribute
                #  `async_get_all_aggregated_interfaces`.
                await neighbor_driver.async_get_all_aggregated_interfaces()
            )
            neighbor_port_channel_name = none_throws(
                next(
                    (
                        agg_name
                        for agg_name, member_ports in neighbor_aggregated_interfaces.items()
                        if neighbor_interface in member_ports
                    ),
                    None,
                )
            )
            await self._register_and_apply_port_channel_min_link_percentage_patcher(
                # pyre-fixme[6]: For 1st argument expected `FbossSwitch` but got
                #  `AbstractSwitch`.
                neighbor_driver,
                register_patchers,
                patcher_name,
                neighbor_port_channel_name,
                min_link_percentage,
                min_link_up_percentage,
            )

    def _build_patcher_args(
        self,
        port_channel_name: str,
        min_link_percentage: float,
        min_link_up_percentage: t.Optional[float] = None,
    ):
        """
        Build the arguments dictionary for the patcher function.

        Args:
            port_channel_name (str): The name of the port channel.
            min_link_percentage (float): The minimum link capacity percentage.
            min_link_up_percentage (optional) (float): The minimum link up percentage.

        Returns:
            Dict[str, str]: Arguments for the patcher function.
        """
        patcher_args = {
            "link_percentage": str(min_link_percentage),
            "port_channel_name": port_channel_name,
        }
        if min_link_up_percentage is not None:
            patcher_args["min_link_up_percentage"] = str(min_link_up_percentage)

        return patcher_args

    async def _register_and_apply_port_channel_min_link_percentage_patcher(
        self,
        driver: "FbossSwitch",
        register_patcher: bool,
        patcher_name: str,
        port_channel_name: str,
        min_link_percentage: t.Optional[float],
        min_link_up_percentage: t.Optional[float] = None,
    ):
        """
        Register the patcher on the given driver and apply it by restarting the agent.

        Args:
            driver (FbossSwitch): The device driver to register the patcher on.
            port_channel_name (str): The name of the port channel to configure.
            min_link_percentage (float): The minimum link capacity percentage to set.

        This method registers the patcher, creates a cold boot file to apply it,
        restarts the agent service, and waits for the agent to reach the configured state.
        """
        if register_patcher:
            # pyre-fixme[16]: `FbossSwitch` has no attribute
            #  `async_register_python_patcher`.
            await driver.async_register_python_patcher(
                patcher_name=patcher_name,
                patcher_args=self._build_patcher_args(
                    port_channel_name,
                    none_throws(min_link_percentage),
                    min_link_up_percentage,
                ),
                config_name=AGENT_CONFIG,
                py_func_name="set_port_channel_min_link_capacity",
                patcher_desc=PATCHER_DESCRIPTION,
            )
        else:
            # pyre-fixme[16]: `FbossSwitch` has no attribute
            #  `async_unregister_python_patcher`.
            await driver.async_unregister_python_patcher(patcher_name, AGENT_CONFIG)
        # cold boot to apply the patcher and wait for agent to reach configured state
        await driver.async_create_cold_boot_file()
        await driver.async_restart_service(FbossSystemctlServiceName.AGENT)
        await driver.async_wait_for_agent_configured()
