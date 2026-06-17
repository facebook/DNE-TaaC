# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""Unit tests for CoreDumpsHealthCheck (snapshot health check)."""

import unittest
from unittest.mock import AsyncMock, MagicMock

from neteng.netcastle.logger import ConsoleFileLogger
from taac.constants import TestDevice
from taac.health_checks.snapshot_health_checks.coredumps_health_check import (
    _format_core_dump_details,
    _parse_eos_core_dump_timestamp,
    CoreDumpsHealthCheck,
)
from taac.health_check.health_check import types as hc_types


class TestParseEosCoreDumpTimestamp(unittest.TestCase):
    """Tests for the EOS core dump timestamp parser."""

    def test_valid_core_dump_filename(self):
        """Valid EOS core dump filename should extract epoch."""
        result = _parse_eos_core_dump_timestamp("core.1234.1700000000.bgpd.gz")
        self.assertEqual(result, 1700000000)

    def test_invalid_filename_returns_current_time(self):
        """Non-matching filename should return current time (fallback)."""
        result = _parse_eos_core_dump_timestamp("not_a_core_dump.txt")
        self.assertIsInstance(result, int)
        self.assertGreater(result, 0)

    def test_missing_epoch_returns_current_time(self):
        """Filename without epoch field should return current time (fallback)."""
        result = _parse_eos_core_dump_timestamp("core.1234")
        self.assertIsInstance(result, int)
        self.assertGreater(result, 0)


class TestFormatCoreDumpDetails(unittest.TestCase):
    """Tests for core dump detail formatting."""

    def test_format_with_items(self):
        """Should format core dumps into readable string."""
        dumps = {"core.123.1700000000.bgpd.gz": 1700000000}
        result = _format_core_dump_details(dumps)
        self.assertIn("core.123", result)

    def test_format_empty_dict(self):
        """Empty dict should produce empty/minimal output."""
        result = _format_core_dump_details({})
        self.assertIsNotNone(result)


class TestCoreDumpsHealthCheck(unittest.IsolatedAsyncioTestCase):
    """Tests for the snapshot lifecycle (capture + compare)."""

    def setUp(self):
        self.logger = MagicMock(spec=ConsoleFileLogger)
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "rsw001.p001.f01.ash6"
        self.input = hc_types.BaseHealthCheckIn()
        self.timestamp = 1700000000
        self.health_check = CoreDumpsHealthCheck(
            obj=self.device,
            input=self.input,
            pre_snapshot_checkpoint_id="pre_checkpoint",
            post_snapshot_checkpoint_id="post_checkpoint",
            check_params={},
            logger=self.logger,
        )
        self.health_check.driver = AsyncMock()

    async def test_no_new_core_dumps_returns_pass(self):
        """No new core dumps between pre and post should PASS."""
        self.health_check._async_find_core_dumps = AsyncMock(
            return_value={"core.old.gz": 1699999000}
        )
        pre = await self.health_check.capture_pre_snapshot(
            self.device, self.input, {}, self.timestamp
        )
        self.health_check._async_find_core_dumps = AsyncMock(
            return_value={"core.old.gz": 1699999000}
        )
        post = await self.health_check.capture_post_snapshot(
            self.device, self.input, {}, self.timestamp + 100
        )
        result = await self.health_check.compare_snapshots(
            self.device, self.input, {}, pre, post
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_new_core_dump_returns_fail(self):
        """A new core dump in post should FAIL."""
        self.health_check._async_find_core_dumps = AsyncMock(return_value={})
        pre = await self.health_check.capture_pre_snapshot(
            self.device, self.input, {}, self.timestamp
        )
        self.health_check._async_find_core_dumps = AsyncMock(
            return_value={"core.999.1700000000.bgpd.gz": 1700000000}
        )
        post = await self.health_check.capture_post_snapshot(
            self.device, self.input, {}, self.timestamp + 100
        )
        result = await self.health_check.compare_snapshots(
            self.device, self.input, {}, pre, post
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("core", result.message.lower())


if __name__ == "__main__":
    unittest.main()
