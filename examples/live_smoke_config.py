"""TestConfig for the OSS live-device smoke.

A minimal TAAC test configuration that the OSS entry point can load,
as a working example of a test-config file passed via `--test-configs`.

Three playbooks:
  - dummy_playbook:  a DUMMY_STEP, exercises the runner's plumbing.
  - ssh_playbook:    a RUN_SSH_COMMAND_STEP that runs `uname -a` on each
                     DUT, exercising the SSH driver path.
  - collector_playbook: idles ~20s and then runs the CPU + memory
                     postchecks, exercising the continuous-polling
                     collectors end to end. See the note below.

NOTE ON --dry-run: the entry point returns right after loading and
filtering playbooks, so a dry run validates only that this file imports
and that its checks are constructible. It does NOT start collectors,
resolve check params, or contact a DUT — collector_playbook's checks are
inert there. Drop --dry-run and point --dut at a real FBOSS device to
actually exercise them.

DUTs are supplied at run time via the entry point's `--dut` flag — this
file leaves `endpoints` empty. Per-host OS resolution is driven by the
OSS topology loader from TAAC_DEVICE_INFO_PATH (a device_info.csv),
which the entry point's `--device-info-csv` flag wires in.

Canonical invocation from a checkout root (inside the `fboss-taac`
image, bind-mounted at /taac):

    python -m taac.runner.oss_entry_point \\
        --test-configs examples/live_smoke_config.py \\
        --device-info-csv examples/topology/sample_device_info.csv \\
        --circuit-info-csv examples/topology/sample_circuit_info.csv \\
        --dut <hostname> [<hostname> ...] \\
        --skip-post-setup-wait
"""

import json

from taac.constants import Gigabyte
from taac.health_checks.healthcheck_definitions import (
    create_cpu_utilization_check,
    create_memory_utilization_check,
)
from taac.test_as_a_config.thrift_types import (
    Params,
    Playbook,
    Stage,
    Step,
    StepName,
    TestConfig,
)


# The collectors poll every DEFAULT_POLL_INTERVAL_SEC (5s), and CPU's first
# poll is always None — a delta needs a previous sample. So the window has to
# span at least two polls or the checks correctly SKIP with "no measurable
# samples", which validates nothing. Idle long enough for a few.
_COLLECTOR_SETTLE_SEC = 20

# --- Knobs for validating the collector path against a live DUT -------------
# Memory is the easier of the two to validate: MemoryCurrent is an absolute
# gauge (so the very first poll yields a real number, where CPU needs two for
# a delta) and it isn't averaged over the poll interval, so all three verdicts
# are reachable by changing _MEM_THRESHOLD_BYTES alone — no load generation,
# no cgroup surgery:
#
#   Gigabyte.GIG_8.value  -> PASS, with a populated per-service table
#   1                     -> FAIL, every real MemoryCurrent exceeds 1 byte
#                            (NOT 0: the check reads 0 as "no global check")
#   ...and setting _COLLECTOR_SETTLE_SEC = 2 instead -> SKIP, empty window
#
# Do NOT validate by allocating real gigabytes into a live unit's cgroup — if
# that cgroup has a MemoryMax you will get the unit OOM-killed.
_MEM_THRESHOLD_BYTES = Gigabyte.GIG_5.value

# CPU rides along as an observer. It is core-summed percent averaged over the
# 5s poll interval, so 400.0 needs four cores pegged for a full interval; a
# daemon restart burns 1-3 core-seconds and only reads as 20-60%. Tripping it
# deliberately means sustained multi-core load inside a monitored unit's
# cgroup — read /tmp/cpu_utilization_collector.*.log instead.
_CPU_THRESHOLD_PCT = 400.0

_COLLECTOR_POSTCHECKS = [
    create_cpu_utilization_check(
        threshold=_CPU_THRESHOLD_PCT,
        start_time_jq_var="test_case_start_time",
    ),
    create_memory_utilization_check(
        threshold=_MEM_THRESHOLD_BYTES,
        start_time_jq_var="test_case_start_time",
    ),
]


test_config = TestConfig(
    name="live_smoke",
    basset_pool="",  # Meta-internal hardware reservation pool; "" for OSS.
    playbooks=[
        Playbook(
            name="dummy_playbook",
            stages=[Stage(steps=[Step(name=StepName.DUMMY_STEP)])],
        ),
        Playbook(
            name="ssh_playbook",
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
                        )
                    ]
                )
            ],
        ),
        Playbook(
            name="collector_playbook",
            stages=[
                Stage(
                    steps=[
                        Step(
                            name=StepName.RUN_SSH_COMMAND_STEP,
                            step_params=Params(
                                json_params=json.dumps(
                                    {"cmd": f"sleep {_COLLECTOR_SETTLE_SEC}"}
                                )
                            ),
                        )
                    ]
                )
            ],
            postchecks=_COLLECTOR_POSTCHECKS,
        ),
    ],
    endpoints=[],  # Populated at run time from oss_entry_point --dut.
    host_os_type_map={},  # Resolved from TAAC_DEVICE_INFO_PATH.
    startup_checks=[],
)
