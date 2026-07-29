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
    register_collector,
    set_test_case_start_time,
    unregister_collector,
    get_test_case_start_time,
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


if __name__ == "__main__":
    unittest.main()
