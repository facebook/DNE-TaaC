# Copyright (c) Meta Platforms, Inc. and affiliates.

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from taac.tasks import fpf_collector_tasks
from taac.tasks.fpf_collector_tasks import (
    _collector_gtsw_scopes,
    FpfStartCollectorsTask,
)


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


class FpfAdditionalNamespaceCollectorTest(unittest.IsolatedAsyncioTestCase):
    async def test_starts_named_remote_namespace_and_filtered_fib_collectors(self):
        collector = MagicMock()
        collector.start = MagicMock()
        collector.set_append_mode = MagicMock()
        registered: list[str] = []

        with (
            patch.object(
                fpf_collector_tasks, "FsdbRibmapCollector", return_value=collector
            ),
            patch.object(
                fpf_collector_tasks, "BgpRibCollector", return_value=collector
            ),
            patch.object(
                fpf_collector_tasks, "FibRouteCollector", return_value=collector
            ),
            patch.object(
                fpf_collector_tasks, "HrtBulkCollector", return_value=collector
            ),
            patch.object(
                fpf_collector_tasks,
                "HrtRemoteFailureCollector",
                return_value=collector,
            ),
            patch.object(
                fpf_collector_tasks,
                "register_collector",
                side_effect=lambda name, _collector: registered.append(name),
            ),
            patch.object(fpf_collector_tasks.asyncio, "sleep", new=AsyncMock()),
        ):
            await FpfStartCollectorsTask().run(
                {
                    "gtsws": ["gtsw001.l1002.c087.mwg2"],
                    "hosts": [],
                    "baseline_collection_sec": 0,
                    "additional_namespaces": [
                        {
                            "name": "remote_b",
                            "subnet_prefix": "4000:dd::/32",
                            "fsdb_gtsws": ["gtsw001.l1002.c087.mwg2"],
                            "bgp_gtsws": [
                                "gtsw001.l1001.c087.mwg2",
                                "gtsw001.l1002.c087.mwg2",
                            ],
                            "fib_gtsws": ["gtsw001.l1002.c087.mwg2"],
                            "hosts": ["twshared1352.03.mwg2"],
                            "device_ids": list(range(8)),
                            "plane_ids": list(range(4)),
                            "include_remote_failure": True,
                        },
                        {
                            "name": "local_a",
                            "subnet_prefix": "5000:dd::/32",
                            "fib_gtsws": ["gtsw001.l1002.c087.mwg2"],
                        },
                    ],
                }
            )

        self.assertTrue(
            {
                "fsdb_remote_b",
                "bgp_remote_b",
                "fib_remote_b",
                "hrt_remote_b",
                "hrt_remote_failure_remote_b",
                "fib_local_a",
            }.issubset(registered)
        )


if __name__ == "__main__":
    unittest.main()
