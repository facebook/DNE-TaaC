# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""RBB SRv6 encap/decap counter-delta task (gate S25).

Proves the data plane actually SRv6-encapsulated (R1) and decapsulated (R2) the
traffic that crossed the core, by asserting a real INCREASE in the relevant
counter across a traffic window — not just that a counter exists.

Two-phase, keyed by ``hostname:direction`` in the task's shared-data namespace
so a snapshot taken before traffic and an assert taken after traffic compare the
same counter on the same box:

* ``action="snapshot"`` — read the counter, store the baseline value.
* ``action="assert"``   — read the counter again, compute ``now - baseline`` and
  raise ``TestCaseFailure`` (a FAIL verdict) when the delta is below
  ``min_delta`` (default 1), i.e. no encap/decap happened.

The exact counter CLI + the integer-extraction regex are scenario-supplied
(``counter_cmd`` / ``counter_regex``; see ``bgp_rbb_scenario_profiles``) so the
device syntax lives with the scenario (§5.4) and the task stays generic. This is
a registered Task (not a new ``CheckName``) for the same schema-stability reason
as ``rbb_srv6_verify`` — no Thrift edit, no ``all_health_checks`` change.
"""

import re
import typing as t

from taac.constants import TestCaseFailure
from taac.tasks.base_task import BaseTask
from taac.utils.driver_factory import async_get_device_driver
from taac.utils.oss_taac_lib_utils import ConsoleFileLogger

_SNAPSHOT = "snapshot"
_ASSERT = "assert"

# Process-local baseline cache keyed by ``hostname:direction``. The RUN_TASK_STEP
# runner constructs a fresh task instance per step and does NOT thread the
# playbook ``shared_data`` through ``run_task`` (see steps.RunTaskStep), so the
# per-instance ``self._data`` from one step is invisible to the next. The
# snapshot and assert steps run sequentially (blocking, awaited) in the same
# playbook process, so a module-level dict reliably carries the baseline between
# them regardless of the shared-data plumbing.
_BASELINE_CACHE: t.Dict[str, int] = {}


class RbbSrv6CounterDeltaTask(BaseTask):
    """Snapshot/assert an SRv6 encap or decap counter delta on one DUT."""

    # pyre-ignore[15]
    NAME: str = "rbb_srv6_counter_delta"

    def __init__(
        self,
        hostname: t.Optional[str] = None,
        description: t.Optional[str] = None,
        ixia: t.Optional[t.Any] = None,
        logger: t.Optional[ConsoleFileLogger] = None,
        shared_data: t.Optional[t.Dict[t.Any, t.Any]] = None,
    ) -> None:
        super().__init__(hostname, description, ixia, logger, shared_data)

    def _extract(self, output: str, regex: str) -> int:
        """Sum every integer captured by ``regex`` in ``output`` (0 if none)."""
        total = 0
        found = False
        for m in re.finditer(regex, output):
            try:
                total += int(m.group(1))
                found = True
            except (IndexError, ValueError):
                continue
        return total if found else 0

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        """Snapshot or assert an SRv6 counter delta.

        params:
            hostname: DUT to query (required).
            action: "snapshot" or "assert" (required).
            counter_cmd: shell command whose stdout carries the counter (required).
            counter_regex: regex with one integer capture group (required).
            direction: "encap" / "decap" label for the shared-data key + logs.
            min_delta: minimum required increase for "assert" (default 1).
            gate: human-readable gate label (optional).
        """
        hostname = params.get("hostname") or self.hostname
        if not hostname:
            raise ValueError("rbb_srv6_counter_delta requires 'hostname'")
        action = params.get("action")
        if action not in (_SNAPSHOT, _ASSERT):
            raise ValueError(
                f"rbb_srv6_counter_delta 'action' must be {_SNAPSHOT!r} or "
                f"{_ASSERT!r}, got {action!r}"
            )
        counter_cmd = params.get("counter_cmd")
        if not counter_cmd:
            raise ValueError("rbb_srv6_counter_delta requires 'counter_cmd'")
        counter_regex = params.get("counter_regex")
        if not counter_regex:
            raise ValueError("rbb_srv6_counter_delta requires 'counter_regex'")
        direction = params.get("direction", "srv6")
        gate = params.get("gate", "rbb_srv6_counter_delta")
        key = f"{hostname}:{direction}"

        driver = await async_get_device_driver(hostname)
        output = await driver.async_run_cmd_on_shell(counter_cmd) or ""
        value = self._extract(output, counter_regex)

        if action == _SNAPSHOT:
            _BASELINE_CACHE[key] = value
            # Also mirror into the task shared-data view for parity when present.
            self._data[key] = value
            self.logger.info(
                f"{hostname} -- [{gate}] {direction} counter baseline={value}"
            )
            return

        min_delta = int(params.get("min_delta", 1))
        if key in _BASELINE_CACHE:
            baseline = _BASELINE_CACHE[key]
        elif key in self._data:
            baseline = self._data[key]
        else:
            baseline = None
        if baseline is None:
            raise TestCaseFailure(
                f"[{gate}] no {direction} baseline recorded on {hostname} "
                f"(snapshot step must run before assert)"
            )
        delta = value - baseline
        self.logger.info(
            f"{hostname} -- [{gate}] {direction} counter now={value} "
            f"baseline={baseline} delta={delta} (min={min_delta})"
        )
        if delta < min_delta:
            raise TestCaseFailure(
                f"[{gate}] SRv6 {direction} counter delta on {hostname} was "
                f"{delta} (< required {min_delta}); expected traffic to "
                f"{direction} across the core"
            )
