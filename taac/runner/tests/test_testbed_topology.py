#!/usr/bin/env python3
# pyre-unsafe

"""Unit tests for ConfigTopology, CircuitLink, and build_testbed_topology."""

from unittest import TestCase
from unittest.mock import patch

from taac.oss_topology_info.circuit_info_loader import (
    DesiredCircuitRecord,
    DesiredPlatformRecord,
    DeviceRecord,
    EndpointRecord,
)
from taac.runner.oss_entry_point import _classify_link, build_testbed_topology
from taac.runner.testbed_topology import CircuitLink, ConfigTopology, LinkType


def _circuit(a_host, a_port, z_host, z_port, a_plat="FBOSS", z_plat="FBOSS"):
    """Shorthand to build a DesiredCircuitRecord."""
    return DesiredCircuitRecord(
        a_endpoint=EndpointRecord(
            name=a_port,
            device=DeviceRecord(
                name=a_host,
                desired_platform=DesiredPlatformRecord(os_type_name=a_plat),
            ),
            aggregated_interface=None,
        ),
        z_endpoint=EndpointRecord(
            name=z_port,
            device=DeviceRecord(
                name=z_host,
                desired_platform=DesiredPlatformRecord(os_type_name=z_plat),
            ),
            aggregated_interface=None,
        ),
        status="3",
        role_name=None,
    )


class TestClassifyLink(TestCase):
    def setUp(self):
        self.dut_set = {"fboss102", "fboss103"}

    def test_dut_to_dut(self):
        self.assertEqual(
            _classify_link("fboss102", "fboss103", "FBOSS", self.dut_set),
            LinkType.DUT,
        )

    def test_tgen(self):
        self.assertEqual(
            _classify_link("fboss102", "ixia-chassis", "ixia", self.dut_set),
            LinkType.TGEN,
        )

    def test_snake(self):
        self.assertEqual(
            _classify_link("fboss102", "fboss102", "FBOSS", self.dut_set),
            LinkType.SNAKE,
        )

    def test_unknown(self):
        self.assertEqual(
            _classify_link("fboss102", "randomhost", "FBOSS", self.dut_set),
            LinkType.UNKNOWN,
        )



class TestConfigTopology(TestCase):
    def test_dut_ports_filters_by_link_type(self):
        links = (
            CircuitLink("fboss102", "eth1/63/1", "fboss103", "eth1/63/1", LinkType.DUT),
            CircuitLink("fboss102", "eth1/59/1", "ixia", "1/1", LinkType.TGEN),
        )
        topo = ConfigTopology(links=links)
        self.assertEqual(topo.dut_ports, {"fboss102": ["eth1/63/1"]})

    def test_empty_topology(self):
        topo = ConfigTopology()
        self.assertEqual(topo.dut_ports, {})

    def test_multiple_duts(self):
        links = (
            CircuitLink("fboss102", "eth1/63/1", "fboss103", "eth1/63/1", LinkType.DUT),
            CircuitLink("fboss103", "eth1/63/1", "fboss102", "eth1/63/1", LinkType.DUT),
        )
        topo = ConfigTopology(links=links)
        self.assertIn("fboss102", topo.dut_ports)
        self.assertIn("fboss103", topo.dut_ports)


class TestBuildTestbedTopology(TestCase):
    def _build(self, circuits, duts):
        with patch(
            "taac.runner.oss_entry_point.load_circuit_info",
            return_value=(circuits, {}),
        ):
            return build_testbed_topology(duts)

    def test_dut_to_dut_both_directions(self):
        circuits = [
            _circuit("fboss102", "eth1/63/1", "fboss103", "eth1/63/1"),
            _circuit("fboss103", "eth1/63/1", "fboss102", "eth1/63/1"),
        ]
        topo = self._build(circuits, ["fboss102", "fboss103"])
        self.assertEqual(topo.dut_ports["fboss102"], ["eth1/63/1"])
        self.assertEqual(topo.dut_ports["fboss103"], ["eth1/63/1"])
        self.assertEqual(len(topo.links), 2)

    def test_single_direction_synthesises_reverse(self):
        """CSV lists only dut1→dut2; dut2 should still get its ports."""
        circuits = [
            _circuit("fboss102", "eth1/63/1", "fboss103", "eth1/63/1"),
        ]
        topo = self._build(circuits, ["fboss102", "fboss103"])
        self.assertIn("fboss102", topo.dut_ports)
        self.assertIn("fboss103", topo.dut_ports)
        self.assertEqual(len(topo.links), 2)

    def test_no_duplicate_links_with_both_directions(self):
        """CSV has both directions; should not double the links."""
        circuits = [
            _circuit("fboss102", "eth1/63/1", "fboss103", "eth1/63/1"),
            _circuit("fboss103", "eth1/63/1", "fboss102", "eth1/63/1"),
        ]
        topo = self._build(circuits, ["fboss102", "fboss103"])
        self.assertEqual(len(topo.links), 2)

    def test_ixia_classified_as_tgen(self):
        circuits = [
            _circuit("fboss102", "eth1/59/1", "ixia", "1/1", z_plat="ixia"),
        ]
        topo = self._build(circuits, ["fboss102"])
        tgen = [l for l in topo.links if l.link_type == LinkType.TGEN]
        self.assertEqual(len(tgen), 1)
        self.assertEqual(topo.dut_ports, {})

    def test_unrelated_hosts_filtered_out(self):
        circuits = [
            _circuit("fboss102", "eth1/63/1", "fboss103", "eth1/63/1"),
            _circuit("fboss999", "eth1/1/1", "fboss998", "eth1/1/1"),
        ]
        topo = self._build(circuits, ["fboss102", "fboss103"])
        hosts = {l.local_host for l in topo.links}
        self.assertNotIn("fboss999", hosts)
        self.assertNotIn("fboss998", hosts)

    def test_mixed_ixia_and_dut_links(self):
        circuits = [
            _circuit("fboss102", "eth1/59/1", "ixia", "1/1", z_plat="ixia"),
            _circuit("fboss102", "eth1/60/1", "ixia", "1/2", z_plat="ixia"),
            _circuit("fboss102", "eth1/63/1", "fboss103", "eth1/63/1"),
            _circuit("fboss103", "eth1/63/1", "fboss102", "eth1/63/1"),
        ]
        topo = self._build(circuits, ["fboss102", "fboss103"])
        self.assertEqual(topo.dut_ports, {
            "fboss102": ["eth1/63/1"],
            "fboss103": ["eth1/63/1"],
        })
        tgen = [l for l in topo.links if l.link_type == LinkType.TGEN]
        self.assertEqual(len(tgen), 2)

if __name__ == "__main__":
    import unittest

    unittest.main()
