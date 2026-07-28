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
    create_drain_undrain_step,
    create_fpf_set_interface_admin_step,
    create_longevity_step,
    create_port_speed_validation_step as get_validation_step,
    create_register_speed_flip_patcher_step,
    create_service_convergence_step,
    create_service_interruption_step,
    create_system_reboot_step,
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


def _reboot_undrain_stages(
    health_check_params: t.Dict[str, t.Any],
    trigger: taac_types.SystemRebootTrigger,
) -> t.List[Stage]:
    """Trigger stages that validate a speed flip across a system reboot.

    Reboots the device (microserver-only or full BMC power reset), then
    undrains it (a reboot leaves the device drained), waits for agent
    convergence, settles, and validates the flipped ports are at the target
    speed. Used as a ``trigger_stage_builder`` override on SpeedFlipPlaybook in
    place of the default agent-restart-based ``service_event_stages``.
    """
    return [
        create_steps_stage(
            steps=[
                create_system_reboot_step(trigger=trigger),
                # A reboot leaves the device drained; undrain before validating.
                create_drain_undrain_step(drain=False),
                create_service_convergence_step(
                    services=[taac_types.Service.AGENT],
                ),
                # Settle: convergence can complete before traffic fully restores.
                create_longevity_step(duration=300),
                get_validation_step(health_check_params),
            ]
        ),
    ]


def microserver_reboot_undrain_stages(
    health_check_params: t.Dict[str, t.Any],
) -> t.List[Stage]:
    """Microserver-only reboot (wedge_power.sh reset -s) + undrain + validate."""
    return _reboot_undrain_stages(
        health_check_params,
        taac_types.SystemRebootTrigger.BMC_MICROSERVER_ONLY_RESET,
    )


def bmc_reboot_undrain_stages(
    health_check_params: t.Dict[str, t.Any],
) -> t.List[Stage]:
    """Full BMC power reset (wedge_power.sh reset) + undrain + validate."""
    return _reboot_undrain_stages(
        health_check_params,
        taac_types.SystemRebootTrigger.BMC_POWER_RESET,
    )


@dataclass
class Circuit:
    """One physical link (subport) exercised by a speed-flip test.

    ``a_end`` is the DUT side (where patchers, reboots and admin-down run);
    ``z_end`` is the peer side of the same link. Both ends flip together, since a
    link's two ends must run at the same speed. A "cage" is the interface minus
    its trailing subport (``eth1/17/1`` and ``eth1/17/5`` -> cage ``eth1/17``);
    subport ``/1`` is the primary (goes to the target speed, subsuming its mate)
    and ``/5`` is the subsumable subport.
    """

    a_end_device_name: str
    a_end_interface_name: str
    z_end_device_name: str
    z_end_interface_name: str


def _cage_base(interface_name: str) -> str:
    """Cage base = interface minus trailing subport (eth1/17/1 -> eth1/17)."""
    return interface_name.rsplit("/", 1)[0]


def _subport(interface_name: str) -> str:
    """Trailing subport id (eth1/17/1 -> '1')."""
    return interface_name.rsplit("/", 1)[1]


def _speed_flip_hc_params(
    ports_by_device: t.Dict[str, t.List[str]], expected_speed_gbps: int
) -> t.Dict[str, t.Any]:
    """Build health_check_params validating each given port at a speed."""
    return {
        device: {
            "interfaces": [
                {"interface_name": port, "expected_speed": expected_speed_gbps}
                for port in ports
            ]
        }
        for device, ports in ports_by_device.items()
    }


def _circuit_endpoints(circuits: t.List[Circuit]) -> t.Dict[str, t.List[str]]:
    """Collapse circuits into an {device: [interfaces]} map covering BOTH ends."""
    endpoints: t.Dict[str, t.List[str]] = {}
    for circuit in circuits:
        endpoints.setdefault(circuit.a_end_device_name, []).append(
            circuit.a_end_interface_name
        )
        endpoints.setdefault(circuit.z_end_device_name, []).append(
            circuit.z_end_interface_name
        )
    return endpoints


def build_speed_flip_subsume_churn_playbook(
    playbook_name: str,
    circuit_info: t.List[Circuit],
    baseline_speed_gbps: int = 400,
    target_speed_gbps: int = 800,
    churn_iterations: int = 1,
) -> Playbook:
    """SPD_041: multi-patcher 400G<->800G subsume churn on 51T.

    ``circuit_info`` must contain exactly 6 circuits = 3 dual cages x 2 subports.
    Per cage, subport ``/1`` is the primary (-> target_speed_gbps, subsumes its
    mate) and ``/5`` is the subsumable subport. Cages are ordered by a_end cage
    base -> the spec's A-F: A=cage_1 /1, B=cage_1 /5, C=cage_2 /1, D=cage_2 /5,
    E=cage_3 /1, F=cage_3 /5. Both a_end (DUT) and z_end (peer) ends flip.

    Two named patchers overlap on C,D,E,F:
    - churn_patcher_1 = all 3 cages (A-F)
    - churn_patcher_2 = cages 2 & 3 (C,D,E,F)

    Sequence (each register/unregister step warmboots the agent):
      0. Precheck: assert all 6 circuits (both ends) at baseline_speed_gbps (400G).
      1. Register churn_patcher_1 (A-F -> 800G). B,D up initially, subsumed by the
         flip. Validate primaries at 800G.
      2. Force F (cage_3 /5) admin-down on the DUT, then register churn_patcher_2
         (C,D,E,F -> 800G). Validate primaries at 800G.
      3. Churn x churn_iterations: remove p1, remove p2, reapply p1, reapply p2,
         remove p2 (each +warmboot, each followed by a primary-speed validation).

    Asserts: exactly 6 circuits; exactly 3 distinct a_end cages; exactly 3
    distinct z_end cages. The all-at-400G check is enforced at runtime (step 0).

    NOTE (review): create_fpf_set_interface_admin_step downs F on the DUT (a_end)
    only; the z_end side of F is not admin-downed by this builder.
    """
    if len(circuit_info) != 6:
        raise ValueError(
            f"SPD_041 subsume churn requires exactly 6 circuits "
            f"(3 dual cages x 2 subports); got {len(circuit_info)}."
        )
    a_cages = {_cage_base(c.a_end_interface_name) for c in circuit_info}
    z_cages = {_cage_base(c.z_end_interface_name) for c in circuit_info}
    if len(a_cages) != 3:
        raise ValueError(
            f"SPD_041 requires exactly 3 a_end cages; got {len(a_cages)}: "
            f"{sorted(a_cages)}."
        )
    if len(z_cages) != 3:
        raise ValueError(
            f"SPD_041 requires exactly 3 z_end cages; got {len(z_cages)}: "
            f"{sorted(z_cages)}."
        )

    patcher1_name = "churn_patcher_1"
    patcher2_name = "churn_patcher_2"

    # Order cages deterministically by a_end cage base -> cage_1, cage_2, cage_3.
    cages_by_base: t.Dict[str, t.List[Circuit]] = {}
    for circuit in circuit_info:
        cages_by_base.setdefault(_cage_base(circuit.a_end_interface_name), []).append(
            circuit
        )
    ordered_cages = [cages_by_base[base] for base in sorted(cages_by_base)]

    patcher1_circuits = circuit_info  # A-F
    patcher2_circuits = ordered_cages[1] + ordered_cages[2]  # cages 2 & 3
    primary_circuits = [
        c for c in circuit_info if _subport(c.a_end_interface_name) == "1"
    ]
    # F = subsumable (/5) subport of cage_3, DUT (a_end) side.
    f_circuit = next(
        c for c in ordered_cages[2] if _subport(c.a_end_interface_name) == "5"
    )

    primary_hc = _speed_flip_hc_params(
        _circuit_endpoints(primary_circuits), target_speed_gbps
    )

    def _patcher_step(
        patcher_name: str, circuits: t.List[Circuit], register: bool
    ) -> Stage:
        # target_port_cage_count = number of a_end cages this patcher covers, so
        # the runtime cage gate passes for this intentionally-3/2-cage test.
        cage_count = len({_cage_base(c.a_end_interface_name) for c in circuits})
        return create_steps_stage(
            steps=[
                create_register_speed_flip_patcher_step(
                    register_patcher=register,
                    port_state_change=False,  # B,D up initially; F handled below
                    patcher_name=patcher_name,
                    endpoints=_circuit_endpoints(circuits),
                    speed_in_gbps=target_speed_gbps,
                    target_port_cage_count=cage_count,
                ),
                get_validation_step(primary_hc),
            ]
        )

    stages: t.List[Stage] = []

    # 0. Precheck: all 6 circuits (both ends) at baseline (400G).
    stages.append(
        create_steps_stage(
            steps=[
                get_validation_step(
                    _speed_flip_hc_params(
                        _circuit_endpoints(circuit_info), baseline_speed_gbps
                    )
                )
            ]
        )
    )

    # 1. churn_patcher_1 (A-F) -> 800G; B,D subsumed (were up).
    stages.append(_patcher_step(patcher1_name, patcher1_circuits, register=True))

    # 2. Force F down (DUT a_end), then churn_patcher_2 (C,D,E,F) -> 800G.
    stages.append(
        create_steps_stage(
            steps=[
                create_fpf_set_interface_admin_step(
                    interfaces=[f_circuit.a_end_interface_name], enable=False
                ),
            ]
        )
    )
    stages.append(_patcher_step(patcher2_name, patcher2_circuits, register=True))

    # 3. Churn: remove p1, remove p2, reapply p1, reapply p2, remove p2.
    for _ in range(churn_iterations):
        stages.append(_patcher_step(patcher1_name, patcher1_circuits, register=False))
        stages.append(_patcher_step(patcher2_name, patcher2_circuits, register=False))
        stages.append(_patcher_step(patcher1_name, patcher1_circuits, register=True))
        stages.append(_patcher_step(patcher2_name, patcher2_circuits, register=True))
        stages.append(_patcher_step(patcher2_name, patcher2_circuits, register=False))

    return create_speed_flip_playbook(
        name=playbook_name,
        stages=stages,
        iteration=1,
    )


def build_subsume_churn_test_config(
    test_config_name: str,
    playbook_name: str,
    circuit_info: t.List[Circuit],
    churn_iterations: int = 1,
) -> TestConfig:
    """Wrap the SPD_041 subsume-churn playbook into a runnable TestConfig."""
    churn_playbook = build_speed_flip_subsume_churn_playbook(
        playbook_name=playbook_name,
        circuit_info=circuit_info,
        churn_iterations=churn_iterations,
    )
    endpoints = _circuit_endpoints(circuit_info)
    dut_device = circuit_info[0].a_end_device_name
    snapshot_checks = [
        create_port_speed_snapshot_check(
            json_params={"endpoints": endpoints},
            pre_snapshot_checkpoint_id="test_case_start",
            post_snapshot_checkpoint_id="test_case_end",
        ),
    ]
    wrapped = create_speed_flip_test_config_playbook(
        built_playbook=churn_playbook,
        snapshot_checks=snapshot_checks,
    )
    return TestConfig(
        name=test_config_name,
        basset_pool="dne.test",
        endpoints=[
            Endpoint(name=device, dut=(device == dut_device)) for device in endpoints
        ],
        playbooks=[wrapped],
    )


@dataclass
class SpeedTransitionStage:
    """
    Represents a single stage in a speed flip scenario.

    Each stage defines:
    - endpoints (hostname -> ports mapping) to change
    - speed to change them to
    - patcher name
    - boolean for change port state to DOWN
    - target_port_cage_count: minimum dual-cage ports required per device
    """

    endpoints: t.Dict[str, t.List[str]]
    speed_in_gbps: int
    patcher_name: str
    port_state_change: bool = False
    # Minimum number of distinct dual-cage ports each device in `endpoints` must
    # supply. Enforced at test runtime by RegisterSpeedFlipPatcherStep — the onus
    # is on the POC configuring/running the test to provide at least this many
    # cages per device (spec calls for 4). NOTE: the existing configs below still
    # supply 1 cage and will fail this runtime gate until expanded to 4.
    target_port_cage_count: int = 4

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
    # Optional override for the playbook's "trigger" phase (Phase 2). When None,
    # the default agent-restart-based `service_event_stages` (warmboot + coldboot
    # + agent-crash + coop-crash) is used. Set to e.g.
    # `microserver_reboot_undrain_stages` / `bmc_reboot_undrain_stages` to instead
    # validate the flip across a system reboot (reboot + undrain + validate).
    trigger_stage_builder: t.Optional[
        t.Callable[[t.Dict[str, t.Any]], t.List[Stage]]
    ] = None

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
                target_port_cage_count=transition_stage.target_port_cage_count,
            )

            taac_stage = create_steps_stage(steps=[step])
            taac_stages.append(taac_stage)

        """
        PHASE 2: SERVICE EVENT STAGES
        """
        trigger_builder = self.trigger_stage_builder or service_event_stages
        taac_stages.extend(trigger_builder(self.health_check_params))

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
                target_port_cage_count=transition_stage.target_port_cage_count,
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
                number_of_iterations=10,
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
                number_of_iterations=10,
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
                number_of_iterations=10,
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
                number_of_iterations=10,
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
                number_of_iterations=10,
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
                number_of_iterations=10,
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
                number_of_iterations=10,
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
                number_of_iterations=10,
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
                number_of_iterations=10,
            ),
            # 100G to 200G, validated across a microserver reboot (+ undrain)
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
                            {"interface_name": "eth1/17/1", "expected_speed": 200},
                            {"interface_name": "eth1/17/5", "expected_speed": 200},
                        ]
                    },
                    "rsw001.p001.m001.qzr1": {
                        "interfaces": [
                            {"interface_name": "eth1/33/1", "expected_speed": 200},
                            {"interface_name": "eth1/33/5", "expected_speed": 200},
                        ]
                    },
                },
                playbook_name="SPEED_FLIP_51T_TEST_PORTS_DOWN_100G_TO_200G_MICROSERVER_REBOOT_PLAYBOOK",
                number_of_iterations=10,
                trigger_stage_builder=microserver_reboot_undrain_stages,
            ),
            # 100G to 200G, validated across a full BMC power reset (+ undrain)
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
                            {"interface_name": "eth1/17/1", "expected_speed": 200},
                            {"interface_name": "eth1/17/5", "expected_speed": 200},
                        ]
                    },
                    "rsw001.p001.m001.qzr1": {
                        "interfaces": [
                            {"interface_name": "eth1/33/1", "expected_speed": 200},
                            {"interface_name": "eth1/33/5", "expected_speed": 200},
                        ]
                    },
                },
                playbook_name="SPEED_FLIP_51T_TEST_PORTS_DOWN_100G_TO_200G_BMC_REBOOT_PLAYBOOK",
                number_of_iterations=10,
                trigger_stage_builder=bmc_reboot_undrain_stages,
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
                number_of_iterations=10,
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
                number_of_iterations=10,
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
                number_of_iterations=10,
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
                number_of_iterations=10,
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
                number_of_iterations=10,
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
                number_of_iterations=10,
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
                number_of_iterations=10,
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
                number_of_iterations=10,
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
                number_of_iterations=10,
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
                number_of_iterations=10,
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
                number_of_iterations=10,
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
                number_of_iterations=10,
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
                number_of_iterations=10,
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
                number_of_iterations=10,
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
                number_of_iterations=10,
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
                number_of_iterations=10,
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
                number_of_iterations=10,
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
                number_of_iterations=10,
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
                number_of_iterations=10,
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
                number_of_iterations=10,
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
                number_of_iterations=10,
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
                number_of_iterations=10,
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
                number_of_iterations=10,
            ),
        ],
    ).build_test_config(),
    # SPD_041: multi-patcher 400G<->800G subsume churn on 51T (fsw003 DUT).
    # 3 dual cages x 2 subports = 6 circuits, all provisioned at 400G, all to
    # peer rsw001. cage_1=eth1/17, cage_2=eth1/21, cage_3=eth1/22 (a_end).
    build_subsume_churn_test_config(
        test_config_name="SPEED_FLIP_51T_SUBSUME_CHURN",
        playbook_name="SPEED_FLIP_51T_SUBSUME_CHURN_PLAYBOOK",
        circuit_info=[
            Circuit(
                a_end_device_name="fsw003.p001.m001.qzr1",
                a_end_interface_name="eth1/17/1",
                z_end_device_name="rsw001.p001.m001.qzr1",
                z_end_interface_name="eth1/1/1",
            ),
            Circuit(
                a_end_device_name="fsw003.p001.m001.qzr1",
                a_end_interface_name="eth1/17/5",
                z_end_device_name="rsw001.p001.m001.qzr1",
                z_end_interface_name="eth1/1/5",
            ),
            Circuit(
                a_end_device_name="fsw003.p001.m001.qzr1",
                a_end_interface_name="eth1/21/1",
                z_end_device_name="rsw001.p001.m001.qzr1",
                z_end_interface_name="eth1/2/1",
            ),
            Circuit(
                a_end_device_name="fsw003.p001.m001.qzr1",
                a_end_interface_name="eth1/21/5",
                z_end_device_name="rsw001.p001.m001.qzr1",
                z_end_interface_name="eth1/2/5",
            ),
            Circuit(
                a_end_device_name="fsw003.p001.m001.qzr1",
                a_end_interface_name="eth1/22/1",
                z_end_device_name="rsw001.p001.m001.qzr1",
                z_end_interface_name="eth1/3/1",
            ),
            Circuit(
                a_end_device_name="fsw003.p001.m001.qzr1",
                a_end_interface_name="eth1/22/5",
                z_end_device_name="rsw001.p001.m001.qzr1",
                z_end_interface_name="eth1/3/5",
            ),
        ],
        churn_iterations=10,
    ),
]
