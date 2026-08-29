# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""Unit tests for `EosOsUpgradeTask`.

The device-facing calls are mocked, so these cover the decision logic that a
lab run would otherwise only exercise destructively: which SWI and URL get
picked out of a netcode package, when the task refuses to reload, and the three
places it must fail loudly rather than leave a device on an unverified image
(md5 mismatch, wrong boot-config, wrong version after the reload).
"""

import typing as t
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import later.unittest
from taac.constants import TestCaseFailure
from taac.internal.tasks.eos_os_upgrade_task import (
    _select_swi,
    _select_url,
    EosOsUpgradeTask,
    ResolvedImage,
)


HOSTNAME = "cpr002.qzp1"
PACKAGE = "arista_eos_4.36.2f-dpe-ctnr"
IMAGE_FILE = "EOS64-4.36.2F-DPE-CTNR.swi"
IMAGE_URL = f"https://netcode.any.fbinfra.net/dl/image/{PACKAGE}/{IMAGE_FILE}"
IMAGE_MD5 = "354df7fd4286182550e1958b45e95504"
OLD_VERSION = "4.35.2FX-R4.2"
NEW_VERSION = "4.36.2F-DPE-CTNR"
BOOT_FILE = f"flash:/{IMAGE_FILE}"
FLASH_PATH = f"/mnt/flash/{IMAGE_FILE}"

RESOLVED = ResolvedImage(
    package=PACKAGE,
    file_name=IMAGE_FILE,
    url=IMAGE_URL,
    md5=IMAGE_MD5,
    version=NEW_VERSION,
)

_MODULE = "neteng.test_infra.dne.taac.internal.tasks.eos_os_upgrade_task"


class TaskRegistrationTest(unittest.TestCase):
    def test_task_is_resolvable_by_name(self) -> None:
        """A playbook reaches this task by string, so the mapping must exist."""
        from taac.tasks.registry import TASK_NAME_TO_CLASS

        self.assertIs(TASK_NAME_TO_CLASS["eos_os_upgrade"], EosOsUpgradeTask)


class SelectSwiTest(unittest.TestCase):
    def test_picks_the_only_swi(self) -> None:
        files = ["README.txt", IMAGE_FILE]
        self.assertEqual(_select_swi(PACKAGE, files), IMAGE_FILE)

    def test_rejects_a_package_with_no_swi(self) -> None:
        with self.assertRaises(ValueError):
            _select_swi(PACKAGE, ["notes.md"])

    def test_rejects_an_ambiguous_package(self) -> None:
        with self.assertRaises(ValueError):
            _select_swi(PACKAGE, ["a.swi", "b.swi"])


class SelectUrlTest(unittest.TestCase):
    def test_prefers_the_url_matching_the_file(self) -> None:
        urls = [
            "https://netcode.any.fbinfra.net/dl/image/pkg/OTHER.swi",
            IMAGE_URL,
        ]
        self.assertEqual(_select_url(PACKAGE, urls, IMAGE_FILE), IMAGE_URL)

    def test_ignores_non_https_urls(self) -> None:
        urls = [
            f"http://netcode.any.fbinfra.net/dl/image/{PACKAGE}/{IMAGE_FILE}",
            f"sftp://netcode.any.fbinfra.net/image/{PACKAGE}/{IMAGE_FILE}",
            IMAGE_URL,
        ]
        self.assertEqual(_select_url(PACKAGE, urls, IMAGE_FILE), IMAGE_URL)

    def test_rejects_a_package_with_no_https_url(self) -> None:
        with self.assertRaises(ValueError):
            _select_url(PACKAGE, ["sftp://host/x.swi"], IMAGE_FILE)


def _driver(
    versions: t.Sequence[t.Dict[str, str]],
    md5: str = IMAGE_MD5,
    boot_file: str = BOOT_FILE,
    failing_namespaces: t.Optional[t.Set[str]] = None,
) -> MagicMock:
    """Build an AristaSwitch-shaped mock that routes on the command string."""
    failing_namespaces = failing_namespaces or set()
    downloaded: t.Dict[str, bool] = {"done": False}
    # Number of liveness probes that should fail after a reload is issued, so
    # the task sees the device go away and then come back.
    state: t.Dict[str, int] = {"down_probes": 0}

    async def run_cmd(cmd: str, *args: object, **kwargs: object) -> str:
        if cmd.startswith("show clock"):
            if state["down_probes"] > 0:
                state["down_probes"] -= 1
                raise RuntimeError("device is rebooting")
            return "clock"
        if "wget" in cmd:
            for namespace in failing_namespaces:
                if f"netns exec {namespace} " in cmd:
                    raise RuntimeError(f"wget failed in {namespace}")
            downloaded["done"] = True
            return ""
        if cmd.startswith("bash find "):
            return FLASH_PATH if downloaded["done"] else ""
        if cmd.startswith("verify /md5"):
            # Not a hash choice: this fakes the output of the EOS `verify /md5`
            # CLI command, and MD5 is what netcode publishes per file.
            # patternlint-disable-next-line poor-choice-of-hash-function
            return f"verify /md5 (file:{FLASH_PATH}) = {md5}"
        return ""

    async def reboot() -> None:
        # After a reload the device must stop answering at least once, so the
        # task's down-detection has something real to observe.
        state["down_probes"] = 1

    driver = MagicMock()
    driver.async_show_version = AsyncMock(side_effect=list(versions))
    driver.async_run_cmd_on_shell = AsyncMock(side_effect=run_cmd)
    driver.async_execute_show_json_on_shell = AsyncMock(
        return_value={"softwareImage": boot_file}
    )
    driver.async_full_system_reboot = AsyncMock(side_effect=reboot)
    driver.wait_for_agent_warmup = AsyncMock()
    return driver


class EosOsUpgradeTaskTest(later.unittest.TestCase):
    def setUp(self) -> None:
        # Patched in `_patches` so no test ever waits out the real post-reload
        # settle (180s by default) or a poll interval.
        self.sleep_mock = AsyncMock()
        self.task = EosOsUpgradeTask(hostname=HOSTNAME, logger=MagicMock())
        self.params: t.Dict[str, t.Any] = {
            "device_name": HOSTNAME,
            "netcode_package": PACKAGE,
        }

    def _patches(self, driver: MagicMock) -> t.List[t.Any]:
        return [
            patch(
                f"{_MODULE}.async_resolve_netcode_image",
                AsyncMock(return_value=RESOLVED),
            ),
            patch(f"{_MODULE}.async_get_device_driver", AsyncMock(return_value=driver)),
            patch(f"{_MODULE}.asyncio.sleep", self.sleep_mock),
        ]

    async def _run(self, driver: MagicMock, **overrides: object) -> None:
        params = {**self.params, **overrides}
        patches = self._patches(driver)
        for p in patches:
            p.start()
        try:
            await self.task.run(params)
        finally:
            for p in patches:
                p.stop()

    async def test_upgrades_and_verifies_the_new_version(self) -> None:
        driver = _driver([{"version": OLD_VERSION}, {"version": NEW_VERSION}])
        await self._run(driver)

        driver.async_full_system_reboot.assert_awaited_once()
        driver.wait_for_agent_warmup.assert_awaited_once()
        commands = [c.args[0] for c in driver.async_run_cmd_on_shell.await_args_list]
        self.assertTrue(any("rm -rf" in c for c in commands), commands)
        self.assertTrue(any("wget" in c for c in commands), commands)
        self.assertTrue(any(c.startswith("verify /md5") for c in commands), commands)
        self.assertTrue(any(f"SWI={BOOT_FILE}" in c for c in commands), commands)

    async def test_skips_when_already_on_the_target_version(self) -> None:
        driver = _driver([{"version": NEW_VERSION}])
        await self._run(driver)

        driver.async_full_system_reboot.assert_not_awaited()
        driver.async_run_cmd_on_shell.assert_not_awaited()

    async def test_fails_when_already_current_and_skip_is_disabled(self) -> None:
        driver = _driver([{"version": NEW_VERSION}])
        with self.assertRaises(TestCaseFailure):
            await self._run(driver, skip_if_current=False)
        driver.async_full_system_reboot.assert_not_awaited()

    async def test_falls_back_to_the_default_namespace(self) -> None:
        driver = _driver(
            [{"version": OLD_VERSION}, {"version": NEW_VERSION}],
            failing_namespaces={"ns-management"},
        )
        await self._run(driver)

        wgets = [
            c.args[0]
            for c in driver.async_run_cmd_on_shell.await_args_list
            if "wget" in c.args[0]
        ]
        self.assertEqual(len(wgets), 2, wgets)
        self.assertIn("netns exec ns-management ", wgets[0])
        self.assertIn("netns exec default ", wgets[1])
        driver.async_full_system_reboot.assert_awaited_once()

    async def test_settles_after_warmup_before_returning(self) -> None:
        """`wait-for-warmup` returns before a chassis' linecards are ready."""
        driver = _driver([{"version": OLD_VERSION}, {"version": NEW_VERSION}])
        await self._run(driver, post_reload_settle_s=42)
        self.assertIn(42, [c.args[0] for c in self.sleep_mock.await_args_list])

    async def test_settle_can_be_disabled(self) -> None:
        driver = _driver([{"version": OLD_VERSION}, {"version": NEW_VERSION}])
        await self._run(driver, post_reload_settle_s=0)
        self.assertNotIn(0, [c.args[0] for c in self.sleep_mock.await_args_list])

    async def test_rejects_a_negative_settle(self) -> None:
        driver = _driver([{"version": OLD_VERSION}])
        with self.assertRaises(ValueError):
            await self._run(driver, post_reload_settle_s=-1)

    async def test_stop_after_download_leaves_boot_behaviour_untouched(self) -> None:
        """The safe hardware-validation mode: download + verify, change nothing."""
        driver = _driver([{"version": OLD_VERSION}])
        await self._run(driver, stop_after_download=True)

        commands = [c.args[0] for c in driver.async_run_cmd_on_shell.await_args_list]
        self.assertTrue(any("wget" in c for c in commands), commands)
        self.assertTrue(any(c.startswith("verify /md5") for c in commands), commands)
        # No boot-config write, no read-back, no reload.
        self.assertFalse(any("SWI=" in c for c in commands), commands)
        driver.async_execute_show_json_on_shell.assert_not_awaited()
        driver.async_full_system_reboot.assert_not_awaited()
        driver.wait_for_agent_warmup.assert_not_awaited()

    async def test_fails_on_md5_mismatch_without_rebooting(self) -> None:
        driver = _driver(
            [{"version": OLD_VERSION}], md5="00000000000000000000000000000000"
        )
        with self.assertRaises(TestCaseFailure):
            await self._run(driver)
        driver.async_full_system_reboot.assert_not_awaited()

    async def test_fails_on_wrong_boot_config_without_rebooting(self) -> None:
        driver = _driver([{"version": OLD_VERSION}], boot_file="flash:/SOMETHING.swi")
        with self.assertRaises(TestCaseFailure):
            await self._run(driver)
        driver.async_full_system_reboot.assert_not_awaited()

    async def test_fails_when_the_device_comes_back_on_the_old_version(self) -> None:
        driver = _driver([{"version": OLD_VERSION}, {"version": OLD_VERSION}])
        with self.assertRaises(TestCaseFailure):
            await self._run(driver)
        driver.async_full_system_reboot.assert_awaited_once()

    async def test_requires_a_task_id_when_draining(self) -> None:
        driver = _driver([{"version": OLD_VERSION}, {"version": NEW_VERSION}])
        with self.assertRaises(ValueError):
            await self._run(driver, drain=True)

    async def test_requires_a_netcode_package(self) -> None:
        driver = _driver([{"version": OLD_VERSION}])
        self.params.pop("netcode_package")
        with self.assertRaises(ValueError):
            await self._run(driver)
