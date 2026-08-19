# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

from unittest.mock import AsyncMock, call, MagicMock, patch

from later.unittest import TestCase
from taac.internal.tasks.eos_compiler_lifecycle_task import (
    EosCompilerLifecycleTask,
)


_MODULE = "neteng.test_infra.dne.taac.internal.tasks.eos_compiler_lifecycle_task"


def _physical_params(
    operation_id: str,
    interface: str,
    *,
    aggregate_gbps: int = 100,
    lane_count: int = 2,
) -> dict[str, object]:
    return {
        "action": "physical_apply",
        "hostname": "dut.example.com",
        "operation_id": operation_id,
        "interface": interface,
        "aggregate_gbps": aggregate_gbps,
        "lane_count": lane_count,
        "ipv4_cidrs": ["192.0.2.1/31"],
        "ipv6_cidrs": ["2001:db8::1/127"],
    }


def _readback(interface: str, speed: str = "100g-2") -> str:
    return "\n".join(
        (
            f"interface {interface}",
            f"   speed {speed}",
            "   no switchport",
            "   ip address 192.0.2.1/31",
            "   ipv6 enable",
            "   ipv6 address 2001:db8::1/127",
        )
    )


class EosCompilerLifecycleTaskTest(TestCase):
    async def test_physical_apply_captures_once_and_verifies_exact_readback(
        self,
    ) -> None:
        driver = MagicMock()
        driver.async_execute_show_or_configure_cmd_on_shell = AsyncMock(
            side_effect=("", _readback("Ethernet1"), "", _readback("Ethernet1"))
        )
        shared_data: dict[object, object] = {}
        task = EosCompilerLifecycleTask(
            hostname="dut.example.com",
            logger=MagicMock(),
            shared_data=shared_data,
        )
        params = _physical_params(
            "physical_interface:dut0/reuse_group/ebgp", "Ethernet1"
        )

        with (
            patch(f"{_MODULE}.async_get_device_driver", AsyncMock(return_value=driver)),
            patch(
                f"{_MODULE}.arista_utils.save_running_config",
                AsyncMock(return_value="flash:taac-original"),
            ) as save_running_config,
        ):
            await task.run(params)
            await task.run(params)

        save_running_config.assert_awaited_once_with(
            driver,
            backup_name=None,
            logger_instance=task.logger,
        )
        configure_call = (
            driver.async_execute_show_or_configure_cmd_on_shell.await_args_list[0]
        )
        command = configure_call.args[0]
        self.assertIn("default interface Ethernet1", command)
        self.assertIn("speed 100g-2", command)
        self.assertIn("ip address 192.0.2.1/31", command)
        self.assertIn("ipv6 address 2001:db8::1/127", command)
        self.assertTrue(configure_call.kwargs["configure"])

    async def test_physical_apply_rejects_readback_drift(self) -> None:
        driver = MagicMock()
        driver.async_execute_show_or_configure_cmd_on_shell = AsyncMock(
            side_effect=("", "interface Ethernet1\n   speed 400g-8")
        )
        task = EosCompilerLifecycleTask(
            hostname="dut.example.com",
            logger=MagicMock(),
            shared_data={},
        )

        with (
            patch(f"{_MODULE}.async_get_device_driver", AsyncMock(return_value=driver)),
            patch(
                f"{_MODULE}.arista_utils.save_running_config",
                AsyncMock(return_value="flash:taac-original"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "exact readback"):
                await task.run(
                    _physical_params(
                        "physical_interface:dut0/reuse_group/ebgp",
                        "Ethernet1",
                    )
                )

    async def test_physical_restore_unwinds_snapshots_in_declared_order(self) -> None:
        driver = MagicMock()

        async def execute(command: str, *, configure: bool = False) -> str:
            if configure:
                return ""
            interface = "Ethernet2" if "Ethernet2" in command else "Ethernet1"
            return _readback(interface)

        driver.async_execute_show_or_configure_cmd_on_shell = AsyncMock(
            side_effect=execute
        )
        task = EosCompilerLifecycleTask(
            hostname="dut.example.com",
            logger=MagicMock(),
            shared_data={},
        )
        first_id = "physical_interface:dut0/reuse_group/first"
        second_id = "physical_interface:dut0/reuse_group/second"
        restore = AsyncMock()
        delete = AsyncMock()

        with (
            patch(f"{_MODULE}.async_get_device_driver", AsyncMock(return_value=driver)),
            patch(
                f"{_MODULE}.arista_utils.save_running_config",
                AsyncMock(side_effect=("flash:first", "flash:second")),
            ),
            patch(
                f"{_MODULE}.arista_utils.restore_running_config",
                restore,
            ),
            patch(
                f"{_MODULE}.arista_utils.delete_backup_config",
                delete,
            ),
        ):
            await task.run(_physical_params(first_id, "Ethernet1"))
            await task.run(_physical_params(second_id, "Ethernet2"))
            await task.run(
                {
                    "action": "physical_restore",
                    "hostname": "dut.example.com",
                    "operations": [
                        {"operation_id": second_id, "interface": "Ethernet2"},
                        {"operation_id": first_id, "interface": "Ethernet1"},
                    ],
                }
            )

        self.assertEqual(
            [
                call(driver, "flash:second", logger_instance=task.logger),
                call(driver, "flash:first", logger_instance=task.logger),
            ],
            restore.await_args_list,
        )
        self.assertEqual(2, delete.await_count)
