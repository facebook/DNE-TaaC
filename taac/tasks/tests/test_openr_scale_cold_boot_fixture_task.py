# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

import json
from unittest.mock import AsyncMock, MagicMock, patch

from later.unittest import TestCase
from taac.internal.tasks.openr_scale_cold_boot_fixture_task import (
    _boot_hook,
    _FIXTURE_READY,
    _NO_ORIGINAL_RC_EOS,
    _OPENR_CONFIG,
    _OPENR_CONFIG_APPLIED,
    _ORIGINAL_OPENR_CONFIG,
    _ORIGINAL_RC_EOS,
    _OWNER,
    _OWNER_PATH,
    _RC_EOS,
    _RESTORE_SCRIPT,
    _restore_script,
    _STATE_DIR,
    OpenRScaleColdBootFixtureTask,
)
from taac.task_definitions import (
    create_openr_scale_cold_boot_fixture_task,
)
from taac.tasks.registry import TASK_NAME_TO_CLASS


_MODULE = "neteng.test_infra.dne.taac.internal.tasks.openr_scale_cold_boot_fixture_task"


def _params(action: str) -> dict[str, object]:
    return {
        "action": action,
        "dut_name": "eb04.lab.ash6",
        "helper_name": "eb02.lab.ash6",
        "port_channel": "Port-Channel1910",
        "num_subinterfaces": 64,
        "start_vlan": 100,
        "dut_host_octet": 2,
        "helper_host_octet": 1,
        "wait_attempts": 450,
        "wait_interval_seconds": 2,
        "setup_timeout_seconds": 600,
    }


class _FakeDriver:
    def __init__(self, *, rc_eos_exists: bool = False) -> None:
        self.paths = {_RC_EOS} if rc_eos_exists else set()
        self.commands: list[str] = []
        self.openr_running = True

    async def async_run_cmd_on_shell(self, command: str) -> str:  # noqa: C901
        self.commands.append(command)
        if "test -e" in command:
            for path in sorted(self.paths, key=len, reverse=True):
                if f"test -e {path} " in command:
                    return "TAAC_OPENR_SCALE_PATH_EXISTS\n"
            return ""
        if f"cat {_OWNER_PATH}" in command:
            return f"{_OWNER}\n"
        if f"mkdir -p {_STATE_DIR}" in command:
            self.paths.add(_STATE_DIR)
        if f"tee {_OWNER_PATH}" in command or command.endswith(f" {_OWNER_PATH}"):
            self.paths.add(_OWNER_PATH)
        if f"cp -p {_RC_EOS} {_ORIGINAL_RC_EOS}" in command:
            self.paths.add(_ORIGINAL_RC_EOS)
        if f"touch {_NO_ORIGINAL_RC_EOS}" in command:
            self.paths.add(_NO_ORIGINAL_RC_EOS)
        if command.endswith(f" {_OPENR_CONFIG}"):
            self.paths.add(_OPENR_CONFIG)
        if command.endswith(f" {_ORIGINAL_OPENR_CONFIG}"):
            self.paths.add(_ORIGINAL_OPENR_CONFIG)
        if command.endswith(f" {_RESTORE_SCRIPT}"):
            self.paths.add(_RESTORE_SCRIPT)
        if command.endswith(f" {_RC_EOS}"):
            self.paths.add(_RC_EOS)
        if f"rm -f {_RC_EOS}" in command:
            self.paths.discard(_RC_EOS)
        if f"rm -rf {_STATE_DIR}" in command:
            self.paths = {
                path for path in self.paths if not path.startswith(_STATE_DIR)
            }
        return ""

    async def async_execute_show_or_configure_cmd_on_shell(
        self, command: str, configure: bool = False
    ) -> str:
        self.commands.append(command)
        if command == "daemon Openr\nshutdown":
            self.openr_running = False
        elif command == "daemon Openr\nno shutdown":
            self.openr_running = True
        return ""

    async def async_get_openr_kvstore_keys(self) -> dict[str, list[str]]:
        if not self.openr_running:
            raise RuntimeError("Open/R is down")
        return {"0": []}


class OpenRScaleColdBootFixtureTaskTest(TestCase):
    def test_factory_serializes_reboot_fixture(self) -> None:
        task = create_openr_scale_cold_boot_fixture_task(
            action="setup",
            dut_name="eb04.lab.ash6",
            helper_name="eb02.lab.ash6",
        )

        self.assertEqual("openr_scale_cold_boot_fixture", task.task_name)
        self.assertEqual(_params("setup"), json.loads(task.params.json_params or "{}"))

    def test_registered_as_internal_task(self) -> None:
        self.assertIs(
            OpenRScaleColdBootFixtureTask,
            TASK_NAME_TO_CLASS["openr_scale_cold_boot_fixture"],
        )

    def test_boot_hook_returns_before_fixture_waiter(self) -> None:
        hook = _boot_hook()

        self.assertNotIn("daemon Openr\nshutdown", hook)
        self.assertIn(
            'install -o root -g root -m 0644 "${ORIGINAL_OPENR_CONFIG}"', hook
        )
        self.assertIn('rm -f "${OPENR_CONFIG_APPLIED}" "${FIXTURE_READY}"', hook)
        self.assertIn('"${RESTORE_SCRIPT}" >>"${LOG_FILE}" 2>&1 &', hook)
        self.assertIn('echo "$!" >"${WAITER_PID}"', hook)

    def test_restore_script_reuses_predeployed_subinterface_setup(self) -> None:
        script = _restore_script(
            linux_port_channel="po1910",
            port_channel="Port-Channel1910",
            num_subinterfaces=64,
            start_vlan=100,
            dut_host_octet=2,
            wait_attempts=600,
            wait_interval_seconds=2,
            setup_timeout_seconds=600,
        )

        self.assertIn("for attempt in {1..600}", script)
        self.assertIn("ip link show po1910", script)
        self.assertIn("/sys/class/net/po1910/operstate", script)
        self.assertIn(
            "timeout 600 bash /mnt/flash/setup_portchannel_subinterfaces.sh "
            "Port-Channel1910 64 100 2",
            script,
        )
        self.assertIn('ip link show "${interface}" | grep -q LOWER_UP', script)
        self.assertIn("scope global | grep -q 'inet6 '", script)
        self.assertIn(f"touch {_FIXTURE_READY}", script)
        self.assertNotIn("daemon Openr", script)

    async def test_setup_arms_dut_and_configures_both_devices(self) -> None:
        dut = _FakeDriver(rc_eos_exists=True)
        helper = _FakeDriver()
        with patch(
            f"{_MODULE}.async_get_device_driver",
            new=AsyncMock(side_effect=[dut, helper]),
        ):
            await OpenRScaleColdBootFixtureTask(logger=MagicMock()).run(
                _params("setup")
            )

        self.assertIn(_ORIGINAL_RC_EOS, dut.paths)
        self.assertIn(_ORIGINAL_OPENR_CONFIG, dut.paths)
        self.assertIn(_OPENR_CONFIG, dut.paths)
        self.assertIn(_RESTORE_SCRIPT, dut.paths)
        self.assertIn(_RC_EOS, dut.paths)
        self.assertTrue(
            any(
                "sed -E" in command and '"dryrun": false' in command
                for command in dut.commands
            )
        )
        self.assertFalse(any("jq" in command for command in dut.commands))
        self.assertTrue(
            any(
                "setup_portchannel_subinterfaces.sh Port-Channel1910 64 100 2"
                in command
                for command in dut.commands
            )
        )
        self.assertTrue(
            any(
                "setup_portchannel_subinterfaces.sh Port-Channel1910 64 100 1"
                in command
                for command in helper.commands
            )
        )

    async def test_cleanup_restores_rc_eos_and_cleans_both_devices(self) -> None:
        dut = _FakeDriver(rc_eos_exists=True)
        dut.paths.update(
            {
                _STATE_DIR,
                _OWNER_PATH,
                _ORIGINAL_RC_EOS,
                _ORIGINAL_OPENR_CONFIG,
                _OPENR_CONFIG_APPLIED,
            }
        )
        helper = _FakeDriver()
        set_increment = AsyncMock()
        remove_routes = AsyncMock(return_value=0)
        with (
            patch(
                f"{_MODULE}.async_get_device_driver",
                new=AsyncMock(side_effect=[dut, helper]),
            ),
            patch(f"{_MODULE}.set_link_metric_increment", new=set_increment),
            patch(
                f"{_MODULE}.get_link_metric_increments",
                new=AsyncMock(return_value={"po1910": 0, "po1910.100": 0}),
            ),
            patch(f"{_MODULE}.remove_leftover_openr_routes", new=remove_routes),
        ):
            await OpenRScaleColdBootFixtureTask(logger=MagicMock()).run(
                _params("cleanup")
            )

        # FIB programming was applied, so routes Open/R left behind are removed
        # once it is back in dryrun.
        remove_routes.assert_awaited_once_with(dut, "eb04.lab.ash6")

        set_increment.assert_awaited_once_with(
            "eb04.lab.ash6", [f"po1910.{vlan}" for vlan in range(100, 164)], 0
        )
        self.assertNotIn(_STATE_DIR, dut.paths)
        self.assertTrue(
            any(
                f"{_ORIGINAL_OPENR_CONFIG} /etc/openr_config" in command
                for command in dut.commands
            )
        )
        self.assertIn("daemon Openr\nshutdown", dut.commands)
        self.assertIn("daemon Openr\nno shutdown", dut.commands)
        self.assertTrue(
            any(
                f"cp -p {_ORIGINAL_RC_EOS} {_RC_EOS}" in command
                for command in dut.commands
            )
        )
        for driver in (dut, helper):
            self.assertTrue(
                any(
                    "cleanup_portchannel_subinterfaces.sh Port-Channel1910 64 100"
                    in command
                    for command in driver.commands
                )
            )

    async def _cleanup_with_increments(
        self, set_increment: AsyncMock, increments: dict[str, int]
    ) -> "_FakeDriver":
        remove_routes = AsyncMock(return_value=0)
        dut = _FakeDriver(rc_eos_exists=True)
        dut.paths.update(
            {_STATE_DIR, _OWNER_PATH, _ORIGINAL_RC_EOS, _ORIGINAL_OPENR_CONFIG}
        )
        with (
            patch(
                f"{_MODULE}.async_get_device_driver",
                new=AsyncMock(side_effect=[dut, _FakeDriver()]),
            ),
            patch(f"{_MODULE}.set_link_metric_increment", new=set_increment),
            patch(
                f"{_MODULE}.get_link_metric_increments",
                new=AsyncMock(return_value=increments),
            ),
            patch(f"{_MODULE}.remove_leftover_openr_routes", new=remove_routes),
        ):
            with self.assertRaisesRegex(RuntimeError, "link-metric increment"):
                await OpenRScaleColdBootFixtureTask(logger=MagicMock()).run(
                    _params("cleanup")
                )
        # FIB programming was never applied, so FibAgent is not touched.
        remove_routes.assert_not_awaited()
        return dut

    async def test_cleanup_fails_when_increment_clear_fails(self) -> None:
        dut = await self._cleanup_with_increments(
            AsyncMock(side_effect=ConnectionError("Open/R is down")), {}
        )
        # The rest of the cleanup still ran.
        self.assertNotIn(_STATE_DIR, dut.paths)

    async def test_cleanup_fails_on_leftover_increment(self) -> None:
        dut = await self._cleanup_with_increments(
            AsyncMock(), {"po1910.100": 1_000_000, "po1910.101": 0}
        )
        self.assertNotIn(_STATE_DIR, dut.paths)
