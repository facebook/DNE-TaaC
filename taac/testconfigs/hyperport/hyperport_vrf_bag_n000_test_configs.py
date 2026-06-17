# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
Hyperport VRF BAG Test Configuration (N000 + BAG only)

Stripped-down version of hyperport_vrf_bag_test_configs that only uses
edsw003.n000 and bag001.snc1 (no edsw003.n001). Longevity test only.

Topology diagram: https://www.internalfb.com/intern/px/p/8Wv9v/

Topology:
  IXIA <-> EDSW003 N000 (IBGP AS 65061) <-> [fabric] <-> BAG001.SNC1 (EBGP AS 65063) <-> IXIA
    eth1/17/1: prefix 4000:3:2:5000::/64      vrf1 (ports 9-12):  4000:3:2:X000::/64
    eth1/23/1: prefix 4000:3:2:6000::/64      vrf2 (ports 13-16): 4000:3:1:X000::/64

BAG static routes:
  vrf1: ipv6 route 4000:3:1::/48 2401:db00:11b:d8a1::91    (-> vrf2)
  vrf2: ipv6 route vrf dest_bag 4000:3:2::/48 2401:db00:11b:d8a1::99  (-> vrf1)

N000 prefixes use 4000:3:2:5000::/6000:: (within 4000:3:2::/48) so return
traffic from BAG vrf2 matches the existing static route. Original 6000:1:1::
prefixes were unreachable from BAG vrf2 causing 50% traffic loss on
bidirectional EDSW<->BAG items.

EDSW-to-BAG traffic items use unidirectional RDMA_IB (DSCP 56, UDP 4791,
IB BTH) via create_dsf_proto_ipv6_traffic_config.
"""

import typing as t

from ixia.ixia import types as ixia_types
from taac.driver.driver_constants import (
    ARISTA_CRITICAL_SAND_AGENTS,
)
from taac.health_checks.healthcheck_definitions import (
    create_bgp_session_snapshot_check,
    create_clear_counters_check,
    create_core_dumps_snapshot_check,
    create_dsf_drain_state_check,
    create_ixia_packet_loss_check,
    create_port_channel_state_snapshot_check,
    create_port_state_check,
    create_service_restart_check,
    create_unclean_exit_check,
)
from taac.packet_headers import TC2_PFC_PAUSE_PACKET_HEADERS
from taac.playbooks.playbook_definitions import (
    build_hyperport_vrf_bag_n000_playbook,
    create_dsf_pfc_check,
    create_dsf_proto_ipv6_traffic_config,
    create_packet_loss_check,
    create_pfc_pause_traffic_config,
    create_pfc_wd_check,
    get_pfc_wd_params,
    IXIA_ENABLE_PFC_PORT_CONFIG,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_arista_custom_agents_service_interruption_step,
    create_longevity_step,
)
from taac.testconfigs.hyperport.hyperport_snc_bag_test_configs import (
    create_basic_port_config,
    EDSW003_N000_PORT_CONFIG_DATA,
    EDSW_BGP_COMMUNITIES,
    N000_PORT_17_1_ENDPOINT,
    N000_PORT_23_1_ENDPOINT,
)
from taac.testconfigs.hyperport.hyperport_vrf_bag_test_configs import (
    BAG_DEST_PORT_13_ENDPOINT,
    BAG_DEST_PORT_14_ENDPOINT,
    BAG_SRC_PORT_10_ENDPOINT,
    BAG_SRC_PORT_9_ENDPOINT,
    VRF_BAG_BASIC_PORT_CONFIGS,
    VRF_BAG_ENDPOINTS,
    VRF_BAG_TRAFFIC_ITEM_CONFIGS,
    VRF_BAG_TRAFFIC_ITEM_CONFIGS_100PCT,
    VRF_DSF_TRAFFIC_ITEM_CONFIGS,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config.types import (
    Endpoint,
    Playbook,
    ServiceInterruptionTrigger,
    TestConfig,
)


# Hyperport uplink interfaces to monitor for AdminState/LinkState consistency
EDSW_N000_HYPERPORT_INTERFACES = [
    {"switch_name": "edsw003.n000.l201.snc1", "interface_name": "hyp1/1/1"},
    {"switch_name": "edsw003.n000.l201.snc1", "interface_name": "hyp1/1/2"},
    {"switch_name": "edsw003.n000.l201.snc1", "interface_name": "hyp1/1/3"},
    {"switch_name": "edsw003.n000.l201.snc1", "interface_name": "hyp1/1/4"},
]


# EDSW003 N000 only endpoint
EDSW003_N000_IXIA_PORTS = [port for port, _, _, _ in EDSW003_N000_PORT_CONFIG_DATA]

N000_ENDPOINT = Endpoint(
    name="edsw003.n000.l201.snc1",
    dut=False,
    ixia_ports=EDSW003_N000_IXIA_PORTS,
)

# N000 port config with corrected prefixes (within 4000:3:2::/48 for VRF routing)
# Original 6000:1:1::/6000:1:2:: prefixes are unreachable from BAG vrf2 because
# the static route only covers 4000:3:2::/48. Using 4000:3:2:5000::/6000:: ensures
# return traffic from BAG vrf2 matches the existing static route.
N000_VRF_PORT_CONFIG_DATA = [
    ("eth1/17/1", "2401:db00:11b:d8a0::1", "2401:db00:11b:d8a0::", "4000:3:2:5000::"),
    ("eth1/23/1", "2401:db00:11b:d8a1::1", "2401:db00:11b:d8a1::", "4000:3:2:6000::"),
]

# N000 port configs using VRF-compatible prefixes
N000_BASIC_PORT_CONFIGS = [
    create_basic_port_config(
        endpoint=f"edsw003.n000.l201.snc1:{port}",
        starting_ip=ixia_ip,
        gateway_ip=gateway_ip,
        local_as=65061,
        bgp_peer_type=ixia_types.BgpPeerType.IBGP,
        starting_prefixes=prefix,
        bgp_communities=EDSW_BGP_COMMUNITIES,
        l1_config=IXIA_ENABLE_PFC_PORT_CONFIG.l1_config,
    )
    for port, ixia_ip, gateway_ip, prefix in N000_VRF_PORT_CONFIG_DATA
]

# Unidirectional RDMA EDSW-to-BAG traffic items (N000 -> BAG)
N000_RDMA_EDSW_TO_BAG_TRAFFIC_ITEM_CONFIGS = [
    create_dsf_proto_ipv6_traffic_config(
        proto="RDMA_IB",
        src_endpoints=[N000_PORT_17_1_ENDPOINT],
        dest_endpoints=[BAG_DEST_PORT_13_ENDPOINT],
        name="RDMA_N000_17_TO_BAG_13",
        line_rate=99,
    ),
    create_dsf_proto_ipv6_traffic_config(
        proto="RDMA_IB",
        src_endpoints=[N000_PORT_17_1_ENDPOINT],
        dest_endpoints=[BAG_DEST_PORT_14_ENDPOINT],
        name="RDMA_N000_17_TO_BAG_14",
        line_rate=99,
    ),
    create_dsf_proto_ipv6_traffic_config(
        proto="RDMA_IB",
        src_endpoints=[N000_PORT_23_1_ENDPOINT],
        dest_endpoints=[BAG_DEST_PORT_13_ENDPOINT],
        name="RDMA_N000_23_TO_BAG_13",
        line_rate=99,
    ),
    create_dsf_proto_ipv6_traffic_config(
        proto="RDMA_IB",
        src_endpoints=[N000_PORT_23_1_ENDPOINT],
        dest_endpoints=[BAG_DEST_PORT_14_ENDPOINT],
        name="RDMA_N000_23_TO_BAG_14",
        line_rate=99,
    ),
]

# PFC Watchdog test configuration. BAG IXIA-facing ports are 800G in this topology;
# get_pfc_wd_params returns the FPS pair and WD high/low frame thresholds.
PFC_WD_PORT_SPEED = 800
PFC_WD_TRAFFIC_DURATION_SEC = 60
_PFC_WD_PARAMS = get_pfc_wd_params(port_speed=PFC_WD_PORT_SPEED)
PFC_WD_VICTIM_INTERFACES = [BAG_SRC_PORT_9_ENDPOINT]

# TC2 PFC pause traffic items (high + low FPS) used by the PFC watchdog playbooks.
# IXIA emits L2 RAW pause frames from BAG_SRC_PORT_9_ENDPOINT; BAG observes them as
# INCOMING on Ethernet5/9/1 which is what the watchdog timer measures.
PFC_WD_PAUSE_TRAFFIC_ITEMS = [
    create_pfc_pause_traffic_config(
        src_endpoints=[BAG_SRC_PORT_9_ENDPOINT],
        dest_endpoints=[BAG_DEST_PORT_13_ENDPOINT],
        name=f"TRAFFIC_TC2_PFC_PAUSE_{fr}FPS",
        line_rate=fr,
        packet_headers=TC2_PFC_PAUSE_PACKET_HEADERS,
    )
    for fr in _PFC_WD_PARAMS["pfc_pause_frame_rates"]
]

# BE traffic from src 10 -> dst 13 used only by test_tc2_pfc_wd_functionality_non_impact_tc1
# to verify a TC2 PFC storm does not starve TC1/BE.
PFC_WD_BE_TRAFFIC_ITEM = create_dsf_proto_ipv6_traffic_config(
    proto="BE",
    src_endpoints=[BAG_SRC_PORT_10_ENDPOINT],
    dest_endpoints=[BAG_DEST_PORT_13_ENDPOINT],
    name="TEST_BE_24_TRAFFIC",
    line_rate=24,
)

PFC_WD_TRAFFIC_ITEM_CONFIGS = PFC_WD_PAUSE_TRAFFIC_ITEMS + [PFC_WD_BE_TRAFFIC_ITEM]

# Combined: N000 + BAG endpoints, port configs, and traffic items
ALL_ENDPOINTS = [N000_ENDPOINT] + VRF_BAG_ENDPOINTS

ALL_BASIC_PORT_CONFIGS = VRF_BAG_BASIC_PORT_CONFIGS + N000_BASIC_PORT_CONFIGS

ALL_TRAFFIC_ITEM_CONFIGS = (
    VRF_BAG_TRAFFIC_ITEM_CONFIGS
    + VRF_DSF_TRAFFIC_ITEM_CONFIGS
    + N000_RDMA_EDSW_TO_BAG_TRAFFIC_ITEM_CONFIGS
    + VRF_BAG_TRAFFIC_ITEM_CONFIGS_100PCT
    + PFC_WD_TRAFFIC_ITEM_CONFIGS
)

# Traffic item names for longevity playbook
LONGEVITY_TRAFFIC_ITEMS = [
    "BGP_BAG_P9_TO_P13_99PCT",
    "BGP_BAG_P10_TO_P14_99PCT",
    "BGP_BAG_P11_TO_P15_99PCT",
    "BGP_BAG_P12_TO_P16_99PCT",
    "DSF_NC_70PCT",
    "DSF_MONITORING_70PCT",
    "DSF_BE_70PCT",
    "DSF_RDMA_IB_70PCT",
    "RDMA_N000_17_TO_BAG_13",
    "RDMA_N000_17_TO_BAG_14",
    "RDMA_N000_23_TO_BAG_13",
    "RDMA_N000_23_TO_BAG_14",
    "BGP_BAG_P9_TO_P13_100PCT",
    "BGP_BAG_P10_TO_P14_100PCT",
    "BGP_BAG_P11_TO_P15_100PCT",
    "BGP_BAG_P12_TO_P16_100PCT",
]


# Traffic items for agent terminate playbooks (BAG-to-BAG through VRFs)
AGENT_TERMINATE_TRAFFIC_ITEMS = [
    "BGP_BAG_P9_TO_P13_99PCT",
    "BGP_BAG_P10_TO_P14_99PCT",
    "BGP_BAG_P11_TO_P15_99PCT",
    "BGP_BAG_P12_TO_P16_99PCT",
]


def _create_agent_terminate_playbook(
    name: str,
    agents: t.List[str],
    traffic_items_to_start: t.List[str],
    clear_traffic_stats: bool = True,
    iteration: int = 2,
) -> Playbook:
    """Create a playbook that terminates Arista agents and checks for traffic loss.

    Args:
        name: Playbook name
        agents: List of agent names to terminate (e.g., ["sandadj"])
        traffic_items_to_start: Traffic items to run during the test
        clear_traffic_stats: If True (hitfull), clear stats before postcheck.
            If False (hitless), verify zero loss across entire test.
        iteration: Number of iterations to run
    """
    return build_hyperport_vrf_bag_n000_playbook(
        name=name,
        device_regexes=["bag001.snc1"],
        postchecks=[
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        str_value="0",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                ],
                clear_traffic_stats=clear_traffic_stats,
            ),
            create_service_restart_check(
                services=list(ARISTA_CRITICAL_SAND_AGENTS),
                expected_restarted_services=agents,
            ),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_arista_custom_agents_service_interruption_step(
                        agents=agents,
                        trigger=ServiceInterruptionTrigger.CRASH,
                    ),
                    create_longevity_step(duration=120),
                ]
            )
        ],
        traffic_items_to_start=traffic_items_to_start,
        iteration=iteration,
    )


def _create_bgp_disruption_playbook(
    name: str,
    agents: t.List[str],
    traffic_items_to_start: t.List[str],
    clear_traffic_stats: bool,
    iteration: int = 2,
    longevity_duration: int = 120,
) -> Playbook:
    """Create a playbook for BGP disruption tests (DTest7b).

    Routes through the driver via ServiceInterruptionStep + ARISTA_CUSTOM_AGENTS,
    identical to the agent terminate flow. Special agent names ("bgp_hard_reset",
    "bgp_soft_reset") are dispatched to dedicated driver methods in
    AristaSwitch._async_crash_service.

    Args:
        name: Playbook name
        agents: Agent names to terminate or special reset names
            ("bgp_hard_reset", "bgp_soft_reset")
        traffic_items_to_start: Traffic items to run during the test
        clear_traffic_stats: If True (hitfull), clear stats before postcheck.
            If False (hitless), verify zero loss across entire test.
        iteration: Number of iterations to run
        longevity_duration: Seconds to wait for BGP convergence after disruption
    """
    return build_hyperport_vrf_bag_n000_playbook(
        name=name,
        device_regexes=["bag001.snc1"],
        prechecks=[
            create_ixia_packet_loss_check(
                thresholds=[hc_types.PacketLossThreshold(str_value="0.1")],
            ),
        ],
        postchecks=[
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        str_value="0",
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    ),
                ],
                clear_traffic_stats=clear_traffic_stats,
            ),
        ],
        snapshot_checks=[
            create_bgp_session_snapshot_check(),
            create_core_dumps_snapshot_check(),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_arista_custom_agents_service_interruption_step(
                        agents=agents,
                        trigger=ServiceInterruptionTrigger.CRASH,
                    ),
                    create_longevity_step(duration=longevity_duration),
                ]
            )
        ],
        traffic_items_to_start=traffic_items_to_start,
        iteration=iteration,
    )


def create_hyperport_vrf_bag_n000_test_config(
    test_config_name: str = "HYPERPORT_VRF_BAG_N000_TEST_CONFIGS",
    basset_pool: str = "networkai.test.regression",
    longevity_duration: int = 360,
) -> TestConfig:
    """Build the Hyperport VRF BAG N000 TestConfig (EDSW N000 testbed).

    Composes a comprehensive disruption + traffic TestConfig for the EDSW
    N000 Hyperport VRF BAG testbed. Wires up DSF drain checks, port-state
    checks, IXIA packet-loss checks (with a WD-friendly variant that omits
    the broad packet-loss check for PFC watchdog playbooks that legitimately
    show 100% pause-frame loss at the IXIA), then assembles:
      - Agent-terminate playbooks (sandadj, sandlag, sandl3ni, sandfabric)
      - BGP disruption playbooks
      - Continuous longevity stages

    Args:
        test_config_name: Final name of the produced TestConfig. Default
            matches the constant `HYPERPORT_VRF_BAG_N000_TEST_CONFIGS`
            re-exported through `testconfigs.hyperport`.
        basset_pool: Basset reservation pool (defaults to
            `networkai.test.regression`).
        longevity_duration: Duration in seconds of the longevity stage.

    Returns:
        TestConfig: The Hyperport VRF BAG N000 TestConfig, bound to the
        `HYPERPORT_VRF_BAG_N000_TEST_CONFIGS` module constant.
    """
    # TC-level checks moved to playbook level
    _tc_prechecks = [
        create_dsf_drain_state_check(),
        create_port_state_check(
            additional_interfaces=EDSW_N000_HYPERPORT_INTERFACES,
        ),
        create_ixia_packet_loss_check(
            thresholds=[hc_types.PacketLossThreshold(str_value="0.1")],
        ),
    ]
    _tc_postchecks = [
        create_ixia_packet_loss_check(
            thresholds=[
                hc_types.PacketLossThreshold(
                    str_value="0",
                    metric=hc_types.PacketLossMetric.PERCENTAGE,
                ),
            ],
        ),
        create_port_state_check(
            additional_interfaces=EDSW_N000_HYPERPORT_INTERFACES,
        ),
        create_unclean_exit_check(),
    ]
    _tc_snapshot_checks = [
        create_core_dumps_snapshot_check(),
        create_port_channel_state_snapshot_check(),
    ]

    # PFC WD playbooks emit RAW PFC pause traffic that reports ~100% Loss% at IXIA
    # (BAG consumes the pause frames at the MAC layer, so the destination IXIA port
    # never receives them). The broad IXIA_PACKET_LOSS_CHECK in _tc_postchecks uses
    # names=None + str_value="0" which would flag those items as failed. Drop that
    # specific check for WD playbooks but keep PORT_STATE_CHECK + UNCLEAN_EXIT_CHECK.
    _tc_postchecks_for_wd = [
        pc
        for pc in _tc_postchecks
        if pc.name != hc_types.CheckName.IXIA_PACKET_LOSS_CHECK
    ]

    # Build agent terminate playbooks and add TC-level checks
    _agent_terminate_playbooks = [
        # Sand Agent Terminate Test Cases (hitless)
        _create_agent_terminate_playbook(
            name="test_sandadj_agent_terminate",
            agents=["sandadj"],
            traffic_items_to_start=AGENT_TERMINATE_TRAFFIC_ITEMS,
            clear_traffic_stats=False,
        ),
        # Sand Agent Terminate Test Cases (hitfull)
        _create_agent_terminate_playbook(
            name="test_sandlag_agent_terminate",
            agents=["sandlag"],
            traffic_items_to_start=AGENT_TERMINATE_TRAFFIC_ITEMS,
            clear_traffic_stats=True,
        ),
        _create_agent_terminate_playbook(
            name="test_sandl3ni_agent_terminate",
            agents=["SandL3Ni"],
            traffic_items_to_start=AGENT_TERMINATE_TRAFFIC_ITEMS,
            clear_traffic_stats=False,
        ),
        _create_agent_terminate_playbook(
            name="test_sandfabric_agent_terminate",
            agents=["SandFabric-Fabric1"],
            traffic_items_to_start=AGENT_TERMINATE_TRAFFIC_ITEMS,
            clear_traffic_stats=True,
        ),
        _create_agent_terminate_playbook(
            name="test_snmp_agent_terminate",
            agents=["snmp"],
            traffic_items_to_start=AGENT_TERMINATE_TRAFFIC_ITEMS,
            clear_traffic_stats=False,
        ),
        _create_agent_terminate_playbook(
            name="test_xcvragent_agent_terminate",
            agents=["XcvrAgent"],
            traffic_items_to_start=AGENT_TERMINATE_TRAFFIC_ITEMS,
            clear_traffic_stats=False,
        ),
        _create_agent_terminate_playbook(
            name="test_sandtm_agent_terminate",
            agents=["SandTm"],
            traffic_items_to_start=AGENT_TERMINATE_TRAFFIC_ITEMS,
            clear_traffic_stats=False,
        ),
        _create_agent_terminate_playbook(
            name="test_sandlanz_agent_terminate",
            agents=["SandLanz"],
            traffic_items_to_start=AGENT_TERMINATE_TRAFFIC_ITEMS,
            clear_traffic_stats=False,
        ),
        _create_agent_terminate_playbook(
            name="test_sandfapni_linecard14_agent_terminate",
            agents=["SandFapNi-Linecard5"],
            traffic_items_to_start=AGENT_TERMINATE_TRAFFIC_ITEMS,
            clear_traffic_stats=True,
        ),
        _create_agent_terminate_playbook(
            name="test_SandMact_terminate",
            agents=["SandMact"],
            traffic_items_to_start=AGENT_TERMINATE_TRAFFIC_ITEMS,
            clear_traffic_stats=False,
        ),
        _create_agent_terminate_playbook(
            name="test_SandHwReader_terminate",
            agents=["SandHwReader"],
            traffic_items_to_start=AGENT_TERMINATE_TRAFFIC_ITEMS,
            clear_traffic_stats=False,
        ),
        _create_agent_terminate_playbook(
            name="test_SandCounters_terminate",
            agents=["SandCounters"],
            traffic_items_to_start=AGENT_TERMINATE_TRAFFIC_ITEMS,
            clear_traffic_stats=False,
        ),
    ]
    _agent_terminate_playbooks = [
        _pb(
            prechecks=list(_pb.prechecks or []) + _tc_prechecks,
            postchecks=list(_pb.postchecks or []) + _tc_postchecks,
            snapshot_checks=list(_pb.snapshot_checks or []) + _tc_snapshot_checks,
        )
        for _pb in _agent_terminate_playbooks
    ]

    return TestConfig(
        name=test_config_name,
        basset_pool=basset_pool,
        endpoints=ALL_ENDPOINTS,
        setup_tasks=[],
        basic_port_configs=ALL_BASIC_PORT_CONFIGS,
        basic_traffic_item_configs=ALL_TRAFFIC_ITEM_CONFIGS,
        # Deprecated - define at playbook level
        # postchecks (moved to each playbook)
        # Deprecated - define at playbook level
        # prechecks (moved to each playbook)
        # Deprecated - define at playbook level
        # snapshot_checks (moved to each playbook)
        playbooks=[
            build_hyperport_vrf_bag_n000_playbook(
                name="test_vrf_bag_longevity",
                traffic_items_to_start=[
                    "BGP_BAG_P9_TO_P13_99PCT",
                    "BGP_BAG_P10_TO_P14_99PCT",
                    "BGP_BAG_P11_TO_P15_99PCT",
                    "BGP_BAG_P12_TO_P16_99PCT",
                ],
                stages=[
                    create_steps_stage(
                        steps=[create_longevity_step(duration=longevity_duration)],
                    )
                ],
                prechecks=_tc_prechecks,
                postchecks=_tc_postchecks,
                snapshot_checks=_tc_snapshot_checks,
            ),
            *_agent_terminate_playbooks,
            # BGP Disruptive Test Cases (DTest7b)
            # BGP agent terminate — GR configured, no traffic loss expected
            _create_bgp_disruption_playbook(
                name="test_bgp_agent_terminate",
                agents=["Bgp"],
                traffic_items_to_start=AGENT_TERMINATE_TRAFFIC_ITEMS,
                clear_traffic_stats=False,
            ),
            # BGP hard reset — sessions restart, hardware reprogrammed, traffic loss expected
            _create_bgp_disruption_playbook(
                name="test_bgp_hard_reset",
                agents=["bgp_hard_reset"],
                traffic_items_to_start=AGENT_TERMINATE_TRAFFIC_ITEMS,
                clear_traffic_stats=True,
            ),
            # BGP soft reset — route refresh only, no session restart, no traffic loss
            _create_bgp_disruption_playbook(
                name="test_bgp_soft_reset",
                agents=["bgp_soft_reset"],
                traffic_items_to_start=AGENT_TERMINATE_TRAFFIC_ITEMS,
                clear_traffic_stats=False,
            ),
            # PFC Watchdog test cases — standalone Playbook literals (no factory helpers)
            # WD positive: high-rate PFC pause (30000 FPS on 800G) must trigger watchdog
            build_hyperport_vrf_bag_n000_playbook(
                name="test_tc2_pfc_wd_functionality",
                description="Watchdog should kick in during high-rate PFC Pause traffic",
                device_regexes=["bag001.snc1"],
                prechecks=[
                    create_clear_counters_check(),
                    *_tc_prechecks,
                ],
                stages=[
                    create_steps_stage(
                        steps=[
                            create_longevity_step(duration=PFC_WD_TRAFFIC_DURATION_SEC),
                        ]
                    )
                ],
                postchecks=[
                    create_dsf_pfc_check(
                        interfaces=PFC_WD_VICTIM_INTERFACES,
                        min_in_pfc_value=_PFC_WD_PARAMS["wd_pfc_threshold_high"],
                        priority=hc_types.Priority.PRIORITY_2,
                    ),
                    create_pfc_wd_check(
                        interfaces=PFC_WD_VICTIM_INTERFACES,
                        comparison_type=hc_types.ComparisonType.GREATER_THAN,
                    ),
                    *_tc_postchecks_for_wd,
                ],
                snapshot_checks=_tc_snapshot_checks,
                traffic_items_to_start=[
                    _PFC_WD_PARAMS["tc2_wd_traffic_item_high"],
                ],
            ),
            # WD negative: low-rate PFC pause (20000 FPS) stays below WD threshold; counters must remain 0
            build_hyperport_vrf_bag_n000_playbook(
                name="test_tc2_pfc_wd_functionality_transient",
                description="Watchdog should not kick in during low-rate PFC Pause traffic",
                device_regexes=["bag001.snc1"],
                prechecks=[
                    create_clear_counters_check(),
                    *_tc_prechecks,
                ],
                stages=[
                    create_steps_stage(
                        steps=[
                            create_longevity_step(duration=PFC_WD_TRAFFIC_DURATION_SEC),
                        ]
                    )
                ],
                postchecks=[
                    create_dsf_pfc_check(
                        interfaces=PFC_WD_VICTIM_INTERFACES,
                        min_in_pfc_value=_PFC_WD_PARAMS["wd_pfc_threshold_low"],
                        priority=hc_types.Priority.PRIORITY_2,
                    ),
                    create_pfc_wd_check(
                        interfaces=PFC_WD_VICTIM_INTERFACES,
                        comparison_type=hc_types.ComparisonType.EQUAL_TO,
                    ),
                    *_tc_postchecks_for_wd,
                ],
                snapshot_checks=_tc_snapshot_checks,
                traffic_items_to_start=[
                    _PFC_WD_PARAMS["tc2_wd_traffic_item_low"],
                ],
            ),
            # WD non-impact: high-rate PFC storm on TC2 must not starve TC1/BE traffic
            build_hyperport_vrf_bag_n000_playbook(
                name="test_tc2_pfc_wd_functionality_non_impact_tc1",
                description="PFC Pause storm traffic should not impact TC1",
                device_regexes=["bag001.snc1"],
                prechecks=[
                    create_clear_counters_check(),
                    *_tc_prechecks,
                ],
                stages=[
                    create_steps_stage(
                        steps=[
                            create_longevity_step(duration=PFC_WD_TRAFFIC_DURATION_SEC),
                        ]
                    )
                ],
                postchecks=[
                    create_dsf_pfc_check(
                        interfaces=PFC_WD_VICTIM_INTERFACES,
                        min_in_pfc_value=_PFC_WD_PARAMS["wd_pfc_threshold_high"],
                        priority=hc_types.Priority.PRIORITY_2,
                    ),
                    create_pfc_wd_check(
                        interfaces=PFC_WD_VICTIM_INTERFACES,
                        comparison_type=hc_types.ComparisonType.GREATER_THAN,
                    ),
                    # pyrefly: ignore [bad-argument-type]
                    create_packet_loss_check(PFC_WD_BE_TRAFFIC_ITEM.name),
                    *_tc_postchecks_for_wd,
                ],
                snapshot_checks=_tc_snapshot_checks,
                traffic_items_to_start=[
                    _PFC_WD_PARAMS["tc2_wd_traffic_item_high"],
                    PFC_WD_BE_TRAFFIC_ITEM.name,
                ],
            ),
        ],
    )


HYPERPORT_VRF_BAG_N000_TEST_CONFIGS = [create_hyperport_vrf_bag_n000_test_config()]
