#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Tests for the shared collector registry.

The registry is shared across custom test handlers, so a handler's teardown
must drop only the slots it owns.
"""

import unittest

from taac.libs.collectors.registry import (
    clear_collectors,
    get_collector,
    get_collector_for_host,
    host_key,
    get_test_case_start_time,
    register_collector,
    set_test_case_start_time,
    unregister_collector,
)


class TestRegistry(unittest.TestCase):
    def tearDown(self) -> None:
        clear_collectors()

    def test_unregister_drops_only_the_named_slot(self) -> None:
        register_collector("cpu_utilization", object())
        fsdb = object()
        register_collector("fsdb", fsdb)

        unregister_collector("cpu_utilization")

        self.assertIsNone(get_collector("cpu_utilization"))
        self.assertIs(get_collector("fsdb"), fsdb)

    def test_unregister_preserves_test_case_start_time(self) -> None:
        """clear_collectors() also resets the runner's window anchor; a
        handler tearing down its own collectors must not."""
        set_test_case_start_time(1234.0)
        register_collector("cpu_utilization", object())

        unregister_collector("cpu_utilization")

        self.assertEqual(get_test_case_start_time(), 1234.0)

    def test_unregister_absent_name_is_a_noop(self) -> None:
        unregister_collector("never_registered")

    def test_each_host_gets_its_own_slot(self) -> None:
        """The bug this keying fixes: one flat slot meant every device but
        the registrant's SKIPped its collector-backed checks."""
        rsw2, rsw1 = object(), object()
        register_collector(host_key("cpu_utilization", "dut1"), rsw2)
        register_collector(host_key("cpu_utilization", "dut2"), rsw1)

        self.assertIs(get_collector_for_host("cpu_utilization", "dut1"), rsw2)
        self.assertIs(get_collector_for_host("cpu_utilization", "dut2"), rsw1)

    def test_unqualified_slot_serves_only_the_host_it_polls(self) -> None:
        """Back-compat for flat registrants (the FPF collectors), without
        handing dut1's samples to a check running against dut2."""

        class _Collector:
            host = "dut1"

        collector = _Collector()
        register_collector("cpu_utilization", collector)

        self.assertIs(get_collector_for_host("cpu_utilization", "dut1"), collector)
        self.assertIsNone(get_collector_for_host("cpu_utilization", "dut2"))

    def test_absent_host_is_none_not_the_wrong_hosts_collector(self) -> None:
        register_collector(host_key("systemd_state", "dut1"), object())

        self.assertIsNone(get_collector_for_host("systemd_state", "dut3"))


if __name__ == "__main__":
    unittest.main()
