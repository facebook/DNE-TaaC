# pyre-unsafe
# Copyright (c) Meta Platforms, Inc. and affiliates.
import unittest
from unittest.mock import MagicMock, patch

from ixia.ixia import types as ixia_types
from taac.ixia.ixia import Ixia


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
