# Copyright (c) Meta Platforms, Inc. and affiliates.
"""Simple connectivity test — SSH reachability and port operational-state check.

Tests the most basic health of a TAAC-managed testbed:
  1. ssh_check        — runs `hostname` on every DUT via SSH
  2. port_state_check — verifies the monitored ports are operationally UP,
     then holds for 30 s (watching for port flaps) so the OSS collectors
     gather enough samples for real CPU/memory verdicts

No service restarts, no traffic, no TGEN required. Postchecks exercise the
OSS collector-backed health checks (CPU / memory / systemd-state collectors
are started automatically for every OSS run by CollectorsTestHandler).

Device targeting: all device-specific values (hostname, monitored ports)
live in examples/testbed_constants.py — edit that file to target a real
testbed. The topology CSVs passed to the runner must describe the same
wiring.

Run (inside fboss-taac image):

    python -m taac.runner.oss_entry_point \
        --test-configs examples/simple_connectivity_test.py \
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

from taac.health_checks.constants import DEFAULT_SERVICE_NAMES
from taac.health_checks.healthcheck_definitions import (
    create_cpu_utilization_check,
    create_memory_utilization_check,
    create_systemctl_active_state_check,
    create_unclean_exit_check,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_longevity_step,
    create_run_ssh_command_step,
    create_verify_port_operational_state_step,
)
from taac.test_as_a_config.thrift_types import Endpoint, Playbook, TestConfig


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
    name="simple_connectivity",
    basset_pool="",
    playbooks=[
        Playbook(
            name="ssh_check",
            stages=[
                create_steps_stage(
                    steps=[
                        create_run_ssh_command_step(
                            cmd="hostname",
                            log_output=True,
                            description="SSH reachability: run `hostname` on the DUT",
                        )
                    ]
                )
            ],
        ),
        Playbook(
            name="port_state_check",
            stages=[
                create_steps_stage(
                    steps=[
                        *_port_state_steps(tb.MONITORED_PORTS),
                        # Hold long enough for the OSS collectors (5 s poll
                        # interval) to gather real CPU/memory samples — the
                        # utilization postchecks would SKIP on an empty
                        # window. Port state is polled during the hold, so a
                        # spontaneous flap fails the step.
                        create_longevity_step(
                            duration=tb.CONNECTIVITY_HOLD_SEC,
                            collect_port_state=True,
                            description="Collector observation window",
                        ),
                    ]
                )
            ],
            # OSS collector-backed baseline health: services stayed active,
            # no unclean exits, CPU/memory within thresholds over the hold
            # window. Scope the systemd check to the collector's own service
            # list so it never asks about units the collector doesn't
            # monitor.
            postchecks=[
                create_systemctl_active_state_check(
                    services_json=DEFAULT_SERVICE_NAMES
                ),
                create_unclean_exit_check(),
                create_cpu_utilization_check(),
                create_memory_utilization_check(),
            ],
        ),
    ],
    endpoints=[Endpoint(name=dut, dut=True) for dut in sorted(tb.MONITORED_PORTS)],
    host_os_type_map={},
    startup_checks=[],
)
