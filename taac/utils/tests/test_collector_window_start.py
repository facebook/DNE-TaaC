#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Tests for ``collector_window_start``.

Two per-iteration anchors exist and disagree by the duration of test-case
setUp — the ``start_time`` jq var is stamped before it, the collector
registry's timestamp after it. The later one wins.
"""

import unittest

from taac.libs.collectors.registry import (
    clear_collectors,
    set_test_case_start_time,
)
from taac.utils.health_check_utils import collector_window_start


class TestCollectorWindowStart(unittest.TestCase):
    def tearDown(self) -> None:
        clear_collectors()

    def test_registry_anchor_wins_over_earlier_jq_start(self) -> None:
        """Today's only caller shape: start_time_jq_var="test_case_start_time",
        stamped before setUp, so the registry's post-setUp anchor is later and
        the tighter window is preserved."""
        set_test_case_start_time(2000.0)
        self.assertEqual(
            collector_window_start({"start_time": 1000}, window_end=3000.0), 2000.0
        )

    def test_later_jq_start_wins(self) -> None:
        """A future call site anchoring to a mid-playbook moment (daemon
        restart, config push) measures the interval it asked for instead of
        silently widening to the whole iteration."""
        set_test_case_start_time(2000.0)
        self.assertEqual(
            collector_window_start({"start_time": 2500}, window_end=3000.0), 2500.0
        )

    def test_jq_start_used_when_registry_anchor_unset(self) -> None:
        self.assertEqual(
            collector_window_start({"start_time": 2500}, window_end=3000.0), 2500.0
        )

    def test_falls_back_to_lookback_when_both_unset(self) -> None:
        self.assertEqual(
            collector_window_start({}, window_end=3000.0, lookback_sec=900), 2100.0
        )

    def test_registry_anchor_used_when_no_jq_start(self) -> None:
        set_test_case_start_time(2000.0)
        self.assertEqual(collector_window_start({}, window_end=3000.0), 2000.0)


if __name__ == "__main__":
    unittest.main()
