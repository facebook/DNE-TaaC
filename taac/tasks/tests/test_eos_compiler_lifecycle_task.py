# Copyright (c) Meta Platforms, Inc. and affiliates.

from __future__ import annotations

import asyncio
import base64
import hashlib
from unittest.mock import AsyncMock, call, MagicMock, patch

from later.unittest import TestCase
from taac.driver.drivers_common import CommandExecutionError
from taac.internal.tasks.eos_compiler_lifecycle_task import (
    _directory_restore_script,
    _firewall_restore_script,
    _has_exact_startup_option,
    _parse_directory_state,
    _parse_firewall_rules,
    _read_firewall_chain_state,
    _RestorableDirectory,
    _RestorableFirewallChain,
    _validated_firewall_chain_name,
    EosCompilerLifecycleTask,
)


_MODULE = "neteng.test_infra.dne.taac.internal.tasks.eos_compiler_lifecycle_task"
_STATE_GUARD_DAEMONS = ["FibGrpc", "FibAgent", "Bgp", "BgpTcpdump"]
# patternlint-disable-next-line no-dev-shm-usage
_RIB_POLICY_STATE_PATH = "/dev/shm/bgp_rp_state.txt"


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
    if action in ("routing_config_install", "routing_config_verify"):
        params["source_path"] = "configerator/raw_configs/test/bgpcpp.json"
    return params


def _routing_component_params(action: str) -> dict[str, object]:
    params: dict[str, object] = {
        "action": action,
        "hostname": "dut.example.com",
        "operation_id": "component:dut0/routing_control_plane",
        "startup_path": "/usr/sbin/run_bgpcpp.sh",
    }
    if action == "routing_component_acknowledge":
        params["daemons"] = [
            {"name": "FibGrpc", "enabled": True, "dependencies": []},
            {"name": "FibBgpGrpc", "enabled": True, "dependencies": []},
            {
                "name": "FibAgent",
                "enabled": True,
                "dependencies": ["FibGrpc"],
            },
            {
                "name": "FibAgentBgp",
                "enabled": True,
                "dependencies": ["FibBgpGrpc"],
            },
            {"name": "Openr", "enabled": False, "dependencies": []},
            {
                "name": "Bgp",
                "enabled": True,
                "dependencies": ["FibAgent", "FibAgentBgp"],
            },
        ]
        params["startup_options"] = [
            {
                "daemon": "Bgp",
                "name": "bgp_resolve_nexthops_from_interface_state",
                "value": "true",
            }
        ]
    return params


def _state_guard_component_params(action: str) -> dict[str, object]:
    params = _routing_component_params(action)
    if action == "routing_component_snapshot":
        params["daemon_names"] = _STATE_GUARD_DAEMONS
    elif action == "routing_component_restore":
        params["force_restart_daemons"] = ["Bgp"]
        params["file_restores"] = [
            {
                "operation_id": "routing_config:dut0",
                "destination": "/mnt/flash/bgpcpp_config",
            },
            {
                "operation_id": "rib_policy_state:dut0",
                "destination": _RIB_POLICY_STATE_PATH,
            },
        ]
    return params


def _file_snapshot_params(operation_id: str, destination: str) -> dict[str, object]:
    return {
        "action": "routing_config_snapshot",
        "hostname": "dut.example.com",
        "operation_id": operation_id,
        "destination": destination,
    }


class EosCompilerLifecycleTaskTest(TestCase):
    def test_directory_state_preserves_presence_and_metadata(self) -> None:
        self.assertEqual(
            _RestorableDirectory(
                path="/mnt/fb/certs",
                exists=True,
                metadata=("750", 42, 43),
            ),
            _parse_directory_state(
                "switch#\ntaac-directory-state:present:750:42:43\nswitch#",
                "/mnt/fb/certs",
            ),
        )
        self.assertEqual(
            _RestorableDirectory(
                path="/mnt/fb/certs",
                exists=False,
                metadata=None,
            ),
            _parse_directory_state(
                "taac-directory-state:absent",
                "/mnt/fb/certs",
            ),
        )

    def test_firewall_state_requires_exact_chain_rules(self) -> None:
        self.assertEqual(
            (
                "-N EOS_BGP",
                "-A EOS_BGP -s 192.0.2.0/24 -j DROP",
                "-A EOS_BGP -j ACCEPT",
            ),
            _parse_firewall_rules(
                "\n".join(
                    (
                        "-N EOS_BGP",
                        "-A EOS_BGP -s 192.0.2.0/24 -j DROP",
                        "-A EOS_BGP -j ACCEPT",
                    )
                ),
                "EOS_BGP",
            ),
        )
        with self.assertRaisesRegex(RuntimeError, "malformed"):
            _parse_firewall_rules("-A OTHER -j ACCEPT", "EOS_BGP")

    def test_firewall_chain_rejects_leading_option_marker(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported characters"):
            _validated_firewall_chain_name("--wait")

    async def test_firewall_snapshot_records_explicit_missing_chain(self) -> None:
        run_shell = AsyncMock(
            side_effect=CommandExecutionError(
                "iptables: No chain/target/match by that name."
            )
        )

        with patch(f"{_MODULE}._run_shell", run_shell):
            state = await _read_firewall_chain_state(MagicMock(), "ipv4", "EOS_BGP")

        self.assertEqual(
            state,
            _RestorableFirewallChain(
                family="ipv4",
                chain="EOS_BGP",
                exists=False,
                rules=(),
            ),
        )
        run_shell.assert_awaited_once()

    async def test_firewall_snapshot_propagates_transient_query_error(self) -> None:
        run_shell = AsyncMock(
            side_effect=CommandExecutionError(
                "Another app is currently holding the xtables lock"
            )
        )

        with (
            patch(f"{_MODULE}._run_shell", run_shell),
            self.assertRaisesRegex(CommandExecutionError, "xtables lock"),
        ):
            await _read_firewall_chain_state(MagicMock(), "ipv4", "EOS_BGP")

        run_shell.assert_awaited_once()

    def test_firewall_restore_script_replays_and_verifies_saved_rules(self) -> None:
        script = _firewall_restore_script(
            _RestorableFirewallChain(
                family="ipv6",
                chain="EOS_BGP",
                exists=True,
                rules=("-N EOS_BGP", "-A EOS_BGP -j DROP"),
            )
        )

        self.assertIn("binary = '/sbin/ip6tables'", script)
        self.assertIn("run([binary, '-F', chain])", script)
        self.assertIn("run([binary, *tokens])", script)
        self.assertIn("line.strip()", script)
        self.assertIn(
            "for line in run([binary, '-S', chain]).stdout.splitlines()",
            script,
        )
        self.assertIn("firewall restore mismatch", script)
        self.assertIn("snapshot owns only the chain's rules", script)

    def test_absent_firewall_restore_removes_inbound_references(self) -> None:
        script = _firewall_restore_script(
            _RestorableFirewallChain(
                family="ipv4",
                chain="EOS_BGP",
                exists=False,
                rules=(),
            )
        )

        self.assertIn("{'-j', '--jump', '-g', '--goto'}", script)
        self.assertIn("run([binary, '-D', *tokens[1:]])", script)
        self.assertIn("belongs to the test state being rolled back", script)
        self.assertLess(script.index("'-D'"), script.index("'-X'"))

    def test_absent_directory_restore_unlinks_symlinks(self) -> None:
        script = _directory_restore_script(
            _RestorableDirectory(
                path="/mnt/fb/certs",
                exists=False,
                metadata=None,
            )
        )

        self.assertIn("if path.is_symlink():", script)
        self.assertIn("path.unlink()", script)
        self.assertIn("Fail closed on unexpected contents", script)
        self.assertLess(script.index("path.unlink()"), script.index("path.rmdir()"))

    def test_startup_option_rejects_space_separated_value(self) -> None:
        self.assertFalse(
            _has_exact_startup_option(
                "--bgp_resolve_nexthops_from_interface_state true",
                "bgp_resolve_nexthops_from_interface_state",
                "true",
            )
        )

    def test_startup_option_rejects_bare_flag_followed_by_flag(self) -> None:
        self.assertFalse(
            _has_exact_startup_option(
                "--bgp_resolve_nexthops_from_interface_state --verbose",
                "bgp_resolve_nexthops_from_interface_state",
                "--verbose",
            )
        )

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
            "bash sudo rm -f '/mnt/flash/bgpcpp_config' && sudo test ! -e "
            "'/mnt/flash/bgpcpp_config' && sudo test ! -L "
            "'/mnt/flash/bgpcpp_config'",
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

    async def test_routing_config_install_uses_configerator_and_typed_overrides(
        self,
    ) -> None:
        source = '{"1":{"rec":{"5":{"i32":1},"36":{"i32":1000}}}}\n'
        expected = '{"1":{"rec":{"5":{"i32":1},"36":{"i32":60000}}}}\n'
        driver = MagicMock()
        driver.async_read_file = AsyncMock(side_effect=("old config", expected))

        async def execute(command: str, *, configure: bool = False) -> str:
            if "stat -c" in command:
                return "taac-file-metadata:640:42:43"
            if "sha256sum" in command:
                return f"{hashlib.sha256(expected.encode()).hexdigest()}  install.tmp"
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
        client = MagicMock()
        client.__enter__.return_value.get_config_contents.return_value = source
        params = _routing_config_params("routing_config_install")
        params["json_i32_overrides"] = [
            {"path": ["1", "rec", "36", "i32"], "value": 60_000}
        ]

        with (
            patch(
                f"{_MODULE}.async_get_device_driver",
                AsyncMock(return_value=driver),
            ),
            patch(f"{_MODULE}.ConfigeratorClient", return_value=client),
        ):
            await task.run(params)

        client.__enter__.return_value.get_config_contents.assert_called_once_with(
            "configerator/raw_configs/test/bgpcpp.json"
        )
        commands = tuple(
            item.args[0]
            for item in driver.async_execute_show_or_configure_cmd_on_shell.await_args_list
        )
        encoded_expected = base64.b64encode(expected.encode()).decode("ascii")
        self.assertTrue(any(encoded_expected in command for command in commands))
        self.assertTrue(any("chown 42:43" in command for command in commands))
        self.assertTrue(any("chmod '640'" in command for command in commands))
        self.assertTrue(any("mv -f" in command for command in commands))
        logger.info.assert_called_once()

    async def test_routing_config_install_rejects_invalid_override_before_io(
        self,
    ) -> None:
        get_driver = AsyncMock()
        task = EosCompilerLifecycleTask(
            hostname="dut.example.com",
            logger=MagicMock(),
            shared_data={},
        )
        params = _routing_config_params("routing_config_install")
        params["json_i32_overrides"] = [
            {"path": ["1", "rec", "36", "i32"], "value": True}
        ]

        with patch(f"{_MODULE}.async_get_device_driver", get_driver):
            with self.assertRaisesRegex(ValueError, "signed i32"):
                await task.run(params)

        get_driver.assert_not_awaited()

    async def test_routing_config_install_rejects_missing_override_path_before_io(
        self,
    ) -> None:
        get_driver = AsyncMock()
        task = EosCompilerLifecycleTask(
            hostname="dut.example.com",
            logger=MagicMock(),
            shared_data={},
        )
        client = MagicMock()
        client.__enter__.return_value.get_config_contents.return_value = (
            '{"1":{"rec":{}}}\n'
        )
        params = _routing_config_params("routing_config_install")
        params["json_i32_overrides"] = [
            {"path": ["1", "rec", "36", "i32"], "value": 60_000}
        ]

        with (
            patch(f"{_MODULE}.async_get_device_driver", get_driver),
            patch(f"{_MODULE}.ConfigeratorClient", return_value=client),
        ):
            with self.assertRaisesRegex(ValueError, "missing path component"):
                await task.run(params)

        get_driver.assert_not_awaited()

    async def test_routing_config_install_rejects_malformed_source_before_device_io(
        self,
    ) -> None:
        get_driver = AsyncMock()
        task = EosCompilerLifecycleTask(
            hostname="dut.example.com",
            logger=MagicMock(),
            shared_data={},
        )
        client = MagicMock()
        client.__enter__.return_value.get_config_contents.return_value = "not-json"
        params = _routing_config_params("routing_config_install")
        params["json_i32_overrides"] = [
            {"path": ["1", "rec", "36", "i32"], "value": 60_000}
        ]

        with (
            patch(f"{_MODULE}.async_get_device_driver", get_driver),
            patch(f"{_MODULE}.ConfigeratorClient", return_value=client),
        ):
            with self.assertRaisesRegex(ValueError, "valid JSON"):
                await task.run(params)

        get_driver.assert_not_awaited()

    async def test_routing_config_verifies_source_and_restores_prior_bytes(
        self,
    ) -> None:
        prior_bytes: bytes = b"prior\xffbytes"
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

    async def test_restore_failure_preserves_cleanup_failure_note(self) -> None:
        driver = MagicMock()
        driver.async_read_file = AsyncMock(return_value="prior bytes")

        async def execute(command: str, *, configure: bool = False) -> str:
            if "stat -c" in command:
                return "taac-file-metadata:640:42:43"
            if "base64 -d" in command:
                raise RuntimeError("primary restore failed")
            if "rm -f" in command:
                raise RuntimeError("scratch cleanup failed")
            return ""

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
            with self.assertRaisesRegex(
                RuntimeError, "primary restore failed"
            ) as context:
                await task.run(_routing_config_params("routing_config_restore"))

        self.assertIn(
            "restore cleanup also failed: scratch cleanup failed",
            context.exception.__notes__,
        )

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

        # Two staging attempts, then one exact post-install verification.
        self.assertEqual(3, checksum_attempts)
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

    async def test_routing_component_restores_startup_and_running_config(self) -> None:
        driver = MagicMock()
        driver.async_read_file = AsyncMock(return_value="original startup")

        async def execute(command: str, *, configure: bool = False) -> str:
            if "stat -c" in command:
                return "taac-file-metadata:755:0:0"
            if "sha256sum" in command:
                return hashlib.sha256(b"original startup").hexdigest()
            return ""

        driver.async_execute_show_or_configure_cmd_on_shell = AsyncMock(
            side_effect=execute
        )
        task = EosCompilerLifecycleTask(
            hostname="dut.example.com",
            logger=MagicMock(),
            shared_data={},
        )
        restore = AsyncMock()
        delete = AsyncMock()

        with (
            patch(
                f"{_MODULE}.async_get_device_driver",
                AsyncMock(return_value=driver),
            ),
            patch(
                f"{_MODULE}.arista_utils.save_running_config",
                AsyncMock(return_value="flash:component-original"),
            ),
            patch(f"{_MODULE}.arista_utils.restore_running_config", restore),
            patch(f"{_MODULE}.arista_utils.delete_backup_config", delete),
        ):
            await task.run(_routing_component_params("routing_component_snapshot"))
            await task.run(_routing_component_params("routing_component_restore"))

        commands = tuple(
            item.args[0]
            for item in driver.async_execute_show_or_configure_cmd_on_shell.await_args_list
        )
        self.assertTrue(
            any("b3JpZ2luYWwgc3RhcnR1cA==" in command for command in commands)
        )
        self.assertTrue(any("chown 0:0" in command for command in commands))
        self.assertTrue(any("chmod '755'" in command for command in commands))
        restore.assert_awaited_once_with(
            driver,
            "flash:component-original",
            logger_instance=task.logger,
        )
        delete.assert_awaited_once_with(
            driver,
            "flash:component-original",
            logger_instance=task.logger,
        )

    async def test_routing_component_restores_directories_and_firewall(self) -> None:
        driver = MagicMock()
        driver.async_read_file = AsyncMock(side_effect=FileNotFoundError)
        driver.async_execute_show_or_configure_cmd_on_shell = AsyncMock(return_value="")
        task = EosCompilerLifecycleTask(
            hostname="dut.example.com",
            logger=MagicMock(),
            shared_data={},
        )
        directory = _RestorableDirectory(
            path="/mnt/fb/certs",
            exists=True,
            metadata=("750", 42, 43),
        )
        firewall = _RestorableFirewallChain(
            family="ipv4",
            chain="EOS_BGP",
            exists=True,
            rules=("-N EOS_BGP", "-A EOS_BGP -j DROP"),
        )
        snapshot_params = _routing_component_params("routing_component_snapshot")
        snapshot_params["directory_paths"] = [directory.path]
        snapshot_params["firewall_chains"] = [
            {"family": firewall.family, "chain": firewall.chain}
        ]
        snapshot_params["daemon_names"] = ["Bgp"]
        restore_order: list[str] = []
        restore_directory = AsyncMock(
            side_effect=lambda *_args: restore_order.append("directory")
        )
        restore_firewall = AsyncMock(
            side_effect=lambda *_args: restore_order.append("firewall")
        )
        reconcile_daemons = AsyncMock(
            side_effect=lambda *_args: restore_order.append("daemons")
        )

        with (
            patch(
                f"{_MODULE}.async_get_device_driver",
                AsyncMock(return_value=driver),
            ),
            patch(
                f"{_MODULE}.arista_utils.save_running_config",
                AsyncMock(return_value="flash:component-original"),
            ),
            patch(
                f"{_MODULE}.arista_utils.restore_running_config",
                AsyncMock(),
            ),
            patch(
                f"{_MODULE}.arista_utils.delete_backup_config",
                AsyncMock(),
            ),
            patch(
                f"{_MODULE}._read_directory_state",
                AsyncMock(return_value=directory),
            ),
            patch(
                f"{_MODULE}._read_firewall_chain_state",
                AsyncMock(return_value=firewall),
            ),
            patch(
                f"{_MODULE}._read_daemon_states",
                AsyncMock(return_value=(("Bgp", True),)),
            ),
            patch(f"{_MODULE}._quiesce_daemons_for_restore", AsyncMock()),
            patch(f"{_MODULE}._reconcile_daemon_states", reconcile_daemons),
            patch(f"{_MODULE}._restore_directory", restore_directory),
            patch(f"{_MODULE}._restore_firewall_chain", restore_firewall),
        ):
            await task.run(snapshot_params)
            restore_firewall.side_effect = RuntimeError("firewall restore failed")
            with self.assertRaisesRegex(RuntimeError, "firewall restore failed"):
                await task.run(_routing_component_params("routing_component_restore"))

            # A dependency restore failure must not strand the captured daemon
            # state in the quiesced/down state.
            reconcile_daemons.assert_awaited_once()

            restore_order.clear()
            restore_firewall.reset_mock()
            restore_firewall.side_effect = lambda *_args: restore_order.append(
                "firewall"
            )
            restore_directory.reset_mock()
            reconcile_daemons.reset_mock()
            await task.run(_routing_component_params("routing_component_restore"))

        restore_firewall.assert_awaited_once_with(driver, firewall)
        restore_directory.assert_awaited_once_with(driver, directory)
        reconcile_daemons.assert_awaited_once()
        self.assertEqual(["firewall", "directory", "daemons"], restore_order)

    async def test_routing_component_snapshot_cleans_backup_on_failure(self) -> None:
        driver = MagicMock()
        driver.async_read_file = AsyncMock(return_value="original startup")
        driver.async_execute_show_or_configure_cmd_on_shell = AsyncMock(
            return_value="malformed metadata"
        )
        shared_data: dict[object, object] = {}
        task = EosCompilerLifecycleTask(
            hostname="dut.example.com",
            logger=MagicMock(),
            shared_data=shared_data,
        )
        delete = AsyncMock()

        with (
            patch(
                f"{_MODULE}.async_get_device_driver",
                AsyncMock(return_value=driver),
            ),
            patch(
                f"{_MODULE}.arista_utils.save_running_config",
                AsyncMock(return_value="flash:component-original"),
            ),
            patch(f"{_MODULE}.arista_utils.delete_backup_config", delete),
        ):
            with self.assertRaisesRegex(RuntimeError, "metadata readback"):
                await task.run(_routing_component_params("routing_component_snapshot"))

        delete.assert_awaited_once_with(
            driver,
            "flash:component-original",
            logger_instance=task.logger,
        )
        self.assertEqual({}, shared_data)

    async def test_snapshot_failure_preserves_error_when_backup_cleanup_fails(
        self,
    ) -> None:
        driver = MagicMock()
        driver.async_read_file = AsyncMock(return_value="original startup")
        driver.async_execute_show_or_configure_cmd_on_shell = AsyncMock(
            return_value="malformed metadata"
        )
        logger = MagicMock()
        task = EosCompilerLifecycleTask(
            hostname="dut.example.com",
            logger=logger,
            shared_data={},
        )

        with (
            patch(
                f"{_MODULE}.async_get_device_driver",
                AsyncMock(return_value=driver),
            ),
            patch(
                f"{_MODULE}.arista_utils.save_running_config",
                AsyncMock(return_value="flash:component-original"),
            ),
            patch(
                f"{_MODULE}.arista_utils.delete_backup_config",
                AsyncMock(side_effect=RuntimeError("backup cleanup failed")),
            ),
            self.assertRaisesRegex(RuntimeError, "metadata readback") as context,
        ):
            await task.run(_routing_component_params("routing_component_snapshot"))

        self.assertIn(
            "provisional snapshot backup cleanup also failed: backup cleanup failed",
            context.exception.__notes__,
        )
        logger.warning.assert_called_once()

    async def test_routing_component_restore_retains_backup_on_failure(self) -> None:
        driver = MagicMock()
        driver.async_read_file = AsyncMock(side_effect=FileNotFoundError)
        driver.async_execute_show_or_configure_cmd_on_shell = AsyncMock(return_value="")
        logger = MagicMock()
        task = EosCompilerLifecycleTask(
            hostname="dut.example.com",
            logger=logger,
            shared_data={},
        )
        restore = AsyncMock(side_effect=ValueError("restore failed"))
        delete = AsyncMock()

        with (
            patch(
                f"{_MODULE}.async_get_device_driver",
                AsyncMock(return_value=driver),
            ),
            patch(
                f"{_MODULE}.arista_utils.save_running_config",
                AsyncMock(return_value="flash:component-original"),
            ),
            patch(f"{_MODULE}.arista_utils.restore_running_config", restore),
            patch(f"{_MODULE}.arista_utils.delete_backup_config", delete),
        ):
            await task.run(_routing_component_params("routing_component_snapshot"))
            with self.assertRaisesRegex(ValueError, "restore failed"):
                await task.run(_routing_component_params("routing_component_restore"))

        delete.assert_not_awaited()
        logger.warning.assert_called_once()

    async def test_routing_component_snapshot_keeps_first_daemon_state(self) -> None:
        daemon_states: dict[str, bool] = {
            "FibGrpc": True,
            "FibAgent": False,
            "Bgp": True,
            "BgpTcpdump": True,
        }
        driver = MagicMock()
        driver.async_read_file = AsyncMock(return_value="original startup")

        async def execute(command: str, *, configure: bool = False) -> str:
            if "stat -c" in command:
                return "taac-file-metadata:755:0:0"
            if command.startswith("show daemon"):
                daemon_name = next(
                    name for name in reversed(_STATE_GUARD_DAEMONS) if name in command
                )
                state = (
                    "running with PID 123"
                    if daemon_states[daemon_name]
                    else "not running"
                )
                return f"Process: {daemon_name} ({state})"
            return ""

        driver.async_execute_show_or_configure_cmd_on_shell = AsyncMock(
            side_effect=execute
        )
        task = EosCompilerLifecycleTask(
            hostname="dut.example.com",
            logger=MagicMock(),
            shared_data={},
        )
        save = AsyncMock(return_value="flash:component-original")

        with (
            patch(
                f"{_MODULE}.async_get_device_driver",
                AsyncMock(return_value=driver),
            ),
            patch(f"{_MODULE}.arista_utils.save_running_config", save),
        ):
            params = _state_guard_component_params("routing_component_snapshot")
            await task.run(params)
            daemon_states["Bgp"] = False
            driver.async_read_file.return_value = "changed startup"
            await task.run(params)

        save.assert_awaited_once()
        driver.async_read_file.assert_awaited_once_with("/usr/sbin/run_bgpcpp.sh")
        daemon_queries = [
            item.args[0]
            for item in driver.async_execute_show_or_configure_cmd_on_shell.await_args_list
            if item.args[0].startswith("show daemon")
        ]
        self.assertEqual(len(_STATE_GUARD_DAEMONS), len(daemon_queries))

    async def test_routing_component_restore_restores_files_then_daemons(self) -> None:
        startup_bytes = b"original startup\n"
        bgpcpp_bytes = b"config\xffbytes"
        rib_policy_bytes = b"\x00rib-policy\xfe"
        files: dict[str, bytes] = {
            "/usr/sbin/run_bgpcpp.sh": startup_bytes,
            "/mnt/flash/bgpcpp_config": bgpcpp_bytes,
            _RIB_POLICY_STATE_PATH: rib_policy_bytes,
        }
        metadata: dict[str, tuple[str, int, int]] = {
            "/usr/sbin/run_bgpcpp.sh": ("755", 0, 0),
            "/mnt/flash/bgpcpp_config": ("640", 42, 43),
            _RIB_POLICY_STATE_PATH: ("600", 44, 45),
        }
        daemon_states: dict[str, bool] = {
            "FibGrpc": True,
            "FibAgent": False,
            "Bgp": True,
            "BgpTcpdump": True,
        }
        transitions: list[tuple[str, bool]] = []
        events: list[str] = []
        driver = MagicMock()

        async def read_file(path: str) -> str:
            return files[path].decode("utf-8", errors="surrogateescape")

        async def execute(command: str, *, configure: bool = False) -> str:
            if command.startswith("show daemon"):
                daemon_name = next(
                    name for name in reversed(_STATE_GUARD_DAEMONS) if name in command
                )
                state = (
                    "running with PID 123"
                    if daemon_states[daemon_name]
                    else "not running"
                )
                return f"Process: {daemon_name} ({state})"
            if configure and command.startswith("daemon"):
                daemon_name = next(
                    name for name in reversed(_STATE_GUARD_DAEMONS) if name in command
                )
                running = "no shutdown" in command
                daemon_states[daemon_name] = running
                transitions.append((daemon_name, running))
                events.append(f"daemon:{daemon_name}:{running}")
                return ""
            if "stat -c" in command:
                path = next(path for path in files if path in command)
                mode, owner_uid, owner_gid = metadata[path]
                return f"taac-file-metadata:{mode}:{owner_uid}:{owner_gid}"
            if "sha256sum" in command:
                path = next(path for path in files if path in command)
                return hashlib.sha256(files[path]).hexdigest()
            if "mv -f" in command:
                path = next(path for path in files if path in command)
                events.append(f"file:{path}")
            return ""

        driver.async_read_file = AsyncMock(side_effect=read_file)
        driver.async_execute_show_or_configure_cmd_on_shell = AsyncMock(
            side_effect=execute
        )
        task = EosCompilerLifecycleTask(
            hostname="dut.example.com",
            logger=MagicMock(),
            shared_data={},
        )

        async def restore_running_config(*args: object, **kwargs: object) -> None:
            events.append("running-config")

        delete = AsyncMock()
        with (
            patch(
                f"{_MODULE}.async_get_device_driver",
                AsyncMock(return_value=driver),
            ),
            patch(
                f"{_MODULE}.arista_utils.save_running_config",
                AsyncMock(return_value="flash:component-original"),
            ),
            patch(
                f"{_MODULE}.arista_utils.restore_running_config",
                side_effect=restore_running_config,
            ),
            patch(f"{_MODULE}.arista_utils.delete_backup_config", delete),
        ):
            await task.run(_state_guard_component_params("routing_component_snapshot"))
            await task.run(
                _file_snapshot_params(
                    "routing_config:dut0",
                    "/mnt/flash/bgpcpp_config",
                )
            )
            await task.run(
                _file_snapshot_params(
                    "rib_policy_state:dut0",
                    _RIB_POLICY_STATE_PATH,
                )
            )
            daemon_states.update(
                {
                    "FibGrpc": False,
                    "FibAgent": True,
                    "Bgp": True,
                    "BgpTcpdump": False,
                }
            )
            await task.run(_state_guard_component_params("routing_component_restore"))

        self.assertEqual(
            [
                ("Bgp", False),
                ("FibAgent", False),
                ("FibGrpc", True),
                ("Bgp", True),
                ("BgpTcpdump", True),
            ],
            transitions,
        )
        self.assertEqual(
            {
                "FibGrpc": True,
                "FibAgent": False,
                "Bgp": True,
                "BgpTcpdump": True,
            },
            daemon_states,
        )
        self.assertLess(
            events.index("daemon:Bgp:False"),
            events.index("file:/mnt/flash/bgpcpp_config"),
        )
        self.assertLess(
            events.index("file:/mnt/flash/bgpcpp_config"),
            events.index("file:/dev/shm/bgp_rp_state.txt"),
        )
        self.assertLess(
            events.index("file:/dev/shm/bgp_rp_state.txt"),
            events.index("file:/usr/sbin/run_bgpcpp.sh"),
        )
        self.assertLess(
            events.index("file:/usr/sbin/run_bgpcpp.sh"), events.index("running-config")
        )
        self.assertLess(events.index("running-config"), events.index("daemon:Bgp:True"))

        commands = tuple(
            item.args[0]
            for item in driver.async_execute_show_or_configure_cmd_on_shell.await_args_list
        )
        for path, content in files.items():
            self.assertTrue(
                any(
                    base64.b64encode(content).decode("ascii") in command
                    for command in commands
                )
            )
            mode, owner_uid, owner_gid = metadata[path]
            self.assertTrue(
                any(
                    f"chown {owner_uid}:{owner_gid}" in command and path in command
                    for command in commands
                )
            )
            self.assertTrue(
                any(
                    f"chmod '{mode}'" in command and path in command
                    for command in commands
                )
            )
        delete.assert_awaited_once_with(
            driver,
            "flash:component-original",
            logger_instance=task.logger,
        )

    async def test_routing_component_does_not_reload_originally_stopped_bgp(
        self,
    ) -> None:
        daemon_running = False
        transitions: list[bool] = []
        driver = MagicMock()
        driver.async_read_file = AsyncMock(side_effect=FileNotFoundError)

        async def execute(command: str, *, configure: bool = False) -> str:
            nonlocal daemon_running
            if command.startswith("show daemon"):
                state = "running with PID 123" if daemon_running else "not running"
                return f"Process: Bgp ({state})"
            if configure and command.startswith("daemon"):
                daemon_running = "no shutdown" in command
                transitions.append(daemon_running)
            return ""

        driver.async_execute_show_or_configure_cmd_on_shell = AsyncMock(
            side_effect=execute
        )
        task = EosCompilerLifecycleTask(
            hostname="dut.example.com",
            logger=MagicMock(),
            shared_data={},
        )
        snapshot_params = _routing_component_params("routing_component_snapshot")
        snapshot_params["daemon_names"] = ["Bgp"]
        restore_params = _routing_component_params("routing_component_restore")
        restore_params["force_restart_daemons"] = ["Bgp"]

        with (
            patch(
                f"{_MODULE}.async_get_device_driver",
                AsyncMock(return_value=driver),
            ),
            patch(
                f"{_MODULE}.arista_utils.save_running_config",
                AsyncMock(return_value="flash:component-original"),
            ),
            patch(
                f"{_MODULE}.arista_utils.restore_running_config",
                AsyncMock(),
            ),
            patch(
                f"{_MODULE}.arista_utils.delete_backup_config",
                AsyncMock(),
            ),
        ):
            await task.run(snapshot_params)
            daemon_running = True
            await task.run(restore_params)

        self.assertEqual([False], transitions)
        self.assertFalse(daemon_running)

    async def test_routing_component_validates_all_file_snapshots_before_restore(
        self,
    ) -> None:
        driver = MagicMock()
        driver.async_read_file = AsyncMock(side_effect=FileNotFoundError)
        driver.async_execute_show_or_configure_cmd_on_shell = AsyncMock(return_value="")
        task = EosCompilerLifecycleTask(
            hostname="dut.example.com",
            logger=MagicMock(),
            shared_data={},
        )
        get_driver = AsyncMock(return_value=driver)
        delete = AsyncMock()

        with (
            patch(f"{_MODULE}.async_get_device_driver", get_driver),
            patch(
                f"{_MODULE}.arista_utils.save_running_config",
                AsyncMock(return_value="flash:component-original"),
            ),
            patch(f"{_MODULE}.arista_utils.delete_backup_config", delete),
        ):
            await task.run(_routing_component_params("routing_component_snapshot"))
            get_driver.reset_mock()
            restore_params = _routing_component_params("routing_component_restore")
            restore_params["file_restores"] = [
                {
                    "operation_id": "missing",
                    "destination": "/mnt/flash/bgpcpp_config",
                }
            ]
            with self.assertRaisesRegex(
                RuntimeError,
                "restore invoked without snapshot for missing",
            ):
                await task.run(restore_params)

        get_driver.assert_not_awaited()
        delete.assert_not_awaited()

    async def test_routing_component_acknowledges_daemons_and_startup_option(
        self,
    ) -> None:
        driver = MagicMock()

        async def daemon_status(command: str) -> str:
            names = ("FibBgpGrpc", "FibAgentBgp", "FibGrpc", "FibAgent", "Openr", "Bgp")
            name = next(name for name in names if name in command)
            state = "not running" if name == "Openr" else "running with PID 123"
            return f"Process: {name} ({state})"

        driver.async_execute_show_or_configure_cmd_on_shell = AsyncMock(
            side_effect=daemon_status
        )
        driver.async_read_file = AsyncMock(
            return_value="\n".join(
                (
                    "--bgp_resolve_nexthops_from_interface_state=\\",
                    "true",
                )
            )
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
            await task.run(_routing_component_params("routing_component_acknowledge"))

        self.assertEqual(
            6,
            driver.async_execute_show_or_configure_cmd_on_shell.await_count,
        )
        driver.async_read_file.assert_awaited_once_with("/usr/sbin/run_bgpcpp.sh")

    async def test_routing_component_acknowledge_skips_unused_startup_file(
        self,
    ) -> None:
        driver = MagicMock()

        async def daemon_status(command: str) -> str:
            names = ("FibBgpGrpc", "FibAgentBgp", "FibGrpc", "FibAgent", "Openr", "Bgp")
            name = next(name for name in names if name in command)
            state = "not running" if name == "Openr" else "running with PID 123"
            return f"Process: {name} ({state})"

        driver.async_execute_show_or_configure_cmd_on_shell = AsyncMock(
            side_effect=daemon_status
        )
        driver.async_read_file = AsyncMock()
        task = EosCompilerLifecycleTask(
            hostname="dut.example.com",
            logger=MagicMock(),
            shared_data={},
        )
        params = _routing_component_params("routing_component_acknowledge")
        params["startup_options"] = []

        with patch(
            f"{_MODULE}.async_get_device_driver",
            AsyncMock(return_value=driver),
        ):
            await task.run(params)

        driver.async_read_file.assert_not_awaited()

    async def test_routing_component_acknowledge_reports_startup_read_failure(
        self,
    ) -> None:
        driver = MagicMock()

        async def daemon_status(command: str) -> str:
            names = ("FibBgpGrpc", "FibAgentBgp", "FibGrpc", "FibAgent", "Openr", "Bgp")
            name = next(name for name in names if name in command)
            state = "not running" if name == "Openr" else "running with PID 123"
            return f"Process: {name} ({state})"

        driver.async_execute_show_or_configure_cmd_on_shell = AsyncMock(
            side_effect=daemon_status
        )
        driver.async_read_file = AsyncMock(
            side_effect=CommandExecutionError("transport failed")
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
            with self.assertRaisesRegex(
                RuntimeError,
                "failed to read EOS routing component startup file ",
            ):
                await task.run(
                    _routing_component_params("routing_component_acknowledge")
                )

    async def test_routing_component_rejects_unacknowledged_daemon(self) -> None:
        driver = MagicMock()
        driver.async_execute_show_or_configure_cmd_on_shell = AsyncMock(
            return_value="Process: FibGrpc (not running)"
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
            with self.assertRaisesRegex(RuntimeError, "acknowledgement mismatch"):
                await task.run(
                    _routing_component_params("routing_component_acknowledge")
                )

    async def test_routing_component_rejects_inexact_startup_option(self) -> None:
        driver = MagicMock()

        async def daemon_status(command: str) -> str:
            names = ("FibBgpGrpc", "FibAgentBgp", "FibGrpc", "FibAgent", "Openr", "Bgp")
            name = next(name for name in names if name in command)
            state = "not running" if name == "Openr" else "running with PID 123"
            return f"Process: {name} ({state})"

        driver.async_execute_show_or_configure_cmd_on_shell = AsyncMock(
            side_effect=daemon_status
        )
        driver.async_read_file = AsyncMock(
            return_value=(
                "# --bgp_resolve_nexthops_from_interface_state=true\n"
                "--bgp_resolve_nexthops_from_interface_state=true0"
            )
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
            with self.assertRaisesRegex(RuntimeError, "was not acknowledged"):
                await task.run(
                    _routing_component_params("routing_component_acknowledge")
                )

    async def test_routing_component_rejects_duplicate_startup_option(self) -> None:
        driver = MagicMock()

        async def daemon_status(command: str) -> str:
            names = ("FibBgpGrpc", "FibAgentBgp", "FibGrpc", "FibAgent", "Openr", "Bgp")
            name = next(name for name in names if name in command)
            state = "not running" if name == "Openr" else "running with PID 123"
            return f"Process: {name} ({state})"

        driver.async_execute_show_or_configure_cmd_on_shell = AsyncMock(
            side_effect=daemon_status
        )
        driver.async_read_file = AsyncMock(
            return_value=(
                "--bgp_resolve_nexthops_from_interface_state=false "
                "--bgp_resolve_nexthops_from_interface_state=true"
            )
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
            with self.assertRaisesRegex(RuntimeError, "was not acknowledged"):
                await task.run(
                    _routing_component_params("routing_component_acknowledge")
                )
