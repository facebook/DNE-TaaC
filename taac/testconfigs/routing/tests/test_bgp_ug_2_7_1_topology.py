# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Shared coverage for the canonical EBB full-scale UG 2.7 topology."""

import json
import typing as t
from types import SimpleNamespace
from unittest import mock

from later.unittest import TestCase
from taac.abstractions.physical_inventory import BAG012_ASH6
from taac.testconfigs.routing.factories import (
    bgp_ebb_full_scale as factory,
    bgp_ug_2_7_suite as suite,
)
from pyre_extensions import none_throws
from taac.health_check.health_check import types as hc_types

_PLAYBOOK_NAME = "bgp_ug_link_flap_recovery"
_RUNTIME_POOL_NAMES = {
    "PREFIX_POOL_IBGP_IPV4_UG_2_7_RUNTIME",
    "PREFIX_POOL_IBGP_IPV6_UG_2_7_RUNTIME",
    "PREFIX_POOL_IPV4_EBGP_UG_2_7_RUNTIME",
    "PREFIX_POOL_IPV6_EBGP_UG_2_7_RUNTIME",
}


def _device_groups(config) -> list:
    return [
        group
        for port in config.basic_port_configs or []
        for group in port.device_group_configs or []
    ]


def _route_specs(
    config,
    pool_names: t.Collection[str],
) -> list[tuple[str, str, int, int, str, tuple[str, ...]]]:
    specs = []
    for group in _device_groups(config):
        for bgp_config in (group.v4_bgp_config, group.v6_bgp_config):
            if bgp_config is None:
                continue
            for route in bgp_config.route_scales or []:
                scale = route.v4_route_scale or route.v6_route_scale
                if scale is None or scale.prefix_name not in pool_names:
                    continue
                specs.append(
                    (
                        group.device_group_name,
                        scale.prefix_name,
                        route.network_group_index,
                        scale.prefix_count,
                        scale.starting_prefixes,
                        tuple(scale.bgp_communities or ()),
                    )
                )
    return sorted(specs)


def _runtime_route_specs(
    config, case: str | None = None
) -> list[tuple[str, str, int, int, str, tuple[str, ...]]]:
    specs = _route_specs(config, _RUNTIME_POOL_NAMES)
    return [spec for spec in specs if case is None or case in spec[1]]


def _runtime_route_geometries(config) -> dict[str, tuple[int, int]]:
    geometries = {}
    for group in _device_groups(config):
        for bgp_config in (group.v4_bgp_config, group.v6_bgp_config):
            if bgp_config is None:
                continue
            for route in bgp_config.route_scales or []:
                scale = route.v4_route_scale or route.v6_route_scale
                if scale is not None and scale.prefix_name in _RUNTIME_POOL_NAMES:
                    geometries[scale.prefix_name] = (
                        scale.multiplier,
                        scale.prefix_count,
                    )
    return geometries


def _hardware_capacity_checks(checks) -> list:
    return [
        check
        for check in checks or []
        if check.name == hc_types.CheckName.HARDWARE_CAPACITY_CHECK
    ]


def _task_params(step) -> dict:
    task = json.loads(none_throws(step.input_json))["task"]
    return json.loads(task["params"]["json_params"])


def _json_params(step) -> dict:
    return json.loads(none_throws(none_throws(step.step_params).json_params))


def _setup_task_params(task) -> dict:
    return json.loads(none_throws(none_throws(task.params).json_params))


class BgpUg27SharedTopologyTest(TestCase):
    def test_selected_link_flap_derives_exact_bag012_cohorts(self) -> None:
        with mock.patch.object(
            factory,
            "create_bgp_ug_link_flap_recovery_playbook",
            wraps=factory.create_bgp_ug_link_flap_recovery_playbook,
        ) as playbook_factory:
            config = factory.create_bgp_ebb_full_scale_test_config(
                BAG012_ASH6,
                name="BAG012_UG_2_7_1_TEST",
                playbooks_selected=[_PLAYBOOK_NAME],
            )

        self.assertEqual(
            [_PLAYBOOK_NAME], [playbook.name for playbook in config.playbooks]
        )
        playbook_factory.assert_called_once()
        kwargs = playbook_factory.call_args.kwargs
        self.assertEqual("bag012.ash6", kwargs["device_name"])
        self.assertEqual("Ethernet3/36/1", kwargs["interface"])
        self.assertEqual(280, len(set(kwargs["target_peer_subnets"])))
        self.assertEqual(140, len(set(kwargs["recovered_ebgp_peer_addrs"])))
        self.assertEqual(
            {
                "EB-FA-V4": "ipv4",
                "EB-FA-V6": "ipv6",
                "EB-EB-V4": "ipv4",
                "EB-EB-V6": "ipv6",
            },
            kwargs["expected_afi_by_substring"],
        )
        self.assertFalse(
            any(
                check.check_id == "startup_hardware_capacity_baseline"
                for check in kwargs["prechecks"]
            )
        )

    def test_runtime_prefix_index_must_stay_inside_canonical_inventory(self) -> None:
        for index in (-1, True, 750):
            with self.subTest(index=index):
                with self.assertRaisesRegex(ValueError, "outside"):
                    factory._prefix_at_index(factory.EBB_EBGP_V4_PREFIX_SET, index)

    def test_unrelated_selection_does_not_add_recovery_route_intent(self) -> None:
        config = factory.create_bgp_ebb_full_scale_test_config(
            BAG012_ASH6,
            name="BAG012_UNRELATED_TEST",
            playbooks_selected=["bgp_ebb_longevity_playbook"],
        )

        self.assertEqual([], _runtime_route_specs(config))

    def test_runtime_route_pools_remain_compact(self) -> None:
        config = factory.create_bgp_ebb_full_scale_test_config(
            BAG012_ASH6,
            name="BAG012_UG_2_7_1_TEST",
            playbooks_selected=[_PLAYBOOK_NAME],
        )

        self.assertEqual(
            {pool_name: (1, 100) for pool_name in _RUNTIME_POOL_NAMES},
            _runtime_route_geometries(config),
        )

    def test_bgp_restart_uses_two_port_all_peer_stability_contract(self) -> None:
        config = factory.create_bgp_ebb_full_scale_test_config(
            BAG012_ASH6,
            name="BAG012_UG_2_7_4_TEST",
            playbooks_selected=["bgp_ug_bgp_daemon_restart"],
        )

        self.assertEqual(
            ["bgp_ug_bgp_daemon_restart"],
            [playbook.name for playbook in config.playbooks],
        )
        baseline = config.playbooks[0].stages[0]
        all_peer_snapshot = json.loads(
            none_throws(none_throws(baseline.steps[7].step_params).json_params)
        )
        peer_addrs = all_peer_snapshot["peer_addrs"]
        self.assertEqual(1272, len(set(peer_addrs)))
        self.assertEqual(636, sum(":" not in address for address in peer_addrs))
        self.assertEqual(636, sum(":" in address for address in peer_addrs))
        self.assertEqual(2, len(config.basic_port_configs or []))
        self.assertEqual(18, len(_device_groups(config)))
        self.assertEqual(
            [
                r"^PREFIX_POOL_IPV4_EBGP_UG_2_7_RUNTIME$",
                r"^PREFIX_POOL_IPV6_EBGP_UG_2_7_RUNTIME$",
            ],
            [_task_params(step)["prefix_pool_regex"] for step in baseline.steps[:2]],
        )
        validation = config.playbooks[0].stages[2]
        stable_hold = json.loads(
            none_throws(none_throws(validation.steps[4].step_params).json_params)
        )
        second_semantic_sample = json.loads(
            none_throws(none_throws(validation.steps[5].step_params).json_params)
        )
        second_route_sample = json.loads(
            none_throws(none_throws(validation.steps[6].step_params).json_params)
        )
        self.assertEqual(30, stable_hold["duration"])
        self.assertEqual("compare", second_semantic_sample["action"])
        self.assertEqual(4, second_semantic_sample["expected_group_count"])
        self.assertEqual(1272, second_semantic_sample["expected_session_count"])
        self.assertEqual(0, second_route_sample["min_delta"])
        self.assertEqual(0, second_route_sample["max_delta"])
        check_payloads = [
            json.loads(none_throws(none_throws(check.check_params).json_params))
            for check in none_throws(config.playbooks[0].prechecks)
            if check.check_params is not None and check.check_params.json_params
        ]
        group_check = next(
            payload
            for payload in check_payloads
            if payload.get("expected_group_count") == 4
        )
        self.assertEqual(
            {
                "EB-FA-V4": "ipv4",
                "EB-FA-V6": "ipv6",
                "EB-EB-V4": "ipv4",
                "EB-EB-V6": "ipv6",
            },
            group_check["expected_afi_by_substring"],
        )
        pre_capacity = _hardware_capacity_checks(config.playbooks[0].prechecks)
        post_capacity = _hardware_capacity_checks(config.playbooks[0].postchecks)
        self.assertEqual(1, len(pre_capacity))
        self.assertEqual(1, len(post_capacity))
        pre_params = json.loads(none_throws(pre_capacity[0].check_params).json_params)
        post_params = json.loads(none_throws(post_capacity[0].check_params).json_params)
        self.assertEqual(9_999, pre_params["fec_threshold"])
        self.assertEqual(999, pre_params["ecmp_threshold"])
        self.assertEqual(2**63 - 1, pre_params["max_ecmp_level1"])
        self.assertEqual(2**63 - 1, pre_params["max_ecmp_level2"])
        self.assertEqual(2**63 - 1, pre_params["max_ecmp_level3"])
        self.assertEqual(100, pre_params["watermark_delta_threshold"])
        self.assertFalse(pre_params["check_watermarks"])
        self.assertEqual(19_999, post_params["fec_threshold"])
        self.assertEqual(999, post_params["ecmp_threshold"])
        self.assertEqual(2**63 - 1, post_params["max_ecmp_level1"])
        self.assertEqual(2**63 - 1, post_params["max_ecmp_level2"])
        self.assertEqual(2**63 - 1, post_params["max_ecmp_level3"])
        self.assertEqual(100, post_params["watermark_delta_threshold"])
        self.assertFalse(post_params["check_watermarks"])

    def test_fibagent_restart_uses_two_port_continuity_contract(self) -> None:
        config = factory.create_bgp_ebb_full_scale_test_config(
            BAG012_ASH6,
            name="BAG012_UG_2_7_6_TEST",
            playbooks_selected=["bgp_ug_fibagent_restart"],
        )

        self.assertEqual(
            ["bgp_ug_fibagent_restart"],
            [playbook.name for playbook in config.playbooks],
        )
        playbook = config.playbooks[0]
        capture = json.loads(
            none_throws(
                none_throws(playbook.stages[0].steps[4].step_params).json_params
            )
        )
        restart_tracks = none_throws(playbook.stages[1].concurrent_steps)
        restart = json.loads(
            none_throws(none_throws(restart_tracks[0].steps[1].step_params).json_params)
        )
        monitor = json.loads(
            none_throws(none_throws(restart_tracks[1].steps[0].step_params).json_params)
        )
        self.assertEqual(4, capture["expected_group_count"])
        self.assertEqual(1272, capture["expected_session_count"])
        self.assertEqual("fibagent_restart", restart["action"])
        self.assertTrue(restart["require_uptime_change"])
        self.assertEqual("group_id", monitor["operational_continuity"])
        self.assertEqual(4, monitor["expected_group_count"])
        self.assertEqual(1272, monitor["expected_session_count"])
        self.assertTrue(monitor["require_uniform_sent_route_counts"])
        self.assertTrue(monitor["require_equal_sent_route_counts"])
        self.assertEqual(
            [
                r"^PREFIX_POOL_IPV4_EBGP_UG_2_7_RUNTIME$",
                r"^PREFIX_POOL_IPV6_EBGP_UG_2_7_RUNTIME$",
            ],
            [
                _task_params(step)["prefix_pool_regex"]
                for step in playbook.stages[0].steps[:2]
            ],
        )
        self.assertEqual(2, len(config.basic_port_configs or []))
        self.assertEqual(18, len(_device_groups(config)))

    def test_sustained_flap_derives_exact_bag012_heartbeat_matrix(self) -> None:
        config = factory.create_bgp_ebb_full_scale_test_config(
            BAG012_ASH6,
            name="BAG012_UG_2_7_2_TEST",
            playbooks_selected=["update_group_sustained_link_flap"],
        )
        self.assertEqual(
            ["update_group_sustained_link_flap"],
            [playbook.name for playbook in config.playbooks],
        )
        disruption = json.loads(
            none_throws(
                none_throws(
                    config.playbooks[0].stages[1].steps[0].step_params
                ).json_params
            )
        )
        self.assertEqual(
            ["Ethernet3/36/1", "Ethernet3/36/2"],
            [track["interface"] for track in disruption["port_tracks"]],
        )
        self.assertEqual(["IDLE"], disruption["expected_recovered_group_states"])
        self.assertEqual(4, disruption["expected_recovered_group_count"])
        self.assertEqual(600, disruption["recovered_group_state_timeout_seconds"])
        self.assertEqual(1, disruption["recovered_group_state_poll_interval_seconds"])
        self.assertEqual(
            [140, 140, 496, 496],
            sorted(
                leg["expected_receiver_count"]
                for scenario in disruption["heartbeat_scenarios"]
                for leg in scenario.get("legs", [])
            ),
        )
        self.assertEqual(
            4,
            len(
                {
                    regex
                    for scenario in disruption["heartbeat_scenarios"]
                    for leg in scenario.get("legs", [])
                    for regex in leg["source_prefix_pool_regexes"]
                }
            ),
        )
        self.assertEqual(
            [
                "route",
                "structural",
                "structural",
                "structural",
            ],
            [
                scenario["verification_mode"]
                for scenario in disruption["heartbeat_scenarios"]
            ],
        )
        self.assertEqual(
            [
                [],
                ["ebgp"],
                ["ibgp"],
                ["ebgp", "ibgp"],
            ],
            [scenario["down_roles"] for scenario in disruption["heartbeat_scenarios"]],
        )
        route_legs = disruption["heartbeat_scenarios"][0]["legs"]
        self.assertEqual(
            [
                r"^PREFIX_POOL_IPV4_EBGP_UG_2_7_RUNTIME$",
                r"^PREFIX_POOL_IPV6_EBGP_UG_2_7_RUNTIME$",
                r"^PREFIX_POOL_IBGP_IPV4_UG_2_7_RUNTIME$",
                r"^PREFIX_POOL_IBGP_IPV6_UG_2_7_RUNTIME$",
            ],
            [leg["source_prefix_pool_regexes"][0] for leg in route_legs],
        )
        self.assertEqual(4, disruption["checkpoint_expected_group_count"])
        self.assertEqual(1272, disruption["checkpoint_expected_session_count"])
        self.assertEqual(
            {"ebgp": 2, "ibgp": 2},
            disruption["checkpoint_group_counts_by_role"],
        )
        self.assertNotIn("expected_ingress_policy_by_role", disruption)
        self.assertEqual(4, len(_runtime_route_specs(config)))
        self.assertFalse(
            any(
                "BGP-MON" in json.dumps(_setup_task_params(task), sort_keys=True)
                for task in config.setup_tasks or []
                if task.params is not None and task.params.json_params is not None
            )
        )
        self.assertEqual([], _hardware_capacity_checks(config.playbooks[0].prechecks))
        self.assertEqual([], _hardware_capacity_checks(config.playbooks[0].postchecks))

    def test_cold_start_owns_exact_bag012_zero_to_formation_trigger(self) -> None:
        config = factory.create_bgp_ebb_full_scale_test_config(
            BAG012_ASH6,
            name="BAG012_UG_2_7_5_TEST",
            playbooks_selected=["bgp_ug_cold_start"],
        )

        playbook = config.playbooks[0]
        self.assertEqual("bgp_ug_cold_start", playbook.name)
        disable = json.loads(_json_params(playbook.stages[0].steps[-1])["args_json"])
        cold_zero_steps = playbook.stages[1].steps
        zero = _json_params(cold_zero_steps[3])
        tracks = none_throws(playbook.stages[2].concurrent_steps)
        wire_start = _json_params(tracks[1].steps[1])
        t0 = _json_params(tracks[1].steps[2])
        enable = json.loads(_json_params(tracks[1].steps[3])["args_json"])
        quiet_rebaseline = _json_params(playbook.stages[4].steps[-1])
        self.assertFalse(disable["enable"])
        self.assertEqual(18, disable["expected_match_count"])
        self.assertEqual("verify_zero", zero["action"])
        self.assertEqual(1272, zero["expected_configured_session_count"])
        self.assertEqual("record_jq_timestamp", t0["custom_step_name"])
        self.assertEqual("bgp_cold_start_formation_t0", t0["var_name"])
        self.assertTrue(enable["enable"])
        self.assertEqual(18, enable["expected_match_count"])
        self.assertEqual(
            ["Ethernet3/36/1", "Ethernet3/36/2"],
            wire_start["capture_interfaces"],
        )
        wire_sources = wire_start["dut_source_addresses"]
        self.assertEqual(1272, len(wire_sources))
        self.assertEqual(1272, len(set(wire_sources)))
        self.assertEqual(636, sum(":" not in address for address in wire_sources))
        self.assertEqual(636, sum(":" in address for address in wire_sources))
        self.assertEqual(
            ["Ethernet3/36/2"],
            quiet_rebaseline["runtime_update_interfaces"],
        )
        validation = playbook.stages[3]
        self.assertEqual("checkpoint", _json_params(validation.steps[3])["action"])
        self.assertEqual("compare", _json_params(validation.steps[6])["action"])
        self.assertEqual(0, _json_params(validation.steps[7])["min_delta"])
        self.assertEqual(2, len(config.basic_port_configs or []))
        self.assertEqual(18, len(_device_groups(config)))

    def test_cold_start_rejects_duplicate_ixia_device_group_names(self) -> None:
        names = [f"group-{index}" for index in range(18)]
        names[-1] = names[0]
        bound = SimpleNamespace(
            device_groups=[
                SimpleNamespace(legacy_ixia_device_group_name=name) for name in names
            ]
        )

        with self.assertRaisesRegex(ValueError, "18 unique named IXIA"):
            suite._validated_device_group_names(t.cast(t.Any, bound))

    def test_full_suite_orders_cold_start_last_on_one_two_port_topology(self) -> None:
        expected_order = [
            "bgp_ug_link_flap_recovery",
            "bgp_ug_bgp_daemon_restart",
            "bgp_ug_fibagent_restart",
            "update_group_sustained_link_flap",
            "bgp_ug_cold_start",
        ]
        config = factory.create_bgp_ebb_full_scale_test_config(
            BAG012_ASH6,
            name="BAG012_UG_2_7_FULL_SUITE_TEST",
            playbooks_selected=expected_order,
        )

        self.assertEqual(
            expected_order, [playbook.name for playbook in config.playbooks]
        )
        self.assertEqual(2, len(config.basic_port_configs or []))
        self.assertEqual(18, len(_device_groups(config)))
        self.assertEqual(4, len(_runtime_route_specs(config)))
