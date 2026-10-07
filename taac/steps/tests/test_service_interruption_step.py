# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import contextlib
import time
import typing as t
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from taac.constants import (  # oss-rewrite (force ShipIt re-export to taac.* root)
    TestDevice,
    TestTopology,
)
from taac.driver.driver_constants import FbossSystemctlServiceName
from taac.driver.fboss_switch import FbossSwitch
from taac.libs.parameter_evaluator import ParameterEvaluator
from taac.steps.step_definitions import (
    create_service_interruption_step,
    ServiceInterruptionStep,
)
from taac.utils import oss_taac_lib_utils
from taac.test_as_a_config import types as taac_types

_INTERNAL_COLD_BOOT_CMD = "touch /dev/shm/fboss/warm_boot/cold_boot_once_0"


@contextlib.contextmanager
def _taac_env(taac_oss: bool, meta_internal: bool) -> t.Iterator[None]:
    """Drive the real gate through the module-level flags it reads."""
    with (
        patch.object(oss_taac_lib_utils, "TAAC_OSS", taac_oss),
        patch.object(oss_taac_lib_utils, "TAAC_OSS_META_INTERNAL", meta_internal),
    ):
        yield


class _ServiceInterruptionStepFixture(unittest.IsolatedAsyncioTestCase):
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

        self.driver_mock = AsyncMock(spec=FbossSwitch)
        self.si_step.driver = self.driver_mock


class TestServiceInterruptionStep(_ServiceInterruptionStepFixture):
    async def test_run_systemctl_restart(self):
        """Test that SYSTEMCTL_RESTART trigger calls async_restart_service."""
        input_data = taac_types.ServiceInterruptionInput(
            name=taac_types.Service.AGENT,
            trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
        )
        await self.si_step.run(input_data, {})
        self.driver_mock.async_restart_service.assert_called_once_with(
            FbossSystemctlServiceName.AGENT, None
        )

    async def test_run_systemctl_stop(self):
        """Test that SYSTEMCTL_STOP trigger calls async_stop_service."""
        input_data = taac_types.ServiceInterruptionInput(
            name=taac_types.Service.AGENT,
            trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_STOP,
        )
        await self.si_step.run(input_data, {})
        self.driver_mock.async_stop_service.assert_called_once()

    async def test_intentional_stop_requests_driver_contract(self):
        input_data = taac_types.ServiceInterruptionInput(
            name=taac_types.Service.FSDB,
            trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_STOP,
        )
        await self.si_step.run(input_data, {"intentional_stop": True})

        self.driver_mock.async_stop_service.assert_awaited_once_with(
            FbossSystemctlServiceName.FSDB,
            accept_failed_if_process_absent=True,
        )

    async def test_intentional_stop_rejects_non_fboss_driver(self):
        input_data = taac_types.ServiceInterruptionInput(
            name=taac_types.Service.FSDB,
            trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_STOP,
        )
        self.si_step.driver = AsyncMock()

        with self.assertRaisesRegex(ValueError, "only by the FBOSS driver"):
            await self.si_step.run(input_data, {"intentional_stop": True})

    async def test_run_systemctl_start(self):
        """Test that SYSTEMCTL_START trigger calls async_start_service."""
        input_data = taac_types.ServiceInterruptionInput(
            name=taac_types.Service.AGENT,
            trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_START,
        )
        await self.si_step.run(input_data, {})
        self.driver_mock.async_start_service.assert_called_once()

    async def test_systemctl_start_retains_strict_active_requirement(self):
        input_data = taac_types.ServiceInterruptionInput(
            name=taac_types.Service.FSDB,
            trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_START,
        )
        self.driver_mock.async_start_service.side_effect = RuntimeError(
            "service did not reach ACTIVE"
        )

        with self.assertRaisesRegex(RuntimeError, "did not reach ACTIVE"):
            await self.si_step.run(input_data, {"intentional_stop": True})

    def test_factory_rejects_intentional_stop_for_start(self):
        with self.assertRaisesRegex(ValueError, "only for SYSTEMCTL_STOP"):
            create_service_interruption_step(
                service=taac_types.Service.FSDB,
                trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_START,
                intentional_stop=True,
            )

    async def test_run_crash(self):
        """Test that CRASH trigger calls async_crash_service."""
        input_data = taac_types.ServiceInterruptionInput(
            name=taac_types.Service.AGENT,
            trigger=taac_types.ServiceInterruptionTrigger.CRASH,
        )
        await self.si_step.run(input_data, {})
        self.driver_mock.async_crash_service.assert_called_once()

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


class _ColdBootStepTestBase(_ServiceInterruptionStepFixture):
    TAAC_OSS: bool = False
    TAAC_OSS_META_INTERNAL: bool = False

    def setUp(self):
        super().setUp()
        env = _taac_env(self.TAAC_OSS, self.TAAC_OSS_META_INTERNAL)
        env.__enter__()
        self.addCleanup(env.__exit__, None, None, None)

    async def _run(
        self,
        service: taac_types.Service,
        create_cold_boot_file: bool = False,
        trigger: taac_types.ServiceInterruptionTrigger = (
            taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART
        ),
    ) -> None:
        await self.si_step.run(
            taac_types.ServiceInterruptionInput(
                name=service,
                trigger=trigger,
                create_cold_boot_file=create_cold_boot_file,
            ),
            {},
        )

    def _shell_commands(self) -> t.List[str]:
        return [
            call.args[0]
            for call in self.driver_mock.async_run_cmd_on_shell.await_args_list
        ]


class PureOssColdBootStepTest(_ColdBootStepTestBase):
    """``TAAC_OSS=1`` without ``TAAC_OSS_META_INTERNAL``: per-agent flags."""

    TAAC_OSS = True

    async def test_run_with_cold_boot_file(self):
        """create_cold_boot_file=True creates the cold boot file before restart."""
        await self._run(taac_types.Service.AGENT, create_cold_boot_file=True)
        self.driver_mock.async_create_cold_boot_file.assert_awaited_once_with(
            FbossSystemctlServiceName.AGENT
        )
        self.driver_mock.async_restart_service.assert_called_once_with(
            FbossSystemctlServiceName.AGENT, None
        )

    async def test_flag_is_cleared_before_it_is_created(self):
        order = MagicMock()
        self.driver_mock.async_remove_cold_boot_file.side_effect = lambda: order(
            "remove"
        )
        self.driver_mock.async_create_cold_boot_file.side_effect = (
            lambda service: order("create")
        )
        self.driver_mock.async_restart_service.side_effect = (
            lambda service, agents: order("restart")
        )
        await self._run(taac_types.Service.AGENT, create_cold_boot_file=True)
        self.assertEqual(
            [call.args[0] for call in order.call_args_list],
            ["remove", "create", "restart"],
        )

    async def test_run_leaves_the_flag_alone_for_non_agent_services(self):
        """qsfp_service owns a separate flag; only the agent reads this one."""
        await self._run(taac_types.Service.QSFP_SERVICE, create_cold_boot_file=True)
        self.driver_mock.async_remove_cold_boot_file.assert_not_awaited()
        self.driver_mock.async_create_cold_boot_file.assert_not_awaited()

    async def test_run_clears_a_stale_cold_boot_flag(self):
        """A restart that didn't ask to be cold must not inherit someone else's flag."""
        await self._run(taac_types.Service.AGENT)
        self.driver_mock.async_remove_cold_boot_file.assert_awaited_once()
        self.driver_mock.async_create_cold_boot_file.assert_not_awaited()

    async def test_split_agent_gets_its_own_flag(self):
        await self._run(taac_types.Service.FBOSS_HW_AGENT_0, create_cold_boot_file=True)
        self.driver_mock.async_create_cold_boot_file.assert_awaited_once_with(
            FbossSystemctlServiceName.FBOSS_HW_AGENT_0
        )

    async def test_never_touches_the_internal_flag_directly(self):
        await self._run(taac_types.Service.AGENT, create_cold_boot_file=True)
        self.assertNotIn(_INTERNAL_COLD_BOOT_CMD, self._shell_commands())


class InternalColdBootStepTest(_ColdBootStepTestBase):
    """Internal runs: the original ``cold_boot_once_0`` touch, nothing else."""

    async def test_cold_boot_touches_the_internal_flag_before_restart(self):
        order = MagicMock()
        self.driver_mock.async_run_cmd_on_shell.side_effect = lambda cmd: order(cmd)
        self.driver_mock.async_restart_service.side_effect = (
            lambda service, agents: order("restart")
        )
        await self._run(taac_types.Service.AGENT, create_cold_boot_file=True)
        self.assertEqual(
            [call.args[0] for call in order.call_args_list],
            [_INTERNAL_COLD_BOOT_CMD, "restart"],
        )
        self.driver_mock.async_restart_service.assert_awaited_once_with(
            FbossSystemctlServiceName.AGENT, None
        )

    async def test_cold_boot_does_not_use_the_per_agent_driver_flags(self):
        await self._run(taac_types.Service.AGENT, create_cold_boot_file=True)
        self.driver_mock.async_create_cold_boot_file.assert_not_awaited()
        self.driver_mock.async_remove_cold_boot_file.assert_not_awaited()

    async def test_warm_restart_touches_no_flag(self):
        await self._run(taac_types.Service.AGENT)
        self.assertEqual(self._shell_commands(), [])
        self.driver_mock.async_remove_cold_boot_file.assert_not_awaited()
        self.driver_mock.async_create_cold_boot_file.assert_not_awaited()
        self.driver_mock.async_restart_service.assert_awaited_once_with(
            FbossSystemctlServiceName.AGENT, None
        )

    async def test_cold_boot_flag_is_honoured_for_every_trigger(self):
        for trigger in (
            taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
            taac_types.ServiceInterruptionTrigger.SYSTEMCTL_STOP,
            taac_types.ServiceInterruptionTrigger.CRASH,
        ):
            with self.subTest(trigger=trigger):
                self.driver_mock.async_run_cmd_on_shell.reset_mock()
                await self._run(
                    taac_types.Service.AGENT,
                    create_cold_boot_file=True,
                    trigger=trigger,
                )
                self.assertEqual(self._shell_commands(), [_INTERNAL_COLD_BOOT_CMD])

    async def test_cold_boot_flag_is_written_for_non_agent_services_too(self):
        """Unchanged from before split-agent support: no per-service filter."""
        await self._run(taac_types.Service.QSFP_SERVICE, create_cold_boot_file=True)
        self.assertEqual(self._shell_commands(), [_INTERNAL_COLD_BOOT_CMD])

    async def test_non_fboss_device_touches_no_flag(self):
        self.device.attributes.operating_system = "EOS"
        si_step = ServiceInterruptionStep(
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
        si_step.driver = self.driver_mock
        self.assertFalse(si_step.is_fboss)
        await si_step.run(
            taac_types.ServiceInterruptionInput(
                name=taac_types.Service.ARISTA_CUSTOM_AGENTS,
                trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                create_cold_boot_file=True,
            ),
            {},
        )
        self.assertEqual(self._shell_commands(), [])


class ContainerizedMetaInternalColdBootStepTest(InternalColdBootStepTest):
    """``TAAC_OSS=1`` + ``TAAC_OSS_META_INTERNAL=1`` behaves as internal."""

    TAAC_OSS = True
    TAAC_OSS_META_INTERNAL = True


class MetaInternalFlagOnlyColdBootStepTest(InternalColdBootStepTest):
    TAAC_OSS_META_INTERNAL = True
