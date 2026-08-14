# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from ixia.ixia import types as ixia_types
from taac.ixia.abstract_traffic_generator import (
    AbstractTrafficGenerator,
)
from taac.ixia.config_render import (
    _readable,
    _render_annotations,
    _render_check_thresholds,
    render_ixia_config,
    ResolvedCheck,
)
from taac.utils.json_thrift_utils import thrift_to_json
from parameterized import parameterized
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types


def _port(
    name: str, groups: ixia_types.PfcPriorityGroupsConfig | None
) -> ixia_types.PortConfig:
    l1_config = (
        None
        if groups is None
        else ixia_types.L1Config(
            flow_control_config=ixia_types.FlowControlConfig(
                pfc_prority_groups_config=groups
            )
        )
    )
    return ixia_types.PortConfig(port_name=name, l1_config=l1_config)


def _traffic_rate_check(
    thresholds: list[hc_types.TrafficRateThreshold],
) -> taac_types.PointInTimeHealthCheck:
    return taac_types.PointInTimeHealthCheck(
        name=hc_types.CheckName.IXIA_TRAFFIC_RATE_CHECK,
        input_json=thrift_to_json(
            hc_types.IxiaTrafficRateHealthCheckIn(thresholds=thresholds)
        ),
    )


def _packet_loss_check(
    thresholds: list[hc_types.PacketLossThreshold],
) -> taac_types.PointInTimeHealthCheck:
    return taac_types.PointInTimeHealthCheck(
        name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
        input_json=thrift_to_json(
            hc_types.IxiaPacketLossHealthCheckIn(thresholds=thresholds)
        ),
    )


def _readable_fields(struct: object) -> dict[str, object]:
    readable = _readable(struct)
    assert isinstance(readable, dict), f"expected a dict, got {type(readable)}"
    return readable


class ReadableTest(unittest.TestCase):
    def test_enums_render_as_names_not_integers(self) -> None:
        item = ixia_types.TrafficItem(
            name="flow1",
            traffic_type=ixia_types.TrafficType.IPV6,
            qos_config=ixia_types.QoSConfig(dscp_value=26),
        )
        readable = _readable_fields(item)
        qos = _readable_fields(item.qos_config)
        self.assertEqual("IPV6", readable["traffic_type"])
        self.assertEqual("TRAFFIC_CLASS", qos["phb_type"])
        self.assertEqual(26, qos["dscp_value"])

    def test_unset_optional_fields_are_dropped(self) -> None:
        readable = _readable_fields(ixia_types.TrafficItem(name="flow1"))
        self.assertNotIn("mpls_config", readable)
        self.assertIn("enabled", readable)

    def test_unmapped_pfc_queue_renders_as_none_not_999(self) -> None:
        readable = _readable_fields(ixia_types.PfcPriorityGroupsConfig())
        self.assertEqual("NONE", readable["priority7_pfc_queue"])
        self.assertEqual("ZERO", readable["priority0_pfc_queue"])


class PfcAnnotationTest(unittest.TestCase):
    @parameterized.expand(
        [
            (
                "identity_default",
                ixia_types.PfcPriorityGroupsConfig(),
                "port p1: PFC priority -> queue map is identity",
            ),
            (
                "swapped_pair",
                ixia_types.PfcPriorityGroupsConfig(
                    priority0_pfc_queue=ixia_types.PfcQueue.THREE,
                    priority3_pfc_queue=ixia_types.PfcQueue.ZERO,
                ),
                "port p1: PFC priority -> queue map is NON-IDENTITY "
                "(priority 0 maps to queue 3, priority 3 maps to queue 0)",
            ),
            (
                "unmapped_priority_is_not_a_swap",
                ixia_types.PfcPriorityGroupsConfig(
                    priority2_pfc_queue=ixia_types.PfcQueue.NONE
                ),
                "port p1: PFC priority -> queue map is identity",
            ),
        ]
    )
    def test_pfc_map_annotation(
        self, _name: str, groups: ixia_types.PfcPriorityGroupsConfig, expected: str
    ) -> None:
        rendered = _render_annotations([_port("p1", groups)], [])
        self.assertIn(expected, rendered)

    def test_port_without_l1_config_is_reported_explicitly(self) -> None:
        rendered = _render_annotations([_port("p1", None)], [])
        self.assertIn(
            "port p1: PFC priority -> queue map is not configured on this port",
            rendered,
        )

    def test_missing_port_config_is_reported_explicitly(self) -> None:
        rendered = _render_annotations([], [])
        self.assertIn("the generator reported no declarative port config", rendered)


class DisabledTrafficItemTest(unittest.TestCase):
    def test_disabled_item_is_named_not_dropped(self) -> None:
        rendered = _render_annotations(
            [],
            [
                ixia_types.TrafficItem(name="live_flow", enabled=True),
                ixia_types.TrafficItem(name="dead_flow", enabled=False),
            ],
        )
        self.assertIn(
            "declared but DISABLED, these flows do not transmit: dead_flow", rendered
        )
        self.assertNotIn("live_flow", rendered)

    def test_all_enabled_is_stated_explicitly(self) -> None:
        rendered = _render_annotations(
            [], [ixia_types.TrafficItem(name="live_flow", enabled=True)]
        )
        self.assertIn("every declared traffic item is enabled", rendered)


class TrafficRateThresholdTest(unittest.TestCase):
    def test_both_directions_are_gated_despite_declared_metric(self) -> None:
        check = _traffic_rate_check(
            [
                hc_types.TrafficRateThreshold(
                    value=32,
                    threshold_type=hc_types.ThresholdType.PERCENT,
                    metric=hc_types.TrafficRateMetric.TX_RATE,
                )
            ]
        )
        rendered = _render_check_thresholds(
            [ResolvedCheck(check=check, params={"base_bandwidth_gbps": 200})]
        )
        self.assertIn("TX_RATE and RX_RATE must both exceed 32", rendered)
        self.assertIn("PERCENT of base_bandwidth_gbps=200.0", rendered)
        self.assertIn("declared metric field is not read by the check", rendered)

    @parameterized.expand(
        [
            ("static_or_json", {"base_bandwidth_gbps": 200}, "=200.0"),
            ("string_param", {"base_bandwidth_gbps": "800"}, "=800.0"),
            ("jq_or_transform_float", {"base_bandwidth_gbps": 200.0}, "=200.0"),
        ]
    )
    def test_resolved_base_bandwidth_is_reported_as_a_float(
        self, _name: str, params: dict[str, object], expected: str
    ) -> None:
        check = _traffic_rate_check([hc_types.TrafficRateThreshold(value=32)])
        rendered = _render_check_thresholds([ResolvedCheck(check=check, params=params)])
        self.assertIn(f"base_bandwidth_gbps{expected}", rendered)

    def test_absent_param_names_the_silent_400g_fallback(self) -> None:
        check = _traffic_rate_check([hc_types.TrafficRateThreshold(value=32)])
        rendered = _render_check_thresholds([ResolvedCheck(check=check, params={})])
        self.assertIn("base_bandwidth_gbps=(UNSET", rendered)
        self.assertIn("400.0 Gbps", rendered)

    def test_unresolvable_params_are_unknown_not_unset(self) -> None:
        check = _traffic_rate_check([hc_types.TrafficRateThreshold(value=32)])
        rendered = _render_check_thresholds([ResolvedCheck(check=check, params=None)])
        self.assertIn("base_bandwidth_gbps=(UNKNOWN", rendered)
        self.assertNotIn("UNSET", rendered)

    def test_absolute_threshold_does_not_reference_a_base(self) -> None:
        check = _traffic_rate_check(
            [
                hc_types.TrafficRateThreshold(
                    value=150, threshold_type=hc_types.ThresholdType.ABSOLUTE
                )
            ]
        )
        rendered = _render_check_thresholds([ResolvedCheck(check=check, params={})])
        self.assertIn("must both exceed 150 Gbps (ABSOLUTE)", rendered)
        self.assertNotIn("base_bandwidth_gbps", rendered)


class PacketLossThresholdTest(unittest.TestCase):
    def test_expect_packet_loss_inverts_the_gate(self) -> None:
        check = _packet_loss_check(
            [
                hc_types.PacketLossThreshold(
                    metric=hc_types.PacketLossMetric.FRAME_DELTA,
                    str_value="0",
                    expect_packet_loss=True,
                )
            ]
        )
        rendered = _render_check_thresholds([ResolvedCheck(check=check, params={})])
        self.assertIn("expect_packet_loss=true", rendered)
        self.assertIn("is NOT", rendered)
        self.assertIn("fails only when FRAME_DELTA is 0", rendered)

    def test_between_reports_both_bounds(self) -> None:
        check = _packet_loss_check(
            [
                hc_types.PacketLossThreshold(
                    metric=hc_types.PacketLossMetric.PERCENTAGE,
                    comparison=hc_types.ComparisonType.BETWEEN,
                    lower_bound="1",
                    upper_bound="5",
                )
            ]
        )
        rendered = _render_check_thresholds([ResolvedCheck(check=check, params={})])
        self.assertIn("PERCENTAGE must be BETWEEN 1 and 5, inclusive", rendered)

    def test_between_names_the_bound_defaults_the_check_substitutes(self) -> None:
        check = _packet_loss_check(
            [
                hc_types.PacketLossThreshold(
                    metric=hc_types.PacketLossMetric.PERCENTAGE,
                    comparison=hc_types.ComparisonType.BETWEEN,
                )
            ]
        )
        rendered = _render_check_thresholds([ResolvedCheck(check=check, params={})])
        self.assertIn("(unset, the check uses 0)", rendered)
        self.assertIn("(unset, the check uses sys.maxsize)", rendered)

    def test_plain_comparison_renders_metric_and_value(self) -> None:
        check = _packet_loss_check(
            [
                hc_types.PacketLossThreshold(
                    names=["flow1"],
                    metric=hc_types.PacketLossMetric.DURATION,
                    str_value="250",
                )
            ]
        )
        rendered = _render_check_thresholds([ResolvedCheck(check=check, params={})])
        self.assertIn(
            "DURATION must be LESS_THAN_EQUAL_TO 250 (traffic items: flow1)", rendered
        )

    def test_no_threshold_bearing_checks_is_stated_explicitly(self) -> None:
        rendered = _render_check_thresholds([])
        self.assertIn("(no threshold-bearing checks declared)", rendered)


class RenderIxiaConfigTest(unittest.TestCase):
    def test_absent_generator_is_not_treated_as_evidence(self) -> None:
        rendered = render_ixia_config(None, None, [])
        self.assertIn("Do not treat this as evidence either way", rendered)

    def test_render_emits_every_block(self) -> None:
        ixia = MagicMock(spec=AbstractTrafficGenerator)
        ixia.get_port_configs.return_value = [
            _port(
                "p1",
                ixia_types.PfcPriorityGroupsConfig(
                    priority0_pfc_queue=ixia_types.PfcQueue.THREE
                ),
            )
        ]
        ixia.get_traffic_item_configs.return_value = [
            ixia_types.TrafficItem(name="dead_flow", enabled=False)
        ]
        ixia.get_traffic_items.return_value = ["live_flow"]
        check = _packet_loss_check([hc_types.PacketLossThreshold(str_value="0")])
        rendered = render_ixia_config(
            ixia, None, [ResolvedCheck(check=check, params={})]
        )
        self.assertIn("Declarative IXIA config this test provisioned:", rendered)
        self.assertIn("Annotations on the config above:", rendered)
        self.assertIn("is NON-IDENTITY (priority 0 maps to queue 3)", rendered)
        self.assertIn(
            "Declared check thresholds, as the check evaluates them:", rendered
        )
        self.assertIn("Live traffic items reported by the generator backend:", rendered)
        self.assertIn("  - live_flow", rendered)

    def test_live_read_failure_is_reported_not_raised(self) -> None:
        ixia = MagicMock(spec=AbstractTrafficGenerator)
        ixia.get_port_configs.return_value = []
        ixia.get_traffic_item_configs.return_value = []
        ixia.get_traffic_items.side_effect = RuntimeError("REST timeout")
        rendered = render_ixia_config(ixia, None, [])
        self.assertIn("ERROR: could not read live traffic items", rendered)
