# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

import asyncio
import base64
import hashlib
from unittest.mock import AsyncMock, call, MagicMock, patch

from later.unittest import TestCase
from taac.driver.drivers_common import CommandExecutionError
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


def _routing_config_params(action: str) -> dict[str, object]:
    params: dict[str, object] = {
        "action": action,
        "hostname": "dut.example.com",
        "operation_id": "routing_config:dut0",
        "destination": "/mnt/flash/bgpcpp_config",
    }
    if action == "routing_config_verify":
        params["source_path"] = "configerator/raw_configs/test/bgpcpp.json"
    return params


class EosCompilerLifecycleTaskTest(TestCase):
    async def test_physical_apply_captures_once_and_verifies_exact_readback(
        self,
    ) -> None:
        driver = MagicMock()
        driver.async_execute_show_or_configure_cmd_on_shell = AsyncMock(
            side_effect=("", _readback("Ethernet1"), "", _readback("Ethernet1"))
        )
        task = EosCompilerLifecycleTask(
            hostname="dut.example.com",
            logger=MagicMock(),
            shared_data={},
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
        shared_data: dict[object, object] = {}
        logger = MagicMock()
        task = EosCompilerLifecycleTask(
            hostname="dut.example.com",
            logger=logger,
            shared_data=shared_data,
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

    async def test_routing_config_restores_prior_absence(self) -> None:
        driver = MagicMock()
        driver.async_read_file = AsyncMock(side_effect=FileNotFoundError)
        driver.async_execute_show_or_configure_cmd_on_shell = AsyncMock(return_value="")
        task = EosCompilerLifecycleTask(
            hostname="dut.example.com",
            logger=MagicMock(),
            shared_data={},
        )

        with patch(
            f"{_MODULE}.async_get_device_driver",
            AsyncMock(return_value=driver),
        ):
            await task.run(_routing_config_params("routing_config_snapshot"))
            await task.run(_routing_config_params("routing_config_restore"))

        remove_call = driver.async_execute_show_or_configure_cmd_on_shell.await_args
        assert remove_call is not None
        self.assertEqual(
            "bash sudo rm -f '/mnt/flash/bgpcpp_config'",
            remove_call.args[0],
        )

    async def test_routing_config_snapshot_reports_transport_failure(self) -> None:
        driver = MagicMock()
        driver.async_read_file = AsyncMock(
            side_effect=CommandExecutionError("transport failed")
        )
        shared_data: dict[object, object] = {}
        task = EosCompilerLifecycleTask(
            hostname="dut.example.com",
            logger=MagicMock(),
            shared_data=shared_data,
        )

        with patch(
            f"{_MODULE}.async_get_device_driver",
            AsyncMock(return_value=driver),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "snapshot failed before install: unable to read ",
            ):
                await task.run(_routing_config_params("routing_config_snapshot"))

        self.assertEqual({}, shared_data)

    async def test_routing_config_restore_without_snapshot_fails_loudly(
        self,
    ) -> None:
        task = EosCompilerLifecycleTask(
            hostname="dut.example.com",
            logger=MagicMock(),
            shared_data={},
        )
        get_driver = AsyncMock()

        with patch(f"{_MODULE}.async_get_device_driver", get_driver):
            with self.assertRaisesRegex(
                RuntimeError,
                "restore invoked without snapshot for routing_config:dut0",
            ):
                await task.run(_routing_config_params("routing_config_restore"))

        get_driver.assert_not_awaited()

    async def test_routing_config_verifies_source_and_restores_prior_bytes(
        self,
    ) -> None:
        prior_bytes = b"prior\xffbytes"
        driver = MagicMock()
        driver.async_read_file = AsyncMock(
            side_effect=(
                prior_bytes.decode("utf-8", errors="surrogateescape"),
                "new bytes",
            )
        )

        async def execute(command: str, *, configure: bool = False) -> str:
            if "stat -c" in command:
                return "switch#\n10:23:45\ntaac-file-metadata:640:42:43\nswitch#"
            if "sha256sum" in command:
                return (
                    "switch#\n"
                    f"{hashlib.sha256(prior_bytes).hexdigest()}  restore.tmp\n"
                    "switch#"
                )
            return ""

        driver.async_execute_show_or_configure_cmd_on_shell = AsyncMock(
            side_effect=execute
        )
        shared_data: dict[object, object] = {}
        logger = MagicMock()
        task = EosCompilerLifecycleTask(
            hostname="dut.example.com",
            logger=logger,
            shared_data=shared_data,
        )
        client = MagicMock()
        client.__enter__.return_value.get_config_contents.return_value = "new bytes"

        with (
            patch(
                f"{_MODULE}.async_get_device_driver",
                AsyncMock(return_value=driver),
            ),
            patch(f"{_MODULE}.ConfigeratorClient", return_value=client),
        ):
            await task.run(_routing_config_params("routing_config_snapshot"))
            await task.run(_routing_config_params("routing_config_verify"))
            await task.run(_routing_config_params("routing_config_restore"))

        commands = tuple(
            item.args[0]
            for item in driver.async_execute_show_or_configure_cmd_on_shell.await_args_list
        )
        self.assertTrue(any("base64 -d" in command for command in commands))
        self.assertTrue(any("sha256sum" in command for command in commands))
        self.assertTrue(any("chown 42:43" in command for command in commands))
        self.assertTrue(any("chmod '640'" in command for command in commands))
        self.assertTrue(any("mv -f" in command for command in commands))
        encoded_prior_bytes = base64.b64encode(prior_bytes).decode("ascii")
        self.assertTrue(any(encoded_prior_bytes in command for command in commands))
        self.assertTrue(
            all("/mnt/flash/bgpcpp_config" in command for command in commands)
        )
        logger.info.assert_called_once()

    async def test_routing_config_rejects_exact_readback_drift(self) -> None:
        driver = MagicMock()
        driver.async_read_file = AsyncMock(return_value="unexpected")
        task = EosCompilerLifecycleTask(
            hostname="dut.example.com",
            logger=MagicMock(),
            shared_data={},
        )
        client = MagicMock()
        client.__enter__.return_value.get_config_contents.return_value = "expected"

        with (
            patch(
                f"{_MODULE}.async_get_device_driver",
                AsyncMock(return_value=driver),
            ),
            patch(f"{_MODULE}.ConfigeratorClient", return_value=client),
        ):
            with self.assertRaisesRegex(RuntimeError, "exact readback"):
                await task.run(_routing_config_params("routing_config_verify"))

    async def test_routing_config_reports_missing_installed_file(self) -> None:
        driver = MagicMock()
        driver.async_read_file = AsyncMock(side_effect=FileNotFoundError)
        task = EosCompilerLifecycleTask(
            hostname="dut.example.com",
            logger=MagicMock(),
            shared_data={},
        )
        client = MagicMock()
        client.__enter__.return_value.get_config_contents.return_value = "expected"

        with (
            patch(
                f"{_MODULE}.async_get_device_driver",
                AsyncMock(return_value=driver),
            ),
            patch(f"{_MODULE}.ConfigeratorClient", return_value=client),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "installed file missing at /mnt/flash/bgpcpp_config",
            ):
                await task.run(_routing_config_params("routing_config_verify"))

    async def test_routing_config_restore_rejects_malformed_checksum_output(
        self,
    ) -> None:
        driver = MagicMock()
        driver.async_read_file = AsyncMock(return_value="prior bytes")

        async def execute(command: str, *, configure: bool = False) -> str:
            return "taac-file-metadata:640:42:43" if "stat -c" in command else ""

        driver.async_execute_show_or_configure_cmd_on_shell = AsyncMock(
            side_effect=execute
        )
        task = EosCompilerLifecycleTask(
            hostname="dut.example.com",
            logger=MagicMock(),
            shared_data={},
        )

        with patch(
            f"{_MODULE}.async_get_device_driver",
            AsyncMock(return_value=driver),
        ):
            await task.run(_routing_config_params("routing_config_snapshot"))
            with self.assertRaisesRegex(RuntimeError, "checksum output is malformed"):
                await task.run(_routing_config_params("routing_config_restore"))

        commands = tuple(
            item.args[0]
            for item in driver.async_execute_show_or_configure_cmd_on_shell.await_args_list
        )
        self.assertTrue(any("rm -f" in command for command in commands))

    async def test_routing_config_restore_logs_scratch_cleanup_failure(self) -> None:
        driver = MagicMock()
        driver.async_read_file = AsyncMock(return_value="prior bytes")

        async def execute(command: str, *, configure: bool = False) -> str:
            if "stat -c" in command:
                return "taac-file-metadata:640:42:43"
            if "sha256sum" in command:
                return hashlib.sha256(b"prior bytes").hexdigest()
            if "rm -f" in command:
                raise RuntimeError("scratch cleanup failed")
            return ""

        driver.async_execute_show_or_configure_cmd_on_shell = AsyncMock(
            side_effect=execute
        )
        logger = MagicMock()
        task = EosCompilerLifecycleTask(
            hostname="dut.example.com",
            logger=logger,
            shared_data={},
        )

        with patch(
            f"{_MODULE}.async_get_device_driver",
            AsyncMock(return_value=driver),
        ):
            await task.run(_routing_config_params("routing_config_snapshot"))
            await task.run(_routing_config_params("routing_config_restore"))

        logger.warning.assert_called_once()

    async def test_routing_config_restore_retries_checksum_mismatch(self) -> None:
        driver = MagicMock()
        driver.async_read_file = AsyncMock(return_value="prior bytes")
        checksum_attempts = 0

        async def execute(command: str, *, configure: bool = False) -> str:
            nonlocal checksum_attempts
            if "stat -c" in command:
                return "taac-file-metadata:640:42:43"
            if "sha256sum" in command:
                checksum_attempts += 1
                if checksum_attempts == 1:
                    return "0" * 64
                return hashlib.sha256(b"prior bytes").hexdigest()
            return ""

        driver.async_execute_show_or_configure_cmd_on_shell = AsyncMock(
            side_effect=execute
        )
        logger = MagicMock()
        task = EosCompilerLifecycleTask(
            hostname="dut.example.com",
            logger=logger,
            shared_data={},
        )

        with patch(
            f"{_MODULE}.async_get_device_driver",
            AsyncMock(return_value=driver),
        ):
            await task.run(_routing_config_params("routing_config_snapshot"))
            await task.run(_routing_config_params("routing_config_restore"))

        self.assertEqual(2, checksum_attempts)
        logger.warning.assert_called_once()

    async def test_routing_config_rejects_parent_path_components(self) -> None:
        task = EosCompilerLifecycleTask(
            hostname="dut.example.com",
            logger=MagicMock(),
            shared_data={},
        )
        get_driver = AsyncMock()

        with patch(f"{_MODULE}.async_get_device_driver", get_driver):
            snapshot_params = _routing_config_params("routing_config_snapshot")
            snapshot_params["destination"] = "/mnt/flash/../../etc/passwd"
            with self.assertRaisesRegex(ValueError, "safe absolute path"):
                await task.run(snapshot_params)

            verify_params = _routing_config_params("routing_config_verify")
            verify_params["source_path"] = "configerator/raw/../secret"
            with self.assertRaisesRegex(ValueError, "safe Configerator path"):
                await task.run(verify_params)

        get_driver.assert_not_awaited()

    async def test_routing_config_cancellation_does_not_start_cleanup(self) -> None:
        driver = MagicMock()
        driver.async_read_file = AsyncMock(return_value="prior bytes")

        async def execute(command: str, *, configure: bool = False) -> str:
            if "stat -c" in command:
                return "taac-file-metadata:640:42:43"
            raise asyncio.CancelledError

        driver.async_execute_show_or_configure_cmd_on_shell = AsyncMock(
            side_effect=execute
        )
        task = EosCompilerLifecycleTask(
            hostname="dut.example.com",
            logger=MagicMock(),
            shared_data={},
        )

        with patch(
            f"{_MODULE}.async_get_device_driver",
            AsyncMock(return_value=driver),
        ):
            await task.run(_routing_config_params("routing_config_snapshot"))
            with self.assertRaises(asyncio.CancelledError):
                await task.run(_routing_config_params("routing_config_restore"))

        commands = tuple(
            item.args[0]
            for item in driver.async_execute_show_or_configure_cmd_on_shell.await_args_list
        )
        self.assertFalse(any("rm -f" in command for command in commands))
