# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""TestConfig + stage builders for port-speed-flip qualification.

Provides ``service_event_stages`` and the speed-flip TestConfig generators used to
qualify port-speed transitions (e.g., 100G <-> 400G) under service interruption /
convergence on multi-DUT topologies.
"""

import typing as t
from dataclasses import dataclass

from taac.health_checks.healthcheck_definitions import (
    create_port_speed_snapshot_check,
)
from taac.playbooks.playbook_definitions import (
    create_speed_flip_playbook,
    create_speed_flip_test_config_playbook,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_longevity_step,
    create_port_speed_validation_step as get_validation_step,
    create_register_speed_flip_patcher_step,
    create_service_convergence_step,
    create_service_interruption_step,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import Endpoint, Playbook, Stage, TestConfig


# Function to create a list of stages for a service event test.
def service_event_stages(health_check_params: t.Dict[str, t.Any]) -> t.List[Stage]:
    """Returns a list of stages for a service event test."""

    return [
        # Agent Warmboot Stage
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=taac_types.Service.AGENT,
                    trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(
                    services=[taac_types.Service.AGENT],
                ),
                # Validation Step
                get_validation_step(health_check_params),
            ]
        ),
        # Agent Coldboot Stage
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=taac_types.Service.AGENT,
                    trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    create_cold_boot_file=True,
                ),
                create_service_convergence_step(
                    services=[taac_types.Service.AGENT],
                ),
                create_longevity_step(duration=180),
                get_validation_step(health_check_params),
            ]
        ),
        # Agent Crash Stage
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=taac_types.Service.AGENT,
                    trigger=taac_types.ServiceInterruptionTrigger.CRASH,
                ),
                create_service_convergence_step(
                    services=[taac_types.Service.AGENT],
                ),
                create_longevity_step(duration=180),
                get_validation_step(health_check_params),
            ]
        ),
        # Coop Crash + Warmboot Stage
        create_steps_stage(
            steps=[
                create_service_interruption_step(
                    service=taac_types.Service.COOP,
                    trigger=taac_types.ServiceInterruptionTrigger.CRASH,
                ),
                create_service_convergence_step(
                    services=[taac_types.Service.AGENT],
                ),
                create_longevity_step(duration=180),
                create_service_interruption_step(
                    service=taac_types.Service.AGENT,
                    trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                ),
                create_service_convergence_step(
                    services=[taac_types.Service.AGENT],
                ),
                get_validation_step(health_check_params),
            ]
        ),
    ]


@dataclass
class SpeedTransitionStage:
    """
    Represents a single stage in a speed flip scenario.

    Each stage defines:
    - endpoints (hostname -> ports mapping) to change
    - speed to change them to
    - patcher name
    - boolean for change port state to DOWN
    """

    endpoints: t.Dict[str, t.List[str]]
    speed_in_gbps: int
    patcher_name: str
    port_state_change: bool = False

    def __post_init__(self):
        """Validate that inputs are correct"""
        if not self.endpoints:
            raise ValueError("endpoints cannot be empty")
        if self.speed_in_gbps <= 0:
            raise ValueError("speed_in_gbps must be positive")


@dataclass
class SpeedFlipPlaybook:
    """
    Complete configuration for a speed flip test playbook

    Each playbook defines:
    - stages: List of SpeedTransitionStages
    - Device HealthCheck Parameters
    - Playbook Name
    - Number of iteration

    Significance of stages:
    For a scenario 200G -> 400G:

    Stage 1:
        Apply patcher 100G to 200G

    Stage 2:
        Apply patcher 200G to 400G

    List of SpeedTransitionStages are required because each stage might require change in endpoint and ports due to platform rule

    CRITICAL ORDERING GUARANTEES:
    1. Patcher Registration Stges: Execute in the order
    """

    stages: t.List[SpeedTransitionStage]
    health_check_params: t.Dict[str, t.Any]
    playbook_name: str
    number_of_iterations: int = 1

    def __post_init__(self) -> None:
        """"""
        if not self.stages:
            raise ValueError("At least one stage is required")

        if not self.health_check_params:
            raise ValueError("Health Check parameters cannot be empty")

    def build_playbook(self) -> Playbook:
        """
        Build a TAAC Playbook from this configuration

        Playbook Structure (GUARANTEED ORDER):
        1. Patcher Registration Stages (in order: A, B, C)
        2. Service Event Stages
        3. Patcher Unregistration Stages (in REVERSE order: C, B, A)

        Returns:
            A TAAC Playbook ready to execute
        """

        taac_stages = []

        """
        PHASE 1: PATHCER REGISTRATION STAGES
        Execute in forward order
        """
        for transition_stage in self.stages:
            step = create_register_speed_flip_patcher_step(
                register_patcher=True,
                port_state_change=transition_stage.port_state_change,
                patcher_name=transition_stage.patcher_name,
                endpoints=transition_stage.endpoints,
                speed_in_gbps=transition_stage.speed_in_gbps,
            )

            taac_stage = create_steps_stage(steps=[step])
            taac_stages.append(taac_stage)

        """
        PHASE 2: SERVICE EVENT STAGES
        """
        service_stages = service_event_stages(self.health_check_params)
        taac_stages.extend(service_stages)

        """
        PHASE 3: PATHCER UNREGISTRATION STAGES
        Execute in REVERSE order
        This ensures LIFO: Last registered patcher is unregistered first
        """

        for transition_stage in reversed(self.stages):
            step = create_register_speed_flip_patcher_step(
                register_patcher=False,
                port_state_change=transition_stage.port_state_change,
                patcher_name=transition_stage.patcher_name,
                endpoints=transition_stage.endpoints,
                speed_in_gbps=transition_stage.speed_in_gbps,
            )

            taac_stage = create_steps_stage(steps=[step])
            taac_stages.append(taac_stage)

        # Create the Playbook with all stages in order
        return create_speed_flip_playbook(
            name=self.playbook_name,
            stages=taac_stages,
            iteration=self.number_of_iterations,
        )


@dataclass
class SpeedFlipTestConfig:
    """
    Create a TestConfig with multiple Speed Flip Playbooks

    Each Test Config defines:
    - playbook: List of SpeedFlipPlaybook
    - Snapshot Health Check params
    - Test Config Name
    - Endpoints: All endpoint devices for this test with first one being DUT device
    """

    playbooks: t.List[SpeedFlipPlaybook]
    snapshot_health_check_params: t.Dict[str, t.Any]
    test_config_name: str
    endpoints: t.List[str]

    def __post_init__(self) -> None:
        """Validate configuration"""
        if not self.playbooks:
            raise ValueError("At least one SpeedFlipPlaybook is required")
        if not self.endpoints:
            raise ValueError("At least one endpoint is required")
        if not self.snapshot_health_check_params:
            raise ValueError("snapshot_health_check_params cannot be empty")
        if not self.test_config_name:
            raise ValueError("test_config_name cannot be empty")

    def build_test_config(self):
        """
        Build a TAAC TestConfig

        Returns:
            A TAAC TestConfig to execute
        """
        # Get the first hostname as the DUT device
        dut_device = next(iter(self.endpoints))

        test_endpoints = [
            Endpoint(name=hostname, dut=(hostname == dut_device))
            for hostname in self.endpoints
        ]

        # Explicit checkpoint IDs prevent stage-level checkpointing
        snapshot_checks = [
            create_port_speed_snapshot_check(
                json_params={"endpoints": self.snapshot_health_check_params},
                pre_snapshot_checkpoint_id="test_case_start",
                post_snapshot_checkpoint_id="test_case_end",
            ),
        ]

        taac_playbooks = []

        for playbook in self.playbooks:
            built_playbook = playbook.build_playbook()
            built_playbook = create_speed_flip_test_config_playbook(
                built_playbook=built_playbook,
                snapshot_checks=snapshot_checks,
            )
            taac_playbooks.append(built_playbook)

        test_config = TestConfig(
            name=self.test_config_name,
            basset_pool="dne.test",
            endpoints=test_endpoints,
            # Deprecated - define at playbook level
            playbooks=taac_playbooks,
        )

        return test_config


SPEED_FLIP_TEST_CONFIGS = [
    # Speed Flip Test Configs for 12.8T Platform
    # Only 100G to 200G Speed Flips Valid on 12.8T Platform
    # 1. With Port State's changed to DOWN before patcher
    SpeedFlipTestConfig(
        endpoints=["fsw004.p001.f01.qzd1", "ssw004.s004.f01.qzd1"],
        test_config_name="SPEED_FLIP_12T_TEST_PORTS_DOWN",
        snapshot_health_check_params={
            "fsw004.p001.f01.qzd1": ["eth3/7/1", "eth3/15/1"],
            "ssw004.s004.f01.qzd1": ["eth3/3/1", "eth3/4/1"],
        },
        playbooks=[
            SpeedFlipPlaybook(
                stages=[
                    SpeedTransitionStage(
                        endpoints={
                            "fsw004.p001.f01.qzd1": ["eth3/7/1", "eth3/15/1"],
                            "ssw004.s004.f01.qzd1": ["eth3/3/1", "eth3/4/1"],
                        },
                        speed_in_gbps=200,
                        patcher_name="change_speed_test_200",
                        port_state_change=True,
                    ),
                ],
                health_check_params={
                    "fsw004.p001.f01.qzd1": {
                        "interfaces": [
                            {
                                "interface_name": "eth3/7/1",
                                "expected_speed": 200,
                            },
                            {
                                "interface_name": "eth3/15/1",
                                "expected_speed": 200,
                            },
                        ],
                    },
                    "ssw004.s004.f01.qzd1": {
                        "interfaces": [
                            {
                                "interface_name": "eth3/3/1",
                                "expected_speed": 200,
                            },
                            {
                                "interface_name": "eth3/4/1",
                                "expected_speed": 200,
                            },
                        ],
                    },
                },
                playbook_name="SPEED_FLIP_12T_TEST_PORTS_DOWN_PLAYBOOK",
                number_of_iterations=1,
            )
        ],
    ).build_test_config(),
    # 2. With Port State's unchanged before patcher
    SpeedFlipTestConfig(
        endpoints=["fsw004.p001.f01.qzd1", "ssw004.s004.f01.qzd1"],
        test_config_name="SPEED_FLIP_12T_TEST_PORTS_UP",
        snapshot_health_check_params={
            "fsw004.p001.f01.qzd1": ["eth3/7/1", "eth3/15/1"],
            "ssw004.s004.f01.qzd1": ["eth3/3/1", "eth3/4/1"],
        },
        playbooks=[
            SpeedFlipPlaybook(
                stages=[
                    SpeedTransitionStage(
                        endpoints={
                            "fsw004.p001.f01.qzd1": ["eth3/7/1", "eth3/15/1"],
                            "ssw004.s004.f01.qzd1": ["eth3/3/1", "eth3/4/1"],
                        },
                        speed_in_gbps=200,
                        patcher_name="change_speed_test_200",
                        port_state_change=False,
                    ),
                ],
                health_check_params={
                    "fsw004.p001.f01.qzd1": {
                        "interfaces": [
                            {
                                "interface_name": "eth3/7/1",
                                "expected_speed": 200,
                            },
                            {
                                "interface_name": "eth3/15/1",
                                "expected_speed": 200,
                            },
                        ],
                    },
                    "ssw004.s004.f01.qzd1": {
                        "interfaces": [
                            {
                                "interface_name": "eth3/3/1",
                                "expected_speed": 200,
                            },
                            {
                                "interface_name": "eth3/4/1",
                                "expected_speed": 200,
                            },
                        ],
                    },
                },
                playbook_name="SPEED_FLIP_12T_TEST_PORTS_UP_PLAYBOOK",
                number_of_iterations=1,
            )
        ],
    ).build_test_config(),
    # Speed Flip Test Configs for 25.6T Platform
    # Multiple Playbook Scenarios
    # a. 100G to 200G
    # b. 100G to 400G
    # c. 200G to 400G
    # 1.  With Port State's changed to DOWN before patcher
    SpeedFlipTestConfig(
        endpoints=["ssw004.s004.f01.qzd1", "fa001-du004.qzd1"],
        test_config_name="SPEED_FLIP_25T_TEST_PORTS_DOWN",
        snapshot_health_check_params={
            "ssw004.s004.f01.qzd1": ["eth2/13/1", "eth2/14/1"],
            "fa001-du004.qzd1": ["eth8/9/1", "eth8/10/1", "eth8/11/1", "eth8/12/1"],
        },
        playbooks=[
            # 100G to 200G Playbook
            SpeedFlipPlaybook(
                stages=[
                    SpeedTransitionStage(
                        endpoints={
                            "ssw004.s004.f01.qzd1": ["eth2/13/1", "eth2/14/1"],
                            "fa001-du004.qzd1": [
                                "eth8/9/1",
                                "eth8/10/1",
                                "eth8/11/1",
                                "eth8/12/1",
                            ],
                        },
                        speed_in_gbps=200,
                        patcher_name="change_speed_test_200",
                        port_state_change=True,
                    ),
                ],
                health_check_params={
                    "ssw004.s004.f01.qzd1": {
                        "interfaces": [
                            {
                                "interface_name": "eth2/13/1",
                                "expected_speed": 200,
                            },
                            {
                                "interface_name": "eth2/14/1",
                                "expected_speed": 200,
                            },
                        ]
                    },
                    "fa001-du004.qzd1": {
                        "interfaces": [
                            {
                                "interface_name": "eth8/9/1",
                                "expected_speed": 200,
                            },
                            {
                                "interface_name": "eth8/10/1",
                                "expected_speed": 200,
                            },
                            {
                                "interface_name": "eth8/11/1",
                                "expected_speed": 200,
                            },
                            {
                                "interface_name": "eth8/12/1",
                                "expected_speed": 200,
                            },
                        ]
                    },
                },
                playbook_name="SPEED_FLIP_25T_TEST_PORTS_DOWN_100G_TO_200G_PLAYBOOK",
                number_of_iterations=1,
            ),
            # 100G to 400G Playbook
            SpeedFlipPlaybook(
                stages=[
                    SpeedTransitionStage(
                        endpoints={
                            "ssw004.s004.f01.qzd1": ["eth2/13/1"],
                            "fa001-du004.qzd1": ["eth8/9/1"],
                        },
                        speed_in_gbps=400,
                        patcher_name="change_speed_test_400",
                        port_state_change=True,
                    ),
                ],
                health_check_params={
                    "ssw004.s004.f01.qzd1": {
                        "interfaces": [
                            {
                                "interface_name": "eth2/13/1",
                                "expected_speed": 400,
                            },
                        ]
                    },
                    "fa001-du004.qzd1": {
                        "interfaces": [
                            {
                                "interface_name": "eth8/9/1",
                                "expected_speed": 400,
                            },
                        ]
                    },
                },
                playbook_name="SPEED_FLIP_25T_TEST_PORTS_DOWN_100G_TO_400G_PLAYBOOK",
                number_of_iterations=1,
            ),
            # 200G to 400G Playbook
            SpeedFlipPlaybook(
                stages=[
                    SpeedTransitionStage(
                        endpoints={
                            "ssw004.s004.f01.qzd1": ["eth2/13/1", "eth2/14/1"],
                            "fa001-du004.qzd1": [
                                "eth8/9/1",
                                "eth8/10/1",
                                "eth8/11/1",
                                "eth8/12/1",
                            ],
                        },
                        speed_in_gbps=200,
                        patcher_name="change_speed_test_200",
                        port_state_change=True,
                    ),
                    SpeedTransitionStage(
                        endpoints={
                            "ssw004.s004.f01.qzd1": ["eth2/13/1"],
                            "fa001-du004.qzd1": ["eth8/9/1"],
                        },
                        speed_in_gbps=400,
                        patcher_name="change_speed_test_400",
                        port_state_change=True,
                    ),
                ],
                health_check_params={
                    "ssw004.s004.f01.qzd1": {
                        "interfaces": [
                            {
                                "interface_name": "eth2/13/1",
                                "expected_speed": 400,
                            },
                        ]
                    },
                    "fa001-du004.qzd1": {
                        "interfaces": [
                            {
                                "interface_name": "eth8/9/1",
                                "expected_speed": 400,
                            },
                        ]
                    },
                },
                playbook_name="SPEED_FLIP_25T_TEST_PORTS_DOWN_200G_TO_400G_PLAYBOOK",
                number_of_iterations=1,
            ),
        ],
    ).build_test_config(),
    # 2. With Port State's unchanged before patcher
    SpeedFlipTestConfig(
        endpoints=["ssw004.s004.f01.qzd1", "fa001-du004.qzd1"],
        test_config_name="SPEED_FLIP_25T_TEST_PORTS_UP",
        snapshot_health_check_params={
            "ssw004.s004.f01.qzd1": ["eth2/13/1", "eth2/14/1"],
            "fa001-du004.qzd1": ["eth8/9/1", "eth8/10/1", "eth8/11/1", "eth8/12/1"],
        },
        playbooks=[
            # 100G to 200G Playbook
            SpeedFlipPlaybook(
                stages=[
                    SpeedTransitionStage(
                        endpoints={
                            "ssw004.s004.f01.qzd1": ["eth2/13/1", "eth2/14/1"],
                            "fa001-du004.qzd1": [
                                "eth8/9/1",
                                "eth8/10/1",
                                "eth8/11/1",
                                "eth8/12/1",
                            ],
                        },
                        speed_in_gbps=200,
                        patcher_name="change_speed_test_200",
                        port_state_change=False,
                    ),
                ],
                health_check_params={
                    "ssw004.s004.f01.qzd1": {
                        "interfaces": [
                            {
                                "interface_name": "eth2/13/1",
                                "expected_speed": 200,
                            },
                            {
                                "interface_name": "eth2/14/1",
                                "expected_speed": 200,
                            },
                        ]
                    },
                    "fa001-du004.qzd1": {
                        "interfaces": [
                            {
                                "interface_name": "eth8/9/1",
                                "expected_speed": 200,
                            },
                            {
                                "interface_name": "eth8/10/1",
                                "expected_speed": 200,
                            },
                            {
                                "interface_name": "eth8/11/1",
                                "expected_speed": 200,
                            },
                            {
                                "interface_name": "eth8/12/1",
                                "expected_speed": 200,
                            },
                        ]
                    },
                },
                playbook_name="SPEED_FLIP_25T_TEST_PORTS_UP_100G_TO_200G_PLAYBOOK",
                number_of_iterations=1,
            ),
            # 100G to 400G Playbook
            SpeedFlipPlaybook(
                stages=[
                    SpeedTransitionStage(
                        endpoints={
                            "ssw004.s004.f01.qzd1": ["eth2/13/1"],
                            "fa001-du004.qzd1": ["eth8/9/1"],
                        },
                        speed_in_gbps=400,
                        patcher_name="change_speed_test_400",
                        port_state_change=False,
                    ),
                ],
                health_check_params={
                    "ssw004.s004.f01.qzd1": {
                        "interfaces": [
                            {
                                "interface_name": "eth2/13/1",
                                "expected_speed": 400,
                            },
                        ]
                    },
                    "fa001-du004.qzd1": {
                        "interfaces": [
                            {
                                "interface_name": "eth8/9/1",
                                "expected_speed": 400,
                            },
                        ]
                    },
                },
                playbook_name="SPEED_FLIP_25T_TEST_PORTS_UP_100G_TO_400G_PLAYBOOK",
                number_of_iterations=1,
            ),
            # 200G to 400G Playbook
            SpeedFlipPlaybook(
                stages=[
                    SpeedTransitionStage(
                        endpoints={
                            "ssw004.s004.f01.qzd1": ["eth2/13/1", "eth2/14/1"],
                            "fa001-du004.qzd1": [
                                "eth8/9/1",
                                "eth8/10/1",
                                "eth8/11/1",
                                "eth8/12/1",
                            ],
                        },
                        speed_in_gbps=200,
                        patcher_name="change_speed_test_200",
                        port_state_change=False,
                    ),
                    SpeedTransitionStage(
                        endpoints={
                            "ssw004.s004.f01.qzd1": ["eth2/13/1"],
                            "fa001-du004.qzd1": ["eth8/9/1"],
                        },
                        speed_in_gbps=400,
                        patcher_name="change_speed_test_400",
                        port_state_change=False,
                    ),
                ],
                health_check_params={
                    "ssw004.s004.f01.qzd1": {
                        "interfaces": [
                            {
                                "interface_name": "eth2/13/1",
                                "expected_speed": 400,
                            },
                        ]
                    },
                    "fa001-du004.qzd1": {
                        "interfaces": [
                            {
                                "interface_name": "eth8/9/1",
                                "expected_speed": 400,
                            },
                        ]
                    },
                },
                playbook_name="SPEED_FLIP_25T_TEST_PORTS_UP_200G_TO_400G_PLAYBOOK",
                number_of_iterations=1,
            ),
        ],
    ).build_test_config(),
    # Speed Flip Test Configs for 51T Platform
    # Multiple Playbook Scenarios
    # a. 2x100G to 2x200G
    # b. 2x100G to 2x400G
    # c. 2x100G to 200G/400G
    # d. 2x100G to 400G/200G
    # e. 100G to 800G
    # f. 2x200G to 400G
    # g. 2x200G to 200G/400G
    # f. 2x200G to 400G/200G
    # h. 200G to 800G
    # i. 200G/400G to 800G
    # j. 400G/200G to 800G
    # k. 400G to 800G
    # 1.  With Port State's changed to DOWN before patcher
    SpeedFlipTestConfig(
        endpoints=["fsw003.p001.m001.qzr1", "rsw001.p001.m001.qzr1"],
        test_config_name="SPEED_FLIP_51T_TEST_PORTS_DOWN",
        snapshot_health_check_params={
            "fsw003.p001.m001.qzr1": [
                "eth1/17/1",
                "eth1/17/5",
                "eth1/23/1",
                "eth1/23/5",
            ],
            "rsw001.p001.m001.qzr1": [
                "eth1/33/1",
                "eth1/33/5",
                "eth1/29/1",
                "eth1/29/5",
            ],
        },
        # All ports are normally at 400G
        # Needs to first revert the ports to 100G
        playbooks=[
            # 100G to 200G Playbook
            SpeedFlipPlaybook(
                stages=[
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/17/1", "eth1/17/5"],
                            "rsw001.p001.m001.qzr1": ["eth1/33/1", "eth1/33/5"],
                        },
                        speed_in_gbps=100,
                        patcher_name="change_speed_test_100",
                        port_state_change=True,
                    ),
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/17/1", "eth1/17/5"],
                            "rsw001.p001.m001.qzr1": ["eth1/33/1", "eth1/33/5"],
                        },
                        speed_in_gbps=200,
                        patcher_name="change_speed_test_200",
                        port_state_change=True,
                    ),
                ],
                health_check_params={
                    "fsw003.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/17/1",
                                "expected_speed": 200,
                            },
                            {
                                "interface_name": "eth1/17/5",
                                "expected_speed": 200,
                            },
                        ]
                    },
                    "rsw001.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/33/1",
                                "expected_speed": 200,
                            },
                            {
                                "interface_name": "eth1/33/5",
                                "expected_speed": 200,
                            },
                        ]
                    },
                },
                playbook_name="SPEED_FLIP_51T_TEST_PORTS_DOWN_100G_TO_200G_PLAYBOOK",
                number_of_iterations=1,
            ),
            # 100G to 400G Playbook
            SpeedFlipPlaybook(
                stages=[
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/17/1", "eth1/17/5"],
                            "rsw001.p001.m001.qzr1": ["eth1/33/1", "eth1/33/5"],
                        },
                        speed_in_gbps=100,
                        patcher_name="change_speed_test_100",
                        port_state_change=True,
                    ),
                ],
                health_check_params={
                    "fsw003.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/17/1",
                                "expected_speed": 100,
                            },
                            {
                                "interface_name": "eth1/17/5",
                                "expected_speed": 100,
                            },
                        ]
                    },
                    "rsw001.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/33/1",
                                "expected_speed": 100,
                            },
                            {
                                "interface_name": "eth1/33/5",
                                "expected_speed": 100,
                            },
                        ]
                    },
                },
                playbook_name="SPEED_FLIP_51T_TEST_PORTS_DOWN_100G_TO_400G_PLAYBOOK",
                number_of_iterations=1,
            ),
            # 2x100G to 200G/400G Playbook (/5 ports to 400G)
            SpeedFlipPlaybook(
                stages=[
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/17/1", "eth1/17/5"],
                            "rsw001.p001.m001.qzr1": ["eth1/33/1", "eth1/33/5"],
                        },
                        speed_in_gbps=100,
                        patcher_name="change_speed_test_100",
                        port_state_change=True,
                    ),
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/17/1", "eth1/17/5"],
                            "rsw001.p001.m001.qzr1": ["eth1/33/1", "eth1/33/5"],
                        },
                        speed_in_gbps=200,
                        patcher_name="change_speed_test_200",
                        port_state_change=True,
                    ),
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/17/5"],
                            "rsw001.p001.m001.qzr1": ["eth1/33/5"],
                        },
                        speed_in_gbps=400,
                        patcher_name="change_speed_test_400",
                        port_state_change=True,
                    ),
                ],
                health_check_params={
                    "fsw003.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/17/1",
                                "expected_speed": 200,
                            },
                            {
                                "interface_name": "eth1/17/5",
                                "expected_speed": 400,
                            },
                        ]
                    },
                    "rsw001.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/33/1",
                                "expected_speed": 200,
                            },
                            {
                                "interface_name": "eth1/33/5",
                                "expected_speed": 400,
                            },
                        ]
                    },
                },
                playbook_name="SPEED_FLIP_51T_TEST_PORTS_DOWN_100G_TO_200G/400G_PLAYBOOK",
                number_of_iterations=1,
            ),
            # 2x100G to 400G/200G Playbook (/1 ports to 400G)
            SpeedFlipPlaybook(
                stages=[
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/17/1", "eth1/17/5"],
                            "rsw001.p001.m001.qzr1": ["eth1/33/1", "eth1/33/5"],
                        },
                        speed_in_gbps=100,
                        patcher_name="change_speed_test_100",
                        port_state_change=True,
                    ),
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/17/1", "eth1/17/5"],
                            "rsw001.p001.m001.qzr1": ["eth1/33/1", "eth1/33/5"],
                        },
                        speed_in_gbps=200,
                        patcher_name="change_speed_test_200",
                        port_state_change=True,
                    ),
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/17/1"],
                            "rsw001.p001.m001.qzr1": ["eth1/33/1"],
                        },
                        speed_in_gbps=400,
                        patcher_name="change_speed_test_400",
                        port_state_change=True,
                    ),
                ],
                health_check_params={
                    "fsw003.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/17/1",
                                "expected_speed": 400,
                            },
                            {
                                "interface_name": "eth1/17/5",
                                "expected_speed": 200,
                            },
                        ]
                    },
                    "rsw001.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/33/1",
                                "expected_speed": 400,
                            },
                            {
                                "interface_name": "eth1/33/5",
                                "expected_speed": 200,
                            },
                        ]
                    },
                },
                playbook_name="SPEED_FLIP_51T_TEST_PORTS_DOWN_100G_TO_400G/200G_PLAYBOOK",
                number_of_iterations=1,
            ),
            # 100G to 800G Playbook
            SpeedFlipPlaybook(
                stages=[
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/23/1", "eth1/23/5"],
                            "rsw001.p001.m001.qzr1": ["eth1/29/1", "eth1/29/5"],
                        },
                        speed_in_gbps=100,
                        patcher_name="change_speed_test_100",
                        port_state_change=True,
                    ),
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/23/1"],
                            "rsw001.p001.m001.qzr1": ["eth1/29/1"],
                        },
                        speed_in_gbps=800,
                        patcher_name="change_speed_test_800",
                        port_state_change=True,
                    ),
                ],
                health_check_params={
                    "fsw003.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/23/1",
                                "expected_speed": 800,
                            },
                        ]
                    },
                    "rsw001.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/29/1",
                                "expected_speed": 800,
                            },
                        ]
                    },
                },
                playbook_name="SPEED_FLIP_51T_TEST_PORTS_DOWN_100G_TO_800G_PLAYBOOK",
                number_of_iterations=1,
            ),
            # 200G to 400G Playbook
            SpeedFlipPlaybook(
                stages=[
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/17/1", "eth1/17/5"],
                            "rsw001.p001.m001.qzr1": ["eth1/33/1", "eth1/33/5"],
                        },
                        speed_in_gbps=200,
                        patcher_name="change_speed_test_200",
                        port_state_change=True,
                    ),
                ],
                health_check_params={
                    "fsw003.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/17/1",
                                "expected_speed": 200,
                            },
                            {
                                "interface_name": "eth1/17/5",
                                "expected_speed": 200,
                            },
                        ]
                    },
                    "rsw001.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/33/1",
                                "expected_speed": 200,
                            },
                            {
                                "interface_name": "eth1/33/5",
                                "expected_speed": 200,
                            },
                        ]
                    },
                },
                playbook_name="SPEED_FLIP_51T_TEST_PORTS_DOWN_200G_TO_400G_PLAYBOOK",
                number_of_iterations=1,
            ),
            # 2x200G to 200G/400G Playbook (/1 port to 200G)
            SpeedFlipPlaybook(
                stages=[
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/17/1"],
                            "rsw001.p001.m001.qzr1": ["eth1/33/1"],
                        },
                        speed_in_gbps=200,
                        patcher_name="change_speed_test_200",
                        port_state_change=True,
                    ),
                ],
                health_check_params={
                    "fsw003.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/17/1",
                                "expected_speed": 200,
                            },
                            {
                                "interface_name": "eth1/17/5",
                                "expected_speed": 400,
                            },
                        ]
                    },
                    "rsw001.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/33/1",
                                "expected_speed": 200,
                            },
                            {
                                "interface_name": "eth1/33/5",
                                "expected_speed": 400,
                            },
                        ]
                    },
                },
                playbook_name="SPEED_FLIP_51T_TEST_PORTS_DOWN_200G_TO_200G/400G_PLAYBOOK",
                number_of_iterations=1,
            ),
            # 2x200G to 400G/200G Playbook
            SpeedFlipPlaybook(
                stages=[
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/17/5"],
                            "rsw001.p001.m001.qzr1": ["eth1/33/5"],
                        },
                        speed_in_gbps=200,
                        patcher_name="change_speed_test_200",
                        port_state_change=True,
                    ),
                ],
                health_check_params={
                    "fsw003.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/17/1",
                                "expected_speed": 400,
                            },
                            {
                                "interface_name": "eth1/17/5",
                                "expected_speed": 200,
                            },
                        ]
                    },
                    "rsw001.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/33/1",
                                "expected_speed": 400,
                            },
                            {
                                "interface_name": "eth1/33/5",
                                "expected_speed": 200,
                            },
                        ]
                    },
                },
                playbook_name="SPEED_FLIP_51T_TEST_PORTS_DOWN_200G_TO_400G/200G_PLAYBOOK",
                number_of_iterations=1,
            ),
            # 200G to 800G Playbook
            SpeedFlipPlaybook(
                stages=[
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/23/1", "eth1/23/5"],
                            "rsw001.p001.m001.qzr1": ["eth1/29/1", "eth1/29/5"],
                        },
                        speed_in_gbps=200,
                        patcher_name="change_speed_test_200",
                        port_state_change=True,
                    ),
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/23/1"],
                            "rsw001.p001.m001.qzr1": ["eth1/29/1"],
                        },
                        speed_in_gbps=800,
                        patcher_name="change_speed_test_800",
                        port_state_change=True,
                    ),
                ],
                health_check_params={
                    "fsw003.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/23/1",
                                "expected_speed": 800,
                            },
                        ]
                    },
                    "rsw001.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/29/1",
                                "expected_speed": 800,
                            },
                        ]
                    },
                },
                playbook_name="SPEED_FLIP_51T_TEST_PORTS_DOWN_200G_TO_800G_PLAYBOOK",
                number_of_iterations=1,
            ),
            # 200G/400G to 800G Playbook (/1 port to 200G first)
            SpeedFlipPlaybook(
                stages=[
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/23/1"],
                            "rsw001.p001.m001.qzr1": ["eth1/29/1"],
                        },
                        speed_in_gbps=200,
                        patcher_name="change_speed_test_200",
                        port_state_change=True,
                    ),
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/23/1"],
                            "rsw001.p001.m001.qzr1": ["eth1/29/1"],
                        },
                        speed_in_gbps=800,
                        patcher_name="change_speed_test_800",
                        port_state_change=True,
                    ),
                ],
                health_check_params={
                    "fsw003.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/23/1",
                                "expected_speed": 800,
                            },
                        ]
                    },
                    "rsw001.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/29/1",
                                "expected_speed": 800,
                            },
                        ]
                    },
                },
                playbook_name="SPEED_FLIP_51T_TEST_PORTS_DOWN_200G/400G_TO_800G_PLAYBOOK",
                number_of_iterations=1,
            ),
            # 400G/200G to 800G Playbook (/1 port to 200G first)
            SpeedFlipPlaybook(
                stages=[
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/23/5"],
                            "rsw001.p001.m001.qzr1": ["eth1/29/5"],
                        },
                        speed_in_gbps=200,
                        patcher_name="change_speed_test_200",
                        port_state_change=True,
                    ),
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/23/1"],
                            "rsw001.p001.m001.qzr1": ["eth1/29/1"],
                        },
                        speed_in_gbps=800,
                        patcher_name="change_speed_test_800",
                        port_state_change=True,
                    ),
                ],
                health_check_params={
                    "fsw003.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/23/1",
                                "expected_speed": 800,
                            },
                        ]
                    },
                    "rsw001.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/29/1",
                                "expected_speed": 800,
                            },
                        ]
                    },
                },
                playbook_name="SPEED_FLIP_51T_TEST_PORTS_DOWN_400G/200G_TO_800G_PLAYBOOK",
                number_of_iterations=1,
            ),
            # 400G to 800G Playbook
            SpeedFlipPlaybook(
                stages=[
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/23/1"],
                            "rsw001.p001.m001.qzr1": ["eth1/29/1"],
                        },
                        speed_in_gbps=800,
                        patcher_name="change_speed_test_800",
                        port_state_change=True,
                    ),
                ],
                health_check_params={
                    "fsw003.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/23/1",
                                "expected_speed": 800,
                            },
                        ]
                    },
                    "rsw001.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/29/1",
                                "expected_speed": 800,
                            },
                        ]
                    },
                },
                playbook_name="SPEED_FLIP_51T_TEST_PORTS_DOWN_400G_TO_800G_PLAYBOOK",
                number_of_iterations=1,
            ),
        ],
    ).build_test_config(),
    # 2. With Port State's unchanged before patcher
    SpeedFlipTestConfig(
        endpoints=["fsw003.p001.m001.qzr1", "rsw001.p001.m001.qzr1"],
        test_config_name="SPEED_FLIP_51T_TEST_PORTS_UP",
        snapshot_health_check_params={
            "fsw003.p001.m001.qzr1": ["eth1/17/1", "eth1/17/5"],
            "rsw001.p001.m001.qzr1": ["eth1/33/1", "eth1/33/5"],
        },
        # All ports are normally at 400G
        # Needs to first revert the ports to 100G
        playbooks=[
            # 100G to 200G Playbook
            SpeedFlipPlaybook(
                stages=[
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/17/1", "eth1/17/5"],
                            "rsw001.p001.m001.qzr1": ["eth1/33/1", "eth1/33/5"],
                        },
                        speed_in_gbps=100,
                        patcher_name="change_speed_test_100",
                        port_state_change=False,
                    ),
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/17/1", "eth1/17/5"],
                            "rsw001.p001.m001.qzr1": ["eth1/33/1", "eth1/33/5"],
                        },
                        speed_in_gbps=200,
                        patcher_name="change_speed_test_200",
                        port_state_change=False,
                    ),
                ],
                health_check_params={
                    "fsw003.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/17/1",
                                "expected_speed": 200,
                            },
                            {
                                "interface_name": "eth1/17/5",
                                "expected_speed": 200,
                            },
                        ]
                    },
                    "rsw001.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/33/1",
                                "expected_speed": 200,
                            },
                            {
                                "interface_name": "eth1/33/5",
                                "expected_speed": 200,
                            },
                        ]
                    },
                },
                playbook_name="SPEED_FLIP_51T_TEST_PORTS_UP_100G_TO_200G_PLAYBOOK",
                number_of_iterations=1,
            ),
            # 100G to 400G Playbook
            SpeedFlipPlaybook(
                stages=[
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/17/1", "eth1/17/5"],
                            "rsw001.p001.m001.qzr1": ["eth1/33/1", "eth1/33/5"],
                        },
                        speed_in_gbps=100,
                        patcher_name="change_speed_test_100",
                        port_state_change=False,
                    ),
                ],
                health_check_params={
                    "fsw003.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/17/1",
                                "expected_speed": 100,
                            },
                            {
                                "interface_name": "eth1/17/5",
                                "expected_speed": 100,
                            },
                        ]
                    },
                    "rsw001.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/33/1",
                                "expected_speed": 100,
                            },
                            {
                                "interface_name": "eth1/33/5",
                                "expected_speed": 100,
                            },
                        ]
                    },
                },
                playbook_name="SPEED_FLIP_51T_TEST_PORTS_UP_100G_TO_400G_PLAYBOOK",
                number_of_iterations=1,
            ),
            # 2x100G to 200G/400G Playbook (/5 ports to 400G)
            SpeedFlipPlaybook(
                stages=[
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/17/1", "eth1/17/5"],
                            "rsw001.p001.m001.qzr1": ["eth1/33/1", "eth1/33/5"],
                        },
                        speed_in_gbps=100,
                        patcher_name="change_speed_test_100",
                        port_state_change=False,
                    ),
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/17/1", "eth1/17/5"],
                            "rsw001.p001.m001.qzr1": ["eth1/33/1", "eth1/33/5"],
                        },
                        speed_in_gbps=200,
                        patcher_name="change_speed_test_200",
                        port_state_change=False,
                    ),
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/17/5"],
                            "rsw001.p001.m001.qzr1": ["eth1/33/5"],
                        },
                        speed_in_gbps=400,
                        patcher_name="change_speed_test_400",
                        port_state_change=False,
                    ),
                ],
                health_check_params={
                    "fsw003.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/17/1",
                                "expected_speed": 200,
                            },
                            {
                                "interface_name": "eth1/17/5",
                                "expected_speed": 400,
                            },
                        ]
                    },
                    "rsw001.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/33/1",
                                "expected_speed": 200,
                            },
                            {
                                "interface_name": "eth1/33/5",
                                "expected_speed": 400,
                            },
                        ]
                    },
                },
                playbook_name="SPEED_FLIP_51T_TEST_PORTS_UP_100G_TO_200G/400G_PLAYBOOK",
                number_of_iterations=1,
            ),
            # 2x100G to 400G/200G Playbook (/1 ports to 400G)
            SpeedFlipPlaybook(
                stages=[
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/17/1", "eth1/17/5"],
                            "rsw001.p001.m001.qzr1": ["eth1/33/1", "eth1/33/5"],
                        },
                        speed_in_gbps=100,
                        patcher_name="change_speed_test_100",
                        port_state_change=False,
                    ),
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/17/1", "eth1/17/5"],
                            "rsw001.p001.m001.qzr1": ["eth1/33/1", "eth1/33/5"],
                        },
                        speed_in_gbps=200,
                        patcher_name="change_speed_test_200",
                        port_state_change=False,
                    ),
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/17/1"],
                            "rsw001.p001.m001.qzr1": ["eth1/33/1"],
                        },
                        speed_in_gbps=400,
                        patcher_name="change_speed_test_400",
                        port_state_change=False,
                    ),
                ],
                health_check_params={
                    "fsw003.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/17/1",
                                "expected_speed": 400,
                            },
                            {
                                "interface_name": "eth1/17/5",
                                "expected_speed": 200,
                            },
                        ]
                    },
                    "rsw001.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/33/1",
                                "expected_speed": 400,
                            },
                            {
                                "interface_name": "eth1/33/5",
                                "expected_speed": 200,
                            },
                        ]
                    },
                },
                playbook_name="SPEED_FLIP_51T_TEST_PORTS_UP_100G_TO_400G/200G_PLAYBOOK",
                number_of_iterations=1,
            ),
            # 100G to 800G Playbook
            SpeedFlipPlaybook(
                stages=[
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/17/1", "eth1/17/5"],
                            "rsw001.p001.m001.qzr1": ["eth1/33/1", "eth1/33/5"],
                        },
                        speed_in_gbps=100,
                        patcher_name="change_speed_test_100",
                        port_state_change=False,
                    ),
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/17/1"],
                            "rsw001.p001.m001.qzr1": ["eth1/33/1"],
                        },
                        speed_in_gbps=800,
                        patcher_name="change_speed_test_800",
                        port_state_change=False,
                    ),
                ],
                health_check_params={
                    "fsw003.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/17/1",
                                "expected_speed": 800,
                            },
                        ]
                    },
                    "rsw001.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/33/1",
                                "expected_speed": 800,
                            },
                        ]
                    },
                },
                playbook_name="SPEED_FLIP_51T_TEST_PORTS_UP_100G_TO_800G_PLAYBOOK",
                number_of_iterations=1,
            ),
            # 200G to 400G Playbook
            SpeedFlipPlaybook(
                stages=[
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/17/1", "eth1/17/5"],
                            "rsw001.p001.m001.qzr1": ["eth1/33/1", "eth1/33/5"],
                        },
                        speed_in_gbps=200,
                        patcher_name="change_speed_test_200",
                        port_state_change=False,
                    ),
                ],
                health_check_params={
                    "fsw003.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/17/1",
                                "expected_speed": 200,
                            },
                            {
                                "interface_name": "eth1/17/5",
                                "expected_speed": 200,
                            },
                        ]
                    },
                    "rsw001.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/33/1",
                                "expected_speed": 200,
                            },
                            {
                                "interface_name": "eth1/33/5",
                                "expected_speed": 200,
                            },
                        ]
                    },
                },
                playbook_name="SPEED_FLIP_51T_TEST_PORTS_UP_200G_TO_400G_PLAYBOOK",
                number_of_iterations=1,
            ),
            # 2x200G to 200G/400G Playbook (/1 port to 200G)
            SpeedFlipPlaybook(
                stages=[
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/17/1"],
                            "rsw001.p001.m001.qzr1": ["eth1/33/1"],
                        },
                        speed_in_gbps=200,
                        patcher_name="change_speed_test_200",
                        port_state_change=False,
                    ),
                ],
                health_check_params={
                    "fsw003.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/17/1",
                                "expected_speed": 200,
                            },
                            {
                                "interface_name": "eth1/17/5",
                                "expected_speed": 400,
                            },
                        ]
                    },
                    "rsw001.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/33/1",
                                "expected_speed": 200,
                            },
                            {
                                "interface_name": "eth1/33/5",
                                "expected_speed": 400,
                            },
                        ]
                    },
                },
                playbook_name="SPEED_FLIP_51T_TEST_PORTS_UP_200G_TO_200G/400G_PLAYBOOK",
                number_of_iterations=1,
            ),
            # 2x200G to 400G/200G Playbook
            SpeedFlipPlaybook(
                stages=[
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/17/5"],
                            "rsw001.p001.m001.qzr1": ["eth1/33/5"],
                        },
                        speed_in_gbps=200,
                        patcher_name="change_speed_test_200",
                        port_state_change=False,
                    ),
                ],
                health_check_params={
                    "fsw003.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/17/1",
                                "expected_speed": 400,
                            },
                            {
                                "interface_name": "eth1/17/5",
                                "expected_speed": 200,
                            },
                        ]
                    },
                    "rsw001.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/33/1",
                                "expected_speed": 400,
                            },
                            {
                                "interface_name": "eth1/33/5",
                                "expected_speed": 200,
                            },
                        ]
                    },
                },
                playbook_name="SPEED_FLIP_51T_TEST_PORTS_UP_200G_TO_400G/200G_PLAYBOOK",
                number_of_iterations=1,
            ),
            # 200G to 800G Playbook
            SpeedFlipPlaybook(
                stages=[
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/17/1", "eth1/17/5"],
                            "rsw001.p001.m001.qzr1": ["eth1/33/1", "eth1/33/5"],
                        },
                        speed_in_gbps=200,
                        patcher_name="change_speed_test_200",
                        port_state_change=False,
                    ),
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/17/1"],
                            "rsw001.p001.m001.qzr1": ["eth1/33/1"],
                        },
                        speed_in_gbps=800,
                        patcher_name="change_speed_test_800",
                        port_state_change=False,
                    ),
                ],
                health_check_params={
                    "fsw003.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/17/1",
                                "expected_speed": 800,
                            },
                        ]
                    },
                    "rsw001.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/33/1",
                                "expected_speed": 800,
                            },
                        ]
                    },
                },
                playbook_name="SPEED_FLIP_51T_TEST_PORTS_UP_200G_TO_800G_PLAYBOOK",
                number_of_iterations=1,
            ),
            # 200G/400G to 800G Playbook (/1 port to 200G first)
            SpeedFlipPlaybook(
                stages=[
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/17/1"],
                            "rsw001.p001.m001.qzr1": ["eth1/33/1"],
                        },
                        speed_in_gbps=200,
                        patcher_name="change_speed_test_200",
                        port_state_change=False,
                    ),
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/17/1"],
                            "rsw001.p001.m001.qzr1": ["eth1/33/1"],
                        },
                        speed_in_gbps=800,
                        patcher_name="change_speed_test_800",
                        port_state_change=False,
                    ),
                ],
                health_check_params={
                    "fsw003.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/17/1",
                                "expected_speed": 800,
                            },
                        ]
                    },
                    "rsw001.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/33/1",
                                "expected_speed": 800,
                            },
                        ]
                    },
                },
                playbook_name="SPEED_FLIP_51T_TEST_PORTS_UP_200G/400G_TO_800G_PLAYBOOK",
                number_of_iterations=1,
            ),
            # 400G/200G to 800G Playbook (/1 port to 200G first)
            SpeedFlipPlaybook(
                stages=[
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/17/5"],
                            "rsw001.p001.m001.qzr1": ["eth1/33/5"],
                        },
                        speed_in_gbps=200,
                        patcher_name="change_speed_test_200",
                        port_state_change=False,
                    ),
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/17/1"],
                            "rsw001.p001.m001.qzr1": ["eth1/33/1"],
                        },
                        speed_in_gbps=800,
                        patcher_name="change_speed_test_800",
                        port_state_change=False,
                    ),
                ],
                health_check_params={
                    "fsw003.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/17/1",
                                "expected_speed": 800,
                            },
                        ]
                    },
                    "rsw001.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/33/1",
                                "expected_speed": 800,
                            },
                        ]
                    },
                },
                playbook_name="SPEED_FLIP_51T_TEST_PORTS_UP_400G/200G_TO_800G_PLAYBOOK",
                number_of_iterations=1,
            ),
            # 400G to 800G Playbook
            SpeedFlipPlaybook(
                stages=[
                    SpeedTransitionStage(
                        endpoints={
                            "fsw003.p001.m001.qzr1": ["eth1/17/1"],
                            "rsw001.p001.m001.qzr1": ["eth1/33/1"],
                        },
                        speed_in_gbps=800,
                        patcher_name="change_speed_test_800",
                        port_state_change=False,
                    ),
                ],
                health_check_params={
                    "fsw003.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/17/1",
                                "expected_speed": 800,
                            },
                        ]
                    },
                    "rsw001.p001.m001.qzr1": {
                        "interfaces": [
                            {
                                "interface_name": "eth1/33/1",
                                "expected_speed": 800,
                            },
                        ]
                    },
                },
                playbook_name="SPEED_FLIP_51T_TEST_PORTS_UP_400G_TO_800G_PLAYBOOK",
                number_of_iterations=1,
            ),
        ],
    ).build_test_config(),
]
