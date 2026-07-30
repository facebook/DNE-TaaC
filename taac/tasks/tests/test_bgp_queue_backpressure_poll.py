# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from taac.internal.tasks.bgp_queue_backpressure_poll_task import (
    BgpQueueBackpressurePoll,
)
from taac.health_check.health_check import types as hc_types

# BgpClientHelper is a module-level import in the handler module, so patch it
# where it is looked up (the handler module's namespace), not at its definition.
_HELPER = (
    "neteng.test_infra.dne.taac.internal.tasks."
    "bgp_queue_backpressure_poll_task.BgpClientHelper"
)


def _peer(adjr=0, send=0, adjr_dur=0, send_dur=0, buffered=0):
    """A fake `TPeerEgressStats` (only the fields the poller reads)."""
    return SimpleNamespace(
        adjribout_queue_blocks=adjr,
        send_queue_blocks=send,
        adjribout_queue_total_block_duration=adjr_dur,
        send_queue_total_block_duration=send_dur,
        total_async_socket_buffered=buffered,
    )


class BgpQueueBackpressurePollTest(unittest.IsolatedAsyncioTestCase):
    """`BgpQueueBackpressurePoll` sums per-peer cumulative queue-block counters,
    and its final check gates on the DELTA accrued over the run. The wrapping
    PeriodicTask.terminate_on_error (from the factory) decides whether a FAIL
    aborts the test; the handler itself only reports PASS/FAIL/SKIP/ERROR."""

    def setUp(self) -> None:
        self.logger = MagicMock()
        self.task = BgpQueueBackpressurePoll(hostname="bag010.ash6", logger=self.logger)

    def _patch_stats(self, stats):
        helper = MagicMock()
        helper.async_get_peer_egress_stats = AsyncMock(return_value=stats)
        return patch(_HELPER, MagicMock(return_value=helper))

    async def test_run_sums_cumulative_blocks_across_peers(self) -> None:
        with self._patch_stats([_peer(adjr=3, send=2), _peer(adjr=1, send=0)]):
            await self.task.run({"hostname": "bag010.ash6", "threshold": 100})
        self.assertEqual(len(self.task._data), 1)
        sample = next(iter(self.task._data.values()))
        self.assertEqual(sample["total_queue_blocks"], 6)  # (3+2) + (1+0)
        self.assertEqual(sample["peer_count"], 2)

    async def test_run_error_swallowed_no_data(self) -> None:
        # getPeerEgressStats unavailable (older image) / thrift error -> logged,
        # no sample recorded, never raises (test must not crash mid-run).
        helper = MagicMock()
        helper.async_get_peer_egress_stats = AsyncMock(
            side_effect=Exception("no such rpc")
        )
        with patch(_HELPER, MagicMock(return_value=helper)):
            await self.task.run({"hostname": "bag010.ash6", "threshold": 100})
        self.logger.error.assert_called()
        self.assertEqual(len(self.task._data), 0)

    async def test_final_check_delta_within_threshold_pass(self) -> None:
        self.task._params.update({"threshold": 100})
        self.task.add_data(
            {"total_queue_blocks": 0, "total_block_duration": 0}, timestamp=1000
        )
        self.task.add_data(
            {"total_queue_blocks": 40, "total_block_duration": 5}, timestamp=1001
        )
        result = await self.task.run_final_check()
        # run_final_check() is typed Optional; these paths always return a
        # result, so narrow it (pyre) and guard the .status access below.
        assert result is not None
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_final_check_delta_exceeds_threshold_fail(self) -> None:
        self.task._params.update({"threshold": 10})
        self.task.add_data(
            {"total_queue_blocks": 0, "total_block_duration": 0}, timestamp=1000
        )
        self.task.add_data(
            {"total_queue_blocks": 50, "total_block_duration": 5}, timestamp=1001
        )
        result = await self.task.run_final_check()
        # run_final_check() is typed Optional; these paths always return a
        # result, so narrow it (pyre) and guard the .status access below.
        assert result is not None
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)

    async def test_final_check_no_data_skip(self) -> None:
        self.task._params.update({"threshold": 100})
        result = await self.task.run_final_check()
        # run_final_check() is typed Optional; these paths always return a
        # result, so narrow it (pyre) and guard the .status access below.
        assert result is not None
        self.assertEqual(result.status, hc_types.HealthCheckStatus.SKIP)

    async def test_final_check_no_threshold_error(self) -> None:
        self.task.add_data(
            {"total_queue_blocks": 5, "total_block_duration": 0}, timestamp=1000
        )
        result = await self.task.run_final_check()
        # run_final_check() is typed Optional; these paths always return a
        # result, so narrow it (pyre) and guard the .status access below.
        assert result is not None
        self.assertEqual(result.status, hc_types.HealthCheckStatus.ERROR)


if __name__ == "__main__":
    unittest.main()
