# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Single-node qualification config for stsw003.qza1.

Covers CPU-queue classification and service-disruption recovery.
"""

from __future__ import annotations

from ixia.ixia import types as ixia_types
from taac.health_checks.constants import (
    SERVICES_TO_MONITOR_DURING_AGENT_RESTART,
    SERVICES_TO_MONITOR_DURING_BGP_RESTART,
    SERVICES_TO_MONITOR_DURING_FSDB_RESTART,
    SERVICES_TO_MONITOR_DURING_QSFP_SERVICE_RESTART,
)
from taac.health_checks.healthcheck_definitions import (
    create_bgp_session_establish_check,
    create_bgp_session_snapshot_check,
    create_core_dumps_snapshot_check,
    create_cpu_queue_snapshot_check,
    create_ixia_packet_loss_check,
    create_port_speed_snapshot_check,
    create_service_restart_check,
    create_systemctl_active_state_check,
    create_unclean_exit_check,
)
from taac.packet_headers import (
    BGP_CP_V6_GLOBAL_DSCP48_TRAFFIC_PACKET_HEADERS,
)
from taac.playbooks.playbook_definitions import (
    build_fa_uu_qzd1_playbook,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_ixia_api_step,
    create_longevity_step,
    create_service_convergence_step,
    create_service_interruption_step,
)
from taac.testconfigs.hyperport.hyperport_snc_bag_test_configs import (
    create_basic_port_config,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types


DEVICE_NAME: str = "stsw003.s001.l201.qza1"
DEVICE_MAC_ADDRESS: str = "8a:5a:23:a6:5c:98"
IXIA_PORTS: list[str] = ["eth1/63/1", "eth1/63/5"]
IXIA_PEER_ADDRESSES: list[str] = [
    "2401:db00:2d1b:d8e0::",
    "2401:db00:2d1b:d8e0::2",
]
IXIA_PEER_AS: int = 65342
BGP_COMMUNITIES: list[str] = ["65529:52780", "65529:52779", "65520:52791"]
TRAFFIC_ITEM_NAME: str = "STSW003_QZA1_DISRUPTIVE_TRAFFIC"
BGP_CP_V6_TRAFFIC_ITEM_NAME: str = "STSW003_QZA1_BGP_CP_V6_GLOBAL_DSCP48_TRAFFIC"
UNAVAILABLE_SERVICES: set[str] = {"openr"}
POST_CONVERGENCE_SOAK_SECONDS: int = 180
PACKET_LOSS_MEASUREMENT_SECONDS: int = 60
PACKET_LOSS_STATS_DRAIN_SECONDS: int = 60
CPU_QUEUE_SOAK_SECONDS: int = 60

# CPU queue indices for MONTBLANC (Minipack3, TH5), matching the mapping in
# `get_cpu_queue_constants()` in `testconfigs/npi/cpu_queue_test_config.py`.
LOW_CPU_QUEUE: int = 0
MID_CPU_QUEUE: int = 2
HIGH_CPU_QUEUE: int = 9

# A2-leakage tolerance for the queues that must stay idle while BGP CP traffic
# runs. Background control traffic ticks every CPU queue, so each idle queue
# gets the same baseline plus per-session budget `create_cpu_queue_playbooks()`
# uses (100 pps floor, +20/session low, +5/session mid), sized for the two IXIA
# BGP sessions this config establishes.
LOW_CPU_QUEUE_NOISE_PPS: int = 140
MID_CPU_QUEUE_NOISE_PPS: int = 110

# (DUT port, IXIA peer address, DUT gateway address, advertised prefix)
PORT_CONFIG_DATA: list[tuple[str, str, str, str]] = [
    ("eth1/63/1", "2401:db00:2d1b:d8e0::", "2401:db00:2d1b:d8e0::1", "7000:2:1::"),
    (
        "eth1/63/5",
        "2401:db00:2d1b:d8e0::2",
        "2401:db00:2d1b:d8e0::3",
        "7000:2:2::",
    ),
]

ENDPOINTS: list[taac_types.Endpoint] = [
    taac_types.Endpoint(
        name=DEVICE_NAME,
        dut=True,
        ixia_needed=True,
        ixia_ports=IXIA_PORTS,
        mac_address=DEVICE_MAC_ADDRESS,
    ),
]

SOURCE_TRAFFIC_ENDPOINTS: list[taac_types.TrafficEndpoint] = [
    taac_types.TrafficEndpoint(
        name=f"{DEVICE_NAME}:eth1/63/1",
        network_group_index=0,
        device_group_index=0,
    ),
]
DESTINATION_TRAFFIC_ENDPOINTS: list[taac_types.TrafficEndpoint] = [
    taac_types.TrafficEndpoint(
        name=f"{DEVICE_NAME}:eth1/63/5",
        network_group_index=0,
        device_group_index=0,
    ),
]

BASIC_PORT_CONFIGS: list[taac_types.BasicPortConfig] = [
    create_basic_port_config(
        endpoint=f"{DEVICE_NAME}:{port}",
        starting_ip=ixia_ip,
        gateway_ip=gateway_ip,
        local_as=IXIA_PEER_AS,
        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
        starting_prefixes=starting_prefix,
        bgp_communities=BGP_COMMUNITIES,
        prefix_count=100,
        prefix_length=64,
    )
    for port, ixia_ip, gateway_ip, starting_prefix in PORT_CONFIG_DATA
]

TRAFFIC_ITEM_CONFIGS: list[taac_types.BasicTrafficItemConfig] = [
    taac_types.BasicTrafficItemConfig(
        name=TRAFFIC_ITEM_NAME,
        src_endpoints=SOURCE_TRAFFIC_ENDPOINTS,
        dest_endpoints=DESTINATION_TRAFFIC_ENDPOINTS,
        line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
        line_rate=99,
        traffic_type=ixia_types.TrafficType.IPV6,
        src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
        bidirectional=True,
        tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
    ),
    # CPU_002: BGPv6 control plane (global SIP/DIP, DSCP 48, TCP/179) addressed
    # to the DUT itself, so it is punted to the CPU rather than forwarded back
    # to IXIA. Packet-loss thresholds do not apply to this item.
    taac_types.BasicTrafficItemConfig(
        name=BGP_CP_V6_TRAFFIC_ITEM_NAME,
        src_endpoints=SOURCE_TRAFFIC_ENDPOINTS,
        dest_endpoints=DESTINATION_TRAFFIC_ENDPOINTS,
        line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
        line_rate=2000,
        traffic_type=ixia_types.TrafficType.RAW,
        bidirectional=False,
        packet_headers=BGP_CP_V6_GLOBAL_DSCP48_TRAFFIC_PACKET_HEADERS,
    ),
]


def _bgp_and_service_checks() -> list[taac_types.PointInTimeHealthCheck]:
    return [
        create_bgp_session_establish_check(
            ignore_all_prefixes_except=IXIA_PEER_ADDRESSES,
            expected_established_sessions=2,
        ),
        create_systemctl_active_state_check(),
    ]


def _prechecks() -> list[taac_types.PointInTimeHealthCheck]:
    return [
        *_bgp_and_service_checks(),
        create_ixia_packet_loss_check(
            thresholds=[
                hc_types.PacketLossThreshold(
                    names=[TRAFFIC_ITEM_NAME],
                    str_value="0",
                    metric=hc_types.PacketLossMetric.DURATION,
                ),
            ],
            sleep_time=PACKET_LOSS_STATS_DRAIN_SECONDS,
        ),
    ]


def _postchecks(
    services_to_monitor: list[str],
) -> list[taac_types.PointInTimeHealthCheck]:
    available_services = [
        service
        for service in services_to_monitor
        if service not in UNAVAILABLE_SERVICES
    ]
    return [
        create_ixia_packet_loss_check(
            thresholds=[
                hc_types.PacketLossThreshold(
                    names=[TRAFFIC_ITEM_NAME],
                    str_value="0",
                    metric=hc_types.PacketLossMetric.DURATION,
                ),
            ],
            sleep_time=PACKET_LOSS_STATS_DRAIN_SECONDS,
        ),
        create_bgp_session_establish_check(
            ignore_all_prefixes_except=IXIA_PEER_ADDRESSES,
            expected_established_sessions=2,
        ),
        create_service_restart_check(services=available_services),
        create_systemctl_active_state_check(),
        create_unclean_exit_check(),
    ]


def _cpu_queue_postchecks() -> list[taac_types.PointInTimeHealthCheck]:
    return [
        *_bgp_and_service_checks(),
        create_unclean_exit_check(),
    ]


def _snapshot_checks() -> list[taac_types.SnapshotHealthCheck]:
    return [
        create_bgp_session_snapshot_check(
            skip_flap_check=True,
            skip_uptime_check=True,
        ),
        create_core_dumps_snapshot_check(),
        create_port_speed_snapshot_check(
            json_params={"endpoints": {DEVICE_NAME: IXIA_PORTS}},
        ),
    ]


def _cpu_queue_snapshot_checks() -> list[taac_types.SnapshotHealthCheck]:
    return [
        create_cpu_queue_snapshot_check(
            active_queues=[HIGH_CPU_QUEUE],
            inactive_queues=[LOW_CPU_QUEUE, MID_CPU_QUEUE],
            inactive_max_pps_per_queue={
                LOW_CPU_QUEUE: LOW_CPU_QUEUE_NOISE_PPS,
                MID_CPU_QUEUE: MID_CPU_QUEUE_NOISE_PPS,
            },
            no_discard_queues=[HIGH_CPU_QUEUE],
        ),
        create_core_dumps_snapshot_check(),
    ]


def _post_convergence_steps() -> list[taac_types.Step]:
    return [
        create_longevity_step(
            duration=(
                POST_CONVERGENCE_SOAK_SECONDS
                - PACKET_LOSS_MEASUREMENT_SECONDS
                - PACKET_LOSS_STATS_DRAIN_SECONDS
            ),
            description="Allow services and traffic to settle after convergence",
        ),
        create_ixia_api_step(
            api_name="clear_traffic_stats",
            args_dict={"wait_for_refresh": True},
            description="Clear IXIA statistics before the loss measurement window",
        ),
        create_longevity_step(
            duration=PACKET_LOSS_MEASUREMENT_SECONDS,
            description="Measure post-convergence packet loss",
        ),
    ]


STSW003_QZA1_SINGLE_NODE_TEST_CONFIG = taac_types.TestConfig(
    name="STSW003_QZA1_SINGLE_NODE_TEST_CONFIG",
    basset_pool="dne.regression",
    basset_reservation_time_hr=4,
    ixia_protocol_verification_timeout=90,
    endpoints=ENDPOINTS,
    basic_port_configs=BASIC_PORT_CONFIGS,
    basic_traffic_item_configs=TRAFFIC_ITEM_CONFIGS,
    setup_tasks=[],
    teardown_tasks=[],
    playbooks=[
        build_fa_uu_qzd1_playbook(
            name="test_stsw003_qza1_bgp_cp_v6_global_dscp48_to_high_queue",
            prechecks=_bgp_and_service_checks(),
            stages=[
                create_steps_stage(
                    steps=[
                        create_longevity_step(
                            duration=CPU_QUEUE_SOAK_SECONDS,
                            description="Soak BGPv6 CP traffic against the CPU",
                        ),
                    ],
                ),
            ],
            postchecks=_cpu_queue_postchecks(),
            traffic_items_to_start=[BGP_CP_V6_TRAFFIC_ITEM_NAME],
            enabled=True,
            snapshot_checks=_cpu_queue_snapshot_checks(),
        ),
        build_fa_uu_qzd1_playbook(
            name="test_stsw003_qza1_coldboot",
            prechecks=_prechecks(),
            stages=[
                create_steps_stage(
                    steps=[
                        create_service_interruption_step(
                            service=taac_types.Service.AGENT,
                            trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                            create_cold_boot_file=True,
                        ),
                        create_service_convergence_step(
                            services=[taac_types.Service.AGENT, taac_types.Service.BGP],
                        ),
                        *_post_convergence_steps(),
                    ],
                ),
            ],
            postchecks=_postchecks(SERVICES_TO_MONITOR_DURING_AGENT_RESTART),
            traffic_items_to_start=[TRAFFIC_ITEM_NAME],
            enabled=True,
            snapshot_checks=_snapshot_checks(),
        ),
        build_fa_uu_qzd1_playbook(
            name="test_stsw003_qza1_bgpd_restart",
            prechecks=_prechecks(),
            stages=[
                create_steps_stage(
                    steps=[
                        create_service_interruption_step(
                            service=taac_types.Service.BGP,
                            trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                        ),
                        create_service_convergence_step(
                            services=[taac_types.Service.BGP],
                        ),
                        *_post_convergence_steps(),
                    ],
                ),
            ],
            postchecks=_postchecks(SERVICES_TO_MONITOR_DURING_BGP_RESTART),
            traffic_items_to_start=[TRAFFIC_ITEM_NAME],
            enabled=True,
            snapshot_checks=_snapshot_checks(),
        ),
        build_fa_uu_qzd1_playbook(
            name="test_stsw003_qza1_agent_restart",
            prechecks=_prechecks(),
            stages=[
                create_steps_stage(
                    steps=[
                        create_service_interruption_step(
                            service=taac_types.Service.AGENT,
                            trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                        ),
                        create_service_convergence_step(
                            services=[taac_types.Service.AGENT, taac_types.Service.BGP],
                        ),
                        *_post_convergence_steps(),
                    ],
                ),
            ],
            postchecks=_postchecks(SERVICES_TO_MONITOR_DURING_AGENT_RESTART),
            traffic_items_to_start=[TRAFFIC_ITEM_NAME],
            enabled=True,
            snapshot_checks=_snapshot_checks(),
        ),
        build_fa_uu_qzd1_playbook(
            name="test_stsw003_qza1_fsdb_restart",
            prechecks=_prechecks(),
            stages=[
                create_steps_stage(
                    steps=[
                        create_service_interruption_step(
                            service=taac_types.Service.FSDB,
                            trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                        ),
                        create_service_convergence_step(
                            services=[
                                taac_types.Service.AGENT,
                                taac_types.Service.FSDB,
                            ],
                        ),
                        *_post_convergence_steps(),
                    ],
                ),
            ],
            postchecks=_postchecks(SERVICES_TO_MONITOR_DURING_FSDB_RESTART),
            traffic_items_to_start=[TRAFFIC_ITEM_NAME],
            enabled=True,
            snapshot_checks=_snapshot_checks(),
        ),
        build_fa_uu_qzd1_playbook(
            name="test_stsw003_qza1_qsfp_restart",
            prechecks=_prechecks(),
            stages=[
                create_steps_stage(
                    steps=[
                        create_service_interruption_step(
                            service=taac_types.Service.QSFP_SERVICE,
                            trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                        ),
                        create_service_convergence_step(
                            services=[taac_types.Service.QSFP_SERVICE],
                        ),
                        *_post_convergence_steps(),
                    ],
                ),
            ],
            postchecks=_postchecks(SERVICES_TO_MONITOR_DURING_QSFP_SERVICE_RESTART),
            traffic_items_to_start=[TRAFFIC_ITEM_NAME],
            enabled=True,
            snapshot_checks=_snapshot_checks(),
        ),
    ],
)
