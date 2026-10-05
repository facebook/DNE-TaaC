# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
"""Focused coverage for EBB full-scale topology selection."""

import typing as t
import unittest
from types import SimpleNamespace
from unittest import mock

from taac.abstractions.topologies.ebb_full_scale import (
    EBB_OPENR_INJECTED_START_IPV4S,
    EBB_OPENR_INJECTED_START_IPV4S_IXIA03,
    EBB_OPENR_INJECTED_START_IPV6S,
    EBB_OPENR_INJECTED_START_IPV6S_IXIA03,
    EBB_PARENT_NETWORKS,
    EBB_PARENT_NETWORKS_IXIA03,
)
from taac.abstractions.topology.model import BoundTopology
from taac.testconfigs.routing.factories import (
    bgp_ebb_full_scale as factory,
)
from taac.test_as_a_config import types as taac_types


_C16_PLAYBOOK = "bgp_ebb_nexthop_group_count_threshold_playbook"
_BGP_MON_CANARY_BUILDERS = {
    "CICD-EBB-05": "get_bgp_ebb_ebgp_route_oscillation_playbook",
    "CICD-EBB-09": "get_bgp_ebb_multipath_group_oscillation_playbook",
    "CICD-EBB-12": "get_bgp_ebb_route_registry_runtime_update_playbook",
    "CICD-EBB-16": "get_bgp_ebb_nexthop_group_count_threshold_playbook",
}
_EBB_PLAYBOOK_BUILDERS = (
    "get_bgp_ebb_attribute_churn_playbook",
    "get_bgp_ebb_route_storm_playbook",
    "get_bgp_ebb_route_registry_runtime_update_playbook",
    "get_bgp_ebb_multipath_group_oscillation_playbook",
    "get_bgp_ebb_igp_pnh_metric_oscillation_playbook",
    "get_bgp_ebb_fauu_drain_undrain_playbook",
    "get_bgp_ebb_plane_drain_undrain_playbook",
    "get_bgp_ebb_longevity_playbook",
    "get_bgp_ebb_daemon_restart_playbook",
    "get_bgp_ebb_cold_start_playbook",
    "get_bgp_ebb_ebgp_session_oscillation_playbook",
    "get_bgp_ebb_ebgp_route_oscillation_playbook",
    "get_bgp_ebb_ibgp_plane_session_oscillation_playbook",
    "get_bgp_ebb_ibgp_route_oscillation_playbook",
    "get_bgp_ebb_igp_unresolvable_pnh_playbook",
    "get_bgp_ebb_nexthop_group_count_threshold_playbook",
)
_PNH_RANGE_BUILDERS = (
    "get_bgp_ebb_attribute_churn_playbook",
    "get_bgp_ebb_route_storm_playbook",
    "get_bgp_ebb_route_registry_runtime_update_playbook",
    "get_bgp_ebb_multipath_group_oscillation_playbook",
    "get_bgp_ebb_daemon_restart_playbook",
    "get_bgp_ebb_cold_start_playbook",
    "get_bgp_ebb_ebgp_session_oscillation_playbook",
    "get_bgp_ebb_ebgp_route_oscillation_playbook",
    "get_bgp_ebb_ibgp_plane_session_oscillation_playbook",
    "get_bgp_ebb_ibgp_route_oscillation_playbook",
)
_PNH_START_LIST_BUILDERS = (
    "get_bgp_ebb_igp_pnh_metric_oscillation_playbook",
    "get_bgp_ebb_igp_unresolvable_pnh_playbook",
)


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
        basic_traffic_item_configs=[],
    )
    return topology


def _bound_shape(prefix_count: int) -> BoundTopology:
    topology = factory.ebb_full_scale_topology(
        openr_mode=factory.OpenRMode.STANDALONE,
        ebgp_prefix_count=prefix_count,
    )
    return t.cast(
        BoundTopology,
        SimpleNamespace(
            device_groups=[
                SimpleNamespace(
                    role=group.role,
                    afi=group.afi,
                    peer_count=group.peer_count,
                    prefix_advertisements=[
                        SimpleNamespace(spec=advertisement)
                        for advertisement in group.prefix_advertisements
                    ],
                )
                for group in topology.device_groups
            ]
        ),
    )


class BgpEbbFullScaleFactoryTest(unittest.TestCase):
    _AUTOMATION = factory._EbbAutomationContract(
        non_monitor_established_session_count=1272,
        internal_peer_group_names_by_afi={"ipv4": "IBGP-V4", "ipv6": "IBGP-V6"},
        ebgp_peer_group_names_by_afi={"ipv4": "EBGP-V4", "ipv6": "EBGP-V6"},
        ebgp_peer_item_names_by_afi={"ipv4": "PEER-V4", "ipv6": "PEER-V6"},
        ebgp_peer_counts_by_afi={"ipv4": 140, "ipv6": 140},
        ebgp_route_item_names_by_afi={
            "ipv4": "ROUTE.POOL[V4]",
            "ipv6": "ROUTE+POOL(V6)",
        },
    )

    def test_all_ebb_playbooks_use_bound_bgp_mon_network(self) -> None:
        bgp_mon_parent_network = "2401:db00:e50d:44:a"
        inventory = _inventory()
        inventory.ixia_ports = [("Ethernet1",), ("Ethernet2",)]
        bound = t.cast(
            BoundTopology,
            SimpleNamespace(
                device_config=SimpleNamespace(
                    fibagent_bgp_nhg_watermark_high=1000,
                    fibagent_bgp_nhg_watermark_low=1000,
                ),
                parent_networks={"bgpmon_v6": bgp_mon_parent_network},
            ),
        )
        builders = {
            name: mock.Mock(return_value=taac_types.Playbook(name=name))
            for name in _EBB_PLAYBOOK_BUILDERS
        }
        with (
            mock.patch.multiple(factory, **builders),
            mock.patch.object(
                factory,
                "_ebb_route_count_histogram_by_afi",
                return_value={"ipv4": {}, "ipv6": {}},
            ),
            mock.patch.object(
                factory,
                "_ebb_peer_prefix_exclusion_blocks_by_pool",
                return_value={
                    "ROUTE.POOL[V4]": [],
                    "ROUTE+POOL(V6)": [],
                },
            ),
            mock.patch.object(
                factory,
                "_ebb_automation_contract",
                return_value=self._AUTOMATION,
            ),
            mock.patch.object(factory, "_nhg_storm_ixia_items", return_value={}),
            mock.patch.object(factory, "build_expected_peer_identity", return_value={}),
            mock.patch.object(factory, "_openr_owner_kv_link", return_value={}),
            mock.patch.object(factory, "_openr_helper_kv_link", return_value={}),
        ):
            playbooks = factory._get_bgp_ebb_full_scale_playbooks(
                inventory,
                profile=factory.DEFAULT_PROFILE,
                bound=bound,
                ebgp_prefix_count=850,
                selected_tc7_playbooks=set(),
            )

        self.assertEqual(len(_EBB_PLAYBOOK_BUILDERS), len(playbooks))
        for name, builder in builders.items():
            with self.subTest(builder=name):
                self.assertEqual(
                    bgp_mon_parent_network,
                    builder.call_args.kwargs["bgp_mon_parent_network"],
                )

    def test_canary_cases_use_paired_canonical_bgp_mon_network(self) -> None:
        inventory = _inventory()
        inventory.ixia_ports = [("Ethernet1",), ("Ethernet2",)]
        canonical_pairs = (
            (
                "BAG/IXIA11",
                EBB_PARENT_NETWORKS,
                "2401:db00:e50d:22:a",
                "2401:db00:e50d:44:a",
                EBB_OPENR_INJECTED_START_IPV4S,
                EBB_OPENR_INJECTED_START_IPV6S,
            ),
            (
                "NRQ/IXIA03",
                EBB_PARENT_NETWORKS_IXIA03,
                "2401:db00:e50d:44:a",
                "2401:db00:e50d:22:a",
                EBB_OPENR_INJECTED_START_IPV4S_IXIA03,
                EBB_OPENR_INJECTED_START_IPV6S_IXIA03,
            ),
        )

        for (
            profile,
            parent_networks,
            expected,
            forbidden,
            start_ipv4s,
            start_ipv6s,
        ) in canonical_pairs:
            with self.subTest(profile=profile):
                self.assertEqual(expected, parent_networks["bgpmon_v6"])
                self.assertNotEqual(forbidden, parent_networks["bgpmon_v6"])
                bound = t.cast(
                    BoundTopology,
                    SimpleNamespace(
                        device_config=SimpleNamespace(
                            fibagent_bgp_nhg_watermark_high=1000,
                            fibagent_bgp_nhg_watermark_low=1000,
                            openr_injected_start_ipv4s=start_ipv4s,
                            openr_injected_start_ipv6s=start_ipv6s,
                        ),
                        parent_networks=parent_networks,
                    ),
                )
                builders = {
                    name: mock.Mock(return_value=taac_types.Playbook(name=name))
                    for name in _EBB_PLAYBOOK_BUILDERS
                }
                with (
                    mock.patch.multiple(factory, **builders),
                    mock.patch.object(
                        factory,
                        "_ebb_route_count_histogram_by_afi",
                        return_value={"ipv4": {}, "ipv6": {}},
                    ),
                    mock.patch.object(
                        factory,
                        "_ebb_peer_prefix_exclusion_blocks_by_pool",
                        return_value={
                            "ROUTE.POOL[V4]": [],
                            "ROUTE+POOL(V6)": [],
                        },
                    ),
                    mock.patch.object(
                        factory,
                        "_ebb_automation_contract",
                        return_value=self._AUTOMATION,
                    ),
                    mock.patch.object(
                        factory, "_nhg_storm_ixia_items", return_value={}
                    ),
                    mock.patch.object(
                        factory, "build_expected_peer_identity", return_value={}
                    ),
                    mock.patch.object(factory, "_openr_owner_kv_link", return_value={}),
                    mock.patch.object(
                        factory, "_openr_helper_kv_link", return_value={}
                    ),
                ):
                    factory._get_bgp_ebb_full_scale_playbooks(
                        inventory,
                        profile=factory.DEFAULT_PROFILE,
                        bound=bound,
                        ebgp_prefix_count=850,
                        selected_tc7_playbooks=set(),
                    )

                for catalog_id, builder_name in _BGP_MON_CANARY_BUILDERS.items():
                    with self.subTest(profile=profile, catalog_id=catalog_id):
                        configured = builders[builder_name].call_args.kwargs[
                            "bgp_mon_parent_network"
                        ]
                        self.assertEqual(expected, configured)
                        self.assertNotEqual(forbidden, configured)

                for builder_name in _PNH_RANGE_BUILDERS:
                    with self.subTest(profile=profile, builder=builder_name):
                        kwargs = builders[builder_name].call_args.kwargs
                        self.assertEqual(start_ipv4s, kwargs["ibgp_pnh_start_ipv4s"])
                        self.assertEqual(start_ipv6s, kwargs["ibgp_pnh_start_ipv6s"])

                for builder_name in _PNH_START_LIST_BUILDERS:
                    with self.subTest(profile=profile, builder=builder_name):
                        kwargs = builders[builder_name].call_args.kwargs
                        self.assertEqual(list(start_ipv4s), kwargs["start_ipv4s"])
                        self.assertEqual(list(start_ipv6s), kwargs["start_ipv6s"])

    def test_full_scale_rejects_missing_bgp_mon_network(self) -> None:
        inventory = _inventory()
        inventory.ixia_ports = [("Ethernet1",), ("Ethernet2",)]
        bound = t.cast(
            BoundTopology,
            SimpleNamespace(
                device_config=SimpleNamespace(
                    fibagent_bgp_nhg_watermark_high=1000,
                    fibagent_bgp_nhg_watermark_low=1000,
                ),
                parent_networks={},
            ),
        )

        with (
            mock.patch.object(
                factory,
                "_ebb_automation_contract",
                return_value=self._AUTOMATION,
            ),
            self.assertRaisesRegex(ValueError, "missing required bgpmon_v6"),
        ):
            factory._get_bgp_ebb_full_scale_playbooks(
                inventory,
                profile=factory.DEFAULT_PROFILE,
                bound=bound,
                ebgp_prefix_count=850,
                selected_tc7_playbooks=set(),
            )

    def test_canonical_route_contract_is_derived_per_afi(self) -> None:
        bound = _bound_shape(850)

        self.assertEqual(
            {
                "ipv4": {720: 50, 750: 90},
                "ipv6": {720: 50, 750: 90},
            },
            factory._ebb_route_count_histogram_by_afi(bound, 750),
        )
        self.assertEqual(
            {
                "ipv4": {816: 50, 850: 90},
                "ipv6": {816: 50, 850: 90},
            },
            factory._ebb_route_count_histogram_by_afi(bound, 850),
        )

    def test_route_histogram_unions_overlapping_exclusion_blocks(self) -> None:
        bound = _bound_shape(850)
        groups: list[t.Any] = list(bound.device_groups)
        first_uplink_index = next(
            index for index, group in enumerate(groups) if group.role == "uplink"
        )
        first_uplink = groups[first_uplink_index]
        advertisement = first_uplink.prefix_advertisements[0].spec
        groups[first_uplink_index] = SimpleNamespace(
            role=first_uplink.role,
            afi=first_uplink.afi,
            peer_count=first_uplink.peer_count,
            prefix_advertisements=[
                SimpleNamespace(
                    spec=SimpleNamespace(
                        allocation=advertisement.allocation,
                        peer_prefix_activation=SimpleNamespace(
                            exclusion_blocks=(
                                SimpleNamespace(
                                    prefix_start_index=10,
                                    prefix_count=10,
                                    peer_indices=(0,),
                                ),
                                SimpleNamespace(
                                    prefix_start_index=15,
                                    prefix_count=10,
                                    peer_indices=(0,),
                                ),
                            )
                        ),
                    )
                )
            ],
        )
        overlapping_bound = t.cast(BoundTopology, SimpleNamespace(device_groups=groups))

        histogram = factory._ebb_route_count_histogram_by_afi(overlapping_bound, 850)

        afi = "ipv4" if first_uplink.afi == "v4" else "ipv6"
        self.assertEqual({835: 1, 850: 139}, histogram[afi])

    def test_route_histogram_rejects_out_of_range_exclusion_peer(self) -> None:
        bound = _bound_shape(850)
        groups: list[t.Any] = list(bound.device_groups)
        first_uplink_index = next(
            index for index, group in enumerate(groups) if group.role == "uplink"
        )
        first_uplink = groups[first_uplink_index]
        advertisement = first_uplink.prefix_advertisements[0].spec
        groups[first_uplink_index] = SimpleNamespace(
            role=first_uplink.role,
            afi=first_uplink.afi,
            name="uplink-with-invalid-exclusion",
            peer_count=first_uplink.peer_count,
            prefix_advertisements=[
                SimpleNamespace(
                    spec=SimpleNamespace(
                        allocation=advertisement.allocation,
                        peer_prefix_activation=SimpleNamespace(
                            exclusion_blocks=(
                                SimpleNamespace(
                                    prefix_start_index=750,
                                    prefix_count=4,
                                    peer_indices=(first_uplink.peer_count,),
                                ),
                            )
                        ),
                    )
                )
            ],
        )
        invalid_bound = t.cast(BoundTopology, SimpleNamespace(device_groups=groups))

        with self.assertRaisesRegex(ValueError, "indices outside"):
            factory._ebb_route_count_histogram_by_afi(invalid_bound, 850)

    def test_canonical_exclusion_blocks_are_keyed_by_prefix_pool(self) -> None:
        blocks_by_pool = factory._ebb_peer_prefix_exclusion_blocks_by_pool(
            _bound_shape(850)
        )

        self.assertEqual(
            {"PREFIX_POOL_IPV4_EBGP", "PREFIX_POOL_IPV6_EBGP"},
            set(blocks_by_pool),
        )
        for blocks in blocks_by_pool.values():
            self.assertEqual(50, len(blocks))
            self.assertEqual(
                {
                    "prefix_start_index": 750,
                    "prefix_count": 4,
                    "peer_indices": [90, 91],
                },
                blocks[25],
            )

    def test_exclusion_blocks_reject_duplicate_prefix_pool_names(self) -> None:
        bound = _bound_shape(850)
        uplink_groups = [
            group for group in bound.device_groups if group.role == "uplink"
        ]
        first_spec = uplink_groups[0].prefix_advertisements[0].spec
        second_spec = uplink_groups[1].prefix_advertisements[0].spec
        duplicate_bound = t.cast(
            BoundTopology,
            SimpleNamespace(
                device_groups=[
                    SimpleNamespace(
                        role="uplink",
                        prefix_advertisements=[SimpleNamespace(spec=first_spec)],
                    ),
                    SimpleNamespace(
                        role="uplink",
                        prefix_advertisements=[
                            SimpleNamespace(
                                spec=SimpleNamespace(
                                    legacy_ixia_name=first_spec.legacy_ixia_name,
                                    peer_prefix_activation=(
                                        second_spec.peer_prefix_activation
                                    ),
                                )
                            )
                        ],
                    ),
                ]
            ),
        )

        with self.assertRaisesRegex(ValueError, "duplicate eBGP IXIA prefix-pool name"):
            factory._ebb_peer_prefix_exclusion_blocks_by_pool(duplicate_bound)

    def test_ebb12_oracle_keys_must_match_bound_automation_contract(self) -> None:
        histograms = {
            "ipv4": {720: 50, 750: 90},
            "ipv6": {720: 50, 750: 90},
        }
        blocks = {
            "ROUTE.POOL[V4]": [],
            "ROUTE+POOL(V6)": [],
        }
        factory._validate_ebb12_automation_oracles(
            self._AUTOMATION,
            histograms,
            histograms,
            blocks,
        )

        with self.assertRaisesRegex(ValueError, "route-count AFIs"):
            factory._validate_ebb12_automation_oracles(
                self._AUTOMATION,
                {"ipv4": histograms["ipv4"]},
                histograms,
                blocks,
            )
        with self.assertRaisesRegex(ValueError, "exclusion-block pools"):
            factory._validate_ebb12_automation_oracles(
                self._AUTOMATION,
                histograms,
                histograms,
                {"WRONG": []},
            )

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
