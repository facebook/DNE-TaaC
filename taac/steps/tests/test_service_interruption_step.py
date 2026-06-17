# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import time
import unittest
from unittest.mock import AsyncMock, MagicMock

from neteng.test_infra.dne.taac.constants import TestDevice, TestTopology
from taac.driver.driver_constants import FbossSystemctlServiceName
from taac.libs.parameter_evaluator import ParameterEvaluator
from taac.steps.step_definitions import ServiceInterruptionStep
from taac.test_as_a_config import types as taac_types


class TestServiceInterruptionStep(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.name = "test_service_interruption"
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "test_device.p001.f01.snc1"

        attributes_mock = MagicMock()
        attributes_mock.operating_system = "FBOSS"
        attributes_mock.role = ""
        attributes_mock.device_name = "test_device"
        attributes_mock.hardware = ""
        attributes_mock.ai_zone = ""
        self.device.attributes = attributes_mock

        self.topology = MagicMock(spec=TestTopology)
        self.test_case_results = []
        self.test_config = MagicMock(spec=taac_types.TestConfig)
        self.test_case_name = "test_case"
        self.test_case_start_time = time.time()
        self.parameter_evaluator = MagicMock(spec=ParameterEvaluator)
        self.step_mock = MagicMock(spec=taac_types.Step)

        self.si_step = ServiceInterruptionStep(
            name=self.name,
            device=self.device,
            topology=self.topology,
            test_case_results=self.test_case_results,
            test_config=self.test_config,
            test_case_name=self.test_case_name,
            test_case_start_time=self.test_case_start_time,
            parameter_evaluator=self.parameter_evaluator,
            step=self.step_mock,
        )

        self.driver_mock = AsyncMock()
        self.si_step.driver = self.driver_mock

    async def test_run_systemctl_restart(self):
        """Test that SYSTEMCTL_RESTART trigger calls async_restart_service."""
        input_data = taac_types.ServiceInterruptionInput(
            name=taac_types.Service.AGENT,
            trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
        )
        await self.si_step.run(input_data, {})
        self.driver_mock.async_restart_service.assert_called_once()

    async def test_run_systemctl_stop(self):
        """Test that SYSTEMCTL_STOP trigger calls async_stop_service."""
        input_data = taac_types.ServiceInterruptionInput(
            name=taac_types.Service.AGENT,
            trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_STOP,
        )
        await self.si_step.run(input_data, {})
        self.driver_mock.async_stop_service.assert_called_once()

    async def test_run_systemctl_start(self):
        """Test that SYSTEMCTL_START trigger calls async_start_service."""
        input_data = taac_types.ServiceInterruptionInput(
            name=taac_types.Service.AGENT,
            trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_START,
        )
        await self.si_step.run(input_data, {})
        self.driver_mock.async_start_service.assert_called_once()

    async def test_run_crash(self):
        """Test that CRASH trigger calls async_crash_service."""
        input_data = taac_types.ServiceInterruptionInput(
            name=taac_types.Service.AGENT,
            trigger=taac_types.ServiceInterruptionTrigger.CRASH,
        )
        await self.si_step.run(input_data, {})
        self.driver_mock.async_crash_service.assert_called_once()

    async def test_run_with_cold_boot_file(self):
        """Test that create_cold_boot_file=True creates the cold boot file before restart."""
        input_data = taac_types.ServiceInterruptionInput(
            name=taac_types.Service.AGENT,
            trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
            create_cold_boot_file=True,
        )
        await self.si_step.run(input_data, {})
        self.driver_mock.async_run_cmd_on_shell.assert_called_once_with(
            "touch /dev/shm/fboss/warm_boot/cold_boot_once_0"
        )
        self.driver_mock.async_restart_service.assert_called_once()

    async def test_run_with_agents(self):
        """Test that agents list is passed through to the driver."""
        input_data = taac_types.ServiceInterruptionInput(
            name=taac_types.Service.ARISTA_CUSTOM_AGENTS,
            trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
            agents=["Rib", "Bgp"],
        )
        await self.si_step.run(input_data, {})
        call_args = self.driver_mock.async_restart_service.call_args
        self.assertEqual(call_args[0][1], ["Rib", "Bgp"])

    def test_service_factory_fboss_service(self):
        """Test service_factory returns correct FbossSystemctlServiceName."""
        service = self.si_step.service_factory(taac_types.Service.AGENT)
        self.assertIsInstance(service, FbossSystemctlServiceName)
