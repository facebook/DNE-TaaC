# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Structural tests for frontend QoS scheduling playbooks."""

import json
import re
import typing as t
import unittest

from taac.testconfigs.fboss_solution_tests.qos_scheduling_fsw001_p005_f01_qzd1_test_config import (
    QOS_SCHEDULING_FSW001_P005_F01_QZD1_TEST_CONFIG,
)
from taac.utils.json_thrift_utils import json_to_thrift
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types


_PLAYBOOK_NAME = "test_qos_single_congestion_queue2_silver"
_AUXILIARY_SUFFIXES = (
    "GOOD_BUT_LOSSY_NDP_TRAFFIC",
    "LOSSY_ROGUE_NDP_TRAFFIC",
    "HIGH_QUEUE_BGP_CP_TRAFFIC",
)
_EXPECTED_RESTARTS = {
    "wedge_agent",
    "bgpd",
    "fboss_sw_agent",
    "fboss_hw_agent@0",
    "openr",
}
_MIB = 1024 * 1024
_BURST_PACKET_COUNTS_100G_30MS = {33: 33118, 34: 34121}
_SCHEDULING_PREFIX = "test_qos_scheduling_"
_PER_QUEUE_CONGESTION_PREFIX = "test_qos_per_queue_congestion_"
_PAIR_CONGESTION_PREFIX = "test_qos_congestion_"
_SINGLE_CONGESTION_PREFIX = "test_qos_single_congestion_"
_MULTI_CONGESTION_PREFIX = "test_qos_multi_congestion_"
_BASELINE_TRAFFIC_SUFFIXES = (
    "V6_LAYER3_TRAFFIC_DOWNLINK_AND_UPLINK",
    "V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
    "V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
)


def _playbook() -> taac_types.Playbook:
    return next(
        playbook
        for playbook in QOS_SCHEDULING_FSW001_P005_F01_QZD1_TEST_CONFIG.playbooks
        if playbook.name == _PLAYBOOK_NAME
    )


def _api_name(step: taac_types.Step) -> str | None:
    if step.name != taac_types.StepName.INVOKE_IXIA_API_STEP or not step.step_params:
        return None
    return json.loads(step.step_params.json_params or "{}").get("api_name")


def _validation_input(step: taac_types.Step) -> taac_types.ValidationInput:
    input_json = step.input_json
    assert input_json is not None
    return json_to_thrift(input_json, taac_types.ValidationInput)


def _traffic_items(
    playbook: taac_types.Playbook,
) -> t.Mapping[str, taac_types.TrafficItemSettings]:
    items = playbook.traffic_items_to_configure
    assert items is not None
    return items


def _step_params_json(step: taac_types.Step) -> str:
    params = step.step_params
    assert params is not None
    return params.json_params or "{}"


def _check_input_json(check: taac_types.PointInTimeHealthCheck) -> str:
    input_json = check.input_json
    assert input_json is not None
    return input_json


def _check_params_json(check: taac_types.PointInTimeHealthCheck) -> str:
    params = check.check_params
    assert params is not None
    return params.json_params or "{}"


def _list_value(mapping: dict[str, object], key: str) -> list[t.Any]:
    return t.cast(list[t.Any], mapping.get(key, []))


def _playbooks_with_prefix(prefix: str) -> list[taac_types.Playbook]:
    return [
        playbook
        for playbook in QOS_SCHEDULING_FSW001_P005_F01_QZD1_TEST_CONFIG.playbooks
        if playbook.name.startswith(prefix)
    ]


def _ixia_api_args(
    steps: list[taac_types.Step], api_name: str
) -> list[dict[str, object]]:
    args = []
    for step in steps:
        if _api_name(step) != api_name or not step.step_params:
            continue
        payload = json.loads(step.step_params.json_params or "{}")
        args.append(json.loads(payload.get("args_json") or "{}"))
    return args


def _playbook_ixia_api_args(
    playbook: taac_types.Playbook, api_name: str
) -> list[dict[str, object]]:
    return [
        args
        for stage in playbook.stages or []
        for args in _ixia_api_args(list(stage.steps or []), api_name)
    ]


def _cleanup_ixia_api_args(
    playbook: taac_types.Playbook, api_name: str
) -> list[dict[str, object]]:
    return _ixia_api_args(list(playbook.cleanup_steps or []), api_name)


def _snapshot_payloads(
    playbook: taac_types.Playbook, check_name: hc_types.CheckName
) -> list[tuple[taac_types.SnapshotHealthCheck, dict[str, object]]]:
    return [
        (check, json.loads(check.input_json or "{}"))
        for check in playbook.snapshot_checks or []
        if check.name == check_name
    ]


def _baseline_and_congestion_names(
    playbook: taac_types.Playbook,
) -> tuple[set[str], set[str]]:
    configured = set(playbook.traffic_items_to_configure or {})
    baseline = {
        name
        for name in configured
        if any(name.endswith(suffix) for suffix in _BASELINE_TRAFFIC_SUFFIXES)
    }
    return baseline, configured - baseline


def _selective_start_positions(
    stage: taac_types.Stage, traffic_names: set[str]
) -> dict[str, int]:
    positions = {}
    for index, step in enumerate(stage.steps or []):
        args = _ixia_api_args([step], "start_traffic_items")
        if not args:
            continue
        pattern = re.compile(str(args[0].get("traffic_item_regex", "")))
        for name in traffic_names:
            if pattern.search(name):
                positions.setdefault(name, index)
    return positions


class QosSchedulingBuilderTest(unittest.TestCase):
    def test_auxiliary_hardening_traffic_is_absent(self) -> None:
        names = {
            item.name
            for item in QOS_SCHEDULING_FSW001_P005_F01_QZD1_TEST_CONFIG.basic_traffic_item_configs
            or []
            if item.name is not None
        }
        for suffix in _AUXILIARY_SUFFIXES:
            self.assertFalse(
                any(name.endswith(suffix) for name in names),
                f"QoS config unexpectedly contains auxiliary traffic {suffix}",
            )

    def test_fqsb097_preserves_ipv4_baseline_traffic(self) -> None:
        names = set(_traffic_items(_playbook()))
        self.assertTrue(
            any(
                name.endswith("V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK")
                for name in names
            )
        )

    def test_fqsb097_has_no_inherited_ixia_checks(self) -> None:
        playbook = _playbook()
        self.assertNotIn(
            hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
            [check.name for check in playbook.prechecks or []],
        )
        self.assertNotIn(
            hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
            [check.name for check in playbook.postchecks or []],
        )

    def test_fqsb097_stops_traffic_before_each_phase_validation(self) -> None:
        playbook = _playbook()
        self.assertEqual(3, len(playbook.stages))
        for stage in playbook.stages:
            steps = list(stage.steps or [])
            with self.subTest(stage=stage.id):
                self.assertGreaterEqual(len(steps), 2)
                self.assertEqual("stop_traffic", _api_name(steps[-2]))
                self.assertEqual(taac_types.StepName.VALIDATION_STEP, steps[-1].name)
                params = json.loads(_step_params_json(steps[-1]))
                self.assertTrue(params.get("skip_start_traffic"))

                validation = _validation_input(steps[-1])
                self.assertEqual(1, len(validation.point_in_time_checks))
                self.assertEqual(
                    hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
                    validation.point_in_time_checks[0].name,
                )

    def test_fqsb097_warmboot_loss_window_includes_restart(self) -> None:
        stage = next(
            stage for stage in _playbook().stages if "warmboot" in (stage.id or "")
        )
        steps = list(stage.steps or [])
        clear_indexes = [
            index
            for index, step in enumerate(steps)
            if _api_name(step) == "clear_traffic_stats"
        ]
        restart_index = next(
            index
            for index, step in enumerate(steps)
            if step.name == taac_types.StepName.SERVICE_INTERRUPTION_STEP
        )
        validation_index = next(
            index
            for index, step in enumerate(steps)
            if step.name == taac_types.StepName.VALIDATION_STEP
        )

        self.assertEqual(1, len(clear_indexes))
        self.assertLess(clear_indexes[0], restart_index)
        self.assertFalse(
            any(restart_index < index < validation_index for index in clear_indexes)
        )

    def test_fqsb097_reverse_loss_window_includes_start_order(self) -> None:
        stage = next(
            stage for stage in _playbook().stages if "reverse" in (stage.id or "")
        )
        steps = list(stage.steps or [])
        clear_indexes = [
            index
            for index, step in enumerate(steps)
            if _api_name(step) == "clear_traffic_stats"
        ]
        start_indexes = [
            index
            for index, step in enumerate(steps)
            if _api_name(step) in {"start_traffic", "start_traffic_items"}
        ]

        self.assertEqual(1, len(clear_indexes))
        self.assertTrue(start_indexes)
        self.assertLess(clear_indexes[0], start_indexes[0])

    def test_fqsb097_protected_flows_require_exact_zero_duration(self) -> None:
        for stage in _playbook().stages:
            validation_step = next(
                step
                for step in stage.steps or []
                if step.name == taac_types.StepName.VALIDATION_STEP
            )
            check = _validation_input(validation_step).point_in_time_checks[0]
            input_value = json_to_thrift(
                _check_input_json(check),
                hc_types.IxiaPacketLossHealthCheckIn,
            )
            no_loss = next(
                threshold
                for threshold in input_value.thresholds
                if not threshold.expect_packet_loss
            )
            with self.subTest(stage=stage.id):
                self.assertEqual("0", no_loss.str_value)
                self.assertEqual(hc_types.PacketLossMetric.DURATION, no_loss.metric)
                self.assertEqual(
                    hc_types.ComparisonType.EQUAL_TO,
                    no_loss.comparison,
                )
                self.assertTrue(
                    any(
                        name.endswith(
                            "V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK"
                        )
                        for name in no_loss.names or []
                    )
                )

    def test_fqsb097_allows_only_expected_warmboot_restarts(self) -> None:
        restart_check = next(
            check
            for check in _playbook().postchecks or []
            if check.name == hc_types.CheckName.SERVICE_RESTART_CHECK
        )
        params = json.loads(_check_params_json(restart_check))
        self.assertEqual(
            _EXPECTED_RESTARTS,
            set(params.get("expected_restarted_services", [])),
        )

    def test_every_qos_phase_stops_traffic_before_validation(self) -> None:
        for playbook in QOS_SCHEDULING_FSW001_P005_F01_QZD1_TEST_CONFIG.playbooks:
            with self.subTest(playbook=playbook.name):
                self.assertNotIn(
                    hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
                    [check.name for check in playbook.prechecks or []],
                )
                self.assertNotIn(
                    hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
                    [check.name for check in playbook.postchecks or []],
                )
            for stage in playbook.stages or []:
                steps = list(stage.steps or [])
                with self.subTest(playbook=playbook.name, stage=stage.id):
                    self.assertEqual("stop_traffic", _api_name(steps[-2]))
                    self.assertEqual(
                        taac_types.StepName.VALIDATION_STEP,
                        steps[-1].name,
                    )
                    params = json.loads(_step_params_json(steps[-1]))
                    self.assertTrue(params.get("skip_start_traffic"))

    def test_every_warmboot_window_includes_the_restart(self) -> None:
        for playbook in QOS_SCHEDULING_FSW001_P005_F01_QZD1_TEST_CONFIG.playbooks:
            for stage in playbook.stages or []:
                if "warmboot" not in (stage.id or ""):
                    continue
                steps = list(stage.steps or [])
                clear_indexes = [
                    index
                    for index, step in enumerate(steps)
                    if _api_name(step) == "clear_traffic_stats"
                ]
                restart_index = next(
                    index
                    for index, step in enumerate(steps)
                    if step.name == taac_types.StepName.SERVICE_INTERRUPTION_STEP
                )
                with self.subTest(playbook=playbook.name, stage=stage.id):
                    self.assertEqual(1, len(clear_indexes))
                    self.assertLess(clear_indexes[0], restart_index)

    def test_every_reverse_window_includes_start_order(self) -> None:
        for playbook in QOS_SCHEDULING_FSW001_P005_F01_QZD1_TEST_CONFIG.playbooks:
            for stage in playbook.stages or []:
                if "reverse" not in (stage.id or ""):
                    continue
                steps = list(stage.steps or [])
                clear_indexes = [
                    index
                    for index, step in enumerate(steps)
                    if _api_name(step) == "clear_traffic_stats"
                ]
                start_indexes = [
                    index
                    for index, step in enumerate(steps)
                    if _api_name(step) in {"start_traffic", "start_traffic_items"}
                ]
                with self.subTest(playbook=playbook.name, stage=stage.id):
                    self.assertEqual(1, len(clear_indexes))
                    self.assertLess(clear_indexes[0], start_indexes[0])

    def test_single_congestion_initial_window_clears_before_start_order(self) -> None:
        playbooks = _playbooks_with_prefix(_SINGLE_CONGESTION_PREFIX)
        self.assertEqual(4, len(playbooks))
        for playbook in playbooks:
            stage = next(
                stage
                for stage in playbook.stages or []
                if stage.id == "qos_single_congestion_traffic"
            )
            steps = list(stage.steps or [])
            clear_indexes = [
                index
                for index, step in enumerate(steps)
                if _api_name(step) == "clear_traffic_stats"
            ]
            start_indexes = [
                index
                for index, step in enumerate(steps)
                if _api_name(step) in {"start_traffic", "start_traffic_items"}
            ]
            with self.subTest(playbook=playbook.name):
                self.assertEqual(1, len(clear_indexes))
                self.assertLess(clear_indexes[0], min(start_indexes))


class QosCatalogBehaviorTest(unittest.TestCase):
    def test_queue_snapshot_checks_use_monotonic_counters(self) -> None:
        for playbook in QOS_SCHEDULING_FSW001_P005_F01_QZD1_TEST_CONFIG.playbooks:
            for _, payload in _snapshot_payloads(
                playbook, hc_types.CheckName.QOS_DSCP_TX_QUEUE_CHECK
            ):
                queue_info = t.cast(
                    list[dict[str, object]], payload.get("tx_queue_info_list", [])
                )
                for info in queue_info:
                    with self.subTest(playbook=playbook.name, info=info):
                        self.assertEqual("out_bytes.sum", info.get("key_desc"))

    def test_selective_start_settle_steps_do_not_start_all_traffic(self) -> None:
        playbooks = (
            _playbooks_with_prefix(_PER_QUEUE_CONGESTION_PREFIX)
            + _playbooks_with_prefix(_SINGLE_CONGESTION_PREFIX)
            + _playbooks_with_prefix(_MULTI_CONGESTION_PREFIX)
        )
        self.assertEqual(16, len(playbooks))
        settle_steps = []
        for playbook in playbooks:
            for stage in playbook.stages or []:
                for step in stage.steps or []:
                    if step.name != taac_types.StepName.LONGEVITY_STEP:
                        continue
                    params = json.loads(_step_params_json(step))
                    if (step.id or "").startswith("settle_"):
                        settle_steps.append((playbook.name, stage.id, params))

        self.assertTrue(settle_steps)
        for playbook_name, stage_id, params in settle_steps:
            with self.subTest(playbook=playbook_name, stage=stage_id):
                self.assertTrue(params.get("skip_start_traffic"))

    def test_scheduling_bursts_every_preserved_traffic_item_for_30ms(self) -> None:
        playbooks = _playbooks_with_prefix(_SCHEDULING_PREFIX)
        self.assertEqual(6, len(playbooks))
        for playbook in playbooks:
            traffic_items = _traffic_items(playbook)
            configured = set(traffic_items)
            self.assertEqual(3, len(configured))
            self.assertTrue(
                any(name.endswith(_BASELINE_TRAFFIC_SUFFIXES[2]) for name in configured)
            )
            burst_args = [
                args
                for args in _playbook_ixia_api_args(
                    playbook, "set_transmission_control"
                )
                if args.get("transmission_type") != "continuous"
            ]
            bursted = {
                name
                for args in burst_args
                for name in configured
                if re.search(str(args.get("traffic_item_regex", "")), name)
            }
            with self.subTest(playbook=playbook.name):
                self.assertEqual(configured, bursted)
                for args in burst_args:
                    self.assertEqual("burstFixedDuration", args["transmission_type"])
                    matching_name = next(
                        name
                        for name in configured
                        if re.search(str(args.get("traffic_item_regex", "")), name)
                    )
                    line_rate = traffic_items[matching_name].line_rate
                    assert line_rate is not None
                    self.assertEqual(
                        _BURST_PACKET_COUNTS_100G_30MS[line_rate],
                        args.get("burst_packet_count"),
                    )
                    self.assertEqual(5.0, args.get("inter_burst_gap_ms"))

    def test_scheduling_burst_mode_is_restored_by_cleanup(self) -> None:
        playbooks = _playbooks_with_prefix(_SCHEDULING_PREFIX)
        self.assertEqual(6, len(playbooks))
        for playbook in playbooks:
            configured = set(_traffic_items(playbook))
            restored = {
                name
                for args in _cleanup_ixia_api_args(playbook, "set_transmission_control")
                if args.get("transmission_type") == "continuous"
                for name in configured
                if re.search(str(args.get("traffic_item_regex", "")), name)
            }
            with self.subTest(playbook=playbook.name):
                self.assertEqual(configured, restored)

    def test_ncnf_cases_validate_queue0_and_buffer_utilization(self) -> None:
        names = {
            "test_qos_scheduling_queue0_ncnf",
            "test_qos_per_queue_congestion_queue0_ncnf",
        }
        playbooks = {
            playbook.name: playbook
            for playbook in QOS_SCHEDULING_FSW001_P005_F01_QZD1_TEST_CONFIG.playbooks
            if playbook.name in names
        }
        self.assertEqual(names, set(playbooks))
        for playbook in playbooks.values():
            queue_payloads = _snapshot_payloads(
                playbook, hc_types.CheckName.QOS_DSCP_TX_QUEUE_CHECK
            )
            buffer_payloads = _snapshot_payloads(
                playbook, hc_types.CheckName.BUFFER_UTILIZATION_CHECK
            )
            queue_descs = {
                desc
                for _, payload in queue_payloads
                for info in _list_value(payload, "tx_queue_info_list")
                for desc in _list_value(info, "queue_desc_list")
            }
            active_queue_descs = {
                desc
                for _, payload in buffer_payloads
                for threshold in _list_value(payload, "thresholds")
                for desc in _list_value(threshold, "active_queue_desc_list")
            }
            with self.subTest(playbook=playbook.name):
                self.assertIn("queue0.ncnf", queue_descs)
                self.assertIn("queue0.ncnf", active_queue_descs)

    def test_catalog_continuous_congestion_cases_have_only_one_stage(self) -> None:
        playbooks = _playbooks_with_prefix(
            _PER_QUEUE_CONGESTION_PREFIX
        ) + _playbooks_with_prefix(_PAIR_CONGESTION_PREFIX)
        self.assertEqual(16, len(playbooks))
        for playbook in playbooks:
            with self.subTest(playbook=playbook.name):
                self.assertEqual(1, len(playbook.stages or []))

    def test_per_queue_congestion_has_no_empty_packet_loss_threshold(self) -> None:
        playbooks = _playbooks_with_prefix(_PER_QUEUE_CONGESTION_PREFIX)
        self.assertEqual(6, len(playbooks))
        for playbook in playbooks:
            validation_step = next(
                step
                for stage in playbook.stages or []
                for step in stage.steps or []
                if step.name == taac_types.StepName.VALIDATION_STEP
            )
            check = next(
                check
                for check in _validation_input(validation_step).point_in_time_checks
                if check.name == hc_types.CheckName.IXIA_PACKET_LOSS_CHECK
            )
            input_value = json_to_thrift(
                _check_input_json(check),
                hc_types.IxiaPacketLossHealthCheckIn,
            )
            with self.subTest(playbook=playbook.name):
                self.assertEqual(1, len(input_value.thresholds))
                self.assertTrue(input_value.thresholds[0].names)
                self.assertTrue(input_value.thresholds[0].expect_packet_loss)

    def test_catalog_continuous_congestion_uses_110mb_and_5mb_bounds(self) -> None:
        playbooks = _playbooks_with_prefix(
            _PER_QUEUE_CONGESTION_PREFIX
        ) + _playbooks_with_prefix(_PAIR_CONGESTION_PREFIX)
        self.assertEqual(16, len(playbooks))
        for playbook in playbooks:
            thresholds = [
                threshold
                for _, payload in _snapshot_payloads(
                    playbook, hc_types.CheckName.BUFFER_UTILIZATION_CHECK
                )
                for threshold in _list_value(payload, "thresholds")
            ]
            active_bounds = {
                threshold.get("active_queue_max_bytes") for threshold in thresholds
            }
            other_bounds = {
                threshold.get("other_queue_max_bytes") for threshold in thresholds
            }
            with self.subTest(playbook=playbook.name):
                self.assertIn(110 * _MIB, active_bounds)
                self.assertIn(5 * _MIB, active_bounds | other_bounds)

    def test_non_multi_congestion_playbooks_validate_each_driven_queue(self) -> None:
        playbooks = (
            _playbooks_with_prefix(_PER_QUEUE_CONGESTION_PREFIX)
            + _playbooks_with_prefix(_PAIR_CONGESTION_PREFIX)
            + _playbooks_with_prefix(_SINGLE_CONGESTION_PREFIX)
        )
        self.assertEqual(20, len(playbooks))
        for playbook in playbooks:
            configured_dscps = {
                settings.qos_config.dscp_value
                for settings in _traffic_items(playbook).values()
                if settings.qos_config is not None
            }
            queue_selectors = {
                ("cos", cos)
                for _, payload in _snapshot_payloads(
                    playbook, hc_types.CheckName.QOS_DSCP_TX_QUEUE_CHECK
                )
                for info in _list_value(payload, "tx_queue_info_list")
                for cos in _list_value(info, "cos_list")
            }
            queue_selectors.update(
                ("desc", desc)
                for _, payload in _snapshot_payloads(
                    playbook, hc_types.CheckName.QOS_DSCP_TX_QUEUE_CHECK
                )
                for info in _list_value(payload, "tx_queue_info_list")
                for desc in _list_value(info, "queue_desc_list")
            )
            with self.subTest(playbook=playbook.name):
                self.assertGreaterEqual(len(queue_selectors), len(configured_dscps))

    def test_long_running_congestion_buffers_are_checked_in_every_phase(self) -> None:
        playbooks = _playbooks_with_prefix(
            _SINGLE_CONGESTION_PREFIX
        ) + _playbooks_with_prefix(_MULTI_CONGESTION_PREFIX)
        self.assertEqual(10, len(playbooks))
        for playbook in playbooks:
            checks = _snapshot_payloads(
                playbook, hc_types.CheckName.BUFFER_UTILIZATION_CHECK
            )
            for stage in playbook.stages or []:
                prefix = f"stage.{stage.id}."
                with self.subTest(playbook=playbook.name, stage=stage.id):
                    self.assertTrue(
                        any(
                            (check.pre_snapshot_checkpoint_id or "").startswith(prefix)
                            and (check.post_snapshot_checkpoint_id or "").startswith(
                                prefix
                            )
                            for check, _ in checks
                        ),
                        f"{playbook.name}: no buffer check for {stage.id}",
                    )

    def test_long_running_reverse_order_uses_selective_starts(self) -> None:
        playbooks = _playbooks_with_prefix(
            _SINGLE_CONGESTION_PREFIX
        ) + _playbooks_with_prefix(_MULTI_CONGESTION_PREFIX)
        self.assertEqual(10, len(playbooks))
        for playbook in playbooks:
            stage = next(
                stage
                for stage in playbook.stages or []
                if "reverse" in (stage.id or "")
            )
            baseline, congestion = _baseline_and_congestion_names(playbook)
            positions = _selective_start_positions(stage, baseline | congestion)
            with self.subTest(playbook=playbook.name):
                self.assertEqual(baseline | congestion, set(positions))
                self.assertLess(
                    max(positions[name] for name in baseline),
                    min(positions[name] for name in congestion),
                )
                first_start = min(positions.values())
                last_start = max(positions.values())
                self.assertFalse(
                    any(
                        _api_name(step) == "stop_traffic"
                        for step in list(stage.steps or [])[
                            first_start + 1 : last_start
                        ]
                    )
                )

    def test_multi_congestion_requires_egress_only_from_priority_queue(self) -> None:
        dscp_to_cos = {48: 5, 35: 4, 18: 3, 9: 2, 10: 1}
        playbooks = _playbooks_with_prefix(_MULTI_CONGESTION_PREFIX)
        self.assertEqual(6, len(playbooks))
        for playbook in playbooks:
            baseline, _ = _baseline_and_congestion_names(playbook)
            priority_dscps = set()
            traffic_items = _traffic_items(playbook)
            for name in baseline:
                qos_config = traffic_items[name].qos_config
                assert qos_config is not None
                dscp_value = qos_config.dscp_value
                assert dscp_value is not None
                priority_dscps.add(dscp_value)
            self.assertEqual(1, len(priority_dscps))
            expected_cos = dscp_to_cos[priority_dscps.pop()]
            queue_payloads = _snapshot_payloads(
                playbook, hc_types.CheckName.QOS_DSCP_TX_QUEUE_CHECK
            )
            for _, payload in queue_payloads:
                queue_info = t.cast(
                    list[dict[str, object]], payload.get("tx_queue_info_list", [])
                )
                with self.subTest(playbook=playbook.name, payload=payload):
                    self.assertEqual(1, len(queue_info))
                    self.assertEqual([expected_cos], queue_info[0].get("cos_list"))
                    self.assertFalse(queue_info[0].get("enforce_exclusivity"))

    def test_multi_congestion_initial_order_uses_selective_starts(self) -> None:
        playbooks = _playbooks_with_prefix(_MULTI_CONGESTION_PREFIX)
        self.assertEqual(6, len(playbooks))
        for playbook in playbooks:
            stage = next(
                stage
                for stage in playbook.stages or []
                if stage.id == "qos_multi_congestion_traffic"
            )
            baseline, congestion = _baseline_and_congestion_names(playbook)
            positions = _selective_start_positions(stage, baseline | congestion)
            with self.subTest(playbook=playbook.name):
                self.assertEqual(baseline | congestion, set(positions))
                self.assertLess(
                    max(positions[name] for name in congestion),
                    min(positions[name] for name in baseline),
                )
                first_start = min(positions.values())
                last_start = max(positions.values())
                self.assertFalse(
                    any(
                        _api_name(step) == "stop_traffic"
                        for step in list(stage.steps or [])[
                            first_start + 1 : last_start
                        ]
                    )
                )
