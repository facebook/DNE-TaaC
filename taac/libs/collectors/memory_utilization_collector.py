#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Continuous memory-utilization collector for OSS FBOSS DUTs.

Polls each monitored service's ``MemoryCurrent`` (systemd's cgroup memory
counter, in bytes) every ``interval_sec`` seconds and stores per-poll
memory-usage rows. Health checks query ``max_per_service_in_window`` to
get the peak memory each service reached across a time window — closer
parity with ODS MAX-over-window semantics than a single-sample check.

Usage (registered by a setup task, consumed by a postcheck):

    collector = MemoryUtilizationCollector(
        driver=dut_driver,
        services=["fboss_sw_agent", "fboss_hw_agent@0", "bgpd", ...],
        host=dut.name,
        interval_sec=5.0,
    )
    collector.start()
    register_collector("memory_utilization", collector)
    ...  # test runs
    max_bytes = collector.max_per_service_in_window(window_start, window_end)
    # {"fboss_sw_agent": 148_750_336, "fboss_hw_agent@0": 3_141_926_912, ...}
    ...
    await collector.stop()
"""

import logging
import os
import time
import typing as t
from dataclasses import dataclass, field

from taac.libs.collectors.service_polling_collector import ServicePollingCollector


logger = logging.getLogger(__name__)


@dataclass
class MemoryUtilizationSample:
    """One collector row — memory usage (bytes) per service at a point in time.

    ``per_service`` maps each monitored service name to its ``MemoryCurrent``
    value in bytes, or ``None`` if the service wasn't measurable at this poll
    (not loaded, inactive, no cgroup yet, or SSH error).
    """

    timestamp: str
    epoch: float
    per_service: t.Dict[str, t.Optional[int]] = field(default_factory=dict)
    notes: str = ""


class MemoryUtilizationCollector(ServicePollingCollector):
    """Polls each service's ``MemoryCurrent`` via SSH.

    Inherits SSH gather, file I/O, window queries, and the full
    ``_poll_once`` loop from ``ServicePollingCollector``. Simpler than
    ``CpuUtilizationCollector`` — ``MemoryCurrent`` is an instantaneous
    value (not a cumulative counter), so no delta computation is needed.
    """

    def __init__(
        self,
        driver: t.Any,
        services: t.Sequence[str],
        host: str,
        tmp_path: t.Optional[str] = None,
        interval_sec: float = 5.0,
    ) -> None:
        if tmp_path is None:
            tmp_path = f"/tmp/memory_utilization_collector.{os.getpid()}.{int(time.time())}.log"
        super().__init__(
            driver=driver, services=services, host=host,
            tmp_path=tmp_path, interval_sec=interval_sec,
        )
        self.rows: t.List[MemoryUtilizationSample] = []

    def _systemd_properties(self) -> t.List[str]:
        return ["LoadState", "ActiveState", "MemoryCurrent"]

    def _extract_value(
        self, unit_data: t.Dict[str, str], service: str
    ) -> t.Optional[int]:
        return self._parse_counter(unit_data.get("MemoryCurrent", ""))

    def _make_sample(
        self,
        timestamp: str,
        epoch: float,
        per_service: t.Dict[str, t.Any],
        notes: str,
    ) -> MemoryUtilizationSample:
        return MemoryUtilizationSample(
            timestamp=timestamp, epoch=epoch, per_service=per_service, notes=notes
        )

    def _write_header(self, f) -> None:
        cols = ["timestamp"] + [f"{s} (bytes)" for s in self.services] + ["notes"]
        f.write("  ".join(cols) + "\n")
