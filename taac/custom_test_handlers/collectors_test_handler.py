#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Custom test handler that starts + stops OSS collectors around a test config.

Runs for EVERY test config under ``TAAC_OSS`` (see ``should_run``): continuous
CPU + memory sampling is part of the baseline OSS environment, not a per-test
opt-in, since the OSS path has no ODS to fall back on. Internal mode keeps the
tag-based opt-in, so the ``oss_collectors`` tag also selects this handler there.
A test config that needs collectors off — e.g. one where the extra SSH polling
would perturb what it measures — can tag itself ``no_oss_collectors``.

Runs as a sibling to the test config's own ``setup_tasks`` /
``teardown_tasks``, so it survives ``--skip-setup-tasks`` /
``--skip-teardown-tasks``.

Starts a ``CpuUtilizationCollector`` + ``MemoryUtilizationCollector`` per DUT
in ``async_test_setUp`` and registers each under a well-known name so the
existing OSS-path CPU / memory health checks pick them up and use
MAX-over-window semantics instead of a single delta / single sample.

Stops both in ``async_test_tearDown`` and clears the registry — critical
for tests that run back-to-back in the same runner process.

Registry key convention (matches what the health checks look for):

* ``"cpu_utilization"``  → the CPU collector
* ``"memory_utilization"`` → the memory collector

Only the first DUT with ``operating_system == "FBOSS"`` gets collectors
attached; the health checks are per-device and only one collector is
registered per name.
"""

import typing as t

from taac.custom_test_handlers.base_custom_test_handler import (
    BaseCustomTestHandler,
)
from taac.health_checks.constants import DEFAULT_SERVICE_NAMES
from taac.libs.collectors.cpu_utilization_collector import (
    CpuUtilizationCollector,
)
from taac.libs.collectors.memory_utilization_collector import (
    MemoryUtilizationCollector,
)
from taac.libs.collectors.registry import (
    register_collector,
    unregister_collector,
)
from taac.utils.driver_factory import async_get_device_driver
from taac.utils.oss_taac_constants import TAAC_OSS


# Default poll interval — 5s keeps SSH load reasonable while still catching
# short spikes. CPU / memory don't need sub-second resolution.
DEFAULT_POLL_INTERVAL_SEC: float = 5.0

# Opt-out tag for the OSS default-on behavior, for test configs where the
# collectors' periodic SSH polling would perturb what they measure.
OPT_OUT_TAG: str = "no_oss_collectors"


class CollectorsTestHandler(BaseCustomTestHandler):
    """Start / stop the OSS CPU + memory continuous-polling collectors."""

    SUPPORTED_TAGS = ["oss_collectors"]

    @classmethod
    def should_run(cls, tags: t.List[str]) -> bool:
        """On for every OSS test config unless opted out: the OSS health checks
        have no ODS to fall back on, so without a collector they silently SKIP.
        Internal mode keeps the plain tag-based opt-in.
        """
        if OPT_OUT_TAG in tags:
            return False
        if TAAC_OSS:
            return True
        return super().should_run(tags)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._fboss_devices: t.List[str] = [
            device.name
            for device in self.test_topology.devices
            if device.attributes.operating_system == "FBOSS"
        ]
        self._cpu_collector: t.Optional[CpuUtilizationCollector] = None
        self._memory_collector: t.Optional[MemoryUtilizationCollector] = None

    async def async_test_setUp(self) -> None:
        if not self._fboss_devices:
            self.logger.warning(
                "CollectorsTestHandler: no FBOSS devices in test topology; "
                "skipping CPU + memory collector setup."
            )
            return

        # Only the first DUT gets collectors. Multi-DUT collector support is
        # out of scope for the initial wiring — each named registry slot only
        # holds one collector, and the OSS health checks target a single DUT
        # per invocation.
        dut = self._fboss_devices[0]
        driver = await async_get_device_driver(dut)
        services = list(DEFAULT_SERVICE_NAMES)

        self.logger.info(
            f"CollectorsTestHandler: starting CPU + memory collectors on {dut} "
            f"(services={services}, interval={DEFAULT_POLL_INTERVAL_SEC}s)"
        )

        cpu = CpuUtilizationCollector(
            driver=driver,
            services=services,
            host=dut,
            interval_sec=DEFAULT_POLL_INTERVAL_SEC,
        )
        cpu.start()
        register_collector("cpu_utilization", cpu)
        self._cpu_collector = cpu

        mem = MemoryUtilizationCollector(
            driver=driver,
            services=services,
            host=dut,
            interval_sec=DEFAULT_POLL_INTERVAL_SEC,
        )
        mem.start()
        register_collector("memory_utilization", mem)
        self._memory_collector = mem

    async def async_test_tearDown(self) -> None:
        # Stop the collectors first, THEN unregister — stopping while they're
        # still registered ensures late queries (from a straggler postcheck)
        # at least see the final rows before the slots empty. Only this
        # handler's own two keys are dropped: the registry is shared, so
        # clear_collectors() here would discard other handlers' collectors
        # and reset the runner's test-case start timestamp.
        if self._cpu_collector is not None:
            try:
                await self._cpu_collector.stop()
            except Exception as e:
                self.logger.warning(
                    f"CollectorsTestHandler: CPU collector stop() failed: {e}"
                )
            self._cpu_collector = None

        if self._memory_collector is not None:
            try:
                await self._memory_collector.stop()
            except Exception as e:
                self.logger.warning(
                    f"CollectorsTestHandler: memory collector stop() failed: {e}"
                )
            self._memory_collector = None

        unregister_collector("cpu_utilization")
        unregister_collector("memory_utilization")
