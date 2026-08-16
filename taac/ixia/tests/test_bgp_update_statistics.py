# Copyright (c) Meta Platforms, Inc. and affiliates.

import unittest

from taac.ixia.ixia import _filter_bgp_stats_by_port


class BgpUpdateStatisticsTest(unittest.TestCase):
    def test_filter_uses_ixnetwork_port_name_column(self) -> None:
        stats = [
            {"Port Name": "10.0.0.1:1/1", "Updates Tx": "7"},
            {"Port Name": "10.0.0.1:1/2", "Updates Tx": "8"},
        ]

        self.assertEqual([stats[0]], _filter_bgp_stats_by_port(stats, "1/1"))

    def test_filter_accepts_legacy_port_column(self) -> None:
        stats = [{"Port": "10.0.0.1:1/1", "Updates Tx": "7"}]

        self.assertEqual(stats, _filter_bgp_stats_by_port(stats, "1/1"))

    def test_filter_falls_back_from_empty_port_name(self) -> None:
        stats = [
            {
                "Port Name": "",
                "Port": "10.0.0.1:1/1",
                "Updates Tx": "7",
            }
        ]

        self.assertEqual(stats, _filter_bgp_stats_by_port(stats, "1/1"))


if __name__ == "__main__":
    unittest.main()
