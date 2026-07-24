"""2-DUT smoke test that discovers topology from circuit_info CSV.

Exercises SSH, port state, port speed, and agent warmboot across two
directly-connected DUTs. Device names and ports are discovered from
the ConfigTopology built by the entry point from --circuit-info-csv.

Playbooks:
  1. ssh_check        — run `uname -a` on both DUTs
  2. port_state_check — verify connected ports are operationally UP
  3. port_speed_check — verify connected ports are at 800G
  4. agent_warmboot   — restart agent on first DUT, wait for convergence,
                        re-verify ports UP on both DUTs
"""

import json

from taac.runner.testbed_topology import ConfigTopology, topology_aware
from taac.steps.step_definitions import (
    create_service_convergence_step,
    create_service_interruption_step,
    create_verify_port_operational_state_step,
    create_verify_port_speed_step_v2,
)
from taac.test_as_a_config.thrift_types import (
    Endpoint,
    Params,
    Playbook,
    Service,
    ServiceInterruptionTrigger,
    Stage,
    Step,
    StepName,
    TestConfig,
)


def _per_dut_port_state_steps(dut_ports, operational_state=True):
    steps = []
    for dut, ports in sorted(dut_ports.items()):
        step = create_verify_port_operational_state_step(
            interfaces=ports,
            operational_state=operational_state,
        )
        step = Step(
            name=step.name,
            step_params=step.step_params,
            device_regexes=[dut],
        )
        steps.append(step)
    return steps


def _per_dut_port_speed_steps(dut_ports, speed):
    steps = []
    for dut, ports in sorted(dut_ports.items()):
        step = create_verify_port_speed_step_v2(
            ports=ports,
            speed_to_verify=speed,
        )
        step = Step(
            name=step.name,
            step_params=step.step_params,
            device_regexes=[dut],
        )
        steps.append(step)
    return steps


@topology_aware
def test_config(topology: ConfigTopology) -> TestConfig:
    dut_ports = topology.dut_ports
    duts = sorted(dut_ports.keys())
    if len(duts) < 2:
        raise RuntimeError(
            f"Expected at least 2 DUTs in circuit CSV, found {len(duts)}: {duts}"
        )

    return TestConfig(
        name="multidut_smoke",
        basset_pool="",
        playbooks=[
            Playbook(
                name="ssh_check",
                stages=[
                    Stage(
                        steps=[
                            Step(
                                name=StepName.RUN_SSH_COMMAND_STEP,
                                step_params=Params(
                                    json_params=json.dumps(
                                        {"cmd": "uname -a", "log_output": True}
                                    )
                                ),
                            ),
                        ],
                    ),
                ],
            ),
            Playbook(
                name="port_state_check",
                stages=[
                    Stage(steps=_per_dut_port_state_steps(dut_ports)),
                ],
            ),
            Playbook(
                name="port_speed_check",
                stages=[
                    Stage(steps=_per_dut_port_speed_steps(dut_ports, speed=800)),
                ],
            ),
            Playbook(
                name="agent_warmboot",
                stages=[
                    Stage(
                        steps=[
                            create_service_interruption_step(
                                service=Service.FBOSS_SW_AGENT,
                                trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                                device_regexes=[duts[0]],
                            ),
                            create_service_convergence_step(
                                services=[Service.FBOSS_SW_AGENT],
                                device_regexes=[duts[0]],
                            ),
                            *_per_dut_port_state_steps(dut_ports),
                        ],
                    ),
                ],
            ),
        ],
        endpoints=[Endpoint(name=dut, dut=True) for dut in duts],
        host_os_type_map={},
        startup_checks=[],
    )
