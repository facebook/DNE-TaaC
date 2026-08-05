# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from taac.constants import BgpPlusPlusProfile
from taac.playbooks.routing.bgp_ebb_playbooks import (
    get_bgp_ebb_attribute_churn_playbook,
)
from taac.stages.stage_definitions import (
    create_bgp_ebb_attribute_churn_stage,
)
from taac.steps.step_definitions import (
    create_bgp_attribute_churn_step,
)
from taac.testconfigs.routing.factories.bgp_ebb_full_scale import (
    _get_bgp_ebb_full_scale_playbooks,
    _TC7_PLAYBOOK_NAMES,
    create_bgp_ebb_full_scale_test_config,
)
from taac.test_as_a_config import types as taac_types


EXPECTED_POOLS = {
    "ipv4": {
        "1": "PREFIX_POOL_IBGP_IPV4_PLANE_1_REMOTE_EB",
        "2": "PREFIX_POOL_IBGP_IPV4_PLANE_2_REMOTE_EB",
        "3": "PREFIX_POOL_IBGP_IPV4_PLANE_3_REMOTE_EB",
        "4": "PREFIX_POOL_IBGP_IPV4_PLANE_4_REMOTE_EB",
    },
    "ipv6": {
        "1": "PREFIX_POOL_IBGP_IPV6_PLANE_1_REMOTE_EB",
        "2": "PREFIX_POOL_IBGP_IPV6_PLANE_2_REMOTE_EB",
        "3": "PREFIX_POOL_IBGP_IPV6_PLANE_3_REMOTE_EB",
        "4": "PREFIX_POOL_IBGP_IPV6_PLANE_4_REMOTE_EB",
    },
}

EXPECTED_MATRIX = {
    "local_pref": {
        "plane_1_preferred": 200,
        "reference": 100,
        "plane_1_nonpreferred": 50,
    },
    "med": {
        "plane_1_preferred": 100,
        "reference": 200,
        "plane_1_nonpreferred": 300,
    },
    "origin": {
        "plane_1_preferred": "igp",
        "reference": "egp",
        "plane_1_nonpreferred": "incomplete",
    },
    "as_path": {
        "plane_1_preferred": 1,
        "reference": 5,
        "plane_1_nonpreferred": 10,
    },
}


def _locked_step_kwargs() -> dict:
    return {
        "hostname": "dut.example.com",
        "prefix_pool_names": EXPECTED_POOLS,
        "observer_peer_parent_prefix": "2401:db00:e50d:22:a::/80",
        "peer_count_per_plane": 62,
        "selected_block_count_per_afi": 7,
        "samples_per_block": 2,
        "routes_per_block": 750,
        "iterations_per_family": 15,
        "cadence_seconds": 60,
        "poll_interval_seconds": 5,
        "transition_timeout_seconds": 60,
        "convergence_hard_timeout_seconds": 300,
        "reference_setup_timeout_seconds": 120,
        "restore_timeout_seconds": 120,
        "quiet_window_seconds": 120,
        "max_lookup_concurrency": 8,
        "attribute_matrix": EXPECTED_MATRIX,
    }


def _step_payload(step: taac_types.Step) -> dict:
    params = step.step_params
    if params is None:
        raise AssertionError("custom step is missing step_params")
    json_params = params.json_params
    if json_params is None:
        raise AssertionError("custom step is missing serialized json_params")
    return json.loads(json_params)


class BgpAttributeChurnPlaybookTest(unittest.TestCase):
    def test_step_factory_serializes_locked_contract(self) -> None:
        step = create_bgp_attribute_churn_step(**_locked_step_kwargs())

        self.assertEqual(taac_types.StepName.CUSTOM_STEP, step.name)
        payload = _step_payload(step)
        self.assertEqual("bgp_attribute_churn", payload["custom_step_name"])
        self.assertEqual(EXPECTED_POOLS, payload["prefix_pool_names"])
        self.assertEqual(EXPECTED_MATRIX, payload["attribute_matrix"])
        self.assertEqual(7, payload["selected_block_count_per_afi"])
        self.assertEqual(15, payload["iterations_per_family"])
        self.assertEqual(300, payload["convergence_hard_timeout_seconds"])

    def test_step_factory_rejects_incomplete_pool_geometry(self) -> None:
        kwargs = _locked_step_kwargs()
        kwargs["prefix_pool_names"] = {
            "ipv4": EXPECTED_POOLS["ipv4"],
            "ipv6": {"1": EXPECTED_POOLS["ipv6"]["1"]},
        }

        with self.assertRaises(ValueError):
            create_bgp_attribute_churn_step(**kwargs)

    def test_step_factory_allows_zero_quiet_window(self) -> None:
        kwargs = _locked_step_kwargs()
        kwargs["quiet_window_seconds"] = 0

        payload = _step_payload(create_bgp_attribute_churn_step(**kwargs))

        self.assertEqual(0, payload["quiet_window_seconds"])

    def test_step_factory_rejects_negative_quiet_window(self) -> None:
        kwargs = _locked_step_kwargs()
        kwargs["quiet_window_seconds"] = -1

        with self.assertRaisesRegex(ValueError, "must be non-negative"):
            create_bgp_attribute_churn_step(**kwargs)

    def test_step_factory_requires_two_selected_blocks_per_afi(self) -> None:
        kwargs = _locked_step_kwargs()
        kwargs["selected_block_count_per_afi"] = 1

        with self.assertRaisesRegex(
            ValueError,
            "selected_block_count_per_afi must be at least 2",
        ):
            create_bgp_attribute_churn_step(**kwargs)

    def test_step_factory_requires_hard_timeout_above_soft_timeouts(self) -> None:
        kwargs = _locked_step_kwargs()
        kwargs["convergence_hard_timeout_seconds"] = 120

        with self.assertRaisesRegex(ValueError, "must exceed"):
            create_bgp_attribute_churn_step(**kwargs)

    def test_stage_contains_only_the_audited_custom_step(self) -> None:
        stage = create_bgp_ebb_attribute_churn_stage(**_locked_step_kwargs())

        self.assertEqual(1, len(stage.steps))
        payload = _step_payload(stage.steps[0])
        self.assertEqual("bgp_attribute_churn", payload["custom_step_name"])

    def test_playbook_wires_production_geometry_and_timing(self) -> None:
        playbook = get_bgp_ebb_attribute_churn_playbook(
            device_name="dut.example.com",
            peergroup_ibgp_v6="IBGP_V6",
            peergroup_ibgp_v4="IBGP_V4",
            total_session_count=1272,
            observer_peer_parent_prefix="2401:db00:e50d:22:a::/80",
            profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
        )

        self.assertEqual(1, len(playbook.stages))
        self.assertEqual(1, len(playbook.stages[0].steps))
        payload = _step_payload(playbook.stages[0].steps[0])
        self.assertEqual(EXPECTED_POOLS, payload["prefix_pool_names"])
        self.assertEqual(EXPECTED_MATRIX, payload["attribute_matrix"])
        self.assertEqual(
            {
                "peer_count_per_plane": 62,
                "selected_block_count_per_afi": 7,
                "samples_per_block": 2,
                "routes_per_block": 750,
                "iterations_per_family": 15,
                "cadence_seconds": 60,
                "poll_interval_seconds": 5,
                "transition_timeout_seconds": 60,
                "convergence_hard_timeout_seconds": 300,
                "reference_setup_timeout_seconds": 120,
                "restore_timeout_seconds": 120,
                "quiet_window_seconds": 120,
                "max_lookup_concurrency": 8,
            },
            {
                key: payload[key]
                for key in (
                    "peer_count_per_plane",
                    "selected_block_count_per_afi",
                    "samples_per_block",
                    "routes_per_block",
                    "iterations_per_family",
                    "cadence_seconds",
                    "poll_interval_seconds",
                    "transition_timeout_seconds",
                    "convergence_hard_timeout_seconds",
                    "reference_setup_timeout_seconds",
                    "restore_timeout_seconds",
                    "quiet_window_seconds",
                    "max_lookup_concurrency",
                )
            },
        )

    def test_openr_profile_enables_ibgp_pnh_check(self) -> None:
        target = (
            "neteng.test_infra.dne.taac.playbooks.routing."
            "bgp_ebb_playbooks.get_profile_checks"
        )
        with patch(target) as get_checks:
            get_checks.return_value = SimpleNamespace(
                prechecks=[],
                postchecks=[],
                snapshot_checks=[],
            )
            get_bgp_ebb_attribute_churn_playbook(
                device_name="dut.example.com",
                peergroup_ibgp_v6="IBGP_V6",
                peergroup_ibgp_v4="IBGP_V4",
                total_session_count=1272,
                observer_peer_parent_prefix="2401:db00:e50d:22:a::/80",
                profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
            )

        self.assertTrue(get_checks.call_args.args[1].check_ibgp_pnh)

    def test_full_scale_factory_passes_bgp_mon_parent(self) -> None:
        inventory = MagicMock()
        inventory.device_name = "dut.example.com"
        inventory.ixia_ports = [["Ethernet1"], ["Ethernet2"], ["Ethernet3"]]
        inventory.openr_standalone_link.owner = "owner"
        inventory.openr_standalone_link.helper = "helper"
        inventory.openr_standalone_link.kv_link.return_value = {}
        target = (
            "neteng.test_infra.dne.taac.testconfigs.routing.factories."
            "bgp_ebb_full_scale.get_bgp_ebb_attribute_churn_playbook"
        )

        with patch(target) as playbook_factory:
            playbook_factory.return_value = MagicMock()
            _get_bgp_ebb_full_scale_playbooks(
                inventory,
                BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
                bound=MagicMock(),
                selected_tc7_playbooks=set(),
            )

        self.assertEqual(
            "2401:db00:e50d:22:a::/80",
            playbook_factory.call_args.kwargs["observer_peer_parent_prefix"],
        )

    def test_full_scale_factory_enables_churn_baseline_only_when_selected(
        self,
    ) -> None:
        inventory = MagicMock()
        inventory.device_name = "dut.example.com"
        compiled = SimpleNamespace(
            endpoints=[],
            host_os_type_map={},
            setup_tasks=[],
            teardown_tasks=[],
            basic_port_configs=[],
        )
        topology_target = (
            "neteng.test_infra.dne.taac.testconfigs.routing.factories."
            "bgp_ebb_full_scale.ebb_full_scale_topology"
        )
        playbooks_target = (
            "neteng.test_infra.dne.taac.testconfigs.routing.factories."
            "bgp_ebb_full_scale._get_bgp_ebb_full_scale_playbooks"
        )

        for selected, expected_churn, expected_ebgp_prefix_count in (
            (None, True, 850),
            (["bgp_ebb_attribute_churn_playbook"], True, 750),
            (["bgp_ebb_route_storm_playbook"], False, 750),
            (["bgp_ebb_route_registry_runtime_update_playbook"], False, 850),
        ):
            available_playbooks = []
            if selected:
                available_playbooks = [taac_types.Playbook(name=selected[0])]
            with (
                self.subTest(selected=selected),
                patch(playbooks_target, return_value=available_playbooks),
                patch(topology_target) as topology_factory,
            ):
                topology_factory.return_value.bind_to_inventory.return_value.compile.return_value = compiled
                create_bgp_ebb_full_scale_test_config(
                    inventory,
                    name="test",
                    playbooks_selected=selected,
                    profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
                )

            self.assertEqual(
                expected_churn,
                topology_factory.call_args.kwargs["enable_attribute_churn"],
            )
            self.assertEqual(
                expected_ebgp_prefix_count,
                topology_factory.call_args.kwargs["ebgp_prefix_count"],
            )
            self.assertIsNone(
                topology_factory.call_args.kwargs["ebgp_static_prefix_count"]
            )
            self.assertEqual(
                "STANDALONE",
                topology_factory.call_args.kwargs["openr_mode"].name,
            )

    def test_full_scale_factory_rejects_invalid_playbook_selections(self) -> None:
        inventory = MagicMock()
        available = [taac_types.Playbook(name=name) for name in ("first", "second")]
        target = (
            "neteng.test_infra.dne.taac.testconfigs.routing.factories."
            "bgp_ebb_full_scale._get_bgp_ebb_full_scale_playbooks"
        )
        topology_target = (
            "neteng.test_infra.dne.taac.testconfigs.routing.factories."
            "bgp_ebb_full_scale.ebb_full_scale_topology"
        )
        topology = MagicMock()
        topology.bind_to_inventory.return_value = MagicMock()
        available_names = str(sorted(set(_TC7_PLAYBOOK_NAMES) | {"first", "second"}))

        for selected, message in (
            (
                ["unknown"],
                "Unknown BGP EBB playbook selections: ['unknown']; "
                f"available: {available_names}",
            ),
            (
                ["unknown", "also_unknown"],
                "Unknown BGP EBB playbook selections: ['unknown', 'also_unknown']; "
                f"available: {available_names}",
            ),
            (["first", "first"], "Duplicate BGP EBB playbook selections: ['first']"),
        ):
            with (
                self.subTest(selected=selected),
                patch(target, return_value=available),
                patch(topology_target, return_value=topology),
            ):
                with self.assertRaises(ValueError) as context:
                    create_bgp_ebb_full_scale_test_config(
                        inventory,
                        name="test",
                        playbooks_selected=selected,
                    )
                self.assertEqual(message, str(context.exception))

    def test_full_scale_factory_preserves_requested_playbook_order(self) -> None:
        inventory = MagicMock()
        inventory.device_name = "dut.example.com"
        compiled = SimpleNamespace(
            endpoints=[],
            host_os_type_map={},
            setup_tasks=[],
            teardown_tasks=[],
            basic_port_configs=[],
        )
        available = [
            taac_types.Playbook(name=name) for name in ("first", "second", "third")
        ]
        playbooks_target = (
            "neteng.test_infra.dne.taac.testconfigs.routing.factories."
            "bgp_ebb_full_scale._get_bgp_ebb_full_scale_playbooks"
        )
        topology_target = (
            "neteng.test_infra.dne.taac.testconfigs.routing.factories."
            "bgp_ebb_full_scale.ebb_full_scale_topology"
        )

        with (
            patch(playbooks_target, return_value=available),
            patch(topology_target) as topology_factory,
        ):
            topology_factory.return_value.bind_to_inventory.return_value.compile.return_value = compiled
            test_config = create_bgp_ebb_full_scale_test_config(
                inventory,
                name="test",
                playbooks_selected=["third", "first"],
            )

        self.assertEqual(
            ["third", "first"],
            [playbook.name for playbook in test_config.playbooks],
        )
