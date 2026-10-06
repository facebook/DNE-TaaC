# Copyright (c) Meta Platforms, Inc. and affiliates.
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import later.unittest
from neteng.fboss.bgp_thrift.types import TPeerEgressStats
from taac.internal.tasks.bgp_queue_backpressure_poll_task import (
    BgpQueueBackpressurePoll,
    calculate_backpressure_delta,
    summarize_peer_egress_backpressure,
)
from taac.health_check.health_check import types as hc_types

# BgpClientHelper is a module-level import in the handler module, so patch it
# where it is looked up (the handler module's namespace), not at its definition.
_HELPER = (
    "neteng.test_infra.dne.taac.internal.tasks."
    "bgp_queue_backpressure_poll_task.BgpClientHelper"
)


def _peer(adjr=0, send=0, adjr_dur=0, send_dur=0, buffered=0):
    return TPeerEgressStats(
        adjribout_queue_blocks=adjr,
        send_queue_blocks=send,
        adjribout_queue_total_block_duration=adjr_dur,
        send_queue_total_block_duration=send_dur,
        total_async_socket_buffered=buffered,
    )


class BgpQueueBackpressurePollTest(later.unittest.TestCase):
    """`BgpQueueBackpressurePoll` sums per-peer cumulative queue-block counters,
    and enforces the DELTA only when explicitly configured."""

    def setUp(self) -> None:
        self.logger = MagicMock()
        self.task = BgpQueueBackpressurePoll(hostname="bag010.ash6", logger=self.logger)

    def _patch_stats(self, stats):
        helper = MagicMock()
        helper.async_get_peer_egress_stats = AsyncMock(return_value=stats)
        return patch(_HELPER, MagicMock(return_value=helper))

    async def test_run_sums_cumulative_blocks_across_peers(self) -> None:
        with self._patch_stats(
            [
                _peer(adjr=3, send=2, adjr_dur=7, send_dur=11),
                _peer(adjr=1, send=0, adjr_dur=13, send_dur=17),
            ]
        ):
            await self.task.run({"hostname": "bag010.ash6", "threshold": 100})
        self.assertEqual(len(self.task._data), 1)
        sample = next(iter(self.task._data.values()))
        self.assertEqual(sample["total_queue_blocks"], 6)  # (3+2) + (1+0)
        self.assertEqual(sample["total_block_duration"], 48)
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
            {"total_queue_blocks": 0, "total_block_duration": 0, "peer_count": 2},
            timestamp=1000,
        )
        self.task.add_data(
            {"total_queue_blocks": 40, "total_block_duration": 5, "peer_count": 2},
            timestamp=1001,
        )
        result = await self.task.run_final_check()
        # run_final_check() is typed Optional; these paths always return a
        # result, so narrow it (pyre) and guard the .status access below.
        assert result is not None
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_final_check_delta_exceeds_threshold_observes_by_default(
        self,
    ) -> None:
        self.task._params.update({"threshold": 10})
        self.task.add_data(
            {"total_queue_blocks": 0, "total_block_duration": 0, "peer_count": 2},
            timestamp=1000,
        )
        self.task.add_data(
            {"total_queue_blocks": 50, "total_block_duration": 5, "peer_count": 2},
            timestamp=1001,
        )
        result = await self.task.run_final_check()
        # run_final_check() is typed Optional; these paths always return a
        # result, so narrow it (pyre) and guard the .status access below.
        assert result is not None
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("Observed non-blocking", result.message)

    async def test_final_check_delta_exceeds_threshold_fails_when_blocking(
        self,
    ) -> None:
        self.task._params.update({"threshold": 10, "fail_on_breach": True})
        self.task.add_data(
            {"total_queue_blocks": 0, "total_block_duration": 0, "peer_count": 2},
            timestamp=1000,
        )
        self.task.add_data(
            {"total_queue_blocks": 50, "total_block_duration": 5, "peer_count": 2},
            timestamp=1001,
        )
        result = await self.task.run_final_check()
        assert result is not None
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)

    async def test_final_check_can_gate_on_block_duration(self) -> None:
        self.task._params.update(
            {
                "threshold": 1000,
                "block_duration_threshold_ms": 10,
                "fail_on_block_duration_breach": True,
            }
        )
        self.task.add_data(
            {"total_queue_blocks": 0, "total_block_duration": 100, "peer_count": 2},
            timestamp=1000,
        )
        self.task.add_data(
            {"total_queue_blocks": 1, "total_block_duration": 125, "peer_count": 2},
            timestamp=1001,
        )

        result = await self.task.run_final_check()

        assert result is not None
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("25 ms blocked", result.message)

    async def test_duration_breach_does_not_reuse_queue_block_fail_flag(self) -> None:
        self.task._params.update(
            {
                "threshold": 1000,
                "block_duration_threshold_ms": 10,
                "fail_on_breach": True,
            }
        )
        self.task.add_data(
            {"total_queue_blocks": 0, "total_block_duration": 100, "peer_count": 2},
            timestamp=1000,
        )
        self.task.add_data(
            {"total_queue_blocks": 1, "total_block_duration": 125, "peer_count": 2},
            timestamp=1001,
        )

        result = await self.task.run_final_check()

        assert result is not None
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("Observed non-blocking", result.message)

    async def test_final_check_duration_gate_keeps_queue_block_gate(self) -> None:
        self.task._params.update(
            {
                "threshold": 0,
                "block_duration_threshold_ms": 100,
                "fail_on_breach": True,
            }
        )
        self.task.add_data(
            {"total_queue_blocks": 0, "total_block_duration": 100, "peer_count": 2},
            timestamp=1000,
        )
        self.task.add_data(
            {"total_queue_blocks": 1, "total_block_duration": 101, "peer_count": 2},
            timestamp=1001,
        )

        result = await self.task.run_final_check()

        assert result is not None
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("queue-block threshold=0", result.message)

    async def test_final_check_uses_largest_distinct_counter_epoch(self) -> None:
        self.task._params.update({"threshold": 49, "fail_on_breach": True})
        self.task.add_data(
            {"total_queue_blocks": 0, "total_block_duration": 0, "peer_count": 2},
            timestamp=1000,
        )
        self.task.add_data(
            {"total_queue_blocks": 50, "total_block_duration": 25, "peer_count": 2},
            timestamp=1001,
        )
        self.task.add_data(
            {"total_queue_blocks": 1, "total_block_duration": 1, "peer_count": 2},
            timestamp=1002,
        )
        self.task.add_data(
            {"total_queue_blocks": 7, "total_block_duration": 6, "peer_count": 2},
            timestamp=1003,
        )

        result = await self.task.run_final_check()

        assert result is not None
        # The reset interval starts a new epoch. The 50-event pre-reset epoch is
        # the conservative lower bound; the later six-event epoch is not added
        # to it because aggregate dips can also be read/population races.
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("50 blocks", result.message)
        self.assertIn("25 ms blocked", result.message)

    async def test_final_check_dip_then_recovery_is_not_double_counted(self) -> None:
        self.task._params.update({"threshold": 90, "fail_on_breach": True})
        for timestamp, blocks in enumerate((10, 100, 50, 100), start=1000):
            self.task.add_data(
                {
                    "total_queue_blocks": blocks,
                    "total_block_duration": blocks,
                    "peer_count": 2,
                },
                timestamp=timestamp,
            )

        result = await self.task.run_final_check()

        assert result is not None
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("90 blocks", result.message)

    async def test_final_check_keeps_duration_epoch_when_only_blocks_reset(
        self,
    ) -> None:
        self.task._params.update(
            {
                "threshold": 1000,
                "block_duration_threshold_ms": 15,
                "fail_on_block_duration_breach": True,
            }
        )
        for timestamp, (blocks, duration) in enumerate(
            ((10, 100), (20, 110), (1, 110), (2, 120)), start=1000
        ):
            self.task.add_data(
                {
                    "total_queue_blocks": blocks,
                    "total_block_duration": duration,
                    "peer_count": 2,
                },
                timestamp=timestamp,
            )

        result = await self.task.run_final_check()

        assert result is not None
        # There is no shared generation marker: the block reset cannot erase
        # evidence from the still-monotonic duration field.
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("20 ms blocked", result.message)

    async def test_final_check_keeps_blocks_epoch_when_only_duration_resets(
        self,
    ) -> None:
        self.task._params.update(
            {
                "threshold": 15,
                "block_duration_threshold_ms": 1000,
                "fail_on_breach": True,
            }
        )
        for timestamp, (blocks, duration) in enumerate(
            ((10, 100), (20, 110), (20, 1), (30, 2)), start=1000
        ):
            self.task.add_data(
                {
                    "total_queue_blocks": blocks,
                    "total_block_duration": duration,
                    "peer_count": 2,
                },
                timestamp=timestamp,
            )

        result = await self.task.run_final_check()

        assert result is not None
        # There is no shared generation marker: the duration reset cannot
        # erase evidence from the still-monotonic block field.
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("20 blocks", result.message)

    async def test_final_check_keeps_valid_intervals_when_one_is_invalid(self) -> None:
        self.task._params.update({"threshold": 5, "fail_on_breach": True})
        self.task.add_data(
            {"total_queue_blocks": 0, "total_block_duration": 0, "peer_count": 2},
            timestamp=1000,
        )
        self.task.add_data(
            {
                "total_queue_blocks": 10,
                "total_block_duration": 4,
                "peer_count": 2,
            },
            timestamp=1001,
        )
        self.task.add_data(
            {
                "total_queue_blocks": 10,
                "total_block_duration": 4,
                "peer_count": 0,
            },
            timestamp=1002,
        )

        result = await self.task.run_final_check()

        assert result is not None
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("10 blocks", result.message)
        self.logger.warning.assert_called_once()

    async def test_final_check_ignores_incomplete_sample_without_breaking_epoch(
        self,
    ) -> None:
        self.task._params.update({"threshold": 15, "fail_on_breach": True})
        self.task.add_data(
            {"total_queue_blocks": 0, "total_block_duration": 0, "peer_count": 2},
            timestamp=1000,
        )
        self.task.add_data(
            {"total_queue_blocks": 10, "total_block_duration": 10, "peer_count": 2},
            timestamp=1001,
        )
        self.task.add_data(
            {"total_queue_blocks": 15, "peer_count": 2},
            timestamp=1002,
        )
        self.task.add_data(
            {"total_queue_blocks": 20, "total_block_duration": 20, "peer_count": 2},
            timestamp=1003,
        )

        result = await self.task.run_final_check()

        assert result is not None
        # The incomplete sample is not a counter-epoch boundary. Complete
        # samples on either side retain the full observable growth.
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("20 blocks", result.message)

    async def test_final_check_errors_when_every_interval_is_invalid(self) -> None:
        self.task._params.update(
            {
                "threshold": 5,
                "fail_on_breach": True,
                "require_complete_delta": True,
            }
        )
        self.task.add_data(
            {"total_queue_blocks": 0, "total_block_duration": 0, "peer_count": 0},
            timestamp=1000,
        )
        self.task.add_data(
            {"total_queue_blocks": 1, "total_block_duration": 1, "peer_count": 2},
            timestamp=1001,
        )

        result = await self.task.run_final_check()

        assert result is not None
        self.assertEqual(result.status, hc_types.HealthCheckStatus.ERROR)
        self.assertIn("No valid BGP queue intervals", result.message)

    async def test_final_check_skips_when_every_interval_is_invalid_and_optional(
        self,
    ) -> None:
        self.task._params.update(
            {
                "threshold": 5,
                "fail_on_breach": True,
                "require_complete_delta": False,
            }
        )
        self.task.add_data(
            {"total_queue_blocks": 0, "total_block_duration": 0, "peer_count": 0},
            timestamp=1000,
        )
        self.task.add_data(
            {"total_queue_blocks": 1, "total_block_duration": 1, "peer_count": 2},
            timestamp=1001,
        )

        result = await self.task.run_final_check()

        assert result is not None
        self.assertEqual(result.status, hc_types.HealthCheckStatus.SKIP)
        self.assertIn("No valid BGP queue intervals", result.message)

    async def test_final_check_requires_two_samples_when_requested(self) -> None:
        self.task._params.update(
            {
                "threshold": 1000,
                "require_complete_delta": True,
            }
        )
        self.task.add_data(
            {"total_queue_blocks": 0, "total_block_duration": 0, "peer_count": 2},
            timestamp=1000,
        )

        result = await self.task.run_final_check()

        assert result is not None
        self.assertEqual(result.status, hc_types.HealthCheckStatus.ERROR)
        self.assertIn("At least two", result.message)

    async def test_final_check_incomplete_delta_never_silently_passes(self) -> None:
        self.task._params.update({"threshold": 1000})
        self.task.add_data(
            {"total_queue_blocks": 0, "total_block_duration": 0, "peer_count": 2},
            timestamp=1000,
        )

        result = await self.task.run_final_check()

        assert result is not None
        self.assertEqual(result.status, hc_types.HealthCheckStatus.SKIP)

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

    async def test_final_check_rejects_non_integer_threshold(self) -> None:
        self.task._params.update({"threshold": "10"})
        self.task.add_data(
            {"total_queue_blocks": 0, "total_block_duration": 0, "peer_count": 2},
            timestamp=1000,
        )
        self.task.add_data(
            {"total_queue_blocks": 1, "total_block_duration": 1, "peer_count": 2},
            timestamp=1001,
        )

        result = await self.task.run_final_check()

        assert result is not None
        self.assertEqual(result.status, hc_types.HealthCheckStatus.ERROR)
        self.assertIn("threshold must be a non-negative integer", result.message)

    async def test_final_check_rejects_boolean_duration_threshold(self) -> None:
        self.task._params.update({"threshold": 10, "block_duration_threshold_ms": True})
        self.task.add_data(
            {"total_queue_blocks": 0, "total_block_duration": 0, "peer_count": 2},
            timestamp=1000,
        )
        self.task.add_data(
            {"total_queue_blocks": 1, "total_block_duration": 1, "peer_count": 2},
            timestamp=1001,
        )

        result = await self.task.run_final_check()

        assert result is not None
        self.assertEqual(result.status, hc_types.HealthCheckStatus.ERROR)
        self.assertIn(
            "block_duration_threshold_ms must be a non-negative integer",
            result.message,
        )


class QueueBackpressureEvidenceTest(unittest.TestCase):
    def test_aggregate_and_delta_preserve_duration(self) -> None:
        baseline = summarize_peer_egress_backpressure(
            [_peer(adjr=1, adjr_dur=10), _peer(send=2, send_dur=20)]
        )
        final = summarize_peer_egress_backpressure(
            [_peer(adjr=2, adjr_dur=15), _peer(send=4, send_dur=29)]
        )

        self.assertEqual(
            calculate_backpressure_delta(baseline, final),
            {"queue_blocks_delta": 3, "block_duration_delta_ms": 14},
        )

    def test_counter_reset_is_clamped_to_zero(self) -> None:
        baseline = {
            "total_queue_blocks": 10,
            "total_block_duration": 20,
            "peer_count": 2,
        }
        final = {
            "total_queue_blocks": 1,
            "total_block_duration": 2,
            "peer_count": 2,
        }

        self.assertEqual(
            calculate_backpressure_delta(baseline, final),
            {"queue_blocks_delta": 0, "block_duration_delta_ms": 0},
        )

    def test_peer_population_change_keeps_aggregate_measurement(self) -> None:
        baseline = {
            "total_queue_blocks": 1,
            "total_block_duration": 2,
            "peer_count": 2,
        }
        final = {
            "total_queue_blocks": 2,
            "total_block_duration": 3,
            "peer_count": 1,
        }

        self.assertEqual(
            calculate_backpressure_delta(baseline, final),
            {"queue_blocks_delta": 1, "block_duration_delta_ms": 1},
        )
