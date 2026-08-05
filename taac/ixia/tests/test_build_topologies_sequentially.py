# pyre-unsafe — extensive MagicMock substitution for the IxNetwork REST
# objects used by the helper under test.
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""Unit tests for `_build_topologies_and_device_groups`."""

import threading
import unittest
from unittest.mock import MagicMock, patch

from taac.ixia.ixia import Ixia


def _make_port_config(port_name: str, has_l1_config: bool = False):
    port = MagicMock()
    port.port_name = port_name
    port.device_group_configs = [MagicMock()]
    port.l1_config = MagicMock() if has_l1_config else None
    return port


def _make_vport_index():
    index = MagicMock()
    index.topology_name = None
    return index


def _create_ixia_instance():
    with patch.object(Ixia, "__init__", lambda self: None):
        ixia = Ixia()
    ixia.logger = MagicMock()
    ixia.ixnetwork = MagicMock()
    ixia.vport_indices = {}
    ixia.create_topology = MagicMock(return_value=MagicMock(Name="TOPOLOGY_MOCK"))
    ixia.create_device_groups = MagicMock()
    ixia.configure_l1_settings = MagicMock()
    return ixia


class BuildTopologiesSequentiallyTest(unittest.TestCase):
    def setUp(self):
        self.ixia = _create_ixia_instance()
        for i in range(8):
            self.ixia.vport_indices[f"PORT_{i}"] = _make_vport_index()

    def test_all_ports_built_once_in_order(self):
        ports = [_make_port_config(f"PORT_{i}") for i in range(8)]

        self.ixia._build_topologies_and_device_groups(ports, _log=MagicMock())

        self.assertEqual(self.ixia.create_topology.call_count, 8)
        self.assertEqual(self.ixia.create_device_groups.call_count, 8)
        self.assertEqual(
            [call.args[0] for call in self.ixia.create_device_groups.call_args_list],
            [f"PORT_{i}" for i in range(8)],
        )
        for i in range(8):
            self.assertEqual(
                self.ixia.vport_indices[f"PORT_{i}"].topology_name,
                "TOPOLOGY_MOCK",
            )

    def test_l1_config_invoked_only_when_present(self):
        ports = [
            _make_port_config("PORT_0", has_l1_config=True),
            _make_port_config("PORT_1", has_l1_config=False),
            _make_port_config("PORT_2", has_l1_config=True),
        ]

        self.ixia._build_topologies_and_device_groups(ports, _log=MagicMock())

        self.assertEqual(self.ixia.configure_l1_settings.call_count, 2)

    def test_port_builds_do_not_overlap(self):
        ports = [_make_port_config(f"PORT_{i}") for i in range(2)]
        state = {"active": 0, "max_active": 0}
        state_lock = threading.Lock()
        two_calls_active = threading.Event()

        def _create_topology(port_identifier, vport):
            with state_lock:
                state["active"] += 1
                state["max_active"] = max(state["max_active"], state["active"])
                if state["active"] == 2:
                    two_calls_active.set()
            two_calls_active.wait(timeout=0.05)
            with state_lock:
                state["active"] -= 1
            return MagicMock(Name=f"TOPOLOGY_{port_identifier}")

        self.ixia.create_topology.side_effect = _create_topology

        self.ixia._build_topologies_and_device_groups(ports, _log=MagicMock())

        self.assertEqual(state["max_active"], 1)

    def test_failure_propagates_without_building_later_ports(self):
        ports = [_make_port_config(f"PORT_{i}") for i in range(4)]
        attempts = []

        def _fail_port_1(port_identifier, dg_configs, topology):
            attempts.append(port_identifier)
            if port_identifier == "PORT_1":
                raise RuntimeError("RestPy mutation failed")

        self.ixia.create_device_groups.side_effect = _fail_port_1

        with self.assertRaisesRegex(RuntimeError, "RestPy mutation failed"):
            self.ixia._build_topologies_and_device_groups(ports, _log=MagicMock())

        self.assertEqual(attempts, ["PORT_0", "PORT_1"])
        self.assertEqual(self.ixia.create_topology.call_count, 2)
