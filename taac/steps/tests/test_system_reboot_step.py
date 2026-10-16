# Copyright (c) Meta Platforms, Inc. and affiliates.

import socket
import time
from unittest.mock import AsyncMock, MagicMock, patch

from later.unittest import TestCase
from taac.constants import (  # oss-rewrite (force ShipIt re-export to taac.* root)
    TestDevice,
    TestTopology,
)
from taac.libs.parameter_evaluator import ParameterEvaluator
from taac.steps import step_definitions
from taac.steps.step_definitions import SystemRebootStep
from taac.test_as_a_config import types as taac_types
from taac.utils import oss_driver_utils

_WEDGE_POWER = "/usr/local/bin/wedge_power.sh"


class SystemRebootStepBmcCommandTest(TestCase):
    def setUp(self) -> None:
        super().setUp()
        device = MagicMock(spec=TestDevice)
        device.name = "fsw001.p001.f01.snc1"
        device.attributes = MagicMock(
            operating_system="FBOSS",
            role="",
            device_name="fsw001",
            hardware="",
            ai_zone="",
        )
        self.step = SystemRebootStep(
            name="test_system_reboot",
            device=device,
            topology=MagicMock(spec=TestTopology),
            test_case_results=[],
            test_config=MagicMock(spec=taac_types.TestConfig),
            test_case_name="test_case",
            test_case_start_time=time.time(),
            parameter_evaluator=MagicMock(spec=ParameterEvaluator),
            step=MagicMock(spec=taac_types.Step),
        )
        self.step.driver = AsyncMock()
        bmc = patch.object(step_definitions, "run_bmc_cmd_hwcontrol")
        self.bmc_mock = bmc.start()
        self.addCleanup(bmc.stop)
        ping = patch.object(step_definitions, "wait_for_ping_reachable")
        self.up_wait = ping.start()
        self.addCleanup(ping.stop)
        # The OSS down-wait probes the device after a BMC reset: report it down.
        self.probe = MagicMock(return_value=False)
        self.sleep = AsyncMock()
        for p in (
            patch.object(
                step_definitions, "is_host_ping_reachable", self.probe, create=True
            ),
            patch.object(step_definitions.asyncio, "sleep", self.sleep),
        ):
            p.start()
            self.addCleanup(p.stop)

    async def _run(self, trigger: taac_types.SystemRebootTrigger) -> None:
        await self.step.run(taac_types.SystemRebootInput(trigger=trigger), {})

    async def test_bmc_power_reset_power_cycles_whole_system(self) -> None:
        await self._run(taac_types.SystemRebootTrigger.BMC_POWER_RESET)
        self.bmc_mock.assert_called_once_with(
            "fsw001.p001.f01.snc1", f"{_WEDGE_POWER} reset -s"
        )

    async def test_bmc_microserver_only_reset_resets_microserver(self) -> None:
        await self._run(taac_types.SystemRebootTrigger.BMC_MICROSERVER_ONLY_RESET)
        self.bmc_mock.assert_called_once_with(
            "fsw001.p001.f01.snc1", f"{_WEDGE_POWER} reset"
        )

    async def _run_down_wait(self) -> None:
        with patch.object(step_definitions, "TAAC_OSS", True):
            await self.step.run(
                taac_types.SystemRebootInput(
                    trigger=taac_types.SystemRebootTrigger.BMC_POWER_RESET
                ),
                {"reboot_down_timeout_s": 0},
            )

    async def test_device_never_down_raises(self) -> None:
        self.probe.return_value = True
        with self.assertRaisesRegex(RuntimeError, "never went down"):
            await self._run_down_wait()
        self.up_wait.assert_not_called()

    async def test_device_down_proceeds_to_up_wait(self) -> None:
        await self._run_down_wait()
        self.up_wait.assert_called_once()
        self.assertIs(self.up_wait.call_args.kwargs["use_ipv6"], True)

    async def test_one_lost_reply_is_not_down(self) -> None:
        """ping -c 5 -w 10 fails on a single dropped reply from a live device."""
        self.probe.side_effect = [False] + [True] * 10
        with self.assertRaisesRegex(RuntimeError, "never went down"):
            await self._run_down_wait()

    async def test_failed_probes_are_spaced_out(self) -> None:
        """An instant failure (DNS, no route) must not make 3 probes in a second."""
        await self._run_down_wait()
        self.assertEqual(
            [c.args for c in self.sleep.await_args_list].count((5,)),
            step_definitions._REBOOT_DOWN_CONSECUTIVE_PROBES - 1,
        )

    async def test_never_down_names_the_swallowed_bmc_error(self) -> None:
        self.probe.return_value = True
        self.bmc_mock.side_effect = RuntimeError("wedge_power.sh: not found")
        with self.assertRaisesRegex(RuntimeError, "wedge_power.sh: not found"):
            await self._run_down_wait()


class PingFamilyTest(TestCase):
    """On a management network with no IPv6, ``ping -6`` fails at once."""

    def _cmd(self, getaddrinfo: MagicMock) -> list[str]:
        with (
            patch.object(socket, "getaddrinfo", getaddrinfo),
            patch.object(
                oss_driver_utils.subprocess, "run", return_value=MagicMock(returncode=0)
            ) as run,
        ):
            oss_driver_utils.is_host_ping_reachable("dut1", use_ipv6=True)
        return run.call_args.args[0]

    def test_host_without_an_ipv6_address_is_pinged_over_ipv4(self) -> None:
        self.assertNotIn("-6", self._cmd(MagicMock(side_effect=socket.gaierror)))

    def test_ipv4_fallback_is_logged_once_per_host(self) -> None:
        oss_driver_utils._IPV4_FALLBACK_LOGGED.discard("dut1")
        log = MagicMock()
        with (
            patch.object(socket, "getaddrinfo", side_effect=socket.gaierror),
            patch.object(
                oss_driver_utils.subprocess, "run", return_value=MagicMock(returncode=0)
            ),
        ):
            for _ in range(3):
                oss_driver_utils.is_host_ping_reachable("dut1", ping_logger=log)
        self.assertEqual(log.info.call_count, 1)

    def test_host_with_an_ipv6_address_keeps_ipv6(self) -> None:
        self.assertIn("-6", self._cmd(MagicMock(return_value=[("addr",)])))
