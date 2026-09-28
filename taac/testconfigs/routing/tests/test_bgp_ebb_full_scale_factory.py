# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
"""Focused coverage for EBB full-scale topology selection."""

import unittest
from types import SimpleNamespace
from unittest import mock

from taac.testconfigs.routing.factories import (
    bgp_ebb_full_scale as factory,
)
from taac.test_as_a_config import types as taac_types


_C16_PLAYBOOK = "bgp_ebb_nexthop_group_count_threshold_playbook"


def _inventory() -> mock.MagicMock:
    inventory = mock.MagicMock()
    inventory.device_name = "bag012.ash6"
    inventory.ixia_ports = []
    return inventory


def _compiled_topology() -> mock.MagicMock:
    topology = mock.MagicMock()
    topology.bind_to_inventory.return_value.compile.return_value = SimpleNamespace(
        endpoints=[],
        host_os_type_map={},
        setup_tasks=[],
        teardown_tasks=[],
        basic_port_configs=[],
    )
    return topology


class BgpEbbFullScaleFactoryTest(unittest.TestCase):
    def test_setup_only_compiles_canonical_topology_without_playbooks(self) -> None:
        topology = _compiled_topology()
        with (
            mock.patch.object(
                factory, "ebb_full_scale_topology", return_value=topology
            ) as topology_builder,
            mock.patch.object(
                factory, "_get_bgp_ebb_full_scale_playbooks"
            ) as playbook_builder,
        ):
            config = factory.create_bgp_ebb_full_scale_test_config(
                _inventory(),
                name="BAG012_DIVERSE_SETUP_ONLY",
                setup_only=True,
            )

        self.assertEqual([], list(config.playbooks))
        topology_builder.assert_called_once()
        playbook_builder.assert_not_called()
        self.assertEqual(750, topology_builder.call_args.kwargs["ebgp_prefix_count"])
        self.assertFalse(topology_builder.call_args.kwargs["route_storm_shards"])
        topology.bind_to_inventory.assert_called_once()

    def test_setup_only_rejects_any_playbook_selector(self) -> None:
        for selection in ([], [_C16_PLAYBOOK]):
            with self.subTest(selection=selection):
                with self.assertRaisesRegex(
                    ValueError, "setup_only requires playbooks_selected=None"
                ):
                    factory.create_bgp_ebb_full_scale_test_config(
                        _inventory(),
                        name="INVALID_SETUP_ONLY",
                        playbooks_selected=selection,
                        setup_only=True,
                    )

    def test_c16_uses_canonical_diverse_topology(self) -> None:
        topology = _compiled_topology()
        playbook = taac_types.Playbook(name=_C16_PLAYBOOK)
        with (
            mock.patch.object(
                factory, "ebb_full_scale_topology", return_value=topology
            ) as topology_builder,
            mock.patch.object(
                factory,
                "_get_bgp_ebb_full_scale_playbooks",
                return_value=[playbook],
            ) as playbook_builder,
        ):
            config = factory.create_bgp_ebb_full_scale_test_config(
                _inventory(),
                name="BAG012_DIVERSE_C16",
                playbooks_selected=[_C16_PLAYBOOK],
            )

        self.assertEqual([_C16_PLAYBOOK], [item.name for item in config.playbooks])
        topology_builder.assert_called_once()
        playbook_builder.assert_called_once()
        self.assertFalse(topology_builder.call_args.kwargs["route_storm_shards"])

    def test_runtime_update_uses_canonical_850_prefix_inventory(self) -> None:
        topology = _compiled_topology()
        playbook_name = "bgp_ebb_route_registry_runtime_update_playbook"
        playbook = taac_types.Playbook(name=playbook_name)
        with (
            mock.patch.object(
                factory, "ebb_full_scale_topology", return_value=topology
            ) as topology_builder,
            mock.patch.object(
                factory,
                "_get_bgp_ebb_full_scale_playbooks",
                return_value=[playbook],
            ),
        ):
            config = factory.create_bgp_ebb_full_scale_test_config(
                _inventory(),
                name="BAG010_RUNTIME_UPDATE",
                playbooks_selected=[playbook_name],
            )

        self.assertEqual([playbook_name], [item.name for item in config.playbooks])
        self.assertEqual(850, topology_builder.call_args.kwargs["ebgp_prefix_count"])
