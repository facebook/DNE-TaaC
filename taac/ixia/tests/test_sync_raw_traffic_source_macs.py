# Copyright (c) Meta Platforms, Inc. and affiliates.

import unittest
from unittest.mock import MagicMock

from taac.ixia.ixia import Ixia


VPORT_1 = "/api/v1/sessions/1/ixnetwork/vport/1"
VPORT_2 = "/api/v1/sessions/1/ixnetwork/vport/2"


def _topology(vport_href: str, mac: str) -> MagicMock:
    ethernet = MagicMock()
    ethernet.Mac.Values = [mac]
    device_group = MagicMock()
    device_group.Ethernet.find.return_value = ethernet
    topology = MagicMock()
    topology.Vports = [vport_href]
    topology.DeviceGroup.find.return_value = [device_group]
    return topology


def _traffic_item(
    name: str, traffic_type: str, sources: list[str]
) -> tuple[MagicMock, MagicMock]:
    field_obj = MagicMock()
    config_element = MagicMock()
    config_element.Stack.find.return_value.Field.find.return_value = field_obj
    endpoint_set = MagicMock()
    endpoint_set.Sources = sources
    traffic_item = MagicMock()
    traffic_item.Name = name
    traffic_item.TrafficType = traffic_type
    traffic_item.EndpointSet.find.return_value = [endpoint_set]
    traffic_item.ConfigElement.find.return_value = [config_element]
    return traffic_item, field_obj


def _make_ixia(
    topologies: list[MagicMock],
    traffic_items: list[MagicMock],
    traffic_running: bool = False,
) -> tuple[Ixia, MagicMock, MagicMock]:
    """Return the Ixia under test plus its regenerate and apply mocks."""
    regenerate = MagicMock()
    apply_traffic = MagicMock()
    ixia = object.__new__(Ixia)
    ixia.ixnetwork = MagicMock()
    ixia.ixnetwork.Topology.find.return_value = topologies
    ixia.ixnetwork.Traffic.TrafficItem.find.return_value = traffic_items
    ixia.logger = MagicMock()
    ixia.is_traffic_running = MagicMock(return_value=traffic_running)
    ixia.regenerate_traffic_items = regenerate
    ixia.apply_traffic = apply_traffic
    return ixia, regenerate, apply_traffic


class SyncRawTrafficSourceMacsTest(unittest.TestCase):
    def test_sets_tx_port_device_group_mac_on_raw_items(self) -> None:
        raw_item, raw_field = _traffic_item("CPU_RAW", "raw", [f"{VPORT_2}/protocols"])
        ipv6_item, ipv6_field = _traffic_item("L3", "ipv6", [f"{VPORT_1}/protocols"])
        ixia, regenerate, apply_traffic = _make_ixia(
            [
                _topology(VPORT_1, "00:11:01:00:00:01"),
                _topology(VPORT_2, "00:12:01:00:00:01"),
            ],
            [raw_item, ipv6_item],
        )

        synced = ixia.sync_raw_traffic_source_macs()

        self.assertEqual(synced, {"CPU_RAW": "00:12:01:00:00:01"})
        raw_field.update.assert_called_once_with(
            ValueType="singleValue", SingleValue="00:12:01:00:00:01"
        )
        ipv6_field.update.assert_not_called()
        regenerate.assert_called_once_with()
        apply_traffic.assert_called_once_with()

    def test_regex_limits_which_raw_items_are_synced(self) -> None:
        wanted, wanted_field = _traffic_item("CPU_RAW", "raw", [f"{VPORT_1}/protocols"])
        other, other_field = _traffic_item("LLDP_RAW", "raw", [f"{VPORT_1}/protocols"])
        ixia, _, _ = _make_ixia(
            [_topology(VPORT_1, "00:11:01:00:00:01")], [wanted, other]
        )

        synced = ixia.sync_raw_traffic_source_macs("^CPU_RAW$")

        self.assertEqual(synced, {"CPU_RAW": "00:11:01:00:00:01"})
        wanted_field.update.assert_called_once()
        other_field.update.assert_not_called()

    def test_skips_item_without_a_single_tx_mac(self) -> None:
        raw_item, raw_field = _traffic_item(
            "MULTI_TX", "raw", [f"{VPORT_1}/protocols", f"{VPORT_2}/protocols"]
        )
        ixia, regenerate, _ = _make_ixia(
            [
                _topology(VPORT_1, "00:11:01:00:00:01"),
                _topology(VPORT_2, "00:12:01:00:00:01"),
            ],
            [raw_item],
        )

        synced = ixia.sync_raw_traffic_source_macs()

        self.assertEqual(synced, {})
        raw_field.update.assert_not_called()
        regenerate.assert_not_called()

    def test_item_without_ethernet_source_mac_field_is_skipped(self) -> None:
        no_eth, _ = _traffic_item("NO_ETH", "raw", [f"{VPORT_1}/protocols"])
        no_eth.ConfigElement.find.return_value[0].Stack.find.return_value = []
        good, good_field = _traffic_item("CPU_RAW", "raw", [f"{VPORT_1}/protocols"])
        ixia, _, _ = _make_ixia(
            [_topology(VPORT_1, "00:11:01:00:00:01")], [no_eth, good]
        )

        synced = ixia.sync_raw_traffic_source_macs()

        self.assertEqual(synced, {"CPU_RAW": "00:11:01:00:00:01"})
        good_field.update.assert_called_once()

    def test_multi_vport_topology_is_not_mapped(self) -> None:
        topology = _topology(VPORT_1, "00:11:01:00:00:01")
        topology.Vports = [VPORT_1, VPORT_2]
        raw_item, raw_field = _traffic_item("CPU_RAW", "raw", [f"{VPORT_1}/protocols"])
        ixia, _, _ = _make_ixia([topology], [raw_item])

        synced = ixia.sync_raw_traffic_source_macs()

        self.assertEqual(synced, {})
        raw_field.update.assert_not_called()

    def test_running_traffic_is_not_reapplied(self) -> None:
        raw_item, _ = _traffic_item("CPU_RAW", "raw", [f"{VPORT_1}/protocols"])
        ixia, regenerate, apply_traffic = _make_ixia(
            [_topology(VPORT_1, "00:11:01:00:00:01")], [raw_item], traffic_running=True
        )

        ixia.sync_raw_traffic_source_macs()

        regenerate.assert_called_once_with()
        apply_traffic.assert_not_called()


if __name__ == "__main__":
    unittest.main()
