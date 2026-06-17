# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""Unit tests for CpuQueueHealthCheck (snapshot health check) and its factory.

Covers the A2 leakage expansion of `create_cpu_queue_snapshot_check`
(new `inactive_queues` + `inactive_max_pps_per_queue` params) and the
underlying check's compare_snapshots assertions on active / inactive /
no_discard queues.
"""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from neteng.netcastle.logger import ConsoleFileLogger
from taac.constants import TestDevice
from taac.health_checks.constants import Snapshot
from taac.health_checks.healthcheck_definitions import (
    create_cpu_queue_snapshot_check,
)
from taac.health_checks.snapshot_health_checks.cpu_queue_health_check import (
    CpuQueueHealthCheck,
)
from taac.health_check.health_check import types as hc_types

# Module path used to patch the network-bound everpaste helpers that
# `compare_snapshots` calls on failure paths. With `network_access = none()`
# the real implementations would try to reach interngraph and fail.
_HC_MODULE = (
    "neteng.test_infra.dne.taac.health_checks.snapshot_health_checks."
    "cpu_queue_health_check"
)


def _make_stats_snapshot(
    out_packets_per_queue: dict,
    discard_packets_per_queue: dict,
    timestamp: int,
) -> Snapshot:
    """Build a Snapshot whose .data.portStats_.queueOut(Discard)Packets_ are dicts."""
    port_stats = MagicMock()
    port_stats.queueOutPackets_ = dict(out_packets_per_queue)
    port_stats.queueOutDiscardPackets_ = dict(discard_packets_per_queue)
    data = MagicMock()
    data.portStats_ = port_stats
    return Snapshot(data=data, timestamp=timestamp)


class TestCreateCpuQueueSnapshotCheckFactory(unittest.TestCase):
    """Factory-level tests for `create_cpu_queue_snapshot_check`."""

    def _payload(self, hc) -> dict:
        return json.loads(hc.input_json)

    def test_default_no_inactive_params_preserved(self):
        hc = create_cpu_queue_snapshot_check(
            active_queues=[2],
            no_discard_queues=[2, 9],
            active_min_out_pps_per_queue={0: 10},
        )
        payload = self._payload(hc)
        self.assertEqual(payload["active_queues"], [2])
        self.assertEqual(payload["no_discard_queues"], [2, 9])
        self.assertEqual(payload["active_min_out_pps_per_queue"], {"0": 10})
        self.assertNotIn("inactive_queues", payload)

    def test_inactive_queues_pass_through(self):
        hc = create_cpu_queue_snapshot_check(
            active_queues=[2],
            inactive_queues=[0, 9],
            no_discard_queues=[0, 2, 9],
        )
        payload = self._payload(hc)
        self.assertEqual(payload["inactive_queues"], [0, 9])

    def test_inactive_max_pps_merges_into_active_min_dict(self):
        """A2 expansion: noise tolerance for inactive queues should be merged into
        the underlying active_min_out_pps_per_queue dict (the existing HC uses one
        dict for both >=N active thresholds and <=N inactive tolerances)."""
        hc = create_cpu_queue_snapshot_check(
            active_queues=[2],
            inactive_queues=[0, 9],
            inactive_max_pps_per_queue={0: 100, 9: 100},
            active_min_out_pps_per_queue={2: 50},
        )
        payload = self._payload(hc)
        self.assertEqual(
            payload["active_min_out_pps_per_queue"], {"2": 50, "0": 100, "9": 100}
        )

    def test_inactive_max_pps_overrides_existing_active_min_entry(self):
        """When a queue appears in both active_min and inactive_max, inactive_max wins
        (it's the semantically-correct tolerance for an inactive queue)."""
        hc = create_cpu_queue_snapshot_check(
            active_queues=[2],
            inactive_queues=[0],
            inactive_max_pps_per_queue={0: 100},
            active_min_out_pps_per_queue={
                0: 10
            },  # legacy: was being used as inactive tolerance
        )
        payload = self._payload(hc)
        self.assertEqual(payload["active_min_out_pps_per_queue"], {"0": 100})

    def test_inactive_max_pps_without_inactive_queues_is_noop(self):
        """If caller passes inactive_max_pps_per_queue but no inactive_queues, the
        merge is skipped (the param is meaningless on its own)."""
        hc = create_cpu_queue_snapshot_check(
            active_queues=[2],
            inactive_max_pps_per_queue={0: 100},
            active_min_out_pps_per_queue={0: 10},
        )
        payload = self._payload(hc)
        self.assertEqual(payload["active_min_out_pps_per_queue"], {"0": 10})


class TestCpuQueueHealthCheckCompareSnapshots(unittest.IsolatedAsyncioTestCase):
    """End-to-end tests for `compare_snapshots`, focused on the inactive_queues
    leakage assertion added in the A2 expansion."""

    def setUp(self):
        self.logger = MagicMock(spec=ConsoleFileLogger)
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "gtsw001.l1001.c085.ash6"
        self.hc = CpuQueueHealthCheck(
            obj=self.device,
            input=hc_types.CpuQueueHealthCheckIn(active_queues=[]),
            pre_snapshot_checkpoint_id="pre",
            post_snapshot_checkpoint_id="post",
            check_params={},
            logger=self.logger,
        )
        self.hc.driver = AsyncMock()
        # Stub the everpaste calls so failure paths don't try to reach interngraph
        # under `network_access = none()`. Patched at the cpu_queue_health_check
        # module (where the functions are looked up), per python_tests rules.
        for fn in ("async_everpaste_str",):
            p = patch(f"{_HC_MODULE}.{fn}", new=AsyncMock(return_value="stub_url"))
            p.start()
            self.addCleanup(p.stop)

    async def _compare(self, input_, pre_out, post_out, pre_disc=None, post_disc=None):
        pre = _make_stats_snapshot(pre_out, pre_disc or {}, timestamp=1000)
        post = _make_stats_snapshot(
            post_out, post_disc or {}, timestamp=1060
        )  # 60s window
        return await self.hc.compare_snapshots(self.device, input_, {}, pre, post)

    async def test_active_queue_with_growth_passes(self):
        result = await self._compare(
            hc_types.CpuQueueHealthCheckIn(
                active_queues=[2],
                active_min_out_pps_per_queue={2: 10},
            ),
            pre_out={2: 0},
            post_out={2: 6000},  # 100 pps
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_active_queue_below_threshold_fails(self):
        result = await self._compare(
            hc_types.CpuQueueHealthCheckIn(
                active_queues=[2],
                active_min_out_pps_per_queue={2: 100},
            ),
            pre_out={2: 0},
            post_out={2: 600},  # 10 pps, below 100
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)

    async def test_inactive_queue_within_noise_tolerance_passes(self):
        """A2 leakage check: small background growth on an inactive queue (BGP
        keepalives etc.) should NOT trip the leakage assertion when below the
        per-queue noise tolerance."""
        result = await self._compare(
            hc_types.CpuQueueHealthCheckIn(
                active_queues=[2],
                inactive_queues=[9],
                # 100 pps tolerance for inactive queue 9 (merged via factory expansion)
                active_min_out_pps_per_queue={2: 10, 9: 100},
            ),
            pre_out={2: 0, 9: 0},
            post_out={
                2: 6000,
                9: 600,
            },  # active 100 pps, inactive 10 pps (well under 100)
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_inactive_queue_above_noise_tolerance_fails(self):
        """A2 leakage check: misclassification routing test traffic to the wrong
        queue produces growth far above noise; assertion must fire."""
        result = await self._compare(
            hc_types.CpuQueueHealthCheckIn(
                active_queues=[2],
                inactive_queues=[9],
                active_min_out_pps_per_queue={2: 10, 9: 100},
            ),
            pre_out={2: 0, 9: 0},
            post_out={2: 6000, 9: 60000},  # leakage: 1000 pps on inactive queue 9
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("9", result.message)

    async def test_no_discard_queue_with_new_discards_fails(self):
        result = await self._compare(
            hc_types.CpuQueueHealthCheckIn(
                active_queues=[],
                no_discard_queues=[0],
            ),
            pre_out={0: 0},
            post_out={0: 0},
            pre_disc={0: 100},
            post_disc={0: 500},  # +400 discards
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("discard", result.message.lower())

    async def test_no_discard_queue_unchanged_passes(self):
        result = await self._compare(
            hc_types.CpuQueueHealthCheckIn(
                active_queues=[],
                no_discard_queues=[0, 2, 9],
            ),
            pre_out={0: 0, 2: 0, 9: 0},
            post_out={0: 0, 2: 0, 9: 0},
            pre_disc={0: 100, 2: 0, 9: 0},
            post_disc={0: 100, 2: 0, 9: 0},
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)


if __name__ == "__main__":
    unittest.main()
