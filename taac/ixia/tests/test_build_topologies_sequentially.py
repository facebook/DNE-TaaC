# pyre-unsafe — extensive MagicMock substitution for the IxNetwork REST
# objects used by the helper under test.
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""Unit tests for `_build_topologies_and_device_groups`."""

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from taac.ixia.ixia import (
    DESIRED_DEVICE_GROUP_NAME,
    DESIRED_ETHERNET_NAME,
    DESIRED_IPV6_NAME,
    DESIRED_TOPOLOGY_NAME,
    DESIRED_V6_BGP_PREFIX_NAME,
    DESIRED_VPORT_NAME,
    Ixia,
    ixia_types,
    IxiaSetupError,
)


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


class _FindByName:
    def __init__(self, objects):
        self._objects = {obj.Name: obj for obj in objects}

    def find(self, Name=None):
        if Name is None:
            return list(self._objects.values())
        return self._objects.get(Name)


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


class RehydrateVportIndicesTest(unittest.TestCase):
    def test_existing_session_setup_rehydrates_before_use(self):
        ixia = _create_ixia_instance()
        port_configs = [MagicMock()]
        ixia.ixia_recovery = None
        ixia.session_id = 524
        ixia.is_existing_session = True
        ixia.cleanup_config = True
        ixia.ixia_config = SimpleNamespace(
            port_configs=port_configs,
            traffic_items=[],
        )
        ixia.connect = MagicMock()
        ixia.rehydrate_vport_indices = MagicMock()
        ixia.verify_ip_advertise_gating = MagicMock()
        ixia.start_and_verify_protocols = MagicMock()

        ixia._create_basic_setup(trial_traffic_interval_s=0)

        ixia.rehydrate_vport_indices.assert_called_once_with(port_configs)
        ixia.verify_ip_advertise_gating.assert_called_once_with()
        ixia.start_and_verify_protocols.assert_called_once_with()

    def test_existing_session_rehydration_failure_is_actionable(self):
        ixia = _create_ixia_instance()
        ixia.ixia_recovery = None
        ixia.session_id = 524
        ixia.is_existing_session = True
        ixia.cleanup_config = True
        ixia.ixia_config = SimpleNamespace(port_configs=[], traffic_items=[])
        ixia.connect = MagicMock()
        ixia.rehydrate_vport_indices = MagicMock(
            side_effect=IxiaSetupError("missing vport")
        )

        with self.assertRaisesRegex(
            IxiaSetupError,
            "Retained IXIA session 524 does not match the requested topology",
        ):
            ixia._create_basic_setup(trial_traffic_interval_s=0)

    def test_rehydrates_existing_topology_from_declarative_config(self):
        ixia = _create_ixia_instance()
        port_identifier = "FSW004.P004.F01.QZD1:ETH7/16/1"
        device_group_identifier = f"D0_{port_identifier}"
        network_group_identifier = f"N0_{device_group_identifier}"

        ipv6 = SimpleNamespace(
            Name=DESIRED_IPV6_NAME.format(port_identifier=device_group_identifier)
        )
        ethernet = SimpleNamespace(
            Name=DESIRED_ETHERNET_NAME.format(port_identifier=device_group_identifier),
            Ipv4=_FindByName([]),
            Ipv6=_FindByName([ipv6]),
        )
        network_group = SimpleNamespace(
            Name=DESIRED_V6_BGP_PREFIX_NAME.format(
                port_identifier=network_group_identifier
            )
        )
        device_group = SimpleNamespace(
            Name=DESIRED_DEVICE_GROUP_NAME.format(
                port_identifier=device_group_identifier
            ),
            Ethernet=_FindByName([ethernet]),
            NetworkGroup=_FindByName([network_group]),
            DeviceGroup=_FindByName([]),
        )
        topology = SimpleNamespace(
            Name=DESIRED_TOPOLOGY_NAME.format(port_identifier=port_identifier),
            DeviceGroup=_FindByName([device_group]),
        )
        vport = SimpleNamespace(
            Name=DESIRED_VPORT_NAME.format(port_identifier=port_identifier)
        )
        ixia.ixnetwork = SimpleNamespace(
            Vport=_FindByName([vport]),
            Topology=_FindByName([topology]),
        )
        ixia.tag_name_to_device_group_name_list = {}

        bgp_prefix = SimpleNamespace(
            network_group_index=0,
            ip_address_family=None,
        )
        bgp_v6_config = SimpleNamespace(
            ip_address_family=ixia_types.IpAddressFamily.IPV6,
            custom_network_group_configs=None,
            bgp_prefix_configs=[bgp_prefix],
            import_bgp_routes_params_list=None,
        )
        device_group_config = SimpleNamespace(
            device_group_index=0,
            tag_name=None,
            device_group_name=None,
            ip_addresses_config=SimpleNamespace(
                ipv4_addresses_config=None,
                ipv6_addresses_config=object(),
            ),
            bgp_config=SimpleNamespace(
                bgp_v4_config=None,
                bgp_v6_config=bgp_v6_config,
            ),
        )
        port_config = SimpleNamespace(
            port_name="fsw004.p004.f01.qzd1:eth7/16/1",
            device_group_configs=[device_group_config],
        )

        ixia.rehydrate_vport_indices([port_config])

        vport_index = ixia.vport_indices[port_identifier]
        self.assertEqual(vport_index.name, vport.Name)
        self.assertEqual(vport_index.topology_name, topology.Name)
        device_group_index = vport_index.device_group_indices[0]
        self.assertIs(device_group_index.device_group, device_group)
        self.assertIs(device_group_index.ethernet, ethernet)
        self.assertIs(device_group_index.ipv6, ipv6)
        self.assertIs(
            device_group_index.network_group_indices[0].network_group,
            network_group,
        )
