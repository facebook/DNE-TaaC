# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from taac.constants import TestDevice
from taac.health_checks.device_health_checks.in_congestion_discard_health_check import (
    InCongestionDiscardHealthCheck,
)
from taac.utils.oss_taac_lib_utils import ConsoleFileLogger
from taac.health_check.health_check import types as hc_types


def _make_device(name="rtsw002.p001.f01.ash6", role="RTSW", os="FBOSS"):
    device = MagicMock(spec=TestDevice)
    device.name = name
    # TestDevice.attributes is an annotation-only dataclass field, so it is not
    # in dir(TestDevice) and a spec'd mock rejects reading it until it is set.
    device.attributes = MagicMock()
    device.attributes.role = role
    device.attributes.operating_system = os
    intf = MagicMock()
    intf.interface_name = "eth1/1/1"
    device.interfaces = [intf]
    return device


PORT_COUNTER = "eth1/1/1.in_congestion_discards.sum.60"
PG3_COUNTER = "eth1/1/1.in_congestion_discards.pg3.sum.60"


@patch(
    "neteng.test_infra.dne.taac.health_checks.device_health_checks.in_congestion_discard_health_check.async_everpaste_str",
    new_callable=AsyncMock,
    return_value="https://everpaste",
)
@patch(
    "neteng.test_infra.dne.taac.health_checks.device_health_checks.in_congestion_discard_health_check.async_get_fburl",
    new_callable=AsyncMock,
    return_value="https://fburl",
)
class TestInCongestionDiscardHealthCheck(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.logger = MagicMock(spec=ConsoleFileLogger)
        self.health_check = InCongestionDiscardHealthCheck(logger=self.logger)
        self.health_check.driver = AsyncMock()
        self.input = hc_types.BaseHealthCheckIn()

    def _fb303(self, counters):
        mock_client = AsyncMock()
        mock_client.getSelectedCounters = AsyncMock(return_value=counters)
        return patch(
            "neteng.test_infra.dne.taac.health_checks.device_health_checks."
            "in_congestion_discard_health_check.get_fb303_client",
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_client)),
        )

    async def test_fboss_reads_the_port_counter(self, _mock_fburl, _mock_everpaste):
        """in_congestion_discards is a port counter, not a per-queue one."""
        device = _make_device()
        with self._fb303({PORT_COUNTER: 0}):
            result = await self.health_check._run_fboss(device, self.input, {})
        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)

    async def test_fboss_nonzero_discards_returns_fail(
        self, _mock_fburl, _mock_everpaste
    ):
        device = _make_device()
        with self._fb303({PORT_COUNTER: 500}):
            result = await self.health_check._run_fboss(device, self.input, {})
        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("500", result.message)

    async def test_fboss_missing_counter_fails_instead_of_reading_zero(
        self, _mock_fburl, _mock_everpaste
    ):
        """The counter the check asks for was never exported.

        Defaulting it to 0 passed the check without observing any telemetry,
        which is the failure mode this asserts against.
        """
        device = _make_device()
        with self._fb303({}):
            result = await self.health_check._run_fboss(device, self.input, {})
        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn(PORT_COUNTER, result.message)

    async def test_fboss_checks_requested_priority_groups(
        self, _mock_fburl, _mock_everpaste
    ):
        device = _make_device()
        with self._fb303({PORT_COUNTER: 0, PG3_COUNTER: 7}):
            result = await self.health_check._run_fboss(
                device, self.input, {"priority_groups": [3]}
            )
        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("pg3", result.message)

    async def test_fboss_missing_priority_group_counter_fails(
        self, _mock_fburl, _mock_everpaste
    ):
        device = _make_device()
        with self._fb303({PORT_COUNTER: 0}):
            result = await self.health_check._run_fboss(
                device, self.input, {"priority_groups": [3]}
            )
        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn(PG3_COUNTER, result.message)

    async def test_fboss_client_exception_returns_error(
        self, _mock_fburl, _mock_everpaste
    ):
        device = _make_device()
        with patch(
            "neteng.test_infra.dne.taac.health_checks.device_health_checks."
            "in_congestion_discard_health_check.get_fb303_client",
            side_effect=Exception("timeout"),
        ):
            result = await self.health_check._run_fboss(device, self.input, {})
        self.assertEqual(hc_types.HealthCheckStatus.ERROR, result.status)
        self.assertIn("timeout", result.message)

    async def test_unknown_comparison_is_a_configuration_error(
        self, _mock_fburl, _mock_everpaste
    ):
        """A typo used to fall back to EQUAL_TO and invert the intent."""
        device = _make_device()
        with self._fb303({PORT_COUNTER: 0}):
            result = await self.health_check._run_fboss(
                device, self.input, {"comparison": "LESS_THAN_EQUAL"}
            )
        self.assertEqual(hc_types.HealthCheckStatus.ERROR, result.status)
        self.assertIn("LESS_THAN_EQUAL", result.message)

    async def test_between_comparison_is_rejected(self, _mock_fburl, _mock_everpaste):
        """BETWEEN has no second bound here; it must not read as healthy."""
        device = _make_device()
        with self._fb303({PORT_COUNTER: 0}):
            result = await self.health_check._run_fboss(
                device, self.input, {"comparison": "BETWEEN"}
            )
        self.assertEqual(hc_types.HealthCheckStatus.ERROR, result.status)

    async def test_custom_threshold(self, _mock_fburl, _mock_everpaste):
        device = _make_device()
        with self._fb303({PORT_COUNTER: 50}):
            result = await self.health_check._run_fboss(
                device,
                self.input,
                {"threshold": 100, "comparison": "LESS_THAN"},
            )
        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)

    async def test_eos_skips_rather_than_parsing_a_schema_eos_never_returns(
        self, _mock_fburl, _mock_everpaste
    ):
        """EOS has no equivalent ASIC counter.

        The previous implementation parsed a made-up schema and turned every
        absent field into 0, so it passed without reading anything.
        """
        device = _make_device(os="EOS")
        result = await self.health_check._run_arista(device, self.input, {})
        self.assertEqual(hc_types.HealthCheckStatus.SKIP, result.status)
        self.health_check.driver.async_execute_show_json_on_shell.assert_not_awaited()

    async def test_skip_unsupported_role(self, _mock_fburl, _mock_everpaste):
        device = _make_device(role="SSW")
        skip, _reason = await self.health_check.skip_check(device)
        self.assertTrue(skip)

    async def test_no_skip_supported_role(self, _mock_fburl, _mock_everpaste):
        device = _make_device(role="RDSW")
        skip, _reason = await self.health_check.skip_check(device)
        self.assertFalse(skip)
