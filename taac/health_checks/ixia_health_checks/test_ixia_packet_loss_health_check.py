# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""Unit tests for IxiaPacketLossHealthCheck.

Tests the synchronous verify_packet_loss_threshold() method (pure logic)
and the async _run() method (with mocked IXIA client).
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from neteng.netcastle.logger import ConsoleFileLogger
from taac.health_checks.ixia_health_checks.ixia_packet_loss_health_check import (
    IxiaPacketLossHealthCheck,
)
from taac.health_check.health_check import types as hc_types


def _make_stat(identifier, duration=0, frame_delta=0, percentage=0.0):
    return {
        "identifier": identifier,
        "packet_loss_duration": duration,
        "frame_delta": frame_delta,
        "packet_loss_percentage": percentage,
    }


class TestVerifyPacketLossThreshold(unittest.TestCase):
    """Tests for the synchronous verify_packet_loss_threshold method."""

    def setUp(self):
        self.logger = MagicMock(spec=ConsoleFileLogger)
        self.health_check = IxiaPacketLossHealthCheck(logger=self.logger)

    def test_no_loss_within_threshold_passes(self):
        """Zero packet loss with threshold=0 should produce no violations."""
        stats = [_make_stat("TRAFFIC_A", duration=0)]
        threshold = hc_types.PacketLossThreshold(
            names=["TRAFFIC_A"],
            str_value="0",
            metric=hc_types.PacketLossMetric.DURATION,
        )
        violations = self.health_check.verify_packet_loss_threshold(stats, threshold)
        self.assertEqual(len(violations), 0)

    def test_loss_exceeding_threshold_fails(self):
        """Packet loss above threshold should produce a violation."""
        stats = [_make_stat("TRAFFIC_A", duration=5.0)]
        threshold = hc_types.PacketLossThreshold(
            names=["TRAFFIC_A"],
            str_value="0",
            metric=hc_types.PacketLossMetric.DURATION,
        )
        violations = self.health_check.verify_packet_loss_threshold(stats, threshold)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].name, "TRAFFIC_A")

    def test_expect_packet_loss_no_loss_is_violation(self):
        """When expect_packet_loss=True, zero loss is a violation."""
        stats = [_make_stat("ROGUE_TRAFFIC", duration=0)]
        threshold = hc_types.PacketLossThreshold(
            names=["ROGUE_TRAFFIC"],
            expect_packet_loss=True,
        )
        violations = self.health_check.verify_packet_loss_threshold(stats, threshold)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].name, "ROGUE_TRAFFIC")

    def test_expect_packet_loss_with_loss_passes(self):
        """When expect_packet_loss=True, non-zero loss should pass."""
        stats = [_make_stat("ROGUE_TRAFFIC", duration=10.0)]
        threshold = hc_types.PacketLossThreshold(
            names=["ROGUE_TRAFFIC"],
            expect_packet_loss=True,
        )
        violations = self.health_check.verify_packet_loss_threshold(stats, threshold)
        self.assertEqual(len(violations), 0)

    def test_unmatched_identifier_ignored(self):
        """Stats for identifiers not in threshold.names should be skipped."""
        stats = [_make_stat("TRAFFIC_B", duration=100.0)]
        threshold = hc_types.PacketLossThreshold(
            names=["TRAFFIC_A"],
            str_value="0",
        )
        violations = self.health_check.verify_packet_loss_threshold(stats, threshold)
        self.assertEqual(len(violations), 0)

    def test_no_names_matches_all(self):
        """When threshold.names is empty, all identifiers should be checked."""
        stats = [
            _make_stat("TRAFFIC_A", duration=5.0),
            _make_stat("TRAFFIC_B", duration=0),
        ]
        threshold = hc_types.PacketLossThreshold(
            str_value="0",
            metric=hc_types.PacketLossMetric.DURATION,
        )
        violations = self.health_check.verify_packet_loss_threshold(stats, threshold)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].name, "TRAFFIC_A")

    def test_missing_metric_key_skipped(self):
        """Stats missing the metric key should be skipped with a log error."""
        stats = [
            {"identifier": "TRAFFIC_A"},
        ]
        threshold = hc_types.PacketLossThreshold(
            names=["TRAFFIC_A"],
            str_value="0",
            metric=hc_types.PacketLossMetric.DURATION,
        )
        violations = self.health_check.verify_packet_loss_threshold(stats, threshold)
        self.assertEqual(len(violations), 0)
        self.logger.error.assert_called()

    def test_percentage_metric(self):
        """Test using PERCENTAGE metric instead of DURATION."""
        stats = [_make_stat("TRAFFIC_A", percentage=2.5)]
        threshold = hc_types.PacketLossThreshold(
            names=["TRAFFIC_A"],
            str_value="1",
            metric=hc_types.PacketLossMetric.PERCENTAGE,
        )
        violations = self.health_check.verify_packet_loss_threshold(stats, threshold)
        self.assertEqual(len(violations), 1)

    def test_multiple_thresholds_multiple_stats(self):
        """Test with multiple traffic items, some passing and some failing."""
        stats = [
            _make_stat("GOOD", duration=0),
            _make_stat("BAD", duration=10.0),
        ]
        threshold = hc_types.PacketLossThreshold(
            names=["GOOD", "BAD"],
            str_value="0",
            metric=hc_types.PacketLossMetric.DURATION,
        )
        violations = self.health_check.verify_packet_loss_threshold(stats, threshold)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].name, "BAD")


class TestIxiaPacketLossRun(unittest.IsolatedAsyncioTestCase):
    """Tests for the async _run() method with mocked IXIA."""

    def setUp(self):
        self.logger = MagicMock(spec=ConsoleFileLogger)
        self.health_check = IxiaPacketLossHealthCheck(logger=self.logger)
        self.mock_ixia = MagicMock()

    async def test_no_traffic_items_returns_skip(self):
        """_run should return SKIP when no traffic items exist."""
        self.mock_ixia.has_traffic_items.return_value = False
        input_data = hc_types.IxiaPacketLossHealthCheckIn(
            thresholds=[hc_types.PacketLossThreshold(str_value="0")],
        )
        result = await self.health_check._run(self.mock_ixia, input_data, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.SKIP)
        self.assertIn("No traffic items", result.message)

    async def test_tracking_not_enabled_returns_skip(self):
        """_run should return SKIP when traffic tracking is not enabled."""
        self.mock_ixia.has_traffic_items.return_value = True
        mock_item = MagicMock()
        mock_item.Enabled = True
        mock_tracking = MagicMock()
        mock_tracking.find.return_value.TrackBy = []
        mock_item.Tracking = mock_tracking
        self.mock_ixia.get_traffic_items.return_value = [mock_item]

        input_data = hc_types.IxiaPacketLossHealthCheckIn(
            thresholds=[hc_types.PacketLossThreshold(str_value="0")],
        )
        result = await self.health_check._run(self.mock_ixia, input_data, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.SKIP)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.ixia_health_checks"
        ".ixia_packet_loss_health_check.async_everpaste_str",
        new_callable=AsyncMock,
        return_value="https://everpaste.test",
    )
    async def test_all_pass_returns_pass(self, mock_everpaste):
        """_run should return PASS when all traffic items are within threshold."""
        self.mock_ixia.has_traffic_items.return_value = True
        self.mock_ixia.traffic_items_start_time = 0
        self.mock_ixia.get_latest_stats.return_value = [
            _make_stat("TRAFFIC_A", duration=0),
        ]
        mock_item = MagicMock()
        mock_item.Enabled = True
        mock_tracking = MagicMock()
        mock_tracking.find.return_value.TrackBy = ["trackingenabled0"]
        mock_item.Tracking = mock_tracking
        self.mock_ixia.get_traffic_items.return_value = [mock_item]

        input_data = hc_types.IxiaPacketLossHealthCheckIn(
            thresholds=[
                hc_types.PacketLossThreshold(
                    names=["TRAFFIC_A"],
                    str_value="0",
                    metric=hc_types.PacketLossMetric.DURATION,
                )
            ],
            sleep_time=0,
        )
        result = await self.health_check._run(self.mock_ixia, input_data, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)


if __name__ == "__main__":
    unittest.main()
