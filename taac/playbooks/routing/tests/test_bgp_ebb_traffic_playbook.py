# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

import json
import unittest

from taac.playbooks.routing.bgp_ebb_playbooks import (
    get_bgp_ebb_nexthop_group_count_threshold_playbook,
)
from taac.playbooks.routing.bgp_ebb_traffic_playbooks import (
    get_bgp_ebb_nexthop_group_count_threshold_traffic_playbook,
)
from taac.utils.json_thrift_utils import json_to_thrift
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types


_TRAFFIC_ITEMS = (
    "EBB16_IPV4_PREFIX_CONTINUITY",
    "EBB16_IPV6_PREFIX_CONTINUITY",
)
_IXIA_ITEMS_BY_AFI = {
    afi: {
        "logical_device_group": f"dg_ebgp_{suffix}",
        "logical_route_advertisement": f"dg_ebgp_{suffix}_routes",
        "device_group_item": f"DEVICE_GROUP_{afi.upper()}_EBGP",
        "peer_item": f"BGP_PEER_{afi.upper()}_EBGP",
        "route_item": f"PREFIX_POOL_{afi.upper()}_EBGP",
        "expected_peer_count": 140,
        "expected_routes_per_peer": 750,
        "target_prefix_count": 750,
    }
    for afi, suffix in (("ipv4", "v4"), ("ipv6", "v6"))
}


def _control_plane_playbook() -> taac_types.Playbook:
    return get_bgp_ebb_nexthop_group_count_threshold_playbook(
        device_name="dut.example.com",
        expected_established_sessions=1272,
        route_count_expected=750,
        ixia_items_by_afi=_IXIA_ITEMS_BY_AFI,
        epoch_count=2,
        epoch_interval_seconds=1,
        soak_duration=1,
    )


def _api_name(step: taac_types.Step) -> str | None:
    if step.step_params is None or step.step_params.json_params is None:
        return None
    return json.loads(step.step_params.json_params).get("api_name")


def _step_params(step: taac_types.Step) -> dict[str, object]:
    if step.step_params is None or step.step_params.json_params is None:
        return {}
    return json.loads(step.step_params.json_params)


def _storm_params(playbook: taac_types.Playbook) -> dict[str, object]:
    matches = [
        params
        for stage in playbook.stages or []
        for step in stage.steps or []
        if (params := _step_params(step)).get("custom_step_name")
        == "bgp_nhg_random_storm"
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected one NHG storm step, found {len(matches)}")
    return matches[0]


def _validation_input(step: taac_types.Step) -> taac_types.ValidationInput:
    if step.input_json is None:
        raise AssertionError("validation step has no typed input")
    return json_to_thrift(step.input_json, taac_types.ValidationInput)


class BgpEbbTrafficPlaybookTest(unittest.TestCase):
    def test_phase1_playbook_is_copied_without_mutation(self) -> None:
        control_plane = _control_plane_playbook()
        expected_control_plane = _control_plane_playbook()
        traffic = get_bgp_ebb_nexthop_group_count_threshold_traffic_playbook(
            control_plane,
            traffic_item_names=_TRAFFIC_ITEMS,
        )

        self.assertEqual(expected_control_plane, control_plane)
        self.assertEqual(
            "bgp_ebb_nexthop_group_count_threshold_playbook",
            control_plane.name,
        )
        self.assertIsNone(control_plane.traffic_items_to_start)
        self.assertEqual(
            "bgp_ebb_nexthop_group_count_threshold_traffic_playbook",
            traffic.name,
        )
        self.assertEqual(
            list(_TRAFFIC_ITEMS),
            list(traffic.traffic_items_to_start or []),
        )
        traffic_setup = list(traffic.setup_steps or [])
        self.assertEqual("toggle_device_groups", _api_name(traffic_setup[0]))
        toggle_args_json = _step_params(traffic_setup[0]).get("args_json")
        if not isinstance(toggle_args_json, str):
            self.fail("IXIA device-group toggle has no serialized arguments")
        self.assertFalse(json.loads(toggle_args_json)["enable"])
        self.assertEqual(
            [step.name for step in control_plane.setup_steps or []],
            [step.name for step in traffic_setup[1:]],
        )
        self.assertTrue(
            all(_step_params(step).get("skip_start_traffic") for step in traffic_setup)
        )
        self.assertTrue(
            all(
                not _step_params(step).get("skip_start_traffic", False)
                for step in control_plane.setup_steps or []
            )
        )
        self.assertEqual([], list(traffic.prechecks or []))
        stages = list(traffic.stages or [])
        self.assertEqual("ebb16_control_plane_prechecks", stages[0].id)
        precheck_step = list(stages[0].steps or [])[0]
        self.assertEqual(
            list(control_plane.prechecks or []),
            list(_validation_input(precheck_step).point_in_time_checks),
        )
        self.assertTrue(_step_params(precheck_step)["skip_start_traffic"])
        self.assertTrue(_step_params(precheck_step)["fail_on_failure"])
        self.assertEqual(control_plane.snapshot_checks, traffic.snapshot_checks)
        self.assertEqual(control_plane.periodic_tasks, traffic.periodic_tasks)
        control_storm = _storm_params(control_plane)
        traffic_storm = _storm_params(traffic)
        self.assertNotIn(
            "defer_control_plane_invariant_failures",
            control_storm,
        )
        self.assertEqual(
            {**control_storm, "defer_control_plane_invariant_failures": True},
            traffic_storm,
        )

        original_system_log_check = next(
            check
            for check in control_plane.postchecks or []
            if check.check_id == "bgp_time_bound_check"
        )
        traffic_system_log_check = next(
            check
            for check in traffic.postchecks or []
            if check.check_id == "bgp_time_bound_check"
        )
        original_check_params = original_system_log_check.check_params
        traffic_check_params = traffic_system_log_check.check_params
        if original_check_params is None or traffic_check_params is None:
            self.fail("EBB16 system-log checks have no parameters")
        self.assertNotIn(
            "allowed_recovered_resource_mnemonics",
            json.loads(original_check_params.json_params or "{}"),
        )
        self.assertEqual(
            ["FEC_RESOURCE", "ROUTING_MPLS_TUNNEL_RESOURCE"],
            json.loads(traffic_check_params.json_params or "{}")[
                "allowed_recovered_resource_mnemonics"
            ],
        )

    def test_stable_and_storm_measurement_windows_are_ordered(self) -> None:
        control_plane = _control_plane_playbook()
        traffic = get_bgp_ebb_nexthop_group_count_threshold_traffic_playbook(
            control_plane,
            traffic_item_names=_TRAFFIC_ITEMS,
        )
        stages = list(traffic.stages or [])

        self.assertEqual("ebb16_control_plane_prechecks", stages[0].id)
        self.assertEqual("ebb16_traffic_stable_state", stages[1].id)
        self.assertEqual(
            [stage.id for stage in control_plane.stages or []],
            [stage.id for stage in stages[2:-1]],
        )
        self.assertEqual("ebb16_traffic_final_liveness", stages[-1].id)
        final_liveness_step = list(stages[-1].steps or [])[0]
        self.assertTrue(_step_params(final_liveness_step)["fail_on_failure"])
        baseline_steps = list(stages[1].steps or [])
        self.assertEqual("start_traffic", _api_name(baseline_steps[0]))
        self.assertEqual("clear_traffic_stats", _api_name(baseline_steps[1]))
        self.assertEqual("start_traffic_items", _api_name(baseline_steps[-2]))
        self.assertEqual("clear_traffic_stats", _api_name(baseline_steps[-1]))
        self.assertEqual(
            [hc_types.CheckName.IXIA_TRAFFIC_RATE_CHECK],
            [
                check.name
                for check in _validation_input(baseline_steps[3]).point_in_time_checks
            ],
        )
        self.assertEqual(
            [hc_types.CheckName.IXIA_PACKET_LOSS_CHECK],
            [
                check.name
                for check in _validation_input(baseline_steps[4]).point_in_time_checks
            ],
        )
        stable_loss_check = _validation_input(baseline_steps[4]).point_in_time_checks[0]
        if stable_loss_check.input_json is None:
            self.fail("EBB16 stable-state loss check has no typed input")
        stable_loss_input = json_to_thrift(
            stable_loss_check.input_json,
            hc_types.IxiaPacketLossHealthCheckIn,
        )
        self.assertEqual(
            hc_types.PacketLossMetric.FRAME_DELTA,
            stable_loss_input.thresholds[0].metric,
        )
        self.assertEqual("0", stable_loss_input.thresholds[0].str_value)
        self.assertTrue(_step_params(baseline_steps[3])["fail_on_failure"])
        self.assertTrue(_step_params(baseline_steps[4])["fail_on_failure"])

    def test_cleanup_always_captures_loss_before_stopping_traffic(self) -> None:
        control_plane = _control_plane_playbook()
        traffic = get_bgp_ebb_nexthop_group_count_threshold_traffic_playbook(
            control_plane,
            traffic_item_names=_TRAFFIC_ITEMS,
        )
        cleanup_steps = list(traffic.cleanup_steps or [])
        loss_step = cleanup_steps[0]
        loss_validation = _validation_input(loss_step)
        loss_check = loss_validation.point_in_time_checks[0]
        if loss_check.input_json is None:
            self.fail("EBB16 traffic loss cleanup check has no typed input")
        loss_input = json_to_thrift(
            loss_check.input_json,
            hc_types.IxiaPacketLossHealthCheckIn,
        )

        self.assertEqual(
            [check.name for check in control_plane.postchecks or []],
            [check.name for check in traffic.postchecks or []],
        )
        self.assertEqual(taac_types.ValidationStage.MID_TEST, loss_validation.stage)
        self.assertFalse(_step_params(loss_step).get("fail_on_failure", False))
        self.assertEqual("ebb16_storm_window_packet_loss", loss_check.check_id)
        self.assertEqual(
            list(_TRAFFIC_ITEMS),
            list(loss_input.thresholds[0].names or []),
        )
        self.assertEqual(
            hc_types.PacketLossMetric.PERCENTAGE,
            loss_input.thresholds[0].metric,
        )
        self.assertEqual("0.1", loss_input.thresholds[0].str_value)
        self.assertFalse(loss_input.clear_traffic_stats)
        self.assertEqual("stop_traffic", _api_name(cleanup_steps[-1]))
