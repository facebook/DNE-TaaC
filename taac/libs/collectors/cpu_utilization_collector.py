#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Continuous CPU-utilization collector for OSS FBOSS DUTs.

Polls each monitored service's ``CPUUsageNSec`` (systemd's cumulative
CPU-time counter, in nanoseconds) every ``interval_sec`` seconds and stores
per-poll CPU% derived from the delta against the previous sample. Health
checks query ``max_per_service_in_window`` to get the maximum sustained CPU%
each service reached across a time window — closer parity with ODS
``cpu.stat.util_pct`` MAX-over-window semantics than a single two-sample
delta.

Usage (registered by a setup task, consumed by a postcheck):

    collector = CpuUtilizationCollector(
        driver=dut_driver,
        services=["fboss_sw_agent", "fboss_hw_agent@0", "bgpd", ...],
        host=dut.name,
        interval_sec=5.0,
    )
    collector.start()
    register_collector("cpu_utilization", collector)
    ...  # test runs
    max_pct = collector.max_per_service_in_window(window_start, window_end)
    # {"fboss_sw_agent": 281.07, "fboss_hw_agent@0": 446.44, ...}
    ...
    await collector.stop()
"""

import logging
import os
import time
import typing as t
from dataclasses import dataclass, field

from taac.libs.collectors.service_polling_collector import (
    ServicePollingCollector,
)


logger = logging.getLogger(__name__)


@dataclass
class CpuUtilizationSample:
    """One collector row — CPU% per service at a single point in time.

    ``per_service`` maps each monitored service name to its CPU% for the
    interval ending at ``timestamp``, computed as
    ``delta_ns / wall_delta / 1e9 * 100`` (CPU-seconds-per-wall-second, as
    percent of a single core; may exceed 100% for multi-threaded services).
    A value of ``None`` means the service wasn't measurable at this poll
    (not loaded, inactive, SSH error, or first sample with no prior baseline).
    """

    timestamp: str
    epoch: float
    per_service: t.Dict[str, t.Optional[float]] = field(default_factory=dict)
    notes: str = ""


class CpuUtilizationCollector(ServicePollingCollector):
    """Polls each service's ``CPUUsageNSec`` via SSH, records per-poll CPU%.

    Inherits the batched-SSH poll loop, file I/O, and window queries from
    ``ServicePollingCollector``; overrides ``_transform_per_service`` to turn
    the raw cumulative-ns counter into a per-interval CPU% via delta.
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
            tmp_path = (
                f"/tmp/cpu_utilization_collector.{os.getpid()}.{int(time.time())}.log"
            )
        super().__init__(
            driver=driver,
            services=services,
            host=host,
            tmp_path=tmp_path,
            interval_sec=interval_sec,
        )
        self._last_ns: t.Dict[str, t.Optional[int]] = dict.fromkeys(services)
        self._last_wall: t.Optional[float] = None
        self.rows: t.List[CpuUtilizationSample] = []

    def _systemd_properties(self) -> t.List[str]:
        return ["LoadState", "ActiveState", "CPUUsageNSec"]

    def _extract_value(
        self, unit_data: t.Dict[str, str], service: str
    ) -> t.Optional[int]:
        return self._parse_counter(unit_data.get("CPUUsageNSec", ""))

    def _format_value(self, value: t.Any) -> str:
        return f"{value:.2f}"

    def _make_sample(
        self,
        timestamp: str,
        epoch: float,
        per_service: t.Dict[str, t.Any],
        notes: str,
    ) -> CpuUtilizationSample:
        return CpuUtilizationSample(
            timestamp=timestamp, epoch=epoch, per_service=per_service, notes=notes
        )

    def _transform_per_service(
        self, raw_per_service: t.Dict[str, t.Optional[int]], poll_wall: float
    ) -> t.Dict[str, t.Optional[float]]:
        """Turn each service's raw cumulative CPUUsageNSec into a per-interval
        CPU% via delta against the previous poll's sample."""
        wall_delta = None
        if self._last_wall is not None:
            gap = poll_wall - self._last_wall
            # A gap far longer than the poll interval (a poll timeout ate a
            # cycle) would average the delta over the whole gap, diluting a
            # real spike. Start a fresh baseline instead.
            if gap <= self.interval_sec * 3:
                wall_delta = max(1.0, gap)

        per_service_pct: t.Dict[str, t.Optional[float]] = {}
        for service in self.services:
            cpu_ns = raw_per_service.get(service)
            prev_ns = self._last_ns.get(service)
            self._last_ns[service] = cpu_ns

            if cpu_ns is None or prev_ns is None or wall_delta is None:
                per_service_pct[service] = None
                continue

            delta_ns = max(0, cpu_ns - prev_ns)
            per_service_pct[service] = (delta_ns / 1e9) / wall_delta * 100.0

        self._last_wall = poll_wall
        return per_service_pct
