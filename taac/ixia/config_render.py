# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict
from __future__ import annotations

import dataclasses
import json
import logging
from collections.abc import Mapping, Sequence
from typing import TypeVar

from ixia.ixia import types as ixia_types
from taac.health_checks.ixia_health_checks.ixia_traffic_rate_health_check import (
    DEFAULT_BASE_BANDWIDTH_GBPS,
)
from taac.ixia.abstract_traffic_generator import (
    AbstractTrafficGenerator,
)
from taac.libs.ixia_candidate import IxiaCandidate
from taac.utils.json_thrift_utils import json_to_thrift
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types
from thrift.py3.types import Struct as Py3Struct
from thrift.python.types import Enum as ThriftEnum, Struct as ThriftStruct

logger: logging.Logger = logging.getLogger(__name__)

DeclaredCheck = taac_types.PointInTimeHealthCheck | taac_types.SnapshotHealthCheck

_CheckIn = TypeVar("_CheckIn", bound=Py3Struct)

_BASE_BANDWIDTH_PARAM: str = "base_bandwidth_gbps"

_NOT_AVAILABLE: str = "(not available)"

_NO_GENERATOR: str = (
    "No traffic generator was provisioned for this test case, so there is no "
    "IXIA configuration to read. Do not treat this as evidence either way."
)

# ``IxiaTrafficRateHealthCheck.verify_traffic_rate_threshold`` never reads
# ``TrafficRateThreshold.metric``; it derives one threshold and flags the flow
# when either direction is at or below it.
_TRAFFIC_RATE_METRIC_NOTE: str = (
    "the declared metric field is not read by the check, which flags the flow "
    "when EITHER direction is at or below the threshold"
)


@dataclasses.dataclass(frozen=True)
class ResolvedCheck:
    """A declared check paired with its ``check_params`` as the runner resolves them.

    ``params`` is None when resolution raised, so the renderer reports the
    reference base as unknown rather than asserting it was left unset.
    """

    check: DeclaredCheck
    params: Mapping[str, object] | None


def render_ixia_config(
    ixia: AbstractTrafficGenerator | None,
    candidate: IxiaCandidate | None,
    checks: Sequence[ResolvedCheck],
) -> str:
    """Render the traffic generator's configuration for one test case.

    The declarative config the test provisioned, annotated with the artifacts a
    serializer cannot express (a non-identity PFC priority map, a flow declared
    but disabled) and with each declared check's threshold restated as the check
    actually evaluates it. Ends with the traffic items the generator backend
    currently holds, so a flow the test declared but never pushed shows up as a
    difference.
    """
    if ixia is None:
        return _NO_GENERATOR
    # Declarative getters expose the thrift config the generator was built from;
    # per ``AbstractTrafficGenerator`` they make no backend call and cannot raise.
    port_configs = ixia.get_port_configs()
    traffic_items = ixia.get_traffic_item_configs()
    blocks = [
        _render_ixia_candidate(candidate),
        _render_declarative_config(port_configs, traffic_items),
        _render_annotations(port_configs, traffic_items),
        _render_check_thresholds(checks),
        "Live traffic items reported by the generator backend:\n"
        f"{_live_traffic_item_report(ixia)}",
    ]
    return "\n\n".join(block for block in blocks if block)


def _render_ixia_candidate(candidate: IxiaCandidate | None) -> str:
    if candidate is None:
        return "IXIA candidate: (none selected)"
    api_server = candidate.api_server_ip or "(auto-discover)"
    return f"IXIA candidate: name={candidate.name} api_server={api_server}"


# ---------------------------------------------------------------------------
# Declarative config dump
# ---------------------------------------------------------------------------


def _render_declarative_config(
    port_configs: Sequence[ixia_types.PortConfig],
    traffic_items: Sequence[ixia_types.TrafficItem],
) -> str:
    payload = {
        "port_configs": [_readable(port) for port in port_configs],
        "traffic_items": [_readable(item) for item in traffic_items],
    }
    return (
        "Declarative IXIA config this test provisioned:\n"
        f"{json.dumps(payload, indent=2, sort_keys=True)}"
    )


def _readable(value: object) -> object:
    """A thrift value as JSON-ready data, with enums rendered as their names.

    The repo serializer emits enums as their integer value, which turns
    ``PfcQueue.NONE`` into a plausible-looking "queue 999" and every traffic
    type, PHB type and rate type into an opaque number. Unset optional fields
    are dropped, matching the serializer.
    """
    if isinstance(value, ThriftEnum):
        return value.name
    if isinstance(value, ThriftStruct):
        return {name: _readable(field) for name, field in value if field is not None}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    if isinstance(value, Mapping):
        return {str(key): _readable(item) for key, item in value.items()}
    if isinstance(value, Sequence):
        return [_readable(item) for item in value]
    return repr(value)


# ---------------------------------------------------------------------------
# Annotations the dump above does not express
# ---------------------------------------------------------------------------


def _render_annotations(
    port_configs: Sequence[ixia_types.PortConfig],
    traffic_items: Sequence[ixia_types.TrafficItem],
) -> str:
    lines = [
        *_render_pfc_annotations(port_configs),
        *_render_traffic_item_annotations(traffic_items),
    ]
    return "\n".join(["Annotations on the config above:", *lines])


def _render_pfc_annotations(
    port_configs: Sequence[ixia_types.PortConfig],
) -> list[str]:
    if not port_configs:
        return ["  - the generator reported no declarative port config"]
    return [_render_pfc_map(port) for port in port_configs]


def _render_pfc_map(port: ixia_types.PortConfig) -> str:
    """Flag a priority mapped to a queue other than its own number.

    This is the artifact an investigation skims past when it is folded into a
    one-line struct repr.
    """
    label = f"  - port {port.port_name or _NOT_AVAILABLE}: PFC priority -> queue map"
    groups = _pfc_groups(port)
    if groups is None:
        return f"{label} is not configured on this port"
    swapped = [
        (priority, queue.value)
        for priority, queue in _priority_queue_pairs(groups)
        if not _is_unmapped(queue) and queue.value != priority
    ]
    if not swapped:
        return f"{label} is identity (every mapped priority uses its own queue)"
    detail = ", ".join(
        f"priority {priority} maps to queue {queue}" for priority, queue in swapped
    )
    return f"{label} is NON-IDENTITY ({detail})"


def _pfc_groups(
    port: ixia_types.PortConfig,
) -> ixia_types.PfcPriorityGroupsConfig | None:
    l1_config = port.l1_config
    if l1_config is None:
        return None
    flow_control = l1_config.flow_control_config
    if flow_control is None:
        return None
    # The thrift field name carries a typo (`prority`); spelled verbatim here.
    return flow_control.pfc_prority_groups_config


def _priority_queue_pairs(
    groups: ixia_types.PfcPriorityGroupsConfig,
) -> tuple[tuple[int, ixia_types.PfcQueue], ...]:
    return (
        (0, groups.priority0_pfc_queue),
        (1, groups.priority1_pfc_queue),
        (2, groups.priority2_pfc_queue),
        (3, groups.priority3_pfc_queue),
        (4, groups.priority4_pfc_queue),
        (5, groups.priority5_pfc_queue),
        (6, groups.priority6_pfc_queue),
        (7, groups.priority7_pfc_queue),
    )


def _is_unmapped(queue: ixia_types.PfcQueue) -> bool:
    """``PfcQueue.NONE`` is the struct default for priorities 4-7, not a swap."""
    return queue == ixia_types.PfcQueue.NONE


def _render_traffic_item_annotations(
    traffic_items: Sequence[ixia_types.TrafficItem],
) -> list[str]:
    if not traffic_items:
        return ["  - the generator reported no declarative traffic-item config"]
    disabled = [
        item.name or _NOT_AVAILABLE for item in traffic_items if not item.enabled
    ]
    if not disabled:
        return ["  - every declared traffic item is enabled"]
    return [
        f"  - declared but DISABLED, these flows do not transmit: {', '.join(disabled)}"
    ]


# ---------------------------------------------------------------------------
# Live traffic items (what the backend holds right now)
# ---------------------------------------------------------------------------


def _live_traffic_item_report(ixia: AbstractTrafficGenerator) -> str:
    try:
        items = ixia.get_traffic_items()
    except Exception as exc:
        logger.warning("live traffic-item read failed", exc_info=True)
        return f"  ERROR: could not read live traffic items: {exc!r}"
    if not items:
        return "  (the generator backend reports no traffic items)"
    return "\n".join(f"  - {_live_traffic_item_label(item)}" for item in items)


def _live_traffic_item_label(item: object) -> str:
    """restpy returns objects carrying a ``Name``; OTG returns plain flow names."""
    name = getattr(item, "Name", None)
    if isinstance(name, str):
        enabled = getattr(item, "Enabled", None)
        return f"{name} (enabled={enabled})" if enabled is not None else name
    return str(item)


# ---------------------------------------------------------------------------
# Declared check thresholds (the gate the check actually applies)
# ---------------------------------------------------------------------------


def _render_check_thresholds(checks: Sequence[ResolvedCheck]) -> str:
    header = "Declared check thresholds, as the check evaluates them:"
    rendered = [line for check in checks for line in _render_check_threshold(check)]
    if not rendered:
        return f"{header}\n  (no threshold-bearing checks declared)"
    return "\n".join([header, *rendered])


def _render_check_threshold(resolved: ResolvedCheck) -> list[str]:
    if resolved.check.name == hc_types.CheckName.IXIA_TRAFFIC_RATE_CHECK:
        return _render_traffic_rate_thresholds(resolved)
    if resolved.check.name == hc_types.CheckName.IXIA_PACKET_LOSS_CHECK:
        return _render_packet_loss_thresholds(resolved.check)
    return []


def _check_label(check: DeclaredCheck) -> str:
    suffix = f" [{check.check_id}]" if check.check_id else ""
    return f"{check.name.name}{suffix}"


def _render_traffic_rate_thresholds(resolved: ResolvedCheck) -> list[str]:
    check = resolved.check
    decoded = _decode_check_input(
        check.input_json, hc_types.IxiaTrafficRateHealthCheckIn
    )
    label = _check_label(check)
    if decoded is None or not decoded.thresholds:
        return [f"  - {label}: {_NOT_AVAILABLE} (no thresholds decoded)"]
    base = _render_base_bandwidth(resolved.params)
    return [
        f"  - {label}: TX_RATE and RX_RATE must both exceed {threshold.value} "
        f"{_render_rate_unit(threshold.threshold_type, base)}"
        f"{_render_threshold_names(threshold.names)}"
        f" [declared metric={threshold.metric.name}; {_TRAFFIC_RATE_METRIC_NOTE}]"
        for threshold in decoded.thresholds
    ]


def _render_rate_unit(threshold_type: hc_types.ThresholdType, base: str) -> str:
    if threshold_type == hc_types.ThresholdType.PERCENT:
        return f"PERCENT of {base}"
    return "Gbps (ABSOLUTE)"


def _render_packet_loss_thresholds(check: DeclaredCheck) -> list[str]:
    decoded = _decode_check_input(
        check.input_json, hc_types.IxiaPacketLossHealthCheckIn
    )
    label = _check_label(check)
    if decoded is None or not decoded.thresholds:
        return [f"  - {label}: {_NOT_AVAILABLE} (no thresholds decoded)"]
    return [
        f"  - {label}: {_render_packet_loss_gate(threshold)}"
        f"{_render_threshold_names(threshold.names)}"
        for threshold in decoded.thresholds
    ]


def _render_packet_loss_gate(threshold: hc_types.PacketLossThreshold) -> str:
    """The gate ``verify_packet_loss_threshold`` applies, not the declared fields.

    ``expect_packet_loss`` short-circuits the comparison entirely, so rendering
    the comparison in that case states the opposite of the gate that ran.
    """
    metric = threshold.metric.name
    if threshold.expect_packet_loss:
        return (
            f"expect_packet_loss=true, so the declared comparison "
            f"({threshold.comparison.name} {threshold.str_value}) is NOT "
            f"evaluated and the check fails only when {metric} is 0"
        )
    if threshold.comparison == hc_types.ComparisonType.BETWEEN:
        lower = _render_bound(threshold.lower_bound, "0")
        upper = _render_bound(threshold.upper_bound, "sys.maxsize")
        return f"{metric} must be BETWEEN {lower} and {upper}, inclusive"
    return f"{metric} must be {threshold.comparison.name} {threshold.str_value}"


def _render_bound(value: str | None, fallback: str) -> str:
    if value:
        return value
    return f"(unset, the check uses {fallback})"


def _render_threshold_names(names: Sequence[str] | None) -> str:
    if not names:
        return " (all traffic items)"
    return f" (traffic items: {', '.join(names)})"


def _render_base_bandwidth(params: Mapping[str, object] | None) -> str:
    """The PERCENT reference base, naming the silent default when it is unset.

    Omitting ``base_bandwidth_gbps`` does not disable the percentage, it scales
    it against 400G, so a 32%-of-line-rate gate on a 200G port is really a
    64%-of-line-rate gate.
    """
    if params is None:
        return (
            f"{_BASE_BANDWIDTH_PARAM}=(UNKNOWN, this check's check_params could "
            "not be resolved)"
        )
    if _BASE_BANDWIDTH_PARAM not in params:
        return (
            f"{_BASE_BANDWIDTH_PARAM}=(UNSET, the check falls back to "
            f"{DEFAULT_BASE_BANDWIDTH_GBPS} Gbps; on a port of any other speed "
            "the effective threshold is mis-scaled)"
        )
    declared = params[_BASE_BANDWIDTH_PARAM]
    resolved = _coerce_float(declared)
    if resolved is None:
        return (
            f"{_BASE_BANDWIDTH_PARAM}={declared!r} (NOT NUMERIC, the check calls "
            "float() on this value and will raise)"
        )
    return f"{_BASE_BANDWIDTH_PARAM}={resolved}"


def _coerce_float(value: object) -> float | None:
    """Mirrors the check's ``float(check_params[...])``, including bool coercion."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _decode_check_input(
    input_json: str | None, check_input_type: type[_CheckIn]
) -> _CheckIn | None:
    if not input_json:
        return None
    try:
        return json_to_thrift(input_json, check_input_type)
    except Exception:
        logger.warning(
            f"could not decode {check_input_type.__name__} check input", exc_info=True
        )
        return None
