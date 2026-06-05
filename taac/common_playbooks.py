# pyre-unsafe
import json

from taac.health_checks.constants import (
    DEFAULT_SERVICE_NAMES,
    SERVICES_EXPECTED_TO_RESTART_DURING_AGENT_WARMBOOT,
    SERVICES_TO_MONITOR_DURING_AGENT_RESTART,
    SERVICES_TO_MONITOR_DURING_BGP_RESTART,
    SERVICES_TO_MONITOR_DURING_FSDB_RESTART,
    SERVICES_TO_MONITOR_DURING_OPENR_RESTART,
    SERVICES_TO_MONITOR_DURING_QSFP_SERVICE_RESTART,
)
from taac.step_definitions import (
    create_longevity_step,
    create_service_convergence_step,
    create_service_interruption_step,
    create_service_restart_steps,
    create_system_reboot_step,
    create_validation_step,
)
from taac.utils.json_thrift_utils import thrift_to_json
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config.types import (
    DrainUndrainInput,
    Params,
    Playbook,
    PointInTimeHealthCheck,
    Service,
    ServiceInterruptionTrigger,
    Stage,
    Step,
    StepName,
    SystemRebootTrigger,
    ValidationStage,
)


def create_service_restart_health_check(
    services_to_monitor, expected_restarted_services=None
):
    """
    Create a PointInTimeHealthCheck for monitoring service restarts.

    Args:
        services_to_monitor: List of services to monitor during restart
        expected_restarted_services: Optional list of services that are expected
            to restart (e.g. during warmboot). These will be skipped during the
            restart detection check.

    Returns:
        PointInTimeHealthCheck configured for service restart monitoring
    """
    params = {"services": services_to_monitor}
    if expected_restarted_services:
        params["expected_restarted_services"] = expected_restarted_services
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.SERVICE_RESTART_CHECK,
        check_params=Params(
            jq_params={
                "start_time": ".test_case_start_time",
            },
            json_params=json.dumps(params),
        ),
    )


TEST_AGENT_COLDBOOT_PLAYBOOK = Playbook(
    name="test_agent_coldboot",
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    create_cold_boot_file=True,
                ),
                create_service_convergence_step(services=[Service.AGENT]),
                create_longevity_step(duration=180),
            ]
        )
    ],
    postchecks=[
        PointInTimeHealthCheck(
            name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
            input_json=thrift_to_json(
                hc_types.IxiaPacketLossHealthCheckIn(
                    clear_traffic_stats=True,
                )
            ),
        )
    ],
)
TEST_CONTINUOUS_AGENT_COLDBOOT_PLAYBOOK = Playbook(
    name="test_continuous_agent_coldboot",
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    create_cold_boot_file=True,
                ),
                create_service_convergence_step(services=[Service.AGENT]),
            ],
            iteration=5,
        ),
        Stage(
            steps=[
                create_longevity_step(duration=180),
            ]
        ),
    ],
    postchecks=[
        PointInTimeHealthCheck(
            name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
            input_json=thrift_to_json(
                hc_types.IxiaPacketLossHealthCheckIn(
                    clear_traffic_stats=True,
                )
            ),
        )
    ],
)


TEST_AGENT_WARMBOOT_PLAYBOOK = Playbook(
    name="test_agent_warmboot",
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(services=[Service.AGENT]),
            ],
        ),
    ],
)

TEST_MULTIPLE_AGENT_WARMBOOT_PLAYBOOK = Playbook(
    name="test_multiple_agent_warmboot",
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(services=[Service.AGENT]),
                create_longevity_step(duration=120),
            ],
            iteration=5,
        ),
    ],
)


TEST_CONTINUOUS_AGENT_WARMBOOT_PLAYBOOK = Playbook(
    name="test_continuous_agent_warmboot",
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(services=[Service.AGENT]),
            ],
        ),
        Stage(
            steps=[
                create_longevity_step(duration=120),
            ]
        ),
    ],
    iteration=5,
)


TEST_AGENT_WARMBOOT_AND_FSDB_RESTART_PLAYBOOK = Playbook(
    name="test_agent_warmboot_and_fsdb_restart",
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_interruption_step(
                    service=Service.FSDB,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
            ],
            concurrent=True,
        ),
        Stage(
            steps=[
                create_service_convergence_step(services=[Service.AGENT, Service.FSDB]),
            ],
        ),
    ],
    prechecks=[
        PointInTimeHealthCheck(name=hc_types.CheckName.SYSTEMCTL_ACTIVE_STATE_CHECK),
        PointInTimeHealthCheck(name=hc_types.CheckName.WEDGE_AGENT_CONFIGURED_CHECK),
    ],
    postchecks=[
        PointInTimeHealthCheck(
            name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
        ),
        PointInTimeHealthCheck(
            name=hc_types.CheckName.UNCLEAN_EXIT_CHECK,
            check_params=Params(
                jq_params={
                    "start_time": ".test_case_start_time",
                }
            ),
        ),
    ],
)


TEST_CONTINUOUS_AGENT_WARMBOOT_AND_FSDB_RESTART_PLAYBOOK = Playbook(
    name="test_continuous_agent_warmboot_and_fsdb_restart",
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_interruption_step(
                    service=Service.FSDB,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
            ],
            concurrent=True,
        ),
        Stage(
            steps=[
                create_service_convergence_step(services=[Service.AGENT]),
            ],
        ),
    ],
    iteration=5,
)

TEST_QSPF_RESTART_PLAYBOOK = Playbook(
    name="test_qsfp_restart",
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.QSFP_SERVICE,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
            ]
        ),
    ],
)

TEST_QSFP_SERVICE_RESTART_PLAYBOOK = Playbook(
    name="test_qsfp_service_restart",
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.QSFP_SERVICE,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(services=[Service.QSFP_SERVICE]),
            ]
        ),
    ],
)

TEST_CONTINUOUS_QSPF_RESTART_PLAYBOOK = Playbook(
    name="test_continuous_qsfp_restart",
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.QSFP_SERVICE,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
            ]
        ),
    ],
)

TEST_FSDB_RESTART_PLAYBOOK = Playbook(
    name="test_fsdb_restart",
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.FSDB,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
            ]
        ),
    ],
)

TEST_CONTINUOUS_FSDB_RESTART_PLAYBOOK = Playbook(
    name="test_continuous_fsdb_restart",
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.FSDB,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
            ],
            iteration=5,
        ),
    ],
)

TEST_BGPD_RESTART_PLAYBOOK = Playbook(
    name="test_bgpd_restart",
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.BGP,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(services=[Service.AGENT]),
            ]
        ),
    ],
    enabled=False,
)

TEST_BGPD_CRASH_PLAYBOOK = Playbook(
    name="test_bgpd_crash",
    prechecks=[
        PointInTimeHealthCheck(
            name=hc_types.CheckName.UNCLEAN_EXIT_CHECK,
            check_params=Params(
                jq_params={"start_time": ".test_case_start_time"},
                json_params=json.dumps({"exclude_services": ["bgpd"]}),
            ),
        ),
    ],
    postchecks=[
        PointInTimeHealthCheck(
            name=hc_types.CheckName.UNCLEAN_EXIT_CHECK,
            check_params=Params(
                jq_params={"start_time": ".test_case_start_time"},
                json_params=json.dumps({"exclude_services": ["bgpd"]}),
            ),
        ),
    ],
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.BGP,
                    trigger=ServiceInterruptionTrigger.CRASH,
                ),
                create_service_convergence_step(services=[Service.AGENT]),
            ]
        ),
    ],
    enabled=False,
)

TEST_FBOSS_HW_AGENT_0_RESTART_PLAYBOOK = Playbook(
    name="test_fboss_hw_agent_0_restart",
    attribute_filters={"role": ["FDSW"]},
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.FBOSS_HW_AGENT_0,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(),
            ]
        )
    ],
    enabled=False,
)

TEST_FBOSS_HW_AGENT_1_RESTART_PLAYBOOK = Playbook(
    name="test_fboss_hw_agent_1_restart",
    attribute_filters={"role": ["FDSW"]},
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.FBOSS_HW_AGENT_1,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(),
            ]
        )
    ],
    enabled=False,
)

TEST_FBOSS_SW_AGENT_WARMBOOT_PLAYBOOK = Playbook(
    name="test_fboss_sw_agent_warmboot",
    attribute_filters={"role": ["FDSW"]},
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.FBOSS_SW_AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(),
            ]
        )
    ],
    enabled=False,
)

TEST_FBOSS_SW_AGENT_AND_HW_AGENT_0_RESTART_PLAYBOOK = Playbook(
    name="test_fboss_sw_agent_and_hw_agent_0_restart",
    attribute_filters={"role": ["FDSW"]},
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.FBOSS_SW_AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_interruption_step(
                    service=Service.FBOSS_HW_AGENT_0,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
            ],
            concurrent=True,
        ),
        Stage(
            steps=[
                create_service_convergence_step(),
            ]
        ),
    ],
    enabled=False,
    postchecks=[
        create_service_restart_health_check(
            DEFAULT_SERVICE_NAMES,
            expected_restarted_services=["fboss_sw_agent", "fboss_hw_agent@0"],
        ),
    ],
)

TEST_FBOSS_SW_AGENT_AND_HW_AGENT_1_RESTART_PLAYBOOK = Playbook(
    name="test_fboss_sw_agent_and_hw_agent_1_restart",
    attribute_filters={"role": ["FDSW"]},
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.FBOSS_SW_AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_interruption_step(
                    service=Service.FBOSS_HW_AGENT_1,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
            ],
            concurrent=True,
        ),
        Stage(
            steps=[
                create_service_convergence_step(services=[Service.AGENT]),
            ],
        ),
    ],
    postchecks=[
        create_service_restart_health_check(
            DEFAULT_SERVICE_NAMES,
            expected_restarted_services=["fboss_sw_agent", "fboss_hw_agent@1"],
        ),
    ],
)

TEST_DEVICE_REBOOT_PLAYBOOK = Playbook(
    name="test_device_reboot",
    stages=[
        Stage(
            steps=[
                create_system_reboot_step(
                    trigger=SystemRebootTrigger.FULL_SYSTEM_REBOOT,
                ),
                create_service_convergence_step(services=[Service.AGENT]),
                create_validation_step(
                    point_in_time_checks=[
                        PointInTimeHealthCheck(
                            name=hc_types.CheckName.DSF_DRAIN_STATE_CHECK,
                            input_json=thrift_to_json(
                                hc_types.DsfDrainStateCheckIn(
                                    is_drained=True,
                                )
                            ),
                        ),
                    ],
                    stage=ValidationStage.MID_TEST,
                ),
                Step(
                    name=StepName.DRAIN_UNDRAIN_STEP,
                    input_json=thrift_to_json(
                        DrainUndrainInput(
                            drain=False,
                        )
                    ),
                ),
                create_longevity_step(duration=120),
            ]
        )
    ],
    postchecks=[
        PointInTimeHealthCheck(
            name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
            input_json=thrift_to_json(
                hc_types.IxiaPacketLossHealthCheckIn(
                    clear_traffic_stats=True,
                )
            ),
        ),
    ],
)

TEST_INTERFACE_DRAIN_PLAYBOOK = Playbook(
    name="test_interface_drain",
    attribute_filters={"role": ["FDSW", "RDSW"]},
    stages=[
        Stage(
            steps=[
                Step(
                    name=StepName.DRAIN_UNDRAIN_STEP,
                    input_json=thrift_to_json(
                        DrainUndrainInput(
                            drain=True,
                        )
                    ),
                    description="Drain 1 random interface",
                ),
                Step(
                    name=StepName.DRAIN_UNDRAIN_STEP,
                    input_json=thrift_to_json(
                        DrainUndrainInput(
                            drain=False,
                        )
                    ),
                    description="Undrain the interface",
                ),
            ]
        )
    ],
    postchecks=[
        PointInTimeHealthCheck(
            name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
            input_json=thrift_to_json(
                hc_types.IxiaPacketLossHealthCheckIn(
                    clear_traffic_stats=True,
                )
            ),
        )
    ],
)

TEST_DEVICE_DRAIN_PLAYBOOK = Playbook(
    name="test_device_drain",
    attribute_filters={"role": ["FDSW"]},
    stages=[
        Stage(
            steps=[
                Step(
                    name=StepName.DRAIN_UNDRAIN_STEP,
                    input_json=thrift_to_json(
                        DrainUndrainInput(
                            drain=True,
                        )
                    ),
                ),
                Step(
                    name=StepName.DRAIN_UNDRAIN_STEP,
                    input_json=thrift_to_json(
                        DrainUndrainInput(
                            drain=False,
                        )
                    ),
                ),
            ]
        )
    ],
)


TEST_DEVICE_DRAIN_AND_REMOTE_INTERFACE_DRAIN_PLAYBOOK = Playbook(
    name="test_device_drain_and_remote_interface_drain",
    attribute_filters={"role": ["FDSW"]},
    stages=[
        Stage(
            steps=[
                Step(
                    name=StepName.DRAIN_UNDRAIN_STEP,
                    input_json=thrift_to_json(
                        DrainUndrainInput(
                            drain=True,
                        )
                    ),
                ),
            ]
        ),
        Stage(
            steps=[
                Step(
                    name=StepName.DRAIN_UNDRAIN_STEP,
                    input_json=thrift_to_json(
                        DrainUndrainInput(
                            drain=True,
                        )
                    ),
                )
            ],
        ),
        Stage(
            steps=[
                Step(
                    name=StepName.DRAIN_UNDRAIN_STEP,
                    input_json=thrift_to_json(
                        DrainUndrainInput(
                            drain=False,
                        )
                    ),
                )
            ],
        ),
        Stage(
            steps=[
                Step(
                    name=StepName.DRAIN_UNDRAIN_STEP,
                    input_json=thrift_to_json(
                        DrainUndrainInput(
                            drain=False,
                        )
                    ),
                ),
            ]
        ),
    ],
    postchecks=[
        PointInTimeHealthCheck(
            name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
            input_json=thrift_to_json(
                hc_types.IxiaPacketLossHealthCheckIn(
                    clear_traffic_stats=True,
                )
            ),
        )
    ],
)

TEST_DEVICE_DRAIN_AND_LOCAL_INTERFACE_DRAIN_PLAYBOOK = Playbook(
    name="test_device_drain_and_local_interface_drain",
    attribute_filters={"role": ["FDSW"]},
    stages=[
        Stage(
            steps=[
                Step(
                    name=StepName.DRAIN_UNDRAIN_STEP,
                    input_json=thrift_to_json(
                        DrainUndrainInput(
                            drain=True,
                        )
                    ),
                ),
                Step(
                    name=StepName.DRAIN_UNDRAIN_STEP,
                    input_json=thrift_to_json(
                        DrainUndrainInput(
                            drain=True,
                        )
                    ),
                ),
                Step(
                    name=StepName.DRAIN_UNDRAIN_STEP,
                    input_json=thrift_to_json(
                        DrainUndrainInput(
                            drain=False,
                        )
                    ),
                ),
                Step(
                    name=StepName.DRAIN_UNDRAIN_STEP,
                    input_json=thrift_to_json(
                        DrainUndrainInput(
                            drain=False,
                        )
                    ),
                ),
            ]
        ),
    ],
    postchecks=[
        PointInTimeHealthCheck(
            name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
            input_json=thrift_to_json(
                hc_types.IxiaPacketLossHealthCheckIn(
                    clear_traffic_stats=True,
                )
            ),
        )
    ],
)

TEST_AGENT_CRASH_PLAYBOOK = Playbook(
    name="test_agent_crash",
    prechecks=[
        PointInTimeHealthCheck(
            name=hc_types.CheckName.UNCLEAN_EXIT_CHECK,
            check_params=Params(
                jq_params={"start_time": ".test_case_start_time"},
                json_params=json.dumps(
                    {
                        "exclude_services": [
                            "wedge_agent",
                            "bgpd",
                            "fboss_sw_agent",
                            "fboss_hw_agent@0",
                        ]
                    }
                ),
            ),
        ),
    ],
    postchecks=[
        PointInTimeHealthCheck(
            name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
            input_json=thrift_to_json(
                hc_types.IxiaPacketLossHealthCheckIn(
                    clear_traffic_stats=True,
                )
            ),
        ),
        PointInTimeHealthCheck(
            name=hc_types.CheckName.UNCLEAN_EXIT_CHECK,
            check_params=Params(
                jq_params={"start_time": ".test_case_start_time"},
                json_params=json.dumps(
                    {
                        "exclude_services": [
                            "wedge_agent",
                            "bgpd",
                            "fboss_sw_agent",
                            "fboss_hw_agent@0",
                        ]
                    }
                ),
            ),
        ),
    ],
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.AGENT,
                    trigger=ServiceInterruptionTrigger.CRASH,
                ),
                create_service_convergence_step(services=[Service.AGENT]),
                create_longevity_step(duration=180),
            ]
        )
    ],
)

TEST_FBOSS_HW_AGENT_0_CRASH_PLAYBOOK = Playbook(
    name="test_fboss_hw_agent_0_crash",
    prechecks=[
        PointInTimeHealthCheck(
            name=hc_types.CheckName.UNCLEAN_EXIT_CHECK,
            check_params=Params(
                jq_params={"start_time": ".test_case_start_time"},
                json_params=json.dumps({"exclude_services": ["fboss_hw_agent@0"]}),
            ),
        ),
    ],
    postchecks=[
        PointInTimeHealthCheck(
            name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
            input_json=thrift_to_json(
                hc_types.IxiaPacketLossHealthCheckIn(
                    clear_traffic_stats=True,
                )
            ),
        ),
        PointInTimeHealthCheck(
            name=hc_types.CheckName.UNCLEAN_EXIT_CHECK,
            check_params=Params(
                jq_params={"start_time": ".test_case_start_time"},
                json_params=json.dumps({"exclude_services": ["fboss_hw_agent@0"]}),
            ),
        ),
    ],
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.FBOSS_HW_AGENT_0,
                    trigger=ServiceInterruptionTrigger.CRASH,
                ),
                create_service_convergence_step(services=[Service.AGENT]),
                create_longevity_step(duration=180),
            ]
        )
    ],
)

TEST_51T_NPI_DCTYPEF_PLAYBOOKS = (
    Playbook(
        name="test_fsdb_restart",
        stages=[
            Stage(
                steps=[
                    create_service_interruption_step(
                        service=Service.FSDB,
                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                ]
            ),
        ],
        postchecks=[
            PointInTimeHealthCheck(
                name=hc_types.CheckName.SERVICE_RESTART_CHECK,
                check_params=Params(
                    jq_params={
                        "start_time": ".test_case_start_time",
                    },
                    json_params=json.dumps(
                        {
                            "services": SERVICES_TO_MONITOR_DURING_FSDB_RESTART,
                        }
                    ),
                ),
            ),
        ],
    ),
    Playbook(
        name="test_qsfp_restart",
        stages=[
            Stage(
                steps=[
                    create_service_interruption_step(
                        service=Service.QSFP_SERVICE,
                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                ]
            ),
        ],
        postchecks=[
            PointInTimeHealthCheck(
                name=hc_types.CheckName.SERVICE_RESTART_CHECK,
                check_params=Params(
                    jq_params={
                        "start_time": ".test_case_start_time",
                    },
                    json_params=json.dumps(
                        {
                            "services": SERVICES_TO_MONITOR_DURING_QSFP_SERVICE_RESTART,
                        }
                    ),
                ),
            ),
        ],
    ),
    Playbook(
        name="test_agent_coldboot",
        stages=[
            Stage(
                steps=[
                    create_service_interruption_step(
                        service=Service.AGENT,
                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                        create_cold_boot_file=True,
                    ),
                    create_service_convergence_step(
                        services=[Service.AGENT, Service.BGP]
                    ),
                    create_longevity_step(duration=300),
                ]
            )
        ],
        postchecks=[
            PointInTimeHealthCheck(
                name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
                input_json=thrift_to_json(
                    hc_types.IxiaPacketLossHealthCheckIn(
                        clear_traffic_stats=True,
                    )
                ),
            ),
            PointInTimeHealthCheck(
                name=hc_types.CheckName.SERVICE_RESTART_CHECK,
                check_params=Params(
                    jq_params={
                        "start_time": ".test_case_start_time",
                    },
                    json_params=json.dumps(
                        {
                            "services": SERVICES_TO_MONITOR_DURING_AGENT_RESTART,
                        }
                    ),
                ),
            ),
        ],
    ),
    Playbook(
        name="test_51t_continuous_agent_warmboot",
        stages=[
            Stage(
                steps=[
                    create_service_interruption_step(
                        service=Service.AGENT,
                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(
                        services=[Service.AGENT, Service.BGP]
                    ),
                ],
            ),
            Stage(
                steps=[
                    create_longevity_step(duration=300),
                ]
            ),
        ],
        iteration=5,
        postchecks=[
            PointInTimeHealthCheck(
                name=hc_types.CheckName.SERVICE_RESTART_CHECK,
                check_params=Params(
                    jq_params={
                        "start_time": ".test_case_start_time",
                    },
                    json_params=json.dumps(
                        {
                            "services": SERVICES_TO_MONITOR_DURING_AGENT_RESTART,
                        }
                    ),
                ),
            ),
        ],
    ),
    Playbook(
        name="test_51t_agent_warmboot",
        stages=[
            Stage(
                steps=[
                    create_service_interruption_step(
                        service=Service.AGENT,
                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(
                        services=[Service.AGENT, Service.BGP]
                    ),
                    create_longevity_step(duration=300),
                ],
            ),
        ],
        postchecks=[
            PointInTimeHealthCheck(
                name=hc_types.CheckName.SERVICE_RESTART_CHECK,
                check_params=Params(
                    jq_params={
                        "start_time": ".test_case_start_time",
                    },
                    json_params=json.dumps(
                        {
                            "services": SERVICES_TO_MONITOR_DURING_AGENT_RESTART,
                        }
                    ),
                ),
            ),
        ],
    ),
    Playbook(
        name="test_bgpd_restart",
        stages=[
            Stage(
                steps=[
                    create_service_interruption_step(
                        service=Service.BGP,
                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(
                        services=[Service.AGENT, Service.BGP]
                    ),
                ]
            ),
        ],
        postchecks=[
            PointInTimeHealthCheck(
                name=hc_types.CheckName.SERVICE_RESTART_CHECK,
                check_params=Params(
                    jq_params={
                        "start_time": ".test_case_start_time",
                    },
                    json_params=json.dumps(
                        {
                            "services": SERVICES_TO_MONITOR_DURING_BGP_RESTART,
                        }
                    ),
                ),
            ),
        ],
    ),
)

TEST_FBOSS_SW_AGENT_CRASH_PLAYBOOK = Playbook(
    name="test_fboss_sw_agent_crash",
    prechecks=[
        PointInTimeHealthCheck(
            name=hc_types.CheckName.UNCLEAN_EXIT_CHECK,
            check_params=Params(
                jq_params={"start_time": ".test_case_start_time"},
                json_params=json.dumps({"exclude_services": ["fboss_sw_agent"]}),
            ),
        ),
    ],
    postchecks=[
        PointInTimeHealthCheck(
            name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
            input_json=thrift_to_json(
                hc_types.IxiaPacketLossHealthCheckIn(
                    clear_traffic_stats=True,
                )
            ),
        ),
        PointInTimeHealthCheck(
            name=hc_types.CheckName.UNCLEAN_EXIT_CHECK,
            check_params=Params(
                jq_params={"start_time": ".test_case_start_time"},
                json_params=json.dumps({"exclude_services": ["fboss_sw_agent"]}),
            ),
        ),
    ],
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.FBOSS_SW_AGENT,
                    trigger=ServiceInterruptionTrigger.CRASH,
                ),
                create_service_convergence_step(services=[Service.AGENT]),
                create_longevity_step(duration=180),
            ],
        ),
    ],
)

TEST_FSDB_CRASH_PLAYBOOK = Playbook(
    name="test_fsdb_crash",
    prechecks=[
        PointInTimeHealthCheck(
            name=hc_types.CheckName.UNCLEAN_EXIT_CHECK,
            check_params=Params(
                jq_params={"start_time": ".test_case_start_time"},
                json_params=json.dumps({"exclude_services": ["fsdb"]}),
            ),
        ),
    ],
    postchecks=[
        PointInTimeHealthCheck(
            name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
            input_json=thrift_to_json(
                hc_types.IxiaPacketLossHealthCheckIn(
                    clear_traffic_stats=True,
                )
            ),
        ),
        PointInTimeHealthCheck(
            name=hc_types.CheckName.UNCLEAN_EXIT_CHECK,
            check_params=Params(
                jq_params={"start_time": ".test_case_start_time"},
                json_params=json.dumps({"exclude_services": ["fsdb"]}),
            ),
        ),
    ],
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.FSDB,
                    trigger=ServiceInterruptionTrigger.CRASH,
                ),
                create_service_convergence_step(services=[Service.FSDB]),
                create_longevity_step(duration=180),
            ]
        )
    ],
)

TEST_QSPF_SERVICE_CRASH_PLAYBOOK = Playbook(
    name="test_qspf_service_crash",
    prechecks=[
        PointInTimeHealthCheck(name=hc_types.CheckName.SYSTEMCTL_ACTIVE_STATE_CHECK),
        PointInTimeHealthCheck(name=hc_types.CheckName.WEDGE_AGENT_CONFIGURED_CHECK),
        PointInTimeHealthCheck(
            name=hc_types.CheckName.UNCLEAN_EXIT_CHECK,
            check_params=Params(
                jq_params={"start_time": ".test_case_start_time"},
                json_params=json.dumps({"exclude_services": ["qsfp_service"]}),
            ),
        ),
    ],
    postchecks=[
        PointInTimeHealthCheck(
            name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
            input_json=thrift_to_json(
                hc_types.IxiaPacketLossHealthCheckIn(
                    clear_traffic_stats=True,
                )
            ),
        ),
        PointInTimeHealthCheck(
            name=hc_types.CheckName.UNCLEAN_EXIT_CHECK,
            check_params=Params(
                jq_params={"start_time": ".test_case_start_time"},
                json_params=json.dumps({"exclude_services": ["qsfp_service"]}),
            ),
        ),
    ],
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.QSFP_SERVICE,
                    trigger=ServiceInterruptionTrigger.CRASH,
                ),
                create_service_convergence_step(services=[Service.QSFP_SERVICE]),
                create_longevity_step(duration=180),
            ]
        )
    ],
)

TEST_QSFP_SERVICE_CRASH_PLAYBOOK = Playbook(
    name="test_qsfp_service_crash",
    prechecks=[
        PointInTimeHealthCheck(
            name=hc_types.CheckName.UNCLEAN_EXIT_CHECK,
            check_params=Params(
                jq_params={"start_time": ".test_case_start_time"},
                json_params=json.dumps({"exclude_services": ["qsfp_service"]}),
            ),
        ),
    ],
    postchecks=[
        PointInTimeHealthCheck(
            name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
            input_json=thrift_to_json(
                hc_types.IxiaPacketLossHealthCheckIn(
                    clear_traffic_stats=True,
                )
            ),
        ),
        PointInTimeHealthCheck(
            name=hc_types.CheckName.UNCLEAN_EXIT_CHECK,
            check_params=Params(
                jq_params={"start_time": ".test_case_start_time"},
                json_params=json.dumps({"exclude_services": ["qsfp_service"]}),
            ),
        ),
    ],
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.QSFP_SERVICE,
                    trigger=ServiceInterruptionTrigger.CRASH,
                ),
                create_service_convergence_step(services=[Service.QSFP_SERVICE]),
                create_longevity_step(duration=180),
            ]
        )
    ],
)

TEST_OPENR_RESTART_PLAYBOOK = Playbook(
    name="test_openr_restart",
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.OPENR,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(),
            ]
        ),
    ],
)

TEST_OPENR_CRASH_PLAYBOOK = Playbook(
    name="test_openr_crash",
    prechecks=[
        PointInTimeHealthCheck(
            name=hc_types.CheckName.UNCLEAN_EXIT_CHECK,
            check_params=Params(
                jq_params={"start_time": ".test_case_start_time"},
                json_params=json.dumps({"exclude_services": ["openr"]}),
            ),
        ),
    ],
    postchecks=[
        PointInTimeHealthCheck(
            name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
            input_json=thrift_to_json(
                hc_types.IxiaPacketLossHealthCheckIn(
                    clear_traffic_stats=True,
                )
            ),
        ),
        PointInTimeHealthCheck(
            name=hc_types.CheckName.UNCLEAN_EXIT_CHECK,
            check_params=Params(
                jq_params={"start_time": ".test_case_start_time"},
                json_params=json.dumps({"exclude_services": ["openr"]}),
            ),
        ),
    ],
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.OPENR,
                    trigger=ServiceInterruptionTrigger.CRASH,
                ),
                create_service_convergence_step(),
                create_longevity_step(duration=180),
            ]
        )
    ],
)

TEST_SW_AGENT_AND_WEDGE_AGENT_RESTART_PLAYBOOK = Playbook(
    name="test_sw_agent_and_wedge_agent_restart",
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.FBOSS_SW_AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_interruption_step(
                    service=Service.AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(services=[Service.AGENT]),
            ],
        ),
    ],
    postchecks=[
        create_service_restart_health_check(
            DEFAULT_SERVICE_NAMES,
            expected_restarted_services=[
                "fboss_sw_agent",
                "wedge_agent",
                "fboss_hw_agent@0",
                "bgpd",
                "openr",
            ],
        ),
    ],
)

TEST_QSFP_SERVICE_AND_AGENT_WARMBOOT_PLAYBOOK = Playbook(
    name="test_qsfp_service_and_agent_warmboot",
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.QSFP_SERVICE,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_longevity_step(duration=300),
                create_service_interruption_step(
                    service=Service.AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(services=[Service.AGENT]),
            ],
        ),
    ],
    postchecks=[
        create_service_restart_health_check(
            DEFAULT_SERVICE_NAMES,
            expected_restarted_services=[
                "qsfp_service",
                "wedge_agent",
                "fboss_sw_agent",
                "fboss_hw_agent@0",
                "bgpd",
                "openr",
            ],
        ),
    ],
)

TEST_BGPD_AND_FSDB_RESTART_PLAYBOOK = Playbook(
    name="test_bgpd_and_fsdb_restart",
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.BGP,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_interruption_step(
                    service=Service.FSDB,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(
                    services=[Service.AGENT, Service.BGP, Service.FSDB]
                ),
            ],
            iteration=5,
        ),
    ],
    postchecks=[
        create_service_restart_health_check(
            DEFAULT_SERVICE_NAMES,
            expected_restarted_services=["bgpd", "fsdb"],
        ),
    ],
)


TEST_AGENT_AND_FSDB_RESTART_PLAYBOOK = Playbook(
    name="test_agent_and_fsdb_restart",
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_interruption_step(
                    service=Service.FSDB,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(services=[Service.AGENT, Service.FSDB]),
            ],
            iteration=5,
        ),
    ],
    postchecks=[
        create_service_restart_health_check(
            DEFAULT_SERVICE_NAMES,
            expected_restarted_services=[
                "wedge_agent",
                "fsdb",
                "fboss_sw_agent",
                "fboss_hw_agent@0",
                "bgpd",
                "openr",
            ],
        ),
    ],
)


TEST_FBOSS_SW_AGENT_AND_HW_AGENT_0_CRASH_PLAYBOOK = Playbook(
    name="test_fboss_sw_agent_and_hw_agent_0_crash",
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.FBOSS_SW_AGENT,
                    trigger=ServiceInterruptionTrigger.CRASH,
                ),
                create_service_interruption_step(
                    service=Service.FBOSS_HW_AGENT_0,
                    trigger=ServiceInterruptionTrigger.CRASH,
                ),
            ],
            concurrent=True,
        ),
        Stage(
            steps=[
                create_service_convergence_step(services=[Service.AGENT]),
            ],
        ),
    ],
    postchecks=[
        create_service_restart_health_check(
            DEFAULT_SERVICE_NAMES,
            expected_restarted_services=["fboss_sw_agent", "fboss_hw_agent@0"],
        ),
    ],
)

TEST_AGENT_AND_BGPD_RESTART_PLAYBOOK = Playbook(
    name="test_agent_and_bgpd_restart",
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_interruption_step(
                    service=Service.BGP,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(services=[Service.AGENT, Service.BGP]),
            ],
            iteration=5,
        ),
    ],
    postchecks=[
        create_service_restart_health_check(
            DEFAULT_SERVICE_NAMES,
            expected_restarted_services=[
                "wedge_agent",
                "bgpd",
                "fboss_sw_agent",
                "fboss_hw_agent@0",
                "openr",
            ],
        ),
    ],
)

TEST_AGENT_AND_QSFP_SERVICE_RESTART_PLAYBOOK = Playbook(
    name="test_agent_and_qsfp_service_restart",
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.AGENT,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_interruption_step(
                    service=Service.QSFP_SERVICE,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(
                    services=[Service.AGENT, Service.QSFP_SERVICE]
                ),
            ],
            iteration=5,
        ),
    ],
    postchecks=[
        create_service_restart_health_check(
            DEFAULT_SERVICE_NAMES,
            expected_restarted_services=[
                "wedge_agent",
                "qsfp_service",
                "fboss_sw_agent",
                "fboss_hw_agent@0",
                "bgpd",
                "openr",
            ],
        ),
    ],
)

TEST_FSDB_AND_QSFP_SERVICE_RESTART_PLAYBOOK = Playbook(
    name="test_fsdb_and_qsfp_service_restart",
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.FSDB,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_interruption_step(
                    service=Service.QSFP_SERVICE,
                    trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(
                    services=[Service.FSDB, Service.QSFP_SERVICE]
                ),
            ],
            iteration=5,
        ),
    ],
    postchecks=[
        create_service_restart_health_check(
            DEFAULT_SERVICE_NAMES,
            expected_restarted_services=["fsdb", "qsfp_service"],
        ),
    ],
)


# ---------------------------------------------------------------------------
# Service restart health-check constants
# ---------------------------------------------------------------------------

AGENT_RESTART_SERVICE_CHECK = create_service_restart_health_check(
    SERVICES_TO_MONITOR_DURING_AGENT_RESTART
)

AGENT_WARMBOOT_SERVICE_CHECK = create_service_restart_health_check(
    DEFAULT_SERVICE_NAMES,
    expected_restarted_services=SERVICES_EXPECTED_TO_RESTART_DURING_AGENT_WARMBOOT,
)

BGP_RESTART_SERVICE_CHECK = create_service_restart_health_check(
    SERVICES_TO_MONITOR_DURING_BGP_RESTART
)

FSDB_RESTART_SERVICE_CHECK = create_service_restart_health_check(
    SERVICES_TO_MONITOR_DURING_FSDB_RESTART
)

QSFP_SERVICE_RESTART_SERVICE_CHECK = create_service_restart_health_check(
    SERVICES_TO_MONITOR_DURING_QSFP_SERVICE_RESTART
)

OPENR_RESTART_SERVICE_CHECK = create_service_restart_health_check(
    SERVICES_TO_MONITOR_DURING_OPENR_RESTART
)


# ---------------------------------------------------------------------------
# Factory functions for restart / crash playbooks
# (parameterised by iteration count to support different conveyors)
# ---------------------------------------------------------------------------


def create_agent_warmboot_playbook(iteration: int = 5) -> Playbook:
    return Playbook(
        name="test_agent_warmboot",
        stages=[
            Stage(
                iteration=iteration,
                steps=create_service_restart_steps(Service.AGENT),
            ),
        ],
        postchecks=[
            AGENT_WARMBOOT_SERVICE_CHECK,
        ],
    )


def create_bgpd_restart_playbook(
    iteration: int = 5,
    ixia_rogue_ic_parent_network_v6: str = "",
    ixia_rogue_ic_parent_network_v4: str = "",
) -> Playbook:
    postchecks = [
        PointInTimeHealthCheck(
            name=hc_types.CheckName.BGP_CONVERGENCE_CHECK,
        ),
    ]
    if ixia_rogue_ic_parent_network_v6 or ixia_rogue_ic_parent_network_v4:
        postchecks.append(
            PointInTimeHealthCheck(
                name=hc_types.CheckName.BGP_RIB_FIB_CONSISTENCY_CHECK,
                check_params=Params(
                    json_params=json.dumps(
                        {
                            "parent_prefixes_to_ignore": [
                                f"{ixia_rogue_ic_parent_network_v6}::/80",
                                f"{ixia_rogue_ic_parent_network_v4}.0/16",
                            ]
                        }
                    ),
                ),
            ),
        )
    postchecks.append(BGP_RESTART_SERVICE_CHECK)
    return Playbook(
        name="test_bgpd_restart",
        stages=[
            Stage(
                iteration=iteration,
                steps=create_service_restart_steps(Service.BGP),
            ),
        ],
        postchecks=postchecks,
    )


def create_qsfp_service_restart_playbook(iteration: int = 5) -> Playbook:
    return Playbook(
        name="test_qsfp_service_restart",
        postchecks=[
            QSFP_SERVICE_RESTART_SERVICE_CHECK,
        ],
        stages=[
            Stage(
                iteration=iteration,
                steps=[
                    create_service_interruption_step(
                        service=Service.QSFP_SERVICE,
                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(),
                ],
            ),
        ],
    )


def create_fsdb_restart_playbook(iteration: int = 5) -> Playbook:
    return Playbook(
        name="test_fsdb_restart",
        postchecks=[
            FSDB_RESTART_SERVICE_CHECK,
        ],
        stages=[
            Stage(
                iteration=iteration,
                steps=[
                    create_service_interruption_step(
                        service=Service.FSDB,
                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_longevity_step(duration=10),
                ],
            ),
        ],
    )


def create_openr_restart_playbook(iteration: int = 5) -> Playbook:
    return Playbook(
        name="test_openr_restart",
        postchecks=[
            OPENR_RESTART_SERVICE_CHECK,
        ],
        stages=[
            Stage(
                iteration=iteration,
                steps=[
                    create_service_interruption_step(
                        service=Service.OPENR,
                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(),
                ],
            ),
        ],
    )


def create_agent_coldboot_playbook(iteration: int = 5) -> Playbook:
    return Playbook(
        name="test_agent_coldboot",
        postchecks=[
            AGENT_WARMBOOT_SERVICE_CHECK,
        ],
        stages=[
            Stage(
                iteration=iteration,
                steps=[
                    create_service_interruption_step(
                        service=Service.AGENT,
                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                        create_cold_boot_file=True,
                    ),
                    create_service_convergence_step(
                        services=[Service.AGENT, Service.BGP],
                    ),
                ],
            ),
        ],
    )


def _unclean_exit_check(exclude_services: list) -> PointInTimeHealthCheck:
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.UNCLEAN_EXIT_CHECK,
        check_params=Params(
            jq_params={"start_time": ".test_case_start_time"},
            json_params=json.dumps({"exclude_services": exclude_services}),
        ),
    )


def create_agent_crash_playbook(iteration: int = 5) -> Playbook:
    return Playbook(
        name="test_agent_crash",
        prechecks=[
            _unclean_exit_check(["wedge_agent", "bgpd"]),
        ],
        postchecks=[
            AGENT_WARMBOOT_SERVICE_CHECK,
            _unclean_exit_check(["wedge_agent", "bgpd"]),
        ],
        stages=[
            Stage(
                iteration=iteration,
                steps=[
                    create_service_interruption_step(
                        service=Service.AGENT,
                        trigger=ServiceInterruptionTrigger.CRASH,
                    ),
                    create_service_convergence_step(
                        services=[Service.AGENT, Service.BGP],
                    ),
                ],
            ),
        ],
    )


def create_bgpd_crash_playbook(iteration: int = 5) -> Playbook:
    return Playbook(
        name="test_bgpd_crash",
        prechecks=[
            _unclean_exit_check(["bgpd"]),
        ],
        postchecks=[
            BGP_RESTART_SERVICE_CHECK,
            _unclean_exit_check(["bgpd"]),
        ],
        stages=[
            Stage(
                iteration=iteration,
                steps=[
                    create_service_interruption_step(
                        service=Service.BGP,
                        trigger=ServiceInterruptionTrigger.CRASH,
                    ),
                    create_service_convergence_step(),
                ],
            ),
        ],
    )


def create_openr_crash_playbook(iteration: int = 5) -> Playbook:
    return Playbook(
        name="test_openr_crash",
        prechecks=[
            _unclean_exit_check(["openr"]),
        ],
        postchecks=[
            OPENR_RESTART_SERVICE_CHECK,
            _unclean_exit_check(["openr"]),
        ],
        stages=[
            Stage(
                iteration=iteration,
                steps=[
                    create_service_interruption_step(
                        service=Service.OPENR,
                        trigger=ServiceInterruptionTrigger.CRASH,
                    ),
                    create_service_convergence_step(),
                ],
            ),
        ],
    )


def create_qsfp_service_crash_playbook(iteration: int = 5) -> Playbook:
    return Playbook(
        name="test_qsfp_service_crash",
        prechecks=[
            _unclean_exit_check(["qsfp_service"]),
        ],
        postchecks=[
            QSFP_SERVICE_RESTART_SERVICE_CHECK,
            _unclean_exit_check(["qsfp_service"]),
        ],
        stages=[
            Stage(
                iteration=iteration,
                steps=[
                    create_service_interruption_step(
                        service=Service.QSFP_SERVICE,
                        trigger=ServiceInterruptionTrigger.CRASH,
                    ),
                    create_service_convergence_step(),
                ],
            ),
        ],
    )


def create_fsdb_crash_playbook(iteration: int = 5) -> Playbook:
    return Playbook(
        name="test_fsdb_crash",
        prechecks=[
            _unclean_exit_check(["fsdb"]),
        ],
        postchecks=[
            FSDB_RESTART_SERVICE_CHECK,
            _unclean_exit_check(["fsdb"]),
        ],
        stages=[
            Stage(
                iteration=iteration,
                steps=[
                    create_service_interruption_step(
                        service=Service.FSDB,
                        trigger=ServiceInterruptionTrigger.CRASH,
                    ),
                    create_longevity_step(duration=10),
                ],
            ),
        ],
    )


TEST_WEDGE_AGENT_AND_FSDB_CRASH_PLAYBOOK = Playbook(
    name="test_wedge_agent_and_fsdb_crash",
    prechecks=[
        PointInTimeHealthCheck(name=hc_types.CheckName.SYSTEMCTL_ACTIVE_STATE_CHECK),
        PointInTimeHealthCheck(name=hc_types.CheckName.WEDGE_AGENT_CONFIGURED_CHECK),
    ],
    postchecks=[
        PointInTimeHealthCheck(
            name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
            input_json=thrift_to_json(
                hc_types.IxiaPacketLossHealthCheckIn(
                    clear_traffic_stats=True,
                )
            ),
        )
    ],
    stages=[
        Stage(
            steps=[
                create_service_interruption_step(
                    service=Service.AGENT,
                    trigger=ServiceInterruptionTrigger.CRASH,
                ),
                create_service_interruption_step(
                    service=Service.FSDB,
                    trigger=ServiceInterruptionTrigger.CRASH,
                ),
            ],
            concurrent=True,
        ),
        Stage(
            steps=[
                create_service_convergence_step(services=[Service.AGENT, Service.FSDB]),
                create_longevity_step(duration=180),
            ],
        ),
    ],
)
