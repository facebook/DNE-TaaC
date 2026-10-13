# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import time
import typing as t
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from neteng.test_infra.dne.taac.constants import TestDevice, TestTopology
from taac.libs.parameter_evaluator import ParameterEvaluator
from taac.steps.step_definitions import RegisterPatcherStep
from taac.test_as_a_config import types as taac_types

_STEPS = "neteng.test_infra.dne.taac.steps.step_definitions"


class RegisterPatcherStepTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        device = MagicMock(spec=TestDevice)
        device.name = "dut1"
        self.step = RegisterPatcherStep(
            name="register_patcher",
            device=device,
            topology=MagicMock(spec=TestTopology),
            test_case_results=[],
            test_config=MagicMock(spec=taac_types.TestConfig),
            test_case_name="test_case",
            test_case_start_time=time.time(),
            parameter_evaluator=MagicMock(spec=ParameterEvaluator),
            step=MagicMock(spec=taac_types.Step),
        )
        self.driver = AsyncMock()
        self.step.driver = t.cast(t.Any, self.driver)
        self.register = taac_types.RegisterPatcherInput(
            register_patcher=True,
            config_name="agent",
            name="permanently_disable_interface_patcher",
            py_func_name="change_port_admin_state",
            kwargs={"eth1/1/1": "disable"},
        )
        self.unregister = taac_types.RegisterPatcherInput(
            register_patcher=False,
            config_name="agent",
            name="permanently_disable_interface_patcher",
        )

    async def test_oss_installs_without_restarting_after_each_change(self) -> None:
        with patch(f"{_STEPS}.oss_config_patcher_enabled", return_value=True):
            await self.step.run(self.register, {})
            await self.step.run(self.unregister, {})

        self.driver.async_register_python_patcher.assert_awaited_once()
        self.driver.async_unregister_python_patcher.assert_awaited_once()
        self.assertEqual(
            [((), {"restart_services": False})] * 2,
            [
                (c.args, c.kwargs)
                for c in self.driver.async_apply_patchers.await_args_list
            ],
        )

    async def test_internal_leaves_rendering_to_coop(self) -> None:
        with patch(f"{_STEPS}.oss_config_patcher_enabled", return_value=False):
            await self.step.run(self.register, {})

        self.driver.async_apply_patchers.assert_not_awaited()

    async def test_oss_cleanup_unregisters_through_the_driver(self) -> None:
        unregister_helper = AsyncMock()
        with (
            patch(f"{_STEPS}.oss_config_patcher_enabled", return_value=True),
            patch(f"{_STEPS}.async_unregister_patcher", unregister_helper),
        ):
            await self.step.run(self.register, {})
            self.driver.async_apply_patchers.reset_mock()
            await self.step.cleanUp(self.register, {})

        self.driver.async_unregister_python_patcher.assert_awaited_once_with(
            config_name="agent", patcher_name="permanently_disable_interface_patcher"
        )
        self.driver.async_apply_patchers.assert_awaited_once_with(
            restart_services=False
        )
        unregister_helper.assert_not_awaited()
