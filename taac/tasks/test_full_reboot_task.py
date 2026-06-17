# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""Unit tests for FullRebootTask."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from neteng.netcastle.logger import ConsoleFileLogger
from taac.tasks.full_reboot_task import FullRebootTask


class TestFullRebootTask(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.logger = MagicMock(spec=ConsoleFileLogger)
        self.task = FullRebootTask(logger=self.logger)

    @patch("neteng.test_infra.dne.taac.tasks.full_reboot_task.wait_for_ssh_reachable")
    @patch("neteng.test_infra.dne.taac.tasks.full_reboot_task.is_host_ssh_reachable")
    @patch("neteng.test_infra.dne.taac.tasks.full_reboot_task.ParamikoClient")
    async def test_happy_path_issues_reboot_then_waits_for_recovery(
        self, mock_client_cls, mock_is_reachable, mock_wait_reachable
    ):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        # Host becomes unreachable on first poll
        mock_is_reachable.return_value = False
        mock_wait_reachable.return_value = True

        await self.task.run({"hostname": "host.example.tfbnw.net"})

        mock_client_cls.assert_called_once_with(
            "host.example.tfbnw.net", username=None, password=None
        )
        mock_client.connect.assert_called_once()
        mock_client.run.assert_called_once_with("sudo systemctl reboot")
        mock_client.disconnect.assert_called_once()
        mock_wait_reachable.assert_called_once()

    @patch("neteng.test_infra.dne.taac.tasks.full_reboot_task.wait_for_ssh_reachable")
    @patch("neteng.test_infra.dne.taac.tasks.full_reboot_task.is_host_ssh_reachable")
    @patch("neteng.test_infra.dne.taac.tasks.full_reboot_task.ParamikoClient")
    async def test_reboot_cmd_exception_is_swallowed(
        self, mock_client_cls, mock_is_reachable, mock_wait_reachable
    ):
        """If the reboot causes the SSH channel to drop, we treat it as success."""
        mock_client = MagicMock()
        mock_client.run.side_effect = ConnectionError("channel closed")
        mock_client_cls.return_value = mock_client
        mock_is_reachable.return_value = False
        mock_wait_reachable.return_value = True

        # Should not raise
        await self.task.run({"hostname": "host.example.tfbnw.net"})
        mock_wait_reachable.assert_called_once()

    @patch("neteng.test_infra.dne.taac.tasks.full_reboot_task.wait_for_ssh_reachable")
    @patch("neteng.test_infra.dne.taac.tasks.full_reboot_task.is_host_ssh_reachable")
    @patch("neteng.test_infra.dne.taac.tasks.full_reboot_task.ParamikoClient")
    async def test_connect_failure_propagates(
        self, mock_client_cls, mock_is_reachable, mock_wait_reachable
    ):
        """Pre-reboot SSH connect must NOT be silently swallowed."""
        mock_client = MagicMock()
        mock_client.connect.side_effect = ConnectionRefusedError("host unreachable")
        mock_client_cls.return_value = mock_client

        with self.assertRaises(ConnectionRefusedError):
            await self.task.run({"hostname": "unreachable.example.tfbnw.net"})
        # Phase 2/3 should never have run
        mock_is_reachable.assert_not_called()
        mock_wait_reachable.assert_not_called()

    @patch.object(
        FullRebootTask, "_wait_for_unreachable", new=AsyncMock(return_value=None)
    )
    @patch("neteng.test_infra.dne.taac.tasks.full_reboot_task.ParamikoClient")
    async def test_fails_if_host_never_goes_down(self, mock_client_cls):
        """If the host stays SSH-reachable past down_max_s, raise TimeoutError.

        `_wait_for_unreachable` mocked to immediately return None (timeout signal)
        — bypasses the asyncio polling loop that's hard to time-mock cleanly.
        """
        mock_client_cls.return_value = MagicMock()
        with self.assertRaises(TimeoutError) as ctx:
            await self.task.run({"hostname": "host.example.tfbnw.net", "down_max_s": 5})
        self.assertIn("did not become SSH-unreachable", str(ctx.exception))

    @patch("neteng.test_infra.dne.taac.tasks.full_reboot_task.wait_for_ssh_reachable")
    @patch("neteng.test_infra.dne.taac.tasks.full_reboot_task.is_host_ssh_reachable")
    @patch("neteng.test_infra.dne.taac.tasks.full_reboot_task.ParamikoClient")
    async def test_custom_reboot_cmd_and_credentials_passed_through(
        self, mock_client_cls, mock_is_reachable, mock_wait_reachable
    ):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_is_reachable.return_value = False
        mock_wait_reachable.return_value = True

        await self.task.run(
            {
                "hostname": "host.example.tfbnw.net",
                "reboot_cmd": "sudo /sbin/reboot",
                "ssh_user": "admin",
                "ssh_password": "secret",
            }
        )
        mock_client_cls.assert_called_once_with(
            "host.example.tfbnw.net", username="admin", password="secret"
        )
        mock_client.run.assert_called_once_with("sudo /sbin/reboot")
        # password forwarded to the unreachable poll and the up-wait
        mock_wait_reachable.assert_called_once()
        _, kwargs = mock_wait_reachable.call_args
        self.assertEqual(kwargs["password"], "secret")
