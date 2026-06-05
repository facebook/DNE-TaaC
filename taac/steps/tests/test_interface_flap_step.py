# pyre-unsafe
import json
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from neteng.test_infra.dne.taac.constants import TestDevice, TestTopology
from taac.libs.parameter_evaluator import ParameterEvaluator
from taac.steps.interface_flap_step import InterfaceFlapStep
from taac.test_as_a_config.thrift_types import (
    BaseInput,
    InterfaceFlapMethod,
    Step,
    StepName,
    TestConfig,
)

BASE_PATH = "neteng.test_infra.dne.taac.steps.interface_flap_step"


def _make_test_interfaces(names: list[str]) -> str:
    return json.dumps(
        [
            {
                "interface_name": name,
                "display_name": f"device.test:{name}",
                "switch_name": "test_device",
                "neighbor_switch_name": "test_device",
                "neighbor_interface_name": f"neighbor_{name}",
                "neighbor_display_name": f"device.test:neighbor_{name}",
                "switch_attributes": {
                    "tags": [],
                    "device_name": "test_device",
                    "role": "TEST",
                    "operating_system": "FBOSS",
                    "hardware": "MORGAN800CC",
                    "ai_zone": "",
                },
            }
            for name in names
        ]
    )


class InterfaceFlapStepTest(unittest.IsolatedAsyncioTestCase):
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
        self.test_config = MagicMock(spec=TestConfig)
        self.parameter_evaluator = MagicMock(spec=ParameterEvaluator)
        self.step_mock = MagicMock(spec=Step)

        self.flap_step = InterfaceFlapStep(
            name="test_interface_flap",
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
        self.flap_step.driver = self.driver_mock

    def _make_params(
        self,
        interfaces: list[str],
        enable: bool,
        method: int,
        delay: int = 0,
        sequential: bool = False,
    ) -> dict:
        return {
            "interfaces": _make_test_interfaces(interfaces),
            "enable": enable,
            "interface_flap_method": method,
            "delay": delay,
            "sequential": sequential,
        }

    # ──────────────────────────────────────────────
    # STEP_NAME
    # ──────────────────────────────────────────────

    def test_step_name(self):
        self.assertEqual(InterfaceFlapStep.STEP_NAME, StepName.INTERFACE_FLAP_STEP)

    # ──────────────────────────────────────────────
    # run() — top-level orchestration
    # ──────────────────────────────────────────────

    @patch(f"{BASE_PATH}.async_get_device_driver", new_callable=AsyncMock)
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_run_with_delay(self, mock_sleep, mock_get_driver):
        mock_get_driver.return_value = self.driver_mock
        self.driver_mock.async_set_port_state = AsyncMock()
        self.driver_mock.async_get_all_interfaces_info = AsyncMock(
            return_value={
                "eth1/1/1": MagicMock(port_id=1),
                "eth1/2/1": MagicMock(port_id=2),
            }
        )
        params = self._make_params(
            ["eth1/1/1", "eth1/2/1"],
            enable=False,
            method=InterfaceFlapMethod.THRIFT_PORT_STATE_CHANGE,
            delay=10,
        )
        await self.flap_step.run(BaseInput(), params)
        mock_sleep.assert_awaited_once_with(10)

    @patch(f"{BASE_PATH}.async_get_device_driver", new_callable=AsyncMock)
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_run_zero_delay_skips_sleep(self, mock_sleep, mock_get_driver):
        mock_get_driver.return_value = self.driver_mock
        self.driver_mock.async_set_port_state = AsyncMock()
        self.driver_mock.async_get_all_interfaces_info = AsyncMock(
            return_value={"eth1/1/1": MagicMock(port_id=1)}
        )
        params = self._make_params(
            ["eth1/1/1"],
            enable=True,
            method=InterfaceFlapMethod.THRIFT_PORT_STATE_CHANGE,
            delay=0,
        )
        await self.flap_step.run(BaseInput(), params)
        mock_sleep.assert_not_awaited()

    @patch(f"{BASE_PATH}.async_get_device_driver", new_callable=AsyncMock)
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_run_uses_custom_device_name(self, mock_sleep, mock_get_driver):
        mock_get_driver.return_value = self.driver_mock
        self.driver_mock.async_set_port_state = AsyncMock()
        self.driver_mock.async_get_all_interfaces_info = AsyncMock(
            return_value={"eth1/1/1": MagicMock(port_id=1)}
        )
        params = self._make_params(
            ["eth1/1/1"],
            enable=True,
            method=InterfaceFlapMethod.THRIFT_PORT_STATE_CHANGE,
            delay=0,
        )
        params["device_name"] = "custom_device"
        await self.flap_step.run(BaseInput(), params)
        mock_get_driver.assert_awaited_once_with("custom_device")

    # ──────────────────────────────────────────────
    # async_flap_interfaces — method dispatch
    # ──────────────────────────────────────────────

    async def test_thrift_method_calls_flap_with_thrift(self):
        self.flap_step.flap_with_thrift = AsyncMock(return_value=True)
        await self.flap_step.async_flap_interfaces(
            "test_device",
            ["eth1/1/1"],
            InterfaceFlapMethod.THRIFT_PORT_STATE_CHANGE,
            enable=True,
            sequential=False,
        )
        self.flap_step.flap_with_thrift.assert_awaited_once_with(
            ["eth1/1/1"], True, False
        )

    async def test_thrift_fallback_to_ssh(self):
        self.flap_step.flap_with_thrift = AsyncMock(return_value=False)
        self.flap_step.flap_with_ssh = AsyncMock()
        await self.flap_step.async_flap_interfaces(
            "test_device",
            ["eth1/1/1"],
            InterfaceFlapMethod.THRIFT_PORT_STATE_CHANGE,
            enable=False,
            sequential=False,
        )
        self.flap_step.flap_with_thrift.assert_awaited_once()
        self.flap_step.flap_with_ssh.assert_awaited_once_with(
            ["eth1/1/1"], False, False
        )

    async def test_qsfp_util_tx_disable(self):
        self.flap_step.flap_with_shell_cmd = AsyncMock()
        await self.flap_step.async_flap_interfaces(
            "test_device",
            ["eth1/1/1"],
            InterfaceFlapMethod.FBOSS_WEDGE_QSFP_UTIL_TX,
            enable=False,
            sequential=False,
        )
        self.flap_step.flap_with_shell_cmd.assert_awaited_once_with(
            ["eth1/1/1"], "--tx_disable", False
        )

    async def test_qsfp_util_tx_enable(self):
        self.flap_step.flap_with_shell_cmd = AsyncMock()
        await self.flap_step.async_flap_interfaces(
            "test_device",
            ["eth1/1/1"],
            InterfaceFlapMethod.FBOSS_WEDGE_QSFP_UTIL_TX,
            enable=True,
            sequential=False,
        )
        self.flap_step.flap_with_shell_cmd.assert_awaited_once_with(
            ["eth1/1/1"], "--tx_enable", False
        )

    async def test_qsfp_util_power_set_low_power(self):
        self.flap_step.flap_with_shell_cmd = AsyncMock()
        await self.flap_step.async_flap_interfaces(
            "test_device",
            ["eth1/1/1"],
            InterfaceFlapMethod.FBOSS_WEDGE_QSFP_UTIL_POWER,
            enable=False,
            sequential=False,
        )
        self.flap_step.flap_with_shell_cmd.assert_awaited_once_with(
            ["eth1/1/1"], "--set_low_power", False
        )

    async def test_qsfp_util_power_clear_low_power(self):
        self.flap_step.flap_with_shell_cmd = AsyncMock()
        await self.flap_step.async_flap_interfaces(
            "test_device",
            ["eth1/1/1"],
            InterfaceFlapMethod.FBOSS_WEDGE_QSFP_UTIL_POWER,
            enable=True,
            sequential=False,
        )
        self.flap_step.flap_with_shell_cmd.assert_awaited_once_with(
            ["eth1/1/1"], "--clear_low_power", False
        )

    async def test_ssh_method_calls_flap_with_ssh(self):
        self.flap_step.flap_with_ssh = AsyncMock()
        await self.flap_step.async_flap_interfaces(
            "test_device",
            ["eth1/1/1", "eth1/2/1"],
            InterfaceFlapMethod.SSH_PORT_STATE_CHANGE,
            enable=True,
            sequential=True,
        )
        self.flap_step.flap_with_ssh.assert_awaited_once_with(
            ["eth1/1/1", "eth1/2/1"], True, True
        )

    async def test_arista_rejects_non_ssh_method(self):
        from taac.internal.driver.arista_switch import (
            AristaSwitch,
        )

        self.flap_step.driver = MagicMock(spec=AristaSwitch)
        with self.assertRaises(NotImplementedError):
            await self.flap_step.async_flap_interfaces(
                "test_device",
                ["eth1/1/1"],
                InterfaceFlapMethod.THRIFT_PORT_STATE_CHANGE,
                enable=True,
                sequential=False,
            )

    async def test_arista_allows_ssh_method(self):
        from taac.internal.driver.arista_switch import (
            AristaSwitch,
        )

        self.flap_step.driver = MagicMock(spec=AristaSwitch)
        self.flap_step.driver.async_enable_ports_via_ssh = AsyncMock()
        await self.flap_step.async_flap_interfaces(
            "test_device",
            ["eth1/1/1"],
            InterfaceFlapMethod.SSH_PORT_STATE_CHANGE,
            enable=True,
            sequential=False,
        )
        self.flap_step.driver.async_enable_ports_via_ssh.assert_awaited_once()

    # ──────────────────────────────────────────────
    # run_coroutines
    # ──────────────────────────────────────────────

    async def test_run_coroutines_parallel(self):
        call_order = []

        async def coro(val):
            call_order.append(val)

        await self.flap_step.run_coroutines(
            [coro(1), coro(2), coro(3)], sequential=False
        )
        self.assertEqual(sorted(call_order), [1, 2, 3])

    async def test_run_coroutines_sequential(self):
        call_order = []

        async def coro(val):
            call_order.append(val)

        await self.flap_step.run_coroutines(
            [coro(1), coro(2), coro(3)], sequential=True
        )
        self.assertEqual(call_order, [1, 2, 3])

    async def test_run_coroutines_parallel_raises_on_error(self):
        async def good_coro():
            pass

        async def bad_coro():
            raise RuntimeError("flap failed")

        with self.assertRaises(RuntimeError):
            await self.flap_step.run_coroutines(
                [good_coro(), bad_coro()], sequential=False
            )

    async def test_run_coroutines_sequential_raises_on_error(self):
        call_order = []

        async def good_coro():
            call_order.append("good")

        async def bad_coro():
            raise RuntimeError("flap failed")

        async def never_reached():
            call_order.append("never")

        with self.assertRaises(RuntimeError):
            await self.flap_step.run_coroutines(
                [good_coro(), bad_coro(), never_reached()], sequential=True
            )
        self.assertEqual(call_order, ["good"])

    # ──────────────────────────────────────────────
    # flap_with_thrift
    # ──────────────────────────────────────────────

    async def test_flap_with_thrift_success(self):
        self.driver_mock.async_get_all_interfaces_info = AsyncMock(
            return_value={
                "eth1/1/1": MagicMock(port_id=1),
                "eth1/2/1": MagicMock(port_id=2),
            }
        )
        self.driver_mock.async_set_port_state = AsyncMock()
        result = await self.flap_step.flap_with_thrift(
            ["eth1/1/1", "eth1/2/1"], enable=True, sequential=False
        )
        self.assertTrue(result)
        self.assertEqual(self.driver_mock.async_set_port_state.await_count, 2)
        self.driver_mock.async_set_port_state.assert_any_await(1, True)
        self.driver_mock.async_set_port_state.assert_any_await(2, True)

    async def test_flap_with_thrift_disable(self):
        self.driver_mock.async_get_all_interfaces_info = AsyncMock(
            return_value={"eth1/1/1": MagicMock(port_id=1)}
        )
        self.driver_mock.async_set_port_state = AsyncMock()
        result = await self.flap_step.flap_with_thrift(
            ["eth1/1/1"], enable=False, sequential=False
        )
        self.assertTrue(result)
        self.driver_mock.async_set_port_state.assert_awaited_once_with(1, False)

    async def test_flap_with_thrift_returns_false_on_failure(self):
        self.driver_mock.async_get_all_interfaces_info = AsyncMock(
            side_effect=Exception("thrift error")
        )
        result = await self.flap_step.flap_with_thrift(
            ["eth1/1/1"], enable=True, sequential=False
        )
        self.assertFalse(result)

    async def test_flap_with_thrift_sequential(self):
        self.driver_mock.async_get_all_interfaces_info = AsyncMock(
            return_value={
                "eth1/1/1": MagicMock(port_id=1),
                "eth1/2/1": MagicMock(port_id=2),
            }
        )
        self.driver_mock.async_set_port_state = AsyncMock()
        result = await self.flap_step.flap_with_thrift(
            ["eth1/1/1", "eth1/2/1"], enable=True, sequential=True
        )
        self.assertTrue(result)
        self.assertEqual(self.driver_mock.async_set_port_state.await_count, 2)

    # ──────────────────────────────────────────────
    # flap_with_ssh
    # ──────────────────────────────────────────────

    async def test_flap_with_ssh(self):
        self.driver_mock.async_enable_ports_via_ssh = AsyncMock()
        await self.flap_step.flap_with_ssh(
            ["eth1/1/1", "eth1/2/1"], enable=True, sequential=False
        )
        self.assertEqual(self.driver_mock.async_enable_ports_via_ssh.await_count, 2)
        self.driver_mock.async_enable_ports_via_ssh.assert_any_await(["eth1/1/1"], True)
        self.driver_mock.async_enable_ports_via_ssh.assert_any_await(["eth1/2/1"], True)

    async def test_flap_with_ssh_sequential(self):
        self.driver_mock.async_enable_ports_via_ssh = AsyncMock()
        await self.flap_step.flap_with_ssh(
            ["eth1/1/1", "eth1/2/1"], enable=False, sequential=True
        )
        self.assertEqual(self.driver_mock.async_enable_ports_via_ssh.await_count, 2)

    # ──────────────────────────────────────────────
    # flap_with_shell_cmd
    # ──────────────────────────────────────────────

    async def test_shell_cmd_parallel_single_command(self):
        self.driver_mock.async_run_cmd_on_shell = AsyncMock()
        await self.flap_step.flap_with_shell_cmd(
            ["eth1/1/1", "eth1/2/1", "eth1/3/1"],
            "--tx_disable",
            sequential=False,
        )
        self.driver_mock.async_run_cmd_on_shell.assert_awaited_once_with(
            "wedge_qsfp_util --tx_disable eth1/1/1 eth1/2/1 eth1/3/1"
        )

    async def test_shell_cmd_sequential_individual_commands(self):
        self.driver_mock.async_run_cmd_on_shell = AsyncMock()
        await self.flap_step.flap_with_shell_cmd(
            ["eth1/1/1", "eth1/2/1", "eth1/3/1"],
            "--tx_enable",
            sequential=True,
        )
        self.assertEqual(self.driver_mock.async_run_cmd_on_shell.await_count, 3)
        self.driver_mock.async_run_cmd_on_shell.assert_any_await(
            "wedge_qsfp_util --tx_enable eth1/1/1"
        )
        self.driver_mock.async_run_cmd_on_shell.assert_any_await(
            "wedge_qsfp_util --tx_enable eth1/2/1"
        )
        self.driver_mock.async_run_cmd_on_shell.assert_any_await(
            "wedge_qsfp_util --tx_enable eth1/3/1"
        )

    async def test_shell_cmd_parallel_single_interface(self):
        self.driver_mock.async_run_cmd_on_shell = AsyncMock()
        await self.flap_step.flap_with_shell_cmd(
            ["eth1/1/1"], "--set_low_power", sequential=False
        )
        self.driver_mock.async_run_cmd_on_shell.assert_awaited_once_with(
            "wedge_qsfp_util --set_low_power eth1/1/1"
        )

    async def test_shell_cmd_error_propagates(self):
        self.driver_mock.async_run_cmd_on_shell = AsyncMock(
            side_effect=RuntimeError("SSH failed")
        )
        with self.assertRaises(RuntimeError):
            await self.flap_step.flap_with_shell_cmd(
                ["eth1/1/1"], "--tx_disable", sequential=False
            )
