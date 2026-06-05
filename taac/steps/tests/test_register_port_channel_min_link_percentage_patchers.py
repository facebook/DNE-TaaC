# pyre-unsafe
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from neteng.test_infra.dne.taac.constants import TestDevice, TestTopology
from taac.driver.driver_constants import FbossSystemctlServiceName
from taac.libs.parameter_evaluator import ParameterEvaluator
from taac.steps.register_port_channel_min_link_percentage_patchers import (
    AGENT_CONFIG,
    PATCHER_DESCRIPTION,
    PATCHER_NAME,
    RegisterPortChannelMinLinkPercentagePatchers,
)
from taac.test_as_a_config.thrift_types import BaseInput, Step, StepName

BASE_PATH = "neteng.test_infra.dne.taac.steps.register_port_channel_min_link_percentage_patchers"


class RegisterPortChannelMinLinkPercentagePatchersTest(
    unittest.IsolatedAsyncioTestCase
):
    def setUp(self):
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "test_device"
        attributes_mock = MagicMock()
        attributes_mock.operating_system = "FBOSS"
        attributes_mock.role = ""
        attributes_mock.device_name = "test_device"
        attributes_mock.hardware = "MORGAN800CC"
        attributes_mock.ai_zone = ""
        self.device.attributes = attributes_mock

        self.topology = MagicMock(spec=TestTopology)
        self.test_config = MagicMock()
        self.parameter_evaluator = MagicMock(spec=ParameterEvaluator)
        self.step_mock = MagicMock(spec=Step)

        self.step = RegisterPortChannelMinLinkPercentagePatchers(
            name="test_register_patcher",
            device=self.device,
            topology=self.topology,
            test_case_results=[],
            test_config=self.test_config,
            test_case_name="test_case",
            test_case_start_time=time.time(),
            parameter_evaluator=self.parameter_evaluator,
            step=self.step_mock,
        )

        self.driver_mock = AsyncMock()
        self.step.driver = self.driver_mock

    def test_step_name(self):
        self.assertEqual(
            RegisterPortChannelMinLinkPercentagePatchers.STEP_NAME,
            StepName.REGISTER_PORT_CHANNEL_MIN_LINK_PERCENTAGE_PATCHERS,
        )

    def test_build_patcher_args_without_min_link_up_percentage(self):
        result = self.step._build_patcher_args("po1", 0.5)
        self.assertEqual(
            result,
            {"link_percentage": "0.5", "port_channel_name": "po1"},
        )
        self.assertNotIn("min_link_up_percentage", result)

    def test_build_patcher_args_with_min_link_up_percentage(self):
        result = self.step._build_patcher_args("po1", 0.5, 0.25)
        self.assertEqual(
            result,
            {
                "link_percentage": "0.5",
                "port_channel_name": "po1",
                "min_link_up_percentage": "0.25",
            },
        )

    async def test_register_and_apply_registers_patcher(self):
        self.driver_mock.async_register_python_patcher = AsyncMock()
        self.driver_mock.async_create_cold_boot_file = AsyncMock()
        self.driver_mock.async_restart_service = AsyncMock()
        self.driver_mock.async_wait_for_agent_configured = AsyncMock()

        await self.step._register_and_apply_port_channel_min_link_percentage_patcher(
            self.driver_mock,
            True,
            PATCHER_NAME,
            "po1",
            0.5,
            None,
        )

        self.driver_mock.async_register_python_patcher.assert_awaited_once_with(
            patcher_name=PATCHER_NAME,
            patcher_args={"link_percentage": "0.5", "port_channel_name": "po1"},
            config_name=AGENT_CONFIG,
            py_func_name="set_port_channel_min_link_capacity",
            patcher_desc=PATCHER_DESCRIPTION,
        )
        self.driver_mock.async_create_cold_boot_file.assert_awaited_once()
        self.driver_mock.async_restart_service.assert_awaited_once_with(
            FbossSystemctlServiceName.AGENT
        )
        self.driver_mock.async_wait_for_agent_configured.assert_awaited_once()

    async def test_register_and_apply_with_min_link_up_percentage(self):
        self.driver_mock.async_register_python_patcher = AsyncMock()
        self.driver_mock.async_create_cold_boot_file = AsyncMock()
        self.driver_mock.async_restart_service = AsyncMock()
        self.driver_mock.async_wait_for_agent_configured = AsyncMock()

        await self.step._register_and_apply_port_channel_min_link_percentage_patcher(
            self.driver_mock,
            True,
            PATCHER_NAME,
            "po1",
            0.5,
            0.25,
        )

        expected_args = {
            "link_percentage": "0.5",
            "port_channel_name": "po1",
            "min_link_up_percentage": "0.25",
        }
        self.driver_mock.async_register_python_patcher.assert_awaited_once_with(
            patcher_name=PATCHER_NAME,
            patcher_args=expected_args,
            config_name=AGENT_CONFIG,
            py_func_name="set_port_channel_min_link_capacity",
            patcher_desc=PATCHER_DESCRIPTION,
        )

    async def test_register_and_apply_unregisters_when_register_patcher_false(self):
        self.driver_mock.async_unregister_python_patcher = AsyncMock()
        self.driver_mock.async_create_cold_boot_file = AsyncMock()
        self.driver_mock.async_restart_service = AsyncMock()
        self.driver_mock.async_wait_for_agent_configured = AsyncMock()

        await self.step._register_and_apply_port_channel_min_link_percentage_patcher(
            self.driver_mock,
            False,
            PATCHER_NAME,
            "po1",
            0.5,
            None,
        )

        self.driver_mock.async_unregister_python_patcher.assert_awaited_once_with(
            PATCHER_NAME, AGENT_CONFIG
        )
        self.driver_mock.async_create_cold_boot_file.assert_awaited_once()
        self.driver_mock.async_restart_service.assert_awaited_once_with(
            FbossSystemctlServiceName.AGENT
        )
        self.driver_mock.async_wait_for_agent_configured.assert_awaited_once()

    @patch(f"{BASE_PATH}.async_get_device_driver", new_callable=AsyncMock)
    async def test_run_registers_on_local_and_neighbor(self, mock_get_driver):
        neighbor_driver_mock = AsyncMock()
        mock_get_driver.return_value = neighbor_driver_mock

        self.driver_mock.async_get_interface_neighbor = AsyncMock(
            return_value=("neighbor_host", "eth1/1/1")
        )
        neighbor_driver_mock.async_get_all_aggregated_interfaces = AsyncMock(
            return_value={"po2": ["eth1/1/1", "eth1/2/1"]}
        )

        self.step._register_and_apply_port_channel_min_link_percentage_patcher = (
            AsyncMock()
        )

        params = {
            "port_channel_name": "po1",
            "min_link_percentage": 0.5,
        }

        await self.step.run(BaseInput(), params)

        calls = self.step._register_and_apply_port_channel_min_link_percentage_patcher.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].args[0], self.driver_mock)
        self.assertEqual(calls[0].args[1], True)
        self.assertEqual(calls[0].args[2], PATCHER_NAME)
        self.assertEqual(calls[0].args[3], "po1")
        self.assertEqual(calls[0].args[4], 0.5)
        self.assertIsNone(calls[0].args[5])

        mock_get_driver.assert_awaited_once_with("neighbor_host")

    @patch(f"{BASE_PATH}.async_get_device_driver", new_callable=AsyncMock)
    async def test_run_skips_neighbor_for_eb_hostname(self, mock_get_driver):
        self.driver_mock.async_get_interface_neighbor = AsyncMock(
            return_value=("eb-neighbor-host", "eth1/1/1")
        )

        self.step._register_and_apply_port_channel_min_link_percentage_patcher = (
            AsyncMock()
        )

        params = {
            "port_channel_name": "po1",
            "min_link_percentage": 0.5,
        }

        await self.step.run(BaseInput(), params)

        self.step._register_and_apply_port_channel_min_link_percentage_patcher.assert_awaited_once()
        mock_get_driver.assert_not_awaited()

    @patch(f"{BASE_PATH}.async_get_device_driver", new_callable=AsyncMock)
    async def test_run_with_custom_patcher_name(self, mock_get_driver):
        self.driver_mock.async_get_interface_neighbor = AsyncMock(
            return_value=("eb-host", "eth1/1/1")
        )

        self.step._register_and_apply_port_channel_min_link_percentage_patcher = (
            AsyncMock()
        )

        params = {
            "port_channel_name": "po1",
            "min_link_percentage": 0.5,
            "patcher_name": "custom_patcher",
        }

        await self.step.run(BaseInput(), params)

        call_args = self.step._register_and_apply_port_channel_min_link_percentage_patcher.call_args
        self.assertEqual(call_args.args[2], "custom_patcher")

    @patch(f"{BASE_PATH}.async_get_device_driver", new_callable=AsyncMock)
    async def test_run_with_register_patchers_false(self, mock_get_driver):
        self.driver_mock.async_get_interface_neighbor = AsyncMock(
            return_value=("eb-host", "eth1/1/1")
        )

        self.step._register_and_apply_port_channel_min_link_percentage_patcher = (
            AsyncMock()
        )

        params = {
            "port_channel_name": "po1",
            "min_link_percentage": 0.5,
            "register_patchers": False,
        }

        await self.step.run(BaseInput(), params)

        call_args = self.step._register_and_apply_port_channel_min_link_percentage_patcher.call_args
        self.assertFalse(call_args.args[1])

    @patch(f"{BASE_PATH}.async_get_device_driver", new_callable=AsyncMock)
    async def test_run_with_min_link_up_percentage(self, mock_get_driver):
        self.driver_mock.async_get_interface_neighbor = AsyncMock(
            return_value=("eb-host", "eth1/1/1")
        )

        self.step._register_and_apply_port_channel_min_link_percentage_patcher = (
            AsyncMock()
        )

        params = {
            "port_channel_name": "po1",
            "min_link_percentage": 0.5,
            "min_link_up_percentage": 0.25,
        }

        await self.step.run(BaseInput(), params)

        call_args = self.step._register_and_apply_port_channel_min_link_percentage_patcher.call_args
        self.assertEqual(call_args.args[5], 0.25)

    @patch(f"{BASE_PATH}.async_get_device_driver", new_callable=AsyncMock)
    async def test_run_default_min_link_up_percentage_is_none(self, mock_get_driver):
        self.driver_mock.async_get_interface_neighbor = AsyncMock(
            return_value=("eb-host", "eth1/1/1")
        )

        self.step._register_and_apply_port_channel_min_link_percentage_patcher = (
            AsyncMock()
        )

        params = {
            "port_channel_name": "po1",
            "min_link_percentage": 0.5,
        }

        await self.step.run(BaseInput(), params)

        call_args = self.step._register_and_apply_port_channel_min_link_percentage_patcher.call_args
        self.assertIsNone(call_args.args[5])
