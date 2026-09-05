# Copyright (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

import unittest

from taac.libs.fpf.fpf_prod_prefix_map import (
    get_all_prefixes,
    get_host_prefixes,
    get_prefix,
    known_hosts,
)


class FpfProdPrefixMapTest(unittest.TestCase):
    def test_twshared1375_has_all_four_physical_gpu_vf1_prefixes(self) -> None:
        host = "twshared1375.03.mwg2"
        expected = [
            "2401:db00:292a:a150::/64",
            "2401:db00:292a:a151::/64",
            "2401:db00:292a:a152::/64",
            "2401:db00:292a:a153::/64",
        ]

        self.assertEqual(get_all_prefixes(host), expected)
        for device_id, prefix in enumerate(expected):
            with self.subTest(device_id=device_id):
                self.assertEqual(get_prefix(host, device_id), prefix)

    def test_known_hosts_are_sorted_and_include_replacement_client(self) -> None:
        hosts = known_hosts()
        self.assertEqual(hosts, sorted(hosts))
        self.assertIn("twshared1375.03.mwg2", hosts)

    def test_replacement_client_device_map_is_exact(self) -> None:
        self.assertEqual(
            get_host_prefixes("twshared1375.03.mwg2"),
            {
                0: "2401:db00:292a:a150::/64",
                1: "2401:db00:292a:a151::/64",
                2: "2401:db00:292a:a152::/64",
                3: "2401:db00:292a:a153::/64",
            },
        )

    def test_unknown_host_and_device_fail_loudly(self) -> None:
        with self.assertRaisesRegex(KeyError, "Known hosts"):
            get_prefix("unknown-host.mwg2")
        with self.assertRaisesRegex(KeyError, "Known devices"):
            get_prefix("twshared1352.03.mwg2", 7)


if __name__ == "__main__":
    unittest.main()
