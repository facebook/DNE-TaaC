# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Unit tests for the RBB SRv6 topology loader (bgp_rbb_topology).

Feeds a small in-test circuit_info CSV fixture and asserts the derived core
port-channel members + IXIA-port map, and separately asserts the generic
documentation-only fallback when no CSV is supplied.

Lives under ``taac/playbooks/routing/tests`` (the OSS-collected test home) for
the same reason as the sibling RBB test files.
"""

import os
import tempfile
import unittest
from dataclasses import replace
from unittest import mock

from taac.testconfigs.routing.util.bgp_rbb_topology import (
    CorePortChannel,
    load_rbb_topology,
    RbbTopologyError,
    validate_rbb_topology,
)

# A tiny circuit_info fixture: two core PCs (each 2 members) between R1 and R2,
# plus one IXIA edge per DUT (IXIA port given as slot/port). All names are
# generic placeholders — this is a schema fixture, not a real lab.
_FIXTURE_CSV = """\
# comment line is ignored
r1.example,eth1/1,FBOSS,port-channelA,r2.example,eth1/1,FBOSS,port-channelA,3,
r1.example,eth1/2,FBOSS,port-channelA,r2.example,eth1/2,FBOSS,port-channelA,3,
r1.example,eth1/3,FBOSS,port-channelB,r2.example,eth1/3,FBOSS,port-channelB,3,
r2.example,eth1/1,FBOSS,port-channelA,r1.example,eth1/1,FBOSS,port-channelA,3,
r2.example,eth1/2,FBOSS,port-channelA,r1.example,eth1/2,FBOSS,port-channelA,3,
r2.example,eth1/3,FBOSS,port-channelB,r1.example,eth1/3,FBOSS,port-channelB,3,
r1.example,eth1/9,FBOSS,,ixia,1/7,IXIA,,3,IXIA
r1.example,eth1/10,FBOSS,,ixia,1/9,IXIA,,3,IXIA
r2.example,eth1/9,FBOSS,,ixia,1/8,IXIA,,3,IXIA
r1.example,eth9/9,FBOSS,port-channel999,r2.example,eth9/9,FBOSS,port-channel999,2,
"""


class RbbTopologyFromCsvTest(unittest.TestCase):
    def setUp(self) -> None:
        fd, self._path = tempfile.mkstemp(suffix="_circuit_info.csv")
        with os.fdopen(fd, "w") as f:
            f.write(_FIXTURE_CSV)
        self.topo = load_rbb_topology(
            r1_host="r1.example",
            r2_host="r2.example",
            circuit_info_path=self._path,
            ixia_chassis="chassis.example",
        )

    def tearDown(self) -> None:
        os.remove(self._path)

    def test_hostnames_and_chassis(self) -> None:
        self.assertEqual(self.topo.r1.hostname, "r1.example")
        self.assertEqual(self.topo.r2.hostname, "r2.example")
        self.assertEqual(self.topo.ixia_chassis, "chassis.example")

    def test_live_ixia_mode_requires_explicit_chassis(self) -> None:
        with mock.patch.dict(os.environ, {"TAAC_RBB_IXIA_CHASSIS": ""}):
            with self.assertRaisesRegex(RbbTopologyError, "IXIA_CHASSIS"):
                load_rbb_topology(
                    r1_host="r1.example",
                    r2_host="r2.example",
                    circuit_info_path=self._path,
                    require_ixia=True,
                )

    def test_core_port_channels_grouped_with_members(self) -> None:
        r1_pcs = {pc.name: pc for pc in self.topo.r1.core_pcs}
        self.assertEqual(set(r1_pcs), {"port-channelA", "port-channelB"})
        self.assertEqual(r1_pcs["port-channelA"].members, ("eth1/1", "eth1/2"))
        self.assertEqual(r1_pcs["port-channelB"].members, ("eth1/3",))
        # R2 mirrors R1's members (derived from its own endpoints).
        r2_pcs = {pc.name: pc for pc in self.topo.r2.core_pcs}
        self.assertEqual(r2_pcs["port-channelA"].members, ("eth1/1", "eth1/2"))

    def test_show_name_capitalization(self) -> None:
        pc = CorePortChannel(name="port-channelB", members=("eth1/3",))
        self.assertEqual(pc.show_name, "Port-ChannelB")

    def test_rif_verify_pc_is_second_core_pc(self) -> None:
        self.assertEqual(self.topo.r1.rif_verify_pc.name, "port-channelB")

    def test_ixia_edges_and_port_map(self) -> None:
        self.assertEqual(
            self.topo.r1.ixia_port_tuples,
            [("eth1/9", "1/7"), ("eth1/10", "1/9")],
        )
        self.assertEqual(self.topo.r2.ixia_port_tuples, [("eth1/9", "1/8")])
        self.assertEqual(self.topo.r1.primary_ixia_interface, "eth1/9")

    def test_user_can_select_one_of_multiple_ixia_edges(self) -> None:
        with mock.patch.dict(
            os.environ, {"TAAC_RBB_R1_IXIA_INTERFACE": "eth1/10"}
        ):
            topology = load_rbb_topology(
                r1_host="r1.example",
                r2_host="r2.example",
                circuit_info_path=self._path,
                ixia_chassis="chassis.example",
                require_ixia=True,
            )
        self.assertEqual(topology.r1.primary_ixia_interface, "eth1/10")
        self.assertEqual(topology.r1.primary_ixia_edge.ixia_port, "1/9")

    def test_invalid_selected_edge_is_rejected(self) -> None:
        topology = replace(
            self.topo,
            r1=replace(self.topo.r1, traffic_ixia_interface="eth9/9/9"),
        )
        with self.assertRaisesRegex(RbbTopologyError, "selected traffic interface"):
            validate_rbb_topology(topology, require_ixia=True)

    def test_selected_edge_match_is_case_insensitive(self) -> None:
        topology = replace(
            self.topo,
            r1=replace(self.topo.r1, traffic_ixia_interface="ETH1/10"),
        )
        validate_rbb_topology(topology, require_ixia=True)
        self.assertEqual(topology.r1.primary_ixia_edge.ixia_port, "1/9")

    def test_asymmetric_core_port_channels_are_rejected(self) -> None:
        topology = replace(
            self.topo,
            r2=replace(self.topo.r2, core_pcs=self.topo.r2.core_pcs[:-1]),
        )
        with self.assertRaisesRegex(RbbTopologyError, "same number"):
            validate_rbb_topology(topology, require_ixia=True)

    def test_one_ixia_port_cannot_be_assigned_to_both_duts(self) -> None:
        r2_edge = replace(self.topo.r2.ixia_edges[0], ixia_port="1/7")
        topology = replace(
            self.topo,
            r2=replace(self.topo.r2, ixia_edges=(r2_edge,)),
        )
        with self.assertRaisesRegex(RbbTopologyError, "assigned to both DUTs"):
            validate_rbb_topology(topology, require_ixia=True)

    def test_ixia_rows_excluded_from_core(self) -> None:
        # The IXIA edge must NOT be miscounted as a core port-channel.
        all_names = {pc.name for pc in self.topo.r1.core_pcs}
        self.assertNotIn("ixia", {n.lower() for n in all_names})
        self.assertNotIn("port-channel999", all_names)

    def test_cross_wired_port_channel_members_are_rejected(self) -> None:
        crossed = _FIXTURE_CSV.replace(
            "r1.example,eth1/2,FBOSS,port-channelA,r2.example,eth1/2,FBOSS,port-channelA",
            "r1.example,eth1/2,FBOSS,port-channelA,r2.example,eth1/2,FBOSS,port-channelB",
        )
        fd, path = tempfile.mkstemp(suffix="_crossed_circuit_info.csv")
        try:
            with os.fdopen(fd, "w") as file:
                file.write(crossed)
            with self.assertRaisesRegex(RbbTopologyError, "wired across"):
                load_rbb_topology(
                    r1_host="r1.example",
                    r2_host="r2.example",
                    circuit_info_path=path,
                    ixia_chassis="chassis.example",
                )
        finally:
            os.unlink(path)


class RbbTopologyGenericFallbackTest(unittest.TestCase):
    """No CSV → generic, documentation-only placeholder wiring."""

    def setUp(self) -> None:
        with mock.patch.dict(os.environ, {"TAAC_CIRCUIT_INFO_PATH": ""}):
            self.topo = load_rbb_topology(
                r1_host="rbb-r1.lab.example",
                r2_host="rbb-r2.lab.example",
            )

    def test_two_generic_core_pcs(self) -> None:
        names = [pc.name for pc in self.topo.r1.core_pcs]
        self.assertEqual(names, ["port-channel1", "port-channel2"])

    def test_generic_ixia_edges_present(self) -> None:
        self.assertTrue(self.topo.r1.ixia_edges)
        self.assertTrue(self.topo.r2.ixia_edges)
        # Fallback wiring carries no lab-specific interface / port values.
        for iface, port in self.topo.r1.ixia_port_tuples:
            self.assertNotIn("1/1/", iface)
            self.assertNotEqual(port, "1/3")

    def test_no_lab_specific_core_interfaces(self) -> None:
        for pc in self.topo.r1.core_pcs:
            for member in pc.members:
                self.assertFalse(member.startswith("eth1/6/"))

    def test_explicit_missing_csv_never_falls_back(self) -> None:
        with self.assertRaises(RbbTopologyError):
            load_rbb_topology(
                r1_host="rbb-r1.lab.example",
                r2_host="rbb-r2.lab.example",
                circuit_info_path="/nonexistent/rbb_circuit_info.csv",
            )

    def test_live_mode_requires_csv(self) -> None:
        with mock.patch.dict(os.environ, {"TAAC_CIRCUIT_INFO_PATH": ""}):
            with self.assertRaises(RbbTopologyError):
                load_rbb_topology(allow_placeholder=False)


if __name__ == "__main__":
    unittest.main()
