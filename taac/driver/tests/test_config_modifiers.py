# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import logging
import typing as t

# IsolatedAsyncioTestCase, not later.unittest.TestCase: ShipIt exports
# driver/tests/ to the OSS repo (unlike libs/tests/ and utils/tests/, which are
# stripped) and github/conftest.py collects it, but `later` is Meta-internal and
# absent from the OSS requirements -- importing it would fail collection for the
# whole OSS suite. The two driver tests already shipping use stdlib unittest for
# the same reason.
from unittest import IsolatedAsyncioTestCase as TestCase
from unittest.mock import AsyncMock, patch

from taac.driver.abstract_switch import AbstractSwitch
from taac.driver.config_modifiers import (
    _FILE_EXISTS_SENTINEL as FILE_EXISTS_SENTINEL,
    _HIDDEN_STARTUP_CONFIG_SYMLINK as HIDDEN_SYMLINK,
    ConfigModifierError,
    drain_device,
    LIVE_CONFIG_PATH,
    MARKER_SOFT_DRAINED,
    MARKER_UNDRAINED,
    SOFTDRAIN_CONFIG_PATH,
    STARTUP_CONFIG_SYMLINK,
    undrain_device,
)
from taac.driver.driver_constants import FbossSystemctlServiceName

_MODULE = "neteng.test_infra.dne.taac.driver.config_modifiers"


class _Device:
    """The slice of on-device state drain/undrain can observe or change.

    Modelling the symlink instead of stubbing ``readlink`` means the verification
    step in ``_apply_drain_state`` reads back the value the ``ln -sfn`` command
    actually set, so ``symlink_after_restart`` can emulate an on-device selector
    clobbering it.
    """

    def __init__(self) -> None:
        self.commands: list[str] = []
        self.restarted_services: list[FbossSystemctlServiceName] = []
        self.existing_files: set[str] = {LIVE_CONFIG_PATH, SOFTDRAIN_CONFIG_PATH}
        self.symlink_target: str = ""
        # Set to a path to emulate an ExecStartPre config_selector repointing the
        # symlink during the bgpd restart.
        self.symlink_after_restart: str | None = None

    @property
    def mutating_commands(self) -> list[str]:
        """Commands that change device state, i.e. everything but the probes."""
        return [c for c in self.commands if not c.startswith(("test -f ", "readlink "))]

    def command_containing(self, needle: str) -> str:
        matches = [c for c in self.commands if needle in c]
        assert len(matches) == 1, f"expected exactly one {needle!r} cmd, got {matches}"
        return matches[0]

    async def run_cmd(self, cmd: str, *args, **kwargs) -> str:
        self.commands.append(cmd)
        # Paths are interpolated unquoted (they are module constants with no shell
        # metacharacters), so a plain split recovers the argv.
        if cmd.startswith("test -f "):
            # "test -f <path> && echo <sentinel> || true"
            path = cmd.split()[2]
            return f"{FILE_EXISTS_SENTINEL}\n" if path in self.existing_files else "\n"
        if cmd.startswith("readlink "):
            return f"{self.symlink_target}\n"
        if cmd.startswith("ln -sfn "):
            # "ln -sfn <target> <staging> && mv -Tf <staging> <link>"
            self.symlink_target = cmd.split()[2]
        return ""

    async def restart_service(self, service, agents=None) -> None:
        self.restarted_services.append(service)
        if self.symlink_after_restart is not None:
            self.symlink_target = self.symlink_after_restart


def _make_switch(device: _Device) -> AbstractSwitch:
    """Build a driver double wired to ``device``.

    ``spec=AbstractSwitch`` does the work a hand-written subclass otherwise
    would: it satisfies ``isinstance``, auto-provides every method on the ABC so
    none need stubbing, and still raises AttributeError on a typo'd member. The
    ABC cannot be instantiated directly -- it has 18 abstract methods.
    """
    switch = AsyncMock(spec=AbstractSwitch)
    # hostname/logger are set in AbstractSwitch.__init__, so they are not part of
    # the class spec; plain `spec` (unlike `spec_set`) still allows setting them.
    switch.hostname = "test-switch"
    switch.logger = logging.getLogger("test_config_modifiers")
    switch.async_run_cmd_on_shell.side_effect = device.run_cmd
    switch.async_restart_service.side_effect = device.restart_service
    # AsyncMock is not nominally an AbstractSwitch even though spec= makes it one
    # at runtime; the cast keeps that fact in one place instead of at every call.
    return t.cast(AbstractSwitch, switch)


class DrainUndrainTest(TestCase):
    def setUp(self) -> None:
        self.device = _Device()
        self.switch = _make_switch(self.device)
        # The driver double is a spec'd mock, not a real FbossSwitch, so point the
        # FBOSS-driver check at its class. The check's own logic is covered by
        # FbossDeviceGuardTest below.
        guard = patch(f"{_MODULE}._fboss_switch_cls", return_value=type(self.switch))
        guard.start()
        self.addCleanup(guard.stop)

    def assert_restarted_bgpd(self, times: int) -> None:
        self.assertEqual(
            [FbossSystemctlServiceName.BGP] * times, self.device.restarted_services
        )

    async def test_drain_clears_undrained_before_setting_soft_drained(self) -> None:
        # The selector resolves UNDRAINED ahead of SOFT_DRAINED, so a drain that
        # sets its marker without clearing the opposite one silently stays live.
        await drain_device(self.switch)

        marker_cmd = self.device.command_containing(MARKER_SOFT_DRAINED)
        self.assertLess(
            marker_cmd.index(f"rm -f {MARKER_UNDRAINED}"),
            marker_cmd.index(f"touch {MARKER_SOFT_DRAINED}"),
        )

    async def test_undrain_clears_soft_drained_before_setting_undrained(self) -> None:
        await undrain_device(self.switch)

        marker_cmd = self.device.command_containing(MARKER_UNDRAINED)
        self.assertLess(
            marker_cmd.index(f"rm -f {MARKER_SOFT_DRAINED}"),
            marker_cmd.index(f"touch {MARKER_UNDRAINED}"),
        )

    async def test_markers_updated_in_a_single_invocation(self) -> None:
        # Two separate calls would leave a window where both or neither marker
        # exists, which the selector would resolve to the wrong config.
        await drain_device(self.switch)

        self.assertEqual(
            f"rm -f {MARKER_UNDRAINED} && touch {MARKER_SOFT_DRAINED}",
            self.device.command_containing("touch "),
        )

    async def test_drain_points_symlink_at_softdrain_config(self) -> None:
        await drain_device(self.switch)

        self.assertEqual(
            f"ln -sfn {SOFTDRAIN_CONFIG_PATH} {HIDDEN_SYMLINK} && "
            f"mv -Tf {HIDDEN_SYMLINK} {STARTUP_CONFIG_SYMLINK}",
            self.device.command_containing("ln -sfn"),
        )
        self.assertEqual(SOFTDRAIN_CONFIG_PATH, self.device.symlink_target)

    async def test_undrain_points_symlink_at_live_config(self) -> None:
        await undrain_device(self.switch)

        self.assertEqual(
            f"ln -sfn {LIVE_CONFIG_PATH} {HIDDEN_SYMLINK} && "
            f"mv -Tf {HIDDEN_SYMLINK} {STARTUP_CONFIG_SYMLINK}",
            self.device.command_containing("ln -sfn"),
        )
        self.assertEqual(LIVE_CONFIG_PATH, self.device.symlink_target)

    async def test_symlink_swap_is_atomic_rename_not_unlink_relink(self) -> None:
        # `ln -sf` on its own unlinks the destination before recreating it, which
        # leaves a window where bgpd could read a missing symlink. Staging plus
        # `mv -T` (rename(2)) closes it -- same idiom fboss_config_selector uses.
        await drain_device(self.switch)

        symlink_cmd = self.device.command_containing("ln -sfn")
        self.assertIn(f"mv -Tf {HIDDEN_SYMLINK} {STARTUP_CONFIG_SYMLINK}", symlink_cmd)
        self.assertLess(symlink_cmd.index("ln -sfn"), symlink_cmd.index("mv -Tf"))

    async def test_restarts_bgpd_once(self) -> None:
        await drain_device(self.switch)

        self.assert_restarted_bgpd(1)

    async def test_restart_bgp_false_skips_restart_only(self) -> None:
        await drain_device(self.switch, restart_bgp=False)

        self.assert_restarted_bgpd(0)
        # Markers and symlink are still applied so a later restart picks them up.
        self.assertIn(
            f"touch {MARKER_SOFT_DRAINED}", self.device.command_containing("touch ")
        )
        self.assertEqual(SOFTDRAIN_CONFIG_PATH, self.device.symlink_target)

    async def test_missing_target_config_raises_before_touching_device(self) -> None:
        self.device.existing_files.remove(SOFTDRAIN_CONFIG_PATH)

        with self.assertRaises(ConfigModifierError) as ctx:
            await drain_device(self.switch)

        self.assertIn(SOFTDRAIN_CONFIG_PATH, str(ctx.exception))
        self.assertEqual([], self.device.mutating_commands)
        self.assert_restarted_bgpd(0)

    async def test_undrain_missing_live_config_raises(self) -> None:
        self.device.existing_files.remove(LIVE_CONFIG_PATH)

        with self.assertRaises(ConfigModifierError):
            await undrain_device(self.switch)

        self.assertEqual([], self.device.mutating_commands)

    async def test_symlink_clobbered_during_restart_raises(self) -> None:
        # Emulates an on-device config_selector re-deriving the symlink at bgpd
        # ExecStartPre and forcing the undrained config -- the drain did not
        # actually take effect, so this must not pass silently.
        self.device.symlink_after_restart = LIVE_CONFIG_PATH

        with self.assertRaises(ConfigModifierError) as ctx:
            await drain_device(self.switch)

        message = str(ctx.exception)
        self.assertIn(LIVE_CONFIG_PATH, message)
        self.assertIn(SOFTDRAIN_CONFIG_PATH, message)
        self.assertIn("drainable", message)

    async def test_missing_symlink_raises(self) -> None:
        self.device.symlink_after_restart = ""

        with self.assertRaises(ConfigModifierError) as ctx:
            await drain_device(self.switch)

        self.assertIn("<nothing>", str(ctx.exception))

    async def test_verification_reads_link_without_resolving_it(self) -> None:
        # readlink -f would follow the coop "current" symlink through to the
        # versioned file and never match the path we set.
        await drain_device(self.switch)

        self.assertEqual(
            f"readlink {STARTUP_CONFIG_SYMLINK}",
            self.device.command_containing("readlink"),
        )

    async def test_drain_undrain_round_trip_leaves_single_marker(self) -> None:
        for _ in range(3):
            await drain_device(self.switch)
            self.assertEqual(SOFTDRAIN_CONFIG_PATH, self.device.symlink_target)
            await undrain_device(self.switch)
            self.assertEqual(LIVE_CONFIG_PATH, self.device.symlink_target)

        self.assert_restarted_bgpd(6)


class FbossDeviceGuardTest(TestCase):
    """The FBOSS-only guard, exercised against the real _assert_fboss_device."""

    class _SomeOtherDriver:
        """Stands in for FbossSwitch so the driver double fails the check."""

    def setUp(self) -> None:
        self.device = _Device()
        self.switch = _make_switch(self.device)

    async def test_rejects_non_fboss_driver(self) -> None:
        # An Arista/Cisco driver would run these FBOSS-specific commands against a
        # device that has no /dev/shm/fboss markers and no bgpd systemd unit.
        with patch(f"{_MODULE}._fboss_switch_cls", return_value=self._SomeOtherDriver):
            with self.assertRaises(ConfigModifierError) as ctx:
                await drain_device(self.switch)

        self.assertIn("FbossSwitch", str(ctx.exception))

    async def test_guard_runs_before_any_device_command(self) -> None:
        with patch(f"{_MODULE}._fboss_switch_cls", return_value=self._SomeOtherDriver):
            with self.assertRaises(ConfigModifierError):
                await drain_device(self.switch)

        self.assertEqual([], self.device.commands)
        self.assertEqual([], self.device.restarted_services)

    def test_resolver_returns_the_real_fboss_switch(self) -> None:
        # The one line the patched tests above cannot cover.
        from taac.driver.config_modifiers import _fboss_switch_cls
        from taac.driver.fboss_switch import FbossSwitch

        self.assertIs(FbossSwitch, _fboss_switch_cls())
