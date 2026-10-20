#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Custom test handler that starts + stops OSS collectors around a test config.

Runs for EVERY test config under ``TAAC_OSS`` (see ``should_run``): continuous
CPU + memory + systemd-state sampling is part of the baseline OSS environment,
not a per-test opt-in, since the OSS path has no ODS to fall back on. Internal
mode keeps the tag-based opt-in, so the ``oss_collectors`` tag also selects
this handler there. A test config that needs collectors off — e.g. one where
the extra SSH polling would perturb what it measures — can tag itself
``no_oss_collectors``.

Runs as a sibling to the test config's own ``setup_tasks`` /
``teardown_tasks``, so it survives ``--skip-setup-tasks`` /
``--skip-teardown-tasks``.

Starts a ``CpuUtilizationCollector`` + ``MemoryUtilizationCollector`` +
``SystemdStateCollector`` per DUT in ``async_test_setUp`` and registers each
under a well-known name so the existing OSS-path health checks pick them up
and use window-based semantics instead of a single point-in-time SSH read.

Stops all in ``async_test_tearDown`` and clears the registry — critical
for tests that run back-to-back in the same runner process.

Registry key convention (matches what the health checks look for):

* ``"cpu_utilization"``  → the CPU collector
* ``"memory_utilization"`` → the memory collector
* ``"systemd_state"`` → the systemd unit-state collector
  (``UncleanExitHealthCheck`` today; future: ``SystemctlActiveState`` /
  ``ServiceRestart``)

Every DUT with ``operating_system == "FBOSS"`` gets its own collector
set, registered under the host-qualified key ``"<name>@<host>"``. The
first DUT is additionally registered under the bare name, so a consumer
that still looks up ``get_collector("cpu_utilization")`` keeps working.
"""

import os
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
    host_key,
    register_collector,
    unregister_collector,
)
from taac.libs.collectors.systemd_state_collector import (
    SystemdStateCollector,
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
        # (registry name, collector) for every slot this handler owns,
        # across every DUT -- teardown stops and unregisters exactly these.
        self._started: t.List[t.Tuple[str, t.Any]] = []

    async def async_test_setUp(self) -> None:
        if not self._fboss_devices:
            self.logger.warning(
                "CollectorsTestHandler: no FBOSS devices in test topology; "
                "skipping CPU + memory collector setup."
            )
            return

        services = list(DEFAULT_SERVICE_NAMES)
        self.logger.info(
            f"CollectorsTestHandler: starting CPU + memory + systemd-state "
            f"collectors on {self._fboss_devices} "
            f"(services={services}, interval={DEFAULT_POLL_INTERVAL_SEC}s)"
        )

        for index, dut in enumerate(self._fboss_devices):
            try:
                driver = await async_get_device_driver(dut)
            except Exception as e:
                # One unreachable pod node must not cost the DUT its
                # collectors -- the checks on that node SKIP, as they did
                # before this handler was multi-host, and the rest run.
                self.logger.warning(
                    f"CollectorsTestHandler: no driver for {dut} ({e}); "
                    "its collector-backed checks will SKIP."
                )
                continue

            for name, cls in (
                ("cpu_utilization", CpuUtilizationCollector),
                ("memory_utilization", MemoryUtilizationCollector),
                ("systemd_state", SystemdStateCollector),
            ):
                collector = cls(
                    driver=driver,
                    services=services,
                    host=dut,
                    # Default tmp_path is pid+second-stamped, so same-second
                    # starts on different hosts would share one file and
                    # interleave their rows. Key it by host instead.
                    tmp_path=f"/tmp/{name}_collector.{os.getpid()}.{dut}.log",
                    interval_sec=DEFAULT_POLL_INTERVAL_SEC,
                )
                collector.start()
                register_collector(host_key(name, dut), collector)
                self._started.append((host_key(name, dut), collector))
                if index == 0:
                    # Back-compat for consumers still reading the bare name.
                    register_collector(name, collector)
                    self._started.append((name, collector))

    async def async_test_tearDown(self) -> None:
        # Stop the collectors first, THEN unregister — stopping while they're
        # still registered ensures late queries (from a straggler postcheck)
        # at least see the final rows before the slots empty. Only this
        # handler's own keys are dropped: the registry is shared, so
        # clear_collectors() here would discard other handlers' collectors
        # and reset the runner's test-case start timestamp.
        #
        # The first DUT's collectors appear twice (host-qualified + bare), so
        # stop each object once and unregister every key.
        stopped = set()
        for _, collector in self._started:
            if id(collector) in stopped:
                continue
            stopped.add(id(collector))
            try:
                await collector.stop()
            except Exception as e:
                self.logger.warning(
                    f"CollectorsTestHandler: {type(collector).__name__} "
                    f"stop() failed for {getattr(collector, 'host', '?')}: {e}"
                )
        for name, _ in self._started:
            unregister_collector(name)
        self._started = []
