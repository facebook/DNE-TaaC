# Copyright (c) Meta Platforms, Inc. and affiliates.

import logging
from unittest.mock import AsyncMock, patch

from later.unittest import TestCase
from taac.driver.driver_constants import FbossSystemctlServiceName
from taac.driver.fboss_switch import FbossSwitch


class FbossSwitchTest(TestCase):
    async def test_multi_switch_agent_crash_kills_all_mnpu_units_together(
        self,
    ) -> None:
        switch = FbossSwitch("test-switch.example.com", logging.getLogger(__name__))

        with (
            patch(
                "neteng.test_infra.dne.taac.driver.drivers_common.get_smc_hosts",
                return_value=[switch.hostname],
            ),
            patch.object(
                switch,
                "async_is_multi_switch",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch.object(
                switch,
                "async_run_cmd_on_shell",
                new_callable=AsyncMock,
            ) as run_cmd_mock,
        ):
            await switch.async_crash_service(FbossSystemctlServiceName.AGENT)

        run_cmd_mock.assert_awaited_once_with(
            "systemctl kill --kill-who=main --signal=SIGKILL "
            "fboss_sw_agent.service fboss_hw_agent@0.service "
            "fboss_hw_agent@1.service"
        )
