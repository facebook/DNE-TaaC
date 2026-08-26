# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""Unit tests for IxiaPortStatsHealthCheck fault-delta and direction logic.

The check compares the cumulative IXIA Port Statistics fault counters against a
baseline stored on the Ixia object, so faults from setup-time link training
don't fail later invocations, and reports which direction of the link lost RX.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from taac.utils.oss_taac_lib_utils import ConsoleFileLogger
from taac.health_checks.ixia_health_checks.ixia_port_stats_health_check import (
    IxiaPortStatsHealthCheck,
)
from taac.health_check.health_check import types as hc_types


EVERPASTE_PATCH = (
    "taac.health_checks.ixia_health_checks"
    ".ixia_port_stats_health_check.async_everpaste_str"
)


def _make_stat(identifier, crc=0.0, local=0.0, remote=0.0, **extra):
    """A row as produced by get_port_statistics()."""
    stat = {
        "identifier": identifier,
        "CRC Errors": float(crc),
        "Local Faults": float(local),
        "Remote Faults": float(remote),
        "view": "Port Statistics",
    }
    stat.update(extra)
    return stat


class FakeRow:
    """Mimics restpy's Row lookup semantics (see assistants/statistics/row.py).

    `row[missing_column]` does NOT return None or raise KeyError: the string
    is treated as a regex, searched against every cell, and on a match the
    Row object itself is returned; only a no-match raises IndexError. Reads
    must therefore be guarded with `column in row.Columns`.
    """

    def __init__(self, values):
        self._values = values

    @property
    def Columns(self):
        return list(self._values)

    def __getitem__(self, key):
        if key in self._values:
            return self._values[key]
        import re

        for cell in map(str, self._values.values()):
            if re.search(key, cell):
                return self
        raise IndexError


def _make_row(port, crc=0.0, local=0.0, remote=0.0, **extra):
    """A raw stat-view row, keyed by IxNetwork column name."""
    row = {
        "Port Name": port,
        "CRC Errors": crc,
        "Local Faults": local,
        "Remote Faults": remote,
    }
    row.update(extra)
    return FakeRow(row)


def _make_ixia(rows, baseline=None):
    ixia = MagicMock()
    ixia.port_fault_baseline = baseline
    view = MagicMock()
    view._ViewName = "Port Statistics"
    view.Rows = rows
    ixia.get_or_create_stat_view.return_value = view
    return ixia


def _baseline(crc=0.0, local=0.0, remote=0.0):
    return {
        "CRC Errors": float(crc),
        "Local Faults": float(local),
        "Remote Faults": float(remote),
    }


class TestComputeFaultDeltas(unittest.TestCase):
    def setUp(self):
        self.check = IxiaPortStatsHealthCheck(logger=MagicMock(spec=ConsoleFileLogger))

    def test_unchanged_counters_yield_zero_deltas(self):
        stats = [_make_stat("p1", crc=4, local=2, remote=1)]
        deltas, regressed = self.check.compute_fault_deltas(
            stats, {"p1": _baseline(crc=4, local=2, remote=1)}
        )
        self.assertEqual(regressed, [])
        self.assertEqual(deltas[0]["CRC Errors"], 0.0)
        self.assertEqual(deltas[0]["Local Faults"], 0.0)
        self.assertEqual(deltas[0]["Remote Faults"], 0.0)

    def test_increase_is_reported_as_delta(self):
        stats = [_make_stat("p1", crc=4, local=5, remote=1)]
        deltas, regressed = self.check.compute_fault_deltas(
            stats, {"p1": _baseline(crc=4, local=2, remote=1)}
        )
        self.assertEqual(regressed, [])
        self.assertEqual(deltas[0]["Local Faults"], 3.0)

    def test_port_missing_from_baseline_gets_zero_baseline(self):
        stats = [_make_stat("p2", local=1)]
        deltas, regressed = self.check.compute_fault_deltas(stats, {})
        self.assertEqual(regressed, [])
        self.assertEqual(deltas[0]["Local Faults"], 1.0)

    def test_counter_below_baseline_is_clamped_and_flagged(self):
        # Something cleared the port's counters after the baseline was taken.
        stats = [_make_stat("p1", crc=1, local=0)]
        deltas, regressed = self.check.compute_fault_deltas(
            stats, {"p1": _baseline(crc=0, local=7)}
        )
        self.assertEqual(regressed, ["p1"])
        self.assertEqual(deltas[0]["Local Faults"], 0.0)
        self.assertEqual(deltas[0]["CRC Errors"], 1.0)

    def test_non_fault_fields_are_preserved(self):
        stats = [_make_stat("p1", **{"Link State": "Link Up"})]
        deltas, _ = self.check.compute_fault_deltas(stats, {"p1": _baseline()})
        self.assertEqual(deltas[0]["Link State"], "Link Up")
        self.assertEqual(deltas[0]["view"], "Port Statistics")


class TestSnapshotFaultBaseline(unittest.TestCase):
    def setUp(self):
        self.check = IxiaPortStatsHealthCheck(logger=MagicMock(spec=ConsoleFileLogger))

    def test_snapshot_stores_only_fault_counters(self):
        ixia = MagicMock()
        ixia.port_fault_baseline = None
        self.check.snapshot_fault_baseline(
            ixia, [_make_stat("p1", crc=4, local=2, remote=1)]
        )
        self.assertEqual(
            ixia.port_fault_baseline, {"p1": _baseline(crc=4, local=2, remote=1)}
        )

    def test_scoped_snapshot_leaves_other_ports_untouched(self):
        ixia = MagicMock()
        ixia.port_fault_baseline = {"p1": _baseline(local=7), "p2": _baseline(local=1)}
        self.check.snapshot_fault_baseline(
            ixia,
            [_make_stat("p1", local=0), _make_stat("p2", local=9)],
            ports=["p1"],
        )
        self.assertEqual(ixia.port_fault_baseline["p1"], _baseline(local=0))
        self.assertEqual(ixia.port_fault_baseline["p2"], _baseline(local=1))


class TestAttributeFaultDirection(unittest.TestCase):
    def setUp(self):
        self.check = IxiaPortStatsHealthCheck(logger=MagicMock(spec=ConsoleFileLogger))

    def test_remote_faults_point_at_the_ixia_to_dut_direction(self):
        [line] = self.check.attribute_fault_direction([_make_stat("p1", remote=2)])
        self.assertIn("IXIA->DUT", line)

    def test_local_faults_point_at_the_dut_to_ixia_direction(self):
        [line] = self.check.attribute_fault_direction([_make_stat("p1", local=3)])
        self.assertIn("DUT->IXIA", line)

    def test_current_link_state_is_appended_when_present(self):
        lines = self.check.attribute_fault_direction(
            [
                _make_stat(
                    "p1",
                    local=1,
                    **{"Link State": "Link Up", "Link Fault State": "No Fault"},
                )
            ]
        )
        self.assertEqual(len(lines), 2)
        self.assertIn("No Fault", lines[1])

    def test_clean_port_produces_no_lines(self):
        self.assertEqual(self.check.attribute_fault_direction([_make_stat("p1")]), [])


class TestGetPortStatistics(unittest.TestCase):
    def setUp(self):
        self.check = IxiaPortStatsHealthCheck(logger=MagicMock(spec=ConsoleFileLogger))

    def test_informational_columns_are_captured_when_present(self):
        view = MagicMock()
        view._ViewName = "Port Statistics"
        view.Rows = [_make_row("p1", **{"Link Fault State": "Local Fault"})]
        [stat] = self.check.get_port_statistics(view)
        self.assertEqual(stat["Link Fault State"], "Local Fault")

    def test_missing_informational_columns_do_not_raise(self):
        view = MagicMock()
        view._ViewName = "Port Statistics"
        view.Rows = [_make_row("p1")]
        [stat] = self.check.get_port_statistics(view)
        self.assertNotIn("Link State", stat)
        self.assertEqual(stat["CRC Errors"], 0.0)

    def test_absent_column_matching_cell_text_is_not_misread(self):
        # restpy falls back to a regex search over cell CONTENTS for an
        # unknown column and returns the Row cursor object on a match — the
        # read must go through row.Columns so a cell that happens to contain
        # the column name is never mistaken for the column.
        view = MagicMock()
        view._ViewName = "Port Statistics"
        view.Rows = [_make_row("p1 Link State demo")]
        [stat] = self.check.get_port_statistics(view)
        self.assertNotIn("Link State", stat)


class TestVerifyPortStatsThreshold(unittest.TestCase):
    def test_exceeded_rows_have_stable_info_keys(self):
        # tabulate(headers="keys") derives the column set from the rows, so
        # every exceeded row must carry the same keys — absent info columns
        # are filled with "n/a" rather than omitted.
        check = IxiaPortStatsHealthCheck(logger=MagicMock(spec=ConsoleFileLogger))
        rows = check.verify_port_stats_threshold(
            [
                _make_stat("p1", local=1, **{"Link State": "Link Up"}),
                _make_stat("p2", local=2),
            ]
        )
        self.assertEqual(len(rows), 2)
        for row in rows:
            for column in (
                "Link State",
                "Link Fault State",
                "PCS Local Faults",
                "PCS Remote Faults",
            ):
                self.assertIn(column, row)
        self.assertEqual(rows[1]["Link State"], "n/a")


class TestRun(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.check = IxiaPortStatsHealthCheck(logger=MagicMock(spec=ConsoleFileLogger))
        self.input = hc_types.BaseHealthCheckIn()

    async def test_first_run_snapshots_baseline_and_passes(self):
        # Faults accrued during setup link training must not fail the run that
        # takes the baseline.
        ixia = _make_ixia([_make_row("p1", crc=4, local=2, remote=1)])
        result = await self.check._run(ixia, self.input, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertEqual(
            ixia.port_fault_baseline, {"p1": _baseline(crc=4, local=2, remote=1)}
        )

    async def test_unchanged_counters_pass_against_baseline(self):
        ixia = _make_ixia(
            [_make_row("p1", crc=4, local=2, remote=1)],
            baseline={"p1": _baseline(crc=4, local=2, remote=1)},
        )
        result = await self.check._run(ixia, self.input, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    @patch(EVERPASTE_PATCH, new_callable=AsyncMock, return_value="https://ep.test")
    async def test_remote_fault_delta_fails_with_direction(self, _ep):
        ixia = _make_ixia(
            [_make_row("p1", remote=2)], baseline={"p1": _baseline()}
        )
        result = await self.check._run(ixia, self.input, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("IXIA->DUT", result.message)
        self.assertIn("https://ep.test", result.message)

    @patch(EVERPASTE_PATCH, new_callable=AsyncMock, return_value="https://ep.test")
    async def test_local_fault_delta_fails_with_direction(self, _ep):
        ixia = _make_ixia([_make_row("p1", local=3)], baseline={"p1": _baseline()})
        result = await self.check._run(ixia, self.input, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("DUT->IXIA", result.message)

    async def test_snapshot_baseline_param_retakes_the_baseline(self):
        ixia = _make_ixia(
            [_make_row("p1", local=5)], baseline={"p1": _baseline(local=1)}
        )
        result = await self.check._run(ixia, self.input, {"snapshot_baseline": True})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertEqual(ixia.port_fault_baseline, {"p1": _baseline(local=5)})

    async def test_baseline_run_fails_on_link_down(self):
        # The counters are exempt while baselining, but Link State is
        # point-in-time: a dead link at baseline time must not pass the
        # precheck. The baseline is still taken so later deltas are sane.
        ixia = _make_ixia([_make_row("p1", **{"Link State": "Link Down"})])
        result = await self.check._run(ixia, self.input, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("Link Down", result.message)
        self.assertEqual(ixia.port_fault_baseline, {"p1": _baseline()})

    async def test_baseline_run_passes_when_links_healthy(self):
        ixia = _make_ixia(
            [
                _make_row(
                    "p1",
                    **{"Link State": "Link Up", "Link Fault State": "No Fault"},
                )
            ]
        )
        result = await self.check._run(ixia, self.input, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_delta_run_fails_on_link_fault_state(self):
        # Zero counter deltas but the port is faulted right now.
        ixia = _make_ixia(
            [_make_row("p1", **{"Link Fault State": "Local Fault"})],
            baseline={"p1": _baseline()},
        )
        result = await self.check._run(ixia, self.input, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("Local Fault", result.message)

    @patch(EVERPASTE_PATCH, new_callable=AsyncMock, return_value="https://ep.test")
    async def test_inline_directions_cover_every_inline_port(self, _ep):
        # A port emits up to 4 direction lines; truncation must be per port
        # so one noisy port cannot crowd the others out of the inline message.
        ixia = _make_ixia(
            [
                _make_row("p1", crc=1, local=1, remote=1, **{"Link State": "Link Up"}),
                _make_row("p2", crc=1, local=1, remote=1, **{"Link State": "Link Up"}),
            ],
            baseline={"p1": _baseline(), "p2": _baseline()},
        )
        result = await self.check._run(ixia, self.input, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("p2: CRC Errors", result.message)

    @patch(EVERPASTE_PATCH, new_callable=AsyncMock, return_value="https://ep.test")
    async def test_regressed_port_is_rebaselined_without_masking_others(self, _ep):
        # p1's counters were cleared (5 -> 0); p2 genuinely faulted.
        ixia = _make_ixia(
            [_make_row("p1", local=0), _make_row("p2", local=3)],
            baseline={"p1": _baseline(local=5), "p2": _baseline(local=0)},
        )
        result = await self.check._run(ixia, self.input, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("p2", result.message)
        self.assertNotIn("p1", result.message)
        self.assertEqual(ixia.port_fault_baseline["p1"], _baseline(local=0))
        self.assertEqual(ixia.port_fault_baseline["p2"], _baseline(local=0))


if __name__ == "__main__":
    unittest.main()
