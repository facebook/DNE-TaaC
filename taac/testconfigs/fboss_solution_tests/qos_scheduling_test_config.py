# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""QoS scheduling TestConfig + scheduling/congestion playbook factories.

Builds ``test_config_qos_scheduling`` and the per-CoS scheduling, per-queue congestion,
single-queue congestion, and multi-queue congestion playbooks used to qualify QoS DSCP /
strict-priority scheduling behavior across NC, ICP, GOLD, SILVER, BRONZE, and NCNF queues.
"""

import json
import re
import typing as t

from ixia.ixia import types as ixia_types
from taac.constants import WEDGE_AGENT_BINDS_TO_CASCADE
from taac.health_checks.healthcheck_definitions import (
    create_buffer_utilization_snapshot_check,
    create_ixia_packet_loss_check,
    create_qos_dscp_tx_queue_snapshot_check,
    create_service_restart_check,
)
from taac.playbooks.playbook_definitions import (
    build_qos_scheduling_playbook,
    COS_MULTI_CONGESTION_PLAYBOOK,
    COS_PAIR_TO_CONGESTION_PLAYBOOK,
    COS_TO_PER_QUEUE_CONGESTION_PLAYBOOK,
    COS_TO_SCHEDULING_PLAYBOOK,
    COS_TO_SINGLE_CONGESTION_PLAYBOOK,
    TEST_QOS_PER_QUEUE_CONGESTION_QUEUE0_NCNF,
    TEST_QOS_SCHEDULING_QUEUE0_NCNF,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_ixia_api_step,
    create_longevity_step,
    create_service_convergence_step,
    create_service_interruption_step,
    create_validation_step,
)
from taac.testconfigs.fboss_solution_tests.fboss_bgp_and_platform_hardening_conveyor import (
    create_ixia_packet_loss_check_traffic_split,
    test_config_for_bgp_and_fboss_platform_hardening_in_conveyor,
)
from taac.utils.qos_constants import ClassOfService
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import (
    Playbook,
    PointInTimeHealthCheck,
    Service,
    ServiceInterruptionTrigger,
    SnapshotHealthCheck,
    Step,
    StepName,
)

# DSCP values for each ClassOfService.
# These are the "self-marking" DSCP values from the cos_utility_maps configerator config.
COS_DSCP_VALUES: t.Dict[ClassOfService, int] = {
    ClassOfService.BRONZE: 10,
    ClassOfService.SILVER: 9,
    ClassOfService.GOLD: 18,
    ClassOfService.ICP: 35,
    ClassOfService.NC: 48,
}

# NCNF is not yet a first-class ClassOfService enum value.
# Define its DSCP and queue descriptor as standalone constants.
NCNF_DSCP_VALUE = 51
NCNF_QUEUE_DESC = "queue0.ncnf"

# Mapping from ClassOfService to human-readable queue description.
# Mirrors COS_QUEUE_FB303_COUNTER_DESC in qos_dscp_tx_queue_health_check.py.
COS_QUEUE_DESC: t.Dict[ClassOfService, str] = {
    ClassOfService.BRONZE: "queue1.bronze",
    ClassOfService.SILVER: "queue2.silver",
    ClassOfService.GOLD: "queue3.gold",
    ClassOfService.ICP: "queue6.icp",
    ClassOfService.NC: "queue7.nc",
}

# Priority ordering (highest → lowest) used to generate congestion test pairs.
# Tests verify that a higher-priority queue is not affected when a
# lower-priority queue is congested.
COS_PRIORITY_ORDER: t.List[ClassOfService] = [
    ClassOfService.NC,
    ClassOfService.ICP,
    ClassOfService.GOLD,
    ClassOfService.SILVER,
    ClassOfService.BRONZE,
]

LONGEVITY_DURATION_S = 120

# Buffer utilization thresholds for single-queue scheduling tests (bytes).
# Active queue (the queue carrying test traffic) must not exceed 105 MB.
ACTIVE_QUEUE_BUFFER_MAX_BYTES = 105 * 1024 * 1024  # 105 MB
# All other queues must not exceed 5 MB.
OTHER_QUEUE_BUFFER_MAX_BYTES = 5 * 1024 * 1024  # 5 MB

# Buffer utilization thresholds for continuous congestion tests (bytes).
CONTINUOUS_CONGESTED_QUEUE_BUFFER_MAX_BYTES = 110 * 1024 * 1024
CONTINUOUS_OTHER_QUEUE_BUFFER_MAX_BYTES = 5 * 1024 * 1024
PRIORITY_QUEUE_BUFFER_MAX_BYTES = 10 * 1024 * 1024
OTHER_QUEUE_BOUND_DELEGATED_BYTES = 200 * 1024 * 1024

# Buffer utilization thresholds for warmboot/reverse-order congestion tests.
LONG_RUNNING_CONGESTED_QUEUE_BUFFER_MAX_BYTES = 150 * 1024 * 1024
LONG_RUNNING_OTHER_QUEUE_BUFFER_MAX_BYTES = 10 * 1024 * 1024

# Burst spec: 30 ms at the configured traffic-item rate and 5 ms between bursts.
BURST_INTER_GAP_MS = 5.0
BURST_DURATION_MS = 30.0
IMIX_MEAN_WIRE_BYTES = (100 * 1 + 1500 * 4 + 4500 * 5 + 7000 * 1 + 9000 * 1) / 12 + 20
PORT_SPEED_BITS_PER_SECOND = 100_000_000_000
BURST_REPEAT_COUNT = round(
    LONGEVITY_DURATION_S * 1000 / (BURST_DURATION_MS + BURST_INTER_GAP_MS)
)

# Linerate for each per-queue congestion traffic item in multi-queue tests.
MULTI_CONGESTION_LINERATE = 10

# Per-queue congestion traffic item name suffixes.
COS_CONGESTION_TRAFFIC_SUFFIX: t.Dict[ClassOfService, str] = {
    ClassOfService.ICP: "CONGESTION_TRAFFIC_ICP",
    ClassOfService.GOLD: "CONGESTION_TRAFFIC_GOLD",
    ClassOfService.SILVER: "CONGESTION_TRAFFIC_SILVER",
    ClassOfService.BRONZE: "CONGESTION_TRAFFIC_BRONZE",
}

# Default frame size for QoS traffic items — weighted IMIX distribution.
DEFAULT_FRAME_SIZE = ixia_types.FrameSize(
    type=ixia_types.FrameSizeType.CUSTOM_IMIX,
    imix_weight={100: 1, 1500: 4, 4500: 5, 7000: 1, 9000: 1},
)

# Name suffix for the congestion traffic item created on the dedicated
# congestion IXIA port.
CONGESTION_TRAFFIC_ITEM_SUFFIX = "CONGESTION_TRAFFIC"

DISABLED_AUXILIARY_TRAFFIC_SUFFIXES = [
    "GOOD_BUT_LOSSY_NDP_TRAFFIC",
    "LOSSY_ROGUE_NDP_TRAFFIC",
    "HIGH_QUEUE_BGP_CP_TRAFFIC",
]


def _get_ipv6_packet_headers() -> t.List[taac_types.PacketHeader]:
    """
    Returns IPv6 packet headers that expose the Traffic Class (DSCP) field
    for manipulation. The Traffic Class in IPv6 encodes the DSCP + ECN bits,
    analogous to the ToS field in IPv4.
    """
    return [
        taac_types.PacketHeader(
            query=ixia_types.Query(
                regex="^ipv6$",
                query_type=ixia_types.QueryType.STACK_TYPE_ID,
            ),
            fields=[
                taac_types.Field(
                    query=ixia_types.Query(regex="Traffic Class"),
                    attrs_json=json.dumps(
                        {
                            "SingleValue": 0,
                        }
                    ),
                ),
            ],
        ),
    ]


def _make_buffer_utilization_check(
    device_name: str,
    active_cos_list: t.List[ClassOfService],
    interfaces: t.List[str],
    active_queue_max_bytes: int,
    other_queue_max_bytes: int,
    active_queue_desc_list: t.Optional[t.List[str]] = None,
    pre_snapshot_checkpoint_id: t.Optional[str] = None,
    post_snapshot_checkpoint_id: t.Optional[str] = None,
) -> SnapshotHealthCheck:
    """Helper to create a BUFFER_UTILIZATION_CHECK SnapshotHealthCheck."""
    return create_buffer_utilization_snapshot_check(
        thresholds=[
            hc_types.BufferUtilizationThreshold(
                hostname=device_name,
                interfaces=interfaces,
                active_cos_list=[int(c) for c in active_cos_list],
                active_queue_desc_list=active_queue_desc_list or [],
                active_queue_max_bytes=active_queue_max_bytes,
                other_queue_max_bytes=other_queue_max_bytes,
            ),
        ],
        pre_snapshot_checkpoint_id=pre_snapshot_checkpoint_id,
        post_snapshot_checkpoint_id=post_snapshot_checkpoint_id,
    )


def _make_qos_snapshot_check(
    device_name: str,
    cos: ClassOfService,
    interfaces: t.List[str],
    pre_snapshot_checkpoint_id: t.Optional[str] = None,
    post_snapshot_checkpoint_id: t.Optional[str] = None,
) -> SnapshotHealthCheck:
    """Helper to create a QOS_DSCP_TX_QUEUE_CHECK SnapshotHealthCheck."""
    return _make_qos_cos_list_snapshot_check(
        device_name=device_name,
        cos_list=[cos],
        interfaces=interfaces,
        pre_snapshot_checkpoint_id=pre_snapshot_checkpoint_id,
        post_snapshot_checkpoint_id=post_snapshot_checkpoint_id,
    )


def _make_qos_cos_list_snapshot_check(
    device_name: str,
    cos_list: t.List[ClassOfService],
    interfaces: t.List[str],
    enforce_exclusivity: bool = True,
    pre_snapshot_checkpoint_id: t.Optional[str] = None,
    post_snapshot_checkpoint_id: t.Optional[str] = None,
) -> SnapshotHealthCheck:
    return create_qos_dscp_tx_queue_snapshot_check(
        tx_queue_info_list=[
            hc_types.TxQueueInfo(
                hostname=device_name,
                interface=interface,
                cos_list=[int(cos) for cos in cos_list],
                key_desc="out_bytes.sum",
                val=0,
                comparison=hc_types.ComparisonType.GREATER_THAN,
                enforce_exclusivity=enforce_exclusivity,
            )
            for interface in interfaces
        ],
        pre_snapshot_checkpoint_id=pre_snapshot_checkpoint_id,
        post_snapshot_checkpoint_id=post_snapshot_checkpoint_id,
    )


def _make_qos_queue_desc_snapshot_check(
    device_name: str,
    queue_descs: t.List[str],
    interfaces: t.List[str],
    idle_cos_list: t.Optional[t.List[ClassOfService]] = None,
    pre_snapshot_checkpoint_id: t.Optional[str] = None,
    post_snapshot_checkpoint_id: t.Optional[str] = None,
) -> SnapshotHealthCheck:
    tx_queue_info_list = []
    for interface in interfaces:
        tx_queue_info_list.append(
            hc_types.TxQueueInfo(
                hostname=device_name,
                interface=interface,
                queue_desc_list=queue_descs,
                key_desc="out_bytes.sum",
                val=0,
                comparison=hc_types.ComparisonType.GREATER_THAN,
                enforce_exclusivity=False,
            )
        )
        if idle_cos_list:
            tx_queue_info_list.append(
                hc_types.TxQueueInfo(
                    hostname=device_name,
                    interface=interface,
                    cos_list=[int(cos) for cos in idle_cos_list],
                    key_desc="out_bytes.sum",
                    val=0,
                    comparison=hc_types.ComparisonType.EQUAL_TO,
                    enforce_exclusivity=False,
                )
            )
    return create_qos_dscp_tx_queue_snapshot_check(
        tx_queue_info_list=tx_queue_info_list,
        pre_snapshot_checkpoint_id=pre_snapshot_checkpoint_id,
        post_snapshot_checkpoint_id=post_snapshot_checkpoint_id,
    )


def _burst_packet_count(line_rate_percent: int) -> int:
    return round(
        PORT_SPEED_BITS_PER_SECOND
        * (line_rate_percent / 100)
        * (BURST_DURATION_MS / 1000)
        / (IMIX_MEAN_WIRE_BYTES * 8)
    )


def _make_scheduling_packet_loss_check(
    device_name: str,
) -> PointInTimeHealthCheck:
    """IXIA packet loss health check for scheduling tests."""
    return create_ixia_packet_loss_check(
        thresholds=[
            hc_types.PacketLossThreshold(
                names=[
                    f"{device_name.upper()}_V6_LAYER3_TRAFFIC_DOWNLINK_AND_UPLINK",
                    f"{device_name.upper()}_V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
                    f"{device_name.upper()}_V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
                ],
                str_value="0",
                metric=hc_types.PacketLossMetric.DURATION,
                comparison=hc_types.ComparisonType.EQUAL_TO,
                expect_packet_loss=False,
            ),
        ],
        skip_traffic_items=[
            f"{device_name.upper()}_{traffic}"
            for traffic in DISABLED_AUXILIARY_TRAFFIC_SUFFIXES
        ],
    )


def _make_congestion_packet_loss_check(
    device_name: str,
    congestion_traffic_item_suffix: str,
) -> PointInTimeHealthCheck:
    """IXIA packet loss health check for congestion tests.

    Under strict priority scheduling (NC > ICP > GOLD > SILVER > BRONZE),
    when a higher-priority queue and a lower-priority queue compete for
    the same egress bandwidth:
    - The 3 existing traffic items (higher-priority queue) should see NO loss.
    - The congestion traffic item (lower-priority queue) SHOULD see loss.
    - The lossy NDP traffic items (not started during QoS playbooks) are
      expected to show loss and should not fail the health check.
    """
    return create_ixia_packet_loss_check_traffic_split(
        device_name,
        expect_loss_traffic=[
            congestion_traffic_item_suffix,
        ],
        no_loss_traffic=[
            "V6_LAYER3_TRAFFIC_DOWNLINK_AND_UPLINK",
            "V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
            "V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
        ],
        no_loss_threshold="0",
        no_loss_metric=hc_types.PacketLossMetric.DURATION,
        no_loss_comparison=hc_types.ComparisonType.EQUAL_TO,
        skip_traffic_items=DISABLED_AUXILIARY_TRAFFIC_SUFFIXES,
    )


# ---------------------------------------------------------------------------
# Helpers to build INVOKE_IXIA_API_STEP steps for traffic control
# ---------------------------------------------------------------------------
def _ixia_enable_traffic_step(
    regexes: t.Optional[t.List[str]],
    enable: bool = True,
    step_id: t.Optional[str] = None,
) -> Step:
    """Build an INVOKE_IXIA_API_STEP that calls ixia.enable_traffic()."""
    args: t.Dict[str, t.Any] = {"enable": enable}
    if regexes is not None:
        args["regexes"] = regexes
    return create_ixia_api_step(
        api_name="enable_traffic",
        args_dict=args,
        description=step_id,
        start_traffic=False,
    )


def _ixia_regenerate_and_apply_step(
    step_id: t.Optional[str] = None,
) -> Step:
    """Build an INVOKE_IXIA_API_STEP that regenerates and applies traffic."""
    return create_ixia_api_step(
        api_name="regenerate_traffic_items",
        args_dict={},
        description=step_id,
        start_traffic=False,
    )


def _ixia_apply_traffic_step(
    step_id: t.Optional[str] = None,
) -> Step:
    return create_ixia_api_step(
        api_name="apply_traffic",
        args_dict={},
        description=step_id,
        start_traffic=False,
    )


def _ixia_clear_traffic_stats_step(
    step_id: t.Optional[str] = None,
) -> Step:
    return create_ixia_api_step(
        api_name="clear_traffic_stats",
        args_dict={},
        description=step_id,
        start_traffic=False,
    )


def _ixia_stop_traffic_step(
    step_id: t.Optional[str] = None,
) -> Step:
    """Build an INVOKE_IXIA_API_STEP that stops the traffic engine."""
    return create_ixia_api_step(
        api_name="stop_traffic",
        args_dict={},
        description=step_id,
        start_traffic=False,
    )


def _ixia_start_traffic_step(
    step_id: t.Optional[str] = None,
) -> Step:
    """Build an INVOKE_IXIA_API_STEP that starts the traffic engine."""
    return create_ixia_api_step(
        api_name="start_traffic",
        args_dict={},
        description=step_id,
        start_traffic=False,
    )


def _ixia_start_traffic_items_step(
    traffic_item_regex: str,
    step_id: t.Optional[str] = None,
) -> Step:
    return create_ixia_api_step(
        api_name="start_traffic_items",
        args_dict={"traffic_item_regex": traffic_item_regex},
        description=step_id,
        start_traffic=False,
    )


def _ixia_set_burst_step(
    traffic_item_regex: str,
    line_rate_percent: int,
    step_id: t.Optional[str] = None,
) -> Step:
    return create_ixia_api_step(
        api_name="set_transmission_control",
        args_dict={
            "traffic_item_regex": traffic_item_regex,
            "transmission_type": "burstFixedDuration",
            "duration": LONGEVITY_DURATION_S,
            "burst_packet_count": _burst_packet_count(line_rate_percent),
            "inter_burst_gap_ms": BURST_INTER_GAP_MS,
            "repeat_burst_count": BURST_REPEAT_COUNT,
            "transmit_mode": "sequential",
        },
        description=step_id,
        start_traffic=False,
    )


def _ixia_set_continuous_step(
    traffic_item_regex: str,
    step_id: t.Optional[str] = None,
) -> Step:
    return create_ixia_api_step(
        api_name="set_transmission_control",
        args_dict={
            "traffic_item_regex": traffic_item_regex,
            "transmission_type": "continuous",
            "transmit_mode": "interleaved",
        },
        description=step_id,
        start_traffic=False,
    )


def _exact_traffic_item_regexes(names: t.Iterable[str]) -> t.List[str]:
    return [rf"^{re.escape(name)}$" for name in names]


def _combined_exact_traffic_item_regex(names: t.Iterable[str]) -> str:
    escaped_names = [re.escape(name) for name in names]
    if not escaped_names:
        raise ValueError("At least one traffic item name is required")
    return rf"^(?:{'|'.join(escaped_names)})$"


def _stop_and_validate_traffic_steps(
    packet_loss_check: PointInTimeHealthCheck,
    phase: str,
) -> t.List[Step]:
    return [
        _ixia_stop_traffic_step(step_id=f"stop_for_{phase}_validation"),
        create_validation_step(
            point_in_time_checks=[packet_loss_check],
            description=f"validate_{phase}_traffic",
            start_traffic=False,
        ),
    ]


def _ixia_api_name(step: Step) -> t.Optional[str]:
    if step.name != StepName.INVOKE_IXIA_API_STEP or step.step_params is None:
        return None
    return json.loads(step.step_params.json_params or "{}").get("api_name")


def _add_phase_packet_loss_validation(
    stage: taac_types.Stage,
    packet_loss_check: PointInTimeHealthCheck,
) -> taac_types.Stage:
    steps = list(stage.steps or [])
    if any(step.name == StepName.VALIDATION_STEP for step in steps):
        return stage
    stage_id = stage.id or "unnamed_stage"

    if "warmboot" in stage_id:
        steps = [
            step for step in steps if _ixia_api_name(step) != "clear_traffic_stats"
        ]
        interruption_index = next(
            index
            for index, step in enumerate(steps)
            if step.name == StepName.SERVICE_INTERRUPTION_STEP
        )
        steps[interruption_index:interruption_index] = [
            _ixia_start_traffic_step(step_id="start_warmboot_traffic"),
            _ixia_clear_traffic_stats_step(step_id="clear_stats_before_warmboot"),
        ]
    elif "reverse" in stage_id:
        steps = [
            step for step in steps if _ixia_api_name(step) != "clear_traffic_stats"
        ]
        first_start_index = next(
            index
            for index, step in enumerate(steps)
            if _ixia_api_name(step) in {"start_traffic", "start_traffic_items"}
        )
        steps.insert(
            first_start_index,
            _ixia_clear_traffic_stats_step(step_id="clear_stats_before_reverse"),
        )
    else:
        steps = [
            step for step in steps if _ixia_api_name(step) != "clear_traffic_stats"
        ]
        longevity_index = next(
            index
            for index, step in enumerate(steps)
            if step.name == StepName.LONGEVITY_STEP
        )
        steps.insert(
            longevity_index,
            _ixia_clear_traffic_stats_step(step_id="clear_stats_before_measurement"),
        )

    steps.extend(_stop_and_validate_traffic_steps(packet_loss_check, stage_id))
    return stage(steps=steps)


# ---------------------------------------------------------------------------
# Existing QoS scheduling playbook (single-queue DSCP validation)
# ---------------------------------------------------------------------------
def _create_qos_scheduling_playbook(
    device_name: str,
    cos: ClassOfService,
    dscp_value: int,
    queue_desc: str,
    interfaces: t.List[str],
    ixia_downlink_interface: str,
    ixia_uplink_interface: str,
    frame_size: t.Optional[ixia_types.FrameSize] = None,
) -> Playbook:
    """
    Creates a playbook that:
    1. Reconfigures all three bidirectional traffic items
       (V6_LAYER3, V6_DIRECTIONAL, V4_DIRECTIONAL) on the fly to use the
       same DSCP value (via QoSConfig) and custom IMIX frame size.
       Each item is set to 33% linerate so the cumulative traffic from
       any IXIA source port totals 99% (3 items × 33%).
    2. Runs a longevity step to let traffic flow.
    3. Validates via SnapshotHealthCheck (QOS_DSCP_TX_QUEUE_CHECK) that traffic
       egressed through the correct queue, with enforce_exclusivity ensuring no
       other queues saw the traffic.
    4. Validates buffer utilization on the egress interfaces where DSCP-marked
       traffic exits the DUT.
    5. Validates stable-state IXIA packet loss health check.

    Note: Tracking is already configured on the base traffic items
    via BasicTrafficItemConfig.tracking_types=[TRAFFIC_ITEM] in the hardening
    helper. TrafficItemSettings (used by traffic_items_to_configure) does not
    have a tracking_types field, so tracking is inherited from the base config.
    """
    playbook_name = COS_TO_SCHEDULING_PLAYBOOK[cos].name

    # 33 + 33 + 34 = 100% linerate cumulative per IXIA source port.
    # Same frame size applied uniformly across all items.
    #
    # QoS/DSCP note: The IXIA packet header stack exposes the DSCP field
    # under different PHB type names depending on the IP version:
    #   - IPv6 items → PHBTypes.TRAFFIC_CLASS  (field "Traffic Class")
    #   - IPv4 items → PHBTypes.DEFAULT         (field "Default PHB")
    # Using the wrong PHB type causes an IndexError because the field
    # lookup returns empty.
    resolved_frame_size = frame_size if frame_size else DEFAULT_FRAME_SIZE

    ipv6_qos_config = ixia_types.QoSConfig(
        phb_type=ixia_types.PHBTypes.TRAFFIC_CLASS,
        dscp_value=dscp_value,
        ecn_capability=ixia_types.EcnCapability.ECN_CAPABLE,
    )
    ipv4_qos_config = ixia_types.QoSConfig(
        phb_type=ixia_types.PHBTypes.DEFAULT,
        dscp_value=dscp_value,
        ecn_capability=ixia_types.EcnCapability.ECN_CAPABLE,
    )

    v6_layer3_name = f"{device_name.upper()}_V6_LAYER3_TRAFFIC_DOWNLINK_AND_UPLINK"
    v6_directional_name = (
        f"{device_name.upper()}_V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK"
    )
    v4_directional_name = (
        f"{device_name.upper()}_V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK"
    )

    traffic_items_to_configure = {
        v6_layer3_name: taac_types.TrafficItemSettings(
            line_rate=33,
            qos_config=ipv6_qos_config,
            frame_size_settings=resolved_frame_size,
        ),
        v6_directional_name: taac_types.TrafficItemSettings(
            line_rate=33,
            qos_config=ipv6_qos_config,
            frame_size_settings=resolved_frame_size,
        ),
        v4_directional_name: taac_types.TrafficItemSettings(
            line_rate=34,
            qos_config=ipv4_qos_config,
            frame_size_settings=resolved_frame_size,
        ),
    }

    # Stage 1: Continuous traffic — let QoS traffic flow and establish baseline.
    continuous_longevity_stage = create_steps_stage(
        stage_id="qos_continuous_longevity",
        steps=[
            create_longevity_step(
                duration=LONGEVITY_DURATION_S, step_id="continuous_longevity"
            ),
        ],
    )

    # Stage 2: Reconfigure every preserved flow for repeating 30 ms bursts.
    burst_longevity_stage = create_steps_stage(
        stage_id="qos_burst_longevity",
        steps=[
            _ixia_stop_traffic_step(step_id="stop_for_burst"),
            _ixia_set_burst_step(v6_layer3_name, 33, "burst_v6_layer3"),
            _ixia_set_burst_step(v6_directional_name, 33, "burst_v6_directional"),
            _ixia_set_burst_step(v4_directional_name, 34, "burst_v4_directional"),
            _ixia_regenerate_and_apply_step(step_id="regenerate_burst_traffic"),
            _ixia_clear_traffic_stats_step(step_id="clear_stats_for_burst"),
            _ixia_start_traffic_step(step_id="start_burst_traffic"),
            create_longevity_step(
                duration=LONGEVITY_DURATION_S, step_id="burst_longevity"
            ),
        ],
    )

    # Snapshot health checks:
    # QoS check over the continuous longevity period.
    snapshot_checks = [
        _make_qos_snapshot_check(
            device_name=device_name,
            cos=cos,
            interfaces=interfaces,
            pre_snapshot_checkpoint_id="stage.qos_continuous_longevity.step.continuous_longevity.start",
            post_snapshot_checkpoint_id="stage.qos_continuous_longevity.step.continuous_longevity.end",
        ),
    ]

    # Buffer utilization check on the DUT egress interfaces where DSCP-marked
    # traffic exits.  All three traffic items are bidirectional:
    #   - Forward:  uplink → DUT → downlink  (egress on ixia_downlink_interface)
    #   - Reverse:  downlink → DUT → uplink  (egress on ixia_uplink_interface)
    # So both downlink and uplink DUT interfaces are destination/egress ports
    # for the DSCP-marked packets and must be checked.
    egress_interfaces = [ixia_downlink_interface, ixia_uplink_interface]
    snapshot_checks.append(
        _make_buffer_utilization_check(
            device_name=device_name,
            active_cos_list=[cos],
            interfaces=egress_interfaces,
            active_queue_max_bytes=ACTIVE_QUEUE_BUFFER_MAX_BYTES,
            other_queue_max_bytes=OTHER_QUEUE_BUFFER_MAX_BYTES,
            pre_snapshot_checkpoint_id="stage.qos_continuous_longevity.step.continuous_longevity.start",
            post_snapshot_checkpoint_id="stage.qos_continuous_longevity.step.continuous_longevity.end",
        ),
    )

    # Burst phase snapshot checks (same thresholds, different checkpoint IDs).
    snapshot_checks.append(
        _make_qos_snapshot_check(
            device_name=device_name,
            cos=cos,
            interfaces=interfaces,
            pre_snapshot_checkpoint_id="stage.qos_burst_longevity.step.burst_longevity.start",
            post_snapshot_checkpoint_id="stage.qos_burst_longevity.step.burst_longevity.end",
        ),
    )
    snapshot_checks.append(
        _make_buffer_utilization_check(
            device_name=device_name,
            active_cos_list=[cos],
            interfaces=egress_interfaces,
            active_queue_max_bytes=ACTIVE_QUEUE_BUFFER_MAX_BYTES,
            other_queue_max_bytes=OTHER_QUEUE_BUFFER_MAX_BYTES,
            pre_snapshot_checkpoint_id="stage.qos_burst_longevity.step.burst_longevity.start",
            post_snapshot_checkpoint_id="stage.qos_burst_longevity.step.burst_longevity.end",
        ),
    )

    return build_qos_scheduling_playbook(
        name=playbook_name,
        traffic_items_to_configure=traffic_items_to_configure,
        traffic_items_to_start=[
            f"(?!{device_name.upper()}_HIGH_QUEUE_BGP_CP_TRAFFIC)"
            f"(?!{device_name.upper()}_GOOD_BUT_LOSSY_NDP_TRAFFIC)"
            f"(?!{device_name.upper()}_LOSSY_ROGUE_NDP_TRAFFIC)"
            f"(?!{device_name.upper()}_{CONGESTION_TRAFFIC_ITEM_SUFFIX})",
        ],
        postchecks=[
            _make_scheduling_packet_loss_check(device_name),
        ],
        snapshot_checks=snapshot_checks,
        stages=[
            continuous_longevity_stage,
            burst_longevity_stage,
        ],
        cleanup_steps=[
            _ixia_stop_traffic_step(step_id="cleanup_stop_after_burst"),
            _ixia_set_continuous_step(v6_layer3_name, "restore_v6_layer3"),
            _ixia_set_continuous_step(v6_directional_name, "restore_v6_directional"),
            _ixia_set_continuous_step(v4_directional_name, "restore_v4_directional"),
        ],
    )


# ---------------------------------------------------------------------------
# Congestion QoS scheduling playbook (two-queue priority validation)
# ---------------------------------------------------------------------------
def _create_qos_congestion_playbook(
    device_name: str,
    priority_cos: ClassOfService,
    congested_cos: ClassOfService,
    ixia_downlink_interface: str,
    frame_size: t.Optional[ixia_types.FrameSize] = None,
) -> Playbook:
    """
    Creates a playbook that validates QoS scheduling priority between two
    queues under congestion.

    The test scenario:
    1. Configure the 3 existing bidirectional traffic items to send on the
       *priority* queue (e.g. NC) at 33% linerate each (99% total).
    2. Configure the congestion traffic item to send on the *congested*
       queue (e.g. ICP) at 30% linerate from the dedicated congestion port.
    3. Run the continuous congestion phase for the catalog duration.
    4. Health checks validate:
       - Priority queue traffic items see NO packet loss.
       - Congested queue traffic item sees packet loss (expected due to
         oversubscription).
    """
    priority_dscp = COS_DSCP_VALUES[priority_cos]
    congested_dscp = COS_DSCP_VALUES[congested_cos]

    playbook_name = COS_PAIR_TO_CONGESTION_PLAYBOOK[(priority_cos, congested_cos)].name

    resolved_frame_size = frame_size if frame_size else DEFAULT_FRAME_SIZE

    # QoS configs for the priority queue (existing 3 items).
    ipv6_priority_qos = ixia_types.QoSConfig(
        phb_type=ixia_types.PHBTypes.TRAFFIC_CLASS,
        dscp_value=priority_dscp,
        ecn_capability=ixia_types.EcnCapability.ECN_CAPABLE,
    )
    ipv4_priority_qos = ixia_types.QoSConfig(
        phb_type=ixia_types.PHBTypes.DEFAULT,
        dscp_value=priority_dscp,
        ecn_capability=ixia_types.EcnCapability.ECN_CAPABLE,
    )

    # QoS config for the congestion traffic item (IPv6 only — new port).
    congestion_qos = ixia_types.QoSConfig(
        phb_type=ixia_types.PHBTypes.TRAFFIC_CLASS,
        dscp_value=congested_dscp,
        ecn_capability=ixia_types.EcnCapability.ECN_CAPABLE,
    )

    v6_layer3_name = f"{device_name.upper()}_V6_LAYER3_TRAFFIC_DOWNLINK_AND_UPLINK"
    v6_directional_name = (
        f"{device_name.upper()}_V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK"
    )
    v4_directional_name = (
        f"{device_name.upper()}_V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK"
    )
    congestion_name = f"{device_name.upper()}_{CONGESTION_TRAFFIC_ITEM_SUFFIX}"

    # Configure all 4 traffic items: 3 existing + 1 congestion.
    # Priority items: 25+25+25 = 75% total linerate.
    # Congestion item: 50% linerate from the dedicated congestion port.
    traffic_items_to_configure = {
        v6_layer3_name: taac_types.TrafficItemSettings(
            line_rate=25,
            qos_config=ipv6_priority_qos,
            frame_size_settings=resolved_frame_size,
        ),
        v6_directional_name: taac_types.TrafficItemSettings(
            line_rate=25,
            qos_config=ipv6_priority_qos,
            frame_size_settings=resolved_frame_size,
        ),
        v4_directional_name: taac_types.TrafficItemSettings(
            line_rate=25,
            qos_config=ipv4_priority_qos,
            frame_size_settings=resolved_frame_size,
        ),
        congestion_name: taac_types.TrafficItemSettings(
            line_rate=50,
            qos_config=congestion_qos,
            frame_size_settings=resolved_frame_size,
        ),
    }

    target_traffic_regexes = _exact_traffic_item_regexes(
        traffic_items_to_configure.keys()
    )
    congestion_item_regex = _exact_traffic_item_regexes([congestion_name])[0]

    # Stage 1: Stop the traffic engine so we can reconfigure items, then
    # enable all four items (existing + congestion), apply, start, and
    # let traffic run.  IxNetwork requires the traffic engine to be
    # stopped before Traffic.Apply() can succeed.
    congestion_stage = create_steps_stage(
        stage_id="qos_congestion_traffic",
        steps=[
            # 1. Stop the traffic engine (traffic_items_to_start started it).
            _ixia_stop_traffic_step(step_id="stop_traffic_engine"),
            _ixia_enable_traffic_step(
                regexes=target_traffic_regexes,
                enable=True,
                step_id="select_test_traffic",
            ),
            # 3. Regenerate and apply the traffic configuration.
            _ixia_regenerate_and_apply_step(step_id="regenerate_traffic"),
            _ixia_apply_traffic_step(step_id="apply_traffic"),
            # 4. Start the traffic engine.
            _ixia_start_traffic_step(step_id="start_traffic_engine"),
            # 5. Clear stats so health checks measure from this point.
            _ixia_clear_traffic_stats_step(step_id="clear_stats"),
            # 6. Let traffic run under congestion.
            create_longevity_step(
                duration=LONGEVITY_DURATION_S, step_id="congestion_longevity"
            ),
        ],
    )

    # IXIA packet loss health check: validates strict priority scheduling.
    # - The 3 existing items (priority queue) should see NO packet loss.
    # - The congestion item (lower-priority queue) SHOULD see loss.
    congestion_packet_loss_check = _make_congestion_packet_loss_check(
        device_name=device_name,
        congestion_traffic_item_suffix=CONGESTION_TRAFFIC_ITEM_SUFFIX,
    )
    # Buffer utilization snapshot checks on the congested egress port.
    # Congestion traffic flows from the congestion IXIA port → DUT →
    # downlink IXIA port, so the congested egress interface is ixia_downlink_interface.
    # The congested queue is expected to use buffer; all others should not.
    idle_cos_list = [
        cos for cos in COS_PRIORITY_ORDER if cos not in {priority_cos, congested_cos}
    ]
    snapshot_checks = [
        _make_qos_cos_list_snapshot_check(
            device_name=device_name,
            cos_list=[priority_cos, congested_cos],
            interfaces=[ixia_downlink_interface],
            pre_snapshot_checkpoint_id="stage.qos_congestion_traffic.step.congestion_longevity.start",
            post_snapshot_checkpoint_id="stage.qos_congestion_traffic.step.congestion_longevity.end",
        ),
        _make_buffer_utilization_check(
            device_name=device_name,
            active_cos_list=[congested_cos],
            interfaces=[ixia_downlink_interface],
            active_queue_max_bytes=CONTINUOUS_CONGESTED_QUEUE_BUFFER_MAX_BYTES,
            other_queue_max_bytes=OTHER_QUEUE_BOUND_DELEGATED_BYTES,
            pre_snapshot_checkpoint_id="stage.qos_congestion_traffic.step.congestion_longevity.start",
            post_snapshot_checkpoint_id="stage.qos_congestion_traffic.step.congestion_longevity.end",
        ),
        _make_buffer_utilization_check(
            device_name=device_name,
            active_cos_list=[priority_cos],
            interfaces=[ixia_downlink_interface],
            active_queue_max_bytes=PRIORITY_QUEUE_BUFFER_MAX_BYTES,
            other_queue_max_bytes=OTHER_QUEUE_BOUND_DELEGATED_BYTES,
            pre_snapshot_checkpoint_id="stage.qos_congestion_traffic.step.congestion_longevity.start",
            post_snapshot_checkpoint_id="stage.qos_congestion_traffic.step.congestion_longevity.end",
        ),
        _make_buffer_utilization_check(
            device_name=device_name,
            active_cos_list=idle_cos_list,
            interfaces=[ixia_downlink_interface],
            active_queue_max_bytes=CONTINUOUS_OTHER_QUEUE_BUFFER_MAX_BYTES,
            other_queue_max_bytes=OTHER_QUEUE_BOUND_DELEGATED_BYTES,
            pre_snapshot_checkpoint_id="stage.qos_congestion_traffic.step.congestion_longevity.start",
            post_snapshot_checkpoint_id="stage.qos_congestion_traffic.step.congestion_longevity.end",
        ),
    ]

    # Cleanup: stop the congestion traffic item after the test.
    cleanup_steps = [
        _ixia_enable_traffic_step(
            regexes=[congestion_item_regex],
            enable=False,
            step_id="cleanup_stop_congestion_traffic",
        ),
    ]

    return build_qos_scheduling_playbook(
        name=playbook_name,
        traffic_items_to_configure=traffic_items_to_configure,
        # Start only the existing items in setUp; congestion item is
        # controlled within the stage steps.
        traffic_items_to_start=[
            f"(?!{device_name.upper()}_HIGH_QUEUE_BGP_CP_TRAFFIC)"
            f"(?!{device_name.upper()}_GOOD_BUT_LOSSY_NDP_TRAFFIC)"
            f"(?!{device_name.upper()}_LOSSY_ROGUE_NDP_TRAFFIC)"
            f"(?!{device_name.upper()}_{CONGESTION_TRAFFIC_ITEM_SUFFIX})",
        ],
        postchecks=[congestion_packet_loss_check],
        snapshot_checks=snapshot_checks,
        stages=[congestion_stage],
        cleanup_steps=cleanup_steps,
    )


def _create_ncnf_scheduling_playbook(
    device_name: str,
    interfaces: t.List[str],
    ixia_downlink_interface: str,
    ixia_uplink_interface: str,
    frame_size: t.Optional[ixia_types.FrameSize] = None,
) -> Playbook:
    """
    Creates a scheduling playbook for the NCNF queue (queue0, DSCP 51).

    NCNF is not yet a first-class ClassOfService enum value, so this
    function uses the standalone NCNF_DSCP_VALUE and NCNF_QUEUE_DESC
    constants instead of the COS_DSCP_VALUES/COS_QUEUE_DESC dicts.

    TODO(harshalsh): Once NCNF is added to the ClassOfService enum,
    merge this into _create_qos_scheduling_playbook and add QoS/buffer
    snapshot health checks.
    """
    playbook_name = TEST_QOS_SCHEDULING_QUEUE0_NCNF.name
    resolved_frame_size = frame_size if frame_size else DEFAULT_FRAME_SIZE

    ipv6_qos_config = ixia_types.QoSConfig(
        phb_type=ixia_types.PHBTypes.TRAFFIC_CLASS,
        dscp_value=NCNF_DSCP_VALUE,
        ecn_capability=ixia_types.EcnCapability.ECN_CAPABLE,
    )
    ipv4_qos_config = ixia_types.QoSConfig(
        phb_type=ixia_types.PHBTypes.DEFAULT,
        dscp_value=NCNF_DSCP_VALUE,
        ecn_capability=ixia_types.EcnCapability.ECN_CAPABLE,
    )

    v6_layer3_name = f"{device_name.upper()}_V6_LAYER3_TRAFFIC_DOWNLINK_AND_UPLINK"
    v6_directional_name = (
        f"{device_name.upper()}_V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK"
    )
    v4_directional_name = (
        f"{device_name.upper()}_V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK"
    )

    traffic_items_to_configure = {
        v6_layer3_name: taac_types.TrafficItemSettings(
            line_rate=33,
            qos_config=ipv6_qos_config,
            frame_size_settings=resolved_frame_size,
        ),
        v6_directional_name: taac_types.TrafficItemSettings(
            line_rate=33,
            qos_config=ipv6_qos_config,
            frame_size_settings=resolved_frame_size,
        ),
        v4_directional_name: taac_types.TrafficItemSettings(
            line_rate=34,
            qos_config=ipv4_qos_config,
            frame_size_settings=resolved_frame_size,
        ),
    }

    continuous_longevity_stage = create_steps_stage(
        stage_id="qos_continuous_longevity",
        steps=[
            create_longevity_step(
                duration=LONGEVITY_DURATION_S, step_id="continuous_longevity"
            ),
        ],
    )

    burst_longevity_stage = create_steps_stage(
        stage_id="qos_burst_longevity",
        steps=[
            _ixia_stop_traffic_step(step_id="stop_for_burst"),
            _ixia_set_burst_step(v6_layer3_name, 33, "burst_v6_layer3"),
            _ixia_set_burst_step(v6_directional_name, 33, "burst_v6_directional"),
            _ixia_set_burst_step(v4_directional_name, 34, "burst_v4_directional"),
            _ixia_regenerate_and_apply_step(step_id="regenerate_burst_traffic"),
            _ixia_clear_traffic_stats_step(step_id="clear_stats_for_burst"),
            _ixia_start_traffic_step(step_id="start_burst_traffic"),
            create_longevity_step(
                duration=LONGEVITY_DURATION_S, step_id="burst_longevity"
            ),
        ],
    )

    egress_interfaces = [ixia_downlink_interface, ixia_uplink_interface]
    snapshot_checks = []
    for stage_id, step_id in (
        ("qos_continuous_longevity", "continuous_longevity"),
        ("qos_burst_longevity", "burst_longevity"),
    ):
        pre_checkpoint = f"stage.{stage_id}.step.{step_id}.start"
        post_checkpoint = f"stage.{stage_id}.step.{step_id}.end"
        snapshot_checks.extend(
            [
                _make_qos_queue_desc_snapshot_check(
                    device_name=device_name,
                    queue_descs=[NCNF_QUEUE_DESC],
                    idle_cos_list=list(COS_DSCP_VALUES),
                    interfaces=egress_interfaces,
                    pre_snapshot_checkpoint_id=pre_checkpoint,
                    post_snapshot_checkpoint_id=post_checkpoint,
                ),
                _make_buffer_utilization_check(
                    device_name=device_name,
                    active_cos_list=[],
                    active_queue_desc_list=[NCNF_QUEUE_DESC],
                    interfaces=egress_interfaces,
                    active_queue_max_bytes=ACTIVE_QUEUE_BUFFER_MAX_BYTES,
                    other_queue_max_bytes=OTHER_QUEUE_BUFFER_MAX_BYTES,
                    pre_snapshot_checkpoint_id=pre_checkpoint,
                    post_snapshot_checkpoint_id=post_checkpoint,
                ),
            ]
        )

    return build_qos_scheduling_playbook(
        name=playbook_name,
        traffic_items_to_configure=traffic_items_to_configure,
        traffic_items_to_start=[
            f"(?!{device_name.upper()}_HIGH_QUEUE_BGP_CP_TRAFFIC)"
            f"(?!{device_name.upper()}_GOOD_BUT_LOSSY_NDP_TRAFFIC)"
            f"(?!{device_name.upper()}_LOSSY_ROGUE_NDP_TRAFFIC)"
            f"(?!{device_name.upper()}_{CONGESTION_TRAFFIC_ITEM_SUFFIX})",
        ],
        postchecks=[
            _make_scheduling_packet_loss_check(device_name),
        ],
        snapshot_checks=snapshot_checks,
        stages=[
            continuous_longevity_stage,
            burst_longevity_stage,
        ],
        cleanup_steps=[
            _ixia_stop_traffic_step(step_id="cleanup_stop_after_burst"),
            _ixia_set_continuous_step(v6_layer3_name, "restore_v6_layer3"),
            _ixia_set_continuous_step(v6_directional_name, "restore_v6_directional"),
            _ixia_set_continuous_step(v4_directional_name, "restore_v4_directional"),
        ],
    )


def get_qos_scheduling_playbooks(
    device_name: str,
    ixia_downlink_interface: str,
    ixia_uplink_interface: str,
    frame_size: t.Optional[ixia_types.FrameSize] = None,
) -> t.List[Playbook]:
    """
    Generates one playbook per ClassOfService that:
    - Sets the DSCP on V6_LAYER3_TRAFFIC_DOWNLINK_AND_UPLINK via
      traffic_items_to_configure with QoSConfig.
    - Configures the frame size for the traffic item (defaults to CUSTOM_IMIX).
    - Validates that traffic egressed through the expected queue using
      qos_dscp_tx_queue_health_check.

    The QoS health check uses fb303 counters keyed by interface name
    (e.g. eth7/16/1.queue1.bronze.out_bytes.sum.60), so we check on
    both the downlink and uplink interfaces since the V6_LAYER3 traffic
    item is bidirectional.

    Queue mapping:
        BRONZE → queue1.bronze  (DSCP 10)
        SILVER → queue2.silver  (DSCP 9)
        GOLD   → queue3.gold    (DSCP 18)
        ICP    → queue6.icp     (DSCP 35)
        NC     → queue7.nc      (DSCP 48)
    """
    interfaces = [ixia_downlink_interface, ixia_uplink_interface]
    playbooks = []
    for cos, dscp_value in COS_DSCP_VALUES.items():
        queue_desc = COS_QUEUE_DESC[cos]
        playbooks.append(
            _create_qos_scheduling_playbook(
                device_name=device_name,
                cos=cos,
                dscp_value=dscp_value,
                queue_desc=queue_desc,
                interfaces=interfaces,
                ixia_downlink_interface=ixia_downlink_interface,
                ixia_uplink_interface=ixia_uplink_interface,
                frame_size=frame_size,
            )
        )

    # NCNF is not a ClassOfService enum value, so generate its playbook
    # separately using the standalone DSCP/queue constants.
    playbooks.append(
        _create_ncnf_scheduling_playbook(
            device_name=device_name,
            interfaces=interfaces,
            ixia_downlink_interface=ixia_downlink_interface,
            ixia_uplink_interface=ixia_uplink_interface,
            frame_size=frame_size,
        )
    )
    return playbooks


def get_qos_congestion_playbooks(
    device_name: str,
    ixia_downlink_interface: str,
    ixia_uplink_interface: str,
    frame_size: t.Optional[ixia_types.FrameSize] = None,
) -> t.List[Playbook]:
    """
    Generates congestion playbooks for every valid pair of
    (priority_cos, congested_cos) where priority_cos has strictly higher
    scheduling priority than congested_cos.

    Test matrix (10 pairs):
        NC  vs ICP, NC  vs GOLD, NC  vs SILVER, NC  vs BRONZE
        ICP vs GOLD, ICP vs SILVER, ICP vs BRONZE
        GOLD vs SILVER, GOLD vs BRONZE
        SILVER vs BRONZE
    """
    playbooks = []
    for i, priority_cos in enumerate(COS_PRIORITY_ORDER):
        for congested_cos in COS_PRIORITY_ORDER[i + 1 :]:
            playbooks.append(
                _create_qos_congestion_playbook(
                    device_name=device_name,
                    priority_cos=priority_cos,
                    congested_cos=congested_cos,
                    ixia_downlink_interface=ixia_downlink_interface,
                    frame_size=frame_size,
                )
            )
    return playbooks


# ---------------------------------------------------------------------------
# Per-queue congestion playbook (same DSCP on both ingress ports)
# ---------------------------------------------------------------------------
def _create_qos_per_queue_congestion_playbook(
    device_name: str,
    cos: ClassOfService,
    ixia_downlink_interface: str,
    frame_size: t.Optional[ixia_types.FrameSize] = None,
) -> Playbook:
    """
    Creates a playbook that validates per-queue congestion behavior when
    2 ingress ports send traffic with the same DSCP marking toward a
    single egress port, oversubscribing a single queue.

    Port 1 (3 existing bidirectional items): 75% total (25+25+25)
    Port 2 (congestion item): 50%
    Total: 125% on the target queue. Loss expected on all items since
    they share the same oversubscribed queue.
    """
    dscp = COS_DSCP_VALUES[cos]
    playbook_name = COS_TO_PER_QUEUE_CONGESTION_PLAYBOOK[cos].name

    resolved_frame_size = frame_size if frame_size else DEFAULT_FRAME_SIZE

    # All items use the same DSCP — same queue, same priority.
    ipv6_qos = ixia_types.QoSConfig(
        phb_type=ixia_types.PHBTypes.TRAFFIC_CLASS,
        dscp_value=dscp,
        ecn_capability=ixia_types.EcnCapability.ECN_CAPABLE,
    )
    ipv4_qos = ixia_types.QoSConfig(
        phb_type=ixia_types.PHBTypes.DEFAULT,
        dscp_value=dscp,
        ecn_capability=ixia_types.EcnCapability.ECN_CAPABLE,
    )

    v6_layer3_name = f"{device_name.upper()}_V6_LAYER3_TRAFFIC_DOWNLINK_AND_UPLINK"
    v6_directional_name = (
        f"{device_name.upper()}_V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK"
    )
    v4_directional_name = (
        f"{device_name.upper()}_V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK"
    )
    congestion_name = f"{device_name.upper()}_{CONGESTION_TRAFFIC_ITEM_SUFFIX}"

    # 25+25+25 = 75% from port 1, 50% from port 2 = 125% total.
    traffic_items_to_configure = {
        v6_layer3_name: taac_types.TrafficItemSettings(
            line_rate=25,
            qos_config=ipv6_qos,
            frame_size_settings=resolved_frame_size,
        ),
        v6_directional_name: taac_types.TrafficItemSettings(
            line_rate=25,
            qos_config=ipv6_qos,
            frame_size_settings=resolved_frame_size,
        ),
        v4_directional_name: taac_types.TrafficItemSettings(
            line_rate=25,
            qos_config=ipv4_qos,
            frame_size_settings=resolved_frame_size,
        ),
        congestion_name: taac_types.TrafficItemSettings(
            line_rate=50,
            qos_config=ipv6_qos,
            frame_size_settings=resolved_frame_size,
        ),
    }

    target_traffic_regexes = _exact_traffic_item_regexes(
        traffic_items_to_configure.keys()
    )
    congestion_item_regex = _exact_traffic_item_regexes([congestion_name])[0]

    # Stage 1: Stop traffic, enable all items, start, longevity.
    congestion_stage = create_steps_stage(
        stage_id="qos_per_queue_congestion_traffic",
        steps=[
            _ixia_stop_traffic_step(step_id="stop_traffic_engine"),
            _ixia_enable_traffic_step(
                regexes=target_traffic_regexes,
                enable=True,
                step_id="select_test_traffic",
            ),
            _ixia_regenerate_and_apply_step(step_id="regenerate_traffic"),
            _ixia_apply_traffic_step(step_id="apply_traffic"),
            _ixia_start_traffic_step(step_id="start_traffic_engine"),
            _ixia_clear_traffic_stats_step(step_id="clear_stats"),
            create_longevity_step(
                duration=LONGEVITY_DURATION_S, step_id="congestion_longevity"
            ),
        ],
    )

    # All items share the same queue — all expect loss under oversubscription.
    def _make_loss_check() -> PointInTimeHealthCheck:
        return create_ixia_packet_loss_check_traffic_split(
            device_name,
            expect_loss_traffic=[
                CONGESTION_TRAFFIC_ITEM_SUFFIX,
                "V6_LAYER3_TRAFFIC_DOWNLINK_AND_UPLINK",
                "V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
                "V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
            ],
            no_loss_traffic=[],
            skip_traffic_items=DISABLED_AUXILIARY_TRAFFIC_SUFFIXES,
        )

    # Buffer utilization: congested queue may use buffer, all others should not.
    snapshot_checks = [
        _make_qos_snapshot_check(
            device_name=device_name,
            cos=cos,
            interfaces=[ixia_downlink_interface],
            pre_snapshot_checkpoint_id="stage.qos_per_queue_congestion_traffic.step.congestion_longevity.start",
            post_snapshot_checkpoint_id="stage.qos_per_queue_congestion_traffic.step.congestion_longevity.end",
        ),
        _make_buffer_utilization_check(
            device_name=device_name,
            active_cos_list=[cos],
            interfaces=[ixia_downlink_interface],
            active_queue_max_bytes=CONTINUOUS_CONGESTED_QUEUE_BUFFER_MAX_BYTES,
            other_queue_max_bytes=CONTINUOUS_OTHER_QUEUE_BUFFER_MAX_BYTES,
            pre_snapshot_checkpoint_id="stage.qos_per_queue_congestion_traffic.step.congestion_longevity.start",
            post_snapshot_checkpoint_id="stage.qos_per_queue_congestion_traffic.step.congestion_longevity.end",
        ),
    ]

    # Cleanup: disable the congestion traffic item.
    cleanup_steps = [
        _ixia_enable_traffic_step(
            regexes=[congestion_item_regex],
            enable=False,
            step_id="cleanup_stop_congestion_traffic",
        ),
    ]

    return build_qos_scheduling_playbook(
        name=playbook_name,
        traffic_items_to_configure=traffic_items_to_configure,
        traffic_items_to_start=[
            f"(?!{device_name.upper()}_HIGH_QUEUE_BGP_CP_TRAFFIC)"
            f"(?!{device_name.upper()}_GOOD_BUT_LOSSY_NDP_TRAFFIC)"
            f"(?!{device_name.upper()}_LOSSY_ROGUE_NDP_TRAFFIC)"
            f"(?!{device_name.upper()}_{CONGESTION_TRAFFIC_ITEM_SUFFIX})",
        ],
        postchecks=[_make_loss_check()],
        snapshot_checks=snapshot_checks,
        stages=[congestion_stage],
        cleanup_steps=cleanup_steps,
    )


def _create_ncnf_per_queue_congestion_playbook(
    device_name: str,
    ixia_downlink_interface: str,
    frame_size: t.Optional[ixia_types.FrameSize] = None,
) -> Playbook:
    """
    Creates a per-queue congestion playbook for NCNF (queue0, DSCP 51).

    NCNF is not yet a first-class ClassOfService enum value, so this
    function uses the standalone NCNF_DSCP_VALUE constant.
    Same structure as _create_qos_per_queue_congestion_playbook but
    without ClassOfService-based buffer health checks.
    """
    playbook_name = TEST_QOS_PER_QUEUE_CONGESTION_QUEUE0_NCNF.name
    resolved_frame_size = frame_size if frame_size else DEFAULT_FRAME_SIZE

    ipv6_qos = ixia_types.QoSConfig(
        phb_type=ixia_types.PHBTypes.TRAFFIC_CLASS,
        dscp_value=NCNF_DSCP_VALUE,
        ecn_capability=ixia_types.EcnCapability.ECN_CAPABLE,
    )
    ipv4_qos = ixia_types.QoSConfig(
        phb_type=ixia_types.PHBTypes.DEFAULT,
        dscp_value=NCNF_DSCP_VALUE,
        ecn_capability=ixia_types.EcnCapability.ECN_CAPABLE,
    )

    v6_layer3_name = f"{device_name.upper()}_V6_LAYER3_TRAFFIC_DOWNLINK_AND_UPLINK"
    v6_directional_name = (
        f"{device_name.upper()}_V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK"
    )
    v4_directional_name = (
        f"{device_name.upper()}_V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK"
    )
    congestion_name = f"{device_name.upper()}_{CONGESTION_TRAFFIC_ITEM_SUFFIX}"

    traffic_items_to_configure = {
        v6_layer3_name: taac_types.TrafficItemSettings(
            line_rate=25,
            qos_config=ipv6_qos,
            frame_size_settings=resolved_frame_size,
        ),
        v6_directional_name: taac_types.TrafficItemSettings(
            line_rate=25,
            qos_config=ipv6_qos,
            frame_size_settings=resolved_frame_size,
        ),
        v4_directional_name: taac_types.TrafficItemSettings(
            line_rate=25,
            qos_config=ipv4_qos,
            frame_size_settings=resolved_frame_size,
        ),
        congestion_name: taac_types.TrafficItemSettings(
            line_rate=50,
            qos_config=ipv6_qos,
            frame_size_settings=resolved_frame_size,
        ),
    }

    baseline_traffic_regex = _combined_exact_traffic_item_regex(
        [v6_layer3_name, v6_directional_name, v4_directional_name]
    )
    target_traffic_regexes = _exact_traffic_item_regexes(
        traffic_items_to_configure.keys()
    )
    congestion_item_regex = _exact_traffic_item_regexes([congestion_name])[0]

    congestion_stage = create_steps_stage(
        stage_id="qos_per_queue_congestion_traffic",
        steps=[
            _ixia_stop_traffic_step(step_id="stop_traffic_engine"),
            _ixia_enable_traffic_step(
                regexes=target_traffic_regexes,
                enable=True,
                step_id="select_test_traffic",
            ),
            _ixia_regenerate_and_apply_step(step_id="regenerate_traffic"),
            _ixia_apply_traffic_step(step_id="apply_traffic"),
            _ixia_start_traffic_items_step(
                congestion_item_regex, step_id="start_congestion_first"
            ),
            create_longevity_step(
                duration=10,
                step_id="settle_congestion",
                start_traffic=False,
            ),
            _ixia_start_traffic_items_step(
                baseline_traffic_regex, step_id="add_priority_traffic"
            ),
            _ixia_clear_traffic_stats_step(step_id="clear_stats"),
            create_longevity_step(
                duration=LONGEVITY_DURATION_S, step_id="congestion_longevity"
            ),
        ],
    )

    def _make_loss_check() -> PointInTimeHealthCheck:
        return create_ixia_packet_loss_check_traffic_split(
            device_name,
            expect_loss_traffic=[
                CONGESTION_TRAFFIC_ITEM_SUFFIX,
                "V6_LAYER3_TRAFFIC_DOWNLINK_AND_UPLINK",
                "V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
                "V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
            ],
            no_loss_traffic=[],
            skip_traffic_items=DISABLED_AUXILIARY_TRAFFIC_SUFFIXES,
        )

    pre_checkpoint = (
        "stage.qos_per_queue_congestion_traffic.step.congestion_longevity.start"
    )
    post_checkpoint = (
        "stage.qos_per_queue_congestion_traffic.step.congestion_longevity.end"
    )
    snapshot_checks = [
        _make_qos_queue_desc_snapshot_check(
            device_name=device_name,
            queue_descs=[NCNF_QUEUE_DESC],
            idle_cos_list=list(COS_DSCP_VALUES),
            interfaces=[ixia_downlink_interface],
            pre_snapshot_checkpoint_id=pre_checkpoint,
            post_snapshot_checkpoint_id=post_checkpoint,
        ),
        _make_buffer_utilization_check(
            device_name=device_name,
            active_cos_list=[],
            active_queue_desc_list=[NCNF_QUEUE_DESC],
            interfaces=[ixia_downlink_interface],
            active_queue_max_bytes=CONTINUOUS_CONGESTED_QUEUE_BUFFER_MAX_BYTES,
            other_queue_max_bytes=CONTINUOUS_OTHER_QUEUE_BUFFER_MAX_BYTES,
            pre_snapshot_checkpoint_id=pre_checkpoint,
            post_snapshot_checkpoint_id=post_checkpoint,
        ),
    ]

    cleanup_steps = [
        _ixia_enable_traffic_step(
            regexes=[congestion_item_regex],
            enable=False,
            step_id="cleanup_stop_congestion_traffic",
        ),
    ]

    return build_qos_scheduling_playbook(
        name=playbook_name,
        traffic_items_to_configure=traffic_items_to_configure,
        traffic_items_to_start=[
            f"(?!{device_name.upper()}_HIGH_QUEUE_BGP_CP_TRAFFIC)"
            f"(?!{device_name.upper()}_GOOD_BUT_LOSSY_NDP_TRAFFIC)"
            f"(?!{device_name.upper()}_LOSSY_ROGUE_NDP_TRAFFIC)"
            f"(?!{device_name.upper()}_{CONGESTION_TRAFFIC_ITEM_SUFFIX})",
        ],
        postchecks=[_make_loss_check()],
        snapshot_checks=snapshot_checks,
        stages=[congestion_stage],
        cleanup_steps=cleanup_steps,
    )


def get_qos_per_queue_congestion_playbooks(
    device_name: str,
    ixia_downlink_interface: str,
    frame_size: t.Optional[ixia_types.FrameSize] = None,
) -> t.List[Playbook]:
    """
    Generates per-queue congestion playbooks — one per ClassOfService queue
    plus NCNF. Both ingress ports send the same DSCP marking:
    Port 1 at 75% linerate, Port 2 at 50% linerate.
    """
    playbooks = []
    for cos in COS_TO_PER_QUEUE_CONGESTION_PLAYBOOK:
        playbooks.append(
            _create_qos_per_queue_congestion_playbook(
                device_name=device_name,
                cos=cos,
                ixia_downlink_interface=ixia_downlink_interface,
                frame_size=frame_size,
            )
        )
    playbooks.append(
        _create_ncnf_per_queue_congestion_playbook(
            device_name=device_name,
            ixia_downlink_interface=ixia_downlink_interface,
            frame_size=frame_size,
        )
    )
    return playbooks


# ---------------------------------------------------------------------------
# Single-queue congestion playbook (one queue congested via per-queue item)
# ---------------------------------------------------------------------------
def _create_qos_single_queue_congestion_playbook(
    device_name: str,
    congested_cos: ClassOfService,
    ixia_downlink_interface: str,
    frame_size: t.Optional[ixia_types.FrameSize] = None,
) -> Playbook:
    """
    Creates a playbook that congests a single queue using the per-queue
    congestion traffic item from the third (congestion) IXIA port.

    The test scenario:
    1. Configure the 3 existing bidirectional traffic items on NC
       (highest priority) at 33+33+34% linerate.
    2. Configure one per-queue congestion traffic item on the target
       queue at MULTI_CONGESTION_LINERATE% from the congestion port.
    3. Traffic sequencing:
       a. Stop all traffic.
       b. Start the congestion traffic item first.
       c. Start the 3 existing priority items.
       d. Let traffic run (longevity).
    4. Warmboot and re-validate.
    5. Stop all traffic, restart in reverse order (priority first, then
       congestion), run checks again.
    6. Buffer utilization: congested queue may use buffer, all others
       should not.
    7. Packet loss: congestion item expects loss, priority items do not.
    """
    priority_cos = ClassOfService.NC
    priority_dscp = COS_DSCP_VALUES[priority_cos]
    congested_dscp = COS_DSCP_VALUES[congested_cos]

    congestion_suffix = COS_CONGESTION_TRAFFIC_SUFFIX[congested_cos]
    playbook_name = COS_TO_SINGLE_CONGESTION_PLAYBOOK[congested_cos].name

    resolved_frame_size = frame_size if frame_size else DEFAULT_FRAME_SIZE

    # QoS configs for the priority queue (existing 3 items on NC).
    ipv6_priority_qos = ixia_types.QoSConfig(
        phb_type=ixia_types.PHBTypes.TRAFFIC_CLASS,
        dscp_value=priority_dscp,
        ecn_capability=ixia_types.EcnCapability.ECN_CAPABLE,
    )
    ipv4_priority_qos = ixia_types.QoSConfig(
        phb_type=ixia_types.PHBTypes.DEFAULT,
        dscp_value=priority_dscp,
        ecn_capability=ixia_types.EcnCapability.ECN_CAPABLE,
    )

    # QoS config for the per-queue congestion traffic item.
    congestion_qos = ixia_types.QoSConfig(
        phb_type=ixia_types.PHBTypes.TRAFFIC_CLASS,
        dscp_value=congested_dscp,
        ecn_capability=ixia_types.EcnCapability.ECN_CAPABLE,
    )

    v6_layer3_name = f"{device_name.upper()}_V6_LAYER3_TRAFFIC_DOWNLINK_AND_UPLINK"
    v6_directional_name = (
        f"{device_name.upper()}_V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK"
    )
    v4_directional_name = (
        f"{device_name.upper()}_V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK"
    )
    congestion_name = f"{device_name.upper()}_{congestion_suffix}"

    def _make_loss_check() -> PointInTimeHealthCheck:
        return create_ixia_packet_loss_check_traffic_split(
            device_name,
            expect_loss_traffic=[congestion_suffix],
            no_loss_traffic=[
                "V6_LAYER3_TRAFFIC_DOWNLINK_AND_UPLINK",
                "V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
                "V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
            ],
            no_loss_threshold="0",
            no_loss_metric=hc_types.PacketLossMetric.DURATION,
            no_loss_comparison=hc_types.ComparisonType.EQUAL_TO,
        )

    traffic_items_to_configure = {
        v6_layer3_name: taac_types.TrafficItemSettings(
            line_rate=33,
            qos_config=ipv6_priority_qos,
            frame_size_settings=resolved_frame_size,
        ),
        v6_directional_name: taac_types.TrafficItemSettings(
            line_rate=33,
            qos_config=ipv6_priority_qos,
            frame_size_settings=resolved_frame_size,
        ),
        v4_directional_name: taac_types.TrafficItemSettings(
            line_rate=34,
            qos_config=ipv4_priority_qos,
            frame_size_settings=resolved_frame_size,
        ),
        congestion_name: taac_types.TrafficItemSettings(
            line_rate=MULTI_CONGESTION_LINERATE,
            qos_config=congestion_qos,
            frame_size_settings=resolved_frame_size,
        ),
    }

    # Build negative-lookahead exclusion regexes for traffic_items_to_start.
    exclude_suffixes = [
        "HIGH_QUEUE_BGP_CP_TRAFFIC",
        "GOOD_BUT_LOSSY_NDP_TRAFFIC",
        "LOSSY_ROGUE_NDP_TRAFFIC",
        CONGESTION_TRAFFIC_ITEM_SUFFIX,
    ] + list(COS_CONGESTION_TRAFFIC_SUFFIX.values())

    traffic_items_to_start_regex = "".join(
        f"(?!{device_name.upper()}_{suffix})" for suffix in exclude_suffixes
    )
    baseline_traffic_regex = _combined_exact_traffic_item_regex(
        [v6_layer3_name, v6_directional_name, v4_directional_name]
    )
    target_traffic_regexes = _exact_traffic_item_regexes(
        traffic_items_to_configure.keys()
    )
    congestion_item_regex = _exact_traffic_item_regexes([congestion_name])[0]

    # Stage 1: Stop traffic, enable all items including per-queue congestion,
    # start, and run longevity.
    congestion_stage = create_steps_stage(
        stage_id="qos_single_congestion_traffic",
        steps=[
            _ixia_stop_traffic_step(step_id="stop_traffic_engine"),
            _ixia_enable_traffic_step(
                regexes=target_traffic_regexes,
                enable=True,
                step_id="select_test_traffic",
            ),
            _ixia_regenerate_and_apply_step(step_id="regenerate_traffic"),
            _ixia_apply_traffic_step(step_id="apply_traffic"),
            _ixia_clear_traffic_stats_step(step_id="clear_stats_before_initial"),
            _ixia_start_traffic_items_step(
                congestion_item_regex, step_id="start_congestion_traffic"
            ),
            create_longevity_step(
                duration=10,
                step_id="settle_congestion",
                start_traffic=False,
            ),
            _ixia_start_traffic_items_step(
                baseline_traffic_regex, step_id="add_priority_traffic"
            ),
            create_longevity_step(
                duration=LONGEVITY_DURATION_S, step_id="congestion_longevity"
            ),
            *_stop_and_validate_traffic_steps(_make_loss_check(), "initial_congestion"),
        ],
    )

    # Stage 2: Start a fresh measurement window before warmboot. Counters are
    # intentionally not cleared after the restart: loss during warmboot is part
    # of the hitless-forwarding contract.
    warmboot_stage = create_steps_stage(
        stage_id="qos_single_congestion_warmboot",
        steps=[
            _ixia_start_traffic_step(step_id="start_warmboot_traffic"),
            _ixia_clear_traffic_stats_step(step_id="clear_stats_before_warmboot"),
            create_service_interruption_step(
                service=Service.AGENT,
                trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                step_id="do_warmboot",
            ),
            create_service_convergence_step(
                services=[Service.AGENT], step_id="warmboot_convergence"
            ),
            create_longevity_step(
                duration=LONGEVITY_DURATION_S, step_id="post_warmboot_longevity"
            ),
            *_stop_and_validate_traffic_steps(
                _make_loss_check(), "warmboot_congestion"
            ),
        ],
    )

    # Stage 3: Stop all, restart in reverse order (priority first, then congestion).
    reverse_restart_stage = create_steps_stage(
        stage_id="qos_single_congestion_reverse_restart",
        steps=[
            _ixia_stop_traffic_step(step_id="stop_all_traffic"),
            _ixia_clear_traffic_stats_step(step_id="clear_stats_before_reverse"),
            _ixia_enable_traffic_step(
                regexes=target_traffic_regexes,
                enable=True,
                step_id="select_all_test_traffic_reverse",
            ),
            _ixia_regenerate_and_apply_step(step_id="regenerate_priority"),
            _ixia_apply_traffic_step(step_id="apply_priority"),
            _ixia_start_traffic_items_step(
                baseline_traffic_regex, step_id="start_priority_traffic"
            ),
            create_longevity_step(
                duration=10,
                step_id="settle_priority",
                start_traffic=False,
            ),
            _ixia_start_traffic_items_step(
                congestion_item_regex, step_id="add_congestion_traffic"
            ),
            create_longevity_step(
                duration=LONGEVITY_DURATION_S, step_id="reverse_longevity"
            ),
            *_stop_and_validate_traffic_steps(_make_loss_check(), "reverse_congestion"),
        ],
    )

    snapshot_checks = []
    for stage_id, step_id in (
        ("qos_single_congestion_traffic", "congestion_longevity"),
        ("qos_single_congestion_warmboot", "post_warmboot_longevity"),
        ("qos_single_congestion_reverse_restart", "reverse_longevity"),
    ):
        pre_checkpoint = f"stage.{stage_id}.step.{step_id}.start"
        post_checkpoint = f"stage.{stage_id}.step.{step_id}.end"
        snapshot_checks.extend(
            [
                _make_qos_cos_list_snapshot_check(
                    device_name=device_name,
                    cos_list=[priority_cos, congested_cos],
                    interfaces=[ixia_downlink_interface],
                    pre_snapshot_checkpoint_id=pre_checkpoint,
                    post_snapshot_checkpoint_id=post_checkpoint,
                ),
                _make_buffer_utilization_check(
                    device_name=device_name,
                    active_cos_list=[congested_cos],
                    interfaces=[ixia_downlink_interface],
                    active_queue_max_bytes=LONG_RUNNING_CONGESTED_QUEUE_BUFFER_MAX_BYTES,
                    other_queue_max_bytes=LONG_RUNNING_OTHER_QUEUE_BUFFER_MAX_BYTES,
                    pre_snapshot_checkpoint_id=pre_checkpoint,
                    post_snapshot_checkpoint_id=post_checkpoint,
                ),
            ]
        )

    # Cleanup: disable the per-queue congestion item.
    cleanup_steps = [
        _ixia_enable_traffic_step(
            regexes=[congestion_item_regex],
            enable=False,
            step_id="cleanup_stop_congestion_traffic",
        ),
    ]

    return build_qos_scheduling_playbook(
        name=playbook_name,
        traffic_items_to_configure=traffic_items_to_configure,
        traffic_items_to_start=[traffic_items_to_start_regex],
        postchecks=[],
        snapshot_checks=snapshot_checks,
        stages=[congestion_stage, warmboot_stage, reverse_restart_stage],
        cleanup_steps=cleanup_steps,
    )


def get_qos_single_queue_congestion_playbooks(
    device_name: str,
    ixia_downlink_interface: str,
    frame_size: t.Optional[ixia_types.FrameSize] = None,
) -> t.List[Playbook]:
    """
    Generates single-queue congestion playbooks — one per lower-priority
    queue (ICP, GOLD, SILVER, BRONZE).

    Each playbook sends the 3 existing items on NC (highest priority)
    and one per-queue congestion item on the target queue from the
    congestion port.
    """
    playbooks = []
    for congested_cos in COS_TO_SINGLE_CONGESTION_PLAYBOOK:
        playbooks.append(
            _create_qos_single_queue_congestion_playbook(
                device_name=device_name,
                congested_cos=congested_cos,
                ixia_downlink_interface=ixia_downlink_interface,
                frame_size=frame_size,
            )
        )
    return playbooks


# ---------------------------------------------------------------------------
# Multi-queue congestion playbook (multiple queues congested simultaneously)
# ---------------------------------------------------------------------------
def _create_qos_multi_congestion_playbook(
    device_name: str,
    priority_cos: ClassOfService,
    congested_cos_list: t.List[ClassOfService],
    ixia_downlink_interface: str,
    frame_size: t.Optional[ixia_types.FrameSize] = None,
) -> Playbook:
    """
    Creates a playbook that validates QoS scheduling when multiple queues
    are congested simultaneously.

    The test scenario:
    1. Configure the 3 existing bidirectional traffic items on the
       *priority* queue at 33+33+34% linerate.
    2. Configure per-queue congestion traffic items for each congested
       queue at MULTI_CONGESTION_LINERATE% from the congestion port.
    3. Traffic sequencing:
       a. Stop all traffic.
       b. Start congestion traffic items first.
       c. Start the 3 existing priority items.
       d. Let traffic run (longevity).
    4. Warmboot and re-validate.
    5. Stop all traffic, restart in reverse order (priority first, then
       congestion), run checks again.
    6. Buffer utilization: all congested queues may use buffer, priority
       queue and other queues should not.
    """
    priority_dscp = COS_DSCP_VALUES[priority_cos]
    congested_cos_tuple = tuple(congested_cos_list)

    playbook_name = COS_MULTI_CONGESTION_PLAYBOOK[
        (priority_cos, congested_cos_tuple)
    ].name

    resolved_frame_size = frame_size if frame_size else DEFAULT_FRAME_SIZE

    # QoS configs for the priority queue (existing 3 items).
    ipv6_priority_qos = ixia_types.QoSConfig(
        phb_type=ixia_types.PHBTypes.TRAFFIC_CLASS,
        dscp_value=priority_dscp,
        ecn_capability=ixia_types.EcnCapability.ECN_CAPABLE,
    )
    ipv4_priority_qos = ixia_types.QoSConfig(
        phb_type=ixia_types.PHBTypes.DEFAULT,
        dscp_value=priority_dscp,
        ecn_capability=ixia_types.EcnCapability.ECN_CAPABLE,
    )

    v6_layer3_name = f"{device_name.upper()}_V6_LAYER3_TRAFFIC_DOWNLINK_AND_UPLINK"
    v6_directional_name = (
        f"{device_name.upper()}_V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK"
    )
    v4_directional_name = (
        f"{device_name.upper()}_V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK"
    )

    traffic_items_to_configure = {
        v6_layer3_name: taac_types.TrafficItemSettings(
            line_rate=33,
            qos_config=ipv6_priority_qos,
            frame_size_settings=resolved_frame_size,
        ),
        v6_directional_name: taac_types.TrafficItemSettings(
            line_rate=33,
            qos_config=ipv6_priority_qos,
            frame_size_settings=resolved_frame_size,
        ),
        v4_directional_name: taac_types.TrafficItemSettings(
            line_rate=34,
            qos_config=ipv4_priority_qos,
            frame_size_settings=resolved_frame_size,
        ),
    }

    # Configure per-queue congestion traffic items.
    congestion_item_names = []
    all_expect_loss_suffixes = []
    for cos in congested_cos_list:
        suffix = COS_CONGESTION_TRAFFIC_SUFFIX[cos]
        congestion_name = f"{device_name.upper()}_{suffix}"
        congested_dscp = COS_DSCP_VALUES[cos]
        congestion_qos = ixia_types.QoSConfig(
            phb_type=ixia_types.PHBTypes.TRAFFIC_CLASS,
            dscp_value=congested_dscp,
            ecn_capability=ixia_types.EcnCapability.ECN_CAPABLE,
        )
        traffic_items_to_configure[congestion_name] = taac_types.TrafficItemSettings(
            line_rate=MULTI_CONGESTION_LINERATE,
            qos_config=congestion_qos,
            frame_size_settings=resolved_frame_size,
        )
        congestion_item_names.append(congestion_name)
        all_expect_loss_suffixes.append(suffix)

    # Build negative-lookahead exclusion regexes for traffic_items_to_start.
    # Exclude all congestion items, NDP, and BGP CP traffic from auto-start.
    exclude_suffixes = [
        "HIGH_QUEUE_BGP_CP_TRAFFIC",
        "GOOD_BUT_LOSSY_NDP_TRAFFIC",
        "LOSSY_ROGUE_NDP_TRAFFIC",
        CONGESTION_TRAFFIC_ITEM_SUFFIX,
    ] + list(COS_CONGESTION_TRAFFIC_SUFFIX.values())

    traffic_items_to_start_regex = "".join(
        f"(?!{device_name.upper()}_{suffix})" for suffix in exclude_suffixes
    )
    baseline_traffic_regex = _combined_exact_traffic_item_regex(
        [v6_layer3_name, v6_directional_name, v4_directional_name]
    )
    congestion_traffic_regex = _combined_exact_traffic_item_regex(congestion_item_names)
    target_traffic_regexes = _exact_traffic_item_regexes(
        traffic_items_to_configure.keys()
    )

    # Stage 1: Stop traffic, enable all items, start congestion first,
    # then priority, run longevity.
    congestion_stage = create_steps_stage(
        stage_id="qos_multi_congestion_traffic",
        steps=[
            _ixia_stop_traffic_step(step_id="stop_traffic_engine"),
            _ixia_enable_traffic_step(
                regexes=target_traffic_regexes,
                enable=True,
                step_id="select_test_traffic",
            ),
            _ixia_regenerate_and_apply_step(step_id="regenerate_traffic"),
            _ixia_apply_traffic_step(step_id="apply_traffic"),
            _ixia_start_traffic_items_step(
                congestion_traffic_regex, step_id="start_congestion_traffic"
            ),
            create_longevity_step(
                duration=10,
                step_id="settle_congestion",
                start_traffic=False,
            ),
            _ixia_start_traffic_items_step(
                baseline_traffic_regex, step_id="add_priority_traffic"
            ),
            create_longevity_step(
                duration=LONGEVITY_DURATION_S, step_id="congestion_longevity"
            ),
        ],
    )

    # Stage 2: Warmboot while all traffic is flowing.
    warmboot_stage = create_steps_stage(
        stage_id="qos_multi_congestion_warmboot",
        steps=[
            create_service_interruption_step(
                service=Service.AGENT,
                trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                step_id="do_warmboot",
            ),
            create_service_convergence_step(
                services=[Service.AGENT], step_id="warmboot_convergence"
            ),
            create_longevity_step(
                duration=LONGEVITY_DURATION_S, step_id="post_warmboot_longevity"
            ),
        ],
    )

    # Stage 3: Stop all, restart in reverse order (priority first, then congestion).
    reverse_restart_stage = create_steps_stage(
        stage_id="qos_multi_congestion_reverse_restart",
        steps=[
            _ixia_stop_traffic_step(step_id="stop_all_traffic"),
            _ixia_enable_traffic_step(
                regexes=target_traffic_regexes,
                enable=True,
                step_id="select_all_test_traffic_reverse",
            ),
            _ixia_regenerate_and_apply_step(step_id="regenerate_priority"),
            _ixia_apply_traffic_step(step_id="apply_priority"),
            _ixia_start_traffic_items_step(
                baseline_traffic_regex, step_id="start_priority_traffic"
            ),
            create_longevity_step(
                duration=10,
                step_id="settle_priority",
                start_traffic=False,
            ),
            _ixia_start_traffic_items_step(
                congestion_traffic_regex, step_id="add_congestion_traffic"
            ),
            create_longevity_step(
                duration=LONGEVITY_DURATION_S, step_id="reverse_longevity"
            ),
        ],
    )

    # Packet loss checks: congestion items expect loss, priority items do not.
    def _make_multi_congestion_loss_check() -> PointInTimeHealthCheck:
        return create_ixia_packet_loss_check_traffic_split(
            device_name,
            expect_loss_traffic=all_expect_loss_suffixes,
            no_loss_traffic=[
                "V6_LAYER3_TRAFFIC_DOWNLINK_AND_UPLINK",
                "V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
                "V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
            ],
            no_loss_threshold="0",
            no_loss_metric=hc_types.PacketLossMetric.DURATION,
            no_loss_comparison=hc_types.ComparisonType.EQUAL_TO,
            skip_traffic_items=DISABLED_AUXILIARY_TRAFFIC_SUFFIXES,
        )

    snapshot_checks = []
    for stage_id, step_id in (
        ("qos_multi_congestion_traffic", "congestion_longevity"),
        ("qos_multi_congestion_warmboot", "post_warmboot_longevity"),
        ("qos_multi_congestion_reverse_restart", "reverse_longevity"),
    ):
        pre_checkpoint = f"stage.{stage_id}.step.{step_id}.start"
        post_checkpoint = f"stage.{stage_id}.step.{step_id}.end"
        snapshot_checks.extend(
            [
                _make_qos_cos_list_snapshot_check(
                    device_name=device_name,
                    cos_list=[priority_cos],
                    interfaces=[ixia_downlink_interface],
                    enforce_exclusivity=False,
                    pre_snapshot_checkpoint_id=pre_checkpoint,
                    post_snapshot_checkpoint_id=post_checkpoint,
                ),
                _make_buffer_utilization_check(
                    device_name=device_name,
                    active_cos_list=congested_cos_list,
                    interfaces=[ixia_downlink_interface],
                    active_queue_max_bytes=LONG_RUNNING_CONGESTED_QUEUE_BUFFER_MAX_BYTES,
                    other_queue_max_bytes=LONG_RUNNING_OTHER_QUEUE_BUFFER_MAX_BYTES,
                    pre_snapshot_checkpoint_id=pre_checkpoint,
                    post_snapshot_checkpoint_id=post_checkpoint,
                ),
            ]
        )

    # Cleanup: disable all per-queue congestion items.
    cleanup_steps = [
        _ixia_enable_traffic_step(
            regexes=congestion_item_names,
            enable=False,
            step_id="cleanup_stop_congestion_traffic",
        ),
    ]

    return build_qos_scheduling_playbook(
        name=playbook_name,
        traffic_items_to_configure=traffic_items_to_configure,
        traffic_items_to_start=[traffic_items_to_start_regex],
        postchecks=[_make_multi_congestion_loss_check()],
        snapshot_checks=snapshot_checks,
        stages=[congestion_stage, warmboot_stage, reverse_restart_stage],
        cleanup_steps=cleanup_steps,
    )


def get_qos_multi_congestion_playbooks(
    device_name: str,
    ixia_downlink_interface: str,
    frame_size: t.Optional[ixia_types.FrameSize] = None,
) -> t.List[Playbook]:
    """
    Generates multi-queue congestion playbooks for all valid combinations
    where a priority queue competes against multiple congested queues.

    Test matrix (6 combinations):
        NC  vs [ICP, GOLD]
        NC  vs [ICP, GOLD, SILVER]
        NC  vs [ICP, GOLD, SILVER, BRONZE]
        ICP vs [GOLD, SILVER]
        ICP vs [GOLD, SILVER, BRONZE]
        GOLD vs [SILVER, BRONZE]
    """
    playbooks = []
    for priority_cos, congested_tuple in COS_MULTI_CONGESTION_PLAYBOOK:
        playbooks.append(
            _create_qos_multi_congestion_playbook(
                device_name=device_name,
                priority_cos=priority_cos,
                congested_cos_list=list(congested_tuple),
                ixia_downlink_interface=ixia_downlink_interface,
                frame_size=frame_size,
            )
        )
    return playbooks


# ---------------------------------------------------------------------------
# Congestion IXIA port + device group + traffic item builders
# ---------------------------------------------------------------------------
def _build_congestion_port_config(
    device_name: str,
    ixia_congestion_interface: str,
    ixia_congestion_ic_parent_network_v6: str,
    congestion_peer_as_4byte: int,
    congestion_prefix_count_v6: int,
    congestion_prefix_start_v6: str,
    is_congestion_peer_confed: str,
    bgp_peer_type=None,
) -> taac_types.BasicPortConfig:
    """Build the BasicPortConfig for the dedicated congestion IXIA port.

    The port has a single IPv6 device group with a BGP peer that
    advertises routes toward the same destination as the uplink/downlink
    peers so that the congestion traffic egresses through the same
    DUT interface.
    """
    return taac_types.BasicPortConfig(
        endpoint=f"{device_name}:{ixia_congestion_interface}",
        device_group_configs=[
            taac_types.DeviceGroupConfig(
                device_group_index=0,
                tag_name="CONGESTION_V6",
                multiplier=1,
                v6_addresses_config=taac_types.IpAddressesConfig(
                    starting_ip=f"{ixia_congestion_ic_parent_network_v6}::11",
                    increment_ip="0:0:0:0::2",
                    gateway_starting_ip=f"{ixia_congestion_ic_parent_network_v6}::10",
                    gateway_increment_ip="0:0:0:0::2",
                    mask=127,
                ),
                v6_bgp_config=taac_types.BgpConfig(
                    local_as_4_bytes=congestion_peer_as_4byte,
                    local_as_increment=0,
                    enable_4_byte_local_as=True,
                    is_confed=is_congestion_peer_confed == "True",
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                    hold_timer=30,
                    keepalive_timer=10,
                    bgp_peer_type=bgp_peer_type,
                    route_scales=[
                        taac_types.RouteScaleSpec(
                            network_group_index=0,
                            v6_route_scale=taac_types.RouteScale(
                                multiplier=1,
                                prefix_count=congestion_prefix_count_v6,
                                prefix_length=64,
                                starting_prefixes=congestion_prefix_start_v6,
                                prefix_step="0:0:0:0::0",
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                            ),
                        ),
                    ],
                ),
            ),
        ],
    )


def _build_congestion_traffic_item_config(
    device_name: str,
    ixia_congestion_interface: str,
    ixia_downlink_interface: str,
) -> taac_types.BasicTrafficItemConfig:
    """Build the BasicTrafficItemConfig for the congestion traffic item.

    Traffic flows from the congestion port → through the DUT → to the
    downlink port, targeting the same egress interface as the existing
    bidirectional traffic items.
    """
    return taac_types.BasicTrafficItemConfig(
        name=f"{device_name.upper()}_{CONGESTION_TRAFFIC_ITEM_SUFFIX}",
        bidirectional=False,
        merge_destinations=True,
        line_rate=50,
        src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
        src_endpoints=[
            taac_types.TrafficEndpoint(
                name=f"{device_name}:{ixia_congestion_interface}",
                network_group_index=0,
                device_group_index=0,
            ),
        ],
        dest_endpoints=[
            taac_types.TrafficEndpoint(
                name=f"{device_name}:{ixia_downlink_interface}",
                network_group_index=0,
                device_group_index=0,
            ),
        ],
        traffic_type=ixia_types.TrafficType.IPV6,
        tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
        frame_size_settings=DEFAULT_FRAME_SIZE,
    )


def _build_per_queue_congestion_traffic_item_configs(
    device_name: str,
    ixia_congestion_interface: str,
    ixia_downlink_interface: str,
) -> t.List[taac_types.BasicTrafficItemConfig]:
    """Build per-queue congestion traffic items for multi-queue congestion tests.

    Creates one traffic item per queue in COS_CONGESTION_TRAFFIC_SUFFIX,
    each at MULTI_CONGESTION_LINERATE% linerate.  These are used in
    multi-queue congestion playbooks where multiple queues are congested
    simultaneously on the same egress port.
    """
    configs = []
    for cos, suffix in COS_CONGESTION_TRAFFIC_SUFFIX.items():
        dscp_value = COS_DSCP_VALUES[cos]
        configs.append(
            taac_types.BasicTrafficItemConfig(
                name=f"{device_name.upper()}_{suffix}",
                bidirectional=False,
                merge_destinations=True,
                line_rate=MULTI_CONGESTION_LINERATE,
                src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_congestion_interface}",
                        network_group_index=0,
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        network_group_index=0,
                        device_group_index=0,
                    ),
                ],
                traffic_type=ixia_types.TrafficType.IPV6,
                tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
                frame_size_settings=DEFAULT_FRAME_SIZE,
                qos_config=ixia_types.QoSConfig(
                    phb_type=ixia_types.PHBTypes.TRAFFIC_CLASS,
                    dscp_value=dscp_value,
                    ecn_capability=ixia_types.EcnCapability.ECN_NON_CAPABLE,
                ),
            )
        )
    return configs


def test_config_qos_scheduling(
    test_config_name,
    device_name,
    local_mac_address,
    ixia_downlink_interface,
    ixia_uplink_interface,
    ixia_rogue_interface,
    peergroup_uplink_mimic_v6,
    peergroup_uplink_mimic_v4,
    peergroup_downlink_mimic_v6,
    peergroup_downlink_mimic_v4,
    peergroup_rogue_mimic_v6,
    peergroup_rogue_mimic_v4,
    route_map_uplink_ingress,
    route_map_uplink_egress,
    route_map_downlink_ingress,
    route_map_downlink_egress,
    route_map_rogue_ingress,
    route_map_rogue_egress,
    ixia_downlink_ic_parent_network_v6,
    ixia_uplink_ic_parent_network_v6,
    ixia_rogue_ic_parent_network_v6,
    ixia_downlink_ic_parent_network_v4,
    ixia_uplink_ic_parent_network_v4,
    ixia_rogue_ic_parent_network_v4,
    good_ndp_entry_network_v6,
    rogue_ndp_entry_network_v6,
    good_arp_entry_network_v4,
    rogue_arp_entry_network_v4,
    prefix_limit,
    per_peer_max_route_limit,
    downlink_peer_count,
    uplink_peer_count,
    rogue_peer_count,
    remote_downlink_as_4byte,
    remote_uplink_as_4byte,
    remote_rogue_as_4byte,
    is_uplink_peer_confed,
    is_downlink_peer_confed,
    is_rogue_peer_confed,
    ixia_downlink_prefix_count_v6,
    ixia_uplink_prefix_count_v6,
    ixia_rogue_prefix_count_v6,
    ixia_downlink_prefix_count_v4,
    ixia_uplink_prefix_count_v4,
    ixia_rogue_prefix_count_v4,
    ixia_downlink_communities,
    ixia_uplink_communities,
    uplink_peer_tag,
    downlink_peer_tag,
    ecmp_group_limit,
    good_ndp_entries_uplink,
    good_ndp_entries_downlink,
    rogue_ndp_entries,
    good_arp_entries,
    rogue_arp_entries,
    good_mac_entry_count,
    rogue_mac_entry_count,
    bgp_induced_ecmp_group_count,
    ixia_uplink_good_ndp_network,
    ixia_downlink_good_ndp_network,
    basset_pool,
    # --- New parameters for congestion IXIA port ---
    ixia_congestion_interface=None,
    ixia_congestion_ic_parent_network_v6=None,
    congestion_peer_as_4byte=None,
    congestion_prefix_count_v6=100,
    congestion_prefix_start_v6=None,
    is_congestion_peer_confed="False",
    # --- Parameters forwarded to the conveyor ---
    additional_setup_tasks=None,
    allow_all_v4_policies=False,
    uplink_bgp_peer_type=None,
    skip_playbooks=None,
):
    """Build a QoS scheduling + congestion TestConfig for FBOSS BGP++ devices.

    Layered on top of `test_config_for_bgp_and_fboss_platform_hardening_in_conveyor`
    (chronos-node base topology with uplink/downlink/rogue IXIA ports).
    Generates per-`ClassOfService` playbooks (BRONZE, SILVER, GOLD, ICP, NC)
    that send DSCP-marked V6 traffic at ~99% linerate, then verify traffic
    egresses through the correct hardware queue via
    `qos_dscp_tx_queue_health_check`. When optional congestion parameters
    are supplied, additional playbooks induce per-queue / multi-queue
    congestion via a dedicated congestion IXIA port and verify priority
    scheduling preserves higher-priority queues.

    Args:
        test_config_name: Name to register in `INTERNAL_TEST_CONFIGS`.
        device_name: Hostname of the DUT.
        local_mac_address: DUT-side MAC for the IXIA endpoint.

        Topology (3 IXIA ports: uplink, downlink, rogue):
            ixia_downlink_interface: DUT interface facing IXIA downlink port.
            ixia_uplink_interface: DUT interface facing IXIA uplink port.
            ixia_rogue_interface: DUT interface facing IXIA rogue port (used
                for negative tests).

        BGP peer-group config (V6 + V4 for each of uplink/downlink/rogue):
            peergroup_uplink_mimic_v6, peergroup_uplink_mimic_v4: bgpcpp
                peer-groups for uplink.
            peergroup_downlink_mimic_v6, peergroup_downlink_mimic_v4: bgpcpp
                peer-groups for downlink.
            peergroup_rogue_mimic_v6, peergroup_rogue_mimic_v4: bgpcpp
                peer-groups for rogue.
            route_map_uplink_ingress / route_map_uplink_egress: Uplink
                policies.
            route_map_downlink_ingress / route_map_downlink_egress: Downlink
                policies.
            route_map_rogue_ingress / route_map_rogue_egress: Rogue policies.

        IP addressing (parent networks for V6 and V4 on each direction):
            ixia_downlink_ic_parent_network_v6 / _v4: Downlink parent nets.
            ixia_uplink_ic_parent_network_v6 / _v4: Uplink parent nets.
            ixia_rogue_ic_parent_network_v6 / _v4: Rogue parent nets.
            good_ndp_entry_network_v6 / rogue_ndp_entry_network_v6: V6
                subnets for installing static NDP entries (good vs rogue).
            good_arp_entry_network_v4 / rogue_arp_entry_network_v4: V4
                subnets for static ARP entries.
            ixia_uplink_good_ndp_network / ixia_downlink_good_ndp_network:
                IXIA-side networks used to source good-NDP traffic.

        BGP scale & limits:
            prefix_limit: bgpcpp switch-wide prefix limit.
            per_peer_max_route_limit: bgpcpp `max_routes` per peer-group.
            downlink_peer_count / uplink_peer_count / rogue_peer_count:
                Number of BGP peers per direction.
            remote_downlink_as_4byte / remote_uplink_as_4byte /
                remote_rogue_as_4byte: Base 4-byte AS per direction.
            is_uplink_peer_confed / is_downlink_peer_confed /
                is_rogue_peer_confed: bgpcpp `is_confed_peer` (string
                "True"/"False") per direction.
            ixia_downlink_prefix_count_v6, _v4 / ixia_uplink_prefix_count_v6,
                _v4 / ixia_rogue_prefix_count_v6, _v4: V6/V4 prefixes
                advertised per direction.
            ixia_downlink_communities / ixia_uplink_communities: BGP
                communities attached to advertised prefixes.
            uplink_peer_tag / downlink_peer_tag: bgpcpp `peer_tag` values.
            ecmp_group_limit: ECMP group capacity used for sizing checks.
            bgp_induced_ecmp_group_count: Expected ECMP groups that BGP
                will install (used for snapshot health-check thresholds).

        NDP/ARP/MAC table scale:
            good_ndp_entries_uplink / good_ndp_entries_downlink: Good NDP
                entry counts.
            rogue_ndp_entries: Rogue NDP entry count.
            good_arp_entries: Good ARP entry count.
            rogue_arp_entries: Rogue ARP entry count.
            good_mac_entry_count / rogue_mac_entry_count: MAC table entries
                (good and rogue).

        Infra:
            basset_pool: Basset device-reservation pool name.

        Optional congestion port (all 4 must be set to enable congestion
        playbooks; `(undocumented; see body)` for finer semantics):
            ixia_congestion_interface: DUT interface facing the dedicated
                congestion IXIA port. Defaults to None (disables congestion
                playbooks).
            ixia_congestion_ic_parent_network_v6: V6 parent network for the
                congestion peer.
            congestion_peer_as_4byte: AS for the congestion peer.
            congestion_prefix_count_v6: V6 prefixes from the congestion peer
                (default 100).
            congestion_prefix_start_v6: Starting V6 prefix for congestion
                advertisements.
            is_congestion_peer_confed: bgpcpp `is_confed_peer` for the
                congestion peer (default "False").

        Conveyor passthrough:
            additional_setup_tasks: Extra `Task` objects merged into the
                base config's setup_tasks (used by conveyors to inject
                pre-test config).
            allow_all_v4_policies: Forwarded to the base config; relaxes
                V4 policy validation when True.
            uplink_bgp_peer_type: Optional override for uplink BGP peer
                type (forwarded to the base config).
            skip_playbooks: Optional iterable of playbook names to omit
                from the final TestConfig.

    Returns:
        A `TestConfig` named `test_config_name` with one playbook per
        ClassOfService for plain QoS scheduling, plus (when congestion
        parameters are provided) per-queue, single-queue, and multi-queue
        congestion playbooks layered on top.

    Example:
        >>> cfg = test_config_qos_scheduling(
        ...     test_config_name="DNE_KODIAK3_QOS_SCHEDULING_TEST",
        ...     device_name="rsw001.kodiak3",
        ...     ixia_congestion_interface="Ethernet5/1/1",
        ...     congestion_peer_as_4byte=4290000099,
        ...     congestion_prefix_start_v6="9000:1::",
        ...     # ... plus the base topology + addressing kwargs
        ... )
    """
    playbooks = get_qos_scheduling_playbooks(
        device_name,
        ixia_downlink_interface,
        ixia_uplink_interface,
    )
    # Add congestion playbooks if the congestion port is configured.
    has_congestion_port = (
        ixia_congestion_interface is not None
        and ixia_congestion_ic_parent_network_v6 is not None
        and congestion_peer_as_4byte is not None
        and congestion_prefix_start_v6 is not None
    )
    if has_congestion_port:
        playbooks.extend(
            get_qos_per_queue_congestion_playbooks(
                device_name,
                ixia_downlink_interface,
            )
        )
        playbooks.extend(
            get_qos_congestion_playbooks(
                device_name,
                ixia_downlink_interface,
                ixia_uplink_interface,
            )
        )
        playbooks.extend(
            get_qos_single_queue_congestion_playbooks(
                device_name,
                ixia_downlink_interface,
            )
        )
        playbooks.extend(
            get_qos_multi_congestion_playbooks(
                device_name,
                ixia_downlink_interface,
            )
        )

    test_config = test_config_for_bgp_and_fboss_platform_hardening_in_conveyor(
        test_config_name,
        device_name,
        local_mac_address,
        ixia_downlink_interface,
        ixia_uplink_interface,
        peergroup_uplink_mimic_v6,
        peergroup_uplink_mimic_v4,
        peergroup_downlink_mimic_v6,
        peergroup_downlink_mimic_v4,
        peergroup_rogue_mimic_v6,
        peergroup_rogue_mimic_v4,
        route_map_uplink_ingress,
        route_map_uplink_egress,
        route_map_downlink_ingress,
        route_map_downlink_egress,
        route_map_rogue_ingress,
        route_map_rogue_egress,
        ixia_downlink_ic_parent_network_v6,
        ixia_uplink_ic_parent_network_v6,
        ixia_rogue_ic_parent_network_v6,
        ixia_downlink_ic_parent_network_v4,
        ixia_uplink_ic_parent_network_v4,
        ixia_rogue_ic_parent_network_v4,
        good_ndp_entry_network_v6,
        rogue_ndp_entry_network_v6,
        good_arp_entry_network_v4,
        rogue_arp_entry_network_v4,
        prefix_limit,
        per_peer_max_route_limit,
        downlink_peer_count,
        uplink_peer_count,
        rogue_peer_count,
        remote_downlink_as_4byte,
        remote_uplink_as_4byte,
        remote_rogue_as_4byte,
        is_uplink_peer_confed,
        is_downlink_peer_confed,
        is_rogue_peer_confed,
        ixia_downlink_prefix_count_v6,
        ixia_uplink_prefix_count_v6,
        ixia_rogue_prefix_count_v6,
        ixia_downlink_prefix_count_v4,
        ixia_uplink_prefix_count_v4,
        ixia_rogue_prefix_count_v4,
        ixia_downlink_communities,
        ixia_uplink_communities,
        uplink_peer_tag,
        downlink_peer_tag,
        ecmp_group_limit,
        good_ndp_entries_uplink,
        good_ndp_entries_downlink,
        rogue_ndp_entries,
        good_arp_entries,
        rogue_arp_entries,
        good_mac_entry_count,
        rogue_mac_entry_count,
        bgp_induced_ecmp_group_count,
        ixia_uplink_good_ndp_network,
        ixia_downlink_good_ndp_network,
        playbooks=playbooks,
        basset_pool=basset_pool,
        additional_setup_tasks=additional_setup_tasks,
        allow_all_v4_policies=allow_all_v4_policies,
        uplink_bgp_peer_type=uplink_bgp_peer_type,
        skip_playbooks=skip_playbooks,
    )

    # Append congestion port config and traffic item to the TestConfig
    # returned by the conveyor, so the base conveyor is untouched.
    # Thrift structs are fully immutable — we must reconstruct a new
    # TestConfig with modified lists rather than mutating in-place.
    if has_congestion_port:
        # Build the modified port configs list.
        # NOTE: Even when the congestion interface reuses the same physical
        # port name as the rogue interface (e.g. eth9/16/1), we must still
        # add a BasicPortConfig for it.  The conveyor does NOT create a
        # separate IXIA vport for the rogue interface — rogue BGP sessions
        # are configured as device groups on the uplink port.  The congestion
        # traffic item needs its own vport, so we always add the port config.
        port_configs = list(test_config.basic_port_configs)
        congestion_port_config = _build_congestion_port_config(
            device_name=device_name,
            ixia_congestion_interface=ixia_congestion_interface,
            ixia_congestion_ic_parent_network_v6=ixia_congestion_ic_parent_network_v6,
            congestion_peer_as_4byte=congestion_peer_as_4byte,
            congestion_prefix_count_v6=congestion_prefix_count_v6,
            congestion_prefix_start_v6=congestion_prefix_start_v6,
            is_congestion_peer_confed=is_congestion_peer_confed,
            bgp_peer_type=uplink_bgp_peer_type,
        )
        port_configs.append(congestion_port_config)

        # Build the modified traffic item configs list.
        traffic_configs = [
            traffic_config
            for traffic_config in test_config.basic_traffic_item_configs
            if not any(
                traffic_config.name.endswith(suffix)
                for suffix in DISABLED_AUXILIARY_TRAFFIC_SUFFIXES
            )
        ]
        congestion_traffic_item = _build_congestion_traffic_item_config(
            device_name=device_name,
            ixia_congestion_interface=ixia_congestion_interface,
            ixia_downlink_interface=ixia_downlink_interface,
        )
        traffic_configs.append(congestion_traffic_item)
        # Per-queue congestion traffic items for multi-queue congestion playbooks.
        traffic_configs.extend(
            _build_per_queue_congestion_traffic_item_configs(
                device_name=device_name,
                ixia_congestion_interface=ixia_congestion_interface,
                ixia_downlink_interface=ixia_downlink_interface,
            )
        )

        # Add the congestion port to the DUT endpoint's ixia_ports so that
        # the IXIA layer creates a vport for it.  Endpoint is also an immutable
        # Thrift struct, so we reconstruct it via dict().
        updated_endpoints = []
        for ep in test_config.endpoints:
            if ep.dut:
                ep_fields = dict(ep)
                ep_fields["ixia_ports"] = list(ep.ixia_ports or []) + [
                    ixia_congestion_interface,
                ]
                updated_endpoints.append(taac_types.Endpoint(**ep_fields))
            else:
                updated_endpoints.append(ep)

        # Reconstruct TestConfig with modified lists (Thrift structs are immutable).
        config_fields = dict(test_config)
        config_fields["basic_port_configs"] = port_configs
        config_fields["basic_traffic_item_configs"] = traffic_configs
        config_fields["endpoints"] = updated_endpoints
        test_config = taac_types.TestConfig(**config_fields)

    normalized_playbooks = []
    for playbook in test_config.playbooks:
        prechecks = [
            check
            for check in playbook.prechecks or []
            if check.name != hc_types.CheckName.IXIA_PACKET_LOSS_CHECK
        ]
        stages = list(playbook.stages or [])
        has_inline_ixia_validation = any(
            step.name == StepName.VALIDATION_STEP
            for stage in stages
            for step in stage.steps or []
        )
        scenario_packet_loss_check = next(
            (
                check
                for check in playbook.postchecks or []
                if check.name == hc_types.CheckName.IXIA_PACKET_LOSS_CHECK
            ),
            None,
        )
        if not has_inline_ixia_validation and scenario_packet_loss_check is not None:
            stages = [
                _add_phase_packet_loss_validation(
                    stage,
                    scenario_packet_loss_check,
                )
                for stage in stages
            ]
        postchecks = []
        for check in playbook.postchecks or []:
            if check.name == hc_types.CheckName.IXIA_PACKET_LOSS_CHECK:
                continue
            postchecks.append(check)
        if any("warmboot" in (stage.id or "") for stage in stages):
            postchecks = [
                check
                for check in postchecks
                if check.name != hc_types.CheckName.SERVICE_RESTART_CHECK
            ]
            postchecks.append(
                create_service_restart_check(
                    expected_restarted_services=WEDGE_AGENT_BINDS_TO_CASCADE + ["openr"]
                )
            )
        normalized_playbooks.append(
            playbook(
                prechecks=prechecks,
                stages=stages,
                postchecks=postchecks,
            )
        )

    config_fields = dict(test_config)
    config_fields["basic_traffic_item_configs"] = [
        traffic_config
        for traffic_config in test_config.basic_traffic_item_configs
        if not any(
            traffic_config.name.endswith(suffix)
            for suffix in DISABLED_AUXILIARY_TRAFFIC_SUFFIXES
        )
    ]
    config_fields["playbooks"] = normalized_playbooks
    test_config = taac_types.TestConfig(**config_fields)

    return test_config
