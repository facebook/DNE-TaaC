# Copyright (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import ANY, AsyncMock, MagicMock, patch

from taac.task_definitions import (
    create_fpf_ensure_interfaces_enabled_task,
)
from taac.tasks import fpf_interface_admin_task


class FpfEnsureInterfacesEnabledTaskTest(unittest.IsolatedAsyncioTestCase):
    def test_factory_rejects_partially_empty_target_map(self) -> None:
        with self.assertRaisesRegex(ValueError, "empty targets.*gtsw002"):
            create_fpf_ensure_interfaces_enabled_task(
                {
                    "gtsw001": ["eth1/41/5"],
                    "gtsw002": [],
                }
            )

    @patch.object(fpf_interface_admin_task, "FbossSwitchInternal")
    async def test_missing_or_empty_targets_do_not_block_teardown(
        self, mock_driver_cls: MagicMock
    ) -> None:
        for params in ({}, {"targets": []}):
            with self.subTest(params=params):
                logger = MagicMock()
                await fpf_interface_admin_task.FpfEnsureInterfacesEnabledTask(
                    logger=logger
                ).run(params)
                logger.error.assert_called_once()
        mock_driver_cls.assert_not_called()

    @patch.object(fpf_interface_admin_task, "FbossSwitchInternal")
    async def test_timeout_is_logged_without_blocking_teardown(
        self, mock_driver_cls: MagicMock
    ) -> None:
        async def never_returns(**kwargs) -> None:
            await asyncio.Event().wait()

        driver = MagicMock()
        driver.async_thrift_disable_enable_interfaces = AsyncMock(
            side_effect=never_returns
        )
        driver.async_get_all_interfaces_admin_status = AsyncMock()
        mock_driver_cls.return_value = driver
        logger = MagicMock()

        await fpf_interface_admin_task.FpfEnsureInterfacesEnabledTask(
            logger=logger
        ).run(
            {
                "targets": [
                    {
                        "device": "gtsw001.l1002.c087.mwg2",
                        "interfaces": ["eth1/41/5"],
                    }
                ],
                "timeout_sec": 0.001,
            }
        )

        driver.async_get_all_interfaces_admin_status.assert_not_awaited()
        logger.error.assert_called_once()
        self.assertIn("TimeoutError", logger.error.call_args.args[0])

    @patch.object(fpf_interface_admin_task, "FbossSwitchInternal")
    async def test_enables_exact_targets_and_verifies_readback(
        self, mock_driver_cls: MagicMock
    ) -> None:
        driver = MagicMock()
        driver.async_thrift_disable_enable_interfaces = AsyncMock()
        driver.async_get_all_interfaces_admin_status = AsyncMock(
            return_value={"eth1/41/5": True}
        )
        mock_driver_cls.return_value = driver

        await fpf_interface_admin_task.FpfEnsureInterfacesEnabledTask().run(
            {
                "targets": [
                    {
                        "device": "gtsw001.l1002.c087.mwg2",
                        "interfaces": ["eth1/41/5"],
                    }
                ]
            }
        )

        mock_driver_cls.assert_called_once_with(
            hostname="gtsw001.l1002.c087.mwg2",
            logger=ANY,
        )
        driver.async_thrift_disable_enable_interfaces.assert_awaited_once_with(
            interface_names=["eth1/41/5"], is_enable_port=True
        )
        driver.async_get_all_interfaces_admin_status.assert_awaited_once_with()

    @patch.object(fpf_interface_admin_task, "FbossSwitchInternal")
    async def test_readback_failure_is_logged_without_blocking_teardown(
        self, mock_driver_cls: MagicMock
    ) -> None:
        driver = MagicMock()
        driver.async_thrift_disable_enable_interfaces = AsyncMock()
        driver.async_get_all_interfaces_admin_status = AsyncMock(
            return_value={"eth1/41/5": False}
        )
        mock_driver_cls.return_value = driver
        logger = MagicMock()

        await fpf_interface_admin_task.FpfEnsureInterfacesEnabledTask(
            logger=logger
        ).run(
            {
                "targets": [
                    {
                        "device": "gtsw001.l1002.c087.mwg2",
                        "interfaces": ["eth1/41/5"],
                    }
                ]
            }
        )

        logger.error.assert_called_once()
        self.assertIn("readback failed", logger.error.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
