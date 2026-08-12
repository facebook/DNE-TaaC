# pyre-unsafe
# Copyright (c) Meta Platforms, Inc. and affiliates.
import json
import unittest
from unittest.mock import MagicMock, patch

from ixia.ixia import types as ixia_types
from taac.ixia.ixia import Ixia


class _MultiValue:
    def __init__(self, values=None):
        self.Values = list(values or [])

    def Single(self, value):
        self.Values = [value]

    def ValueList(self, values):
        self.Values = list(values)


class _ExtendedCommunity:
    def __init__(self):
        self.Type = _MultiValue()
        self.SubType = _MultiValue()
        self.AsNumber2Bytes = _MultiValue()
        self.AssignedNumber4Bytes = _MultiValue()
        self.AsNumber4Bytes = _MultiValue()
        self.AssignedNumber2Bytes = _MultiValue()


class _ExtendedCommunityCollection:
    def __init__(self, positions):
        self._positions = positions

    def find(self):
        return self._positions


class _RouteProperty:
    def __init__(self, positions):
        self.EnableExtendedCommunity = _MultiValue()
        self.NoOfExternalCommunities = 0
        self.BgpExtendedCommunitiesList = _ExtendedCommunityCollection(positions)


def _make_device_group(name: str, network_groups=None):
    """Create a mock device group with a given name and optional network groups."""
    dg = MagicMock()
    dg.Name = name
    if network_groups is not None:
        dg.NetworkGroup.find.return_value = network_groups
    else:
        dg.NetworkGroup.find.return_value = []
    return dg


def _make_network_group(
    name: str,
    has_ipv4: bool = True,
    has_ipv6: bool = True,
):
    """Create a mock network group with IPv4/IPv6 prefix pools."""
    ng = MagicMock()
    ng.Name = name

    ipv4_pools = []
    if has_ipv4:
        ipv4_pool = MagicMock()
        ipv4_route_prop = MagicMock()
        ipv4_pool.BgpIPRouteProperty.find.return_value = [ipv4_route_prop]
        ipv4_pools = [ipv4_pool]
    ng.Ipv4PrefixPools.find.return_value = ipv4_pools

    ipv6_pools = []
    if has_ipv6:
        ipv6_pool = MagicMock()
        ipv6_route_prop = MagicMock()
        ipv6_pool.BgpV6IPRouteProperty.find.return_value = [ipv6_route_prop]
        ipv6_pools = [ipv6_pool]
    ng.Ipv6PrefixPools.find.return_value = ipv6_pools

    return ng


def _create_ixia_instance():
    """Create an Ixia instance with mocked session and logger."""
    with patch.object(Ixia, "__init__", lambda self: None):
        ixia = Ixia()
    ixia.logger = MagicMock()
    ixia.session = MagicMock()
    ixia.stop_protocols = MagicMock()
    # Protocol-state settling is out of scope here (these tests cover regex
    # filtering and position math) and needs a live topology to poll
    # DeviceGroup.Status against. It has dedicated coverage in
    # test_protocol_state_wait.py.
    ixia.stop_protocols_and_wait = MagicMock()
    ixia.start_protocols = MagicMock()
    ixia.apply_changes = MagicMock()
    return ixia


class TestBuildAsPathPositionValues(unittest.TestCase):
    """Tests for Ixia._build_as_path_position_values static method."""

    def test_basic_pool(self):
        """Two paths of length 3 produce 3 position lists of 2 values each."""
        pool = [(65001, 65002, 65003), (65004, 65005, 65006)]
        result = Ixia._build_as_path_position_values(pool, max_as_path_length=3)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0], [65001, 65004])
        self.assertEqual(result[1], [65002, 65005])
        self.assertEqual(result[2], [65003, 65006])

    def test_uneven_path_lengths_pads_zero(self):
        """Shorter paths get 0 for positions beyond their length."""
        pool = [(65001, 65002, 65003), (65004,)]
        result = Ixia._build_as_path_position_values(pool, max_as_path_length=3)
        self.assertEqual(result[0], [65001, 65004])
        self.assertEqual(result[1], [65002, 0])
        self.assertEqual(result[2], [65003, 0])

    def test_single_path(self):
        """A single path produces lists with one value each."""
        pool = [(100, 200)]
        result = Ixia._build_as_path_position_values(pool, max_as_path_length=2)
        self.assertEqual(result[0], [100])
        self.assertEqual(result[1], [200])

    def test_empty_pool(self):
        """An empty pool produces empty position lists."""
        result = Ixia._build_as_path_position_values([], max_as_path_length=2)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], [])
        self.assertEqual(result[1], [])


class TestColdAsPathConstruction(unittest.TestCase):
    def test_ten_slot_sequence_is_created_without_protocol_restart(self) -> None:
        ixia = _create_ixia_instance()
        route_property = MagicMock()
        segment = MagicMock()
        slots = [MagicMock() for _ in range(10)]
        segment.BgpAsNumberList.find.return_value = slots
        route_property.BgpAsPathSegmentList.find.return_value = [segment]

        ixia._configure_as_path_prepend(
            route_property,
            port_identifier="dut:Ethernet1",
            prefix_name="PREFIX_POOL_IBGP_IPV4_PLANE_1_REMOTE_EB",
            ip_version=ixia_types.IpAddressFamily.IPV4,
            as_path_prepend_flag=True,
            as_path_prepend_configs=[ixia_types.AsPathPrepend(as_numbers=[64512] * 10)],
        )

        route_property.EnableAsPathSegments.Single.assert_called_once_with(True)
        self.assertEqual(1, route_property.NoOfASPathSegmentsPerRouteRange)
        segment.SegmentType.Single.assert_called_once_with("asseq")
        self.assertEqual(10, segment.NumberOfAsNumberInSegment)
        for slot in slots:
            slot.AsNumber.Single.assert_called_once_with(64512)
        ixia.stop_protocols.assert_not_called()
        ixia.start_protocols.assert_not_called()


class TestGeneratedRouteNextHop(unittest.TestCase):
    def test_create_bgp_prefixes_programs_requested_next_hop_type(self) -> None:
        ixia = _create_ixia_instance()
        route_property = MagicMock()
        prefix_pool = MagicMock()
        prefix_pool.BgpIPRouteProperty.find.return_value = route_property
        network_group = MagicMock()
        network_group.Ipv4PrefixPools.add.return_value = prefix_pool
        device_group = MagicMock()
        device_group.NetworkGroup.find.return_value = []
        device_group.NetworkGroup.add.return_value = network_group
        device_group_index = MagicMock()
        device_group_index.network_group_indices = {}
        ixia.configure_prefix_length = MagicMock()
        ixia.get_bgp_ip_route_property = MagicMock(return_value=route_property)

        ixia.create_bgp_prefixes(
            port_identifier="dut:Ethernet1",
            ip_address_family=ixia_types.IpAddressFamily.IPV4,
            bgp_prefix_configs=[
                ixia_types.BgpPrefixConfig(
                    prefix_name="PREFIX_POOL_IPV4_EBGP",
                    starting_ip="120.0.0.0",
                    increment_ip="0.0.1.0",
                    prefix_length=24,
                    count=50_000,
                    network_group_index=0,
                    multiplier=1,
                    set_next_hop_type=ixia_types.SetNextHopType.SAME_AS_LOCAL_IP,
                )
            ],
            device_group_obj=device_group,
            device_group_index=device_group_index,
        )

        route_property.NextHopType.Single.assert_called_once_with("sameaslocalip")


class TestExtendedCommunityPool(unittest.TestCase):
    def setUp(self):
        self.ixia = _create_ixia_instance()

    def test_two_byte_as_route_target_uses_four_byte_assigned_number(self):
        position = _ExtendedCommunity()
        route = _RouteProperty([position])
        self.ixia.configure_extended_community_pool_on_route_property(
            route,
            [["rt:65001:1"], ["rt:65001:70000"]],
        )
        self.assertEqual([True], route.EnableExtendedCommunity.Values)
        self.assertEqual(1, route.NoOfExternalCommunities)
        # Both rows share a two-byte ASN and route-target subtype, so five of the
        # six fields are constant and collapse to a single value. Only the
        # assigned number differs per row, so only it ships a per-route list --
        # see Ixia._write_multivalue.
        self.assertEqual(["administratoras2octet"], position.Type.Values)
        self.assertEqual(["routetarget"], position.SubType.Values)
        self.assertEqual([65001], position.AsNumber2Bytes.Values)
        self.assertEqual([1, 70000], position.AssignedNumber4Bytes.Values)
        self.assertEqual([0], position.AsNumber4Bytes.Values)
        self.assertEqual([0], position.AssignedNumber2Bytes.Values)

    def test_four_byte_as_route_target_uses_two_byte_assigned_number(self):
        position = _ExtendedCommunity()
        route = _RouteProperty([position])
        self.ixia._configure_extended_community_pool_on_route_property(
            route,
            [["rt:70000:7"]],
        )
        self.assertEqual(["administratoras4octet"], position.Type.Values)
        self.assertEqual([0], position.AsNumber2Bytes.Values)
        self.assertEqual([0], position.AssignedNumber4Bytes.Values)
        self.assertEqual([70000], position.AsNumber4Bytes.Values)
        self.assertEqual([7], position.AssignedNumber2Bytes.Values)

    def test_two_byte_as_site_of_origin_uses_site_of_origin_subtype(self):
        position = _ExtendedCommunity()
        route = _RouteProperty([position])

        self.ixia._configure_extended_community_pool_on_route_property(
            route,
            [["soo:65001:70000"]],
        )

        self.assertEqual(["administratoras2octet"], position.Type.Values)
        self.assertEqual(["origin"], position.SubType.Values)
        self.assertEqual([65001], position.AsNumber2Bytes.Values)
        self.assertEqual([70000], position.AssignedNumber4Bytes.Values)

    def test_schema_and_shape_errors_are_not_silently_ignored(self):
        with self.assertRaisesRegex(ValueError, "position count mismatch"):
            self.ixia.configure_extended_community_pool_on_route_property(
                _RouteProperty([]),
                [["rt:65001:1"]],
            )
        with self.assertRaisesRegex(ValueError, "unsupported"):
            self.ixia.configure_extended_community_pool_on_route_property(
                _RouteProperty([_ExtendedCommunity()]),
                [["color:65001:1"]],
            )

    def test_extended_community_api_errors_are_logged_and_reraised(self):
        position = _ExtendedCommunity()
        # A single row makes Type constant, so the write goes through Single().
        position.Type.Single = MagicMock(side_effect=RuntimeError("write failed"))

        with self.assertRaisesRegex(RuntimeError, "write failed"):
            self.ixia.configure_extended_community_pool_on_route_property(
                _RouteProperty([position]),
                [["rt:65001:1"]],
            )

        self.ixia.logger.exception.assert_called_once()

    def test_legacy_extended_community_helper_remains_best_effort(self):
        self.ixia._configure_extended_community_pool_on_route_property(
            _RouteProperty([]),
            [["rt:65001:1"]],
        )

        self.ixia.logger.warning.assert_called_once()


class TestRoutePropertyPublicApis(unittest.TestCase):
    def setUp(self):
        self.ixia = _create_ixia_instance()

    def test_as_path_api_programs_each_asn_position(self):
        route = MagicMock()
        segment = MagicMock()
        slots = [MagicMock(), MagicMock()]
        route.BgpAsPathSegmentList.find.return_value = [segment]
        segment.BgpAsNumberList.find.return_value = slots

        self.ixia.configure_as_path_pool_on_route_property(
            route, ["65001 65002", "65003 65004"]
        )

        route.EnableAsPathSegments.Single.assert_called_once_with(True)
        self.assertEqual(1, route.NoOfASPathSegmentsPerRouteRange)
        segment.SegmentType.Single.assert_called_once_with("asseq")
        self.assertEqual(2, segment.NumberOfAsNumberInSegment)
        slots[0].AsNumber.ValueList.assert_called_once_with([65001, 65003])
        slots[1].AsNumber.ValueList.assert_called_once_with([65002, 65004])
        for slot in slots:
            slot.EnableASNumber.Single.assert_called_once_with(True)

    def test_as_path_api_rejects_empty_pool_before_programming(self):
        route = MagicMock()

        with self.assertRaisesRegex(ValueError, "must not be empty"):
            self.ixia.configure_as_path_pool_on_route_property(route, [])

        route.EnableAsPathSegments.Single.assert_not_called()

    def test_as_path_segment_api_programs_sequence_and_set(self):
        route = MagicMock()
        segments = [MagicMock(), MagicMock()]
        segment_slots = [
            [MagicMock(), MagicMock()],
            [MagicMock(), MagicMock()],
        ]
        route.BgpAsPathSegmentList.find.return_value = segments
        for segment, slots in zip(segments, segment_slots):
            segment.BgpAsNumberList.find.return_value = slots

        self.ixia.configure_as_path_segment_pools_on_route_property(
            route,
            (
                ("asseq", ["65001 65002", "65003 65004"]),
                ("asset", ["65101 65102", "65103 65104"]),
            ),
        )

        route.EnableAsPathSegments.Single.assert_called_once_with(True)
        self.assertEqual(2, route.NoOfASPathSegmentsPerRouteRange)
        segments[0].SegmentType.Single.assert_called_once_with("asseq")
        segments[1].SegmentType.Single.assert_called_once_with("asset")
        segment_slots[0][0].AsNumber.ValueList.assert_called_once_with([65001, 65003])
        segment_slots[1][1].AsNumber.ValueList.assert_called_once_with([65102, 65104])

    def test_as_path_segment_api_splits_each_path_once(self):
        split_calls: list[str] = []

        class CountingPath(str):
            def split(self, sep=None, maxsplit=-1):
                split_calls.append(str(self))
                return super().split(sep, maxsplit)

        route = MagicMock()
        segments = [MagicMock(), MagicMock()]
        for segment in segments:
            segment.BgpAsNumberList.find.return_value = [MagicMock(), MagicMock()]
        route.BgpAsPathSegmentList.find.return_value = segments
        paths = (
            ("asseq", [CountingPath("65001 65002"), CountingPath("65003 65004")]),
            ("asset", [CountingPath("65101 65102"), CountingPath("65103 65104")]),
        )

        self.ixia.configure_as_path_segment_pools_on_route_property(route, paths)

        self.assertEqual(
            [str(path) for _segment_type, pool in paths for path in pool], split_calls
        )

    def test_as_path_segment_snapshot_reads_only_original_structure(self):
        route = MagicMock()
        route.EnableAsPathSegments = _MultiValue(["false", "false"])
        original_segment = MagicMock()
        original_segment.SegmentType = _MultiValue(["asseq", "asseq"])
        original_slot = MagicMock()
        original_slot.AsNumber = _MultiValue([65000, 65000])
        original_slot.EnableASNumber = _MultiValue(["true", "true"])
        expanded_slot = MagicMock()
        expanded_segment = MagicMock()
        prepared = (
            (original_segment, (original_slot, expanded_slot), 1),
            (expanded_segment, (expanded_slot, expanded_slot), 0),
        )

        snapshots = self.ixia._capture_as_path_segment_values(route, prepared, 1)

        self.assertEqual(
            [
                "route.enable",
                "segment[0].type",
                "segment[0].slot[0].asn",
                "segment[0].slot[0].enable",
            ],
            [label for label, _handle, _values in snapshots],
        )
        self.assertEqual(0, expanded_slot.AsNumber.Values.call_count)
        self.assertEqual(0, expanded_segment.SegmentType.Values.call_count)

    def test_as_path_segment_api_validates_all_pools_before_programming(self):
        route = MagicMock()

        with self.assertRaisesRegex(ValueError, "equal row counts"):
            self.ixia.configure_as_path_segment_pools_on_route_property(
                route,
                (
                    ("asseq", ["65001", "65002"]),
                    ("asset", ["65101"]),
                ),
            )

        route.EnableAsPathSegments.Single.assert_not_called()

    def test_as_path_segment_api_rejects_variable_width_before_programming(self):
        route = MagicMock()

        with self.assertRaisesRegex(ValueError, "fixed positive width"):
            self.ixia.configure_as_path_segment_pools_on_route_property(
                route,
                (
                    ("asseq", ["65001 65002", "65003"]),
                    ("asset", ["65101 65102", "65103 65104"]),
                ),
            )

        route.EnableAsPathSegments.Single.assert_not_called()

    def test_as_path_segment_api_rolls_back_structure_on_slot_validation_error(self):
        route = MagicMock()
        route.NoOfASPathSegmentsPerRouteRange = 1
        segments = [MagicMock(), MagicMock()]
        segments[0].NumberOfAsNumberInSegment = 1
        segments[1].NumberOfAsNumberInSegment = 3
        segments[0].BgpAsNumberList.find.return_value = [MagicMock(), MagicMock()]
        segments[1].BgpAsNumberList.find.return_value = [MagicMock()]
        route.BgpAsPathSegmentList.find.return_value = segments

        with self.assertRaisesRegex(ValueError, "segment 1 has 1 slots"):
            self.ixia.configure_as_path_segment_pools_on_route_property(
                route,
                (
                    ("asseq", ["65001 65002", "65003 65004"]),
                    ("asset", ["65101 65102", "65103 65104"]),
                ),
            )

        self.assertEqual(1, route.NoOfASPathSegmentsPerRouteRange)
        self.assertEqual(
            [1, 3],
            [segment.NumberOfAsNumberInSegment for segment in segments],
        )
        route.EnableAsPathSegments.Single.assert_not_called()
        for segment in segments:
            segment.SegmentType.Single.assert_not_called()

    def test_as_path_segment_api_rolls_back_missing_segment_count(self):
        route = MagicMock()
        route.NoOfASPathSegmentsPerRouteRange = 1
        route.BgpAsPathSegmentList.find.return_value = [MagicMock()]

        with self.assertRaisesRegex(ValueError, "1 entries"):
            self.ixia.configure_as_path_segment_pools_on_route_property(
                route,
                (
                    ("asseq", ["65001", "65002"]),
                    ("asset", ["65101", "65102"]),
                ),
            )

        self.assertEqual(1, route.NoOfASPathSegmentsPerRouteRange)
        route.EnableAsPathSegments.Single.assert_not_called()

    def test_as_path_segment_api_rolls_back_restpy_slot_lookup_error(self):
        route = MagicMock()
        route.NoOfASPathSegmentsPerRouteRange = 1
        segments = [MagicMock(), MagicMock()]
        segments[0].NumberOfAsNumberInSegment = 1
        segments[1].NumberOfAsNumberInSegment = 3
        segments[0].BgpAsNumberList.find.return_value = [MagicMock(), MagicMock()]
        segments[1].BgpAsNumberList.find.side_effect = RuntimeError("RestPy failure")
        route.BgpAsPathSegmentList.find.return_value = segments

        with self.assertRaisesRegex(RuntimeError, "RestPy failure"):
            self.ixia.configure_as_path_segment_pools_on_route_property(
                route,
                (
                    ("asseq", ["65001 65002", "65003 65004"]),
                    ("asset", ["65101 65102", "65103 65104"]),
                ),
            )

        self.assertEqual(1, route.NoOfASPathSegmentsPerRouteRange)
        self.assertEqual(
            [1, 3],
            [segment.NumberOfAsNumberInSegment for segment in segments],
        )
        route.EnableAsPathSegments.Single.assert_not_called()

    def test_as_path_segment_api_rolls_back_restpy_segment_lookup_error(self):
        route = MagicMock()
        route.NoOfASPathSegmentsPerRouteRange = 1
        route.BgpAsPathSegmentList.find.side_effect = RuntimeError("RestPy failure")

        with self.assertRaisesRegex(RuntimeError, "RestPy failure"):
            self.ixia.configure_as_path_segment_pools_on_route_property(
                route,
                (
                    ("asseq", ["65001", "65002"]),
                    ("asset", ["65101", "65102"]),
                ),
            )

        self.assertEqual(1, route.NoOfASPathSegmentsPerRouteRange)
        route.EnableAsPathSegments.Single.assert_not_called()

    def test_as_path_segment_prepare_rollback_is_best_effort(self):
        class TrackingSegment:
            def __init__(self, *, fail_restore=False, lookup_error=None):
                self._width = 1
                self._programmed = False
                self.fail_restore = fail_restore
                self.restore_attempted = False
                self.BgpAsNumberList = MagicMock()
                if lookup_error is None:
                    self.BgpAsNumberList.find.return_value = [MagicMock(), MagicMock()]
                else:
                    self.BgpAsNumberList.find.side_effect = lookup_error

            @property
            def NumberOfAsNumberInSegment(self):
                return self._width

            @NumberOfAsNumberInSegment.setter
            def NumberOfAsNumberInSegment(self, value):
                if self._programmed and value == 1:
                    self.restore_attempted = True
                    if self.fail_restore:
                        raise RuntimeError(f"first width restore failed {'x' * 2_000}")
                self._width = value
                self._programmed = value != 1

        first = TrackingSegment(fail_restore=True)
        second = TrackingSegment(
            lookup_error=RuntimeError(f"slot lookup failed {'x' * 2_000}")
        )
        route = MagicMock()
        route.NoOfASPathSegmentsPerRouteRange = 1
        route.BgpAsPathSegmentList.find.return_value = [first, second]

        with self.assertRaises(RuntimeError) as context:
            self.ixia._prepare_as_path_segments(
                route,
                (("asseq", 2, []), ("asset", 2, [])),
            )

        message = str(context.exception)
        self.assertRegex(
            message,
            "preparation failed .*slot lookup failed.*rollback also failed.*"
            "segment\\[0\\].width",
        )
        self.assertNotIn("x" * 300, message)
        self.assertLess(len(message), 600)
        self.assertTrue(first.restore_attempted)
        self.assertTrue(second.restore_attempted)
        self.assertEqual(1, route.NoOfASPathSegmentsPerRouteRange)

    def test_as_path_segment_api_rolls_back_partial_programming_error(self):
        route = MagicMock()
        route.NoOfASPathSegmentsPerRouteRange = 1
        route.EnableAsPathSegments = _MultiValue(["false", "false"])
        segments = [MagicMock(), MagicMock()]
        segment_slots = []
        for index, segment in enumerate(segments):
            segment.NumberOfAsNumberInSegment = 1
            segment.SegmentType = _MultiValue([f"original-{index}"] * 2)
            slots = [MagicMock(), MagicMock()]
            for position, slot in enumerate(slots):
                slot.AsNumber = _MultiValue([65000 + position] * 2)
                slot.EnableASNumber = _MultiValue(["false", "false"])
            segment.BgpAsNumberList.find.return_value = slots
            segment_slots.append(slots)
        route.BgpAsPathSegmentList.find.return_value = segments

        def fail_after_partial_write(slots, _position_values):
            slots[0].AsNumber.ValueList([999, 999])
            slots[0].EnableASNumber.Single(True)
            raise RuntimeError("programming failure")

        self.ixia._apply_as_positions_concurrently = MagicMock(
            side_effect=fail_after_partial_write
        )

        with self.assertRaisesRegex(RuntimeError, "programming failure"):
            self.ixia.configure_as_path_segment_pools_on_route_property(
                route,
                (
                    ("asseq", ["65001 65002", "65003 65004"]),
                    ("asset", ["65101 65102", "65103 65104"]),
                ),
            )

        self.assertEqual(1, route.NoOfASPathSegmentsPerRouteRange)
        self.assertEqual([1, 1], [s.NumberOfAsNumberInSegment for s in segments])
        self.assertEqual(["false", "false"], route.EnableAsPathSegments.Values)
        self.assertEqual(["original-0"] * 2, segments[0].SegmentType.Values)
        self.assertEqual([65000, 65000], segment_slots[0][0].AsNumber.Values)
        self.assertEqual(["false", "false"], segment_slots[0][0].EnableASNumber.Values)

    def test_as_path_segment_rollback_rejects_empty_snapshot(self):
        handle = MagicMock()

        with self.assertRaisesRegex(ValueError, "empty IXIA multivalue snapshot"):
            self.ixia._restore_ixia_values(handle, ())

        handle.Single.assert_not_called()
        handle.ValueList.assert_not_called()

    def test_as_path_segment_rollback_reports_bounded_handle_evidence(self):
        failed_snapshots = []
        for index in range(12):
            handle = MagicMock()
            handle.ValueList.side_effect = RuntimeError("x" * 2_000)
            failed_snapshots.append((f"failed[{index}]", handle, ("false", "false")))
        restored_snapshots = [
            (
                f"restored[{index}]",
                _MultiValue(["current", "current"]),
                ("original", "original"),
            )
            for index in range(7)
        ]
        self.ixia._restore_as_path_segment_structure = MagicMock()

        with self.assertRaises(RuntimeError) as context:
            self.ixia._rollback_as_path_segment_programming(
                MagicMock(),
                (),
                1,
                (*failed_snapshots, *restored_snapshots),
            )

        message = str(context.exception)
        self.assertIn("failed_count=12", message)
        self.assertIn("failed[11]", message)
        self.assertNotIn("failed[0]", message)
        self.assertIn("restored_count=7", message)
        self.assertIn("restored[6]", message)
        self.assertNotIn("restored[0]", message)
        self.assertNotIn("x" * 300, message)
        self.assertLess(len(message), 4_000)
        self.ixia._restore_as_path_segment_structure.assert_called_once()

    def test_as_path_segment_snapshot_rollback_is_best_effort(self):
        class FailingRestoreSegment:
            def __init__(self, original_width, slots):
                self._width = original_width
                self._original_width = original_width
                self._was_programmed = False
                self.BgpAsNumberList = MagicMock()
                self.BgpAsNumberList.find.return_value = slots
                self.SegmentType = _MultiValue(["original", "original"])

            @property
            def NumberOfAsNumberInSegment(self):
                return self._width

            @NumberOfAsNumberInSegment.setter
            def NumberOfAsNumberInSegment(self, value):
                if self._was_programmed and value == self._original_width:
                    raise RuntimeError("width rollback failure")
                self._width = value
                self._was_programmed = value != self._original_width

        class SnapshotFailure:
            @property
            def Values(self):
                raise RuntimeError("snapshot failure")

        slots = [MagicMock(), MagicMock()]
        for slot in slots:
            slot.AsNumber = _MultiValue([65000, 65000])
            slot.EnableASNumber = _MultiValue(["false", "false"])
        first = FailingRestoreSegment(1, slots)
        second = MagicMock()
        second.NumberOfAsNumberInSegment = 3
        second.BgpAsNumberList.find.return_value = slots
        second.SegmentType = _MultiValue(["original", "original"])
        route = MagicMock()
        route.NoOfASPathSegmentsPerRouteRange = 1
        route.EnableAsPathSegments = SnapshotFailure()
        route.BgpAsPathSegmentList.find.return_value = [first, second]

        with self.assertRaisesRegex(
            RuntimeError,
            "snapshot failed .*snapshot failure.*rollback also failed.*"
            "width rollback failure",
        ):
            self.ixia.configure_as_path_segment_pools_on_route_property(
                route,
                (
                    ("asseq", ["65001 65002", "65003 65004"]),
                    ("asset", ["65101 65102", "65103 65104"]),
                ),
            )

        self.assertEqual(2, first.NumberOfAsNumberInSegment)
        self.assertEqual(3, second.NumberOfAsNumberInSegment)
        self.assertEqual(1, route.NoOfASPathSegmentsPerRouteRange)

    def test_as_path_segment_api_programs_two_255_slot_segments(self):
        route = MagicMock()
        segments = [MagicMock(), MagicMock()]
        route.BgpAsPathSegmentList.find.return_value = segments
        for segment in segments:
            segment.BgpAsNumberList.find.return_value = [MagicMock()] * 255
        self.ixia._apply_as_positions_concurrently = MagicMock()
        sequence = " ".join(str(64512 + offset) for offset in range(255))
        as_set = " ".join(str(65000 + offset) for offset in range(255))

        self.ixia.configure_as_path_segment_pools_on_route_property(
            route,
            (
                ("asseq", [sequence, sequence]),
                ("asset", [as_set, as_set]),
            ),
        )

        self.assertEqual(2, route.NoOfASPathSegmentsPerRouteRange)
        self.assertEqual(
            [255, 255],
            [segment.NumberOfAsNumberInSegment for segment in segments],
        )
        self.assertEqual(2, self.ixia._apply_as_positions_concurrently.call_count)
        for call in self.ixia._apply_as_positions_concurrently.call_args_list:
            self.assertEqual(255, len(call.args[1]))
            self.assertEqual(2, len(call.args[1][0]))

    def test_large_as_matrix_is_applied_in_resource_manager_batches(self):
        slots = [MagicMock() for _ in range(128)]
        for position, slot in enumerate(slots):
            slot.href = f"/api/v1/sessions/1/ixnetwork/as-number/{position}"
        position_values = [[position] * 10_000 for position in range(128)]
        self.ixia.ixnetwork = MagicMock()
        self.ixia.ixnetwork.href = "/api/v1/sessions/1/ixnetwork"
        self.ixia.ixnetwork._connection._execute.return_value = [
            {"xpath": f"/as-number[{position + 1}]"} for position in range(128)
        ]
        self.ixia.ixnetwork.ResourceManager.ImportConfig.return_value = []

        self.ixia._apply_as_positions_concurrently(slots, position_values)

        self.assertEqual(8, self.ixia.ixnetwork.ResourceManager.ImportConfig.call_count)
        first_payload = json.loads(
            self.ixia.ixnetwork.ResourceManager.ImportConfig.call_args_list[0].args[0]
        )
        self.assertEqual(32, len(first_payload))
        self.assertEqual(
            "/multivalue[@source = '/as-number[1] asNumber']/valueList",
            first_payload[0]["xpath"],
        )
        self.assertEqual(position_values[0], first_payload[0]["values"])
        self.assertEqual(
            "/multivalue[@source = '/as-number[1] enableASNumber']/singleValue",
            first_payload[1]["xpath"],
        )
        self.assertTrue(first_payload[1]["value"])
        for slot in slots:
            slot.AsNumber.ValueList.assert_not_called()
            slot.EnableASNumber.Single.assert_not_called()
        self.ixia.logger.info.assert_any_call(
            "Configuring %d AS positions in ResourceManager batches of %d "
            "across %d route rows",
            128,
            16,
            10_000,
        )

    def test_large_as_matrix_fails_closed_on_batch_import_error(self):
        slots = [MagicMock() for _ in range(128)]
        for position, slot in enumerate(slots):
            slot.href = f"/api/v1/sessions/1/ixnetwork/as-number/{position}"
        self.ixia.ixnetwork = MagicMock()
        self.ixia.ixnetwork.href = "/api/v1/sessions/1/ixnetwork"
        self.ixia.ixnetwork._connection._execute.return_value = [
            {"xpath": f"/as-number[{position + 1}]"} for position in range(128)
        ]
        self.ixia.ixnetwork.ResourceManager.ImportConfig.return_value = [
            "invalidCommit"
        ]

        with self.assertRaisesRegex(RuntimeError, "positions \\[0, 16\\)"):
            self.ixia._apply_as_positions_concurrently(
                slots, [[position] * 10_000 for position in range(128)]
            )

        self.ixia.ixnetwork.ResourceManager.ImportConfig.assert_called_once()

    def test_as_matrix_rejects_ragged_route_rows(self):
        slots = [MagicMock(), MagicMock()]

        with self.assertRaisesRegex(ValueError, "equal route-row counts"):
            self.ixia._apply_as_positions_concurrently(slots, [[1], [2, 3]])

        for slot in slots:
            slot.AsNumber.ValueList.assert_not_called()
            slot.EnableASNumber.Single.assert_not_called()

    def test_community_api_programs_each_community_position(self):
        route = MagicMock()
        positions = [MagicMock(), MagicMock()]
        route.BgpCommunitiesList.find.return_value = positions

        self.ixia.configure_community_pool_on_route_property(
            route,
            [["65000:1", "65001:2"], ["65002:3", "65003:4"]],
        )

        route.EnableCommunity.Single.assert_called_once_with(True)
        self.assertEqual(2, route.NoOfCommunities)
        positions[0].AsNumber.ValueList.assert_called_once_with([65000, 65002])
        positions[0].LastTwoOctets.ValueList.assert_called_once_with([1, 3])
        positions[1].AsNumber.ValueList.assert_called_once_with([65001, 65003])
        positions[1].LastTwoOctets.ValueList.assert_called_once_with([2, 4])

    def test_public_apis_reject_incomplete_route_property_schema(self):
        as_path_route = MagicMock()
        as_path_route.BgpAsPathSegmentList.find.return_value = []
        community_route = MagicMock()
        community_route.BgpCommunitiesList.find.return_value = []

        with self.assertRaisesRegex(ValueError, "AS path segment list"):
            self.ixia.configure_as_path_pool_on_route_property(
                as_path_route, ["65001 65002"]
            )
        with self.assertRaisesRegex(ValueError, "community list entries"):
            self.ixia.configure_community_pool_on_route_property(
                community_route, [["65000:1"]]
            )

        missing_community_route = MagicMock()
        missing_community_route.BgpCommunitiesList.find.return_value = None
        with self.assertRaisesRegex(ValueError, "community list entries"):
            self.ixia.configure_community_pool_on_route_property(
                missing_community_route, [["65000:1"]]
            )

    def test_public_apis_preserve_ixia_failure_context(self):
        as_path_route = MagicMock()
        as_path_route.BgpAsPathSegmentList.find.side_effect = RuntimeError(
            "AS path read failed"
        )
        community_route = MagicMock()
        position = MagicMock()
        position.AsNumber.ValueList.side_effect = RuntimeError("community write failed")
        community_route.BgpCommunitiesList.find.return_value = [position]

        with self.assertRaisesRegex(RuntimeError, "AS path read failed"):
            self.ixia.configure_as_path_pool_on_route_property(
                as_path_route, ["65001 65002"]
            )
        with self.assertRaisesRegex(RuntimeError, "community write failed"):
            self.ixia.configure_community_pool_on_route_property(
                community_route, [["65000:1"]]
            )

    def test_public_community_api_validates_before_programming(self):
        route = MagicMock()

        with self.assertRaises(ValueError):
            self.ixia.configure_community_pool_on_route_property(route, [["invalid"]])

        route.EnableCommunity.Single.assert_not_called()

    def test_private_community_api_preserves_best_effort_values(self):
        route = MagicMock()
        position = MagicMock()
        route.BgpCommunitiesList.find.return_value = [position]

        self.ixia._configure_community_pool_on_route_property(route, [["invalid"], []])

        position.AsNumber.ValueList.assert_called_once_with([0, 0])
        position.LastTwoOctets.ValueList.assert_called_once_with([0, 0])


class TestDeviceGroupRegexFiltering(unittest.TestCase):
    """Tests for device_group_regex filtering in pool configuration functions."""

    def setUp(self):
        self.ixia = _create_ixia_instance()

        # Create device groups simulating a real topology
        ng_plane1 = _make_network_group("NG_IBGP_PLANE_1")
        ng_plane2 = _make_network_group("NG_IBGP_PLANE_2")

        self.dg_plane1 = _make_device_group(
            "DEVICE_GROUP_IPV6_IBGP_PLANE_1_REMOTE_EB",
            network_groups=[ng_plane1],
        )
        self.dg_plane2 = _make_device_group(
            "DEVICE_GROUP_IPV6_IBGP_PLANE_2_REMOTE_EB",
            network_groups=[ng_plane2],
        )
        self.dg_ebgp = _make_device_group(
            "DEVICE_GROUP_IPV6_EBGP",
            network_groups=[_make_network_group("NG_EBGP")],
        )

        self.all_device_groups = [self.dg_plane1, self.dg_plane2, self.dg_ebgp]

    def test_configure_as_path_pool_filters_by_regex(self):
        """configure_as_path_pool only processes device groups matching regex."""
        self.ixia.get_device_groups_by_port_and_interface = MagicMock(
            return_value=self.all_device_groups
        )
        self.ixia._configure_as_path_pool_on_route_property = MagicMock()

        result = self.ixia.configure_as_path_pool(
            hostname="test_host",
            interface="Et1/1",
            as_path_pool=["65001 65002"],
            restart_protocols=False,
            device_group_regex=".*IBGP.*PLANE_1.*",
        )

        self.assertTrue(result)
        # Only PLANE_1 device group should have its route properties configured
        # PLANE_2 and EBGP should be skipped
        call_count = self.ixia._configure_as_path_pool_on_route_property.call_count
        # PLANE_1 has 1 network group with 1 IPv4 + 1 IPv6 = 2 calls
        self.assertEqual(call_count, 2)

    def test_configure_as_path_pool_matches_all_with_default_regex(self):
        """Default regex '.*' matches all device groups."""
        self.ixia.get_device_groups_by_port_and_interface = MagicMock(
            return_value=self.all_device_groups
        )
        self.ixia._configure_as_path_pool_on_route_property = MagicMock()

        result = self.ixia.configure_as_path_pool(
            hostname="test_host",
            interface="Et1/1",
            as_path_pool=["65001 65002"],
            restart_protocols=False,
            device_group_regex=".*",
        )

        self.assertTrue(result)
        # All 3 device groups × 1 network group each × 2 (IPv4+IPv6) = 6 calls
        call_count = self.ixia._configure_as_path_pool_on_route_property.call_count
        self.assertEqual(call_count, 6)

    def test_configure_community_pool_filters_by_regex(self):
        """configure_community_pool only processes device groups matching regex."""
        self.ixia.get_device_groups_by_port_and_interface = MagicMock(
            return_value=self.all_device_groups
        )

        combinations = [["100:1", "100:2"]]
        result = self.ixia.configure_community_pool(
            hostname="test_host",
            interface="Et1/1",
            community_combinations=combinations,
            restart_protocols=False,
            device_group_regex=".*IBGP.*PLANE_1.*",
        )

        self.assertTrue(result)
        # Verify PLANE_2 and EBGP network groups were NOT accessed
        self.dg_plane2.NetworkGroup.find.assert_not_called()
        self.dg_ebgp.NetworkGroup.find.assert_not_called()
        # PLANE_1 was processed
        self.dg_plane1.NetworkGroup.find.assert_called_once()

    def test_configure_extended_community_pool_filters_by_regex(self):
        """configure_extended_community_pool only processes matching device groups."""
        self.ixia.get_device_groups_by_port_and_interface = MagicMock(
            return_value=self.all_device_groups
        )
        self.ixia._configure_extended_community_pool_on_route_property = MagicMock()

        combinations = [["rt:100:1", "rt:100:2"]]
        result = self.ixia.configure_extended_community_pool(
            hostname="test_host",
            interface="Et1/1",
            extended_community_combinations=combinations,
            restart_protocols=False,
            device_group_regex=".*EBGP.*",
        )

        self.assertTrue(result)
        # Only EBGP should be processed
        self.dg_ebgp.NetworkGroup.find.assert_called_once()
        self.dg_plane1.NetworkGroup.find.assert_not_called()
        self.dg_plane2.NetworkGroup.find.assert_not_called()
        self.assertEqual(
            2,
            self.ixia._configure_extended_community_pool_on_route_property.call_count,
        )

    def test_no_device_groups_returns_false(self):
        """Returns False when no device groups found for interface."""
        self.ixia.get_device_groups_by_port_and_interface = MagicMock(return_value=[])

        result = self.ixia.configure_as_path_pool(
            hostname="test_host",
            interface="Et1/1",
            as_path_pool=["65001"],
            restart_protocols=False,
        )

        self.assertFalse(result)

    def test_regex_is_case_insensitive(self):
        """device_group_regex matching is case-insensitive."""
        dg_lower = _make_device_group(
            "device_group_ibgp_plane_1",
            network_groups=[_make_network_group("ng1")],
        )
        self.ixia.get_device_groups_by_port_and_interface = MagicMock(
            return_value=[dg_lower]
        )
        self.ixia._configure_as_path_pool_on_route_property = MagicMock()

        result = self.ixia.configure_as_path_pool(
            hostname="test_host",
            interface="Et1/1",
            as_path_pool=["65001"],
            restart_protocols=False,
            device_group_regex=".*IBGP.*PLANE_1.*",
        )

        self.assertTrue(result)
        # Should match despite case difference
        self.assertTrue(
            self.ixia._configure_as_path_pool_on_route_property.call_count > 0
        )
