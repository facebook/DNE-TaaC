# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import unittest
from unittest.mock import AsyncMock, call, MagicMock, patch

from taac.tasks.interface_ip_configuration_task import (
    InterfaceIpConfigurationTask,
)


TASK_PATH = "neteng.test_infra.dne.taac.tasks.interface_ip_configuration_task"
ARISTA_UTILS_PATH = "neteng.test_infra.dne.taac.utils.arista_utils"


class InterfaceIpConfigurationTaskTest(unittest.IsolatedAsyncioTestCase):
    """Unit tests for InterfaceIpConfigurationTask.

    The real IP-address generators are used (they are pure functions) so a
    peer_count of 0 exercises the actual empty-address-list path; only the
    device driver and the config-push/backup IO are mocked.
    """

    def setUp(self) -> None:
        self.logger = MagicMock()
        self.shared_data = {}
        self.task = InterfaceIpConfigurationTask(
            hostname="bag010.ash6",
            logger=self.logger,
            shared_data=self.shared_data,
        )

    @patch(f"{ARISTA_UTILS_PATH}.restore_running_config", new_callable=AsyncMock)
    @patch(
        f"{ARISTA_UTILS_PATH}.configure_interface_secondary_ips", new_callable=AsyncMock
    )
    @patch(f"{ARISTA_UTILS_PATH}.save_running_config", new_callable=AsyncMock)
    @patch(f"{ARISTA_UTILS_PATH}.backup_config_exists", new_callable=AsyncMock)
    @patch(f"{TASK_PATH}.async_get_device_driver", new_callable=AsyncMock)
    async def test_repeated_configuration_reuses_first_backup(
        self,
        mock_get_driver,
        mock_backup_exists,
        mock_save,
        mock_configure,
        mock_restore,
    ) -> None:
        mock_backup_exists.return_value = True
        mock_save.return_value = "flash:first_backup"
        params = {
            "interface": "Ethernet3/36/2",
            "ipv4_base_network": "10.163.28",
            "peer_count": 1,
            "address_families": ["ipv4"],
            "clear_existing": True,
        }

        await self.task.run(params)
        await self.task.run(params)

        mock_save.assert_awaited_once()
        mock_backup_exists.assert_awaited_once_with(
            mock_get_driver.return_value, "flash:first_backup"
        )
        self.assertEqual(
            "flash:first_backup",
            self.shared_data["interface_ip_backup__Ethernet3/36/2"],
        )
        self.assertEqual(2, mock_configure.await_count)
        mock_restore.assert_not_awaited()
        self.assertEqual(
            1,
            self.logger.info.call_args_list.count(
                call("  Stored backup reference: interface_ip_backup__Ethernet3/36/2")
            ),
        )
        self.logger.info.assert_any_call("Reusing original backup: flash:first_backup")

    @patch(f"{ARISTA_UTILS_PATH}.restore_running_config", new_callable=AsyncMock)
    @patch(
        f"{ARISTA_UTILS_PATH}.configure_interface_secondary_ips", new_callable=AsyncMock
    )
    @patch(f"{ARISTA_UTILS_PATH}.save_running_config", new_callable=AsyncMock)
    @patch(f"{ARISTA_UTILS_PATH}.backup_config_exists", new_callable=AsyncMock)
    @patch(f"{TASK_PATH}.async_get_device_driver", new_callable=AsyncMock)
    async def test_stale_backup_reference_is_replaced(
        self,
        mock_get_driver,
        mock_backup_exists,
        mock_save,
        mock_configure,
        mock_restore,
    ) -> None:
        backup_key = "interface_ip_backup__Ethernet3/36/2"
        self.shared_data[backup_key] = "flash:missing_backup"
        mock_backup_exists.return_value = False
        mock_save.return_value = "flash:replacement_backup"

        await self.task.run(
            {
                "interface": "Ethernet3/36/2",
                "ipv4_base_network": "10.163.28",
                "peer_count": 1,
                "address_families": ["ipv4"],
                "clear_existing": True,
            }
        )

        mock_backup_exists.assert_awaited_once_with(
            mock_get_driver.return_value, "flash:missing_backup"
        )
        mock_save.assert_awaited_once()
        self.assertEqual("flash:replacement_backup", self.shared_data[backup_key])
        mock_configure.assert_awaited_once()
        mock_restore.assert_not_awaited()
        self.logger.warning.assert_called_once_with(
            "Stored backup no longer exists; creating a new one: flash:missing_backup"
        )

    @patch(f"{ARISTA_UTILS_PATH}.restore_running_config", new_callable=AsyncMock)
    @patch(
        f"{ARISTA_UTILS_PATH}.configure_interface_secondary_ips", new_callable=AsyncMock
    )
    @patch(f"{ARISTA_UTILS_PATH}.save_running_config", new_callable=AsyncMock)
    @patch(f"{TASK_PATH}.async_get_device_driver", new_callable=AsyncMock)
    async def test_zero_peer_count_ipv6_does_not_raise(
        self, mock_get_driver, mock_save, mock_configure, mock_restore
    ) -> None:
        # Ingress-only setups pass peer_count=0 for the iBGP interface; the task
        # must clear the interface with an empty address list rather than crash
        # on ipv6_addresses[0].
        mock_save.return_value = "flash:taac_backup"

        params = {
            "interface": "Ethernet3/36/2",
            "ipv6_base_network": "2401:db00:e50d:11:9",
            "peer_count": 0,
            "address_families": ["ipv6"],
            "clear_existing": True,
        }
        await self.task.run(params)

        mock_configure.assert_awaited_once()
        call_kwargs = mock_configure.call_args.kwargs
        self.assertEqual(call_kwargs["ipv6_addresses"], [])
        self.assertTrue(call_kwargs["clear_existing"])
        # No failure -> backup must not be restored.
        mock_restore.assert_not_awaited()

    @patch(f"{ARISTA_UTILS_PATH}.restore_running_config", new_callable=AsyncMock)
    @patch(
        f"{ARISTA_UTILS_PATH}.configure_interface_secondary_ips", new_callable=AsyncMock
    )
    @patch(f"{ARISTA_UTILS_PATH}.save_running_config", new_callable=AsyncMock)
    @patch(f"{TASK_PATH}.async_get_device_driver", new_callable=AsyncMock)
    async def test_zero_peer_count_ipv4_does_not_raise(
        self, mock_get_driver, mock_save, mock_configure, mock_restore
    ) -> None:
        mock_save.return_value = "flash:taac_backup"

        params = {
            "interface": "Ethernet3/36/2",
            "ipv4_base_network": "10.163.28",
            "peer_count": 0,
            "address_families": ["ipv4"],
            "clear_existing": True,
        }
        await self.task.run(params)

        mock_configure.assert_awaited_once()
        call_kwargs = mock_configure.call_args.kwargs
        self.assertEqual(call_kwargs["ipv4_addresses"], [])
        mock_restore.assert_not_awaited()

    @patch(f"{ARISTA_UTILS_PATH}.restore_running_config", new_callable=AsyncMock)
    @patch(
        f"{ARISTA_UTILS_PATH}.configure_interface_secondary_ips", new_callable=AsyncMock
    )
    @patch(f"{ARISTA_UTILS_PATH}.save_running_config", new_callable=AsyncMock)
    @patch(f"{TASK_PATH}.async_get_device_driver", new_callable=AsyncMock)
    async def test_positive_peer_count_generates_ipv6(
        self, mock_get_driver, mock_save, mock_configure, mock_restore
    ) -> None:
        # Regression: the normal (non-zero) path still generates and applies the
        # expected number of addresses.
        mock_save.return_value = "flash:taac_backup"

        params = {
            "interface": "Ethernet3/36/1",
            "ipv6_base_network": "2401:db00:e50d:11:8",
            "peer_count": 3,
            "address_families": ["ipv6"],
            "clear_existing": True,
        }
        await self.task.run(params)

        mock_configure.assert_awaited_once()
        call_kwargs = mock_configure.call_args.kwargs
        self.assertEqual(len(call_kwargs["ipv6_addresses"]), 3)
        mock_restore.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
