# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""Tests for measuring expected restarts against a recorded restart time.

A service named in `expected_restarted_services` is skipped outright when the
caller has no completion timestamp for the intentional restart. When one is
supplied via `duration_since_restart`, the service is measured instead, so a
second restart after the intentional one is still reported.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock

from taac.constants import TestDevice
from taac.health_checks.device_health_checks.service_restart_health_check import (
    ServiceRestartHealthCheck,
)

_TEST_DURATION = 1800
_SINCE_RESTART = 300


class ServiceRestartExpectedWindowTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "test_device"
        self.check = ServiceRestartHealthCheck.__new__(ServiceRestartHealthCheck)
        self.check.logger = MagicMock()
        self.driver = AsyncMock()
        self.driver.async_is_netos = AsyncMock(return_value=False)
        self.check.driver = self.driver

    def _uptimes(self, **services: int) -> None:
        self.driver.get_agents_uptime = AsyncMock(return_value=dict(services))

    async def test_expected_service_skipped_without_restart_time(self) -> None:
        # uptime far below test_duration, but no recorded restart time
        self._uptimes(wedge_agent=60)
        failed, restarted = await self.check._check_services_uptime(
            self.device, ["wedge_agent"], _TEST_DURATION, ["wedge_agent"], None
        )
        self.assertEqual([], failed)
        self.assertEqual([], restarted)

    async def test_expected_service_consistent_with_restart_passes(self) -> None:
        # came up at the intentional restart and stayed up
        self._uptimes(wedge_agent=_SINCE_RESTART + 5)
        failed, restarted = await self.check._check_services_uptime(
            self.device,
            ["wedge_agent"],
            _TEST_DURATION,
            ["wedge_agent"],
            _SINCE_RESTART,
        )
        self.assertEqual([], failed)
        self.assertEqual([], restarted)

    async def test_second_restart_after_intentional_one_is_caught(self) -> None:
        # uptime younger than the intentional restart => it restarted again
        self._uptimes(wedge_agent=30)
        failed, restarted = await self.check._check_services_uptime(
            self.device,
            ["wedge_agent"],
            _TEST_DURATION,
            ["wedge_agent"],
            _SINCE_RESTART,
        )
        self.assertEqual([], failed)
        self.assertEqual(1, len(restarted))
        self.assertIn("wedge_agent", restarted[0])
        self.assertIn("after the intentional restart", restarted[0])

    async def test_unexpected_service_still_measured_against_test_duration(
        self,
    ) -> None:
        # bgpd is not in the expected set, so the restart-time window must not
        # excuse it
        self._uptimes(wedge_agent=_SINCE_RESTART + 5, bgpd=60)
        failed, restarted = await self.check._check_services_uptime(
            self.device,
            ["wedge_agent", "bgpd"],
            _TEST_DURATION,
            ["wedge_agent"],
            _SINCE_RESTART,
        )
        self.assertEqual([], failed)
        self.assertEqual(1, len(restarted))
        self.assertIn("bgpd", restarted[0])


class LagStressPlaybookScopesRestartCheckTest(unittest.TestCase):
    """The stress variants must keep a SERVICE_RESTART_CHECK, scoped to the
    patcher restart; the warmboot/coldboot variants must drop it."""

    @staticmethod
    def _restart_checks(playbook):
        from taac.health_check.health_check import types as hc_types

        skipped = set(playbook.postchecks_to_skip or [])
        return [
            c
            for c in (playbook.postchecks or [])
            if c.name == hc_types.CheckName.SERVICE_RESTART_CHECK
            and c.name not in skipped
        ]

    def _build(self, with_agent_restart: bool):
        from taac.playbooks.playbook_definitions import (
            create_lag_variable_minlink_flap_playbook,
            LinkFlapVariation,
        )

        return create_lag_variable_minlink_flap_playbook(
            playbook_name="pb",
            member_interfaces=["eth1/1/1", "eth1/4/1"],
            min_link_percentage=0.65,
            min_link_up_percentage=0.75,
            portchannel_name_map={"d": ["Port-Channel4008"]},
            variation=LinkFlapVariation.BELOW_MIN_CAPACITY,
            with_agent_restart=with_agent_restart,
            services_to_skip=["openr"],
        )

    def test_stress_variant_keeps_a_scoped_check(self) -> None:
        checks = self._restart_checks(self._build(with_agent_restart=False))
        self.assertEqual(1, len(checks), "stress variant must keep one check")
        payload = checks[0].check_params.json_params
        self.assertIn("expected_restarted_services", payload)
        jq = checks[0].check_params.jq_params
        self.assertEqual(".lag_patcher_restart_time", jq["restart_start_time"])

    def test_scoped_check_keeps_the_shared_service_exclusions(self) -> None:
        # Overriding the shared check by name drops its params, so the
        # exclusions must be re-supplied or the replacement fails on a service
        # the device does not deploy (openr on FX).
        checks = self._restart_checks(self._build(with_agent_restart=False))
        self.assertIn("openr", checks[0].check_params.json_params)

    def test_restart_variant_drops_the_check(self) -> None:
        from taac.health_check.health_check import types as hc_types

        pb = self._build(with_agent_restart=True)
        self.assertIn(
            hc_types.CheckName.SERVICE_RESTART_CHECK, pb.postchecks_to_skip or []
        )
        self.assertEqual([], self._restart_checks(pb))
