# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe

"""Unit tests for the Pod Mosaic additions in
neteng.test_infra.dne.taac.libs.fpf.inject_bgp_prefixes.

Pure-Python coverage (no live BGP) for:
- Per-bucket TBgpAttributes carries the correct origin ASN AND the full
  shared community set (including AI_ZONE_LB_HOST_VIP 65529:52792).
- validate_injection_bulk() flags a mismatched origin ASN as failed.
- The --pods 1 / no-Pod-Mosaic-flag path is byte-identical to the original
  implementation (single shared TBgpAttributes object across all prefixes,
  no as_path).
- Loop-deny guard rejects ASNs from STSW-self and L1002 testbed ranges.
- Partition produces contiguous +1-to-low-index buckets.
"""

from __future__ import annotations

import argparse
import asyncio
import unittest
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

from neteng.fboss.bgp_attr.types import TAsPathSeg, TAsPathSegType
from neteng.fboss.bgp_route_types.types import TBgpPath, TRibEntry
from neteng.test_infra.dne.taac.libs.fpf import inject_bgp_prefixes as inj


VIP_COMMUNITY = "65529:52792"  # AI_ZONE_LB_HOST_VIP


def _make_prefix(i: int):
    return inj.build_tip_prefix(f"5000:dd:{i:x}::/64")


def _build_rib_entry(prefix, origin_asn: Optional[int]) -> TRibEntry:
    """Build a minimal TRibEntry with a single path whose as_path's first
    segment carries `origin_asn` in asns_4_byte. Pass origin_asn=None to
    omit the as_path entirely."""
    if origin_asn is None:
        path = TBgpPath(next_hop=prefix, as_path=[])
    else:
        seg = TAsPathSeg(
            seg_type=TAsPathSegType.AS_SEQUENCE,
            asns_4_byte=[origin_asn],
        )
        path = TBgpPath(next_hop=prefix, as_path=[seg])
    return TRibEntry(
        prefix=prefix,
        paths={"g": [path]},
        best_group="g",
        best_next_hop=prefix,
    )


def _make_args(**overrides) -> argparse.Namespace:
    """Build the slice of argparse.Namespace that resolve_pod_mosaic reads."""
    base = {
        "pods": 1,
        "pod_asn_preset": None,
        "pod_asn_list": None,
        "base_asn_path": None,
        "increment_asn_per_pod": 1,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


class PartitionPrefixesIntoPodsTest(unittest.TestCase):
    def test_equal_partition(self) -> None:
        self.assertEqual(
            inj.partition_prefixes_into_pods(10, 5),
            [0, 0, 1, 1, 2, 2, 3, 3, 4, 4],
        )

    def test_remainder_goes_to_low_index_buckets(self) -> None:
        # 11 prefixes across 4 buckets -> first 3 buckets get 3 prefixes,
        # last bucket gets 2.
        assignment = inj.partition_prefixes_into_pods(11, 4)
        self.assertEqual(assignment, [0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3])

    def test_one_pod(self) -> None:
        self.assertEqual(inj.partition_prefixes_into_pods(4, 1), [0, 0, 0, 0])

    def test_zero_pods_rejected(self) -> None:
        with self.assertRaises(ValueError):
            inj.partition_prefixes_into_pods(10, 0)

    def test_more_pods_than_prefixes_rejected(self) -> None:
        with self.assertRaises(ValueError):
            inj.partition_prefixes_into_pods(3, 4)


class LoopDenyGuardTest(unittest.TestCase):
    def test_stsw_self_range_rejected(self) -> None:
        # STSW-self range is 4203601901-4203601908. 4203601905 is in range.
        violations = inj.pod_mosaic_loop_deny_violations([4203601905])
        self.assertEqual(violations, [4203601905])

    def test_l1002_range_rejected(self) -> None:
        # L1002 testbed range is 4203601009-4203601016. 4203601012 is in range.
        violations = inj.pod_mosaic_loop_deny_violations([4203601012])
        self.assertEqual(violations, [4203601012])

    def test_safe_asns_pass(self) -> None:
        # Synthetic preset block (4203699001..4203699010) and a far-away ASN.
        safe = list(range(4203699001, 4203699011)) + [65000]
        self.assertEqual(inj.pod_mosaic_loop_deny_violations(safe), [])


class ResolvePodMosaicTest(unittest.TestCase):
    def test_backcompat_no_flags(self) -> None:
        args = _make_args(pods=1)
        self.assertIsNone(inj.resolve_pod_mosaic(args, prefix_count=10))

    def test_pods_ge_2_without_asn_source_rejected(self) -> None:
        args = _make_args(pods=4)
        with self.assertRaises(ValueError) as ctx:
            inj.resolve_pod_mosaic(args, prefix_count=10)
        self.assertIn("--pod-asn-preset", str(ctx.exception))

    def test_preset_and_list_mutually_exclusive(self) -> None:
        args = _make_args(
            pods=2,
            pod_asn_preset="mwg2-placeholder-10",
            pod_asn_list="1,2",
        )
        with self.assertRaises(ValueError):
            inj.resolve_pod_mosaic(args, prefix_count=10)

    def test_pod_asn_list_length_must_match_pods(self) -> None:
        args = _make_args(pods=3, pod_asn_list="100,200")
        with self.assertRaises(ValueError) as ctx:
            inj.resolve_pod_mosaic(args, prefix_count=10)
        self.assertIn("must equal", str(ctx.exception))

    def test_loop_deny_rejects_stsw_self(self) -> None:
        # 4203601905 is inside STSW-self deny range.
        args = _make_args(pods=2, pod_asn_list="4203601905,4203699999")
        with self.assertRaises(ValueError) as ctx:
            inj.resolve_pod_mosaic(args, prefix_count=10)
        self.assertIn("loop-deny", str(ctx.exception))

    def test_loop_deny_rejects_l1002(self) -> None:
        # 4203601012 is inside L1002 testbed deny range.
        args = _make_args(pods=2, pod_asn_list="4203699001,4203601012")
        with self.assertRaises(ValueError) as ctx:
            inj.resolve_pod_mosaic(args, prefix_count=10)
        self.assertIn("loop-deny", str(ctx.exception))

    def test_preset_resolves_to_ten_asns(self) -> None:
        args = _make_args(pods=10, pod_asn_preset="mwg2-placeholder-10")
        asns = inj.resolve_pod_mosaic(args, prefix_count=20)
        self.assertIsNotNone(asns)
        self.assertEqual(asns, list(range(4203699001, 4203699011)))

    def test_preset_implicit_pod_count(self) -> None:
        # When --pods is left at 1 but a preset is given, pods becomes
        # len(preset) implicitly.
        args = _make_args(pods=1, pod_asn_preset="mwg2-placeholder-10")
        asns = inj.resolve_pod_mosaic(args, prefix_count=100)
        self.assertIsNotNone(asns)
        assert asns is not None  # narrow for pyre
        self.assertEqual(len(asns), 10)
        self.assertEqual(args.pods, 10)

    # ----- --base-asn-path / --increment-asn-per-pod -----

    def test_base_asn_default_increment(self) -> None:
        # Default step of 1: 144 pods starting at 4203699001 -> 1..144 block.
        args = _make_args(pods=144, base_asn_path=4203699001)
        asns = inj.resolve_pod_mosaic(args, prefix_count=144 * 240)
        self.assertIsNotNone(asns)
        assert asns is not None
        self.assertEqual(len(asns), 144)
        self.assertEqual(asns[0], 4203699001)
        self.assertEqual(asns[143], 4203699144)
        self.assertEqual(asns, list(range(4203699001, 4203699145)))

    def test_base_asn_custom_increment(self) -> None:
        args = _make_args(pods=5, base_asn_path=4203699001, increment_asn_per_pod=10)
        asns = inj.resolve_pod_mosaic(args, prefix_count=5)
        self.assertEqual(
            asns, [4203699001, 4203699011, 4203699021, 4203699031, 4203699041]
        )

    def test_base_asn_negative_increment(self) -> None:
        # Negative step is allowed (descending block).
        args = _make_args(pods=3, base_asn_path=4203699100, increment_asn_per_pod=-1)
        asns = inj.resolve_pod_mosaic(args, prefix_count=3)
        self.assertEqual(asns, [4203699100, 4203699099, 4203699098])

    def test_base_asn_zero_increment_rejected(self) -> None:
        args = _make_args(pods=4, base_asn_path=4203699001, increment_asn_per_pod=0)
        with self.assertRaises(ValueError) as ctx:
            inj.resolve_pod_mosaic(args, prefix_count=10)
        self.assertIn("non-zero", str(ctx.exception))

    def test_base_asn_requires_explicit_pods(self) -> None:
        # --base-asn-path with pods left at default 1 should error — no
        # implicit length available.
        args = _make_args(pods=1, base_asn_path=4203699001)
        with self.assertRaises(ValueError) as ctx:
            inj.resolve_pod_mosaic(args, prefix_count=10)
        self.assertIn("--pods", str(ctx.exception))

    def test_base_asn_loop_deny_guard(self) -> None:
        # Generated list lands on STSW-self 4203601905 (in 1901-1908).
        args = _make_args(pods=8, base_asn_path=4203601901)
        with self.assertRaises(ValueError) as ctx:
            inj.resolve_pod_mosaic(args, prefix_count=8)
        self.assertIn("loop-deny", str(ctx.exception))

    def test_base_asn_mutually_exclusive_with_preset(self) -> None:
        args = _make_args(
            pods=10,
            pod_asn_preset="mwg2-placeholder-10",
            base_asn_path=4203699001,
        )
        with self.assertRaises(ValueError):
            inj.resolve_pod_mosaic(args, prefix_count=10)

    def test_base_asn_mutually_exclusive_with_list(self) -> None:
        args = _make_args(
            pods=2,
            pod_asn_list="1,2",
            base_asn_path=4203699001,
        )
        with self.assertRaises(ValueError):
            inj.resolve_pod_mosaic(args, prefix_count=10)


class BuildInjectNetworksTest(unittest.TestCase):
    def setUp(self) -> None:
        self.prefixes = [_make_prefix(i) for i in range(6)]
        self.communities = inj.build_communities(inj.GTSW_COMMUNITIES)

    def test_byte_identical_no_pods(self) -> None:
        """Without Pod Mosaic, every prefix maps to the SAME shared
        TBgpAttributes object, with no as_path set — byte-identical to the
        pre-Pod-Mosaic implementation."""
        networks = inj.build_inject_networks(self.prefixes, self.communities)
        self.assertEqual(len(networks), len(self.prefixes))
        attrs_objs = list(networks.values())
        # Same object reference for every prefix (preserves the old
        # `{p: attrs for p in prefixes}` literal).
        first = attrs_objs[0]
        for a in attrs_objs[1:]:
            self.assertIs(a, first)
        # And no as_path field is set.
        self.assertFalse(getattr(first, "as_path", None))
        # Communities preserved verbatim.
        self.assertEqual(
            list(first.communities),
            list(self.communities),
        )

    def test_per_bucket_attrs_carry_correct_asn_and_communities(self) -> None:
        pod_asn_list = [4203699001, 4203699002, 4203699003]
        as_path_map = inj.build_pod_mosaic_as_path_map(self.prefixes, pod_asn_list)
        networks = inj.build_inject_networks(
            self.prefixes, self.communities, prefix_as_path=as_path_map
        )
        # 6 prefixes / 3 pods -> 2 per bucket, contiguous.
        expected_origins = [
            pod_asn_list[0],
            pod_asn_list[0],
            pod_asn_list[1],
            pod_asn_list[1],
            pod_asn_list[2],
            pod_asn_list[2],
        ]
        comm_set = {(c.asn, c.value) for c in self.communities}
        for prefix, expected in zip(self.prefixes, expected_origins):
            attrs = networks[prefix]
            self.assertIsNotNone(attrs.as_path, f"missing as_path for {prefix}")
            self.assertEqual(len(attrs.as_path), 1)
            seg = attrs.as_path[0]
            self.assertEqual(seg.seg_type, TAsPathSegType.AS_SEQUENCE)
            self.assertEqual(list(seg.asns_4_byte), [expected])
            # Community set is UNCHANGED across every bucket.
            self.assertEqual(
                {(c.asn, c.value) for c in attrs.communities},
                comm_set,
            )
        # AI_ZONE_LB_HOST_VIP (65529:52792) is in every bucket's community set.
        self.assertIn((65529, 52792), comm_set)


class ValidateInjectionBulkAsPathTest(unittest.TestCase):
    """Drives validate_injection_bulk() against a mocked BGP client."""

    def _run(
        self, prefixes, communities, prefix_as_path, pod_asn_list, rib_origin_overrides
    ):
        # Build mock RIB entries with the requested origin ASNs (or
        # override_value to deliberately mismatch).
        rib_entries = []
        for p in prefixes:
            expected = prefix_as_path[p][0]
            actual = rib_origin_overrides.get(p, expected)
            rib_entries.append(_build_rib_entry(p, actual))
        # Community-filtered RIB returns all prefixes (community match).
        comm_entries = [_build_rib_entry(p, None) for p in prefixes]

        bgp_mock = MagicMock()
        bgp_mock.async_get_bgp_rib_entries = AsyncMock(return_value=rib_entries)
        bgp_mock.async_get_rib_entries_for_communities = AsyncMock(
            return_value=comm_entries
        )
        driver = MagicMock()
        driver.hostname = "test-host"
        driver.bgp = AsyncMock(return_value=bgp_mock)

        return asyncio.run(
            inj.validate_injection_bulk(
                driver,
                prefixes,
                communities,
                prefix_as_path=prefix_as_path,
                pod_asn_list=pod_asn_list,
            )
        )

    def test_all_match_passes(self) -> None:
        prefixes = [_make_prefix(i) for i in range(4)]
        pod_asn_list = [4203699001, 4203699002]
        as_path_map = inj.build_pod_mosaic_as_path_map(prefixes, pod_asn_list)
        communities = inj.build_communities(inj.GTSW_COMMUNITIES)
        results = self._run(
            prefixes,
            communities,
            as_path_map,
            pod_asn_list,
            rib_origin_overrides={},
        )
        self.assertEqual(len(results), 4)
        for r in results:
            self.assertTrue(r.as_path_check_required)
            self.assertTrue(r.as_path_passed, msg=str(r))
            self.assertTrue(r.rib_lookup_passed)
            self.assertTrue(r.community_lookup_prefix_found)

    def test_mismatched_origin_asn_flagged(self) -> None:
        prefixes = [_make_prefix(i) for i in range(4)]
        pod_asn_list = [4203699001, 4203699002]
        as_path_map = inj.build_pod_mosaic_as_path_map(prefixes, pod_asn_list)
        communities = inj.build_communities(inj.GTSW_COMMUNITIES)
        # Sabotage prefix #0: rib says ASN 999999 instead of 4203699001.
        results = self._run(
            prefixes,
            communities,
            as_path_map,
            pod_asn_list,
            rib_origin_overrides={prefixes[0]: 999999},
        )
        # First prefix fails as_path, the rest pass.
        self.assertFalse(results[0].as_path_passed)
        self.assertEqual(results[0].as_path_actual_asn, 999999)
        self.assertEqual(results[0].as_path_expected_asn, 4203699001)
        self.assertEqual(results[0].pod_bucket, 0)
        for r in results[1:]:
            self.assertTrue(r.as_path_passed)
