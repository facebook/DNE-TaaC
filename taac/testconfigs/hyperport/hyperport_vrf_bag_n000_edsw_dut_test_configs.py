# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
Hyperport VRF BAG N000 EDSW-DUT Test Configuration

Variant of hyperport_vrf_bag_n000_test_configs that targets EDSW003.N000 as the
DUT (instead of BAG001.SNC1). Same N000 + BAG endpoints, port configs, and
traffic items, but every health check and FBOSS critical-service playbook
runs only on the EDSW.

Topology and IXIA endpoint reuse — see hyperport_vrf_bag_n000_test_configs.

Only the four BGP_BAG_PX_TO_PY_99PCT traffic items are started during each
playbook (no DSF, no 100PCT, no PFC, no RDMA). Health checks and FBOSS
critical-service playbooks are restricted to edsw003.n000.l201.snc1.
"""

from taac.health_checks.healthcheck_definitions import (
    create_core_dumps_snapshot_check,
    create_dsf_drain_state_check,
    create_ixia_packet_loss_check,
    create_port_channel_state_snapshot_check,
    create_port_state_check,
    create_unclean_exit_check,
)
from taac.playbooks.playbook_definitions import (
    build_hyperport_vrf_bag_n000_playbook,
)
from taac.stages.stage_definitions import (
    create_longevity_stage,
    create_steps_stage,
)
from taac.steps.step_definitions import (
    create_longevity_step,
    create_service_convergence_step,
    create_service_interruption_step,
)
from taac.testconfigs.hyperport.hyperport_vrf_bag_n000_test_configs import (
    ALL_BASIC_PORT_CONFIGS,
    ALL_TRAFFIC_ITEM_CONFIGS,
    EDSW003_N000_IXIA_PORTS,
    EDSW_N000_HYPERPORT_INTERFACES,
)
from taac.testconfigs.hyperport.hyperport_vrf_bag_test_configs import (
    VRF_BAG_IXIA_PORTS,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config.types import (
    ConcurrentStep,
    Endpoint,
    Playbook,
    Service,
    ServiceInterruptionTrigger,
    Stage,
    TestConfig,
)


EDSW_DUT = "edsw003.n000.l201.snc1"
EDSW_DUT_REGEXES = [EDSW_DUT]

# EDSW is the DUT in this variant; BAG is a non-DUT traffic peer.
# The imported ALL_ENDPOINTS from the BAG-DUT module has these flags reversed,
# so endpoints are reconstructed locally.
ALL_ENDPOINTS = [
    Endpoint(
        name=EDSW_DUT,
        dut=True,
        ixia_ports=EDSW003_N000_IXIA_PORTS,
    ),
    Endpoint(
        name="bag001.snc1",
        dut=False,
        ixia_ports=VRF_BAG_IXIA_PORTS,
    ),
]

# Only these four BGP traffic items are started for every playbook.
EDSW_DUT_TRAFFIC_ITEMS = [
    "BGP_BAG_P9_TO_P13_99PCT",
    "BGP_BAG_P10_TO_P14_99PCT",
    "BGP_BAG_P11_TO_P15_99PCT",
    "BGP_BAG_P12_TO_P16_99PCT",
]


def _tc_prechecks():
    return [
        create_dsf_drain_state_check(),
        create_port_state_check(additional_interfaces=EDSW_N000_HYPERPORT_INTERFACES),
        create_ixia_packet_loss_check(
            thresholds=[hc_types.PacketLossThreshold(str_value="0.1")],
            clear_traffic_stats=True,
        ),
    ]


def _tc_postchecks(
    clear_traffic_stats: bool = False,
    unclean_exit_exclude_services: list | None = None,
):
    return [
        create_ixia_packet_loss_check(
            thresholds=[
                hc_types.PacketLossThreshold(
                    str_value="0",
                    metric=hc_types.PacketLossMetric.PERCENTAGE,
                ),
            ],
            clear_traffic_stats=clear_traffic_stats,
        ),
        create_port_state_check(additional_interfaces=EDSW_N000_HYPERPORT_INTERFACES),
        create_unclean_exit_check(exclude_services=unclean_exit_exclude_services),
    ]


def _tc_snapshot_checks():
    return [
        create_core_dumps_snapshot_check(),
        create_port_channel_state_snapshot_check(),
    ]


def _create_fboss_critical_service_playbook(
    name: str,
    services: list,
    trigger: ServiceInterruptionTrigger,
    create_cold_boot_file: bool = False,
    concurrent: bool = False,
    iteration: int = 2,
    longevity_duration: int = 120,
    clear_traffic_stats: bool = False,
    unclean_exit_exclude_services: list | None = None,
    add_service_convergence: bool = False,
) -> Playbook:
    """Build an FBOSS critical-service playbook scoped to EDSW DUT.

    `services` may be a single Service or a list. When more than one service is
    given (and `concurrent=True`), the interruption steps run concurrently in
    a dedicated concurrent stage, followed by a separate sequential stage with
    the longevity step (and optional service-convergence step) so the
    longevity wait happens AFTER the interruptions have started rather than
    racing alongside them.

    `clear_traffic_stats` should be True for crash playbooks: the IXIA packet
    loss postcheck clears traffic counters before measuring, so loss accumulated
    during the prior steady-state window is not counted against the test.

    `unclean_exit_exclude_services` should list the services SIGKILL'd by the
    test so the UNCLEAN_EXIT_CHECK postcheck does not flag them as unexpected.

    `add_service_convergence` inserts a SERVICE_CONVERGENCE_STEP between the
    interruption and the longevity step. Required for agent coldboot/crash so
    wedge_agent is fully back online before PORT_STATE_CHECK fires (otherwise
    the Thrift connect to fboss.agent:5909 fails with CONNECT_UNKNOWN).
    """
    interruption_steps = [
        create_service_interruption_step(
            service=svc,
            trigger=trigger,
            create_cold_boot_file=create_cold_boot_file,
        )
        for svc in services
    ]
    run_concurrent = concurrent and len(services) > 1
    stages: list[Stage] = []
    if run_concurrent:
        stages.append(
            create_steps_stage(
                concurrent=True,
                concurrent_steps=[
                    ConcurrentStep(steps=[step]) for step in interruption_steps
                ],
            )
        )
        trailing_steps = []
        if add_service_convergence:
            trailing_steps.append(create_service_convergence_step(services=services))
        trailing_steps.append(create_longevity_step(duration=longevity_duration))
        stages.append(create_steps_stage(steps=trailing_steps))
    else:
        stage_steps = list(interruption_steps)
        if add_service_convergence:
            stage_steps.append(create_service_convergence_step(services=services))
        stage_steps.append(create_longevity_step(duration=longevity_duration))
        stages.append(create_steps_stage(steps=stage_steps))
    return build_hyperport_vrf_bag_n000_playbook(
        name=name,
        device_regexes=EDSW_DUT_REGEXES,
        prechecks=_tc_prechecks(),
        postchecks=_tc_postchecks(
            clear_traffic_stats=clear_traffic_stats,
            unclean_exit_exclude_services=unclean_exit_exclude_services,
        ),
        snapshot_checks=_tc_snapshot_checks(),
        stages=stages,
        traffic_items_to_start=EDSW_DUT_TRAFFIC_ITEMS,
        iteration=iteration,
    )


def create_hyperport_vrf_bag_n000_edsw_dut_test_config(
    test_config_name: str = "HYPERPORT_BAG_EDSW_DUT_TEST_CONFIGS",
    basset_pool: str = "networkai.test",
    longevity_duration: int = 360,
) -> TestConfig:
    fboss_playbooks = [
        _create_fboss_critical_service_playbook(
            name="test_agent_warmboot",
            services=[Service.AGENT],
            trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
        ),
        _create_fboss_critical_service_playbook(
            name="test_agent_coldboot",
            services=[Service.AGENT],
            trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
            create_cold_boot_file=True,
            add_service_convergence=True,
            longevity_duration=180,
            clear_traffic_stats=True,
        ),
        _create_fboss_critical_service_playbook(
            name="test_agent_crash",
            services=[Service.AGENT],
            trigger=ServiceInterruptionTrigger.CRASH,
            clear_traffic_stats=True,
            add_service_convergence=True,
            longevity_duration=180,
            unclean_exit_exclude_services=["wedge_agent"],
        ),
        _create_fboss_critical_service_playbook(
            name="test_bgpd_restart",
            services=[Service.BGP],
            trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
        ),
        _create_fboss_critical_service_playbook(
            name="test_bgpd_crash",
            services=[Service.BGP],
            trigger=ServiceInterruptionTrigger.CRASH,
            clear_traffic_stats=True,
            unclean_exit_exclude_services=["bgpd"],
        ),
        _create_fboss_critical_service_playbook(
            name="test_fsdb_restart",
            services=[Service.FSDB],
            trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
        ),
        _create_fboss_critical_service_playbook(
            name="test_fsdb_crash",
            services=[Service.FSDB],
            trigger=ServiceInterruptionTrigger.CRASH,
            clear_traffic_stats=True,
            unclean_exit_exclude_services=["fsdb"],
        ),
        _create_fboss_critical_service_playbook(
            name="test_qsfp_restart",
            services=[Service.QSFP_SERVICE],
            trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
        ),
        _create_fboss_critical_service_playbook(
            name="test_qsfp_service_crash",
            services=[Service.QSFP_SERVICE],
            trigger=ServiceInterruptionTrigger.CRASH,
            clear_traffic_stats=True,
            unclean_exit_exclude_services=["qsfp_service"],
        ),
        _create_fboss_critical_service_playbook(
            name="test_agent_and_bgpd_restart",
            services=[Service.AGENT, Service.BGP],
            trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
            concurrent=True,
        ),
        _create_fboss_critical_service_playbook(
            name="test_agent_and_fsdb_restart",
            services=[Service.AGENT, Service.FSDB],
            trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
            concurrent=True,
        ),
        _create_fboss_critical_service_playbook(
            name="test_agent_and_qsfp_service_restart",
            services=[Service.AGENT, Service.QSFP_SERVICE],
            trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
            concurrent=True,
        ),
        _create_fboss_critical_service_playbook(
            name="test_bgpd_and_fsdb_restart",
            services=[Service.BGP, Service.FSDB],
            trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
            concurrent=True,
        ),
        _create_fboss_critical_service_playbook(
            name="test_fsdb_and_qsfp_service_restart",
            services=[Service.FSDB, Service.QSFP_SERVICE],
            trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
            concurrent=True,
        ),
    ]

    return TestConfig(
        name=test_config_name,
        basset_pool=basset_pool,
        endpoints=ALL_ENDPOINTS,
        setup_tasks=[],
        basic_port_configs=ALL_BASIC_PORT_CONFIGS,
        basic_traffic_item_configs=ALL_TRAFFIC_ITEM_CONFIGS,
        playbooks=[
            build_hyperport_vrf_bag_n000_playbook(
                name="test_vrf_bag_longevity",
                device_regexes=EDSW_DUT_REGEXES,
                traffic_items_to_start=EDSW_DUT_TRAFFIC_ITEMS,
                stages=[create_longevity_stage(duration=longevity_duration)],
                prechecks=_tc_prechecks(),
                postchecks=_tc_postchecks(),
                snapshot_checks=_tc_snapshot_checks(),
            ),
            *fboss_playbooks,
        ],
    )


HYPERPORT_VRF_BAG_N000_EDSW_DUT_TEST_CONFIGS = [
    create_hyperport_vrf_bag_n000_edsw_dut_test_config()
]
