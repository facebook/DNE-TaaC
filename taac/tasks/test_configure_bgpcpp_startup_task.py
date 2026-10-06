# Copyright (c) Meta Platforms, Inc. and affiliates.

"""Unit tests for ConfigureBgpcppStartupTask and its shared sed builder."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import later.unittest
from neteng.netcastle.logger import ConsoleFileLogger
from taac.tasks.all import _truncate_cmd_for_log
from taac.tasks.configure_bgpcpp_startup_task import (
    _build_flag_sed_commands,
    _build_flag_verify_command,
    _FLAG_VERIFIED_SENTINEL,
    ConfigureBgpcppStartupTask,
    RUN_BGPCPP_SCRIPT_PATH,
)

_STARTUP_MODULE = "neteng.test_infra.dne.taac.tasks.configure_bgpcpp_startup_task"


class BuildFlagSedCommandsTest(unittest.TestCase):
    """The sed strings are load-bearing: their backslash escaping must match
    run_bgpcpp.sh's format, so pin both byte-for-byte."""

    def test_seds_are_byte_exact(self) -> None:
        cmds = _build_flag_sed_commands("my_flag", "true")
        self.assertEqual(
            cmds,
            [
                f'bash test "$(sudo grep -c -E -- '
                f"'^[[:space:]]*--max_rss_size=' {RUN_BGPCPP_SCRIPT_PATH})\" "
                f"-eq 1 && sudo sed -i '/^[[:space:]]*--my_flag=/d' "
                f"{RUN_BGPCPP_SCRIPT_PATH}",
                f'bash test "$(sudo grep -c -E -- '
                f"'^[[:space:]]*--max_rss_size=' {RUN_BGPCPP_SCRIPT_PATH})\" "
                f"-eq 1 && sudo sed -i '/--max_rss_size/i\\      "
                f"--my_flag=true \\\\' {RUN_BGPCPP_SCRIPT_PATH}",
            ],
        )

    def test_each_mutation_requires_exactly_one_insertion_anchor(self) -> None:
        for command in _build_flag_sed_commands("my_flag", "true"):
            self.assertIn("grep -c -E", command)
            self.assertIn(')" -eq 1 && sudo sed', command)

    def test_cleanup_matches_only_the_exact_flag_assignment(self) -> None:
        remove_cmd, _insert_cmd = _build_flag_sed_commands("my_flag", "true")

        self.assertIn("--my_flag=", remove_cmd)
        self.assertNotIn("/my_flag/d", remove_cmd)


class ConfigureBgpcppStartupManagedShellTest(later.unittest.TestCase):
    def setUp(self) -> None:
        self.logger = MagicMock(spec=ConsoleFileLogger)
        self.task = ConfigureBgpcppStartupTask(logger=self.logger)

    @patch(f"{_STARTUP_MODULE}.async_get_device_driver", new_callable=AsyncMock)
    async def test_managed_shell_runs_seds_via_driver(self, mock_get_driver) -> None:
        mock_driver = MagicMock()
        mock_driver.async_run_cmd_on_shell = AsyncMock(
            side_effect=["", "", _FLAG_VERIFIED_SENTINEL]
        )
        mock_get_driver.return_value = mock_driver

        await self.task.run(
            {
                "hostname": "bag010.ash6",
                "flags": {"bgp_resolve_nexthops_from_interface_state": "true"},
                "use_managed_shell": True,
            }
        )

        mock_get_driver.assert_awaited_once_with("bag010.ash6")
        sent = [c.args[0] for c in mock_driver.async_run_cmd_on_shell.await_args_list]
        self.assertEqual(
            sent,
            [
                *_build_flag_sed_commands(
                    "bgp_resolve_nexthops_from_interface_state", "true"
                ),
                _build_flag_verify_command(
                    "bgp_resolve_nexthops_from_interface_state", "true"
                ),
            ],
        )

    @patch(f"{_STARTUP_MODULE}.async_get_device_driver", new_callable=AsyncMock)
    async def test_multiple_flags_each_keep_a_line_continuation(
        self, mock_get_driver
    ) -> None:
        mock_driver = MagicMock()
        mock_driver.async_run_cmd_on_shell = AsyncMock(
            side_effect=[
                "",
                "",
                _FLAG_VERIFIED_SENTINEL,
                "",
                "",
                _FLAG_VERIFIED_SENTINEL,
            ]
        )
        mock_get_driver.return_value = mock_driver

        await self.task.run(
            {
                "hostname": "bag012.ash6",
                "flags": {
                    "agent_thrift_recv_timeout_ms": "160000",
                    "bgp_resolve_nexthops_from_interface_state": "true",
                },
                "use_managed_shell": True,
            }
        )

        sent = [c.args[0] for c in mock_driver.async_run_cmd_on_shell.await_args_list]
        self.assertEqual(
            sent,
            [
                *_build_flag_sed_commands("agent_thrift_recv_timeout_ms", "160000"),
                _build_flag_verify_command("agent_thrift_recv_timeout_ms", "160000"),
                *_build_flag_sed_commands(
                    "bgp_resolve_nexthops_from_interface_state", "true"
                ),
                _build_flag_verify_command(
                    "bgp_resolve_nexthops_from_interface_state", "true"
                ),
            ],
        )
        insertion_commands = [
            command for command in sent if "/--max_rss_size/i\\" in command
        ]
        self.assertTrue(
            all("/--max_rss_size/i\\" in command for command in insertion_commands)
        )
        self.assertTrue(
            all(
                f"\\\\' {RUN_BGPCPP_SCRIPT_PATH}" in command
                for command in insertion_commands
            )
        )

    @patch(f"{_STARTUP_MODULE}.AristaSSHHelper")
    @patch(f"{_STARTUP_MODULE}.async_get_device_driver", new_callable=AsyncMock)
    async def test_managed_shell_never_touches_ssh(
        self, mock_get_driver, mock_ssh_helper
    ) -> None:
        """Managed mode passes no SSH credentials, so it must never construct
        the raw-SSH helper."""
        mock_driver = MagicMock()
        mock_driver.async_run_cmd_on_shell = AsyncMock(
            side_effect=["", "", _FLAG_VERIFIED_SENTINEL]
        )
        mock_get_driver.return_value = mock_driver

        await self.task.run(
            {
                "hostname": "bag010.ash6",
                "flags": {"my_flag": "true"},
                "use_managed_shell": True,
            }
        )

        mock_ssh_helper.assert_not_called()

    @patch(f"{_STARTUP_MODULE}.async_get_device_driver", new_callable=AsyncMock)
    async def test_managed_shell_rejects_restart_before_writing(
        self, mock_get_driver
    ) -> None:
        with self.assertRaisesRegex(ValueError, "never restarted"):
            await self.task.run(
                {
                    "hostname": "bag010.ash6",
                    "flags": {"my_flag": "true"},
                    "use_managed_shell": True,
                    "restart_bgp": True,
                }
            )

        mock_get_driver.assert_not_awaited()

    @patch(f"{_STARTUP_MODULE}.async_get_device_driver", new_callable=AsyncMock)
    async def test_managed_shell_fails_when_inserted_flag_is_absent(
        self, mock_get_driver
    ) -> None:
        mock_driver = MagicMock()
        mock_driver.async_run_cmd_on_shell = AsyncMock(side_effect=["", "", ""])
        mock_get_driver.return_value = mock_driver

        with self.assertRaisesRegex(RuntimeError, "exactly one --max_rss_size"):
            await self.task.run(
                {
                    "hostname": "bag012.ash6",
                    "flags": {"my_flag": "true"},
                    "use_managed_shell": True,
                }
            )

    @patch(f"{_STARTUP_MODULE}.AristaSSHHelper")
    async def test_raw_ssh_runs_the_shared_sed_commands(self, mock_ssh_helper) -> None:
        helper = mock_ssh_helper.return_value
        helper.run_command.side_effect = [
            (True, "ok"),
            (True, "ok"),
            (True, _FLAG_VERIFIED_SENTINEL),
        ]

        await self.task.run(
            {
                "hostname": "bag010.ash6",
                "flags": {"my_flag": "true"},
                "use_managed_shell": False,
            }
        )

        sent = [call.args[0] for call in helper.run_command.call_args_list]
        self.assertEqual(
            sent,
            [
                *_build_flag_sed_commands("my_flag", "true"),
                _build_flag_verify_command("my_flag", "true"),
            ],
        )

    @patch(f"{_STARTUP_MODULE}.AristaSSHHelper")
    async def test_raw_ssh_fails_when_inserted_flag_is_absent(
        self, mock_ssh_helper
    ) -> None:
        helper = mock_ssh_helper.return_value
        helper.run_command.side_effect = [
            (True, "ok"),
            (True, "ok"),
            (False, "not found"),
        ]

        with self.assertRaisesRegex(RuntimeError, "exactly one --max_rss_size"):
            await self.task.run(
                {
                    "hostname": "bag012.ash6",
                    "flags": {"my_flag": "true"},
                    "use_managed_shell": False,
                }
            )


class TruncateCmdForLogTest(unittest.TestCase):
    def test_short_cmd_passthrough(self) -> None:
        cmd = "show bgp summary"
        self.assertEqual(_truncate_cmd_for_log(cmd), cmd)

    def test_long_cmd_is_bounded(self) -> None:
        cmd = "x" * 5000
        logged = _truncate_cmd_for_log(cmd)
        self.assertTrue(logged.startswith("x" * 200))
        self.assertIn("[truncated 5000 chars]", logged)
        self.assertLess(len(logged), len(cmd))
