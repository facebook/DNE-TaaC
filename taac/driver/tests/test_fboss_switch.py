# Copyright (c) Meta Platforms, Inc. and affiliates.

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch, PropertyMock

from later.unittest import TestCase
from taac.driver.driver_constants import FbossSystemctlServiceName
from taac.driver.fboss_switch import FbossSwitch


class FbossSwitchTest(TestCase):
    def setUp(self) -> None:
        self.switch = FbossSwitch(
            "test-switch.example.com", logging.getLogger(__name__)
        )

    async def test_agent_config_reload_uses_async_client(self) -> None:
        client = AsyncMock()
        client.__aenter__.return_value = client
        self.switch.async_wait_for_agent_state_configured = AsyncMock()

        with (
            patch(
                "neteng.test_infra.dne.taac.driver.drivers_common.get_smc_hosts",
                return_value=[self.switch.hostname],
            ),
            patch.object(
                FbossSwitch,
                "async_agent_client",
                new_callable=PropertyMock,
                return_value=client,
            ),
        ):
            await self.switch.async_agent_config_reload()

        client.reloadConfig.assert_awaited_once_with()
        self.switch.async_wait_for_agent_state_configured.assert_awaited_once_with()

    async def test_dump_transceiver_i2c_log_returns_every_result(self) -> None:
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.dumpTransceiverI2cLog.side_effect = ["first", "second"]
        self.switch.async_get_all_interfaces_info = AsyncMock(
            return_value={"eth1/1/1": object(), "eth1/2/1": object()}
        )
        self.switch.async_get_qsfp_client = AsyncMock(return_value=client)

        result = await self.switch.async_get_dump_transceiver_i2c_log()

        self.assertEqual(["first", "second"], result)

    async def test_start_all_bgp_sessions_uses_async_sleep(self) -> None:
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.getBgpSessions.return_value = [SimpleNamespace(peer_addr="2001:db8::1")]
        self.switch._get_bgp_client = AsyncMock(return_value=client)
        self.switch.async_count_established_bgp_sessions = AsyncMock(return_value=1)

        with patch(
            "neteng.test_infra.dne.taac.driver.fboss_switch.asyncio.sleep",
            new_callable=AsyncMock,
        ) as sleep:
            self.assertTrue(await self.switch.start_all_bgp_sessions())

        sleep.assert_awaited_once_with(1)

    async def test_multi_switch_agent_crash_kills_all_mnpu_units_together(
        self,
    ) -> None:
        switch = self.switch

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
            "pkill -9 -x fboss_sw_agent; pkill -9 -x fboss_hw_agent"
        )
