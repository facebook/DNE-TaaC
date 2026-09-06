# Copyright (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from taac.tasks import fpf_inject_bgp_prefixes_task


class FpfInjectBgpPrefixesTaskTest(unittest.IsolatedAsyncioTestCase):
    async def test_pod_mosaic_preserves_as_path_and_batching(self) -> None:
        driver = MagicMock()
        inject = AsyncMock()

        with (
            patch.object(
                fpf_inject_bgp_prefixes_task,
                "FbossSwitchInternal",
                return_value=driver,
            ),
            patch.object(
                fpf_inject_bgp_prefixes_task,
                "inject_prefixes",
                inject,
            ),
        ):
            await fpf_inject_bgp_prefixes_task.FpfInjectBgpPrefixesTask().run(
                {
                    "groups": [
                        {
                            "devices": ["stsw001.s001.l202.mwg2"],
                            "prefix_base": "5000:dd::/64",
                            "count": 4,
                            "communities": ["65529:52792"],
                            "pods": 2,
                            "prefixes_per_pod": 2,
                            "base_asn_path": 4203699001,
                            "batch_size": 2,
                        }
                    ]
                }
            )

        inject.assert_awaited_once()
        call = inject.await_args
        assert call is not None
        self.assertIs(call.args[0], driver)
        self.assertEqual(len(call.args[1]), 4)
        self.assertEqual(call.kwargs["batch_size"], 2)
        prefix_as_path = call.kwargs["prefix_as_path"]
        self.assertEqual(len(prefix_as_path), 4)
        self.assertEqual(
            list(prefix_as_path.values()),
            [[4203699001], [4203699001], [4203699002], [4203699002]],
        )


if __name__ == "__main__":
    unittest.main()
