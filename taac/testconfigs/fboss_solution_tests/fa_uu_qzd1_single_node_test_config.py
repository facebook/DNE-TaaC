# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Single-node FA/UU FBOSS qualification TestConfig for the QZD1 lab.

Builds a TestConfig that exercises one FA/UU device with parallel BGP peer config, IXIA
traffic, COOP patcher injection, and a longevity playbook. Used to qualify FBOSS agent
behavior end-to-end on a single FA001-UU001 device prior to multi-node tests.
"""

import json

from ixia.ixia import types as ixia_types
from taac.health_checks.healthcheck_definitions import (
    create_bgp_session_snapshot_check,
    create_core_dumps_snapshot_check,
    create_ixia_packet_loss_check,
    create_port_speed_snapshot_check,
    create_prefix_limit_check,
    create_systemctl_active_state_check,
)
from taac.playbooks.playbook_definitions import (
    build_fa_uu_qzd1_playbook,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_drain_undrain_step,
    create_longevity_step,
    create_service_convergence_step,
    create_service_interruption_step,
)
from taac.task_definitions import (
    create_configure_parallel_bgp_peers_task,
    create_coop_apply_patchers_task,
    create_coop_register_patcher_task,
    create_coop_unregister_patchers_task,
)
from taac.testconfigs.fboss_solution_tests.test_config_for_2_ixia_bgp_and_fboss_platform_hardening_in_conveyor import (
    get_bgp_peer_config_tasks,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import (
    Service,
    ServiceInterruptionTrigger,
    TestConfig,
    TrafficEndpoint,
)


# ============================================================
# Device: fa001-uu002.qzd1 (FA-UU role, QZD1 datacenter)
#
# IXIA Port Mappings:
#   Downlink: eth6/13/1 - FA-DU facing (FADU peer group, AS 7001, confed)
#   Uplink:   eth6/15/1 - EB facing (EB peer group, AS 65272, EBGP)
# ============================================================

DEVICE_NAME = "fa001-uu002.qzd1"
DEVICE_FQDN = "fa001-uu002.qzd1.tfbnw.net"
FAUU_QZD1_IXIA_PORTS = ["eth6/13/1", "eth6/15/1"]

# Single-node endpoint definition
FAUU_QZD1_SINGLE_NODE_ENDPOINTS = [
    taac_types.Endpoint(
        name=DEVICE_NAME,
        dut=True,
        ixia_needed=True,
        ixia_ports=FAUU_QZD1_IXIA_PORTS,
    ),
]

# Traffic endpoints for src/dstfboss2 coop --help
FAUU_QZD1_SRC_TRAFFIC_ENDPOINTS = [
    TrafficEndpoint(name=f"{DEVICE_NAME}:eth6/13/1"),
]

FAUU_QZD1_DST_TRAFFIC_ENDPOINTS = [
    TrafficEndpoint(name=f"{DEVICE_NAME}:eth6/15/1"),
]

# ============================================================
# BGP Setup Tasks (minimal)
# Creates peer groups on the switch and configures 1 BGP peer
# per IXIA port for basic BGP-routed traffic forwarding.
# ============================================================

FAUU_QZD1_SETUP_TASKS = (
    [
        create_coop_unregister_patchers_task(DEVICE_NAME),
        # Configure BGP prefix limit
        create_coop_register_patcher_task(
            hostname=DEVICE_NAME,
            config_names=["bgpcpp", "bgpcpp_softdrain"],
            patcher_name="configure_bgp_switch_limit",
            py_func_name="configure_bgp_switch_limit",
            patcher_args={"prefix_limit": "75000"},
        ),
        # Enable IXIA ports
        create_coop_register_patcher_task(
            hostname=DEVICE_NAME,
            config_name="agent",
            patcher_name="enable_port_all_ixia_ports",
            py_func_name="change_port_admin_state",
            patcher_args={"eth6/13/1": "enable", "eth6/15/1": "enable"},
        ),
    ]
    + get_bgp_peer_config_tasks(
        # Create peer groups (PEERGROUP_FAUU_EB_V6, PEERGROUP_FAUU_FADU_V6, etc.)
        # and configure per-peer route limits on the switch
        device_name=DEVICE_NAME,
        peergroup_downlink_mimic_v6="PEERGROUP_FAUU_FADU_V6",
        peergroup_uplink_mimic_v6="PEERGROUP_FAUU_EB_V6",
        peergroup_uplink_mimic_v4="PEERGROUP_FAUU_EB_V4",
        peergroup_downlink_mimic_v4="PEERGROUP_FAUU_FADU_V4",
        is_downlink_peer_confed="True",
        is_uplink_peer_confed="False",
        per_peer_max_route_limit="25000",
        uplink_peer_tag="EB",
        downlink_peer_tag="FADU",
        route_map_uplink_ingress="PROPAGATE_FAUU_EB_IN",
        route_map_uplink_egress="PROPAGATE_FAUU_EB_OUT",
        route_map_downlink_ingress="PROPAGATE_FAUU_FADU_IN",
        route_map_downlink_egress="PROPAGATE_FAUU_FADU_OUT",
        ecmp_group_overflow_prefix="7000",
        v6_uplink_prefix="6200",
    )
    + [
        # Apply peer group patchers to bgpd
        create_coop_apply_patchers_task(
            hostnames=[DEVICE_NAME],
            config_name="bgpcpp",
        ),
        # Configure downlink BGP peer (IXIA mimics FADU on eth6/13/1)
        create_configure_parallel_bgp_peers_task(
            hostname=DEVICE_NAME,
            configure_vlans_patcher_name="configure_vlans_downlink",
            add_bgp_peers_patcher_name="add_bgp_peers_downlink",
            config_json=json.dumps(
                {
                    "eth6/13/1": [
                        {
                            "starting_ip": "2401:db00:e50d:11:8::10",
                            "increment_ip": "0:0:0:0::2",
                            "prefix_length": 127,
                            "description": "Downlink IPv6 Peer (FADU)",
                            "peer_group_name": "PEERGROUP_FAUU_FADU_V6",
                            "num_sessions": 1,
                            "remote_as_4_byte": 7001,
                            "remote_as_4_byte_step": 0,
                            "gateway_starting_ip": "2401:db00:e50d:11:8::11",
                            "gateway_increment_ip": "0:0:0:0::2",
                        },
                    ]
                }
            ),
        ),
        # Configure uplink BGP peer (IXIA mimics EB on eth6/15/1)
        create_configure_parallel_bgp_peers_task(
            hostname=DEVICE_NAME,
            configure_vlans_patcher_name="configure_vlans_uplink",
            add_bgp_peers_patcher_name="add_bgp_peers_uplink",
            config_json=json.dumps(
                {
                    "eth6/15/1": [
                        {
                            "starting_ip": "2401:db00:e50d:11:9::10",
                            "increment_ip": "0:0:0:0::2",
                            "prefix_length": 127,
                            "description": "Uplink IPv6 Peer (EB)",
                            "peer_group_name": "PEERGROUP_FAUU_EB_V6",
                            "num_sessions": 1,
                            "remote_as_4_byte": 65272,
                            "remote_as_4_byte_step": 0,
                            "gateway_starting_ip": "2401:db00:e50d:11:9::11",
                            "gateway_increment_ip": "0:0:0:0::2",
                        },
                    ]
                }
            ),
        ),
        # Apply all patchers with warmboot
        create_coop_apply_patchers_task(
            hostnames=[DEVICE_NAME],
            do_warmboot=True,
        ),
    ]
)

# Teardown tasks - cleanup patchers after test
FAUU_QZD1_TEARDOWN_TASKS = [
    create_coop_unregister_patchers_task(DEVICE_NAME),
]

# IXIA port configs with BGP (IXIA side)
# Note: endpoint uses FQDN to match TAAC's auto-discovered hostname
FAUU_QZD1_PORT_CONFIGS = [
    # Downlink port - IXIA acts as FADU (AS 7001, confederation)
    taac_types.BasicPortConfig(
        endpoint=f"{DEVICE_FQDN}:eth6/13/1",
        device_group_configs=[
            taac_types.DeviceGroupConfig(
                device_group_index=0,
                v6_bgp_config=taac_types.BgpConfig(
                    local_as_4_bytes=7001,
                    enable_4_byte_local_as=True,
                    is_confed=True,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                    route_scales=[
                        taac_types.RouteScaleSpec(
                            v6_route_scale=taac_types.RouteScale(
                                multiplier=1,
                                prefix_count=100,
                                prefix_length=64,
                                starting_prefixes="3100:1::",
                                bgp_communities=["65529:34810", "65441:133"],
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                            ),
                        )
                    ],
                    graceful_restart_timer=180,
                ),
            )
        ],
    ),
    # Uplink port - IXIA acts as EB (AS 65272, EBGP)
    taac_types.BasicPortConfig(
        endpoint=f"{DEVICE_FQDN}:eth6/15/1",
        device_group_configs=[
            taac_types.DeviceGroupConfig(
                device_group_index=0,
                v6_bgp_config=taac_types.BgpConfig(
                    local_as_4_bytes=65272,
                    enable_4_byte_local_as=True,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                    route_scales=[
                        taac_types.RouteScaleSpec(
                            v6_route_scale=taac_types.RouteScale(
                                multiplier=1,
                                prefix_count=100,
                                prefix_length=64,
                                starting_prefixes="6200:1::",
                                bgp_communities=[
                                    "65441:133",
                                    "65442:135",
                                    "65526:35724",
                                ],
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                            ),
                        )
                    ],
                    graceful_restart_timer=180,
                ),
            )
        ],
    ),
]

# Reusable traffic item config
FAUU_QZD1_TRAFFIC_ITEM_CONFIGS = [
    taac_types.BasicTrafficItemConfig(
        name="FA_UU_QZD1_LONGEVITY_TRAFFIC",
        src_endpoints=FAUU_QZD1_SRC_TRAFFIC_ENDPOINTS,
        dest_endpoints=FAUU_QZD1_DST_TRAFFIC_ENDPOINTS,
        line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
        line_rate=99,
        traffic_type=ixia_types.TrafficType.IPV6,
        bidirectional=True,
    ),
]

# Reusable packet loss check (0% loss threshold)
IXIA_PACKET_LOSS_CHECK = create_ixia_packet_loss_check(
    thresholds=[
        hc_types.PacketLossThreshold(
            names=["FA_UU_QZD1_LONGEVITY_TRAFFIC"],
            str_value="0",
            metric=hc_types.PacketLossMetric.PERCENTAGE,
        ),
    ],
)

# Packet loss postcheck for disruptive tests (clears stats after disruption,
# only measures loss during post-convergence soak period)
IXIA_PACKET_LOSS_POSTCHECK_CLEAR_STATS = create_ixia_packet_loss_check(
    clear_traffic_stats=True,
)

# Reusable snapshot checks
FAUU_QZD1_SNAPSHOT_CHECKS = [
    create_bgp_session_snapshot_check(),
    create_core_dumps_snapshot_check(),
    create_port_speed_snapshot_check(
        json_params={"endpoints": {DEVICE_NAME: FAUU_QZD1_IXIA_PORTS}},
    ),
]

# Snapshot checks for disruptive tests (skip BGP flap check since
# we intentionally restart services which causes expected flaps)
FAUU_QZD1_DISRUPTIVE_SNAPSHOT_CHECKS = [
    create_bgp_session_snapshot_check(
        skip_flap_check=True,
        skip_uptime_check=True,
    ),
    create_core_dumps_snapshot_check(),
    create_port_speed_snapshot_check(
        json_params={"endpoints": {DEVICE_NAME: FAUU_QZD1_IXIA_PORTS}},
    ),
]

# ============================================================
# Milestone 1: Longevity Test
# 240-second longevity soak with IXIA traffic running
# Validates: packet loss, BGP peer state, core dumps, port speed
# ============================================================

FA_UU_QZD1_SINGLE_NODE_LONGEVITY_TEST_CONFIG = TestConfig(
    name="FA_UU_QZD1_SINGLE_NODE_LONGEVITY_TEST_CONFIG",
    basset_pool="dne.regression",
    endpoints=FAUU_QZD1_SINGLE_NODE_ENDPOINTS,
    basic_traffic_item_configs=FAUU_QZD1_TRAFFIC_ITEM_CONFIGS,
    basic_port_configs=FAUU_QZD1_PORT_CONFIGS,
    setup_tasks=FAUU_QZD1_SETUP_TASKS,
    teardown_tasks=FAUU_QZD1_TEARDOWN_TASKS,
    playbooks=[
        build_fa_uu_qzd1_playbook(
            name="test_fa_uu_qzd1_longevity",
            stages=[
                create_steps_stage(
                    steps=[
                        create_longevity_step(duration=240),
                    ]
                )
            ],
            postchecks=[
                IXIA_PACKET_LOSS_CHECK,
            ],
            traffic_items_to_start=["FA_UU_QZD1_LONGEVITY_TRAFFIC"],
            enabled=True,
            snapshot_checks=FAUU_QZD1_SNAPSHOT_CHECKS,
        ),
    ],
    # Deprecated - define at playbook level
)

# ============================================================
# Milestone 2: Disruptive Tests
# BGP restart, Wedge agent restart, Drain/undrain
# Coldboot deferred pending framework fix (convert_to_async bug)
# ============================================================

FA_UU_QZD1_SINGLE_NODE_DISRUPTIVE_TEST_CONFIG = TestConfig(
    name="FA_UU_QZD1_SINGLE_NODE_DISRUPTIVE_TEST_CONFIG",
    basset_pool="dne.regression",
    endpoints=FAUU_QZD1_SINGLE_NODE_ENDPOINTS,
    basic_traffic_item_configs=FAUU_QZD1_TRAFFIC_ITEM_CONFIGS,
    basic_port_configs=FAUU_QZD1_PORT_CONFIGS,
    setup_tasks=FAUU_QZD1_SETUP_TASKS,
    teardown_tasks=FAUU_QZD1_TEARDOWN_TASKS,
    playbooks=[
        # Coldboot: agent cold restart → convergence → longevity soak
        build_fa_uu_qzd1_playbook(
            name="test_fa_uu_qzd1_coldboot",
            prechecks=[
                create_systemctl_active_state_check(),
                IXIA_PACKET_LOSS_CHECK,
            ],
            stages=[
                create_steps_stage(
                    steps=[
                        create_service_interruption_step(
                            service=Service.AGENT,
                            trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                            create_cold_boot_file=True,
                        ),
                        create_service_convergence_step(
                            services=[Service.AGENT, Service.BGP],
                        ),
                        create_longevity_step(duration=180),
                    ]
                )
            ],
            postchecks=[
                IXIA_PACKET_LOSS_POSTCHECK_CLEAR_STATS,
                create_systemctl_active_state_check(),
                create_prefix_limit_check(),
            ],
            traffic_items_to_start=["FA_UU_QZD1_LONGEVITY_TRAFFIC"],
            enabled=True,
            snapshot_checks=FAUU_QZD1_DISRUPTIVE_SNAPSHOT_CHECKS,
        ),
        # BGP daemon restart: bgpd restart → convergence → verify peer recovery
        build_fa_uu_qzd1_playbook(
            name="test_fa_uu_qzd1_bgpd_restart",
            prechecks=[
                create_systemctl_active_state_check(),
                IXIA_PACKET_LOSS_CHECK,
            ],
            stages=[
                create_steps_stage(
                    steps=[
                        create_service_interruption_step(
                            service=Service.BGP,
                            trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                        ),
                        create_service_convergence_step(
                            services=[Service.BGP],
                        ),
                        create_longevity_step(duration=180),
                    ]
                )
            ],
            postchecks=[
                IXIA_PACKET_LOSS_CHECK,
                create_systemctl_active_state_check(),
                create_prefix_limit_check(),
            ],
            traffic_items_to_start=["FA_UU_QZD1_LONGEVITY_TRAFFIC"],
            enabled=True,
            snapshot_checks=FAUU_QZD1_DISRUPTIVE_SNAPSHOT_CHECKS,
        ),
        # Wedge agent restart: FBOSS agent restart → convergence → verify traffic recovery
        build_fa_uu_qzd1_playbook(
            name="test_fa_uu_qzd1_agent_restart",
            prechecks=[
                create_systemctl_active_state_check(),
                IXIA_PACKET_LOSS_CHECK,
            ],
            stages=[
                create_steps_stage(
                    steps=[
                        create_service_interruption_step(
                            service=Service.AGENT,
                            trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                        ),
                        create_service_convergence_step(
                            services=[Service.AGENT],
                        ),
                        create_longevity_step(duration=180),
                    ]
                )
            ],
            postchecks=[
                IXIA_PACKET_LOSS_POSTCHECK_CLEAR_STATS,
                create_systemctl_active_state_check(),
                create_prefix_limit_check(),
            ],
            traffic_items_to_start=["FA_UU_QZD1_LONGEVITY_TRAFFIC"],
            enabled=True,
            snapshot_checks=FAUU_QZD1_DISRUPTIVE_SNAPSHOT_CHECKS,
        ),
        # Drain/undrain: drain → longevity → undrain → longevity
        build_fa_uu_qzd1_playbook(
            name="test_fa_uu_qzd1_drain_undrain",
            prechecks=[
                create_systemctl_active_state_check(),
                IXIA_PACKET_LOSS_CHECK,
            ],
            stages=[
                create_steps_stage(
                    steps=[
                        create_drain_undrain_step(drain=True),
                        create_longevity_step(duration=180),
                        create_drain_undrain_step(drain=False),
                        create_longevity_step(duration=180),
                    ]
                )
            ],
            postchecks=[
                IXIA_PACKET_LOSS_POSTCHECK_CLEAR_STATS,
                create_systemctl_active_state_check(),
                create_prefix_limit_check(),
            ],
            traffic_items_to_start=["FA_UU_QZD1_LONGEVITY_TRAFFIC"],
            enabled=True,
            snapshot_checks=FAUU_QZD1_DISRUPTIVE_SNAPSHOT_CHECKS,
        ),
    ],
    # Deprecated - define at playbook level
)

FA_UU_QZD1_TEST_CONFIGS = [
    FA_UU_QZD1_SINGLE_NODE_LONGEVITY_TEST_CONFIG,
    FA_UU_QZD1_SINGLE_NODE_DISRUPTIVE_TEST_CONFIG,
]
