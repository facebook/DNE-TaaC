# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import base64
import math
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import later.unittest
from taac.tasks.all import (
    AristaCreateFileFromConfig,
    RunCommandsOnShell,
    ValidateBgpcppUpdateGroupState,
)


ALL_PATH = "neteng.test_infra.dne.taac.tasks.all"


def _count_chunk_commands(call_args_list) -> int:
    """Count the base64 chunk-upload commands among driver shell calls.

    Chunk commands are the `echo '<chunk>' >|>> file.b64` writes; the
    `base64 -d`, `wc -c`, and `rm -f` commands do not contain `echo '`.
    """
    return sum(1 for call in call_args_list if "echo '" in call.args[0])


class AristaCreateFileFromConfigTest(unittest.IsolatedAsyncioTestCase):
    """Unit tests for AristaCreateFileFromConfig chunking behavior."""

    def setUp(self) -> None:
        self.logger = MagicMock()
        self.task = AristaCreateFileFromConfig(
            hostname="bag012.ash6",
            logger=self.logger,
        )

    def _make_driver(self, expected_size: int) -> MagicMock:
        """Build a mock driver whose `wc -c` returns the expected byte size."""
        driver = MagicMock()

        async def fake_exec(cmd, *args, **kwargs):
            if "wc -c" in cmd:
                return str(expected_size)
            return ""

        driver.async_execute_show_or_configure_cmd_on_shell = AsyncMock(
            side_effect=fake_exec
        )
        return driver

    async def _run_with_content(
        self, content: str, params_extra: dict | None = None
    ) -> MagicMock:
        expected_size = len(content.encode("utf-8"))
        driver = self._make_driver(expected_size)

        params = {
            "hostname": "bag012.ash6",
            "configerator_path": "taac/ebb_ci_cd_configs/ebb_full_scale_bgpcpp_config",
            "file_path": "/mnt/flash/bgpcpp_config",
        }
        if params_extra:
            params.update(params_extra)

        with (
            patch(f"{ALL_PATH}.ConfigeratorClient") as mock_cfg,
            patch(
                f"{ALL_PATH}.async_get_device_driver",
                new_callable=AsyncMock,
                return_value=driver,
            ),
        ):
            mock_cfg.return_value.__enter__.return_value.get_config_contents.return_value = content
            await self.task.run(params)

        return driver

    def test_default_chunk_size_is_30k(self) -> None:
        self.assertEqual(30000, AristaCreateFileFromConfig.DEFAULT_CHUNK_SIZE)

    async def test_uses_default_chunk_size(self) -> None:
        content = "x" * 250000
        encoded_len = len(base64.b64encode(content.encode("utf-8")).decode("utf-8"))
        expected_chunks = math.ceil(
            encoded_len / AristaCreateFileFromConfig.DEFAULT_CHUNK_SIZE
        )

        driver = await self._run_with_content(content)

        actual_chunks = _count_chunk_commands(
            driver.async_execute_show_or_configure_cmd_on_shell.call_args_list
        )
        self.assertEqual(expected_chunks, actual_chunks)
        self.assertEqual(12, expected_chunks)

    async def test_custom_chunk_size_override(self) -> None:
        # An explicit chunk_size param overrides the default.
        content = "y" * 250000
        encoded_len = len(base64.b64encode(content.encode("utf-8")).decode("utf-8"))
        expected_chunks = math.ceil(encoded_len / 30000)

        driver = await self._run_with_content(content, {"chunk_size": 30000})

        actual_chunks = _count_chunk_commands(
            driver.async_execute_show_or_configure_cmd_on_shell.call_args_list
        )
        self.assertEqual(expected_chunks, actual_chunks)

    async def test_size_mismatch_retries_then_raises(self) -> None:
        # wc -c always reports a wrong size -> task retries MAX_RETRIES times
        # then raises, never silently succeeding on a truncated file.
        content = "z" * 1000
        driver = MagicMock()

        async def fake_exec(cmd, *args, **kwargs):
            if "wc -c" in cmd:
                return "1"  # wrong size on every attempt
            return ""

        driver.async_execute_show_or_configure_cmd_on_shell = AsyncMock(
            side_effect=fake_exec
        )

        params = {
            "hostname": "bag012.ash6",
            "configerator_path": "taac/foo",
            "file_path": "/mnt/flash/bgpcpp_config",
        }
        with (
            patch(f"{ALL_PATH}.ConfigeratorClient") as mock_cfg,
            patch(
                f"{ALL_PATH}.async_get_device_driver",
                new_callable=AsyncMock,
                return_value=driver,
            ),
        ):
            mock_cfg.return_value.__enter__.return_value.get_config_contents.return_value = content
            with self.assertRaisesRegex(Exception, "File size mismatch"):
                await self.task.run(params)

        # wc -c should have been invoked once per retry attempt.
        wc_calls = sum(
            1
            for call in driver.async_execute_show_or_configure_cmd_on_shell.call_args_list
            if "wc -c" in call.args[0]
        )
        self.assertEqual(AristaCreateFileFromConfig.MAX_RETRIES, wc_calls)


class RunCommandsOnShellTest(later.unittest.TestCase):
    def setUp(self) -> None:
        self.driver = MagicMock()
        self.driver.async_run_cmd_on_shell = AsyncMock()
        self.driver.async_execute_show_or_configure_cmd_on_shell = AsyncMock()
        self.task = RunCommandsOnShell(
            hostname="bag012.ash6",
            logger=MagicMock(),
        )

    async def test_uses_existing_unvalidated_path_by_default(self) -> None:
        with patch(
            f"{ALL_PATH}.async_get_device_driver",
            new_callable=AsyncMock,
            return_value=self.driver,
        ):
            await self.task.run(
                {
                    "hostname": "bag012.ash6",
                    "cmds": ["show version"],
                }
            )

        self.driver.async_run_cmd_on_shell.assert_awaited_once_with("show version")
        self.driver.async_execute_show_or_configure_cmd_on_shell.assert_not_awaited()

    async def test_validates_output_when_requested(self) -> None:
        with patch(
            f"{ALL_PATH}.async_get_device_driver",
            new_callable=AsyncMock,
            return_value=self.driver,
        ):
            await self.task.run(
                {
                    "hostname": "bag012.ash6",
                    "cmds": ["bash false"],
                    "validate_output": True,
                }
            )

        self.driver.async_execute_show_or_configure_cmd_on_shell.assert_awaited_once_with(
            "bash false"
        )
        self.driver.async_run_cmd_on_shell.assert_not_awaited()


class ValidateBgpcppUpdateGroupStateTest(later.unittest.TestCase):
    def setUp(self) -> None:
        self.driver = MagicMock()
        self.logger = MagicMock()
        self.task = ValidateBgpcppUpdateGroupState(
            hostname="bag012.ash6",
            logger=self.logger,
        )

    async def test_accepts_expected_disabled_state(self) -> None:
        self.driver.async_get_update_group_info = AsyncMock(
            return_value=SimpleNamespace(enable_update_group=False)
        )
        with patch(
            f"{ALL_PATH}.async_get_device_driver",
            new_callable=AsyncMock,
            return_value=self.driver,
        ):
            await self.task.run(
                {
                    "hostname": "bag012.ash6",
                    "expect_enabled": False,
                }
            )
        self.driver.async_get_update_group_info.assert_awaited_once_with()
        self.logger.info.assert_called_once()
        log_message = self.logger.info.call_args.args[0]
        self.assertIn("enabled=False", log_message)
        self.assertIn("bag012.ash6", log_message)

    async def test_rejects_unexpected_enabled_state(self) -> None:
        self.driver.async_get_update_group_info = AsyncMock(
            return_value=SimpleNamespace(enable_update_group=True)
        )
        with (
            patch(
                f"{ALL_PATH}.async_get_device_driver",
                new_callable=AsyncMock,
                return_value=self.driver,
            ),
            self.assertRaisesRegex(RuntimeError, "expected False"),
        ):
            await self.task.run(
                {
                    "hostname": "bag012.ash6",
                    "expect_enabled": False,
                }
            )
        self.logger.info.assert_called_once()
        log_message = self.logger.info.call_args.args[0]
        self.assertIn("enabled=True", log_message)
        self.assertIn("expected False", log_message)

    async def test_logs_query_failure(self) -> None:
        self.driver.async_get_update_group_info = AsyncMock(
            side_effect=RuntimeError("permission denied")
        )
        with (
            patch(
                f"{ALL_PATH}.async_get_device_driver",
                new_callable=AsyncMock,
                return_value=self.driver,
            ),
            self.assertRaisesRegex(RuntimeError, "permission denied"),
        ):
            await self.task.run(
                {
                    "hostname": "bag012.ash6",
                    "expect_enabled": False,
                }
            )
        self.logger.exception.assert_called_once()
