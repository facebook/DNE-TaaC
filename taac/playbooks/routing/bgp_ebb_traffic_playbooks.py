# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

from __future__ import annotations

import json
import re

from taac.health_checks.healthcheck_definitions import (
    create_ixia_packet_loss_check,
    create_ixia_traffic_rate_check,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_ixia_api_step,
    create_ixia_device_group_toggle_step,
    create_longevity_step,
    create_validation_step,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types


_EXPECTED_RECOVERED_RESOURCE_MNEMONICS = (
    "FEC_RESOURCE",
    "ROUTING_MPLS_TUNNEL_RESOURCE",
)
_STORM_PACKET_LOSS_THRESHOLD_PERCENT = "0.1"


def _traffic_liveness_check(
    traffic_item_names: tuple[str, ...],
) -> taac_types.PointInTimeHealthCheck:
    return create_ixia_traffic_rate_check(
        thresholds=[
            hc_types.TrafficRateThreshold(
                names=list(traffic_item_names),
                value=0,
                threshold_type=hc_types.ThresholdType.ABSOLUTE,
                metric=hc_types.TrafficRateMetric.TX_RATE,
            )
        ]
    )


def _packet_loss_check(
    traffic_item_names: tuple[str, ...],
    *,
    check_id: str,
    metric: hc_types.PacketLossMetric = hc_types.PacketLossMetric.FRAME_DELTA,
    threshold: str = "0",
) -> taac_types.PointInTimeHealthCheck:
    return create_ixia_packet_loss_check(
        thresholds=[
            hc_types.PacketLossThreshold(
                names=list(traffic_item_names),
                str_value=threshold,
                metric=metric,
                comparison=hc_types.ComparisonType.LESS_THAN_EQUAL_TO,
                expect_packet_loss=False,
            )
        ],
        clear_traffic_stats=False,
        check_id=check_id,
    )


def _traffic_item_regex(traffic_item_names: tuple[str, ...]) -> str:
    return "^(?:" + "|".join(re.escape(name) for name in traffic_item_names) + ")$"


def _defer_traffic_start(step: taac_types.Step) -> taac_types.Step:
    params = step.step_params
    json_params = json.loads(params.json_params or "{}") if params else {}
    json_params["skip_start_traffic"] = True
    return step(
        step_params=(
            params(json_params=json.dumps(json_params))
            if params is not None
            else taac_types.Params(json_params=json.dumps(json_params))
        )
    )


def _defer_storm_control_plane_invariant_failures(
    stages: tuple[taac_types.Stage, ...],
) -> list[taac_types.Stage]:
    copied_stages: list[taac_types.Stage] = []
    storm_step_count = 0
    for stage in stages:
        copied_steps: list[taac_types.Step] = []
        stage_changed = False
        for step in stage.steps or []:
            params = step.step_params
            json_params = json.loads(params.json_params or "{}") if params else {}
            if json_params.get("custom_step_name") == "bgp_nhg_random_storm":
                json_params["defer_control_plane_invariant_failures"] = True
                step = step(
                    step_params=(
                        params(json_params=json.dumps(json_params))
                        if params is not None
                        else taac_types.Params(json_params=json.dumps(json_params))
                    )
                )
                storm_step_count += 1
                stage_changed = True
            copied_steps.append(step)
        copied_stages.append(stage(steps=copied_steps) if stage_changed else stage)
    if storm_step_count != 1:
        raise ValueError("EBB16 traffic requires exactly one BGP NHG random-storm step")
    return copied_stages


def _allow_expected_recovered_resource_logs(
    check: taac_types.PointInTimeHealthCheck,
) -> taac_types.PointInTimeHealthCheck:
    if check.check_id != "bgp_time_bound_check" or check.check_params is None:
        return check
    params = check.check_params
    json_params = json.loads(params.json_params or "{}")
    if not json_params.get("check_system_logs"):
        return check
    json_params["allowed_recovered_resource_mnemonics"] = list(
        _EXPECTED_RECOVERED_RESOURCE_MNEMONICS
    )
    return check(check_params=params(json_params=json.dumps(json_params)))


def get_bgp_ebb_nexthop_group_count_threshold_traffic_playbook(
    control_plane_playbook: taac_types.Playbook,
    *,
    traffic_item_names: tuple[str, ...],
    stable_state_duration_seconds: int = 30,
) -> taac_types.Playbook:
    """Copy EBB16 and add bounded pre-storm and end-to-end traffic windows."""
    if (
        len(traffic_item_names) != 2
        or len(set(traffic_item_names)) != 2
        or any(not name for name in traffic_item_names)
    ):
        raise ValueError("EBB16 traffic requires two distinct traffic item names")
    if stable_state_duration_seconds <= 0:
        raise ValueError("EBB16 stable-state traffic duration must be positive")
    if control_plane_playbook.name != (
        "bgp_ebb_nexthop_group_count_threshold_playbook"
    ):
        raise ValueError("EBB16 traffic requires the Phase 1 control-plane playbook")
    traffic_storm_stages = _defer_storm_control_plane_invariant_failures(
        tuple(control_plane_playbook.stages or [])
    )
    stable_loss_check = _packet_loss_check(
        traffic_item_names,
        check_id="ebb16_stable_state_packet_loss",
    )
    final_loss_check = _packet_loss_check(
        traffic_item_names,
        check_id="ebb16_storm_window_packet_loss",
        metric=hc_types.PacketLossMetric.PERCENTAGE,
        threshold=_STORM_PACKET_LOSS_THRESHOLD_PERCENT,
    )
    traffic_regex = _traffic_item_regex(traffic_item_names)
    control_plane_prechecks = list(control_plane_playbook.prechecks or [])
    control_plane_precheck_stage = create_steps_stage(
        stage_id="ebb16_control_plane_prechecks",
        description="Validate the EBB16 control-plane baseline before traffic",
        steps=[
            create_validation_step(
                point_in_time_checks=control_plane_prechecks,
                stage=taac_types.ValidationStage.PRE_TEST,
                description="Validate the EBB16 control-plane baseline",
                start_traffic=False,
                fail_on_failure=True,
            )
        ],
    )
    stable_state_stage = create_steps_stage(
        stage_id="ebb16_traffic_stable_state",
        description="Prove both EBB16 traffic items are lossless before churn",
        steps=[
            create_ixia_api_step(
                api_name="start_traffic",
                args_dict={},
                description="Start EBB16 traffic after control-plane convergence",
                start_traffic=False,
            ),
            create_ixia_api_step(
                api_name="clear_traffic_stats",
                args_dict={"wait_for_refresh": True},
                description="Start a clean EBB16 stable-state traffic window",
                start_traffic=False,
            ),
            create_longevity_step(
                duration=stable_state_duration_seconds,
                description="Hold EBB16 traffic in stable state",
                start_traffic=False,
            ),
            create_validation_step(
                point_in_time_checks=[_traffic_liveness_check(traffic_item_names)],
                description="Verify both EBB16 traffic items are transmitting",
                start_traffic=False,
                fail_on_failure=True,
            ),
            create_validation_step(
                point_in_time_checks=[stable_loss_check],
                description="Verify the EBB16 stable-state window is lossless",
                start_traffic=False,
                fail_on_failure=True,
            ),
            create_ixia_api_step(
                api_name="start_traffic_items",
                args_dict={"traffic_item_regex": traffic_regex},
                description="Restart EBB16 traffic after the baseline loss check",
                start_traffic=False,
            ),
            create_ixia_api_step(
                api_name="clear_traffic_stats",
                args_dict={"wait_for_refresh": True},
                description="Start the EBB16 storm packet-loss window",
                start_traffic=False,
            ),
        ],
    )
    final_liveness_stage = create_steps_stage(
        stage_id="ebb16_traffic_final_liveness",
        description="Confirm both EBB16 traffic items are live after restoration",
        steps=[
            create_validation_step(
                point_in_time_checks=[_traffic_liveness_check(traffic_item_names)],
                description="Verify post-storm EBB16 traffic is transmitting",
                start_traffic=False,
                fail_on_failure=True,
            )
        ],
    )
    return control_plane_playbook(
        name="bgp_ebb_nexthop_group_count_threshold_traffic_playbook",
        setup_steps=[
            _defer_traffic_start(
                create_ixia_device_group_toggle_step(
                    enable=False,
                    device_group_name_regex=".*",
                    description=(
                        "Reset all IXIA device groups before EBB16 convergence"
                    ),
                    require_match=True,
                    verify_readback=True,
                )
            ),
            *(
                _defer_traffic_start(step)
                for step in (control_plane_playbook.setup_steps or [])
            ),
        ],
        stages=[
            control_plane_precheck_stage,
            stable_state_stage,
            *traffic_storm_stages,
            final_liveness_stage,
        ],
        prechecks=[],
        postchecks=[
            _allow_expected_recovered_resource_logs(check)
            for check in (control_plane_playbook.postchecks or [])
        ],
        cleanup_steps=[
            # The runner folds this recorded MID_TEST failure into the final
            # verdict. Keep it non-raising so restoration and traffic stop run.
            create_validation_step(
                point_in_time_checks=[final_loss_check],
                stage=taac_types.ValidationStage.MID_TEST,
                description=(
                    "Capture EBB16 storm packet loss even when the workload fails"
                ),
                start_traffic=False,
                fail_on_failure=False,
            ),
            *(control_plane_playbook.cleanup_steps or []),
            create_ixia_api_step(
                api_name="stop_traffic",
                args_dict={},
                description="Stop EBB16 continuity traffic during cleanup",
                start_traffic=False,
            ),
        ],
        traffic_items_to_start=list(traffic_item_names),
    )
