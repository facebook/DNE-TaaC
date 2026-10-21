# Copyright (c) Meta Platforms, Inc. and affiliates.
"""OSS-runnable coverage for the CPU queue check's failure evidence.

``test_cpu_queue_health_check.py`` cannot run in the OSS image (it imports
``neteng.netcastle``), so the assertions that a failure carries the window it
measured live here, where ``run_tests.sh`` actually executes them.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from taac.health_checks.constants import Snapshot
from taac.health_checks.snapshot_health_checks.cpu_queue_health_check import (
    CpuQueueHealthCheck,
)
from taac.health_check.health_check import types as hc_types

_HC_MODULE = "neteng.test_infra.dne.taac.health_checks.snapshot_health_checks.cpu_queue_health_check"


def _snapshot(out_packets: dict, discards: dict, timestamp: int) -> Snapshot:
    port_stats = MagicMock()
    port_stats.queueOutPackets_ = dict(out_packets)
    port_stats.queueOutDiscardPackets_ = dict(discards)
    data = MagicMock()
    data.portStats_ = port_stats
    return Snapshot(data=data, timestamp=timestamp)


class TestCpuQueueFailureWindow(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.check = CpuQueueHealthCheck(
            obj=MagicMock(),
            input=hc_types.CpuQueueHealthCheckIn(active_queues=[]),
            pre_snapshot_checkpoint_id="pre",
            post_snapshot_checkpoint_id="post",
            check_params={},
            logger=MagicMock(),
        )
        # The failure path uploads its full reason list; keep it off the network.
        patcher = patch(
            f"{_HC_MODULE}.async_everpaste_str", new=AsyncMock(return_value="stub_url")
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    async def _compare(self, input_, pre_out, post_out, pre_disc, post_disc):
        return await self.check.compare_snapshots(
            MagicMock(),
            input_,
            {},
            _snapshot(pre_out, pre_disc, timestamp=1000),
            _snapshot(post_out, post_disc, timestamp=1060),
        )

    async def test_active_queue_failures_carry_their_own_counters(self):
        """A failure has to carry the window it measured.

        A flat out_packets with climbing discards is a policer eating the
        punts; flat with flat discards is a punt that never happened; a
        counter that went backwards is an agent restart inside the window.
        All three read as "no increase", and nothing in the message tells
        them apart unless the numbers are in it.
        """
        policed = await self._compare(
            hc_types.CpuQueueHealthCheckIn(
                active_queues=[0], active_min_out_pps_per_queue={0: 10}
            ),
            pre_out={0: 38166},
            post_out={0: 38166},
            pre_disc={0: 1000000},
            post_disc={0: 6665827},
        )
        self.assertEqual(policed.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("out_packets 38166 -> 38166 in 60s", policed.message)
        self.assertIn("discards 1000000 -> 6665827", policed.message)

        below_threshold = await self._compare(
            hc_types.CpuQueueHealthCheckIn(
                active_queues=[0], active_min_out_pps_per_queue={0: 100}
            ),
            pre_out={0: 0},
            post_out={0: 600},  # 10 pps, below the 100 pps floor
            pre_disc={0: 0},
            post_disc={0: 42},
        )
        self.assertEqual(below_threshold.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("out_packets 0 -> 600 in 60s", below_threshold.message)
        self.assertIn("discards 0 -> 42", below_threshold.message)


if __name__ == "__main__":
    unittest.main()
