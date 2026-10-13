# Copyright (c) Meta Platforms, Inc. and affiliates.

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
        ping.start()
        self.addCleanup(ping.stop)

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
