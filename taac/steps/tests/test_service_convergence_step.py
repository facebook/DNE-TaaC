# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe
import time
import unittest
from unittest.mock import AsyncMock, MagicMock

from neteng.test_infra.dne.taac.constants import TestDevice, TestTopology
from taac.libs.parameter_evaluator import ParameterEvaluator
from taac.steps.service_convergence_step import (
    ServiceConvergenceStep,
)
from taac.test_as_a_config import types as taac_types


class TestServiceConvergenceStep(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.name = "test_service_convergence"
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "rsw001.p001.f01.snc1"

        attributes_mock = MagicMock()
        attributes_mock.operating_system = "FBOSS"
        attributes_mock.role = ""
        attributes_mock.device_name = "rsw001"
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

        self.sc_step = ServiceConvergenceStep(
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
        self.sc_step.driver = self.driver_mock

    async def test_run_agent_convergence(self):
        """Test convergence waiting for AGENT service."""
        input_data = taac_types.ServiceConvergenceInput(
            services=[taac_types.Service.AGENT],
            timeout=300,
        )
        await self.sc_step.run(input_data, {})
        self.driver_mock.async_wait_for_agent_configured.assert_called_once_with(300)

    async def test_run_bgp_convergence(self):
        """Test convergence waiting for BGP service."""
        input_data = taac_types.ServiceConvergenceInput(
            services=[taac_types.Service.BGP],
            timeout=300,
        )
        await self.sc_step.run(input_data, {})
        self.driver_mock.async_wait_for_bgp_convergence.assert_called_once_with(300)

    async def test_run_bgp_convergence_with_ixia_on_rsw(self):
        """Test that IXIA BGP peers are restarted for RSW devices when ixia is present."""
        ixia_mock = MagicMock()
        self.sc_step.ixia = ixia_mock
        input_data = taac_types.ServiceConvergenceInput(
            services=[taac_types.Service.BGP],
            timeout=300,
        )
        await self.sc_step.run(input_data, {})
        ixia_mock.restart_bgp_peers.assert_called_once_with(["RSW001.P001.F01.SNC1"])
        self.driver_mock.async_wait_for_bgp_convergence.assert_called_once()

    async def test_run_qsfp_service_convergence(self):
        """Test convergence waiting for QSFP_SERVICE."""
        input_data = taac_types.ServiceConvergenceInput(
            services=[taac_types.Service.QSFP_SERVICE],
            timeout=120,
        )
        await self.sc_step.run(input_data, {})
        self.driver_mock.async_wait_for_qsfp_service_state_active.assert_called_once_with(
            120
        )

    async def test_run_fsdb_convergence(self):
        """Test convergence waiting for FSDB service."""
        input_data = taac_types.ServiceConvergenceInput(
            services=[taac_types.Service.FSDB],
            timeout=120,
        )
        await self.sc_step.run(input_data, {})
        self.driver_mock.async_wait_for_fsdb_state_active.assert_called_once_with(120)

    async def test_run_multiple_services(self):
        """Test convergence with multiple services."""
        input_data = taac_types.ServiceConvergenceInput(
            services=[
                taac_types.Service.AGENT,
                taac_types.Service.BGP,
            ],
            timeout=300,
        )
        await self.sc_step.run(input_data, {})
        self.driver_mock.async_wait_for_agent_configured.assert_called_once()
        self.driver_mock.async_wait_for_bgp_convergence.assert_called_once()

    async def test_run_with_per_service_timeout(self):
        """Test that per-service timeout overrides the default timeout."""
        input_data = taac_types.ServiceConvergenceInput(
            services=[taac_types.Service.AGENT],
            timeout=300,
            service_convergence_timeout={taac_types.Service.AGENT: 600},
        )
        await self.sc_step.run(input_data, {})
        self.driver_mock.async_wait_for_agent_configured.assert_called_once_with(600)

    async def test_run_fsdb_with_per_service_timeout(self):
        """Test that per-service timeout overrides the default timeout for FSDB."""
        input_data = taac_types.ServiceConvergenceInput(
            services=[taac_types.Service.FSDB],
            timeout=120,
            service_convergence_timeout={taac_types.Service.FSDB: 360},
        )
        await self.sc_step.run(input_data, {})
        self.driver_mock.async_wait_for_fsdb_state_active.assert_called_once_with(360)
