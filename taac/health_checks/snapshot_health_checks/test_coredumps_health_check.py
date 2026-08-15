# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""Unit tests for CoreDumpsHealthCheck (snapshot health check)."""

import time
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


class EosCoreDumpSymlinkListingTest(unittest.IsolatedAsyncioTestCase):
    """`ls -ltr` on EOS /var/core mostly returns SYMLINKS into
    /mnt/flash/archive/current/var/core/, so the line ends "<name> -> <target>".

    Keying on the last token therefore recorded the TARGET path, which fails
    EOS_CORE_DUMP_FILENAME_REGEX, so the timestamp fell through to
    int(time.time()) and every rotated core was stamped with the snapshot time.
    Observed on bag013 release 191: 33 of 37 cores reported with a fabricated
    mtime and no process/pid, which is the exact evidence a new-vs-pre-existing
    triage relies on.
    """

    def setUp(self) -> None:
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "bag013.ash6"
        self.check = CoreDumpsHealthCheck(
            obj=self.device,
            input=hc_types.BaseHealthCheckIn(),
            pre_snapshot_checkpoint_id="pre_checkpoint",
            post_snapshot_checkpoint_id="post_checkpoint",
            check_params={},
            logger=MagicMock(spec=ConsoleFileLogger),
        )
        # Held as an AsyncMock-typed local: ``check.driver`` is initialised to
        # ``...`` on the abstract base, so pyre resolves it to EllipsisType and
        # assignments reached through it do not type-check.
        self.driver = AsyncMock()
        self.check.driver = self.driver

    def _set_listing(self, output: str) -> None:
        self.driver.async_execute_show_or_configure_cmd_on_shell = AsyncMock(
            return_value=output
        )

    async def test_symlinked_core_is_keyed_by_name_with_real_timestamp(self) -> None:
        self._set_listing(
            "total 4\n"
            "lrwxrwxrwx 1 root root 65 Aug 10 22:48 core.4777.1786427296.openr.gz "
            "-> /mnt/flash/archive/current/var/core/core.4777.1786427296.openr.gz\n"
        )

        cores = await self.check._async_find_all_eos_core_dumps(self.device)

        self.assertEqual({"core.4777.1786427296.openr.gz": 1786427296}, cores)

    async def test_regular_file_still_parses(self) -> None:
        self._set_listing(
            "total 4\n"
            "-rw-r--r-- 1 root root 5285765 Aug 10 23:12 "
            "core.16917.1786428752.openr.gz\n"
        )

        cores = await self.check._async_find_all_eos_core_dumps(self.device)

        self.assertEqual({"core.16917.1786428752.openr.gz": 1786428752}, cores)

    async def test_symlink_and_plain_file_collapse_to_one_key(self) -> None:
        """A core seen as a symlink in one snapshot and a plain file in another
        must not read as two different cores, or a rotation looks like a crash."""
        self._set_listing(
            "lrwxrwxrwx 1 root root 65 Aug 10 22:48 core.4777.1786427296.openr.gz "
            "-> /mnt/flash/archive/current/var/core/core.4777.1786427296.openr.gz\n"
            "-rw-r--r-- 1 root root 5285765 Aug 10 22:48 core.4777.1786427296.openr.gz\n"
        )

        cores = await self.check._async_find_all_eos_core_dumps(self.device)

        self.assertEqual(1, len(cores))
        self.assertIn("core.4777.1786427296.openr.gz", cores)

    async def test_timestamp_is_not_snapshot_time(self) -> None:
        """Regression guard: the embedded epoch must win over time.time()."""
        self._set_listing(
            "lrwxrwxrwx 1 root root 70 Aug 10 22:46 "
            "core.2414.1786419453.FbConfigAgent.gz "
            "-> /mnt/flash/archive/current/var/core/core.2414.1786419453."
            "FbConfigAgent.gz\n"
        )

        cores = await self.check._async_find_all_eos_core_dumps(self.device)

        self.assertEqual(1786419453, cores["core.2414.1786419453.FbConfigAgent.gz"])
        self.assertLess(
            cores["core.2414.1786419453.FbConfigAgent.gz"], int(time.time())
        )


if __name__ == "__main__":
    unittest.main()
