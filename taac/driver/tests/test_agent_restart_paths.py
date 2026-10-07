#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Which agent restart path ``FbossSwitch.async_restart_service`` takes.

The split-agent warmboot orchestration is pure-OSS only. Internal runs and
``TAAC_OSS_META_INTERNAL=1`` runs restart the agent unit with
``systemctl restart``, retried, exactly as before split-agent support existed.
"""

import contextlib
import typing as t
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from taac.driver import fboss_switch
from taac.driver.driver_constants import FbossSystemctlServiceName
from taac.driver.fboss_switch import FbossSwitch
from taac.utils import oss_taac_lib_utils

# Matches the is_dne_test_device preprod allowlist, so the internal-mode SMC
# gate passes without a network lookup.
_HOSTNAME = "fa001-uu002.qzd1"


@contextlib.contextmanager
def _taac_env(taac_oss: bool, meta_internal: bool) -> t.Iterator[None]:
    """Drive the real gate through the module-level flags it reads."""
    with (
        patch.object(oss_taac_lib_utils, "TAAC_OSS", taac_oss),
        patch.object(oss_taac_lib_utils, "TAAC_OSS_META_INTERNAL", meta_internal),
    ):
        yield


class _RestartTestBase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.switch = FbossSwitch(_HOSTNAME, logger=MagicMock())
        self.run_cmd = AsyncMock(return_value="")
        self.switch.async_run_cmd_on_shell = self.run_cmd
        self.start_times = AsyncMock(side_effect=[100, 200])
        self.switch.async_get_service_monotonic_start_time = self.start_times
        self.split_restart = AsyncMock()
        self.switch.async_restart_split_agents = self.split_restart
        self.is_multi_switch = AsyncMock(return_value=True)
        self.switch.async_is_multi_switch = self.is_multi_switch
        sleep_patcher = patch.object(
            oss_taac_lib_utils.asyncio, "sleep", new_callable=AsyncMock
        )
        sleep_patcher.start()
        self.addCleanup(sleep_patcher.stop)

    def _restart_commands(self) -> t.List[str]:
        return [
            call.args[0]
            for call in self.run_cmd.await_args_list
            if call.args[0].startswith("systemctl restart")
        ]


class InternalAgentRestartTest(_RestartTestBase):
    """Every mode except pure OSS: the original systemctl restart path."""

    NON_OSS_MODES = (
        ("internal", False, False),
        ("containerized_meta_internal", True, True),
        ("meta_internal_flag_only", False, True),
    )

    async def test_agent_restart_uses_systemctl_on_a_multi_switch_dut(self) -> None:
        for label, taac_oss, meta_internal in self.NON_OSS_MODES:
            with self.subTest(mode=label), _taac_env(taac_oss, meta_internal):
                self.run_cmd.reset_mock()
                self.start_times.side_effect = [100, 200]
                self.split_restart.reset_mock()
                await self.switch.async_restart_service(FbossSystemctlServiceName.AGENT)
                self.assertEqual(
                    self._restart_commands(), ["systemctl restart wedge_agent"]
                )
                self.split_restart.assert_not_awaited()

    async def test_agent_restart_does_not_probe_multi_switch(self) -> None:
        """The pre-split path made no thrift call before restarting."""
        self.is_multi_switch.side_effect = AssertionError("must not probe")
        for label, taac_oss, meta_internal in self.NON_OSS_MODES:
            with self.subTest(mode=label), _taac_env(taac_oss, meta_internal):
                self.start_times.side_effect = [100, 200]
                await self.switch.async_restart_service(FbossSystemctlServiceName.AGENT)
        self.is_multi_switch.assert_not_awaited()

    async def test_agent_restart_is_retried(self) -> None:
        """A first attempt whose start time did not move is retried."""
        self.start_times.side_effect = [100, 100, 100, 200]
        with _taac_env(taac_oss=False, meta_internal=False):
            await self.switch.async_restart_service(FbossSystemctlServiceName.AGENT)
        self.assertEqual(
            self._restart_commands(),
            ["systemctl restart wedge_agent", "systemctl restart wedge_agent"],
        )

    async def test_agent_restart_fails_once_retries_are_exhausted(self) -> None:
        self.start_times.side_effect = None
        self.start_times.return_value = 100
        with _taac_env(taac_oss=False, meta_internal=False):
            with self.assertRaises(AssertionError):
                await self.switch.async_restart_service(FbossSystemctlServiceName.AGENT)
        self.assertGreater(len(self._restart_commands()), 1)
        self.split_restart.assert_not_awaited()

    async def test_split_agent_restart_is_also_a_plain_systemctl_restart(
        self,
    ) -> None:
        for service in (
            FbossSystemctlServiceName.FBOSS_SW_AGENT,
            FbossSystemctlServiceName.FBOSS_HW_AGENT_0,
        ):
            with self.subTest(service=service), _taac_env(False, False):
                self.run_cmd.reset_mock()
                self.start_times.side_effect = [100, 200]
                await self.switch.async_restart_service(service)
                self.assertEqual(
                    self._restart_commands(), [f"systemctl restart {service.value}"]
                )
        self.split_restart.assert_not_awaited()

    async def test_non_agent_service_restart_is_unchanged(self) -> None:
        with _taac_env(taac_oss=False, meta_internal=False):
            await self.switch.async_restart_service(FbossSystemctlServiceName.BGP)
        self.assertEqual(self._restart_commands(), ["systemctl restart bgpd"])
        self.split_restart.assert_not_awaited()


class PureOssAgentRestartTest(_RestartTestBase):
    """``TAAC_OSS=1`` without ``TAAC_OSS_META_INTERNAL``: the split-agent path."""

    async def test_agent_restart_uses_split_restart(self) -> None:
        with _taac_env(taac_oss=True, meta_internal=False):
            await self.switch.async_restart_service(FbossSystemctlServiceName.AGENT)
        self.split_restart.assert_awaited_once_with()
        self.assertEqual(self._restart_commands(), [])

    async def test_agent_restart_never_runs_systemctl_restart_wedge_agent(
        self,
    ) -> None:
        """OSS images have no wedge_agent unit, whatever the probe reports."""
        probe_outcomes = (
            ("multi_switch", AsyncMock(return_value=True)),
            ("not_multi_switch", AsyncMock(return_value=False)),
            ("probe_not_implemented", AsyncMock(side_effect=NotImplementedError)),
            ("agent_unreachable", AsyncMock(side_effect=ConnectionError("down"))),
        )
        for label, probe in probe_outcomes:
            with self.subTest(probe=label), _taac_env(True, False):
                self.split_restart.reset_mock()
                self.run_cmd.reset_mock()
                self.switch.async_is_multi_switch = probe
                await self.switch.async_restart_service(FbossSystemctlServiceName.AGENT)
                self.split_restart.assert_awaited_once_with()
                self.assertNotIn(
                    "systemctl restart wedge_agent", self._restart_commands()
                )

    async def test_agent_restart_does_not_probe_multi_switch(self) -> None:
        """The probe reports False when the agent is down, so it cannot gate this."""
        with _taac_env(taac_oss=True, meta_internal=False):
            await self.switch.async_restart_service(FbossSystemctlServiceName.AGENT)
        self.is_multi_switch.assert_not_awaited()

    async def test_split_restart_failure_is_not_retried(self) -> None:
        """A retry would restart from an already cold-booted hw agent."""
        self.split_restart.side_effect = Exception("warm boot did not hold")
        with _taac_env(taac_oss=True, meta_internal=False):
            with self.assertRaisesRegex(Exception, "warm boot did not hold"):
                await self.switch.async_restart_service(FbossSystemctlServiceName.AGENT)
        self.split_restart.assert_awaited_once()
        self.assertEqual(self._restart_commands(), [])

    async def test_non_agent_service_skips_the_multi_switch_probe(self) -> None:
        with _taac_env(taac_oss=True, meta_internal=False):
            await self.switch.async_restart_service(FbossSystemctlServiceName.BGP)
        self.assertEqual(self._restart_commands(), ["systemctl restart bgpd"])
        self.is_multi_switch.assert_not_awaited()
        self.split_restart.assert_not_awaited()

    async def test_a_single_split_agent_restart_uses_systemctl(self) -> None:
        with _taac_env(taac_oss=True, meta_internal=False):
            await self.switch.async_restart_service(
                FbossSystemctlServiceName.FBOSS_HW_AGENT_0
            )
        self.assertEqual(
            self._restart_commands(), ["systemctl restart fboss_hw_agent@0"]
        )
        self.split_restart.assert_not_awaited()


class ColdBootThenRestartTest(_RestartTestBase):
    """The flag-then-restart sequence callers such as the port-channel step use."""

    async def test_internal_cold_boot_writes_the_internal_flag_then_restarts(
        self,
    ) -> None:
        with _taac_env(taac_oss=True, meta_internal=True):
            await self.switch.async_create_cold_boot_file()
            await self.switch.async_restart_service(FbossSystemctlServiceName.AGENT)
        commands = [call.args[0] for call in self.run_cmd.await_args_list]
        self.assertEqual(
            commands,
            [
                "touch /dev/shm/fboss/warm_boot/cold_boot_once_0",
                "systemctl restart wedge_agent",
            ],
        )
        self.split_restart.assert_not_awaited()

    async def test_pure_oss_cold_boot_writes_per_agent_flags_then_split_restarts(
        self,
    ) -> None:
        self.switch.async_get_hw_agent_switch_indices = AsyncMock(return_value=[0])
        with _taac_env(taac_oss=True, meta_internal=False):
            await self.switch.async_create_cold_boot_file()
            await self.switch.async_restart_service(FbossSystemctlServiceName.AGENT)
        self.run_cmd.assert_awaited_once_with(
            "touch /dev/shm/fboss/warm_boot/sw_cold_boot_once "
            "/dev/shm/fboss/warm_boot/hw_cold_boot_once_0"
        )
        self.split_restart.assert_awaited_once()


class GateWiringTest(unittest.TestCase):
    def test_driver_reads_the_shared_gate(self) -> None:
        """A local copy of the flag would drift from the step's gate."""
        self.assertIs(
            fboss_switch.oss_agent_restart_paths_enabled,
            oss_taac_lib_utils.oss_agent_restart_paths_enabled,
        )
