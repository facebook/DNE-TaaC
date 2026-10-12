# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import base64
import contextlib
import json
import math
import typing as t
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, MagicMock, patch

import later.unittest
from taac.task_definitions import create_coop_apply_patchers_task
from neteng.test_infra.dne.taac.tasks import all as tasks_all
from taac.tasks.all import (
    AristaCreateFileFromConfig,
    AristaDaemonControlTask,
    ConfigureParallelBgpPeers,
    CoopApplyPatchersTask,
    CoopApplyPatchersV2,
    CoopRegisterPatcherTask,
    CoopUnregisterPatchersTask,
    IxiaStopTrafficAndWaitTask,
    IxiaSyncRawSourceMacsTask,
    RunCommandsOnShell,
    ScpFile,
    ValidateBgpcppUpdateGroupState,
)
from taac.utils import oss_taac_lib_utils


ALL_PATH = "neteng.test_infra.dne.taac.tasks.all"
RETRY_UTILS_PATH = "neteng.test_infra.dne.taac.utils.oss_taac_lib_utils"


class AristaDaemonControlTaskTest(later.unittest.TestCase):
    async def test_enable_is_noop_when_daemon_is_already_healthy(self) -> None:
        driver = MagicMock()
        driver.async_execute_show_or_configure_cmd_on_shell = AsyncMock()
        task = AristaDaemonControlTask(logger=MagicMock())
        task._check_daemon_running_status = AsyncMock(
            return_value={
                "daemon_exists": True,
                "is_running": True,
                "daemon_config": (
                    "daemon Bgp",
                    "exec /usr/sbin/run_bgpcpp.sh",
                    "no shutdown",
                ),
            }
        )

        await task._enable_daemon(driver, "Bgp", "/usr/sbin/run_bgpcpp.sh")

        driver.async_execute_show_or_configure_cmd_on_shell.assert_not_awaited()

    async def test_enable_repairs_mismatched_exec_configuration(self) -> None:
        driver = MagicMock()
        driver.async_execute_show_or_configure_cmd_on_shell = AsyncMock()
        task = AristaDaemonControlTask(logger=MagicMock())
        task._check_daemon_running_status = AsyncMock(
            side_effect=[
                {
                    "daemon_exists": True,
                    "is_running": True,
                    "daemon_config": (
                        "daemon Bgp",
                        "exec /usr/sbin/old_bgpcpp.sh",
                        "no shutdown",
                    ),
                },
                {
                    "daemon_exists": True,
                    "is_running": True,
                    "daemon_config": (
                        "daemon Bgp",
                        "exec /usr/sbin/run_bgpcpp.sh",
                        "no shutdown",
                    ),
                },
            ]
        )

        with patch(f"{ALL_PATH}.asyncio.sleep", new_callable=AsyncMock):
            await task._enable_daemon(driver, "Bgp", "/usr/sbin/run_bgpcpp.sh")

        driver.async_execute_show_or_configure_cmd_on_shell.assert_awaited_once_with(
            "daemon Bgp\nexec /usr/sbin/run_bgpcpp.sh\nno shutdown",
            configure=True,
        )


class ScpFileTest(later.unittest.TestCase):
    async def test_writes_through_os_aware_driver(self) -> None:
        driver = MagicMock()
        driver.async_write_file_on_device = AsyncMock()
        task = ScpFile(logger=MagicMock())

        with patch(
            f"{ALL_PATH}.async_get_device_driver",
            new_callable=AsyncMock,
            return_value=driver,
        ):
            await task.run(
                {
                    "hostname": "rsw.example",
                    "remote_path": "/etc/example/config",
                    "file_content": "payload",
                }
            )

        driver.async_write_file_on_device.assert_awaited_once_with(
            "payload",
            "/etc/example/config",
        )

    async def test_preserves_scp_fallback_for_non_fboss_drivers(self) -> None:
        driver = SimpleNamespace()
        client = MagicMock()
        client_context = MagicMock()
        client_context.__enter__.return_value = client
        task = ScpFile(logger=MagicMock())

        with (
            patch(
                f"{ALL_PATH}.async_get_device_driver",
                new_callable=AsyncMock,
                return_value=driver,
            ),
            patch(
                f"{ALL_PATH}.ParamikoClient",
                return_value=client_context,
            ) as paramiko_client,
        ):
            await task.run(
                {
                    "hostname": "eos.example",
                    "remote_path": "/mnt/flash/config",
                    "file_content": "payload",
                }
            )

        paramiko_client.assert_called_once_with("eos.example")
        client.scp.assert_called_once()
        self.assertEqual(
            "/mnt/flash/config",
            client.scp.call_args.kwargs["remote_path"],
        )


class CoopApplyPatchersTaskTest(later.unittest.TestCase):
    async def test_singular_agent_config_does_not_restart_bgpd(self) -> None:
        driver = MagicMock()
        driver.async_agent_config_reload = AsyncMock()
        driver.async_restart_service = AsyncMock()
        task = CoopApplyPatchersTask(logger=MagicMock())

        with patch(
            f"{ALL_PATH}.async_get_device_driver",
            new_callable=AsyncMock,
            return_value=driver,
        ):
            await task.run({"hostnames": ["fsw.example"], "config_name": "agent"})

        driver.async_agent_config_reload.assert_awaited_once_with()
        driver.async_restart_service.assert_not_awaited()

    async def test_default_task_reloads_agent_and_restarts_bgpd(self) -> None:
        driver = MagicMock()
        driver.async_agent_config_reload = AsyncMock()
        driver.async_restart_service = AsyncMock()
        task = CoopApplyPatchersTask(logger=MagicMock())
        json_params = create_coop_apply_patchers_task(
            ["fsw.example"]
        ).params.json_params
        if json_params is None:
            self.fail("create_coop_apply_patchers_task produced no json_params")
        params = json.loads(json_params)

        with patch(
            f"{ALL_PATH}.async_get_device_driver",
            new_callable=AsyncMock,
            return_value=driver,
        ):
            await task.run(params)

        driver.async_agent_config_reload.assert_awaited_once_with()
        driver.async_restart_service.assert_awaited_once()


@contextlib.contextmanager
def _taac_env(taac_oss: bool, meta_internal: bool):
    """The tasks split internal from OSS on their own TAAC_OSS and pick the pure-OSS
    patcher through the shared gate, so drive both."""
    with (
        patch(f"{ALL_PATH}.TAAC_OSS", taac_oss),
        patch.object(oss_taac_lib_utils, "TAAC_OSS", taac_oss),
        patch.object(oss_taac_lib_utils, "TAAC_OSS_META_INTERNAL", meta_internal),
    ):
        yield


class CoopUnregisterPatchersTaskTest(later.unittest.TestCase):
    """A config with nothing to unregister must not end the loop. fsw is drainable,
    so the default configs are agent, bgpcpp, bgpcpp_drain and bgpcpp_softdrain;
    with `break`, nothing after the empty agent config was ever unregistered."""

    async def _run_teardown(
        self, taac_oss: bool, owner: t.Optional[str]
    ) -> t.Tuple[MagicMock, t.Dict[str, list]]:
        patcher = SimpleNamespace(name="p", owner=owner)
        registered = {
            "agent": [],
            "bgpcpp": [patcher],
            "bgpcpp_drain": [],
            "bgpcpp_softdrain": [patcher],
        }

        async def list_patchers(config_name: str) -> list:
            return list(registered[config_name])

        async def unregister(patcher_name: str, config_name: str, **kwargs) -> None:
            registered[config_name] = [
                p for p in registered[config_name] if p.name != patcher_name
            ]

        driver = MagicMock()
        driver.async_coop_list_patchers = AsyncMock(side_effect=list_patchers)
        driver.async_coop_unregister_patchers = AsyncMock(side_effect=unregister)
        driver.async_restore_patched_configs = AsyncMock()
        with (
            _taac_env(taac_oss=taac_oss, meta_internal=False),
            patch(
                f"{ALL_PATH}.async_get_device_driver",
                new_callable=AsyncMock,
                return_value=driver,
            ),
        ):
            await CoopUnregisterPatchersTask(logger=MagicMock()).run(
                {"hostname": "fsw.example"}
            )
        return driver, registered

    def _assert_every_config_cleaned(
        self, driver: MagicMock, registered: t.Dict[str, list]
    ) -> None:
        self.assertEqual(
            [
                call("p", "bgpcpp", auto_remediate_failure=True),
                call("p", "bgpcpp_softdrain", auto_remediate_failure=True),
            ],
            driver.async_coop_unregister_patchers.await_args_list,
        )
        self.assertEqual(
            {"agent": [], "bgpcpp": [], "bgpcpp_drain": [], "bgpcpp_softdrain": []},
            registered,
        )

    def test_default_configs_for_a_drainable_host(self) -> None:
        self.assertEqual(
            ["agent", "bgpcpp", "bgpcpp_drain", "bgpcpp_softdrain"],
            tasks_all.get_default_configs("fsw.example"),
        )

    async def test_internal_empty_config_does_not_stop_the_rest(self) -> None:
        # COOP stamps the owner; OSS patchers carry none.
        driver, registered = await self._run_teardown(
            taac_oss=False, owner=tasks_all.DNE_TEST_REGRESSION_NAME
        )
        self._assert_every_config_cleaned(driver, registered)
        driver.async_restore_patched_configs.assert_not_awaited()

    async def test_pure_oss_empty_config_does_not_stop_the_rest(self) -> None:
        driver, registered = await self._run_teardown(taac_oss=True, owner=None)
        self._assert_every_config_cleaned(driver, registered)
        driver.async_restore_patched_configs.assert_awaited_once_with()


class CoopPatcherTaskGateTest(later.unittest.TestCase):
    """The OSS patcher is pure-OSS only; the TAAC_OSS_META_INTERNAL container skips
    the COOP patcher tasks, as every OSS run did before the OSS patcher."""

    async def test_container_skips_every_coop_patcher_task(self) -> None:
        runs = [
            (
                CoopRegisterPatcherTask,
                {
                    "hostname": "fsw.example",
                    "config_name": "bgpcpp",
                    "patcher_name": "p",
                    "py_func_name": "remove_bgp_peers",
                    "patcher_args": "{}",
                },
            ),
            (CoopUnregisterPatchersTask, {"hostname": "fsw.example"}),
            (CoopApplyPatchersTask, {"hostnames": ["fsw.example"]}),
            (
                CoopApplyPatchersV2,
                {"hostnames": ["fsw.example"], "apply_patcher_method": 2},
            ),
        ]
        with (
            _taac_env(taac_oss=True, meta_internal=True),
            patch(
                f"{ALL_PATH}.async_get_device_driver", new_callable=AsyncMock
            ) as get_driver,
        ):
            for task_cls, params in runs:
                await task_cls(logger=MagicMock()).run(params)

        get_driver.assert_not_awaited()

    async def test_pure_oss_apply_uses_the_oss_patcher(self) -> None:
        driver = MagicMock()
        driver.async_apply_patchers = AsyncMock()
        with (
            _taac_env(taac_oss=True, meta_internal=False),
            patch(
                f"{ALL_PATH}.async_get_device_driver",
                new_callable=AsyncMock,
                return_value=driver,
            ),
        ):
            await CoopApplyPatchersTask(logger=MagicMock()).run(
                {"hostnames": ["fsw.example"], "do_warmboot": True}
            )

        driver.async_apply_patchers.assert_awaited_once_with(
            tasks_all.taac_types.ApplyPatcherMethod.AGENT_WARMBOOT, coldboot=False
        )

    async def test_pure_oss_teardown_restores_baselines(self) -> None:
        driver = MagicMock()
        driver.async_coop_list_patchers = AsyncMock(return_value=[])
        driver.async_restore_patched_configs = AsyncMock()
        driver.async_apply_patchers = AsyncMock()
        with (
            _taac_env(taac_oss=True, meta_internal=False),
            patch(
                f"{ALL_PATH}.async_get_device_driver",
                new_callable=AsyncMock,
                return_value=driver,
            ),
        ):
            await CoopUnregisterPatchersTask(logger=MagicMock()).run(
                {"hostname": "fsw.example"}
            )

        driver.async_restore_patched_configs.assert_awaited_once_with()
        driver.async_apply_patchers.assert_not_awaited()

    async def test_pure_oss_partial_unregister_applies(self) -> None:
        registered = {"bgpcpp": [SimpleNamespace(name="drop", owner=None)]}
        registered["bgpcpp"].append(SimpleNamespace(name="keep", owner=None))

        async def list_patchers(config_name: str) -> list:
            return list(registered.get(config_name, []))

        async def unregister(patcher_name: str, config_name: str, **kwargs) -> None:
            registered[config_name] = [
                p for p in registered[config_name] if p.name != patcher_name
            ]

        driver = MagicMock()
        driver.async_coop_list_patchers = AsyncMock(side_effect=list_patchers)
        driver.async_coop_unregister_patchers = AsyncMock(side_effect=unregister)
        driver.async_restore_patched_configs = AsyncMock()
        driver.async_apply_patchers = AsyncMock()
        with (
            _taac_env(taac_oss=True, meta_internal=False),
            patch(
                f"{ALL_PATH}.async_get_device_driver",
                new_callable=AsyncMock,
                return_value=driver,
            ),
        ):
            await CoopUnregisterPatchersTask(logger=MagicMock()).run(
                {"hostname": "fsw.example", "regex": "drop"}
            )

        self.assertEqual(["keep"], [p.name for p in registered["bgpcpp"]])
        driver.async_apply_patchers.assert_awaited_once_with()
        driver.async_restore_patched_configs.assert_not_awaited()

    async def test_internal_unregister_never_restores_oss_baselines(self) -> None:
        driver = MagicMock()
        driver.async_coop_list_patchers = AsyncMock(return_value=[])
        driver.async_restore_patched_configs = AsyncMock()
        driver.async_apply_patchers = AsyncMock()
        with (
            _taac_env(taac_oss=False, meta_internal=False),
            patch(
                f"{ALL_PATH}.async_get_device_driver",
                new_callable=AsyncMock,
                return_value=driver,
            ),
        ):
            await CoopUnregisterPatchersTask(logger=MagicMock()).run(
                {"hostname": "fsw.example"}
            )

        driver.async_coop_list_patchers.assert_awaited()
        driver.async_restore_patched_configs.assert_not_awaited()
        driver.async_apply_patchers.assert_not_awaited()


class ConfigureParallelBgpPeersTest(later.unittest.TestCase):
    async def test_interface_only_config_does_not_register_bgp_patcher(self) -> None:
        driver = MagicMock()
        driver.async_get_all_port_info = AsyncMock(
            return_value={10: SimpleNamespace(name="eth2/1/1", portId=10, vlans=[3000])}
        )
        driver.async_get_vlan_addresses = AsyncMock(return_value=[])
        driver.async_register_python_patcher = AsyncMock()
        task = ConfigureParallelBgpPeers(logger=MagicMock())

        with patch(
            f"{ALL_PATH}.async_get_device_driver",
            new_callable=AsyncMock,
            return_value=driver,
        ):
            await task.run(
                {
                    "hostname": "fsw.example",
                    "config_json": json.dumps(
                        {
                            "eth2/1/1": [
                                {
                                    "starting_ip": "2401:db00:abcd::1",
                                    "increment_ip": "::0",
                                    "prefix_length": 80,
                                    "description": "NDP stressor RIF",
                                    "peer_group_name": "UNUSED",
                                    "num_sessions": 1,
                                    "remote_as_4_byte": 65000,
                                    "gateway_starting_ip": "2401:db00:abcd::2",
                                    "gateway_increment_ip": "::0",
                                    "config_only_interface_ip": True,
                                }
                            ]
                        }
                    ),
                }
            )

        self.assertEqual(driver.async_register_python_patcher.await_count, 1)
        patcher_call = driver.async_register_python_patcher.await_args
        self.assertIsNotNone(patcher_call)
        if patcher_call is None:
            self.fail("async_register_python_patcher was not awaited")
        self.assertEqual(
            patcher_call.kwargs["config_name"],
            "agent",
        )

    async def test_default_behavior_uses_live_vlan_and_retains_addresses(self) -> None:
        driver = MagicMock()
        driver.async_get_all_port_info = AsyncMock(
            return_value={10: SimpleNamespace(name="eth2/1/1", portId=10, vlans=[3000])}
        )
        driver.async_get_vlan_addresses = AsyncMock(
            return_value=["2401:db00:abcd::a/64"]
        )
        driver.async_register_python_patcher = AsyncMock()
        task = ConfigureParallelBgpPeers(logger=MagicMock())

        with patch(
            f"{ALL_PATH}.async_get_device_driver",
            new_callable=AsyncMock,
            return_value=driver,
        ):
            await task.run(
                {
                    "hostname": "fsw.example",
                    "config_json": json.dumps(
                        {
                            "eth2/1/1": [
                                {
                                    "starting_ip": "2401:db00:abcd::10",
                                    "increment_ip": "::2",
                                    "prefix_length": 127,
                                    "description": "default",
                                    "peer_group_name": "TEST",
                                    "num_sessions": 1,
                                    "remote_as_4_byte": 65000,
                                    "gateway_starting_ip": "2401:db00:abcd::11",
                                    "gateway_increment_ip": "::2",
                                }
                            ]
                        }
                    ),
                }
            )

        driver.async_get_vlan_addresses.assert_awaited_once_with(3000, global_only=True)
        vlan_call = next(
            call
            for call in driver.async_register_python_patcher.await_args_list
            if call.kwargs["config_name"] == "agent"
        )
        vlan_config = json.loads(vlan_call.kwargs["patcher_args"]["vlan3000"])
        self.assertEqual(vlan_config["vlan_id"], 3000)
        self.assertCountEqual(
            vlan_config["ip_addresses"],
            ["2401:db00:abcd::a/64", "2401:db00:abcd::10/127"],
        )

    async def test_explicit_vlan_split_replaces_existing_vlan_addresses(self) -> None:
        driver = MagicMock()
        driver.async_get_all_port_info = AsyncMock(
            return_value={
                129: SimpleNamespace(name="eth1/17/1", portId=129, vlans=[2000]),
                137: SimpleNamespace(name="eth1/18/1", portId=137, vlans=[2000]),
            }
        )
        driver.async_get_vlan_addresses = AsyncMock(
            return_value=["2401:db00:501c::a/64"]
        )
        driver.async_register_python_patcher = AsyncMock()
        task = ConfigureParallelBgpPeers(logger=MagicMock())

        with patch(
            f"{ALL_PATH}.async_get_device_driver",
            new_callable=AsyncMock,
            return_value=driver,
        ):
            await task.run(
                {
                    "hostname": "rsw001.p001.f01.qzd1",
                    "shared_vlan_id": 2000,
                    "configure_vlans_patcher_name": "configure_vlans_reboot_test",
                    "add_bgp_peers_patcher_name": "add_bgp_peers_reboot_test",
                    "config_json": json.dumps(
                        {
                            "eth1/17/1": [
                                {
                                    "starting_ip": "2401:db00:501c::10",
                                    "increment_ip": "::2",
                                    "prefix_length": 127,
                                    "description": "primary",
                                    "peer_group_name": "TAAC_REBOOT_IXIA_V6",
                                    "num_sessions": 1,
                                    "remote_as_4_byte": 65000,
                                    "gateway_starting_ip": "2401:db00:501c::11",
                                    "gateway_increment_ip": "::2",
                                    "vlan_id": 2000,
                                    "retain_existing_vlan_addresses": False,
                                }
                            ],
                            "eth1/18/1": [
                                {
                                    "starting_ip": "2401:db00:e50d:11:18::10",
                                    "increment_ip": "::2",
                                    "prefix_length": 127,
                                    "description": "secondary",
                                    "peer_group_name": "TAAC_REBOOT_IXIA_V6",
                                    "num_sessions": 1,
                                    "remote_as_4_byte": 6016,
                                    "gateway_starting_ip": "2401:db00:e50d:11:18::11",
                                    "gateway_increment_ip": "::2",
                                    "vlan_id": 4016,
                                    "retain_existing_vlan_addresses": False,
                                }
                            ],
                        }
                    ),
                }
            )

        vlan_call = next(
            call
            for call in driver.async_register_python_patcher.await_args_list
            if call.kwargs["config_name"] == "agent"
        )
        vlan_args = vlan_call.kwargs["patcher_args"]
        primary = json.loads(vlan_args["vlan2000"])
        secondary = json.loads(vlan_args["vlan4016"])
        # Only the OSS patcher needs telling; COOP replaces addresses anyway.
        self.assertNotIn("retain_existing_vlan_addresses", primary)
        self.assertEqual(primary["ports"], [129])
        self.assertEqual(primary["ip_addresses"], ["2401:db00:501c::10/127"])
        self.assertEqual(secondary["ports"], [137])
        self.assertEqual(
            secondary["ip_addresses"],
            ["2401:db00:e50d:11:18::10/127"],
        )
        driver.async_get_vlan_addresses.assert_not_awaited()

        bgp_call = next(
            call
            for call in driver.async_register_python_patcher.await_args_list
            if call.kwargs["config_name"] == "bgpcpp"
        )
        peer_configs = json.loads(bgp_call.kwargs["patcher_args"]["peer_configs"])
        self.assertEqual(
            [peer["remote_as_4_byte"] for peer in peer_configs],
            ["65000", "6016"],
        )

    async def test_oss_split_tells_the_patcher_to_replace_addresses(self) -> None:
        driver = MagicMock()
        driver.async_get_all_port_info = AsyncMock(
            return_value={
                129: SimpleNamespace(name="eth1/17/1", portId=129, vlans=[2000]),
            }
        )
        driver.async_register_python_patcher = AsyncMock()
        config = {
            "eth1/17/1": [
                {
                    "starting_ip": "2401:db00:501c::10",
                    "increment_ip": "::2",
                    "prefix_length": 127,
                    "description": "primary",
                    "peer_group_name": "TAAC_REBOOT_IXIA_V6",
                    "num_sessions": 1,
                    "remote_as_4_byte": 65000,
                    "gateway_starting_ip": "2401:db00:501c::11",
                    "gateway_increment_ip": "::2",
                    "vlan_id": 2000,
                    "retain_existing_vlan_addresses": False,
                }
            ]
        }
        with (
            patch(
                f"{ALL_PATH}.async_get_device_driver",
                new_callable=AsyncMock,
                return_value=driver,
            ),
            patch(f"{ALL_PATH}.oss_config_patcher_enabled", return_value=True),
        ):
            await ConfigureParallelBgpPeers(logger=MagicMock()).run(
                {
                    "hostname": "rsw001.p001.f01.qzd1",
                    "config_json": json.dumps(config),
                }
            )

        vlan_call = next(
            call
            for call in driver.async_register_python_patcher.await_args_list
            if call.kwargs["config_name"] == "agent"
        )
        vlan_config = json.loads(vlan_call.kwargs["patcher_args"]["vlan2000"])
        self.assertIs(False, vlan_config["retain_existing_vlan_addresses"])

    async def test_shared_vlan_split_rejects_non_lowest_primary(self) -> None:
        driver = MagicMock()
        driver.async_get_all_port_info = AsyncMock(
            return_value={
                129: SimpleNamespace(name="eth1/17/1", portId=129, vlans=[2000]),
                137: SimpleNamespace(name="eth1/18/1", portId=137, vlans=[2000]),
            }
        )
        task = ConfigureParallelBgpPeers(logger=MagicMock())
        config = {
            interface: [
                {
                    "starting_ip": f"2401:db00:501c::{host}",
                    "increment_ip": "::2",
                    "prefix_length": 127,
                    "description": "bad split",
                    "peer_group_name": "TEST",
                    "num_sessions": 1,
                    "remote_as_4_byte": 65000,
                    "gateway_starting_ip": f"2401:db00:501c::{host + 1}",
                    "gateway_increment_ip": "::2",
                    "vlan_id": vlan_id,
                    "retain_existing_vlan_addresses": False,
                }
            ]
            for interface, host, vlan_id in (
                ("eth1/17/1", 10, 4016),
                ("eth1/18/1", 12, 2000),
            )
        }

        with (
            patch(
                f"{ALL_PATH}.async_get_device_driver",
                new_callable=AsyncMock,
                return_value=driver,
            ),
            self.assertRaisesRegex(ValueError, "lowest IXIA interface eth1/17/1"),
        ):
            await task.run(
                {
                    "hostname": "rsw001.p001.f01.qzd1",
                    "shared_vlan_id": 2000,
                    "config_json": json.dumps(config),
                }
            )


class IxiaStopTrafficAndWaitTaskTest(later.unittest.TestCase):
    @patch(f"{ALL_PATH}.asyncio.sleep", new_callable=AsyncMock)
    async def test_stops_traffic_before_waiting(self, sleep: AsyncMock) -> None:
        ixia = MagicMock()
        task = IxiaStopTrafficAndWaitTask(ixia=ixia, logger=MagicMock())

        await task.run({"wait_seconds": 300})

        ixia.stop_traffic.assert_called_once_with()
        sleep.assert_awaited_once_with(300.0)

    async def test_rejects_negative_wait(self) -> None:
        task = IxiaStopTrafficAndWaitTask(ixia=MagicMock(), logger=MagicMock())

        with self.assertRaisesRegex(ValueError, "must be non-negative"):
            await task.run({"wait_seconds": -1})


class IxiaSyncRawSourceMacsTaskTest(later.unittest.TestCase):
    async def test_syncs_matching_raw_items(self) -> None:
        ixia = MagicMock()
        ixia.sync_raw_traffic_source_macs.return_value = {
            "CPU_RAW": "00:11:01:00:00:01"
        }
        task = IxiaSyncRawSourceMacsTask(ixia=ixia, logger=MagicMock())

        await task.run({"traffic_item_regex": "^CPU_RAW$"})

        ixia.sync_raw_traffic_source_macs.assert_called_once_with("^CPU_RAW$")

    async def test_fails_when_nothing_was_synced(self) -> None:
        ixia = MagicMock()
        ixia.sync_raw_traffic_source_macs.return_value = {}
        task = IxiaSyncRawSourceMacsTask(ixia=ixia, logger=MagicMock())

        with self.assertRaisesRegex(ValueError, "had its source MAC synced"):
            await task.run({"traffic_item_regex": "^MISSING$"})


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

    async def test_accepts_enabled_state_without_active_groups(self) -> None:
        self.driver.async_get_update_group_info = AsyncMock(
            return_value=SimpleNamespace(
                enable_update_group=True,
                update_groups=[],
            )
        )
        with patch(
            f"{ALL_PATH}.async_get_device_driver",
            new_callable=AsyncMock,
            return_value=self.driver,
        ):
            await self.task.run(
                {
                    "hostname": "bag012.ash6",
                    "expect_enabled": True,
                }
            )
        self.driver.async_get_update_group_info.assert_awaited_once_with()

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
            patch(f"{RETRY_UTILS_PATH}.asyncio.sleep", new_callable=AsyncMock),
            self.assertRaisesRegex(RuntimeError, "expected False"),
        ):
            await self.task.run(
                {
                    "hostname": "bag012.ash6",
                    "expect_enabled": False,
                }
            )
        self.assertEqual(3, self.logger.info.call_count)
        log_message = self.logger.info.call_args.args[0]
        self.assertIn("enabled=True", log_message)
        self.assertIn("expected False", log_message)

    async def test_retries_until_expected_state_is_observed(self) -> None:
        self.driver.async_get_update_group_info = AsyncMock(
            side_effect=[
                RuntimeError("daemon starting"),
                SimpleNamespace(enable_update_group=True, update_groups=[]),
            ]
        )
        with (
            patch(
                f"{ALL_PATH}.async_get_device_driver",
                new_callable=AsyncMock,
                return_value=self.driver,
            ),
            patch(f"{RETRY_UTILS_PATH}.asyncio.sleep", new_callable=AsyncMock),
        ):
            await self.task.run(
                {
                    "hostname": "bag012.ash6",
                    "expect_enabled": True,
                }
            )
        self.assertEqual(2, self.driver.async_get_update_group_info.await_count)

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
            patch(f"{RETRY_UTILS_PATH}.asyncio.sleep", new_callable=AsyncMock),
            self.assertRaisesRegex(RuntimeError, "permission denied"),
        ):
            await self.task.run(
                {
                    "hostname": "bag012.ash6",
                    "expect_enabled": False,
                }
            )
        self.assertEqual(3, self.logger.exception.call_count)
