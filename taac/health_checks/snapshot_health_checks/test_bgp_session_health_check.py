# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""Unit tests for BgpSessionHealthCheck flap / reset detection.

Focus: the uptime handling in ``compare_snapshots``. A slow post-snapshot device
read makes the device-reported uptime arrive several seconds "newer" than the
snapshot timestamp; the old absolute ``abs(actual - expected) > UPTIME_TOLERANCE``
check turned that pure measurement skew into a spurious FAIL. These tests assert
that skew no longer fails the check while genuine resets are still caught.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from neteng.netcastle.logger import ConsoleFileLogger
from taac.constants import TestDevice
from taac.health_checks.constants import Snapshot
from taac.health_checks.snapshot_health_checks.bgp_session_health_check import (
    BgpSessionHealthCheck,
    BgpSessionId,
)
from taac.health_check.health_check import types as hc_types


_KEY = BgpSessionId(my_addr="10.0.0.1", peer_addr="10.0.0.2")


def _session(uptime_seconds: int, num_of_flaps: int = 0, has_details: bool = True):
    """Minimal stand-in for TBgpSession.

    ``compare_snapshots`` only reads ``.uptime`` (in milliseconds) and, when
    present, ``.details.num_of_flaps``. When ``has_details=False`` the flap check
    falls back to the uptime-decrease path instead of the flap-counter path.
    """
    details = SimpleNamespace(num_of_flaps=num_of_flaps) if has_details else None
    return SimpleNamespace(uptime=uptime_seconds * 1000, details=details)


def _make_check() -> BgpSessionHealthCheck:
    return BgpSessionHealthCheck(
        obj=MagicMock(spec=TestDevice),
        input=hc_types.BaseHealthCheckIn(),
        pre_snapshot_checkpoint_id="pre",
        post_snapshot_checkpoint_id="post",
        check_params={},
        logger=MagicMock(spec=ConsoleFileLogger),
    )


class TestBgpSessionUptimeCheck(unittest.IsolatedAsyncioTestCase):
    async def _compare(self, pre_data, post_data, pre_ts, post_ts, **check_params):
        check = _make_check()
        return await check.compare_snapshots(
            obj=MagicMock(spec=TestDevice),
            input=hc_types.BaseHealthCheckIn(),
            check_params=check_params,
            pre_snapshot=Snapshot(timestamp=pre_ts, data=pre_data),
            post_snapshot=Snapshot(timestamp=post_ts, data=post_data),
        )

    async def test_slow_post_capture_does_not_false_fail(self):
        """Healthy session whose post-snapshot uptime is HIGHER than the naive
        ``pre_uptime + elapsed`` — the signature of a slow post-snapshot device
        read. The removed abs()/UPTIME_TOLERANCE check failed this; must PASS."""
        pre = {_KEY: _session(uptime_seconds=6000, num_of_flaps=1)}
        # elapsed = 80s, but uptime grew by 92s -> +12s skew over "expected".
        post = {_KEY: _session(uptime_seconds=6092, num_of_flaps=1)}
        result = await self._compare(pre, post, pre_ts=1000, post_ts=1080)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS, result.message)

    async def test_healthy_session_passes(self):
        """Session stayed up: uptime grew by ~elapsed, no flaps -> PASS."""
        pre = {_KEY: _session(uptime_seconds=6000, num_of_flaps=0)}
        post = {_KEY: _session(uptime_seconds=6080, num_of_flaps=0)}
        result = await self._compare(pre, post, pre_ts=1000, post_ts=1080)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS, result.message)

    async def test_num_of_flaps_increase_detects_flap(self):
        """Flap counter advanced across the window -> FAIL."""
        pre = {_KEY: _session(uptime_seconds=6000, num_of_flaps=1)}
        post = {_KEY: _session(uptime_seconds=6080, num_of_flaps=2)}
        result = await self._compare(pre, post, pre_ts=1000, post_ts=1080)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("Flapped", result.message)

    async def test_uptime_decrease_detects_flap(self):
        """No flap-counter details available -> uptime going backwards is the
        flap signal -> FAIL."""
        pre = {_KEY: _session(uptime_seconds=6000, has_details=False)}
        post = {_KEY: _session(uptime_seconds=10, has_details=False)}
        result = await self._compare(pre, post, pre_ts=1000, post_ts=1001)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("Flapped", result.message)

    async def test_restart_backstop_uptime_less_than_interval(self):
        """Flap counter unchanged and uptime did not decrease, but post uptime
        (50s) is less than the inter-snapshot interval (200s) -> the session
        could not have stayed up the whole window, so it reset -> FAIL."""
        pre = {_KEY: _session(uptime_seconds=10, num_of_flaps=0)}
        post = {_KEY: _session(uptime_seconds=50, num_of_flaps=0)}
        result = await self._compare(pre, post, pre_ts=1000, post_ts=1200)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("restarted", result.message)


if __name__ == "__main__":
    unittest.main()
