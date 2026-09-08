# Copyright (c) Meta Platforms, Inc. and affiliates.
"""FBOSS SW-agent restart test.

Verifies that a FBOSS switch recovers cleanly after its software agent
(`fboss_sw_agent`) is restarted via `systemctl restart`:

  1. baseline_port_check — assert the monitored ports are UP before restart
  2. agent_restart       — restart agent on AGENT_RESTART_DUT, wait for
                           convergence, re-verify port state

Topology: a single FBOSS DUT with at least one operationally-UP port
(the defaults monitor the TGEN-facing ports).

DUT prerequisite: `fboss_sw_agent` running and the monitored ports UP.

Device targeting: all device-specific values (hostname, monitored ports,
which DUT gets restarted) live in examples/testbed_constants.py — edit that
file to target a real testbed. The topology CSVs passed to the runner must
describe the same wiring.

Run (inside fboss-taac image):

    python -m taac.runner.oss_entry_point \
        --test-configs examples/agent_restart_test.py \
        --device-info-csv examples/topology/single_switch/device_info.csv \
        --circuit-info-csv examples/topology/single_switch/circuit_info.csv \
        --dut switch01.example.com \
        --skip-ixia-setup \
        --skip-post-setup-wait
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import testbed_constants as tb

from taac.health_checks.constants import (
    DEFAULT_SERVICE_NAMES,
    SERVICES_TO_MONITOR_DURING_AGENT_RESTART,
)
from taac.health_checks.healthcheck_definitions import (
    create_memory_utilization_check,
    create_service_restart_check,
    create_systemctl_active_state_check,
    create_unclean_exit_check,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_service_convergence_step,
    create_service_interruption_step,
    create_verify_port_operational_state_step,
)
from taac.test_as_a_config.thrift_types import (
    Endpoint,
    Playbook,
    Service,
    ServiceInterruptionTrigger,
    TestConfig,
)


def _port_state_steps(dut_ports):
    """One VERIFY_PORT_OPERATIONAL_STATE step per DUT, scoped by device_regexes."""
    return [
        create_verify_port_operational_state_step(
            interfaces=ports,
            operational_state=True,
            device_regexes=[dut],
        )
        for dut, ports in sorted(dut_ports.items())
    ]


TEST_CONFIG = TestConfig(
    name="agent_restart",
    basset_pool="",
    playbooks=[
        Playbook(
            name="baseline_port_check",
            stages=[create_steps_stage(steps=_port_state_steps(tb.MONITORED_PORTS))],
        ),
        Playbook(
            name="agent_restart",
            stages=[
                create_steps_stage(
                    steps=[
                        create_service_interruption_step(
                            service=Service.FBOSS_SW_AGENT,
                            trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                            device_regexes=[tb.AGENT_RESTART_DUT],
                        ),
                        create_service_convergence_step(
                            services=[Service.FBOSS_SW_AGENT],
                            device_regexes=[tb.AGENT_RESTART_DUT],
                        ),
                        # Re-verify port state after the agent comes back.
                        *_port_state_steps(tb.MONITORED_PORTS),
                    ]
                )
            ],
            # OSS collector-backed postchecks. The restart cascade
            # (AGENT_RESTART_EXPECTED_RESTARTS) is allowed to bounce; every
            # other monitored service must have stayed active the whole
            # window, and nothing may have exited uncleanly (systemctl
            # restart is a clean stop, so the restarted services pass too).
            postchecks=[
                create_service_restart_check(
                    services=SERVICES_TO_MONITOR_DURING_AGENT_RESTART,
                    expected_restarted_services=tb.AGENT_RESTART_EXPECTED_RESTARTS,
                ),
                create_systemctl_active_state_check(
                    services_json=DEFAULT_SERVICE_NAMES,
                    expected_restarted_services=tb.AGENT_RESTART_EXPECTED_RESTARTS,
                ),
                create_unclean_exit_check(),
                create_memory_utilization_check(),
            ],
        ),
    ],
    endpoints=[Endpoint(name=dut, dut=True) for dut in sorted(tb.MONITORED_PORTS)],
    host_os_type_map={},
    startup_checks=[],
)
