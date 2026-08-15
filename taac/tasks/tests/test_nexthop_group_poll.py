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
