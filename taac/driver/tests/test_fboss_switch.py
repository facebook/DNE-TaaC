# Copyright (c) Meta Platforms, Inc. and affiliates.

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, MagicMock, patch, PropertyMock

from later.unittest import TestCase
from neteng.fboss.ctrl.types import SwitchRunState
from taac.driver.driver_constants import FbossSystemctlServiceName
from taac.driver.fboss_switch import FbossSwitch
from taac.health_checks.device_health_checks.wedge_agent_configured_health_check import (
    WedgeAgentConfiguredHealthCheck,
)
from servicerouter.python.error import ServiceRouterError
from taac.health_check.health_check import types as hc_types
from thrift.python.exceptions import (
    ApplicationError,
    ApplicationErrorType,
    ApplicationOverloadError,
    TransportError,
    TransportErrorType,
)


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


class SwitchRunStateRetryTest(TestCase):
    def setUp(self) -> None:
        self.logger = MagicMock()
        self.switch = FbossSwitch("dut.example.com", self.logger)
        self.client = AsyncMock()
        self.client.__aenter__.return_value = self.client
        self.enterContext(
            patch.object(
                FbossSwitch,
                "async_agent_client",
                new_callable=PropertyMock,
                return_value=self.client,
            )
        )
        self.sleep = self.enterContext(
            patch(
                "neteng.test_infra.dne.taac.driver.fboss_switch.asyncio.sleep",
                new_callable=AsyncMock,
            )
        )
        self.jitter = self.enterContext(
            patch(
                "tenacity.wait.random.uniform",
                side_effect=lambda lower, upper: upper / 2,
            )
        )
        self.throttle = ServiceRouterError(
            TransportErrorType.UNKNOWN,
            "(APP_OVERLOAD) App Overloaded: ThriftMethoRateLimit",
            0,
            0,
        )

    async def test_success_needs_no_retry(self) -> None:
        self.client.getSwitchRunState.return_value = SwitchRunState.CONFIGURED

        result = await self.switch.async_get_switch_run_state()

        self.assertEqual(result, SwitchRunState.CONFIGURED)
        self.client.getSwitchRunState.assert_awaited_once_with()
        self.sleep.assert_not_awaited()
        self.jitter.assert_not_called()

    async def test_sr_throttling_recovers_with_backoff_and_jitter(self) -> None:
        self.client.getSwitchRunState.side_effect = [
            self.throttle,
            self.throttle,
            self.throttle,
            SwitchRunState.CONFIGURED,
        ]

        result = await self.switch.async_get_switch_run_state()

        self.assertEqual(result, SwitchRunState.CONFIGURED)
        self.assertEqual(self.client.getSwitchRunState.await_count, 4)
        self.assertEqual(self.client.__aexit__.await_count, 4)
        self.assertEqual(
            self.sleep.await_args_list, [call(1.05), call(2.05), call(4.05)]
        )
        self.assertIn("dut.example.com", self.logger.warning.call_args.args[0])
        self.assertIn("attempt 3/4", self.logger.warning.call_args.args[0])

    async def test_direct_thrift_throttling_recovers(self) -> None:
        self.client.getSwitchRunState.side_effect = [
            ApplicationOverloadError(
                "reject thrift methd due to rate limit: 3 for method: getSwitchRunState"
            ),
            SwitchRunState.CONFIGURED,
        ]

        result = await self.switch.async_get_switch_run_state()

        self.assertEqual(result, SwitchRunState.CONFIGURED)
        self.assertEqual(self.client.getSwitchRunState.await_count, 2)
        self.sleep.assert_awaited_once_with(1.05)

    async def test_exhaustion_preserves_original_throttle(self) -> None:
        self.client.getSwitchRunState.side_effect = self.throttle

        with self.assertRaises(ServiceRouterError) as raised:
            await self.switch.async_get_switch_run_state()

        self.assertIs(raised.exception, self.throttle)
        self.assertEqual(self.client.getSwitchRunState.await_count, 4)
        self.assertEqual(self.sleep.await_count, 3)

    async def test_repeated_calls_each_get_a_fresh_retry_budget(self) -> None:
        self.client.getSwitchRunState.side_effect = [
            self.throttle,
            SwitchRunState.CONFIGURED,
            self.throttle,
            SwitchRunState.CONFIGURED,
        ]

        first = await self.switch.async_get_switch_run_state()
        second = await self.switch.async_get_switch_run_state()

        self.assertEqual((first, second), (SwitchRunState.CONFIGURED,) * 2)
        self.assertEqual(self.client.getSwitchRunState.await_count, 4)
        self.assertEqual(self.sleep.await_args_list, [call(1.05), call(1.05)])

    async def test_other_errors_are_not_retried(self) -> None:
        errors = [
            ServiceRouterError(TransportErrorType.UNKNOWN, "APP_OVERLOAD", 0, 0),
            TransportError(TransportErrorType.TIMED_OUT, "timed out", 0, 0),
            ApplicationError(ApplicationErrorType.INTERNAL_ERROR, "handler failed"),
            ValueError("ThriftMethoRateLimit"),
        ]
        for error in errors:
            with self.subTest(error=error):
                self.client.getSwitchRunState.reset_mock(side_effect=True)
                self.client.getSwitchRunState.side_effect = error

                with self.assertRaises(type(error)) as raised:
                    await self.switch.async_get_switch_run_state()

                self.assertIs(raised.exception, error)
                self.client.getSwitchRunState.assert_awaited_once_with()
                self.sleep.assert_not_awaited()

    async def test_cancellation_during_backoff_stops_retries(self) -> None:
        self.client.getSwitchRunState.side_effect = self.throttle
        self.sleep.side_effect = asyncio.CancelledError

        with self.assertRaises(asyncio.CancelledError):
            await self.switch.async_get_switch_run_state()

        self.client.getSwitchRunState.assert_awaited_once_with()
        self.client.__aexit__.assert_awaited_once()

    async def test_recovered_read_still_fails_for_unconfigured_agent(self) -> None:
        self.client.getSwitchRunState.side_effect = [
            self.throttle,
            SwitchRunState.INITIALIZED,
        ]
        check = WedgeAgentConfiguredHealthCheck(logger=self.logger)
        check.driver = self.switch
        device = MagicMock()
        device.name = self.switch.hostname

        result = await check._run(device, hc_types.BaseHealthCheckIn(), {})

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("INITIALIZED", result.message or "")
        self.assertEqual(self.client.getSwitchRunState.await_count, 2)
        self.sleep.assert_awaited_once_with(1.05)
