# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""Unit tests for SetupBaseConfigsTask."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from neteng.netcastle.logger import ConsoleFileLogger
from taac.tasks.registry import TASK_NAME_TO_CLASS
from taac.tasks.setup_base_configs_task import (
    SetupBaseConfigsTask,
)

_TASK_MODULE = "neteng.test_infra.dne.taac.tasks.setup_base_configs_task"


class SetupBaseConfigsTaskTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.logger = MagicMock(spec=ConsoleFileLogger)

    def _patches(self):
        """Patch the driver lookup and the driver call the task delegates to."""
        return (
            patch(f"{_TASK_MODULE}.async_get_device_driver", new_callable=AsyncMock),
            patch(f"{_TASK_MODULE}.setup_base_configs", new_callable=AsyncMock),
        )

    async def test_configures_the_task_hostname(self) -> None:
        task = SetupBaseConfigsTask(logger=self.logger, hostname="switch-1")
        get_driver, setup = self._patches()

        with get_driver as mock_get_driver, setup as mock_setup:
            mock_get_driver.return_value = driver = MagicMock()
            await task.run({})

        mock_get_driver.assert_awaited_once_with("switch-1")
        mock_setup.assert_awaited_once_with(driver, restart_bgp=True)

    async def test_params_hostname_overrides_the_task_hostname(self) -> None:
        # Lets one Task definition be retargeted from params without rewriting
        # the Task itself, which is how the parameterized configs drive it.
        task = SetupBaseConfigsTask(logger=self.logger, hostname="switch-1")
        get_driver, setup = self._patches()

        with get_driver as mock_get_driver, setup:
            mock_get_driver.return_value = MagicMock()
            await task.run({"hostname": "switch-2"})

        mock_get_driver.assert_awaited_once_with("switch-2")

    async def test_restart_bgp_is_forwarded(self) -> None:
        task = SetupBaseConfigsTask(logger=self.logger, hostname="switch-1")
        get_driver, setup = self._patches()

        with get_driver as mock_get_driver, setup as mock_setup:
            mock_get_driver.return_value = driver = MagicMock()
            await task.run({"restart_bgp": False})

        mock_setup.assert_awaited_once_with(driver, restart_bgp=False)

    async def test_missing_hostname_raises_before_touching_a_device(self) -> None:
        # The task configures one specific device; with no hostname there is
        # nothing sensible to default to, and silently doing nothing would be
        # worse than failing.
        task = SetupBaseConfigsTask(logger=self.logger)
        get_driver, setup = self._patches()

        with get_driver as mock_get_driver, setup as mock_setup:
            with self.assertRaises(ValueError) as ctx:
                await task.run({})

        self.assertIn("hostname", str(ctx.exception))
        mock_get_driver.assert_not_awaited()
        mock_setup.assert_not_awaited()

    def test_registered_under_its_name(self) -> None:
        # Test configs reference tasks by string, so an unregistered task fails
        # at run time with a KeyError rather than at import.
        self.assertIs(TASK_NAME_TO_CLASS["setup_base_configs"], SetupBaseConfigsTask)

    def test_available_in_oss(self) -> None:
        # It must be in the unconditional part of TASK_REGISTRY, not the
        # `if not TAAC_OSS` extension -- OSS is the only place it is useful.
        from taac.tasks import registry

        self.assertIn(SetupBaseConfigsTask, registry.TASK_REGISTRY)
