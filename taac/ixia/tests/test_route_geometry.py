# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-strict

import dataclasses
import json
import typing as t
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from taac.constants import TestCaseFailure
from taac.ixia.route_geometry import (
    IxiaOverlay,
    IxiaOverlayVector,
    IxiaRouteGeometry,
    IxiaValueVector,
)


class _MultiValue:
    def __init__(self, values: t.Iterable[object], *, count: int | None = None) -> None:
        self.Values = list(values)
        self.Count = count if count is not None else len(self.Values)
        self._properties = (
            {"pattern": "singleValue", "singleValue": {"value": self.Values[0]}}
            if len(self.Values) == 1
            else {"pattern": "valueList", "valueList": {"values": list(self.Values)}}
        )
        self.single_calls: list[object] = []
        self.value_list_calls: list[list[object]] = []

    def Single(self, value: object) -> None:
        self.single_calls.append(value)
        self.Values = [value]
        self._properties = {
            "pattern": "singleValue",
            "singleValue": {"value": value},
        }

    def ValueList(self, values: list[object]) -> None:
        self.value_list_calls.append(list(values))
        self.Values = list(values)
        self._properties = {
            "pattern": "valueList",
            "valueList": {"values": list(values)},
        }


class _PatternMultiValue(_MultiValue):
    def __init__(
        self,
        values: t.Iterable[object],
        pattern: str,
        payload: t.Mapping[str, object],
    ) -> None:
        super().__init__(values)
        self._properties = {"pattern": pattern, pattern: dict(payload)}
        self.increment_calls: list[tuple[int, int, int | None]] = []

    @property
    def Pattern(self) -> str:
        return str(self._properties["pattern"])

    def Single(self, value: object) -> None:
        super().Single(value)
        self._properties = {
            "pattern": "singleValue",
            "singleValue": {"value": value},
        }

    def ValueList(self, values: list[object]) -> None:
        super().ValueList(values)
        self._properties = {
            "pattern": "valueList",
            "valueList": {"values": list(values)},
        }

    def Increment(self, start: int, step: int, count: int | None = None) -> None:
        self.increment_calls.append((start, step, count))
        effective_count = self.Count if count is None else count
        self.Values = [start + index * step for index in range(effective_count)]
        self._properties = {
            "pattern": "counter",
            "counter": {
                "direction": "increment",
                "start": start,
                "step": step,
                "count": count,
            },
        }


class _LazyPatternMultiValue(_PatternMultiValue):
    def __init__(
        self,
        values: t.Iterable[object],
        pattern: str,
        payload: t.Mapping[str, object],
    ) -> None:
        super().__init__(values, pattern, payload)
        self._resolved_properties = self._properties
        self._properties = {}

    @property
    def Pattern(self) -> str:
        self._properties = self._resolved_properties
        return str(self._properties["pattern"])


class _OverlayConnection:
    def __init__(self) -> None:
        self.overlays: list[dict[str, object]] = []
        self.clear_calls = 0
        self.create_calls = 0
        self.child_updates: list[tuple[str, dict[str, object]]] = []
        self.fail_on_create: int | None = None
        self.fail_after_create: int | None = None
        self.fail_on_create_not_found: int | None = None
        self.fail_on_child_update: int | None = None
        self.reject_create_after_clear = False
        self.read_errors: list[Exception] = []
        self.post_create_read_errors: list[Exception] = []
        self._headers: dict[str, str] = {}
        self._verify_cert = False
        self.request_calls: list[dict[str, object]] = []
        self.request_status = 201
        self.response_body_override: dict[str, object] | None = None
        self.merge_adjacent_same_value = False

    def _normalize_url(self, href: str) -> tuple[str, str]:
        return "", href

    def _request(self, **kwargs: object) -> SimpleNamespace:
        if kwargs.get("method") != "POST":
            raise AssertionError(kwargs)
        self.request_calls.append(dict(kwargs))
        if self.request_status != 201:
            return SimpleNamespace(status_code=self.request_status)
        href = str(kwargs["url"])
        raw_data = kwargs["data"]
        if not isinstance(raw_data, str):
            raise AssertionError(raw_data)
        payload = json.loads(raw_data)
        self._create(href, payload, follow_child=False)
        return SimpleNamespace(
            status_code=201,
            json=lambda: self.response_body_override
            or {"links": self.overlays[-1]["links"]},
        )

    def _process_response_status_code(self, *args: object) -> None:
        raise RuntimeError(f"injected HTTP status {self.request_status}")

    def _read(self, href: str) -> list[dict[str, object]]:
        if not href.endswith("/overlay"):
            raise AssertionError(href)
        if self.read_errors:
            raise self.read_errors.pop(0)
        return [dict(overlay) for overlay in self.overlays]

    def _create(
        self,
        href: str,
        payload: dict[str, object],
        *,
        follow_child: bool = True,
    ) -> None:
        if not href.endswith("/overlay"):
            raise AssertionError(href)
        self.create_calls += 1
        if self.fail_on_create == self.create_calls:
            raise RuntimeError("injected overlay create failure")
        if self.fail_on_create_not_found == self.create_calls:
            raise RuntimeError(
                f"The requested resource {href}/{self.create_calls} cannot be found"
            )
        if self.reject_create_after_clear and self.clear_calls:
            raise RuntimeError("overlay self link is not ready after clear")
        overlay = dict(payload)
        overlay["links"] = [
            {
                "rel": "self",
                "href": f"{href}/{self.create_calls}",
            }
        ]
        self.overlays.append(overlay)
        if self.merge_adjacent_same_value and len(self.overlays) >= 2:
            previous = self.overlays[-2]
            current = self.overlays[-1]
            previous_index = t.cast(int, previous["index"])
            previous_count = t.cast(int, previous["count"])
            current_index = t.cast(int, current["index"])
            previous_end = previous_index + previous_count
            if previous_end == current_index and previous["value"] == current["value"]:
                previous["count"] = previous_count + t.cast(int, current["count"])
                self.overlays.pop()
        if self.fail_after_create == self.create_calls:
            self.read_errors.extend(self.post_create_read_errors)
            if follow_child:
                raise RuntimeError(
                    f"The requested resource {href}/{self.create_calls} cannot be found"
                )

    def _update(self, href: str, payload: dict[str, object]) -> None:
        if payload == {"clearOverlays": True}:
            self.clear_calls += 1
            self.overlays = []
        elif "/overlay/" in href:
            if set(payload) != {"count", "index", "indexStep", "value"}:
                raise AssertionError(
                    "IXIA child updates must preserve the complete overlay geometry"
                )
            self.child_updates.append((href, dict(payload)))
            if self.fail_on_child_update == len(self.child_updates):
                raise RuntimeError("injected overlay update failure")
            for overlay in self.overlays:
                links = t.cast(list[dict[str, str]], overlay["links"])
                link_href = str(links[0]["href"])
                if link_href == href or link_href.endswith(href):
                    overlay.update(payload)
                    break
            else:
                raise AssertionError(href)


class _OverlayMultiValue:
    def __init__(self, value: object, count: int) -> None:
        self.Count = count
        self.PatternType = "Single"
        self.Pattern = value
        self._href = "/api/v1/sessions/1/ixnetwork/multivalue/1"
        self._connection = _OverlayConnection()
        self.overlay_calls = 0

    def _custom_select(self) -> None:
        pass

    @property
    def Values(self) -> list[object]:
        raise AssertionError("sparse overlays must not expand effective Values")

    def Overlay(self, index: int, value: object, count: int = 1) -> None:
        self.overlay_calls += 1
        self._connection._create(
            f"{self._href}/overlay",
            {"count": count, "index": index, "indexStep": 1, "value": value},
        )

    def ClearOverlays(self) -> None:
        self._connection._update(self._href, {"clearOverlays": True})
        self._connection._update(self._href, {"clearOverlays": False})


def _pool(
    count: int,
    addresses_per_row: int,
    starts: list[str],
    lasts: list[str],
    prefix_lengths: list[int],
    *,
    plain_values: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        Count=count,
        NumberOfAddresses=addresses_per_row,
        NetworkAddress=starts if plain_values else _MultiValue(starts),
        LastNetworkAddress=lasts if plain_values else _MultiValue(lasts),
        PrefixLength=prefix_lengths if plain_values else _MultiValue(prefix_lengths),
    )


class IxiaRouteGeometryTest(unittest.TestCase):
    def test_compact_geometry_maps_one_row_per_peer(self) -> None:
        geometry = IxiaRouteGeometry.from_pool(
            _pool(
                2,
                3,
                ["10.0.0.0", "11.0.0.0"],
                ["10.0.2.0", "11.0.2.0"],
                [24],
            ),
            ("192.0.2.1", "192.0.2.2"),
            peer_count=2,
            routes_per_peer=3,
            label="compact",
        )

        self.assertFalse(geometry.flattened)
        self.assertEqual((1,), geometry.physical_rows_for_peer(1))
        self.assertEqual(
            ("11.0.0.0", "11.0.2.0", 24),
            geometry.prefix_range_for_peer(1),
        )
        self.assertEqual((3, 4, 5), geometry.route_rows_for_peer(1))
        self.assertEqual("11.0.1.0/24", geometry.prefix_for_peer_route(1, 1))
        self.assertEqual(["a", "b"], geometry.expand_peer_values(("a", "b")))

    def test_flat_geometry_maps_complete_peer_ranges(self) -> None:
        geometry = IxiaRouteGeometry.from_pool(
            _pool(
                6,
                1,
                [f"10.0.{row}.0" for row in range(6)],
                [f"10.0.{row}.0" for row in range(6)],
                [24] * 6,
            ),
            ("192.0.2.1", "192.0.2.2"),
            peer_count=2,
            routes_per_peer=3,
            label="flat",
        )

        self.assertTrue(geometry.flattened)
        self.assertEqual((0, 1, 2), geometry.physical_rows_for_peer(0))
        self.assertEqual((3, 4, 5), geometry.physical_rows_for_peer(1))
        self.assertEqual((0, 2), geometry.endpoint_rows_for_peer(0))
        self.assertEqual(
            ("10.0.3.0", "10.0.5.0", 24),
            geometry.prefix_range_for_peer(1),
        )
        self.assertEqual((3, 4, 5), geometry.route_rows_for_peer(1))
        self.assertEqual("10.0.4.0/24", geometry.prefix_for_peer_route(1, 1))
        self.assertEqual(
            ["a", "a", "a", "b", "b", "b"],
            geometry.expand_peer_values(("a", "b")),
        )

    def test_compact_ipv6_prefix_preserves_address_family(self) -> None:
        geometry = IxiaRouteGeometry.from_pool(
            _pool(
                1,
                3,
                ["2001:db8::/64"],
                ["2001:db8:0:2::/64"],
                [64],
            ),
            ("2001:db8:ffff::1",),
            peer_count=1,
            routes_per_peer=3,
            label="compact v6",
        )

        self.assertEqual("2001:db8:0:1::/64", geometry.prefix_for_peer_route(0, 1))

    def test_prefix_rejects_mixed_address_family_range(self) -> None:
        geometry = IxiaRouteGeometry.from_pool(
            _pool(1, 2, ["10.0.0.0"], ["2001:db8::"], [24]),
            ("192.0.2.1",),
            peer_count=1,
            routes_per_peer=2,
            label="mixed family",
        )

        with self.assertRaisesRegex(TestCaseFailure, "mixes address families"):
            geometry.prefix_for_peer_route(0, 1)

    def test_reads_plain_and_mixed_read_only_values(self) -> None:
        plain_pool = _pool(
            2,
            3,
            ["10.0.0.0", "11.0.0.0"],
            ["10.0.2.0", "11.0.2.0"],
            [24],
            plain_values=True,
        )
        plain_geometry = IxiaRouteGeometry.from_pool(
            plain_pool,
            ("192.0.2.1", "192.0.2.2"),
            peer_count=2,
            routes_per_peer=3,
            label="plain",
        )
        mixed_pool = _pool(
            2,
            3,
            ["10.0.0.0", "11.0.0.0"],
            ["10.0.2.0", "11.0.2.0"],
            [24],
        )
        mixed_pool.LastNetworkAddress = list(mixed_pool.LastNetworkAddress.Values)
        mixed_geometry = IxiaRouteGeometry.from_pool(
            mixed_pool,
            ("192.0.2.1", "192.0.2.2"),
            peer_count=2,
            routes_per_peer=3,
            label="mixed",
        )

        self.assertEqual(("10.0.2.0", "11.0.2.0"), plain_geometry.lasts)
        self.assertEqual(
            plain_geometry, dataclasses.replace(mixed_geometry, label="plain")
        )

    def test_rejects_malformed_read_only_values(self) -> None:
        bad_length = _pool(
            2,
            3,
            ["10.0.0.0"],
            ["10.0.2.0", "11.0.2.0"],
            [24],
            plain_values=True,
        )
        with self.assertRaisesRegex(TestCaseFailure, "NetworkAddress has 1 rows"):
            IxiaRouteGeometry.from_pool(
                bad_length,
                ("192.0.2.1", "192.0.2.2"),
                peer_count=2,
                routes_per_peer=3,
                label="bad length",
            )

        for field_value in (42, "10.0.0.0"):
            bad_type = _pool(
                2,
                3,
                ["10.0.0.0", "11.0.0.0"],
                ["10.0.2.0", "11.0.2.0"],
                [24],
            )
            bad_type.LastNetworkAddress = field_value
            with (
                self.subTest(field_value=field_value),
                self.assertRaisesRegex(
                    TestCaseFailure, "LastNetworkAddress must be an iterable"
                ),
            ):
                IxiaRouteGeometry.from_pool(
                    bad_type,
                    ("192.0.2.1", "192.0.2.2"),
                    peer_count=2,
                    routes_per_peer=3,
                    label="bad type",
                )

    def test_rejects_hybrid_geometry_and_bad_vectors(self) -> None:
        with self.assertRaisesRegex(TestCaseFailure, "unsupported IXIA"):
            IxiaRouteGeometry.from_pool(
                _pool(2, 1, ["a", "b"], ["a", "b"], [24]),
                ("192.0.2.1", "192.0.2.2"),
                peer_count=2,
                routes_per_peer=3,
                label="hybrid",
            )

        geometry = IxiaRouteGeometry.from_pool(
            _pool(6, 1, ["a"] * 6, ["a"] * 6, [24]),
            ("192.0.2.1", "192.0.2.2"),
            peer_count=2,
            routes_per_peer=3,
            label="flat",
        )
        with self.assertRaisesRegex(TestCaseFailure, "expected 1 or 6"):
            geometry.value_at((1, 2), 0, "attribute")

    def test_vector_expands_selected_rows_and_restores_singleton(self) -> None:
        handle = _MultiValue(["true"])
        vector = IxiaValueVector.capture(handle, 6, "Active")

        vector.write_rows((1, 4), "false")

        self.assertEqual(
            ["true", "false", "true", "true", "false", "true"],
            handle.Values,
        )
        vector.restore()
        self.assertEqual(["true"], handle.Values)
        self.assertEqual(["true"], handle.single_calls)
        self.assertTrue(vector.is_exactly_restored())

    def test_vector_restores_full_shape_with_value_list(self) -> None:
        handle = _MultiValue([0, 1, 2])
        vector = IxiaValueVector.capture(handle, 3, "MED")
        vector.write_rows((1,), 99)

        vector.restore()

        self.assertEqual([0, 1, 2], handle.Values)
        self.assertEqual([0, 1, 2], handle.value_list_calls[-1])
        self.assertEqual([], handle.single_calls)

    def test_vector_preserves_single_entry_value_list_pattern(self) -> None:
        handle = _PatternMultiValue([7], "valueList", {"values": [7]})
        vector = IxiaValueVector.capture(handle, 1, "MED")
        handle.Single(99)

        vector.restore()

        self.assertEqual([7], handle.Values)
        self.assertEqual([7], handle.value_list_calls[-1])
        self.assertTrue(vector.is_exactly_restored())

    def test_vector_captures_properties_replaced_by_lazy_pattern_resolution(
        self,
    ) -> None:
        handle = _LazyPatternMultiValue([7], "valueList", {"values": [7]})

        vector = IxiaValueVector.capture(handle, 1, "MED")

        self.assertIsNotNone(vector.pattern)
        self.assertEqual("valueList", vector.pattern.pattern)

    def test_vector_preserves_increment_pattern(self) -> None:
        handle = _PatternMultiValue(
            [10, 12, 14],
            "counter",
            {"direction": "increment", "start": 10, "step": 2, "count": 3},
        )
        vector = IxiaValueVector.capture(handle, 3, "MED")
        handle.ValueList([1, 1, 1])

        vector.restore()

        self.assertEqual([10, 12, 14], handle.Values)
        self.assertEqual([(10, 2, 3)], handle.increment_calls)
        self.assertEqual("counter", handle._properties["pattern"])
        self.assertTrue(vector.is_exactly_restored())

    def test_vector_rejects_nonrepeatable_random_pattern(self) -> None:
        handle = _PatternMultiValue([1, 2], "random", {})

        with self.assertRaisesRegex(TestCaseFailure, "non-repeatable"):
            IxiaValueVector.capture(handle, 2, "random")

    def test_vector_rejects_unknown_pattern_before_mutation(self) -> None:
        handle = _PatternMultiValue([1, 2], "futurePattern", {"value": 1})

        with self.assertRaisesRegex(TestCaseFailure, "unsupported IXIA pattern"):
            IxiaValueVector.capture(handle, 2, "future")

    def test_vector_rejects_missing_pattern_metadata_before_mutation(self) -> None:
        handle = SimpleNamespace(Values=[1, 2])

        with self.assertRaisesRegex(TestCaseFailure, "no restorable IXIA _properties"):
            IxiaValueVector.capture(handle, 2, "missing metadata")

    def test_vector_rejects_pattern_payload_missing_required_fields(self) -> None:
        for pattern, payload in (
            ("singleValue", {}),
            ("valueList", {}),
            ("alternate", {}),
        ):
            handle = _PatternMultiValue([1], pattern, payload)
            with (
                self.subTest(pattern=pattern),
                self.assertRaisesRegex(TestCaseFailure, "missing required fields"),
            ):
                IxiaValueVector.capture(handle, 1, pattern)

    def test_vector_rejects_custom_pattern_missing_start_or_step(self) -> None:
        for missing_field, payload in (
            ("start", {"step": 1, "increment": []}),
            ("step", {"start": 0, "increment": []}),
        ):
            handle = _PatternMultiValue([1], "custom", payload)
            with (
                self.subTest(missing_field=missing_field),
                self.assertRaisesRegex(TestCaseFailure, missing_field),
            ):
                IxiaValueVector.capture(handle, 1, "custom")

    def test_vector_rejects_malformed_nested_pattern_payloads(self) -> None:
        for pattern, payload in (
            ("customDistributed", {"values": [{"arg1": 1}]}),
            (
                "custom",
                {"start": 0, "step": 1, "increment": [{"value": 1}]},
            ),
        ):
            handle = _PatternMultiValue([1], pattern, payload)
            with (
                self.subTest(pattern=pattern),
                self.assertRaisesRegex(TestCaseFailure, "missing required fields"),
            ):
                IxiaValueVector.capture(handle, 1, pattern)

    def test_vector_expands_and_restores_compact_peer_shape(self) -> None:
        handle = _MultiValue(["peer-0", "peer-1"])
        vector = IxiaValueVector.capture(
            handle,
            6,
            "Active",
            compact_row_count=2,
        )

        self.assertEqual(6, vector.expanded_row_count)
        self.assertEqual(2, vector.compact_row_count)
        self.assertEqual("peer-0", vector.baseline_value(2))
        self.assertEqual("peer-1", vector.baseline_value(3))

        handle.Values = ["changed-0", "changed-1"]
        self.assertEqual("changed-0", vector.current_value(2))
        self.assertEqual("changed-1", vector.current_value(3))
        handle.Values = ["peer-0", "peer-1"]

        vector.write_rows((1, 4), "false")

        self.assertEqual(
            ["peer-0", "false", "peer-0", "peer-1", "false", "peer-1"],
            handle.Values,
        )
        vector.restore()
        self.assertEqual(["peer-0", "peer-1"], handle.Values)
        self.assertTrue(vector.is_exactly_restored())

    def test_vector_rejects_invalid_compact_shape(self) -> None:
        with self.assertRaisesRegex(TestCaseFailure, "does not divide"):
            IxiaValueVector.capture(
                _MultiValue([1, 2]),
                5,
                "Active",
                compact_row_count=2,
            )

    def test_fixed_count_plan_is_exact_for_flat_shape(self) -> None:
        handle = _MultiValue(["true"] * 6)
        vector = IxiaValueVector.capture(handle, 6, "Active")

        expected, write = vector.plan_fixed_count_write((1, 4), "false")

        self.assertEqual(
            ("true", "false", "true", "true", "false", "true"),
            expected,
        )
        self.assertEqual(expected, write)
        vector.write_fixed_count(write)
        vector.assert_exact_fixed_count_readback(expected)

    def test_fixed_count_plan_compresses_uniform_expanded_blocks(self) -> None:
        handle = _MultiValue(["true", "true"], count=2)
        vector = IxiaValueVector.capture(
            handle,
            6,
            "Active",
            compact_row_count=2,
        )

        expected, write = vector.plan_fixed_count_write((0, 1, 2), "false")

        self.assertEqual(("false", "true"), write)
        vector.write_fixed_count(write)
        vector.assert_exact_fixed_count_readback(expected)

    def test_fixed_count_plan_rejects_partial_compact_block_before_write(self) -> None:
        handle = _MultiValue(["true", "true"], count=2)
        vector = IxiaValueVector.capture(
            handle,
            6,
            "Active",
            compact_row_count=2,
        )

        with self.assertRaisesRegex(TestCaseFailure, "not representable"):
            vector.plan_fixed_count_write((0, 1), "false")

        self.assertEqual([], handle.value_list_calls)
        self.assertEqual(["true", "true"], handle.Values)

    def test_fixed_count_plan_rejects_count_and_values_mismatches(self) -> None:
        count_mismatch = IxiaValueVector.capture(
            _MultiValue(["true"] * 2, count=3),
            6,
            "Active",
            compact_row_count=2,
        )
        with self.assertRaisesRegex(TestCaseFailure, "Count is 3, expected 2"):
            count_mismatch.plan_fixed_count_write((), "false")

        values_handle = _MultiValue(["true"] * 2, count=2)
        values_mismatch = IxiaValueVector.capture(
            values_handle,
            6,
            "Active",
            compact_row_count=2,
        )
        values_handle.Values = ["true"] * 3
        with self.assertRaisesRegex(TestCaseFailure, "effective Values has 3"):
            values_mismatch.plan_fixed_count_write((), "false")

    def test_fixed_count_readback_rejects_mismatch_and_mixed_singleton(self) -> None:
        handle = _MultiValue(["true", "true"], count=2)
        vector = IxiaValueVector.capture(
            handle,
            6,
            "Active",
            compact_row_count=2,
        )
        expected, _write = vector.plan_fixed_count_write((0, 1, 2), "false")

        with self.assertRaisesRegex(TestCaseFailure, "does not match"):
            vector.assert_exact_fixed_count_readback(expected)

        handle.Values = ["false"]
        with self.assertRaisesRegex(TestCaseFailure, "singleton.*mixed"):
            vector.assert_exact_fixed_count_readback(expected)

    def test_overlay_vector_writes_sparse_ranges_without_expanding_values(self) -> None:
        handle = _OverlayMultiValue(100, 46_500)
        handle._connection.reject_create_after_clear = True
        vector = IxiaOverlayVector.capture(handle, 46_500, "LocalPreference")
        rows = tuple(range(0, 750)) + tuple(range(7_500, 8_250))

        vector.write_rows(rows, 200)
        vector.assert_exact_readback()

        self.assertEqual(
            [
                {
                    "count": 750,
                    "index": 1,
                    "indexStep": 1,
                    "value": 200,
                },
                {
                    "count": 750,
                    "index": 7_501,
                    "indexStep": 1,
                    "value": 200,
                },
            ],
            [
                {key: value for key, value in overlay.items() if key != "links"}
                for overlay in handle._connection.overlays
            ],
        )
        self.assertEqual(0, handle._connection.clear_calls)
        self.assertEqual(2, handle._connection.create_calls)
        self.assertEqual(0, handle.overlay_calls)
        self.assertTrue(
            all(
                call["allow_redirects"] is False
                and call["headers"] == {"Content-Type": "application/json"}
                for call in handle._connection.request_calls
            )
        )
        self.assertEqual(200, vector.current_value(0))
        self.assertEqual(100, vector.current_value(7499))
        self.assertEqual(
            (0, 749, 750, 7_499, 7_500, 8_249, 8_250, 46_499),
            vector.audit_rows(),
        )

        vector.restore()

        self.assertEqual([], handle._connection.overlays)
        self.assertTrue(vector.is_exactly_restored())

    def test_overlay_vector_updates_existing_shape_in_place(self) -> None:
        handle = _OverlayMultiValue(100, 10)
        vector = IxiaOverlayVector.capture(handle, 10, "LocalPreference")

        vector.write_rows((1, 2, 5), 200)
        for overlay in handle._connection.overlays:
            links = t.cast(list[dict[str, str]], overlay["links"])
            links[0]["href"] = f"https://ixia.example{links[0]['href']}"
        vector.write_rows((1, 2, 5), 300)

        self.assertEqual(2, handle._connection.create_calls)
        self.assertEqual(0, handle._connection.clear_calls)
        self.assertEqual(
            [
                (
                    "/api/v1/sessions/1/ixnetwork/multivalue/1/overlay/1",
                    {"count": 2, "index": 2, "indexStep": 1, "value": 300},
                ),
                (
                    "/api/v1/sessions/1/ixnetwork/multivalue/1/overlay/2",
                    {"count": 1, "index": 6, "indexStep": 1, "value": 300},
                ),
            ],
            handle._connection.child_updates,
        )
        vector.assert_exact_readback()
        self.assertEqual(300, vector.current_value(1))

    def test_overlay_vector_appends_nonoverlapping_rows(self) -> None:
        handle = _OverlayMultiValue(False, 10)
        vector = IxiaOverlayVector.capture(handle, 10, "Active")

        vector.append_rows((0, 1, 2), True)
        vector.append_rows((5, 6), True)

        self.assertEqual(
            (
                IxiaOverlay(index=1, count=3, value=True),
                IxiaOverlay(index=6, count=2, value=True),
            ),
            vector.expected_overlays,
        )
        self.assertEqual(2, handle._connection.create_calls)
        vector.assert_exact_readback(refresh_base=True)

    def test_overlay_vector_accepts_server_merged_appended_rows(self) -> None:
        handle = _OverlayMultiValue(False, 10)
        handle._connection.merge_adjacent_same_value = True
        vector = IxiaOverlayVector.capture(handle, 10, "Active")

        vector.append_rows((0, 1, 2), True)
        vector.expected_overlays = (
            IxiaOverlay(index=1, count=2, value=True),
            IxiaOverlay(index=3, count=1, value=True),
        )
        vector.append_rows((3, 4), True)

        self.assertEqual(
            (IxiaOverlay(index=1, count=5, value=True),),
            vector.expected_overlays,
        )
        self.assertEqual(2, handle._connection.create_calls)
        vector.assert_exact_readback(refresh_base=True)

    def test_overlay_vector_rejects_overlapping_appended_rows(self) -> None:
        handle = _OverlayMultiValue(False, 10)
        vector = IxiaOverlayVector.capture(handle, 10, "Active")
        vector.append_rows((0, 1, 2), True)

        with self.assertRaisesRegex(TestCaseFailure, "overlapping ranges"):
            vector.append_rows((2, 3), True)

        self.assertEqual(1, handle._connection.create_calls)

    def test_overlay_vector_rejects_appended_base_value(self) -> None:
        handle = _OverlayMultiValue(False, 10)
        vector = IxiaOverlayVector.capture(handle, 10, "Active")

        with self.assertRaisesRegex(TestCaseFailure, "equal to the base value"):
            vector.append_rows((0, 1), False)

        self.assertEqual(0, handle._connection.create_calls)

    def test_overlay_vector_elides_writes_equal_to_topology_base(self) -> None:
        handle = _OverlayMultiValue(True, 10)
        vector = IxiaOverlayVector.capture(handle, 10, "MED enable")

        vector.write_rows((1, 2, 5), "true")

        self.assertEqual(0, handle._connection.create_calls)
        self.assertEqual(0, handle._connection.clear_calls)
        self.assertEqual((), vector.expected_overlays)
        self.assertFalse(vector.touched)
        vector.assert_exact_readback()

    def test_overlay_vector_clears_owned_shape_when_writing_topology_base(
        self,
    ) -> None:
        handle = _OverlayMultiValue(100, 10)
        vector = IxiaOverlayVector.capture(handle, 10, "LocalPreference")
        vector.write_rows((1, 2, 5), 200)

        vector.write_rows((1, 2, 5), 100)

        self.assertEqual(2, handle._connection.create_calls)
        self.assertEqual(1, handle._connection.clear_calls)
        self.assertEqual([], handle._connection.overlays)
        self.assertEqual((), vector.expected_overlays)
        vector.assert_exact_readback()

    def test_overlay_vector_rejects_shape_change_before_clearing_to_base(
        self,
    ) -> None:
        handle = _OverlayMultiValue(100, 10)
        vector = IxiaOverlayVector.capture(handle, 10, "LocalPreference")
        vector.write_rows((1, 2, 5), 200)

        with self.assertRaisesRegex(TestCaseFailure, "overlay shape changed"):
            vector.write_rows((1, 2, 6), 100)

        self.assertEqual(0, handle._connection.clear_calls)
        vector.assert_exact_readback()

    def test_overlay_vector_rejects_shape_change_before_update(self) -> None:
        handle = _OverlayMultiValue(100, 10)
        vector = IxiaOverlayVector.capture(handle, 10, "LocalPreference")
        vector.write_rows((1, 2, 5), 200)

        with self.assertRaisesRegex(TestCaseFailure, "overlay shape changed"):
            vector.write_rows((1, 2, 6), 300)

        self.assertEqual(2, handle._connection.create_calls)
        self.assertEqual([], handle._connection.child_updates)
        vector.assert_exact_readback()

    def test_overlay_vector_rejects_untrusted_links_before_update(self) -> None:
        link_sets: tuple[tuple[str, list[dict[str, str]]], ...] = (
            ("missing", []),
            (
                "out-of-scope",
                [
                    {
                        "rel": "self",
                        "href": "/api/v1/sessions/1/ixnetwork/multivalue/2/overlay/1",
                    }
                ],
            ),
            (
                "multiple self links",
                [
                    {
                        "rel": "self",
                        "href": "/api/v1/sessions/1/ixnetwork/multivalue/1/overlay/1",
                    },
                    {
                        "rel": "self",
                        "href": "/api/v1/sessions/1/ixnetwork/multivalue/1/overlay/2",
                    },
                ],
            ),
        )
        for name, links in link_sets:
            with self.subTest(name=name):
                handle = _OverlayMultiValue(100, 10)
                vector = IxiaOverlayVector.capture(handle, 10, "LocalPreference")
                vector.write_rows((1, 2, 5), 200)
                handle._connection.overlays[0]["links"] = links

                with self.assertRaises(TestCaseFailure):
                    vector.write_rows((1, 2, 5), 300)

                self.assertEqual([], handle._connection.child_updates)

    def test_overlay_vector_updates_collection_entries_with_meta_links(self) -> None:
        handle = _OverlayMultiValue(100, 10)
        vector = IxiaOverlayVector.capture(handle, 10, "LocalPreference")
        vector.write_rows((1, 2, 5), 200)
        for child_id, overlay in enumerate(handle._connection.overlays, start=1):
            overlay["id"] = child_id
            overlay["links"] = [
                {
                    "rel": "meta",
                    "href": f"{handle._href}/overlay/{child_id}",
                    "method": "OPTIONS",
                }
            ]

        vector.write_rows((1, 2, 5), 300)

        self.assertEqual(
            [
                (
                    f"{handle._href}/overlay/1",
                    {"count": 2, "index": 2, "indexStep": 1, "value": 300},
                ),
                (
                    f"{handle._href}/overlay/2",
                    {"count": 1, "index": 6, "indexStep": 1, "value": 300},
                ),
            ],
            handle._connection.child_updates,
        )
        vector.assert_exact_readback()

    def test_overlay_vector_updates_reordered_noncontiguous_collection_ids(
        self,
    ) -> None:
        handle = _OverlayMultiValue(100, 10)
        vector = IxiaOverlayVector.capture(handle, 10, "LocalPreference")
        vector.write_rows((1, 2, 5), 200)
        for overlay, child_id in zip(
            handle._connection.overlays,
            ("11", 7),
        ):
            overlay["id"] = child_id
            overlay["links"] = [
                {
                    "rel": "meta",
                    "href": f"{handle._href}/overlay/{child_id}",
                    "method": "OPTIONS",
                }
            ]
        handle._connection.overlays.reverse()

        vector.write_rows((1, 2, 5), 300)

        self.assertEqual(
            [
                (
                    f"{handle._href}/overlay/11",
                    {"count": 2, "index": 2, "indexStep": 1, "value": 300},
                ),
                (
                    f"{handle._href}/overlay/7",
                    {"count": 1, "index": 6, "indexStep": 1, "value": 300},
                ),
            ],
            handle._connection.child_updates,
        )
        vector.restore()
        self.assertEqual([], handle._connection.overlays)

    def test_overlay_vector_rejects_invalid_collection_ids_before_update(self) -> None:
        for overlay_id in (True, 1.5, 0, -1, "01", "invalid"):
            with self.subTest(overlay_id=overlay_id):
                handle = _OverlayMultiValue(100, 10)
                vector = IxiaOverlayVector.capture(handle, 10, "LocalPreference")
                vector.write_rows((1, 2, 5), 200)
                handle._connection.overlays[0]["id"] = overlay_id
                handle._connection.overlays[0]["links"] = [
                    {
                        "rel": "meta",
                        "href": f"{handle._href}/overlay/1",
                        "method": "OPTIONS",
                    }
                ]

                with self.assertRaises(TestCaseFailure):
                    vector.write_rows((1, 2, 5), 300)

                self.assertEqual([], handle._connection.child_updates)

    def test_overlay_vector_rejects_conflicting_self_link_and_id(self) -> None:
        handle = _OverlayMultiValue(100, 10)
        vector = IxiaOverlayVector.capture(handle, 10, "LocalPreference")
        vector.write_rows((1, 2, 5), 200)
        handle._connection.overlays[0]["id"] = 2

        with self.assertRaisesRegex(TestCaseFailure, "conflicts with its id"):
            vector.write_rows((1, 2, 5), 300)

        self.assertEqual([], handle._connection.child_updates)

    def test_overlay_vector_rejects_conflicting_meta_link_and_id(self) -> None:
        handle = _OverlayMultiValue(100, 10)
        vector = IxiaOverlayVector.capture(handle, 10, "LocalPreference")
        vector.write_rows((1, 2, 5), 200)
        handle._connection.overlays[0]["id"] = 2
        handle._connection.overlays[0]["links"] = [
            {
                "rel": "meta",
                "href": f"{handle._href}/overlay/1",
                "method": "OPTIONS",
            }
        ]

        with self.assertRaisesRegex(TestCaseFailure, "conflicts with its id"):
            vector.write_rows((1, 2, 5), 300)

        self.assertEqual([], handle._connection.child_updates)

    def test_overlay_vector_rejects_malformed_link_entry(self) -> None:
        handle = _OverlayMultiValue(100, 10)
        vector = IxiaOverlayVector.capture(handle, 10, "LocalPreference")
        vector.write_rows((1, 2, 5), 200)
        handle._connection.overlays[0]["id"] = 1
        handle._connection.overlays[0]["links"] = ["malformed"]

        with self.assertRaisesRegex(TestCaseFailure, "links are malformed"):
            vector.write_rows((1, 2, 5), 300)

        self.assertEqual([], handle._connection.child_updates)

    def test_overlay_vector_rejects_duplicate_child_links_before_update(self) -> None:
        handle = _OverlayMultiValue(100, 10)
        vector = IxiaOverlayVector.capture(handle, 10, "LocalPreference")
        vector.write_rows((1, 2, 5), 200)
        handle._connection.overlays[1]["links"] = handle._connection.overlays[0][
            "links"
        ]

        with self.assertRaisesRegex(TestCaseFailure, "duplicate child links"):
            vector.write_rows((1, 2, 5), 300)

        self.assertEqual([], handle._connection.child_updates)

    def test_overlay_vector_rejects_duplicate_collection_ids_before_update(
        self,
    ) -> None:
        handle = _OverlayMultiValue(100, 10)
        vector = IxiaOverlayVector.capture(handle, 10, "LocalPreference")
        vector.write_rows((1, 2, 5), 200)
        for overlay in handle._connection.overlays:
            overlay["id"] = 1
            overlay["links"] = [
                {
                    "rel": "meta",
                    "href": f"{handle._href}/overlay/1",
                    "method": "OPTIONS",
                }
            ]

        with self.assertRaisesRegex(TestCaseFailure, "duplicate child links"):
            vector.write_rows((1, 2, 5), 300)

        self.assertEqual([], handle._connection.child_updates)

    def test_overlay_vector_partial_create_is_restorable(self) -> None:
        handle = _OverlayMultiValue(100, 10)
        handle._connection.fail_on_create = 2
        vector = IxiaOverlayVector.capture(handle, 10, "LocalPreference")

        with self.assertRaisesRegex(RuntimeError, "injected overlay create failure"):
            vector.write_rows((1, 2, 5), 200)

        self.assertTrue(vector.touched)
        self.assertEqual(1, len(handle._connection.overlays))
        vector.restore()
        self.assertEqual([], handle._connection.overlays)

    def test_overlay_vector_reconciles_post_create_child_visibility(self) -> None:
        handle = _OverlayMultiValue(100, 10)
        handle._connection.fail_after_create = 1
        vector = IxiaOverlayVector.capture(handle, 10, "LocalPreference")

        vector.write_rows((1, 2, 5), 200)

        self.assertEqual(2, handle._connection.create_calls)
        vector.assert_exact_readback()
        self.assertEqual(200, vector.current_value(1))

    def test_overlay_vector_reconciles_non_prefix_visible_subset(self) -> None:
        handle = _OverlayMultiValue(100, 10)
        vector = IxiaOverlayVector.capture(handle, 10, "LocalPreference")
        expected = (
            IxiaOverlay(index=2, count=2, value=200),
            IxiaOverlay(index=6, count=1, value=200),
        )

        with (
            patch.object(
                vector,
                "_read_overlays",
                side_effect=((expected[1],), expected),
            ),
            patch.object(
                IxiaOverlayVector,
                "_CREATE_RECONCILE_POLL_SECONDS",
                0.0,
            ),
        ):
            self.assertTrue(vector._reconcile_created_overlays(expected))

    def test_overlay_vector_reconciliation_rejects_unexpected_subset(self) -> None:
        handle = _OverlayMultiValue(100, 10)
        vector = IxiaOverlayVector.capture(handle, 10, "LocalPreference")
        expected = (IxiaOverlay(index=2, count=2, value=200),)
        unexpected = (IxiaOverlay(index=6, count=1, value=200),)

        with patch.object(vector, "_read_overlays", return_value=unexpected):
            self.assertFalse(vector._reconcile_created_overlays(expected))

    def test_overlay_vector_fallback_reconciles_ambiguous_child_lookup(self) -> None:
        handle = _OverlayMultiValue(100, 10)
        handle._connection.fail_after_create = 1
        vector = IxiaOverlayVector.capture(handle, 10, "LocalPreference")

        with patch.object(handle._connection, "_request", None):
            vector.write_rows((1, 2, 5), 200)

        self.assertEqual(2, handle.overlay_calls)
        vector.assert_exact_readback()

    def test_overlay_vector_fallback_preserves_unconfirmed_child_error(self) -> None:
        handle = _OverlayMultiValue(100, 10)
        handle._connection.fail_on_create_not_found = 1
        vector = IxiaOverlayVector.capture(handle, 10, "LocalPreference")

        with (
            patch.object(handle._connection, "_request", None),
            patch.object(
                IxiaOverlayVector,
                "_CREATE_RECONCILE_TIMEOUT_SECONDS",
                0.0,
            ),
            self.assertRaisesRegex(
                TestCaseFailure,
                "created overlays did not converge",
            ) as context,
        ):
            vector.write_rows((1, 2), 200)

        self.assertIsInstance(context.exception.__cause__, RuntimeError)
        self.assertIn("cannot be found", str(context.exception.__cause__))

    def test_overlay_vector_reconciled_partial_create_is_restorable(self) -> None:
        handle = _OverlayMultiValue(100, 10)
        handle._connection.fail_after_create = 1
        handle._connection.fail_on_create = 2
        vector = IxiaOverlayVector.capture(handle, 10, "LocalPreference")

        with self.assertRaisesRegex(RuntimeError, "injected overlay create failure"):
            vector.write_rows((1, 2, 5), 200)

        self.assertEqual(1, len(handle._connection.overlays))
        vector.restore()
        self.assertEqual([], handle._connection.overlays)

    def test_overlay_vector_does_not_reconcile_unrelated_create_error(self) -> None:
        handle = _OverlayMultiValue(100, 10)
        handle._connection.fail_on_create = 1
        vector = IxiaOverlayVector.capture(handle, 10, "LocalPreference")

        with self.assertRaisesRegex(RuntimeError, "injected overlay create failure"):
            vector.write_rows((1, 2), 200)

        self.assertEqual(1, handle._connection.create_calls)

    def test_overlay_vector_rejects_failed_raw_post(self) -> None:
        handle = _OverlayMultiValue(100, 10)
        handle._connection.request_status = 500
        vector = IxiaOverlayVector.capture(handle, 10, "LocalPreference")

        with self.assertRaisesRegex(RuntimeError, "injected HTTP status 500"):
            vector.write_rows((1, 2), 200)

        self.assertTrue(vector.touched)
        self.assertEqual([], handle._connection.overlays)

    def test_overlay_vector_rejects_untrusted_post_self_link(self) -> None:
        handle = _OverlayMultiValue(100, 10)
        handle._connection.response_body_override = {
            "links": [
                {
                    "rel": "self",
                    "href": "/api/v1/sessions/1/ixnetwork/multivalue/2/overlay/1",
                }
            ]
        }
        vector = IxiaOverlayVector.capture(handle, 10, "LocalPreference")

        with self.assertRaisesRegex(TestCaseFailure, "outside its multivalue"):
            vector.write_rows((1, 2), 200)

        self.assertEqual(1, len(handle._connection.overlays))
        vector.restore()
        self.assertEqual([], handle._connection.overlays)

    def test_overlay_vector_accepts_post_id_with_meta_link(self) -> None:
        handle = _OverlayMultiValue(100, 10)
        handle._connection.response_body_override = {
            "id": 1,
            "links": [
                {
                    "rel": "meta",
                    "href": f"{handle._href}/overlay/1",
                    "method": "OPTIONS",
                }
            ],
        }
        vector = IxiaOverlayVector.capture(handle, 10, "LocalPreference")

        vector.write_rows((1, 2), 200)

        self.assertEqual(1, handle._connection.create_calls)
        vector.assert_exact_readback()

    def test_overlay_vector_reraises_unconfirmed_child_not_found(self) -> None:
        handle = _OverlayMultiValue(100, 10)
        handle._connection.fail_on_create_not_found = 1
        vector = IxiaOverlayVector.capture(handle, 10, "LocalPreference")

        with (
            patch.object(
                IxiaOverlayVector,
                "_CREATE_RECONCILE_TIMEOUT_SECONDS",
                0.0,
            ),
            self.assertRaisesRegex(RuntimeError, "cannot be found"),
        ):
            vector.write_rows((1, 2), 200)

        self.assertEqual(1, handle._connection.create_calls)
        self.assertEqual([], handle._connection.overlays)

    def test_overlay_vector_preserves_reconciliation_timeout(self) -> None:
        handle = _OverlayMultiValue(100, 10)
        vector = IxiaOverlayVector.capture(handle, 10, "LocalPreference")
        handle._connection.fail_after_create = 1
        deadline_error = TimeoutError("geometry request deadline expired")
        handle._connection.post_create_read_errors = [deadline_error]

        with self.assertRaises(TimeoutError) as context:
            vector.write_rows((1, 2), 200)

        self.assertIs(deadline_error, context.exception)
        self.assertEqual(1, handle._connection.create_calls)

    def test_overlay_vector_retries_matching_reconciliation_read_404(self) -> None:
        handle = _OverlayMultiValue(100, 10)
        vector = IxiaOverlayVector.capture(handle, 10, "LocalPreference")
        handle._connection.fail_after_create = 1
        handle._connection.post_create_read_errors = [
            RuntimeError(
                "The requested resource "
                "/api/v1/sessions/1/ixnetwork/multivalue/1/overlay/1 "
                "cannot be found"
            )
        ]

        with patch.object(
            IxiaOverlayVector,
            "_CREATE_RECONCILE_POLL_SECONDS",
            0.0,
        ):
            vector.write_rows((1, 2), 200)

        self.assertEqual(1, handle._connection.create_calls)
        vector.assert_exact_readback()

    def test_overlay_vector_reports_reconciliation_child_visibility_timeout(
        self,
    ) -> None:
        handle = _OverlayMultiValue(100, 10)
        vector = IxiaOverlayVector.capture(handle, 10, "LocalPreference")
        handle._connection.fail_after_create = 1
        child_error = RuntimeError(
            "The requested resource "
            "/api/v1/sessions/1/ixnetwork/multivalue/1/overlay/1 "
            "cannot be found"
        )
        handle._connection.post_create_read_errors = [child_error]

        with (
            patch.object(
                IxiaOverlayVector,
                "_CREATE_RECONCILE_TIMEOUT_SECONDS",
                0.0,
            ),
            self.assertRaisesRegex(
                TestCaseFailure,
                "overlay child visibility did not converge",
            ) as context,
        ):
            vector.write_rows((1, 2), 200)

        self.assertIs(child_error, context.exception.__cause__)

    def test_overlay_vector_partial_update_is_restorable(self) -> None:
        handle = _OverlayMultiValue(100, 10)
        vector = IxiaOverlayVector.capture(handle, 10, "LocalPreference")
        vector.write_rows((1, 2, 5), 200)
        handle._connection.fail_on_child_update = 2

        with self.assertRaisesRegex(RuntimeError, "injected overlay update failure"):
            vector.write_rows((1, 2, 5), 300)

        self.assertEqual(300, handle._connection.overlays[0]["value"])
        self.assertEqual(200, handle._connection.overlays[1]["value"])
        vector.restore()
        self.assertEqual([], handle._connection.overlays)

    def test_overlay_vector_rejects_tampered_readback(self) -> None:
        handle = _OverlayMultiValue("true", 10)
        vector = IxiaOverlayVector.capture(handle, 10, "AS enable")
        vector.write_rows((1, 2), "false")
        handle._connection.overlays[0]["count"] = 3

        with self.assertRaisesRegex(TestCaseFailure, "overlay readback mismatch"):
            vector.assert_exact_readback()

    def test_overlay_vector_rejects_ambiguous_topology_base(self) -> None:
        handle = _OverlayMultiValue(100, 10)
        handle._connection.overlays.append(
            {"count": 1, "index": 1, "indexStep": 1, "value": 200}
        )
        with self.assertRaisesRegex(TestCaseFailure, "pre-existing overlays"):
            IxiaOverlayVector.capture(handle, 10, "LocalPreference")

        handle._connection.overlays = []
        handle.PatternType = "ValueList"
        with self.assertRaisesRegex(TestCaseFailure, "expected 'Single'"):
            IxiaOverlayVector.capture(handle, 10, "LocalPreference")

    def test_overlay_vector_restoration_refreshes_base_and_count(self) -> None:
        handle = _OverlayMultiValue(100, 10)
        vector = IxiaOverlayVector.capture(handle, 10, "LocalPreference")
        vector.write_rows((0,), 200)

        handle.Count = 11
        with self.assertRaisesRegex(TestCaseFailure, "Count changed"):
            vector.is_exactly_restored()

        handle.Count = 10
        handle.Pattern = 101
        with self.assertRaisesRegex(TestCaseFailure, "topology base changed"):
            vector.is_exactly_restored()

    def test_overlay_vector_rejects_malformed_overlay_metadata(self) -> None:
        for field, value, message in (
            ("index", True, "must be an integer"),
            ("index", 1.9, "must be an integer"),
            ("count", 0, "must be positive"),
            ("indexStep", 2, "expected 1"),
        ):
            with self.subTest(field=field, value=value):
                handle = _OverlayMultiValue(100, 10)
                vector = IxiaOverlayVector.capture(handle, 10, "LocalPreference")
                handle._connection.overlays.append(
                    {"count": 1, "index": 1, "indexStep": 1, "value": 200}
                )
                handle._connection.overlays[0][field] = value

                with self.assertRaisesRegex(TestCaseFailure, message):
                    vector.assert_exact_readback()


if __name__ == "__main__":
    unittest.main()
