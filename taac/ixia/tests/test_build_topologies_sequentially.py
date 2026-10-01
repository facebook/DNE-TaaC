# pyre-unsafe — extensive MagicMock substitution for the IxNetwork REST
# objects used by the helper under test.
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""Unit tests for `_build_topologies_and_device_groups`."""

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import call, MagicMock, patch

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
    ixia._is_deferred_routed_traffic_preparation_enabled = MagicMock(return_value=True)
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

    def test_existing_session_can_replace_traffic_items(self):
        ixia = _create_ixia_instance()
        port_configs = [MagicMock()]
        traffic_items = [SimpleNamespace(source_endpoints=[], dest_endpoints=[])]
        ixia.ixia_recovery = None
        ixia.session_id = 524
        ixia.is_existing_session = True
        ixia.cleanup_config = True
        ixia.override_traffic_items = True
        ixia.ixia_config = SimpleNamespace(
            port_configs=port_configs,
            traffic_items=traffic_items,
        )
        ixia.connect = MagicMock()
        ixia.rehydrate_vport_indices = MagicMock()
        ixia.verify_ip_advertise_gating = MagicMock()
        ixia.start_and_verify_protocols = MagicMock()
        ixia.create_traffic_items = MagicMock()
        ixia.start_traffic = MagicMock()
        ixia.stop_traffic = MagicMock()

        ixia._create_basic_setup(trial_traffic_interval_s=0)

        ixia.create_traffic_items.assert_called_once_with(
            traffic_items,
            override_traffic_items=True,
            generate_traffic_items=True,
        )
        ixia.start_traffic.assert_called_once_with()
        ixia.stop_traffic.assert_called_once_with()

    def test_routed_traffic_generation_is_deferred_until_after_dut_setup(self):
        ixia = _create_ixia_instance()
        port_configs = [MagicMock()]
        traffic_items = [
            SimpleNamespace(
                source_endpoints=[SimpleNamespace(network_group_index=None)],
                dest_endpoints=[SimpleNamespace(network_group_index=0)],
            )
        ]
        ixia.ixia_recovery = None
        ixia.session_id = 524
        ixia.is_existing_session = True
        ixia.cleanup_config = True
        ixia.override_traffic_items = True
        ixia.ixia_config = SimpleNamespace(
            port_configs=port_configs,
            traffic_items=traffic_items,
        )
        ixia.connect = MagicMock()
        ixia.rehydrate_vport_indices = MagicMock()
        ixia.verify_ip_advertise_gating = MagicMock()
        ixia.start_and_verify_protocols = MagicMock()
        ixia.create_traffic_items = MagicMock()
        ixia.start_traffic = MagicMock()
        ixia.stop_traffic = MagicMock()

        ixia._create_basic_setup(trial_traffic_interval_s=0)

        ixia.create_traffic_items.assert_called_once_with(
            traffic_items,
            override_traffic_items=True,
            generate_traffic_items=False,
        )
        self.assertTrue(ixia._defer_traffic_preparation)
        ixia.start_traffic.assert_not_called()
        ixia.stop_traffic.assert_not_called()

    def test_disabled_gate_preserves_immediate_routed_traffic_setup(self):
        ixia = _create_ixia_instance()
        port_configs = [MagicMock()]
        traffic_items = [
            SimpleNamespace(
                source_endpoints=[SimpleNamespace(network_group_index=None)],
                dest_endpoints=[SimpleNamespace(network_group_index=0)],
            )
        ]
        ixia.ixia_recovery = None
        ixia.session_id = 524
        ixia.is_existing_session = True
        ixia.cleanup_config = True
        ixia.override_traffic_items = True
        ixia.ixia_config = SimpleNamespace(
            port_configs=port_configs,
            traffic_items=traffic_items,
        )
        ixia.connect = MagicMock()
        ixia.rehydrate_vport_indices = MagicMock()
        ixia.verify_ip_advertise_gating = MagicMock()
        ixia.start_and_verify_protocols = MagicMock()
        ixia.create_traffic_items = MagicMock()
        ixia.start_traffic = MagicMock()
        ixia.stop_traffic = MagicMock()
        ixia._is_deferred_routed_traffic_preparation_enabled.return_value = False

        ixia._create_basic_setup(trial_traffic_interval_s=0)

        ixia.create_traffic_items.assert_called_once_with(
            traffic_items,
            override_traffic_items=True,
            generate_traffic_items=True,
        )
        self.assertFalse(ixia._defer_traffic_preparation)
        ixia.start_traffic.assert_called_once_with()
        ixia.stop_traffic.assert_called_once_with()

    def test_mixed_routed_and_direct_traffic_defers_entire_set(self):
        ixia = _create_ixia_instance()
        routed = SimpleNamespace(
            source_endpoints=[SimpleNamespace(network_group_index=None)],
            dest_endpoints=[SimpleNamespace(network_group_index=0)],
        )
        direct = SimpleNamespace(
            source_endpoints=[SimpleNamespace(network_group_index=None)],
            dest_endpoints=[SimpleNamespace(network_group_index=None)],
        )

        self.assertTrue(ixia._requires_post_setup_traffic_preparation([routed, direct]))
        ixia.logger.warning.assert_called_once_with(
            "Mixed routed and directly connected IXIA traffic items defer "
            "preparation for the entire set"
        )

    def test_override_defers_unique_replacement_without_deleting_collision(self):
        ixia = _create_ixia_instance()
        existing = MagicMock()
        colliding_item = MagicMock()
        replacement = MagicMock()
        replacement.ConfigElement.find.return_value = [MagicMock()]
        ixia.ixnetwork.Traffic.TrafficItem.find.side_effect = [
            existing,
            colliding_item,
            None,
        ]
        ixia.ixnetwork.Traffic.TrafficItem.add.return_value = replacement
        ixia.configure_frame_setup = MagicMock()
        ixia.configure_rate_setup = MagicMock()
        ixia.modify_traffic_options = MagicMock()
        traffic_item = MagicMock()
        traffic_item.name = "replacement_flow"
        traffic_item.traffic_type = ixia_types.TrafficType.IPV4
        traffic_item.source_endpoints = []
        traffic_item.dest_endpoints = []
        traffic_item.packet_headers = []
        traffic_item.hoplimit_config = None
        traffic_item.qos_config = None
        traffic_item.l4_protocol_config = None
        traffic_item.enabled = True
        traffic_item.traffic_flow_config = SimpleNamespace(tracking_types=[])

        with (
            patch(
                "neteng.test_infra.dne.taac.ixia.ixia.uuid.uuid4",
                side_effect=[
                    SimpleNamespace(hex="collision"),
                    SimpleNamespace(hex="unique"),
                ],
            ),
            patch.object(Ixia, "update_traffic_item_global_params"),
            patch.object(Ixia, "configure_traffic_stats_tracking"),
        ):
            ixia.create_traffic_items(
                [traffic_item],
                override_traffic_items=True,
                generate_traffic_items=False,
            )

        existing.remove.assert_not_called()
        colliding_item.remove.assert_not_called()
        ixia.ixnetwork.Traffic.TrafficItem.find.assert_has_calls(
            [
                call(Name=r"^replacement_flow$"),
                call(Name=r"^replacement_flow__taac_replacement_collision$"),
                call(Name=r"^replacement_flow__taac_replacement_unique$"),
            ]
        )
        ixia.ixnetwork.Traffic.TrafficItem.add.assert_called_once_with(
            Name="replacement_flow__taac_replacement_unique",
            TrafficType=ixia_types.TRAFFIC_TYPE_MAP[ixia_types.TrafficType.IPV4],
        )
        replacement.update.assert_called_once_with(Enabled=False)
        replacement.Generate.assert_not_called()
        self.assertEqual(
            [
                (
                    "replacement_flow",
                    "replacement_flow__taac_replacement_unique",
                )
            ],
            ixia._deferred_traffic_item_replacements,
        )

    def test_finalize_deferred_replacement_swaps_generated_item(self):
        ixia = _create_ixia_instance()
        existing = MagicMock()
        replacement = MagicMock()
        ixia._deferred_traffic_item_replacements = [
            ("replacement_flow", "replacement_flow__taac_replacement")
        ]
        ixia.ixnetwork.Traffic.TrafficItem.find.side_effect = [
            replacement,
            existing,
        ]
        operations = MagicMock()
        operations.attach_mock(existing.update, "rename_previous")
        operations.attach_mock(replacement.update, "install_replacement")
        operations.attach_mock(existing.remove, "remove_previous")

        ixia.finalize_deferred_traffic_item_replacements()

        self.assertEqual(
            [
                call.rename_previous(
                    Name="replacement_flow__taac_replacement__previous"
                ),
                call.install_replacement(Name="replacement_flow"),
                call.remove_previous(),
            ],
            operations.mock_calls,
        )
        existing.update.assert_called_once_with(
            Name="replacement_flow__taac_replacement__previous"
        )
        existing.remove.assert_called_once_with()
        replacement.update.assert_called_once_with(Name="replacement_flow")
        self.assertEqual([], ixia._deferred_traffic_item_replacements)

    def test_finalize_deferred_replacement_deduplicates_pending_state(self):
        ixia = _create_ixia_instance()
        existing = MagicMock()
        replacement = MagicMock()
        replacement_key = (
            "replacement_flow",
            "replacement_flow__taac_replacement",
        )
        ixia._deferred_traffic_item_replacements = [
            replacement_key,
            replacement_key,
        ]
        ixia.ixnetwork.Traffic.TrafficItem.find.side_effect = [
            replacement,
            existing,
        ]

        ixia.finalize_deferred_traffic_item_replacements()

        existing.update.assert_called_once_with(
            Name="replacement_flow__taac_replacement__previous"
        )
        existing.remove.assert_called_once_with()
        replacement.update.assert_called_once_with(Name="replacement_flow")
        self.assertEqual([], ixia._deferred_traffic_item_replacements)

    def test_finalize_deferred_replacements_validates_all_before_swapping(self):
        ixia = _create_ixia_instance()
        first_existing = MagicMock()
        first_replacement = MagicMock()
        ixia._deferred_traffic_item_replacements = [
            ("first_flow", "first_flow__taac_replacement"),
            ("second_flow", "second_flow__taac_replacement"),
        ]
        ixia.ixnetwork.Traffic.TrafficItem.find.side_effect = [
            first_replacement,
            first_existing,
            None,
        ]

        with self.assertRaisesRegex(
            RuntimeError,
            "Deferred replacement second_flow__taac_replacement is missing",
        ):
            ixia.finalize_deferred_traffic_item_replacements()

        first_existing.update.assert_not_called()
        first_existing.remove.assert_not_called()
        first_replacement.update.assert_not_called()
        self.assertEqual(
            [
                ("first_flow", "first_flow__taac_replacement"),
                ("second_flow", "second_flow__taac_replacement"),
            ],
            ixia._deferred_traffic_item_replacements,
        )

    def test_finalize_deferred_replacements_retries_only_unfinished_swaps(self):
        ixia = _create_ixia_instance()
        first_existing = MagicMock()
        first_replacement = MagicMock()
        second_existing = MagicMock()
        second_replacement = MagicMock()
        third_existing = MagicMock()
        third_replacement = MagicMock()
        second_replacement.update.side_effect = [RuntimeError("rename failed"), None]
        ixia._deferred_traffic_item_replacements = [
            ("first_flow", "first_flow__taac_replacement"),
            ("second_flow", "second_flow__taac_replacement"),
            ("third_flow", "third_flow__taac_replacement"),
        ]
        ixia._deferred_traffic_item_replacement_swaps_started = set()
        ixia.ixnetwork.Traffic.TrafficItem.find.side_effect = [
            first_replacement,
            first_existing,
            second_replacement,
            second_existing,
            third_replacement,
            third_existing,
        ]

        with self.assertRaisesRegex(
            RuntimeError,
            "Failed to install deferred replacements: second_flow: rename failed; "
            "pending replacements: second_flow",
        ):
            ixia.finalize_deferred_traffic_item_replacements()

        self.assertEqual(
            [("second_flow", "second_flow__taac_replacement")],
            ixia._deferred_traffic_item_replacements,
        )
        self.assertEqual(
            {("second_flow", "second_flow__taac_replacement")},
            ixia._deferred_traffic_item_replacement_swaps_started,
        )
        second_existing.update.assert_called_once_with(
            Name="second_flow__taac_replacement__previous"
        )
        second_existing.remove.assert_not_called()

        ixia.ixnetwork.Traffic.TrafficItem.find.side_effect = [
            second_replacement,
            second_existing,
        ]
        ixia.finalize_deferred_traffic_item_replacements()

        first_existing.remove.assert_called_once_with()
        first_replacement.update.assert_called_once_with(Name="first_flow")
        second_existing.remove.assert_called_once_with()
        third_existing.remove.assert_called_once_with()
        third_replacement.update.assert_called_once_with(Name="third_flow")
        self.assertEqual(2, second_replacement.update.call_count)
        self.assertEqual([], ixia._deferred_traffic_item_replacements)
        self.assertEqual(set(), ixia._deferred_traffic_item_replacement_swaps_started)

    def test_finalize_deferred_replacement_retries_backup_removal(self):
        ixia = _create_ixia_instance()
        previous_item = MagicMock()
        previous_item.remove.side_effect = [RuntimeError("remove failed"), None]
        replacement = MagicMock()
        installed_replacement = MagicMock()
        replacement_key = (
            "replacement_flow",
            "replacement_flow__taac_replacement",
        )
        ixia._deferred_traffic_item_replacements = [replacement_key]
        ixia._deferred_traffic_item_replacement_swaps_started = set()
        ixia.ixnetwork.Traffic.TrafficItem.find.side_effect = [
            replacement,
            previous_item,
        ]

        with self.assertRaisesRegex(
            RuntimeError,
            "Failed to install deferred replacements: replacement_flow: remove failed",
        ):
            ixia.finalize_deferred_traffic_item_replacements()

        self.assertEqual([replacement_key], ixia._deferred_traffic_item_replacements)
        self.assertEqual(
            {replacement_key},
            ixia._deferred_traffic_item_replacement_swaps_started,
        )

        ixia.ixnetwork.Traffic.TrafficItem.find.side_effect = [
            None,
            previous_item,
            installed_replacement,
        ]
        ixia.finalize_deferred_traffic_item_replacements()

        previous_item.update.assert_called_once_with(
            Name="replacement_flow__taac_replacement__previous"
        )
        replacement.update.assert_called_once_with(Name="replacement_flow")
        self.assertEqual(2, previous_item.remove.call_count)
        self.assertEqual([], ixia._deferred_traffic_item_replacements)
        self.assertEqual(set(), ixia._deferred_traffic_item_replacement_swaps_started)

    def test_finalize_deferred_replacement_cleans_up_backup_after_prior_rename(self):
        ixia = _create_ixia_instance()
        previous_item = MagicMock()
        installed_replacement = MagicMock()
        replacement_key = (
            "replacement_flow",
            "replacement_flow__taac_replacement",
        )
        ixia._deferred_traffic_item_replacements = [replacement_key]
        ixia._deferred_traffic_item_replacement_swaps_started = {replacement_key}
        ixia.ixnetwork.Traffic.TrafficItem.find.side_effect = [
            None,
            previous_item,
            installed_replacement,
        ]

        ixia.finalize_deferred_traffic_item_replacements()

        previous_item.remove.assert_called_once_with()
        installed_replacement.remove.assert_not_called()
        installed_replacement.update.assert_not_called()
        self.assertEqual([], ixia._deferred_traffic_item_replacements)
        self.assertEqual(set(), ixia._deferred_traffic_item_replacement_swaps_started)

    def test_override_keeps_existing_item_when_replacement_configuration_fails(self):
        ixia = _create_ixia_instance()
        existing = MagicMock()
        replacement = MagicMock()
        replacement.ConfigElement.find.return_value = [MagicMock()]
        ixia.ixnetwork.Traffic.TrafficItem.find.side_effect = [existing, None]
        ixia.ixnetwork.Traffic.TrafficItem.add.return_value = replacement
        ixia.configure_frame_setup = MagicMock(
            side_effect=RuntimeError("frame setup failed")
        )
        traffic_item = MagicMock()
        traffic_item.name = "replacement_flow"
        traffic_item.traffic_type = ixia_types.TrafficType.IPV4
        traffic_item.source_endpoints = []
        traffic_item.dest_endpoints = []
        traffic_item.packet_headers = []
        traffic_item.hoplimit_config = None
        traffic_item.qos_config = None
        traffic_item.l4_protocol_config = None
        traffic_item.enabled = True
        traffic_item.traffic_flow_config = SimpleNamespace(tracking_types=[])

        with (
            patch.object(Ixia, "update_traffic_item_global_params"),
            self.assertRaisesRegex(RuntimeError, "frame setup failed"),
        ):
            ixia.create_traffic_items(
                [traffic_item],
                override_traffic_items=True,
                generate_traffic_items=False,
            )

        existing.remove.assert_not_called()

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
