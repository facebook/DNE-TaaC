# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Unit tests for the NexthopGroupPoll final-check verdicts.

This poll is the gate for the "bounded number of programmed ECMP sets"
characteristic (SC9). Two properties matter and neither was covered:

1. It must not pass when it measured nothing. ``run`` logs and swallows every
   collection failure, so a device that never answered produced an empty series
   and a SKIP -- which is not a failing status, so the characteristic silently
   disappeared from the run.
2. ``num_unprogrammed_groups`` -- the device's own report that it could not
   program a group, i.e. the most direct signal that a hardware table was
   exceeded -- was sampled and plotted but never asserted.
3. Once a caller opts in to that assertion, it must never vanish. The verdict
   depends on a series the collection loop populates in lockstep with the
   count series; if that lockstep ever breaks the gate has to SAY so, not
   quietly drop itself. Both halves of that are pinned below.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from taac.tasks.periodic_tasks import (
    _unprogrammed_verdict,
    NexthopGroupPoll,
)
from taac.utils.arista_utils import NexthopGroupSummary
from taac.health_check.health_check import types as hc_types

# Defined in the task's own module, so patch it there.
_PLOT = "neteng.test_infra.dne.taac.tasks.periodic_tasks._generate_multi_series_plot"


def _summary(configured: int, unprogrammed: int = 0) -> NexthopGroupSummary:
    return NexthopGroupSummary(
        num_groups_configured=configured,
        num_unprogrammed_groups=unprogrammed,
        nexthop_group_sizes={128: configured} if configured else {},
        nexthop_group_types={"IP": configured},
    )


class NexthopGroupPollFinalCheckTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.task = NexthopGroupPoll(hostname="bag013.ash6", logger=MagicMock())
        # Returning no plot path short-circuits the everpaste upload, keeping
        # the test hermetic (the target declares no network access).
        self._plot = patch(_PLOT, new=AsyncMock(return_value=None))
        self._plot.start()
        self.addCleanup(self._plot.stop)

    def _params(self, threshold: int = 50, max_unprogrammed=None) -> None:
        self.task._params.clear()
        self.task._params.update({"hostname": "bag013.ash6", "threshold": threshold})
        if max_unprogrammed is not None:
            self.task._params["max_unprogrammed"] = max_unprogrammed

    async def _final_check(self):
        """run_final_check returns Optional, so narrow it once here rather than
        repeating an assert in every test."""
        result = await self.task.run_final_check()
        assert result is not None
        return result

    async def test_empty_series_fails_rather_than_skipping(self) -> None:
        """Every poll failing must fail the check, not silently excuse it."""
        self._params()

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("No nexthop-group data collected", result.message)

    async def test_samples_without_a_summary_fail(self) -> None:
        """Data recorded, but nothing parseable -- still no measurement."""
        self._params()
        self.task.add_data("not a summary", timestamp=1)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        # The empty-series branch also returns FAIL, so pin which one fired.
        self.assertIn("none was a NexthopGroupSummary", result.message)
        self.assertNotIn("No nexthop-group data collected", result.message)

    async def test_count_below_threshold_passes(self) -> None:
        self._params(threshold=50)
        self.task.add_data(_summary(2), timestamp=1)
        self.task.add_data(_summary(17), timestamp=2)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertIn("count OK", result.message)
        self.assertIn("samples=2", result.message)

    async def test_count_equal_to_threshold_fails(self) -> None:
        """The comparison is strict `<`, so max == threshold is a breach."""
        self._params(threshold=50)
        self.task.add_data(_summary(50), timestamp=1)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("count BREACH", result.message)

    async def test_unprogrammed_is_not_asserted_by_default(self) -> None:
        """Existing callers pass no max_unprogrammed and must be unaffected."""
        self._params(threshold=50)
        self.task.add_data(_summary(3, unprogrammed=9), timestamp=1)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertNotIn("unprogrammed", result.message)

    async def test_unprogrammed_breach_fails_when_opted_in(self) -> None:
        """A group the device could not program fails the check even though
        the count itself is comfortably under the ceiling."""
        self._params(threshold=50, max_unprogrammed=0)
        self.task.add_data(_summary(3, unprogrammed=1), timestamp=1)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("unprogrammed BREACH", result.message)

    async def test_unprogrammed_zero_passes_when_opted_in(self) -> None:
        self._params(threshold=50, max_unprogrammed=0)
        self.task.add_data(_summary(3, unprogrammed=0), timestamp=1)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertIn("unprogrammed OK", result.message)

    async def test_both_breaches_are_reported_together(self) -> None:
        """Triage needs to see which verdict failed, so both are named."""
        self._params(threshold=10, max_unprogrammed=0)
        self.task.add_data(_summary(99, unprogrammed=4), timestamp=1)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("count BREACH", result.message)
        self.assertIn("unprogrammed BREACH", result.message)


class NexthopGroupUnprogrammedCouplingTest(unittest.IsolatedAsyncioTestCase):
    """The unprogrammed verdict cannot silently skip itself.

    Guarding the verdict on ``num_unprogrammed_groups_data`` being truthy would
    be the natural way to write it and would be wrong: it reads as a safety
    belt but encodes "drop a gate the caller explicitly asked for", which is
    the vacuous pass this whole module exists to prevent.

    What makes the truthy form indistinguishable from the explicit form today
    is an invariant, not an accident: the collection loop fills the count and
    unprogrammed series in the same ``isinstance`` branch, and an empty count
    series already returns before the verdict runs. So the two tests here pin
    the pair: the invariant that makes the empty case unreachable, and the
    empty case itself, asserted directly on the verdict function because no
    input to the poll can drive it there.
    """

    def setUp(self) -> None:
        self.task = NexthopGroupPoll(hostname="bag013.ash6", logger=MagicMock())
        # Held rather than discarded: the collected series never reaches
        # PeriodicCheckResult (which carries only name/status/message), so the
        # plot call is the only place they are observable from outside.
        self.plot = AsyncMock(return_value=None)
        plot_patch = patch(_PLOT, new=self.plot)
        plot_patch.start()
        self.addCleanup(plot_patch.stop)
        self.task._params.clear()
        self.task._params.update(
            {"hostname": "bag013.ash6", "threshold": 50, "max_unprogrammed": 0}
        )

    async def test_the_two_series_are_populated_in_lockstep(self) -> None:
        """The invariant the unreachability of the empty case rests on.

        If a later change ever populates the count series without the
        unprogrammed one, this fails and points at the verdict that would
        otherwise have started skipping itself.
        """
        for ts, summary in enumerate([_summary(2), _summary(11), _summary(4)], 1):
            self.task.add_data(summary, timestamp=ts)

        await self.task.run_final_check()

        series = self.plot.call_args.kwargs["data_series"]
        # KEYS, i.e. timestamps -- the two series carry different values by
        # design (counts vs unprogrammed counts). Sample-for-sample presence is
        # the invariant.
        self.assertEqual(
            series["num_groups_configured"].keys(),
            series["num_unprogrammed_groups"].keys(),
        )
        self.assertEqual(3, len(series["num_unprogrammed_groups"]))

    def test_an_empty_series_is_a_failure_not_a_skip(self) -> None:
        """The case run_final_check cannot reach, asserted where it can be.

        No input to the poll produces an empty unprogrammed series (that is the
        invariant above), so this is only reachable by calling the verdict
        directly -- which is the whole reason it is a module-level function.
        Reintroducing a truthiness guard at the CALL SITE would make this
        branch dead again, but the branch itself would still be correct here;
        what this pins is that the verdict never answers "no comment".
        """
        failed, text = _unprogrammed_verdict({}, 0)

        self.assertTrue(failed)
        self.assertIn("unprogrammed NOT EVALUATED", text)

    def test_a_populated_series_still_renders_ok_and_breach(self) -> None:
        """The two reachable arms, asserted on the helper for symmetry."""
        failed, text = _unprogrammed_verdict({1.0: 0, 2.0: 0}, 0)
        self.assertFalse(failed)
        self.assertIn("unprogrammed OK", text)

        failed, text = _unprogrammed_verdict({1.0: 0, 2.0: 3}, 0)
        self.assertTrue(failed)
        self.assertIn("unprogrammed BREACH", text)


def _sized(sizes: dict) -> NexthopGroupSummary:
    """A summary whose group-width histogram is given explicitly."""
    return NexthopGroupSummary(
        num_groups_configured=sum(sizes.values()),
        num_unprogrammed_groups=0,
        nexthop_group_sizes=sizes,
        nexthop_group_types={"IP": sum(sizes.values())},
    )


class NexthopGroupEcmpSetVerdictTest(unittest.IsolatedAsyncioTestCase):
    """The raw group count cannot distinguish "more ECMP sets" from "ECMP
    collapsed into width-1 singletons" -- the latter makes the count RISE.

    Shapes below are the real bag013 release-191 series: healthy {128: 2}, then
    {1: 256, 128: 2} (count 258), then {1: 256} (count 256, zero real sets).
    """

    def setUp(self) -> None:
        self.task = NexthopGroupPoll(hostname="bag013.ash6", logger=MagicMock())
        self._plot = patch(_PLOT, new=AsyncMock(return_value=None))
        self._plot.start()
        self.addCleanup(self._plot.stop)

    def _params(self, **kwargs) -> None:
        self.task._params.clear()
        self.task._params.update(
            {"hostname": "bag013.ash6", "threshold": 10_000, **kwargs}
        )

    async def _final_check(self):
        result = await self.task.run_final_check()
        assert result is not None
        return result

    async def test_healthy_shape_counts_two_real_sets(self) -> None:
        self._params(min_ecmp_width=2, max_multiway_groups=2)
        self.task.add_data(_sized({128: 2}), timestamp=1)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertIn("max groups >= 2-wide = 2", result.message)

    async def test_singleton_collapse_is_not_counted_as_ecmp_sets(self) -> None:
        """count = 258 but only 2 groups are real ECMP sets."""
        self._params(min_ecmp_width=2, max_multiway_groups=2)
        self.task.add_data(_sized({1: 256, 128: 2}), timestamp=1)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertIn("max groups >= 2-wide = 2", result.message)
        self.assertIn("max width-1 groups = 256", result.message)

    async def test_total_collapse_to_singletons_fails(self) -> None:
        """Groups exist but none is multi-way: ECMP was destroyed. Reporting
        "0 real sets" and passing would be the inverse of the truth."""
        self._params(min_ecmp_width=2, max_multiway_groups=2)
        self.task.add_data(_sized({1: 256}), timestamp=1)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("ecmp-sets BREACH", result.message)
        self.assertIn("max groups >= 2-wide = 0", result.message)

    async def test_empty_histogram_refuses_to_evaluate(self) -> None:
        """sizes={} for every sample is a parse failure, not a device with no
        nexthop groups -- the size table has no found-flag in the parser."""
        self._params(min_ecmp_width=2, max_multiway_groups=2)
        self.task.add_data(_sized({}), timestamp=1)
        self.task.add_data(_sized({}), timestamp=2)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("ecmp-sets NOT EVALUATED", result.message)

    async def test_genuine_ecmp_set_growth_still_breaches(self) -> None:
        """The gate must still catch what it is actually for."""
        self._params(min_ecmp_width=2, max_multiway_groups=2)
        self.task.add_data(_sized({4: 40}), timestamp=1)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("ecmp-sets BREACH", result.message)

    async def test_observe_only_when_no_ceiling_given(self) -> None:
        self._params(min_ecmp_width=2)
        self.task.add_data(_sized({4: 40}), timestamp=1)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertIn("ecmp-sets OBSERVED", result.message)


class NexthopGroupRecoveryVerdictTest(unittest.IsolatedAsyncioTestCase):
    """Recovery separates a bounded transient from a structural regression by
    duration rather than magnitude, so it needs no calibrated ceiling."""

    def setUp(self) -> None:
        self.task = NexthopGroupPoll(hostname="bag013.ash6", logger=MagicMock())
        self._plot = patch(_PLOT, new=AsyncMock(return_value=None))
        self._plot.start()
        self.addCleanup(self._plot.stop)

    def _params(self, **kwargs) -> None:
        self.task._params.clear()
        self.task._params.update(
            {"hostname": "bag013.ash6", "threshold": 10_000, **kwargs}
        )

    def _series(self, values) -> None:
        for i, v in enumerate(values):
            self.task.add_data(_summary(v), timestamp=i + 1)

    async def _final_check(self):
        result = await self.task.run_final_check()
        assert result is not None
        return result

    async def test_transient_that_settles_back_passes(self) -> None:
        """Baseline 2, a spike to 16 mid-run, back to 2 -- a healthy drain."""
        self._params(recovery_tolerance=1.5, recovery_window_samples=3)
        self._series([2, 2, 2, 9, 16, 11, 2, 2, 2])

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertIn("recovery OK", result.message)

    async def test_persistent_elevation_fails(self) -> None:
        """The real bag013 shape: 2 -> 258 -> 256 and never returns."""
        self._params(recovery_tolerance=1.5, recovery_window_samples=3)
        self._series([2, 2, 2, 21, 33, 258, 256, 256, 256])

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("recovery BREACH", result.message)
        self.assertIn("persistent change", result.message)

    async def test_recovery_not_asserted_by_default(self) -> None:
        self._params()
        self._series([2, 2, 2, 258, 256, 256])

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertNotIn("recovery", result.message)

    async def test_high_transient_with_clean_recovery_beats_a_level_gate(self) -> None:
        """A spike far above any plausible ceiling still passes if it settles --
        which is the point of gating on persistence instead of level."""
        self._params(recovery_tolerance=1.5, recovery_window_samples=3)
        self._series([2, 2, 2, 400, 900, 400, 2, 2, 2])

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertIn("recovery OK", result.message)


class NexthopGroupVacuityGuardTest(unittest.IsolatedAsyncioTestCase):
    """Guards for four ways this check could report a pass it had not earned.

    All four were found by auditing the first cut of these gates against the
    routing authoring standard, and all four are reproduced here.
    """

    def setUp(self) -> None:
        self.task = NexthopGroupPoll(hostname="bag013.ash6", logger=MagicMock())
        self._plot = patch(_PLOT, new=AsyncMock(return_value=None))
        self._plot.start()
        self.addCleanup(self._plot.stop)

    def _params(self, **kwargs) -> None:
        self.task._params.clear()
        self.task._params.update(
            {"hostname": "bag013.ash6", "threshold": 10_000, **kwargs}
        )

    async def _final_check(self):
        result = await self.task.run_final_check()
        assert result is not None
        return result

    async def test_series_shorter_than_two_windows_fails(self) -> None:
        """`_series_window` returns the whole series when the requested count
        exceeds its length, so both windows would be the same samples and the
        gate would pass for any tolerance >= 1."""
        self._params(recovery_tolerance=1.5)  # default window = 10
        for i, v in enumerate([2, 2, 2, 258, 256, 256, 256, 256]):
            self.task.add_data(_summary(v), timestamp=i + 1)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("recovery NOT EVALUATED", result.message)

    async def test_all_zero_series_fails_the_observation_floor(self) -> None:
        """An all-zero series is not empty, so it clears the empty guard and
        then satisfies any ceiling. This is the bag012 884-sample case."""
        self._params(threshold=50, min_observed_groups=1)
        for i in range(20):
            self.task.add_data(_summary(0), timestamp=i + 1)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("observation BREACH", result.message)

    async def test_recovery_uses_multiway_count_when_available(self) -> None:
        """A collapse from {128: 2} to {1: 2} leaves the RAW count at 2, so raw
        recovery passes while every real ECMP set was destroyed."""
        self._params(
            min_ecmp_width=2, recovery_tolerance=1.5, recovery_window_samples=2
        )
        for i, shape in enumerate(
            [{128: 2}, {128: 2}, {64: 2}, {1: 2}, {1: 2}, {1: 2}]
        ):
            self.task.add_data(_sized(shape), timestamp=i + 1)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("recovery BREACH", result.message)
        self.assertIn("2-wide", result.message)

    async def test_ceiling_without_width_is_reported_not_ignored(self) -> None:
        self._params(max_multiway_groups=2)

        self.task.add_data(_sized({128: 2}), timestamp=1)
        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("config BREACH", result.message)
        self.assertIn("min_ecmp_width", result.message)

    async def test_recovery_window_without_tolerance_is_reported(self) -> None:
        self._params(recovery_window_samples=5)

        self.task.add_data(_summary(2), timestamp=1)
        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("recovery_window_samples was set without", result.message)

    async def test_observation_floor_passes_when_metric_is_alive(self) -> None:
        self._params(threshold=10_000, min_observed_groups=1)
        self.task.add_data(_summary(2), timestamp=1)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertIn("observation OK", result.message)


class NexthopGroupRecoveryDirectionTest(unittest.IsolatedAsyncioTestCase):
    """Recovery must be TWO-SIDED.

    An upper bound alone passes a collapse: on the real bag013 series the
    multi-way count went 2 -> 0 and "settled at 0" -- every ECMP set destroyed
    -- yet 0 <= 2 * 1.5, so a one-sided gate reported OK. Recovery means
    returning to the steady state, not merely staying under it.
    """

    def setUp(self) -> None:
        self.task = NexthopGroupPoll(hostname="bag013.ash6", logger=MagicMock())
        self._plot = patch(_PLOT, new=AsyncMock(return_value=None))
        self._plot.start()
        self.addCleanup(self._plot.stop)

    def _params(self, **kwargs) -> None:
        self.task._params.clear()
        self.task._params.update(
            {"hostname": "bag013.ash6", "threshold": 10_000, **kwargs}
        )

    def _series(self, values) -> None:
        for i, v in enumerate(values):
            self.task.add_data(_summary(v), timestamp=i + 1)

    async def _final_check(self):
        result = await self.task.run_final_check()
        assert result is not None
        return result

    async def test_collapse_to_zero_fails(self) -> None:
        """The regression this fix exists for."""
        self._params(recovery_tolerance=1.5, recovery_window_samples=3)
        self._series([2, 2, 2, 2, 2, 2, 0, 0, 0])

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("recovery BREACH", result.message)
        self.assertIn("below", result.message)

    async def test_partial_collapse_below_the_band_fails(self) -> None:
        self._params(recovery_tolerance=1.5, recovery_window_samples=3)
        self._series([10, 10, 10, 10, 10, 10, 4, 4, 4])

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("below", result.message)

    async def test_within_band_either_side_passes(self) -> None:
        self._params(recovery_tolerance=1.5, recovery_window_samples=3)
        self._series([10, 10, 10, 40, 40, 40, 8, 8, 8])

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertIn("recovery OK", result.message)

    async def test_zero_baseline_refuses_to_evaluate(self) -> None:
        """A zero opening window means the poll started before convergence;
        any ratio against 0 is meaningless."""
        self._params(recovery_tolerance=1.5, recovery_window_samples=3)
        self._series([0, 0, 0, 2, 2, 2, 2, 2, 2])

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("recovery NOT EVALUATED", result.message)
        self.assertIn("predates convergence", result.message)

    async def test_baseline_uses_median_not_max(self) -> None:
        """One spike inside the opening window must not inflate the baseline
        and make the gate permissive."""
        self._params(recovery_tolerance=1.5, recovery_window_samples=3)
        # max(opening) would be 100 and admit almost anything; median is 2.
        self._series([2, 100, 2, 2, 2, 2, 20, 20, 20])

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("baseline of 2", result.message)


def _counters_only(configured: int) -> NexthopGroupSummary:
    """Counter lines parsed but the SIZE table did not.

    The size table has no found-flag in the parser, so a wording or column
    change yields ``sizes={}`` while the counters still read fine.
    """
    return NexthopGroupSummary(
        num_groups_configured=configured,
        num_unprogrammed_groups=0,
        nexthop_group_sizes={},
        nexthop_group_types={"IP": configured},
    )


class NexthopGroupRecoveryToleranceValidationTest(unittest.IsolatedAsyncioTestCase):
    """`recovery_tolerance` defines the band ``baseline/t .. baseline*t``.

    That is only meaningful at ``t >= 1``. Zero divides, ``0 < t < 1`` inverts
    the band so no value can satisfy it, and a non-finite tolerance admits
    everything. None of these were validated, so the first two reached
    `_recovery_verdict` as a crash and a silent always-fail respectively.
    """

    def setUp(self) -> None:
        self.task = NexthopGroupPoll(hostname="bag013.ash6", logger=MagicMock())
        self._plot = patch(_PLOT, new=AsyncMock(return_value=None))
        self._plot.start()
        self.addCleanup(self._plot.stop)

    def _params(self, **kwargs) -> None:
        self.task._params.clear()
        self.task._params.update(
            {"hostname": "bag013.ash6", "threshold": 10_000, **kwargs}
        )

    async def _final_check(self):
        result = await self.task.run_final_check()
        assert result is not None
        return result

    async def test_zero_tolerance_is_rejected_not_raised(self) -> None:
        """`baseline / 0` would raise ZeroDivisionError out of the final check."""
        self._params(recovery_tolerance=0, recovery_window_samples=2)
        for i, v in enumerate([2, 2, 2, 2, 2, 2]):
            self.task.add_data(_summary(v), timestamp=i + 1)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("config BREACH", result.message)
        self.assertIn("recovery_tolerance must be a finite value >= 1", result.message)

    async def test_fractional_tolerance_is_rejected(self) -> None:
        """t=0.5 gives low=4, high=1 on a baseline of 2 -- an empty interval,
        so every run fails for a reason the recovery message never states."""
        self._params(recovery_tolerance=0.5, recovery_window_samples=2)
        for i, v in enumerate([2, 2, 2, 2, 2, 2]):
            self.task.add_data(_summary(v), timestamp=i + 1)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("inverts the recovery band", result.message)

    async def test_infinite_tolerance_is_rejected(self) -> None:
        self._params(recovery_tolerance=float("inf"), recovery_window_samples=2)
        for i, v in enumerate([2, 2, 2, 2, 2, 2]):
            self.task.add_data(_summary(v), timestamp=i + 1)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("recovery_tolerance must be a finite value >= 1", result.message)

    async def test_tolerance_of_exactly_one_is_accepted(self) -> None:
        """t=1 is the strictest legal setting: the band collapses to the
        baseline itself. It must be allowed through, not rejected as invalid."""
        self._params(recovery_tolerance=1.0, recovery_window_samples=2)
        for i, v in enumerate([2, 2, 2, 2, 2, 2]):
            self.task.add_data(_summary(v), timestamp=i + 1)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertNotIn("config BREACH", result.message)
        self.assertIn("recovery OK", result.message)

    async def test_invalid_params_do_not_reach_the_verdict_helpers(self) -> None:
        """Validating a parameter and then using it anyway is the bug this
        guards. A non-positive window makes `_series_window` return the whole
        series for BOTH windows, so baseline == final and recovery passes
        vacuously -- the gate must never get that far."""
        self._params(recovery_tolerance=1.5, recovery_window_samples=0)
        for i, v in enumerate([2, 2, 2, 2, 2, 2]):
            self.task.add_data(_summary(v), timestamp=i + 1)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("recovery_window_samples must be positive", result.message)
        self.assertNotIn("recovery OK", result.message)
        # The check returns on a bad config, so no other verdict is scored
        # against a configuration nobody intended.
        self.assertNotIn("count OK", result.message)


class NexthopGroupEmptyHistogramRecoveryTest(unittest.IsolatedAsyncioTestCase):
    """An all-empty size histogram must not be scored as a real recovery.

    `sizes_data` carries one entry per `NexthopGroupSummary`, so it is falsy
    only when there were no summaries at all -- a case that returns earlier.
    With `min_ecmp_width` set, the multi-way series is therefore ALWAYS the one
    used, and an unparsed size table yields an all-zero series rather than a
    fall back to the raw count. This pins that: the verdict must stay labelled
    as the multi-way metric and must not silently answer a different question.
    """

    def setUp(self) -> None:
        self.task = NexthopGroupPoll(hostname="bag013.ash6", logger=MagicMock())
        self._plot = patch(_PLOT, new=AsyncMock(return_value=None))
        self._plot.start()
        self.addCleanup(self._plot.stop)

    async def test_unparsed_size_table_is_not_scored_as_raw_recovery(self) -> None:
        self.task._params.clear()
        self.task._params.update(
            {
                "hostname": "bag013.ash6",
                "threshold": 10_000,
                "min_ecmp_width": 2,
                "recovery_tolerance": 1.5,
                "recovery_window_samples": 2,
            }
        )
        # Counters read a healthy, perfectly steady 2 throughout. On the raw
        # series that is a textbook recovery; only the size table can reveal
        # that nothing was actually counted.
        for i in range(6):
            self.task.add_data(_counters_only(2), timestamp=i + 1)

        result = await self.task.run_final_check()
        assert result is not None

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("ecmp-sets NOT EVALUATED", result.message)
        # The recovery verdict must NOT have been computed against the raw
        # count, which would have read "recovery OK" on this data.
        self.assertNotIn("recovery OK", result.message)
        self.assertNotIn("nexthop-group count settled", result.message)
