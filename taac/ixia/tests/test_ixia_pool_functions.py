# pyre-unsafe
# Copyright (c) Meta Platforms, Inc. and affiliates.
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
        pool = ["65001 65002 65003", "65004 65005 65006"]
        result = Ixia._build_as_path_position_values(pool, max_as_path_length=3)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0], [65001, 65004])
        self.assertEqual(result[1], [65002, 65005])
        self.assertEqual(result[2], [65003, 65006])

    def test_uneven_path_lengths_pads_zero(self):
        """Shorter paths get 0 for positions beyond their length."""
        pool = ["65001 65002 65003", "65004"]
        result = Ixia._build_as_path_position_values(pool, max_as_path_length=3)
        self.assertEqual(result[0], [65001, 65004])
        self.assertEqual(result[1], [65002, 0])
        self.assertEqual(result[2], [65003, 0])

    def test_single_path(self):
        """A single path produces lists with one value each."""
        pool = ["100 200"]
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
