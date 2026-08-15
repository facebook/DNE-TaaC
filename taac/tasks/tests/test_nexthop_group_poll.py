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
    _converged_verdict,
    _DEFAULT_CONVERGED_WINDOW_SAMPLES,
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
        failed, text = _unprogrammed_verdict({}, 0, None)

        self.assertTrue(failed)
        self.assertIn("unprogrammed NOT EVALUATED", text)

    def test_a_populated_series_still_renders_ok_and_breach(self) -> None:
        """The two reachable arms, asserted on the helper for symmetry.

        `tolerance_samples=None` keeps the pre-tolerance behaviour: any
        exceedance at all is a breach.
        """
        failed, text = _unprogrammed_verdict({1.0: 0, 2.0: 0}, 0, None)
        self.assertFalse(failed)
        self.assertIn("unprogrammed OK", text)

        failed, text = _unprogrammed_verdict({1.0: 0, 2.0: 3}, 0, None)
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
        self.assertIn("recovery_window_samples must be >= 1, got 0", result.message)
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


class NexthopGroupConvergedValueTest(unittest.IsolatedAsyncioTestCase):
    """The steady state, as opposed to the maximum.

    Every other verdict on this task is a max over the whole run, so a device
    that idles at the wrong number of ECMP sets is indistinguishable from one
    that idles at the right number but spiked once. This is the only gate that
    reads the state the device was LEFT in.
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

    def _shapes(self, shapes) -> None:
        for i, shape in enumerate(shapes):
            self.task.add_data(_sized(shape), timestamp=i + 1)

    async def test_settling_at_the_expected_value_passes(self) -> None:
        """The real bag013 shape: steady, drained, transient, recovered."""
        self._params(
            min_ecmp_width=2,
            expected_converged_multiway_groups=2,
            converged_window_samples=3,
        )
        self._shapes(
            [{128: 2}, {128: 2}, {}, {}, {64: 6}, {128: 2}, {128: 2}, {128: 2}]
        )

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status, result.message)
        self.assertIn("converged OK", result.message)

    async def test_settling_above_the_expected_value_fails(self) -> None:
        """ECMP sets that never collapsed back. The peak alone cannot see this:
        max is 6 either way."""
        self._params(
            min_ecmp_width=2,
            expected_converged_multiway_groups=2,
            converged_window_samples=3,
        )
        self._shapes([{128: 2}, {128: 2}, {}, {}, {64: 6}, {64: 5}, {64: 5}, {64: 5}])

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("converged BREACH", result.message)
        self.assertIn("settled at 5", result.message)

    async def test_settling_below_the_expected_value_fails(self) -> None:
        """Sets that never formed -- the inverse failure, equally invisible to a
        maximum."""
        self._params(
            min_ecmp_width=2,
            expected_converged_multiway_groups=2,
            converged_window_samples=3,
        )
        self._shapes([{128: 2}, {128: 2}, {128: 4}, {1: 9}, {1: 9}, {1: 9}])

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("converged BREACH", result.message)

    async def test_uses_the_median_so_one_artifact_cannot_decide(self) -> None:
        self._params(
            min_ecmp_width=2,
            expected_converged_multiway_groups=2,
            converged_window_samples=5,
        )
        # One spike inside the closing window; the other four are correct.
        self._shapes(
            [{128: 2}, {128: 2}, {128: 2}, {64: 9}, {128: 2}, {128: 2}, {128: 2}]
        )

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status, result.message)

    async def test_too_few_samples_refuses_to_evaluate(self) -> None:
        # 21, not 20: an even window is now rejected as a config breach before
        # the verdict runs, which would mask the behaviour under test here.
        self._params(
            min_ecmp_width=2,
            expected_converged_multiway_groups=2,
            converged_window_samples=21,
        )
        self._shapes([{128: 2}, {128: 2}])

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("converged NOT EVALUATED", result.message)

    async def test_without_min_ecmp_width_it_is_reported_not_ignored(self) -> None:
        """There is no multi-way series to settle, so the gate is inert -- and a
        silently inert gate is the failure mode this whole task exists to
        prevent."""
        self._params(expected_converged_multiway_groups=2)
        self.task.add_data(_sized({128: 2}), timestamp=1)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("config BREACH", result.message)
        self.assertIn("expected_converged_multiway_groups", result.message)


class NexthopGroupConvergedWindowParityTest(unittest.TestCase):
    """An EVEN closing window can BREACH on a perfectly healthy device.

    ``statistics.median`` AVERAGES the two middle samples of an even-length
    window, so a window straddling 2 and 3 yields 2.5 -- and ``2.5 == 2`` is
    False. This is not theoretical: the first fully green SC9 run on bag013
    logged ``settled at 2.0``, a float, and passed only because all ten of its
    closing samples happened to be identical. One sample of 3 anywhere in that
    window would have failed the run for a device doing exactly the right
    thing.
    """

    def test_even_window_medians_to_a_half_integer_and_breaches(self) -> None:
        # Four closing samples straddling two values. Nothing here is unhealthy:
        # the device is oscillating between 2 and 3 sets, and 2 is expected.
        series = {1.0: 2, 2.0: 2, 3.0: 3, 4.0: 3}

        failed, message = _converged_verdict(series, 2, 4, "groups >= 2-wide")

        self.assertTrue(failed)
        # The half-integer is now caught one step earlier, by the dominance
        # floor: no sample can hold a value that lies between two of them, so
        # the window is reported as never having settled rather than as a
        # device left at 2.5. Still a failure, and still never a silent pass --
        # which is what `_misconfigured_params` rejecting an even window is for.
        self.assertIn("NOT EVALUATED", message)
        self.assertIn("median value 2.5", message)

    def test_odd_window_always_medians_to_a_real_observed_sample(self) -> None:
        # Five closing samples, still straddling two values, so the median has
        # to be a real observation rather than an average of the middle pair.
        series = {1.0: 2, 2.0: 3, 3.0: 3, 4.0: 3, 5.0: 3}

        failed, message = _converged_verdict(series, 3, 5, "groups >= 2-wide")

        self.assertFalse(failed, message)
        self.assertIn("settled at 3", message)

    def test_the_default_window_is_odd(self) -> None:
        """Pins the invariant for every caller that does not set the param.

        ``_misconfigured_params`` rejects an even value, but only when one is
        supplied -- so the default has to carry the same guarantee itself.
        """
        self.assertEqual(1, _DEFAULT_CONVERGED_WINDOW_SAMPLES % 2)


class NexthopGroupConvergedWindowSettlingTest(unittest.TestCase):
    """A median is only a SETTLED value if the window it came from settled.

    SC9 run 9's drain aborted in cycle 3 of 5, so Stage C's soak never ran and
    the closing window covered a drained device, a rebuild and the recovered
    steady state -- 17 samples at 0, 11 at 6 and 3 at 2. Its median was 0, so
    the verdict announced that the device had been LEFT with every ECMP set
    destroyed, about a device whose final samples were sitting at the correct
    two 128-wide sets. The run was already failing on the aborted step; what
    this cost was an hour of chasing the wrong device behaviour.
    """

    def test_the_run_9_shape_is_reported_as_unevaluated(self) -> None:
        series = {float(i): v for i, v in enumerate([0] * 17 + [6] * 11 + [2] * 3)}

        failed, message = _converged_verdict(series, 2, 31, "groups >= 2-wide")

        self.assertTrue(failed)
        self.assertIn("converged NOT EVALUATED", message)
        self.assertIn("only 17 of 31 closing samples", message)
        self.assertIn("median value 0", message)

    def test_a_flat_window_at_the_wrong_value_still_breaches(self) -> None:
        """What the gate exists for -- a terminal collapse to one wide set --
        produces a FLAT window, which is dominant by definition. The precondition
        cannot convert that into a pass, or into an abstention."""
        series = {float(i): 1 for i in range(31)}

        failed, message = _converged_verdict(series, 2, 31, "groups >= 2-wide")

        self.assertTrue(failed)
        self.assertIn("converged BREACH", message)
        self.assertIn("settled at 1", message)

    def test_a_lone_artifact_does_not_withhold_the_verdict(self) -> None:
        """One bad sample in a window must not cost the verdict; that is what
        taking a median was for in the first place."""
        series = {1.0: 2, 2.0: 2, 3.0: 9, 4.0: 2, 5.0: 2}

        failed, message = _converged_verdict(series, 2, 5, "groups >= 2-wide")

        self.assertFalse(failed, message)
        self.assertIn("converged OK", message)


class NexthopGroupParamValidationTest(unittest.IsolatedAsyncioTestCase):
    """A misconfigured gate must produce a VERDICT, never an exception.

    ``_misconfigured_params`` exists to turn "this gate cannot run" into a
    reported breach. Coercing its own inputs with a bare ``int()`` / ``float()``
    meant the detector could raise straight out of ``run_final_check`` on the
    one input class it exists to catch.
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

    async def test_even_converged_window_is_rejected(self) -> None:
        self._params(
            min_ecmp_width=2,
            expected_converged_multiway_groups=2,
            converged_window_samples=4,
        )
        for i, shape in enumerate([{128: 2}] * 6):
            self.task.add_data(_sized(shape), timestamp=i + 1)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("converged_window_samples must be ODD", result.message)
        # A rejected config must not reach any verdict helper.
        self.assertNotIn("converged OK", result.message)
        self.assertNotIn("count OK", result.message)

    async def test_non_numeric_window_is_a_breach_not_a_crash(self) -> None:
        self._params(recovery_tolerance=1.5, recovery_window_samples="two")
        self.task.add_data(_sized({128: 2}), timestamp=1)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("recovery_window_samples must be an integer", result.message)

    async def test_non_numeric_tolerance_is_a_breach_not_a_crash(self) -> None:
        self._params(recovery_tolerance="loose", recovery_window_samples=2)
        self.task.add_data(_sized({128: 2}), timestamp=1)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("recovery_tolerance must be a number", result.message)

    async def test_non_numeric_converged_window_is_a_breach_not_a_crash(self) -> None:
        self._params(
            min_ecmp_width=2,
            expected_converged_multiway_groups=2,
            converged_window_samples="thirty-one",
        )
        self.task.add_data(_sized({128: 2}), timestamp=1)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("converged_window_samples must be an integer", result.message)

    async def test_non_positive_min_samples_is_a_breach(self) -> None:
        self._params(min_samples=0)
        self.task.add_data(_sized({128: 2}), timestamp=1)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("min_samples must be >= 1, got 0", result.message)


class NexthopGroupMinSamplesTest(unittest.IsolatedAsyncioTestCase):
    """A run that lost most of its polls scored every verdict on the survivors.

    ``run`` swallows every collection exception and the empty-series guard fires
    only when the series is ENTIRELY empty, so 5% collection produced a green
    run indistinguishable from a complete one.
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

    def _collect(self, count: int) -> None:
        for i in range(count):
            self.task.add_data(_sized({128: 2}), timestamp=i + 1)

    async def _final_check(self):
        result = await self.task.run_final_check()
        assert result is not None
        return result

    async def test_below_the_floor_fails(self) -> None:
        self._params(min_samples=10)
        self._collect(4)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("samples BREACH: collected only 4", result.message)

    async def test_at_the_floor_passes(self) -> None:
        self._params(min_samples=10)
        self._collect(10)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status, result.message)
        self.assertIn("samples OK: collected 10", result.message)

    async def test_unset_leaves_existing_callers_unaffected(self) -> None:
        """Opt-in: no param, no verdict -- the count is still reported."""
        self._params()
        self._collect(1)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status, result.message)
        self.assertNotIn("samples BREACH", result.message)
        self.assertNotIn("samples OK", result.message)
        self.assertIn("[samples=1, span=0s]", result.message)

    async def test_the_span_exposes_a_collection_wedge(self) -> None:
        """Count alone cannot distinguish a full run from one that stopped.

        Both series below have the same length, so `min_samples` passes either
        way -- but the second stopped collecting a third of the way in, which
        means the closing window `_converged_verdict` reads is really a mid-run
        window. The span is what makes the two distinguishable.
        """
        self._params(min_samples=5)
        for i in range(10):
            self.task.add_data(_sized({128: 2}), timestamp=1000 + i * 60)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status, result.message)
        self.assertIn("[samples=10, span=540s]", result.message)


class NexthopGroupSharedDataKeyTypeTest(unittest.IsolatedAsyncioTestCase):
    """Production hands back STRING timestamp keys; every other test uses ints.

    `add_data` casts the timestamp to `int`, which is why this looks safe. But a
    real run passes `shared_data`, so `_data` resolves to a `_SharedDataView`
    over a multiprocessing Manager dict, which stores each key as
    `f"{prefix}{key}"` and yields it back as `key[prefix_len:]`. Both operations
    are string operations. Tests pass `shared_data=None`, take the plain-dict
    branch, and keep int keys -- so the entire suite exercises a key type that
    never occurs in production.

    That divergence cost a hardware run: the first code to do ARITHMETIC on a
    timestamp died at teardown with
    ``unsupported operand type(s) for -: 'str' and 'str'``, failing a run in
    which every other gate had passed. This test builds the task the way the
    runner does, so the coercion boundary under test is the real one.
    """

    def setUp(self) -> None:
        # A plain dict is a faithful stand-in for the Manager dict here: the
        # stringification happens in _SharedDataView, not in the manager.
        self.shared: dict = {}
        self.task = NexthopGroupPoll(
            hostname="bag013.ash6", logger=MagicMock(), shared_data=self.shared
        )
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

    async def test_production_key_type_is_str(self) -> None:
        """Pins the premise. If this ever fails the comment above is stale."""
        self.task.add_data(_sized({128: 2}), timestamp=1000)

        self.assertTrue(
            all(isinstance(key, str) for key in self.task._data),
            f"expected str keys from the shared-data view, got "
            f"{[type(k).__name__ for k in self.task._data]}",
        )

    async def test_every_verdict_survives_string_keys(self) -> None:
        self._params(
            min_samples=5,
            min_ecmp_width=2,
            expected_converged_multiway_groups=2,
            converged_window_samples=3,
            max_unprogrammed=0,
            min_observed_groups=1,
        )
        for i in range(10):
            self.task.add_data(_sized({128: 2}), timestamp=1000 + i * 60)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status, result.message)
        # The span is computed from the keys, so this is the assertion that
        # would have caught the crash.
        self.assertIn("[samples=10, span=540s]", result.message)
        self.assertIn("converged OK", result.message)


class NexthopGroupUnprogrammedToleranceTest(unittest.IsolatedAsyncioTestCase):
    """`max == 0` asserts that group creation and hardware programming are
    atomic. They are not.

    The first complete five-cycle drain on bag013 read
    `num_unprogrammed_groups` 0 in 390 of 391 samples and 4 in exactly ONE,
    caught mid-rebuild with the widths climbing 1,2,3,12,...,26 as peers
    returned to the next-hop sets, and back to 0 five seconds later. That
    failed a run whose every other gate passed. What is assertable is that
    groups do not STAY unprogrammed.
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

    def _collect(self, unprogrammed: list) -> None:
        for i, value in enumerate(unprogrammed):
            self.task.add_data(_summary(2, unprogrammed=value), timestamp=1000 + i * 6)

    async def _final_check(self):
        result = await self.task.run_final_check()
        assert result is not None
        return result

    async def test_replays_the_real_five_cycle_series(self) -> None:
        """The actual shape from the run: one isolated non-zero in 391."""
        self._params(max_unprogrammed=0, unprogrammed_tolerance_samples=3)
        series = [0] * 200 + [4] + [0] * 190
        self._collect(series)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status, result.message)
        self.assertIn("only transiently", result.message)
        self.assertIn("peak 4", result.message)
        self.assertIn("longest consecutive run above 0 = 1", result.message)

    async def test_that_same_series_fails_without_the_tolerance(self) -> None:
        """Pins that the tolerance is what changed the verdict, and that the
        pre-existing behaviour is intact for callers that do not opt in."""
        self._params(max_unprogrammed=0)
        self._collect([0] * 200 + [4] + [0] * 190)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("unprogrammed BREACH", result.message)

    async def test_sustained_unprogrammed_still_breaches(self) -> None:
        """The gate must keep its teeth: groups that stay unprogrammed are
        blackholing traffic, and rel-191 sat at 8 while ECMP collapsed."""
        self._params(max_unprogrammed=0, unprogrammed_tolerance_samples=3)
        self._collect([0] * 50 + [8] * 12 + [0] * 50)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("STAYED unprogrammed", result.message)
        self.assertIn("longest consecutive run above 0 = 12", result.message)

    async def test_exactly_at_the_tolerance_passes(self) -> None:
        self._params(max_unprogrammed=0, unprogrammed_tolerance_samples=3)
        self._collect([0] * 20 + [1, 2, 1] + [0] * 20)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status, result.message)

    async def test_separate_transients_are_not_summed(self) -> None:
        """Five cycles means five rebuilds. Each may blip; that is not the same
        as one sustained failure, and a naive count of non-zero samples would
        conflate them."""
        self._params(max_unprogrammed=0, unprogrammed_tolerance_samples=3)
        self._collect(([0] * 20 + [4]) * 5 + [0] * 20)

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status, result.message)
        self.assertIn("longest consecutive run above 0 = 1", result.message)

    async def test_tolerance_without_a_ceiling_is_a_config_breach(self) -> None:
        self._params(unprogrammed_tolerance_samples=3)
        self._collect([0, 0, 0])

        result = await self._final_check()

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("without max_unprogrammed", result.message)
