# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import base64
import math
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from taac.tasks.all import AristaCreateFileFromConfig


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
