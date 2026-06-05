# pyre-unsafe
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from taac.tasks.eos import (
    AddEosBgpPrefixListToPeerGroup,
    BackupRunningConfigTask,
    CreateEosBgpPeerGroup,
    RestoreRunningConfigTask,
)


ARISTA_SWITCH_PATH = (
    "neteng.test_infra.dne.taac.internal.driver.arista_switch.AristaSwitch"
)
ARISTA_UTILS_PATH = "neteng.test_infra.dne.taac.utils.arista_utils"


class CreateEosBgpPeerGroupTest(unittest.IsolatedAsyncioTestCase):
    """Unit tests for CreateEosBgpPeerGroup task."""

    def setUp(self) -> None:
        self.logger = MagicMock()
        self.task = CreateEosBgpPeerGroup(
            hostname="bag002.snc1",
            logger=self.logger,
        )

    @patch(ARISTA_SWITCH_PATH)
    async def test_create_peer_group_minimal(self, mock_switch_cls) -> None:
        mock_driver = MagicMock()
        mock_driver.async_create_bgp_peer_group = AsyncMock(return_value=True)
        mock_switch_cls.return_value = mock_driver

        params = {
            "hostname": "bag002.snc1",
            "peer_group_name": "PEERGROUP_BAG_STSW_V6",
        }
        await self.task.run(params)

        mock_switch_cls.assert_called_once_with("bag002.snc1", logger=self.logger)
        mock_driver.async_create_bgp_peer_group.assert_called_once_with(
            peer_group_name="PEERGROUP_BAG_STSW_V6",
        )

    @patch(ARISTA_SWITCH_PATH)
    async def test_create_peer_group_all_params(self, mock_switch_cls) -> None:
        mock_driver = MagicMock()
        mock_driver.async_create_bgp_peer_group = AsyncMock(return_value=True)
        mock_switch_cls.return_value = mock_driver

        params = {
            "hostname": "bag002.snc1",
            "peer_group_name": "PEERGROUP_BAG_STSW_V6",
            "remote_as": 65000,
            "description": "BGP peering to STSW IPv6",
            "route_map_in": "PROPAGATE_BAG_STSW_IN",
            "route_map_out": "PROPAGATE_BAG_STSW_OUT",
            "next_hop_self": True,
            "graceful_restart_helper": True,
            "timers_keepalive": 10,
            "timers_holdtime": 30,
            "ipv4_unicast": False,
            "ipv6_unicast": True,
            "maximum_routes": 90000,
            "maximum_routes_warning_limit": 0,
            "maximum_routes_warning_only": True,
            "send_community": True,
            "out_delay": 7,
        }
        await self.task.run(params)

        mock_driver.async_create_bgp_peer_group.assert_called_once_with(
            peer_group_name="PEERGROUP_BAG_STSW_V6",
            remote_as=65000,
            description="BGP peering to STSW IPv6",
            route_map_in="PROPAGATE_BAG_STSW_IN",
            route_map_out="PROPAGATE_BAG_STSW_OUT",
            next_hop_self=True,
            graceful_restart_helper=True,
            timers_keepalive=10,
            timers_holdtime=30,
            ipv4_unicast=False,
            ipv6_unicast=True,
            maximum_routes=90000,
            maximum_routes_warning_limit=0,
            maximum_routes_warning_only=True,
            send_community=True,
            out_delay=7,
        )

    @patch(ARISTA_SWITCH_PATH)
    async def test_remove_peer_group(self, mock_switch_cls) -> None:
        mock_driver = MagicMock()
        mock_driver.async_remove_bgp_peer_group = AsyncMock(return_value=True)
        mock_switch_cls.return_value = mock_driver

        params = {
            "hostname": "bag002.snc1",
            "peer_group_name": "PEERGROUP_BAG_STSW_V6",
            "register": False,
        }
        await self.task.run(params)

        mock_switch_cls.assert_called_once_with("bag002.snc1", logger=self.logger)
        mock_driver.async_remove_bgp_peer_group.assert_called_once_with(
            "PEERGROUP_BAG_STSW_V6",
        )
        mock_driver.async_create_bgp_peer_group.assert_not_called()

    @patch(ARISTA_SWITCH_PATH)
    async def test_register_true_does_not_call_remove(self, mock_switch_cls) -> None:
        mock_driver = MagicMock()
        mock_driver.async_create_bgp_peer_group = AsyncMock(return_value=True)
        mock_switch_cls.return_value = mock_driver

        params = {
            "hostname": "bag002.snc1",
            "peer_group_name": "PEERGROUP_BAG_STSW_V6",
            "register": True,
        }
        await self.task.run(params)

        mock_driver.async_create_bgp_peer_group.assert_called_once()
        mock_driver.async_remove_bgp_peer_group.assert_not_called()

    @patch(ARISTA_SWITCH_PATH)
    async def test_optional_params_not_passed_when_absent(
        self, mock_switch_cls
    ) -> None:
        mock_driver = MagicMock()
        mock_driver.async_create_bgp_peer_group = AsyncMock(return_value=True)
        mock_switch_cls.return_value = mock_driver

        params = {
            "hostname": "bag002.snc1",
            "peer_group_name": "PEERGROUP_EBGP_V4",
            "next_hop_self": True,
        }
        await self.task.run(params)

        call_kwargs = mock_driver.async_create_bgp_peer_group.call_args[1]
        self.assertEqual(call_kwargs["peer_group_name"], "PEERGROUP_EBGP_V4")
        self.assertTrue(call_kwargs["next_hop_self"])
        self.assertNotIn("remote_as", call_kwargs)
        self.assertNotIn("description", call_kwargs)
        self.assertNotIn("route_map_in", call_kwargs)
        self.assertNotIn("timers_holdtime", call_kwargs)


class AddEosBgpPrefixListToPeerGroupTest(unittest.IsolatedAsyncioTestCase):
    """Unit tests for AddEosBgpPrefixListToPeerGroup task."""

    def setUp(self) -> None:
        self.logger = MagicMock()
        self.task = AddEosBgpPrefixListToPeerGroup(
            hostname="bag002.snc1",
            logger=self.logger,
        )

    @patch(ARISTA_SWITCH_PATH)
    async def test_add_ipv6_prefix_list(self, mock_switch_cls) -> None:
        mock_driver = MagicMock()
        mock_driver.async_add_bgp_prefix_list_to_peer_group = AsyncMock(
            return_value=True
        )
        mock_switch_cls.return_value = mock_driver

        params = {
            "hostname": "bag002.snc1",
            "prefix_list_name": "ALLOW_V6_PREFIXES",
            "prefix": "5000::/16",
            "peer_group_name": "PEERGROUP_BAG_STSW_V6",
            "direction": "in",
            "prefix_length": 128,
        }
        await self.task.run(params)

        mock_driver.async_add_bgp_prefix_list_to_peer_group.assert_called_once_with(
            prefix_list_name="ALLOW_V6_PREFIXES",
            prefix="5000::/16",
            peer_group_name="PEERGROUP_BAG_STSW_V6",
            direction="in",
            prefix_length=128,
            seq=None,
        )

    @patch(ARISTA_SWITCH_PATH)
    async def test_add_with_seq_number(self, mock_switch_cls) -> None:
        mock_driver = MagicMock()
        mock_driver.async_add_bgp_prefix_list_to_peer_group = AsyncMock(
            return_value=True
        )
        mock_switch_cls.return_value = mock_driver

        params = {
            "hostname": "bag002.snc1",
            "prefix_list_name": "ALLOW_V6_PREFIXES",
            "prefix": "6000::/16",
            "peer_group_name": "PEERGROUP_BAG_STSW_V6",
            "direction": "out",
            "prefix_length": 64,
            "seq": 20,
        }
        await self.task.run(params)

        mock_driver.async_add_bgp_prefix_list_to_peer_group.assert_called_once_with(
            prefix_list_name="ALLOW_V6_PREFIXES",
            prefix="6000::/16",
            peer_group_name="PEERGROUP_BAG_STSW_V6",
            direction="out",
            prefix_length=64,
            seq=20,
        )

    @patch(ARISTA_SWITCH_PATH)
    async def test_add_defaults(self, mock_switch_cls) -> None:
        mock_driver = MagicMock()
        mock_driver.async_add_bgp_prefix_list_to_peer_group = AsyncMock(
            return_value=True
        )
        mock_switch_cls.return_value = mock_driver

        params = {
            "hostname": "bag002.snc1",
            "prefix_list_name": "ALLOW_PREFIXES",
            "prefix": "5000::/16",
            "peer_group_name": "PEERGROUP_BAG_STSW_V6",
        }
        await self.task.run(params)

        call_kwargs = mock_driver.async_add_bgp_prefix_list_to_peer_group.call_args[1]
        self.assertEqual(call_kwargs["direction"], "in")
        self.assertIsNone(call_kwargs["prefix_length"])
        self.assertIsNone(call_kwargs["seq"])

    @patch(ARISTA_SWITCH_PATH)
    async def test_remove_prefix_list_with_prefix(self, mock_switch_cls) -> None:
        mock_driver = MagicMock()
        mock_driver.async_remove_bgp_prefix_list_from_peer_group = AsyncMock(
            return_value=True
        )
        mock_switch_cls.return_value = mock_driver

        params = {
            "hostname": "bag002.snc1",
            "prefix_list_name": "ALLOW_V6_PREFIXES",
            "peer_group_name": "PEERGROUP_BAG_STSW_V6",
            "prefix": "5000::/16",
            "direction": "in",
            "register": False,
        }
        await self.task.run(params)

        mock_driver.async_remove_bgp_prefix_list_from_peer_group.assert_called_once_with(
            prefix_list_name="ALLOW_V6_PREFIXES",
            peer_group_name="PEERGROUP_BAG_STSW_V6",
            direction="in",
            is_ipv6=True,
        )
        mock_driver.async_add_bgp_prefix_list_to_peer_group.assert_not_called()

    @patch(ARISTA_SWITCH_PATH)
    async def test_remove_ipv4_prefix_list(self, mock_switch_cls) -> None:
        mock_driver = MagicMock()
        mock_driver.async_remove_bgp_prefix_list_from_peer_group = AsyncMock(
            return_value=True
        )
        mock_switch_cls.return_value = mock_driver

        params = {
            "hostname": "bag002.snc1",
            "prefix_list_name": "ALLOW_V4_PREFIXES",
            "peer_group_name": "PEERGROUP_BAG_STSW_V4",
            "prefix": "10.0.0.0/8",
            "direction": "out",
            "register": False,
        }
        await self.task.run(params)

        mock_driver.async_remove_bgp_prefix_list_from_peer_group.assert_called_once_with(
            prefix_list_name="ALLOW_V4_PREFIXES",
            peer_group_name="PEERGROUP_BAG_STSW_V4",
            direction="out",
            is_ipv6=False,
        )

    @patch(ARISTA_SWITCH_PATH)
    async def test_remove_with_is_ipv6_flag(self, mock_switch_cls) -> None:
        mock_driver = MagicMock()
        mock_driver.async_remove_bgp_prefix_list_from_peer_group = AsyncMock(
            return_value=True
        )
        mock_switch_cls.return_value = mock_driver

        params = {
            "hostname": "bag002.snc1",
            "prefix_list_name": "ALLOW_V4_PREFIXES",
            "peer_group_name": "PEERGROUP_BAG_STSW_V4",
            "is_ipv6": False,
            "register": False,
        }
        await self.task.run(params)

        mock_driver.async_remove_bgp_prefix_list_from_peer_group.assert_called_once_with(
            prefix_list_name="ALLOW_V4_PREFIXES",
            peer_group_name="PEERGROUP_BAG_STSW_V4",
            direction="in",
            is_ipv6=False,
        )

    @patch(ARISTA_SWITCH_PATH)
    async def test_add_to_multiple_peer_groups(self, mock_switch_cls) -> None:
        mock_driver = MagicMock()
        mock_driver.async_add_bgp_prefix_list_to_peer_group = AsyncMock(
            return_value=True
        )
        mock_switch_cls.return_value = mock_driver

        peer_groups = ["PEERGROUP_BAG_STSW_V6", "PEERGROUP_BAG_CBAG_V6"]
        params = {
            "hostname": "bag002.snc1",
            "prefix_list_name": "ALLOW_V6_PREFIXES",
            "prefix": "5000::/16",
            "peer_group_name": peer_groups,
            "direction": "in",
        }
        await self.task.run(params)

        mock_driver.async_add_bgp_prefix_list_to_peer_group.assert_called_once_with(
            prefix_list_name="ALLOW_V6_PREFIXES",
            prefix="5000::/16",
            peer_group_name=peer_groups,
            direction="in",
            prefix_length=None,
            seq=None,
        )

    @patch(ARISTA_SWITCH_PATH)
    async def test_remove_from_multiple_peer_groups(self, mock_switch_cls) -> None:
        mock_driver = MagicMock()
        mock_driver.async_remove_bgp_prefix_list_from_peer_group = AsyncMock(
            return_value=True
        )
        mock_switch_cls.return_value = mock_driver

        peer_groups = ["PEERGROUP_BAG_STSW_V6", "PEERGROUP_BAG_CBAG_V6"]
        params = {
            "hostname": "bag002.snc1",
            "prefix_list_name": "ALLOW_V6_PREFIXES",
            "peer_group_name": peer_groups,
            "prefix": "5000::/16",
            "direction": "in",
            "register": False,
        }
        await self.task.run(params)

        mock_driver.async_remove_bgp_prefix_list_from_peer_group.assert_called_once_with(
            prefix_list_name="ALLOW_V6_PREFIXES",
            peer_group_name=peer_groups,
            direction="in",
            is_ipv6=True,
        )
        mock_driver.async_add_bgp_prefix_list_to_peer_group.assert_not_called()


class BackupRunningConfigTest(unittest.IsolatedAsyncioTestCase):
    """Unit tests for BackupRunningConfigTask."""

    def setUp(self) -> None:
        self.logger = MagicMock()
        self.task = BackupRunningConfigTask(
            hostname="bag002.snc1",
            logger=self.logger,
        )

    @patch(ARISTA_SWITCH_PATH)
    @patch(f"{ARISTA_UTILS_PATH}.save_running_config", new_callable=AsyncMock)
    async def test_backup_with_backup_file(self, mock_save, mock_switch_cls) -> None:
        mock_driver = MagicMock()
        mock_switch_cls.return_value = mock_driver
        mock_save.return_value = "flash:taac_backup"

        params = {
            "hostname": "bag002.snc1",
            "backup_file": "taac_backup",
        }
        await self.task.run(params)

        mock_switch_cls.assert_called_once_with("bag002.snc1", logger=self.logger)
        mock_save.assert_called_once_with(
            mock_driver, backup_name="taac_backup", logger_instance=self.logger
        )

    @patch(ARISTA_SWITCH_PATH)
    @patch(f"{ARISTA_UTILS_PATH}.save_running_config", new_callable=AsyncMock)
    async def test_backup_without_backup_file(self, mock_save, mock_switch_cls) -> None:
        mock_driver = MagicMock()
        mock_switch_cls.return_value = mock_driver
        mock_save.return_value = "flash:taac_backup_20251114_162530"

        params = {"hostname": "bag002.snc1"}
        await self.task.run(params)

        mock_save.assert_called_once_with(
            mock_driver, backup_name=None, logger_instance=self.logger
        )


class RestoreRunningConfigTest(unittest.IsolatedAsyncioTestCase):
    """Unit tests for RestoreRunningConfigTask."""

    def setUp(self) -> None:
        self.logger = MagicMock()
        self.task = RestoreRunningConfigTask(
            hostname="bag002.snc1",
            logger=self.logger,
        )

    @patch(ARISTA_SWITCH_PATH)
    @patch(f"{ARISTA_UTILS_PATH}.restore_running_config", new_callable=AsyncMock)
    async def test_restore(self, mock_restore, mock_switch_cls) -> None:
        mock_driver = MagicMock()
        mock_switch_cls.return_value = mock_driver

        params = {
            "hostname": "bag002.snc1",
            "backup_file": "flash:taac_backup_20251114_162530",
        }
        await self.task.run(params)

        mock_switch_cls.assert_called_once_with("bag002.snc1", logger=self.logger)
        mock_restore.assert_called_once_with(
            mock_driver,
            backup_file="flash:taac_backup_20251114_162530",
            logger_instance=self.logger,
        )

    @patch(ARISTA_SWITCH_PATH)
    async def test_restore_without_backup_file_raises(self, mock_switch_cls) -> None:
        mock_switch_cls.return_value = MagicMock()

        params = {"hostname": "bag002.snc1"}
        with self.assertRaises(ValueError):
            await self.task.run(params)
