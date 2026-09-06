# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""RBB SRv6-path counter-delta task (gate S25).

Asserts a real counter INCREASE across the traffic window, rather than merely
checking that a counter exists. The portable defaults measure the selected
core-egress and tail-edge path. Platforms with per-SRv6-object counters should
provide those through the documented command/regex overrides for strict
encapsulation/decapsulation evidence.

Two-phase, keyed by ``hostname:direction`` in the task's shared-data namespace
so a snapshot taken before traffic and an assert taken after traffic compare the
same counter on the same box:

* ``action="snapshot"`` — read the counter, store the baseline value.
* ``action="assert"``   — read the counter again, compute ``now - baseline`` and
  raise ``TestCaseFailure`` (a FAIL verdict) when the delta is below
  ``min_delta`` (default 1), i.e. no traffic crossed the selected measured
  path. With platform-specific SRv6-object overrides, the same result is strict
  encap/decap evidence.

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


class RbbSrv6CounterDeltaTask(BaseTask):
    """Snapshot/assert a selected path or SRv6-object counter on one DUT."""

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

    def _extract(self, output: str, regex: str) -> t.Optional[int]:
        """Sum every captured integer, or return ``None`` when none matched."""
        total = 0
        found = False
        for m in re.finditer(regex, output):
            try:
                total += int(m.group(1))
                found = True
            except (IndexError, ValueError):
                continue
        return total if found else None

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
        min_delta = int(params.get("min_delta", 1))
        if action == _ASSERT and min_delta < 1:
            raise ValueError(
                "rbb_srv6_counter_delta 'min_delta' must be at least 1 for "
                f"an assert action, got {min_delta}"
            )

        driver = await async_get_device_driver(hostname)
        output = await driver.async_run_cmd_on_shell(counter_cmd) or ""
        value = self._extract(output, counter_regex)
        if value is None:
            raise TestCaseFailure(
                f"[{gate}] counter regex did not match output on {hostname}: "
                f"{counter_regex!r}"
            )

        if action == _SNAPSHOT:
            self._data[key] = value
            self.logger.info(
                f"{hostname} -- [{gate}] {direction} counter baseline={value}"
            )
            return

        if key in self._data:
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
                f"[{gate}] selected {direction}-path counter delta on {hostname} was "
                f"{delta} (< required {min_delta}); expected traffic to "
                f"{direction} across the core"
            )
