# Copyright (c) Meta Platforms, Inc. and affiliates.

import unittest

from taac.tasks.fpf_collector_tasks import _collector_gtsw_scopes


class FpfCollectorScopeTest(unittest.TestCase):
    def test_fsdb_expands_all_planes_but_bgp_keeps_observers(self) -> None:
        observers = [
            "gtsw001.l1002.c087.mwg2",
            "gtsw001.l1001.c087.mwg2",
        ]

        fsdb_gtsws, bgp_gtsws = _collector_gtsw_scopes(observers)

        self.assertEqual(len(fsdb_gtsws), 9)
        self.assertEqual(
            fsdb_gtsws[:8], [f"gtsw{i:03d}.l1002.c087.mwg2" for i in range(1, 9)]
        )
        self.assertEqual(fsdb_gtsws[-1], "gtsw001.l1001.c087.mwg2")
        self.assertEqual(bgp_gtsws, observers)


if __name__ == "__main__":
    unittest.main()
