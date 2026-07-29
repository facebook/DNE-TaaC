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
from unittest.mock import AsyncMock, MagicMock

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

    async def test_intentional_restart_requires_both_snapshot_skips(self):
        pre = {_KEY: _session(uptime_seconds=6000, has_details=False)}
        post = {_KEY: _session(uptime_seconds=10, has_details=False)}

        uptime_only = await self._compare(
            pre,
            post,
            pre_ts=1000,
            post_ts=1001,
            skip_uptime_check=True,
        )
        both_skipped = await self._compare(
            pre,
            post,
            pre_ts=1000,
            post_ts=1001,
            skip_flap_check=True,
            skip_uptime_check=True,
        )

        self.assertEqual(uptime_only.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("Flapped", uptime_only.message)
        self.assertEqual(both_skipped.status, hc_types.HealthCheckStatus.PASS)

    async def test_restart_backstop_uptime_less_than_interval(self):
        """Flap counter unchanged and uptime did not decrease, but post uptime
        (50s) is less than the inter-snapshot interval (200s) -> the session
        could not have stayed up the whole window, so it reset -> FAIL."""
        pre = {_KEY: _session(uptime_seconds=10, num_of_flaps=0)}
        post = {_KEY: _session(uptime_seconds=50, num_of_flaps=0)}
        result = await self._compare(pre, post, pre_ts=1000, post_ts=1200)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("restarted", result.message)


_KEY2 = BgpSessionId(my_addr="10.0.0.1", peer_addr="10.0.0.3")


class TestBgpReconvergenceAssertion(unittest.IsolatedAsyncioTestCase):
    """The opt-in reconvergence-timing assertion (assert_reconvergence).

    convergence_sec = (post_ts - uptime) - restart_epoch; ALL pre-Established
    peers must be within max_convergence_sec. Anchored on the disrupted service's
    systemd ActiveEnterTimestamp, scoped to the disrupted device.
    """

    async def _compare(
        self,
        pre_data,
        post_data,
        post_ts,
        restart_epoch="1000",
        obj_name="gtsw001",
        **check_params,
    ):
        check = _make_check()
        check.driver = SimpleNamespace(
            async_run_cmd_on_shell=AsyncMock(return_value=restart_epoch)
        )
        return await check.compare_snapshots(
            obj=SimpleNamespace(name=obj_name),
            input=hc_types.BaseHealthCheckIn(),
            check_params={"assert_reconvergence": True, **check_params},
            pre_snapshot=Snapshot(timestamp=0, data=pre_data),
            post_snapshot=Snapshot(timestamp=post_ts, data=post_data),
        )

    async def test_all_peers_within_sla_pass(self):
        # restart_epoch=1000, post_ts=1080; uptime 30s -> established_at=1050 ->
        # convergence=50s <= 60s SLA for both peers -> PASS.
        pre = {_KEY: _session(6000), _KEY2: _session(6000)}
        post = {_KEY: _session(30), _KEY2: _session(30)}
        result = await self._compare(pre, post, post_ts=1080, max_convergence_sec=60.0)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS, result.message)

    async def test_one_peer_exceeds_sla_fail(self):
        # _KEY2 uptime 10s -> established_at=1070 -> convergence=70s > 60s -> FAIL.
        pre = {_KEY: _session(6000), _KEY2: _session(6000)}
        post = {_KEY: _session(30), _KEY2: _session(10)}
        result = await self._compare(pre, post, post_ts=1080, max_convergence_sec=60.0)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL, result.message)
        self.assertIn("reconvergence SLA", result.message)

    async def test_scoped_out_device_skipped(self):
        # Even with a peer that would violate, a non-DUT device returns PASS.
        pre = {_KEY: _session(6000)}
        post = {_KEY: _session(10)}
        result = await self._compare(
            pre,
            post,
            post_ts=1080,
            obj_name="gtsw002",
            max_convergence_sec=60.0,
            reconvergence_hosts=["gtsw001"],
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS, result.message)
        self.assertIn("not the disrupted device", result.message)

    async def test_deleted_peer_still_fails_before_timing(self):
        # A pre-Established peer absent post -> the deleted-session check fires
        # (peer never re-established) regardless of timing.
        pre = {_KEY: _session(6000), _KEY2: _session(6000)}
        post = {_KEY: _session(30)}
        result = await self._compare(pre, post, post_ts=1080, max_convergence_sec=60.0)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL, result.message)
        self.assertIn("not present in post snapshot", result.message)

    async def test_restart_epoch_unknown_skips(self):
        pre = {_KEY: _session(6000)}
        post = {_KEY: _session(10)}
        result = await self._compare(
            pre, post, post_ts=1080, restart_epoch="", max_convergence_sec=60.0
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS, result.message)
        self.assertIn("skipping reconvergence", result.message)

    async def test_no_pre_peers_passes(self):
        # Only NEW peers post (none in pre) -> nothing in scope -> PASS.
        pre = {}
        post = {_KEY: _session(10)}
        result = await self._compare(pre, post, post_ts=1080, max_convergence_sec=60.0)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS, result.message)


if __name__ == "__main__":
    unittest.main()
